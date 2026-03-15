from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
                             QLineEdit, QPushButton, QFrame, QApplication, QGraphicsDropShadowEffect, QSizePolicy, QDialog)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QColor, QPixmap, QGuiApplication, QPainter, QFontDatabase
import os
import base64
from ui.utils.icon_loader import qta
from utils.system.id_utils import get_software_id
from utils.setting.settings_manager import SettingsManager
from utils.system.app_info_manager import AppInfoManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.color_manager import ColorManager
from ui.resources.about_images_data import ABOUT_IMAGES

class ClickableImageLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event is not None:
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.clicked.emit()
            except Exception:
                pass
        super().mousePressEvent(event)

class AboutImageOverlay(QDialog):
    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap if pixmap is not None else QPixmap()
        self._scaled_pixmap = QPixmap()
        self._container = QFrame()
        self._container.setStyleSheet(
            "QFrame { background-color: rgba(255,255,255,245); border-radius: 12px; border: 1px solid rgba(0,0,0,30); }"
        )

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background-color: transparent; border: none;")

        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.addWidget(self._label, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._container)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        except Exception:
            pass
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        except Exception:
            pass
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        try:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowFullScreen)
        except Exception:
            pass

        self._fit_to_screen()
        self._apply_pixmap()
        try:
            self.installEventFilter(self)
            self._container.installEventFilter(self)
            self._label.installEventFilter(self)
        except Exception:
            pass

    def paintEvent(self, event):
        try:
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0, 160))
        except Exception:
            pass
        super().paintEvent(event)

    def _apply_pixmap(self):
        pm = self._scaled_pixmap if not self._scaled_pixmap.isNull() else self._pixmap
        if pm is None or pm.isNull():
            self._label.clear()
            return
        self._label.setPixmap(pm)
        try:
            self._label.setFixedSize(pm.size())
        except Exception:
            pass

    def _fit_to_screen(self):
        try:
            screen = QGuiApplication.screenAt(self.cursor().pos()) or QGuiApplication.primaryScreen()
        except Exception:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        try:
            geo = screen.availableGeometry()
        except Exception:
            return
        try:
            self.setGeometry(geo)
        except Exception:
            pass
        try:
            max_w = max(320, int(geo.width() * 0.92))
            max_h = max(240, int(geo.height() * 0.92))
        except Exception:
            max_w, max_h = 1200, 800
        try:
            max_w = max(320, int(max_w * 0.88))
            max_h = max(240, int(max_h * 0.88))
        except Exception:
            pass
        pm = self._pixmap
        if pm is not None and not pm.isNull():
            try:
                self._scaled_pixmap = pm.scaled(QSize(int(max_w - 20), int(max_h - 20)), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            except Exception:
                self._scaled_pixmap = QPixmap()
        else:
            self._scaled_pixmap = QPixmap()
        try:
            pm2 = self._scaled_pixmap if not self._scaled_pixmap.isNull() else pm
            lw = pm2.width() if pm2 is not None else 0
            lh = pm2.height() if pm2 is not None else 0
            want_w = min(max_w, lw + 20)
            want_h = min(max_h, lh + 20)
            self._container.setFixedSize(QSize(int(want_w), int(want_h)))
        except Exception:
            pass

    def mousePressEvent(self, event):
        try:
            if event is not None:
                gp = event.globalPosition().toPoint()
                inside = False
                try:
                    tl = self._label.mapToGlobal(self._label.rect().topLeft())
                    br = self._label.mapToGlobal(self._label.rect().bottomRight())
                    inside = bool((tl.x() <= gp.x() <= br.x()) and (tl.y() <= gp.y() <= br.y()))
                except Exception:
                    inside = False
                if not inside:
                    self.close()
                    return
        except Exception:
            pass
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        try:
            if event is not None and event.key() == Qt.Key.Key_Escape:
                self.close()
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        try:
            if event is not None and event.type() == QEvent.Type.MouseButtonPress:
                gp = event.globalPosition().toPoint()
                inside = False
                try:
                    tl = self._label.mapToGlobal(self._label.rect().topLeft())
                    br = self._label.mapToGlobal(self._label.rect().bottomRight())
                    inside = bool((tl.x() <= gp.x() <= br.x()) and (tl.y() <= gp.y() <= br.y()))
                except Exception:
                    inside = False
                if not inside:
                    self.close()
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

class AboutImageStrip(QWidget):
    def __init__(self, pixmaps: list[QPixmap], parent=None):
        super().__init__(parent)
        self._pixmaps: list[QPixmap] = list(pixmaps or [])
        self._labels: list[ClickableImageLabel] = []
        self._spacing = 10
        self._target_height = 120

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self._spacing)

        for _ in self._pixmaps:
            lbl = ClickableImageLabel()
            lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("background-color: transparent; border: none;")
            self._labels.append(lbl)
            lay.addWidget(lbl)

        self.setFixedHeight(int(self._target_height))
        self._refresh_scaled_pixmaps()

    def set_target_height(self, h: int):
        try:
            self._target_height = int(max(40, h))
        except Exception:
            self._target_height = 120
        self.setFixedHeight(int(self._target_height))
        self._refresh_scaled_pixmaps()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scaled_pixmaps()

    def _refresh_scaled_pixmaps(self):
        n = len(self._labels)
        if n <= 0:
            return
        try:
            w = int(self.width())
            h = int(self.height())
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        cell_w = max(1, int((w - self._spacing * (n - 1)) / n))
        cell_h = max(1, int(h))

        for i, lbl in enumerate(self._labels):
            try:
                lbl.setFixedSize(QSize(int(cell_w), int(cell_h)))
            except Exception:
                pass
            pm = self._pixmaps[i] if i < len(self._pixmaps) else QPixmap()
            if pm.isNull():
                lbl.clear()
                continue
            try:
                scaled = pm.scaled(QSize(int(cell_w), int(cell_h)), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            except Exception:
                lbl.clear()
                continue
            lbl.setPixmap(scaled)

    def set_click_handler(self, handler):
        try:
            for i, lbl in enumerate(self._labels):
                try:
                    lbl.clicked.disconnect()
                except Exception:
                    pass
                try:
                    lbl.clicked.connect(lambda _=None, idx=int(i): handler(idx))
                except Exception:
                    pass
        except Exception:
            pass

class InfoPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings_manager = SettingsManager()
        self.init_ui()

    def _load_siyuan_bold_font_family(self) -> str:
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts", "siyuan")
        if not os.path.isdir(base_dir):
            return ""
        target = ""
        try:
            for fn in sorted(os.listdir(base_dir)):
                lower = fn.lower()
                if not lower.endswith((".otf", ".ttf", ".ttc")):
                    continue
                if "bold" in lower and "italic" not in lower:
                    target = os.path.join(base_dir, fn)
                    break
        except Exception:
            target = ""
        if not target or not os.path.exists(target):
            return ""
        try:
            font_id = QFontDatabase.addApplicationFont(target)
        except Exception:
            font_id = -1
        if int(font_id) < 0:
            return ""
        try:
            families = QFontDatabase.applicationFontFamilies(int(font_id))
        except Exception:
            families = []
        return str(families[0]) if families else ""

    def init_ui(self):
        # 主布局 - 居中显示卡片
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # === 卡片容器 ===
        self._card = QFrame()
        self._card.setFixedWidth(600)
        
        # 添加阴影效果
        self._card_shadow = QGraphicsDropShadowEffect(self)
        self._card_shadow.setBlurRadius(20)
        self._card_shadow.setOffset(0, 4)
        self._card.setGraphicsEffect(self._card_shadow)
        
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(40, 50, 40, 50)
        card_layout.setSpacing(30)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # === 1. 头部区域 (图标 + 标题 + 版本) ===
        header_layout = QVBoxLayout()
        header_layout.setSpacing(10)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 图标
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("background-color: transparent; border: none;")
        header_layout.addWidget(self._icon_label)
        
        # 标题
        self._title_label = QLabel(AppInfoManager.instance().get_app_name())
        siyuan_family = self._load_siyuan_bold_font_family()
        if siyuan_family:
            self._title_label.setFont(QFont(siyuan_family, 24, QFont.Weight.Bold))
        else:
            self._title_label.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._title_label)
        
        # 版本徽章
        version_str = AppInfoManager.instance().get_full_version()
        self._version_badge = QLabel(f"  {version_str}  ")
        self._version_badge.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._version_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # version_badge.setFixedSize(80, 24)
        
        # 用一个容器来居中版本号
        version_container = QWidget()
        version_container.setStyleSheet("background-color: transparent; border: none;")
        vc_layout = QHBoxLayout(version_container)
        vc_layout.setContentsMargins(0, 0, 0, 0)
        vc_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vc_layout.addWidget(self._version_badge)
        header_layout.addWidget(version_container)
        
        card_layout.addLayout(header_layout)

        # === 分隔线 ===
        self._line = QFrame()
        self._line.setFrameShape(QFrame.Shape.HLine)
        card_layout.addWidget(self._line)

        # === 2. Software ID 区域 ===
        id_group = QWidget()
        id_group.setStyleSheet("background-color: transparent; border: none;")
        id_group_layout = QVBoxLayout(id_group)
        id_group_layout.setContentsMargins(0, 0, 0, 0)
        id_group_layout.setSpacing(8)
        
        self._id_title = QLabel("Software ID")
        self._id_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        id_group_layout.addWidget(self._id_title)
        
        # ID 输入框容器
        self._id_box_container = QWidget()
        id_box_layout = QHBoxLayout(self._id_box_container)
        id_box_layout.setContentsMargins(15, 10, 15, 10)
        
        self.id_input = QLineEdit()
        self.id_input.setReadOnly(True)
        self.id_input.setText(get_software_id())
        self.id_input.setFont(QFont("Consolas", 13))
        
        self._copy_btn = QPushButton()
        self._copy_btn.setToolTip("复制到剪贴板")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setFixedSize(30, 30)
        self._copy_btn.clicked.connect(self.copy_id)
        cm = ColorManager.instance()
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        self._copy_btn.setStyleSheet(f"""
            QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
        """)

        id_box_layout.addWidget(self.id_input)
        id_box_layout.addWidget(self._copy_btn)
        
        id_group_layout.addWidget(self._id_box_container)
        
        self._id_tip = QLabel("此 ID 基于您的硬件生成，作为本设备的唯一标识。")
        self._id_tip.setFont(QFont("Segoe UI", 9))
        id_group_layout.addWidget(self._id_tip)
        
        card_layout.addWidget(id_group)

        # === 3. 联系方式区域 ===
        contact_group = QWidget()
        contact_group.setStyleSheet("background-color: transparent; border: none;")
        contact_layout = QVBoxLayout(contact_group)
        contact_layout.setContentsMargins(0, 0, 0, 0)
        contact_layout.setSpacing(15)
        
        self._contact_title = QLabel("CONTACT")
        self._contact_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        contact_layout.addWidget(self._contact_title)
        
        # QQ 交流群
        group_row = QWidget()
        group_layout = QHBoxLayout(group_row)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(15)
        
        self._group_icon = QLabel()
        self._group_icon.setFixedSize(24, 24)
        
        self._group_label = QLabel("QQ 交流群")
        self._group_label.setFont(QFont("Segoe UI", 11))
        
        self._group_value = QLabel("962628584")
        self._group_value.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._group_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        group_layout.addWidget(self._group_icon)
        group_layout.addWidget(self._group_label)
        group_layout.addStretch()
        group_layout.addWidget(self._group_value)
        
        contact_layout.addWidget(group_row)

        # 作者 QQ
        author_row = QWidget()
        author_layout = QHBoxLayout(author_row)
        author_layout.setContentsMargins(0, 0, 0, 0)
        author_layout.setSpacing(15)
        
        self._author_icon = QLabel()
        self._author_icon.setFixedSize(24, 24)
        
        self._author_label = QLabel("作者 QQ")
        self._author_label.setFont(QFont("Segoe UI", 11))
        
        self._author_value = QLabel("1401330388")
        self._author_value.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._author_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        author_layout.addWidget(self._author_icon)
        author_layout.addWidget(self._author_label)
        author_layout.addStretch()
        author_layout.addWidget(self._author_value)
        
        contact_layout.addWidget(author_row)

        # 作者小红书
        xhs_row = QWidget()
        xhs_layout = QHBoxLayout(xhs_row)
        xhs_layout.setContentsMargins(0, 0, 0, 0)
        xhs_layout.setSpacing(15)

        self._xhs_icon = QLabel()
        self._xhs_icon.setFixedSize(24, 24)

        self._xhs_label = QLabel("作者小红书")
        self._xhs_label.setFont(QFont("Segoe UI", 11))

        self._xhs_value = QLabel("94104027962")
        self._xhs_value.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._xhs_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        xhs_layout.addWidget(self._xhs_icon)
        xhs_layout.addWidget(self._xhs_label)
        xhs_layout.addStretch()
        xhs_layout.addWidget(self._xhs_value)

        contact_layout.addWidget(xhs_row)

        # bilibili 视频说明书
        bili_row = QWidget()
        bili_layout = QHBoxLayout(bili_row)
        bili_layout.setContentsMargins(0, 0, 0, 0)
        bili_layout.setSpacing(15)

        self._bili_icon = QLabel()
        self._bili_icon.setFixedSize(24, 24)

        self._bili_label = QLabel("bilibili视频说明书")
        self._bili_label.setFont(QFont("Segoe UI", 11))

        bili_url = "https://space.bilibili.com/8561895"
        self._bili_value = QLabel(f'<a href="{bili_url}">{bili_url}</a>')
        self._bili_value.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._bili_value.setOpenExternalLinks(True)
        self._bili_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        bili_layout.addWidget(self._bili_icon)
        bili_layout.addWidget(self._bili_label)
        bili_layout.addStretch()
        bili_layout.addWidget(self._bili_value)

        contact_layout.addWidget(bili_row)

        # 软件官网
        website_row = QWidget()
        website_layout = QHBoxLayout(website_row)
        website_layout.setContentsMargins(0, 0, 0, 0)
        website_layout.setSpacing(15)

        self._website_icon = QLabel()
        self._website_icon.setFixedSize(24, 24)

        self._website_label = QLabel("软件官网")
        self._website_label.setFont(QFont("Segoe UI", 11))

        website_url = "https://qitu-photo.top"
        self._website_value = QLabel(f'<a href="{website_url}">{website_url}</a>')
        self._website_value.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._website_value.setOpenExternalLinks(True)
        self._website_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        website_layout.addWidget(self._website_icon)
        website_layout.addWidget(self._website_label)
        website_layout.addStretch()
        website_layout.addWidget(self._website_value)

        contact_layout.addWidget(website_row)

        self._bili_tip = QLabel("如有bug或者任何建议，请使用以下方法联系我，后续会优先在QQ群内放出测试版")
        self._bili_tip.setWordWrap(True)
        self._bili_tip.setFont(QFont("Segoe UI", 9))
        contact_layout.addWidget(self._bili_tip)
        card_layout.addWidget(contact_group)
        
        keys = ["1.png", "2.jpg", "3.jpg", "5.png"]
        pixmaps = []
        for k in keys:
            pm = QPixmap()
            try:
                b64 = ABOUT_IMAGES.get(str(k))
                if b64:
                    pm.loadFromData(base64.b64decode(str(b64)))
            except Exception:
                pm = QPixmap()
            pixmaps.append(pm)
        self._about_image_strip = AboutImageStrip(pixmaps, self._card)
        self._about_image_strip.set_target_height(120)
        self._about_image_strip.set_click_handler(self._open_about_image_preview)
        card_layout.addSpacing(16)
        card_layout.addWidget(self._about_image_strip)

        # 将卡片添加到主布局
        main_layout.addWidget(self._card)

        self._apply_theme_styles()
        try:
            ColorManager.instance().register_listener(self._apply_theme_styles)
        except Exception:
            pass

    def _open_about_image_preview(self, idx: int):
        try:
            idx = int(idx)
        except Exception:
            idx = -1
        try:
            pm = self._about_image_strip._pixmaps[idx] if 0 <= idx < len(self._about_image_strip._pixmaps) else QPixmap()
        except Exception:
            pm = QPixmap()
        if pm.isNull():
            return
        try:
            dlg = AboutImageOverlay(pm, parent=self)
            dlg.exec()
        except Exception:
            pass

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        page_bg = cm.get("theme.background.primary")
        card_bg = cm.get("theme.background.light")
        card_border = cm.get("popup.border.primary")
        divider_color = cm.get("settings.shortcut_table.gridline")
        accent_color = cm.get("theme.primary")
        primary_text = cm.get("theme.text.dark")
        secondary_text = cm.get("settings.shortcut_table.header.text")
        input_border = cm.get("settings.shortcut_input.border")
        input_bg = cm.get("settings.shortcut_input.background")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background")
        shadow_color = cm.get("image_detail.nav_button.background")
        accent_bg = accent_color
        if isinstance(accent_color, str) and accent_color.startswith("#") and len(accent_color) == 7:
            accent_bg = f"{accent_color}1A"

        self.setStyleSheet(f"background-color: {page_bg};")
        self._card.setStyleSheet(f"""
            QFrame {{
                background-color: {card_bg};
                border-radius: 16px;
                border: 1px solid {card_border};
            }}
        """)
        self._card_shadow.setColor(QColor(shadow_color))
        self._icon_label.setPixmap(qta.icon('ph.bird-fill', color=accent_color).pixmap(80, 80))
        self._title_label.setStyleSheet(f"color: {accent_color}; background-color: transparent; border: none;")
        self._version_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {accent_bg};
                color: {accent_color};
                border-radius: 12px;
                padding: 4px 8px;
                border: none;
            }}
        """)
        self._line.setStyleSheet(f"background-color: {divider_color}; border: none;")
        self._id_title.setStyleSheet(f"color: {secondary_text}; text-transform: uppercase; letter-spacing: 1px;")
        self._id_box_container.setStyleSheet(f"""
            QWidget {{
                background-color: {input_bg};
                border: 1px solid {input_border};
                border-radius: 8px;
            }}
        """)
        self.id_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: transparent;
                border: none;
                color: {primary_text};
            }}
        """)
        self._copy_btn.setIcon(qta.icon('mdi6.content-copy', color=secondary_text))
        cm = ColorManager.instance()
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        self._copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
        """)
        self._id_tip.setStyleSheet(f"color: {secondary_text}; font-style: italic;")
        self._contact_title.setStyleSheet(f"color: {secondary_text}; text-transform: uppercase; letter-spacing: 1px;")
        self._group_icon.setPixmap(qta.icon('mdi6.qqchat', color=accent_color).pixmap(24, 24))
        self._group_label.setStyleSheet(f"color: {secondary_text};")
        self._group_value.setStyleSheet(f"color: {primary_text};")
        self._author_icon.setPixmap(qta.icon('mdi6.account', color=accent_color).pixmap(24, 24))
        self._author_label.setStyleSheet(f"color: {secondary_text};")
        self._author_value.setStyleSheet(f"color: {primary_text};")
        if hasattr(self, "_xhs_icon"):
            self._xhs_icon.setPixmap(qta.icon('ph.star-four-fill', color=accent_color).pixmap(24, 24))
        if hasattr(self, "_xhs_label"):
            self._xhs_label.setStyleSheet(f"color: {secondary_text};")
        if hasattr(self, "_xhs_value"):
            self._xhs_value.setStyleSheet(f"color: {primary_text};")
        if hasattr(self, "_bili_icon"):
            self._bili_icon.setPixmap(qta.icon('ri.bilibili-fill', color=accent_color).pixmap(24, 24))
        if hasattr(self, "_bili_label"):
            self._bili_label.setStyleSheet(f"color: {secondary_text};")
        if hasattr(self, "_bili_value"):
            self._bili_value.setStyleSheet(f"""
                QLabel {{
                    color: {primary_text};
                }}
                QLabel a {{
                    color: {primary_text};
                    text-decoration: underline;
                }}
            """)
        if hasattr(self, "_bili_tip"):
            self._bili_tip.setStyleSheet(f"color: {secondary_text};")
        # 软件官网图标
        if hasattr(self, "_website_icon"):
            self._website_icon.setPixmap(qta.icon('mdi6.web', color=accent_color).pixmap(24, 24))
        if hasattr(self, "_website_label"):
            self._website_label.setStyleSheet(f"color: {secondary_text};")
        if hasattr(self, "_website_value"):
            self._website_value.setStyleSheet(f"""
                QLabel {{
                    color: {primary_text};
                }}
                QLabel a {{
                    color: {primary_text};
                    text-decoration: underline;
                }}
            """)

    def copy_id(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.id_input.text())
        
        # 显示统一的 Toast 提示
        NotificationManager.instance().show_toast("已复制到剪贴板")
