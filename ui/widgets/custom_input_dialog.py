from PyQt6.QtWidgets import (QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit)
from PyQt6.QtCore import Qt
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog

class CustomInputDialog(BasePopupDialog):
    """自定义输入对话框，风格匹配主界面"""
    
    def __init__(self, parent=None, title="输入", label="请输入:", text="", placeholder=""):
        self.title = title
        self.label_text = label
        self.default_text = text
        self.placeholder = placeholder
        self.input_text = ""
        self.ok = False
        self.drag_pos = None
        super().__init__(parent=parent, title=title, size=(400, 200))
        self.init_ui()
        
    def init_ui(self):
        cm = ColorManager.instance()
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        primary_color = cm.get("theme.primary", "#2196F3")
        self.set_bottom_bar_style(self.get_footer_background(), border_color)

        msg_label = QLabel(self.label_text)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"""
            color: {text_color};
            font-size: 14px;
            border: none;
            background: transparent;
        """)
        self.content_layout.addWidget(msg_label)
        
        # 输入框
        self.line_edit = QLineEdit()
        self.line_edit.setText(self.default_text)
        self.line_edit.setPlaceholderText(self.placeholder)
        self.line_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 6px 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 14px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        self.line_edit.selectAll() # 默认全选文本，方便修改
        self.content_layout.addWidget(self.line_edit)
        
        # 确定按钮
        confirm_btn = QPushButton("确定")
        confirm_btn.setFixedSize(80, 32)
        self.apply_dialog_button_style(confirm_btn, "primary")
        confirm_btn.clicked.connect(self.on_confirm)
        
        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        self.apply_dialog_button_style(cancel_btn, "secondary")
        cancel_btn.clicked.connect(self.reject)
        
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(confirm_btn)
        
    def showEvent(self, event):
        super().showEvent(event)
        # 窗口显示后设置焦点并全选
        self.line_edit.setFocus()
        self.line_edit.selectAll()

    def on_confirm(self):
        self.input_text = self.line_edit.text()
        self.ok = True
        self.accept()

    def get_value(self):
        """获取输入的值"""
        return self.input_text
        
    @staticmethod
    def getText(parent, title, label, text="", placeholder=""):
        """
        静态方法，模拟 QInputDialog.getText
        返回: (text, ok)
        """
        dialog = CustomInputDialog(parent, title, label, text, placeholder)
        if dialog.exec():
            return dialog.input_text, True
        return "", False
