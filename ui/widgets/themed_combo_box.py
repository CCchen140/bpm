import os
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtCore import QUrl
from ui.utils.color_manager import ColorManager
from ui.common.icon_utils import get_arrow_down_svg_base64


class ThemedComboBox(QComboBox):
    def __init__(self, parent=None, font_size=12, padding="4px 8px"):
        super().__init__(parent)
        self._font_size = font_size
        self._padding = padding
        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()

    def apply_theme_styles(self):
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary")
        text_dark = cm.get("theme.text.dark")
        text_light = cm.get("theme.text.light")
        light_bg = cm.get("theme.background.light")
        dark_bg = cm.get("theme.background.dark")
        primary = cm.get("theme.primary")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        
        # 使用Base64编码的SVG箭头，避免中文路径问题
        arrow_url = get_arrow_down_svg_base64(text_dark)
        
        self.setStyleSheet(f"""
            QComboBox {{
                padding: {self._padding};
                border: 1px solid {border};
                border-radius: 4px;
                background-color: {light_bg};
                font-size: {self._font_size}px;
                color: {text_dark};
            }}
            QComboBox:hover {{
                border: 1px solid {primary};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({arrow_url});
                width: 12px;
                height: 12px;
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {border};
                background-color: {light_bg};
                selection-background-color: {primary};
                selection-color: {text_light};
                color: {text_dark};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {dark_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {primary};
                color: {text_light};
            }}
            QComboBox QAbstractItemView QScrollBar:vertical {{
                background-color: {light_bg};
                width: 8px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical {{
                background-color: {border};
                min-height: 24px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {{
                background-color: {primary};
            }}
            QComboBox QAbstractItemView QScrollBar::add-line:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QComboBox QAbstractItemView QScrollBar::add-page:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
            }}
        """)
