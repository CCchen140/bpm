import os
import json
import tempfile
import subprocess
import time
import re
import shutil
import threading
import hashlib
import math
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QObject, QRunnable, QThreadPool, QPointF, QEvent, QUrl, QRectF, QThread
from PyQt6.QtGui import QImage, QPixmap, QColor, QFont, QFontDatabase, QKeySequence, QShortcut, QFontMetricsF, QCursor, QImageReader, QPainter, QBrush, QPen, QTransform, QPainterPath
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QSlider,
    QFileDialog,
    QCheckBox,
    QProgressBar,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsLineItem,
    QGraphicsTextItem,
    QGraphicsSceneMouseEvent,
    QScrollArea,
    QSplitterHandle,
    QSizePolicy,
    QPlainTextEdit,
    QMenu,
    QAbstractSpinBox,
)

from PyQt6.QtSvg import QSvgRenderer

from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.widgets.themed_color_dialog import ThemedColorDialog
from ui.utils.color_manager import ColorManager
from ui.utils.icon_loader import qta
from ui.utils.notification_manager import NotificationManager
from utils.setting.settings_manager import SettingsManager
from utils.file.file import load_image
from utils.exif.exif_utils import get_exiftool_path, ExifHandleWorker, EXIF_TAG
from utils.sql.data_base import BirdLibraryDB
from utils.file.fingerprint import get_unique_id
from utils.file.file_util import get_fast_id
from utils.log_manager import LogManager
from utils.paths import PathManager


def _cv_to_qimage_bgr(img_bgr: np.ndarray) -> QImage:
    if img_bgr is None or not isinstance(img_bgr, np.ndarray):
        return QImage()
    h, w = img_bgr.shape[:2]
    if h <= 0 or w <= 0:
        return QImage()
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    bytes_per_line = int(img_rgb.strides[0])
    return QImage(img_rgb.data, int(w), int(h), bytes_per_line, QImage.Format.Format_RGB888).copy()


def _fill_meta_from_exifread(file_path: str, meta: dict) -> dict:
    """
    使用 exifread 对 EXIF 进行回填，补齐 exiftool 路径可能缺失的关键字段。

    说明：
    - 本项目存在两条 EXIF 读取链路：exiftool（ExifHandleWorker）与 exifread（信息面板）。
    - 部分图片在 exiftool 下会出现 ISO/快门/光圈等字段为空或缺失，导致水印标签无法替换。
    - 这里在不破坏现有 meta 的前提下，只对“缺失/为空”的字段做回填，保证水印标签与信息面板显示一致。

    参数：
    - file_path: 图片文件路径
    - meta: 已有的元数据字典（可能来自 exiftool）

    返回：
    - 回填后的元数据字典
    """
    p = str(file_path or "")
    if not p or not os.path.exists(p):
        return meta if isinstance(meta, dict) else {}
    out = dict(meta) if isinstance(meta, dict) else {}

    try:
        import exifread
    except Exception:
        return out

    def _first_tag(tags: dict, keys: list[str]) -> str:
        # 按照优先级依次尝试读取 EXIF 标签，取到第一个“可打印且非空”的值就返回
        for k in keys:
            try:
                v = tags.get(k)
            except Exception:
                v = None
            if v is None:
                continue
            try:
                s = getattr(v, "printable", None)
                if s is not None:
                    s = str(s).strip()
                    if s:
                        return s
            except Exception:
                pass
            try:
                s2 = str(v).strip()
                if s2:
                    return s2
            except Exception:
                pass
        return ""

    try:
        with open(p, "rb") as f:
            tags = exifread.process_file(f, details=False, strict=False) or {}
    except Exception:
        tags = {}

    if not _first_non_empty(out.get("DateTimeOriginal")):
        v = _first_tag(tags, ["EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "EXIF DateTime", "Image DateTime"])
        if v:
            out["DateTimeOriginal"] = v
    if not _first_non_empty(out.get("ISO"), out.get("ISOSpeedRatings"), out.get("PhotographicSensitivity")):
        v = _first_tag(tags, ["EXIF ISOSpeedRatings", "EXIF PhotographicSensitivity"])
        if v:
            out["ISO"] = v
    if not _first_non_empty(out.get("ExposureTime"), out.get("ShutterSpeedValue"), out.get("ShutterSpeed")):
        v = _first_tag(tags, ["EXIF ExposureTime", "EXIF ShutterSpeedValue"])
        if v:
            out["ExposureTime"] = v
    if not _first_non_empty(out.get("FNumber"), out.get("ApertureValue"), out.get("Aperture")):
        v = _first_tag(tags, ["EXIF FNumber"])
        if v:
            out["FNumber"] = v
    if not _first_non_empty(out.get("FocalLength")):
        v = _first_tag(tags, ["EXIF FocalLength"])
        if v:
            out["FocalLength"] = v
    if not _first_non_empty(out.get("Model")):
        v = _first_tag(tags, ["Image Model", "EXIF Model"])
        if v:
            out["Model"] = v
    if not _first_non_empty(out.get("LensModel")):
        v = _first_tag(tags, ["EXIF LensModel", "EXIF Lens Model", "MakerNote LensType", "MakerNote Lens"])
        if v:
            out["LensModel"] = v

    def _get_gps_coord(key: str) -> float | None:
        try:
            tag_name = f"GPS GPS{key}"
            ref_name = f"GPS GPS{key}Ref"
            if tag_name not in tags:
                return None
            values = getattr(tags[tag_name], "values", None)
            if not values or len(values) < 3:
                return None
            d = float(values[0])
            m = float(values[1])
            s = float(values[2])
            val = d + m / 60.0 + s / 3600.0
            try:
                if ref_name in tags:
                    ref = str(getattr(tags[ref_name], "values", "")).upper()
                    if ref == "S" or ref == "W":
                        val = -val
            except Exception:
                pass
            return float(val)
        except Exception:
            return None

    if not _first_non_empty(out.get("GPSLatitude"), out.get("GPSLongitude")):
        lat_val = _get_gps_coord("Latitude")
        lng_val = _get_gps_coord("Longitude")
        if lat_val is not None:
            out["GPSLatitude"] = float(lat_val)
            out["GPSLatitudeRef"] = "S" if float(lat_val) < 0 else "N"
        if lng_val is not None:
            out["GPSLongitude"] = float(lng_val)
            out["GPSLongitudeRef"] = "W" if float(lng_val) < 0 else "E"

    return out


def _load_preview_qimage(file_path: str, max_edge: int) -> tuple[QImage, bool | None]:
    p = str(file_path or "")
    if not p:
        return QImage(), None
    try:
        reader = QImageReader(p)
        if not reader.canRead():
            return QImage(), None
        try:
            sz = reader.size()
            w = int(sz.width())
            h = int(sz.height())
        except Exception:
            w, h = 0, 0
        ref_landscape = None
        try:
            if w > 0 and h > 0:
                ref_landscape = bool(w >= h)
        except Exception:
            ref_landscape = None
        if w > 0 and h > 0:
            sw, sh = _scale_long_edge(w, h, int(max_edge))
            try:
                reader.setAutoTransform(True)
            except Exception:
                pass
            try:
                reader.setScaledSize(QSize(int(sw), int(sh)))
            except Exception:
                pass
        img = reader.read()
        return img if isinstance(img, QImage) else QImage(), ref_landscape
    except Exception:
        return QImage(), None

def _scale_long_edge(w: int, h: int, max_edge: int) -> tuple[int, int]:
    w = int(max(1, w))
    h = int(max(1, h))
    max_edge = int(max(1, max_edge))
    long_edge = max(w, h)
    if long_edge <= max_edge:
        return w, h
    scale = max_edge / float(long_edge)
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def _render_svg_to_rgba(svg_path: str, width: int, height: int) -> np.ndarray | None:
    p = str(svg_path or "")
    if not p or not os.path.exists(p):
        return None
    width = int(max(1, width))
    height = int(max(1, height))
    renderer = QSvgRenderer(p)
    if not renderer.isValid():
        return None
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    from PyQt6.QtGui import QPainter

    painter = QPainter(img)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((height, width, 4))
    return arr.copy()

def _render_text_to_bgra(text: str, font_family: str, font_px: int, *, bold: bool = False, italic: bool = False, underline: bool = False, rgba: list[int] | None = None) -> np.ndarray | None:
    """
    使用 Qt 在离屏 QImage 上渲染文本（导出用），保证中文/字体样式与预览一致。
    
    背景与原因：
    - OpenCV 的 putText 仅支持少量内置拉丁字体，中文会被替换成“???”，且抗锯齿/透明度也与 Qt 预览不一致。
    - 预览使用 QGraphicsTextItem（Qt 渲染），导出也应使用 Qt 渲染再与 OpenCV 图像做 alpha 合成，才能做到一致。
    
    参数：
    - text: 需要渲染的文本（支持换行）
    - font_family: 字体族名（为空时由 Qt 选择系统默认字体）
    - font_px: 字号（像素）
    - bold/italic/underline: 字体样式
    - rgba: 文本颜色与透明度 [R, G, B, A]
    
    返回：
    - BGRA 格式的 numpy 数组（uint8），可直接与 BGR 图片做 alpha 合成
    """
    try:
        s = str(text or "")
    except Exception:
        s = ""
    if not s:
        return None
    try:
        font_px = int(max(1, int(font_px)))
    except Exception:
        font_px = 24
    try:
        c = list(rgba or [255, 255, 255, 255])
        r, g, b, a = int(c[0]), int(c[1]), int(c[2]), int(c[3])
        r = int(max(0, min(255, r)))
        g = int(max(0, min(255, g)))
        b = int(max(0, min(255, b)))
        a = int(max(0, min(255, a)))
    except Exception:
        r, g, b, a = 255, 255, 255, 255
    font = QFont(str(font_family or ""))
    try:
        font.setPixelSize(int(font_px))
    except Exception:
        pass
    try:
        font.setBold(bool(bold))
        font.setItalic(bool(italic))
        font.setUnderline(bool(underline))
    except Exception:
        pass
    fm = QFontMetricsF(font)
    try:
        lines = [str(x) for x in str(s).splitlines()]
    except Exception:
        lines = [s]
    if not lines:
        lines = [""]
    lefts = []
    rights = []
    for line in lines:
        sline = line if line != "" else " "
        try:
            br = fm.boundingRect(str(sline))
            lefts.append(float(br.left()))
            rights.append(float(br.right()))
        except Exception:
            lefts.append(0.0)
            rights.append(1.0)
    try:
        line_h = int(max(1, round(float(fm.height()))))
        ascent = int(max(1, round(float(fm.ascent()))))
    except Exception:
        line_h = int(max(1, font_px))
        ascent = int(max(1, int(round(font_px * 0.8))))
    pad = 2
    min_left = float(min(lefts) if lefts else 0.0)
    max_right = float(max(rights) if rights else 1.0)
    text_w = float(max(1.0, max_right - min_left))
    w = int(max(1, round(text_w + float(pad * 2))))
    h = int(max(1, line_h * len(lines) + pad * 2))
    img = QImage(int(w), int(h), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    try:
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        except Exception:
            pass
        try:
            painter.setFont(font)
        except Exception:
            pass
        try:
            pen = QPen(QColor(int(r), int(g), int(b), int(a)))
            painter.setPen(pen)
        except Exception:
            painter.setPen(QColor(int(r), int(g), int(b), int(a)))
        try:
            x_base = float(pad) - float(min_left)
        except Exception:
            x_base = float(pad)
        for i, line in enumerate(lines):
            try:
                y = int(pad + ascent + i * line_h)
                painter.drawText(QPointF(float(x_base), float(y)), str(line))
            except Exception:
                pass
    finally:
        try:
            painter.end()
        except Exception:
            pass
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((int(h), int(w), 4))
    return arr.copy()

_TEXT_RENDER_SERVICE = None

class _TextRenderService(QObject):
    request = pyqtSignal(int, object)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._pending = {}
        self._seq = 0
        try:
            self.request.connect(self._on_request, Qt.ConnectionType.QueuedConnection)
        except Exception:
            self.request.connect(self._on_request)

    def render_sync(self, payload: dict) -> object:
        try:
            if QThread.currentThread() == self.thread():
                return self._render(payload)
        except Exception:
            pass
        ev = threading.Event()
        box = {}
        with self._lock:
            self._seq = int(self._seq) + 1
            rid = int(self._seq)
            self._pending[rid] = (ev, box)
        try:
            self.request.emit(int(rid), payload)
        except Exception:
            with self._lock:
                try:
                    self._pending.pop(rid, None)
                except Exception:
                    pass
            return None
        try:
            ev.wait(20.0)
        except Exception:
            pass
        with self._lock:
            try:
                self._pending.pop(rid, None)
            except Exception:
                pass
        return box.get("result")

    def _on_request(self, rid: int, payload: object):
        res = None
        try:
            res = self._render(payload if isinstance(payload, dict) else {})
        except Exception:
            res = None
        ev = None
        box = None
        with self._lock:
            v = self._pending.get(int(rid))
            if v:
                ev, box = v
        if isinstance(box, dict):
            try:
                box["result"] = res
            except Exception:
                pass
        if ev is not None:
            try:
                ev.set()
            except Exception:
                pass

    def _render(self, payload: dict) -> object:
        try:
            mode = str(payload.get("mode") or "text_raw")
            if mode == "text_patch":
                return _render_text_patch_to_bgra(
                    str(payload.get("text") or ""),
                    str(payload.get("font_family") or ""),
                    int(payload.get("font_px") or 24),
                    bold=bool(payload.get("bold")),
                    italic=bool(payload.get("italic")),
                    underline=bool(payload.get("underline")),
                    rgba=payload.get("rgba"),
                    angle_deg=float(payload.get("angle_deg") or 0.0),
                    supersample=int(payload.get("supersample") or 2),
                    stroke_width=int(payload.get("stroke_width") or 0),
                    stroke_rgba=payload.get("stroke_rgba"),
                    shadow_offset=payload.get("shadow_offset"),
                    shadow_rgba=payload.get("shadow_rgba"),
                    shadow_range=payload.get("shadow_range"),
                    shadow_style=payload.get("shadow_style"),
                    mirror_gap_px=payload.get("mirror_gap_px"),
                    mirror_angle_deg=payload.get("mirror_angle_deg"),
                    stack_count=payload.get("stack_count"),
                    stack_step_px=payload.get("stack_step_px"),
                )
            return _render_text_to_bgra(
                str(payload.get("text") or ""),
                str(payload.get("font_family") or ""),
                int(payload.get("font_px") or 24),
                bold=bool(payload.get("bold")),
                italic=bool(payload.get("italic")),
                underline=bool(payload.get("underline")),
                rgba=payload.get("rgba"),
            )
        except Exception:
            return None

def _render_text_to_bgra_safe(text: str, font_family: str, font_px: int, *, bold: bool = False, italic: bool = False, underline: bool = False, rgba: list[int] | None = None) -> np.ndarray | None:
    svc = globals().get("_TEXT_RENDER_SERVICE")
    if svc is None or not isinstance(svc, _TextRenderService):
        try:
            app = QApplication.instance()
            if app is not None and QThread.currentThread() != app.thread():
                return None
        except Exception:
            return None
        return _render_text_to_bgra(text, font_family, font_px, bold=bold, italic=italic, underline=underline, rgba=rgba)
    payload = {
        "mode": "text_raw",
        "text": str(text or ""),
        "font_family": str(font_family or ""),
        "font_px": int(font_px or 24),
        "bold": bool(bold),
        "italic": bool(italic),
        "underline": bool(underline),
        "rgba": list(rgba) if isinstance(rgba, list) else None,
    }
    try:
        out = svc.render_sync(payload)
    except Exception:
        out = None
    if out is None or not isinstance(out, np.ndarray):
        try:
            app = QApplication.instance()
            if app is not None and QThread.currentThread() != app.thread():
                return None
        except Exception:
            return None
        return _render_text_to_bgra(text, font_family, font_px, bold=bold, italic=italic, underline=underline, rgba=rgba)
    return out

def _apply_mirror_effect_bgra(img_bgra: np.ndarray, *, strength: float = 0.6, gap_px: int = 0, ref_ratio: float = 0.6) -> np.ndarray:
    if img_bgra is None or not isinstance(img_bgra, np.ndarray) or img_bgra.ndim != 3 or img_bgra.shape[2] < 4:
        return img_bgra
    try:
        h, w = img_bgra.shape[:2]
    except Exception:
        return img_bgra
    if int(h) <= 0 or int(w) <= 0:
        return img_bgra
    try:
        gap = int(max(0, min(int(h), int(gap_px or 0))))
    except Exception:
        gap = 0
    try:
        ref_h = int(max(1, round(float(h) * float(ref_ratio))))
    except Exception:
        ref_h = int(max(1, round(float(h) * 0.6)))
    try:
        canvas = np.zeros((int(h + gap + ref_h), int(w), 4), dtype=np.uint8)
        canvas[:h, :w] = img_bgra
        ref = img_bgra[::-1, :, :].copy()
        ref = ref[:ref_h, :, :]
        if ref_h > 1:
            grad = np.linspace(1.0, 0.0, int(ref_h), dtype=np.float32).reshape((int(ref_h), 1))
        else:
            grad = np.array([[1.0]], dtype=np.float32)
        alpha = ref[:, :, 3].astype(np.float32) / 255.0
        try:
            k = float(max(0.0, min(1.0, float(strength))))
        except Exception:
            k = 0.6
        alpha = alpha * grad * k
        ref[:, :, 0:3] = np.clip(ref[:, :, 0:3].astype(np.float32) * 0.95, 0.0, 255.0).astype(np.uint8)
        ref[:, :, 3] = np.clip(alpha * 255.0, 0.0, 255.0).astype(np.uint8)
        canvas[int(h + gap):int(h + gap + ref_h), :w] = ref
        return canvas
    except Exception:
        return img_bgra

<<<<<<< HEAD
def _apply_mirror_shadow_bgra(img_bgra: np.ndarray, *, direction: tuple[int, int], gap_px: int, rgba: list[int], blur: int = 0, angle_deg: float | None = None) -> np.ndarray:
=======
def _apply_mirror_shadow_bgra(img_bgra: np.ndarray, *, direction: tuple[int, int], gap_px: int, rgba: list[int], blur: int = 0) -> np.ndarray:
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    if img_bgra is None or not isinstance(img_bgra, np.ndarray) or img_bgra.ndim != 3 or img_bgra.shape[2] < 4:
        return img_bgra
    try:
        h, w = img_bgra.shape[:2]
    except Exception:
        return img_bgra
    if int(h) <= 0 or int(w) <= 0:
        return img_bgra
    try:
        dx, dy = int(direction[0] or 0), int(direction[1] or 0)
    except Exception:
        dx, dy = 0, 1
    try:
        gap = int(max(0, min(200, int(gap_px or 0))))
    except Exception:
        gap = 0
    try:
        c = [int(max(0, min(255, int(x)))) for x in (rgba or [0, 0, 0, 153])[:4]]
        cr, cg, cb, ca = int(c[0]), int(c[1]), int(c[2]), int(c[3])
    except Exception:
        cr, cg, cb, ca = 0, 0, 0, 153
    alpha0 = img_bgra[:, :, 3].astype(np.float32) / 255.0
    alpha1 = np.clip(alpha0 * (float(ca) / 255.0), 0.0, 1.0)
    try:
        sigma = float(max(0.0, float(int(blur) if blur is not None else 0) / 100.0 * 3.2))
    except Exception:
        sigma = 0.0
    if sigma > 1e-6:
        try:
            alpha1 = cv2.GaussianBlur(alpha1, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_CONSTANT)
        except Exception:
            pass
    try:
        # 防止模糊后在整块画布上留下极低透明度，合成到背景时会表现为“半透明矩形遮挡”
        alpha1 = np.where(alpha1 < (2.0 / 255.0), 0.0, alpha1)
    except Exception:
        pass
    layer = np.zeros((int(h), int(w), 4), dtype=np.uint8)
    a_u8 = np.clip(alpha1 * 255.0, 0.0, 255.0).astype(np.uint8)
    layer[:, :, 3] = a_u8
    try:
        m = a_u8 > 0
        if bool(m.any()):
            layer[m, 0] = int(cb)
            layer[m, 1] = int(cg)
            layer[m, 2] = int(cr)
    except Exception:
        layer[:, :, 0] = int(cb)
        layer[:, :, 1] = int(cg)
        layer[:, :, 2] = int(cr)
    vx = 0 if int(dx) == 0 else (1 if int(dx) > 0 else -1)
    vy = 0 if int(dy) == 0 else (1 if int(dy) > 0 else -1)
<<<<<<< HEAD
    use_vertical = True
    try:
        use_vertical = bool(abs(int(dy)) >= abs(int(dx)))
    except Exception:
        use_vertical = True
    f = 1.0
    try:
        a = float(angle_deg if angle_deg is not None else 180.0)
        a = float(max(0.0, min(180.0, a)))
        f = float(abs(math.cos(math.radians(a))))
        f = float(max(0.02, min(1.0, f)))
    except Exception:
        f = 1.0
    def _alpha_over(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
        """
        将 src 以 alpha 叠加到 dst 指定位置（src 覆盖 dst）。
        
        说明：
        - 镜像阴影在 gap=0 时可能与原图发生重叠，如果直接用数组赋值会出现“阴影把水印盖住一块”的问题。
        - 这里使用标准 alpha 合成，且保证后续把原图叠加到阴影上时不会把阴影透明区抹掉。
        """
        if dst is None or src is None:
            return
        try:
            dh, dw = dst.shape[:2]
            sh, sw = src.shape[:2]
        except Exception:
            return
        if dh <= 0 or dw <= 0 or sh <= 0 or sw <= 0:
            return
        x0 = int(max(0, x))
        y0 = int(max(0, y))
        x1 = int(min(dw, x + sw))
        y1 = int(min(dh, y + sh))
        if x1 <= x0 or y1 <= y0:
            return
        sx0 = int(x0 - x)
        sy0 = int(y0 - y)
        sx1 = int(sx0 + (x1 - x0))
        sy1 = int(sy0 + (y1 - y0))
        try:
            roi = dst[y0:y1, x0:x1]
            s = src[sy0:sy1, sx0:sx1]
            a_s = s[:, :, 3:4].astype(np.float32) / 255.0
            a_d = roi[:, :, 3:4].astype(np.float32) / 255.0
            out_a = a_s + a_d * (1.0 - a_s)
            roi[:, :, 0:3] = np.clip(s[:, :, 0:3].astype(np.float32) * a_s + roi[:, :, 0:3].astype(np.float32) * (1.0 - a_s), 0.0, 255.0).astype(np.uint8)
            roi[:, :, 3:4] = np.clip(out_a * 255.0, 0.0, 255.0).astype(np.uint8)
        except Exception:
            return
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    def _edge_empty_rows(alpha: np.ndarray) -> tuple[int, int]:
        try:
            mask = np.any(alpha > 0, axis=1)
            if not bool(mask.any()):
                return int(alpha.shape[0]), int(alpha.shape[0])
            top = int(np.argmax(mask))
            bottom = int(alpha.shape[0] - 1 - np.argmax(mask[::-1]))
            return int(top), int(alpha.shape[0] - 1 - bottom)
        except Exception:
            return 0, 0
    def _edge_empty_cols(alpha: np.ndarray) -> tuple[int, int]:
        try:
            mask = np.any(alpha > 0, axis=0)
            if not bool(mask.any()):
                return int(alpha.shape[1]), int(alpha.shape[1])
            left = int(np.argmax(mask))
            right = int(alpha.shape[1] - 1 - np.argmax(mask[::-1]))
            return int(left), int(alpha.shape[1] - 1 - right)
        except Exception:
            return 0, 0
<<<<<<< HEAD
    if use_vertical:
        flip = layer[::-1, :, :].copy()
        a_flip_src = img_bgra[::-1, :, 3]
        flip_h = int(h)
        if float(f) < 0.999:
            try:
                flip_h = int(max(1, round(float(h) * float(f))))
                interp = cv2.INTER_AREA if int(flip_h) < int(h) else cv2.INTER_LINEAR
                flip = cv2.resize(flip, (int(w), int(flip_h)), interpolation=interp)
                a_flip_src = cv2.resize(a_flip_src, (int(w), int(flip_h)), interpolation=interp)
            except Exception:
                flip_h = int(h)
                a_flip_src = img_bgra[::-1, :, 3]
                flip = layer[::-1, :, :].copy()
        overlap = 0
        vy_sign = 1 if int(vy) >= 0 else -1
        try:
            # 无论 gap=0 还是 gap>0，都用透明边距来“抵消”空白，避免 0 与 1 差距过大
            a_img = img_bgra[:, :, 3]
            top_img, bottom_img = _edge_empty_rows(a_img)
            top_flip, bottom_flip = _edge_empty_rows(a_flip_src)
            if int(vy_sign) > 0:
                overlap = int(max(0, min(int(h), int(bottom_img) + int(top_flip))))
            else:
                overlap = int(max(0, min(int(flip_h), int(bottom_flip) + int(top_img))))
        except Exception:
            overlap = 0
        shift_x_mag = 0
        try:
            if int(vx) != 0 and int(vy) != 0:
                base_shift = int(round(float(max(1, min(int(w), int(h)))) * 0.12))
                shift_x_mag = int(max(6, min(60, base_shift)))
        except Exception:
            shift_x_mag = 0
        canvas_h = int((int(h) + int(gap) + int(flip_h) - int(overlap)) if int(vy_sign) > 0 else (int(flip_h) + int(gap) + int(h) - int(overlap)))
        canvas_w = int(w + shift_x_mag)
=======
    # 镜像阴影：方向可能是斜向（例如左下/右下），需要在主轴镜像的同时做正交方向偏移
    # 镜像阴影：当间隔为 0 时，让两部分尽量贴合，避免因为透明边距导致“中间有大空白”
    shift_x = 0
    shift_y = 0
    # 斜向时需要明显的“侧向偏移”，否则左右/上下会看起来一样
    # 这里用图块尺寸的比例来估算偏移，保证不同字号下视觉一致
    try:
        if int(vy) != 0 and int(vx) != 0:
            base_shift = int(round(float(max(1, min(int(w), int(h)))) * 0.12))
            shift_x = int(max(6, min(60, base_shift)))
    except Exception:
        shift_x = 0
    try:
        if int(vx) != 0 and int(vy) != 0:
            base_shift = int(round(float(max(1, min(int(w), int(h)))) * 0.12))
            shift_y = int(max(6, min(60, base_shift)))
    except Exception:
        shift_y = 0
    if vy != 0:
        flip = layer[::-1, :, :].copy()
        overlap = 0
        if int(gap) <= 0:
            try:
                a_img = img_bgra[:, :, 3]
                a_flip_src = img_bgra[::-1, :, 3]
                top_img, bottom_img = _edge_empty_rows(a_img)
                top_flip, bottom_flip = _edge_empty_rows(a_flip_src)
                if vy > 0:
                    overlap = int(max(0, min(int(h), int(bottom_img) + int(top_flip))))
                else:
                    overlap = int(max(0, min(int(h), int(bottom_flip) + int(top_img))))
            except Exception:
                overlap = 0
        canvas_h = int(h + gap + h - overlap)
        canvas_w = int(w + (shift_x if int(vx) != 0 else 0))
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        canvas = np.zeros((int(canvas_h), int(canvas_w), 4), dtype=np.uint8)
        x_img = 0
        x_flip = 0
        if int(vx) >= 0:
<<<<<<< HEAD
            x_flip = int(shift_x_mag)
        else:
            x_img = int(shift_x_mag)
        if int(vy_sign) > 0:
            y_img = 0
            y_flip = int(int(h) + int(gap) - int(overlap))
            _alpha_over(canvas, flip, int(x_flip), int(y_flip))
            _alpha_over(canvas, img_bgra, int(x_img), int(y_img))
        else:
            y_flip = 0
            y_img = int(int(flip_h) + int(gap) - int(overlap))
            _alpha_over(canvas, flip, int(x_flip), int(y_flip))
            _alpha_over(canvas, img_bgra, int(x_img), int(y_img))
        return canvas
    flip = layer[:, ::-1, :].copy()
    a_flip_src = img_bgra[:, ::-1, 3]
    flip_w = int(w)
    if float(f) < 0.999:
        try:
            flip_w = int(max(1, round(float(w) * float(f))))
            interp = cv2.INTER_AREA if int(flip_w) < int(w) else cv2.INTER_LINEAR
            flip = cv2.resize(flip, (int(flip_w), int(h)), interpolation=interp)
            a_flip_src = cv2.resize(a_flip_src, (int(flip_w), int(h)), interpolation=interp)
        except Exception:
            flip_w = int(w)
            a_flip_src = img_bgra[:, ::-1, 3]
            flip = layer[:, ::-1, :].copy()
    overlap = 0
    vx_sign = 1 if int(vx) >= 0 else -1
    try:
        a_img = img_bgra[:, :, 3]
        left_img, right_img = _edge_empty_cols(a_img)
        left_flip, right_flip = _edge_empty_cols(a_flip_src)
        if int(vx_sign) > 0:
            overlap = int(max(0, min(int(w), int(right_img) + int(left_flip))))
        else:
            overlap = int(max(0, min(int(flip_w), int(right_flip) + int(left_img))))
    except Exception:
        overlap = 0
    shift_y_mag = 0
    try:
        if int(vx) != 0 and int(vy) != 0:
            base_shift = int(round(float(max(1, min(int(w), int(h)))) * 0.12))
            shift_y_mag = int(max(6, min(60, base_shift)))
    except Exception:
        shift_y_mag = 0
    canvas_w = int((int(w) + int(gap) + int(flip_w) - int(overlap)) if int(vx_sign) > 0 else (int(flip_w) + int(gap) + int(w) - int(overlap)))
    canvas_h = int(h + shift_y_mag)
=======
            x_flip = int(shift_x)
        else:
            x_img = int(shift_x)
        if vy > 0:
            y_img = 0
            y_flip = int(h + gap - overlap)
            canvas[int(y_img):int(y_img + h), int(x_img):int(x_img + w)] = img_bgra
            canvas[int(y_flip):int(y_flip + h), int(x_flip):int(x_flip + w)] = flip
        else:
            y_flip = 0
            y_img = int(h + gap - overlap)
            canvas[int(y_flip):int(y_flip + h), int(x_flip):int(x_flip + w)] = flip
            canvas[int(y_img):int(y_img + h), int(x_img):int(x_img + w)] = img_bgra
        return canvas
    flip = layer[:, ::-1, :].copy()
    overlap = 0
    if int(gap) <= 0:
        try:
            a_img = img_bgra[:, :, 3]
            a_flip_src = img_bgra[:, ::-1, 3]
            left_img, right_img = _edge_empty_cols(a_img)
            left_flip, right_flip = _edge_empty_cols(a_flip_src)
            if vx > 0:
                overlap = int(max(0, min(int(w), int(right_img) + int(left_flip))))
            else:
                overlap = int(max(0, min(int(w), int(right_flip) + int(left_img))))
        except Exception:
            overlap = 0
    canvas_w = int(w + gap + w - overlap)
    canvas_h = int(h + (shift_y if int(vy) != 0 else 0))
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    canvas = np.zeros((int(canvas_h), int(canvas_w), 4), dtype=np.uint8)
    y_img = 0
    y_flip = 0
    if int(vy) >= 0:
<<<<<<< HEAD
        y_flip = int(shift_y_mag)
    else:
        y_img = int(shift_y_mag)
    if int(vx_sign) > 0:
        x_img = 0
        x_flip = int(int(w) + int(gap) - int(overlap))
        _alpha_over(canvas, flip, int(x_flip), int(y_flip))
        _alpha_over(canvas, img_bgra, int(x_img), int(y_img))
    else:
        x_flip = 0
        x_img = int(int(flip_w) + int(gap) - int(overlap))
        _alpha_over(canvas, flip, int(x_flip), int(y_flip))
        _alpha_over(canvas, img_bgra, int(x_img), int(y_img))
=======
        y_flip = int(shift_y)
    else:
        y_img = int(shift_y)
    if vx > 0:
        x_img = 0
        x_flip = int(w + gap - overlap)
        canvas[int(y_img):int(y_img + h), int(x_img):int(x_img + w)] = img_bgra
        canvas[int(y_flip):int(y_flip + h), int(x_flip):int(x_flip + w)] = flip
    else:
        x_flip = 0
        x_img = int(w + gap - overlap)
        canvas[int(y_flip):int(y_flip + h), int(x_flip):int(x_flip + w)] = flip
        canvas[int(y_img):int(y_img + h), int(x_img):int(x_img + w)] = img_bgra
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    return canvas

def _render_text_patch_to_bgra(
    text: str,
    font_family: str,
    font_px: int,
    *,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    rgba: list[int] | None = None,
    angle_deg: float = 0.0,
    supersample: int = 2,
    stroke_width: int = 0,
    stroke_rgba: list[int] | None = None,
    shadow_offset: tuple[int, int] | None = None,
    shadow_rgba: list[int] | None = None,
    shadow_range: int | None = None,
    shadow_style: str | None = None,
    mirror_gap_px: int | None = None,
<<<<<<< HEAD
    mirror_angle_deg: float | None = None,
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    stack_count: int | None = None,
    stack_step_px: int | None = None,
) -> np.ndarray | None:
    try:
        s = str(text or "")
    except Exception:
        s = ""
    if not s:
        return None
    try:
        base_px = int(max(1, int(font_px)))
    except Exception:
        base_px = 24
    try:
        ss = int(max(1, min(8, int(supersample or 1))))
    except Exception:
        ss = 2
    try:
        c = list(rgba or [255, 255, 255, 255])
        r, g, b, a = int(c[0]), int(c[1]), int(c[2]), int(c[3])
        r = int(max(0, min(255, r)))
        g = int(max(0, min(255, g)))
        b = int(max(0, min(255, b)))
        a = int(max(0, min(255, a)))
    except Exception:
        r, g, b, a = 255, 255, 255, 255
    try:
        sw = int(max(0, int(stroke_width or 0)))
    except Exception:
        sw = 0
    try:
        so = shadow_offset if isinstance(shadow_offset, tuple) and len(shadow_offset) == 2 else (0, 0)
        sdx = int(so[0] or 0)
        sdy = int(so[1] or 0)
    except Exception:
        sdx, sdy = 0, 0
    try:
        sc = list(stroke_rgba or [])
        sr, sg, sb, sa = int(sc[0]), int(sc[1]), int(sc[2]), int(sc[3])
        sr = int(max(0, min(255, sr)))
        sg = int(max(0, min(255, sg)))
        sb = int(max(0, min(255, sb)))
        sa = int(max(0, min(255, sa)))
    except Exception:
        sr, sg, sb, sa = 0, 0, 0, int(a)
    try:
        sh = list(shadow_rgba or [])
        shr, shg, shb, sha = int(sh[0]), int(sh[1]), int(sh[2]), int(sh[3])
        shr = int(max(0, min(255, shr)))
        shg = int(max(0, min(255, shg)))
        shb = int(max(0, min(255, shb)))
        sha = int(max(0, min(255, sha)))
    except Exception:
        shr, shg, shb, sha = int(r), int(g), int(b), int(max(0, min(255, round(int(a) * 0.6))))
    try:
        sh_style = str(shadow_style or "solid").strip().lower()
    except Exception:
        sh_style = "solid"
    try:
        srng = int(shadow_range if shadow_range is not None else 0)
    except Exception:
        srng = 0
    srng = int(max(0, min(100, srng)))
    try:
        mgap = int(mirror_gap_px if mirror_gap_px is not None else 0)
    except Exception:
        mgap = 0
    mgap = int(max(0, min(200, mgap)))
    try:
        scount = int(stack_count if stack_count is not None else 3)
    except Exception:
        scount = 3
    scount = int(max(1, min(20, scount)))
    try:
        sstep = int(stack_step_px if stack_step_px is not None else 2)
    except Exception:
        sstep = 2
    sstep = int(max(0, min(50, sstep)))
    font = QFont(str(font_family or ""))
    try:
        font.setPixelSize(int(base_px * ss))
    except Exception:
        pass
    try:
        font.setBold(bool(bold))
        font.setItalic(bool(italic))
        font.setUnderline(bool(underline))
    except Exception:
        pass
    fm = QFontMetricsF(font)
    try:
        lines = [str(x) for x in str(s).splitlines()]
    except Exception:
        lines = [s]
    if not lines:
        lines = [""]
    lefts = []
    rights = []
    for line in lines:
        sline = line if line != "" else " "
        try:
            br = fm.boundingRect(str(sline))
            lefts.append(float(br.left()))
            rights.append(float(br.right()))
        except Exception:
            lefts.append(0.0)
            rights.append(1.0)
    try:
        line_h = float(fm.height())
        ascent = float(fm.ascent())
    except Exception:
        line_h = float(max(1, int(base_px * ss)))
        ascent = float(max(1, int(round(base_px * ss * 0.8))))
    try:
        dist0 = int(max(abs(int(sdx)), abs(int(sdy))))
    except Exception:
        dist0 = 0
    extra_shadow = 0
    if sha > 0 and dist0 > 0:
        if sh_style in ("trail", "beam"):
            # 光束/拖尾的“模糊度”需要对阴影边缘范围产生明显影响
            # 这里扩大 padding，避免后续模糊被裁剪，同时让模糊对边缘软化更明显
            extra_shadow = int(round(float(dist0) * 1.8)) + int(round(float(srng) / 100.0 * 120.0)) + 20
        elif sh_style == "stack":
            extra_shadow = int(int(sstep) * int(scount)) + 4
        elif sh_style == "mirror":
            extra_shadow = int(round(float(srng) / 100.0 * 12.0)) + 6
        else:
            extra_shadow = int(dist0) + 2
    extra = int(max(0, int(sw) + int(extra_shadow)))
    pad = float((2 + extra) * ss)
    min_left = float(min(lefts) if lefts else 0.0)
    max_right = float(max(rights) if rights else 1.0)
    text_w = float(max(1.0, max_right - min_left))
    w0 = float(max(1.0, text_w + pad * 2.0))
    h0 = float(max(1.0, line_h * float(len(lines)) + pad * 2.0))
    try:
        ang = float(angle_deg or 0.0)
    except Exception:
        ang = 0.0
    rad = math.radians(float(ang))
    cosv = abs(math.cos(rad))
    sinv = abs(math.sin(rad))
    w1 = float(max(1.0, w0 * cosv + h0 * sinv))
    h1 = float(max(1.0, w0 * sinv + h0 * cosv))
    img = QImage(int(math.ceil(w1)), int(math.ceil(h1)), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    try:
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.HighQualityAntialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        except Exception:
            pass
        try:
            painter.setFont(font)
        except Exception:
            pass
        try:
            x_base = float(pad) - float(min_left)
        except Exception:
            x_base = float(pad)
        base_path = QPainterPath()
        underline_lines = []
        try:
            ul_pos = float(fm.underlinePos())
        except Exception:
            ul_pos = 0.0
        try:
            ul_w = float(max(1.0, float(fm.lineWidth())))
        except Exception:
            ul_w = 1.0
        for i, line in enumerate(lines):
            sline = str(line or "")
            try:
                y = float(pad + ascent + float(i) * line_h)
            except Exception:
                y = float(pad)
            if sline:
                try:
                    base_path.addText(QPointF(float(x_base), float(y)), font, str(sline))
                except Exception:
                    pass
            if bool(underline):
                try:
                    adv = float(fm.horizontalAdvance(str(sline if sline else " ")))
                    underline_lines.append((float(x_base), float(y + ul_pos), float(x_base + adv), float(y + ul_pos)))
                except Exception:
                    pass
        def _fill_text_at(p: QPainter, dx0: float, dy0: float, color: QColor):
            """
            在指定偏移处“填充”文字路径（用于更平滑的斜线/曲线/字体边缘）。

            参数：
            - p: 目标画笔
            - dx0/dy0: 相对当前坐标系的偏移量
            - color: 填充颜色（包含透明度）
            """
            p.save()
            try:
                p.translate(float(dx0), float(dy0))
            except Exception:
                pass
            try:
                p.fillPath(base_path, color)
            except Exception:
                pass
            if underline_lines:
                try:
                    pen = QPen(color)
                    pen.setWidthF(float(ul_w))
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    p.setPen(pen)
                    for x1, y1, x2, y2 in underline_lines:
                        p.drawLine(QPointF(float(x1), float(y1)), QPointF(float(x2), float(y2)))
                except Exception:
                    pass
            p.restore()
        def _stroke_text_at(p: QPainter, dx0: float, dy0: float, pen: QPen):
            """
            在指定偏移处“描边”文字路径（用于边框粗细正确生效且更平滑）。

            参数：
            - p: 目标画笔
            - dx0/dy0: 相对当前坐标系的偏移量
            - pen: 描边画笔（需包含宽度、连接/端点样式、颜色透明度等）
            """
            p.save()
            try:
                p.translate(float(dx0), float(dy0))
            except Exception:
                pass
            try:
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(base_path)
            except Exception:
                pass
            if underline_lines:
                try:
                    p.setPen(pen)
                    for x1, y1, x2, y2 in underline_lines:
                        p.drawLine(QPointF(float(x1), float(y1)), QPointF(float(x2), float(y2)))
                except Exception:
                    pass
            p.restore()
        try:
            painter.translate(float(w1) / 2.0, float(h1) / 2.0)
            painter.rotate(float(ang))
            painter.translate(-float(w0) / 2.0, -float(h0) / 2.0)
        except Exception:
            pass
        if sha > 0 and (int(sdx) != 0 or int(sdy) != 0) and sh_style != "mirror":
            if sh_style in ("trail", "beam"):
                dist = int(max(abs(int(sdx)), abs(int(sdy))))
                steps = int(max(10, min(22, dist * 3)))
                tail_k = 0.8
                shadow_img = QImage(int(math.ceil(w1)), int(math.ceil(h1)), QImage.Format.Format_ARGB32)
                shadow_img.fill(QColor(0, 0, 0, 0))
                shadow_p = QPainter(shadow_img)
                try:
                    try:
                        shadow_p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                        shadow_p.setRenderHint(QPainter.RenderHint.HighQualityAntialiasing, True)
                        shadow_p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                        shadow_p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                    except Exception:
                        pass
                    try:
                        shadow_p.setFont(font)
                    except Exception:
                        pass
                    try:
                        shadow_p.translate(float(w1) / 2.0, float(h1) / 2.0)
                        shadow_p.rotate(float(ang))
                        shadow_p.translate(-float(w0) / 2.0, -float(h0) / 2.0)
                    except Exception:
                        pass
                    for i in range(0, int(steps)):
                        f = 1.0 + (float(i) / float(max(1, steps - 1))) * float(tail_k)
                        a2 = int(max(0, min(255, round(float(sha) * (1.0 - float(i) / float(max(1, steps - 1)))))))
                        if a2 <= 0:
                            continue
                        ox = int(round(float(sdx) * f)) * ss
                        oy = int(round(float(sdy) * f)) * ss
                        try:
                            shadow_p.setPen(QPen(QColor(int(shr), int(shg), int(shb), int(a2))))
                        except Exception:
                            shadow_p.setPen(QColor(int(shr), int(shg), int(shb), int(a2)))
                        _fill_text_at(shadow_p, float(ox), float(oy), QColor(int(shr), int(shg), int(shb), int(a2)))
                finally:
                    try:
                        shadow_p.end()
                    except Exception:
                        pass
                try:
                    ptr2 = shadow_img.bits()
                    ptr2.setsize(shadow_img.sizeInBytes())
                    arr2 = np.frombuffer(ptr2, dtype=np.uint8).reshape((int(shadow_img.height()), int(shadow_img.width()), 4))
                    alpha2 = arr2[:, :, 3].astype(np.float32)
                    # 提高模糊半径，让“模糊度”到 100 时阴影能“糊成一团”
                    sigma = float(max(0.0, float(srng) / 100.0 * 40.0))
                    if sigma > 1e-6:
                        alpha2 = cv2.GaussianBlur(alpha2, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_CONSTANT)
                    try:
                        # 防止模糊把边缘“糊出一圈整块透明度”，导致出现看不见的方形遮挡
                        alpha2 = np.where(alpha2 < 1.0, 0.0, alpha2)
                    except Exception:
                        pass
                    arr2[:, :, 3] = np.clip(alpha2, 0.0, 255.0).astype(np.uint8)
                    blur_img = QImage(arr2.data, int(shadow_img.width()), int(shadow_img.height()), int(arr2.strides[0]), QImage.Format.Format_ARGB32)
                    painter.save()
                    painter.resetTransform()
                    painter.drawImage(0, 0, blur_img.copy())
                    painter.restore()
                except Exception:
                    pass
            elif sh_style == "stack":
                vx = 0 if int(sdx) == 0 else (1 if int(sdx) > 0 else -1)
                vy = 0 if int(sdy) == 0 else (1 if int(sdy) > 0 else -1)
                if vx == 0 and vy == 0:
                    vx, vy = 1, 1
                step_px = int(max(0, int(sstep))) * ss
                for i in range(int(scount), 0, -1):
                    # 叠字阴影：最上层应该偏移更小、更“贴近”文字，所以让更小偏移的层更不透明
                    k = float(int(scount) - int(i) + 1) / float(max(1, scount))
                    a2 = int(max(0, min(255, round(float(sha) * k))))
                    if a2 <= 0:
                        continue
                    ox = int(vx) * int(step_px) * int(i)
                    oy = int(vy) * int(step_px) * int(i)
                    _fill_text_at(painter, float(ox), float(oy), QColor(int(shr), int(shg), int(shb), int(a2)))
            else:
                _fill_text_at(painter, float(int(sdx) * ss), float(int(sdy) * ss), QColor(int(shr), int(shg), int(shb), int(sha)))
        if sw > 0 and sa > 0:
            try:
                pen = QPen(QColor(int(sr), int(sg), int(sb), int(sa)))
                pen.setWidthF(float(max(1.0, float(int(sw) * int(ss)))))
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            except Exception:
                pen = QPen(QColor(int(sr), int(sg), int(sb), int(sa)))
            _stroke_text_at(painter, 0.0, 0.0, pen)
        _fill_text_at(painter, 0.0, 0.0, QColor(int(r), int(g), int(b), int(a)))
    finally:
        try:
            painter.end()
        except Exception:
            pass
    if ss > 1:
        try:
            out_w = int(max(1, round(float(img.width()) / float(ss))))
            out_h = int(max(1, round(float(img.height()) / float(ss))))
            img = img.scaled(out_w, out_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((int(img.height()), int(img.width()), 4))
    out = arr.copy()
    if sh_style == "mirror" and sha > 0 and (int(sdx) != 0 or int(sdy) != 0):
<<<<<<< HEAD
        out = _apply_mirror_shadow_bgra(
            out,
            direction=(int(sdx), int(sdy)),
            gap_px=int(mgap),
            rgba=[int(shr), int(shg), int(shb), int(sha)],
            blur=int(srng),
            angle_deg=mirror_angle_deg,
        )
=======
        out = _apply_mirror_shadow_bgra(out, direction=(int(sdx), int(sdy)), gap_px=int(mgap), rgba=[int(shr), int(shg), int(shb), int(sha)], blur=int(srng))
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    return out

def _render_text_patch_to_bgra_safe(
    text: str,
    font_family: str,
    font_px: int,
    *,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    rgba: list[int] | None = None,
    angle_deg: float = 0.0,
    supersample: int = 2,
    stroke_width: int = 0,
    stroke_rgba: list[int] | None = None,
    shadow_offset: tuple[int, int] | None = None,
    shadow_rgba: list[int] | None = None,
    shadow_range: int | None = None,
    shadow_style: str | None = None,
    mirror_gap_px: int | None = None,
<<<<<<< HEAD
    mirror_angle_deg: float | None = None,
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    stack_count: int | None = None,
    stack_step_px: int | None = None,
) -> np.ndarray | None:
    try:
        app = QApplication.instance()
        if app is not None and QThread.currentThread() == app.thread():
            return None
    except Exception:
        return None
    return _render_text_patch_to_bgra(
        text,
        font_family,
        font_px,
        bold=bold,
        italic=italic,
        underline=underline,
        rgba=rgba,
        angle_deg=angle_deg,
        supersample=supersample,
        stroke_width=stroke_width,
        stroke_rgba=stroke_rgba,
        shadow_offset=shadow_offset,
        shadow_rgba=shadow_rgba,
        shadow_range=shadow_range,
        shadow_style=shadow_style,
        mirror_gap_px=mirror_gap_px,
<<<<<<< HEAD
        mirror_angle_deg=mirror_angle_deg,
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        stack_count=stack_count,
        stack_step_px=stack_step_px,
    )

def _rotate_bgra_keep_bounds(img_bgra: np.ndarray, angle_deg: float) -> np.ndarray:
    """
    旋转 BGRA 图像并扩大画布，避免旋转后被裁剪。
    
    说明：
    - 预览（QGraphicsItem）旋转不会裁剪内容，但 cv2.warpAffine 若输出尺寸不变会裁掉四角。
    - 这里按旋转后的外接矩形计算新尺寸，并平移仿射矩阵，让内容完整保留。
    """
    if img_bgra is None or not isinstance(img_bgra, np.ndarray):
        return img_bgra
    h, w = img_bgra.shape[:2]
    if h <= 0 or w <= 0:
        return img_bgra
    try:
        ang = float(angle_deg or 0.0)
    except Exception:
        ang = 0.0
    if abs(ang) <= 0.1:
        return img_bgra
    center = (float(w) / 2.0, float(h) / 2.0)
    M = cv2.getRotationMatrix2D(center, float(ang), 1.0)
    cos = abs(float(M[0, 0]))
    sin = abs(float(M[0, 1]))
    new_w = int(round(float(h) * sin + float(w) * cos))
    new_h = int(round(float(h) * cos + float(w) * sin))
    new_w = int(max(1, new_w))
    new_h = int(max(1, new_h))
    M[0, 2] += float(new_w) / 2.0 - float(w) / 2.0
    M[1, 2] += float(new_h) / 2.0 - float(h) / 2.0
    interp = cv2.INTER_CUBIC
    try:
        if hasattr(cv2, "INTER_LANCZOS4"):
            interp = cv2.INTER_LANCZOS4
    except Exception:
        pass
    return cv2.warpAffine(img_bgra, M, (int(new_w), int(new_h)), flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _ensure_svg_raster_cache(svg_path: str, max_edge: int = 2048) -> str:
    p = str(svg_path or "")
    if not p:
        return ""
    try:
        if not os.path.exists(p):
            return ""
    except Exception:
        return ""
    try:
        st = os.stat(p)
        sig = f"{os.path.normcase(os.path.abspath(p))}|{int(st.st_mtime)}|{int(st.st_size)}"
    except Exception:
        sig = f"{os.path.normcase(os.path.abspath(p))}"
    try:
        key = hashlib.sha1(sig.encode("utf-8", errors="ignore")).hexdigest()
    except Exception:
        key = str(abs(hash(sig)))
    try:
        cache_dir = str(PathManager.instance().get_user_data_path() / "watermark" / "svg_cache")
    except Exception:
        cache_dir = os.path.join(os.getcwd(), "data", "watermark", "svg_cache")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        return ""
    out_path = os.path.join(cache_dir, f"{key}.png")
    try:
        if os.path.exists(out_path):
            return out_path
    except Exception:
        pass
    try:
        from PyQt6.QtGui import QPainter
        renderer = QSvgRenderer(p)
        if not renderer.isValid():
            return ""
        ds = renderer.defaultSize()
        w0 = int(getattr(ds, "width", lambda: 0)())
        h0 = int(getattr(ds, "height", lambda: 0)())
        if w0 <= 0 or h0 <= 0:
            w0, h0 = 1024, 1024
        long_edge = max(w0, h0)
        try:
            max_edge = int(max(256, min(4096, int(max_edge))))
        except Exception:
            max_edge = 2048
        if long_edge > max_edge:
            scale = float(max_edge) / float(long_edge)
        else:
            scale = 1.0
        w = int(max(1, round(float(w0) * scale)))
        h = int(max(1, round(float(h0) * scale)))
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        painter = QPainter(img)
        try:
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setRenderHint(QPainter.RenderHint.HighQualityAntialiasing, True)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            except Exception:
                pass
            renderer.render(painter)
        finally:
            painter.end()
        try:
            if not img.save(out_path, "PNG"):
                return ""
        except Exception:
            return ""
        return out_path
    except Exception:
        return ""


def _first_non_empty(*values) -> str:
    for v in values:
        try:
            s = str(v or "").strip()
        except Exception:
            s = ""
        if s:
            return s
    return ""

def _meta_first(meta: dict, *keys) -> str:
    if not isinstance(meta, dict):
        meta = {}
    prefixes = ["", "EXIF:", "EXIF ", "XMP:", "XMP ", "Composite:", "Composite ", "File:", "File ", "QuickTime:", "QuickTime ", "MakerNotes:", "MakerNotes ", "MakerNote ", "IPTC:", "IPTC ", "Image ", "GPS ", "GPS:"]
    for k in keys:
        base = str(k or "").strip()
        if not base:
            continue
        for p in prefixes:
            try:
                v = meta.get(f"{p}{base}")
            except Exception:
                v = None
            s = _first_non_empty(v)
            if s:
                return s
    return ""


def _format_latlng(meta: dict) -> str:
    if not isinstance(meta, dict):
        return ""
    lat = _meta_first(meta, "GPSLatitude", "GPS Latitude")
    lng = _meta_first(meta, "GPSLongitude", "GPS Longitude")
    lat_ref = _meta_first(meta, "GPSLatitudeRef", "GPS LatitudeRef")
    lng_ref = _meta_first(meta, "GPSLongitudeRef", "GPS LongitudeRef")
    try:
        lat_f = float(str(lat).strip())
        if str(lat_ref).strip().upper() == "S":
            lat_f = -abs(lat_f)
        lat = f"{lat_f:.6f}".rstrip("0").rstrip(".")
    except Exception:
        pass
    try:
        lng_f = float(str(lng).strip())
        if str(lng_ref).strip().upper() == "W":
            lng_f = -abs(lng_f)
        lng = f"{lng_f:.6f}".rstrip("0").rstrip(".")
    except Exception:
        pass
    if not lat and not lng:
        return ""
    if lat and lng:
        return f"{lat}, {lng}"
    return lat or lng


def _resolve_tag_text(meta: dict, tag_key: str) -> str:
    if not isinstance(meta, dict):
        meta = {}
    key = str(tag_key or "").strip()
    if not key:
        return ""
    if key == "shoot_time":
        v = _meta_first(meta, "DateTimeOriginal", "CreateDate", "MediaCreateDate", "SubSecDateTimeOriginal", "DateTimeDigitized", "FileModifyDate")
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 拍摄时间为空: {key}")
            except Exception:
                pass
        return v
    if key == "iso":
        v = _meta_first(meta, "ISO", "ISOSpeedRatings", "PhotographicSensitivity")
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] ISO为空: {key}")
            except Exception:
                pass
        return v
    if key == "shutter":
        v = _meta_first(meta, "ExposureTime", "ShutterSpeed", "ShutterSpeedValue")
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 快门为空: {key}")
            except Exception:
                pass
        return v
    if key == "aperture":
        v = _meta_first(meta, "FNumber", "Aperture", "ApertureValue", "MaxApertureValue")
        v2 = _format_aperture(v)
        if v2:
            return v2
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 光圈为空: {key}")
            except Exception:
                pass
        return v
    if key == "focal_length":
        v = _meta_first(meta, "FocalLength")
        v2 = _format_focal_length(v)
        if v2:
            return v2
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 焦距为空: {key}")
            except Exception:
                pass
        return v
    if key == "distance":
        v = _meta_first(meta, "FocusDistance", "FocusDistanceUpper", "FocusDistanceLower")
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 对焦距离为空: {key}")
            except Exception:
                pass
        return v
    if key == "camera":
        v = _meta_first(meta, "Model")
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 机身型号为空: {key}")
            except Exception:
                pass
        return v
    if key == "lens":
        v = _meta_first(meta, "LensModel")
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 镜头型号为空: {key}")
            except Exception:
                pass
        return v
    if key == "location":
        v = _first_non_empty(
            meta.get("XMP-bmp:Location"),
            meta.get(str(EXIF_TAG.Location.value)),
            _meta_first(meta, "Location"),
            meta.get("XMP:Location"),
        )
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 位置为空: {key}")
            except Exception:
                pass
        return v
    if key == "latlng":
        v = _format_latlng(meta)
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 经纬度为空: {key}")
            except Exception:
                pass
        return v
    if key == "species":
        v = _first_non_empty(meta.get(str(EXIF_TAG.SpeciesCls.value)), meta.get(str(EXIF_TAG.Object.value)), _meta_first(meta, "Species"))
        if not v:
            try:
                LogManager.instance().debug(f"[Watermark] 物种为空: {key}")
            except Exception:
                pass
        return v
    if key == "order":
        v = _first_non_empty(meta.get(str(EXIF_TAG.OrderCls.value)), _meta_first(meta, "OrderCls"), _meta_first(meta, "Order"))
        return v
    if key == "family":
        v = _first_non_empty(meta.get(str(EXIF_TAG.FamilyCls.value)), _meta_first(meta, "FamilyCls"), _meta_first(meta, "Family"))
        return v
    if key == "genus":
        v = _first_non_empty(meta.get(str(EXIF_TAG.GenusCls.value)), _meta_first(meta, "GenusCls"), _meta_first(meta, "Genus"))
        return v
    return ""


def _resolve_text_with_tags(meta: dict, text: str, label_to_key: dict, key_set: set, key_to_label: dict, fallback_tag_key: str = "") -> str:
    if not isinstance(meta, dict):
        meta = {}
    base_text = str(text or "")
    if not base_text and fallback_tag_key:
        label = str(key_to_label.get(fallback_tag_key, fallback_tag_key))
        base_text = f"{{{label}}}"
    if not base_text:
        return ""
    pattern = re.compile(r"\{([^{}]+)\}")
    def _replace(match):
        key = str(match.group(1) or "").strip()
        if not key:
            return ""
        tag_key = str(label_to_key.get(key, key))
        if tag_key not in key_set:
            return ""
        resolved = _resolve_tag_text(meta, tag_key)
        if not str(resolved or "").strip():
            return ""
        return resolved
    out = pattern.sub(_replace, base_text)
    if "{" in base_text and "}" in base_text:
        try:
            if not str(out).strip():
                LogManager.instance().debug(f"[Watermark] 标签解析结果为空: {base_text}")
            elif out == base_text:
                LogManager.instance().debug(f"[Watermark] 标签未替换: {base_text}")
        except Exception:
            pass
    return out


def _parse_fraction_or_float(value: str) -> float | None:
    """
    将 EXIF 中常见的“分数/小数/带单位”的数值解析为 float。

    说明：
    - exiftool/exifread 可能返回 "63/10"、"6.3"、"f/6.3"、"600 mm" 等格式
    - 这里做一个尽量宽松的解析，解析失败则返回 None

    参数：
    - value: 待解析的字符串

    返回：
    - 解析出的浮点数，或 None
    """
    s = str(value or "").strip()
    if not s:
        return None
    s = s.lower().replace("f/", "").replace("f", "")
    s = s.replace("mm", "").replace(" ", "")
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            num = float(a)
            den = float(b)
            if abs(den) < 1e-9:
                return None
            return num / den
        return float(s)
    except Exception:
        return None


def _format_aperture(value: str) -> str:
    """
    将光圈字段格式化为 f6.3 形式。

    参数：
    - value: 原始光圈字符串（可能为分数/小数/带 f 前缀）

    返回：
    - 格式化后的光圈字符串，无法解析时返回空字符串
    """
    v = _parse_fraction_or_float(value)
    if v is None:
        return ""
    try:
        if v <= 0:
            return ""
    except Exception:
        return ""
    if abs(v - round(v)) < 1e-6:
        return f"f{int(round(v))}"
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return f"f{s}"


def _format_focal_length(value: str) -> str:
    """
    将焦距字段格式化为 600mm 形式。

    参数：
    - value: 原始焦距字符串（可能为分数/小数/带 mm 单位）

    返回：
    - 格式化后的焦距字符串，无法解析时返回空字符串
    """
    v = _parse_fraction_or_float(value)
    if v is None:
        return ""
    try:
        if v <= 0:
            return ""
    except Exception:
        return ""
    if abs(v - round(v)) < 1e-6:
        return f"{int(round(v))}mm"
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{s}mm"


def _calc_text_font_size(base_size: int, text: str) -> int:
    try:
        base = int(base_size or 24)
    except Exception:
        base = 24
    t = str(text or "")
    if not t:
        return max(10, base)
    length = len(t)
    ref_len = 8
    if length <= ref_len:
        return max(10, base)
    scale = (float(ref_len) / float(max(1, length))) ** 0.5
    size = int(round(float(base) * float(scale)))
    return max(10, min(base, size))


def _get_tags_multi_merged(file_paths: list[str], tags: list[str], timeout: int = 20) -> dict:
    paths = [str(p) for p in (file_paths or []) if p]
    if not paths:
        return {}
    try:
        worker = ExifHandleWorker.get_instance()
    except Exception:
        return {p: {} for p in paths}
    try:
        file_map = worker.get_tags_multi(paths, tags, timeout=int(timeout), force_mode="file")
    except Exception:
        file_map = {}
    try:
        xmp_map = worker.get_tags_multi(paths, tags, timeout=int(timeout), force_mode="xmp")
    except Exception:
        xmp_map = {}
    out = {}
    for p in paths:
        merged = {}
        try:
            fm = file_map.get(p, {}) if isinstance(file_map, dict) else {}
            xm = xmp_map.get(p, {}) if isinstance(xmp_map, dict) else {}
        except Exception:
            fm, xm = {}, {}
        if isinstance(fm, dict):
            merged.update(fm)
        if isinstance(xm, dict):
            for k, v in xm.items():
                try:
                    cur = merged.get(k)
                except Exception:
                    cur = None
                if _first_non_empty(cur):
                    continue
                if not _first_non_empty(v):
                    continue
                try:
                    merged[k] = v
                except Exception:
                    pass
        out[p] = merged
    return out


def _fill_meta_from_db(file_path: str, meta: dict) -> dict:
    try:
        p = str(file_path or "")
    except Exception:
        p = ""
    if not p:
        return meta if isinstance(meta, dict) else {}
    out = meta if isinstance(meta, dict) else {}
    try:
        db = BirdLibraryDB()
    except Exception:
        return out
    record = None
    try:
        uuid_key = str(EXIF_TAG.Uuid.value)
        uuid_val = _first_non_empty(out.get(uuid_key), _meta_first(out, uuid_key), _meta_first(out, "Uuid"))
        if uuid_val:
            record = db.get_result_by_uuid(str(uuid_val).strip(), table_name="bird_results")
            if not record:
                record = db.get_result_by_uuid(str(uuid_val).strip(), table_name="import_cache")
    except Exception:
        record = None
    if not record:
        try:
            record = db.get_result_by_path(p, table_name="bird_results")
            if not record:
                record = db.get_result_by_path(p, table_name="import_cache")
        except Exception:
            record = None
    if not record:
        return out
    try:
        loc = record.get("location")
        if loc is not None and str(loc).strip():
            v = str(loc).strip()
            out[str(EXIF_TAG.Location.value)] = v
            out["XMP-bmp:Location"] = v
            out["Xmp-bmp:Location"] = v
    except Exception:
        pass
    try:
        lat = record.get("latitude")
        lng = record.get("longitude")
        if lat is not None and str(lat).strip():
            try:
                lat_f = float(str(lat).strip())
                out["GPSLatitude"] = float(lat_f)
                out["GPSLatitudeRef"] = "S" if lat_f < 0 else "N"
            except Exception:
                pass
        if lng is not None and str(lng).strip():
            try:
                lng_f = float(str(lng).strip())
                out["GPSLongitude"] = float(lng_f)
                out["GPSLongitudeRef"] = "W" if lng_f < 0 else "E"
            except Exception:
                pass
    except Exception:
        pass
    try:
        obj = record.get("object")
        if obj is not None and str(obj).strip():
            out[str(EXIF_TAG.Object.value)] = str(obj).strip()
    except Exception:
        pass
    try:
        o = record.get("order_cls")
        if o is not None and str(o).strip():
            out[str(EXIF_TAG.OrderCls.value)] = str(o).strip()
    except Exception:
        pass
    try:
        f = record.get("family_cls")
        if f is not None and str(f).strip():
            out[str(EXIF_TAG.FamilyCls.value)] = str(f).strip()
    except Exception:
        pass
    try:
        g = record.get("genus_cls")
        if g is not None and str(g).strip():
            out[str(EXIF_TAG.GenusCls.value)] = str(g).strip()
    except Exception:
        pass
    try:
        s = record.get("species_cls")
        if s is not None and str(s).strip():
            out[str(EXIF_TAG.SpeciesCls.value)] = str(s).strip()
    except Exception:
        pass
    try:
        t = record.get("tags")
        if t is not None and str(t).strip():
            out[str(EXIF_TAG.Tags.value)] = str(t).strip()
    except Exception:
        pass
    return out


WATERMARK_TAG_READ_LIST = [
    "DateTimeOriginal",
    "CreateDate",
    "MediaCreateDate",
    "SubSecDateTimeOriginal",
    "DateTimeDigitized",
    "FileModifyDate",
    "ISO",
    "ISOSpeedRatings",
    "PhotographicSensitivity",
    "ExposureTime",
    "ShutterSpeed",
    "ShutterSpeedValue",
    "FNumber",
    "Aperture",
    "ApertureValue",
    "MaxApertureValue",
    "FocalLength",
    "FocusDistance",
    "FocusDistanceUpper",
    "FocusDistanceLower",
    "Model",
    "LensModel",
    str(EXIF_TAG.Location.value),
    "XMP-bmp:Location",
    str(EXIF_TAG.OrderCls.value),
    str(EXIF_TAG.FamilyCls.value),
    str(EXIF_TAG.GenusCls.value),
    str(EXIF_TAG.SpeciesCls.value),
    str(EXIF_TAG.Object.value),
    str(EXIF_TAG.Uuid.value),
    str(EXIF_TAG.Fastid.value),
    "GPSLatitude",
    "GPSLongitude",
    "GPSLatitudeRef",
    "GPSLongitudeRef",
]

WATERMARK_TAG_ITEMS = [
    ("拍摄时间", "shoot_time"),
    ("ISO", "iso"),
    ("快门", "shutter"),
    ("光圈", "aperture"),
    ("焦距", "focal_length"),
    ("距离", "distance"),
    ("拍摄相机", "camera"),
    ("拍摄镜头", "lens"),
    ("拍摄位置", "location"),
    ("经纬度", "latlng"),
    ("鸟目", "order"),
    ("鸟科", "family"),
    ("鸟属", "genus"),
    ("鸟种", "species"),
]
WATERMARK_TAG_LABEL_TO_KEY = {label: key for label, key in WATERMARK_TAG_ITEMS}
WATERMARK_TAG_KEY_TO_LABEL = {key: label for label, key in WATERMARK_TAG_ITEMS}
WATERMARK_TAG_KEY_SET = set(WATERMARK_TAG_KEY_TO_LABEL.keys())


class _ResizeHandle(QGraphicsRectItem):
    def __init__(self, corner: str, parent_item: QGraphicsItem):
        super().__init__(parent_item)
        self.corner = str(corner or "")
        self.setRect(0, 0, 10, 10)
        self.setBrush(QColor(255, 255, 255, 230))
        self.setPen(QColor(0, 0, 0, 80))
        self.setZValue(1000)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        cur = Qt.CursorShape.SizeAllCursor
        if self.corner in ("tl", "br"):
            cur = Qt.CursorShape.SizeFDiagCursor
        elif self.corner in ("tr", "bl"):
            cur = Qt.CursorShape.SizeBDiagCursor
        self.setCursor(QCursor(cur))
        self._dragging = False
        self._start_scene_pos = None

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        try:
            p = self.parentItem()
            if p is not None and hasattr(p, "state") and getattr(p.state, "kind", "text") == "text":
                event.ignore()
                return
        except Exception:
            pass
        self._dragging = True
        self._start_scene_pos = event.scenePos()
        try:
            p = self.parentItem()
            if p is not None and hasattr(p, "_on_handle_press"):
                p._on_handle_press(self.corner, event.scenePos())
        except Exception:
            pass
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if not self._dragging:
            event.ignore()
            return
        try:
            p = self.parentItem()
            if p is not None and hasattr(p, "_on_handle_drag"):
                p._on_handle_drag(self.corner, event.scenePos())
        except Exception:
            pass
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        self._dragging = False
        try:
            p = self.parentItem()
            if p is not None and hasattr(p, "_on_handle_release"):
                p._on_handle_release(self.corner, event.scenePos())
        except Exception:
            pass
        event.accept()


class _LockedSplitter(QSplitter):
    def createHandle(self):
        h = QSplitterHandle(self.orientation(), self)
        try:
            h.setEnabled(False)
            h.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            pass
        return h


class _IgnoreWheelFilter(QObject):
    def eventFilter(self, obj, event):
        try:
            if event is not None and event.type() == QEvent.Type.Wheel:
                return True
        except Exception:
            pass
        return super().eventFilter(obj, event)


class _WatermarkFontSelectDialog(BasePopupDialog):
    """
    水印字体选择弹窗。

    功能：
    - 允许用户将字体文件加入“已添加字体列表”
    - 选择某个字体后，底部测试文字“栖图”实时切换字体显示
    - 记忆：已添加字体文件列表、上次选择的字体文件、上次选择的目录
    - 打开时检查已添加字体文件是否仍存在，缺失则提示并自动移除
    """

    def __init__(self, parent=None, prefs_key: str = "watermark/prefs"):
        super().__init__(parent=parent, title="选择字体", size=(720, 560))
        self._prefs_key = str(prefs_key or "watermark/prefs")
        self.selected_font_family = ""
        self.selected_font_path = ""
        self._font_files: list[str] = []
        self._path_to_family: dict[str, str] = {}
        self._path_to_alias: dict[str, str] = {}
        self._build_ui()
        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()
        self._load_and_refresh()

    def _build_ui(self):
        header = QLabel("已添加字体")
        header.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.content_layout.addWidget(header)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        self.btn_add_font = QPushButton("添加字体")
        self.btn_add_font.clicked.connect(self._add_font_clicked)
        row_layout.addWidget(self.btn_add_font)
        self.btn_rename_font = QPushButton("重命名")
        self.btn_rename_font.clicked.connect(self._rename_current_font)
        row_layout.addWidget(self.btn_rename_font)
        self.btn_delete_font = QPushButton("删除字体")
        self.btn_delete_font.clicked.connect(self._delete_current_font)
        row_layout.addWidget(self.btn_delete_font)
        row_layout.addStretch(1)
        self.content_layout.addWidget(row)

        self.list_fonts = QListWidget()
        self.list_fonts.currentItemChanged.connect(self._on_current_changed)
        self.content_layout.addWidget(self.list_fonts, 1)

        test_title = QLabel("测试文字")
        test_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.content_layout.addWidget(test_title)

        self.lbl_preview = QLabel("栖图")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            self.lbl_preview.setMinimumHeight(72)
        except Exception:
            pass
        self.lbl_preview.setStyleSheet("font-size: 44px; font-weight: 600;")
        self.content_layout.addWidget(self.lbl_preview)

        self.btn_cancel = QPushButton("取消")
        self.btn_ok = QPushButton("确定")
        try:
            self.btn_add_font.setFixedSize(92, 36)
            self.btn_rename_font.setFixedSize(92, 36)
            self.btn_delete_font.setFixedSize(92, 36)
            self.btn_cancel.setFixedSize(92, 36)
            self.btn_ok.setFixedSize(92, 36)
        except Exception:
            pass
        self.apply_dialog_button_style(self.btn_add_font, "secondary")
        self.apply_dialog_button_style(self.btn_rename_font, "secondary")
        self.apply_dialog_button_style(self.btn_delete_font, "secondary")
        self.apply_dialog_button_style(self.btn_cancel, "secondary")
        self.apply_dialog_button_style(self.btn_ok, "primary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._accept_current)
        self.bottom_layout.addWidget(self.btn_cancel)
        self.bottom_layout.addWidget(self.btn_ok)

    def _read_prefs(self) -> dict:
        sm = SettingsManager.instance()
        try:
            raw = sm.get(self._prefs_key, "") or ""
        except Exception:
            raw = ""
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def _write_prefs(self, d: dict):
        sm = SettingsManager.instance()
        try:
            sm.set(self._prefs_key, json.dumps(d or {}, ensure_ascii=False))
            sm.sync_to_config(self._prefs_key)
        except Exception:
            pass

    def _load_and_refresh(self):
        d = self._read_prefs()
        raw_files = d.get("font_files")
        if not isinstance(raw_files, list) or not raw_files:
            raw_files = d.get("recent_fonts") or []
        raw_alias = d.get("font_aliases")
        if not isinstance(raw_alias, dict):
            raw_alias = {}
        files = []
        for x in (raw_files or []):
            try:
                p = str(x or "").strip()
            except Exception:
                p = ""
            if not p:
                continue
            if p not in files:
                files.append(p)

        missing = []
        kept = []
        path_to_family = {}
        kept_alias = {}
        for p in files:
            try:
                if not os.path.exists(p):
                    missing.append(p)
                    continue
            except Exception:
                missing.append(p)
                continue
            fid = -1
            try:
                fid = QFontDatabase.addApplicationFont(p)
            except Exception:
                fid = -1
            families = []
            try:
                families = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
            except Exception:
                families = []
            if not families:
                missing.append(p)
                continue
            kept.append(p)
            path_to_family[p] = str(families[0])
            try:
                alias = str(raw_alias.get(p) or "").strip()
            except Exception:
                alias = ""
            if alias:
                kept_alias[p] = alias

        if missing:
            # 缺失字体文件：提示并从记忆里自动移除
            try:
                if len(missing) == 1:
                    NotificationManager.instance().show_toast(f"字体文件不存在，已移除：{os.path.basename(missing[0])}", 2600, parent=self, position="top")
                else:
                    NotificationManager.instance().show_toast(f"已移除 {len(missing)} 个不存在的字体文件", 2600, parent=self, position="top")
            except Exception:
                pass

        d["font_files"] = kept
        d["font_aliases"] = kept_alias
        last_file = ""
        try:
            last_file = str(d.get("last_font_file") or "").strip()
        except Exception:
            last_file = ""
        if last_file and last_file not in kept:
            d["last_font_file"] = ""
        self._write_prefs(d)

        self._font_files = kept
        self._path_to_family = path_to_family
        self._path_to_alias = kept_alias
        self._rebuild_list(d.get("last_font_file") or "")

    def _rebuild_list(self, last_path: str):
        self.list_fonts.blockSignals(True)
        try:
            self.list_fonts.clear()
        except Exception:
            pass
        for p in (self._font_files or []):
            fam = str(self._path_to_family.get(p, "") or "")
            alias = ""
            try:
                alias = str(self._path_to_alias.get(p, "") or "").strip()
            except Exception:
                alias = ""
            show_name = alias if alias else fam
            title = f"{show_name}  ({os.path.basename(p)})" if show_name else os.path.basename(p)
            it = QListWidgetItem(title)
            it.setData(Qt.ItemDataRole.UserRole, str(p))
            self.list_fonts.addItem(it)
        self.list_fonts.blockSignals(False)

        target = str(last_path or "").strip()
        if not target and self._font_files:
            target = str(self._font_files[0])
        if target:
            for i in range(self.list_fonts.count()):
                it = self.list_fonts.item(i)
                if str(it.data(Qt.ItemDataRole.UserRole) or "") == target:
                    try:
                        self.list_fonts.setCurrentRow(i)
                    except Exception:
                        pass
                    break

    def _current_path(self) -> str:
        it = None
        try:
            it = self.list_fonts.currentItem()
        except Exception:
            it = None
        try:
            return str(it.data(Qt.ItemDataRole.UserRole) or "") if it is not None else ""
        except Exception:
            return ""

    def _on_current_changed(self, cur: QListWidgetItem, _prev: QListWidgetItem):
        p = self._current_path()
        fam = str(self._path_to_family.get(p, "") or "")
        if fam:
            try:
                f = QFont(str(fam))
                f.setPixelSize(48)
                self.lbl_preview.setFont(f)
            except Exception:
                pass

    def _add_font_clicked(self):
        d = self._read_prefs()
        init_dir = ""
        try:
            init_dir = str(d.get("last_font_dir") or "")
        except Exception:
            init_dir = ""
        if not init_dir:
            try:
                last_file = str(d.get("last_font_file") or "").strip()
            except Exception:
                last_file = ""
            if last_file:
                try:
                    init_dir = os.path.dirname(last_file)
                except Exception:
                    init_dir = ""
        p, _ = QFileDialog.getOpenFileName(self, "添加字体文件", init_dir, "字体文件 (*.ttf *.otf)")
        if not p:
            return
        fid = -1
        try:
            fid = QFontDatabase.addApplicationFont(p)
        except Exception:
            fid = -1
        families = []
        try:
            families = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
        except Exception:
            families = []
        if not families:
            NotificationManager.instance().show_warning("错误", "加载字体失败")
            return
        fam = str(families[0])

        files = list(self._font_files or [])
        if p not in files:
            files.append(str(p))
        self._font_files = files
        self._path_to_family[str(p)] = fam

        # 添加字体后立刻允许用户重命名：避免字体家族名不直观（同族多字重名、英文名等）
        # 这里把“重命名”作为显示别名保存，不改变字体文件本身，也不影响实际渲染使用的 family
        alias = ""
        try:
            from ui.widgets.custom_input_dialog import CustomInputDialog
            alias, ok = CustomInputDialog.getText(self, "字体重命名", "字体名称：", str(fam), "可输入更易识别的名称")
            if not ok:
                alias = ""
        except Exception:
            alias = ""
        alias = str(alias or "").strip()
        if alias:
            self._path_to_alias[str(p)] = str(alias)

        d["font_files"] = list(self._font_files)
        try:
            d["last_font_dir"] = str(os.path.dirname(p) or "")
        except Exception:
            d["last_font_dir"] = ""
        try:
            d["last_font_file"] = str(p)
        except Exception:
            d["last_font_file"] = ""
        try:
            d["font_aliases"] = dict(self._path_to_alias or {})
        except Exception:
            d["font_aliases"] = {}
        self._write_prefs(d)

        self._rebuild_list(str(p))

    def _delete_current_font(self):
        """
        删除当前选中的字体记录（仅移除“记忆列表”，不删除磁盘文件）。

        参数说明：
        - 无（从列表当前选中项读取字体路径）
        """
        p = self._current_path()
        if not p:
            NotificationManager.instance().show_warning("提示", "请先选择一个字体")
            return
        files = list(self._font_files or [])
        if p in files:
            files.remove(p)
        self._font_files = files
        try:
            self._path_to_family.pop(p, None)
        except Exception:
            pass
        try:
            self._path_to_alias.pop(p, None)
        except Exception:
            pass
        d = self._read_prefs()
        d["font_files"] = list(self._font_files)
        try:
            d["font_aliases"] = dict(self._path_to_alias or {})
        except Exception:
            d["font_aliases"] = {}
        try:
            if str(d.get("last_font_file") or "") == str(p):
                d["last_font_file"] = ""
        except Exception:
            pass
        self._write_prefs(d)
        self._rebuild_list(str(d.get("last_font_file") or ""))

    def _rename_current_font(self):
        """
        重命名当前选中的字体（保存为显示别名）。

        参数说明：
        - 无（从列表当前选中项读取字体路径）
        """
        p = self._current_path()
        if not p:
            NotificationManager.instance().show_warning("提示", "请先选择一个字体")
            return
        fam = str(self._path_to_family.get(p, "") or "")
        if not fam:
            NotificationManager.instance().show_warning("提示", "所选字体不可用")
            return
        cur_alias = ""
        try:
            cur_alias = str(self._path_to_alias.get(p, "") or "").strip()
        except Exception:
            cur_alias = ""
        init_name = cur_alias if cur_alias else fam
        new_name = ""
        try:
            from ui.widgets.custom_input_dialog import CustomInputDialog
            new_name, ok = CustomInputDialog.getText(self, "字体重命名", "字体名称：", str(init_name), "可输入更易识别的名称")
            if not ok:
                return
        except Exception:
            return
        new_name = str(new_name or "").strip()
        if not new_name or new_name == fam:
            # 名称为空或等于字体家族名：等价于“取消别名”，回退为默认显示
            try:
                self._path_to_alias.pop(p, None)
            except Exception:
                pass
        else:
            self._path_to_alias[p] = str(new_name)
        d = self._read_prefs()
        try:
            d["font_aliases"] = dict(self._path_to_alias or {})
        except Exception:
            d["font_aliases"] = {}
        self._write_prefs(d)
        self._rebuild_list(str(d.get("last_font_file") or p))

    def _accept_current(self):
        p = self._current_path()
        if not p:
            NotificationManager.instance().show_warning("提示", "请先选择一个字体")
            return
        fam = str(self._path_to_family.get(p, "") or "")
        if not fam:
            NotificationManager.instance().show_warning("提示", "所选字体不可用")
            return
        self.selected_font_path = str(p)
        self.selected_font_family = str(fam)

        d = self._read_prefs()
        try:
            d["last_font_file"] = str(p)
            d["last_font_dir"] = str(os.path.dirname(p) or "")
        except Exception:
            pass
        if "font_files" not in d:
            d["font_files"] = list(self._font_files)
        self._write_prefs(d)
        self.accept()

    def apply_theme_styles(self):
        cm = ColorManager.instance()
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        text_color = cm.get("popup.text.primary", "#333333")
        light_bg = cm.get("theme.background.light", "#FFFFFF")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        primary_color = cm.get("theme.primary", "#2196F3")

        try:
            if self.container:
                self.container.setStyleSheet(
                    f"QWidget#container{{background-color:{light_bg}; border:1px solid {border_color}; border-radius:8px;}}"
                )
        except Exception:
            pass
        try:
            if self.content_widget:
                self.content_widget.setStyleSheet(
                    f"QWidget#contentWidget{{background-color:{light_bg};}} QLabel{{color:{text_color}; background:transparent;}}"
                )
        except Exception:
            pass
        try:
            self.set_title_bar_style(cm.get("popup.header.background", "#2c3e50"), cm.get("popup.header.text", "#FFFFFF"))
        except Exception:
            pass
        try:
            self.set_bottom_bar_style(self.get_footer_background(), border_color)
        except Exception:
            pass
        try:
            self.list_fonts.setStyleSheet(
                f"""
                QListWidget {{
                    border: 1px solid {border_color};
                    border-radius: 6px;
                    background-color: {light_bg};
                    color: {text_color};
                }}
                QListWidget::item {{
                    padding: 8px 10px;
                }}
                QListWidget::item:hover {{
                    background-color: {hover_bg};
                }}
                QListWidget::item:selected {{
                    background-color: {primary_color};
                    color: #FFFFFF;
                }}
                QScrollBar:vertical {{
                    background-color: transparent;
                    width: 10px;
                    margin: 2px 0 2px 0;
                }}
                QScrollBar::handle:vertical {{
                    background-color: {border_color};
                    min-height: 30px;
                    border-radius: 5px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background-color: {primary_color};
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                    background: transparent;
                }}
                """
            )
        except Exception:
            pass


class WatermarkPresetLoadDialog(BasePopupDialog):
    def __init__(self, parent=None, preset_dir: str = ""):
        super().__init__(parent=parent, title="加载水印方案", size=(720, 520))
        self._preset_dir = str(preset_dir or "")
        self.selected_path = None
        self._build_ui()
        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()
        self._reload_list()

    def _build_ui(self):
        header = QLabel("选择一个已保存的水印方案")
        header.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.content_layout.addWidget(header)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(lambda _cur, _prev: self._update_preview())
        body_layout.addWidget(self.list_widget, 1)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        try:
            self._preview_wheel_filter = _IgnoreWheelFilter()
            self.preview.installEventFilter(self._preview_wheel_filter)
        except Exception:
            pass
        body_layout.addWidget(self.preview, 1)

        self.content_layout.addWidget(body, 1)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_load = QPushButton("加载")
        self.btn_load.clicked.connect(self._accept_selected)
        try:
            self.btn_delete.setFixedSize(80, 32)
            self.btn_cancel.setFixedSize(80, 32)
            self.btn_load.setFixedSize(80, 32)
        except Exception:
            pass
        self.apply_dialog_button_style(self.btn_delete, "secondary")
        self.apply_dialog_button_style(self.btn_cancel, "secondary")
        self.apply_dialog_button_style(self.btn_load, "primary")
        self.bottom_layout.addWidget(self.btn_delete)
        self.bottom_layout.addWidget(self.btn_cancel)
        self.bottom_layout.addWidget(self.btn_load)

    def _reload_list(self):
        self.list_widget.clear()
        files = []
        try:
            if self._preset_dir and os.path.exists(self._preset_dir):
                files = [f for f in os.listdir(self._preset_dir) if str(f).lower().endswith(".bwm")]
        except Exception:
            files = []
        files.sort()
        for f in files:
            it = QListWidgetItem(str(f))
            it.setData(Qt.ItemDataRole.UserRole, os.path.join(self._preset_dir, str(f)))
            self.list_widget.addItem(it)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self._update_preview()

    def _selected_file_path(self) -> str:
        it = self.list_widget.currentItem()
        if it is None:
            return ""
        return str(it.data(Qt.ItemDataRole.UserRole) or "")

    def _load_preview_data(self, fp: str) -> list:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        states = (data or {}).get("states") or []
        return [x for x in (states or []) if isinstance(x, dict)]

    def _update_preview(self):
        fp = self._selected_file_path()
        try:
            self.btn_delete.setEnabled(bool(fp))
            self.btn_load.setEnabled(bool(fp))
        except Exception:
            pass
        if not fp or not os.path.exists(fp):
            self.preview.setPlainText("")
            return
        states = self._load_preview_data(fp)
        lines = []
        lines.append(os.path.basename(fp))
        lines.append("")
        lines.append(f"图层数量: {len(states)}")
        lines.append("")
        for i, s in enumerate(states, start=1):
            name = str((s or {}).get("name") or f"水印{i}")
            kind = str((s or {}).get("kind") or "text")
            visible = bool((s or {}).get("visible", True))
            k = "文字" if kind == "text" else "图片"
            v = "显示" if visible else "隐藏"
            lines.append(f"{i}. {name}  ({k}, {v})")
        self.preview.setPlainText("\n".join(lines))

    def _delete_selected(self):
        fp = self._selected_file_path()
        if not fp or not os.path.exists(fp):
            return
        name = os.path.basename(fp)
        if not NotificationManager.instance().ask_confirmation("确认删除", f"确认删除方案 '{name}'？"):
            return
        try:
            os.remove(fp)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"删除失败: {e}")
            return
        self._reload_list()

    def _accept_selected(self):
        fp = self._selected_file_path()
        if not fp or not os.path.exists(fp):
            return
        self.selected_path = fp
        self.accept()

    def apply_theme_styles(self):
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.light", "#FFFFFF")
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        border = cm.get("popup.border.primary", "#D0D0D0")
        text = cm.get("popup.text.primary", "#333333")
        hover_bg = cm.get("settings.shortcut_reset.hover_background", "#2196F31A")
        scrollbar_bg = cm.get("settings.shortcut_table.header.background", "#F5F5F5")
        scrollbar_handle = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        scrollbar_hover = cm.get("settings.shortcut_table.row.hover_border", "#D7E3F5")
        try:
            self.list_widget.setStyleSheet(
                f"QListWidget{{border:1px solid {border}; border-radius:6px; background:{panel_bg};}}"
                f"QListWidget::item{{padding:8px 10px; color:{text};}}"
                f"QListWidget::item:selected{{background:{hover_bg}; color:{text};}}"
                f"QScrollBar:vertical{{background:{scrollbar_bg}; width:10px;}}"
                f"QScrollBar::handle:vertical{{background:{scrollbar_handle}; min-height:30px;}}"
                f"QScrollBar::handle:vertical:hover{{background:{scrollbar_hover};}}"
            )
        except Exception:
            pass
        try:
            self.preview.setStyleSheet(
                f"QPlainTextEdit{{border:1px solid {border}; border-radius:6px; background:{control_bg}; color:{text}; padding:8px;}}"
                f"QScrollBar:vertical{{background:{scrollbar_bg}; width:10px;}}"
                f"QScrollBar::handle:vertical{{background:{scrollbar_handle}; min-height:30px;}}"
                f"QScrollBar::handle:vertical:hover{{background:{scrollbar_hover};}}"
            )
        except Exception:
            pass


class _WatermarkGraphicsItem(QGraphicsRectItem):
    def __init__(
        self,
        state: "WatermarkState",
        image_size: QSize,
        on_changed=None,
        on_selected=None,
        on_interaction=None,
        bg_qimg: QImage | None = None,
        render_requester=None,
    ):
        super().__init__()
        self.state = state
        self.image_w = int(max(1, image_size.width()))
        self.image_h = int(max(1, image_size.height()))
        self.on_changed = on_changed
        self.on_selected = on_selected
        self.on_interaction = on_interaction
        self._bg_qimg = bg_qimg if isinstance(bg_qimg, QImage) and not bg_qimg.isNull() else None
        self._render_requester = render_requester

        self.setZValue(10)
        self.setPen(QColor(255, 255, 255, 160))
        self.setBrush(QColor(0, 0, 0, 0))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setTransformOriginPoint(0, 0)
        try:
            # 拖动时主要是平移，为了避免每帧都重新栅格化复杂内容，开启设备坐标缓存
            self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        except Exception:
            pass

        self._content_text = None
        self._content_pix = None
        self._pix_source_path = ""
        self._pix_original = QPixmap()
        self._pix_scaled = QPixmap()
        self._pix_scaled_key = None
        self._pix_mirror = QPixmap()
        self._pix_mirror_key = None
        self._render_token = 0
        self._render_key = None
        self._img_render_token = 0
        self._img_render_key = None
        self._handles = {
            "tl": _ResizeHandle("tl", self),
            "tr": _ResizeHandle("tr", self),
            "bl": _ResizeHandle("bl", self),
            "br": _ResizeHandle("br", self),
        }
        self._handle_start_rect = None
        self._handle_start_scene = None
        self._handle_start_w_norm = None
        self._handle_start_center = None
        self._snap_threshold = 6.0
        self._guide_lines = {}
        self._interacting = False
        self._auto_color_last_ts = 0.0
        self._update_from_state()

    def _current_rect_wh(self) -> tuple[float, float]:
        r = self.rect()
        return float(max(1.0, r.width())), float(max(1.0, r.height()))

    def _clamp_pos(self, pos):
        x = float(pos.x())
        y = float(pos.y())
        w, h = self._current_rect_wh()
        try:
            ang = float(self.rotation() or 0.0)
        except Exception:
            ang = 0.0
        try:
            cx = float(w) / 2.0
            cy = float(h) / 2.0
            t = QTransform()
            t.translate(cx, cy)
            t.rotate(ang)
            t.translate(-cx, -cy)
            mapped = t.mapRect(QRectF(0.0, 0.0, float(w), float(h)))
            left = float(mapped.left())
            right = float(mapped.right())
            top = float(mapped.top())
            bottom = float(mapped.bottom())
            min_x = float(0.0 - right + 1.0)
            max_x = float(float(self.image_w) - left - 1.0)
            min_y = float(0.0 - bottom + 1.0)
            max_y = float(float(self.image_h) - top - 1.0)
            x = max(min_x, min(max_x, x))
            y = max(min_y, min(max_y, y))
            return type(pos)(x, y)
        except Exception:
            min_x = float(min(0.0, float(self.image_w) - float(w)))
            max_x = float(max(0.0, float(self.image_w) - float(w)))
            min_y = float(min(0.0, float(self.image_h) - float(h)))
            max_y = float(max(0.0, float(self.image_h) - float(h)))
            x = max(min_x, min(max_x, x))
            y = max(min_y, min(max_y, y))
            return type(pos)(x, y)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and value is not None:
            try:
                pos = self._clamp_pos(value)
                if bool(getattr(self, "_interacting", False)):
                    pos = self._apply_snap(pos)
                    try:
                        st = self.state
                        if (
                            st is not None
                            and str(getattr(st, "kind", "text") or "text") == "text"
                            and str(getattr(st, "color_mode", "custom") or "custom") == "auto"
                        ):
                            w, h = self._current_rect_wh()
                            cx = float(pos.x()) + float(w) / 2.0
                            cy = float(pos.y()) + float(h) / 2.0
                            st.x_norm = float(cx) / float(self.image_w)
                            st.y_norm = float(cy) / float(self.image_h)
                            now = float(time.monotonic())
                            last = float(getattr(self, "_auto_color_last_ts", 0.0) or 0.0)
                            if now - last >= 0.06:
                                self._auto_color_last_ts = float(now)
                                try:
                                    self._update_from_state(sync_geometry=False)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                return pos
            except Exception:
                return value
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            try:
                for h in self._handles.values():
                    h.setVisible(False)
            except Exception:
                pass
            if bool(value):
                try:
                    if callable(self.on_selected):
                        self.on_selected(str(self.state.wm_id))
                except Exception:
                    pass
        return super().itemChange(change, value)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        try:
            if callable(self.on_interaction):
                self.on_interaction(True)
        except Exception:
            pass
        self._interacting = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        self._sync_state_from_item()
        self._hide_guides()
        self._interacting = False
        try:
            if callable(self.on_interaction):
                self.on_interaction(False)
        except Exception:
            pass

    def _sync_state_from_item(self):
        try:
            w, h = self._current_rect_wh()
            x0 = float(self.pos().x())
            y0 = float(self.pos().y())
            cx = x0 + w / 2.0
            cy = y0 + h / 2.0
            self.state.x_norm = float(cx) / float(self.image_w)
            self.state.y_norm = float(cy) / float(self.image_h)
            self.state.w_norm = float(w) / float(self.image_w)
            self.state.h_norm = float(h) / float(self.image_h)
        except Exception:
            pass
        try:
            if callable(self.on_changed):
                self.on_changed()
        except Exception:
            pass

    def _update_handles(self):
        w, h = self._current_rect_wh()
        self._handles["tl"].setPos(-5, -5)
        self._handles["tr"].setPos(w - 5, -5)
        self._handles["bl"].setPos(-5, h - 5)
        self._handles["br"].setPos(w - 5, h - 5)

    def _ensure_guides(self):
        if self._guide_lines:
            return
        sc = self.scene()
        if sc is None:
            return
        cm = ColorManager.instance()
        color_hex = cm.get("theme.primary", "#2196F3")
        pen = QPen(QColor(color_hex))
        pen.setWidthF(1.2)
        for key in ("left", "center", "right", "top", "middle", "bottom"):
            line = QGraphicsLineItem()
            line.setPen(pen)
            line.setZValue(2000)
            line.setVisible(False)
            sc.addItem(line)
            self._guide_lines[key] = line

    def _hide_guides(self):
        if not self._guide_lines:
            return
        for line in self._guide_lines.values():
            try:
                line.setVisible(False)
            except Exception:
                pass

    def _apply_snap(self, pos):
        self._ensure_guides()
        if not self._guide_lines:
            return pos
        x = float(pos.x())
        y = float(pos.y())
        w, h = self._current_rect_wh()
        left = x
        center = x + w / 2.0
        right = x + w
        top = y
        middle = y + h / 2.0
        bottom = y + h
        x_targets = [0.0, float(self.image_w) / 2.0, float(self.image_w)]
        y_targets = [0.0, float(self.image_h) / 2.0, float(self.image_h)]
        sc = self.scene()
        if sc is not None:
            for it in sc.items():
                if it is self or not isinstance(it, _WatermarkGraphicsItem):
                    continue
                try:
                    ox = float(it.pos().x())
                    oy = float(it.pos().y())
                    ow, oh = it._current_rect_wh()
                except Exception:
                    continue
                x_targets.append(ox)
                x_targets.append(ox + ow / 2.0)
                x_targets.append(ox + ow)
                y_targets.append(oy)
                y_targets.append(oy + oh / 2.0)
                y_targets.append(oy + oh)
        best_dx = None
        best_x_target = None
        for t in x_targets:
            for cur in (left, center, right):
                dx = float(t) - float(cur)
                if abs(dx) <= self._snap_threshold:
                    if best_dx is None or abs(dx) < abs(best_dx):
                        best_dx = dx
                        best_x_target = float(t)
        best_dy = None
        best_y_target = None
        for t in y_targets:
            for cur in (top, middle, bottom):
                dy = float(t) - float(cur)
                if abs(dy) <= self._snap_threshold:
                    if best_dy is None or abs(dy) < abs(best_dy):
                        best_dy = dy
                        best_y_target = float(t)
        for line in self._guide_lines.values():
            try:
                line.setVisible(False)
            except Exception:
                pass
        if best_dx is not None:
            x = x + float(best_dx)
            for key in ("left", "center", "right"):
                try:
                    self._guide_lines[key].setLine(best_x_target, 0.0, best_x_target, float(self.image_h))
                    self._guide_lines[key].setVisible(True)
                except Exception:
                    pass
        if best_dy is not None:
            y = y + float(best_dy)
            for key in ("top", "middle", "bottom"):
                try:
                    self._guide_lines[key].setLine(0.0, best_y_target, float(self.image_w), best_y_target)
                    self._guide_lines[key].setVisible(True)
                except Exception:
                    pass
        if best_dx is None and best_dy is None:
            self._hide_guides()
        return type(pos)(x, y)

    def _update_from_state(self, *, sync_geometry: bool = True):
        st = self.state
        base_w = max(1.0, float(st.w_norm) * float(self.image_w))
        base_h = max(1.0, float(getattr(st, "h_norm", st.w_norm)) * float(self.image_h))
        if st.kind == "text":
            txt = str(st.text or "")
            if self._content_pix is None:
                self._content_pix = QGraphicsPixmapItem(self)
                try:
                    self._content_pix.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    self._content_pix.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                    self._content_pix.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, False)
                    self._content_pix.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
                except Exception:
                    pass
            if self._content_text is not None:
                try:
                    self._content_text.setVisible(False)
                except Exception:
                    pass
            rgba = list(st.color_rgba or [255, 255, 255, 200])
            try:
                mode = str(getattr(st, "color_mode", "custom") or "custom")
            except Exception:
                mode = "custom"
            if mode == "auto" and self._bg_qimg is not None:
                try:
                    cx = float(st.x_norm) * float(self.image_w)
                    cy = float(st.y_norm) * float(self.image_h)
                    bw = float(base_w)
                    bh = float(base_h)
                    box = int(max(8, min(96, min(bw, bh))))
                    x0 = int(max(0, min(self.image_w - 1, round(cx - box / 2.0))))
                    y0 = int(max(0, min(self.image_h - 1, round(cy - box / 2.0))))
                    x1 = int(max(0, min(self.image_w, x0 + box)))
                    y1 = int(max(0, min(self.image_h, y0 + box)))
                    if x1 > x0 and y1 > y0:
                        sub = self._bg_qimg.copy(int(x0), int(y0), int(x1 - x0), int(y1 - y0)).convertToFormat(QImage.Format.Format_ARGB32)
                        ptr = sub.bits()
                        ptr.setsize(sub.sizeInBytes())
                        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((int(sub.height()), int(sub.width()), 4))
                        bgr = arr[:, :, :3].astype(np.float32)
                        lum = float((0.114 * bgr[:, :, 0] + 0.587 * bgr[:, :, 1] + 0.299 * bgr[:, :, 2]).mean())
                        rgb = 0 if lum >= 140.0 else 255
                        rgba = [int(rgb), int(rgb), int(rgb), int(rgba[3])]
                except Exception:
                    pass
            try:
                font_px = int(max(10, int(getattr(st, "font_point_size", 24) or 24)))
            except Exception:
                font_px = 24
            try:
                stroke_enabled = bool(getattr(st, "stroke_enabled", False))
            except Exception:
                stroke_enabled = False
            try:
                stroke_width = int(max(0, int(getattr(st, "stroke_width", 0) or 0)))
            except Exception:
                stroke_width = 0
            try:
                stroke_rgba = list(getattr(st, "stroke_rgba", None) or [])
            except Exception:
                stroke_rgba = []
            if not stroke_rgba:
                stroke_rgba = [0, 0, 0, 255]
            try:
                shadow_enabled = bool(getattr(st, "shadow_enabled", False))
            except Exception:
                shadow_enabled = False
            try:
                effect_mode = str(getattr(st, "effect_mode", "none") or "none")
            except Exception:
                effect_mode = "none"
            effect_mode = str(effect_mode or "none").strip().lower()
            if effect_mode == "none":
                shadow_enabled = False
            try:
                shadow_follow = bool(getattr(st, "shadow_follow_color", True))
            except Exception:
                shadow_follow = True
            try:
                shadow_rgba = list(getattr(st, "shadow_rgba", None) or [])
            except Exception:
                shadow_rgba = []
            if shadow_follow:
                shadow_rgba = [int(rgba[0]), int(rgba[1]), int(rgba[2]), 153]
            elif not shadow_rgba:
                shadow_rgba = [0, 0, 0, 153]
            try:
                shadow_dir = str(getattr(st, "shadow_dir", "右下") or "右下")
            except Exception:
                shadow_dir = "右下"
            try:
                shadow_dist = int(max(0, int(getattr(st, "shadow_distance", 4) or 4)))
            except Exception:
                shadow_dist = 4
            try:
                shadow_range = int(getattr(st, "shadow_range", 0) or 0)
            except Exception:
                shadow_range = 0
            unit = 1
            if effect_mode in ("mirror", "stack"):
                shadow_dist = unit
            dx, dy = 0, 0
            if shadow_dir == "右下":
                dx, dy = shadow_dist, shadow_dist
            elif shadow_dir == "左下":
                dx, dy = -shadow_dist, shadow_dist
            elif shadow_dir == "右上":
                dx, dy = shadow_dist, -shadow_dist
            elif shadow_dir == "左上":
                dx, dy = -shadow_dist, -shadow_dist
            elif shadow_dir == "上":
                dx, dy = 0, -shadow_dist
            elif shadow_dir == "下":
                dx, dy = 0, shadow_dist
            elif shadow_dir == "左":
                dx, dy = -shadow_dist, 0
            elif shadow_dir == "右":
                dx, dy = shadow_dist, 0
            if effect_mode == "beam" and shadow_enabled and int(getattr(st, "shadow_distance", 0) or 0) <= 0:
                shadow_enabled = False
            try:
                item_opacity = max(0.0, min(1.0, float(int(rgba[3])) / 255.0))
            except Exception:
                item_opacity = 1.0
            try:
                if self._content_pix is not None:
                    self._content_pix.setOpacity(float(item_opacity))
            except Exception:
                pass
            key = (
                str(txt),
                str(getattr(st, "font_family", "") or ""),
                int(font_px),
                bool(getattr(st, "font_bold", False)),
                bool(getattr(st, "font_italic", False)),
                bool(getattr(st, "font_underline", False)),
                tuple(int(x) for x in rgba[:3]),
                bool(stroke_enabled),
                int(stroke_width),
                tuple(int(x) for x in (stroke_rgba or [0, 0, 0, 255])[:4]),
                bool(shadow_enabled),
                bool(shadow_follow),
                tuple(int(x) for x in (shadow_rgba or [0, 0, 0, 153])[:4]),
                str(shadow_dir),
                int(shadow_dist),
                int(shadow_range),
                str(effect_mode),
                int(getattr(st, "mirror_gap_px", 0) or 0),
<<<<<<< HEAD
                int(getattr(st, "mirror_angle_deg", 180) or 180),
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
                int(getattr(st, "stack_count", 3) or 0),
                int(getattr(st, "stack_step_px", 2) or 0),
            )
            if key != self._render_key:
                self._render_key = key
                self._render_token = int(getattr(self, "_render_token", 0) or 0) + 1
                token = int(self._render_token)
                shadow_style = "none"
                if shadow_enabled and effect_mode in ("beam", "mirror", "stack"):
                    shadow_style = str(effect_mode)
                payload = {
                    "mode": "text_patch",
                    "text": str(txt),
                    "font_family": str(getattr(st, "font_family", "") or ""),
                    "font_px": int(font_px),
                    "bold": bool(getattr(st, "font_bold", False)),
                    "italic": bool(getattr(st, "font_italic", False)),
                    "underline": bool(getattr(st, "font_underline", False)),
                    "rgba": [int(rgba[0]), int(rgba[1]), int(rgba[2]), 255],
                    "angle_deg": 0.0,
                    "supersample": 6,
                    "stroke_width": int(stroke_width) if stroke_enabled else 0,
                    "stroke_rgba": [int(stroke_rgba[0]), int(stroke_rgba[1]), int(stroke_rgba[2]), int(stroke_rgba[3])] if stroke_enabled else None,
                    "shadow_offset": (int(dx), int(dy)) if shadow_enabled else (0, 0),
                    "shadow_rgba": [int(shadow_rgba[0]), int(shadow_rgba[1]), int(shadow_rgba[2]), int(shadow_rgba[3])] if shadow_enabled else None,
                    "shadow_range": int(shadow_range),
                    "shadow_style": str(shadow_style),
                    "mirror_gap_px": int(getattr(st, "mirror_gap_px", 0) or 0),
<<<<<<< HEAD
                    "mirror_angle_deg": float(getattr(st, "mirror_angle_deg", 180) or 180),
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
                    "stack_count": int(getattr(st, "stack_count", 3) or 0),
                    "stack_step_px": int(getattr(st, "stack_step_px", 2) or 0),
                }
                try:
                    if self._render_requester is not None and hasattr(self._render_requester, "_queue_text_patch_render"):
                        self._render_requester._queue_text_patch_render(str(st.wm_id), token, payload)
                except Exception:
                    pass
            if self._content_pix.pixmap().isNull():
                self.setRect(0, 0, float(base_w), float(base_h))
                try:
                    self.setTransformOriginPoint(float(base_w) / 2.0, float(base_h) / 2.0)
                    self._content_pix.setPos(0.0, 0.0)
                except Exception:
                    pass
        else:
            p = str(st.image_path or "")
            src_path = ""
            if p and os.path.exists(p):
                ext = os.path.splitext(p)[1].lower()
                if ext == ".svg":
                    try:
                        rp = str(getattr(st, "svg_raster_path", "") or "")
                    except Exception:
                        rp = ""
                    if not rp or not os.path.exists(rp):
                        try:
                            rp = _ensure_svg_raster_cache(p)
                        except Exception:
                            rp = ""
                        try:
                            st.svg_raster_path = str(rp or "")
                        except Exception:
                            pass
                    src_path = str(rp or "")
                else:
                    src_path = str(p or "")
            if self._content_pix is None:
                self._content_pix = QGraphicsPixmapItem(self)
                try:
                    self._content_pix.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
                except Exception:
                    pass
            target_w = int(max(1, round(base_w)))
            target_h = int(max(1, round(base_h)))
            try:
                me = bool(getattr(st, "mirror_effect", False))
            except Exception:
                me = False
            try:
                gap_px = int(getattr(st, "mirror_gap_px", 0) or 0)
            except Exception:
                gap_px = 0
            rgba = list(st.color_rgba or [255, 255, 255, 200])
            try:
                self._content_pix.setOpacity(float(rgba[3]) / 255.0)
            except Exception:
                pass
            if src_path:
                key = (str(src_path), int(target_w), int(target_h), bool(st.keep_aspect), bool(me), int(gap_px))
                if key != self._img_render_key:
                    self._img_render_key = key
                    self._img_render_token = int(getattr(self, "_img_render_token", 0) or 0) + 1
                    token = int(self._img_render_token)
                    payload = {
                        "target_w": int(target_w),
                        "target_h": int(target_h),
                        "keep_aspect": bool(st.keep_aspect),
                        "mirror_effect": bool(me),
                        "mirror_strength": 0.6,
                        "mirror_gap_px": int(gap_px),
                    }
                    try:
                        if self._render_requester is not None and hasattr(self._render_requester, "_queue_image_wm_render"):
                            self._render_requester._queue_image_wm_render(str(st.wm_id), token, str(src_path), payload)
                    except Exception:
                        pass
                if self._content_pix.pixmap().isNull():
                    self.setRect(0, 0, base_w, base_h if not bool(st.keep_aspect) else base_w)
                    try:
                        w, h = self._current_rect_wh()
                        self.setTransformOriginPoint(float(w) / 2.0, float(h) / 2.0)
                    except Exception:
                        pass
            else:
                self._content_pix.setPixmap(QPixmap())
                self.setRect(0, 0, base_w, base_h if not bool(st.keep_aspect) else base_w)
                try:
                    w, h = self._current_rect_wh()
                    self.setTransformOriginPoint(float(w) / 2.0, float(h) / 2.0)
                except Exception:
                    pass
            if self._content_text is not None:
                try:
                    self._content_text.setVisible(False)
                except Exception:
                    pass

        if bool(sync_geometry):
            try:
                self.setRotation(float(st.rotation_deg))
            except Exception:
                pass
            cx = float(st.x_norm) * float(self.image_w)
            cy = float(st.y_norm) * float(self.image_h)
            w, h = self._current_rect_wh()
            x0 = float(cx - w / 2.0)
            y0 = float(cy - h / 2.0)
            self.setPos(float(x0), float(y0))
            self._update_handles()
            try:
                for hdl in self._handles.values():
                    hdl.setVisible(False)
            except Exception:
                pass

    def _apply_text_patch(self, token: int, patch: object):
        try:
            if int(token) != int(getattr(self, "_render_token", 0) or 0):
                return
        except Exception:
            return
        if patch is None or not isinstance(patch, np.ndarray) or patch.ndim != 3 or patch.shape[2] < 4:
            return
        if self._content_pix is None:
            self._content_pix = QGraphicsPixmapItem(self)
        try:
            h, w = patch.shape[:2]
        except Exception:
            return
        if int(h) <= 0 or int(w) <= 0:
            return
        try:
            qimg = QImage(patch.data, int(w), int(h), int(patch.strides[0]), QImage.Format.Format_ARGB32)
            pix = QPixmap.fromImage(qimg.copy())
        except Exception:
            return
        self._content_pix.setPixmap(pix)
        try:
            self._content_pix.setVisible(True)
        except Exception:
            pass
        try:
            self._content_pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass
        x0i, y0i, x1i, y1i = 0, 0, int(w), int(h)
        try:
            a = patch[:, :, 3]
            thr = 200
            pad = 4
            try:
                mode = str(getattr(self.state, "effect_mode", "none") or "none").strip().lower()
            except Exception:
                mode = "none"
            if mode == "mirror":
                thr = 4
                try:
                    srng = int(getattr(self.state, "shadow_range", 0) or 0)
                except Exception:
                    srng = 0
                pad = int(6 + round(max(0, min(100, srng)) / 100.0 * 18.0))
            mask = a >= np.uint8(int(max(0, min(255, thr))))
            if bool(mask.any()):
                ys = np.where(np.any(mask, axis=1))[0]
                xs = np.where(np.any(mask, axis=0))[0]
                if ys.size > 0 and xs.size > 0:
                    y0i = int(ys[0])
                    y1i = int(ys[-1] + 1)
                    x0i = int(xs[0])
                    x1i = int(xs[-1] + 1)
        except Exception:
            x0i, y0i, x1i, y1i = 0, 0, int(w), int(h)
        try:
            x0i = int(max(0, x0i - pad))
            y0i = int(max(0, y0i - pad))
            x1i = int(min(int(w), x1i + pad))
            y1i = int(min(int(h), y1i + pad))
        except Exception:
            pass
        rect_w = float(max(1, int(x1i - x0i)))
        rect_h = float(max(1, int(y1i - y0i)))
        self.setRect(0, 0, float(rect_w), float(rect_h))
        self.setTransformOriginPoint(float(rect_w) / 2.0, float(rect_h) / 2.0)
        self._content_pix.setPos(float(-x0i), float(-y0i))
        try:
            cx = float(self.state.x_norm) * float(self.image_w)
            cy = float(self.state.y_norm) * float(self.image_h)
            x0 = float(cx - float(rect_w) / 2.0)
            y0 = float(cy - float(rect_h) / 2.0)
            self.setPos(float(x0), float(y0))
        except Exception:
            pass
        self._update_handles()

    def _apply_image_qimg(self, token: int, qimg: object):
        try:
            if int(token) != int(getattr(self, "_img_render_token", 0) or 0):
                return
        except Exception:
            return
        if not isinstance(qimg, QImage) or qimg.isNull():
            return
        if self._content_pix is None:
            self._content_pix = QGraphicsPixmapItem(self)
        try:
            pix = QPixmap.fromImage(qimg)
        except Exception:
            return
        if pix.isNull():
            return
        self._content_pix.setPixmap(pix)
        self._content_pix.setScale(1.0)
        self._content_pix.setPos(0.0, 0.0)
        try:
            self._content_pix.setVisible(True)
        except Exception:
            pass
        rgba = list(getattr(self.state, "color_rgba", None) or [255, 255, 255, 200])
        try:
            self._content_pix.setOpacity(float(rgba[3]) / 255.0)
        except Exception:
            pass
        pix_w = float(pix.width())
        pix_h = float(pix.height())
        base_w = float(max(1.0, float(getattr(self.state, "w_norm", 0.25) or 0.25) * float(self.image_w)))
        base_h = float(max(1.0, float(getattr(self.state, "h_norm", getattr(self.state, "w_norm", 0.25)) or getattr(self.state, "w_norm", 0.25)) * float(self.image_h)))

        # 图片水印渲染时可能会因为阴影/特效扩展输出画布，导致水印边框随“模糊度”等参数一起变大
        # 这里固定交互边框为水印本体尺寸（base_w/base_h），把渲染结果居中摆放，避免拖拽框抖动/变形
        self.setRect(0, 0, float(base_w), float(base_h))
        self.setTransformOriginPoint(float(base_w) / 2.0, float(base_h) / 2.0)
        try:
            self._content_pix.setPos(float((base_w - pix_w) / 2.0), float((base_h - pix_h) / 2.0))
        except Exception:
            self._content_pix.setPos(0.0, 0.0)
        try:
            self.setRotation(float(getattr(self.state, "rotation_deg", 0.0) or 0.0))
        except Exception:
            pass
        try:
            cx = float(self.state.x_norm) * float(self.image_w)
            cy = float(self.state.y_norm) * float(self.image_h)
            x0 = float(cx - float(base_w) / 2.0)
            y0 = float(cy - float(base_h) / 2.0)
            self.setPos(float(x0), float(y0))
        except Exception:
            pass
        self._update_handles()

    def _on_handle_press(self, _corner: str, scene_pos):
        try:
            if callable(self.on_interaction):
                self.on_interaction(True)
        except Exception:
            pass
        self._interacting = True
        self._handle_start_rect = self.rect()
        self._handle_start_scene = scene_pos
        self._handle_start_w_norm = float(self.state.w_norm)
        try:
            w, h = self._current_rect_wh()
            x0 = float(self.pos().x())
            y0 = float(self.pos().y())
            self._handle_start_center = (x0 + w / 2.0, y0 + h / 2.0)
        except Exception:
            self._handle_start_center = None

    def _on_handle_drag(self, corner: str, scene_pos):
        if self._handle_start_rect is None or self._handle_start_scene is None:
            return
        try:
            rect = self._handle_start_rect
            if corner == "tl":
                opp = QPointF(rect.width(), rect.height())
            elif corner == "tr":
                opp = QPointF(0.0, rect.height())
            elif corner == "bl":
                opp = QPointF(rect.width(), 0.0)
            else:
                opp = QPointF(0.0, 0.0)
            local_pos = self.mapFromScene(scene_pos)
            new_w = abs(float(local_pos.x() - opp.x()))
            new_h = abs(float(local_pos.y() - opp.y()))
            if bool(self.state.keep_aspect):
                size = max(new_w, new_h)
                new_w = size
                new_h = size
            new_w = max(8.0, min(float(self.image_w), new_w))
            new_h = max(8.0, min(float(self.image_h), new_h))
            if corner in ("tl", "tr"):
                y_local = float(opp.y() - new_h)
            else:
                y_local = float(opp.y())
            if corner in ("tl", "bl"):
                x_local = float(opp.x() - new_w)
            else:
                x_local = float(opp.x())
            new_top_left_scene = self.mapToScene(QPointF(x_local, y_local))
            self.setRect(0.0, 0.0, float(new_w), float(new_h))
            self.setPos(new_top_left_scene)
            if str(getattr(self.state, "kind", "text") or "text") != "text" and self._content_pix is not None:
                try:
                    pm = self._content_pix.pixmap()
                    if not pm.isNull():
                        scaled = pm.scaled(int(max(1, round(new_w))), int(max(1, round(new_h))), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self._content_pix.setPixmap(scaled)
                except Exception:
                    pass
            self._update_handles()
            self._sync_state_from_item()
        except Exception:
            pass

    def _on_handle_release(self, _corner: str, _scene_pos):
        self._handle_start_rect = None
        self._handle_start_scene = None
        self._handle_start_w_norm = None
        self._handle_start_center = None
        self._interacting = False
        try:
            if callable(self.on_interaction):
                self.on_interaction(False)
        except Exception:
            pass


@dataclass
class WatermarkState:
    wm_id: str
    name: str
    kind: str
    visible: bool = True
    x_norm: float = 0.5
    y_norm: float = 0.5
    w_norm: float = 0.25
    h_norm: float = 0.25
    rotation_deg: float = 0.0
    keep_aspect: bool = True
    text_mode: str = "custom"
    custom_text: str = "水印"
    tag_key: str = ""
    text: str = "水印"
    font_family: str = ""
    font_base_size: int = 24
    font_point_size: int = 24
    font_bold: bool = False
    font_italic: bool = False
    font_underline: bool = False
    color_rgba: list = None
    color_mode: str = "custom"
    stroke_enabled: bool = False
    stroke_width: int = 2
    stroke_rgba: list = None
    shadow_enabled: bool = False
    shadow_follow_color: bool = True
    shadow_rgba: list = None
    shadow_dir: str = "右下"
    shadow_distance: int = 4
    shadow_range: int = 0
    effect_mode: str = "none"
    mirror_effect: bool = False
    mirror_gap_px: int = 0
<<<<<<< HEAD
    mirror_angle_deg: int = 180
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
    stack_count: int = 3
    stack_step_px: int = 2
    image_path: str = ""
    svg_raster_path: str = ""

    def to_json(self) -> dict:
        return {
            "wm_id": self.wm_id,
            "name": self.name,
            "kind": self.kind,
            "visible": bool(self.visible),
            "x_norm": float(self.x_norm),
            "y_norm": float(self.y_norm),
            "w_norm": float(self.w_norm),
            "h_norm": float(self.h_norm),
            "rotation_deg": float(self.rotation_deg),
            "keep_aspect": bool(self.keep_aspect),
            "text_mode": str(self.text_mode or "custom"),
            "custom_text": str(self.custom_text or ""),
            "tag_key": str(self.tag_key or ""),
            "font_family": str(self.font_family or ""),
            "font_base_size": int(self.font_base_size or self.font_point_size or 24),
            "font_point_size": int(self.font_point_size or 24),
            "font_bold": bool(self.font_bold),
            "font_italic": bool(self.font_italic),
            "font_underline": bool(self.font_underline),
            "color_rgba": list(self.color_rgba or [255, 255, 255, 200]),
            "color_mode": str(getattr(self, "color_mode", "custom") or "custom"),
            "stroke_enabled": bool(getattr(self, "stroke_enabled", False)),
            "stroke_width": int(getattr(self, "stroke_width", 2) or 0),
            "stroke_rgba": list(getattr(self, "stroke_rgba", None) or []),
            "shadow_enabled": bool(getattr(self, "shadow_enabled", False)),
            "shadow_follow_color": bool(getattr(self, "shadow_follow_color", True)),
            "shadow_rgba": list(getattr(self, "shadow_rgba", None) or []),
            "shadow_dir": str(getattr(self, "shadow_dir", "右下") or "右下"),
            "shadow_distance": int(getattr(self, "shadow_distance", 4) or 0),
            "shadow_range": int(getattr(self, "shadow_range", 0) or 0),
            "effect_mode": str(getattr(self, "effect_mode", "none") or "none"),
            "mirror_effect": bool(getattr(self, "mirror_effect", False)),
            "mirror_gap_px": int(getattr(self, "mirror_gap_px", 0) or 0),
<<<<<<< HEAD
            "mirror_angle_deg": int(getattr(self, "mirror_angle_deg", 180) or 180),
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
            "stack_count": int(getattr(self, "stack_count", 3) or 0),
            "stack_step_px": int(getattr(self, "stack_step_px", 2) or 0),
            "image_path": str(self.image_path or ""),
            "svg_raster_path": str(self.svg_raster_path or ""),
        }

    @staticmethod
    def from_json(d: dict) -> "WatermarkState":
        d = d or {}
        st = WatermarkState(
            wm_id=str(d.get("wm_id") or ""),
            name=str(d.get("name") or "水印"),
            kind=str(d.get("kind") or "text"),
        )
        st.visible = bool(d.get("visible", True))
        st.x_norm = float(d.get("x_norm", 0.5))
        st.y_norm = float(d.get("y_norm", 0.5))
        st.w_norm = float(d.get("w_norm", 0.25))
        st.h_norm = float(d.get("h_norm", d.get("w_norm", 0.25)))
        st.rotation_deg = float(d.get("rotation_deg", 0.0))
        st.keep_aspect = bool(d.get("keep_aspect", True))
        st.text_mode = str(d.get("text_mode") or "custom")
        st.custom_text = str(d.get("custom_text") or d.get("text") or "水印")
        st.tag_key = str(d.get("tag_key") or "")
        st.text = str(st.custom_text or "水印")
        st.font_family = str(d.get("font_family") or "")
        st.font_base_size = int(d.get("font_base_size") or d.get("font_point_size") or 24)
        st.font_point_size = int(d.get("font_point_size") or 24)
        st.font_bold = bool(d.get("font_bold", False))
        st.font_italic = bool(d.get("font_italic", False))
        st.font_underline = bool(d.get("font_underline", False))
        st.color_rgba = list(d.get("color_rgba") or [255, 255, 255, 200])
        st.color_mode = str(d.get("color_mode") or "custom")
        st.stroke_enabled = bool(d.get("stroke_enabled", False))
        st.stroke_width = int(d.get("stroke_width") or 2)
        st.stroke_rgba = list(d.get("stroke_rgba") or [])
        st.shadow_enabled = bool(d.get("shadow_enabled", False))
        st.shadow_follow_color = bool(d.get("shadow_follow_color", True))
        st.shadow_rgba = list(d.get("shadow_rgba") or [])
        st.shadow_dir = str(d.get("shadow_dir") or "右下")
        st.shadow_distance = int(d.get("shadow_distance") or 4)
        st.shadow_range = int(d.get("shadow_range") or 0)
        try:
            if d.get("effect_mode") is not None:
                st.effect_mode = str(d.get("effect_mode") or "none")
            else:
                st.effect_mode = "mirror" if bool(d.get("mirror_effect", False)) else "beam"
        except Exception:
            st.effect_mode = "none"
        st.mirror_effect = bool(d.get("mirror_effect", False))
        try:
            if d.get("mirror_gap_px") is not None:
                st.mirror_gap_px = int(d.get("mirror_gap_px") or 0)
            else:
                st.mirror_gap_px = int(d.get("mirror_gap_percent") or 0)
        except Exception:
            st.mirror_gap_px = 0
        try:
            st.mirror_gap_px = int(max(0, min(200, int(st.mirror_gap_px))))
        except Exception:
            st.mirror_gap_px = 0
        try:
<<<<<<< HEAD
            st.mirror_angle_deg = int(d.get("mirror_angle_deg") if d.get("mirror_angle_deg") is not None else 180)
        except Exception:
            st.mirror_angle_deg = 180
        try:
            st.mirror_angle_deg = int(max(0, min(180, int(st.mirror_angle_deg))))
        except Exception:
            st.mirror_angle_deg = 180
        try:
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
            st.stack_count = int(d.get("stack_count") or 3)
        except Exception:
            st.stack_count = 3
        try:
            st.stack_count = int(max(1, min(20, int(st.stack_count))))
        except Exception:
            st.stack_count = 3
        try:
            st.stack_step_px = int(d.get("stack_step_px") or 2)
        except Exception:
            st.stack_step_px = 2
        try:
            st.stack_step_px = int(max(0, min(50, int(st.stack_step_px))))
        except Exception:
            st.stack_step_px = 2
        st.image_path = str(d.get("image_path") or "")
        st.svg_raster_path = str(d.get("svg_raster_path") or "")
        try:
            if str(st.image_path or "").lower().endswith(".svg"):
                rp = _ensure_svg_raster_cache(st.image_path)
                if rp:
                    st.svg_raster_path = rp
        except Exception:
            pass
        return st


class _WatermarkSignals(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(bool, str)


class _WatermarkBatchTask(QRunnable):
    def __init__(
        self,
        file_paths: List[str],
        states: List[WatermarkState],
        ref_is_landscape: bool | None = None,
        auto_rotate: bool = False,
        preview_max_edge: int = 1600,
    ):
        super().__init__()
        self.file_paths = [str(p) for p in (file_paths or []) if p]
        safe_states = []
        for s in (states or []):
            if s is None:
                continue
            if isinstance(s, WatermarkState):
                try:
                    safe_states.append(WatermarkState.from_json(s.to_json()))
                    continue
                except Exception:
                    pass
            if isinstance(s, dict):
                try:
                    safe_states.append(WatermarkState.from_json(s))
                    continue
                except Exception:
                    pass
        self.states = safe_states
        self.ref_is_landscape = ref_is_landscape
        self.auto_rotate = bool(auto_rotate)
        try:
            self.preview_max_edge = int(preview_max_edge or 1600)
        except Exception:
            self.preview_max_edge = 1600
        self.signals = _WatermarkSignals()
        self.changed_paths = []
        self.unchanged_paths = []

    def _resolve_text_for_meta(self, st: WatermarkState, meta: dict) -> str:
        mode = str(getattr(st, "text_mode", "custom") or "custom")
        tag_key = str(getattr(st, "tag_key", "") or "")
        if mode == "tag" and not str(getattr(st, "custom_text", "") or "").strip() and tag_key:
            base_text = ""
        else:
            base_text = str(getattr(st, "custom_text", "") or getattr(st, "text", "") or "")
        try:
            if "{" in base_text and "}" in base_text:
                keys = list(meta.keys()) if isinstance(meta, dict) else []
                LogManager.instance().debug(f"[Watermark] 标签解析输入: {base_text}")
                LogManager.instance().debug(f"[Watermark] 元数据键数量: {len(keys)} 预览: {keys[:30]}")
        except Exception:
            pass
        resolved = _resolve_text_with_tags(
            meta,
            base_text,
            WATERMARK_TAG_LABEL_TO_KEY,
            WATERMARK_TAG_KEY_SET,
            WATERMARK_TAG_KEY_TO_LABEL,
            fallback_tag_key=str(getattr(st, "tag_key", "") or ""),
        )
        try:
            if "{" in base_text and "}" in base_text:
                LogManager.instance().debug(f"[Watermark] 标签解析结果: {resolved}")
        except Exception:
            pass
        return resolved

    def _compose_on_image(self, img_bgr: np.ndarray, states: List[WatermarkState], angle_offset: float = 0.0, meta: dict | None = None) -> np.ndarray:
        if img_bgr is None or not isinstance(img_bgr, np.ndarray):
            return img_bgr
        if meta is None or not isinstance(meta, dict):
            meta = {}
        h, w = img_bgr.shape[:2]
        out = img_bgr.copy()
        preview_w, preview_h = w, h
        try:
            preview_w, preview_h = _scale_long_edge(int(w), int(h), int(getattr(self, "preview_max_edge", 1600) or 1600))
        except Exception:
            preview_w, preview_h = w, h
        preview_scale_ratio = 1.0
        try:
            preview_scale_ratio = float(max(1, int(max(w, h)))) / float(max(1, int(max(preview_w, preview_h))))
        except Exception:
            preview_scale_ratio = 1.0
        for st in states:
            if not st.visible:
                continue
            cx = float(st.x_norm) * float(w)
            cy = float(st.y_norm) * float(h)
            target_w = max(1.0, float(st.w_norm) * float(w))
            target_h = max(1.0, float(getattr(st, "h_norm", st.w_norm)) * float(h))
            angle = float(st.rotation_deg) + float(angle_offset or 0.0)
            if st.kind == "text":
                txt = self._resolve_text_for_meta(st, meta)
                if not txt:
                    continue
                rgba = list(st.color_rgba or [255, 255, 255, 200])
                try:
                    mode = str(getattr(st, "color_mode", "custom") or "custom")
                except Exception:
                    mode = "custom"
                if mode == "auto":
                    try:
                        bw = float(target_w)
                        bh = float(target_h)
                        box = int(max(8, min(96, min(bw, bh))))
                        x0b = int(max(0, min(w - 1, round(cx - box / 2.0))))
                        y0b = int(max(0, min(h - 1, round(cy - box / 2.0))))
                        x1b = int(max(0, min(w, x0b + box)))
                        y1b = int(max(0, min(h, y0b + box)))
                        if x1b > x0b and y1b > y0b:
                            roi_bg = out[int(y0b):int(y1b), int(x0b):int(x1b)]
                            if roi_bg is not None and isinstance(roi_bg, np.ndarray) and roi_bg.size > 0 and roi_bg.ndim == 3:
                                bgr = roi_bg[:, :, :3].astype(np.float32)
                                lum = float((0.114 * bgr[:, :, 0] + 0.587 * bgr[:, :, 1] + 0.299 * bgr[:, :, 2]).mean())
                                rgb = 0 if lum >= 140.0 else 255
                                rgba = [int(rgb), int(rgb), int(rgb), int(rgba[3])]
                    except Exception:
                        pass
                try:
                    font_px = int(getattr(st, "font_point_size", 0) or 0)
                except Exception:
                    font_px = 0
                if int(font_px) <= 0:
                    try:
                        font_px = int(getattr(st, "font_base_size", 0) or 0)
                    except Exception:
                        font_px = 0
                if int(font_px) <= 0:
                    font_px = 24
                try:
                    font_px = int(round(float(font_px) * float(preview_scale_ratio)))
                except Exception:
                    pass
                font_px = max(10, int(font_px))
                try:
                    stroke_enabled = bool(getattr(st, "stroke_enabled", False))
                except Exception:
                    stroke_enabled = False
                try:
                    stroke_width = int(max(0, int(getattr(st, "stroke_width", 0) or 0)))
                except Exception:
                    stroke_width = 0
                try:
                    stroke_rgba = list(getattr(st, "stroke_rgba", None) or [])
                except Exception:
                    stroke_rgba = []
                if not stroke_rgba:
                    stroke_rgba = [0, 0, 0, int(rgba[3])]
                try:
                    shadow_enabled = bool(getattr(st, "shadow_enabled", False))
                except Exception:
                    shadow_enabled = False
                try:
                    effect_mode = str(getattr(st, "effect_mode", "none") or "none")
                except Exception:
                    effect_mode = "none"
                effect_mode = str(effect_mode or "none").strip().lower()
                if effect_mode == "none":
                    shadow_enabled = False
                try:
                    shadow_follow = bool(getattr(st, "shadow_follow_color", True))
                except Exception:
                    shadow_follow = True
                try:
                    shadow_rgba = list(getattr(st, "shadow_rgba", None) or [])
                except Exception:
                    shadow_rgba = []
                if shadow_follow:
                    shadow_rgba = [int(rgba[0]), int(rgba[1]), int(rgba[2]), int(max(0, min(255, round(int(rgba[3]) * 0.6))))]
                elif not shadow_rgba:
                    shadow_rgba = [0, 0, 0, int(max(0, min(255, round(int(rgba[3]) * 0.6))))]
                try:
                    shadow_dir = str(getattr(st, "shadow_dir", "右下") or "右下")
                except Exception:
                    shadow_dir = "右下"
                try:
                    shadow_dist = int(max(0, int(getattr(st, "shadow_distance", 4) or 4)))
                except Exception:
                    shadow_dist = 4
                try:
                    shadow_range = int(getattr(st, "shadow_range", 0) or 0)
                except Exception:
                    shadow_range = 0
                if effect_mode in ("mirror", "stack"):
                    shadow_dist = 1
                dx, dy = 0, 0
                if shadow_dir == "右下":
                    dx, dy = shadow_dist, shadow_dist
                elif shadow_dir == "左下":
                    dx, dy = -shadow_dist, shadow_dist
                elif shadow_dir == "右上":
                    dx, dy = shadow_dist, -shadow_dist
                elif shadow_dir == "左上":
                    dx, dy = -shadow_dist, -shadow_dist
                elif shadow_dir == "上":
                    dx, dy = 0, -shadow_dist
                elif shadow_dir == "下":
                    dx, dy = 0, shadow_dist
                elif shadow_dir == "左":
                    dx, dy = -shadow_dist, 0
                elif shadow_dir == "右":
                    dx, dy = shadow_dist, 0
                if effect_mode == "beam" and shadow_enabled and int(getattr(st, "shadow_distance", 0) or 0) <= 0:
                    shadow_enabled = False
                shadow_style = "none"
                if shadow_enabled and effect_mode in ("beam", "mirror", "stack"):
                    shadow_style = str(effect_mode)
                patch = _render_text_patch_to_bgra_safe(
                    str(txt),
                    str(getattr(st, "font_family", "") or ""),
                    int(font_px),
                    bold=bool(getattr(st, "font_bold", False)),
                    italic=bool(getattr(st, "font_italic", False)),
                    underline=bool(getattr(st, "font_underline", False)),
                    rgba=[int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3])],
                    # 旋转方向需与预览保持一致（预览使用 QGraphicsItem.setRotation(st.rotation_deg)）
                    angle_deg=float(angle),
                    # 提高超采样倍率，降低斜线/曲线边缘锯齿（尤其在旋转与小字号时更明显）
                    supersample=6,
                    stroke_width=int(stroke_width) if stroke_enabled else 0,
                    stroke_rgba=[int(stroke_rgba[0]), int(stroke_rgba[1]), int(stroke_rgba[2]), int(stroke_rgba[3])] if stroke_enabled else None,
                    shadow_offset=(int(dx), int(dy)) if shadow_enabled else (0, 0),
                    shadow_rgba=[int(shadow_rgba[0]), int(shadow_rgba[1]), int(shadow_rgba[2]), int(shadow_rgba[3])] if shadow_enabled else None,
                    shadow_range=int(shadow_range),
                    shadow_style=str(shadow_style),
                    mirror_gap_px=int(getattr(st, "mirror_gap_px", 0) or 0),
<<<<<<< HEAD
                    mirror_angle_deg=float(getattr(st, "mirror_angle_deg", 180) or 180),
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
                    stack_count=int(getattr(st, "stack_count", 3) or 0),
                    stack_step_px=int(getattr(st, "stack_step_px", 2) or 0),
                )
                if patch is None or not isinstance(patch, np.ndarray):
                    continue
                if patch.ndim != 3 or patch.shape[2] < 4:
                    continue
                ph, pw = patch.shape[:2]
                if ph <= 0 or pw <= 0:
                    continue
                x0 = int(round(cx - float(pw) / 2.0))
                y0 = int(round(cy - float(ph) / 2.0))
                x1 = x0 + int(pw)
                y1 = y0 + int(ph)
                ix0 = max(0, x0)
                iy0 = max(0, y0)
                ix1 = min(w, x1)
                iy1 = min(h, y1)
                if ix1 <= ix0 or iy1 <= iy0:
                    continue
                roi = out[iy0:iy1, ix0:ix1]
                if roi.size == 0:
                    continue
                ox0 = int(ix0 - x0)
                oy0 = int(iy0 - y0)
                ox1 = int(ox0 + (ix1 - ix0))
                oy1 = int(oy0 + (iy1 - iy0))
                patch_roi = patch[oy0:oy1, ox0:ox1]
                if patch_roi.size == 0:
                    continue
                try:
                    alpha = patch_roi[:, :, 3:4].astype(np.float32) / 255.0
                    fg = patch_roi[:, :, :3].astype(np.float32)
                    bg = roi.astype(np.float32)
                    comp = fg * alpha + bg * (1.0 - alpha)
                    out[iy0:iy1, ix0:ix1] = np.clip(comp, 0.0, 255.0).astype(np.uint8)
                except Exception:
                    pass
            else:
                p = str(st.image_path or "")
                if not p or not os.path.exists(p):
                    continue
                ext = os.path.splitext(p)[1].lower()
                if ext == ".svg":
                    rp = ""
                    try:
                        rp = str(getattr(st, "svg_raster_path", "") or "")
                    except Exception:
                        rp = ""
                    if not rp or not os.path.exists(rp):
                        continue
                    data = np.fromfile(rp, dtype=np.uint8)
                    wm = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
                    if wm is None:
                        continue
                    if wm.ndim == 2:
                        wm = cv2.cvtColor(wm, cv2.COLOR_GRAY2BGRA)
                    elif wm.shape[2] == 3:
                        wm = cv2.cvtColor(wm, cv2.COLOR_BGR2BGRA)
                    wm_rgba = wm
                else:
                    data = np.fromfile(p, dtype=np.uint8)
                    wm = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
                    if wm is None:
                        continue
                    if wm.ndim == 2:
                        wm = cv2.cvtColor(wm, cv2.COLOR_GRAY2BGRA)
                    elif wm.shape[2] == 3:
                        wm = cv2.cvtColor(wm, cv2.COLOR_BGR2BGRA)
                    wm_rgba = wm
                wh, ww = wm_rgba.shape[:2]
                if wh <= 0 or ww <= 0:
                    continue
                if bool(st.keep_aspect):
                    img_scale_ratio = float(target_w) / float(max(1, ww))
                    new_w = max(1, int(round(ww * img_scale_ratio)))
                    new_h = max(1, int(round(wh * img_scale_ratio)))
                    interp_up = cv2.INTER_CUBIC
                    try:
                        if hasattr(cv2, "INTER_LANCZOS4"):
                            interp_up = cv2.INTER_LANCZOS4
                    except Exception:
                        pass
                    wm_rgba = cv2.resize(wm_rgba, (new_w, new_h), interpolation=cv2.INTER_AREA if img_scale_ratio < 1 else interp_up)
                else:
                    scale_w = float(target_w) / float(max(1, ww))
                    scale_h = float(target_h) / float(max(1, wh))
                    new_w = max(1, int(round(ww * scale_w)))
                    new_h = max(1, int(round(wh * scale_h)))
                    interp_up = cv2.INTER_CUBIC
                    try:
                        if hasattr(cv2, "INTER_LANCZOS4"):
                            interp_up = cv2.INTER_LANCZOS4
                    except Exception:
                        pass
                    wm_rgba = cv2.resize(wm_rgba, (new_w, new_h), interpolation=cv2.INTER_AREA if max(scale_w, scale_h) < 1 else interp_up)
                try:
                    if bool(getattr(st, "mirror_effect", False)):
                        wm_rgba = _apply_mirror_effect_bgra(
                            wm_rgba,
                            strength=0.6,
                            gap_px=int(getattr(st, "mirror_gap_px", 0) or 0),
                        )
                except Exception:
                    pass
                if abs(angle) > 0.1:
                    try:
                        # 旋转方向需与预览保持一致
                        wm_rgba = _rotate_bgra_keep_bounds(wm_rgba, float(angle))
                    except Exception:
                        M = cv2.getRotationMatrix2D((new_w / 2.0, new_h / 2.0), angle, 1.0)
                        wm_rgba = cv2.warpAffine(wm_rgba, M, (new_w, new_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
                wh, ww = wm_rgba.shape[:2]
                x0 = int(round(cx - ww / 2.0))
                y0 = int(round(cy - wh / 2.0))
                x1 = x0 + ww
                y1 = y0 + wh
                ix0 = max(0, x0)
                iy0 = max(0, y0)
                ix1 = min(w, x1)
                iy1 = min(h, y1)
                if ix1 <= ix0 or iy1 <= iy0:
                    continue
                roi = out[iy0:iy1, ix0:ix1]
                wm_roi = wm_rgba[(iy0 - y0):(iy1 - y0), (ix0 - x0):(ix1 - x0)]
                if wm_roi.shape[2] < 4:
                    continue
                rgba = list(st.color_rgba or [255, 255, 255, 200])
                alpha = wm_roi[:, :, 3:4].astype(np.float32) / 255.0
                alpha = alpha * (float(rgba[3]) / 255.0)
                fg = wm_roi[:, :, :3].astype(np.float32)
                bg = roi.astype(np.float32)
                comp = fg * alpha + bg * (1.0 - alpha)
                out[iy0:iy1, ix0:ix1] = comp.astype(np.uint8)
        return out

    def _imencode_like_original(self, src_path: str, img_bgr: np.ndarray) -> tuple[bytes | None, str]:
        ext_src = os.path.splitext(str(src_path or ""))[1].lower()
        ext = str(ext_src or "")

        encode_ext = ext
        if encode_ext in (".jpg", ".jpeg"):
            encode_ext = ".jpg"
        elif encode_ext in (".png", ".webp", ".bmp", ".tif", ".tiff"):
            encode_ext = encode_ext
        else:
            return None, ext

        if encode_ext == ".png":
            ok, buf = cv2.imencode(".png", img_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            return (buf.tobytes() if ok else None), ext
        if encode_ext == ".webp":
            try:
                ok, buf = cv2.imencode(".webp", img_bgr, [cv2.IMWRITE_WEBP_QUALITY, 95])
                return (buf.tobytes() if ok else None), ext
            except Exception:
                return None, ext
        if encode_ext in (".bmp", ".tif", ".tiff"):
            try:
                ok, buf = cv2.imencode(str(encode_ext), img_bgr)
                return (buf.tobytes() if ok else None), ext
            except Exception:
                return None, ext

        params = [cv2.IMWRITE_JPEG_QUALITY, 100]
        try:
            if hasattr(cv2, "IMWRITE_JPEG_OPTIMIZE"):
                params.extend([cv2.IMWRITE_JPEG_OPTIMIZE, 1])
        except Exception:
            pass
        try:
            if hasattr(cv2, "IMWRITE_JPEG_PROGRESSIVE"):
                params.extend([cv2.IMWRITE_JPEG_PROGRESSIVE, 1])
        except Exception:
            pass
        try:
            if hasattr(cv2, "IMWRITE_JPEG_SAMPLING_FACTOR") and hasattr(cv2, "IMWRITE_JPEG_SAMPLING_FACTOR_444"):
                params.extend([cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444])
        except Exception:
            pass
        try:
            ok, buf = cv2.imencode(".jpg", img_bgr, params)
            return (buf.tobytes() if ok else None), ext
        except Exception:
            return None, ext

    def _copy_exif(self, src_path: str, dst_path: str) -> bool:
        exiftool = get_exiftool_path()
        if not exiftool or not os.path.exists(exiftool):
            try:
                return bool(self._copy_exif_fallback(src_path, dst_path))
            except Exception:
                return False
        cmd = [
            str(exiftool),
            "-TagsFromFile",
            str(src_path),
            "-all:all",
            "-overwrite_original",
            "-P",
            "-q",
            "-q",
            str(dst_path),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60)
            ok = int(getattr(r, "returncode", 1) or 1) == 0
            if ok:
                return True
            try:
                return bool(self._copy_exif_fallback(src_path, dst_path))
            except Exception:
                return False
        except Exception:
            try:
                return bool(self._copy_exif_fallback(src_path, dst_path))
            except Exception:
                return False

    def _copy_exif_fallback(self, src_path: str, dst_path: str) -> bool:
        sp = str(src_path or "")
        dp = str(dst_path or "")
        ext1 = os.path.splitext(sp)[1].lower()
        ext2 = os.path.splitext(dp)[1].lower()
        if ext1 not in (".jpg", ".jpeg") or ext2 not in (".jpg", ".jpeg"):
            return False
        try:
            with open(sp, "rb") as f:
                src_bytes = f.read()
        except Exception:
            return False
        try:
            with open(dp, "rb") as f:
                dst_bytes = f.read()
        except Exception:
            return False
        merged = self._merge_jpeg_app_segments(src_bytes, dst_bytes, app_markers={0xE1, 0xE2, 0xED})
        if not merged:
            return False
        try:
            with open(dp, "wb") as f:
                f.write(merged)
            return True
        except Exception:
            return False

    def _merge_jpeg_app_segments(self, src_bytes: bytes, dst_bytes: bytes, app_markers: set[int] | None = None) -> bytes | None:
        if not src_bytes or not dst_bytes:
            return None
        if len(src_bytes) < 4 or len(dst_bytes) < 4:
            return None
        if not (src_bytes[0] == 0xFF and src_bytes[1] == 0xD8):
            return None
        if not (dst_bytes[0] == 0xFF and dst_bytes[1] == 0xD8):
            return None
        if app_markers is None:
            app_markers = {0xE1}

        def _split_segments(jpeg: bytes):
            segs = []
            tail = b""
            i = 2
            n = len(jpeg)
            while i + 1 < n:
                if jpeg[i] != 0xFF:
                    i += 1
                    continue
                j = i
                while j < n and jpeg[j] == 0xFF:
                    j += 1
                if j >= n:
                    break
                marker = jpeg[j]
                i = j + 1
                if marker == 0xDA:
                    tail = jpeg[j - 1 :]
                    break
                if marker == 0xD9:
                    tail = jpeg[j - 1 :]
                    break
                if marker == 0x01 or (0xD0 <= marker <= 0xD7):
                    segs.append(jpeg[j - 1 : j + 1])
                    continue
                if i + 1 >= n:
                    break
                seg_len = (int(jpeg[i]) << 8) | int(jpeg[i + 1])
                if seg_len < 2:
                    break
                start = j - 1
                end = start + 2 + seg_len
                if end > n:
                    break
                segs.append(jpeg[start:end])
                i = end
            if not tail:
                tail = jpeg[i:] if i < n else b""
            return segs, tail

        src_segs, _src_tail = _split_segments(src_bytes)
        dst_segs, dst_tail = _split_segments(dst_bytes)
        if not dst_tail:
            dst_tail = dst_bytes[2:]

        src_app = []
        for seg in src_segs:
            if not seg or len(seg) < 2:
                continue
            if seg[0] != 0xFF:
                continue
            mk = int(seg[1])
            if mk in app_markers:
                src_app.append(seg)

        if not src_app:
            return None

        kept = []
        for seg in dst_segs:
            if not seg or len(seg) < 2:
                continue
            if seg[0] != 0xFF:
                continue
            mk = int(seg[1])
            if mk in app_markers:
                continue
            kept.append(seg)

        insert_after = {0xE0, 0xEE, 0xE2}
        insert_idx = 0
        for idx, seg in enumerate(kept):
            try:
                mk = int(seg[1])
            except Exception:
                mk = -1
            if mk in insert_after:
                insert_idx = idx + 1
            else:
                break
        merged_segs = kept[:insert_idx] + src_app + kept[insert_idx:]
        return b"\xFF\xD8" + b"".join(merged_segs) + (dst_tail or b"")

    def run(self):
        ok_all = True
        msg = ""
        exif_failed = False
        total = len(self.file_paths)
        readonly_files = []
        bad_files = []
        meta_map = {}
        try:
            meta_map = _get_tags_multi_merged(self.file_paths, WATERMARK_TAG_READ_LIST, timeout=20)
        except Exception:
            try:
                LogManager.instance().warning("[Watermark] 读取拍摄数据失败")
            except Exception:
                pass
            meta_map = {}
        for i, p in enumerate(self.file_paths):
            self.signals.progress.emit(i + 1, total, os.path.basename(p))
            try:
                if not p or not os.path.exists(p):
                    ok_all = False
                    bad_files.append(p)
                    continue
                try:
                    if not os.access(p, os.W_OK):
                        ok_all = False
                        readonly_files.append(p)
                        continue
                except Exception:
                    pass
                data = np.fromfile(p, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if img is None:
                    ok_all = False
                    bad_files.append(p)
                    continue
                angle_offset = 0.0
                try:
                    if self.auto_rotate and self.ref_is_landscape is not None:
                        cur_is_landscape = bool(int(img.shape[1]) >= int(img.shape[0]))
                        if bool(cur_is_landscape) != bool(self.ref_is_landscape):
                            angle_offset = 90.0 if bool(self.ref_is_landscape) else -90.0
                except Exception:
                    angle_offset = 0.0
                meta = meta_map.get(p) if isinstance(meta_map, dict) else None
                meta = _fill_meta_from_exifread(p, meta)
                meta = _fill_meta_from_db(p, meta)
                out = self._compose_on_image(img, self.states, angle_offset=angle_offset, meta=meta)
                is_modified = True
                try:
                    # 这里用像素级对比判断是否真的对图片产生了改动
                    # 目的：避免“没有改动水印但仍触发缩略图刷新/缓存失效”的体验问题
                    is_modified = not np.array_equal(out, img)
                except Exception:
                    is_modified = True
                if not is_modified:
                    try:
                        self.unchanged_paths.append(p)
                    except Exception:
                        pass
                    continue
                try:
                    self.changed_paths.append(p)
                except Exception:
                    pass
                enc, ext = self._imencode_like_original(p, out)
                if not enc:
                    ok_all = False
                    bad_files.append(p)
                    continue
                try:
                    tmp_dir = os.path.dirname(p)
                    if not tmp_dir:
                        tmp_dir = tempfile.gettempdir()
                except Exception:
                    tmp_dir = tempfile.gettempdir()
                tmp_fd = None
                tmp_path = ""
                try:
                    tmp_fd, tmp_path = tempfile.mkstemp(prefix="bmp_wm_", suffix=str(ext), dir=tmp_dir)
                except Exception:
                    tmp_fd, tmp_path = tempfile.mkstemp(prefix="bmp_wm_", suffix=str(ext))
                try:
                    if tmp_fd is not None:
                        os.close(tmp_fd)
                except Exception:
                    pass
                with open(tmp_path, "wb") as wf:
                    wf.write(enc)
                if not self._copy_exif(p, tmp_path):
                    exif_failed = True
                os.replace(tmp_path, p)
            except PermissionError:
                ok_all = False
                msg = "存在只读文件，写入失败"
            except Exception:
                try:
                    import traceback
                    LogManager.instance().error(traceback.format_exc())
                except Exception:
                    pass
                try:
                    LogManager.instance().warning(f"[Watermark] 写入失败: {p}")
                except Exception:
                    pass
                ok_all = False
        if readonly_files and not msg:
            msg = "存在只读文件，写入失败"
        if bad_files and not msg:
            msg = "存在损坏或无法读取的图片"
        if total == 1 and not ok_all and not msg:
            msg = "图片写入失败"
        if ok_all and not msg and exif_failed:
            msg = "处理完成，但Exif工具不可用或复制失败（已写入水印）"
        if ok_all and not msg:
            try:
                if not (self.changed_paths or []):
                    msg = "未检测到水印改动"
            except Exception:
                pass
        self.signals.finished.emit(ok_all, msg or ("处理完成" if ok_all else "部分图片处理失败"))


class _WatermarkSaveCopySignals(QObject):
    finished = pyqtSignal(bool, str, str, object)


class _WatermarkSaveCopyTask(_WatermarkBatchTask):
    def __init__(
        self,
        src_path: str,
        dst_path: str,
        states: List[WatermarkState],
        ref_is_landscape: bool | None = None,
        auto_rotate: bool = False,
        preview_max_edge: int = 1600,
    ):
        super().__init__([str(dst_path or "")], states, ref_is_landscape=ref_is_landscape, auto_rotate=auto_rotate, preview_max_edge=preview_max_edge)
        self.src_path = str(src_path or "")
        self.dst_path = str(dst_path or "")
        self.signals = _WatermarkSaveCopySignals()

    def run(self):
        ok = True
        msg = ""
        img = None
        meta = {}
        src_record = None
        if not self.src_path or not os.path.exists(self.src_path):
            ok = False
            msg = "源文件不存在"
        if ok:
            try:
                dst_dir = os.path.dirname(self.dst_path)
                if dst_dir:
                    os.makedirs(dst_dir, exist_ok=True)
            except Exception:
                pass
            try:
                shutil.copy2(self.src_path, self.dst_path)
            except Exception:
                ok = False
                msg = "复制失败"
        if ok:
            try:
                meta_map = _get_tags_multi_merged([self.src_path], WATERMARK_TAG_READ_LIST, timeout=20)
                if isinstance(meta_map, dict):
                    meta = meta_map.get(self.src_path) or {}
            except Exception:
                try:
                    LogManager.instance().warning("[Watermark] 读取拍摄数据失败")
                except Exception:
                    pass
                meta = {}
            try:
                meta = _fill_meta_from_db(self.src_path, meta)
            except Exception:
                pass
            try:
                db = BirdLibraryDB()
                uuid_key = str(EXIF_TAG.Uuid.value)
                fastid_key = str(EXIF_TAG.Fastid.value)
                src_uuid = _first_non_empty(meta.get(uuid_key), meta.get("Uuid"))
                if src_uuid:
                    src_record = db.get_result_by_uuid(str(src_uuid).strip(), table_name="bird_results") or db.get_result_by_uuid(str(src_uuid).strip(), table_name="import_cache")
                if not src_record:
                    src_fastid = _first_non_empty(meta.get(fastid_key), meta.get("Fastid"), meta.get("FastId"))
                    if not src_fastid:
                        try:
                            src_fastid = get_fast_id(self.src_path)
                        except Exception:
                            src_fastid = None
                    if src_fastid:
                        try:
                            src_record = db.get_result_by_fast_id(str(src_fastid).strip(), table_name="bird_results") or db.get_result_by_fast_id(str(src_fastid).strip(), table_name="import_cache")
                        except Exception:
                            src_record = None
            except Exception:
                src_record = None
        if ok:
            try:
                data = np.fromfile(self.dst_path, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if img is None:
                    ok = False
                    msg = "图片读取失败"
                    _trace("decode_failed")
                else:
                    angle_offset = 0.0
                    try:
                        if self.auto_rotate and self.ref_is_landscape is not None:
                            cur_is_landscape = bool(int(img.shape[1]) >= int(img.shape[0]))
                            if bool(cur_is_landscape) != bool(self.ref_is_landscape):
                                angle_offset = 90.0 if bool(self.ref_is_landscape) else -90.0
                    except Exception:
                        angle_offset = 0.0
                    out = self._compose_on_image(img, self.states, angle_offset=angle_offset, meta=meta)
                    _trace("compose_ok")
                    enc, ext = self._imencode_like_original(self.dst_path, out)
                    if not enc:
                        ok = False
                        msg = "图片写入失败"
                        _trace("encode_failed")
                    else:
                        _trace("encode_ok", extra=f"ext={ext}")
                        try:
                            tmp_dir = os.path.dirname(self.dst_path)
                            if not tmp_dir:
                                tmp_dir = tempfile.gettempdir()
                        except Exception:
                            tmp_dir = tempfile.gettempdir()
                        tmp_fd = None
                        tmp_path = ""
                        try:
                            tmp_fd, tmp_path = tempfile.mkstemp(prefix="bmp_wm_", suffix=str(ext), dir=tmp_dir)
                        except Exception:
                            tmp_fd, tmp_path = tempfile.mkstemp(prefix="bmp_wm_", suffix=str(ext))
                        try:
                            if tmp_fd is not None:
                                os.close(tmp_fd)
                        except Exception:
                            pass
                        with open(tmp_path, "wb") as wf:
                            wf.write(enc)
                        _trace("tmp_write_ok", extra=f"tmp={tmp_path}")
                        self._copy_exif(self.src_path, tmp_path)
                        os.replace(tmp_path, self.dst_path)
                        _trace("replace_ok")
            except Exception:
                ok = False
                msg = "图片写入失败"
                _trace("exception")
        info = {}
        if ok:
            try:
                stat = os.stat(self.dst_path)
                create_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime))
                create_ts = float(stat.st_ctime)
                size_bytes = int(getattr(stat, "st_size", 0) or 0)
            except Exception:
                create_time = ""
                create_ts = 0.0
                size_bytes = 0
            try:
                w = int(img.shape[1]) if img is not None else 0
                h = int(img.shape[0]) if img is not None else 0
            except Exception:
                w = 0
                h = 0
            shot_time = _meta_first(meta, "DateTimeOriginal", "CreateDate", "MediaCreateDate", "SubSecDateTimeOriginal", "FileModifyDate")
            iso = _meta_first(meta, "ISO")
            fnumber = _meta_first(meta, "FNumber", "Aperture", "ApertureValue")
            shutter = _meta_first(meta, "ExposureTime", "ShutterSpeed", "ShutterSpeedValue")
            focal_length = _meta_first(meta, "FocalLength")
            camera_model = _meta_first(meta, "Model")
            lens_model = _meta_first(meta, "LensModel")
            location = _first_non_empty(meta.get(str(EXIF_TAG.Location.value)), _meta_first(meta, "Location"), meta.get("XMP:Location"))
            order_cls = _first_non_empty(meta.get(str(EXIF_TAG.OrderCls.value)), _meta_first(meta, "OrderCls"), _meta_first(meta, "Order"))
            family_cls = _first_non_empty(meta.get(str(EXIF_TAG.FamilyCls.value)), _meta_first(meta, "FamilyCls"), _meta_first(meta, "Family"))
            genus_cls = _first_non_empty(meta.get(str(EXIF_TAG.GenusCls.value)), _meta_first(meta, "GenusCls"), _meta_first(meta, "Genus"))
            species = _first_non_empty(meta.get(str(EXIF_TAG.SpeciesCls.value)), meta.get(str(EXIF_TAG.Object.value)), _meta_first(meta, "Species"))
            label = ""
            tags = ""
            is_favorite = 0
            rating = 0
            bbox = None
            focus_point = None
            position = ""
            focus_detect_json = ""
            area_ratio = 0.0
            pixel_count = 0
            eye_coordinates = None
            description = ""
            focus_distance = ""
            lat = 0.0
            lng = 0.0
            if isinstance(src_record, dict):
                try:
                    label = str(src_record.get("label") or "")
                except Exception:
                    label = ""
                try:
                    tags = str(src_record.get("tags") or "")
                except Exception:
                    tags = ""
                try:
                    is_favorite = int(src_record.get("is_favorite") or 0)
                except Exception:
                    is_favorite = 0
                try:
                    rating = int(src_record.get("rating") or 0)
                except Exception:
                    rating = 0
                try:
                    bbox = src_record.get("bbox")
                except Exception:
                    bbox = None
                try:
                    focus_point = src_record.get("focus_point")
                except Exception:
                    focus_point = None
                try:
                    position = str(src_record.get("position") or "")
                except Exception:
                    position = ""
                try:
                    focus_detect_json = str(src_record.get("focus_detect_json") or "")
                except Exception:
                    focus_detect_json = ""
                try:
                    area_ratio = float(src_record.get("area_ratio") or 0.0)
                except Exception:
                    area_ratio = 0.0
                try:
                    pixel_count = int(src_record.get("pixel_count") or 0)
                except Exception:
                    pixel_count = 0
                try:
                    eye_coordinates = src_record.get("eye_coordinates")
                except Exception:
                    eye_coordinates = None
                try:
                    description = str(src_record.get("description") or "")
                except Exception:
                    description = ""
                try:
                    focus_distance = str(src_record.get("focus_distance") or "")
                except Exception:
                    focus_distance = ""
                try:
                    lat = float(src_record.get("latitude") or 0.0)
                except Exception:
                    lat = 0.0
                try:
                    lng = float(src_record.get("longitude") or 0.0)
                except Exception:
                    lng = 0.0
                try:
                    location = _first_non_empty(str(src_record.get("location") or ""), location)
                except Exception:
                    pass
                try:
                    order_cls = _first_non_empty(str(src_record.get("order_cls") or ""), order_cls)
                    family_cls = _first_non_empty(str(src_record.get("family_cls") or ""), family_cls)
                    genus_cls = _first_non_empty(str(src_record.get("genus_cls") or ""), genus_cls)
                    species = _first_non_empty(str(src_record.get("species_cls") or ""), species)
                except Exception:
                    pass
                try:
                    shot_time = _first_non_empty(str(src_record.get("shot_time") or ""), shot_time)
                except Exception:
                    pass
                try:
                    fnumber = _first_non_empty(str(src_record.get("fnumber") or ""), fnumber)
                except Exception:
                    pass
                try:
                    shutter = _first_non_empty(str(src_record.get("shutter") or ""), shutter)
                except Exception:
                    pass
                try:
                    iso = _first_non_empty(str(src_record.get("iso") or ""), iso)
                except Exception:
                    pass
                try:
                    focal_length = _first_non_empty(str(src_record.get("focal_length") or ""), focal_length)
                except Exception:
                    pass
                try:
                    camera_model = _first_non_empty(str(src_record.get("camera_model") or ""), camera_model)
                except Exception:
                    pass
                try:
                    lens_model = _first_non_empty(str(src_record.get("lens_model") or ""), lens_model)
                except Exception:
                    pass
            new_uuid = get_unique_id()
            dst_fastid = None
            try:
                dst_fastid = get_fast_id(self.dst_path)
            except Exception:
                dst_fastid = None
            try:
                imported_at_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            except Exception:
                imported_at_now = ""
            db = BirdLibraryDB()
            db_err = ""
            try:
                db.save_results_batch(
                    [
                        {
                            "uuid": new_uuid,
                            "fast_id": dst_fastid,
                            "path": self.dst_path,
                            "file": os.path.basename(self.dst_path),
                            "shot_time": shot_time,
                            "order_cls": order_cls,
                            "family_cls": family_cls,
                            "genus_cls": genus_cls,
                            "species_cls": species,
                            "label": label,
                            "score": 0.0,
                            "norm_score": 0,
                            "bbox": bbox,
                            "position": position,
                            "pixel_count": pixel_count,
                            "area_ratio": area_ratio,
                            "focus_point": focus_point,
                            "object": species,
                            "eye_coordinates": eye_coordinates,
                            "description": description,
                            "focus_detect_json": focus_detect_json,
                            "is_favorite": is_favorite,
                            "rating": rating,
                            "fnumber": float(fnumber or 0.0),
                            "shutter": shutter,
                            "iso": float(iso or 0),
                            "focal_length": focal_length,
                            "camera_model": camera_model,
                            "lens_model": lens_model,
                            "focus_distance": focus_distance,
                            "latitude": lat,
                            "longitude": lng,
                            "location": location,
                            "tags": tags,
                            "imported_at": imported_at_now,
                        }
                    ],
                    table_name="bird_results",
                )
            except Exception:
                try:
                    import traceback
                    db_err = traceback.format_exc()
                except Exception:
                    db_err = ""
                try:
                    LogManager.instance().warning("[Watermark] 另存入库失败")
                except Exception:
                    pass
            exif_err = ""
            try:
                worker = ExifHandleWorker.get_instance()
            except Exception:
                worker = None
            if worker is not None:
                try:
                    tag_map = {
                        str(EXIF_TAG.Uuid.value): str(new_uuid),
                        str(EXIF_TAG.Fastid.value): str(dst_fastid or ""),
                        str(EXIF_TAG.Object.value): str(species or ""),
                        str(EXIF_TAG.OrderCls.value): str(order_cls or ""),
                        str(EXIF_TAG.FamilyCls.value): str(family_cls or ""),
                        str(EXIF_TAG.GenusCls.value): str(genus_cls or ""),
                        str(EXIF_TAG.SpeciesCls.value): str(species or ""),
                        str(EXIF_TAG.Location.value): str(location or ""),
                        str(EXIF_TAG.Tags.value): str(tags or ""),
                        str(EXIF_TAG.Label.value): str(label or ""),
                        str(EXIF_TAG.Rating.value): str(int(rating or 0)),
                        str(EXIF_TAG.Favorite.value): str(int(is_favorite or 0)),
                    }
                    worker.write_tags(self.dst_path, tag_map)
                except Exception:
                    try:
                        import traceback
                        exif_err = traceback.format_exc()
                    except Exception:
                        exif_err = ""
            if (db_err or exif_err) and not msg:
                msg = "另存完成，但入库或Exif写入存在异常"
            info = {
                "path": self.dst_path,
                "name": os.path.basename(self.dst_path),
                "create_time": create_time,
                "create_ts": create_ts,
                "shot_time": shot_time,
                "shot_ts": create_ts,
                "size": size_bytes,
                "width": w,
                "height": h,
                "position": position,
                "score": 0,
                "norm_score": 0,
                "bbox": bbox,
                "focus_point": focus_point,
                "focus_detect_json": focus_detect_json,
                "label": label,
                "order": order_cls or "",
                "family": family_cls or "",
                "genus": genus_cls or "",
                "species": species or os.path.basename(os.path.dirname(self.dst_path)),
                "is_favorite": is_favorite,
                "rating": rating,
                "uuid": new_uuid,
                "fnumber": fnumber,
                "shutter": shutter,
                "iso": iso,
                "focal_length": focal_length,
                "camera_model": camera_model,
                "lens_model": lens_model,
                "tags": tags,
                "location": location,
            }
        self.signals.finished.emit(ok, msg or ("另存完成" if ok else "另存失败"), self.dst_path, info)


class _MetaLoadSignals(QObject):
    loaded = pyqtSignal(dict)


class _MetaLoadTask(QRunnable):
    def __init__(self, file_paths: List[str]):
        super().__init__()
        self.file_paths = [str(p) for p in (file_paths or []) if p]
        self.signals = _MetaLoadSignals()

    def run(self):
        out = {}
        try:
            out = _get_tags_multi_merged(self.file_paths, WATERMARK_TAG_READ_LIST, timeout=20)
        except Exception:
            try:
                LogManager.instance().warning("[Watermark] 读取拍摄数据失败")
            except Exception:
                pass
            out = {}
        if not isinstance(out, dict):
            out = {}
        try:
            for p in (self.file_paths or []):
                if not p:
                    continue
                meta = out.get(p, {})
                filled = _fill_meta_from_exifread(p, meta)
                filled = _fill_meta_from_db(p, filled)
                out[p] = filled
                if not _first_non_empty(_meta_first(filled, "ISO", "ISOSpeedRatings", "PhotographicSensitivity")):
                    try:
                        LogManager.instance().debug(f"[Watermark] ISO仍为空: {os.path.basename(p)}")
                    except Exception:
                        pass
        except Exception:
            pass
        self.signals.loaded.emit(out)


class _PreviewLoadSignals(QObject):
    loaded = pyqtSignal(str, object, object, int)


class _PreviewLoadTask(QRunnable):
    def __init__(self, path: str, max_edge: int, seq: int):
        super().__init__()
        self.path = str(path or "")
        self.max_edge = int(max_edge)
        self.seq = int(seq)
        self.signals = _PreviewLoadSignals()

    def run(self):
        qimg = QImage()
        ref_landscape = None
        try:
            qimg, ref_landscape = _load_preview_qimage(self.path, self.max_edge)
        except Exception:
            qimg, ref_landscape = QImage(), None
        if isinstance(qimg, QImage) and not qimg.isNull():
            self.signals.loaded.emit(self.path, qimg, ref_landscape, self.seq)
            return
        try:
            img = load_image(self.path)
        except Exception:
            img = None
        if img is None:
            self.signals.loaded.emit(self.path, QImage(), ref_landscape, self.seq)
            return
        try:
            h, w = img.shape[:2]
            try:
                ref_landscape = bool(int(w) >= int(h))
            except Exception:
                ref_landscape = None
            sw, sh = _scale_long_edge(w, h, self.max_edge)
            if sw != w or sh != h:
                img = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
            qimg = _cv_to_qimage_bgr(img)
        except Exception:
            qimg = QImage()
        self.signals.loaded.emit(self.path, qimg, ref_landscape, self.seq)


class _TextPatchRenderSignals(QObject):
    rendered = pyqtSignal(str, int, object)


class _TextPatchRenderTask(QRunnable):
    def __init__(self, wm_id: str, token: int, payload: dict):
        super().__init__()
        self.wm_id = str(wm_id or "")
        self.token = int(token or 0)
        self.payload = payload if isinstance(payload, dict) else {}
        self.signals = _TextPatchRenderSignals()

    def run(self):
        patch = None
        try:
            patch = _render_text_patch_to_bgra(
                str(self.payload.get("text") or ""),
                str(self.payload.get("font_family") or ""),
                int(self.payload.get("font_px") or 24),
                bold=bool(self.payload.get("bold")),
                italic=bool(self.payload.get("italic")),
                underline=bool(self.payload.get("underline")),
                rgba=self.payload.get("rgba"),
                angle_deg=float(self.payload.get("angle_deg") or 0.0),
                supersample=int(self.payload.get("supersample") or 2),
                stroke_width=int(self.payload.get("stroke_width") or 0),
                stroke_rgba=self.payload.get("stroke_rgba"),
                shadow_offset=self.payload.get("shadow_offset"),
                shadow_rgba=self.payload.get("shadow_rgba"),
                shadow_range=self.payload.get("shadow_range"),
                shadow_style=self.payload.get("shadow_style"),
                mirror_gap_px=self.payload.get("mirror_gap_px"),
<<<<<<< HEAD
                mirror_angle_deg=self.payload.get("mirror_angle_deg"),
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
                stack_count=self.payload.get("stack_count"),
                stack_step_px=self.payload.get("stack_step_px"),
            )
        except Exception:
            patch = None
        try:
            self.signals.rendered.emit(str(self.wm_id), int(self.token), patch)
        except Exception:
            pass


class _ImageWatermarkRenderSignals(QObject):
    rendered = pyqtSignal(str, int, object)


class _ImageWatermarkRenderTask(QRunnable):
    def __init__(self, wm_id: str, token: int, src_path: str, payload: dict):
        super().__init__()
        self.wm_id = str(wm_id or "")
        self.token = int(token or 0)
        self.src_path = str(src_path or "")
        self.payload = payload if isinstance(payload, dict) else {}
        self.signals = _ImageWatermarkRenderSignals()

    def run(self):
        out = None
        try:
            qimg = QImage(str(self.src_path))
            if not isinstance(qimg, QImage) or qimg.isNull():
                raise RuntimeError("bad image")
            qimg = qimg.convertToFormat(QImage.Format.Format_ARGB32)
            keep_aspect = bool(self.payload.get("keep_aspect", True))
            target_w = int(max(1, int(self.payload.get("target_w", 1) or 1)))
            target_h = int(max(1, int(self.payload.get("target_h", 1) or 1)))
            if keep_aspect:
                qimg = qimg.scaledToWidth(int(target_w), Qt.TransformationMode.SmoothTransformation)
            else:
                qimg = qimg.scaled(int(target_w), int(target_h), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            try:
                me = bool(self.payload.get("mirror_effect", False))
            except Exception:
                me = False
            if me and not qimg.isNull():
                ptr = qimg.bits()
                ptr.setsize(qimg.sizeInBytes())
                arr = np.frombuffer(ptr, dtype=np.uint8).reshape((int(qimg.height()), int(qimg.width()), 4))
                bgra = arr.copy()
                try:
                    gap_px = int(self.payload.get("mirror_gap_px") or 0)
                except Exception:
                    gap_px = 0
                bgra2 = _apply_mirror_effect_bgra(
                    bgra,
                    strength=float(self.payload.get("mirror_strength", 0.6) or 0.6),
                    gap_px=int(gap_px),
                )
                qimg2 = QImage(bgra2.data, int(bgra2.shape[1]), int(bgra2.shape[0]), int(bgra2.strides[0]), QImage.Format.Format_ARGB32)
                qimg = qimg2.copy()
            out = qimg
        except Exception:
            out = None
        try:
            self.signals.rendered.emit(str(self.wm_id), int(self.token), out)
        except Exception:
            pass


class WatermarkDialog(BasePopupDialog):
    def __init__(self, parent=None, file_paths: Optional[List[str]] = None):
        super().__init__(parent=parent, title="添加水印", size=(980, 680), translucent_background=False)
        try:
            SettingsManager.instance().set("system/hide_subprocess_console", True)
        except Exception:
            pass
        try:
            global _TEXT_RENDER_SERVICE
            if _TEXT_RENDER_SERVICE is None or not isinstance(_TEXT_RENDER_SERVICE, _TextRenderService):
                _TEXT_RENDER_SERVICE = _TextRenderService()
        except Exception:
            pass
        self.file_paths = [str(p) for p in (file_paths or []) if p]
        self._index = 0
        self._preview_max_edge = 1600
        self._states: List[WatermarkState] = []
        self._selected_wm_id: str | None = None
        self._wm_items = {}
        self._base_pixmap_item = None
        self._preview_image_size = QSize(1, 1)
        self._ref_is_landscape = None
        self._meta_cache = {}
        self._preview_load_seq = 0
        self._preview_loading_seq = 0
        self._preview_loading_path = ""
        self._preview_need_fit_on_load = False
        self._meta_task = None
        self._save_copy_task = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._render_preview)
        self._text_debounce_timer = QTimer(self)
        self._text_debounce_timer.setSingleShot(True)
        self._text_debounce_timer.setInterval(120)
        self._text_debounce_timer.timeout.connect(self._commit_text_edit)
        self._pending_text_value = None
        self._thread_pool = QThreadPool()
        self._text_patch_signals = _TextPatchRenderSignals()
        self._text_patch_signals.rendered.connect(self._on_text_patch_rendered)
        self._pending_text_patch_jobs = {}
        self._text_patch_timer = QTimer(self)
        self._text_patch_timer.setSingleShot(True)
        self._text_patch_timer.setInterval(40)
        self._text_patch_timer.timeout.connect(self._flush_text_patch_jobs)
        self._image_wm_signals = _ImageWatermarkRenderSignals()
        self._image_wm_signals.rendered.connect(self._on_image_wm_rendered)
        self._batch_task = None
        self._wheel_filter = _IgnoreWheelFilter()
        # 记录用户是否显式点击过“保存/另存”，用于决定是否需要触发父页面的缩略图刷新逻辑
        # 说明：
        # - 历史上父页面在对话框关闭后无条件刷新缩略图，导致“未改动水印也触发缓存失效”
        # - 这里用“是否点击按钮”作为最直接的判据，符合当前产品预期
        self._user_clicked_write = False
        self._user_clicked_save_copy = False
        # 最近一次“保存/批处理”的变更结果，供父页面在必要时做精确刷新
        self._last_changed_paths = []
        self._last_unchanged_paths = []
        self._scene_interacting = False
        self._pending_render = False
        self._slider_interacting = False
        self._pending_slider_render = False
        self._pending_render_hidden = False
        self._syncing_ui = False
        self._preview_zoom = 1.0
        self._fit_transform = None
        # 先隐藏预览区域，避免初始化时的黑色闪烁
        self._preview_hidden = True
        self._build_ui()
        self._default_font_family = self._load_default_font_family()
        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()
        self._start_load_meta()
        self._ensure_default_watermark()

    def showEvent(self, event):
        try:
            super().showEvent(event)
        except Exception:
            pass
        try:
            if bool(getattr(self, "_first_show_done", False)):
                return
        except Exception:
            return
        self._first_show_done = True
        try:
            self._adjust_panel_width()
        except Exception:
            pass
        try:
            self._adjust_preview_area_width()
        except Exception:
            pass
        try:
            self._show_preview_delayed()
        except Exception:
            pass

    def resizeEvent(self, event):
        """
        窗口尺寸变化时，跟随调整预览区域的宽度，避免图片区空白过大。

        说明：
        - 预览区使用 QGraphicsView 居中显示图片，若左侧面板过宽会造成大量空白
        - 该窗口的分割条被锁定（不可手动拖拽），因此需要在 resize 时自动重新分配宽度
        """
        try:
            super().resizeEvent(event)
        except Exception:
            pass
        try:
            self._adjust_preview_area_width()
        except Exception:
            pass

    def _build_ui(self):
        self.splitter = _LockedSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        try:
            self.splitter.setHandleWidth(0)
        except Exception:
            pass
        self.content_layout.addWidget(self.splitter, 1)
        try:
            self.splitter.setStretchFactor(0, 4)
            self.splitter.setStretchFactor(1, 1)
        except Exception:
            pass

        self.preview_root = QWidget()
        preview_layout = QVBoxLayout(self.preview_root)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)

        top_bar = QWidget()
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        top_bar_layout.setSpacing(10)

        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(qta.icon("mdi6.chevron-left", color="white"))
        self.btn_prev.setIconSize(QSize(26, 26))
        self.btn_prev.setFixedSize(40, 34)
        self.btn_prev.clicked.connect(self._prev_image)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(qta.icon("mdi6.chevron-right", color="white"))
        self.btn_next.setIconSize(QSize(26, 26))
        self.btn_next.setFixedSize(40, 34)
        self.btn_next.clicked.connect(self._next_image)

        self.lbl_index = QLabel("0/0")
        self.lbl_index.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_bar_layout.addWidget(self.btn_prev)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self.lbl_index)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self.btn_next)
        preview_layout.addWidget(top_bar)

        zoom_bar = QWidget()
        zoom_bar_layout = QHBoxLayout(zoom_bar)
        zoom_bar_layout.setContentsMargins(0, 0, 0, 0)
        zoom_bar_layout.setSpacing(10)
        zoom_bar_layout.addWidget(QLabel("预览缩放"))
        self.slider_preview_zoom = QSlider(Qt.Orientation.Horizontal)
        self.slider_preview_zoom.setRange(25, 400)
        self.slider_preview_zoom.setValue(100)
        self.slider_preview_zoom.valueChanged.connect(self._on_preview_zoom_changed)
        self.slider_preview_zoom.sliderPressed.connect(lambda: self._on_slider_interaction(True))
        self.slider_preview_zoom.sliderReleased.connect(lambda: self._on_slider_interaction(False))
        zoom_bar_layout.addWidget(self.slider_preview_zoom, 1)
        self.lbl_preview_zoom = QLabel("100%")
        zoom_bar_layout.addWidget(self.lbl_preview_zoom)
        preview_layout.addWidget(zoom_bar)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 设置背景为透明，避免初始化时显示黑色
        self.view.setStyleSheet("background: transparent; border: none;")
        self.view.setBackgroundBrush(QBrush(Qt.BrushStyle.NoBrush))
        try:
            self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
            self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
            self.view.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
            self.view.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        except Exception:
            pass
        preview_layout.addWidget(self.view, 1)

        self.splitter.addWidget(self.preview_root)

        self.panel_root = QWidget()
        try:
            self.panel_root.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        except Exception:
            pass
        panel_layout = QVBoxLayout(self.panel_root)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)

        self.group_type = self._make_group("水印类型选择")
        type_layout = QVBoxLayout(self.group_type["body"])
        type_layout.setContentsMargins(10, 10, 10, 10)
        type_layout.setSpacing(8)
        self.combo_kind = QComboBox()
        self.combo_kind.addItem("文字水印", "text")
        self.combo_kind.addItem("图片水印", "image")
        self.combo_kind.currentIndexChanged.connect(self._on_kind_changed)
        type_layout.addWidget(self.combo_kind)
        panel_layout.addWidget(self.group_type["root"])

        self.group_preset = self._make_group("水印方案")
        preset_layout = QHBoxLayout(self.group_preset["body"])
        preset_layout.setContentsMargins(10, 10, 10, 10)
        preset_layout.setSpacing(8)
        self.btn_save_preset = QPushButton("保存方案")
        self.btn_save_preset.clicked.connect(self._save_preset_clicked)
        self.btn_load_preset = QPushButton("加载方案")
        self.btn_load_preset.clicked.connect(self._load_preset_clicked)
        preset_layout.addWidget(self.btn_save_preset)
        preset_layout.addWidget(self.btn_load_preset)
        preset_layout.addStretch()
        panel_layout.addWidget(self.group_preset["root"])

        self.group_basic = self._make_group("基础属性")
        basic_layout = QVBoxLayout(self.group_basic["body"])
        basic_layout.setContentsMargins(10, 10, 10, 10)
        basic_layout.setSpacing(10)

        self.row_text = QWidget()
        row_text_layout = QVBoxLayout(self.row_text)
        row_text_layout.setContentsMargins(0, 0, 0, 0)
        row_text_layout.setSpacing(8)
        row_text_top = QWidget()
        row_text_top_layout = QHBoxLayout(row_text_top)
        row_text_top_layout.setContentsMargins(0, 0, 0, 0)
        row_text_top_layout.setSpacing(8)
        row_text_top_layout.addWidget(QLabel("文字"))
        row_text_top_layout.addStretch(1)
        self.edit_text = QPlainTextEdit()
        self.edit_text.setPlainText("水印")
        self.edit_text.setPlaceholderText("可输入文字并用 {拍摄时间} 等标签")
        self.edit_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.edit_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.edit_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit_text.textChanged.connect(self._on_text_changed)
        try:
            fm = self.edit_text.fontMetrics()
            self.edit_text.setFixedHeight(int(fm.height() * 2 + 16))
        except Exception:
            pass
        self._tag_items = list(WATERMARK_TAG_ITEMS)
        self._tag_label_to_key = dict(WATERMARK_TAG_LABEL_TO_KEY)
        self._tag_key_to_label = dict(WATERMARK_TAG_KEY_TO_LABEL)
        self._tag_key_set = set(WATERMARK_TAG_KEY_SET)
        self.combo_tag_insert = QComboBox()
        for label, key in self._tag_items:
            self.combo_tag_insert.addItem(label, key)
        try:
            self.combo_tag_insert.activated[int].connect(self._on_tag_insert_activated)
        except Exception:
            self.combo_tag_insert.activated.connect(self._on_tag_insert_activated)
        try:
            self.combo_tag_insert.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.combo_tag_insert.setMinimumContentsLength(6)
        except Exception:
            pass
        row_text_top_layout.addWidget(self.combo_tag_insert)
        row_text_layout.addWidget(row_text_top)
        row_text_layout.addWidget(self.edit_text)
        basic_layout.addWidget(self.row_text)
        self._update_tag_combo_width()

        self.row_font = QWidget()
        row_font_layout = QHBoxLayout(self.row_font)
        row_font_layout.setContentsMargins(0, 0, 0, 0)
        row_font_layout.setSpacing(8)
        row_font_layout.addWidget(QLabel("字体"))
        self.btn_pick_font = QPushButton("选择字体文件")
        self.btn_pick_font.clicked.connect(self._pick_font_file)
        row_font_layout.addWidget(self.btn_pick_font)
        self.lbl_font = QLabel("")
        try:
            self.lbl_font.setWordWrap(True)
            self.lbl_font.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        except Exception:
            pass
        row_font_layout.addWidget(self.lbl_font, 1)
        basic_layout.addWidget(self.row_font)

        self.row_font_size = QWidget()
        row_fs_layout = QHBoxLayout(self.row_font_size)
        row_fs_layout.setContentsMargins(0, 0, 0, 0)
        row_fs_layout.setSpacing(8)
        row_fs_layout.addWidget(QLabel("大小"))
        self.btn_font_minus = QPushButton("-")
        try:
            self.btn_font_minus.setFixedSize(28, 28)
        except Exception:
            pass
        row_fs_layout.addWidget(self.btn_font_minus)
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(10, 9999)
        self.spin_font_size.setValue(36)
        self.spin_font_size.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_font_size.valueChanged.connect(self._on_font_size_changed)
        try:
            le = self.spin_font_size.lineEdit()
            if le is not None:
                le.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            pass
        try:
            self.spin_font_size.setFixedWidth(96)
        except Exception:
            pass
        row_fs_layout.addWidget(self.spin_font_size)
        self.btn_font_plus = QPushButton("+")
        try:
            self.btn_font_plus.setFixedSize(28, 28)
        except Exception:
            pass
        row_fs_layout.addWidget(self.btn_font_plus)
        self.btn_font_minus.clicked.connect(lambda: self.spin_font_size.setValue(int(max(self.spin_font_size.minimum(), self.spin_font_size.value() - 1))))
        self.btn_font_plus.clicked.connect(lambda: self.spin_font_size.setValue(int(min(self.spin_font_size.maximum(), self.spin_font_size.value() + 1))))
        row_fs_layout.addStretch()
        basic_layout.addWidget(self.row_font_size)

        self.row_font_style = QWidget()
        row_style_layout = QHBoxLayout(self.row_font_style)
        row_style_layout.setContentsMargins(0, 0, 0, 0)
        row_style_layout.setSpacing(8)
        row_style_layout.addWidget(QLabel("样式"))
        self.chk_font_bold = QCheckBox("加粗")
        self.chk_font_italic = QCheckBox("斜体")
        self.chk_font_underline = QCheckBox("下划线")
        self.chk_font_bold.stateChanged.connect(self._on_font_style_changed)
        self.chk_font_italic.stateChanged.connect(self._on_font_style_changed)
        self.chk_font_underline.stateChanged.connect(self._on_font_style_changed)
        row_style_layout.addWidget(self.chk_font_bold)
        row_style_layout.addWidget(self.chk_font_italic)
        row_style_layout.addWidget(self.chk_font_underline)
        row_style_layout.addStretch()
        basic_layout.addWidget(self.row_font_style)

        self.row_color = QWidget()
        row_color_layout = QHBoxLayout(self.row_color)
        row_color_layout.setContentsMargins(0, 0, 0, 0)
        row_color_layout.setSpacing(8)
        row_color_layout.addWidget(QLabel("颜色"))
        self.btn_pick_color = QPushButton("选择颜色")
        self.btn_pick_color.clicked.connect(self._pick_color)
        row_color_layout.addWidget(self.btn_pick_color)
        self.color_preview = QLabel("")
        self.color_preview.setFixedSize(22, 22)
        try:
            self.color_preview.setCursor(Qt.CursorShape.PointingHandCursor)
            self.color_preview.mousePressEvent = lambda _e: self._pick_color()
            self.btn_pick_color.setVisible(False)
        except Exception:
            pass
        row_color_layout.addWidget(self.color_preview)
        self.lbl_color = QLabel("")
        try:
            self.lbl_color.setWordWrap(True)
            self.lbl_color.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        except Exception:
            pass
        row_color_layout.addWidget(self.lbl_color, 1)
        basic_layout.addWidget(self.row_color)

        self.row_auto_color = QWidget()
        row_auto_layout = QHBoxLayout(self.row_auto_color)
        row_auto_layout.setContentsMargins(0, 0, 0, 0)
        row_auto_layout.setSpacing(8)
        row_auto_layout.addWidget(QLabel("智能颜色"))
        self.chk_auto_color = QCheckBox("自动黑白")
        self.chk_auto_color.stateChanged.connect(self._on_auto_color_changed)
        row_auto_layout.addWidget(self.chk_auto_color)
        row_auto_layout.addStretch()
        basic_layout.addWidget(self.row_auto_color)

        self.row_stroke = QWidget()
        row_stroke_layout = QHBoxLayout(self.row_stroke)
        row_stroke_layout.setContentsMargins(0, 0, 0, 0)
        row_stroke_layout.setSpacing(8)
        row_stroke_layout.addWidget(QLabel("边框"))
        self.chk_stroke = QCheckBox("启用")
        self.chk_stroke.stateChanged.connect(self._on_stroke_changed)
        row_stroke_layout.addWidget(self.chk_stroke)
        row_stroke_layout.addWidget(QLabel("粗细"))
        self.spin_stroke_width = QSpinBox()
        self.spin_stroke_width.setRange(0, 20)
        self.spin_stroke_width.setValue(2)
        self.spin_stroke_width.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_stroke_width.valueChanged.connect(self._on_stroke_changed)
        try:
            self.spin_stroke_width.setFixedWidth(64)
        except Exception:
            pass
        row_stroke_layout.addWidget(self.spin_stroke_width)
        self.btn_pick_stroke_color = QPushButton("边框颜色")
        self.btn_pick_stroke_color.clicked.connect(self._pick_stroke_color)
        row_stroke_layout.addWidget(self.btn_pick_stroke_color)
        self.stroke_preview = QLabel("")
        self.stroke_preview.setFixedSize(22, 22)
        try:
            self.stroke_preview.setCursor(Qt.CursorShape.PointingHandCursor)
            self.stroke_preview.mousePressEvent = lambda _e: self._pick_stroke_color()
            self.btn_pick_stroke_color.setVisible(False)
        except Exception:
            pass
        row_stroke_layout.addWidget(self.stroke_preview)
        self.lbl_stroke = QLabel("")
        try:
            self.lbl_stroke.setWordWrap(True)
            self.lbl_stroke.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        except Exception:
            pass
        row_stroke_layout.addWidget(self.lbl_stroke, 1)
        basic_layout.addWidget(self.row_stroke)

        self.row_shadow = QWidget()
        row_shadow_layout = QVBoxLayout(self.row_shadow)
        row_shadow_layout.setContentsMargins(0, 0, 0, 0)
        row_shadow_layout.setSpacing(8)
        row_shadow_type = QWidget()
        row_shadow_type_layout = QHBoxLayout(row_shadow_type)
        row_shadow_type_layout.setContentsMargins(0, 0, 0, 0)
        row_shadow_type_layout.setSpacing(8)
        row_shadow_type_layout.addWidget(QLabel("阴影"))
        row_shadow_type_layout.addWidget(QLabel("类型"))
        self.combo_effect = QComboBox()
        self.combo_effect.addItem("无阴影", "none")
        self.combo_effect.addItem("光束阴影", "beam")
        self.combo_effect.addItem("镜像", "mirror")
        self.combo_effect.addItem("叠字", "stack")
        self.combo_effect.currentIndexChanged.connect(self._on_effect_changed)
        try:
            self.combo_effect.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.combo_effect.setMinimumContentsLength(6)
            self.combo_effect.setFixedWidth(140)
        except Exception:
            pass
        row_shadow_type_layout.addWidget(self.combo_effect)
        row_shadow_type_layout.addStretch(1)
        row_shadow_layout.addWidget(row_shadow_type)

        row_shadow_params = QWidget()
<<<<<<< HEAD
        row_shadow_params_layout = QVBoxLayout(row_shadow_params)
        row_shadow_params_layout.setContentsMargins(0, 0, 0, 0)
        row_shadow_params_layout.setSpacing(6)

        row_shadow_params_top = QWidget()
        row_shadow_params_top_layout = QHBoxLayout(row_shadow_params_top)
        row_shadow_params_top_layout.setContentsMargins(0, 0, 0, 0)
        row_shadow_params_top_layout.setSpacing(8)
        self.chk_shadow_follow = QCheckBox("跟随颜色")
        self.chk_shadow_follow.setChecked(False)
        self.chk_shadow_follow.stateChanged.connect(self._on_shadow_changed)
        row_shadow_params_top_layout.addWidget(self.chk_shadow_follow)
        self.lbl_shadow_dir = QLabel("方向")
        row_shadow_params_top_layout.addWidget(self.lbl_shadow_dir)
=======
        row_shadow_params_layout = QHBoxLayout(row_shadow_params)
        row_shadow_params_layout.setContentsMargins(0, 0, 0, 0)
        row_shadow_params_layout.setSpacing(8)
        self.chk_shadow_follow = QCheckBox("跟随颜色")
        self.chk_shadow_follow.setChecked(False)
        self.chk_shadow_follow.stateChanged.connect(self._on_shadow_changed)
        row_shadow_params_layout.addWidget(self.chk_shadow_follow)
        self.lbl_shadow_dir = QLabel("方向")
        row_shadow_params_layout.addWidget(self.lbl_shadow_dir)
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        self.combo_shadow_dir = QComboBox()
        for t in ("右下", "左下", "右上", "左上", "上", "下", "左", "右"):
            self.combo_shadow_dir.addItem(t, t)
        try:
            self.combo_shadow_dir.activated[int].connect(self._on_shadow_changed)
        except Exception:
            self.combo_shadow_dir.activated.connect(self._on_shadow_changed)
        try:
            self.combo_shadow_dir.setFixedWidth(84)
        except Exception:
            pass
<<<<<<< HEAD
        row_shadow_params_top_layout.addWidget(self.combo_shadow_dir)
        self.lbl_shadow_dist = QLabel("长度")
        row_shadow_params_top_layout.addWidget(self.lbl_shadow_dist)
=======
        row_shadow_params_layout.addWidget(self.combo_shadow_dir)
        self.lbl_shadow_dist = QLabel("长度")
        row_shadow_params_layout.addWidget(self.lbl_shadow_dist)
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        self.spin_shadow_dist = QSpinBox()
        self.spin_shadow_dist.setRange(0, 200)
        self.spin_shadow_dist.setValue(4)
        self.spin_shadow_dist.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_shadow_dist.valueChanged.connect(self._on_shadow_changed)
        try:
            self.spin_shadow_dist.setFixedWidth(64)
        except Exception:
            pass
<<<<<<< HEAD
        row_shadow_params_top_layout.addWidget(self.spin_shadow_dist)
        self.lbl_shadow_range = QLabel("模糊度")
        row_shadow_params_top_layout.addWidget(self.lbl_shadow_range)
=======
        row_shadow_params_layout.addWidget(self.spin_shadow_dist)
        self.lbl_shadow_range = QLabel("模糊度")
        row_shadow_params_layout.addWidget(self.lbl_shadow_range)
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        self.spin_shadow_range = QSpinBox()
        self.spin_shadow_range.setRange(0, 100)
        self.spin_shadow_range.setValue(0)
        self.spin_shadow_range.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_shadow_range.valueChanged.connect(self._on_shadow_changed)
        try:
            self.spin_shadow_range.setFixedWidth(64)
        except Exception:
            pass
<<<<<<< HEAD
        row_shadow_params_top_layout.addWidget(self.spin_shadow_range)
        self.lbl_stack_step = QLabel("间隔")
        row_shadow_params_top_layout.addWidget(self.lbl_stack_step)
=======
        row_shadow_params_layout.addWidget(self.spin_shadow_range)
        self.lbl_stack_step = QLabel("间隔")
        row_shadow_params_layout.addWidget(self.lbl_stack_step)
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        self.spin_stack_step = QSpinBox()
        self.spin_stack_step.setRange(0, 50)
        self.spin_stack_step.setValue(2)
        self.spin_stack_step.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_stack_step.valueChanged.connect(self._on_shadow_changed)
        try:
            self.spin_stack_step.setFixedWidth(64)
        except Exception:
            pass
<<<<<<< HEAD
        row_shadow_params_top_layout.addWidget(self.spin_stack_step)
        row_shadow_params_top_layout.addStretch(1)
        row_shadow_params_layout.addWidget(row_shadow_params_top)

        row_shadow_params_color = QWidget()
        row_shadow_params_color_layout = QHBoxLayout(row_shadow_params_color)
        row_shadow_params_color_layout.setContentsMargins(0, 0, 0, 0)
        row_shadow_params_color_layout.setSpacing(8)
        self.lbl_mirror_angle = QLabel("镜像夹角")
        row_shadow_params_color_layout.addWidget(self.lbl_mirror_angle)
        self.spin_mirror_angle = QSpinBox()
        self.spin_mirror_angle.setRange(0, 180)
        self.spin_mirror_angle.setValue(180)
        self.spin_mirror_angle.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_mirror_angle.valueChanged.connect(self._on_shadow_changed)
        try:
            self.spin_mirror_angle.setFixedWidth(64)
        except Exception:
            pass
        row_shadow_params_color_layout.addWidget(self.spin_mirror_angle)
        self.btn_pick_shadow_color = QPushButton("阴影颜色")
        self.btn_pick_shadow_color.clicked.connect(self._pick_shadow_color)
        row_shadow_params_color_layout.addWidget(self.btn_pick_shadow_color)
=======
        row_shadow_params_layout.addWidget(self.spin_stack_step)
        self.btn_pick_shadow_color = QPushButton("阴影颜色")
        self.btn_pick_shadow_color.clicked.connect(self._pick_shadow_color)
        row_shadow_params_layout.addWidget(self.btn_pick_shadow_color)
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        self.shadow_preview = QLabel("")
        self.shadow_preview.setFixedSize(22, 22)
        try:
            self.shadow_preview.setCursor(Qt.CursorShape.PointingHandCursor)
            self.shadow_preview.mousePressEvent = lambda _e: self._pick_shadow_color()
            self.btn_pick_shadow_color.setEnabled(False)
            self.btn_pick_shadow_color.setStyleSheet("border:none; background:transparent; padding:0px;")
        except Exception:
            pass
<<<<<<< HEAD
        row_shadow_params_color_layout.addWidget(self.shadow_preview)
        row_shadow_params_color_layout.addStretch(1)
        row_shadow_params_layout.addWidget(row_shadow_params_color)
=======
        row_shadow_params_layout.addWidget(self.shadow_preview)
        row_shadow_params_layout.addStretch(1)
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        row_shadow_layout.addWidget(row_shadow_params)
        self.lbl_shadow = QLabel("")
        try:
            self.lbl_shadow.setWordWrap(True)
            self.lbl_shadow.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        except Exception:
            pass
        row_shadow_layout.addWidget(self.lbl_shadow)
        basic_layout.addWidget(self.row_shadow)

        self.row_opacity = QWidget()
        row_op_layout = QHBoxLayout(self.row_opacity)
        row_op_layout.setContentsMargins(0, 0, 0, 0)
        row_op_layout.setSpacing(8)
        row_op_layout.addWidget(QLabel("透明度"))
        self.btn_opacity_minus = QPushButton("-")
        try:
            self.btn_opacity_minus.setFixedSize(28, 28)
        except Exception:
            pass
        self.btn_opacity_minus.clicked.connect(lambda: self.slider_opacity.setValue(int(max(0, self.slider_opacity.value() - 1))))
        row_op_layout.addWidget(self.btn_opacity_minus)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(80)
        self.slider_opacity.valueChanged.connect(self._on_opacity_slider_changed)
        self.slider_opacity.sliderPressed.connect(lambda: self._on_slider_interaction(True))
        self.slider_opacity.sliderReleased.connect(lambda: self._on_slider_interaction(False))
        row_op_layout.addWidget(self.slider_opacity, 1)
        self.btn_opacity_plus = QPushButton("+")
        try:
            self.btn_opacity_plus.setFixedSize(28, 28)
        except Exception:
            pass
        self.btn_opacity_plus.clicked.connect(lambda: self.slider_opacity.setValue(int(min(100, self.slider_opacity.value() + 1))))
        row_op_layout.addWidget(self.btn_opacity_plus)
        self.lbl_opacity = QLabel("80%")
        row_op_layout.addWidget(self.lbl_opacity)
        basic_layout.addWidget(self.row_opacity)

        self.row_rot = QWidget()
        row_rot_layout = QHBoxLayout(self.row_rot)
        row_rot_layout.setContentsMargins(0, 0, 0, 0)
        row_rot_layout.setSpacing(8)
        row_rot_layout.addWidget(QLabel("旋转"))
        self.btn_rotate_minus = QPushButton("-")
        try:
            self.btn_rotate_minus.setFixedSize(28, 28)
        except Exception:
            pass
        row_rot_layout.addWidget(self.btn_rotate_minus)
        self.slider_rotate = QSlider(Qt.Orientation.Horizontal)
        self.slider_rotate.setRange(-180, 180)
        self.slider_rotate.setValue(0)
        self.slider_rotate.valueChanged.connect(self._on_rotate_slider_changed)
        self.slider_rotate.sliderPressed.connect(lambda: self._on_slider_interaction(True))
        self.slider_rotate.sliderReleased.connect(lambda: self._on_slider_interaction(False))
        row_rot_layout.addWidget(self.slider_rotate, 1)
        self.btn_rotate_plus = QPushButton("+")
        try:
            self.btn_rotate_plus.setFixedSize(28, 28)
        except Exception:
            pass
        row_rot_layout.addWidget(self.btn_rotate_plus)
        self.spin_rotate = QSpinBox()
        self.spin_rotate.setRange(-180, 180)
        self.spin_rotate.setValue(0)
        self.spin_rotate.setSuffix("°")
        self.spin_rotate.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin_rotate.valueChanged.connect(self._on_rotate_spin_changed)
        try:
            self.spin_rotate.setFixedWidth(78)
        except Exception:
            pass
        row_rot_layout.addWidget(self.spin_rotate)
        self.btn_rotate_minus.clicked.connect(lambda: self.slider_rotate.setValue(int(max(self.slider_rotate.minimum(), self.slider_rotate.value() - 1))))
        self.btn_rotate_plus.clicked.connect(lambda: self.slider_rotate.setValue(int(min(self.slider_rotate.maximum(), self.slider_rotate.value() + 1))))
        basic_layout.addWidget(self.row_rot)

        self.row_image_size = QWidget()
        row_is_layout = QHBoxLayout(self.row_image_size)
        row_is_layout.setContentsMargins(0, 0, 0, 0)
        row_is_layout.setSpacing(8)
        row_is_layout.addWidget(QLabel("图片大小"))
        self.btn_image_size_minus = QPushButton("-")
        try:
            self.btn_image_size_minus.setFixedSize(28, 28)
        except Exception:
            pass
        row_is_layout.addWidget(self.btn_image_size_minus)
        self.slider_image_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_image_size.setRange(1, 100)
        self.slider_image_size.setValue(100)
        self.slider_image_size.valueChanged.connect(self._on_image_size_slider_changed)
        self.slider_image_size.sliderPressed.connect(lambda: self._on_slider_interaction(True))
        self.slider_image_size.sliderReleased.connect(lambda: self._on_slider_interaction(False))
        row_is_layout.addWidget(self.slider_image_size, 1)
        self.btn_image_size_plus = QPushButton("+")
        try:
            self.btn_image_size_plus.setFixedSize(28, 28)
        except Exception:
            pass
        row_is_layout.addWidget(self.btn_image_size_plus)
        self.lbl_image_size = QLabel("100%")
        row_is_layout.addWidget(self.lbl_image_size)
        self.btn_image_size_minus.clicked.connect(lambda: self.slider_image_size.setValue(int(max(1, self.slider_image_size.value() - 1))))
        self.btn_image_size_plus.clicked.connect(lambda: self.slider_image_size.setValue(int(min(100, self.slider_image_size.value() + 1))))
        basic_layout.addWidget(self.row_image_size)

        self.row_image = QWidget()
        row_img_layout = QHBoxLayout(self.row_image)
        row_img_layout.setContentsMargins(0, 0, 0, 0)
        row_img_layout.setSpacing(8)
        row_img_layout.addWidget(QLabel("图片"))
        self.btn_pick_image = QPushButton("选择SVG/PNG")
        self.btn_pick_image.clicked.connect(self._pick_image_file)
        row_img_layout.addWidget(self.btn_pick_image)
        self.lbl_image = QLabel("")
        try:
            self.lbl_image.setWordWrap(True)
            self.lbl_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        except Exception:
            pass
        row_img_layout.addWidget(self.lbl_image, 1)
        basic_layout.addWidget(self.row_image)

        panel_layout.addWidget(self.group_basic["root"])

        self.group_adv = self._make_group("高级设置")
        adv_layout = QVBoxLayout(self.group_adv["body"])
        adv_layout.setContentsMargins(10, 10, 10, 10)
        adv_layout.setSpacing(10)
        try:
            self.group_adv["root"].setVisible(False)
        except Exception:
            pass

        self.group_batch = self._make_group("批量操作")
        batch_layout = QVBoxLayout(self.group_batch["body"])
        batch_layout.setContentsMargins(10, 10, 10, 10)
        batch_layout.setSpacing(10)

        self.btn_apply_all = QPushButton("应用当前设置到所有图片")
        self.btn_apply_all.clicked.connect(self._apply_all_clicked)
        batch_layout.addWidget(self.btn_apply_all)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        try:
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(14)
        except Exception:
            pass
        try:
            self.progress.setVisible(False)
        except Exception:
            pass
        batch_layout.addWidget(self.progress)

        self.lbl_progress = QLabel("")
        batch_layout.addWidget(self.lbl_progress)
        try:
            self.lbl_progress.setVisible(False)
        except Exception:
            pass

        panel_layout.addWidget(self.group_batch["root"])

        self.group_layers = self._make_group("图层面板")
        layers_layout = QVBoxLayout(self.group_layers["body"])
        layers_layout.setContentsMargins(10, 10, 10, 10)
        layers_layout.setSpacing(8)

        layer_sel_row = QWidget()
        layer_sel_layout = QHBoxLayout(layer_sel_row)
        layer_sel_layout.setContentsMargins(0, 0, 0, 0)
        layer_sel_layout.setSpacing(8)
        self.btn_layer_all = QPushButton("全选")
        self.btn_layer_all.clicked.connect(lambda: self._set_all_layers_checked(True))
        self.btn_layer_none = QPushButton("全不选")
        self.btn_layer_none.clicked.connect(lambda: self._set_all_layers_checked(False))
        layer_sel_layout.addWidget(self.btn_layer_all)
        layer_sel_layout.addWidget(self.btn_layer_none)
        layer_sel_layout.addStretch()
        layers_layout.addWidget(layer_sel_row)

        self.list_layers = QListWidget()
        self.list_layers.currentItemChanged.connect(self._on_layer_selected)
        self.list_layers.itemChanged.connect(lambda _it: self._schedule_preview_update())
        layers_layout.addWidget(self.list_layers, 1)

        layer_btn_row = QWidget()
        layer_btn_layout = QHBoxLayout(layer_btn_row)
        layer_btn_layout.setContentsMargins(0, 0, 0, 0)
        layer_btn_layout.setSpacing(8)
        self.btn_add_layer = QPushButton("新增水印")
        self.btn_add_layer.clicked.connect(lambda: self._add_watermark("text"))
        self.btn_del = QPushButton("删除")
        self.btn_del.clicked.connect(self._delete_selected)
        self.btn_up = QPushButton("上移")
        self.btn_up.clicked.connect(lambda: self._move_layer(-1))
        self.btn_down = QPushButton("下移")
        self.btn_down.clicked.connect(lambda: self._move_layer(1))
        layer_btn_layout.addWidget(self.btn_add_layer)
        layer_btn_layout.addWidget(self.btn_del)
        layer_btn_layout.addWidget(self.btn_up)
        layer_btn_layout.addWidget(self.btn_down)
        layers_layout.addWidget(layer_btn_row)

        panel_layout.addWidget(self.group_layers["root"], 1)

        self.btn_reset = QPushButton("恢复默认设置")
        self.btn_reset.clicked.connect(self._reset_clicked)
        panel_layout.addWidget(self.btn_reset)

        self.panel_scroll = QScrollArea()
        self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.panel_scroll.setWidget(self.panel_root)
        self.splitter.addWidget(self.panel_scroll)
        try:
            self.splitter.setStretchFactor(0, 4)
            self.splitter.setStretchFactor(1, 1)
        except Exception:
            pass
        self.splitter.setSizes([700, 320])

        cancel_btn = QPushButton("关闭")
        self.btn_save_copy = QPushButton("另存")
        apply_btn = QPushButton("保存")
        try:
            cancel_btn.setFixedSize(110, 36)
            self.btn_save_copy.setFixedSize(110, 36)
            apply_btn.setFixedSize(110, 36)
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_save_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        except Exception:
            pass
        self.apply_dialog_button_style(cancel_btn, "secondary")
        self.apply_dialog_button_style(self.btn_save_copy, "secondary")
        self.apply_dialog_button_style(apply_btn, "primary")
        cancel_btn.clicked.connect(self.reject)
        self.btn_save_copy.clicked.connect(self._save_copy_clicked)
        apply_btn.clicked.connect(self._write_clicked)
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(self.btn_save_copy)
        self.bottom_layout.addWidget(apply_btn)

        self._copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
        self._copy_shortcut.activated.connect(self._copy_selected)
        self._paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        self._paste_shortcut.activated.connect(self._paste_to_new)
        self._install_wheel_filters()

    def _install_wheel_filters(self):
        for w in (
            self.combo_kind,
            self.combo_tag_insert,
            self.combo_effect,
            self.combo_shadow_dir,
            self.spin_font_size,
            getattr(self, "slider_preview_zoom", None),
            self.slider_opacity,
            self.slider_image_size,
            self.slider_rotate,
            self.spin_rotate,
        ):
            try:
                if w is None:
                    continue
                w.installEventFilter(self._wheel_filter)
            except Exception:
                pass

    def _adjust_panel_width(self):
        """
        根据参数区内容的实际宽度自适应右侧面板最小宽度。

        说明：
        - 参数区控件较多且会动态变化（例如标签下拉内容变更、按钮增加等）
        - 使用 sizeHint 计算一个“足够放下最宽行”的最小宽度，避免内容被挤压
        """
        try:
            root = getattr(self, "panel_root", None)
            scroll = getattr(self, "panel_scroll", None)
            splitter = getattr(self, "splitter", None)
            if root is None or scroll is None or splitter is None:
                return
            hint = int(root.sizeHint().width())
            # 参数区过宽会导致窗口整体变大、预览区空白增多
            # 这里给参数区设置一个更紧凑的上限，窗口宽度更多让给预览
            panel_w = int(max(320, min(520, hint + 40)))
            scroll.setMinimumWidth(panel_w)
            scroll.setMaximumWidth(panel_w)
        except Exception:
            pass

    def _adjust_preview_area_width(self):
        """
        根据当前预览图片在视图中的实际显示宽度，动态调整左侧预览区域宽度。

        目标：
        - 预览区宽度尽量贴近图片显示宽度（减少空白）
        - 右侧参数区保持足够宽度（避免控件被挤压）
        """
        try:
            splitter = getattr(self, "splitter", None)
            view = getattr(self, "view", None)
            panel_scroll = getattr(self, "panel_scroll", None)
            base_item = getattr(self, "_base_pixmap_item", None)
            if splitter is None or view is None or panel_scroll is None or base_item is None:
                return
            pix = base_item.pixmap() if hasattr(base_item, "pixmap") else QPixmap()
            if pix is None or pix.isNull():
                return
            total_w = int(splitter.width())
            if total_w <= 0:
                total_w = int(self.width())
            if total_w <= 0:
                return
            try:
                right_min = int(panel_scroll.minimumWidth())
            except Exception:
                right_min = 360
            right_min = int(max(320, right_min))
            try:
                tr = view.transform()
                scale = float(min(tr.m11(), tr.m22()))
            except Exception:
                scale = 1.0
            if scale <= 0:
                scale = 1.0
            shown_w = int(round(float(pix.width()) * float(scale)))
            # 为顶部栏/滚动条/边距预留空间
            desired_left = int(max(420, min(1200, shown_w + 80)))
            left_w = int(min(desired_left, max(420, total_w - right_min)))
            right_w = int(max(right_min, total_w - left_w))
            splitter.setSizes([int(left_w), int(right_w)])
        except Exception:
            pass

    def _load_default_font_family(self) -> str:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "siyuan"))
        candidates = [
            os.path.join(base_dir, "SourceHanSansCN-Medium#1.otf"),
            os.path.join(base_dir, "SourceHanSansCN-Medium.otf"),
        ]
        for p in candidates:
            if os.path.exists(p):
                fid = QFontDatabase.addApplicationFont(p)
                families = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
                if families:
                    return str(families[0])
        try:
            fams = QFontDatabase.families()
            for f in fams:
                if "Source Han Sans" in f or "思源黑体" in f:
                    return str(f)
        except Exception:
            pass
        return ""

    def _preset_dir(self) -> str:
        try:
            base = str(PathManager.instance().get_user_data_path() / "watermark")
        except Exception:
            base = os.path.join(os.getcwd(), "data", "watermark")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass
        try:
            legacy = str(PathManager.instance().get_app_data_path() / "watermark")
        except Exception:
            legacy = os.path.join(os.getcwd(), "data", "watermark")
        try:
            if os.path.isdir(legacy):
                for name in os.listdir(legacy):
                    if not str(name).lower().endswith(".bwm"):
                        continue
                    src = os.path.join(legacy, str(name))
                    dst = os.path.join(base, str(name))
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
        return base

    def _save_preset_clicked(self):
        from ui.widgets.custom_input_dialog import CustomInputDialog

        d = CustomInputDialog(self, "保存水印方案", "方案名称:", "")
        if not d.exec():
            return
        name = str(d.get_value() or "").strip()
        if not name:
            return
        if any(c in name for c in '<>:"/\\|?*'):
            NotificationManager.instance().show_warning("错误", "方案名称包含非法字符")
            return
        save_dir = self._preset_dir()
        fp = os.path.join(save_dir, f"{name}.bwm")
        if os.path.exists(fp):
            if not NotificationManager.instance().ask_confirmation("确认覆盖", f"方案 '{name}' 已存在，是否覆盖？"):
                return
        try:
            payload = {"states": [s.to_json() for s in (self._states or [])]}
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            NotificationManager.instance().show_toast("水印方案已保存", 1600, parent=self, position="top")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"保存失败: {e}")

    def _load_preset_clicked(self):
        save_dir = self._preset_dir()
        has_any = False
        try:
            has_any = bool([f for f in os.listdir(save_dir) if str(f).lower().endswith(".bwm")])
        except Exception:
            has_any = False
        if not has_any:
            NotificationManager.instance().show_toast("没有找到已保存的水印方案", 1600, parent=self, position="top")
            return
        dlg = WatermarkPresetLoadDialog(self, preset_dir=save_dir)
        if not dlg.exec():
            return
        fp = str(getattr(dlg, "selected_path", "") or "")
        if not fp:
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"加载失败: {e}")
            return
        if isinstance(data, list):
            states_raw = data
        else:
            states_raw = (data or {}).get("states") or []
        new_states = []
        for it in (states_raw or []):
            if not isinstance(it, dict):
                continue
            try:
                new_states.append(WatermarkState.from_json(it))
            except Exception:
                pass
        self._states = list(new_states or [])
        self.list_layers.clear()
        for s in (self._states or []):
            item = QListWidgetItem(str(s.name or "水印"))
            item.setData(Qt.ItemDataRole.UserRole, str(s.wm_id))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(Qt.CheckState.Checked if bool(s.visible) else Qt.CheckState.Unchecked)
            self.list_layers.addItem(item)
        if self.list_layers.count() > 0:
            self.list_layers.setCurrentRow(0)
            try:
                self._selected_wm_id = str(self.list_layers.item(0).data(Qt.ItemDataRole.UserRole) or "") or None
            except Exception:
                self._selected_wm_id = None
        else:
            self._selected_wm_id = None
        self._sync_ui_from_state()
        self._render_preview()

    def _make_group(self, title: str) -> dict:
        root = QFrame()
        root.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QPushButton(str(title or ""))
        header.setCheckable(True)
        header.setChecked(True)
        header.setCursor(Qt.CursorShape.PointingHandCursor)

        body = QWidget()
        body.setVisible(True)

        def _toggle():
            body.setVisible(bool(header.isChecked()))

        header.toggled.connect(lambda _v: _toggle())
        layout.addWidget(header)
        layout.addWidget(body)
        return {"root": root, "header": header, "body": body}

    def apply_theme_styles(self):
        cm = ColorManager.instance()
        nav_bg = cm.to_qss_color("image_detail.nav_button.background", default="#00000032")
        nav_hover_bg = cm.to_qss_color("image_detail.nav_button.hover_background", default="#00000064")
        for b in (self.btn_prev, self.btn_next):
            b.setStyleSheet(f"QPushButton {{ background-color: {nav_bg}; border: none; border-radius: 6px; }} QPushButton:hover {{ background-color: {nav_hover_bg}; }}")

        panel_bg = cm.get("theme.background.light", "#FFFFFF")
        border = cm.get("popup.border.primary", "#D0D0D0")
        text = cm.get("popup.text.primary", "#333333")
        text_dark = cm.get("theme.text.dark", "#000000")
        hover = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        hover_bg = cm.get("settings.shortcut_reset.hover_background", "#2196F31A")
        primary = cm.get("theme.primary", "#2196F3")
        scrollbar_bg = cm.get("settings.shortcut_table.header.background", "#F5F5F5")
        scrollbar_handle = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        scrollbar_hover = cm.get("settings.shortcut_table.row.hover_border", "#D7E3F5")
        arrow_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "icon", "line", "箭头下_arrow-down.svg"))
        arrow_url = QUrl.fromLocalFile(arrow_path).toString()
        for g in (self.group_type, self.group_preset, self.group_basic, self.group_adv, self.group_batch, self.group_layers):
            g["root"].setStyleSheet(f"QFrame{{background:{panel_bg}; border:1px solid {border}; border-radius:8px;}}")
            g["header"].setStyleSheet(
                f"QPushButton{{text-align:left; padding:8px 10px; background:transparent; border:none; color:{text}; font-weight:600;}}"
                f"QPushButton:hover{{background:{hover};}}"
            )
        self.list_layers.setStyleSheet(
            f"QListWidget{{border:1px solid {border}; border-radius:6px; background:{panel_bg};}}"
            f"QListWidget::item{{padding:6px; color:{text};}}"
            f"QListWidget::item:selected{{background:{hover_bg}; color:{text};}}"
        )
        for w in (self.edit_text,):
            try:
                w.setStyleSheet(
                    f"QPlainTextEdit{{border:1px solid #000000; border-radius:6px; background:{control_bg}; color:{text}; padding:6px 8px;}}"
                    f"QPlainTextEdit QScrollBar:vertical{{background:{scrollbar_bg}; width:10px;}}"
                    f"QPlainTextEdit QScrollBar::handle:vertical{{background:{scrollbar_handle}; min-height:30px;}}"
                    f"QPlainTextEdit QScrollBar::handle:vertical:hover{{background:{scrollbar_hover};}}"
                    f"QPlainTextEdit QScrollBar::add-line:vertical{{height:0px; background:transparent;}}"
                    f"QPlainTextEdit QScrollBar::sub-line:vertical{{height:0px; background:transparent;}}"
                    f"QPlainTextEdit QScrollBar::add-page:vertical{{background:transparent;}}"
                    f"QPlainTextEdit QScrollBar::sub-page:vertical{{background:transparent;}}"
                )
            except Exception:
                pass
        for cb in (self.combo_kind, self.combo_tag_insert, self.combo_effect):
            try:
                cb.setStyleSheet(
                    f"QComboBox{{padding:6px 10px; border:1px solid {border}; border-radius:6px; background:{control_bg}; color:{text};}}"
                    f"QComboBox:hover{{border:1px solid {primary};}}"
                    f"QComboBox::drop-down{{border:none; width:22px; background:transparent;}}"
                    f"QComboBox::down-arrow{{image:url({arrow_url}); width:12px; height:12px; margin-right:6px;}}"
                    f"QComboBox QAbstractItemView{{border:1px solid {border}; background:{panel_bg}; color:{text}; selection-background-color:{hover_bg};}}"
                    f"QComboBox QAbstractItemView QScrollBar:vertical{{background:{scrollbar_bg}; width:10px;}}"
                    f"QComboBox QAbstractItemView QScrollBar::handle:vertical{{background:{scrollbar_handle}; min-height:30px;}}"
                    f"QComboBox QAbstractItemView QScrollBar::handle:vertical:hover{{background:{scrollbar_hover};}}"
                    f"QComboBox QAbstractItemView QScrollBar::add-line:vertical{{height:0px; background:transparent;}}"
                    f"QComboBox QAbstractItemView QScrollBar::sub-line:vertical{{height:0px; background:transparent;}}"
                    f"QComboBox QAbstractItemView QScrollBar::add-page:vertical{{background:transparent;}}"
                    f"QComboBox QAbstractItemView QScrollBar::sub-page:vertical{{background:transparent;}}"
                )
            except Exception:
                pass
        try:
            self.spin_font_size.setStyleSheet(
                f"QSpinBox{{border:1px solid {border}; border-radius:6px; background:{control_bg}; color:{text}; padding:6px 8px;}}"
                f"QSpinBox:hover{{border:1px solid {primary};}}"
            )
        except Exception:
            pass
        try:
            self.spin_rotate.setStyleSheet(
                f"QSpinBox{{border:1px solid {border}; border-radius:6px; background:{control_bg}; color:{text}; padding:6px 8px;}}"
                f"QSpinBox:hover{{border:1px solid {primary};}}"
            )
        except Exception:
            pass
        try:
            self._update_tag_combo_width()
        except Exception:
            pass
        for b in (
            self.btn_save_preset,
            self.btn_load_preset,
            self.btn_pick_font,
            self.btn_pick_color,
            self.btn_pick_image,
            self.btn_apply_all,
            self.btn_save_copy,
            self.btn_add_layer,
            self.btn_del,
            self.btn_up,
            self.btn_down,
            self.btn_reset,
            self.btn_opacity_minus,
            self.btn_opacity_plus,
            self.btn_image_size_minus,
            self.btn_image_size_plus,
            self.btn_font_minus,
            self.btn_font_plus,
            self.btn_rotate_minus,
            self.btn_rotate_plus,
            self.btn_layer_all,
            self.btn_layer_none,
        ):
            try:
                b.setStyleSheet(
                    f"QPushButton{{border:1px solid {border}; border-radius:6px; background:{control_bg}; color:{text}; padding:6px 10px;}}"
                    f"QPushButton:hover{{background:{hover_bg}; border:1px solid {primary};}}"
                )
            except Exception:
                pass
        for b in (
            self.btn_opacity_minus,
            self.btn_opacity_plus,
            self.btn_image_size_minus,
            self.btn_image_size_plus,
            self.btn_font_minus,
            self.btn_font_plus,
            self.btn_rotate_minus,
            self.btn_rotate_plus,
        ):
            try:
                b.setStyleSheet(
                    f"QPushButton{{border:1px solid {border}; border-radius:6px; background:{control_bg}; color:{text}; padding:0px; font-size:16px; font-weight:600;}}"
                    f"QPushButton:hover{{background:{hover_bg}; border:1px solid {primary};}}"
                )
            except Exception:
                pass
        try:
            all_checks = list(self.content_widget.findChildren(QCheckBox))
        except Exception:
            all_checks = []
        for cb in (all_checks or []):
            try:
                cb.setStyleSheet(
                    f"QCheckBox{{color:{text}; spacing:6px;}}"
                    f"QCheckBox::indicator{{width:16px; height:16px; border-radius:4px; border:1px solid {border}; background:{control_bg};}}"
                    f"QCheckBox::indicator:hover{{border:1px solid {primary};}}"
                    f"QCheckBox::indicator:checked{{background:{primary}; border:1px solid {primary};}}"
                )
            except Exception:
                pass
        try:
            for lbl in self.content_widget.findChildren(QLabel):
                lbl.setStyleSheet("border:none; background:transparent;")
        except Exception:
            pass
        try:
            self.slider_opacity.setStyleSheet(
                f"QSlider::groove:horizontal{{height:6px; background:{border}; border-radius:3px;}}"
                f"QSlider::handle:horizontal{{width:12px; margin:-4px 0; background:{primary}; border-radius:6px;}}"
            )
            if hasattr(self, "slider_preview_zoom") and self.slider_preview_zoom is not None:
                self.slider_preview_zoom.setStyleSheet(
                    f"QSlider::groove:horizontal{{height:6px; background:{border}; border-radius:3px;}}"
                    f"QSlider::handle:horizontal{{width:12px; margin:-4px 0; background:{primary}; border-radius:6px;}}"
                )
            self.slider_image_size.setStyleSheet(
                f"QSlider::groove:horizontal{{height:6px; background:{border}; border-radius:3px;}}"
                f"QSlider::handle:horizontal{{width:12px; margin:-4px 0; background:{primary}; border-radius:6px;}}"
            )
            self.slider_rotate.setStyleSheet(
                f"QSlider::groove:horizontal{{height:6px; background:{border}; border-radius:3px;}}"
                f"QSlider::handle:horizontal{{width:12px; margin:-4px 0; background:{primary}; border-radius:6px;}}"
            )
        except Exception:
            pass
        try:
            self._adjust_panel_width()
        except Exception:
            pass
        try:
            self.progress.setStyleSheet(
                f"QProgressBar{{border:1px solid {border}; border-radius:6px; background:{control_bg}; color:{text}; text-align:center;}}"
                f"QProgressBar::chunk{{background:{primary}; border-radius:6px;}}"
            )
        except Exception:
            pass
        try:
            self.panel_scroll.setStyleSheet(
                f"QScrollArea{{background:transparent; border:none;}}"
                f"QScrollBar:vertical{{background:{scrollbar_bg}; width:10px;}}"
                f"QScrollBar::handle:vertical{{background:{scrollbar_handle}; min-height:30px;}}"
                f"QScrollBar::handle:vertical:hover{{background:{scrollbar_hover};}}"
            )
        except Exception:
            pass
        try:
            self.color_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:{control_bg};")
        except Exception:
            pass
        try:
            self.lbl_progress.setStyleSheet("border:none; background:transparent;")
        except Exception:
            pass
        try:
            self.lbl_index.setStyleSheet("border:none; background:transparent;")
        except Exception:
            pass
        try:
            if hasattr(self, "view") and self.view is not None:
                self.view.setStyleSheet(
                    f"QGraphicsView{{background: transparent; border: none;}}"
                    f"QScrollBar:vertical{{background:{scrollbar_bg}; width:10px;}}"
                    f"QScrollBar::handle:vertical{{background:{scrollbar_handle}; min-height:30px;}}"
                    f"QScrollBar::handle:vertical:hover{{background:{scrollbar_hover};}}"
                    f"QScrollBar::add-line:vertical{{height:0px; background:transparent;}}"
                    f"QScrollBar::sub-line:vertical{{height:0px; background:transparent;}}"
                    f"QScrollBar::add-page:vertical{{background:transparent;}}"
                    f"QScrollBar::sub-page:vertical{{background:transparent;}}"
                    f"QScrollBar:horizontal{{background:{scrollbar_bg}; height:10px;}}"
                    f"QScrollBar::handle:horizontal{{background:{scrollbar_handle}; min-width:30px;}}"
                    f"QScrollBar::handle:horizontal:hover{{background:{scrollbar_hover};}}"
                    f"QScrollBar::add-line:horizontal{{width:0px; background:transparent;}}"
                    f"QScrollBar::sub-line:horizontal{{width:0px; background:transparent;}}"
                    f"QScrollBar::add-page:horizontal{{background:transparent;}}"
                    f"QScrollBar::sub-page:horizontal{{background:transparent;}}"
                )
        except Exception:
            pass

    def _start_load_meta(self):
        if not self.file_paths:
            return
        task = _MetaLoadTask(self.file_paths)
        self._meta_task = task
        task.signals.loaded.connect(self._on_meta_loaded)
        self._thread_pool.start(task)

    def _on_meta_loaded(self, meta_map: dict):
        if not isinstance(meta_map, dict):
            meta_map = {}
        self._meta_cache = meta_map
        self._apply_text_mode_controls()
        self._schedule_preview_update()

    def _show_preview_delayed(self):
        """延迟显示预览区域，避免初始化时的黑色闪烁"""
        self._preview_hidden = False
        try:
            pending = bool(getattr(self, "_pending_render_hidden", False))
        except Exception:
            pending = False
        self._pending_render_hidden = False
        if pending:
            self._render_preview()
        else:
            self._render_preview()

    def _ensure_default_watermark(self):
        if self._states:
            return
        self._add_watermark("text")
        if self._states and getattr(self, "_default_font_family", ""):
            self._states[-1].font_family = str(self._default_font_family)
            self.lbl_font.setText(self._states[-1].font_family)

    def _update_index_label(self):
        n = len(self.file_paths)
        self.lbl_index.setText(f"{min(n, self._index + 1)}/{n}")
        self.btn_prev.setEnabled(self._index > 0)
        self.btn_next.setEnabled(self._index < (n - 1))

    def _prev_image(self):
        if self._index <= 0:
            return
        self._index -= 1
        self._render_preview()

    def _next_image(self):
        if self._index >= len(self.file_paths) - 1:
            return
        self._index += 1
        self._render_preview()

    def _schedule_preview_update(self, immediate: bool = False):
        if bool(getattr(self, "_preview_hidden", False)):
            self._pending_render_hidden = True
            return
        try:
            self.lbl_opacity.setText(f"{int(self.slider_opacity.value())}%")
        except Exception:
            pass
        try:
            if hasattr(self, "slider_image_size") and hasattr(self, "lbl_image_size"):
                self.lbl_image_size.setText(f"{int(self.slider_image_size.value())}%")
        except Exception:
            pass
        if bool(getattr(self, "_scene_interacting", False)):
            try:
                self._pending_render = True
            except Exception:
                pass
            return
        try:
            cur = self._current_state()
            heavy = cur is not None and str(getattr(cur, "kind", "text") or "text") != "text"
        except Exception:
            heavy = False
        if bool(getattr(self, "_slider_interacting", False)) and heavy:
            self._pending_slider_render = True
            return
        if immediate:
            try:
                self._debounce_timer.stop()
            except Exception:
                pass
            self._render_preview()
        else:
            self._debounce_timer.start()

    def _on_slider_interaction(self, interacting: bool):
        self._slider_interacting = bool(interacting)
        if not self._slider_interacting and bool(getattr(self, "_pending_slider_render", False)):
            self._pending_slider_render = False
            self._render_preview()

    def _on_preview_zoom_changed(self, v: int):
        try:
            vv = int(v)
        except Exception:
            vv = 100
        vv = int(max(25, min(400, vv)))
        try:
            self._preview_zoom = float(vv) / 100.0
        except Exception:
            self._preview_zoom = 1.0
        try:
            if hasattr(self, "lbl_preview_zoom") and self.lbl_preview_zoom is not None:
                self.lbl_preview_zoom.setText(f"{vv}%")
        except Exception:
            pass
        self._apply_preview_zoom()

    def _apply_preview_zoom(self):
        try:
            view = getattr(self, "view", None)
            if view is None:
                return
        except Exception:
            return
        try:
            fit_t = getattr(self, "_fit_transform", None)
        except Exception:
            fit_t = None
        try:
            zoom = float(getattr(self, "_preview_zoom", 1.0) or 1.0)
        except Exception:
            zoom = 1.0
        zoom = float(max(0.25, min(4.0, zoom)))
        try:
            if fit_t is not None:
                view.setTransform(fit_t)
            else:
                view.resetTransform()
            if abs(zoom - 1.0) > 1e-6:
                view.scale(zoom, zoom)
        except Exception:
            pass
        try:
            self._adjust_preview_area_width()
        except Exception:
            pass

    def _on_text_changed(self):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None or str(getattr(st, "kind", "text") or "text") != "text":
            return
        try:
            self._pending_text_value = str(self.edit_text.toPlainText() or "")
        except Exception:
            self._pending_text_value = ""
        try:
            self._text_debounce_timer.start()
        except Exception:
            self._commit_text_edit()

    def _commit_text_edit(self):
        st = self._current_state()
        if st is None or str(getattr(st, "kind", "text") or "text") != "text":
            return
        try:
            v = self._pending_text_value
        except Exception:
            v = None
        if v is None:
            try:
                v = str(self.edit_text.toPlainText() or "")
            except Exception:
                v = ""
        try:
            st.custom_text = str(v or "")
        except Exception:
            st.custom_text = ""
        self._schedule_preview_update(False)

    def _update_current_item_fast(self, *, resolve_text: bool = False):
        st = self._current_state()
        if st is None:
            return
        wid = str(getattr(st, "wm_id", "") or "")
        it = self._wm_items.get(wid) if isinstance(getattr(self, "_wm_items", None), dict) else None
        if it is None:
            return
        if resolve_text and str(getattr(st, "kind", "text") or "text") == "text":
            try:
                path = self.file_paths[self._index] if self.file_paths and 0 <= int(self._index) < len(self.file_paths) else ""
            except Exception:
                path = ""
            meta = self._meta_cache.get(path, {}) if isinstance(getattr(self, "_meta_cache", None), dict) else {}
            try:
                st.text = _resolve_text_with_tags(
                    meta,
                    str(getattr(st, "custom_text", "") or ""),
                    WATERMARK_TAG_LABEL_TO_KEY,
                    WATERMARK_TAG_KEY_SET,
                    WATERMARK_TAG_KEY_TO_LABEL,
                    fallback_tag_key=str(getattr(st, "tag_key", "") or ""),
                )
                st.font_point_size = _calc_text_font_size(
                    int(getattr(st, "font_base_size", st.font_point_size) or st.font_point_size or 24),
                    str(getattr(st, "text", "") or ""),
                )
            except Exception:
                pass
        try:
            it.setVisible(bool(getattr(st, "visible", True)))
        except Exception:
            pass
        try:
            it._update_from_state()
        except Exception:
            pass

    def _on_font_size_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None or str(getattr(st, "kind", "text") or "text") != "text":
            return
        try:
            new_size = int(self.spin_font_size.value())
        except Exception:
            new_size = 24
        st.font_base_size = int(new_size)
        st.font_point_size = int(new_size)
        self._update_current_item_fast(resolve_text=True)

    def _on_font_style_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None or str(getattr(st, "kind", "text") or "text") != "text":
            return
        try:
            st.font_bold = bool(self.chk_font_bold.isChecked())
            st.font_italic = bool(self.chk_font_italic.isChecked())
            st.font_underline = bool(self.chk_font_underline.isChecked())
        except Exception:
            st.font_bold = False
            st.font_italic = False
            st.font_underline = False
        self._update_current_item_fast(resolve_text=True)

    def _on_keep_aspect_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None:
            return
        try:
            st.keep_aspect = True
        except Exception:
            pass
        self._schedule_preview_update(True)

    def _on_effect_changed(self, _v=None):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None:
            return
        try:
            st.effect_mode = str(self.combo_effect.currentData() or "none")
        except Exception:
            st.effect_mode = str(getattr(st, "effect_mode", "none") or "none")
        mode = str(getattr(st, "effect_mode", "none") or "none").strip().lower()
        try:
            st.shadow_enabled = bool(mode != "none")
        except Exception:
            pass
        if mode == "beam":
            try:
                st.shadow_follow_color = False
            except Exception:
                pass
            try:
                if hasattr(self, "chk_shadow_follow") and self.chk_shadow_follow is not None:
                    self._syncing_ui = True
                    self.chk_shadow_follow.setChecked(False)
                    self._syncing_ui = False
            except Exception:
                self._syncing_ui = False
            try:
                if int(getattr(st, "shadow_distance", 0) or 0) <= 0:
                    st.shadow_distance = 4
                self._syncing_ui = True
                self.spin_shadow_dist.setValue(int(getattr(st, "shadow_distance", 4) or 4))
            except Exception:
                pass
            self._syncing_ui = False
        if mode == "mirror":
            try:
                st.mirror_gap_px = int(getattr(st, "mirror_gap_px", 0) or 0)
            except Exception:
                st.mirror_gap_px = 0
            try:
                st.shadow_follow_color = True
            except Exception:
                pass
            try:
                if hasattr(self, "chk_shadow_follow") and self.chk_shadow_follow is not None:
                    self._syncing_ui = True
                    self.chk_shadow_follow.setChecked(True)
                    self._syncing_ui = False
            except Exception:
                self._syncing_ui = False
            try:
                self._syncing_ui = True
                self.spin_shadow_dist.setValue(int(getattr(st, "mirror_gap_px", 0) or 0))
            except Exception:
                pass
            self._syncing_ui = False
        if mode == "stack":
            try:
                st.stack_count = int(getattr(st, "stack_count", 3) or 3)
            except Exception:
                st.stack_count = 3
            try:
                st.stack_step_px = int(getattr(st, "stack_step_px", 2) or 2)
            except Exception:
                st.stack_step_px = 2
            try:
                self._syncing_ui = True
                self.spin_shadow_dist.setValue(int(getattr(st, "stack_count", 3) or 3))
                self.spin_stack_step.setValue(int(getattr(st, "stack_step_px", 2) or 0))
            except Exception:
                pass
            self._syncing_ui = False
        self._apply_text_mode_controls()
        try:
            self._on_shadow_changed(0)
        except Exception:
            pass
        self._update_current_item_fast(resolve_text=False)

    def _on_opacity_slider_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        try:
            self.lbl_opacity.setText(f"{int(self.slider_opacity.value())}%")
        except Exception:
            pass
        try:
            st = self._current_state()
            if st is not None:
                op = int(self.slider_opacity.value())
                rgba = list(st.color_rgba or [255, 255, 255, 200])
                rgba[3] = int(round(op / 100.0 * 255))
                st.color_rgba = rgba
                self._update_color_label()
                try:
                    self._update_shadow_label()
                except Exception:
                    pass
                try:
                    it = self._wm_items.get(str(getattr(st, "wm_id", "") or ""))
                    if it is not None and hasattr(it, "_content_pix") and getattr(it, "_content_pix", None) is not None:
                        it._content_pix.setOpacity(max(0.0, min(1.0, float(rgba[3]) / 255.0)))
                except Exception:
                    pass
        except Exception:
            pass
        return

    def _on_image_size_slider_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        try:
            self.lbl_image_size.setText(f"{int(self.slider_image_size.value())}%")
        except Exception:
            pass
        try:
            st = self._current_state()
            if st is not None and str(getattr(st, "kind", "text") or "text") != "text":
                pct = float(self.slider_image_size.value()) / 100.0
                pct = max(0.01, min(1.0, pct))
                st.w_norm = pct
                st.h_norm = pct
        except Exception:
            pass
        try:
            cur = self._current_state()
            heavy = cur is not None and str(getattr(cur, "kind", "text") or "text") != "text"
        except Exception:
            heavy = False
        if self.slider_image_size.isSliderDown() and heavy:
            self._pending_slider_render = True
            return
        self._schedule_preview_update(True)

    def _on_rotate_slider_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        try:
            val = int(self.slider_rotate.value())
        except Exception:
            val = 0
        try:
            self.spin_rotate.blockSignals(True)
            self.spin_rotate.setValue(val)
        finally:
            self.spin_rotate.blockSignals(False)
        try:
            st = self._current_state()
            if st is not None:
                st.rotation_deg = float(val)
        except Exception:
            pass
        try:
            cur = self._current_state()
            heavy = cur is not None and str(getattr(cur, "kind", "text") or "text") != "text"
        except Exception:
            heavy = False
        if self.slider_rotate.isSliderDown() and heavy:
            self._pending_slider_render = True
            return
        self._update_current_item_fast(resolve_text=False)

    def _on_rotate_spin_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        try:
            val = int(self.spin_rotate.value())
        except Exception:
            val = 0
        try:
            self.slider_rotate.blockSignals(True)
            self.slider_rotate.setValue(val)
        finally:
            self.slider_rotate.blockSignals(False)
        try:
            st = self._current_state()
            if st is not None:
                st.rotation_deg = float(val)
        except Exception:
            pass
        self._update_current_item_fast(resolve_text=False)

    def _on_scene_interaction(self, interacting: bool):
        self._scene_interacting = bool(interacting)
        if not self._scene_interacting and bool(getattr(self, "_pending_render", False)):
            self._pending_render = False
            self._render_preview()

    def _update_tag_combo_width(self):
        try:
            fm = QFontMetricsF(self.combo_tag_insert.font())
            max_w = 0.0
            for i in range(int(self.combo_tag_insert.count())):
                t = str(self.combo_tag_insert.itemText(i) or "")
                max_w = max(max_w, float(fm.horizontalAdvance(t)))
            w = int(max(96.0, max_w + 44.0))
            w = int(min(220, max(96, w)))
            self.combo_tag_insert.setFixedWidth(int(w))
        except Exception:
            pass
        try:
            self._adjust_panel_width()
        except Exception:
            pass

    def _on_tag_insert_activated(self, index):
        try:
            idx = int(index)
        except Exception:
            idx = -1
        if idx < 0:
            return
        try:
            key = str(self.combo_tag_insert.itemData(idx) or "")
        except Exception:
            key = ""
        if not key:
            return
        label = str(self._tag_key_to_label.get(key, key))
        self._insert_tag_token(label)

    def _insert_tag_from_button(self):
        try:
            key = str(self.combo_tag_insert.currentData() or "")
        except Exception:
            key = ""
        if not key:
            return
        label = str(self._tag_key_to_label.get(key, key))
        self._insert_tag_token(label)

    def _insert_tag_token(self, label: str):
        token = f"{{{str(label or '').strip()}}}"
        if token == "{}":
            return
        try:
            cursor = self.edit_text.textCursor()
            cursor.insertText(token)
            self.edit_text.setTextCursor(cursor)
            self._schedule_preview_update(True)
        except Exception:
            pass

    def _current_state(self) -> WatermarkState | None:
        if not self._selected_wm_id:
            return None
        for st in self._states:
            if st.wm_id == self._selected_wm_id:
                return st
        return None

    def _sync_ui_from_state(self):
        st = self._current_state()
        if st is None:
            return
        self._syncing_ui = True
        self.combo_kind.blockSignals(True)
        try:
            try:
                idx = 0 if st.kind == "text" else 1
                self.combo_kind.setCurrentIndex(idx)
            finally:
                self.combo_kind.blockSignals(False)
            base_text = str(getattr(st, "custom_text", "") or "")
            if not base_text and str(getattr(st, "text_mode", "custom") or "custom") == "tag":
                tag_key = str(getattr(st, "tag_key", "") or "")
                if tag_key:
                    base_text = f"{{{self._tag_key_to_label.get(tag_key, tag_key)}}}"
            self.edit_text.setPlainText(base_text)
            if str(getattr(st, "kind", "text") or "text") == "text" and not int(getattr(st, "font_base_size", 0) or 0):
                # 文字渲染会动态缩放 font_point_size，这里把“用户设定的基础字号”单独固定下来，避免每次选中都越来越小
                st.font_base_size = int(getattr(st, "font_point_size", 24) or 24)
            self.spin_font_size.setValue(int(st.font_base_size or st.font_point_size or 24))
            try:
                self.chk_font_bold.setChecked(bool(getattr(st, "font_bold", False)))
                self.chk_font_italic.setChecked(bool(getattr(st, "font_italic", False)))
                self.chk_font_underline.setChecked(bool(getattr(st, "font_underline", False)))
            except Exception:
                pass
            try:
                self.chk_auto_color.setChecked(str(getattr(st, "color_mode", "custom") or "custom") == "auto")
                self.chk_stroke.setChecked(bool(getattr(st, "stroke_enabled", False)))
                self.spin_stroke_width.setValue(int(getattr(st, "stroke_width", 2) or 0))
                self.chk_shadow_follow.setChecked(bool(getattr(st, "shadow_follow_color", True)))
                cur_dir = str(getattr(st, "shadow_dir", "右下") or "右下")
                idx2 = int(self.combo_shadow_dir.findData(cur_dir))
                if idx2 >= 0:
                    self.combo_shadow_dir.setCurrentIndex(idx2)
                try:
                    mode0 = str(getattr(st, "effect_mode", "none") or "none").strip().lower()
                except Exception:
                    mode0 = "none"
                if mode0 == "mirror":
                    self.spin_shadow_dist.setValue(int(getattr(st, "mirror_gap_px", 0) or 0))
<<<<<<< HEAD
                    self.spin_mirror_angle.setValue(int(getattr(st, "mirror_angle_deg", 180) or 180))
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
                elif mode0 == "stack":
                    self.spin_shadow_dist.setValue(int(getattr(st, "stack_count", 3) or 3))
                    self.spin_stack_step.setValue(int(getattr(st, "stack_step_px", 2) or 0))
                else:
                    self.spin_shadow_dist.setValue(int(getattr(st, "shadow_distance", 4) or 0))
                self.spin_shadow_range.setValue(int(getattr(st, "shadow_range", 0) or 0))
            except Exception:
                pass
            rgba = list(st.color_rgba or [255, 255, 255, 200])
            self.slider_opacity.setValue(int(round(max(0, min(100, rgba[3] / 255.0 * 100.0)))))
            try:
                self.slider_image_size.setValue(int(round(max(1, min(100, float(st.w_norm) * 100.0)))))
                self.lbl_image_size.setText(f"{int(self.slider_image_size.value())}%")
            except Exception:
                pass
            try:
                val = int(round(float(st.rotation_deg)))
            except Exception:
                val = 0
            try:
                self.slider_rotate.blockSignals(True)
                self.spin_rotate.blockSignals(True)
                self.slider_rotate.setValue(val)
                self.spin_rotate.setValue(val)
            finally:
                try:
                    self.slider_rotate.blockSignals(False)
                except Exception:
                    pass
                try:
                    self.spin_rotate.blockSignals(False)
                except Exception:
                    pass
            try:
                mode = str(getattr(st, "effect_mode", "none") or "none")
            except Exception:
                mode = "none"
            try:
                idxm = int(self.combo_effect.findData(mode))
                if idxm >= 0:
                    self.combo_effect.setCurrentIndex(idxm)
                else:
                    self.combo_effect.setCurrentIndex(0)
            except Exception:
                pass
            try:
                if str(getattr(st, "kind", "text") or "text") == "text" and not str(getattr(st, "font_family", "") or "").strip():
                    if getattr(self, "_default_font_family", ""):
                        st.font_family = str(self._default_font_family)
            except Exception:
                pass
            self.lbl_font.setText(str(st.font_family or ""))
            self.lbl_image.setText(os.path.basename(str(st.image_path or "")))
            self._update_color_label()
            try:
                self._update_stroke_label()
                self._update_shadow_label()
            except Exception:
                pass
            self._apply_kind_rows(st.kind)
            self._apply_text_mode_controls()
        finally:
            self._syncing_ui = False

    def _apply_kind_rows(self, kind: str):
        k = str(kind or "text")
        is_text = k == "text"
        self.row_text.setVisible(is_text)
        self.row_font.setVisible(is_text)
        self.row_font_size.setVisible(is_text)
        self.row_font_style.setVisible(is_text)
        self.row_color.setVisible(is_text)
        self.row_auto_color.setVisible(is_text)
        self.row_stroke.setVisible(is_text)
        self.row_shadow.setVisible(is_text)
        self.row_opacity.setVisible(True)
        self.row_image_size.setVisible(not is_text)
        self.row_image.setVisible(not is_text)

    def _apply_text_mode_controls(self):
        st = self._current_state()
        if st is None:
            return
        is_text = str(st.kind or "text") == "text"
        self.edit_text.setEnabled(is_text)
        self.combo_tag_insert.setEnabled(is_text)
        try:
            mode = str(getattr(st, "color_mode", "custom") or "custom")
        except Exception:
            mode = "custom"
        try:
            self.btn_pick_color.setVisible(False)
        except Exception:
            pass
        try:
            self.btn_pick_shadow_color.setEnabled(False)
        except Exception:
            pass
        try:
            self.btn_pick_stroke_color.setVisible(False)
        except Exception:
            pass
        self._apply_effect_controls()

    def _apply_effect_controls(self):
        st = self._current_state()
        if st is None:
            return
        is_text = str(getattr(st, "kind", "text") or "text") == "text"
        try:
            self.combo_effect.setEnabled(is_text)
        except Exception:
            pass
        if not is_text:
            try:
                self.row_shadow.setVisible(False)
            except Exception:
                pass
            return
        try:
            effect_mode = str(getattr(st, "effect_mode", "none") or "none")
        except Exception:
            effect_mode = "none"
        effect_mode = str(effect_mode or "none").strip().lower()
        try:
            self.row_shadow.setVisible(True)
        except Exception:
            pass
        try:
            self.chk_shadow_follow.setVisible(True)
            self.lbl_shadow_dir.setVisible(True)
            self.combo_shadow_dir.setVisible(True)
            self.lbl_shadow_dist.setVisible(True)
            self.spin_shadow_dist.setVisible(True)
            self.lbl_shadow_range.setVisible(True)
            self.spin_shadow_range.setVisible(True)
            self.lbl_stack_step.setVisible(False)
            self.spin_stack_step.setVisible(False)
<<<<<<< HEAD
            self.lbl_mirror_angle.setVisible(False)
            self.spin_mirror_angle.setVisible(False)
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
            self.btn_pick_shadow_color.setVisible(True)
            self.shadow_preview.setVisible(True)
            self.lbl_shadow.setVisible(True)
        except Exception:
            pass
        if effect_mode == "none":
            try:
                self.chk_shadow_follow.setVisible(False)
                self.lbl_shadow_dir.setVisible(False)
                self.combo_shadow_dir.setVisible(False)
                self.lbl_shadow_dist.setVisible(False)
                self.spin_shadow_dist.setVisible(False)
                self.lbl_shadow_range.setVisible(False)
                self.spin_shadow_range.setVisible(False)
                self.lbl_stack_step.setVisible(False)
                self.spin_stack_step.setVisible(False)
                self.btn_pick_shadow_color.setVisible(False)
                self.shadow_preview.setVisible(False)
                self.lbl_shadow.setVisible(False)
            except Exception:
                pass
            return
        if effect_mode == "beam":
            try:
                self.lbl_shadow_dist.setText("长度")
            except Exception:
                pass
            try:
                self.spin_shadow_dist.setRange(0, 200)
            except Exception:
                pass
            try:
                self.lbl_shadow_range.setVisible(True)
                self.spin_shadow_range.setVisible(True)
            except Exception:
                pass
            try:
                self._adjust_panel_width()
            except Exception:
                pass
            return
        if effect_mode == "mirror":
            try:
                self.lbl_shadow_dist.setText("间隔")
            except Exception:
                pass
            try:
                self.spin_shadow_dist.setRange(0, 200)
            except Exception:
                pass
            try:
                self.lbl_shadow_range.setText("模糊度")
                self.lbl_shadow_range.setVisible(True)
                self.spin_shadow_range.setVisible(True)
            except Exception:
                pass
            try:
<<<<<<< HEAD
                self.lbl_mirror_angle.setVisible(True)
                self.spin_mirror_angle.setVisible(True)
            except Exception:
                pass
            try:
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
                self._adjust_panel_width()
            except Exception:
                pass
            return
        if effect_mode == "stack":
            try:
                self.lbl_shadow_dist.setText("数量")
            except Exception:
                pass
            try:
                self.spin_shadow_dist.setRange(1, 20)
            except Exception:
                pass
            try:
                self.lbl_stack_step.setVisible(True)
                self.spin_stack_step.setVisible(True)
            except Exception:
                pass
            try:
                self.lbl_shadow_range.setVisible(False)
                self.spin_shadow_range.setVisible(False)
            except Exception:
                pass
            try:
                self._adjust_panel_width()
            except Exception:
                pass
            return
        try:
            self._adjust_panel_width()
        except Exception:
            pass

    def _on_kind_changed(self):
        st = self._current_state()
        if st is None:
            return
        st.kind = str(self.combo_kind.currentData() or "text")
        self._apply_kind_rows(st.kind)
        self._apply_text_mode_controls()
        self._schedule_preview_update(True)

    def _update_color_label(self):
        st = self._current_state()
        if st is None:
            self.lbl_color.setText("")
            try:
                self.color_preview.setStyleSheet("border:1px solid #D0D0D0; border-radius:4px; background:#FFFFFF;")
            except Exception:
                pass
            return
        rgba = list(st.color_rgba or [255, 255, 255, 200])
        r, g, b, a = [int(max(0, min(255, v))) for v in rgba]
        alpha_pct = int(round(a / 255.0 * 100.0))
        try:
            mode = str(getattr(st, "color_mode", "custom") or "custom")
        except Exception:
            mode = "custom"
        if mode == "auto":
            self.lbl_color.setText(f"自动黑白  {alpha_pct}%")
        else:
            hex_rgb = f"#{r:02X}{g:02X}{b:02X}"
            self.lbl_color.setText(f"{hex_rgb}  {alpha_pct}%")
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary", "#D0D0D0")
        if mode == "auto":
            hex_argb = f"#{a:02X}808080"
        else:
            hex_argb = f"#{a:02X}{r:02X}{g:02X}{b:02X}"
        try:
            self.color_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:{hex_argb};")
        except Exception:
            pass

    def _pick_color(self):
        st = self._current_state()
        if st is None:
            return
        try:
            if str(getattr(st, "color_mode", "custom") or "custom") == "auto":
                return
        except Exception:
            pass
        rgba = list(st.color_rgba or [255, 255, 255, 200])
        c = ThemedColorDialog.get_color(self, "选择颜色", rgba, show_alpha=True)
        if c is None or not isinstance(c, QColor):
            return
        st.color_rgba = [int(c.red()), int(c.green()), int(c.blue()), int(c.alpha())]
        self._update_color_label()
        try:
            self._update_shadow_label()
        except Exception:
            pass
        try:
            self._push_recent_color(st.color_rgba)
        except Exception:
            pass
        self._schedule_preview_update(True)

    def _update_stroke_label(self):
        st = self._current_state()
        if st is None:
            try:
                self.lbl_stroke.setText("")
                self.stroke_preview.setStyleSheet("border:1px solid #D0D0D0; border-radius:4px; background:#FFFFFF;")
            except Exception:
                pass
            return
        if not bool(getattr(st, "stroke_enabled", False)):
            try:
                self.lbl_stroke.setText("未启用")
            except Exception:
                pass
            cm = ColorManager.instance()
            border = cm.get("popup.border.primary", "#D0D0D0")
            try:
                self.stroke_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:#00FFFFFF;")
            except Exception:
                pass
            return
        rgba = list(getattr(st, "stroke_rgba", None) or [])
        if not rgba:
            base_a = int(list(st.color_rgba or [255, 255, 255, 200])[3])
            rgba = [0, 0, 0, base_a]
        r, g, b, a = [int(max(0, min(255, v))) for v in rgba[:4]]
        hex_rgb = f"#{r:02X}{g:02X}{b:02X}"
        alpha_pct = int(round(a / 255.0 * 100.0))
        try:
            self.lbl_stroke.setText(f"{hex_rgb}  {alpha_pct}%  粗细{int(getattr(st, 'stroke_width', 0) or 0)}")
        except Exception:
            self.lbl_stroke.setText(f"{hex_rgb}  {alpha_pct}%")
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary", "#D0D0D0")
        hex_argb = f"#{a:02X}{r:02X}{g:02X}{b:02X}"
        try:
            self.stroke_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:{hex_argb};")
        except Exception:
            pass

    def _update_shadow_label(self):
        st = self._current_state()
        if st is None:
            try:
                self.lbl_shadow.setText("")
                self.shadow_preview.setStyleSheet("border:1px solid #D0D0D0; border-radius:4px; background:#FFFFFF;")
            except Exception:
                pass
            return
        try:
            mode = str(getattr(st, "effect_mode", "none") or "none").strip().lower()
        except Exception:
            mode = "none"
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary", "#D0D0D0")
        if mode == "none":
            try:
                self.lbl_shadow.setText("无阴影")
            except Exception:
                pass
            try:
                self.shadow_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:#00FFFFFF;")
            except Exception:
                pass
            return
        if not bool(getattr(st, "shadow_enabled", False)):
            try:
                self.lbl_shadow.setText("未启用")
            except Exception:
                pass
            try:
                self.shadow_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:#00FFFFFF;")
            except Exception:
                pass
            return
        follow = bool(getattr(st, "shadow_follow_color", False))
        dir_name = str(getattr(st, "shadow_dir", "右下") or "右下")
        dist = int(getattr(st, "shadow_distance", 4) or 0)
        blur = int(getattr(st, "shadow_range", 0) or 0)
        gap_px = int(getattr(st, "mirror_gap_px", 0) or 0)
<<<<<<< HEAD
        angle_deg = int(getattr(st, "mirror_angle_deg", 180) or 180)
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
        stack_count = int(getattr(st, "stack_count", 3) or 3)
        stack_step = int(getattr(st, "stack_step_px", 2) or 0)
        if follow:
            try:
                if mode == "beam":
                    self.lbl_shadow.setText(f"光束阴影  跟随颜色  {dir_name}  长度{dist}  模糊{blur}")
                elif mode == "mirror":
<<<<<<< HEAD
                    self.lbl_shadow.setText(f"镜像阴影  跟随颜色  {dir_name}  间隔{gap_px}  夹角{angle_deg}")
=======
                    self.lbl_shadow.setText(f"镜像阴影  跟随颜色  {dir_name}  间隔{gap_px}")
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
                elif mode == "stack":
                    self.lbl_shadow.setText(f"叠字阴影  跟随颜色  {dir_name}  数量{stack_count}  间隔{stack_step}")
                else:
                    self.lbl_shadow.setText(f"跟随颜色  {dir_name}")
            except Exception:
                pass
            base = list(st.color_rgba or [255, 255, 255, 200])
            r, g, b, a = [int(max(0, min(255, v))) for v in base[:4]]
            a = int(max(0, min(255, round(a * 0.6))))
            hex_argb = f"#{a:02X}{r:02X}{g:02X}{b:02X}"
            try:
                self.shadow_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:{hex_argb};")
            except Exception:
                pass
            return
        rgba = list(getattr(st, "shadow_rgba", None) or [])
        if not rgba:
            base = list(st.color_rgba or [255, 255, 255, 200])
            r0, g0, b0, a0 = [int(max(0, min(255, v))) for v in base[:4]]
            rgba = [0, 0, 0, int(max(0, min(255, round(a0 * 0.6))))]
        r, g, b, a = [int(max(0, min(255, v))) for v in rgba[:4]]
        hex_rgb = f"#{r:02X}{g:02X}{b:02X}"
        alpha_pct = int(round(a / 255.0 * 100.0))
        try:
            if mode == "beam":
                self.lbl_shadow.setText(f"光束阴影  {hex_rgb}  {alpha_pct}%  {dir_name}  长度{dist}  模糊{blur}")
            elif mode == "mirror":
<<<<<<< HEAD
                self.lbl_shadow.setText(f"镜像阴影  {hex_rgb}  {alpha_pct}%  {dir_name}  间隔{gap_px}  夹角{angle_deg}")
=======
                self.lbl_shadow.setText(f"镜像阴影  {hex_rgb}  {alpha_pct}%  {dir_name}  间隔{gap_px}")
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
            elif mode == "stack":
                self.lbl_shadow.setText(f"叠字阴影  {hex_rgb}  {alpha_pct}%  {dir_name}  数量{stack_count}  间隔{stack_step}")
            else:
                self.lbl_shadow.setText(f"{hex_rgb}  {alpha_pct}%  {dir_name}")
        except Exception:
            self.lbl_shadow.setText(f"{hex_rgb}  {alpha_pct}%")
        hex_argb = f"#{a:02X}{r:02X}{g:02X}{b:02X}"
        try:
            self.shadow_preview.setStyleSheet(f"border:1px solid {border}; border-radius:4px; background:{hex_argb};")
        except Exception:
            pass

    def _on_auto_color_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None or str(getattr(st, "kind", "text") or "text") != "text":
            return
        try:
            st.color_mode = "auto" if bool(self.chk_auto_color.isChecked()) else "custom"
        except Exception:
            st.color_mode = "custom"
        self._update_color_label()
        self._apply_text_mode_controls()
        self._update_current_item_fast(resolve_text=True)

    def _on_stroke_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None or str(getattr(st, "kind", "text") or "text") != "text":
            return
        try:
            st.stroke_enabled = bool(self.chk_stroke.isChecked())
        except Exception:
            st.stroke_enabled = False
        try:
            st.stroke_width = int(self.spin_stroke_width.value())
        except Exception:
            st.stroke_width = int(getattr(st, "stroke_width", 2) or 2)
        try:
            rgba = list(getattr(st, "stroke_rgba", None) or [])
        except Exception:
            rgba = []
        if not rgba:
            base_a = int(list(st.color_rgba or [255, 255, 255, 200])[3])
            st.stroke_rgba = [0, 0, 0, base_a]
        self._update_stroke_label()
        self._apply_text_mode_controls()
        self._update_current_item_fast(resolve_text=True)

    def _on_shadow_changed(self, _v):
        if bool(getattr(self, "_syncing_ui", False)):
            return
        st = self._current_state()
        if st is None or str(getattr(st, "kind", "text") or "text") != "text":
            return
        try:
            mode = str(getattr(st, "effect_mode", "none") or "none").strip().lower()
        except Exception:
            mode = "none"
        try:
            st.shadow_enabled = bool(mode != "none")
        except Exception:
            pass
        try:
            st.shadow_follow_color = bool(self.chk_shadow_follow.isChecked())
        except Exception:
            st.shadow_follow_color = True
        try:
            st.shadow_dir = str(self.combo_shadow_dir.currentData() or "右下")
        except Exception:
            st.shadow_dir = str(getattr(st, "shadow_dir", "右下") or "右下")
        try:
            v0 = int(self.spin_shadow_dist.value())
            if mode == "mirror":
                st.mirror_gap_px = int(v0)
<<<<<<< HEAD
                st.mirror_angle_deg = int(self.spin_mirror_angle.value())
=======
>>>>>>> af13f1a07498e6b1821fd8630804deaf4d11af0a
            elif mode == "stack":
                st.stack_count = int(v0)
            else:
                st.shadow_distance = int(v0)
        except Exception:
            st.shadow_distance = int(getattr(st, "shadow_distance", 4) or 4)
        try:
            if mode == "stack":
                st.stack_step_px = int(self.spin_stack_step.value())
            st.shadow_range = int(self.spin_shadow_range.value())
        except Exception:
            st.shadow_range = int(getattr(st, "shadow_range", 0) or 0)
        if bool(getattr(st, "shadow_follow_color", True)):
            try:
                st.shadow_rgba = []
            except Exception:
                pass
        else:
            try:
                rgba = list(getattr(st, "shadow_rgba", None) or [])
            except Exception:
                rgba = []
            if not rgba:
                base = list(st.color_rgba or [255, 255, 255, 200])
                _r0, _g0, _b0, a0 = [int(max(0, min(255, v))) for v in base[:4]]
                st.shadow_rgba = [0, 0, 0, int(max(0, min(255, round(a0 * 0.6))))]
        self._update_shadow_label()
        self._apply_text_mode_controls()
        self._update_current_item_fast(resolve_text=True)

    def _pick_stroke_color(self):
        st = self._current_state()
        if st is None:
            return
        rgba = list(getattr(st, "stroke_rgba", None) or [])
        if not rgba:
            base_a = int(list(st.color_rgba or [255, 255, 255, 200])[3])
            rgba = [0, 0, 0, base_a]
        c = ThemedColorDialog.get_color(self, "边框颜色", rgba, show_alpha=True)
        if c is None or not isinstance(c, QColor):
            return
        st.stroke_rgba = [int(c.red()), int(c.green()), int(c.blue()), int(c.alpha())]
        try:
            st.stroke_enabled = True
            self.chk_stroke.setChecked(True)
        except Exception:
            pass
        self._update_stroke_label()
        self._apply_text_mode_controls()
        self._update_current_item_fast(resolve_text=True)

    def _pick_shadow_color(self):
        st = self._current_state()
        if st is None:
            return
        try:
            if str(getattr(st, "effect_mode", "none") or "none").strip().lower() == "none":
                st.effect_mode = "beam"
                try:
                    idxm = int(self.combo_effect.findData("beam"))
                    if idxm >= 0:
                        self._syncing_ui = True
                        self.combo_effect.setCurrentIndex(idxm)
                except Exception:
                    pass
                self._syncing_ui = False
        except Exception:
            pass
        if bool(getattr(st, "shadow_follow_color", False)):
            try:
                self._syncing_ui = True
                self.chk_shadow_follow.setChecked(False)
            except Exception:
                pass
            self._syncing_ui = False
            try:
                st.shadow_follow_color = False
            except Exception:
                pass
        rgba = list(getattr(st, "shadow_rgba", None) or [])
        if not rgba:
            base = list(st.color_rgba or [255, 255, 255, 200])
            r0, g0, b0, a0 = [int(max(0, min(255, v))) for v in base[:4]]
            rgba = [r0, g0, b0, int(max(0, min(255, round(a0 * 0.6))))]
        c = ThemedColorDialog.get_color(self, "阴影颜色", rgba, show_alpha=True)
        if c is None or not isinstance(c, QColor):
            return
        st.shadow_rgba = [int(c.red()), int(c.green()), int(c.blue()), int(c.alpha())]
        try:
            st.shadow_enabled = True
        except Exception:
            pass
        self._update_shadow_label()
        self._apply_text_mode_controls()
        self._update_current_item_fast(resolve_text=True)

    def _pick_font_file(self):
        st = self._current_state()
        if st is None:
            return
        dlg = _WatermarkFontSelectDialog(self, prefs_key=self._prefs_key())
        if not dlg.exec():
            return
        fam = str(getattr(dlg, "selected_font_family", "") or "").strip()
        fp = str(getattr(dlg, "selected_font_path", "") or "").strip()
        if not fam:
            return
        try:
            st.font_family = str(fam)
        except Exception:
            st.font_family = str(fam)
        try:
            self.lbl_font.setText(str(fam))
        except Exception:
            pass
        try:
            if fp:
                self._push_recent_font(fp)
        except Exception:
            pass
        self._schedule_preview_update()

    def _pick_image_file(self):
        st = self._current_state()
        if st is None:
            return
        p, _ = QFileDialog.getOpenFileName(self, "选择水印图片", "", "水印图片 (*.png *.svg)")
        if not p:
            return
        ext = os.path.splitext(p)[1].lower()
        if ext not in (".png", ".svg"):
            NotificationManager.instance().show_warning("错误", "仅支持 SVG/PNG")
            return
        st.image_path = str(p)
        try:
            if ext == ".svg":
                st.svg_raster_path = _ensure_svg_raster_cache(st.image_path)
            else:
                st.svg_raster_path = ""
        except Exception:
            st.svg_raster_path = ""
        self.lbl_image.setText(os.path.basename(st.image_path))
        self._schedule_preview_update()

    def _show_add_menu(self):
        menu = QMenu(self)
        act_text = menu.addAction("文字水印")
        act_image = menu.addAction("图片水印")
        act_text.triggered.connect(lambda: self._add_watermark("text"))
        act_image.triggered.connect(lambda: self._add_watermark("image"))
        menu.exec(QCursor.pos())

    def _add_watermark(self, kind: str):
        k = str(kind or "text")
        wm_id = f"wm_{len(self._states) + 1}_{int(time.time_ns())}"
        st = WatermarkState(wm_id=wm_id, name=f"水印{len(self._states) + 1}", kind=("image" if k == "image" else "text"))
        st.visible = True
        st.x_norm = 0.5
        st.y_norm = 0.5
        if k == "image":
            st.w_norm = 1.0
            st.h_norm = 1.0
        else:
            st.w_norm = 0.25
            st.h_norm = 0.25
        st.rotation_deg = 0.0
        st.keep_aspect = True
        st.text_mode = "custom"
        st.custom_text = "水印"
        st.tag_key = ""
        st.text = "水印"
        # 新增文字水印时的默认字号，按用户反馈提升到更易见的大小
        base_size = 100
        st.font_base_size = int(base_size)
        st.font_point_size = int(base_size)
        op = 80
        st.color_rgba = [255, 255, 255, int(round(float(op) / 100.0 * 255))]
        st.color_mode = "custom"
        st.stroke_enabled = False
        st.stroke_width = 2
        st.stroke_rgba = [0, 0, 0, int(st.color_rgba[3])]
        st.shadow_enabled = False
        st.shadow_follow_color = False
        st.shadow_rgba = []
        st.shadow_dir = "右下"
        st.shadow_distance = 4
        st.shadow_range = 0
        st.effect_mode = "none"
        st.mirror_effect = False
        st.mirror_gap_px = 0
        st.stack_count = 3
        st.stack_step_px = 2
        st.image_path = ""
        if k == "text" and getattr(self, "_default_font_family", ""):
            st.font_family = str(self._default_font_family)
        self._states.append(st)
        item = QListWidgetItem(st.name)
        item.setData(Qt.ItemDataRole.UserRole, st.wm_id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
        item.setCheckState(Qt.CheckState.Checked)
        self.list_layers.addItem(item)
        self.list_layers.setCurrentItem(item)
        self._refresh_layer_list()
        self._schedule_preview_update()

    def _refresh_layer_list(self):
        for i in range(self.list_layers.count()):
            it = self.list_layers.item(i)
            wm_id = str(it.data(Qt.ItemDataRole.UserRole) or "")
            st = next((s for s in self._states if s.wm_id == wm_id), None)
            if st is None:
                continue
            st.name = str(it.text() or st.name)
            st.visible = it.checkState() == Qt.CheckState.Checked
        self._update_layers_min_height()

    def _update_layers_min_height(self):
        try:
            count = int(self.list_layers.count())
        except Exception:
            count = 0
        rows = max(1, min(4, max(0, count)))
        try:
            if count <= 0:
                row_h = 32
            else:
                row_h = int(self.list_layers.sizeHintForRow(0) or 32)
                row_h = max(26, row_h)
        except Exception:
            row_h = 32
        try:
            self.list_layers.setMinimumHeight(int(rows * row_h + 12))
        except Exception:
            pass

    def _on_layer_selected(self, cur: QListWidgetItem, _prev: QListWidgetItem):
        if cur is None:
            return
        wm_id = str(cur.data(Qt.ItemDataRole.UserRole) or "")
        self._selected_wm_id = wm_id or None
        self._sync_ui_from_state()
        self._apply_text_mode_controls()

    def _delete_selected(self):
        cur = self.list_layers.currentItem()
        if cur is None:
            return
        wm_id = str(cur.data(Qt.ItemDataRole.UserRole) or "")
        row = self.list_layers.row(cur)
        self.list_layers.takeItem(row)
        self._states = [s for s in self._states if s.wm_id != wm_id]
        if self.list_layers.count() > 0:
            self.list_layers.setCurrentRow(max(0, min(row, self.list_layers.count() - 1)))
        else:
            self._selected_wm_id = None
        self._schedule_preview_update()
        self._save_prefs()

    def reject(self):
        """
        关闭窗口时保存当前水印方案，避免删除/调整后未点击写入导致方案未持久化。
        """
        try:
            self._refresh_layer_list()
        except Exception:
            pass
        try:
            self._save_prefs()
        except Exception:
            pass
        return super().reject()

    def _set_all_layers_checked(self, checked: bool):
        """
        批量设置所有图层的勾选状态（全选/全不选）。

        参数：
        - checked: True 表示全部勾选并显示，False 表示全部取消勾选并隐藏
        """
        try:
            self.list_layers.blockSignals(True)
        except Exception:
            pass
        try:
            for i in range(self.list_layers.count()):
                it = self.list_layers.item(i)
                if it is None:
                    continue
                try:
                    it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                except Exception:
                    pass
        finally:
            try:
                self.list_layers.blockSignals(False)
            except Exception:
                pass
        self._schedule_preview_update(True)

    def _move_layer(self, delta: int):
        cur = self.list_layers.currentItem()
        if cur is None:
            return
        row = self.list_layers.row(cur)
        new_row = row + int(delta)
        if new_row < 0 or new_row >= self.list_layers.count():
            return
        it = self.list_layers.takeItem(row)
        self.list_layers.insertItem(new_row, it)
        self.list_layers.setCurrentRow(new_row)
        ids = []
        for i in range(self.list_layers.count()):
            ids.append(str(self.list_layers.item(i).data(Qt.ItemDataRole.UserRole) or ""))
        new_states = []
        for wm_id in ids:
            st = next((s for s in self._states if s.wm_id == wm_id), None)
            if st is not None:
                new_states.append(st)
        self._states = new_states
        self._schedule_preview_update()

    def _copy_selected(self):
        st = self._current_state()
        if st is None:
            return
        try:
            self._clipboard_state = json.dumps(st.to_json(), ensure_ascii=False)
            NotificationManager.instance().show_toast("已复制水印设置", 1600, parent=self, position="top")
        except Exception:
            pass

    def _paste_to_new(self):
        try:
            payload = str(getattr(self, "_clipboard_state", "") or "")
            if not payload:
                return
            d = json.loads(payload)
            st = WatermarkState.from_json(d)
            st.wm_id = f"wm_{len(self._states) + 1}_{int(time.time_ns())}"
            st.name = f"{st.name}-副本"
            self._states.append(st)
            item = QListWidgetItem(st.name)
            item.setData(Qt.ItemDataRole.UserRole, st.wm_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(Qt.CheckState.Checked if st.visible else Qt.CheckState.Unchecked)
            self.list_layers.addItem(item)
            self.list_layers.setCurrentItem(item)
            self._schedule_preview_update()
        except Exception:
            pass

    def _render_preview(self):
        if bool(getattr(self, "_preview_hidden", False)):
            self._pending_render_hidden = True
            return
        self._refresh_layer_list()

        self._update_index_label()
        if not self.file_paths:
            return
        path = self.file_paths[self._index]
        prev_render_path = str(getattr(self, "_render_path", "") or "")
        need_fit = (prev_render_path != str(path or "")) or (not bool(getattr(self, "_has_fit", False)))
        meta = self._meta_cache.get(path, {}) if isinstance(self._meta_cache, dict) else {}
        for s in (self._states or []):
            if str(getattr(s, "kind", "text") or "text") != "text":
                continue
            if not int(getattr(s, "font_base_size", 0) or 0):
                # 兼容老数据/粘贴/导入：没有基础字号时，用当前字号兜底，避免后续被“动态缩放结果”反向污染
                s.font_base_size = int(getattr(s, "font_point_size", 24) or 24)
            s.text = _resolve_text_with_tags(
                meta,
                str(getattr(s, "custom_text", "") or ""),
                WATERMARK_TAG_LABEL_TO_KEY,
                WATERMARK_TAG_KEY_SET,
                WATERMARK_TAG_KEY_TO_LABEL,
                fallback_tag_key=str(getattr(s, "tag_key", "") or ""),
            )
            s.font_point_size = _calc_text_font_size(int(getattr(s, "font_base_size", 24) or 24), s.text)

        can_update_only = (
            str(getattr(self, "_render_path", "") or "") == str(path or "")
            and self._base_pixmap_item is not None
            and isinstance(self._wm_items, dict)
            and len(self._wm_items) == len(self._states or [])
        )
        if can_update_only:
            for i, st2 in enumerate(self._states or []):
                it = self._wm_items.get(str(st2.wm_id))
                if it is None:
                    can_update_only = False
                    break
                try:
                    it.setVisible(bool(st2.visible))
                    it.setZValue(10 + i)
                    it._update_from_state()
                except Exception:
                    pass
            if can_update_only:
                try:
                    if self._selected_wm_id and self._selected_wm_id in self._wm_items:
                        self._wm_items[self._selected_wm_id].setSelected(True)
                except Exception:
                    pass
                self._apply_text_mode_controls()
                return

        try:
            if str(getattr(self, "_render_path", "") or "") == str(path or "") and self._base_pixmap_item is not None:
                pix0 = self._base_pixmap_item.pixmap()
                if pix0 is not None and not pix0.isNull():
                    self._apply_loaded_preview_qimage(path, pix0.toImage(), getattr(self, "_ref_is_landscape", None), need_fit)
                    return
        except Exception:
            pass

        self.scene.clear()
        self._wm_items = {}
        self._base_pixmap_item = None
        self._render_path = ""
        try:
            loading = QGraphicsTextItem("加载中...")
            self.scene.addItem(loading)
        except Exception:
            pass
        self._start_preview_load(path, need_fit)
        return

    def _start_preview_load(self, path: str, need_fit: bool):
        p = str(path or "")
        if not p:
            return
        if str(getattr(self, "_preview_loading_path", "") or "") == p and int(getattr(self, "_preview_loading_seq", 0) or 0) > 0 and self._base_pixmap_item is None:
            return
        self._preview_load_seq = int(getattr(self, "_preview_load_seq", 0) or 0) + 1
        seq = int(self._preview_load_seq)
        self._preview_loading_seq = seq
        self._preview_loading_path = p
        self._preview_need_fit_on_load = bool(need_fit)
        task = _PreviewLoadTask(p, int(self._preview_max_edge), seq)
        task.signals.loaded.connect(self._on_preview_loaded)
        self._thread_pool.start(task)

    def _on_preview_loaded(self, path: str, qimg: object, ref_landscape: object, seq: int):
        try:
            if int(seq) != int(getattr(self, "_preview_loading_seq", 0) or 0):
                return
        except Exception:
            return
        try:
            cur_path = str(self.file_paths[self._index] or "") if self.file_paths else ""
        except Exception:
            cur_path = ""
        if str(cur_path or "") != str(path or ""):
            return
        self._apply_loaded_preview_qimage(path, qimg, ref_landscape, bool(getattr(self, "_preview_need_fit_on_load", False)))

    def _apply_loaded_preview_qimage(self, path: str, qimg: object, ref_landscape: object, need_fit: bool):
        try:
            self.scene.clear()
        except Exception:
            pass
        self._wm_items = {}
        self._base_pixmap_item = None
        if isinstance(ref_landscape, bool):
            self._ref_is_landscape = ref_landscape
        if not isinstance(qimg, QImage) or qimg.isNull():
            try:
                err = QGraphicsTextItem("图片加载失败")
                self.scene.addItem(err)
            except Exception:
                pass
            return
        try:
            self._preview_qimg = qimg.convertToFormat(QImage.Format.Format_ARGB32)
        except Exception:
            self._preview_qimg = qimg if isinstance(qimg, QImage) else None
        pix = QPixmap.fromImage(qimg)
        self._base_pixmap_item = QGraphicsPixmapItem(pix)
        self._base_pixmap_item.setZValue(0)
        self.scene.addItem(self._base_pixmap_item)
        self.scene.setSceneRect(0, 0, pix.width(), pix.height())
        self._preview_image_size = QSize(int(pix.width()), int(pix.height()))
        self._render_path = str(path or "")

        def _on_any_item_changed():
            self._refresh_layer_list()
            cur_state = self._current_state()
            if cur_state is not None:
                self._syncing_ui = True
                try:
                    self.edit_text.blockSignals(True)
                    self.spin_font_size.blockSignals(True)
                    self.slider_opacity.blockSignals(True)
                    self.slider_rotate.blockSignals(True)
                    self.spin_rotate.blockSignals(True)
                    try:
                        self.chk_font_bold.blockSignals(True)
                        self.chk_font_italic.blockSignals(True)
                        self.chk_font_underline.blockSignals(True)
                    except Exception:
                        pass
                    try:
                        self.chk_auto_color.blockSignals(True)
                        self.chk_stroke.blockSignals(True)
                        self.spin_stroke_width.blockSignals(True)
                        self.chk_shadow_follow.blockSignals(True)
                        self.combo_shadow_dir.blockSignals(True)
                        self.spin_shadow_dist.blockSignals(True)
                        self.spin_shadow_range.blockSignals(True)
                        self.spin_stack_step.blockSignals(True)
                        self.combo_effect.blockSignals(True)
                    except Exception:
                        pass
                    base_text = str(getattr(cur_state, "custom_text", "") or "")
                    if not base_text and str(getattr(cur_state, "text_mode", "custom") or "custom") == "tag":
                        tag_key = str(getattr(cur_state, "tag_key", "") or "")
                        if tag_key:
                            base_text = f"{{{self._tag_key_to_label.get(tag_key, tag_key)}}}"
                    self.edit_text.setPlainText(base_text)
                    if str(getattr(cur_state, "kind", "text") or "text") == "text" and not int(getattr(cur_state, "font_base_size", 0) or 0):
                        cur_state.font_base_size = int(getattr(cur_state, "font_point_size", 24) or 24)
                    self.spin_font_size.setValue(int(getattr(cur_state, "font_base_size", 0) or cur_state.font_point_size or 24))
                    try:
                        self.chk_font_bold.setChecked(bool(getattr(cur_state, "font_bold", False)))
                        self.chk_font_italic.setChecked(bool(getattr(cur_state, "font_italic", False)))
                        self.chk_font_underline.setChecked(bool(getattr(cur_state, "font_underline", False)))
                    except Exception:
                        pass
                    try:
                        self.chk_auto_color.setChecked(str(getattr(cur_state, "color_mode", "custom") or "custom") == "auto")
                        self.chk_stroke.setChecked(bool(getattr(cur_state, "stroke_enabled", False)))
                        self.spin_stroke_width.setValue(int(getattr(cur_state, "stroke_width", 2) or 0))
                        self.chk_shadow_follow.setChecked(bool(getattr(cur_state, "shadow_follow_color", True)))
                        cur_dir = str(getattr(cur_state, "shadow_dir", "右下") or "右下")
                        idx = int(self.combo_shadow_dir.findData(cur_dir))
                        if idx >= 0:
                            self.combo_shadow_dir.setCurrentIndex(idx)
                        try:
                            mode = str(getattr(cur_state, "effect_mode", "none") or "none")
                        except Exception:
                            mode = "none"
                        idxm = int(self.combo_effect.findData(mode))
                        if idxm >= 0:
                            self.combo_effect.setCurrentIndex(idxm)
                        else:
                            self.combo_effect.setCurrentIndex(0)
                        mode2 = str(mode or "none").strip().lower()
                        if mode2 == "mirror":
                            self.spin_shadow_dist.setValue(int(getattr(cur_state, "mirror_gap_px", 0) or 0))
                        elif mode2 == "stack":
                            self.spin_shadow_dist.setValue(int(getattr(cur_state, "stack_count", 3) or 3))
                            self.spin_stack_step.setValue(int(getattr(cur_state, "stack_step_px", 2) or 0))
                        else:
                            self.spin_shadow_dist.setValue(int(getattr(cur_state, "shadow_distance", 4) or 0))
                        self.spin_shadow_range.setValue(int(getattr(cur_state, "shadow_range", 0) or 0))
                    except Exception:
                        pass
                    rgba2 = list(cur_state.color_rgba or [255, 255, 255, 200])
                    self.slider_opacity.setValue(int(round(max(0, min(100, rgba2[3] / 255.0 * 100.0)))))
                    try:
                        val = int(round(float(cur_state.rotation_deg)))
                    except Exception:
                        val = 0
                    try:
                        self.spin_rotate.setValue(val)
                        self.slider_rotate.setValue(val)
                    except Exception:
                        pass
                    if str(getattr(cur_state, "kind", "text") or "text") != "text":
                        try:
                            self.slider_image_size.setValue(int(round(max(1, min(100, float(cur_state.w_norm) * 100.0)))))
                        except Exception:
                            pass
                    self._update_color_label()
                    try:
                        self._update_stroke_label()
                        self._update_shadow_label()
                    except Exception:
                        pass
                finally:
                    self.edit_text.blockSignals(False)
                    self.spin_font_size.blockSignals(False)
                    self.slider_opacity.blockSignals(False)
                    self.slider_rotate.blockSignals(False)
                    self.spin_rotate.blockSignals(False)
                    try:
                        self.chk_font_bold.blockSignals(False)
                        self.chk_font_italic.blockSignals(False)
                        self.chk_font_underline.blockSignals(False)
                    except Exception:
                        pass
                    try:
                        self.chk_auto_color.blockSignals(False)
                        self.chk_stroke.blockSignals(False)
                        self.spin_stroke_width.blockSignals(False)
                        self.chk_shadow_follow.blockSignals(False)
                        self.combo_shadow_dir.blockSignals(False)
                        self.spin_shadow_dist.blockSignals(False)
                        self.spin_shadow_range.blockSignals(False)
                        self.spin_stack_step.blockSignals(False)
                        self.combo_effect.blockSignals(False)
                    except Exception:
                        pass
                    self._syncing_ui = False
                self._apply_text_mode_controls()

        def _on_item_selected(wm_id: str):
            self._select_layer_by_id(wm_id)

        for st2 in (self._states or []):
            it = _WatermarkGraphicsItem(
                st2,
                self._preview_image_size,
                on_changed=_on_any_item_changed,
                on_selected=_on_item_selected,
                on_interaction=self._on_scene_interaction,
                bg_qimg=getattr(self, "_preview_qimg", None),
                render_requester=self,
            )
            it.setVisible(bool(st2.visible))
            it.setZValue(10 + len(self._wm_items))
            self.scene.addItem(it)
            self._wm_items[str(st2.wm_id)] = it

        try:
            if self._selected_wm_id and self._selected_wm_id in self._wm_items:
                self._wm_items[self._selected_wm_id].setSelected(True)
        except Exception:
            pass
        if need_fit:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            try:
                self._fit_transform = self.view.transform()
            except Exception:
                self._fit_transform = None
            self._has_fit = True
            self._apply_preview_zoom()
        try:
            self._adjust_preview_area_width()
        except Exception:
            pass
        self._apply_text_mode_controls()

    def _queue_text_patch_render(self, wm_id: str, token: int, payload: dict):
        try:
            if self._thread_pool is None:
                return
        except Exception:
            return
        wid = str(wm_id or "")
        if not wid:
            return
        try:
            if not isinstance(self._pending_text_patch_jobs, dict):
                self._pending_text_patch_jobs = {}
            self._pending_text_patch_jobs[wid] = (int(token or 0), payload if isinstance(payload, dict) else {})
            try:
                self._text_patch_timer.start()
            except Exception:
                self._flush_text_patch_jobs()
        except Exception:
            pass

    def _flush_text_patch_jobs(self):
        try:
            if self._thread_pool is None:
                return
        except Exception:
            return
        try:
            jobs = dict(self._pending_text_patch_jobs) if isinstance(self._pending_text_patch_jobs, dict) else {}
            self._pending_text_patch_jobs = {}
        except Exception:
            jobs = {}
        for wid, job in (jobs or {}).items():
            try:
                token, payload = job
            except Exception:
                continue
            try:
                task = _TextPatchRenderTask(str(wid or ""), int(token or 0), payload if isinstance(payload, dict) else {})
                try:
                    task.signals.rendered.connect(self._text_patch_signals.rendered)
                except Exception:
                    task.signals.rendered.connect(self._on_text_patch_rendered)
                self._thread_pool.start(task)
            except Exception:
                pass

    def _on_text_patch_rendered(self, wm_id: str, token: int, patch: object):
        wid = str(wm_id or "")
        if not wid:
            return
        try:
            it = self._wm_items.get(wid) if isinstance(self._wm_items, dict) else None
        except Exception:
            it = None
        if it is None or not isinstance(it, _WatermarkGraphicsItem):
            return
        try:
            it._apply_text_patch(int(token or 0), patch)
        except Exception:
            pass

    def _queue_image_wm_render(self, wm_id: str, token: int, src_path: str, payload: dict):
        try:
            if self._thread_pool is None:
                return
        except Exception:
            return
        wid = str(wm_id or "")
        if not wid:
            return
        sp = str(src_path or "")
        if not sp:
            return
        try:
            task = _ImageWatermarkRenderTask(wid, int(token or 0), sp, payload if isinstance(payload, dict) else {})
            try:
                task.signals.rendered.connect(self._image_wm_signals.rendered)
            except Exception:
                task.signals.rendered.connect(self._on_image_wm_rendered)
            self._thread_pool.start(task)
        except Exception:
            pass

    def _on_image_wm_rendered(self, wm_id: str, token: int, qimg: object):
        wid = str(wm_id or "")
        if not wid:
            return
        try:
            it = self._wm_items.get(wid) if isinstance(self._wm_items, dict) else None
        except Exception:
            it = None
        if it is None or not isinstance(it, _WatermarkGraphicsItem):
            return
        try:
            it._apply_image_qimg(int(token or 0), qimg)
        except Exception:
            pass

    def _select_layer_by_id(self, wm_id: str):
        wid = str(wm_id or "")
        if not wid:
            return
        for i in range(self.list_layers.count()):
            it = self.list_layers.item(i)
            if str(it.data(Qt.ItemDataRole.UserRole) or "") == wid:
                try:
                    self.list_layers.setCurrentRow(i)
                except Exception:
                    pass
                break

    def _apply_all_clicked(self):
        try:
            self._refresh_layer_list()
        except Exception:
            pass
        try:
            NotificationManager.instance().show_toast("已应用到所有图片（未保存）", 2000, parent=self, position="top")
        except Exception:
            try:
                NotificationManager.instance().show_toast("已应用到所有图片（未保存）")
            except Exception:
                pass
        self._schedule_preview_update(True)

    def _save_copy_clicked(self):
        if not self.file_paths:
            return
        if self._index < 0 or self._index >= len(self.file_paths):
            return
        src_path = str(self.file_paths[self._index] or "")
        if not src_path:
            return
        self._refresh_layer_list()
        # 用户点击“另存”属于真实写入操作（会生成新文件）
        try:
            self._user_clicked_save_copy = True
        except Exception:
            pass
        auto_rotate = True
        base, ext = os.path.splitext(src_path)
        if not ext:
            ext = ".jpg"
        dst_path = f"{base}_watermark{ext}"
        if os.path.exists(dst_path):
            idx = 2
            while True:
                cand = f"{base}_watermark_{idx}{ext}"
                if not os.path.exists(cand):
                    dst_path = cand
                    break
                idx += 1
        task = _WatermarkSaveCopyTask(
            src_path,
            dst_path,
            self._states,
            ref_is_landscape=getattr(self, "_ref_is_landscape", None),
            auto_rotate=auto_rotate,
            preview_max_edge=int(getattr(self, "_preview_max_edge", 1600) or 1600),
        )
        self._save_copy_task = task
        self.btn_save_copy.setEnabled(False)
        task.signals.finished.connect(self._on_save_copy_finished)
        self._thread_pool.start(task)

    def _write_clicked(self):
        if not self.file_paths:
            return
        self._refresh_layer_list()
        # 用户点击“保存/应用”才允许触发父页面的缩略图刷新逻辑
        try:
            self._user_clicked_write = True
        except Exception:
            pass
        # 用户点击“保存/应用”后，任务处理完成即自动退出窗口
        # 这个标记只对本次批处理有效，避免其它流程误触发关闭
        try:
            self._auto_close_on_finish = True
        except Exception:
            pass
        try:
            auto_rotate = True
        except Exception:
            auto_rotate = True
        try:
            p0 = str(self.file_paths[0] or "") if self.file_paths else ""
        except Exception:
            p0 = ""
        task = _WatermarkBatchTask(
            self.file_paths,
            self._states,
            ref_is_landscape=getattr(self, "_ref_is_landscape", None),
            auto_rotate=auto_rotate,
            preview_max_edge=int(getattr(self, "_preview_max_edge", 1600) or 1600),
        )
        self._batch_task = task
        self.btn_apply_all.setEnabled(False)
        self.progress.setValue(0)
        self.lbl_progress.setText("")
        try:
            self.lbl_progress.setVisible(False)
        except Exception:
            pass
        try:
            self.progress.setVisible(True)
        except Exception:
            pass
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        self._thread_pool.start(task)

    def _on_save_copy_finished(self, ok: bool, message: str, dst_path: str, info: object):
        try:
            self.btn_save_copy.setEnabled(True)
        except Exception:
            pass
        if ok:
            NotificationManager.instance().show_toast(str(message or "另存完成"), 2200, parent=self, position="top")
        else:
            NotificationManager.instance().show_warning("完成", str(message or "另存失败"))
        if not ok:
            return
        # 另存属于“新增文件”，这里记录为变更路径，便于父页面（如有需要）做后续精确刷新
        try:
            self._last_changed_paths = [str(dst_path or "")] if dst_path else []
            self._last_unchanged_paths = []
        except Exception:
            pass
        try:
            parent = self.parent()
            if parent is None:
                return
            path_key = dst_path
            if hasattr(parent, "_normalize_path_key"):
                try:
                    path_key = parent._normalize_path_key(dst_path)
                except Exception:
                    path_key = dst_path
            found = False
            raw_list = getattr(parent, "raw_image_files", None)
            if isinstance(raw_list, list) and raw_list:
                first_item = None
                dup_indices = []
                for idx, it in enumerate(list(raw_list)):
                    try:
                        p = str(it.get("path") or "")
                    except Exception:
                        p = ""
                    if not p:
                        continue
                    try:
                        k = parent._normalize_path_key(p) if hasattr(parent, "_normalize_path_key") else p
                    except Exception:
                        k = p
                    if k != path_key:
                        continue
                    found = True
                    if first_item is None and isinstance(it, dict):
                        first_item = it
                        continue
                    if isinstance(it, dict):
                        if isinstance(first_item, dict):
                            try:
                                for kk, vv in it.items():
                                    try:
                                        cur = first_item.get(kk)
                                    except Exception:
                                        cur = None
                                    if cur is None or cur == "" or cur == 0:
                                        first_item[kk] = vv
                            except Exception:
                                pass
                    dup_indices.append(int(idx))
                if dup_indices:
                    for i in sorted(dup_indices, reverse=True):
                        try:
                            raw_list.pop(int(i))
                        except Exception:
                            pass
            all_list = getattr(parent, "all_image_files", None)
            if isinstance(all_list, list) and all_list:
                first_item = None
                dup_indices = []
                for idx, it in enumerate(list(all_list)):
                    try:
                        p = str(it.get("path") or "")
                    except Exception:
                        p = ""
                    if not p:
                        continue
                    try:
                        k = parent._normalize_path_key(p) if hasattr(parent, "_normalize_path_key") else p
                    except Exception:
                        k = p
                    if k != path_key:
                        continue
                    if first_item is None and isinstance(it, dict):
                        first_item = it
                        continue
                    dup_indices.append(int(idx))
                if dup_indices:
                    for i in sorted(dup_indices, reverse=True):
                        try:
                            all_list.pop(int(i))
                        except Exception:
                            pass
            cur_folder = getattr(parent, "current_folder_path", "")
            if cur_folder and cur_folder.startswith("virtual://taxonomy"):
                if hasattr(parent, "load_images_from_taxonomy"):
                    parent.load_images_from_taxonomy(cur_folder)
                    return
            if cur_folder and os.path.normpath(cur_folder) == os.path.normpath(os.path.dirname(dst_path)):
                if not found and hasattr(parent, "load_images_from_folder"):
                    parent.load_images_from_folder(cur_folder)
                    return
            if found:
                try:
                    parent.apply_quick_filters()
                except Exception:
                    pass
                try:
                    parent.refresh_thumbnail(dst_path)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_progress(self, cur: int, total: int, name: str):
        total = max(1, int(total))
        cur = max(0, int(cur))
        self.progress.setValue(int(round(cur / float(total) * 100.0)))
        self.lbl_progress.setText(f"{cur}/{total}  {name}")
        try:
            self.lbl_progress.setVisible(True)
        except Exception:
            pass

    def _on_finished(self, ok: bool, message: str):
        self.btn_apply_all.setEnabled(True)
        try:
            self.progress.setVisible(False)
        except Exception:
            pass
        try:
            self.lbl_progress.setVisible(False)
        except Exception:
            pass
        try:
            parent = self.parent()
        except Exception:
            parent = None
        notify_parent = parent if parent is not None else self
        if ok:
            NotificationManager.instance().show_toast(str(message or "处理完成"), 2200, parent=notify_parent, position="top")
        else:
            NotificationManager.instance().show_warning("完成", str(message or "部分图片处理失败"))
        try:
            self._save_prefs()
        except Exception:
            pass
        try:
            if parent is not None:
                task = getattr(self, "_batch_task", None)
                changed = None
                try:
                    changed = getattr(task, "changed_paths", None) if task is not None else None
                except Exception:
                    changed = None
                # 仅对真实发生改动的图片做缓存失效与缩略图刷新
                base_paths = changed if isinstance(changed, list) else []
                paths = [str(p or "") for p in (base_paths or []) if p]
                # 记录变更结果，供父页面在关闭对话框后按需刷新（避免无条件刷新导致的缓存抖动）
                try:
                    self._last_changed_paths = list(paths)
                except Exception:
                    self._last_changed_paths = []
                try:
                    unchanged = getattr(task, "unchanged_paths", None) if task is not None else None
                except Exception:
                    unchanged = None
                try:
                    self._last_unchanged_paths = [str(p or "") for p in (unchanged or []) if p] if isinstance(unchanged, list) else []
                except Exception:
                    self._last_unchanged_paths = []
                if not paths:
                    return
                if paths:
                    keys = set()
                    try:
                        if hasattr(parent, "_normalize_path_key"):
                            for p in paths:
                                try:
                                    keys.add(parent._normalize_path_key(p))
                                except Exception:
                                    keys.add(str(p))
                        else:
                            for p in paths:
                                keys.add(str(p))
                    except Exception:
                        keys = set(str(p) for p in paths)
                    cm = getattr(parent, "cache_manager", None)
                    if cm is not None and hasattr(cm, "invalidate_many"):
                        try:
                            cm.invalidate_many(paths)
                        except Exception:
                            pass
                    elif cm is not None and hasattr(cm, "invalidate"):
                        for p in paths:
                            try:
                                cm.invalidate(p)
                            except Exception:
                                pass
                    try:
                        bic = getattr(parent, "big_image_cache", None)
                        if bic is not None and hasattr(bic, "clear"):
                            bic.clear()
                    except Exception:
                        pass
                    try:
                        pp = getattr(parent, "preview_panel", None)
                        if pp is not None and hasattr(pp, "current_original_pixmap"):
                            pp.current_original_pixmap = None
                        if pp is not None:
                            try:
                                cur_preview = str(getattr(pp, "current_image_path", "") or "")
                            except Exception:
                                cur_preview = ""
                            if cur_preview:
                                k0 = cur_preview
                                try:
                                    if hasattr(parent, "_normalize_path_key"):
                                        k0 = parent._normalize_path_key(cur_preview)
                                except Exception:
                                    k0 = cur_preview
                                if k0 in keys and hasattr(pp, "load_image"):
                                    try:
                                        pp.load_image(cur_preview)
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    tl = getattr(parent, "thumbnail_loader", None)
                    dc = getattr(tl, "disk_cache", None) if tl is not None else None
                    if dc is not None and hasattr(dc, "invalidate_many"):
                        try:
                            dc.invalidate_many(paths)
                        except Exception:
                            pass
                    try:
                        thumb_map = getattr(parent, "_thumb_by_path", None)
                        if isinstance(thumb_map, dict) and keys:
                            for k in list(keys):
                                t = thumb_map.get(k)
                                if t is None:
                                    continue
                                try:
                                    t.thumbnail_pixmap = None
                                except Exception:
                                    pass
                                try:
                                    if hasattr(t, "_thumbnail_image"):
                                        t._thumbnail_image = None
                                except Exception:
                                    pass
                                try:
                                    t._stale_thumbnail = True
                                except Exception:
                                    pass
                                try:
                                    t.update()
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    if hasattr(parent, "_schedule_visible_load"):
                        try:
                            parent._schedule_visible_load(immediate=True)
                        except Exception:
                            pass
        except Exception:
            pass
        try:
            auto_close = bool(getattr(self, "_auto_close_on_finish", False))
        except Exception:
            auto_close = False
        if auto_close:
            try:
                self._auto_close_on_finish = False
            except Exception:
                pass
            try:
                QTimer.singleShot(0, self.accept)
            except Exception:
                try:
                    self.accept()
                except Exception:
                    pass

    def _reset_clicked(self):
        from ui.widgets.custom_message_box import CustomMessageBox

        box = CustomMessageBox(
            parent=self,
            title="确认",
            message="确认恢复默认设置？",
            buttons=[("取消", "cancel"), ("确定", "ok")],
        )
        if box.exec() == 0:
            return
        try:
            self.list_layers.blockSignals(True)
        except Exception:
            pass
        try:
            self._selected_wm_id = None
        except Exception:
            pass
        try:
            self._wm_items = {}
            self._base_pixmap_item = None
            self._render_path = ""
        except Exception:
            pass
        try:
            self._states = []
            self.list_layers.clear()
            self._ensure_default_watermark()
            if self.list_layers.count() > 0:
                self.list_layers.setCurrentRow(0)
                try:
                    self._selected_wm_id = str(self.list_layers.item(0).data(Qt.ItemDataRole.UserRole) or "") or None
                except Exception:
                    self._selected_wm_id = None
            self._sync_ui_from_state()
            self._update_layers_min_height()
            self._save_prefs(reset=True)
            self._render_preview()
        except Exception as e:
            try:
                NotificationManager.instance().show_warning("错误", f"恢复默认失败: {e}")
            except Exception:
                pass
        try:
            self.list_layers.blockSignals(False)
        except Exception:
            pass

    def _prefs_key(self) -> str:
        return "watermark/prefs"

    def user_clicked_write(self) -> bool:
        """
        判断用户是否点击过“保存/应用”按钮。
        
        说明：
        - 父页面可用该结果决定是否需要在对话框关闭后刷新缩略图
        - 仅用于避免“未改动水印也触发缓存失效”的体验问题
        """
        try:
            return bool(getattr(self, "_user_clicked_write", False))
        except Exception:
            return False

    def user_clicked_save_copy(self) -> bool:
        """
        判断用户是否点击过“另存”按钮。
        
        说明：
        - 另存会生成新文件；通常由对话框内部直接刷新父页面
        - 这里提供给父页面兜底判断（例如父页面需要做额外刷新时）
        """
        try:
            return bool(getattr(self, "_user_clicked_save_copy", False))
        except Exception:
            return False

    def get_last_changed_paths(self) -> list[str]:
        """
        获取最近一次保存产生的“实际发生像素改动”的文件路径列表。
        
        说明：
        - 用于父页面做精确刷新，避免对未改动图片做缓存失效
        - 若用户未执行保存/批处理，则可能为空列表
        """
        try:
            paths = getattr(self, "_last_changed_paths", None)
        except Exception:
            paths = None
        if isinstance(paths, list):
            return [str(p or "") for p in paths if p]
        return []

    def _load_prefs(self):
        sm = SettingsManager.instance()
        try:
            raw = sm.get(self._prefs_key(), "") or ""
        except Exception:
            raw = ""
        try:
            d = json.loads(raw) if raw else {}
        except Exception:
            d = {}
        try:
            recent = d.get("recent_presets") or []
            if isinstance(recent, list) and recent:
                last = recent[0]
                states = [WatermarkState.from_json(x) for x in (last.get("states") or []) if isinstance(x, dict)]
                if states:
                    try:
                        font_files = d.get("font_files") or []
                        recent_fonts = d.get("recent_fonts") or []
                        all_fonts = []
                        if isinstance(font_files, list) and font_files:
                            all_fonts.extend([str(x) for x in font_files if x])
                        if isinstance(recent_fonts, list) and recent_fonts:
                            all_fonts.extend([str(x) for x in recent_fonts if x])
                        seen = set()
                        merged = []
                        for fp in all_fonts:
                            try:
                                p = str(fp or "").strip()
                            except Exception:
                                p = ""
                            if not p or p in seen:
                                continue
                            seen.add(p)
                            merged.append(p)
                        for fp in merged[:20]:
                            try:
                                p = str(fp or "")
                            except Exception:
                                p = ""
                            if not p:
                                continue
                            try:
                                if os.path.exists(p):
                                    QFontDatabase.addApplicationFont(p)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    fixed = []
                    for s in states:
                        try:
                            k = str(getattr(s, "kind", "text") or "text")
                        except Exception:
                            k = "text"
                        if k not in ("text", "image"):
                            try:
                                s.kind = "text"
                            except Exception:
                                pass
                            k = "text"
                        try:
                            if k == "image" and not str(getattr(s, "image_path", "") or "").strip():
                                continue
                        except Exception:
                            pass
                        try:
                            if not str(getattr(s, "wm_id", "") or "").strip():
                                s.wm_id = f"wm_{len(fixed) + 1}_{int(time.time_ns())}"
                        except Exception:
                            pass
                        fixed.append(s)
                    self._states = fixed
                    if getattr(self, "_default_font_family", ""):
                        for s in self._states:
                            if str(getattr(s, "kind", "text") or "text") == "text" and not str(getattr(s, "font_family", "") or ""):
                                s.font_family = str(self._default_font_family)
                    self.list_layers.clear()
                    for st in self._states:
                        it = QListWidgetItem(st.name)
                        it.setData(Qt.ItemDataRole.UserRole, st.wm_id)
                        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
                        it.setCheckState(Qt.CheckState.Checked if st.visible else Qt.CheckState.Unchecked)
                        self.list_layers.addItem(it)
                    self.list_layers.setCurrentRow(0)
        except Exception:
            pass
        try:
            default_kind = str(d.get("default_kind") or "text")
            self.combo_kind.setCurrentIndex(0 if default_kind == "text" else 1)
        except Exception:
            pass

    def _save_prefs(self, reset: bool = False):
        sm = SettingsManager.instance()
        if reset:
            payload = {
                "recent_presets": [],
                "default_kind": "text",
                "recent_fonts": [],
                "font_files": [],
                "last_font_file": "",
                "recent_colors": [],
                "last_font_dir": "",
            }
            try:
                sm.set(self._prefs_key(), json.dumps(payload, ensure_ascii=False))
                sm.sync_to_config(self._prefs_key())
            except Exception:
                pass
            return
        try:
            raw = sm.get(self._prefs_key(), "") or ""
        except Exception:
            raw = ""
        try:
            d = json.loads(raw) if raw else {}
        except Exception:
            d = {}
        recent = d.get("recent_presets")
        if not isinstance(recent, list):
            recent = []
        preset = {"states": [s.to_json() for s in (self._states or [])]}
        recent = [preset] + [x for x in recent if x != preset]
        recent = recent[:5]
        d["recent_presets"] = recent
        d["default_kind"] = str(self.combo_kind.currentData() or "text")
        try:
            sm.set(self._prefs_key(), json.dumps(d, ensure_ascii=False))
            sm.sync_to_config(self._prefs_key())
        except Exception:
            pass

    def _push_recent_font(self, font_path: str):
        sm = SettingsManager.instance()
        try:
            raw = sm.get(self._prefs_key(), "") or ""
        except Exception:
            raw = ""
        try:
            d = json.loads(raw) if raw else {}
        except Exception:
            d = {}
        recent = d.get("recent_fonts")
        if not isinstance(recent, list):
            recent = []
        font_files = d.get("font_files")
        if not isinstance(font_files, list):
            font_files = []
        p = str(font_path or "")
        if p:
            recent = [p] + [x for x in recent if x != p]
            if p not in font_files:
                font_files.append(p)
            try:
                d["last_font_file"] = str(p)
                d["last_font_dir"] = str(os.path.dirname(p) or "")
            except Exception:
                pass
        d["recent_fonts"] = recent[:10]
        d["font_files"] = font_files
        try:
            sm.set(self._prefs_key(), json.dumps(d, ensure_ascii=False))
            sm.sync_to_config(self._prefs_key())
        except Exception:
            pass

    def _push_recent_color(self, rgba):
        sm = SettingsManager.instance()
        try:
            raw = sm.get(self._prefs_key(), "") or ""
        except Exception:
            raw = ""
        try:
            d = json.loads(raw) if raw else {}
        except Exception:
            d = {}
        recent = d.get("recent_colors")
        if not isinstance(recent, list):
            recent = []
        try:
            v = [int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3])]
        except Exception:
            v = None
        if v is not None:
            key = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            recent = [key] + [x for x in recent if x != key]
        d["recent_colors"] = recent[:20]
        try:
            sm.set(self._prefs_key(), json.dumps(d, ensure_ascii=False))
            sm.sync_to_config(self._prefs_key())
        except Exception:
            pass
