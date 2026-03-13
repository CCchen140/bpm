from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QStackedWidget, QLabel, 
                             QPushButton, QButtonGroup, QApplication, QStatusBar)
from PyQt6.QtCore import Qt, QSize, QTimer, QEvent, QPoint, QThreadPool, QRunnable, QObject, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QPalette

from ui.guide_page import GuidePage
from ui.utils.notification_manager import NotificationManager
from ui.utils.status_manager import StatusManager
from ui.utils.color_manager import ColorManager
from ui.utils.app_icon import get_app_icon
from ui.widgets.status_detail_popup import StatusDetailPopup

from ui.utils.icon_loader import qta
import os
import sys
import psutil
import time
import threading

from utils.setting.settings_manager import SettingsManager
from utils.paths import PathManager
from ui.utils.window_effect import apply_dark_title_bar
from utils.log_manager import LogManager
from utils.system.gpu_monitor import get_gpu_detail_metrics, get_gpu_util_text
from utils.guide_manager import GuideManager


class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
        except Exception:
            pass
        super().mousePressEvent(event)


class GpuUtilWorkerSignals(QObject):
    result = pyqtSignal(object)


class GpuUtilWorker(QRunnable):
    def __init__(self, fetch_detail: bool = False, fast_mode: bool = False, last_text: str = "--"):
        super().__init__()
        self._fetch_detail = bool(fetch_detail)
        self._fast_mode = bool(fast_mode)
        self._last_text = str(last_text or "--")
        self.signals = GpuUtilWorkerSignals()

    def run(self):
        try:
            # 首次采样保守一点，后续刷新压到接近 CPU 的 1s 节奏
            total_timeout = 1.0 if self._fast_mode else 5.0
            detail_timeout = 1.0 if self._fast_mode else 2.0
            sampled_text = get_gpu_util_text(timeout_s=total_timeout)
            sample_ok = bool(sampled_text and sampled_text != "--")
            gpu_text = sampled_text
            if self._fast_mode and (not gpu_text or gpu_text == "--") and self._last_text and self._last_text != "--":
                gpu_text = self._last_text
            detail = None
            if self._fetch_detail:
                detail = get_gpu_detail_metrics(timeout_s=detail_timeout) or {}
                total = detail.get("total") if isinstance(detail, dict) else None
                if total is not None:
                    gpu_text = f"{float(total):.2f}%" if float(total) < 1.0 else f"{float(total):.1f}%"
                    sample_ok = True
        except Exception:
            detail = None
            sample_ok = False
            gpu_text = self._last_text if self._fast_mode and self._last_text and self._last_text != "--" else "--"
        try:
            self.signals.result.emit({"text": gpu_text, "detail": detail, "sample_ok": sample_ok})
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

    def _create_loading_placeholder(self, title: str):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(10)
        lay.addStretch()
        lbl = QLabel("正在加载")
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet("font-size: 22px; font-weight: 600;")
        lay.addWidget(lbl)
        sub = QLabel(f"{str(title or '')} 页面正在后台加载，请稍候…")
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
        self.charts_debug_click_count = 0
        self.charts_debug_click_timer = QTimer()
        self.charts_debug_click_timer.setInterval(3000)
        self.charts_debug_click_timer.timeout.connect(self._reset_charts_debug_click_count)

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
            QStatusBar QLabel {{
                padding: 0 5px;
                color: {status_text};
            }}
        """)
        # 设置状态栏到主窗口（QMainWindow 的状态栏不需要添加到布局中）
        self.setStatusBar(self.status_bar)

        # 状态栏组件
        # 1. 任务状态 (最左)
        self.lbl_task_status = QLabel("就绪")
        self.status_bar.addWidget(self.lbl_task_status)
        
        # 2. 图片计数 (左侧第二个)
        self.lbl_image_counts = QLabel("")
        self.status_bar.addWidget(self.lbl_image_counts)
        
        # 3. 系统资源状态（最右）
        self.sys_status_widget = QWidget(self.status_bar)
        self.sys_status_layout = QHBoxLayout(self.sys_status_widget)
        self.sys_status_layout.setContentsMargins(0, 0, 0, 0)
        self.sys_status_layout.setSpacing(6)
        self.lbl_cpu_status = ClickableLabel("CPU: 0%")
        self.lbl_cpu_status.setToolTip("点击查看 CPU 明细")
        self.lbl_gpu_status = ClickableLabel("GPU: --")
        self.lbl_gpu_status.setToolTip("点击查看 GPU 明细")
        self.lbl_mem_status = QLabel("Mem: 0 MB")
        for sep_idx in range(2):
            sep = QLabel("|")
            sep.setStyleSheet("padding: 0 2px;")
            self.sys_status_layout.addWidget(
                self.lbl_cpu_status if sep_idx == 0 else self.lbl_gpu_status
            )
            self.sys_status_layout.addWidget(sep)
        self.sys_status_layout.addWidget(self.lbl_mem_status)
        self.status_bar.addPermanentWidget(self.sys_status_widget)
        self.lbl_cpu_status.clicked.connect(lambda: self._toggle_status_detail_popup("cpu"))
        self.lbl_gpu_status.clicked.connect(lambda: self._toggle_status_detail_popup("gpu"))
        
        # 连接任务管理器信号
        StatusManager.instance().status_changed.connect(self.on_task_status_changed)
        self._base_task_status_message = "就绪"
        self._base_task_status_idle = True

        self.exif_task_timer = QTimer(self)
        self.exif_task_timer.timeout.connect(self._refresh_exif_task_status)
        self.exif_task_timer.start(300)
        
        # 系统资源监控定时器
        self.sys_timer = QTimer(self)
        self.sys_timer.timeout.connect(self.update_sys_status)
        self._proc = psutil.Process(os.getpid())
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        try:
            self._proc.cpu_percent(interval=None)
        except Exception:
            pass
        self.sys_timer.start(1000) # 0.5秒更新一次
        self._gpu_util_text = "--"
        self._cpu_detail_cache = {}
        self._gpu_detail_cache = {}
        self._gpu_query_running = False
        self._gpu_last_request_ts = 0.0
        self._gpu_last_success_ts = 0.0
        self._gpu_suppress_until = 0.0
        self._gpu_thread_pool = QThreadPool.globalInstance()
        self._status_popups = {
            "cpu": StatusDetailPopup("CPU 明细", self),
            "gpu": StatusDetailPopup("GPU 明细", self),
        }
        
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
        tooltip_bg = cm.get("tooltip.background")
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
        self.btn_filter.installEventFilter(self)
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
        
        # 图库 Web 版按钮（放在奖章按钮后面）- 暂时隐藏
        self.btn_library_web = QPushButton()
        # 尝试多个图标，使用第一个可用的
        icon_names = ['mdi6.web', 'mdi.web', 'fa5s.globe', 'mdi6.earth', 'fa5s.desktop']
        icon_set = False
        for icon_name in icon_names:
            try:
                self.btn_library_web.setIcon(qta.icon(icon_name, color=button_color))
                icon_set = True
                break
            except Exception:
                continue
        if not icon_set:
            # 如果所有图标都失败，使用文字
            self.btn_library_web.setText("W")
        self.btn_library_web.setIconSize(QSize(28, 28))
        self.btn_library_web.setFixedSize(50, 50)
        self.btn_library_web.setToolTip("图库 Web 版")
        self.btn_library_web.setCheckable(True)
        self.btn_library_web.setStyleSheet(sidebar_btn_style)
        self.sidebar_btn_group.addButton(self.btn_library_web, 6)
        icon_layout.addWidget(self.btn_library_web)
        self._sidebar_buttons.append(self.btn_library_web)
        self._sidebar_icon_map.append((self.btn_library_web, "mdi6.web", "mdi6.web"))
        # 暂时隐藏 Web 版按钮
        self.btn_library_web.hide()
        
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

        self._page_loaded_flags = {
            0: False,  # 图库
            1: False,  # 导入
            4: False,  # 设置
            5: False,  # 关于
            6: False,  # Web
        }
        self._page_loading_flags = {
            0: False,
            1: False,
            4: False,
            5: False,
            6: False,
        }
        self._page_placeholders = {}
        self._cross_page_signals_connected = False

        self.page_library = None
        self.page_import = None
        self.page_settings = None
        self.page_info = None
        self.page_library_web = None

        ph_lib = self._create_loading_placeholder("图片库")
        self._page_placeholders[0] = ph_lib
        self.pages.addWidget(ph_lib)

        ph_import = self._create_loading_placeholder("导入")
        self._page_placeholders[1] = ph_import
        self.pages.addWidget(ph_import)

        self._charts_page_loaded = False
        self._charts_page_loading = False
        self.pages.addWidget(self._create_dev_placeholder("数据图表"))
        self.pages.addWidget(self._create_dev_placeholder("奖章页面"))

        ph_settings = self._create_loading_placeholder("设置")
        self._page_placeholders[4] = ph_settings
        self.pages.addWidget(ph_settings)

        ph_info = self._create_loading_placeholder("关于")
        self._page_placeholders[5] = ph_info
        self.pages.addWidget(ph_info)

        ph_web = self._create_loading_placeholder("图库 Web 版")
        self._page_placeholders[6] = ph_web
        self.pages.addWidget(ph_web)
        
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
                QStatusBar QLabel {{
                    padding: 0 5px;
                    color: {status_text};
                }}
            """)
        for popup in getattr(self, "_status_popups", {}).values():
            try:
                if popup is not None:
                    popup.refresh_theme()
            except Exception:
                pass
        if hasattr(self, "content_container"):
            self.content_container.setStyleSheet(f"background-color: {page_side_bg};")
        if hasattr(self, "main_widget"):
            self.main_widget.setStyleSheet(f"background-color: {page_side_bg};")
        if hasattr(self, "pages"):
            self.pages.setStyleSheet(f"background-color: {page_side_bg};")
        app = QApplication.instance()
        if app:
            try:
                pal = app.palette()
                pal.setColor(QPalette.ColorRole.Highlight, QColor(cm.get("theme.primary")))
                pal.setColor(QPalette.ColorRole.HighlightedText, QColor(cm.get("theme.text.light")))
                app.setPalette(pal)
            except Exception:
                pass
            combo_hover_bg = cm.get("theme.background.dark")
            combo_selected_bg = cm.get("theme.primary")
            combo_selected_text = cm.get("theme.text.light")
            combo_text = cm.get("theme.text.dark")
            combo_border = cm.get("popup.border.primary")
            combo_bg = cm.get("theme.background.light")
            # 使用Base64编码的SVG箭头，避免中文路径问题
            from ui.common.icon_utils import get_arrow_down_svg_base64
            arrow_url = get_arrow_down_svg_base64(combo_text)
            app.setStyleSheet(f"""
                QToolTip {{
                    background-color: {tooltip_bg};
                    color: {tooltip_text};
                    border: 1px solid {tooltip_border};
                    font-size: 11px;
                }}
                QMenu::item:selected {{
                    background-color: {combo_selected_bg};
                    color: {combo_selected_text};
                }}
                QAbstractItemView {{
                    outline: none;
                    selection-background-color: {combo_selected_bg};
                    selection-color: {combo_selected_text};
                }}
                QAbstractItemView::item {{
                    padding: 6px 8px;
                    border-radius: 4px;
                }}
                QAbstractItemView::item:hover {{
                    background-color: {combo_hover_bg};
                }}
                QAbstractItemView::item:selected {{
                    background-color: {combo_selected_bg};
                    color: {combo_selected_text};
                }}
                QComboBox {{
                    border: 1px solid {combo_border};
                    background-color: {combo_bg};
                    color: {combo_text};
                    padding: 4px 8px;
                }}
                QComboBox::drop-down {{
                    border: none;
                    width: 22px;
                    background: transparent;
                }}
                QComboBox::down-arrow {{
                    image: url({arrow_url});
                    width: 12px;
                    height: 12px;
                    margin-right: 6px;
                }}
                QComboBox QAbstractItemView {{
                    border: 1px solid {combo_border};
                    background-color: {combo_bg};
                    color: {combo_text};
                    outline: none;
                    selection-background-color: {combo_selected_bg};
                    selection-color: {combo_selected_text};
                }}
                QComboBox QAbstractItemView::item {{
                    padding: 6px 8px;
                    border-radius: 4px;
                }}
                QComboBox QAbstractItemView::item:hover {{
                    background-color: {combo_hover_bg};
                }}
                QComboBox QAbstractItemView::item:selected {{
                    background-color: {combo_selected_bg};
                    color: {combo_selected_text};
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
            # 根据状态选择图标样式：选中时用fill，未选中时用line
            icon_style = 'fill' if is_on else 'line'
            try:
                btn.setIcon(qta.icon(icon_name, color=icon_color, style=icon_style))
            except Exception:
                try:
                    btn.setIcon(qta.icon("mdi6.chart-box", color=icon_color, style=icon_style))
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
        try:
            self._reposition_status_detail_popups()
        except Exception:
            pass
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
        
        try:
            QTimer.singleShot(150, lambda: self._ensure_page_loaded(0))
            QTimer.singleShot(250, lambda: self._ensure_page_loaded(1))
        except Exception:
            pass

        if not self._startup_preloaded:
            try:
                QTimer.singleShot(1200, self._maybe_start_page_startup_jobs)
            except Exception:
                pass
        QTimer.singleShot(1200, self._warmup_subject_detector_once)
        QTimer.singleShot(600, self._warmup_exiftool_stayopen_once)
        
        # 尝试启动主界面功能引导（针对已有用户或测试模式）
        # 延迟一点时间，确保界面已完全显示
        # QTimer.singleShot(1500, self._try_start_main_guide)
        
        t1 = time.perf_counter()
        try:
            LogManager.instance().debug(f"[Startup] show_main_interface: {t1 - t0:.3f}s")
        except Exception:
            pass

    def _maybe_start_page_startup_jobs(self):
        """
        主界面显示后，启动与页面相关但不影响首屏显示的初始化工作。
        """
        try:
            if bool(getattr(self, "_startup_preloaded", False)):
                return
        except Exception:
            pass
        try:
            if not bool(getattr(self, "_entered_main_interface", False)):
                return
        except Exception:
            return

        lib = getattr(self, "page_library", None)
        imp = getattr(self, "page_import", None)
        if lib is None and imp is None:
            try:
                QTimer.singleShot(500, self._maybe_start_page_startup_jobs)
            except Exception:
                pass
            return

        try:
            if lib is not None and hasattr(lib, "initialize"):
                QTimer.singleShot(0, lib.initialize)
        except Exception:
            pass
        try:
            if imp is not None and hasattr(imp, "_start_cache_loading"):
                QTimer.singleShot(0, imp._start_cache_loading)
        except Exception:
            pass

        self._startup_preloaded = True

    def _connect_cross_page_signals_if_ready(self):
        """
        页面之间的信号联动需要双方页面都已创建，这里集中做一次性连接。
        """
        try:
            if bool(getattr(self, "_cross_page_signals_connected", False)):
                return
        except Exception:
            pass
        lib = getattr(self, "page_library", None)
        imp = getattr(self, "page_import", None)
        st = getattr(self, "page_settings", None)
        if lib is None or imp is None or st is None:
            return
        try:
            imp.import_to_library_succeeded.connect(lib.on_import_to_library_succeeded)
        except Exception:
            pass
        try:
            st.library_thumbnail_setting_changed.connect(lib.reload_thumbnails_config)
        except Exception:
            pass
        try:
            st.import_thumbnail_setting_changed.connect(imp.reload_thumbnails_config)
        except Exception:
            pass
        try:
            st.thumbnail_ui_perf_setting_changed.connect(lib.update_thumbnail_ui_perf_config)
        except Exception:
            pass
        try:
            st.thumbnail_ui_perf_setting_changed.connect(imp.update_thumbnail_ui_perf_config)
        except Exception:
            pass
        try:
            imp.folder_panel.folderRemovedFromTree.connect(lib.clear_if_showing_folder)
            imp.folder_panel.folderDeletedOnDisk.connect(lib.clear_if_showing_folder)
        except Exception:
            pass
        self._cross_page_signals_connected = True

    def _ensure_page_loaded(self, index: int):
        """
        延后加载指定页面：
        - 避免在启动阶段立即 import / 构造所有页面，减少首屏等待
        - 页面构造必须在主线程进行，因此使用 QTimer 把工作推迟到事件循环开始后执行
        """
        idx = int(index)
        if idx not in (0, 1, 4, 5, 6):
            return
        if bool(self._page_loaded_flags.get(idx, False)):
            return
        if bool(self._page_loading_flags.get(idx, False)):
            return

        self._page_loading_flags[idx] = True

        title_map = {0: "图片库", 1: "导入", 4: "设置", 5: "关于", 6: "图库 Web 版"}
        title = title_map.get(idx, "页面")
        task_id = None
        try:
            task_id = StatusManager.instance().start_task(f"正在加载{title}页面...")
        except Exception:
            task_id = None

        def _do_load():
            try:
                if idx == 0:
                    from ui.image_library_page import ImageLibraryPage
                    page = ImageLibraryPage()
                    try:
                        page.stats_changed.connect(self.on_library_stats_changed)
                    except Exception:
                        pass
                    self.page_library = page
                elif idx == 1:
                    from ui.import_page import ImportPage
                    page = ImportPage()
                    try:
                        page.stats_changed.connect(self.on_import_stats_changed)
                    except Exception:
                        pass
                    self.page_import = page
                elif idx == 4:
                    from ui.settings_page import SettingsPage
                    page = SettingsPage()
                    self.page_settings = page
                elif idx == 5:
                    from ui.info_page import InfoPage
                    page = InfoPage()
                    self.page_info = page
                else:
                    from ui.web.image_library_web_page import ImageLibraryWebPage
                    page = ImageLibraryWebPage()
                    self.page_library_web = page

                old = self._page_placeholders.get(idx)
                was_current = False
                try:
                    if old is not None and self.pages.currentWidget() == old:
                        was_current = True
                except Exception:
                    was_current = False
                try:
                    if old is not None:
                        self.pages.removeWidget(old)
                    self.pages.insertWidget(idx, page)
                except Exception:
                    self.pages.addWidget(page)
                    try:
                        if was_current:
                            self.pages.setCurrentWidget(page)
                    except Exception:
                        pass
                try:
                    if was_current:
                        self.pages.setCurrentWidget(page)
                except Exception:
                    pass
                try:
                    if old is not None:
                        old.deleteLater()
                except Exception:
                    pass
                self._page_loaded_flags[idx] = True
                self._page_placeholders.pop(idx, None)

                try:
                    if idx == 4:
                        self._connect_cross_page_signals_if_ready()
                    if idx in (0, 1):
                        self._connect_cross_page_signals_if_ready()
                except Exception:
                    pass

                try:
                    if idx in (0, 1):
                        QTimer.singleShot(0, self._maybe_start_page_startup_jobs)
                except Exception:
                    pass
            except Exception as e:
                try:
                    err = str(e)
                    if err:
                        err = err.replace("\r", " ").replace("\n", " ").strip()
                    if err and len(err) > 140:
                        err = err[:140] + "..."
                    msg = f"{title}页面加载失败"
                    if err:
                        msg = f"{msg}：{err}"
                    NotificationManager.instance().show_toast(msg)
                except Exception:
                    pass
                try:
                    LogManager.instance().warning(f"{title}页面加载失败: {e}")
                except Exception:
                    pass
            finally:
                try:
                    if task_id is not None:
                        StatusManager.instance().finish_task(task_id)
                except Exception:
                    pass
                self._page_loading_flags[idx] = False

        QTimer.singleShot(0, _do_load)

    def _warmup_exiftool_stayopen_once(self):
        try:
            if bool(getattr(self, "_exiftool_warmup_started", False)):
                return
            self._exiftool_warmup_started = True
        except Exception:
            self._exiftool_warmup_started = True

        def _run():
            try:
                from utils.exif.exif_utils import ExifHandleWorker

                worker = ExifHandleWorker.get_instance()
                try:
                    worker._start_stayopen_process()
                except Exception:
                    pass
            except Exception:
                pass

        try:
            threading.Thread(target=_run, name="WarmupExifTool", daemon=True).start()
        except Exception:
            try:
                _run()
            except Exception:
                pass

    def _ensure_charts_page_loaded(self):
        try:
            if getattr(self, "_charts_page_loaded", False):
                return
            if getattr(self, "_charts_page_loading", False):
                return
        except Exception:
            pass

        self._charts_page_loading = True
        try:
            from table.data_charts_page import DataChartsPage

            page = DataChartsPage(self)
            try:
                old = self.pages.widget(2)
            except Exception:
                old = None
            try:
                self.pages.insertWidget(2, page)
                try:
                    self.pages.setCurrentWidget(page)
                except Exception:
                    try:
                        self.pages.setCurrentIndex(2)
                    except Exception:
                        pass
                if old is not None:
                    try:
                        self.pages.removeWidget(old)
                    except Exception:
                        pass
                    try:
                        old.deleteLater()
                    except Exception:
                        pass
                self.page_charts = page
                self._charts_page_loaded = True
            except Exception as e:
                try:
                    NotificationManager.instance().show_toast("数据图表页面加载失败")
                except Exception:
                    pass
                try:
                    LogManager.instance().warning(f"数据图表页面加载失败: {e}")
                except Exception:
                    pass
        except Exception as e:
            try:
                NotificationManager.instance().show_toast("数据图表页面加载失败")
            except Exception:
                pass
            try:
                LogManager.instance().warning(f"数据图表页面导入失败: {e}")
            except Exception:
                pass
        finally:
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
            lib = getattr(self, "page_library", None)
            if lib is not None and hasattr(lib, "initialize"):
                QTimer.singleShot(600, lib.initialize)
        except Exception:
            pass
        try:
            gp = getattr(self, "guide_page", None)
            sw = getattr(gp, "scan_worker", None) if gp is not None else None
            if sw is not None and sw.isRunning():
                if not getattr(self, "_guide_scan_refresh_connected", False):
                    self._guide_scan_refresh_connected = True
                    sw.scan_finished.connect(
                        lambda: QTimer.singleShot(0, p.initialize) if (p := getattr(self, "page_library", None)) is not None and hasattr(p, "initialize") else None
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
        try:
            self._base_task_status_message = str(message or "")
        except Exception:
            self._base_task_status_message = message
        try:
            self._base_task_status_idle = bool(is_idle)
        except Exception:
            self._base_task_status_idle = True
        # 可以根据 is_idle 改变样式，比如空闲时灰色，忙碌时黑色
        cm = ColorManager.instance()
        status_text = cm.get("theme.text.dark")
        if is_idle:
            self.lbl_task_status.setStyleSheet(f"color: {status_text};")
        else:
            busy_color = cm.get("theme.primary", "#2196F3")
            self.lbl_task_status.setStyleSheet(f"color: {busy_color}; font-weight: bold;")
        try:
            self._refresh_exif_task_status()
        except Exception:
            pass

    def _refresh_exif_task_status(self):
        """
        刷新左下角任务栏文本：
        - UI 侧的“数据库读写”等任务仍由 StatusManager 推送
        - Exif/XMP 的实际队列/批量写入属于持续任务，这里用轮询方式补齐显示进度与待处理数量
        """
        base_msg = str(getattr(self, "_base_task_status_message", "") or "")
        base_idle = bool(getattr(self, "_base_task_status_idle", True))

        exif_msg = ""
        is_exif_busy = False
        try:
            from utils.exif.exif_utils import ExifHandleWorker
            worker = ExifHandleWorker.get_instance()
            counts = worker.get_pending_task_counts() or {}
            pending_all = int(counts.get("pending_all") or 0)
            pending_write = int(counts.get("pending") or 0)
            read_queued = int(counts.get("read_queued") or 0)
            c, t = worker.get_task_progress()
            try:
                c = int(c or 0)
            except Exception:
                c = 0
            try:
                t = int(t or 0)
            except Exception:
                t = 0

            if pending_all > 0:
                is_exif_busy = True
                if t > 0:
                    exif_msg = f"元数据任务：{c}/{t}（写入待处理{pending_write}，读取待处理{read_queued}）"
                else:
                    exif_msg = f"元数据任务：写入待处理{pending_write}，读取待处理{read_queued}"
        except Exception:
            exif_msg = ""
            is_exif_busy = False

        if exif_msg:
            if (not base_idle) and base_msg and base_msg != "就绪":
                show = f"{base_msg} | {exif_msg}"
            else:
                show = exif_msg
        else:
            show = base_msg if base_msg else "就绪"

        self.lbl_task_status.setText(show)

        cm = ColorManager.instance()
        status_text = cm.get("theme.text.dark")
        if (not base_idle) or is_exif_busy:
            busy_color = cm.get("theme.primary", "#2196F3")
            self.lbl_task_status.setStyleSheet(f"color: {busy_color}; font-weight: bold;")
        else:
            self.lbl_task_status.setStyleSheet(f"color: {status_text};")

    def on_library_stats_changed(self, total, loaded, selected):
        """图库统计信息变更"""
        self._library_stats = (total, loaded, selected)
        if self.pages.currentIndex() == 0:
            cache_info = None
            try:
                lib = getattr(self, "page_library", None)
                cache_info = lib.cache_manager.get_cache_info() if lib is not None else None
            except Exception:
                cache_info = None
            self.lbl_image_counts.setText(self._format_stats_text(total, loaded, selected, cache_info))

    def on_import_stats_changed(self, total, loaded, selected):
        self._import_stats = (total, loaded, selected)
        if self.pages.currentIndex() == 1:
            imp = getattr(self, "page_import", None)
            if imp is None or not getattr(imp, "has_valid_folder", False):
                self.lbl_image_counts.setText("")
                return
            cache_info = None
            try:
                cache_info = imp.cache_manager.get_cache_info()
            except Exception:
                cache_info = None
            self.lbl_image_counts.setText(self._format_stats_text(total, loaded, selected, cache_info))

    def on_page_changed(self, index):
        try:
            if int(index) in (0, 1, 4, 5, 6):
                self._ensure_page_loaded(int(index))
        except Exception:
            pass
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
        if int(index) == 2:
            try:
                self._ensure_charts_page_loaded()
            except Exception:
                pass
            # 不再每次切换都重新加载HTML，避免页面闪烁
            # 如果需要刷新数据，页面内部会通过WebSocket或定时器自动刷新
        if index == 0:
            total, loaded, selected = getattr(self, "_library_stats", (0, 0, 0))
            cache_info = None
            try:
                lib = getattr(self, "page_library", None)
                cache_info = lib.cache_manager.get_cache_info() if lib is not None else None
            except Exception:
                cache_info = None
            self.lbl_image_counts.setText(self._format_stats_text(total, loaded, selected, cache_info))
            return
        if index == 1:
            total, loaded, selected = getattr(self, "_import_stats", (0, 0, 0))
            imp = getattr(self, "page_import", None)
            if imp is None or not getattr(imp, "has_valid_folder", False):
                self.lbl_image_counts.setText("")
                return
            cache_info = None
            try:
                cache_info = imp.cache_manager.get_cache_info()
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
                lib = getattr(self, "page_library", None)
                if lib is not None and hasattr(lib, "release_memory_caches"):
                    lib.release_memory_caches()
            except Exception:
                pass
            return
        if int(page_index) == 1:
            try:
                imp = getattr(self, "page_import", None)
                if imp is not None and hasattr(imp, "release_memory_caches"):
                    imp.release_memory_caches()
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
            # 请求 GPU 数据更新（异步）
            self._request_gpu_util_update()
            # 立即刷新状态栏显示（使用当前的 GPU 数据）
            self._refresh_sys_status_text()
        except Exception as e:
            try:
                LogManager.instance().warning(f"更新系统状态失败: {e}")
            except Exception:
                pass

    def _request_gpu_util_update(self, force_detail: bool = False):
        try:
            if not bool(self.isActiveWindow()):
                return
        except Exception:
            pass
        try:
            aw = QApplication.activeWindow()
        except Exception:
            aw = None
        if aw is not None and aw is not self:
            try:
                from PyQt6.QtWidgets import QDialog

                if isinstance(aw, QDialog):
                    return
            except Exception:
                return
        now = time.monotonic()
        try:
            if float(now) < float(getattr(self, "_gpu_suppress_until", 0.0) or 0.0):
                return
        except Exception:
            pass
        if self._gpu_query_running:
            return
        # 与 CPU 状态栏保持同样的 1s 更新节奏
        if now - self._gpu_last_request_ts < 1.0:
            return
        try:
            gpu_popup = getattr(self, "_status_popups", {}).get("gpu")
            need_detail = bool(force_detail) or bool(gpu_popup is not None and gpu_popup.isVisible())
        except Exception:
            need_detail = bool(force_detail)
        try:
            fast_mode = bool(self._gpu_util_text and self._gpu_util_text != "--")
            if fast_mode and (now - float(getattr(self, "_gpu_last_success_ts", 0.0) or 0.0) >= 3.0):
                fast_mode = False
        except Exception:
            fast_mode = False
        self._gpu_last_request_ts = now
        self._gpu_query_running = True
        worker = GpuUtilWorker(fetch_detail=need_detail, fast_mode=fast_mode, last_text=self._gpu_util_text)
        worker.signals.result.connect(self._on_gpu_util_ready)
        self._gpu_thread_pool.start(worker)

    def _on_gpu_util_ready(self, payload):
        text = "--"
        detail = {}
        sample_ok = False
        try:
            if isinstance(payload, dict):
                text = str(payload.get("text") or "--")
                detail_val = payload.get("detail")
                detail = detail_val if isinstance(detail_val, dict) else None
                sample_ok = bool(payload.get("sample_ok"))
            else:
                text = str(payload or "--")
                detail = None
        except Exception:
            text = "--"
            detail = None
            sample_ok = False
        self._gpu_util_text = text or "--"
        if sample_ok:
            try:
                self._gpu_last_success_ts = float(time.monotonic())
            except Exception:
                self._gpu_last_success_ts = 0.0
        if isinstance(detail, dict):
            self._gpu_detail_cache = detail or {}
        self._gpu_query_running = False
        # GPU 数据更新后，立即刷新状态栏显示
        try:
            self._refresh_sys_status_text()
        except Exception:
            pass
    
    def _format_mb_text(self, value_mb):
        try:
            value = float(value_mb)
        except Exception:
            return "--"
        if value >= 1024.0:
            return f"{value / 1024.0:.2f} GB"
        return f"{value:.0f} MB"

    def _format_percent_text(self, value):
        try:
            v = float(value)
        except Exception:
            return "--"
        if v < 1.0:
            return f"{v:.2f}%"
        return f"{v:.1f}%"

    def _collect_cpu_detail_metrics(self):
        try:
            logical = int(psutil.cpu_count(logical=True) or 1)
        except Exception:
            logical = 1
        if logical <= 0:
            logical = 1
        metrics = {}
        try:
            system_cpu = float(psutil.cpu_percent(interval=None))
            metrics["system_cpu"] = system_cpu
        except Exception:
            metrics["system_cpu"] = None
        try:
            process_cpu_raw = float(self._proc.cpu_percent(interval=None))
        except Exception:
            process_cpu_raw = None
        metrics["process_cpu_raw"] = process_cpu_raw
        try:
            metrics["process_cpu"] = None if process_cpu_raw is None else float(process_cpu_raw) / float(logical)
        except Exception:
            metrics["process_cpu"] = None
        try:
            mem_info = self._proc.memory_info()
            metrics["mem_mb"] = float(mem_info.rss) / 1024.0 / 1024.0
        except Exception:
            metrics["mem_mb"] = None
        try:
            metrics["mem_percent"] = float(self._proc.memory_percent())
        except Exception:
            metrics["mem_percent"] = None
        try:
            vm = psutil.virtual_memory()
            metrics["system_mem_percent"] = float(vm.percent)
            metrics["system_mem_used_mb"] = float(vm.used) / 1024.0 / 1024.0
            metrics["system_mem_total_mb"] = float(vm.total) / 1024.0 / 1024.0
        except Exception:
            metrics["system_mem_percent"] = None
            metrics["system_mem_used_mb"] = None
            metrics["system_mem_total_mb"] = None
        return metrics

    def _build_cpu_popup_rows(self):
        data = self._cpu_detail_cache or {}
        return [
            ("总 CPU", self._format_percent_text(data.get("system_cpu"))),
            ("进程 CPU", self._format_percent_text(data.get("process_cpu"))),
            ("进程 CPU(原始)", self._format_percent_text(data.get("process_cpu_raw"))),
            ("进程内存", self._format_mb_text(data.get("mem_mb"))),
            ("进程内存占比", self._format_percent_text(data.get("mem_percent"))),
            (
                "系统内存",
                f"{self._format_mb_text(data.get('system_mem_used_mb'))} / {self._format_mb_text(data.get('system_mem_total_mb'))}",
            ),
            ("系统内存占比", self._format_percent_text(data.get("system_mem_percent"))),
        ]

    def _build_gpu_popup_rows(self):
        data = self._gpu_detail_cache or {}
        rows = [("GPU 总和", self._gpu_util_text or "--")]
        
        # 获取厂商信息
        try:
            vendor = str(data.get("vendor") or "").strip().lower()
        except Exception:
            vendor = ""
        
        # 对于 AMD 显卡，显示简化的信息
        if vendor == "amd":
            rows.append(("", ""))  # 空行
            rows.append(("提示", "AMD 显卡仅支持总体利用率检测"))
            rows.append(("", ""))  # 空行
        else:
            # NVIDIA/Intel 显示详细引擎信息
            rows.append(("CUDA/Compute", self._format_percent_text(data.get("compute"))))
            rows.append(("Video Decode", self._format_percent_text(data.get("decode"))))
            rows.append(("Video Encode", self._format_percent_text(data.get("encode"))))
            rows.append(("Copy", self._format_percent_text(data.get("copy"))))
            rows.append(("3D", self._format_percent_text(data.get("3d"))))
        
        mem_used = data.get("memory_used_mb")
        mem_total = data.get("memory_total_mb")
        if mem_used is not None or mem_total is not None:
            rows.append(("显存", f"{self._format_mb_text(mem_used)} / {self._format_mb_text(mem_total)}"))
        mem_dedicated = data.get("memory_dedicated_mb")
        if mem_dedicated is not None:
            rows.append(("专用显存", self._format_mb_text(mem_dedicated)))
        mem_shared = data.get("memory_shared_mb")
        if mem_shared is not None:
            rows.append(("共享显存", self._format_mb_text(mem_shared)))
        rows.append(("显存带宽", self._format_percent_text(data.get("memory"))))
        try:
            detail_available = bool(data.get("detail_available"))
        except Exception:
            detail_available = False
        try:
            engine_source = str(data.get("engine_source") or "").strip()
        except Exception:
            engine_source = ""
        rows.append(("细分来源", engine_source or "未命中"))
        rows.append(("细分状态", "已获取" if detail_available else "当前仅拿到总量"))
        if vendor:
            rows.append(("厂商", vendor.upper()))
        try:
            name = str(data.get("name") or "").strip()
        except Exception:
            name = ""
        if name:
            rows.append(("设备", name))
        return rows

    def _refresh_status_detail_popups(self):
        try:
            cpu_popup = self._status_popups.get("cpu")
            if cpu_popup is not None:
                cpu_popup.set_rows(self._build_cpu_popup_rows())
        except Exception:
            pass
        try:
            gpu_popup = self._status_popups.get("gpu")
            if gpu_popup is not None:
                gpu_popup.set_rows(self._build_gpu_popup_rows())
        except Exception:
            pass
        self._reposition_status_detail_popups()

    def _reposition_status_detail_popups(self):
        anchor_map = {
            "cpu": getattr(self, "lbl_cpu_status", None),
            "gpu": getattr(self, "lbl_gpu_status", None),
        }
        try:
            visible_items = []
            for kind in ("cpu", "gpu"):
                popup = getattr(self, "_status_popups", {}).get(kind)
                anchor = anchor_map.get(kind)
                if popup is None or anchor is None or not popup.isVisible():
                    continue
                top_left = anchor.mapToGlobal(QPoint(0, 0))
                center_x = int(top_left.x() + anchor.width() / 2)
                top_y = int(top_left.y())
                visible_items.append(
                    {
                        "kind": kind,
                        "popup": popup,
                        "anchor": anchor,
                        "center_x": center_x,
                        "top_y": top_y,
                    }
                )
            if not visible_items:
                return
        except Exception:
            return

        gap = 10
        top_y = max(0, min(int(item["top_y"]) for item in visible_items) - 8)

        if len(visible_items) == 1:
            item = visible_items[0]
            popup = item["popup"]
            try:
                x = int(item["center_x"] - popup.width() / 2)
                y = int(top_y - popup.height())
                popup.move(x, max(0, y))
            except Exception:
                return
            return

        try:
            visible_items.sort(key=lambda item: item["center_x"])
            total_width = sum(int(item["popup"].width()) for item in visible_items) + gap * (len(visible_items) - 1)
            left_center = int(visible_items[0]["center_x"])
            right_center = int(visible_items[-1]["center_x"])
            cluster_center = int((left_center + right_center) / 2)
            start_x = int(cluster_center - total_width / 2)
        except Exception:
            start_x = None

        if start_x is None:
            return

        current_x = int(start_x)
        for item in visible_items:
            popup = item["popup"]
            try:
                y = int(top_y - popup.height())
                popup.move(current_x, max(0, y))
                current_x += int(popup.width()) + gap
            except Exception:
                continue

    def _toggle_status_detail_popup(self, kind: str):
        kind = str(kind or "").strip().lower()
        popup = getattr(self, "_status_popups", {}).get(kind)
        if popup is None:
            return
        for other_kind, other_popup in getattr(self, "_status_popups", {}).items():
            if other_kind == kind or other_popup is None:
                continue
            if other_popup.isVisible() and not other_popup.is_pinned():
                other_popup.hide()
        if popup.isVisible() and not popup.is_pinned():
            popup.hide()
            return
        if kind == "gpu":
            try:
                self._gpu_last_request_ts = 0.0
            except Exception:
                pass
            try:
                self._request_gpu_util_update(force_detail=True)
            except Exception:
                pass
        self._refresh_status_detail_popups()
        try:
            popup.show()
            self._reposition_status_detail_popups()
            popup.raise_()
            popup.activateWindow()
        except Exception:
            pass

    def _refresh_sys_status_text(self):
        """刷新系统状态栏文本（CPU/GPU/内存）"""
        try:
            self._cpu_detail_cache = self._collect_cpu_detail_metrics()
            cpu_percent = self._cpu_detail_cache.get("system_cpu")
            mem_mb = self._cpu_detail_cache.get("mem_mb")
            self.lbl_cpu_status.setText(f"CPU: {self._format_percent_text(cpu_percent)}")
            self.lbl_gpu_status.setText(f"GPU: {self._gpu_util_text}")
            self.lbl_mem_status.setText(f"Mem: {self._format_mb_text(mem_mb)}")
            self._refresh_status_detail_popups()
        except Exception:
            pass

    def suppress_gpu_util_refresh(self, seconds: float = 3.0):
        try:
            sec = float(seconds)
        except Exception:
            sec = 3.0
        if sec <= 0:
            return
        try:
            self._gpu_suppress_until = max(float(getattr(self, "_gpu_suppress_until", 0.0) or 0.0), float(time.monotonic()) + sec)
        except Exception:
            try:
                self._gpu_suppress_until = float(time.monotonic()) + sec
            except Exception:
                self._gpu_suppress_until = 0.0

    def reset_click_count(self):
        self.settings_click_count = 0
        self.settings_click_timer.stop()

    def _reset_charts_debug_click_count(self):
        self.charts_debug_click_count = 0
        self.charts_debug_click_timer.stop()

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
        if obj == self.btn_filter and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.RightButton:
                try:
                    if self.charts_debug_click_count == 0:
                        self.charts_debug_click_timer.start()
                    self.charts_debug_click_count += 1
                    if self.charts_debug_click_count >= 6:
                        self._reset_charts_debug_click_count()
                        try:
                            enabled = not bool(self.settings_manager.get("debug/charts_web_debug", False))
                        except Exception:
                            enabled = True
                        try:
                            self.settings_manager.set("debug/charts_web_debug", bool(enabled))
                            self.settings_manager.sync()
                        except Exception:
                            pass
                        try:
                            page = getattr(self, "page_charts", None)
                            if page is not None and hasattr(page, "set_debug_enabled"):
                                page.set_debug_enabled(bool(enabled))
                        except Exception:
                            pass
                        try:
                            NotificationManager.instance().show_toast("数据图表调试已开启" if enabled else "数据图表调试已关闭")
                        except Exception:
                            pass
                        # 根据debug模式显示/隐藏Web版按钮
                        try:
                            if enabled:
                                self.btn_library_web.show()
                            else:
                                self.btn_library_web.hide()
                        except Exception:
                            pass
                except Exception:
                    pass
                return True
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
            for popup in getattr(self, "_status_popups", {}).values():
                if popup is not None:
                    popup.hide()
        except Exception:
            pass
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
        try:
            lib = getattr(self, "page_library", None)
            if lib is not None and hasattr(lib, "shutdown"):
                lib.shutdown()
        except Exception:
            pass
        try:
            imp = getattr(self, "page_import", None)
            if imp is not None and hasattr(imp, "shutdown"):
                imp.shutdown()
        except Exception:
            pass

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
        try:
            self._reposition_status_detail_popups()
        except Exception:
            pass

    def moveEvent(self, event):
        super().moveEvent(event)
        try:
            self._reposition_status_detail_popups()
        except Exception:
            pass
