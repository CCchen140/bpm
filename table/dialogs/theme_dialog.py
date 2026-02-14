from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.widgets.themed_combo_box import ThemedComboBox


THEME_OPTIONS = [
    ("follow", "跟随软件主题"),
    ("light", "浅色主题（占位）"),
    ("dark", "深色主题（占位）"),
    ("echarts_default", "图表默认主题（占位）"),
]


class ThemeDialog(BasePopupDialog):
    def __init__(self, parent=None, current_theme: str | None = None):
        super().__init__(parent=parent, title="修改主题", size=(720, 360))
        self._current_theme = str(current_theme or "")
        self._build_ui()
        try:
            ColorManager.instance().register_listener(self.apply_theme_styles)
        except Exception:
            pass
        self.apply_theme_styles()

    def _build_ui(self):
        header = QLabel("选择主题（应用到所有图表）")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.content_layout.addWidget(header)

        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.theme_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in THEME_OPTIONS:
            self.theme_combo.addItem(title, key)
        form.addRow("主题", self.theme_combo)
        self.content_layout.addWidget(wrap)

        idx = self.theme_combo.findData(self._current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确定")
        self.apply_dialog_button_style(cancel_btn, "secondary")
        self.apply_dialog_button_style(ok_btn, "primary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(ok_btn)

    def apply_theme_styles(self):
        cm = ColorManager.instance()
        content_bg = cm.get("theme.background.light", "#FFFFFF")
        footer_bg = cm.get("theme.background.dark", "#E7E7E7")
        border = cm.get("popup.border.primary", "#D0D0D0")
        header_bg = cm.get("popup.header.background", "#2c3e50")
        header_text = cm.get("popup.header.text", "#FFFFFF")
        close_hover_bg = cm.get("popup.header.close_button.hover_background", "#FFFFFF1A")
        self.set_title_bar_style(header_bg, header_text, hover_background=close_hover_bg)
        self.set_bottom_bar_style(footer_bg, border_color=border)
        try:
            if self.container:
                self.container.setStyleSheet(f"""
                    QWidget#container {{
                        background-color: {content_bg};
                        border: 1px solid {border};
                        border-radius: 8px;
                    }}
                """)
        except Exception:
            pass

    def get_theme(self) -> str:
        return str(self.theme_combo.currentData() or "")

