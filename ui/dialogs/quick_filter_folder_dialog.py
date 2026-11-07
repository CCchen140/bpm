from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit
from PyQt6.QtCore import Qt

from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.widgets.themed_combo_box import ThemedComboBox
from ui.utils.color_manager import ColorManager


class QuickFilterFolderDialog(BasePopupDialog):
    """快捷筛选文件夹设置弹窗。"""

    def __init__(self, parent=None, preset_options=None, initial_name="", initial_preset_file=""):
        super().__init__(parent, title="快捷筛选文件夹设置", size=(600, 300))
        self._preset_options = list(preset_options or [])
        self._result_data = None
        self._initial_name = str(initial_name or "")
        self._initial_preset_file = str(initial_preset_file or "")
        self._build_ui()
        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()

    def _build_ui(self):
        """构建弹窗界面。"""
        self.content_layout.setSpacing(14)

        self.desc_label = QLabel("为快捷筛选文件夹设置显示名称，并绑定一个已保存的筛选方案。")
        self.desc_label.setWordWrap(True)
        self.content_layout.addWidget(self.desc_label)

        name_row = QWidget()
        name_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(12)
        self.name_label = QLabel("文件夹名称")
        self.name_label.setMinimumWidth(78)
        name_layout.addWidget(self.name_label)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("请输入快捷筛选文件夹名称")
        self.name_input.setText(self._initial_name)
        name_layout.addWidget(self.name_input, 1)
        self.content_layout.addWidget(name_row)

        preset_row = QWidget()
        preset_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(12)
        self.preset_label = QLabel("筛选方案")
        self.preset_label.setMinimumWidth(78)
        preset_layout.addWidget(self.preset_label)
        self.preset_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        self.preset_combo.setMinimumWidth(320)
        for option in self._preset_options:
            label = str(option.get("label") or "")
            file_name = str(option.get("file_name") or "")
            self.preset_combo.addItem(label, file_name)
        preset_layout.addWidget(self.preset_combo, 1)
        self.content_layout.addWidget(preset_row)
        self.content_layout.addStretch(1)

        try:
            if self._initial_preset_file:
                idx = self.preset_combo.findData(self._initial_preset_file)
                if idx >= 0:
                    self.preset_combo.setCurrentIndex(idx)
        except Exception:
            pass

        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确定")
        cancel_btn.setFixedSize(104, 40)
        ok_btn.setFixedSize(104, 40)
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self._accept_result)
        self.apply_dialog_button_style(cancel_btn, "secondary")
        self.apply_dialog_button_style(ok_btn, "primary")
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(ok_btn)

    def _line_edit_style(self) -> str:
        """返回输入框主题样式。"""
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary", "#D0D0D0")
        primary = cm.get("theme.primary", "#2196F3")
        bg = cm.get("theme.background.light", "#FFFFFF")
        text = cm.get("theme.text.dark", "#333333")
        return f"""
            QLineEdit {{
                border: 1px solid {border};
                border-radius: 4px;
                padding: 6px 10px;
                background-color: {bg};
                color: {text};
            }}
            QLineEdit:focus {{
                border: 1px solid {primary};
            }}
        """

    def apply_theme_styles(self):
        """在主题变更时刷新弹窗样式。"""
        cm = ColorManager.instance()

        self._content_bg = cm.get("theme.background.light", "#FFFFFF")
        self._footer_bg = cm.get("theme.background.dark", "#E7E7E7")
        self._border_color = cm.get("theme.background.light", "#D0D0D0")
        self._header_bg = cm.get("popup.header.background", "#2c3e50")
        self._header_text = cm.get("popup.header.text", "#FFFFFF")
        self._close_hover_bg = cm.get("popup.header.close_button.hover_background", "#FFFFFF1A")
        self._close_hover_icon = cm.get("border.subject_rect", "#F50F0F")
        self._primary_color = cm.get("theme.primary", "#2196F3")
        self._text_color = cm.get("popup.text.primary", "#333333")
        self._disabled_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        self._hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")

        if self.container:
            self.container.setStyleSheet(f"""
                QWidget#container {{
                    background-color: {self._content_bg};
                    border: 1px solid {self._border_color};
                    border-radius: 8px;
                }}
            """)

        if self.title_bar:
            self.set_title_bar_style(self._header_bg, self._header_text, hover_background=self._close_hover_bg)
        if self.bottom_bar:
            self.set_bottom_bar_style(self._footer_bg, border_color=self._border_color)
        if self.content_widget:
            self.content_widget.setStyleSheet(f"""
                QWidget#contentWidget {{
                    background-color: {self._content_bg};
                }}
                QWidget#contentWidget QWidget {{
                    background: transparent;
                    border: none;
                }}
                QWidget#contentWidget QLabel {{
                    color: {self._text_color};
                    background: transparent;
                }}
            """)
        try:
            if hasattr(self, "desc_label") and self.desc_label:
                self.desc_label.setStyleSheet(f"""
                    color: {self._text_color};
                    background: transparent;
                    border: none;
                    font-size: 13px;
                    padding-bottom: 4px;
                """)
        except Exception:
            pass
        try:
            for label in [getattr(self, "name_label", None), getattr(self, "preset_label", None)]:
                if label is not None:
                    label.setStyleSheet(f"""
                        color: {self._text_color};
                        background: transparent;
                        border: none;
                        font-size: 12px;
                        font-weight: 600;
                    """)
        except Exception:
            pass
        try:
            if hasattr(self, "name_input") and self.name_input:
                self.name_input.setStyleSheet(self._line_edit_style())
        except Exception:
            pass

    def _accept_result(self):
        """校验输入并生成结果。"""
        name = str(self.name_input.text() or "").strip()
        preset_file = self.preset_combo.currentData()
        if not name:
            self.name_input.setFocus()
            return
        if not preset_file:
            self.preset_combo.setFocus()
            return
        self._result_data = {
            "name": name,
            "preset_file": str(preset_file),
        }
        self.accept()

    def get_result(self):
        """返回用户在弹窗中确认后的配置结果。"""
        return self._result_data
