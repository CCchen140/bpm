from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


@register_chart("gauge")
class GaugeDataBuilder(ChartDataBuilder):
    """
    仪表盘图数据构建器

    用于构建仪表盘数据，展示图片总数、物种数、收藏数等关键指标
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "gauge") -> dict:
        """
        构建仪表盘图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
            chart_type: 图表类型标识

        返回:
            包含仪表盘指标数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        # 查询图片总数
        total = self._db.scalar(f"SELECT COUNT(*) AS c FROM {table_name}", [])

        # 查询物种数
        species = self._db.scalar(
            f"SELECT COUNT(DISTINCT species_cls) AS c FROM {table_name} WHERE species_cls IS NOT NULL AND species_cls != ''",
            [],
        )

        # 查询收藏数
        fav = self._db.scalar(f"SELECT COUNT(*) AS c FROM {table_name} WHERE is_favorite = 1", [])

        return {
            "kind": "gauge",
            "metrics": [
                {"name": "图片总数", "value": int(total)},
                {"name": "物种数", "value": int(species)},
                {"name": "收藏数", "value": int(fav)},
            ],
        }
