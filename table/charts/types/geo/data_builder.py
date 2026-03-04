from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全地将值转换为浮点数"""
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    """安全地将值转换为整数"""
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


@register_chart("geo")
@register_chart("geo_points")
class GeoDataBuilder(ChartDataBuilder):
    """
    地理坐标图数据构建器

    用于构建地理坐标点数据，展示图片拍摄位置的分布
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "geo") -> dict:
        """
        构建地理坐标图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
            chart_type: 图表类型标识

        返回:
            包含地理坐标点数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        sql = f"""
            SELECT latitude AS lat, longitude AS lng, COUNT(*) AS cnt
            FROM {table_name}
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND latitude != 0 AND longitude != 0
            GROUP BY ROUND(latitude, 3), ROUND(longitude, 3)
            ORDER BY cnt DESC
            LIMIT 2000
        """
        rows = self._db.query(sql, []).rows or []

        # 构建坐标点数据 [经度, 纬度, 数量]
        pts = [[_safe_float(r.get("lng"), 0.0), _safe_float(r.get("lat"), 0.0), _safe_int(r.get("cnt"), 0)] for r in rows]
        return {"kind": "geo_points", "points": pts}
