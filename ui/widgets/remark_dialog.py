from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QWidget, QComboBox, QPlainTextEdit
)
from PyQt6.QtCore import Qt
import os
import json

from ui.utils.notification_manager import NotificationManager
from ui.widgets.custom_input_dialog import CustomInputDialog
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog

class RemarkDialog(BasePopupDialog):
    def __init__(self, parent=None, current_remark=""):
        super().__init__(parent=parent, title="添加备注", size=(600, 450))
        self.current_remark = current_remark
        self.presets_dir = os.path.join(os.getcwd(), "data", "remark_presets")
        self.init_ui()
        self.load_presets()

    def init_ui(self):
        self.setWindowTitle("添加备注")
        self.setModal(True)

        cm = ColorManager.instance()
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        primary_color = cm.get("theme.primary", "#2196F3")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        disabled_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        text_light_color = cm.get("theme.text.light", "#FFFFFF")
        self.set_bottom_bar_style(self.get_footer_background(), border_color)

        header = QLabel("编辑图片备注信息")
        header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        header.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {text_color};")
        self.content_layout.addWidget(header)

        self.preset_combo = QComboBox()
        self.preset_combo.setEditable(False)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.preset_combo.setStyleSheet(f"""
            QComboBox {{
                padding: 6px 10px;
                border: 1px solid {border_color};
                background-color: {control_bg};
                font-size: 13px;
                min-width: 160px;
                color: {text_color};
            }}
            QComboBox:hover {{
                border: 1px solid {primary_color};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {text_color};
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {border_color};
                background-color: {control_bg};
                selection-background-color: {primary_color};
                selection-color: {text_light_color};
                color: {text_color};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {hover_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {primary_color};
                color: {text_light_color};
            }}
        """)

        preset_layout = QHBoxLayout()
        preset_label = QLabel("预设模板:")
        preset_label.setStyleSheet(f"color: {text_color};")
        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.preset_combo, 1)
        self.content_layout.addLayout(preset_layout)

        self.remark_edit = QPlainTextEdit()
        self.remark_edit.setPlaceholderText("在此输入备注信息...")
        self.remark_edit.setPlainText(self.current_remark)
        self.remark_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                padding: 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 14px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QPlainTextEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        self.content_layout.addWidget(self.remark_edit, 1)

        action_row = QHBoxLayout()
        
        self.delete_preset_btn = QPushButton("删除模板")
        self.delete_preset_btn.setFixedHeight(36)
        self.delete_preset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {control_bg};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 0px 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)
        self.delete_preset_btn.clicked.connect(self.delete_preset)
        action_row.addWidget(self.delete_preset_btn)

        action_row.addStretch()

        self.save_preset_btn = QPushButton("保存为模板")
        self.save_preset_btn.setFixedHeight(36)
        self.save_preset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary_color};
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 0px 14px;
            }}
            QPushButton:hover {{
                background-color: {primary_color};
            }}
            QPushButton:pressed {{
                background-color: {primary_color};
            }}
            QPushButton:disabled {{
                background-color: {disabled_bg};
            }}
        """)
        self.save_preset_btn.clicked.connect(self.save_preset)
        action_row.addWidget(self.save_preset_btn)

        self.content_layout.addLayout(action_row)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        self.apply_dialog_button_style(cancel_btn, "secondary")
        cancel_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton("确定")
        confirm_btn.setFixedSize(80, 32)
        self.apply_dialog_button_style(confirm_btn, "primary")
        confirm_btn.clicked.connect(self.accept)

        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(confirm_btn)

    def get_remark(self):
        return self.remark_edit.toPlainText()

    def load_presets(self):
        if not os.path.exists(self.presets_dir):
            os.makedirs(self.presets_dir, exist_ok=True)
        files = [f for f in os.listdir(self.presets_dir) if f.endswith(".txt")]
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("选择模板...", "")
        for f in files:
            name = os.path.splitext(f)[0]
            self.preset_combo.addItem(name, os.path.join(self.presets_dir, f))
        self.preset_combo.blockSignals(False)

    def delete_preset(self):
        index = self.preset_combo.currentIndex()
        path = self.preset_combo.itemData(index)
        if not path:
            return
        
        name = self.preset_combo.currentText()
        if not NotificationManager.instance().ask_confirmation("确认删除", f"确定要删除模板 '{name}' 吗？"):
            return
        try:
            if os.path.exists(path):
                os.remove(path)
            NotificationManager.instance().show_toast(f"模板 '{name}' 已删除")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"删除失败: {e}")
        self.load_presets()

    def on_preset_changed(self, index):
        path = self.preset_combo.itemData(index)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.remark_edit.setPlainText(content)
        except Exception as e:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().warning(f"加载备注模板失败: {e}")
            except Exception:
                pass

    def save_preset(self):
        content = self.get_remark()
        if not content:
            NotificationManager.instance().show_warning("提示", "备注内容为空")
            return
            
        dialog = CustomInputDialog(self, "保存备注模板", "模板名称:", "")
        if not dialog.exec():
            return
        name = dialog.get_value()
        if not name:
            return
        if any(c in name for c in '<>:"/\\|?*'):
            NotificationManager.instance().show_warning("错误", "名称包含非法字符")
            return
        
        if not os.path.exists(self.presets_dir):
            os.makedirs(self.presets_dir, exist_ok=True)
            
        file_path = os.path.join(self.presets_dir, f"{name}.txt")
        if os.path.exists(file_path):
            if not NotificationManager.instance().ask_confirmation("确认覆盖", f"模板 '{name}' 已存在，是否覆盖？"):
                return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            NotificationManager.instance().show_toast("备注模板已保存")
            self.load_presets()
            # Select the newly saved preset
            index = self.preset_combo.findText(name)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"保存失败: {e}")
