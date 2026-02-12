# PyInstaller 构建指南

## 1. 先决条件

- Windows 环境
- Python 已安装并可用（建议使用项目当前使用的 Python 版本）
- 依赖已安装：PyQt6、qtawesome、psutil、PyInstaller（以及项目运行所需的其他依赖）
- 使用 conda 创建并激活环境（示例：Python 3.11，可按需调整版本）：
   conda create -n bird_cuda python=3.11 -y
   conda activate bird_cuda
   conda activate bird_cuda_12.6
   conda activate bird_cuda
## 2. 软件基础信息

- 软件名与版本号是硬编码在 [app_info_manager.py](file:///d:/code/BirdPictureManager/utils/system/app_info_manager.py) 内的：
  - `APP_NAME`
  - `APP_VERSION`
- 关于软件页与 PyInstaller spec 会同时读取这两个常量作为统一来源。

## 3. 图标生成（ph.bird-fill）

- 构建前会自动生成图标文件：
  - 生成脚本：[generate_icon.py](file:///d:/code/BirdPictureManager/build/generate_icon.py)
  - 输出图标：`build/ph.bird-fill.ico`

手动生成：

```powershell
python build\generate_icon.py
```

## 4. 构建命令

推荐使用一键构建脚本（会先尝试生成图标，再执行 PyInstaller）：

```powershell
python build\build.py
```

如果希望给输出的软件名追加后缀（例如 gpu），可以传入一个参数：

```powershell
python build\build.py gpu
```

最终输出目录将是：

- `dist/<软件名>_gpu_<版本号>/`（目录名示例：`dist/栖图_gpu_V0.0.1/`）
- 其中 EXE 文件名不包含版本号：`dist/栖图_gpu_V0.0.1/栖图_gpu.exe`
- 资源文件与依赖默认放在 EXE 同级目录（不使用 `_internal` 目录）

如果希望启用混淆/防反编译（PyArmor），增加 `--obf` 参数：

```powershell
python build\build.py gpu --obf
```

要求：环境中已安装 `pyarmor`（命令可用，或 `python -m pyarmor` 可用）。

等价手动方式：

```powershell
python -m PyInstaller --noconfirm --clean build\bird_picture_manager.spec
```

说明：

- spec 不依赖 `__file__`（某些 PyInstaller 执行环境下 spec 的 `__file__` 可能不存在），而是通过构建时注入的环境变量定位项目根目录：
  - `BPM_PROJECT_ROOT`
  - `BPM_BUILD_DIR`

Windows 下默认不建议启用二进制 strip（需要额外的 `strip` 工具链，且容易因找不到可执行文件导致构建报错）。本项目 spec 已设置 `strip=False`。

## 5. ExifTool（运行时工具）目录结构

程序在冻结运行时会优先从 `./lib/exiftool.exe` 查找 ExifTool（并兼容旧的 `./libs/exiftool.exe`）。

本项目 spec 会将它们打包到：

- `dist/<软件名>/lib/exiftool.exe`
- `dist/<软件名>/lib/exiftool_files/**`

## 6. 混淆/防篡改说明

- PyInstaller v6.0 起已移除 bytecode encryption（`cipher`/`block_cipher`），因此 spec 不再提供“字节码加密”选项。
- 目前本项目的“防篡改”主要通过：
  - 软件名/版本号在代码内硬编码（避免被外部 json 改写）
  - 打包后通过 EXE/目录结构固定运行时依赖

如果你需要更强的“源码混淆/防反编译”，建议在 PyInstaller 之前引入第三方混淆/打包方案（例如 PyArmor 或 Nuitka 等），然后再将产物交给 PyInstaller 进行封装分发。

## 7. 输出产物

PyInstaller 默认输出目录：

- `dist/<软件名>/`
- `build/`（PyInstaller 中间产物目录，不是本仓库的 build 目录）
