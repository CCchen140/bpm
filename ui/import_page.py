from PyQt6.QtWidgets import QWidget, QSplitter, QVBoxLayout, QFileDialog, QHBoxLayout, QLabel, QFrame, QMenu, QPushButton, QApplication
from PyQt6.QtCore import Qt, QTimer, QByteArray, pyqtSignal, QEvent, QSize, QObject, QPoint, QRect
from PyQt6.QtGui import QShortcut, QKeySequence
import os
import json
import re
import fnmatch
from collections import deque, OrderedDict
import time
from threading import Thread, Event
from datetime import datetime
import qtawesome as qta

from ui.common.base_page import BaseImageBrowserPage
from ui.common.styles import TOOLBAR_BTN_STYLE
from ui.panels.folder_panel import FolderPanel
from ui.library.views.thumbnail_grid_view import ThumbnailGridView
from ui.library.views.virtual_thumbnail_grid_view import VirtualThumbnailGridView
from ui.library.views.toolbar_view import ToolbarView
from ui.panels.preview_panel import PreviewPanel
from ui.panels.info_panel import InfoPanel
from ui.panels.image_detail_panel import ImageDetailPanel
from utils.sql.data_base import BirdLibraryDB
from utils.setting.settings_manager import SettingsManager
from cache.cache_manager import ImageCacheManager
from cache.big_image_cache_manager import BigImageCacheManager
from ui.utils.thumbnail_loader import ThumbnailLoader
from ui.utils.status_manager import StatusManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.shortcut_manager import ShortcutManager
from ui.widgets.toggle_switch import ToggleSwitch
from ui.widgets.image_thumbnail import ImageThumbnail
from ui.widgets.loading_overlay import LoadingOverlay
from ui.widgets.task_progress_overlay import TaskProgressOverlay
from utils.file.file import raw_exts, img_exts
from utils.system.task_scheduler import TaskType
from ui.utils.color_manager import ColorManager
from ui.dialogs.focus_detect_dialog import FocusDetectDialog

class ImportPage(BaseImageBrowserPage):
    scanResultsReady = pyqtSignal(int, object)
    exifDetailsReady = pyqtSignal(int, object)
    stats_changed = pyqtSignal(int, int, int)
    import_to_library_succeeded = pyqtSignal(str)
    """
    图片导入页面
    采用与图库界面相似的布局：
    - 左侧：文件树
    - 中间：图库展示 (Grid)
    - 右侧：预览面板
    - 顶部：工具栏
    - 底部：信息面板 (InfoPanel)
    """
    def __init__(self):
        # 初始化依赖
        self.db = BirdLibraryDB()
        self.settings_manager = SettingsManager()
        
        # 读取配置
        cache_size = int(self.settings_manager.get("import/cache_size", 500))
        self._event_filter_installed = False
        self._suspend_filter_panel_auto_hide = False
        cpu_count = os.cpu_count() or 4
        default_threads = max(1, cpu_count - 2)
        loader_threads = int(self.settings_manager.get("import/loader_threads", default_threads))
        # Ensure within bounds
        loader_threads = max(1, min(loader_threads, default_threads))
        self._default_loader_threads = loader_threads

        # 禁用预加载线程，减少启动开销
        self.cache_manager = ImageCacheManager(context="import", enable_preload=False)
        self.big_image_cache = BigImageCacheManager.instance("import")
        # 设置最大缓存数量
        self.cache_manager.max_cache_size = cache_size
        
        self.thumbnail_loader = ThumbnailLoader(self.cache_manager, TaskType.IMPORT_LOADER)
        self.thumbnail_loader.set_max_thread_count(loader_threads)
        
        self.image_files = [] # 当前显示的图片文件列表
        self._all_image_files = []
        self._stash_by_folder = {}
        self._stash_filter_mode = 0
        self._virtual_fav_filter = False
        self._virtual_rating_filter = 0
        self._advanced_search_conditions = []
        self._current_folder_path = ""
        self._thumb_by_path = {} # 路径到缩略图控件的映射
        self._last_left_width = 240 # 记录左侧面板折叠前的宽度
        self.is_virtual_mode = False # 默认为真实文件模式
        self._open_detail_shortcut = None
        try:
            self.display_mode = int(self.settings_manager.get("import/view_mode", 1))
        except Exception:
            self.display_mode = 1
        try:
            self.sort_field_mode = str(self.settings_manager.get("import/sort_field_real", self.settings_manager.get("import/sort_field", "文件名")) or "文件名")
        except Exception:
            self.sort_field_mode = "文件名"
        try:
            self.sort_order = str(self.settings_manager.get("import/sort_order_real", self.settings_manager.get("import/sort_order", "asc")) or "asc")
        except Exception:
            self.sort_order = "asc"
        if self.sort_order not in ("asc", "desc"):
            self.sort_order = "asc"
        self._sort_options_real = ["文件名", "拍摄时间", "大小"]
        self._sort_options_virtual = ["文件名", "拍摄时间", "评分", "得分", "标准分", "鸟占比", "物种", "文件大小", "ISO"]
        self._focus_detect_running = False
        
        # 统计计数
        self.loaded_count = 0
        self.selected_count = 0
        self._load_request_id = 0
        self._requested_paths = set()
        self._requested_retry_ts = {}
        self._inmem_thumb_lru = OrderedDict()
        self._inmem_retain_keys = set()
        self._requested_exif_paths = set()
        self._active_render_indices = set()
        self._pending_visible_paths = set()
        self._error_notified = False
        self._metrics_total = 0
        self._metrics_fail = 0
        self._metrics_times = []
        self._metrics_last_log = 0.0
        self._metrics_cache_hits = 0
        self._folder_load_request_id = 0
        self._thumb_status_task_id = None
        self.has_valid_folder = False
        self._loaded_paths = set()
        self._last_scroll_value = None
        self._scroll_direction = 0
        self._last_visible_start = None
        self._last_visible_end = None
        self._thumb_build_request_id = 0
        self._thumb_build_pending_files = []
        self._thumb_build_index = 0
        self._thumb_build_batch_size = 30  # 减小批次大小以避免阻塞主线程
        self._thumb_build_target_count = 0
        self._full_build_deferred = False
        self._full_build_total_count = 0
        self._cache_warmup_deferred = False

        super().__init__()
        self._thumb_build_timer = QTimer(self)
        self._thumb_build_timer.setSingleShot(True)
        self._thumb_build_timer.timeout.connect(self._build_thumbnail_batch)

        self._focus_progress_timer = QTimer(self)
        self._focus_progress_timer.setInterval(300)
        self._focus_progress_timer.timeout.connect(self._refresh_focus_progress_ui)
        self._focus_progress_operation = ""
        self._focus_progress_done = 0
        self._focus_progress_total = 0
        self._focus_progress_start_ts = 0.0
        self._focus_eta_last_op = ""
        self._focus_eta_last_total = 0
        self._focus_eta_last_done = 0
        self._focus_eta_seconds = None
        self._focus_eta_last_update_ts = 0.0

        self._focus_db_poll_timer = QTimer(self)
        self._focus_db_poll_timer.setInterval(3000)
        self._focus_db_poll_timer.timeout.connect(self._poll_focus_db_results)
        self._focus_db_last_poll_ts = 0.0
        self._focus_threshold_debounce_timer = QTimer(self)
        self._focus_threshold_debounce_timer.setSingleShot(True)
        self._focus_threshold_debounce_timer.setInterval(180)
        self._focus_threshold_debounce_timer.timeout.connect(self._apply_focus_thresholds_change)
        
        self._startup_mask_enabled = True
        self._startup_mask_visible = False
        self._startup_pending_paths = set()
        self._startup_first_page_ready = False
        self._startup_initial_load_processed = False  # 标记是否已完成初始可视区域计算
        self._startup_mask_timeout_timer = QTimer(self)
        self._startup_mask_timeout_timer.setSingleShot(True)
        self._startup_mask_timeout_timer.timeout.connect(self._force_hide_startup_mask)
        
        # 批量更新加载完成的图片，避免主线程阻塞
        self._pending_updates = deque()
        # 允许每帧处理更多图片，但受时间限制控制
        # 之前为 1，会导致每张图片都需要一次事件循环，效率极低
        self._update_batch_size = 10
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(5) 
        self._update_timer.timeout.connect(self._process_pending_updates)
        self._visible_load_force_cancel = False
        self._mouse_busy = False
        try:
            self._mouse_busy_loader_threads = max(2, min(int(getattr(self, "_default_loader_threads", 2) or 2), 6))
        except Exception:
            self._mouse_busy_loader_threads = 2
        self._mouse_busy_timer = QTimer(self)
        self._mouse_busy_timer.setSingleShot(True)
        self._mouse_busy_timer.timeout.connect(lambda: (setattr(self, "_mouse_busy", False), self.thumbnail_loader.set_max_thread_count(self._default_loader_threads), self.thumbnail_loader.cancel_pending(), setattr(self, "_requested_paths", set()), self._schedule_visible_load(immediate=True)))
        self._cache_warmup_paths = []
        self._cache_warmup_index = 0
        self._cache_warmup_request_id = 0
        self._cache_warmup_timer = QTimer(self)
        self._cache_warmup_timer.setInterval(10)
        self._cache_warmup_timer.timeout.connect(self._process_cache_warmup)
        self._fast_scroll_active = False
        self._fast_scroll_timer = QTimer(self)
        self._fast_scroll_timer.setSingleShot(True)
        self._fast_scroll_timer.timeout.connect(self._end_fast_scroll)
        self._thumb_resize_timer = QTimer(self)
        self._thumb_resize_timer.setSingleShot(True)
        self._thumb_resize_timer.setInterval(30)
        self._thumb_resize_timer.timeout.connect(self._apply_thumbnail_resize)
        self._is_slider_dragging = False
        self._pending_thumb_size = None
        self._pending_preview_path = None
        self._preview_debounce_timer = QTimer(self)
        self._preview_debounce_timer.setSingleShot(True)
        self._preview_debounce_timer.setInterval(60)
        self._preview_debounce_timer.timeout.connect(self._apply_pending_preview)
        self._pending_detail_nav = None
        self._detail_debounce_timer = QTimer(self)
        self._detail_debounce_timer.setSingleShot(True)
        self._detail_debounce_timer.setInterval(80)
        self._detail_debounce_timer.timeout.connect(self._apply_pending_detail_nav)
        self._pending_big_preload_range = None
        self._big_preload_timer = QTimer(self)
        self._big_preload_timer.setSingleShot(True)
        self._big_preload_timer.setInterval(120)
        self._big_preload_timer.timeout.connect(self._apply_pending_big_preload)
        try:
            self._debug_import_virtual_exif = bool(self.settings_manager.get("debug/import_virtual_exif", True))
        except Exception:
            self._debug_import_virtual_exif = True

        # 初始化UI
        self.init_ui()

        self._stash_save_timer = QTimer(self)
        self._stash_save_timer.setSingleShot(True)
        self._stash_save_timer.setInterval(800)
        self._stash_save_timer.timeout.connect(self._save_stash_state_now)
        self._load_stash_state()
        
        # 连接加载器信号
        self.thumbnail_loader.signals.loaded.connect(self.on_thumbnail_loaded)
        if hasattr(self.thumbnail_loader.signals, "loaded_metrics"):
            self.thumbnail_loader.signals.loaded_metrics.connect(self.on_thumbnail_metrics)
        self.scanResultsReady.connect(self._apply_scan_results)
        self.exifDetailsReady.connect(self._apply_exif_details_updates)
        
        # 注册主题监听器
        ColorManager.instance().register_listener(self._update_mode_switch_theme)
        
        # 初始化主题颜色
        self._update_mode_switch_theme()
        try:
            QTimer.singleShot(300, self.load_settings)
        except Exception:
            pass
        try:
            QTimer.singleShot(0, lambda: self._apply_thumb_size_from_slider(apply_reload=False))
            QTimer.singleShot(220, lambda: self._apply_thumb_size_from_slider(apply_reload=False))
        except Exception:
            pass

    def _get_stash_store_path(self) -> str:
        try:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        except Exception:
            root = os.getcwd()
        return os.path.join(root, "data", "cache", "import_stash.json")

    def _load_stash_state(self):
        path = self._get_stash_store_path()
        data = None
        try:
            if not os.path.isfile(path):
                return
        except Exception:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return
        try:
            raw = data.get("stash_by_folder") or {}
            out = {}
            if isinstance(raw, dict):
                for fk, items in raw.items():
                    if not fk:
                        continue
                    if not isinstance(items, (list, tuple, set)):
                        continue
                    s = set()
                    for x in items:
                        if not x:
                            continue
                        try:
                            s.add(str(x))
                        except Exception:
                            pass
                    if s:
                        out[str(fk)] = s
            self._stash_by_folder = out
        except Exception:
            pass
        try:
            if "stash_filter_mode" in data:
                self._stash_filter_mode = int(data.get("stash_filter_mode", 0) or 0)
            else:
                self._stash_filter_mode = 1 if bool(data.get("stash_filter_enabled", False)) else 0
        except Exception:
            self._stash_filter_mode = 0
        try:
            if hasattr(self, "stash_filter_btn") and self.stash_filter_btn:
                try:
                    self._apply_stash_filter_btn_ui()
                except Exception:
                    pass
        except Exception:
            try:
                if hasattr(self, "stash_filter_btn") and self.stash_filter_btn:
                    self.stash_filter_btn.blockSignals(False)
            except Exception:
                pass

    def _schedule_save_stash_state(self):
        try:
            if hasattr(self, "_stash_save_timer") and self._stash_save_timer is not None:
                self._stash_save_timer.start()
        except Exception:
            pass

    def _save_stash_state_now(self):
        path = self._get_stash_store_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            return
        payload = {
            "version": 1,
            "stash_filter_mode": int(getattr(self, "_stash_filter_mode", 0) or 0),
            "stash_filter_enabled": bool(int(getattr(self, "_stash_filter_mode", 0) or 0) == 1),
            "stash_by_folder": {},
            "updated_at": float(time.time()),
        }
        try:
            out = {}
            for fk, s in (getattr(self, "_stash_by_folder", {}) or {}).items():
                if not fk or not s:
                    continue
                try:
                    out[str(fk)] = list({str(x) for x in s if x})
                except Exception:
                    continue
            payload["stash_by_folder"] = out
        except Exception:
            pass
        tmp = f"{path}.tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _start_cache_loading(self):
        """启动后台线程加载缓存"""
        if not getattr(self.cache_manager, "persistent_cache_enabled", False):
            return
        if hasattr(self, "load_cache_thread") and self.load_cache_thread and self.load_cache_thread.is_alive():
            return
        self.load_cache_thread = Thread(target=self.cache_manager.load_persistent_cache, daemon=True, name="ImportCacheLoader")
        self.load_cache_thread.start()

    def shutdown(self):
        """页面关闭时的清理工作"""
        if hasattr(self, "thumbnail_loader"):
            self.thumbnail_loader.shutdown()

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
            if hasattr(self, "_thumb_by_path") and isinstance(self._thumb_by_path, dict):
                for thumb in list(self._thumb_by_path.values()):
                    try:
                        thumb.clear_image_data()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self._inmem_thumb_lru = OrderedDict()
            self._inmem_retain_keys = set()
        except Exception:
            pass
        try:
            self._requested_paths = set()
            self._requested_retry_ts = {}
            self._pending_visible_paths = set()
            self._loaded_paths = set()
        except Exception:
            pass
        try:
            if hasattr(self, "_visible_load_timer") and self._visible_load_timer.isActive():
                self._visible_load_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_update_timer") and self._update_timer.isActive():
                self._update_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_thumb_build_timer") and self._thumb_build_timer.isActive():
                self._thumb_build_timer.stop()
        except Exception:
            pass

    def update_thumbnail_ui_perf_config(self):
        # 功能已移除
        pass

    def showEvent(self, event):
        """页面显示时恢复加载任务"""
        super().showEvent(event)
        try:
            self._apply_thumb_size_from_slider(apply_reload=False)
        except Exception:
            pass
        try:
            QTimer.singleShot(0, lambda: self._apply_thumb_size_from_slider(apply_reload=False))
            QTimer.singleShot(80, lambda: self._apply_thumb_size_from_slider(apply_reload=False))
        except Exception:
            pass
        try:
            QTimer.singleShot(220, self._force_refresh_first_visible_thumbnail)
        except Exception:
            pass
        try:
            if not getattr(self, "_import_cache_loading_started", False):
                self._import_cache_loading_started = True
                self._start_cache_loading()
        except Exception:
            pass
        if hasattr(self, "thumbnail_loader"):
            # 恢复线程数
            if hasattr(self, "_default_loader_threads"):
                self.thumbnail_loader.set_max_thread_count(self._default_loader_threads)
            
            # 触发可见区域加载
            self._schedule_visible_load(immediate=True)

    def _force_refresh_first_visible_thumbnail(self):
        try:
            if bool(getattr(self, "_thumb_ui_suspended", False)):
                return
        except Exception:
            return
        gv = getattr(self, "grid_view", None)
        if gv is None:
            return
        thumbs = getattr(gv, "thumbnails", []) or []
        if not thumbs:
            return
        thumb0 = thumbs[0]
        path = None
        try:
            info = getattr(thumb0, "image_info", None) or {}
            path = info.get("path")
        except Exception:
            path = None
        if not path:
            return
        try:
            if hasattr(self.cache_manager, "invalidate_memory_only"):
                self.cache_manager.invalidate_memory_only(path)
        except Exception:
            pass
        try:
            thumb0._stale_thumbnail = True
        except Exception:
            pass
        try:
            thumb0.thumbnail_pixmap = None
        except Exception:
            pass
        try:
            thumb0._thumbnail_image = None
        except Exception:
            pass
        try:
            self._requested_paths.discard(self._normalize_path_key(path))
        except Exception:
            try:
                self._requested_paths.discard(path)
            except Exception:
                pass
        try:
            self._schedule_visible_load(immediate=True)
        except Exception:
            pass

    def hideEvent(self, event):
        """页面隐藏时暂停/降级加载任务"""
        super().hideEvent(event)
        if hasattr(self, "thumbnail_loader"):
            # 取消待处理任务
            self.thumbnail_loader.cancel_pending()
            # 将线程数降为1 (静默模式)
            self.thumbnail_loader.set_max_thread_count(1)
        
        # 停止定时器
        if hasattr(self, "_visible_load_timer") and self._visible_load_timer.isActive():
            self._visible_load_timer.stop()
        if hasattr(self, "_update_timer") and self._update_timer.isActive():
            self._update_timer.stop()

    def eventFilter(self, obj, event):
        # 监听网格视图的大小变化事件
        if obj == self.grid_view and event.type() == QEvent.Type.Resize:
            if self._startup_mask_visible and hasattr(self, "_startup_mask"):
                self._startup_mask.setGeometry(self.grid_view.rect())
            try:
                if hasattr(self, "_focus_detect_mask") and self._focus_detect_mask is not None and self._focus_detect_mask.isVisible():
                    self._focus_detect_mask.setGeometry(self.grid_view.rect())
            except Exception:
                pass
            if hasattr(self, "_focus_progress_overlay") and self._focus_progress_overlay is not None:
                try:
                    self._focus_progress_overlay.reposition()
                except Exception:
                    pass
            try:
                panel = getattr(self, "_focus_threshold_panel", None)
                if panel is not None and panel.isVisible():
                    self._reposition_focus_threshold_panel()
            except Exception:
                pass
            try:
                self._apply_thumb_size_from_slider(apply_reload=False)
            except Exception:
                pass
        try:
            if hasattr(self, "grid_view") and self.grid_view is not None:
                vp = None
                try:
                    vp = getattr(getattr(self.grid_view, "scroll_area", None), "viewport", None)
                except Exception:
                    vp = None
                try:
                    if vp is not None and callable(vp) and obj == vp() and event.type() == QEvent.Type.Resize:
                        self._apply_thumb_size_from_slider(apply_reload=False)
                except Exception:
                    pass
                try:
                    lv = getattr(self.grid_view, "list_view", None)
                    if lv is not None and hasattr(lv, "viewport") and obj == lv.viewport() and event.type() == QEvent.Type.Resize:
                        self._apply_thumb_size_from_slider(apply_reload=False)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if event.type() == QEvent.Type.MouseButtonPress:
                try:
                    filter_panel = getattr(getattr(self, "toolbar", None), "filter_panel", None)
                    filter_btn = getattr(getattr(self, "toolbar", None), "filter_btn", None)
                    if filter_panel is not None and filter_panel.isVisible():
                        if getattr(self, "_suspend_filter_panel_auto_hide", False):
                            return super().eventFilter(obj, event)
                        if not self._is_click_inside(obj, [filter_panel, filter_btn], event):
                            try:
                                if filter_btn is not None:
                                    filter_btn.setChecked(False)
                                else:
                                    filter_panel.hide()
                            except Exception:
                                pass
                except Exception:
                    pass
                panel = getattr(self, "_focus_threshold_panel", None)
                if panel is not None and panel.isVisible():
                    btn = getattr(self, "focus_threshold_btn", None)
                    gp = None
                    try:
                        gp = event.globalPosition().toPoint()
                    except Exception:
                        try:
                            gp = event.globalPos()
                        except Exception:
                            gp = None
                    if gp is not None:
                        inside_panel = False
                        inside_btn = False
                        try:
                            inside_panel = bool(panel.rect().contains(panel.mapFromGlobal(gp)))
                        except Exception:
                            inside_panel = False
                        try:
                            if btn is not None and btn.isVisible():
                                inside_btn = bool(btn.rect().contains(btn.mapFromGlobal(gp)))
                        except Exception:
                            inside_btn = False
                        if not inside_panel and not inside_btn:
                            try:
                                self._focus_threshold_panel_open = False
                            except Exception:
                                pass
                            try:
                                panel.hide()
                            except Exception:
                                pass
        except Exception:
            pass
        if hasattr(self, "grid_view") and obj == self.grid_view.scroll_area.viewport():
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.Wheel):
                self._mouse_busy = True
                if hasattr(self, "thumbnail_loader"):
                    self.thumbnail_loader.set_max_thread_count(self._mouse_busy_loader_threads)
                if self._mouse_busy_timer.isActive():
                    self._mouse_busy_timer.stop()
                self._mouse_busy_timer.start(60)
        try:
            if hasattr(self, "_focus_progress_show_btn") and self._focus_progress_show_btn is not None:
                if self._focus_progress_show_btn.isVisible():
                    self._reposition_focus_progress_show_btn()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _update_event_filter_state(self, *args, **kwargs):
        needs_filter = False
        try:
            btn = getattr(getattr(self, "toolbar", None), "filter_btn", None)
            if btn is not None and btn.isVisible() and btn.isChecked():
                needs_filter = True
        except Exception:
            needs_filter = False

        app = QApplication.instance()
        if app is None:
            return
        if needs_filter and not self._event_filter_installed:
            app.installEventFilter(self)
            self._event_filter_installed = True
        elif (not needs_filter) and self._event_filter_installed:
            app.removeEventFilter(self)
            self._event_filter_installed = False

    def _is_click_inside(self, obj, widgets, event=None):
        if event and hasattr(event, "globalPosition"):
            try:
                click_pos = event.globalPosition().toPoint()
                popup = QApplication.activePopupWidget()
                if popup and popup.isVisible():
                    rect = QRect(popup.mapToGlobal(QPoint(0, 0)), popup.size())
                    if rect.contains(click_pos):
                        return True
            except Exception:
                pass

        try:
            from PyQt6.QtWidgets import QComboBox
        except Exception:
            QComboBox = None

        if obj:
            for widget in widgets:
                if self._is_ancestor_or_self(widget, obj):
                    return True

                if QComboBox is not None and isinstance(widget, QWidget):
                    combos = widget.findChildren(QComboBox)
                    for combo in combos:
                        view = combo.view()
                        if view:
                            if self._is_ancestor_or_self(view, obj):
                                return True
                            if view.viewport() == obj:
                                return True
                            if view.window() and self._is_ancestor_or_self(view.window(), obj):
                                return True
                            if view.isVisible():
                                if obj in view.findChildren(QObject):
                                    return True
                            if view and view.isVisible():
                                try:
                                    popup_window = view.window()
                                    if popup_window:
                                        if event and hasattr(event, "globalPosition"):
                                            click_pos = event.globalPosition().toPoint()
                                            try:
                                                global_pos = popup_window.mapToGlobal(QPoint(0, 0))
                                                win_rect = QRect(global_pos, popup_window.size())
                                                if win_rect.contains(click_pos):
                                                    return True
                                            except Exception:
                                                pass
                                            win_rect = QRect(popup_window.pos(), popup_window.size())
                                            if win_rect.contains(click_pos):
                                                return True
                                except Exception:
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
                                if event and hasattr(event, "globalPosition"):
                                    click_pos = event.globalPosition().toPoint()
                                    win_rect = QRect(popup_window.pos(), popup_window.size())
                                    if win_rect.contains(click_pos):
                                        return True
                            except Exception:
                                pass

        if event and hasattr(event, "globalPosition"):
            try:
                click_pos = event.globalPosition().toPoint()
                for widget in widgets:
                    if widget and widget.isVisible():
                        rect = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
                        if rect.contains(click_pos):
                            return True
            except Exception:
                pass

        return False

    def _is_ancestor_or_self(self, widget, target):
        if not widget or not target:
            return False
        tmp = target
        while tmp:
            if tmp == widget:
                return True
            if tmp.parent():
                tmp = tmp.parent()
            elif hasattr(tmp, "parentWidget") and tmp.parentWidget():
                tmp = tmp.parentWidget()
            else:
                break
        return False

    def _show_startup_mask(self, text=None):
        """显示启动遮罩
        
        用于在加载新文件夹时遮挡缩略图网格，直到初始批次的缩略图加载完成。
        这可以避免用户看到缩略图从空白到加载完成的跳变过程。
        """
        if not self._startup_mask_enabled:
            return
        if not hasattr(self, "_startup_mask"):
            return
            
        if text:
            self._startup_mask_label.setText(text)
            
        self._startup_mask.setGeometry(self.grid_view.rect())
        self._startup_mask.raise_()
        self._startup_mask.show()
        self._startup_mask_visible = True
        
        # 启动超时定时器，防止遮罩因加载异常而永久显示
        self._startup_mask_timeout_timer.stop()
        self._startup_mask_timeout_timer.start(10000) # 10秒超时强制隐藏

    def _show_focus_detect_mask(self):
        try:
            mask = getattr(self, "_focus_detect_mask", None)
        except Exception:
            mask = None
        if mask is None:
            return
        try:
            mask.setGeometry(self.grid_view.rect())
            mask.raise_()
            mask.show()
        except Exception:
            try:
                mask.show()
            except Exception:
                pass

    def _hide_focus_detect_mask(self):
        try:
            mask = getattr(self, "_focus_detect_mask", None)
        except Exception:
            mask = None
        if mask is None:
            return
        try:
            mask.hide()
        except Exception:
            pass

    def _force_hide_startup_mask(self):
        """强制隐藏启动遮罩"""
        if not self._startup_mask_visible:
            return
        if hasattr(self, "_startup_mask"):
            self._startup_mask.hide()
        self._startup_mask_visible = False
        self._startup_mask_timeout_timer.stop()
        try:
            if hasattr(self, "grid_view"):
                QTimer.singleShot(0, self._post_mask_refresh)
        except Exception:
            pass

    def _post_mask_refresh(self):
        try:
            self.grid_view.arrange_thumbnails()
            self.grid_view.update()
            self.grid_view.scroll_area.viewport().update()
            self._schedule_visible_load(immediate=True)
        except Exception:
            pass

    def _maybe_hide_startup_mask(self):
        """尝试隐藏启动遮罩
        
        检查是否还有待加载的初始缩略图，如果没有了，则隐藏遮罩。
        """
        if not self._startup_mask_visible:
            return
        
        if not self._startup_initial_load_processed:
            return
        if not self._startup_first_page_ready:
            return
        if self._startup_pending_paths:
            return
            
        # 延迟一小段时间隐藏，确保渲染完成，避免画面闪烁
        QTimer.singleShot(50, self._force_hide_startup_mask)


    def init_ui(self):
        # 1. 左侧区域：文件树导航面板 (复用 FolderPanel)
        self.folder_panel = FolderPanel(self.db, self.settings_manager, context="import")
        self.folder_panel.set_show_db_stats(False)
        try:
            self.folder_panel.folderRemovedFromTree.connect(self._on_import_roots_changed)
            self.folder_panel.folderDeletedOnDisk.connect(self._on_import_roots_changed)
            self.folder_panel.rootFoldersChanged.connect(self._on_import_roots_changed)
            self.folder_panel.focusDetectFoldersDropped.connect(self._on_focus_detect_folders_dropped)
        except Exception:
            pass
        
        # Add custom buttons for Import Page
        # 为导入页面添加自定义按钮
        self.import_btn = self.folder_panel.add_tool_button(
            'fa5s.file-import', "导入", self.on_import_clicked
        )
        self.recognition_btn = self.folder_panel.add_tool_button(
            'ri.voice-recognition-fill', "对焦检测", self.on_recognition_clicked
        )
        
        # Toggle Switch for Mode (Real/Virtual)
        # 模式切换开关（真实文件/虚拟扫描）
        self.mode_container = QWidget()
        self.mode_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # Ensure transparent background
        # Override FolderPanel's global QWidget style (which adds border-top)
        # 覆盖 FolderPanel 的全局 QWidget 样式（该样式添加了顶部边框）
        self.mode_container.setStyleSheet("QWidget { border: none; background: transparent; }")
        mode_layout = QHBoxLayout(self.mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(4)
        icon_color = ColorManager.instance().get("theme.text.dark")
        # Left Icon (Real File)
        # 左侧图标（真实文件）
        self.label_real = QLabel()
        self.label_real.setPixmap(qta.icon('mdi6.file', color=icon_color).pixmap(16, 16))
        self.label_real.setToolTip("真实文件模式")
        mode_layout.addWidget(self.label_real)
        
        # Switch
        # 切换开关
        self.mode_switch = ToggleSwitch(width=30, height=16, track_color_on=ColorManager.instance().get("theme.primary"), track_color_off="#90A4AE")
        self.mode_switch.setToolTip("切换真实/扫描文件树")
        self.mode_switch.stateChanged.connect(self.on_mode_switch_toggled)
        mode_layout.addWidget(self.mode_switch)
        
        # Right Icon (Virtual File)
        # 右侧图标（虚拟文件）
        self.label_virtual = QLabel()
        self.label_virtual.setPixmap(qta.icon('fa6b.files-pinwheel', color=icon_color).pixmap(16, 16))
        self.label_virtual.setToolTip("扫描文件模式")
        mode_layout.addWidget(self.label_virtual)
        
        self.folder_panel.add_widget(self.mode_container)
        
        self.set_left_panel(self.folder_panel)
        self.folder_panel.folderSelected.connect(self.on_folder_selected)
        self.folder_panel.toggleRequested.connect(self.on_folder_panel_toggled)
        
        # 2. 顶部区域：工具栏 (复用 ToolbarView)
        # 使用空配置或特定配置来初始化工具栏
        toolbar_config = {
            'show_new_folder': False,
            'show_rename': False,
            'show_delete': True,
            'show_compare': True,
            'show_fav': True,
            'show_rating': True,
            'show_filter': True,
            'show_view_mode': True,
            'show_sort': True,
            'show_slider': True,
            'show_spray': True,
            'compact_quick_filter_spacing': True,
            'view_mode_setting_key': "import/view_mode",
            'view_options': ["仅缩略图", "缩略图+文件名", "缩略图+详细信息"],
            'sort_options': ["文件名", "拍摄时间", "大小"],
        }
        self.toolbar = ToolbarView(self, self.settings_manager, config=toolbar_config)
        self._focus_threshold_panel = self._create_focus_threshold_panel()
        toolbar_host = QWidget()
        toolbar_host_layout = QVBoxLayout(toolbar_host)
        toolbar_host_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_host_layout.setSpacing(0)
        toolbar_host_layout.addWidget(self.toolbar)
        self.set_toolbar(toolbar_host)
        try:
            self._focus_threshold_panel_open = False
        except Exception:
            pass
        try:
            self.focus_threshold_btn = QPushButton()
            self.focus_threshold_btn.setIcon(qta.icon("mdi6.tune", color=ColorManager.instance().get("theme.text.dark")))
            self.focus_threshold_btn.setIconSize(QSize(22, 22))
            self.focus_threshold_btn.setFixedSize(32, 32)
            self.focus_threshold_btn.setToolTip("阈值设置")
            self.focus_threshold_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.focus_threshold_btn.clicked.connect(self._toggle_focus_threshold_panel)
            self.focus_threshold_btn.hide()
            if hasattr(self.toolbar, "layout") and self.toolbar.layout is not None:
                self.toolbar.layout.insertWidget(0, self.focus_threshold_btn)
            else:
                self.toolbar.add_widget(self.focus_threshold_btn)
        except Exception:
            self.focus_threshold_btn = None
        self.focus_stop_btn = None
        try:
            self.show_subject_rect_btn = QPushButton()
            self.show_subject_rect_btn.setIcon(qta.icon("mdi6.crop-square", color=ColorManager.instance().get("theme.text.dark")))
            self.show_subject_rect_btn.setIconSize(QSize(22, 22))
            self.show_subject_rect_btn.setFixedSize(32, 32)
            self.show_subject_rect_btn.setToolTip("显示/隐藏主体框")
            self.show_subject_rect_btn.setCheckable(True)
            self.show_subject_rect_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            try:
                init_val = bool(self.settings_manager.get("focus_detect_ui/show_subject_rect", True))
            except Exception:
                init_val = True
            self.show_subject_rect_btn.setChecked(bool(init_val))
            self.show_subject_rect_btn.toggled.connect(self._on_show_subject_rect_toggled)
            self.show_subject_rect_btn.hide()
            if hasattr(self.toolbar, "layout") and self.toolbar.layout is not None:
                self.toolbar.layout.insertWidget(3, self.show_subject_rect_btn)
            else:
                self.toolbar.add_widget(self.show_subject_rect_btn)
        except Exception:
            self.show_subject_rect_btn = None
        try:
            self.show_focus_point_btn = QPushButton()
            self.show_focus_point_btn.setIcon(qta.icon("mdi6.focus-field", color=ColorManager.instance().get("theme.text.dark")))
            self.show_focus_point_btn.setIconSize(QSize(22, 22))
            self.show_focus_point_btn.setFixedSize(32, 32)
            self.show_focus_point_btn.setToolTip("显示/隐藏对焦点")
            self.show_focus_point_btn.setCheckable(True)
            self.show_focus_point_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            try:
                init_val = bool(self.settings_manager.get("focus_detect_ui/show_focus_point", True))
            except Exception:
                init_val = True
            self.show_focus_point_btn.setChecked(bool(init_val))
            self.show_focus_point_btn.toggled.connect(self._on_show_focus_point_toggled)
            self.show_focus_point_btn.hide()
            if hasattr(self.toolbar, "layout") and self.toolbar.layout is not None:
                self.toolbar.layout.insertWidget(4, self.show_focus_point_btn)
            else:
                self.toolbar.add_widget(self.show_focus_point_btn)
        except Exception:
            self.show_focus_point_btn = None
        try:
            self.show_auto_label_btn = QPushButton()
            self.show_auto_label_btn.setIcon(qta.icon("mdi6.label-outline", color=ColorManager.instance().get("theme.text.dark")))
            self.show_auto_label_btn.setIconSize(QSize(22, 22))
            self.show_auto_label_btn.setFixedSize(32, 32)
            self.show_auto_label_btn.setToolTip("显示/隐藏自动色标")
            self.show_auto_label_btn.setCheckable(True)
            self.show_auto_label_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            try:
                init_val = bool(self.settings_manager.get("import/virtual_auto_label", True))
            except Exception:
                init_val = True
            self.show_auto_label_btn.setChecked(bool(init_val))
            self.show_auto_label_btn.toggled.connect(self._on_show_auto_label_toggled)
            self.show_auto_label_btn.hide()
            if hasattr(self.toolbar, "layout") and self.toolbar.layout is not None:
                self.toolbar.layout.insertWidget(5, self.show_auto_label_btn)
            else:
                self.toolbar.add_widget(self.show_auto_label_btn)
        except Exception:
            self.show_auto_label_btn = None
        try:
            self.toolbar.compareRequested.connect(self.on_compare_clicked)
        except Exception:
            pass
        try:
            self.toolbar.deleteRequested.connect(self.delete_selected_images)
        except Exception:
            pass
        try:
            self.toolbar.favToggled.connect(self.on_toolbar_fav_filter_toggled)
        except Exception:
            pass
        try:
            self.toolbar.ratingChanged.connect(self.on_toolbar_rating_filter_changed)
        except Exception:
            pass
        try:
            self.toolbar.ratingOperatorChanged.connect(self.on_toolbar_rating_operator_changed)
        except Exception:
            pass
        try:
            self.toolbar.advancedSearchRequested.connect(self.on_advanced_search)
        except Exception:
            pass
        try:
            self.toolbar.saveFilterRequested.connect(self.on_save_filter)
        except Exception:
            pass
        try:
            self.toolbar.loadFilterRequested.connect(self.on_load_filter)
        except Exception:
            pass
        try:
            btn = getattr(self.toolbar, "filter_btn", None)
            if btn is not None:
                btn.toggled.connect(self._update_event_filter_state)
        except Exception:
            pass
        try:
            self.toolbar.sprayModeChanged.connect(self.on_spray_mode_changed)
        except Exception:
            pass
        self.toolbar.thumbnailSizeChanged.connect(self.on_thumbnail_size_changed)
        self.toolbar.viewModeChanged.connect(self.on_view_mode_changed)
        self.toolbar.sortModeChanged.connect(self.on_sort_changed)
        try:
            self.stash_filter_btn = QPushButton()
            self.stash_filter_btn.setIcon(qta.icon('mdi6.tag-outline', color=ColorManager.instance().get("theme.text.dark"), options=[{'scale_factor': 1.1}]))
            self.stash_filter_btn.setIconSize(QSize(22, 22))
            self.stash_filter_btn.setFixedSize(32, 32)
            self.stash_filter_btn.setToolTip("暂存筛选：不筛选")
            self.stash_filter_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.stash_filter_btn.clicked.connect(self.on_stash_filter_clicked)
            try:
                if hasattr(self.toolbar, "layout") and self.toolbar.layout is not None:
                    self.toolbar.layout.insertWidget(2, self.stash_filter_btn)
                else:
                    self.toolbar.add_widget(self.stash_filter_btn)
            except Exception:
                self.toolbar.add_widget(self.stash_filter_btn)
        except Exception:
            pass
        try:
            self.batch_rename_btn = QPushButton()
            self.batch_rename_btn.setIcon(qta.icon('mdi6.rename-box', color=ColorManager.instance().get("theme.text.dark"), options=[{'scale_factor': 1.1}]))
            self.batch_rename_btn.setIconSize(QSize(22, 22))
            self.batch_rename_btn.setFixedSize(32, 32)
            self.batch_rename_btn.setToolTip("批量重命名")
            self.batch_rename_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.batch_rename_btn.clicked.connect(self.on_batch_rename_clicked)
            try:
                if hasattr(self.toolbar, "layout") and self.toolbar.layout is not None:
                    self.toolbar.layout.insertWidget(3, self.batch_rename_btn)
                else:
                    self.toolbar.add_widget(self.batch_rename_btn)
            except Exception:
                self.toolbar.add_widget(self.batch_rename_btn)
        except Exception:
            self.batch_rename_btn = None
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
        try:
            if hasattr(self.toolbar, "sort_combo") and self.toolbar.sort_combo:
                self._apply_sort_options_for_mode()
                self.toolbar.sort_combo.setProperty("sort_order", self.sort_order)
                self.toolbar.sort_combo.blockSignals(True)
                for i in range(self.toolbar.sort_combo.count()):
                    if self.toolbar.sort_combo.itemText(i) == self.sort_field_mode:
                        self.toolbar.sort_combo.setCurrentIndex(i)
                        break
                self.toolbar.sort_combo.blockSignals(False)
        except Exception:
            try:
                if hasattr(self.toolbar, "sort_combo") and self.toolbar.sort_combo:
                    self.toolbar.sort_combo.blockSignals(False)
            except Exception:
                pass
        if hasattr(self.toolbar, "preview_slider"):
            self.toolbar.preview_slider.sliderPressed.connect(self._on_thumbnail_slider_pressed)
            self.toolbar.preview_slider.sliderReleased.connect(self._on_thumbnail_slider_released)
        
        if hasattr(self.toolbar, 'filter_panel') and self.toolbar.filter_panel:
            self.toolbar.filter_panel.setParent(self)
            self.toolbar.filter_panel.hide()
        try:
            self._update_toolbar_for_mode()
        except Exception:
            pass

        # 3. 中间区域：图库展示区 (复用 ThumbnailGridView)
        self.grid_view = VirtualThumbnailGridView(self)
        self.grid_view.set_settings_manager(self.settings_manager)
        self.set_grid(self.grid_view)
        try:
            self.grid_view.zoomRequested.connect(self.on_wheel_zoom)
        except Exception:
            pass
        try:
            if getattr(self, "_focus_threshold_panel", None) is not None:
                self._focus_threshold_panel.setParent(self.grid_view)
                self._focus_threshold_panel.hide()
        except Exception:
            pass
        try:
            if not hasattr(self, "_stash_shortcut") or self._stash_shortcut is None:
                self._stash_shortcut = QShortcut(self)
                self._stash_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self._stash_shortcut.setKey(QKeySequence(Qt.Key.Key_Space))
                self._stash_shortcut.activated.connect(self.stash_selected_images)
        except Exception:
            pass
        try:
            if self._open_detail_shortcut is None:
                self._open_detail_shortcut = QShortcut(self)
                self._open_detail_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self._open_detail_shortcut.activated.connect(self._on_open_detail_shortcut)
                self._update_open_detail_shortcut()
                ShortcutManager.instance().shortcuts_changed.connect(self._update_open_detail_shortcut)
        except Exception:
            pass
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
            if hasattr(self.grid_view, "_details_compact"):
                self.grid_view._details_compact = not bool(getattr(self, "is_virtual_mode", False))
        except Exception:
            pass
        try:
            if hasattr(self.grid_view, "_item_margin"):
                self.grid_view._item_margin = 1
        except Exception:
            pass
        try:
            if hasattr(self.grid_view, "_text_gap"):
                self.grid_view._text_gap = 1
        except Exception:
            pass
        try:
            if hasattr(self.toolbar, "view_combo") and self.toolbar.view_combo:
                count = self.toolbar.view_combo.count()
                idx = self.toolbar.view_combo.currentIndex()
                if idx < 0:
                    idx = 1 if count > 1 else 0
                    self.toolbar.view_combo.setCurrentIndex(idx)
                self.on_view_mode_changed(idx)
        except Exception:
            pass
        
        # 安装事件过滤器以处理遮罩大小调整
        self.grid_view.installEventFilter(self)
        self.grid_view.scroll_area.viewport().installEventFilter(self)
        try:
            if hasattr(self, "toolbar") and self.toolbar is not None:
                self.toolbar.installEventFilter(self)
        except Exception:
            pass
        try:
            tree = getattr(getattr(self, "folder_panel", None), "folder_tree", None)
            if tree is not None:
                tree.installEventFilter(self)
                try:
                    tree.viewport().installEventFilter(self)
                except Exception:
                    pass
        except Exception:
            pass
        # 缩略图滚动性能控制器已移除
        self._thumb_ui_controller = None

        # 初始化启动遮罩
        self._startup_mask = QFrame(self.grid_view)
        cm = ColorManager.instance()
        startup_mask_bg = cm.to_qss_color("library_page.startup_mask.background", default="#f5f5f5")
        self._startup_mask.setStyleSheet(f"""
            QFrame {{
                background-color: {startup_mask_bg};
                border: none;
            }}
        """)
        self._startup_mask_label = QLabel("正在加载...", self._startup_mask)
        self._startup_mask_label.setStyleSheet("""
            QLabel {
                color: #333333;
                font-size: 14px;
                background: transparent;
                border: none;
                margin: 0px;
                padding: 0px;
            }
        """)
        mask_layout = QVBoxLayout(self._startup_mask)
        mask_layout.setContentsMargins(0, 0, 0, 0)
        mask_layout.addStretch()
        mask_layout.addWidget(self._startup_mask_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        mask_layout.addStretch()
        self._startup_mask.hide()
        self._focus_detect_mask = QFrame(self.grid_view)
        self._focus_detect_mask.setStyleSheet(f"""
            QFrame {{
                background-color: {startup_mask_bg};
                border: none;
            }}
        """)
        self._focus_detect_mask.hide()
        
        self.grid_view.itemClicked.connect(self.on_thumbnail_clicked_proxy)
        try:
            self.grid_view.itemDoubleClicked.connect(self.on_thumbnail_double_clicked)
        except Exception:
            pass
        self.grid_view.blankClicked.connect(self.clear_preview)
        self.grid_view.selectionChanged.connect(self.on_selection_changed)
        self.grid_view.scrollValueChanged.connect(self.on_grid_scroll)
        try:
            self.grid_view.sprayActionRequested.connect(self.on_spray_action_requested)
            self.grid_view.sprayCancelRequested.connect(self.on_spray_cancel_requested)
        except Exception:
            pass
        try:
            self.grid_view.contextMenuRequested.connect(self.on_thumbnail_context_menu_proxy)
        except Exception:
            pass

        self._visible_load_timer = QTimer(self)
        self._visible_load_timer.setSingleShot(True)
        self._visible_load_timer.setInterval(30) # 30ms for more responsive loading
        self._visible_load_timer.timeout.connect(self._load_visible_thumbnails)

        self.loading_overlay = LoadingOverlay(self.grid_view)
        self.loading_overlay.hide()
        self._focus_progress_overlay = TaskProgressOverlay(self.grid_view)
        self._focus_progress_overlay.hide()
        self._focus_progress_show_btn = None

        # 4. 右侧区域：文件预览面板 (复用 PreviewPanel)
        self.preview_panel = PreviewPanel(self.settings_manager, cache_context="import")
        self.preview_panel.visibility_changed.connect(self._on_preview_visibility_changed)
        # 初始状态下（默认是真实模式），隐藏预览面板的按钮
        try:
            self.preview_panel.set_actions_visible(False)
        except Exception:
            pass
        try:
            self.preview_panel.fav_toggled.connect(self.on_preview_fav_toggled)
            self.preview_panel.rating_changed.connect(self.on_preview_rating_changed)
            self.preview_panel.label_changed.connect(self.on_preview_label_changed)
        except Exception:
            pass
        self.info_panel = InfoPanel(show_extended_info=False)
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
            
        self.center_stack = QWidget()
        self.center_stack_layout = QVBoxLayout(self.center_stack)
        self.center_stack_layout.setContentsMargins(0, 0, 0, 0)
        self.center_stack_layout.setSpacing(0)
        self.center_stack_layout.addWidget(self.content_splitter)
        self.main_layout.addWidget(self.center_stack, 1)

        self.content_splitter.setSizes([240, 600, 360])
        try:
            self.content_splitter.setStretchFactor(0, 0)
            self.content_splitter.setStretchFactor(1, 10)
            self.content_splitter.setStretchFactor(2, 0)
        except Exception:
            pass

        # 连接保存设置信号
        self._splitter_layout_timer = QTimer(self)
        self._splitter_layout_timer.setSingleShot(True)
        self._splitter_layout_timer.setInterval(120)
        self._splitter_layout_timer.timeout.connect(self._on_splitter_layout_changed)

        def _on_content_splitter_moved():
            try:
                if not bool(getattr(self, "_splitter_preview_clamp", False)):
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
            try:
                self.settings_manager.set("import/splitter_state", self.content_splitter.saveState())
            except Exception:
                pass
            try:
                if self._splitter_layout_timer.isActive():
                    self._splitter_layout_timer.stop()
                self._splitter_layout_timer.start()
            except Exception:
                pass

        def _on_vertical_splitter_moved():
            try:
                self.settings_manager.set("import/preview_info_splitter_state", self.preview_info_splitter.saveState())
            except Exception:
                pass
            try:
                if self._splitter_layout_timer.isActive():
                    self._splitter_layout_timer.stop()
                self._splitter_layout_timer.start()
            except Exception:
                pass

        self.content_splitter.splitterMoved.connect(_on_content_splitter_moved)
        self.preview_info_splitter.splitterMoved.connect(_on_vertical_splitter_moved)
        if hasattr(self.toolbar, 'preview_slider'):
             self.toolbar.preview_slider.sliderReleased.connect(lambda: self.settings_manager.set("import/thumbnail_size", self.toolbar.preview_slider.value()))

        # 延迟加载设置
        QTimer.singleShot(0, self.load_settings)

    def _on_preview_visibility_changed(self, visible):
        try:
            self.settings_manager.set("import/preview_visible", bool(visible))
        except Exception:
            pass
        try:
            if hasattr(self, "info_panel") and self.info_panel is not None:
                self.info_panel.setVisible(bool(visible))
        except Exception:
            pass
        try:
            self.content_splitter.setProperty("preview_collapsed", not bool(visible))
            self._apply_theme_styles()
        except Exception:
            pass
        try:
            current_sizes = self.content_splitter.sizes()
        except Exception:
            current_sizes = []
        if not current_sizes or len(current_sizes) < 3:
            return

        if bool(visible):
            try:
                saved_width = int(self.settings_manager.get("import/preview_width", 360))
            except Exception:
                saved_width = 360
            preview_width = max(150, min(int(saved_width), 800))
            try:
                self.content_splitter.setSizes([current_sizes[0], current_sizes[1] - (preview_width - current_sizes[2]), preview_width])
            except Exception:
                pass
            try:
                handle = self.content_splitter.handle(2)
                if handle:
                    handle.setEnabled(True)
                    handle.setCursor(Qt.CursorShape.SplitHCursor)
            except Exception:
                pass
            try:
                if hasattr(self, "grid_view") and self.grid_view is not None:
                    QTimer.singleShot(100, self.grid_view.arrange_thumbnails)
            except Exception:
                pass
        else:
            try:
                if int(current_sizes[2]) > 100:
                    self.settings_manager.set("import/preview_width", int(current_sizes[2]))
            except Exception:
                pass
            try:
                self.content_splitter.setSizes([current_sizes[0], current_sizes[1] + (current_sizes[2] - 30), 30])
            except Exception:
                pass
            try:
                handle = self.content_splitter.handle(2)
                if handle:
                    handle.setEnabled(False)
                    handle.setCursor(Qt.CursorShape.ArrowCursor)
            except Exception:
                pass
            try:
                if hasattr(self, "grid_view") and self.grid_view is not None:
                    QTimer.singleShot(100, self.grid_view.arrange_thumbnails)
            except Exception:
                pass

    def _on_splitter_layout_changed(self):
        try:
            if bool(getattr(self, "_thumb_ui_suspended", False)):
                return
        except Exception:
            return
        try:
            if hasattr(self, "grid_view") and self.grid_view is not None:
                self.grid_view.arrange_thumbnails()
                self.grid_view.update()
                try:
                    self.grid_view.scroll_area.viewport().update()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._schedule_visible_load(immediate=True)
        except Exception:
            pass

    def _get_import_root_paths_from_tree(self):
        roots = []
        try:
            for i in range(self.folder_panel.folder_tree.topLevelItemCount()):
                it = self.folder_panel.folder_tree.topLevelItem(i)
                p = it.data(0, Qt.ItemDataRole.UserRole)
                if p:
                    roots.append(str(p))
        except Exception:
            return []
        return roots

    def _save_import_root_paths(self, roots):
        paths = roots or []
        if isinstance(paths, (str, bytes)):
            paths = [paths]
        out = []
        seen = set()
        for p in paths:
            if not p:
                continue
            try:
                s = str(p)
            except Exception:
                continue
            try:
                norm = os.path.normcase(os.path.normpath(s))
            except Exception:
                norm = s
            if norm in seen:
                continue
            seen.add(norm)
            out.append(s)
        try:
            self.settings_manager.set("import/root_paths", out)
            self.settings_manager.sync()
        except Exception:
            pass

    def _on_import_roots_changed(self, *_args):
        try:
            roots = self._get_import_root_paths_from_tree()
        except Exception:
            roots = []
        self._save_import_root_paths(roots)

    def load_settings(self):
        """加载页面设置"""
        # 0. 恢复模式设置 (如果有)
        # 这里假设默认从 Settings 恢复，或者如果之前没有保存模式，则默认为真实模式
        # 注意：__init__ 中默认 self.is_virtual_mode = False
        # 如果需要持久化模式，可以在 on_mode_switch_toggled 中保存，在此处读取
        # 目前根据用户需求，主要是"进入页面时检查"
        
        # 尝试恢复上次导入的路径并自动加载
        last_path = self.settings_manager.get("import/last_path")
        root_paths = self.settings_manager.get("import/root_paths", []) or []
        try:
            root_paths = [p for p in root_paths if p and os.path.exists(str(p))]
        except Exception:
            root_paths = []
        try:
            import tempfile
            temp_root = os.path.normcase(os.path.normpath(tempfile.gettempdir()))
        except Exception:
            temp_root = ""
        if temp_root:
            filtered = []
            changed = False
            for p in root_paths:
                s = str(p)
                try:
                    norm = os.path.normcase(os.path.normpath(s))
                except Exception:
                    norm = s
                if norm.startswith(temp_root + os.sep) or norm == temp_root:
                    changed = True
                    continue
                filtered.append(s)
            if changed:
                root_paths = filtered
                try:
                    self.settings_manager.set("import/root_paths", root_paths)
                    self.settings_manager.sync()
                except Exception:
                    pass
        
        # 检查当前模式 (这里简单起见，假设每次启动应用默认是真实模式，或者我们应该保存模式状态)
        # 如果要完全响应"检查是否处于真实文件模式"，我们应该确信当前的 self.is_virtual_mode 是正确的
        # 由于我们没有保存 is_virtual_mode 到设置，它总是 False (真实模式)
        if not self.is_virtual_mode:
            self.folder_panel.set_override_strict_mode(False)
            if root_paths:
                self.folder_panel.add_root_folders(root_paths)
                self._save_import_root_paths(self._get_import_root_paths_from_tree())
            elif last_path and os.path.exists(last_path):
                self.folder_panel.add_root_folders([last_path])
                self._save_import_root_paths(self._get_import_root_paths_from_tree())
            def _auto_select_and_load(p: str):
                path = str(p or "")
                if not path or not os.path.exists(path):
                    return
                state = {"tries": 0, "loaded": False}

                def _try_select():
                    state["tries"] += 1
                    ok = False
                    try:
                        if hasattr(self, "folder_panel") and hasattr(self.folder_panel, "navigate_to_folder"):
                            ok = bool(self.folder_panel.navigate_to_folder(path))
                    except Exception:
                        ok = False

                    if ok and not state["loaded"]:
                        state["loaded"] = True
                        try:
                            self.load_images(path, recursive=False)
                        except Exception:
                            pass
                        return

                    if state["tries"] >= 6 and not state["loaded"]:
                        state["loaded"] = True
                        try:
                            self.load_images(path, recursive=False)
                        except Exception:
                            pass
                        return

                    QTimer.singleShot(120, _try_select)

                _try_select()

            auto_folder = self.settings_manager.get("import/last_folder", "") or ""
            if temp_root:
                try:
                    auto_norm = os.path.normcase(os.path.normpath(str(auto_folder)))
                except Exception:
                    auto_norm = str(auto_folder)
                if auto_norm.startswith(temp_root + os.sep) or auto_norm == temp_root:
                    auto_folder = ""
                    try:
                        self.settings_manager.set("import/last_folder", "")
                        self.settings_manager.sync()
                    except Exception:
                        pass
            if auto_folder and os.path.exists(auto_folder):
                try:
                    self._show_startup_mask("正在加载...")
                except Exception:
                    pass
                QTimer.singleShot(80, lambda p=str(auto_folder): _auto_select_and_load(p))
            elif last_path and os.path.exists(last_path):
                try:
                    self._show_startup_mask("正在加载...")
                except Exception:
                    pass
                QTimer.singleShot(80, lambda p=str(last_path): _auto_select_and_load(p))

        # 1. 恢复缩略图大小
        thumb_size = self.settings_manager.get("import/thumbnail_size")
        if thumb_size is not None:
            val = int(thumb_size)
            if hasattr(self, 'toolbar') and hasattr(self.toolbar, 'preview_slider'):
                self.toolbar.preview_slider.blockSignals(True)
                self.toolbar.preview_slider.setValue(val)
                self.toolbar.preview_slider.blockSignals(False)
                self.on_thumbnail_size_changed(val)

        # 2. 恢复 Splitter 状态
        splitter_state = self.settings_manager.get("import/splitter_state")
        if splitter_state:
            self.content_splitter.restoreState(splitter_state)
            
        preview_info_state = self.settings_manager.get("import/preview_info_splitter_state")
        if preview_info_state and hasattr(self, "preview_info_splitter"):
            try:
                self.preview_info_splitter.restoreState(preview_info_state)
            except Exception:
                pass

        # 3. 恢复面板可见性
        # PreviewPanel
        preview_visible = self.settings_manager.get("import/preview_visible")
        if preview_visible is not None:
            preview_visible = str(preview_visible).lower() == 'true'
            if hasattr(self.preview_panel, 'set_expanded'):
                self.preview_panel.set_expanded(preview_visible)

        # FolderPanel
        folder_visible = self.settings_manager.get("import/folder_visible")
        if folder_visible is not None:
            folder_visible = str(folder_visible).lower() == 'true'
            # 使用 FolderPanel 自己的 set_panel_visible 方法来正确处理折叠状态
            # 而不是直接隐藏 container (这样会把 toggle 按钮也隐藏)
            if hasattr(self.folder_panel, 'set_panel_visible'):
                self.folder_panel.set_panel_visible(folder_visible)
            else:
                self.left_panel_container.setVisible(folder_visible)

        # 4. 恢复上次选中的文件夹
        # last_folder = self.settings_manager.get("import/last_folder")
        # if last_folder and os.path.exists(last_folder):
        #     # 尝试导航到该文件夹
        #     if hasattr(self.folder_panel, 'navigate_to_folder'):
        #         self.folder_panel.navigate_to_folder(last_folder)
        #     else:
        #         # 如果无法导航，至少加载图片
        #         self.load_images(last_folder)
        # else:
        #     # 如果没有记录，尝试选择第一个文件夹
        #      if hasattr(self.folder_panel, 'select_first_folder'):
        #         self.folder_panel.select_first_folder()

    def reload_thumbnails_config(self):
        try:
            if hasattr(self, "cache_manager"):
                self.cache_manager.update_settings()
                self.cache_manager.clear()
                try:
                    from cache.thumbnail_disk_cache import ThumbnailDiskCache
                    ThumbnailDiskCache(self.cache_manager, scope="import").clear_all()
                except Exception:
                    pass
                
            # 重新应用低质量模式标志
            self._update_force_low_quality_state()
                
        except Exception:
            pass

        try:
            if hasattr(self, "toolbar") and hasattr(self.toolbar, "preview_slider"):
                current_value = self.toolbar.preview_slider.value()
                self.on_thumbnail_size_changed(current_value)
        except Exception:
            pass

        try:
            self._loaded_paths = set()
            self._requested_paths = set()
            self.loaded_count = 0
            if hasattr(self, "_pending_updates"):
                self._pending_updates.clear()
        except Exception:
            pass

        try:
            if hasattr(self, "grid_view"):
                for thumb in getattr(self.grid_view, "thumbnails", []):
                    if hasattr(thumb, "clear_image_data"):
                        thumb.clear_image_data()
                    else:
                        try:
                            thumb.thumbnail_pixmap = None
                            thumb._thumbnail_image = None
                        except Exception:
                            pass
                        thumb.update()
                self.grid_view.arrange_thumbnails()
        except Exception:
            pass

        if self.has_valid_folder:
            self.stats_changed.emit(len(self.image_files), self.loaded_count, self.selected_count)
        self._schedule_visible_load(immediate=True)

    def calculate_thumb_size(self, slider_value):
        """根据滑块值计算缩略图大小"""
        min_w = 96
        min_h = 72
        ratio = min_h / min_w
        
        try:
            slider_max = 200.0
            if hasattr(self, "toolbar") and self.toolbar and hasattr(self.toolbar, "preview_slider"):
                slider_max = float(self.toolbar.preview_slider.maximum() or 200)
            if slider_max <= 0:
                slider_max = 200.0
        except Exception:
            slider_max = 200.0

        hard_cap = 900
        max_w = max(min_w + 100, int(hard_cap))
        
        # 线性插值计算当前宽度（与布局宽度解耦，避免拖动分栏导致缩略图“自适应放大”）
        try:
            progress = float(slider_value) / float(slider_max)
        except Exception:
            progress = 0.0
        progress = max(0.0, min(1.0, progress))
        current_w = int(min_w + (max_w - min_w) * progress)
        
        # 确保宽度不小于最小宽度
        current_w = max(min_w, min(int(max_w), int(current_w)))
        
        current_h = int(current_w * ratio)
        return (current_w, current_h)

    def _normalize_path_key(self, path):
        if not path:
            return ""
        try:
            p = str(path).replace("/", os.sep)
            p = os.path.normpath(p)
            if os.name == "nt":
                p = os.path.normcase(p)
            return p
        except Exception:
            try:
                return str(path)
            except Exception:
                return ""

    def _is_missing_focus_point_value(self, v) -> bool:
        if v is None:
            return True
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return True
            s2 = s.lower()
            if s2 in ("null", "none", "nan", "[]", "{}", "0,0", "0 0"):
                return True
            try:
                obj = json.loads(s)
            except Exception:
                return False
            return self._is_missing_focus_point_value(obj)
        if isinstance(v, (list, tuple)):
            return len(v) < 2
        if isinstance(v, dict):
            if "x" in v and "y" in v:
                try:
                    x = float(v.get("x"))
                    y = float(v.get("y"))
                except Exception:
                    return True
                if not (x == x and y == y):
                    return True
                return False
            return True
        return False

    def on_view_mode_changed(self, index):
        try:
            self.display_mode = int(index)
        except Exception:
            self.display_mode = 1
        try:
            if hasattr(self.grid_view, "_details_compact"):
                if bool(getattr(self, "is_virtual_mode", False)):
                    self.grid_view._details_compact = self.display_mode != ImageThumbnail.MODE_WITH_DETAILS
                else:
                    self.grid_view._details_compact = True
        except Exception:
            pass
        try:
            self.settings_manager.set("import/view_mode", int(self.display_mode))
        except Exception:
            pass
        try:
            self.grid_view.set_display_mode(self.display_mode)
        except Exception:
            pass
        try:
            self.grid_view.set_thumbnail_size(
                getattr(self.grid_view, "current_thumb_size", self.calculate_thumb_size(getattr(self.toolbar.preview_slider, "value", lambda: 0)())),
                scale_visible_only=False,
                extra_rows=2,
            )
        except Exception:
            try:
                self.grid_view.arrange_thumbnails()
            except Exception:
                pass
        try:
            self._requested_paths = set()
        except Exception:
            pass
        try:
            self._requested_exif_paths = set()
        except Exception:
            pass
        try:
            self._schedule_visible_load(immediate=True)
        except Exception:
            pass
        try:
            if int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) == ImageThumbnail.MODE_THUMBNAIL_ONLY:
                self.big_image_cache.set_max_items_override(10)
            else:
                self.big_image_cache.set_max_items_override(None)
        except Exception:
            pass

    def _get_visible_index_range_for_loading(self, extra_rows: int = 0):
        try:
            if bool(getattr(self.grid_view, "is_virtualized", False)):
                return self.grid_view.get_visible_index_range(extra_rows=max(0, int(extra_rows or 0)))
        except Exception:
            pass
        try:
            total = int(len(self.image_files))
        except Exception:
            total = 0
        if total <= 0:
            return 0, -1, 0

        try:
            thumb_size = getattr(self.grid_view, "current_thumb_size", 120)
            if isinstance(thumb_size, (tuple, list)):
                thumb_w_for_cols = int(thumb_size[0])
            else:
                thumb_w_for_cols = int(thumb_size)
            thumb_w_for_cols = max(1, int(thumb_w_for_cols))
            available_width = int(self.grid_view.get_available_width())
            cols = max(1, int(available_width) // int(thumb_w_for_cols))
        except Exception:
            cols = 1

        try:
            viewport = self.grid_view.scroll_area.viewport()
            viewport_h = max(1, int(viewport.height()))
        except Exception:
            viewport = None
            viewport_h = 1

        def _find_thumb_index_at(vx: int, vy: int):
            try:
                if viewport is None:
                    return None
                content_pos = self.grid_view.thumbnails_container.mapFrom(viewport, QPoint(int(vx), int(vy)))
                w = self.grid_view.thumbnails_container.childAt(content_pos)
            except Exception:
                w = None
            while w is not None and not isinstance(w, ImageThumbnail):
                try:
                    w = w.parent()
                except Exception:
                    w = None
            if w is None:
                return None
            try:
                return int(getattr(w, "index", None))
            except Exception:
                return None

        vx_candidates = [5]
        try:
            vx_candidates.append(max(5, int(available_width) // 2))
            vx_candidates.append(max(5, int(available_width) - 5))
        except Exception:
            pass
        top_idx = None
        bottom_idx = None
        for vx in vx_candidates:
            top_idx = _find_thumb_index_at(vx, 5)
            if top_idx is not None:
                break
        for vx in vx_candidates:
            bottom_idx = _find_thumb_index_at(vx, max(1, int(viewport_h) - 5))
            if bottom_idx is not None:
                break

        if top_idx is not None:
            top_idx = max(0, min(int(total) - 1, int(top_idx)))
        if bottom_idx is not None:
            bottom_idx = max(0, min(int(total) - 1, int(bottom_idx)))

        if top_idx is None or bottom_idx is None:
            try:
                metrics = self.grid_view.get_viewport_metrics() or {}
                thumb_h = max(1, int(metrics.get("thumb_h", 1)))
                scroll_val = int(self.grid_view.scroll_area.verticalScrollBar().value())
                first_row = max(0, int(scroll_val) // int(thumb_h))
                view_bottom = int(scroll_val) + int(viewport_h)
                last_row = max(0, (int(view_bottom) - 1) // int(thumb_h))
                last_row += max(0, int(extra_rows or 0))
                start_index = int(first_row) * int(cols)
                end_index = min(int(total) - 1, max(0, (int(last_row) + 1) * int(cols) - 1))
                visible_rows = max(1, int(last_row - first_row + 1))
                return int(start_index), int(end_index), int(visible_rows)
            except Exception:
                return 0, min(int(total) - 1, int(cols) * 3 - 1), 3

        start_row = int(top_idx) // int(cols) if int(cols) > 0 else 0
        end_row = int(bottom_idx) // int(cols) if int(cols) > 0 else start_row
        end_row += max(0, int(extra_rows or 0))
        start_index = int(start_row) * int(cols)
        end_index = min(int(total) - 1, (int(end_row) + 1) * int(cols) - 1)
        visible_rows = max(1, int(end_row - start_row + 1))
        return int(start_index), int(end_index), int(visible_rows)

    def _parse_datetime_to_ts(self, value):
        if value is None:
            return 0.0
        s = str(value).strip()
        if not s:
            return 0.0
        fmts = [
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y:%m:%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y:%m:%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y:%m:%d",
        ]
        for fmt in fmts:
            try:
                return float(datetime.strptime(s, fmt).timestamp())
            except Exception:
                continue
        return 0.0

    def on_sort_changed(self, index):
        if not hasattr(self, "toolbar") or not hasattr(self.toolbar, "sort_combo"):
            return
        try:
            text = self.toolbar.sort_combo.itemText(index)
        except Exception:
            return
        clean_text = str(text).replace(" ↑", "").replace(" ↓", "")
        if clean_text == "递增":
            self.sort_order = "asc"
        elif clean_text == "递减":
            self.sort_order = "desc"
        else:
            self.sort_field_mode = clean_text
        try:
            suffix = "virtual" if bool(getattr(self, "is_virtual_mode", False)) else "real"
        except Exception:
            suffix = "real"
        try:
            self.settings_manager.set("import/sort_field", str(self.sort_field_mode))
            self.settings_manager.set("import/sort_order", str(self.sort_order))
            self.settings_manager.set(f"import/sort_field_{suffix}", str(self.sort_field_mode))
            self.settings_manager.set(f"import/sort_order_{suffix}", str(self.sort_order))
        except Exception:
            pass
        try:
            if hasattr(self.toolbar, "sort_combo") and self.toolbar.sort_combo:
                self.toolbar.sort_combo.setProperty("sort_order", self.sort_order)
        except Exception:
            pass
        try:
            self._apply_sort_and_rebuild()
        except Exception:
            pass

    def _apply_sort_options_for_mode(self):
        combo = getattr(getattr(self, "toolbar", None), "sort_combo", None)
        if combo is None:
            return
        options = self._sort_options_virtual if bool(getattr(self, "is_virtual_mode", False)) else self._sort_options_real
        if not options:
            return
        try:
            suffix = "virtual" if bool(getattr(self, "is_virtual_mode", False)) else "real"
        except Exception:
            suffix = "real"
        try:
            stored_field = str(self.settings_manager.get(f"import/sort_field_{suffix}", self.settings_manager.get("import/sort_field", "文件名")) or "")
        except Exception:
            stored_field = ""
        try:
            stored_order = str(self.settings_manager.get(f"import/sort_order_{suffix}", self.settings_manager.get("import/sort_order", "asc")) or "asc")
        except Exception:
            stored_order = "asc"
        if stored_order not in ("asc", "desc"):
            stored_order = "asc"
        if stored_field:
            self.sort_field_mode = stored_field
        self.sort_order = stored_order
        cur_field = str(getattr(self, "sort_field_mode", "文件名") or "文件名")
        if cur_field == "日期":
            cur_field = "拍摄时间"
        if cur_field not in options:
            cur_field = str(options[0])
        try:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(list(options))
            combo.insertSeparator(combo.count())
            combo.addItems(["递增", "递减"])
            for i in range(combo.count()):
                if combo.itemText(i) == cur_field:
                    combo.setCurrentIndex(i)
                    break
        except Exception:
            pass
        finally:
            try:
                combo.blockSignals(False)
            except Exception:
                pass
        self.sort_field_mode = cur_field
        try:
            self.settings_manager.set("import/sort_field", str(self.sort_field_mode))
            self.settings_manager.set(f"import/sort_field_{suffix}", str(self.sort_field_mode))
            self.settings_manager.set(f"import/sort_order_{suffix}", str(self.sort_order))
        except Exception:
            pass
        try:
            combo.setProperty("sort_order", str(self.sort_order))
        except Exception:
            pass

    def _sort_image_files_in_place(self):
        if not getattr(self, "image_files", None):
            return
        sort_field = getattr(self, "sort_field_mode", "文件名") or "文件名"
        sort_order = getattr(self, "sort_order", "asc") or "asc"
        reverse = sort_order == "desc"

        def k_name(x):
            try:
                return str(x.get("name", "")).lower()
            except Exception:
                return ""

        def k_date(x):
            return self._parse_datetime_to_ts(x.get("create_time"))

        def k_shot_time(x):
            return self._parse_datetime_to_ts(x.get("shot_time"))

        def k_size(x):
            try:
                return int(x.get("size", 0) or 0)
            except Exception:
                return 0

        def k_file_size(x):
            try:
                return int(x.get("pixel_count") or x.get("size") or 0)
            except Exception:
                return 0

        def k_rating(x):
            try:
                return int(x.get("rating") or 0)
            except Exception:
                return 0

        def k_fav(x):
            try:
                return int(x.get("is_favorite") or x.get("favorite") or 0)
            except Exception:
                return 0

        def k_label(x):
            try:
                return str(x.get("label") or "")
            except Exception:
                return ""

        def k_score(x):
            try:
                return float(x.get("score") or 0.0)
            except Exception:
                return 0.0

        def k_norm_score(x):
            try:
                return float(x.get("norm_score") or 0.0)
            except Exception:
                return 0.0

        def k_area_ratio(x):
            try:
                return float(x.get("area_ratio") or 0.0)
            except Exception:
                return 0.0

        def k_position(x):
            try:
                return int(x.get("position") or 0)
            except Exception:
                return 0

        def k_species(x):
            try:
                return str(x.get("object") or "").lower()
            except Exception:
                return ""

        def k_iso(x):
            try:
                return int(x.get("iso") or 0)
            except Exception:
                return 0

        if sort_field in ("拍摄时间", "日期"):
            key_func = k_shot_time
        elif sort_field == "大小":
            key_func = k_size
        elif sort_field == "文件大小":
            key_func = k_file_size
        elif sort_field == "评分":
            key_func = k_rating
        elif sort_field == "收藏":
            key_func = k_fav
        elif sort_field == "色标":
            key_func = k_label
        elif sort_field == "物种":
            key_func = k_species
        elif sort_field == "ISO":
            key_func = k_iso
        elif sort_field in ("得分", "Score", "score"):
            key_func = k_score
        elif sort_field in ("标准分", "NormScore", "norm_score"):
            key_func = k_norm_score
        elif sort_field in ("鸟占比", "主体占比", "占比", "AreaRatio", "area_ratio"):
            key_func = k_area_ratio
        elif sort_field == "位置":
            key_func = k_position
        else:
            key_func = k_name

        try:
            self.image_files.sort(key=key_func, reverse=reverse)
        except Exception:
            try:
                self.image_files.sort(key=k_name, reverse=reverse)
            except Exception:
                pass

    def _apply_sort_and_rebuild(self):
        if not getattr(self, "image_files", None):
            return
        self._sort_image_files_in_place()

        self.grid_view.clear_thumbnails()
        self._thumb_by_path.clear()
        self._thumb_build_request_id = self._folder_load_request_id
        self._thumb_build_pending_files = self.image_files
        self._thumb_build_index = 0
        self._thumb_build_target_count = 0
        try:
            self._requested_paths = set()
            self._pending_visible_paths = set()
            self._loaded_paths = set()
            self.loaded_count = 0
            self.selected_count = 0
        except Exception:
            pass
        try:
            if self.has_valid_folder:
                self.stats_changed.emit(len(self.image_files), self.loaded_count, self.selected_count)
        except Exception:
            pass
        try:
            if self._thumb_build_timer.isActive():
                self._thumb_build_timer.stop()
            self._thumb_build_timer.start(0)
        except Exception:
            pass


    def on_thumbnail_size_changed(self, value):
        """处理缩略图大小变化"""
        self._pending_thumb_size = self.calculate_thumb_size(value)
        try:
            if hasattr(self, "right_content_container") and self.right_content_container is not None:
                w = int(self._pending_thumb_size[0]) if isinstance(self._pending_thumb_size, (tuple, list)) else int(self._pending_thumb_size)
                self.right_content_container.setMinimumWidth(max(0, w + 40))
        except Exception:
            pass
        try:
            if hasattr(self, "_thumb_resize_timer") and self._thumb_resize_timer.isActive():
                self._thumb_resize_timer.stop()
        except Exception:
            pass
        
        # 在拖动过程中，如果是虚拟模式，不需要频繁设置 GridView
        # 只需要更新 pending 状态即可，避免频繁重绘导致 UI 卡顿
        # 但为了让用户看到实时效果，我们还是需要更新，但要注意性能
        if getattr(self, "_is_slider_dragging", False):
            try:
                # 只有当变化足够大时才应用，减少更新频率
                last_applied = getattr(self, "_last_applied_drag_size", None)
                should_update = True
                if last_applied:
                    diff = abs(self._pending_thumb_size[0] - last_applied[0])
                    if diff < 5: # 变化小于5像素不更新
                        should_update = False
                
                if should_update:
                    self.grid_view.set_thumbnail_size(
                        self._pending_thumb_size,
                        scale_visible_only=True,
                        extra_rows=2,
                    )
                    self._last_applied_drag_size = self._pending_thumb_size
            except Exception:
                pass
            return
            
        self._apply_thumbnail_resize()

    def _apply_thumb_size_from_slider(self, apply_reload: bool = False):
        """根据工具栏滑条值应用缩略图尺寸
        
        说明：
            - 解决进入导入页时“滑条在中间但缩略图仍最小”的问题（布局未完成会导致计算宽度偏小）
            - apply_reload=True 时会触发一次重载逻辑（用于强制更新已加载缩略图）
        参数：
            apply_reload: 是否同步触发重载
        """
        if not hasattr(self, "toolbar") or self.toolbar is None:
            return
        if not hasattr(self.toolbar, "preview_slider"):
            return
        try:
            v = int(self.toolbar.preview_slider.value())
        except Exception:
            v = 0
        new_size = self.calculate_thumb_size(v)
        try:
            self._pending_thumb_size = new_size
        except Exception:
            pass
        try:
            if hasattr(self, "right_content_container") and self.right_content_container is not None:
                w = int(new_size[0]) if isinstance(new_size, (tuple, list)) else int(new_size)
                self.right_content_container.setMinimumWidth(max(0, w + 40))
        except Exception:
            pass
        try:
             pass
        except Exception:
             pass
        try:
            self.grid_view.set_thumbnail_size(new_size, scale_visible_only=True, extra_rows=1)
        except Exception:
            pass
        if apply_reload:
            try:
                self._is_slider_dragging = False
                self._last_applied_drag_size = None # Reset drag state
            except Exception:
                pass
            self._apply_thumbnail_resize()

    def _apply_thumbnail_resize(self):
        """执行缩略图尺寸调整"""
        if not self._pending_thumb_size:
            return
        try:
             pass
        except Exception:
             pass
        try:
            old_size = getattr(self, "_last_applied_thumb_size", None)
        except Exception:
            old_size = None
        self.grid_view.set_thumbnail_size(
            self._pending_thumb_size,
            scale_visible_only=self._is_slider_dragging,
            extra_rows=2
        )
        if not self._is_slider_dragging:
            try:
                self._last_applied_thumb_size = self._pending_thumb_size
            except Exception:
                pass
            old_max = 0
            new_max = 0
            try:
                if isinstance(old_size, (tuple, list)):
                    old_max = max(int(old_size[0]), int(old_size[1]))
                elif old_size:
                    old_max = int(old_size)
            except Exception:
                old_max = 0
            try:
                if isinstance(self._pending_thumb_size, (tuple, list)):
                    new_max = max(int(self._pending_thumb_size[0]), int(self._pending_thumb_size[1]))
                else:
                    new_max = int(self._pending_thumb_size)
            except Exception:
                new_max = 0
            if new_max > 0 and old_max > 0 and int(new_max) != int(old_max):
                try:
                    self._load_request_id += 1
                except Exception:
                    pass
            
            # 重置加载状态
            try:
                self._visible_load_force_cancel = True
                self.thumbnail_loader.cancel_pending()
                self._requested_paths = set()
                self._requested_retry_ts = {}
                self._pending_visible_paths = set()
                self._loaded_paths = set()
            except Exception:
                pass

            # 遍历所有缩略图进行处理
            if hasattr(self.grid_view, "thumbnails"):
                try:
                    is_scaling_up = new_max > old_max and new_max > 0
                    for thumb in self.grid_view.thumbnails:
                        try:
                            # 1. 标记为过期
                            thumb._stale_thumbnail = True
                            
                            # 2. 清除当前显示的图片对象，强制重新获取
                            if hasattr(thumb, "thumbnail_pixmap"):
                                thumb.thumbnail_pixmap = None
                            if hasattr(thumb, "_thumbnail_image"):
                                thumb._thumbnail_image = None
                            
                            # 3. 如果是放大，必须清除内存缓存，否则会获取到旧的小图
                            if is_scaling_up:
                                path = None
                                if getattr(thumb, "image_info", None):
                                    path = thumb.image_info.get("path")
                                if path and hasattr(self.cache_manager, "invalidate_memory_only"):
                                    self.cache_manager.invalidate_memory_only(path)
                        except Exception:
                            pass
                except Exception:
                    pass
            
            # 立即触发可见区域加载
            try:
                QTimer.singleShot(0, self._load_visible_thumbnails)
            except Exception:
                pass
            try:
                if old_max <= 0 or new_max <= 0:
                    if isinstance(old_size, (tuple, list)):
                        old_max = max(int(old_size[0]), int(old_size[1]))
                    elif old_size:
                        old_max = int(old_size)
                    if isinstance(self._pending_thumb_size, (tuple, list)):
                        new_max = max(int(self._pending_thumb_size[0]), int(self._pending_thumb_size[1]))
                    else:
                        new_max = int(self._pending_thumb_size)
                if new_max > 0 and abs(new_max - old_max) >= 16:
                    try:
                        self.cache_manager.clear()
                    except Exception:
                        pass
                    try:
                        self._load_request_id += 1
                        self._visible_load_force_cancel = True
                        self.thumbnail_loader.cancel_pending()
                        self._requested_paths = set()
                    except Exception:
                        pass
            except Exception:
                pass
            self._schedule_visible_load(immediate=True)

    def on_wheel_zoom(self, delta):
        """Ctrl+滚轮缩放：调整滑块值 (导入页面)"""
        if not hasattr(self, "toolbar") or not hasattr(self.toolbar, "preview_slider"):
            return
        current_value = self.toolbar.preview_slider.value()
        # 每次滚动改变5个单位
        step = 5 if delta > 0 else -5
        max_val = self.toolbar.preview_slider.maximum()
        new_value = max(0, min(max_val, current_value + step))
        self.toolbar.preview_slider.setValue(new_value)

    def _on_thumbnail_slider_pressed(self):
        """处理缩略图大小滑块按下"""
        self._is_slider_dragging = True

    def _on_thumbnail_slider_released(self):
        """处理缩略图大小滑块释放"""
        self._is_slider_dragging = False
        if hasattr(self.toolbar, "preview_slider"):
            self._pending_thumb_size = self.calculate_thumb_size(self.toolbar.preview_slider.value())
            self._apply_thumbnail_resize()

    def on_thumbnail_clicked_proxy(self, index, modifiers):
        thumbnails = self.grid_view.thumbnails
        if index < len(thumbnails):
            thumb = thumbnails[index]
            if thumb.image_info:
                self._schedule_preview(thumb.image_info.get('path'))
                try:
                    self._print_focus_detect_result(thumb.image_info.get("path"), thumb.image_info)
                except Exception:
                    pass
                try:
                    self._preload_big_neighbors_grid(index)
                except Exception:
                    pass
                try:
                    if hasattr(self, "detail_panel") and self.detail_panel:
                        self._schedule_detail_nav(int(index), modifiers)
                except Exception:
                    pass
        elif index < len(self.image_files):
            img_info = self.image_files[index]
            if isinstance(img_info, dict):
                self._schedule_preview(img_info.get('path'))
                try:
                    self._print_focus_detect_result(img_info.get("path"), img_info)
                except Exception:
                    pass
                try:
                    self._preload_big_neighbors_grid(index)
                except Exception:
                    pass
                try:
                    if hasattr(self, "detail_panel") and self.detail_panel:
                        self._schedule_detail_nav(int(index), modifiers)
                except Exception:
                    pass
        try:
            self._schedule_visible_load(immediate=True)
        except Exception:
            pass

    def on_thumbnail_double_clicked(self, index: int):
        try:
            idx = int(index)
        except Exception:
            idx = -1
        if idx < 0 or idx >= len(self.image_files):
            return
        self.show_detail_panel(idx)

    def on_compare_clicked(self):
        selected = self.get_selected_files()
        if len(selected) != 2:
            NotificationManager.instance().show_toast("请选择两张图片进行对比")
            return
        indices = []
        for it in selected:
            try:
                indices.append(int(it.get("index", -1)))
            except Exception:
                indices.append(-1)
        if any(i < 0 for i in indices):
            paths = [it.get("path") for it in selected if isinstance(it, dict) and it.get("path")]
            indices = []
            for p in paths:
                for i, row in enumerate(self.image_files or []):
                    if isinstance(row, dict) and row.get("path") == p:
                        indices.append(int(i))
                        break
        indices = [i for i in indices if isinstance(i, int) and 0 <= i < len(self.image_files)]
        if len(indices) != 2:
            NotificationManager.instance().show_warning("提示", "未能定位对比图片索引")
            return
        self.show_detail_panel(indices[0], compare_indices=indices)

    def on_batch_rename_clicked(self):
        selected_files = self.get_selected_files() or []
        if not selected_files:
            NotificationManager.instance().show_warning("提示", "请先选择图片")
            return
        try:
            from ui.widgets.batch_rename_dialog import BatchRenameDialog
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开批量重命名失败: {e}")
            return

        dialog = BatchRenameDialog(self, selected_files)
        if not dialog.exec():
            return
        rename_map = dialog.get_results() or {}
        if not isinstance(rename_map, dict) or not rename_map:
            return

        success_count = 0
        fail_count = 0
        for file_info in (selected_files or []):
            old_path = file_info.get("path")
            if not old_path:
                continue
            if old_path not in rename_map:
                continue
            new_name = rename_map.get(old_path)
            if not new_name:
                continue
            dir_path = os.path.dirname(old_path)
            new_path = os.path.join(dir_path, str(new_name))
            if old_path == new_path:
                continue
            if os.path.exists(new_path) and str(old_path).lower() != str(new_path).lower():
                base, ext = os.path.splitext(str(new_name))
                counter = 1
                while os.path.exists(new_path):
                    new_name = f"{base}_{counter}{ext}"
                    new_path = os.path.join(dir_path, new_name)
                    counter += 1
            try:
                os.rename(old_path, new_path)
                try:
                    self.db.update_file_path(old_path, new_path, os.path.basename(new_path), table_name="import_cache")
                except Exception:
                    pass
                try:
                    self.db.update_file_path(old_path, new_path, os.path.basename(new_path), table_name="bird_results")
                except Exception:
                    pass
                try:
                    if hasattr(self, "cache_manager") and self.cache_manager is not None:
                        self.cache_manager.rename_cache(old_path, new_path)
                except Exception:
                    pass
                try:
                    for lst_name in ("image_files", "_all_image_files"):
                        lst = getattr(self, lst_name, None)
                        if not isinstance(lst, list):
                            continue
                        for it in lst:
                            if isinstance(it, dict) and it.get("path") == old_path:
                                it["path"] = new_path
                                it["name"] = os.path.basename(new_path)
                except Exception:
                    pass
                try:
                    for thumb in (getattr(self.grid_view, "thumbnails", []) or []):
                        info = getattr(thumb, "image_info", None)
                        if isinstance(info, dict) and info.get("path") == old_path:
                            info["path"] = new_path
                            info["name"] = os.path.basename(new_path)
                            try:
                                if hasattr(thumb, "_detail_cache"):
                                    thumb._detail_cache = None
                                if hasattr(thumb, "_detail_cache_path"):
                                    thumb._detail_cache_path = None
                            except Exception:
                                pass
                            try:
                                thumb.update()
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    if getattr(self, "current_preview_path", None) == old_path:
                        self.preview_image_file(new_path)
                except Exception:
                    pass
                success_count += 1
            except Exception:
                fail_count += 1
                continue

        if fail_count > 0:
            NotificationManager.instance().show_warning("提示", f"重命名完成：成功 {success_count}，失败 {fail_count}")
        else:
            NotificationManager.instance().show_toast(f"重命名完成：成功 {success_count}")

    def on_spray_mode_changed(self, active: bool, action_type: str, value):
        if not bool(getattr(self, "is_virtual_mode", False)):
            try:
                if hasattr(self, "toolbar") and self.toolbar and hasattr(self.toolbar, "deactivate_spray_mode"):
                    self.toolbar.deactivate_spray_mode()
            except Exception:
                pass
            return
        try:
            if hasattr(self, "grid_view") and self.grid_view and hasattr(self.grid_view, "set_spray_mode"):
                self.grid_view.set_spray_mode(bool(active), str(action_type or ""), value)
        except Exception:
            pass

    def on_spray_action_requested(self, action_type: str, value, indices):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        try:
            idxs = [int(i) for i in (indices or [])]
        except Exception:
            idxs = []
        if not idxs:
            return
        paths = []
        for i in idxs:
            if i < 0 or i >= len(self.image_files):
                continue
            it = self.image_files[i]
            if isinstance(it, dict) and it.get("path"):
                paths.append(str(it.get("path")))
        if not paths:
            return

        t = str(action_type or "")
        if t == "favorite":
            val = 1 if bool(value) else 0
            self._update_virtual_db_user_field(paths, "is_favorite", val)
            self._update_status_in_memory(paths, "is_favorite", val)
        elif t == "label":
            try:
                l = str(value or "")
            except Exception:
                l = ""
            self._update_virtual_db_user_field(paths, "label", l)
            self._update_status_in_memory(paths, "label", l)
        elif t == "rating":
            try:
                r = max(0, min(5, int(value or 0)))
            except Exception:
                r = 0
            self._update_virtual_db_user_field(paths, "rating", r)
            self._update_status_in_memory(paths, "rating", r)
        elif t == "stash":
            self._set_stash_for_paths(paths, bool(value))
        elif t == "tag":
            tags_str = ""
            mode = "overwrite"
            try:
                if isinstance(value, dict):
                    tags_str = str(value.get("tags") or "")
                    mode = str(value.get("mode") or "overwrite")
                else:
                    tags_str = str(value or "")
                    mode = "overwrite"
            except Exception:
                tags_str = ""
                mode = "overwrite"
            if mode not in ("append", "overwrite"):
                mode = "overwrite"
            if mode == "append":
                try:
                    current_map = self.db.get_user_fields_map(paths, table_name="import_cache") or {}
                except Exception:
                    current_map = {}
                merged_by_path = {}
                for p in paths:
                    cur = ""
                    try:
                        cur = str((current_map.get(p) or {}).get("tags") or "")
                    except Exception:
                        cur = ""
                    cur_parts = [s.strip() for s in cur.split("|") if s.strip()]
                    add_parts = [s.strip() for s in tags_str.split("|") if s.strip()]
                    merged = []
                    seen = set()
                    for s in (cur_parts + add_parts):
                        if s in seen:
                            continue
                        seen.add(s)
                        merged.append(s)
                    merged_by_path[p] = "|".join(merged)
                for p, merged_tags in merged_by_path.items():
                    try:
                        self.db.update_tags_batch_for_table([p], merged_tags, table_name="import_cache")
                    except Exception:
                        pass
                self._update_status_in_memory(paths, "tags", tags_str)
            else:
                try:
                    self.db.update_tags_batch_for_table(paths, tags_str, table_name="import_cache")
                except Exception as e:
                    NotificationManager.instance().show_warning("错误", f"更新标签失败: {e}")
                    return
                self._update_status_in_memory(paths, "tags", tags_str)

    def on_spray_cancel_requested(self):
        try:
            if hasattr(self, "toolbar") and self.toolbar and hasattr(self.toolbar, "deactivate_spray_mode"):
                self.toolbar.deactivate_spray_mode()
        except Exception:
            pass

    def show_detail_panel(self, index: int, compare_indices=None):
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
            if hasattr(self, "_stash_shortcut") and self._stash_shortcut is not None:
                self._stash_shortcut.setEnabled(False)
        except Exception:
            pass
        try:
            if hasattr(self, "_open_detail_shortcut") and self._open_detail_shortcut is not None:
                self._open_detail_shortcut.setEnabled(False)
        except Exception:
            pass

        try:
            if hasattr(self, "detail_panel") and self.detail_panel:
                self.detail_panel.setParent(None)
                self.detail_panel.deleteLater()
        except Exception:
            pass

        try:
            self.detail_panel = ImageDetailPanel(
                self.image_files,
                index,
                self.center_stack,
                compare_indices=compare_indices,
                cache_manager=self.cache_manager,
                show_action_overlay=self.is_virtual_mode, # 仅在虚拟模式下显示操作浮层
                show_import_to_library_button=True,
                show_stash_controls=True,
                db_table_name="import_cache",
                big_cache_context="import",
            )
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
            self.detail_panel.import_to_library_requested.connect(self.on_detail_import_to_library_requested)
            if hasattr(self.detail_panel, "stash_toggle_requested"):
                self.detail_panel.stash_toggle_requested.connect(self._on_detail_stash_toggle_requested)
        except Exception:
            pass

        try:
            if 0 <= index < len(self.image_files):
                p = self.image_files[index].get("path") if isinstance(self.image_files[index], dict) else None
                self._update_info_panel(p)
        except Exception:
            pass

    def hide_detail_panel(self):
        last_idx = getattr(self, "_detail_last_index", None)
        try:
            if last_idx is not None:
                last_idx = int(last_idx)
        except Exception:
            last_idx = None
        try:
            if hasattr(self, "detail_panel") and self.detail_panel:
                self.detail_panel.hide()
                self.detail_panel.setParent(None)
                self.detail_panel.deleteLater()
                self.detail_panel = None
        except Exception:
            self.detail_panel = None
        try:
            if hasattr(self, "_stash_shortcut") and self._stash_shortcut is not None:
                self._stash_shortcut.setEnabled(True)
        except Exception:
            pass
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
            self.content_splitter.show()
        except Exception:
            pass
        try:
            self._sync_focus_overlay_toolbar_buttons_from_settings()
        except Exception:
            pass
        try:
            if last_idx is not None and 0 <= int(last_idx) < len(self.image_files):
                p = self.image_files[int(last_idx)].get("path") if isinstance(self.image_files[int(last_idx)], dict) else None
                self._update_info_panel(p)
        except Exception:
            pass
        try:
            if last_idx is not None and hasattr(self, "grid_view") and self.grid_view:
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

    def _sync_focus_overlay_toolbar_buttons_from_settings(self):
        sm = getattr(self, "settings_manager", None)
        if sm is None:
            return
        try:
            subject_on = bool(sm.get("focus_detect_ui/show_subject_rect", True))
        except Exception:
            subject_on = True
        try:
            focus_on = bool(sm.get("focus_detect_ui/show_focus_point", True))
        except Exception:
            focus_on = True
        try:
            btn = getattr(self, "show_subject_rect_btn", None)
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(bool(subject_on))
                btn.blockSignals(False)
        except Exception:
            try:
                btn = getattr(self, "show_subject_rect_btn", None)
                if btn is not None:
                    btn.blockSignals(False)
            except Exception:
                pass
        try:
            btn = getattr(self, "show_focus_point_btn", None)
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(bool(focus_on))
                btn.blockSignals(False)
        except Exception:
            try:
                btn = getattr(self, "show_focus_point_btn", None)
                if btn is not None:
                    btn.blockSignals(False)
            except Exception:
                pass
        try:
            gv = getattr(self, "grid_view", None)
            if gv is not None and hasattr(gv, "refresh_visible_thumbnails"):
                gv.refresh_visible_thumbnails()
        except Exception:
            pass

        selected_files = self.get_selected_files()
        if selected_files:
            try:
                self._update_info_panel(selected_files[0].get("path"))
            except Exception:
                pass
            try:
                idx = int(selected_files[0].get("index", -1))
            except Exception:
                idx = -1
            if idx >= 0 and hasattr(self, "grid_view"):
                try:
                    self.grid_view.select_thumbnail(idx, scroll_to=True)
                except Exception:
                    pass
        else:
            try:
                self._update_info_panel(None)
            except Exception:
                pass

    def on_detail_image_changed(self, path: str):
        try:
            self._update_info_panel(path)
        except Exception:
            pass
        try:
            if hasattr(self, "detail_panel") and self.detail_panel and hasattr(self.detail_panel, "update_stash_ui"):
                self.detail_panel.update_stash_ui()
        except Exception:
            pass
        try:
            for i, img in enumerate(self.image_files or []):
                if isinstance(img, dict) and img.get("path") == path:
                    try:
                        self._detail_last_index = int(i)
                    except Exception:
                        self._detail_last_index = None
                    try:
                        self.grid_view.select_thumbnail(i, scroll_to=True)
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    def _on_detail_stash_toggle_requested(self, path: str):
        if not path:
            return
        self._toggle_stash_for_paths([path])
        try:
            if hasattr(self, "detail_panel") and self.detail_panel and hasattr(self.detail_panel, "update_stash_ui"):
                try:
                    self.detail_panel.image_list = self.image_files
                except Exception:
                    pass
                try:
                    self.detail_panel.populate_thumbnails()
                except Exception:
                    pass
                self.detail_panel.update_stash_ui()
        except Exception:
            pass

    def on_detail_import_to_library_requested(self, paths):
        if not paths:
            return
        if isinstance(paths, (str, bytes)):
            paths = [paths]
        selected_files = []
        seen = set()
        for p in (paths or []):
            if not p:
                continue
            try:
                pk = self._normalize_path_key(p)
            except Exception:
                pk = str(p)
            if pk in seen:
                continue
            seen.add(pk)
            found = None
            for it in (self.image_files or []):
                if not isinstance(it, dict):
                    continue
                if self._normalize_path_key(it.get("path")) == pk:
                    found = it
                    break
            if found is not None:
                selected_files.append(found.copy())
            else:
                try:
                    selected_files.append({"path": str(p), "name": os.path.basename(str(p))})
                except Exception:
                    selected_files.append({"path": str(p)})
        self._open_import_to_library_dialog_with_selected_files(selected_files)

    def _open_import_to_library_dialog_with_selected_files(self, selected_files):
        if not selected_files:
            NotificationManager.instance().show_warning("提示", "请先选择图片")
            return
        try:
            from ui.dialogs.import_to_library_rename_dialog import ImportToLibraryRenameDialog
            dialog = ImportToLibraryRenameDialog(self, selected_files=selected_files)
            try:
                def _on_import_succeeded(target_folder: str):
                    try:
                        if hasattr(self, "folder_panel") and self.folder_panel is not None:
                            skip_refresh = False
                            try:
                                if bool(getattr(self, "is_virtual_mode", False)):
                                    skip_refresh = True
                            except Exception:
                                skip_refresh = False
                            if not skip_refresh:
                                try:
                                    tree = getattr(self.folder_panel, "folder_tree", None)
                                    if tree is not None:
                                        for i in range(tree.topLevelItemCount()):
                                            top = tree.topLevelItem(i)
                                            if top is None:
                                                continue
                                            role = top.data(0, Qt.ItemDataRole.UserRole)
                                            if isinstance(role, str) and role.startswith("virtual://"):
                                                skip_refresh = True
                                                break
                                except Exception:
                                    pass
                            if not skip_refresh:
                                self.folder_panel.refresh_tree(target_path=str(target_folder or ""))
                    except Exception:
                        pass
                    try:
                        self.import_to_library_succeeded.emit(str(target_folder or ""))
                    except Exception:
                        pass
                dialog.import_succeeded.connect(_on_import_succeeded)
            except Exception:
                pass
            dialog.exec()
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开导入图库窗口失败: {e}")

    def preview_image_file(self, image_path):
        self.current_preview_path = image_path
        if hasattr(self, 'preview_panel'):
            self.preview_panel.load_image(image_path)
            fav = False
            rating = 0
            label = ""
            bbox = None
            focus_point = None
            orig_size = None
            fdj_for_overlay = None
            dbg_cur = ""
            dbg_info_bbox = None
            dbg_info_fp = None
            dbg_db_bbox = None
            dbg_db_fp = None
            try:
                info = self._find_image_info_by_path(image_path) if image_path else None
                if isinstance(info, dict):
                    fav = bool(int(info.get("is_favorite") or info.get("favorite") or 0) == 1)
                    rating = int(info.get("rating") or 0)
                    label = str(info.get("label") or "")
                    bbox = info.get("bbox")
                    focus_point = info.get("focus_point")
                    try:
                        dbg_info_bbox = bbox
                        dbg_info_fp = focus_point
                    except Exception:
                        pass
                    try:
                        w0 = info.get("width")
                        h0 = info.get("height")
                        if w0 and h0:
                            orig_size = (int(w0), int(h0))
                    except Exception:
                        orig_size = None
                    if orig_size is None:
                        try:
                            fdj = info.get("focus_detect_json")
                            if isinstance(fdj, str) and fdj.strip():
                                fdj = json.loads(fdj)
                            if isinstance(fdj, dict):
                                fdj_for_overlay = fdj
                                ow = fdj.get("orig_w")
                                oh = fdj.get("orig_h")
                                if ow and oh:
                                    orig_size = (int(ow), int(oh))
                        except Exception:
                            orig_size = None
                    if fdj_for_overlay is None and (bbox is None or focus_point is None):
                        try:
                            fdj = info.get("focus_detect_json")
                            if isinstance(fdj, str) and fdj.strip():
                                fdj = json.loads(fdj)
                            if isinstance(fdj, dict):
                                fdj_for_overlay = fdj
                        except Exception:
                            fdj_for_overlay = None

                if image_path and (bbox is None or focus_point is None):
                    rec = None
                    try:
                        if hasattr(self, "db") and self.db is not None and isinstance(info, dict):
                            fid0 = info.get("fast_id")
                            if fid0 and hasattr(self.db, "get_results_by_fast_ids"):
                                m = self.db.get_results_by_fast_ids([str(fid0)], table_name="import_cache") or {}
                                rec = m.get(str(fid0)) if isinstance(m, dict) else None
                            if rec is None:
                                u0 = info.get("uuid")
                                if u0 and hasattr(self.db, "get_result_by_uuid"):
                                    rec = self.db.get_result_by_uuid(str(u0), table_name="import_cache")
                    except Exception:
                        rec = None
                    if rec is None:
                        try:
                            recs = self.db.get_results_by_paths([str(image_path)], table_name="import_cache") if hasattr(self, "db") else {}
                        except Exception:
                            recs = {}
                        try:
                            rec = recs.get(str(image_path))
                        except Exception:
                            rec = None
                        if not isinstance(rec, dict):
                            rec = None
                    if rec is not None:
                        try:
                            fav = bool(int(rec.get("is_favorite") or 0) == 1)
                        except Exception:
                            pass
                        try:
                            rating = int(rec.get("rating") or 0)
                        except Exception:
                            pass
                        try:
                            label = str(rec.get("label") or "")
                        except Exception:
                            pass
                        try:
                            bbox = rec.get("bbox")
                        except Exception:
                            pass
                        try:
                            focus_point = rec.get("focus_point")
                        except Exception:
                            pass
                        try:
                            dbg_db_bbox = bbox
                            dbg_db_fp = focus_point
                        except Exception:
                            pass
                        if orig_size is None:
                            try:
                                fdj = rec.get("focus_detect_json")
                                if isinstance(fdj, str) and fdj.strip():
                                    fdj = json.loads(fdj)
                                if isinstance(fdj, dict):
                                    fdj_for_overlay = fdj
                                    ow = fdj.get("orig_w")
                                    oh = fdj.get("orig_h")
                                    if ow and oh:
                                        orig_size = (int(ow), int(oh))
                            except Exception:
                                orig_size = None
                        if fdj_for_overlay is None and (bbox is None or focus_point is None):
                            try:
                                fdj = rec.get("focus_detect_json")
                                if isinstance(fdj, str) and fdj.strip():
                                    fdj = json.loads(fdj)
                                if isinstance(fdj, dict):
                                    fdj_for_overlay = fdj
                            except Exception:
                                pass
            except Exception:
                fav = False
                rating = 0
                label = ""
                bbox = None
                focus_point = None
                orig_size = None
                fdj_for_overlay = None

            if bbox is None and isinstance(fdj_for_overlay, dict):
                if bbox is None:
                    try:
                        bbox = fdj_for_overlay.get("bbox_orig") or fdj_for_overlay.get("bbox")
                    except Exception:
                        pass
            try:
                if bool(getattr(self, "is_virtual_mode", False)):
                    try:
                        dbg_cur = str(getattr(self, "_current_folder_path", "") or "")
                    except Exception:
                        dbg_cur = ""
                    if dbg_cur.startswith("virtual://focus_detect?") or dbg_cur.startswith("virtual://focus_detect_burst?"):
                        from utils.log_manager import LogManager
                        LogManager.instance().info(
                            f"[FocusDetectUI] click path={str(image_path)} cur={dbg_cur} "
                            f"info_bbox={repr(dbg_info_bbox)[:160]} info_fp={repr(dbg_info_fp)[:160]} "
                            f"db_bbox={repr(dbg_db_bbox)[:160]} db_fp={repr(dbg_db_fp)[:160]} "
                            f"final_bbox={repr(bbox)[:160]} final_fp={repr(focus_point)[:160]} orig_size={repr(orig_size)}"
                        )
            except Exception:
                pass
            self.preview_panel.set_favorite(bool(fav))
            self.preview_panel.set_rating(int(rating))
            self.preview_panel.set_label(str(label))
            try:
                if hasattr(self.preview_panel, "set_overlays"):
                    self.preview_panel.set_overlays(bbox=bbox, focus_point=focus_point, orig_size=orig_size)
            except Exception:
                pass
        self._update_info_panel(image_path)
        try:
            QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
        except Exception:
            pass

    def _refresh_current_preview_overlays_from_import_cache(self):
        try:
            if not bool(getattr(self, "is_virtual_mode", False)):
                return
        except Exception:
            return
        p = getattr(self, "current_preview_path", None)
        if not p:
            return
        panel = getattr(self, "preview_panel", None)
        if panel is None or not hasattr(panel, "set_overlays"):
            return
        info = None
        try:
            info = self._find_image_info_by_path(str(p))
        except Exception:
            info = None
        bbox = None
        focus_point = None
        orig_size = None
        fdj = None
        if isinstance(info, dict):
            try:
                bbox = info.get("bbox")
            except Exception:
                bbox = None
            try:
                focus_point = info.get("focus_point")
            except Exception:
                focus_point = None
            try:
                w0 = info.get("width")
                h0 = info.get("height")
                if w0 and h0:
                    orig_size = (int(w0), int(h0))
            except Exception:
                orig_size = None
            try:
                raw_fdj = info.get("focus_detect_json")
                if isinstance(raw_fdj, str) and raw_fdj.strip():
                    raw_fdj = json.loads(raw_fdj)
                if isinstance(raw_fdj, dict):
                    fdj = raw_fdj
            except Exception:
                fdj = None

        if (bbox is None or focus_point is None) and fdj is None:
            rec = None
            try:
                if hasattr(self, "db") and self.db is not None and isinstance(info, dict):
                    u0 = info.get("uuid")
                    if u0 and hasattr(self.db, "get_result_by_uuid"):
                        rec = self.db.get_result_by_uuid(str(u0), table_name="import_cache")
            except Exception:
                rec = None
            if rec is None:
                try:
                    recs = self.db.get_results_by_paths([str(p)], table_name="import_cache") if hasattr(self, "db") else {}
                except Exception:
                    recs = {}
                try:
                    rec = recs.get(str(p))
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
                    raw_fdj = rec.get("focus_detect_json")
                    if isinstance(raw_fdj, str) and raw_fdj.strip():
                        raw_fdj = json.loads(raw_fdj)
                    if isinstance(raw_fdj, dict):
                        fdj = raw_fdj
                except Exception:
                    fdj = None
                if orig_size is None and isinstance(fdj, dict):
                    try:
                        ow = fdj.get("orig_w")
                        oh = fdj.get("orig_h")
                        if ow and oh:
                            orig_size = (int(ow), int(oh))
                    except Exception:
                        orig_size = None

        if bbox is None and isinstance(fdj, dict):
            if bbox is None:
                try:
                    bbox = fdj.get("bbox_orig") or fdj.get("bbox")
                except Exception:
                    pass

        try:
            panel.set_overlays(bbox=bbox, focus_point=focus_point, orig_size=orig_size)
        except Exception:
            pass

    def _focus_status_label(self, status: str) -> str:
        s = str(status or "")
        if s == "Sharp":
            return "锐利"
        if s == "Normal":
            return "普通"
        if s == "Blurry":
            return "虚焦"
        if s == "Minimal":
            return "极小"
        if s == "ExpFrame":
            return "爆框"
        if s == "NoBird":
            return "无鸟"
        return s or "-"

    def _format_focus_classification_reason(self, status: str, debug: dict) -> str:
        try:
            st = str(status or "")
        except Exception:
            st = ""
        if not isinstance(debug, dict):
            debug = {}
        r0 = str(debug.get("reason") or "")
        if r0 == "no_focus_detect":
            return "缺少对焦检测数据"
        if r0 == "no_bird_or_zero_score":
            return "未检测到鸟或得分为0，按无鸟分类"
        if r0 == "conf_below_threshold":
            try:
                conf = float(debug.get("conf") or 0.0)
            except Exception:
                conf = 0.0
            try:
                conf_th = float(debug.get("conf_th") or 0.0)
            except Exception:
                conf_th = 0.0
            return f"置信度{conf:.2f} < 阈值{conf_th:.2f}，按无鸟分类"
        if r0 == "minimal_area":
            try:
                area = float(debug.get("area") or 0.0)
            except Exception:
                area = 0.0
            try:
                th = float(debug.get("minimal_th") or 0.0)
            except Exception:
                th = 0.0
            return f"主体占比{area:.6f} < 极小阈值{th:.6f}，按极小分类"
        if r0 == "focus_point_in_bird_override":
            exp = bool(debug.get("exp_frame", False))
            if exp:
                return "对焦点落在鸟框内，判为锐利；同时爆框，归为爆框"
            return "对焦点落在鸟框内，按设置强制判为锐利"

        try:
            score = float(debug.get("score") or 0.0)
        except Exception:
            score = 0.0
        try:
            sharp_th = float(debug.get("sharp_th") or 0.0)
        except Exception:
            sharp_th = 0.0
        try:
            norm_score = float(debug.get("norm_score") or 0.0)
        except Exception:
            norm_score = 0.0
        try:
            norm_th = float(debug.get("norm_sharp_th") or 0.0)
        except Exception:
            norm_th = 0.0
        try:
            abs_ratio = float(debug.get("abs_ratio") or 0.0)
        except Exception:
            abs_ratio = 0.0
        try:
            contrast_score = float(debug.get("contrast_score") or 0.0)
        except Exception:
            contrast_score = 0.0
        try:
            focus_score = float(debug.get("focus_score") or 0.0)
        except Exception:
            focus_score = 0.0

        s_cmp = "≥" if score >= sharp_th else "<"
        n_cmp = "≥" if norm_score >= norm_th else "<"
        base = f"得分{score:.0f} {s_cmp} 锐度阈值{sharp_th:.0f}；归一化得分{norm_score:.0f} {n_cmp} 归一化阈值{norm_th:.0f}"

        if st == "Sharp":
            return f"{base}；综合指标{focus_score:.2f} 满足【锐利】条件"
        if st == "Normal":
            return f"{base}；综合指标{focus_score:.2f} 未达到【锐利】条件，满足【普通】条件"
        if st == "Blurry":
            return f"{base}；综合指标{focus_score:.2f} 未达到【普通】条件，判为【虚焦】"
        if st == "ExpFrame":
            return f"{base}；检测到【爆框】，判为【爆框】"
        return base or "-"

    def _update_info_panel(self, image_path):
        try:
            panel = getattr(self, "info_panel", None)
            if panel is None:
                return
        except Exception:
            return

        ctx = None
        try:
            p0 = str(image_path or "")
        except Exception:
            p0 = ""
        try:
            cur = str(getattr(self, "_current_folder_path", "") or "")
        except Exception:
            cur = ""
        if p0 and bool(getattr(self, "is_virtual_mode", False)) and isinstance(cur, str) and (cur.startswith("virtual://focus_detect?") or cur.startswith("virtual://focus_detect_burst?")):
            try:
                rec = self.db.get_result_by_path(p0, table_name="import_cache") if hasattr(self, "db") else None
            except Exception:
                rec = None
            if not isinstance(rec, dict):
                rec = self._find_image_info_by_path(p0) if hasattr(self, "_find_image_info_by_path") else None
            if not isinstance(rec, dict):
                rec = {}
            try:
                thresholds = self._get_focus_detect_ui_thresholds()
            except Exception:
                thresholds = {}
            try:
                st, dbg = self._compute_focus_status_and_debug(rec, thresholds)
            except Exception:
                st, dbg = "NoBird", {"reason": "no_focus_detect"}
            try:
                ctx = {
                    "focus_status": f"{self._focus_status_label(st)}（{str(st or '')}）" if str(st or "") else "-",
                    "focus_reason": self._format_focus_classification_reason(st, dbg),
                }
            except Exception:
                ctx = None
            if isinstance(ctx, dict):
                try:
                    ctx["score"] = rec.get("score")
                except Exception:
                    pass
                try:
                    ctx["norm_score"] = rec.get("norm_score")
                except Exception:
                    pass
                try:
                    ctx["area_ratio"] = rec.get("area_ratio")
                except Exception:
                    pass
                try:
                    ctx["rating"] = rec.get("rating")
                except Exception:
                    pass

        try:
            panel.update_info(image_path, ctx)
        except Exception:
            try:
                panel.update_info(image_path)
            except Exception:
                pass

    def clear_preview(self):
        self.current_preview_path = None
        if hasattr(self, 'preview_panel'):
            self.preview_panel.load_image(None)
            self.preview_panel.set_favorite(False)
            self.preview_panel.set_rating(0)
            self.preview_panel.set_label("")
        self._update_info_panel(None)

    def on_folder_selected(self, path, depth):
        """处理文件夹选择"""
        if not path or path == "__placeholder__":
            self.image_files = []
            self.grid_view.clear_thumbnails()
            self._thumb_by_path.clear()
            self.loaded_count = 0
            self.selected_count = 0
            self.has_valid_folder = False
            self._loaded_paths = set()
            self.stats_changed.emit(0, 0, 0)
            return
        if isinstance(path, str) and path == "virtual://focus_detect_root":
            try:
                QTimer.singleShot(0, self._reload_virtual_focus_detect_view)
            except Exception:
                pass
            return
        try:
            self._requested_exif_paths = set()
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._update_focus_threshold_panel_visibility)
        except Exception:
            pass
        if isinstance(path, str) and path.startswith("virtual://"):
            try:
                if str(path).startswith("virtual://focus_detect_burst?"):
                    folder, first_name, status = self._parse_focus_detect_burst_virtual_path(str(path))
                    if not folder or not first_name:
                        return
                    try:
                        self.image_files = []
                        self._all_image_files = []
                        self._thumb_by_path = {}
                        self.loaded_count = 0
                        self.selected_count = 0
                        self._requested_paths = set()
                        self._requested_exif_paths = set()
                        self._loaded_paths = set()
                    except Exception:
                        pass
                    try:
                        self.grid_view.clear_thumbnails()
                    except Exception:
                        pass
                    try:
                        self.big_image_cache.clear()
                    except Exception:
                        pass
                    self.has_valid_folder = True
                    try:
                        self._current_folder_path = str(path)
                    except Exception:
                        pass
                    self._folder_load_request_id += 1
                    request_id = self._folder_load_request_id
                    self.loading_overlay.hide_loading()
                    self._startup_initial_load_processed = False
                    try:
                        self._force_hide_startup_mask()
                    except Exception:
                        pass
                    try:
                        QTimer.singleShot(0, self._update_focus_threshold_panel_visibility)
                    except Exception:
                        pass
                    try:
                        if hasattr(self.grid_view, "_details_compact"):
                            self.grid_view._details_compact = int(getattr(self, "display_mode", 1) or 1) != ImageThumbnail.MODE_WITH_DETAILS
                    except Exception:
                        pass
                    try:
                        self.grid_view.set_display_mode(int(getattr(self, "display_mode", 1) or 1))
                    except Exception:
                        pass
                    try:
                        self.grid_view.set_thumbnail_size(getattr(self.grid_view, "current_thumb_size", 120), scale_visible_only=False, extra_rows=2)
                    except Exception:
                        pass
                    try:
                        thresholds = self._get_focus_detect_ui_thresholds()
                    except Exception:
                        thresholds = {}
                    status_sel = str(status or "All") or "All"

                    def run_scan():
                        items = []
                        bird_map_norm = {}
                        try:
                            rows = self.db.list_import_cache_by_burst_first_in_folder(folder, first_name, limit=100000)
                        except Exception:
                            rows = []
                        try:
                            paths0 = []
                            for r0 in (rows or []):
                                try:
                                    fp0 = str(r0.get("file_path") or "")
                                except Exception:
                                    fp0 = ""
                                if fp0:
                                    paths0.append(fp0)
                            if paths0:
                                db_paths = []
                                for p0 in paths0:
                                    try:
                                        p_db = self.db._normalize_file_path_for_db(p0)
                                    except Exception:
                                        p_db = p0
                                    if p_db:
                                        db_paths.append(str(p_db))
                                br_map = self.db.get_results_by_paths(list(dict.fromkeys(db_paths)), table_name="bird_results") or {}
                                for k, v in (br_map or {}).items():
                                    try:
                                        nk = self.db._norm_path_key(k)
                                    except Exception:
                                        nk = k
                                    if nk and isinstance(v, dict):
                                        bird_map_norm[str(nk)] = v
                        except Exception:
                            bird_map_norm = {}
                        for r in (rows or []):
                            try:
                                fp = str(r.get("file_path") or "")
                                if not fp:
                                    continue
                                try:
                                    st = self._compute_focus_status_for_item(r, thresholds)
                                except Exception:
                                    st = "NoBird"
                                try:
                                    stat = os.stat(fp)
                                    file_size = int(stat.st_size)
                                    create_time = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                                except Exception:
                                    file_size = 0
                                    create_time = str(r.get("created_at") or "")
                                shot_time = str(r.get("shot_time") or "")
                                if not shot_time.strip():
                                    shot_time = create_time
                                w0 = 0
                                h0 = 0
                                try:
                                    fdj = r.get("focus_detect_json")
                                except Exception:
                                    fdj = None
                                fd = None
                                if isinstance(fdj, dict):
                                    fd = fdj
                                elif isinstance(fdj, str):
                                    s = fdj.strip()
                                    if s:
                                        try:
                                            fd = json.loads(s)
                                        except Exception:
                                            fd = None
                                if isinstance(fd, dict):
                                    try:
                                        w0 = int(float(fd.get("orig_w") or 0))
                                    except Exception:
                                        w0 = 0
                                    try:
                                        h0 = int(float(fd.get("orig_h") or 0))
                                    except Exception:
                                        h0 = 0
                                if w0 <= 1 or h0 <= 1:
                                    try:
                                        from cache.focus_scaled_cache import try_load_meta
                                        focus_target = 640
                                        try:
                                            focus_target = int(self.settings_manager.get("focus_detect/target_size", 640) or 640)
                                        except Exception:
                                            focus_target = 640
                                        meta0 = try_load_meta(fp, int(focus_target), scope="import_focus")
                                        if isinstance(meta0, dict):
                                            try:
                                                w0 = int(float(meta0.get("orig_w") or 0))
                                            except Exception:
                                                pass
                                            try:
                                                h0 = int(float(meta0.get("orig_h") or 0))
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                iso = r.get("iso")
                                fnumber = r.get("fnumber")
                                shutter = r.get("shutter")
                                focal_length = r.get("focal_length")
                                if (iso in (None, "", 0, 0.0) and (shutter in (None, "")) and (fnumber in (None, "", 0, 0.0)) and (focal_length in (None, ""))):
                                    try:
                                        fp_db = self.db._normalize_file_path_for_db(fp)
                                        br = bird_map_norm.get(self.db._norm_path_key(fp_db)) if fp_db else None
                                    except Exception:
                                        br = None
                                    if isinstance(br, dict):
                                        try:
                                            iso2 = br.get("iso")
                                            if iso2 not in (None, "", 0, 0.0):
                                                iso = iso2
                                        except Exception:
                                            pass
                                        try:
                                            f2 = br.get("fnumber")
                                            if f2 not in (None, "", 0, 0.0):
                                                fnumber = f2
                                        except Exception:
                                            pass
                                        try:
                                            s2 = br.get("shutter")
                                            if s2 not in (None, ""):
                                                shutter = s2
                                        except Exception:
                                            pass
                                        try:
                                            fl2 = br.get("focal_length")
                                            if fl2 not in (None, ""):
                                                focal_length = fl2
                                        except Exception:
                                            pass
                                has_exif = False
                                try:
                                    has_exif = bool(
                                        (shot_time and shot_time != create_time)
                                        or (iso not in (None, "", 0, 0.0))
                                        or (fnumber not in (None, "", 0, 0.0))
                                        or (shutter not in (None, ""))
                                        or (focal_length not in (None, ""))
                                    )
                                except Exception:
                                    has_exif = False
                                items.append(
                                    {
                                        "path": fp,
                                        "name": str(r.get("file_name") or os.path.basename(fp)),
                                        "uuid": r.get("uuid"),
                                        "fast_id": r.get("fast_id"),
                                        "size": file_size,
                                        "pixel_count": int(r.get("pixel_count") or 0),
                                        "create_time": create_time,
                                        "shot_time": shot_time,
                                        "width": int(w0),
                                        "height": int(h0),
                                        "has_exif": has_exif,
                                        "label": r.get("label"),
                                        "rating": r.get("rating", 0),
                                        "is_favorite": int(r.get("is_favorite") or 0),
                                        "favorite": int(r.get("is_favorite") or 0),
                                        "description": r.get("description") or "",
                                        "focus_detect_json": r.get("focus_detect_json") or "",
                                        "score": r.get("score"),
                                        "norm_score": r.get("norm_score"),
                                        "area_ratio": r.get("area_ratio"),
                                        "bbox": r.get("bbox"),
                                        "focus_point": r.get("focus_point"),
                                        "position": r.get("position"),
                                        "object": r.get("object"),
                                        "iso": iso,
                                        "fnumber": fnumber,
                                        "shutter": shutter,
                                        "focal_length": focal_length,
                                        "camera_model": r.get("camera_model"),
                                        "lens_model": r.get("lens_model"),
                                        "focus_status": str(st),
                                    }
                                )
                            except Exception:
                                continue
                        if request_id != self._folder_load_request_id:
                            return
                        self.scanResultsReady.emit(request_id, items)

                    Thread(target=run_scan, daemon=True, name=f"ImportVirtualBurstScan-{request_id}").start()
                    return
                if str(path).startswith("virtual://focus_detect?"):
                    folder, status, sub = self._parse_focus_detect_virtual_path(str(path))
                    if not folder:
                        return
                    try:
                        self.image_files = []
                        self._all_image_files = []
                        self._thumb_by_path = {}
                        self.loaded_count = 0
                        self.selected_count = 0
                        self._requested_paths = set()
                        self._requested_exif_paths = set()
                        self._loaded_paths = set()
                    except Exception:
                        pass
                    try:
                        self.grid_view.clear_thumbnails()
                    except Exception:
                        pass
                    try:
                        self.big_image_cache.clear()
                    except Exception:
                        pass
                    self.has_valid_folder = True
                    try:
                        self._current_folder_path = str(path)
                    except Exception:
                        pass
                    try:
                        self._virtual_focus_selected_folder = str(folder)
                        self._virtual_focus_selected_status = str(status or "All")
                        self._virtual_focus_selected_sub = str(sub or "")
                    except Exception:
                        self._virtual_focus_selected_folder = str(folder)
                        self._virtual_focus_selected_status = "All"
                        self._virtual_focus_selected_sub = ""
                    self._folder_load_request_id += 1
                    request_id = self._folder_load_request_id
                    self.loading_overlay.hide_loading()
                    self._startup_initial_load_processed = False
                    try:
                        self._force_hide_startup_mask()
                    except Exception:
                        pass
                    try:
                        QTimer.singleShot(0, self._update_focus_threshold_panel_visibility)
                    except Exception:
                        pass
                    try:
                        if hasattr(self.grid_view, "_details_compact"):
                            self.grid_view._details_compact = int(getattr(self, "display_mode", 1) or 1) != ImageThumbnail.MODE_WITH_DETAILS
                    except Exception:
                        pass
                    try:
                        self.grid_view.set_display_mode(int(getattr(self, "display_mode", 1) or 1))
                    except Exception:
                        pass
                    try:
                        self.grid_view.set_thumbnail_size(getattr(self.grid_view, "current_thumb_size", 120), scale_visible_only=False, extra_rows=2)
                    except Exception:
                        pass

                    try:
                        thresholds = self._get_focus_detect_ui_thresholds()
                    except Exception:
                        thresholds = {}
                    status_sel = str(status or "All") or "All"
                    sub_sel = str(sub or "").strip()

                    def _burst_first_file(row: dict) -> str:
                        try:
                            fd = self._extract_focus_detect_info(row)
                        except Exception:
                            fd = {}
                        if not isinstance(fd, dict):
                            return ""
                        try:
                            v = str(fd.get("burst_first_file") or "")
                        except Exception:
                            v = ""
                        return v.strip()

                    def run_scan():
                        items = []
                        try:
                            rows = self.db.list_import_cache_by_folder(folder, limit=100000)
                        except Exception:
                            rows = []
                        try:
                            self._vdbg_log(f"virtual_scan: folder={folder} rows={len(rows or [])}")
                        except Exception:
                            pass
                        bird_map = {}
                        bird_map_norm = {}
                        try:
                            paths = []
                            for r in (rows or []):
                                try:
                                    fp0 = str(r.get("file_path") or "")
                                except Exception:
                                    fp0 = ""
                                if fp0:
                                    paths.append(fp0)
                            if paths:
                                try:
                                    db_paths = []
                                    for p0 in paths:
                                        try:
                                            p_db = self.db._normalize_file_path_for_db(p0)
                                        except Exception:
                                            p_db = p0
                                        if p_db:
                                            db_paths.append(str(p_db))
                                    bird_map = self.db.get_results_by_paths(db_paths, table_name="bird_results") or {}
                                    for k, v in (bird_map or {}).items():
                                        try:
                                            nk = self.db._norm_path_key(k)
                                        except Exception:
                                            nk = k
                                        if nk:
                                            bird_map_norm[str(nk)] = v
                                except Exception:
                                    bird_map = {}
                                    bird_map_norm = {}
                        except Exception:
                            bird_map = {}
                            bird_map_norm = {}
                        try:
                            self._vdbg_log(f"virtual_scan: bird_results_map={len(bird_map_norm or {})}")
                        except Exception:
                            pass
                        try:
                            from PyQt6.QtGui import QImageReader
                        except Exception:
                            QImageReader = None
                        for r in (rows or []):
                            try:
                                fp = str(r.get("file_path") or "")
                                if not fp:
                                    continue
                                if sub_sel:
                                    try:
                                        base = self._normalize_folder_key(folder)
                                        if base and not base.endswith(os.sep):
                                            base = base + os.sep
                                        d0 = self._normalize_folder_key(os.path.dirname(fp))
                                        if not base or not d0 or (not d0.startswith(base)):
                                            continue
                                        rel = d0[len(base):]
                                        rel = "" if rel in (".", os.curdir) else rel
                                        first = rel.split(os.sep)[0] if rel else ""
                                        if first != sub_sel:
                                            continue
                                    except Exception:
                                        try:
                                            from utils.setting.settings_manager import SettingsManager
                                            if bool(SettingsManager().get("debug/focus_virtual_counts_log", False)):
                                                from utils.log_manager import LogManager
                                                LogManager.instance().info(f"[FocusDetectUI] sub_filter_failed folder={folder} fp={fp}")
                                        except Exception:
                                            pass
                                        continue
                                try:
                                    st = self._compute_focus_status_for_item(r, thresholds)
                                except Exception:
                                    st = "NoBird"
                                try:
                                    stat = os.stat(fp)
                                    file_size = int(stat.st_size)
                                    create_time = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                                except Exception:
                                    file_size = 0
                                    create_time = str(r.get("created_at") or "")
                                width = 0
                                height = 0
                                if QImageReader is not None and os.path.exists(fp):
                                    try:
                                        from utils.system.stderr_suppressor import suppress_stderr_fd

                                        with suppress_stderr_fd():
                                            reader = QImageReader(fp)
                                            s = reader.size()
                                            width = int(s.width()) if s and s.width() > 0 else 0
                                            height = int(s.height()) if s and s.height() > 0 else 0
                                    except Exception:
                                        width = 0
                                        height = 0
                                if width <= 1 or height <= 1:
                                    try:
                                        fdj = r.get("focus_detect_json")
                                    except Exception:
                                        fdj = None
                                    fd = None
                                    if isinstance(fdj, dict):
                                        fd = fdj
                                    elif isinstance(fdj, str):
                                        s0 = fdj.strip()
                                        if s0:
                                            try:
                                                fd = json.loads(s0)
                                            except Exception:
                                                fd = None
                                    if isinstance(fd, dict):
                                        try:
                                            width = int(float(fd.get("orig_w") or 0))
                                        except Exception:
                                            pass
                                        try:
                                            height = int(float(fd.get("orig_h") or 0))
                                        except Exception:
                                            pass
                                if width <= 1 or height <= 1:
                                    try:
                                        from cache.focus_scaled_cache import try_load_meta
                                        focus_target = 640
                                        try:
                                            focus_target = int(self.settings_manager.get("focus_detect/target_size", 640) or 640)
                                        except Exception:
                                            focus_target = 640
                                        meta0 = try_load_meta(fp, int(focus_target), scope="import_focus")
                                        if isinstance(meta0, dict):
                                            try:
                                                width = int(float(meta0.get("orig_w") or 0))
                                            except Exception:
                                                pass
                                            try:
                                                height = int(float(meta0.get("orig_h") or 0))
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                if width <= 1 or height <= 1:
                                    try:
                                        bb = r.get("bbox")
                                    except Exception:
                                        bb = None
                                    try:
                                        fp0 = r.get("focus_point")
                                    except Exception:
                                        fp0 = None
                                    if isinstance(bb, str) and bb.strip():
                                        try:
                                            bb = json.loads(bb)
                                        except Exception:
                                            bb = None
                                    if isinstance(fp0, str) and fp0.strip():
                                        try:
                                            fp0 = json.loads(fp0)
                                        except Exception:
                                            fp0 = None
                                    try:
                                        if isinstance(bb, (list, tuple)) and len(bb) >= 4:
                                            x1, y1, x2, y2 = bb[0], bb[1], bb[2], bb[3]
                                            x2 = float(x2)
                                            y2 = float(y2)
                                            if x2 > 1 and y2 > 1:
                                                width = max(int(width or 0), int(round(x2)))
                                                height = max(int(height or 0), int(round(y2)))
                                    except Exception:
                                        pass
                                    try:
                                        if isinstance(fp0, (list, tuple)) and len(fp0) >= 2:
                                            fx, fy = float(fp0[0]), float(fp0[1])
                                            if fx > 1 and fy > 1:
                                                width = max(int(width or 0), int(round(fx)))
                                                height = max(int(height or 0), int(round(fy)))
                                    except Exception:
                                        pass
                                shot_time = str(r.get("shot_time") or "")
                                if not shot_time.strip():
                                    shot_time = create_time
                                iso = r.get("iso")
                                fnumber = r.get("fnumber")
                                shutter = r.get("shutter")
                                focal_length = r.get("focal_length")
                                if (iso in (None, "", 0, 0.0) and (shutter in (None, "")) and (fnumber in (None, "", 0, 0.0)) and (focal_length in (None, ""))):
                                    try:
                                        try:
                                            fp_db = self.db._normalize_file_path_for_db(fp)
                                        except Exception:
                                            fp_db = fp
                                        try:
                                            fp_nk = self.db._norm_path_key(fp_db)
                                        except Exception:
                                            fp_nk = fp_db
                                        br = bird_map_norm.get(str(fp_nk)) or bird_map.get(str(fp_db)) or bird_map.get(fp) or {}
                                    except Exception:
                                        br = {}
                                    if isinstance(br, dict) and br:
                                        try:
                                            shot_time2 = str(br.get("shot_time") or "")
                                            if shot_time2.strip():
                                                shot_time = shot_time2
                                        except Exception:
                                            pass
                                        try:
                                            iso2 = br.get("iso")
                                            if iso2 not in (None, "", 0, 0.0):
                                                iso = iso2
                                        except Exception:
                                            pass
                                        try:
                                            fnumber2 = br.get("fnumber")
                                            if fnumber2 not in (None, "", 0, 0.0):
                                                fnumber = fnumber2
                                        except Exception:
                                            pass
                                        try:
                                            shutter2 = br.get("shutter")
                                            if shutter2 not in (None, ""):
                                                shutter = shutter2
                                        except Exception:
                                            pass
                                        try:
                                            focal2 = br.get("focal_length")
                                            if focal2 not in (None, ""):
                                                focal_length = focal2
                                        except Exception:
                                            pass
                                has_exif = False
                                try:
                                    has_exif = bool(
                                        (shot_time and shot_time != create_time)
                                        or (iso not in (None, "", 0, 0.0))
                                        or (fnumber not in (None, "", 0, 0.0))
                                        or (shutter not in (None, ""))
                                        or (focal_length not in (None, ""))
                                    )
                                except Exception:
                                    has_exif = False
                                items.append(
                                    {
                                        "path": fp,
                                        "name": str(r.get("file_name") or os.path.basename(fp)),
                                        "uuid": r.get("uuid"),
                                        "fast_id": r.get("fast_id"),
                                        "size": file_size,
                                        "pixel_count": int(r.get("pixel_count") or 0),
                                        "create_time": create_time,
                                        "shot_time": shot_time,
                                        "width": width,
                                        "height": height,
                                        "has_exif": has_exif,
                                        "label": r.get("label"),
                                        "rating": r.get("rating", 0),
                                        "is_favorite": int(r.get("is_favorite") or 0),
                                        "favorite": int(r.get("is_favorite") or 0),
                                        "description": r.get("description") or "",
                                        "focus_detect_json": r.get("focus_detect_json") or "",
                                        "score": r.get("score"),
                                        "norm_score": r.get("norm_score"),
                                        "area_ratio": r.get("area_ratio"),
                                        "bbox": r.get("bbox"),
                                        "focus_point": r.get("focus_point"),
                                        "position": r.get("position"),
                                        "object": r.get("object"),
                                        "iso": iso,
                                        "fnumber": fnumber,
                                        "shutter": shutter,
                                        "focal_length": focal_length,
                                        "camera_model": r.get("camera_model"),
                                        "lens_model": r.get("lens_model"),
                                        "focus_status": str(st),
                                    }
                                )
                            except Exception:
                                continue
                        if request_id != self._folder_load_request_id:
                            return
                        self.scanResultsReady.emit(request_id, items)

                    Thread(target=run_scan, daemon=True, name=f"ImportVirtualScan-{request_id}").start()
                    return
                return
            except Exception as e:
                try:
                    LogManager.instance().warning(f"虚拟文件夹加载失败: {e}")
                except Exception:
                    pass
                try:
                    NotificationManager.instance().show_warning("错误", f"虚拟视图加载失败: {e}")
                except Exception:
                    pass
                return
        try:
            path = os.path.normcase(os.path.normpath(str(path).replace("/", os.sep)))
        except Exception:
            try:
                path = os.path.normcase(str(path).replace("/", os.sep))
            except Exception:
                pass
        if os.path.isfile(path):
            path = os.path.dirname(path)
        if not os.path.isdir(path):
            self.image_files = []
            self.grid_view.clear_thumbnails()
            self._thumb_by_path.clear()
            self.loaded_count = 0
            self.selected_count = 0
            self.has_valid_folder = False
            self._loaded_paths = set()
            self.stats_changed.emit(0, 0, 0)
            return
        self.has_valid_folder = True
        self.settings_manager.set("import/last_folder", path)
        self.load_images(path)

    def load_images(self, folder_path, recursive=False):
        if not folder_path or not os.path.exists(folder_path):
            self.has_valid_folder = False
            self._loaded_paths = set()
            self.stats_changed.emit(0, 0, 0)
            return
        try:
            self.big_image_cache.clear()
        except Exception:
            pass
        try:
            normalized_folder = os.path.normpath(str(folder_path))
        except Exception:
            normalized_folder = str(folder_path)
        if not self.is_virtual_mode:
            self._current_folder_path = normalized_folder
            try:
                self.settings_manager.set("import/last_folder", normalized_folder)
            except Exception:
                pass
            try:
                if hasattr(self, "folder_panel") and hasattr(self.folder_panel, "navigate_to_folder"):
                    do_sync = True
                    try:
                        tree = getattr(self.folder_panel, "folder_tree", None)
                        cur_item = tree.currentItem() if tree is not None else None
                        cur_path = cur_item.data(0, Qt.ItemDataRole.UserRole) if cur_item is not None else None
                        if cur_path:
                            do_sync = os.path.normcase(os.path.normpath(str(cur_path))) != os.path.normcase(os.path.normpath(str(normalized_folder)))
                    except Exception:
                        do_sync = True
                    if do_sync:
                        self.folder_panel.navigate_to_folder(normalized_folder)
            except Exception:
                pass
        if self._thumb_status_task_id is not None:
            StatusManager.instance().finish_task(self._thumb_status_task_id)
            self._thumb_status_task_id = None
        self.has_valid_folder = True
        try:
            self.thumbnail_loader.cancel_all()
        except Exception:
            pass
        self._folder_load_request_id += 1
        request_id = self._folder_load_request_id
        self.loading_overlay.hide_loading()
        self._startup_initial_load_processed = False
        try:
            if bool(getattr(self, "is_virtual_mode", False)) or str(normalized_folder or "").startswith("virtual://"):
                self._force_hide_startup_mask()
            else:
                self._show_startup_mask("正在加载...")
        except Exception:
            try:
                self._show_startup_mask("正在加载...")
            except Exception:
                pass

        def run_scan():
            image_files = []
            valid_extensions = set(ext.lower() for ext in (raw_exts + img_exts))
            try:
                from PyQt6.QtGui import QImageReader
            except Exception:
                QImageReader = None
            excl = []
            try:
                for p in (self.settings_manager.get("library/scan_exclude_dirs", []) or []):
                    if not p:
                        continue
                    try:
                        excl.append(os.path.normcase(os.path.normpath(str(p))))
                    except Exception:
                        excl.append(str(p))
            except Exception:
                excl = []
            rx = None
            try:
                rx_str = str(self.settings_manager.get("library/scan_exclude_regex", "") or "").strip()
            except Exception:
                rx_str = ""
            if rx_str:
                try:
                    rx = re.compile(rx_str, flags=re.IGNORECASE)
                except Exception:
                    try:
                        if any(ch in rx_str for ch in ("*", "?")):
                            rx = re.compile(fnmatch.translate(str(rx_str).replace("\\", "/")), flags=re.IGNORECASE)
                    except Exception:
                        rx = None

            def _path_matches_exclude(p: str) -> bool:
                if not rx:
                    return False
                try:
                    s = os.path.normcase(os.path.normpath(str(p))).replace("\\", "/")
                except Exception:
                    try:
                        s = str(p).replace("\\", "/")
                    except Exception:
                        return False
                try:
                    return bool(rx.search(s))
                except Exception:
                    return False

            def _is_excluded_dir(p: str) -> bool:
                try:
                    p_norm = os.path.normcase(os.path.normpath(str(p)))
                except Exception:
                    p_norm = str(p)
                    
                # 默认排除回收站等系统目录（即使 excl 为空）
                default_excludes = ["$RECYCLE.BIN", "System Volume Information", "Recovery"]
                for de in default_excludes:
                    if de.lower() in p_norm.lower():
                         # 检查是否是路径的一部分，且作为独立目录名出现
                         # 简单做法：只要包含这个名字，大概率就是系统目录
                         return True
                
                for e in excl:
                    if not e:
                        continue
                    if p_norm == e:
                        return True
                    try:
                        if p_norm.startswith(e + os.sep):
                            return True
                    except Exception:
                        continue
                if _path_matches_exclude(p_norm):
                    return True
                return False

            last_err = ""
            seen_paths = set() # 用于文件去重
            seen_dirs = set()  # 用于目录去重 (避免软链接循环或重复访问)
            
            try:
                if recursive:
                    for root, dirs, files in os.walk(folder_path):
                        # 检查当前目录是否已访问过 (normcase 处理大小写)
                        try:
                            norm_root = os.path.normcase(os.path.normpath(root))
                            if norm_root in seen_dirs:
                                dirs[:] = [] # 阻止进入子目录
                                continue
                            seen_dirs.add(norm_root)
                        except Exception:
                            pass

                        if _is_excluded_dir(root):
                            dirs[:] = []
                            continue
                        if dirs:
                            kept = []
                            for d in list(dirs):
                                full = os.path.join(root, d)
                                # 预先检查子目录是否被排除或已访问
                                if _is_excluded_dir(full):
                                    continue
                                # 检查软链接或重复路径
                                try:
                                    # 如果是软链接，根据需求决定是否跟随。这里简单起见，记录真实路径以防循环
                                    # 如果不需要跟随软链接，可以直接: if os.path.islink(full): continue
                                    norm_full = os.path.normcase(os.path.normpath(full))
                                    if norm_full in seen_dirs:
                                        continue
                                    
                                    # 如果跟随软链接，需要检查目标真实路径
                                    if os.path.islink(full):
                                        real_path = os.path.realpath(full)
                                        norm_real = os.path.normcase(real_path)
                                        if norm_real in seen_dirs:
                                            continue
                                except Exception:
                                    pass
                                    
                                kept.append(d)
                            dirs[:] = kept
                        for name in files:
                            ext = os.path.splitext(name)[1].lower()
                            if ext in valid_extensions:
                                full_path = os.path.join(root, name)
                                
                                # 文件去重检查
                                try:
                                    norm_path = os.path.normcase(os.path.normpath(full_path))
                                    if norm_path in seen_paths:
                                        continue
                                    seen_paths.add(norm_path)
                                except Exception:
                                    pass
                                
                                if _path_matches_exclude(full_path):
                                    continue
                                try:
                                    stat = os.stat(full_path)
                                    width = 0
                                    height = 0
                                    if QImageReader is not None:
                                        try:
                                            from utils.system.stderr_suppressor import suppress_stderr_fd

                                            with suppress_stderr_fd():
                                                reader = QImageReader(full_path)
                                                s = reader.size()
                                                width = int(s.width()) if s and s.width() > 0 else 0
                                                height = int(s.height()) if s and s.height() > 0 else 0
                                        except Exception:
                                            width = 0
                                            height = 0
                                    create_time = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                                    image_files.append({
                                        'path': full_path,
                                        'name': name,
                                        'create_time': create_time,
                                        'shot_time': create_time,
                                        'size': stat.st_size,
                                        'width': width,
                                        'height': height,
                                        'has_exif': False,
                                    })
                                except Exception:
                                    pass
                else:
                    # 非递归模式不需要 seen_dirs，但也可以用 seen_paths 简单的去重
                    with os.scandir(folder_path) as entries:
                        for entry in entries:
                            if entry.is_file():
                                ext = os.path.splitext(entry.name)[1].lower()
                                if ext in valid_extensions:
                                    # 文件去重检查
                                    try:
                                        norm_path = os.path.normcase(os.path.normpath(entry.path))
                                        if norm_path in seen_paths:
                                            continue
                                        seen_paths.add(norm_path)
                                    except Exception:
                                        pass
                                        
                                    if _path_matches_exclude(entry.path):
                                        continue
                                    stat = entry.stat()
                                    width = 0
                                    height = 0
                                    if QImageReader is not None:
                                        try:
                                            from utils.system.stderr_suppressor import suppress_stderr_fd

                                            with suppress_stderr_fd():
                                                reader = QImageReader(entry.path)
                                                s = reader.size()
                                                width = int(s.width()) if s and s.width() > 0 else 0
                                                height = int(s.height()) if s and s.height() > 0 else 0
                                        except Exception:
                                            width = 0
                                            height = 0
                                    create_time = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                                    image_files.append({
                                        'path': entry.path,
                                        'name': entry.name,
                                        'create_time': create_time,
                                        'shot_time': create_time,
                                        'size': stat.st_size,
                                        'width': width,
                                        'height': height,
                                        'has_exif': False,
                                    })
            except Exception as e:
                try:
                    last_err = str(e)
                except Exception:
                    last_err = "scan_error"
                image_files = []
            if request_id != self._folder_load_request_id:
                return
            if not image_files:
                try:
                    from utils.log_manager import LogManager

                    LogManager.instance().debug(
                        f"[Import] scan empty folder={folder_path} recursive={bool(recursive)} exts={len(valid_extensions)} err={last_err}"
                    )
                except Exception:
                    pass

            self.scanResultsReady.emit(request_id, image_files)

        Thread(target=run_scan, daemon=True, name=f"ImportFolderScan-{request_id}").start()

    def _apply_scan_results(self, request_id, image_files):
        """应用文件夹扫描结果
        参数:
            request_id: 请求标识
            image_files: 扫描得到的图片信息列表
        """
        if request_id != self._folder_load_request_id:
            return
        try:
            self._all_image_files = list(image_files or [])
        except Exception:
            self._all_image_files = []
        files = self._filter_files_for_display(self._all_image_files)
        self._apply_files_view(request_id, files)
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                cur = str(getattr(self, "_current_folder_path", "") or "")
                if cur.startswith("virtual://focus_detect?"):
                    folder, _, sub = self._parse_focus_detect_virtual_path(cur)
                    if folder:
                        QTimer.singleShot(
                            0,
                            lambda f=str(folder), s=str(sub or ""): self._update_focus_detect_virtual_folder_counts(
                                f, getattr(self, "_all_image_files", []) or [], sub=s
                            ),
                        )
                    QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
                    QTimer.singleShot(0, self._refresh_current_preview_overlays_from_import_cache)
        except Exception:
            pass

    def _apply_files_view(self, request_id: int, image_files):
        try:
            stashed = self._get_stash_set_for_current_folder()
        except Exception:
            stashed = set()
        self._requested_exif_paths = set()
        try:
            self._requested_paths = set()
        except Exception:
            pass
        self.image_files = []
        for it in (image_files or []):
            if not isinstance(it, dict):
                continue
            info = it.copy()
            p = info.get("path")
            if p:
                info["is_stashed"] = self._normalize_path_key(p) in stashed
                try:
                    if bool(getattr(self, "is_virtual_mode", False)):
                        try:
                            auto_enabled = bool(self.settings_manager.get("import/virtual_auto_label", True))
                        except Exception:
                            auto_enabled = True
                        if auto_enabled:
                            info["auto_label"] = self._auto_label_for_focus_status(info.get("focus_status"))
                        else:
                            info.pop("auto_label", None)
                    else:
                        info.pop("auto_label", None)
                except Exception:
                    pass
            self.image_files.append(info)
        try:
            if bool(getattr(self, "is_virtual_mode", False)) and self.image_files:
                self._schedule_focus_point_backfill(self.image_files)
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)) and self.image_files:
                cur = str(getattr(self, "_current_folder_path", "") or "")
                if cur.startswith("virtual://focus_detect?") or cur.startswith("virtual://focus_detect_burst?"):
                    QTimer.singleShot(0, lambda: self._start_import_cache_bulk_backfill(interval_ms=30, batch_size=200))
        except Exception:
            pass
        if not self.image_files:
            self.grid_view.clear_thumbnails()
            self._thumb_by_path.clear()
            self.loaded_count = 0
            self.selected_count = 0
            self._loaded_paths = set()
            if self.has_valid_folder:
                self.stats_changed.emit(0, 0, 0)
            self._startup_pending_paths = set()
            self._startup_first_page_ready = True
            self._force_hide_startup_mask()
            return

        self._startup_initial_load_processed = False
        self._startup_first_page_ready = False
        try:
            self._sort_image_files_in_place()
        except Exception:
            try:
                self.image_files.sort(key=lambda x: x['name'].lower())
            except Exception:
                pass
        self.loaded_count = 0
        self.selected_count = 0
        self._loaded_paths = set()
        if self.has_valid_folder:
            self.stats_changed.emit(len(self.image_files), self.loaded_count, self.selected_count)
        self.grid_view.clear_thumbnails()
        self._thumb_by_path.clear()
        self._thumb_build_request_id = request_id
        self._thumb_build_pending_files = self.image_files
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                self._virtual_overlay_backfill_rid = -1
        except Exception:
            pass
        
        self._startup_pending_paths = set()
        
        self._thumb_build_index = 0
        self._thumb_build_target_count = 0
        total_count = len(self._thumb_build_pending_files)
        if total_count > 0:
            try:
                available_width = self.grid_view.get_available_width()
            except Exception:
                available_width = 800
            thumb_size = self.grid_view.current_thumb_size
            if isinstance(thumb_size, (tuple, list)):
                thumb_w = int(thumb_size[0])
                thumb_h = int(thumb_size[1])
            else:
                thumb_w = int(thumb_size)
                thumb_h = int(thumb_size)
            cols = max(1, int(available_width // max(1, thumb_w)))
            try:
                viewport_h = int(self.grid_view.scroll_area.viewport().height())
            except Exception:
                viewport_h = 600
            rows = max(1, int(viewport_h // max(1, thumb_h)))
            initial_rows = max(1, rows + 1)
            initial_count = min(total_count, cols * initial_rows)
            self._thumb_build_target_count = initial_count
            self._full_build_total_count = total_count
            self._full_build_deferred = total_count > initial_count
        if self._thumb_build_timer.isActive():
            self._thumb_build_timer.stop()
        self._thumb_build_timer.start(0)

        self._cache_warmup_request_id = request_id
        self._cache_warmup_index = 0
        self._cache_warmup_paths = [img.get("path") for img in self.image_files if img.get("path")]
        if self._cache_warmup_timer.isActive():
            self._cache_warmup_timer.stop()
        self._cache_warmup_deferred = bool(self._full_build_deferred)
        if self._cache_warmup_paths and not self._cache_warmup_deferred:
            self._cache_warmup_timer.start()
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                QTimer.singleShot(0, self._refresh_current_preview_overlays_from_import_cache)
                QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
        except Exception:
            pass

    def _schedule_focus_point_backfill(self, file_list):
        try:
            from utils.worker.focus_point_backfill import FocusPointBackfillService
        except Exception:
            return
        try:
            bridge = getattr(self, "_focus_point_backfill_bridge", None)
        except Exception:
            bridge = None
        if bridge is None:
            try:
                class _FocusPointBackfillBridge(QObject):
                    updated = pyqtSignal(object)

                bridge = _FocusPointBackfillBridge()
                bridge.updated.connect(lambda u: self._apply_exif_updates(u))
                self._focus_point_backfill_bridge = bridge
            except Exception:
                bridge = None
        paths = []
        try:
            for it in (file_list or [])[:800]:
                if not isinstance(it, dict):
                    continue
                fp = it.get("focus_point")
                if not bool(self._is_missing_focus_point_value(fp)):
                    continue
                p = it.get("path")
                if p:
                    paths.append(str(p))
        except Exception:
            paths = []
        if not paths:
            return
        try:
            FocusPointBackfillService.instance().submit(
                paths,
                table_name="import_cache",
                callback=(lambda updates: bridge.updated.emit(updates)) if bridge is not None else None,
            )
        except Exception:
            pass

    def _normalize_folder_key(self, folder_path: str) -> str:
        if not folder_path:
            return ""
        try:
            p = str(folder_path).replace("/", os.sep)
            p = os.path.normpath(p)
            if os.name == "nt":
                p = os.path.normcase(p)
            return p
        except Exception:
            try:
                return str(folder_path)
            except Exception:
                return ""

    def _parse_focus_detect_virtual_path(self, path: str) -> tuple[str, str, str]:
        try:
            if not isinstance(path, str):
                return "", "All", ""
            if not path.startswith("virtual://focus_detect?"):
                return "", "All", ""
            import urllib.parse

            q = urllib.parse.urlparse(path)
            qs = urllib.parse.parse_qs(q.query)
            folder = (qs.get("folder") or [""])[0]
            status = (qs.get("status") or ["All"])[0]
            sub = (qs.get("sub") or [""])[0]
            try:
                folder = urllib.parse.unquote(str(folder or ""))
            except Exception:
                folder = str(folder or "")
            try:
                status = urllib.parse.unquote(str(status or "All"))
            except Exception:
                status = str(status or "All")
            try:
                sub = urllib.parse.unquote(str(sub or ""))
            except Exception:
                sub = str(sub or "")
            if not status:
                status = "All"
            return folder, status, sub
        except Exception:
            return "", "All", ""

    def _parse_focus_detect_burst_virtual_path(self, path: str) -> tuple[str, str, str]:
        try:
            if not isinstance(path, str):
                return "", "", "All"
            if not path.startswith("virtual://focus_detect_burst?"):
                return "", "", "All"
            import urllib.parse

            q = urllib.parse.urlparse(path)
            qs = urllib.parse.parse_qs(q.query)
            folder = (qs.get("folder") or [""])[0]
            first_name = (qs.get("first") or [""])[0]
            status = (qs.get("status") or ["All"])[0]
            try:
                folder = urllib.parse.unquote(str(folder or ""))
            except Exception:
                folder = str(folder or "")
            try:
                first_name = urllib.parse.unquote(str(first_name or ""))
            except Exception:
                first_name = str(first_name or "")
            try:
                status = urllib.parse.unquote(str(status or "All"))
            except Exception:
                status = str(status or "All")
            if not status:
                status = "All"
            return folder, first_name, status
        except Exception:
            return "", "", "All"

    def _vdbg_enabled(self) -> bool:
        try:
            if hasattr(self, "settings_manager") and self.settings_manager is not None:
                return bool(self.settings_manager.get("debug/import_virtual_exif", getattr(self, "_debug_import_virtual_exif", True)))
        except Exception:
            pass
        return bool(getattr(self, "_debug_import_virtual_exif", True))

    def _vdbg_log(self, msg: str):
        if not self._vdbg_enabled():
            return
        try:
            from utils.log_manager import LogManager

            LogManager.instance().debug(f"[ImportVirtualEXIF] {msg}")
        except Exception:
            pass

    def _schedule_preview(self, path: str):
        if not path:
            return
        try:
            self._pending_preview_path = str(path)
            if self._preview_debounce_timer.isActive():
                self._preview_debounce_timer.stop()
            self._preview_debounce_timer.start()
        except Exception:
            try:
                self.preview_image_file(path)
            except Exception:
                pass

    def _apply_pending_preview(self):
        p = getattr(self, "_pending_preview_path", None)
        if not p:
            return
        try:
            self._pending_preview_path = None
        except Exception:
            pass
        try:
            self.preview_image_file(p)
        except Exception:
            pass

    def _schedule_detail_nav(self, index: int, modifiers):
        try:
            if not (hasattr(self, "detail_panel") and self.detail_panel):
                return
        except Exception:
            return
        try:
            self._pending_detail_nav = (int(index), modifiers)
            if self._detail_debounce_timer.isActive():
                self._detail_debounce_timer.stop()
            self._detail_debounce_timer.start()
        except Exception:
            pass

    def _apply_pending_detail_nav(self):
        nav = getattr(self, "_pending_detail_nav", None)
        if not nav:
            return
        try:
            self._pending_detail_nav = None
        except Exception:
            pass
        try:
            idx, modifiers = nav
        except Exception:
            return
        try:
            if hasattr(self, "detail_panel") and self.detail_panel:
                self.detail_panel.on_thumbnail_clicked_proxy(int(idx), modifiers)
        except Exception:
            pass

    def _schedule_big_preload(self, start_idx: int, end_idx: int):
        try:
            if not bool(getattr(self, "is_virtual_mode", False)):
                return
        except Exception:
            return
        try:
            if int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) == ImageThumbnail.MODE_THUMBNAIL_ONLY:
                return
        except Exception:
            pass
        try:
            enabled = bool(self.settings_manager.get("performance/preload_visible_big_images", True))
        except Exception:
            enabled = True
        if not enabled:
            return
        try:
            self._pending_big_preload_range = (int(start_idx), int(end_idx))
            if self._big_preload_timer.isActive():
                self._big_preload_timer.stop()
            self._big_preload_timer.start()
        except Exception:
            pass

    def _apply_pending_big_preload(self):
        rng = getattr(self, "_pending_big_preload_range", None)
        if not rng:
            return
        try:
            self._pending_big_preload_range = None
        except Exception:
            pass
        try:
            start_idx, end_idx = int(rng[0]), int(rng[1])
        except Exception:
            return
        if start_idx < 0 or end_idx < start_idx:
            return
        paths = []
        try:
            is_big_mode = int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) == ImageThumbnail.MODE_THUMBNAIL_ONLY
        except Exception:
            is_big_mode = False
        if is_big_mode:
            try:
                self.big_image_cache.set_max_items_override(10)
            except Exception:
                pass
        limit = 10 if is_big_mode else 80
        for idx in range(start_idx, min(end_idx + 1, len(self.image_files))):
            if len(paths) >= limit:
                break
            it = self.image_files[idx]
            if not isinstance(it, dict):
                continue
            p = it.get("path")
            if p:
                paths.append(p)
        if paths:
            try:
                self.big_image_cache.preload(paths)
            except Exception:
                pass

    def _read_exif_basic_exifread(self, image_path: str) -> dict:
        try:
            import exifread
        except Exception:
            return {}
        if not image_path:
            return {}
        try:
            with open(image_path, "rb") as f:
                tags = exifread.process_file(f, details=False) or {}
        except Exception:
            return {}
        if not isinstance(tags, dict) or not tags:
            return {}

        def _ratio_to_float(v):
            try:
                if hasattr(v, "num") and hasattr(v, "den"):
                    den = float(v.den) if float(v.den) != 0 else 0.0
                    return float(v.num) / den if den else None
            except Exception:
                pass
            try:
                s = str(v)
                if "/" in s:
                    a, b = s.split("/", 1)
                    a = float(a.strip())
                    b = float(b.strip())
                    return a / b if b else None
                return float(s)
            except Exception:
                return None

        def _tag_first_value(tag_obj):
            if tag_obj is None:
                return None
            try:
                vals = getattr(tag_obj, "values", None)
                if isinstance(vals, (list, tuple)) and vals:
                    return vals[0]
            except Exception:
                pass
            try:
                return getattr(tag_obj, "value", None)
            except Exception:
                return None

        def _tag_str(tag_obj):
            if tag_obj is None:
                return ""
            try:
                s = str(tag_obj)
            except Exception:
                s = ""
            return s.strip()

        iso = None
        iso_tag = tags.get("EXIF ISOSpeedRatings") or tags.get("EXIF PhotographicSensitivity") or tags.get("EXIF ISO")
        iso_val = _tag_first_value(iso_tag)
        if iso_val is None:
            try:
                iso_val = int(_tag_str(iso_tag) or 0)
            except Exception:
                iso_val = None
        try:
            if iso_val is not None:
                iso = int(iso_val)
        except Exception:
            try:
                iso = int(float(str(iso_val)))
            except Exception:
                iso = None

        fnumber = None
        fn_tag = tags.get("EXIF FNumber") or tags.get("EXIF ApertureValue")
        fn_val = _tag_first_value(fn_tag)
        fn_f = _ratio_to_float(fn_val)
        try:
            if fn_f is not None and fn_f > 0:
                fnumber = round(float(fn_f), 1)
        except Exception:
            fnumber = None

        shutter = ""
        exp_tag = tags.get("EXIF ExposureTime")
        if exp_tag is not None:
            exp_val = _tag_first_value(exp_tag)
            try:
                s = str(exp_val).strip()
            except Exception:
                s = ""
            if s:
                shutter = s if s.endswith("s") else (s + "s")
        if not shutter:
            shutter = _tag_str(tags.get("EXIF ShutterSpeedValue"))

        focal_length = ""
        fl_tag = tags.get("EXIF FocalLength") or tags.get("EXIF FocalLengthIn35mmFilm")
        fl_val = _tag_first_value(fl_tag)
        fl_f = _ratio_to_float(fl_val)
        try:
            if fl_f is not None and fl_f > 0:
                focal_length = f"{round(float(fl_f), 0):.0f}mm"
        except Exception:
            focal_length = ""
        if not focal_length:
            fl_s = _tag_str(fl_tag)
            if fl_s:
                focal_length = fl_s if fl_s.lower().endswith("mm") else (fl_s + "mm")

        shot_time = ""
        dt_tag = tags.get("EXIF DateTimeOriginal") or tags.get("EXIF CreateDate") or tags.get("Image DateTime")
        dt_s = _tag_str(dt_tag)
        if dt_s:
            try:
                if len(dt_s) >= 19 and dt_s[4] == ":" and dt_s[7] == ":":
                    shot_time = dt_s[:10].replace(":", "-") + dt_s[10:]
                else:
                    shot_time = dt_s
            except Exception:
                shot_time = dt_s

        has_exif = any(x not in (None, "", 0, 0.0) for x in (iso, fnumber, shutter, focal_length))
        if not has_exif:
            return {}
        out = {"has_exif": True}
        if iso is not None:
            out["iso"] = iso
        if fnumber is not None:
            out["fnumber"] = fnumber
        if shutter:
            out["shutter"] = shutter
        if focal_length:
            out["focal_length"] = focal_length
        if shot_time:
            out["shot_time"] = shot_time
        return out

    def _get_current_folder_key(self) -> str:
        try:
            folder = str(getattr(self, "_current_folder_path", "") or "") or str(self.settings_manager.get("import/last_folder", "") or "")
        except Exception:
            folder = ""
        try:
            if isinstance(folder, str) and folder.startswith("virtual://focus_detect?"):
                real_folder, _, _ = self._parse_focus_detect_virtual_path(folder)
                if real_folder:
                    folder = str(real_folder)
        except Exception:
            pass
        return self._normalize_folder_key(folder)

    def _get_stash_set_for_current_folder(self) -> set:
        folder_key = self._get_current_folder_key()
        if not folder_key:
            return set()
        try:
            s = self._stash_by_folder.get(folder_key)
            return set(s) if s else set()
        except Exception:
            return set()

    def _get_focus_detect_ui_thresholds(self) -> dict:
        out = {}
        try:
            out["sharp_threshold"] = int(self.settings_manager.get("focus_detect_ui/sharp_threshold", 60) or 60)
        except Exception:
            out["sharp_threshold"] = 60
        try:
            out["norm_sharp_threshold"] = int(self.settings_manager.get("focus_detect_ui/norm_sharp_threshold", 110) or 110)
        except Exception:
            out["norm_sharp_threshold"] = 110
        try:
            out["normal_contrast_threshold"] = float(self.settings_manager.get("focus_detect_ui/normal_contrast_threshold", 0.8) or 0.8)
        except Exception:
            out["normal_contrast_threshold"] = 0.8
        try:
            out["conf_threshold"] = float(self.settings_manager.get("focus_detect_ui/conf_threshold", 0.1) or 0.1)
        except Exception:
            out["conf_threshold"] = 0.1
        try:
            out["minimal_area_threshold"] = float(self.settings_manager.get("focus_detect_ui/minimal_area_threshold", 0.001) or 0.001)
        except Exception:
            out["minimal_area_threshold"] = 0.001
        try:
            out["hf_ratio_threshold"] = float(self.settings_manager.get("focus_detect_ui/hf_ratio_threshold", 1.15) or 1.15)
        except Exception:
            out["hf_ratio_threshold"] = 1.15
        try:
            out["hf_margin_threshold"] = float(self.settings_manager.get("focus_detect_ui/hf_margin_threshold", 5.0) or 5.0)
        except Exception:
            out["hf_margin_threshold"] = 5.0
        try:
            out["texture_ratio_threshold"] = float(self.settings_manager.get("focus_detect_ui/texture_ratio_threshold", 1.1) or 1.1)
        except Exception:
            out["texture_ratio_threshold"] = 1.1
        try:
            out["texture_weight"] = float(self.settings_manager.get("focus_detect_ui/texture_weight", 0.0) or 0.0)
        except Exception:
            out["texture_weight"] = 0.0
        try:
            out["focus_point_in_bird_sharp"] = bool(self.settings_manager.get("focus_detect_ui/focus_point_in_bird_sharp", True))
        except Exception:
            out["focus_point_in_bird_sharp"] = True
        return out

    def _create_focus_threshold_panel(self):
        try:
            from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QSlider, QWidget, QPushButton, QCheckBox
            from PyQt6.QtCore import Qt
        except Exception:
            return QWidget()

        cm = ColorManager.instance()
        bg = cm.get("theme.background.primary", "#FFFFFF")
        border = cm.get("popup.border.primary", "#D0D0D0")
        text = cm.get("theme.text.dark", "#333333")
        slider_groove = cm.get("theme.background.dark", "#E0E0E0")
        slider_handle = cm.get("theme.primary", "#2196F3")

        panel = QFrame()
        try:
            panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        except Exception:
            pass
        try:
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        try:
            panel.setObjectName("focusThresholdPanel")
        except Exception:
            pass
        panel.setStyleSheet(
            "\n".join(
                [
                    f"QFrame#focusThresholdPanel {{ background-color: {bg}; border-bottom: 1px solid {border}; }}",
                    "QFrame#focusThresholdPanel QWidget { background: transparent; border: none; }",
                    "QFrame#focusThresholdPanel QSlider { background: transparent; }",
                    f"QFrame#focusThresholdPanel QCheckBox {{ background: transparent; border: none; color: {text}; }}",
                ]
            )
        )
        panel.setFixedHeight(76)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(14)

        slider_style = f"""
            QSlider {{
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 6px;
                background: {slider_groove};
                margin: 10px 0;
            }}
            QSlider::handle:horizontal {{
                width: 12px;
                height: 18px;
                background: {slider_handle};
                border-radius: 2px;
                margin: -6px 0;
            }}
            QSlider::sub-page:horizontal {{
                background: {slider_handle};
                height: 6px;
                margin: 10px 0;
            }}
            QSlider::add-page:horizontal {{
                background: {slider_groove};
                height: 6px;
                margin: 10px 0;
            }}
        """

        def add_slider(title: str, *, key: str, min_v: int, max_v: int, init_v: int, fmt, on_set):
            w = QWidget()
            try:
                from PyQt6.QtWidgets import QSizePolicy
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                w.setMinimumWidth(0)
            except Exception:
                pass
            try:
                w.setStyleSheet("background: transparent; border: none;")
            except Exception:
                pass
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            title_label = QLabel(title)
            title_label.setStyleSheet(f"color: {text}; font-size: 12px; border: none; background: transparent;")
            value_label = QLabel("")
            value_label.setStyleSheet(f"color: {text}; font-size: 12px; border: none; background: transparent;")
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(title_label)
            row.addStretch(1)
            row.addWidget(value_label)
            v.addLayout(row)

            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(int(min_v), int(max_v))
            s.setValue(int(init_v))
            s.setStyleSheet(slider_style)
            v.addWidget(s)

            def _sync_label(val: int):
                try:
                    value_label.setText(str(fmt(int(val))))
                except Exception:
                    value_label.setText(str(val))

            _sync_label(int(init_v))
            try:
                setattr(s, "_sync_label_func", _sync_label)
            except Exception:
                pass

            def _changed(val: int):
                _sync_label(int(val))
                try:
                    if self._focus_threshold_debounce_timer.isActive():
                        self._focus_threshold_debounce_timer.stop()
                except Exception:
                    pass
                try:
                    self._focus_threshold_debounce_timer.start()
                except Exception:
                    pass

            s.valueChanged.connect(_changed)
            try:
                s.sliderReleased.connect(self._apply_focus_thresholds_change)
            except Exception:
                pass
            on_set(s)
            layout.addWidget(w, 1)

        try:
            init_sharp = int(self.settings_manager.get("focus_detect_ui/sharp_threshold", 60) or 60)
        except Exception:
            init_sharp = 60
        try:
            init_norm = int(self.settings_manager.get("focus_detect_ui/norm_sharp_threshold", 110) or 110)
        except Exception:
            init_norm = 110
        try:
            init_normal_ratio = float(self.settings_manager.get("focus_detect_ui/normal_contrast_threshold", 0.8) or 0.8)
        except Exception:
            init_normal_ratio = 0.8
        try:
            init_conf = float(self.settings_manager.get("focus_detect_ui/conf_threshold", 0.1) or 0.1)
        except Exception:
            init_conf = 0.1
        try:
            init_min_area = float(self.settings_manager.get("focus_detect_ui/minimal_area_threshold", 0.001) or 0.001)
        except Exception:
            init_min_area = 0.001
        try:
            init_hf_ratio = float(self.settings_manager.get("focus_detect_ui/hf_ratio_threshold", 1.15) or 1.15)
        except Exception:
            init_hf_ratio = 1.15
        try:
            init_hf_margin = float(self.settings_manager.get("focus_detect_ui/hf_margin_threshold", 5.0) or 5.0)
        except Exception:
            init_hf_margin = 5.0
        try:
            init_tex_ratio = float(self.settings_manager.get("focus_detect_ui/texture_ratio_threshold", 1.1) or 1.1)
        except Exception:
            init_tex_ratio = 1.1
        try:
            init_tex_weight = float(self.settings_manager.get("focus_detect_ui/texture_weight", 0.0) or 0.0)
        except Exception:
            init_tex_weight = 0.0
        try:
            init_fp_in_bird_sharp = bool(self.settings_manager.get("focus_detect_ui/focus_point_in_bird_sharp", True))
        except Exception:
            init_fp_in_bird_sharp = True

        add_slider(
            "锐度阈值",
            key="focus_detect_ui/sharp_threshold",
            min_v=0,
            max_v=1000,
            init_v=max(0, min(1000, int(init_sharp))),
            fmt=lambda x: x,
            on_set=lambda s: setattr(self, "_focus_slider_sharp", s),
        )
        add_slider(
            "归一化阈值",
            key="focus_detect_ui/norm_sharp_threshold",
            min_v=0,
            max_v=500,
            init_v=max(0, min(500, int(init_norm))),
            fmt=lambda x: x,
            on_set=lambda s: setattr(self, "_focus_slider_norm_sharp", s),
        )
        add_slider(
            "普通阈值",
            key="focus_detect_ui/normal_contrast_threshold",
            min_v=0,
            max_v=300,
            init_v=max(0, min(300, int(round(float(init_normal_ratio) * 100.0)))),
            fmt=lambda x: f"{x/100.0:.2f}",
            on_set=lambda s: setattr(self, "_focus_slider_normal_ratio", s),
        )
        add_slider(
            "置信度阈值",
            key="focus_detect_ui/conf_threshold",
            min_v=0,
            max_v=100,
            init_v=max(0, min(100, int(round(float(init_conf) * 100.0)))),
            fmt=lambda x: f"{x/100.0:.2f}",
            on_set=lambda s: setattr(self, "_focus_slider_conf", s),
        )
        add_slider(
            "极小占比",
            key="focus_detect_ui/minimal_area_threshold",
            min_v=0,
            max_v=300,
            init_v=max(0, min(300, int(round(float(init_min_area) * 100000.0)))),
            fmt=lambda x: f"{x/100000.0:.5f}",
            on_set=lambda s: setattr(self, "_focus_slider_min_area", s),
        )
        add_slider(
            "高频比例",
            key="focus_detect_ui/hf_ratio_threshold",
            min_v=0,
            max_v=300,
            init_v=max(0, min(300, int(round(float(init_hf_ratio) * 100.0)))),
            fmt=lambda x: f"{x/100.0:.2f}",
            on_set=lambda s: setattr(self, "_focus_slider_hf_ratio", s),
        )
        add_slider(
            "高频差值",
            key="focus_detect_ui/hf_margin_threshold",
            min_v=0,
            max_v=200,
            init_v=max(0, min(200, int(round(float(init_hf_margin))))),
            fmt=lambda x: f"{x:.0f}",
            on_set=lambda s: setattr(self, "_focus_slider_hf_margin", s),
        )
        add_slider(
            "纹理比例",
            key="focus_detect_ui/texture_ratio_threshold",
            min_v=0,
            max_v=300,
            init_v=max(0, min(300, int(round(float(init_tex_ratio) * 100.0)))),
            fmt=lambda x: f"{x/100.0:.2f}",
            on_set=lambda s: setattr(self, "_focus_slider_tex_ratio", s),
        )
        add_slider(
            "纹理权重",
            key="focus_detect_ui/texture_weight",
            min_v=0,
            max_v=100,
            init_v=max(0, min(100, int(round(float(init_tex_weight) * 100.0)))),
            fmt=lambda x: f"{x/100.0:.2f}",
            on_set=lambda s: setattr(self, "_focus_slider_tex_weight", s),
        )

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        try:
            right.setStyleSheet("background: transparent; border: none;")
        except Exception:
            pass

        fp_cb = QCheckBox("对焦点在鸟上时默认锐利")
        fp_cb.setChecked(bool(init_fp_in_bird_sharp))
        fp_cb.setStyleSheet(f"QCheckBox {{ color: {text}; font-size: 12px; padding-left: 4px; }}")
        try:
            fp_cb.toggled.connect(self._on_focus_point_in_bird_sharp_toggled)
        except Exception:
            pass
        self._focus_cb_fp_in_bird_sharp = fp_cb
        right_layout.addWidget(fp_cb, 0, Qt.AlignmentFlag.AlignRight)
        right_layout.addStretch(1)

        reset_btn = QPushButton("恢复默认")
        reset_btn.setFixedHeight(28)
        reset_bg0 = cm.get("theme.background.secondary", "#F6F7FA")
        reset_bg1 = cm.get("theme.background.primary", "#FFFFFF")
        reset_border = cm.get("popup.border.primary", "#D0D0D0")
        reset_hover = cm.get("theme.background.dark", "#EAECEF")
        reset_pressed = cm.get("theme.background.darkest", "#DDE1E6")
        reset_primary = cm.get("theme.primary", "#2196F3")
        reset_btn.setStyleSheet(
            f"""
            QPushButton {{
                color: {text};
                font-size: 12px;
                font-weight: 600;
                padding: 4px 12px;
                border-radius: 8px;
                border: 1px solid {reset_border};
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {reset_bg1}, stop:1 {reset_bg0});
            }}
            QPushButton:hover {{
                border: 1px solid {reset_primary};
                background: {reset_hover};
            }}
            QPushButton:pressed {{
                background: {reset_pressed};
            }}
            """
        )
        try:
            reset_btn.clicked.connect(self._reset_focus_thresholds_to_default)
        except Exception:
            pass
        right_layout.addWidget(reset_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(right, 0)
        panel.hide()
        return panel

    def _update_focus_threshold_panel_visibility(self):
        try:
            panel = getattr(self, "_focus_threshold_panel", None)
            btn = getattr(self, "focus_threshold_btn", None)
            if panel is None:
                if btn is not None:
                    btn.hide()
                return
            is_virtual = bool(getattr(self, "is_virtual_mode", False))
            p0 = str(getattr(self, "_current_folder_path", "") or "")
            in_focus_virtual = bool(
                is_virtual
                and isinstance(p0, str)
                and (p0.startswith("virtual://focus_detect?") or p0.startswith("virtual://focus_detect_burst?"))
            )
            if btn is not None:
                btn.setVisible(bool(in_focus_virtual))

            if not in_focus_virtual:
                try:
                    self._focus_threshold_panel_open = False
                except Exception:
                    pass
                panel.hide()
                return

            try:
                open0 = bool(getattr(self, "_focus_threshold_panel_open", False))
            except Exception:
                open0 = False
            if open0:
                panel.show()
                self._reposition_focus_threshold_panel()
            else:
                panel.hide()
        except Exception:
            pass

    def _apply_focus_thresholds_change(self):
        try:
            sharp = int(getattr(self, "_focus_slider_sharp", None).value()) if getattr(self, "_focus_slider_sharp", None) is not None else None
        except Exception:
            sharp = None
        try:
            norm = int(getattr(self, "_focus_slider_norm_sharp", None).value()) if getattr(self, "_focus_slider_norm_sharp", None) is not None else None
        except Exception:
            norm = None
        try:
            normal_ratio = float(int(getattr(self, "_focus_slider_normal_ratio", None).value())) / 100.0 if getattr(self, "_focus_slider_normal_ratio", None) is not None else None
        except Exception:
            normal_ratio = None
        try:
            conf = float(int(getattr(self, "_focus_slider_conf", None).value())) / 100.0 if getattr(self, "_focus_slider_conf", None) is not None else None
        except Exception:
            conf = None
        try:
            min_area = float(int(getattr(self, "_focus_slider_min_area", None).value())) / 100000.0 if getattr(self, "_focus_slider_min_area", None) is not None else None
        except Exception:
            min_area = None
        try:
            hf_ratio = float(int(getattr(self, "_focus_slider_hf_ratio", None).value())) / 100.0 if getattr(self, "_focus_slider_hf_ratio", None) is not None else None
        except Exception:
            hf_ratio = None
        try:
            hf_margin = float(int(getattr(self, "_focus_slider_hf_margin", None).value())) if getattr(self, "_focus_slider_hf_margin", None) is not None else None
        except Exception:
            hf_margin = None
        try:
            tex_ratio = float(int(getattr(self, "_focus_slider_tex_ratio", None).value())) / 100.0 if getattr(self, "_focus_slider_tex_ratio", None) is not None else None
        except Exception:
            tex_ratio = None
        try:
            tex_weight = float(int(getattr(self, "_focus_slider_tex_weight", None).value())) / 100.0 if getattr(self, "_focus_slider_tex_weight", None) is not None else None
        except Exception:
            tex_weight = None
        try:
            fp_in_bird_sharp = bool(getattr(self, "_focus_cb_fp_in_bird_sharp", None).isChecked()) if getattr(self, "_focus_cb_fp_in_bird_sharp", None) is not None else None
        except Exception:
            fp_in_bird_sharp = None

        try:
            if sharp is not None:
                self.settings_manager.set("focus_detect_ui/sharp_threshold", int(sharp))
            if norm is not None:
                self.settings_manager.set("focus_detect_ui/norm_sharp_threshold", int(norm))
            if normal_ratio is not None:
                self.settings_manager.set("focus_detect_ui/normal_contrast_threshold", float(normal_ratio))
            if conf is not None:
                self.settings_manager.set("focus_detect_ui/conf_threshold", float(conf))
            if min_area is not None:
                self.settings_manager.set("focus_detect_ui/minimal_area_threshold", float(min_area))
            if hf_ratio is not None:
                self.settings_manager.set("focus_detect_ui/hf_ratio_threshold", float(hf_ratio))
            if hf_margin is not None:
                self.settings_manager.set("focus_detect_ui/hf_margin_threshold", float(hf_margin))
            if tex_ratio is not None:
                self.settings_manager.set("focus_detect_ui/texture_ratio_threshold", float(tex_ratio))
            if tex_weight is not None:
                self.settings_manager.set("focus_detect_ui/texture_weight", float(tex_weight))
            if fp_in_bird_sharp is not None:
                self.settings_manager.set("focus_detect_ui/focus_point_in_bird_sharp", bool(fp_in_bird_sharp))
            self.settings_manager.sync()
        except Exception:
            pass

        try:
            if not bool(getattr(self, "is_virtual_mode", False)):
                return
            p0 = str(getattr(self, "_current_folder_path", "") or "")
            if not (
                isinstance(p0, str)
                and (p0.startswith("virtual://focus_detect?") or p0.startswith("virtual://focus_detect_burst?"))
            ):
                return
        except Exception:
            return
        try:
            folder = ""
            sub_sel = ""
            burst_first = ""
            burst_status = "All"
            if str(p0).startswith("virtual://focus_detect?"):
                folder, _, sub_sel = self._parse_focus_detect_virtual_path(p0)
            elif str(p0).startswith("virtual://focus_detect_burst?"):
                folder, burst_first, burst_status = self._parse_focus_detect_burst_virtual_path(p0)
        except Exception:
            folder = ""
            sub_sel = ""
            burst_first = ""
            burst_status = "All"
        thresholds = {}
        try:
            thresholds = self._get_focus_detect_ui_thresholds()
        except Exception:
            thresholds = {}

        changed = False
        try:
            for it in (getattr(self, "_all_image_files", []) or []):
                if not isinstance(it, dict):
                    continue
                old = str(it.get("focus_status") or "")
                try:
                    new = str(self._compute_focus_status_for_item(it, thresholds))
                except Exception:
                    new = "NoBird"
                if not old or old != new:
                    changed = True
                it["focus_status"] = new
        except Exception:
            changed = True

        if not changed:
            try:
                changed = True
            except Exception:
                pass

        try:
            if folder and str(p0).startswith("virtual://focus_detect?"):
                self._update_focus_detect_virtual_folder_counts(folder, getattr(self, "_all_image_files", []) or [], sub=str(sub_sel or ""))
            if folder and str(p0).startswith("virtual://focus_detect_burst?") and burst_first:
                self._update_focus_detect_burst_virtual_group_counts(folder, burst_first, getattr(self, "_all_image_files", []) or [])
        except Exception:
            pass

        try:
            files = None
            if str(p0).startswith("virtual://focus_detect?"):
                files = self._filter_files_for_display(getattr(self, "_all_image_files", []) or [])
            elif str(p0).startswith("virtual://focus_detect_burst?"):
                files0 = list(getattr(self, "_all_image_files", []) or [])
                st_sel = str(burst_status or "All") or "All"
                if st_sel != "All":
                    files0 = [it for it in files0 if isinstance(it, dict) and str(it.get("focus_status") or "") == st_sel]
                files = files0
            else:
                files = list(getattr(self, "_all_image_files", []) or [])
            self._apply_files_view(getattr(self, "_folder_load_request_id", 0), files)
        except Exception:
            pass

    def _reset_focus_thresholds_to_default(self):
        defaults = {
            "sharp_threshold": 60,
            "norm_sharp_threshold": 110,
            "normal_contrast_threshold": 0.8,
            "conf_threshold": 0.1,
            "minimal_area_threshold": 0.001,
            "hf_ratio_threshold": 1.15,
            "hf_margin_threshold": 5.0,
            "texture_ratio_threshold": 1.1,
            "texture_weight": 0.0,
            "focus_point_in_bird_sharp": True,
        }
        try:
            self.settings_manager.set("focus_detect_ui/focus_point_in_bird_sharp", bool(defaults["focus_point_in_bird_sharp"]))
            self.settings_manager.sync()
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_sharp", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(defaults["sharp_threshold"]))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_norm_sharp", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(defaults["norm_sharp_threshold"]))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_normal_ratio", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(round(float(defaults["normal_contrast_threshold"]) * 100.0)))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_conf", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(round(float(defaults["conf_threshold"]) * 100.0)))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_min_area", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(round(float(defaults["minimal_area_threshold"]) * 100000.0)))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_hf_ratio", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(round(float(defaults["hf_ratio_threshold"]) * 100.0)))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_hf_margin", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(round(float(defaults["hf_margin_threshold"]))))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_tex_ratio", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(round(float(defaults["texture_ratio_threshold"]) * 100.0)))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            s = getattr(self, "_focus_slider_tex_weight", None)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(round(float(defaults["texture_weight"]) * 100.0)))
                try:
                    getattr(s, "_sync_label_func", None) and s._sync_label_func(int(s.value()))
                except Exception:
                    pass
                s.blockSignals(False)
        except Exception:
            pass
        try:
            cb = getattr(self, "_focus_cb_fp_in_bird_sharp", None)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(bool(defaults["focus_point_in_bird_sharp"]))
                cb.blockSignals(False)
        except Exception:
            pass
        self._apply_focus_thresholds_change()

    def _on_focus_point_in_bird_sharp_toggled(self, checked: bool):
        try:
            self.settings_manager.set("focus_detect_ui/focus_point_in_bird_sharp", bool(checked))
            self.settings_manager.sync()
        except Exception:
            pass
        try:
            self._apply_focus_thresholds_change()
        except Exception:
            pass

    def _update_focus_detect_virtual_folder_counts(self, folder: str, items: list, sub: str = ""):
        try:
            from PyQt6.QtCore import Qt
            import urllib.parse
        except Exception:
            return
        tree = getattr(self.folder_panel, "folder_tree", None) if hasattr(self, "folder_panel") else None
        if tree is None:
            return
        fp = str(folder or "")
        if not fp:
            return

        role_all = f"virtual://focus_detect?folder={urllib.parse.quote(fp)}&status=All"
        role_root = "virtual://focus_detect_root"

        root = None
        try:
            for i in range(tree.topLevelItemCount()):
                it = tree.topLevelItem(i)
                if it is None:
                    continue
                if it.data(0, Qt.ItemDataRole.UserRole) == role_root:
                    root = it
                    break
        except Exception:
            root = None
        if root is None:
            return

        folder_item = None
        try:
            for j in range(root.childCount()):
                c = root.child(j)
                if c is None:
                    continue
                if c.data(0, Qt.ItemDataRole.UserRole) == role_all:
                    folder_item = c
                    break
        except Exception:
            folder_item = None
        if folder_item is None:
            return
        def _count_by_status(src_items: list) -> tuple[dict, int]:
            counts0 = {"Sharp": 0, "Normal": 0, "Blurry": 0, "Minimal": 0, "ExpFrame": 0, "NoBird": 0}
            total0 = 0
            for it in (src_items or []):
                if not isinstance(it, dict):
                    continue
                total0 += 1
                st0 = str(it.get("focus_status") or "")
                if st0 not in counts0:
                    st0 = "NoBird"
                counts0[st0] = int(counts0.get(st0, 0) or 0) + 1
            return counts0, int(total0)

        def _update_status_children(parent_item, counts0: dict, total0: int, tooltip0: str):
            status_name = {
                "All": "全部",
                "Sharp": "锐利",
                "Normal": "普通",
                "Blurry": "虚焦",
                "Minimal": "极小",
                "ExpFrame": "爆框",
                "NoBird": "无鸟",
            }
            try:
                for k in range(parent_item.childCount()):
                    si = parent_item.child(k)
                    if si is None:
                        continue
                    role = si.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(role, str) or "&status=" not in role:
                        continue
                    _, st, _ = self._parse_focus_detect_virtual_path(role)
                    st = str(st or "All")
                    label = status_name.get(st, st)
                    if st == "All":
                        cnt = int(total0)
                    else:
                        cnt = int(counts0.get(st, 0) or 0)
                    si.setText(0, f"{label}（{cnt}）")
                    si.setToolTip(0, tooltip0)
            except Exception:
                pass

        sub = str(sub or "").strip()
        if sub:
            sub_root = None
            try:
                for k in range(folder_item.childCount()):
                    c = folder_item.child(k)
                    if c is None:
                        continue
                    if str(c.text(0) or "").startswith("子文件夹"):
                        sub_root = c
                        break
            except Exception:
                sub_root = None
            if sub_root is None:
                return

            target_sub_item = None
            try:
                for k in range(sub_root.childCount()):
                    c = sub_root.child(k)
                    if c is None:
                        continue
                    role = c.data(0, Qt.ItemDataRole.UserRole)
                    if not isinstance(role, str) or "&sub=" not in role:
                        continue
                    _, _, sub2 = self._parse_focus_detect_virtual_path(role)
                    if str(sub2 or "") == sub:
                        target_sub_item = c
                        break
            except Exception:
                target_sub_item = None
            if target_sub_item is None:
                return

            counts2, total2 = _count_by_status(items)
            try:
                target_sub_item.setText(0, f"{sub}（{int(total2)}）")
            except Exception:
                pass
            _update_status_children(target_sub_item, counts2, total2, os.path.join(fp, sub))
            return

        counts, total = _count_by_status(items)
        name = os.path.basename(fp) or fp
        try:
            folder_item.setText(0, f"{name}（{int(total)}）")
            folder_item.setToolTip(0, fp)
        except Exception:
            pass
        _update_status_children(folder_item, counts, total, fp)

        try:
            sub_root = None
            for k in range(folder_item.childCount()):
                c = folder_item.child(k)
                if c is None:
                    continue
                if str(c.text(0) or "").startswith("子文件夹"):
                    sub_root = c
                    break
            if sub_root is None:
                return

            sub_groups: dict[str, list] = {}
            for it in (items or []):
                if not isinstance(it, dict):
                    continue
                p0 = str(it.get("path") or "")
                if not p0:
                    continue
                try:
                    base = self._normalize_folder_key(fp)
                    if base and not base.endswith(os.sep):
                        base = base + os.sep
                    d0 = self._normalize_folder_key(os.path.dirname(p0))
                    if not base or not d0 or (not d0.startswith(base)):
                        first = ""
                    else:
                        rel = d0[len(base):]
                        rel = "" if rel in (".", os.curdir) else rel
                        first = rel.split(os.sep)[0] if rel else ""
                except Exception:
                    first = ""
                if not first or first.startswith(".."):
                    continue
                lst = sub_groups.get(first)
                if lst is None:
                    lst = []
                    sub_groups[first] = lst
                lst.append(it)

            for k in range(sub_root.childCount()):
                sub_item = sub_root.child(k)
                if sub_item is None:
                    continue
                role = sub_item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(role, str) or "&sub=" not in role:
                    continue
                _, _, sub_name = self._parse_focus_detect_virtual_path(role)
                sub_name = str(sub_name or "")
                sub_items = sub_groups.get(sub_name) or []
                counts3, total3 = _count_by_status(sub_items)
                try:
                    sub_item.setText(0, f"{sub_name}（{int(total3)}）")
                except Exception:
                    pass
                _update_status_children(sub_item, counts3, total3, os.path.join(fp, sub_name))
        except Exception:
            pass

    def _update_focus_detect_burst_virtual_group_counts(self, folder: str, first_name: str, items: list):
        try:
            from PyQt6.QtCore import Qt
            import urllib.parse
        except Exception:
            return
        tree = getattr(self.folder_panel, "folder_tree", None) if hasattr(self, "folder_panel") else None
        if tree is None:
            return
        fp = str(folder or "")
        if not fp:
            return
        first = str(first_name or "")
        if not first:
            return

        role_group_all = f"virtual://focus_detect_burst?folder={urllib.parse.quote(fp)}&first={urllib.parse.quote(str(first or ''))}&status=All"
        group_item = None
        try:
            for i in range(tree.topLevelItemCount()):
                top = tree.topLevelItem(i)
                if top is None:
                    continue
                if top.data(0, Qt.ItemDataRole.UserRole) != "virtual://focus_detect_root":
                    continue
                stack = [top]
                while stack and group_item is None:
                    it = stack.pop()
                    try:
                        if it.data(0, Qt.ItemDataRole.UserRole) == role_group_all:
                            group_item = it
                            break
                    except Exception:
                        pass
                    try:
                        for j in range(it.childCount()):
                            c = it.child(j)
                            if c is not None:
                                stack.append(c)
                    except Exception:
                        pass
                break
        except Exception:
            group_item = None
        if group_item is None:
            return

        counts0 = {"Sharp": 0, "Normal": 0, "Blurry": 0, "Minimal": 0, "ExpFrame": 0, "NoBird": 0}
        total0 = 0
        for it in (items or []):
            if not isinstance(it, dict):
                continue
            total0 += 1
            st0 = str(it.get("focus_status") or "")
            if st0 not in counts0:
                st0 = "NoBird"
            counts0[st0] = int(counts0.get(st0, 0) or 0) + 1

        display = first
        try:
            display = os.path.splitext(os.path.basename(display))[0] or display
        except Exception:
            display = display
        try:
            group_item.setText(0, f"{display}（{int(total0)}）")
        except Exception:
            pass

        status_name = {
            "All": "全部",
            "Sharp": "锐利",
            "Normal": "普通",
            "Blurry": "虚焦",
            "Minimal": "极小",
            "ExpFrame": "爆框",
            "NoBird": "无鸟",
        }
        try:
            for j in range(group_item.childCount()):
                si = group_item.child(j)
                if si is None:
                    continue
                role = si.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(role, str) or "&status=" not in role:
                    continue
                folder2, first2, st = self._parse_focus_detect_burst_virtual_path(role)
                if str(folder2 or "") != fp or str(first2 or "") != first:
                    continue
                st = str(st or "All")
                label = status_name.get(st, st)
                if st == "All":
                    cnt = int(total0)
                else:
                    cnt = int(counts0.get(st, 0) or 0)
                si.setText(0, f"{label}（{cnt}）")
        except Exception:
            pass

    def _extract_focus_detect_info(self, item: dict) -> dict:
        if not isinstance(item, dict):
            return {}
        raw = item.get("focus_detect_json")
        if isinstance(raw, str) and raw.strip():
            try:
                data = json.loads(raw)
            except Exception:
                data = None
            if isinstance(data, dict):
                return data
        desc = item.get("description") or ""
        if not isinstance(desc, str) or "focus_detect" not in desc:
            return {}
        try:
            data = json.loads(desc)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        fd = data.get("focus_detect")
        return fd if isinstance(fd, dict) else {}

    def _compute_focus_status_and_debug(self, item: dict, thresholds: dict) -> tuple[str, dict]:
        fd = self._extract_focus_detect_info(item)
        if not fd:
            return "NoBird", {"reason": "no_focus_detect"}

        def _parse_xy(v):
            if v is None:
                return None
            if isinstance(v, dict):
                try:
                    if "x" in v and "y" in v:
                        return float(v.get("x")), float(v.get("y"))
                except Exception:
                    return None
            if isinstance(v, (tuple, list)) and len(v) >= 2:
                try:
                    return float(v[0]), float(v[1])
                except Exception:
                    return None
            if isinstance(v, str) and v:
                try:
                    x = json.loads(v)
                except Exception:
                    x = None
                if isinstance(x, (tuple, list)) and len(x) >= 2:
                    try:
                        return float(x[0]), float(x[1])
                    except Exception:
                        return None
            return None

        def _parse_bbox(v):
            if v is None:
                return None
            if isinstance(v, (tuple, list)) and len(v) >= 4:
                try:
                    return float(v[0]), float(v[1]), float(v[2]), float(v[3])
                except Exception:
                    return None
            if isinstance(v, str) and v:
                try:
                    x = json.loads(v)
                except Exception:
                    x = None
                if isinstance(x, (tuple, list)) and len(x) >= 4:
                    try:
                        return float(x[0]), float(x[1]), float(x[2]), float(x[3])
                    except Exception:
                        return None
            return None

        try:
            has_bird = bool(fd.get("has_bird", True))
        except Exception:
            has_bird = True
        try:
            score = float(fd.get("score") or 0.0)
        except Exception:
            score = 0.0
        try:
            norm_score = float(fd.get("norm_score") or 0.0)
        except Exception:
            norm_score = 0.0
        try:
            area = float(fd.get("area") or item.get("area_ratio") or 0.0)
        except Exception:
            area = 0.0
        conf_present = "conf" in fd
        try:
            conf = float(fd.get("conf") or 0.0) if conf_present else 1.0
        except Exception:
            conf = 1.0
        try:
            exp_frame = bool(fd.get("exp_frame", False))
        except Exception:
            exp_frame = False
        try:
            is_minimal = bool(fd.get("is_minimal", False))
        except Exception:
            is_minimal = False

        conf_th = float((thresholds or {}).get("conf_threshold", 0.0) or 0.0)
        if (not has_bird) or (score <= 0.0 and norm_score <= 0.0):
            return "NoBird", {"reason": "no_bird_or_zero_score"}
        if conf_th > 0.0 and conf_present and conf < conf_th:
            return "NoBird", {"reason": "conf_below_threshold", "conf": conf, "conf_th": conf_th}

        minimal_th = float((thresholds or {}).get("minimal_area_threshold", 0.001) or 0.001)
        if area > 0.0 and area < minimal_th:
            is_minimal = True
        if is_minimal:
            return "Minimal", {"reason": "minimal_area", "area": area, "minimal_th": minimal_th}

        fp_override = False
        fp_in_bird = False
        try:
            fp_override = bool((thresholds or {}).get("focus_point_in_bird_sharp", False))
        except Exception:
            fp_override = False
        if fp_override:
            fp = _parse_xy(item.get("focus_point"))
            bbox = _parse_bbox(fd.get("bbox_orig") or fd.get("bbox") or item.get("bbox_orig") or item.get("bbox"))
            if fp is not None and bbox is not None:
                fx, fy = fp
                try:
                    iw = float(item.get("width") or 0)
                    ih = float(item.get("height") or 0)
                except Exception:
                    iw = ih = 0.0
                if iw > 1 and ih > 1:
                    try:
                        if 0.0 <= float(fx) <= 1.0 and 0.0 <= float(fy) <= 1.0:
                            fx = float(fx) * iw
                            fy = float(fy) * ih
                    except Exception:
                        pass
                x1, y1, x2, y2 = bbox
                fp_in_bird = (fx >= min(x1, x2) and fx <= max(x1, x2) and fy >= min(y1, y2) and fy <= max(y1, y2))
                if fp_in_bird:
                    st = "Sharp"
                    if exp_frame:
                        st = "ExpFrame"
                    return st, {
                        "reason": "focus_point_in_bird_override",
                        "focus_point": (fx, fy),
                        "bbox": (x1, y1, x2, y2),
                        "exp_frame": bool(exp_frame),
                    }

        sharp_th = float((thresholds or {}).get("sharp_threshold", 60) or 60)
        norm_sharp_th = float((thresholds or {}).get("norm_sharp_threshold", 110) or 110)
        sharp_ratio = score / max(float(sharp_th), 1e-6)
        norm_ratio = norm_score / max(float(norm_sharp_th), 1e-6)
        abs_ratio = min(float(sharp_ratio), float(norm_ratio))

        try:
            ratio_best = float(fd.get("ratio_best") or 0.0)
        except Exception:
            ratio_best = 0.0
        try:
            hf_ratio = float(fd.get("hf_ratio") or 0.0)
        except Exception:
            hf_ratio = 0.0
        try:
            hf_margin = float(fd.get("hf_margin") or 0.0)
        except Exception:
            hf_margin = 0.0
        try:
            hf_ratio_robust = float(fd.get("hf_ratio_robust") or 0.0)
        except Exception:
            hf_ratio_robust = 0.0
        try:
            hf_margin_robust = float(fd.get("hf_margin_robust") or 0.0)
        except Exception:
            hf_margin_robust = 0.0
        try:
            bg_hf_p95 = float(fd.get("bg_hf_p95") or 0.0)
        except Exception:
            bg_hf_p95 = 0.0

        normal_ratio_th = float((thresholds or {}).get("normal_contrast_threshold", 0.8) or 0.8)
        hf_ratio_th = float((thresholds or {}).get("hf_ratio_threshold", 1.15) or 1.15)
        hf_margin_th = float((thresholds or {}).get("hf_margin_threshold", 5.0) or 5.0)

        ratio_score = ratio_best / max(float(normal_ratio_th), 1e-6)
        hf_ratio_eff = float(hf_ratio)
        if float(hf_ratio_robust) > 0.0:
            hf_ratio_eff = float(min(float(hf_ratio), float(hf_ratio_robust))) if float(hf_ratio) > 0.0 else float(hf_ratio_robust)
        hf_margin_eff = float(hf_margin)
        if float(hf_margin_robust) != 0.0:
            hf_margin_eff = float(min(float(hf_margin), float(hf_margin_robust))) if float(hf_margin) != 0.0 else float(hf_margin_robust)

        hf_ratio_score = hf_ratio_eff / max(float(hf_ratio_th), 1e-6)
        hf_margin_score = hf_margin_eff / max(float(hf_margin_th), 1e-6)
        contrast_score = max(float(ratio_score), float(hf_ratio_score), float(hf_margin_score))

        texture_ratio_th = float((thresholds or {}).get("texture_ratio_threshold", 1.1) or 1.1)
        texture_weight = float((thresholds or {}).get("texture_weight", 0.0) or 0.0)
        texture_edge_density_ratio = 1.0
        texture_entropy_ratio = 1.0
        try:
            texture_edge_density_ratio = float(fd.get("texture_edge_density_ratio") or 1.0)
        except Exception:
            texture_edge_density_ratio = 1.0
        try:
            texture_entropy_ratio = float(fd.get("texture_entropy_ratio") or 1.0)
        except Exception:
            texture_entropy_ratio = 1.0
        try:
            tw = max(0.0, min(1.0, float(texture_weight)))
        except Exception:
            tw = 0.0
        if tw > 0.0 and texture_ratio_th > 0.0:
            try:
                tex_ratio_eff = max(float(texture_edge_density_ratio), float(texture_entropy_ratio))
                tex_score_raw = float(tex_ratio_eff) / max(float(texture_ratio_th), 1e-6)
                tex_score = 1.0 + (float(tex_score_raw) - 1.0) * float(tw)
                contrast_score = max(float(contrast_score), float(tex_score))
            except Exception:
                pass

        try:
            raw_bg_score = float(fd.get("raw_bg_score") or 0.0)
        except Exception:
            raw_bg_score = 0.0
        try:
            bg_score = float(fd.get("bg_score") or 0.0)
        except Exception:
            bg_score = 0.0

        bg_tail_heavy = False
        try:
            bg_tail_heavy = bool(bg_hf_p95 > max(1.0, float(score) * 0.55))
        except Exception:
            bg_tail_heavy = False
        flat_bg = (raw_bg_score < (score * 0.2)) or (bg_score < 20.0)
        if flat_bg and abs_ratio < 1.0:
            contrast_score = max(float(hf_ratio_score), float(hf_margin_score))
        if bg_tail_heavy and abs_ratio < 1.1:
            contrast_score = min(float(contrast_score), max(float(hf_ratio_score), float(hf_margin_score), float(ratio_score)))

        area_penalty = 1.0
        try:
            if minimal_th > 0:
                area_penalty = min(1.0, max(0.75, float(area) / float(minimal_th * 3.0)))
        except Exception:
            area_penalty = 1.0

        focus_score = float(abs_ratio) * float(contrast_score) * float(area_penalty)
        if conf_present and conf_th > 0.0:
            try:
                focus_score = focus_score * min(1.0, max(0.0, float(conf) / float(conf_th)))
            except Exception:
                pass

        if focus_score >= 1.0 and abs_ratio >= 1.0 and contrast_score >= 1.0:
            status = "Sharp"
        elif focus_score >= 0.65 and abs_ratio >= 0.75:
            status = "Normal"
        else:
            status = "Blurry"

        if exp_frame and status in ("Sharp", "Normal"):
            status = "ExpFrame"

        debug = {
            "score": score,
            "norm_score": norm_score,
            "sharp_th": sharp_th,
            "norm_sharp_th": norm_sharp_th,
            "focus_point_in_bird_sharp": bool(fp_override),
            "focus_point_in_bird": bool(fp_in_bird),
            "sharp_ratio": sharp_ratio,
            "norm_ratio": norm_ratio,
            "abs_ratio": abs_ratio,
            "ratio_best": ratio_best,
            "normal_ratio_th": normal_ratio_th,
            "ratio_score": ratio_score,
            "hf_ratio": hf_ratio,
            "hf_ratio_th": hf_ratio_th,
            "hf_ratio_robust": hf_ratio_robust,
            "hf_ratio_eff": hf_ratio_eff,
            "hf_ratio_score": hf_ratio_score,
            "hf_margin": hf_margin,
            "hf_margin_th": hf_margin_th,
            "hf_margin_robust": hf_margin_robust,
            "hf_margin_eff": hf_margin_eff,
            "hf_margin_score": hf_margin_score,
            "texture_edge_density_ratio": texture_edge_density_ratio,
            "texture_entropy_ratio": texture_entropy_ratio,
            "texture_ratio_th": texture_ratio_th,
            "texture_weight": texture_weight,
            "contrast_score": contrast_score,
            "raw_bg_score": raw_bg_score,
            "bg_score": bg_score,
            "bg_hf_p95": bg_hf_p95,
            "bg_tail_heavy": bool(bg_tail_heavy),
            "flat_bg": bool(flat_bg),
            "area": area,
            "minimal_area_th": minimal_th,
            "area_penalty": area_penalty,
            "conf": conf if conf_present else None,
            "conf_th": conf_th if conf_present else None,
            "focus_score": focus_score,
        }
        return status, debug

    def _compute_focus_status_for_item(self, item: dict, thresholds: dict) -> str:
        st, _ = self._compute_focus_status_and_debug(item, thresholds)
        return st

    def _print_focus_detect_result(self, image_path: str, image_info: dict | None = None):
        try:
            p0 = str(image_path or "")
        except Exception:
            p0 = ""
        if not p0:
            return
        try:
            cur = str(getattr(self, "_current_folder_path", "") or "")
        except Exception:
            cur = ""
        if not (isinstance(cur, str) and cur.startswith("virtual://focus_detect?")):
            return

        record = None
        try:
            p_db = self.db._normalize_file_path_for_db(p0) if hasattr(self, "db") and hasattr(self.db, "_normalize_file_path_for_db") else p0
        except Exception:
            p_db = p0
        try:
            recs = self.db.get_results_by_paths([p_db], table_name="import_cache") if hasattr(self, "db") and hasattr(self.db, "get_results_by_paths") else {}
        except Exception:
            recs = {}
        if isinstance(recs, dict) and recs:
            try:
                nk = self.db._norm_path_key(p_db) if hasattr(self.db, "_norm_path_key") else str(p_db)
            except Exception:
                nk = str(p_db)
            record = recs.get(str(nk)) or recs.get(str(p_db)) or recs.get(p0)
        if not isinstance(record, dict):
            record = image_info if isinstance(image_info, dict) else {}

        thresholds = self._get_focus_detect_ui_thresholds()
        status, decision = self._compute_focus_status_and_debug(record, thresholds)
        fd = self._extract_focus_detect_info(record)

        out = {
            "path": p0,
            "status": status,
            "thresholds": thresholds,
            "decision": decision,
        }
        try:
            if isinstance(fd, dict) and fd:
                for k in (
                    "has_bird",
                    "score",
                    "norm_score",
                    "area",
                    "conf",
                    "is_minimal",
                    "exp_frame",
                    "raw_bg_score",
                    "bg_score",
                    "bg_hf_p90",
                    "bg_hf_p95",
                    "bird_hf_p90",
                    "ratio",
                    "ratio_local",
                    "ratio_best",
                    "hf_ratio",
                    "hf_margin",
                    "hf_ratio_robust",
                    "hf_margin_robust",
                    "texture_edge_density_ratio",
                    "texture_entropy_ratio",
                    "pos",
                    "bbox_orig",
                    "burst_first_file",
                ):
                    if k in fd:
                        out[k] = fd.get(k)
        except Exception:
            pass
        try:
            if "score" not in out and record.get("score") is not None:
                out["score"] = record.get("score")
        except Exception:
            pass
        try:
            if "norm_score" not in out and record.get("norm_score") is not None:
                out["norm_score"] = record.get("norm_score")
        except Exception:
            pass
        try:
            if "rating" not in out and record.get("rating") is not None:
                out["rating"] = record.get("rating")
        except Exception:
            pass
        try:
            if "label" not in out and record.get("label") is not None:
                out["label"] = record.get("label")
        except Exception:
            pass

        # try:
        #     from utils.log_manager import LogManager

        #     LogManager.instance().debug(f"[FocusDetect] {json.dumps(out, ensure_ascii=False)}")
        # except Exception:
        #     try:
        #         from utils.log_manager import LogManager

        #         LogManager.instance().debug(f"[FocusDetect] path={p0} status={status}")
        #     except Exception:
        #         pass

    def _filter_files_for_display(self, files):
        out = list(files or [])
        if bool(getattr(self, "is_virtual_mode", False)):
            if bool(getattr(self, "_virtual_fav_filter", False)):
                out = [it for it in out if isinstance(it, dict) and int(it.get("is_favorite") or it.get("favorite") or 0) == 1]
            try:
                rf = int(getattr(self, "_virtual_rating_filter", 0) or 0)
            except Exception:
                rf = 0
            if rf > 0:
                op = "="
                try:
                    if hasattr(self, "toolbar") and getattr(self.toolbar, "rating_filter_btn", None) is not None:
                        op = str(self.toolbar.rating_filter_btn.get_mode() or "=")
                except Exception:
                    op = "="
                if op == "≥":
                    out = [it for it in out if isinstance(it, dict) and int(it.get("rating") or 0) >= rf]
                elif op == "≤":
                    out = [it for it in out if isinstance(it, dict) and int(it.get("rating") or 0) <= rf]
                else:
                    out = [it for it in out if isinstance(it, dict) and int(it.get("rating") or 0) == rf]
            try:
                p0 = str(getattr(self, "_current_folder_path", "") or "")
            except Exception:
                p0 = ""
            if isinstance(p0, str) and p0.startswith("virtual://focus_detect?"):
                _, st, _ = self._parse_focus_detect_virtual_path(p0)
                thresholds = self._get_focus_detect_ui_thresholds()
                out2 = []
                for it in out:
                    if not isinstance(it, dict):
                        continue
                    s = self._compute_focus_status_for_item(it, thresholds)
                    it["focus_status"] = s
                    if str(st or "All") != "All" and s != str(st):
                        continue
                    out2.append(it)
                out = out2
            elif isinstance(p0, str) and p0.startswith("virtual://focus_detect_burst?"):
                # 连拍组内的“普通/虚焦/极小...”子节点需要按 status 过滤，否则切换节点缩略图不会变化
                _, _, st = self._parse_focus_detect_burst_virtual_path(p0)
                thresholds = self._get_focus_detect_ui_thresholds()
                out2 = []
                for it in out:
                    if not isinstance(it, dict):
                        continue
                    s = self._compute_focus_status_for_item(it, thresholds)
                    it["focus_status"] = s
                    if str(st or "All") != "All" and s != str(st):
                        continue
                    out2.append(it)
                out = out2

        try:
            adv = getattr(self, "_advanced_search_conditions", None)
        except Exception:
            adv = None
        if adv:
            out2 = []
            local_conditions = [
                c for c in (adv or [])
                if isinstance(c, dict) and c.get("field") not in ("__scope_all__", "__scope_fav__")
            ]
            if local_conditions:
                for img_info in out:
                    if not isinstance(img_info, dict):
                        continue
                    is_match = True
                    for i, condition in enumerate(local_conditions):
                        current_match = self._check_advanced_condition(img_info, condition)
                        if i == 0:
                            is_match = current_match
                        else:
                            logic = condition.get("logic", "AND")
                            if logic == "AND":
                                is_match = is_match and current_match
                            elif logic == "OR":
                                is_match = is_match or current_match
                            elif logic == "NOT":
                                is_match = is_match and (not current_match)
                    if is_match:
                        out2.append(img_info)
                out = out2

        try:
            mode = int(getattr(self, "_stash_filter_mode", 0) or 0)
        except Exception:
            mode = 0
        if mode == 0:
            return out

        stashed = self._get_stash_set_for_current_folder()
        if not stashed:
            return out if mode == 2 else []
        out2 = []
        for it in out:
            try:
                p = it.get("path") if isinstance(it, dict) else None
            except Exception:
                p = None
            if not p:
                continue
            in_stash = self._normalize_path_key(p) in stashed
            if mode == 1 and in_stash:
                out2.append(it)
            elif mode == 2 and (not in_stash):
                out2.append(it)
        return out2

    def _apply_stash_filter_btn_ui(self):
        btn = getattr(self, "stash_filter_btn", None)
        if btn is None:
            return
        try:
            mode = int(getattr(self, "_stash_filter_mode", 0) or 0)
        except Exception:
            mode = 0
        try:
            c = ColorManager.instance().get("theme.text.dark")
        except Exception:
            c = "#555"
        if mode == 1:
            btn.setIcon(qta.icon("mdi6.tag-check", color=c, options=[{"scale_factor": 1.1}]))
            btn.setToolTip("暂存筛选：仅暂存")
        elif mode == 2:
            btn.setIcon(qta.icon("mdi6.tag-off", color=c, options=[{"scale_factor": 1.1}]))
            btn.setToolTip("暂存筛选：仅非暂存")
        else:
            btn.setIcon(qta.icon("mdi6.tag-outline", color=c, options=[{"scale_factor": 1.1}]))
            btn.setToolTip("暂存筛选：不筛选")

    def _apply_stash_filter_mode(self):
        self._schedule_save_stash_state()
        try:
            mode = int(getattr(self, "_stash_filter_mode", 0) or 0)
        except Exception:
            mode = 0
        try:
            if mode == 1:
                self._show_startup_mask("正在筛选暂存...")
            elif mode == 2:
                self._show_startup_mask("正在筛选非暂存...")
            else:
                self._show_startup_mask("正在恢复...")
        except Exception:
            pass
        try:
            request_id = int(getattr(self, "_folder_load_request_id", 0))
        except Exception:
            request_id = 0
        files = self._filter_files_for_display(getattr(self, "_all_image_files", []) or [])
        self._apply_files_view(request_id, files)

    def on_stash_filter_clicked(self):
        try:
            mode = int(getattr(self, "_stash_filter_mode", 0) or 0)
        except Exception:
            mode = 0
        mode = int((mode + 1) % 3)
        try:
            self._stash_filter_mode = int(mode)
        except Exception:
            self._stash_filter_mode = 0
        try:
            self._apply_stash_filter_btn_ui()
        except Exception:
            pass
        self._apply_stash_filter_mode()

    def on_stash_filter_toggled(self, checked: bool):
        try:
            self._stash_filter_mode = 1 if bool(checked) else 0
        except Exception:
            self._stash_filter_mode = 0
        try:
            self._apply_stash_filter_btn_ui()
        except Exception:
            pass
        self._apply_stash_filter_mode()

    def on_toolbar_fav_filter_toggled(self, checked: bool):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        self._virtual_fav_filter = bool(checked)
        try:
            self._show_startup_mask("正在筛选...")
        except Exception:
            pass
        try:
            request_id = int(getattr(self, "_folder_load_request_id", 0))
        except Exception:
            request_id = 0
        files = self._filter_files_for_display(getattr(self, "_all_image_files", []) or [])
        self._apply_files_view(request_id, files)

    def on_toolbar_rating_operator_changed(self):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        try:
            if int(getattr(self, "_virtual_rating_filter", 0) or 0) <= 0:
                return
        except Exception:
            return
        try:
            request_id = int(getattr(self, "_folder_load_request_id", 0))
        except Exception:
            request_id = 0
        files = self._filter_files_for_display(getattr(self, "_all_image_files", []) or [])
        self._apply_files_view(request_id, files)

    def on_toolbar_rating_filter_changed(self, rating: int):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        try:
            self._virtual_rating_filter = max(0, int(rating or 0))
        except Exception:
            self._virtual_rating_filter = 0
        try:
            self._show_startup_mask("正在筛选...")
        except Exception:
            pass
        try:
            request_id = int(getattr(self, "_folder_load_request_id", 0))
        except Exception:
            request_id = 0
        files = self._filter_files_for_display(getattr(self, "_all_image_files", []) or [])
        self._apply_files_view(request_id, files)

    def on_advanced_search(self, conditions):
        try:
            self._advanced_search_conditions = [
                c for c in (conditions or [])
                if isinstance(c, dict) and c.get("field") not in ("__scope_all__", "__scope_fav__")
            ]
        except Exception:
            self._advanced_search_conditions = []
        try:
            self._advanced_search_record_map = {}
        except Exception:
            pass
        try:
            need_fields = {c.get("field") for c in (self._advanced_search_conditions or []) if isinstance(c, dict)}
        except Exception:
            need_fields = set()
        need_db = bool(need_fields.intersection({"标签", "拍摄地址", "地址", "目", "科", "属", "种"}))
        if need_db and bool(getattr(self, "is_virtual_mode", False)):
            try:
                paths = [it.get("path") for it in (getattr(self, "_all_image_files", []) or []) if isinstance(it, dict) and it.get("path")]
            except Exception:
                paths = []
            try:
                raw_map = self.db.get_results_by_paths(paths, table_name="import_cache") if hasattr(self, "db") else {}
            except Exception:
                raw_map = {}
            norm_map = {}
            try:
                for p, rec in (raw_map or {}).items():
                    k = self._normalize_path_key(p)
                    if k:
                        norm_map[k] = rec
            except Exception:
                norm_map = {}
            self._advanced_search_record_map = norm_map
        try:
            self._show_startup_mask("正在筛选...")
        except Exception:
            pass
        try:
            request_id = int(getattr(self, "_folder_load_request_id", 0))
        except Exception:
            request_id = 0
        files = self._filter_files_for_display(getattr(self, "_all_image_files", []) or [])
        self._apply_files_view(request_id, files)

    def on_save_filter(self):
        filter_panel = getattr(getattr(self, "toolbar", None), "filter_panel", None)
        if filter_panel is None:
            return
        try:
            conditions = filter_panel.get_all_conditions()
        except Exception:
            conditions = []

        from ui.widgets.custom_input_dialog import CustomInputDialog
        dialog = CustomInputDialog(self, "保存过滤方案", "方案名称:", "")
        self._suspend_filter_panel_auto_hide = True
        try:
            if not dialog.exec():
                return
            name = dialog.get_value()
            if not name:
                return

            if any(c in name for c in '<>:"/\\|?*'):
                NotificationManager.instance().show_warning("错误", "方案名称包含非法字符")
                return

            save_dir = os.path.join(os.getcwd(), "data", "filter")
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)

            file_path = os.path.join(save_dir, f"{name}.bft")
            if os.path.exists(file_path):
                if not NotificationManager.instance().ask_confirmation("确认覆盖", f"方案 '{name}' 已存在，是否覆盖？"):
                    return

            save_data = {
                "filters": conditions,
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            NotificationManager.instance().show_toast("过滤方案已保存")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"保存失败: {e}")
        finally:
            self._suspend_filter_panel_auto_hide = False

    def on_load_filter(self):
        filter_panel = getattr(getattr(self, "toolbar", None), "filter_panel", None)
        if filter_panel is None:
            return

        save_dir = os.path.join(os.getcwd(), "data", "filter")
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        files = [f for f in os.listdir(save_dir) if f.endswith(".bft")]
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
                close_btn.setIcon(qta.icon("mdi6.close", color=header_text))
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
        finally:
            self._suspend_filter_panel_auto_hide = False
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"加载失败: {e}")
            return

        if isinstance(data, list):
            filters = data
        elif isinstance(data, dict):
            filters = data.get("filters", []) or []
        else:
            NotificationManager.instance().show_warning("错误", "文件格式不正确")
            return

        try:
            filter_panel.set_conditions(filters)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"应用过滤失败: {e}")
            return

        try:
            filter_panel.on_search_clicked()
        except Exception:
            try:
                self.on_advanced_search(filter_panel.get_all_conditions())
            except Exception:
                pass
        NotificationManager.instance().show_toast("方案已加载")

    def _check_advanced_condition(self, img_info, condition):
        field = condition.get("field")
        value = condition.get("value", "")
        fuzzy = condition.get("fuzzy", False)
        operator = condition.get("operator", "=")

        target_value = ""
        rec = None
        try:
            p = img_info.get("path") if isinstance(img_info, dict) else None
        except Exception:
            p = None
        if p:
            try:
                k = self._normalize_path_key(p)
            except Exception:
                k = ""
            if k:
                try:
                    rec = (getattr(self, "_advanced_search_record_map", None) or {}).get(k)
                except Exception:
                    rec = None

        if field == "文件名":
            target_value = str(img_info.get("name", "") or "").lower()
        elif field == "路径":
            target_value = str(img_info.get("path", "") or "").lower()
        elif field == "标签":
            raw_tags = img_info.get("tags", "") or ""
            if raw_tags is None:
                raw_tags = ""
            if (not raw_tags) and isinstance(rec, dict):
                try:
                    raw_tags = rec.get("tags", "") or ""
                except Exception:
                    raw_tags = raw_tags
            search_val = str(value or "").strip().lower()
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
            raw_loc = img_info.get("location", "") if isinstance(img_info, dict) else ""
            if (not raw_loc) and isinstance(rec, dict):
                try:
                    raw_loc = rec.get("location", "") or ""
                except Exception:
                    raw_loc = raw_loc
            target_value = str(raw_loc or "").strip().lower()
            search_val = str(value or "").strip().lower()
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
        elif field == "目":
            v0 = img_info.get("order") if isinstance(img_info, dict) else ""
            if not v0:
                v0 = img_info.get("order_cls") if isinstance(img_info, dict) else ""
            if (not v0) and isinstance(rec, dict):
                v0 = rec.get("order_cls")
            target_value = str(v0 or "").strip().lower()
        elif field == "科":
            v0 = img_info.get("family") if isinstance(img_info, dict) else ""
            if not v0:
                v0 = img_info.get("family_cls") if isinstance(img_info, dict) else ""
            if (not v0) and isinstance(rec, dict):
                v0 = rec.get("family_cls")
            target_value = str(v0 or "").strip().lower()
        elif field == "属":
            v0 = img_info.get("genus") if isinstance(img_info, dict) else ""
            if not v0:
                v0 = img_info.get("genus_cls") if isinstance(img_info, dict) else ""
            if (not v0) and isinstance(rec, dict):
                v0 = rec.get("genus_cls")
            target_value = str(v0 or "").strip().lower()
        elif field == "种":
            v0 = img_info.get("species") if isinstance(img_info, dict) else ""
            if not v0:
                v0 = img_info.get("species_cls") if isinstance(img_info, dict) else ""
            if (not v0) and isinstance(rec, dict):
                v0 = rec.get("species_cls")
            target_value = str(v0 or "").strip().lower()
        elif field == "拍摄时间":
            op = operator or "between"

            shot_ts = 0.0
            try:
                shot_time = img_info.get("shot_time")
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
            if op == "≤":
                return shot_ts <= start_ts
            return shot_ts >= start_ts
        elif field == "评分":
            try:
                filter_rating = float(value)
            except Exception:
                return False
            try:
                img_rating = float(img_info.get("rating") or 0)
            except Exception:
                img_rating = 0.0
            if operator == "=":
                return abs(img_rating - filter_rating) < 0.1
            if operator == "≥":
                return img_rating >= filter_rating - 0.1
            if operator == "≤":
                return img_rating <= filter_rating + 0.1
            return False
        elif field == "分数":
            try:
                filter_score = float(value)
            except Exception:
                return False
            img_score = img_info.get("score")
            if img_score is None:
                img_score = img_info.get("norm_score")
            if img_score is None:
                img_score = 0.0
            try:
                img_score = float(img_score)
            except Exception:
                img_score = 0.0
            if operator == "=":
                return abs(img_score - filter_score) < 0.01
            if operator == "≥":
                return img_score >= filter_score
            if operator == "≤":
                return img_score <= filter_score
            return False
        elif field == "鸟的位置":
            target_value = str(img_info.get("position", "") or "").lower()
        elif field == "色标":
            target_value = str(img_info.get("label", "") or "")
            if value == "None":
                return not target_value
            return value == target_value
        elif field == "目":
            target_value = str(img_info.get("order", "") or "").lower()
        elif field == "科":
            target_value = str(img_info.get("family", "") or "").lower()
        elif field == "属":
            target_value = str(img_info.get("genus", "") or "").lower()
        elif field == "种":
            target_value = str(img_info.get("species", "") or "").lower()
        elif field == "备注":
            target_value = str(img_info.get("notes", "") or img_info.get("remark", "") or "").lower()

        try:
            v = str(value or "").strip().lower()
        except Exception:
            v = ""
        if not v:
            return True
        if fuzzy:
            return v in target_value
        return v == target_value

    def _get_current_detail_path(self):
        try:
            if hasattr(self, "detail_panel") and self.detail_panel:
                idx = int(getattr(self.detail_panel, "current_index", -1))
                lst = getattr(self.detail_panel, "image_list", None) or []
                if 0 <= idx < len(lst):
                    it = lst[idx]
                    if isinstance(it, dict):
                        return it.get("path")
        except Exception:
            pass
        return None

    def _toggle_stash_for_paths(self, file_paths):
        if not file_paths:
            return
        folder_key = self._get_current_folder_key()
        if not folder_key:
            try:
                folder_key = self._normalize_folder_key(os.path.dirname(str(file_paths[0] or "")))
            except Exception:
                folder_key = ""
        if not folder_key:
            NotificationManager.instance().show_warning("提示", "未能确定当前文件夹")
            return

        stash = self._stash_by_folder.setdefault(folder_key, set())
        added = 0
        removed = 0
        changed_to_true = []
        changed_to_false = []
        for p in (file_paths or []):
            k = self._normalize_path_key(p)
            if not k:
                continue
            if k in stash:
                try:
                    stash.remove(k)
                except Exception:
                    pass
                changed_to_false.append(k)
                removed += 1
            else:
                stash.add(k)
                changed_to_true.append(k)
                added += 1

        if not stash:
            try:
                self._stash_by_folder.pop(folder_key, None)
            except Exception:
                pass

        if changed_to_true or changed_to_false:
            changed_true_set = set(changed_to_true)
            changed_false_set = set(changed_to_false)
            try:
                for it in (self._all_image_files or []):
                    if not isinstance(it, dict):
                        continue
                    p = it.get("path")
                    if not p:
                        continue
                    k = self._normalize_path_key(p)
                    if k in changed_true_set:
                        it["is_stashed"] = True
                    elif k in changed_false_set:
                        it["is_stashed"] = False
            except Exception:
                pass
            try:
                for it in (self.image_files or []):
                    if not isinstance(it, dict):
                        continue
                    p = it.get("path")
                    if not p:
                        continue
                    k = self._normalize_path_key(p)
                    if k in changed_true_set:
                        it["is_stashed"] = True
                    elif k in changed_false_set:
                        it["is_stashed"] = False
            except Exception:
                pass
            try:
                for k in changed_true_set.union(changed_false_set):
                    for thumb in (self._thumb_by_path.get(k, []) or []):
                        try:
                            info = getattr(thumb, "image_info", None)
                            if isinstance(info, dict):
                                info["is_stashed"] = k in changed_true_set
                                if hasattr(thumb, "icon_overlay") and thumb.icon_overlay is not None:
                                    thumb.icon_overlay.set_image_info(info)
                                thumb.update()
                        except Exception:
                            pass
            except Exception:
                pass

        # if added > 0 and removed > 0:
        #     NotificationManager.instance().show_toast(f"已暂存 {added} 张，已取消暂存 {removed} 张")
        # elif added > 0:
        #     NotificationManager.instance().show_toast(f"已暂存 {added} 张")
        # elif removed > 0:
        #     NotificationManager.instance().show_toast(f"已取消暂存 {removed} 张")
        # else:
        #     NotificationManager.instance().show_toast("未变更暂存状态")
        try:
            if int(getattr(self, "_stash_filter_mode", 0) or 0) != 0:
                self._apply_stash_filter_mode()
        except Exception:
            pass
        self._schedule_save_stash_state()

    def _set_stash_for_paths(self, file_paths, stashed: bool):
        if not file_paths:
            return
        folder_key = self._get_current_folder_key()
        if not folder_key:
            try:
                folder_key = self._normalize_folder_key(os.path.dirname(str(file_paths[0] or "")))
            except Exception:
                folder_key = ""
        if not folder_key:
            return
        stash = self._stash_by_folder.setdefault(folder_key, set())
        changed_to_true = []
        changed_to_false = []
        for p in (file_paths or []):
            k = self._normalize_path_key(p)
            if not k:
                continue
            if bool(stashed):
                if k not in stash:
                    stash.add(k)
                    changed_to_true.append(k)
            else:
                if k in stash:
                    try:
                        stash.remove(k)
                    except Exception:
                        pass
                    changed_to_false.append(k)

        if not stash:
            try:
                self._stash_by_folder.pop(folder_key, None)
            except Exception:
                pass

        if changed_to_true or changed_to_false:
            changed_true_set = set(changed_to_true)
            changed_false_set = set(changed_to_false)
            try:
                for it in (self._all_image_files or []):
                    if not isinstance(it, dict):
                        continue
                    p = it.get("path")
                    if not p:
                        continue
                    k = self._normalize_path_key(p)
                    if k in changed_true_set:
                        it["is_stashed"] = True
                    elif k in changed_false_set:
                        it["is_stashed"] = False
            except Exception:
                pass
            try:
                for it in (self.image_files or []):
                    if not isinstance(it, dict):
                        continue
                    p = it.get("path")
                    if not p:
                        continue
                    k = self._normalize_path_key(p)
                    if k in changed_true_set:
                        it["is_stashed"] = True
                    elif k in changed_false_set:
                        it["is_stashed"] = False
            except Exception:
                pass
            try:
                for k in changed_true_set.union(changed_false_set):
                    for thumb in (self._thumb_by_path.get(k, []) or []):
                        try:
                            info = getattr(thumb, "image_info", None)
                            if isinstance(info, dict):
                                info["is_stashed"] = k in changed_true_set
                                if hasattr(thumb, "icon_overlay") and thumb.icon_overlay is not None:
                                    thumb.icon_overlay.set_image_info(info)
                                thumb.update()
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            if int(getattr(self, "_stash_filter_mode", 0) or 0) != 0:
                self._apply_stash_filter_mode()
        except Exception:
            pass
        self._schedule_save_stash_state()

    def stash_selected_images(self):
        file_paths = self.get_selected_paths()
        if not file_paths:
            p = self._get_current_detail_path() or getattr(self, "current_preview_path", None)
            if p:
                file_paths = [p]
        if not file_paths:
            NotificationManager.instance().show_warning("提示", "请先选择图片")
            return
        self._toggle_stash_for_paths(file_paths)

    def _update_force_low_quality_state(self):
        """更新强制低质量模式状态"""
        force_low = bool(self.settings_manager.get("import/force_low_quality", True))
        if hasattr(self, "grid_view") and hasattr(self.grid_view, "thumbnails"):
            for thumb in self.grid_view.thumbnails:
                thumb.force_low_quality = force_low
                
    def _build_thumbnail_batch(self):
        t0 = time.perf_counter()
        try:
            if bool(getattr(self, "_thumb_ui_suspended", False)):
                try:
                    if hasattr(self, "_thumb_build_timer") and self._thumb_build_timer.isActive():
                        self._thumb_build_timer.stop()
                except Exception:
                    pass
                return
        except Exception:
            return
        if self._thumb_build_request_id != self._folder_load_request_id:
            return
        files = self._thumb_build_pending_files
        if not files:
            self._force_hide_startup_mask()
            return
        if getattr(self.grid_view, "is_virtualized", False):
            try:
                if hasattr(self.grid_view, "set_image_list"):
                    self.grid_view.set_image_list(files)
                else:
                    self.grid_view.clear_thumbnails()
                    for i, img_data in enumerate(files):
                        if isinstance(img_data, dict):
                            info = img_data.copy()
                        else:
                            info = {"path": "", "name": "", "create_time": ""}
                        info["index"] = int(i)
                        self.grid_view.add_thumbnail(info)
                force_low_quality = bool(self.settings_manager.get("import/force_low_quality", True))
                self._thumb_by_path = {}
                for item in getattr(self.grid_view, "thumbnails", []) or []:
                    try:
                        item.force_low_quality = force_low_quality
                    except Exception:
                        pass
                    try:
                        info = getattr(item, "image_info", None) or {}
                        path_key = info.get("path")
                    except Exception:
                        path_key = None
                    if path_key:
                        self._thumb_by_path.setdefault(self._normalize_path_key(path_key), []).append(item)
                self._thumb_build_pending_files = []
                self._thumb_build_index = len(files)
                self._thumb_build_target_count = len(files)
                self._reset_visible_loading()
                QTimer.singleShot(0, self._maybe_hide_startup_mask)
                try:
                    if bool(getattr(self, "is_virtual_mode", False)):
                        self._virtual_overlay_backfill_rid = int(getattr(self, "_folder_load_request_id", 0) or 0)
                        QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
                        QTimer.singleShot(0, self._refresh_current_preview_overlays_from_import_cache)
                except Exception:
                    pass
            except Exception as e:
                try:
                    from utils.log_manager import LogManager

                    LogManager.instance().warning(f"构建虚拟缩略图失败: {e}")
                except Exception:
                    pass
                self._force_hide_startup_mask()
            return
        
        try:
            start = self._thumb_build_index
            max_batch = 200
            t_budget = 0.004
            end = min(len(files), start + max_batch)

            # 获取低质量设置
            force_low_quality = bool(self.settings_manager.get("import/force_low_quality", True))
            
            i = start
            t_start = time.perf_counter()
            while i < end and (time.perf_counter() - t_start) < t_budget:
                img_data = files[i]
                # 创建占位符缩略图
                thumb = ImageThumbnail(index=i, size=self.grid_view.current_thumb_size)
                thumb.cache_manager = self.cache_manager
                thumb.force_low_quality = force_low_quality # 设置低质量标志
                
                # load_now=False 确保不进行同步加载，仅显示占位符
                thumb.set_image_info(img_data, load_now=False)
                self.grid_view.add_thumbnail(thumb)
                if isinstance(img_data, dict):
                    path_key = img_data.get("path")
                    if path_key:
                        self._thumb_by_path.setdefault(self._normalize_path_key(path_key), []).append(thumb)
                i += 1
            
            # 使用增量布局更新
            if i > start:
                self.grid_view.append_batch_to_layout(self._thumb_build_index)
                try:
                    if start == 0 and not bool(getattr(self, "_did_first_batch_thumb_resize", False)):
                        self._did_first_batch_thumb_resize = True
                        QTimer.singleShot(0, lambda: self._apply_thumb_size_from_slider(apply_reload=True))
                except Exception:
                    pass
                
                self._thumb_build_index = i
                # 仅在缩略图控件真正创建并添加到布局后，再计算可视区域
                if self._thumb_build_index >= self._thumb_build_target_count:
                     self._schedule_visible_load(immediate=False)
                     try:
                         if bool(getattr(self, "is_virtual_mode", False)):
                             rid0 = int(getattr(self, "_folder_load_request_id", 0) or 0)
                             if int(getattr(self, "_virtual_overlay_backfill_rid", -1) or -1) != rid0:
                                 self._virtual_overlay_backfill_rid = rid0
                                 QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
                                 QTimer.singleShot(0, self._refresh_current_preview_overlays_from_import_cache)
                     except Exception:
                         pass
            
            if i < len(files):
                # 继续构建下一批
                self._thumb_build_timer.start(0)
            else:
                # 全部构建完成
                self._thumb_build_pending_files = []
                self._reset_visible_loading()
                self._full_build_deferred = False
                
                # 只有在全部构建完成，或者达到了初始加载目标数量时，才允许隐藏遮罩
                # 这里我们稍微延迟一点，确保布局刷新完成
                QTimer.singleShot(50, self._maybe_hide_startup_mask)
            
            t1 = time.perf_counter()
            if t1 - t0 > 0.005:
                pass
        except Exception as e:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().warning(f"构建缩略图失败: {e}")
            except Exception:
                pass

    def _process_cache_warmup(self):
        if self._cache_warmup_request_id != self._folder_load_request_id:
            self._cache_warmup_timer.stop()
            return
        if not self._cache_warmup_paths:
            self._cache_warmup_timer.stop()
            return
        if getattr(self, "_mouse_busy", False):
            return
        cache_info = self.cache_manager.get_cache_info()
        if cache_info.get("general_cached", 0) >= cache_info.get("max_size", 0):
            self._cache_warmup_timer.stop()
            return
        t0 = time.perf_counter()
        batch = []
        batch_limit = 20
        t_budget = 0.0025
        total = len(self._cache_warmup_paths)
        while self._cache_warmup_index < total and len(batch) < batch_limit:
            if len(batch) > 0 and (time.perf_counter() - t0) > t_budget:
                break
            path = self._cache_warmup_paths[self._cache_warmup_index]
            self._cache_warmup_index += 1
            if not path:
                continue
            norm_path = self._normalize_path_key(path)
            if norm_path in self._requested_paths:
                continue
            if self.cache_manager.has_cache(norm_path):
                continue
            batch.append((4, norm_path))
        if batch:
            load_thumb_size = self.grid_view.current_thumb_size
            try:
                base = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
            except Exception:
                base = 0
            if base > 0:
                try:
                    load_thumb_size = int(base)
                except Exception:
                    load_thumb_size = self.grid_view.current_thumb_size
            self.thumbnail_loader.load_thumbnails(batch, load_thumb_size, request_id=self._load_request_id)
        if self._cache_warmup_index >= total:
            self._cache_warmup_timer.stop()

    def on_thumbnail_loaded(self, path, image):
        """缩略图加载完成回调 (放入队列批量处理)"""
        # 直接使用 _pending_updates 队列
        self._pending_updates.append((path, image))
        if not self._update_timer.isActive():
            self._update_timer.start()

    def _apply_loaded_thumbnail_ui(self, path, image, is_visible):
        # 单张回填逻辑（由性能控制器调用）
        # 核心原则：
        # 1) 可见项：做最小 UI 更新，让用户马上看到
        # 2) 不可见项：只“静默回填”数据，不触发 update/notify，避免无意义重绘导致滚动掉帧
        # 3) 所有耗时操作（读盘/解码/缩放）应已在后台线程完成，这里只做数据写入与必要刷新
        stats_updated = False

        key = self._normalize_path_key(path)
        if key in self._thumb_by_path:
            try:
                if bool(getattr(self.grid_view, "is_virtualized", False)):
                    is_visible = True
            except Exception:
                pass
            for thumb in self._thumb_by_path[key]:
                existing_pix = getattr(thumb, "thumbnail_pixmap", None)
                existing_img = getattr(thumb, "_thumbnail_image", None)
                has_existing_pix = existing_pix is not None and not (hasattr(existing_pix, "isNull") and existing_pix.isNull())
                has_existing_img = existing_img is not None and not (hasattr(existing_img, "isNull") and existing_img.isNull())
                try:
                    is_stale = bool(getattr(thumb, "_stale_thumbnail", False))
                except Exception:
                    is_stale = False
                if (has_existing_pix or has_existing_img) and not is_stale:
                    continue
                if not is_visible:
                    try:
                        thumb._thumbnail_image = image
                        try:
                            thumb._stale_thumbnail = False
                        except Exception:
                            pass
                    except Exception:
                        pass
                    continue
                if hasattr(thumb, "set_thumbnail_image"):
                    # 可见：使用控件自身的更新接口（内部会触发必要的重绘）
                    thumb.set_thumbnail_image(image)
                else:
                    try:
                        thumb.set_pixmap(image)
                    except Exception:
                        pass
                    try:
                        thumb.update()
                    except Exception:
                        pass
                try:
                    thumb._stale_thumbnail = False
                except Exception:
                    pass

            if image is not None and key not in self._loaded_paths:
                self._loaded_paths.add(key)
                self.loaded_count += 1
                stats_updated = True
            if image is not None:
                try:
                    self._inmem_thumb_lru.pop(key, None)
                except Exception:
                    pass
                try:
                    self._inmem_thumb_lru[key] = float(time.time())
                except Exception:
                    self._inmem_thumb_lru[key] = 0.0
                try:
                    self._enforce_in_memory_thumbnail_limit()
                except Exception:
                    pass

        if key in self._pending_visible_paths:
            self._pending_visible_paths.discard(key)

        if self._startup_mask_visible:
            # 启动遮罩的隐藏条件：
            # - 当前“第一屏可见区域”所有 pending 路径都完成加载（或命中缓存）
            # - 避免用户看到从空白到逐个出现的跳变
            if image is not None and key in self._startup_pending_paths:
                self._startup_pending_paths.discard(key)
            if not self._startup_pending_paths:
                self._startup_first_page_ready = True
            self._maybe_hide_startup_mask()
            if self._startup_first_page_ready and self._full_build_deferred:
                # 第一屏 ready 后再继续做“全量增量构建”，避免一上来建控件把主线程压死
                self._full_build_deferred = False
                self._thumb_build_target_count = max(self._thumb_build_target_count, self._full_build_total_count)
                if not getattr(self, "_thumb_ui_suspended", False):
                    if not self._thumb_build_timer.isActive():
                        self._thumb_build_timer.start(0)
                if self._cache_warmup_deferred and self._cache_warmup_paths:
                    self._cache_warmup_deferred = False
                    self._cache_warmup_timer.start()

        if image is None and not self._error_notified:
            self._error_notified = True

        if stats_updated and self.has_valid_folder:
            self.stats_changed.emit(len(self.image_files), self.loaded_count, self.selected_count)
        if not self._pending_visible_paths and self._thumb_status_task_id is not None:
            if not self._pending_updates:
                StatusManager.instance().finish_task(self._thumb_status_task_id)
                self._thumb_status_task_id = None

    def _process_pending_updates(self):
        """批量处理待更新的图片"""
        try:
            if bool(getattr(self, "_thumb_ui_suspended", False)):
                try:
                    self._pending_updates.clear()
                except Exception:
                    try:
                        self._pending_updates = deque()
                    except Exception:
                        pass
                try:
                    self._update_timer.stop()
                except Exception:
                    pass
                return
        except Exception:
            return
        if not self._pending_updates:
            self._update_timer.stop()
            return

        t0 = time.perf_counter()
        
        count = 0
        stats_updated = False
        t_start = time.perf_counter()
        
        max_count = 6 if getattr(self, "_mouse_busy", False) else self._update_batch_size
        t_budget = 0.0025 if getattr(self, "_mouse_busy", False) else 0.006
        while self._pending_updates and count < max_count:
            # 动态调整：如果当前帧已经消耗了超过 10ms，则停止处理，留给下一帧
            if count > 0 and (time.perf_counter() - t_start) > t_budget:
                break
                
            path, image = self._pending_updates.popleft()
            count += 1
            
            if not getattr(self, "_current_visible_paths", None):
                continue
            if path not in self._current_visible_paths:
                continue

            if path in self._thumb_by_path:
                for thumb in self._thumb_by_path[path]:
                    existing_pix = getattr(thumb, "thumbnail_pixmap", None)
                    existing_img = getattr(thumb, "_thumbnail_image", None)
                    has_existing_pix = existing_pix is not None and not (hasattr(existing_pix, "isNull") and existing_pix.isNull())
                    has_existing_img = existing_img is not None and not (hasattr(existing_img, "isNull") and existing_img.isNull())
                    if has_existing_pix or has_existing_img:
                        continue
                    # 直接使用预处理好的图片！
                    if hasattr(thumb, 'set_thumbnail_image'):
                        thumb.set_thumbnail_image(image)
                    else:
                        thumb.set_pixmap(image)
                        thumb.update()
                
                # 只有当这是该路径的第一次加载回调时才增加计数
                if image is not None and path not in self._loaded_paths:
                    self._loaded_paths.add(path)
                    self.loaded_count += 1
                    stats_updated = True
            if path in self._pending_visible_paths:
                self._pending_visible_paths.discard(path)

            # 检查是否可以移除启动遮罩中的等待项
            if self._startup_mask_visible:
                if image is not None and path in self._startup_pending_paths:
                    self._startup_pending_paths.discard(path)
                if not self._startup_pending_paths:
                    self._startup_first_page_ready = True
                self._maybe_hide_startup_mask()
                if self._startup_first_page_ready and self._full_build_deferred:
                    self._full_build_deferred = False
                    self._thumb_build_target_count = max(self._thumb_build_target_count, self._full_build_total_count)
                    if not self._thumb_build_timer.isActive():
                        self._thumb_build_timer.start(0)
                    if self._cache_warmup_deferred and self._cache_warmup_paths:
                        self._cache_warmup_deferred = False
                        self._cache_warmup_timer.start()

            if image is None and not self._error_notified:
                self._error_notified = True

        if stats_updated and self.has_valid_folder:
            self.stats_changed.emit(len(self.image_files), self.loaded_count, self.selected_count)
        if not self._pending_visible_paths and self._thumb_status_task_id is not None:
            if not self._pending_updates:
                StatusManager.instance().finish_task(self._thumb_status_task_id)
                self._thumb_status_task_id = None

        t1 = time.perf_counter()
        if t1 - t0 > 0.005:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().debug(f"[Import] process updates ({count}) took: {t1-t0:.4f}s")
            except Exception:
                pass
        
        if not self._pending_updates:
            self._update_timer.stop()


    def on_thumbnail_metrics(self, path, image, request_id, elapsed_ms, from_cache, attempts):
        if int(request_id or 0) != int(self._load_request_id):
            return
        self._metrics_total += 1
        if image is None:
            self._metrics_fail += 1
        if from_cache:
            self._metrics_cache_hits += 1
        self._metrics_times.append(float(elapsed_ms))
        now = time.time()
        if now - self._metrics_last_log >= 2.0:
            self._metrics_last_log = now
            total = len(self._metrics_times)
            avg_ms = sum(self._metrics_times) / max(1, total)
            sorted_times = sorted(self._metrics_times)
            p50 = sorted_times[int((total - 1) * 0.5)] if total else 0.0
            p95 = sorted_times[int((total - 1) * 0.95)] if total else 0.0
            max_ms = sorted_times[-1] if total else 0.0
            cache_info = self.cache_manager.get_cache_info()
            try:
                from utils.log_manager import LogManager

                LogManager.instance().debug(
                    f"[Import] Thumb metrics: total={self._metrics_total}, fail={self._metrics_fail}, "
                    f"cache_hit={self._metrics_cache_hits}, avg_ms={avg_ms:.1f}, p50={p50:.1f}, "
                    f"p95={p95:.1f}, max={max_ms:.1f}, "
                    f"cache={cache_info.get('general_cached', 0)}/{cache_info.get('max_size', 0)}, "
                    f"preload_q={cache_info.get('preload_queue', 0)}, requested={len(self._requested_paths)}"
                )
            except Exception:
                pass
    def on_grid_scroll(self, value):
        # 导入页滚动事件：
        # - 滚动回调频率很高，不能在这里做任何重计算或批量 UI 更新
        # - 这里主要做两件事：
        #   1) 仅计算可见范围（不做额外动作）
        #   2) 根据可见范围估算需要补建的缩略图控件数量（增量构建），但在快滚暂停期间不建
        t0 = time.perf_counter()
        try:
            # 兜底：没有控制器时仅计算可见范围（不做额外动作）
            start, end, visible_rows = self.grid_view.get_visible_index_range()
        except Exception:
            start, end, visible_rows = 0, -1, 0
        try:
            is_big_mode = int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) == ImageThumbnail.MODE_THUMBNAIL_ONLY
        except Exception:
            is_big_mode = False
        if bool(getattr(self, "is_virtual_mode", False)) and is_big_mode and end >= start:
            try:
                metrics = self.grid_view.get_viewport_metrics() or {}
                cols = max(1, int(metrics.get("cols", 1)))
            except Exception:
                cols = 1
            if cols > 0:
                try:
                    last_row = max(0, int(end) // int(cols))
                except Exception:
                    last_row = 0
                probe_row = int(last_row) + 2
                probe_start = int(probe_row) * int(cols)
                try:
                    total_items = len(getattr(self.grid_view, "thumbnails", []) or [])
                except Exception:
                    total_items = 0
                if 0 <= int(probe_start) < int(total_items):
                    probe_end = min(int(total_items) - 1, int(probe_start) + int(cols) - 1)
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
                            self._schedule_visible_load(immediate=True)
                        except Exception:
                            pass

        try:
            total_count = len(self.image_files)
            built_count = len(self.grid_view.thumbnails)
        except Exception:
            total_count = 0
            built_count = 0

        if built_count < total_count and end >= start:
            # 控件增量构建：
            # - 导入页的缩略图控件是逐步 append 的，如果滚动到尚未构建的区域，需要尽快补齐控件，否则无法显示占位/缩略图
            # - 但构建控件本身也会占用主线程，所以在“快滚暂停”期间直接跳过，等停下后再补齐
            try:
                metrics = self.grid_view.get_viewport_metrics() or {}
                cols = max(1, int(metrics.get("cols", 1)))
            except Exception:
                cols = 1
            buffer_rows = max(1, int(visible_rows or 0) if not getattr(self, "_mouse_busy", False) else 1)
            desired_count = min(total_count, int(end) + 1 + buffer_rows * cols)
            if desired_count > getattr(self, "_thumb_build_target_count", 0):
                self._thumb_build_target_count = desired_count
                if not getattr(self, "_thumb_ui_suspended", False):
                    if not self._thumb_build_timer.isActive():
                        self._thumb_build_timer.start(0)
        t1 = time.perf_counter()
        if t1 - t0 > 0.005:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().debug(f"[Import] scroll event took: {t1-t0:.4f}s")
            except Exception:
                pass

    def _end_fast_scroll(self):
        self._fast_scroll_active = False
        self._schedule_visible_load(immediate=True)

    def _reset_visible_loading(self):
        self._load_request_id += 1
        self._requested_paths = set()
        self._requested_retry_ts = {}
        self._inmem_thumb_lru = OrderedDict()
        self._inmem_retain_keys = set()
        self._active_render_indices = set()
        self._pending_visible_paths = set()
        self._error_notified = False
        self._metrics_total = 0
        self._metrics_fail = 0
        self._metrics_times = []
        self._metrics_last_log = 0.0
        self._metrics_cache_hits = 0
        if self._thumb_status_task_id is not None:
            StatusManager.instance().finish_task(self._thumb_status_task_id)
            self._thumb_status_task_id = None
        self._schedule_visible_load(immediate=True)
        self._last_visible_start = None
        self._last_visible_end = None

    def _schedule_visible_load(self, immediate=False):
        """调度可见区域缩略图的加载
        
        使用去抖动（Debounce）机制来优化滚动性能。
        """
        try:
            if bool(getattr(self, "_thumb_ui_suspended", False)):
                return
        except Exception:
            return
        if not hasattr(self, "_visible_load_timer"):
            return
        self._visible_load_force_cancel = bool(immediate)
        
        if self._visible_load_timer.isActive():
            if not bool(immediate):
                return
            try:
                if int(self._visible_load_timer.interval()) == 0:
                    return
            except Exception:
                return
            self._visible_load_timer.stop()
        
        # immediate=True 时立即执行（延时0ms），否则延时 40ms
        # 优化：降低延时以支持"随滚随加载"，避免等待感
        interval = 0 if immediate else 40 
        self._visible_load_timer.start(interval)

    def _load_visible_thumbnails(self):
        """加载当前可见区域及预加载区域的缩略图"""
        t0 = time.perf_counter()
        try:
            if bool(getattr(self, "_thumb_ui_suspended", False)):
                return
        except Exception:
            return
        if not self.image_files or not self.grid_view.thumbnails:
            return
            
        # 获取当前可视区域范围
        start, end, visible_rows = self._get_visible_index_range_for_loading(extra_rows=1)
        if end < start:
            # 如果尚未布局（例如刚启动），强制认为前几行可见
            # 这样可以触发占位符的绘制
            start = 0
            # 估算可见数量：假设 3 行
            metrics = self.grid_view.get_viewport_metrics() or {}
            cols = max(1, int(metrics.get("cols", 1)))
            end = min(len(self.image_files) - 1, start + 3 * cols)
            
        # 获取视口度量信息
        metrics = self.grid_view.get_viewport_metrics() or {}
        cols = max(1, int(metrics.get("cols", 1)))
        try:
            req_size = getattr(self.grid_view, "current_thumb_size", None)
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
        
        # 1. 计算可视区域 + 1个屏幕高度的预加载范围
        # 可视区域已经由 start, end 给出
        # 预加载区域：向下延伸 visible_rows 行 (即下一屏)
        preload_rows = visible_rows
        preload_count = preload_rows * cols
        
        preload_end = min(len(self.image_files) - 1, end + preload_count)

        try:
            is_big_mode = int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) == ImageThumbnail.MODE_THUMBNAIL_ONLY
        except Exception:
            is_big_mode = False
        if is_big_mode and cols > 0 and visible_rows > 0:
            try:
                last_row = max(0, int(end) // int(cols))
            except Exception:
                last_row = 0
            probe_row = int(last_row) + 2
            probe_start = int(probe_row) * int(cols)
            if probe_start < len(self.image_files):
                probe_end = min(len(self.image_files) - 1, probe_start + int(cols) - 1)
                probe_has_unloaded = False
                try:
                    built_n = len(self.grid_view.thumbnails)
                except Exception:
                    built_n = 0
                if built_n > 0:
                    for j in range(int(probe_start), int(min(probe_end, built_n - 1)) + 1):
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
                        big_end = min(len(self.image_files) - 1, int(probe_start) + int(visible_rows) * int(cols) - 1)
                    except Exception:
                        big_end = preload_end
                    if int(big_end) > int(preload_end):
                        preload_end = int(big_end)
                    try:
                        total_count = len(self.image_files)
                        built_count = len(self.grid_view.thumbnails)
                    except Exception:
                        total_count = 0
                        built_count = 0
                    if built_count < total_count and built_count < int(preload_end) + 1:
                        try:
                            self._thumb_build_target_count = max(int(getattr(self, "_thumb_build_target_count", 0) or 0), int(preload_end) + 1)
                            if not getattr(self, "_thumb_ui_suspended", False):
                                if not self._thumb_build_timer.isActive():
                                    self._thumb_build_timer.start(0)
                        except Exception:
                            pass

        try:
            inmem_limit = int(getattr(self.cache_manager, "max_cache_size", 0) or 0)
        except Exception:
            inmem_limit = 0
        inmem_limit = int(max(30, min(5000, inmem_limit if inmem_limit > 0 else 500)))
        if is_big_mode and inmem_limit > 0:
            try:
                preload_end = min(int(preload_end), int(start) + int(inmem_limit) - 1)
            except Exception:
                pass

        try:
            if not bool(getattr(self.grid_view, "is_virtualized", False)):
                total_count = int(len(self.image_files))
                built_count = int(len(self.grid_view.thumbnails))
                desired_count = min(int(total_count), int(preload_end) + 1)
                if built_count < desired_count and desired_count > 0:
                    self._thumb_build_target_count = max(int(getattr(self, "_thumb_build_target_count", 0) or 0), int(desired_count))
                    if not bool(getattr(self, "_thumb_ui_suspended", False)):
                        if not self._thumb_build_timer.isActive():
                            self._thumb_build_timer.start(0)
        except Exception:
            pass

        load_thumb_size = self.grid_view.current_thumb_size
        if is_big_mode:
            try:
                base = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
            except Exception:
                base = 0
            if base > 0:
                try:
                    max_req = int(req_max) if int(req_max) > 0 else int(base)
                except Exception:
                    max_req = int(base)
                try:
                    load_thumb_size = int(min(int(max_req), int(base)))
                except Exception:
                    load_thumb_size = int(base)
        
        # 2. 设置当前的请求ID
        self.thumbnail_loader.set_active_request_id(self._load_request_id)
        if getattr(self, "_visible_load_force_cancel", False):
            self.thumbnail_loader.cancel_pending()
            self._requested_paths = set()
            self._requested_exif_paths = set()
        self._visible_load_force_cancel = False

        # 3. 收集需要加载的路径
        # 优先级策略：
        # Priority -1: 可视区域内的图片 (最高优先级)
        # Priority 1: 预加载区域内的图片
        # Priority 3: 其他区域 (如果是全量加载模式，但在懒加载模式下通常不加载)
        
        paths_to_load = []
        current_visible_paths = set()
        pending_visible = set()
        
        # 遍历可视区域 + 预加载区域
        # 仅处理此范围内的图片，实现懒加载
        target_indices = range(start, preload_end + 1)

        try:
            retain_end = max(int(end), int(preload_end))
        except Exception:
            retain_end = int(preload_end)
        if is_big_mode and inmem_limit > 0:
            try:
                retain_end = max(int(end), min(int(preload_end), int(start) + int(inmem_limit) - 1))
            except Exception:
                pass
        retain_keys = set()
        try:
            for ridx in range(int(start), int(retain_end) + 1):
                if ridx < 0 or ridx >= len(self.image_files):
                    break
                fd0 = self.image_files[ridx]
                rp = fd0.get("path") if isinstance(fd0, dict) else str(fd0)
                if not rp:
                    continue
                rk = self._normalize_path_key(rp)
                if rk:
                    retain_keys.add(rk)
        except Exception:
            retain_keys = set()
        self._inmem_retain_keys = retain_keys
        
        # 如果还在启动遮罩显示期间，强制让所有可见的缩略图显示占位符
        force_update_placeholder = self._startup_mask_visible

        missing_control_max_idx = -1
        
        for idx in target_indices:
            if idx >= len(self.image_files):
                break
                
            file_data = self.image_files[idx]
            # 兼容处理：self.image_files 可能包含路径字符串或信息字典
            if isinstance(file_data, dict):
                path = file_data.get('path')
            else:
                path = str(file_data)
                
            if not path:
                continue
            path = self._normalize_path_key(path)
            if not path:
                continue

            if idx <= end: # 在可视区域内
                current_visible_paths.add(path)
                
            # 检查是否需要加载
            # 注意：ThumbnailGridView 中的 thumbnails 列表可能只包含已创建的控件
            # 如果是虚拟模式或控件复用，需要根据 idx 获取对应的控件或状态
            # 这里假设 thumbnails 与 image_files 一一对应 (非虚拟列表模式)
            if idx >= len(self.grid_view.thumbnails):
                if idx > missing_control_max_idx:
                    missing_control_max_idx = int(idx)
                continue
                
            thumb = self.grid_view.thumbnails[idx]
            
            # 如果需要强制显示占位符，且当前没有图片，则触发 update
            if force_update_placeholder and idx <= end:
                 if not getattr(thumb, "thumbnail_pixmap", None) and not getattr(thumb, "_thumbnail_image", None):
                     thumb.update()

            # 检查是否已有图片数据
            existing_pix = getattr(thumb, "thumbnail_pixmap", None)
            existing_img = getattr(thumb, "_thumbnail_image", None)
            has_existing_pix = existing_pix is not None and not (hasattr(existing_pix, "isNull") and existing_pix.isNull())
            has_existing_img = existing_img is not None and not (hasattr(existing_img, "isNull") and existing_img.isNull())
            try:
                is_stale = bool(getattr(thumb, "_stale_thumbnail", False))
            except Exception:
                is_stale = False
            if (has_existing_pix or has_existing_img) and not is_stale and req_max > 0 and not is_big_mode:
                try:
                    if has_existing_img:
                        existing_max = max(int(existing_img.width() or 0), int(existing_img.height() or 0))
                    else:
                        existing_max = max(int(existing_pix.width() or 0), int(existing_pix.height() or 0))
                except Exception:
                    existing_max = 0
                if existing_max > 0 and (existing_max < int(req_max * 0.85) or req_max - existing_max >= 32):
                    try:
                        thumb._stale_thumbnail = True
                        is_stale = True
                    except Exception:
                        pass
            has_loaded = (has_existing_pix or has_existing_img) and not is_stale
            
            # 如果已经请求过，不再重复请求（stale 例外：允许重新请求）
            if path in self._requested_paths and not is_stale:
                if idx <= end: # 可视区域
                    pending_visible.add(path)
                if idx <= end and not has_loaded and not getattr(self, "_mouse_busy", False):
                    try:
                        now_ts = float(time.time())
                    except Exception:
                        now_ts = 0.0
                    last_ts = 0.0
                    try:
                        last_ts = float(self._requested_retry_ts.get(path, 0.0) or 0.0)
                    except Exception:
                        last_ts = 0.0
                    if now_ts > 0.0 and (last_ts <= 0.0 or (now_ts - last_ts) >= 0.8):
                        try:
                            if len(self._requested_retry_ts) > 5000:
                                self._requested_retry_ts = {}
                        except Exception:
                            self._requested_retry_ts = {}
                        try:
                            self._requested_retry_ts[path] = now_ts
                        except Exception:
                            pass
                        paths_to_load.append((-1, path, True))
                continue
            if path in self._requested_paths and is_stale:
                try:
                    self._requested_paths.discard(path)
                except Exception:
                    pass
            
            # 决定优先级
            if idx <= end:
                # 可视区域：最高优先级
                priority = -1
            elif getattr(self, "_mouse_busy", False):
                # 预加载区域且鼠标忙碌：低优先级
                priority = 2
            else:
                # 预加载区域且鼠标空闲：普通优先级
                priority = 1
            
            # 仅加载未完成的
            if not has_loaded:
                paths_to_load.append((priority, path, idx <= end))
                self._requested_paths.add(path)
                if idx <= end:
                    pending_visible.add(path)
        
        # 强制清除可视区域之外的已加载缩略图以释放内存 (可选优化)
        # 但要注意保留预加载区域
        # retain_indices = set(range(max(0, start - 100), min(len(self.image_files), preload_end + 100)))
        # self._active_render_indices = set(target_indices) # 更新当前活跃渲染区域
        
        # for idx, thumb in enumerate(self.grid_view.thumbnails):
        #     if idx not in retain_indices:
        #         # 清除图片数据，只保留占位符
        #         if getattr(thumb, "thumbnail_pixmap", None) or getattr(thumb, "_thumbnail_image", None):
        #             thumb.clear_image_data()

        self._current_visible_paths = current_visible_paths
        self._pending_visible_paths = pending_visible

        if paths_to_load:
            # 批量提交加载任务
            self.thumbnail_loader.load_thumbnails(paths_to_load, load_thumb_size, request_id=self._load_request_id)
        if missing_control_max_idx >= 0:
            try:
                total_count = int(len(self.image_files))
                desired_count = min(int(total_count), int(missing_control_max_idx) + 1)
                if desired_count > int(getattr(self, "_thumb_build_target_count", 0) or 0):
                    self._thumb_build_target_count = int(desired_count)
                if not bool(getattr(self, "_thumb_ui_suspended", False)):
                    if not self._thumb_build_timer.isActive():
                        self._thumb_build_timer.start(0)
                QTimer.singleShot(0, lambda: self._schedule_visible_load(immediate=True))
            except Exception:
                pass
        try:
            self._request_visible_exif_details(start, end)
        except Exception:
            pass
        try:
            self._schedule_big_preload(start, end)
        except Exception:
            pass
        
        # 4. 滚动监听与触发机制优化
        # 检查是否接近预加载阈值（距离底部仅剩1行）
        # 这部分逻辑主要在滚动事件处理中，但在加载完成后也需重新评估
        
        # 标记初始可视区域计算已完成
        if not self._startup_initial_load_processed:
            # 收集初始可见区域的路径，用于判断遮罩隐藏时机
            if self._startup_mask_visible:
                 # 将 pending_visible 中的路径加入 _startup_pending_paths
                 # 这样只有当这些图片加载完成后，遮罩才会消失
                 self._startup_pending_paths.update(pending_visible)
                 
                 # 如果没有任何待加载的（例如全部缓存命中），则立即隐藏
                 if not self._startup_pending_paths:
                     self._maybe_hide_startup_mask()
            
            self._startup_initial_load_processed = True
            
        # 如果遮罩仍可见，检查是否所有可视图片都已显示占位符或已加载
        # 其实只要触发了 update，paintEvent 就会绘制占位符
        # 这里我们更关注何时隐藏遮罩：当第一屏图片加载完成时

        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
        except Exception:
            pass

        t1 = time.perf_counter()
        if t1 - t0 > 0.005:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().debug(f"[Import] visible load took: {t1-t0:.4f}s (indices: {len(target_indices)})")
            except Exception:
                pass

    def _enforce_in_memory_thumbnail_limit(self):
        try:
            is_big_mode = int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) == ImageThumbnail.MODE_THUMBNAIL_ONLY
        except Exception:
            is_big_mode = False
        if not is_big_mode:
            return
        try:
            limit = int(getattr(self.cache_manager, "max_cache_size", 0) or 0)
        except Exception:
            limit = 0
        limit = int(max(30, min(5000, limit if limit > 0 else 500)))
        if limit <= 0:
            return
        retain = getattr(self, "_inmem_retain_keys", None)
        if not isinstance(retain, set):
            retain = set()
        if len(retain) >= limit:
            return
        tries = 0
        while len(self._inmem_thumb_lru) > limit and tries < (limit * 2 + 100):
            tries += 1
            try:
                k, _ts = self._inmem_thumb_lru.popitem(last=False)
            except Exception:
                break
            if k in retain:
                try:
                    self._inmem_thumb_lru[k] = float(time.time())
                except Exception:
                    self._inmem_thumb_lru[k] = 0.0
                continue
            thumbs = []
            try:
                thumbs = list(self._thumb_by_path.get(k, []) or [])
            except Exception:
                thumbs = []
            for t in thumbs:
                try:
                    if hasattr(t, "clear_image_data"):
                        t.clear_image_data()
                except Exception:
                    pass
                try:
                    if hasattr(t, "_stale_thumbnail"):
                        t._stale_thumbnail = True
                except Exception:
                    pass
            try:
                self._requested_paths.discard(k)
            except Exception:
                pass
            try:
                self._requested_retry_ts.pop(k, None)
            except Exception:
                pass

    def _request_visible_exif_details(self, start_idx: int, end_idx: int):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        if int(getattr(self, "display_mode", ImageThumbnail.MODE_WITH_NAME) or ImageThumbnail.MODE_WITH_NAME) != ImageThumbnail.MODE_WITH_DETAILS:
            return
        if start_idx < 0 or end_idx < start_idx:
            return
        request_id = int(getattr(self, "_folder_load_request_id", 0) or 0)
        paths = []
        keys = []
        limit = 60
        for idx in range(int(start_idx), int(end_idx) + 1):
            if len(paths) >= limit:
                break
            if idx < 0 or idx >= len(self.image_files):
                break
            file_data = self.image_files[idx]
            if not isinstance(file_data, dict):
                continue
            raw_path = file_data.get("path")
            if not raw_path:
                continue
            k = self._normalize_path_key(raw_path)
            if not k:
                continue
            if k in self._requested_exif_paths:
                continue
            try:
                has_exif = bool(file_data.get("has_exif"))
                has_any = any(bool(file_data.get(x)) for x in ("iso", "shutter", "fnumber", "focal_length"))
            except Exception:
                has_exif = False
                has_any = False
            if has_exif or has_any:
                self._requested_exif_paths.add(k)
                continue
            self._requested_exif_paths.add(k)
            paths.append(str(raw_path))
            keys.append(k)
        if not paths:
            return
        try:
            self._vdbg_log(f"request_visible_exif: req_id={request_id} range={start_idx}-{end_idx} paths={len(paths)} display_mode={getattr(self,'display_mode',None)}")
        except Exception:
            pass

        def run():
            updates = {}
            try:
                try:
                    db_paths = []
                    key_by_db_path = {}
                    for i, p0 in enumerate(paths):
                        try:
                            p_db = self.db._normalize_file_path_for_db(p0)
                        except Exception:
                            p_db = p0
                        if not p_db:
                            continue
                        p_db = str(p_db)
                        db_paths.append(p_db)
                        key_by_db_path[p_db] = keys[i]
                    br_map_raw = self.db.get_results_by_paths(db_paths, table_name="bird_results") or {}
                    br_map_norm = {}
                    for k, v in (br_map_raw or {}).items():
                        try:
                            nk = self.db._norm_path_key(k)
                        except Exception:
                            nk = k
                        if nk:
                            br_map_norm[str(nk)] = v
                except Exception:
                    br_map_raw = {}
                    br_map_norm = {}
                try:
                    self._vdbg_log(f"request_visible_exif: db_lookup bird_results raw={len(br_map_raw or {})} norm={len(br_map_norm or {})}")
                except Exception:
                    pass
                for i, p in enumerate(paths):
                    if request_id != int(getattr(self, "_folder_load_request_id", 0) or 0):
                        return
                    br = {}
                    try:
                        try:
                            p_db = self.db._normalize_file_path_for_db(p)
                        except Exception:
                            p_db = p
                        try:
                            p_nk = self.db._norm_path_key(p_db)
                        except Exception:
                            p_nk = p_db
                        br = br_map_norm.get(str(p_nk)) or br_map_raw.get(str(p_db)) or br_map_raw.get(p) or {}
                    except Exception:
                        br = {}
                    if isinstance(br, dict) and br:
                        iso = br.get("iso")
                        fnumber = br.get("fnumber")
                        shutter = br.get("shutter")
                        focal_length = br.get("focal_length")
                        shot_time = br.get("shot_time")
                        try:
                            has_exif = any(x not in (None, "", 0, 0.0) for x in (iso, fnumber, shutter, focal_length))
                        except Exception:
                            has_exif = False
                        if has_exif:
                            upd = {
                                "has_exif": True,
                                "iso": iso,
                                "fnumber": fnumber,
                                "shutter": shutter,
                                "focal_length": focal_length,
                            }
                            try:
                                if shot_time and str(shot_time).strip():
                                    upd["shot_time"] = shot_time
                            except Exception:
                                pass
                            updates[keys[i]] = upd
                try:
                    self._vdbg_log(f"request_visible_exif: updates_from_bird_results={len(updates)} of {len(paths)}")
                except Exception:
                    pass
                if request_id != int(getattr(self, "_folder_load_request_id", 0) or 0):
                    return
                missing = []
                missing_keys = []
                for i, p in enumerate(paths):
                    if keys[i] not in updates:
                        missing.append(p)
                        missing_keys.append(keys[i])
                if missing:
                    try:
                        try:
                            self._vdbg_log(f"request_visible_exif: fallback_exifread missing={len(missing)}")
                        except Exception:
                            pass
                        for j, p in enumerate(missing):
                            if request_id != int(getattr(self, "_folder_load_request_id", 0) or 0):
                                return
                            try:
                                upd = self._read_exif_basic_exifread(p) or {}
                            except Exception:
                                upd = {}
                            if not isinstance(upd, dict) or not upd:
                                continue
                            updates[missing_keys[j]] = upd
                    except Exception:
                        try:
                            self._vdbg_log("request_visible_exif: fallback_exifread_exception")
                        except Exception:
                            pass
                        pass
            except Exception:
                updates = {}
            if updates:
                try:
                    try:
                        self._vdbg_log(f"request_visible_exif: emit_updates={len(updates)}")
                    except Exception:
                        pass
                    self.exifDetailsReady.emit(request_id, updates)
                except Exception:
                    pass

        Thread(target=run, daemon=True, name=f"ImportExifDetails-{request_id}").start()

    def _apply_exif_updates(self, updates: dict):
        if not isinstance(updates, dict) or not updates:
            return
        try:
            for it in (getattr(self, "_all_image_files", []) or []):
                if not isinstance(it, dict):
                    continue
                p = it.get("path")
                if not p:
                    continue
                k = self._normalize_path_key(p)
                if k in updates:
                    try:
                        it.update(dict(updates.get(k) or {}))
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            for it in (self.image_files or []):
                if not isinstance(it, dict):
                    continue
                p = it.get("path")
                if not p:
                    continue
                k = self._normalize_path_key(p)
                if k in updates:
                    try:
                        it.update(dict(updates.get(k) or {}))
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            for thumb in (getattr(self.grid_view, "thumbnails", []) or []):
                info = getattr(thumb, "image_info", None)
                if not isinstance(info, dict):
                    continue
                p = info.get("path")
                if not p:
                    continue
                k = self._normalize_path_key(p)
                if k in updates:
                    try:
                        info.update(dict(updates.get(k) or {}))
                    except Exception:
                        pass
                    try:
                        if hasattr(thumb, "_detail_cache"):
                            thumb._detail_cache = None
                        if hasattr(thumb, "_detail_cache_path"):
                            thumb._detail_cache_path = None
                    except Exception:
                        pass
                    try:
                        thumb.update()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            if hasattr(self.grid_view, "refresh_specific_thumbnails"):
                file_paths = []
                for thumb in (getattr(self.grid_view, "thumbnails", []) or []):
                    try:
                        p = (thumb.image_info or {}).get("path")
                    except Exception:
                        p = None
                    if not p:
                        continue
                    kk = self._normalize_path_key(p)
                    if kk in updates:
                        file_paths.append(p)
                if file_paths:
                    self.grid_view.refresh_specific_thumbnails(file_paths)
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                cur = str(getattr(self, "_current_folder_path", "") or "")
                thresholds = self._get_focus_detect_ui_thresholds()
                try:
                    for it in (getattr(self, "_all_image_files", []) or []):
                        if not isinstance(it, dict):
                            continue
                        p = it.get("path")
                        if not p:
                            continue
                        k = self._normalize_path_key(p)
                        if k not in updates:
                            continue
                        try:
                            it["focus_status"] = str(self._compute_focus_status_for_item(it, thresholds))
                        except Exception:
                            it["focus_status"] = str(it.get("focus_status") or "NoBird")
                except Exception:
                    pass
                if cur.startswith("virtual://focus_detect_burst?"):
                    folder, first_name, _ = self._parse_focus_detect_burst_virtual_path(cur)
                    if folder and first_name:
                        self._update_focus_detect_burst_virtual_group_counts(folder, first_name, getattr(self, "_all_image_files", []) or [])
                elif cur.startswith("virtual://focus_detect?"):
                    folder, _, sub = self._parse_focus_detect_virtual_path(cur)
                    if folder:
                        self._update_focus_detect_virtual_folder_counts(folder, getattr(self, "_all_image_files", []) or [], sub=str(sub or ""))
        except Exception:
            pass

    def _apply_exif_details_updates(self, request_id: int, updates):
        if request_id != int(getattr(self, "_folder_load_request_id", 0) or 0):
            return
        if not isinstance(updates, dict) or not updates:
            return
        try:
            sample = None
            for k, v in (updates or {}).items():
                sample = (k, v)
                break
            if sample:
                self._vdbg_log(f"apply_exif_updates: req_id={request_id} count={len(updates)} sample_key={sample[0]} sample={ {kk: sample[1].get(kk) for kk in ('has_exif','iso','shutter','fnumber','focal_length','shot_time')} }")
            else:
                self._vdbg_log(f"apply_exif_updates: req_id={request_id} count={len(updates)}")
        except Exception:
            pass
        try:
            for it in (self.image_files or []):
                if not isinstance(it, dict):
                    continue
                p = it.get("path")
                if not p:
                    continue
                k = self._normalize_path_key(p)
                if k in updates:
                    try:
                        it.update(dict(updates.get(k) or {}))
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            updated_thumbs = 0
            for thumb in (getattr(self.grid_view, "thumbnails", []) or []):
                info = getattr(thumb, "image_info", None)
                if not isinstance(info, dict):
                    continue
                p = info.get("path")
                if not p:
                    continue
                k = self._normalize_path_key(p)
                if k in updates:
                    try:
                        info.update(dict(updates.get(k) or {}))
                    except Exception:
                        pass
                    try:
                        if hasattr(thumb, "_detail_cache"):
                            thumb._detail_cache = None
                        if hasattr(thumb, "_detail_cache_path"):
                            thumb._detail_cache_path = None
                    except Exception:
                        pass
                    try:
                        thumb.update()
                    except Exception:
                        pass
                    updated_thumbs += 1
        except Exception:
            pass
        try:
            self._vdbg_log(f"apply_exif_updates: updated_thumbs={int(updated_thumbs)}")
        except Exception:
            pass
        try:
            raw_paths = []
            for k, v in (updates or {}).items():
                if not k:
                    continue
                raw_paths.append(k)
            if hasattr(self.grid_view, "refresh_specific_thumbnails"):
                file_paths = []
                for thumb in (getattr(self.grid_view, "thumbnails", []) or []):
                    try:
                        p = (thumb.image_info or {}).get("path")
                    except Exception:
                        p = None
                    if not p:
                        continue
                    kk = self._normalize_path_key(p)
                    if kk in updates:
                        file_paths.append(p)
                if file_paths:
                    self.grid_view.refresh_specific_thumbnails(file_paths)
        except Exception:
            pass

    def on_folder_panel_toggled(self, visible):
        """处理文件夹面板折叠/展开"""
        # 保存可见性状态
        self.settings_manager.set("import/folder_visible", visible)
        
        sizes = self.content_splitter.sizes()
        if len(sizes) < 2:
            return

        if visible:
            # 展开：恢复之前的宽度
            target_width = max(120, self._last_left_width)
            
            # 解除最大宽度限制
            self.left_panel_container.setMaximumWidth(16777215) # QWIDGETSIZE_MAX
            
            # 调整 sizes
            current_left = sizes[0]
            diff = target_width - current_left
            
            # 主要是减小中间面板 (index 1)
            new_sizes = list(sizes)
            new_sizes[0] = target_width
            if len(new_sizes) > 1:
                new_sizes[1] = max(0, new_sizes[1] - diff)
                
            self.content_splitter.setSizes(new_sizes)
            
            # 恢复 Splitter 拖动
            handle = self.content_splitter.handle(1)
            if handle:
                handle.setEnabled(True)
                handle.setCursor(Qt.CursorShape.SplitHCursor)
        else:
            # 折叠：记录当前宽度，然后收缩
            if sizes[0] > 40: # 避免记录已经是折叠状态的宽度
                self._last_left_width = sizes[0]
            
            target_width = 34 # 30 + border
            
            # 设置最大宽度限制，防止被拉伸
            self.left_panel_container.setMaximumWidth(target_width)
            
            current_left = sizes[0]
            diff = current_left - target_width
            
            # 把多余的空间给中间面板 (index 1)
            new_sizes = list(sizes)
            new_sizes[0] = target_width
            if len(new_sizes) > 1:
                new_sizes[1] += diff
            
            self.content_splitter.setSizes(new_sizes)
            
            # 禁用 Splitter 拖动
            handle = self.content_splitter.handle(1)
            if handle:
                handle.setEnabled(False)
                handle.setCursor(Qt.CursorShape.ArrowCursor)

    def on_import_clicked(self):
        """处理导入按钮点击"""
        last_path = self.settings_manager.get("import/last_path", "")
        before = set()
        try:
            for i in range(self.folder_panel.folder_tree.topLevelItemCount()):
                it = self.folder_panel.folder_tree.topLevelItem(i)
                p = it.data(0, Qt.ItemDataRole.UserRole)
                if p:
                    before.add(os.path.normcase(os.path.normpath(str(p))))
        except Exception:
            before = set()
        paths = []
        path = QFileDialog.getExistingDirectory(self, "选择导入目录", last_path)
        if path and os.path.isdir(path):
            paths = [path]
        if not paths:
            return
        try:
            self.settings_manager.set("import/last_path", paths[0])
        except Exception:
            pass
        try:
            self.folder_panel.add_root_folders(paths)
        except Exception:
            for p in paths:
                self.folder_panel.populate_tree(p)
                break
        self._save_import_root_paths(self._get_import_root_paths_from_tree())
        try:
            after = set()
            for i in range(self.folder_panel.folder_tree.topLevelItemCount()):
                it = self.folder_panel.folder_tree.topLevelItem(i)
                p = it.data(0, Qt.ItemDataRole.UserRole)
                if p:
                    after.add(os.path.normcase(os.path.normpath(str(p))))
            added = max(0, len(after - before))
            skipped = max(0, len(paths) - added)
            if skipped > 0:
                NotificationManager.instance().show_toast(f"已添加 {added} 个目录，已忽略 {skipped} 个已存在目录")
            else:
                NotificationManager.instance().show_toast(f"已添加 {added} 个目录")
        except Exception:
            pass

    def on_recognition_clicked(self):
        """处理识别按钮点击"""
        try:
            if self._focus_detect_running:
                NotificationManager.instance().show_toast("对焦检测正在进行")
                return
        except Exception:
            pass

        roots = self._get_focus_detect_root_paths()
        if not roots:
            NotificationManager.instance().show_warning("提示", "请先添加导入文件夹")
            return

        cancel_event = Event()
        dialog = FocusDetectDialog(self, folders=[], folder_image_counts={})
        try:
            dialog._force_select_none_once = True
            dialog._force_select_all_once = False
            dialog._default_folder_check_state = Qt.CheckState.Unchecked
            dialog._override_saved_folder_selection = True
            dialog._saved_selected_folders = []
        except Exception:
            pass
        try:
            dialog.set_scanning(True, "正在统计文件夹...")
        except Exception:
            pass
        try:
            dialog.finished.connect(lambda _code=None: cancel_event.set())
        except Exception:
            pass

        valid_extensions = set(ext.lower() for ext in (raw_exts + img_exts))
        ignore_dir_names = set(["$RECYCLE.BIN", "System Volume Information"])
        counts = {}
        folder_time_ranges = {}

        def _scan_log(msg: str):
            try:
                from utils.log_manager import LogManager

                LogManager.instance().debug(f"[FocusDetectScan] {msg}")
            except Exception:
                pass

        class _FocusDetectScanBridge(QObject):
            update = pyqtSignal(object, object, object, object, bool, str)

        bridge = _FocusDetectScanBridge()

        def _on_bridge_update(snapshot_counts, found_exts, folder_exts_map, folder_time_ranges_map, done: bool, status_text: str):
            try:
                push_update(
                    dict(snapshot_counts or {}),
                    list(found_exts or []),
                    dict(folder_exts_map or {}),
                    dict(folder_time_ranges_map or {}),
                    bool(done),
                    str(status_text or ""),
                )
            except Exception as e:
                _scan_log(f"ui_update_failed err={e}")

        try:
            bridge.update.connect(_on_bridge_update)
        except Exception as e:
            _scan_log(f"bridge_connect_failed err={e}")

        def push_update(snapshot_counts: dict, found_exts: list, folder_exts_map: dict, folder_time_ranges_map: dict, done: bool, status_text: str):
            try:
                if cancel_event.is_set():
                    return
            except Exception:
                return
            folders = list(snapshot_counts.keys())
            try:
                folders.sort()
            except Exception:
                pass
            try:
                dialog.set_folders_and_counts(folders, snapshot_counts)
                dialog.set_folder_extensions_map(folder_exts_map)
                dialog.set_folder_time_ranges(folder_time_ranges_map)
                dialog.set_scanning(not bool(done), status_text)
            except Exception:
                pass

        def run_scan():
            from collections import deque
            import traceback

            last_emit = time.perf_counter()
            last_print = time.perf_counter()
            t0 = time.perf_counter()
            scanned_dirs = 0
            found_dirs = 0
            err_dirs = 0
            last_activity = time.perf_counter()
            current_dir = ""
            found_extensions = set()
            folder_extensions_map = {}

            _scan_log(f"thread_started roots={len(roots or [])}")
            try:
                sample_exts = sorted(list(valid_extensions))[:20]
            except Exception:
                sample_exts = []
            _scan_log(f"valid_extensions={len(valid_extensions)} sample={sample_exts}")

            def watchdog():
                nonlocal last_activity, current_dir
                while not cancel_event.is_set():
                    time.sleep(2.0)
                    try:
                        idle = time.perf_counter() - last_activity
                    except Exception:
                        idle = 0
                    if idle >= 6.0:
                        _scan_log(f"stalled_for={idle:.1f}s current_dir={current_dir}")

            Thread(target=watchdog, daemon=True, name="FocusDetectScanWatchdog").start()

            def scan_dir(start_dir: str):
                nonlocal last_emit, last_print, scanned_dirs, found_dirs, err_dirs
                q = deque([start_dir])
                _scan_log(f"scan_dir_start root={start_dir}")
                while q:
                    if cancel_event.is_set():
                        _scan_log("cancelled")
                        return
                    d = q.popleft()
                    cnt = 0
                    current_dir = d
                    last_activity = time.perf_counter()
                    try:
                        now0 = time.perf_counter()
                        snap0 = dict(counts)
                        map_to_send = {k: list(v) for k, v in folder_extensions_map.items()}
                        time_to_send = dict(folder_time_ranges)
                        bridge.update.emit(
                            snap0,
                            list(found_extensions),
                            map_to_send,
                            time_to_send,
                            False,
                            f"正在统计文件夹... 已扫描 {scanned_dirs} 个目录，发现 {found_dirs} 个目录含图片（正在读取：{d}）",
                        )
                        last_emit = now0
                    except Exception:
                        pass
                    try:
                        entries_seen = 0
                        _scan_log(f"scandir_open dir={d}")
                        with os.scandir(d) as it:
                            _scan_log(f"scandir_iter_begin dir={d}")
                            local_min_ts = None
                            local_max_ts = None
                            for entry in it:
                                if cancel_event.is_set():
                                    _scan_log("cancelled")
                                    return
                                name = entry.name
                                entries_seen += 1
                                try:
                                    last_activity = time.perf_counter()
                                except Exception:
                                    pass
                                now = time.perf_counter()
                                if now - last_emit >= 0.45:
                                    snap = dict(counts)
                                    try:
                                        time_to_send = dict(folder_time_ranges)
                                        bridge.update.emit(
                                            snap,
                                            False,
                                            {},
                                            time_to_send,
                                            False,
                                            f"正在统计文件夹... 已扫描 {scanned_dirs} 个目录，发现 {found_dirs} 个目录含图片（当前：{d}，已读取 {entries_seen} 项）",
                                        )
                                    except Exception:
                                        pass
                                    last_emit = now
                                if now - last_print >= 2.0:
                                    elapsed = now - t0
                                    _scan_log(f"progress dir={d} entries={entries_seen} scanned={scanned_dirs} found={found_dirs} errors={err_dirs} elapsed={elapsed:.1f}s queue={len(q)}")
                                    last_print = now
                                try:
                                    if entry.is_dir(follow_symlinks=False):
                                        try:
                                            if entry.is_symlink():
                                                continue
                                        except Exception:
                                            pass
                                        if name in ignore_dir_names:
                                            continue
                                        if name.startswith("."):
                                            continue
                                        q.append(entry.path)
                                        continue
                                except Exception:
                                    pass
                                try:
                                    if entry.is_file(follow_symlinks=False):
                                        ext = os.path.splitext(name)[1].lower()
                                        if ext in valid_extensions:
                                            found_extensions.add(ext)
                                            if d not in folder_extensions_map:
                                                folder_extensions_map[d] = set()
                                            folder_extensions_map[d].add(ext)
                                            cnt += 1
                                            try:
                                                st = entry.stat(follow_symlinks=False)
                                                ts = float(getattr(st, "st_mtime", 0.0) or 0.0)
                                            except Exception:
                                                ts = 0.0
                                            if local_min_ts is None or ts < float(local_min_ts):
                                                local_min_ts = float(ts)
                                            if local_max_ts is None or ts > float(local_max_ts):
                                                local_max_ts = float(ts)
                                except Exception:
                                    continue
                        if cnt > 0:
                            counts[d] = int(counts.get(d, 0) or 0) + int(cnt)
                            try:
                                folder_time_ranges[d] = (local_min_ts, local_max_ts)
                            except Exception:
                                pass
                        _scan_log(f"scandir_done dir={d} entries={entries_seen} matched_files={cnt}")
                    except Exception:
                        err_dirs += 1
                        cnt = 0
                        if err_dirs % 20 == 0:
                            _scan_log(f"errors={err_dirs} last_dir={d}")
                        try:
                            _scan_log(f"dir_scan_exception dir={d} err={traceback.format_exc()}")
                        except Exception:
                            pass

                    scanned_dirs += 1
                    if cnt > 0:
                        found_dirs += 1

                    now = time.perf_counter()
                    if now - last_emit >= 0.45:
                        snap = dict(counts)
                        try:
                            map_to_send = {k: list(v) for k, v in folder_extensions_map.items()}
                            time_to_send = dict(folder_time_ranges)
                            bridge.update.emit(
                                snap,
                                list(found_extensions),
                                map_to_send,
                                time_to_send,
                                False,
                                f"正在统计文件夹... 已扫描 {scanned_dirs} 个目录，发现 {found_dirs} 个目录含图片",
                            )
                        except Exception:
                            pass
                        last_emit = now

                    if now - last_print >= 2.0:
                        elapsed = now - t0
                        _scan_log(f"progress scanned={scanned_dirs} found={found_dirs} errors={err_dirs} elapsed={elapsed:.1f}s")
                        last_print = now

            try:
                for r in (roots or []):
                    if cancel_event.is_set():
                        break
                    if r and os.path.isdir(str(r)):
                        rr = str(r).replace("/", os.sep)
                        _scan_log(f"start_root {rr}")
                        try:
                            scan_dir(rr)
                        except Exception as e:
                            _scan_log(f"root_scan_failed root={rr} err={e}")

                snap = dict(counts)
                try:
                    elapsed = time.perf_counter() - t0
                    try:
                        map_to_send = {k: list(v) for k, v in folder_extensions_map.items()}
                        time_to_send = dict(folder_time_ranges)
                        bridge.update.emit(
                            snap,
                            list(found_extensions),
                            map_to_send,
                            time_to_send,
                            True,
                            f"统计完成：已扫描 {scanned_dirs} 个目录，发现 {found_dirs} 个目录含图片，耗时 {elapsed:.1f}s",
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
                _scan_log(f"done scanned={scanned_dirs} found={found_dirs} errors={err_dirs} elapsed={elapsed:.1f}s")
            except Exception as e:
                _scan_log(f"scan_thread_fatal_error err={e}")

        Thread(target=run_scan, daemon=True).start()

        if not dialog.exec():
            try:
                cancel_event.set()
            except Exception:
                pass
            return
        try:
            cancel_event.set()
        except Exception:
            pass

        selected_folders = list(getattr(dialog, "selected_folders", []) or [])
        options = dict(getattr(dialog, "options", {}) or {})
        self._start_focus_detect(selected_folders, options)

    def _on_focus_detect_folders_dropped(self, folders):
        try:
            if self._focus_detect_running:
                NotificationManager.instance().show_toast("对焦检测正在进行")
                return
        except Exception:
            pass
        roots = []
        try:
            seen = set()
            for p in (folders or []):
                if not p:
                    continue
                s = str(p)
                try:
                    k = os.path.normcase(os.path.normpath(s))
                except Exception:
                    k = s
                if not k or k in seen:
                    continue
                seen.add(k)
                roots.append(s)
        except Exception:
            roots = []
        if not roots:
            return

        cancel_event = Event()
        dialog = FocusDetectDialog(self, folders=[], folder_image_counts={})
        try:
            dialog._force_select_all_once = True
            dialog._force_select_none_once = False
            dialog._default_folder_check_state = Qt.CheckState.Checked
            dialog._override_saved_folder_selection = True
            dialog._saved_selected_folders = []
        except Exception:
            pass
        try:
            dialog.set_scanning(True, "正在统计文件夹...")
        except Exception:
            pass
        try:
            dialog.finished.connect(lambda _code=None: cancel_event.set())
        except Exception:
            pass

        valid_extensions = set(ext.lower() for ext in (raw_exts + img_exts))
        ignore_dir_names = set(["$RECYCLE.BIN", "System Volume Information"])
        counts = {}
        folder_extensions_map = {}
        folder_time_ranges = {}

        class _Bridge(QObject):
            update = pyqtSignal(object, object, object, bool, str)

        bridge = _Bridge()

        def _on_update(snapshot_counts, ext_map, time_ranges_map, done: bool, status_text: str):
            try:
                folders2 = list((snapshot_counts or {}).keys())
                try:
                    folders2.sort()
                except Exception:
                    pass
                dialog.set_folders_and_counts(folders2, dict(snapshot_counts or {}))
                dialog.set_folder_extensions_map(dict(ext_map or {}))
                dialog.set_folder_time_ranges(dict(time_ranges_map or {}))
                dialog.set_scanning(not bool(done), str(status_text or ""))
            except Exception:
                pass

        try:
            bridge.update.connect(_on_update)
        except Exception:
            pass

        def run_scan():
            total_roots = len(roots or [])
            for idx, root in enumerate(list(roots or [])):
                if cancel_event.is_set():
                    return
                
                try:
                    for dirpath, dirnames, filenames in os.walk(root):
                        if cancel_event.is_set():
                            return
                        try:
                            dirnames[:] = [d for d in (dirnames or []) if d not in ignore_dir_names]
                        except Exception:
                            pass
                        
                        local_count = 0
                        local_exts = set()
                        local_min_ts = None
                        local_max_ts = None
                        for fn in (filenames or []):
                            try:
                                ext = os.path.splitext(fn)[1].lower()
                            except Exception:
                                ext = ""
                            if ext and ext in valid_extensions:
                                local_count += 1
                                local_exts.add(ext)
                                try:
                                    fp = os.path.join(str(dirpath), str(fn))
                                    ts = float(os.path.getmtime(fp) or 0.0)
                                except Exception:
                                    ts = 0.0
                                if local_min_ts is None or ts < float(local_min_ts):
                                    local_min_ts = float(ts)
                                if local_max_ts is None or ts > float(local_max_ts):
                                    local_max_ts = float(ts)
                        
                        if local_count > 0:
                            counts[str(dirpath)] = local_count
                            try:
                                folder_extensions_map[str(dirpath)] = sorted(list(local_exts))
                            except Exception:
                                folder_extensions_map[str(dirpath)] = []
                            try:
                                folder_time_ranges[str(dirpath)] = (local_min_ts, local_max_ts)
                            except Exception:
                                pass
                except Exception:
                    pass

                try:
                    bridge.update.emit(dict(counts), dict(folder_extensions_map), dict(folder_time_ranges), False, f"正在统计文件夹... ({idx+1}/{total_roots})")
                except Exception:
                    pass
            try:
                bridge.update.emit(dict(counts), dict(folder_extensions_map), dict(folder_time_ranges), True, "统计完成")
            except Exception:
                pass

        Thread(target=run_scan, daemon=True, name=f"FocusDetectDropScan-{int(time.time())}").start()

        if not dialog.exec():
            try:
                cancel_event.set()
            except Exception:
                pass
            return
        try:
            cancel_event.set()
        except Exception:
            pass

        selected_folders = list(getattr(dialog, "selected_folders", []) or [])
        options = dict(getattr(dialog, "options", {}) or {})
        if not selected_folders:
            return
        self._start_focus_detect(selected_folders, options)

    def _get_focus_detect_root_paths(self) -> list[str]:
        roots = []
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                # If we are in virtual mode (showing results), we should NOT use the import root paths from tree or settings.
                # Instead, we should probably return empty to force the user to select something?
                # OR, if the user wants to re-scan the *current* virtual set, that's different.
                # But typically, when user clicks "Focus Check", they want to scan a FOLDER.
                
                # If we return empty list here, the code below returns []
                # And on_recognition_clicked shows "请先添加导入文件夹".
                
                # Wait, if is_virtual_mode is True, it means we are viewing results of a previous scan.
                # If user clicks "Focus Check" again, maybe they want to scan a new folder?
                # Or maybe they want to re-scan the original folders of the current results?
                
                # Let's try to get the original folders from settings if available
                last_folders = self.settings_manager.get("focus_detect/last_folders", [])
                if last_folders:
                     roots = [str(x) for x in last_folders if x]
                else:
                     roots = []
            else:
                # Normal mode: use the folders from the tree
                roots = [str(p) for p in (self._get_import_root_paths_from_tree() or []) if p]
        except Exception:
            roots = []
        
        # If still no roots found (e.g. tree is empty), try fallback to settings
        if not roots:
            try:
                roots = [str(p) for p in (self.settings_manager.get("import/root_paths", []) or []) if p]
            except Exception:
                roots = []

        out = []
        seen = set()
        for p in (roots or []):
            try:
                k = os.path.normcase(os.path.normpath(str(p)))
            except Exception:
                k = str(p)
            if not k or k in seen:
                continue
            seen.add(k)
            if os.path.isdir(str(p)):
                out.append(str(p))
        return out

    def _collect_paths_for_folders(self, folders: list[str], allowed_extensions: list[str] | None = None) -> list[str]:
        if allowed_extensions:
            valid_extensions = set(ext.lower() for ext in allowed_extensions)
        else:
            valid_extensions = set(ext.lower() for ext in (raw_exts + img_exts))
        roots = [str(p) for p in (folders or []) if p]
        
        # If no folders are provided, we should NOT fall back to _all_image_files blindly.
        # This fallback logic (returning self._all_image_files) is likely the cause of "detecting all previous files".
        # Because in virtual mode, _all_image_files contains ALL results from previous detection!
        
        if not roots:
             # If we are in virtual mode, _all_image_files contains everything.
             # If user unchecked all folders in the dialog, they probably expect NOTHING to be scanned, or maybe they made a mistake.
             # But definitely NOT everything.
             # However, if this method is called with empty folders list, what should it return?
             # If it returns empty list, the detection will stop/warn "no files".
             
             # Let's check if we are in virtual mode.
             if bool(getattr(self, "is_virtual_mode", False)):
                 return []
             
             # If not in virtual mode, maybe it's safe to return current view files?
             # But even then, it's risky if the user explicitly deselected folders.
             # The only case where roots is empty is if the user deselected everything in the dialog.
             return []

        out = []
        seen = set()
        ignore_dir_names = set(["$RECYCLE.BIN", "System Volume Information"])
        
        # 将传入的 folders 转换为 set 以便快速查找，并统一路径格式
        # 注意：这里我们只关心 roots 本身，如果用户选择了子目录，它们也应该在 roots 列表中
        selected_folders_set = set()
        for f in roots:
            try:
                selected_folders_set.add(os.path.normcase(os.path.normpath(f)))
            except Exception:
                pass
                
        for start_dir in roots:
            if not start_dir or not os.path.isdir(start_dir):
                continue
            
            # 使用 stack 进行遍历，但仅当子目录也在 selected_folders_set 中时才继续深入？
            # 不，如果使用 stack 递归，意味着只要 start_dir 在列表中，它的所有子目录都会被扫描。
            # 用户的需求是：如果选中了父文件夹，不应该默认把子文件一起检测。
            # 这意味着用户希望非递归扫描？
            # 但通常选择文件夹意味着包含其内容。
            # 如果 FocusDetectDialog 返回的是勾选的所有节点（包括子节点），那么我们可以只扫描这些节点，而不递归。
            # 如果 FocusDetectDialog 只返回父节点（隐含包含子节点），那么我们需要递归。
            # 根据之前的分析，FocusDetectDialog 返回所有被 Check 的节点。
            # 所以，如果用户在 UI 上只勾选了父节点，而没勾选子节点（如果 UI 允许），那么 roots 只包含父节点。
            # 此时如果递归，就会扫描到子节点。这违反了用户的意图（只处理勾选的）。
            # 所以我们应该修改为：只扫描 roots 列表中的每个目录的直接子文件，不递归进入子目录。
            # 但是，如果 roots 中包含了子目录，它们会在外层循环中被处理。
            
            # 修正逻辑：只扫描当前目录下的文件，不将子目录加入 stack
            
            try:
                with os.scandir(start_dir) as it:
                    for entry in it:
                        name = entry.name
                        # 跳过目录处理（不再递归）
                        # try:
                        #     if entry.is_dir(follow_symlinks=False):
                        #         if name in ignore_dir_names or name.startswith("."):
                        #             continue
                        #         stack.append(entry.path)
                        #         continue
                        # except Exception:
                        #     pass
                        
                        try:
                            if entry.is_file(follow_symlinks=False):
                                ext = os.path.splitext(name)[1].lower()
                                if ext not in valid_extensions:
                                    continue
                                p = str(entry.path)
                                try:
                                    k = os.path.normcase(os.path.normpath(p))
                                except Exception:
                                    k = p
                                if k in seen:
                                    continue
                                seen.add(k)
                                out.append(p)
                        except Exception:
                            continue
            except Exception:
                continue
        return out

    def _format_remaining_time(self, seconds: float) -> str:
        """
        将剩余秒数格式化为更易读的中文时间字符串。

        Args:
            seconds: 剩余秒数
        """
        try:
            seconds = float(seconds)
        except Exception:
            seconds = 0.0
        if seconds <= 0:
            return "0秒"
        s = int(seconds + 0.5)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h}小时{m}分{sec}秒"
        if m > 0:
            return f"{m}分{sec}秒"
        return f"{sec}秒"

    def _format_elapsed_time(self, seconds: float) -> str:
        try:
            seconds = float(seconds)
        except Exception:
            seconds = 0.0
        if seconds <= 0:
            return "0秒"
        s = int(seconds + 0.5)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h}小时{m}分{sec}秒"
        if m > 0:
            return f"{m}分{sec}秒"
        return f"{sec}秒"

    def _refresh_focus_progress_ui(self):
        """
        刷新中间图库面板中的对焦检测进度显示。

        仅在“虚拟文件模式”下显示；真实模式下隐藏但继续后台统计。
        """
        overlay = getattr(self, "_focus_progress_overlay", None)
        if overlay is None or not hasattr(overlay, "set_progress"):
            return

        try:
            if not bool(getattr(self, "is_virtual_mode", False)):
                overlay.set_progress(visible=False)
                return
        except Exception:
            try:
                overlay.set_progress(visible=False)
            except Exception:
                pass
            return

        running = bool(getattr(self, "_focus_detect_running", False))
        show_in_center_panel = bool(running)
        if not show_in_center_panel:
            try:
                overlay.set_progress(visible=False)
            except Exception:
                pass
            return

        op = str(getattr(self, "_focus_progress_operation", "") or "处理中")
        try:
            done = int(getattr(self, "_focus_progress_done", 0) or 0)
        except Exception:
            done = 0
        try:
            total = int(getattr(self, "_focus_progress_total", 0) or 0)
        except Exception:
            total = 0
        try:
            start_ts = float(getattr(self, "_focus_progress_start_ts", 0.0) or 0.0)
        except Exception:
            start_ts = 0.0

        if op == "写入EXIF":
            try:
                from utils.exif.exif_utils import ExifHandleWorker

                c, t = ExifHandleWorker.get_instance().get_task_progress()
                base_done = 0
                try:
                    base_done = int(getattr(self, "_focus_exif_base_done", 0) or 0)
                except Exception:
                    base_done = 0
                batch_total = 0
                try:
                    batch_total = int(getattr(self, "_focus_exif_total", 0) or 0)
                except Exception:
                    batch_total = 0
                done = max(0, int(c or 0) - base_done)
                if batch_total > 0:
                    total = int(batch_total)
                    done = min(done, total)
                else:
                    total = int(t or 0)
            except Exception:
                pass

        remaining = max(0, total - done) if total > 0 else 0
        if total > 0 and done >= total and remaining <= 0:
            try:
                overlay.set_progress(visible=False)
            except Exception:
                pass
            try:
                self._focus_eta_op = ""
                self._focus_eta_total = 0
                self._focus_eta_step = 0
                self._focus_eta_bucket = 0
                self._focus_eta_cached_seconds = None
                self._focus_eta_cached_update_ts = 0.0
            except Exception:
                pass
            return
        eta_txt = ""
        elapsed_txt = ""
        try:
            if start_ts > 0:
                elapsed_txt = self._format_elapsed_time(max(0.0, float(time.time()) - float(start_ts)))
        except Exception:
            elapsed_txt = ""
        if total > 0 and done > 0 and start_ts > 0 and remaining > 0:
            try:
                eta_op = str(getattr(self, "_focus_eta_op", "") or "")
            except Exception:
                eta_op = ""
            try:
                eta_total = int(getattr(self, "_focus_eta_total", 0) or 0)
            except Exception:
                eta_total = 0
            try:
                eta_step = int(getattr(self, "_focus_eta_step", 0) or 0)
            except Exception:
                eta_step = 0
            try:
                eta_bucket = int(getattr(self, "_focus_eta_bucket", 0) or 0)
            except Exception:
                eta_bucket = 0
            try:
                eta_cached_seconds = getattr(self, "_focus_eta_cached_seconds", None)
            except Exception:
                eta_cached_seconds = None
            try:
                eta_cached_update_ts = float(getattr(self, "_focus_eta_cached_update_ts", 0.0) or 0.0)
            except Exception:
                eta_cached_update_ts = 0.0

            step = max(1, int((int(total) + 9) // 10))
            if op != eta_op or int(total) != int(eta_total) or int(step) != int(eta_step):
                eta_cached_seconds = None
                eta_cached_update_ts = 0.0
                eta_bucket = 0

            try:
                new_bucket = int(done) // int(step)
            except Exception:
                new_bucket = 0

            if new_bucket >= 1 and int(new_bucket) != int(eta_bucket):
                now_ts = float(time.time())
                elapsed = max(0.001, float(now_ts) - float(start_ts))
                spi = float(elapsed) / float(max(1, int(done)))
                try:
                    spi = max(0.001, min(600.0, float(spi)))
                except Exception:
                    spi = float(elapsed) / float(max(1, int(done)))
                eta_seconds = max(0.0, float(spi) * float(remaining))
                eta_cached_seconds = float(eta_seconds)
                eta_cached_update_ts = float(now_ts)
                eta_bucket = int(new_bucket)

            if eta_cached_seconds is not None and eta_cached_update_ts > 0.0:
                now_ts = float(time.time())
                eta_left = max(0.0, float(eta_cached_seconds) - max(0.0, float(now_ts) - float(eta_cached_update_ts)))
                eta_txt = self._format_remaining_time(float(eta_left))
            try:
                self._focus_eta_op = str(op or "")
                self._focus_eta_total = int(total)
                self._focus_eta_step = int(step)
                self._focus_eta_bucket = int(eta_bucket)
                self._focus_eta_cached_seconds = float(eta_cached_seconds) if eta_cached_seconds is not None else None
                self._focus_eta_cached_update_ts = float(eta_cached_update_ts or 0.0)
            except Exception:
                pass

        if total > 0:
            if eta_txt:
                if elapsed_txt:
                    text = f"当前操作：{op}  已用时 {elapsed_txt}  已完成 {done} / {total} 个文件，还剩 {remaining} 个，预计剩余 {eta_txt}"
                else:
                    text = f"当前操作：{op}  已完成 {done} / {total} 个文件，还剩 {remaining} 个，预计剩余 {eta_txt}"
            else:
                if elapsed_txt:
                    text = f"当前操作：{op}  已用时 {elapsed_txt}  已完成 {done} / {total} 个文件，还剩 {remaining} 个"
                else:
                    text = f"当前操作：{op}  已完成 {done} / {total} 个文件，还剩 {remaining} 个"
        else:
            if elapsed_txt:
                text = f"当前操作：{op}  已用时 {elapsed_txt}"
            else:
                text = f"当前操作：{op}"

        try:
            overlay.set_progress(visible=True, current=done, total=total, text=text)
        except Exception:
            pass

    def _on_focus_progress_update(self, op: str, done: int, total: int, start_ts: float):
        try:
            self._focus_progress_operation = str(op or "处理中")
            self._focus_progress_done = int(done or 0)
            self._focus_progress_total = int(total or 0)
            self._focus_progress_start_ts = float(start_ts or time.time())
        except Exception:
            pass
        try:
            self._refresh_focus_progress_ui()
        except Exception:
            pass

    def _poll_focus_db_results(self):
        try:
            if not bool(getattr(self, "_focus_detect_running", False)):
                if getattr(self, "_focus_db_poll_timer", None) is not None and self._focus_db_poll_timer.isActive():
                    self._focus_db_poll_timer.stop()
                return
        except Exception:
            return
        try:
            if bool(getattr(self, "_thumb_ui_suspended", False)):
                return
        except Exception:
            return

        now_ts = 0.0
        try:
            now_ts = float(time.time())
        except Exception:
            now_ts = 0.0
        try:
            last_ts = float(getattr(self, "_focus_db_last_poll_ts", 0.0) or 0.0)
        except Exception:
            last_ts = 0.0
        if last_ts and now_ts and (now_ts - last_ts) < 2.5:
            return
        try:
            self._focus_db_last_poll_ts = now_ts
        except Exception:
            pass

        thumbs = []
        try:
            thumbs = list(getattr(self.grid_view, "thumbnails", []) or [])
        except Exception:
            thumbs = []
        if not thumbs:
            return

        paths = []
        need_update_keys = set()
        for t in thumbs:
            try:
                info = getattr(t, "image_info", None) or {}
                p = info.get("path")
                if p:
                    try:
                        if (
                            info.get("focus_detect_json")
                            and info.get("score") is not None
                            and info.get("norm_score") is not None
                            and info.get("bbox") is not None
                            and info.get("focus_point") is not None
                        ):
                            continue
                    except Exception:
                        pass
                    ps = str(p)
                    paths.append(ps)
                    if len(paths) >= 60:
                        break
            except Exception:
                continue
        if not paths:
            return

        try:
            records = self.db.get_results_by_paths(paths, table_name="import_cache")
        except Exception:
            records = {}
        if not records:
            return

        rec_by_key = {}
        try:
            for k, v in (records or {}).items():
                if not isinstance(v, dict):
                    continue
                try:
                    rk = self._normalize_path_key(k)
                except Exception:
                    rk = str(k)
                if rk:
                    rec_by_key[rk] = v
                try:
                    fp = v.get("file_path")
                    if fp:
                        rec_by_key[self._normalize_path_key(fp)] = v
                except Exception:
                    pass
        except Exception:
            rec_by_key = {}

        for t in thumbs:
            try:
                info = getattr(t, "image_info", None)
                if not isinstance(info, dict):
                    continue
                p = str(info.get("path") or "")
                if not p:
                    continue
                rec = None
                try:
                    rec = records.get(p)
                except Exception:
                    rec = None
                if rec is None:
                    try:
                        rec = rec_by_key.get(self._normalize_path_key(p))
                    except Exception:
                        rec = None
                if not isinstance(rec, dict):
                    continue
                changed = False
                try:
                    if rec.get("label") is not None and info.get("label") != rec.get("label"):
                        info["label"] = rec.get("label")
                        changed = True
                except Exception:
                    pass
                try:
                    if rec.get("rating") is not None and info.get("rating") != rec.get("rating"):
                        info["rating"] = rec.get("rating")
                        changed = True
                except Exception:
                    pass
                try:
                    if rec.get("description") and info.get("description") != rec.get("description"):
                        info["description"] = rec.get("description")
                        changed = True
                except Exception:
                    pass
                try:
                    if rec.get("norm_score") is not None and info.get("norm_score") != rec.get("norm_score"):
                        info["norm_score"] = rec.get("norm_score")
                        changed = True
                except Exception:
                    pass
                try:
                    if rec.get("score") is not None and info.get("score") != rec.get("score"):
                        info["score"] = rec.get("score")
                        changed = True
                except Exception:
                    pass
                try:
                    if rec.get("bbox") is not None and info.get("bbox") != rec.get("bbox"):
                        info["bbox"] = rec.get("bbox")
                        changed = True
                except Exception:
                    pass
                try:
                    if rec.get("focus_point") is not None and info.get("focus_point") != rec.get("focus_point"):
                        info["focus_point"] = rec.get("focus_point")
                        changed = True
                except Exception:
                    pass
                try:
                    if info.get("width") in (None, 0, 0.0, "") or info.get("height") in (None, 0, 0.0, ""):
                        fdj = rec.get("focus_detect_json")
                        if isinstance(fdj, str) and fdj.strip():
                            fdj = json.loads(fdj)
                        if isinstance(fdj, dict):
                            ow = fdj.get("orig_w")
                            oh = fdj.get("orig_h")
                            if ow and oh:
                                info["width"] = int(ow)
                                info["height"] = int(oh)
                                changed = True
                except Exception:
                    pass
                if changed:
                    try:
                        ov = getattr(t, "icon_overlay", None)
                        if ov is not None and hasattr(ov, "set_image_info"):
                            ov.set_image_info(info)
                        else:
                            t.update()
                    except Exception:
                        pass
            except Exception:
                continue

        try:
            all_items = getattr(self, "_all_image_files", None)
        except Exception:
            all_items = None
        if isinstance(all_items, list) and all_items and rec_by_key:
            try:
                for it in all_items:
                    if not isinstance(it, dict):
                        continue
                    try:
                        p = str(it.get("path") or "")
                    except Exception:
                        p = ""
                    if not p:
                        continue
                    try:
                        rec = rec_by_key.get(self._normalize_path_key(p))
                    except Exception:
                        rec = None
                    if not isinstance(rec, dict):
                        continue
                    try:
                        if rec.get("label") is not None:
                            it["label"] = rec.get("label")
                    except Exception:
                        pass
                    try:
                        if rec.get("rating") is not None:
                            it["rating"] = rec.get("rating")
                    except Exception:
                        pass
                    try:
                        if rec.get("description") is not None:
                            it["description"] = rec.get("description")
                    except Exception:
                        pass
                    try:
                        if rec.get("focus_detect_json") is not None:
                            it["focus_detect_json"] = rec.get("focus_detect_json")
                    except Exception:
                        pass
                    try:
                        if rec.get("bbox") is not None:
                            it["bbox"] = rec.get("bbox")
                    except Exception:
                        pass
                    try:
                        if rec.get("focus_point") is not None:
                            it["focus_point"] = rec.get("focus_point")
                    except Exception:
                        pass
                    try:
                        if (it.get("width") in (None, 0, 0.0, "")) or (it.get("height") in (None, 0, 0.0, "")):
                            fdj = rec.get("focus_detect_json")
                            if isinstance(fdj, str) and fdj.strip():
                                fdj = json.loads(fdj)
                            if isinstance(fdj, dict):
                                ow = fdj.get("orig_w")
                                oh = fdj.get("orig_h")
                                if ow and oh:
                                    it["width"] = int(ow)
                                    it["height"] = int(oh)
                    except Exception:
                        pass
                    try:
                        if rec.get("norm_score") is not None:
                            it["norm_score"] = rec.get("norm_score")
                    except Exception:
                        pass
                    try:
                        if rec.get("score") is not None:
                            it["score"] = rec.get("score")
                    except Exception:
                        pass
            except Exception:
                pass

    def _backfill_visible_thumbnails_from_import_cache(self):
        try:
            thumbs = list(getattr(self.grid_view, "thumbnails", []) or [])
        except Exception:
            thumbs = []
        if not thumbs:
            return
        paths = []
        uuids = []
        fast_ids = []
        for t in thumbs:
            try:
                info = getattr(t, "image_info", None)
                if not isinstance(info, dict):
                    continue
                p = str(info.get("path") or "")
                if not p:
                    continue
                fid0 = info.get("fast_id")
                if not fid0:
                    try:
                        fid0 = get_fast_id(p)
                        if fid0:
                            info["fast_id"] = fid0
                    except Exception:
                        fid0 = None
                if fid0 and str(fid0).strip():
                    fast_ids.append(str(fid0))
                u0 = info.get("uuid")
                if u0 and str(u0).strip():
                    uuids.append(str(u0))
                fp_missing = bool(self._is_missing_focus_point_value(info.get("focus_point")))
                if info.get("bbox") is None and fp_missing and not info.get("focus_detect_json"):
                    paths.append(p)
                elif info.get("bbox") is None or fp_missing:
                    paths.append(p)
                if len(paths) >= 120 and len(uuids) >= 120 and len(fast_ids) >= 120:
                    break
            except Exception:
                continue
        if not paths and not uuids and not fast_ids:
            return
        rec_by_fast_id = {}
        if fast_ids:
            try:
                if hasattr(self, "db") and self.db is not None and hasattr(self.db, "get_results_by_fast_ids"):
                    rec_by_fast_id = self.db.get_results_by_fast_ids(list(dict.fromkeys(fast_ids[:300])), table_name="import_cache") or {}
            except Exception:
                rec_by_fast_id = {}
        rec_by_uuid = {}
        if uuids:
            try:
                if hasattr(self, "db") and self.db is not None and hasattr(self.db, "get_results_by_uuids"):
                    rec_by_uuid = self.db.get_results_by_uuids(list(dict.fromkeys(uuids[:300])), table_name="import_cache") or {}
                elif hasattr(self, "db") and self.db is not None and hasattr(self.db, "get_result_by_uuid"):
                    for u in list(dict.fromkeys(uuids[:120])):
                        try:
                            rec = self.db.get_result_by_uuid(str(u), table_name="import_cache")
                        except Exception:
                            rec = None
                        if isinstance(rec, dict):
                            rec_by_uuid[str(u)] = rec
            except Exception:
                rec_by_uuid = {}
        try:
            recs = self.db.get_results_by_paths(list(dict.fromkeys(paths[:400])), table_name="import_cache") if hasattr(self, "db") else {}
        except Exception:
            recs = {}
        if (not isinstance(recs, dict) or not recs) and not rec_by_uuid and not rec_by_fast_id:
            return
        try:
            rec_by_key = {}
            for k, v in recs.items():
                if not isinstance(v, dict):
                    continue
                rec_by_key[self._normalize_path_key(str(k))] = v
                try:
                    fp = v.get("file_path")
                    if fp:
                        rec_by_key[self._normalize_path_key(str(fp))] = v
                except Exception:
                    pass
        except Exception:
            rec_by_key = {}
        if not rec_by_key and not rec_by_uuid and not rec_by_fast_id:
            return
        for t in thumbs:
            try:
                info = getattr(t, "image_info", None)
                if not isinstance(info, dict):
                    continue
                p = str(info.get("path") or "")
                if not p:
                    continue
                rec = None
                fid0 = info.get("fast_id")
                if fid0:
                    try:
                        rec = rec_by_fast_id.get(str(fid0))
                    except Exception:
                        rec = None
                if not isinstance(rec, dict):
                    u0 = info.get("uuid")
                    if u0:
                        try:
                            rec = rec_by_uuid.get(str(u0))
                        except Exception:
                            rec = None
                if not isinstance(rec, dict):
                    try:
                        rec = recs.get(p)
                    except Exception:
                        rec = None
                if not isinstance(rec, dict):
                    try:
                        rec = rec_by_key.get(self._normalize_path_key(p))
                    except Exception:
                        rec = None
                if not isinstance(rec, dict):
                    continue
                changed = False
                for k in ("bbox", "focus_detect_json", "score", "norm_score", "area_ratio", "position"):
                    try:
                        if rec.get(k) is not None and info.get(k) != rec.get(k):
                            info[k] = rec.get(k)
                            changed = True
                    except Exception:
                        pass
                try:
                    if rec.get("focus_point") is not None and info.get("focus_point") != rec.get("focus_point"):
                        info["focus_point"] = rec.get("focus_point")
                        changed = True
                except Exception:
                    pass
                try:
                    if info.get("width") in (None, 0, 0.0, "") or info.get("height") in (None, 0, 0.0, ""):
                        fdj = rec.get("focus_detect_json")
                        if isinstance(fdj, str) and fdj.strip():
                            fdj = json.loads(fdj)
                        if isinstance(fdj, dict):
                            ow = fdj.get("orig_w")
                            oh = fdj.get("orig_h")
                            if ow and oh:
                                info["width"] = int(ow)
                                info["height"] = int(oh)
                                changed = True
                except Exception:
                    pass
                if changed:
                    try:
                        t.update()
                    except Exception:
                        pass
            except Exception:
                continue

    def _start_focus_point_overlay_autorefresh(self, *, rounds: int = 16, interval_ms: int = 350):
        try:
            timer = getattr(self, "_focus_point_overlay_refresh_timer", None)
        except Exception:
            timer = None
        try:
            if timer is not None:
                timer.stop()
        except Exception:
            pass
        try:
            self._focus_point_overlay_refresh_rounds = int(rounds)
        except Exception:
            self._focus_point_overlay_refresh_rounds = 0
        try:
            self._focus_point_overlay_refresh_timer = QTimer(self)
            self._focus_point_overlay_refresh_timer.setSingleShot(False)
            self._focus_point_overlay_refresh_timer.timeout.connect(self._tick_focus_point_overlay_autorefresh)
            self._focus_point_overlay_refresh_timer.start(int(interval_ms))
        except Exception:
            pass

    def _tick_focus_point_overlay_autorefresh(self):
        try:
            left = int(getattr(self, "_focus_point_overlay_refresh_rounds", 0) or 0)
        except Exception:
            left = 0
        if left <= 0:
            try:
                t = getattr(self, "_focus_point_overlay_refresh_timer", None)
                if t is not None:
                    t.stop()
            except Exception:
                pass
            return
        try:
            self._focus_point_overlay_refresh_rounds = int(left - 1)
        except Exception:
            pass
        try:
            if not bool(getattr(self, "is_virtual_mode", False)):
                return
        except Exception:
            return
        try:
            self._schedule_focus_point_backfill(getattr(self, "image_files", []) or [])
        except Exception:
            pass
        try:
            self._backfill_visible_thumbnails_from_import_cache()
        except Exception:
            pass
        try:
            if hasattr(self.grid_view, "refresh_visible_thumbnails"):
                self.grid_view.refresh_visible_thumbnails(extra_rows=2)
        except Exception:
            pass

    def _start_import_cache_bulk_backfill(self, *, interval_ms: int = 30, batch_size: int = 200):
        try:
            if not bool(getattr(self, "is_virtual_mode", False)):
                return
        except Exception:
            return
        try:
            token = int(getattr(self, "_import_cache_bulk_token", 0) or 0) + 1
            self._import_cache_bulk_token = int(token)
        except Exception:
            self._import_cache_bulk_token = 1
        try:
            self._import_cache_bulk_index = 0
            self._import_cache_bulk_batch_size = int(max(50, min(500, int(batch_size or 200))))
            self._import_cache_bulk_source_id = 0
            self._import_cache_bulk_paths = []
            self._import_cache_bulk_info_by_key = {}
            self._import_cache_bulk_all_source_id = 0
            self._import_cache_bulk_all_by_key = {}
            self._import_cache_bulk_last_log_ts = 0.0
            self._import_cache_bulk_last_log_idx = -1
        except Exception:
            return
        try:
            from utils.log_manager import LogManager

            LogManager.instance().info(
                f"[Import][FocusBulk] start token={int(getattr(self, '_import_cache_bulk_token', 0) or 0)} "
                f"interval_ms={int(interval_ms or 0)} batch_size={int(getattr(self, '_import_cache_bulk_batch_size', 0) or 0)}"
            )
        except Exception:
            pass
        try:
            timer = getattr(self, "_import_cache_bulk_timer", None)
        except Exception:
            timer = None
        if timer is None:
            try:
                timer = QTimer(self)
                timer.setSingleShot(False)
                timer.timeout.connect(self._tick_import_cache_bulk_backfill)
                self._import_cache_bulk_timer = timer
            except Exception:
                return
        try:
            if timer.isActive():
                timer.stop()
        except Exception:
            pass
        try:
            timer.start(int(max(10, min(120, int(interval_ms or 30)))))
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._tick_import_cache_bulk_backfill)
        except Exception:
            pass

    def _tick_import_cache_bulk_backfill(self):
        def _log(msg: str, *, force: bool = False, level: str = "debug"):
            try:
                now_ts = float(time.time())
            except Exception:
                now_ts = 0.0
            try:
                last_ts = float(getattr(self, "_import_cache_bulk_last_log_ts", 0.0) or 0.0)
            except Exception:
                last_ts = 0.0
            if not force and now_ts > 0.0 and last_ts > 0.0 and (now_ts - last_ts) < 1.2:
                return
            try:
                self._import_cache_bulk_last_log_ts = float(now_ts)
            except Exception:
                pass
            try:
                from utils.log_manager import LogManager

                logger = LogManager.instance()
                if str(level or "").lower() == "info":
                    logger.info(str(msg))
                else:
                    logger.debug(str(msg))
            except Exception:
                pass

        try:
            if not bool(getattr(self, "is_virtual_mode", False)):
                _log("[Import][FocusBulk] stop reason=not_virtual_mode", force=True, level="info")
                return
        except Exception:
            _log("[Import][FocusBulk] stop reason=is_virtual_mode_error", force=True, level="info")
            return
        try:
            src = getattr(self, "image_files", None)
            src_id = int(id(src))
        except Exception:
            src = None
            src_id = 0
        try:
            last_src_id = int(getattr(self, "_import_cache_bulk_source_id", 0) or 0)
        except Exception:
            last_src_id = 0
        if src is None or not isinstance(src, list):
            try:
                t = getattr(self, "_import_cache_bulk_timer", None)
                if t is not None:
                    t.stop()
            except Exception:
                pass
            _log("[Import][FocusBulk] stop reason=image_files_missing_or_not_list", force=True, level="info")
            return
        if src_id != last_src_id:
            paths = []
            info_by_key = {}
            try:
                for it in (src or []):
                    if not isinstance(it, dict):
                        continue
                    p = str(it.get("path") or "")
                    if not p:
                        continue
                    k = self._normalize_path_key(p)
                    if not k:
                        continue
                    paths.append(p)
                    info_by_key[k] = it
            except Exception:
                paths = []
                info_by_key = {}
            try:
                all_src = getattr(self, "_all_image_files", None)
                all_src_id = int(id(all_src))
            except Exception:
                all_src = None
                all_src_id = 0
            try:
                last_all_id = int(getattr(self, "_import_cache_bulk_all_source_id", 0) or 0)
            except Exception:
                last_all_id = 0
            if all_src is not None and isinstance(all_src, list) and all_src_id != last_all_id:
                all_by_key = {}
                try:
                    for it in (all_src or []):
                        if not isinstance(it, dict):
                            continue
                        p = str(it.get("path") or "")
                        if not p:
                            continue
                        k = self._normalize_path_key(p)
                        if not k:
                            continue
                        all_by_key[k] = it
                except Exception:
                    all_by_key = {}
                try:
                    self._import_cache_bulk_all_source_id = int(all_src_id)
                    self._import_cache_bulk_all_by_key = dict(all_by_key)
                except Exception:
                    pass
            try:
                sig_len = int(len(paths))
                sig_first = self._normalize_path_key(paths[0]) if paths else ""
                sig_last = self._normalize_path_key(paths[-1]) if paths else ""
                sig = (int(sig_len), str(sig_first), str(sig_last))
            except Exception:
                sig = None
            try:
                prev_sig = getattr(self, "_import_cache_bulk_paths_sig", None)
            except Exception:
                prev_sig = None
            try:
                prev_idx = int(getattr(self, "_import_cache_bulk_index", 0) or 0)
            except Exception:
                prev_idx = 0
            reset_idx = True
            try:
                if sig is not None and prev_sig is not None and tuple(sig) == tuple(prev_sig):
                    reset_idx = False
            except Exception:
                reset_idx = True
            try:
                self._import_cache_bulk_source_id = int(src_id)
                self._import_cache_bulk_paths = list(paths)
                self._import_cache_bulk_info_by_key = dict(info_by_key)
                self._import_cache_bulk_paths_sig = sig
                if bool(reset_idx):
                    self._import_cache_bulk_index = 0
                else:
                    self._import_cache_bulk_index = int(max(0, min(int(prev_idx), int(len(paths)))))
            except Exception:
                pass
            _log(
                f"[Import][FocusBulk] source_changed image_files_id={src_id} paths={len(paths)} reset={bool(reset_idx)} idx={int(getattr(self, '_import_cache_bulk_index', 0) or 0)}",
                force=True,
                level="info",
            )
        try:
            paths = list(getattr(self, "_import_cache_bulk_paths", []) or [])
            idx = int(getattr(self, "_import_cache_bulk_index", 0) or 0)
            bs = int(getattr(self, "_import_cache_bulk_batch_size", 200) or 200)
            info_by_key = getattr(self, "_import_cache_bulk_info_by_key", None) or {}
            all_by_key = getattr(self, "_import_cache_bulk_all_by_key", None) or {}
        except Exception:
            paths = []
            idx = 0
            bs = 200
            info_by_key = {}
            all_by_key = {}
        if not paths or not info_by_key:
            try:
                t = getattr(self, "_import_cache_bulk_timer", None)
                if t is not None:
                    t.stop()
            except Exception:
                pass
            _log("[Import][FocusBulk] stop reason=paths_or_map_empty", force=True, level="info")
            return
        if idx >= len(paths):
            try:
                t = getattr(self, "_import_cache_bulk_timer", None)
                if t is not None:
                    t.stop()
            except Exception:
                pass
            _log(f"[Import][FocusBulk] done total={len(paths)}", force=True, level="info")
            try:
                QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
            except Exception:
                pass
            try:
                if hasattr(self.grid_view, "refresh_visible_thumbnails"):
                    self.grid_view.refresh_visible_thumbnails(extra_rows=3)
            except Exception:
                pass
            return

        batch_paths = paths[idx : idx + max(1, bs)]
        try:
            self._import_cache_bulk_index = int(idx + len(batch_paths))
        except Exception:
            pass
        try:
            last_idx = int(getattr(self, "_import_cache_bulk_last_log_idx", -1) or -1)
        except Exception:
            last_idx = -1
        if last_idx < 0 or int(idx) - int(last_idx) >= int(max(1, bs * 5)):
            try:
                self._import_cache_bulk_last_log_idx = int(idx)
            except Exception:
                pass
            _log(
                f"[Import][FocusBulk] tick idx={idx} batch={len(batch_paths)} total={len(paths)}",
                force=False,
                level="debug",
            )
        try:
            records = self.db.get_results_by_paths(list(dict.fromkeys(batch_paths)), table_name="import_cache") if hasattr(self, "db") else {}
        except Exception:
            records = {}
        if not isinstance(records, dict) or not records:
            _log(
                f"[Import][FocusBulk] db_empty idx={idx} batch={len(batch_paths)}",
                force=False,
                level="debug",
            )
            return

        rec_by_key = {}
        try:
            for k, v in (records or {}).items():
                if not isinstance(v, dict):
                    continue
                try:
                    rk = self._normalize_path_key(str(k))
                except Exception:
                    rk = str(k)
                if rk:
                    rec_by_key[rk] = v
                try:
                    fp = v.get("file_path")
                    if fp:
                        rec_by_key[self._normalize_path_key(str(fp))] = v
                except Exception:
                    pass
        except Exception:
            rec_by_key = {}
        if not rec_by_key:
            _log(
                f"[Import][FocusBulk] rec_map_empty idx={idx} batch={len(batch_paths)} rows={len(records or {})}",
                force=False,
                level="debug",
            )
            return

        changed_any = False
        hit = 0
        changed = 0
        updated_thumbs = 0
        for p in batch_paths:
            try:
                key = self._normalize_path_key(p)
            except Exception:
                key = ""
            if not key:
                continue
            rec = rec_by_key.get(key)
            if not isinstance(rec, dict):
                continue
            hit += 1
            info = info_by_key.get(key)
            if not isinstance(info, dict):
                continue
            all_info = None
            try:
                all_info = all_by_key.get(key)
            except Exception:
                all_info = None
            changed = False
            for k2 in ("bbox", "focus_detect_json", "score", "norm_score", "area_ratio", "position", "label", "rating", "description"):
                try:
                    if rec.get(k2) is not None and info.get(k2) != rec.get(k2):
                        info[k2] = rec.get(k2)
                        changed = True
                except Exception:
                    pass
                try:
                    if isinstance(all_info, dict) and rec.get(k2) is not None and all_info.get(k2) != rec.get(k2):
                        all_info[k2] = rec.get(k2)
                except Exception:
                    pass
            try:
                if rec.get("focus_point") is not None and info.get("focus_point") != rec.get("focus_point"):
                    info["focus_point"] = rec.get("focus_point")
                    changed = True
            except Exception:
                pass
            try:
                if isinstance(all_info, dict) and rec.get("focus_point") is not None and all_info.get("focus_point") != rec.get("focus_point"):
                    all_info["focus_point"] = rec.get("focus_point")
            except Exception:
                pass
            try:
                if info.get("width") in (None, 0, 0.0, "") or info.get("height") in (None, 0, 0.0, ""):
                    fdj = rec.get("focus_detect_json")
                    if isinstance(fdj, str) and fdj.strip():
                        fdj = json.loads(fdj)
                    if isinstance(fdj, dict):
                        ow = fdj.get("orig_w")
                        oh = fdj.get("orig_h")
                        if ow and oh:
                            info["width"] = int(ow)
                            info["height"] = int(oh)
                            changed = True
            except Exception:
                pass
            try:
                if isinstance(all_info, dict) and (all_info.get("width") in (None, 0, 0.0, "") or all_info.get("height") in (None, 0, 0.0, "")):
                    fdj = rec.get("focus_detect_json")
                    if isinstance(fdj, str) and fdj.strip():
                        fdj = json.loads(fdj)
                    if isinstance(fdj, dict):
                        ow = fdj.get("orig_w")
                        oh = fdj.get("orig_h")
                        if ow and oh:
                            all_info["width"] = int(ow)
                            all_info["height"] = int(oh)
            except Exception:
                pass
            if not changed:
                continue
            changed_any = True
            changed += 1
            try:
                for thumb in (self._thumb_by_path.get(key, []) or []):
                    tinfo = None
                    try:
                        tinfo = getattr(thumb, "image_info", None)
                    except Exception:
                        tinfo = None
                    if isinstance(tinfo, dict) and tinfo is not info:
                        try:
                            for k3 in ("bbox", "focus_detect_json", "score", "norm_score", "area_ratio", "position", "label", "rating", "description", "focus_point", "width", "height"):
                                if k3 in info and tinfo.get(k3) != info.get(k3):
                                    tinfo[k3] = info.get(k3)
                        except Exception:
                            pass
                    try:
                        if hasattr(thumb, "icon_overlay") and thumb.icon_overlay is not None:
                            thumb.icon_overlay.set_image_info(tinfo if isinstance(tinfo, dict) else info)
                    except Exception:
                        pass
                    try:
                        thumb.update()
                    except Exception:
                        pass
                    updated_thumbs += 1
            except Exception:
                pass

        if changed_any:
            try:
                if hasattr(self.grid_view, "scroll_area") and self.grid_view.scroll_area is not None:
                    self.grid_view.scroll_area.viewport().update()
            except Exception:
                pass
            try:
                now_ts = float(time.time())
            except Exception:
                now_ts = 0.0
            try:
                last_refresh = float(getattr(self, "_import_cache_bulk_last_ui_refresh_ts", 0.0) or 0.0)
            except Exception:
                last_refresh = 0.0
            if now_ts <= 0.0 or last_refresh <= 0.0 or (now_ts - last_refresh) >= 0.25:
                try:
                    self._import_cache_bulk_last_ui_refresh_ts = float(now_ts)
                except Exception:
                    pass
                try:
                    if hasattr(self.grid_view, "refresh_visible_thumbnails"):
                        self.grid_view.refresh_visible_thumbnails(extra_rows=2)
                except Exception:
                    pass
        _log(
            f"[Import][FocusBulk] batch_result idx={idx} hit={hit} changed={changed} thumbs={updated_thumbs} rows={len(records or {})}",
            force=False,
            level="debug",
        )

    def _reposition_focus_progress_show_btn(self):
        btn = getattr(self, "_focus_progress_show_btn", None)
        if btn is None:
            return
        try:
            rect = self.grid_view.rect()
        except Exception:
            return
        try:
            btn.adjustSize()
        except Exception:
            pass
        try:
            w = int(btn.sizeHint().width())
            h = int(btn.sizeHint().height())
        except Exception:
            w, h = 80, 26
        x = int(max(8, int(rect.width()) - int(w) - 8))
        y = 8
        try:
            btn.setGeometry(int(x), int(y), int(w), int(h))
            btn.raise_()
        except Exception:
            pass

    def _toggle_focus_progress_overlay_from_toolbar(self):
        return

    def _update_focus_progress_toolbar_btn(self):
        return

    def _update_focus_stop_toolbar_btn(self):
        btn = getattr(self, "focus_stop_btn", None)
        if btn is None:
            return
        try:
            running = bool(getattr(self, "_focus_detect_running", False))
        except Exception:
            running = False
        try:
            is_virtual = bool(getattr(self, "is_virtual_mode", False))
        except Exception:
            is_virtual = False
        try:
            btn.setVisible(bool(running and is_virtual))
        except Exception:
            pass
        if not running or not is_virtual:
            return
        try:
            req = bool(getattr(self, "_focus_detect_cancel_requested", False))
        except Exception:
            req = False
        try:
            btn.setEnabled(not req)
        except Exception:
            pass
        try:
            btn.setToolTip("正在停止..." if req else "停止对焦检测")
        except Exception:
            pass

    def _on_focus_stop_clicked(self):
        try:
            if not bool(getattr(self, "_focus_detect_running", False)):
                return
        except Exception:
            return
        try:
            evt = getattr(self, "_focus_detect_cancel_event", None)
            if evt is not None and hasattr(evt, "set"):
                evt.set()
        except Exception:
            pass
        try:
            self._focus_detect_cancel_requested = True
        except Exception:
            pass
        try:
            NotificationManager.instance().show_toast("已请求停止对焦检测")
        except Exception:
            pass
        try:
            self._update_focus_stop_toolbar_btn()
        except Exception:
            pass

    def _apply_focus_progress_mask_styles(self):
        return

    def _reposition_focus_progress_mask(self):
        return

    def _hide_focus_progress_overlay(self):
        return

    def _show_focus_progress_overlay(self):
        return

    def _set_grid_content_visible(self, visible: bool):
        try:
            gv = getattr(self, "grid_view", None)
            if gv is None:
                return
            sa = getattr(gv, "scroll_area", None)
            if sa is not None and hasattr(sa, "setVisible"):
                sa.setVisible(bool(visible))
        except Exception:
            pass

    def _reposition_focus_threshold_panel(self):
        panel = getattr(self, "_focus_threshold_panel", None)
        if panel is None:
            return
        try:
            if panel.parentWidget() is not self.grid_view:
                panel.setParent(self.grid_view)
        except Exception:
            pass
        try:
            rect = self.grid_view.rect()
        except Exception:
            return
        x = 0
        y = 0
        w = max(1, int(rect.width()))
        try:
            h = int(panel.sizeHint().height())
        except Exception:
            h = int(panel.height() or 76)
        try:
            panel.setGeometry(int(x), int(y), int(w), int(h))
            panel.raise_()
        except Exception:
            pass

    def _toggle_focus_threshold_panel(self):
        try:
            cur = bool(getattr(self, "_focus_threshold_panel_open", False))
        except Exception:
            cur = False
        try:
            self._focus_threshold_panel_open = not cur
        except Exception:
            pass
        try:
            self._update_focus_threshold_panel_visibility()
        except Exception:
            pass

    def _start_focus_detect(self, folders: list[str], options: dict):
        def _focus_log(msg: str):
            try:
                from utils.log_manager import LogManager

                LogManager.instance().info(f"[FocusDetectUI] {msg}")
            except Exception:
                pass

        paths = self._collect_paths_for_folders(folders, options.get("file_extensions"))
        if not paths:
            NotificationManager.instance().show_warning("提示", "未找到需要检测的图片")
            return
        _focus_log(f"_start_focus_detect: folders={len(folders or [])} paths={len(paths)} options_keys={list((options or {}).keys())}")
        try:
            auto_switch = bool(self.settings_manager.get("focus_detect/auto_switch_to_scan_mode", True))
        except Exception:
            auto_switch = True
        if auto_switch:
            try:
                if not bool(getattr(self, "is_virtual_mode", False)):
                    QTimer.singleShot(0, lambda: self.mode_switch.setChecked(True))
            except Exception:
                pass
        try:
            self._focus_detect_last_options = dict(options or {})
        except Exception:
            self._focus_detect_last_options = {}
        try:
            self._focus_detect_last_folders = list(folders or [])
        except Exception:
            self._focus_detect_last_folders = []
        try:
            import threading as _threading
            self._focus_detect_cancel_event = _threading.Event()
        except Exception:
            self._focus_detect_cancel_event = None
        try:
            self._focus_detect_cancel_requested = False
        except Exception:
            pass

        self._focus_detect_running = True
        try:
            self._focus_prev_startup_mask_enabled = bool(getattr(self, "_startup_mask_enabled", True))
        except Exception:
            self._focus_prev_startup_mask_enabled = True
        try:
            self._startup_mask_enabled = False
        except Exception:
            pass
        try:
            self._force_hide_startup_mask()
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                self._show_focus_detect_mask()
            else:
                self._hide_focus_detect_mask()
        except Exception:
            pass
        try:
            from utils.system.gpu_utils import GPUScaler
            GPUScaler.set_suspended(True)
        except Exception:
            pass
        try:
            import cv2
            prev_ocl = None
            try:
                if hasattr(cv2, "ocl"):
                    prev_ocl = bool(cv2.ocl.useOpenCL())
                    cv2.ocl.setUseOpenCL(False)
            except Exception:
                prev_ocl = None
            self._focus_prev_cv_opencl = prev_ocl
        except Exception:
            try:
                self._focus_prev_cv_opencl = None
            except Exception:
                pass
        try:
            self._focus_prev_thumb_ui_suspended = bool(getattr(self, "_thumb_ui_suspended", False))
        except Exception:
            self._focus_prev_thumb_ui_suspended = False
        try:
            self._thumb_ui_suspended = True
        except Exception:
            pass
        try:
            if hasattr(self, "_visible_load_timer") and self._visible_load_timer.isActive():
                self._visible_load_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_thumb_build_timer") and self._thumb_build_timer.isActive():
                self._thumb_build_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_cache_warmup_timer") and self._cache_warmup_timer.isActive():
                self._cache_warmup_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_update_timer") and self._update_timer.isActive():
                self._update_timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "thumbnail_loader") and self.thumbnail_loader is not None:
                self.thumbnail_loader.cancel_pending()
        except Exception:
            pass
        try:
            self._update_toolbar_for_mode()
        except Exception:
            pass
        try:
            self._focus_progress_user_hidden = False
        except Exception:
            pass
        try:
            self._update_focus_progress_toolbar_btn()
        except Exception:
            pass
        try:
            self._update_focus_stop_toolbar_btn()
        except Exception:
            pass
        self._focus_progress_operation = "准备中"
        self._focus_progress_done = 0
        self._focus_progress_total = int(len(paths))
        self._focus_progress_start_ts = float(time.time())
        self._focus_exif_base_done = 0
        self._focus_exif_total = 0
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                overlay = getattr(self, "_focus_progress_overlay", None)
                if overlay is not None and hasattr(overlay, "set_progress"):
                    overlay.set_progress(
                        visible=True,
                        current=int(self._focus_progress_done),
                        total=int(self._focus_progress_total),
                        text="当前操作：准备中",
                    )
        except Exception:
            pass
        _focus_log("set _focus_detect_running=True and start timers")
        try:
            if not self._focus_progress_timer.isActive():
                self._focus_progress_timer.start()
        except Exception:
            pass
        try:
            if getattr(self, "_focus_db_poll_timer", None) is not None and not self._focus_db_poll_timer.isActive():
                self._focus_db_poll_timer.start()
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._refresh_focus_progress_ui)
        except Exception:
            pass
        try:
            if getattr(self, "loading_overlay", None):
                self.loading_overlay.hide()
        except Exception:
            pass

        class _FocusProgressBridge(QObject):
            progress = pyqtSignal(str, int, int, float)

        progress_bridge = _FocusProgressBridge()
        try:
            progress_bridge.progress.connect(self._on_focus_progress_update)
        except Exception:
            pass
        try:
            self._focus_progress_bridge = progress_bridge
        except Exception:
            pass

        class _FocusDetectFinishBridge(QObject):
            finished = pyqtSignal(object, object, object, str, bool, bool)

        finish_bridge = _FocusDetectFinishBridge()
        try:
            finish_bridge.finished.connect(lambda p, r, o, e, a, s: self._on_focus_detect_finished(p, r, o, e, a, s))
        except Exception:
            pass
        try:
            self._focus_detect_finish_bridge = finish_bridge
        except Exception:
            pass

        def run():
            results = {}
            err = ""
            append_detect_mode = False
            append_skip_all = False
            run_paths = list(paths or [])
            try:
                _focus_log("worker thread: importing detect_focus_batch_for_import")
                from core.check_cli import detect_focus_batch_for_import

                def progress_cb(op: str, done: int, total: int, start_ts: float):
                    try:
                        progress_bridge.progress.emit(str(op or "对焦检测"), int(done or 0), int(total or 0), float(start_ts or time.time()))
                    except Exception:
                        pass

                call_opts = dict(options or {})
                call_opts["progress_callback"] = progress_cb
                try:
                    ce = getattr(self, "_focus_detect_cancel_event", None)
                    if ce is not None:
                        call_opts["cancel_event"] = ce
                except Exception:
                    pass
                append_detect = call_opts.pop("append_detect", False)
                no_db_write = False
                try:
                    no_db_write = bool((options or {}).get("no_db_write", False))
                except Exception:
                    no_db_write = False
                try:
                    if isinstance(append_detect, str):
                        append_detect = append_detect.strip().lower() in ("1", "true", "yes", "y", "on")
                    elif isinstance(append_detect, (int, float)):
                        append_detect = bool(int(append_detect))
                    else:
                        append_detect = bool(append_detect)
                except Exception:
                    append_detect = False
                allowed = {
                    "enable_burst",
                    "enable_similarity",
                    "use_multiprocess",
                    "use_gpu",
                    "multi_check",
                    "exp_frame_check",
                    "model",
                    "initial_conf",
                    "target_size",
                    "burst_min_count",
                    "burst_fps",
                    "reserve_cpu",
                    "per_file_timeout_sec",
                    "progress_callback",
                }
                try:
                    call_opts = {k: v for k, v in call_opts.items() if k in allowed}
                except Exception:
                    pass
                try:
                    if "per_file_timeout_sec" not in call_opts:
                        call_opts["per_file_timeout_sec"] = 240
                except Exception:
                    pass
                try:
                    safe_opts = {}
                    for k, v in (call_opts or {}).items():
                        if k == "progress_callback":
                            continue
                        ks = str(k or "").lower()
                        if "key" in ks or "api" in ks or "token" in ks:
                            safe_opts[k] = "***"
                        else:
                            safe_opts[k] = v
                    _focus_log(f"worker thread: append_detect={append_detect} call_opts={safe_opts}")
                except Exception:
                    _focus_log(f"worker thread: append_detect={append_detect}")
                append_detect_mode = bool(append_detect)
                if not append_detect:
                    try:
                        progress_bridge.progress.emit("清理缓存", 0, 1, float(time.time()))
                    except Exception:
                        pass
                    try:
                        _focus_log("worker thread: clearing import_cache")
                        self.db.clear_import_cache()
                    except Exception:
                        pass
                    
                    # Also clear all results from import_cache table to ensure fresh start
                    try:
                        self.db.clear_table("import_cache")
                    except Exception:
                        pass

                    try:
                        import shutil
                        from cache.focus_scaled_cache import get_cache_dir

                        cache_dir = get_cache_dir("import_focus")
                        if cache_dir and os.path.isdir(cache_dir):
                            _focus_log(f"worker thread: removing focus_scaled cache dir={cache_dir}")
                            shutil.rmtree(cache_dir, ignore_errors=True)
                    except Exception:
                        pass
                    try:
                        progress_bridge.progress.emit("清理缓存", 1, 1, float(time.time()))
                    except Exception:
                        pass

                run_paths = list(paths or [])
                if append_detect:
                    try:
                        progress_bridge.progress.emit("检查已检测文件", 0, 1, float(time.time()))
                    except Exception:
                        pass
                    try:
                        _focus_log("worker thread: querying existing paths from import_cache")
                        def _norm_key(p: str) -> str:
                            try:
                                p_db = self.db._normalize_file_path_for_db(str(p))
                            except Exception:
                                p_db = str(p)
                            try:
                                return str(self.db._norm_path_key(p_db))
                            except Exception:
                                return str(p_db)

                        def _is_done(rec: dict) -> bool:
                            try:
                                if not isinstance(rec, dict):
                                    return False
                                fdj = rec.get("focus_detect_json")
                                if isinstance(fdj, str) and fdj.strip():
                                    return True
                                desc = rec.get("description")
                                if isinstance(desc, str) and "focus_detect" in desc:
                                    return True
                                score = rec.get("score")
                                norm_score = rec.get("norm_score")
                                if score is None and norm_score is None:
                                    return False
                                if rec.get("bbox") is not None or rec.get("focus_point") is not None:
                                    return True
                                pos = rec.get("position")
                                if pos not in (None, ""):
                                    return True
                                if rec.get("area_ratio") is not None:
                                    return True
                                return True
                            except Exception:
                                return False

                        db_paths = []
                        for p in (run_paths or []):
                            try:
                                db_paths.append(self.db._normalize_file_path_for_db(str(p)))
                            except Exception:
                                db_paths.append(str(p))
                        records = self.db.get_results_by_paths(db_paths, table_name="import_cache")
                        done = set()
                        if isinstance(records, dict) and records:
                            for p, rec in records.items():
                                if _is_done(rec):
                                    try:
                                        done.add(_norm_key(str(p)))
                                    except Exception:
                                        done.add(str(p))
                                    try:
                                        fp = rec.get("file_path") or rec.get("path")
                                        if fp:
                                            done.add(_norm_key(str(fp)))
                                    except Exception:
                                        pass
                        if done:
                            run_paths = [p for p in run_paths if _norm_key(str(p)) not in done]
                        _focus_log(f"worker thread: append resume skip_done={len(done)} remaining={len(run_paths)}")
                    except Exception:
                        pass
                    try:
                        progress_bridge.progress.emit("检查已检测文件", 1, 1, float(time.time()))
                    except Exception:
                        pass

                if not run_paths:
                    append_skip_all = bool(append_detect)
                    results = {"results": {}, "options": call_opts}
                else:
                    try:
                        progress_bridge.progress.emit("对焦检测", 0, int(len(run_paths)), float(time.time()))
                    except Exception:
                        pass
                    _focus_log(f"worker thread: calling detect_focus_batch_for_import(paths={len(run_paths)})")
                    results = detect_focus_batch_for_import(run_paths, **call_opts)
                    _focus_log("worker thread: detect_focus_batch_for_import returned")
            except Exception as e:
                err = str(e)
                results = {}
                _focus_log(f"worker thread: exception: {err}")
            try:
                finish_bridge.finished.emit(list(run_paths or []), results, options, err, bool(append_detect_mode), bool(append_skip_all))
            except Exception:
                pass

        Thread(target=run, daemon=True).start()
        _focus_log("worker thread started")

    def _on_focus_detect_finished(self, paths: list[str], results: dict, options: dict, err: str, append_detect: bool = False, skipped_all: bool = False):
        try:
            if getattr(self, "loading_overlay", None):
                self.loading_overlay.hide()
        except Exception:
            pass
        try:
            self._hide_focus_detect_mask()
        except Exception:
            pass
        if err:
            self._focus_detect_running = False
            try:
                self._focus_detect_cancel_requested = False
                self._focus_detect_cancel_event = None
            except Exception:
                pass
            try:
                self._focus_progress_operation = ""
                self._focus_progress_done = 0
                self._focus_progress_total = 0
                self._focus_eta_last_op = ""
                self._focus_eta_last_total = 0
                self._focus_eta_last_done = 0
                self._focus_eta_seconds = None
                self._focus_eta_last_update_ts = 0.0
                if getattr(self, "_focus_progress_timer", None) is not None and self._focus_progress_timer.isActive():
                    self._focus_progress_timer.stop()
                if getattr(self, "_focus_db_poll_timer", None) is not None and self._focus_db_poll_timer.isActive():
                    self._focus_db_poll_timer.stop()
                try:
                    overlay = getattr(self, "_focus_progress_overlay", None)
                    if overlay is not None and hasattr(overlay, "set_progress"):
                        overlay.set_progress(visible=False)
                    if overlay is not None and hasattr(overlay, "hide"):
                        overlay.hide()
                except Exception:
                    pass
                QTimer.singleShot(0, self._refresh_focus_progress_ui)
            except Exception:
                pass
            try:
                self._update_toolbar_for_mode()
            except Exception:
                pass
            NotificationManager.instance().show_warning("错误", f"对焦检测失败: {err}")
            return

        if bool(append_detect) and bool(skipped_all):
            # Even if skipped all because all were detected, we should still reload the view to show the results!
            # The previous logic just returned, leaving the user with an empty or stale view.
            # We should proceed to reload the view.
            
            # Restore UI state first
            self._focus_detect_running = False
            try:
                self._focus_detect_cancel_requested = False
                self._focus_detect_cancel_event = None
            except Exception:
                pass
            
            # Hide progress overlay
            try:
                self._focus_progress_operation = ""
                self._focus_progress_done = 0
                self._focus_progress_total = 0
                if getattr(self, "_focus_progress_timer", None) is not None and self._focus_progress_timer.isActive():
                    self._focus_progress_timer.stop()
                if getattr(self, "_focus_db_poll_timer", None) is not None and self._focus_db_poll_timer.isActive():
                    self._focus_db_poll_timer.stop()
                try:
                    overlay = getattr(self, "_focus_progress_overlay", None)
                    if overlay is not None and hasattr(overlay, "hide"):
                        overlay.hide()
                except Exception:
                    pass
                self._refresh_focus_progress_ui()
            except Exception:
                pass
            
            try:
                self._update_toolbar_for_mode()
            except Exception:
                pass
            
            NotificationManager.instance().show_toast("追加检测：所有文件已检测过，直接加载结果")
            
            # Proceed to reload view logic (similar to normal finish)
            try:
                if getattr(self, "loading_overlay", None):
                    self.loading_overlay.hide()
            except Exception:
                pass
            try:
                self._pending_virtual_focus_reload = True
                if bool(getattr(self, "is_virtual_mode", False)):
                    self._build_focus_detect_virtual_folders()
                    QTimer.singleShot(0, self._reload_virtual_focus_detect_view)
            except Exception:
                pass
            return

        try:
            if getattr(self, "loading_overlay", None):
                self.loading_overlay.hide()
        except Exception:
            pass

        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                self._build_focus_detect_virtual_folders()
        except Exception:
            pass
        try:
            from utils.log_manager import LogManager

            res_map = (results or {}).get("results") if isinstance(results, dict) else None
            if isinstance(res_map, dict):
                counts = {"Sharp": 0, "Normal": 0, "Blurry": 0, "Minimal": 0, "ExpFrame": 0, "NoBird": 0}
                for p, r in res_map.items():
                    if not isinstance(r, dict):
                        continue
                    try:
                        st = str(r.get("status") or r.get("focus_status") or "")
                    except Exception:
                        st = ""
                    if st not in counts:
                        st = "NoBird"
                    counts[st] = int(counts.get(st, 0) or 0) + 1
                LogManager.instance().info(f"对焦检测完成: 处理={len(res_map)} 统计={counts} 追加={bool(append_detect)}")
        except Exception:
            pass

        def _apply_post_action(done_paths: list[str], results_by_src: dict) -> tuple[list[str], str, dict]:
            action = ""
            dest_root = ""
            try:
                action = str((options or {}).get("post_action") or "").strip().lower()
            except Exception:
                action = ""
            try:
                dest_root = str((options or {}).get("post_dir") or "").strip()
            except Exception:
                dest_root = ""
            if action not in ("copy", "move", "copy_by_status", "move_by_status", "copy_by_status_to_source", "move_by_status_to_source"):
                try:
                    self._focus_detect_virtual_roots = None
                except Exception:
                    pass
                try:
                    self.settings_manager.set("focus_detect/virtual_roots", [])
                    self.settings_manager.sync()
                except Exception:
                    pass
                return list(done_paths or []), "", dict(results_by_src or {})

            is_to_source = action.endswith("_to_source")
            if (not dest_root) and (not is_to_source):
                try:
                    self._focus_detect_virtual_roots = None
                except Exception:
                    pass
                try:
                    self.settings_manager.set("focus_detect/virtual_roots", [])
                    self.settings_manager.sync()
                except Exception:
                    pass
                return list(done_paths or []), "", dict(results_by_src or {})
            
            if not is_to_source:
                try:
                    dest_root = os.path.abspath(dest_root)
                except Exception:
                    dest_root = str(dest_root)
                try:
                    if not os.path.isdir(dest_root):
                        try:
                            os.makedirs(dest_root, exist_ok=True)
                        except Exception:
                            pass
                    if not os.path.isdir(dest_root):
                        try:
                            self._focus_detect_virtual_roots = None
                        except Exception:
                            pass
                        return list(done_paths or []), "", dict(results_by_src or {})
                except Exception:
                    try:
                        self._focus_detect_virtual_roots = None
                    except Exception:
                        pass
                    return list(done_paths or []), "", dict(results_by_src or {})

            if action in ("move", "move_by_status") and not is_to_source:
                try:
                    self._focus_detect_virtual_roots = [str(dest_root)]
                except Exception:
                    pass
                try:
                    self.settings_manager.set("focus_detect/virtual_roots", [str(dest_root)])
                    self.settings_manager.sync()
                except Exception:
                    pass
            else:
                try:
                    self._focus_detect_virtual_roots = None
                except Exception:
                    pass
                try:
                    self.settings_manager.set("focus_detect/virtual_roots", [])
                    self.settings_manager.sync()
                except Exception:
                    pass
            no_db_write = False
            try:
                no_db_write = bool((options or {}).get("no_db_write", False))
            except Exception:
                no_db_write = False

            thresholds = {}
            try:
                thresholds = self._get_focus_detect_ui_thresholds()
            except Exception:
                thresholds = {}

            status_folder = {
                "Sharp": "锐利",
                "Normal": "普通",
                "Blurry": "虚焦",
                "Minimal": "极小",
                "ExpFrame": "爆框",
                "NoBird": "无鸟",
            }

            def _status_for_result(res: dict) -> str:
                if not isinstance(res, dict):
                    return "NoBird"
                try:
                    import json as _json
                    payload = dict(res)
                    try:
                        payload.pop("path", None)
                    except Exception:
                        pass
                    pseudo = {"focus_detect_json": _json.dumps(payload, ensure_ascii=False, default=str)}
                    return str(self._compute_focus_status_for_item(pseudo, thresholds) or "NoBird")
                except Exception:
                    return "NoBird"

            try:
                folders = list(getattr(self, "_focus_detect_last_folders", []) or [])
            except Exception:
                folders = []
            auto_base_dir = None
            if action in ("copy_by_status", "move_by_status", "copy_by_status_to_source", "move_by_status_to_source"):
                try:
                    cp = os.path.commonpath([str(x) for x in (done_paths or []) if x])
                except Exception:
                    cp = ""
                try:
                    if cp and os.path.isfile(cp):
                        cp = os.path.dirname(cp)
                except Exception:
                    pass
                try:
                    if cp and os.path.isdir(cp):
                        base_name = os.path.basename(cp)
                        if base_name in ("连拍",):
                            cp = os.path.dirname(cp)
                        auto_base_dir = str(cp)
                except Exception:
                    auto_base_dir = None

            def _norm(p: str) -> str:
                try:
                    return os.path.normcase(os.path.normpath(str(p)))
                except Exception:
                    return str(p)

            def _pick_base(src: str) -> str | None:
                try:
                    abd = str(auto_base_dir or "")
                except Exception:
                    abd = ""
                if abd:
                    try:
                        srcn0 = _norm(src)
                        abdn0 = _norm(abd)
                        if srcn0.startswith(abdn0 + os.sep):
                            return abd
                    except Exception:
                        pass
                srcn = _norm(src)
                best = None
                best_len = -1
                for f in (folders or []):
                    if not f:
                        continue
                    fn = _norm(f)
                    prefix = fn + os.sep
                    try:
                        ok = srcn.startswith(prefix)
                    except Exception:
                        ok = False
                    if not ok:
                        continue
                    if len(prefix) > best_len:
                        best = str(f)
                        best_len = len(prefix)
                return best

            def _dedupe_dest(path0: str) -> str:
                if not path0:
                    return path0
                if not os.path.exists(path0):
                    return path0
                base, ext = os.path.splitext(path0)
                for i in range(1, 1000):
                    cand = f"{base} ({i}){ext}"
                    if not os.path.exists(cand):
                        return cand
                return path0

            import shutil

            post_paths: list[str] = []
            post_results: dict = {}
            ok_count = 0
            fail_count = 0
            last_err = ""
            failed_samples: list[str] = []

            def _copy_or_move(src0: str, dest0: str) -> bool:
                nonlocal last_err
                delays = (0.0, 0.25, 0.6, 1.2)
                for d in delays:
                    if d > 0:
                        try:
                            time.sleep(float(d))
                        except Exception:
                            pass
                    try:
                        if action in ("copy", "copy_by_status", "copy_by_status_to_source"):
                            from utils.file.file_utils import copy2_with_sidecar
                            copy2_with_sidecar(src0, dest0)
                            return True
                        from utils.file.file_utils import move_with_sidecar
                        move_with_sidecar(src0, dest0)
                        return True
                    except Exception as e:
                        last_err = str(e)
                        try:
                            if action in ("move", "move_by_status", "move_by_status_to_source"):
                                try:
                                    from utils.file.file_utils import copy2_with_sidecar, delete_with_sidecar
                                    copy2_with_sidecar(src0, dest0)
                                    delete_with_sidecar(src0, prefer_trash=False)
                                except Exception:
                                    pass
                                if os.path.isfile(dest0):
                                    return True
                        except Exception as e2:
                            last_err = str(e2)
                        continue
                return False

            for src in (done_paths or []):
                src = str(src or "")
                if not src:
                    continue
                try:
                    if not os.path.isfile(src):
                        fail_count += 1
                        if len(failed_samples) < 8:
                            failed_samples.append(src)
                        continue
                except Exception:
                    fail_count += 1
                    if len(failed_samples) < 8:
                        failed_samples.append(src)
                    continue
                src_meta = None
                try:
                    from cache.focus_scaled_cache import try_load_meta
                    focus_target = 640
                    try:
                        focus_target = int(self.settings_manager.get("focus_detect/target_size", 640) or 640)
                    except Exception:
                        focus_target = 640
                    src_meta = try_load_meta(str(src), int(focus_target), scope="import_focus")
                except Exception:
                    src_meta = None

                base = _pick_base(src)
                try:
                    rel = os.path.relpath(src, base) if base else os.path.basename(src)
                except Exception:
                    rel = os.path.basename(src)
                
                current_dest_root = dest_root
                if is_to_source:
                    try:
                        current_dest_root = os.path.dirname(src)
                    except Exception:
                        current_dest_root = dest_root

                if action in ("copy_by_status", "move_by_status", "copy_by_status_to_source", "move_by_status_to_source"):
                    st = _status_for_result((results_by_src or {}).get(src))
                    if is_to_source:
                         dest = os.path.normpath(os.path.join(current_dest_root, status_folder.get(st, st), os.path.basename(src)))
                    else:
                         dest = os.path.normpath(os.path.join(current_dest_root, status_folder.get(st, st), rel))
                else:
                    dest = os.path.normpath(os.path.join(current_dest_root, rel))

                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                except Exception:
                    fail_count += 1
                    continue
                dest = _dedupe_dest(dest)
                try:
                    ok = _copy_or_move(src, dest)
                    if not ok:
                        raise RuntimeError(last_err or "move_failed")
                    ok_count += 1
                    post_paths.append(dest)
                    try:
                        if (not no_db_write) and action in ("move", "move_by_status", "move_by_status_to_source"):
                            self.db.update_file_path(src, dest, os.path.basename(dest), table_name="import_cache")
                    except Exception:
                        pass
                    try:
                        for lst_name in ("image_files", "_all_image_files"):
                            lst = getattr(self, lst_name, None)
                            if not isinstance(lst, list):
                                continue
                            for it in lst:
                                if not isinstance(it, dict):
                                    continue
                                if str(it.get("path") or "") == str(src):
                                    it["path"] = str(dest)
                                    it["name"] = os.path.basename(str(dest))
                    except Exception:
                        pass
                    try:
                        if str(getattr(self, "current_preview_path", "") or "") == str(src):
                            self.current_preview_path = str(dest)
                    except Exception:
                        pass
                    try:
                        rr = (results_by_src or {}).get(src)
                        if isinstance(rr, dict):
                            rr = dict(rr)
                            if isinstance(src_meta, dict):
                                try:
                                    if rr.get("orig_w") in (None, "", 0, 0.0) and src_meta.get("orig_w") not in (None, "", 0, 0.0):
                                        rr["orig_w"] = src_meta.get("orig_w")
                                except Exception:
                                    pass
                                try:
                                    if rr.get("orig_h") in (None, "", 0, 0.0) and src_meta.get("orig_h") not in (None, "", 0, 0.0):
                                        rr["orig_h"] = src_meta.get("orig_h")
                                except Exception:
                                    pass
                            rr["path"] = dest
                            post_results[dest] = rr
                    except Exception:
                        pass
                except Exception as e:
                    last_err = str(e)
                    fail_count += 1
                    if len(failed_samples) < 8:
                        failed_samples.append(src)
                    try:
                        rr = (results_by_src or {}).get(src)
                        if isinstance(rr, dict):
                            post_paths.append(src)
                            rr2 = dict(rr)
                            if isinstance(src_meta, dict):
                                try:
                                    if rr2.get("orig_w") in (None, "", 0, 0.0) and src_meta.get("orig_w") not in (None, "", 0, 0.0):
                                        rr2["orig_w"] = src_meta.get("orig_w")
                                except Exception:
                                    pass
                                try:
                                    if rr2.get("orig_h") in (None, "", 0, 0.0) and src_meta.get("orig_h") not in (None, "", 0, 0.0):
                                        rr2["orig_h"] = src_meta.get("orig_h")
                                except Exception:
                                    pass
                            post_results[src] = rr2
                    except Exception:
                        pass
                    continue

            warn = ""
            if ok_count > 0 or fail_count > 0:
                op = "复制" if action in ("copy", "copy_by_status", "copy_by_status_to_source") else "剪切"
                if fail_count > 0:
                    sample = ""
                    try:
                        if failed_samples:
                            sample = "；示例：" + " | ".join([os.path.basename(x) for x in failed_samples[:5]])
                    except Exception:
                        sample = ""
                    warn = f"对焦检测后文件{op}：成功 {ok_count}，失败 {fail_count}{sample}" + (f"（最后错误：{last_err}）" if last_err else "")
                else:
                    warn = f"对焦检测后文件{op}：成功 {ok_count}"
            if not post_results:
                try:
                    post_results = dict(results_by_src or {})
                except Exception:
                    post_results = {}
            return post_paths if post_paths else list(done_paths or []), warn, post_results

        class _FocusDetectPostBridge(QObject):
            done = pyqtSignal(str, str)

        post_bridge = _FocusDetectPostBridge()
        try:
            post_bridge.done.connect(lambda e, w: self._on_focus_detect_saved(e, w))
        except Exception:
            pass
        try:
            self._focus_detect_post_bridge = post_bridge
        except Exception:
            pass

        def run_post():
            t0 = 0.0
            try:
                t0 = float(time.time())
            except Exception:
                t0 = 0.0
            done_evt = None
            try:
                import threading as _threading
                done_evt = _threading.Event()
            except Exception:
                done_evt = None

            def watchdog():
                try:
                    time.sleep(60.0)
                except Exception:
                    return
                try:
                    if done_evt is not None and done_evt.is_set():
                        return
                except Exception:
                    pass
                dump_path = ""
                try:
                    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                    dump_path = os.path.join(os.getcwd(), "cache", "logs", f"focus_detect_hang_{ts}.log")
                    os.makedirs(os.path.dirname(dump_path), exist_ok=True)
                    import faulthandler
                    with open(dump_path, "w", encoding="utf-8") as f:
                        faulthandler.dump_traceback(file=f, all_threads=True)
                except Exception:
                    dump_path = ""
                try:
                    from utils.log_manager import LogManager
                    if dump_path:
                        LogManager.instance().warning(f"[FocusDetectUI] run_post 超过60秒未结束，已导出线程堆栈: {dump_path}")
                    else:
                        LogManager.instance().warning("[FocusDetectUI] run_post 超过60秒未结束，导出线程堆栈失败")
                except Exception:
                    pass

            try:
                Thread(target=watchdog, daemon=True, name="FocusDetectPostWatchdog").start()
            except Exception:
                pass

            post_err = ""
            post_warn = ""
            post_paths = list(paths or [])
            post_results = {}
            try:
                try:
                    raw = results.get("results") if isinstance(results, dict) else None
                except Exception:
                    raw = None
                results_by_src = raw if isinstance(raw, dict) else {}
                post_paths, post_warn, post_results = _apply_post_action(post_paths, results_by_src)
            except Exception as e:
                post_err = str(e)
            try:
                self._save_focus_detect_results(post_paths, {"results": post_results}, options)
            except Exception as e:
                post_err = str(e)
            try:
                try:
                    if done_evt is not None:
                        done_evt.set()
                except Exception:
                    pass
                try:
                    from utils.log_manager import LogManager
                    if t0:
                        LogManager.instance().info(f"[FocusDetectUI] run_post done elapsed_s={float(time.time()-t0):.2f}")
                except Exception:
                    pass
                post_bridge.done.emit(str(post_err or ""), str(post_warn or ""))
            except Exception:
                pass

        try:
            action = str((options or {}).get("post_action") or "").strip().lower()
        except Exception:
            action = ""
        if action in ("copy", "move", "copy_by_status", "move_by_status"):
            try:
                op = "复制" if action in ("copy", "copy_by_status") else "剪切"
                dest_root = str((options or {}).get("post_dir") or "").strip()
            except Exception:
                op = "处理"
                dest_root = ""
            try:
                if getattr(self, "loading_overlay", None) is not None and hasattr(self.loading_overlay, "show_loading"):
                    QTimer.singleShot(
                        0,
                        lambda: self.loading_overlay.show_loading(
                            "正在处理文件...",
                            (f"正在{op}到目标目录：{dest_root}" if dest_root else f"正在{op}到目标目录..."),
                        ),
                    )
            except Exception:
                pass
        Thread(target=run_post, daemon=True).start()

    def _on_focus_detect_saved(self, err: str, warn: str = ""):
        try:
            if getattr(self, "loading_overlay", None):
                self.loading_overlay.hide()
        except Exception:
            pass
        try:
            self._startup_mask_enabled = bool(getattr(self, "_focus_prev_startup_mask_enabled", True))
        except Exception:
            try:
                self._startup_mask_enabled = True
            except Exception:
                pass
        try:
            self._force_hide_startup_mask()
        except Exception:
            pass
        try:
            self._hide_focus_detect_mask()
        except Exception:
            pass
        self._focus_detect_running = False
        try:
            self._focus_detect_cancel_requested = False
            self._focus_detect_cancel_event = None
        except Exception:
            pass
        try:
            from utils.system.gpu_utils import GPUScaler
            GPUScaler.set_suspended(False)
        except Exception:
            pass
        try:
            import cv2
            prev_ocl = getattr(self, "_focus_prev_cv_opencl", None)
            if prev_ocl is not None and hasattr(cv2, "ocl"):
                cv2.ocl.setUseOpenCL(bool(prev_ocl))
        except Exception:
            pass
        try:
            self._thumb_ui_suspended = False
        except Exception:
            try:
                self._thumb_ui_suspended = False
            except Exception:
                pass
        try:
            self._schedule_visible_load(immediate=True)
        except Exception:
            pass
        try:
            if hasattr(self, "_update_timer") and self._update_timer is not None and not self._update_timer.isActive():
                self._update_timer.start()
        except Exception:
            pass
        try:
            self._update_toolbar_for_mode()
        except Exception:
            pass
        try:
            self._focus_progress_operation = ""
            self._focus_progress_done = 0
            self._focus_progress_total = 0
            self._focus_exif_base_done = 0
            self._focus_exif_total = 0
            self._focus_eta_last_op = ""
            self._focus_eta_last_total = 0
            self._focus_eta_last_done = 0
            self._focus_eta_seconds = None
            self._focus_eta_last_update_ts = 0.0
            if getattr(self, "_focus_progress_timer", None) is not None and self._focus_progress_timer.isActive():
                self._focus_progress_timer.stop()
            if getattr(self, "_focus_db_poll_timer", None) is not None and self._focus_db_poll_timer.isActive():
                self._focus_db_poll_timer.stop()
            try:
                overlay = getattr(self, "_focus_progress_overlay", None)
                if overlay is not None and hasattr(overlay, "set_progress"):
                    overlay.set_progress(visible=False)
                if overlay is not None and hasattr(overlay, "hide"):
                    overlay.hide()
            except Exception:
                pass
            self._refresh_focus_progress_ui()
        except Exception:
            pass
        if err:
            NotificationManager.instance().show_warning("错误", f"保存检测结果失败: {err}")
            return
        NotificationManager.instance().show_toast("对焦检测完成")
        if warn:
            try:
                NotificationManager.instance().show_toast(str(warn))
            except Exception:
                pass
        try:
            QTimer.singleShot(0, lambda: self._schedule_focus_point_backfill(getattr(self, "image_files", []) or []))
        except Exception:
            pass
        try:
            QTimer.singleShot(250, lambda: self._schedule_focus_point_backfill(getattr(self, "image_files", []) or []))
        except Exception:
            pass
        try:
            QTimer.singleShot(0, lambda: self._start_focus_point_overlay_autorefresh(rounds=16, interval_ms=350))
        except Exception:
            pass
        try:
            self._pending_virtual_focus_reload = True
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                self._build_focus_detect_virtual_folders()
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                QTimer.singleShot(0, self._reload_virtual_focus_detect_view)
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                QTimer.singleShot(600, self._build_focus_detect_virtual_folders)
                QTimer.singleShot(800, self._reload_virtual_focus_detect_view)
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                QTimer.singleShot(0, self._backfill_visible_thumbnails_from_import_cache)
        except Exception:
            pass
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                QTimer.singleShot(0, self._refresh_current_preview_overlays_from_import_cache)
        except Exception:
            pass
        try:
            action = ""
            try:
                action = str((getattr(self, "_focus_detect_last_options", {}) or {}).get("finish_action") or "none").strip().lower()
            except Exception:
                action = "none"
            if action == "quit_app":
                from PyQt6.QtWidgets import QApplication

                QTimer.singleShot(200, QApplication.instance().quit)
            elif action == "shutdown_pc":
                import subprocess

                subprocess.Popen(["shutdown", "/s", "/t", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif action == "run_script":
                script_path = ""
                try:
                    script_path = str((getattr(self, "_focus_detect_last_options", {}) or {}).get("finish_script") or "").strip()
                except Exception:
                    script_path = ""
                if not script_path:
                    try:
                        NotificationManager.instance().show_warning("提示", "未设置检测结束脚本")
                    except Exception:
                        pass
                elif not os.path.isfile(script_path):
                    try:
                        NotificationManager.instance().show_warning("提示", f"脚本不存在: {script_path}")
                    except Exception:
                        pass
                else:
                    try:
                        import sys
                        import subprocess
                        from utils.log_manager import LogManager

                        env = None
                        try:
                            env = dict(os.environ or {})
                            opts = getattr(self, "_focus_detect_last_options", {}) or {}
                            env["BPM_FOCUS_POST_ACTION"] = str(opts.get("post_action") or "")
                            env["BPM_FOCUS_POST_DIR"] = str(opts.get("post_dir") or "")
                        except Exception:
                            env = None
                        try:
                            if os.name == "nt":
                                py_exe = ""
                                try:
                                    py_exe = str(getattr(sys, "_base_executable", "") or "").strip()
                                except Exception:
                                    py_exe = ""
                                if not py_exe:
                                    try:
                                        py_exe = str(sys.executable or "").strip()
                                    except Exception:
                                        py_exe = ""
                                try:
                                    if py_exe and (not os.path.isfile(py_exe)):
                                        py_exe = ""
                                except Exception:
                                    py_exe = ""
                                if not py_exe:
                                    try:
                                        import shutil
                                        py_exe = str(shutil.which("python.exe") or shutil.which("python") or "").strip()
                                    except Exception:
                                        py_exe = ""
                                if not py_exe:
                                    try:
                                        import shutil
                                        py_exe = str(shutil.which("py.exe") or shutil.which("py") or "").strip()
                                    except Exception:
                                        py_exe = ""
                                if not py_exe:
                                    py_exe = "python"

                                cmd_line = f'cmd.exe /k ""{py_exe}" "{str(script_path)}""'
                                subprocess.Popen(
                                    cmd_line,
                                    cwd=os.path.dirname(script_path) or os.getcwd(),
                                    env=env,
                                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                                )
                            else:
                                subprocess.Popen(
                                    [str(sys.executable), str(script_path)],
                                    cwd=os.path.dirname(script_path) or os.getcwd(),
                                    env=env,
                                )
                            LogManager.instance().info(f"[FocusDetectUI] finish script started: {script_path}")
                        except Exception:
                            pass
                        try:
                            NotificationManager.instance().show_toast(f"已启动脚本：{os.path.basename(script_path)}")
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            NotificationManager.instance().show_warning("错误", f"启动脚本失败: {e}")
                        except Exception:
                            pass
        except Exception:
            pass

    def _start_build_focus_detect_virtual_folders(self):
        try:
            from PyQt6.QtCore import Qt, QTimer
        except Exception:
            return
        tree = getattr(self.folder_panel, "folder_tree", None) if hasattr(self, "folder_panel") else None
        if tree is None:
            return
        current_role = None
        try:
            it0 = tree.currentItem()
            current_role = it0.data(0, Qt.ItemDataRole.UserRole) if it0 is not None else None
        except Exception:
            current_role = None
        try:
            self._focus_virtual_build_seq = int(getattr(self, "_focus_virtual_build_seq", 0) or 0) + 1
        except Exception:
            self._focus_virtual_build_seq = 1
        seq = int(getattr(self, "_focus_virtual_build_seq", 0) or 0)

        def run_build():
            t0 = time.time()
            folders = []
            try:
                folders = list(getattr(self, "_focus_detect_last_folders", []) or [])
            except Exception:
                folders = []
            try:
                vr = getattr(self, "_focus_detect_virtual_roots", None)
                if isinstance(vr, (list, tuple)) and vr:
                    folders = [str(x) for x in vr if x]
            except Exception:
                pass
            if not folders:
                try:
                    vr = self.settings_manager.get("focus_detect/virtual_roots", []) or []
                    if isinstance(vr, (list, tuple)) and vr:
                        folders = [str(x) for x in vr if x]
                except Exception:
                    pass
            if not folders:
                try:
                    folders = self.settings_manager.get("focus_detect/folders", []) or []
                    folders = [str(x) for x in folders if x]
                    self._focus_detect_last_folders = list(folders)
                except Exception:
                    folders = []
            if not folders:
                try:
                    folders = self.db.list_import_cache_recent_folders(limit_rows=5000, max_folders=50)
                    folders = [str(x) for x in (folders or []) if x]
                    self._focus_detect_last_folders = list(folders)
                except Exception:
                    folders = []
            norm_seen = set()
            deduped = []
            for f in (folders or []):
                try:
                    fp = str(f or "")
                except Exception:
                    continue
                if not fp:
                    continue
                try:
                    if os.path.isfile(fp):
                        fp = os.path.dirname(fp)
                except Exception:
                    pass
                if not fp:
                    continue
                try:
                    k = os.path.normcase(os.path.normpath(fp))
                except Exception:
                    k = fp
                if k in norm_seen:
                    continue
                norm_seen.add(k)
                deduped.append(fp)
            folders = deduped

            thresholds = {}
            try:
                thresholds = self._get_focus_detect_ui_thresholds()
            except Exception:
                thresholds = {}

            def _burst_first_file(row: dict) -> str:
                try:
                    fd = self._extract_focus_detect_info(row)
                except Exception:
                    fd = {}
                if not isinstance(fd, dict):
                    return ""
                try:
                    v = str(fd.get("burst_first_file") or "")
                except Exception:
                    v = ""
                return v.strip()

            items = []
            for fp in (folders or []):
                counts = {"Sharp": 0, "Normal": 0, "Blurry": 0, "Minimal": 0, "ExpFrame": 0, "NoBird": 0}
                total = 0
                burst_groups: dict[str, dict] = {}
                try:
                    rows = self.db.list_import_cache_by_folder(fp, limit=100000)
                except Exception:
                    rows = []
                for r in (rows or []):
                    if not isinstance(r, dict):
                        continue
                    total += 1
                    try:
                        st = self._compute_focus_status_for_item(r, thresholds)
                    except Exception:
                        st = "NoBird"
                    if st not in counts:
                        st = "NoBird"
                    counts[st] = int(counts.get(st, 0) or 0) + 1
                    try:
                        bfirst = _burst_first_file(r)
                    except Exception:
                        bfirst = ""
                    if bfirst:
                        g = burst_groups.get(bfirst)
                        if g is None:
                            g = {"counts": {"Sharp": 0, "Normal": 0, "Blurry": 0, "Minimal": 0, "ExpFrame": 0, "NoBird": 0}, "total": 0}
                            burst_groups[bfirst] = g
                        g["total"] = int(g.get("total", 0) or 0) + 1
                        g["counts"][st] = int(g["counts"].get(st, 0) or 0) + 1
                items.append(
                    {
                        "folder": fp,
                        "name": os.path.basename(fp) or fp,
                        "total": int(total),
                        "counts": counts,
                        "burst_groups": burst_groups,
                    }
                )
            try:
                from utils.log_manager import LogManager
                LogManager.instance().info(f"[FocusDetectUI] virtual_tree_build done folders={len(items)} elapsed_s={float(time.time()-t0):.2f}")
            except Exception:
                pass
            try:
                if int(getattr(self, "_focus_virtual_build_seq", 0) or 0) != int(seq):
                    return
            except Exception:
                return
            try:
                QTimer.singleShot(0, lambda: self._apply_focus_detect_virtual_folders_tree(items, current_role))
            except Exception:
                pass

        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[FocusDetectUI] virtual_tree_build start seq={seq}")
        except Exception:
            pass
        Thread(target=run_build, daemon=True, name=f"FocusVirtualBuild-{seq}").start()

    def _apply_focus_detect_virtual_folders_tree(self, items: list[dict], current_role=None):
        try:
            from PyQt6.QtWidgets import QTreeWidgetItem
            from PyQt6.QtCore import Qt
            import urllib.parse
        except Exception:
            return
        tree = getattr(self.folder_panel, "folder_tree", None) if hasattr(self, "folder_panel") else None
        if tree is None:
            return
        try:
            for i in range(tree.topLevelItemCount() - 1, -1, -1):
                it = tree.topLevelItem(i)
                if it is None:
                    continue
                p = it.data(0, Qt.ItemDataRole.UserRole)
                if p == "virtual://focus_detect_root":
                    tree.takeTopLevelItem(i)
        except Exception:
            pass
        root = QTreeWidgetItem(["对焦检测"])
        root.setData(0, Qt.ItemDataRole.UserRole, "virtual://focus_detect_root")
        try:
            root.setExpanded(True)
        except Exception:
            pass
        tree.insertTopLevelItem(0, root)
        if not items:
            child = QTreeWidgetItem(["（暂无记录）"])
            child.setData(0, Qt.ItemDataRole.UserRole, "__placeholder__")
            root.addChild(child)
        else:
            status_folder = {
                "All": "全部",
                "Sharp": "锐利",
                "Normal": "普通",
                "Blurry": "虚焦",
                "Minimal": "极小",
                "ExpFrame": "爆框",
                "NoBird": "无鸟",
            }
            status_order = ["All", "Sharp", "Normal", "Blurry", "Minimal", "ExpFrame", "NoBird"]
            for it0 in (items or []):
                try:
                    fp = str(it0.get("folder") or "")
                except Exception:
                    continue
                if not fp:
                    continue
                try:
                    name = str(it0.get("name") or os.path.basename(fp) or fp)
                except Exception:
                    name = os.path.basename(fp) or fp
                try:
                    total = int(it0.get("total", 0) or 0)
                except Exception:
                    total = 0
                counts = it0.get("counts") if isinstance(it0.get("counts"), dict) else {}
                burst_groups = it0.get("burst_groups") if isinstance(it0.get("burst_groups"), dict) else {}

                folder_item = QTreeWidgetItem([f"{name}（{total}）"])
                folder_item.setToolTip(0, fp)
                folder_item.setData(0, Qt.ItemDataRole.UserRole, f"virtual://focus_detect?folder={urllib.parse.quote(fp)}&status=All")
                root.addChild(folder_item)

                for st in status_order:
                    if st == "All":
                        cnt = total
                    else:
                        try:
                            cnt = int(counts.get(st, 0) or 0)
                        except Exception:
                            cnt = 0
                    s_it = QTreeWidgetItem([f"{status_folder.get(st, st)}（{cnt}）"])
                    s_it.setToolTip(0, fp)
                    s_it.setData(0, Qt.ItemDataRole.UserRole, f"virtual://focus_detect?folder={urllib.parse.quote(fp)}&status={urllib.parse.quote(st)}")
                    folder_item.addChild(s_it)

                burst_total = 0
                try:
                    burst_total = sum(int(v.get("total", 0) or 0) for v in (burst_groups or {}).values())
                except Exception:
                    burst_total = 0
                burst_node = QTreeWidgetItem([f"连拍（{int(burst_total)}）"])
                burst_node.setToolTip(0, fp)
                burst_node.setData(0, Qt.ItemDataRole.UserRole, f"virtual://focus_detect_burst_root?folder={urllib.parse.quote(fp)}")
                folder_item.addChild(burst_node)

        try:
            if current_role:
                for i in range(tree.topLevelItemCount()):
                    it = tree.topLevelItem(i)
                    if it is None:
                        continue
                    if it.data(0, Qt.ItemDataRole.UserRole) == current_role:
                        tree.setCurrentItem(it)
                        break
        except Exception:
            pass

    def _build_focus_detect_virtual_folders(self):
        try:
            folders = list(getattr(self, "_focus_detect_last_folders", []) or [])
        except Exception:
            folders = []
        try:
            vr = getattr(self, "_focus_detect_virtual_roots", None)
            if isinstance(vr, (list, tuple)) and vr:
                folders = [str(x) for x in vr if x]
        except Exception:
            pass
        if not folders:
            try:
                vr = self.settings_manager.get("focus_detect/virtual_roots", []) or []
                if isinstance(vr, (list, tuple)) and vr:
                    folders = [str(x) for x in vr if x]
            except Exception:
                pass
        if not folders:
            try:
                folders = self.settings_manager.get("focus_detect/folders", []) or []
                folders = [str(x) for x in folders if x]
                self._focus_detect_last_folders = list(folders)
            except Exception:
                folders = []
        if not folders:
            try:
                folders = self.db.list_import_cache_recent_folders(limit_rows=5000, max_folders=50)
                folders = [str(x) for x in (folders or []) if x]
                self._focus_detect_last_folders = list(folders)
            except Exception:
                folders = []
        else:
            try:
                ok_any = False
                for fp in (folders or []):
                    try:
                        rows0 = self.db.list_import_cache_by_folder(fp, limit=1)
                    except Exception:
                        rows0 = []
                    if rows0:
                        ok_any = True
                        break
                if not ok_any:
                    folders = self.db.list_import_cache_recent_folders(limit_rows=5000, max_folders=50)
                    folders = [str(x) for x in (folders or []) if x]
                    self._focus_detect_last_folders = list(folders)
            except Exception:
                pass
        norm_seen = set()
        deduped = []
        for f in (folders or []):
            try:
                fp = str(f or "").strip()
            except Exception:
                continue
            if not fp:
                continue
            try:
                if os.path.isfile(fp):
                    fp = os.path.dirname(fp)
            except Exception:
                pass
            fp = str(fp or "").strip()
            if not fp:
                continue
            try:
                k = os.path.normcase(os.path.normpath(fp))
            except Exception:
                k = fp
            if not k or k in norm_seen:
                continue
            norm_seen.add(k)
            deduped.append(fp)
        folders = deduped
        try:
            from utils.setting.settings_manager import SettingsManager
            if bool(SettingsManager().get("debug/focus_virtual_counts_log", False)):
                from utils.log_manager import LogManager
                LogManager.instance().info(f"[FocusDetectUI] virtual_counts: folders={len(folders)}")
        except Exception:
            pass
        try:
            from PyQt6.QtWidgets import QTreeWidgetItem
            from PyQt6.QtCore import Qt
            import urllib.parse
        except Exception:
            return
        tree = getattr(self.folder_panel, "folder_tree", None) if hasattr(self, "folder_panel") else None
        if tree is None:
            return

        current_role = None
        try:
            it0 = tree.currentItem()
            current_role = it0.data(0, Qt.ItemDataRole.UserRole) if it0 is not None else None
        except Exception:
            current_role = None

        try:
            for i in range(tree.topLevelItemCount() - 1, -1, -1):
                it = tree.topLevelItem(i)
                if it is None:
                    continue
                p = it.data(0, Qt.ItemDataRole.UserRole)
                if p == "virtual://focus_detect_root":
                    tree.takeTopLevelItem(i)
        except Exception:
            pass

        root = QTreeWidgetItem(["对焦检测"])
        root.setData(0, Qt.ItemDataRole.UserRole, "virtual://focus_detect_root")
        try:
            root.setExpanded(True)
        except Exception:
            pass
        tree.insertTopLevelItem(0, root)

        if not folders:
            child = QTreeWidgetItem(["（暂无记录）"])
            child.setData(0, Qt.ItemDataRole.UserRole, "__placeholder__")
            root.addChild(child)
        else:
            thresholds = {}
            try:
                thresholds = self._get_focus_detect_ui_thresholds()
            except Exception:
                thresholds = {}

            def _burst_first_file(row: dict) -> str:
                try:
                    fd = self._extract_focus_detect_info(row)
                except Exception:
                    fd = {}
                if not isinstance(fd, dict):
                    return ""
                try:
                    v = str(fd.get("burst_first_file") or "")
                except Exception:
                    v = ""
                return v.strip()
            for f in folders:
                try:
                    fp = str(f or "")
                except Exception:
                    continue
                if not fp:
                    continue
                counts = {"Sharp": 0, "Normal": 0, "Blurry": 0, "Minimal": 0, "ExpFrame": 0, "NoBird": 0}
                total = 0
                burst_groups: dict[str, dict] = {}
                try:
                    rows = self.db.list_import_cache_by_folder(fp, limit=100000)
                except Exception:
                    rows = []
                try:
                    from utils.setting.settings_manager import SettingsManager
                    if bool(SettingsManager().get("debug/focus_virtual_counts_log", False)):
                        from utils.log_manager import LogManager
                        LogManager.instance().info(f"[FocusDetectUI] virtual_counts: folder={fp} rows={len(rows or [])}")
                except Exception:
                    pass
                for r in (rows or []):
                    if not isinstance(r, dict):
                        continue
                    try:
                        bfirst = _burst_first_file(r)
                    except Exception:
                        bfirst = ""
                    if bfirst:
                        g = burst_groups.get(bfirst)
                        if g is None:
                            g = {"counts": {"Sharp": 0, "Normal": 0, "Blurry": 0, "Minimal": 0, "ExpFrame": 0, "NoBird": 0}, "total": 0}
                            burst_groups[bfirst] = g
                        g["total"] = int(g.get("total", 0) or 0) + 1
                        try:
                            st = self._compute_focus_status_for_item(r, thresholds)
                        except Exception:
                            st = "NoBird"
                        if st not in g["counts"]:
                            st = "NoBird"
                        g["counts"][st] = int(g["counts"].get(st, 0) or 0) + 1
                    total += 1
                    try:
                        st = self._compute_focus_status_for_item(r, thresholds)
                    except Exception:
                        st = "NoBird"
                    if st not in counts:
                        st = "NoBird"
                    counts[st] = int(counts.get(st, 0) or 0) + 1

                name = os.path.basename(fp) or fp
                folder_item = QTreeWidgetItem([f"{name}（{total}）"])
                folder_item.setToolTip(0, fp)
                folder_item.setData(0, Qt.ItemDataRole.UserRole, f"virtual://focus_detect?folder={urllib.parse.quote(fp)}&status=All")
                root.addChild(folder_item)

                status_defs = [
                    ("All", "全部", total),
                    ("Sharp", "锐利", int(counts.get("Sharp", 0) or 0)),
                    ("Normal", "普通", int(counts.get("Normal", 0) or 0)),
                    ("Blurry", "虚焦", int(counts.get("Blurry", 0) or 0)),
                    ("Minimal", "极小", int(counts.get("Minimal", 0) or 0)),
                    ("ExpFrame", "爆框", int(counts.get("ExpFrame", 0) or 0)),
                    ("NoBird", "无鸟", int(counts.get("NoBird", 0) or 0)),
                ]
                for st, label, cnt in status_defs:
                    s_it = QTreeWidgetItem([f"{label}（{int(cnt or 0)}）"])
                    s_it.setToolTip(0, fp)
                    s_it.setData(0, Qt.ItemDataRole.UserRole, f"virtual://focus_detect?folder={urllib.parse.quote(fp)}&status={urllib.parse.quote(st)}")
                    folder_item.addChild(s_it)

                burst_total = 0
                try:
                    burst_total = sum(int(v.get("total", 0) or 0) for v in (burst_groups or {}).values())
                except Exception:
                    burst_total = 0
                burst_node = QTreeWidgetItem([f"连拍（{int(burst_total)}）"])
                burst_node.setToolTip(0, fp)
                burst_node.setData(0, Qt.ItemDataRole.UserRole, f"virtual://focus_detect_burst_root?folder={urllib.parse.quote(fp)}")
                folder_item.addChild(burst_node)

                if burst_groups:
                    status_defs2 = [
                        ("All", "全部"),
                        ("Sharp", "锐利"),
                        ("Normal", "普通"),
                        ("Blurry", "虚焦"),
                        ("Minimal", "极小"),
                        ("ExpFrame", "爆框"),
                        ("NoBird", "无鸟"),
                    ]
                    try:
                        keys = sorted(burst_groups.keys(), key=lambda x: str(x or ""))
                    except Exception:
                        keys = list(burst_groups.keys())
                    for first_name in keys:
                        g = burst_groups.get(first_name) or {}
                        total2 = int(g.get("total", 0) or 0)
                        display = str(first_name or "")
                        try:
                            display = os.path.splitext(os.path.basename(display))[0] or display
                        except Exception:
                            display = display
                        grp = QTreeWidgetItem([f"{display}（{total2}）"])
                        grp.setToolTip(0, str(first_name or ""))
                        grp.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            f"virtual://focus_detect_burst?folder={urllib.parse.quote(fp)}&first={urllib.parse.quote(str(first_name or ''))}&status=All",
                        )
                        burst_node.addChild(grp)
                        counts2 = g.get("counts") if isinstance(g.get("counts"), dict) else {}
                        for st2, label2 in status_defs2:
                            if st2 == "All":
                                cnt2 = total2
                            else:
                                cnt2 = int(counts2.get(st2, 0) or 0)
                            s_it2 = QTreeWidgetItem([f"{label2}（{cnt2}）"])
                            s_it2.setToolTip(0, str(first_name or ""))
                            s_it2.setData(
                                0,
                                Qt.ItemDataRole.UserRole,
                                f"virtual://focus_detect_burst?folder={urllib.parse.quote(fp)}&first={urllib.parse.quote(str(first_name or ''))}&status={urllib.parse.quote(st2)}",
                            )
                            grp.addChild(s_it2)
                        try:
                            grp.setExpanded(False)
                        except Exception:
                            pass
                try:
                    folder_item.setExpanded(True)
                except Exception:
                    pass
        try:
            if isinstance(current_role, str) and current_role:
                found = None
                stack = []
                try:
                    for i in range(tree.topLevelItemCount()):
                        top = tree.topLevelItem(i)
                        if top is None:
                            continue
                        if top.data(0, Qt.ItemDataRole.UserRole) == "virtual://focus_detect_root":
                            stack.append(top)
                            break
                except Exception:
                    stack = []
                while stack and found is None:
                    it = stack.pop()
                    try:
                        if it.data(0, Qt.ItemDataRole.UserRole) == current_role:
                            found = it
                            break
                    except Exception:
                        pass
                    try:
                        for j in range(it.childCount()):
                            c = it.child(j)
                            if c is not None:
                                stack.append(c)
                    except Exception:
                        pass
                if found is not None:
                    tree.setCurrentItem(found)
                else:
                    sel = root
                    try:
                        if root.childCount() > 0:
                            sel = root.child(0)
                            if sel.childCount() > 0:
                                sel = sel.child(0)
                            if sel.childCount() > 0:
                                sel = sel.child(0)
                    except Exception:
                        sel = root
                    tree.setCurrentItem(sel)
            else:
                sel = root
                try:
                    if root.childCount() > 0:
                        sel = root.child(0)
                        if sel.childCount() > 0:
                            sel = sel.child(0)
                        if sel.childCount() > 0:
                            sel = sel.child(0)
                except Exception:
                    sel = root
                tree.setCurrentItem(sel)
        except Exception:
            pass

    def _reload_virtual_focus_detect_view(self):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        try:
            from PyQt6.QtCore import Qt
        except Exception:
            return
        tree = getattr(self.folder_panel, "folder_tree", None) if hasattr(self, "folder_panel") else None
        if tree is None:
            return
        p = None
        try:
            it = tree.currentItem()
            p0 = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
            if isinstance(p0, str) and (p0.startswith("virtual://focus_detect?folder=") or p0.startswith("virtual://focus_detect_burst?folder=")):
                p = p0
        except Exception:
            p = None
        if not p:
            try:
                for i in range(tree.topLevelItemCount()):
                    top = tree.topLevelItem(i)
                    if top is None:
                        continue
                    if top.data(0, Qt.ItemDataRole.UserRole) != "virtual://focus_detect_root":
                        continue
                    stack = []
                    try:
                        for j in range(top.childCount()):
                            c = top.child(j)
                            if c is not None:
                                stack.append(c)
                    except Exception:
                        stack = []
                    while stack:
                        child = stack.pop(0)
                        if child is None:
                            continue
                        p1 = child.data(0, Qt.ItemDataRole.UserRole)
                        if isinstance(p1, str) and (p1.startswith("virtual://focus_detect?folder=") or p1.startswith("virtual://focus_detect_burst?folder=")):
                            tree.setCurrentItem(child)
                            p = p1
                            break
                        try:
                            for k in range(child.childCount()):
                                cc = child.child(k)
                                if cc is not None:
                                    stack.append(cc)
                        except Exception:
                            pass
                    break
            except Exception:
                p = None
        if p:
            self.on_folder_selected(str(p), 0)

    def _save_focus_detect_results(self, paths: list[str], results: dict, options: dict):
        from utils.file.file_util import get_fast_id
        from utils.file.fingerprint import get_unique_id
        import json
        from utils.exif.exif_utils import ExifHandleWorker
        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[FocusDetectUI] finalize_results start files={len(paths or [])}")
        except Exception:
            pass

        now_results = results.get("results") if isinstance(results, dict) else None
        if not isinstance(now_results, dict):
            now_results = {}

        no_db_write = False
        try:
            no_db_write = bool((options or {}).get("no_db_write", False))
        except Exception:
            no_db_write = False

        if no_db_write:
            return

        data_list = []
        existing_by_path = {}
        existing_by_fast_id = {}
        fast_id_by_norm_path = {}
        try:
            db_paths = []
            for p in (paths or []):
                try:
                    p_db = self.db._normalize_file_path_for_db(str(p))
                except Exception:
                    p_db = str(p)
                if p_db:
                    db_paths.append(str(p_db))
            if db_paths:
                existing_raw = self.db.get_results_by_paths(db_paths, table_name="import_cache") or {}
                if isinstance(existing_raw, dict) and existing_raw:
                    for k, v in existing_raw.items():
                        try:
                            nk = self.db._norm_path_key(k)
                        except Exception:
                            nk = str(k)
                        if nk:
                            existing_by_path[str(nk)] = v
        except Exception:
            existing_by_path = {}

        try:
            if paths:
                fids = []
                for p in (paths or []):
                    if not p:
                        continue
                    fid = None
                    try:
                        fid = get_fast_id(str(p))
                    except Exception:
                        fid = None
                    if fid:
                        fids.append(str(fid))
                    try:
                        nk = self.db._norm_path_key(self.db._normalize_file_path_for_db(str(p)))
                    except Exception:
                        nk = str(p)
                    if fid and nk:
                        fast_id_by_norm_path[str(nk)] = str(fid)
                if fids and hasattr(self, "db") and self.db is not None and hasattr(self.db, "get_results_by_fast_ids"):
                    existing_by_fast_id = self.db.get_results_by_fast_ids(list(dict.fromkeys(fids)), table_name="import_cache") or {}
        except Exception:
            existing_by_fast_id = {}

        exif_worker = None
        try:
            exif_worker = ExifHandleWorker.get_instance()
        except Exception:
            exif_worker = None
        exif_tags = ["ISO", "FNumber", "ApertureValue", "ExposureTime", "ShutterSpeedValue", "FocalLength", "Model", "LensModel"]
        time_map = {}
        meta_map = {}
        time_map_norm = {}
        meta_map_norm = {}
        if exif_worker is not None and paths:
            try:
                from utils.log_manager import LogManager
                t0 = time.time()
                chunk = 200
                for i in range(0, len(paths), chunk):
                    sub = [str(x) for x in (paths[i:i + chunk] or []) if x]
                    if not sub:
                        continue
                    try:
                        m = exif_worker.get_times(sub, timeout=12) or {}
                        if isinstance(m, dict):
                            time_map.update(m)
                    except Exception:
                        pass
                    try:
                        mm = exif_worker.get_tags_multi(sub, exif_tags, timeout=12) or {}
                        if isinstance(mm, dict):
                            meta_map.update(mm)
                    except Exception:
                        pass
                t1 = time.time()
                LogManager.instance().info(f"[FocusDetectUI] batch_exif_read done files={len(paths)} elapsed_s={float(t1 - t0):.2f}")
            except Exception:
                time_map = {}
                meta_map = {}
        try:
            def _nk(p: str) -> str:
                if not p:
                    return ""
                try:
                    p0 = os.path.normpath(str(p))
                except Exception:
                    p0 = str(p)
                if os.name == "nt":
                    try:
                        p0 = p0.replace("/", "\\")
                    except Exception:
                        pass
                    try:
                        p0 = os.path.normcase(p0)
                    except Exception:
                        p0 = str(p0).lower()
                return str(p0)
            if isinstance(time_map, dict):
                for k, v in time_map.items():
                    kk = _nk(str(k))
                    if kk:
                        time_map_norm[kk] = v
            if isinstance(meta_map, dict):
                for k, v in meta_map.items():
                    kk = _nk(str(k))
                    if kk:
                        meta_map_norm[kk] = v
        except Exception:
            time_map_norm = {}
            meta_map_norm = {}

        total = int(len(paths or []))
        done = 0
        for p in (paths or []):
            r = now_results.get(p) or {}
            if not isinstance(r, dict):
                r = {}
            bbox = r.get("bbox_orig") or r.get("bbox") or None
            score = r.get("score")
            norm_score = r.get("norm_score")
            area_ratio = r.get("area")
            pos = r.get("pos") or ""
            try:
                nk = self.db._norm_path_key(self.db._normalize_file_path_for_db(str(p)))
            except Exception:
                nk = str(p)
            fid0 = fast_id_by_norm_path.get(str(nk)) if isinstance(fast_id_by_norm_path, dict) else None
            existing = None
            if fid0 and isinstance(existing_by_fast_id, dict):
                existing = existing_by_fast_id.get(str(fid0))
            if existing is None:
                existing = existing_by_path.get(str(nk)) if isinstance(existing_by_path, dict) else None
            label = existing.get("label") if isinstance(existing, dict) else None
            rating = existing.get("rating") if isinstance(existing, dict) else 0
            is_favorite = existing.get("is_favorite") if isinstance(existing, dict) else 0
            tags = existing.get("tags") if isinstance(existing, dict) else ""
            fp = (existing.get("focus_point") if isinstance(existing, dict) else None)
            extra = dict(r)
            try:
                extra.pop("bbox", None)
                extra.pop("bbox_orig", None)
                extra.pop("focus_point", None)
                extra.pop("focus_point_orig", None)
            except Exception:
                pass
            try:
                if "orig_w" not in extra or "orig_h" not in extra:
                    from cache.focus_scaled_cache import try_load_meta
                    focus_target = 640
                    try:
                        focus_target = int(self.settings_manager.get("focus_detect/target_size", 640) or 640)
                    except Exception:
                        focus_target = 640
                    meta0 = try_load_meta(str(p), int(focus_target), scope="import_focus")
                    if isinstance(meta0, dict):
                        if "orig_w" not in extra and meta0.get("orig_w") is not None:
                            extra["orig_w"] = meta0.get("orig_w")
                        if "orig_h" not in extra and meta0.get("orig_h") is not None:
                            extra["orig_h"] = meta0.get("orig_h")
            except Exception:
                pass
            try:
                focus_detect_json = json.dumps(extra, ensure_ascii=False, default=str)
            except Exception:
                focus_detect_json = "{}"
            try:
                desc = existing.get("description") if isinstance(existing, dict) else ""
            except Exception:
                desc = ""

            try:
                pixel_count = 0
                st = os.stat(p)
                pixel_count = int(st.st_size)
            except Exception:
                pixel_count = 0

            shot_time = ""
            iso = 0
            fnumber = 0.0
            shutter = ""
            focal_length = ""
            camera_model = ""
            lens_model = ""
            try:
                dt = time_map_norm.get(_nk(str(p))) if isinstance(time_map_norm, dict) else None
                if dt is not None:
                    shot_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                shot_time = ""
            meta = {}
            try:
                meta = meta_map_norm.get(_nk(str(p))) if isinstance(meta_map_norm, dict) else {}
            except Exception:
                meta = {}
            if isinstance(meta, dict):
                def _pick(tag: str):
                    if not tag:
                        return None
                    if tag in meta:
                        return meta.get(tag)
                    t1 = f"EXIF:{tag}"
                    if t1 in meta:
                        return meta.get(t1)
                    for k, v in meta.items():
                        try:
                            ks = str(k)
                        except Exception:
                            continue
                        if ks.endswith(f":{tag}") or ks.replace(":", "_") == tag or ks.replace(":", "") == tag:
                            return v
                    return None
                try:
                    shutter = str(_pick("ShutterSpeedValue") or _pick("ExposureTime") or "")
                except Exception:
                    shutter = ""
                try:
                    v = _pick("ISO")
                    iso = float(v or 0) if v not in (None, "") else 0
                except Exception:
                    iso = 0
                try:
                    fnumber = float(_pick("FNumber") or _pick("ApertureValue") or 0.0)
                except Exception:
                    fnumber = 0.0
                try:
                    focal_length = str(_pick("FocalLength") or "")
                except Exception:
                    focal_length = ""
                try:
                    camera_model = str(_pick("Model") or "")
                except Exception:
                    camera_model = ""
                try:
                    lens_model = str(_pick("LensModel") or "")
                except Exception:
                    lens_model = ""

                data_list.append(
                    {
                        "uuid": (existing.get("uuid") if isinstance(existing, dict) and existing.get("uuid") else get_unique_id()),
                        "fast_id": (fid0 or get_fast_id(p)),
                        "path": p,
                        "file": os.path.basename(p),
                        "label": label,
                        "score": score,
                        "norm_score": norm_score,
                        "bbox": bbox,
                        "position": pos,
                        "pixel_count": pixel_count,
                        "area_ratio": area_ratio,
                        "focus_point": fp,
                        "description": desc,
                        "focus_detect_json": focus_detect_json,
                        "rating": int(rating or 0),
                        "is_favorite": int(is_favorite or 0),
                        "tags": str(tags or ""),
                        "shot_time": shot_time,
                        "iso": iso,
                        "fnumber": fnumber,
                        "shutter": shutter,
                        "focal_length": focal_length,
                        "camera_model": camera_model,
                        "lens_model": lens_model,
                    }
                )
            done += 1
            if done == 1 or done == total or done % 20 == 0 or (total - done) <= 20:
                try:
                    pb = getattr(self, "_focus_progress_bridge", None)
                    if pb is not None and hasattr(pb, "progress"):
                        pb.progress.emit("整理检测结果", int(done), int(total), float(time.time()))
                    else:
                        self._focus_progress_operation = "整理检测结果"
                        self._focus_progress_done = int(done)
                        self._focus_progress_total = int(total)
                except Exception:
                    pass

        if data_list:
            try:
                pb = getattr(self, "_focus_progress_bridge", None)
                if pb is not None and hasattr(pb, "progress"):
                    pb.progress.emit("保存到数据库", 0, 1, float(time.time()))
                else:
                    self._focus_progress_operation = "保存到数据库"
                    self._focus_progress_done = 0
                    self._focus_progress_total = 1
            except Exception:
                pass
            self.db.save_results_batch(data_list, table_name="import_cache")
            try:
                pb = getattr(self, "_focus_progress_bridge", None)
                if pb is not None and hasattr(pb, "progress"):
                    pb.progress.emit("保存到数据库", 1, 1, float(time.time()))
                else:
                    self._focus_progress_operation = "保存到数据库"
                    self._focus_progress_done = 1
                    self._focus_progress_total = 1
            except Exception:
                pass

        return
        try:
            from utils.log_manager import LogManager
            LogManager.instance().info(f"[FocusDetectUI] finalize_results done files={len(paths or [])} rows={len(data_list or [])}")
        except Exception:
            pass

    def _save_focus_detect_thumbnails(self, paths: list[str]):
        try:
            from cache.thumbnail_disk_cache import ThumbnailDiskCache
            from cache.cache_manager import ImageCacheManager
            from PyQt6.QtGui import QImageReader
            from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
            from utils.system.gpu_utils import GPUScaler
        except Exception:
            return

        thumb_size = 0
        try:
            thumb_size = int(self.settings_manager.get("import/thumbnail_size", 0))
        except Exception:
            thumb_size = 0
        if thumb_size <= 0:
            thumb_size = 256

        try:
            cache_manager = ImageCacheManager(context="import", enable_preload=False)
            disk_cache = ThumbnailDiskCache(cache_manager, scope="import")
        except Exception:
            return

        need = []
        for p in (paths or []):
            try:
                if not p:
                    continue
                if disk_cache.has(p, (thumb_size, thumb_size), cache_type="general", scale_quality="low"):
                    continue
                need.append(str(p))
            except Exception:
                continue

        if not need:
            return
        try:
            pb = getattr(self, "_focus_progress_bridge", None)
            if pb is not None and hasattr(pb, "progress"):
                pb.progress.emit("生成缩略图", 0, int(len(need)), float(time.time()))
            else:
                self._focus_progress_operation = "生成缩略图"
                self._focus_progress_done = 0
                self._focus_progress_total = int(len(need))
                self._focus_progress_start_ts = float(time.time())
        except Exception:
            pass

        def build_one(path: str):
            try:
                focus_target = 640
                try:
                    focus_target = int(self.settings_manager.get("focus_detect/target_size", 640) or 640)
                except Exception:
                    focus_target = 640
                from cache.focus_scaled_cache import try_load_qimage

                cached_img, _meta = try_load_qimage(path, int(focus_target), scope="import_focus")
                if cached_img is not None and not cached_img.isNull():
                    use_gpu_scaling = True
                    try:
                        use_gpu_scaling = bool(self.settings_manager.get("performance/use_gpu_scaling", True))
                    except Exception:
                        use_gpu_scaling = True
                    if cached_img.width() > thumb_size or cached_img.height() > thumb_size:
                        if use_gpu_scaling:
                            scaled = GPUScaler.scale_qimage(cached_img, thumb_size, thumb_size, keep_aspect=True, fast_mode=True)
                            cached_img = scaled if scaled is not None else cached_img
                        if cached_img.width() > thumb_size or cached_img.height() > thumb_size:
                            cached_img = cached_img.scaled(
                                thumb_size,
                                thumb_size,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.FastTransformation,
                            )
                    disk_cache.put(path, cached_img, (thumb_size, thumb_size), cache_type="general", scale_quality="low")
                    return True
            except Exception:
                pass

            ext = ""
            try:
                ext = os.path.splitext(str(path))[1].upper()
            except Exception:
                ext = ""

            img = None
            if ext in (".TIF", ".TIFF"):
                try:
                    cv_img = load_image(path)
                except Exception:
                    cv_img = None
                if cv_img is not None:
                    try:
                        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                        height, width, channel = cv_img.shape
                        bytes_per_line = 3 * width
                        img = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
                    except Exception:
                        img = None

            if img is None or (hasattr(img, "isNull") and img.isNull()):
                from utils.system.stderr_suppressor import suppress_stderr_fd

                with suppress_stderr_fd():
                    reader = QImageReader(path)
                    reader.setAutoTransform(True)
                    sz = reader.size()
                    if sz and sz.width() > 0 and sz.height() > 0:
                        reader.setScaledSize(sz.scaled(thumb_size, thumb_size, Qt.AspectRatioMode.KeepAspectRatio))
                    img = reader.read()

            if img and not img.isNull():
                disk_cache.put(path, img, (thumb_size, thumb_size), cache_type="general", scale_quality="low")
                return True
            return False

        max_workers = min(6, max(1, (os.cpu_count() or 4) // 2))
        completed = 0
        ex = ThreadPoolExecutor(max_workers=max_workers)
        futures_by_path = {}
        start_by_future = {}
        try:
            for p in need:
                try:
                    fut = ex.submit(build_one, p)
                    futures_by_path[fut] = str(p)
                    start_by_future[fut] = float(time.time())
                except Exception:
                    continue

            pending = set(futures_by_path.keys())
            stall_timeout = 45.0
            per_item_timeout = 90.0
            last_progress_ts = float(time.time())
            while pending:
                done_set, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                if done_set:
                    last_progress_ts = float(time.time())
                for f in (done_set or []):
                    try:
                        _ = f.result()
                    except Exception:
                        pass
                    completed += 1
                    if completed == 1 or completed == len(need) or completed % 10 == 0:
                        try:
                            pb = getattr(self, "_focus_progress_bridge", None)
                            if pb is not None and hasattr(pb, "progress"):
                                pb.progress.emit("生成缩略图", int(completed), int(len(need)), float(time.time()))
                            else:
                                self._focus_progress_operation = "生成缩略图"
                                self._focus_progress_done = int(completed)
                                self._focus_progress_total = int(len(need))
                        except Exception:
                            pass

                now_ts = float(time.time())
                if pending and (now_ts - float(last_progress_ts)) > float(stall_timeout):
                    bad = []
                    try:
                        for f in pending:
                            st = float(start_by_future.get(f, now_ts))
                            if (now_ts - st) > float(per_item_timeout):
                                bad.append(futures_by_path.get(f))
                    except Exception:
                        bad = []
                    try:
                        if bad:
                            LogManager.instance().warning(f"[FocusDetect][Thumb] 超时未完成，跳过 {len(pending)} 个缩略图（示例：{bad[:3]}）")
                        else:
                            LogManager.instance().warning(f"[FocusDetect][Thumb] 长时间无进度，跳过 {len(pending)} 个缩略图")
                    except Exception:
                        pass
                    completed += int(len(pending))
                    pending = set()
                    try:
                        pb = getattr(self, "_focus_progress_bridge", None)
                        if pb is not None and hasattr(pb, "progress"):
                            pb.progress.emit("生成缩略图", int(completed), int(len(need)), float(time.time()))
                        else:
                            self._focus_progress_operation = "生成缩略图"
                            self._focus_progress_done = int(completed)
                            self._focus_progress_total = int(len(need))
                    except Exception:
                        pass
                    try:
                        NotificationManager.instance().show_warning("提示", "有少量图片生成缩略图超时，已跳过；不影响对焦检测结果")
                    except Exception:
                        pass
                    break
        finally:
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                try:
                    ex.shutdown(wait=False)
                except Exception:
                    pass

    def on_thumbnail_context_menu_proxy(self, index, pos):
        if bool(getattr(self, "is_virtual_mode", False)):
            return self.on_thumbnail_context_menu_virtual(index, pos)
        return self.on_thumbnail_context_menu(index, pos)

    def _style_context_menu(self, menu: QMenu):
        """统一右键菜单样式，保持与项目内其他菜单一致"""
        try:
            if hasattr(self, "folder_panel") and self.folder_panel is not None:
                self.folder_panel.style_menu(menu)
                return
        except Exception:
            pass
        try:
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
        except Exception:
            pass

    def get_selected_files(self):
        """获取选中的文件信息列表（与图库页保持一致的结构）"""
        selected_files = []
        try:
            for thumb in self.grid_view.get_selected_thumbnails():
                info = getattr(thumb, "image_info", None)
                if not isinstance(info, dict):
                    continue
                file_info = info.copy()
                file_info["index"] = int(getattr(thumb, "index", file_info.get("index", -1)))
                selected_files.append(file_info)
        except Exception:
            return []
        return selected_files

    def _find_image_info_by_path(self, image_path: str):
        if not image_path:
            return None
        try:
            key = self._normalize_path_key(image_path)
        except Exception:
            key = str(image_path)
        for it in (getattr(self, "image_files", []) or []):
            if not isinstance(it, dict):
                continue
            p = it.get("path")
            if not p:
                continue
            try:
                if self._normalize_path_key(p) == key:
                    return it
            except Exception:
                if str(p) == str(image_path):
                    return it
        for it in (getattr(self, "_all_image_files", []) or []):
            if not isinstance(it, dict):
                continue
            p = it.get("path")
            if not p:
                continue
            try:
                if self._normalize_path_key(p) == key:
                    return it
            except Exception:
                if str(p) == str(image_path):
                    return it
        return None

    def _update_status_in_memory(self, file_paths, field_name: str, value):
        if not file_paths:
            return
        keys = set()
        for p in (file_paths or []):
            if not p:
                continue
            try:
                keys.add(self._normalize_path_key(p))
            except Exception:
                keys.add(str(p))
        if not keys:
            return
        for lst_name in ("image_files", "_all_image_files"):
            lst = getattr(self, lst_name, None)
            if not isinstance(lst, list):
                continue
            for it in lst:
                if not isinstance(it, dict):
                    continue
                p = it.get("path")
                if not p:
                    continue
                try:
                    k = self._normalize_path_key(p)
                except Exception:
                    k = str(p)
                if k not in keys:
                    continue
                it[field_name] = value
                if field_name == "is_favorite":
                    it["favorite"] = int(value or 0)
                if field_name == "favorite":
                    it["is_favorite"] = int(value or 0)
        for k in keys:
            thumbs = []
            try:
                thumbs = (self._thumb_by_path.get(k) or []) if hasattr(self, "_thumb_by_path") else []
            except Exception:
                thumbs = []
            for t in thumbs:
                try:
                    info = getattr(t, "image_info", None)
                    if isinstance(info, dict):
                        info[field_name] = value
                        if field_name == "is_favorite":
                            info["favorite"] = int(value or 0)
                        if field_name == "favorite":
                            info["is_favorite"] = int(value or 0)
                    t.update()
                except Exception:
                    pass
        try:
            p = getattr(self, "current_preview_path", None)
            if p:
                try:
                    pk = self._normalize_path_key(p)
                except Exception:
                    pk = str(p)
                if pk in keys and hasattr(self, "preview_panel") and self.preview_panel is not None:
                    info = self._find_image_info_by_path(str(p))
                    if isinstance(info, dict):
                        fav = bool(int(info.get("is_favorite") or info.get("favorite") or 0) == 1)
                        rating = int(info.get("rating") or 0)
                        label = str(info.get("label") or "")
                        self.preview_panel.set_favorite(bool(fav))
                        self.preview_panel.set_rating(int(rating))
                        self.preview_panel.set_label(str(label))
        except Exception:
            pass

    def _update_virtual_db_user_field(self, file_paths, field_name: str, value):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        if not file_paths:
            return
        try:
            self.db.update_user_field_batch_for_table(file_paths, field_name, value, table_name="import_cache")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"更新状态失败: {e}")

    def on_preview_fav_toggled(self, checked: bool):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        p = getattr(self, "current_preview_path", None)
        if not p:
            return
        val = 1 if bool(checked) else 0
        self._update_virtual_db_user_field([p], "is_favorite", val)
        self._update_status_in_memory([p], "is_favorite", val)

    def on_preview_rating_changed(self, rating: int):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        p = getattr(self, "current_preview_path", None)
        if not p:
            return
        try:
            r = max(0, min(5, int(rating or 0)))
        except Exception:
            r = 0
        self._update_virtual_db_user_field([p], "rating", r)
        self._update_status_in_memory([p], "rating", r)

    def on_preview_label_changed(self, label: str):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        p = getattr(self, "current_preview_path", None)
        if not p:
            return
        try:
            l = str(label or "")
        except Exception:
            l = ""
        self._update_virtual_db_user_field([p], "label", l)
        self._update_status_in_memory([p], "label", l)

    def toggle_favorite_selection(self, is_favorite: bool):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        selected_paths = self.get_selected_paths() or []
        if not selected_paths:
            p = getattr(self, "current_preview_path", None)
            if p:
                selected_paths = [p]
        if not selected_paths:
            return
        val = 1 if bool(is_favorite) else 0
        self._update_virtual_db_user_field(selected_paths, "is_favorite", val)
        self._update_status_in_memory(selected_paths, "is_favorite", val)

    def set_rating_selection(self, rating: int):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        selected_paths = self.get_selected_paths() or []
        if not selected_paths:
            p = getattr(self, "current_preview_path", None)
            if p:
                selected_paths = [p]
        if not selected_paths:
            return
        try:
            r = max(0, min(5, int(rating or 0)))
        except Exception:
            r = 0
        self._update_virtual_db_user_field(selected_paths, "rating", r)
        self._update_status_in_memory(selected_paths, "rating", r)

    def set_label_selection(self, label: str):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        selected_paths = self.get_selected_paths() or []
        if not selected_paths:
            p = getattr(self, "current_preview_path", None)
            if p:
                selected_paths = [p]
        if not selected_paths:
            return
        try:
            l = str(label or "")
        except Exception:
            l = ""
        self._update_virtual_db_user_field(selected_paths, "label", l)
        self._update_status_in_memory(selected_paths, "label", l)

    def _update_open_detail_shortcut(self):
        if self._open_detail_shortcut is None:
            return
        try:
            seq = ShortcutManager.instance().get_sequence("ThumbnailGrid.OpenDetail")
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

    def _thumb_edit_get_target_paths(self):
        try:
            paths = self.get_selected_paths() or []
        except Exception:
            paths = []
        if not paths:
            p = getattr(self, "current_preview_path", None)
            if p:
                paths = [p]
        paths = [p for p in (paths or []) if p]
        if not paths:
            return [], None
        first = str(paths[0])
        info0 = None
        key0 = self._normalize_path_key(first)
        try:
            for it in (self.image_files or []):
                if isinstance(it, dict) and self._normalize_path_key(it.get("path")) == key0:
                    info0 = it
                    break
        except Exception:
            info0 = None
        return paths, info0

    def _thumb_edit_toggle_favorite(self):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        paths, info0 = self._thumb_edit_get_target_paths()
        if not paths:
            return
        cur = 0
        try:
            if isinstance(info0, dict):
                cur = int(info0.get("is_favorite") or info0.get("favorite") or 0)
        except Exception:
            cur = 0
        self.toggle_favorite_selection(bool(int(cur) != 1))

    def _thumb_edit_set_rating(self, rating: int):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        paths, info0 = self._thumb_edit_get_target_paths()
        if not paths:
            return
        cur = 0
        try:
            if isinstance(info0, dict):
                cur = int(info0.get("rating") or 0)
        except Exception:
            cur = 0
        new_rating = 0 if int(cur) == int(rating) else int(rating)
        self.set_rating_selection(int(new_rating))

    def _thumb_edit_set_label(self, label: str):
        if not bool(getattr(self, "is_virtual_mode", False)):
            return
        paths, info0 = self._thumb_edit_get_target_paths()
        if not paths:
            return
        cur = ""
        try:
            if isinstance(info0, dict):
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
            selected = self.get_selected_files()
            if selected:
                idx = int(selected[0].get("index", -1))
        except Exception:
            idx = -1
        if idx < 0:
            try:
                p = getattr(self, "current_preview_path", None) or self._get_current_detail_path()
                if p:
                    for i, it in enumerate(self.image_files or []):
                        if isinstance(it, dict) and it.get("path") == p:
                            idx = int(i)
                            break
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
            if j is None:
                continue
            try:
                j = int(j)
            except Exception:
                continue
            if j < 0 or j >= len(self.image_files) or j == i:
                continue
            try:
                p = self.image_files[j].get("path") if isinstance(self.image_files[j], dict) else None
            except Exception:
                p = None
            if p:
                paths.append(str(p))
        if paths:
            try:
                self.big_image_cache.preload(paths)
            except Exception:
                pass

    def get_selected_paths(self):
        """获取选中文件的路径列表"""
        out = []
        for f in self.get_selected_files():
            p = f.get("path")
            if p:
                out.append(str(p))
        return out

    def on_thumbnail_context_menu_virtual(self, index, position):
        try:
            thumbnails = getattr(self.grid_view, "thumbnails", []) or []
            if index < 0 or index >= len(thumbnails):
                return
            thumb = thumbnails[index]
            image_info = getattr(thumb, "image_info", None)
            if not isinstance(image_info, dict):
                return
            image_path = image_info.get("path")
            if not image_path:
                return

            if not bool(getattr(thumb, "selected", False)):
                try:
                    if getattr(self.grid_view, "is_virtualized", False):
                        self.grid_view.select_thumbnail(index, scroll_to=False)
                    else:
                        for i, t in enumerate(thumbnails):
                            try:
                                t.set_selected(i == index)
                            except Exception:
                                pass
                    self.last_selected_index = index
                except Exception:
                    pass

            menu = QMenu(self)
            self._style_context_menu(menu)

            open_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "打开")
            open_action.triggered.connect(lambda: self.open_image(image_path))

            edit_in_app_action = menu.addAction(qta.icon('mdi6.open-in-app', color='#555'), "在外部软件内编辑")
            edit_in_app_action.triggered.connect(lambda: self.open_in_external_editor(self.get_selected_paths() or [str(image_path)]))

            show_in_folder_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "在文件管理器打开")
            show_in_folder_action.triggered.connect(lambda: self.folder_panel.open_in_explorer(os.path.dirname(image_path)))

            copy_action = menu.addAction(qta.icon('mdi6.content-copy', color='#555'), "复制")
            copy_action.triggered.connect(lambda: self.copy_image(image_path))

            copy_path_action = menu.addAction(qta.icon('mdi6.link-variant', color='#555'), "复制路径")
            copy_path_action.triggered.connect(lambda: self.copy_image_path(image_path))

            menu.addSeparator()

            is_fav = bool(int(image_info.get("is_favorite") or image_info.get("favorite") or 0) == 1)
            if is_fav:
                fav_action = menu.addAction(qta.icon('mdi6.heart-outline', color='#555'), "取消收藏")
                fav_action.triggered.connect(lambda: self.toggle_favorite_selection(False))
            else:
                fav_action = menu.addAction(qta.icon('mdi6.heart', color='#e74c3c'), "收藏")
                fav_action.triggered.connect(lambda: self.toggle_favorite_selection(True))

            rating_menu = menu.addMenu(qta.icon('fa5s.star', color='#FFCC00'), "评分")
            rating_menu.addAction("0星 (清除)").triggered.connect(lambda: self.set_rating_selection(0))
            rating_menu.addSeparator()
            for r in range(1, 6):
                rating_menu.addAction(f"{r}星").triggered.connect(lambda checked=False, v=r: self.set_rating_selection(v))

            label_menu = menu.addMenu(qta.icon('mdi.circle', color='#2196F3'), "设置色标")
            label_menu.addAction("无色标 (清除)").triggered.connect(lambda: self.set_label_selection(""))
            label_menu.addSeparator()
            labels = [
                ("Red", "红色", "#FF3B30"),
                ("Yellow", "黄色", "#FFCC00"),
                ("Green", "绿色", "#5CB85C"),
                ("Blue", "蓝色", "#007AFF"),
                ("Purple", "紫色", "#AF52DE"),
                ("White", "白色", "#FFFFFF"),
                ("Orange", "橙色", "#FF9500"),
                ("Pink", "粉色", "#F06292"),
                ("Cyan", "青色", "#5AC8FA"),
                ("Gray", "灰色", "#8E8E93"),
                ("Black", "黑色", "#48484A"),
            ]
            for en_name, cn_name, color_hex in labels:
                if en_name == "White":
                    icon = qta.icon('mdi.circle', color=color_hex, color_off='#A0A0A0')
                    action = label_menu.addAction(icon, cn_name)
                else:
                    action = label_menu.addAction(qta.icon('mdi.circle', color=color_hex), cn_name)
                action.triggered.connect(lambda checked=False, l=en_name: self.set_label_selection(l))

            menu.addSeparator()

            location_action = menu.addAction(qta.icon('mdi6.map-marker-outline', color='#555'), "设置地理位置")
            location_action.triggered.connect(self.show_geolocation_dialog)

            track_match_action = menu.addAction(qta.icon('mdi6.transit-connection-variant', color='#555'), "轨迹匹配")
            track_match_action.triggered.connect(self.show_track_match_dialog)

            import_to_library_action = menu.addAction(qta.icon('mdi6.database-import', color='#555'), "导入图库")
            import_to_library_action.triggered.connect(self.open_import_to_library_dialog)

            species_detect_action = menu.addAction(qta.icon('ri.voice-recognition-fill', color='#555'), "鸟种检测")
            species_detect_action.triggered.connect(self.open_bird_species_detect_dialog)

            stash_action = menu.addAction(qta.icon('mdi6.tag-check', color='#555'), "暂存")
            stash_action.triggered.connect(self.stash_selected_images)

            add_tag_action = menu.addAction(qta.icon('ph.tag-simple-fill', color='#555'), "添加标签")
            add_tag_action.triggered.connect(self.open_tag_manager)

            remark_action = menu.addAction(qta.icon('mdi6.comment-text-outline', color='#555'), "添加备注")
            remark_action.triggered.connect(lambda: self.edit_remark(image_path))

            menu.addSeparator()

            delete_action = menu.addAction(qta.icon('mdi6.trash-can-outline', color='#e74c3c'), "删除")
            delete_action.triggered.connect(self.delete_selected_images)

            properties_action = menu.addAction(qta.icon('mdi6.information', color='#555'), "属性")
            properties_action.triggered.connect(lambda: self.show_image_properties(image_path))

            menu.exec(position)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开右键菜单失败: {e}")

    def on_thumbnail_context_menu(self, index, position):
        """处理缩略图右键菜单（真实文件模式）"""
        try:
            thumbnails = getattr(self.grid_view, "thumbnails", []) or []
            if index < 0 or index >= len(thumbnails):
                return
            thumb = thumbnails[index]
            image_info = getattr(thumb, "image_info", None)
            if not isinstance(image_info, dict):
                return
            image_path = image_info.get("path")
            if not image_path:
                return

            if not bool(getattr(thumb, "selected", False)):
                try:
                    if getattr(self.grid_view, "is_virtualized", False):
                        self.grid_view.select_thumbnail(index, scroll_to=False)
                    else:
                        for i, t in enumerate(thumbnails):
                            try:
                                t.set_selected(i == index)
                            except Exception:
                                pass
                    self.last_selected_index = index
                except Exception:
                    pass

            menu = QMenu(self)
            self._style_context_menu(menu)

            open_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "打开")
            open_action.triggered.connect(lambda: self.open_image(image_path))

            edit_in_app_action = menu.addAction(qta.icon('mdi6.open-in-app', color='#555'), "在外部软件内编辑")
            edit_in_app_action.triggered.connect(lambda: self.open_in_external_editor(self.get_selected_paths() or [str(image_path)]))

            show_in_folder_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "在文件管理器打开")
            show_in_folder_action.triggered.connect(lambda: self.folder_panel.open_in_explorer(os.path.dirname(image_path)))

            copy_action = menu.addAction(qta.icon('mdi6.content-copy', color='#555'), "复制")
            copy_action.triggered.connect(lambda: self.copy_image(image_path))

            copy_path_action = menu.addAction(qta.icon('mdi6.link-variant', color='#555'), "复制路径")
            copy_path_action.triggered.connect(lambda: self.copy_image_path(image_path))

            menu.addSeparator()

            location_action = menu.addAction(qta.icon('mdi6.map-marker-outline', color='#555'), "设置地理位置")
            location_action.triggered.connect(self.show_geolocation_dialog)

            track_match_action = menu.addAction(qta.icon('mdi6.transit-connection-variant', color='#555'), "轨迹匹配")
            track_match_action.triggered.connect(self.show_track_match_dialog)

            import_to_library_action = menu.addAction(qta.icon('mdi6.database-import', color='#555'), "导入图库")
            import_to_library_action.triggered.connect(self.open_import_to_library_dialog)

            species_detect_action = menu.addAction(qta.icon('ri.voice-recognition-fill', color='#555'), "鸟种检测")
            species_detect_action.triggered.connect(self.open_bird_species_detect_dialog)

            stash_action = menu.addAction(qta.icon('mdi6.tag-check', color='#555'), "暂存")
            stash_action.triggered.connect(self.stash_selected_images)

            add_tag_action = menu.addAction(qta.icon('ph.tag-simple-fill', color='#555'), "添加标签")
            add_tag_action.triggered.connect(self.open_tag_manager)

            remark_action = menu.addAction(qta.icon('mdi6.comment-text-outline', color='#555'), "添加备注")
            remark_action.triggered.connect(lambda: self.edit_remark(image_path))

            menu.addSeparator()

            delete_action = menu.addAction(qta.icon('mdi6.trash-can-outline', color='#e74c3c'), "删除")
            delete_action.triggered.connect(self.delete_selected_images)

            properties_action = menu.addAction(qta.icon('mdi6.information', color='#555'), "属性")
            properties_action.triggered.connect(lambda: self.show_image_properties(image_path))

            menu.exec(position)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开右键菜单失败: {e}")

    def open_bird_species_detect_dialog(self):
        selected_files = self.get_selected_files()
        if not selected_files:
            NotificationManager.instance().show_warning("提示", "请先选择图片")
            return
        try:
            table_name = "import_cache" if bool(getattr(self, "is_virtual_mode", False)) else "bird_results"
        except Exception:
            table_name = "bird_results"
        try:
            self._auto_match_species_from_folder_names(selected_files, table_name=table_name)
        except Exception:
            pass
        try:
            from ui.dialogs.bird_species_detect_dialog import BirdSpeciesDetectDialog
            dialog = BirdSpeciesDetectDialog(self, selected_files=selected_files)
            dialog.exec()
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开鸟种检测窗口失败: {e}")
            return
        updates = []
        for f in (selected_files or []):
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "")
            if not p:
                continue
            species = str(f.get("species") or f.get("object") or "").strip()
            order_cls = str(f.get("order") or f.get("order_cls") or "").strip()
            family_cls = str(f.get("family") or f.get("family_cls") or "").strip()
            genus_cls = str(f.get("genus") or f.get("genus_cls") or "").strip()
            species_cls = str(f.get("species_cls") or species or "").strip()
            updates.append(
                {
                    "path": p,
                    "object": species,
                    "order_cls": order_cls,
                    "family_cls": family_cls,
                    "genus_cls": genus_cls,
                    "species_cls": species_cls,
                }
            )
        try:
            if updates:
                self.db.update_taxonomy_batch_for_table(updates, table_name=table_name)
        except Exception:
            pass
        try:
            for u in (updates or []):
                p = u.get("path")
                if not p:
                    continue
                self._update_status_in_memory([p], "object", u.get("object"))
                self._update_status_in_memory([p], "order_cls", u.get("order_cls"))
                self._update_status_in_memory([p], "family_cls", u.get("family_cls"))
                self._update_status_in_memory([p], "genus_cls", u.get("genus_cls"))
                self._update_status_in_memory([p], "species_cls", u.get("species_cls"))
        except Exception:
            pass
        try:
            self._refresh_thumbnail_overlays()
        except Exception:
            pass

    _bird_classification_cache = None

    def _load_bird_classification_map(self):
        if isinstance(getattr(self, "_bird_classification_cache", None), dict):
            return self._bird_classification_cache
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(project_root, "data", "bird_classification.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._bird_classification_cache = data
                return data
        except Exception:
            pass
        self._bird_classification_cache = {}
        return self._bird_classification_cache

    def _match_taxonomy_from_folder_name(self, file_path: str):
        try:
            folder_name = os.path.basename(os.path.dirname(str(file_path)))
        except Exception:
            folder_name = ""
        folder_name = str(folder_name or "").strip()
        if not folder_name:
            return None
        data = self._load_bird_classification_map()
        meta = data.get(folder_name) if isinstance(data, dict) else None
        if not isinstance(meta, dict):
            return None
        order_cn = str(meta.get("order_cn") or "").strip()
        family_cn = str(meta.get("family_cn") or "").strip()
        genus_cn = str(meta.get("genus_cn") or "").strip()
        return {
            "species": folder_name,
            "object": folder_name,
            "species_cls": folder_name,
            "order_cls": order_cn,
            "family_cls": family_cn,
            "genus_cls": genus_cn,
        }

    def _auto_match_species_from_folder_names(self, selected_files, *, table_name: str):
        updates = []
        for f in (selected_files or []):
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "")
            if not p:
                continue
            existing_species = str(f.get("species") or f.get("object") or f.get("species_cls") or "").strip()
            if existing_species:
                continue
            m = self._match_taxonomy_from_folder_name(p)
            if not isinstance(m, dict):
                continue
            f["species"] = m.get("species") or ""
            f["object"] = m.get("object") or ""
            f["species_cls"] = m.get("species_cls") or ""
            f["order_cls"] = m.get("order_cls") or ""
            f["family_cls"] = m.get("family_cls") or ""
            f["genus_cls"] = m.get("genus_cls") or ""
            updates.append(
                {
                    "path": p,
                    "object": f.get("object"),
                    "order_cls": f.get("order_cls"),
                    "family_cls": f.get("family_cls"),
                    "genus_cls": f.get("genus_cls"),
                    "species_cls": f.get("species_cls") or f.get("object"),
                }
            )
        if not updates:
            return
        try:
            self.db.update_taxonomy_batch_for_table(updates, table_name=table_name)
        except Exception:
            pass
        try:
            for u in (updates or []):
                p = u.get("path")
                if not p:
                    continue
                self._update_status_in_memory([p], "object", u.get("object"))
                self._update_status_in_memory([p], "order_cls", u.get("order_cls"))
                self._update_status_in_memory([p], "family_cls", u.get("family_cls"))
                self._update_status_in_memory([p], "genus_cls", u.get("genus_cls"))
                self._update_status_in_memory([p], "species_cls", u.get("species_cls"))
        except Exception:
            pass
        try:
            self._refresh_thumbnail_overlays()
        except Exception:
            pass


    def open_image(self, image_path):
        """打开图片文件"""
        try:
            import platform
            if platform.system() == "Windows":
                os.startfile(image_path)
            elif platform.system() == "Darwin":
                import subprocess
                subprocess.Popen(["open", image_path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", image_path])
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"无法打开图片: {e}")

    def open_in_external_editor(self, image_paths: list[str]):
        paths = [str(p) for p in (image_paths or []) if p]
        if not paths:
            return
        app_path = str(self.settings_manager.get("external/edit_image_app", "") or "").strip()
        if not app_path:
            for p in paths:
                self.open_image(p)
            return
        if not os.path.exists(app_path):
            NotificationManager.instance().show_warning("错误", "编辑软件路径无效，请在设置页配置")
            return
        try:
            import subprocess
            subprocess.Popen([app_path, *paths])
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"无法在外部软件中打开: {e}")

    def copy_image(self, image_path):
        """复制图片到剪贴板"""
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtGui import QClipboard, QImage, QPixmap
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
            
            # 为了确保数据被复制且脱离 numpy 引用，同时也为了确保剪贴板兼容性，
            # 最好在这里做一个深拷贝并转为标准 RGB
            q_img = q_img.copy() 
            
            pixmap = QPixmap.fromImage(q_img)
            
            clipboard = QApplication.clipboard()
            if not pixmap.isNull():
                clipboard.setPixmap(pixmap)
                NotificationManager.instance().show_toast("图片已复制到剪贴板")
            else:
                NotificationManager.instance().show_warning("错误", "无法加载图片")
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
            NotificationManager.instance().show_warning("错误", f"复制失败: {e}")

    def copy_image_path(self, image_path):
        """复制图片路径到剪贴板"""
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(str(image_path))
            NotificationManager.instance().show_toast("路径已复制到剪贴板")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"复制失败: {e}")

    def show_image_properties(self, image_path):
        """显示图片属性"""
        try:
            from datetime import datetime
            from PyQt6.QtGui import QImageReader
            file_stat = os.stat(image_path)
            size = file_stat.st_size
            create_time = datetime.fromtimestamp(file_stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
            modify_time = datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
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
            NotificationManager.instance().show_info("属性", info_text)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"无法获取属性: {e}")

    def show_geolocation_dialog(self, checked: bool = False):
        """显示设置地理位置弹窗"""
        try:
            _ = checked
            selected_paths = self.get_selected_paths()
            selected_count = len(selected_paths)
            if selected_count == 0:
                NotificationManager.instance().show_warning("提示", "请先选择图片")
                return
            from ui.widgets.geolocation_dialog import GeoLocationDialog
            table_name = "import_cache" if bool(getattr(self, "is_virtual_mode", False)) else "bird_results"
            dialog = GeoLocationDialog(self, selected_count=selected_count, file_paths=selected_paths, table_name=table_name)
            dialog.exec()
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开地理位置窗口失败: {e}")

    def show_track_match_dialog(self, checked: bool = False):
        try:
            _ = checked
            selected_paths = self.get_selected_paths()
            selected_count = len(selected_paths)
            if selected_count == 0:
                NotificationManager.instance().show_warning("提示", "请先选择图片")
                return
            from ui.widgets.track_match_dialog import TrackMatchDialog
            table_name = "import_cache" if bool(getattr(self, "is_virtual_mode", False)) else "bird_results"
            dialog = TrackMatchDialog(self, file_paths=selected_paths, table_name=table_name)
            dialog.exec()
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开轨迹匹配窗口失败: {e}")

    def open_import_to_library_dialog(self):
        """打开导入图库弹窗"""
        selected_files = self.get_selected_files()
        if not selected_files:
            NotificationManager.instance().show_warning("提示", "请先选择图片")
            return
        try:
            table_name = "import_cache" if bool(getattr(self, "is_virtual_mode", False)) else "bird_results"
        except Exception:
            table_name = "bird_results"
        try:
            self._auto_match_species_from_folder_names(selected_files, table_name=table_name)
        except Exception:
            pass
        try:
            from ui.dialogs.import_to_library_rename_dialog import ImportToLibraryRenameDialog
            dialog = ImportToLibraryRenameDialog(self, selected_files=selected_files, is_virtual_mode=bool(getattr(self, "is_virtual_mode", False)))
            try:
                def _on_import_succeeded(target_folder: str):
                    current_selected = ""
                    try:
                        if hasattr(self, "folder_panel") and self.folder_panel is not None:
                            item = self.folder_panel.folder_tree.currentItem()
                            current_selected = item.data(0, Qt.ItemDataRole.UserRole) if item else ""
                    except Exception:
                        current_selected = ""
                    try:
                        if hasattr(self, "folder_panel") and self.folder_panel is not None:
                            skip_refresh = False
                            try:
                                if bool(getattr(self, "is_virtual_mode", False)):
                                    skip_refresh = True
                            except Exception:
                                skip_refresh = False
                            if not skip_refresh:
                                try:
                                    tree = getattr(self.folder_panel, "folder_tree", None)
                                    if tree is not None:
                                        for i in range(tree.topLevelItemCount()):
                                            top = tree.topLevelItem(i)
                                            if top is None:
                                                continue
                                            role = top.data(0, Qt.ItemDataRole.UserRole)
                                            if isinstance(role, str) and role.startswith("virtual://"):
                                                skip_refresh = True
                                                break
                                except Exception:
                                    pass
                            if not skip_refresh:
                                try:
                                    self.folder_panel.folder_tree.blockSignals(True)
                                except Exception:
                                    pass
                                try:
                                    self.folder_panel.refresh_tree(target_path=str(target_folder or ""))
                                finally:
                                    try:
                                        self.folder_panel.folder_tree.blockSignals(False)
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    if current_selected:
                        try:
                            QTimer.singleShot(0, lambda p=str(current_selected): self.folder_panel.navigate_to_folder(p))
                        except Exception:
                            pass
                    try:
                        self.import_to_library_succeeded.emit(str(target_folder or ""))
                    except Exception:
                        pass
                dialog.import_succeeded.connect(_on_import_succeeded)
            except Exception:
                pass
            if dialog.exec():
                try:
                    is_v = bool(getattr(self, "is_virtual_mode", False))
                except Exception:
                    is_v = False
                if not is_v:
                    folder = self.settings_manager.get("import/last_folder", "") or ""
                    if folder and os.path.exists(folder):
                        self.load_images(folder, recursive=False)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开导入图库窗口失败: {e}")

    def open_tag_manager(self):
        """打开标签管理弹窗"""
        selected_paths = self.get_selected_paths()
        if not selected_paths:
            NotificationManager.instance().show_warning("提示", "请先选择图片")
            return
        try:
            from ui.dialogs.tag_manager_dialog import TagManagerDialog
            table_name = "import_cache" if bool(getattr(self, "is_virtual_mode", False)) else "bird_results"
            dialog = TagManagerDialog(self.db, selected_paths, self, table_name=table_name)
            dialog.tags_updated.connect(self.on_tags_updated)
            dialog.exec()
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开标签窗口失败: {e}")

    def on_tags_updated(self, file_paths, tags_str):
        """标签更新回调"""
        self._perform_tags_update(file_paths, tags_str)

    def _perform_tags_update(self, file_paths, tags_str):
        """执行标签写入（数据库 + 元数据）"""
        try:
            if bool(getattr(self, "is_virtual_mode", False)):
                self.db.update_tags_batch_for_table(file_paths, tags_str, table_name="import_cache")
            else:
                self.db.update_tags_batch(file_paths, tags_str)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"更新标签失败: {e}")
            return

        try:
            from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG
            tags = {EXIF_TAG.Tags.value: tags_str}
            exif_tasks = [(path, tags) for path in (file_paths or []) if path]

            def run_exif_update():
                task_id = StatusManager.instance().start_task("正在更新标签 (写入元数据)...")
                try:
                    ExifHandleWorker.get_instance().enqueue_update_tags(exif_tasks)
                finally:
                    StatusManager.instance().finish_task(task_id)

            Thread(target=run_exif_update, daemon=True).start()
        except Exception:
            pass

        NotificationManager.instance().show_toast("标签已更新")
        try:
            if getattr(self, "current_preview_path", None) in set(file_paths or []):
                self._update_info_panel(self.current_preview_path)
        except Exception:
            pass

    def edit_remark(self, image_path):
        """编辑图片备注"""
        try:
            current_remark = ""
            table_name = "import_cache" if bool(getattr(self, "is_virtual_mode", False)) else "bird_results"
            record = self.db.get_result_by_path(image_path, table_name=table_name)
            if record:
                d = record.get("description")
                if d:
                    current_remark = str(d)

            from ui.widgets.remark_dialog import RemarkDialog
            dialog = RemarkDialog(self, current_remark)
            if not dialog.exec():
                return
            new_remark = dialog.get_remark()

            self.db.update_description(image_path, new_remark, table_name=table_name)

            try:
                target_key = self._normalize_path_key(image_path)
                thumbs = self._thumb_by_path.get(target_key, []) if hasattr(self, "_thumb_by_path") else []
                for t in thumbs:
                    if getattr(t, "image_info", None) and t.image_info.get("path") == image_path:
                        t.image_info["description"] = new_remark
                        try:
                            t.update()
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                target_img = next((img for img in (self.image_files or []) if img.get("path") == image_path), None)
                if target_img is not None:
                    target_img["description"] = new_remark
            except Exception:
                pass

            try:
                if getattr(self, "current_preview_path", None) == image_path and self.info_panel.isVisible():
                    self._update_info_panel(image_path)
            except Exception:
                pass

            NotificationManager.instance().show_toast("备注已更新")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"更新备注失败: {e}")

    def delete_selected_images(self):
        if bool(getattr(self, "is_virtual_mode", False)):
            selected_files = self.get_selected_files()
            if not selected_files:
                NotificationManager.instance().show_warning("提示", "请先选择图片")
                return
            
            # 获取是否删除本地文件的上次选择状态
            delete_local_key = "import/delete_local_file_in_virtual_mode"
            
            # 使用带复选框的确认对话框
            confirmed, delete_local = NotificationManager.instance().ask_confirmation(
                "确认删除",
                f"确定要从数据库中删除选中的 {len(selected_files)} 条记录吗？",
                show_checkbox=True,
                checkbox_text="同时删除本地磁盘文件",
                default_checked=bool(self.settings_manager.get(delete_local_key, False))
            )
            
            try:
                self.settings_manager.set(delete_local_key, delete_local)
                self.settings_manager.sync()
            except Exception:
                pass
            
            if not confirmed:
                return
            
            deleted_paths = []
            for f in (selected_files or []):
                p = f.get("path")
                if not p:
                    continue
                try:
                    self.db.delete_result(p, table_name="import_cache")
                    
                    # 如果勾选了删除本地文件
                    if delete_local:
                        try:
                            if os.path.exists(p):
                                try:
                                    from utils.file.file_utils import delete_with_sidecar
                                    delete_with_sidecar(p, prefer_trash=True)
                                except Exception:
                                    try:
                                        from utils.file.file_utils import delete_with_sidecar
                                        delete_with_sidecar(p, prefer_trash=False)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                            
                    deleted_paths.append(str(p))
                except Exception:
                    pass

            if not deleted_paths:
                NotificationManager.instance().show_warning("错误", "删除失败")
                return

            try:
                deleted_keys = set()
                for p in deleted_paths:
                    try:
                        deleted_keys.add(self._normalize_path_key(p))
                    except Exception:
                        deleted_keys.add(str(p))
            except Exception:
                deleted_keys = set(deleted_paths)

            try:
                folder_key = self._get_current_folder_key()
                if folder_key and folder_key in self._stash_by_folder:
                    self._stash_by_folder[folder_key] = set(self._stash_by_folder.get(folder_key) or set()) - deleted_keys
                    self._schedule_save_stash_state()
            except Exception:
                pass

            try:
                self._all_image_files = [it for it in (self._all_image_files or []) if isinstance(it, dict) and self._normalize_path_key(it.get("path", "")) not in deleted_keys]
            except Exception:
                pass
            try:
                self.image_files = [it for it in (self.image_files or []) if isinstance(it, dict) and self._normalize_path_key(it.get("path", "")) not in deleted_keys]
            except Exception:
                pass
            try:
                if getattr(self, "current_preview_path", None):
                    try:
                        pk = self._normalize_path_key(self.current_preview_path)
                    except Exception:
                        pk = str(self.current_preview_path)
                    if pk in deleted_keys:
                        self.clear_preview()
            except Exception:
                pass

            try:
                request_id = int(getattr(self, "_folder_load_request_id", 0))
            except Exception:
                request_id = 0
            files = self._filter_files_for_display(getattr(self, "_all_image_files", []) or [])
            self._apply_files_view(request_id, files)

            NotificationManager.instance().show_toast(f"已删除 {len(deleted_paths)} 条记录")
            try:
                QTimer.singleShot(0, self._start_build_focus_detect_virtual_folders)
            except Exception:
                pass
            return

        """删除选中的图片文件（真实文件模式）"""
        selected_files = self.get_selected_files()
        if not selected_files:
            NotificationManager.instance().show_warning("提示", "请先选择图片")
            return
        if not NotificationManager.instance().ask_confirmation("确认删除", f"确定要删除选中的 {len(selected_files)} 个文件吗？"):
            return

        deleted_paths = []
        for f in selected_files:
            p = f.get("path")
            if not p:
                continue
            try:
                if os.path.exists(p):
                    from utils.file.file_utils import delete_with_sidecar
                    delete_with_sidecar(p, prefer_trash=False)
                deleted_paths.append(p)
            except Exception:
                pass

        if not deleted_paths:
            NotificationManager.instance().show_warning("错误", "删除失败")
            return

        try:
            deleted_set = set(deleted_paths)
            self.image_files = [img for img in (self.image_files or []) if img.get("path") not in deleted_set]
        except Exception:
            pass

        try:
            if getattr(self, "current_preview_path", None) in set(deleted_paths):
                self.clear_preview()
        except Exception:
            pass

        try:
            folder = self.settings_manager.get("import/last_folder", "") or ""
            if folder and os.path.exists(folder):
                self.load_images(folder, recursive=False)
        except Exception:
            pass

        NotificationManager.instance().show_toast(f"已删除 {len(deleted_paths)} 个文件")

    def on_mode_switch_toggled(self, state):
        """处理模式切换开关变化"""
        self.is_virtual_mode = (state == Qt.CheckState.Checked.value)
        try:
            if not bool(getattr(self, "_focus_detect_running", False)):
                self._thumb_ui_suspended = False
        except Exception:
            try:
                self._thumb_ui_suspended = False
            except Exception:
                pass
        try:
            if getattr(self, "loading_overlay", None):
                self.loading_overlay.hide()
        except Exception:
            pass
        try:
            self._force_hide_startup_mask()
        except Exception:
            pass
        try:
            self._hide_focus_detect_mask()
        except Exception:
            pass
        try:
            overlay = getattr(self, "_focus_progress_overlay", None)
            if overlay is not None and hasattr(overlay, "set_progress"):
                overlay.set_progress(visible=False)
        except Exception:
            pass
        try:
            if not bool(getattr(self, "_focus_detect_running", False)):
                self._startup_mask_enabled = True
        except Exception:
            pass
        
        # 1. 更新预览面板 (PreviewPanel) 的按钮可见性
        try:
            if hasattr(self, "preview_panel") and self.preview_panel:
                # PreviewPanel 使用 set_actions_visible 控制按钮显示
                if hasattr(self.preview_panel, "set_actions_visible"):
                    self.preview_panel.set_actions_visible(self.is_virtual_mode)
        except Exception:
            pass
            
        # 2. 更新 InfoPanel 的扩展信息显示
        # 如果 InfoPanel 没有提供 set_extended_info_visible，则这里需要修改 InfoPanel
        # 假设我们已经修改了 InfoPanel
        try:
            if hasattr(self, "info_panel") and self.info_panel:
                if hasattr(self.info_panel, "set_extended_info_visible"):
                    self.info_panel.set_extended_info_visible(self.is_virtual_mode)
        except Exception:
            pass
            
        try:
            if hasattr(self, "grid_view") and self.grid_view is not None and hasattr(self.grid_view, "_details_compact"):
                if self.is_virtual_mode:
                    self.grid_view._details_compact = int(getattr(self, "display_mode", 1) or 1) != ImageThumbnail.MODE_WITH_DETAILS
                else:
                    self.grid_view._details_compact = True
                try:
                    self.grid_view.set_display_mode(int(getattr(self, "display_mode", 1) or 1))
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if not self.is_virtual_mode:
                self._virtual_fav_filter = False
                self._virtual_rating_filter = 0
            else:
                self._virtual_fav_filter = False
                self._virtual_rating_filter = 0
        except Exception:
            pass
        try:
            if hasattr(self, "toolbar") and self.toolbar:
                if getattr(self.toolbar, "fav_btn", None) is not None:
                    try:
                        self.toolbar.set_fav_checked(False)
                    except Exception:
                        self.toolbar.fav_btn.setChecked(False)
                if getattr(self.toolbar, "star_rating", None) is not None:
                    try:
                        self.toolbar.set_rating(0, emit_signal=False)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self._update_toolbar_for_mode()
        except Exception:
            pass
        try:
            self._sync_focus_overlay_toolbar_buttons_from_settings()
        except Exception:
            pass
        try:
            self._apply_sort_options_for_mode()
        except Exception:
            pass
        try:
            if hasattr(self, "folder_panel") and self.folder_panel is not None and hasattr(self.folder_panel, "folder_tree"):
                if self.is_virtual_mode:
                    self.folder_panel.folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
                else:
                    self.folder_panel.folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        except Exception:
            pass
        
        if self.is_virtual_mode:
            # 切换到虚拟模式
            self.folder_panel.set_override_strict_mode(None) # Use settings
            self.folder_panel.folder_tree.clear()
            try:
                if hasattr(self, "thumbnail_loader"):
                    self.thumbnail_loader.cancel_pending()
            except Exception:
                pass
            try:
                if hasattr(self, "grid_view") and hasattr(self.grid_view, "clear_thumbnails"):
                    self.grid_view.clear_thumbnails()
            except Exception:
                pass
            try:
                self.clear_preview()
            except Exception:
                pass
            try:
                self.image_files = []
                self._all_image_files = []
                self._thumb_by_path = {}
                self.loaded_count = 0
                self.selected_count = 0
                self._requested_paths = set()
                self._requested_exif_paths = set()
                self._loaded_paths = set()
            except Exception:
                pass
            try:
                self._build_focus_detect_virtual_folders()
            except Exception:
                pass
            try:
                QTimer.singleShot(0, self._reload_virtual_focus_detect_view)
            except Exception:
                pass
            try:
                if bool(getattr(self, "_pending_virtual_focus_reload", False)):
                    self._pending_virtual_focus_reload = False
                    QTimer.singleShot(0, self._reload_virtual_focus_detect_view)
            except Exception:
                pass
            try:
                if hasattr(self, "grid_view") and self.grid_view is not None:
                    if getattr(self.grid_view, "is_virtualized", False) and hasattr(self.grid_view, "list_view"):
                        QTimer.singleShot(0, self.grid_view.list_view.setFocus)
                    else:
                        QTimer.singleShot(0, self.grid_view.scroll_area.setFocus)
            except Exception:
                pass
        else:
            # 切换回真实模式
            self.folder_panel.set_override_strict_mode(False) # Disable strict for real files
            try:
                if hasattr(self, "folder_panel") and self.folder_panel is not None and hasattr(self.folder_panel, "folder_tree"):
                    self.folder_panel.folder_tree.clear()
            except Exception:
                pass

            root_paths = self.settings_manager.get("import/root_paths", []) or []
            root_paths = [p for p in root_paths if p and os.path.exists(str(p))]
            try:
                import tempfile
                temp_root = os.path.normcase(os.path.normpath(tempfile.gettempdir()))
            except Exception:
                temp_root = ""
            if temp_root:
                filtered = []
                changed = False
                for p in root_paths:
                    s = str(p)
                    try:
                        norm = os.path.normcase(os.path.normpath(s))
                    except Exception:
                        norm = s
                    if norm.startswith(temp_root + os.sep) or norm == temp_root:
                        changed = True
                        continue
                    filtered.append(s)
                if changed:
                    root_paths = filtered
                    try:
                        self.settings_manager.set("import/root_paths", root_paths)
                        self.settings_manager.sync()
                    except Exception:
                        pass
            if root_paths:
                self.folder_panel.add_root_folders(root_paths)
                self._save_import_root_paths(self._get_import_root_paths_from_tree())

            auto_folder = self.settings_manager.get("import/last_folder", "") or ""
            if temp_root:
                try:
                    auto_norm = os.path.normcase(os.path.normpath(str(auto_folder)))
                except Exception:
                    auto_norm = str(auto_folder)
                if auto_norm.startswith(temp_root + os.sep) or auto_norm == temp_root:
                    auto_folder = ""
                    try:
                        self.settings_manager.set("import/last_folder", "")
                        self.settings_manager.sync()
                    except Exception:
                        pass
            if auto_folder and os.path.exists(auto_folder):
                self.load_images(auto_folder, recursive=False)
            else:
                path = self.settings_manager.get("import/last_path")
                if path and os.path.exists(path):
                    if not root_paths:
                        self.folder_panel.add_root_folders([path])
                        self._save_import_root_paths(self._get_import_root_paths_from_tree())
                    self.load_images(path, recursive=False)

        try:
            self._refresh_focus_progress_ui()
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._update_focus_threshold_panel_visibility)
        except Exception:
            pass

    def _update_toolbar_for_mode(self):
        show_filter = bool(self.is_virtual_mode)
        filter_btn = getattr(self.toolbar, "filter_btn", None) if hasattr(self, "toolbar") else None
        filter_panel = getattr(self.toolbar, "filter_panel", None) if hasattr(self, "toolbar") else None
        if filter_btn is not None:
            if not show_filter:
                try:
                    filter_btn.blockSignals(True)
                    filter_btn.setChecked(False)
                finally:
                    try:
                        filter_btn.blockSignals(False)
                    except Exception:
                        pass
            filter_btn.setVisible(show_filter)
        if filter_panel is not None:
            if not show_filter:
                try:
                    filter_panel.hide()
                except Exception:
                    pass
        try:
            show_quick_filters = bool(self.is_virtual_mode)
            if hasattr(self, "toolbar") and self.toolbar:
                if getattr(self.toolbar, "fav_btn", None) is not None:
                    if not show_quick_filters:
                        try:
                            self.toolbar.set_fav_checked(False)
                        except Exception:
                            try:
                                self.toolbar.fav_btn.setChecked(False)
                            except Exception:
                                pass
                    self.toolbar.fav_btn.setVisible(show_quick_filters)
                if getattr(self.toolbar, "rating_filter_btn", None) is not None:
                    self.toolbar.rating_filter_btn.setVisible(show_quick_filters)
                if getattr(self.toolbar, "star_rating", None) is not None:
                    if not show_quick_filters:
                        try:
                            self.toolbar.set_rating(0, emit_signal=False)
                        except Exception:
                            pass
                    self.toolbar.star_rating.setVisible(show_quick_filters)
                if getattr(self.toolbar, "compare_btn", None) is not None:
                    self.toolbar.compare_btn.setVisible(show_quick_filters)
                if getattr(self.toolbar, "delete_btn", None) is not None:
                    self.toolbar.delete_btn.setVisible(show_quick_filters)
                if getattr(self.toolbar, "spray_btn", None) is not None:
                    self.toolbar.spray_btn.setVisible(show_quick_filters)
        except Exception:
            pass
        try:
            if hasattr(self, "recognition_btn") and self.recognition_btn is not None:
                self.recognition_btn.setEnabled(not bool(getattr(self, "_focus_detect_running", False)))
        except Exception:
            pass
        try:
            show = bool(self.is_virtual_mode)
            enabled = not bool(getattr(self, "_focus_detect_running", False))
            if getattr(self, "show_subject_rect_btn", None) is not None:
                self.show_subject_rect_btn.setVisible(show)
                self.show_subject_rect_btn.setEnabled(bool(enabled))
            if getattr(self, "show_focus_point_btn", None) is not None:
                self.show_focus_point_btn.setVisible(show)
                self.show_focus_point_btn.setEnabled(bool(enabled))
            if getattr(self, "show_auto_label_btn", None) is not None:
                self.show_auto_label_btn.setVisible(show)
                self.show_auto_label_btn.setEnabled(bool(enabled))
        except Exception:
            pass
        try:
            self._update_focus_progress_toolbar_btn()
        except Exception:
            pass
        try:
            self._update_focus_stop_toolbar_btn()
        except Exception:
            pass
        try:
            if hasattr(self, "batch_rename_btn") and self.batch_rename_btn is not None:
                self.batch_rename_btn.setVisible(not bool(self.is_virtual_mode))
        except Exception:
            pass
    
    def _update_mode_switch_theme(self):
        """更新模式切换组件的主题颜色"""
        cm = ColorManager.instance()
        icon_color = cm.get("theme.text.dark")
        primary_color = cm.get("theme.primary")
        
        # 更新图标颜色
        if hasattr(self, "label_real"):
            self.label_real.setPixmap(qta.icon('mdi6.file', color=icon_color).pixmap(16, 16))
        if hasattr(self, "label_virtual"):
            self.label_virtual.setPixmap(qta.icon('fa6b.files-pinwheel', color=icon_color).pixmap(16, 16))
        
        # 更新开关颜色
        if hasattr(self, "mode_switch"):
            self.mode_switch.set_track_color_on(primary_color)
        
        # 更新启动遮罩样式
        self._update_startup_mask_theme()
        try:
            self._apply_import_toolbar_theme_styles()
        except Exception:
            pass
        try:
            splitter_bg = cm.get("popup.border.primary")
            primary = cm.get("theme.primary")
            if hasattr(self, "preview_info_splitter") and self.preview_info_splitter is not None:
                self.preview_info_splitter.setStyleSheet(f"""
                    QSplitter::handle {{
                        background-color: {splitter_bg};
                        height: 1px;
                    }}
                    QSplitter::handle:hover {{
                        background-color: {primary};
                    }}
                """)
        except Exception:
            pass
        try:
            splitter_bg = cm.get("popup.border.primary")
            primary = cm.get("theme.primary")
            if hasattr(self, "content_splitter") and self.content_splitter is not None:
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
        except Exception:
            pass

    def _apply_import_toolbar_theme_styles(self):
        cm = ColorManager.instance()
        text_dark = cm.get("theme.text.dark")
        hover_bg = cm.get("theme.background.dark")
        pressed_bg = cm.get("theme.background.dark")
        checked_bg = cm.get("theme.primary")
        border = cm.get("popup.border.primary")
        tooltip_text = cm.get("tooltip.text")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_border = cm.get("tooltip.border")

        base = f"""
            QPushButton {{ background: transparent; border: none; border-radius: 4px; padding: 4px; }}
            QPushButton:hover {{ background-color: {hover_bg}; }}
            QPushButton:pressed {{ background-color: {pressed_bg}; }}
            QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
        """
        toggle = base + f"""
            QPushButton:checked {{
                background-color: {checked_bg};
                border: 1px solid {border};
            }}
        """

        for btn in [
            getattr(self, "focus_threshold_btn", None),
            getattr(self, "batch_rename_btn", None),
            getattr(self, "toolbar_geo_btn", None),
            getattr(self, "toolbar_track_match_btn", None),
        ]:
            if btn is None:
                continue
            try:
                btn.setStyleSheet(base)
            except Exception:
                pass

        for btn in [
            getattr(self, "show_subject_rect_btn", None),
            getattr(self, "show_focus_point_btn", None),
            getattr(self, "show_auto_label_btn", None),
            getattr(self, "stash_filter_btn", None),
        ]:
            if btn is None:
                continue
            try:
                btn.setStyleSheet(toggle)
            except Exception:
                pass

        try:
            if getattr(self, "focus_threshold_btn", None) is not None:
                self.focus_threshold_btn.setIcon(qta.icon("mdi6.tune", color=text_dark))
        except Exception:
            pass
        try:
            if getattr(self, "focus_stop_btn", None) is not None:
                self.focus_stop_btn.setIcon(qta.icon("mdi6.stop-circle-outline", color=text_dark))
        except Exception:
            pass
        try:
            if getattr(self, "show_subject_rect_btn", None) is not None:
                self.show_subject_rect_btn.setIcon(qta.icon("mdi6.crop-square", color=text_dark))
        except Exception:
            pass
        try:
            if getattr(self, "show_focus_point_btn", None) is not None:
                self.show_focus_point_btn.setIcon(qta.icon("mdi6.focus-field", color=text_dark))
        except Exception:
            pass
        try:
            if getattr(self, "show_auto_label_btn", None) is not None:
                self.show_auto_label_btn.setIcon(qta.icon("mdi6.label-outline", color=text_dark))
        except Exception:
            pass
        try:
            if getattr(self, "stash_filter_btn", None) is not None:
                self.stash_filter_btn.setIcon(qta.icon("mdi6.tag-check", color=text_dark, options=[{"scale_factor": 1.1}]))
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
        try:
            if getattr(self, "batch_rename_btn", None) is not None:
                self.batch_rename_btn.setIcon(qta.icon("mdi6.rename-box", color=text_dark, options=[{"scale_factor": 1.1}]))
        except Exception:
            pass
    
    def _update_startup_mask_theme(self):
        """更新启动遮罩的主题颜色"""
        if not hasattr(self, "_startup_mask"):
            return
        cm = ColorManager.instance()
        startup_mask_bg = cm.to_qss_color("library_page.startup_mask.background", default="#f5f5f5")
        text_color = cm.get("theme.text.dark")
        self._startup_mask.setStyleSheet(f"""
            QFrame {{
                background-color: {startup_mask_bg};
                border: none;
            }}
        """)
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

    def on_selection_changed(self, count=None):
        """处理图片选择变化"""
        if count is not None:
              self.selected_count = count
        else:
              selected_items = self.grid_view.get_selected_thumbnails()
              self.selected_count = len(selected_items)
        if self.has_valid_folder:
            self.stats_changed.emit(len(self.image_files), self.loaded_count, self.selected_count)
        try:
            if hasattr(self, "detail_panel") and self.detail_panel:
                return
        except Exception:
            pass
        try:
            selected = self.get_selected_files() or []
        except Exception:
            selected = []
        if len(selected) == 1:
            try:
                p = selected[0].get("path")
            except Exception:
                p = None
            if p and p != getattr(self, "current_preview_path", None):
                self._schedule_preview(p)

    def _on_show_subject_rect_toggled(self, checked: bool):
        try:
            self.settings_manager.set("focus_detect_ui/show_subject_rect", bool(checked))
            self.settings_manager.sync()
        except Exception:
            pass
        try:
            sm2 = getattr(getattr(self, "cache_manager", None), "settings_manager", None)
            if sm2 is not None:
                sm2.set("focus_detect_ui/show_subject_rect", bool(checked))
                sm2.sync()
        except Exception:
            pass
        try:
            gv = getattr(self, "grid_view", None)
            if gv is not None and hasattr(gv, "set_settings_manager"):
                gv.set_settings_manager(self.settings_manager)
        except Exception:
            pass
        self._refresh_thumbnail_overlays()

    def _on_show_focus_point_toggled(self, checked: bool):
        try:
            self.settings_manager.set("focus_detect_ui/show_focus_point", bool(checked))
            self.settings_manager.sync()
        except Exception:
            pass
        try:
            sm2 = getattr(getattr(self, "cache_manager", None), "settings_manager", None)
            if sm2 is not None:
                sm2.set("focus_detect_ui/show_focus_point", bool(checked))
                sm2.sync()
        except Exception:
            pass
        try:
            gv = getattr(self, "grid_view", None)
            if gv is not None and hasattr(gv, "set_settings_manager"):
                gv.set_settings_manager(self.settings_manager)
        except Exception:
            pass
        self._refresh_thumbnail_overlays()
        if bool(checked):
            try:
                cur = str(getattr(self, "_current_folder_path", "") or "")
            except Exception:
                cur = ""
            if bool(getattr(self, "is_virtual_mode", False)) and isinstance(cur, str) and (cur.startswith("virtual://focus_detect?") or cur.startswith("virtual://focus_detect_burst?")):
                try:
                    p0 = str(getattr(self, "current_preview_path", "") or "")
                except Exception:
                    p0 = ""
                fp = None
                if p0 and hasattr(self, "db"):
                    try:
                        rec = self.db.get_result_by_path(p0, table_name="import_cache")
                    except Exception:
                        rec = None
                    if isinstance(rec, dict):
                        fp = rec.get("focus_point")
                if not fp:
                    try:
                        NotificationManager.instance().show_toast("未找到对焦点数据")
                    except Exception:
                        pass

    def _on_show_auto_label_toggled(self, checked: bool):
        try:
            self.settings_manager.set("import/virtual_auto_label", bool(checked))
            self.settings_manager.sync()
        except Exception:
            pass
        try:
            auto_enabled = bool(checked)
        except Exception:
            auto_enabled = True
        gv = getattr(self, "grid_view", None)
        if gv is not None and getattr(gv, "is_virtualized", False):
            try:
                thumbs = getattr(gv, "thumbnails", None) or []
            except Exception:
                thumbs = []
            for t in (thumbs or []):
                try:
                    info = getattr(t, "image_info", None)
                except Exception:
                    info = None
                if not isinstance(info, dict):
                    continue
                p = info.get("path")
                if not p:
                    continue
                if auto_enabled and bool(getattr(self, "is_virtual_mode", False)):
                    try:
                        info["auto_label"] = self._auto_label_for_focus_status(info.get("focus_status"))
                    except Exception:
                        info["auto_label"] = None
                else:
                    try:
                        info.pop("auto_label", None)
                    except Exception:
                        pass
                try:
                    t.update()
                except Exception:
                    pass
            self._refresh_thumbnail_overlays()
            return
        try:
            for it in (getattr(self, "_all_image_files", None) or []):
                if not isinstance(it, dict):
                    continue
                p = it.get("path")
                if not p:
                    continue
                if auto_enabled and bool(getattr(self, "is_virtual_mode", False)):
                    try:
                        it["auto_label"] = self._auto_label_for_focus_status(it.get("focus_status"))
                    except Exception:
                        it["auto_label"] = None
                else:
                    try:
                        it.pop("auto_label", None)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            for it in (getattr(self, "image_files", None) or []):
                if not isinstance(it, dict):
                    continue
                p = it.get("path")
                if not p:
                    continue
                if auto_enabled and bool(getattr(self, "is_virtual_mode", False)):
                    try:
                        it["auto_label"] = self._auto_label_for_focus_status(it.get("focus_status"))
                    except Exception:
                        it["auto_label"] = None
                else:
                    try:
                        it.pop("auto_label", None)
                    except Exception:
                        pass
        except Exception:
            pass
        self._refresh_thumbnail_overlays()

    def _refresh_thumbnail_overlays(self):
        gv = getattr(self, "grid_view", None)
        if gv is None:
            return
        if getattr(gv, "is_virtualized", False):
            try:
                if hasattr(gv, "list_view") and gv.list_view is not None:
                    gv.list_view.viewport().update()
                    gv.list_view.update()
                elif hasattr(gv, "thumbnails_container") and gv.thumbnails_container is not None:
                    gv.thumbnails_container.update()
                else:
                    gv.update()
            except Exception:
                try:
                    gv.update()
                except Exception:
                    pass
            return
        thumbs = getattr(gv, "thumbnails", None)
        if isinstance(thumbs, list) and thumbs:
            for t in thumbs:
                try:
                    t.update()
                except Exception:
                    pass
            return
        try:
            gv.update()
        except Exception:
            pass

    def _auto_label_for_focus_status(self, focus_status):
        try:
            st = str(focus_status or "").strip()
        except Exception:
            st = ""
        if not st:
            return None
        m = {
            "Sharp": "Green",
            "锐利": "Green",
            "Normal": "Cyan",
            "普通": "Cyan",
            "Blurry": "Red",
            "虚焦": "Red",
            "Minimal": "Purple",
            "极小": "Purple",
            "ExpFrame": "Orange",
            "爆框": "Orange",
            "NoBird": "Gray",
            "无鸟": "Gray",
        }
        return m.get(st)

    def save_cache(self):
        """保存缓存（供主窗口退出时调用）"""
        return
