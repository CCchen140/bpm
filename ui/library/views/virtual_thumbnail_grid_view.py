from PyQt6.QtWidgets import QWidget, QListView, QVBoxLayout, QFrame, QApplication, QStyle
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QPointF, QRect, QAbstractListModel, QModelIndex, QEvent
from PyQt6.QtGui import QPainter, QColor, QFont, QCursor, QFontMetrics, QPen, QMouseEvent
from PyQt6.QtWidgets import QStyledItemDelegate
from PyQt6.QtCore import QItemSelectionModel
from ui.utils.icon_loader import qta
import json

from ui.utils.shortcut_manager import ShortcutManager
from ui.utils.color_manager import ColorManager
from ui.widgets.image_thumbnail import ImageThumbnail

_RAW_EXTS = {".NEF", ".RAW", ".CR2", ".CR3", ".RAF", ".ORF", ".DNG", ".ARW"}


class _VirtualThumbnailItem:
    def __init__(self, index: int, image_info: dict, notify_changed, request_repaint):
        self.index = int(index)
        self.image_info = image_info
        self.selected = False
        self.hovered = False
        self.thumb_size = 120
        self.display_mode = ImageThumbnail.MODE_WITH_NAME
        self.thumbnail_pixmap = None
        self._thumbnail_image = None
        self._has_error = False
        self.force_low_quality = False
        self._notify_changed = notify_changed
        self._request_repaint = request_repaint

    def set_selected(self, selected: bool):
        self.selected = bool(selected)
        self._notify_changed(self.index)

    def set_thumbnail_image(self, image):
        self._thumbnail_image = image
        self._has_error = image is None
        self._notify_changed(self.index)

    def clear_image_data(self):
        self.thumbnail_pixmap = None
        self._thumbnail_image = None
        self._has_error = False
        try:
            self._stale_thumbnail = False
        except Exception:
            pass
        self._notify_changed(self.index)

    def set_image_info(self, info, load_now=False):
        self.image_info = info
        self._notify_changed(self.index)

    def set_size(self, size, reload_thumbnail=False):
        self.thumb_size = size
        self._notify_changed(self.index)

    def set_display_mode(self, mode):
        self.display_mode = int(mode)
        self._notify_changed(self.index)

    def load_thumbnail(self):
        self._has_error = True
        self._notify_changed(self.index)

    def update(self):
        self._request_repaint(self.index)


class _VirtualThumbnailModel(QAbstractListModel):
    INFO_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    IMAGE_ROLE = int(Qt.ItemDataRole.UserRole) + 2
    INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 3
    SELECTED_ROLE = int(Qt.ItemDataRole.UserRole) + 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._items):
            return None
        item = self._items[row]
        if role == int(Qt.ItemDataRole.DisplayRole):
            try:
                info = item.image_info or {}
                return info.get("name") or info.get("path") or ""
            except Exception:
                return ""
        if role == self.INFO_ROLE:
            return item.image_info
        if role == self.IMAGE_ROLE:
            return item._thumbnail_image
        if role == self.INDEX_ROLE:
            return item.index
        if role == self.SELECTED_ROLE:
            return item.selected
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def clear(self):
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def append_items(self, items):
        if not items:
            return
        start = len(self._items)
        end = start + len(items) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._items.extend(items)
        self.endInsertRows()

    def notify_row_changed(self, row: int):
        if row < 0 or row >= len(self._items):
            return
        mi = self.index(row, 0)
        self.dataChanged.emit(mi, mi, [])

    def get_item(self, row: int):
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def items(self):
        return self._items


class _VirtualThumbnailDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        ImageThumbnail._ensure_icons_loaded()

    def paint(self, painter: QPainter, option, index: QModelIndex):
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.primary")
        text_color = cm.get("theme.text.dark")
        primary = cm.get("theme.primary")
        border = cm.get("popup.border.primary")

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = option.rect
        painter.fillRect(rect, QColor(panel_bg))

        info = index.data(_VirtualThumbnailModel.INFO_ROLE) or {}
        image = index.data(_VirtualThumbnailModel.IMAGE_ROLE)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        view = self.parent()
        try:
            margin = int(getattr(view, "_item_margin", 3))
        except Exception:
            margin = 3
        if margin < 0:
            margin = 0
        display_mode = getattr(view, "_display_mode", ImageThumbnail.MODE_WITH_NAME)
        thumb_size = getattr(view, "_thumb_size", 120)
        if isinstance(thumb_size, (tuple, list)):
            try:
                thumb_w = int(thumb_size[0])
                thumb_h = int(thumb_size[1])
            except Exception:
                thumb_w = 120
                thumb_h = 120
        else:
            try:
                thumb_w = int(thumb_size)
                thumb_h = int(thumb_size)
            except Exception:
                thumb_w = 120
                thumb_h = 120
        bottom_space = max(0, rect.height() - thumb_h)
        img_rect = rect.adjusted(margin, margin, -margin, -margin - bottom_space)

        try:
            is_stashed = bool(info.get("is_stashed", False))
        except Exception:
            is_stashed = False

        target_rect = QRect(img_rect)
        if image is not None and not (hasattr(image, "isNull") and image.isNull()):
            img_w = image.width()
            img_h = image.height()
            painter.setClipRect(img_rect)
            if img_w > 0 and img_h > 0 and img_rect.width() > 0 and img_rect.height() > 0:
                ratio = min(img_rect.width() / img_w, img_rect.height() / img_h)
                new_w = int(img_w * ratio)
                new_h = int(img_h * ratio)
                target_rect = QRect(
                    img_rect.x() + (img_rect.width() - new_w) // 2,
                    img_rect.y() + (img_rect.height() - new_h) // 2,
                    new_w,
                    new_h,
                )
                painter.drawImage(target_rect, image)
            else:
                painter.drawImage(img_rect, image)
        else:
            try:
                icon = getattr(ImageThumbnail, "_shared_placeholder_icon", None)
                if icon is not None:
                    size = max(1, min(img_rect.width(), img_rect.height()) // 3)
                    x = img_rect.center().x() - size // 2
                    y = img_rect.center().y() - size // 2
                    painter.setOpacity(0.5)
                    icon.paint(painter, QRect(x, y, size, size), Qt.AlignmentFlag.AlignCenter)
                    painter.setOpacity(1.0)
                else:
                    placeholder = ImageThumbnail._shared_placeholder_icon.pixmap(32, 32)
                    ph_x = img_rect.center().x() - placeholder.width() // 2
                    ph_y = img_rect.center().y() - placeholder.height() // 2
                    painter.drawPixmap(ph_x, ph_y, placeholder)
            except Exception:
                pass
        try:
            painter.setClipping(False)
        except Exception:
            pass

        view = self.parent()
        simplified = bool(getattr(view, "_fast_scroll_simplified", False))
        if simplified and selected:
            try:
                sel_bg = QColor(primary)
                sel_bg.setAlphaF(0.16)
                painter.fillRect(rect.adjusted(1, 1, -1, -1), sel_bg)
            except Exception:
                pass

        try:
            bbox0 = info.get("bbox")
            fp0 = info.get("focus_point")
        except Exception:
            bbox0 = None
            fp0 = None
        try:
            if not bool(getattr(view, "show_focus_overlays", True)):
                bbox0 = None
                fp0 = None
        except Exception:
            pass

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
            if isinstance(v, (list, tuple)) and len(v) == 4:
                try:
                    x1, y1, x2, y2 = v
                    return float(x1), float(y1), float(x2), float(y2)
                except Exception:
                    return None
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
                    return float(v[0]), float(v[1])
                except Exception:
                    return None
            return None

        bbox = _parse_bbox(bbox0)
        fp = _parse_xy(fp0)
        show_bbox = True
        show_fp = True
        try:
            sm = getattr(view, "settings_manager", None)
            if sm is not None:
                show_bbox = bool(sm.get("focus_detect_ui/show_subject_rect", True))
                show_fp = bool(sm.get("focus_detect_ui/show_focus_point", True))
        except Exception:
            show_bbox = True
            show_fp = True
        if not show_bbox:
            bbox = None
        if not show_fp:
            fp = None
        try:
            orig_w = float(info.get("width") or 0)
            orig_h = float(info.get("height") or 0)
        except Exception:
            orig_w = 0.0
            orig_h = 0.0
        if (orig_w <= 1 or orig_h <= 1) and (bbox is not None or fp is not None):
            try:
                fdj = info.get("focus_detect_json")
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
                    ow = float(fd.get("orig_w") or 0)
                    oh = float(fd.get("orig_h") or 0)
                except Exception:
                    ow = 0.0
                    oh = 0.0
                if ow > 1 and oh > 1:
                    orig_w = ow
                    orig_h = oh
        norm_coords = False
        if (bbox is not None or fp is not None) and target_rect.width() > 1 and target_rect.height() > 1:
            if orig_w <= 1 or orig_h <= 1:
                try:
                    if bbox is not None:
                        x1, y1, x2, y2 = bbox
                        norm_coords = bool(
                            0.0 <= float(x1) <= 1.0
                            and 0.0 <= float(y1) <= 1.0
                            and 0.0 <= float(x2) <= 1.0
                            and 0.0 <= float(y2) <= 1.0
                        )
                except Exception:
                    norm_coords = False
                if not norm_coords and fp is not None:
                    try:
                        fx, fy = fp
                        norm_coords = bool(0.0 <= float(fx) <= 1.0 and 0.0 <= float(fy) <= 1.0)
                    except Exception:
                        norm_coords = False
            if norm_coords:
                orig_w = 1.0
                orig_h = 1.0

        if (bbox is not None or fp is not None) and (norm_coords or (orig_w > 1 and orig_h > 1)) and target_rect.width() > 1 and target_rect.height() > 1:
            try:
                pen_w = max(1, int(max(thumb_w, thumb_h) // 90))
            except Exception:
                pen_w = 2
            rect_color = cm.qcolor("border.subject_rect", default="#f50f0f")
            if bbox is not None:
                try:
                    x1, y1, x2, y2 = bbox
                    x1 = max(0.0, min(orig_w, x1))
                    x2 = max(0.0, min(orig_w, x2))
                    y1 = max(0.0, min(orig_h, y1))
                    y2 = max(0.0, min(orig_h, y2))
                    if x2 > x1 and y2 > y1:
                        rx = float(target_rect.x()) + (x1 / orig_w) * float(target_rect.width())
                        ry = float(target_rect.y()) + (y1 / orig_h) * float(target_rect.height())
                        rw = ((x2 - x1) / orig_w) * float(target_rect.width())
                        rh = ((y2 - y1) / orig_h) * float(target_rect.height())
                        c = QColor(rect_color)
                        c.setAlpha(230)
                        painter.setPen(QPen(c, int(pen_w)))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(QRect(int(rx), int(ry), int(rw), int(rh)))
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
                    fx = max(0.0, min(orig_w, fx))
                    fy = max(0.0, min(orig_h, fy))
                    cx = float(target_rect.x()) + (fx / orig_w) * float(target_rect.width())
                    cy = float(target_rect.y()) + (fy / orig_h) * float(target_rect.height())
                    try:
                        r = max(10, int(max(thumb_w, thumb_h) // 12))
                    except Exception:
                        r = 14
                    try:
                        if getattr(ImageThumbnail, "_shared_focus_point_thumb_icon", None) is None:
                            ImageThumbnail._shared_focus_point_thumb_icon = qta.icon("fa5s.crosshairs", color="#4CAF50", options=[{"scale_factor": 1.05}])
                            ImageThumbnail._shared_focus_point_thumb_shadow_icon = qta.icon("fa5s.crosshairs", color="#00000066", options=[{"scale_factor": 1.05}])
                    except Exception:
                        pass
                    try:
                        icon_rect = QRect(int(cx - r // 2), int(cy - r // 2), int(r), int(r))
                        if getattr(ImageThumbnail, "_shared_focus_point_thumb_shadow_icon", None) is not None:
                            shadow_rect = QRect(icon_rect.x() + 1, icon_rect.y() + 1, icon_rect.width(), icon_rect.height())
                            ImageThumbnail._shared_focus_point_thumb_shadow_icon.paint(painter, shadow_rect)
                        if getattr(ImageThumbnail, "_shared_focus_point_thumb_icon", None) is not None:
                            ImageThumbnail._shared_focus_point_thumb_icon.paint(painter, icon_rect)
                    except Exception:
                        pass
                except Exception:
                    pass

        if simplified:
            painter.restore()
            return

        try:
            is_fav = bool(info.get("is_favorite"))
            raw_label = info.get("label")
            manual_label = raw_label.title() if raw_label else None
            raw_auto = info.get("auto_label")
            auto_label = raw_auto.title() if raw_auto else None
            label = manual_label or auto_label
            rating = int(info.get("rating", 0) or 0)
        except Exception:
            is_fav = False
            manual_label = None
            auto_label = None
            label = None
            rating = 0

        if is_stashed and getattr(ImageThumbnail, "_shared_stash_icon", None) is not None:
            try:
                stash_size = 16
                margin_left = 4
                margin_top = 4
                x = img_rect.left() + margin_left
                y = img_rect.top() + margin_top
                shadow_rect = QRect(x + 1, y + 1, stash_size, stash_size)
                ImageThumbnail._shared_stash_shadow_icon.paint(painter, shadow_rect)
                icon_rect = QRect(x, y, stash_size, stash_size)
                ImageThumbnail._shared_stash_icon.paint(painter, icon_rect)
            except Exception:
                pass

        icon_size = 20
        spacing = 2
        margin_right = 4
        margin_top = 4
        current_y = img_rect.top() + margin_top
        icon_x = img_rect.right() - icon_size - margin_right

        if is_fav:
            shadow_rect = QRect(icon_x + 1, current_y + 1, icon_size, icon_size)
            ImageThumbnail._shared_fav_shadow_icon.paint(painter, shadow_rect)
            icon_rect = QRect(icon_x, current_y, icon_size, icon_size)
            ImageThumbnail._shared_fav_icon.paint(painter, icon_rect)
            current_y += icon_size + spacing

        if label and hasattr(ImageThumbnail, "LABEL_COLORS") and label in ImageThumbnail.LABEL_COLORS:
            color = QColor(ImageThumbnail.LABEL_COLORS[label])
            dot_size = 14
            offset = int((icon_size - dot_size) / 2)
            dot_rect = QRect(icon_x + offset, current_y + offset, dot_size, dot_size)
            if manual_label:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(dot_rect)
                if label == "White":
                    painter.setPen(QColor("#d0d0d0"))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(dot_rect)
            else:
                pen = QPen(color, 2)
                if label == "White":
                    pen = QPen(QColor("#d0d0d0"), 2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(dot_rect)
            current_y += icon_size + spacing

        if rating > 0:
            shadow_rect = QRect(icon_x + 1, current_y + 1, icon_size, icon_size)
            ImageThumbnail._shared_rating_shadow_icon.paint(painter, shadow_rect)
            icon_rect = QRect(icon_x, current_y, icon_size, icon_size)
            ImageThumbnail._shared_rating_icon.paint(painter, icon_rect)

            painter.setPen(QColor("#333333"))
            f = painter.font()
            f.setBold(True)
            f.setPixelSize(10)
            painter.setFont(f)
            painter.drawText(QRect(icon_x, current_y, icon_size, icon_size), Qt.AlignmentFlag.AlignCenter, str(rating))

        if display_mode != ImageThumbnail.MODE_THUMBNAIL_ONLY and bottom_space > 0:
            size_for_calcs = max(1, min(thumb_w, thumb_h))
            show_name = False
            show_details = False
            if display_mode == ImageThumbnail.MODE_WITH_NAME:
                show_name = size_for_calcs >= 30
            elif display_mode == ImageThumbnail.MODE_WITH_DETAILS:
                if size_for_calcs >= 50:
                    show_details = True
                else:
                    show_name = size_for_calcs >= 30

            painter.setPen(QColor(text_color))
            text_left = rect.left() + margin
            text_width = rect.width() - 2 * margin
            try:
                text_gap = int(getattr(view, "_text_gap", 2))
            except Exception:
                text_gap = 2
            if text_gap < 0:
                text_gap = 0
            text_top = img_rect.bottom() + text_gap
            text_area_h = max(0, rect.bottom() - text_top)

            font_px = 11
            try:
                sm = getattr(view, "settings_manager", None)
                if sm is not None:
                    font_px = int(sm.get("library/thumbnail_info_font_size", 11))
            except Exception:
                font_px = 11
            font_px = int(max(8, min(20, font_px)))
            line_gap = 1

            if show_details and text_area_h > 0:
                def _format_size_line():
                    try:
                        file_size = int(info.get("size", 0) or 0)
                    except Exception:
                        file_size = 0
                    size_in_kb = file_size / 1024 if file_size > 0 else 0.0
                    try:
                        w0 = int(info.get("width", 0) or 0)
                        h0 = int(info.get("height", 0) or 0)
                    except Exception:
                        w0 = 0
                        h0 = 0
                    if size_in_kb > 0:
                        if size_in_kb > 1024:
                            size_str = f"{size_in_kb/1024:.1f}MB"
                        else:
                            size_str = f"{int(size_in_kb)}KB"
                    else:
                        size_str = "未知大小"
                    if w0 > 0 and h0 > 0:
                        return f"尺寸 {w0}x{h0} | 大小 {size_str}"
                    return f"大小 {size_str}"

                name = info.get("name") or info.get("path") or ""
                shot_time = info.get("shot_time") or info.get("create_time") or ""
                has_exif = bool(info.get("has_exif"))
                if not has_exif:
                    try:
                        has_exif = any(
                            bool(info.get(k))
                            for k in ("focal_length", "iso", "shutter", "fnumber")
                        )
                    except Exception:
                        has_exif = False
                lines = [name, _format_size_line(), shot_time]
                if has_exif:
                    focal_length = info.get("focal_length") or "unknow"
                    fnumber = info.get("fnumber") or 0.0
                    shutter = info.get("shutter") or "unknown s"
                    iso = info.get("iso") or "ISO unknown"
                    lines = [
                        name,
                        _format_size_line(),
                        shot_time,
                        f"{focal_length} , F {fnumber}",
                        f"{shutter} , ISO {iso}",
                    ]
                try:
                    lines = [x for x in lines if str(x).strip()]
                except Exception:
                    pass

                f = painter.font()
                f.setBold(False)
                f.setPixelSize(int(font_px))
                painter.setFont(f)
                fm = QFontMetrics(f)
                line_h = int(fm.height())

                y_pos = int(text_top)
                for text in lines:
                    if y_pos + line_h > rect.bottom():
                        break
                    text_rect = QRect(int(text_left), int(y_pos), int(text_width), int(line_h))
                    try:
                        draw_text = fm.elidedText(str(text), Qt.TextElideMode.ElideRight, text_rect.width())
                    except Exception:
                        draw_text = str(text)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, draw_text)
                    y_pos += int(line_h + line_gap)
            elif show_name and text_area_h > 0:
                name = info.get("name") or ""
                f = painter.font()
                f.setBold(False)
                f.setPixelSize(int(font_px))
                painter.setFont(f)
                fm = QFontMetrics(f)
                line_h = int(fm.height())
                text_rect = QRect(int(text_left), int(text_top), int(text_width), int(line_h))
                try:
                    draw_name = fm.elidedText(str(name), Qt.TextElideMode.ElideRight, text_rect.width())
                except Exception:
                    draw_name = str(name)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, draw_name)

        if selected:
            try:
                sel_bg = QColor(primary)
                sel_bg.setAlphaF(0.22)
                painter.fillRect(rect.adjusted(1, 1, -1, -1), sel_bg)
            except Exception:
                pass
            pen = painter.pen()
            pen.setColor(QColor(primary))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(2, 2, -3, -3))
        else:
            pen = painter.pen()
            pen.setColor(QColor(border))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))

        painter.restore()

    def sizeHint(self, option, index: QModelIndex):
        view = self.parent()
        if view is None:
            return super().sizeHint(option, index)
        thumb_size = getattr(view, "_thumb_size", 120)
        display_mode = getattr(view, "_display_mode", ImageThumbnail.MODE_WITH_NAME)
        font_px = 11
        try:
            sm = getattr(view, "settings_manager", None)
            if sm is not None:
                font_px = int(sm.get("library/thumbnail_info_font_size", 11))
        except Exception:
            font_px = 11
        font_px = int(max(8, min(20, font_px)))
        try:
            text_gap = int(getattr(view, "_text_gap", 2))
        except Exception:
            text_gap = 2
        if text_gap < 0:
            text_gap = 0
        details_max_lines = 5
        if display_mode == ImageThumbnail.MODE_WITH_DETAILS and bool(getattr(view, "_details_compact", False)):
            details_max_lines = 3
        w, h = ImageThumbnail.calculate_size_with_text_font(
            thumb_size,
            display_mode,
            info_font_pixel_size=font_px,
            details_max_lines=details_max_lines,
            text_gap=int(text_gap),
            line_gap=1,
            bottom_padding=2,
        )
        return QSize(int(w), int(h))


class VirtualThumbnailGridView(QWidget):
    itemClicked = pyqtSignal(int, object)
    itemDoubleClicked = pyqtSignal(int)
    contextMenuRequested = pyqtSignal(int, object)
    backgroundContextMenuRequested = pyqtSignal(QPoint)
    selectionChanged = pyqtSignal(int)
    zoomRequested = pyqtSignal(int)
    scrollValueChanged = pyqtSignal(int)
    blankClicked = pyqtSignal()
    sprayActionRequested = pyqtSignal(str, object, list)
    sprayCancelRequested = pyqtSignal()

    is_virtualized = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbnails = []
        self._thumb_size = 120
        self.current_thumb_size = 120
        self._display_mode = ImageThumbnail.MODE_WITH_NAME
        self._details_compact = False
        # 快速滚动时的绘制降级开关：
        # - True 表示 delegate.paint 走“轻量绘制路径”
        self._fast_scroll_simplified = False
        self.last_selected_index = -1
        self.settings_manager = None
        self.spray_mode_active = False
        self.spray_action = None
        self._spray_cursor = None
        self.spray_range_cells = 1
        self._box_select_candidate = False
        self._box_selecting = False
        self._box_start_pos = None
        self._box_end_pos = None

        self._model = _VirtualThumbnailModel(self)
        self._delegate = _VirtualThumbnailDelegate(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.list_view = QListView(self)
        self.scroll_area = self.list_view
        self.thumbnails_container = self.list_view.viewport()
        try:
            self.list_view.setFrameShape(QFrame.Shape.NoFrame)
        except Exception:
            pass
        try:
            self.list_view.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass
        try:
            self.list_view.setViewportMargins(0, 0, 0, 0)
        except Exception:
            pass
        try:
            self.list_view.setStyleSheet("QListView { border: none; padding: 0px; margin: 0px; } QListView::item { padding: 0px; margin: 0px; }")
        except Exception:
            pass
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setMovement(QListView.Movement.Static)
        self.list_view.setWrapping(True)
        self.list_view.setFlow(QListView.Flow.LeftToRight)
        self.list_view.setSpacing(0)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        try:
            self.list_view.setSelectionRectVisible(False)
        except Exception:
            pass
        try:
            self.list_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception:
            pass
        try:
            self.list_view.setDragDropMode(QListView.DragDropMode.NoDragDrop)
        except Exception:
            pass
        try:
            self.list_view.setDragEnabled(False)
        except Exception:
            pass
        try:
            self.list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        except Exception:
            pass
        try:
            self.list_view.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        except Exception:
            pass
        try:
            self.list_view.setBatchSize(250)
        except Exception:
            pass

        self.list_view.setModel(self._model)
        self.list_view.setItemDelegate(self._delegate)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self._on_context_menu_requested)
        self.list_view.clicked.connect(self._on_clicked)
        self.list_view.doubleClicked.connect(self._on_double_clicked)
        self.list_view.verticalScrollBar().valueChanged.connect(self.scrollValueChanged.emit)

        self.list_view.viewport().installEventFilter(self)
        self.list_view.installEventFilter(self)
        if self.list_view.selectionModel() is not None:
            self.list_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self.spray_range_overlay = QFrame(self.list_view.viewport())
        self.spray_range_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.spray_range_overlay.hide()
        self.selection_overlay = QFrame(self.list_view.viewport())
        self.selection_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.selection_overlay.hide()

        layout.addWidget(self.list_view)

        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()
        self._apply_grid_metrics()

    def _update_minimum_width_for_single_thumb(self):
        w = 0
        try:
            gs = self.list_view.gridSize()
            w = int(gs.width() or 0)
        except Exception:
            w = 0
        if w <= 0:
            try:
                font_px = 11
                if self.settings_manager is not None:
                    font_px = int(self.settings_manager.get("library/thumbnail_info_font_size", 11))
                font_px = int(max(8, min(20, font_px)))
            except Exception:
                font_px = 11
            try:
                text_gap = int(getattr(self, "_text_gap", 2))
            except Exception:
                text_gap = 2
            if text_gap < 0:
                text_gap = 0
            details_max_lines = 5
            if self._display_mode == ImageThumbnail.MODE_WITH_DETAILS and bool(getattr(self, "_details_compact", False)):
                details_max_lines = 3
            try:
                w, _h = ImageThumbnail.calculate_size_with_text_font(
                    self.current_thumb_size,
                    self._display_mode,
                    info_font_pixel_size=font_px,
                    details_max_lines=details_max_lines,
                    text_gap=int(text_gap),
                    line_gap=1,
                    bottom_padding=2,
                )
                w = int(w)
            except Exception:
                w = 0
        try:
            min_w = max(1, int(w))
        except Exception:
            min_w = 120
        try:
            self.setMinimumWidth(min_w)
        except Exception:
            pass
        try:
            self.list_view.setMinimumWidth(min_w)
        except Exception:
            pass

    def set_fast_scroll_simplified(self, enabled: bool):
        # 设置快速滚动简化绘制开关
        # 注意：这里只影响绘制复杂度，不改变数据与加载流程
        self._fast_scroll_simplified = bool(enabled)
        try:
            self.list_view.viewport().update()
        except Exception:
            pass

    def set_settings_manager(self, settings_manager):
        self.settings_manager = settings_manager

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.primary")
        scrollbar_bg = cm.get("theme.background.dark")
        scrollbar_handle = cm.get("popup.border.primary")
        scrollbar_hover = cm.get("theme.primary")
        spray_bg = cm.to_qss_color("thumbnail_grid.spray_overlay.background")
        spray_border = cm.to_qss_color("thumbnail_grid.spray_overlay.border")
        select_bg = cm.to_qss_color("zoomable_scroll_area.selection_overlay.background", default="#2196F333")
        select_border = cm.get("theme.primary")
        self.list_view.setStyleSheet(f"""
            QListView {{
                border: none;
                background-color: {panel_bg};
                outline: none;
            }}
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {scrollbar_handle};
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {scrollbar_hover};
            }}
            QScrollBar:horizontal {{
                background-color: {scrollbar_bg};
                height: 10px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {scrollbar_handle};
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {scrollbar_hover};
            }}
        """)
        self.spray_range_overlay.setStyleSheet(f"""
            background-color: {spray_bg};
            border: 1px solid {spray_border};
        """)
        self.selection_overlay.setStyleSheet(f"""
            background-color: {select_bg};
            border: 1px solid {select_border};
        """)
        self._spray_cursor = None
        if self.spray_mode_active:
            cursor = self._create_spray_cursor()
            self.setCursor(cursor)
            self.list_view.viewport().setCursor(cursor)
            self.list_view.setCursor(cursor)

    def _create_spray_cursor(self):
        if self._spray_cursor is None:
            color = ColorManager.instance().get("theme.text.dark")
            try:
                pixmap = qta.icon("fa5s.spray-can", color=color).pixmap(32, 32)
            except Exception:
                try:
                    pixmap = qta.icon("mdi6.spray-can", color=color).pixmap(32, 32)
                except Exception:
                    pixmap = qta.icon("mdi6.spray", color=color).pixmap(32, 32)
            self._spray_cursor = QCursor(pixmap, 2, 2)
        return self._spray_cursor

    def _apply_grid_metrics(self):
        font_px = 11
        try:
            if self.settings_manager is not None:
                font_px = int(self.settings_manager.get("library/thumbnail_info_font_size", 11))
        except Exception:
            font_px = 11
        font_px = int(max(8, min(20, font_px)))
        try:
            text_gap = int(getattr(self, "_text_gap", 2))
        except Exception:
            text_gap = 2
        if text_gap < 0:
            text_gap = 0
        details_max_lines = 5
        if self._display_mode == ImageThumbnail.MODE_WITH_DETAILS and bool(getattr(self, "_details_compact", False)):
            details_max_lines = 3

        w, h = ImageThumbnail.calculate_size_with_text_font(
            self.current_thumb_size,
            self._display_mode,
            info_font_pixel_size=font_px,
            details_max_lines=details_max_lines,
            text_gap=int(text_gap),
            line_gap=1,
            bottom_padding=2,
        )
        self._thumb_size = self.current_thumb_size
        try:
            self.list_view.setGridSize(QSize(int(w), int(h)))
        except Exception:
            pass
        try:
            self.list_view.setIconSize(QSize(int(w), int(h)))
        except Exception:
            pass
        try:
            self.list_view.doItemsLayout()
        except Exception:
            pass
        self.list_view.viewport().update()
        try:
            self._update_minimum_width_for_single_thumb()
        except Exception:
            pass

    def eventFilter(self, source, event):
        if source == self.list_view and event.type() == QEvent.Type.KeyPress:
            if self._handle_thumbnail_nav_key(event):
                event.accept()
                return True
        if source == self.list_view.viewport():
            if event.type() == QEvent.Type.MouseMove:
                if self.spray_mode_active:
                    self._update_spray_range_overlay(event.position().toPoint())
                if self._box_selecting and self._box_start_pos is not None:
                    self._box_end_pos = event.position().toPoint()
                    self._update_box_overlay()
                    self._apply_box_selection()
                    return True
                if self._box_select_candidate and (event.buttons() & Qt.MouseButton.LeftButton) and self._box_start_pos is not None:
                    if (event.position().toPoint() - self._box_start_pos).manhattanLength() >= QApplication.startDragDistance():
                        # 发送模拟 Release 事件，重置 QListView 状态，避免其处于按压状态导致后续点击变为范围选择
                        dummy_pos = QPointF(-100.0, -100.0)
                        release_event = QMouseEvent(
                            QEvent.Type.MouseButtonRelease,
                            dummy_pos,
                            event.globalPosition(),
                            Qt.MouseButton.LeftButton,
                            Qt.MouseButton.NoButton,
                            event.modifiers()
                        )
                        QApplication.sendEvent(self.list_view.viewport(), release_event)

                        self._start_box_select(self._box_start_pos)
                        self._box_end_pos = event.position().toPoint()
                        self._update_box_overlay()
                        self._apply_box_selection()
                        return True
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    pos = event.position().toPoint()
                    idx = self.list_view.indexAt(pos)
                    if not idx.isValid():
                        self.blankClicked.emit()
                        self._start_box_select(pos)
                        return True
                    if self.spray_mode_active:
                        action_type, value = self.spray_action
                        center = pos
                        rect = self._get_spray_rect_for_center(center)
                        indices = self._get_indices_in_rect(rect)
                        if indices:
                            self.sprayActionRequested.emit(action_type, value, indices)
                        return True
                    self._box_select_candidate = True
                    self._box_start_pos = pos
                    self._box_end_pos = pos
            if event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    if self._box_selecting:
                        self._finish_box_select()
                        return True
                    self._box_select_candidate = False
            if event.type() == QEvent.Type.Wheel:
                sm = ShortcutManager.instance()
                is_zoom_in = sm.check_library_zoom_in(event)
                is_zoom_out = sm.check_library_zoom_out(event)
                if is_zoom_in or is_zoom_out:
                    steps = 1 if is_zoom_in else -1
                    if self.spray_mode_active:
                        self._set_spray_range_cells(self.spray_range_cells + steps)
                        if self.settings_manager:
                            self.settings_manager.set("library/spray_range_size", int(self.spray_range_cells))
                        self._update_spray_range_overlay(event.position().toPoint())
                    else:
                        self.zoomRequested.emit(steps)
                    event.accept()
                    return True
        if source == self.list_view and event.type() == QEvent.Type.Resize:
            self._apply_grid_metrics()
        return super().eventFilter(source, event)

    def _handle_thumbnail_nav_key(self, event) -> bool:
        if not self.thumbnails:
            return False
        try:
            if event.modifiers() != Qt.KeyboardModifier.NoModifier:
                return False
        except Exception:
            return False
        sm = ShortcutManager.instance()
        delta = None
        if sm.check_thumbnail_prev(event):
            delta = ("col", -1)
        elif sm.check_thumbnail_next(event):
            delta = ("col", 1)
        elif sm.check_thumbnail_up(event):
            delta = ("row", -1)
        elif sm.check_thumbnail_down(event):
            delta = ("row", 1)
        if delta is None:
            return False
        cur = -1
        try:
            ci = self.list_view.currentIndex()
            if ci is not None and ci.isValid():
                cur = int(ci.row())
        except Exception:
            cur = -1
        if cur < 0:
            try:
                cur = int(getattr(self, "last_selected_index", -1))
            except Exception:
                cur = -1
        if cur < 0:
            cur = 0
        cols = self._get_nav_cols()
        axis, step = delta
        if axis == "col":
            if step < 0 and cur <= 0:
                nxt = len(self.thumbnails) - 1
            elif step > 0 and cur >= len(self.thumbnails) - 1:
                nxt = 0
            else:
                nxt = cur + step
        else:
            if step < 0 and cur < cols:
                col = int(cur) % int(cols)
                last_row = int((len(self.thumbnails) - 1) // int(cols))
                nxt = int(last_row * int(cols) + col)
                while nxt >= len(self.thumbnails) and nxt - cols >= 0:
                    nxt -= int(cols)
            elif step > 0 and (cur + cols) >= len(self.thumbnails):
                nxt = int(cur) % int(cols)
            else:
                nxt = cur + step * cols
        nxt = max(0, min(int(nxt), len(self.thumbnails) - 1))
        if nxt == cur:
            return True
        try:
            mi = self._model.index(int(nxt), 0)
        except Exception:
            return True
        try:
            self.list_view.setCurrentIndex(mi)
        except Exception:
            pass
        try:
            if self.list_view.selectionModel() is not None:
                self.list_view.selectionModel().select(mi, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        except Exception:
            pass
        try:
            self.list_view.scrollTo(mi)
        except Exception:
            pass
        try:
            self.last_selected_index = int(nxt)
        except Exception:
            pass
        try:
            self.list_view.viewport().update()
        except Exception:
            pass
        def _post():
            try:
                self.refresh_visible_thumbnails(extra_rows=1)
            except Exception:
                pass
            try:
                self.itemClicked.emit(int(nxt), Qt.KeyboardModifier.NoModifier)
            except Exception:
                pass
        try:
            QTimer.singleShot(0, _post)
        except Exception:
            _post()
        return True

    def _get_nav_cols(self) -> int:
        try:
            viewport_w = int(self.list_view.viewport().width())
        except Exception:
            viewport_w = 800
        try:
            grid_w = int(self.list_view.gridSize().width())
        except Exception:
            grid_w = 0
        grid_w = max(1, grid_w)
        return max(1, int(viewport_w // grid_w))

    def _start_box_select(self, viewport_pos: QPoint):
        if viewport_pos is None:
            return
        self._box_selecting = True
        self._box_select_candidate = False
        self._box_start_pos = viewport_pos
        self._box_end_pos = viewport_pos
        if self.list_view.selectionModel() is not None:
            self.list_view.selectionModel().clearSelection()
        self.selection_overlay.raise_()
        self.selection_overlay.show()
        self._update_box_overlay()

    def _finish_box_select(self):
        self._box_selecting = False
        self._box_select_candidate = False
        self.selection_overlay.hide()
        self._box_start_pos = None
        self._box_end_pos = None

    def _update_box_overlay(self):
        if self._box_start_pos is None or self._box_end_pos is None:
            return
        rect = QRect(self._box_start_pos, self._box_end_pos).normalized()
        self.selection_overlay.setGeometry(rect)
        self.selection_overlay.raise_()

    def _apply_box_selection(self):
        if self._box_start_pos is None or self._box_end_pos is None:
            return
        if self.list_view.selectionModel() is None:
            return
        rect = QRect(self._box_start_pos, self._box_end_pos).normalized()
        start, end, _ = self.get_visible_index_range(extra_rows=2)
        if end < start:
            return
        self.list_view.selectionModel().blockSignals(True)
        try:
            self.list_view.selectionModel().clearSelection()
            for i in range(max(0, start), min(len(self.thumbnails), end + 1)):
                mi = self._model.index(i, 0)
                vr = self.list_view.visualRect(mi)
                if not vr.isValid():
                    continue
                if rect.intersects(vr):
                    self.list_view.selectionModel().select(mi, QItemSelectionModel.SelectionFlag.Select)
        finally:
            self.list_view.selectionModel().blockSignals(False)
        selected_rows = set()
        try:
            for mi in self.list_view.selectionModel().selectedIndexes():
                selected_rows.add(mi.row())
        except Exception:
            selected_rows = set()
        for i in range(max(0, start), min(len(self.thumbnails), end + 1)):
            item = self._model.get_item(i)
            if item is not None:
                item.selected = i in selected_rows
        self.selectionChanged.emit(self.get_selected_count())
        try:
            self.list_view.viewport().update()
        except Exception:
            pass

    def _on_selection_changed(self, selected, deselected):
        for mi in selected.indexes():
            item = self._model.get_item(mi.row())
            if item is not None:
                item.selected = True
        for mi in deselected.indexes():
            item = self._model.get_item(mi.row())
            if item is not None:
                item.selected = False
        self.selectionChanged.emit(self.get_selected_count())

    def _on_clicked(self, model_index: QModelIndex):
        if not model_index.isValid():
            return
        self.last_selected_index = model_index.row()
        modifiers = QApplication.keyboardModifiers()
        self.itemClicked.emit(model_index.row(), modifiers)

    def _on_double_clicked(self, model_index: QModelIndex):
        if not model_index.isValid():
            return
        self.itemDoubleClicked.emit(model_index.row())

    def _on_context_menu_requested(self, pos: QPoint):
        idx = self.list_view.indexAt(pos)
        global_pos = self.list_view.viewport().mapToGlobal(pos)
        if self.spray_mode_active:
            self.sprayCancelRequested.emit()
            return
        if idx.isValid():
            self.contextMenuRequested.emit(idx.row(), global_pos)
        else:
            self.backgroundContextMenuRequested.emit(self.mapFromGlobal(global_pos))

    def _notify_item_changed(self, row: int):
        self._model.notify_row_changed(row)

    def _request_repaint(self, row: int):
        self._model.notify_row_changed(row)

    def clear_thumbnails(self):
        self.thumbnails.clear()
        self._model.clear()

    def add_thumbnail(self, thumbnail):
        if isinstance(thumbnail, dict):
            info = thumbnail
            try:
                index = int(info.get("index", len(self.thumbnails)))
            except Exception:
                index = len(self.thumbnails)
        else:
            info = getattr(thumbnail, "image_info", None)
            index = getattr(thumbnail, "index", len(self.thumbnails))
        item = _VirtualThumbnailItem(index, info, self._notify_item_changed, self._request_repaint)
        item.thumb_size = self.current_thumb_size
        item.display_mode = self._display_mode
        self.thumbnails.append(item)
        self._model.append_items([item])

    def append_batch_to_layout(self, start_index):
        return

    def arrange_thumbnails(self):
        self._apply_grid_metrics()

    def get_available_width(self):
        return self.list_view.viewport().width()

    def get_viewport_metrics(self):
        available_width = self.get_available_width()
        try:
            grid = self.list_view.gridSize()
            thumb_w = max(1, int(grid.width()))
            thumb_h = max(1, int(grid.height()))
        except Exception:
            thumb_w, thumb_h = ImageThumbnail.calculate_size_with_text_font(
                self.current_thumb_size,
                self._display_mode,
                info_font_pixel_size=11,
                details_max_lines=5,
                text_gap=2,
                line_gap=1,
                bottom_padding=2,
            )
            thumb_w = max(1, int(thumb_w))
            thumb_h = max(1, int(thumb_h))
        cols = max(1, int(available_width) // max(1, int(thumb_w)))
        viewport_h = self.list_view.viewport().height()
        return {"cols": cols, "thumb_w": int(thumb_w), "thumb_h": int(thumb_h), "viewport_h": int(viewport_h)}

    def get_visible_index_range(self, extra_rows=0):
        if not self.thumbnails:
            return 0, -1, 0
        metrics = self.get_viewport_metrics()
        thumb_h = max(1, metrics["thumb_h"])
        cols = max(1, metrics["cols"])
        viewport_h = max(1, metrics["viewport_h"])
        scroll_val = self.list_view.verticalScrollBar().value()
        first_row = max(0, int(scroll_val) // thumb_h)
        view_bottom = int(scroll_val) + int(viewport_h)
        last_row = max(0, (view_bottom - 1) // thumb_h)
        last_row += int(extra_rows or 0)
        visible_rows = last_row - first_row + 1
        start_index = first_row * cols
        end_index = min(len(self.thumbnails) - 1, max(0, (last_row + 1) * cols - 1))
        return start_index, end_index, visible_rows

    def set_image_list(self, image_list):
        items = []
        for i, img_data in enumerate(image_list or []):
            if isinstance(img_data, dict):
                info = img_data
            else:
                info = {"path": "", "name": "", "create_time": ""}
            info["index"] = int(i)
            items.append(_VirtualThumbnailItem(int(i), info, self._notify_item_changed, self._request_repaint))
        for it in items:
            it.thumb_size = self.current_thumb_size
            it.display_mode = self._display_mode
        self.thumbnails = items
        self._model.clear()
        self._model.append_items(items)

    def set_thumbnail_size(self, size, scale_visible_only=False, extra_rows=0):
        if isinstance(size, (tuple, list)):
            try:
                self.current_thumb_size = (int(size[0]), int(size[1]))
            except Exception:
                self.current_thumb_size = 120
        else:
            try:
                self.current_thumb_size = int(size)
            except Exception:
                self.current_thumb_size = 120
        
        self._thumb_size = self.current_thumb_size
        self._apply_grid_metrics()
        try:
            self._update_minimum_width_for_single_thumb()
        except Exception:
            pass

    def set_display_mode(self, mode):
        self._display_mode = int(mode)
        for t in self.thumbnails:
            t.display_mode = self._display_mode
        self._apply_grid_metrics()
        try:
            self._update_minimum_width_for_single_thumb()
        except Exception:
            pass

    def refresh_specific_thumbnails(self, file_paths):
        target_paths = set(file_paths or [])
        for item in self.thumbnails:
            try:
                if item.image_info and item.image_info.get("path") in target_paths:
                    item.update()
            except Exception:
                pass

    def refresh_visible_thumbnails(self, extra_rows: int = 1):
        try:
            if not self.thumbnails or self.list_view is None:
                return
        except Exception:
            return
        try:
            vp = self.list_view.viewport()
            w = max(1, int(vp.width()))
            h = max(1, int(vp.height()))
        except Exception:
            return
        try:
            top = self.list_view.indexAt(QPoint(1, 1))
        except Exception:
            top = QModelIndex()
        try:
            bottom = self.list_view.indexAt(QPoint(max(1, w - 2), max(1, h - 2)))
        except Exception:
            bottom = QModelIndex()
        start = int(top.row()) if top is not None and top.isValid() else 0
        end = int(bottom.row()) if bottom is not None and bottom.isValid() else min(len(self.thumbnails) - 1, start + max(1, self._get_nav_cols()) * 3)
        cols = max(1, self._get_nav_cols())
        try:
            end = min(len(self.thumbnails) - 1, int(end) + int(extra_rows) * cols)
        except Exception:
            end = min(len(self.thumbnails) - 1, int(end) + cols)
        start = max(0, int(start))
        end = min(len(self.thumbnails) - 1, int(end))
        for i in range(start, end + 1):
            try:
                it = self._model.get_item(int(i))
                if it is not None:
                    it.update()
            except Exception:
                pass

    def scroll_to_index(self, index: int):
        if index < 0 or index >= self._model.rowCount():
            return
        mi = self._model.index(index, 0)
        self.list_view.scrollTo(mi, QListView.ScrollHint.PositionAtCenter)

    def select_thumbnail(self, index: int, scroll_to=False):
        if index < 0 or index >= self._model.rowCount():
            return
        mi = self._model.index(index, 0)
        if scroll_to:
            self.scroll_to_index(index)
        try:
            self.list_view.setCurrentIndex(mi)
        except Exception:
            pass
        if self.list_view.selectionModel() is None:
            return
        self.list_view.selectionModel().select(mi, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def clear_selection(self):
        try:
            self.last_selected_index = -1
        except Exception:
            pass
        try:
            if self.list_view.selectionModel() is not None:
                self.list_view.selectionModel().clearSelection()
        except Exception:
            pass
        try:
            self.list_view.setCurrentIndex(QModelIndex())
        except Exception:
            pass
        try:
            self.selectionChanged.emit(0)
        except Exception:
            pass

    def select_all_thumbnails(self):
        self.list_view.selectAll()

    def get_selected_thumbnails(self):
        if self.list_view.selectionModel() is None:
            return []
        items = []
        for mi in self.list_view.selectionModel().selectedIndexes():
            it = self._model.get_item(mi.row())
            if it is not None:
                items.append(it)
        return items

    def get_selected_count(self):
        if self.list_view.selectionModel() is None:
            return 0
        return len(self.list_view.selectionModel().selectedIndexes())

    def _set_spray_range_cells(self, size):
        try:
            size = int(size)
        except Exception:
            size = 1
        self.spray_range_cells = max(1, size)

    def set_spray_range_size(self, size):
        self._set_spray_range_cells(size)
        if self.spray_mode_active:
            self._update_spray_range_overlay(self.list_view.viewport().mapFromGlobal(QCursor.pos()))

    def set_spray_mode(self, active, action_type, value):
        self.spray_mode_active = bool(active)
        self.spray_action = (action_type, value)
        if self.spray_mode_active:
            try:
                self._spray_prev_mouse_tracking_view = bool(self.list_view.hasMouseTracking())
                self._spray_prev_mouse_tracking_vp = bool(self.list_view.viewport().hasMouseTracking())
                self.list_view.setMouseTracking(True)
                self.list_view.viewport().setMouseTracking(True)
            except Exception:
                pass
            cursor = self._create_spray_cursor()
            self.setCursor(cursor)
            self.list_view.viewport().setCursor(cursor)
            self.list_view.setCursor(cursor)
            self.spray_range_overlay.show()
            self.spray_range_overlay.raise_()
            self._update_spray_range_overlay(self.list_view.viewport().mapFromGlobal(QCursor.pos()))
        else:
            self.unsetCursor()
            self.list_view.viewport().unsetCursor()
            self.list_view.unsetCursor()
            self._spray_cursor = None
            self.spray_range_overlay.hide()
            try:
                self.list_view.setMouseTracking(bool(getattr(self, "_spray_prev_mouse_tracking_view", False)))
                self.list_view.viewport().setMouseTracking(bool(getattr(self, "_spray_prev_mouse_tracking_vp", False)))
            except Exception:
                pass

    def _get_spray_rect_for_center(self, center: QPoint):
        metrics = self.get_viewport_metrics()
        cell_w = max(1, int(metrics["thumb_w"]))
        cell_h = max(1, int(metrics["thumb_h"]))
        r = max(1, int(self.spray_range_cells))
        half_w = int((cell_w * r) / 2)
        half_h = int((cell_h * r) / 2)
        return QRect(center.x() - half_w, center.y() - half_h, cell_w * r, cell_h * r)

    def _get_indices_in_rect(self, rect: QRect):
        metrics = self.get_viewport_metrics()
        cell_w = max(1, int(metrics["thumb_w"]))
        cell_h = max(1, int(metrics["thumb_h"]))
        cols = max(1, int(metrics["cols"]))
        scroll_val = int(self.list_view.verticalScrollBar().value())

        x1 = max(0, rect.left())
        y1 = max(0, rect.top())
        x2 = max(0, rect.right())
        y2 = max(0, rect.bottom())

        abs_y1 = scroll_val + y1
        abs_y2 = scroll_val + y2

        row1 = max(0, abs_y1 // cell_h)
        row2 = max(0, abs_y2 // cell_h)
        col1 = max(0, x1 // cell_w)
        col2 = max(0, x2 // cell_w)

        indices = []
        for r in range(row1, row2 + 1):
            base = r * cols
            for c in range(col1, col2 + 1):
                idx = base + c
                if 0 <= idx < len(self.thumbnails):
                    indices.append(idx)
        return indices

    def _update_spray_range_overlay(self, viewport_pos: QPoint):
        if not self.spray_mode_active:
            return
        rect = self._get_spray_rect_for_center(viewport_pos)
        self.spray_range_overlay.setGeometry(rect)
        self.spray_range_overlay.raise_()
        self.spray_range_overlay.show()
