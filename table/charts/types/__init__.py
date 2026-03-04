from __future__ import annotations

# 导出基础类和注册表
from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import ChartRegistry, register_chart

# 自动导入并注册所有图表类型的 data_builder
# 这会触发各个模块中的 @register_chart 装饰器

# 柱状图
from table.charts.types.bar.data_builder import BarDataBuilder

# 饼图
from table.charts.types.pie.data_builder import PieDataBuilder

# 散点图
from table.charts.types.scatter.data_builder import ScatterDataBuilder

# 折线图/柱状图
from table.charts.types.line.data_builder import LineDataBuilder

# 数据图（数字统计）
from table.charts.types.number.data_builder import NumberDataBuilder

# 树形图
from table.charts.types.tree.data_builder import TreeDataBuilder

# 关系图
from table.charts.types.graph.data_builder import GraphDataBuilder

# 地理坐标图
from table.charts.types.geo.data_builder import GeoDataBuilder

# 仪表盘图
from table.charts.types.gauge.data_builder import GaugeDataBuilder

# 雷达图
from table.charts.types.radar.data_builder import RadarDataBuilder

# 日历图
from table.charts.types.calendar.data_builder import CalendarDataBuilder

# 图库预览
from table.charts.types.gallery.data_builder import GalleryDataBuilder

__all__ = [
    'ChartDataBuilder',
    'ChartRegistry',
    'register_chart',
    # 图表数据构建器类
    'BarDataBuilder',
    'PieDataBuilder',
    'ScatterDataBuilder',
    'LineDataBuilder',
    'NumberDataBuilder',
    'TreeDataBuilder',
    'GraphDataBuilder',
    'GeoDataBuilder',
    'GaugeDataBuilder',
    'RadarDataBuilder',
    'CalendarDataBuilder',
    'GalleryDataBuilder',
]
