import os
import time
import hashlib
import json
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QImage

from utils.sql.data_base import BirdLibraryDB
from utils.file.file_util import get_fast_id
from utils.file.fingerprint import get_smart_fingerprint


class ThumbnailDiskCache:
    """
    缩略图磁盘缓存管理器：
    1) 使用稳定键（优先 fast_id，失败则回退 smart_fingerprint）作为查找键
    2) 以 PNG 形式把缩略图落到 cache/pictures
    3) 用数据库表保存 “键 + 变体 -> 本地缓存文件” 的映射，并建立索引
    4) 提供清理逻辑（缺失文件/超限 LRU 清理）
    """

    def __init__(self, cache_manager, scope=None, cache_dir=None, db=None):
        self.cache_manager = cache_manager
        self.settings_manager = getattr(cache_manager, "settings_manager", None)
        self.db = db or BirdLibraryDB()
        if scope is None:
            scope = "import" if str(getattr(cache_manager, "context", "")).lower() == "import" else "library"
        self.scope = str(scope).lower()
        base_dir = cache_dir or os.path.join("cache", "pictures")
        self.cache_dir = os.path.join(base_dir, self.scope)
        self._last_cleanup_schedule_ts = 0.0
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            pass
        self._ensure_cache_meta()

    def is_enabled(self):
        """
        统一复用现有的“本地缩略图读写”开关：
        - performance/disable_thumbnail_persistence=True：关闭磁盘缓存
        """
        try:
            if self.settings_manager is None:
                return False
            return not bool(self.settings_manager.get("performance/disable_thumbnail_persistence", False))
        except Exception:
            return False

    def _build_cache_key(self, file_path):
        """
        生成稳定键：
        - 优先使用 get_fast_id（Windows 文件 ID / inode+ctime）
        - 失败则使用 get_smart_fingerprint（中部 1MB + size + ctime）
        """
        fid = None
        try:
            fid = get_fast_id(file_path)
        except Exception:
            fid = None
        if fid:
            return f"fid:{fid}"
        try:
            fp = get_smart_fingerprint(file_path)
        except Exception:
            fp = None
        if fp:
            return f"fp:{fp}"
        return None

    def _normalize_size(self, size):
        if not size:
            return None, None
        if isinstance(size, (tuple, list)):
            try:
                return int(size[0]), int(size[1])
            except Exception:
                return None, None
        try:
            v = int(size)
            return v, v
        except Exception:
            return None, None

    def _variant_key(self, width, height, cache_type, scale_quality, base_px):
        w = int(width or 0)
        h = int(height or 0)
        ct = str(cache_type or "general")
        q = str(scale_quality or "low")
        bp = int(base_px or 0)
        return f"{ct}:{w}x{h}:base{bp}:{q}"

    def _rel_path_for(self, cache_key, variant):
        raw = f"{cache_key}|{variant}".encode("utf-8", errors="ignore")
        digest = hashlib.sha1(raw).hexdigest()
        sub = digest[:2]
        return os.path.join(sub, f"{digest}.png")

    def _abs_path_from_rel(self, rel_path):
        return os.path.join(self.cache_dir, rel_path)

    def _encode_png_bytes(self, qimg):
        if qimg is None or qimg.isNull():
            return None
        try:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            ok = qimg.save(buf, "PNG")
            buf.close()
            if not ok:
                return None
            return bytes(ba.data())
        except Exception:
            return None

    def _atomic_write(self, abs_path, data: bytes):
        if not data:
            return False
        folder = os.path.dirname(abs_path)
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass
        tmp_path = abs_path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, abs_path)
            return True
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False

    def _read_image(self, abs_path):
        try:
            if not os.path.exists(abs_path):
                return None
            img = QImage()
            if not img.load(abs_path):
                return None
            return img
        except Exception:
            return None

    def _meta_settings_key(self):
        return f"performance/disk_thumbnail_cache_meta_{self.scope}"

    def _get_current_meta(self, base_px, scale_quality):
        try:
            bp = int(base_px or 0)
        except Exception:
            bp = 0
        q = str(scale_quality or "low").lower()
        if q not in ["low", "high"]:
            q = "low"
        try:
            disable_scaling = bool(self.settings_manager.get("performance/thumbnail_disable_scaling", False)) if self.settings_manager else False
        except Exception:
            disable_scaling = False
        try:
            force_low = bool(self.settings_manager.get("import/force_low_quality", True)) if self.settings_manager else False
        except Exception:
            force_low = False
        return {
            "base_px": int(bp),
            "quality": q,
            "disable_scaling": bool(disable_scaling),
            "import_force_low": bool(force_low) if self.scope == "import" else False,
        }

    def _ensure_cache_meta(self):
        if self.settings_manager is None:
            return
        base_px = getattr(self.cache_manager, "cache_thumbnail_size", 0)
        try:
            scale_quality = self.cache_manager.get_scale_quality() if hasattr(self.cache_manager, "get_scale_quality") else str(self.settings_manager.get("performance/thumbnail_scale_quality", "low"))
        except Exception:
            scale_quality = "low"
        current = self._get_current_meta(base_px, scale_quality)
        key = self._meta_settings_key()
        prev = None
        try:
            raw = self.settings_manager.get(key, "")
            if raw:
                prev = json.loads(str(raw))
        except Exception:
            prev = None
        if prev != current:
            self.clear_all()
        try:
            self.settings_manager.set(key, json.dumps(current, ensure_ascii=False))
            self.settings_manager.sync()
        except Exception:
            pass

    def has(self, file_path, size, cache_type="general", scale_quality="low", base_px=0):
        if not self.is_enabled():
            return False
        cache_key = self._build_cache_key(file_path)
        if not cache_key:
            return False
        w, h = self._normalize_size(size)
        if not w or not h:
            return False
        variant = self._variant_key(w, h, cache_type, scale_quality, base_px)
        row = self.db.get_thumbnail_disk_cache(cache_key, variant, scope=self.scope)
        if not row:
            return False
        rel = row.get("cache_rel_path")
        if not rel:
            return False
        abs_path = self._abs_path_from_rel(rel)
        try:
            return os.path.exists(abs_path)
        except Exception:
            return False

    def get(self, file_path, size, cache_type="general", scale_quality="low", base_px=0):
        """
        查询并读取磁盘缓存：
        - 查询条件只使用稳定键 + 变体，不使用 file_path 作为查找条件
        - 通过 mtime/size 校验文件是否变化，避免返回过时缓存
        - 如果无法获取文件 stat（如文件暂时不可访问），仍然尝试返回缓存的图片
        """
        if not self.is_enabled():
            return None
        cache_key = self._build_cache_key(file_path)
        if not cache_key:
            return None
        w, h = self._normalize_size(size)
        if not w or not h:
            return None
        variant = self._variant_key(w, h, cache_type, scale_quality, base_px)
        
        # 尝试获取文件 stat 信息用于校验
        src_size = None
        src_mtime = None
        try:
            st = os.stat(file_path)
            src_size = int(st.st_size)
            src_mtime = float(st.st_mtime)
        except Exception:
            # 文件暂时无法访问（如被移动或锁定），仍然尝试使用缓存
            pass
            
        row = self.db.get_thumbnail_disk_cache(cache_key, variant, scope=self.scope)
        if not row:
            return None
            
        # 如果成功获取了文件 stat 信息，进行校验
        if src_size is not None and src_mtime is not None:
            try:
                if int(row.get("source_size") or 0) != src_size:
                    return None
                if float(row.get("source_mtime") or 0.0) != src_mtime:
                    return None
            except Exception:
                return None
                
        rel = row.get("cache_rel_path")
        if not rel:
            return None
        abs_path = self._abs_path_from_rel(rel)
        img = self._read_image(abs_path)
        if img is None:
            try:
                self.db.delete_thumbnail_disk_cache(cache_key, variant, scope=self.scope)
            except Exception:
                pass
            return None
        try:
            self.db.touch_thumbnail_disk_cache(cache_key, variant, scope=self.scope)
        except Exception:
            pass
        return img

    def put(self, file_path, qimg: QImage, size, cache_type="general", scale_quality="low", base_px=0):
        """
        保存磁盘缓存：
        - 只保存“缩放后的最终输出图”（与当前请求的 size 对应）
        - 写入采用原子替换，避免中断造成损坏文件
        """
        if not self.is_enabled():
            return None
        cache_key = self._build_cache_key(file_path)
        if not cache_key:
            return None
        w, h = self._normalize_size(size)
        if not w or not h:
            return None
        variant = self._variant_key(w, h, cache_type, scale_quality, base_px)
        try:
            st = os.stat(file_path)
            src_size = int(st.st_size)
            src_mtime = float(st.st_mtime)
        except Exception:
            return None
        rel = self._rel_path_for(cache_key, variant)
        abs_path = self._abs_path_from_rel(rel)
        data = self._encode_png_bytes(qimg)
        if not data:
            return None
        if not self._atomic_write(abs_path, data):
            return None
        self.db.upsert_thumbnail_disk_cache(
            cache_key=cache_key,
            variant=variant,
            cache_rel_path=rel,
            source_size=src_size,
            source_mtime=src_mtime,
            cache_bytes=len(data),
            file_path=file_path,
            scope=self.scope,
        )
        self._schedule_cleanup_if_needed()
        return rel

    def clear_all(self):
        try:
            self.db.clear_thumbnail_disk_cache(scope=self.scope)
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(self.cache_dir, ignore_errors=True)
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception:
            pass

    def invalidate_file(self, file_path: str):
        p = str(file_path or "").strip()
        if not p:
            return
        cache_key = self._build_cache_key(p)
        if not cache_key:
            return
        try:
            rows = self.db.list_thumbnail_disk_cache_by_key(cache_key, scope=self.scope)
        except Exception:
            rows = []
        for r in rows:
            rel = str((r or {}).get("cache_rel_path") or "")
            if not rel:
                continue
            abs_path = self._abs_path_from_rel(rel)
            try:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            except Exception:
                pass
        try:
            self.db.delete_thumbnail_disk_cache_by_key(cache_key, scope=self.scope)
        except Exception:
            pass

    def invalidate_many(self, file_paths: list[str] | tuple[str, ...]):
        for p in (file_paths or []):
            try:
                self.invalidate_file(str(p or ""))
            except Exception:
                pass

    def _get_cleanup_limits(self):
        max_bytes = 2 * 1024 * 1024 * 1024
        batch = 500
        try:
            if self.settings_manager is not None:
                max_bytes = int(self.settings_manager.get("performance/disk_thumbnail_cache_max_bytes", max_bytes))
                batch = int(self.settings_manager.get("performance/disk_thumbnail_cache_cleanup_batch", batch))
        except Exception:
            pass
        if max_bytes < 0:
            max_bytes = 0
        if batch < 10:
            batch = 10
        return max_bytes, batch

    def _schedule_cleanup_if_needed(self):
        max_bytes, _ = self._get_cleanup_limits()
        if max_bytes <= 0:
            return
        now = time.time()
        if now - self._last_cleanup_schedule_ts < 6.0:
            return
        self._last_cleanup_schedule_ts = now
        try:
            total = self.db.sum_thumbnail_disk_cache_bytes(scope=self.scope)
        except Exception:
            total = 0
        if total > max_bytes:
            self.cleanup_async(delay_sec=1.5)

    def cleanup(self):
        """
        清理过时缓存：
        1) 删除数据库记录存在但文件缺失的条目
        2) 若总字节数超限，则按加入时间(created_at)从旧到新删除，直到低于上限或达到单次清理数量
        """
        if not self.is_enabled():
            return
        max_bytes, batch = self._get_cleanup_limits()
        if max_bytes <= 0:
            return

        removed = 0
        try:
            total_bytes = int(self.db.sum_thumbnail_disk_cache_bytes(scope=self.scope))
        except Exception:
            total_bytes = 0
        stale = self.db.list_thumbnail_disk_cache(scope=self.scope, order_by_created_asc=True, limit=200000)
        for r in stale:
            if removed >= batch:
                break
            rel = r.get("cache_rel_path")
            if not rel:
                continue
            abs_path = self._abs_path_from_rel(rel)
            exists = False
            size_bytes = int(r.get("cache_bytes") or 0)
            try:
                exists = os.path.exists(abs_path)
            except Exception:
                exists = False
            if not exists:
                try:
                    self.db.delete_thumbnail_disk_cache(r.get("cache_key"), r.get("variant"), scope=self.scope)
                except Exception:
                    pass
                removed += 1
                continue

            if total_bytes > max_bytes:
                try:
                    os.remove(abs_path)
                except Exception:
                    pass
                try:
                    self.db.delete_thumbnail_disk_cache(r.get("cache_key"), r.get("variant"), scope=self.scope)
                except Exception:
                    pass
                total_bytes = max(0, total_bytes - size_bytes)
                removed += 1

    def cleanup_async(self, delay_sec=5.0):
        if not self.is_enabled():
            return
        try:
            delay_sec = float(delay_sec)
        except Exception:
            delay_sec = 5.0

        def _worker():
            try:
                time.sleep(max(0.0, delay_sec))
                self.cleanup()
            except Exception:
                pass

        from threading import Thread
        t = Thread(target=_worker, daemon=True, name="ThumbnailDiskCacheCleanup")
        t.start()
