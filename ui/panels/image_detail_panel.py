import os
import cv2
import numpy as np
import json
import exifread
import time
from datetime import datetime
from typing import Optional
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QGraphicsView, QGraphicsScene, 
                             QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsItem, QFrame, QScrollArea, QSizePolicy,
                             QToolButton, QGraphicsOpacityEffect, QStackedWidget, QSplitter, QApplication, QMenu, QListView, QStyle, QTextBrowser)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QPointF, QTimer, QThread, QEvent, QRectF, QObject
from PyQt6.QtGui import QPixmap, QImage, QIcon, QColor, QPainter, QAction, QTransform, QPainterPath, QBrush, QPen, QRadialGradient, QImageReader, QShortcut
from ui.utils.icon_loader import qta

from utils.file.file import load_image, load_raw_full, raw_exts
from utils.file.fingerprint import get_unique_id
from ui.widgets.image_thumbnail import ImageThumbnail
from ui.widgets.rating_filter_widget import StarRatingWidget
from cache.cache_manager import ImageCacheManager
from cache.big_image_cache_manager import BigImageCacheManager
from utils.sql.data_base import BirdLibraryDB
from utils.setting.settings_manager import SettingsManager
from ui.utils.shortcut_manager import ShortcutManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.color_manager import ColorManager
from ui.panels.info_panel import InfoPanel
from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG
from utils.system.gpu_utils import GPUScaler
from ui.utils.thumbnail_loader import ThumbnailLoader
from utils.log_manager import LogManager
from utils.system.stderr_suppressor import suppress_stderr_fd

from PyQt6.QtCore import QAbstractListModel, QModelIndex
from PyQt6.QtWidgets import QStyledItemDelegate

_ACTIVE_LOADER_THREADS = set()
_ORIG_IMAGE_SIZE_BY_PATH = {}

def _track_loader_thread(t: QThread):
    if t is None:
        return None
    _ACTIVE_LOADER_THREADS.add(t)
    try:
        def _cleanup():
            try:
                _ACTIVE_LOADER_THREADS.discard(t)
            except Exception:
                pass
            try:
                t.deleteLater()
            except Exception:
                pass
        t.finished.connect(_cleanup)
    except Exception:
        pass
    return t


class _OverlayExifBridge(QObject):
    ready = pyqtSignal(str, dict)


class MagnifierGraphicsView(QGraphicsView):
    zoom_in_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()
    magnifier_moved = pyqtSignal(QPoint)
    magnifier_toggled = pyqtSignal(bool)
    magnification_changed = pyqtSignal(float)
    lens_radius_changed = pyqtSignal(int)
    manual_rect_saved = pyqtSignal(object)
    drawing_mode_exited = pyqtSignal()
    ctrl_right_detect_requested = pyqtSignal()

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.magnifier_enabled = False
        self.magnification_factor = 1.5  # 50% 放大 (1.5x)
        self.lens_radius = 150  # 放大镜半径
        self.setMouseTracking(True)  # 追踪鼠标移动
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # 设置缩放锚点为视图中心，这样 Ctrl+滚轮缩放不会跟随鼠标偏移位置
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._external_sync = False # 防止信号循环的标志
        
        # Manual drawing state
        self.drawing_mode = False
        self._drawing_start_pos = None
        self._temp_rect_item = None

    def set_drawing_mode(self, enabled):
        self.drawing_mode = enabled
        if enabled:
            if self.magnifier_enabled:
                self.toggle_magnifier(False)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().unsetCursor()
            if self._temp_rect_item:
                try:
                    if self._temp_rect_item.scene():
                        self._temp_rect_item.scene().removeItem(self._temp_rect_item)
                except Exception:
                    pass
                self._temp_rect_item = None
            self.drawing_mode_exited.emit()

    def set_magnifier_state(self, enabled):
        """设置状态而不发送切换信号（用于同步）"""
        if self.magnifier_enabled == enabled:
            return
        self._external_sync = True
        self.toggle_magnifier(enabled)
        self._external_sync = False

    def set_magnifier_pos(self, pos):
        """设置放大镜位置（用于同步）"""
        if not self.magnifier_enabled:
            return
        # 更新同步位置并刷新视图，paintEvent 会优先使用 _sync_pos
        self._sync_pos = pos
        self.viewport().update()

    def set_magnification(self, factor):
        if self.magnification_factor == factor:
            return
        self.magnification_factor = factor
        self.viewport().update()

    def set_lens_radius(self, radius: int):
        try:
            r = int(radius)
        except Exception:
            return
        if r < 60:
            r = 60
        if r > 360:
            r = 360
        if int(getattr(self, "lens_radius", 150) or 150) == int(r):
            return
        self.lens_radius = int(r)
        self.viewport().update()

    def toggle_magnifier(self, enabled):
        self.magnifier_enabled = enabled
        if enabled:
            # 禁用拖拽模式
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            
            # 隐藏鼠标
            self.viewport().setCursor(Qt.CursorShape.BlankCursor)
        else:
            # 恢复拖拽
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            # 恢复鼠标 (unsetCursor 会让它回退到 DragMode 的默认光标)
            self.viewport().unsetCursor()
            self._sync_pos = None
        
        self.viewport().update()
        
        if not self._external_sync:
            self.magnifier_toggled.emit(enabled)

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.magnifier_enabled:
            # 刚进入时，立即发送当前位置，确保同步视图更新
            self.magnifier_moved.emit(self.mapFromGlobal(self.cursor().pos()))
            self.viewport().update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        # 鼠标离开时清除同步位置，并通知同步视图隐藏
        self._sync_pos = None
        if self.magnifier_enabled:
            # 发送一个视口外的坐标，使另一侧隐藏放大镜
            self.magnifier_moved.emit(QPoint(-9999, -9999))
            self.viewport().update()

    def mouseMoveEvent(self, event):
        if self.drawing_mode:
            if event.buttons() & Qt.MouseButton.LeftButton:
                if self._drawing_start_pos is not None and self._temp_rect_item:
                    current_pos = self.mapToScene(event.pos())
                    rect = QRectF(self._drawing_start_pos, current_pos).normalized()
                    self._temp_rect_item.setRect(rect)
            return

        super().mouseMoveEvent(event)
        
        # 清除同步位置，确保主动视图使用真实鼠标位置
        self._sync_pos = None
        
        if self.magnifier_enabled:
            self.magnifier_moved.emit(event.pos())
            self.viewport().update()
            
            # 强制隐藏鼠标（防止拖拽时出现手型光标）
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.viewport().setCursor(Qt.CursorShape.BlankCursor)

    def wheelEvent(self, event):
        sm = ShortcutManager.instance()
        try:
            if self.magnifier_enabled:
                if sm.is_match("ImageDetail.MagnifierLensBiggerWheel", event):
                    self.lens_radius = int(min(360, int(getattr(self, "lens_radius", 150) or 150) + 12))
                    self.lens_radius_changed.emit(int(self.lens_radius))
                    self.viewport().update()
                    event.accept()
                    return
                if sm.is_match("ImageDetail.MagnifierLensSmallerWheel", event):
                    self.lens_radius = int(max(60, int(getattr(self, "lens_radius", 150) or 150) - 12))
                    self.lens_radius_changed.emit(int(self.lens_radius))
                    self.viewport().update()
                    event.accept()
                    return
                if sm.is_match("ImageDetail.MagnifierZoomInWheel", event):
                    self.magnification_factor = float(min(8.0, float(self.magnification_factor) + 0.1))
                    self.magnification_changed.emit(self.magnification_factor)
                    self.viewport().update()
                    event.accept()
                    return
                if sm.is_match("ImageDetail.MagnifierZoomOutWheel", event):
                    self.magnification_factor = float(max(1.1, float(self.magnification_factor) - 0.1))
                    self.magnification_changed.emit(self.magnification_factor)
                    self.viewport().update()
                    event.accept()
                    return
        except Exception:
            pass
        
        # 优先处理快捷键定义的缩放 (支持键盘+滚轮组合)
        def on_zoom_in():
            if self.magnifier_enabled:
                self.magnification_factor += 0.1
                self.magnification_changed.emit(self.magnification_factor)
                self.viewport().update()
            else:
                self.zoom_in_requested.emit()

        if sm.check_detail_zoom_in(event, on_zoom_in):
            event.accept()
            return
            
        def on_zoom_out():
            if self.magnifier_enabled:
                self.magnification_factor = max(1.1, self.magnification_factor - 0.1)
                self.magnification_changed.emit(self.magnification_factor)
                self.viewport().update()
            else:
                self.zoom_out_requested.emit()

        if sm.check_detail_zoom_out(event, on_zoom_out):
            event.accept()
            return

        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if self.drawing_mode:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drawing_start_pos = self.mapToScene(event.pos())
                if not self._temp_rect_item:
                    self._temp_rect_item = QGraphicsRectItem()
                    pen = QPen(ColorManager.instance().qcolor("border.subject_rect", default="#f50f0f"))
                    pen.setWidth(2)
                    self._temp_rect_item.setPen(pen)
                    self._temp_rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    self.scene().addItem(self._temp_rect_item)
                
                self._temp_rect_item.setRect(QRectF(self._drawing_start_pos, self._drawing_start_pos))
                event.accept()
                return
            elif event.button() == Qt.MouseButton.RightButton:
                if self._temp_rect_item:
                    rect = self._temp_rect_item.rect().normalized()
                    if rect.width() > 0 and rect.height() > 0:
                        self.manual_rect_saved.emit(rect)
                self.set_drawing_mode(False)
                event.accept()
                return
            event.accept()
            return

        modifiers = QApplication.keyboardModifiers()
        if event.button() == Qt.MouseButton.RightButton and (modifiers & Qt.KeyboardModifier.ControlModifier):
            self.ctrl_right_detect_requested.emit()
            event.accept()
            return

        if self.magnifier_enabled:
            if event.button() == Qt.MouseButton.RightButton:
                self.toggle_magnifier(False)
                return
            
            # 禁用拖拽，吞掉左键事件
            if event.button() == Qt.MouseButton.LeftButton:
                event.accept()
                return

            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        
        if self.magnifier_enabled:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # 获取鼠标在 viewport 中的位置
            if hasattr(self, '_sync_pos') and self._sync_pos:
                mouse_pos = self._sync_pos
            else:
                mouse_pos = self.mapFromGlobal(self.cursor().pos())
            
            # 如果鼠标在 viewport 外，不绘制
            if not self.viewport().rect().contains(mouse_pos):
                return

            # 1. 绘制放大镜圆形边框和背景
            path = QPainterPath()
            path.addEllipse(QPointF(mouse_pos), self.lens_radius, self.lens_radius)
            
            painter.setClipPath(path)
            
            # 2. 绘制放大的图像内容
            # 计算需要从 scene 中抓取的区域
            # 放大镜显示区域大小 = 2 * r
            # 抓取区域大小 = (2 * r) / magnification_factor
            
            # 获取当前视图的缩放比例，修正 source_size
            # 使得放大倍率相对于当前视图显示大小，而不是 Scene 原始大小
            view_scale = self.transform().m11()
            
            lens_diameter = self.lens_radius * 2
            
            # source_size 是在 Scene 坐标系下的大小
            # 目标: 放大镜内看到的图像比当前视图看到的图像大 magnification_factor 倍
            # source_size = (lens_diameter / magnification_factor) / view_scale
            if view_scale != 0:
                source_size = (lens_diameter / self.magnification_factor) / view_scale
            else:
                source_size = lens_diameter / self.magnification_factor
            # 鼠标对应的 scene 坐标
            scene_pos = self.mapToScene(mouse_pos)
            
            source_rect = float(scene_pos.x() - source_size / 2), float(scene_pos.y() - source_size / 2), float(source_size), float(source_size)
            
            # 目标区域（viewport 坐标）
            target_rect = float(mouse_pos.x() - self.lens_radius), float(mouse_pos.y() - self.lens_radius), float(lens_diameter), float(lens_diameter)
            
            # 填充背景（防止边缘透明）
            painter.fillPath(path, Qt.GlobalColor.black)
            
            # 渲染 Scene 的对应部分到 viewport
            # 注意：render 需要 QRectF
            from PyQt6.QtCore import QRectF
            self.scene().render(painter, QRectF(*target_rect), QRectF(*source_rect))
            
            # 3. 绘制边框
            painter.setClipping(False)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawEllipse(mouse_pos, self.lens_radius, self.lens_radius)
            
            # 绘制倍率文字
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(mouse_pos.x() - 20, mouse_pos.y() + self.lens_radius + 20, f"x{self.magnification_factor:.1f}")

# 增加对 RAW 原图加载的支持
def load_full_image_wrapper(file_path, max_edge: int = 2560):
    """
    加载完整图片，如果是 RAW 则进行解析
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        p_key = str(file_path or "")
    except Exception:
        p_key = ""
    
    try:
        if ext.upper() in raw_exts:
            # 1. 尝试使用 rawpy 解析原图 (高质量)
            # rgb = load_raw_full(file_path)
            rgb = None
            # 2. 如果解析失败，尝试加载嵌入的预览图 (兜底)
            if rgb is None:
                img = load_image(file_path) # 返回 BGR numpy array
                if img is not None:
                    # BGR -> RGB
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    height, width, channel = img.shape
                    if p_key:
                        _ORIG_IMAGE_SIZE_BY_PATH[p_key] = (int(width), int(height))
                    try:
                        max_edge = int(max_edge) if int(max_edge or 0) > 0 else 2560
                        long_edge = max(int(width), int(height))
                        if long_edge > max_edge:
                            ratio = float(max_edge) / float(long_edge)
                            nw = max(1, int(round(float(width) * ratio)))
                            nh = max(1, int(round(float(height) * ratio)))
                            img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
                            height, width, channel = img.shape
                    except Exception:
                        pass
                    bytes_per_line = 3 * width
                    qimg = QImage(img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
                    return qimg
                else:
                    try:
                        LogManager.instance().warning("[ImageLoader] Failed to load RAW preview as well.")
                    except Exception:
                        pass
                    return None

            if rgb is not None:
                # 确保内存连续，避免 QImage 显示错乱
                rgb = np.ascontiguousarray(rgb)
                
                # numpy array (H, W, 3) RGB -> QImage
                height, width, channel = rgb.shape
                if p_key:
                    _ORIG_IMAGE_SIZE_BY_PATH[p_key] = (int(width), int(height))
                try:
                    max_edge = int(max_edge) if int(max_edge or 0) > 0 else 2560
                    long_edge = max(int(width), int(height))
                    if long_edge > max_edge:
                        ratio = float(max_edge) / float(long_edge)
                        nw = max(1, int(round(float(width) * ratio)))
                        nh = max(1, int(round(float(height) * ratio)))
                        rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
                        height, width, channel = rgb.shape
                except Exception:
                    pass
                bytes_per_line = 3 * width
                # 必须拷贝数据，因为 numpy array 释放后 QImage 会崩溃
                qimg = QImage(rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
                return qimg
        else:
            try:
                with suppress_stderr_fd():
                    reader = QImageReader(file_path)
                    reader.setAutoTransform(True)
                ow = oh = 0
                try:
                    with suppress_stderr_fd():
                        sz = reader.size()
                    if sz is not None and sz.isValid():
                        ow = int(sz.width())
                        oh = int(sz.height())
                except Exception:
                    ow = oh = 0
                if p_key and ow > 0 and oh > 0:
                    _ORIG_IMAGE_SIZE_BY_PATH[p_key] = (int(ow), int(oh))
                max_edge = int(max_edge) if int(max_edge or 0) > 0 else 2560
                if ow > 0 and oh > 0:
                    long_edge = max(ow, oh)
                    if long_edge > max_edge:
                        if ow >= oh:
                            tw = int(max_edge)
                            th = max(1, int(round(float(oh) * (float(tw) / float(max(1, ow))))))
                        else:
                            th = int(max_edge)
                            tw = max(1, int(round(float(ow) * (float(th) / float(max(1, oh))))))
                        reader.setScaledSize(QSize(int(tw), int(th)))
                with suppress_stderr_fd():
                    qimg = reader.read()
                if qimg is not None and not qimg.isNull():
                    return qimg
            except Exception:
                pass

            img_array = np.fromfile(file_path, dtype=np.uint8)
            with suppress_stderr_fd():
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is None:
                return None
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            height, width, channel = img.shape
            if p_key:
                _ORIG_IMAGE_SIZE_BY_PATH[p_key] = (int(width), int(height))
            try:
                max_edge = int(max_edge) if int(max_edge or 0) > 0 else 2560
                long_edge = max(int(width), int(height))
                if long_edge > max_edge:
                    ratio = float(max_edge) / float(long_edge)
                    nw = max(1, int(round(float(width) * ratio)))
                    nh = max(1, int(round(float(height) * ratio)))
                    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
                    height, width, channel = img.shape
            except Exception:
                pass
            bytes_per_line = 3 * width
            qimg = QImage(img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
            return qimg
    except Exception as e:
        try:
            LogManager.instance().warning(f"加载完整图片失败 {file_path}: {e}")
        except Exception:
            pass
        return None

class ImageLoaderThread(QThread):
    image_loaded = pyqtSignal(QImage, str) # image, path

    def __init__(self, path, max_edge: int = 2560):
        super().__init__()
        self.path = path
        self.max_edge = int(max_edge) if int(max_edge or 0) > 0 else 2560

    def run(self):
        try:
            img = load_full_image_wrapper(self.path, max_edge=self.max_edge)
            if img:
                self.image_loaded.emit(img, self.path)
        except Exception as e:
            try:
                LogManager.instance().warning(f"图片加载线程异常: {e}")
            except Exception:
                pass

class ImageInfoOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # 背景容器，半透明圆角
        self.container = QWidget()
        cm = ColorManager.instance()
        overlay_bg = cm.to_qss_color("image_detail.overlay.background", default="#00000064")
        self.container.setStyleSheet(f"""
            QWidget {{
                background-color: {overlay_bg};
                border-radius: 8px;
            }}
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(10, 8, 10, 8)
        container_layout.setSpacing(2)
        
        # 文件名
        self.lbl_filename = QLabel()
        self.lbl_filename.setStyleSheet("color: white; font-weight: bold; font-size: 14px; background: transparent;")
        container_layout.addWidget(self.lbl_filename)
        
        # 详细信息 (ISO, 光圈等)
        self.lbl_details = QLabel()
        self.lbl_details.setStyleSheet("color: white; font-size: 12px; background: transparent;")
        self.lbl_details.setWordWrap(True)
        container_layout.addWidget(self.lbl_details)
        
        layout.addWidget(self.container)
        
        try:
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass

    def set_data(self, filename, details_text, extra_text=None):
        self.lbl_filename.setText(filename)
        self.lbl_details.setText(details_text)
        
        self.container.show()
        self.adjustSize()
        self.show()

class ImageAllInfoOverlay(QWidget):
    collapse_requested = pyqtSignal()
    html_loaded = pyqtSignal()  # HTML 加载完成信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._html = ""
        try:
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        self._setup_ui()
        try:
            ColorManager.instance().register_listener(self._apply_theme_styles)
        except Exception:
            pass
        self._apply_theme_styles()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        self.container = QWidget()
        try:
            self.container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(6)

        header = QWidget()
        try:
            header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        self.btn_collapse = QToolButton()
        self.btn_collapse.setIcon(qta.icon("mdi6.chevron-up", color="white"))
        self.btn_collapse.setIconSize(QSize(16, 16))
        self.btn_collapse.setFixedSize(24, 24)
        try:
            self.btn_collapse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        self.btn_collapse.setStyleSheet(
            "QToolButton { background: transparent; border: none; padding: 0px; margin: 0px; outline: none; "
            "min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }"
            "QToolButton:focus { outline: none; }"
        )
        self.btn_collapse.clicked.connect(self.collapse_requested.emit)
        header_layout.addWidget(self.btn_collapse)
        header_layout.addStretch(1)
        container_layout.addWidget(header)

        # 创建滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 隐藏滚动条但保持滚动功能
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self.scroll_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        
        # 创建内容容器
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        
        # 创建 QTextBrowser
        self.content = QTextBrowser()
        self.content.setOpenExternalLinks(False)
        self.content.setFrameShape(QFrame.Shape.NoFrame)
        self.content.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            self.content.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        self.content.setStyleSheet(
            "color: #FFFFFF; font-size: 12px; background: transparent; border: none; outline: none;"
            "QTextBrowser:focus { border: none; outline: none; }"
        )
        
        self.content_layout.addWidget(self.content)
        self.scroll_area.setWidget(self.content_container)
        container_layout.addWidget(self.scroll_area, 1)

        layout.addWidget(self.container)

    def set_html(self, html: str):
        try:
            t = str(html or "").strip()
        except Exception:
            t = ""
        self._html = t
        if not t:
            try:
                self.content.setHtml("")
            except Exception:
                self.content.setText("")
            self.hide()
            return
        
        # 保存当前滚动位置（使用 QScrollArea 的滚动条）
        scrollbar = self.scroll_area.verticalScrollBar()
        old_value = scrollbar.value() if scrollbar else 0
        old_max = scrollbar.maximum() if scrollbar else 0
        
        try:
            self.content.setHtml(t)
        except Exception:
            self.content.setText(t)
        
        self.show()
        self.adjustSize()
        
        # 发射信号通知 HTML 加载完成
        self.html_loaded.emit()

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        overlay_bg = cm.to_qss_color("image_detail.overlay.background", default="#00000064")
        overlay_border = cm.to_qss_color("image_detail.overlay.border", default="#FFFFFF33")
        overlay_hover = cm.to_qss_color("image_detail.overlay.hover_background", default="#FFFFFF1E")
        text_color = cm.get("theme.text.light")
        self.container.setStyleSheet(
            f"QWidget {{ background-color: {overlay_bg}; border-radius: 8px; border: 1px solid {overlay_border}; }}"
        )
        self.btn_collapse.setStyleSheet(
            f"QToolButton {{ background-color: transparent; border: 1px solid {overlay_border}; border-radius: 5px; "
            f"padding: 0px; margin: 0px; outline: none; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; }}"
            f"QToolButton:hover {{ background-color: {overlay_hover}; }}"
            f"QToolButton:focus {{ outline: none; }}"
        )
        try:
            self.btn_collapse.setIconSize(QSize(16, 16))
            self.btn_collapse.setFixedSize(24, 24)
        except Exception:
            pass
        try:
            self.btn_collapse.setIcon(qta.icon("mdi6.chevron-up", color=text_color))
        except Exception:
            pass
        self.content.setStyleSheet(
            f"QTextBrowser {{ color: {text_color}; font-size: 12px; background: transparent; border: none; outline: none; }}"
            f"QTextBrowser:focus {{ border: none; outline: none; }}"
            f"p {{ color: {text_color}; }}"
            f"div {{ color: {text_color}; }}"
            f"span {{ color: {text_color}; }}"
            f"b {{ color: {text_color}; }}"
            f"body {{ color: {text_color}; }}"
        )

class ImageActionOverlay(QWidget):
    action_triggered = pyqtSignal(str, str, object) # path, action_type ('fav', 'rating', 'label'), value

    LABEL_COLORS = {
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 背景容器，半透明圆角
        self.container = QWidget()
        cm = ColorManager.instance()
        overlay_bg = cm.to_qss_color("image_detail.overlay.background", default="#00000064")
        overlay_hover_bg = cm.to_qss_color("image_detail.overlay.hover_background", default="#FFFFFF1E")
        self.container.setStyleSheet(f"""
            QWidget {{
                background-color: {overlay_bg};
                border-radius: 8px;
            }}
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        
        # 收藏按钮 (放大)
        self.btn_fav = QPushButton()
        self.btn_fav.setFixedSize(48, 48) # 32 -> 48
        self.btn_fav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fav.setIconSize(QSize(32, 32)) # Icon size also increased
        self.btn_fav.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {overlay_hover_bg};
                border-radius: 24px;
            }}
        """)
        self.btn_fav.clicked.connect(self.on_fav_clicked)
        container_layout.addWidget(self.btn_fav, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 色标按钮
        self.btn_label = QPushButton()
        self.btn_label.setFixedSize(48, 48)
        self.btn_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_label.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 24px;
            }}
            QPushButton:hover {{
                background-color: {overlay_hover_bg};
            }}
            QPushButton::menu-indicator {{
                image: none;
            }}
        """)
        self.btn_label.clicked.connect(self.on_label_clicked)
        self.update_label_icon(None) # 初始化为灰色
        container_layout.addWidget(self.btn_label, 0, Qt.AlignmentFlag.AlignCenter)

        # 评分组件 (垂直, 放大)
        # size=20->32, font_size=16->24
        self.rating_widget = StarRatingWidget(size=32, font_size=24, orientation='vertical')
        self.rating_widget.ratingChanged.connect(self.on_rating_changed)
        container_layout.addWidget(self.rating_widget, 0, Qt.AlignmentFlag.AlignCenter)
        
        layout.addWidget(self.container)

    def set_data(self, path, is_fav, rating, label=None):
        self.path = path
        
        # 更新收藏图标
        if is_fav:
            self.btn_fav.setIcon(qta.icon('mdi6.heart', color='red'))
        else:
            self.btn_fav.setIcon(qta.icon('mdi6.heart-outline', color='white'))
            
        # 更新色标
        self.update_label_icon(label)

        # 更新评分
        self.rating_widget.blockSignals(True)
        self.rating_widget.set_rating(rating, emit_signal=False)
        self.rating_widget.blockSignals(False)
        
        self.adjustSize()
        self.raise_()
        self.show()

    def on_fav_clicked(self):
        if self.path:
            # 切换状态
            is_currently_fav = self.btn_fav.icon().name() == 'mdi6.heart' # 简单判断，或者存状态
            # 实际上我们只负责发信号，状态更新由外部回写或 set_data 控制
            # 但为了即时反馈，我们可以先发信号
            self.action_triggered.emit(self.path, 'fav', None)

    def on_rating_changed(self, value):
        if self.path:
            self.action_triggered.emit(self.path, 'rating', value)

    def update_label_icon(self, label):
        """更新色标按钮图标"""
        size = 26
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
             painter.setPen(QColor('#D0D0D0'))
             painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
             painter.drawEllipse(0, 0, size-1, size-1)

        painter.end()
        
        self.btn_label.setIcon(QIcon(pixmap))
        self.btn_label.setIconSize(QSize(size, size))

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
            QMenu::separator {{
                height: 1px;
                background-color: {menu_border};
                margin: 2px 4px;
            }}
        """)
        
        # 1. Clear action
        clear_action = menu.addAction("无色标")
        clear_action.setIcon(qta.icon('mdi.circle-outline', color='#999'))
        clear_action.triggered.connect(lambda: self.action_triggered.emit(self.path, 'label', "")) 
        
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
            color_hex = self.LABEL_COLORS.get(en_name, '#000000')
            
            # Use qtawesome for menu icons
            if en_name == 'White':
                 action.setIcon(qta.icon('mdi.circle', color=color_hex, color_off='#ccc'))
            else:
                 action.setIcon(qta.icon('mdi.circle', color=color_hex))
                 
            action.triggered.connect(lambda checked=False, l=en_name: self.action_triggered.emit(self.path, 'label', l))
            
        # 显示在按钮右侧或合适位置
        pos = self.btn_label.mapToGlobal(self.btn_label.rect().bottomRight())
        # 稍微调整位置，使其不遮挡按钮
        pos.setX(pos.x() - self.btn_label.width()) 
        pos.setY(pos.y() + 2)
        menu.exec(pos)

class ImageDetailPanel(QWidget):
    # 信号
    back_requested = pyqtSignal()
    image_changed = pyqtSignal(str) # path
    rating_changed = pyqtSignal(str, int) # path, rating
    favorite_changed = pyqtSignal(str, bool) # path, is_fav
    label_changed = pyqtSignal(str, str) # path, label
    left_image_selected = pyqtSignal(int) # 新增：左侧图片选中信号
    subject_detected = pyqtSignal(str, str, object, object, str, str, object) # side, path, bbox, focus_point, position, err, targets
    import_to_library_requested = pyqtSignal(object)
    stash_toggle_requested = pyqtSignal(str)
    _all_info_html_ready = pyqtSignal(str)  # 后台线程 EXIF 数据准备就绪

    def __init__(self, image_list, current_index=0, parent=None, compare_indices=None, cache_manager=None, show_action_overlay: bool = True, show_import_to_library_button: bool = False, show_stash_controls: bool = False, db_table_name: str = "bird_results", big_cache_context: str = "library"):
        super().__init__(parent)
        try:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception:
            pass
        self.cache_manager = cache_manager or ImageCacheManager.instance()
        self.image_list = image_list
        self.current_index = current_index
        # 初始进入大图模式，默认适应窗口 (zoom_scale=1.0)
        # 不要从设置中读取保存的缩放比例，否则如果上次放很大，这次一进来就是大的，体验不好
        self.zoom_scale = 1.0
        self.rotation_angle = 0
        self.loader_thread = None
        self.thumbnail_widgets = []
        self._subject_rect_item = None
        self._subject_rect_path = None
        self._subject_rect_item_left = None
        self._subject_rect_path_left = None
        self._subject_rect_item_right = None
        self._subject_rect_path_right = None
        self._eye_rect_item = None
        self._eye_rect_path = None
        self._eye_rect_item_left = None
        self._eye_rect_path_left = None
        self._eye_rect_item_right = None
        self._eye_rect_path_right = None
        try:
            sm = getattr(self.cache_manager, "settings_manager", None)
        except Exception:
            sm = None
        if sm is not None:
            try:
                self._subject_rect_display_enabled = bool(sm.get("focus_detect_ui/show_subject_rect", True))
            except Exception:
                self._subject_rect_display_enabled = True
        else:
            self._subject_rect_display_enabled = False
        self._detect_subject_pending = False
        self._detect_subject_target_scene = None
        self._detect_subject_pending_left = False
        self._detect_subject_pending_right = False
        self._detect_subject_target_scene_left = None
        self._detect_subject_target_scene_right = None
        self._detect_subject_image_size_left = None
        self._detect_subject_image_size_right = None
        self.db = BirdLibraryDB()
        self._uuid_cache = {}
        self._exif_orientation_cache = {}
        self._overlay_exif_brief_cache = {}
        self._overlay_exif_brief_pending = set()
        try:
            self._overlay_exif_bridge = _OverlayExifBridge(self)
            self._overlay_exif_bridge.ready.connect(self._on_overlay_exif_brief_ready)
        except Exception:
            self._overlay_exif_bridge = None
        self._is_zoomed_to_bird = False
        self._is_zoomed_to_bird_compare = False
        self._settings_manager = None
        try:
            self._settings_manager = getattr(self.cache_manager, "settings_manager", None)
        except Exception:
            self._settings_manager = None
        if self._settings_manager is None:
            try:
                self._settings_manager = SettingsManager.instance()
            except Exception:
                self._settings_manager = None
        # 已移除从设置中读取 zoom_scale 的逻辑，强制默认 1.0
        self.zoom_scale = 1.0
        self._big_cache_context = str(big_cache_context or "library")
        self.big_image_cache = BigImageCacheManager.instance(self._big_cache_context)
        self._detail_decode_max_edge = 2560
        if self._big_cache_context.strip().lower() == "import":
            try:
                self.big_image_cache.set_max_items_override(10)
                self.big_image_cache.set_max_long_edge_override(1600)
            except Exception:
                pass
            self._detail_decode_max_edge = 1600
        self._pending_load_index = None
        self._neighbors_preload_timer = QTimer(self)
        self._neighbors_preload_timer.setSingleShot(True)
        self._neighbors_preload_timer.timeout.connect(self._preload_big_neighbors_detail)
        self._deferred_load_timer = QTimer(self)
        self._deferred_load_timer.setSingleShot(True)
        self._deferred_load_timer.timeout.connect(self._flush_deferred_big_image_load)
        self._deferred_load_index = None
        self._auto_nav_timer = QTimer(self)
        self._auto_nav_timer.setSingleShot(True)
        self._auto_nav_timer.timeout.connect(self._auto_nav_on_timeout)
        self._auto_nav_active = False
        self._auto_nav_paused = False
        self._auto_nav_direction = 0
        self._auto_nav_base_interval_ms = 800
        self._auto_nav_current_interval_ms = 800
        self._auto_nav_hold_direction = 0
        self._show_action_overlay = bool(show_action_overlay)
        self._show_import_to_library_button = bool(show_import_to_library_button)
        self._show_stash_controls = bool(show_stash_controls)
        if sm is not None:
            try:
                self._focus_point_display_enabled = bool(sm.get("focus_detect_ui/show_focus_point", True))
            except Exception:
                self._focus_point_display_enabled = True
        else:
            self._focus_point_display_enabled = False
        self._db_table_name = str(db_table_name or "bird_results")
        if self._db_table_name not in ("bird_results", "import_cache"):
            self._db_table_name = "bird_results"

        # 对比模式状态
        self.compare_mode = False
        self.view_left = None
        self.view_right = None
        self.scene_left = None
        self.scene_right = None
        self.pixmap_item_left = None
        self.pixmap_item_right = None
        
        # 主容器背景
        cm = ColorManager.instance()
        page_bg = cm.to_qss_color("page.background.primary", default="#000000")
        self.setStyleSheet(f"background-color: {page_bg};")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. 顶部工具栏 (替代原信息栏，包含返回按钮)
        self.init_top_bar()
        
        # 2. 中间图片区域
        self.init_image_view()
        
        # 3. 底部缩略图栏
        self.init_thumbnail_strip()
        
        # 4. 底部工具栏
        self.init_toolbar()
        
        # 加载初始图片
        self.load_current_image()
        
        # 确保缩略图栏选中当前图片
        self.update_thumbnail_selection()

        try:
            if not hasattr(self, "_detail_prev_shortcut") or self._detail_prev_shortcut is None:
                self._detail_prev_shortcut = QShortcut(self)
                self._detail_prev_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self._detail_prev_shortcut.activated.connect(self._on_prev_image_shortcut)
        except Exception:
            self._detail_prev_shortcut = None
        try:
            if not hasattr(self, "_detail_next_shortcut") or self._detail_next_shortcut is None:
                self._detail_next_shortcut = QShortcut(self)
                self._detail_next_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self._detail_next_shortcut.activated.connect(self._on_next_image_shortcut)
        except Exception:
            self._detail_next_shortcut = None
        try:
            if not hasattr(self, "_detail_close_shortcut") or self._detail_close_shortcut is None:
                self._detail_close_shortcut = QShortcut(self)
                self._detail_close_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self._detail_close_shortcut.activated.connect(self.back_requested.emit)
        except Exception:
            self._detail_close_shortcut = None
        try:
            if not hasattr(self, "_detail_toggle_subject_rect_shortcut") or self._detail_toggle_subject_rect_shortcut is None:
                self._detail_toggle_subject_rect_shortcut = QShortcut(self)
                self._detail_toggle_subject_rect_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self._detail_toggle_subject_rect_shortcut.activated.connect(lambda: (self._auto_nav_pause_if_needed(), self.btn_show_subject_rect.toggle()) if hasattr(self, "btn_show_subject_rect") and self.btn_show_subject_rect is not None else None)
        except Exception:
            self._detail_toggle_subject_rect_shortcut = None
        try:
            if not hasattr(self, "_detail_delete_shortcut") or self._detail_delete_shortcut is None:
                self._detail_delete_shortcut = QShortcut(self)
                self._detail_delete_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                self._detail_delete_shortcut.activated.connect(self._on_delete_clicked)
        except Exception:
            self._detail_delete_shortcut = None
        try:
            self._update_detail_shortcut_keys()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_detail_shortcut_keys)
        except Exception:
            pass

        self.subject_detected.connect(self._on_subject_detected)

        # 处理直接进入对比模式
        if compare_indices and len(compare_indices) == 2:
            self.compare_mode = True
            self.saved_left_index = compare_indices[0] # 保存左侧索引以便退出时恢复
            self.center_stack.setCurrentIndex(1)
            
            # 1. 加载左侧图片 (compare_indices[0])
            self.load_left_image(compare_indices[0])
            
            # 2. 设置当前索引为 compare_indices[1]，并重新加载右侧图片
            self.current_index = compare_indices[1]
            self._prefetch_compare_subject_state()
            self.load_current_image() # 这将加载右侧图片
            
            # 3. 更新对比按钮样式
            try:
                self._apply_compare_button_style(active=True)
            except Exception:
                pass
                
            # 提示
            try:
                from ui.utils.notification_manager import NotificationManager
                NotificationManager.instance().show_toast("进入对比模式")
            except Exception:
                pass

    def _apply_toolbar_toggle_button_style(self, btn: QPushButton, active: bool):
        if btn is None:
            return
        cm = ColorManager.instance()
        hover_bg = cm.to_qss_color("image_detail.toolbar.button.hover_background", default="#FFFFFF1E")
        pressed_bg = cm.to_qss_color("image_detail.toolbar.button.pressed_background", default="#FFFFFF32")
        tooltip_text = cm.get("tooltip.text")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_border = cm.get("tooltip.border")
        active_bg = cm.to_qss_color("image_detail.compare_button.active_background", default="#FFFFFF32")
        if bool(active):
            btn.setStyleSheet(f"""
                QPushButton {{ background-color: {active_bg}; border: 1px solid #FFFFFF; border-radius: 4px; }}
                QPushButton:hover {{ background-color: {hover_bg}; }}
                QPushButton:pressed {{ background-color: {pressed_bg}; }}
                QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{ background-color: transparent; border: none; border-radius: 4px; }}
                QPushButton:hover {{ background-color: {hover_bg}; }}
                QPushButton:pressed {{ background-color: {pressed_bg}; }}
                QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
            """)

    def _norm_uuid_cache_key(self, path: str):
        if not path:
            return None
        try:
            return os.path.normcase(os.path.normpath(str(path)))
        except Exception:
            return str(path)

    def _ensure_uuid_for_path(self, path: str):
        if not path:
            return None
        key = self._norm_uuid_cache_key(path)
        if key in self._uuid_cache:
            return self._uuid_cache.get(key)

        uuid_val = None
        try:
            if getattr(self, "_db_table_name", "") != "import_cache":
                record = self.db.get_result_by_path(path, table_name=self._db_table_name)
                if isinstance(record, dict) and record.get("uuid"):
                    uuid_val = str(record.get("uuid") or "").strip()
        except Exception:
            uuid_val = uuid_val
        if uuid_val:
            self._uuid_cache[key] = uuid_val
            return uuid_val

        try:
            uuid_val = ExifHandleWorker.get_instance().read_tag(path, EXIF_TAG.Uuid.value, timeout=3, raise_on_error=True)
        except Exception:
            # 读取失败（如超时），不应假定没有UUID，避免错误覆写
            return None
        
        if uuid_val is not None:
            try:
                uuid_val = str(uuid_val).strip()
            except Exception:
                uuid_val = None

        if not uuid_val:
            uuid_val = get_unique_id()
            try:
                ExifHandleWorker.get_instance().set_metadata(path, {EXIF_TAG.Uuid.value: uuid_val})
            except Exception:
                pass

        self._uuid_cache[key] = uuid_val
        return uuid_val

    def _get_record_for_path(self, path: str):
        if self._db_table_name == "import_cache":
            try:
                return self.db.get_result_by_path(path, table_name="import_cache")
            except Exception:
                return None
        # 首先尝试通过路径直接获取记录（与 info_panel 保持一致）
        try:
            record = self.db.get_result_by_path(path, table_name=self._db_table_name)
            if isinstance(record, dict) and record:
                return record
        except Exception:
            pass
        # 如果路径查找失败，尝试通过 UUID 获取
        uuid_val = self._ensure_uuid_for_path(path)
        if not uuid_val:
            return None
        try:
            return self.db.get_result_by_uuid(uuid_val, table_name=self._db_table_name)
        except Exception:
            return None

    def _prefetch_compare_subject_state(self):
        if not self.compare_mode:
            return
        if not self.image_list:
            return

        left_index = getattr(self, "saved_left_index", None)
        right_index = self.current_index
        left_bbox = False
        left_focus = False
        right_bbox = False
        right_focus = False

        def fill_from_record(idx: Optional[int]):
            if idx is None or idx < 0 or idx >= len(self.image_list):
                return False, False
            info = self.image_list[idx]
            path = info.get("path") or ""
            if not path:
                return False, False
            record = None
            try:
                if self._db_table_name == "import_cache":
                    record = self.db.get_result_by_path(path, table_name="import_cache")
                else:
                    uuid_val = self._ensure_uuid_for_path(path)
                    if uuid_val:
                        info["uuid"] = uuid_val
                        record = self.db.get_result_by_uuid(uuid_val, table_name=self._db_table_name)
            except Exception:
                record = None
            if isinstance(record, dict) and record:
                if "bbox" in record:
                    info["bbox"] = record.get("bbox")
                if "focus_point" in record:
                    info["focus_point"] = record.get("focus_point")
            has_bbox = bool(info.get("bbox"))
            fp = info.get("focus_point")
            has_focus = False
            if isinstance(fp, dict):
                try:
                    has_focus = (str(fp.get("mode") or "").lower() == "global") and (fp.get("x") is not None) and (fp.get("y") is not None)
                except Exception:
                    has_focus = False
            elif isinstance(fp, str):
                try:
                    d = json.loads(fp)
                    if isinstance(d, dict):
                        has_focus = (str(d.get("mode") or "").lower() == "global") and (d.get("x") is not None) and (d.get("y") is not None)
                    elif isinstance(d, list):
                        has_focus = len(d) >= 2
                except Exception:
                    has_focus = False
            elif isinstance(fp, (list, tuple)):
                try:
                    has_focus = len(fp) >= 2
                except Exception:
                    has_focus = False
            return has_bbox, has_focus

        left_bbox, left_focus = fill_from_record(left_index)
        right_bbox, right_focus = fill_from_record(right_index)

        if hasattr(self, "btn_zoom_to_bird"):
            self.btn_zoom_to_bird.setEnabled(left_bbox or right_bbox)
        try:
            if hasattr(self, "btn_show_subject_rect") and self.btn_show_subject_rect is not None:
                self.btn_show_subject_rect.setEnabled(True)
        except Exception:
            pass
        if hasattr(self, "btn_zoom_to_focus"):
            try:
                self.btn_zoom_to_focus.setEnabled(True)
            except Exception:
                pass

    def load_left_image(self, index):
        if index < 0 or index >= len(self.image_list):
            return
            
        path = self.image_list[index]['path']
        try:
            if hasattr(self, "left_loader_thread") and self.left_loader_thread and self.left_loader_thread.isRunning():
                try:
                    self._pending_left_load_index = int(index)
                except Exception:
                    self._pending_left_load_index = None
                return
        except Exception:
            pass
        self.left_loader_thread = _track_loader_thread(ImageLoaderThread(path, max_edge=int(getattr(self, "_detail_decode_max_edge", 2560) or 2560)))
        self.left_loader_thread.image_loaded.connect(self.on_left_image_loaded)
        try:
            self.left_loader_thread.finished.connect(self._on_left_loader_finished)
        except Exception:
            pass
        self.left_loader_thread.start()

    def _on_left_loader_finished(self):
        try:
            self.left_loader_thread = None
        except Exception:
            self.left_loader_thread = None
        pending = getattr(self, "_pending_left_load_index", None)
        try:
            self._pending_left_load_index = None
        except Exception:
            pass
        if pending is None:
            return
        try:
            pending = int(pending)
        except Exception:
            return
        try:
            if bool(getattr(self, "compare_mode", False)):
                self.load_left_image(pending)
        except Exception:
            pass

    def on_left_image_loaded(self, qimg, path):
        pixmap = QPixmap.fromImage(qimg)
        self.pixmap_item_left.setPixmap(pixmap)
        self.pixmap_item_left.setPos(0, 0)
        if self.compare_mode:
            self._clear_subject_rect_side("left")
            self._clear_focus_point_side("left")
        self._fit_view(self.view_left, self.pixmap_item_left)
        try:
            if self.compare_mode:
                QTimer.singleShot(0, self._refresh_subject_rect_overlay)
                QTimer.singleShot(0, self._refresh_focus_point_overlay)
        except Exception:
            pass
        
        # 加载左侧图片的元数据并更新 Overlay
        self._update_overlay_data(path, self.overlay_left, self.info_overlay_left)

    def _format_overlay_details(self, path: str, brief: dict | None) -> str:
        dims = "-"
        try:
            p = str(path or "")
        except Exception:
            p = ""
        try:
            cached_size = _ORIG_IMAGE_SIZE_BY_PATH.get(p) if p else None
        except Exception:
            cached_size = None
        if cached_size and isinstance(cached_size, (tuple, list)) and len(cached_size) >= 2:
            try:
                w = int(cached_size[0])
                h = int(cached_size[1])
                if w > 0 and h > 0:
                    dims = f"{w} x {h}"
            except Exception:
                pass
        if dims == "-":
            try:
                d = (brief or {}).get("dimensions")
                if d is not None and str(d).strip():
                    dims = str(d).strip()
            except Exception:
                pass

        iso_disp = "-"
        aperture_disp = "-"
        shutter_disp = "-"
        focal_disp = "-"
        try:
            v = (brief or {}).get("iso")
            if v not in (None, "", 0):
                iso_disp = str(v)
        except Exception:
            pass
        try:
            v = (brief or {}).get("aperture")
            if v is not None and str(v).strip():
                aperture_disp = str(v).strip()
        except Exception:
            pass
        try:
            v = (brief or {}).get("shutter")
            if v is not None and str(v).strip():
                shutter_disp = str(v).strip()
        except Exception:
            pass
        try:
            v = (brief or {}).get("focal_length")
            if v not in (None, "", 0):
                focal_disp = f"{int(float(v))}"
        except Exception:
            pass

        shutter_suffix = ""
        try:
            if shutter_disp != "-" and not shutter_disp.lower().endswith("s"):
                shutter_suffix = "s"
        except Exception:
            shutter_suffix = ""
        focal_suffix = ""
        try:
            if focal_disp != "-" and not focal_disp.lower().endswith("mm"):
                focal_suffix = "mm"
        except Exception:
            focal_suffix = ""

        return f"尺寸 {dims}\nISO {iso_disp}  |  光圈 {aperture_disp}  |  快门 {shutter_disp}{shutter_suffix}  |  焦距 {focal_disp}{focal_suffix}"

    def _extract_overlay_exif_brief(self, meta: object) -> dict:
        brief = {
            "iso": None,
            "aperture": None,
            "shutter": None,
            "focal_length": None,
            "dimensions": None,
        }
        exif = meta
        if isinstance(exif, list) and exif:
            exif = exif[0]
        if not isinstance(exif, dict):
            return brief

        for key in ["ISO", "PhotographicSensitivity", "EXIF:ISO", "EXIF:PhotographicSensitivity"]:
            try:
                if key in exif and exif[key]:
                    brief["iso"] = int(float(str(exif[key])))
                    break
            except Exception:
                pass

        for key in ["FNumber", "ApertureValue", "EXIF:FNumber", "EXIF:ApertureValue"]:
            try:
                if key in exif and exif[key]:
                    val = float(str(exif[key]))
                    brief["aperture"] = f"f/{val}"
                    break
            except Exception:
                pass

        for key in ["ExposureTime", "ShutterSpeedValue", "EXIF:ExposureTime", "EXIF:ShutterSpeedValue"]:
            try:
                if key in exif and exif[key]:
                    val = str(exif[key]).strip()
                    if "/" in val:
                        brief["shutter"] = val
                    else:
                        try:
                            fval = float(val)
                            if fval < 1:
                                brief["shutter"] = f"1/{int(1 / fval)}"
                            else:
                                brief["shutter"] = str(int(fval))
                        except Exception:
                            brief["shutter"] = val
                    break
            except Exception:
                pass

        for key in ["FocalLength", "EXIF:FocalLength"]:
            try:
                if key in exif and exif[key]:
                    val = str(exif[key]).strip().replace("mm", "").strip()
                    brief["focal_length"] = int(float(val))
                    break
            except Exception:
                pass

        for key in ["ImageSize", "ImageWidth", "ExifImageWidth", "EXIF:ImageSize"]:
            try:
                if key in exif and exif[key]:
                    val = str(exif[key]).strip()
                    if "x" in val.lower():
                        brief["dimensions"] = val.lower().replace("x", " x ")
                    elif key == "ImageWidth":
                        width = val
                        height = exif.get("ImageHeight") or exif.get("ExifImageHeight")
                        if height:
                            brief["dimensions"] = f"{width} x {height}"
                    break
            except Exception:
                pass

        return brief

    def _normalize_overlay_path_key(self, path: str) -> str:
        try:
            p = str(path or "")
        except Exception:
            p = ""
        if not p:
            return ""
        try:
            p = os.path.normpath(p)
        except Exception:
            pass
        if os.name == "nt":
            try:
                p = p.replace("/", "\\")
            except Exception:
                pass
        try:
            p = os.path.normcase(p)
        except Exception:
            pass
        return p

    def _is_effective_overlay_brief(self, brief: object) -> bool:
        if not isinstance(brief, dict):
            return False
        for k in ("iso", "aperture", "shutter", "focal_length", "dimensions"):
            try:
                v = brief.get(k)
            except Exception:
                v = None
            if v not in (None, "", 0, "-"):
                return True
        return False

    def _on_overlay_exif_brief_ready(self, path_key: str, brief_value: dict):
        key = self._normalize_overlay_path_key(path_key)
        if not key:
            return
        try:
            b = brief_value or {}
            if not self._is_effective_overlay_brief(b):
                b = {}
            self._overlay_exif_brief_cache[key] = b
            if len(self._overlay_exif_brief_cache) > 600:
                self._overlay_exif_brief_cache.clear()
        except Exception:
            pass
        try:
            self._overlay_exif_brief_pending.discard(key)
        except Exception:
            pass
        try:
            self._refresh_overlay_data_for_path(key)
        except Exception:
            pass

    def _request_overlay_exif_brief(self, path: str):
        try:
            p_src = str(path or "")
        except Exception:
            p_src = ""
        if not p_src:
            return
        p = self._normalize_overlay_path_key(p_src)
        if not p:
            return
        try:
            if p in self._overlay_exif_brief_cache:
                return
        except Exception:
            pass
        try:
            if p in self._overlay_exif_brief_pending:
                return
        except Exception:
            pass
        self._overlay_exif_brief_pending.add(p)
        def _looks_valid(b: dict) -> bool:
            return self._is_effective_overlay_brief(b)

        def _worker_info_panel():
            brief = {}
            try:
                brief = InfoPanel.get_exif_data_sync(p_src, timeout=5) or {}
            except Exception:
                brief = {}

            if not _looks_valid(brief):
                try:
                    from utils.exif.exif_utils import ExifHandleWorker, READ_PICTURE_METADATA_TAG
                    worker = ExifHandleWorker.get_instance()
                    meta = worker._read_sync(p_src, READ_PICTURE_METADATA_TAG, timeout=5)
                    brief2 = self._extract_overlay_exif_brief(meta)
                    if _looks_valid(brief2):
                        brief = brief2
                except Exception:
                    pass
            if not _looks_valid(brief):
                brief = {}

            try:
                bridge = getattr(self, "_overlay_exif_bridge", None)
                if bridge is not None:
                    bridge.ready.emit(p, brief)
                else:
                    self._on_overlay_exif_brief_ready(p, brief)
            except Exception:
                try:
                    self._on_overlay_exif_brief_ready(p, brief)
                except Exception:
                    pass

        try:
            import threading
            t = threading.Thread(target=_worker_info_panel, daemon=True, name="ImageDetailOverlayExif")
            t.start()
        except Exception as e:
            try:
                self._overlay_exif_brief_pending.discard(p)
            except Exception:
                pass
            try:
                LogManager.instance().warning(f"[ImageDetail] 请求EXIF读取失败 {p}: {e}")
            except Exception:
                pass

    def _refresh_overlay_data_for_path(self, path: str):
        try:
            p0 = str(path or "")
        except Exception:
            p0 = ""
        p = self._normalize_overlay_path_key(p0)
        if not p:
            return
        try:
            if not bool(getattr(self, "compare_mode", False)):
                cur = ""
                try:
                    if self.image_list and 0 <= int(self.current_index) < len(self.image_list):
                        cur = self._normalize_overlay_path_key(str(self.image_list[int(self.current_index)].get("path") or ""))
                except Exception:
                    cur = ""
                if cur and cur == p:
                    try:
                        src_path = str(self.image_list[int(self.current_index)].get("path") or "")
                    except Exception:
                        src_path = p0
                    self._update_overlay_data(src_path, getattr(self, "overlay_main", None), getattr(self, "info_overlay_main", None))
                    try:
                        self._update_main_info_stack_layout()
                    except Exception:
                        pass
                return
        except Exception:
            pass

        try:
            left_path = ""
            try:
                idx = int(getattr(self, "saved_left_index", -1))
            except Exception:
                idx = -1
            if self.image_list and 0 <= idx < len(self.image_list):
                left_path = self._normalize_overlay_path_key(str(self.image_list[idx].get("path") or ""))
            if left_path and left_path == p:
                try:
                    src_path = str(self.image_list[idx].get("path") or "")
                except Exception:
                    src_path = p0
                self._update_overlay_data(src_path, getattr(self, "overlay_left", None), getattr(self, "info_overlay_left", None))
        except Exception:
            pass

        try:
            right_path = ""
            try:
                idx = int(getattr(self, "current_index", -1))
            except Exception:
                idx = -1
            if self.image_list and 0 <= idx < len(self.image_list):
                right_path = self._normalize_overlay_path_key(str(self.image_list[idx].get("path") or ""))
            if right_path and right_path == p:
                try:
                    src_path = str(self.image_list[idx].get("path") or "")
                except Exception:
                    src_path = p0
                self._update_overlay_data(src_path, getattr(self, "overlay_right", None), getattr(self, "info_overlay_right", None))
        except Exception:
            pass

    def _update_overlay_data(self, path, overlay, info_overlay=None):
        if not overlay and not info_overlay:
            return
            
        try:
            is_fav = False
            rating = 0
            label = ''
            
            # 首先尝试从数据库获取基本信息
            try:
                record = self.db.get_result_by_path(path, table_name="bird_results")
                if not record:
                    record = self.db.get_result_by_path(path, table_name="import_cache")
                
                if isinstance(record, dict) and record:
                    is_fav = int(record.get('is_favorite', 0) or 0) == 1
                    rating = int(record.get('rating', 0) or 0)
                    label = record.get('label', '') or ''
            except Exception as e:
                pass
            
            brief = {}
            try:
                key = self._normalize_overlay_path_key(str(path or ""))
                brief = self._overlay_exif_brief_cache.get(key, {}) or {}
            except Exception:
                brief = {}
            try:
                if not self._is_effective_overlay_brief(brief):
                    brief = {}
            except Exception:
                brief = {}
            
            try:
                record_brief = {}
                if isinstance(record, dict) and record:
                    try:
                        v = record.get("iso")
                        if v not in (None, "", 0, "-"):
                            record_brief["iso"] = int(float(str(v)))
                    except Exception:
                        pass
                    try:
                        v = record.get("fnumber")
                        if v not in (None, "", 0, "-"):
                            fv = float(str(v))
                            record_brief["aperture"] = f"f/{fv}"
                    except Exception:
                        try:
                            v = record.get("aperture")
                            if v is not None and str(v).strip() and str(v).strip() != "-":
                                record_brief["aperture"] = str(v).strip()
                        except Exception:
                            pass
                    try:
                        v = record.get("shutter")
                        if v is not None and str(v).strip() and str(v).strip() != "-":
                            sv = str(v).strip()
                            if "/" in sv:
                                record_brief["shutter"] = sv
                            else:
                                try:
                                    fsv = float(sv)
                                    if fsv < 1:
                                        record_brief["shutter"] = f"1/{int(1 / fsv)}"
                                    else:
                                        record_brief["shutter"] = str(int(fsv))
                                except Exception:
                                    record_brief["shutter"] = sv
                    except Exception:
                        pass
                    try:
                        v = record.get("focal_length")
                        if v not in (None, "", 0, "-"):
                            record_brief["focal_length"] = int(float(str(v).replace("mm", "").strip()))
                    except Exception:
                        pass
                if record_brief:
                    if not isinstance(brief, dict) or not brief:
                        brief = dict(record_brief)
                    else:
                        for _k, _v in record_brief.items():
                            try:
                                curv = brief.get(_k)
                            except Exception:
                                curv = None
                            if curv in (None, "", 0, "-"):
                                brief[_k] = _v
            except Exception:
                pass
            if not brief:
                try:
                    self._request_overlay_exif_brief(str(path or ""))
                except Exception:
                    pass
                
            # 更新操作浮层 (Action Overlay)
            if overlay:
                overlay.set_data(path, is_fav, rating, label)
                # 手动触发一次位置更新
                if overlay.parentWidget():
                    self._update_overlay_pos(overlay.parentWidget(), overlay, is_info=False)
            
            # 更新信息浮层 (Info Overlay)
            if info_overlay:
                details = self._format_overlay_details(str(path or ""), brief)
                filename = os.path.basename(path)
                
                try:
                    info_overlay.set_data(filename, details, None)
                except TypeError:
                    info_overlay.set_data(filename, details)
                
                # 确保信息浮层及其父控件可见
                try:
                    info_overlay.show()
                    info_overlay.raise_()
                    if info_overlay.parentWidget():
                        info_overlay.parentWidget().show()
                        info_overlay.parentWidget().raise_()
                except Exception as e:
                    pass
                try:
                    if info_overlay is not getattr(self, "info_overlay_main", None) and info_overlay.parentWidget():
                        self._update_overlay_pos(info_overlay.parentWidget(), info_overlay, is_info=True)
                except Exception:
                    pass
                try:
                    if info_overlay is getattr(self, "info_overlay_main", None):
                        self._update_main_info_stack_layout()
                except Exception as e:
                    pass

            try:
                if not bool(getattr(self, "compare_mode", False)) and info_overlay is getattr(self, "info_overlay_main", None):
                    all_overlay = getattr(self, "all_info_overlay_main", None)
                    if all_overlay is not None:
                        mirror = getattr(self, "_all_info_mirror_panel", None)
                        if mirror is None:
                            try:
                                show_ext = bool(getattr(self, "_db_table_name", "bird_results") != "import_cache")
                                mirror = InfoPanel(show_extended_info=show_ext)
                                mirror.hide()
                                self._all_info_mirror_panel = mirror
                            except Exception:
                                mirror = None
                        if mirror is not None:
                            mirror.update_info(path, context=None)
                            
                            # 启动后台线程获取 EXIF 信息并更新浮层
                            def _load_exif_and_update():
                                try:
                                    from ui.panels.info_panel import InfoPanel
                                    exif_data = InfoPanel.get_exif_data_sync(path, timeout=3)
                                except Exception:
                                    exif_data = {}
                                
                                def _esc(s: object) -> str:
                                    try:
                                        t = str(s if s is not None else "").strip()
                                    except Exception:
                                        t = ""
                                    return (
                                        t.replace("&", "&amp;")
                                        .replace("<", "&lt;")
                                        .replace(">", "&gt;")
                                        .replace('"', "&quot;")
                                    )
                                
                                def _get_exif_direct(key, default="-"):
                                    if key in exif_data and exif_data[key] is not None:
                                        v = str(exif_data[key]).strip()
                                        if v and v != "-" and v != "None":
                                            return v
                                    return default
                                
                                parts = []
                                try:
                                    tree = getattr(mirror, "info_tree", None)
                                    top_n = int(tree.topLevelItemCount()) if tree is not None else 0
                                except Exception:
                                    tree = None
                                    top_n = 0
                                for i0 in range(top_n):
                                    try:
                                        g = tree.topLevelItem(int(i0))
                                    except Exception:
                                        continue
                                    try:
                                        gt = str(g.text(0) or "").strip()
                                    except Exception:
                                        gt = ""
                                    if gt.startswith("+ ") or gt.startswith("- "):
                                        gt = gt[2:].strip()
                                    if gt:
                                        parts.append(f"<div style='margin-top:6px;'><b>{_esc(gt)}</b></div>")
                                    try:
                                        child_n = int(g.childCount())
                                    except Exception:
                                        child_n = 0
                                    cm = ColorManager.instance()
                                    text_light = cm.get("theme.text.light")
                                    try:
                                        qc_text = QColor(str(text_light or ""))
                                    except Exception:
                                        qc_text = QColor("#FFFFFF")
                                    if not qc_text.isValid():
                                        qc_text = QColor("#FFFFFF")
                                    label_color = f"rgba({qc_text.red()}, {qc_text.green()}, {qc_text.blue()}, 0.7)"
                                    value_color = qc_text.name()
                                    for j0 in range(child_n):
                                        try:
                                            it = g.child(int(j0))
                                        except Exception:
                                            continue
                                        try:
                                            k = str(it.text(0) or "").strip()
                                        except Exception:
                                            k = ""
                                        try:
                                            v = str(it.text(1) or "").strip()
                                        except Exception:
                                            v = ""
                                        if not k:
                                            continue
                                        
                                        # 如果是 EXIF 相关字段，使用同步获取的数据
                                        k_stripped = k.strip()
                                        if k_stripped == "ISO":
                                            v = _get_exif_direct("iso", v)
                                        elif k_stripped == "光圈":
                                            v = _get_exif_direct("aperture", v)
                                        elif k_stripped == "快门":
                                            v = _get_exif_direct("shutter", v)
                                        elif k_stripped == "焦距":
                                            v = _get_exif_direct("focal_length", v)
                                        elif k_stripped == "尺寸":
                                            v = _get_exif_direct("dimensions", v)
                                        elif k_stripped == "相机":
                                            v = _get_exif_direct("model", v)
                                        elif k_stripped == "镜头":
                                            v = _get_exif_direct("lens", v)
                                        
                                        parts.append(f"<div><span style='color:{label_color};'>{_esc(k)}</span>：<span style='color:{value_color};'>{_esc(v)}</span></div>")

                                html = "<div style='line-height: 1.45;'>" + "".join(parts) + "</div>" if parts else ""
                                
                                # 发射信号，让主线程更新 UI
                                try:
                                    self._all_info_html_ready.emit(html)
                                except Exception:
                                    pass
                            
                            # 连接信号（只连接一次）
                            try:
                                self._all_info_html_ready.disconnect()
                            except Exception:
                                pass
                            self._all_info_html_ready.connect(lambda html: all_overlay.set_html(html))
                            
                            # 启动后台线程
                            import threading
                            thread = threading.Thread(target=_load_exif_and_update, daemon=True)
                            thread.start()
                            
                            # 先显示基本信息（不含 EXIF）
                            def _esc(s: object) -> str:
                                try:
                                    t = str(s if s is not None else "").strip()
                                except Exception:
                                    t = ""
                                return (
                                    t.replace("&", "&amp;")
                                    .replace("<", "&lt;")
                                    .replace(">", "&gt;")
                                    .replace('"', "&quot;")
                                )
                            
                            parts = []
                            try:
                                tree = getattr(mirror, "info_tree", None)
                                top_n = int(tree.topLevelItemCount()) if tree is not None else 0
                            except Exception:
                                tree = None
                                top_n = 0
                            for i0 in range(top_n):
                                try:
                                    g = tree.topLevelItem(int(i0))
                                except Exception:
                                    continue
                                try:
                                    gt = str(g.text(0) or "").strip()
                                except Exception:
                                    gt = ""
                                if gt.startswith("+ ") or gt.startswith("- "):
                                    gt = gt[2:].strip()
                                if gt:
                                    parts.append(f"<div style='margin-top:6px;'><b>{_esc(gt)}</b></div>")
                                try:
                                    child_n = int(g.childCount())
                                except Exception:
                                    child_n = 0
                                cm = ColorManager.instance()
                                text_light = cm.get("theme.text.light")
                                try:
                                    qc_text = QColor(str(text_light or ""))
                                except Exception:
                                    qc_text = QColor("#FFFFFF")
                                if not qc_text.isValid():
                                    qc_text = QColor("#FFFFFF")
                                label_color = f"rgba({qc_text.red()}, {qc_text.green()}, {qc_text.blue()}, 0.7)"
                                value_color = qc_text.name()
                                for j0 in range(child_n):
                                    try:
                                        it = g.child(int(j0))
                                    except Exception:
                                        continue
                                    try:
                                        k = str(it.text(0) or "").strip()
                                    except Exception:
                                        k = ""
                                    try:
                                        v = str(it.text(1) or "").strip()
                                    except Exception:
                                        v = ""
                                    if not k:
                                        continue
                                    parts.append(f"<div><span style='color:{label_color};'>{_esc(k)}</span>：<span style='color:{value_color};'>{_esc(v)}</span></div>")

                            html = "<div style='line-height: 1.45;'>" + "".join(parts) + "</div>" if parts else ""
                            all_overlay.set_html(html)

                        try:
                            if bool(getattr(self, "_all_info_collapsed", False)):
                                self._set_all_info_collapsed(True, persist=False)
                            else:
                                self._set_all_info_collapsed(False, persist=False)
                        except Exception:
                            pass
                        self._update_main_info_stack_layout()
                        QTimer.singleShot(0, self._update_main_info_stack_layout)
            except Exception:
                pass
        except Exception as e:
            try:
                LogManager.instance().warning(f"更新叠加信息失败 {path}: {e}")
            except Exception:
                pass

    def on_overlay_action(self, path, action_type, value):
        """处理 Overlay 的操作信号"""
        if action_type == 'fav':
            self.toggle_favorite(target_path=path)
        elif action_type == 'rating':
            self.set_rating(value, target_path=path)
        elif action_type == 'label':
            self.label_changed.emit(path, value)
            # Optimistic UI update
            if hasattr(self, 'overlay_main') and self.overlay_main and self.overlay_main.path == path:
                 self.overlay_main.update_label_icon(value)
            if hasattr(self, 'overlay_left') and self.overlay_left and self.overlay_left.path == path:
                 self.overlay_left.update_label_icon(value)
            if hasattr(self, 'overlay_right') and self.overlay_right and self.overlay_right.path == path:
                 self.overlay_right.update_label_icon(value)

    def init_top_bar(self):
        """初始化顶部栏（返回按钮 + 简要信息）"""
        self.top_bar = QWidget()
        self.top_bar.setFixedHeight(40)
        cm = ColorManager.instance()
        page_bg = cm.to_qss_color("page.background.primary", default="#000000")
        self.top_bar.setStyleSheet(f"background-color: {page_bg};")
        layout = QHBoxLayout(self.top_bar)
        layout.setContentsMargins(10, 0, 10, 0)
        
        # 返回按钮
        self.btn_back = QPushButton("返回图库")
        self.btn_back.setIcon(qta.icon('mdi6.arrow-left', color='white'))
        # 返回到图库按钮的边框和文字都是白色
        cm = ColorManager.instance()
        back_hover_bg = cm.to_qss_color("image_detail.back_button.hover_background", default="#FFFFFF28")
        self.btn_back.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid #FFFFFF;
                border-radius: 4px;
                padding: 4px 10px;
                color: #FFFFFF;
            }}
            QPushButton:hover {{
                background-color: {back_hover_bg};
                color: #FFFFFF;
            }}
        """)
        self.btn_back.clicked.connect(self.back_requested.emit)
        layout.addWidget(self.btn_back)
        
        layout.addStretch()
        
        # 文件名显示 (已删除)
        # self.lbl_filename = QLabel("")
        # self.lbl_filename.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
        # layout.addWidget(self.lbl_filename)
        
        # layout.addSpacing(20)
        
        # 简要信息 (已删除)
        # self.lbl_info = QLabel("")
        # self.lbl_info.setStyleSheet("font-size: 12px; color: white;")
        # layout.addWidget(self.lbl_info)
        
        layout.addStretch()
        
        dummy = QWidget()
        dummy.setFixedWidth(self.btn_back.sizeHint().width())
        layout.addWidget(dummy)
        
        self.main_layout.addWidget(self.top_bar)

    def _apply_stash_button_style(self):
        if not self._show_stash_controls:
            return
        cm = ColorManager.instance()
        hover = cm.to_qss_color("image_detail.toolbar.button.hover_background", default="#FFFFFF1E")
        pressed = cm.to_qss_color("image_detail.toolbar.button.pressed_background", default="#FFFFFF32")
        checked_bg = cm.to_qss_color("image_detail.toolbar.button.hover_background", default="#FFFFFF1E")
        tooltip_text = cm.get("tooltip.text")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_border = cm.get("tooltip.border")
        self.btn_stash.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
                color: #FFFFFF;
            }}
            QPushButton:hover {{
                background-color: {hover};
                color: #FFFFFF;
            }}
            QPushButton:pressed {{
                background-color: {pressed};
                color: #FFFFFF;
            }}
            QPushButton:checked {{
                background-color: {checked_bg};
                color: #FFFFFF;
            }}
            QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
        """)
        self._update_stash_ui()

    def _update_stash_ui(self):
        if not self._show_stash_controls:
            return
        try:
            info = None
            if self.image_list and 0 <= int(self.current_index) < len(self.image_list):
                it = self.image_list[int(self.current_index)]
                if isinstance(it, dict):
                    info = it
            is_stashed = bool(info.get("is_stashed")) if isinstance(info, dict) else False
        except Exception:
            is_stashed = False
        try:
            self.btn_stash.blockSignals(True)
            self.btn_stash.setChecked(bool(is_stashed))
            self.btn_stash.blockSignals(False)
        except Exception:
            try:
                self.btn_stash.blockSignals(False)
            except Exception:
                pass
        try:
            self.btn_stash.setIconSize(QSize(20, 20))
            if is_stashed:
                self.btn_stash.setIcon(qta.icon("mdi6.tag-check", color="white"))
                self.btn_stash.setToolTip("取消暂存")
            else:
                self.btn_stash.setIcon(qta.icon("mdi6.tag-outline", color="white"))
                self.btn_stash.setToolTip("暂存")
        except Exception:
            pass

        try:
            idx = int(getattr(self, "current_index", -1))
        except Exception:
            idx = -1
        if idx >= 0:
            try:
                mi = self._strip_model.index(int(idx), 0)
                if mi.isValid():
                    self._strip_model.dataChanged.emit(mi, mi, [])
            except Exception:
                pass
        try:
            if hasattr(self, "thumbnail_scroll") and self.thumbnail_scroll is not None:
                self.thumbnail_scroll.viewport().update()
        except Exception:
            pass

        try:
            if hasattr(self, "stash_icon_main") and self.stash_icon_main:
                if is_stashed:
                    self.stash_icon_main.setPixmap(qta.icon("mdi6.tag-check", color="#4CAF50").pixmap(18, 18))
                    self.stash_icon_main.show()
                    self._update_stash_icon_pos(self.view.viewport(), self.stash_icon_main, self.info_overlay_main)
                else:
                    self.stash_icon_main.hide()
        except Exception:
            pass

        if getattr(self, "compare_mode", False):
            try:
                li = getattr(self, "saved_left_index", None)
                ri = getattr(self, "current_index", None)
                left_stashed = False
                right_stashed = False
                if li is not None and self.image_list and 0 <= int(li) < len(self.image_list):
                    left_stashed = bool(self.image_list[int(li)].get("is_stashed"))
                if ri is not None and self.image_list and 0 <= int(ri) < len(self.image_list):
                    right_stashed = bool(self.image_list[int(ri)].get("is_stashed"))
                if hasattr(self, "stash_icon_left") and self.stash_icon_left:
                    if left_stashed:
                        self.stash_icon_left.setPixmap(qta.icon("mdi6.tag-check", color="#4CAF50").pixmap(18, 18))
                        self.stash_icon_left.show()
                        self._update_stash_icon_pos(self.view_left.viewport(), self.stash_icon_left, self.info_overlay_left)
                    else:
                        self.stash_icon_left.hide()
                if hasattr(self, "stash_icon_right") and self.stash_icon_right:
                    if right_stashed:
                        self.stash_icon_right.setPixmap(qta.icon("mdi6.tag-check", color="#4CAF50").pixmap(18, 18))
                        self.stash_icon_right.show()
                        self._update_stash_icon_pos(self.view_right.viewport(), self.stash_icon_right, self.info_overlay_right)
                    else:
                        self.stash_icon_right.hide()
            except Exception:
                pass

    def update_stash_ui(self):
        self._update_stash_ui()

    def _on_stash_clicked(self):
        if not bool(getattr(self, "_show_stash_controls", False)):
            return
        try:
            if self.image_list and 0 <= int(self.current_index) < len(self.image_list):
                it = self.image_list[int(self.current_index)]
                if isinstance(it, dict):
                    p = it.get("path")
                else:
                    p = None
            else:
                p = None
        except Exception:
            p = None
        if p:
            self.stash_toggle_requested.emit(str(p))
        try:
            self._update_stash_ui()
        except Exception:
            pass

    def _on_delete_clicked(self):
        """删除按钮点击处理 - 使用与右键菜单相同的确认弹窗"""
        try:
            if self.image_list and 0 <= int(self.current_index) < len(self.image_list):
                it = self.image_list[int(self.current_index)]
                if isinstance(it, dict):
                    image_path = it.get("path")
                else:
                    image_path = None
            else:
                image_path = None
        except Exception:
            image_path = None
        
        if not image_path:
            return
        
        try:
            from ui.utils.notification_manager import NotificationManager
            from utils.setting.settings_manager import SettingsManager
            
            # 获取上次的删除选择状态
            delete_local_key = "library/delete_local_file_enabled"
            sm = SettingsManager.instance()
            
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
            
            # 使用带复选框的确认对话框（与右键菜单一致）
            confirmed, delete_local = NotificationManager.instance().ask_confirmation(
                "确认删除",
                f"确定要删除以下文件吗？\n{os.path.basename(image_path)}",
                show_checkbox=True,
                checkbox_text="同时删除本地磁盘文件",
                default_checked=_to_bool(sm.get(delete_local_key, True), default=True)
            )
            
            try:
                sm.set(delete_local_key, delete_local)
                sm.sync()
            except Exception:
                pass
            
            if not confirmed:
                return
            
            # 删除本地文件（如果勾选）
            if delete_local and os.path.exists(image_path):
                deleted = False
                try:
                    # 尝试使用send2trash
                    import send2trash
                    send2trash.send2trash(image_path)
                    deleted = True
                except ImportError:
                    # send2trash未安装，使用Windows API
                    try:
                        import ctypes
                        from ctypes import windll, c_wchar_p, c_uint
                        
                        # 使用SHFileOperation将文件移到回收站
                        class SHFILEOPSTRUCT(ctypes.Structure):
                            _fields_ = [
                                ("hwnd", ctypes.c_void_p),
                                ("wFunc", c_uint),
                                ("pFrom", c_wchar_p),
                                ("pTo", c_wchar_p),
                                ("fFlags", ctypes.c_uint16),
                                ("fAnyOperationsAborted", ctypes.c_int),
                                ("hNameMappings", ctypes.c_void_p),
                                ("lpszProgressTitle", c_wchar_p)
                            ]
                        
                        FO_DELETE = 0x0003
                        FOF_ALLOWUNDO = 0x0040
                        FOF_NOCONFIRMATION = 0x0010
                        FOF_SILENT = 0x0004
                        
                        pFrom = image_path + '\0'
                        
                        fileop = SHFILEOPSTRUCT()
                        fileop.hwnd = None
                        fileop.wFunc = FO_DELETE
                        fileop.pFrom = pFrom
                        fileop.pTo = None
                        fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
                        fileop.fAnyOperationsAborted = 0
                        fileop.hNameMappings = None
                        fileop.lpszProgressTitle = None
                        
                        result = windll.shell32.SHFileOperationW(ctypes.byref(fileop))
                        if result == 0:
                            deleted = True
                        else:
                            # Windows API失败，直接删除
                            os.remove(image_path)
                            deleted = True
                    except Exception:
                        # Windows API失败，直接删除
                        os.remove(image_path)
                        deleted = True
                except Exception:
                    # send2trash失败，直接删除
                    try:
                        os.remove(image_path)
                        deleted = True
                    except Exception:
                        pass
                
                if not deleted:
                    NotificationManager.instance().show_error("删除失败", "无法删除文件")
                    return
            
            # 从数据库中删除记录（总是执行）
            try:
                self.db.delete_image_by_path(image_path, table_name=self._db_table_name)
            except Exception:
                pass
            
            # 从图片列表中移除
            try:
                self.image_list.pop(self.current_index)
            except Exception:
                pass
            
            # 如果列表为空，关闭详情面板
            if not self.image_list:
                NotificationManager.instance().show_toast("图片已删除")
                self.back_requested.emit()
                return
            
            # 调整当前索引
            if self.current_index >= len(self.image_list):
                self.current_index = len(self.image_list) - 1
            
            # 加载下一张图片
            self.load_current_image()
            self.update_thumbnail_selection()
            
            NotificationManager.instance().show_toast("图片已删除")
            
        except Exception as e:
            try:
                from ui.utils.notification_manager import NotificationManager
                NotificationManager.instance().show_error("删除失败", f"删除图片时出错：{str(e)}")
            except Exception:
                pass

    # 移除原有的 init_info_bar
    # def init_info_bar(self): ...

    def init_image_view(self):
        # 使用 QStackedWidget 管理单图/对比模式
        self.center_stack = QStackedWidget()
        
        # --- 页面 1: 单图模式 ---
        self.image_container = QWidget()
        container_layout = QVBoxLayout(self.image_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # 使用 QGraphicsView 实现缩放和拖拽
        self.scene = QGraphicsScene()
        self.view = MagnifierGraphicsView(self.scene)
        self.view.setStyleSheet("background: transparent; border: none;")
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 优化显示效果：始终保持居中
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        
        # 连接视图的缩放信号
        self.view.zoom_in_requested.connect(self.zoom_in)
        self.view.zoom_out_requested.connect(self.zoom_out)
        try:
            self.view.magnification_changed.connect(lambda _v=None: self._auto_nav_pause_if_needed())
        except Exception:
            pass
        try:
            self.view.magnification_changed.connect(lambda f: self._on_magnification_changed(f))
        except Exception:
            pass
        try:
            self.view.lens_radius_changed.connect(lambda r: self._on_magnifier_lens_radius_changed(r))
        except Exception:
            pass
        self.view.manual_rect_saved.connect(self.save_manual_subject_rect)
        self.view.ctrl_right_detect_requested.connect(lambda: self.detect_subject(force=False))
        
        # 安装事件过滤器以拦截键盘事件
        self.view.installEventFilter(self)
        try:
            self.view.viewport().installEventFilter(self)
        except Exception:
            pass
        
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        
        container_layout.addWidget(self.view)
        
        # 左右导航按钮 (浮动在 view 上)
        # 注意：这里将按钮设为 image_container 的子控件，并使用 resizeEvent 调整位置
        self.btn_prev = QPushButton(self.image_container)
        self.btn_prev.setIcon(qta.icon('mdi6.chevron-left', color='white'))
        self.btn_prev.setIconSize(QSize(48, 48))
        self.btn_prev.setFixedSize(60, 100)
        cm = ColorManager.instance()
        nav_bg = cm.to_qss_color("image_detail.nav_button.background", default="#00000032")
        nav_hover_bg = cm.to_qss_color("image_detail.nav_button.hover_background", default="#00000064")
        self.btn_prev.setStyleSheet(f"""
            QPushButton {{ background-color: {nav_bg}; border: none; border-radius: 5px; }}
            QPushButton:hover {{ background-color: {nav_hover_bg}; }}
        """)
        self.btn_prev.clicked.connect(self.show_prev_image)
        
        self.btn_next = QPushButton(self.image_container)
        self.btn_next.setIcon(qta.icon('mdi6.chevron-right', color='white'))
        self.btn_next.setIconSize(QSize(48, 48))
        self.btn_next.setFixedSize(60, 100)
        self.btn_next.setStyleSheet(f"""
            QPushButton {{ background-color: {nav_bg}; border: none; border-radius: 5px; }}
            QPushButton:hover {{ background-color: {nav_hover_bg}; }}
        """)
        self.btn_next.clicked.connect(self.show_next_image)

        if self._show_action_overlay:
            self.overlay_main = ImageActionOverlay(self.view.viewport())
            self.overlay_main.action_triggered.connect(self.on_overlay_action)
            self.overlay_main.hide()
        else:
            self.overlay_main = None

        # 添加主视图的信息浮层
        self.info_overlay_stack_main = QWidget(self.view.viewport())
        self.info_overlay_stack_main.setStyleSheet("background: transparent;")

        self.info_overlay_main = ImageInfoOverlay(self.info_overlay_stack_main)
        self.info_overlay_main.hide()
        self.all_info_overlay_main = ImageAllInfoOverlay(self.info_overlay_stack_main)
        self.all_info_overlay_main.hide()

        self.all_info_expand_btn = QToolButton(self.view.viewport())
        try:
            cm = ColorManager.instance()
            overlay_bg = cm.to_qss_color("image_detail.overlay.background", default="#00000064")
            overlay_border = cm.to_qss_color("image_detail.overlay.border", default="#FFFFFF33")
            overlay_hover = cm.to_qss_color("image_detail.overlay.hover_background", default="#FFFFFF1E")
            self.all_info_expand_btn.setStyleSheet(
                f"QToolButton {{ background-color: {overlay_bg}; border: 1px solid {overlay_border}; border-radius: 6px; "
                f"padding: 0px; margin: 0px; outline: none; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; }}"
                f"QToolButton:hover {{ background-color: {overlay_hover}; }}"
                f"QToolButton:focus {{ outline: none; }}"
            )
        except Exception:
            pass
        self.all_info_expand_btn.setIcon(qta.icon("mdi6.chevron-down", color="white"))
        self.all_info_expand_btn.setFixedSize(32, 32)
        try:
            self.all_info_expand_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        self.all_info_expand_btn.clicked.connect(lambda: self._set_all_info_collapsed(False, persist=True))
        self.all_info_expand_btn.hide()

        try:
            self.all_info_overlay_main.collapse_requested.connect(lambda: self._set_all_info_collapsed(True, persist=True))
            self.all_info_overlay_main.html_loaded.connect(self._restore_all_info_scroll_pos)
        except Exception:
            pass
        try:
            show_ext = bool(getattr(self, "_db_table_name", "bird_results") != "import_cache")
            self._all_info_mirror_panel = InfoPanel(show_extended_info=show_ext)
            self._all_info_mirror_panel.hide()
        except Exception:
            self._all_info_mirror_panel = None
        try:
            sm0 = getattr(self, "_settings_manager", None)
            self._all_info_collapsed = bool(sm0.get("image_detail/all_info_overlay_collapsed", False)) if sm0 is not None else False
        except Exception:
            self._all_info_collapsed = False
        try:
            self._set_all_info_collapsed(bool(getattr(self, "_all_info_collapsed", False)), persist=False)
        except Exception:
            pass
        self.info_overlay_stack_main.adjustSize()
        
        if self._show_stash_controls:
            self.stash_icon_main = QLabel(self.view.viewport())
            self.stash_icon_main.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.stash_icon_main.hide()

        # 安装事件过滤器以处理布局变化（解决按钮错位问题）
        self.image_container.installEventFilter(self)

        self.center_stack.addWidget(self.image_container)

        # --- 页面 2: 对比模式 ---
        self.init_compare_view()
        self.center_stack.addWidget(self.compare_container)
        
        self.main_layout.addWidget(self.center_stack, 1) # 占用主要空间

        try:
            self._apply_saved_magnifier_lens_radius()
        except Exception:
            pass
        try:
            self._apply_saved_magnification_factor()
        except Exception:
            pass

    def init_compare_view(self):
        """初始化对比模式视图"""
        self.compare_container = QWidget()
        layout = QHBoxLayout(self.compare_container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        cm = ColorManager.instance()
        handle_bg = cm.to_qss_color("image_detail.splitter.handle_background", default="#444444")
        self.splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {handle_bg}; }}")
        
        # 左侧视图 (参考图)
        self.scene_left = QGraphicsScene()
        self.view_left = MagnifierGraphicsView(self.scene_left)
        self._setup_compare_view(self.view_left)
        self.pixmap_item_left = QGraphicsPixmapItem()
        self.scene_left.addItem(self.pixmap_item_left)
        self.view_left.manual_rect_saved.connect(lambda rect: self.save_manual_subject_rect(rect, side="left"))
        self.view_left.ctrl_right_detect_requested.connect(lambda: self.detect_subject(force=False, side="left"))
        try:
            self.view_left.magnification_changed.connect(lambda _v=None: self._auto_nav_pause_if_needed())
        except Exception:
            pass
        try:
            self.view_left.magnification_changed.connect(lambda f: self._on_magnification_changed(f))
        except Exception:
            pass
        try:
            self.view_left.lens_radius_changed.connect(lambda r: self._on_magnifier_lens_radius_changed(r))
        except Exception:
            pass
        
        # 右侧视图 (当前图)
        self.scene_right = QGraphicsScene()
        self.view_right = MagnifierGraphicsView(self.scene_right)
        self._setup_compare_view(self.view_right)
        self.view_right.manual_rect_saved.connect(lambda rect: self.save_manual_subject_rect(rect, side="right"))
        self.view_right.ctrl_right_detect_requested.connect(lambda: self.detect_subject(force=False, side="right"))
        try:
            self.view_right.magnification_changed.connect(lambda _v=None: self._auto_nav_pause_if_needed())
        except Exception:
            pass
        try:
            self.view_right.magnification_changed.connect(lambda f: self._on_magnification_changed(f))
        except Exception:
            pass
        try:
            self.view_right.lens_radius_changed.connect(lambda r: self._on_magnifier_lens_radius_changed(r))
        except Exception:
            pass
        self.pixmap_item_right = QGraphicsPixmapItem()
        self.scene_right.addItem(self.pixmap_item_right)
        
        if self._show_action_overlay:
            self.overlay_left = ImageActionOverlay(self.view_left.viewport())
            self.overlay_left.action_triggered.connect(self.on_overlay_action)
            self.overlay_left.hide()

            self.overlay_right = ImageActionOverlay(self.view_right.viewport())
            self.overlay_right.action_triggered.connect(self.on_overlay_action)
            self.overlay_right.hide()
        else:
            self.overlay_left = None
            self.overlay_right = None
        
        # 4. 信息浮层 (InfoOverlay)
        self.info_overlay_left = ImageInfoOverlay(self.view_left.viewport())
        self.info_overlay_left.hide()

        self.info_overlay_right = ImageInfoOverlay(self.view_right.viewport())
        self.info_overlay_right.hide()

        if self._show_stash_controls:
            self.stash_icon_left = QLabel(self.view_left.viewport())
            self.stash_icon_left.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.stash_icon_left.hide()
            self.stash_icon_right = QLabel(self.view_right.viewport())
            self.stash_icon_right.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.stash_icon_right.hide()

        # --- 同步逻辑 ---
        # 1. 滚动条同步 (使用相对位移，支持独立拖动后的联动)
        self._is_syncing_scroll = False # 防止循环同步的标志

        def sync_scroll(source, target):
            if self._is_syncing_scroll:
                return

            # 获取上次的值
            last_value = source.property("last_value")
            current_value = source.value()
            
            # 如果没有记录上次的值，初始化它并返回（避免第一次跳变）
            if last_value is None:
                source.setProperty("last_value", current_value)
                return
            
            # 计算增量
            delta = current_value - last_value
            
            # 更新上次的值
            source.setProperty("last_value", current_value)
            
            # 如果没有变化，直接返回
            if delta == 0:
                return

            # 检查是否按下了 Ctrl 键
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                return
                
            # 应用增量到目标
            self._is_syncing_scroll = True
            target.setValue(target.value() + delta)
            target.setProperty("last_value", target.value())
            self._is_syncing_scroll = False

        # 初始化 last_value
        self.view_left.horizontalScrollBar().setProperty("last_value", self.view_left.horizontalScrollBar().value())
        self.view_right.horizontalScrollBar().setProperty("last_value", self.view_right.horizontalScrollBar().value())
        self.view_left.verticalScrollBar().setProperty("last_value", self.view_left.verticalScrollBar().value())
        self.view_right.verticalScrollBar().setProperty("last_value", self.view_right.verticalScrollBar().value())

        self.view_left.horizontalScrollBar().valueChanged.connect(
            lambda v: sync_scroll(self.view_left.horizontalScrollBar(), self.view_right.horizontalScrollBar()))
        self.view_right.horizontalScrollBar().valueChanged.connect(
            lambda v: sync_scroll(self.view_right.horizontalScrollBar(), self.view_left.horizontalScrollBar()))
            
        self.view_left.verticalScrollBar().valueChanged.connect(
            lambda v: sync_scroll(self.view_left.verticalScrollBar(), self.view_right.verticalScrollBar()))
        self.view_right.verticalScrollBar().valueChanged.connect(
            lambda v: sync_scroll(self.view_right.verticalScrollBar(), self.view_left.verticalScrollBar()))

        # 2. 放大镜同步
        self.view_left.magnifier_toggled.connect(self.view_right.set_magnifier_state)
        self.view_right.magnifier_toggled.connect(self.view_left.set_magnifier_state)
        
        self.view_left.magnifier_moved.connect(self.view_right.set_magnifier_pos)
        self.view_right.magnifier_moved.connect(self.view_left.set_magnifier_pos)
        
        self.view_left.magnification_changed.connect(self.view_right.set_magnification)
        self.view_right.magnification_changed.connect(self.view_left.set_magnification)

        self.view_left.lens_radius_changed.connect(self.view_right.set_lens_radius)
        self.view_right.lens_radius_changed.connect(self.view_left.set_lens_radius)
        
        # 应用保存的放大镜设置到对比模式
        try:
            self._apply_saved_magnifier_lens_radius()
        except Exception:
            pass
        try:
            self._apply_saved_magnification_factor()
        except Exception:
            pass
        
        self.splitter.addWidget(self.view_left)
        self.splitter.addWidget(self.view_right)
        
        # 默认 5:5 分割
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        
        layout.addWidget(self.splitter)

    def _setup_compare_view(self, view):
        view.setStyleSheet("background: transparent; border: none;")
        view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        view.zoom_in_requested.connect(self.zoom_in)
        view.zoom_out_requested.connect(self.zoom_out)
        view.installEventFilter(self)
        try:
            view.viewport().installEventFilter(self)
        except Exception:
            pass

    def _apply_saved_magnifier_lens_radius(self):
        sm = getattr(self, "_settings_manager", None)
        if sm is None:
            return
        try:
            r = int(sm.get("image_detail/magnifier_lens_radius", 150) or 150)
        except Exception:
            r = 150
        if r < 60:
            r = 60
        if r > 360:
            r = 360
        for v in self._get_active_views():
            try:
                v.set_lens_radius(int(r))
            except Exception:
                pass

    def _on_magnifier_lens_radius_changed(self, radius: int):
        sm = getattr(self, "_settings_manager", None)
        if sm is None:
            return
        try:
            r = int(radius)
        except Exception:
            return
        if r < 60:
            r = 60
        if r > 360:
            r = 360
        try:
            sm.set("image_detail/magnifier_lens_radius", int(r))
            sm.sync()
        except Exception:
            pass

    def _on_magnification_changed(self, factor: float):
        """保存放大镜放大倍率到设置"""
        sm = getattr(self, "_settings_manager", None)
        if sm is None:
            return
        try:
            f = float(factor)
        except Exception:
            return
        if f < 1.1:
            f = 1.1
        if f > 8.0:
            f = 8.0
        try:
            sm.set("image_detail/magnification_factor", float(f))
            sm.sync()
        except Exception:
            pass

    def _apply_saved_magnification_factor(self):
        """应用保存的放大镜放大倍率"""
        sm = getattr(self, "_settings_manager", None)
        if sm is None:
            return
        try:
            f = float(sm.get("image_detail/magnification_factor", 1.5) or 1.5)
        except Exception:
            f = 1.5
        if f < 1.1:
            f = 1.1
        if f > 8.0:
            f = 8.0
        for v in self._get_active_views():
            try:
                v.set_magnification(float(f))
            except Exception:
                pass

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if obj == self.view or obj == self.view_left or obj == self.view_right or obj == self.view.viewport() or obj == self.view_left.viewport() or obj == self.view_right.viewport():
                # 转发给自己的 keyPressEvent 处理
                self.keyPressEvent(event)
                return True # 拦截事件，避免 QGraphicsView 默认处理（如滚动）
        if event.type() == QEvent.Type.KeyRelease:
            if obj == self.view or obj == self.view_left or obj == self.view_right or obj == self.view.viewport() or obj == self.view_left.viewport() or obj == self.view_right.viewport():
                self.keyReleaseEvent(event)
                return True
        
        elif event.type() == QEvent.Type.Resize:
            if obj == self.image_container:
                self.update_nav_buttons_pos()
                if hasattr(self, 'overlay_main') and self.overlay_main:
                    self._update_overlay_pos(self.view.viewport(), self.overlay_main, is_info=False)
                self._update_main_info_stack_layout()
                if hasattr(self, "stash_icon_main") and self.stash_icon_main:
                    self._update_stash_icon_pos(self.view.viewport(), self.stash_icon_main, self.info_overlay_main)
                    
            elif obj == self.view or obj == self.view.viewport():
                if hasattr(self, 'overlay_main') and self.overlay_main:
                    self._update_overlay_pos(self.view.viewport(), self.overlay_main, is_info=False)
                self._update_main_info_stack_layout()
                if hasattr(self, "stash_icon_main") and self.stash_icon_main:
                    self._update_stash_icon_pos(self.view.viewport(), self.stash_icon_main, self.info_overlay_main)

            elif obj == self.view_left or obj == self.view_left.viewport():
                if hasattr(self, 'overlay_left') and self.overlay_left:
                    self._update_overlay_pos(self.view_left.viewport(), self.overlay_left, is_info=False)
                if hasattr(self, 'info_overlay_left') and self.info_overlay_left:
                    self._update_overlay_pos(self.view_left.viewport(), self.info_overlay_left, is_info=True)
                if hasattr(self, "stash_icon_left") and self.stash_icon_left:
                    self._update_stash_icon_pos(self.view_left.viewport(), self.stash_icon_left, self.info_overlay_left)
                    
            elif obj == self.view_right or obj == self.view_right.viewport():
                if hasattr(self, 'overlay_right') and self.overlay_right:
                    self._update_overlay_pos(self.view_right.viewport(), self.overlay_right, is_info=False)
                if hasattr(self, 'info_overlay_right') and self.info_overlay_right:
                    self._update_overlay_pos(self.view_right.viewport(), self.info_overlay_right, is_info=True)
                if hasattr(self, "stash_icon_right") and self.stash_icon_right:
                    self._update_stash_icon_pos(self.view_right.viewport(), self.stash_icon_right, self.info_overlay_right)
                
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        # 确保面板显示时获得焦点，以便立即响应快捷键
        if hasattr(self, 'view') and self.view:
            self.view.setFocus()
        try:
            QTimer.singleShot(0, lambda: self._update_overlay_pos(self.view.viewport(), self.overlay_main, is_info=False) if getattr(self, "overlay_main", None) is not None else None)
            QTimer.singleShot(0, self._update_main_info_stack_layout)
        except Exception:
            pass
        
        # [修复] 确保面板显示时图片适应窗口
        # 这解决了"即使以100%退出，下次进入还是偏小"的问题
        # 因为在图片加载时面板可能还不可见(size不对)，导致fit计算错误
        # 只有在showEvent且layout完成(timer=0)后，才能获取正确的viewport尺寸进行fit
        try:
            if hasattr(self, 'pixmap_item') and self.pixmap_item.pixmap() and not self.pixmap_item.pixmap().isNull():
                self.zoom_scale = 1.0
                QTimer.singleShot(0, self.fit_image_to_view)
        except Exception:
            pass

    def hideEvent(self, event):
        try:
            self._auto_nav_stop()
        except Exception:
            pass
        super().hideEvent(event)

    def keyPressEvent(self, event):
        sm = ShortcutManager.instance()

        try:
            if sm.is_match("ImageDetail.AutoPause", event):
                self._auto_nav_toggle_pause()
                event.accept()
                return
        except Exception:
            pass
        try:
            if sm.is_match("ImageDetail.AutoNext", event):
                self._auto_nav_keypress(1, bool(event.isAutoRepeat()))
                event.accept()
                return
        except Exception:
            pass
        try:
            if sm.is_match("ImageDetail.AutoPrev", event):
                self._auto_nav_keypress(-1, bool(event.isAutoRepeat()))
                event.accept()
                return
        except Exception:
            pass

        try:
            if int(event.key()) == int(Qt.Key.Key_Space) and not bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                if bool(getattr(self, "_show_stash_controls", False)):
                    try:
                        if self.image_list and 0 <= int(self.current_index) < len(self.image_list):
                            it = self.image_list[int(self.current_index)]
                            if isinstance(it, dict) and it.get("path"):
                                self.stash_toggle_requested.emit(str(it.get("path")))
                    except Exception:
                        pass
                    try:
                        self._update_stash_ui()
                    except Exception:
                        pass
                event.accept()
                return
        except Exception:
            pass
        
        try:
            mods = event.modifiers()
        except Exception:
            mods = Qt.KeyboardModifier.NoModifier
        try:
            k_int = int(event.key())
        except Exception:
            k_int = -1

        if (not bool(getattr(self, "compare_mode", False))) and k_int == int(Qt.Key.Key_R) and not bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            try:
                self._set_all_info_collapsed(not bool(getattr(self, "_all_info_collapsed", False)), persist=True)
            except Exception:
                pass
            event.accept()
            return

        try:
            if sm.is_match("ImageDetail.ResetView", event):
                try:
                    self._auto_nav_pause_if_needed()
                except Exception:
                    pass
                try:
                    self.zoom_scale = 1.0
                    try:
                        if self._settings_manager is not None:
                            self._settings_manager.set("image_detail/zoom_scale", float(self.zoom_scale))
                            self._settings_manager.sync()
                    except Exception:
                        pass
                    self.fit_image_to_view()
                except Exception:
                    pass
                event.accept()
                return
        except Exception:
            pass

        try:
            reset_seq = str(sm.get_sequence_str("ImageDetail.ResetView") or "").strip()
        except Exception:
            reset_seq = ""
        if reset_seq in ("", "Tab") and k_int == int(Qt.Key.Key_Tab) and not bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            try:
                self._auto_nav_pause_if_needed()
            except Exception:
                pass
            try:
                self.zoom_scale = 1.0
                try:
                    if self._settings_manager is not None:
                        self._settings_manager.set("image_detail/zoom_scale", float(self.zoom_scale))
                        self._settings_manager.sync()
                except Exception:
                    pass
                self.fit_image_to_view()
            except Exception:
                pass
            event.accept()
            return

        try:
            if bool(getattr(self, "_auto_nav_active", False)) and not bool(getattr(self, "_auto_nav_paused", False)):
                if k_int in (int(Qt.Key.Key_A), int(Qt.Key.Key_D)) and not bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
                    if bool(event.isAutoRepeat()):
                        try:
                            self._auto_nav_keypress(1 if k_int == int(Qt.Key.Key_D) else -1, True)
                        except Exception:
                            pass
                    else:
                        try:
                            cur_dir = int(getattr(self, "_auto_nav_direction", 0) or 0)
                        except Exception:
                            cur_dir = 0
                        key_dir = 1 if k_int == int(Qt.Key.Key_D) else -1
                        if cur_dir != 0 and int(key_dir) != int(cur_dir):
                            try:
                                ok = bool(self._auto_nav_step(int(key_dir)))
                            except Exception:
                                ok = False
                            if ok:
                                try:
                                    self._auto_nav_hold_direction = 0
                                except Exception:
                                    pass
                                try:
                                    self._auto_nav_current_interval_ms = int(self._auto_nav_get_base_interval_ms())
                                except Exception:
                                    pass
                                try:
                                    self._auto_nav_schedule()
                                except Exception:
                                    pass
                    event.accept()
                    return
        except Exception:
            pass

        try:
            matched = False
            use_right = False
            if bool(getattr(self, "compare_mode", False)):
                try:
                    if sm.is_match("ImageDetailRight.ToggleFavorite", event):
                        matched = True
                        use_right = True
                except Exception:
                    matched = False
            if not matched:
                try:
                    if sm.is_match("ImageDetail.ToggleFavorite", event):
                        matched = True
                        use_right = False
                except Exception:
                    matched = False
            if not matched:
                try:
                    cfg_left = str(sm.get_sequence_str("ImageDetail.ToggleFavorite") or "").strip()
                except Exception:
                    cfg_left = ""
                try:
                    cfg_right = str(sm.get_sequence_str("ImageDetailRight.ToggleFavorite") or "").strip()
                except Exception:
                    cfg_right = ""
                try:
                    txt0 = str(event.text() or "")
                except Exception:
                    txt0 = ""
                if txt0 == "·":
                    if bool(getattr(self, "compare_mode", False)) and bool(mods & Qt.KeyboardModifier.AltModifier) and cfg_right.endswith("`"):
                        matched = True
                        use_right = True
                    elif (not bool(mods & Qt.KeyboardModifier.AltModifier)) and cfg_left.endswith("`"):
                        matched = True
                        use_right = False
            if matched and not bool(mods & Qt.KeyboardModifier.ControlModifier):
                target_path = None
                if bool(getattr(self, "compare_mode", False)):
                    try:
                        idx = int(getattr(self, "current_index", 0)) if use_right else int(getattr(self, "saved_left_index", getattr(self, "current_index", 0)))
                    except Exception:
                        idx = int(getattr(self, "current_index", 0))
                    if 0 <= int(idx) < len(self.image_list):
                        target_path = (self.image_list[int(idx)] or {}).get("path")
                else:
                    try:
                        if 0 <= int(self.current_index) < len(self.image_list):
                            target_path = (self.image_list[int(self.current_index)] or {}).get("path")
                    except Exception:
                        target_path = None
                if target_path:
                    self.toggle_favorite(target_path=target_path)
                    event.accept()
                    return
        except Exception:
            pass

        try:
            if not bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                for rating in (1, 2, 3, 4, 5):
                    matched = False
                    use_right = False
                    if bool(getattr(self, "compare_mode", False)):
                        try:
                            if sm.is_match(f"ImageDetailRight.SetRating{rating}", event):
                                matched = True
                                use_right = True
                        except Exception:
                            matched = False
                    if not matched:
                        try:
                            if sm.is_match(f"ImageDetail.SetRating{rating}", event):
                                matched = True
                                use_right = False
                        except Exception:
                            matched = False
                    if not matched:
                        continue
                    target_path = None
                    if bool(getattr(self, "compare_mode", False)):
                        try:
                            idx = int(getattr(self, "current_index", 0)) if use_right else int(getattr(self, "saved_left_index", getattr(self, "current_index", 0)))
                        except Exception:
                            idx = int(getattr(self, "current_index", 0))
                    else:
                        idx = int(getattr(self, "current_index", 0))
                    try:
                        if 0 <= int(idx) < len(self.image_list):
                            target_path = (self.image_list[int(idx)] or {}).get("path")
                    except Exception:
                        target_path = None
                    if target_path:
                        cur_rating = None
                        try:
                            rec = self._get_record_for_path(str(target_path)) or {}
                            if isinstance(rec, dict):
                                cur_rating = int(rec.get("rating", 0) or 0)
                        except Exception:
                            cur_rating = None
                        if cur_rating is None:
                            try:
                                cur_rating = int((self._find_image_info_by_path(str(target_path)) or {}).get("rating", 0) or 0)
                            except Exception:
                                cur_rating = 0
                        new_rating = 0 if int(cur_rating) == int(rating) else int(rating)
                        self.set_rating(int(new_rating), target_path=target_path)
                        event.accept()
                        return
        except Exception:
            pass

        try:
            label_map = {
                0: "",
                1: "Red",
                2: "Orange",
                3: "Yellow",
                4: "Green",
                5: "Cyan",
                6: "Blue",
                7: "Purple",
                8: "Pink",
                9: "White",
            }
            for digit, label in label_map.items():
                matched = False
                use_right = False
                if bool(getattr(self, "compare_mode", False)):
                    try:
                        if sm.is_match(f"ImageDetailRight.SetLabel{digit}", event):
                            matched = True
                            use_right = True
                    except Exception:
                        matched = False
                if not matched:
                    try:
                        if sm.is_match(f"ImageDetail.SetLabel{digit}", event):
                            matched = True
                            use_right = False
                    except Exception:
                        matched = False
                if not matched:
                    continue
                target_path = None
                if bool(getattr(self, "compare_mode", False)):
                    try:
                        idx = int(getattr(self, "current_index", 0)) if use_right else int(getattr(self, "saved_left_index", getattr(self, "current_index", 0)))
                    except Exception:
                        idx = int(getattr(self, "current_index", 0))
                else:
                    idx = int(getattr(self, "current_index", 0))
                try:
                    if 0 <= int(idx) < len(self.image_list):
                        target_path = (self.image_list[int(idx)] or {}).get("path")
                except Exception:
                    target_path = None
                if target_path is not None:
                    cur_label = ""
                    try:
                        rec = self._get_record_for_path(str(target_path)) or {}
                        if isinstance(rec, dict):
                            cur_label = str(rec.get("label", "") or "")
                    except Exception:
                        cur_label = ""
                    if not cur_label:
                        try:
                            cur_label = str((self._find_image_info_by_path(str(target_path)) or {}).get("label", "") or "")
                        except Exception:
                            cur_label = ""
                    if label and str(cur_label) == str(label):
                        label = ""
                    self.label_changed.emit(str(target_path), str(label))
                    try:
                        if hasattr(self, 'overlay_main') and self.overlay_main and getattr(self.overlay_main, "path", None) == target_path:
                            self.overlay_main.update_label_icon(label)
                        if hasattr(self, 'overlay_left') and self.overlay_left and getattr(self.overlay_left, "path", None) == target_path:
                            self.overlay_left.update_label_icon(label)
                        if hasattr(self, 'overlay_right') and self.overlay_right and getattr(self.overlay_right, "path", None) == target_path:
                            self.overlay_right.update_label_icon(label)
                    except Exception:
                        pass
                    event.accept()
                    return
        except Exception:
            pass

        try:
            if bool(getattr(self, "compare_mode", False)):
                views0 = self._get_active_views()
                magnifier_active0 = any(getattr(v, "magnifier_enabled", False) for v in views0)
                zoomed0 = False
                if not magnifier_active0:
                    for v0 in views0:
                        try:
                            t0 = v0.transform()
                            if abs(float(t0.m11())) > 1.01 or abs(float(t0.m22())) > 1.01:
                                zoomed0 = True
                                break
                        except Exception:
                            pass
                        try:
                            if v0.horizontalScrollBar().maximum() > 0 or v0.verticalScrollBar().maximum() > 0:
                                zoomed0 = True
                                break
                        except Exception:
                            pass
                if (not magnifier_active0) and (not zoomed0):
                    direction = 0
                    try:
                        if sm.is_match("ImageDetail.PanLeft", event):
                            direction = -1
                        elif sm.is_match("ImageDetail.PanRight", event):
                            direction = 1
                    except Exception:
                        direction = 0
                    if direction != 0:
                        try:
                            ri = int(getattr(self, "current_index", 0))
                        except Exception:
                            ri = 0
                        li = getattr(self, "saved_left_index", None)
                        if li is None:
                            li = max(0, int(ri) - 1)
                        try:
                            li = int(li)
                        except Exception:
                            li = max(0, int(ri) - 1)
                        li = li + int(direction)
                        if li == ri:
                            li += int(direction)
                        li = max(0, min(int(li), len(self.image_list) - 1))
                        if li != ri and 0 <= li < len(self.image_list):
                            self.saved_left_index = int(li)
                            self._clear_subject_rect_side("left")
                            self._clear_focus_point_side("left")
                            self.load_left_image(int(li))
                            try:
                                self._prefetch_compare_subject_state()
                            except Exception:
                                pass
                            self.update_thumbnail_selection(center_index=int(li))
                        event.accept()
                        return
        except Exception:
            pass

        try:
            mods = event.modifiers()
            views = self._get_active_views()
            magnifier_active = any(getattr(v, "magnifier_enabled", False) for v in views)
            step = 30
            dx = 0
            dy = 0
            try:
                if sm.is_match("ImageDetail.PanUp", event):
                    dy = -step
                elif sm.is_match("ImageDetail.PanDown", event):
                    dy = step
                elif sm.is_match("ImageDetail.PanLeft", event):
                    dx = -step
                elif sm.is_match("ImageDetail.PanRight", event):
                    dx = step
            except Exception:
                dx = 0
                dy = 0
            if dx or dy:
                try:
                    self._auto_nav_pause_if_needed()
                except Exception:
                    pass
            if magnifier_active and (dx or dy):
                    base_view = None
                    for v in views:
                        if getattr(v, "magnifier_enabled", False):
                            base_view = v
                            break
                    if base_view is not None:
                        try:
                            pos = getattr(base_view, "_sync_pos", None)
                        except Exception:
                            pos = None
                        if pos is None:
                            try:
                                pos = base_view.mapFromGlobal(base_view.cursor().pos())
                            except Exception:
                                pos = QPoint(0, 0)
                        try:
                            x = int(pos.x()) + int(dx)
                            y = int(pos.y()) + int(dy)
                        except Exception:
                            x = int(dx)
                            y = int(dy)
                        try:
                            r = base_view.viewport().rect()
                            x = max(0, min(int(x), int(r.width() - 1)))
                            y = max(0, min(int(y), int(r.height() - 1)))
                        except Exception:
                            pass
                        new_pos = QPoint(int(x), int(y))
                        for v in views:
                            if getattr(v, "magnifier_enabled", False):
                                try:
                                    v.set_magnifier_pos(new_pos)
                                except Exception:
                                    pass
                        event.accept()
                        return
            if (not magnifier_active) and (dx or dy):
                zoomed = False
                for v in views:
                    try:
                        t = v.transform()
                        if abs(float(t.m11())) > 1.01 or abs(float(t.m22())) > 1.01:
                            zoomed = True
                            break
                    except Exception:
                        continue
                    try:
                        if v.horizontalScrollBar().maximum() > 0 or v.verticalScrollBar().maximum() > 0:
                            zoomed = True
                            break
                    except Exception:
                        pass
                if zoomed:
                    for v in views:
                        try:
                            sbx = v.horizontalScrollBar()
                            sby = v.verticalScrollBar()
                            if dx:
                                sbx.setValue(int(sbx.value()) + int(dx))
                            if dy:
                                sby.setValue(int(sby.value()) + int(dy))
                        except Exception:
                            pass
                    event.accept()
                    return
        except Exception:
            pass
        
        # 放大镜开关
        if sm.check_detail_toggle_magnifier(event, self.toggle_magnifier):
            event.accept()
            return

        # 放大 (新增)
        def on_zoom_in():
            # 获取当前激活的视图列表
            views = self._get_active_views()
            
            # 如果其中任何一个开启了放大镜，就使用放大镜逻辑
            magnifier_active = any(v.magnifier_enabled for v in views)
            
            if magnifier_active:
                for v in views:
                    if v.magnifier_enabled:
                        v.magnification_factor += 0.1
                        v.viewport().update()
            else:
                self.zoom_in()

        if sm.check_detail_zoom_in(event, on_zoom_in):
            event.accept()
            return
            
        # 缩小 (新增)
        def on_zoom_out():
            views = self._get_active_views()
            magnifier_active = any(v.magnifier_enabled for v in views)
            
            if magnifier_active:
                for v in views:
                    if v.magnifier_enabled:
                        v.magnification_factor = max(1.1, v.magnification_factor - 0.1)
                        v.viewport().update()
            else:
                self.zoom_out()

        if sm.check_detail_zoom_out(event, on_zoom_out):
            event.accept()
            return

        # 上一张
        if sm.check_detail_prev_image(event, lambda: self._on_prev_image_shortcut()):
            event.accept()
            return
            
        # 下一张
        if sm.check_detail_next_image(event, lambda: self._on_next_image_shortcut()):
            event.accept()
            return

        # 旋转
        if sm.check_detail_rotate(event, self.rotate_image):
            event.accept()
            return

        # 检测主体
        if sm.check_detail_detect_subject(event, self.detect_subject):
            event.accept()
            return

        # 聚焦主体
        if sm.check_detail_zoom_to_bird(event, self.zoom_to_bird):
            event.accept()
            return

        # 显示/隐藏对焦点
        if sm.check_detail_toggle_focus_point(event, self.zoom_to_focus):
            event.accept()
            return

        if sm.check_detail_toggle_subject_rect(event, lambda: (self._auto_nav_pause_if_needed(), self.btn_show_subject_rect.toggle()) if hasattr(self, "btn_show_subject_rect") and self.btn_show_subject_rect is not None else None):
            event.accept()
            return

        # 对比模式
        if sm.check_detail_toggle_compare_mode(event, self.toggle_compare_mode):
            event.accept()
            return

        if sm.check_detail_close(event, self.back_requested.emit):
            event.accept()
            return
            
        # 关闭/返回 (ESC)
        if sm.check_general_close(event, self.back_requested.emit):
            event.accept()
            return
        
        # 放大镜本体大小调整快捷键 (Shift+W / Shift+S)
        try:
            views = self._get_active_views()
            magnifier_active = any(getattr(v, "magnifier_enabled", False) for v in views)
            if magnifier_active:
                if k_int == int(Qt.Key.Key_W) and bool(mods & Qt.KeyboardModifier.ShiftModifier):
                    # 放大镜本体变大
                    for v in views:
                        if getattr(v, "magnifier_enabled", False):
                            new_radius = int(min(360, int(getattr(v, "lens_radius", 150) or 150) + 12))
                            v.set_lens_radius(new_radius)
                    event.accept()
                    return
                if k_int == int(Qt.Key.Key_S) and bool(mods & Qt.KeyboardModifier.ShiftModifier):
                    # 放大镜本体变小
                    for v in views:
                        if getattr(v, "magnifier_enabled", False):
                            new_radius = int(max(60, int(getattr(v, "lens_radius", 150) or 150) - 12))
                            v.set_lens_radius(new_radius)
                    event.accept()
                    return
        except Exception:
            pass

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        try:
            k = int(event.key())
        except Exception:
            k = None
        if k in (int(Qt.Key.Key_A), int(Qt.Key.Key_D)):
            try:
                self._auto_nav_on_key_release(k)
            except Exception:
                pass
        try:
            event.accept()
        except Exception:
            pass

    def _auto_nav_get_base_interval_ms(self) -> int:
        try:
            sm = getattr(self, "_settings_manager", None)
            v = int(sm.get("image_detail/auto_switch_interval_ms", 800) if sm is not None else 800)
        except Exception:
            v = 800
        return int(max(50, min(5000, v)))

    def _auto_nav_schedule(self):
        if not bool(getattr(self, "_auto_nav_active", False)):
            return
        if bool(getattr(self, "_auto_nav_paused", False)):
            return
        try:
            self._auto_nav_timer.stop()
        except Exception:
            pass
        try:
            ms = int(getattr(self, "_auto_nav_current_interval_ms", 800) or 800)
        except Exception:
            ms = 800
        ms = int(max(20, min(5000, ms)))
        self._auto_nav_timer.start(ms)

    def _auto_nav_pause_if_needed(self):
        if not bool(getattr(self, "_auto_nav_active", False)):
            return
        if bool(getattr(self, "_auto_nav_paused", False)):
            return
        self._auto_nav_paused = True
        try:
            self._auto_nav_timer.stop()
        except Exception:
            pass
        try:
            self._update_detail_nav_shortcuts_enabled()
        except Exception:
            pass

    def _update_detail_nav_shortcuts_enabled(self):
        enabled = True
        try:
            enabled = not (bool(getattr(self, "_auto_nav_active", False)) and not bool(getattr(self, "_auto_nav_paused", False)))
        except Exception:
            enabled = True
        for sc in (getattr(self, "_detail_prev_shortcut", None), getattr(self, "_detail_next_shortcut", None)):
            if sc is None:
                continue
            try:
                sc.setEnabled(bool(enabled))
            except Exception:
                pass

    def _auto_nav_step(self, direction: int) -> bool:
        try:
            direction = 1 if int(direction) >= 0 else -1
        except Exception:
            direction = 1
        try:
            idx0 = int(getattr(self, "current_index", 0) or 0)
        except Exception:
            idx0 = 0
        if direction > 0:
            if idx0 >= len(self.image_list) - 1:
                return False
            self._on_next_image_shortcut()
            return True
        if idx0 <= 0:
            return False
        self._on_prev_image_shortcut()
        return True

    def _auto_nav_start(self, direction: int, *, immediate: bool):
        self._auto_nav_active = True
        self._auto_nav_paused = False
        self._auto_nav_direction = 1 if int(direction) >= 0 else -1
        self._auto_nav_base_interval_ms = self._auto_nav_get_base_interval_ms()
        self._auto_nav_current_interval_ms = int(self._auto_nav_base_interval_ms)
        self._auto_nav_hold_direction = 0
        if immediate:
            if not self._auto_nav_step(self._auto_nav_direction):
                self._auto_nav_stop()
                return
        try:
            self._update_detail_nav_shortcuts_enabled()
        except Exception:
            pass
        self._auto_nav_schedule()

    def _auto_nav_stop(self):
        self._auto_nav_active = False
        self._auto_nav_paused = False
        self._auto_nav_direction = 0
        self._auto_nav_hold_direction = 0
        try:
            self._auto_nav_timer.stop()
        except Exception:
            pass
        try:
            self._update_detail_nav_shortcuts_enabled()
        except Exception:
            pass

    def _auto_nav_toggle_pause(self):
        if not bool(getattr(self, "_auto_nav_active", False)):
            return
        self._auto_nav_paused = not bool(getattr(self, "_auto_nav_paused", False))
        if self._auto_nav_paused:
            try:
                self._auto_nav_timer.stop()
            except Exception:
                pass
        else:
            self._auto_nav_current_interval_ms = int(self._auto_nav_get_base_interval_ms())
            self._auto_nav_schedule()
        try:
            self._update_detail_nav_shortcuts_enabled()
        except Exception:
            pass

    def _auto_nav_keypress(self, direction: int, is_repeat: bool):
        dir0 = 1 if int(direction) >= 0 else -1
        if bool(getattr(self, "_auto_nav_active", False)) and not bool(is_repeat):
            if int(getattr(self, "_auto_nav_direction", 0) or 0) == int(dir0):
                self._auto_nav_stop()
                return
        if bool(getattr(self, "_auto_nav_active", False)) and bool(is_repeat):
            if int(getattr(self, "_auto_nav_direction", 0) or 0) != int(dir0):
                return
            self._auto_nav_hold_direction = int(dir0)
            try:
                self._auto_nav_current_interval_ms = int(max(20, int(self._auto_nav_current_interval_ms) * 0.65))
            except Exception:
                self._auto_nav_current_interval_ms = 20
            if self._auto_nav_step(dir0):
                self._auto_nav_schedule()
            else:
                self._auto_nav_stop()
            return
        if bool(getattr(self, "_auto_nav_active", False)) and int(getattr(self, "_auto_nav_direction", 0) or 0) != int(dir0):
            self._auto_nav_direction = int(dir0)
            self._auto_nav_paused = False
            self._auto_nav_base_interval_ms = self._auto_nav_get_base_interval_ms()
            self._auto_nav_current_interval_ms = int(self._auto_nav_base_interval_ms)
            self._auto_nav_hold_direction = 0
            if not self._auto_nav_step(dir0):
                self._auto_nav_stop()
                return
            self._auto_nav_schedule()
            try:
                self._update_detail_nav_shortcuts_enabled()
            except Exception:
                pass
            return
        self._auto_nav_start(dir0, immediate=True)

    def _auto_nav_on_timeout(self):
        if not bool(getattr(self, "_auto_nav_active", False)):
            return
        if bool(getattr(self, "_auto_nav_paused", False)):
            return
        d = int(getattr(self, "_auto_nav_direction", 0) or 0)
        if d == 0:
            self._auto_nav_stop()
            return
        if not self._auto_nav_step(d):
            self._auto_nav_stop()
            return
        if int(getattr(self, "_auto_nav_hold_direction", 0) or 0) == 0:
            self._auto_nav_base_interval_ms = self._auto_nav_get_base_interval_ms()
            self._auto_nav_current_interval_ms = int(self._auto_nav_base_interval_ms)
        self._auto_nav_schedule()

    def _auto_nav_on_key_release(self, key_int: int):
        if not bool(getattr(self, "_auto_nav_active", False)):
            return
        if bool(getattr(self, "_auto_nav_paused", False)):
            return
        d = int(getattr(self, "_auto_nav_direction", 0) or 0)
        if d == 0:
            return
        if int(key_int) == int(Qt.Key.Key_D) and d > 0:
            self._auto_nav_hold_direction = 0
            self._auto_nav_current_interval_ms = int(self._auto_nav_get_base_interval_ms())
        if int(key_int) == int(Qt.Key.Key_A) and d < 0:
            self._auto_nav_hold_direction = 0
            self._auto_nav_current_interval_ms = int(self._auto_nav_get_base_interval_ms())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        # 注意：按钮和 Overlay 的位置更新已移至 eventFilter 处理
        # 这样可以确保在容器实际大小改变时更新，避免错位

        # 适应窗口大小
        if self.pixmap_item.pixmap() and not self.pixmap_item.pixmap().isNull():
            self.fit_image_to_view()
        
        # 根据窗口大小动态调整解码分辨率
        self._update_decode_max_edge_by_viewport()

    def _update_decode_max_edge_by_viewport(self):
        """根据视口大小动态调整解码分辨率，以显示最大分辨率的图片"""
        try:
            # 获取当前激活的视图
            views = self._get_active_views()
            if not views:
                return
            
            # 获取最大视口尺寸
            max_viewport_size = 0
            for v in views:
                try:
                    vw = int(v.viewport().width() or 0)
                    vh = int(v.viewport().height() or 0)
                    max_viewport_size = max(max_viewport_size, vw, vh)
                except Exception:
                    pass
            
            if max_viewport_size <= 0:
                return
            
            # 考虑缩放因子，预留一些余量
            # 使用 2x 视口大小作为解码目标，以支持 200% 缩放
            target_edge = int(max_viewport_size * 2)
            
            # 限制最小和最大值
            min_edge = 1600
            max_edge = 4096  # 最大解码分辨率
            
            new_max_edge = max(min_edge, min(target_edge, max_edge))
            
            # 只有当变化超过 20% 时才更新，避免频繁调整
            current_edge = int(getattr(self, "_detail_decode_max_edge", 2560) or 2560)
            if abs(new_max_edge - current_edge) / current_edge > 0.2:
                self._detail_decode_max_edge = new_max_edge
                # 更新缓存管理器的设置
                try:
                    if hasattr(self, "big_image_cache") and self.big_image_cache:
                        self.big_image_cache.set_max_long_edge_override(new_max_edge)
                except Exception:
                    pass
        except Exception:
            pass

    def _update_overlay_pos(self, view, overlay, is_info=False):
        if not view or not overlay:
            return
            
        # 确保 overlay 尺寸已更新，避免使用旧尺寸导致位置错误
        overlay.adjustSize()
            
        margin = 20
        
        if is_info:
            try:
                max_h = max(60, int(view.height()) - int(margin * 2) - 12)
                overlay.setMaximumHeight(int(max_h))
                overlay.adjustSize()
            except Exception:
                pass
            # 信息浮层：左上角
            x = margin
            y = margin
        else:
            # 操作浮层：右下角
            reserve_right = 0
            try:
                if hasattr(self, "btn_next") and self.btn_next and self.btn_next.isVisible():
                    reserve_right = int(self.btn_next.width()) + 16
            except Exception:
                reserve_right = 0
            x = view.width() - overlay.width() - margin - int(reserve_right)
            y = view.height() - overlay.height() - margin
            
        try:
            x = max(int(margin), int(x))
            y = max(int(margin), int(y))
        except Exception:
            pass
        overlay.move(int(x), int(y))
        overlay.raise_()

    def _update_main_info_stack_layout(self):
        try:
            if bool(getattr(self, "compare_mode", False)):
                try:
                    if getattr(self, "info_overlay_stack_main", None) is not None:
                        self.info_overlay_stack_main.hide()
                except Exception:
                    pass
                try:
                    if getattr(self, "all_info_expand_btn", None) is not None:
                        self.all_info_expand_btn.hide()
                except Exception:
                    pass
                return
        except Exception:
            pass
        view = getattr(self, "view", None)
        if view is None:
            return
        try:
            vp = view.viewport()
        except Exception:
            return
        stack = getattr(self, "info_overlay_stack_main", None)
        if stack is None:
            return
        margin = 20
        gap = 8
        try:
            max_w = max(240, int(vp.width()) - int(margin * 2))
        except Exception:
            max_w = 320
        w = min(360, int(max_w))
        try:
            stack.setFixedWidth(int(w))
        except Exception:
            pass
        try:
            h = max(60, int(vp.height()) - int(margin) - int(gap))
            stack.setFixedHeight(int(h))
        except Exception:
            pass
        try:
            stack.move(int(margin), int(margin))
            stack.raise_()
            stack.show()
        except Exception:
            pass

        info = getattr(self, "info_overlay_main", None)
        try:
            if info is not None:
                info.setMaximumWidth(int(w))
                info.adjustSize()
                info.move(0, 0)
                info.raise_()
                info.show()
        except Exception as e:
            pass
        all_overlay = getattr(self, "all_info_overlay_main", None)
        expand_btn = getattr(self, "all_info_expand_btn", None)

        try:
            info_h = int(info.height()) if info is not None else 0
        except Exception:
            info_h = 0
        y_all = int(info_h) + int(gap)

        if bool(getattr(self, "_all_info_collapsed", False)):
            try:
                if all_overlay is not None:
                    all_overlay.hide()
            except Exception:
                pass
            try:
                if expand_btn is not None:
                    expand_btn.move(int(margin), int(margin + y_all))
                    expand_btn.show()
                    expand_btn.raise_()
            except Exception:
                pass
            return

        try:
            if expand_btn is not None:
                expand_btn.hide()
        except Exception:
            pass

        if all_overlay is None:
            print(f"[DEBUG] all_overlay is None")
            return
        html_content = str(getattr(all_overlay, "_html", "") or "").strip()
        try:
            if not html_content:
                print(f"[DEBUG] all_overlay hiding due to empty html")
                all_overlay.hide()
                return
            all_overlay.show()
        except Exception as e:
            print(f"[DEBUG] all_overlay show/hide exception: {e}")
            pass
        try:
            all_overlay.setFixedWidth(int(w))
        except Exception:
            pass
        try:
            y_abs = int(margin) + int(y_all)
            max_h = int(vp.height()) - int(y_abs) - int(gap)
        except Exception:
            max_h = 240
        if max_h < 80:
            max_h = 80
        try:
            all_overlay.setFixedHeight(int(max_h))
        except Exception:
            pass
        try:
            all_overlay.move(0, int(y_all))
            all_overlay.raise_()
        except Exception:
            pass

    def _update_all_info_html(self, html: str):
        """后台线程更新 all_info_overlay HTML 的槽方法"""
        try:
            all_overlay = getattr(self, "all_info_overlay_main", None)
            if all_overlay is not None:
                all_overlay.set_html(html)
        except Exception:
            pass

    def _set_all_info_collapsed(self, collapsed: bool, persist: bool = True):
        try:
            if bool(getattr(self, "compare_mode", False)):
                return
        except Exception:
            pass
        try:
            collapsed = bool(collapsed)
        except Exception:
            collapsed = False
        try:
            self._all_info_collapsed = bool(collapsed)
        except Exception:
            pass
        if persist:
            try:
                sm = getattr(self, "_settings_manager", None)
                if sm is None:
                    try:
                        sm = SettingsManager.instance()
                        self._settings_manager = sm
                    except Exception:
                        sm = None
                if sm is not None:
                    sm.set("image_detail/all_info_overlay_collapsed", bool(collapsed))
                    sm.sync()
            except Exception:
                pass

        all_overlay = getattr(self, "all_info_overlay_main", None)
        expand_btn = getattr(self, "all_info_expand_btn", None)
        if collapsed:
            try:
                if all_overlay is not None:
                    all_overlay.hide()
            except Exception:
                pass
            try:
                if expand_btn is not None:
                    expand_btn.show()
            except Exception:
                pass
        else:
            try:
                if expand_btn is not None:
                    expand_btn.hide()
            except Exception:
                pass
            try:
                if all_overlay is not None:
                    if str(getattr(all_overlay, "_html", "") or "").strip():
                        all_overlay.show()
            except Exception:
                pass
        try:
            self._update_main_info_stack_layout()
        except Exception:
            pass

    def _update_all_info_overlay_pos(self, view, info_overlay, all_info_overlay):
        if not view or all_info_overlay is None:
            return
        try:
            if not all_info_overlay.isVisible():
                return
        except Exception:
            return

        margin = 20
        gap = 8
        base_y = margin
        try:
            if info_overlay is not None and info_overlay.isVisible():
                try:
                    info_overlay.adjustSize()
                except Exception:
                    pass
                base_y = int(info_overlay.y()) + int(info_overlay.height()) + int(gap)
        except Exception:
            base_y = margin + 40

        try:
            max_w = max(240, int(view.width()) - int(margin * 2))
        except Exception:
            max_w = 320
        try:
            w = min(360, int(max_w))
            all_info_overlay.setFixedWidth(int(w))
        except Exception:
            pass
        try:
            max_h = max(80, int(view.height()) - int(base_y) - int(gap))
            all_info_overlay.setFixedHeight(int(max_h))
        except Exception:
            pass
        try:
            all_info_overlay.adjustSize()
            all_info_overlay.move(int(margin), int(max(margin, base_y)))
            all_info_overlay.raise_()
        except Exception:
            pass

    def _update_stash_icon_pos(self, view, icon_label, info_overlay=None):
        if not view or not icon_label:
            return
        try:
            icon_label.adjustSize()
        except Exception:
            pass
        margin = 20
        x = margin
        y = margin
        try:
            if info_overlay is not None and info_overlay.isVisible():
                y = margin + int(info_overlay.height()) + 8
        except Exception:
            pass
        try:
            icon_label.move(int(x), int(y))
            icon_label.raise_()
        except Exception:
            pass

    def update_nav_buttons_pos(self):
        mid_y = self.image_container.height() // 2 - 50
        self.btn_prev.move(10, mid_y)
        self.btn_next.move(self.image_container.width() - 70, mid_y)
        
        # 动态隐藏按钮
        self.btn_prev.setVisible(self.current_index > 0)
        self.btn_next.setVisible(self.current_index < len(self.image_list) - 1)

    def init_thumbnail_strip(self):
        cm = ColorManager.instance()
        strip_bg = cm.to_qss_color("image_detail.thumbnail_strip.background", default="#121212")
        sb_bg = cm.to_qss_color("image_detail.thumbnail_strip.scrollbar.background", default="#1C1C1C")
        sb_handle_bg = cm.to_qss_color("image_detail.thumbnail_strip.scrollbar.handle", default="#3A3A3A")
        border_top = cm.to_qss_color("image_detail.thumbnail_strip.border_top", default="#2A2A2A")

        class _StripItem:
            def __init__(self, index: int, info: dict):
                self.index = int(index)
                self.info = info or {}
                self.path = str((self.info.get("path") if isinstance(self.info, dict) else "") or "")
                self.image = None
                self.selected = False

        class _StripModel(QAbstractListModel):
            INFO_ROLE = int(Qt.ItemDataRole.UserRole) + 1
            IMAGE_ROLE = int(Qt.ItemDataRole.UserRole) + 2
            INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 3
            PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 4
            SELECTED_ROLE = int(Qt.ItemDataRole.UserRole) + 5

            def __init__(self, parent=None):
                super().__init__(parent)
                self._items = []
                self._selected_row = -1

            def rowCount(self, parent=QModelIndex()):
                if parent.isValid():
                    return 0
                return len(self._items)

            def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
                if not index.isValid():
                    return None
                row = int(index.row())
                if row < 0 or row >= len(self._items):
                    return None
                it = self._items[row]
                if role == int(Qt.ItemDataRole.DisplayRole):
                    return it.path
                if role == self.INFO_ROLE:
                    return it.info
                if role == self.IMAGE_ROLE:
                    return it.image
                if role == self.INDEX_ROLE:
                    return it.index
                if role == self.PATH_ROLE:
                    return it.path
                if role == self.SELECTED_ROLE:
                    return bool(it.selected)
                return None

            def flags(self, index: QModelIndex):
                if not index.isValid():
                    return Qt.ItemFlag.NoItemFlags
                return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

            def reset_items(self, items):
                self.beginResetModel()
                self._items = list(items or [])
                self.endResetModel()

            def set_selected_index(self, idx: int):
                try:
                    idx = int(idx)
                except Exception:
                    idx = -1
                try:
                    old_row = int(getattr(self, "_selected_row", -1))
                except Exception:
                    old_row = -1
                new_row = -1
                try:
                    if 0 <= idx < len(self._items) and int(self._items[idx].index) == int(idx):
                        new_row = int(idx)
                except Exception:
                    new_row = -1
                if new_row < 0:
                    for row, it in enumerate(self._items):
                        if int(it.index) == int(idx):
                            new_row = int(row)
                            break

                if 0 <= old_row < len(self._items):
                    try:
                        self._items[old_row].selected = False
                    except Exception:
                        pass
                if 0 <= new_row < len(self._items):
                    try:
                        self._items[new_row].selected = True
                    except Exception:
                        pass
                try:
                    self._selected_row = int(new_row)
                except Exception:
                    self._selected_row = -1

                try:
                    if 0 <= old_row < len(self._items):
                        a = self.index(old_row, 0)
                        self.dataChanged.emit(a, a, [])
                    if 0 <= new_row < len(self._items):
                        b = self.index(new_row, 0)
                        self.dataChanged.emit(b, b, [])
                except Exception:
                    pass

            def set_image_for_path(self, path: str, qimg: QImage):
                if not path:
                    return []
                updated = []
                for row, it in enumerate(self._items):
                    if it.path == path:
                        it.image = qimg
                        updated.append(row)
                return updated

            def clear_images_outside(self, keep_start: int, keep_end: int):
                try:
                    keep_start = int(keep_start)
                    keep_end = int(keep_end)
                except Exception:
                    return []
                if keep_end < keep_start:
                    return []
                cleared = []
                for row, it in enumerate(self._items):
                    if row < keep_start or row > keep_end:
                        if it.image is not None:
                            it.image = None
                            cleared.append((int(row), str(it.path or "")))
                return cleared

        class _StripDelegate(QStyledItemDelegate):
            def paint(self, painter: QPainter, option, index: QModelIndex):
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

                rect = option.rect
                painter.fillRect(rect, QColor(strip_bg))
                selected = bool(index.data(_StripModel.SELECTED_ROLE))
                if selected:
                    try:
                        sel_bg = QColor(cm.get("theme.primary"))
                        sel_bg.setAlphaF(0.28)
                        painter.fillRect(rect.adjusted(2, 2, -2, -2), sel_bg)
                    except Exception:
                        pass

                img = index.data(_StripModel.IMAGE_ROLE)
                if img is not None and not (hasattr(img, "isNull") and img.isNull()):
                    try:
                        iw = int(img.width())
                        ih = int(img.height())
                    except Exception:
                        iw = 0
                        ih = 0
                    inner = rect.adjusted(4, 4, -4, -4)
                    if iw > 0 and ih > 0 and inner.width() > 0 and inner.height() > 0:
                        ratio = min(inner.width() / iw, inner.height() / ih)
                        nw = max(1, int(iw * ratio))
                        nh = max(1, int(ih * ratio))
                        target = QRectF(inner.x() + (inner.width() - nw) // 2, inner.y() + (inner.height() - nh) // 2, nw, nh)
                        painter.drawImage(target, img)
                    else:
                        painter.drawImage(inner, img)

                try:
                    info = index.data(_StripModel.INFO_ROLE)
                except Exception:
                    info = None
                try:
                    is_stashed = bool(info.get("is_stashed")) if isinstance(info, dict) else False
                except Exception:
                    is_stashed = False
                try:
                    ImageThumbnail._ensure_icons_loaded()
                except Exception:
                    pass
                if is_stashed and getattr(ImageThumbnail, "_shared_stash_icon", None) is not None:
                    try:
                        stash_size = 14
                        x = rect.left() + 6
                        y = rect.top() + 6
                        shadow_rect = QRect(x + 1, y + 1, stash_size, stash_size)
                        ImageThumbnail._shared_stash_shadow_icon.paint(painter, shadow_rect)
                        icon_rect = QRect(x, y, stash_size, stash_size)
                        ImageThumbnail._shared_stash_icon.paint(painter, icon_rect)
                    except Exception:
                        pass
                painter.restore()

            def sizeHint(self, option, index: QModelIndex):
                return QSize(132, 132)

        self.thumbnail_scroll = QListView()
        self.thumbnail_scroll.setFixedHeight(140)
        self.thumbnail_scroll.setViewMode(QListView.ViewMode.IconMode)
        self.thumbnail_scroll.setFlow(QListView.Flow.LeftToRight)
        self.thumbnail_scroll.setWrapping(False)
        self.thumbnail_scroll.setMovement(QListView.Movement.Static)
        self.thumbnail_scroll.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbnail_scroll.setSpacing(0)
        self.thumbnail_scroll.setUniformItemSizes(True)
        self.thumbnail_scroll.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.thumbnail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thumbnail_scroll.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.thumbnail_scroll.setStyleSheet(f"""
            QListView {{
                border: none;
                background-color: {strip_bg};
                outline: none;
                border-top: 1px solid {border_top};
            }}
            QScrollBar:horizontal {{
                height: 10px;
                background: {sb_bg};
            }}
            QScrollBar::handle:horizontal {{
                background: {sb_handle_bg};
                border-radius: 5px;
            }}
        """)

        self._strip_model = _StripModel(self)
        self._strip_item_cls = _StripItem
        self._strip_model_cls = _StripModel
        self._strip_delegate = _StripDelegate(self.thumbnail_scroll)
        self.thumbnail_scroll.setModel(self._strip_model)
        self.thumbnail_scroll.setItemDelegate(self._strip_delegate)
        self.thumbnail_scroll.clicked.connect(self._on_strip_clicked)
        try:
            self.thumbnail_scroll.horizontalScrollBar().valueChanged.connect(self._on_strip_scrolled)
        except Exception:
            pass

        self._strip_thumb_loader = ThumbnailLoader(self.cache_manager)
        self._strip_thumb_loader.signals.loaded.connect(self._on_strip_thumbnail_loaded)
        self._strip_thumb_request_id = 1
        self._strip_thumb_timer = QTimer(self)
        self._strip_thumb_timer.setSingleShot(True)
        self._strip_thumb_timer.timeout.connect(self._load_strip_visible_thumbnails)

        QTimer.singleShot(0, self.populate_thumbnails)
        self.main_layout.addWidget(self.thumbnail_scroll)

    def _on_strip_clicked(self, model_index: QModelIndex):
        if not model_index.isValid():
            return
        idx = int(model_index.row())
        modifiers = QApplication.keyboardModifiers()
        self.on_thumbnail_clicked_proxy(idx, modifiers)

    def _on_strip_scrolled(self, value):
        try:
            if self._strip_thumb_timer.isActive():
                self._strip_thumb_timer.stop()
            self._strip_thumb_timer.start(20)
        except Exception:
            pass

    def _load_strip_visible_thumbnails(self):
        if not hasattr(self, "_strip_model") or self._strip_model is None:
            return
        total = int(self._strip_model.rowCount())
        if total <= 0:
            return
        view = self.thumbnail_scroll
        try:
            w = int(view.viewport().width())
        except Exception:
            w = 0
        try:
            mid_y = max(1, int(view.viewport().height()) // 2)
        except Exception:
            mid_y = 2
        left = view.indexAt(QPoint(2, int(mid_y)))
        right = view.indexAt(QPoint(max(2, w - 2), int(mid_y)))
        try:
            start = int(left.row()) if left.isValid() else 0
        except Exception:
            start = 0
        try:
            end = int(right.row()) if right.isValid() else min(total - 1, start + 40)
        except Exception:
            end = min(total - 1, start + 40)
        if end < start:
            end = start
        pre = 60
        start = max(0, start - pre)
        end = min(total - 1, end + pre)
        try:
            cleared = self._strip_model.clear_images_outside(int(start), int(end))
            for r in cleared:
                try:
                    row = int(r[0]) if isinstance(r, (list, tuple)) and len(r) >= 1 else int(r)
                    mi = self._strip_model.index(int(row), 0)
                    self._strip_model.dataChanged.emit(mi, mi, [])
                except Exception:
                    pass
        except Exception:
            pass
        tasks = []
        for i in range(start, end + 1):
            mi = self._strip_model.index(i, 0)
            try:
                p = str(mi.data(self._strip_model_cls.PATH_ROLE) or "")
            except Exception:
                p = ""
            if not p:
                continue
            img = None
            try:
                img = mi.data(self._strip_model_cls.IMAGE_ROLE)
            except Exception:
                img = None
            if img is not None and not (hasattr(img, "isNull") and img.isNull()):
                continue
            tasks.append((0 if abs(i - int(getattr(self, "current_index", 0))) <= 4 else 3, p, abs(i - int(getattr(self, "current_index", 0))) <= 4))
        if tasks:
            self._strip_thumb_request_id += 1
            self._strip_thumb_loader.set_active_request_id(self._strip_thumb_request_id)
            self._strip_thumb_loader.load_thumbnails(tasks, 104, request_id=self._strip_thumb_request_id)

    def _on_strip_thumbnail_loaded(self, path, image):
        if image is None:
            return
        try:
            rows = self._strip_model.set_image_for_path(str(path), image)
        except Exception:
            rows = []
        for r in rows:
            try:
                mi = self._strip_model.index(int(r), 0)
                self._strip_model.dataChanged.emit(mi, mi, [])
            except Exception:
                pass

    def populate_thumbnails(self):
        items = []
        for i, info in enumerate(self.image_list or []):
            try:
                it_cls = getattr(self, "_strip_item_cls", None)
            except Exception:
                it_cls = None
            if it_cls is None:
                break
            items.append(it_cls(i, info if isinstance(info, dict) else {"path": "", "name": ""}))
        try:
            self._strip_model.reset_items(items)
        except Exception:
            pass
        self.update_thumbnail_selection()
        try:
            pass
        except Exception:
            pass
        try:
            if self._strip_thumb_timer.isActive():
                self._strip_thumb_timer.stop()
            self._strip_thumb_timer.start(0)
        except Exception:
            pass

    def on_thumbnail_clicked_proxy(self, index, modifiers):
        # 处理对比模式下的 Ctrl+点击：切换左侧图片
        if self.compare_mode and (modifiers & Qt.KeyboardModifier.ControlModifier):
            if index == self.current_index:
                try:
                    NotificationManager.instance().show_toast("对比模式下左右不能是同一张图片")
                except Exception:
                    pass
                self.update_thumbnail_selection(center_index=index)
                return
            self.saved_left_index = index
            self._clear_subject_rect()
            self._clear_focus_point()
            self.load_left_image(index)
            self._prefetch_compare_subject_state()
            # 发送左侧图片选中信号
            self.left_image_selected.emit(index)
            
            # 重置右侧图片的缩放和位置
            if self.pixmap_item_right.pixmap() and not self.pixmap_item_right.pixmap().isNull():
                self._fit_view(self.view_right, self.pixmap_item_right)
            
            # 提示
            try:
                from ui.utils.notification_manager import NotificationManager
            except:
                pass
                
            # 居中显示点击的缩略图，但不改变选中状态（选中状态跟随 current_index，即右侧图片）
            self.update_thumbnail_selection(center_index=index)
            return

        if self.compare_mode and index == getattr(self, "saved_left_index", None):
            try:
                NotificationManager.instance().show_toast("对比模式下左右不能是同一张图片")
            except Exception:
                pass
            self.update_thumbnail_selection(center_index=index)
            return

        self.current_index = index
        if self.compare_mode:
            self._clear_subject_rect()
            self._clear_focus_point()
        self.load_current_image()
        self.update_thumbnail_selection()
        try:
            v = None
            if self.compare_mode:
                v = self.view_right
            else:
                v = self.view
            if v:
                v.setFocus()
        except Exception:
            pass

    def _update_detail_shortcut_keys(self):
        sm = ShortcutManager.instance()
        try:
            if getattr(self, "_detail_prev_shortcut", None) is not None:
                self._detail_prev_shortcut.setKey(sm.get_sequence("ImageDetail.PrevImage"))
        except Exception:
            pass
        try:
            if getattr(self, "_detail_next_shortcut", None) is not None:
                self._detail_next_shortcut.setKey(sm.get_sequence("ImageDetail.NextImage"))
        except Exception:
            pass
        try:
            if getattr(self, "_detail_close_shortcut", None) is not None:
                self._detail_close_shortcut.setKey(sm.get_sequence("ImageDetail.Close"))
        except Exception:
            pass
        try:
            if getattr(self, "_detail_toggle_subject_rect_shortcut", None) is not None:
                self._detail_toggle_subject_rect_shortcut.setKey(sm.get_sequence("ImageDetail.ToggleSubjectRect"))
        except Exception:
            pass
        try:
            if getattr(self, "_detail_delete_shortcut", None) is not None:
                self._detail_delete_shortcut.setKey(sm.get_sequence("ImageDetail.Delete"))
        except Exception:
            pass

    def update_thumbnail_selection(self, center_index=None):
        try:
            self._strip_model.set_selected_index(int(self.current_index))
        except Exception:
            pass
        target_idx = center_index if center_index is not None else self.current_index
        try:
            target_idx = int(target_idx)
        except Exception:
            target_idx = -1
        if hasattr(self, "thumbnail_scroll") and self.thumbnail_scroll is not None and 0 <= target_idx < int(self._strip_model.rowCount()):
            try:
                mi = self._strip_model.index(int(target_idx), 0)
                self.thumbnail_scroll.scrollTo(mi, QListView.ScrollHint.PositionAtCenter)
            except Exception:
                pass
            try:
                if self._strip_thumb_timer.isActive():
                    self._strip_thumb_timer.stop()
                self._strip_thumb_timer.start(0)
            except Exception:
                pass

    def init_toolbar(self):
        toolbar = QFrame()
        toolbar.setFixedHeight(50)
        cm = ColorManager.instance()
        toolbar_bg = cm.to_qss_color("image_detail.toolbar.background", default="#333333")
        toolbar.setStyleSheet(f"background-color: {toolbar_bg};")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(15)
        
        tool_btn_hover_bg = cm.to_qss_color("image_detail.toolbar.button.hover_background", default="#FFFFFF1E")
        tool_btn_pressed_bg = cm.to_qss_color("image_detail.toolbar.button.pressed_background", default="#FFFFFF32")
        tooltip_text = cm.get("tooltip.text")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_border = cm.get("tooltip.border")
        
        # 定义工具栏按钮
        def create_tool_btn(icon_name, tooltip, slot):
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color='white'))
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(36, 36)
            btn.setToolTip(tooltip)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(f"""
                QPushButton {{ background-color: transparent; border: none; border-radius: 4px; }}
                QPushButton:hover {{ background-color: {tool_btn_hover_bg}; }}
                QPushButton:pressed {{ background-color: {tool_btn_pressed_bg}; }}
                QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
            """)
            btn.clicked.connect(slot)
            return btn

        def create_toggle_btn(icon_name, tooltip, toggled_slot):
            btn = QPushButton()
            btn.setIcon(qta.icon(icon_name, color='white'))
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(36, 36)
            btn.setToolTip(tooltip)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCheckable(True)
            btn.setChecked(False)
            self._apply_toolbar_toggle_button_style(btn, active=False)
            btn.toggled.connect(toggled_slot)
            return btn
            
        # 缩小
        layout.addWidget(create_tool_btn('mdi6.minus', "缩小", self.zoom_out))
        
        # 比例文本
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setStyleSheet("color: white; font-weight: bold;")
        self.lbl_zoom.setFixedWidth(50)
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_zoom)
        
        # 放大
        layout.addWidget(create_tool_btn('mdi6.plus', "放大", self.zoom_in))
        
        # 旋转
        layout.addWidget(create_tool_btn('mdi6.rotate-right', "旋转", self.rotate_image))
        
        layout.addSpacing(20)
        
        # 放大镜
        layout.addWidget(create_tool_btn('mdi6.magnify', "放大镜", self.toggle_magnifier))
        
        # 对比模式
        self.btn_compare = create_tool_btn('mdi6.compare', "对比模式", self.toggle_compare_mode)
        layout.addWidget(self.btn_compare)
        
        self.btn_detect_subject = create_tool_btn('fa5s.crosshairs', "检测主体", self.on_detect_subject_clicked)
        layout.addWidget(self.btn_detect_subject)
        
        self.btn_show_subject_rect = create_toggle_btn('ph.frame-corners', "显示主体框", self._on_subject_rect_display_toggled)
        layout.addWidget(self.btn_show_subject_rect)
        try:
            self.btn_show_subject_rect.blockSignals(True)
            self.btn_show_subject_rect.setChecked(bool(getattr(self, "_subject_rect_display_enabled", False)))
        finally:
            try:
                self.btn_show_subject_rect.blockSignals(False)
            except Exception:
                pass
        try:
            self._apply_toolbar_toggle_button_style(self.btn_show_subject_rect, active=bool(self.btn_show_subject_rect.isChecked()))
        except Exception:
            pass

        # 聚焦主体
        self.btn_zoom_to_bird = create_tool_btn('fa6s.object-group', "聚焦主体", self.zoom_to_bird)
        layout.addWidget(self.btn_zoom_to_bird)
        
        self.btn_zoom_to_focus = create_toggle_btn('mdi6.focus-field', "显示对焦点", self._on_focus_point_display_toggled)
        layout.addWidget(self.btn_zoom_to_focus)
        try:
            self.btn_zoom_to_focus.blockSignals(True)
            self.btn_zoom_to_focus.setChecked(bool(getattr(self, "_focus_point_display_enabled", False)))
        finally:
            try:
                self.btn_zoom_to_focus.blockSignals(False)
            except Exception:
                pass
        try:
            self._apply_toolbar_toggle_button_style(self.btn_zoom_to_focus, active=bool(self.btn_zoom_to_focus.isChecked()))
        except Exception:
            pass

        # 删除按钮
        self.btn_delete = QPushButton()
        self.btn_delete.setIcon(qta.icon('mdi6.trash-can-outline', color='#e74c3c'))
        self.btn_delete.setIconSize(QSize(24, 24))
        self.btn_delete.setFixedSize(36, 36)
        self.btn_delete.setToolTip(f"删除 ({ShortcutManager.instance().get_sequence('ImageDetail.Delete').toString()})")
        self.btn_delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background-color: #ffcccc; }}
            QPushButton:pressed {{ background-color: #ff9999; }}
            QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
        """)
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self.btn_delete)

        if self._show_stash_controls:
            self.btn_stash = QPushButton()
            self.btn_stash.setCheckable(True)
            self.btn_stash.setIconSize(QSize(20, 20))
            self.btn_stash.setFixedSize(36, 36)
            self.btn_stash.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.btn_stash.clicked.connect(self._on_stash_clicked)
            self._apply_stash_button_style()
            layout.addWidget(self.btn_stash)
        
        layout.addStretch()
        
        if self._show_import_to_library_button:
            layout.addWidget(create_tool_btn('mdi6.database-import', "导入图库", self.on_import_to_library_clicked))

        # 打开
        layout.addWidget(create_tool_btn('mdi6.open-in-new', "外部打开", self.open_external))

        self.main_layout.addWidget(toolbar)

    def on_import_to_library_clicked(self):
        paths = []
        try:
            if self.image_list and 0 <= int(self.current_index) < len(self.image_list):
                p = self.image_list[int(self.current_index)].get("path")
                if p:
                    paths.append(str(p))
        except Exception:
            paths = []
        try:
            if bool(getattr(self, "compare_mode", False)):
                li = getattr(self, "saved_left_index", None)
                if li is not None and 0 <= int(li) < len(self.image_list):
                    lp = self.image_list[int(li)].get("path")
                    if lp:
                        lp = str(lp)
                        if lp not in paths:
                            paths.append(lp)
        except Exception:
            pass
        if paths:
            self.import_to_library_requested.emit(paths)

    def load_current_image(self):
        self._is_zoomed_to_bird = False
        if not self.image_list or self.current_index < 0 or self.current_index >= len(self.image_list):
            return
            
        img_info = self.image_list[self.current_index]
        path = img_info['path']
        
        # 获取完整 DB 信息（为了收藏和评星状态）
        try:
            record = self._get_record_for_path(path)
            if record:
                # 将数据库信息合并到 img_info 或更新特定字段
                if record.get("uuid"):
                    img_info["uuid"] = record.get("uuid")
                img_info['rating'] = record.get('rating', 0)
                # 使用数据库中的 is_favorite，映射到两个键以保持兼容性
                is_fav = record.get('is_favorite', 0)
                img_info['favorite'] = is_fav
                img_info['is_favorite'] = is_fav
                
                # 更新 bbox 和 focus_point 到 img_info，以便按钮状态判断
                if 'bbox' in record:
                    img_info['bbox'] = record['bbox']
                if 'focus_point' in record:
                    img_info['focus_point'] = record['focus_point']
                if 'eye_coordinates' in record:
                    img_info['eye_coordinates'] = record['eye_coordinates']
                if 'focus_detect_json' in record:
                    img_info['focus_detect_json'] = record['focus_detect_json']
                    
        except Exception as e:
            try:
                LogManager.instance().warning(f"加载数据库信息失败 {path}: {e}")
            except Exception:
                pass

        # 发送信号通知外部更新 InfoPanel
        self.image_changed.emit(path)
        try:
            if not bool(getattr(self, "compare_mode", False)):
                self._update_overlay_data(path, getattr(self, "overlay_main", None), getattr(self, "info_overlay_main", None))
                try:
                    if getattr(self, "info_overlay_main", None) is not None:
                        self.info_overlay_main.raise_()
                except Exception:
                    pass
                try:
                    def _relayout_overlays():
                        try:
                            self._update_main_info_stack_layout()
                        except Exception:
                            pass
                    QTimer.singleShot(0, _relayout_overlays)
                    QTimer.singleShot(60, _relayout_overlays)
                except Exception:
                    pass
        except Exception:
            pass
        
        # 更新按钮状态
        self.update_nav_buttons_pos()
        
        # 更新功能按钮状态 (聚焦主体/显示对焦点)
        has_bbox = False
        if img_info.get('bbox'):
             # bbox 可能是 JSON 字符串或列表，这里简单判断非空
             has_bbox = True
             
        has_focus = False
        if img_info.get('focus_point'):
            has_focus = True
            
        if hasattr(self, 'btn_zoom_to_bird'):
            if self.compare_mode:
                self._prefetch_compare_subject_state()
            else:
                self.btn_zoom_to_bird.setEnabled(has_bbox)
        try:
            if hasattr(self, "btn_show_subject_rect") and self.btn_show_subject_rect is not None:
                self.btn_show_subject_rect.setEnabled(True)
        except Exception:
            pass
        if hasattr(self, 'btn_zoom_to_focus'):
            try:
                if self.compare_mode:
                    self._prefetch_compare_subject_state()
                else:
                    self.btn_zoom_to_focus.setEnabled(True)
            except Exception:
                pass
        
        # 更新收藏和评星状态
        self.update_fav_rating_status()
        try:
            self._update_stash_ui()
        except Exception:
            pass
        
        # 停止旧线程
        if self.loader_thread and self.loader_thread.isRunning():
            try:
                self._pending_load_index = int(self.current_index)
            except Exception:
                self._pending_load_index = None
            return

        try:
            cached = self.big_image_cache.get(path)
        except Exception:
            cached = None
        if cached is not None and not cached.isNull():
            try:
                need_edge = int(getattr(self, "_detail_decode_max_edge", 2560) or 2560)
            except Exception:
                need_edge = 2560
            try:
                cw = int(cached.width())
                ch = int(cached.height())
                cached_long = int(max(cw, ch))
            except Exception:
                cached_long = 0
            if cached_long > 0 and need_edge > 0 and cached_long < int(need_edge):
                try:
                    orig = self._get_orig_size_for_path(path)
                except Exception:
                    orig = None
                if orig is not None:
                    try:
                        ow, oh = orig
                        orig_long = int(max(int(ow), int(oh)))
                    except Exception:
                        orig_long = 0
                    if orig_long > cached_long and orig_long >= int(need_edge):
                        cached = None
        if cached is not None and not cached.isNull():
            try:
                self.on_image_loaded(cached, path)
            except Exception:
                pass
            try:
                self._schedule_preload_big_neighbors_detail()
            except Exception:
                pass
            return
            
        # 启动新线程加载
        self.loader_thread = _track_loader_thread(ImageLoaderThread(path, max_edge=int(getattr(self, "_detail_decode_max_edge", 2560) or 2560)))
        self.loader_thread.image_loaded.connect(self.on_image_loaded)
        try:
            self.loader_thread.finished.connect(self._on_loader_finished)
        except Exception:
            pass
        self.loader_thread.start()
        try:
            self._schedule_preload_big_neighbors_detail()
        except Exception:
            pass

    def _on_loader_finished(self):
        try:
            self.loader_thread = None
        except Exception:
            self.loader_thread = None
        pending = getattr(self, "_pending_load_index", None)
        try:
            self._pending_load_index = None
        except Exception:
            pass
        if pending is None:
            return
        try:
            pending = int(pending)
        except Exception:
            return
        if pending < 0 or pending >= len(self.image_list):
            return
        try:
            self.current_index = pending
        except Exception:
            return
        try:
            self.load_current_image()
        except Exception:
            pass

    def _preload_big_neighbors_detail(self):
        if not self.image_list:
            return
        try:
            if str(getattr(self, "_big_cache_context", "")).strip().lower() == "import":
                return
        except Exception:
            pass
        try:
            i = int(self.current_index)
        except Exception:
            return
        cand = [i - 1, i + 1]
        paths = []
        for j in cand:
            try:
                j = int(j)
            except Exception:
                continue
            if j < 0 or j >= len(self.image_list) or j == i:
                continue
            try:
                p = self.image_list[j].get("path") if isinstance(self.image_list[j], dict) else None
            except Exception:
                p = None
            if p:
                paths.append(str(p))
        if paths:
            self.big_image_cache.preload(paths)

    def _schedule_preload_big_neighbors_detail(self):
        try:
            if str(getattr(self, "_big_cache_context", "")).strip().lower() == "import":
                return
        except Exception:
            return
        try:
            t = getattr(self, "_neighbors_preload_timer", None)
        except Exception:
            t = None
        if t is None:
            return
        try:
            if t.isActive():
                t.stop()
            t.start(120)
        except Exception:
            pass

    def _schedule_deferred_big_image_load(self, index: int, delay_ms: int = 140):
        try:
            if str(getattr(self, "_big_cache_context", "")).strip().lower() != "library":
                return False
        except Exception:
            return False
        try:
            index = int(index)
        except Exception:
            return False
        if not self.image_list or index < 0 or index >= len(self.image_list):
            return False
        try:
            self._deferred_load_index = int(index)
        except Exception:
            self._deferred_load_index = None
            return False
        try:
            if self._deferred_load_timer.isActive():
                self._deferred_load_timer.stop()
            self._deferred_load_timer.start(max(0, int(delay_ms)))
        except Exception:
            pass
        return True

    def _flush_deferred_big_image_load(self):
        try:
            idx = getattr(self, "_deferred_load_index", None)
        except Exception:
            idx = None
        try:
            self._deferred_load_index = None
        except Exception:
            pass
        if idx is None:
            return
        try:
            idx = int(idx)
        except Exception:
            return
        if not self.image_list or idx < 0 or idx >= len(self.image_list):
            return
        if int(getattr(self, "current_index", -1)) != idx:
            return
        self.load_current_image()
        self.update_thumbnail_selection()
        self.update_nav_buttons_pos()

    def on_detect_subject_clicked(self):
        modifiers = QApplication.keyboardModifiers()
        force = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        self.detect_subject(force=force)

    # 移除 update_info_bar
    # def update_info_bar(self, img_info): ...

    def format_file_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def on_image_loaded(self, qimg, path):
        # 确认是当前需要的图片
        if self.current_index < len(self.image_list) and self.image_list[self.current_index]['path'] == path:
            try:
                if qimg is not None and not qimg.isNull():
                    self.big_image_cache.put(path, qimg)
            except Exception:
                pass
            pixmap = QPixmap.fromImage(qimg)
            
            # 始终更新主视图 item (确保切换回单图模式时内容正确)
            self.pixmap_item.setPixmap(pixmap)
            self.pixmap_item.setPos(0, 0)
            self.scene.setSceneRect(self.pixmap_item.boundingRect())
            
            if self.compare_mode:
                # 对比模式：更新右侧视图
                self.pixmap_item_right.setPixmap(pixmap)
                self.pixmap_item_right.setPos(0, 0)
                self._clear_subject_rect_side("right")
                self._clear_focus_point_side("right")
                self._fit_view(self.view_right, self.pixmap_item_right)
                try:
                    QTimer.singleShot(0, self._refresh_subject_rect_overlay)
                    QTimer.singleShot(0, self._refresh_focus_point_overlay)
                except Exception:
                    pass
                
                self._update_overlay_data(path, self.overlay_right, self.info_overlay_right)
                
                # 延迟强制更新位置，确保布局完成后位置正确
                QTimer.singleShot(50, lambda: self._update_overlay_pos(self.view_right.viewport(), self.overlay_right, is_info=False))
                QTimer.singleShot(50, lambda: self._update_overlay_pos(self.view_right.viewport(), self.info_overlay_right, is_info=True))
                
                # 当右侧图片切换时，左侧图片也恢复一开始的位置和缩放
                if self.pixmap_item_left.pixmap() and not self.pixmap_item_left.pixmap().isNull():
                    self._fit_view(self.view_left, self.pixmap_item_left)
                try:
                    # 保持当前的缩放比例，不重置
                    for view in self._get_active_views():
                        view.scale(float(self.zoom_scale), float(self.zoom_scale))
                        if hasattr(view, "horizontalScrollBar"):
                            view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                            view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
                except Exception:
                    pass
                try:
                    self.update_zoom_label()
                except Exception:
                    pass
                try:
                    if hasattr(self, "splitter") and self.splitter is not None:
                        QTimer.singleShot(0, lambda: self.splitter.setSizes([max(1, int(self.splitter.width() // 2)), max(1, int(self.splitter.width() // 2))]))
                except Exception:
                    pass
            else:
                # 单图模式：更新主视图
                self.rotation_angle = 0
                self._clear_subject_rect()
                # 保持当前的缩放比例，不重置
                self._apply_zoom_scale()
                try:
                    QTimer.singleShot(0, self._refresh_subject_rect_overlay)
                    QTimer.singleShot(0, self._refresh_focus_point_overlay)
                except Exception:
                    pass
                
                # 更新主 Overlay
                self._update_overlay_data(path, self.overlay_main, self.info_overlay_main)
                # 强制置顶并延迟更新位置
                try:
                    if hasattr(self, "overlay_main") and self.overlay_main:
                        self.overlay_main.raise_()
                except Exception:
                    pass
                self.info_overlay_main.raise_()
                QTimer.singleShot(50, lambda: self._update_overlay_pos(self.view.viewport(), self.overlay_main, is_info=False))
                QTimer.singleShot(50, self._update_main_info_stack_layout)
            
            # 更新收藏状态
            self.update_fav_rating_status()

            # 更新缓存（利用加载好的大图生成正确的缩略图）
            try:
                cache_mgr = getattr(self, "cache_manager", None) or ImageCacheManager.instance()
                thumb_size = cache_mgr.cache_thumbnail_size
                disable_scaling = False
                try:
                    if hasattr(cache_mgr, "settings_manager"):
                        disable_scaling = bool(cache_mgr.settings_manager.get("performance/thumbnail_disable_scaling", False))
                except Exception:
                    disable_scaling = False
                scale_quality = "low"
                try:
                    if hasattr(cache_mgr, "get_scale_quality"):
                        scale_quality = str(cache_mgr.get_scale_quality()).lower()
                    elif hasattr(cache_mgr, "settings_manager"):
                        scale_quality = str(cache_mgr.settings_manager.get("performance/thumbnail_scale_quality", "low")).lower()
                except Exception:
                    scale_quality = "low"
                transformation_mode = Qt.TransformationMode.SmoothTransformation if scale_quality == "high" else Qt.TransformationMode.FastTransformation
                if disable_scaling:
                    transformation_mode = Qt.TransformationMode.FastTransformation
                scaled = GPUScaler.scale_qimage(
                    qimg,
                    thumb_size,
                    thumb_size,
                    keep_aspect=True,
                    fast_mode=transformation_mode == Qt.TransformationMode.FastTransformation
                )
                thumb = scaled if scaled is not None else qimg.scaled(
                    thumb_size,
                    thumb_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    transformation_mode
                )
                
                # 更新内存缓存
                cache_mgr.put(path, thumb)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"从详情页更新缩略图缓存失败: {e}")
                except Exception:
                    pass

    def _fit_view(self, view, item):
        """辅助方法：将 item 适应 view"""
        if item.pixmap() and not item.pixmap().isNull():
            self._is_syncing_scroll = True
            try:
                view.scene().setSceneRect(item.boundingRect())
                view.resetTransform()
                
                view_rect = view.viewport().rect()
                scene_rect = item.boundingRect()
                
                if scene_rect.width() > 0 and scene_rect.height() > 0:
                    factor_w = view_rect.width() / scene_rect.width()
                    factor_h = view_rect.height() / scene_rect.height()
                    scale = min(factor_w, factor_h)
                    view.scale(scale, scale)
                    view.centerOn(item)
                    
                    # 更新 last_value，防止后续同步跳变
                    if hasattr(view, "horizontalScrollBar"):
                        view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                        view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
            finally:
                self._is_syncing_scroll = False

    def _apply_zoom_scale(self):
        """应用当前的缩放比例到视图"""
        try:
            # 先适应窗口，然后再应用缩放
            self._fit_view(self.view, self.pixmap_item)
            # 应用当前的缩放比例
            for view in self._get_active_views():
                view.scale(float(self.zoom_scale), float(self.zoom_scale))
            self.update_zoom_label()
        except Exception:
            pass

    def fit_image_to_view(self):
        # 重置 zoom_scale 为 1.0 (适应窗口)
        self.zoom_scale = 1.0

        if self.compare_mode:
            self._fit_view(self.view_left, self.pixmap_item_left)
            self._fit_view(self.view_right, self.pixmap_item_right)
            # 在 fit_view 中已经缩放到了适应窗口，此时 zoom_scale 应该视为 1.0
            # 所以不需要再 scale(self.zoom_scale) 了，或者说 scale(1.0) 是多余的
            # 但为了保持逻辑一致性，我们可以重置 view 的 transform 为 fit 状态
            
            try:
                for view in self._get_active_views():
                    # 关键修复：不要在 fit 之后再次叠加缩放
                    # _fit_view 已经计算并应用了适应窗口的变换矩阵
                    # 如果再次 scale(1.0)，虽然理论上无影响，但如果之前有残留的 transform 可能会有问题
                    # 这里确保逻辑是：fit = 100% 缩放比例
                    
                    if hasattr(view, "horizontalScrollBar"):
                        view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                        view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
            except Exception:
                pass
            self.update_zoom_label()
        else:
            if self.pixmap_item.pixmap():
                # 复用 _fit_view 逻辑，同时更新 zoom_scale
                self._fit_view(self.view, self.pixmap_item)
                try:
                    for view in self._get_active_views():
                        if hasattr(view, "horizontalScrollBar"):
                            view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                            view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
                except Exception:
                    pass
                self.update_zoom_label()

    def show_prev_image(self):
        if self.current_index > 0:
            # 保存大浮层的滚动位置
            self._save_all_info_scroll_pos()
            self.current_index -= 1
            self.load_current_image()
            self.update_thumbnail_selection()
            self.update_nav_buttons_pos()

    def show_next_image(self):
        if self.current_index < len(self.image_list) - 1:
            # 保存大浮层的滚动位置
            self._save_all_info_scroll_pos()
            self.current_index += 1
            self.load_current_image()
            self.update_thumbnail_selection()
            self.update_nav_buttons_pos()

    def _save_all_info_scroll_pos(self):
        """保存大浮层的滚动位置"""
        try:
            all_overlay = getattr(self, "all_info_overlay_main", None)
            if all_overlay is not None and hasattr(all_overlay, "scroll_area"):
                scrollbar = all_overlay.scroll_area.verticalScrollBar()
                if scrollbar:
                    self._saved_scroll_value = scrollbar.value()
                    self._saved_scroll_max = scrollbar.maximum()
                    print(f"[DEBUG] Saved scroll: value={self._saved_scroll_value}, max={self._saved_scroll_max}")
        except Exception as e:
            print(f"[DEBUG] Save scroll error: {e}")

    def _restore_all_info_scroll_pos(self):
        """恢复大浮层的滚动位置"""
        try:
            if hasattr(self, "_saved_scroll_value") and hasattr(self, "_saved_scroll_max"):
                all_overlay = getattr(self, "all_info_overlay_main", None)
                if all_overlay is not None and hasattr(all_overlay, "scroll_area"):
                    scrollbar = all_overlay.scroll_area.verticalScrollBar()
                    if scrollbar and self._saved_scroll_max > 0:
                        new_max = scrollbar.maximum()
                        if new_max > 0:
                            ratio = self._saved_scroll_value / self._saved_scroll_max
                            new_value = int(ratio * new_max)
                            scrollbar.setValue(new_value)
                            print(f"[DEBUG] Restored scroll: old={self._saved_scroll_value}, new={new_value}, ratio={ratio}")
        except Exception as e:
            print(f"[DEBUG] Restore scroll error: {e}")

    def _on_prev_image_shortcut(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.update_thumbnail_selection()
            self.update_nav_buttons_pos()
            if not self._schedule_deferred_big_image_load(int(self.current_index), delay_ms=140):
                self.load_current_image()

    def _on_next_image_shortcut(self):
        if self.current_index < len(self.image_list) - 1:
            self.current_index += 1
            self.update_thumbnail_selection()
            self.update_nav_buttons_pos()
            if not self._schedule_deferred_big_image_load(int(self.current_index), delay_ms=140):
                self.load_current_image()

    def zoom_in(self):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        self._is_syncing_scroll = True
        try:
            old_zoom = float(self.zoom_scale)
            new_zoom = float(old_zoom) + 0.1
            try:
                new_zoom = float(max(0.05, min(20.0, float(new_zoom))))
            except Exception:
                new_zoom = 1.0
            ratio = 1.0
            try:
                ratio = float(new_zoom) / float(old_zoom) if float(old_zoom) > 0 else 1.0
            except Exception:
                ratio = 1.0
            for view in self._get_active_views():
                view.scale(float(ratio), float(ratio))
                # 缩放后更新 last_value
                if hasattr(view, "horizontalScrollBar"):
                    view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                    view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
            self.zoom_scale = float(new_zoom)
            self.update_zoom_label()
            # 刷新鸟眼框位置
            try:
                QTimer.singleShot(0, self._refresh_eye_rect_overlay)
            except Exception:
                pass
            try:
                if self._settings_manager is not None:
                    self._settings_manager.set("image_detail/zoom_scale", float(self.zoom_scale))
                    self._settings_manager.sync()
            except Exception:
                pass
        finally:
            self._is_syncing_scroll = False

    def zoom_out(self):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        self._is_syncing_scroll = True
        try:
            old_zoom = float(self.zoom_scale)
            new_zoom = float(old_zoom) - 0.1
            try:
                new_zoom = float(max(0.05, min(20.0, float(new_zoom))))
            except Exception:
                new_zoom = 1.0
            ratio = 1.0
            try:
                ratio = float(new_zoom) / float(old_zoom) if float(old_zoom) > 0 else 1.0
            except Exception:
                ratio = 1.0
            for view in self._get_active_views():
                view.scale(float(ratio), float(ratio))
                # 缩放后更新 last_value
                if hasattr(view, "horizontalScrollBar"):
                    view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                    view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
            self.zoom_scale = float(new_zoom)
            self.update_zoom_label()
            # 刷新鸟眼框位置
            try:
                QTimer.singleShot(0, self._refresh_eye_rect_overlay)
            except Exception:
                pass
            try:
                if self._settings_manager is not None:
                    self._settings_manager.set("image_detail/zoom_scale", float(self.zoom_scale))
                    self._settings_manager.sync()
            except Exception:
                pass
        finally:
            self._is_syncing_scroll = False
        
    def update_zoom_label(self):
        self.lbl_zoom.setText(f"{int(self.zoom_scale * 100)}%")

    def rotate_image(self):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self._is_syncing_scroll = True
        try:
            for view in self._get_active_views():
                view.rotate(90)
                # 旋转后更新 last_value
                if hasattr(view, "horizontalScrollBar"):
                    view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                    view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
        finally:
            self._is_syncing_scroll = False

    def toggle_magnifier(self):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        # 切换所有视图的放大镜状态
        # 获取当前状态（取第一个视图）
        views = self._get_active_views()
        if not views:
            return
            
        current_state = views[0].magnifier_enabled
        new_state = not current_state
        
        # 统一倍率：使用第一个视图的倍率作为基准
        base_factor = views[0].magnification_factor
        
        for view in views:
            view.toggle_magnifier(new_state)
            # 开启时强制同步倍率
            if new_state:
                view.set_magnification(base_factor)

    def _get_active_views(self):
        if self.compare_mode:
            return [self.view_left, self.view_right]
        return [self.view]

    def toggle_compare_mode(self):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        self.compare_mode = not self.compare_mode
        
        if self.compare_mode:
            # 进入对比模式
            self.saved_left_index = self.current_index
            self.center_stack.setCurrentIndex(1)
            try:
                if hasattr(self, "splitter") and self.splitter is not None:
                    QTimer.singleShot(0, lambda: self.splitter.setSizes([max(1, int(self.splitter.width() // 2)), max(1, int(self.splitter.width() // 2))]))
            except Exception:
                pass
            self._apply_compare_button_style(active=True)
            self._clear_subject_rect()
            self._clear_focus_point()
            try:
                if hasattr(self, "info_overlay_main") and self.info_overlay_main:
                    self.info_overlay_main.hide()
                if hasattr(self, "all_info_overlay_main") and self.all_info_overlay_main:
                    self.all_info_overlay_main.hide()
                if hasattr(self, "info_overlay_left") and self.info_overlay_left:
                    self.info_overlay_left.hide()
                if hasattr(self, "info_overlay_right") and self.info_overlay_right:
                    self.info_overlay_right.hide()
            except Exception:
                pass
            
            # 刷新缩略图选中状态（清除高亮）
            self.update_thumbnail_selection()
            
            # 1. 设置左侧为当前显示的图片（固定）
            if self.pixmap_item.pixmap():
                self.pixmap_item_left.setPixmap(self.pixmap_item.pixmap())
                self.pixmap_item_left.setPos(0, 0)
                # 使用 _fit_view 确保左侧居中
                self._fit_view(self.view_left, self.pixmap_item_left)
                
                # 同步更新左侧 Overlay 数据
                if 0 <= self.current_index < len(self.image_list):
                    path = self.image_list[self.current_index]['path']
                    self._update_overlay_data(path, self.overlay_left, self.info_overlay_left)

            self._prefetch_compare_subject_state()
                
            # 2. 右侧初始为空，等待用户点击其他图片
            self.pixmap_item_right.setPixmap(QPixmap())
            self.view_right.resetTransform()
            
            # 隐藏右侧 Overlay 直到加载图片
            if hasattr(self, 'overlay_right') and self.overlay_right:
                self.overlay_right.hide()
            if hasattr(self, 'info_overlay_right') and self.info_overlay_right:
                self.info_overlay_right.hide()
            
            # 提示
            try:
                from ui.utils.notification_manager import NotificationManager
                NotificationManager.instance().show_toast("进入对比模式：左侧固定，右侧点击图片列表切换")
            except Exception as e:
                try:
                    LogManager.instance().warning(f"Toast 提示失败: {e}")
                except Exception:
                    pass
                
        else:
            # 退出对比模式
            self.center_stack.setCurrentIndex(0)
            self._apply_compare_button_style(active=False)
            
            # 恢复到左侧图片
            if hasattr(self, 'saved_left_index') and 0 <= self.saved_left_index < len(self.image_list):
                self.current_index = self.saved_left_index
                self._clear_subject_rect()
                self._clear_focus_point()
                self.load_current_image()
                self.update_thumbnail_selection()
            
            # 重新适应主视图
            self.fit_image_to_view()
            try:
                if hasattr(self, "info_overlay_main") and self.info_overlay_main:
                    self.info_overlay_main.show()
                if hasattr(self, "info_overlay_left") and self.info_overlay_left:
                    self.info_overlay_left.hide()
                if hasattr(self, "info_overlay_right") and self.info_overlay_right:
                    self.info_overlay_right.hide()
            except Exception:
                pass

    def _apply_compare_button_style(self, active: bool):
        if not hasattr(self, "btn_compare") or self.btn_compare is None:
            return
        cm = ColorManager.instance()
        hover_bg = cm.to_qss_color("image_detail.toolbar.button.hover_background", default="#FFFFFF1E")
        pressed_bg = cm.to_qss_color("image_detail.toolbar.button.pressed_background", default="#FFFFFF32")
        tooltip_text = cm.get("tooltip.text")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_border = cm.get("tooltip.border")
        active_bg = cm.to_qss_color("image_detail.compare_button.active_background", default="#FFFFFF32")
        if bool(active):
            self.btn_compare.setStyleSheet(f"""
                QPushButton {{ background-color: {active_bg}; border: 1px solid #FFFFFF; border-radius: 4px; }}
                QPushButton:hover {{ background-color: {hover_bg}; }}
                QPushButton:pressed {{ background-color: {pressed_bg}; }}
                QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
            """)
        else:
            self.btn_compare.setStyleSheet(f"""
                QPushButton {{ background-color: transparent; border: none; border-radius: 4px; }}
                QPushButton:hover {{ background-color: {hover_bg}; }}
                QPushButton:pressed {{ background-color: {pressed_bg}; }}
                QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
            """)
            
    def _effective_view_scale(self, transform: QTransform) -> float:
        return float((transform.m11() ** 2 + transform.m21() ** 2) ** 0.5)
            
    def _zoom_view_to_rect(self, view, rect: QRectF):
        if not view or rect is None or rect.isNull():
            return
        self._is_syncing_scroll = True
        try:
            view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            if getattr(self, "rotation_angle", 0):
                view.rotate(self.rotation_angle)
            if hasattr(view, "horizontalScrollBar"):
                view.horizontalScrollBar().setProperty("last_value", view.horizontalScrollBar().value())
                view.verticalScrollBar().setProperty("last_value", view.verticalScrollBar().value())
        finally:
            self._is_syncing_scroll = False

    def _get_pixmap_size_for_scene(self, target_scene):
        try:
            if self.compare_mode:
                if target_scene == self.scene_left:
                    pix = self.pixmap_item_left.pixmap() if self.pixmap_item_left else QPixmap()
                elif target_scene == self.scene_right:
                    pix = self.pixmap_item_right.pixmap() if self.pixmap_item_right else QPixmap()
                else:
                    pix = QPixmap()
            else:
                pix = self.pixmap_item.pixmap() if hasattr(self, "pixmap_item") and self.pixmap_item else QPixmap()
            if pix and not pix.isNull():
                return int(pix.width()), int(pix.height())
        except Exception:
            pass
        return None

    def _get_exif_orientation_code(self, path: str) -> int:
        try:
            p = str(path or "")
        except Exception:
            p = ""
        if not p:
            return 1
        try:
            cached = (getattr(self, "_exif_orientation_cache", None) or {}).get(p)
            if cached is not None:
                return int(cached)
        except Exception:
            pass
        code = 1
        try:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    tags = exifread.process_file(f, details=False, stop_tag="Image Orientation")
                tag = None
                if isinstance(tags, dict):
                    tag = tags.get("Image Orientation") or tags.get("Orientation") or tags.get("EXIF Orientation")
                if tag is not None:
                    try:
                        vals = getattr(tag, "values", None)
                        if isinstance(vals, (list, tuple)) and vals:
                            code = int(vals[0])
                        else:
                            code = int(str(tag).strip())
                    except Exception:
                        s = str(tag or "")
                        try:
                            import re
                            nums = re.findall(r"\\d+", s)
                            if nums:
                                code = int(nums[0])
                        except Exception:
                            pass
        except Exception:
            code = 1
        try:
            if not hasattr(self, "_exif_orientation_cache") or self._exif_orientation_cache is None:
                self._exif_orientation_cache = {}
            self._exif_orientation_cache[p] = int(code)
        except Exception:
            pass
        return int(code or 1)

    def _get_detect_base_size_for_path(self, path: str):
        p = str(path or "")
        if not p:
            return None
        try:
            rec = self._get_record_for_path(p)
        except Exception:
            rec = None
        if isinstance(rec, dict):
            fd = None
            try:
                fdj = rec.get("focus_detect_json")
            except Exception:
                fdj = None
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
                    ow = int(float(fd.get("orig_w") or 0))
                    oh = int(float(fd.get("orig_h") or 0))
                    if ow > 1 and oh > 1:
                        return (ow, oh)
                except Exception:
                    pass
        try:
            from cache.focus_scaled_cache import try_load_meta
            try:
                focus_target = int(SettingsManager.instance().get("focus_detect/target_size", 640) or 640)
            except Exception:
                focus_target = 640
            scope = "import_focus" if str(getattr(self, "_db_table_name", "")) == "import_cache" or str(getattr(self, "_big_cache_context", "")).lower() == "import" else "focus"
            meta0 = try_load_meta(p, int(focus_target), scope=str(scope))
            if isinstance(meta0, dict):
                try:
                    ow = int(float(meta0.get("orig_w") or 0))
                    oh = int(float(meta0.get("orig_h") or 0))
                    if ow > 1 and oh > 1:
                        return (ow, oh)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            for info in (self.image_list or []):
                if isinstance(info, dict) and str(info.get("path") or "") == p:
                    try:
                        w0 = int(info.get("width") or 0)
                        h0 = int(info.get("height") or 0)
                        if w0 > 1 and h0 > 1:
                            return (w0, h0)
                    except Exception:
                        pass
                    break
        except Exception:
            pass
        try:
            if os.path.exists(p):
                with suppress_stderr_fd():
                    reader = QImageReader(p)
                    try:
                        reader.setAutoTransform(False)
                    except Exception:
                        pass
                    sz = reader.size()
                if sz is not None and sz.isValid():
                    ow = int(sz.width())
                    oh = int(sz.height())
                    if ow > 1 and oh > 1:
                        return (ow, oh)
        except Exception:
            pass
        return None

    def _map_point_to_scene_xy(self, x, y, path: str, scene_w: int, scene_h: int, *, is_normalized: bool):
        try:
            sw = int(scene_w)
            sh = int(scene_h)
        except Exception:
            return None
        if sw <= 1 or sh <= 1:
            return None
        if bool(is_normalized):
            try:
                return float(x) * float(sw), float(y) * float(sh)
            except Exception:
                return None
        bases = []
        try:
            b0 = self._get_detect_base_size_for_path(path)
        except Exception:
            b0 = None
        if b0 is not None:
            bases.append(b0)
        try:
            b1 = self._get_orig_size_for_path(path)
        except Exception:
            b1 = None
        if b1 is not None:
            bases.append(b1)
        if bases:
            uniq = []
            for b in bases:
                try:
                    bw = int(b[0])
                    bh = int(b[1])
                except Exception:
                    continue
                if bw <= 1 or bh <= 1:
                    continue
                key = (bw, bh)
                if key not in uniq:
                    uniq.append(key)
            bases = uniq
        if not bases:
            try:
                return float(x), float(y)
            except Exception:
                return None
        try:
            x0 = float(x)
            y0 = float(y)
        except Exception:
            return None
        rot_hint = 0
        try:
            ori = int(self._get_exif_orientation_code(path) or 1)
            if ori == 3:
                rot_hint = 180
            elif ori == 6:
                rot_hint = 90
            elif ori == 8:
                rot_hint = 270
        except Exception:
            rot_hint = 0

        cand_rots = []
        for r in (rot_hint, 0, 90, 270, 180):
            try:
                r = int(r or 0) % 360
            except Exception:
                r = 0
            if r not in cand_rots:
                cand_rots.append(r)

        best = None
        best_score = -1e18
        for bi, base_wh in enumerate(bases):
            try:
                ow = float(base_wh[0])
                oh = float(base_wh[1])
            except Exception:
                continue
            if ow <= 1.0 or oh <= 1.0:
                continue

            def _map_with_rot(r: int):
                try:
                    r = int(r or 0) % 360
                except Exception:
                    r = 0
                try:
                    if r == 90:
                        x1 = float(oh) - float(y0)
                        y1 = float(x0)
                        rw = float(oh)
                        rh = float(ow)
                    elif r == 270:
                        x1 = float(y0)
                        y1 = float(ow) - float(x0)
                        rw = float(oh)
                        rh = float(ow)
                    elif r == 180:
                        x1 = float(ow) - float(x0)
                        y1 = float(oh) - float(y0)
                        rw = float(ow)
                        rh = float(oh)
                    else:
                        x1 = float(x0)
                        y1 = float(y0)
                        rw = float(ow)
                        rh = float(oh)
                except Exception:
                    x1 = float(x0)
                    y1 = float(y0)
                    rw = float(ow)
                    rh = float(oh)
                if rw <= 1.0 or rh <= 1.0:
                    return None
                try:
                    sx = float(sw) / float(rw)
                    sy = float(sh) / float(rh)
                except Exception:
                    return None
                px = float(x1) * float(sx)
                py = float(y1) * float(sy)
                return px, py, x1, y1, rw, rh

            for r in cand_rots:
                m = _map_with_rot(r)
                if m is None:
                    continue
                px, py, x1, y1, rw, rh = m
                sc = 0.0
                try:
                    if 0.0 <= float(px) <= float(sw) and 0.0 <= float(py) <= float(sh):
                        sc += 4.0
                except Exception:
                    pass
                try:
                    if 0.0 <= float(x1) <= float(rw) and 0.0 <= float(y1) <= float(rh):
                        sc += 2.0
                except Exception:
                    pass
                try:
                    if int(r) == int(rot_hint):
                        sc += 0.2
                except Exception:
                    pass
                try:
                    if int(bi) == 1:
                        sc += 0.05
                except Exception:
                    pass
                if sc > best_score:
                    best_score = sc
                    best = (px, py)

        if best is not None:
            return best[0], best[1]
        try:
            ow = float(bases[-1][0])
            oh = float(bases[-1][1])
            return float(x0) * float(sw) / float(ow), float(y0) * float(sh) / float(oh)
        except Exception:
            try:
                return float(x0), float(y0)
            except Exception:
                return None

    def _get_orig_size_for_path(self, path: str):
        if not path:
            return None
        try:
            p = str(path)
            cached = _ORIG_IMAGE_SIZE_BY_PATH.get(p)
            if cached:
                return cached
            try:
                if os.path.exists(p):
                    with suppress_stderr_fd():
                        reader = QImageReader(p)
                        reader.setAutoTransform(True)
                        sz = reader.size()
                    if sz is not None and sz.isValid():
                        ow = int(sz.width())
                        oh = int(sz.height())
                        if ow > 0 and oh > 0:
                            _ORIG_IMAGE_SIZE_BY_PATH[p] = (ow, oh)
                            return (ow, oh)
            except Exception:
                pass
            try:
                ext = os.path.splitext(p)[1].upper()
            except Exception:
                ext = ""
            if ext and ext in raw_exts:
                try:
                    img = load_image(p)
                except Exception:
                    img = None
                if img is not None:
                    try:
                        oh, ow = img.shape[:2]
                        ow = int(ow)
                        oh = int(oh)
                    except Exception:
                        ow = 0
                        oh = 0
                    if ow > 0 and oh > 0:
                        _ORIG_IMAGE_SIZE_BY_PATH[p] = (ow, oh)
                        return (ow, oh)
            try:
                exif_worker = ExifHandleWorker.get_instance()
            except Exception:
                exif_worker = None
            if exif_worker is not None:
                tags = [
                    "ImageWidth",
                    "ImageHeight",
                    "ExifImageWidth",
                    "ExifImageHeight",
                    "RawImageFullWidth",
                    "RawImageFullHeight",
                    "RawImageWidth",
                    "RawImageHeight",
                ]
                meta = {}
                try:
                    meta = exif_worker.get_tags(p, tags) or {}
                except Exception:
                    meta = {}
                def _int(v):
                    if v is None:
                        return 0
                    try:
                        if isinstance(v, (int, float)):
                            return int(v)
                        s = str(v).strip()
                        if not s:
                            return 0
                        digits = "".join(ch for ch in s if ch.isdigit())
                        return int(digits) if digits else 0
                    except Exception:
                        return 0
                if ext and ext in raw_exts:
                    ow = _int(meta.get("ExifImageWidth")) or _int(meta.get("ImageWidth")) or _int(meta.get("RawImageFullWidth")) or _int(meta.get("RawImageWidth"))
                    oh = _int(meta.get("ExifImageHeight")) or _int(meta.get("ImageHeight")) or _int(meta.get("RawImageFullHeight")) or _int(meta.get("RawImageHeight"))
                else:
                    ow = _int(meta.get("RawImageFullWidth")) or _int(meta.get("RawImageWidth")) or _int(meta.get("ExifImageWidth")) or _int(meta.get("ImageWidth"))
                    oh = _int(meta.get("RawImageFullHeight")) or _int(meta.get("RawImageHeight")) or _int(meta.get("ExifImageHeight")) or _int(meta.get("ImageHeight"))
                if ow > 0 and oh > 0:
                    _ORIG_IMAGE_SIZE_BY_PATH[p] = (ow, oh)
                    return (ow, oh)
            return None
        except Exception:
            return None

    def _sd_dbg_log(self, msg: str):
        try:
            LogManager.instance().debug(f"[SubjectRectDBG] {msg}")
        except Exception:
            pass

    def _bbox_to_rect_and_xywh(self, bbox, image_size=None, orig_size=None):
        if bbox is None:
            return None, None

        # 尝试解析字符串形式的 bbox
        if isinstance(bbox, str):
            try:
                bbox = json.loads(bbox)
            except Exception:
                pass

        x = y = w = h = None
        if isinstance(bbox, dict):
            try:
                x = float(bbox.get("x"))
                y = float(bbox.get("y"))
                w = float(bbox.get("w"))
                h = float(bbox.get("h"))
            except Exception:
                x = y = w = h = None
            if x is None or y is None or w is None or h is None:
                try:
                    if all(k in bbox for k in ("x1", "y1", "x2", "y2")):
                        x1 = float(bbox.get("x1"))
                        y1 = float(bbox.get("y1"))
                        x2 = float(bbox.get("x2"))
                        y2 = float(bbox.get("y2"))
                        x = x1
                        y = y1
                        w = x2 - x1
                        h = y2 - y1
                except Exception:
                    x = y = w = h = None
            if x is None or y is None or w is None or h is None:
                try:
                    if all(k in bbox for k in ("left", "top", "right", "bottom")):
                        x1 = float(bbox.get("left"))
                        y1 = float(bbox.get("top"))
                        x2 = float(bbox.get("right"))
                        y2 = float(bbox.get("bottom"))
                        x = x1
                        y = y1
                        w = x2 - x1
                        h = y2 - y1
                except Exception:
                    x = y = w = h = None
        elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                a, b, c, d = [float(v) for v in bbox]
            except Exception:
                a = b = c = d = None

            cand_xywh = None
            if a is not None and b is not None and c is not None and d is not None:
                if c > 0 and d > 0:
                    cand_xywh = (a, b, c, d)

            cand_xyxy = None
            if a is not None and b is not None and c is not None and d is not None:
                if c > a and d > b:
                    cand_xyxy = (a, b, c - a, d - b)

            if cand_xywh is None and cand_xyxy is None:
                return None, None
            if cand_xywh is not None and cand_xyxy is None:
                x, y, w, h = cand_xywh
            elif cand_xyxy is not None and cand_xywh is None:
                x, y, w, h = cand_xyxy
            else:
                base_w = base_h = 0.0
                try:
                    if a is not None and b is not None and c is not None and d is not None:
                        if 0.0 <= a <= 1.0 and 0.0 <= b <= 1.0 and 0.0 <= c <= 1.0 and 0.0 <= d <= 1.0:
                            base_w, base_h = 1.0, 1.0
                except Exception:
                    base_w = base_h = 0.0

                if base_w <= 0.0 or base_h <= 0.0:
                    try:
                        if orig_size and len(orig_size) >= 2:
                            base_w = float(orig_size[0] or 0)
                            base_h = float(orig_size[1] or 0)
                    except Exception:
                        base_w = base_h = 0.0

                if base_w <= 0.0 or base_h <= 0.0:
                    try:
                        if image_size and len(image_size) >= 2:
                            base_w = float(image_size[0] or 0)
                            base_h = float(image_size[1] or 0)
                    except Exception:
                        base_w = base_h = 0.0

                if base_w <= 0.0 or base_h <= 0.0:
                    x, y, w, h = cand_xywh
                else:
                    img_w, img_h = base_w, base_h
                    def penalty(v):
                        vx, vy, vw, vh = v
                        p = 0.0
                        if vw <= 0 or vh <= 0:
                            p += 1e9
                        if vx < 0:
                            p += -vx
                        if vy < 0:
                            p += -vy
                        if vx + vw > img_w:
                            p += (vx + vw - img_w)
                        if vy + vh > img_h:
                            p += (vy + vh - img_h)
                        return p
                    if penalty(cand_xyxy) <= penalty(cand_xywh):
                        x, y, w, h = cand_xyxy
                    else:
                        x, y, w, h = cand_xywh
        else:
            return None, None

        if x is None or y is None or w is None or h is None:
            return None, None

        w = float(max(1.0, w))
        h = float(max(1.0, h))

        disp_w = disp_h = 0
        try:
            if image_size:
                disp_w = int(image_size[0])
                disp_h = int(image_size[1])
        except Exception:
            disp_w = disp_h = 0

        orig_w = orig_h = 0
        try:
            if orig_size:
                orig_w = int(orig_size[0])
                orig_h = int(orig_size[1])
        except Exception:
            orig_w = orig_h = 0
        try:
            if orig_w > 0 and orig_h > 0 and disp_w > 0 and disp_h > 0:
                r_disp = float(disp_w) / float(disp_h)
                r_orig = float(orig_w) / float(orig_h)
                r_swap = float(orig_h) / float(orig_w) if orig_w > 0 else r_orig
                if abs(r_swap - r_disp) < abs(r_orig - r_disp):
                    orig_w, orig_h = int(orig_h), int(orig_w)
        except Exception:
            pass

        try:
            is_normalized = (0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0 and 0.0 < float(w) <= 1.0 and 0.0 < float(h) <= 1.0)
        except Exception:
            is_normalized = False

        rect_x = float(x)
        rect_y = float(y)
        rect_w = float(w)
        rect_h = float(h)

        if is_normalized:
            if disp_w > 0 and disp_h > 0:
                rect_x = float(x) * float(disp_w)
                rect_y = float(y) * float(disp_h)
                rect_w = float(w) * float(disp_w)
                rect_h = float(h) * float(disp_h)
            if orig_w > 0 and orig_h > 0:
                xywh = [
                    int(round(float(x) * float(orig_w))),
                    int(round(float(y) * float(orig_h))),
                    int(round(float(w) * float(orig_w))),
                    int(round(float(h) * float(orig_h))),
                ]
            elif disp_w > 0 and disp_h > 0:
                xywh = [
                    int(round(float(x) * float(disp_w))),
                    int(round(float(y) * float(disp_h))),
                    int(round(float(w) * float(disp_w))),
                    int(round(float(h) * float(disp_h))),
                ]
            else:
                xywh = [int(round(float(x))), int(round(float(y))), int(round(float(w))), int(round(float(h)))]
        else:
            if orig_w > 0 and orig_h > 0:
                xywh = [int(round(float(x))), int(round(float(y))), int(round(float(w))), int(round(float(h)))]
                if disp_w > 0 and disp_h > 0 and (disp_w != orig_w or disp_h != orig_h):
                    try:
                        sx = float(disp_w) / float(orig_w)
                        sy = float(disp_h) / float(orig_h)
                        rect_x = float(x) * sx
                        rect_y = float(y) * sy
                        rect_w = float(w) * sx
                        rect_h = float(h) * sy
                    except Exception:
                        rect_x = float(x)
                        rect_y = float(y)
                        rect_w = float(w)
                        rect_h = float(h)
            else:
                xywh = [int(round(float(x))), int(round(float(y))), int(round(float(w))), int(round(float(h)))]

        if disp_w > 0 and disp_h > 0:
            try:
                rect_x = max(0.0, min(float(rect_x), float(disp_w - 1)))
                rect_y = max(0.0, min(float(rect_y), float(disp_h - 1)))
                rect_w = max(1.0, min(float(rect_w), float(disp_w) - float(rect_x)))
                rect_h = max(1.0, min(float(rect_h), float(disp_h) - float(rect_y)))
            except Exception:
                pass

        rect = QRectF(float(rect_x), float(rect_y), float(rect_w), float(rect_h))
        try:
            if disp_w > 0 and disp_h > 0:
                tiny = float(rect.width()) <= 1.5 or float(rect.height()) <= 1.5
                near_edge = float(rect.x()) >= float(disp_w - 2) or float(rect.y()) >= float(disp_h - 2)
                if tiny and near_edge:
                    self._sd_dbg_log(
                        f"tiny_rect_at_edge bbox={bbox} is_norm={bool(is_normalized)} "
                        f"disp=({disp_w},{disp_h}) orig=({orig_w},{orig_h}) rect=({rect.x():.2f},{rect.y():.2f},{rect.width():.2f},{rect.height():.2f}) "
                        f"xywh={xywh}"
                    )
        except Exception:
            pass
        return rect, xywh

    def _draw_subject_rect(self, rect: QRectF, target_scene, image_path: str):
        if rect is None or rect.isNull() or target_scene is None:
            return
        existing_item = None
        if self.compare_mode and target_scene == self.scene_left:
            existing_item = self._subject_rect_item_left
        elif self.compare_mode and target_scene == self.scene_right:
            existing_item = self._subject_rect_item_right
        else:
            existing_item = self._subject_rect_item

        if existing_item is not None:
            try:
                if existing_item.scene() is not None:
                    existing_item.scene().removeItem(existing_item)
            except Exception:
                pass

        if self.compare_mode and target_scene == self.scene_left:
            self._subject_rect_item_left = None
            self._subject_rect_path_left = None
        elif self.compare_mode and target_scene == self.scene_right:
            self._subject_rect_item_right = None
            self._subject_rect_path_right = None
        else:
            self._subject_rect_item = None
            self._subject_rect_path = None

        item = QGraphicsRectItem(rect)
        pen = QPen(ColorManager.instance().qcolor("border.subject_rect", default="#f50f0f"))
        pen.setWidth(3)
        pen.setCosmetic(False)
        item.setPen(pen)
        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        item.setZValue(100)
        target_scene.addItem(item)
        if self.compare_mode and target_scene == self.scene_left:
            self._subject_rect_item_left = item
            self._subject_rect_path_left = image_path
        elif self.compare_mode and target_scene == self.scene_right:
            self._subject_rect_item_right = item
            self._subject_rect_path_right = image_path
        else:
            self._subject_rect_item = item
            self._subject_rect_path = image_path

    def save_manual_subject_rect(self, rect: QRectF, side: Optional[str] = None):
        if not self.image_list:
            return

        target_index = self.current_index
        target_scene = self.scene
        if self.compare_mode:
            if side == "left":
                target_index = getattr(self, "saved_left_index", None)
                target_scene = self.scene_left
            else:
                target_index = self.current_index
                target_scene = self.scene_right

        if target_index is None or target_index < 0 or target_index >= len(self.image_list):
            return

        image_path = self.image_list[target_index].get("path", "")
        if not image_path:
            return

        rect = rect.normalized()
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        bbox_xywh = [int(round(x)), int(round(y)), int(round(w)), int(round(h))]
        try:
            disp_size = self._get_pixmap_size_for_scene(target_scene)
        except Exception:
            disp_size = None
        orig_size = self._get_orig_size_for_path(image_path)
        try:
            if disp_size and orig_size:
                dw, dh = int(disp_size[0]), int(disp_size[1])
                ow, oh = int(orig_size[0]), int(orig_size[1])
                if dw > 0 and dh > 0 and ow > 0 and oh > 0 and (dw != ow or dh != oh):
                    bbox_xywh = [
                        int(round(float(bbox_xywh[0]) * float(ow) / float(dw))),
                        int(round(float(bbox_xywh[1]) * float(oh) / float(dh))),
                        int(round(float(bbox_xywh[2]) * float(ow) / float(dw))),
                        int(round(float(bbox_xywh[3]) * float(oh) / float(dh))),
                    ]
        except Exception:
            pass
        bbox_xyxy = None
        try:
            bbox_xyxy = [int(bbox_xywh[0]), int(bbox_xywh[1]), int(bbox_xywh[0] + bbox_xywh[2]), int(bbox_xywh[1] + bbox_xywh[3])]
        except Exception:
            bbox_xyxy = None

        img_info = self.image_list[target_index]
        existing_focus = None
        existing_position = img_info.get("position")

        raw_focus = img_info.get("focus_point")
        if raw_focus:
            if isinstance(raw_focus, dict):
                try:
                    if "x" in raw_focus and "y" in raw_focus:
                        existing_focus = [float(raw_focus.get("x")), float(raw_focus.get("y"))]
                except Exception:
                    existing_focus = None
            elif isinstance(raw_focus, (list, tuple)) and len(raw_focus) >= 2:
                try:
                    existing_focus = [float(raw_focus[0]), float(raw_focus[1])]
                except Exception:
                    existing_focus = None
            elif isinstance(raw_focus, str):
                try:
                    parsed = json.loads(raw_focus)
                    if isinstance(parsed, dict) and "x" in parsed and "y" in parsed:
                        existing_focus = [float(parsed.get("x")), float(parsed.get("y"))]
                    elif isinstance(parsed, list) and len(parsed) >= 2:
                        existing_focus = [float(parsed[0]), float(parsed[1])]
                    else:
                        existing_focus = None
                except Exception:
                    existing_focus = None

        if target_scene:
            try:
                if bool(getattr(self, "_subject_rect_display_enabled", False)):
                    self._draw_subject_rect(rect, target_scene, image_path)
            except Exception:
                pass

        try:
            if self._db_table_name == "import_cache":
                self.db.update_subject_info(image_path, bbox=bbox_xyxy, focus_point=existing_focus, position=existing_position, table_name="import_cache")
            else:
                uuid_val = self._ensure_uuid_for_path(image_path)
                if uuid_val:
                    self.db.update_subject_info_by_uuid(
                        uuid_val,
                        file_path=image_path,
                        bbox=bbox_xyxy,
                        focus_point=existing_focus,
                        position=existing_position,
                        table_name=self._db_table_name,
                    )
        except Exception as e:
            try:
                NotificationManager.instance().show_warning("保存失败", f"数据库更新失败: {e}")
            except Exception:
                pass
            return

        img_info["bbox"] = json.dumps(bbox_xyxy) if bbox_xyxy is not None else None
        try:
            if existing_focus is not None:
                img_info["focus_point"] = json.dumps(existing_focus)
        except Exception:
            pass

        try:
            tags = {}
            if bbox_xyxy is not None:
                tags[EXIF_TAG.ObjectCoordinates.value] = json.dumps(bbox_xyxy)
            if existing_position:
                tags[EXIF_TAG.Position.value] = str(existing_position)
            ExifHandleWorker.get_instance().set_metadata(image_path, tags)
            NotificationManager.instance().show_toast("手动标注已保存")
        except Exception as e:
            try:
                NotificationManager.instance().show_warning("保存失败", f"EXIF更新失败: {e}")
            except Exception:
                pass

        if hasattr(self, "btn_zoom_to_bird"):
            if self.compare_mode:
                left_has_bbox = False
                right_has_bbox = False
                try:
                    li = getattr(self, "saved_left_index", None)
                    if li is not None and 0 <= li < len(self.image_list):
                        left_has_bbox = bool(self.image_list[li].get("bbox"))
                except Exception:
                    pass
                try:
                    ri = self.current_index
                    if 0 <= ri < len(self.image_list):
                        right_has_bbox = bool(self.image_list[ri].get("bbox"))
                except Exception:
                    pass
                self.btn_zoom_to_bird.setEnabled(left_has_bbox or right_has_bbox)
            else:
                self.btn_zoom_to_bird.setEnabled(True)

        if hasattr(self, "btn_zoom_to_focus"):
            if self.compare_mode:
                self.btn_zoom_to_focus.setEnabled(True)
            else:
                self.btn_zoom_to_focus.setEnabled(True)
            
    def detect_subject(self, force=False, side=None):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        modifiers = QApplication.keyboardModifiers()
        if self.compare_mode and side is None:
            if not force and (modifiers & Qt.KeyboardModifier.ControlModifier):
                if self._subject_rect_item_left is not None:
                    try:
                        if self._subject_rect_item_left.scene() is not None:
                            self._subject_rect_item_left.scene().removeItem(self._subject_rect_item_left)
                    except Exception:
                        pass
                    self._subject_rect_item_left = None
                    self._subject_rect_path_left = None
                if self._subject_rect_item_right is not None:
                    try:
                        if self._subject_rect_item_right.scene() is not None:
                            self._subject_rect_item_right.scene().removeItem(self._subject_rect_item_right)
                    except Exception:
                        pass
                    self._subject_rect_item_right = None
                    self._subject_rect_path_right = None

                if self.view_left:
                    self.view_left.set_drawing_mode(True)
                if self.view_right:
                    self.view_right.set_drawing_mode(True)
                try:
                    NotificationManager.instance().show_toast("进入手动绘制模式：在左/右图绘制红框后右键保存退出")
                except Exception:
                    pass
                return

            left_index = getattr(self, "saved_left_index", None)
            right_index = self.current_index
            if left_index is None or left_index < 0 or left_index >= len(self.image_list):
                return
            if right_index < 0 or right_index >= len(self.image_list):
                return

            left_path = self.image_list[left_index].get("path", "")
            right_path = self.image_list[right_index].get("path", "")
            if not left_path or not right_path:
                if left_path:
                    self.detect_subject(force=force, side="left")
                if right_path:
                    self.detect_subject(force=force, side="right")
                return

            left_info = self.image_list[left_index]
            right_info = self.image_list[right_index]
            try:
                left_record = self._get_record_for_path(left_path)
                if left_record:
                    if "bbox" in left_record:
                        left_info["bbox"] = left_record.get("bbox")
                    if "focus_point" in left_record:
                        left_info["focus_point"] = left_record.get("focus_point")
            except Exception:
                pass
            try:
                right_record = self._get_record_for_path(right_path)
                if right_record:
                    if "bbox" in right_record:
                        right_info["bbox"] = right_record.get("bbox")
                    if "focus_point" in right_record:
                        right_info["focus_point"] = right_record.get("focus_point")
            except Exception:
                pass

            def _is_global_fp(fp):
                if not fp:
                    return False
                if isinstance(fp, dict):
                    try:
                        mode = str(fp.get("mode") or "").lower()
                        mode_ok = (mode == "global") or (mode == "")
                        return mode_ok and (fp.get("x") is not None) and (fp.get("y") is not None)
                    except Exception:
                        return False
                if isinstance(fp, str):
                    try:
                        return _is_global_fp(json.loads(fp))
                    except Exception:
                        return False
                if isinstance(fp, (list, tuple)):
                    try:
                        return len(fp) >= 2
                    except Exception:
                        return False
                return False

            left_has_bbox = bool(left_info.get("bbox"))
            left_has_focus = _is_global_fp(left_info.get("focus_point"))
            right_has_bbox = bool(right_info.get("bbox"))
            right_has_focus = _is_global_fp(right_info.get("focus_point"))

            if not force and left_has_bbox and left_has_focus and right_has_bbox and right_has_focus:
                try:
                    self._refresh_subject_rect_overlay()
                except Exception:
                    pass
                try:
                    self._refresh_focus_point_overlay()
                except Exception:
                    pass
                return

            targets = []
            if force:
                targets = ["bbox_orig", "pos"]
            else:
                if not (left_has_bbox and right_has_bbox):
                    targets.append("bbox_orig")
                if targets:
                    targets.append("pos")

            if not targets:
                return

            self._detect_subject_pending_left = True
            self._detect_subject_pending_right = True
            self._detect_subject_target_scene_left = self.scene_left
            self._detect_subject_target_scene_right = self.scene_right
            self._detect_subject_image_size_left = self._get_pixmap_size_for_scene(self.scene_left)
            self._detect_subject_image_size_right = self._get_pixmap_size_for_scene(self.scene_right)
            if hasattr(self, "btn_detect_subject"):
                self.btn_detect_subject.setEnabled(False)

            try:
                from core.check_cli import detect_subject_bbox_multi_async
            except Exception:
                self.detect_subject(force=force, side="left")
                self.detect_subject(force=force, side="right")
                return

            def _cb(image_path: str, bbox, focus_point, position, err: str):
                try:
                    if image_path == left_path:
                        side_name = "left"
                    elif image_path == right_path:
                        side_name = "right"
                    else:
                        side_name = "single"
                    self.subject_detected.emit(side_name, image_path, bbox, focus_point, position, err, targets)
                except Exception:
                    pass

            detect_subject_bbox_multi_async([left_path, right_path], callback=_cb, targets=targets)
            return

        if not self.compare_mode and side is None:
            if not force and (modifiers & Qt.KeyboardModifier.ControlModifier):
                target_view = self.view
                if self._subject_rect_item is not None:
                    try:
                        if self._subject_rect_item.scene() is not None:
                            self._subject_rect_item.scene().removeItem(self._subject_rect_item)
                    except Exception:
                        pass
                    self._subject_rect_item = None
                    self._subject_rect_path = None

                if target_view:
                    target_view.set_drawing_mode(True)
                    try:
                        NotificationManager.instance().show_toast("进入手动绘制模式，绘制红框后右键保存退出")
                    except Exception:
                        pass
                return

        target_scene = None
        target_index = None

        if self.compare_mode:
            if side == "left":
                target_scene = self.scene_left
                target_index = getattr(self, "saved_left_index", None)
            elif side == "right":
                target_scene = self.scene_right
                target_index = self.current_index
            else:
                target_scene = self.scene_right
                target_index = self.current_index
        else:
            target_scene = self.scene
            target_index = self.current_index

        if target_index is None or not self.image_list or target_index < 0 or target_index >= len(self.image_list):
            return

        current_path = self.image_list[target_index].get("path", "")
        if not current_path:
            return

        if self.compare_mode:
            if side == "left" and getattr(self, "_detect_subject_pending_left", False):
                return
            if side == "right" and getattr(self, "_detect_subject_pending_right", False):
                return
        else:
            if getattr(self, "_detect_subject_pending", False):
                return

        if target_scene is None:
            return

        image_size = self._get_pixmap_size_for_scene(target_scene)

        record = self._get_record_for_path(current_path)

        has_bbox = False
        has_focus = False
        if record:
            if record.get("bbox"):
                has_bbox = True
            fp = record.get("focus_point")
            if isinstance(fp, dict):
                try:
                    mode = str(fp.get("mode") or "").lower()
                    mode_ok = (mode == "global") or (mode == "")
                    has_focus = mode_ok and (fp.get("x") is not None) and (fp.get("y") is not None)
                except Exception:
                    has_focus = False
            elif isinstance(fp, (list, tuple)):
                try:
                    has_focus = len(fp) >= 2
                except Exception:
                    has_focus = False
            elif isinstance(fp, str):
                try:
                    d = json.loads(fp)
                    if isinstance(d, dict):
                        mode = str(d.get("mode") or "").lower()
                        mode_ok = (mode == "global") or (mode == "")
                        has_focus = mode_ok and (d.get("x") is not None) and (d.get("y") is not None)
                    elif isinstance(d, list):
                        has_focus = len(d) >= 2
                except Exception:
                    has_focus = False
            try:
                info = self.image_list[target_index]
                if "bbox" in record:
                    info["bbox"] = record.get("bbox")
                if "focus_point" in record:
                    info["focus_point"] = record.get("focus_point")
            except Exception:
                pass

        if not force and has_bbox and has_focus:
            try:
                self._refresh_subject_rect_overlay()
            except Exception:
                pass
            try:
                self._refresh_focus_point_overlay()
            except Exception:
                pass
            return

        targets = []
        if force:
            targets = ["bbox_orig", "pos"]
        else:
            if not has_bbox:
                targets.append("bbox_orig")
            if (not has_focus) and bool(getattr(self, "_focus_point_display_enabled", False)):
                targets.append("focus_point_orig")
            if targets:
                targets.append("pos")
            else:
                return

        if self.compare_mode:
            if side == "left":
                self._detect_subject_pending_left = True
                self._detect_subject_target_scene_left = target_scene
                self._detect_subject_image_size_left = image_size
            elif side == "right":
                self._detect_subject_pending_right = True
                self._detect_subject_target_scene_right = target_scene
                self._detect_subject_image_size_right = image_size
        else:
            self._detect_subject_pending = True
            self._detect_subject_target_scene = target_scene
            self._detect_subject_image_size = image_size

        if hasattr(self, 'btn_detect_subject'):
            self.btn_detect_subject.setEnabled(False)

        try:
            from core.check_cli import detect_subject_bbox_async
        except Exception as e:
            if self.compare_mode:
                if side == "left":
                    self._detect_subject_pending_left = False
                elif side == "right":
                    self._detect_subject_pending_right = False
                if not self._detect_subject_pending_left and not self._detect_subject_pending_right:
                    if hasattr(self, 'btn_detect_subject'):
                        self.btn_detect_subject.setEnabled(True)
            else:
                self._detect_subject_pending = False
                if hasattr(self, 'btn_detect_subject'):
                    self.btn_detect_subject.setEnabled(True)
            pretty = None
            try:
                s = str(e)
            except Exception:
                s = ""
            low = s.lower()
            if ("dll" in low and "初始化" in s) or ("winerror 1114" in low) or ("c10.dll" in low) or ("torch" in low and "dll" in low):
                pretty = "检测引擎初始化失败：可能缺少 PyTorch/YOLO 依赖或显卡驱动异常，请检查运行环境或安装 CPU 版本支持。"
            elif "torch" in low and ("import" in low or "load" in low):
                pretty = "检测引擎导入失败：PyTorch/YOLO 未正确安装或版本不兼容。"
            elif "yolo" in low and ("model" in low or "load" in low):
                pretty = "模型加载失败：未找到或无法读取模型文件，请检查 models 目录。"
            try:
                msg = pretty if pretty else f"检测主体失败: {s}"
            except Exception:
                msg = "检测主体失败"
            try:
                NotificationManager.instance().show_warning("错误", msg)
            except Exception:
                pass
            return

        def _cb(image_path: str, bbox, focus_point, position, err: str):
            try:
                self.subject_detected.emit(side or "single", image_path, bbox, focus_point, position, err, targets)
            except Exception:
                pass

        detect_subject_bbox_async(current_path, callback=_cb, targets=targets)

    def _on_subject_detected(self, side: str, image_path: str, bbox, focus_point, position, err: str, targets=None):
        if self.compare_mode:
            if side == "left":
                self._detect_subject_pending_left = False
            elif side == "right":
                self._detect_subject_pending_right = False
            if hasattr(self, 'btn_detect_subject'):
                self.btn_detect_subject.setEnabled(not self._detect_subject_pending_left and not self._detect_subject_pending_right)
        else:
            self._detect_subject_pending = False
            if hasattr(self, 'btn_detect_subject'):
                self.btn_detect_subject.setEnabled(True)

        if self.compare_mode:
            if side == "left":
                target_scene = getattr(self, "_detect_subject_target_scene_left", None) or self.scene_left
                image_size = getattr(self, "_detect_subject_image_size_left", None)
                target_index = getattr(self, "saved_left_index", None)
            elif side == "right":
                target_scene = getattr(self, "_detect_subject_target_scene_right", None) or self.scene_right
                image_size = getattr(self, "_detect_subject_image_size_right", None)
                target_index = self.current_index
            else:
                target_scene = self.scene_right
                image_size = None
                target_index = self.current_index
        else:
            target_scene = getattr(self, "_detect_subject_target_scene", None) or self.scene
            image_size = getattr(self, "_detect_subject_image_size", None)
            target_index = self.current_index

        if err:
            pretty = None
            try:
                s = str(err)
            except Exception:
                s = ""
            low = s.lower()
            if ("dll" in low and "初始化" in s) or ("winerror 1114" in low) or ("c10.dll" in low) or ("torch" in low and "dll" in low):
                pretty = "检测引擎初始化失败：可能缺少 PyTorch/YOLO 依赖或显卡驱动异常，请检查运行环境或安装 CPU 版本支持。"
            elif "torch" in low and ("import" in low or "load" in low):
                pretty = "检测引擎导入失败：PyTorch/YOLO 未正确安装或版本不兼容。"
            elif "yolo" in low and ("model" in low or "load" in low):
                pretty = "模型加载失败：未找到或无法读取模型文件，请检查 models 目录。"
            try:
                msg = pretty if pretty else f"检测主体失败: {s}"
            except Exception:
                msg = "检测主体失败"
            try:
                NotificationManager.instance().show_warning("错误", msg)
            except Exception:
                pass
            return

        if target_index is None or not self.image_list or target_index < 0 or target_index >= len(self.image_list):
            return
        if self.image_list[target_index].get("path") != image_path:
            return
        if target_scene is None:
            return
            
        rect, xywh = self._bbox_to_rect_and_xywh(bbox, image_size=image_size, orig_size=self._get_orig_size_for_path(image_path))
        
        # 处理检测不到主体的情况
        if rect is None or rect.isNull() or not xywh:
            # 只有当请求了 bbox 且未检测到时才提示
            if targets and "bbox_orig" in targets:
                try:
                    NotificationManager.instance().show_toast("未检测到主体")
                except Exception:
                    pass
                return
            else:
                # 如果没检测到（或没请求），尝试使用现有的
                # 这里假设如果 targets 不含 bbox_orig，说明之前已经有 bbox 了
                # 从内存中读取现有的 bbox
                info = self.image_list[target_index]
                existing_bbox = info.get('bbox')
                if existing_bbox:
                    rect, xywh = self._bbox_to_rect_and_xywh(existing_bbox, image_size=image_size, orig_size=self._get_orig_size_for_path(image_path))

        if rect is not None and not rect.isNull() and xywh:
            try:
                if bool(getattr(self, "_subject_rect_display_enabled", False)):
                    self._draw_subject_rect(rect, target_scene, image_path)
            except Exception:
                pass

        focus_list = None
        if isinstance(focus_point, dict) and ("x" in focus_point and "y" in focus_point):
            try:
                focus_list = [float(focus_point.get("x")), float(focus_point.get("y"))]
            except Exception:
                focus_list = None
        elif isinstance(focus_point, (list, tuple)) and len(focus_point) >= 2:
            try:
                focus_list = [float(focus_point[0]), float(focus_point[1])]
            except Exception:
                focus_list = None
        
        # 如果没检测到对焦点，保留旧的（对焦点统一来自 EXIF 回填/数据库）
        if not focus_list:
             info = self.image_list[target_index]
             raw_focus = info.get('focus_point')
             if raw_focus:
                 if isinstance(raw_focus, dict) and "x" in raw_focus and "y" in raw_focus:
                     try:
                         focus_list = [float(raw_focus.get("x")), float(raw_focus.get("y"))]
                     except Exception:
                         focus_list = None
                 elif isinstance(raw_focus, (list, tuple)) and len(raw_focus) >= 2:
                     try:
                         focus_list = [float(raw_focus[0]), float(raw_focus[1])]
                     except Exception:
                         focus_list = None
                 elif isinstance(raw_focus, str):
                     try:
                         parsed = json.loads(raw_focus)
                         if isinstance(parsed, dict) and "x" in parsed and "y" in parsed:
                             focus_list = [float(parsed.get("x")), float(parsed.get("y"))]
                         elif isinstance(parsed, list) and len(parsed) >= 2:
                             focus_list = [float(parsed[0]), float(parsed[1])]
                     except Exception:
                         focus_list = focus_list

        focus_payload = None
        if focus_list:
            try:
                focus_payload = {"x": float(focus_list[0]), "y": float(focus_list[1]), "mode": "global"}
            except Exception:
                focus_payload = focus_list

        bbox_xyxy = None
        if bbox is not None:
            if isinstance(bbox, dict) and ("x" in bbox and "y" in bbox and "w" in bbox and "h" in bbox):
                try:
                    x0 = float(bbox.get("x"))
                    y0 = float(bbox.get("y"))
                    w0 = float(bbox.get("w"))
                    h0 = float(bbox.get("h"))
                    bbox_xyxy = [x0, y0, x0 + w0, y0 + h0]
                except Exception:
                    bbox_xyxy = None
            elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                try:
                    bbox_xyxy = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                except Exception:
                    bbox_xyxy = None
            elif isinstance(bbox, str):
                try:
                    parsed = json.loads(bbox)
                    if isinstance(parsed, dict) and ("x" in parsed and "y" in parsed and "w" in parsed and "h" in parsed):
                        x0 = float(parsed.get("x"))
                        y0 = float(parsed.get("y"))
                        w0 = float(parsed.get("w"))
                        h0 = float(parsed.get("h"))
                        bbox_xyxy = [x0, y0, x0 + w0, y0 + h0]
                    elif isinstance(parsed, list) and len(parsed) >= 4:
                        bbox_xyxy = [float(parsed[0]), float(parsed[1]), float(parsed[2]), float(parsed[3])]
                except Exception:
                    bbox_xyxy = None
        if bbox_xyxy is None and xywh:
            try:
                bbox_xyxy = [float(xywh[0]), float(xywh[1]), float(xywh[0] + xywh[2]), float(xywh[1] + xywh[3])]
            except Exception:
                bbox_xyxy = None

        try:
            # 更新 DB时，只更新有效的字段，或者都更新？
            # update_subject_info 会处理 None 值吗？通常会覆盖。
            # 所以我们要确保 xywh 和 focus_dict 是最新的（包括 fallback 到旧值的）
            if self._db_table_name == "import_cache":
                self.db.update_subject_info(image_path, bbox=bbox_xyxy, position=position, table_name="import_cache")
            else:
                uuid_val = self._ensure_uuid_for_path(image_path)
                if uuid_val:
                    self.db.update_subject_info_by_uuid(
                        uuid_val,
                        file_path=image_path,
                        bbox=bbox_xyxy,
                        position=position,
                        table_name=self._db_table_name,
                    )
        except Exception:
            pass

        # Update image_list
        if self.image_list and 0 <= target_index < len(self.image_list):
            info = self.image_list[target_index]
            if info.get('path') == image_path:
                info['bbox'] = json.dumps(bbox_xyxy) if bbox_xyxy else None
                if focus_list:
                    try:
                        info['focus_point'] = json.dumps([float(focus_list[0]), float(focus_list[1])])
                    except Exception:
                        info['focus_point'] = info.get('focus_point')
                if position:
                    info['position'] = position
        
        try:
            from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG
            tags = {}
            if bbox_xyxy:
                tags[EXIF_TAG.ObjectCoordinates.value] = json.dumps(bbox_xyxy)
            if focus_list:
                try:
                    tags[EXIF_TAG.FocusPoint.value] = json.dumps([float(focus_list[0]), float(focus_list[1])])
                except Exception:
                    tags = tags
            if position is not None and position != "":
                tags[EXIF_TAG.Position.value] = str(position)
            if tags:
                ExifHandleWorker.get_instance().set_metadata(image_path, tags)
        except Exception:
            pass

        if self.compare_mode:
            left_ok_bbox = False
            left_ok_focus = False
            right_ok_bbox = False
            right_ok_focus = False
            try:
                li = getattr(self, "saved_left_index", None)
                if li is not None and 0 <= li < len(self.image_list):
                    left_ok_bbox = bool(self.image_list[li].get("bbox"))
                    left_ok_focus = bool(self.image_list[li].get("focus_point"))
            except Exception:
                pass
            try:
                ri = self.current_index
                if 0 <= ri < len(self.image_list):
                    right_ok_bbox = bool(self.image_list[ri].get("bbox"))
                    right_ok_focus = bool(self.image_list[ri].get("focus_point"))
            except Exception:
                pass
            if hasattr(self, 'btn_zoom_to_bird'):
                self.btn_zoom_to_bird.setEnabled(left_ok_bbox or right_ok_bbox)
            if hasattr(self, 'btn_zoom_to_focus'):
                self.btn_zoom_to_focus.setEnabled(True)
        else:
            has_bbox = True if xywh else False
            has_focus = True if focus_list else False
            if hasattr(self, 'btn_zoom_to_bird'):
                self.btn_zoom_to_bird.setEnabled(has_bbox)
            if hasattr(self, 'btn_zoom_to_focus'):
                self.btn_zoom_to_focus.setEnabled(True)

        try:
            QTimer.singleShot(0, self._refresh_subject_rect_overlay)
            QTimer.singleShot(0, self._refresh_focus_point_overlay)
        except Exception:
            pass

    def _clear_subject_rect(self):
        items = [
            ("_subject_rect_item", "_subject_rect_path"),
            ("_subject_rect_item_left", "_subject_rect_path_left"),
            ("_subject_rect_item_right", "_subject_rect_path_right"),
        ]
        for item_attr, path_attr in items:
            item = getattr(self, item_attr, None)
            if item is None:
                try:
                    setattr(self, path_attr, None)
                except Exception:
                    pass
                continue
            try:
                if item.scene() is not None:
                    item.scene().removeItem(item)
            except Exception:
                pass
            try:
                setattr(self, item_attr, None)
                setattr(self, path_attr, None)
            except Exception:
                pass

    def _clear_subject_rect_side(self, side: str):
        if side == "left":
            item_attr, path_attr = "_subject_rect_item_left", "_subject_rect_path_left"
        elif side == "right":
            item_attr, path_attr = "_subject_rect_item_right", "_subject_rect_path_right"
        else:
            return

        item = getattr(self, item_attr, None)
        if item is not None:
            try:
                if item.scene() is not None:
                    item.scene().removeItem(item)
            except Exception:
                pass
        try:
            setattr(self, item_attr, None)
            setattr(self, path_attr, None)
        except Exception:
            pass

    def _clear_eye_rect(self):
        items = [
            ("_eye_rect_item", "_eye_rect_path"),
            ("_eye_rect_item_left", "_eye_rect_path_left"),
            ("_eye_rect_item_right", "_eye_rect_path_right"),
        ]
        for item_attr, path_attr in items:
            item = getattr(self, item_attr, None)
            if item is None:
                try:
                    setattr(self, path_attr, None)
                except Exception:
                    pass
                continue
            try:
                if item.scene() is not None:
                    item.scene().removeItem(item)
            except Exception:
                pass
            try:
                setattr(self, item_attr, None)
                setattr(self, path_attr, None)
            except Exception:
                pass

    def _clear_eye_rect_side(self, side: str):
        if side == "left":
            item_attr, path_attr = "_eye_rect_item_left", "_eye_rect_path_left"
        elif side == "right":
            item_attr, path_attr = "_eye_rect_item_right", "_eye_rect_path_right"
        else:
            return

        item = getattr(self, item_attr, None)
        if item is not None:
            try:
                if item.scene() is not None:
                    item.scene().removeItem(item)
            except Exception:
                pass
        try:
            setattr(self, item_attr, None)
            setattr(self, path_attr, None)
        except Exception:
            pass

    def _clear_focus_point(self):
        items = []
        if hasattr(self, "_focus_point_item_left") and getattr(self, "_focus_point_item_left", None):
            items.append(("_focus_point_item_left", getattr(self, "_focus_point_item_left")))
        if hasattr(self, "_focus_point_item_right") and getattr(self, "_focus_point_item_right", None):
            items.append(("_focus_point_item_right", getattr(self, "_focus_point_item_right")))
        if hasattr(self, "_focus_point_item") and getattr(self, "_focus_point_item", None):
            items.append(("_focus_point_item", getattr(self, "_focus_point_item")))

        for attr, item in items:
            try:
                if item and item.scene():
                    item.scene().removeItem(item)
            except Exception:
                pass
            try:
                setattr(self, attr, None)
            except Exception:
                pass

    def _clear_focus_point_side(self, side: str):
        if side == "left":
            attr = "_focus_point_item_left"
        elif side == "right":
            attr = "_focus_point_item_right"
        else:
            return

        item = getattr(self, attr, None)
        if not item:
            return
        try:
            if item.scene():
                item.scene().removeItem(item)
        except Exception:
            pass
        try:
            setattr(self, attr, None)
        except Exception:
            pass
            
    def zoom_to_bird(self):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        if self.compare_mode:
            if getattr(self, "_is_zoomed_to_bird_compare", False):
                if self.view_left and self.pixmap_item_left:
                    self._fit_view(self.view_left, self.pixmap_item_left)
                if self.view_right and self.pixmap_item_right:
                    self._fit_view(self.view_right, self.pixmap_item_right)
                self._is_zoomed_to_bird_compare = False
                return

            left_index = getattr(self, "saved_left_index", None)
            right_index = self.current_index
            if left_index is None or left_index < 0 or left_index >= len(self.image_list):
                return
            if right_index < 0 or right_index >= len(self.image_list):
                return

            left_bbox = self.image_list[left_index].get("bbox")
            right_bbox = self.image_list[right_index].get("bbox")

            left_size = self._get_pixmap_size_for_scene(self.scene_left)
            right_size = self._get_pixmap_size_for_scene(self.scene_right)
            left_path = None
            right_path = None
            try:
                left_path = self.image_list[left_index].get("path")
            except Exception:
                left_path = None
            try:
                right_path = self.image_list[right_index].get("path")
            except Exception:
                right_path = None
            left_rect, _ = self._bbox_to_rect_and_xywh(left_bbox, image_size=left_size, orig_size=self._get_orig_size_for_path(left_path))
            right_rect, _ = self._bbox_to_rect_and_xywh(right_bbox, image_size=right_size, orig_size=self._get_orig_size_for_path(right_path))

            any_zoom = False
            if left_rect is not None and not left_rect.isNull() and self.view_left:
                self._zoom_view_to_rect(self.view_left, left_rect)
                any_zoom = True
            elif self.view_left and self.pixmap_item_left:
                self._fit_view(self.view_left, self.pixmap_item_left)

            if right_rect is not None and not right_rect.isNull() and self.view_right:
                self._zoom_view_to_rect(self.view_right, right_rect)
                any_zoom = True
            elif self.view_right and self.pixmap_item_right:
                self._fit_view(self.view_right, self.pixmap_item_right)

            self._is_zoomed_to_bird_compare = any_zoom
            if not any_zoom:
                try:
                    NotificationManager.instance().show_toast("未找到主体信息")
                except Exception:
                    pass
            return

        if getattr(self, "_is_zoomed_to_bird", False):
            if self.view and self.pixmap_item:
                self._fit_view(self.view, self.pixmap_item)
            self._is_zoomed_to_bird = False
            return

        if not self.image_list or self.current_index < 0 or self.current_index >= len(self.image_list):
            return

        bbox = self.image_list[self.current_index].get("bbox")
        target_scene = self.scene
        if not target_scene:
            return

        image_size = self._get_pixmap_size_for_scene(target_scene)
        cur_path = None
        try:
            cur_path = self.image_list[self.current_index].get("path")
        except Exception:
            cur_path = None
        rect, _ = self._bbox_to_rect_and_xywh(bbox, image_size=image_size, orig_size=self._get_orig_size_for_path(cur_path))
        if rect and not rect.isNull() and self.view:
            self._zoom_view_to_rect(self.view, rect)
            self._is_zoomed_to_bird = True
        else:
            try:
                NotificationManager.instance().show_toast("未找到主体信息")
            except Exception:
                pass

    def _on_subject_rect_display_toggled(self, checked: bool):
        try:
            self._subject_rect_display_enabled = bool(checked)
        except Exception:
            self._subject_rect_display_enabled = False
        try:
            sm = getattr(getattr(self, "cache_manager", None), "settings_manager", None)
            if sm is not None:
                sm.set("focus_detect_ui/show_subject_rect", bool(checked))
                sm.sync()
        except Exception:
            pass
        try:
            if hasattr(self, "btn_show_subject_rect") and self.btn_show_subject_rect is not None:
                self._apply_toolbar_toggle_button_style(self.btn_show_subject_rect, active=bool(checked))
        except Exception:
            pass
        self._refresh_subject_rect_overlay()

    def _on_focus_point_display_toggled(self, checked: bool):
        try:
            self._focus_point_display_enabled = bool(checked)
        except Exception:
            self._focus_point_display_enabled = False
        try:
            sm = getattr(getattr(self, "cache_manager", None), "settings_manager", None)
            if sm is not None:
                sm.set("focus_detect_ui/show_focus_point", bool(checked))
                sm.sync()
        except Exception:
            pass
        try:
            if hasattr(self, "btn_zoom_to_focus") and self.btn_zoom_to_focus is not None:
                self._apply_toolbar_toggle_button_style(self.btn_zoom_to_focus, active=bool(checked))
        except Exception:
            pass
        try:
            if bool(checked):
                self.detect_subject(force=False)
        except Exception:
            pass
        self._refresh_focus_point_overlay()

    def _refresh_subject_rect_overlay(self):
        try:
            enabled = bool(getattr(self, "_subject_rect_display_enabled", False))
        except Exception:
            enabled = False
        try:
            focus_enabled = bool(getattr(self, "_focus_point_display_enabled", False))
        except Exception:
            focus_enabled = False
        def _is_missing_xy(v) -> bool:
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
                return _is_missing_xy(obj)
            if isinstance(v, dict):
                if "x" in v and "y" in v:
                    try:
                        float(v.get("x"))
                        float(v.get("y"))
                        return False
                    except Exception:
                        return True
                return True
            if isinstance(v, (list, tuple)):
                return len(v) < 2
            return False

        if self.compare_mode:
            try:
                self._clear_subject_rect()
            except Exception:
                pass
            try:
                self._clear_eye_rect()
            except Exception:
                pass
            left_index = getattr(self, "saved_left_index", None)
            right_index = self.current_index
            try:
                left_index = int(left_index) if left_index is not None else None
            except Exception:
                left_index = None
            try:
                right_index = int(right_index)
            except Exception:
                right_index = -1

            def _parse_xy(v):
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

            def _get_bbox_from_fd(fdj):
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
                        return fd.get("bbox_orig") or fd.get("bbox")
                    except Exception:
                        return None
                return None

            def _get_eye(i: int):
                if i is None or i < 0 or i >= len(self.image_list):
                    return None, None, None
                info0 = self.image_list[i]
                p0 = info0.get("path")
                eye0 = info0.get("eye_coordinates")
                eye_xy = _parse_xy(eye0)
                record0 = None
                if not eye_xy and p0:
                    try:
                        record0 = self._get_record_for_path(p0)
                    except Exception:
                        record0 = None
                    if isinstance(record0, dict):
                        try:
                            eye_xy = _parse_xy(record0.get("eye_coordinates"))
                        except Exception:
                            eye_xy = eye_xy
                if not eye_xy:
                    fdj = None
                    try:
                        fdj = info0.get("focus_detect_json")
                    except Exception:
                        fdj = None
                    if not fdj and isinstance(record0, dict):
                        try:
                            fdj = record0.get("focus_detect_json")
                        except Exception:
                            fdj = fdj
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
                            eye_xy = _parse_xy(fd.get("eye_coordinates") or fd.get("eye"))
                        except Exception:
                            eye_xy = eye_xy
                if not eye_xy:
                    return None, None, p0
                return eye_xy[0], eye_xy[1], p0

            def _add_eye(scene, size, ex, ey, attr: str, path: str):
                if scene is None or size is None or ex is None or ey is None:
                    return
                try:
                    w, h = int(size[0]), int(size[1])
                except Exception:
                    return
                is_normalized = (0.0 <= float(ex) <= 1.0 and 0.0 <= float(ey) <= 1.0)
                mapped = None
                try:
                    mapped = self._map_point_to_scene_xy(ex, ey, str(path or ""), int(w), int(h), is_normalized=bool(is_normalized))
                except Exception:
                    mapped = None
                if mapped is None:
                    scene_x = float(ex) * float(w) if is_normalized else float(ex)
                    scene_y = float(ey) * float(h) if is_normalized else float(ey)
                else:
                    scene_x, scene_y = mapped
                try:
                    r = 8.0
                except Exception:
                    r = 8.0
                item = QGraphicsRectItem(QRectF(scene_x - r, scene_y - r, 2 * r, 2 * r))
                c = QColor("#2196F3")
                c.setAlpha(240)
                pen = QPen(c, 3)
                pen.setCosmetic(False)
                item.setPen(pen)
                item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                item.setZValue(101)
                scene.addItem(item)
                try:
                    setattr(self, attr, item)
                except Exception:
                    pass

            if left_index is not None and 0 <= left_index < len(self.image_list):
                try:
                    left_info = self.image_list[left_index]
                    left_path = left_info.get("path")
                    left_bbox = left_info.get("bbox")
                    if not left_bbox:
                        try:
                            left_bbox = _get_bbox_from_fd(left_info.get("focus_detect_json"))
                        except Exception:
                            left_bbox = left_bbox
                        if left_bbox:
                            left_info["bbox"] = left_bbox
                    if left_path and not left_bbox:
                        try:
                            record0 = self._get_record_for_path(left_path)
                        except Exception:
                            record0 = None
                        if isinstance(record0, dict):
                            try:
                                left_bbox = record0.get("bbox")
                            except Exception:
                                left_bbox = left_bbox
                            if not left_bbox:
                                try:
                                    left_bbox = _get_bbox_from_fd(record0.get("focus_detect_json"))
                                except Exception:
                                    left_bbox = left_bbox
                            if left_bbox:
                                left_info["bbox"] = left_bbox
                    left_size = self._get_pixmap_size_for_scene(self.scene_left)
                    left_rect, _ = self._bbox_to_rect_and_xywh(left_bbox, image_size=left_size, orig_size=self._get_orig_size_for_path(left_path))
                    if enabled and left_rect is not None and not left_rect.isNull():
                        self._draw_subject_rect(left_rect, self.scene_left, left_path)
                    if enabled:
                        ex, ey, p0 = _get_eye(left_index)
                        _add_eye(self.scene_left, left_size, ex, ey, "_eye_rect_item_left", p0)
                except Exception:
                    pass

            if 0 <= right_index < len(self.image_list):
                try:
                    right_info = self.image_list[right_index]
                    right_path = right_info.get("path")
                    right_bbox = right_info.get("bbox")
                    if not right_bbox:
                        try:
                            right_bbox = _get_bbox_from_fd(right_info.get("focus_detect_json"))
                        except Exception:
                            right_bbox = right_bbox
                        if right_bbox:
                            right_info["bbox"] = right_bbox
                    if right_path and not right_bbox:
                        try:
                            record0 = self._get_record_for_path(right_path)
                        except Exception:
                            record0 = None
                        if isinstance(record0, dict):
                            try:
                                right_bbox = record0.get("bbox")
                            except Exception:
                                right_bbox = right_bbox
                            if not right_bbox:
                                try:
                                    right_bbox = _get_bbox_from_fd(record0.get("focus_detect_json"))
                                except Exception:
                                    right_bbox = right_bbox
                            if right_bbox:
                                right_info["bbox"] = right_bbox
                    right_size = self._get_pixmap_size_for_scene(self.scene_right)
                    right_rect, _ = self._bbox_to_rect_and_xywh(right_bbox, image_size=right_size, orig_size=self._get_orig_size_for_path(right_path))
                    if enabled and right_rect is not None and not right_rect.isNull():
                        self._draw_subject_rect(right_rect, self.scene_right, right_path)
                    if enabled:
                        ex, ey, p0 = _get_eye(right_index)
                        _add_eye(self.scene_right, right_size, ex, ey, "_eye_rect_item_right", p0)
                except Exception:
                    pass
            return

        try:
            self._clear_subject_rect()
        except Exception:
            pass
        try:
            self._clear_eye_rect()
        except Exception:
            pass
        try:
            idx = int(self.current_index)
        except Exception:
            idx = -1
        if not self.image_list or idx < 0 or idx >= len(self.image_list):
            return
        try:
            info = self.image_list[idx]
            path = info.get("path")
            bbox = info.get("bbox")
            eye0 = info.get("eye_coordinates")
        except Exception:
            path = None
            bbox = None
            eye0 = None
        if not bbox:
            try:
                bbox = _get_bbox_from_fd(info.get("focus_detect_json"))
            except Exception:
                bbox = bbox
            if bbox:
                try:
                    info["bbox"] = bbox
                except Exception:
                    pass
        if path and not bbox:
            try:
                record = self._get_record_for_path(path)
                if record and "bbox" in record:
                    bbox = record.get("bbox")
                    info["bbox"] = bbox
            except Exception:
                bbox = bbox
        if path and not bbox:
            try:
                record = self._get_record_for_path(path)
            except Exception:
                record = None
            if isinstance(record, dict):
                try:
                    bbox = _get_bbox_from_fd(record.get("focus_detect_json"))
                except Exception:
                    bbox = bbox
                if bbox:
                    try:
                        info["bbox"] = bbox
                    except Exception:
                        pass
        if path and _is_missing_xy(eye0):
            try:
                record = self._get_record_for_path(path)
            except Exception:
                record = None
            if isinstance(record, dict):
                try:
                    eye0 = record.get("eye_coordinates")
                except Exception:
                    eye0 = eye0
                if not eye0:
                    try:
                        fdj = record.get("focus_detect_json")
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
                            eye0 = fd.get("eye_coordinates") or fd.get("eye")
                        except Exception:
                            eye0 = eye0
        if not path:
            return
        try:
            now = float(time.time())
        except Exception:
            now = 0.0
        try:
            last_p = str(getattr(self, "_big_overlay_warn_path", "") or "")
        except Exception:
            last_p = ""
        try:
            last_ts = float(getattr(self, "_big_overlay_warn_ts", 0.0) or 0.0)
        except Exception:
            last_ts = 0.0
        do_warn = False
        try:
            do_warn = (last_p != str(path)) or (now - last_ts > 2.0)
        except Exception:
            do_warn = False
        try:
            if do_warn:
                self._big_overlay_warn_path = str(path)
                self._big_overlay_warn_ts = float(now)
        except Exception:
            pass
        try:
            image_size = self._get_pixmap_size_for_scene(self.scene)
        except Exception:
            image_size = None
        if bbox:
            rect, _ = self._bbox_to_rect_and_xywh(bbox, image_size=image_size, orig_size=self._get_orig_size_for_path(path))
            if enabled and rect is not None and not rect.isNull():
                try:
                    self._draw_subject_rect(rect, self.scene, path)
                except Exception:
                    pass
        eye_xy = None
        try:
            if isinstance(eye0, str):
                s = eye0.strip()
                if s:
                    eye0 = json.loads(s)
        except Exception:
            pass
        try:
            if isinstance(eye0, dict) and "x" in eye0 and "y" in eye0:
                eye_xy = (float(eye0.get("x")), float(eye0.get("y")))
            elif isinstance(eye0, (list, tuple)) and len(eye0) >= 2:
                eye_xy = (float(eye0[0]), float(eye0[1]))
        except Exception:
            eye_xy = None
        if not eye_xy:
            fdj = None
            try:
                fdj = info.get("focus_detect_json")
            except Exception:
                fdj = None
            if not fdj and path:
                try:
                    record = self._get_record_for_path(path)
                except Exception:
                    record = None
                if isinstance(record, dict):
                    try:
                        fdj = record.get("focus_detect_json")
                    except Exception:
                        fdj = fdj
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
                    v = fd.get("eye_coordinates") or fd.get("eye")
                except Exception:
                    v = None
                try:
                    if isinstance(v, str):
                        sv = v.strip()
                        if sv:
                            v = json.loads(sv)
                except Exception:
                    v = v
                try:
                    if isinstance(v, dict) and "x" in v and "y" in v:
                        eye_xy = (float(v.get("x")), float(v.get("y")))
                    elif isinstance(v, (list, tuple)) and len(v) >= 2:
                        eye_xy = (float(v[0]), float(v[1]))
                except Exception:
                    eye_xy = eye_xy
        if enabled and eye_xy and image_size is not None:
            try:
                w, h = int(image_size[0]), int(image_size[1])
            except Exception:
                w = h = 0
            if w > 0 and h > 0:
                ex, ey = eye_xy
                is_normalized = (0.0 <= float(ex) <= 1.0 and 0.0 <= float(ey) <= 1.0)
                mapped = None
                try:
                    mapped = self._map_point_to_scene_xy(ex, ey, str(path or ""), int(w), int(h), is_normalized=bool(is_normalized))
                except Exception:
                    mapped = None
                if mapped is None:
                    scene_x = float(ex) * float(w) if is_normalized else float(ex)
                    scene_y = float(ey) * float(h) if is_normalized else float(ey)
                else:
                    scene_x, scene_y = mapped
                try:
                    r = 8.0
                except Exception:
                    r = 8.0
                try:
                    item = QGraphicsRectItem(QRectF(scene_x - r, scene_y - r, 2 * r, 2 * r))
                    c = QColor("#2196F3")
                    c.setAlpha(240)
                    pen = QPen(c, 3)
                    pen.setCosmetic(False)
                    item.setPen(pen)
                    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    item.setZValue(101)
                    self.scene.addItem(item)
                    self._eye_rect_item = item
                    self._eye_rect_path = path
                    try:
                        if bool(do_warn):
                            vpos = None
                            try:
                                vpos = self.view.mapFromScene(QPointF(float(scene_x), float(scene_y)))
                            except Exception:
                                vpos = None
                            try:
                                vw = int(self.view.viewport().width() or 0)
                                vh = int(self.view.viewport().height() or 0)
                            except Exception:
                                vw = vh = 0
                    except Exception:
                        pass
                    try:
                        self.scene.update()
                    except Exception:
                        pass
                    try:
                        self.view.viewport().update()
                    except Exception:
                        pass
                except Exception as e:
                    LogManager.instance().warning(f"[大图叠加] eye_add_failed path={path} err={repr(e)}")

    def _refresh_focus_point_overlay(self):
        try:
            enabled = bool(getattr(self, "_focus_point_display_enabled", False))
        except Exception:
            enabled = False
        def _is_missing_fp(v) -> bool:
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
                return _is_missing_fp(obj)
            if isinstance(v, (list, tuple)):
                return len(v) < 2
            if isinstance(v, dict):
                if "x" in v and "y" in v:
                    try:
                        float(v.get("x"))
                        float(v.get("y"))
                        return False
                    except Exception:
                        return True
                return True
            return False

        if self.compare_mode:
            try:
                self._clear_focus_point()
            except Exception:
                pass
            if not enabled:
                return

            left_index = getattr(self, "saved_left_index", None)
            right_index = self.current_index
            try:
                left_index = int(left_index) if left_index is not None else None
            except Exception:
                left_index = None
            try:
                right_index = int(right_index)
            except Exception:
                right_index = -1

            def _get_fp(i: int):
                if i is None or i < 0 or i >= len(self.image_list):
                    return None, None, None
                info = self.image_list[i]
                fp = info.get("focus_point")
                if _is_missing_fp(fp):
                    try:
                        p = info.get("path")
                        if p:
                            record = self._get_record_for_path(p)
                            if isinstance(record, dict):
                                try:
                                    fp0 = record.get("focus_point")
                                except Exception:
                                    fp0 = None
                                if not _is_missing_fp(fp0):
                                    fp = fp0
                                    info["focus_point"] = fp
                                else:
                                    fd = None
                                    try:
                                        fdj = record.get("focus_detect_json")
                                    except Exception:
                                        fdj = None
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
                                            fp1 = fd.get("focus_point")
                                        except Exception:
                                            fp1 = None
                                        if not _is_missing_fp(fp1):
                                            fp = fp1
                                            info["focus_point"] = fp
                    except Exception:
                        fp = fp
                fx = fy = None
                mode_ok = False
                if isinstance(fp, dict):
                    try:
                        mode = str(fp.get("mode") or "").lower()
                        mode_ok = (mode == "global") or (mode == "")
                    except Exception:
                        mode_ok = False
                    fx, fy = fp.get("x"), fp.get("y")
                elif isinstance(fp, (list, tuple)) and len(fp) >= 2:
                    try:
                        mode_ok = True
                        fx, fy = float(fp[0]), float(fp[1])
                    except Exception:
                        fx = fy = None
                elif isinstance(fp, str):
                    try:
                        d = json.loads(fp)
                        if isinstance(d, dict):
                            try:
                                mode = str(d.get("mode") or "").lower()
                                mode_ok = (mode == "global") or (mode == "")
                            except Exception:
                                mode_ok = False
                            fx, fy = d.get("x"), d.get("y")
                        elif isinstance(d, list) and len(d) >= 2:
                            mode_ok = True
                            fx, fy = float(d[0]), float(d[1])
                    except Exception:
                        fx = fy = None
                if not mode_ok:
                    fx = fy = None
                try:
                    p0 = info.get("path")
                except Exception:
                    p0 = None
                return fx, fy, p0

            icon = qta.icon("mdi6.focus-field", color=ColorManager.instance().to_qss_color("border.subject_rect", default="red"))
            pixmap = icon.pixmap(QSize(40, 40))

            def _add(scene, size, fx, fy, attr: str, path: str):
                if scene is None or size is None or fx is None or fy is None:
                    return
                try:
                    w, h = int(size[0]), int(size[1])
                except Exception:
                    return
                is_normalized = (0 <= fx <= 1.0 and 0 <= fy <= 1.0)
                mapped = None
                try:
                    mapped = self._map_point_to_scene_xy(fx, fy, str(path or ""), int(w), int(h), is_normalized=bool(is_normalized))
                except Exception:
                    mapped = None
                if mapped is None:
                    scene_x = fx * w if is_normalized else fx
                    scene_y = fy * h if is_normalized else fy
                else:
                    scene_x, scene_y = mapped
                item = QGraphicsPixmapItem(pixmap)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                item.setPos(scene_x, scene_y)
                item.setOffset(-20, -20)
                item.setZValue(100)
                scene.addItem(item)
                try:
                    setattr(self, attr, item)
                except Exception:
                    pass

            left_fx, left_fy, left_path = _get_fp(left_index) if left_index is not None else (None, None, None)
            right_fx, right_fy, right_path = _get_fp(right_index)
            _add(self.scene_left, self._get_pixmap_size_for_scene(self.scene_left), left_fx, left_fy, "_focus_point_item_left", left_path)
            _add(self.scene_right, self._get_pixmap_size_for_scene(self.scene_right), right_fx, right_fy, "_focus_point_item_right", right_path)
            return

        try:
            self._clear_focus_point()
        except Exception:
            pass
        if not enabled:
            return
        try:
            idx = int(self.current_index)
        except Exception:
            idx = -1
        if not self.image_list or idx < 0 or idx >= len(self.image_list):
            return
        img_info = self.image_list[idx]
        focus_point = img_info.get("focus_point")
        if _is_missing_fp(focus_point):
            try:
                path = img_info.get("path")
                if path:
                    record = self._get_record_for_path(path)
                    if isinstance(record, dict):
                        try:
                            fp0 = record.get("focus_point")
                        except Exception:
                            fp0 = None
                        if not _is_missing_fp(fp0):
                            focus_point = fp0
                            img_info["focus_point"] = focus_point
                        else:
                            fd = None
                            try:
                                fdj = record.get("focus_detect_json")
                            except Exception:
                                fdj = None
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
                                    fp1 = fd.get("focus_point")
                                except Exception:
                                    fp1 = None
                                if not _is_missing_fp(fp1):
                                    focus_point = fp1
                                    img_info["focus_point"] = focus_point
            except Exception:
                focus_point = focus_point
        try:
            pass
        except Exception:
            pass
        fx = fy = None
        mode_ok = False
        if isinstance(focus_point, dict):
            try:
                mode = str(focus_point.get("mode") or "").lower()
                mode_ok = (mode == "global") or (mode == "")
            except Exception:
                mode_ok = False
            fx, fy = focus_point.get("x"), focus_point.get("y")
        elif isinstance(focus_point, (list, tuple)) and len(focus_point) >= 2:
            try:
                mode_ok = True
                fx, fy = float(focus_point[0]), float(focus_point[1])
            except Exception:
                fx = fy = None
        elif isinstance(focus_point, str):
            try:
                d = json.loads(focus_point)
                if isinstance(d, dict):
                    try:
                        mode = str(d.get("mode") or "").lower()
                        mode_ok = (mode == "global") or (mode == "")
                    except Exception:
                        mode_ok = False
                    fx, fy = d.get("x"), d.get("y")
                elif isinstance(d, list) and len(d) >= 2:
                    mode_ok = True
                    fx, fy = float(d[0]), float(d[1])
            except Exception:
                fx = fy = None
        if not mode_ok:
            fx = fy = None
        if fx is None or fy is None:
            return
        target_scene = self.scene
        image_size = self._get_pixmap_size_for_scene(target_scene)
        if not image_size:
            return
        w, h = image_size
        is_normalized = (0 <= fx <= 1.0 and 0 <= fy <= 1.0)
        mapped = None
        try:
            mapped = self._map_point_to_scene_xy(fx, fy, str(img_info.get("path") or ""), int(w), int(h), is_normalized=bool(is_normalized))
        except Exception:
            mapped = None
        if mapped is None:
            scene_x = fx * w if is_normalized else fx
            scene_y = fy * h if is_normalized else fy
        else:
            scene_x, scene_y = mapped
        icon = qta.icon("mdi6.focus-field", color=ColorManager.instance().to_qss_color("border.subject_rect", default="red"))
        pixmap = icon.pixmap(QSize(40, 40))
        self._focus_point_item = QGraphicsPixmapItem(pixmap)
        self._focus_point_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._focus_point_item.setPos(scene_x, scene_y)
        self._focus_point_item.setOffset(-20, -20)
        self._focus_point_item.setZValue(100)
        target_scene.addItem(self._focus_point_item)

    def zoom_to_focus(self):
        try:
            self._auto_nav_pause_if_needed()
        except Exception:
            pass
        try:
            if hasattr(self, "btn_zoom_to_focus") and self.btn_zoom_to_focus is not None and self.btn_zoom_to_focus.isCheckable():
                self.btn_zoom_to_focus.setChecked(not bool(self.btn_zoom_to_focus.isChecked()))
                return
        except Exception:
            pass
        if self.compare_mode:
            if getattr(self, "_focus_point_item_left", None) or getattr(self, "_focus_point_item_right", None):
                self._clear_focus_point()
                return

            left_index = getattr(self, "saved_left_index", None)
            right_index = self.current_index
            if left_index is None or left_index < 0 or left_index >= len(self.image_list):
                return
            if right_index < 0 or right_index >= len(self.image_list):
                return

            def get_focus(index: int):
                info = self.image_list[index]
                fp = info.get("focus_point")
                if not fp:
                    try:
                        p = info.get("path")
                        if p:
                            record = self._get_record_for_path(p)
                            if record and "focus_point" in record:
                                fp = record["focus_point"]
                                info["focus_point"] = fp
                    except Exception:
                        fp = fp

                fx = fy = None
                if isinstance(fp, dict):
                    fx, fy = fp.get("x"), fp.get("y")
                elif isinstance(fp, (list, tuple)) and len(fp) >= 2:
                    try:
                        fx, fy = float(fp[0]), float(fp[1])
                    except Exception:
                        fx = fy = None
                elif isinstance(fp, str):
                    try:
                        d = json.loads(fp)
                        fx, fy = d.get("x"), d.get("y")
                    except Exception:
                        fx = fy = None
                return fx, fy

            left_fx, left_fy = get_focus(left_index)
            right_fx, right_fy = get_focus(right_index)

            any_added = False
            icon = qta.icon("mdi6.focus-field", color=ColorManager.instance().to_qss_color("border.subject_rect", default="red"))
            pixmap = icon.pixmap(QSize(40, 40))

            def add_item(scene, w: int, h: int, fx, fy, attr: str, orig_size=None):
                nonlocal any_added
                if fx is None or fy is None or scene is None:
                    return
                is_normalized = (0 <= fx <= 1.0 and 0 <= fy <= 1.0)
                scene_x = fx * w if is_normalized else fx
                scene_y = fy * h if is_normalized else fy
                if not is_normalized and orig_size is not None:
                    try:
                        ow, oh = int(orig_size[0]), int(orig_size[1])
                    except Exception:
                        ow, oh = 0, 0
                    try:
                        if ow > 0 and oh > 0 and (int(w) != int(ow) or int(h) != int(oh)):
                            scene_x = float(scene_x) * float(w) / float(ow)
                            scene_y = float(scene_y) * float(h) / float(oh)
                    except Exception:
                        pass
                item = QGraphicsPixmapItem(pixmap)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                item.setPos(scene_x, scene_y)
                item.setOffset(-20, -20)
                item.setZValue(100)
                scene.addItem(item)
                setattr(self, attr, item)
                any_added = True

            left_size = self._get_pixmap_size_for_scene(self.scene_left)
            if left_size:
                left_orig = None
                try:
                    left_orig = self._get_orig_size_for_path(self.image_list[left_index].get("path"))
                except Exception:
                    left_orig = None
                add_item(self.scene_left, left_size[0], left_size[1], left_fx, left_fy, "_focus_point_item_left", orig_size=left_orig)
            right_size = self._get_pixmap_size_for_scene(self.scene_right)
            if right_size:
                right_orig = None
                try:
                    right_orig = self._get_orig_size_for_path(self.image_list[right_index].get("path"))
                except Exception:
                    right_orig = None
                add_item(self.scene_right, right_size[0], right_size[1], right_fx, right_fy, "_focus_point_item_right", orig_size=right_orig)

            if not any_added:
                try:
                    NotificationManager.instance().show_toast("未找到对焦点数据，请先检测主体")
                except Exception:
                    pass
            return

        if getattr(self, "_focus_point_item", None):
            self._clear_focus_point()
            return

        if not self.image_list or self.current_index < 0 or self.current_index >= len(self.image_list):
            return

        img_info = self.image_list[self.current_index]
        focus_point = img_info.get("focus_point")
        if not focus_point:
            try:
                path = img_info.get("path")
                if path:
                    record = self._get_record_for_path(path)
                    if record and "focus_point" in record:
                        focus_point = record["focus_point"]
                        img_info["focus_point"] = focus_point
            except Exception:
                pass

        if not focus_point:
            try:
                NotificationManager.instance().show_toast("未找到对焦点数据，请先检测主体")
            except Exception:
                pass
            return

        fx = fy = None
        if isinstance(focus_point, dict):
            fx, fy = focus_point.get("x"), focus_point.get("y")
        elif isinstance(focus_point, (list, tuple)) and len(focus_point) >= 2:
            try:
                fx, fy = float(focus_point[0]), float(focus_point[1])
            except Exception:
                fx = fy = None
        elif isinstance(focus_point, str):
            try:
                d = json.loads(focus_point)
                fx, fy = d.get("x"), d.get("y")
            except Exception:
                fx = fy = None

        if fx is None or fy is None:
            return

        target_scene = self.scene
        image_size = self._get_pixmap_size_for_scene(target_scene)
        if not image_size:
            try:
                now = float(time.time())
                last_ts = float(getattr(self, "_focus_point_retry_ts", 0.0) or 0.0)
                retries = int(getattr(self, "_focus_point_retry_count", 0) or 0)
                if now - last_ts > 0.2:
                    retries = 0
                if retries < 6:
                    self._focus_point_retry_ts = now
                    self._focus_point_retry_count = retries + 1
                    QTimer.singleShot(60, self.zoom_to_focus)
            except Exception:
                pass
            return

        w, h = image_size
        is_normalized = (0 <= fx <= 1.0 and 0 <= fy <= 1.0)
        scene_x = fx * w if is_normalized else fx
        scene_y = fy * h if is_normalized else fy
        if not is_normalized:
            orig_size = None
            try:
                orig_size = self._get_orig_size_for_path(img_info.get("path"))
            except Exception:
                orig_size = None
            if orig_size is not None:
                try:
                    ow, oh = int(orig_size[0]), int(orig_size[1])
                except Exception:
                    ow, oh = 0, 0
                try:
                    if ow > 0 and oh > 0 and (int(w) != int(ow) or int(h) != int(oh)):
                        scene_x = float(scene_x) * float(w) / float(ow)
                        scene_y = float(scene_y) * float(h) / float(oh)
                except Exception:
                    pass

        icon = qta.icon("mdi6.focus-field", color=ColorManager.instance().to_qss_color("border.subject_rect", default="red"))
        pixmap = icon.pixmap(QSize(40, 40))
        self._focus_point_item = QGraphicsPixmapItem(pixmap)
        self._focus_point_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._focus_point_item.setPos(scene_x, scene_y)
        self._focus_point_item.setOffset(-20, -20)
        self._focus_point_item.setZValue(100)
        target_scene.addItem(self._focus_point_item)

    
    def _update_thumbnail_by_path(self, path):
        """根据路径更新对应的缩略图显示"""
        for i, info in enumerate(self.image_list):
            if info['path'] == path:
                if 0 <= i < len(self.thumbnail_widgets):
                    self.thumbnail_widgets[i].update()
                break

    def toggle_favorite(self, target_path=None):
        path = target_path
        img_info = None
        
        # 如果没有指定路径，默认使用当前图片
        if path is None:
            if not self.image_list or self.current_index < 0 or self.current_index >= len(self.image_list):
                return
            img_info = self.image_list[self.current_index]
            path = img_info['path']
        else:
            # 尝试在 image_list 中找到对应 info，以便更新内存中的状态
            # 如果找不到（比如左侧图片不在当前列表？理论上应该在），就只更新 DB
            for info in self.image_list:
                if info['path'] == path:
                    img_info = info
                    break

        # 获取当前状态 (优先从内存获取，否则假设为0，实际应该查库)
        current_fav = 0
        if img_info:
            current_fav = img_info.get('is_favorite', img_info.get('favorite', 0))
        else:
            # 如果 img_info 为空，尝试从 overlay 获取或者直接查库
            # 简化起见，我们查库
            try:
                record = self.db.get_image_info(path)
                if record:
                    current_fav = record.get('is_favorite', record.get('favorite', 0))
            except:
                pass

        new_fav = 0 if current_fav == 1 else 1

        # 更新数据库
        try:
            # 根据表名选择正确的更新方法
            if getattr(self, "_db_table_name", "bird_results") == "import_cache":
                self.db.update_user_field_batch_for_table([path], "is_favorite", new_fav, table_name="import_cache")
            else:
                self.db.update_favorite_batch([path], new_fav)
            if img_info:
                img_info['favorite'] = new_fav # 更新内存
                img_info['is_favorite'] = new_fav

            # 更新界面
            self.update_fav_rating_status()

            # 更新底部缩略图
            self._update_thumbnail_by_path(path)

            # 如果在对比模式，更新对应的 Overlay
            if self.compare_mode:
                if hasattr(self, 'overlay_left') and self.overlay_left and self.overlay_left.path == path:
                    self._update_overlay_data(path, self.overlay_left, self.info_overlay_left)
                if hasattr(self, 'overlay_right') and self.overlay_right and self.overlay_right.path == path:
                    self._update_overlay_data(path, self.overlay_right, self.info_overlay_right)

            # 发送信号
            self.favorite_changed.emit(path, new_fav == 1)
            try:
                LogManager.instance().info(f"收藏切换: fav={new_fav} path={path}")
            except Exception:
                pass
        except Exception as e:
            try:
                LogManager.instance().warning(f"切换收藏失败: {e}")
            except Exception:
                pass

    def set_rating(self, rating, target_path=None):
        path = target_path
        img_info = None
        
        if path is None:
            if not self.image_list or self.current_index < 0 or self.current_index >= len(self.image_list):
                return
            img_info = self.image_list[self.current_index]
            path = img_info['path']
        else:
            for info in self.image_list:
                if info['path'] == path:
                    img_info = info
                    break
        
        # 更新数据库
        try:
            # 根据表名选择正确的更新方法
            if getattr(self, "_db_table_name", "bird_results") == "import_cache":
                self.db.update_user_field_batch_for_table([path], "rating", rating, table_name="import_cache")
            else:
                self.db.update_rating_batch([path], rating)
            if img_info:
                img_info['rating'] = rating # 更新内存

            # 更新界面
            self.update_fav_rating_status()

            # 更新底部缩略图
            self._update_thumbnail_by_path(path)

            # 如果在对比模式，更新对应的 Overlay
            if self.compare_mode:
                if hasattr(self, 'overlay_left') and self.overlay_left and self.overlay_left.path == path:
                    self._update_overlay_data(path, self.overlay_left, self.info_overlay_left)
                if hasattr(self, 'overlay_right') and self.overlay_right and self.overlay_right.path == path:
                    self._update_overlay_data(path, self.overlay_right, self.info_overlay_right)

            # 发送信号
            self.rating_changed.emit(path, rating)
            try:
                LogManager.instance().info(f"评分设置: rating={rating} path={path}")
            except Exception:
                pass
        except Exception as e:
            try:
                LogManager.instance().warning(f"设置评分失败: {e}")
            except Exception:
                pass

    def toggle_rating(self):
        # 已弃用，使用 StarRatingWidget 的 set_rating
        pass

    def open_external(self):
        path = self.image_list[self.current_index]['path']
        try:
            app_path = str(SettingsManager().get("external/open_image_app", "") or "").strip()
            if app_path:
                if not os.path.exists(app_path):
                    NotificationManager.instance().show_warning("错误", "外部打开软件路径无效，请在设置页配置")
                    return
                import subprocess
                subprocess.Popen([app_path, str(path)])
                return
            import platform
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"外部打开失败: {e}")

    def update_fav_rating_status(self):
        if not self.image_list or self.current_index < 0 or self.current_index >= len(self.image_list):
            return

        img_info = self.image_list[self.current_index]
        path = img_info['path']
        
        # 只需要更新当前主视图的 Overlay (如果不是对比模式)
        if not self.compare_mode and hasattr(self, 'overlay_main') and self.overlay_main:
             self._update_overlay_data(path, self.overlay_main, self.info_overlay_main)
