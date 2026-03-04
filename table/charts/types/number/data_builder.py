from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


@register_chart("number")
class NumberDataBuilder(ChartDataBuilder):
    """
    数据图（数字统计）数据构建器

    用于显示单个数字统计，支持图片数量、鸟种数、加新数量等统计类型
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "number") -> dict:
        """
        构建数据图（数字统计）数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
                - number_type: 数据类型 (count/species_count/new_species)
                - number_time_type: 时间类型 (shot_time/imported_at/created_at)
                - number_time_start: 起始时间
                - number_time_end: 结束时间
                - number_time_end_now: 是否使用当前时间作为结束时间
                - number_filters: 额外的筛选条件
            chart_type: 图表类型标识

        返回:
            包含数字统计数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        number_type = str(options.get("number_type") or "count")
        time_type = str(options.get("number_time_type") or "shot_time")

        # 根据时间类型选择使用的时间列
        if time_type == "imported_at":
            time_col = "COALESCE(NULLIF(imported_at,''), created_at)"
        elif time_type == "created_at":
            time_col = "created_at"
        else:  # 默认为拍摄时间
            time_col = "COALESCE(NULLIF(shot_time,''), created_at)"

        # 构建时间范围筛选
        time_start = str(options.get("number_time_start") or "").strip()
        time_end = str(options.get("number_time_end") or "").strip()
        time_end_now = bool(options.get("number_time_end_now", False))

        extra = []
        extra_params = []

        # 添加时间范围条件
        if time_start:
            extra.append(f"{time_col} >= ?")
            extra_params.append(time_start)
        if time_end and not time_end_now:
            extra.append(f"{time_col} <= ?")
            extra_params.append(time_end)

        # 构建筛选条件
        filters = options.get("number_filters") or []
        if filters and hasattr(self._db, 'build_where_from_conditions'):
            try:
                filter_sql, filter_params = self._db.build_where_from_conditions(filters, exclude_fields=set())
                if filter_sql:
                    extra.append(filter_sql)
                    extra_params.extend(filter_params)
            except Exception:
                pass

        # 构建 WHERE 子句
        where_parts = [f"{time_col} IS NOT NULL AND {time_col} != ''"]
        if extra:
            where_parts.extend(extra)
        where_sql = " AND ".join(where_parts)

        # 根据数据类型计算数值
        if number_type == "species_count":
            # 鸟种数：统计不同的物种数量
            sql = f"""
                SELECT COUNT(DISTINCT species_cls) as value
                FROM {table_name}
                WHERE {where_sql}
                AND species_cls IS NOT NULL AND species_cls != ''
            """
            title = "鸟种数"
        elif number_type == "new_species":
            # 加新数量：统计在当前时间范围内首次出现的物种数量
            sql = f"""
                SELECT COUNT(*) as value
                FROM (
                    SELECT species_cls
                    FROM {table_name}
                    WHERE {where_sql}
                    AND species_cls IS NOT NULL AND species_cls != ''
                    GROUP BY species_cls
                    HAVING MIN({time_col}) >= ?
                )
            """
            # 加新数量需要起始时间
            if time_start:
                extra_params.insert(0, time_start)
            else:
                # 如果没有起始时间，查询所有时间
                sql = f"""
                    SELECT COUNT(DISTINCT species_cls) as value
                    FROM {table_name}
                    WHERE {where_sql}
                    AND species_cls IS NOT NULL AND species_cls != ''
                """
            title = "加新数量"
        else:
            # 默认：图片数量
            sql = f"""
                SELECT COUNT(*) as value
                FROM {table_name}
                WHERE {where_sql}
            """
            title = "图片数量"

        result = self._db.query(sql, extra_params).rows or []
        value = int(result[0].get("value", 0)) if result else 0

        return {
            "kind": "number",
            "value": value,
            "title": title,
            "meta": {
                "number_type": number_type,
                "time_type": time_type
            }
        }
