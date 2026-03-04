from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


@register_chart("radar")
class RadarDataBuilder(ChartDataBuilder):
    """
    雷达图数据构建器

    用于构建雷达图数据，展示评分均值、ISO均值、光圈均值等多维度指标
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "radar") -> dict:
        """
        构建雷达图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
            chart_type: 图表类型标识

        返回:
            包含雷达图指标数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        # 定义要统计的指标
        metrics = [
            ("评分均值", "AVG(score)"),
            ("ISO均值", "AVG(iso)"),
            ("光圈均值", "AVG(fnumber)"),
            ("收藏比例", "AVG(is_favorite)"),
            ("评分均值(星)", "AVG(rating)"),
        ]

        indicators = []
        values = []

        for name, expr in metrics:
            v = self._db.scalar(f"SELECT {expr} AS c FROM {table_name}", [])
            val = float(v or 0.0)
            # 收藏比例需要转换为百分比
            if "比例" in name:
                val = val * 100.0
            indicators.append({"name": name, "max": max(1.0, val * 1.2)})
            values.append(val)

        return {"kind": "radar", "indicators": indicators, "value": values}
