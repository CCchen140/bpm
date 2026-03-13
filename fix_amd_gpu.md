# AMD GPU 问题修复指南

## 问题原因

你当前安装的是 CUDA 版本的 PyTorch (`torch==2.10.0+cu126`)，这个版本在导入时会尝试加载 NVIDIA CUDA DLL。在 AMD GPU 上，这些 DLL 不存在，导致加载失败：

```
[WinError 1114] 动态链接库(DLL)初始化例程失败。
Error loading "...\torch\lib\c10.dll"
```

## 解决方案

### 方案 1：安装 CPU 版本的 PyTorch（推荐）

在 AMD GPU 上，应该使用 CPU 版本的 PyTorch：

```bash
# 先卸载当前的 CUDA 版本
pip uninstall torch torchvision torchaudio -y

# 安装 CPU 版本
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

然后重新打包应用程序。

### 方案 2：在代码中处理 AMD GPU

我已经修改了运行时钩子 (`pyi_rth_torch_dlls.py`)，在 AMD GPU 上设置以下环境变量：

- `CUDA_VISIBLE_DEVICES=""` - 禁用 CUDA 设备
- `USE_CUDA="0"` - 禁用 CUDA
- `TORCH_CUDA_ARCH_LIST=""` - 禁用 CUDA 架构列表
- `PYTORCH_CUDA_ALLOC_CONF="backend:native"` - 配置 CUDA 分配器

但这些环境变量只能在 PyTorch 导入后生效，无法阻止导入时的 DLL 加载。

### 方案 3：使用 ROCm 版本的 PyTorch（仅限 Linux）

AMD GPU 在 Windows 上不支持 ROCm，所以这个方案不适用。

## 推荐的打包流程

1. **创建新的 Conda 环境**
```bash
conda create -n bird_cpu python=3.11
conda activate bird_cpu
```

2. **安装 CPU 版本的 PyTorch**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

3. **安装其他依赖**
```bash
pip install -r requirements.txt
```

4. **重新打包**
```bash
python build/build.py
```

## 验证安装

安装后验证 PyTorch 是否正确：

```python
import torch
print(torch.__version__)           # 应该显示 cpu 版本，如 2.10.0+cpu
print(torch.cuda.is_available())   # 应该返回 False
```

## 注意事项

- CPU 版本的 PyTorch 在 AMD GPU 上运行正常，只是使用 CPU 进行计算
- 检测速度会比 GPU 版本慢，但在 AMD GPU 上这是唯一可行的方案
- 确保在打包前验证 PyTorch 版本正确
