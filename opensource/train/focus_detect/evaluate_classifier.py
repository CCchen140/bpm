"""
鸟图对焦分类模型评估脚本
生成详细的评估报告和混淆矩阵
"""
import os
import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import matplotlib.pyplot as plt
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    accuracy_score,
    precision_recall_fscore_support,
)
from ultralytics import YOLO
import torch


CLASSES = ["Focus", "NotFocus", "MotionBlur", "Noise"]
CLASS_NAMES_CN = {
    "Focus": "对焦清晰",
    "NotFocus": "失焦",
    "MotionBlur": "运动模糊",
    "Noise": "噪点过多"
}


def evaluate_model(
    model_path: str,
    data_path: str,
    split: str = "test",
    output_dir: str = "evaluation_results",
    device: str = None,
) -> Dict:
    """
    全面评估分类模型性能

    Args:
        model_path: 模型路径
        data_path: 数据集路径
        split: 评估的数据集划分
        output_dir: 结果输出目录
        device: 运行设备

    Returns:
        评估结果字典
    """
    print("=" * 60)
    print("分类模型评估")
    print("=" * 60)

    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"

    # 创建输出目录
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 加载模型
    print(f"\n加载模型: {model_path}")
    model = YOLO(model_path)

    # 获取测试集路径
    test_path = Path(data_path) / split
    if not test_path.exists():
        print(f"错误: 测试集不存在 {test_path}")
        return {}

    # 收集所有测试图片和真实标签
    true_labels = []
    pred_labels = []
    confidences = []
    image_paths = []

    print(f"\n评估数据集: {test_path}")

    for class_idx, class_name in enumerate(CLASSES):
        class_dir = test_path / class_name
        if not class_dir.exists():
            continue

        # 获取该类别所有图片
        images = []
        for ext in ["*.jpg", "*.jpeg", "*.png", "*.bmp"]:
            images.extend(class_dir.glob(ext))
            images.extend(class_dir.glob(ext.upper()))

        print(f"  {class_name}: {len(images)} 张")

        # 预测每张图片
        for img_path in images:
            try:
                results = model(str(img_path), device=device, verbose=False)
                result = results[0]

                pred_class_idx = result.probs.top1
                confidence = result.probs.top1conf.item()

                true_labels.append(class_idx)
                pred_labels.append(pred_class_idx)
                confidences.append(confidence)
                image_paths.append(str(img_path))

            except Exception as e:
                print(f"    错误处理 {img_path}: {e}")

    # 转换为numpy数组
    true_labels = np.array(true_labels)
    pred_labels = np.array(pred_labels)
    confidences = np.array(confidences)

    # 计算指标
    print("\n" + "=" * 60)
    print("评估结果")
    print("=" * 60)

    # 1. 整体准确率
    accuracy = accuracy_score(true_labels, pred_labels)
    print(f"\n整体准确率: {accuracy:.4f} ({accuracy*100:.2f}%)")

    # 2. 每个类别的指标
    precision, recall, f1, support = precision_recall_fscore_support(
        true_labels, pred_labels, average=None, labels=range(len(CLASSES))
    )

    print("\n各类别性能:")
    print(f"{'类别':<15} {'精确率':>10} {'召回率':>10} {'F1分数':>10} {'样本数':>10}")
    print("-" * 60)
    for i, class_name in enumerate(CLASSES):
        print(f"{class_name:<15} {precision[i]:>10.4f} {recall[i]:>10.4f} {f1[i]:>10.4f} {int(support[i]):>10}")

    # 3. 宏平均和加权平均
    macro_precision, macro_recall, macro_f1, _ = precision_recall_fscore_support(
        true_labels, pred_labels, average='macro'
    )
    weighted_precision, weighted_recall, weighted_f1, _ = precision_recall_fscore_support(
        true_labels, pred_labels, average='weighted'
    )

    print("\n宏平均:")
    print(f"  精确率: {macro_precision:.4f}")
    print(f"  召回率: {macro_recall:.4f}")
    print(f"  F1分数: {macro_f1:.4f}")

    print("\n加权平均:")
    print(f"  精确率: {weighted_precision:.4f}")
    print(f"  召回率: {weighted_recall:.4f}")
    print(f"  F1分数: {weighted_f1:.4f}")

    # 4. 混淆矩阵
    cm = confusion_matrix(true_labels, pred_labels, labels=range(len(CLASSES)))
    print("\n混淆矩阵:")
    print(f"{'':<15}", end="")
    for class_name in CLASSES:
        print(f"{class_name:>12}", end="")
    print()
    print("-" * 75)
    for i, class_name in enumerate(CLASSES):
        print(f"{class_name:<15}", end="")
        for j in range(len(CLASSES)):
            print(f"{cm[i][j]:>12}", end="")
        print()

    # 5. 分类报告
    print("\n详细分类报告:")
    report = classification_report(
        true_labels,
        pred_labels,
        target_names=CLASSES,
        digits=4,
    )
    print(report)

    # 保存结果到文件
    results = {
        "accuracy": float(accuracy),
        "macro_avg": {
            "precision": float(macro_precision),
            "recall": float(macro_recall),
            "f1": float(macro_f1),
        },
        "weighted_avg": {
            "precision": float(weighted_precision),
            "recall": float(weighted_recall),
            "f1": float(weighted_f1),
        },
        "per_class": {
            class_name: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
            for i, class_name in enumerate(CLASSES)
        },
        "confusion_matrix": cm.tolist(),
    }

    # 保存JSON
    json_path = Path(output_dir) / "evaluation_results.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n评估结果已保存: {json_path}")

    # 保存文本报告
    report_path = Path(output_dir) / "evaluation_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("鸟图对焦分类模型评估报告\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"模型: {model_path}\n")
        f.write(f"数据集: {data_path}/{split}\n")
        f.write(f"样本总数: {len(true_labels)}\n\n")
        f.write(f"整体准确率: {accuracy:.4f} ({accuracy*100:.2f}%)\n\n")
        f.write("各类别性能:\n")
        f.write(f"{'类别':<15} {'精确率':>10} {'召回率':>10} {'F1分数':>10} {'样本数':>10}\n")
        f.write("-" * 60 + "\n")
        for i, class_name in enumerate(CLASSES):
            f.write(f"{class_name:<15} {precision[i]:>10.4f} {recall[i]:>10.4f} {f1[i]:>10.4f} {int(support[i]):>10}\n")
        f.write("\n")
        f.write("宏平均:\n")
        f.write(f"  精确率: {macro_precision:.4f}\n")
        f.write(f"  召回率: {macro_recall:.4f}\n")
        f.write(f"  F1分数: {macro_f1:.4f}\n\n")
        f.write("加权平均:\n")
        f.write(f"  精确率: {weighted_precision:.4f}\n")
        f.write(f"  召回率: {weighted_recall:.4f}\n")
        f.write(f"  F1分数: {weighted_f1:.4f}\n\n")
        f.write("混淆矩阵:\n")
        f.write(f"{'':<15}")
        for class_name in CLASSES:
            f.write(f"{class_name:>12}")
        f.write("\n")
        f.write("-" * 75 + "\n")
        for i, class_name in enumerate(CLASSES):
            f.write(f"{class_name:<15}")
            for j in range(len(CLASSES)):
                f.write(f"{cm[i][j]:>12}")
            f.write("\n")
        f.write("\n")
        f.write("详细分类报告:\n")
        f.write(report)

    print(f"评估报告已保存: {report_path}")

    # 绘制混淆矩阵图
    plot_confusion_matrix(cm, CLASSES, output_dir)

    # 绘制各类别性能对比图
    plot_class_performance(results["per_class"], output_dir)

    # 分析错误案例
    analyze_errors(true_labels, pred_labels, confidences, image_paths, output_dir)

    return results


def plot_confusion_matrix(cm: np.ndarray, class_names: List[str], output_dir: str):
    """绘制混淆矩阵热力图"""
    plt.figure(figsize=(10, 8))
    plt.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
    plt.title('Confusion Matrix', fontsize=16)
    plt.colorbar()

    tick_marks = np.arange(len(class_names))
    plt.xticks(tick_marks, class_names, rotation=45, ha='right')
    plt.yticks(tick_marks, class_names)

    # 添加数值标注
    thresh = cm.max() / 2.
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            plt.text(j, i, format(cm[i, j], 'd'),
                    ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black",
                    fontsize=12)

    plt.tight_layout()
    plt.ylabel('True Label', fontsize=12)
    plt.xlabel('Predicted Label', fontsize=12)

    save_path = Path(output_dir) / "confusion_matrix.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"混淆矩阵图已保存: {save_path}")


def plot_class_performance(per_class_results: Dict, output_dir: str):
    """绘制各类别性能对比图"""
    class_names = list(per_class_results.keys())
    precision = [per_class_results[c]["precision"] for c in class_names]
    recall = [per_class_results[c]["recall"] for c in class_names]
    f1 = [per_class_results[c]["f1"] for c in class_names]

    x = np.arange(len(class_names))
    width = 0.25

    fig, ax = plt.subplots(figsize=(12, 6))
    bars1 = ax.bar(x - width, precision, width, label='Precision', color='#2ecc71')
    bars2 = ax.bar(x, recall, width, label='Recall', color='#3498db')
    bars3 = ax.bar(x + width, f1, width, label='F1-Score', color='#e74c3c')

    ax.set_xlabel('Class', fontsize=12)
    ax.set_ylabel('Score', fontsize=12)
    ax.set_title('Per-Class Performance Metrics', fontsize=16)
    ax.set_xticks(x)
    ax.set_xticklabels(class_names, rotation=45, ha='right')
    ax.legend()
    ax.set_ylim([0, 1])

    # 添加数值标签
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.2f}',
                       xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3),
                       textcoords="offset points",
                       ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    save_path = Path(output_dir) / "class_performance.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"类别性能对比图已保存: {save_path}")


def analyze_errors(
    true_labels: np.ndarray,
    pred_labels: np.ndarray,
    confidences: np.ndarray,
    image_paths: List[str],
    output_dir: str,
    top_k: int = 20,
):
    """分析错误分类案例"""
    # 找出错误分类的样本
    errors = []
    for i in range(len(true_labels)):
        if true_labels[i] != pred_labels[i]:
            errors.append({
                "index": i,
                "image": image_paths[i],
                "true_class": CLASSES[true_labels[i]],
                "pred_class": CLASSES[pred_labels[i]],
                "confidence": confidences[i],
            })

    if not errors:
        print("\n没有错误分类的样本！")
        return

    # 按置信度排序
    errors.sort(key=lambda x: x["confidence"], reverse=True)

    print(f"\n错误分类分析:")
    print(f"总错误数: {len(errors)}")
    print(f"错误率: {len(errors)/len(true_labels)*100:.2f}%")

    # 统计各类别的错误
    error_by_class = {}
    for error in errors:
        true_cls = error["true_class"]
        if true_cls not in error_by_class:
            error_by_class[true_cls] = []
        error_by_class[true_cls].append(error)

    print("\n各类别错误分布:")
    for class_name in CLASSES:
        if class_name in error_by_class:
            count = len(error_by_class[class_name])
            print(f"  {class_name}: {count} 个错误")

    # 保存错误案例
    errors_path = Path(output_dir) / "error_cases.json"
    with open(errors_path, 'w', encoding='utf-8') as f:
        json.dump({
            "total_errors": len(errors),
            "error_rate": len(errors)/len(true_labels),
            "top_errors": errors[:top_k],
            "errors_by_class": {k: len(v) for k, v in error_by_class.items()},
        }, f, ensure_ascii=False, indent=2)

    print(f"\n错误案例分析已保存: {errors_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="评估鸟图对焦分类模型")
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="模型路径",
    )
    parser.add_argument(
        "--data",
        type=str,
        default="classification_dataset",
        help="数据集路径",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="test",
        help="数据集划分 (train/val/test)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="evaluation_results",
        help="输出目录",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="运行设备",
    )

    args = parser.parse_args()

    evaluate_model(
        model_path=args.model,
        data_path=args.data,
        split=args.split,
        output_dir=args.output,
        device=args.device,
    )
