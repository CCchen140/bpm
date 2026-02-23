# 鸟眼检测模型改进指南

本文档介绍如何使用新数据集改进现有的鸟眼检测模型。

## 目录
- [概述](#概述)
- [准备工作](#准备工作)
- [三种改进方式](#三种改进方式)
- [使用脚本改进](#使用脚本改进)
- [手动改进](#手动改进)
- [验证改进效果](#验证改进效果)
- [常见问题](#常见问题)

## 概述

### 为什么要改进模型？
- 提高检测精度
- 适应新的场景
- 修复误检/漏检问题
- 增加对不同鸟类的适应性

### 改进策略
1. **增量训练**：在现有模型基础上，使用新数据继续训练
2. **迁移学习**：冻结部分层，只训练特定层
3. **数据增强**：扩充数据集多样性

## 准备工作

### 1. 准备新数据集

新数据集需要符合YOLO格式：
```
new_dataset/
├── images/          # 图片文件
│   ├── img1.jpg
│   ├── img2.jpg
│   └── ...
├── labels/          # 标注文件（YOLO格式）
│   ├── img1.txt
│   ├── img2.txt
│   └── ...
└── classes.txt      # 类别定义（内容为：BirdEye）
```

### 2. 标注格式

每个.txt文件包含目标的位置信息：
```
<class_id> <x_center> <y_center> <width> <height>
```

例如：
```
0 0.5 0.5 0.2 0.3
```

## 三种改进方式

### 方式一：增量训练（推荐）

使用新数据在现有模型基础上继续训练，保留已学习的特征。

**适用场景**：
- 新数据量较小（< 500张）
- 新场景与原始场景相似
- 想要保持原有检测能力

**优点**：
- 训练速度快
- 不会遗忘已学知识
- 适合小数据集

### 方式二：完全重新训练

合并新旧数据集，从头开始训练。

**适用场景**：
- 新数据量很大
- 新场景与原始场景差异大
- 有足够计算资源

**优点**：
- 模型更适应新数据分布
- 可能获得更好的整体性能

### 方式三：迁移学习

冻结模型的骨干网络，只训练检测头。

**适用场景**：
- 新数据量很小（< 100张）
- 防止过拟合
- 快速适应新场景

**优点**：
- 训练最快
- 不容易过拟合
- 保持通用特征提取能力

## 使用脚本改进

### 快速开始

```bash
# 1. 增量训练（推荐）
python improve_model.py --mode train \
    --current-model best.pt \
    --new-dataset new_dataset \
    --epochs 50 \
    --freeze 10

# 2. 仅合并数据集
python improve_model.py --mode merge \
    --original-dataset dataset \
    --new-dataset new_dataset

# 3. 验证改进后的模型
python improve_model.py --mode validate \
    --current-model runs/improve/birdeye_improved/weights/best.pt \
    --new-dataset test_images
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mode` | 操作模式：train/merge/validate | train |
| `--current-model` | 当前模型路径 | best.pt |
| `--new-dataset` | 新数据集路径 | None |
| `--original-dataset` | 原始数据集路径 | dataset |
| `--output-name` | 输出模型名称 | birdeye_improved |
| `--epochs` | 训练轮数 | 50 |
| `--batch` | 批次大小 | 16 |
| `--freeze` | 冻结层数 | 10 |
| `--device` | 训练设备 | auto |

### 训练示例

#### 示例1：小数据集增量训练
```bash
python improve_model.py --mode train \
    --current-model best.pt \
    --new-dataset new_data_100images \
    --epochs 30 \
    --freeze 15 \
    --batch 8
```

#### 示例2：大数据集完全训练
```bash
python improve_model.py --mode train \
    --current-model best.pt \
    --new-dataset new_data_1000images \
    --epochs 100 \
    --freeze 0 \
    --batch 16 \
    --output-name birdeye_v2
```

#### 示例3：快速适应（冻结更多层）
```bash
python improve_model.py --mode train \
    --current-model best.pt \
    --new-dataset new_data_50images \
    --epochs 20 \
    --freeze 20 \
    --batch 4
```

## 手动改进

如果你想更精细地控制训练过程，可以手动操作：

### 步骤1：合并数据集

```python
from improve_model import merge_datasets

merged_path = merge_datasets(
    original_dataset_path="dataset",
    new_dataset_path="new_dataset",
    output_path="merged_dataset"
)
```

### 步骤2：创建数据配置

```python
from improve_model import split_dataset, create_data_yaml

train_files, val_files = split_dataset("merged_dataset", train_ratio=0.8)
data_yaml = create_data_yaml("merged_dataset", train_files, val_files)
```

### 步骤3：自定义训练

```python
from ultralytics import YOLO

# 加载当前模型
model = YOLO("best.pt")

# 自定义训练参数
results = model.train(
    data="data_improved.yaml",
    epochs=50,
    batch=16,
    freeze=10,  # 冻结前10层
    lr0=0.001,  # 较低的学习率
    lrf=0.01,
    patience=15,
    project="runs/improve",
    name="custom_training",
)
```

## 验证改进效果

### 1. 客观指标对比

```bash
# 验证原模型
python improve_model.py --mode validate --current-model best.pt

# 验证新模型
python improve_model.py --mode validate --current-model runs/improve/birdeye_improved/weights/best.pt
```

对比指标：
- **mAP50**：IoU=0.5时的平均精度
- **mAP50-95**：IoU从0.5到0.95的平均精度
- **Precision**：精确率
- **Recall**：召回率

### 2. 主观效果对比

使用检测脚本对比：

```bash
# 原模型检测
python detect_bird_and_eye.py --image test.jpg --eye-model best.pt --output results/original

# 新模型检测
python detect_bird_and_eye.py --image test.jpg --eye-model runs/improve/birdeye_improved/weights/best.pt --output results/improved
```

### 3. 效果评估标准

| 指标 | 说明 | 目标值 |
|------|------|--------|
| mAP50 | 整体检测精度 | > 0.85 |
| 漏检率 | 未检测到的鸟眼比例 | < 5% |
| 误检率 | 错误检测的比例 | < 10% |
| 定位精度 | 检测框与真实框的重合度 | > 0.8 |

## 常见问题

### Q1: 新数据集需要多少张图片？

**A**: 取决于场景差异：
- 场景相似：50-100张即可
- 场景差异大：200-500张
- 全新场景：1000张以上

### Q2: 训练多少轮合适？

**A**: 建议：
- 小数据集（<100张）：20-30轮
- 中数据集（100-500张）：50-100轮
- 大数据集（>500张）：100-200轮

观察验证集损失，如果开始上升则停止训练。

### Q3: 冻结层数怎么选？

**A**: 
- 冻结15-20层：小数据集，防止过拟合
- 冻结5-10层：中等数据集，平衡速度和精度
- 冻结0层（不冻结）：大数据集，充分训练

### Q4: 学习率需要调整吗？

**A**: 增量训练建议使用较低学习率：
- 原始训练：0.01
- 增量训练：0.001
- 微调：0.0001

### Q5: 改进后模型变差了怎么办？

**A**: 
1. 检查新数据标注质量
2. 减少冻结层数，增加训练轮数
3. 增加新数据量
4. 降低学习率
5. 如果都不行，回退到原模型

### Q6: 如何保存多个版本的模型？

**A**: 使用不同的 `--output-name`：
```bash
# 版本1
python improve_model.py --output-name birdeye_v1 ...

# 版本2
python improve_model.py --output-name birdeye_v2 ...
```

### Q7: 可以多次增量训练吗？

**A**: 可以，每次使用改进后的模型作为基础：
```bash
# 第一次改进
python improve_model.py --current-model best.pt --output-name v1 ...

# 第二次改进
python improve_model.py --current-model runs/improve/v1/weights/best.pt --output-name v2 ...

# 第三次改进
python improve_model.py --current-model runs/improve/v2/weights/best.pt --output-name v3 ...
```

## 最佳实践

1. **备份原模型**：改进前备份 `best.pt`
2. **小步快跑**：先小批量数据测试，再大规模训练
3. **持续验证**：每轮训练后验证效果
4. **记录实验**：记录每次训练的参数和结果
5. **数据质量**：确保新数据标注准确
6. **多样性**：新数据应覆盖不同场景、角度、光照

## 总结

改进模型是一个迭代过程：
1. 收集新数据 → 2. 增量训练 → 3. 验证效果 → 4. 部署使用

如果效果提升，部署新模型；如果效果不佳，分析原因并调整策略。
