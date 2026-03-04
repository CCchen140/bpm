from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


@register_chart("gallery")
class GalleryDataBuilder(ChartDataBuilder):
    """
    图库预览数据构建器

    用于构建图库预览数据，展示最近添加的图片
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "gallery") -> dict:
        """
        构建图库预览数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
            chart_type: 图表类型标识

        返回:
            包含图库预览数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        sql = f"""
            SELECT file_path AS p, created_at AS t
            FROM {table_name}
            ORDER BY created_at DESC
            LIMIT 60
        """
        rows = self._db.query(sql, []).rows or []

        # 构建图库项目列表
        items = [{"path": str(r.get("p") or ""), "time": str(r.get("t") or "")} for r in rows if str(r.get("p") or "")]
        return {"kind": "gallery", "items": items}
