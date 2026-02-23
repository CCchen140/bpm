"""
鸟图对焦分类数据集准备脚本
将原始图片按 Focus/NotFocus/MotionBlur/Noise 分类整理为YOLO-cls格式
"""
import os
import shutil
from pathlib import Path
from typing import Dict, List
import random


# 分类类别
CLASSES = ["Focus", "NotFocus", "MotionBlur", "Noise"]


def prepare_classification_dataset(
    source_dir: str,
    output_dir: str = "classification_dataset",
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 42,
) -> str:
    """
    准备分类数据集，整理为YOLO-cls格式

    期望的原始目录结构:
    source_dir/
    ├── Focus/          # 对焦清晰的图片
    ├── NotFocus/       # 失焦的图片
    ├── MotionBlur/     # 运动模糊的图片
    └── Noise/          # 噪点过多的图片

    输出的YOLO-cls格式:
    output_dir/
    ├── train/
    │   ├── Focus/
    │   ├── NotFocus/
    │   ├── MotionBlur/
    │   └── Noise/
    ├── val/
    │   ├── Focus/
    │   ├── NotFocus/
    │   ├── MotionBlur/
    │   └── Noise/
    └── test/
        ├── Focus/
        ├── NotFocus/
        ├── MotionBlur/
        └── Noise/

    Args:
        source_dir: 原始数据目录
        output_dir: 输出目录
        train_ratio: 训练集比例
        val_ratio: 验证集比例
        test_ratio: 测试集比例
        seed: 随机种子

    Returns:
        数据集根目录路径
    """
    assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6, "比例之和必须等于1"

    random.seed(seed)

    print("=" * 60)
    print("准备鸟图对焦分类数据集")
    print("=" * 60)
    print(f"\n原始数据目录: {source_dir}")
    print(f"输出目录: {output_dir}")
    print(f"训练集: {train_ratio*100:.0f}%, 验证集: {val_ratio*100:.0f}%, 测试集: {test_ratio*100:.0f}%")

    # 创建输出目录结构
    splits = ["train", "val", "test"]
    for split in splits:
        for cls in CLASSES:
            (Path(output_dir) / split / cls).mkdir(parents=True, exist_ok=True)

    # 统计信息
    stats = {cls: 0 for cls in CLASSES}
    split_stats = {split: {cls: 0 for cls in CLASSES} for split in splits}

    # 处理每个类别
    for cls in CLASSES:
        class_dir = Path(source_dir) / cls
        if not class_dir.exists():
            print(f"\n警告: 类别目录不存在 {class_dir}")
            continue

        # 获取该类别所有图片
        images = []
        for ext in [".jpg", ".jpeg", ".png", ".bmp", ".webp"]:
            images.extend(class_dir.glob(f"*{ext}"))
            images.extend(class_dir.glob(f"*{ext.upper()}"))

        # 去重并排序
        images = sorted(list(set(images)))
        total = len(images)
        stats[cls] = total

        if total == 0:
            print(f"\n警告: 类别 {cls} 没有图片")
            continue

        print(f"\n处理类别 {cls}: {total} 张图片")

        # 随机打乱
        random.shuffle(images)

        # 划分数据集
        train_end = int(total * train_ratio)
        val_end = train_end + int(total * val_ratio)

        train_images = images[:train_end]
        val_images = images[train_end:val_end]
        test_images = images[val_end:]

        # 复制图片到对应目录
        for img in train_images:
            shutil.copy2(img, Path(output_dir) / "train" / cls / img.name)
            split_stats["train"][cls] += 1

        for img in val_images:
            shutil.copy2(img, Path(output_dir) / "val" / cls / img.name)
            split_stats["val"][cls] += 1

        for img in test_images:
            shutil.copy2(img, Path(output_dir) / "test" / cls / img.name)
            split_stats["test"][cls] += 1

    # 打印统计信息
    print("\n" + "=" * 60)
    print("数据集统计")
    print("=" * 60)

    print("\n各类别总数:")
    for cls in CLASSES:
        print(f"  {cls}: {stats[cls]} 张")

    print("\n训练集分布:")
    for cls in CLASSES:
        print(f"  {cls}: {split_stats['train'][cls]} 张")

    print("\n验证集分布:")
    for cls in CLASSES:
        print(f"  {cls}: {split_stats['val'][cls]} 张")

    print("\n测试集分布:")
    for cls in CLASSES:
        print(f"  {cls}: {split_stats['test'][cls]} 张")

    # 创建数据集配置文件
    create_dataset_yaml(output_dir)

    print(f"\n数据集准备完成！")
    print(f"保存路径: {output_dir}")

    return output_dir


def create_dataset_yaml(dataset_dir: str, output_path: str = "classification_data.yaml"):
    """
    创建分类数据集的配置文件

    Args:
        dataset_dir: 数据集根目录
        output_path: 配置文件输出路径
    """
    config = f"""# 鸟图对焦分类数据集配置
path: {Path(dataset_dir).absolute()}  # 数据集根目录
train: train  # 训练集目录
val: val      # 验证集目录
test: test    # 测试集目录

# 类别
nc: {len(CLASSES)}  # 类别数量
names: {CLASSES}    # 类别名称

# 类别说明:
# Focus: 对焦清晰
# NotFocus: 失焦/模糊
# MotionBlur: 运动模糊
# Noise: 噪点过多
"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(config)

    print(f"\n配置文件已创建: {output_path}")


def check_dataset(dataset_dir: str) -> Dict:
    """
    检查数据集完整性

    Args:
        dataset_dir: 数据集目录

    Returns:
        统计信息字典
    """
    print("\n" + "=" * 60)
    print("检查数据集")
    print("=" * 60)

    stats = {}
    for split in ["train", "val", "test"]:
        split_dir = Path(dataset_dir) / split
        if not split_dir.exists():
            print(f"警告: 目录不存在 {split_dir}")
            continue

        stats[split] = {}
        total_images = 0

        for cls in CLASSES:
            class_dir = split_dir / cls
            if not class_dir.exists():
                print(f"警告: 类别目录不存在 {class_dir}")
                stats[split][cls] = 0
                continue

            images = list(class_dir.glob("*.jpg")) + \
                     list(class_dir.glob("*.jpeg")) + \
                     list(class_dir.glob("*.png"))

            count = len(images)
            stats[split][cls] = count
            total_images += count

        stats[split]["total"] = total_images
        print(f"{split}: {total_images} 张图片")

    return stats


def balance_dataset(
    dataset_dir: str,
    target_count: int = None,
    method: str = "undersample",
) -> str:
    """
    平衡数据集（解决类别不平衡问题）

    Args:
        dataset_dir: 数据集目录
        target_count: 目标数量（每类），None则使用最小类的数量
        method: 平衡方法 (undersample-欠采样, oversample-过采样)

    Returns:
        平衡后的数据集路径
    """
    print("\n" + "=" * 60)
    print("平衡数据集")
    print("=" * 60)

    output_dir = f"{dataset_dir}_balanced"

    # 统计各类别数量
    class_counts = {}
    for cls in CLASSES:
        train_dir = Path(dataset_dir) / "train" / cls
        if train_dir.exists():
            count = len(list(train_dir.glob("*.jpg"))) + \
                    len(list(train_dir.glob("*.jpeg"))) + \
                    len(list(train_dir.glob("*.png")))
            class_counts[cls] = count

    if not class_counts:
        print("错误: 没有找到训练数据")
        return dataset_dir

    # 确定目标数量
    if target_count is None:
        target_count = min(class_counts.values())

    print(f"目标数量: 每类 {target_count} 张")
    print(f"当前数量: {class_counts}")

    # 创建输出目录
    for split in ["train", "val", "test"]:
        for cls in CLASSES:
            (Path(output_dir) / split / cls).mkdir(parents=True, exist_ok=True)

    # 处理每个split
    for split in ["train", "val", "test"]:
        for cls in CLASSES:
            src_dir = Path(dataset_dir) / split / cls
            dst_dir = Path(output_dir) / split / cls

            if not src_dir.exists():
                continue

            images = list(src_dir.glob("*.jpg")) + \
                     list(src_dir.glob("*.jpeg")) + \
                     list(src_dir.glob("*.png"))

            if method == "undersample" and len(images) > target_count:
                # 欠采样
                images = random.sample(images, target_count)
            elif method == "oversample" and len(images) < target_count:
                # 过采样（复制）
                images = images * (target_count // len(images)) + \
                         random.sample(images, target_count % len(images))

            # 复制图片
            for img in images:
                shutil.copy2(img, dst_dir / img.name)

    print(f"\n平衡后的数据集保存至: {output_dir}")
    create_dataset_yaml(output_dir, f"{output_dir}.yaml")

    return output_dir


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="准备鸟图对焦分类数据集")
    parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="原始数据目录（包含Focus/NotFocus/MotionBlur/Noise子目录）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="classification_dataset",
        help="输出目录",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.8,
        help="训练集比例",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.1,
        help="验证集比例",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.1,
        help="测试集比例",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查数据集",
    )
    parser.add_argument(
        "--balance",
        action="store_true",
        help="平衡数据集",
    )
    parser.add_argument(
        "--balance-method",
        type=str,
        default="undersample",
        choices=["undersample", "oversample"],
        help="平衡方法",
    )

    args = parser.parse_args()

    if args.check:
        # 仅检查数据集
        check_dataset(args.source)
    elif args.balance:
        # 平衡数据集
        balance_dataset(args.source, method=args.balance_method)
    else:
        # 准备数据集
        prepare_classification_dataset(
            source_dir=args.source,
            output_dir=args.output,
            train_ratio=args.train_ratio,
            val_ratio=args.val_ratio,
            test_ratio=args.test_ratio,
        )
