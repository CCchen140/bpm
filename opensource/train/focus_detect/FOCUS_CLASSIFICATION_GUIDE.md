# 鸟图对焦分类模型训练指南

本文档介绍如何训练一个鸟图对焦质量分类模型，使用YOLO11-cls进行四分类（Focus/NotFocus/MotionBlur/Noise）。

## 目录
- [概述](#概述)
- [环境准备](#环境准备)
- [数据准备](#数据准备)
- [训练模型](#训练模型)
- [模型评估](#模型评估)
- [使用模型](#使用模型)
- [进阶技巧](#进阶技巧)

## 概述

### 任务定义
将鸟图按对焦质量分为4类：
- **Focus** - 对焦清晰，画面锐利
- **NotFocus** - 失焦/模糊，主体不清晰
- **MotionBlur** - 运动模糊，有拖影
- **Noise** - 噪点过多，画面粗糙

### 模型选择
| 模型 | 大小 | 速度 | 精度 | 适用场景 |
|------|------|------|------|---------|
| yolo11n-cls | 小 | 快 | 中 | 实时应用、边缘设备 |
| yolo11s-cls | 中 | 中 | 高 | 平衡选择 |
| yolo11m-cls | 大 | 慢 | 更高 | 追求精度 |

## 环境准备

### 1. 安装依赖

```bash
pip install ultralytics torch torchvision
pip install scikit-learn matplotlib numpy
```

### 2. 检查GPU

```python
import torch
print(torch.cuda.is_available())  # 应该输出 True
```

## 数据准备

### 1. 原始数据结构

```
raw_data/
├── Focus/              # 对焦清晰的图片
│   ├── img1.jpg
│   ├── img2.jpg
│   └── ...
├── NotFocus/           # 失焦的图片
│   ├── img1.jpg
│   └── ...
├── MotionBlur/         # 运动模糊的图片
│   ├── img1.jpg
│   └── ...
└── Noise/              # 噪点过多的图片
    ├── img1.jpg
    └── ...
```

### 2. 准备数据集

```bash
python prepare_classification_dataset.py --source raw_data --output classification_dataset
```

这会自动：
- 划分训练集(80%)、验证集(10%)、测试集(10%)
- 创建YOLO-cls格式的目录结构
- 生成数据集配置文件

### 3. 检查数据集

```bash
python prepare_classification_dataset.py --source classification_dataset --check
```

### 4. 平衡数据集（可选）

如果各类别数量不均衡：

```bash
# 欠采样（将所有类别降至最少类的数量）
python prepare_classification_dataset.py --source classification_dataset --balance --balance-method undersample

# 过采样（将所有类别增至最多类的数量）
python prepare_classification_dataset.py --source classification_dataset --balance --balance-method oversample
```

## 训练模型

### 1. 快速开始

```bash
python train_focus_classifier.py --mode train \
    --data classification_dataset \
    --model yolo11n-cls.pt \
    --epochs 100 \
    --batch 32 \
    --name bird_focus_v1
```

### 2. 训练参数说明

| 参数 | 说明 | 建议值 |
|------|------|--------|
| --model | 预训练模型 | yolo11n-cls.pt (轻量) / yolo11s-cls.pt (平衡) |
| --epochs | 训练轮数 | 50-200，根据数据量调整 |
| --batch | 批次大小 | 16-64，根据显存调整 |
| --imgsz | 输入尺寸 | 224 (标准) / 320 (更高精度) |
| --lr0 | 初始学习率 | 0.001-0.01 |

### 3. 不同场景的训练策略

#### 小数据集 (< 500张)
```bash
python train_focus_classifier.py --mode train \
    --data classification_dataset \
    --model yolo11n-cls.pt \
    --epochs 50 \
    --batch 16 \
    --lr0 0.001 \
    --name bird_focus_small
```

#### 大数据集 (> 2000张)
```bash
python train_focus_classifier.py --mode train \
    --data classification_dataset \
    --model yolo11s-cls.pt \
    --epochs 150 \
    --batch 32 \
    --imgsz 320 \
    --name bird_focus_large
```

#### 追求最高精度
```bash
python train_focus_classifier.py --mode train \
    --data classification_dataset \
    --model yolo11m-cls.pt \
    --epochs 200 \
    --batch 16 \
    --imgsz 320 \
    --name bird_focus_best
```

## 模型评估

### 1. 全面评估

```bash
python evaluate_classifier.py \
    --model runs/classify/bird_focus_v1/weights/best.pt \
    --data classification_dataset \
    --split test \
    --output evaluation_results
```

评估报告包括：
- 整体准确率
- 各类别的精确率、召回率、F1分数
- 混淆矩阵
- 错误案例分析
- 可视化图表

### 2. 验证模型

```bash
python train_focus_classifier.py --mode val \
    --model runs/classify/bird_focus_v1/weights/best.pt \
    --data classification_dataset
```

## 使用模型

### 1. 单张图片预测

```bash
python train_focus_classifier.py --mode predict \
    --model runs/classify/bird_focus_v1/weights/best.pt \
    --image path/to/image.jpg
```

输出示例：
```
预测结果:
  图片: path/to/image.jpg
  预测类别: Focus (对焦清晰)
  置信度: 0.9523

各类别概率:
  Focus (对焦清晰): 0.9523
  NotFocus (失焦): 0.0312
  MotionBlur (运动模糊): 0.0125
  Noise (噪点过多): 0.0040
```

### 2. 批量预测

```bash
python train_focus_classifier.py --mode batch \
    --model runs/classify/bird_focus_v1/weights/best.pt \
    --folder path/to/image/folder \
    --output classification_results
```

结果会按类别分类保存到不同文件夹。

### 3. 在Python代码中使用

```python
from ultralytics import YOLO

# 加载模型
model = YOLO("runs/classify/bird_focus_v1/weights/best.pt")

# 单张预测
results = model("image.jpg")
result = results[0]

# 获取预测结果
predicted_class = result.names[result.probs.top1]
confidence = result.probs.top1conf.item()

print(f"预测类别: {predicted_class}")
print(f"置信度: {confidence:.4f}")

# 批量预测
results = model(["img1.jpg", "img2.jpg", "img3.jpg"])
for result in results:
    print(f"{result.names[result.probs.top1]}: {result.probs.top1conf.item():.4f}")
```

## 进阶技巧

### 1. 数据增强策略

训练脚本已内置数据增强：
- 随机旋转（±15度）
- 随机缩放（0.5-1.5倍）
- 随机剪切
- 水平翻转
- HSV色彩变换

如需调整，修改 `train_focus_classifier.py` 中的增强参数。

### 2. 处理类别不平衡

如果某类样本特别少：

```python
# 在训练脚本中调整类别权重
class_weights = [1.0, 2.0, 1.5, 1.0]  # 给NotFocus类更高权重
```

### 3. 模型集成

训练多个模型进行投票：

```python
from ultralytics import YOLO
import numpy as np

models = [
    YOLO("model1.pt"),
    YOLO("model2.pt"),
    YOLO("model3.pt"),
]

# 集成预测
results = [model("image.jpg")[0] for model in models]
probs = [r.probs.data.cpu().numpy() for r in results]

# 平均概率
avg_probs = np.mean(probs, axis=0)
predicted_class = np.argmax(avg_probs)
```

### 4. 导出模型

```bash
# 导出为ONNX格式
python train_focus_classifier.py --mode export \
    --model runs/classify/bird_focus_v1/weights/best.pt \
    --export-format onnx

# 导出为TensorRT格式（NVIDIA GPU加速）
python train_focus_classifier.py --mode export \
    --model runs/classify/bird_focus_v1/weights/best.pt \
    --export-format engine
```

### 5. 增量训练

使用新数据改进模型：

```bash
# 1. 准备新数据
python prepare_classification_dataset.py --source new_data --output new_dataset

# 2. 在新数据上继续训练
python train_focus_classifier.py --mode train \
    --model runs/classify/bird_focus_v1/weights/best.pt \
    --data new_dataset \
    --epochs 30 \
    --lr0 0.0005 \
    --name bird_focus_v2
```

## 常见问题

### Q1: 训练需要多少数据？

**A**: 
- 最低要求：每类50-100张
- 推荐：每类200-500张
- 理想：每类1000张以上

### Q2: 训练需要多长时间？

**A**: 参考时间（NVIDIA RTX 3060）：
- yolo11n-cls: 100轮约10-20分钟
- yolo11s-cls: 100轮约30-60分钟
- yolo11m-cls: 100轮约1-2小时

### Q3: 准确率多少算好？

**A**: 
- 基础可用：> 75%
- 良好：> 85%
- 优秀：> 90%

### Q4: 如何区分类别？

**A**: 标注时的判断标准：
- **Focus**: 眼睛/羽毛细节清晰锐利
- **NotFocus**: 整体模糊，无清晰区域
- **MotionBlur**: 有明显拖影或动态模糊
- **Noise**: 颗粒感重，ISO过高导致的噪点

### Q5: 模型预测错误怎么办？

**A**: 
1. 检查训练数据标注是否正确
2. 增加该类的训练样本
3. 使用数据增强扩充该类
4. 尝试更大的模型
5. 检查是否有相似图片混入了错误类别

## 文件说明

| 文件 | 说明 |
|------|------|
| prepare_classification_dataset.py | 数据集准备脚本 |
| train_focus_classifier.py | 模型训练脚本 |
| evaluate_classifier.py | 模型评估脚本 |
| FOCUS_CLASSIFICATION_GUIDE.md | 本指南文档 |

## 总结

训练流程：
1. 收集并标注数据（Focus/NotFocus/MotionBlur/Noise）
2. 运行 `prepare_classification_dataset.py` 准备数据集
3. 运行 `train_focus_classifier.py` 训练模型
4. 运行 `evaluate_classifier.py` 评估模型
5. 使用训练好的模型进行预测

祝你训练成功！
