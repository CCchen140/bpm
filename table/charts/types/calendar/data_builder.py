from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


@register_chart("calendar")
class CalendarDataBuilder(ChartDataBuilder):
    """
    日历图数据构建器

    用于构建日历热力图数据，展示每日图片数量的分布
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "calendar") -> dict:
        """
        构建日历图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
            chart_type: 图表类型标识

        返回:
            包含日历图数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        sql = f"""
            SELECT substr(COALESCE(shot_time, created_at), 1, 10) AS d, COUNT(*) AS c
            FROM {table_name}
            WHERE COALESCE(shot_time, created_at) IS NOT NULL AND COALESCE(shot_time, created_at) != ''
            GROUP BY d
            ORDER BY d ASC
            LIMIT 5000
        """
        rows = self._db.query(sql, []).rows or []

        # 构建日历数据 [日期, 数量]
        data = [[str(r.get("d") or ""), int(r.get("c") or 0)] for r in rows if str(r.get("d") or "")]
        return {"kind": "calendar", "data": data}
