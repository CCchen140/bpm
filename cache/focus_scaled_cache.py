import hashlib
import json
import os
import threading
from typing import Any

import cv2
import numpy as np
from PyQt6.QtGui import QImage
from utils.system.stderr_suppressor import suppress_stderr_fd

_lock = threading.Lock()


def _project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    except Exception:
        return os.getcwd()


def get_cache_dir(scope: str = "import_focus") -> str:
    """获取对焦检测缩略图缓存目录

    使用绝对路径，避免多进程环境下工作目录不同导致的问题
    """
    try:
        # 获取当前文件所在目录，然后上一级到项目根目录
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_file_dir, os.pardir))
        base = os.path.join(project_root, "cache")
        s = str(scope or "import_focus").lower()
        if s in ["import_focus", "focus_scaled", "focus"]:
            cache_dir = os.path.join(base, "focus_scaled")
        else:
            cache_dir = os.path.join(base, f"focus_scaled_{s}")
        # 确保目录存在
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            pass
        return cache_dir
    except Exception:
        # 如果失败，使用基于当前工作目录的路径（兼容旧逻辑）
        base = os.path.join(_project_root(), "cache")
        s = str(scope or "import_focus").lower()
        if s in ["import_focus", "focus_scaled", "focus"]:
            return os.path.join(base, "focus_scaled")
        return os.path.join(base, f"focus_scaled_{s}")


def _max_count_from_settings(default: int = 500) -> int:
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
    """
    try:
        # 使用normpath规范化路径分隔符
        path = os.path.normpath(str(image_path))
        # 在Windows上转换为小写，确保大小写不敏感
        if os.name == "nt":
            path = path.lower()
        return path
    except Exception:
        return str(image_path)


def build_key(image_path: str, target_size: int) -> str:
    """构建缓存键

    注意：不使用 mtime_ns（修改时间）作为键的一部分，因为：
    1. 文件在对焦检测后可能被其他软件修改（如添加标签）
    2. 这会导致缓存键不匹配，即使文件内容没有实质变化
    3. 使用文件路径和大小足以识别文件
    """
    try:
        st = os.stat(image_path)
        # 只使用文件路径和大小作为键，不使用修改时间
        # 使用规范化后的路径，确保Windows上大小写不敏感
        normalized_path = _normalize_path_for_key(image_path)
        token = f"{normalized_path}|{int(st.st_size)}|{int(target_size)}"
    except Exception:
        normalized_path = _normalize_path_for_key(image_path)
        token = f"{normalized_path}|0|{int(target_size)}"
    return hashlib.sha1(token.encode("utf-8", errors="ignore")).hexdigest()


def get_paths(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[str, str]:
    key = build_key(image_path, int(target_size or 0))
    d = get_cache_dir(scope)
    return os.path.join(d, f"{key}.jpg"), os.path.join(d, f"{key}.json")


def try_load_qimage(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[QImage | None, dict[str, Any] | None]:
    """尝试加载缓存图片

    同时尝试新旧两种格式的缓存键，兼容旧缓存
    """
    # 先尝试新格式缓存
    jpg_path, meta_path = get_paths(image_path, target_size, scope=scope)
    use_legacy = False
    try:
        jpg_exists = os.path.isfile(jpg_path)
        meta_exists = os.path.isfile(meta_path)
        if not jpg_exists or not meta_exists:
            # 尝试旧格式缓存
            jpg_path_old, meta_path_old = _get_paths_legacy(image_path, target_size, scope=scope)
            jpg_exists_old = os.path.isfile(jpg_path_old)
            meta_exists_old = os.path.isfile(meta_path_old)
            if jpg_exists_old and meta_exists_old:
                jpg_path, meta_path = jpg_path_old, meta_path_old
                use_legacy = True
            else:
                return None, None
    except Exception:
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
        return None, meta
    try:
        os.utime(jpg_path, None)
    except Exception:
        pass
    return img, meta


def try_load_cv_bgr(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[np.ndarray | None, dict[str, Any] | None]:
    jpg_path, meta_path = get_paths(image_path, target_size, scope=scope)
    try:
        if not os.path.isfile(jpg_path) or not os.path.isfile(meta_path):
            return None, None
    except Exception:
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
    _jpg_path, meta_path = get_paths(image_path, target_size, scope=scope)
    try:
        if not os.path.isfile(meta_path):
            return None
    except Exception:
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except Exception:
        return None


def _build_key_legacy(image_path: str, target_size: int) -> str:
    """旧版本的缓存键生成（包含 mtime_ns）

    用于兼容旧缓存，在过渡期后应删除
    """
    try:
        st = os.stat(image_path)
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        token = f"{image_path}|{int(st.st_size)}|{mtime_ns}|{int(target_size)}"
    except Exception:
        token = f"{image_path}|0|0|{int(target_size)}"
    return hashlib.sha1(token.encode("utf-8", errors="ignore")).hexdigest()


def _get_paths_legacy(image_path: str, target_size: int, scope: str = "import_focus") -> tuple[str, str]:
    """获取旧版本缓存路径"""
    key = _build_key_legacy(image_path, int(target_size or 0))
    d = get_cache_dir(scope)
    return os.path.join(d, f"{key}.jpg"), os.path.join(d, f"{key}.json")


def has(image_path: str, target_size: int, scope: str = "import_focus") -> bool:
    """检查缓存是否存在，不实际加载图片

    同时检查新旧两种格式的缓存键，兼容旧缓存
    """
    # 检查新格式缓存
    jpg_path, meta_path = get_paths(image_path, target_size, scope=scope)
    try:
        if os.path.isfile(jpg_path) and os.path.isfile(meta_path):
            return True
    except Exception:
        pass
    
    # 检查旧格式缓存（兼容过渡期）
    try:
        jpg_path_old, meta_path_old = _get_paths_legacy(image_path, target_size, scope=scope)
        if os.path.isfile(jpg_path_old) and os.path.isfile(meta_path_old):
            return True
    except Exception:
        pass
    
    return False


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
    enforce_limit(scope=scope)


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
    if bgr is None or not isinstance(bgr, np.ndarray) or bgr.size <= 0:
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
            q = int(max(50, min(95, int(quality))))
        except Exception:
            q = 90
        try:
            ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(q)])
        except Exception:
            ok, buf = False, None
        if not ok or buf is None:
            return
        try:
            with open(tmp, "wb") as f:
                f.write(buf.tobytes())
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
    enforce_limit(scope=scope)


def enforce_limit(scope: str = "import_focus"):
    cache_dir = get_cache_dir(scope)
    try:
        max_count = int(_max_count_from_settings(500))
    except Exception:
        max_count = 500
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
