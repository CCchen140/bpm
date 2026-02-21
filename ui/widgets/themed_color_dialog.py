from PyQt6.QtWidgets import QWidget, QVBoxLayout, QColorDialog, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.utils.color_manager import ColorManager


class ThemedColorDialog(BasePopupDialog):
    def __init__(self, parent=None, title: str = "选择颜色", initial: QColor | None = None, show_alpha: bool = True):
        super().__init__(parent=parent, title=str(title or "选择颜色"), size=(620, 460), translucent_background=False)
        self._show_alpha = bool(show_alpha)
        self._selected_color: QColor | None = None

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
                f"QLineEdit,QSpinBox,QDoubleSpinBox{{background:{control_bg}; color:{text}; border:1px solid {border}; border-radius:4px; padding:4px 6px;}}"
                f"QAbstractButton{{background:{control_bg}; color:{text}; border:1px solid {border}; border-radius:4px; padding:6px 10px;}}"
                f"QAbstractButton:hover{{background:{hover_bg}; border:1px solid {primary};}}"
            )
        except Exception:
            pass
