from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from table.charts.chart_controller import ChartController
from table.charts.simple_placeholder_controller import SimplePlaceholderChartController
from table.chart_types import CHART_TYPE_TITLE_MAP


def create_controller(parent: QWidget, config: dict) -> ChartController:
    title = CHART_TYPE_TITLE_MAP.get("bar", "柱状图")
    return SimplePlaceholderChartController(parent, title, config)
