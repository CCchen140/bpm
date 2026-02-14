from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from table.chart_types import CHART_TYPE_TITLE_MAP
from table.charts.chart_controller import ChartController
from table.charts.simple_placeholder_controller import SimplePlaceholderChartController


def create_controller(parent: QWidget, config: dict) -> ChartController:
    title = CHART_TYPE_TITLE_MAP.get("customGauge", "自定义仪表")
    return SimplePlaceholderChartController(parent, title, config)

