from PyQt6.QtWidgets import QPushButton
from ui.utils.color_manager import ColorManager

class RatingFilterButton(QPushButton):
    def __init__(self):
        super().__init__()
        self.modes = ["=", "≥", "≤"]
        self.current_mode = 0
        self.setText(self.modes[0])
        self.setFixedSize(28, 28)
        self.setToolTip("点击切换: 等于/大于等于/小于等于")
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()
        self.clicked.connect(self.toggle_mode)

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        text_dark = cm.get("theme.text.dark")
        hover_bg = cm.get("theme.background.dark")
        border = cm.get("popup.border.primary")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                color: {text_dark};
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border: 1px solid {border};
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
            }}
        """)

    def toggle_mode(self):
        self.current_mode = (self.current_mode + 1) % 3
        self.setText(self.modes[self.current_mode])

    def get_mode(self):
        return self.modes[self.current_mode]
