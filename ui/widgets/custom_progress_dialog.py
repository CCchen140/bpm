from PyQt6.QtWidgets import (QLabel, QProgressBar)
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog

class CustomProgressDialog(BasePopupDialog):
    """自定义进度弹窗，风格匹配 CustomMessageBox"""
    
    def __init__(self, title="请稍候", message="正在处理...", parent=None):
        super().__init__(parent=parent, title=title, size=(400, 160))
        self.setModal(True)
        self.title = title
        self.message = message
        self.init_ui()
        
    def init_ui(self):
        cm = ColorManager.instance()
        popup_bg = cm.get("popup.background.primary", "#FFFFFF")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        text_color = cm.get("popup.text.primary", "#333333")
        primary_color = cm.get("theme.primary", "#2196F3")
        progress_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        self.set_bottom_bar_style(popup_bg, border_color)
        self.set_bottom_bar_visible(False)

        content_layout = self.content_layout
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        self.msg_label = QLabel(self.message)
        self.msg_label.setWordWrap(True)
        self.msg_label.setStyleSheet(f"""
            color: {text_color};
            font-size: 14px;
            border: none;
        """)
        content_layout.addWidget(self.msg_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {progress_bg};
                border-radius: 4px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {primary_color};
                border-radius: 4px;
            }}
        """)
        content_layout.addWidget(self.progress_bar)
        
        content_layout.addStretch()
        
    def setLabelText(self, text):
        self.msg_label.setText(text)
        
    def setMaximum(self, value):
        self.progress_bar.setMaximum(value)
        
    def setValue(self, value):
        self.progress_bar.setValue(value)
        
    def setAutoClose(self, auto_close):
        pass

    def closeEvent(self, event):
        super().closeEvent(event)
