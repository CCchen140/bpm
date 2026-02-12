import os
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon, QImage, QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QByteArray, QBuffer
try:
    import qtawesome as qta
except Exception:
    qta = None


def _pixmap_to_png_bytes(pm: QPixmap) -> bytes:
    qimg = pm.toImage()
    if qimg.isNull():
        return b""
    ba = QByteArray()
    buf = QBuffer(ba)
    if not buf.open(QBuffer.OpenModeFlag.WriteOnly):
        return b""
    qimg.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def _write_ico_from_pngs(out_path: str, png_entries: list[tuple[int, int, bytes]]) -> bool:
    try:
        entries = [(int(w), int(h), bytes(b)) for (w, h, b) in png_entries if b]
    except Exception:
        entries = []
    if not entries:
        return False
    n = len(entries)
    header_size = 6
    dir_entry_size = 16
    offset = header_size + n * dir_entry_size

    parts = []
    parts.append((0).to_bytes(2, "little"))
    parts.append((1).to_bytes(2, "little"))
    parts.append((n).to_bytes(2, "little"))

    dir_bytes = bytearray()
    data_bytes = bytearray()
    for w, h, png in entries:
        ww = 0 if w >= 256 else w
        hh = 0 if h >= 256 else h
        dir_bytes += bytes([ww & 0xFF, hh & 0xFF, 0, 0])
        dir_bytes += (1).to_bytes(2, "little")
        dir_bytes += (32).to_bytes(2, "little")
        dir_bytes += (len(png)).to_bytes(4, "little")
        dir_bytes += (offset + len(data_bytes)).to_bytes(4, "little")
        data_bytes += png

    try:
        with open(out_path, "wb") as f:
            for p in parts:
                f.write(p)
            f.write(dir_bytes)
            f.write(data_bytes)
        return True
    except Exception:
        return False


def _fallback_png_entries(primary_color: str = "#2196F3") -> list[tuple[int, int, bytes]]:
    entries: list[tuple[int, int, bytes]] = []
    sizes = [16, 24, 32, 48, 64, 128, 256]
    bg = QColor(str(primary_color or "#2196F3"))
    for s in sizes:
        pm = QPixmap(int(s), int(s))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        except Exception:
            pass
        r = pm.rect()
        pad = max(1, int(round(float(s) * 0.06)))
        rr = r.adjusted(pad, pad, -pad, -pad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawEllipse(rr)
        font = QFont()
        font.setBold(True)
        font.setPointSize(max(6, int(round(float(s) * 0.52))))
        p.setFont(font)
        p.setPen(Qt.GlobalColor.white)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "栖")
        p.end()
        png = _pixmap_to_png_bytes(pm)
        if png:
            entries.append((int(s), int(s), png))
    return entries


def main():
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "ph.bird-fill.ico"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    icon = None
    try:
        if qta is not None:
            icon = qta.icon("ph.bird-fill", color="#2196F3")
    except Exception:
        icon = None
    try:
        sizes = [16, 24, 32, 48, 64, 128, 256]
        png_entries: list[tuple[int, int, bytes]] = []
        if icon is not None:
            for s in sizes:
                inner = int(round(float(s) * 0.86))
                inner = max(1, min(inner, s))
                pm_inner = icon.pixmap(inner, inner)
                if pm_inner.isNull():
                    continue
                pm = QPixmap(s, s)
                pm.fill(Qt.GlobalColor.transparent)
                p = QPainter(pm)
                try:
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                except Exception:
                    pass
                x = int((s - inner) / 2)
                y = int((s - inner) / 2)
                p.drawPixmap(x, y, pm_inner)
                p.end()
                png = _pixmap_to_png_bytes(pm)
                if png:
                    png_entries.append((s, s, png))
        if not png_entries:
            png_entries = _fallback_png_entries("#2196F3")
        if not _write_ico_from_pngs(out_path, png_entries):
            return 4
    except Exception:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
