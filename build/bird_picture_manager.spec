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
    if collect_dynamic_libs is not None:
        binaries += collect_dynamic_libs("PyQt6.QtWebEngineCore")
        binaries += collect_dynamic_libs("PyQt6.QtWebEngineWidgets")
        binaries += collect_dynamic_libs("PyQt6.QtWebChannel")
except Exception:
    pass

# 收集 torch 相关模块和数据
try:
    if collect_submodules is not None:
        hiddenimports += collect_submodules("torch")
        hiddenimports += collect_submodules("torch.nn")
        hiddenimports += collect_submodules("torch.optim")
        hiddenimports += collect_submodules("torch.utils")
        hiddenimports += collect_submodules("torch.onnx")
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
        binaries += collect_dynamic_libs("torch._C")
except Exception:
    pass

try:
    if collect_submodules is not None:
        hiddenimports += collect_submodules("ultralytics")
except Exception:
    pass

try:
    if collect_data_files is not None:
        datas += collect_data_files("ultralytics")
except Exception:
    pass

try:
    import nvidia as _nvidia

    _nvidia_dir = os.path.dirname(getattr(_nvidia, "__file__", "") or "")
    if _nvidia_dir and os.path.isdir(_nvidia_dir):
        for _src in glob.glob(os.path.join(_nvidia_dir, "**", "*.dll"), recursive=True):
            try:
                rel = os.path.relpath(os.path.dirname(_src), _nvidia_dir)
            except Exception:
                rel = ""
            low_rel = str(rel or "").replace("\\", "/").lower()
            if "/bin" not in f"/{low_rel}/":
                continue
            dest = os.path.join("nvidia", rel).replace("\\", "/")
            binaries.append((_src, dest))
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
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
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
