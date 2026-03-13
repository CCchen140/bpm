# BirdPictureManager 打包指南

## 目录

1. [环境准备](#环境准备)
2. [完整包打包](#完整包打包)
3. [增量升级包打包](#增量升级包打包)
4. [打包依赖白名单](#打包依赖白名单)
5. [常见问题](#常见问题)

---

## 环境准备

### 必需组件

1. **Python 3.10+**
2. **PyInstaller** - 用于打包 Python 应用
3. **Inno Setup 6** - 用于制作安装程序
4. **PyQt6-WebEngine** - 地图功能依赖

### 安装依赖

```bash
pip install PyInstaller
pip install PyQt6-WebEngine
```

### 可选组件

- **pyarmor** - 用于代码混淆（`pip install pyarmor`）

---

## 完整包打包

### 基本打包

```bash
python build/build.py
```

输出位置：`dist/BirdPictureManager_V{版本号}/`

### 带后缀的打包

```bash
# 打包测试版本
python build/build.py beta

# 打包 RC 版本
python build/build.py rc1
```

输出位置：`dist/BirdPictureManager_beta_V{版本号}/`

### CPU/GPU 版本打包

```bash
# CPU 版本（不包含 CUDA 依赖，体积较小）
python build/build.py --flavor cpu

# GPU 版本（包含 CUDA 依赖，支持 GPU 加速）
python build/build.py --flavor gpu
```

### 混淆打包

```bash
python build/build.py --obf
```

注意：需要先安装 pyarmor

---

## 增量升级包打包

### 什么是增量升级包？

增量升级包只包含相对于旧版本发生变化的文件，可以显著减小安装包体积，加快用户下载和安装速度。

### 增量包打包步骤

#### 1. 准备旧版本

确保旧版本的打包目录存在，例如：
```
dist/BirdPictureManager_V1.0.0/
```

#### 2. 执行增量打包

```bash
python build/build.py --delta-from "dist/BirdPictureManager_V1.0.0" --from-version "V1.0.0"
```

参数说明：
- `--delta-from`: 旧版本 dist 目录的完整路径
- `--from-version`: 旧版本号（如 V1.0.0）

#### 3. 生成文件

打包完成后会生成：
- **安装程序**: `build/installer/栖图_从V1.0.0升级_V1.0.1.exe`
- **增量报告**: `dist/BirdPictureManager_V1.0.1_delta_report.txt`

#### 4. 查看增量报告

增量报告包含三类文件：
- **新增的文件**：新版本中新增的文件
- **修改的文件**：内容发生变化的文件
- **删除的文件**：新版本中不再需要的文件

示例报告：
```
================================================================================
BirdPictureManager 增量升级包文件列表
================================================================================

旧版本目录: D:\Projects\BirdPictureManager\dist\BirdPictureManager_V1.0.0
新版本目录: D:\Projects\BirdPictureManager\dist\BirdPictureManager_V1.0.1
新增文件数: 3
修改文件数: 10
删除文件数: 2
总计: 15 个文件

--------------------------------------------------------------------------------
新增的文件 (3 个):
--------------------------------------------------------------------------------
   1. [新增] new_feature.dll (2.5 MB)
   2. [新增] ui\new_dialog.py (15.2 KB)
   3. [新增] resources\new_icon.png (5.0 KB)

--------------------------------------------------------------------------------
修改的文件 (10 个):
--------------------------------------------------------------------------------
   1. [修改] BirdPictureManager.exe (25.3 MB)
   2. [修改] ui\dialogs\watermark_dialog.py (45.2 KB)
   ...

--------------------------------------------------------------------------------
删除的文件 (2 个):
--------------------------------------------------------------------------------
   1. [删除] old_module.dll
   2. [删除] resources\deprecated.png

================================================================================
生成时间: 2026-03-05 14:30:00
================================================================================
```

### 使用 build.py --delta 打包升级包（推荐）

`build.py` 现在支持 `--delta` 参数，可以直接调用 `build_delta.py` 创建升级包，一步完成完整包打包和升级包创建。

#### 快速开始

```bash
# 打包完整版 + 自动创建升级包
python build/build.py --flavor gpu --delta-from "dist/栖图_V0.0.4_gpu" --delta

# 输出：
# - dist/栖图_V1.0.1_gpu/              <- 完整版文件夹
# - dist/栖图_V1.0.1_gpu_update1/      <- 差分升级文件夹
# - build/installer/update_V1.0.1_gpu_update1.iss  <- 升级包 ISS 脚本
```

#### 工作流程

```bash
# 1. 打包完整版并创建升级包
python build/build.py --flavor gpu --delta-from "dist/栖图_V0.0.4_gpu" --delta

# 2. 使用 Inno Setup 编译生成的 ISS 脚本
# 打开 Inno Setup → 打开 build/installer/update_V1.0.1_gpu_update1.iss
# 点击 Build → Compile

# 3. 输出升级包
# build/installer/栖图_V1.0.1_gpu_update1.exe
```

#### 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `--flavor` | CPU/GPU 版本 | `gpu` 或 `cpu` |
| `--delta-from` | 旧版本目录 | `dist/栖图_V1.0.0_gpu` |
| `--delta` | 使用 build_delta 创建升级包 | 无需值 |
| `--from-version` | 旧版本号（可选） | `V1.0.0` |

#### 单独使用 build_delta.py

如果只想创建升级包（不打包完整版）：

```bash
# 基本用法（自动检测新版本和参数）
python build/build_delta.py --from "dist/栖图_V1.0.0_gpu"

# 完整参数
python build/build_delta.py --from "dist/栖图_V0.0.4_o1" --to "dist/栖图_V0.0.4_gpu" --version "0.0.4" --flavor gpu --update 1
```

#### 差分升级文件夹结构

```
dist/栖图_V1.0.1_gpu_update1/
├── 栖图.exe                    <- 修改的文件
├── ui/dialogs/watermark_dialog.py   <- 修改的文件
├── core/new_feature.py         <- 新增的文件
├── _delete_files.txt           <- 需要删除的文件列表
└── _delta_report.txt           <- 差异报告
```

#### 自动化编译（可选）

如果你希望全自动编译，可以使用 Inno Setup 命令行：

```bash
# 先创建差分包
python build/build.py --flavor gpu --delta-from "dist/栖图_V1.0.0_gpu" --delta

# 然后自动编译（需要 Inno Setup 在 PATH 中）
cd "C:\Program Files (x86)\Inno Setup 6"
ISCC.exe "D:\code\BirdPictureManager\build\installer\update_V1.0.1_gpu_update1.iss"
```

### 传统方法：手动使用 update_installer.iss

如果 `build_delta.py` 不能满足需求，可以手动编辑 `update_installer.iss`：

1. **打开脚本**
   - 启动 Inno Setup
   - 打开 `build/installer/update_installer.iss`

2. **修改版本号**
   ```pascal
   #define MyAppVersion "1.0.1"
   ```

3. **设置 Flavor**
   ```pascal
   #define MyAppFlavor "gpu"
   ```

4. **设置 Update 编号**
   ```pascal
   #define MyAppUpdate "1"
   ```

5. **修改 MyAppDistDir**（重要！）
   ```pascal
   ; 改为绝对路径，指向差分升级文件夹
   #define MyAppDistDir "D:\code\BirdPictureManager\dist\栖图_V1.0.1_gpu_update1"
   ```

6. **编译**
   - 点击 `Build` → `Compile`

### 增量包版本升级流程

#### 场景：从 V1.0.0 升级到 V1.0.1

```bash
# 1. 打包完整版 V1.0.1 并创建升级包（一步完成）
python build/build.py --flavor gpu --delta-from "dist/栖图_V1.0.0_gpu" --delta

# 输出：
# - dist/栖图_V1.0.1_gpu/              <- 完整版（新用户安装）
# - dist/栖图_V1.0.1_gpu_update1/      <- 差分升级文件夹
# - build/installer/update_V1.0.1_gpu_update1.iss

# 2. 编译升级包
# 打开 Inno Setup → 打开 build/installer/update_V1.0.1_gpu_update1.iss
# 点击 Build → Compile
# 输出：build/installer/栖图_V1.0.1_gpu_update1.exe（老用户升级）
```

#### 场景：多版本升级路径

如果用户可能从多个旧版本升级，需要为每个版本制作增量包：

```bash
# V1.0.0 -> V1.0.2
python build/build.py --flavor gpu --delta-from "dist/栖图_V1.0.0_gpu" --delta
# 编译生成的 ISS 脚本

# V1.0.1 -> V1.0.2
python build/build.py --flavor gpu --delta-from "dist/栖图_V1.0.1_gpu" --delta
# 编译生成的 ISS 脚本
```

### update_installer.iss 与 newinstaller.iss 的区别

| 特性 | update_installer.iss | newinstaller.iss |
|------|---------------------|------------------|
| **用途** | 专用增量升级包 | 通用安装包（完整/增量） |
| **输出格式** | `栖图_Vx.x.x_gpu_update1.exe` | `栖图_Vx.x.x_gpu.exe` 或 `栖图_Vx.x.x_gpu_update1.exe` |
| **数据保护** | 自动保护 data/cache 目录 | 需要手动配置 |
| **更新检测** | 自动检测并提示 | 需要手动配置 |
| **使用场景** | 已知是升级场景 | 通用场景 |

### 推荐工作流

1. **开发完成，准备发布 V1.0.1**

2. **打包完整版**（供新用户下载）
   ```bash
   python build/build.py --flavor gpu
   ```
   - 使用 `newinstaller.iss` 编译
   - 输出：`栖图_V1.0.1_gpu.exe`

3. **生成增量包**（供老用户升级）
   ```bash
   python build/build.py --delta-from "dist/栖图_V1.0.0_gpu" --from-version "V1.0.0"
   ```
   - 查看生成的 `delta_report.txt`
   - 根据报告编辑 `update_installer.iss` 的 [Files] 段
   - 设置 `MyAppVersion=

---

## 打包流程详解

### 完整打包流程

```
1. 生成图标 (generate_icon.py)
   ↓
2. 可选：代码混淆 (pyarmor)
   ↓
3. PyInstaller 打包
   ↓
4. 清理 dist 目录 (删除测试文件、__pycache__ 等)
   ↓
5. 写入构建标记 (build_flavor.txt)
   ↓
6. 可选：计算增量文件列表
   ↓
7. 更新 iss 脚本
   ↓
8. Inno Setup 编译安装程序
```

### 增量包打包流程

```
1-5. 同完整包流程
   ↓
6. 对比旧版本，计算三类差异文件
   - 新增的文件 (added)
   - 修改的文件 (modified)
   - 删除的文件 (deleted)
   ↓
7. 重写 iss 文件的 [Files] 段
   - 添加新增的文件
   - 更新修改的文件
   ↓
8. 添加 [InstallDelete] 段
   - 标记需要删除的旧文件
   ↓
9. 更新 iss 文件的 MyAppFromVersion
   ↓
10. 生成增量报告
   ↓
11. Inno Setup 编译增量升级安装程序
```

### 增量包文件处理说明

增量升级包会智能处理三类文件：

| 类型 | 处理方式 | 说明 |
|------|----------|------|
| **新增** | 复制到新版本 | 旧版本中没有，新版本新增的文件 |
| **修改** | 覆盖旧文件 | 内容发生变化的文件（通过大小、时间戳、哈希值判断） |
| **删除** | 安装时删除 | 旧版本中有，但新版本不再需要的文件 |

**文件对比逻辑：**
1. 首先比较文件大小，不同则认为已修改
2. 大小相同则比较修改时间戳
3. 时间戳不同则计算 SHA1 哈希值进行精确对比
4. 在旧版本中存在但在新版本中不存在的文件标记为删除

---

## 打包依赖白名单

### 背景

本项目在开发环境中可以直接 `pip install` 后运行，但打包为 PyInstaller 程序时，部分第三方库会因为以下原因被漏收：

- 在函数内部动态导入
- 仅在 `try/except ImportError` 中按需导入
- 除 Python 代码外还依赖字体、映射表、配置等资源文件
- 依赖原生扩展、`.pyd`、`.dll` 或额外运行时文件

因此，是否"本地已安装成功"并不等于"打包后一定可用"。

### 当前已显式补入 `bird_picture_manager.spec` 的高风险依赖

这些库已经在 `build/bird_picture_manager.spec` 中做了显式收集：

| 依赖 | 用途 | 风险原因 | 当前处理 |
|------|------|----------|----------|
| `qtawesome` | UI 图标 | 依赖包内 `fonts` 资源 | `collect_submodules` + `collect_data_files` |
| `pypinyin` | 中文拼音排序 | 在 `folder_panel.py` 中存在动态导入 | `collect_submodules` + `collect_data_files` |
| `exiftool` | ExifTool Python 包兜底 | 之前有顶层导入，且属于可选第三方包 | `collect_submodules` + `collect_data_files` |
| `torch` | PyTorch 推理 | DLL、CUDA 依赖复杂 | 已做专项收集 |
| `ultralytics` | YOLO 模型推理 | 模型配置与资源较多 | `collect_submodules` + `collect_data_files` |
| `geopy` | 地理编码 | 可选导入 | `collect_submodules` + `collect_data_files` |
| `GPUtil` | GPU 监控 | 函数内导入 | `collect_submodules` + `collect_data_files` |
| `psutil` | 进程/系统信息 | 多处运行期导入 | `collect_submodules` + `collect_data_files` |
| `send2trash` | 回收站删除 | 可选导入 | `collect_submodules` + `collect_data_files` |

### 建议重点关注的依赖分类

#### 1. 必须显式收集

这类库一旦漏收，打包后容易直接缺模块或表现异常：

- `qtawesome`
- `pypinyin`
- `exiftool`
- `torch`
- `ultralytics`

#### 2. 建议显式收集

这类库很多时候 PyInstaller 能自动带上，但项目中存在动态导入、条件导入或回退逻辑，建议继续保留显式收集：

- `geopy`
- `GPUtil`
- `psutil`
- `send2trash`

#### 3. 一般可自动收集，但后续若报错可再专项补

- `rawpy`
- `exifread`
- `numpy`
- `opencv-python`
- `PyQt6`
- `PyQt6-WebEngine`

说明：

- `rawpy`、`opencv-python` 偏原生扩展，如果后续出现 `.pyd` / `.dll` 问题，需要单独补动态库
- `PyQt6-WebEngine` 当前已经在 `spec` 中做了专项处理

#### 4. 可选依赖，有回退逻辑

这类库即使未打进包，也不一定导致程序崩溃，但会触发功能降级或提示：

- `send2trash`
  说明：缺失时会回退到 Windows API 回收站删除方案
- `pypinyin`
  说明：缺失时会回退到英文排序，并弹出提示
- `GPUtil`
  说明：缺失时 GPU 监控信息可能不完整

### 当前打包环境核对建议

发布前建议在**打包所用的 Python 环境**中执行一次检查，而不是只看源码环境。

示例：

```bash
python -c "import importlib.util; mods=['pypinyin','qtawesome','geopy','GPUtil','psutil','send2trash','rawpy','exifread']; [print(m, bool(importlib.util.find_spec(m))) for m in mods]"
```

如果某个模块输出为 `False`，说明该环境本身就没有安装，打包脚本即使写了显式收集也无法带进去。

### 维护建议

后续新增第三方库时，优先按以下规则判断是否需要同步修改 `bird_picture_manager.spec`：

1. 如果库在函数内部导入，建议补 `hiddenimports`
2. 如果库带字体、图标、映射表、模板或配置文件，建议补 `collect_data_files`
3. 如果库依赖 `.dll`、`.pyd`、CUDA、原生扩展，建议额外检查动态库是否被带入
4. 如果库只是可选能力，代码里要保留明确的降级逻辑和用户提示

---

## 常见问题

### Q1: 打包时提示 "未检测到 PyQt6-WebEngine"

**解决**: 安装 PyQt6-WebEngine
```bash
pip install PyQt6-WebEngine
```

### Q2: 打包 GPU 版本时提示 "当前环境的 torch 不是 CUDA 版"

**解决**: 切换到安装了 CUDA 版 torch 的 Python 环境
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

### Q3: 增量包安装时提示 "未检测到已安装的软件版本"

**原因**: 目标电脑上没有安装旧版本，或者注册表信息丢失

**解决**: 
- 确保用户电脑上已安装指定的旧版本
- 或者提供完整安装包给用户

### Q4: 增量包安装时提示 "该升级包仅支持从 X 升级到 Y"

**原因**: 用户电脑上安装的版本与 `--from-version` 指定的版本不匹配

**解决**: 
- 确认用户当前版本
- 使用正确的 `--from-version` 参数重新打包

### Q5: 如何强制打包完整包（忽略 --delta-from）？

```bash
python build/build.py --delta-from "dist/BirdPictureManager_V1.0.0" --full
```

### Q6: 打包后的安装程序在哪里？

- **完整包**: `build/installer/栖图_V{版本号}.exe`
- **增量包**: `build/installer/栖图_从V{旧版本}升级_V{新版本}.exe`

### Q7: 如何清理旧的打包文件？

```bash
# 删除 dist 目录
rmdir /s /q dist

# 删除 build 工作目录
rmdir /s /q build\_pyi_work
```

---

## 版本命名规范

### 版本号格式

`V{主版本}.{次版本}.{修订版本}`

示例：
- `V1.0.0` - 初始版本
- `V1.0.1` - 修复版本
- `V1.1.0` - 功能更新
- `V2.0.0` - 重大更新

### 文件名规范

**完整包**: `栖图_V{版本号}.exe`

**增量包**: `栖图_从V{旧版本}升级_V{新版本}.exe`

---

## 注意事项

1. **备份旧版本**: 在打包新版本前，建议备份旧版本的 dist 目录，以便后续制作增量包

2. **版本一致性**: 确保 `--from-version` 参数与实际旧版本一致，否则用户无法正常升级

3. **多版本支持**: 如果用户可能从多个旧版本升级，需要为每个版本制作对应的增量包

4. **测试升级**: 发布前务必测试增量升级流程，确保升级后软件正常运行

5. **文件清理**: 打包脚本会自动清理 `__pycache__` 等临时文件，无需手动处理

---

## 技术支持

如有问题，请查看项目文档或联系开发团队。
