from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ChartType:
    chart_type: str
    title: str


CHART_TYPES: List[ChartType] = [
    ChartType("number", "数据图"),  # 显示单个数字的图表类型
    ChartType("bar", "柱状图"),
    ChartType("line", "折线图"),
    ChartType("pie", "饼图"),
    ChartType("scatter", "散点图"),
    ChartType("tree", "树图"),
    ChartType("treemap", "矩形树图"),
    ChartType("sunburst", "旭日图"),
    ChartType("map", "地图"),
    ChartType("lines", "线图"),
    ChartType("graph", "关系图"),
    ChartType("gauge", "仪表盘"),
    ChartType("geo", "地理坐标系"),
    ChartType("calendar", "日历"),
    ChartType("calendarH", "横向日历"),
    ChartType("customGauge", "自定义仪表"),
    ChartType("radar", "基础雷达图"),
    ChartType("radarCustom", "自定义雷达图"),
    ChartType("radarMulti", "多雷达图"),
    ChartType("geoGraph", "地理关系图"),
    ChartType("scrollLegend", "可滚动图例"),
    ChartType("globe3D", "中国观鸟热力图"),
    ChartType("timelineLine", "时间轴折线图"),
    ChartType("timelineGallery", "时间轴图片表格"),
    ChartType("bar3D", "3D柱状图"),
]


CHART_TYPE_TITLE_MAP: Dict[str, str] = {t.chart_type: t.title for t in CHART_TYPES}

