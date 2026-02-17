from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from utils.log_manager import LogManager
from utils.sql.data_base import BirdLibraryDB

from table.chart_types import CHART_TYPES, CHART_TYPE_TITLE_MAP
from table.web.data_query_service import ChartsDataService


def _project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    except Exception:
        return os.getcwd()


def _store_path() -> str:
    try:
        from utils.paths import PathManager

        p = PathManager.instance().get_user_table_setting_dir() / "charts_layout_v2.json"
        return str(p)
    except Exception:
        return os.path.join(_project_root(), "data", "cache", "charts_layout_v2.json")


def _ensure_parent_dir(path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ChartRecord:
    chart_id: str
    config: dict
    layout: dict


class ChartsBackendManager:
    def __init__(self):
        self._db_error: str = ""
        try:
            self._db = BirdLibraryDB()
        except Exception as e:
            self._db = None
            self._db_error = str(e)
            self._log_warning(f"图表数据库初始化失败: {e}")
        self._data = ChartsDataService(self._db)
        self._charts: Dict[str, ChartRecord] = {}
        self._theme: str = "follow"
        self._display_options: Dict[str, Any] = {
            "show_title": True,
            "show_legend": True,
            "show_grid": True,
            "enable_animation": True,
            "pause_refresh_on_mouse_leave": False,
            "font_size": 12,
            "watermark_enabled": False,
            "watermark_text": "",
            "watermark_font_size": 22,
            "echarts_theme": "dark",
            "window_style": "acrylic",
            "ignore_empty_dates": False,
        }
        self._gpu_rendering_enabled: bool = False
        self._load_preferences()
        self._load_layout_state()

    def _log_warning(self, msg: str) -> None:
        try:
            LogManager.instance().warning(msg)
        except Exception:
            pass

    def _log_debug(self, msg: str) -> None:
        try:
            LogManager.instance().debug(msg)
        except Exception:
            pass

    def _settings(self):
        try:
            from utils.setting.settings_manager import SettingsManager

            return SettingsManager.instance()
        except Exception:
            return None

    def _display_option_keys(self) -> Dict[str, Tuple[str, Any]]:
        return {
            "show_title": ("charts/show_title", True),
            "show_legend": ("charts/show_legend", True),
            "show_grid": ("charts/show_grid", True),
            "enable_animation": ("charts/enable_animation", True),
            "pause_refresh_on_mouse_leave": ("charts/pause_refresh_on_mouse_leave", False),
            "font_size": ("charts/font_size", 12),
            "watermark_enabled": ("charts/watermark_enabled", False),
            "watermark_text": ("charts/watermark_text", ""),
            "watermark_font_size": ("charts/watermark_font_size", 22),
            "echarts_theme": ("charts/echarts_theme", "dark"),
            "window_style": ("charts/window_style", "acrylic"),
            "ignore_empty_dates": ("charts/ignore_empty_dates", False),
        }

    def _has_any_display_options_in_settings(self, sm) -> bool:
        try:
            if sm is None or not hasattr(sm, "contains"):
                return False
            for _, (k, _) in self._display_option_keys().items():
                try:
                    if sm.contains(k):
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _load_preferences(self) -> None:
        sm = self._settings()
        if sm is None:
            self._load_preferences_from_legacy_file(migrate_to_settings=False)
            return
        try:
            theme = str(sm.get("charts/theme", "follow") or "follow")
            self._theme = theme
        except Exception:
            pass
        try:
            self._gpu_rendering_enabled = bool(sm.get("charts/gpu_rendering_enabled", False))
        except Exception:
            pass
        has_any = self._has_any_display_options_in_settings(sm)
        if not has_any:
            try:
                raw = str(sm.get("charts/display_options_json", "{}") or "{}")
                obj = json.loads(raw) if raw else {}
            except Exception:
                obj = {}
            if isinstance(obj, dict) and obj:
                merged = dict(self._display_options)
                merged.update(obj)
                self._display_options = merged
                try:
                    for opt_key, (k, _) in self._display_option_keys().items():
                        if opt_key in merged:
                            sm.set(k, merged.get(opt_key))
                    sm.sync()
                except Exception:
                    pass
        try:
            for opt_key, (k, default) in self._display_option_keys().items():
                try:
                    v = sm.get(k, default)
                    self._display_options[opt_key] = v
                except Exception:
                    continue
        except Exception:
            pass

    def _save_preferences(self) -> None:
        sm = self._settings()
        if sm is None:
            return
        try:
            sm.set("charts/theme", str(self._theme or "follow"))
            sm.set("charts/gpu_rendering_enabled", bool(self._gpu_rendering_enabled))
            for opt_key, (k, default) in self._display_option_keys().items():
                sm.set(k, (self._display_options or {}).get(opt_key, default))
            sm.set("charts/display_options_json", json.dumps(self._display_options or {}, ensure_ascii=False))
            sm.sync()
        except Exception:
            return

    def _load_preferences_from_legacy_file(self, migrate_to_settings: bool) -> None:
        p = _store_path()
        try:
            if not os.path.exists(p):
                return
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            return
        try:
            theme = str(obj.get("theme") or "follow")
            display_options = obj.get("display_options")
            gpu = bool(obj.get("gpu_rendering_enabled", False))
            if theme:
                self._theme = theme
            if isinstance(display_options, dict) and display_options:
                merged = dict(self._display_options)
                merged.update(display_options)
                self._display_options = merged
            self._gpu_rendering_enabled = gpu
        except Exception:
            return
        if not migrate_to_settings:
            return
        sm = self._settings()
        if sm is None:
            return
        try:
            if hasattr(sm, "contains") and sm.contains("charts/theme"):
                return
        except Exception:
            pass
        try:
            sm.set("charts/theme", str(self._theme or "follow"))
            sm.set("charts/gpu_rendering_enabled", bool(self._gpu_rendering_enabled))
            for opt_key, (k, default) in self._display_option_keys().items():
                sm.set(k, (self._display_options or {}).get(opt_key, default))
            sm.set("charts/display_options_json", json.dumps(self._display_options or {}, ensure_ascii=False))
            sm.sync()
        except Exception:
            pass

    def _load_layout_state(self) -> None:
        p = _store_path()
        try:
            if not os.path.exists(p):
                self._load_preferences_from_legacy_file(migrate_to_settings=True)
                return
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            return
        try:
            charts = obj.get("charts") or []
            for c in charts:
                cid = str(c.get("chart_id") or "")
                cfg = dict(c.get("config") or {})
                layout = dict(c.get("layout") or {})
                if cid:
                    self._charts[cid] = ChartRecord(chart_id=cid, config=cfg, layout=layout)
            self._load_preferences_from_legacy_file(migrate_to_settings=True)
        except Exception:
            return

    def _save_layout_state(self) -> None:
        p = _store_path()
        _ensure_parent_dir(p)
        try:
            obj = {
                "version": 3,
                "saved_at": _now_ms(),
                "charts": [{"chart_id": c.chart_id, "config": c.config, "layout": c.layout} for c in self._charts.values()],
            }
            with open(p, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log_warning(f"图表布局保存失败: {e}")

    def bootstrap(self) -> dict:
        tags: list = []
        try:
            from utils.tag_manager import TagManager

            tags = TagManager.instance().get_all_tags() or []
        except Exception:
            tags = []
        return {
            "chart_types": [{"id": t.chart_type, "title": t.title} for t in CHART_TYPES],
            "tags": [{"id": t, "title": t} for t in tags],
            "fields": [
                {"id": "score", "title": "评分"},
                {"id": "iso", "title": "ISO"},
                {"id": "shutter", "title": "快门"},
                {"id": "fnumber", "title": "光圈"},
                {"id": "focal_length", "title": "焦距"},
                {"id": "shot_time", "title": "拍摄时间"},
                {"id": "created_at", "title": "创建时间"},
                {"id": "species", "title": "物种"},
                {"id": "order", "title": "目"},
                {"id": "family", "title": "科"},
                {"id": "genus", "title": "属"},
            ],
            "aggs": [
                {"id": "count", "title": "数量"},
                {"id": "mean", "title": "平均值(评分)"},
                {"id": "sum", "title": "求和(评分)"},
            ],
            "theme": self._theme,
            "display_options": self._display_options,
            "gpu_rendering_enabled": self._gpu_rendering_enabled,
            "db_ready": bool(self._db is not None),
            "db_error": str(self._db_error or ""),
            "charts": [self._serialize_chart(c) for c in self._charts.values()],
        }

    def _serialize_chart(self, rec: ChartRecord) -> dict:
        cfg = dict(rec.config or {})
        t = str(cfg.get("type") or "")
        ds = str(cfg.get("dataset") or "")
        return {
            "chart_id": rec.chart_id,
            "name": str(cfg.get("name") or "未命名图表"),
            "type": t,
            "type_title": CHART_TYPE_TITLE_MAP.get(t, t or "未知"),
            "dataset": ds,
            "options": dict(cfg.get("options") or {}),
            "layout": dict(rec.layout or {}),
        }

    def add_chart(self, config: dict) -> dict:
        cfg = dict(config or {})
        chart_id = uuid.uuid4().hex
        self._charts[chart_id] = ChartRecord(chart_id=chart_id, config=cfg, layout={})
        self._save_layout_state()
        return self._serialize_chart(self._charts[chart_id])

    def update_chart(self, chart_id: str, config: dict) -> dict:
        cid = str(chart_id or "")
        if not cid:
            raise ValueError("chart_id required")
        rec = self._charts.get(cid)
        if rec is None:
            raise KeyError("chart not found")
        rec.config = dict(config or {})
        self._save_layout_state()
        return self._serialize_chart(rec)

    def remove_chart(self, chart_id: str) -> None:
        cid = str(chart_id or "")
        if not cid:
            return
        self._charts.pop(cid, None)
        self._save_layout_state()

    def update_layout(self, chart_id: str, layout: dict) -> None:
        cid = str(chart_id or "")
        if not cid:
            return
        rec = self._charts.get(cid)
        if rec is None:
            return
        rec.layout = dict(layout or {})
        self._save_layout_state()

    def set_theme(self, theme: str) -> None:
        self._theme = str(theme or "follow")
        self._save_preferences()

    def set_display_options(self, options: dict) -> None:
        merged = dict(self._display_options)
        merged.update(dict(options or {}))
        self._display_options = merged
        self._save_preferences()

    def set_gpu_rendering_enabled(self, enabled: bool) -> None:
        self._gpu_rendering_enabled = bool(enabled)
        self._save_preferences()

    def set_preferences(self, theme: str, options: dict, gpu_enabled: bool) -> None:
        self._theme = str(theme or "follow")
        merged = dict(self._display_options)
        merged.update(dict(options or {}))
        self._display_options = merged
        self._gpu_rendering_enabled = bool(gpu_enabled)
        self._save_preferences()

    def _table_name(self, dataset: str) -> str:
        ds = str(dataset or "library")
        return "bird_results"

    def update_dataset_user_field(self, dataset: str, field_name: str, field_value: Any, file_paths: List[str]) -> None:
        table_name = self._table_name(dataset)
        if self._data is None:
            return
        self._data.update_user_field_batch(table_name, str(field_name or ""), field_value, list(file_paths or []))

    def build_chart_payload(self, chart: dict) -> dict:
        cfg = dict(chart or {})
        chart_id = str(cfg.get("chart_id") or "")
        config = dict(cfg.get("config") or cfg)
        t = str(config.get("type") or "")
        ds = str(config.get("dataset") or "library")
        table_name = self._table_name(ds)
        options = dict(config.get("options") or {})

        try:
            if t in ("bar", "line", "timelineLine") and str(options.get("bar_x_kind") or "").strip():
                return self._payload_bar_custom(table_name, options, chart_type=t)
            if t in ("bar", "line", "timelineLine", "bar3D"):
                return self._payload_xy(t, table_name, options)
            if t == "pie":
                return self._payload_pie(table_name, options)
            if t == "scatter":
                return self._payload_scatter(table_name, options)
            if t in ("tree", "treemap", "sunburst"):
                return self._payload_taxonomy_tree(table_name)
            if t in ("map", "geo", "geoGraph", "lines", "globe3D"):
                return self._payload_geo_points(table_name)
            if t == "graph":
                return self._payload_taxonomy_graph(table_name)
            if t in ("gauge", "customGauge"):
                return self._payload_gauge(table_name)
            if t in ("radar", "radarCustom", "radarMulti"):
                return self._payload_radar(table_name)
            if t in ("calendar", "calendarH"):
                return self._payload_calendar(table_name)
            if t in ("scrollLegend", "timelineGallery"):
                return self._payload_gallery(table_name)
        except Exception as e:
            self._log_warning(f"构建图表数据失败({t}): {e}")

        return {"kind": "empty", "message": "暂无可用数据"}

    def _payload_xy(self, chart_type: str, table_name: str, options: dict) -> dict:
        x_field = str(options.get("x_field") or "")
        y_agg = str(options.get("y_agg") or "count")
        group_field = str(options.get("group_field") or "")
        smooth = bool(options.get("smooth", False))

        x_expr, where, params = self._group_expr_for_field(x_field)
        group_expr, group_where, group_params = self._group_expr_for_field(group_field) if group_field else (None, "", [])
        wheres = [w for w in [where, group_where] if w]
        params = list(params or []) + list(group_params or [])
        where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

        y_sql = "COUNT(*)"
        if y_agg == "mean":
            y_sql = "AVG(score)"
        elif y_agg == "sum":
            y_sql = "SUM(score)"

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

        rows = self._query(sql, params)
        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

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

        xs = [str(r.get("x") or "") for r in rows]
        ys = [_safe_float(r.get("y"), 0.0) for r in rows]
        return {
            "kind": "xy",
            "chart_type": chart_type,
            "x": xs,
            "series": [{"name": "数值", "data": ys}],
            "meta": {"y_agg": y_agg, "smooth": smooth},
        }

    def _payload_bar_custom(self, table_name: str, options: dict, chart_type: str = "bar") -> dict:
        if not self._data or not self._data.is_ready():
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

        where_expr, params = self._data.build_where_from_conditions(filters, exclude_fields=exclude)
        extra = []
        extra_params: list = []

        if kind == "time":
            time_col = "COALESCE(NULLIF(imported_at,''), created_at)"
            unit = str(options.get("bar_time_unit") or "day")
            try:
                step = int(options.get("bar_time_step") or 1)
            except Exception:
                step = 1
            step = max(1, min(3650, step))
            if unit == "month":
                idx = f"(CAST(strftime('%Y',{time_col}) AS INTEGER) * 12 + CAST(strftime('%m',{time_col}) AS INTEGER) - 1)"
                bucket = f"(CAST(CAST(({idx})/{step} AS INTEGER) * {step} AS INTEGER))"
                group_expr = f"printf('%04d-%02d-01', CAST(({bucket})/12 AS INTEGER), (({bucket}) % 12) + 1)"
            elif unit == "year":
                yv = f"CAST(strftime('%Y',{time_col}) AS INTEGER)"
                by = f"(CAST(CAST(({yv})/{step} AS INTEGER) * {step} AS INTEGER))"
                group_expr = f"printf('%04d-01-01', {by})"
            else:
                seconds = 86400 * step
                group_expr = f"date(CAST(CAST(strftime('%s',{time_col}) AS INTEGER) / {seconds} AS INTEGER) * {seconds}, 'unixepoch')"
            extra.append(f"{time_col} IS NOT NULL AND {time_col} != ''")
            preset = str(options.get("bar_time_preset") or "").strip().lower()
            start = str(options.get("bar_time_start") or "").strip()
            end = str(options.get("bar_time_end") or "").strip()
            end_now = bool(options.get("bar_time_end_now", False) or str(options.get("bar_time_end") or "").strip().lower() in ("now", "__now__", "today"))
            if preset in ("today", "week", "month", "year"):
                try:
                    import datetime

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
            if start:
                extra.append(f"{time_col} >= ?")
                extra_params.append(start + (" 00:00:00" if len(start) == 10 else ""))
            if end_now:
                try:
                    import datetime

                    end = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    end = ""
            if end:
                extra.append(f"{time_col} <= ?")
                extra_params.append(end + (" 23:59:59" if len(end) == 10 else ""))
            if y_kind == "new_species":
                extra.append("species_cls IS NOT NULL AND species_cls != ''")
            elif y_kind == "species_count":
                extra.append("species_cls IS NOT NULL AND species_cls != ''")

            all_where = []
            if where_expr:
                all_where.append(f"({where_expr})")
            if extra:
                all_where.append("(" + " AND ".join(extra) + ")")
            final_where = " AND ".join(all_where)
            final_params = list(params or []) + list(extra_params or [])
            rows = self._data.query_group_agg(table_name, group_expr, y_expr, final_where, final_params, order_by="x ASC", limit=2000).rows or []
            m: Dict[str, float] = {}
            for r in rows:
                x = str(r.get("x") or "")
                if not x:
                    continue
                m[x] = _safe_float(r.get("y"), 0.0)
            ignore_empty_dates = bool(self._display_options.get("ignore_empty_dates", False))
            if ignore_empty_dates:
                xs = [str(r.get("x") or "") for r in rows if str(r.get("x") or "")]
                if not xs:
                    return {"kind": "empty", "message": "暂无数据"}
                ys = [m.get(x, 0.0) for x in xs]
                return {"kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs, "series": [{"name": series_name, "data": ys}], "meta": {"bar_x_kind": kind, "unit": unit, "step": step, "bar_y_kind": y_kind}}

            def _parse_dt(v: str):
                if not v:
                    return None
                s = str(v).strip()
                if not s:
                    return None
                try:
                    if len(s) == 10:
                        import datetime

                        return datetime.datetime.strptime(s, "%Y-%m-%d")
                    import datetime

                    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    try:
                        import datetime

                        return datetime.datetime.fromisoformat(s)
                    except Exception:
                        return None

            start_dt = _parse_dt(start)
            end_dt = _parse_dt(end)
            try:
                if end_dt and isinstance(end, str) and len(end) == 10:
                    import datetime

                    end_dt = end_dt.replace(hour=23, minute=59, second=59)
            except Exception:
                pass
            if not end_dt and end_now:
                try:
                    import datetime

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
                return {"kind": "empty", "message": "暂无数据"}
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
                    import calendar
                    import datetime

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

            if not xs:
                return {"kind": "empty", "message": "暂无数据"}
            ys = [m.get(x, 0.0) for x in xs]
            return {"kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs, "series": [{"name": series_name, "data": ys}], "meta": {"bar_x_kind": kind, "unit": unit, "step": step, "bar_y_kind": y_kind}}

        if kind == "rating":
            group_expr = "rating"
            extra.append("rating >= 1 AND rating <= 5")
            if y_kind == "new_species":
                extra.append("species_cls IS NOT NULL AND species_cls != ''")
            elif y_kind == "species_count":
                extra.append("species_cls IS NOT NULL AND species_cls != ''")
            all_where = []
            if where_expr:
                all_where.append(f"({where_expr})")
            if extra:
                all_where.append("(" + " AND ".join(extra) + ")")
            final_where = " AND ".join(all_where)
            final_params = list(params or []) + list(extra_params or [])
            rows = self._data.query_group_agg(table_name, group_expr, y_expr, final_where, final_params, order_by="x ASC", limit=10).rows or []
            m: Dict[str, float] = {}
            for r in rows:
                try:
                    k = str(int(r.get("x") or 0))
                except Exception:
                    continue
                m[k] = _safe_float(r.get("y"), 0.0)
            xs = ["1", "2", "3", "4", "5"]
            ys = [m.get(x, 0.0) for x in xs]
            return {"kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs, "series": [{"name": series_name, "data": ys}], "meta": {"bar_x_kind": kind, "bar_y_kind": y_kind}}

        if kind == "label":
            group_expr = "CASE WHEN label IS NULL OR label = '' THEN 'None' ELSE label END"
            if y_kind == "new_species":
                extra.append("species_cls IS NOT NULL AND species_cls != ''")
            elif y_kind == "species_count":
                extra.append("species_cls IS NOT NULL AND species_cls != ''")
            all_where = [f"({where_expr})"] if where_expr else []
            if extra:
                all_where.append("(" + " AND ".join(extra) + ")")
            final_where = " AND ".join(all_where)
            final_params = list(params or []) + list(extra_params or [])
            rows = self._data.query_group_agg(table_name, group_expr, y_expr, final_where, final_params, order_by="y DESC", limit=30).rows or []
            order = ["Green", "Blue", "Yellow", "Red", "Purple", "White", "Orange", "Pink", "Black", "None"]
            m: Dict[str, float] = {}
            for r in rows:
                k = str(r.get("x") or "").strip()
                if not k:
                    continue
                m[k] = _safe_float(r.get("y"), 0.0)
            xs = [x for x in order if x in m] + [k for k in m.keys() if k not in order]
            if not xs:
                return {"kind": "empty", "message": "暂无数据"}
            ys = [m.get(x, 0.0) for x in xs]
            return {"kind": "xy", "chart_type": str(chart_type or "bar"), "x": xs, "series": [{"name": series_name, "data": ys}], "meta": {"bar_x_kind": kind, "bar_y_kind": y_kind}}

        if kind == "location":
            return {"kind": "empty", "message": "地点统计暂未实现(仅提供 UI)"}

        return {"kind": "empty", "message": "暂无数据"}

    def _payload_pie(self, table_name: str, options: dict) -> dict:
        cat = str(options.get("category_field") or "")
        value_agg = str(options.get("value_agg") or "count")

        x_expr, where, params = self._group_expr_for_field(cat)
        where_sql = f" WHERE {where}" if where else ""
        y_sql = "COUNT(*)" if value_agg == "count" else ("AVG(score)" if value_agg == "mean" else "SUM(score)")
        sql = f"""
            SELECT {x_expr} AS x, {y_sql} AS y
            FROM {table_name}
            {where_sql}
            GROUP BY x
            ORDER BY y DESC
            LIMIT 50
        """
        rows = self._query(sql, params)
        if not rows:
            return {"kind": "empty", "message": "暂无数据"}
        items = [{"name": str(r.get("x") or ""), "value": _safe_float(r.get("y"), 0.0)} for r in rows if str(r.get("x") or "")]
        return {"kind": "pie", "items": items, "meta": {"value_agg": value_agg}}

    def _payload_scatter(self, table_name: str, options: dict) -> dict:
        x_field = str(options.get("x_field") or "")
        y_field = str(options.get("y_field") or "")
        size_field = str(options.get("size_field") or "")

        xf, xw, xp = self._value_expr_for_field(x_field)
        yf, yw, yp = self._value_expr_for_field(y_field)
        sf, sw, sp = self._value_expr_for_field(size_field) if size_field else ("NULL", "", [])
        wheres = [w for w in [xw, yw, sw] if w]
        params = list(xp or []) + list(yp or []) + list(sp or [])
        where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        sql = f"""
            SELECT {xf} AS x, {yf} AS y, {sf} AS s
            FROM {table_name}
            {where_sql}
            LIMIT 2000
        """
        rows = self._query(sql, params)
        if not rows:
            return {"kind": "empty", "message": "暂无数据"}
        pts = []
        for r in rows:
            x = _safe_float(r.get("x"), None)
            y = _safe_float(r.get("y"), None)
            if x is None or y is None:
                continue
            s = _safe_float(r.get("s"), 0.0)
            pts.append([x, y, s])
        return {"kind": "scatter", "points": pts}

    def _payload_taxonomy_tree(self, table_name: str) -> dict:
        if not self._data.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}
        stats = self._data.get_taxonomy_tree_stats(table_name=table_name)
        tree = stats.get("tree") or {}
        root = {"name": "分类", "children": []}
        for o, o_node in tree.items():
            o_item = {"name": o, "value": int(o_node.get("image_count") or 0), "children": []}
            for f, f_node in (o_node.get("children") or {}).items():
                f_item = {"name": f, "value": int(f_node.get("image_count") or 0), "children": []}
                for g, g_node in (f_node.get("children") or {}).items():
                    g_item = {"name": g, "value": int(g_node.get("image_count") or 0), "children": []}
                    for s, s_node in (g_node.get("children") or {}).items():
                        g_item["children"].append({"name": s, "value": int(s_node.get("image_count") or 0)})
                    f_item["children"].append(g_item)
                o_item["children"].append(f_item)
            root["children"].append(o_item)
        return {"kind": "tree", "data": root, "unclassified_image_count": int(stats.get("unclassified_image_count") or 0)}

    def _payload_taxonomy_graph(self, table_name: str) -> dict:
        if not self._data.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}
        stats = self._data.get_taxonomy_tree_stats(table_name=table_name)
        tree = stats.get("tree") or {}
        nodes = []
        links = []
        node_idx: Dict[str, int] = {}

        def add_node(name: str, category: str, value: int) -> None:
            key = f"{category}:{name}"
            if key in node_idx:
                return
            node_idx[key] = len(nodes)
            nodes.append({"id": key, "name": name, "category": category, "value": int(value)})

        def add_link(src: str, dst: str, value: int) -> None:
            links.append({"source": src, "target": dst, "value": int(value)})

        for o, o_node in tree.items():
            add_node(o, "order", int(o_node.get("image_count") or 0))
            for f, f_node in (o_node.get("children") or {}).items():
                add_node(f, "family", int(f_node.get("image_count") or 0))
                add_link(f"order:{o}", f"family:{f}", int(f_node.get("image_count") or 0))
                for g, g_node in (f_node.get("children") or {}).items():
                    add_node(g, "genus", int(g_node.get("image_count") or 0))
                    add_link(f"family:{f}", f"genus:{g}", int(g_node.get("image_count") or 0))
                    for s, s_node in (g_node.get("children") or {}).items():
                        add_node(s, "species", int(s_node.get("image_count") or 0))
                        add_link(f"genus:{g}", f"species:{s}", int(s_node.get("image_count") or 0))
        categories = [{"name": "order"}, {"name": "family"}, {"name": "genus"}, {"name": "species"}]
        return {"kind": "graph", "nodes": nodes, "links": links, "categories": categories}

    def _payload_geo_points(self, table_name: str) -> dict:
        sql = f"""
            SELECT latitude AS lat, longitude AS lng, COUNT(*) AS cnt
            FROM {table_name}
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND latitude != 0 AND longitude != 0
            GROUP BY ROUND(latitude, 3), ROUND(longitude, 3)
            ORDER BY cnt DESC
            LIMIT 2000
        """
        rows = self._query(sql, [])
        pts = [[_safe_float(r.get("lng"), 0.0), _safe_float(r.get("lat"), 0.0), _safe_int(r.get("cnt"), 0)] for r in rows]
        return {"kind": "geo_points", "points": pts}

    def _payload_gauge(self, table_name: str) -> dict:
        total = self._scalar(f"SELECT COUNT(*) AS c FROM {table_name}", [])
        species = self._scalar(
            f"SELECT COUNT(DISTINCT species_cls) AS c FROM {table_name} WHERE species_cls IS NOT NULL AND species_cls != ''",
            [],
        )
        fav = self._scalar(f"SELECT COUNT(*) AS c FROM {table_name} WHERE is_favorite = 1", [])
        return {
            "kind": "gauge",
            "metrics": [
                {"name": "图片总数", "value": int(total)},
                {"name": "物种数", "value": int(species)},
                {"name": "收藏数", "value": int(fav)},
            ],
        }

    def _payload_radar(self, table_name: str) -> dict:
        metrics = [
            ("评分均值", "AVG(score)"),
            ("ISO均值", "AVG(iso)"),
            ("光圈均值", "AVG(fnumber)"),
            ("收藏比例", "AVG(is_favorite)"),
            ("评分均值(星)", "AVG(rating)"),
        ]
        inds = []
        vals = []
        for name, expr in metrics:
            v = self._scalar(f"SELECT {expr} AS c FROM {table_name}", [])
            val = float(v or 0.0)
            if "比例" in name:
                val = val * 100.0
            inds.append({"name": name, "max": max(1.0, val * 1.2)})
            vals.append(val)
        return {"kind": "radar", "indicators": inds, "value": vals}

    def _payload_calendar(self, table_name: str) -> dict:
        sql = f"""
            SELECT substr(COALESCE(shot_time, created_at), 1, 10) AS d, COUNT(*) AS c
            FROM {table_name}
            WHERE COALESCE(shot_time, created_at) IS NOT NULL AND COALESCE(shot_time, created_at) != ''
            GROUP BY d
            ORDER BY d ASC
            LIMIT 5000
        """
        rows = self._query(sql, [])
        data = [[str(r.get("d") or ""), int(r.get("c") or 0)] for r in rows if str(r.get("d") or "")]
        return {"kind": "calendar", "data": data}

    def _payload_gallery(self, table_name: str) -> dict:
        sql = f"""
            SELECT file_path AS p, created_at AS t
            FROM {table_name}
            ORDER BY created_at DESC
            LIMIT 60
        """
        rows = self._query(sql, [])
        items = [{"path": str(r.get("p") or ""), "time": str(r.get("t") or "")} for r in rows if str(r.get("p") or "")]
        return {"kind": "gallery", "items": items}

    def _query(self, sql: str, params: list) -> List[dict]:
        return (self._data.query(sql, params).rows or []) if self._data is not None else []

    def _scalar(self, sql: str, params: list) -> Any:
        if self._data is None:
            return 0
        return self._data.scalar(sql, params)

    def _group_expr_for_field(self, field_id: str) -> Tuple[str, str, list]:
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
        if f in ("score", "iso", "fnumber", "rating"):
            return f, f"{f} IS NOT NULL", []
        if f in ("shutter", "focal_length", "camera_model", "lens_model", "location"):
            return f, f"{f} IS NOT NULL AND {f} != ''", []
        return f, f"{f} IS NOT NULL", []

    def _value_expr_for_field(self, field_id: str) -> Tuple[str, str, list]:
        f = str(field_id or "").strip()
        if not f:
            return "NULL", "", []
        if f in ("score", "iso", "fnumber", "rating", "latitude", "longitude"):
            return f, f"{f} IS NOT NULL", []
        if f == "shot_time":
            return "strftime('%s', shot_time)", "shot_time IS NOT NULL AND shot_time != ''", []
        if f == "created_at":
            return "strftime('%s', created_at)", "created_at IS NOT NULL AND created_at != ''", []
        if f == "shutter":
            return "CAST(replace(shutter,'/','.') AS REAL)", "shutter IS NOT NULL AND shutter != ''", []
        if f == "focal_length":
            return "CAST(replace(focal_length,'mm','') AS REAL)", "focal_length IS NOT NULL AND focal_length != ''", []
        if f == "species":
            return "NULL", "", []
        if f == "order":
            return "NULL", "", []
        if f == "family":
            return "NULL", "", []
        if f == "genus":
            return "NULL", "", []
        return "NULL", "", []
