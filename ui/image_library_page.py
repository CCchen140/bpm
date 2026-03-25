import os
import json
import re
import subprocess
import exifread
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout,
                             QHBoxLayout, QListWidget, QLabel,
                             QMessageBox, QFrame, QPushButton, QListWidgetItem,
                             QLineEdit, QSizePolicy, 
                             QComboBox, QSlider, QGridLayout, QStatusBar, QSplitter, QMenu, QFileDialog, QInputDialog)

from PyQt6.QtCore import Qt, QSize, QRect, QTimer, QPoint, QEvent, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QShortcut, QKeySequence, QImageReader, QPainter, QColor, QPen, QBrush, QRadialGradient, QIcon
import threading
import time
from collections import deque
from datetime import datetime

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

from ui.utils.icon_loader import qta

from ui.widgets.rating_filter_button import RatingFilterButton
from ui.widgets.rating_filter_widget import StarRatingWidget, StarMenuAction
from ui.widgets.image_thumbnail import ImageThumbnail
from ui.widgets.remark_dialog import RemarkDialog
from ui.widgets.geolocation_dialog import GeoLocationDialog
from ui.zoomable_scroll_area import ZoomableScrollArea
from ui.widgets.advanced_filter_panel import AdvancedFilterPanel
from ui.widgets.batch_rename_dialog import BatchRenameDialog
from ui.panels.info_panel import InfoPanel
from ui.panels.preview_panel import PreviewPanel
from ui.panels.folder_panel import FolderPanel
from ui.utils.notification_manager import NotificationManager
from ui.utils.color_manager import ColorManager
from ui.utils.thumbnail_loader import ThumbnailLoader
from utils.sql.data_base import BirdLibraryDB
from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG
from cache.cache_manager import ImageCacheManager
from cache.big_image_cache_manager import BigImageCacheManager
from utils.setting.settings_manager import SettingsManager
from ui.utils.status_manager import StatusManager
from ui.utils.shortcut_manager import ShortcutManager
from utils.system.task_scheduler import TaskType, TaskScheduler
from utils.log_manager import LogManager

from ui.library.views.toolbar_view import ToolbarView
from ui.library.views.thumbnail_grid_view import ThumbnailGridView
from ui.library.views.virtual_thumbnail_grid_view import VirtualThumbnailGridView
from ui.common.base_page import BaseImageBrowserPage
from ui.panels.image_detail_panel import ImageDetailPanel
from ui.common.styles import TOOLBAR_BTN_STYLE

import utils.file.file as file_utils
from urllib.parse import parse_qs, urlparse
import shutil

from ui.dialogs.edit_species_dialog import EditSpeciesDialog

class FolderLoadWorker(QThread):
    finished = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = str(folder_path or "")
        self.is_cancelled = False

    def _normalize_path_str(self, path):
        if not path:
            return ""
        try:
            p = str(path)
        except Exception:
            p = path
        try:
            p = os.path.normpath(p)
        except Exception:
            pass
        if os.name == "nt":
            try:
                p = p.replace("/", "\\")
            except Exception:
                pass
        return p

    def _parse_datetime_to_ts(self, value):
        if value is None:
            return 0.0
        s = str(value).strip()
        if not s:
            return 0.0
        s = s.replace("T", " ").strip()
        if s.endswith("Z"):
            s = s[:-1].strip()
        fmts = [
            "%Y:%m:%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y:%m:%d %H:%M",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y:%m:%d",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ]
        for fmt in fmts:
            try:
                return float(datetime.strptime(s, fmt).timestamp())
            except Exception:
                continue
        try:
            if len(s) >= 19 and s[4] == ":" and s[7] == ":":
                s2 = f"{s[0:4]}-{s[5:7]}-{s[8:10]}{s[10:]}"
                return float(datetime.strptime(s2, "%Y-%m-%d %H:%M:%S").timestamp())
        except Exception:
            pass
        return 0.0

    def run(self):
        folder_path = self._normalize_path_str(self.folder_path)
        if not folder_path or not os.path.exists(folder_path):
            self.finished.emit(folder_path, [])
            return
        image_extensions = set(ext.lower() for ext in file_utils.img_exts + file_utils.raw_exts)
        fs_files = []
        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if self.is_cancelled:
                        return
                    try:
                        if entry.is_file() and os.path.splitext(entry.name)[1].lower() in image_extensions:
                            fs_files.append(self._normalize_path_str(entry.path))
                    except Exception:
                        continue
        except Exception as e:
            self.failed.emit(folder_path, f"扫描文件夹失败: {e}")
            return

        if self.is_cancelled:
            return
        if not fs_files:
            self.finished.emit(folder_path, [])
            return

        db = BirdLibraryDB()
        loaded_files = []
        try:
            norm_folder = os.path.normpath(folder_path)
            species_name_fallback = os.path.basename(norm_folder)
            conn = db._get_connection()
            cursor = conn.cursor()

            default_taxonomy = {"order": "", "family": "", "genus": ""}
            try:
                cursor.execute(
                    "SELECT order_cls, family_cls, genus_cls FROM bird_results WHERE species_cls = ? LIMIT 1",
                    (species_name_fallback,)
                )
                tax_row = cursor.fetchone()
                if tax_row:
                    default_taxonomy["order"] = tax_row["order_cls"]
                    default_taxonomy["family"] = tax_row["family_cls"]
                    default_taxonomy["genus"] = tax_row["genus_cls"]
            except Exception:
                pass

            db_info_map = {}
            chunk_size = 500
            for i in range(0, len(fs_files), chunk_size):
                if self.is_cancelled:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    return
                chunk = fs_files[i:i + chunk_size]
                placeholders = ",".join(["?"] * len(chunk))
                if os.name == "nt":
                    query_clause = "lower(replace(file_path, '/', '\\'))"
                    chunk_keys = [os.path.normcase(p) for p in chunk]
                else:
                    query_clause = "lower(file_path)"
                    chunk_keys = [p.lower() for p in chunk]

                cursor.execute(
                    f"SELECT file_path, shot_time, created_at, position, score, norm_score, bbox, focus_point, focus_detect_json, "
                    f"label, order_cls, family_cls, genus_cls, species_cls, is_favorite, rating, uuid, "
                    f"fnumber, shutter, iso, focal_length, camera_model, lens_model, tags, location "
                    f"FROM bird_results WHERE {query_clause} IN ({placeholders})",
                    chunk_keys
                )
                rows = cursor.fetchall()
                for row in rows:
                    norm_p = os.path.normcase(os.path.normpath(row["file_path"]))

                    def _row_quality(r):
                        try:
                            label_val = r["label"]
                            has_label = bool(label_val and str(label_val).strip() and str(label_val).strip() != "None")
                        except Exception:
                            has_label = False
                        try:
                            bbox_v = r["bbox"]
                            has_bbox = 1 if (bbox_v not in (None, "", "None")) else 0
                        except Exception:
                            has_bbox = 0
                        try:
                            fp_v = r["focus_point"]
                            has_fp = 1 if (fp_v not in (None, "", "None")) else 0
                        except Exception:
                            has_fp = 0
                        try:
                            fdj = r["focus_detect_json"]
                            has_fdj = 1 if (fdj and str(fdj).strip() and str(fdj).strip() != "None") else 0
                        except Exception:
                            has_fdj = 0
                        try:
                            is_fav = 1 if (r["is_favorite"] or 0) else 0
                        except Exception:
                            is_fav = 0
                        try:
                            rating = int(r["rating"] or 0)
                        except Exception:
                            rating = 0
                        try:
                            has_uuid = 1 if r["uuid"] else 0
                        except Exception:
                            has_uuid = 0
                        try:
                            t = r["shot_time"] or r["created_at"] or ""
                            t = str(t)
                        except Exception:
                            t = ""
                        return (has_bbox, has_fp, has_fdj, 1 if has_label else 0, is_fav, rating, has_uuid, t)

                    exist = db_info_map.get(norm_p)
                    if not exist or _row_quality(row) > _row_quality(exist):
                        db_info_map[norm_p] = row

            try:
                conn.close()
            except Exception:
                pass

            for file_path in fs_files:
                if self.is_cancelled:
                    return
                norm_path = os.path.normcase(os.path.normpath(file_path))
                row = db_info_map.get(norm_path)
                width = 0
                height = 0
                try:
                    r = QImageReader(file_path)
                    s = r.size()
                    if s.isValid():
                        width = int(s.width())
                        height = int(s.height())
                except Exception:
                    width = 0
                    height = 0

                def _is_missing_exif(v):
                    if v is None:
                        return True
                    try:
                        if isinstance(v, (int, float)):
                            return float(v) <= 0
                    except Exception:
                        pass
                    try:
                        return not bool(str(v).strip())
                    except Exception:
                        return True

                def _read_exif_quick(p):
                    try:
                        ext = os.path.splitext(p)[1].lower()
                    except Exception:
                        ext = ""
                    try:
                        raw_exts = set(str(x).lower() for x in (file_utils.raw_exts or []))
                    except Exception:
                        raw_exts = set()
                    if ext in raw_exts:
                        return {}
                    try:
                        with open(p, "rb") as f:
                            tags = exifread.process_file(f, details=False, strict=False)
                    except Exception:
                        return {}
                    out = {}
                    try:
                        v = tags.get("EXIF ISOSpeedRatings") or tags.get("EXIF PhotographicSensitivity")
                        if v is not None:
                            out["iso"] = str(getattr(v, "printable", v)).strip()
                    except Exception:
                        pass
                    try:
                        v = tags.get("EXIF FNumber")
                        if v is not None:
                            out["fnumber"] = str(getattr(v, "printable", v)).strip()
                    except Exception:
                        pass
                    try:
                        v = tags.get("EXIF ExposureTime") or tags.get("EXIF ShutterSpeedValue")
                        if v is not None:
                            out["shutter"] = str(getattr(v, "printable", v)).strip()
                    except Exception:
                        pass
                    try:
                        v = tags.get("EXIF FocalLength")
                        if v is not None:
                            out["focal_length"] = str(getattr(v, "printable", v)).strip()
                    except Exception:
                        pass
                    try:
                        v = tags.get("Image Model") or tags.get("EXIF Model")
                        if v is not None:
                            out["camera_model"] = str(getattr(v, "printable", v)).strip()
                    except Exception:
                        pass
                    try:
                        v = tags.get("EXIF LensModel") or tags.get("EXIF Lens Model")
                        if v is not None:
                            out["lens_model"] = str(getattr(v, "printable", v)).strip()
                    except Exception:
                        pass
                    return out

                if row:
                    time_str = ""
                    create_ts = 0.0
                    size_bytes = 0
                    try:
                        stat = os.stat(file_path)
                        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime))
                        create_ts = float(stat.st_ctime)
                        size_bytes = int(getattr(stat, "st_size", 0) or 0)
                    except Exception:
                        time_str = row["shot_time"] if row["shot_time"] else str(row["created_at"])
                        create_ts = 0.0
                    iso_v = row["iso"]
                    fnumber_v = row["fnumber"]
                    shutter_v = row["shutter"]
                    focal_v = row["focal_length"]
                    cam_v = row["camera_model"]
                    lens_v = row["lens_model"]
                    if _is_missing_exif(iso_v) or _is_missing_exif(fnumber_v) or _is_missing_exif(shutter_v) or _is_missing_exif(focal_v) or _is_missing_exif(cam_v) or _is_missing_exif(lens_v):
                        ex = _read_exif_quick(file_path)
                        if ex:
                            if _is_missing_exif(iso_v) and ex.get("iso"):
                                iso_v = ex.get("iso")
                            if _is_missing_exif(fnumber_v) and ex.get("fnumber"):
                                fnumber_v = ex.get("fnumber")
                            if _is_missing_exif(shutter_v) and ex.get("shutter"):
                                shutter_v = ex.get("shutter")
                            if _is_missing_exif(focal_v) and ex.get("focal_length"):
                                focal_v = ex.get("focal_length")
                            if _is_missing_exif(cam_v) and ex.get("camera_model"):
                                cam_v = ex.get("camera_model")
                            if _is_missing_exif(lens_v) and ex.get("lens_model"):
                                lens_v = ex.get("lens_model")
                    loaded_files.append({
                        "path": file_path,
                        "name": os.path.basename(file_path),
                        "create_time": time_str,
                        "create_ts": create_ts,
                        "shot_time": row["shot_time"] or "",
                        "shot_ts": self._parse_datetime_to_ts(row["shot_time"] or "") or create_ts,
                        "size": size_bytes,
                        "width": width,
                        "height": height,
                        "position": row["position"],
                        "score": row["score"],
                        "norm_score": row["norm_score"],
                        "bbox": row["bbox"] if "bbox" in row.keys() else None,
                        "focus_point": row["focus_point"] if "focus_point" in row.keys() else None,
                        "focus_detect_json": row["focus_detect_json"] if "focus_detect_json" in row.keys() else "",
                        "label": row["label"] or "",
                        "order": row["order_cls"] or default_taxonomy["order"],
                        "family": row["family_cls"] or default_taxonomy["family"],
                        "genus": row["genus_cls"] or default_taxonomy["genus"],
                        "species": row["species_cls"] or species_name_fallback,
                        "is_favorite": row["is_favorite"],
                        "rating": row["rating"] or 0,
                        "uuid": row["uuid"],
                        "fnumber": fnumber_v,
                        "shutter": shutter_v,
                        "iso": iso_v,
                        "focal_length": focal_v,
                        "camera_model": cam_v,
                        "lens_model": lens_v,
                        "tags": row["tags"] if "tags" in row.keys() else "",
                        "location": row["location"] if "location" in row.keys() else "",
                    })
                else:
                    stat = os.stat(file_path)
                    create_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime))
                    create_ts = float(stat.st_ctime)
                    loaded_files.append({
                        "path": file_path,
                        "name": os.path.basename(file_path),
                        "create_time": create_time,
                        "create_ts": create_ts,
                        "shot_time": "",
                        "shot_ts": create_ts,
                        "size": int(getattr(stat, "st_size", 0) or 0),
                        "width": width,
                        "height": height,
                        "position": "",
                        "score": 0,
                        "norm_score": 0,
                        "bbox": None,
                        "focus_point": None,
                        "focus_detect_json": "",
                        "label": "",
                        "order": default_taxonomy["order"],
                        "family": default_taxonomy["family"],
                        "genus": default_taxonomy["genus"],
                        "species": species_name_fallback,
                        "is_favorite": 0,
                        "rating": 0,
                        "uuid": None,
                        "fnumber": None,
                        "shutter": None,
                        "iso": None,
                        "focal_length": None,
                        "camera_model": None,
                        "lens_model": None,
                        "tags": "",
                        "location": "",
                    })

        except Exception as e:
            self.failed.emit(folder_path, f"读取数据库失败: {e}")
            return

        if self.is_cancelled:
            return
        self.finished.emit(folder_path, loaded_files)


class TaxonomyLoadWorker(QThread):
    finished = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, taxonomy_uri: str, db: BirdLibraryDB, root_path: str = ""):
        super().__init__()
        self.taxonomy_uri = str(taxonomy_uri or "")
        self.db = db
        self.root_path = str(root_path or "")
        self.is_cancelled = False

    def run(self):
        uri = str(self.taxonomy_uri or "")
        if not uri:
            self.finished.emit(uri, [])
            return
        try:
            if uri.startswith("virtual://taxonomy/unclassified"):
                parsed = urlparse(uri.replace("virtual://taxonomy", "http://taxonomy", 1))
                qs = parse_qs(parsed.query or "")
                d = (qs.get("dir") or [""])[0]
                if d:
                    try:
                        from urllib.parse import unquote
                        d = unquote(d)
                    except Exception:
                        pass
                    rows = self.db.query_unclassified_images_in_folder(d, table_name="bird_results", root_path=self.root_path)
                else:
                    rows = self.db.query_images_by_taxonomy(unclassified=True, table_name="bird_results", root_path=self.root_path)
            else:
                parsed = urlparse(uri.replace("virtual://taxonomy", "http://taxonomy", 1))
                qs = parse_qs(parsed.query or "")
                order_cls = (qs.get("order") or [""])[0]
                family_cls = (qs.get("family") or [""])[0]
                genus_cls = (qs.get("genus") or [""])[0]
                species_cls = (qs.get("species") or [""])[0]
                rows = self.db.query_images_by_taxonomy(
                    order_cls=order_cls or None,
                    family_cls=family_cls or None,
                    genus_cls=genus_cls or None,
                    species_cls=species_cls or None,
                    unclassified=False,
                    table_name="bird_results",
                    root_path=self.root_path,
                )
        except Exception as e:
            self.failed.emit(uri, f"读取数据库失败: {e}")
            return

        if self.is_cancelled:
            return
        loaded_files = []
        try:
            def _is_missing_exif(v):
                if v is None:
                    return True
                try:
                    if isinstance(v, (int, float)):
                        return float(v) <= 0
                except Exception:
                    pass
                try:
                    return not bool(str(v).strip())
                except Exception:
                    return True

            def _read_exif_quick(p):
                try:
                    ext = os.path.splitext(p)[1].lower()
                except Exception:
                    ext = ""
                try:
                    raw_exts = set(str(x).lower() for x in (file_utils.raw_exts or []))
                except Exception:
                    raw_exts = set()
                if ext in raw_exts:
                    return {}
                try:
                    with open(p, "rb") as f:
                        tags = exifread.process_file(f, details=False, strict=False)
                except Exception:
                    return {}
                out = {}
                try:
                    v = tags.get("EXIF ISOSpeedRatings") or tags.get("EXIF PhotographicSensitivity")
                    if v is not None:
                        out["iso"] = str(getattr(v, "printable", v)).strip()
                except Exception:
                    pass
                try:
                    v = tags.get("EXIF FNumber")
                    if v is not None:
                        out["fnumber"] = str(getattr(v, "printable", v)).strip()
                except Exception:
                    pass
                try:
                    v = tags.get("EXIF ExposureTime") or tags.get("EXIF ShutterSpeedValue")
                    if v is not None:
                        out["shutter"] = str(getattr(v, "printable", v)).strip()
                except Exception:
                    pass
                try:
                    v = tags.get("EXIF FocalLength")
                    if v is not None:
                        out["focal_length"] = str(getattr(v, "printable", v)).strip()
                except Exception:
                    pass
                try:
                    v = tags.get("Image Model") or tags.get("EXIF Model")
                    if v is not None:
                        out["camera_model"] = str(getattr(v, "printable", v)).strip()
                except Exception:
                    pass
                try:
                    v = tags.get("EXIF LensModel") or tags.get("EXIF Lens Model")
                    if v is not None:
                        out["lens_model"] = str(getattr(v, "printable", v)).strip()
                except Exception:
                    pass
                return out

            for row in (rows or []):
                if self.is_cancelled:
                    return
                try:
                    fp = str(row["file_path"] or "")
                except Exception:
                    fp = ""
                if not fp:
                    continue
                try:
                    if not os.path.exists(fp):
                        continue
                except Exception:
                    pass
                try:
                    shot_time = row["shot_time"] or ""
                except Exception:
                    shot_time = ""
                try:
                    created_at = row["created_at"] or ""
                except Exception:
                    created_at = ""
                try:
                    time_str = str(shot_time or created_at or "")
                except Exception:
                    time_str = ""
                size_bytes = 0
                try:
                    stat = os.stat(fp)
                    size_bytes = int(getattr(stat, "st_size", 0) or 0)
                except Exception:
                    size_bytes = 0
                width = 0
                height = 0
                try:
                    r = QImageReader(fp)
                    s = r.size()
                    if s.isValid():
                        width = int(s.width())
                        height = int(s.height())
                except Exception:
                    width = 0
                    height = 0

                iso_v = row["iso"]
                fnumber_v = row["fnumber"]
                shutter_v = row["shutter"]
                focal_v = row["focal_length"]
                cam_v = row["camera_model"]
                lens_v = row["lens_model"]
                if _is_missing_exif(iso_v) or _is_missing_exif(fnumber_v) or _is_missing_exif(shutter_v) or _is_missing_exif(focal_v) or _is_missing_exif(cam_v) or _is_missing_exif(lens_v):
                    ex = _read_exif_quick(fp)
                    if ex:
                        if _is_missing_exif(iso_v) and ex.get("iso"):
                            iso_v = ex.get("iso")
                        if _is_missing_exif(fnumber_v) and ex.get("fnumber"):
                            fnumber_v = ex.get("fnumber")
                        if _is_missing_exif(shutter_v) and ex.get("shutter"):
                            shutter_v = ex.get("shutter")
                        if _is_missing_exif(focal_v) and ex.get("focal_length"):
                            focal_v = ex.get("focal_length")
                        if _is_missing_exif(cam_v) and ex.get("camera_model"):
                            cam_v = ex.get("camera_model")
                        if _is_missing_exif(lens_v) and ex.get("lens_model"):
                            lens_v = ex.get("lens_model")
                loaded_files.append({
                    "path": fp,
                    "name": str(row["file_name"] or os.path.basename(fp)),
                    "create_time": time_str,
                    "create_ts": 0.0,
                    "shot_time": str(shot_time or ""),
                    "shot_ts": 0.0,
                    "size": size_bytes,
                    "width": width,
                    "height": height,
                    "position": row["position"],
                    "score": row["score"],
                    "norm_score": row["norm_score"],
                    "bbox": row["bbox"] if "bbox" in row.keys() else None,
                    "focus_point": row["focus_point"] if "focus_point" in row.keys() else None,
                    "focus_detect_json": row["focus_detect_json"] if "focus_detect_json" in row.keys() else "",
                    "label": row["label"] or "",
                    "order": row["order_cls"] or "",
                    "family": row["family_cls"] or "",
                    "genus": row["genus_cls"] or "",
                    "species": row["species_cls"] or "",
                    "is_favorite": row["is_favorite"],
                    "rating": row["rating"] or 0,
                    "uuid": row["uuid"],
                    "fnumber": fnumber_v,
                    "shutter": shutter_v,
                    "iso": iso_v,
                    "focal_length": focal_v,
                    "camera_model": cam_v,
                    "lens_model": lens_v,
                    "tags": row["tags"] if "tags" in row.keys() else "",
                    "location": row["location"] if "location" in row.keys() else "",
                })
        except Exception as e:
            self.failed.emit(uri, f"构造列表失败: {e}")
            return

        if self.is_cancelled:
            return
        self.finished.emit(uri, loaded_files)

# 图片库页面
class ImageLibraryPage(BaseImageBrowserPage):
    # total_in_view, currently_loaded, selected_count
    stats_changed = pyqtSignal(int, int, int)
    
    def __init__(self):
        super().__init__()
        self.db = BirdLibraryDB()
        self.current_original_pixmap = None  # 缓存当前预览的原图
        self.cache_manager = ImageCacheManager()
        self.big_image_cache = BigImageCacheManager.instance("library")
        self._library_cache_loading_started = False
        self._special_cache_inited = False
        self.thumbnail_loader = ThumbnailLoader(self.cache_manager, TaskType.LIBRARY_LOADER)
        self.thumbnail_loader.signals.loaded.connect(self.on_thumbnail_loaded)
        self._thumbnail_request_id = 0
        self._thumb_by_path = {}
        self._requested_paths = set()
        self._startup_mask_enabled = True
        self._startup_mask_visible = False
        self._startup_pending_paths = set()
        self._startup_mask_ready = False
        self._startup_blocking_show = False
        self._startup_mask_timeout_timer = QTimer()
        self._startup_mask_timeout_timer.setSingleShot(True)
        self._startup_mask_timeout_timer.timeout.connect(self._force_hide_startup_mask)
        self._thumbnail_loaded_retry_delay_ms = 60
        self._thumbnail_loaded_retry_max = 20
        self._pending_updates = deque()
        self._update_batch_size = 20
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(0)
        self._update_timer.timeout.connect(self._process_pending_updates)
        self._visible_load_force_cancel = False
        self._current_visible_path_keys = set()
        self._pending_visible_path_keys = set()
        self._visible_load_timer = QTimer(self)
        self._visible_load_timer.setSingleShot(True)
        self._visible_load_timer.timeout.connect(self._load_visible_thumbnails)
        self._idle_visible_load_timer = QTimer(self)
        self._idle_visible_load_timer.setInterval(200)
        self._idle_visible_load_timer.timeout.connect(self._on_idle_visible_load_tick)
        try:
            self._idle_visible_load_timer.start()
        except Exception:
            pass
        self._mouse_busy = False
        self._mouse_busy_loader_threads = 1
        self._default_loader_threads = TaskScheduler.instance().get_thread_count(TaskType.LIBRARY_LOADER)
        self._mouse_busy_timer = QTimer(self)
        self._mouse_busy_timer.setSingleShot(True)
        self._mouse_busy_timer.timeout.connect(lambda: (setattr(self, "_mouse_busy", False), self.thumbnail_loader.set_max_thread_count(self._default_loader_threads), self._schedule_visible_load(immediate=True)))
        self._fast_scroll_active = False
        self._thumbnail_ui_suspended = False
        self._fast_scroll_timer = QTimer(self)
        self._fast_scroll_timer.setSingleShot(True)
        self._fast_scroll_timer.timeout.connect(self._on_fast_scroll_timeout)
        self._last_scroll_value = None
        self._scroll_direction = 0
        self._last_visible_start = None
        self._last_visible_end = None
        self.settings_manager = SettingsManager()
        self._settings_loaded = False  # 标记设置是否已加载完成
        self._event_filter_installed = False  # 全局事件过滤器状态
        self.current_folder_path = "" # 当前文件夹路径
        self._folder_view_state_map = self._load_folder_view_state_map()
        self._folder_view_state_save_timer = QTimer(self)
        self._folder_view_state_save_timer.setSingleShot(True)
        self._folder_view_state_save_timer.timeout.connect(self._persist_folder_view_state_now)
        self._pending_restore_folder_key = None
        self._pending_restore_state = None
        self._pending_restore_applied = True
        self._spray_exit_shortcut = None
        self._select_all_shortcut = None
        self._open_detail_shortcut = None
        self._select_all_active = False
        
        # 懒加载相关变量
        self.batch_size = 50        # 每次加载的数量
        self.current_loaded_count = 0 # 当前已加载的数量
        self.all_image_files = []   # 所有待显示的图片信息 (用于懒加载)
        self.image_files = []       # 当前符合过滤条件的文件列表 (用于排序)
        self.raw_image_files = []   # 当前文件夹下的所有原始图片信息（未经过滤）
        self.is_lazy_loading = False # 是否正在懒加载模式
        
        # 快速过滤状态
        self.favorite_filter = False
        self.rating_filter = 0
        self.sort_field_mode = "文件名"
        self.sort_order = None

        self._global_all_base_root = None

        self._global_all_base_strict = None
        self._global_all_base_files = None
        
        # 缩略图调整大小防抖定时器
        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(30)
        self.resize_timer.timeout.connect(self._perform_resize)
        self._is_slider_dragging = False
        self._pending_splitter_update = False
        
        self.init_ui()

    def shutdown(self):
        """页面关闭时的清理工作"""
        if hasattr(self, "thumbnail_loader"):
            self.thumbnail_loader.shutdown()
        
        # 停止可能存在的后台线程
        # 注意：cache_manager 的线程由 cache_manager 自己管理，或者我们在 main_window 统一处理
        pass

    def release_memory_caches(self):
        try:
            if hasattr(self, "thumbnail_loader") and self.thumbnail_loader:
                try:
                    self.thumbnail_loader.cancel_all()
                except Exception:
                    pass
                try:
                    self.thumbnail_loader.cancel_pending()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if hasattr(self, "cache_manager") and self.cache_manager:
                try:
                    self.cache_manager.stop_preload()
                except Exception:
                    pass
                try:
                    self.cache_manager.clear()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if hasattr(self, "big_image_cache") and self.big_image_cache:
                self.big_image_cache.clear()
        except Exception:
            pass
        try:
            self.current_original_pixmap = None
        except Exception:
            pass
        try:
            if hasattr(self, "_thumb_by_path") and isinstance(self._thumb_by_path, dict):
                for thumb in list(self._thumb_by_path.values()):
                    try:
                        thumb.clear_image_data()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self._requested_paths = set()
        except Exception:
            pass
        try:
            self._needs_visible_reload = True
        except Exception:
            pass

    def showEvent(self, event):
        """页面显示时触发可见缩略图加载
        
        说明：
            - 当页面在后台被“超时释放缓存”后，缩略图控件还在，但图片数据已被清空
            - 如果不主动触发一次可见区域加载，往往要等用户滚动/点击才会触发刷新
        """
        super().showEvent(event)
        try:
            if not bool(getattr(self, "_needs_visible_reload", False)):
                return
        except Exception:
            return
        try:
            self._needs_visible_reload = False
        except Exception:
            pass
        try:
            QTimer.singleShot(0, lambda: self._schedule_visible_load(immediate=True))
        except Exception:
            pass

    def update_thumbnail_ui_perf_config(self):
        # 功能已移除
        pass

    def _update_spray_exit_shortcut(self):
        if not self._spray_exit_shortcut:
            return
        sm = ShortcutManager.instance()
        seq = sm.get_sequence("General.Close")
        if isinstance(seq, str):
            if "Wheel" in seq:
                self._spray_exit_shortcut.setKey(QKeySequence("Esc"))
            else:
                self._spray_exit_shortcut.setKey(QKeySequence(seq))
        else:
            self._spray_exit_shortcut.setKey(seq)

    def _on_spray_exit_shortcut(self):
        if hasattr(self, "grid_view") and self.grid_view and getattr(self.grid_view, "spray_mode_active", False):
            self.on_spray_cancel_requested()

    def _update_select_all_shortcut(self):
        if not self._select_all_shortcut:
            return
        sm = ShortcutManager.instance()
        seq = sm.get_sequence("ImageLibrary.SelectAll")
        if isinstance(seq, str):
            self._select_all_shortcut.setKey(QKeySequence("Ctrl+A"))
        else:
            self._select_all_shortcut.setKey(seq)

    def _on_select_all_shortcut(self):
        if not hasattr(self, "grid_view") or not self.grid_view:
            return
        if getattr(self.grid_view, "spray_mode_active", False):
            return
        try:
            focus_widget = QApplication.focusWidget()
            if focus_widget is not None:
                from PyQt6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
                if isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                    return
        except Exception:
            pass
        self._select_all_active = True
        self.grid_view.select_all_thumbnails()

    def _update_open_detail_shortcut(self):
        if not self._open_detail_shortcut:
            return
        sm = ShortcutManager.instance()
        try:
            seq = sm.get_sequence("ThumbnailGrid.OpenDetail")
        except Exception:
            return
        if isinstance(seq, str):
            return
        try:
            self._open_detail_shortcut.setKey(seq)
        except Exception:
            pass

    def _init_folder_nav_shortcuts(self):
        if hasattr(self, "_folder_nav_shortcuts_by_id") and isinstance(self._folder_nav_shortcuts_by_id, dict) and self._folder_nav_shortcuts_by_id:
            return
        self._folder_nav_shortcuts_by_id = {}
        panel = getattr(self, "folder_panel", None)
        if panel is None:
            return
        try:
            shortcut_parent = getattr(panel, "folder_tree", None) or panel
        except Exception:
            shortcut_parent = panel
        mapping = {
            "FolderNav.PrevFolder": (lambda: panel.select_prev_visible_folder() if hasattr(panel, "select_prev_visible_folder") else None),
            "FolderNav.NextFolder": (lambda: panel.select_next_visible_folder() if hasattr(panel, "select_next_visible_folder") else None),
            "FolderNav.PrevSiblingFolder": (lambda: panel.select_prev_sibling_folder() if hasattr(panel, "select_prev_sibling_folder") else None),
            "FolderNav.NextSiblingFolder": (lambda: panel.select_next_sibling_folder() if hasattr(panel, "select_next_sibling_folder") else None),
            "FolderNav.ParentFolder": (lambda: panel.select_prev_upper_folder() if hasattr(panel, "select_prev_upper_folder") else None),
            "FolderNav.ParentFolder2": (lambda: panel.select_next_upper_folder() if hasattr(panel, "select_next_upper_folder") else None),
        }
        for sid, fn in mapping.items():
            try:
                sc = QShortcut(shortcut_parent)
                sc.setContext(Qt.ShortcutContext.WidgetShortcut)
                sc.activated.connect(fn)
                self._folder_nav_shortcuts_by_id[str(sid)] = sc
            except Exception:
                continue

    def _update_folder_nav_shortcuts(self):
        mp = getattr(self, "_folder_nav_shortcuts_by_id", None)
        if not isinstance(mp, dict) or not mp:
            return
        sm = ShortcutManager.instance()
        for sid, sc in mp.items():
            if sc is None:
                continue
            try:
                seq = sm.get_sequence(str(sid))
            except Exception:
                continue
            if isinstance(seq, str):
                continue
            try:
                sc.setKey(seq)
            except Exception:
                pass

    def _init_focus_transfer_shortcuts(self):
        if hasattr(self, "_focus_transfer_shortcuts_by_id") and isinstance(getattr(self, "_focus_transfer_shortcuts_by_id", None), dict) and self._focus_transfer_shortcuts_by_id:
            return
        self._focus_transfer_shortcuts_by_id = {}
        panel = getattr(self, "folder_panel", None)
        tree = getattr(panel, "folder_tree", None) if panel is not None else None
        gv = getattr(self, "grid_view", None)
        if tree is not None:
            try:
                sc = QShortcut(tree)
                sc.setContext(Qt.ShortcutContext.WidgetShortcut)
                sc.activated.connect(self._focus_grid_first_visible)
                self._focus_transfer_shortcuts_by_id["FolderTree.FocusToGrid"] = sc
            except Exception:
                pass
        if gv is not None:
            try:
                sc = QShortcut(gv)
                sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                sc.activated.connect(self._focus_tree_current)
                self._focus_transfer_shortcuts_by_id["ThumbnailGrid.FocusToTree"] = sc
            except Exception:
                pass
        try:
            self._update_focus_transfer_shortcuts()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_focus_transfer_shortcuts)
        except Exception:
            pass

    def _update_focus_transfer_shortcuts(self):
        mp = getattr(self, "_focus_transfer_shortcuts_by_id", None)
        if not isinstance(mp, dict) or not mp:
            return
        sm = ShortcutManager.instance()
        for sid, sc in mp.items():
            if sc is None:
                continue
            try:
                seq = sm.get_sequence(str(sid))
            except Exception:
                continue
            if isinstance(seq, str):
                continue
            try:
                sc.setKey(seq)
            except Exception:
                pass

    def _focus_grid_first_visible(self):
        gv = getattr(self, "grid_view", None)
        if gv is None:
            return
        idx = 0
        try:
            if getattr(gv, "is_virtualized", False) and getattr(gv, "list_view", None) is not None:
                from PyQt6.QtCore import QPoint
                mi = gv.list_view.indexAt(QPoint(1, 1))
                if mi is not None and mi.isValid():
                    idx = int(mi.row())
            else:
                start, _, _ = gv.get_visible_index_range(extra_rows=0)
                idx = int(start)
        except Exception:
            idx = 0
        try:
            gv.select_thumbnail(int(idx), scroll_to=True)
        except Exception:
            pass
        try:
            if getattr(gv, "is_virtualized", False) and getattr(gv, "list_view", None) is not None:
                gv.list_view.setFocus(Qt.FocusReason.ShortcutFocusReason)
            elif getattr(gv, "scroll_area", None) is not None:
                gv.scroll_area.setFocus(Qt.FocusReason.ShortcutFocusReason)
            else:
                gv.setFocus(Qt.FocusReason.ShortcutFocusReason)
        except Exception:
            pass
        try:
            self._schedule_visible_load(immediate=True)
        except Exception:
            pass
        try:
            QTimer.singleShot(0, lambda i=int(idx): self.on_thumbnail_clicked_proxy(int(i), Qt.KeyboardModifier.NoModifier))
        except Exception:
            try:
                self.on_thumbnail_clicked_proxy(int(idx), Qt.KeyboardModifier.NoModifier)
            except Exception:
                pass

    def _init_thumbnail_edit_shortcuts(self):
        if hasattr(self, "_thumb_edit_shortcuts_by_id") and isinstance(getattr(self, "_thumb_edit_shortcuts_by_id", None), dict) and self._thumb_edit_shortcuts_by_id:
            return
        self._thumb_edit_shortcuts_by_id = {}
        gv = getattr(self, "grid_view", None)
        if gv is None:
            return
        try:
            target = getattr(gv, "list_view", None) or getattr(gv, "scroll_area", None) or gv
        except Exception:
            target = gv

        mapping = {}
        try:
            mapping["ImageDetail.ToggleFavorite"] = lambda: self._thumb_edit_toggle_favorite()
            mapping["ImageDetailRight.ToggleFavorite"] = lambda: self._thumb_edit_toggle_favorite()
            for r in (1, 2, 3, 4, 5):
                mapping[f"ImageDetail.SetRating{r}"] = (lambda val=int(r): self._thumb_edit_set_rating(int(val)))
                mapping[f"ImageDetailRight.SetRating{r}"] = (lambda val=int(r): self._thumb_edit_set_rating(int(val)))
            label_map = {0: "", 1: "Red", 2: "Orange", 3: "Yellow", 4: "Green", 5: "Cyan", 6: "Blue", 7: "Purple", 8: "Pink", 9: "White"}
            for d, lab in label_map.items():
                mapping[f"ImageDetail.SetLabel{int(d)}"] = (lambda v=str(lab): self._thumb_edit_set_label(str(v)))
                mapping[f"ImageDetailRight.SetLabel{int(d)}"] = (lambda v=str(lab): self._thumb_edit_set_label(str(v)))
        except Exception:
            mapping = {}
        for sid, fn in (mapping or {}).items():
            try:
                sc = QShortcut(target)
                sc.setContext(Qt.ShortcutContext.WidgetShortcut)
                sc.activated.connect(fn)
                self._thumb_edit_shortcuts_by_id[str(sid)] = sc
            except Exception:
                continue

    def _update_thumbnail_edit_shortcuts(self):
        mp = getattr(self, "_thumb_edit_shortcuts_by_id", None)
        if not isinstance(mp, dict) or not mp:
            return
        sm = ShortcutManager.instance()
        for sid, sc in mp.items():
            if sc is None:
                continue
            try:
                seq = sm.get_sequence(str(sid))
            except Exception:
                continue
            if isinstance(seq, str):
                continue
            try:
                sc.setKey(seq)
            except Exception:
                pass

    def _thumb_edit_get_first_info(self):
        selected_files = []
        try:
            selected_files = self.get_selected_files() or []
        except Exception:
            selected_files = []
        if selected_files:
            return selected_files[0]
        p = getattr(self, "current_preview_path", None)
        if not p:
            try:
                p = getattr(self.preview_panel, "current_image_path", None)
            except Exception:
                p = None
        if not p:
            return None
        key0 = self._normalize_path_key(p)
        for pool in (getattr(self, "image_files", None), getattr(self, "raw_image_files", None), getattr(self, "all_image_files", None)):
            try:
                for it in (pool or []):
                    if isinstance(it, dict) and self._normalize_path_key(it.get("path")) == key0:
                        return it
            except Exception:
                continue
        return {"path": p}

    def _thumb_edit_toggle_favorite(self):
        info0 = self._thumb_edit_get_first_info()
        if not isinstance(info0, dict):
            return
        p = info0.get("path")
        if not p:
            return
        cur = 0
        try:
            cur = int(info0.get("favorite") or info0.get("is_favorite") or 0)
        except Exception:
            cur = 0
        self.toggle_favorite_selection(bool(int(cur) != 1))

    def _thumb_edit_set_rating(self, rating: int):
        info0 = self._thumb_edit_get_first_info()
        if not isinstance(info0, dict):
            return
        p = info0.get("path")
        if not p:
            return
        cur = 0
        try:
            cur = int(info0.get("rating") or 0)
        except Exception:
            cur = 0
        new_rating = 0 if int(cur) == int(rating) else int(rating)
        self.set_rating_selection(int(new_rating))

    def _thumb_edit_set_label(self, label: str):
        info0 = self._thumb_edit_get_first_info()
        if not isinstance(info0, dict):
            return
        p = info0.get("path")
        if not p:
            return
        cur = ""
        try:
            cur = str(info0.get("label") or "")
        except Exception:
            cur = ""
        new_label = "" if (label and str(cur) == str(label)) else str(label or "")
        self.set_label_selection(str(new_label))

    def _focus_tree_current(self):
        panel = getattr(self, "folder_panel", None)
        tree = getattr(panel, "folder_tree", None) if panel is not None else None
        if tree is None:
            return
        try:
            gv = getattr(self, "grid_view", None)
            if gv is not None and hasattr(gv, "clear_selection"):
                gv.clear_selection()
        except Exception:
            pass
        try:
            cur = tree.currentItem()
            if cur is not None:
                tree.setCurrentItem(cur)
                tree.scrollToItem(cur)
        except Exception:
            pass
        try:
            tree.setFocus()
        except Exception:
            pass

    def _on_open_detail_shortcut(self):
        try:
            if hasattr(self, "detail_panel") and self.detail_panel:
                return
        except Exception:
            pass
        try:
            from PyQt6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
            focus_widget = QApplication.focusWidget()
            if focus_widget is not None and isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                return
        except Exception:
            pass
        idx = -1
        try:
            selected_indices = self.get_selected_indices()
            if selected_indices:
                idx = int(selected_indices[0])
        except Exception:
            idx = -1
        if idx < 0:
            try:
                idx = int(getattr(self.grid_view, "last_selected_index", -1))
            except Exception:
                idx = -1
        if idx < 0:
            idx = 0
        if idx < 0 or idx >= len(self.image_files):
            return
        self.show_detail_panel(int(idx))

    def _normalize_path_key(self, path):
        if not path:
            return path
        try:
            return os.path.normcase(os.path.normpath(str(path).replace("/", os.sep)))
        except Exception:
            return path

    def _normalize_path_str(self, path):
        if not path:
            return path
        try:
            return os.path.normcase(os.path.normpath(str(path).replace("/", os.sep)))
        except Exception:
            try:
                return os.path.normcase(str(path).replace("/", os.sep))
            except Exception:
                return path

    def _show_startup_mask(self, text=None):
        if not self._startup_mask_enabled:
            return
        if text:
            self._startup_mask_label.setText(text)
        if hasattr(self, "_grid_container_style_default") and self._grid_container_style_default is not None:
            cm = ColorManager.instance()
            grid_bg = cm.get("theme.background")
            self.grid_container.setStyleSheet(f"""
                QWidget {{
                    background-color: {grid_bg};
                    border-top: none;
                }}
            """)
        self._startup_mask.setGeometry(self.grid_container.rect())
        self._startup_mask.raise_()
        self._startup_mask.show()
        self._startup_mask_visible = True
        self._startup_mask_timeout_timer.stop()
        if not getattr(self, "_startup_blocking_show", False):
            self._startup_mask_timeout_timer.start(2000)

    def _force_hide_startup_mask(self):
        if not self._startup_mask_enabled:
            return
        if not self._startup_mask_visible:
            return
        self._startup_mask.hide()
        self._startup_mask_visible = False
        self._startup_mask_enabled = False
        self._startup_mask_ready = True
        self._startup_mask_timeout_timer.stop()
        if hasattr(self, "_grid_container_style_default") and self._grid_container_style_default is not None:
            self.grid_container.setStyleSheet(self._grid_container_style_default)

    def _maybe_hide_startup_mask(self):
        if not self._startup_mask_enabled:
            return
        if not self._startup_mask_visible:
            return
        if self.current_loaded_count <= 0:
            return
        if self._startup_pending_paths:
            return
        def _hide():
            if not self._startup_mask_enabled or not self._startup_mask_visible:
                return
            if self._startup_pending_paths:
                return
            self._startup_mask.hide()
            self._startup_mask_visible = False
            self._startup_mask_enabled = False
            self._startup_mask_ready = True
            self._startup_mask_timeout_timer.stop()
            if hasattr(self, "_grid_container_style_default") and self._grid_container_style_default is not None:
                self.grid_container.setStyleSheet(self._grid_container_style_default)
        QTimer.singleShot(60, _hide)

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        page_bg = cm.get("theme.background.primary")
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {page_bg};
            }}
        """)
        grid_bg = cm.get("theme.background.primary")
        grid_border = cm.get("popup.border.primary")
        primary = cm.get("theme.primary")
        self._grid_container_style_default = f"""
            QWidget {{
                background-color: {grid_bg};
                border-top: 1px solid {grid_border};
            }}
        """
        if hasattr(self, "grid_container") and not getattr(self, "_startup_mask_visible", False):
            self.grid_container.setStyleSheet(self._grid_container_style_default)
        if hasattr(self, "_startup_mask"):
            startup_mask_bg = cm.to_qss_color("image_library.startup_mask.background")
            self._startup_mask.setStyleSheet(f"""
                QFrame {{
                    background-color: {startup_mask_bg};
                    border: none;
                }}
            """)
        if hasattr(self, "_startup_mask_label"):
            text_color = cm.get("theme.text.dark")
            self._startup_mask_label.setStyleSheet(f"""
                QLabel {{
                    color: {text_color};
                    font-size: 14px;
                    background: transparent;
                    border: none;
                    margin: 0px;
                    padding: 0px;
                }}
            """)
        if hasattr(self, "preview_info_splitter") and self.preview_info_splitter is not None:
            splitter_bg = cm.get("popup.border.primary")
            self.preview_info_splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: {splitter_bg};
                    height: 1px;
                }}
                QSplitter::handle:hover {{
                    background-color: {primary};
                }}
            """)
        if hasattr(self, "content_splitter") and self.content_splitter is not None:
            splitter_bg = cm.get("popup.border.primary")
            collapsed = False
            try:
                collapsed = bool(self.content_splitter.property("preview_collapsed"))
            except Exception:
                collapsed = False
            if collapsed:
                splitter_bg = "transparent"
            self.content_splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: {splitter_bg};
                    width: 2px;
                }}
                QSplitter::handle:hover {{
                    background-color: {primary};
                }}
            """)
        try:
            text_dark = cm.get("theme.text.dark")
            hover_bg = cm.get("theme.background.dark")
            tooltip_bg = cm.get("theme.text.light")
            tooltip_text = cm.get("tooltip.text")
            tooltip_border = cm.get("tooltip.border")
            btn_style = f"""
                QPushButton {{ background: transparent; border: none; border-radius: 4px; padding: 4px; }}
                QPushButton:hover {{ background-color: {hover_bg}; }}
                QPushButton:pressed {{ background-color: {hover_bg}; }}
                QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
            """
            for btn in [getattr(self, "toolbar_geo_btn", None), getattr(self, "toolbar_track_match_btn", None)]:
                if btn is None:
                    continue
                try:
                    btn.setStyleSheet(btn_style)
                except Exception:
                    pass
            try:
                if getattr(self, "toolbar_geo_btn", None) is not None:
                    self.toolbar_geo_btn.setIcon(qta.icon("mdi6.map-marker-outline", color=text_dark))
            except Exception:
                pass
            try:
                if getattr(self, "toolbar_track_match_btn", None) is not None:
                    self.toolbar_track_match_btn.setIcon(qta.icon("mdi6.transit-connection-variant", color=text_dark))
            except Exception:
                pass
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_startup_mask") and self._startup_mask_visible:
            self._startup_mask.setGeometry(self.grid_container.rect())

    def _init_special_caches(self):
        """异步初始化物种和收藏缓存 (延迟200ms启动)"""
        QTimer.singleShot(200, self._start_preload_task)

    def _start_preload_task(self):
        def run():
            try:
                # 获取收藏图片 (前500) - 优先级最高
                fav_images = self.db.get_top_favorite_images(500)
                try:
                    LogManager.instance().debug(f"[Cache] Found {len(fav_images) if fav_images else 0} favorite images for preload.")
                except Exception:
                    pass
                if fav_images:
                    self.cache_manager.preload(fav_images, 'fav')
                
                # 获取物种图片 (前500) - 优先级次之
                species_images = self.db.get_top_species_images(500)
                try:
                    LogManager.instance().debug(f"[Cache] Found {len(species_images) if species_images else 0} species images for preload.")
                except Exception:
                    pass
                if species_images:
                    self.cache_manager.preload(species_images, 'species')
            except Exception as e:
                try:
                    LogManager.instance().warning(f"初始化特殊缓存失败: {e}")
                except Exception:
                    pass
                
        threading.Thread(target=run, daemon=True).start()

    def init_ui(self):
        # 初始化显示模式（对应 view_combo 的索引：0=仅缩略图, 1=缩略图+文件名, 2=缩略图+详情）
        self.display_mode = 1  # 默认显示文件名
        self._apply_theme_styles()

        # 左侧：文件夹区域
        self.folder_panel = FolderPanel(self.db, self.settings_manager, context="library")
        # Restore standard toolbar buttons for library page
        self.folder_panel.add_search_button()
        self.folder_panel.add_sort_button()
        
        self.folder_panel.folderSelected.connect(self.on_folder_selected)
        self.folder_panel.folderClicked.connect(self.on_folder_clicked)
        self.folder_panel.folderRenamed.connect(self.on_folder_renamed_from_panel)
        try:
            self.folder_panel.folderDeletedOnDisk.connect(self.on_folder_deleted_from_panel)
        except Exception:
            pass
        self.folder_panel.toggleRequested.connect(self.on_folder_panel_toggled)
        self.folder_tree_visible = True

        self.set_left_panel(self.folder_panel)

        # ========== 工具栏 ==========
        self.toolbar = ToolbarView(self, self.settings_manager, config={"show_stash": False, "show_new_folder": False, "compact_quick_filter_spacing": True})
        self.toolbar.newFolderRequested.connect(self.on_new_folder_clicked)
        self.toolbar.renameRequested.connect(self.on_rename_clicked)
        self.toolbar.deleteRequested.connect(self.on_delete_clicked)
        self.toolbar.favToggled.connect(self.on_fav_toggled)
        self.toolbar.ratingOperatorChanged.connect(self.on_rating_operator_changed)
        self.toolbar.ratingChanged.connect(self.on_toolbar_rating_changed)
        self.toolbar.advancedSearchRequested.connect(self.on_advanced_search)
        self.toolbar.saveFilterRequested.connect(self.on_save_filter)
        self.toolbar.loadFilterRequested.connect(self.on_load_filter)
        self.toolbar.viewModeChanged.connect(self.on_view_mode_changed)
        self.toolbar.sortModeChanged.connect(self.on_sort_changed)
        self.toolbar.thumbnailSizeChanged.connect(self.on_thumbnail_size_changed)
        self.toolbar.compareRequested.connect(self.on_compare_clicked)
        self.toolbar.sprayModeChanged.connect(self.on_spray_mode_changed)
        if hasattr(self.toolbar, "preview_slider"):
            self.toolbar.preview_slider.sliderPressed.connect(self._on_thumbnail_slider_pressed)
            self.toolbar.preview_slider.sliderReleased.connect(self._on_thumbnail_slider_released)
        try:
            icon_color = ColorManager.instance().get("theme.text.dark")
        except Exception:
            icon_color = "#555"
        try:
            self.toolbar_geo_btn = QPushButton()
            self.toolbar_geo_btn.setIcon(qta.icon("mdi6.map-marker-outline", color=icon_color))
            self.toolbar_geo_btn.setIconSize(QSize(22, 22))
            self.toolbar_geo_btn.setFixedSize(32, 32)
            self.toolbar_geo_btn.setToolTip("设置地理位置")
            self.toolbar_geo_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.toolbar_geo_btn.clicked.connect(self.show_geolocation_dialog)
            self.toolbar.add_widget(self.toolbar_geo_btn)
        except Exception:
            self.toolbar_geo_btn = None
        try:
            self.toolbar_track_match_btn = QPushButton()
            self.toolbar_track_match_btn.setIcon(qta.icon("mdi6.transit-connection-variant", color=icon_color))
            self.toolbar_track_match_btn.setIconSize(QSize(22, 22))
            self.toolbar_track_match_btn.setFixedSize(32, 32)
            self.toolbar_track_match_btn.setToolTip("轨迹匹配")
            self.toolbar_track_match_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.toolbar_track_match_btn.clicked.connect(self.show_track_match_dialog)
            self.toolbar.add_widget(self.toolbar_track_match_btn)
        except Exception:
            self.toolbar_track_match_btn = None

        self.set_toolbar(self.toolbar)
        
        # 将筛选面板重新定位为 ImageLibraryPage 的子组件，以便实现悬浮效果
        if hasattr(self.toolbar, 'filter_panel') and self.toolbar.filter_panel:
             self.toolbar.filter_panel.setParent(self)
             self.toolbar.filter_panel.hide()
             # self.filter_panel is a property, no need to set it
             if hasattr(self.toolbar, 'filter_btn'):
                 self._filter_btn = self.toolbar.filter_btn

        # Connect signals for event filter state
        if hasattr(self.toolbar, 'filter_btn'):
            self.toolbar.filter_btn.toggled.connect(self._update_event_filter_state)
        if hasattr(self.folder_panel, 'search_btn'):
            self.folder_panel.search_btn.toggled.connect(self._update_event_filter_state)
            
        # Ensure initial check
        self._update_event_filter_state()

        # ========== 缩略图网格 ==========
        self.grid_view = VirtualThumbnailGridView(self)
        self.grid_view.itemClicked.connect(self.on_thumbnail_clicked_proxy)
        self.grid_view.itemDoubleClicked.connect(self.on_thumbnail_double_clicked)
        self.grid_view.contextMenuRequested.connect(self.on_thumbnail_context_menu_proxy)
        self.grid_view.backgroundContextMenuRequested.connect(self.on_background_context_menu)
        self.grid_view.selectionChanged.connect(self.on_selection_changed)
        self.grid_view.zoomRequested.connect(self.on_wheel_zoom)
        self.grid_view.scrollValueChanged.connect(self.on_scroll_value_changed)
        self.grid_view.blankClicked.connect(self.clear_preview)
        self.grid_view.sprayActionRequested.connect(self.on_spray_action_requested)
        self.grid_view.sprayCancelRequested.connect(self.on_spray_cancel_requested)
        
        self.set_grid(self.grid_view)
        self.grid_view.set_settings_manager(self.settings_manager)
        try:
            self.grid_view.show_focus_overlays = False
        except Exception:
            pass
        self.grid_view.installEventFilter(self)
        self.grid_view.scroll_area.viewport().installEventFilter(self)
        # 缩略图滚动性能控制器已移除
        self._thumb_ui_controller = None

        if self._spray_exit_shortcut is None:
            self._spray_exit_shortcut = QShortcut(self)
            self._spray_exit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._spray_exit_shortcut.activated.connect(self._on_spray_exit_shortcut)
            self._spray_exit_shortcut.setEnabled(False)
            self._update_spray_exit_shortcut()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_spray_exit_shortcut)

        if self._select_all_shortcut is None:
            self._select_all_shortcut = QShortcut(self)
            self._select_all_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._select_all_shortcut.activated.connect(self._on_select_all_shortcut)
            self._update_select_all_shortcut()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_select_all_shortcut)

        if self._open_detail_shortcut is None:
            self._open_detail_shortcut = QShortcut(self)
            self._open_detail_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self._open_detail_shortcut.activated.connect(self._on_open_detail_shortcut)
            self._update_open_detail_shortcut()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_open_detail_shortcut)

        try:
            self._init_folder_nav_shortcuts()
            self._update_folder_nav_shortcuts()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_folder_nav_shortcuts)
        except Exception:
            pass
        try:
            self._init_focus_transfer_shortcuts()
        except Exception:
            pass
        try:
            self._init_thumbnail_edit_shortcuts()
            self._update_thumbnail_edit_shortcuts()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_thumbnail_edit_shortcuts)
        except Exception:
            pass

        try:
            spray_range_size = int(self.settings_manager.get("library/spray_range_size", 1))
        except Exception:
            spray_range_size = 1
        if spray_range_size < 1:
            spray_range_size = 1
        self.grid_view.set_spray_range_size(spray_range_size)
        self.settings_manager.set("library/spray_range_size", spray_range_size)
        # Apply style to grid container to match original look
        self._grid_container_style_default = ""
        self.grid_container.setStyleSheet(self._grid_container_style_default)

        self._startup_mask = QFrame(self.grid_container)
        self._startup_mask.setFrameShape(QFrame.Shape.NoFrame)
        cm = ColorManager.instance()
        startup_mask_bg = cm.to_qss_color("image_library.startup_mask.background")
        self._startup_mask.setStyleSheet(f"""
            QFrame {{
                background-color: {startup_mask_bg};
                border: none;
            }}
        """)
        self._startup_mask_label = QLabel("正在初始化...", self._startup_mask)
        self._startup_mask_label.setStyleSheet("")
        mask_layout = QVBoxLayout(self._startup_mask)
        mask_layout.setContentsMargins(0, 0, 0, 0)
        mask_layout.addStretch()
        mask_layout.addWidget(self._startup_mask_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        mask_layout.addStretch()
        self._startup_mask.hide()
        self._startup_mask.setGeometry(self.grid_container.rect())
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()
        
        # 初始排列缩略图（使用默认列数）
        self.grid_view.arrange_thumbnails()
        
        # 右侧：图片预览窗口
        self.preview_panel = PreviewPanel(self.settings_manager, cache_context="library")
        self.preview_panel.visibility_changed.connect(self.on_preview_visibility_changed)
        self.preview_panel.fav_toggled.connect(self.on_preview_fav_toggled)
        self.preview_panel.rating_changed.connect(self.on_preview_rating_changed)
        self.preview_panel.label_changed.connect(self.on_preview_label_changed)
        self.info_panel = InfoPanel()
        self.preview_info_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_info_splitter.setHandleWidth(1)
        self.preview_info_splitter.setChildrenCollapsible(True)
        self.preview_info_splitter.addWidget(self.preview_panel)
        self.preview_info_splitter.addWidget(self.info_panel)
        try:
            self.preview_info_splitter.setSizes([420, 220])
        except Exception:
            pass

        self.preview_info_container = QWidget()
        preview_info_layout = QVBoxLayout(self.preview_info_container)
        preview_info_layout.setContentsMargins(0, 0, 0, 0)
        preview_info_layout.setSpacing(0)
        preview_info_layout.addWidget(self.preview_info_splitter, 1)

        self._preview_info_last_sizes = None
        self._preview_collapsed_vert = False
        self._info_collapsed_vert = False

        def _toggle_preview_up():
            try:
                sizes = list(self.preview_info_splitter.sizes())
            except Exception:
                sizes = []
            if not sizes or len(sizes) < 2:
                return
            if not bool(getattr(self, "_preview_collapsed_vert", False)):
                if not bool(getattr(self, "_info_collapsed_vert", False)):
                    self._preview_info_last_sizes = sizes
                self._preview_collapsed_vert = True
                self._info_collapsed_vert = False
                try:
                    self.preview_panel.set_vertical_collapsed(True)
                except Exception:
                    pass
                try:
                    self.info_panel.set_vertical_collapsed(False)
                except Exception:
                    pass
                total = max(1, int(sizes[0] + sizes[1]))
                self.preview_info_splitter.setSizes([34, max(1, total - 34)])
            else:
                self._preview_collapsed_vert = False
                try:
                    self.preview_panel.set_vertical_collapsed(False)
                except Exception:
                    pass
                restore = list(getattr(self, "_preview_info_last_sizes", None) or [])
                if len(restore) == 2:
                    self.preview_info_splitter.setSizes(restore)
                else:
                    self.preview_info_splitter.setSizes([420, 220])

        def _toggle_info_down():
            try:
                sizes = list(self.preview_info_splitter.sizes())
            except Exception:
                sizes = []
            if not sizes or len(sizes) < 2:
                return
            if not bool(getattr(self, "_info_collapsed_vert", False)):
                if not bool(getattr(self, "_preview_collapsed_vert", False)):
                    self._preview_info_last_sizes = sizes
                self._info_collapsed_vert = True
                self._preview_collapsed_vert = False
                try:
                    self.info_panel.set_vertical_collapsed(True)
                except Exception:
                    pass
                try:
                    self.preview_panel.set_vertical_collapsed(False)
                except Exception:
                    pass
                total = max(1, int(sizes[0] + sizes[1]))
                self.preview_info_splitter.setSizes([max(1, total - 34), 34])
            else:
                self._info_collapsed_vert = False
                try:
                    self.info_panel.set_vertical_collapsed(False)
                except Exception:
                    pass
                restore = list(getattr(self, "_preview_info_last_sizes", None) or [])
                if len(restore) == 2:
                    self.preview_info_splitter.setSizes(restore)
                else:
                    self.preview_info_splitter.setSizes([420, 220])

        try:
            self.preview_panel.vertical_toggle_requested.connect(_toggle_preview_up)
        except Exception:
            pass
        try:
            self.info_panel.vertical_toggle_requested.connect(_toggle_info_down)
        except Exception:
            pass

        self.content_splitter.addWidget(self.preview_info_container)
        try:
            self.preview_panel.setMinimumWidth(0)
        except Exception:
            pass
        try:
            # 给预览区设置最小宽度，防止拖动左侧时被挤压消失
            self.preview_info_container.setMinimumWidth(30)
            try:
                max_w = int(self.preview_panel.maximumWidth() or 800)
            except Exception:
                max_w = 800
            if max_w > 0:
                self.preview_info_container.setMaximumWidth(int(max_w))
            # 恢复默认 SizePolicy，避免被 Splitter 忽略尺寸限制
            self.preview_info_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        except Exception:
            pass
            
        try:
            if hasattr(self, "right_content_container"):
                self.right_content_container.setMinimumWidth(0)
        except Exception:
            pass

        # 设置初始比例：文件夹 1，图片 3，预览 1
        self.content_splitter.setSizes([200, 600, 280])
        try:
            self.content_splitter.setStretchFactor(0, 0)
            self.content_splitter.setStretchFactor(1, 10)
            self.content_splitter.setStretchFactor(2, 0)
        except Exception:
            pass
        self.content_splitter.splitterMoved.connect(self.on_splitter_moved)
        self.center_stack = QWidget()
        self.center_stack_layout = QVBoxLayout(self.center_stack)
        self.center_stack_layout.setContentsMargins(0, 0, 0, 0)
        self.center_stack_layout.setSpacing(0)
        self.center_stack_layout.addWidget(self.content_splitter)
        self.main_layout.addWidget(self.center_stack, 1)

        # ========== 下方状态栏 ==========
        # Status bar removed - using MainWindow global status bar
        # 使用 QTimer 延迟初始化缩略图大小，确保 UI 完全加载
        QTimer.singleShot(100, self._init_thumbnail_size)
        # 延迟加载设置（包括上次选中的文件夹）
        QTimer.singleShot(300, self.load_settings)

    @property
    def filter_btn(self):
        return self.toolbar.filter_btn

    @property
    def folder_search_btn(self):
        return self.folder_panel.search_btn

    @property
    def scroll_area(self):
        return self.grid_view.scroll_area

    @property
    def preview_slider(self):
        return self.toolbar.preview_slider

    @property
    def filter_panel(self):
        return self.toolbar.filter_panel

    @property
    def current_thumb_size(self):
        return self.grid_view.current_thumb_size
        
    @current_thumb_size.setter
    def current_thumb_size(self, value):
        self.grid_view.current_thumb_size = value

    @property
    def view_combo(self):
        return self.toolbar.view_combo

    @property
    def sort_combo(self):
        return self.toolbar.sort_combo
        
    @property
    def fav_btn(self):
        return self.toolbar.fav_btn
        
    @property
    def star_rating(self):
        return self.toolbar.star_rating
        
    @property
    def rating_filter_btn(self):
        return self.toolbar.rating_filter_btn

    def initialize(self):
        """手动初始化加载（用于延迟加载）"""
        t0 = time.perf_counter()
        if not self._library_cache_loading_started:
            self._library_cache_loading_started = True
            if getattr(self.cache_manager, "persistent_cache_enabled", False):
                threading.Thread(target=self.cache_manager.load_persistent_cache, daemon=True, name="LibraryCacheLoader").start()
        if not self._special_cache_inited:
            self._special_cache_inited = True
            self._init_special_caches()
        self.root_dir = self.settings_manager.get("general/root_path")
        if self.root_dir and os.path.exists(self.root_dir):
            self.folder_panel.populate_tree(self.root_dir)
            
            # 尝试恢复上次浏览的文件夹
            last_folder = self.settings_manager.get("library/last_folder")
            folder_restored = False
            
            if last_folder:
                str_last = str(last_folder)
                if str_last.startswith("virtual://taxonomy"):
                    # 恢复虚拟分类路径
                    try:
                        from urllib.parse import urlparse, parse_qs, unquote
                        parsed = urlparse(str_last)
                        params = parse_qs(parsed.query)
                        
                        order = params.get('order', [None])[0]
                        family = params.get('family', [None])[0]
                        genus = params.get('genus', [None])[0]
                        species = params.get('species', [None])[0]
                        
                        # 特殊处理未分类目录参数
                        file_path = None
                        if "unclassified" in parsed.path:
                             dir_param = params.get('dir', [None])[0]
                             if dir_param:
                                 # locate_taxonomy_node expects a file path to find its dir, 
                                 # or we can modify it? No, let's look at folder_panel.py logic.
                                 # It takes file_path and does os.path.dirname(file_path).
                                 # So we append a dummy file name.
                                 file_path = os.path.join(dir_param, "dummy.jpg")
                        
                        # 调用定位
                        # 如果是根节点 virtual://taxonomy/root，可能没有参数，默认也会选中根？
                        # locate_taxonomy_node 主要是为了选中特定的子节点。
                        # 如果仅仅是 root，select_first_folder 应该够了，或者我们需要专门处理 root
                        
                        if order or family or genus or species or file_path or "unclassified" in parsed.path:
                             self.folder_panel.locate_taxonomy_node(
                                 order, family, genus, species, file_path=file_path, emit_signal=True
                             )
                             # 检查是否真的选中了
                             if self.folder_panel.folder_tree.currentItem():
                                 folder_restored = True
                    except Exception as e:
                        try:
                            LogManager.instance().warning(f"Restore virtual folder failed: {e}")
                        except:
                            pass
                elif os.path.exists(last_folder):
                     # 恢复物理路径
                     folder_restored = self.folder_panel.navigate_to_folder(last_folder)
            
            if not folder_restored:
                self.folder_panel.select_first_folder()
            try:
                if not getattr(self, "current_folder_path", None):
                    self.folder_panel.on_tree_selection_changed()
            except Exception:
                pass
        t1 = time.perf_counter()
        try:
            LogManager.instance().debug(f"[Startup] library.initialize: {t1 - t0:.3f}s")
        except Exception:
            pass
        
        # 启动时预加载前100张图片的缩略图
        self._preload_initial_thumbnails()

    def _preload_initial_thumbnails(self):
        """预加载数据库中前100张图片"""
        def load_task():
            try:
                db = BirdLibraryDB()
                # 按路径排序获取前100个文件
                conn = db._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT file_path FROM bird_results ORDER BY file_path LIMIT 100")
                rows = cursor.fetchall()
                conn.close()
                
                paths = [row['file_path'] for row in rows]
                try:
                    LogManager.instance().debug(f"[Cache] Found {len(paths)} files for initial preload.")
                except Exception:
                    pass
                if paths:
                    self.cache_manager.preload(paths)
                    try:
                        LogManager.instance().debug(f"[Cache] Submitted {len(paths)} files to cache manager.")
                    except Exception:
                        pass
            except Exception as e:
                try:
                    LogManager.instance().warning(f"[Cache] Initial preload failed: {e}")
                except Exception:
                    pass
                pass
                
        # 在后台线程执行查询，避免阻塞 UI
        threading.Thread(target=load_task, daemon=True).start()

    def load_settings(self):
        """加载页面设置"""
        # 0. 恢复缩略图大小 (优先恢复)
        thumb_size = self.settings_manager.get("library/thumbnail_size")
        if thumb_size is not None:
            val = int(thumb_size)
            if hasattr(self, 'preview_slider'):
                self.preview_slider.blockSignals(True)
                self.preview_slider.setValue(val)
                self.preview_slider.blockSignals(False)
                self.on_thumbnail_size_changed(val)

        # 1. 恢复分割器状态
        splitter_state = self.settings_manager.get("library/splitter_state")
        if splitter_state:
            self.content_splitter.restoreState(splitter_state)

        preview_info_state = self.settings_manager.get("library/preview_info_splitter_state")
        if preview_info_state and hasattr(self, "preview_info_splitter"):
            try:
                self.preview_info_splitter.restoreState(preview_info_state)
            except Exception:
                pass

        # 2. 恢复显示模式
        display_mode = self.settings_manager.get("library/display_mode")
        if display_mode is not None:
            self.view_combo.setCurrentIndex(int(display_mode))



        sort_field = self.settings_manager.get("library/sort_field")
        if sort_field:
            self.sort_field_mode = str(sort_field)
            if self.sort_field_mode == "日期":
                self.sort_field_mode = "拍摄时间"
            if hasattr(self, 'sort_combo'):
                idx = self.sort_combo.findText(self.sort_field_mode)
                if idx >= 0:
                    self.sort_combo.setCurrentIndex(idx)
        sort_order = self.settings_manager.get("library/sort_order")
        if sort_order:
            if sort_order in ["asc", "desc"]:
                self.sort_order = sort_order

        # 4. 恢复上次选中的文件夹
        # 移到 initialize 中处理，因为此时可能还没有加载文件夹树
        pass
        
        # 5. 恢复文件夹区域可见性
        folder_visible = self.settings_manager.get("library/folder_visible")
        if folder_visible is not None:
            folder_visible = str(folder_visible).lower() == 'true'
            if folder_visible != self.folder_tree_visible:
                self.folder_panel.set_panel_visible(folder_visible)

        # 6. 恢复预览区域可见性
        preview_visible = self.settings_manager.get("library/preview_visible")
        if preview_visible is not None:
            preview_visible = str(preview_visible).lower() == 'true'
            # PreviewPanel defaults to True
            if preview_visible != self.preview_panel.is_expanded:
                self.preview_panel.set_expanded(preview_visible)

        # 连接信号以便在更改时保存
        self.content_splitter.splitterMoved.connect(lambda: self.settings_manager.set("library/splitter_state", self.content_splitter.saveState()))
        try:
            def _on_preview_info_splitter_moved():
                self.settings_manager.set("library/preview_info_splitter_state", self.preview_info_splitter.saveState())
                # 如果信息面板处于收起状态，确保info_tree保持隐藏
                try:
                    if hasattr(self, "info_panel") and self.info_panel is not None:
                        if getattr(self.info_panel, "_vert_collapsed", False):
                            try:
                                self.info_panel.info_tree.setVisible(False)
                            except Exception:
                                pass
                except Exception:
                    pass
            self.preview_info_splitter.splitterMoved.connect(_on_preview_info_splitter_moved)
        except Exception:
            pass
        self.view_combo.currentIndexChanged.connect(lambda idx: self.settings_manager.set("library/display_mode", idx))
        self.preview_slider.sliderReleased.connect(lambda: self.settings_manager.set("library/thumbnail_size", self.preview_slider.value()))
        self._update_sort_display()
        
        self._settings_loaded = True

    def _get_effective_sort_direction(self):
        if self.sort_order in ("asc", "desc"):
            return self.sort_order
        if self.sort_field_mode in ("拍摄时间", "日期", "评分", "分数"):
            return "desc"
        return "asc"

    def _update_sort_display(self):
        if not hasattr(self, 'sort_combo') or not self.sort_combo:
            return
        if self.sort_field_mode == "日期":
            self.sort_field_mode = "拍摄时间"

        combo = self.sort_combo
        combo.blockSignals(True) # 防止触发信号循环

        # 确保 Editable 关闭
        if combo.isEditable():
            combo.setEditable(False)
            
        # 设置排序方向属性，供 Delegate 使用
        combo.setProperty("sort_order", self.sort_order or "asc")
        
        # 找到当前字段的索引
        target_index = -1
        count = combo.count()
        for i in range(count):
            text = combo.itemText(i)
            # 清理箭头（如果有残留）
            clean_text = text.replace(" ↑", "").replace(" ↓", "")
            if text != clean_text:
                combo.setItemText(i, clean_text)
                
            if clean_text == self.sort_field_mode:
                target_index = i
        
        # 强制选中当前字段（这样顶部的文本框始终显示字段名）
        if target_index >= 0 and combo.currentIndex() != target_index:
            combo.setCurrentIndex(target_index)
            
        # 触发重绘以更新 Delegate 的标记
        combo.update()
        
        combo.blockSignals(False)

    def _init_thumbnail_size(self):
        """延迟初始化缩略图大小，确保正确计算"""
        if hasattr(self, 'preview_slider'):
            self.on_thumbnail_size_changed(self.preview_slider.value())


    def get_available_width(self):
        """获取可用的容器宽度"""
        try:
            if hasattr(self, "grid_view") and self.grid_view is not None and hasattr(self.grid_view, "scroll_area"):
                width = int(self.grid_view.scroll_area.viewport().width() or 0)
                return max(width, 200)
        except Exception:
            pass
        return 800

    def get_available_height(self):
        """获取可用的容器高度"""
        if hasattr(self, 'scroll_area'):
            height = self.scroll_area.viewport().height() - 16  # 减去边距
            return max(height, 200)
        return 600

    def _get_current_thumb_wh(self):
        """获取当前缩略图宽高"""
        size = self.current_thumb_size
        if isinstance(size, (tuple, list)):
            return int(size[0]), int(size[1])
        return int(size), int(size)

    def calculate_thumb_size(self, slider_value):
        """根据滑块值计算缩略图大小
        slider_value: 0-100
        """
        min_w = 96
        min_h = 72
        
        # 宽高比
        ratio = min_h / min_w

        # 线性插值计算宽度
        # 注意：这里的 slider_value 是 0-slider.maximum()，需要归一化
        # 获取真实的 slider maximum
        try:
             slider_max = 200.0
             if hasattr(self, "preview_slider"):
                 slider_max = float(self.preview_slider.maximum() or 200)
             if slider_max <= 0:
                 slider_max = 200.0
        except Exception:
             slider_max = 200.0

        hard_cap = 900
        max_w = max(min_w + 100, int(hard_cap))
        try:
            progress = float(slider_value) / float(slider_max)
        except Exception:
            progress = 0.0
        progress = max(0.0, min(1.0, progress))
        w = int(min_w + (max_w - min_w) * progress)
        w = max(min_w, min(int(max_w), int(w)))
        h = int(w * ratio)
        return (w, h)

    def reload_thumbnails_config(self):
        """重新加载缩略图配置（当设置改变时调用）"""
        try:
            LogManager.instance().debug("[Library] Reloading thumbnail config and refreshing view...")
        except Exception:
            pass
        # 重新计算当前尺寸
        if hasattr(self, 'preview_slider'):
             self.current_thumb_size = self.calculate_thumb_size(self.preview_slider.value())
        
        # 刷新缩略图列表（这将触发重新加载，因为缓存已被清除）
        self.update_thumbnails()
        
        # 触发特殊缓存重建（物种和收藏）
        self.rebuild_special_caches()
        
    def rebuild_special_caches(self):
        """重建特殊缓存（物种和收藏），并触发后台保存"""
        try:
            LogManager.instance().debug("[Library] Rebuilding special caches...")
        except Exception:
            pass
        from utils.sql.data_base import BirdLibraryDB
        db = BirdLibraryDB()
        
        # 1. 获取前200个收藏
        fav_paths = db.get_top_favorite_images(limit=200)
        if fav_paths:
            try:
                LogManager.instance().debug(f"[Library] Preloading {len(fav_paths)} favorite images...")
            except Exception:
                pass
            self.cache_manager.preload(fav_paths, cache_type='fav')
            
        # 2. 获取前200个物种图片
        species_paths = db.get_top_species_images(limit=200)
        if species_paths:
            try:
                LogManager.instance().debug(f"[Library] Preloading {len(species_paths)} species images...")
            except Exception:
                pass
            self.cache_manager.preload(species_paths, cache_type='species')
            
        if fav_paths or species_paths:
            pass

    def on_selection_changed(self, count):
        """处理选择变化（来自 ThumbnailGridView）"""
        if getattr(self, "_select_all_active", False):
            if self.grid_view.get_selected_count() < self.current_loaded_count:
                self._select_all_active = False
                count = self.grid_view.get_selected_count()
            else:
                count = len(self.all_image_files)
        self.stats_changed.emit(len(self.all_image_files), self.current_loaded_count, count)
        if count == 0:
            self.clear_preview()

    def on_thumbnail_clicked_proxy(self, index, modifiers):
        """处理缩略图点击代理（来自 ThumbnailGridView）"""
        # 此时 ThumbnailGridView 已经更新了选中状态
        
        # 预览选中的图片
        # Access thumbnails via grid_view
        thumbnails = getattr(self.grid_view, "thumbnails", []) or []
        info = None
        if index < len(thumbnails):
            thumb = thumbnails[index]
            if thumb.image_info:
                info = thumb.image_info
        
        if not info and 0 <= index < len(self.image_files):
             info = self.image_files[index]
        
        if info:
             try:
                 path = info.get("path") or info.get("file_path") or info.get("filepath")
             except Exception:
                 path = None
             if path:
                 self.preview_image_file(path)
             self._preload_big_neighbors_grid(index)
             try:
                 self._schedule_visible_load(immediate=True)
             except Exception:
                 pass
             try:
                 self._schedule_persist_folder_view_state()
             except Exception:
                 pass
             # Auto-locate in tree
             try:
                # Use standard keys (without _cls suffix) as per Worker data structure
                o = info.get('order') or info.get('order_cls')
                f = info.get('family') or info.get('family_cls')
                g = info.get('genus') or info.get('genus_cls')
                s = info.get('species') or info.get('species_cls')
                path = info.get('path')
                if hasattr(self, 'folder_panel'):
                     self.folder_panel.locate_taxonomy_node(o, f, g, s, path, emit_signal=False)
                     
                     # Check if we are already in taxonomy mode
                     current_folder = getattr(self, "current_folder_path", "")
                     if str(current_folder).startswith("virtual://taxonomy"):
                         # Check if the clicked item's species matches current view
                         # If we are viewing a higher level (e.g. Family), and user clicks a species, 
                         # we might want to narrow down? 
                         # User requirement: "When auto-selected species folder, clicking again should act like manual click -> filter to this species"
                         
                         # Construct the virtual path for this species
                         target_virtual_path = None
                         if s:
                              target_virtual_path = f"virtual://taxonomy?order={o}&family={f}&genus={g}&species={s}"
                         
                         # If we are NOT already viewing this exact species node
                         if target_virtual_path and current_folder != target_virtual_path:
                              # And if the current view actually CONTAINS this species (which it should if we clicked it)
                              # We trigger a load for this specific species
                              # But we must be careful not to trigger this on every click if user just wants to browse
                              # The user said: "When auto-selected ... again click ... like manual click"
                              # But here we are single clicking a thumbnail.
                              # If I single click a thumbnail, I expect to see preview.
                              # The user says "When auto-selected species folder... again click..." 
                              # This implies the tree node is selected.
                              # If I click the thumbnail -> tree node selected (auto-locate).
                              # If the tree node is selected, does the view update? No, we set emit_signal=False.
                              # So the view remains on the parent folder (e.g. Family).
                              # The user wants the view to update to the species folder?
                              # "Like manual click to this folder" -> means load_images_from_taxonomy(species_node)
                              
                              # Let's try to update the view IF we are in a different scope
                              # But wait, if we update view, the grid changes to only show that species.
                              # This might be jarring if I just wanted to preview.
                              # "When auto-selected... again click..."
                              # Maybe the user means: 
                              # 1. I click a photo of "Egret" in "All Birds" view.
                              # 2. Tree jumps to "Egret".
                              # 3. View stays "All Birds".
                              # 4. I click the photo AGAIN? Or I click the tree node?
                              # User said: "当自动选中了物种文件夹时，再次点击要像手动点击到这个文件夹一样"
                              # "再次点击" -> clicking the PHOTO again? or the FOLDER?
                              # If it means clicking the photo again, we can detect if it's already selected.
                              # But `on_thumbnail_clicked_proxy` is called on every click.
                              # If it means clicking the FOLDER node in the tree:
                              # We already have logic for tree click.
                              # But `locate_taxonomy_node` uses `emit_signal=False`, so `on_folder_selected` is NOT called.
                              # This is correct to prevent view refresh on first click.
                              # So the user is likely saying: "I want the view to refresh to that species ONLY".
                              # If I click a photo, tree jumps to species. 
                              # If I want to filter to that species, I should probably double click or something?
                              # Or maybe the user WANTS the view to jump immediately? 
                              # "files tree also jumps... " (previous request) -> done.
                              # "When auto-selected... again click... "
                              # This phrasing "When auto-selected... again click" suggests a two-step or a confirmation.
                              # BUT, if I am browsing a huge list, and I click one, and the view suddenly filters to just 10 images, 
                              # I lost my context of the huge list. That is bad UX usually.
                              # However, if the user explicitly asked for "like manual click", maybe they want that.
                              # Let's re-read: "当自动选中了物种文件夹时，再次点击要像手动点击到这个文件夹一样"
                              # Context: "I click Egret (photo), tree jumps to Egret (folder). (implied: view didn't change)"
                              # "Again click" -> likely means clicking the PHOTO again.
                              # So:
                              # 1. Click photo A (Species S). Tree -> S. View -> Unchanged.
                              # 2. Click photo A (Species S) AGAIN. View -> S.
                              
                              # Let's implement this "Click again to drill down" logic.
                              
                              last_clicked_index = getattr(self, "_last_auto_located_index", -1)
                              if last_clicked_index == index:
                                  # Clicked the same image again
                                  if target_virtual_path:
                                      # Trigger folder selection manually
                                      # IMPORTANT: We need to ensure that the folder panel is in a state where it can select
                                      # Use emit_signal=True to trigger view update
                                      
                                      # Note: locate_taxonomy_node with emit_signal=True will select the node AND emit the signal.
                                      # But if the node is already selected (from the previous auto-locate), 
                                      # QTreeWidget might NOT emit itemSelectionChanged if the selection doesn't actually change.
                                      # So we might need to FORCE the load.
                                      
                                      current_selected_path = None
                                      try:
                                          if hasattr(self.folder_panel, "folder_tree"):
                                              items = self.folder_panel.folder_tree.selectedItems()
                                              if items:
                                                  current_selected_path = items[0].data(0, Qt.ItemDataRole.UserRole)
                                      except Exception:
                                          pass
                                      
                                      # If already selected in tree, we force load
                                      # Normalize paths for comparison
                                      norm_target = self._normalize_path_str(target_virtual_path)
                                      norm_current_tree = self._normalize_path_str(current_selected_path)
                                      
                                      if norm_current_tree == norm_target:
                                          # Tree is already there, force load directly
                                          self.load_images_from_taxonomy(target_virtual_path)
                                          # Also update preview stats
                                          try:
                                              title = s or g or f or o or "分类"
                                              try:
                                                  root_dir = str(self.settings_manager.get("general/root_path", "") or "")
                                              except Exception:
                                                  root_dir = ""
                                              stats = self.db.get_taxonomy_node_stats(
                                                  order_cls=o or None,
                                                  family_cls=f or None,
                                                  genus_cls=g or None,
                                                  species_cls=s or None,
                                                  unclassified=False,
                                                  table_name="bird_results",
                                                  root_path=root_dir,
                                              )
                                              self.preview_panel.show_folder_stats(title, stats)
                                          except:
                                              pass
                                      else:
                                          # Tree not there yet, normal locate with signal
                                          self.folder_panel.locate_taxonomy_node(o, f, g, s, path, emit_signal=True)
                              
                              self._last_auto_located_index = index

             except Exception as e:
                print(f"Auto-locate error: {e}")


    def _get_grid_nav_cols(self) -> int:
        try:
            if getattr(self.grid_view, "is_virtualized", False) and hasattr(self.grid_view, "list_view"):
                viewport_w = int(self.grid_view.list_view.viewport().width())
                cell_w = int(self.grid_view.list_view.gridSize().width())
            else:
                viewport_w = int(self.grid_view.scroll_area.viewport().width())
                size = getattr(self.grid_view, "current_thumb_size", 120)
                if isinstance(size, (tuple, list)) and len(size) >= 1:
                    cell_w = int(size[0])
                else:
                    cell_w = int(size)
        except Exception:
            viewport_w = 800
            cell_w = 120
        cell_w = max(1, int(cell_w))
        return max(1, int(viewport_w // cell_w))

    def _preload_big_neighbors_grid(self, index: int):
        try:
            i = int(index)
        except Exception:
            return
        if i < 0 or i >= len(self.image_files):
            return
        cols = self._get_grid_nav_cols()
        cand = []
        try:
            if (i % cols) != 0:
                cand.append(i - 1)
        except Exception:
            cand.append(i - 1)
        cand.append(i + 1)
        cand.append(i - cols)
        cand.append(i + cols)
        paths = []
        for j in cand:
            try:
                j = int(j)
            except Exception:
                continue
            if j < 0 or j >= len(self.image_files) or j == i:
                continue
            try:
                p = self.image_files[j].get("path")
            except Exception:
                p = None
            if p:
                paths.append(str(p))
        if paths:
            try:
                self.big_image_cache.preload(paths)
            except Exception:
                pass

    def on_thumbnail_double_clicked(self, index):
        """双击缩略图，切换到大图浏览模式"""
        try:
            if 0 <= index < len(self.image_files):
                self.show_detail_panel(index)
        except Exception as e:
            try:
                LogManager.instance().exception("双击进入大图失败", e)
            except Exception:
                pass
            try:
                NotificationManager.instance().show_warning("错误", f"进入大图失败: {e}")
            except Exception:
                pass

    def on_compare_clicked(self):
        """Handle compare button click"""
        selected_indices = self.get_selected_indices()
        if len(selected_indices) != 2:
            NotificationManager.instance().show_toast("请选择两张图片进行对比")
            return
            
        # 直接进入对比模式，以第一张图为索引（实际上 ImageDetailPanel 会处理）
        self.show_detail_panel(selected_indices[0], compare_indices=selected_indices)

    def show_detail_panel(self, index, compare_indices=None):
        try:
            self._detail_last_index = int(index)
        except Exception:
            self._detail_last_index = None
        try:
            self.content_splitter.hide()
        except Exception:
            pass
        try:
            for sc in (getattr(self, "_folder_nav_shortcuts_by_id", {}) or {}).values():
                if sc is not None:
                    sc.setEnabled(False)
        except Exception:
            pass
        try:
            if hasattr(self, "_open_detail_shortcut") and self._open_detail_shortcut is not None:
                self._open_detail_shortcut.setEnabled(False)
        except Exception:
            pass

        try:
            if hasattr(self, 'detail_panel') and self.detail_panel:
                self.detail_panel.setParent(None)
                self.detail_panel.deleteLater()
        except Exception:
            pass

        try:
            parent_stack = getattr(self, "center_stack", None)
            if parent_stack is None:
                parent_stack = self
            self.detail_panel = ImageDetailPanel(
                self.image_files,
                index,
                parent_stack,
                compare_indices=compare_indices,
                cache_manager=self.cache_manager,
                big_cache_context="library",
            )
            if getattr(self, "center_stack_layout", None) is not None:
                self.center_stack_layout.addWidget(self.detail_panel)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开大图模式失败: {e}")
            try:
                self.content_splitter.show()
            except Exception:
                pass
            return

        try:
            self.detail_panel.back_requested.connect(self.hide_detail_panel)
            self.detail_panel.image_changed.connect(self.on_detail_image_changed)
            self.detail_panel.left_image_selected.connect(self.on_detail_left_image_selected)
            self.detail_panel.favorite_changed.connect(self.on_detail_favorite_changed)
            self.detail_panel.rating_changed.connect(self.on_detail_rating_changed)
            self.detail_panel.label_changed.connect(self.on_detail_label_changed)
        except Exception:
            pass

        try:
            if index < len(self.image_files):
                self.info_panel.update_info(self.image_files[index]['path'])
        except Exception:
            pass

    def hide_detail_panel(self):
        """返回图库视图"""
        last_idx = getattr(self, "_detail_last_index", None)
        try:
            if last_idx is not None:
                last_idx = int(last_idx)
        except Exception:
            last_idx = None
        if hasattr(self, 'detail_panel') and self.detail_panel:
            self.detail_panel.hide()
            self.detail_panel.setParent(None)
            self.detail_panel.deleteLater()
            self.detail_panel = None
            
        self.content_splitter.show()
        try:
            if hasattr(self, "_open_detail_shortcut") and self._open_detail_shortcut is not None:
                self._open_detail_shortcut.setEnabled(True)
        except Exception:
            pass
        try:
            for sc in (getattr(self, "_folder_nav_shortcuts_by_id", {}) or {}).values():
                if sc is not None:
                    sc.setEnabled(True)
        except Exception:
            pass
        try:
            if last_idx is not None and 0 <= int(last_idx) < len(self.image_files):
                self.info_panel.update_info(self.image_files[int(last_idx)]['path'])
        except Exception:
            pass
        try:
            if last_idx is not None and hasattr(self, 'grid_view') and self.grid_view:
                self.grid_view.select_thumbnail(int(last_idx), scroll_to=True)
        except Exception:
            pass
        try:
            gv = getattr(self, "grid_view", None)
            if gv is not None:
                if getattr(gv, "is_virtualized", False) and hasattr(gv, "list_view") and gv.list_view:
                    gv.list_view.setFocus()
                elif hasattr(gv, "scroll_area") and gv.scroll_area:
                    gv.scroll_area.setFocus()
                else:
                    gv.setFocus()
        except Exception:
            pass
        try:
            gv = getattr(self, "grid_view", None)
            if gv is not None and hasattr(gv, "refresh_visible_thumbnails"):
                gv.refresh_visible_thumbnails()
        except Exception:
            pass
        
        # 恢复信息面板显示当前选中的缩略图信息
        selected_files = self.get_selected_files()
        if selected_files:
            self.info_panel.update_info(selected_files[0]['path'])
            # 确保选中的缩略图可见
            index = selected_files[0].get('index', -1)
            if index >= 0 and hasattr(self, 'grid_view'):
                self.grid_view.scroll_to_index(index)
        else:
            self.info_panel.update_info(None)

    def on_detail_image_changed(self, path):
        """详情页切换图片时更新信息面板"""
        self.info_panel.update_info(path)
        
        # 如果在对比模式下，普通切换（右侧图片）不更新图库选中状态
        if hasattr(self, 'detail_panel') and self.detail_panel and self.detail_panel.compare_mode:
            return

        # 同步更新图库选中状态
        if hasattr(self, 'image_files') and hasattr(self, 'grid_view'):
            for i, img in enumerate(self.image_files):
                if img.get('path') == path:
                    try:
                        self._detail_last_index = int(i)
                    except Exception:
                        self._detail_last_index = None
                    self.grid_view.select_thumbnail(i, scroll_to=True)
                    break

    def on_detail_left_image_selected(self, index):
        """对比模式下左侧图片切换时，同步更新图库选中状态"""
        if hasattr(self, 'image_files') and hasattr(self, 'grid_view'):
            if 0 <= index < len(self.image_files):
                # 同步选中状态
                self.grid_view.select_thumbnail(index, scroll_to=True)
                
                # 可选：更新信息面板显示左侧图片信息
                self.info_panel.update_info(self.image_files[index]['path'])

    def on_detail_favorite_changed(self, path, is_fav):
        """Handle favorite change from detail panel"""
        # Update thumbnails
        self._update_thumbnail_status(path, 'favorite', 1 if is_fav else 0)
        # Update info panel if needed
        self.info_panel.update_info(path)

    def on_detail_rating_changed(self, path, rating):
        """Handle rating change from detail panel"""
        # Update thumbnails
        self._update_thumbnail_status(path, 'rating', rating)
        # Update info panel if needed
        self.info_panel.update_info(path)

    def on_detail_label_changed(self, path, label):
        """Handle label change from detail panel"""
        self._perform_label_update([path], label)
        self.info_panel.update_info(path)

    def _update_thumbnail_status(self, path, key, value):
        target_key = self._normalize_path_key(path)
        # Update visible thumbnails
        if hasattr(self, 'grid_view'):
            for thumb in self.grid_view.thumbnails:
                if not thumb.image_info:
                    continue
                if self._normalize_path_key(thumb.image_info.get('path')) == target_key:
                    # Update info dict
                    thumb.image_info[key] = value
                    if key == 'favorite':
                         thumb.image_info['is_favorite'] = value # map favorite to is_favorite for compatibility
                    # Force repaint
                    thumb.update()
                    # Keep looking? No, usually one thumbnail per path unless split views
                    # But grid_view.thumbnails is a list, let's break
                    break
                    
        # Also update self.image_files and self.all_image_files
        for img_list in [self.image_files, self.all_image_files]:
            for img in img_list:
                if self._normalize_path_key(img.get('path')) == target_key:
                    img[key] = value
                    if key == 'favorite':
                         img['is_favorite'] = value
                    break

    def open_tag_manager(self):
        selected_paths = self.get_selected_paths()
        if not selected_paths:
            return
            
        from ui.dialogs.tag_manager_dialog import TagManagerDialog
        dialog = TagManagerDialog(self.db, selected_paths, self)
        dialog.tags_updated.connect(self.on_tags_updated)
        dialog.exec()

    def on_tags_updated(self, file_paths, tags_str):
        self._perform_tags_update(file_paths, tags_str)

    def _perform_tags_update(self, file_paths, tags_str):
        try:
            LogManager.instance().info(f"[Tags] Updating {len(file_paths)} files to tags={tags_str}")
        except Exception:
            pass
        target_keys = {self._normalize_path_key(p) for p in file_paths if p}
        
        # 1. Update DB
        self.db.update_tags_batch(file_paths, tags_str)
        
        # 2. Update EXIF (Async)
        tags = {EXIF_TAG.Tags.value: tags_str}
        exif_tasks = [(path, tags) for path in file_paths]
        
        def run_exif_update():
            task_id = StatusManager.instance().start_task(f"正在更新标签 (写入元数据)...")
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
            finally:
                StatusManager.instance().finish_task(task_id)

        threading.Thread(target=run_exif_update, daemon=True).start()
        
        # 3. Update Memory and UI
        # Need to update image_files 'tags' field
        for img_list in [self.raw_image_files, self.image_files, self.all_image_files]:
             for img in img_list:
                if self._normalize_path_key(img.get('path')) in target_keys:
                    img['tags'] = tags_str
        
        # Refresh info panel if current selection affected
        selected = self.get_selected_files()
        if selected and self._normalize_path_key(selected[0]['path']) in target_keys:
            # 从数据库获取最新记录，确保标签信息已更新
            try:
                record = self.db.get_result_by_path(selected[0]['path'], table_name='bird_results')
                io_data = {"record": record} if record else None
                self.info_panel.update_info(selected[0]['path'], io_data=io_data)
            except Exception:
                self.info_panel.update_info(selected[0]['path'])

    def on_thumbnail_context_menu_proxy(self, index, pos):
        """处理缩略图右键菜单代理"""
        self.on_thumbnail_context_menu(index, pos)

    def _is_unclassified_context(self) -> bool:
        try:
            p = str(getattr(self, "current_folder_path", "") or "")
        except Exception:
            p = ""
        if not p:
            return False
        try:
            if p.startswith("virtual://taxonomy/unclassified"):
                return True
        except Exception:
            pass
        try:
            if p.startswith("virtual://taxonomy") and "unclassified" in p:
                return True
        except Exception:
            pass
        try:
            base = os.path.basename(os.path.normpath(p))
            if base == "未分类":
                return True
        except Exception:
            pass
        return False

    def get_selected_files(self):
        """获取所有选中的文件信息
        Returns:
            list: 选中文件的信息列表，每个元素包含:
                - 'name': 文件名
                - 'path': 完整路径
                - 'create_time': 创建时间
                - 'index': 在列表中的索引
        """
        if getattr(self, "_select_all_active", False):
            selected_files = []
            for i, img_info in enumerate(self.all_image_files or []):
                if not isinstance(img_info, dict):
                    continue
                file_info = img_info.copy()
                file_info['index'] = i
                selected_files.append(file_info)
            return selected_files

        selected_files = []
        # Use grid_view.get_selected_thumbnails() directly
        for thumb in self.grid_view.get_selected_thumbnails():
            if thumb.image_info:
                file_info = thumb.image_info.copy()
                file_info['index'] = thumb.index # Use internal index from thumbnail
                selected_files.append(file_info)
        return selected_files

    def get_selected_paths(self):
        """获取所有选中文件的路径列表
        Returns:
            list: 选中文件的完整路径列表
        """
        return [f['path'] for f in self.get_selected_files()]

    def get_selected_indices(self):
        """获取所有选中文件的索引列表
        Returns:
            list: 选中文件在列表中的索引
        """
        if getattr(self, "_select_all_active", False):
            return list(range(len(self.all_image_files or [])))
        return [thumb.index for thumb in self.grid_view.get_selected_thumbnails()]

    def get_selected_count(self):
        """获取选中文件的数量
        Returns:
            int: 选中文件的数量
        """
        if getattr(self, "_select_all_active", False):
            return len(self.all_image_files or [])
        return self.grid_view.get_selected_count()

    def on_thumbnail_context_menu(self, index, position):
        """处理缩略图右键菜单"""
        try:
            thumbnails = self.grid_view.thumbnails
            if index >= len(thumbnails):
                return
                
            thumb = thumbnails[index]
            if not thumb.image_info:
                return

            # 如果右键点击的图标未被选中，则单选该图标
            if not thumb.selected:
                if getattr(self.grid_view, "is_virtualized", False):
                    self.grid_view.select_thumbnail(index, scroll_to=False)
                else:
                    for i, t in enumerate(thumbnails):
                        t.set_selected(i == index)
                self.last_selected_index = index
            image_info = thumb.image_info
            image_path = image_info['path']
            # 创建右键菜单
            menu = QMenu(self)
            cm = ColorManager.instance()
            menu_bg = cm.get("theme.background.light")
            menu_border = cm.get("popup.border.primary")
            menu_text = cm.get("theme.text.dark")
            menu_hover = cm.get("theme.background.dark")
            menu_disabled = cm.get("theme.text.light")
            menu.setStyleSheet(f"""
            QMenu {{
                background-color: {menu_bg};
                border: 1px solid {menu_border};
                padding: 2px;
            }}
            QMenu::item {{
                padding: 4px 20px 4px 30px;
                border: none;
                color: {menu_text};
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
                color: {menu_text};
            }}
            QMenu::item:disabled {{
                color: {menu_disabled};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {menu_border};
                margin: 2px 4px;
            }}
            """)

            # 打开
            open_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "打开")
            open_action.triggered.connect(lambda: self.open_image(image_path))
            # 在文件管理器中打开文件夹
            show_in_folder_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "在文件管理器中打开")
            show_in_folder_action.triggered.connect(lambda: self.folder_panel.open_in_explorer(os.path.dirname(image_path)))

            # 复制图片（支持多选和RAW缩略图）
            copy_action = menu.addAction(qta.icon('mdi6.content-copy', color='#555'), "复制图片")
            copy_action.triggered.connect(lambda: self.copy_image())
            # 复制图片文件（含XMP文件）
            copy_file_action = menu.addAction(qta.icon('mdi6.file-multiple', color='#555'), "复制图片文件")
            copy_file_action.triggered.connect(lambda: self.copy_image_files())
            # 复制路径
            copy_path_action = menu.addAction(qta.icon('mdi6.link-variant', color='#555'), "复制路径")
            copy_path_action.triggered.connect(lambda: self.copy_image_path(image_path))
            menu.addSeparator()

            try:
                if bool(getattr(self.grid_view, "is_virtualized", False)):
                    try:
                        selected_paths = self.get_selected_paths() or [str(image_path)]
                    except Exception:
                        selected_paths = [str(image_path)]
                    watermark_action = menu.addAction(qta.icon("mdi6.watermark", color="#555"), "添加水印")
                    watermark_action.triggered.connect(lambda: self.open_watermark_dialog(selected_paths))
                    menu.addSeparator()
            except Exception:
                pass

            # 收藏/取消收藏
            is_fav = bool(image_info.get('is_favorite', 0))
            if is_fav:
                fav_action = menu.addAction(qta.icon('mdi6.heart-outline', color='#555'), "取消收藏")
                fav_action.triggered.connect(lambda: self.toggle_favorite_selection(False))
            else:
                fav_action = menu.addAction(qta.icon('mdi6.heart', color='#e74c3c'), "收藏")
                fav_action.triggered.connect(lambda: self.toggle_favorite_selection(True))
            
            # 评分菜单
            rating_menu = menu.addMenu(qta.icon('fa5s.star', color='#FFCC00'), "评分")
            current_rating = image_info.get('rating', 0)
            
            # 0星 (清除评分)
            r0_action = rating_menu.addAction("0星 (清除)")
            if current_rating == 0:
                r0_action.setIcon(qta.icon('mdi6.check', color='#4caf50'))
            r0_action.triggered.connect(lambda: self.set_rating_selection(0))
            
            rating_menu.addSeparator()
            
            # 1-5星
            for r in range(1, 6):
                r_action = StarMenuAction(r, rating_menu)
                r_action.triggered_rating.connect(lambda val: self.set_rating_selection(val))
                rating_menu.addAction(r_action)

            # 色标菜单
            label_menu = menu.addMenu("设置色标")
            try:
                pm = QPixmap(16, 16)
                pm.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pm)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                rect = QRect(1, 1, 14, 14)
                base_color = QColor("#2196F3")
                grad = QRadialGradient(rect.x() + 14 * 0.3, rect.y() + 14 * 0.3, 14 * 0.8)
                grad.setColorAt(0, base_color.lighter(130))
                grad.setColorAt(0.5, base_color)
                grad.setColorAt(1, base_color.darker(110))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(grad))
                painter.drawEllipse(rect)
                painter.end()
                label_menu.setIcon(QIcon(pm))
            except Exception:
                pass
            
            # 定义颜色列表
            labels = [
                ("Red", "红色", "#FF3B30"),
                ("Yellow", "黄色", "#FFCC00"),
                ("Green", "绿色", "#5CB85C"), # Updated: Less saturated Green
                ("Blue", "蓝色", "#007AFF"),
                ("Purple", "紫色", "#AF52DE"),
                ("White", "白色", "#FFFFFF"),
                ("Orange", "橙色", "#FF9500"),
                ("Pink", "粉色", "#F06292"), # Updated: Less saturated Pink
                ("Cyan", "青色", "#5AC8FA"),
                ("Gray", "灰色", "#8E8E93"),
                ("Black", "黑色", "#48484A"),
            ]
            
            # 清除色标
            clear_label_action = label_menu.addAction("无色标 (清除)")
            clear_label_action.setIcon(qta.icon('mdi.close', color='#757575'))
            clear_label_action.triggered.connect(lambda: self.set_label_selection(""))
            
            label_menu.addSeparator()
            
            for en_name, cn_name, color_hex in labels:
                action = label_menu.addAction(cn_name)
                try:
                    pm = QPixmap(16, 16)
                    pm.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(pm)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    rect = QRect(1, 1, 14, 14)
                    base_color = QColor(str(color_hex or "#000000"))
                    grad = QRadialGradient(rect.x() + 14 * 0.3, rect.y() + 14 * 0.3, 14 * 0.8)
                    grad.setColorAt(0, base_color.lighter(130))
                    grad.setColorAt(0.5, base_color)
                    grad.setColorAt(1, base_color.darker(110))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(grad))
                    painter.drawEllipse(rect)
                    if en_name == "White":
                        painter.setPen(QPen(QColor("#A0A0A0"), 1))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(rect)
                    painter.end()
                    action.setIcon(QIcon(pm))
                except Exception:
                    pass
                action.triggered.connect(lambda checked=False, l=en_name: self.set_label_selection(l))

            # 地理位置
            location_action = menu.addAction(qta.icon('mdi6.map-marker-outline', color='#555'), "设置地理位置")
            location_action.triggered.connect(self.show_geolocation_dialog)

            track_match_action = menu.addAction(qta.icon('mdi6.transit-connection-variant', color='#555'), "轨迹匹配")
            track_match_action.triggered.connect(self.show_track_match_dialog)

            # 添加标签
            add_tag_action = menu.addAction(qta.icon('ph.tag-simple-fill', color='#555'), "添加标签")
            add_tag_action.triggered.connect(self.open_tag_manager)

            # 备注
            remark_action = menu.addAction(qta.icon('mdi6.comment-text-outline', color='#555'), "编辑备注")
            remark_action.triggered.connect(lambda: self.edit_remark(image_path))
            
            edit_species_action = menu.addAction(qta.icon('mdi6.target', color='#555'), "鸟种检测")
            edit_species_action.triggered.connect(self.edit_species_for_selection)
            menu.addSeparator()

            # 重命名
            rename_action = menu.addAction(qta.icon('mdi6.rename-box', color='#555'), "重命名")
            rename_action.triggered.connect(lambda: self.rename_image(index, image_path))
            # 删除
            delete_action = menu.addAction(qta.icon('mdi6.trash-can-outline', color='#e74c3c'), "删除")
            def _delete_clicked():
                selected = self.get_selected_files()
                try:
                    selected_paths = {self._normalize_path_key(f.get("path")) for f in (selected or []) if isinstance(f, dict) and f.get("path")}
                except Exception:
                    selected_paths = set()
                if len(selected_paths) > 1 and self._normalize_path_key(image_path) in selected_paths:
                    self.on_delete_clicked()
                else:
                    self.delete_image(index, image_path)
            delete_action.triggered.connect(_delete_clicked)
            
            menu.addSeparator()

            
            menu.addSeparator()
            # Exif 操作
            exif_write_action = menu.addAction(qta.icon('mdi6.file-document-edit', color='#555'), "写入Exif信息")
            exif_write_action.triggered.connect(lambda: self.show_exif_write_dialog(image_path))
            exif_read_action = menu.addAction(qta.icon('mdi6.file-search', color='#555'), "读取Exif信息")
            exif_read_action.triggered.connect(lambda: self.show_exif_read_dialog(image_path))
            menu.addSeparator()

            # 属性
            properties_action = menu.addAction(qta.icon('mdi6.information', color='#555'), "属性")
            properties_action.triggered.connect(lambda: self.show_image_properties(image_path))
            
            menu.addSeparator()
            
            # 刷新缩略图
            refresh_action = menu.addAction(qta.icon('mdi6.refresh', color='#555'), "刷新缩略图")
            refresh_action.triggered.connect(lambda: self.refresh_thumbnail(image_path))
            
            # 显示菜单
            try:
                menu.exec(position)
            except Exception as e:
                try:
                    LogManager.instance().error(f"显示右键菜单失败: {e}")
                    import traceback
                    LogManager.instance().error(traceback.format_exc())
                except Exception:
                    pass
        except Exception as e:
            try:
                LogManager.instance().error(f"右键菜单处理失败: {e}")
                import traceback
                LogManager.instance().error(traceback.format_exc())
            except Exception:
                pass

    def open_watermark_dialog(self, file_paths):
        if bool(getattr(self, "_watermark_dialog_opening", False)):
            return
        self._watermark_dialog_opening = True
        gpu_paused = False
        main_win = None
        old_gpu_suppress_until = None
        old_gpu_query_running = None
        old_sys_timer_active = None
        old_sys_timer_interval = None
        try:
            paths = [str(p) for p in (file_paths or []) if p]
            if not paths:
                return
            try:
                main_win = self.window()
            except Exception:
                main_win = None
            try:
                from utils.system.gpu_monitor import enter_gpu_query_pause

                gpu_paused = bool(enter_gpu_query_pause())
            except Exception:
                gpu_paused = False
            try:
                if main_win is not None:
                    try:
                        if hasattr(main_win, "sys_timer") and main_win.sys_timer is not None:
                            old_sys_timer_active = bool(main_win.sys_timer.isActive())
                            old_sys_timer_interval = int(main_win.sys_timer.interval())
                            main_win.sys_timer.stop()
                    except Exception:
                        old_sys_timer_active = None
                        old_sys_timer_interval = None
                    try:
                        old_gpu_suppress_until = float(getattr(main_win, "_gpu_suppress_until", 0.0) or 0.0)
                    except Exception:
                        old_gpu_suppress_until = None
                    try:
                        old_gpu_query_running = bool(getattr(main_win, "_gpu_query_running", False))
                    except Exception:
                        old_gpu_query_running = None
                    try:
                        import time

                        main_win._gpu_suppress_until = float(time.monotonic()) + 3600.0
                    except Exception:
                        pass
                    try:
                        main_win._gpu_query_running = True
                    except Exception:
                        pass
            except Exception:
                pass
            from ui.dialogs.watermark_dialog import WatermarkDialog

            dlg = WatermarkDialog(parent=self, file_paths=paths)
            dlg.exec()
            try:
                # 仅在用户点击“保存/另存”时才触发缩略图刷新，避免未改动也触发缓存失效
                did_write = False
                try:
                    did_write = dlg.user_clicked_write() if hasattr(dlg, "user_clicked_write") else bool(getattr(dlg, "_user_clicked_write", False))
                except Exception:
                    did_write = False
                if did_write:
                    changed_paths = []
                    try:
                        changed_paths = dlg.get_last_changed_paths() if hasattr(dlg, "get_last_changed_paths") else []
                    except Exception:
                        changed_paths = []
                    for p in (changed_paths or []):
                        self.refresh_thumbnail(p)
            except Exception:
                pass
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开水印窗口失败: {e}")
        finally:
            try:
                if gpu_paused:
                    from utils.system.gpu_monitor import exit_gpu_query_pause

                    exit_gpu_query_pause()
            except Exception:
                pass
            try:
                if main_win is not None and old_gpu_suppress_until is not None:
                    main_win._gpu_suppress_until = float(old_gpu_suppress_until)
            except Exception:
                pass
            try:
                if main_win is not None and old_gpu_query_running is not None:
                    main_win._gpu_query_running = bool(old_gpu_query_running)
            except Exception:
                pass
            try:
                if main_win is not None and old_sys_timer_active:
                    try:
                        itv = int(old_sys_timer_interval) if old_sys_timer_interval is not None else 1000
                    except Exception:
                        itv = 1000
                    try:
                        if hasattr(main_win, "sys_timer") and main_win.sys_timer is not None:
                            main_win.sys_timer.start(int(itv))
                    except Exception:
                        pass
            except Exception:
                pass
            self._watermark_dialog_opening = False

    def _safe_rmdir_empty(self, path: str, root_limit=None):
        p = str(path or "")
        if not p:
            return
        try:
            root_norm = os.path.normcase(os.path.normpath(str(root_limit))) if root_limit else ""
        except Exception:
            root_norm = ""
        cur = p
        for _ in range(6):
            if not cur:
                break
            try:
                if not os.path.isdir(cur):
                    break
            except Exception:
                break
            try:
                if os.listdir(cur):
                    break
            except Exception:
                break
            try:
                os.rmdir(cur)
            except Exception:
                break
            try:
                parent = os.path.dirname(cur)
            except Exception:
                break
            if not parent or parent == cur:
                break
            if root_norm:
                try:
                    if not os.path.normcase(os.path.normpath(parent)).startswith(root_norm):
                        break
                except Exception:
                    break
            cur = parent

    def edit_species_for_selection(self):
        selected = self.get_selected_files()
        if not selected:
            return
        
        from ui.dialogs.bird_species_detect_dialog import BirdSpeciesDetectDialog
        dlg = BirdSpeciesDetectDialog(self, selected_files=selected)
        if not dlg.exec():
            return
        
        # 获取结果 (path -> {species, order, family, genus})
        results = dlg.get_results()
        if not results:
            return
            
        root_dir = str(self.settings_manager.get("general/root_path") or "")
        # 默认总是移动文件（符合用户需求）
        move_files = True
        
        tax_updates = []
        exif_tasks = []
        old_dirs = set()
        moved_map = {}
        
        # 批量处理更新
        for path_key, state in results.items():
            if not path_key: continue
            
            # 找到原始文件对象
            orig_file = None
            for f in selected:
                if str(f.get("path") or "") == path_key:
                    orig_file = f
                    break
            if not orig_file: continue
            
            p = path_key
            if not os.path.exists(p): continue
            
            species = str(state.get("species") or "").strip()
            order = str(state.get("order") or "").strip()
            family = str(state.get("family") or "").strip()
            genus = str(state.get("genus") or "").strip()
            
            # 如果没有修改，跳过？或者强制更新？
            # 只要有物种信息就更新
            if not species: continue
            
            old_dirs.add(os.path.dirname(p))
            new_path = p
            
            if move_files and root_dir and os.path.isdir(root_dir) and order and family and genus and species:
                dest_dir = os.path.join(root_dir, order, family, genus, species)
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                except Exception:
                    pass
                base = os.path.basename(p)
                candidate = os.path.join(dest_dir, base)
                
                # 如果目标路径不同，才移动
                if os.path.normcase(os.path.normpath(candidate)) != os.path.normcase(os.path.normpath(p)):
                    if os.path.exists(candidate):
                        stem, ext = os.path.splitext(base)
                        for n in range(1, 200):
                            cand2 = os.path.join(dest_dir, f"{stem}_{n}{ext}")
                            if not os.path.exists(cand2):
                                candidate = cand2
                                break
                    try:
                        from utils.file.file_utils import move_with_sidecar
                        move_with_sidecar(p, candidate)
                        new_path = candidate
                        moved_map[p] = new_path
                        try:
                            self.db.update_file_path(p, new_path, os.path.basename(new_path), table_name="bird_results")
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            LogManager.instance().warning(f"移动文件失败 {p}: {e}")
                        except Exception:
                            pass
                        continue
            
            tax_updates.append({
                "path": new_path,
                "object": species,
                "order_cls": order,
                "family_cls": family,
                "genus_cls": genus,
                "species_cls": species,
            })
            
            exif_tasks.append((
                new_path,
                {
                    EXIF_TAG.Object.value: species,
                    EXIF_TAG.OrderCls.value: order,
                    EXIF_TAG.FamilyCls.value: family,
                    EXIF_TAG.GenusCls.value: genus,
                    EXIF_TAG.SpeciesCls.value: species,
                },
            ))

        if tax_updates:
            try:
                self.db.update_taxonomy_batch_for_table(tax_updates, table_name="bird_results")
            except Exception:
                pass
        if exif_tasks:
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
            except Exception:
                pass

        for d in old_dirs:
            self._safe_rmdir_empty(d, root_limit=root_dir)

        pre_op_path = str(getattr(self, "current_folder_path", "") or "")

        try:
            if hasattr(self, "folder_panel") and self.folder_panel is not None:
                self.folder_panel.refresh_tree(root_path=root_dir)
        except Exception:
            pass
            
        view_restored = False
        if pre_op_path:
             # 1. 虚拟分类路径
             if pre_op_path.startswith("virtual://taxonomy"):
                 try:
                     from urllib.parse import urlparse, parse_qs
                     parsed = urlparse(pre_op_path)
                     params = parse_qs(parsed.query)
                     order = params.get('order', [None])[0]
                     family = params.get('family', [None])[0]
                     genus = params.get('genus', [None])[0]
                     species = params.get('species', [None])[0]
                     
                     if order or family or genus or species or "unclassified" in pre_op_path:
                          self.folder_panel.locate_taxonomy_node(order, family, genus, species, emit_signal=False)
                          if self.folder_panel.folder_tree.selectedItems():
                              view_restored = True
                              self.load_images_from_taxonomy(pre_op_path)
                 except:
                     pass
             
             # 2. 物理文件夹路径
             elif os.path.exists(pre_op_path):
                 if self.folder_panel.navigate_to_folder(pre_op_path):
                     view_restored = True
                     # navigate_to_folder 可能会触发信号，但也可能不触发（如果已经选中了？）
                     # 无论如何，强制刷新一次是安全的
                     self.load_images_from_folder(pre_op_path)
        
        # 如果未能恢复（例如文件夹被移空删除了，或者分类下没图片导致节点消失了）
        if not view_restored:
            # Check if the target virtual node exists after update
            # We construct the virtual path for the NEW species info
            try:
                if order and family and genus and species:
                     self.folder_panel.locate_taxonomy_node(order, family, genus, species, emit_signal=False)
                     if self.folder_panel.folder_tree.selectedItems():
                         # Found the new node! Load it.
                         new_virtual_uri = f"virtual://taxonomy?order={order}&family={family}&genus={genus}&species={species}"
                         self.load_images_from_taxonomy(new_virtual_uri)
                         view_restored = True
            except Exception:
                pass
        
        if not view_restored:
             # 清空视图
             self.image_files = []
             self.raw_image_files = []
             self.update_thumbnails()
             self.clear_preview()
             # 清空路径记录
             self.current_folder_path = ""
             # 确保树不选中任何东西
             try:
                 self.folder_panel.folder_tree.clearSelection()
             except:
                 pass
             self.update_path_bar("")

        try:
            NotificationManager.instance().show_toast("物种已更新")
        except Exception:
            pass

    def rename_current_taxonomy_node(self):
        try:
            item = self.folder_panel.folder_tree.currentItem() if hasattr(self, "folder_panel") else None
            uri = item.data(0, Qt.ItemDataRole.UserRole) if item else ""
        except Exception:
            uri = ""
        uri = str(uri or "")
        if not uri.startswith("virtual://taxonomy"):
            return
        if uri.startswith("virtual://taxonomy/unclassified"):
            NotificationManager.instance().show_toast("未分类节点不支持重命名")
            return
        parsed = urlparse(uri.replace("virtual://taxonomy", "http://taxonomy", 1))
        qs = parse_qs(parsed.query or "")
        order = (qs.get("order") or [""])[0]
        family = (qs.get("family") or [""])[0]
        genus = (qs.get("genus") or [""])[0]
        species = (qs.get("species") or [""])[0]
        if not (order and family and genus and species):
            NotificationManager.instance().show_toast("仅支持对“种”节点执行重命名")
            return
        try:
            root_dir = str(self.settings_manager.get("general/root_path") or "")
        except Exception:
            root_dir = ""
        rows = []
        try:
            rows = self.db.query_images_by_taxonomy(order_cls=order, family_cls=family, genus_cls=genus, species_cls=species, unclassified=False, table_name="bird_results", root_path=root_dir)
        except Exception:
            rows = []
        if not rows:
            NotificationManager.instance().show_toast("该物种下没有图片")
            return
        selected = [{"path": r["file_path"]} for r in rows if r and r.get("file_path")]
        first = {"species": species, "order": order, "family": family, "genus": genus}
        init_species = str(first.get("species") or "").strip()
        init_order = str(first.get("order") or "").strip()
        init_family = str(first.get("family") or "").strip()
        init_genus = str(first.get("genus") or "").strip()
        dlg = EditSpeciesDialog(self, initial_species=init_species, initial_order=init_order, initial_family=init_family, initial_genus=init_genus)
        if not dlg.exec():
            return
        res = dlg.get_result() or {}
        new_species = str(res.get("species_cls") or "").strip()
        new_order = str(res.get("order_cls") or "").strip()
        new_family = str(res.get("family_cls") or "").strip()
        new_genus = str(res.get("genus_cls") or "").strip()
        move_files = bool(res.get("move_files"))

        if move_files and not (root_dir and os.path.isdir(root_dir) and new_order and new_family and new_genus and new_species):
            move_files = False

        tax_updates = []
        exif_tasks = []
        old_dirs = set()

        for it in selected:
            p = str(it.get("path") or "")
            if not p or not os.path.exists(p):
                continue
            old_dirs.add(os.path.dirname(p))
            new_path = p
            if move_files:
                dest_dir = os.path.join(root_dir, new_order, new_family, new_genus, new_species)
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                except Exception:
                    pass
                base = os.path.basename(p)
                candidate = os.path.join(dest_dir, base)
                if os.path.normcase(os.path.normpath(candidate)) != os.path.normcase(os.path.normpath(p)):
                    if os.path.exists(candidate):
                        stem, ext = os.path.splitext(base)
                        for n in range(1, 200):
                            cand2 = os.path.join(dest_dir, f"{stem}_{n}{ext}")
                            if not os.path.exists(cand2):
                                candidate = cand2
                                break
                    try:
                        from utils.file.file_utils import move_with_sidecar
                        move_with_sidecar(p, candidate)
                        new_path = candidate
                        try:
                            self.db.update_file_path(p, new_path, os.path.basename(new_path), table_name="bird_results")
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            LogManager.instance().warning(f"移动文件失败 {p}: {e}")
                        except Exception:
                            pass
                        continue

            tax_updates.append({"path": new_path, "object": new_species, "order_cls": new_order, "family_cls": new_family, "genus_cls": new_genus, "species_cls": new_species})
            exif_tasks.append((new_path, {EXIF_TAG.Object.value: new_species, EXIF_TAG.OrderCls.value: new_order, EXIF_TAG.FamilyCls.value: new_family, EXIF_TAG.GenusCls.value: new_genus, EXIF_TAG.SpeciesCls.value: new_species}))

        if tax_updates:
            try:
                self.db.update_taxonomy_batch_for_table(tax_updates, table_name="bird_results")
            except Exception:
                pass
        if exif_tasks:
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
            except Exception:
                pass

        for d in old_dirs:
            self._safe_rmdir_empty(d, root_limit=root_dir)

        try:
            if hasattr(self, "folder_panel") and self.folder_panel is not None:
                self.folder_panel.refresh_tree(root_path=root_dir)
        except Exception:
            pass
        try:
            cur = str(getattr(self, "current_folder_path", "") or "")
            if cur.startswith("virtual://taxonomy"):
                self.load_images_from_taxonomy(cur)
        except Exception:
            pass
        NotificationManager.instance().show_toast("分类已更新")

    def clear_current_taxonomy_node(self):
        try:
            item = self.folder_panel.folder_tree.currentItem() if hasattr(self, "folder_panel") else None
            uri = item.data(0, Qt.ItemDataRole.UserRole) if item else ""
        except Exception:
            uri = ""
        uri = str(uri or "")
        if not uri.startswith("virtual://taxonomy"):
            return
        if not NotificationManager.instance().ask_confirmation("确认操作", "确定要将该节点下的图片设为未分类吗？"):
            return
        if uri.startswith("virtual://taxonomy/unclassified"):
            NotificationManager.instance().show_toast("未分类节点无需清空")
            return
        parsed = urlparse(uri.replace("virtual://taxonomy", "http://taxonomy", 1))
        qs = parse_qs(parsed.query or "")
        order = (qs.get("order") or [""])[0] or None
        family = (qs.get("family") or [""])[0] or None
        genus = (qs.get("genus") or [""])[0] or None
        species = (qs.get("species") or [""])[0] or None
        try:
            root_dir = str(self.settings_manager.get("general/root_path") or "")
        except Exception:
            root_dir = ""
        rows = []
        try:
            rows = self.db.query_images_by_taxonomy(order_cls=order, family_cls=family, genus_cls=genus, species_cls=species, unclassified=False, table_name="bird_results", root_path=root_dir)
        except Exception:
            rows = []
        if not rows:
            NotificationManager.instance().show_toast("该节点下没有图片")
            return
        updates = []
        exif_tasks = []
        for r in rows:
            try:
                p = str(r["file_path"] or "")
            except Exception:
                p = ""
            if not p:
                continue
            updates.append({"path": p, "object": "", "order_cls": "", "family_cls": "", "genus_cls": "", "species_cls": ""})
            exif_tasks.append((p, {EXIF_TAG.Object.value: "", EXIF_TAG.OrderCls.value: "", EXIF_TAG.FamilyCls.value: "", EXIF_TAG.GenusCls.value: "", EXIF_TAG.SpeciesCls.value: ""}))
        try:
            if updates:
                self.db.update_taxonomy_batch_for_table(updates, table_name="bird_results")
        except Exception:
            pass
        try:
            if exif_tasks:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
        except Exception:
            pass
        try:
            if hasattr(self, "folder_panel") and self.folder_panel is not None:
                self.folder_panel.refresh_tree(root_path=root_dir)
        except Exception:
            pass
        try:
            cur = str(getattr(self, "current_folder_path", "") or "")
            if cur.startswith("virtual://taxonomy"):
                self.load_images_from_taxonomy(cur)
        except Exception:
            pass
        NotificationManager.instance().show_toast("已设为未分类")

    def refresh_thumbnail(self, image_path):
        """强制刷新指定图片的缩略图"""
        if not image_path:
            return
            
        try:
            LogManager.instance().info(f"[UI] Refreshing thumbnail for: {image_path}")
        except Exception:
            pass
        
        # 1. 使缓存失效
        self.cache_manager.invalidate(image_path)
        
        # 2. 重新加载
        # 找到对应的缩略图控件并重置
        key = self._normalize_path_key(image_path)
        thumb = self._thumb_by_path.get(key)
        if thumb:
            # 清除显示的图片，显示加载中状态（可选）
            thumb.thumbnail_pixmap = None
            thumb.update()
            
        # 触发加载器
        cache_type = getattr(self, "current_cache_type", "general")
        try:
            req_size = getattr(self, "current_thumb_size", None)
        except Exception:
            req_size = None
        try:
            if isinstance(req_size, (tuple, list)):
                req_max = max(int(req_size[0]), int(req_size[1]))
            elif req_size:
                req_max = int(req_size)
            else:
                req_max = 0
        except Exception:
            req_max = 0
        self.thumbnail_loader.load_thumbnails([image_path], self.current_thumb_size, cache_type, request_id=getattr(self, "_thumbnail_request_id", None))
        NotificationManager.instance().show_toast("正在刷新缩略图...")

    def open_image(self, image_path):
        """打开图片"""
        try:
            import platform
            if platform.system() == "Windows":
                os.startfile(image_path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", image_path])
            else:
                subprocess.Popen(["xdg-open", image_path])
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"无法打开图片: {e}")

    def show_in_folder(self, image_path):
        """在文件管理器中显示"""
        try:
            import platform
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", "/select,", image_path])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-R", image_path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(image_path)])
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"无法打开文件管理器: {e}")

    def copy_image(self, image_path=None):
        """复制图片到剪贴板，支持多选图片和RAW缩略图
        
        Args:
            image_path: 单张图片路径（可选，如果为None则复制所有选中的图片）
        """
        try:
            from PyQt6.QtGui import QClipboard, QImage
            from utils.file.file import load_image
            import numpy as np
            
            # 获取要复制的图片路径列表
            if image_path:
                # 单张图片
                paths = [image_path]
            else:
                # 多选图片
                paths = self.get_selected_paths()
            
            if not paths:
                NotificationManager.instance().show_warning("提示", "没有选中图片")
                return
            
            # 复制第一张图片的数据到剪贴板
            self._copy_single_image(paths[0])
            
            # 如果有多张图片，显示提示
            if len(paths) > 1:
                NotificationManager.instance().show_toast(f"已复制第一张图片到剪贴板（共选中 {len(paths)} 张）")
            
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"复制失败: {e}")

    def _copy_single_image(self, image_path):
        """复制单张图片到剪贴板"""
        try:
            from PyQt6.QtGui import QClipboard, QImage
            from utils.file.file import load_image
            import numpy as np
            
            # 使用 file.py 中的 load_image 统一接口加载图片（支持 RAW 内嵌预览图）
            img_data = load_image(image_path)
            
            if img_data is None:
                NotificationManager.instance().show_warning("错误", "无法加载图片")
                return

            # OpenCV (BGR) -> Qt (RGB)
            height, width, channel = img_data.shape
            bytes_per_line = 3 * width
            
            # 方法 B: 正确声明源数据是 BGR888
            q_img = QImage(img_data.data, width, height, bytes_per_line, QImage.Format.Format_BGR888)
            
            # 深拷贝并转为标准 RGB
            q_img = q_img.copy() 
            
            pixmap = QPixmap.fromImage(q_img)
            
            clipboard = QApplication.clipboard()
            if not pixmap.isNull():
                clipboard.setPixmap(pixmap)
                NotificationManager.instance().show_toast("图片已复制到剪贴板")
            else:
                NotificationManager.instance().show_warning("错误", "无法转换图片数据")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"复制失败: {e}")
            try:
                # Fallback: 尝试最原始的方法
                from PyQt6.QtGui import QClipboard
                clipboard = QApplication.clipboard()
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    clipboard.setPixmap(pixmap)
            except Exception:
                pass

    def copy_image_files(self, image_path=None):
        """复制图片文件到剪贴板（含XMP文件）
        
        Args:
            image_path: 单张图片路径（可选，如果为None则复制所有选中的图片）
        """
        try:
            from PyQt6.QtCore import QMimeData, QUrl
            
            # 获取要复制的图片路径列表
            if image_path:
                paths = [image_path]
            else:
                paths = self.get_selected_paths()
            
            if not paths:
                NotificationManager.instance().show_warning("提示", "没有选中图片")
                return
            
            # 收集所有要复制的文件（图片 + 对应的XMP文件）
            files_to_copy = []
            xmp_count = 0
            
            for path in paths:
                if os.path.exists(path):
                    files_to_copy.append(path)
                    
                    # 检查是否存在对应的XMP文件
                    base_path = os.path.splitext(path)[0]
                    
                    # 在 Windows 上文件系统不区分大小写，所以只需要检查一次
                    # 优先检查小写扩展名
                    xmp_path = base_path + '.xmp'
                    if os.path.exists(xmp_path):
                        files_to_copy.append(xmp_path)
                        xmp_count += 1
                    else:
                        # 如果小写不存在，再检查大写（Linux/Mac 可能区分大小写）
                        xmp_path_upper = base_path + '.XMP'
                        if os.path.exists(xmp_path_upper):
                            files_to_copy.append(xmp_path_upper)
                            xmp_count += 1
            
            if not files_to_copy:
                NotificationManager.instance().show_warning("错误", "文件不存在")
                return
            
            # 创建MIME数据
            mime_data = QMimeData()
            urls = [QUrl.fromLocalFile(f) for f in files_to_copy]
            mime_data.setUrls(urls)
            
            clipboard = QApplication.clipboard()
            clipboard.setMimeData(mime_data)
            
            # 显示提示
            if xmp_count > 0:
                NotificationManager.instance().show_toast(f"已复制 {len(paths)} 个图片文件和 {xmp_count} 个XMP文件")
            else:
                NotificationManager.instance().show_toast(f"已复制 {len(paths)} 个图片文件")
                
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"复制文件失败: {e}")

    def copy_image_path(self, image_path):
        """复制图片路径到剪贴板"""
        try:
            from PyQt6.QtGui import QClipboard
            clipboard = QApplication.clipboard()
            clipboard.setText(image_path)
            NotificationManager.instance().show_toast("路径已复制到剪贴板")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"复制失败: {e}")

    def rename_image(self, index, image_path):
        """重命名图片（单张，走批量重命名流程）"""
        file_info = None
        if hasattr(self, 'grid_view') and 0 <= index < len(self.grid_view.thumbnails):
            thumb = self.grid_view.thumbnails[index]
            if thumb.image_info and thumb.image_info['path'] == image_path:
                file_info = thumb.image_info.copy()
                file_info['index'] = index
        
        if not file_info:
            # Fallback if thumbnail lookup fails
            file_info = {'path': image_path, 'name': os.path.basename(image_path), 'index': index}
            
        self.batch_rename_images([file_info])

    def batch_rename_images(self, selected_files):
        """批量重命名图片"""
        if not selected_files:
            return
            
        dialog = BatchRenameDialog(self, selected_files)
        if dialog.exec():
            rename_map = dialog.get_results() # {old_path: new_name}
            success_count = 0
            fail_count = 0
            
            # 执行重命名
            for file_info in selected_files:
                old_path = file_info['path']
                thumb_index = file_info.get('index', -1)
                
                if old_path not in rename_map:
                    continue
                    
                new_name = rename_map[old_path]
                dir_path = os.path.dirname(old_path)
                new_path = os.path.join(dir_path, new_name)
                
                if old_path == new_path:
                    continue
                    
                # 检查文件是否被占用
                if os.path.exists(new_path) and old_path.lower() != new_path.lower():
                     # 如果目标文件已存在，可能是之前的循环重命名产生的冲突
                     # 或者确实有同名文件
                     try:
                         LogManager.instance().debug(f"目标文件已存在，尝试生成唯一名称: {new_path}")
                     except Exception:
                         pass
                     # 尝试生成唯一名称
                     base, ext = os.path.splitext(new_name)
                     counter = 1
                     while os.path.exists(new_path):
                         new_name = f"{base}_{counter}{ext}"
                         new_path = os.path.join(dir_path, new_name)
                         counter += 1
                
                try:
                    from utils.file.file_utils import rename_with_sidecar
                    rename_with_sidecar(old_path, new_path)
                    
                    # 更新数据库
                    self.db.update_file_path(old_path, new_path, new_name)
                    
                    # 更新内存数据 (在 self.image_files 中查找并更新)
                    target_img = next((img for img in self.image_files if img['path'] == old_path), None)
                    if target_img:
                        target_img['path'] = new_path
                        target_img['name'] = new_name
                    
                    # 更新缓存索引
                    self.cache_manager.rename_cache(old_path, new_path)
                    
                    # 更新缩略图
                    if hasattr(self, 'grid_view') and 0 <= thumb_index < len(self.grid_view.thumbnails):
                        thumb = self.grid_view.thumbnails[thumb_index]
                        # 确保缩略图对应的是同一个文件 (以防万一)
                        # 如果是 target_img 找到了，用它更新；否则用构造的
                        new_info = target_img if target_img else file_info.copy()
                        new_info['path'] = new_path
                        new_info['name'] = new_name
                        thumb.set_image_info(new_info)
                        
                    success_count += 1
                except Exception as e:
                    try:
                        LogManager.instance().warning(f"重命名失败: {old_path} -> {new_path}: {e}")
                    except Exception:
                        pass
                    # 如果是权限错误，可能是缩略图占用，尝试释放资源
                    if "WinError 32" in str(e): # The process cannot access the file because it is being used by another process
                         # 释放所有缩略图资源
                         self.thumbnail_loader.cancel_all()
                         # 尝试强制关闭文件句柄（如果可能）
                         # 这里简单地等待一下再试
                         time.sleep(0.1)
                         try:
                            from utils.file.file_utils import rename_with_sidecar
                            rename_with_sidecar(old_path, new_path)
                            # 成功了！继续后续更新
                            self.db.update_file_path(old_path, new_path, new_name)
                            
                            target_img = next((img for img in self.image_files if img['path'] == old_path), None)
                            if target_img:
                                target_img['path'] = new_path
                                target_img['name'] = new_name
                            
                            # 更新缓存索引
                            self.cache_manager.rename_cache(old_path, new_path)
                            
                            if hasattr(self, 'grid_view') and 0 <= thumb_index < len(self.grid_view.thumbnails):
                                thumb = self.grid_view.thumbnails[thumb_index]
                                new_info = target_img if target_img else file_info.copy()
                                new_info['path'] = new_path
                                new_info['name'] = new_name
                                thumb.set_image_info(new_info)
                                
                            success_count += 1
                            continue
                         except Exception as retry_e:
                             try:
                                 LogManager.instance().warning(f"重命名重试失败: {retry_e}")
                             except Exception:
                                 pass
                             fail_count += 1
                    else:
                        fail_count += 1
            
            if success_count > 0:
                NotificationManager.instance().show_toast(f"成功重命名 {success_count} 个文件")
            if fail_count > 0:
                NotificationManager.instance().show_warning("警告", f"{fail_count} 个文件重命名失败")
            
            # 重新排序并刷新显示以修复排列混乱问题
            self.sort_images()

    def edit_remark(self, image_path):
        """编辑图片备注"""
        try:
            # 获取当前备注
            current_remark = ""
            record = self.db.get_result_by_path(image_path, table_name="bird_results")
            if record:
                d = record.get("description")
                if d:
                    current_remark = str(d)
            
            dialog = RemarkDialog(self, current_remark)
            if dialog.exec():
                new_remark = dialog.get_remark()
                
                # 更新数据库
                self.db.update_description(image_path, new_remark)
                
                # 更新内存中的信息
                # 找到对应的缩略图并更新
                for thumb in self.grid_view.thumbnails:
                    if thumb.image_info and thumb.image_info.get('path') == image_path:
                        thumb.image_info['description'] = new_remark
                        break
                
                # 更新当前内存列表
                target_img = next((img for img in self.image_files if img['path'] == image_path), None)
                if target_img:
                    target_img['description'] = new_remark
                    
                # 如果当前选中的是这张图，刷新信息面板
                if self.info_panel.isVisible():
                     selected_paths = self.get_selected_paths()
                     if image_path in selected_paths:
                         # 从数据库获取最新记录，确保备注信息已更新
                         try:
                             record = self.db.get_result_by_path(image_path, table_name='bird_results')
                             io_data = {"record": record} if record else None
                             self.info_panel.update_info(image_path, io_data=io_data)
                         except Exception:
                             self.info_panel.update_info(image_path)
                         
                NotificationManager.instance().show_toast("备注已更新")
                
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"更新备注失败: {e}")

    def show_geolocation_dialog(self, checked: bool = False):
        """显示设置地理位置弹窗"""
        try:
            _ = checked
            selected_paths = self.get_selected_paths()
            selected_count = len(selected_paths)
            
            if selected_count == 0:
                NotificationManager.instance().show_warning("提示", "请先选择图片")
                return

            dialog = GeoLocationDialog(self, selected_count=selected_count, file_paths=selected_paths)
            dialog.geo_updated.connect(self._on_geo_updated)
            dialog.exec()
            try:
                from ui.utils.window_effect import apply_dark_title_bar
                main_window = self.window()
                if main_window:
                    cm = ColorManager.instance()
                    apply_dark_title_bar(main_window, "#2c3e50", cm.get("theme.text.light"))
            except Exception:
                pass
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开地理位置窗口失败: {e}")
    
    def _on_geo_updated(self, file_paths):
        """地理位置更新完成回调，刷新信息面板"""
        try:
            # 清除可能存在的缓存，确保下次切换图片时能获取最新数据
            # 注意：image_library_page 没有使用 _info_panel_cache，但 info_panel 内部可能有 EXIF 缓存
            # 这里我们强制刷新当前显示的图片的信息面板
            current_path = getattr(self.preview_panel, "current_image_path", None) if hasattr(self, 'preview_panel') else None
            if current_path and current_path in file_paths:
                # 刷新信息面板
                if hasattr(self, 'info_panel') and self.info_panel:
                    # 从数据库获取最新记录，确保地理位置信息已更新
                    try:
                        from utils.sql.data_base import BirdLibraryDB
                        db = BirdLibraryDB()
                        record = db.get_result_by_path(current_path, table_name='bird_results')
                        io_data = {"record": record} if record else None
                        self.info_panel.update_info(current_path, io_data=io_data)
                    except Exception:
                        # 如果数据库查询失败，仍然尝试刷新信息面板
                        self.info_panel.update_info(current_path)
        except Exception:
            pass

    def show_track_match_dialog(self, checked: bool = False):
        try:
            _ = checked
            selected_paths = self.get_selected_paths()
            if not selected_paths:
                NotificationManager.instance().show_warning("提示", "请先选择图片")
                return
            from ui.widgets.track_match_dialog import TrackMatchDialog
            dialog = TrackMatchDialog(self, file_paths=selected_paths, table_name="bird_results")
            dialog.exec()
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开轨迹匹配窗口失败: {e}")

    def delete_image(self, index, image_path):
        """删除图片"""
        # 获取上次的删除选择状态
        delete_local_key = "library/delete_local_file_enabled"
        
        # 使用带复选框的确认对话框
        def _to_bool(v, default=True):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(int(v))
            try:
                s = str(v).strip().lower()
            except Exception:
                return bool(default)
            if s in ("1", "true", "yes", "y", "on"):
                return True
            if s in ("0", "false", "no", "n", "off", ""):
                return False
            return bool(default)

        confirmed, delete_local = NotificationManager.instance().ask_confirmation(
            "确认删除",
            f"确定要删除以下文件吗？\n{os.path.basename(image_path)}",
            show_checkbox=True,
            checkbox_text="同时删除本地磁盘文件",
            default_checked=_to_bool(self.settings_manager.get(delete_local_key, True), default=True)
        )

        try:
            self.settings_manager.set(delete_local_key, delete_local)
            self.settings_manager.sync()
        except Exception:
            pass

        if not confirmed:
            return

        try:
            try:
                target_key = self._normalize_path_key(image_path)
            except Exception:
                target_key = str(image_path or "")
            try:
                root_dir = str(self.settings_manager.get("general/root_path") or "")
            except Exception:
                root_dir = ""

            # 1. 删除本地文件 (如果勾选)
            if delete_local and os.path.exists(image_path):
                try:
                    from utils.file.file_utils import delete_with_sidecar
                    delete_with_sidecar(image_path, prefer_trash=True)
                except Exception:
                    try:
                        from utils.file.file_utils import delete_with_sidecar
                        delete_with_sidecar(image_path, prefer_trash=False)
                    except Exception:
                        pass
                try:
                    if os.path.exists(image_path):
                        NotificationManager.instance().show_warning("错误", "删除失败：文件仍存在（可能被占用）")
                        return
                except Exception:
                    pass
                try:
                    self._safe_rmdir_empty(os.path.dirname(str(image_path or "")), root_limit=root_dir)
                except Exception:
                    pass
            
            # 2. 从数据库删除 (总是执行，清理记录)
            uuid_to_delete = None
            try:
                for img in (self.image_files or []):
                    if not isinstance(img, dict):
                        continue
                    p = img.get("path") or img.get("file_path") or img.get("filepath")
                    if not p:
                        continue
                    if self._normalize_path_key(p) == target_key:
                        uuid_to_delete = img.get("uuid")
                        break
            except Exception:
                uuid_to_delete = None
            if not uuid_to_delete:
                try:
                    rec = self.db.get_result_by_path(image_path, table_name="bird_results")
                except Exception:
                    rec = None
                if isinstance(rec, dict):
                    uuid_to_delete = rec.get("uuid")
            if uuid_to_delete:
                try:
                    self.db.delete_result_by_uuid(str(uuid_to_delete), table_name="bird_results")
                except Exception:
                    pass

            # 3. 删除本地缩略图缓存（内存缓存和磁盘缓存）
            try:
                # 删除内存缓存
                if hasattr(self, "cache_manager") and self.cache_manager:
                    self.cache_manager.invalidate(image_path)
            except Exception:
                pass
            try:
                # 删除磁盘缓存
                from cache.thumbnail_disk_cache import ThumbnailDiskCache
                disk_cache = ThumbnailDiskCache(self.cache_manager, scope="library")
                disk_cache.invalidate_file(image_path)
            except Exception:
                pass

            # 4. 从内存列表中移除 (通过路径匹配)
            def _keep_img(img):
                try:
                    if not isinstance(img, dict):
                        return True
                    if uuid_to_delete and img.get("uuid") and str(img.get("uuid")) == str(uuid_to_delete):
                        return False
                    p = img.get('path') or img.get('file_path') or img.get('filepath')
                    if not p:
                        return True
                    return self._normalize_path_key(p) != target_key
                except Exception:
                    return True
            try:
                self.image_files = [img for img in (self.image_files or []) if _keep_img(img)]
            except Exception:
                pass
            try:
                self.raw_image_files = [img for img in (self.raw_image_files or []) if _keep_img(img)]
            except Exception:
                pass
            
            try:
                if getattr(self, "current_preview_path", None) and self._normalize_path_key(str(getattr(self, "current_preview_path", "") or "")) == target_key:
                    self.clear_preview()
            except Exception:
                pass
            self.update_thumbnails()
            try:
                if hasattr(self, "folder_panel") and self.folder_panel is not None:
                    self.folder_panel.refresh_tree(root_path=root_dir)
            except Exception:
                pass
                
            NotificationManager.instance().show_toast("删除成功")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"删除失败: {e}")

    def show_image_properties(self, image_path):
        """显示图片属性"""
        try:
            from datetime import datetime
            file_stat = os.stat(image_path)
            size = file_stat.st_size
            create_time = datetime.fromtimestamp(file_stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
            modify_time = datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            # 获取图片尺寸
            from PyQt6.QtGui import QImageReader
            from utils.system.stderr_suppressor import suppress_stderr_fd

            with suppress_stderr_fd():
                reader = QImageReader(image_path)
                img_size = reader.size()
            info_text = f"""文件名: {os.path.basename(image_path)}

路径: {image_path}

大小: {size / 1024 / 1024:.2f} MB ({size} 字节)

尺寸: {img_size.width()} × {img_size.height()}

创建时间: {create_time}

修改时间: {modify_time}"""
            NotificationManager.instance().show_info("图片属性", info_text)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"无法获取属性: {e}")

    def on_new_folder_clicked(self):
        """新建文件夹"""
        try:
            if str(getattr(self, "current_folder_path", "") or "").startswith("virtual://taxonomy"):
                if self.get_selected_files():
                    self.edit_species_for_selection()
                else:
                    NotificationManager.instance().show_toast("虚拟分类模式下请先选中图片，再进行分类/新建")
                return
        except Exception:
            pass
        self.folder_panel.create_new_folder()

    def on_rename_clicked(self):
        """重命名按钮点击"""
        selected_files = self.get_selected_files()
        if selected_files:
            # 选中了图片 (单选或多选都走批量流程)
            self.batch_rename_images(selected_files)
        else:
            try:
                if str(getattr(self, "current_folder_path", "") or "").startswith("virtual://taxonomy"):
                    self.rename_current_taxonomy_node()
                    return
            except Exception:
                pass
            self.folder_panel.rename_folder()

    def on_delete_clicked(self):
        """删除按钮点击"""
        selected_files = self.get_selected_files()
        if not selected_files:
            try:
                if str(getattr(self, "current_folder_path", "") or "").startswith("virtual://taxonomy"):
                    self.clear_current_taxonomy_node()
                    return
            except Exception:
                pass
            self.folder_panel.delete_folder()
            return
            
        # 删除选中的图片
        # 获取上次的删除选择状态
        delete_local_key = "library/delete_local_file_enabled"
        def _to_bool(v, default=True):
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(int(v))
            try:
                s = str(v).strip().lower()
            except Exception:
                return bool(default)
            if s in ("1", "true", "yes", "y", "on"):
                return True
            if s in ("0", "false", "no", "n", "off", ""):
                return False
            return bool(default)
        
        confirmed, delete_local = NotificationManager.instance().ask_confirmation(
            "确认删除",
            f"确定要删除选中的 {len(selected_files)} 个文件吗？",
            show_checkbox=True,
            checkbox_text="同时删除本地磁盘文件",
            default_checked=_to_bool(self.settings_manager.get(delete_local_key, True), default=True)
        )

        try:
            self.settings_manager.set(delete_local_key, delete_local)
            self.settings_manager.sync()
        except Exception:
            pass

        if not confirmed:
            return

        deleted_paths = []
        deleted_uuids = []
        failed_paths = []
        for file_info in selected_files:
             try:
                image_path = file_info['path']
                # 1. 删除本地文件 (如果勾选)
                if delete_local and os.path.exists(image_path):
                    try:
                        from utils.file.file_utils import delete_with_sidecar
                        delete_with_sidecar(image_path, prefer_trash=True)
                    except Exception:
                        try:
                            from utils.file.file_utils import delete_with_sidecar
                            delete_with_sidecar(image_path, prefer_trash=False)
                        except Exception:
                            pass
                    try:
                        if os.path.exists(image_path):
                            failed_paths.append(str(image_path))
                            continue
                    except Exception:
                        pass
                
                # 2. 从数据库删除 (总是执行，清理记录)
                try:
                    u = file_info.get("uuid")
                except Exception:
                    u = None
                if not u:
                    try:
                        rec = self.db.get_result_by_path(image_path, table_name="bird_results")
                    except Exception:
                        rec = None
                    if isinstance(rec, dict):
                        u = rec.get("uuid")
                if u:
                    deleted_uuids.append(str(u))
                deleted_paths.append(image_path)
             except Exception as e:
                      try:
                          LogManager.instance().warning(f"删除失败 {file_info.get('name', '')}: {e}")
                      except Exception:
                          pass

        if deleted_uuids:
            try:
                self.db.delete_results_by_uuids(list(deleted_uuids), table_name="bird_results")
            except Exception:
                pass

        # 删除本地缩略图缓存（内存缓存和磁盘缓存）
        if deleted_paths:
            try:
                # 删除内存缓存
                if hasattr(self, "cache_manager") and self.cache_manager:
                    self.cache_manager.invalidate_many(deleted_paths)
            except Exception:
                pass
            try:
                # 删除磁盘缓存
                from cache.thumbnail_disk_cache import ThumbnailDiskCache
                disk_cache = ThumbnailDiskCache(self.cache_manager, scope="library")
                disk_cache.invalidate_many(deleted_paths)
            except Exception:
                pass

         # 从内存列表中移除
        if deleted_paths:
            try:
                deleted_keys = {self._normalize_path_key(p) for p in (deleted_paths or []) if p}
            except Exception:
                deleted_keys = set(deleted_paths or [])
            def _keep_img2(img):
                try:
                    if not isinstance(img, dict):
                        return True
                    if deleted_uuids and img.get("uuid") and str(img.get("uuid")) in set(deleted_uuids):
                        return False
                    p = img.get('path') or img.get('file_path') or img.get('filepath')
                    if not p:
                        return True
                    return self._normalize_path_key(p) not in deleted_keys
                except Exception:
                    return True
            try:
                self.image_files = [img for img in (self.image_files or []) if _keep_img2(img)]
            except Exception:
                pass
            try:
                self.raw_image_files = [img for img in (self.raw_image_files or []) if _keep_img2(img)]
            except Exception:
                pass
            
            try:
                if getattr(self, "current_preview_path", None):
                    pk = self._normalize_path_key(str(getattr(self, "current_preview_path", "") or ""))
                    if pk in deleted_keys:
                        self.clear_preview()
            except Exception:
                pass
            self.update_thumbnails()
            try:
                if failed_paths:
                    NotificationManager.instance().show_warning("提示", f"删除完成：成功 {len(deleted_paths)} 个，失败 {len(failed_paths)} 个（文件可能被占用）")
                else:
                    NotificationManager.instance().show_toast(f"成功删除 {len(deleted_paths)} 个文件")
            except Exception:
                pass
        # else:
            # 删除当前文件夹
            # if self.current_folder_path:
            #     self.delete_current_folder()


    def on_background_context_menu(self, position):
        """背景右键菜单"""
        if self._is_unclassified_context():
            return
        menu = QMenu(self)
        cm = ColorManager.instance()
        menu_bg = cm.get("theme.background.light")
        menu_border = cm.get("popup.border.primary")
        menu_text = cm.get("theme.text.dark")
        menu_hover = cm.get("theme.background.dark")
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {menu_bg};
                border: 1px solid {menu_border};
                padding: 2px;
            }}
            QMenu::item {{
                padding: 4px 20px 4px 30px;
                border: none;
                color: {menu_text};
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
                color: {menu_text};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {menu_border};
                margin: 2px 4px;
            }}
        """)
        
        # 新建文件夹
        new_folder_action = menu.addAction(qta.icon('mdi6.folder-plus', color='#555'), "新建文件夹")
        new_folder_action.triggered.connect(self.on_new_folder_clicked)
        
        menu.addSeparator()
        
        # 如果没有选中图片，显示文件夹操作
        if self.get_selected_count() == 0:
            rename_action = menu.addAction(qta.icon('mdi6.rename-box', color='#555'), "重命名当前文件夹")
            rename_action.triggered.connect(self.on_rename_clicked)
            
            delete_action = menu.addAction(qta.icon('mdi6.trash-can-outline', color='#e74c3c'), "删除当前文件夹")
            delete_action.triggered.connect(self.on_delete_clicked)
            
            menu.addSeparator()
            # 在文件管理器中打开
            open_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "在文件管理器中打开")
            open_action.triggered.connect(lambda: self.folder_panel.open_in_explorer(self.current_folder_path))
        else:
             # 如果有选中图片，可以显示一些批量操作，或者取消选择
             clear_selection_action = menu.addAction("取消选择")
             clear_selection_action.triggered.connect(lambda: self.on_thumbnail_clicked(-1, Qt.KeyboardModifier.NoModifier)) # Hacky way to clear? No on_thumbnail_clicked expects index.
             # Better way to clear selection:
             # for t in self.thumbnails: t.set_selected(False)
             # But let's just leave it simple for now.
             
        menu.exec(self.grid_view.mapToGlobal(position))

    def on_thumbnail_size_changed(self, value):
        """当滑块值改变时调整缩略图大小"""
        self._pending_thumb_size = self.calculate_thumb_size(value)
        try:
            if hasattr(self, "right_content_container") and self.right_content_container is not None:
                w = int(self._pending_thumb_size[0]) if isinstance(self._pending_thumb_size, (tuple, list)) else int(self._pending_thumb_size)
                self.right_content_container.setMinimumWidth(max(0, w + 40))
        except Exception:
            pass
        try:
            if hasattr(self, "resize_timer") and self.resize_timer.isActive():
                self.resize_timer.stop()
        except Exception:
            pass
        if getattr(self, "_is_slider_dragging", False):
            try:
                self.current_thumb_size = self._pending_thumb_size
            except Exception:
                pass
            try:
                self.grid_view.set_thumbnail_size(
                    self.current_thumb_size,
                    scale_visible_only=True,
                    extra_rows=2,
                )
            except Exception:
                pass
            return
        self._perform_resize()

    def _perform_resize(self):
        """执行实际的调整大小操作"""
        if not hasattr(self, '_pending_thumb_size'):
            return

        try:
            self._suppress_max_thumb_recalc = True
            def _unset():
                try:
                    self._suppress_max_thumb_recalc = False
                except Exception:
                    pass
            QTimer.singleShot(150, _unset)
        except Exception:
            pass
            
        # 保存设置 (仅当设置已加载完成且不是初始化阶段)
        if hasattr(self, 'preview_slider') and getattr(self, '_settings_loaded', False):
            self.settings_manager.set("library/thumbnail_size", self.preview_slider.value())

        self.current_thumb_size = self._pending_thumb_size
        try:
            if hasattr(self, "right_content_container") and self.right_content_container is not None:
                w = int(self.current_thumb_size[0]) if isinstance(self.current_thumb_size, (tuple, list)) else int(self.current_thumb_size)
                self.right_content_container.setMinimumWidth(max(0, w + 40))
        except Exception:
            pass
        
        # 强制全量刷新尺寸
        # 用户反馈：第一次进入大缩略图模式时，首屏图片模糊（未重新加载高清图），往下滚才清晰
        # 原因：scale_visible_only=True/False 只是设置了 widget size，但如果没有触发 scroll 事件，
        # Loader 可能认为当前缓存的图片（低分）仍然有效，或者 visible range 计算有误导致未触发 reload。
        # 修复：强制 scale_visible_only=False，并强制刷新可见区域
        
        self.grid_view.set_thumbnail_size(
            self.current_thumb_size,
            scale_visible_only=False, # 强制全量更新布局
            extra_rows=2
        )
        
        if not self._is_slider_dragging:
            try:
                # 先清除所有请求记录和过期标记
                self._requested_paths = set()
                self._thumbnail_request_id += 1  # 增加请求ID，确保loader使用新的ID
                
                # 关键：同步更新 thumbnail_loader 的 active_request_id
                try:
                    self.thumbnail_loader.set_active_request_id(self._thumbnail_request_id)
                except Exception:
                    pass
                
                start, end, _ = self.grid_view.get_visible_index_range(extra_rows=2)
                # 标记所有可见缩略图为过期，强制重新请求图片
                for i in range(max(0, start), min(len(self.grid_view.thumbnails), end + 1)):
                    thumb = self.grid_view.thumbnails[i]
                    try:
                        thumb._stale_thumbnail = True
                    except Exception:
                        pass
                    # 清除缩略图数据，强制重新加载
                    try:
                        thumb.thumbnail_pixmap = None
                        thumb._thumbnail_image = None
                    except Exception:
                        pass
                
                # 强制触发滚动事件，Loader 会检查 visible range 并重新加载过期/未加载的图片
                self.on_scroll_value_changed(self.grid_view.scroll_area.verticalScrollBar().value())
            except Exception as e:
                print(f"[ERROR] _perform_resize loading failed: {e}")
                import traceback
                traceback.print_exc()
        
        # 缩略图大小改变后，可能需要加载更多才能填满屏幕
        if self.is_lazy_loading and not self._is_slider_dragging:
            self.load_more_thumbnails()
        if self._pending_splitter_update:
            self._pending_splitter_update = False
            self.update_preview_image_size()

    def on_view_mode_changed(self, index):
        """切换显示模式"""
        self.display_mode = index  # 更新显示模式
        
        # 重新计算尺寸（因为不同模式最小尺寸不同）
        self.current_thumb_size = self.calculate_thumb_size(self.preview_slider.value())

        self.grid_view.set_display_mode(index)
        self.grid_view.set_thumbnail_size(self.current_thumb_size)
        try:
            self._requested_paths = set()
            self.on_scroll_value_changed(self.grid_view.scroll_area.verticalScrollBar().value())
        except Exception:
            pass

    def update_preview_image_size(self):
        """根据预览区大小调整图片显示"""
        if hasattr(self, 'preview_panel'):
            self.preview_panel.update_image_size()

    def preview_image_file(self, image_path):
        """在预览区显示图片"""
        self.current_preview_path = image_path
        if hasattr(self, 'preview_panel'):
            self.preview_panel.load_image(image_path)
        
        # 同步收藏状态
        is_fav = False
        img_key = self._normalize_path_key(image_path) if image_path else ""
        img_info = next((img for img in self.image_files if self._normalize_path_key(img.get('path')) == img_key), None)
        if not img_info:
            img_info = next((img for img in self.raw_image_files if self._normalize_path_key(img.get('path')) == img_key), None)
        if not img_info:
            img_info = next((img for img in getattr(self, 'all_image_files', []) if self._normalize_path_key(img.get('path')) == img_key), None)
        if img_info:
            is_fav = bool(img_info.get('is_favorite', 0))
        
        # 更新预览面板按钮
        if hasattr(self, 'preview_panel'):
            self.preview_panel.set_favorite(is_fav)

        # 更新信息树
        if hasattr(self, 'info_panel'):
            self.info_panel.update_info(image_path)
            try:
                if hasattr(self, "preview_info_splitter") and self.preview_info_splitter is not None:
                    sizes = self.preview_info_splitter.sizes()
                    if isinstance(sizes, (list, tuple)) and len(sizes) >= 2:
                        if int(sizes[1]) < 60:
                            total = int(sizes[0]) + int(sizes[1])
                            new_info = min(180, max(100, total // 6))
                            self.preview_info_splitter.setSizes([max(1, total - new_info), new_info])
            except Exception:
                pass
            
        # 同步评分状态
        rating = 0
        if img_info:
            rating = img_info.get('rating', 0)
        
        # 更新预览面板评分
        if hasattr(self, 'preview_panel'):
            self.preview_panel.set_rating(rating)
            
        # 同步色标状态
        label = ""
        if img_info:
            label = img_info.get('label', "")
            
        if hasattr(self, 'preview_panel'):
            self.preview_panel.set_label(label)
            try:
                if hasattr(self.preview_panel, "set_overlays"):
                    bbox = None
                    focus_point = None
                    eye_coordinates = None
                    orig_size = None
                    fdj = None
                    if isinstance(img_info, dict):
                        try:
                            bbox = img_info.get("bbox")
                        except Exception:
                            bbox = None
                        try:
                            focus_point = img_info.get("focus_point")
                        except Exception:
                            focus_point = None
                        try:
                            eye_coordinates = img_info.get("eye_coordinates")
                        except Exception:
                            eye_coordinates = None
                        try:
                            w0 = img_info.get("width")
                            h0 = img_info.get("height")
                            if w0 and h0:
                                orig_size = (int(w0), int(h0))
                        except Exception:
                            orig_size = None
                        try:
                            raw_fdj = img_info.get("focus_detect_json")
                            if isinstance(raw_fdj, str) and raw_fdj.strip():
                                raw_fdj = json.loads(raw_fdj)
                            if isinstance(raw_fdj, dict):
                                fdj = raw_fdj
                        except Exception:
                            fdj = None

                    if (bbox is None or focus_point is None or eye_coordinates is None) and fdj is None:
                        rec = None
                        uuid_val = ""
                        try:
                            uuid_val = str((img_info or {}).get("uuid") or "").strip()
                        except Exception:
                            uuid_val = ""
                        if uuid_val:
                            try:
                                rec = self.db.get_result_by_uuid(uuid_val, table_name="bird_results")
                            except Exception:
                                rec = None
                        if rec is None:
                            try:
                                from utils.file.file_util import get_fast_id
                                fid = ""
                                try:
                                    fid = str((img_info or {}).get("fast_id") or "").strip()
                                except Exception:
                                    fid = ""
                                if not fid:
                                    fid = str(get_fast_id(str(image_path or "")) or "").strip()
                                if fid:
                                    rec = self.db.get_result_by_fast_id(fid, table_name="bird_results")
                                    if isinstance(rec, dict):
                                        try:
                                            if img_info is not None and not uuid_val:
                                                rec_uuid = str(rec.get("uuid") or "").strip()
                                                if rec_uuid:
                                                    img_info["uuid"] = rec_uuid
                                        except Exception:
                                            pass
                            except Exception:
                                rec = None
                        if isinstance(rec, dict):
                            try:
                                if bbox is None:
                                    bbox = rec.get("bbox")
                            except Exception:
                                pass
                            try:
                                if focus_point is None:
                                    focus_point = rec.get("focus_point")
                            except Exception:
                                pass
                            try:
                                if eye_coordinates is None:
                                    eye_coordinates = rec.get("eye_coordinates")
                            except Exception:
                                pass
                            try:
                                raw_fdj = rec.get("focus_detect_json")
                                if isinstance(raw_fdj, str) and raw_fdj.strip():
                                    raw_fdj = json.loads(raw_fdj)
                                if isinstance(raw_fdj, dict):
                                    fdj = raw_fdj
                            except Exception:
                                fdj = None

                    if isinstance(fdj, dict):
                        if bbox is None:
                            try:
                                bbox = fdj.get("bbox_orig") or fdj.get("bbox")
                            except Exception:
                                pass
                        if focus_point is None:
                            try:
                                focus_point = fdj.get("focus_point")
                            except Exception:
                                focus_point = focus_point
                        if eye_coordinates is None:
                            try:
                                eye_coordinates = fdj.get("eye_coordinates") or fdj.get("eye")
                            except Exception:
                                eye_coordinates = eye_coordinates
                        try:
                            ow = fdj.get("orig_w")
                            oh = fdj.get("orig_h")
                            if ow and oh:
                                orig_size = (int(ow), int(oh))
                        except Exception:
                            orig_size = orig_size
                    self.preview_panel.set_overlays(bbox=None, focus_point=focus_point, eye_coordinates=eye_coordinates, orig_size=orig_size)
            except Exception:
                pass

    def apply_quick_filters(self):
        """应用快速过滤 (收藏/评分)"""
        if not self.raw_image_files:
            self.image_files = []
            self.update_thumbnails()
            return

        filtered_files = self.raw_image_files

        # 1. 收藏过滤
        if self.favorite_filter:
            filtered_files = [img for img in filtered_files if img.get('is_favorite')]

        # 2. 评分过滤
        mode = self.rating_filter_btn.get_mode()
        if self.rating_filter > 0:
            if mode == "=":
                filtered_files = [img for img in filtered_files if img.get('rating', 0) == self.rating_filter]
            elif mode == "≥":
                filtered_files = [img for img in filtered_files if img.get('rating', 0) >= self.rating_filter]
            elif mode == "≤":
                filtered_files = [img for img in filtered_files if img.get('rating', 0) <= self.rating_filter]

        self.image_files = filtered_files
        
        # 更新状态栏或通知
        if self.favorite_filter or self.rating_filter > 0:
            try:
                LogManager.instance().debug(
                    f"[Filter] Applied filters: Fav={self.favorite_filter}, Rating {mode if self.rating_filter > 0 else ''} {self.rating_filter}. "
                    f"Result: {len(self.image_files)}/{len(self.raw_image_files)}"
                )
            except Exception:
                pass
        
        # 刷新显示
        self.update_thumbnails()

    def on_rating_operator_changed(self):
        """评分比较操作符改变"""
        self.apply_quick_filters()

    def on_fav_toggled(self, checked):
        """工具栏收藏按钮切换 (作为过滤器)"""
        # 更新过滤状态
        self.favorite_filter = checked
        
        # Update icon immediately for visual feedback
        if checked:
            self.fav_btn.setIcon(qta.icon('mdi6.heart', color='#e74c3c', options=[{'scale_factor': 1.1}]))
        else:
            self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
            
        # 应用过滤
        self.apply_quick_filters()

    def toggle_favorite_selection(self, is_favorite):
        """批量设置选中图片的收藏状态"""
        selected_files = self.get_selected_files()
        
        # 如果没有选中文件，但在预览模式下，尝试操作当前预览图片
        if not selected_files and self.current_preview_path:
             for img in self.image_files:
                 if img['path'] == self.current_preview_path:
                     selected_files = [img]
                     break
        
        if not selected_files:
            return

        file_paths = [f['path'] for f in selected_files]
        self._perform_favorite_update(file_paths, is_favorite)

    def on_preview_fav_toggled(self, is_favorite):
        """预览面板收藏状态改变"""
        image_path = self.preview_panel.current_image_path
        if not image_path:
            return
        self._perform_favorite_update([image_path], is_favorite)

    def _perform_favorite_update(self, file_paths, is_favorite):
        """执行收藏更新核心逻辑"""
        if not file_paths:
            return

        fav_val = 1 if is_favorite else 0
        target_keys = {self._normalize_path_key(p) for p in file_paths if p}
        
        # 构造带有分类信息的列表，用于数据库更新
        # 这样如果数据库中没有该图片记录，插入时可以带上分类信息，避免排序问题
        files_data = []
        for path in file_paths:
            # 查找当前内存中的图片信息
            p_key = self._normalize_path_key(path)
            img_info = next((img for img in self.raw_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if not img_info:
                img_info = next((img for img in self.image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if not img_info:
                img_info = next((img for img in self.all_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if img_info:
                files_data.append({
                    'path': path,
                    'order': img_info.get('order'),
                    'family': img_info.get('family'),
                    'genus': img_info.get('genus'),
                    'species': img_info.get('species')
                })
            else:
                files_data.append(path)

        # 1. 后台更新 DB 和 EXIF
        def run_background_update():
            # DB Update
            db_task_id = StatusManager.instance().start_task(f"正在{'收藏' if is_favorite else '取消收藏'} (写入数据库)...")
            try:
                self.db.update_favorite_batch(files_data, fav_val)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"DB Update failed: {e}")
                except Exception:
                    pass
                try:
                    msg = str(e)
                    QTimer.singleShot(0, lambda m=msg: NotificationManager.instance().show_warning("错误", f"写入数据库失败: {m}"))
                except Exception:
                    pass
            finally:
                StatusManager.instance().finish_task(db_task_id)

            # EXIF Update
            tags = {EXIF_TAG.Favorite.value: "True" if is_favorite else "False"}
            exif_tasks = [(path, tags) for path in file_paths]
            
            task_id = StatusManager.instance().start_task(f"正在{'收藏' if is_favorite else '取消收藏'} (写入元数据)...")
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
            finally:
                StatusManager.instance().finish_task(task_id)

        threading.Thread(target=run_background_update, daemon=True).start()
        
        # 2. 更新内存和 UI (乐观更新)
        files_set = set(file_paths)
        
        # Update raw_image_files (Source of Truth)
        for img in self.raw_image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['is_favorite'] = fav_val
        for img in self.image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['is_favorite'] = fav_val
        for img in self.all_image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['is_favorite'] = fav_val
        
        # 优化：如果是 "显示全部" 或者操作后无需移除项目，则只刷新 UI 不重载
        should_reload = False
        
        # 如果当前只显示收藏，且执行了取消收藏，则必须重载以移除项目
        if self.favorite_filter and not is_favorite:
            should_reload = True
            
        if should_reload:
            self.apply_quick_filters()
        else:
            # 仅刷新受影响的缩略图（避免闪烁）
            self.grid_view.refresh_specific_thumbnails(file_paths)
            
        try:
            if hasattr(self, 'preview_panel') and self._normalize_path_key(self.preview_panel.current_image_path) in target_keys:
                self.preview_panel.set_favorite(is_favorite)
        except Exception:
            pass
        
        # 刷新信息面板（如果当前选中的图片被修改）
        try:
            selected = self.get_selected_files()
            if selected and self._normalize_path_key(selected[0]['path']) in target_keys:
                record = self.db.get_result_by_path(selected[0]['path'], table_name='bird_results')
                io_data = {"record": record} if record else None
                self.info_panel.update_info(selected[0]['path'], io_data=io_data)
        except Exception:
            pass
             
        # 4. 预加载
        if is_favorite:
            self.cache_manager.preload(file_paths, 'fav', priority=ImageCacheManager.PRIORITY_FAV)
            
        # 5. 通知
        status = "已收藏" if is_favorite else "已取消收藏"
        # if len(file_paths) > 1:
        #     NotificationManager.instance().show_toast(f"{status} {len(file_paths)} 张图片")
        # else:
        #     NotificationManager.instance().show_toast(status)

    def set_rating_selection(self, rating):
        """设置选中图片的评分"""
        selected_files = self.get_selected_files()
        if not selected_files:
            return
            
        file_paths = [f['path'] for f in selected_files]
        self._perform_rating_update(file_paths, rating)

    def set_label_selection(self, label):
        """设置选中图片的色标"""
        selected_files = self.get_selected_files()
        if not selected_files:
            return
            
        file_paths = [f['path'] for f in selected_files]
        self._perform_label_update(file_paths, label)

    def _perform_label_update(self, file_paths, label):
        """执行色标更新核心逻辑"""
        if not file_paths:
            return

        try:
            LogManager.instance().info(f"[Label] Updating {len(file_paths)} files to label={label}")
        except Exception:
            pass
        target_keys = {self._normalize_path_key(p) for p in file_paths if p}
        
        # 1. 更新数据库
        # 构造带有分类信息的列表，用于数据库更新
        files_data = []
        for path in file_paths:
            # 查找当前内存中的图片信息 (优先从 raw_image_files 找)
            p_key = self._normalize_path_key(path)
            img_info = next((img for img in self.raw_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if not img_info:
                 # Fallback to image_files just in case
                 img_info = next((img for img in self.image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            
            if img_info:
                files_data.append({
                    'path': path,
                    'order': img_info.get('order'),
                    'family': img_info.get('family'),
                    'genus': img_info.get('genus'),
                    'species': img_info.get('species')
                })
            else:
                files_data.append(path)

        # 1. 后台更新 DB 和 EXIF
        def run_background_update():
            # DB Update
            db_task_id = StatusManager.instance().start_task("正在更新色标 (写入数据库)...")
            try:
                self.db.update_label_batch(files_data, label)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"DB Update failed: {e}")
                except Exception:
                    pass
                try:
                    msg = str(e)
                    QTimer.singleShot(0, lambda m=msg: NotificationManager.instance().show_warning("错误", f"写入数据库失败: {m}"))
                except Exception:
                    pass
            finally:
                StatusManager.instance().finish_task(db_task_id)

            # EXIF Update
            tags = {EXIF_TAG.Label.value: label}
            exif_tasks = [(path, tags) for path in file_paths]
            
            task_id = StatusManager.instance().start_task(f"正在更新色标 (写入元数据)...")
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
            finally:
                StatusManager.instance().finish_task(task_id)

        threading.Thread(target=run_background_update, daemon=True).start()
        
        # 2. 更新内存和 UI (乐观更新)
        files_set = set(file_paths)
        
        # Update raw_image_files (Source of Truth)
        for img in self.raw_image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['label'] = label
        for img in self.image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['label'] = label
        for img in self.all_image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['label'] = label
        
        # 刷新受影响的缩略图
        if hasattr(self, 'grid_view'):
            self.grid_view.refresh_specific_thumbnails(file_paths)

        try:
            if getattr(self, "current_preview_path", None) and self._normalize_path_key(self.current_preview_path) in target_keys:
                if hasattr(self, 'preview_panel'):
                    self.preview_panel.set_label(label)
        except Exception:
            pass
        
        # 刷新信息面板（如果当前选中的图片被修改）
        try:
            selected = self.get_selected_files()
            if selected and self._normalize_path_key(selected[0]['path']) in target_keys:
                record = self.db.get_result_by_path(selected[0]['path'], table_name='bird_results')
                io_data = {"record": record} if record else None
                self.info_panel.update_info(selected[0]['path'], io_data=io_data)
        except Exception:
            pass
        
        NotificationManager.instance().show_toast(f"已更新 {len(file_paths)} 张图片的色标")

    def on_preview_rating_changed(self, rating):
        """预览面板评分改变"""
        image_path = self.preview_panel.current_image_path
        if not image_path:
            return
        self._perform_rating_update([image_path], rating)

    def on_preview_label_changed(self, label):
        """预览面板色标改变"""
        image_path = self.preview_panel.current_image_path
        if not image_path:
            return
        self._perform_label_update([image_path], label)

    def on_toolbar_rating_changed(self, rating):
        """工具栏评分控件改变 (作为过滤器)"""
        # 更新过滤状态
        self.rating_filter = rating
        
        # 应用过滤
        self.apply_quick_filters()

    def on_spray_mode_changed(self, active, action_type, value):
        """喷漆模式改变"""
        if hasattr(self, 'grid_view'):
            self.grid_view.set_spray_mode(active, action_type, value)
        if self._spray_exit_shortcut:
            self._spray_exit_shortcut.setEnabled(bool(active))

    def on_spray_cancel_requested(self):
        if hasattr(self, "toolbar") and self.toolbar:
            try:
                self.toolbar.deactivate_spray_mode()
                return
            except Exception:
                pass
        if hasattr(self, 'grid_view'):
            self.grid_view.set_spray_mode(False, "", None)

    def on_spray_action_requested(self, action_type, value, indices):
        """处理喷漆操作"""
        file_paths = []
        for index in indices:
            if 0 <= index < len(self.image_files):
                file_paths.append(self.image_files[index]['path'])
                
        if not file_paths:
            return
            
        if action_type == 'favorite':
            self._perform_favorite_update(file_paths, value)
        elif action_type == 'label':
            self._perform_label_update(file_paths, value)
        elif action_type == 'rating':
            self._perform_rating_update(file_paths, value)
        elif action_type == 'tag':
            self._perform_tag_update(file_paths, value)

    def _perform_tag_update(self, file_paths, tag_data):
        """执行标签更新核心逻辑 (支持追加/覆盖模式)"""
        if not file_paths:
            return

        # 解析 tag_data
        new_tags_str = ""
        mode = "append" # default

        if isinstance(tag_data, dict):
            new_tags_str = tag_data.get('tags', '')
            mode = tag_data.get('mode', 'append')
        else:
            # 兼容旧代码：直接传字符串则默认为追加单个标签
            new_tags_str = str(tag_data)
            mode = "append"

        # 如果是覆盖模式且标签为空，则表示清除标签
        if mode == 'overwrite' and not new_tags_str:
            try:
                LogManager.instance().info(f"[Tag] Clearing tags for {len(file_paths)} files")
            except Exception:
                pass
        elif not new_tags_str and mode == 'append':
            # 追加空标签无意义
            return
        else:
            try:
                LogManager.instance().info(f"[Tag] Updating {len(file_paths)} files: tags='{new_tags_str}', mode='{mode}'")
            except Exception:
                pass
        
        # 准备任务：计算每个文件的新标签字符串
        tasks = [] # (path, final_tags_str)
        
        # 预处理新标签列表
        new_tags_list = [t.strip() for t in new_tags_str.split('|') if t.strip()]
        
        for path in file_paths:
            p_key = self._normalize_path_key(path)
            # 查找图片信息
            img_info = next((img for img in self.raw_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if not img_info:
                img_info = next((img for img in self.image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if not img_info:
                img_info = next((img for img in self.all_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            
            final_str = ""
            
            if mode == 'overwrite':
                # 覆盖模式：直接使用新标签列表
                final_str = "|".join(sorted(new_tags_list))
            else:
                # 追加模式：合并现有标签和新标签
                current_tags_str = img_info.get('tags', '') if img_info else ''
                if current_tags_str is None:
                    current_tags_str = ''
                
                current_list = [t.strip() for t in current_tags_str.split('|') if t.strip()]
                
                # 使用集合去重，但保持排序
                merged_set = set(current_list)
                for t in new_tags_list:
                    merged_set.add(t)
                
                final_str = "|".join(sorted(list(merged_set)))

            # 只有当标签发生变化时才添加任务
            old_str = img_info.get('tags', '') if img_info else ''
            if old_str is None: old_str = ''
            
            # 简单比较字符串可能不准（顺序不同），但上面我们已经sort过了，或者至少final_str是新的
            # 为了准确，比较排序后的列表
            old_list = sorted([t.strip() for t in old_str.split('|') if t.strip()])
            new_list = sorted([t.strip() for t in final_str.split('|') if t.strip()])
            
            if old_list != new_list:
                tasks.append((path, final_str))
        
        if not tasks:
            return

        # 确保新标签已保存到本地记录 (TagManager)
        from utils.tag_manager import TagManager
        for t in new_tags_list:
            TagManager.instance().add_tag(t)

        # 1. 后台更新 DB 和 EXIF
        def run_background_update():
            # DB Update (由于每个文件的标签结果可能不同，需要逐个更新或分批更新)
            try:
                # 优化：按 final_tags_str 分组
                groups = {}
                for path, t_str in tasks:
                    if t_str not in groups:
                        groups[t_str] = []
                    groups[t_str].append(path)
                
                for t_str, paths in groups.items():
                    # 构造 files_data 用于 update_tags_batch
                    files_data = []
                    for path in paths:
                        p_key = self._normalize_path_key(path)
                        img_info = next((img for img in self.raw_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
                        if not img_info:
                             img_info = next((img for img in self.image_files if self._normalize_path_key(img.get('path')) == p_key), None)
                        if not img_info:
                             img_info = next((img for img in self.all_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
                        
                        if img_info:
                            files_data.append({
                                'path': path,
                                'order': img_info.get('order'),
                                'family': img_info.get('family'),
                                'genus': img_info.get('genus'),
                                'species': img_info.get('species')
                            })
                        else:
                            files_data.append(path)

                    self.db.update_tags_batch(files_data, t_str)
                    
            except Exception as e:
                try:
                    LogManager.instance().warning(f"DB Update failed: {e}")
                except Exception:
                    pass

            # EXIF Update
            exif_tasks = []
            for path, t_str in tasks:
                exif_tasks.append((path, {EXIF_TAG.Tags.value: t_str}))
            
            task_id = StatusManager.instance().start_task(f"正在更新标签 (写入元数据)...")
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
            finally:
                StatusManager.instance().finish_task(task_id)

        threading.Thread(target=run_background_update, daemon=True).start()
        
        # 2. 更新内存和 UI (乐观更新)
        target_keys = {self._normalize_path_key(p) for p, _ in tasks}
        updates_map = {self._normalize_path_key(p): t_str for p, t_str in tasks}
        
        for img_list in [self.raw_image_files, self.image_files, self.all_image_files]:
            for img in img_list:
                p_key = self._normalize_path_key(img.get('path'))
                if p_key in target_keys:
                    img['tags'] = updates_map[p_key]
        
        # 仅刷新受影响的缩略图
        self.grid_view.refresh_specific_thumbnails([t[0] for t in tasks])

        NotificationManager.instance().show_toast(f"已更新 {len(tasks)} 张图片的标签")


    def _perform_rating_update(self, file_paths, rating):
        """执行评分更新核心逻辑"""
        if not file_paths:
            return

        try:
            LogManager.instance().info(f"[Rating] Updating {len(file_paths)} files to rating={rating}")
        except Exception:
            pass
        target_keys = {self._normalize_path_key(p) for p in file_paths if p}

        # 构造带有分类信息的列表，用于数据库更新
        files_data = []
        for path in file_paths:
            # 查找当前内存中的图片信息 (优先从 raw_image_files 找)
            p_key = self._normalize_path_key(path)
            img_info = next((img for img in self.raw_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if not img_info:
                 # Fallback to image_files just in case
                 img_info = next((img for img in self.image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            if not img_info:
                 img_info = next((img for img in self.all_image_files if self._normalize_path_key(img.get('path')) == p_key), None)
            
            if img_info:
                files_data.append({
                    'path': path,
                    'order': img_info.get('order'),
                    'family': img_info.get('family'),
                    'genus': img_info.get('genus'),
                    'species': img_info.get('species')
                })
            else:
                files_data.append(path)

        # 1. 后台更新 DB 和 EXIF
        def run_background_update():
            # DB Update
            db_task_id = StatusManager.instance().start_task(f"正在更新评分 (写入数据库)...")
            try:
                self.db.update_rating_batch(files_data, rating)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"DB Update failed: {e}")
                except Exception:
                    pass
                try:
                    msg = str(e)
                    QTimer.singleShot(0, lambda m=msg: NotificationManager.instance().show_warning("错误", f"写入数据库失败: {m}"))
                except Exception:
                    pass
            finally:
                StatusManager.instance().finish_task(db_task_id)

            # EXIF Update
            tags = {EXIF_TAG.Rating.value: str(rating)}
            exif_tasks = [(path, tags) for path in file_paths]
            
            task_id = StatusManager.instance().start_task(f"正在更新评分 (写入元数据)...")
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
            finally:
                StatusManager.instance().finish_task(task_id)

        threading.Thread(target=run_background_update, daemon=True).start()
        
        # 2. 更新内存和 UI (乐观更新)
        files_set = set(file_paths)
        
        # Update raw_image_files (Source of Truth)
        for img in self.raw_image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['rating'] = rating
        for img in self.image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['rating'] = rating
        for img in self.all_image_files:
            if self._normalize_path_key(img.get('path')) in target_keys:
                img['rating'] = rating
        
        # 优化：如果没有启用评分过滤，则不需要重载整个列表
        should_reload = False
        if self.rating_filter > 0:
            should_reload = True
            
        if should_reload:
            self.apply_quick_filters()
        else:
            # 仅刷新受影响的缩略图
            self.grid_view.refresh_specific_thumbnails(file_paths)
        
        # 更新预览面板 (如果当前预览图片被修改)
        try:
            if hasattr(self, 'preview_panel') and self._normalize_path_key(self.preview_panel.current_image_path) in target_keys:
                self.preview_panel.set_rating(rating)
        except Exception:
            pass
        
        # 刷新信息面板（如果当前选中的图片被修改）
        try:
            selected = self.get_selected_files()
            if selected and self._normalize_path_key(selected[0]['path']) in target_keys:
                record = self.db.get_result_by_path(selected[0]['path'], table_name='bird_results')
                io_data = {"record": record} if record else None
                self.info_panel.update_info(selected[0]['path'], io_data=io_data)
        except Exception:
            pass
            
        # 3. 通知
        if len(file_paths) > 1:
            NotificationManager.instance().show_toast(f"已评分 {len(file_paths)} 张图片: {rating}星")
        else:
            NotificationManager.instance().show_toast(f"已评分: {rating}星")

    def toggle_filter_panel(self, checked):
        """切换过滤面板显示"""
        if checked:
            # 计算面板位置（在按钮下方）
            btn_pos = self.filter_btn.mapTo(self, self.filter_btn.rect().bottomLeft())
            # 设置面板宽度和位置
            panel_width = 500 # 加宽以容纳更多控件
            panel_x = btn_pos.x() - panel_width // 2 + self.filter_btn.width() // 2
            # 确保不超出左边界
            panel_x = max(10, panel_x)
            # 确保不超出右边界
            if panel_x + panel_width > self.width():
                panel_x = self.width() - panel_width - 10
                
            self.filter_panel.setFixedWidth(panel_width)
            # 让高度自动适应内容
            self.filter_panel.adjustSize() 
            self.filter_panel.move(panel_x, btn_pos.y() + 2)
            self.filter_panel.show()
            self.filter_panel.raise_()
            # self.filter_input.setFocus() # old
            # 更新图标
            self.filter_btn.setIcon(qta.icon('mdi6.filter', color='#2196f3', options=[{'scale_factor': 1.1}]))
        else:
            self.filter_panel.hide()
            self.filter_btn.setIcon(qta.icon('mdi6.filter-outline', color='#555', options=[{'scale_factor': 1.1}]))
        
        self._update_event_filter_state()

    def _get_global_all_files_base(self):
        root_dir = self.settings_manager.get("general/root_path")
        if not root_dir or not os.path.isdir(root_dir):
            return []

        bird_strict = self.settings_manager.get("setting/bird_strict", True)
        if isinstance(bird_strict, str):
            bird_strict = bird_strict.lower() == 'true'

        root_norm = os.path.normpath(root_dir)
        if (
            self._global_all_base_files is not None
            and self._global_all_base_root == root_norm
            and self._global_all_base_strict == bool(bird_strict)
        ):
            return self._global_all_base_files

        base_list = []
        try:
            rows_full = self.db.query_images_by_taxonomy(unclassified=False, table_name="bird_results", root_path=str(root_dir or ""))
        except Exception:
            rows_full = []
        try:
            rows_un = self.db.query_images_by_taxonomy(unclassified=True, table_name="bird_results", root_path=str(root_dir or ""))
        except Exception:
            rows_un = []
        rows = list(rows_full or []) + list(rows_un or [])
        for row in rows:
            try:
                fpath = str(row["file_path"] or "")
            except Exception:
                fpath = ""
            if not fpath:
                continue
            try:
                if not os.path.exists(fpath):
                    continue
            except Exception:
                pass
            try:
                shot_time = row["shot_time"] or ""
            except Exception:
                shot_time = ""
            try:
                created_at = row["created_at"] or ""
            except Exception:
                created_at = ""
            base_list.append({
                'path': fpath,
                'name': str(row["file_name"] or os.path.basename(fpath)),
                'create_time': str(shot_time or created_at or ""),
                'create_ts': 0.0,
                'shot_time': str(shot_time or ""),
                'shot_ts': 0.0,
                'position': row["position"],
                'score': row["score"],
                'norm_score': row["norm_score"],
                'bbox': row["bbox"] if "bbox" in row.keys() else None,
                'focus_point': row["focus_point"] if "focus_point" in row.keys() else None,
                'focus_detect_json': row["focus_detect_json"] if "focus_detect_json" in row.keys() else '',
                'label': row["label"] or '',
                'order': row["order_cls"] or '',
                'family': row["family_cls"] or '',
                'genus': row["genus_cls"] or '',
                'species': row["species_cls"] or '',
                'is_favorite': row["is_favorite"],
                'rating': row["rating"] or 0,
                'uuid': row["uuid"],
                'fnumber': row["fnumber"],
                'shutter': row["shutter"],
                'iso': row["iso"],
                'focal_length': row["focal_length"],
                'camera_model': row["camera_model"],
                'lens_model': row["lens_model"],
                'description': '',
                'tags': row["tags"] if "tags" in row.keys() else '',
                'location': row["location"] if "location" in row.keys() else '',
            })

        self._global_all_base_root = root_norm
        self._global_all_base_strict = bool(bird_strict)
        self._global_all_base_files = base_list
        return base_list

    def _perform_global_search(self, conditions):
        """执行全局数据库搜索"""
        # 提取搜索范围
        scope_all_cond = next((c for c in conditions if c.get('field') == '__scope_all__'), None)
        scope_fav_cond = next((c for c in conditions if c.get('field') == '__scope_fav__'), None)
        
        scope_all = scope_all_cond.get('value', False) if scope_all_cond else False
        scope_fav = scope_fav_cond.get('value', False) if scope_fav_cond else False
            
        taxonomy_fields = ["目", "科", "属", "种"]
        tax_conditions = [c for c in conditions if c.get('field') in taxonomy_fields]
        
        # 用户要求：当两个选项都未选中时，系统应显示所有文件
        # 所以不再需要在这里拦截空条件

        if scope_all:
            base_list = self._get_global_all_files_base()
            if not base_list:
                return []

            user_map = {}
            try:
                user_map = self.db.get_user_fields_map([it.get('path') for it in base_list])
            except Exception:
                user_map = {}

            results = []
            for it in base_list:
                try:
                    key = self.db._norm_path_key(it.get('path'))
                except Exception:
                    key = None

                if key and key in user_map:
                    u = user_map.get(key) or {}
                    it['is_favorite'] = int(u.get('is_favorite') or 0)
                    it['rating'] = int(u.get('rating') or 0)
                    it['label'] = u.get('label') or ''
                    it['description'] = u.get('description') or ''
                else:
                    it['is_favorite'] = int(it.get('is_favorite') or 0)
                    it['rating'] = int(it.get('rating') or 0)
                    it['label'] = it.get('label') or ''
                    it['description'] = it.get('description') or ''

                if scope_fav and not it.get('is_favorite'):
                    continue
                results.append(it)

            return results
        
        try:
            db = BirdLibraryDB()
            conn = db._get_connection()
            cursor = conn.cursor()
            
            # 构建 SQL
            sql = "SELECT file_path, shot_time, created_at, position, score, norm_score, bbox, focus_point, focus_detect_json, \
            label, order_cls, family_cls, genus_cls, species_cls, is_favorite, rating, uuid, \
            fnumber, shutter, iso, focal_length, camera_model, lens_model, latitude, longitude, location, tags FROM bird_results WHERE "
            params = []
            where_clause = "1=1" # 默认 true，方便后面拼接
            
            # 处理收藏筛选
            # 逻辑：
            # 1. 勾选"搜索收藏的文件" -> AND is_favorite = 1
            # 2. 勾选"搜索全部文件" -> 不添加限制 (显示全部)
            # 3. 都不勾选 -> 不添加限制 (显示全部)
            # 4. 都勾选 -> 取交集 -> AND is_favorite = 1
            if scope_fav:
                where_clause += " AND is_favorite = 1"
            
            field_map = {"目": "order_cls", "科": "family_cls", "属": "genus_cls", "种": "species_cls"}
            
            # 处理分类学条件
            if tax_conditions:
                tax_clause = ""
                for i, cond in enumerate(tax_conditions):
                    db_field = field_map.get(cond['field'])
                    value = cond['value']
                    fuzzy = cond.get('fuzzy', False)
                    logic = cond.get('logic', 'AND')
                    
                    value = str(value or "").strip()
                    value_l = value.lower()
                    if fuzzy:
                        clause = f"LOWER(TRIM({db_field})) LIKE ?"
                        params.append(f"%{value_l}%")
                    else:
                        clause = f"LOWER(TRIM({db_field})) = ?"
                        params.append(value_l)
                    
                    if i == 0:
                        tax_clause += f"({clause})"
                    else:
                        sql_op = "AND"
                        if logic == 'OR':
                            sql_op = "OR"
                        
                        if logic == 'NOT':
                            tax_clause += f" AND NOT ({clause})"
                        else:
                            tax_clause += f" {sql_op} ({clause})"
                
                if tax_clause:
                    where_clause += f" AND ({tax_clause})"

            # 处理评分条件 (适配搜索里的通过星星过滤的功能)
            rating_conditions = [c for c in conditions if c.get('field') == "评分"]
            if rating_conditions:
                rating_clause = ""
                for i, cond in enumerate(rating_conditions):
                    value = cond['value']
                    operator = cond.get('operator', '=')
                    logic = cond.get('logic', 'AND')
                    
                    try:
                        val_float = float(value)
                    except ValueError:
                        continue
                        
                    clause = ""
                    # 使用 COALESCE(rating, 0) 处理 NULL 值，确保未评分图片也能被正确过滤 (如 =0)
                    if operator == '=':
                        # 浮点数比较，允许微小误差 (与 _check_condition 保持一致)
                        clause = "COALESCE(rating, 0) BETWEEN ? AND ?"
                        params.append(val_float - 0.1)
                        params.append(val_float + 0.1)
                    elif operator == '≥':
                        # >= value - 0.1
                        clause = "COALESCE(rating, 0) >= ?"
                        params.append(val_float - 0.1)
                    elif operator == '≤':
                        # <= value + 0.1
                        clause = "COALESCE(rating, 0) <= ?"
                        params.append(val_float + 0.1)
                    else:
                        continue

                    if i == 0:
                        rating_clause += f"({clause})"
                    else:
                        sql_op = "AND"
                        if logic == 'OR':
                            sql_op = "OR"
                        
                        if logic == 'NOT':
                            rating_clause += f" AND NOT ({clause})"
                        else:
                            rating_clause += f" {sql_op} ({clause})"
                
                if rating_clause:
                    where_clause += f" AND ({rating_clause})"

            # 处理标签条件
            tag_conditions = [c for c in conditions if c.get('field') == "标签"]
            if tag_conditions:
                tag_clause = ""
                for i, cond in enumerate(tag_conditions):
                    value = cond['value']
                    logic = cond.get('logic', 'AND')
                    fuzzy = cond.get('fuzzy', False)
                    
                    value = str(value or "").strip()
                    value_l = value.lower()
                    if fuzzy:
                        clause = "LOWER(tags) LIKE ?"
                        params.append(f"%{value_l}%")
                    else:
                        clause = "(" \
                                 "LOWER(tags) = ? " \
                                 "OR LOWER(tags) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(tags) LIKE ? " \
                                 "OR LOWER(tags) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(tags) LIKE ? " \
                                 ")"
                        params.append(value_l)
                        params.append(value_l + "|%")
                        params.append("%|" + value_l + "|%")
                        params.append("%|" + value_l)
                        params.append(value_l + ",%")
                        params.append("%," + value_l + ",%")
                        params.append("%," + value_l)
                    
                    if i == 0:
                        tag_clause += f"({clause})"
                    else:
                        sql_op = "AND"
                        if logic == 'OR':
                            sql_op = "OR"
                        
                        if logic == 'NOT':
                            tag_clause += f" AND NOT ({clause})"
                        else:
                            tag_clause += f" {sql_op} ({clause})"
                
                if tag_clause:
                    where_clause += f" AND ({tag_clause})"

            # 处理地址条件
            addr_conditions = [c for c in conditions if c.get('field') in ("地址", "拍摄地址")]
            if addr_conditions:
                addr_clause = ""
                for i, cond in enumerate(addr_conditions):
                    value = cond['value']
                    fuzzy = cond.get('fuzzy', False)
                    logic = cond.get('logic', 'AND')
                    
                    value = str(value or "").strip()
                    value_l = value.lower()
                    if fuzzy:
                        clause = "LOWER(TRIM(location)) LIKE ?"
                        params.append(f"%{value_l}%")
                    else:
                        cands = []
                        if value_l:
                            cands.append(value_l)
                        try:
                            v2 = re.sub(r"(特别行政区|自治区|自治州|地区|盟|省|市|区|县|旗|镇|乡|街道)+$", "", value_l)
                            v2 = str(v2 or "").strip()
                            if v2 and v2 not in cands:
                                cands.append(v2)
                        except Exception:
                            pass
                        if not cands:
                            continue
                        clause = "(" + " OR ".join(["LOWER(TRIM(location)) LIKE ?"] * len(cands)) + ")"
                        for c in cands:
                            params.append(f"%{c}%")
                    
                    if i == 0:
                        addr_clause += f"({clause})"
                    else:
                        sql_op = "AND"
                        if logic == 'OR':
                            sql_op = "OR"
                        
                        if logic == 'NOT':
                            addr_clause += f" AND NOT ({clause})"
                        else:
                            addr_clause += f" {sql_op} ({clause})"
                
                if addr_clause:
                    where_clause += f" AND ({addr_clause})"

            # 处理拍摄时间条件
            shot_time_conditions = [c for c in conditions if c.get('field') == "拍摄时间"]
            if shot_time_conditions:
                shot_time_clause = ""

                normalized_time_expr = (
                    "CASE "
                    "WHEN shot_time IS NOT NULL AND TRIM(shot_time) != '' "
                    "THEN REPLACE(REPLACE(REPLACE(SUBSTR(shot_time, 1, 10), ':', '-'), '/', '-') || SUBSTR(shot_time, 11), 'T', ' ') "
                    "ELSE created_at "
                    "END"
                )

                for i, cond in enumerate(shot_time_conditions):
                    raw = str(cond.get('value') or '').strip()
                    operator = str(cond.get('operator') or 'between').strip() or 'between'
                    logic = cond.get('logic', 'AND')

                    start_s = ""
                    end_s = ""
                    if "||" in raw:
                        parts = raw.split("||", 1)
                        start_s = parts[0].strip()
                        end_s = parts[1].strip()
                    elif "," in raw:
                        parts = raw.split(",", 1)
                        start_s = parts[0].strip()
                        end_s = parts[1].strip()
                    else:
                        start_s = raw

                    clause = ""
                    if operator == "between":
                        if start_s and end_s and start_s > end_s:
                            start_s, end_s = end_s, start_s
                        if start_s and end_s:
                            clause = f"({normalized_time_expr} >= ? AND {normalized_time_expr} <= ?)"
                            params.append(start_s)
                            params.append(end_s)
                        elif start_s:
                            clause = f"({normalized_time_expr} >= ?)"
                            params.append(start_s)
                        elif end_s:
                            clause = f"({normalized_time_expr} <= ?)"
                            params.append(end_s)
                        else:
                            continue
                    elif operator == "≤":
                        if not start_s:
                            continue
                        clause = f"({normalized_time_expr} <= ?)"
                        params.append(start_s)
                    else:
                        if not start_s:
                            continue
                        clause = f"({normalized_time_expr} >= ?)"
                        params.append(start_s)

                    if i == 0:
                        shot_time_clause += f"({clause})"
                    else:
                        sql_op = "AND"
                        if logic == 'OR':
                            sql_op = "OR"
                        if logic == 'NOT':
                            shot_time_clause += f" AND NOT ({clause})"
                        else:
                            shot_time_clause += f" {sql_op} ({clause})"

                if shot_time_clause:
                    where_clause += f" AND ({shot_time_clause})"
            
            try:
                LogManager.instance().debug("[DB] Executing global search query...")
            except Exception:
                pass
            query_start = time.time()
            cursor.execute(sql + where_clause, params)
            rows = cursor.fetchall()
            conn.close()
            try:
                LogManager.instance().debug(
                    f"[DB] Query finished in {time.time() - query_start:.4f}s. Found {len(rows)} rows."
                )
            except Exception:
                pass
            
            unique_rows = {}
            for row in rows:
                try:
                    norm_path = os.path.normcase(os.path.normpath(row['file_path']))
                except Exception:
                    norm_path = row['file_path']

                inferred_order = ""
                inferred_family = ""
                inferred_genus = ""
                inferred_species = ""
                try:
                    p = os.path.normpath(row['file_path'])
                    parts = [seg for seg in p.split(os.sep) if seg]
                    if len(parts) >= 5:
                        inferred_species = parts[-2]
                        inferred_genus = parts[-3]
                        inferred_family = parts[-4]
                        inferred_order = parts[-5]
                    elif len(parts) >= 2:
                        inferred_species = parts[-2]
                except Exception:
                    pass

                def _norm_str(v):
                    try:
                        return str(v or "").strip().lower()
                    except Exception:
                        return ""

                def _row_get(r, key):
                    try:
                        return r[key]
                    except Exception:
                        return None

                def _row_quality_global(r):
                    try:
                        label_val = r['label']
                        has_label = bool(label_val and str(label_val).strip() and str(label_val).strip() != "None")
                    except Exception:
                        has_label = False
                    try:
                        bbox_v = r["bbox"]
                        has_bbox = 1 if (bbox_v not in (None, "", "None")) else 0
                    except Exception:
                        has_bbox = 0
                    try:
                        fp_v = r["focus_point"]
                        has_fp = 1 if (fp_v not in (None, "", "None")) else 0
                    except Exception:
                        has_fp = 0
                    try:
                        fdj = r["focus_detect_json"]
                        has_fdj = 1 if (fdj and str(fdj).strip() and str(fdj).strip() != "None") else 0
                    except Exception:
                        has_fdj = 0
                    try:
                        is_fav = 1 if (r['is_favorite'] or 0) else 0
                    except Exception:
                        is_fav = 0
                    try:
                        rating = int(r['rating'] or 0)
                    except Exception:
                        rating = 0
                    try:
                        has_uuid = 1 if r['uuid'] else 0
                    except Exception:
                        has_uuid = 0
                    try:
                        t = r['shot_time'] or r['created_at'] or ""
                        t = str(t)
                    except Exception:
                        t = ""

                    species_match = 1 if inferred_species and _norm_str(_row_get(r, 'species_cls')) == _norm_str(inferred_species) else 0
                    genus_match = 1 if inferred_genus and _norm_str(_row_get(r, 'genus_cls')) == _norm_str(inferred_genus) else 0
                    family_match = 1 if inferred_family and _norm_str(_row_get(r, 'family_cls')) == _norm_str(inferred_family) else 0
                    order_match = 1 if inferred_order and _norm_str(_row_get(r, 'order_cls')) == _norm_str(inferred_order) else 0
                    return (species_match, genus_match, family_match, order_match, has_bbox, has_fp, has_fdj, 1 if has_label else 0, is_fav, rating, has_uuid, t)

                exist = unique_rows.get(norm_path)
                if not exist or _row_quality_global(row) > _row_quality_global(exist):
                    unique_rows[norm_path] = row

            rows = list(unique_rows.values())

            results = []
            for row in rows:
                
                time_str = ""
                create_ts = 0.0
                try:
                    stat = os.stat(row['file_path'])
                    time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_ctime))
                    create_ts = float(stat.st_ctime)
                except Exception:
                    time_str = row['shot_time'] if row['shot_time'] else str(row['created_at'])
                
                # 如果数据库中没有物种信息，尝试从路径推断 (与 load_images_from_folder 逻辑保持一致)
                # 这解决了收藏图片在全局搜索后因缺失分类信息而排在最后的问题
                species_val = row['species_cls']
                if not species_val:
                    try:
                        # 假设目录结构为 .../Genus/Species/Image.jpg
                        species_val = os.path.basename(os.path.dirname(row['file_path']))
                    except:
                        pass

                results.append({
                    'path': row['file_path'],
                    'name': os.path.basename(row['file_path']),
                    'create_time': time_str,
                    'create_ts': create_ts,
                    'shot_time': row['shot_time'] or '',
                    'shot_ts': self._parse_datetime_to_ts(row['shot_time'] or '') or create_ts,
                    'position': row['position'],
                    'score': row['score'],
                    'norm_score': row['norm_score'],
                    'bbox': row['bbox'] if 'bbox' in row.keys() else None,
                    'focus_point': row['focus_point'] if 'focus_point' in row.keys() else None,
                    'focus_detect_json': row['focus_detect_json'] if 'focus_detect_json' in row.keys() else '',
                    'label': row['label'],
                    'order': row['order_cls'] or '',
                    'family': row['family_cls'] or '',
                    'genus': row['genus_cls'] or '',
                    'species': species_val,
                    'is_favorite': row['is_favorite'],
                    'rating': row['rating'] or 0,
                    'uuid': row['uuid'],
                    'fnumber': row['fnumber'],
                    'shutter': row['shutter'],
                    'iso': row['iso'],
                    'focal_length': row['focal_length'],
                    'camera_model': row['camera_model'],
                    'lens_model': row['lens_model'],
                    'tags': row['tags'],
                    'location': row['location'],
                })
            
            if results:
                pass
            
            return results
            
        except Exception as e:
            try:
                LogManager.instance().warning(f"全局搜索失败: {e}")
            except Exception:
                pass
            NotificationManager.instance().show_warning("错误", f"全局搜索失败: {e}")
            return []

    def on_advanced_search(self, conditions):
        """处理高级搜索"""
        scope_all_cond = next((c for c in conditions if c.get('field') == '__scope_all__'), None)
        scope_fav_cond = next((c for c in conditions if c.get('field') == '__scope_fav__'), None)
        
        scope_all = scope_all_cond.get('value', False) if scope_all_cond else False
        scope_fav = scope_fav_cond.get('value', False) if scope_fav_cond else False
        
        local_conditions = [
            c for c in conditions
            if c.get('field') not in ['__scope_all__', '__scope_fav__']
        ]
        
        # 检查是否有分类学字段（触发全局搜索）
        # 将 标签 和 地址 也加入触发全局搜索的字段中，因为这些信息主要存储在数据库中
        # 且本地加载列表时可能未完全加载这些元数据
        taxonomy_fields = {"目", "科", "属", "种", "标签", "地址", "拍摄地址", "拍摄时间"}
        has_taxonomy = local_conditions and any(c.get('field') in taxonomy_fields for c in local_conditions)
        
        # 触发全局搜索的条件：
        # 1. 选择了"搜索全部文件" (scope_all=True)
        # 2. 选择了"搜索收藏的文件" (scope_fav=True)
        # 3. 有分类学条件
        is_global_search = scope_all or scope_fav or has_taxonomy
        self.showing_search_results = is_global_search or bool(local_conditions)

        if is_global_search:
            try:
                LogManager.instance().debug(f"触发全局搜索: All={scope_all}, Fav={scope_fav}, Taxonomy={has_taxonomy}")
            except Exception:
                pass

            self.favorite_filter = False
            self.rating_filter = 0
            if hasattr(self, "fav_btn"):
                try:
                    self.fav_btn.blockSignals(True)
                    self.fav_btn.setChecked(False)
                    self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
                finally:
                    self.fav_btn.blockSignals(False)
            if hasattr(self, "star_rating"):
                try:
                    self.star_rating.set_rating(0, emit_signal=False)
                except Exception:
                    pass
            
            # 执行全局数据库搜索 (使用原始 conditions，包含 scope)
            start_time = time.time()
            global_files = self._perform_global_search(conditions)
            try:
                LogManager.instance().debug(
                    f"[Performance] _perform_global_search took {time.time() - start_time:.4f}s. Found {len(global_files)} files."
                )
            except Exception:
                pass
            
            # 将搜索结果作为当前图片列表
            self.image_files = global_files
            
            # 再次应用所有过滤条件（包括非数据库字段）
            # 数据库查询处理了 scope 和 taxonomy
            # 这里处理剩下的字段（如评分、状态等）
            
            filtered_files = []
            for img_info in self.image_files:
                is_match = True
                
                # 如果没有本地过滤条件，默认匹配
                if not local_conditions:
                    filtered_files.append(img_info)
                    continue

                for i, condition in enumerate(local_conditions):
                    current_match = self._check_condition(img_info, condition)
                    if i == 0:
                        is_match = current_match
                    else:
                        logic = condition.get('logic', 'AND')
                        if logic == 'AND':
                            is_match = is_match and current_match
                        elif logic == 'OR':
                            is_match = is_match or current_match
                        elif logic == 'NOT':
                            is_match = is_match and (not current_match)
                
                if is_match:
                    filtered_files.append(img_info)
            
            self.image_files = filtered_files
            self.raw_image_files = list(self.image_files)
            
            # 启动缩略图加载
            self.cache_manager.stop_preload()
            self.thumbnail_loader.cancel_all()
            
            paths_to_load = [img['path'] for img in self.image_files if img.get('path')]
                
            if paths_to_load:
                cache_type = 'general'
                if scope_fav and not scope_all:
                    cache_type = 'fav'
                elif has_taxonomy:
                    cache_type = 'species'
                self.thumbnail_loader.load_thumbnails(paths_to_load, self.current_thumb_size, cache_type, request_id=getattr(self, "_thumbnail_request_id", None))
            else:
                pass
            
            # 更新排序并显示
            self.sort_images()
            
            scope_text = "全局"
            if scope_fav and not scope_all:
                scope_text = "收藏"
            pass
            return

        # 如果没有触发全局搜索，且没有本地过滤条件，恢复显示当前文件夹
        if not local_conditions:
            # 如果没有条件，恢复当前文件夹
            if self.current_folder_path:
                try:
                    cur = str(self.current_folder_path or "")
                except Exception:
                    cur = ""
                if cur.startswith("virtual://taxonomy"):
                    self.load_images_from_taxonomy(cur)
                else:
                    self.load_images_from_folder(cur)
            else:
                self.update_thumbnails()
            return
            
        try:
            LogManager.instance().debug(f"本地搜索条件: {local_conditions}")
        except Exception:
            pass
        filtered_files = []
        
        for img_info in self.image_files:
            # 初始匹配状态
            is_match = True
            
            # 遍历条件
            for i, condition in enumerate(local_conditions):
                # 检查当前条件是否匹配
                current_match = self._check_condition(img_info, condition)
                
                if i == 0:
                    is_match = current_match
                else:
                    logic = condition.get('logic', 'AND')
                    if logic == 'AND':
                        is_match = is_match and current_match
                    elif logic == 'OR':
                        is_match = is_match or current_match
                    elif logic == 'NOT':
                        is_match = is_match and (not current_match)
            
            if is_match:
                filtered_files.append(img_info)
        
        self.image_files = filtered_files
        self.sort_images()
        
        # 自动关闭面板
        # self._filter_btn.setChecked(False) # 可选：搜索后是否自动关闭

    def _check_condition(self, img_info, condition):
        """检查单个条件是否匹配"""
        field = condition.get('field')
        value = condition.get('value', '')
        fuzzy = condition.get('fuzzy', False)
        operator = condition.get('operator', '=')
        
        target_value = ""
        
        if field == "文件名":
            target_value = img_info.get('name', '').lower()
        elif field == "路径":
            target_value = img_info.get('path', '').lower()
        elif field == "标签":
            raw_tags = img_info.get('tags', '') or ''
            if raw_tags is None:
                raw_tags = ""
            search_val = str(value or '').strip().lower()
            if not search_val:
                return True
            hay = str(raw_tags).lower()
            if fuzzy:
                return search_val in hay
            try:
                parts = re.split(r"[|,;]", hay)
            except Exception:
                parts = [hay]
            tag_set = {p.strip() for p in parts if p.strip()}
            return search_val in tag_set
        elif field in ("地址", "拍摄地址"):
            target_value = str(img_info.get('location', '') or '').strip().lower()
            search_val = str(value or '').strip().lower()
            
            if fuzzy:
                return search_val in target_value
            if not search_val:
                return True
            try:
                s_target = re.sub(r"[\s,;，；/\\]+", "", str(target_value or ""))
                s_query = re.sub(r"[\s,;，；/\\]+", "", str(search_val or ""))
            except Exception:
                s_target = str(target_value or "")
                s_query = str(search_val or "")

            suffix_pat = r"(特别行政区|自治区|自治州|地区|盟|省|市|区|县|旗|镇|乡|街道)"

            def _units(s: str) -> list[str]:
                out = []
                try:
                    t = str(s or "")
                except Exception:
                    return out
                pos = 0
                while pos < len(t):
                    m = re.search(suffix_pat, t[pos:])
                    if not m:
                        tail = t[pos:]
                        if tail:
                            out.append(tail)
                        break
                    idx0 = pos + int(m.start())
                    idx1 = pos + int(m.end())
                    seg = t[pos:idx0]
                    if seg:
                        out.append(seg)
                    pos = idx1
                out2 = []
                for seg in out:
                    try:
                        x = re.sub(suffix_pat + r"+$", "", str(seg))
                    except Exception:
                        x = str(seg)
                    x = str(x or "").strip()
                    if x:
                        out2.append(x)
                return out2

            target_units = _units(s_target)
            query_units = _units(s_query)
            if not query_units:
                query_units = [s_query] if s_query else []
            if not target_units:
                target_units = [s_target] if s_target else []
            try:
                t_set = set(target_units)
            except Exception:
                t_set = set()
            if len(query_units) == 1:
                q0 = query_units[0]
                if q0 in t_set:
                    return True
                try:
                    return q0 in "".join(target_units)
                except Exception:
                    return False
            for q in query_units:
                if q not in t_set:
                    try:
                        if q not in "".join(target_units):
                            return False
                    except Exception:
                        return False
            return True
        elif field == "拍摄时间":
            op = operator or 'between'

            shot_ts = 0.0
            try:
                shot_time = img_info.get('shot_time')
            except Exception:
                shot_time = None
            shot_ts = self._parse_datetime_to_ts(shot_time) if shot_time else 0.0

            if op == "between":
                raw = str(value or "").strip()
                start_s = ""
                end_s = ""
                if "||" in raw:
                    parts = raw.split("||", 1)
                    start_s = parts[0].strip()
                    end_s = parts[1].strip()
                elif "," in raw:
                    parts = raw.split(",", 1)
                    start_s = parts[0].strip()
                    end_s = parts[1].strip()
                else:
                    start_s = raw

                start_ts = self._parse_datetime_to_ts(start_s) if start_s else 0.0
                end_ts = self._parse_datetime_to_ts(end_s) if end_s else 0.0

                if not start_ts and not end_ts:
                    return True
                if not shot_ts:
                    return False
                if start_ts and end_ts and start_ts > end_ts:
                    start_ts, end_ts = end_ts, start_ts

                if start_ts and shot_ts < start_ts:
                    return False
                if end_ts and shot_ts > end_ts:
                    return False
                return True

            start_ts = self._parse_datetime_to_ts(value)
            if not start_ts:
                return True
            if not shot_ts:
                return False
            if op == '≤':
                return shot_ts <= start_ts
            return shot_ts >= start_ts
        elif field == "创建时间":
            return True
        elif field == "评分":
            # 处理评分比较
            try:
                # 尝试将输入值转换为浮点数
                filter_rating = float(value)
            except ValueError:
                # 如果输入不是有效数字，则忽略此条件（或认为不匹配）
                return False

            # 获取图片评分
            # 优先从 img_info 获取评分
            if 'rating' in img_info and img_info['rating'] is not None:
                img_rating = float(img_info['rating'])
            elif 'norm_score' in img_info and img_info['norm_score'] is not None:
                img_rating = float(img_info['norm_score'])
            else:
                img_rating = self._get_image_rating(img_info['path'])
            
            if operator == '=':
                # 浮点数比较，允许微小误差
                return abs(img_rating - filter_rating) < 0.1
            elif operator == '≥':
                return img_rating >= filter_rating - 0.1
            elif operator == '≤':
                return img_rating <= filter_rating + 0.1
            else:
                return False
            
        elif field == "分数":
            try:
                filter_score = float(value)
            except ValueError:
                return False
            
            img_score = img_info.get('score')
            if img_score is None:
                 img_score = img_info.get('norm_score')
            
            if img_score is None:
                 img_score = 0.0

            if operator == '=':
                return abs(img_score - filter_score) < 0.01
            elif operator == '≥':
                return img_score >= filter_score
            elif operator == '≤':
                return img_score <= filter_score
            else:
                return False

        elif field == "鸟的位置":
            target_value = str(img_info.get('position', '') or '').lower()
        elif field == "色标":
            # 精确匹配
            target_value = str(img_info.get('label', '') or '')
            if value == "None":
                return not target_value
            return value == target_value
        elif field == "目":
            target_value = str(img_info.get('order', '') or '').strip().lower()
        elif field == "科":
            target_value = str(img_info.get('family', '') or '').strip().lower()
        elif field == "属":
            target_value = str(img_info.get('genus', '') or '').strip().lower()
        elif field == "种":
            target_value = str(img_info.get('species', '') or '').strip().lower()
        # 处理特殊范围字段 (这些字段不应该进入这里，但为了防止报错，直接返回 True)
        elif field in ['__scope_all__', '__scope_fav__']:
             return True

        try:
            v = str(value or '').strip().lower()
        except Exception:
            v = ''
        if not v:
            return True
        if fuzzy:
            return v in target_value
        return v == target_value

    def _get_image_rating(self, image_path):
        """尝试获取图片评分"""
        try:
            # 简单快速读取，只尝试 exifread
            # 注意：exifread 对 XMP 支持有限，可能无法读取所有软件写入的评分
            with open(image_path, 'rb') as f:
                # 只读取必要的标签以加快速度
                tags = exifread.process_file(f, details=False, stop_tag='Rating')
                
                # 常见评分标签
                if 'Image Rating' in tags:
                    return float(str(tags['Image Rating']))
                if 'Rating' in tags: # 有时直接是 Rating
                    return float(str(tags['Rating']))
                if 'Image RatingPercent' in tags:
                    # 有些软件使用百分比，例如 Windows
                    return float(str(tags['Image RatingPercent'])) / 20.0
        except:
            pass
        return 0.0

    def on_scroll_value_changed(self, value):
        """处理滚动事件，触发可见范围缩略图加载"""
        # 兜底：如果控制器不可用，则走原逻辑（保持兼容）
        self._schedule_visible_load(immediate=False)
        try:
            self._schedule_persist_folder_view_state()
        except Exception:
            pass

    def _get_folder_view_state_key(self, folder_path: str) -> str:
        try:
            fp = str(folder_path or "")
        except Exception:
            fp = ""
        if not fp:
            return ""
        if fp.startswith("virtual://"):
            return fp
        return self._normalize_path_str(fp)

    def _load_folder_view_state_map(self) -> dict:
        sm = getattr(self, "settings_manager", None)
        if sm is None:
            return {}
        try:
            raw = sm.get("library/folder_view_state_map", "") or ""
        except Exception:
            raw = ""
        if not raw:
            return {}
        try:
            d = json.loads(str(raw))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    def _save_folder_view_state_map(self):
        sm = getattr(self, "settings_manager", None)
        if sm is None:
            return
        m = getattr(self, "_folder_view_state_map", None)
        if not isinstance(m, dict):
            m = {}
        items = []
        for k, v in (m or {}).items():
            if not k:
                continue
            if not isinstance(v, dict):
                continue
            try:
                ts = float(v.get("ts") or 0)
            except Exception:
                ts = 0.0
            items.append((k, v, ts))
        items.sort(key=lambda x: x[2], reverse=True)
        trimmed = {}
        for k, v, _ in items[:200]:
            trimmed[str(k)] = v
        try:
            sm.set("library/folder_view_state_map", json.dumps(trimmed, ensure_ascii=False))
        except Exception:
            pass
        self._folder_view_state_map = trimmed

    def _capture_folder_view_state(self) -> dict:
        gv = getattr(self, "grid_view", None)
        if gv is None:
            return {}
        selected = -1
        anchor = -1
        try:
            if getattr(gv, "is_virtualized", False) and getattr(gv, "list_view", None) is not None:
                try:
                    ci = gv.list_view.currentIndex()
                    if ci is not None and ci.isValid():
                        selected = int(ci.row())
                except Exception:
                    selected = -1
                try:
                    mi = gv.list_view.indexAt(QPoint(1, 1))
                    if mi is not None and mi.isValid():
                        anchor = int(mi.row())
                except Exception:
                    anchor = -1
        except Exception:
            pass
        if selected < 0:
            try:
                selected = int(getattr(gv, "last_selected_index", -1))
            except Exception:
                selected = -1
        if anchor < 0:
            try:
                start, _, _ = gv.get_visible_index_range(extra_rows=0)
                anchor = int(start)
            except Exception:
                anchor = -1
        try:
            ts = float(time.time())
        except Exception:
            ts = 0.0
        return {"selected": int(selected), "anchor": int(anchor), "ts": ts}

    def _schedule_persist_folder_view_state(self):
        if not hasattr(self, "_folder_view_state_save_timer") or self._folder_view_state_save_timer is None:
            return
        try:
            self._folder_view_state_save_timer.start(250)
        except Exception:
            pass

    def _persist_folder_view_state_now(self):
        fp = str(getattr(self, "current_folder_path", "") or "")
        key = self._get_folder_view_state_key(fp)
        if not key:
            return
        st = self._capture_folder_view_state()
        if not st:
            return
        m = getattr(self, "_folder_view_state_map", None)
        if not isinstance(m, dict):
            m = {}
        m[str(key)] = st
        self._folder_view_state_map = m
        self._save_folder_view_state_map()

    def _set_pending_restore_for_folder(self, folder_path: str):
        key = self._get_folder_view_state_key(folder_path)
        self._pending_restore_folder_key = key or None
        st = None
        try:
            if key and isinstance(getattr(self, "_folder_view_state_map", None), dict):
                st = self._folder_view_state_map.get(str(key))
        except Exception:
            st = None
        self._pending_restore_state = st if isinstance(st, dict) else None
        self._pending_restore_applied = False if self._pending_restore_state else True

    def _maybe_apply_pending_restore(self):
        if bool(getattr(self, "_pending_restore_applied", True)):
            return
        st = getattr(self, "_pending_restore_state", None)
        if not isinstance(st, dict):
            self._pending_restore_applied = True
            return
        try:
            sel = int(st.get("selected", -1))
        except Exception:
            sel = -1
        try:
            anc = int(st.get("anchor", -1))
        except Exception:
            anc = -1
        target = sel if sel >= 0 else anc
        if target < 0:
            self._pending_restore_applied = True
            return
        try:
            total = int(len(self.all_image_files or []))
        except Exception:
            total = 0
        if total <= 0:
            return
        target = max(0, min(int(target), int(total) - 1))
        if int(getattr(self, "current_loaded_count", 0) or 0) <= int(target) and bool(getattr(self, "is_lazy_loading", False)):
            try:
                QTimer.singleShot(0, lambda: self.load_more_thumbnails(load_all=False))
            except Exception:
                pass
            return
        gv = getattr(self, "grid_view", None)
        if gv is None:
            self._pending_restore_applied = True
            return
        try:
            gv.select_thumbnail(int(target), scroll_to=True)
        except Exception:
            pass
        try:
            if getattr(gv, "is_virtualized", False) and getattr(gv, "list_view", None) is not None:
                gv.list_view.viewport().update()
            else:
                gv.thumbnails_container.update()
        except Exception:
            pass
        def _post():
            try:
                self.on_thumbnail_clicked_proxy(int(target), Qt.KeyboardModifier.NoModifier)
            except Exception:
                pass
        try:
            QTimer.singleShot(0, _post)
        except Exception:
            _post()
        self._pending_restore_applied = True

    def _on_fast_scroll_timeout(self):
        self._fast_scroll_active = False
        self._resume_thumbnail_ui_updates()
        self._schedule_visible_load(immediate=True)

    def _on_scrollbar_pressed(self):
        self._suspend_thumbnail_ui_updates()

    def _on_scrollbar_released(self):
        if self._fast_scroll_timer.isActive():
            self._fast_scroll_timer.stop()
        self._fast_scroll_active = False
        self._resume_thumbnail_ui_updates()
        self._schedule_visible_load(immediate=True)

    def _suspend_thumbnail_ui_updates(self):
        self._thumbnail_ui_suspended = True
        try:
            if getattr(self, "grid_view", None) and getattr(self.grid_view, "is_virtualized", False):
                if hasattr(self.grid_view, "set_fast_scroll_simplified"):
                    self.grid_view.set_fast_scroll_simplified(True)
        except Exception:
            pass
        try:
            self._update_timer.stop()
        except Exception:
            pass

    def _resume_thumbnail_ui_updates(self):
        self._thumbnail_ui_suspended = False
        try:
            if getattr(self, "grid_view", None) and getattr(self.grid_view, "is_virtualized", False):
                if hasattr(self.grid_view, "set_fast_scroll_simplified"):
                    self.grid_view.set_fast_scroll_simplified(False)
        except Exception:
            pass
        try:
            if self._pending_updates:
                self._update_timer.start(0)
        except Exception:
            pass

    def _schedule_visible_load(self, immediate=False):
        """调度可见区域缩略图的加载
        
        使用去抖动（Debounce）机制来优化滚动性能，避免滚动条 valueChanged 高频触发时反复扫描可见范围。
        """
        if not hasattr(self, "_visible_load_timer"):
            return
        self._visible_load_force_cancel = bool(immediate)
        if self._visible_load_timer.isActive():
            self._visible_load_timer.stop()
        interval = 0 if immediate else 40
        self._visible_load_timer.start(interval)

    def _load_visible_thumbnails(self):
        """加载当前可见区域及预加载区域的缩略图"""
        if not getattr(self, "grid_view", None) or not getattr(self.grid_view, "thumbnails", None):
            return

        start_visible, end_visible, visible_rows = self.grid_view.get_visible_index_range()
        if end_visible < start_visible:
            return

        extra_rows = 0 if getattr(self, "_fast_scroll_active", False) else visible_rows
        start, end, _ = self.grid_view.get_visible_index_range(extra_rows=extra_rows)
        if end < start:
            return

        try:
            metrics = self.grid_view.get_viewport_metrics() or {}
            cols = max(1, int(metrics.get("cols", 1)))
        except Exception:
            cols = 1
        try:
            is_big_mode = int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) == ImageThumbnail.MODE_THUMBNAIL_ONLY
        except Exception:
            is_big_mode = False
        if is_big_mode and not bool(getattr(self, "_fast_scroll_active", False)) and cols > 0 and visible_rows > 0:
            try:
                last_row = max(0, int(end_visible) // int(cols))
            except Exception:
                last_row = 0
            probe_row = int(last_row) + 2
            probe_start = int(probe_row) * int(cols)
            if probe_start < len(self.grid_view.thumbnails):
                probe_end = min(len(self.grid_view.thumbnails) - 1, probe_start + int(cols) - 1)
                probe_has_unloaded = False
                for j in range(int(probe_start), int(probe_end) + 1):
                    try:
                        t = self.grid_view.thumbnails[j]
                    except Exception:
                        continue
                    try:
                        is_stale = bool(getattr(t, "_stale_thumbnail", False))
                    except Exception:
                        is_stale = False
                    try:
                        pix = getattr(t, "thumbnail_pixmap", None)
                        img = getattr(t, "_thumbnail_image", None)
                        has_pix = pix is not None and not (hasattr(pix, "isNull") and pix.isNull())
                        has_img = img is not None and not (hasattr(img, "isNull") and img.isNull())
                    except Exception:
                        has_pix = False
                        has_img = False
                    if not ((has_pix or has_img) and not is_stale):
                        probe_has_unloaded = True
                        break
                if probe_has_unloaded:
                    try:
                        big_end = min(len(self.grid_view.thumbnails) - 1, int(probe_start) + int(visible_rows) * int(cols) - 1)
                    except Exception:
                        big_end = end
                    if int(big_end) > int(end):
                        end = int(big_end)

        cache_type = getattr(self, "current_cache_type", "general")
        try:
            req_size = getattr(self, "current_thumb_size", None)
        except Exception:
            req_size = None
        try:
            if isinstance(req_size, (tuple, list)):
                req_max = max(int(req_size[0]), int(req_size[1]))
            elif req_size:
                req_max = int(req_size)
            else:
                req_max = 0
        except Exception:
            req_max = 0

        if getattr(self, "_visible_load_force_cancel", False):
            self.thumbnail_loader.cancel_pending()
            self._requested_paths = set()
        self._visible_load_force_cancel = False

        paths_to_load = []
        current_visible_keys = set()
        pending_visible_keys = set()

        for i in range(start, end + 1):
            try:
                thumb = self.grid_view.thumbnails[i]
            except Exception:
                continue
            info = getattr(thumb, "image_info", None)
            if not info:
                continue
            try:
                path = info.get("path") or info.get("file_path") or info.get("filepath")
            except Exception:
                path = None
            if not path:
                continue

            key = self._normalize_path_key(path)
            pending_visible_keys.add(key)
            if i <= end_visible:
                current_visible_keys.add(key)

            try:
                is_stale = bool(getattr(thumb, "_stale_thumbnail", False))
            except Exception:
                is_stale = False
            try:
                pix = getattr(thumb, "thumbnail_pixmap", None)
                img = getattr(thumb, "_thumbnail_image", None)
                has_pix = pix is not None and not (hasattr(pix, "isNull") and pix.isNull())
                has_img = img is not None and not (hasattr(img, "isNull") and img.isNull())
            except Exception:
                has_pix = False
                has_img = False
            if (has_pix or has_img) and not is_stale and req_max > 0:
                try:
                    if has_img:
                        existing_max = max(int(img.width() or 0), int(img.height() or 0))
                    else:
                        existing_max = max(int(pix.width() or 0), int(pix.height() or 0))
                except Exception:
                    existing_max = 0
                
                if existing_max > 0 and existing_max < int(req_max * 0.6):
                    try:
                        thumb._stale_thumbnail = True
                        is_stale = True
                    except Exception:
                        pass
            has_loaded = (has_pix or has_img) and not is_stale

            if key in self._requested_paths and not is_stale:
                if i <= end_visible:
                    if not has_loaded and hasattr(thumb, "load_thumbnail"):
                        try:
                            if hasattr(thumb, "update"):
                                thumb.update()
                        except Exception:
                            pass
                continue
            if key in self._requested_paths and is_stale:
                try:
                    self._requested_paths.discard(key)
                except Exception:
                    pass

            self._requested_paths.add(key)

            if i <= end_visible:
                priority = -1
                is_in_view = True
            elif getattr(self, "_mouse_busy", False):
                priority = 2
                is_in_view = False
            else:
                priority = 1
                is_in_view = False

            paths_to_load.append((priority, path, is_in_view))

            if self._startup_mask_enabled and self._startup_mask_visible and i <= end_visible:
                try:
                    pix = getattr(thumb, "thumbnail_pixmap", None)
                    img = getattr(thumb, "_thumbnail_image", None)
                    has_pix = pix is not None and not (hasattr(pix, "isNull") and pix.isNull())
                    has_img = img is not None and not (hasattr(img, "isNull") and img.isNull())
                    is_missing = not (has_pix or has_img)
                except Exception:
                    is_missing = True
                if is_missing:
                    self._startup_pending_paths.add(key)

        self._current_visible_path_keys = current_visible_keys
        self._pending_visible_path_keys = pending_visible_keys

        if paths_to_load:
            self.thumbnail_loader.load_thumbnails(paths_to_load, self.current_thumb_size, cache_type, request_id=getattr(self, "_thumbnail_request_id", None))

        if self.is_lazy_loading and self.current_loaded_count < len(self.all_image_files):
            try:
                if end_visible >= max(0, len(self.grid_view.thumbnails) - 6):
                    self.load_more_thumbnails()
            except Exception:
                pass

    def calculate_dynamic_batch_size(self):
        """计算动态加载数量"""
        # 获取可见区域尺寸
        available_width = self.get_available_width()
        available_height = self.scroll_area.viewport().height()
        
        thumb_w, thumb_h = self._get_current_thumb_wh()
        
        # 避免除以零
        if thumb_w <= 0 or thumb_h <= 0:
            return 50
            
        # 计算每行和每列能显示的图片数量
        cols = max(1, available_width // thumb_w)
        # 启动时视口高度可能不准，给一个安全的最小行数（例如 10 行），确保能填满屏幕
        rows_visible = max(10, available_height // thumb_h)
        
        # 可视区域能显示的数量
        visible_count = cols * rows_visible
        
        # 缓冲区域（预加载下方 5 行，增加缓冲以防止快速滚动时的空白）
        buffer_rows = 5
        buffer_count = cols * buffer_rows
        
        # 初始加载数量
        initial_count = visible_count + buffer_count
        
        try:
            LogManager.instance().debug(
                f"[UI] Dynamic Batch Size: {initial_count} (Cols: {cols}, Visible Rows: {rows_visible}, Buffer: {buffer_rows})"
            )
        except Exception:
            pass
        return initial_count

    def load_more_thumbnails(self, load_all=False):
        """加载更多缩略图"""
        # 防止重入
        if getattr(self, '_loading_more', False):
            return
            
        if not self.all_image_files:
            return

        self._loading_more = True
        t0 = time.perf_counter()
        
        task_id = None
        updates_disabled = False
        grid_view = getattr(self, "grid_view", None)
        thumbnails_container = getattr(grid_view, "thumbnails_container", None)
        try:
            # 动态计算加载数量
            self.batch_size = self.calculate_dynamic_batch_size()
    
            if load_all:
                start = 0
                end = len(self.all_image_files)
            else:
                start = self.current_loaded_count
                end = min(start + self.batch_size, len(self.all_image_files))
            
            try:
                LogManager.instance().debug(
                    f"[UI] Loading thumbnails from {start} to {end} (Total: {len(self.all_image_files)})"
                )
            except Exception:
                pass
            
            if start >= end:
                # 已全部加载
                self.is_lazy_loading = False
                # 隐藏加载提示（如果后续添加了）
                self.stats_changed.emit(len(self.all_image_files), self.current_loaded_count, self.get_selected_count())
                return
    
            task_id = StatusManager.instance().start_task("正在加载缓存...")
    
            # 获取当前批次的文件
            files_slice = self.all_image_files[start:end]
            
            if grid_view is not None:
                grid_view.setUpdatesEnabled(False)
            if thumbnails_container is not None:
                thumbnails_container.setUpdatesEnabled(False)
            updates_disabled = True

            # 创建新的缩略图组件
            new_thumbnails = []
            for i, img_info in enumerate(files_slice):
                # 全局索引
                global_index = start + i
                if getattr(grid_view, "is_virtualized", False):
                    if isinstance(img_info, dict):
                        info = img_info
                    else:
                        info = {"path": "", "name": "", "create_time": ""}
                    info["index"] = global_index
                    grid_view.add_thumbnail(info)
                    thumbnail = grid_view.thumbnails[-1]
                    img_path = None
                    try:
                        img_path = info.get("path") or info.get("file_path") or info.get("filepath")
                    except Exception:
                        img_path = None
                    if img_path:
                        self._thumb_by_path[self._normalize_path_key(img_path)] = thumbnail
                    new_thumbnails.append(thumbnail)
                else:
                    thumbnail = ImageThumbnail(global_index, self.current_thumb_size, parent=thumbnails_container)
                    thumbnail.set_display_mode(self.display_mode)
                    img_path = None
                    try:
                        if isinstance(img_info, dict):
                            img_path = img_info.get("path") or img_info.get("file_path") or img_info.get("filepath")
                    except Exception:
                        img_path = None
                    try:
                        thumbnail.set_image_info(img_info, load_now=False)
                    except Exception:
                        pass
                    if getattr(self, "_select_all_active", False):
                        try:
                            thumbnail.set_selected(True)
                        except Exception:
                            pass
                    if img_path:
                        self._thumb_by_path[self._normalize_path_key(img_path)] = thumbnail
                    # 使用 grid_view 添加缩略图 (会自动绑定信号)
                    grid_view.add_thumbnail(thumbnail)
                    new_thumbnails.append(thumbnail)
            
            self.current_loaded_count = end
            
            # 追加布局，避免全量重排
            grid_view.append_batch_to_layout(start)
            if getattr(self, "_select_all_active", False) and getattr(grid_view, "is_virtualized", False):
                grid_view.select_all_thumbnails()
            
            cache_type = getattr(self, 'current_cache_type', 'general')
            paths_to_load = []
            try:
                visible_start, visible_end, _ = grid_view.get_visible_index_range(extra_rows=0)
            except Exception:
                visible_start, visible_end = 0, -1
            try:
                metrics = grid_view.get_viewport_metrics() or {}
                cols = max(1, int(metrics.get("cols", 1)))
            except Exception:
                cols = 1
            try:
                fallback_visible_end = min(len(grid_view.thumbnails) - 1, int(visible_start) + int(cols) * 8 - 1)
            except Exception:
                fallback_visible_end = visible_end
            try:
                effective_visible_end = max(int(visible_end), int(fallback_visible_end))
            except Exception:
                effective_visible_end = visible_end
            for t in new_thumbnails:
                path = None
                try:
                    info = getattr(t, "image_info", None) or {}
                    if isinstance(info, dict):
                        path = info.get("path") or info.get("file_path") or info.get("filepath")
                except Exception:
                    path = None
                if not path:
                    continue
                idx = getattr(t, "index", None)
                is_visible = idx is not None and effective_visible_end >= visible_start and visible_start <= idx <= effective_visible_end
                priority = -1 if is_visible else 3
                paths_to_load.append((priority, path, bool(is_visible)))
                if self._startup_mask_enabled and self._startup_mask_visible:
                    if is_visible:
                        try:
                            pix = getattr(t, "thumbnail_pixmap", None)
                            img = getattr(t, "_thumbnail_image", None)
                            has_pix = pix is not None and not (hasattr(pix, "isNull") and pix.isNull())
                            has_img = img is not None and not (hasattr(img, "isNull") and img.isNull())
                            is_missing = not (has_pix or has_img)
                        except Exception:
                            is_missing = True
                        if is_missing:
                            self._startup_pending_paths.add(self._normalize_path_key(path))
                    
            if paths_to_load:
                self.thumbnail_loader.load_thumbnails(paths_to_load, self.current_thumb_size, cache_type, request_id=getattr(self, "_thumbnail_request_id", None))
                
            # 如果加载完了，关闭懒加载标志
            if self.current_loaded_count >= len(self.all_image_files):
                self.is_lazy_loading = False
                
            # 更新状态栏
            self.stats_changed.emit(len(self.all_image_files), self.current_loaded_count, self.get_selected_count())
            self._maybe_hide_startup_mask()
            
        except Exception as e:
            try:
                LogManager.instance().warning(f"[UI] Error loading thumbnails: {e}")
            except Exception:
                pass
            # self.findChild(QStatusBar).showMessage(f"加载失败: {e}")
            # 可以在这里添加重试逻辑，比如弹窗询问是否重试，或者自动重试几次
            
        finally:
            self._loading_more = False
            if updates_disabled:
                if grid_view is not None:
                    grid_view.setUpdatesEnabled(True)
                if thumbnails_container is not None:
                    thumbnails_container.setUpdatesEnabled(True)
                    thumbnails_container.update()
            try:
                QTimer.singleShot(0, self._maybe_apply_pending_restore)
            except Exception:
                pass
            t1 = time.perf_counter()
            try:
                total = len(self.all_image_files or [])
            except Exception:
                total = 0
            try:
                LogManager.instance().debug(
                    f"[UI] load_more_thumbnails done: {self.current_loaded_count}/{total} in {t1 - t0:.3f}s"
                )
            except Exception:
                pass
            if task_id is not None:
                StatusManager.instance().finish_task(task_id)


    def _update_thumbnails_with_list(self, files_list):
        """使用指定的文件列表更新缩略图"""
        try:
            LogManager.instance().debug(f"[UI] _update_thumbnails_with_list called with {len(files_list)} files.")
        except Exception:
            pass
        try:
            self._thumbnail_request_id = int(getattr(self, "_thumbnail_request_id", 0)) + 1
        except Exception:
            self._thumbnail_request_id = 1
        try:
            self.thumbnail_loader.set_active_request_id(self._thumbnail_request_id)
        except Exception:
            pass
        try:
            self._pending_updates.clear()
        except Exception:
            pass
        try:
            if self._update_timer.isActive():
                self._update_timer.stop()
        except Exception:
            pass
        try:
            self._current_visible_path_keys = set()
            self._pending_visible_path_keys = set()
        except Exception:
            pass
        try:
            cur_key = self._get_folder_view_state_key(getattr(self, "current_folder_path", "") or "")
            if (not cur_key) or (cur_key != (getattr(self, "_pending_restore_folder_key", None) or "")):
                self._pending_restore_applied = True
        except Exception:
            pass
        if self._startup_mask_enabled:
            self._startup_mask_ready = False
            self._startup_pending_paths.clear()
            self._show_startup_mask("正在加载缩略图...")
            QTimer.singleShot(200, self._reconcile_missing_thumbnails)

        try:
            self._prefill_focus_points_from_db(files_list)
        except Exception:
            pass

        self.all_image_files = files_list
        self.current_loaded_count = 0
        self._select_all_active = False
        self.is_lazy_loading = True
        self._requested_paths = set()
        
        self.grid_view.clear_thumbnails()
        self._thumb_by_path.clear()
        
        self.stats_changed.emit(len(files_list), self.current_loaded_count, self.get_selected_count())
        
        # Start preloading background task for this list
        if files_list:
            try:
                self.cache_manager.stop_preload()
                cache_type = getattr(self, 'current_cache_type', 'general')
                limit = 500
                if hasattr(self.cache_manager, 'max_cache_size'):
                     if cache_type == 'species':
                         limit = getattr(self.cache_manager, 'species_cache_size', 200)
                     elif cache_type == 'fav':
                         limit = getattr(self.cache_manager, 'fav_cache_size', 200)
                     else:
                         limit = getattr(self.cache_manager, 'max_cache_size', 500)
                
                paths = []
                for f in (files_list or [])[:limit]:
                    if not isinstance(f, dict):
                        continue
                    p = f.get("path") or f.get("file_path") or f.get("filepath")
                    if p:
                        paths.append(p)
                self.cache_manager.preload(paths, cache_type=cache_type)
            except Exception:
                pass

        if not files_list:
            self.is_lazy_loading = False
            self._startup_mask_ready = True
            return
        QTimer.singleShot(0, self.load_more_thumbnails)
        try:
            QTimer.singleShot(120, lambda: self._schedule_visible_load(immediate=True))
        except Exception:
            pass
        try:
            if not getattr(self, "_startup_mask_enabled", False):
                QTimer.singleShot(500, lambda: self._reconcile_missing_thumbnails(2))
        except Exception:
            pass

    def _prefill_focus_points_from_db(self, files_list):
        if not files_list:
            return
        try:
            db = getattr(self, "db", None)
        except Exception:
            db = None
        if db is None:
            return
        paths = []
        for it in (files_list or [])[:1500]:
            if not isinstance(it, dict):
                continue
            if it.get("focus_point"):
                continue
            p = it.get("path")
            if p:
                paths.append(str(p))
        if not paths:
            return
        try:
            db_paths = [db._normalize_file_path_for_db(p) for p in paths]
            records = db.get_results_by_paths(db_paths, table_name="bird_results") or {}
            rec_norm = {db._norm_path_key(k): v for k, v in records.items() if k}
        except Exception:
            rec_norm = {}
        if not rec_norm:
            return
        for it in (files_list or [])[:1500]:
            if not isinstance(it, dict):
                continue
            if it.get("focus_point"):
                continue
            p = it.get("path")
            if not p:
                continue
            key = db._norm_path_key(p)
            rec = rec_norm.get(key)
            if isinstance(rec, dict) and rec.get("focus_point"):
                it["focus_point"] = rec.get("focus_point")

    def _schedule_focus_point_backfill(self, files_list):
        return

    def _apply_focus_point_updates(self, updates: dict):
        if not isinstance(updates, dict) or not updates:
            return
        target_keys = {self._normalize_path_key(k) for k in updates.keys() if k}
        if not target_keys:
            return
        for lst in (getattr(self, "raw_image_files", []), getattr(self, "image_files", []), getattr(self, "all_image_files", [])):
            try:
                for img in lst:
                    if not isinstance(img, dict):
                        continue
                    p = img.get("path")
                    if not p:
                        continue
                    k = self._normalize_path_key(p)
                    if k in target_keys:
                        u = updates.get(k) or updates.get(p) or {}
                        if isinstance(u, dict) and u.get("focus_point"):
                            img["focus_point"] = u.get("focus_point")
            except Exception:
                pass
        try:
            file_paths = []
            for k in target_keys:
                for img in getattr(self, "all_image_files", []):
                    if self._normalize_path_key(img.get("path")) == k:
                        file_paths.append(img.get("path"))
                        break
            if file_paths:
                self.grid_view.refresh_specific_thumbnails(file_paths)
        except Exception:
            pass

    def on_save_filter(self):
        """保存过滤条件"""
        conditions = self.filter_panel.get_all_conditions()
        
        # 使用 CustomInputDialog 替代原生 QInputDialog，保持 UI 风格一致
        from ui.widgets.custom_input_dialog import CustomInputDialog
        dialog = CustomInputDialog(self, "保存过滤方案", "方案名称:", "")
        self._suspend_filter_panel_auto_hide = True
        try:
            if not dialog.exec():
                return
            name = dialog.get_value()
            if not name:
                return

            # 检查非法字符
            if any(c in name for c in '<>:"/\\|?*'):
                NotificationManager.instance().show_warning("错误", "方案名称包含非法字符")
                return
            
            # 确保目录存在
            from utils.paths import PathManager
            pm = PathManager.instance()
            save_dir = str(pm.get_user_data_path() / "filter")
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            
            file_path = os.path.join(save_dir, f"{name}.bft")
            
            # 如果文件存在，询问是否覆盖
            if os.path.exists(file_path):
                if not NotificationManager.instance().ask_confirmation("确认覆盖", f"方案 '{name}' 已存在，是否覆盖？"):
                    return

            try:
                # 获取当前星级
                rating = self.star_rating.rating if hasattr(self, 'star_rating') else 0
                
                # 构造保存数据
                save_data = {
                    "filters": conditions,
                    "rating": rating
                }
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
                NotificationManager.instance().show_toast("过滤方案已保存")
            except Exception as e:
                NotificationManager.instance().show_warning("错误", f"保存失败: {e}")
        finally:
            self._suspend_filter_panel_auto_hide = False

    def on_load_filter(self):
        """加载过滤条件"""
        from utils.paths import PathManager
        pm = PathManager.instance()
        save_dir = str(pm.get_user_data_path() / "filter")
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        try:
            legacy_dir = str(pm.get_app_data_path() / "filter")
        except Exception:
            legacy_dir = os.path.join(os.getcwd(), "data", "filter")
        try:
            if os.path.isdir(legacy_dir):
                for name in os.listdir(legacy_dir):
                    if not str(name).lower().endswith(".bft"):
                        continue
                    src = os.path.join(legacy_dir, str(name))
                    dst = os.path.join(save_dir, str(name))
                    try:
                        if os.path.exists(dst):
                            continue
                    except Exception:
                        pass
                    try:
                        with open(src, "rb") as rf:
                            data = rf.read()
                        with open(dst, "wb") as wf:
                            wf.write(data)
                    except Exception:
                        pass
        except Exception:
            pass
            
        # 获取所有 .bft 文件
        files = [f for f in os.listdir(save_dir) if f.endswith('.bft')]
        
        if not files:
            NotificationManager.instance().show_toast("没有找到已保存的搜索方案")
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QListWidget, QListWidgetItem

        class _FilterPresetLoadDialog(QDialog):
            def __init__(self, parent, preset_files, preset_dir):
                super().__init__(parent)
                self._preset_files = preset_files
                self._preset_dir = preset_dir
                self._selected_path = None
                self.setWindowTitle("加载过滤方案")
                self.setModal(True)
                self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                self.resize(520, 420)

                main_layout = QVBoxLayout(self)
                main_layout.setContentsMargins(10, 10, 10, 10)

                self.container = QWidget()
                self.container.setObjectName("container")
                cm = ColorManager.instance()
                container_bg = cm.get("popup.background.primary")
                border_color = cm.get("popup.border.primary")
                text_dark = cm.get("theme.text.dark")
                text_light = cm.get("theme.text.light")
                header_bg = cm.get("popup.header.background")
                header_text = cm.get("popup.header.text")
                primary = cm.get("theme.primary")
                light_bg = cm.get("theme.background.light")
                dark_bg = cm.get("theme.background.dark")
                list_bg = container_bg
                self.container.setStyleSheet(f"""
                    QWidget#container {{
                        background-color: {container_bg};
                        border: 1px solid {border_color};
                        border-radius: 8px;
                    }}
                """)
                container_layout = QVBoxLayout(self.container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.setSpacing(0)

                title_bar = QWidget()
                title_bar.setFixedHeight(40)
                title_bar.setStyleSheet(f"""
                    QWidget {{
                        background-color: {header_bg};
                        border-top-left-radius: 8px;
                        border-top-right-radius: 8px;
                        border-bottom: 1px solid {header_bg};
                    }}
                """)
                title_layout = QHBoxLayout(title_bar)
                title_layout.setContentsMargins(15, 0, 5, 0)
                title_label = QLabel("加载过滤方案")
                title_label.setStyleSheet(f"""
                    color: {header_text};
                    font-size: 14px;
                    font-weight: bold;
                    border: none;
                    background: transparent;
                """)
                title_layout.addWidget(title_label)
                title_layout.addStretch()
                close_btn = QPushButton()
                close_btn.setIcon(qta.icon('mdi6.close', color=header_text))
                close_btn.setFixedSize(30, 30)
                close_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        border: none;
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {dark_bg};
                    }}
                """)
                close_btn.clicked.connect(self.reject)
                title_layout.addWidget(close_btn)
                container_layout.addWidget(title_bar)

                content_widget = QWidget()
                content_widget.setStyleSheet(f"background-color: {list_bg};")
                content_layout = QVBoxLayout(content_widget)
                content_layout.setContentsMargins(20, 20, 20, 20)
                content_layout.setSpacing(10)

                header = QLabel("选择一个已保存的过滤方案")
                header.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {text_dark};")
                content_layout.addWidget(header)

                self.list_widget = QListWidget()
                self.list_widget.setStyleSheet(f"""
                    QListWidget {{
                        border: 1px solid {border_color};
                        border-radius: 4px;
                        background-color: {list_bg};
                        color: {text_dark};
                    }}
                    QListWidget::item {{
                        padding: 8px 10px;
                        border-radius: 2px;
                    }}
                    QListWidget::item:selected {{
                        background-color: {primary};
                        color: {text_light};
                    }}
                    QListWidget::item:hover {{
                        background-color: {dark_bg};
                    }}
                """)
                for fn in self._preset_files:
                    display_name = os.path.splitext(fn)[0]
                    item = QListWidgetItem(display_name)
                    item.setData(Qt.ItemDataRole.UserRole, fn)
                    self.list_widget.addItem(item)
                self.list_widget.itemDoubleClicked.connect(self._accept_current)
                self.list_widget.currentItemChanged.connect(self._on_current_changed)
                content_layout.addWidget(self.list_widget, 1)

                action_row = QHBoxLayout()
                self.delete_btn = QPushButton("删除")
                self.delete_btn.setFixedHeight(36)
                self.delete_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {light_bg};
                        color: {text_dark};
                        border: 1px solid {border_color};
                        border-radius: 4px;
                        padding: 0px 12px;
                    }}
                    QPushButton:hover {{
                        background-color: {dark_bg};
                    }}
                """)
                self.delete_btn.clicked.connect(self._delete_current)
                self.delete_btn.setEnabled(False)
                action_row.addWidget(self.delete_btn)
                action_row.addStretch()
                content_layout.addLayout(action_row)

                container_layout.addWidget(content_widget)

                btn_widget = QWidget()
                btn_widget.setObjectName("bottomBar")
                btn_widget.setFixedHeight(60)
                btn_widget.setStyleSheet(f"""
                    QWidget#bottomBar {{
                        border-bottom-left-radius: 8px;
                        border-bottom-right-radius: 8px;
                        background-color: {dark_bg};
                        border-top: 1px solid {border_color};
                    }}
                """)
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(0, 0, 20, 0)
                btn_layout.setSpacing(10)
                btn_layout.addStretch()

                cancel_btn = QPushButton("取消")
                cancel_btn.setFixedSize(80, 32)
                cancel_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {light_bg};
                        color: {text_dark};
                        border: 1px solid {border_color};
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {dark_bg};
                    }}
                """)
                cancel_btn.clicked.connect(self.reject)

                self.confirm_btn = QPushButton("确定")
                self.confirm_btn.setFixedSize(80, 32)
                self.confirm_btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {primary};
                        color: {text_light};
                        border: none;
                        border-radius: 4px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background-color: {dark_bg};
                    }}
                    QPushButton:pressed {{
                        background-color: {primary};
                    }}
                    QPushButton:disabled {{
                        background-color: {border_color};
                    }}
                """)
                self.confirm_btn.clicked.connect(self._accept_current)
                self.confirm_btn.setEnabled(False)

                btn_layout.addWidget(cancel_btn)
                btn_layout.addWidget(self.confirm_btn)
                container_layout.addWidget(btn_widget)

                main_layout.addWidget(self.container)

                if self.list_widget.count() > 0:
                    self.list_widget.setCurrentRow(0)

            def _on_current_changed(self, current, previous):
                enabled = current is not None
                self.confirm_btn.setEnabled(enabled)
                self.delete_btn.setEnabled(enabled)

            def _accept_current(self, *args, **kwargs):
                item = self.list_widget.currentItem()
                if not item:
                    return
                fn = item.data(Qt.ItemDataRole.UserRole)
                if not fn:
                    return
                self._selected_path = os.path.join(self._preset_dir, str(fn))
                self.accept()

            def _delete_current(self):
                item = self.list_widget.currentItem()
                if not item:
                    return
                fn = item.data(Qt.ItemDataRole.UserRole)
                if not fn:
                    return
                display_name = item.text()
                fp = os.path.join(self._preset_dir, str(fn))
                if not NotificationManager.instance().ask_confirmation("确认删除", f"确定要删除方案 '{display_name}' 吗？"):
                    return
                try:
                    os.remove(fp)
                    NotificationManager.instance().show_toast(f"方案 '{display_name}' 已删除")
                except Exception as e:
                    NotificationManager.instance().show_warning("错误", f"删除失败: {e}")
                    return

                row = self.list_widget.row(item)
                self.list_widget.takeItem(row)
                if self.list_widget.count() == 0:
                    self._selected_path = None
                    self.reject()

            def get_selected_path(self):
                return self._selected_path

        dialog = _FilterPresetLoadDialog(self, files, save_dir)
        self._suspend_filter_panel_auto_hide = True
        try:
            if not dialog.exec():
                return
            fp = dialog.get_selected_path()
            if not fp:
                return
            self._load_filter_file(fp)
        finally:
            self._suspend_filter_panel_auto_hide = False

    def show_exif_write_dialog(self, image_path):
        # 优先使用选中的文件
        selected_files = self.get_selected_files()
        file_paths = []
        
        # 只有当 image_path 在选中列表中，或者没有选中列表时，才使用选中列表
        # 如果 image_path 不在选中列表中（例如右键没选中的项目），则只处理该项目
        # 但 on_thumbnail_context_menu 已经处理了自动选中，所以通常 image_path 就在选中列表中
        
        if selected_files:
            file_paths = [f['path'] for f in selected_files]
        elif image_path:
             file_paths = [image_path]
             
        if not file_paths:
            return

        from ui.widgets.exif_write_dialog import ExifWriteDialog
        dialog = ExifWriteDialog(self, file_paths=file_paths)
        if not dialog.exec():
            return
        tags = dialog.get_tag_dict()
        if not tags:
            NotificationManager.instance().show_toast("未填写任何Exif标签")
            return
            
        exif_tasks = [(path, tags) for path in file_paths]
        
        def run_update():
            task_id = StatusManager.instance().start_task(f"正在写入Exif ({len(file_paths)} 张)...")
            try:
                ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
                NotificationManager.instance().show_toast(f"Exif写入完成")
            except Exception as e:
                NotificationManager.instance().show_warning("错误", f"写入Exif失败: {e}")
            finally:
                StatusManager.instance().finish_task(task_id)

        threading.Thread(target=run_update, daemon=True).start()
        NotificationManager.instance().show_toast(f"正在后台写入 {len(file_paths)} 张图片的Exif信息...")

    def show_exif_read_dialog(self, image_path):
        from ui.widgets.exif_read_dialog import ExifReadDialog
        dialog = ExifReadDialog(self, image_path=image_path)
        if not dialog.exec():
            return
        tag_name = dialog.get_tag_name()
        if not tag_name:
            NotificationManager.instance().show_toast("未填写要读取的标签名")
            return
        if ":" in tag_name:
            prefix, rest = tag_name.split(":", 1)
            prefix_low = prefix.strip().lower()
            if prefix_low == "xmp":
                tag_name = f"XMP:{rest.strip()}"
            elif prefix_low == "xmp-bmp":
                tag_name = f"XMP-bmp:{rest.strip()}"
        worker = ExifHandleWorker.get_instance()
        try:
            value = worker.read_tag(image_path, tag_name)
            if value is None or value == "":
                msg = f"{tag_name}: (无值)"
            else:
                msg = f"{tag_name}: {value}"
            NotificationManager.instance().show_toast(msg)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"读取Exif失败: {e}")

    def _load_filter_file(self, file_path):
        """执行加载文件逻辑"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 兼容旧版本 (list) 和新版本 (dict)
            if isinstance(data, list):
                conditions = data
                rating = 0
            elif isinstance(data, dict):
                conditions = data.get("filters", [])
                rating = data.get("rating", 0)
            else:
                NotificationManager.instance().show_warning("错误", "文件格式不正确")
                return

            # 设置过滤条件
            self.filter_panel.set_conditions(conditions)
            
            # 设置星级
            if hasattr(self, 'star_rating'):
                # 使用 emit_signal=False 避免 toggle 行为，然后手动触发更新
                self.star_rating.set_rating(rating, emit_signal=False)
                self.on_toolbar_rating_changed(rating)
            
            # 加载后自动展开面板
            if not self.filter_btn.isChecked():
                self.filter_btn.setChecked(True)
            NotificationManager.instance().show_toast("方案已加载")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"加载失败: {e}")


    def on_wheel_zoom(self, delta):
        """Ctrl+滚轮缩放：调整滑块值"""
        current_value = self.preview_slider.value()
        # 每次滚动改变5个单位，向上滚动(delta>0)放大(值增加)
        step = 5 if delta > 0 else -5
        # 修复：滑块最大值可能已被调整为200（在ToolbarView中），这里硬编码100会导致无法滚到最大
        max_val = self.preview_slider.maximum()
        new_value = max(0, min(max_val, current_value + step))
        self.preview_slider.setValue(new_value)

    def on_splitter_moved(self, pos, index):
        """分隔器拖动时重新计算缩略图尺寸和布局"""
        try:
            if bool(getattr(self, "_splitter_preview_clamp", False)):
                raise Exception("skip")
            sizes = list(self.content_splitter.sizes())
            if len(sizes) >= 3:
                try:
                    max_w = int(self.preview_panel.maximumWidth() or 800)
                except Exception:
                    max_w = 800
                if max_w > 0 and int(sizes[2]) > int(max_w):
                    self._splitter_preview_clamp = True
                    try:
                        delta = int(sizes[2]) - int(max_w)
                        sizes[2] = int(max_w)
                        sizes[1] = max(0, int(sizes[1]) + int(delta))
                        self.content_splitter.setSizes(sizes)
                    finally:
                        self._splitter_preview_clamp = False
        except Exception:
            try:
                self._splitter_preview_clamp = False
            except Exception:
                pass
        if hasattr(self, 'scroll_area') and hasattr(self, 'preview_slider'):
            self._pending_thumb_size = self.calculate_thumb_size(self.preview_slider.value())
            self._pending_splitter_update = True
            self.resize_timer.start()

    def _on_thumbnail_slider_pressed(self):
        """处理缩略图大小滑块按下"""
        self._is_slider_dragging = True

    def _on_thumbnail_slider_released(self):
        """处理缩略图大小滑块释放"""
        self._is_slider_dragging = False
        if hasattr(self, 'preview_slider'):
            self._pending_thumb_size = self.calculate_thumb_size(self.preview_slider.value())
            self._perform_resize()

    def eventFilter(self, obj, event):
        """全局事件过滤器，处理点击外部关闭面板"""
        if obj == getattr(self, "grid_view", None) and event.type() == QEvent.Type.Resize:
            if self._startup_mask_visible and hasattr(self, "_startup_mask"):
                self._startup_mask.setGeometry(self.grid_container.rect())
        if hasattr(self, "grid_view") and obj == self.grid_view.scroll_area.viewport():
            if event.type() == QEvent.Type.Resize:
                try:
                    if hasattr(self, "preview_slider") and self.preview_slider is not None:
                        if bool(getattr(self, "_suppress_max_thumb_recalc", False)):
                            return super().eventFilter(obj, event)
                        if int(self.preview_slider.value()) == int(self.preview_slider.maximum() or 0):
                            w = int(self.grid_view.scroll_area.viewport().width() or 0)
                            last_w = int(getattr(self, "_last_max_thumb_viewport_w", 0) or 0)
                            if w > 0 and abs(int(w) - int(last_w)) >= 8:
                                self._last_max_thumb_viewport_w = int(w)
                                self._pending_thumb_size = self.calculate_thumb_size(self.preview_slider.value())
                                try:
                                    t = getattr(self, "_max_thumb_recalc_timer", None)
                                except Exception:
                                    t = None
                                if t is None:
                                    t = QTimer(self)
                                    t.setSingleShot(True)
                                    t.timeout.connect(self._perform_resize)
                                    self._max_thumb_recalc_timer = t
                                t.start(80)
                except Exception:
                    pass
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.Wheel):
                self._mouse_busy = True
                if hasattr(self, "thumbnail_loader"):
                    self.thumbnail_loader.set_max_thread_count(self._mouse_busy_loader_threads)
                if self._mouse_busy_timer.isActive():
                    self._mouse_busy_timer.stop()
                self._mouse_busy_timer.start(60)
        if event.type() == QEvent.Type.MouseButtonPress:
            # 检查文件夹搜索面板
            if hasattr(self, 'folder_panel') and hasattr(event, 'globalPosition'):
                self.folder_panel.handle_click_outside(event.globalPosition().toPoint())

            # 检查过滤面板
            if hasattr(self, 'filter_panel') and self.filter_panel.isVisible():
                if getattr(self, "_suspend_filter_panel_auto_hide", False):
                    return super().eventFilter(obj, event)
                if not self._is_click_inside(obj, [self.filter_panel, self.filter_btn], event):
                    self.filter_btn.setChecked(False)
                    
        return super().eventFilter(obj, event)

    def _is_click_inside(self, obj, widgets, event=None):
        """检查点击对象是否在指定控件列表中"""
        if event and hasattr(event, 'globalPosition'):
            try:
                click_pos = event.globalPosition().toPoint()
                popup = QApplication.activePopupWidget()
                if popup and popup.isVisible():
                    rect = QRect(popup.mapToGlobal(QPoint(0, 0)), popup.size())
                    if rect.contains(click_pos):
                        return True
            except Exception:
                pass

        # 1. 检查对象层级
        if obj:
            for widget in widgets:
                if self._is_ancestor_or_self(widget, obj):
                    return True
                
                # 特殊处理 QComboBox 的弹出列表
                # 因为弹出列表可能是独立的顶级窗口，层级检查无法覆盖
                if isinstance(widget, QWidget):
                    combos = widget.findChildren(QComboBox)
                    for combo in combos:
                        view = combo.view()
                        if view:
                            # 检查 obj 是否是 view 本身或其子孙
                            if self._is_ancestor_or_self(view, obj):
                                return True
                            # 检查 obj 是否是 view 的 viewport
                            if view.viewport() == obj:
                                return True
                            # 检查 obj 是否在 view 所在的窗口内 (处理 Popup)
                            if view.window() and self._is_ancestor_or_self(view.window(), obj):
                                return True
                            
                            # 终极大法：如果 view 是可见的，且 obj 是 view 的子组件
                            # 有时候 view.window() 返回的不是预期的，或者层级太深
                            # 我们直接检查 obj 是否属于 view 的 children
                            if view.isVisible():
                                if obj in view.findChildren(QObject):
                                    return True
                                    
                            # 新增：检查点击是否在 view 的全局几何范围内
                            # 处理当下拉列表超出父窗口边界时的情况
                            if view and view.isVisible():
                                try:
                                    # 尝试获取 view 所在的顶层窗口（通常是 Popup）
                                    popup_window = view.window()
                                    if popup_window:
                                        # 检查点击位置是否在 popup 窗口内
                                        if event and hasattr(event, 'globalPosition'):
                                            click_pos = event.globalPosition().toPoint()
                                            # 使用 mapToGlobal 获取绝对坐标，更可靠，特别是对于独立的 Popup 窗口
                                            try:
                                                global_pos = popup_window.mapToGlobal(QPoint(0, 0))
                                                win_rect = QRect(global_pos, popup_window.size())
                                                if win_rect.contains(click_pos):
                                                    return True
                                            except Exception:
                                                pass
                                            
                                            # 后备检查：直接使用 pos (如果 popup 是顶级窗口)
                                            win_rect = QRect(popup_window.pos(), popup_window.size())
                                            if win_rect.contains(click_pos):
                                                return True
                                except:
                                    pass

                    try:
                        from PyQt6.QtWidgets import QDateTimeEdit
                        edits = widget.findChildren(QDateTimeEdit)
                    except Exception:
                        edits = []
                    for edit in edits:
                        try:
                            cal = edit.calendarWidget()
                        except Exception:
                            cal = None
                        if not cal:
                            continue
                        try:
                            if self._is_ancestor_or_self(cal, obj):
                                return True
                        except Exception:
                            pass
                        try:
                            popup_window = cal.window()
                        except Exception:
                            popup_window = None
                        if popup_window and getattr(popup_window, "isVisible", None) and popup_window.isVisible():
                            try:
                                if event and hasattr(event, 'globalPosition'):
                                    click_pos = event.globalPosition().toPoint()
                                    win_rect = QRect(popup_window.pos(), popup_window.size())
                                    if win_rect.contains(click_pos):
                                        return True
                            except Exception:
                                pass
        
        # 2. 检查几何位置 (如果有事件信息)
        if event and hasattr(event, 'globalPosition'):
            try:
                click_pos = event.globalPosition().toPoint()
                for widget in widgets:
                    if widget and widget.isVisible():
                        # 获取控件在屏幕上的矩形
                        rect = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
                        if rect.contains(click_pos):
                            return True
            except:
                pass
                
        return False

    def _is_ancestor_or_self(self, widget, target):
        """检查 target 是否是 widget 的子孙或自身"""
        if not widget or not target:
            return False
        tmp = target
        while tmp:
            if tmp == widget:
                return True
            # 处理 popup/menu 等没有 parent() 但有 parentWidget() 的情况
            if tmp.parent():
                tmp = tmp.parent()
            elif hasattr(tmp, 'parentWidget') and tmp.parentWidget():
                tmp = tmp.parentWidget()
            else:
                break
        return False

    def _update_event_filter_state(self):
        """更新全局事件过滤器状态"""
        needs_filter = False
        if self.folder_search_btn.isChecked() or self.filter_btn.isChecked():
            needs_filter = True
            
        if needs_filter and not self._event_filter_installed:
            QApplication.instance().installEventFilter(self)
            self._event_filter_installed = True
        elif not needs_filter and self._event_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._event_filter_installed = False

    def resizeEvent(self, event):
        """窗口大小改变时重新排列缩略图（不改变缩略图大小）"""
        super().resizeEvent(event)
        if hasattr(self, 'grid_view') and hasattr(self, 'scroll_area'):
            # 只重新排列，不重新计算缩略图大小（保持固定大小）
            self.grid_view.arrange_thumbnails()
            scrollbar = self.scroll_area.verticalScrollBar()
            self.on_scroll_value_changed(scrollbar.value())
        if hasattr(self, 'preview_slider'):
            new_size = self.calculate_thumb_size(self.preview_slider.value())
            if new_size != self.current_thumb_size:
                self.current_thumb_size = new_size
                self.grid_view.set_thumbnail_size(self.current_thumb_size)
        
        # 如果预览区有图片，重新缩放
        self.update_preview_image_size()

    def on_preview_visibility_changed(self, visible):
        """预览区域可见性改变时处理"""
        self.settings_manager.set("library/preview_visible", visible)
        try:
            if hasattr(self, "info_panel") and self.info_panel is not None:
                # 只有当信息面板不是收起状态时才设置可见性
                # 避免覆盖信息面板的收起状态
                if not getattr(self.info_panel, "_vert_collapsed", False):
                    self.info_panel.setVisible(bool(visible))
        except Exception:
            pass
        try:
            self.content_splitter.setProperty("preview_collapsed", not bool(visible))
            self._apply_theme_styles()
        except Exception:
            pass
        
        current_sizes = self.content_splitter.sizes()
        if len(current_sizes) < 3:
            return

        if visible:
            # 恢复宽度
            saved_width = int(self.settings_manager.get("library/preview_width", 280))
            preview_width = max(150, min(saved_width, 800)) # 限制在合理范围内
            
            # 保持左侧文件夹树宽度不变
            self.content_splitter.setSizes([current_sizes[0], current_sizes[1] - (preview_width - current_sizes[2]), preview_width])
            
            # 恢复 Splitter 拖动 (Handle index 2 is between widget 1 and 2)
            handle = self.content_splitter.handle(2)
            if handle:
                handle.setEnabled(True)
                handle.setCursor(Qt.CursorShape.SplitHCursor)
                
            # 重新排列缩略图以适应新的布局
            QTimer.singleShot(100, self.grid_view.arrange_thumbnails)
            # 恢复预览图片显示
            QTimer.singleShot(150, self.update_preview_image_size)
        else:
            # 保存当前宽度（仅当当前宽度大于最小折叠宽度时）
            if current_sizes[2] > 100:
                 self.settings_manager.set("library/preview_width", current_sizes[2])

            # 获取当前分割器大小，调整比例让图片库扩展
            # 右侧保留30px的"把手"空间，确保有足够的点击区域，同时不显示内容
            # 将预览面板的宽度设为最小，图片库自动扩展
            # 保持左侧文件夹树宽度不变
            self.content_splitter.setSizes([current_sizes[0], current_sizes[1] + (current_sizes[2] - 30), 30])
            
            # 禁用 Splitter 拖动
            handle = self.content_splitter.handle(2)
            if handle:
                handle.setEnabled(False)
                handle.setCursor(Qt.CursorShape.ArrowCursor)
            
            # 重新排列缩略图以适应新的布局
            QTimer.singleShot(100, self.grid_view.arrange_thumbnails)

    def on_folder_selected(self, folder_path, depth=0):
        """文件夹选择时加载图片"""
        if not folder_path or folder_path == "__placeholder__":
            return
        try:
            current_fp = str(getattr(self, "current_folder_path", "") or "")
        except Exception:
            current_fp = ""
        try:
            if isinstance(folder_path, str) and folder_path.startswith("virtual://taxonomy"):
                if str(folder_path) == str(current_fp):
                    if not (self.showing_search_results or self.filter_panel.has_conditions()):
                        try:
                            self._schedule_visible_load(immediate=True)
                        except Exception:
                            pass
                        return
            else:
                fp_norm = self._normalize_path_str(folder_path)
                if os.path.isfile(fp_norm):
                    fp_norm = os.path.dirname(fp_norm)
                cur_norm = self._normalize_path_str(current_fp)
                if cur_norm and fp_norm and os.path.normcase(os.path.normpath(cur_norm)) == os.path.normcase(os.path.normpath(fp_norm)):
                    if not (self.showing_search_results or self.filter_panel.has_conditions()):
                        try:
                            self._schedule_visible_load(immediate=True)
                        except Exception:
                            pass
                        return
        except Exception:
            pass
        try:
            if isinstance(folder_path, str) and folder_path.startswith("virtual://taxonomy"):
                try:
                    if current_fp and str(folder_path) != str(current_fp):
                        self._persist_folder_view_state_now()
                except Exception:
                    pass
                try:
                    self._set_pending_restore_for_folder(str(folder_path))
                except Exception:
                    pass
                self.current_folder_path = str(folder_path)
                self.load_images_from_taxonomy(str(folder_path))
                try:
                    if depth < 4:
                        uri = str(folder_path)
                        try:
                            root_dir = str(self.settings_manager.get("general/root_path", "") or "")
                        except Exception:
                            root_dir = ""
                        if uri == "virtual://taxonomy/unclassified":
                            title = "未分类"
                            stats = self.db.get_taxonomy_node_stats(unclassified=True, table_name="bird_results", root_path=root_dir)
                        else:
                            parsed = urlparse(uri.replace("virtual://taxonomy", "http://taxonomy", 1))
                            qs = parse_qs(parsed.query or "")
                            o = (qs.get("order") or [""])[0]
                            f = (qs.get("family") or [""])[0]
                            g = (qs.get("genus") or [""])[0]
                            s = (qs.get("species") or [""])[0]
                            title = s or g or f or o or "分类"
                            stats = self.db.get_taxonomy_node_stats(
                                order_cls=o or None,
                                family_cls=f or None,
                                genus_cls=g or None,
                                species_cls=s or None,
                                unclassified=False,
                                table_name="bird_results",
                                root_path=root_dir,
                            )
                        self.preview_panel.show_folder_stats(title, stats)
                except Exception:
                    pass
                return
        except Exception:
            pass
        folder_path = self._normalize_path_str(folder_path)
        # 如果是文件路径，获取父目录
        if os.path.isfile(folder_path):
            folder_path = os.path.dirname(folder_path)
        if not os.path.isdir(folder_path):
            return

        try:
            if current_fp and self._normalize_path_str(current_fp) != self._normalize_path_str(folder_path):
                self._persist_folder_view_state_now()
        except Exception:
            pass
        try:
            self._set_pending_restore_for_folder(str(folder_path))
        except Exception:
            pass
        self.current_folder_path = folder_path
        self.settings_manager.set("library/last_folder", folder_path)
        try:
            self.settings_manager.sync()
        except Exception:
            pass
        self.load_images_from_folder(folder_path)

        # 更新文件夹统计信息到预览区 (PreviewPanel)
        try:
            # 只有当深度 < 4 时才显示统计信息 (即选中目、科、属时显示，选中种文件夹时不显示)
            if depth < 4:
                stats = self.db.get_folder_stats(folder_path)
                folder_name = os.path.basename(folder_path)
                self.preview_panel.show_folder_stats(folder_name, stats)
        except Exception as e:
            try:
                LogManager.instance().warning(f"更新文件夹统计失败: {e}")
            except Exception:
                pass

    def load_images_from_taxonomy(self, taxonomy_uri: str):
        self.clear_preview()
        self.current_folder_path = str(taxonomy_uri or "")
        
        # Save to history/settings
        try:
             self.settings_manager.set("library/last_folder", self.current_folder_path)
             # Also save folder view mode
             self.settings_manager.set("ui/library_view_mode", "taxonomy")
             try:
                 self.settings_manager.sync()
             except Exception:
                 pass
        except:
             pass
        
        self.showing_search_results = False
        self.favorite_filter = False
        self.rating_filter = 0
        self.fav_btn.blockSignals(True)
        self.fav_btn.setChecked(False)
        self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
        self.fav_btn.blockSignals(False)
        self.star_rating.set_rating(0, emit_signal=False)
        
        # 不要停止预加载，如果正在加载相同的图片集，可以复用
        # self.cache_manager.stop_preload() 
        # 但为了避免加载之前的旧文件夹内容，还是停止比较好。
        # 关键是 _update_thumbnails_with_list 里会重启预加载。
        self.cache_manager.stop_preload()
        
        try:
            self.big_image_cache.clear()
        except Exception:
            pass
        
        # 不要立即清空 image_files，这样在加载新列表前还能保持显示（虽然这可能导致 UI 不一致）
        # 但通常我们会清空。
        # self.image_files = [] 
        
        # 设置当前缓存类型为 species (如果 taxonomy_uri 包含 species 参数，或者本身就是分类浏览)
        # 这有助于 cache_manager 使用 _species_cache
        # 解析 uri
        is_species_view = False
        try:
            if "species=" in taxonomy_uri:
                is_species_view = True
        except:
            pass
            
        if is_species_view:
            self.current_cache_type = 'species'
        else:
            self.current_cache_type = 'general'

        try:
            w = getattr(self, "_folder_load_worker", None)
            if w is not None and w.isRunning():
                w.is_cancelled = True
        except Exception:
            pass
        try:
            w2 = getattr(self, "_taxonomy_load_worker", None)
            if w2 is not None and w2.isRunning():
                w2.is_cancelled = True
        except Exception:
            pass
        
        # 这里不要清空 raw_image_files，等待 worker 完成后再替换
        # self.raw_image_files = [] 
        
        # 显示加载状态，但不清空缩略图? 
        # 如果不清空，用户会看到旧图，然后突然变新图。通常清空比较好。
        # self.update_thumbnails() # 这会清空 grid
        
        # 为了更好的体验，我们可以在 worker 完成后再清空和更新
        # 但需要显示 Loading 指示器
        # 目前 _update_thumbnails_with_list 会负责清空
        
        self.thumbnail_loader.cancel_all()
        try:
            root_dir = str(self.settings_manager.get("general/root_path", "") or "")
        except Exception:
            root_dir = ""
        self._taxonomy_load_worker = TaxonomyLoadWorker(str(taxonomy_uri or ""), self.db, root_path=root_dir)
        self._taxonomy_load_worker.finished.connect(self._on_folder_load_finished)
        self._taxonomy_load_worker.failed.connect(self._on_folder_load_failed)
        self._taxonomy_load_worker.start()
        
        # 显示加载遮罩 (可选，如果 _update_thumbnails_with_list 被延迟调用)
        # self._show_startup_mask("正在加载...")

    def on_folder_clicked(self, folder_path):
        """文件夹点击事件 (用于退出搜索模式)"""
        if not folder_path:
            return
        try:
            if isinstance(folder_path, str) and folder_path.startswith("virtual://taxonomy"):
                if self.current_folder_path and str(folder_path) == str(self.current_folder_path):
                    if self.showing_search_results or self.filter_panel.has_conditions():
                        self.filter_panel.reset_to_default()
                        self.load_images_from_taxonomy(str(self.current_folder_path))
                return
        except Exception:
            pass
        folder_path = self._normalize_path_str(folder_path)
            
        if os.path.isfile(folder_path):
            folder_path = os.path.dirname(folder_path)
            
        # 如果点击的是当前文件夹，且处于搜索模式，则退出搜索
        if self.current_folder_path and os.path.normpath(folder_path) == os.path.normpath(self.current_folder_path):
            if self.showing_search_results or self.filter_panel.has_conditions():
                # 重置过滤面板
                self.filter_panel.reset_to_default()
                # 重新加载文件夹内容 (这会重置 showing_search_results)
                self.load_images_from_folder(self.current_folder_path)

    def on_folder_renamed_from_panel(self, old_path, new_path):
        """文件夹在面板中重命名后更新"""
        try:
            root_dir = self.settings_manager.get("general/root_path") or ""
            self.db.update_folder_paths_and_taxonomy(old_path, new_path, root_path=root_dir, table_name="bird_results")
        except Exception:
            pass
        # 如果当前显示的文件夹是被重命名的文件夹（或其子文件夹），需要更新路径
        if self.current_folder_path and self.current_folder_path.startswith(old_path):
            # 更新当前文件夹路径
            self.current_folder_path = self.current_folder_path.replace(old_path, new_path, 1)
            self.settings_manager.set("library/last_folder", self.current_folder_path)
            try:
                self.load_images_from_folder(self.current_folder_path)
            except Exception:
                pass

    def on_folder_deleted_from_panel(self, folder_path: str):
        try:
            folder_path = self._normalize_path_str(folder_path)
        except Exception:
            folder_path = str(folder_path or "")
        if not folder_path:
            return
        try:
            self.db.delete_results_under_folder(folder_path, table_name="bird_results")
        except Exception:
            pass
        try:
            if getattr(self, "current_preview_path", None) and str(self.current_preview_path).startswith(folder_path):
                self.clear_preview()
        except Exception:
            pass
        try:
            if getattr(self, "current_folder_path", None) and str(self.current_folder_path).startswith(folder_path):
                parent = os.path.dirname(folder_path)
                if parent and os.path.isdir(parent):
                    self.current_folder_path = parent
                    self.settings_manager.set("library/last_folder", parent)
                    self.load_images_from_folder(parent)
        except Exception:
            pass
            
    def on_import_to_library_succeeded(self, target_folder: str):
        try:
            target = self._normalize_path_str(target_folder)
        except Exception:
            target = str(target_folder or "")
        if target:
            try:
                if hasattr(self, "folder_panel") and self.folder_panel is not None:
                    self.folder_panel.refresh_tree(target_path=target)
            except Exception:
                pass
        try:
            current = self._normalize_path_str(getattr(self, "current_folder_path", "") or "")
        except Exception:
            current = str(getattr(self, "current_folder_path", "") or "")
        if not current:
            if target and os.path.isdir(target):
                try:
                    self.current_folder_path = target
                    self.settings_manager.set("library/last_folder", target)
                    self.load_images_from_folder(target)
                except Exception:
                    pass
            return
        try:
            if target and os.path.normcase(os.path.normpath(current)) == os.path.normcase(os.path.normpath(target)):
                try:
                    self._requested_paths = set()
                except Exception:
                    pass
                self.load_images_from_folder(current)
                return
        except Exception:
            pass
        try:
            if (not os.path.isdir(current)) and target and os.path.isdir(target):
                self.current_folder_path = target
                self.settings_manager.set("library/last_folder", target)
                self.load_images_from_folder(target)
        except Exception:
            pass

    def on_folder_panel_toggled(self, visible):
        """文件夹面板可见性改变"""
        self.folder_tree_visible = visible
        self.settings_manager.set("library/folder_visible", visible)
        
        # 调整分割器
        current_sizes = self.content_splitter.sizes()
        if len(current_sizes) >= 3:
            if visible:
                # 恢复宽度
                saved_width = int(self.settings_manager.get("library/folder_width", 280))
                folder_width = max(180, min(saved_width, 520))
                
                # 保持右侧预览面板宽度不变
                self.content_splitter.setSizes([folder_width, current_sizes[1] - (folder_width - current_sizes[0]), current_sizes[2]])
                
                # 恢复 Splitter 拖动
                handle = self.content_splitter.handle(1)
                if handle:
                    handle.setEnabled(True)
                    handle.setCursor(Qt.CursorShape.SplitHCursor)
            else:
                # 保存当前宽度
                if current_sizes[0] > 50:
                    self.settings_manager.set("library/folder_width", current_sizes[0])
                # 最小化
                # 左侧保留34px的"把手"空间
                self.content_splitter.setSizes([34, current_sizes[1] + (current_sizes[0] - 34), current_sizes[2]])
                
                # 禁用 Splitter 拖动
                handle = self.content_splitter.handle(1)
                if handle:
                    handle.setEnabled(False)
                    handle.setCursor(Qt.CursorShape.ArrowCursor)
                
        # 重新排列缩略图
        QTimer.singleShot(100, self.grid_view.arrange_thumbnails)

    def get_files_for_persistence(self):
        """获取用于持久化缓存的文件列表
        如果当前是搜索结果，则尝试获取当前文件夹的文件列表，
        以避免将搜索结果存入启动缓存。
        """
        current_folder = self._normalize_path_str(self.current_folder_path)
        if self.showing_search_results and current_folder and os.path.isdir(current_folder):
            # 处于搜索模式，扫描当前文件夹
            files = []
            image_extensions = set(ext.lower() for ext in file_utils.img_exts + file_utils.raw_exts)
            try:
                with os.scandir(current_folder) as it:
                    for entry in it:
                        if entry.is_file() and os.path.splitext(entry.name)[1].lower() in image_extensions:
                            files.append({'path': self._normalize_path_str(entry.path)})
                return files
            except Exception:
                # 扫描失败，返回空列表
                return []
        else:
            # 非搜索模式，直接返回当前列表
            return self.image_files

    def clear_preview(self):
        """清空预览面板"""
        self.current_preview_path = None
        if hasattr(self, 'preview_panel'):
            self.preview_panel.load_image(None)
            self.preview_panel.set_rating(0)
        if hasattr(self, 'info_panel'):
            self.info_panel.update_info(None)
        
        # Note: fav_btn and star_rating are now global filters, 
        # so we don't reset them when clearing preview (e.g. deselecting).
        # They are only reset when switching folders.

    def clear_if_showing_folder(self, folder_path):
        if not folder_path:
            return
        try:
            target = self._normalize_path_str(folder_path)
        except Exception:
            target = str(folder_path)
        if not target:
            return
        try:
            current = self._normalize_path_str(getattr(self, "current_folder_path", "") or "")
        except Exception:
            current = str(getattr(self, "current_folder_path", "") or "")
        if not current:
            return
        try:
            t = os.path.normcase(os.path.normpath(target))
            c = os.path.normcase(os.path.normpath(current))
        except Exception:
            t = target
            c = current
        if c == t or c.startswith(t + os.sep):
            try:
                self.clear_preview()
            except Exception:
                pass
            try:
                if hasattr(self, "grid_view") and self.grid_view:
                    self.grid_view.clear_thumbnails()
            except Exception:
                pass
            try:
                self.image_files = []
                self.raw_image_files = []
                self.all_image_files = []
                self.current_loaded_count = 0
            except Exception:
                pass
            try:
                self.current_folder_path = ""
            except Exception:
                pass

    def load_images_from_folder(self, folder_path):
        """从文件夹加载图片文件"""
        self.clear_preview()
        folder_path = self._normalize_path_str(folder_path)
        self.current_folder_path = folder_path
        self.showing_search_results = False # 重置搜索状态
        
        # 重置过滤状态 (切换文件夹时)
        self.favorite_filter = False
        self.rating_filter = 0
        
        # 重置过滤 UI
        self.fav_btn.blockSignals(True)
        self.fav_btn.setChecked(False)
        self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
        self.fav_btn.blockSignals(False)
        self.star_rating.set_rating(0, emit_signal=False)
        
        # 停止之前的预加载
        self.cache_manager.stop_preload()
        try:
            self.big_image_cache.clear()
        except Exception:
            pass
        self.image_files = []
        try:
            w = getattr(self, "_folder_load_worker", None)
            if w is not None and w.isRunning():
                w.is_cancelled = True
        except Exception:
            pass
        
        if not os.path.exists(folder_path):
            return
        self.raw_image_files = []
        self.update_thumbnails()
        try:
            self._thumbnail_request_id = int(getattr(self, "_thumbnail_request_id", 0)) + 1
        except Exception:
            self._thumbnail_request_id = 1
        try:
            self.thumbnail_loader.set_active_request_id(self._thumbnail_request_id)
        except Exception:
            pass
        self.thumbnail_loader.cancel_all()
        try:
            self._pending_updates.clear()
        except Exception:
            pass
        try:
            if self._update_timer.isActive():
                self._update_timer.stop()
        except Exception:
            pass
        try:
            self._requested_paths.clear()
        except Exception:
            pass
        try:
            self._current_visible_path_keys = set()
            self._pending_visible_path_keys = set()
        except Exception:
            pass

        self._folder_load_worker = FolderLoadWorker(folder_path)
        self._folder_load_worker.finished.connect(self._on_folder_load_finished)
        self._folder_load_worker.failed.connect(self._on_folder_load_failed)
        self._folder_load_worker.start()
        return

        end_time1 = time.time()
        self.thumbnail_loader.cancel_all()

        # 更新缩略图显示（此时未加载的会显示占位符）
        # self.sort_images() # apply_quick_filters 已经调用了 sort_images
        
        # 切换文件夹后，检查是否有选中的收藏文件（通常没有），如果没有则取消收藏按钮选中
        # 修正：现在收藏按钮是过滤开关，不需要根据选中文件自动取消
        # 但是如果切换了文件夹，应该重置过滤状态吗？通常文件管理器会重置过滤
        # 用户可能希望保持过滤状态？
        # 如果重置：
        # self.favorite_filter = False
        # self.rating_filter = 0
        # self.fav_btn.setChecked(False)
        # self.star_rating.set_rating(0)
        
        # 这里为了避免混淆，切换文件夹时重置过滤状态
        # 实际上上面的代码已经执行了 apply_quick_filters，使用的是当前的 filter 状态
        # 如果要重置，应该在 load_images_from_folder 开头重置
        # 但是用户可能希望保留 "只看收藏" 的状态去浏览不同文件夹
        # 所以暂时保留状态
        
        # 更新按钮 UI 以匹配当前状态 (防止状态不一致)
        self.fav_btn.blockSignals(True)
        self.fav_btn.setChecked(self.favorite_filter)
        if self.favorite_filter:
            self.fav_btn.setIcon(qta.icon('mdi6.heart', color='#e74c3c', options=[{'scale_factor': 1.1}]))
        else:
            self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
        self.fav_btn.blockSignals(False)
            
        self.star_rating.set_rating(self.rating_filter, emit_signal=False)

    def _on_folder_load_failed(self, folder_path, message):
        if self._normalize_path_str(folder_path) != self._normalize_path_str(getattr(self, "current_folder_path", "")):
            return
        try:
            if message:
                NotificationManager.instance().show_warning("错误", str(message))
        except Exception:
            pass

    def _on_folder_load_finished(self, folder_path, loaded_files):
        if self._normalize_path_str(folder_path) != self._normalize_path_str(getattr(self, "current_folder_path", "")):
            return
        try:
            self.raw_image_files = loaded_files or []
        except Exception:
            self.raw_image_files = []
        self.apply_quick_filters()

    def on_thumbnail_loaded(self, path, image):
        """缩略图加载完成回调"""
        # 直接使用 _pending_updates 队列
        self._pending_updates.append((path, image))
        if not self._update_timer.isActive():
            self._update_timer.start(0)

    def _on_thumbnail_ui_applied(self, path):
        # 控制器每完成一次 UI 回填后触发的补充动作：
        # - 主要用于维护启动遮罩的 pending 集合，决定何时隐藏遮罩
        key = self._normalize_path_key(path)
        if self._startup_mask_enabled and self._startup_mask_visible:
            if key in self._startup_pending_paths:
                self._startup_pending_paths.discard(key)
            self._maybe_hide_startup_mask()

    def _process_pending_updates(self):
        if not self._pending_updates:
            self._update_timer.stop()
            return
        if getattr(self, "_thumbnail_ui_suspended", False):
            self._update_timer.stop()
            return
        path, image = self._pending_updates.popleft()
        key = self._normalize_path_key(path)
        if not self._apply_loaded_thumbnail(path, image):
            self._retry_apply_loaded_thumbnail(path, image, 0)
        if self._startup_mask_enabled and self._startup_mask_visible:
            if key in self._startup_pending_paths:
                self._startup_pending_paths.discard(key)
        if self._startup_mask_enabled and self._startup_mask_visible:
            self._maybe_hide_startup_mask()
        if self._pending_updates:
            self._update_timer.start(0)

    def _on_idle_visible_load_tick(self):
        try:
            if getattr(self, "_thumbnail_ui_suspended", False):
                return
            if getattr(self, "_fast_scroll_active", False):
                return
            if not getattr(self, "grid_view", None) or not getattr(self.grid_view, "thumbnails", None):
                return
            if self._visible_load_timer.isActive():
                return
            start, end, _ = self.grid_view.get_visible_index_range(extra_rows=2)
            if end < start:
                return
            missing = False
            for i in range(int(start), int(end) + 1):
                try:
                    t = self.grid_view.thumbnails[i]
                except Exception:
                    continue
                try:
                    is_stale = bool(getattr(t, "_stale_thumbnail", False))
                except Exception:
                    is_stale = False
                try:
                    pix = getattr(t, "thumbnail_pixmap", None)
                    img = getattr(t, "_thumbnail_image", None)
                    has_pix = pix is not None and not (hasattr(pix, "isNull") and pix.isNull())
                    has_img = img is not None and not (hasattr(img, "isNull") and img.isNull())
                except Exception:
                    has_pix = False
                    has_img = False
                if (not (has_pix or has_img)) or is_stale:
                    missing = True
                    break
            if not missing:
                return
            self._schedule_visible_load(immediate=False)
        except Exception:
            return

    def _apply_loaded_thumbnail(self, path, image=None):
        key = self._normalize_path_key(path)
        thumb = self._thumb_by_path.get(key)
        if not thumb or not getattr(thumb, "image_info", None):
            return False
        try:
            info_path = thumb.image_info.get("path")
        except Exception:
            info_path = None
        if self._normalize_path_key(info_path) != key:
            return False
        if image is None:
            return True
        if image is not None and hasattr(thumb, "set_thumbnail_image"):
            thumb.set_thumbnail_image(image)
            try:
                thumb._stale_thumbnail = False
            except Exception:
                pass
        return True

    def _retry_apply_loaded_thumbnail(self, path, image, attempt):
        if attempt >= getattr(self, "_thumbnail_loaded_retry_max", 20):
            return
        key = self._normalize_path_key(path)
        if self._pending_visible_path_keys and key not in self._pending_visible_path_keys:
            return
        delay = getattr(self, "_thumbnail_loaded_retry_delay_ms", 60)
        QTimer.singleShot(delay, lambda p=path, img=image, a=attempt + 1: self._retry_apply_loaded_thumbnail(p, img, a) if not self._apply_loaded_thumbnail(p, img) else None)

    def _reconcile_missing_thumbnails(self, rounds_left=6):
        if rounds_left <= 0:
            return
        if not hasattr(self, "grid_view") or not getattr(self.grid_view, "thumbnails", None):
            return
        cache_type = getattr(self, "current_cache_type", "general")
        paths_to_load = []
        for thumb in self.grid_view.thumbnails:
            info = getattr(thumb, "image_info", None)
            if not info:
                continue
            path = info.get("path")
            if not path:
                continue
            try:
                pix = getattr(thumb, "thumbnail_pixmap", None)
                img = getattr(thumb, "_thumbnail_image", None)
                has_pix = pix is not None and not (hasattr(pix, "isNull") and pix.isNull())
                has_img = img is not None and not (hasattr(img, "isNull") and img.isNull())
                is_missing = not (has_pix or has_img)
            except Exception:
                is_missing = True
            if not is_missing:
                continue
            paths_to_load.append(path)
        if paths_to_load:
            self.thumbnail_loader.load_thumbnails(paths_to_load, self.current_thumb_size, cache_type, request_id=getattr(self, "_thumbnail_request_id", None))
        QTimer.singleShot(300, lambda r=rounds_left - 1: self._reconcile_missing_thumbnails(r))

    def on_sort_changed(self, index):
        # 获取当前点击的项的文本
        text = self.sort_combo.itemText(index)
        
        # 清理可能残留的箭头（为了兼容旧状态）
        clean_text = text.replace(" ↑", "").replace(" ↓", "")
        
        # 标记是否只是改变了排序方向
        order_changed_only = False
        
        if clean_text == "递增":
            self.sort_order = 'asc'
        elif clean_text == "递减":
            self.sort_order = 'desc'
            order_changed_only = True
        else:
            # 字段切换
            self.sort_field_mode = clean_text
            
        self.settings_manager.set("library/sort_field", self.sort_field_mode)
        self.settings_manager.set("library/sort_order", self.sort_order or "")
        
        # 不再强制跳转回字段，直接显示用户选中的项
        self._update_sort_display()
        self.sort_images()

    def _parse_datetime_to_ts(self, value):
        if value is None:
            return 0.0
        s = str(value).strip()
        if not s:
            return 0.0
        s = s.replace("T", " ").strip()
        if s.endswith("Z"):
            s = s[:-1].strip()
        fmts = [
            "%Y:%m:%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y:%m:%d %H:%M",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y:%m:%d",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ]
        for fmt in fmts:
            try:
                return float(datetime.strptime(s, fmt).timestamp())
            except Exception:
                continue
        try:
            if len(s) >= 19 and s[4] == ":" and s[7] == ":":
                s2 = f"{s[0:4]}-{s[5:7]}-{s[8:10]}{s[10:]}"
                return float(datetime.strptime(s2, "%Y-%m-%d %H:%M:%S").timestamp())
        except Exception:
            pass
        return 0.0

    def _ensure_create_ts_for_items(self, items):
        if not items:
            return
        for it in items:
            if it is None:
                continue
            try:
                existing = it.get('create_ts', None)
            except Exception:
                existing = None
            if existing is not None:
                continue
            p = None
            try:
                p = it.get('path')
            except Exception:
                p = None
            ts = 0.0
            if p:
                try:
                    ts = float(os.stat(p).st_ctime)
                except Exception:
                    ts = 0.0
            try:
                it['create_ts'] = ts
            except Exception:
                pass

    def _ensure_shot_ts_for_items(self, items):
        if not items:
            return
        for it in items:
            if it is None:
                continue
            shot_ts = 0.0
            shot_time = None
            try:
                shot_time = it.get('shot_time')
            except Exception:
                shot_time = None
            if shot_time:
                shot_ts = self._parse_datetime_to_ts(shot_time)
            try:
                it['shot_ts'] = shot_ts
            except Exception:
                pass

    def sort_images(self):
        """对图片列表进行排序"""
        if self.image_files:
            sort_mode = self.sort_field_mode
            reverse_override = None
            if self.sort_order == 'asc':
                reverse_override = False
            elif self.sort_order == 'desc':
                reverse_override = True
            
            if sort_mode == "文件名":
                reverse = reverse_override if reverse_override is not None else False
                self.image_files.sort(key=lambda x: x['name'], reverse=reverse)
            elif sort_mode in ("拍摄时间", "日期"):
                self._ensure_shot_ts_for_items(self.image_files)
                effective_desc = reverse_override if reverse_override is not None else True
                if effective_desc:
                    self.image_files.sort(key=lambda x: (0 if (x.get('shot_ts', 0.0) or 0.0) else 1, -(x.get('shot_ts', 0.0) or 0.0)))
                else:
                    self.image_files.sort(key=lambda x: (0 if (x.get('shot_ts', 0.0) or 0.0) else 1, (x.get('shot_ts', 0.0) or 0.0)))
            elif sort_mode == "评分":
                reverse = reverse_override if reverse_override is not None else True
                self.image_files.sort(
                    key=lambda x: (x.get('rating', 0) or 0, x.get('score', 0) or 0),
                    reverse=reverse
                )
            elif sort_mode == "ISO":
                reverse = reverse_override if reverse_override is not None else False
                self.image_files.sort(
                    key=lambda x: x.get('iso', 0) or 0,
                    reverse=reverse
                )
            elif sort_mode == "文件大小":
                def get_size(item):
                     path = item.get('path')
                     if path and os.path.exists(path):
                         try:
                             return os.stat(path).st_size
                         except:
                             return 0
                     return 0
                reverse = reverse_override if reverse_override is not None else False
                self.image_files.sort(key=get_size, reverse=reverse)
            elif sort_mode == "物种":
                def get_species_key(item):
                    s = item.get('species')
                    s_str = str(s).strip() if s else ""
                    
                    # 如果没有物种信息，将其排在最后，而不是混排
                    # 混排会导致 groupby 产生大量碎片化的分组
                    if not s_str:
                        # 使用一个较大的前缀确保排在最后，并在同类中按文件名排序
                        return ("~~~~~~", item.get('name', ''))
                    
                    pinyin_str = ""
                    if lazy_pinyin:
                        pinyin_str = ''.join(lazy_pinyin(s_str)).lower()
                    else:
                        pinyin_str = s_str.lower()
                    
                    return (pinyin_str, s_str)
                reverse = reverse_override if reverse_override is not None else False
                self.image_files.sort(key=get_species_key, reverse=reverse)
            
        self.update_thumbnails()

    def update_thumbnails(self):
        """更新缩略图列表"""
        # 确保使用正确的尺寸
        thumb_w, thumb_h = self._get_current_thumb_wh()
        if thumb_w <= 0 or thumb_h <= 0:
             self.current_thumb_size = self.calculate_thumb_size(self.preview_slider.value())

        # 使用通用方法更新，确保分组逻辑生效
        self._update_thumbnails_with_list(self.image_files)

        # 停止旧的刷新定时器（如果存在）
        if hasattr(self, '_refresh_timer'):
            self._refresh_timer.stop()
