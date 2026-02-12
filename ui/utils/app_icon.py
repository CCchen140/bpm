from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


def build_app_icon(primary_color: str = "#2196F3") -> QIcon:
    ico = QIcon()
    sizes = (16, 24, 32, 48, 64, 128, 256)
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
        ico.addPixmap(pm)
    return ico


def build_qtawesome_icon(primary_color: str = "#2196F3") -> QIcon | None:
    try:
        import qtawesome as qta
    except Exception:
        return None

    try:
        base_icon = qta.icon("ph.bird-fill", color=str(primary_color or "#2196F3"))
    except Exception:
        base_icon = None
    if base_icon is None:
        return None

    ico = QIcon()
    added = 0
    for s in (16, 24, 32, 48, 64, 128, 256):
        try:
            pm = base_icon.pixmap(int(s), int(s))
            if pm is not None and (not pm.isNull()):
                ico.addPixmap(pm)
                added += 1
        except Exception:
            continue
    if added <= 0:
        return None
    return ico


def get_app_icon(primary_color: str = "#2196F3") -> QIcon:
    ico = build_qtawesome_icon(primary_color)
    if ico is not None and not ico.isNull():
        return ico
    return build_app_icon(primary_color)

