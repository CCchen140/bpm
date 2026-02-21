from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QWidget, QFormLayout, QComboBox
)
from PyQt6.QtCore import Qt, QUrl
import os
import json

from ui.common.styles import SCROLL_AREA_STYLE
from ui.utils.icon_loader import qta
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from utils.paths import PathManager


class ExifWriteDialog(BasePopupDialog):
    def __init__(self, parent=None, image_path=None, file_paths=None):
        super().__init__(parent=parent, title="写入Exif信息", size=(760, 560))
        self.image_path = image_path
        self.file_paths = file_paths
        if not self.file_paths and self.image_path:
            self.file_paths = [self.image_path]

        self.entries = []
        pm = PathManager.instance()
        self.presets_dir = str(pm.get_user_data_path() / "exif_presets")
        self._migrate_legacy_presets(str(pm.get_app_data_path() / "exif_presets"))
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
        self.setWindowTitle("写入Exif信息")
        self.setModal(True)

        cm = ColorManager.instance()
        self._popup_bg = self.get_content_background()
        self._control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        self._text_color = cm.get("popup.text.primary", "#333333")
        self._border_color = cm.get("popup.border.primary", "#D0D0D0")
        self._header_bg = cm.get("popup.header.background", "#2c3e50")
        self._header_text_color = cm.get("popup.header.text", "#FFFFFF")
        self._primary_color = cm.get("theme.primary", "#2196F3")
        self._hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        self._disabled_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        self.set_title_bar_style(self._header_bg, self._header_text_color, self._hover_bg)
        self.set_bottom_bar_style(self.get_footer_background(), self._border_color)

        count = len(self.file_paths) if self.file_paths else 0
        if count > 1:
            header_text = f"为选中的 {count} 张图片添加或修改 Exif 标签"
        else:
            header_text = "为当前图片添加或修改 Exif 标签"
        header = QLabel(header_text)
        header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        header.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {self._text_color};")
        self.content_layout.addWidget(header)

        self.preset_combo = QComboBox()
        self.preset_combo.setEditable(False)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        arrow_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "icon", "line", "箭头下_arrow-down.svg"))
        arrow_url = QUrl.fromLocalFile(arrow_path).toString()
        self.preset_combo.setStyleSheet(f"""
            QComboBox {{
                padding: 6px 10px;
                border: 1px solid {self._border_color};
                background-color: {self._control_bg};
                font-size: 13px;
                min-width: 160px;
                color: {self._text_color};
            }}
            QComboBox:hover {{
                border: 1px solid {self._primary_color};
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
                border: 1px solid {self._border_color};
                background-color: {self._control_bg};
                selection-background-color: {self._primary_color};
                selection-color: {self._header_text_color};
                color: {self._text_color};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {self._hover_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {self._primary_color};
                color: {self._header_text_color};
            }}
        """)

        preset_layout = QHBoxLayout()
        preset_label = QLabel("预设方案:")
        preset_label.setStyleSheet(f"color: {self._text_color};")
        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.preset_combo, 1)
        self.content_layout.addLayout(preset_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(SCROLL_AREA_STYLE)
        scroll.setMinimumHeight(300)
        self.form_container = QWidget()
        self.form_layout = QFormLayout(self.form_container)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setSpacing(10)
        scroll.setWidget(self.form_container)
        self.content_layout.addWidget(scroll, 1)

        action_row = QHBoxLayout()

        add_btn = QPushButton("添加条目")
        add_btn.setFixedHeight(36)
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._control_bg};
                color: {self._text_color};
                border: 1px solid {self._border_color};
                border-radius: 4px;
                padding: 0px 12px;
            }}
            QPushButton:hover {{
                background-color: {self._hover_bg};
            }}
        """)
        add_btn.clicked.connect(lambda: self.add_entry())
        action_row.addWidget(add_btn)

        action_row.addStretch()

        self.delete_preset_btn = QPushButton("删除预设")
        self.delete_preset_btn.setFixedHeight(36)
        self.delete_preset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._control_bg};
                color: {self._text_color};
                border: 1px solid {self._border_color};
                border-radius: 4px;
                padding: 0px 12px;
            }}
            QPushButton:hover {{
                background-color: {self._hover_bg};
            }}
        """)
        self.delete_preset_btn.clicked.connect(self.delete_preset)
        action_row.addWidget(self.delete_preset_btn)

        self.save_preset_btn = QPushButton("保存为预设")
        self.save_preset_btn.setFixedHeight(36)
        self.save_preset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._primary_color};
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 0px 14px;
            }}
            QPushButton:hover {{
                background-color: {self._primary_color};
            }}
            QPushButton:pressed {{
                background-color: {self._primary_color};
            }}
            QPushButton:disabled {{
                background-color: {self._disabled_bg};
            }}
        """)
        self.save_preset_btn.clicked.connect(self.save_preset)
        action_row.addWidget(self.save_preset_btn)

        self.content_layout.addLayout(action_row)

        self.add_entry()

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

    def add_entry(self, tag_text="", value_text=""):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        tag_edit = QLineEdit()
        tag_edit.setPlaceholderText("写入XMP-bmp空间")
        tag_edit.setText(tag_text)
        tag_edit.setMinimumHeight(36)
        tag_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {self._border_color};
                border-radius: 4px;
                font-size: 14px;
                background-color: {self._control_bg};
                color: {self._text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {self._primary_color};
            }}
        """)

        value_edit = QLineEdit()
        value_edit.setPlaceholderText("标签值")
        value_edit.setText(value_text)
        value_edit.setMinimumHeight(36)
        value_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {self._border_color};
                border-radius: 4px;
                font-size: 14px;
                background-color: {self._control_bg};
                color: {self._text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {self._primary_color};
            }}
        """)

        remove_btn = QPushButton("删除")
        remove_btn.setFixedSize(70, 36)
        remove_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._control_bg};
                color: {self._text_color};
                border: 1px solid {self._border_color};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {self._hover_bg};
            }}
        """)

        def on_remove():
            idx = None
            for i, (w, t, v) in enumerate(self.entries):
                if w is row_widget:
                    idx = i
                    break
            if idx is not None:
                item = self.form_layout.takeAt(idx)
                if item:
                    w = item.widget()
                    if w:
                        w.setParent(None)
                self.entries.pop(idx)

        remove_btn.clicked.connect(on_remove)

        row_layout.addWidget(tag_edit, 2)
        row_layout.addWidget(value_edit, 3)
        row_layout.addWidget(remove_btn)

        self.form_layout.addRow(row_widget)
        self.entries.append((row_widget, tag_edit, value_edit))

    def get_tag_dict(self):
        result = {}
        for _, tag_edit, value_edit in self.entries:
            raw_tag = tag_edit.text().strip()
            value = value_edit.text().strip()
            if not raw_tag or not value:
                continue
            if ":" in raw_tag:
                prefix, rest = raw_tag.split(":", 1)
                prefix_low = prefix.strip().lower()
                if prefix_low == "xmp":
                    tag = f"XMP:{rest.strip()}"
                elif prefix_low == "xmp-bmp":
                    tag = f"XMP-bmp:{rest.strip()}"
                else:
                    tag = raw_tag
            else:
                tag = f"XMP-bmp:{raw_tag}"
            result[tag] = value
        return result

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
            for i in range(len(self.entries) - 1, -1, -1):
                item = self.form_layout.takeAt(i)
                if item and item.widget():
                    item.widget().setParent(None)
            self.entries.clear()
            if isinstance(data, dict):
                for tag, value in data.items():
                    self.add_entry(tag, str(value))
        except Exception as e:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().warning(f"加载 Exif 预设失败: {e}")
            except Exception:
                pass

    def save_preset(self):
        tags = self.get_tag_dict()
        if not tags:
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
                json.dump(tags, f, ensure_ascii=False, indent=2)
            from ui.utils.notification_manager import NotificationManager
            NotificationManager.instance().show_toast("Exif预设已保存")
            self.load_presets()
        except Exception as e:
            from ui.utils.notification_manager import NotificationManager
            NotificationManager.instance().show_warning("错误", f"保存失败: {e}")
