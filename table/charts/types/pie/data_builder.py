from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全地将值转换为浮点数"""
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


@register_chart("pie")
class PieDataBuilder(ChartDataBuilder):
    """
    饼图数据构建器

    用于构建饼图所需的数据结构，支持按不同字段分组统计，
    支持时间范围筛选和数据筛选条件
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "pie") -> dict:
        """
        构建饼图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
                - category_field: 分类字段 (order/family/genus/species/rating/label/location)
                - value_agg: 聚合方式 (count/species_count)
                - pie_time_type: 时间类型 (all/shot_time/imported_at/created_at)
                - pie_time_start: 起始时间
                - pie_time_end: 结束时间
                - pie_time_end_now: 是否使用当前时间作为结束时间
                - pie_time_preset: 预设时间范围
                - pie_time_step: 时间步长
                - pie_time_unit: 时间单位 (day/month/year)
                - pie_filters: 筛选条件列表
            chart_type: 图表类型标识

        返回:
            包含饼图数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        cat = str(options.get("category_field") or "species")
        value_agg = str(options.get("value_agg") or "count")
        time_type = str(options.get("pie_time_type") or "all")

        # 获取分类字段对应的筛选项名称，用于排除
        category_filter_field = self._category_to_filter_field(cat)
        exclude_fields = {category_filter_field} if category_filter_field else set()

        # 构建筛选条件
        filters = options.get("pie_filters") or []
        where_expr, params = self._db.build_where_from_conditions(filters, exclude_fields=exclude_fields)

        # 构建额外的WHERE条件
        extra = []
        extra_params: list = []

        # 获取分组表达式和基础WHERE条件
        x_expr, cat_where, cat_params = self._group_expr_for_field(cat)
        if cat_where:
            extra.append(cat_where)

        # 处理时间范围
        if time_type != "all":
            time_col = self._get_time_column(time_type)
            time_start, time_end, time_end_now = self._parse_time_range(options)

            if time_start:
                extra.append(f"{time_col} >= ?")
                extra_params.append(time_start + (" 00:00:00" if len(time_start) == 10 else ""))
            if time_end_now:
                try:
                    time_end = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    time_end = ""
            if time_end:
                extra.append(f"{time_col} <= ?")
                extra_params.append(time_end + (" 23:59:59" if len(time_end) == 10 else ""))

        # 合并所有WHERE条件
        all_where = []
        if where_expr:
            all_where.append(f"({where_expr})")
        if extra:
            all_where.append("(" + " AND ".join(extra) + ")")
        final_where = " AND ".join(all_where)
        final_params = list(params or []) + list(cat_params or []) + list(extra_params or [])

        # 根据聚合方式构建SQL
        if value_agg == "species_count":
            # 鸟种数：统计每个分类下不同的物种数量
            y_sql = "COUNT(DISTINCT species_cls)"
            # 需要确保species_cls不为空
            if "species_cls IS NOT NULL AND species_cls != ''" not in final_where:
                if final_where:
                    final_where = f"({final_where}) AND (species_cls IS NOT NULL AND species_cls != '')"
                else:
                    final_where = "species_cls IS NOT NULL AND species_cls != ''"
        else:
            # 默认：图片数量
            y_sql = "COUNT(*)"

        where_sql = f" WHERE {final_where}" if final_where else ""

        sql = f"""
            SELECT {x_expr} AS x, {y_sql} AS y
            FROM {table_name}
            {where_sql}
            GROUP BY x
            ORDER BY y DESC
            LIMIT 50
        """
        rows = self._db.query(sql, final_params).rows or []
        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

        # 构建饼图数据项
        items = [{"name": str(r.get("x") or ""), "value": _safe_float(r.get("y"), 0.0)} for r in rows if str(r.get("x") or "")]
        return {
            "kind": "pie",
            "items": items,
            "meta": {
                "value_agg": value_agg,
                "category_field": cat,
                "time_type": time_type
            }
        }

    def _category_to_filter_field(self, cat: str) -> str:
        """
        将分类字段ID转换为筛选字段名称

        参数:
            cat: 分类字段ID

        返回:
            筛选字段名称
        """
        mapping = {
            "order": "目",
            "family": "科",
            "genus": "属",
            "species": "种",
            "rating": "评星",
            "label": "色标",
            "location": "拍摄地址"
        }
        return mapping.get(cat, "")

    def _get_time_column(self, time_type: str) -> str:
        """
        根据时间类型获取对应的时间列表达式

        参数:
            time_type: 时间类型

        返回:
            时间列SQL表达式
        """
        if time_type == "imported_at":
            return "COALESCE(NULLIF(imported_at,''), created_at)"
        elif time_type == "created_at":
            return "created_at"
        else:  # shot_time
            return "COALESCE(NULLIF(shot_time,''), created_at)"

    def _parse_time_range(self, options: dict) -> tuple:
        """
        解析时间范围配置

        参数:
            options: 配置选项字典

        返回:
            (起始时间, 结束时间, 是否至今) 元组
        """
        preset = str(options.get("pie_time_preset") or "").strip().lower()
        start = str(options.get("pie_time_start") or "").strip()
        end = str(options.get("pie_time_end") or "").strip()
        end_now = bool(
            options.get("pie_time_end_now", False) or
            str(options.get("pie_time_end") or "").strip().lower() in ("now", "__now__", "today") or
            preset == "now"
        )

        if preset in ("today", "week", "month", "year", "now"):
            try:
                now = datetime.datetime.now()
                end = now.strftime("%Y-%m-%d %H:%M:%S")
                end_now = True
                if preset == "today":
                    start = now.strftime("%Y-%m-%d")
                elif preset == "week":
                    start_dt = now - datetime.timedelta(days=6)
                    start = start_dt.strftime("%Y-%m-%d")
                elif preset == "month":
                    start = now.replace(day=1).strftime("%Y-%m-%d")
                else:
                    start_dt = now - datetime.timedelta(days=364)
                    start = start_dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        return start, end, end_now

    def _group_expr_for_field(self, field_id: str) -> tuple:
        """
        根据字段ID获取分组表达式

        参数:
            field_id: 字段标识符

        返回:
            (表达式, WHERE条件, 参数列表) 元组
        """
        f = str(field_id or "").strip()
        if not f:
            return "''", "", []
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
        if f == "label":
            return "label", "label IS NOT NULL AND label != ''", []
        if f == "location":
            return "location", "location IS NOT NULL AND location != ''", []
        if f in ("score", "iso", "fnumber"):
            return f, f"{f} IS NOT NULL", []
        if f in ("shutter", "focal_length", "camera_model", "lens_model"):
            return f, f"{f} IS NOT NULL AND {f} != ''", []
        return f, f"{f} IS NOT NULL", []
