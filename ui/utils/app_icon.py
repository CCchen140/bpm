from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from ui.utils.icon_loader import qta


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


def build_svg_icon(primary_color: str = "#2196F3") -> QIcon | None:
    """尝试从.ico文件加载图标"""
    try:
        import os
        # 查找.ico文件
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        ico_paths = [
            os.path.join(base_dir, 'build', 'ph.bird-fill.ico'),
            os.path.join(base_dir, 'build', 'test.ico'),
        ]
        
        for ico_path in ico_paths:
            if os.path.exists(ico_path):
                icon = QIcon(ico_path)
                if not icon.isNull():
                    return icon
    except Exception:
        pass
    
    return None


def get_app_icon(primary_color: str = "#2196F3") -> QIcon:
    try:
        ico_qta = qta.icon("ph.bird-fill", color=str(primary_color or "#2196F3"))
        if ico_qta is not None and not ico_qta.isNull():
            return ico_qta
    except Exception:
        pass
    ico = build_svg_icon(primary_color)
    if ico is not None and not ico.isNull():
        return ico
    return build_app_icon(primary_color)

