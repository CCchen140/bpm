from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全地将值转换为浮点数"""
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


@register_chart("line")
@register_chart("bar_line")  # 同时注册为柱状图/折线图类型
class LineDataBuilder(ChartDataBuilder):
    """
    折线图/柱状图数据构建器

    用于构建折线图和柱状图所需的数据结构，支持分组和聚合
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "line") -> dict:
        """
        构建折线图/柱状图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
                - x_field: X轴字段
                - y_agg: Y轴聚合方式 (count/mean/sum)
                - group_field: 分组字段（可选）
                - smooth: 是否平滑曲线
                - bar_ignore_empty_dates: 是否忽略无数据的日期
            chart_type: 图表类型标识 (line/bar_line)

        返回:
            包含折线图/柱状图数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        x_field = str(options.get("x_field") or "")
        y_agg = str(options.get("y_agg") or "count")
        group_field = str(options.get("group_field") or "")
        smooth = bool(options.get("smooth", False))

        # 获取分组表达式和筛选条件
        x_expr, where, params = self._group_expr_for_field(x_field)
        group_expr, group_where, group_params = self._group_expr_for_field(group_field) if group_field else (None, "", [])

        # 合并筛选条件
        wheres = [w for w in [where, group_where] if w]
        params = list(params or []) + list(group_params or [])
        where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

        # 构建Y轴聚合SQL
        y_sql = "COUNT(*)"
        if y_agg == "mean":
            y_sql = "AVG(score)"
        elif y_agg == "sum":
            y_sql = "SUM(score)"

        # 根据是否分组构建不同的SQL
        if group_expr:
            sql = f"""
                SELECT {x_expr} AS x, {group_expr} AS g, {y_sql} AS y
                FROM {table_name}
                {where_sql}
                GROUP BY x, g
                ORDER BY x ASC
                LIMIT 2000
            """
        else:
            sql = f"""
                SELECT {x_expr} AS x, {y_sql} AS y
                FROM {table_name}
                {where_sql}
                GROUP BY x
                ORDER BY x ASC
                LIMIT 2000
            """

        rows = self._db.query(sql, params).rows or []
        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

        # 处理隐藏无数据时间的选项
        ignore_empty = bool(options.get("bar_ignore_empty_dates", self._display_options.get("ignore_empty_dates", False)))
        if ignore_empty:
            # 过滤掉数值为0的数据点
            filtered_rows = [r for r in rows if _safe_float(r.get("y"), 0.0) > 0]
            if not filtered_rows:
                return {"kind": "empty", "message": "暂无数据"}
            rows = filtered_rows

        # 处理分组数据
        if group_expr:
            groups: Dict[str, Dict[str, float]] = {}
            xs: List[str] = []
            for r in rows:
                x = str(r.get("x") or "")
                g = str(r.get("g") or "")
                y = _safe_float(r.get("y"), 0.0)
                if x and x not in xs:
                    xs.append(x)
                groups.setdefault(g or "未分组", {})[x] = y

            # 构建系列数据
            series = []
            for g, xmap in groups.items():
                series.append({"name": g, "data": [xmap.get(x, 0.0) for x in xs]})

            return {
                "kind": "xy",
                "chart_type": chart_type,
                "x": xs,
                "series": series,
                "meta": {"y_agg": y_agg, "smooth": smooth},
            }

        # 无分组时的简单数据
        xs = [str(r.get("x") or "") for r in rows]
        ys = [_safe_float(r.get("y"), 0.0) for r in rows]
        return {
            "kind": "xy",
            "chart_type": chart_type,
            "x": xs,
            "series": [{"name": "数值", "data": ys}],
            "meta": {"y_agg": y_agg, "smooth": smooth},
        }

    def _group_expr_for_field(self, field_id: str):
        """
        根据字段ID获取分组表达式

        参数:
            field_id: 字段标识符

        返回:
            (表达式, WHERE条件, 参数列表) 元组
        """
        f = str(field_id or "").strip()
        if not f:
            return None, "", []
        if f in ("shot_time", "created_at"):
            return "substr(COALESCE(shot_time, created_at), 1, 7)", "COALESCE(shot_time, created_at) IS NOT NULL AND COALESCE(shot_time, created_at) != ''", []
        if f == "species":
            return "species_cls", "species_cls IS NOT NULL AND species_cls != ''", []
        if f == "order":
            return "order_cls", "order_cls IS NOT NULL AND order_cls != ''", []
        if f == "family":
            return "family_cls", "family_cls IS NOT NULL AND family_cls != ''", []
        if f == "genus":
            return "genus_cls", "genus_cls IS NOT NULL AND genus_cls != ''", []
        if f == "rating":
            return "rating", "rating IS NOT NULL AND rating >= 1 AND rating <= 5", []
        if f in ("score", "iso", "fnumber"):
            return f, f"{f} IS NOT NULL", []
        if f == "shutter":
            # 快门值分组
            return "shutter", "shutter IS NOT NULL AND shutter != ''", []
        if f == "focal_length":
            # 焦距分组
            return "focal_length", "focal_length IS NOT NULL AND focal_length != ''", []
        if f in ("camera_model", "lens_model", "location"):
            return f, f"{f} IS NOT NULL AND {f} != ''", []
        return f, f"{f} IS NOT NULL", []
