from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QMenu,
    QProgressBar,
    QSlider,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QRect, QEvent, QRunnable, QThreadPool, QObject
from PyQt6.QtGui import QPixmap, QImage, QColor, QPainter, QRadialGradient, QBrush, QIcon, QImageReader
from ui.utils.icon_loader import qta
import os
import cv2
import numpy as np
from utils.file.file import load_image, raw_exts
from utils.log_manager import LogManager

from ui.widgets.rating_filter_widget import StarRatingWidget
from ui.utils.color_manager import ColorManager
from cache.big_image_cache_manager import BigImageCacheManager
from cache.cache_manager import ImageCacheManager
import json


def _decode_image_to_qimage_off_main_thread(image_path: str, max_long_edge: int = 3840) -> "QImage | None":
    """在非主线程中解码图片为 QImage，供 PreviewLoadWorker 调用。仅做 I/O 与解码，不触碰任何 Qt 控件。"""
    if not image_path or not os.path.exists(image_path):
        return None
    ext = ""
    try:
        ext = os.path.splitext(str(image_path))[1].lower()
    except Exception:
        pass
    qimage = None
    if ext and ext not in set([str(x).lower() for x in (raw_exts or [])]):
        try:
            from utils.system.stderr_suppressor import suppress_stderr_fd
            with suppress_stderr_fd():
                reader = QImageReader(image_path)
                reader.setAutoTransform(True)
            try:
                size = reader.size()
            except Exception:
                size = None
            max_edge = max(800, min(4096, max(2560, max_long_edge)))
            if size is not None and size.isValid():
                try:
                    w, h = int(size.width()), int(size.height())
                    if w > 0 and h > 0:
                        long_edge = max(w, h)
                        if long_edge > max_edge:
                            if w >= h:
                                tw, th = int(max_edge), max(1, int(h * (max_edge / max(1, w))))
                            else:
                                th, tw = int(max_edge), max(1, int(w * (max_edge / max(1, h))))
                            reader.setScaledSize(QSize(tw, th))
                except Exception:
                    pass
            with suppress_stderr_fd():
                qimage = reader.read()
        except Exception:
            qimage = None
    if qimage is None or qimage.isNull():
        try:
            cv_img = load_image(image_path)
            if cv_img is not None:
                cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                height, width, channel = cv_img.shape
                bytes_per_line = 3 * width
                qimage = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
        except Exception:
            qimage = None
    if qimage is None or qimage.isNull():
        try:
            qimage = QImage(image_path)
        except Exception:
            return None
    return qimage if (qimage is not None and not qimage.isNull()) else None


class _PreviewLoadSignals(QObject):
    """仅用于跨线程信号，保证 finished 在主线程槽中执行。"""
    finished = pyqtSignal(str, object, int, object)  # path, QImage, generation, error_msg


class PreviewLoadWorker(QRunnable):
    """后台解码预览图，不触碰 UI；解码完成后通过信号将 QImage 传回主线程，由主线程更新 UI。"""

    def __init__(self, image_path: str, generation: int, cache: "BigImageCacheManager", signals: _PreviewLoadSignals):
        super().__init__()
        self.image_path = image_path
        self.generation = generation
        self._cache = cache
        self._signals = signals
        self._max_long_edge = 3840

    def set_max_long_edge(self, value):
        self._max_long_edge = max(800, min(4096, value))

    def run(self):
        import os
        # P1 优化：在后台线程检查文件是否存在，避免主线程阻塞
        if not self.image_path or not os.path.exists(self.image_path):
            self._signals.finished.emit(self.image_path, None, self.generation, "文件不存在")
            return
        try:
            qimg = _decode_image_to_qimage_off_main_thread(self.image_path, self._max_long_edge)
        except Exception:
            qimg = None
        if qimg is None or qimg.isNull():
            self._signals.finished.emit(self.image_path, None, self.generation, "解码失败")
            return
        try:
            self._cache.put(self.image_path, qimg)
        except Exception:
            pass
        try:
            self._signals.finished.emit(self.image_path, qimg.copy(), self.generation, None)
        except Exception:
            self._signals.finished.emit(self.image_path, None, self.generation, "信号发送失败")


class PreviewPanel(QWidget):
    """图片预览面板"""
    
    # 信号：可见性改变 (is_visible)
    visibility_changed = pyqtSignal(bool)
    # 信号：收藏状态改变 (checked)
    fav_toggled = pyqtSignal(bool)
    # 信号：评分改变 (rating)
    rating_changed = pyqtSignal(int)
    # 信号：色标改变 (label)
    label_changed = pyqtSignal(str)
    vertical_toggle_requested = pyqtSignal()
    
    def __init__(self, settings_manager, parent=None, cache_context: str = "library"):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self._cache_context = str(cache_context or "library")
        self._big_cache = BigImageCacheManager.instance(self._cache_context)
        # 缩略图缓存管理器，用于快速显示缩略图
        self._thumb_cache = ImageCacheManager.instance()
        self.current_original_pixmap = None
        self.current_image_path = None
        self.is_expanded = True # 默认展开
        self.current_label = None
        self._overlay_bbox = None
        self._overlay_focus_point = None
        self._overlay_eye_coordinates = None
        self._overlay_orig_size = None
        self._zoom_percent = 100
        self._pan_offset = (0, 0)
        self._panning = False
        self._last_pan_pos = None
        self._vert_collapsed = False
        self._preview_load_gen = 0
        self._preview_load_signals = _PreviewLoadSignals(self)
        self._preview_load_signals.finished.connect(self._on_preview_load_finished)
        # 标记当前显示的是否是缩略图（临时显示）
        self._showing_thumbnail = False
        
        # 色标颜色映射 (与 ImageThumbnail 保持一致)
        self.LABEL_COLORS = {
            'Red': '#FF3B30',      # Apple Red
            'Yellow': '#FFCC00',   # Apple Yellow
            'Green': '#66BB6A',    # Desaturated Green
            'Blue': '#007AFF',     # Apple Blue
            'Purple': '#AF52DE',   # Apple Purple
            'White': '#FFFFFF',    # White
            'Orange': '#FF9500',   # Apple Orange
            'Pink': '#FF80AB',     # Desaturated Pink
            'Black': '#48484A',    # Apple Gray
            'Cyan': '#5AC8FA',     # Apple Cyan
            'Gray': '#8E8E93',     # Apple Gray
            'None': '#B0B0B0'      # Default Gray
        }
        
        self.init_ui()
        ColorManager.instance().register_listener(self._apply_theme_styles)
        try:
            if hasattr(self.settings_manager, "setting_changed"):
                self.settings_manager.setting_changed.connect(self._on_setting_changed)
        except Exception:
            pass

    def _on_setting_changed(self, key, _value):
        try:
            k = str(key or "")
        except Exception:
            k = ""
        if k in ("focus_detect_ui/show_subject_rect", "focus_detect_ui/show_focus_point"):
            try:
                self._mark_image_dirty()
            except Exception:
                pass
        
    def init_ui(self):
        # 基本属性
        self.setMinimumWidth(150)
        self.setMaximumWidth(800)
        self.setMinimumHeight(34)
        
        # 主布局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 10, 15, 10)
        self.main_layout.setSpacing(10)
        
        # 1. 顶部：折叠按钮
        self.header_widget = QWidget()
        self.header_widget.setStyleSheet("border: none; background: transparent;")
        try:
            self.header_widget.setFixedHeight(34)
        except Exception:
            pass
        self.top_widget = self.header_widget
        top_layout = QHBoxLayout(self.header_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setIconSize(QSize(18, 18))
        self.toggle_btn.setFixedSize(24, 24)
        self.toggle_btn.setToolTip("折叠预览")
        self.toggle_btn.clicked.connect(self.on_toggle_clicked)
        
        top_layout.addWidget(self.toggle_btn)

        self.vert_toggle_btn = QPushButton()
        self.vert_toggle_btn.setIconSize(QSize(18, 18))
        self.vert_toggle_btn.setFixedSize(24, 24)
        self.vert_toggle_btn.setToolTip("收起预览")
        self.vert_toggle_btn.clicked.connect(lambda: self.vertical_toggle_requested.emit())
        top_layout.addWidget(self.vert_toggle_btn)
        top_layout.addStretch()

        self.zoom_out_btn = QPushButton()
        self.zoom_out_btn.setFixedSize(24, 24)
        self.zoom_out_btn.setToolTip("缩小")

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 400)
        self.zoom_slider.setValue(int(self._zoom_percent))
        self.zoom_slider.setFixedWidth(120)

        self.zoom_in_btn = QPushButton()
        self.zoom_in_btn.setFixedSize(24, 24)
        self.zoom_in_btn.setToolTip("放大")

        self.zoom_label = QLabel(f"{int(self._zoom_percent)}%")
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.zoom_out_btn.clicked.connect(lambda: self._set_zoom_percent(int(self._zoom_percent) - 10))
        self.zoom_in_btn.clicked.connect(lambda: self._set_zoom_percent(int(self._zoom_percent) + 10))
        self.zoom_slider.valueChanged.connect(self._set_zoom_percent)

        top_layout.addWidget(self.zoom_out_btn)
        top_layout.addWidget(self.zoom_slider)
        top_layout.addWidget(self.zoom_in_btn)

        self.zoom_reset_btn = QPushButton()
        self.zoom_reset_btn.setFixedSize(24, 24)
        self.zoom_reset_btn.setToolTip("恢复适配")
        self.zoom_reset_btn.clicked.connect(self.reset_view)
        top_layout.addWidget(self.zoom_reset_btn)

        top_layout.addWidget(self.zoom_label)
        self.main_layout.addWidget(self.header_widget)
        
        self.body_widget = QWidget()
        body_layout = QVBoxLayout(self.body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        # 2. 中间：预览图片
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(1, 1)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setScaledContents(False) # 保持比例，手动缩放
        self.image_label.setMouseTracking(True)
        self.image_label.installEventFilter(self)
        body_layout.addWidget(self.image_label, 1)

        self.progress_widget = QWidget()
        self.progress_widget.setStyleSheet("border: none; background: transparent;")
        progress_layout = QVBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(6)

        self.task_progress_bar = QProgressBar()
        self.task_progress_bar.setFixedHeight(8)
        self.task_progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.task_progress_bar)

        self.task_progress_label = QLabel("")
        self.task_progress_label.setWordWrap(True)
        progress_layout.addWidget(self.task_progress_label)

        body_layout.addWidget(self.progress_widget)
        self.progress_widget.hide()
        
        # 3. 底部：收藏和评分
        self.bottom_widget = QWidget()
        self.bottom_widget.setStyleSheet("border: none; background: transparent;")
        bottom_layout = QHBoxLayout(self.bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)
        bottom_layout.addStretch()
        
        # 收藏按钮
        self.fav_btn = QPushButton()
        self.fav_btn.setIconSize(QSize(24, 24))
        self.fav_btn.setCheckable(True)
        self.fav_btn.setFixedSize(36, 36)
        self.fav_btn.setToolTip("收藏")
        self.fav_btn.toggled.connect(self.on_fav_toggled)
        bottom_layout.addWidget(self.fav_btn)
        
        # 色标按钮
        self.label_btn = QPushButton()
        self.label_btn.setFixedSize(36, 36)
        self.label_btn.setToolTip("设置色标")
        self.label_btn.clicked.connect(self.on_label_clicked)
        self.update_label_icon(None) # 初始化为灰色
        bottom_layout.addWidget(self.label_btn)

        # 评分控件
        self.star_rating = StarRatingWidget(size=28, font_size=20)
        self.star_rating.ratingChanged.connect(self.on_rating_changed)
        bottom_layout.addWidget(self.star_rating)
        
        bottom_layout.addStretch()
        body_layout.addWidget(self.bottom_widget)
        self.bottom_widget.hide() # 初始状态隐藏，直到加载图片

        self.main_layout.addWidget(self.body_widget, 1)
        self._apply_theme_styles()

    def _set_zoom_percent(self, value):
        try:
            v = int(value)
        except Exception:
            return
        v = max(10, min(400, v))
        if int(getattr(self, "_zoom_percent", 100) or 100) == v:
            return
        self._zoom_percent = v
        try:
            if self.zoom_slider.value() != v:
                self.zoom_slider.blockSignals(True)
                self.zoom_slider.setValue(v)
                self.zoom_slider.blockSignals(False)
        except Exception:
            pass
        try:
            self.zoom_label.setText(f"{int(v)}%")
        except Exception:
            pass
        try:
            self._mark_image_dirty()
        except Exception:
            pass

    def reset_view(self):
        self._pan_offset = (0, 0)
        self._panning = False
        self._last_pan_pos = None
        try:
            self._set_zoom_percent(100)
        except Exception:
            try:
                self._mark_image_dirty()
            except Exception:
                pass

    def set_vertical_collapsed(self, collapsed: bool):
        self._vert_collapsed = bool(collapsed)
        try:
            self.body_widget.setVisible(not bool(collapsed))
        except Exception:
            pass
        try:
            self.zoom_out_btn.setEnabled(not bool(collapsed))
            self.zoom_in_btn.setEnabled(not bool(collapsed))
            self.zoom_slider.setEnabled(not bool(collapsed))
            self.zoom_reset_btn.setEnabled(not bool(collapsed))
        except Exception:
            pass
        try:
            for w in (self.zoom_out_btn, self.zoom_slider, self.zoom_in_btn, self.zoom_reset_btn, self.zoom_label):
                w.setVisible(not bool(collapsed))
        except Exception:
            pass
        try:
            if bool(collapsed):
                self.main_layout.setContentsMargins(6, 4, 6, 4)
                self.main_layout.setSpacing(0)
            else:
                self.main_layout.setContentsMargins(15, 10, 15, 10)
                self.main_layout.setSpacing(10)
        except Exception:
            pass
        try:
            self._apply_theme_styles()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if obj is getattr(self, "image_label", None):
            try:
                t = event.type()
            except Exception:
                t = None
            if t == QEvent.Type.MouseButtonPress:
                try:
                    if event.button() == Qt.MouseButton.LeftButton:
                        if self.current_original_pixmap is not None and not self.current_original_pixmap.isNull():
                            self._panning = True
                            self._last_pan_pos = event.position()
                            try:
                                self.image_label.setCursor(Qt.CursorShape.ClosedHandCursor)
                            except Exception:
                                pass
                            return True
                except Exception:
                    pass
            elif t == QEvent.Type.MouseMove:
                if bool(getattr(self, "_panning", False)) and getattr(self, "_last_pan_pos", None) is not None:
                    try:
                        cur = event.position()
                        last = self._last_pan_pos
                        dx = float(cur.x() - last.x())
                        dy = float(cur.y() - last.y())
                        ox, oy = self._pan_offset
                        self._pan_offset = (int(ox + dx), int(oy + dy))
                        self._last_pan_pos = cur
                        self.update_image_size()
                        return True
                    except Exception:
                        pass
            elif t == QEvent.Type.MouseButtonRelease:
                try:
                    if event.button() == Qt.MouseButton.LeftButton:
                        self._panning = False
                        self._last_pan_pos = None
                        try:
                            self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
                        except Exception:
                            pass
                        return True
                except Exception:
                    pass
            elif t == QEvent.Type.Leave:
                if bool(getattr(self, "_panning", False)):
                    self._panning = False
                    self._last_pan_pos = None
                    try:
                        self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
                    except Exception:
                        pass
        try:
            return super().eventFilter(obj, event)
        except Exception:
            return False

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.primary")
        border = cm.get("popup.border.primary")
        icon_color = cm.get("theme.text.dark")
        hover_bg = cm.get("theme.primary")
        fav_hover = cm.get("theme.background.dark")
        tooltip_text = cm.get("tooltip.text")
        tooltip_bg = cm.get("tooltip.background")
        tooltip_border = cm.get("tooltip.border")
        text_color = cm.get("popup.text.primary", "#333333")
        primary_color = cm.get("theme.primary", "#2196F3")
        progress_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {panel_bg};
                border-top: 1px solid {border};
            }}
        """)
        header_btn_qss = f"""
            QPushButton {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border-radius: 3px;
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
                font-family: "Microsoft YaHei";
            }}
        """
        self.toggle_btn.setStyleSheet(header_btn_qss)
        try:
            self.vert_toggle_btn.setStyleSheet(header_btn_qss)
        except Exception:
            pass
        if self.is_expanded:
            self.toggle_btn.setIcon(qta.icon("mdi6.chevron-right", color=icon_color, options=[{"scale_factor": 1.1}]))
        else:
            self.toggle_btn.setIcon(qta.icon("mdi6.chevron-left", color=icon_color, options=[{"scale_factor": 1.1}]))
        try:
            if bool(getattr(self, "_vert_collapsed", False)):
                self.vert_toggle_btn.setIcon(qta.icon("mdi6.chevron-down", color=icon_color, options=[{"scale_factor": 1.1}]))
                self.vert_toggle_btn.setToolTip("展开预览")
            else:
                self.vert_toggle_btn.setIcon(qta.icon("mdi6.chevron-up", color=icon_color, options=[{"scale_factor": 1.1}]))
                self.vert_toggle_btn.setToolTip("收起预览")
        except Exception:
            pass
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {panel_bg};
                border: 1px solid {border};
            }}
        """)
        try:
            btn_qss = f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {border};
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    border: 1px solid {primary_color};
                    background-color: {fav_hover};
                }}
                QToolTip {{
                    color: {tooltip_text};
                    background-color: {tooltip_bg};
                    border: 1px solid {tooltip_border};
                    font-family: "Microsoft YaHei";
                }}
            """
            self.zoom_out_btn.setStyleSheet(btn_qss)
            self.zoom_in_btn.setStyleSheet(btn_qss)
            self.zoom_reset_btn.setStyleSheet(btn_qss)
            self.zoom_out_btn.setIcon(qta.icon("mdi6.magnify-minus-outline", color=icon_color, options=[{"scale_factor": 1.0}]))
            self.zoom_in_btn.setIcon(qta.icon("mdi6.magnify-plus-outline", color=icon_color, options=[{"scale_factor": 1.0}]))
            self.zoom_reset_btn.setIcon(qta.icon("mdi6.fit-to-screen-outline", color=icon_color, options=[{"scale_factor": 1.0}]))
            self.zoom_label.setStyleSheet(f"QLabel {{ color: {text_color}; background: transparent; border: none; font-size: 12px; }}")
        except Exception:
            pass
        self.fav_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {fav_hover};
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
                font-family: "Microsoft YaHei";
            }}
        """)
        self._update_fav_icon()
        self.label_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 18px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton::menu-indicator {{
                image: none;
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
                font-family: "Microsoft YaHei";
            }}
        """)

        self.task_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {progress_bg};
                border-radius: 4px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {primary_color};
                border-radius: 4px;
            }}
        """)
        self.task_progress_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: 12px;
                border: none;
                background: transparent;
            }}
        """)
        try:
            if self.current_original_pixmap is not None:
                self._mark_image_dirty()
        except Exception:
            pass

    def set_task_progress(self, *, visible: bool, current: int = 0, total: int = 0, text: str = ""):
        """
        设置面板中的任务进度显示。

        Args:
            visible: 是否显示进度区域
            current: 已完成数量
            total: 总数量
            text: 进度说明文字
        """
        try:
            self.task_progress_label.setText(str(text or ""))
        except Exception:
            pass

        if not visible:
            self.progress_widget.hide()
            return

        if total and total > 0:
            try:
                self.task_progress_bar.setRange(0, int(total))
                self.task_progress_bar.setValue(min(int(current), int(total)))
            except Exception:
                pass
        else:
            try:
                self.task_progress_bar.setRange(0, 0)
            except Exception:
                pass

        self.progress_widget.show()

    def _update_fav_icon(self):
        if self.fav_btn.isChecked():
            icon_color = ColorManager.instance().get("preview.favorite.active")
            icon_name = "mdi6.heart"
        else:
            icon_color = ColorManager.instance().get("theme.text.dark")
            icon_name = "mdi6.heart-outline"
        self.fav_btn.setIcon(qta.icon(icon_name, color=icon_color, options=[{"scale_factor": 1.1}]))

    def load_image(self, image_path, initial_pixmap=None):
        """加载并在预览区显示图片

        优化策略：
        1. 先检查大图片缓存，如果有直接显示
        2. 如果传入了 initial_pixmap（当前显示的缩略图），直接显示它（最快）
        3. 如果没有传入，尝试从缩略图缓存加载
        4. 同时启动后台线程加载原图，加载完成后替换

        参数:
            image_path: 图片路径
            initial_pixmap: 可选，当前已经显示的缩略图QPixmap，直接用于预览
        """
        self.current_image_path = image_path
        self._showing_thumbnail = False

        if not image_path:
            # 清空显示，不显示"图片不存在"，保持空白或显示之前的统计信息(如果没被清空的话)
            # 但这里我们清空它，以便 clear_preview 能正常工作
            self.image_label.setText("")
            self.image_label.setPixmap(QPixmap())
            self.current_original_pixmap = None
            self._overlay_bbox = None
            self._overlay_focus_point = None
            self._overlay_orig_size = None
            self.bottom_widget.hide()
            try:
                self.zoom_out_btn.setEnabled(False)
                self.zoom_in_btn.setEnabled(False)
                self.zoom_slider.setEnabled(False)
                self.zoom_reset_btn.setEnabled(False)
            except Exception:
                pass
            return

        try:
            # 第一步：检查大图片缓存
            cached = None
            try:
                cached = self._big_cache.get(image_path)
            except Exception:
                cached = None
            if cached is not None and not cached.isNull():
                pixmap = QPixmap.fromImage(cached)
                if not pixmap.isNull():
                    self.current_original_pixmap = pixmap
                    self._mark_image_dirty()
                    self.image_label.setText("")
                    if self.is_expanded:
                        self.bottom_widget.show()
                    try:
                        self.zoom_out_btn.setEnabled(True)
                        self.zoom_in_btn.setEnabled(True)
                        self.zoom_slider.setEnabled(True)
                        self.zoom_reset_btn.setEnabled(True)
                    except Exception:
                        pass
                    return

            # 第二步：如果有传入的缩略图pixmap，直接显示（最快路径）
            if initial_pixmap is not None and not initial_pixmap.isNull():
                # 将传入的缩略图缩放到预览面板大小并显示
                try:
                    panel_size = self.size()
                    margins = self.main_layout.contentsMargins()
                    bottom_height = self.bottom_widget.height() if self.bottom_widget.isVisible() else 0
                    top_height = self.top_widget.height()
                    available_width = panel_size.width() - margins.left() - margins.right() - 4
                    available_height = panel_size.height() - margins.top() - margins.bottom() - bottom_height - top_height - 20

                    # 缩略图缩放到适合预览面板的大小
                    thumb_scaled = initial_pixmap.scaled(
                        max(1, available_width),
                        max(1, available_height),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    if not thumb_scaled.isNull():
                        self.current_original_pixmap = thumb_scaled
                        self._showing_thumbnail = True  # 标记当前显示的是缩略图
                        self._mark_image_dirty()
                        self.image_label.setText("")
                        if self.is_expanded:
                            self.bottom_widget.show()
                        try:
                            self.zoom_out_btn.setEnabled(True)
                            self.zoom_in_btn.setEnabled(True)
                            self.zoom_slider.setEnabled(True)
                            self.zoom_reset_btn.setEnabled(True)
                        except Exception:
                            pass
                except Exception:
                    pass
            else:
                # 第三步：没有传入pixmap，尝试从缩略图缓存加载
                thumb_image = None
                try:
                    thumb_image = self._thumb_cache.get_image(image_path)
                except Exception:
                    thumb_image = None

                if thumb_image is not None and not thumb_image.isNull():
                    # 将缩略图缩放到预览面板大小并显示
                    try:
                        panel_size = self.size()
                        margins = self.main_layout.contentsMargins()
                        bottom_height = self.bottom_widget.height() if self.bottom_widget.isVisible() else 0
                        top_height = self.top_widget.height()
                        available_width = panel_size.width() - margins.left() - margins.right() - 4
                        available_height = panel_size.height() - margins.top() - margins.bottom() - bottom_height - top_height - 20

                        # 缩略图缩放到适合预览面板的大小
                        thumb_scaled = thumb_image.scaled(
                            max(1, available_width),
                            max(1, available_height),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        thumb_pixmap = QPixmap.fromImage(thumb_scaled)
                        if not thumb_pixmap.isNull():
                            self.current_original_pixmap = thumb_pixmap
                            self._showing_thumbnail = True  # 标记当前显示的是缩略图
                            self._mark_image_dirty()
                            self.image_label.setText("")
                            if self.is_expanded:
                                self.bottom_widget.show()
                            try:
                                self.zoom_out_btn.setEnabled(True)
                                self.zoom_in_btn.setEnabled(True)
                                self.zoom_slider.setEnabled(True)
                                self.zoom_reset_btn.setEnabled(True)
                            except Exception:
                                pass
                    except Exception:
                        pass

            # 第四步：启动后台线程加载原图，加载完成后替换缩略图
            self._preview_load_gen += 1
            self.current_image_path = image_path
            self._overlay_bbox = None
            self._overlay_focus_point = None
            self._overlay_orig_size = None
            max_edge = 3840
            try:
                panel_size = self.size()
                margins = self.main_layout.contentsMargins()
                bottom_height = self.bottom_widget.height() if self.bottom_widget.isVisible() else 0
                top_height = self.top_widget.height()
                available_width = panel_size.width() - margins.left() - margins.right() - 4
                available_height = panel_size.height() - margins.top() - margins.bottom() - bottom_height - top_height - 20
                max_edge = int(max(1600, min(4096, max(available_width, available_height) * 2)))
            except Exception:
                pass
            worker = PreviewLoadWorker(image_path, self._preview_load_gen, self._big_cache, self._preview_load_signals)
            worker.set_max_long_edge(max_edge)
            QThreadPool.globalInstance().start(worker)
            return
            
        except Exception as e:
            try:
                LogManager.instance().warning(f"预览图片失败: {e}")
            except Exception:
                pass
            self.image_label.setText(f"预览失败: {str(e)}")
            self.image_label.setPixmap(QPixmap())
            self.current_original_pixmap = None
            self._overlay_bbox = None
            self._overlay_focus_point = None
            self._overlay_eye_coordinates = None
            self._overlay_orig_size = None
            self.bottom_widget.hide()
            try:
                self.zoom_out_btn.setEnabled(False)
                self.zoom_in_btn.setEnabled(False)
                self.zoom_slider.setEnabled(False)
                self.zoom_reset_btn.setEnabled(False)
            except Exception:
                pass

    def _on_preview_load_finished(self, path: str, qimage, generation: int, error_msg=None):
        """仅在主线程执行：校验请求未过期后更新 UI，保证线程隔离。

        优化：如果当前显示的是缩略图，原图加载完成后会替换缩略图。
        """
        if path != getattr(self, "current_image_path", None):
            return
        if generation != getattr(self, "_preview_load_gen", 0):
            return
        try:
            self.image_label.setToolTip("")
        except Exception:
            pass
        if qimage is None or qimage.isNull():
            # 如果当前显示的是缩略图，不显示错误，保持缩略图显示
            if getattr(self, "_showing_thumbnail", False):
                return
            # P1 优化：显示具体的错误信息
            display_msg = "无法加载图片"
            if error_msg == "文件不存在":
                display_msg = "图片不存在"
            self.image_label.setText(display_msg)
            self.image_label.setPixmap(QPixmap())
            self.current_original_pixmap = None
            self.bottom_widget.hide()
            try:
                self.zoom_out_btn.setEnabled(False)
                self.zoom_in_btn.setEnabled(False)
                self.zoom_slider.setEnabled(False)
                self.zoom_reset_btn.setEnabled(False)
            except Exception:
                pass
            return
        try:
            pixmap = QPixmap.fromImage(qimage)
        except Exception:
            # 如果当前显示的是缩略图，不显示错误，保持缩略图显示
            if getattr(self, "_showing_thumbnail", False):
                return
            self.image_label.setText("无法加载图片")
            self.image_label.setPixmap(QPixmap())
            self.current_original_pixmap = None
            return
        if pixmap.isNull():
            # 如果当前显示的是缩略图，不显示错误，保持缩略图显示
            if getattr(self, "_showing_thumbnail", False):
                return
            self.image_label.setText("无法加载图片")
            self.image_label.setPixmap(QPixmap())
            self.current_original_pixmap = None
            return
        # 原图加载完成，替换缩略图（如果有的话）
        self.current_original_pixmap = pixmap
        self._showing_thumbnail = False  # 标记现在显示的是原图
        self.image_label.setText("")
        self._mark_image_dirty()
        if self.is_expanded:
            self.bottom_widget.show()
        try:
            self.zoom_out_btn.setEnabled(True)
            self.zoom_in_btn.setEnabled(True)
            self.zoom_slider.setEnabled(True)
            self.zoom_reset_btn.setEnabled(True)
        except Exception:
            pass

    def set_overlays(self, bbox=None, focus_point=None, eye_coordinates=None, orig_size=None):
        self._overlay_bbox = bbox
        self._overlay_focus_point = focus_point
        self._overlay_eye_coordinates = eye_coordinates
        self._overlay_orig_size = orig_size
        try:
            self._mark_image_dirty()
        except Exception:
            pass

    def show_folder_stats(self, folder_name, stats):
        """显示文件夹统计信息"""
        self.current_image_path = None
        self.current_original_pixmap = None
        self._overlay_bbox = None
        self._overlay_focus_point = None
        self._overlay_eye_coordinates = None
        self._overlay_orig_size = None
        self.bottom_widget.hide()
        try:
            self.zoom_out_btn.setEnabled(False)
            self.zoom_in_btn.setEnabled(False)
            self.zoom_slider.setEnabled(False)
            self.zoom_reset_btn.setEnabled(False)
        except Exception:
            pass
        
        if not stats:
            cm = ColorManager.instance()
            text_color = cm.get("theme.text.dark")
            self.image_label.setText(f"<div style='text-align: center; color: {text_color};'><h3>{folder_name}</h3><p>暂无统计信息</p></div>")
            return
            
        species_count = stats.get('species_count', 0)
        image_count = stats.get('image_count', 0)
        
        cm = ColorManager.instance()
        text_color = cm.get("theme.text.dark")
        accent_color = cm.get("theme.primary")
        html = f"""
        <div style='text-align: center; color: {text_color};'>
            <h2 style='margin-bottom: 20px;'>{folder_name}</h2>
            <div style='font-size: 16px; margin: 10px;'>
                <p>物种数量: <span style='color: {accent_color}; font-weight: bold;'>{species_count}</span></p>
                <p>图片总数: <span style='color: {accent_color}; font-weight: bold;'>{image_count}</span></p>
            </div>
        </div>
        """
        self.image_label.setText(html)
        self.image_label.show()

    def _mark_image_dirty(self):
        """P2：合并同一事件循环内多次 update_image_size，只执行一次"""
        if getattr(self, "_image_dirty", False):
            return
        self._image_dirty = True
        QTimer.singleShot(0, self._flush_image_update)

    def _flush_image_update(self):
        self._image_dirty = False
        self.update_image_size()

    def update_image_size(self):
        """根据面板大小调整图片显示"""
        if not self.current_original_pixmap:
            return
            
        if not self.is_expanded or self.image_label.isHidden():
            return

        try:
            pixmap = self.current_original_pixmap
            try:
                canvas_w = int(self.image_label.width() or 0)
                canvas_h = int(self.image_label.height() or 0)
            except Exception:
                canvas_w = 0
                canvas_h = 0
            if canvas_w <= 1 or canvas_h <= 1:
                panel_size = self.size()
                margins = self.main_layout.contentsMargins()
                bottom_height = self.bottom_widget.height() if self.bottom_widget.isVisible() else 0
                top_height = self.top_widget.height()
                canvas_w = int(panel_size.width() - margins.left() - margins.right() - 4)
                canvas_h = int(panel_size.height() - margins.top() - margins.bottom() - bottom_height - top_height - 20)
            canvas_w = max(1, int(canvas_w))
            canvas_h = max(1, int(canvas_h))

            # 计算缩放
            pixmap_width = pixmap.width()
            pixmap_height = pixmap.height()
            
            scale_w = canvas_w / pixmap_width if pixmap_width > 0 else 1
            scale_h = canvas_h / pixmap_height if pixmap_height > 0 else 1
            scale = min(scale_w, scale_h)
            try:
                z = float(getattr(self, "_zoom_percent", 100) or 100) / 100.0
            except Exception:
                z = 1.0
            try:
                z = float(max(0.1, min(4.0, z)))
            except Exception:
                z = 1.0
            scale = float(scale) * float(z)
            
            new_width = int(pixmap_width * scale)
            new_height = int(pixmap_height * scale)
            
            scaled_pixmap = pixmap.scaled(new_width, new_height,
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            try:
                bbox = self._overlay_bbox
                fp = self._overlay_focus_point
                eye_coordinates = self._overlay_eye_coordinates
                orig_size = self._overlay_orig_size

                def _parse_bbox(v):
                    if v is None:
                        return None
                    if isinstance(v, str):
                        s = v.strip()
                        if not s:
                            return None
                        try:
                            v = json.loads(s)
                        except Exception:
                            return None
                    if isinstance(v, dict):
                        try:
                            x = float(v.get("x"))
                            y = float(v.get("y"))
                            w = float(v.get("w"))
                            h = float(v.get("h"))
                            return x, y, x + w, y + h
                        except Exception:
                            pass
                        try:
                            if all(k in v for k in ("x1", "y1", "x2", "y2")):
                                return float(v.get("x1")), float(v.get("y1")), float(v.get("x2")), float(v.get("y2"))
                        except Exception:
                            pass
                        try:
                            if all(k in v for k in ("left", "top", "right", "bottom")):
                                return float(v.get("left")), float(v.get("top")), float(v.get("right")), float(v.get("bottom"))
                        except Exception:
                            pass
                        return None
                    if isinstance(v, (list, tuple)) and len(v) == 4:
                        try:
                            x1, y1, x2, y2 = v
                            return float(x1), float(y1), float(x2), float(y2)
                        except Exception:
                            return None
                    return None

                def _parse_fp(v):
                    if v is None:
                        return None
                    if isinstance(v, str):
                        s = v.strip()
                        if not s:
                            return None
                        try:
                            v = json.loads(s)
                        except Exception:
                            return None
                    if isinstance(v, dict):
                        try:
                            if "x" in v and "y" in v:
                                return float(v.get("x")), float(v.get("y"))
                        except Exception:
                            return None
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        try:
                            return float(v[0]), float(v[1])
                        except Exception:
                            return None
                    return None

                def _parse_eye(v):
                    if v is None:
                        return None
                    if isinstance(v, str):
                        s = v.strip()
                        if not s:
                            return None
                        try:
                            v = json.loads(s)
                        except Exception:
                            return None
                    if isinstance(v, dict):
                        try:
                            if "x" in v and "y" in v:
                                return float(v.get("x")), float(v.get("y"))
                        except Exception:
                            return None
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        try:
                            return float(v[0]), float(v[1])
                        except Exception:
                            return None
                    return None

                bbox = _parse_bbox(bbox)
                fp = _parse_fp(fp)
                eye_coordinates = _parse_eye(eye_coordinates)

                orig_w = 0.0
                orig_h = 0.0
                try:
                    if isinstance(orig_size, (list, tuple)) and len(orig_size) >= 2:
                        orig_w = float(orig_size[0] or 0)
                        orig_h = float(orig_size[1] or 0)
                except Exception:
                    orig_w = 0.0
                    orig_h = 0.0
                try:
                    # 坐标基准尺寸可能来自“未按 EXIF 旋转的原图尺寸”，而预览 pixmap 往往是按方向显示的
                    # 这里用长宽比接近度做一次启发式纠正，避免对焦点/鸟眼框整体偏移
                    rotated_90 = False
                    if orig_w > 1.0 and orig_h > 1.0 and pixmap.width() > 1 and pixmap.height() > 1:
                        r_disp = float(pixmap.width()) / float(pixmap.height())
                        r_orig = float(orig_w) / float(orig_h)
                        r_swap = float(orig_h) / float(orig_w) if float(orig_w) != 0.0 else r_orig
                        if abs(r_swap - r_disp) < abs(r_orig - r_disp):
                            orig_w, orig_h = float(orig_h), float(orig_w)
                            rotated_90 = True
                except Exception:
                    rotated_90 = False
                    pass

                def _in_bounds_pt(x: float, y: float, w: float, h: float) -> bool:
                    try:
                        return bool(0.0 <= float(x) <= float(w) and 0.0 <= float(y) <= float(h))
                    except Exception:
                        return False

                def _rot90_cw_pt(x: float, y: float, w: float, h: float) -> tuple[float, float]:
                    return float(y), float(w - x)

                def _rot90_ccw_pt(x: float, y: float, w: float, h: float) -> tuple[float, float]:
                    return float(h - y), float(x)

                def _rot_bbox(b, w: float, h: float, rot_fn) -> tuple[float, float, float, float] | None:
                    if b is None:
                        return None
                    try:
                        x1, y1, x2, y2 = b
                        pts = [(float(x1), float(y1)), (float(x2), float(y1)), (float(x2), float(y2)), (float(x1), float(y2))]
                    except Exception:
                        return None
                    out_pts = []
                    for x, y in pts:
                        try:
                            out_pts.append(rot_fn(float(x), float(y), float(w), float(h)))
                        except Exception:
                            return None
                    try:
                        xs = [p[0] for p in out_pts]
                        ys = [p[1] for p in out_pts]
                        return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))
                    except Exception:
                        return None

                def _score_overlay(b, p, e, w: float, h: float) -> float:
                    score = 0.0
                    if b is not None:
                        try:
                            x1, y1, x2, y2 = b
                            if _in_bounds_pt(float(x1), float(y1), w, h) and _in_bounds_pt(float(x2), float(y2), w, h):
                                score += 3.0
                        except Exception:
                            pass
                    if e is not None:
                        try:
                            ex, ey = e
                            if _in_bounds_pt(float(ex), float(ey), w, h):
                                score += 2.0
                                if b is not None:
                                    x1, y1, x2, y2 = b
                                    if float(x1) <= float(ex) <= float(x2) and float(y1) <= float(ey) <= float(y2):
                                        score += 6.0
                        except Exception:
                            pass
                    if p is not None:
                        try:
                            fx, fy = p
                            if _in_bounds_pt(float(fx), float(fy), w, h):
                                score += 1.0
                                if b is not None:
                                    x1, y1, x2, y2 = b
                                    if float(x1) <= float(fx) <= float(x2) and float(y1) <= float(fy) <= float(y2):
                                        score += 2.0
                        except Exception:
                            pass
                    return float(score)

                if rotated_90 and orig_w > 1.0 and orig_h > 1.0:
                    try:
                        src_w = float(orig_h)
                        src_h = float(orig_w)
                        dst_w = float(orig_w)
                        dst_h = float(orig_h)

                        cand = []
                        cand.append(("none", bbox, fp, eye_coordinates))
                        if fp is not None:
                            fx, fy = fp
                            cand_fp_cw = _rot90_cw_pt(float(fx), float(fy), src_w, src_h)
                            cand_fp_ccw = _rot90_ccw_pt(float(fx), float(fy), src_w, src_h)
                        else:
                            cand_fp_cw = cand_fp_ccw = None
                        if eye_coordinates is not None:
                            ex, ey = eye_coordinates
                            cand_eye_cw = _rot90_cw_pt(float(ex), float(ey), src_w, src_h)
                            cand_eye_ccw = _rot90_ccw_pt(float(ex), float(ey), src_w, src_h)
                        else:
                            cand_eye_cw = cand_eye_ccw = None
                        cand.append(
                            (
                                "cw",
                                _rot_bbox(bbox, src_w, src_h, _rot90_cw_pt),
                                cand_fp_cw if cand_fp_cw is not None else None,
                                cand_eye_cw if cand_eye_cw is not None else None,
                            )
                        )
                        cand.append(
                            (
                                "ccw",
                                _rot_bbox(bbox, src_w, src_h, _rot90_ccw_pt),
                                cand_fp_ccw if cand_fp_ccw is not None else None,
                                cand_eye_ccw if cand_eye_ccw is not None else None,
                            )
                        )
                        best = None
                        best_score = -1e9
                        for _, b1, p1, e1 in cand:
                            sc = _score_overlay(b1, p1, e1, dst_w, dst_h)
                            if sc > best_score:
                                best_score = sc
                                best = (b1, p1, e1)
                        if best is not None:
                            bbox, fp, eye_coordinates = best
                    except Exception:
                        pass

                bbox_norm = False
                if bbox is not None:
                    try:
                        x1, y1, x2, y2 = bbox
                        bbox_norm = bool(0.0 <= x1 <= 1.0 and 0.0 <= y1 <= 1.0 and 0.0 <= x2 <= 1.0 and 0.0 <= y2 <= 1.0)
                    except Exception:
                        bbox_norm = False
                fp_norm = False
                eye_norm = False
                if fp is not None:
                    try:
                        fx, fy = fp
                        fp_norm = bool(0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0)
                    except Exception:
                        fp_norm = False
                if eye_coordinates is not None:
                    try:
                        ex, ey = eye_coordinates
                        eye_norm = bool(0.0 <= ex <= 1.0 and 0.0 <= ey <= 1.0)
                    except Exception:
                        eye_norm = False

                base_w_bbox = base_h_bbox = 0.0
                if bbox_norm:
                    base_w_bbox = 1.0
                    base_h_bbox = 1.0
                else:
                    base_w_bbox = float(orig_w or 0.0)
                    base_h_bbox = float(orig_h or 0.0)

                base_w_fp = base_h_fp = 0.0
                if fp_norm:
                    base_w_fp = 1.0
                    base_h_fp = 1.0
                else:
                    base_w_fp = float(orig_w or 0.0)
                    base_h_fp = float(orig_h or 0.0)

                base_w_eye = base_h_eye = 0.0
                if eye_norm:
                    base_w_eye = 1.0
                    base_h_eye = 1.0
                else:
                    base_w_eye = float(orig_w or 0.0)
                    base_h_eye = float(orig_h or 0.0)

                need_fill_bbox = (not bbox_norm) and (base_w_bbox <= 1.0 or base_h_bbox <= 1.0)
                need_fill_fp = (not fp_norm) and (base_w_fp <= 1.0 or base_h_fp <= 1.0)
                need_fill_eye = (not eye_norm) and (base_w_eye <= 1.0 or base_h_eye <= 1.0)
                if need_fill_bbox or need_fill_fp or need_fill_eye:
                    try:
                        ow = float(pixmap.width())
                        oh = float(pixmap.height())
                        if ow > 1 and oh > 1:
                            if need_fill_bbox:
                                base_w_bbox = ow
                                base_h_bbox = oh
                            if need_fill_fp:
                                base_w_fp = ow
                                base_h_fp = oh
                            if need_fill_eye:
                                base_w_eye = ow
                                base_h_eye = oh
                    except Exception:
                        pass

                show_bbox = True
                show_fp = True
                try:
                    if self.settings_manager is not None:
                        show_bbox = bool(self.settings_manager.get("focus_detect_ui/show_subject_rect", True))
                        show_fp = bool(self.settings_manager.get("focus_detect_ui/show_focus_point", True))
                except Exception:
                    show_bbox = True
                    show_fp = True
                can_draw_bbox = bool(show_bbox) and (bbox is not None) and (base_w_bbox > 0.0) and (base_h_bbox > 0.0)
                can_draw_fp = bool(show_fp) and (fp is not None) and (base_w_fp > 0.0) and (base_h_fp > 0.0)
                can_draw_eye = bool(show_bbox) and (eye_coordinates is not None) and (base_w_eye > 0.0) and (base_h_eye > 0.0)

                if (can_draw_bbox or can_draw_fp or can_draw_eye) and scaled_pixmap.width() > 1 and scaled_pixmap.height() > 1:
                    sx_bbox = float(scaled_pixmap.width()) / float(base_w_bbox) if base_w_bbox > 0.0 else 0.0
                    sy_bbox = float(scaled_pixmap.height()) / float(base_h_bbox) if base_h_bbox > 0.0 else 0.0
                    sx_fp = float(scaled_pixmap.width()) / float(base_w_fp) if base_w_fp > 0.0 else 0.0
                    sy_fp = float(scaled_pixmap.height()) / float(base_h_fp) if base_h_fp > 0.0 else 0.0
                    sx_eye = float(scaled_pixmap.width()) / float(base_w_eye) if base_w_eye > 0.0 else 0.0
                    sy_eye = float(scaled_pixmap.height()) / float(base_h_eye) if base_h_eye > 0.0 else 0.0
                    cm = ColorManager.instance()
                    rect_color = cm.qcolor("border.subject_rect", default="#f50f0f")
                    fp_color = cm.qcolor("border.focus_point", default="#f50f0f")
                    eye_color = QColor("#2196F3")
                    painter = QPainter(scaled_pixmap)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    try:
                        pen_w = max(2, int(max(scaled_pixmap.width(), scaled_pixmap.height()) // 250))
                    except Exception:
                        pen_w = 2
                    if can_draw_bbox and bbox is not None:
                        try:
                            x1, y1, x2, y2 = bbox
                            rx = int(round(float(x1) * sx_bbox))
                            ry = int(round(float(y1) * sy_bbox))
                            rw = int(round((float(x2) - float(x1)) * sx_bbox))
                            rh = int(round((float(y2) - float(y1)) * sy_bbox))
                            pen = painter.pen()
                            pen.setColor(rect_color)
                            pen.setWidth(int(pen_w))
                            painter.setPen(pen)
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawRect(QRect(int(rx), int(ry), int(rw), int(rh)))
                        except Exception:
                            pass
                    if can_draw_fp and fp is not None:
                        try:
                            fx, fy = fp
                            px = int(round(float(fx) * sx_fp))
                            py = int(round(float(fy) * sy_fp))
                            r = max(3, int(round(pen_w * 2.2)))
                            pen = painter.pen()
                            pen.setColor(fp_color)
                            pen.setWidth(int(pen_w))
                            painter.setPen(pen)
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawEllipse(px - r, py - r, r * 2, r * 2)
                            painter.drawLine(px - r * 2, py, px + r * 2, py)
                            painter.drawLine(px, py - r * 2, px, py + r * 2)
                        except Exception:
                            pass
                    if eye_coordinates is not None:
                        try:
                            ex, ey = eye_coordinates
                            px = int(round(float(ex) * sx_eye))
                            py = int(round(float(ey) * sy_eye))

                            r = max(4, int(round(pen_w * 2.4)))
                            pen = painter.pen()
                            pen.setColor(eye_color)
                            pen.setWidth(int(pen_w))
                            painter.setPen(pen)
                            painter.setBrush(Qt.BrushStyle.NoBrush)
                            painter.drawRect(QRect(px - r, py - r, r * 2, r * 2))
                        except Exception:
                            pass
                    painter.end()
            except Exception:
                pass

            try:
                base_x = int((canvas_w - scaled_pixmap.width()) // 2)
                base_y = int((canvas_h - scaled_pixmap.height()) // 2)
            except Exception:
                base_x = 0
                base_y = 0

            ox, oy = self._pan_offset
            try:
                if scaled_pixmap.width() <= canvas_w:
                    ox = 0
                else:
                    x0 = int(base_x + int(ox))
                    x0 = int(max(int(canvas_w - scaled_pixmap.width()), min(0, x0)))
                    ox = int(x0 - base_x)
                if scaled_pixmap.height() <= canvas_h:
                    oy = 0
                else:
                    y0 = int(base_y + int(oy))
                    y0 = int(max(int(canvas_h - scaled_pixmap.height()), min(0, y0)))
                    oy = int(y0 - base_y)
            except Exception:
                pass
            self._pan_offset = (int(ox), int(oy))

            try:
                composed = QPixmap(canvas_w, canvas_h)
                try:
                    cm = ColorManager.instance()
                    composed.fill(QColor(cm.get("theme.background.primary")))
                except Exception:
                    composed.fill(Qt.GlobalColor.transparent)
                painter = QPainter(composed)
                painter.drawPixmap(int(base_x + ox), int(base_y + oy), scaled_pixmap)
                painter.end()
                self.image_label.setPixmap(composed)
            except Exception:
                self.image_label.setPixmap(scaled_pixmap)
            
        except Exception as e:
            try:
                LogManager.instance().warning(f"更新预览图片尺寸失败: {e}")
            except Exception:
                pass

    def set_label(self, label):
        """设置显示的色标"""
        self.current_label = label
        self.update_label_icon(label)

    def update_label_icon(self, label):
        """更新色标按钮图标"""
        size = 24
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Determine color
        if label and label in self.LABEL_COLORS and label != 'None' and label != '':
            color_hex = self.LABEL_COLORS[label]
            color = QColor(color_hex)
        else:
            # Gray for None
            color = QColor('#B0B0B0')
            
        # Draw gradient ball
        gradient = QRadialGradient(size * 0.3, size * 0.3, size * 0.8)
        gradient.setColorAt(0, color.lighter(130))
        gradient.setColorAt(0.5, color)
        gradient.setColorAt(1, color.darker(110))
        
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size, size)
        
        # If White, draw a border
        if label == 'White':
             border_color = ColorManager.instance().get("popup.border.primary")
             painter.setPen(QColor(border_color))
             painter.setBrush(Qt.BrushStyle.NoBrush)
             painter.drawEllipse(0, 0, size-1, size-1)

        painter.end()
        
        self.label_btn.setIcon(QIcon(pixmap))

    def on_label_clicked(self):
        """点击色标按钮，弹出菜单"""
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
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 24px 6px 36px;
                border-radius: 2px;
                color: {menu_text};
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
                color: {menu_text};
            }}
            QMenu::icon {{
                padding-left: 10px;
            }}
        """)
        
        # 1. Clear action
        clear_action = menu.addAction("无色标")
        clear_action.setIcon(qta.icon("mdi.circle-outline", color=menu_text))
        clear_action.triggered.connect(lambda: self.label_changed.emit("")) # Emit empty string for clear
        
        menu.addSeparator()
        
        # 2. Colors
        labels = [
            ("Red", "红色"), ("Orange", "橙色"), ("Yellow", "黄色"), 
            ("Green", "绿色"), ("Cyan", "青色"), ("Blue", "蓝色"), 
            ("Purple", "紫色"), ("Pink", "粉色"), ("White", "白色"), 
            ("Gray", "灰色"), ("Black", "黑色")
        ]
        
        for en_name, cn_name in labels:
            action = menu.addAction(cn_name)
            color_hex = self.LABEL_COLORS.get(en_name, "#000000")
            
            # Use qtawesome for menu icons for simplicity
            if en_name == 'White':
                 action.setIcon(qta.icon("mdi.circle", color=color_hex, color_off=menu_border))
            else:
                 action.setIcon(qta.icon("mdi.circle", color=color_hex))
                 
            action.triggered.connect(lambda checked=False, l=en_name: self.label_changed.emit(l))
            
        # 显示在按钮下方
        pos = self.label_btn.mapToGlobal(self.label_btn.rect().bottomLeft())
        # 稍微调整位置
        pos.setY(pos.y() + 2)
        menu.exec(pos)

    def on_toggle_clicked(self):
        """点击折叠/展开按钮"""
        self.is_expanded = not self.is_expanded
        
        if self.is_expanded:
            # 展开状态
            try:
                self.vert_toggle_btn.setVisible(True)
            except Exception:
                pass
            try:
                for w in (self.zoom_out_btn, self.zoom_slider, self.zoom_in_btn, self.zoom_reset_btn, self.zoom_label):
                    w.setVisible(True)
            except Exception:
                pass
            try:
                self.body_widget.setVisible(True)
            except Exception:
                pass
            try:
                self.image_label.show()
            except Exception:
                pass
            if self.current_original_pixmap:
                try:
                    self.bottom_widget.show()
                except Exception:
                    pass
            self.setMinimumWidth(150)
            self.setMaximumWidth(500)
            self.main_layout.setContentsMargins(15, 10, 15, 10)
            self.toggle_btn.setToolTip("折叠预览")
            
            # 延迟更新图片，确保布局完成
            QTimer.singleShot(100, self.update_image_size)
        else:
            # 折叠状态
            try:
                self.vert_toggle_btn.setVisible(False)
            except Exception:
                pass
            try:
                for w in (self.zoom_out_btn, self.zoom_slider, self.zoom_in_btn, self.zoom_reset_btn, self.zoom_label):
                    w.setVisible(False)
            except Exception:
                pass
            try:
                self.body_widget.setVisible(False)
            except Exception:
                pass
            try:
                self.image_label.hide()
            except Exception:
                pass
            try:
                self.bottom_widget.hide()
            except Exception:
                pass
            self.main_layout.setContentsMargins(2, 2, 2, 2)
            self.setMinimumWidth(34)
            self.setMaximumWidth(34)
            self.toggle_btn.setToolTip("展开预览")
            
        # 发送信号通知外部调整Splitter
        self.visibility_changed.emit(self.is_expanded)
        self._apply_theme_styles()

    def set_expanded(self, expanded):
        """外部设置展开状态"""
        if self.is_expanded != expanded:
            self.on_toggle_clicked()

    def on_fav_toggled(self, checked):
        self._update_fav_icon()
        self.fav_toggled.emit(checked)

    def set_favorite(self, is_favorite):
        self.fav_btn.blockSignals(True)
        self.fav_btn.setChecked(is_favorite)
        self._update_fav_icon()
        self.fav_btn.blockSignals(False)

    def on_rating_changed(self, rating):
        """评分改变"""
        self.rating_changed.emit(rating)

    def set_rating(self, rating):
        """设置评分显示 (不触发信号)"""
        # 使用 blockSignals 防止循环触发
        # 这里的 StarRatingWidget.set_rating 已经支持 emit_signal 参数
        self.star_rating.set_rating(rating, emit_signal=False)

    def set_actions_visible(self, visible):
        """设置操作按钮（收藏、色标、评分）的可见性"""
        self.fav_btn.setVisible(visible)
        self.label_btn.setVisible(visible)
        self.star_rating.setVisible(visible)
        
        # 如果都隐藏了，bottom_widget 本身也应该隐藏或高度减小
        # 但这里 bottom_widget 是 QHBoxLayout，如果子控件都隐藏，它会自动塌缩吗？
        # 通常 Layout 不会自动隐藏，除非手动设置
        # 但如果 is_expanded 为 True，load_image 会调用 bottom_widget.show()
        # 所以我们这里只是隐藏内部组件，bottom_widget 依然作为容器存在
        
        # 强制更新布局
        self.bottom_widget.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._mark_image_dirty()
