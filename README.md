BirdManager/
├── main.py                 # 启动入口（初始化 App、加载主窗口）
├── config.ini              # 配置文件
├── bird_data.db            # SQLite 数据库文件
├── requirements.txt        # 依赖清单
│
├── core/                   # 核心业务逻辑（无 UI 代码）
│   ├── detector.py         # YOLO 封装、锐度算法、抖动检测
│   ├── metadata.py         # ExifTool 封装、XMP 读写、批量写入
│   ├── database.py         # SQLite 操作类
│   └── processor.py        # 任务分发逻辑、多线程/进程协调
│
├── ui/                     # 界面相关（Qt 专属代码）
│   ├── main_window.py      # 主窗口逻辑
│   ├── widgets/            # 自定义小部件（如图片卡片、进度条）
│   ├── styles.qss          # CSS 样式表
│   └── resources_rc.py     # 编译后的图标资源文件
│
├── utils/                  # 通用工具函数
│   ├── file_helper.py      # 文件拷贝、重命名、缓存清理
│   ├── image_helper.py     # 缩略图生成、哈希计算
│   └── logger.py           # 日志管理
│
├── assets/                 # 静态资源
│   ├── models/             # YOLO .pt 模型文件
│   ├── icons/              # 软件图标、按钮图标
│   └── tools/              # 外部程序（exiftool.exe）
│
├── locales/                # 多语言翻译文件
│   ├── zh_CN.qm
│   └── en_US.qm
│
├── update/                 # 自动升级系统
│   ├── update_config.py    # 升级配置文件
│   ├── update_manager.py   # 升级管理器
│   ├── update_checker.py   # 版本检查
│   ├── update_downloader.py # 下载器
│   └── update_page.py      # 升级页面 UI
│
└── cache/                  # 运行时自动生成的缓存
    ├── thumbnails/         # 缩略图缓存
    ├── logs/               # 运行日志
    └── update/             # 升级包缓存
```

---

### 各目录职责详解：

#### 1. `core/` (逻辑层)
这是你程序的"大脑"。
*   **原则**：这里的代码**不应该包含任何 PyQt 的 import**。
*   **好处**：当你以后想换一个 GUI 框架（比如换成 Web 界面或 Flet）时，`core/` 里的算法逻辑完全不需要动。

#### 2. `ui/` (表现层)
只负责界面显示和用户交互。
*   **`main_window.py`**：负责把 `core/` 里的检测结果通过列表或网格展示出来。
*   **解耦方法**：界面通过 **信号 (Signal)** 触发 `core/` 里的逻辑，核心逻辑完成后通过 **回调或信号** 通知 UI 更新进度。

#### 3. `assets/` (资源层)
存放程序运行必须的外部文件。
*   将 `exiftool.exe` 放在 `assets/tools/` 下，程序中通过 `os.path.join(BASE_DIR, "assets", "tools", "exiftool.exe")` 动态定位，这样打包成 `.exe` 时路径最稳。

#### 4. `cache/` (缓存层)
*   **缩略图**：放在单独的目录，并由 `utils/file_helper.py` 负责定期清理旧缓存。
*   **升级包**：下载的 zip 包和解压后的安装程序存放在 `cache/update/` 目录。
*   **重要性**：不要把缓存和代码混在一起，否则 Git 提交或备份时会非常痛苦。

#### 5. `update/` (自动升级系统)
负责软件自动升级功能。
*   **`update_config.py`**：升级相关配置，包括 GitHub 仓库信息、镜像地址、测试模式开关等。
*   **`update_manager.py`**：升级管理器，协调整个升级流程。
*   **`update_page.py`**：升级页面 UI，显示下载和解压进度。

---

### 自动升级系统说明

#### 升级流程
1. **检查更新**：从 GitHub Release 获取版本清单，检查是否有新版本
2. **下载升级包**：下载 zip 格式的升级包到 `cache/update/` 目录
3. **解压升级包**：解压 zip 包，提取其中的 innosetup 安装程序
4. **启动安装程序**：退出当前程序，启动安装程序进行静默安装

#### 升级包格式
升级包为 zip 格式，内部包含：
- innosetup 生成的安装程序（.exe 文件）
- 可选：其他资源文件

#### 测试模式
在 `update/update_config.py` 中可配置测试模式：

```python
# 链路测试模式开关
# 开启后，可以识别和下载以 _test 结尾的测试版本
# 测试版本包内容为空，仅用于验证升级链路
LINK_TEST_MODE = True  # 默认 False

# 测试版本后缀
TEST_VERSION_SUFFIX = "_test"
```

**链路测试模式行为**：
- 正常模式：解压完成后自动启动安装程序并退出当前程序
- 链路测试模式：解压完成后显示"链路测试完成"，不启动安装程序，保留"返回"按钮供用户返回

#### 镜像加速
支持多镜像自动切换，当 GitHub 访问不稳定时自动切换到可用镜像：
- ghproxy.com
- mirror.ghproxy.com
- hub.gitmirror.com
- githubfast.com
- kgithub.com

---

### 打包建议（针对 PyInstaller）

采用这种结构后，你可以使用 `.spec` 文件非常清晰地进行打包：

```python
# spec 文件关键配置
datas=[
    ('assets/models/*.pt', 'assets/models'),
    ('assets/tools/exiftool.exe', 'assets/tools'),
    ('assets/icons/*', 'assets/icons'),
    ('locales/*.qm', 'locales'),
]
```

### 总结
你现在的 `checktest.py` 可以按以下顺序拆分：
1.  **第一步**：把 `BirdFocusDetector` 搬到 `core/detector.py`。
2.  **第二步**：把 `batch_write_metadata` 搬到 `core/metadata.py`。
3.  **第三步**：新建 `ui/main_window.py`，把 `if __name__ == "__main__":` 里的流程改为 GUI 按钮触发。

这种结构能让你的"鸟图管理软件"从一开始就具备**"大厂"架构**，后期增加"鸟眼检测"、"在线更新"、"地图分布"等功能时，代码会非常清晰。
