"""
YOLOv11n 鸟眼识别模型训练脚本
"""
from ultralytics import YOLO
import os
import torch


def train_birdeye_model(
    data_yaml_path: str = "data.yaml",
    model_size: str = "yolo11n.pt",
    epochs: int = 100,
    batch_size: int = 16,
    image_size: int = 640,
    device: str = None,
    project: str = "runs/train",
    name: str = "birdeye_yolo11n",
    patience: int = 20,
    save_period: int = 10,
):
    """
    训练YOLOv11n鸟眼识别模型

    Args:
        data_yaml_path: 数据集配置文件路径
        model_size: 预训练模型，默认 yolo11n.pt (nano版本，最轻量)
        epochs: 训练轮数
        batch_size: 批次大小，根据显存调整
        image_size: 输入图像尺寸
        device: 训练设备，None则自动选择
        project: 训练结果保存目录
        name: 训练任务名称
        patience: 早停耐心值
        save_period: 每多少轮保存一次模型
    """

    # 自动选择设备
    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"
        print(f"自动选择设备: {'GPU' if device == 0 else 'CPU'}")

    # 加载预训练模型
    print(f"加载模型: {model_size}")
    model = YOLO(model_size)

    # 开始训练
    print(f"\n开始训练...")
    print(f"数据集: {data_yaml_path}")
    print(f"训练轮数: {epochs}")
    print(f"批次大小: {batch_size}")
    print(f"图像尺寸: {image_size}")
    print(f"设备: {device}")

    results = model.train(
        data=data_yaml_path,
        epochs=epochs,
        batch=batch_size,
        imgsz=image_size,
        device=device,
        project=project,
        name=name,
        patience=patience,
        save_period=save_period,
        # 数据增强参数
        augment=True,
        mosaic=1.0,
        mixup=0.0,
        copy_paste=0.0,
        # 优化器参数
        optimizer="AdamW",
        lr0=0.01,
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=3.0,
        # 其他参数
        cos_lr=True,
        close_mosaic=10,
        box=7.5,
        cls=0.5,
        dfl=1.5,
        val=True,
        plots=True,
    )

    print(f"\n训练完成!")
    best_model_path = os.path.join(project, name, "weights/best.pt")
    print(f"最佳模型路径: {best_model_path}")
    print(f"训练结果保存至: {os.path.join(project, name)}")
    
    # 打印训练结果摘要
    if hasattr(results, 'results_dict'):
        print(f"\n训练结果摘要:")
        for key, value in results.results_dict.items():
            print(f"  {key}: {value}")

    return results


def validate_model(model_path: str, data_yaml_path: str = "data.yaml"):
    """
    验证训练好的模型

    Args:
        model_path: 模型路径
        data_yaml_path: 数据集配置文件路径
    """
    print(f"\n验证模型: {model_path}")
    model = YOLO(model_path)
    metrics = model.val(data=data_yaml_path)

    print(f"\n验证结果:")
    print(f"mAP50: {metrics.box.map50:.4f}")
    print(f"mAP50-95: {metrics.box.map:.4f}")
    print(f"Precision: {metrics.box.p:.4f}")
    print(f"Recall: {metrics.box.r:.4f}")

    return metrics


def export_model(model_path: str, format: str = "onnx"):
    """
    导出模型为其他格式

    Args:
        model_path: 模型路径
        format: 导出格式 (onnx, torchscript, engine等)
    """
    print(f"\n导出模型: {model_path} -> {format}")
    model = YOLO(model_path)
    model.export(format=format)
    print(f"导出完成!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="YOLOv11n 鸟眼识别模型训练")
    parser.add_argument("--data", type=str, default="data.yaml", help="数据集配置文件路径")
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数")
    parser.add_argument("--batch", type=int, default=16, help="批次大小")
    parser.add_argument("--imgsz", type=int, default=640, help="图像尺寸")
    parser.add_argument("--device", type=str, default=None, help="训练设备 (0, 1, cpu等)")
    parser.add_argument("--name", type=str, default="birdeye_yolo11n", help="训练任务名称")
    parser.add_argument("--model", type=str, default="yolo11n.pt", help="预训练模型")
    parser.add_argument("--val-only", action="store_true", help="仅验证模式")
    parser.add_argument("--export", type=str, default=None, help="导出格式 (onnx, engine等)")

    args = parser.parse_args()

    if args.val_only:
        # 仅验证
        best_model = os.path.join("runs/train", args.name, "weights/best.pt")
        if os.path.exists(best_model):
            validate_model(best_model, args.data)
        else:
            print(f"未找到模型: {best_model}")
    elif args.export:
        # 导出模型
        best_model = os.path.join("runs/train", args.name, "weights/best.pt")
        if os.path.exists(best_model):
            export_model(best_model, args.export)
        else:
            print(f"未找到模型: {best_model}")
    else:
        # 训练模型
        results = train_birdeye_model(
            data_yaml_path=args.data,
            model_size=args.model,
            epochs=args.epochs,
            batch_size=args.batch,
            image_size=args.imgsz,
            device=args.device,
            name=args.name,
        )
