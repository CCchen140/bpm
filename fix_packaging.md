# 打包问题修复指南

## 问题原因

你当前使用的 Python 环境与期望的不一致：

- **当前环境**: `D:\Python\Python314` (Python 3.14)
  - torch 版本: `2.10.0+cpu` (CPU 版本)
  - `c10.dll` 哈希: `382F25B53B278CDD80F75B2C853E77777A3CF66A8EBFAD5706B2F59B7002B189`

- **正常版本** (`栖图_V0.0.3`): 
  - `c10.dll` 哈希: `45B23B13913F2999F7330BD533EFC584ABB83B0A415D1357DAE601F58ECC2612`
  - 文件大小: 1,085,952 字节

- **问题版本** (`栖图_V0.0.4_gpu`):
  - `c10.dll` 哈希: `49226B1AB8304DE33043D426655123F5CDA5ADA1782453A5770A781D6B3768DF`
  - 文件大小: 1,081,344 字节

## 解决方案

### 方法 1：在正确的 Conda 环境中打包（推荐）

你需要在 `bird_cuda_12.6` Conda 环境中打包：

```bash
# 激活 Conda 环境
conda activate bird_cuda_12.6

# 验证 torch 版本
python -c "import torch; print(torch.__version__)"
# 应该显示: 2.10.0+cu126 (GPU 版本)

# 运行打包脚本
python build/build.py
```

### 方法 2：直接指定 Python 路径

如果你不想激活 Conda 环境，可以直接指定 Python 路径：

```bash
# 使用 Conda 环境的 Python
D:\anaconda3\envs\bird_cuda_12.6\python.exe build/build.py
```

### 方法 3：修改 build.py 使用固定的 Python 路径

可以修改 `build.py` 强制使用特定的 Python 解释器。

## 验证打包环境

在打包前，务必验证环境正确：

```python
import torch
print(f"torch version: {torch.__version__}")
print(f"torch location: {torch.__file__}")

import sys
print(f"python executable: {sys.executable}")
```

## 文件对比

正常版本和问题版本的 `c10.dll` 文件不同：

| 版本 | 文件大小 | SHA256 哈希 |
|------|---------|------------|
| 正常 (V0.0.3) | 1,085,952 | 45B23B13913F2999F7330BD533EFC584ABB83B0A415D1357DAE601F58ECC2612 |
| 问题 (V0.0.4) | 1,081,344 | 49226B1AB8304DE33043D426655123F5CDA5ADA1782453A5770A781D6B3768DF |
| 当前环境 | 1,081,344 | 382F25B53B278CDD80F75B2C853E77777A3CF66A8EBFAD5706B2F59B7002B189 |

## 建议

1. 始终在正确的 Conda 环境中打包
2. 打包前验证 torch 版本和位置
3. 打包后验证关键 DLL 文件的哈希值
