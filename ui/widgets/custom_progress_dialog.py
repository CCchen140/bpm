from PyQt6.QtWidgets import (QLabel, QProgressBar, QHBoxLayout, QWidget)
from PyQt6.QtCore import Qt
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog

class CustomProgressDialog(BasePopupDialog):
    """自定义进度弹窗，风格匹配 CustomMessageBox"""
    
    def __init__(self, title="请稍候", message="正在处理...", parent=None):
        super().__init__(parent=parent, title=title, size=(400, 180))
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
        
        # GPU/CPU 状态显示
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(10)
        
        self.device_label = QLabel("检测中...")
        self.device_label.setStyleSheet(f"""
            color: {text_color};
            font-size: 12px;
            border: none;
        """)
        status_layout.addWidget(self.device_label)
        status_layout.addStretch()
        
        self.reason_label = QLabel("")
        self.reason_label.setStyleSheet(f"""
            color: {primary_color};
            font-size: 11px;
            border: none;
        """)
        self.reason_label.setWordWrap(True)
        status_layout.addWidget(self.reason_label)
        
        content_layout.addWidget(status_widget)
        
        content_layout.addStretch()
        
    def setLabelText(self, text):
        self.msg_label.setText(text)
        
    def setMaximum(self, value):
        self.progress_bar.setMaximum(value)
        
    def setValue(self, value):
        self.progress_bar.setValue(value)
        
    def setDeviceInfo(self, use_gpu: bool, reason: str = ""):
        """设置 GPU/CPU 状态信息
        
        Args:
            use_gpu: 是否使用 GPU
            reason: 未使用 GPU 的原因
        """
        if use_gpu:
            self.device_label.setText("🚀 使用 GPU 加速")
            self.device_label.setStyleSheet(f"""
                color: #4CAF50;
                font-size: 12px;
                font-weight: bold;
                border: none;
            """)
            self.reason_label.setText("")
        else:
            self.device_label.setText("💻 使用 CPU")
            self.device_label.setStyleSheet(f"""
                color: #FF9800;
                font-size: 12px;
                font-weight: bold;
                border: none;
            """)
            if reason:
                self.reason_label.setText(f"原因: {reason}")
            else:
                self.reason_label.setText("")
        
    def setAutoClose(self, auto_close):
        pass

    def closeEvent(self, event):
        super().closeEvent(event)
