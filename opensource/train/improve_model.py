"""
使用新数据集改进当前鸟眼检测模型
支持增量训练和迁移学习
"""
import os
import shutil
from pathlib import Path
from typing import List, Tuple
import yaml
from ultralytics import YOLO


def merge_datasets(
    original_dataset_path: str,
    new_dataset_path: str,
    output_path: str = "merged_dataset",
) -> str:
    """
    合并原始数据集和新数据集

    Args:
        original_dataset_path: 原始数据集路径
        new_dataset_path: 新数据集路径
        output_path: 合并后的数据集输出路径

    Returns:
        合并后数据集的路径
    """
    print("=" * 50)
    print("合并数据集")
    print("=" * 50)

    # 创建输出目录结构
    merged_images = Path(output_path) / "images"
    merged_labels = Path(output_path) / "labels"
    merged_images.mkdir(parents=True, exist_ok=True)
    merged_labels.mkdir(parents=True, exist_ok=True)

    # 复制原始数据集
    original_images = Path(original_dataset_path) / "images"
    original_labels = Path(original_dataset_path) / "labels"

    if original_images.exists():
        print(f"复制原始数据集图片...")
        for img in original_images.iterdir():
            if img.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']:
                shutil.copy2(img, merged_images / img.name)

    if original_labels.exists():
        print(f"复制原始数据集标注...")
        for lbl in original_labels.iterdir():
            if lbl.suffix == '.txt':
                shutil.copy2(lbl, merged_labels / lbl.name)

    # 复制新数据集
    new_images = Path(new_dataset_path) / "images"
    new_labels = Path(new_dataset_path) / "labels"

    if new_images.exists():
        print(f"复制新数据集图片...")
        for img in new_images.iterdir():
            if img.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']:
                # 如果文件名冲突，添加前缀
                dest = merged_images / img.name
                if dest.exists():
                    dest = merged_images / f"new_{img.name}"
                shutil.copy2(img, dest)

    if new_labels.exists():
        print(f"复制新数据集标注...")
        for lbl in new_labels.iterdir():
            if lbl.suffix == '.txt':
                # 如果文件名冲突，添加前缀
                dest = merged_labels / lbl.name
                if dest.exists():
                    dest = merged_labels / f"new_{lbl.name}"
                shutil.copy2(lbl, dest)

    # 复制classes.txt
    for src_path in [Path(new_dataset_path) / "classes.txt", Path(original_dataset_path) / "classes.txt"]:
        if src_path.exists():
            shutil.copy2(src_path, Path(output_path) / "classes.txt")
            break

    # 统计
    img_count = len(list(merged_images.iterdir()))
    lbl_count = len(list(merged_labels.iterdir()))
    print(f"\n合并完成!")
    print(f"  总图片数: {img_count}")
    print(f"  总标注数: {lbl_count}")
    print(f"  保存路径: {output_path}")

    return output_path


def split_dataset(
    dataset_path: str,
    train_ratio: float = 0.8,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> Tuple[List[str], List[str]]:
    """
    将数据集划分为训练集和验证集

    Args:
        dataset_path: 数据集路径
        train_ratio: 训练集比例
        val_ratio: 验证集比例
        seed: 随机种子

    Returns:
        训练集和验证集的文件列表
    """
    import random

    images_dir = Path(dataset_path) / "images"
    all_images = [
        f.name for f in images_dir.iterdir()
        if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp']
    ]

    random.seed(seed)
    random.shuffle(all_images)

    train_size = int(len(all_images) * train_ratio)
    train_files = all_images[:train_size]
    val_files = all_images[train_size:]

    return train_files, val_files


def create_data_yaml(
    dataset_path: str,
    train_files: List[str],
    val_files: List[str],
    output_path: str = "data_merged.yaml",
) -> str:
    """
    创建合并后的数据集配置文件

    Args:
        dataset_path: 数据集路径
        train_files: 训练集文件列表
        val_files: 验证集文件列表
        output_path: 输出配置文件路径

    Returns:
        配置文件路径
    """
    # 读取类别信息
    classes_file = Path(dataset_path) / "classes.txt"
    if classes_file.exists():
        with open(classes_file, 'r', encoding='utf-8') as f:
            class_names = [line.strip() for line in f if line.strip()]
    else:
        class_names = ["BirdEye"]

    # 创建train.txt和val.txt
    dataset_path_obj = Path(dataset_path)

    train_txt = dataset_path_obj / "train.txt"
    with open(train_txt, 'w', encoding='utf-8') as f:
        for fname in train_files:
            img_path = dataset_path_obj / "images" / fname
            f.write(str(img_path.absolute()) + '\n')

    val_txt = dataset_path_obj / "val.txt"
    with open(val_txt, 'w', encoding='utf-8') as f:
        for fname in val_files:
            img_path = dataset_path_obj / "images" / fname
            f.write(str(img_path.absolute()) + '\n')

    # 创建data.yaml
    data_config = {
        'path': str(dataset_path_obj.absolute()),
        'train': str(train_txt.absolute()),
        'val': str(val_txt.absolute()),
        'nc': len(class_names),
        'names': {i: name for i, name in enumerate(class_names)}
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(data_config, f, allow_unicode=True, sort_keys=False)

    print(f"\n数据集配置已保存: {output_path}")
    print(f"  训练集: {len(train_files)} 张")
    print(f"  验证集: {len(val_files)} 张")
    print(f"  类别数: {len(class_names)}")

    return output_path


def incremental_train(
    current_model_path: str = "best.pt",
    new_dataset_path: str = None,
    original_dataset_path: str = "dataset",
    output_name: str = "birdeye_improved",
    epochs: int = 50,
    batch_size: int = 16,
    image_size: int = 640,
    freeze_layers: int = 10,
    device: str = None,
):
    """
    使用新数据集进行增量训练（迁移学习）

    Args:
        current_model_path: 当前模型路径
        new_dataset_path: 新数据集路径（如果为None则只使用原始数据集）
        original_dataset_path: 原始数据集路径
        output_name: 输出模型名称
        epochs: 训练轮数
        batch_size: 批次大小
        image_size: 图像尺寸
        freeze_layers: 冻结前N层（保留预训练特征）
        device: 训练设备
    """
    print("=" * 50)
    print("开始增量训练")
    print("=" * 50)

    # 自动选择设备
    if device is None:
        import torch
        device = 0 if torch.cuda.is_available() else "cpu"

    # 准备数据集
    if new_dataset_path and Path(new_dataset_path).exists():
        print("\n合并新旧数据集...")
        merged_path = merge_datasets(original_dataset_path, new_dataset_path, "merged_dataset")
    else:
        print("\n使用原始数据集...")
        merged_path = original_dataset_path

    # 划分数据集
    print("\n划分训练集和验证集...")
    train_files, val_files = split_dataset(merged_path, train_ratio=0.8, val_ratio=0.2)

    # 创建配置文件
    data_yaml = create_data_yaml(merged_path, train_files, val_files, "data_improved.yaml")

    # 加载当前模型作为预训练权重
    print(f"\n加载预训练模型: {current_model_path}")
    model = YOLO(current_model_path)

    print(f"\n开始训练...")
    print(f"  模型: {current_model_path}")
    print(f"  轮数: {epochs}")
    print(f"  批次: {batch_size}")
    print(f"  冻结层数: {freeze_layers}")
    print(f"  设备: {device}")

    # 开始训练
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        batch=batch_size,
        imgsz=image_size,
        device=device,
        project="runs/improve",
        name=output_name,
        patience=15,
        save_period=10,
        # 冻结前N层，保留预训练特征
        freeze=freeze_layers,
        # 使用较低学习率进行微调
        lr0=0.001,
        lrf=0.01,
        # 数据增强
        augment=True,
        mosaic=1.0,
        mixup=0.1,
        # 优化器
        optimizer="AdamW",
        warmup_epochs=3.0,
        # 验证和绘图
        val=True,
        plots=True,
    )

    print(f"\n训练完成!")
    print(f"改进后的模型保存在: runs/improve/{output_name}/weights/best.pt")

    return results


def validate_improved_model(
    model_path: str = "runs/improve/birdeye_improved/weights/best.pt",
    test_images_path: str = None,
):
    """
    验证改进后的模型

    Args:
        model_path: 改进后的模型路径
        test_images_path: 测试图片路径
    """
    print("=" * 50)
    print("验证改进后的模型")
    print("=" * 50)

    if not Path(model_path).exists():
        print(f"模型不存在: {model_path}")
        return

    model = YOLO(model_path)

    # 在验证集上评估
    print("\n在验证集上评估...")
    metrics = model.val()

    print(f"\n验证结果:")
    print(f"  mAP50: {metrics.box.map50:.4f}")
    print(f"  mAP50-95: {metrics.box.map:.4f}")
    print(f"  Precision: {metrics.box.p:.4f}")
    print(f"  Recall: {metrics.box.r:.4f}")

    # 如果有测试图片，进行预测对比
    if test_images_path and Path(test_images_path).exists():
        print(f"\n在测试图片上预测...")
        results = model(test_images_path, save=True, project="runs/improve", name="test_results")
        print(f"预测结果保存在: runs/improve/test_results")

    return metrics


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="改进鸟眼检测模型")
    parser.add_argument(
        "--mode",
        type=str,
        default="train",
        choices=["train", "merge", "validate"],
        help="操作模式: train(训练), merge(合并数据集), validate(验证)",
    )
    parser.add_argument(
        "--current-model",
        type=str,
        default="best.pt",
        help="当前模型路径",
    )
    parser.add_argument(
        "--new-dataset",
        type=str,
        default=None,
        help="新数据集路径",
    )
    parser.add_argument(
        "--original-dataset",
        type=str,
        default="dataset",
        help="原始数据集路径",
    )
    parser.add_argument(
        "--output-name",
        type=str,
        default="birdeye_improved",
        help="输出模型名称",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
        help="训练轮数",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=16,
        help="批次大小",
    )
    parser.add_argument(
        "--freeze",
        type=int,
        default=10,
        help="冻结层数",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="训练设备",
    )

    args = parser.parse_args()

    if args.mode == "train":
        # 增量训练
        incremental_train(
            current_model_path=args.current_model,
            new_dataset_path=args.new_dataset,
            original_dataset_path=args.original_dataset,
            output_name=args.output_name,
            epochs=args.epochs,
            batch_size=args.batch,
            freeze_layers=args.freeze,
            device=args.device,
        )

    elif args.mode == "merge":
        # 仅合并数据集
        if args.new_dataset:
            merge_datasets(args.original_dataset, args.new_dataset, "merged_dataset")
        else:
            print("请指定 --new-dataset 参数")

    elif args.mode == "validate":
        # 验证模型
        validate_improved_model(
            model_path=args.current_model,
            test_images_path=args.new_dataset,  # 这里用new_dataset参数传入测试图片路径
        )
