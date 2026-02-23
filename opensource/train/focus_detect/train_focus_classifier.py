"""
鸟图对焦分类模型训练脚本
使用YOLO11-cls模型训练 Focus/NotFocus/MotionBlur/Noise 四分类
"""
import os
import torch
from pathlib import Path
from ultralytics import YOLO
from typing import Dict, List, Optional
import json


# 类别定义
CLASSES = ["Focus", "NotFocus", "MotionBlur", "Noise"]
CLASS_NAMES_CN = {
    "Focus": "对焦清晰",
    "NotFocus": "失焦",
    "MotionBlur": "运动模糊",
    "Noise": "噪点过多"
}


def train_focus_classifier(
    data_path: str = "classification_dataset",
    model_size: str = "yolo11n-cls.pt",  # nano版本，轻量快速
    epochs: int = 100,
    batch_size: int = 32,
    image_size: int = 224,  # 分类模型通常使用224x224
    device: str = None,
    project: str = "runs/classify",
    name: str = "bird_focus_classifier",
    patience: int = 20,
    lr0: float = 0.001,
    lrf: float = 0.01,
    optimizer: str = "AdamW",
    seed: int = 42,
    pretrained: bool = True,
    augment: bool = True,
) -> Dict:
    """
    训练鸟图对焦分类模型

    Args:
        data_path: 数据集路径（YOLO-cls格式）
        model_size: 模型大小 (yolo11n-cls.pt, yolo11s-cls.pt, yolo11m-cls.pt)
        epochs: 训练轮数
        batch_size: 批次大小
        image_size: 输入图像尺寸
        device: 训练设备
        project: 项目保存路径
        name: 训练任务名称
        patience: 早停耐心值
        lr0: 初始学习率
        lrf: 最终学习率因子
        optimizer: 优化器
        seed: 随机种子
        pretrained: 是否使用预训练权重
        augment: 是否使用数据增强

    Returns:
        训练结果字典
    """
    print("=" * 60)
    print("鸟图对焦分类模型训练")
    print("=" * 60)

    # 自动选择设备
    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"
        print(f"自动选择设备: {'GPU' if device == 0 else 'CPU'}")

    print(f"\n训练配置:")
    print(f"  数据集: {data_path}")
    print(f"  模型: {model_size}")
    print(f"  轮数: {epochs}")
    print(f"  批次: {batch_size}")
    print(f"  图像尺寸: {image_size}")
    print(f"  学习率: {lr0}")
    print(f"  优化器: {optimizer}")
    print(f"  设备: {device}")
    print(f"  类别: {CLASSES}")

    # 加载预训练模型
    print(f"\n加载模型: {model_size}")
    model = YOLO(model_size)

    # 开始训练
    print(f"\n开始训练...")
    results = model.train(
        data=data_path,
        epochs=epochs,
        batch=batch_size,
        imgsz=image_size,
        device=device,
        project=project,
        name=name,
        patience=patience,
        lr0=lr0,
        lrf=lrf,
        optimizer=optimizer,
        seed=seed,
        pretrained=pretrained,
        augment=augment,
        # 分类任务特定参数
        cos_lr=True,
        dropout=0.2,  # 防止过拟合
        # 数据增强参数
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=15,  # 随机旋转
        translate=0.1,
        scale=0.5,
        shear=5,
        flipud=0.0,
        fliplr=0.5,
        mosaic=0.0,  # 分类任务不使用mosaic
        mixup=0.0,   # 分类任务不使用mixup
        # 保存和验证
        save=True,
        save_period=10,
        val=True,
        plots=True,
    )

    print(f"\n训练完成!")
    print(f"最佳模型: {project}/{name}/weights/best.pt")

    # 保存训练信息
    training_info = {
        "model": model_size,
        "epochs": epochs,
        "batch_size": batch_size,
        "image_size": image_size,
        "classes": CLASSES,
        "class_names_cn": CLASS_NAMES_CN,
        "best_model_path": f"{project}/{name}/weights/best.pt",
    }

    info_path = f"{project}/{name}/training_info.json"
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(training_info, f, ensure_ascii=False, indent=2)

    print(f"训练信息已保存: {info_path}")

    return results


def validate_classifier(
    model_path: str,
    data_path: str = "classification_dataset",
    split: str = "test",
    device: str = None,
) -> Dict:
    """
    验证分类模型

    Args:
        model_path: 模型路径
        data_path: 数据集路径
        split: 验证的数据集划分 (train/val/test)
        device: 运行设备

    Returns:
        验证结果字典
    """
    print("=" * 60)
    print("验证分类模型")
    print("=" * 60)

    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"

    print(f"模型: {model_path}")
    print(f"数据集: {data_path}/{split}")

    # 加载模型
    model = YOLO(model_path)

    # 验证
    results = model.val(
        data=data_path,
        split=split,
        device=device,
    )

    # 打印结果
    print("\n验证结果:")
    if hasattr(results, 'top1'):
        print(f"  Top-1 准确率: {results.top1:.4f}")
    if hasattr(results, 'top5'):
        print(f"  Top-5 准确率: {results.top5:.4f}")

    return results


def predict_single_image(
    model_path: str,
    image_path: str,
    device: str = None,
) -> Dict:
    """
    对单张图片进行预测

    Args:
        model_path: 模型路径
        image_path: 图片路径
        device: 运行设备

    Returns:
        预测结果字典
    """
    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"

    # 加载模型
    model = YOLO(model_path)

    # 预测
    results = model(image_path, device=device)

    # 解析结果
    result = results[0]
    probs = result.probs

    # 获取预测结果
    pred_class_idx = probs.top1
    pred_class = result.names[pred_class_idx]
    confidence = probs.top1conf.item()

    # 获取所有类别的概率
    all_probs = {}
    for i, cls_name in result.names.items():
        all_probs[cls_name] = probs.data[i].item()

    output = {
        "image": image_path,
        "predicted_class": pred_class,
        "predicted_class_cn": CLASS_NAMES_CN.get(pred_class, pred_class),
        "confidence": confidence,
        "all_probabilities": all_probs,
    }

    print(f"\n预测结果:")
    print(f"  图片: {image_path}")
    print(f"  预测类别: {pred_class} ({CLASS_NAMES_CN.get(pred_class, pred_class)})")
    print(f"  置信度: {confidence:.4f}")
    print(f"\n各类别概率:")
    for cls, prob in sorted(all_probs.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cls} ({CLASS_NAMES_CN.get(cls, cls)}): {prob:.4f}")

    return output


def predict_batch(
    model_path: str,
    image_folder: str,
    output_folder: str = "classification_results",
    device: str = None,
) -> List[Dict]:
    """
    批量预测图片

    Args:
        model_path: 模型路径
        image_folder: 图片文件夹
        output_folder: 结果输出文件夹
        device: 运行设备

    Returns:
        所有预测结果列表
    """
    import shutil
    from collections import defaultdict

    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"

    print("=" * 60)
    print("批量预测")
    print("=" * 60)

    # 加载模型
    model = YOLO(model_path)

    # 获取所有图片
    image_paths = []
    for ext in ["*.jpg", "*.jpeg", "*.png", "*.bmp"]:
        image_paths.extend(Path(image_folder).glob(ext))
        image_paths.extend(Path(image_folder).glob(ext.upper()))

    print(f"找到 {len(image_paths)} 张图片")

    # 创建输出目录
    for cls in CLASSES:
        (Path(output_folder) / cls).mkdir(parents=True, exist_ok=True)

    # 统计
    class_counts = defaultdict(int)
    all_results = []

    # 批量预测
    for i, img_path in enumerate(image_paths, 1):
        print(f"\n处理 [{i}/{len(image_paths)}]: {img_path.name}")

        try:
            results = model(str(img_path), device=device, verbose=False)
            result = results[0]

            pred_class_idx = result.probs.top1
            pred_class = result.names[pred_class_idx]
            confidence = result.probs.top1conf.item()

            # 保存结果
            output_result = {
                "image": str(img_path),
                "filename": img_path.name,
                "predicted_class": pred_class,
                "predicted_class_cn": CLASS_NAMES_CN.get(pred_class, pred_class),
                "confidence": confidence,
            }
            all_results.append(output_result)

            # 复制到对应类别文件夹
            dest_path = Path(output_folder) / pred_class / img_path.name
            shutil.copy2(img_path, dest_path)

            class_counts[pred_class] += 1

            print(f"  预测: {pred_class} ({confidence:.4f})")

        except Exception as e:
            print(f"  错误: {e}")

    # 保存预测结果到JSON
    json_path = Path(output_folder) / "predictions.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # 打印统计
    print("\n" + "=" * 60)
    print("预测统计")
    print("=" * 60)
    for cls in CLASSES:
        count = class_counts[cls]
        percentage = (count / len(image_paths)) * 100 if image_paths else 0
        print(f"  {cls} ({CLASS_NAMES_CN[cls]}): {count} 张 ({percentage:.1f}%)")

    print(f"\n结果已保存到: {output_folder}")
    print(f"预测详情: {json_path}")

    return all_results


def export_model(
    model_path: str,
    format: str = "onnx",
    imgsz: int = 224,
):
    """
    导出模型为其他格式

    Args:
        model_path: 模型路径
        format: 导出格式 (onnx, torchscript, engine等)
        imgsz: 输入图像尺寸
    """
    print(f"\n导出模型: {model_path} -> {format}")
    model = YOLO(model_path)
    model.export(format=format, imgsz=imgsz)
    print(f"导出完成!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="鸟图对焦分类模型训练")
    parser.add_argument(
        "--mode",
        type=str,
        default="train",
        choices=["train", "val", "predict", "batch", "export"],
        help="操作模式",
    )
    parser.add_argument(
        "--data",
        type=str,
        default="classification_dataset",
        help="数据集路径",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolo11n-cls.pt",
        help="模型类型或路径",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=100,
        help="训练轮数",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=32,
        help="批次大小",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=224,
        help="图像尺寸",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="训练设备",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="bird_focus_classifier",
        help="训练任务名称",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="单张图片路径（预测模式）",
    )
    parser.add_argument(
        "--folder",
        type=str,
        default=None,
        help="图片文件夹路径（批量预测模式）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="classification_results",
        help="输出目录",
    )
    parser.add_argument(
        "--export-format",
        type=str,
        default="onnx",
        help="导出格式",
    )

    args = parser.parse_args()

    if args.mode == "train":
        # 训练模型
        train_focus_classifier(
            data_path=args.data,
            model_size=args.model,
            epochs=args.epochs,
            batch_size=args.batch,
            image_size=args.imgsz,
            device=args.device,
            name=args.name,
        )

    elif args.mode == "val":
        # 验证模型
        validate_classifier(
            model_path=args.model,
            data_path=args.data,
            device=args.device,
        )

    elif args.mode == "predict":
        # 单张预测
        if not args.image:
            print("请指定 --image 参数")
        else:
            predict_single_image(
                model_path=args.model,
                image_path=args.image,
                device=args.device,
            )

    elif args.mode == "batch":
        # 批量预测
        if not args.folder:
            print("请指定 --folder 参数")
        else:
            predict_batch(
                model_path=args.model,
                image_folder=args.folder,
                output_folder=args.output,
                device=args.device,
            )

    elif args.mode == "export":
        # 导出模型
        export_model(
            model_path=args.model,
            format=args.export_format,
            imgsz=args.imgsz,
        )
