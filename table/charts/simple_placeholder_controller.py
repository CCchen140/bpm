from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from table.charts.chart_controller import ChartController
from ui.utils.color_manager import ColorManager


class SimplePlaceholderChartController(ChartController):
    def __init__(self, parent: QWidget, title: str, config: dict):
        self._config = dict(config or {})
        self._title_text = str(title or "").strip() or "图表"

        self._theme: Optional[str] = None
        self._display_options: Dict[str, Any] = {}
        self._data: Any = None

        self._root = QWidget(parent)
        layout = QVBoxLayout(self._root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._title = QLabel(f"{self._title_text}（占位）")
        self._title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._sub = QLabel("")
        self._sub.setWordWrap(True)

        layout.addWidget(self._title)
        layout.addWidget(self._sub)
        layout.addStretch(1)

        self._apply_theme()
        try:
            ColorManager.instance().register_listener(self._apply_theme)
        except Exception:
            pass
        self.refresh()

    @property
    def widget(self) -> QWidget:
        return self._root

    def set_data(self, data: Any) -> None:
        self._data = data

    def set_theme(self, theme: Optional[str]) -> None:
        self._theme = theme

    def set_display_options(self, options: Dict[str, Any]) -> None:
        self._display_options = dict(options or {})

    def refresh(self) -> None:
        theme_text = str(self._theme or "follow")
        opts = self._display_options or {}
        opt_text = "、".join([k for k, v in opts.items() if bool(v)]) or "无"
        self._sub.setText(f"主题：{theme_text}    显示效果：{opt_text}")

    def _apply_theme(self):
        cm = ColorManager.instance()
        text = cm.get("popup.text.primary", "#333333")
        sub_text = cm.get("popup.text.secondary", text)
        self._title.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {text};")
        self._sub.setStyleSheet(f"font-size: 12px; color: {sub_text};")

