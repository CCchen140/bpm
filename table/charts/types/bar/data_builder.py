from __future__ import annotations

from typing import Dict, List, Any, Optional
import datetime
import calendar

from table.charts.types import ChartDataBuilder, register_chart


@register_chart("bar")
class BarDataBuilder(ChartDataBuilder):
    """柱状图数据生成器"""

    def build_payload(self, table_name: str, options: dict, chart_type: str = "bar") -> dict:
        """构建柱状图数据"""
        # 检查数据库是否可用 - self._db 就是 ChartsDataService 实例
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        kind = str(options.get("bar_x_kind") or "time")
        filters = options.get("bar_filters") or []
        y_kind = str(options.get("bar_y_kind") or "count")
        y_expr = "COUNT(*)"
        series_name = "图片数量"

        if y_kind == "new_species":
            y_expr = "COUNT(DISTINCT species_cls)"
            series_name = "加新次数"
        elif y_kind == "species_count":
            y_expr = "COUNT(DISTINCT species_cls)"
            series_name = "鸟种数"

        exclude = set()
        if kind == "time":
            exclude.add("拍摄时间")
        elif kind == "location":
            exclude.add("拍摄地址")
        elif kind == "rating":
            exclude.add("评星")
        elif kind == "label":
            exclude.add("色标")
        elif kind == "score":
            exclude.add("分数")
        elif kind == "iso":
            pass  # ISO没有对应筛选项
        elif kind == "shutter":
            pass  # 快门没有对应筛选项
        elif kind == "fnumber":
            pass  # 光圈没有对应筛选项
        elif kind == "focal_length":
            pass  # 焦距没有对应筛选项
        elif kind == "species":
            exclude.add("种")
        elif kind == "order":
            exclude.add("目")
        elif kind == "family":
            exclude.add("科")
        elif kind == "genus":
            exclude.add("属")

        # self._db 就是 ChartsDataService，直接使用其方法
        where_expr, params = self._db.build_where_from_conditions(filters, exclude_fields=exclude)
        extra = []
        extra_params: list = []

        if kind == "time":
            return self._build_time_payload(
                table_name, options, chart_type, y_kind, y_expr, series_name,
                where_expr, params, extra, extra_params
            )
        elif kind == "rating":
            return self._build_rating_payload(
                table_name, options, chart_type, y_kind, y_expr, series_name,
                where_expr, params, extra, extra_params
            )
        elif kind == "label":
            return self._build_label_payload(
                table_name, options, chart_type, y_kind, y_expr, series_name,
                where_expr, params, extra, extra_params
            )
        elif kind == "location":
            return {"kind": "empty", "message": "地点统计暂未实现(仅提供 UI)"}
        elif kind in ("score", "iso", "shutter", "fnumber", "focal_length"):
            return self._build_numeric_field_payload(
                table_name, options, chart_type, kind, y_kind, y_expr, series_name,
                where_expr, params, extra, extra_params
            )
        elif kind in ("species", "order", "family", "genus"):
            return self._build_taxonomy_field_payload(
                table_name, options, chart_type, kind, y_kind, y_expr, series_name,
                where_expr, params, extra, extra_params
            )

        return {"kind": "empty", "message": "暂无数据"}

    def _build_time_payload(
        self, table_name: str, options: dict, chart_type: str, y_kind: str, y_expr: str, series_name: str,
        where_expr: str, params: list, extra: list, extra_params: list
    ) -> dict:
        """构建时间维度柱状图数据"""
        # 根据时间类型选择使用的时间列，默认为拍摄时间
        time_type = str(options.get("bar_time_type") or "shot_time")
        if time_type == "imported_at":
            time_col = "COALESCE(NULLIF(imported_at,''), created_at)"
        elif time_type == "created_at":
            time_col = "created_at"
        else:
            time_col = "COALESCE(NULLIF(shot_time,''), created_at)"

        unit = str(options.get("bar_time_unit") or "day")
        try:
            step = int(options.get("bar_time_step") or 1)
        except Exception:
            step = 1
        step = max(1, min(3650, step))

        if unit == "month":
            year_expr = f"CAST(substr({time_col}, 1, 4) AS INTEGER)"
            month_expr = f"CAST(substr({time_col}, 6, 2) AS INTEGER)"
            idx = f"({year_expr} * 12 + {month_expr} - 1)"
            bucket = f"(CAST(CAST(({idx})/{step} AS INTEGER) * {step} AS INTEGER))"
            group_expr = f"printf('%04d-%02d-01', CAST(({bucket})/12 AS INTEGER), (({bucket}) % 12) + 1)"
        elif unit == "year":
            yv = f"CAST(substr({time_col}, 1, 4) AS INTEGER)"
            by = f"(CAST(CAST(({yv})/{step} AS INTEGER) * {step} AS INTEGER))"
            group_expr = f"printf('%04d-01-01', {by})"
        else:
            seconds = 86400 * step
            group_expr = f"date(CAST(CAST(strftime('%s', substr({time_col}, 1, 10)) AS INTEGER) / {seconds} AS INTEGER) * {seconds}, 'unixepoch')"

        extra.append(f"{time_col} IS NOT NULL AND {time_col} != ''")

        # 处理时间范围
        start, end, end_now = self._parse_time_range(options)

        if start:
            extra.append(f"{time_col} >= ?")
            extra_params.append(start + (" 00:00:00" if len(start) == 10 else ""))
        if end_now:
            try:
                end = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                end = ""
        if end:
            extra.append(f"{time_col} <= ?")
            extra_params.append(end + (" 23:59:59" if len(end) == 10 else ""))

        if y_kind in ("new_species", "species_count"):
            extra.append("species_cls IS NOT NULL AND species_cls != ''")

        all_where = []
        if where_expr:
            all_where.append(f"({where_expr})")
        if extra:
            all_where.append("(" + " AND ".join(extra) + ")")
        final_where = " AND ".join(all_where)
        final_params = list(params or []) + list(extra_params or [])

        # 查询数据
        if y_kind == "new_species":
            rows = self._query_new_species_by_time(
                table_name, group_expr, final_where, final_params, unit, step, time_type
            )
        else:
            # 使用 self._db.query 直接查询
            sql = f"""
                SELECT {group_expr} AS x, {y_expr} AS y
                FROM {table_name}
                WHERE {final_where}
                GROUP BY x
                ORDER BY x ASC
                LIMIT 2000
            """
            rows = self._db.query(sql, final_params).rows or []

        m: Dict[str, float] = {}
        for r in rows:
            x = str(r.get("x") or "")
            if not x:
                continue
            m[x] = self._safe_float(r.get("y"), 0.0)

        # 处理隐藏无数据时间的选项
        ignore_empty_dates = bool(
            options.get("bar_ignore_empty_dates", self._display_options.get("ignore_empty_dates", False))
        )
        if ignore_empty_dates:
            xs = [str(r.get("x") or "") for r in rows if str(r.get("x") or "") and self._safe_float(r.get("y"), 0.0) > 0]
            if not xs:
                return {"kind": "empty", "message": "暂无数据"}
            ys = [m.get(x, 0.0) for x in xs]
            return {
                "kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs,
                "series": [{"name": series_name, "data": ys}],
                "meta": {"bar_x_kind": "time", "unit": unit, "step": step, "bar_y_kind": y_kind}
            }

        # 填充完整的时间范围
        xs = self._fill_time_range(start, end, end_now, unit, step, m)
        if not xs:
            return {"kind": "empty", "message": "暂无数据"}

        ys = [m.get(x, 0.0) for x in xs]
        return {
            "kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs,
            "series": [{"name": series_name, "data": ys}],
            "meta": {"bar_x_kind": "time", "unit": unit, "step": step, "bar_y_kind": y_kind}
        }

    def _parse_time_range(self, options: dict) -> tuple:
        """解析时间范围配置"""
        preset = str(options.get("bar_time_preset") or "").strip().lower()
        start = str(options.get("bar_time_start") or "").strip()
        end = str(options.get("bar_time_end") or "").strip()
        end_now = bool(
            options.get("bar_time_end_now", False) or
            str(options.get("bar_time_end") or "").strip().lower() in ("now", "__now__", "today") or
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

    def _fill_time_range(self, start: str, end: str, end_now: bool, unit: str, step: int, m: Dict[str, float]) -> List[str]:
        """填充完整的时间范围"""
        def _parse_dt(v: str):
            if not v:
                return None
            s = str(v).strip()
            if not s:
                return None
            try:
                if len(s) == 10:
                    return datetime.datetime.strptime(s, "%Y-%m-%d")
                return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    return datetime.datetime.fromisoformat(s)
                except Exception:
                    return None

        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end)

        if end_dt and isinstance(end, str) and len(end) == 10:
            try:
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
            except Exception:
                pass

        if not end_dt and end_now:
            try:
                end_dt = datetime.datetime.now()
            except Exception:
                end_dt = None

        if not start_dt or not end_dt:
            try:
                if m:
                    xs_sorted = sorted(m.keys())
                    if not start_dt and xs_sorted:
                        start_dt = _parse_dt(xs_sorted[0])
                    if not end_dt and xs_sorted:
                        end_dt = _parse_dt(xs_sorted[-1])
            except Exception:
                pass

        if not start_dt or not end_dt:
            return []

        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt

        xs: List[str] = []
        if unit == "month":
            s_idx = start_dt.year * 12 + start_dt.month - 1
            e_idx = end_dt.year * 12 + end_dt.month - 1
            s_bucket = int(s_idx // step) * step
            e_bucket = int(e_idx // step) * step
            idx = s_bucket
            while idx <= e_bucket:
                yv = int(idx // 12)
                mv = int(idx % 12) + 1
                xs.append(f"{yv:04d}-{mv:02d}-01")
                idx += step
        elif unit == "year":
            s_bucket = int(start_dt.year // step) * step
            e_bucket = int(end_dt.year // step) * step
            yv = s_bucket
            while yv <= e_bucket:
                xs.append(f"{yv:04d}-01-01")
                yv += step
        else:
            try:
                seconds = 86400 * step
                s_ts = int(calendar.timegm(start_dt.timetuple()))
                e_ts = int(calendar.timegm(end_dt.timetuple()))
                s_bucket = int(s_ts // seconds) * seconds
                e_bucket = int(e_ts // seconds) * seconds
                cur = s_bucket
                while cur <= e_bucket:
                    xs.append(datetime.datetime.utcfromtimestamp(cur).strftime("%Y-%m-%d"))
                    cur += seconds
            except Exception:
                xs = []

        return xs

    def _build_rating_payload(
        self, table_name: str, options: dict, chart_type: str, y_kind: str, y_expr: str, series_name: str,
        where_expr: str, params: list, extra: list, extra_params: list
    ) -> dict:
        """构建评星维度柱状图数据"""
        group_expr = "rating"
        extra.append("rating >= 1 AND rating <= 5")
        if y_kind in ("new_species", "species_count"):
            extra.append("species_cls IS NOT NULL AND species_cls != ''")

        all_where = []
        if where_expr:
            all_where.append(f"({where_expr})")
        if extra:
            all_where.append("(" + " AND ".join(extra) + ")")
        final_where = " AND ".join(all_where)
        final_params = list(params or []) + list(extra_params or [])

        sql = f"""
            SELECT {group_expr} AS x, {y_expr} AS y
            FROM {table_name}
            WHERE {final_where}
            GROUP BY x
            ORDER BY x ASC
            LIMIT 10
        """
        rows = self._db.query(sql, final_params).rows or []

        m: Dict[str, float] = {}
        for r in rows:
            try:
                k = str(int(r.get("x") or 0))
            except Exception:
                continue
            m[k] = self._safe_float(r.get("y"), 0.0)

        xs = ["1", "2", "3", "4", "5"]
        ys = [m.get(x, 0.0) for x in xs]
        return {
            "kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs,
            "series": [{"name": series_name, "data": ys}],
            "meta": {"bar_x_kind": "rating", "bar_y_kind": y_kind}
        }

    def _build_label_payload(
        self, table_name: str, options: dict, chart_type: str, y_kind: str, y_expr: str, series_name: str,
        where_expr: str, params: list, extra: list, extra_params: list
    ) -> dict:
        """构建色标维度柱状图数据"""
        group_expr = "CASE WHEN label IS NULL OR label = '' THEN 'None' ELSE label END"
        if y_kind in ("new_species", "species_count"):
            extra.append("species_cls IS NOT NULL AND species_cls != ''")

        all_where = [f"({where_expr})"] if where_expr else []
        if extra:
            all_where.append("(" + " AND ".join(extra) + ")")
        final_where = " AND ".join(all_where)
        final_params = list(params or []) + list(extra_params or [])

        sql = f"""
            SELECT {group_expr} AS x, {y_expr} AS y
            FROM {table_name}
            WHERE {final_where}
            GROUP BY x
            ORDER BY y DESC
            LIMIT 30
        """
        rows = self._db.query(sql, final_params).rows or []

        order = ["Green", "Blue", "Yellow", "Red", "Purple", "White", "Orange", "Pink", "Black"]
        m: Dict[str, float] = {}
        for r in rows:
            k = str(r.get("x") or "").strip()
            if not k or k == "None":
                continue
            m[k] = self._safe_float(r.get("y"), 0.0)

        xs = [x for x in order if x in m] + [k for k in m.keys() if k not in order and k != "None"]
        if not xs:
            return {"kind": "empty", "message": "暂无数据"}

        ys = [m.get(x, 0.0) for x in xs]
        return {
            "kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs,
            "series": [{"name": series_name, "data": ys}],
            "meta": {"bar_x_kind": "label", "bar_y_kind": y_kind}
        }

    def _query_new_species_by_time(
        self, table_name: str, group_expr: str, where_expr: str, params: list,
        unit: str, step: int, time_type: str = "shot_time"
    ) -> list:
        """查询加新次数：统计在每个时段内首次添加到图库的物种数量"""
        if time_type == "imported_at":
            time_col = "COALESCE(NULLIF(imported_at,''), created_at)"
        elif time_type == "created_at":
            time_col = "created_at"
        else:
            time_col = "COALESCE(NULLIF(shot_time,''), created_at)"

        where_sql = f"WHERE {where_expr}" if where_expr else ""

        if unit == "month":
            bucket_expr = f"substr(MIN({time_col}), 1, 7) || '-01'"
        elif unit == "year":
            bucket_expr = f"substr(MIN({time_col}), 1, 4) || '-01-01'"
        else:
            seconds = 86400 * step
            bucket_expr = f"date(CAST(CAST(strftime('%s', substr(MIN({time_col}), 1, 10)) AS INTEGER) / {seconds} AS INTEGER) * {seconds}, 'unixepoch')"

        time_not_empty = f"AND {time_col} IS NOT NULL AND {time_col} != ''"

        sql = f"""
            SELECT x, COUNT(*) AS y
            FROM (
                SELECT {bucket_expr} AS x
                FROM {table_name}
                {where_sql}
                AND species_cls IS NOT NULL AND species_cls != ''
                {time_not_empty}
                GROUP BY species_cls
            )
            GROUP BY x
            ORDER BY x ASC
        """

        result = self._db.query(sql, params or [])
        return result.rows or []

    def _build_numeric_field_payload(
        self, table_name: str, options: dict, chart_type: str, field: str, y_kind: str, y_expr: str, series_name: str,
        where_expr: str, params: list, extra: list, extra_params: list
    ) -> dict:
        """构建数值型字段维度柱状图数据（评分、ISO、快门、光圈、焦距）"""
        # 根据字段类型确定分组表达式
        if field == "score":
            group_expr = "CAST(score AS INTEGER)"
            extra.append("score IS NOT NULL")
            field_name = "评分"
        elif field == "iso":
            group_expr = "iso"
            extra.append("iso IS NOT NULL")
            field_name = "ISO"
        elif field == "shutter":
            # 快门值分组
            group_expr = "shutter"
            extra.append("shutter IS NOT NULL AND shutter != ''")
            field_name = "快门"
        elif field == "fnumber":
            group_expr = "fnumber"
            extra.append("fnumber IS NOT NULL")
            field_name = "光圈"
        elif field == "focal_length":
            # 焦距分组
            group_expr = "focal_length"
            extra.append("focal_length IS NOT NULL AND focal_length != ''")
            field_name = "焦距"
        else:
            return {"kind": "empty", "message": "未知字段类型"}

        if y_kind in ("new_species", "species_count"):
            extra.append("species_cls IS NOT NULL AND species_cls != ''")

        all_where = []
        if where_expr:
            all_where.append(f"({where_expr})")
        if extra:
            all_where.append("(" + " AND ".join(extra) + ")")
        final_where = " AND ".join(all_where)
        final_params = list(params or []) + list(extra_params or [])

        sql = f"""
            SELECT {group_expr} AS x, {y_expr} AS y
            FROM {table_name}
            WHERE {final_where}
            GROUP BY x
            ORDER BY x ASC
            LIMIT 100
        """
        rows = self._db.query(sql, final_params).rows or []

        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

        xs = []
        ys = []
        for r in rows:
            x = str(r.get("x") or "")
            if not x:
                continue
            xs.append(x)
            ys.append(self._safe_float(r.get("y"), 0.0))

        if not xs:
            return {"kind": "empty", "message": "暂无数据"}

        return {
            "kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs,
            "series": [{"name": series_name, "data": ys}],
            "meta": {"bar_x_kind": field, "bar_y_kind": y_kind}
        }

    def _build_taxonomy_field_payload(
        self, table_name: str, options: dict, chart_type: str, field: str, y_kind: str, y_expr: str, series_name: str,
        where_expr: str, params: list, extra: list, extra_params: list
    ) -> dict:
        """构建分类学字段维度柱状图数据（物种、目、科、属）"""
        # 根据字段类型确定分组表达式
        if field == "species":
            group_expr = "species_cls"
            extra.append("species_cls IS NOT NULL AND species_cls != ''")
            field_name = "物种"
        elif field == "order":
            group_expr = "order_cls"
            extra.append("order_cls IS NOT NULL AND order_cls != ''")
            field_name = "目"
        elif field == "family":
            group_expr = "family_cls"
            extra.append("family_cls IS NOT NULL AND family_cls != ''")
            field_name = "科"
        elif field == "genus":
            group_expr = "genus_cls"
            extra.append("genus_cls IS NOT NULL AND genus_cls != ''")
            field_name = "属"
        else:
            return {"kind": "empty", "message": "未知字段类型"}

        if y_kind in ("new_species", "species_count"):
            extra.append("species_cls IS NOT NULL AND species_cls != ''")

        all_where = []
        if where_expr:
            all_where.append(f"({where_expr})")
        if extra:
            all_where.append("(" + " AND ".join(extra) + ")")
        final_where = " AND ".join(all_where)
        final_params = list(params or []) + list(extra_params or [])

        sql = f"""
            SELECT {group_expr} AS x, {y_expr} AS y
            FROM {table_name}
            WHERE {final_where}
            GROUP BY x
            ORDER BY y DESC
            LIMIT 50
        """
        rows = self._db.query(sql, final_params).rows or []

        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

        xs = []
        ys = []
        for r in rows:
            x = str(r.get("x") or "")
            if not x:
                continue
            xs.append(x)
            ys.append(self._safe_float(r.get("y"), 0.0))

        if not xs:
            return {"kind": "empty", "message": "暂无数据"}

        return {
            "kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs,
            "series": [{"name": series_name, "data": ys}],
            "meta": {"bar_x_kind": field, "bar_y_kind": y_kind}
        }
