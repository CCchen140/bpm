import os
import json

from ui.utils.icon_loader import qta
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
)
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from utils.paths import PathManager


class ExifReadDialog(BasePopupDialog):
    def __init__(self, parent=None, image_path=None):
        super().__init__(parent=parent, title="读取Exif信息", size=(680, 280))
        self.image_path = image_path
        pm = PathManager.instance()
        self.presets_dir = str(pm.get_user_data_path() / "exif_read_presets")
        self._migrate_legacy_presets(str(pm.get_app_data_path() / "exif_read_presets"))
        self.init_ui()
        self.load_presets()

    def _migrate_legacy_presets(self, legacy_dir: str):
        try:
            src_dir = str(legacy_dir or "")
        except Exception:
            src_dir = ""
        if not src_dir:
            return
        try:
            if not os.path.isdir(src_dir):
                return
        except Exception:
            return
        try:
            os.makedirs(self.presets_dir, exist_ok=True)
        except Exception:
            return
        try:
            for name in os.listdir(src_dir):
                if not str(name).lower().endswith(".json"):
                    continue
                src = os.path.join(src_dir, str(name))
                dst = os.path.join(self.presets_dir, str(name))
                try:
                    if os.path.exists(dst):
                        continue
                except Exception:
                    pass
                try:
                    with open(src, "rb") as rf:
                        data = rf.read()
                    with open(dst, "wb") as wf:
                        wf.write(data)
                except Exception:
                    pass
        except Exception:
            return
    def init_ui(self):
        self.setWindowTitle("读取Exif信息")
        self.setModal(True)

        cm = ColorManager.instance()
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        header_bg = cm.get("popup.header.background", "#2c3e50")
        header_text_color = cm.get("popup.header.text", "#FFFFFF")
        primary_color = cm.get("theme.primary", "#2196F3")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        disabled_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")

        self.set_title_bar_style(header_bg, header_text_color, hover_bg)
        self.set_bottom_bar_style(self.get_footer_background(), border_color)

        header = QLabel("读取当前图片的单个 Exif 标签")
        header.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {text_color};")
        self.content_layout.addWidget(header)

        preset_row = QHBoxLayout()
        preset_label = QLabel("预设方案:")
        preset_label.setStyleSheet(f"color: {text_color};")
        preset_row.addWidget(preset_label)
        self.preset_combo = QComboBox()
        self.preset_combo.setEditable(False)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        # 使用Base64编码的SVG箭头，避免中文路径问题
        from ui.common.icon_utils import get_arrow_down_svg_base64
        arrow_url = get_arrow_down_svg_base64(text_color)
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
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({arrow_url});
                width: 12px;
                height: 12px;
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {border_color};
                background-color: {control_bg};
                selection-background-color: {primary_color};
                selection-color: {header_text_color};
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
                color: {header_text_color};
            }}
        """)
        preset_row.addWidget(self.preset_combo, 1)

        self.save_preset_btn = QPushButton("保存为预设")
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
        preset_row.addWidget(self.save_preset_btn)

        self.delete_preset_btn = QPushButton("删除预设")
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
        preset_row.addWidget(self.delete_preset_btn)
        self.content_layout.addLayout(preset_row)

        tag_row = QHBoxLayout()
        tag_label = QLabel("标签名:")
        tag_label.setStyleSheet(f"color: {text_color};")
        tag_row.addWidget(tag_label)
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("例如: Xmp:Score 或 ExifIFD:ISO")
        self.tag_edit.setMinimumHeight(36)
        self.tag_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
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
        tag_row.addWidget(self.tag_edit, 1)
        self.content_layout.addLayout(tag_row)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        self.apply_dialog_button_style(cancel_btn, "secondary")
        cancel_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton("读取")
        confirm_btn.setFixedSize(80, 32)
        self.apply_dialog_button_style(confirm_btn, "primary")
        confirm_btn.clicked.connect(self.accept)

        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(confirm_btn)

    def get_tag_name(self):
        return (self.tag_edit.text() or "").strip()

    def load_presets(self):
        if not os.path.exists(self.presets_dir):
            os.makedirs(self.presets_dir, exist_ok=True)
        files = [f for f in os.listdir(self.presets_dir) if f.endswith(".json")]
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("不使用预设", "")
        for f in files:
            name = os.path.splitext(f)[0]
            self.preset_combo.addItem(name, os.path.join(self.presets_dir, f))
        self.preset_combo.blockSignals(False)

    def delete_preset(self):
        index = self.preset_combo.currentIndex()
        path = self.preset_combo.itemData(index)
        if not path:
            return
        from ui.utils.notification_manager import NotificationManager
        name = self.preset_combo.currentText()
        if not NotificationManager.instance().ask_confirmation("确认删除", f"确定要删除预设 '{name}' 吗？"):
            return
        try:
            if os.path.exists(path):
                os.remove(path)
            NotificationManager.instance().show_toast(f"预设 '{name}' 已删除")
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"删除失败: {e}")
        self.load_presets()

    def on_preset_changed(self, index):
        path = self.preset_combo.itemData(index)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                tag = data.get("tag", "")
            else:
                tag = str(data)
            self.tag_edit.setText(tag)
        except Exception:
            return

    def save_preset(self):
        tag = self.get_tag_name()
        if not tag:
            return
        from ui.widgets.custom_input_dialog import CustomInputDialog
        dialog = CustomInputDialog(self, "保存Exif预设", "预设名称:", "")
        if not dialog.exec():
            return
        name = dialog.get_value()
        if not name:
            return
        if any(c in name for c in '<>:"/\\|?*'):
            from ui.utils.notification_manager import NotificationManager
            NotificationManager.instance().show_warning("错误", "名称包含非法字符")
            return
        if not os.path.exists(self.presets_dir):
            os.makedirs(self.presets_dir, exist_ok=True)
        file_path = os.path.join(self.presets_dir, f"{name}.json")
        if os.path.exists(file_path):
            from ui.utils.notification_manager import NotificationManager
            if not NotificationManager.instance().ask_confirmation("确认覆盖", f"预设 '{name}' 已存在，是否覆盖？"):
                return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"tag": tag}, f, ensure_ascii=False, indent=2)
            from ui.utils.notification_manager import NotificationManager
            NotificationManager.instance().show_toast("Exif预设已保存")
            self.load_presets()
        except Exception as e:
            from ui.utils.notification_manager import NotificationManager
            NotificationManager.instance().show_warning("错误", f"保存失败: {e}")
