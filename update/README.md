# 栖图自动升级系统开发文档

## 1. 系统概述

### 1.1 功能目标
实现栖图软件的自动升级功能，支持：
- 后台检测新版本
- 显示更新提示弹窗
- 支持多次升级链式更新
- 下载并安装更新包
- 自动重启程序

### 1.2 核心特性
1. **后台检测**：软件启动时后台检查更新
2. **弹窗提示**：显示新版本特性和操作按钮
3. **链式升级**：支持跨多个版本的连续升级
4. **进度显示**：下载和安装进度可视化
5. **自动清理**：升级完成后清理临时文件
6. **链路测试**：支持测试模式验证升级链路

## 2. 架构设计

### 2.1 模块结构
```
update/
├── __init__.py                 # 模块初始化
├── README.md                   # 开发文档
├── update_manager.py           # 升级管理器（核心协调）
├── update_checker.py           # 版本检查模块
├── update_downloader.py        # 下载模块
├── update_installer.py         # 安装模块
├── update_dialog.py            # 更新提示对话框
├── update_progress_dialog.py   # 升级进度对话框
├── update_launcher.py          # 升级启动器（独立进程）
└── update_config.py            # 配置文件
```

### 2.2 升级流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        升级流程图                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐                                                │
│  │ 软件启动    │                                                │
│  └──────┬──────┘                                                │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────────┐                                            │
│  │ 后台检查更新    │──────┐                                      │
│  │ (UpdateChecker) │      │ 无更新                               │
│  └────────┬────────┘      └──────> 结束                          │
│           │                                                     │
│           │ 有更新                                               │
│           ▼                                                     │
│  ┌─────────────────┐                                            │
│  │ 显示更新对话框  │                                            │
│  │ (UpdateDialog)  │                                            │
│  └────────┬────────┘                                            │
│           │                                                     │
│     ┌─────┼─────┐                                               │
│     │     │     │                                               │
│     ▼     ▼     ▼                                               │
│   忽略   开始  取消                                              │
│   当前   升级                                                    │
│   版本                                                            │
│     │     │                                                       │
│     │     ▼                                                       │
│     │  ┌─────────────────┐                                        │
│     │  │ 退出主程序      │                                        │
│     │  │ 启动升级器      │                                        │
│     │  │ (UpdateLauncher)│                                        │
│     │  └────────┬────────┘                                        │
│     │           │                                                 │
│     │           ▼                                                 │
│     │  ┌─────────────────┐                                        │
│     │  │ 显示进度对话框  │                                        │
│     │  │ (ProgressDialog)│                                        │
│     │  └────────┬────────┘                                        │
│     │           │                                                 │
│     │           ▼                                                 │
│     │  ┌─────────────────┐                                        │
│     │  │ 下载所有升级包  │                                        │
│     │  │ (Downloader)    │                                        │
│     │  │ -> /cache/update│                                        │
│     │  └────────┬────────┘                                        │
│     │           │                                                 │
│     │           ▼                                                 │
│     │  ┌─────────────────┐                                        │
│     │  │ 按顺序安装      │                                        │
│     │  │ (Installer)     │                                        │
│     │  └────────┬────────┘                                        │
│     │           │                                                 │
│     │           ▼                                                 │
│     │  ┌─────────────────┐                                        │
│     │  │ 清理临时文件    │                                        │
│     │  │ 启动主程序      │                                        │
│     │  └─────────────────┘                                        │
│     │                                                             │
│     └────────────────────────────────────────────────────────>   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 详细设计

### 3.1 版本号解析

```python
# 版本号格式
"0.0.4"          # 基础版本
"0.0.4_update1"  # 增量版本
"0.0.4_update2"  # 增量版本

# 解析函数
parse_version("0.0.4_update2") -> {
    "base": "0.0.4",
    "update": 2,
    "full": "0.0.4_update2"
}
```

### 3.2 升级路径计算

```python
# 示例：从 0.0.4_update1 升级到 0.0.5_update2
calculate_upgrade_steps("0.0.4_update1", "0.0.5_update2")

# 返回：
[
    {
        "from": "0.0.4_update1",
        "to": "0.0.5",
        "package": "qitu_V0.0.5.zip",
        "url": "https://github.com/.../qitu_V0.0.5.zip",
        "size": 50000000,
        "hash": "sha256:xxx"
    },
    {
        "from": "0.0.5",
        "to": "0.0.5_update2",
        "package": "qitu_V0.0.5_update2.zip",
        "url": "https://github.com/.../qitu_V0.0.5_update2.zip",
        "size": 10000000,
        "hash": "sha256:yyy"
    }
]
```

### 3.3 update_manifest.json 结构详解

`update_manifest.json` 是自动升级系统的核心配置文件，存储在 GitHub Releases 中，用于描述所有可用版本和升级包信息。

#### 完整结构示例

```json
{
  "latest_version": "0.0.5_update2",
  "release_date": "2026-03-15",
  "changelog": "## V0.0.5_update2\n- 修复xxx问题\n- 新增xxx功能",
  "force_update": false,
  "min_supported_version": "0.0.1",
  "releases": {
    "0.0.4": {
      "base_version": "0.0.4",
      "cross_upgrade": {},
      "updates": {
        "1": {
          "version": "0.0.4_update1",
          "package": "qitu_V0.0.4_update1.zip",
          "size": 10000000,
          "hash": "sha256:abc123..."
        }
      }
    },
    "0.0.5": {
      "base_version": "0.0.5",
      "cross_upgrade": {
        "from_base": "0.0.4",
        "package": "qitu_V0.0.5.zip",
        "size": 50000000,
        "hash": "sha256:def456..."
      },
      "updates": {
        "1": {
          "version": "0.0.5_update1",
          "package": "qitu_V0.0.5_update1.zip",
          "size": 8000000,
          "hash": "sha256:ghi789..."
        },
        "2": {
          "version": "0.0.5_update2",
          "package": "qitu_V0.0.5_update2.zip",
          "size": 12000000,
          "hash": "sha256:jkl012..."
        }
      }
    }
  }
}
```

#### 字段说明

##### 根级别字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `latest_version` | string | 是 | 当前最新版本号，格式为 `x.x.x` 或 `x.x.x_updateN` |
| `release_date` | string | 是 | 最新版本发布日期，格式 `YYYY-MM-DD` |
| `changelog` | string | 否 | 最新版本的更新日志，支持 Markdown 格式 |
| `force_update` | boolean | 否 | 是否强制用户更新，默认为 `false` |
| `min_supported_version` | string | 否 | 最低支持的版本，低于此版本必须强制升级 |
| `releases` | object | 是 | 所有发布的版本信息，键为版本号（如 `0.0.4`） |

##### releases 对象结构

每个基础版本（如 `0.0.4`、`0.0.5`）对应一个对象：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `base_version` | string | 是 | 基础版本号，与父级键一致 |
| `cross_upgrade` | object | 否 | 跨版本升级包信息（从其他大版本升级到此版本） |
| `updates` | object | 否 | 该版本内的增量更新包（`update1`、`update2` 等） |

##### cross_upgrade 对象结构

用于从旧大版本升级到新大版本：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `from_base` | string | 是 | 来源基础版本（如 `0.0.4`） |
| `package` | string | 是 | 升级包文件名（如 `qitu_V0.0.5.zip`） |
| `size` | integer | 是 | 文件大小（字节） |
| `hash` | string | 是 | 文件 SHA256 哈希值，格式 `sha256:xxx` |

##### updates 对象结构

键为 update 编号（如 `1`、`2`），值为对象：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | string | 是 | 完整版本号（如 `0.0.4_update1`） |
| `package` | string | 是 | 升级包文件名（如 `qitu_V0.0.4_update1.zip`） |
| `size` | integer | 是 | 文件大小（字节） |
| `hash` | string | 是 | 文件 SHA256 哈希值，格式 `sha256:xxx` |

#### 版本类型说明

**1. 初始版本**
```json
{
  "latest_version": "0.0.4",
  "releases": {
    "0.0.4": {
      "base_version": "0.0.4",
      "cross_upgrade": {},
      "updates": {}
    }
  }
}
```

**2. 同版本内的 update（增量更新）**
```json
{
  "latest_version": "0.0.4_update1",
  "releases": {
    "0.0.4": {
      "base_version": "0.0.4",
      "cross_upgrade": {},
      "updates": {
        "1": {
          "version": "0.0.4_update1",
          "package": "qitu_V0.0.4_update1.zip",
          "size": 10240000,
          "hash": "sha256:xxx"
        }
      }
    }
  }
}
```

**3. 跨版本升级**
```json
{
  "latest_version": "0.0.5",
  "releases": {
    "0.0.4": { ... },
    "0.0.5": {
      "base_version": "0.0.5",
      "cross_upgrade": {
        "from_base": "0.0.4",
        "package": "qitu_V0.0.5.zip",
        "size": 52428800,
        "hash": "sha256:xxx"
      },
      "updates": {}
    }
  }
}
```

#### 文件位置

- **本地路径**: `dist/update_manifest.json`
- **GitHub URL**: `https://github.com/{owner}/{repo}/releases/latest/download/update_manifest.json`

#### 自动生成

##### 完整打包流程（推荐）

使用 `build_delta.py` 一键完成：创建差分包 → 生成 ISS 脚本 → 编译安装包 → 创建 zip → 更新 manifest

**自动检测update版本：**

打包脚本会自动从 `utils/system/app_info_manager.py` 中的 `APP_UPDATE` 变量读取update版本号。

```python
# 在 app_info_manager.py 中设置
APP_UPDATE = "update1"  # 设置update版本号
```

**目录命名规则：**
- 完整包：`dist/qitu_V0.0.4_fr`（fr = full release）
- Update 包：`dist/qitu_V0.0.4_update1`（update1 = update 1）

```bash
# 1. 先打包完整版（生成 dist/qitu_V0.0.4_fr）
python build/build.py

# 2. 打包 update1 完整版（自动检测update版本，生成 dist/qitu_V0.0.4_update1）
python build/build.py

# 3. 创建差分包（自动查找 fr 和 update1 目录，自动检测update版本）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --output-zip --update-manifest

# 跨版本升级（从 V0.0.4 升级到 V0.0.5）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --to "dist/qitu_V0.0.5_fr" --output-zip --update-manifest

# changelog 从 ReleaseNote.md 自动读取
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --output-zip --update-manifest
```

##### 分步打包流程

如果不需要创建 zip 包或只想生成 exe 安装包：

**使用 build.py（推荐）：**

```bash
# 完整发布流程（打包 → 差分 → zip → manifest）
python build/build.py --delta-from "dist/qitu_V0.0.4_fr" --complete

# 打包并生成安装包（不生成zip）
python build/build.py --delta-from "dist/qitu_V0.0.4_fr" --package

# 仅创建差分包（不编译安装包）
python build/build.py --delta-from "dist/qitu_V0.0.4_fr" --delta
```

**使用 build_delta.py：**

```bash
# 只生成差异文件和 ISS 脚本（不编译）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --to "dist/qitu_V0.0.4_update1"

# 生成 ISS 脚本并编译为 exe 安装包（不创建 zip）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --to "dist/qitu_V0.0.4_update1" --setup

# 完整流程（生成 ISS、编译、创建 zip、更新 manifest）
python build/build_delta.py --from "dist/qitu_V0.0.4_fr" --output-zip --update-manifest
```

**build.py 三种模式对比：**

| 模式 | 参数 | 输出 |
|------|------|------|
| 仅差分包 | `--delta` | ISS脚本 + 差异文件 |
| 打包并生成安装包 | `--package` | ISS脚本 + 差异文件 + exe安装包 |
| 完整发布流程 | `--complete` | 以上所有 + zip包 + manifest更新 |

**参数说明：**

| 参数 | 说明 | 示例 |
|------|------|------|
| `--from` | 旧版本 dist 目录路径（必需） | `dist/qitu_V0.0.4_fr` |
| `--to` | 新版本 dist 目录路径（可选，默认自动查找） | `dist/qitu_V0.0.4_update1` |
| `--version` | 升级包版本号（可选，默认从目录名提取） | `0.0.4` |
| `--update` | update 编号（可选，默认自动检测） | `1` |
| `--setup` | 生成 ISS 脚本并编译为 exe 安装包 | - |
| `--output-zip` | 输出为 zip 压缩包（与 --setup 互斥，优先） | - |
| `--update-manifest` | 同时更新 update_manifest.json（需配合 --output-zip） | - |
| `--changelog` | 更新日志内容（可选，默认从 ReleaseNote.md 读取） | `"修复bug\n- 修复问题"` |

**执行模式：**

1. **无 `--setup` 和 `--output-zip`**：只生成差异文件和 ISS 脚本，不编译
2. **`--setup`**：生成 ISS 脚本并编译为 exe 安装包，不创建 zip
3. **`--output-zip`**：完整流程（生成 ISS、编译、创建 zip、可选更新 manifest）
4. **同时指定 `--setup` 和 `--output-zip`**：`--output-zip` 优先，执行完整流程

**流程说明：**
1. 自动从代码中读取 `APP_UPDATE` 版本号
2. 自动查找旧版本（`fr` 目录）和新版本（`update1` 目录）
3. 计算新旧版本文件差异
4. 生成 Inno Setup ISS 脚本
5. 编译 ISS 生成 exe 安装包
6. 创建 zip 包（包含 exe + 差异清单）
7. 计算 zip 的 SHA256 哈希值
8. 从 `ReleaseNote.md` 自动读取changelog
9. 更新 `update_manifest.json`

**输出文件：**
- `build/installer/update_V0.0.4_update1.iss` - Inno Setup 脚本
- `build/installer/栖图_V0.0.4_gpu_update1.exe` - 安装包
- `dist/qitu_V0.0.4_update1.zip` - GitHub 发布用 zip 包
- `dist/update_manifest.json` - 版本清单

**上传到 GitHub Releases：**
- `qitu_V0.0.4_u1.zip`（必须）
- `update_manifest.json`（必须）

### 3.4 链路测试模式

为了验证升级链路的完整性，系统支持**链路测试模式**。

#### 测试版本命名规则

- 测试版本包以 `_test` 结尾，例如：`qitu_V0.0.5_test.zip`
- 测试版本的升级包内容为空（仅用于测试下载和安装流程）
- 只有启用链路测试模式，客户端才能识别和下载测试版本

#### 启用测试模式

在 `update_config.py` 中设置：

```python
# 链路测试模式
# 开启后，可以识别和下载以 _test 结尾的测试版本
TEST_MODE = True  # 默认 False
```

#### 测试版本 manifest 示例

```json
{
  "latest_version": "0.0.5_update1_test",
  "release_date": "2026-03-15",
  "changelog": "## 测试版本 V0.0.5_update1_test\n- 用于测试升级链路",
  "force_update": false,
  "releases": {
    "0.0.4": {
      "base_version": "0.0.4",
      "cross_upgrade": {},
      "updates": {}
    },
    "0.0.5": {
      "base_version": "0.0.5",
      "cross_upgrade": {
        "from_base": "0.0.4",
        "package": "qitu_V0.0.5_test.zip",
        "size": 1024,
        "hash": "sha256:xxx"
      },
      "updates": {
        "1": {
          "version": "0.0.5_update1_test",
          "package": "qitu_V0.0.5_update1_test.zip",
          "size": 1024,
          "hash": "sha256:yyy"
        }
      }
    }
  }
}
```

#### 测试流程

1. **生成测试包**
   ```bash
   # 创建一个空的测试包
   python -c "import zipfile; zipfile.ZipFile('dist/qitu_V0.0.5_test.zip', 'w').close()"
   ```

2. **上传测试包到 GitHub Releases**
   - `qitu_V0.0.5_test.zip`
   - `update_manifest.json`（包含测试版本信息）

3. **客户端启用测试模式**
   - 修改 `update_config.py` 中的 `TEST_MODE = True`
   - 或设置环境变量 `QITU_UPDATE_TEST_MODE=1`

4. **执行测试**
   - 客户端会检测到 `0.0.5_test` 版本
   - 下载测试包（空文件，速度很快）
   - 验证升级流程是否正常

#### 注意事项

1. **测试版本不会覆盖正式版本**
   - 测试版本号包含 `_test` 后缀
   - 正式版本不会识别测试版本

2. **测试包内容为空**
   - 仅用于验证下载和安装流程
   - 不会实际修改程序文件

3. **生产环境禁用测试模式**
   - 发布前确保 `TEST_MODE = False`
   - 避免用户误下载测试版本

## 4. 模块接口设计

### 4.1 UpdateManager（升级管理器）

```python
class UpdateManager(QObject):
    """
    升级管理器 - 协调整个升级流程
    """
    
    # 信号定义
    update_available = pyqtSignal(dict)      # 发现新版本
    update_ignored = pyqtSignal(str)          # 用户忽略当前版本
    update_cancelled = pyqtSignal()           # 用户取消升级
    update_started = pyqtSignal()             # 开始升级
    download_progress = pyqtSignal(int)       # 下载进度 0-100
    install_progress = pyqtSignal(int, str)   # 安装进度 (百分比, 当前步骤)
    update_completed = pyqtSignal()           # 升级完成
    update_error = pyqtSignal(str)            # 升级错误
    
    def __init__(self, parent=None):
        """
        初始化升级管理器
        
        参数:
            parent: 父对象
        """
        pass
    
    def check_update(self, silent: bool = False) -> None:
        """
        检查更新
        
        参数:
            silent: 是否静默检查（不弹窗提示）
        """
        pass
    
    def start_update(self, update_info: dict) -> None:
        """
        开始升级流程
        
        参数:
            update_info: 更新信息字典
        """
        pass
    
    def ignore_version(self, version: str) -> None:
        """
        忽略指定版本
        
        参数:
            version: 要忽略的版本号
        """
        pass
    
    def is_version_ignored(self, version: str) -> bool:
        """
        检查版本是否被忽略
        
        参数:
            version: 版本号
            
        返回:
            是否被忽略
        """
        pass
```

### 4.2 UpdateChecker（版本检查器）

```python
class UpdateChecker(QObject):
    """
    版本检查器 - 从 GitHub 获取最新版本信息
    """
    
    check_completed = pyqtSignal(dict)   # 检查完成
    check_failed = pyqtSignal(str)       # 检查失败
    
    def __init__(self):
        pass
    
    def check_for_updates(self, current_version: str) -> None:
        """
        检查是否有更新
        
        参数:
            current_version: 当前版本号
        """
        pass
    
    def parse_version(self, version_str: str) -> dict:
        """
        解析版本号
        
        参数:
            version_str: 版本号字符串
            
        返回:
            解析后的版本信息字典
        """
        pass
    
    def compare_versions(self, v1: str, v2: str) -> int:
        """
        比较两个版本号
        
        参数:
            v1: 版本1
            v2: 版本2
            
        返回:
            -1: v1 < v2
             0: v1 = v2
             1: v1 > v2
        """
        pass
    
    def calculate_upgrade_path(self, current: str, target: str, manifest: dict) -> list:
        """
        计算升级路径
        
        参数:
            current: 当前版本
            target: 目标版本
            manifest: 版本清单
            
        返回:
            升级步骤列表
        """
        pass
```

### 4.3 UpdateDownloader（下载器）

```python
class UpdateDownloader(QObject):
    """
    下载器 - 负责下载升级包
    """
    
    download_progress = pyqtSignal(int)           # 下载进度 0-100
    download_completed = pyqtSignal(str)          # 下载完成（文件路径）
    download_failed = pyqtSignal(str)             # 下载失败
    
    def __init__(self, download_dir: str):
        """
        初始化下载器
        
        参数:
            download_dir: 下载目录
        """
        pass
    
    def download_package(self, url: str, filename: str, expected_hash: str = None) -> None:
        """
        下载升级包
        
        参数:
            url: 下载地址
            filename: 保存文件名
            expected_hash: 期望的文件哈希值
        """
        pass
    
    def download_packages(self, packages: list) -> None:
        """
        批量下载多个升级包
        
        参数:
            packages: 升级包信息列表
        """
        pass
    
    def cancel_download(self) -> None:
        """取消当前下载"""
        pass
```

### 4.4 UpdateInstaller（安装器）

```python
class UpdateInstaller(QObject):
    """
    安装器 - 负责安装升级包
    """
    
    install_progress = pyqtSignal(int, str)   # 安装进度 (百分比, 描述)
    install_completed = pyqtSignal(list)      # 安装完成（返回受影响的文件列表）
    install_failed = pyqtSignal(str)          # 安装失败
    
    def __init__(self, install_dir: str):
        """
        初始化安装器
        
        参数:
            install_dir: 安装目录
        """
        pass
    
    def install_package(self, package_path: str) -> None:
        """
        安装单个升级包
        
        参数:
            package_path: 升级包路径
        """
        pass
    
    def install_packages(self, package_paths: list) -> None:
        """
        按顺序安装多个升级包
        
        参数:
            package_paths: 升级包路径列表
        """
        pass
    
    def cancel_install(self) -> None:
        """取消当前安装"""
        pass
```

### 4.5 UpdateDialog（更新提示对话框）

```python
class UpdateDialog(QDialog):
    """
    更新提示对话框 - 显示新版本信息和操作按钮
    """
    
    ignore_clicked = pyqtSignal()     # 点击"忽略此版本"
    upgrade_clicked = pyqtSignal()    # 点击"立即升级"
    cancel_clicked = pyqtSignal()     # 点击"取消"
    
    def __init__(self, update_info: dict, parent=None):
        """
        初始化对话框
        
        参数:
            update_info: 更新信息字典
            parent: 父窗口
        """
        pass
    
    def set_update_info(self, update_info: dict) -> None:
        """
        设置更新信息
        
        参数:
            update_info: 更新信息字典
        """
        pass
```

### 4.6 UpdateProgressDialog（升级进度对话框）

```python
class UpdateProgressDialog(QDialog):
    """
    升级进度对话框 - 显示下载和安装进度
    """
    
    cancel_requested = pyqtSignal()   # 用户请求取消
    
    def __init__(self, total_steps: int = 1, parent=None):
        """
        初始化对话框
        
        参数:
            total_steps: 总升级步骤数
            parent: 父窗口
        """
        pass
    
    def set_phase(self, phase: str) -> None:
        """
        设置当前阶段
        
        参数:
            phase: 阶段名称（"下载"、"安装"等）
        """
        pass
    
    def set_download_progress(self, progress: int) -> None:
        """
        设置下载进度
        
        参数:
            progress: 进度百分比 0-100
        """
        pass
    
    def set_install_progress(self, progress: int, description: str) -> None:
        """
        设置安装进度
        
        参数:
            progress: 进度百分比 0-100
            description: 进度描述
        """
        pass
    
    def set_current_file(self, filename: str) -> None:
        """
        设置当前处理的文件名
        
        参数:
            filename: 文件名
        """
        pass
    
    def enable_cancel_button(self, enabled: bool) -> None:
        """
        启用/禁用取消按钮
        
        参数:
            enabled: 是否启用
        """
        pass
```

### 4.7 UpdateLauncher（升级启动器）

```python
class UpdateLauncher:
    """
    升级启动器 - 独立进程执行升级
    
    这是一个独立的程序，在主程序退出后运行
    """
    
    def __init__(self):
        pass
    
    def run(self) -> int:
        """
        运行升级流程
        
        返回:
            退出码
        """
        pass
    
    def load_update_plan(self, plan_path: str) -> dict:
        """
        加载升级计划
        
        参数:
            plan_path: 升级计划文件路径
            
        返回:
            升级计划字典
        """
        pass
    
    def download_all_packages(self, packages: list, download_dir: str) -> bool:
        """
        下载所有升级包
        
        参数:
            packages: 升级包列表
            download_dir: 下载目录
            
        返回:
            下载是否成功
        """
        pass
    
    def install_all_packages(self, package_paths: list, install_dir: str) -> bool:
        """
        安装所有升级包
        
        参数:
            package_paths: 升级包路径列表
            install_dir: 安装目录
            
        返回:
            安装是否成功
        """
        pass
    
    def cleanup(self, download_dir: str) -> None:
        """
        清理临时文件
        
        参数:
            download_dir: 下载目录
        """
        pass
    
    def launch_main_app(self, app_path: str) -> bool:
        """
        启动主程序
        
        参数:
            app_path: 主程序路径
            
        返回:
            启动是否成功
        """
        pass
```

## 5. 数据结构设计

### 5.1 更新信息结构

```python
UpdateInfo = {
    "current_version": "0.0.4_update1",
    "latest_version": "0.0.5_update2",
    "release_date": "2026-03-15",
    "changelog": "## V0.0.5_update2\n- 修复xxx问题\n- 新增xxx功能",
    "force_update": False,
    "min_supported_version": "0.0.1",
    "upgrade_steps": [
        {
            "step": 1,
            "from": "0.0.4_update1",
            "to": "0.0.5",
            "package": "qitu_V0.0.5.zip",
            "url": "https://github.com/.../qitu_V0.0.5.zip",
            "size": 50000000,
            "hash": "sha256:xxx",
            "download_path": ""
        },
        {
            "step": 2,
            "from": "0.0.5",
            "to": "0.0.5_update2",
            "package": "qitu_V0.0.5_update2.zip",
            "url": "https://github.com/.../qitu_V0.0.5_update2.zip",
            "size": 12000000,
            "hash": "sha256:yyy",
            "download_path": ""
        }
    ]
}
```

### 5.2 升级计划结构

```python
UpdatePlan = {
  "created_at": "2026-03-15T10:30:00",
  "current_version": "0.0.4_update1",
  "target_version": "0.0.5_update2",
  "total_steps": 2,
  "packages": [
    {
      "step": 1,
      "filename": "qitu_V0.0.5.zip",
      "url": "https://github.com/.../qitu_V0.0.5.zip",
      "size": 50000000,
      "hash": "sha256:xxx"
    },
    {
      "step": 2,
      "filename": "qitu_V0.0.5_update2.zip",
      "url": "https://github.com/.../qitu_V0.0.5_update2.zip",
      "size": 12000000,
      "hash": "sha256:yyy"
    }
  ],
  "main_app_path": "C:/Program Files/栖图/栖图.exe",
  "install_dir": "C:/Program Files/栖图",
  "download_dir": "C:/Users/xxx/AppData/Local/栖图/cache/update"
}
```

## 6. 配置文件

### 6.1 update_config.py

```python
# GitHub 仓库配置
GITHUB_OWNER = "CCchen140"
GITHUB_REPO = "qitupage"

# 版本清单 URL
UPDATE_MANIFEST_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download/update_manifest.json"

# 下载超时时间（秒）
DOWNLOAD_TIMEOUT = 300

# 检查间隔（小时）
CHECK_INTERVAL_HOURS = 24

# 最低支持版本
MIN_SUPPORTED_VERSION = "0.0.1"

# 链路测试模式
# 开启后，可以识别和下载以 _test 结尾的测试版本
TEST_MODE = False  # 默认 False

# 测试版本后缀
TEST_VERSION_SUFFIX = "_test"
```

### 6.2 忽略版本记录

```json
{
  "ignored_versions": ["0.0.5", "0.0.5_update1"],
  "last_check_time": "2026-03-15T10:00:00",
  "check_interval_hours": 24
}
```

## 7. 错误处理

### 7.1 错误码定义

```python
ERROR_CODES = {
    0: "成功",
    1: "网络错误",
    2: "下载失败",
    3: "文件校验失败",
    4: "安装失败",
    5: "权限不足",
    6: "磁盘空间不足",
    7: "升级包损坏",
    8: "升级被中断",
    9: "未知错误"
}
```

## 8. 安全考虑

1. **文件校验**：所有下载的文件必须进行 SHA256 校验
2. **HTTPS 传输**：所有下载必须使用 HTTPS
3. **数字签名**：升级包建议进行数字签名验证
4. **权限检查**：安装前检查是否有写入权限
5. **备份机制**：升级前备份关键配置文件

## 9. 使用示例

### 9.1 在 main.py 中集成

```python
from update.update_manager import UpdateManager

def main():
    # ... 其他初始化代码 ...
    
    # 创建升级管理器
    update_manager = UpdateManager()
    
    # 连接信号
    update_manager.update_available.connect(on_update_available)
    update_manager.update_error.connect(on_update_error)
    
    # 启动时检查更新（静默模式）
    update_manager.check_update(silent=True)
    
    # ... 启动主程序 ...

def on_update_available(update_info):
    """有更新时的处理"""
    # 更新对话框会自动显示
    pass

def on_update_error(error_msg):
    """更新错误时的处理"""
    print(f"检查更新失败: {error_msg}")
```

### 9.2 启用链路测试模式

```python
from update import update_config as config

# 启用测试模式
config.TEST_MODE = True

# 现在可以检测到测试版本
# 例如：0.0.5_test
```

## 10. 开发计划

### 第一阶段：基础功能
1. [x] 创建目录结构
2. [x] 编写开发文档
3. [x] 实现 UpdateChecker
4. [x] 实现 UpdateDownloader
5. [x] 实现 UpdateDialog

### 第二阶段：核心功能
1. [x] 实现 UpdateInstaller
2. [x] 实现 UpdateProgressDialog
3. [x] 实现 UpdateLauncher
4. [x] 实现 UpdateManager

### 第三阶段：集成测试
1. [ ] 集成到 main.py
2. [ ] 测试升级流程
3. [ ] 处理边界情况
4. [ ] 优化用户体验

### 第四阶段：链路测试
1. [x] 实现测试模式
2. [ ] 生成测试版本
3. [ ] 验证升级链路
4. [ ] 文档完善

## 11. 注意事项

1. **升级包命名**：必须与 GitHub Release 中的文件名一致
2. **版本号格式**：统一使用 `x.x.x` 或 `x.x.x_updateN` 格式
3. **路径处理**：注意 Windows 路径分隔符和空格处理
4. **进程管理**：确保主程序完全退出后再启动升级器
5. **异常恢复**：升级失败时要有回滚机制
6. **测试模式**：生产环境务必禁用测试模式
