import importlib
import glob
import os
import re
import sys
try:
    from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
except Exception:
    collect_data_files = None
    collect_dynamic_libs = None
    collect_submodules = None

PROJECT_ROOT = ""
try:
    PROJECT_ROOT = str(os.environ.get("BPM_PROJECT_ROOT") or "").strip()
except Exception:
    PROJECT_ROOT = ""
if not PROJECT_ROOT:
    try:
        PROJECT_ROOT = os.getcwd()
    except Exception:
        PROJECT_ROOT = "."
ROOT = os.path.abspath(PROJECT_ROOT)
BUILD_DIR = ""
try:
    BUILD_DIR = str(os.environ.get("BPM_BUILD_DIR") or "").strip()
except Exception:
    BUILD_DIR = ""
if not BUILD_DIR:
    BUILD_DIR = os.path.join(ROOT, "build")

SOURCE_ROOT = ""
try:
    SOURCE_ROOT = str(os.environ.get("BPM_SOURCE_ROOT") or "").strip()
except Exception:
    SOURCE_ROOT = ""
if not SOURCE_ROOT:
    SOURCE_ROOT = ROOT
SOURCE_ROOT = os.path.abspath(SOURCE_ROOT)

ENTRY_SCRIPT = ""
try:
    ENTRY_SCRIPT = str(os.environ.get("BPM_ENTRY") or "").strip()
except Exception:
    ENTRY_SCRIPT = ""
if not ENTRY_SCRIPT:
    ENTRY_SCRIPT = os.path.join(SOURCE_ROOT, "main.py")
ENTRY_SCRIPT = os.path.abspath(ENTRY_SCRIPT)


def _collect_datas(src_dir: str, dst_prefix: str):
    items = []
    if not src_dir or not os.path.isdir(src_dir):
        return items
    src_dir = os.path.abspath(src_dir)
    for base, _, files in os.walk(src_dir):
        rel_dir = os.path.relpath(base, src_dir)
        if rel_dir == ".":
            rel_dir = ""
        dst_dir = os.path.join(dst_prefix, rel_dir).replace("\\", "/").rstrip("/")
        for fn in files:
            src_path = os.path.join(base, fn)
            items.append((src_path, dst_dir))
    return items

app_name = "BirdPictureManager"
app_version = "V0.0.1"
try:
    if SOURCE_ROOT not in sys.path:
        sys.path.insert(0, SOURCE_ROOT)
    mod = importlib.import_module("utils.system.app_info_manager")
    app_name = str(getattr(mod, "APP_NAME", app_name))
    app_version = str(getattr(mod, "APP_VERSION", app_version))
except Exception:
    pass

suffix = ""
try:
    suffix = str(os.environ.get("BPM_NAME_SUFFIX") or "").strip()
except Exception:
    suffix = ""

# 构建版本号（移除 V/v 前缀）
v_token = ""
try:
    v = str(app_version or "").strip()
    if v:
        v_token = re.sub(r"[^0-9A-Za-z_.\-]+", "_", v)
        # 移除版本号前的 V/v
        if v_token.lower().startswith('v'):
            v_token = v_token[1:]
except Exception:
    pass

# 确定 cpu/gpu 后缀
flavor_suffix = ""
if suffix and suffix.lower() in ("cpu", "gpu"):
    flavor_suffix = suffix.lower()

# 构建 dist 目录名称：栖图_Vx.x.x_gpu 或 栖图_Vx.x.x_cpu
dist_name = "栖图"
if v_token:
    dist_name = f"{dist_name}_V{v_token}"
if flavor_suffix:
    dist_name = f"{dist_name}_{flavor_suffix}"

# exe 名称保持为中文名
exe_name = "栖图"

icon_path = os.path.join(BUILD_DIR, "ph.bird-fill.ico")
if not os.path.exists(icon_path):
    icon_path = os.path.join(ROOT, "assets", "icons", "bpm_512.ico")

datas = []
datas += _collect_datas(os.path.join(ROOT, "assets"), "assets")
data_template_dir = os.path.join(ROOT, "data")
datas += _collect_datas(data_template_dir, "data")
datas += _collect_datas(os.path.join(ROOT, "models"), "models")
datas += _collect_datas(os.path.join(ROOT, "opensource"), "opensource")
try:
    manual_docx = os.path.join(ROOT, "docs", "使用说明书.docx")
    if os.path.exists(manual_docx):
        datas.append((manual_docx, "."))
except Exception:
    pass
try:
    release_note = os.path.join(ROOT, "ReleaseNote.md")
    if os.path.exists(release_note):
        datas.append((release_note, "."))
except Exception:
    pass

binaries = []
try:
    exiftool_exe = os.path.join(ROOT, "exiftool.exe")
    if os.path.exists(exiftool_exe):
        binaries.append((exiftool_exe, "lib"))
except Exception:
    pass
try:
    exiftool_dir = os.path.join(ROOT, "exiftool_files")
    if os.path.isdir(exiftool_dir):
        datas += _collect_datas(exiftool_dir, "lib/exiftool_files")
except Exception:
    pass

hiddenimports = []
try:
    if collect_submodules is not None:
        hiddenimports += [
            "PyQt6.QtWebEngineWidgets",
            "PyQt6.QtWebEngineCore",
            "PyQt6.QtWebChannel",
        ]
        hiddenimports += collect_submodules("PyQt6.QtWebEngineWidgets")
        hiddenimports += collect_submodules("PyQt6.QtWebEngineCore")
        hiddenimports += collect_submodules("PyQt6.QtWebChannel")
except Exception:
    pass

try:
    if collect_submodules is not None:
        hiddenimports += collect_submodules("PyQt6.QtOpenGLWidgets")
except Exception:
    pass

try:
    if collect_data_files is not None:
        datas += collect_data_files("PyQt6", includes=["Qt6/resources/**", "Qt6/translations/**"])
except Exception:
    pass

try:
    if collect_submodules is not None:
        hiddenimports += collect_submodules("qtawesome")
    else:
        hiddenimports += ["qtawesome"]
except Exception:
    try:
        hiddenimports += ["qtawesome"]
    except Exception:
        pass

try:
    if collect_data_files is not None:
        datas += collect_data_files("qtawesome")
except Exception:
    pass

for _opt_pkg in ("pypinyin", "geopy", "GPUtil", "send2trash", "psutil"):
    try:
        if collect_submodules is not None:
            hiddenimports += collect_submodules(_opt_pkg)
        else:
            hiddenimports += [_opt_pkg]
    except Exception:
        try:
            hiddenimports += [_opt_pkg]
        except Exception:
            pass
    # 注意：send2trash 是单文件模块，不是包，跳过 collect_data_files
    if _opt_pkg != "send2trash":
        try:
            if collect_data_files is not None:
                datas += collect_data_files(_opt_pkg)
        except Exception:
            pass

# 注意：PyQt6 WebEngine 相关模块是 C 扩展，不是 Python 包
# collect_dynamic_libs 对它们无效，会在后面手动收集
# 这里跳过以避免警告
try:
    if collect_dynamic_libs is not None:
        # 这些模块是 C 扩展，跳过 collect_dynamic_libs
        pass
except Exception:
    pass

try:
    if collect_submodules is not None:
        hiddenimports += collect_submodules("exiftool")
    else:
        hiddenimports += ["exiftool"]
except Exception:
    try:
        hiddenimports += ["exiftool"]
    except Exception:
        pass

try:
    if collect_data_files is not None:
        datas += collect_data_files("exiftool")
except Exception:
    pass

# 收集 torch 相关模块和数据
# 注意：跳过会导致警告的模块（tensorboard, onnx）
try:
    if collect_submodules is not None:
        # 使用 exclude 参数跳过不需要的模块
        _torch_excludes = ["torch.utils.tensorboard", "torch.onnx._internal.fx.passes"]
        hiddenimports += collect_submodules("torch", exclude=_torch_excludes)
        hiddenimports += collect_submodules("torch.nn")
        hiddenimports += collect_submodules("torch.optim")
        # 跳过 torch.utils 中的 tensorboard 相关子模块
        hiddenimports += collect_submodules("torch.utils", exclude=["torch.utils.tensorboard"])
        # 跳过 torch.onnx 中的内部 passes 模块
        hiddenimports += collect_submodules("torch.onnx", exclude=["torch.onnx._internal.fx.passes"])
        hiddenimports += collect_submodules("torch.cuda")
        hiddenimports += collect_submodules("torch.version")
        hiddenimports += collect_submodules("torch.backends")
        hiddenimports += collect_submodules("torch.backends.cuda")
        hiddenimports += collect_submodules("torch.backends.cudnn")
        # 显式添加 torch 核心 C 扩展模块
        for _torch_mod in ("torch._C", "torch._C_cuda", "torch._C_cudnn", "torch._C_inductor"):
            try:
                hiddenimports += [_torch_mod]
            except Exception:
                pass
except Exception:
    pass

try:
    if collect_data_files is not None:
        datas += collect_data_files("torch", includes=["**/*.dll", "**/*.so", "**/*.pyd", "**/*.json"])
except Exception:
    pass

try:
    if collect_dynamic_libs is not None:
        binaries += collect_dynamic_libs("torch")
        # 注意：torch._C 是 C 扩展模块，不是包，跳过以避免警告
        # binaries += collect_dynamic_libs("torch._C")
except Exception:
    pass

try:
    import torch as _torch_pkg
    _torch_version = getattr(_torch_pkg, '__version__', 'unknown')
    _torch_lib_dir = os.path.join(os.path.dirname(_torch_pkg.__file__), "lib")
    print(f"[INFO] PyInstaller spec: torch version={_torch_version}, lib_dir={_torch_lib_dir}")
    if os.path.isdir(_torch_lib_dir):
        _torch_dll_seen = set()
        _torch_dll_count = 0
        # 收集所有 DLL，包括子目录中的
        for _root, _dirs, _files in os.walk(_torch_lib_dir):
            for _file in _files:
                if _file.lower().endswith('.dll'):
                    _dll = os.path.join(_root, _file)
                    if os.path.isfile(_dll):
                        _dname = os.path.basename(_dll).lower()
                        if _dname not in _torch_dll_seen:
                            _torch_dll_seen.add(_dname)
                            _torch_dll_count += 1
                            # 保持相对路径结构
                            _rel_path = os.path.relpath(_root, _torch_lib_dir)
                            if _rel_path == '.':
                                binaries.append((_dll, "torch/lib"))
                            else:
                                binaries.append((_dll, os.path.join("torch/lib", _rel_path)))
        print(f"[INFO] PyInstaller spec: collected {_torch_dll_count} torch DLLs")
except Exception as e:
    print(f"[WARN] Failed to collect torch lib DLLs: {e}")
    import traceback
    traceback.print_exc()
    pass

try:
    if collect_submodules is not None:
        hiddenimports += collect_submodules("ultralytics")
        # 显式添加 ultralytics 的关键子模块
        hiddenimports += [
            "ultralytics.nn",
            "ultralytics.nn.modules",
            "ultralytics.nn.tasks",
            "ultralytics.models",
            "ultralytics.models.yolo",
            "ultralytics.models.yolo.segment",
            "ultralytics.utils",
            "ultralytics.utils.metrics",
            "ultralytics.utils.loss",
            "ultralytics.data",
            "ultralytics.engine",
            "ultralytics.engine.model",
            "ultralytics.engine.predictor",
            "ultralytics.engine.results",
        ]
except Exception:
    pass

try:
    if collect_data_files is not None:
        datas += collect_data_files("ultralytics")
except Exception:
    pass

_nvidia_dll_seen = set()

def _collect_nvidia_dlls_from_dir(nvidia_base_dir):
    if not nvidia_base_dir or not os.path.isdir(nvidia_base_dir):
        return
    for _src in glob.glob(os.path.join(nvidia_base_dir, "**", "*.dll"), recursive=True):
        _dll_name_lower = os.path.basename(_src).lower()
        if _dll_name_lower in _nvidia_dll_seen:
            continue
        _nvidia_dll_seen.add(_dll_name_lower)
        binaries.append((_src, "torch/lib"))

try:
    import nvidia as _nvidia

    _nvidia_dirs = []
    if hasattr(_nvidia, "__path__"):
        for _p in _nvidia.__path__:
            if _p and os.path.isdir(_p):
                _nvidia_dirs.append(os.path.abspath(_p))
    if not _nvidia_dirs:
        _f = getattr(_nvidia, "__file__", "") or ""
        if _f:
            _d = os.path.dirname(_f)
            if _d and os.path.isdir(_d):
                _nvidia_dirs.append(os.path.abspath(_d))
    for _nvidia_dir in _nvidia_dirs:
        _collect_nvidia_dlls_from_dir(_nvidia_dir)
except Exception:
    pass

try:
    _nvidia_subpkgs = [
        "nvidia.cublas", "nvidia.cuda_runtime", "nvidia.cuda_nvrtc",
        "nvidia.cudnn", "nvidia.cufft", "nvidia.curand",
        "nvidia.cusolver", "nvidia.cusparse", "nvidia.nccl",
        "nvidia.nvjitlink", "nvidia.nvtx",
    ]
    for _pkg_name in _nvidia_subpkgs:
        try:
            _pkg = importlib.import_module(_pkg_name)
            _pkg_dirs = []
            if hasattr(_pkg, "__path__"):
                _pkg_dirs = list(_pkg.__path__)
            elif hasattr(_pkg, "__file__") and _pkg.__file__:
                _pkg_dirs = [os.path.dirname(_pkg.__file__)]
            for _pd in _pkg_dirs:
                if _pd and os.path.isdir(_pd):
                    _collect_nvidia_dlls_from_dir(os.path.abspath(_pd))
        except Exception:
            continue
except Exception:
    pass

_require_webengine = str(os.environ.get("BPM_REQUIRE_WEBENGINE", "1") or "1").strip().lower() not in ("0", "false", "no")
try:
    import PyQt6 as _pyqt6

    _pyqt6_dir = os.path.dirname(getattr(_pyqt6, "__file__", "") or "")
    if not _pyqt6_dir:
        if _require_webengine:
            raise RuntimeError("无法定位 PyQt6 安装目录，无法打包 WebEngine。")
    else:
        _required_pyds = ["QtWebEngineWidgets.pyd", "QtWebEngineCore.pyd"]
        _missing_pyds = [p for p in _required_pyds if not os.path.exists(os.path.join(_pyqt6_dir, p))]
        if _missing_pyds and _require_webengine:
            raise RuntimeError(f"缺少 PyQt6-WebEngine 组件: {_missing_pyds}")

        for _pyd_name in (
            "QtWebEngineCore.pyd",
            "QtWebEngineWidgets.pyd",
            "QtWebEngineQuick.pyd",
        ):
            _pyd = os.path.join(_pyqt6_dir, _pyd_name)
            if os.path.exists(_pyd):
                binaries.append((_pyd, "PyQt6"))

        _process_candidates = [
            os.path.join(_pyqt6_dir, "Qt6", "libexec", "QtWebEngineProcess.exe"),
            os.path.join(_pyqt6_dir, "Qt6", "bin", "QtWebEngineProcess.exe"),
        ]
        for _p in _process_candidates:
            if not os.path.exists(_p):
                continue
            if os.path.normcase(os.path.normpath(_p)).endswith(os.path.normcase(os.path.normpath(os.path.join("Qt6", "bin", "QtWebEngineProcess.exe")))):
                binaries.append((_p, "PyQt6/Qt6/bin"))
            else:
                binaries.append((_p, "PyQt6/Qt6/libexec"))
            break

        _qt6_bin = os.path.join(_pyqt6_dir, "Qt6", "bin")
        _qt6_res = os.path.join(_pyqt6_dir, "Qt6", "resources")
        _qt6_tr = os.path.join(_pyqt6_dir, "Qt6", "translations")

        if os.path.isdir(_qt6_bin):
            for _name in (
                "Qt6WebEngineCore.dll",
                "Qt6WebEngineWidgets.dll",
                "Qt6WebEngineQuick.dll",
                "Qt6WebEngineQuickDelegatesQml.dll",
                "Qt6WebChannel.dll",
            ):
                _dll = os.path.join(_qt6_bin, _name)
                if os.path.exists(_dll):
                    binaries.append((_dll, "PyQt6/Qt6/bin"))

        if os.path.isdir(_qt6_res):
            for _pat in ("qtwebengine*.pak", "qtwebengine*.debug.pak", "icudtl.dat"):
                for _src in glob.glob(os.path.join(_qt6_res, _pat)):
                    if os.path.isfile(_src):
                        datas.append((_src, "PyQt6/Qt6/resources"))

        _locales_dir = os.path.join(_qt6_tr, "qtwebengine_locales")
        if os.path.isdir(_locales_dir):
            for _src in glob.glob(os.path.join(_locales_dir, "*.pak")):
                if os.path.isfile(_src):
                    datas.append((_src, "PyQt6/Qt6/translations/qtwebengine_locales"))
except Exception:
    if _require_webengine:
        raise

analysis = Analysis(
    [ENTRY_SCRIPT],
    pathex=[SOURCE_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[os.path.join(BUILD_DIR, "pyi_rth_torch_dlls.py")],
    excludes=[
        # 排除不需要的 torch 可选模块，减少警告
        "tensorboard",
        "onnx",
        "torch.utils.tensorboard",
        "torch.onnx._internal.fx.passes",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=True,
)

pyz = PYZ(analysis.pure, analysis.zipped_data)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=str(exe_name),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    contents_directory=".",
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
    uac_uiaccess=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.exists(icon_path) else None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    name=str(dist_name),
)
