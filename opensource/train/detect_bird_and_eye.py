"""
两阶段检测脚本：
1. 使用YOLOv11n检测鸟
2. 裁剪出鸟的区域，使用鸟眼模型检测鸟眼
3. 在原图上画出鸟和鸟眼的检测框

支持RAW格式文件，使用内置缩略图进行检测
"""
import os
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Union
from ultralytics import YOLO

# 尝试导入rawpy用于RAW文件处理
try:
    import rawpy
    _RAWPY_AVAILABLE = True
except ImportError:
    _RAWPY_AVAILABLE = False
    print("警告: rawpy未安装，RAW文件处理功能受限。安装命令: pip install rawpy")


class BirdAndEyeDetector:
    def __init__(
        self,
        bird_model_path: str = "yolo11n.pt",
        eye_model_path: str = "best.pt",
        bird_conf: float = 0.25,
        eye_conf: float = 0.25,
        device: str = None,
    ):
        """
        初始化两阶段检测器

        Args:
            bird_model_path: 鸟类检测模型路径
            eye_model_path: 鸟眼检测模型路径
            bird_conf: 鸟类检测置信度阈值
            eye_conf: 鸟眼检测置信度阈值
            device: 运行设备 (cuda/cpu)
        """
        self.bird_conf = bird_conf
        self.eye_conf = eye_conf

        # 自动选择设备
        if device is None:
            import torch
            device = "0" if torch.cuda.is_available() else "cpu"

        print(f"加载鸟类检测模型: {bird_model_path}")
        self.bird_model = YOLO(bird_model_path)
        self.bird_model.to(device)

        print(f"加载鸟眼检测模型: {eye_model_path}")
        self.eye_model = YOLO(eye_model_path)
        self.eye_model.to(device)

        print(f"使用设备: {device}")

    @staticmethod
    def is_raw_file(file_path: str) -> bool:
        """检查文件是否为RAW格式"""
        raw_extensions = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.raf', '.pef', '.rw2'}
        return Path(file_path).suffix.lower() in raw_extensions

    @staticmethod
    def read_raw_thumbnail(file_path: str) -> np.ndarray:
        """
        读取RAW文件的内置缩略图

        Args:
            file_path: RAW文件路径

        Returns:
            OpenCV格式的图像 (BGR)
        """
        if not _RAWPY_AVAILABLE:
            raise RuntimeError("rawpy未安装，无法处理RAW文件。请运行: pip install rawpy")

        try:
            with rawpy.imread(file_path) as raw:
                # 尝试获取内置缩略图
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        # 解码JPEG缩略图
                        img_array = np.frombuffer(thumb.data, dtype=np.uint8)
                        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                        if image is not None:
                            return image
                except Exception as e:
                    print(f"  无法提取缩略图: {e}，尝试使用RAW数据")

                # 如果没有缩略图或提取失败，使用postprocess生成预览图（较低质量，较快）
                rgb = raw.postprocess(
                    half_size=True,  # 一半尺寸，加快处理
                    use_camera_wb=True,  # 使用相机白平衡
                    no_auto_bright=True,  # 不自动调整亮度
                    output_bps=8,  # 8位输出
                )
                # RGB转BGR
                image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                return image

        except Exception as e:
            raise RuntimeError(f"无法读取RAW文件 {file_path}: {e}")

    @staticmethod
    def load_image(file_path: str) -> np.ndarray:
        """
        加载图片，支持普通格式和RAW格式

        Args:
            file_path: 图片路径

        Returns:
            OpenCV格式的图像 (BGR)
        """
        if BirdAndEyeDetector.is_raw_file(file_path):
            print(f"  检测到RAW文件，使用内置缩略图")
            return BirdAndEyeDetector.read_raw_thumbnail(file_path)
        else:
            # 普通图片格式
            image = cv2.imread(file_path)
            if image is None:
                raise ValueError(f"无法读取图片: {file_path}")
            return image

    def detect_birds(self, image: np.ndarray) -> List[Dict]:
        """
        检测图片中的鸟

        Returns:
            鸟的位置列表，每个元素包含bbox和conf
        """
        results = self.bird_model(image, conf=self.bird_conf, verbose=False)
        birds = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0].cpu().numpy())
                cls = int(box.cls[0].cpu().numpy())

                birds.append({
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "conf": conf,
                    "class": cls,
                    "class_name": result.names.get(cls, "bird"),
                })

        return birds

    def detect_eyes_in_crop(
        self, crop_img: np.ndarray, offset_x: int = 0, offset_y: int = 0
    ) -> List[Dict]:
        """
        在裁剪出的鸟区域中检测鸟眼

        Args:
            crop_img: 裁剪出的鸟区域图像
            offset_x: 在原图中的x偏移量
            offset_y: 在原图中的y偏移量

        Returns:
            鸟眼位置列表（坐标是相对于原图的）
        """
        results = self.eye_model(crop_img, conf=self.eye_conf, verbose=False)
        eyes = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0].cpu().numpy())
                cls = int(box.cls[0].cpu().numpy())

                # 转换坐标到原图
                eyes.append({
                    "bbox": [
                        int(x1) + offset_x,
                        int(y1) + offset_y,
                        int(x2) + offset_x,
                        int(y2) + offset_y,
                    ],
                    "conf": conf,
                    "class": cls,
                    "class_name": result.names.get(cls, "BirdEye"),
                })

        return eyes

    def detect(self, image_path: str) -> Tuple[np.ndarray, Dict]:
        """
        对单张图片进行两阶段检测

        Args:
            image_path: 图片路径

        Returns:
            标注后的图像和检测结果字典
        """
        # 读取图片（支持RAW格式）
        image = self.load_image(image_path)

        original_image = image.copy()
        h, w = image.shape[:2]

        # 第一阶段：检测鸟
        birds = self.detect_birds(image)
        print(f"检测到 {len(birds)} 只鸟")

        all_eyes = []

        # 第二阶段：对每个鸟的区域检测鸟眼
        for i, bird in enumerate(birds):
            x1, y1, x2, y2 = bird["bbox"]

            # 裁剪出鸟的区域（稍微扩大一点范围）
            margin = 10
            crop_x1 = max(0, x1 - margin)
            crop_y1 = max(0, y1 - margin)
            crop_x2 = min(w, x2 + margin)
            crop_y2 = min(h, y2 + margin)

            bird_crop = original_image[crop_y1:crop_y2, crop_x1:crop_x2]

            if bird_crop.size == 0:
                continue

            # 检测鸟眼
            eyes = self.detect_eyes_in_crop(bird_crop, crop_x1, crop_y1)
            print(f"  鸟 {i+1}: 检测到 {len(eyes)} 个鸟眼")

            bird["eyes"] = eyes
            all_eyes.extend(eyes)

        # 在图像上画框
        result_image = self.visualize(image, birds)

        results = {
            "birds": birds,
            "total_birds": len(birds),
            "total_eyes": len(all_eyes),
        }

        return result_image, results

    def visualize(self, image: np.ndarray, birds: List[Dict]) -> np.ndarray:
        """
        在图像上画出鸟和鸟眼的检测框

        Args:
            image: 原始图像
            birds: 鸟的检测结果列表

        Returns:
            标注后的图像
        """
        result = image.copy()

        for i, bird in enumerate(birds):
            x1, y1, x2, y2 = bird["bbox"]
            conf = bird["conf"]

            # 画鸟的框（蓝色）
            cv2.rectangle(result, (x1, y1), (x2, y2), (255, 0, 0), 2)
            cv2.putText(
                result,
                f"Bird {i+1}: {conf:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 0, 0),
                2,
            )

            # 画鸟眼的框（红色）
            if "eyes" in bird:
                for j, eye in enumerate(bird["eyes"]):
                    ex1, ey1, ex2, ey2 = eye["bbox"]
                    econf = eye["conf"]

                    cv2.rectangle(result, (ex1, ey1), (ex2, ey2), (0, 0, 255), 2)
                    cv2.putText(
                        result,
                        f"Eye: {econf:.2f}",
                        (ex1, ey1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 0, 255),
                        2,
                    )

        return result


def process_folder(
    input_folder: str,
    output_folder: str,
    bird_model_path: str = "yolo11n.pt",
    eye_model_path: str = "best.pt",
):
    """
    处理整个文件夹的图片

    Args:
        input_folder: 输入图片文件夹
        output_folder: 输出结果文件夹
        bird_model_path: 鸟类检测模型路径
        eye_model_path: 鸟眼检测模型路径
    """
    # 创建输出文件夹
    os.makedirs(output_folder, exist_ok=True)

    # 初始化检测器
    detector = BirdAndEyeDetector(
        bird_model_path=bird_model_path,
        eye_model_path=eye_model_path,
    )

    # 支持的图片格式（包括RAW格式）
    image_extensions = {
        ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp",
        ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".raf", ".pef", ".rw2"
    }

    # 获取所有图片文件
    image_files = [
        f for f in Path(input_folder).iterdir()
        if f.suffix.lower() in image_extensions
    ]

    print(f"找到 {len(image_files)} 张图片")
    print("=" * 50)

    # 处理每张图片
    for i, image_path in enumerate(image_files, 1):
        print(f"\n处理 [{i}/{len(image_files)}]: {image_path.name}")

        try:
            result_image, results = detector.detect(str(image_path))

            # 保存结果为JPG格式
            base_name = image_path.stem  # 获取文件名（不含扩展名）
            output_filename = f"detected_{base_name}.jpg"
            output_path = os.path.join(output_folder, output_filename)

            # 使用JPEG格式保存，质量95%
            cv2.imwrite(output_path, result_image, [cv2.IMWRITE_JPEG_QUALITY, 95])

            print(f"  结果: {results['total_birds']} 只鸟, {results['total_eyes']} 个鸟眼")
            print(f"  保存至: {output_path}")

        except Exception as e:
            print(f"  错误: {e}")

    print("\n" + "=" * 50)
    print(f"处理完成！结果保存在: {output_folder}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="鸟和鸟眼两阶段检测")
    parser.add_argument(
        "--input",
        type=str,
        default=r"D:\BaiduNetdiskDownload\temp\test",
        help="输入图片文件夹",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=r"D:\BaiduNetdiskDownload\temp\test\detected",
        help="输出结果文件夹",
    )
    parser.add_argument(
        "--bird-model",
        type=str,
        default="yolo11n.pt",
        help="鸟类检测模型路径",
    )
    parser.add_argument(
        "--eye-model",
        type=str,
        default="best.pt",
        help="鸟眼检测模型路径",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="单张图片路径（如果指定则只处理单张）",
    )

    args = parser.parse_args()

    if args.image:
        # 单张图片处理
        detector = BirdAndEyeDetector(
            bird_model_path=args.bird_model,
            eye_model_path=args.eye_model,
        )

        print(f"处理单张图片: {args.image}")
        result_image, results = detector.detect(args.image)

        # 保存结果为JPG格式
        os.makedirs(args.output, exist_ok=True)
        image_path_obj = Path(args.image)
        output_filename = f"detected_{image_path_obj.stem}.jpg"
        output_path = os.path.join(args.output, output_filename)

        # 使用JPEG格式保存，质量95%
        cv2.imwrite(output_path, result_image, [cv2.IMWRITE_JPEG_QUALITY, 95])

        print(f"\n检测完成!")
        print(f"  鸟数量: {results['total_birds']}")
        print(f"  鸟眼数量: {results['total_eyes']}")
        print(f"  结果保存: {output_path}")
    else:
        # 批量处理文件夹
        process_folder(
            input_folder=args.input,
            output_folder=args.output,
            bird_model_path=args.bird_model,
            eye_model_path=args.eye_model,
        )
