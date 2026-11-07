import hashlib
import json
import os
import random
import sys
import threading
import time
from urllib.parse import unquote
from typing import Any

import cv2
import numpy as np
from PyQt6.QtGui import QImage
from utils.system.stderr_suppressor import suppress_stderr_fd

_lock = threading.Lock()

# 缓存统计（用于调试）
_cache_stats = {
    "load_attempts": 0,
    "load_hits": 0,
    "load_misses": 0,
    "save_attempts": 0,
    "save_success": 0,
}

def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    return dict(_cache_stats)


def reset_cache_stats():
    """重置缓存统计信息"""
    global _cache_stats
    _cache_stats = {
        "load_attempts": 0,
        "load_hits": 0,
        "load_misses": 0,
        "save_attempts": 0,
        "save_success": 0,
    }


def _project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    except Exception:
        return os.getcwd()


def _get_exe_dir() -> str:
    """获取可执行文件所在目录（支持打包后的程序和多进程环境）

    在多进程环境下，子进程的 sys.executable 可能指向 Python 解释器，
    而不是主程序。这种情况下，我们优先使用环境变量传递的主程序目录。
    """
    # 优先使用环境变量指定的主程序目录（由主进程设置）
    env_exe_dir = os.environ.get("BIRD_PICTURE_MANAGER_EXE_DIR")
    if env_exe_dir and os.path.isdir(env_exe_dir):
        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[_get_exe_dir] 使用环境变量目录: {env_exe_dir}")
        except Exception:
            pass
        return env_exe_dir
    
    exe_dir = os.path.dirname(sys.executable)

    # 打印调试信息
    try:
        from utils.log_manager import LogManager
        LogManager.instance().info(f"[_get_exe_dir] 初始 exe_dir={exe_dir}, sys.executable={sys.executable}, sys.frozen={getattr(sys, 'frozen', False)}")
    except Exception:
        pass

    # 如果 exe_dir 包含 "_internal"，则向上回退到上级目录
    if "_internal" in exe_dir.lower():
        exe_dir = os.path.dirname(exe_dir)
        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[_get_exe_dir] 包含 _internal，回退到上级目录: {exe_dir}")
        except Exception:
            pass
        return exe_dir

    # 如果 exe_dir 包含 "python" 或 "Python"，说明是Python解释器
    # 尝试通过 sys.argv[0] 找到主程序
    if "python" in os.path.basename(exe_dir).lower() or "python" in os.path.basename(sys.executable).lower():
        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[_get_exe_dir] 检测到Python解释器，尝试通过sys.argv[0]查找主程序")
        except Exception:
            pass
        try:
            # 尝试使用 sys.argv[0] 获取主程序路径
            main_script = sys.argv[0] if sys.argv else None
            if main_script:
                main_dir = os.path.dirname(os.path.abspath(main_script))
                try:
                    from utils.log_manager import LogManager
                    LogManager.instance().info(f"[_get_exe_dir] sys.argv[0]={main_script}, main_dir={main_dir}")
                except Exception:
                    pass
                if main_dir and os.path.isdir(main_dir):
                    # 检查这个目录是否包含可执行文件（.exe）
                    for f in os.listdir(main_dir):
                        if f.lower().endswith('.exe'):
                            try:
                                from utils.log_manager import LogManager
                                LogManager.instance().info(f"[_get_exe_dir] 找到.exe文件: {f}，返回目录: {main_dir}")
                            except Exception:
                                pass
                            return main_dir
                    # 如果上级目录包含 _internal，说明是打包后的程序
                    parent_dir = os.path.dirname(main_dir)
                    if "_internal" in os.path.basename(parent_dir).lower():
                        try:
                            from utils.log_manager import LogManager
                            LogManager.instance().info(f"[_get_exe_dir] 上级目录包含_internal，返回: {parent_dir}")
                        except Exception:
                            pass
                        return parent_dir
        except Exception as e:
            try:
                from utils.log_manager import LogManager
                LogManager.instance().info(f"[_get_exe_dir] 通过sys.argv[0]查找失败: {e}")
            except Exception:
                pass

    try:
        from utils.log_manager import LogManager
        LogManager.instance().info(f"[_get_exe_dir] 返回最终目录: {exe_dir}")
    except Exception:
        pass
    return exe_dir


def get_cache_dir(scope: str = "import_focus") -> str:
    """获取对焦检测缩略图缓存目录

    使用绝对路径，避免多进程环境下工作目录不同导致的问题
    支持打包后的程序（PyInstaller）
    """
    # 辅助函数：记录日志
    def _log(msg, level: str = "info"):
        try:
            from utils.log_manager import LogManager
            logger = LogManager.instance()
            if str(level or "info").lower() == "debug":
                logger.debug(msg)
            else:
                logger.info(msg)
        except Exception:
            pass

    _log(f"[get_cache_dir] 开始执行，scope={scope}", level="debug")
    _log(f"[get_cache_dir] sys.executable={sys.executable}", level="debug")
    _log(f"[get_cache_dir] sys.frozen={getattr(sys, 'frozen', False)}", level="debug")
    _log(f"[get_cache_dir] sys.argv={sys.argv}", level="debug")

    try:
        # 优先使用环境变量指定的缓存目录（打包后的程序可以设置这个变量）
        env_cache_dir = os.environ.get("BIRD_PICTURE_MANAGER_CACHE_DIR")
        if env_cache_dir:
            base = env_cache_dir
            _log(f"[get_cache_dir] 使用环境变量缓存目录: {base}")
        else:
            # 优先使用环境变量指定的主程序目录（由主进程设置）
            # 这一步必须在检查 sys.frozen 之前，因为子进程的 sys.frozen 可能不是 True
            env_exe_dir = os.environ.get("BIRD_PICTURE_MANAGER_EXE_DIR")
            if env_exe_dir and os.path.isdir(env_exe_dir):
                base = os.path.join(env_exe_dir, "cache")
                _log(f"[get_cache_dir] 使用环境变量主程序目录: env_exe_dir={env_exe_dir}, base={base}", level="debug")
            else:
                # 检测是否在PyInstaller打包环境中
                is_frozen = getattr(sys, 'frozen', False)
                _log(f"[get_cache_dir] is_frozen={is_frozen}")
                if is_frozen:
                    # 打包后的程序，使用可执行文件所在目录
                    # 注意：在多进程环境下，sys.executable 可能指向 Python 解释器
                    # 需要使用 _get_exe_dir() 来处理这种情况
                    exe_dir = _get_exe_dir()
                    base = os.path.join(exe_dir, "cache")
                    _log(f"[get_cache_dir] 打包环境，exe_dir={exe_dir}, base={base}")
                else:
                    # 开发环境，使用项目根目录
                    current_file_dir = os.path.dirname(os.path.abspath(__file__))
                    project_root = os.path.abspath(os.path.join(current_file_dir, os.pardir))
                    base = os.path.join(project_root, "cache")
                    _log(f"[get_cache_dir] 开发环境，project_root={project_root}, base={base}")

        s = str(scope or "import_focus").lower()
        if s in ["import_focus", "focus_scaled", "focus"]:
            cache_dir = os.path.join(base, "focus_scaled")
        else:
            cache_dir = os.path.join(base, f"focus_scaled_{s}")

        # 确保目录存在
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception as e:
            _log(f"[get_cache_dir] 创建目录失败: {e}")

        _log(f"[get_cache_dir] scope={scope}, 最终缓存目录: {cache_dir}", level="debug")
        return cache_dir
    except Exception as e:
        # 如果失败，使用基于当前工作目录的路径（兼容旧逻辑）
        _log(f"[get_cache_dir] 发生异常: {e}，使用备用路径")
        base = os.path.join(_project_root(), "cache")
        s = str(scope or "import_focus").lower()
        if s in ["import_focus", "focus_scaled", "focus"]:
            return os.path.join(base, "focus_scaled")
        return os.path.join(base, f"focus_scaled_{s}")


def _max_count_from_settings(default: int = 2000) -> int:
    try:
        from utils.setting.settings_manager import SettingsManager

        sm = SettingsManager()
        v = int(sm.get("import/cache_size", default))
        return max(50, v)
    except Exception:
        return int(default)


def _normalize_path_for_key(image_path: str) -> str:
    """规范化路径用于构建缓存键

    在Windows系统上，路径是大小写不敏感的，因此需要将路径统一转换为小写
    以确保同一文件的不同大小写形式产生相同的缓存键

    同时确保路径是绝对路径,避免相对路径导致缓存键不匹配
    """
    try:
        raw_path = str(image_path or "")
        path = raw_path.strip()

        # 兼容 file:// URI，避免不同调用链传入 URI 与本地路径时生成不同 key。
        if path.lower().startswith("file:///"):
            path = unquote(path[8:])
        elif path.lower().startswith("file://"):
            path = unquote(path[7:])

        if os.name == "nt":
            # 兼容 Windows 长路径前缀，避免 `\\?\D:\...` 与 `D:\...` 命中不同缓存键。
            if path.startswith("\\\\?\\UNC\\"):
                path = "\\\\" + path[8:]
            elif path.startswith("\\\\?\\"):
                path = path[4:]

        # 先转换为绝对路径
        path = os.path.abspath(path)
        # 使用normpath规范化路径分隔符
        path = os.path.normpath(path)
        # 在Windows上转换为小写，确保大小写不敏感
        if os.name == "nt":
            path = os.path.normcase(path)
        # 统一路径分隔符为正斜杠，避免反斜杠和正斜杠混用导致缓存键不匹配
        path = path.replace('\\', '/')
        return path
    except Exception:
        return str(image_path)


def _normalize_path_for_key_legacy(image_path: str) -> str:
    """生成旧兼容路径规范化结果

    这里保留历史逻辑，不主动清洗长路径前缀或 file:// URI，
    用于兼容已经按旧规则写入到磁盘中的缓存文件。
    """
    try:
        path = os.path.abspath(str(image_path))
        path = os.path.normpath(path)
        if os.name == "nt":
            path = os.path.normcase(path)
        path = path.replace("\\", "/")
        return path
    except Exception:
        return str(image_path)


def _collect_normalized_path_candidates(image_path: str) -> list[str]:
    """收集可能的路径规范化结果

    读取缓存时同时尝试新旧两套规范化结果，兼容历史缓存文件，
    并额外兼容 Windows 长路径前缀、file:// URI 以及 realpath 差异。
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _append(path_value: str):
        try:
            s = str(path_value or "")
        except Exception:
            s = ""
        if not s or s in seen:
            return
        seen.add(s)
        candidates.append(s)

    raw_path = str(image_path or "")
    cleaned_path = raw_path.strip()

    primary = _normalize_path_for_key(raw_path)
    legacy = _normalize_path_for_key_legacy(raw_path)
    _append(primary)
    _append(legacy)

    try:
        real_primary = _normalize_path_for_key(os.path.realpath(cleaned_path or raw_path))
        _append(real_primary)
    except Exception:
        pass

    try:
        real_legacy = _normalize_path_for_key_legacy(os.path.realpath(cleaned_path or raw_path))
        _append(real_legacy)
    except Exception:
        pass

    return candidates


def _build_key_from_normalized_path(normalized_path: str, target_size: int) -> str:
    """基于已规范化路径构建缓存键"""
    token = f"{normalized_path}|{int(target_size)}"
    return hashlib.sha1(token.encode("utf-8", errors="ignore")).hexdigest()


def build_key(image_path: str, target_size: int) -> str:
    """构建缓存键
    
    只使用文件路径和目标尺寸作为键，不使用文件大小和修改时间，因为：
    1. 文件大小可能在对焦检测后变化（如添加EXIF标签、修改元数据）
    2. 文件修改时间可能因文件复制、同步等操作而变化
    3. 文件路径和目标尺寸足以唯一标识一个缓存项
    """
    try:
        # 使用规范化后的路径，确保Windows上大小写不敏感
        normalized_path = _normalize_path_for_key(image_path)
        return _build_key_from_normalized_path(normalized_path, target_size)
    except Exception:
        normalized_path = _normalize_path_for_key(image_path)
        return _build_key_from_normalized_path(normalized_path, target_size)


def get_paths(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[str, str]:
    key = build_key(image_path, int(target_size or 0))
    d = get_cache_dir(scope)
    return os.path.join(d, f"{key}.jpg"), os.path.join(d, f"{key}.json")


def _build_key_legacy_from_parts(normalized_path: str, file_size: int, target_size: int) -> str:
    """基于规范化路径和文件大小构建旧版缓存键"""
    token = f"{normalized_path}|{int(file_size)}|{int(target_size)}"
    return hashlib.sha1(token.encode("utf-8", errors="ignore")).hexdigest()


def _get_legacy_file_size(image_path: str) -> int:
    """尽量获取文件大小，供旧版缓存键兼容使用"""
    raw_path = str(image_path or "")
    for candidate in (raw_path, raw_path.strip()):
        if not candidate:
            continue
        try:
            return int(os.stat(candidate).st_size)
        except Exception:
            continue
    for candidate in _collect_normalized_path_candidates(image_path):
        try:
            return int(os.stat(candidate).st_size)
        except Exception:
            continue
    return 0


def _iter_cache_path_candidates(image_path: str, target_size: int, scope: str = "import_focus") -> list[tuple[str, str, str, bool]]:
    """生成缓存路径候选列表

    返回值:
        [(jpg_path, meta_path, 描述, 是否旧格式), ...]
    """
    cache_dir = get_cache_dir(scope)
    candidates: list[tuple[str, str, str, bool]] = []
    seen_keys: set[str] = set()
    normalized_candidates = _collect_normalized_path_candidates(image_path)

    for index, normalized_path in enumerate(normalized_candidates):
        key = _build_key_from_normalized_path(normalized_path, int(target_size or 0))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        desc = "primary" if index == 0 else f"compat_new_{index}"
        candidates.append(
            (
                os.path.join(cache_dir, f"{key}.jpg"),
                os.path.join(cache_dir, f"{key}.json"),
                desc,
                False,
            )
        )

    legacy_size = _get_legacy_file_size(image_path)
    for index, normalized_path in enumerate(normalized_candidates):
        key = _build_key_legacy_from_parts(normalized_path, legacy_size, int(target_size or 0))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        desc = "legacy" if index == 0 else f"compat_legacy_{index}"
        candidates.append(
            (
                os.path.join(cache_dir, f"{key}.jpg"),
                os.path.join(cache_dir, f"{key}.json"),
                desc,
                True,
            )
        )

    return candidates


def _resolve_existing_cache_paths(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[str | None, str | None, bool, str]:
    """查找实际存在的缓存文件路径

    会按主键、兼容键、旧版键依次尝试，尽量兼容历史缓存文件。
    """
    for jpg_path, meta_path, desc, use_legacy in _iter_cache_path_candidates(image_path, target_size, scope):
        try:
            if os.path.isfile(jpg_path) and os.path.isfile(meta_path):
                return jpg_path, meta_path, use_legacy, desc
        except Exception:
            continue
    return None, None, False, ""


def try_load_qimage(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[QImage | None, dict[str, Any] | None]:
    """尝试加载缓存图片

    同时尝试新旧两种格式的缓存键，兼容旧缓存
    """
    global _cache_stats
    _cache_stats["load_attempts"] += 1

    use_legacy = False
    try:
        jpg_path, meta_path, use_legacy, hit_desc = _resolve_existing_cache_paths(image_path, target_size, scope=scope)
        if not jpg_path or not meta_path:
            _cache_stats["load_misses"] += 1
            return None, None
    except Exception:
        _cache_stats["load_misses"] += 1
        return None, None

    meta = None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = None

    try:
        img = QImage(jpg_path)
    except Exception:
        img = None
    if img is None or img.isNull():
        _cache_stats["load_misses"] += 1
        return None, meta
    try:
        os.utime(jpg_path, None)
    except Exception:
        pass
    _cache_stats["load_hits"] += 1
    return img, meta


def try_load_cv_bgr(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[np.ndarray | None, dict[str, Any] | None]:
    jpg_path, meta_path, _use_legacy, _hit_desc = _resolve_existing_cache_paths(image_path, target_size, scope=scope)
    if not jpg_path or not meta_path:
        return None, None

    meta = None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = None

    try:
        buf = np.fromfile(jpg_path, dtype=np.uint8)
        with suppress_stderr_fd():
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        img = None
    if img is None or not isinstance(img, np.ndarray) or img.size <= 0:
        return None, meta
    try:
        os.utime(jpg_path, None)
    except Exception:
        pass
    return img, meta


def try_load_meta(image_path: str, target_size: int, scope: str = "import_focus") -> dict[str, Any] | None:
    _jpg_path, meta_path, _use_legacy, _hit_desc = _resolve_existing_cache_paths(image_path, target_size, scope=scope)
    if not meta_path:
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except Exception:
        return None


def _build_key_legacy(image_path: str, target_size: int) -> str:
    """旧版本的缓存键生成（包含文件大小）

    用于兼容旧缓存，在过渡期后应删除
    
    注意：旧缓存键格式为 {path}|{size}|{target_size}
    """
    try:
        st_size = _get_legacy_file_size(image_path)
        # 旧缓存键使用原始路径（未规范化），但为了兼容性，我们尝试规范化
        normalized_path = _normalize_path_for_key(image_path)
        return _build_key_legacy_from_parts(normalized_path, st_size, target_size)
    except Exception:
        normalized_path = _normalize_path_for_key(image_path)
        return _build_key_legacy_from_parts(normalized_path, 0, target_size)


def _get_paths_legacy(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[str, str]:
    """获取旧版本缓存路径"""
    key = _build_key_legacy(image_path, int(target_size or 0))
    d = get_cache_dir(scope)
    return os.path.join(d, f"{key}.jpg"), os.path.join(d, f"{key}.json")


def has(image_path: str, target_size: int, scope: str = "import_focus") -> bool:
    """检查缓存是否存在，不实际加载图片

    同时检查新旧两种格式的缓存键，兼容旧缓存
    """
    jpg_path, meta_path, _use_legacy, _hit_desc = _resolve_existing_cache_paths(image_path, target_size, scope=scope)
    return bool(jpg_path and meta_path)


def save_scaled_qimage(
    image_path: str,
    target_size: int,
    qimg: QImage,
    *,
    orig_w: int,
    orig_h: int,
    scope: str = "import_focus",
    quality: int = 90,
):
    if qimg is None or qimg.isNull():
        return
    cache_dir = get_cache_dir(scope)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        return

    jpg_path, meta_path = get_paths(image_path, target_size, scope=scope)
    tmp = f"{jpg_path}.tmp.{os.getpid()}"
    tmp_meta = f"{meta_path}.tmp.{os.getpid()}"
    with _lock:
        try:
            if os.path.isfile(jpg_path) and os.path.isfile(meta_path):
                return
        except Exception:
            pass
        try:
            fmt = "JPG"
            qimg.save(tmp, fmt, int(quality))
            meta = {"orig_w": int(orig_w or 0), "orig_h": int(orig_h or 0)}
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
            os.replace(tmp, jpg_path)
            os.replace(tmp_meta, meta_path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            try:
                if os.path.exists(tmp_meta):
                    os.remove(tmp_meta)
            except Exception:
                pass
    # 注意：不在此处清理缓存，缓存清理只在开始新的对焦检测时进行


def save_scaled_cv_bgr(
    image_path: str,
    target_size: int,
    bgr: np.ndarray,
    *,
    orig_w: int,
    orig_h: int,
    scope: str = "import_focus",
    quality: int = 90,
):
    global _cache_stats
    _cache_stats["save_attempts"] += 1

    if bgr is None or not isinstance(bgr, np.ndarray) or bgr.size <= 0:
        return
    cache_dir = get_cache_dir(scope)

    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        return

    jpg_path, meta_path = get_paths(image_path, target_size, scope=scope)

    # 多进程安全：使用进程ID和随机数创建唯一的临时文件名
    unique_id = f"{os.getpid()}_{random.randint(1000, 9999)}_{int(time.time()*1000)%1000}"
    tmp = f"{jpg_path}.tmp.{unique_id}"
    tmp_meta = f"{meta_path}.tmp.{unique_id}"

    # 先检查缓存是否已存在（避免重复写入）
    try:
        if os.path.isfile(jpg_path) and os.path.isfile(meta_path):
            _cache_stats["save_success"] += 1
            return
    except Exception:
        pass

    try:
        q = int(max(50, min(95, int(quality))))
    except Exception:
        q = 90
    try:
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(q)])
    except Exception:
        ok, buf = False, None
    if not ok or buf is None:
        return

    saved = False
    try:
        # 写入临时文件
        with open(tmp, "wb") as f:
            f.write(buf.tobytes())
        meta = {"orig_w": int(orig_w or 0), "orig_h": int(orig_h or 0)}
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        # 使用原子操作移动到目标位置
        # 在Windows上，如果目标文件已存在，os.replace会覆盖它
        # 这可能导致竞态条件，但比文件损坏要好
        try:
            os.replace(tmp, jpg_path)
            os.replace(tmp_meta, meta_path)
            saved = True
        except Exception:
            # 如果移动失败（例如目标文件被锁定），清理临时文件
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            try:
                if os.path.exists(tmp_meta):
                    os.remove(tmp_meta)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        # 确保临时文件被清理
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        try:
            if os.path.exists(tmp_meta):
                os.remove(tmp_meta)
        except Exception:
            pass

    if saved:
        _cache_stats["save_success"] += 1
        # 记录缓存保存成功
        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[save_scaled_cv_bgr] 缓存保存成功: path={os.path.basename(image_path)}, jpg_path={jpg_path}")
        except Exception:
            pass
    else:
        # 记录缓存保存失败
        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[save_scaled_cv_bgr] 缓存保存失败: path={os.path.basename(image_path)}")
        except Exception:
            pass
    # 注意：不在此处清理缓存，缓存清理只在开始新的对焦检测时进行


def cleanup_temp_files(scope: str = "import_focus", max_age_hours: int = 24):
    """清理缓存目录中的临时文件

    参数:
        scope: 缓存作用域
        max_age_hours: 临时文件的最大保留时间（小时），超过此时间的临时文件将被删除
    """
    cache_dir = get_cache_dir(scope)
    try:
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        count = 0
        for name in os.listdir(cache_dir):
            # 检查是否是临时文件（包含.tmp.的文件名）
            if ".tmp." not in name:
                continue
            p = os.path.join(cache_dir, name)
            try:
                # 检查文件年龄
                file_mtime = os.path.getmtime(p)
                if current_time - file_mtime > max_age_seconds:
                    os.remove(p)
                    count += 1
            except Exception:
                pass
        if count > 0:
            try:
                from utils.log_manager import LogManager
                LogManager.instance().debug(f"[FocusCache] 清理了 {count} 个临时文件")
            except Exception:
                pass
    except Exception:
        pass


def enforce_limit(scope: str = "import_focus"):
    cache_dir = get_cache_dir(scope)
    try:
        # 增加默认缓存数量到5000，以支持大量RAW文件
        max_count = int(_max_count_from_settings(5000))
    except Exception:
        max_count = 5000
    if max_count <= 0:
        return
    try:
        entries = []
        for name in os.listdir(cache_dir):
            if not name.lower().endswith(".jpg"):
                continue
            p = os.path.join(cache_dir, name)
            try:
                ts = os.path.getmtime(p)
            except Exception:
                ts = 0.0
            entries.append((ts, p))
    except Exception:
        return
    if len(entries) <= max_count:
        return
    entries.sort(key=lambda x: x[0])
    remove_n = max(0, len(entries) - max_count)
    for _, jpg_path in entries[:remove_n]:
        try:
            meta_path = os.path.splitext(jpg_path)[0] + ".json"
        except Exception:
            meta_path = ""
        try:
            if os.path.isfile(jpg_path):
                os.remove(jpg_path)
        except Exception:
            pass
        if meta_path:
            try:
                if os.path.isfile(meta_path):
                    os.remove(meta_path)
            except Exception:
                pass
