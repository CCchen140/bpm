from PyQt6.QtWidgets import QWidget, QVBoxLayout, QColorDialog, QPushButton, QLabel, QGroupBox, QAbstractButton, QTabWidget
from PyQt6.QtCore import Qt, QTimer, QTranslator, QCoreApplication, QLibraryInfo, QLocale
from PyQt6.QtGui import QColor

from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.utils.color_manager import ColorManager


class ThemedColorDialog(BasePopupDialog):
    _qt_translator_installed = False

    def __init__(self, parent=None, title: str = "选择颜色", initial: QColor | None = None, show_alpha: bool = True):
        super().__init__(parent=parent, title=str(title or "选择颜色"), size=(640, 480), translucent_background=True)
        self._show_alpha = bool(show_alpha)
        self._selected_color: QColor | None = None

        self._ensure_qt_translator()

        self._picker = QColorDialog(self)
        try:
            self._picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        except Exception:
            pass
        try:
            self._picker.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
        except Exception:
            pass
        try:
            self._picker.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, bool(self._show_alpha))
        except Exception:
            pass
        try:
            if isinstance(initial, QColor):
                self._picker.setCurrentColor(initial)
        except Exception:
            pass

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._picker, 1)
        self.content_layout.addWidget(body, 1)

        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确定")
        try:
            cancel_btn.setFixedSize(110, 36)
            ok_btn.setFixedSize(110, 36)
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        except Exception:
            pass
        self.apply_dialog_button_style(cancel_btn, "secondary")
        self.apply_dialog_button_style(ok_btn, "primary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self._accept_color)
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(ok_btn)

        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()
        self._localize_picker()

    def _accept_color(self):
        try:
            self._selected_color = self._picker.currentColor()
        except Exception:
            self._selected_color = None
        self.accept()

    def selected_color(self) -> QColor | None:
        try:
            return self._selected_color if isinstance(self._selected_color, QColor) else None
        except Exception:
            return None

    def _localize_picker(self):
        mapping = {
            "select color": "选择颜色",
            "basic colors": "基础颜色",
            "custom colors": "自定义颜色",
            "hue": "色相",
            "sat": "饱和度",
            "val": "明度",
            "red": "红",
            "green": "绿",
            "blue": "蓝",
            "alpha": "透明度",
            "color": "颜色",
            "add to custom colors": "添加到自定义颜色",
            "pick screen color": "屏幕取色",
            "screen": "屏幕",
            "h": "色相",
            "s": "饱和度",
            "v": "明度",
            "r": "红",
            "g": "绿",
            "b": "蓝",
            "rgb": "RGB",
            "hsv": "HSV",
            "html": "HTML",
        }
        def translate(text: str) -> str | None:
            raw = str(text or "").strip()
            if not raw:
                return None
            norm = raw.rstrip(":").strip().lower()
            return mapping.get(norm)
        try:
            for label in self._picker.findChildren(QLabel):
                text = str(label.text() or "").strip()
                mapped = translate(text)
                if mapped:
                    label.setText(mapped)
        except Exception:
            pass
        try:
            for group in self._picker.findChildren(QGroupBox):
                title = str(group.title() or "").strip()
                mapped = translate(title)
                if mapped:
                    group.setTitle(mapped)
        except Exception:
            pass
        try:
            for btn in self._picker.findChildren(QAbstractButton):
                text = str(btn.text() or "").strip()
                mapped = translate(text)
                if mapped:
                    btn.setText(mapped)
                tooltip = str(btn.toolTip() or "").strip()
                mapped_tip = translate(tooltip)
                if mapped_tip:
                    btn.setToolTip(mapped_tip)
        except Exception:
            pass
        try:
            for tab in self._picker.findChildren(QTabWidget):
                for i in range(tab.count()):
                    text = str(tab.tabText(i) or "").strip()
                    mapped = translate(text)
                    if mapped:
                        tab.setTabText(i, mapped)
        except Exception:
            pass
        try:
            if self.title_label:
                mapped = translate(self.title_label.text())
                if mapped:
                    self.title_label.setText(mapped)
        except Exception:
            pass

    def _ensure_qt_translator(self):
        if bool(getattr(ThemedColorDialog, "_qt_translator_installed", False)):
            return
        try:
            app = QCoreApplication.instance()
        except Exception:
            app = None
        if app is None:
            return
        try:
            translator = QTranslator(app)
            locale = QLocale(QLocale.Language.Chinese, QLocale.Country.China)
            trans_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            if translator.load(locale, "qtbase", "_", trans_path):
                app.installTranslator(translator)
                ThemedColorDialog._qt_translator_installed = True
        except Exception:
            pass

    @staticmethod
    def get_color(parent=None, title: str = "选择颜色", initial_rgba: list[int] | None = None, show_alpha: bool = True) -> QColor | None:
        init = None
        try:
            rgba = list(initial_rgba or [])
        except Exception:
            rgba = []
        if len(rgba) >= 3:
            try:
                r = int(max(0, min(255, int(rgba[0]))))
                g = int(max(0, min(255, int(rgba[1]))))
                b = int(max(0, min(255, int(rgba[2]))))
                a = int(max(0, min(255, int(rgba[3] if len(rgba) > 3 else 255))))
                init = QColor(int(r), int(g), int(b), int(a))
            except Exception:
                init = None
        dlg = ThemedColorDialog(parent=parent, title=str(title or "选择颜色"), initial=init, show_alpha=bool(show_alpha))
        if dlg.exec():
            return dlg.selected_color()
        return None

    def apply_theme_styles(self):
        try:
            super().apply_theme_styles()
        except Exception:
            pass
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.light", "#FFFFFF")
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text = cm.get("popup.text.primary", "#333333")
        border = cm.get("popup.border.primary", "#D0D0D0")
        hover_bg = cm.get("settings.shortcut_reset.hover_background", "#2196F31A")
        primary = cm.get("theme.primary", "#2196F3")
        try:
            self._picker.setStyleSheet(
                f"QColorDialog{{background:{panel_bg}; color:{text};}}"
                f"QColorDialog QWidget{{background:{panel_bg}; color:{text};}}"
                f"QLabel{{color:{text};}}"
                f"QGroupBox{{border:1px solid {border}; border-radius:6px; margin-top:10px; padding:6px;}}"
                f"QGroupBox::title{{subcontrol-origin: margin; left:10px; padding:0 6px; color:{text};}}"
                f"QTabWidget::pane{{border:1px solid {border}; border-radius:6px; top:-1px;}}"
                f"QTabBar::tab{{background:{control_bg}; color:{text}; padding:6px 12px; border:1px solid {border}; border-bottom:none; border-top-left-radius:6px; border-top-right-radius:6px; margin-right:4px;}}"
                f"QTabBar::tab:selected{{background:{panel_bg}; color:{text}; border:1px solid {border};}}"
                f"QLineEdit,QSpinBox,QDoubleSpinBox{{background:{control_bg}; color:{text}; border:1px solid {border}; border-radius:4px; padding:4px 6px;}}"
                f"QAbstractButton{{background:{control_bg}; color:{text}; border:1px solid {border}; border-radius:4px; padding:6px 10px;}}"
                f"QAbstractButton:hover{{background:{hover_bg}; border:1px solid {primary};}}"
                f"QSlider::groove:horizontal{{height:6px; background:{border}; border-radius:3px;}}"
                f"QSlider::handle:horizontal{{background:{primary}; width:14px; margin:-4px 0; border-radius:7px;}}"
                f"QSlider::groove:vertical{{width:6px; background:{border}; border-radius:3px;}}"
                f"QSlider::handle:vertical{{background:{primary}; height:14px; margin:0 -4px; border-radius:7px;}}"
                f"QColorDialog QWellArray{{background:{panel_bg}; border:1px solid {border};}}"
                f"QColorDialog QWellArray::item{{border:1px solid {border};}}"
                f"QColorDialog QWellArray::item:selected{{border:1px solid {primary};}}"
                f"QColorDialog QWidget#qt_color_well{{background:{panel_bg}; border:1px solid {border};}}"
                f"QColorDialog QFrame{{border:1px solid {border};}}"
            )
        except Exception:
            pass
        self._localize_picker()

    def showEvent(self, event):
        try:
            super().showEvent(event)
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._localize_picker)
            QTimer.singleShot(200, self._localize_picker)
        except Exception:
            pass
