from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


def _safe_float(v: Any, default: Any = 0.0) -> Any:
    """安全地将值转换为浮点数，如果转换失败则返回默认值"""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@register_chart("scatter")
class ScatterDataBuilder(ChartDataBuilder):
    """
    散点图数据构建器

    用于构建散点图所需的数据结构，支持X/Y轴和气泡大小，
    支持筛选条件和时间分组
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "scatter") -> dict:
        """
        构建散点图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
                - x_field: X轴字段
                - y_field: Y轴字段
                - size_field: 气泡大小字段（可选）
                - scatter_filters: 筛选条件列表
                - scatter_time_group: 时间分组（day/week/month/year）
            chart_type: 图表类型标识

        返回:
            包含散点图数据的字典
        """
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        x_field = str(options.get("x_field") or "score")
        y_field = str(options.get("y_field") or "count")
        auto_size = bool(options.get("scatter_auto_size"))
        filters = options.get("scatter_filters") or []
        time_group = str(options.get("scatter_time_group") or "day")

        if self._is_stat_field(y_field):
            return self._build_stat_scatter(table_name, x_field, y_field, filters, time_group, auto_size)
        else:
            return self._build_simple_scatter(table_name, x_field, y_field, filters, auto_size)

    def _is_stat_field(self, field_id: str) -> bool:
        """判断是否为统计字段"""
        return field_id in ("count", "species_count", "new_count")

    def _build_simple_scatter(self, table_name: str, x_field: str, y_field: str, filters: list, auto_size: bool) -> dict:
        """构建简单散点图（单张图片属性）"""
        xf, xw, xp = self._value_expr_for_field(x_field)
        yf, yw, yp = self._value_expr_for_field(y_field)

        x_filter_field = self._field_to_filter_field(x_field)
        y_filter_field = self._field_to_filter_field(y_field)
        exclude_fields = set()
        if x_filter_field:
            exclude_fields.add(x_filter_field)
        if y_filter_field:
            exclude_fields.add(y_filter_field)

        filter_where, filter_params = self._db.build_where_from_conditions(filters, exclude_fields=exclude_fields)

        wheres = [w for w in [xw, yw] if w]
        params = list(xp or []) + list(yp or []) + list(filter_params or [])

        if filter_where:
            wheres.append(filter_where)

        where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

        sql = f"""
            SELECT {xf} AS x, {yf} AS y
            FROM {table_name}
            {where_sql}
            LIMIT 2000
        """
        result = self._db.query(sql, params)
        rows = result.rows or []
        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

        pts = []
        for r in rows:
            x_raw = r.get("x")
            y = _safe_float(r.get("y"), None)
            if x_raw is None or y is None:
                continue
            x = x_raw if isinstance(x_raw, str) else _safe_float(x_raw, None)
            if x is None:
                continue
            pts.append([x, y])

        return {"kind": "scatter", "points": pts, "auto_size": auto_size}

    def _build_stat_scatter(self, table_name: str, x_field: str, y_field: str, filters: list, time_group: str, auto_size: bool) -> dict:
        """构建统计散点图（按X轴分组统计）"""
        xf, xw, xp = self._value_expr_for_field(x_field)

        if x_field in ("shot_time", "created_at"):
            xf = self._get_time_group_expr(x_field, time_group)
            xw = f"{x_field} IS NOT NULL AND {x_field} != ''"

        x_filter_field = self._field_to_filter_field(x_field)
        exclude_fields = set()
        if x_filter_field:
            exclude_fields.add(x_filter_field)

        filter_where, filter_params = self._db.build_where_from_conditions(filters, exclude_fields=exclude_fields)

        wheres = [w for w in [xw] if w]
        params = list(xp or []) + list(filter_params or [])

        if filter_where:
            wheres.append(filter_where)

        where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

        if y_field == "count":
            y_expr = "COUNT(*)"
        elif y_field == "species_count":
            y_expr = "COUNT(DISTINCT species)"
        elif y_field == "new_count":
            y_expr = "COUNT(*)"
        else:
            y_expr = "COUNT(*)"

        sql = f"""
            SELECT {xf} AS x, {y_expr} AS y
            FROM {table_name}
            {where_sql}
            GROUP BY {xf}
            HAVING {xf} IS NOT NULL
            LIMIT 2000
        """
        result = self._db.query(sql, params)
        rows = result.rows or []
        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

        pts = []
        for r in rows:
            x_raw = r.get("x")
            y = _safe_float(r.get("y"), None)
            if x_raw is None or y is None:
                continue
            x = x_raw if isinstance(x_raw, str) else _safe_float(x_raw, None)
            if x is None:
                continue
            pts.append([x, y])

        return {"kind": "scatter", "points": pts, "auto_size": auto_size}

    def _get_time_group_expr(self, field: str, group: str) -> str:
        """获取时间分组表达式"""
        # shot_time格式可能是 "2026:02:09 16:38:04" 或 "2026:01:26 22:50:43+08:00"
        # 先替换冒号为短横线，然后提取日期部分
        if group == "day":
            return f"substr(replace({field}, ':', '-'), 1, 10)"
        elif group == "week":
            # 按周分组：返回年份-周数
            return f"strftime('%Y-W%W', substr(replace({field}, ':', '-'), 1, 10))"
        elif group == "month":
            # 按月分组：返回年份-月份
            return f"substr(replace({field}, ':', '-'), 1, 7)"
        elif group == "year":
            # 按年分组：返回年份
            return f"substr(replace({field}, ':', '-'), 1, 4)"
        else:
            return f"substr(replace({field}, ':', '-'), 1, 10)"

    def _field_to_filter_field(self, field_id: str) -> str:
        mapping = {
            "score": "分数",
            "rating": "评星",
            "shot_time": "拍摄时间",
            "created_at": "创建时间"
        }
        return mapping.get(field_id, "")

    def _value_expr_for_field(self, field_id: str) -> Tuple[str, str, list]:
        f = str(field_id or "").strip()
        if not f:
            return "NULL", "", []
        if f == "count":
            return "COUNT(*)", "", []
        if f == "species_count":
            return "COUNT(DISTINCT species)", "", []
        if f == "new_count":
            return "COUNT(*)", "", []
        if f == "score":
            return "score", "score IS NOT NULL", []
        if f == "rating":
            return "rating", "rating IS NOT NULL AND rating >= 1 AND rating <= 5", []
        if f == "iso":
            return "iso", "iso IS NOT NULL", []
        if f == "fnumber":
            return "fnumber", "fnumber IS NOT NULL", []
        if f == "shutter":
            return "CASE WHEN shutter LIKE '%/%' THEN CAST(substr(shutter, 1, instr(shutter,'/')-1) AS REAL) / CAST(substr(shutter, instr(shutter,'/')+1) AS REAL) ELSE CAST(shutter AS REAL) END", "shutter IS NOT NULL AND shutter != ''", []
        if f == "focal_length":
            return "CAST(replace(focal_length,'mm','') AS REAL)", "focal_length IS NOT NULL AND focal_length != ''", []
        if f == "shot_time":
            return "strftime('%s', shot_time)", "shot_time IS NOT NULL AND shot_time != ''", []
        if f == "created_at":
            return "strftime('%s', created_at)", "created_at IS NOT NULL AND created_at != ''", []
        return "NULL", "", []
