---
name: 创建窗口
description: 基于 BasePopupDialog 生成可拖动、主题自适配（含动态颜色变化）的弹窗模板。用户要新增弹窗/对话框且需统一滚动条/下拉框/按钮样式时调用。
---

# Popup Dialog Builder（BasePopupDialog 模板）

用于在本项目中创建新的弹窗/对话框窗口：以 [base_popup_dialog.py](file:///d:/code/BirdPictureManager/ui/widgets/base_popup_dialog.py) 为基础模板，确保：

- 主题色与颜色动态改变时自动刷新（ColorManager 配色文件变化）
- 按钮/下拉框/滚动条都匹配当前软件主题样式
- 窗口可拖动（默认使用 BasePopupDialog 的标题栏拖动）

## 触发条件（何时调用）

当你需要新增任意弹窗窗口（QDialog）并要求：

- 无边框圆角浮层风格（与软件其他弹窗一致）
- 跟随主题色动态变化（无需重启）
- 内容里包含滚动区域、下拉框、按钮等控件并必须统一主题样式

## 约束与约定

- 必须继承 `BasePopupDialog`，不要从 `QDialog` 直接起炉灶
- 不要重写拖动逻辑；保持 BasePopupDialog 的 `title_bar/title_label` 作为可拖动区域
- 下拉框优先使用 `ThemedComboBox`（自带主题监听）
- 底栏按钮优先使用 `apply_dialog_button_style(button, role)`

## 实现步骤（推荐）

### 1) 新建对话框文件

建议位置：

- `ui/dialogs/<xxx>_dialog.py`（业务对话框）
- `ui/widgets/<xxx>_dialog.py`（更通用/可复用的组件对话框）

### 2) 基础类与主题动态刷新

`BasePopupDialog` 会在构造时从 `ColorManager` 拉取颜色并设置 QSS，但本身不会自动监听主题变化。因此子类需要：

- 注册主题变更监听：`ColorManager.instance().register_listener(self.apply_theme_styles)`
- 在 `apply_theme_styles()` 内重新读取颜色 token 并刷新：
  - container/title_bar/title_label/close_btn/content_widget/bottom_bar
  - 以及你额外创建的滚动条/下拉列表样式

### 3) 统一控件样式（滚动条/下拉框/按钮）

- **按钮**
  - Primary：`apply_dialog_button_style(ok_btn, "primary")`
  - Secondary：`apply_dialog_button_style(cancel_btn, "secondary")`
- **下拉框**
  - 使用 `ThemedComboBox`（已内置主题监听与下拉列表滚动条样式）
- **滚动条**
  - 对 `QScrollArea` / `QAbstractScrollArea` 设置动态 QSS（从 ColorManager 取色生成）
  - 若对话框没有滚动区域可跳过

## 代码模板（可直接复制）

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea
from PyQt6.QtCore import Qt

from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.utils.color_manager import ColorManager
from ui.widgets.themed_combo_box import ThemedComboBox


class ExamplePopupDialog(BasePopupDialog):
    def __init__(self, parent=None):
        super().__init__(parent, title="示例弹窗", size=(720, 520))
        self._build_ui()
        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()

    def _build_ui(self):
        header = QLabel("这里是内容区标题")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.content_layout.addWidget(header)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        row_layout.addWidget(QLabel("模式:"))
        self.mode_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        self.mode_combo.addItem("A", "a")
        self.mode_combo.addItem("B", "b")
        row_layout.addWidget(self.mode_combo, 1)
        self.content_layout.addWidget(row)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        scroll_body = QWidget()
        scroll_layout = QVBoxLayout(scroll_body)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)

        for i in range(30):
            scroll_layout.addWidget(QLabel(f"条目 {i + 1}"))

        self.scroll_area.setWidget(scroll_body)
        self.content_layout.addWidget(self.scroll_area, 1)

        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确定")
        self.apply_dialog_button_style(cancel_btn, "secondary")
        self.apply_dialog_button_style(ok_btn, "primary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(ok_btn)

    def _scrollbar_qss(self) -> str:
        cm = ColorManager.instance()
        bg = cm.get("theme.background.light", "#FFFFFF")
        track = cm.get("theme.background.dark", "#E7E7E7")
        handle = cm.get("theme.primary", "#2196F3")
        handle_hover = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        return f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 2px;
            }}
            QScrollBar::groove:vertical {{
                background: {track};
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {handle};
                border-radius: 5px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {handle_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 2px;
            }}
            QScrollBar::groove:horizontal {{
                background: {track};
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle};
                border-radius: 5px;
                min-width: 24px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {handle_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """

    def apply_theme_styles(self):
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

        if self.content_widget:
            self.content_widget.setStyleSheet(f"""
                QWidget#contentWidget {{
                    background-color: {self._content_bg};
                }}
                QWidget#contentWidget QLabel {{
                    color: {self._text_color};
                    background: transparent;
                }}
            """)

        if self.title_bar:
            self.set_title_bar_style(self._header_bg, self._header_text, hover_background=self._close_hover_bg)
        if self.bottom_bar:
            self.set_bottom_bar_style(self._footer_bg, border_color=self._border_color)

        try:
            if hasattr(self, "scroll_area") and self.scroll_area:
                self.scroll_area.setStyleSheet(self._scrollbar_qss())
        except Exception:
            pass
```

## 常见检查清单

- 必须使用 `BasePopupDialog`（无边框/圆角/拖动机制一致）
- `ColorManager.register_listener(self.apply_theme_styles)` 已注册
- `apply_theme_styles()` 内刷新了：
  - 标题栏（背景/文字/关闭按钮 hover）
  - 容器边框与背景
  - 内容区文字色（至少 QLabel）
  - 底栏背景与分割线
  - 滚动条（如存在）
- 下拉框使用 `ThemedComboBox`
- 所有按钮通过 `apply_dialog_button_style` 设置（primary/secondary）