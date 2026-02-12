from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QStackedWidget, QLabel, 
                             QPushButton, QButtonGroup, QApplication, QStatusBar)
from PyQt6.QtCore import Qt, QSize, QTimer, QEvent, QPoint, QThreadPool, QRunnable, QObject, pyqtSignal

from ui.image_library_page import ImageLibraryPage
from ui.settings_page import SettingsPage
from ui.guide_page import GuidePage
from ui.info_page import InfoPage
from ui.utils.notification_manager import NotificationManager
from ui.utils.status_manager import StatusManager
from ui.utils.color_manager import ColorManager
from ui.utils.app_icon import get_app_icon
from ui.import_page import ImportPage

import qtawesome as qta
import os
import sys
import psutil
import time

from utils.setting.settings_manager import SettingsManager
from utils.paths import PathManager
from ui.utils.window_effect import apply_dark_title_bar
from utils.log_manager import LogManager
from utils.system.gpu_monitor import get_gpu_util_text
from utils.guide_manager import GuideManager


class GpuUtilWorkerSignals(QObject):
    result = pyqtSignal(str)


class GpuUtilWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = GpuUtilWorkerSignals()

    def run(self):
        try:
            gpu_text = get_gpu_util_text(timeout_s=0.9)
        except Exception:
            gpu_text = "--"
        try:
            self.signals.result.emit(gpu_text)
        except RuntimeError:
            return

class MainWindow(QMainWindow):
    def _create_dev_placeholder(self, title: str):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(10)
        lay.addStretch()
        lbl = QLabel("开发中")
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet("font-size: 22px; font-weight: 600;")
        lay.addWidget(lbl)
        sub = QLabel(f"{str(title or '')} 功能正在开发中")
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        sub.setStyleSheet("font-size: 13px; opacity: 0.85;")
        lay.addWidget(sub)
        lay.addStretch()
        return w

    def __init__(self, defer_startup=False):
        super().__init__()
        self.settings_manager = SettingsManager()
        self._entered_main_interface = False
        self._restore_defaults_requested = False
        self._defer_startup = bool(defer_startup)
        self._startup_preloaded = False
        
        # 调试控制台计数器
        self.settings_click_count = 0
        self.settings_click_timer = QTimer()
        self.settings_click_timer.setInterval(3000) # 3秒重置
        self.settings_click_timer.timeout.connect(self.reset_click_count)

        self.setWindowTitle("栖图")
        self.resize(1560, 920)
        self.setMinimumSize(800, 600)  # 设置最小尺寸，防止内容撑大导致无法缩小

        # 应用 Windows 11 云母/深色标题栏效果，颜色与侧边栏一致
        cm = ColorManager.instance()
        title_bar_color = cm.get("theme.sidebar")
        apply_dark_title_bar(self, title_bar_color, cm.get("theme.text.light"))

        # 主容器
        central_widget = QWidget()
        self.central_widget = central_widget
        self.setCentralWidget(central_widget)
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        
        # 初始化通知管理器
        NotificationManager.instance().set_parent(self)
        
        # 内容区域容器
        self.content_container = QWidget()
        self.content_container.setAutoFillBackground(True)
        central_layout.addWidget(self.content_container, 1)

        # ========== 底部状态栏 ==========
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        status_bg = cm.get("theme.background.primary")
        status_border = cm.get("popup.border.primary")
        status_text = cm.get("theme.text.dark")
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {status_bg};
                border-top: 1px solid {status_border};
                color: {status_text};
                font-size: 11px;
            }}
            QLabel {{
                padding: 0 5px;
            }}
        """)
        central_layout.addWidget(self.status_bar)

        # 状态栏组件
        # 1. 任务状态 (最左)
        self.lbl_task_status = QLabel("就绪")
        self.status_bar.addWidget(self.lbl_task_status)
        
        # 2. 图片计数 (左侧第二个)
        self.lbl_image_counts = QLabel("")
        self.status_bar.addWidget(self.lbl_image_counts)
        
        # 3. CPU/Mem (最右)
        self.lbl_sys_status = QLabel("CPU: 0% | Mem: 0%")
        self.status_bar.addPermanentWidget(self.lbl_sys_status)
        
        # 连接任务管理器信号
        StatusManager.instance().status_changed.connect(self.on_task_status_changed)
        
        # 系统资源监控定时器
        self.sys_timer = QTimer(self)
        self.sys_timer.timeout.connect(self.update_sys_status)
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        self.sys_timer.start(1000) # 0.5秒更新一次
        self._gpu_util_text = "--"
        self._gpu_query_running = False
        self._gpu_last_request_ts = 0.0
        self._gpu_thread_pool = QThreadPool.globalInstance()
        
        # 引导页面 (默认隐藏，覆盖在内容区域之上，或者替代内容区域)
        # 这里我们选择替代策略：如果需要引导，只显示引导页，否则显示主界面
        
        self.guide_page = GuidePage()
        self.guide_page.setup_completed.connect(self.on_guide_completed)
        self.guide_page.hide() # 默认隐藏
        
        # 主界面内容
        self.main_widget = QWidget()
        self.main_widget.setAutoFillBackground(True)
        main_layout = QHBoxLayout(self.main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 将主界面和引导页都添加到 content_container 的布局中
        # 使用 StackedLayout 可能更合适，或者简单的显示/隐藏
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.addWidget(self.main_widget)
        self.content_layout.addWidget(self.guide_page)

        # ========== 最左侧：单个图标的垂直工具栏 ==========
        self.icon_toolbar = QWidget()
        self.icon_toolbar.setFixedWidth(60)
        sidebar_bg = cm.get("theme.sidebar")
        self.icon_toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {sidebar_bg};
            }}
        """)
        icon_layout = QVBoxLayout(self.icon_toolbar)
        icon_layout.setContentsMargins(5, 10, 5, 10)
        icon_layout.setSpacing(5)
        # 侧边栏按钮样式
        button_color = cm.get("theme.primary")
        button_hover = cm.get("theme.background.primary")
        sidebar_btn_bg = cm.get("theme.sidebar")
        sidebar_btn_checked = cm.get("theme.primary")
        sidebar_btn_hover = cm.get("theme.primary")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        sidebar_btn_style = f"""
            QPushButton {{
                background-color: {sidebar_btn_bg};
                border: none;
                border-radius: 5px;
                color: {button_color};
            }}
            QPushButton:checked {{
                background-color: {sidebar_btn_checked};
            }}
            QPushButton:hover {{
                background-color: {button_hover};
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
            }}
        """
        # 创建按钮组（互斥选择）
        self.sidebar_btn_group = QButtonGroup(self)
        self.sidebar_btn_group.setExclusive(True)
        self._sidebar_buttons = []
        self._sidebar_icon_map = []
        self.btn_library = QPushButton()
        self.btn_library.setIcon(qta.icon('fa6.images', color=button_color))
        self.btn_library.setIconSize(QSize(28, 28))
        self.btn_library.setFixedSize(50, 50)
        self.btn_library.setToolTip("图片库")
        self.btn_library.setCheckable(True)
        self.btn_library.setChecked(True)
        self.btn_library.setStyleSheet(sidebar_btn_style)
        self.sidebar_btn_group.addButton(self.btn_library, 0)
        icon_layout.addWidget(self.btn_library)
        self._sidebar_buttons.append(self.btn_library)
        self._sidebar_icon_map.append((self.btn_library, "fa6.image", "fa6s.image"))
        # 图片导入按钮
        self.btn_import = QPushButton()
        self.btn_import.setIcon(qta.icon('mdi6.file-import-outline', color=button_color))
        self.btn_import.setIconSize(QSize(28, 28))
        self.btn_import.setFixedSize(50, 50)
        self.btn_import.setToolTip("导入")
        self.btn_import.setCheckable(True)
        self.btn_import.setStyleSheet(sidebar_btn_style)
        self.sidebar_btn_group.addButton(self.btn_import, 1)
        # 确保按钮点击时切换到导入页面 (索引 1)
        self.btn_import.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        icon_layout.addWidget(self.btn_import)
        self._sidebar_buttons.append(self.btn_import)
        self._sidebar_icon_map.append((self.btn_import, "mdi6.file-import-outline", "mdi6.file-import"))
        # 数据图表按钮
        self.btn_filter = QPushButton()
        self.btn_filter.setIcon(qta.icon('ph.presentation-chart-bold', color=button_color))
        self.btn_filter.setIconSize(QSize(28, 28))
        self.btn_filter.setFixedSize(50, 50)
        self.btn_filter.setToolTip("数据图表")
        self.btn_filter.setCheckable(True)
        self.btn_filter.setStyleSheet(sidebar_btn_style)
        self.sidebar_btn_group.addButton(self.btn_filter, 2)
        icon_layout.addWidget(self.btn_filter)
        self._sidebar_buttons.append(self.btn_filter)
        self._sidebar_icon_map.append((self.btn_filter, "ph.presentation-chart-bold", "ph.presentation-chart-fill"))
        # 奖章页面按钮
        self.btn_milestone = QPushButton()
        self.btn_milestone.setIcon(qta.icon('ri.medal-line', color=button_color))
        self.btn_milestone.setIconSize(QSize(28, 28))
        self.btn_milestone.setFixedSize(50, 50)
        self.btn_milestone.setToolTip("奖章页面（开发中）")
        self.btn_milestone.setCheckable(True)
        self.btn_milestone.setStyleSheet(sidebar_btn_style)
        self.sidebar_btn_group.addButton(self.btn_milestone, 3)
        icon_layout.addWidget(self.btn_milestone)
        self._sidebar_buttons.append(self.btn_milestone)
        self._sidebar_icon_map.append((self.btn_milestone, "ri.medal-line", "ri.medal-fill"))
        icon_layout.addStretch()
        self.btn_manual = QPushButton()
        self.btn_manual.setIcon(qta.icon('fa6s.book', color=button_color))
        self.btn_manual.setIconSize(QSize(28, 28))
        self.btn_manual.setFixedSize(50, 50)
        self.btn_manual.setToolTip("使用说明书")
        self.btn_manual.setStyleSheet(sidebar_btn_style)
        self.btn_manual.clicked.connect(self.open_user_manual)
        icon_layout.addWidget(self.btn_manual)
        self._sidebar_buttons.append(self.btn_manual)
        self._sidebar_icon_map.append((self.btn_manual, "fa6s.book", "fa6s.book"))
        # 设置按钮
        self.btn_settings = QPushButton()
        self.btn_settings.setIcon(qta.icon('mdi.cog', color=button_color))
        self.btn_settings.setIconSize(QSize(28, 28))
        self.btn_settings.setFixedSize(50, 50)
        self.btn_settings.setFixedSize(50, 50)
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setCheckable(True)
        self.btn_settings.setStyleSheet(sidebar_btn_style)
        # 移除 clicked 连接，改为 installEventFilter
        # btn_settings.clicked.connect(self.on_settings_clicked)
        self.btn_settings.installEventFilter(self)
        self.sidebar_btn_group.addButton(self.btn_settings, 4)
        icon_layout.addWidget(self.btn_settings)
        self._sidebar_buttons.append(self.btn_settings)
        self._sidebar_icon_map.append((self.btn_settings, "mdi.cog", "mdi.cog-box"))

        # 关于按钮
        self.btn_info = QPushButton()
        self.btn_info.setIcon(qta.icon('mdi.information-outline', color=button_color))
        self.btn_info.setIconSize(QSize(28, 28))
        self.btn_info.setFixedSize(50, 50)
        self.btn_info.setToolTip("关于软件")
        self.btn_info.setCheckable(True)
        self.btn_info.setStyleSheet(sidebar_btn_style)
        self.sidebar_btn_group.addButton(self.btn_info, 5)
        icon_layout.addWidget(self.btn_info)
        self._sidebar_buttons.append(self.btn_info)
        self._sidebar_icon_map.append((self.btn_info, "mdi.information-outline", "mdi.information"))

        for _btn in self._sidebar_buttons:
            try:
                _btn.toggled.connect(self._update_sidebar_icons)
            except Exception:
                pass
        self._update_sidebar_icons()

        main_layout.addWidget(self.icon_toolbar)

        # ========== 右侧：页面堆栈 ==========
        self.pages = QStackedWidget()
        self.pages.setAutoFillBackground(True)
        # 图片库页面
        self.page_library = ImageLibraryPage()
        self.pages.addWidget(self.page_library)
        # 连接状态更新信号
        self.page_library.stats_changed.connect(self.on_library_stats_changed)
        # 图片导入页面
        self.page_import = ImportPage()
        self.pages.addWidget(self.page_import)
        self.page_import.stats_changed.connect(self.on_import_stats_changed)
        try:
            self.page_import.import_to_library_succeeded.connect(self.page_library.on_import_to_library_succeeded)
        except Exception:
            pass
        self._charts_page_loaded = False
        self._charts_page_loading = False
        self.pages.addWidget(self._create_dev_placeholder("数据图表"))
        self.pages.addWidget(self._create_dev_placeholder("奖章页面"))
        # 设置页面
        self.page_settings = SettingsPage()
        self.pages.addWidget(self.page_settings)
        # 连接设置变化信号
        self.page_settings.library_thumbnail_setting_changed.connect(self.page_library.reload_thumbnails_config)
        self.page_settings.import_thumbnail_setting_changed.connect(self.page_import.reload_thumbnails_config)
        self.page_settings.thumbnail_ui_perf_setting_changed.connect(self.page_library.update_thumbnail_ui_perf_config)
        self.page_settings.thumbnail_ui_perf_setting_changed.connect(self.page_import.update_thumbnail_ui_perf_config)
        try:
            self.page_import.folder_panel.folderRemovedFromTree.connect(self.page_library.clear_if_showing_folder)
            self.page_import.folder_panel.folderDeletedOnDisk.connect(self.page_library.clear_if_showing_folder)
        except Exception:
            pass
        
        # 关于页面
        self.page_info = InfoPage()
        self.pages.addWidget(self.page_info)
        
        # 连接按钮组到页面切换
        self.sidebar_btn_group.idClicked.connect(self.pages.setCurrentIndex)
        self.pages.currentChanged.connect(self.on_page_changed)
        main_layout.addWidget(self.pages, 1)

        self._page_cache_release_timers = {}
        self._page_cache_release_deadlines = {}
        self._last_main_page_index = int(self.pages.currentIndex())
        for _idx in (0, 1):
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda idx=_idx: self._on_page_cache_release_timeout(int(idx)))
            self._page_cache_release_timers[int(_idx)] = t

        self._apply_theme_styles()
        try:
            ColorManager.instance().register_listener(self._apply_theme_styles)
        except Exception:
            pass

        if not self._defer_startup:
            self.check_guide_needed()

        # 恢复窗口状态
        try:
            # 1. 先尝试恢复普通尺寸（如果存在）
            normal_rect = self.settings_manager.get("window/normal_rect")
            geometry = None
            
            restored_rect = False
            if normal_rect and isinstance(normal_rect, (list, tuple)) and len(normal_rect) == 4:
                try:
                    x, y, w, h = [int(v) for v in normal_rect]
                    w = max(1200, w)
                    h = max(740, h)
                    self.setGeometry(x, y, w, h)
                    restored_rect = True
                except Exception:
                    restored_rect = False

            if not restored_rect:
                geometry = self.settings_manager.get("window/geometry")
                if geometry:
                    self.restoreGeometry(geometry)
            
            # 2. 再根据保存的状态决定是否最大化
            is_maximized = self.settings_manager.get("window/maximized", False)
            is_fullscreen = self.settings_manager.get("window/fullscreen", False)

            try:
                has_geometry = geometry is not None and hasattr(geometry, "isEmpty") and (not geometry.isEmpty())
            except Exception:
                has_geometry = bool(geometry)
            
            if is_fullscreen:
                self._pending_window_mode = "fullscreen"
            elif is_maximized:
                self._pending_window_mode = "maximized"
            else:
                self._pending_window_mode = "normal"
            self._window_state_restored = False

        except Exception as e:
            try:
                LogManager.instance().warning(f"恢复窗口状态失败: {e}")
            except Exception:
                pass
            self._pending_window_mode = "normal"
            self._window_state_restored = False

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        apply_dark_title_bar(self, cm.get("theme.sidebar"), cm.get("theme.text.light"))
        page_side_bg = cm.get("theme.background.light")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        try:
            icon_color = cm.get("theme.primary", "#2196F3")
            app_icon = get_app_icon(icon_color)
            QApplication.instance().setWindowIcon(app_icon)
            self.setWindowIcon(app_icon)
        except Exception:
            pass
        status_bg = cm.get("theme.background.primary")
        status_border = cm.get("popup.border.primary")
        status_text = cm.get("theme.text.dark")
        if hasattr(self, "status_bar"):
            self.status_bar.setStyleSheet(f"""
                QStatusBar {{
                    background-color: {status_bg};
                    border-top: 1px solid {status_border};
                    color: {status_text};
                    font-size: 11px;
                }}
                QLabel {{
                    padding: 0 5px;
                }}
            """)
        if hasattr(self, "content_container"):
            self.content_container.setStyleSheet(f"background-color: {page_side_bg};")
        if hasattr(self, "main_widget"):
            self.main_widget.setStyleSheet(f"background-color: {page_side_bg};")
        if hasattr(self, "pages"):
            self.pages.setStyleSheet(f"background-color: {page_side_bg};")
        app = QApplication.instance()
        if app:
            app.setStyleSheet(f"""
                QToolTip {{
                    background-color: {tooltip_bg};
                    color: {tooltip_text};
                    border: 1px solid {tooltip_border};
                    font-size: 11px;
                }}
            """)
        sidebar_bg = cm.get("theme.sidebar")
        if hasattr(self, "icon_toolbar"):
            self.icon_toolbar.setStyleSheet(f"""
                QWidget {{
                    background-color: {sidebar_bg};
                }}
            """)
        sidebar_btn_style = f"""
            QPushButton {{
                background-color: {sidebar_bg};
                border: none;
                border-radius: 5px;
                color: {icon_color};
            }}
            QPushButton:checked {{
                background-color: {cm.get("theme.primary")};
            }}
            QPushButton:hover {{
                background-color: {cm.get("theme.primary")};
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
                font-size: 11px;
            }}
        """
        for btn in getattr(self, "_sidebar_buttons", []):
            btn.setStyleSheet(sidebar_btn_style)
        self._update_sidebar_icons()

    def _update_sidebar_icons(self):
        cm = ColorManager.instance()
        icon_color_off = cm.get("theme.primary", "#2196F3")
        icon_color_on = cm.get("theme.text.light")
        for item in getattr(self, "_sidebar_icon_map", []):
            try:
                btn, icon_off, icon_on = item
            except Exception:
                continue
            try:
                is_on = bool(btn.isChecked())
            except Exception:
                is_on = False
            icon_name = icon_on if is_on else icon_off
            icon_color = icon_color_on if is_on else icon_color_off
            try:
                btn.setIcon(qta.icon(icon_name, color=icon_color))
            except Exception:
                try:
                    btn.setIcon(qta.icon("mdi6.chart-box", color=icon_color))
                except Exception:
                    pass

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            t = event.type()
            if t in (QEvent.Type.WindowActivate, QEvent.Type.ActivationChange):
                cm = ColorManager.instance()
                apply_dark_title_bar(self, cm.get("theme.sidebar"), cm.get("theme.text.light"))
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_window_state_restored", False):
            return
        self._window_state_restored = True

        mode = getattr(self, "_pending_window_mode", "normal")
        try:
            state = self.windowState()
            state_value = getattr(state, "value", state)
        except Exception:
            state_value = self.windowState()
        if mode == "fullscreen":
            QTimer.singleShot(0, self.showFullScreen)
        elif mode == "maximized":
            QTimer.singleShot(0, self.showMaximized)
        else:
            QTimer.singleShot(0, self.showNormal)

    def _warmup_webengine_once(self):
        if getattr(self, "_webengine_warmed", False):
            return
        self._webengine_warmed = True
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except Exception:
            return

        try:
            view = QWebEngineView()
            view.resize(1, 1)
            view.hide()
            view.setHtml("<html><body></body></html>")
            self._webengine_warmup_view = view
            QTimer.singleShot(1200, self._cleanup_webengine_warmup)
        except Exception:
            try:
                if hasattr(self, "_webengine_warmup_view"):
                    del self._webengine_warmup_view
            except Exception:
                pass

    def _cleanup_webengine_warmup(self):
        try:
            view = getattr(self, "_webengine_warmup_view", None)
            self._webengine_warmup_view = None
            if view:
                view.deleteLater()
        except Exception:
            pass

    def check_guide_needed(self):
        """检查是否需要显示引导页"""
        # Check for data migration flag (set by MigrationManager)
        try:
            # Note: QSettings might return string "true" or boolean True
            val = self.settings_manager.get("ShowDataMigrationWizard", False)
            show_data_wiz = str(val).lower() == "true" if isinstance(val, str) else bool(val)
        except Exception:
            show_data_wiz = False
            
        if show_data_wiz:
            # We must show the guide in data migration mode
            try:
                self.settings_manager.remove("ShowDataMigrationWizard")
                self.settings_manager.sync()
            except Exception:
                pass
            
            try:
                self.guide_page.set_mode("data_migration")
                self.show_guide()
                return
            except Exception as e:
                LogManager.instance().error(f"Failed to show data migration wizard: {e}")

        from utils.sql.data_base import get_default_db_path
        db_path = get_default_db_path()
        if not os.path.exists(db_path):
            self.settings_manager.set("general/first_run", True)
            self.settings_manager.sync()
        else:
            # DB exists, ensure first_run is False to skip wizard
            if self.settings_manager.get("general/first_run", True):
                self.settings_manager.set("general/first_run", False)
                self.settings_manager.sync()

        is_first_run = self.settings_manager.get("general/first_run")
        
        # 如果是首次运行，则显示引导页
        if is_first_run:
            self.guide_page.set_mode("full") # Ensure full mode
            self.show_guide()
        else:
            self.show_main_interface()

    def show_guide(self):
        """显示引导页"""
        self._entered_main_interface = False
        # 隐藏主界面的所有其他部分，除了标题栏
        self.main_widget.hide()
        # 显示引导页
        self.guide_page.show()
        
        # 确保侧边栏也被隐藏 (如果它是 main_widget 之外的)
        if hasattr(self, 'icon_toolbar'):
             self.icon_toolbar.hide()

    def show_main_interface(self):
        """显示主界面"""
        t0 = time.perf_counter()
        self._entered_main_interface = True
        self.guide_page.hide()
        self.main_widget.show()
        
        if hasattr(self, 'icon_toolbar'):
             self.icon_toolbar.show()
        
        if not self._startup_preloaded:
            if hasattr(self, 'page_library'):
                 QTimer.singleShot(0, self.page_library.initialize)
            if hasattr(self, 'page_import'):
                 QTimer.singleShot(0, self.page_import._start_cache_loading)
        QTimer.singleShot(1200, self._warmup_subject_detector_once)
        
        # 尝试启动主界面功能引导（针对已有用户或测试模式）
        # 延迟一点时间，确保界面已完全显示
        # QTimer.singleShot(1500, self._try_start_main_guide)
        
        t1 = time.perf_counter()
        try:
            LogManager.instance().debug(f"[Startup] show_main_interface: {t1 - t0:.3f}s")
        except Exception:
            pass

    def _ensure_charts_page_loaded(self):
        self._charts_page_loaded = True
        self._charts_page_loading = False

    def _warmup_subject_detector_once(self):
        try:
            if getattr(self, "_subject_detector_warmup_started", False):
                return
            self._subject_detector_warmup_started = True
        except Exception:
            self._subject_detector_warmup_started = True
        try:
            from core.check_cli import warmup_subject_detector_async

            warmup_subject_detector_async()
        except Exception:
            pass

    def on_guide_completed(self):
        """引导完成"""
        self.show_main_interface()
        NotificationManager.instance().show_toast("设置已完成，开始探索吧！")
        try:
            if hasattr(self, "page_library"):
                QTimer.singleShot(600, self.page_library.initialize)
        except Exception:
            pass
        try:
            gp = getattr(self, "guide_page", None)
            sw = getattr(gp, "scan_worker", None) if gp is not None else None
            if sw is not None and sw.isRunning():
                if not getattr(self, "_guide_scan_refresh_connected", False):
                    self._guide_scan_refresh_connected = True
                    sw.scan_finished.connect(
                        lambda: QTimer.singleShot(0, self.page_library.initialize) if hasattr(self, "page_library") else None
                    )
        except Exception:
            pass

    def _try_start_main_guide(self):
        """尝试启动主界面功能引导"""
        return # 暂时禁用引导功能，解决闪退问题
        
        should_show = False
        try:
            # 如果是首次运行且刚完成引导页，或者开启了测试模式
            test_mode = self.settings_manager.get("debug/test_guide_overlay", False)
            shown = self.settings_manager.get("guide/main_tutorial_shown", False)
            if (not shown) or test_mode:
                should_show = True
        except Exception:
            pass
            
        if not should_show:
            return
            
        # 检查关键控件是否准备好 (避免调用过早)
        lib_page = getattr(self, "page_library", None)
        
        # 如果图库页面未初始化，或工具栏尚未显示/布局，延迟重试
        if not lib_page or not hasattr(self, 'icon_toolbar') or not self.icon_toolbar.isVisible() or self.icon_toolbar.width() <= 0:
            # 使用 getattr 安全检查重试计数器，防止死循环
            retry_count = getattr(self, "_guide_retry_count", 0)
            if retry_count < 10: # 最多重试 5 秒
                self._guide_retry_count = retry_count + 1
                QTimer.singleShot(500, self._try_start_main_guide)
            return
            
        # 切换到图库页面以确保控件可见
        self.pages.setCurrentIndex(0)
        self.btn_library.setChecked(True)
        
        # 动态获取页面内的控件
        folder_panel = getattr(lib_page, "folder_panel", None)
        grid_view = getattr(lib_page, "grid_view", None)
        tool_bar = getattr(lib_page, "tool_bar", None)
        preview_panel = getattr(lib_page, "preview_panel", None)
        info_panel = getattr(lib_page, "info_panel", None)
        
        steps = [
            {
                "widget": self.icon_toolbar,
                "text": "1. 侧边栏\n这里是程序的页面切换中心，您可以点击图标在不同功能页面间切换。",
                "position": "right"
            },
            {
                "widget": self.btn_library,
                "text": "2. 图库按钮\n点击这里进入图库页面，这是您的图片管理中心。",
                "position": "right"
            },
            {
                "widget": self.btn_import,
                "text": "3. 导入按钮\n这里是图片导入页面，您可以在此处理未导入的图片、进行对焦检测或导入到图库。",
                "position": "right"
            },
            {
                "widget": self.btn_settings,
                "text": "4. 设置按钮\n进入设置页面，您可以配置基础参数、API Key、性能选项和快捷键等。",
                "position": "right"
            },
            {
                "widget": self.btn_info,
                "text": "5. 关于软件\n查看软件版本信息、ID 以及作者的联系方式。",
                "position": "right"
            },
            # 以下步骤涉及 page_library 内部组件
            {
                "widget": folder_panel,
                "text": "6. 文件树\n这里显示所有物种的文件树，按生物学分类（目/科/属/种）排布。",
                "position": "right"
            },
            {
                "widget": grid_view,
                "text": "7. 缩略图面板\n这里是图片展示区域，显示当前选中分类下的图片缩略图。",
                "position": "top"
            },
            {
                "widget": tool_bar,
                "text": "8. 工具栏\n位于缩略图上方，提供重命名、视图切换、筛选、地理位置设置等操作。",
                "position": "bottom"
            },
            {
                "widget": preview_panel,
                "text": "9. 预览面板\n点击缩略图后，这里会显示大图。您可以在此进行收藏、评星和标记色标。",
                "position": "left"
            },
            {
                "widget": info_panel,
                "text": "10. 信息面板\n查看选中图片的基本信息、物种分类详情和地理位置数据。",
                "position": "top"
            }
        ]
        
        # 过滤掉 widget 为 None 的步骤
        valid_steps = [s for s in steps if s.get("widget") is not None]
        
        if valid_steps:
            GuideManager.instance().start_guide(self, valid_steps, on_finish=self._on_main_guide_finished)

    def _on_main_guide_finished(self):
        """引导结束回调"""
        try:
            self.settings_manager.set("guide/main_tutorial_shown", True)
            self.settings_manager.sync()
        except Exception:
            pass

    def on_task_status_changed(self, message, is_idle):
        """任务状态变更"""
        self.lbl_task_status.setText(message)
        # 可以根据 is_idle 改变样式，比如空闲时灰色，忙碌时黑色
        cm = ColorManager.instance()
        status_text = cm.get("theme.text.dark")
        if is_idle:
            self.lbl_task_status.setStyleSheet(f"color: {status_text};")
        else:
            busy_color = cm.get("theme.primary", "#2196F3")
            self.lbl_task_status.setStyleSheet(f"color: {busy_color}; font-weight: bold;")

    def on_library_stats_changed(self, total, loaded, selected):
        """图库统计信息变更"""
        self._library_stats = (total, loaded, selected)
        if self.pages.currentIndex() == 0:
            cache_info = None
            try:
                cache_info = self.page_library.cache_manager.get_cache_info()
            except Exception:
                cache_info = None
            self.lbl_image_counts.setText(self._format_stats_text(total, loaded, selected, cache_info))

    def on_import_stats_changed(self, total, loaded, selected):
        self._import_stats = (total, loaded, selected)
        if self.pages.currentIndex() == 1:
            if not getattr(self.page_import, "has_valid_folder", False):
                self.lbl_image_counts.setText("")
                return
            cache_info = None
            try:
                cache_info = self.page_import.cache_manager.get_cache_info()
            except Exception:
                cache_info = None
            self.lbl_image_counts.setText(self._format_stats_text(total, loaded, selected, cache_info))

    def on_page_changed(self, index):
        try:
            self._update_sidebar_icons()
        except Exception:
            pass
        try:
            old_index = getattr(self, "_last_main_page_index", None)
            self._handle_page_cache_release(old_index, int(index))
        except Exception:
            pass
        try:
            self._last_main_page_index = int(index)
        except Exception:
            self._last_main_page_index = index
        try:
            self._ensure_charts_page_loaded()
        except Exception:
            pass
        if index == 0:
            total, loaded, selected = getattr(self, "_library_stats", (0, 0, 0))
            cache_info = None
            try:
                cache_info = self.page_library.cache_manager.get_cache_info()
            except Exception:
                cache_info = None
            self.lbl_image_counts.setText(self._format_stats_text(total, loaded, selected, cache_info))
            return
        if index == 1:
            total, loaded, selected = getattr(self, "_import_stats", (0, 0, 0))
            if not getattr(self.page_import, "has_valid_folder", False):
                self.lbl_image_counts.setText("")
                return
            cache_info = None
            try:
                cache_info = self.page_import.cache_manager.get_cache_info()
            except Exception:
                cache_info = None
            self.lbl_image_counts.setText(self._format_stats_text(total, loaded, selected, cache_info))
            return
        self.lbl_image_counts.setText("")

    def _get_page_cache_release_seconds(self) -> int | None:
        try:
            v = int(self.settings_manager.get("performance/page_cache_release_seconds", 120) or 120)
        except Exception:
            v = 120
        if v <= 0:
            return None
        v = int(max(30, min(600, v)))
        try:
            allowed = [30] + [60 * i for i in range(1, 11)]
            if v not in allowed:
                v = int(min(allowed, key=lambda x: abs(int(x) - int(v))))
        except Exception:
            pass
        return int(v)

    def _handle_page_cache_release(self, old_index: int | None, new_index: int):
        sec = self._get_page_cache_release_seconds()
        if new_index in (0, 1):
            self._cancel_page_cache_release(new_index)
        if old_index in (0, 1) and int(old_index) != int(new_index):
            if sec is None:
                self._cancel_page_cache_release(int(old_index))
                return
            self._schedule_page_cache_release(int(old_index), int(sec))

    def _schedule_page_cache_release(self, page_index: int, seconds: int):
        t = self._page_cache_release_timers.get(int(page_index))
        if t is None:
            return
        try:
            t.stop()
        except Exception:
            pass
        try:
            self._page_cache_release_deadlines[int(page_index)] = time.monotonic() + float(seconds)
        except Exception:
            self._page_cache_release_deadlines[int(page_index)] = None
        t.start(int(max(1, seconds) * 1000))

    def _cancel_page_cache_release(self, page_index: int):
        t = self._page_cache_release_timers.get(int(page_index))
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
        try:
            if int(page_index) in self._page_cache_release_deadlines:
                del self._page_cache_release_deadlines[int(page_index)]
        except Exception:
            pass

    def _on_page_cache_release_timeout(self, page_index: int):
        try:
            if int(self.pages.currentIndex()) == int(page_index):
                return
        except Exception:
            return
        try:
            dl = self._page_cache_release_deadlines.get(int(page_index))
            if dl is not None and time.monotonic() < float(dl):
                remain = float(dl) - time.monotonic()
                self._schedule_page_cache_release(int(page_index), int(max(1, round(remain))))
                return
        except Exception:
            pass
        t0 = time.perf_counter()
        try:
            if int(page_index) == 0:
                page_name = "图库"
            elif int(page_index) == 1:
                page_name = "导入"
            else:
                page_name = str(page_index)
            LogManager.instance().info(f"超时触发：正在释放{page_name}页面缓存")
        except Exception:
            pass
        try:
            self._release_page_memory_cache(int(page_index))
            try:
                dt = time.perf_counter() - float(t0)
                LogManager.instance().info(f"释放{page_name}页面缓存完成，用时 {dt:.3f}s")
            except Exception:
                pass
        finally:
            self._cancel_page_cache_release(int(page_index))

    def _release_page_memory_cache(self, page_index: int):
        if int(page_index) == 0:
            try:
                self.page_library.release_memory_caches()
            except Exception:
                pass
            return
        if int(page_index) == 1:
            try:
                self.page_import.release_memory_caches()
            except Exception:
                pass
            return

    def _format_stats_text(self, total, loaded, selected, cache_info=None):
        text = f"总数: {total} | 已加载: {loaded} | 已选择: {selected}"
        if cache_info and "general_cached" in cache_info and "max_size" in cache_info:
            text = f"{text} | 缓存: {cache_info['general_cached']} / {cache_info['max_size']}"
        return text

    def update_sys_status(self):
        """更新系统资源占用"""
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            mem_mb = mem_info.rss / 1024 / 1024
            self._request_gpu_util_update()
            self.lbl_sys_status.setText(f"CPU: {cpu_percent:.1f}% | GPU: {self._gpu_util_text} | Mem: {mem_mb:.1f} MB")
        except Exception as e:
            try:
                LogManager.instance().warning(f"更新系统状态失败: {e}")
            except Exception:
                pass

    def _request_gpu_util_update(self):
        now = time.monotonic()
        if self._gpu_query_running:
            return
        if now - self._gpu_last_request_ts < 0.6:
            return
        self._gpu_last_request_ts = now
        self._gpu_query_running = True
        worker = GpuUtilWorker()
        worker.signals.result.connect(self._on_gpu_util_ready)
        self._gpu_thread_pool.start(worker)

    def _on_gpu_util_ready(self, text):
        self._gpu_util_text = text or "--"
        self._gpu_query_running = False

    def reset_click_count(self):
        self.settings_click_count = 0
        self.settings_click_timer.stop()

    def open_user_manual(self):
        try:
            if bool(getattr(sys, "frozen", False)):
                root = os.path.dirname(sys.executable)
            else:
                from utils.paths import PathManager
                root = str(PathManager.instance().get_project_root())
        except Exception:
            from utils.paths import PathManager
            root = str(PathManager.instance().get_project_root())
        doc_path = os.path.join(str(root), "使用说明书.docx")
        try:
            if not os.path.isfile(doc_path):
                NotificationManager.instance().show_warning("提示", f"说明书不存在：{doc_path}")
                return
        except Exception:
            pass
        try:
            os.startfile(doc_path)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"打开说明书失败: {e}")

    def eventFilter(self, obj, event):
        if obj == self.btn_settings and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.RightButton:
                try:
                    is_dev = not bool(getattr(sys, "frozen", False))
                except Exception:
                    is_dev = True
                try:
                    from utils.paths import PathManager
                    root = str(PathManager.instance().get_project_root())
                    debug_ok = os.path.exists(os.path.join(root, "debug_cgq_bmp.vip"))
                except Exception:
                    debug_ok = False
                if is_dev or debug_ok:
                    self.on_settings_right_clicked()
                    return True # 拦截右键，不显示默认菜单（如果有）
        return super().eventFilter(obj, event)

    def on_settings_right_clicked(self):
        if self.settings_click_count == 0:
            self.settings_click_timer.start()
        
        self.settings_click_count += 1
        
        if self.settings_click_count >= 6:
            self.reset_click_count()
            from ui.debug_console import DebugConsole
            console = DebugConsole(self)
            console.exec()

    def closeEvent(self, event):
        try:
            app = QApplication.instance()
        except Exception:
            app = None
        try:
            skip_confirm = bool(app.property("skip_exit_confirm")) if app is not None else False
        except Exception:
            skip_confirm = False
        try:
            if not skip_confirm and not bool(getattr(self, "_restore_defaults_requested", False)):
                if not NotificationManager.instance().ask_confirmation("确认退出", "确定要退出栖图吗？"):
                    event.ignore()
                    return
        except Exception:
            pass

        # 停止所有后台任务，确保线程及时退出
        if hasattr(self, 'page_library'):
             self.page_library.shutdown()
        if hasattr(self, 'page_import'):
             self.page_import.shutdown()

        # 保存窗口状态
        try:
            is_maximized = self.isMaximized()
            is_fullscreen = self.isFullScreen()

            try:
                state = self.windowState()
                state_value = getattr(state, "value", state)
            except Exception:
                state_value = self.windowState()
            
            # 保存是否最大化
            self.settings_manager.set("window/maximized", is_maximized)
            self.settings_manager.set("window/fullscreen", is_fullscreen)
            
            # 如果当前不是最大化状态，则保存当前的 geometry 和 normal_rect
            if not is_maximized and not is_fullscreen:
                # 1. 保存 geometry (QByteArray)
                self.settings_manager.set("window/geometry", self.saveGeometry())
                
                # 2. 保存 normal_rect (List)
                rect = self.geometry()
                self.settings_manager.set("window/normal_rect", [rect.x(), rect.y(), rect.width(), rect.height()])
                
        except Exception as e:
            try:
                LogManager.instance().warning(f"保存窗口状态失败: {e}")
            except Exception:
                pass

        pass

        # 检查是否有正在进行的 Exif 写入任务
        from utils.exif.exif_utils import ExifHandleWorker
        
        worker_instance = ExifHandleWorker.get_instance()
        skip_confirm = False
        try:
            app = QApplication.instance()
            skip_confirm = bool(app and app.property("skip_exit_confirm"))
        except Exception:
            skip_confirm = False
        if (not skip_confirm) and worker_instance.has_pending_tasks():
            try:
                counts = worker_instance.get_pending_task_counts() or {}
            except Exception:
                counts = {}
            try:
                pending = int(counts.get("pending", 0) or 0)
            except Exception:
                pending = 0
            try:
                unique_files = int(counts.get("inflight_unique_files", 0) or 0)
            except Exception:
                unique_files = 0
            completed, total = worker_instance.get_task_progress()
            
            confirmed = NotificationManager.instance().ask_confirmation(
                "后台任务正在运行",
                f"当前还有 Exif 信息正在写入中（待处理 {pending}，涉及文件 {unique_files}）。\n"
                f"累计进度：{completed}/{total}\n\n"
                "强制退出可能会导致数据写入不完整。\n"
                "建议等待任务完成后再退出"
            )
            
            if not confirmed:
                event.ignore()
                return
        try:
            worker_instance.stop(force=True)
        except Exception:
            pass
        
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 更新 Toast 位置
        if NotificationManager.instance().toast and NotificationManager.instance().toast.isVisible():
            NotificationManager.instance().toast.update_position()
