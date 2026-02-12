from PyQt6.QtWidgets import QWidget, QHBoxLayout, QFrame, QSlider
from ui.common.styles import TOOLBAR_BTN_STYLE
from ui.utils.color_manager import ColorManager

class BaseToolbar(QWidget):
    """
    基础工具栏组件
    提供统一的样式和布局管理
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_style()
        self.init_layout()
        ColorManager.instance().register_listener(self.init_style)
        
    def init_style(self):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.primary")
        border = cm.get("popup.border.primary")
        slider_groove = cm.get("theme.background.dark")
        slider_handle = cm.get("theme.primary")
        slider_sub = cm.get("theme.primary")
        slider_add = cm.get("theme.background.dark")
        self.setFixedHeight(36)
        self.setObjectName("BaseToolbar")
        self.setStyleSheet(f"""
            #BaseToolbar {{
                background-color: {bg};
                border-bottom: 1px solid {border};
            }}
        """)
        slider_style = f"""
            QSlider {{
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 6px;
                background: {slider_groove};
                margin: 15px 0;
            }}
            QSlider::handle:horizontal {{
                width: 12px;
                height: 20px;
                background: {slider_handle};
                border-radius: 2px;
                margin: -7px 0;
            }}
            QSlider::handle:horizontal:hover {{
                background: {slider_handle};
            }}
            QSlider::sub-page:horizontal {{
                background: {slider_sub};
                height: 6px;
                margin: 15px 0;
            }}
            QSlider::add-page:horizontal {{
                background: {slider_add};
                height: 6px;
                margin: 15px 0;
            }}
        """
        for slider in self.findChildren(QSlider):
            slider.setStyleSheet(slider_style)
        
    def init_layout(self):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 0, 8, 0)
        self.layout.setSpacing(8)

    def add_widget(self, widget):
        self.layout.addWidget(widget)
        
    def add_separator(self):
        # 使用透明间隔代替原来的竖线
        spacer = QFrame()
        spacer.setFrameShape(QFrame.Shape.NoFrame)
        spacer.setStyleSheet("background: transparent;")
        spacer.setFixedWidth(4) 
        self.layout.addWidget(spacer)
        
    def add_stretch(self):
        self.layout.addStretch()
