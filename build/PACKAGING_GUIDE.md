# BirdPictureManager 打包指南

## 目录

1. [环境准备](#环境准备)
2. [完整包打包](#完整包打包)
3. [增量升级包打包](#增量升级包打包)
4. [打包依赖白名单](#打包依赖白名单)
5. [常见问题](#常见问题)

***

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

***

## 完整包打包

### 基本打包

```bash
python build/build.py
```

输出位置：`dist/qitu_V{版本号}/`

### 带后缀的打包

```bash
# 打包测试版本
python build/build.py beta

# 打包 RC 版本
python build/build.py rc1
```

输出位置：`dist/qitu_beta_V{版本号}/`

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

***

## 增量升级包打包

### 什么是增量升级包？

增量升级包只包含相对于旧版本发生变化的文件，可以显著减小安装包体积，加快用户下载和安装速度。

### 增量包打包步骤

#### 1. 准备旧版本

确保旧版本的打包目录存在，例如：

```
dist/qitu_V0.0.4/
```

#### 2. 执行增量打包

```bash
python build/build.py --delta-from "dist/qitu_V0.0.4" --from-version "V0.0.4"
```

参数说明：

- `--delta-from`: 旧版本 dist 目录的完整路径
- `--from-version`: 旧版本号（如 V0.0.4）

#### 3. 生成文件

打包完成后会生成：

- **安装程序**: `build/installer/栖图_V0.0.4_update1.exe`
- **增量报告**: `dist/qitu_V0.0.4_update1/_delta_report.txt`

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

旧版本目录: D:\code\BirdPictureManager\dist\qitu_V0.0.4
新版本目录: D:\code\BirdPictureManager\dist\qitu_V0.0.4_update1
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

### 使用 build.py 打包升级包

`build.py` 支持多种方式创建升级包，从简单差分包到完整发布流程。

**自动检测update版本：**

打包脚本会自动从 `utils/system/app_info_manager.py` 中的 `APP_UPDATE` 变量读取update版本号，无需手动指定。

```python
# app_info_manager.py
APP_UPDATE = "update1"  # 设置update版本号，空字符串表示非升级版本
```

#### 方式一：完整发布流程（推荐）

使用 `--complete` 参数执行完整发布流程：打包 → 创建差分包 → 生成 zip → 更新 manifest

```bash
# 完整发布流程（自动检测update版本）
python build/build.py --delta-from "dist/qitu_V0.0.4_fr" --complete

# 输出：
# - dist/qitu_V0.0.4_update1/                    <- update1 完整包
# - build/installer/update_V0.0.4_update1.iss    <- ISS 脚本
# - build/installer/栖图_V0.0.4_gpu_update1.exe  <- 安装包
# - dist/qitu_V0.0.4_update1.zip                 <- GitHub 发布用 zip
# - dist/update_manifest.json                    <- 更新的版本清单
```

**工作流程：**

1. 自动从代码中读取 `APP_UPDATE` 版本号
2. 打包 update1 版本（生成 `dist/qitu_V0.0.4_update1/`）
3. 与旧版本（`dist/qitu_V0.0.4_fr/`）对比生成差分文件
4. 生成 InnoSetup ISS 脚本
5. 编译 ISS 生成 exe 安装包
6. 创建 zip 包（包含 exe + 差异清单）
7. 计算 zip 的 SHA256 哈希值
8. 更新 `update_manifest.json`

#### 方式二：打包并生成安装包

使用 `--package` 参数打包并生成安装包，但不生成 zip 和更新 manifest：

```bash
# 打包并生成安装包（自动检测update版本）
python build/build.py --delta-from "dist/qitu_V0.0.4_fr" --package

# 输出：
# - dist/qitu_V0.0.4_u1/                         <- update1 完整包
# - dist/qitu_V0.0.4_update1/                    <- 差异包
# - build/installer/update_V0.0.4_update1.iss    <- ISS 脚本
# - build/installer/栖图_V0.0.4_gpu_update1.exe  <- 安装包
```

#### 方式三：仅创建差分包

使用 `--delta` 参数只创建差分包，不编译安装包：

```bash
# 打包完整版 + 自动创建升级包（自动检测update版本）
python build/build.py --flavor gpu --delta-from "dist/qitu_V0.0.4_fr" --delta

# 输出：
# - dist/qitu_V0.0.4_update1/                    <- update1 完整包
# - build/installer/update_V0.0.4_update1.iss    <- 升级包 ISS 脚本
```

#### 参数说明

| 参数               | 说明                                       | 示例                    |
| ---------------- | ---------------------------------------- | --------------------- |
| `suffix`         | 文件名后缀（update编号，可选，默认自动检测）      | `update1`, `u1`       |
| `--flavor`       | CPU/GPU 版本                               | `gpu` 或 `cpu`         |
| `--delta-from`   | 旧版本目录（用于差分）                          | `dist/qitu_V0.0.4_fr` |
| `--complete`     | 完整发布流程（打包→差分→zip→manifest）          | 无需值                   |
| `--package`      | 打包并生成安装包（不生成zip）                    | 无需值                   |
| `--delta`        | 仅创建差分包（不编译安装包）                     | 无需值                   |
| `--from-version` | 旧版本号（可选）                             | `V0.0.4`              |

**注意：** 如果手动指定了 `suffix` 参数，将优先使用手动指定的值，而不是自动检测的值。

**三种模式对比：**

| 模式 | 参数 | 输出 |
|------|------|------|
| 仅差分包 | `--delta` | ISS脚本 + 差异文件 |
| 打包并生成安装包 | `--package` | ISS脚本 + 差异文件 + exe安装包 |
| 完整发布流程 | `--complete` | 以上所有 + zip包 + manifest更新 |

#### 单独使用 build\_delta.py

如果只想创建升级包（不打包完整版）：

**自动检测update版本：**

`build_delta.py` 会自动从 `utils/system/app_info_manager.py` 中的 `APP_UPDATE` 变量读取update版本号。

```bash
# 基本用法（自动检测update版本和参数，只生成差异文件和 ISS 脚本）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr"

# 生成 ISS 脚本并编译为 exe 安装包（不创建 zip）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --to "dist/qitu_V0.0.4_update1" --setup

# 完整发布流程（自动检测update版本）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --output-zip --update-manifest
```

**参数说明：**

| 参数                  | 说明                                           | 示例                    |
| ------------------- | -------------------------------------------- | --------------------- |
| `--from`            | 旧版本 dist 目录路径（必需）                            | `dist/qitu_V0.0.4_fr` |
| `--to`              | 新版本 dist 目录路径（可选，默认自动查找）                     | `dist/qitu_V0.0.4_update1` |
| `--version`         | 升级包版本号（可选，默认从目录名提取）                          | `0.0.4`               |
| `--update`          | update 编号（可选，默认自动检测）                        | `1`                   |
| `--setup`           | 生成 ISS 脚本并编译为 exe 安装包                        | -                     |
| `--output-zip`      | 输出为 zip 压缩包（与 --setup 互斥，优先）                 | -                     |
| `--update-manifest` | 同时更新 update\_manifest.json（需配合 --output-zip） | -                     |
| `--changelog`       | 更新日志内容（支持 \n 换行）                             | `"修复bug\n- 修复问题"`     |

**执行模式：**

1. **无** **`--setup`** **和** **`--output-zip`**：只生成差异文件和 ISS 脚本，不编译
2. **`--setup`**：生成 ISS 脚本并编译为 exe 安装包，不创建 zip
3. **`--output-zip`**：完整流程（生成 ISS、编译、创建 zip、可选更新 manifest）
4. **同时指定** **`--setup`** **和** **`--output-zip`**：`--output-zip` 优先，执行完整流程

**注意：** 如果手动指定了 `--update` 参数，将优先使用手动指定的值，而不是自动检测的值。

### GitHub 自动升级包（zip 格式）

从 V0.0.4 开始，支持生成 zip 格式的升级包，用于 GitHub Releases 自动升级系统。

#### 目录命名规则

- **完整包**：`dist/qitu_V0.0.4_fr`（fr = full release）
- **Update 包**：`dist/qitu_V0.0.4_update1`（update1 = update 1）

#### 一键打包流程（推荐）

`build_delta.py` 现在支持完整的打包流程，并自动检测update版本：

**设置update版本：**

在 `utils/system/app_info_manager.py` 中设置 `APP_UPDATE`：

```python
APP_UPDATE = "update1"  # 设置update版本号
```

**打包流程：**

```bash
# 1. 先打包完整版（生成 dist/qitu_V0.0.4_fr）
python build/build.py

# 2. 打包 update1 完整版（自动检测update版本，生成 dist/qitu_V0.0.4_update1）
python build/build.py

# 3. 创建差分包（自动查找 fr 和 update1 目录，自动检测update版本）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --output-zip --update-manifest

# 跨版本升级
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --to "dist/qitu_V0.0.5_fr" --output-zip --update-manifest

# 指定 changelog（从 ReleaseNote.md 自动读取）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --output-zip --update-manifest
```

**流程说明：**

1. 自动从代码中读取 `APP_UPDATE` 版本号
2. 自动查找旧版本（`fr` 目录）和新版本（`update1` 目录）
3. 计算新旧版本文件差异
4. 生成 Inno Setup ISS 脚本（`build/installer/update_V{x.x.x}_update{n}.iss`）
5. 自动调用 Inno Setup 编译生成 exe 安装包
6. 创建 zip 包（包含 exe + 差异清单）
7. 计算 zip 文件的 SHA256 哈希值
8. 从 `ReleaseNote.md` 自动读取changelog
9. 更新 `update_manifest.json`

#### 生成的文件

执行命令后会生成以下文件：

```
项目根目录/
├── build/
│   └── installer/
│       ├── update_V0.0.4_u1.iss           # Inno Setup 脚本
│       └── 栖图_V0.0.4_u1.exe             # 安装包（由 ISS 编译生成）
├── dist/
│   ├── qitu_V0.0.4_u1.zip                 # GitHub 发布用 zip 包
│   │   ├── 栖图_V0.0.4_u1.exe             # 安装包
│   │   ├── diff_V0.0.4_to_V0.0.4_u1.json  # 差异清单
│   │   └── build_flavor.txt               # 构建类型标记
│   └── update_manifest.json               # 版本清单（自动更新）
└── ...
```

#### zip 升级包内容

生成的 zip 文件包含：

```
qitu_V0.0.4_u1.zip
├── 栖图_V0.0.4_u1.exe                    # Inno Setup 安装包
├── diff_V0.0.4_to_V0.0.4_u1.json         # 差异文件清单
└── build_flavor.txt                       # 构建类型标记 (cpu/gpu)
```

**差异文件清单说明：**

从 V0.0.4 开始，升级包包含差异文件清单 `diff_V{旧版本}_to_V{新版本}.json`，用于：

1. **增量备份**：升级前只备份将被覆盖的文件，节省磁盘空间
2. **版本回退**：记录新增/删除的文件，支持回退到旧版本

清单文件格式：

```json
{
  "version": "1.0",
  "from_version": "0.0.4",
  "to_version": "0.0.5",
  "build_time": "2026-03-18T10:30:00",
  "affected_files": ["main.exe", "app/core/upgrade.py"],
  "new_files": ["app/modules/new_feature.py"],
  "deleted_files": ["app/deprecated/old_module.py"],
  "renamed_files": [{"from": "old.py", "to": "new.py"}]
}
```

清单文件生成位置：

- 本地打包时保存到：`/dist/diff/diff_V{旧版本}_to_V{新版本}.json`
- 随升级包一起上传到 GitHub Releases
- 用户升级时下载到：`%LOCALAPPDATA%/栖图/cache/update/diff_V{旧版本}_to_V{新版本}.json`

#### update\_manifest.json 结构

自动生成的 manifest 文件格式：

```json
{
  "latest_version": "0.0.5_update1",
  "release_date": "2026-03-15",
  "releases": {
    "0.0.4": {
      "base_version": "0.0.4",
      "updates": {
        "1": {
          "version": "0.0.4_update1",
          "package": "栖图_V0.0.4_update1.zip",
          "hash": "sha256:abc123...",
          "size": 10485760
        }
      }
    },
    "0.0.5": {
      "base_version": "0.0.5",
      "cross_upgrade": {
        "from_base": "0.0.4",
        "package": "栖图_V0.0.5.zip",
        "hash": "sha256:def456...",
        "size": 52428800
      },
      "updates": {
        "1": {
          "version": "0.0.5_update1",
          "package": "栖图_V0.0.5_update1.zip",
          "hash": "sha256:ghi789...",
          "size": 10240000
        }
      }
    }
  }
}
```

#### 升级包类型说明

| 类型             | 说明           | 示例                       |
| -------------- | ------------ | ------------------------ |
| **同版本 update** | 同一基础版本内的增量更新 | V0.0.4 → V0.0.4\_update1 |
| **跨版本升级**      | 从旧大版本升级到新版本  | V0.0.4 → V0.0.5          |

#### GitHub 发布流程

1. **打包新版本**
   ```bash
   # 1. 打包完整版
   python build/build.py

   # 2. 生成 zip 升级包并更新 manifest
   python build/build_delta.py --from "dist/qitu_V0.0.4" --output-zip --update-manifest
   ```
2. **上传到 GitHub Releases**
   - 上传 `qitu_V0.0.4.exe`（完整安装包）
   - 上传 `qitu_V0.0.4.zip`（跨版本升级包，如果有）
   - 上传 `qitu_V0.0.4_update1.zip`（同版本增量包）
   - 上传 `diff_V0.0.4_to_V0.0.4_update1.json`（差异文件清单，**重要**）
   - 上传 `update_manifest.json`（版本清单）
     **注意**：差异清单文件 `diff_V{旧版本}_to_V{新版本}.json` 必须和升级包一起上传，用于升级时的增量备份和版本回退功能。
3. **配置自动更新**
   - 在 `update/update_config.py` 中设置 GitHub 仓库信息
   - 软件启动时会自动检查 GitHub 上的最新版本

#### 测试升级包（不执行实际替换）

在发布前，可以使用测试模式验证升级包是否能正确下载和解压：

```bash
# 手动测试升级流程（不执行文件替换）
python update/update_launcher.py --plan "C:\Users\xxx\AppData\Local\栖图\cache\update\update_plan.json" --test
```

测试模式特点：

- **下载**：正常下载所有升级包到缓存目录
- **解压**：正常解压 zip 文件
- **跳过**：不执行实际的文件替换操作
- **保留**：不清理临时文件，方便检查
- **不启动**：不会启动主程序

测试完成后，可以检查缓存目录中的文件：

```
%LOCALAPPDATA%\qitu\cache\update\
├── qitu_V0.0.4.zip              # 下载的升级包
├── qitu_V0.0.4_update1.zip      # 下载的升级包
└── update_plan.json             # 升级计划
```

#### 升级包验证清单

发布前请确认：

- [ ] zip 文件可以正常解压
- [ ] `_delete_files.txt` 包含正确的删除列表
- [ ] `diff_V{旧版本}_to_V{新版本}.json` 差异清单包含正确的文件列表
- [ ] `build_flavor.txt` 标记正确（cpu/gpu）
- [ ] `update_manifest.json` 中的 hash 和 size 正确
- [ ] 测试模式可以正常下载所有升级包
- [ ] 升级包大小合理（不应超过完整包）

#### 版本回退功能

从 V0.0.4 开始，支持版本回退功能：

**工作原理：**

1. 升级前根据差异清单只备份将被覆盖的文件（增量备份）
2. 升级完成后记录升级历史
3. 用户可以在设置中选择回退到之前的版本
4. 回退时还原备份的文件，删除升级时新增的文件

**使用场景：**

- 升级后出现兼容性问题
- 新功能不稳定需要回退
- 用户偏好旧版本界面

**注意事项：**

- 回退只影响程序文件，不删除用户数据（数据库、配置等）
- 回退后需要重启程序才能生效
- 差异清单文件必须正确上传，否则无法进行增量备份和回退

#### 差分升级文件夹结构

```
dist/qitu_V0.0.4_gpu_update1/
├── qitu.exe                    <- 修改的文件
├── ui/dialogs/watermark_dialog.py   <- 修改的文件
├── core/new_feature.py         <- 新增的文件
├── _delete_files.txt           <- 需要删除的文件列表
└── _delta_report.txt           <- 差异报告
```

#### 自动化编译（可选）

如果你希望全自动编译，可以使用 Inno Setup 命令行：

```bash
# 先创建差分包
python build/build.py --flavor gpu --delta-from "dist/qitu_V0.0.4_gpu" --delta

# 然后自动编译（需要 Inno Setup 在 PATH 中）
cd "C:\Program Files (x86)\Inno Setup 6"
ISCC.exe "D:\code\BirdPictureManager\build\installer\update_V0.0.4_gpu_update1.iss"
```

### 传统方法：手动使用 update\_installer.iss

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
   #define MyAppDistDir "D:\code\BirdPictureManager\dist\qitu_V0.0.4_gpu_update1"
   ```
6. **编译**
   - 点击 `Build` → `Compile`

### 增量包版本升级流程

#### 场景：从 V0.0.4 升级到 V0.0.4\_update1

```bash
# 1. 打包完整版 V0.0.4_update1 并创建升级包（一步完成）
python build/build.py --flavor gpu --delta-from "dist/qitu_V0.0.4_gpu" --delta

# 输出：
# - dist/qitu_V0.0.4_gpu/              <- 完整版（新用户安装）
# - dist/qitu_V0.0.4_gpu_update1/      <- 差分升级文件夹
# - build/installer/update_V0.0.4_gpu_update1.iss

# 2. 编译升级包
# 打开 Inno Setup → 打开 build/installer/update_V0.0.4_gpu_update1.iss
# 点击 Build → Compile
# 输出：build/installer/qitu_V0.0.4_gpu_update1.exe（老用户升级）
```

#### 场景：多版本升级路径

如果用户可能从多个旧版本升级，需要为每个版本制作增量包：

```bash
# V0.0.4 -> V0.0.4_update2
python build/build.py --flavor gpu --delta-from "dist/qitu_V0.0.4_gpu" --update 2 --delta
# 编译生成的 ISS 脚本

# V0.0.4_update1 -> V0.0.4_update2
python build/build.py --flavor gpu --delta-from "dist/qitu_V0.0.4_gpu_update1" --update 2 --delta
# 编译生成的 ISS 脚本
```

### update\_installer.iss 与 newinstaller.iss 的区别

| 特性       | update\_installer.iss       | newinstaller.iss                                  |
| -------- | --------------------------- | ------------------------------------------------- |
| **用途**   | 专用增量升级包                     | 通用安装包（完整/增量）                                      |
| **输出格式** | `栖图_Vx.x.x_gpu_update1.exe` | `栖图_Vx.x.x_gpu.exe` 或 `栖图_Vx.x.x_gpu_update1.exe` |
| **数据保护** | 自动保护 data/cache 目录          | 需要手动配置                                            |
| **更新检测** | 自动检测并提示                     | 需要手动配置                                            |
| **使用场景** | 已知是升级场景                     | 通用场景                                              |

### 推荐工作流

1. **开发完成，准备发布 V0.0.4\_update1**
2. **打包完整版**（供新用户下载）
   ```bash
   python build/build.py --flavor gpu
   ```
   - 使用 `newinstaller.iss` 编译
   - 输出：`qitu_V0.0.4_gpu.exe`
3. **生成增量包**（供老用户升级）
   ```bash
   python build/build.py --delta-from "dist/qitu_V0.0.4_gpu" --from-version "V0.0.4"
   ```
   - 查看生成的 `delta_report.txt`
   - 根据报告编辑 `update_installer.iss` 的 \[Files] 段
   - 设置 \`MyAppVersion=

***

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

| 类型     | 处理方式   | 说明                        |
| ------ | ------ | ------------------------- |
| **新增** | 复制到新版本 | 旧版本中没有，新版本新增的文件           |
| **修改** | 覆盖旧文件  | 内容发生变化的文件（通过大小、时间戳、哈希值判断） |
| **删除** | 安装时删除  | 旧版本中有，但新版本不再需要的文件         |

**文件对比逻辑：**

1. 首先比较文件大小，不同则认为已修改
2. 大小相同则比较修改时间戳
3. 时间戳不同则计算 SHA1 哈希值进行精确对比
4. 在旧版本中存在但在新版本中不存在的文件标记为删除

***

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

| 依赖            | 用途                  | 风险原因                        | 当前处理                                        |
| ------------- | ------------------- | --------------------------- | ------------------------------------------- |
| `qtawesome`   | UI 图标               | 依赖包内 `fonts` 资源             | `collect_submodules` + `collect_data_files` |
| `pypinyin`    | 中文拼音排序              | 在 `folder_panel.py` 中存在动态导入 | `collect_submodules` + `collect_data_files` |
| `exiftool`    | ExifTool Python 包兜底 | 之前有顶层导入，且属于可选第三方包           | `collect_submodules` + `collect_data_files` |
| `torch`       | PyTorch 推理          | DLL、CUDA 依赖复杂               | 已做专项收集                                      |
| `ultralytics` | YOLO 模型推理           | 模型配置与资源较多                   | `collect_submodules` + `collect_data_files` |
| `geopy`       | 地理编码                | 可选导入                        | `collect_submodules` + `collect_data_files` |
| `GPUtil`      | GPU 监控              | 函数内导入                       | `collect_submodules` + `collect_data_files` |
| `psutil`      | 进程/系统信息             | 多处运行期导入                     | `collect_submodules` + `collect_data_files` |
| `send2trash`  | 回收站删除               | 可选导入                        | `collect_submodules` + `collect_data_files` |

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

***

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
python build/build.py --delta-from "dist/qitu_V0.0.4" --full
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

***

## 版本命名规范

### 版本号格式

`V{主版本}.{次版本}.{修订版本}`

示例：

- `V0.0.4` - 当前版本
- `V0.0.4_update1` - 修复版本
- `V1.1.0` - 功能更新
- `V2.0.0` - 重大更新

### 文件名规范

**完整包**: `栖图_V{版本号}.exe`

**增量包**: `栖图_从V{旧版本}升级_V{新版本}.exe`

***

## 注意事项

1. **备份旧版本**: 在打包新版本前，建议备份旧版本的 dist 目录，以便后续制作增量包
2. **版本一致性**: 确保 `--from-version` 参数与实际旧版本一致，否则用户无法正常升级
3. **多版本支持**: 如果用户可能从多个旧版本升级，需要为每个版本制作对应的增量包
4. **测试升级**: 发布前务必测试增量升级流程，确保升级后软件正常运行
5. **文件清理**: 打包脚本会自动清理 `__pycache__` 等临时文件，无需手动处理

***

## 技术支持

如有问题，请查看项目文档或联系开发团队。
