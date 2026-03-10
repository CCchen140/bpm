# 栖图软件编译打包指南

本文档详细介绍如何从源码编译并打包"栖图"软件，生成可发布的安装程序。

## 目录

1. [环境准备](#1-环境准备)
2. [项目结构说明](#2-项目结构说明)
3. [打包流程概述](#3-打包流程概述)
4. [详细打包步骤](#4-详细打包步骤)
5. [安装程序制作](#5-安装程序制作)
6. [常见问题](#6-常见问题)

---

## 1. 环境准备

### 1.1 系统要求

- **操作系统**: Windows 10/11 64位
- **Python版本**: 3.11 或更高（推荐3.11）
- **磁盘空间**: 至少 10GB 可用空间
- **内存**: 建议 8GB 以上

### 1.2 必需软件

| 软件 | 用途 | 下载地址 |
|------|------|----------|
| Python 3.11 | 运行环境 | https://www.python.org/downloads/ |
| Inno Setup 6 | 制作安装程序 | https://jrsoftware.org/isinfo.php |
| Git | 版本控制（可选） | https://git-scm.com/ |

### 1.3 Python依赖包

```bash
# 核心依赖
pip install PyQt6 PyQt6-WebEngine qtawesome psutil PyInstaller

# AI/图像处理依赖（根据版本选择CPU或GPU）
# CPU版本
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# GPU版本（CUDA 12.1）
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 其他依赖
pip install pillow numpy pandas requests
```

### 1.4 验证环境

```powershell
# 验证Python版本
python --version

# 验证PyQt6-WebEngine（地图功能必需）
python -c "import PyQt6.QtWebEngineWidgets; print('PyQt6-WebEngine OK')"

# 验证PyInstaller
pyinstaller --version

# 验证Inno Setup（命令行编译器）
iscc /?
```

---

## 2. 项目结构说明

```
BirdPictureManager/
├── assets/                 # 静态资源（图标、图片等）
├── build/                  # 打包相关文件
│   ├── build.py           # 主构建脚本
│   ├── bird_picture_manager.spec  # PyInstaller配置
│   ├── generate_icon.py   # 图标生成工具
│   ├── installer/         # 安装程序脚本
│   │   ├── newinstaller.iss      # 完整安装程序
│   │   └── update_installer.iss  # 升级安装程序
│   └── ph.bird-fill.ico   # 应用程序图标
├── cache/                  # 缓存目录（打包时排除）
├── data/                   # 数据文件
│   ├── bird_classification.json      # 鸟类分类数据
│   ├── species_text_aliases.json     # 物种别名
│   └── echart/            # 图表库
├── docs/                   # 文档
├── models/                 # AI模型文件
├── opensource/             # 开源组件
├── ui/                     # UI界面代码
├── utils/                  # 工具类
├── main.py                 # 程序入口
└── requirements.txt        # 依赖列表
```

### 2.1 关键配置文件

#### bird_picture_manager.spec
PyInstaller的主配置文件，定义了：
- 入口脚本路径
- 需要打包的数据文件
- 需要排除的模块
- 隐藏导入的模块
- EXE文件属性

#### build.py
构建脚本，功能包括：
- 自动生成图标
- 支持代码混淆（PyArmor）
- 支持CPU/GPU版本切换
- 自动清理和优化打包结果

---

## 3. 打包流程概述

```
┌─────────────────┐
│   1. 环境检查    │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. 生成应用图标  │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. PyInstaller  │
│    打包EXE      │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. 清理优化      │
│   (可选混淆)    │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 5. 制作安装程序  │
│   (Inno Setup)  │
└─────────────────┘
```

---

## 4. 详细打包步骤

### 4.1 标准打包（推荐）

使用一键构建脚本：

```powershell
# 进入项目根目录
cd D:\code\BirdPictureManager

# 标准打包
python build\build.py

# 带版本后缀打包（如GPU版本）
python build\build.py gpu

# 带混淆打包（防反编译）
python build\build.py --obf

# GPU版本+混淆
python build\build.py gpu --obf
```

打包完成后，输出目录为：
```
dist/栖图_V0.0.3/
├── 栖图.exe          # 主程序
├── assets/           # 资源文件
├── data/             # 数据文件
├── lib/              # 依赖库
└── ...
```

### 4.2 手动打包

如果需要更精细的控制，可以手动执行各步骤：

#### 步骤1：生成图标

```powershell
python build\generate_icon.py
```

生成 `build/ph.bird-fill.ico` 图标文件。

#### 步骤2：执行PyInstaller

```powershell
# 设置环境变量
$env:BPM_PROJECT_ROOT = "D:\code\BirdPictureManager"
$env:BPM_BUILD_DIR = "D:\code\BirdPictureManager\build"

# 执行打包
python -m PyInstaller --noconfirm --clean build\bird_picture_manager.spec
```

#### 步骤3：验证输出

检查 `dist/栖图_V0.0.3/` 目录是否包含：
- 栖图.exe（主程序）
- assets/ 目录
- data/ 目录
- lib/ 目录（包含exiftool.exe）

### 4.3 CPU/GPU版本说明

#### CPU版本
- 使用CPU进行AI推理
- 打包体积小（约500MB-1GB）
- 无需CUDA依赖

```powershell
# 确保安装CPU版torch
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 打包
python build\build.py cpu
```

#### GPU版本
- 使用NVIDIA GPU进行AI推理
- 打包体积大（约2GB-4GB，包含CUDA库）
- 需要用户电脑有NVIDIA显卡

```powershell
# 确保安装CUDA版torch
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 打包
python build\build.py gpu
```

**注意**：打包时会自动检测当前环境的torch版本，如果环境不匹配会报错。

### 4.4 代码混淆（可选）

使用PyArmor对源码进行混淆，增加反编译难度：

```powershell
# 安装PyArmor
pip install pyarmor

# 打包时添加--obf参数
python build\build.py --obf
```

混淆后的代码位于 `build/obf_src/`，然后使用混淆后的代码进行打包。

---

## 5. 安装程序制作

使用Inno Setup制作专业的Windows安装程序。

### 5.1 完整安装程序

用于首次安装软件的用户。

#### 配置文件

`build/installer/update_installer.iss`

#### 编译步骤

```powershell
# 命令行编译
iscc build\installer\update_installer.iss

# 或在Inno Setup IDE中打开后按F9编译
```

#### 输出文件

`build/installer/栖图安装器_V0.0.3.exe`

#### 安装程序特性

- 自动检测已安装版本
- 支持更新模式（保留用户数据）
- 创建桌面快捷方式（可选）
- 注册文件关联（.myp文件）
- 智能处理data目录（保留用户数据，更新系统数据）

### 5.2 升级安装程序

用于从特定版本升级到新版本。

#### 配置文件

`build/installer/newinstaller.iss`

#### 使用方法

需要指定来源版本和目标版本：

```pascal
// 在ISS文件顶部定义
#define MyAppFromVersion "0.0.2"  // 从该版本升级
#define MyAppVersion "0.0.3"      // 升级到该版本
```

#### 升级校验

- 校验已安装版本是否匹配来源版本
- 校验升级路径（不允许降级）
- 强制安装到原目录

### 5.3 安装脚本关键配置

```pascal
[Setup]
AppId=74F28464-C26A-47D9-AE73-22E79631B472  ; 唯一标识，不要修改
AppName=栖图
AppVersion=0.0.3
DefaultDirName={autopf}\栖图
OutputBaseFilename=栖图安装器_V0.0.3
SetupIconFile=..\ph.bird-fill.ico
Compression=lzma2/ultra64  ; 最大压缩

[Files]
; 主程序
Source: "{dist}\栖图.exe"; DestDir: "{app}"

; 资源文件（递归子目录）
Source: "{dist}\*"; DestDir: "{app}"; Excludes: "data,cache"; Flags: recursesubdirs

; data目录处理：系统数据强制更新，用户数据不覆盖
Source: "{dist}\data\bird_classification.json"; DestDir: "{app}\data"; Flags: comparetimestamp
Source: "{dist}\data\*"; DestDir: "{app}\data"; Excludes: "bird_classification.json"; Flags: onlyifdoesntexist recursesubdirs
```

---

## 6. 常见问题

### Q1: 打包时提示缺少PyQt6-WebEngine

**错误信息**：
```
未检测到 PyQt6-WebEngine（或其依赖无法加载），打包后地图会不可用。
```

**解决方案**：
```bash
pip install PyQt6-WebEngine
```

### Q2: 打包后地图功能无法使用

**原因**：WebEngine相关文件未正确打包

**解决方案**：
1. 确保安装PyQt6-WebEngine
2. 检查spec文件中是否包含WebEngine相关配置
3. 手动复制QtWebEngineProcess.exe到输出目录

### Q3: 打包体积过大

**优化建议**：
1. 使用CPU版torch而非GPU版
2. 在spec文件中排除不需要的模块：
   ```python
   excludes=[
       "torch._dynamo",
       "torch._inductor",
       "torch.distributed",
       "torch.testing",
   ]
   ```
3. 使用UPX压缩（修改spec中`upx=True`）

### Q4: 打包后ExifTool无法使用

**检查清单**：
1. 确保项目根目录有`exiftool.exe`
2. 检查spec文件中是否正确配置了binaries
3. 确保输出目录`lib/exiftool.exe`存在

### Q5: 如何修改软件版本号

**修改位置**：
```python
# utils/system/app_info_manager.py
APP_NAME = "栖图"
APP_VERSION = "V0.0.3"  # 修改这里
```

### Q6: 打包时内存不足

**解决方案**：
1. 关闭其他程序释放内存
2. 增加虚拟内存（页面文件）大小
3. 使用64位Python

### Q7: 如何制作增量更新包

**步骤**：
1. 使用`--delta-from`参数指定旧版本目录
2. 脚本会自动计算差异文件
3. 更新installer.iss中的Files段

```powershell
python build\build.py --delta-from "dist/栖图_V0.0.2"
```

---

## 附录

### A. 构建脚本参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `suffix` | 软件名后缀 | `python build\build.py gpu` |
| `--obf` | 启用代码混淆 | `python build\build.py --obf` |
| `--flavor` | 指定CPU/GPU版本 | `python build\build.py --flavor cpu` |
| `--delta-from` | 增量更新基准目录 | `python build\build.py --delta-from dist/旧版本` |

### B. 目录变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BPM_PROJECT_ROOT` | 项目根目录 | 当前工作目录 |
| `BPM_BUILD_DIR` | 构建目录 | `项目根目录/build` |
| `BPM_SOURCE_ROOT` | 源码目录 | 项目根目录 |
| `BPM_ENTRY` | 入口脚本 | `main.py` |
| `BPM_NAME_SUFFIX` | 软件名后缀 | 空 |

### C. 相关文件清单

| 文件 | 用途 |
|------|------|
| `build/build.py` | 主构建脚本 |
| `build/bird_picture_manager.spec` | PyInstaller配置 |
| `build/generate_icon.py` | 图标生成 |
| `build/installer/update_installer.iss` | 完整安装程序脚本 |
| `build/installer/newinstaller.iss` | 升级安装程序脚本 |
| `utils/system/app_info_manager.py` | 版本信息 |

---

*文档版本: 1.0*
*最后更新: 2026-03-05*
