from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog


class DisplayOptionsDialog(BasePopupDialog):
    def __init__(self, parent=None, current_options: dict | None = None):
        super().__init__(parent=parent, title="修改显示效果", size=(760, 480))
        self._current_options = dict(current_options or {})
        self._build_ui()
        try:
            ColorManager.instance().register_listener(self.apply_theme_styles)
        except Exception:
            pass
        self.apply_theme_styles()

    def _build_ui(self):
        header = QLabel("显示效果（应用到所有图表）")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.content_layout.addWidget(header)

        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.cb_title = QCheckBox("显示标题")
        self.cb_legend = QCheckBox("显示图例")
        self.cb_grid = QCheckBox("显示网格")
        self.cb_animation = QCheckBox("启用动画")

        self.cb_title.setChecked(bool(self._current_options.get("show_title", True)))
        self.cb_legend.setChecked(bool(self._current_options.get("show_legend", True)))
        self.cb_grid.setChecked(bool(self._current_options.get("show_grid", True)))
        self.cb_animation.setChecked(bool(self._current_options.get("enable_animation", True)))

        form.addRow("标题", self.cb_title)
        form.addRow("图例", self.cb_legend)
        form.addRow("网格", self.cb_grid)
        form.addRow("动画", self.cb_animation)

        self.font_size = QSpinBox()
        self.font_size.setRange(9, 24)
        self.font_size.setValue(int(self._current_options.get("font_size", 12) or 12))
        form.addRow("字体大小", self.font_size)

        self.content_layout.addWidget(wrap)

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

    def get_options(self) -> dict:
        return {
            "show_title": bool(self.cb_title.isChecked()),
            "show_legend": bool(self.cb_legend.isChecked()),
            "show_grid": bool(self.cb_grid.isChecked()),
            "enable_animation": bool(self.cb_animation.isChecked()),
            "font_size": int(self.font_size.value()),
        }

