from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt
import qtawesome as qta
from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.utils.color_manager import ColorManager

class CustomMessageBox(BasePopupDialog):
    """自定义消息弹窗，继承自 BasePopupDialog 以保持风格一致"""
    
    # 类型常量
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    QUESTION = "question"
    
    def __init__(self, parent=None, title="提示", message="", mode=WARNING):
        super().__init__(parent, title, size=(400, 200))
        self.message = message
        self.mode = mode
        self.result_value = False
        
        self.init_message_ui()
        self.update_style_by_mode()
        
    def init_message_ui(self):
        # 内容区域布局
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # 图标
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        
        # 消息文本
        self.msg_label = QLabel(self.message)
        self.msg_label.setWordWrap(True)
        cm = ColorManager.instance()
        text_color = cm.get("popup.text.primary", "#333333")
        self.msg_label.setStyleSheet(f"""
            color: {text_color};
            font-size: 14px;
            border: none;
            background: transparent;
        """)
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.msg_label, 1)
        
        self.content_layout.addLayout(layout)
        
        # 按钮区域
        self.set_bottom_bar_visible(True)
        
        # 确定/是 按钮
        yes_text = "确定" if self.mode != self.QUESTION else "是"
        self.yes_btn = self.add_button(yes_text, self.accept, role="primary")
        
        # 否/取消 按钮
        if self.mode == self.QUESTION:
            self.no_btn = self.add_button("否", self.reject, role="secondary")
            
    def add_button(self, text, callback, role="secondary"):
        btn = QPushButton(text)
        btn.setFixedSize(80, 32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_dialog_button_style(btn, role)
        btn.clicked.connect(callback)
        self.bottom_layout.addWidget(btn)
        return btn

    def add_checkbox(self, text, default_checked=False):
        """添加复选框到内容区域底部"""
        from PyQt6.QtWidgets import QCheckBox
        self.checkbox = QCheckBox(text)
        self.checkbox.setChecked(default_checked)
        cm = ColorManager.instance()
        text_color = cm.get("popup.text.primary", "#333333")
        self.checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {text_color};
                font-size: 14px;
                margin-top: 10px;
            }}
        """)
        # 插入到内容布局的最后
        self.content_layout.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignLeft)
        
    def is_checkbox_checked(self):
        if hasattr(self, 'checkbox'):
            return self.checkbox.isChecked()
        return False

    def update_style_by_mode(self):
        cm = ColorManager.instance()
        
        # 默认颜色
        header_bg = cm.get("popup.header.background", "#2c3e50")
        header_text = cm.get("popup.header.text", "#ffffff")
        icon_color = cm.get("theme.primary", "#2196f3")
        icon_name = 'mdi6.information'
        
        if self.mode == self.WARNING:
            header_bg = "#ff9800" # 橙色
            icon_color = "#ff9800"
            icon_name = 'mdi6.alert'
        elif self.mode == self.ERROR:
            header_bg = "#f44336" # 红色
            icon_color = "#f44336"
            icon_name = 'mdi6.close-circle'
        elif self.mode == self.QUESTION:
            icon_color = cm.get("theme.primary", "#2196f3")
            icon_name = 'mdi6.help-circle'
            
        # 设置标题栏样式
        self.set_title_bar_style(header_bg, header_text)
        
        # 设置图标
        self.icon_label.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(48, 48))
        
        # 如果是错误模式，主按钮也用红色
        if self.mode == self.ERROR:
            self.yes_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #d32f2f;
                }}
            """)
