from PyQt6.QtWidgets import (QHBoxLayout, QLabel, 
                             QPushButton, QComboBox)
from PyQt6.QtCore import Qt
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog

class CustomSelectionDialog(BasePopupDialog):
    """自定义选择对话框，风格匹配主界面"""
    
    def __init__(self, parent=None, title="选择", label="请选择:", items=None, current=0, editable=False):
        self.title = title
        self.label_text = label
        self.items = items or []
        self.current_index = current
        self.editable = editable
        self.selected_item = None
        self.ok = False
        self.drag_pos = None
        super().__init__(parent=parent, title=title, size=(400, 200))
        self.init_ui()
        
    def init_ui(self):
        cm = ColorManager.instance()
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text_color = cm.get("popup.text.primary", "#333333")
        # 边框颜色
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        primary_color = cm.get("theme.primary", "#2196F3")
        text_light_color = cm.get("theme.text.light", "#FFFFFF")
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
        
        # 下拉框
        self.combo_box = QComboBox()
        self.combo_box.addItems(self.items)
        if 0 <= self.current_index < len(self.items):
            self.combo_box.setCurrentIndex(self.current_index)
        self.combo_box.setEditable(self.editable)
        
        # 样式适配
        self.combo_box.setStyleSheet(f"""
            QComboBox {{
                padding: 6px 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 14px;
                color: {text_color};
                background-color: {control_bg};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 0px;
                border-top-right-radius: 3px;
                border-bottom-right-radius: 3px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {border_color};
                selection-background-color: {primary_color};
                selection-color: {text_light_color};
                background-color: {control_bg};
                color: {text_color};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {control_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {primary_color};
                color: {text_light_color};
            }}
        """)
        self.content_layout.addWidget(self.combo_box)
        
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
        
    def on_confirm(self):
        self.selected_item = self.combo_box.currentText()
        self.ok = True
        self.accept()
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    @staticmethod
    def getItem(parent, title, label, items, current=0, editable=False):
        dialog = CustomSelectionDialog(parent, title, label, items, current, editable)
        dialog.exec()
        return dialog.selected_item, dialog.ok
