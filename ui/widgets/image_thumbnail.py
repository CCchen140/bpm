import os
import time
import json
from PyQt6.QtWidgets import QWidget

from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF
from PyQt6.QtGui import QPixmap, QFont, QColor, QPen, QRadialGradient, QBrush, QPainter, QLinearGradient
from ui.utils.icon_loader import qta

from cache.cache_manager import ImageCacheManager
from utils.system.gpu_utils import GPUScaler
from ui.utils.color_manager import ColorManager
from utils.log_manager import LogManager

class ThumbnailOverlay(QWidget):
    """覆盖在缩略图上的透明层，用于绘制清晰的矢量图标"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.image_info = None
        self.parent_thumbnail = parent
        
    def set_image_info(self, info):
        self.image_info = info
        self.update()
        
    def paintEvent(self, event):
        if not self.image_info:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        margin = 1 + 2
        try:
            w, h = self.parent_thumbnail._get_wh()
        except Exception:
            w, h = self.parent_thumbnail.width(), self.parent_thumbnail.height()
        size_for_calcs = min(w, h)
        img_w = w - 2 * margin 
        img_h = h - 2 * margin
        img_rect = QRect(margin, margin, img_w, img_h)

        is_stashed = bool(self.image_info.get("is_stashed", False))
        if is_stashed and getattr(ImageThumbnail, "_shared_stash_icon", None) is not None:
            icon_size = 16
            margin_left = 4
            margin_top = 4
            x = img_rect.left() + margin_left
            y = img_rect.top() + margin_top
            shadow_rect = QRect(x + 1, y + 1, icon_size, icon_size)
            ImageThumbnail._shared_stash_shadow_icon.paint(painter, shadow_rect)
            icon_rect = QRect(x, y, icon_size, icon_size)
            ImageThumbnail._shared_stash_icon.paint(painter, icon_rect)
        
        # 绘制右上角图标 (收藏 -> 色标 -> 评分 竖向排列)
        icon_size = 20
        spacing = 2
        margin_right = 4
        margin_top = 4
        
        current_y = img_rect.top() + margin_top
        icon_x = img_rect.right() - icon_size - margin_right

        # 1. 收藏图标
        is_fav = self.image_info.get('is_favorite')
        if is_fav:
            # 绘制阴影
            shadow_rect = QRect(icon_x + 1, current_y + 1, icon_size, icon_size)
            ImageThumbnail._shared_fav_shadow_icon.paint(painter, shadow_rect)
            # 绘制图标
            icon_rect = QRect(icon_x, current_y, icon_size, icon_size)
            ImageThumbnail._shared_fav_icon.paint(painter, icon_rect)
            
            current_y += icon_size + spacing

        # 2. 色标图标
        raw_label = self.image_info.get('label')
        manual_label = raw_label.title() if raw_label else None
        raw_auto = self.image_info.get('auto_label')
        auto_label = raw_auto.title() if raw_auto else None
        label = manual_label or auto_label
        
        if label and label in ImageThumbnail.LABEL_COLORS:
            color = QColor(ImageThumbnail.LABEL_COLORS[label])
            
            # 绘制圆点 (14px)
            dot_size = 14
            offset = (icon_size - dot_size) / 2
            # 使用 QRectF 支持浮点坐标，避免类型错误
            rect = QRectF(icon_x + offset, current_y + offset, dot_size, dot_size)
            
            if manual_label:
                gradient = QRadialGradient(
                    rect.x() + dot_size * 0.3,
                    rect.y() + dot_size * 0.3,
                    dot_size * 0.8
                )
                gradient.setColorAt(0, color.lighter(130))
                gradient.setColorAt(0.5, color)
                gradient.setColorAt(1, color.darker(110))
                
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawEllipse(rect)
                
                if label == 'White':
                    painter.setPen(QPen(QColor("#d0d0d0"), 1))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(rect)
            else:
                pen = QPen(color, 2)
                if label == "White":
                    pen = QPen(QColor("#d0d0d0"), 2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(rect)
            
            current_y += icon_size + spacing
                
        # 3. 评分图标
        rating = self.image_info.get('rating', 0)
        if rating > 0:
            # 绘制阴影
            shadow_rect = QRect(icon_x + 1, current_y + 1, icon_size, icon_size)
            ImageThumbnail._shared_rating_shadow_icon.paint(painter, shadow_rect)
            # 绘制图标
            icon_rect = QRect(icon_x, current_y, icon_size, icon_size)
            ImageThumbnail._shared_rating_icon.paint(painter, icon_rect)
            
            # 绘制数字
            painter.setPen(QColor("#333333"))
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(10)
            painter.setFont(font)
            
            text_rect = QRect(icon_x, current_y, icon_size, icon_size)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, str(rating))
            
            current_y += icon_size + spacing

        try:
            bbox0 = self.image_info.get("bbox")
            fp0 = self.image_info.get("focus_point")
            eye0 = self.image_info.get("eye_coordinates")
        except Exception:
            bbox0 = None
            fp0 = None
            eye0 = None
        if bbox0 is None or fp0 is None or eye0 is None:
            fd = None
            try:
                fdj = self.image_info.get("focus_detect_json")
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
                if bbox0 is None:
                    try:
                        bbox0 = fd.get("bbox_orig") or fd.get("bbox")
                    except Exception:
                        pass
                if eye0 is None:
                    try:
                        eye0 = fd.get("eye_coordinates") or fd.get("eye")
                    except Exception:
                        pass
        try:
            sm = getattr(getattr(self.parent_thumbnail, "cache_manager", None), "settings_manager", None)
        except Exception:
            sm = None
        show_bbox = True
        show_fp = True
        show_eye = True
        if sm is not None:
            try:
                show_bbox = bool(sm.get("focus_detect_ui/show_subject_rect", True))
            except Exception:
                show_bbox = True
            try:
                show_fp = bool(sm.get("focus_detect_ui/show_focus_point", True))
            except Exception:
                show_fp = True
        show_eye = bool(show_bbox)
        if not show_bbox:
            bbox0 = None
        if not show_fp:
            fp0 = None
        if not show_eye:
            eye0 = None
        if bbox0 is None and fp0 is None and eye0 is None:
            return

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
                    if all(k in v for k in ("x", "y", "w", "h")):
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
            if isinstance(v, (list, tuple)) and len(v) == 4:
                try:
                    a, b, c, d = [float(x) for x in v]
                except Exception:
                    return None
                if c <= 0.0 or d <= 0.0:
                    return None
                is_normalized = False
                try:
                    is_normalized = (0.0 <= a <= 1.0 and 0.0 <= b <= 1.0 and 0.0 <= c <= 1.0 and 0.0 <= d <= 1.0)
                except Exception:
                    is_normalized = False
                if is_normalized:
                    if (a + c) <= 1.01 and (b + d) <= 1.01 and not (c > a and d > b):
                        return float(a), float(b), float(a + c), float(b + d)
                    if c > a and d > b:
                        return float(a), float(b), float(c), float(d)
                    return float(a), float(b), float(a + c), float(b + d)
                if c > a and d > b:
                    return float(a), float(b), float(c), float(d)
                return float(a), float(b), float(a + c), float(b + d)
            return None

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
                    x, y = v[0], v[1]
                    return float(x), float(y)
                except Exception:
                    return None
            return None

        bbox = _parse_bbox(bbox0)
        fp = _parse_xy(fp0)
        eye = _parse_xy(eye0)
        if bbox is None and fp is None and eye is None:
            return

        try:
            orig_w = float(self.image_info.get("width") or 0)
            orig_h = float(self.image_info.get("height") or 0)
        except Exception:
            orig_w = 0.0
            orig_h = 0.0
        if (orig_w <= 1 or orig_h <= 1) and (bbox is not None or fp is not None or eye is not None):
            fd = None
            try:
                fdj = self.image_info.get("focus_detect_json")
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
                    ow = float(fd.get("orig_w") or 0)
                    oh = float(fd.get("orig_h") or 0)
                except Exception:
                    ow = 0.0
                    oh = 0.0
                if ow > 1 and oh > 1:
                    orig_w = ow
                    orig_h = oh
        img = None
        try:
            img = getattr(self.parent_thumbnail, "_thumbnail_image", None)
            if img is None or (hasattr(img, "isNull") and img.isNull()):
                img = getattr(self.parent_thumbnail, "thumbnail_pixmap", None)
        except Exception:
            img = None
        if img is None:
            return
        try:
            img_w = float(img.width() or 0)
            img_h = float(img.height() or 0)
        except Exception:
            img_w = 0.0
            img_h = 0.0
        if img_w <= 1 or img_h <= 1 or img_rect.width() <= 1 or img_rect.height() <= 1:
            return

        if orig_w <= 1 or orig_h <= 1:
            try:
                if bbox is not None:
                    x1, y1, x2, y2 = bbox
                    if (
                        0.0 <= float(x1) <= 1.0
                        and 0.0 <= float(y1) <= 1.0
                        and 0.0 <= float(x2) <= 1.0
                        and 0.0 <= float(y2) <= 1.0
                        and float(x2) > float(x1)
                        and float(y2) > float(y1)
                    ):
                        orig_w = 1.0
                        orig_h = 1.0
            except Exception:
                pass
            try:
                if (orig_w <= 1 or orig_h <= 1) and fp is not None:
                    fx, fy = fp
                    if 0.0 <= float(fx) <= 1.0 and 0.0 <= float(fy) <= 1.0:
                        orig_w = 1.0
                        orig_h = 1.0
            except Exception:
                pass
            try:
                if (orig_w <= 1 or orig_h <= 1) and eye is not None:
                    ex, ey = eye
                    if 0.0 <= float(ex) <= 1.0 and 0.0 <= float(ey) <= 1.0:
                        orig_w = 1.0
                        orig_h = 1.0
            except Exception:
                pass
            if orig_w <= 1 or orig_h <= 1:
                orig_w = float(img_w)
                orig_h = float(img_h)
            if orig_w <= 1 or orig_h <= 1:
                return

        ratio = min(float(img_rect.width()) / img_w, float(img_rect.height()) / img_h)
        new_w = float(img_w * ratio)
        new_h = float(img_h * ratio)
        target_rect = QRectF(
            float(img_rect.x()) + (float(img_rect.width()) - new_w) / 2.0,
            float(img_rect.y()) + (float(img_rect.height()) - new_h) / 2.0,
            new_w,
            new_h,
        )

        cm = ColorManager.instance()
        rect_color = cm.qcolor("border.subject_rect", default="#f50f0f")
        fp_color = cm.qcolor("theme.primary", default="#2196F3")
        eye_color = QColor("#2196F3")
        try:
            pen_w = max(1, int(size_for_calcs // 90))
        except Exception:
            pen_w = 2

        if bbox is not None:
            try:
                x1, y1, x2, y2 = bbox
                x1 = max(0.0, min(orig_w, x1))
                x2 = max(0.0, min(orig_w, x2))
                y1 = max(0.0, min(orig_h, y1))
                y2 = max(0.0, min(orig_h, y2))
                if x2 > x1 and y2 > y1:
                    rx = target_rect.x() + (x1 / orig_w) * target_rect.width()
                    ry = target_rect.y() + (y1 / orig_h) * target_rect.height()
                    rw = ((x2 - x1) / orig_w) * target_rect.width()
                    rh = ((y2 - y1) / orig_h) * target_rect.height()
                    c = QColor(rect_color)
                    c.setAlpha(230)
                    painter.setPen(QPen(c, int(pen_w)))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(QRectF(rx, ry, rw, rh))
            except Exception:
                pass

        if fp is not None:
            try:
                fx, fy = fp
                try:
                    if 0.0 <= float(fx) <= 1.0 and 0.0 <= float(fy) <= 1.0:
                        fx = float(fx) * float(orig_w)
                        fy = float(fy) * float(orig_h)
                except Exception:
                    pass
                try:
                    if (float(fx) < 0.0 or float(fy) < 0.0) and orig_w > 1.0 and orig_h > 1.0:
                        fx2 = float(fx) + float(orig_w) / 2.0
                        fy2 = float(fy) + float(orig_h) / 2.0
                        if 0.0 <= fx2 <= float(orig_w) and 0.0 <= fy2 <= float(orig_h):
                            fx, fy = fx2, fy2
                except Exception:
                    pass
                fx = max(0.0, min(orig_w, fx))
                fy = max(0.0, min(orig_h, fy))
                cx = target_rect.x() + (fx / orig_w) * target_rect.width()
                cy = target_rect.y() + (fy / orig_h) * target_rect.height()
                try:
                    r = max(3, int(size_for_calcs // 26))
                except Exception:
                    r = 6
                c = QColor(fp_color)
                c.setAlpha(235)
                painter.setPen(QPen(c, int(pen_w)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
                painter.drawLine(int(cx - r * 2), int(cy), int(cx + r * 2), int(cy))
                painter.drawLine(int(cx), int(cy - r * 2), int(cx), int(cy + r * 2))
            except Exception:
                pass

        if eye is not None:
            try:
                ex, ey = eye
                try:
                    if 0.0 <= float(ex) <= 1.0 and 0.0 <= float(ey) <= 1.0:
                        ex = float(ex) * float(orig_w)
                        ey = float(ey) * float(orig_h)
                except Exception:
                    pass
                ex = max(0.0, min(orig_w, ex))
                ey = max(0.0, min(orig_h, ey))
                cx = target_rect.x() + (ex / orig_w) * target_rect.width()
                cy = target_rect.y() + (ey / orig_h) * target_rect.height()
                try:
                    r = max(4, int(round(pen_w * 2.8)))
                except Exception:
                    r = 6
                c = QColor(eye_color)
                c.setAlpha(240)
                painter.setPen(QPen(c, int(pen_w)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(cx - r, cy - r, 2 * r, 2 * r))
            except Exception:
                pass

class ImageThumbnail(QWidget):
    # 信号：点击时发送 (index, modifiers)
    clicked = pyqtSignal(int, object)
    # 信号：双击时发送 (index)
    doubleClicked = pyqtSignal(int)
    # 信号：右键菜单时发送 (index, position)
    contextMenuRequested = pyqtSignal(int, object)
    # 显示模式常量
    MODE_THUMBNAIL_ONLY = 0      # 只显示缩略图
    MODE_WITH_NAME = 1           # 缩略图+文件名
    MODE_WITH_DETAILS = 2        # 缩略图+详细信息

    _icons_loaded = False
    _shared_fav_pixmap = None
    _shared_fav_shadow_pixmap = None
    _shared_rating_icon_pixmap = None
    _shared_rating_shadow_pixmap = None
    _shared_placeholder_icon = None
    _shared_stash_icon = None
    _shared_stash_shadow_icon = None
    # 全局共享的色标缓存
    _shared_color_label_pixmaps = {}

    @classmethod
    def _ensure_icons_loaded(cls):
        if cls._icons_loaded:
            if getattr(cls, "_shared_stash_icon", None) is None:
                try:
                    cls._shared_stash_icon = qta.icon('mdi6.tag-check', color='#4CAF50', options=[{'scale_factor': 1.05}])
                    cls._shared_stash_shadow_icon = qta.icon('mdi6.tag-check', color='#00000055', options=[{'scale_factor': 1.05}])
                except Exception:
                    pass
            return
            
        # 恢复正常逻辑像素尺寸
        # 图标绘制将移至 OverlayWidget，这里只保留基础图标资源
        
        # 预加载收藏图标
        fav_icon = qta.icon('mdi6.heart', color='#FF3B30', options=[{'scale_factor': 1.08}])
        fav_shadow_icon = qta.icon('mdi6.heart', color='#00000055', options=[{'scale_factor': 1.08}])
        
        cls._shared_fav_icon = fav_icon
        cls._shared_fav_shadow_icon = fav_shadow_icon
        
        # 预加载评分星星图标
        cls._shared_rating_icon = qta.icon('fa5s.star', color='#FFCC00')
        cls._shared_rating_shadow_icon = qta.icon('fa5s.star', color='#00000040')
        
        cls._shared_stash_icon = qta.icon('mdi6.tag-check', color='#4CAF50', options=[{'scale_factor': 1.05}])
        cls._shared_stash_shadow_icon = qta.icon('mdi6.tag-check', color='#00000055', options=[{'scale_factor': 1.05}])

        cls._shared_placeholder_icon = qta.icon('fa6s.image', color='#999999')
        
        # 预加载色标颜色定义
        cls.LABEL_COLORS = {
            'Red': '#FF3B30',
            'Yellow': '#FFCC00',
            'Green': '#66BB6A',
            'Blue': '#007AFF',
            'Purple': '#AF52DE',
            'White': '#FFFFFF',
            'Orange': '#FF9500',
            'Pink': '#FF80AB',
            'Black': '#48484A',
            'Cyan': '#5AC8FA',
            'Gray': '#8E8E93'
        }
        
        cls._icons_loaded = True

    @classmethod
    def _preload_color_labels(cls):
        # 这里的预加载不再需要，OverlayWidget 会直接绘制
        pass

    def __init__(self, index, size=150, parent=None, cache_manager=None):
        t0 = time.perf_counter()
        super().__init__(parent)
        self._ensure_icons_loaded()
        self.index = index
        self.selected = False
        self.hovered = False
        self.base_bg_color = None
        self.thumb_size = size  # 使用传入的大小
        self.display_mode = self.MODE_WITH_NAME  # 默认显示文件名
        self.image_info = None  # 图片信息：{'path': '', 'name': '', 'create_time': ''}
        self.thumbnail_pixmap = None  # 显示用缩略图
        self._thumbnail_image = None  # 显示用缩略图 (QImage 格式，用于避免主线程转换)
        self._cached_pixmap = None  # 缓存的原始缩略图（较大尺寸，用于快速缩放）
        self._update_widget_size()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        if cache_manager:
            self.cache_manager = cache_manager
        else:
            self.cache_manager = ImageCacheManager()
        self._pressed = False
        self._press_pos = None
        self._press_modifiers = Qt.KeyboardModifier.NoModifier
        self._dragging = False
        
        self._has_error = False # 新增错误状态标记
        self._placeholder_pixmap = None
        self._placeholder_pixmap_size = None
        self._detail_cache = None
        self._detail_cache_path = None
        self.force_low_quality = False # 新增：强制低质量模式标志
        
        self._error_icon_pixmap = None # 错误图标缓存
        
        # 初始化图标蒙版
        self.icon_overlay = ThumbnailOverlay(self)
        
        # 记录初始化耗时
        t1 = time.perf_counter()
        if t1 - t0 > 0.001:
            try:
                LogManager.instance().debug(f"[Thumbnail] __init__ took: {t1-t0:.4f}s")
            except Exception:
                pass
        
        # 色标颜色映射 (优化为更有质感的配色)
        self.LABEL_COLORS = {
            'Red': '#FF3B30',      # Apple Red
            'Yellow': '#FFCC00',   # Apple Yellow
            'Green': '#66BB6A',    # Desaturated Green (User requested)
            'Blue': '#007AFF',     # Apple Blue
            'Purple': '#AF52DE',   # Apple Purple
            'White': '#FFFFFF',    # White
            'Orange': '#FF9500',   # Apple Orange
            'Pink': '#FF80AB',     # Desaturated Pink (User requested)
            'Black': '#48484A',    # Apple Gray (System Gray)
            'Cyan': '#5AC8FA',     # Apple Cyan (Added for completeness)
            'Gray': '#8E8E93'      # Apple Gray (Added for completeness)
        }
        
    def _get_color_label_pixmap(self, label, size=14):
        """获取缓存的色标 Pixmap"""
        key = (label, size)
        if key in self._shared_color_label_pixmaps:
            return self._shared_color_label_pixmaps[key]
            
        # 生成新的色标 Pixmap
        if label not in self.LABEL_COLORS:
            return None
            
        color_hex = self.LABEL_COLORS[label]
        color = QColor(color_hex)
        
        pixmap = QPixmap(size + 2, size + 2) # +2 for border/shadow space if needed
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 居中绘制
        rect = QRect(1, 1, size, size)
        
        # 渐变球体效果
        gradient = QRadialGradient(
            rect.x() + size * 0.3, 
            rect.y() + size * 0.3, 
            size * 0.8
        )
        gradient.setColorAt(0, color.lighter(130))
        gradient.setColorAt(0.5, color)
        gradient.setColorAt(1, color.darker(110))
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(rect)
        
        # 白色色标边框
        if label == 'White':
            painter.setPen(QPen(QColor("#d0d0d0"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)
            
        painter.end()
        
        self._shared_color_label_pixmaps[key] = pixmap
        return pixmap


    def _apply_gradient_to_pixmap(self, pixmap, color1, color2):
        """给 Pixmap 应用渐变色"""
        if pixmap.isNull():
            return pixmap
            
        # 创建一个新的 Pixmap
        result = QPixmap(pixmap.size())
        result.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(result)
        # 绘制原始图标作为遮罩
        painter.drawPixmap(0, 0, pixmap)
        
        # 设置合成模式：只在非透明区域绘制
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        
        # 创建线性渐变 (从左上到右下)
        gradient = QLinearGradient(0, 0, pixmap.width(), pixmap.height())
        gradient.setColorAt(0, color1)
        gradient.setColorAt(1, color2)
        
        painter.fillRect(result.rect(), QBrush(gradient))
        painter.end()
        
        return result

    def set_image_info(self, image_info, load_now=True):
        """设置图片信息
        Args:
            image_info: 图片信息字典
            load_now: 是否立即尝试加载图片 (默认 True)。
                      在批量创建缩略图时，应设为 False 以避免主线程阻塞。
        """
        self.image_info = image_info
        self._cached_pixmap = None  # 清除缓存
        self._detail_cache = None
        self._detail_cache_path = None
        
        # 更新蒙版信息
        if self.icon_overlay:
            self.icon_overlay.set_image_info(image_info)
        try:
            self._update_widget_size()
        except Exception:
            pass
            
        if load_now:
            self.load_thumbnail(force_reload=True)
        else:
            self.thumbnail_pixmap = None

    def _get_rating_string(self, rating):
        """获取评分星星字符串"""
        try:
            r = int(rating)
            if r <= 0:
                return ""
            r = min(5, r)
            return "★" * r + "☆" * (5 - r)
        except:
            return ""

    def _get_wh(self):
        """获取宽和高"""
        if isinstance(self.thumb_size, (tuple, list)):
            return int(self.thumb_size[0]), int(self.thumb_size[1])
        return int(self.thumb_size), int(self.thumb_size)

    def _get_info_text_font_pixel_size(self, size_for_calcs: int) -> int:
        """
        获取缩略图下方“文件名/详细信息”的字体像素大小。

        说明：
        - 字体大小由设置项控制，便于用户在不同屏幕/DPI 下自行调整可读性。
        - 如果读取设置失败，会回退到一个与缩略图尺寸相关的安全值，保证不至于过大或过小。

        参数：
        - size_for_calcs: 用于计算的缩略图基准尺寸（通常取宽高较小值）
        """
        v = None
        try:
            if hasattr(self.cache_manager, "settings_manager"):
                v = self.cache_manager.settings_manager.get("library/thumbnail_info_font_size", None)
        except Exception:
            v = None
        try:
            if v is not None:
                px = int(v)
            else:
                px = int(max(9, min(12, int(size_for_calcs) // 10)))
        except Exception:
            px = 11
        return int(max(8, min(20, px)))

    def _get_text_layout_metrics(self, size_for_calcs: int) -> tuple[int, int, int]:
        """
        获取文字区域的布局指标（间距/内边距）。

        说明：
        - 这里的“图片与文字间距”必须保持固定，避免缩略图放大后间距看起来忽大忽小。
        - 行间距尽量紧凑，只留很小的缝隙，提升信息密度与观感一致性。

        参数：
        - size_for_calcs: 用于计算的缩略图基准尺寸（当前主要用于兜底扩展）
        """
        _ = size_for_calcs
        text_gap = 2
        line_gap = 1
        bottom_padding = 2
        return int(text_gap), int(line_gap), int(bottom_padding)

    def clear_image_data(self):
        """清空图片数据以释放内存"""
        self.thumbnail_pixmap = None
        self._thumbnail_image = None
        self._cached_pixmap = None
        self.update()

    def set_error_state(self, has_error=True):
        """设置错误状态并显示错误提示"""
        self._has_error = has_error
        if has_error:
            # 清除图片数据以显示错误图标
            self.thumbnail_pixmap = None
            self._thumbnail_image = None
            self._cached_pixmap = None
        self.update()

    def set_thumbnail_image(self, image, immediate=False):
        """直接设置缩略图 (优化性能，避免内部重新缩放) - 优化版

        优化点：
        1. 如果图片尺寸合适，跳过缩放操作
        2. 优先使用快速缩放模式
        3. 延迟更新，避免频繁重绘（除非 immediate=True）
        4. 尽可能避免在主线程进行耗时操作

        参数:
            image: 要设置的缩略图图像
            immediate: 是否立即更新，不延迟。用于预加载的图片，避免闪烁。
        """
        self._has_error = False  # 成功设置图片时清除错误状态

        if image is None or (hasattr(image, "isNull") and image.isNull()):
            self.clear_image_data()
            return

        try:
            w, h = self._get_wh()
            border_width = 1
            margin = border_width + 2
            thumb_w = w - 2 * margin
            thumb_h = h - 2 * margin

            # 优化：如果图片尺寸已经合适，跳过缩放
            img_w = image.width()
            img_h = image.height()

            # 优化：如果图片尺寸接近目标尺寸（误差在20%以内），直接使用原图
            # 避免在主线程进行耗时的缩放操作
            # 放宽阈值从10%到20%，减少主线程缩放次数
            if thumb_w > 0 and thumb_h > 0:
                size_ratio = max(img_w / thumb_w, img_h / thumb_h)

                # 如果图片比目标大很多，才进行缩放
                if size_ratio > 1.2:  # 图片大于目标20%以上时进行缩放
                    target_w = thumb_w
                    target_h = thumb_h

                    # 使用Qt的快速缩放模式，避免SmoothTransformation的耗时
                    # FastTransformation使用最近邻插值，速度快很多
                    image = image.scaled(
                        target_w,
                        target_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation
                    )

            # 优化：延迟格式转换到真正显示时进行
            # 原代码：if image.format() != QImage.Format.Format_ARGB32_Premultiplied: ...
            # 现在：直接存储原始格式，在paintEvent中转换
            self._thumbnail_image = image
            self.thumbnail_pixmap = None
            self._cached_pixmap = None

            # 根据 immediate 参数决定是否立即更新
            self._schedule_update(immediate=immediate)

        except Exception as e:
            try:
                LogManager.instance().warning(f"设置缩略图图像失败: {e}")
            except Exception:
                pass
            self.clear_image_data()
    
    def _schedule_update(self, immediate=False):
        """延迟更新缩略图显示，避免频繁重绘
        
        参数:
            immediate: 是否立即更新，不延迟。用于预加载的图片，避免闪烁。
        """
        if not hasattr(self, '_update_pending'):
            self._update_pending = False
        
        if immediate:
            # 立即更新，不延迟
            self._update_pending = False
            self.update()
            return
            
        if not self._update_pending:
            self._update_pending = True
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(5, self._do_update)
    
    def _do_update(self):
        """执行实际的更新"""
        self._update_pending = False
        self.update()

    def load_thumbnail(self, force_reload=False):
        """加载缩略图
        Args:
            force_reload: 是否强制从磁盘重新加载
        """
        if not self.image_info or not os.path.exists(self.image_info['path']):
            self.thumbnail_pixmap = None
            self._cached_pixmap = None
            return
        path = self.image_info['path']
        try:
            disable_scaling = False
            try:
                if hasattr(self.cache_manager, "settings_manager"):
                    disable_scaling = bool(self.cache_manager.settings_manager.get("performance/thumbnail_disable_scaling", False))
            except Exception:
                disable_scaling = False
            scale_quality = "low"
            try:
                if hasattr(self.cache_manager, "get_scale_quality"):
                    scale_quality = str(self.cache_manager.get_scale_quality()).lower()
                elif hasattr(self.cache_manager, "settings_manager"):
                    scale_quality = str(self.cache_manager.settings_manager.get("performance/thumbnail_scale_quality", "low")).lower()
            except Exception:
                scale_quality = "low"
            transformation_mode = Qt.TransformationMode.SmoothTransformation if scale_quality == "high" else Qt.TransformationMode.FastTransformation
            
            # 如果强制使用低质量模式
            if getattr(self, "force_low_quality", False):
                transformation_mode = Qt.TransformationMode.FastTransformation
            
            if disable_scaling:
                transformation_mode = Qt.TransformationMode.FastTransformation
            cached_image = None
            if hasattr(self.cache_manager, "get_image"):
                cached_image = self.cache_manager.get_image(path)
            
            if cached_image is not None and not (hasattr(cached_image, "isNull") and cached_image.isNull()):
                w, h = self._get_wh()
                size_for_margin = min(w, h)
                border_width = 1
                margin = border_width + 2
                
                thumb_w = w - 2 * margin
                thumb_h = h - 2 * margin
                
                if thumb_w <= 0 or thumb_h <= 0:
                    return
                
                # 获取GPU缩放设置
                use_gpu_scaling = True
                try:
                    if hasattr(self.cache_manager, "settings_manager"):
                        use_gpu_scaling = bool(self.cache_manager.settings_manager.get("performance/use_gpu_scaling", True))
                except Exception:
                    use_gpu_scaling = True
                
                # 优化：使用简单的快速缩放，避免GPUScaler可能带来的UI阻塞
                if (cached_image.width() > thumb_w or cached_image.height() > thumb_h) and not disable_scaling:
                    cached_image = cached_image.scaled(
                        thumb_w,
                        thumb_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation
                    )
                self._thumbnail_image = cached_image
                self.thumbnail_pixmap = None
                self._cached_pixmap = None
                return
            
            # 1. 尝试从缓存获取
            cached = self.cache_manager.get(path)
            
            # 2. 如果缓存命中
            if cached is not None:
                self._cached_pixmap = cached
                self._thumbnail_image = None
            else:
                # 3. 如果缓存未命中，返回空，等待外部加载器加载
                self.thumbnail_pixmap = None
                self._cached_pixmap = None
                self._thumbnail_image = None
                return

            # 4. 从缓存缩放到目标大小
            w, h = self._get_wh()
            size_for_margin = min(w, h)
            border_width = 1
            # margin = max(2, size_for_margin // 40) + border_width
            # 紧贴图片，仅留出边框和微小内边距
            margin = border_width + 2
            
            thumb_w = w - 2 * margin
            thumb_h = h - 2 * margin
            
            if thumb_w <= 0 or thumb_h <= 0:
                 return

            self.thumbnail_pixmap = self._cached_pixmap.scaled(thumb_w, thumb_h,
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  transformation_mode)
        except Exception as e:
            try:
                LogManager.instance().warning(f"加载缩略图失败: {e}")
            except Exception:
                pass
            self.thumbnail_pixmap = None
            self._cached_pixmap = None
            self._thumbnail_image = None

    @staticmethod
    def calculate_size(thumb_size, display_mode):
        """静态方法：计算控件的总尺寸，避免实例化后重新布局"""
        # 兼容处理：thumb_size 可能是 int 或 (w, h) 元组
        if isinstance(thumb_size, (tuple, list)):
            w, h = int(thumb_size[0]), int(thumb_size[1])
        else:
            w, h = int(thumb_size), int(thumb_size)
            
        size_for_calcs = min(w, h)
        
        extra_height = 0
        if display_mode == ImageThumbnail.MODE_THUMBNAIL_ONLY:
            extra_height = 0
        elif display_mode == ImageThumbnail.MODE_WITH_NAME:
            if size_for_calcs >= 30:
                extra_height = max(18, min(28, size_for_calcs // 5))
        else:  # MODE_WITH_DETAILS
            if size_for_calcs >= 50:
                filename_line_height = max(16, min(22, size_for_calcs // 5))
                other_line_height = max(12, min(16, size_for_calcs // 8))
                extra_height = filename_line_height + 4 + (other_line_height * 4) + (2 * 3) + 2
            else:
                if size_for_calcs >= 30:
                    extra_height = min(18, max(12, size_for_calcs // 8))
                    
        return w, h + extra_height

    @staticmethod
    def calculate_size_with_text_font(
        thumb_size,
        display_mode,
        info_font_pixel_size: int = 11,
        details_max_lines: int = 5,
        text_gap: int = 2,
        line_gap: int = 1,
        bottom_padding: int = 2,
    ):
        """
        计算用于“虚拟化缩略图网格”的格子尺寸。

        说明：
        - 虚拟化网格（QListView IconMode）通常会用统一 gridSize，这里按“最大可能行数”预留空间，避免绘制被裁剪。
        - 行高使用 QFontMetrics 计算，确保“每行自适应行内文字高度”，并且在不同 DPI 下表现稳定。
        - 该函数只用于计算尺寸；具体显示内容仍在 paint 阶段进行省略/裁剪控制。

        参数：
        - thumb_size: 缩略图本体尺寸（不含文字区域）
        - display_mode: 显示模式（仅缩略图/带文件名/带详情）
        - info_font_pixel_size: 信息文字字体像素大小
        - details_max_lines: 详情模式最大行数（默认 5：文件名+4行信息）
        - text_gap: 图片与文字之间的间距
        - line_gap: 行间距
        - bottom_padding: 文字区域底部留白
        """
        if isinstance(thumb_size, (tuple, list)):
            w, h = int(thumb_size[0]), int(thumb_size[1])
        else:
            w, h = int(thumb_size), int(thumb_size)
        size_for_calcs = max(1, min(w, h))

        try:
            from PyQt6.QtGui import QFont, QFontMetrics
            f = QFont()
            f.setPixelSize(int(max(8, min(20, int(info_font_pixel_size)))))
            fm = QFontMetrics(f)
            line_h = int(fm.height())
        except Exception:
            line_h = 14

        extra = 0
        if display_mode == ImageThumbnail.MODE_THUMBNAIL_ONLY:
            extra = 0
        elif display_mode == ImageThumbnail.MODE_WITH_NAME:
            if size_for_calcs >= 30:
                extra = int(text_gap + line_h + bottom_padding)
        else:
            if size_for_calcs >= 50:
                lines_count = int(max(1, details_max_lines))
                extra = int(text_gap + line_h * lines_count + line_gap * max(0, lines_count - 1) + bottom_padding)
            else:
                if size_for_calcs >= 30:
                    extra = int(text_gap + line_h + bottom_padding)
        return int(w), int(h + extra)

    def _has_exif_info(self):
        info = getattr(self, "image_info", None) or {}
        try:
            if bool(info.get("has_exif")):
                return True
        except Exception:
            pass
        try:
            return any(bool(info.get(k)) for k in ("focal_length", "iso", "shutter", "fnumber"))
        except Exception:
            return False

    def _update_widget_size(self):
        """根据缩略图尺寸和显示模式计算整体控件尺寸"""
        if isinstance(self.thumb_size, (tuple, list)):
            w = int(self.thumb_size[0])
            h = int(self.thumb_size[1])
        else:
            w = int(self.thumb_size)
            h = int(self.thumb_size)
        size_for_calcs = max(1, min(w, h))

        extra_height = 0
        if self.display_mode == ImageThumbnail.MODE_THUMBNAIL_ONLY:
            extra_height = 0
        elif self.display_mode == ImageThumbnail.MODE_WITH_NAME:
            if size_for_calcs >= 30:
                text_gap, _line_gap, bottom_padding = self._get_text_layout_metrics(size_for_calcs)
                from PyQt6.QtGui import QFont, QFontMetrics
                f = QFont()
                f.setPixelSize(self._get_info_text_font_pixel_size(size_for_calcs))
                fm = QFontMetrics(f)
                extra_height = int(text_gap + fm.height() + bottom_padding)
        else:
            if size_for_calcs >= 50:
                text_gap, line_gap, bottom_padding = self._get_text_layout_metrics(size_for_calcs)
                from PyQt6.QtGui import QFont, QFontMetrics
                f = QFont()
                f.setPixelSize(self._get_info_text_font_pixel_size(size_for_calcs))
                fm = QFontMetrics(f)
                line_h = int(fm.height())
                other_count = 4 if self._has_exif_info() else 2
                lines_count = 1 + int(other_count)
                extra_height = int(text_gap + line_h * lines_count + line_gap * max(0, lines_count - 1) + bottom_padding)
            else:
                if size_for_calcs >= 30:
                    text_gap, _line_gap, bottom_padding = self._get_text_layout_metrics(size_for_calcs)
                    from PyQt6.QtGui import QFont, QFontMetrics
                    f = QFont()
                    f.setPixelSize(self._get_info_text_font_pixel_size(size_for_calcs))
                    fm = QFontMetrics(f)
                    extra_height = int(text_gap + fm.height() + bottom_padding)

        self.setFixedSize(w, h + extra_height)

    def set_size(self, size, reload_thumbnail=True):
        """设置缩略图大小"""
        self.thumb_size = size
        self._update_widget_size()
        if reload_thumbnail and self.image_info:
            self.load_thumbnail()
        self.update()

    def set_display_mode(self, mode):
        """设置显示模式"""
        self.display_mode = mode
        self._update_widget_size()
        self.update()

    def set_selected(self, selected):
        # P1 优化：避免重复更新和减少重绘
        if getattr(self, 'selected', None) == selected:
            return
        self.selected = selected
        # 如果父容器正在批量更新，跳过单独 update，由父容器统一刷新
        parent = getattr(self, 'parent', lambda: None)()
        if parent is not None and getattr(parent, '_batch_selecting', False):
            return
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.icon_overlay:
            self.icon_overlay.resize(self.size())
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._press_pos = event.position().toPoint()
            self._press_modifiers = event.modifiers()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressed and not self._dragging:
            from PyQt6.QtWidgets import QApplication
            current_pos = event.position().toPoint()
            if self._press_pos is not None and (current_pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            if not self._dragging:
                self.clicked.emit(self.index, self._press_modifiers)
            self._pressed = False
            self._press_pos = None
            self._press_modifiers = Qt.KeyboardModifier.NoModifier
            self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit(self.index)
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        """右键菜单事件"""
        try:
            if self.image_info:
                # 发送右键菜单信号，传递索引和位置
                self.contextMenuRequested.emit(self.index, event.globalPos())
        except Exception as e:
            try:
                LogManager.instance().error(f"缩略图右键菜单事件失败: {e}")
                import traceback
                LogManager.instance().error(traceback.format_exc())
            except Exception:
                pass

    def paintEvent(self, event):
        t0 = time.perf_counter()
        from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics
        
        # 调试：检查特定图片
        img_name = self.image_info.get('name', 'unknown') if self.image_info else 'unknown'
        if '白鹭_027' in img_name or '白鹭_026' in img_name:
            print(f"[DEBUG] paintEvent called: {img_name}")
            print(f"[DEBUG]   isVisible={self.isVisible()}")
            print(f"[DEBUG]   size={self.size()}")
            print(f"[DEBUG]   rect={self.rect()}")
            print(f"[DEBUG]   parent={self.parent()}")
            print(f"[DEBUG]   has image_info={self.image_info is not None}")
        
        painter = QPainter(self)
        
        # 首先绘制边框（确保即使后续出错，边框也能显示）
        try:
            base_color = QColor(self.base_bg_color) if self.base_bg_color else None
            if self.selected:
                painter.fillRect(self.rect(), QColor("#e3f2fd"))
                painter.setPen(QPen(QColor("#2196F3"), 2))
                painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            elif self.hovered:
                if base_color is not None:
                    painter.fillRect(self.rect(), base_color.lighter(110))
                    painter.setPen(QPen(base_color.darker(130), 1))
                    painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
                else:
                    painter.fillRect(self.rect(), QColor("#e8e8e8"))
                    painter.setPen(QPen(QColor("#c0c0c0"), 1))
                    painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            else:
                if base_color is not None:
                    painter.fillRect(self.rect(), base_color)
                    painter.setPen(QPen(base_color.darker(200), 1))
                    painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
                else:
                    painter.fillRect(self.rect(), QColor("#f0f0f0"))
                    painter.setPen(QPen(QColor("#a0a0a0"), 1))
                    painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            if '白鹭_027' in img_name or '白鹭_026' in img_name:
                print(f"[DEBUG] border drawn for {img_name}")
        except Exception as e:
            # 如果绘制边框失败，至少绘制一个默认边框
            if '白鹭_027' in img_name or '白鹭_026' in img_name:
                print(f"[DEBUG] border exception for {img_name}: {e}")
            painter.fillRect(self.rect(), QColor("#f0f0f0"))
            painter.setPen(QPen(QColor("#808080"), 1))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        
        # 开启抗锯齿和平滑变换，解决缩略图锯齿感问题
        # 优化：默认关闭全局抗锯齿和平滑变换，仅在需要时开启，提升性能
        # painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        thumb_w, thumb_h = self._get_wh()
        size_for_calcs = min(thumb_w, thumb_h)
        
        # 根据显示模式计算额外高度（用于文字显示区域）
        if self.display_mode == self.MODE_THUMBNAIL_ONLY:
            show_name = False
            show_details = False
        elif self.display_mode == self.MODE_WITH_NAME:
            show_name = size_for_calcs >= 30
            show_details = False
        else:  # MODE_WITH_DETAILS
            if size_for_calcs >= 50:
                filename_line_height = max(16, min(22, size_for_calcs // 5))  # 文件名行高
                other_line_height = max(12, min(16, size_for_calcs // 8))  # 其他行高
                # 5行文字：文件名 + 4行信息
                # 间距：文件名后4px，其他行间2px，底部6px
                show_name = False
                show_details = True
            else:
                # 最小格式下也显示文件名
                show_name = size_for_calcs >= 30
                show_details = False
        # 计算边距
        border_width = 1
        # 紧贴图片
        margin = border_width + 2
        
        bottom_space = 0
        if show_name:
            bottom_space = max(18, min(28, size_for_calcs // 5))
        elif show_details:
            filename_line_height = max(16, min(22, size_for_calcs // 5))
            other_line_height = max(12, min(16, size_for_calcs // 8))
            other_count = 4 if self._has_exif_info() else 2
            bottom_space = filename_line_height + 4 + (other_line_height * other_count) + (2 * max(0, other_count - 1)) + 2
            
        img_w = thumb_w - 2 * margin
        img_h = thumb_h - 2 * margin
        img_x = margin
        img_y = margin
        img_rect = QRect(img_x, img_y, img_w, img_h)
        # 初始化字体（后续绘制文字时需要）
        font = painter.font()
        # 绘制缩略图
        if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
            pix_w = self.thumbnail_pixmap.width()
            pix_h = self.thumbnail_pixmap.height()
            
            # 始终按比例缩放以填满显示区域（保持纵横比）
            # 解决放大缩略图控件时，图片仍然保持原尺寸（居中显示）的问题
            if pix_w > 0 and pix_h > 0:
                ratio = min(img_rect.width() / pix_w, img_rect.height() / pix_h)
                new_w = int(pix_w * ratio)
                new_h = int(pix_h * ratio)
                target_rect = QRect(
                    img_rect.x() + (img_rect.width() - new_w) // 2,
                    img_rect.y() + (img_rect.height() - new_h) // 2,
                    new_w,
                    new_h
                )
                painter.drawPixmap(target_rect, self.thumbnail_pixmap)

        elif self._thumbnail_image and not self._thumbnail_image.isNull():
            img_w_src = self._thumbnail_image.width()
            img_h_src = self._thumbnail_image.height()
            
            # 始终按比例缩放以填满显示区域（保持纵横比）
            if img_w_src > 0 and img_h_src > 0:
                ratio = min(img_rect.width() / img_w_src, img_rect.height() / img_h_src)
                new_w = int(img_w_src * ratio)
                new_h = int(img_h_src * ratio)
                target_rect = QRect(
                    img_rect.x() + (img_rect.width() - new_w) // 2,
                    img_rect.y() + (img_rect.height() - new_h) // 2,
                    new_w,
                    new_h
                )
                # 优化：延迟格式转换到显示时进行
                # 如果格式不是 ARGB32_Premultiplied，转换为该格式（QPixmap.fromImage 最快）
                img_to_draw = self._thumbnail_image
                if img_to_draw.format() != QImage.Format.Format_ARGB32_Premultiplied:
                    img_to_draw = img_to_draw.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                painter.drawImage(target_rect, img_to_draw)

        elif getattr(self, "_has_error", False):
            # 绘制错误提示图标
            if not self._error_icon_pixmap:
                # 延迟加载错误图标
                self._error_icon_pixmap = qta.icon('mdi6.alert-circle-outline', color='#FF3B30').pixmap(48, 48)
            
            if self._error_icon_pixmap:
                px_w = self._error_icon_pixmap.width()
                px_h = self._error_icon_pixmap.height()
                x = img_rect.x() + (img_rect.width() - px_w) // 2
                y = img_rect.y() + (img_rect.height() - px_h) // 2
                painter.drawPixmap(x, y, self._error_icon_pixmap)
                
            # 绘制"加载失败"文字
            painter.setPen(QColor("#FF3B30"))
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            text_rect = QRect(img_rect.left(), img_rect.bottom() - 20, img_rect.width(), 20)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "加载失败")
            
        else:
            # 绘制占位符
            # 使用缓存的占位符 pixmap，避免重复生成
            current_size = max(1, min(img_rect.width(), img_rect.height()) // 3)
            if (self._placeholder_pixmap is None or 
                self._placeholder_pixmap_size != current_size):
                if self._shared_placeholder_icon:
                    self._placeholder_pixmap = self._shared_placeholder_icon.pixmap(current_size, current_size)
                    self._placeholder_pixmap_size = current_size
            
            if self._shared_placeholder_icon:
                x = img_rect.center().x() - current_size // 2
                y = img_rect.center().y() - current_size // 2
                painter.setOpacity(0.5)
                self._shared_placeholder_icon.paint(
                    painter,
                    QRect(x, y, current_size, current_size),
                    Qt.AlignmentFlag.AlignCenter,
                )
                painter.setOpacity(1.0)
            elif self._placeholder_pixmap:
                px_w = self._placeholder_pixmap.width()
                px_h = self._placeholder_pixmap.height()
                x = img_rect.x() + (img_rect.width() - px_w) // 2
                y = img_rect.y() + (img_rect.height() - px_h) // 2
                painter.setOpacity(0.5)
                painter.drawPixmap(x, y, self._placeholder_pixmap)
                painter.setOpacity(1.0)
        # 绘制文件名（单行）
        if show_name:
            text_gap, _line_gap, _bottom_padding = self._get_text_layout_metrics(size_for_calcs)
            text_px = self._get_info_text_font_pixel_size(size_for_calcs)
            font.setBold(False)
            font.setPixelSize(int(text_px))
            painter.setFont(font)
            fm = QFontMetrics(font)
            name = self.image_info['name'] if self.image_info else f"IMG_{self.index + 1:04d}.jpg"
            name_rect = QRect(margin, int(thumb_h + text_gap), int(thumb_w - 2 * margin), int(fm.height()))
            painter.setPen(QColor("#333333"))
            try:
                name_draw = fm.elidedText(str(name), Qt.TextElideMode.ElideRight, name_rect.width())
            except Exception:
                name_draw = str(name)
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, name_draw)
        
        # 右上角图标已移至 ThumbnailOverlay 绘制，此处不再绘制
            

        # 绘制详细信息（5行）
        if show_details:
            text_gap, line_gap, _bottom_padding = self._get_text_layout_metrics(size_for_calcs)
            text_px = self._get_info_text_font_pixel_size(size_for_calcs)
            font.setBold(False)
            font.setPixelSize(int(text_px))
            painter.setFont(font)
            fm = QFontMetrics(font)
            line_h = int(fm.height())
            
            # 使用实际的图片信息
            if self.image_info:
                current_path = self.image_info.get('path')
                if self._detail_cache is None or self._detail_cache_path != current_path:
                    try:
                        # 仅使用已有的信息，避免同步 IO 阻塞主线程
                        # from PyQt6.QtGui import QImageReader
                        # reader = QImageReader(current_path)
                        # img_size = reader.size()
                        # file_size = os.path.getsize(current_path)
                        
                        file_size = self.image_info.get('size', 0)
                        size_in_kb = file_size / 1024
                        
                        # 如果没有宽度信息，暂时不显示分辨率，避免 IO
                        width = self.image_info.get('width', 0)
                        height = self.image_info.get('height', 0)
                        
                        if size_in_kb > 0:
                            if size_in_kb > 1024:
                                size_str = f"{size_in_kb/1024:.1f}MB"
                            else:
                                size_str = f"{int(size_in_kb)}KB"
                        else:
                            size_str = "未知大小"

                        if width > 0 and height > 0:
                            size_info = f"尺寸 {width}x{height} | 大小 {size_str}"
                        else:
                            size_info = f"大小 {size_str}"
                    except Exception:
                        size_info = "未知大小"
                    shot_time = self.image_info.get('shot_time', '')
                    if not shot_time:
                        shot_time = self.image_info.get('create_time', '')
                    has_exif = bool(self.image_info.get('has_exif'))
                    if not has_exif:
                        try:
                            has_exif = any(
                                bool(self.image_info.get(k))
                                for k in ("focal_length", "iso", "shutter", "fnumber")
                            )
                        except Exception:
                            has_exif = False

                    if not has_exif:
                        self._detail_cache = [self.image_info['name'], size_info, shot_time]
                    else:
                        focal_length = self.image_info.get('focal_length', '')
                        if not focal_length:
                            focal_length = "unknow"
                        iso = self.image_info.get('iso', '')
                        if not iso:
                            iso = "ISO unknown"
                        shutter = self.image_info.get('shutter', '')
                        if not shutter:
                            shutter = "unknown s"
                        fnumber = self.image_info.get('fnumber', '')
                        if not fnumber:
                            fnumber = 0.0
                        self._detail_cache = [self.image_info['name'], size_info, shot_time, focal_length + " , F " + str(fnumber), shutter + " , ISO " + str(iso)]
                    self._detail_cache_path = current_path
                details = self._detail_cache
            else:
                # 模拟的详细信息
                details = [
                    f"IMG_{self.index + 1:04d}.jpg",
                    f"6000x4000 - 12MB",
                    f"2024-01-{(self.index % 28) + 1:02d} 10:00:00",
                    "600mm f/6.3", 
                    "1/5000s ISO 3200" # Exif 占位符
                ]
            
            try:
                details = [x for x in details if str(x).strip()]
            except Exception:
                pass

            # 从图片底部开始，加上固定间距，保证缩放后一致
            y_pos = int(thumb_h + text_gap)
            
            for i, text in enumerate(details):
                painter.setPen(QColor("#333333"))
                text_rect = QRect(int(margin), int(y_pos), int(thumb_w - 2 * margin), int(line_h))
                try:
                    draw_text = fm.elidedText(str(text), Qt.TextElideMode.ElideRight, text_rect.width())
                except Exception:
                    draw_text = str(text)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, draw_text)
                y_pos += int(line_h + line_gap)
        
        t1 = time.perf_counter()
        if t1 - t0 > 0.01:  # 仅记录超过 10ms 的绘制
            try:
                LogManager.instance().debug(f"[Widget] paint took: {t1-t0:.4f}s (mode={self.display_mode})")
            except Exception:
                pass
