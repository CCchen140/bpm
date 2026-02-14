from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.log_manager import LogManager
from utils.sql.data_base import BirdLibraryDB


@dataclass(frozen=True)
class QueryResult:
    rows: List[dict]


class ChartsDataService:
    def __init__(self, db: Optional[BirdLibraryDB]):
        self._db = db

    def is_ready(self) -> bool:
        return self._db is not None

    def query(self, sql: str, params: list) -> QueryResult:
        if self._db is None:
            return QueryResult(rows=[])
        try:
            conn = self._db._get_connection()
        except Exception:
            return QueryResult(rows=[])
        try:
            cur = conn.cursor()
            cur.execute(sql, tuple(params or []))
            rows = cur.fetchall() or []
            out: List[dict] = []
            for r in rows:
                try:
                    out.append(dict(r))
                except Exception:
                    try:
                        out.append({k: r[k] for k in r.keys()})
                    except Exception:
                        pass
            return QueryResult(rows=out)
        except Exception as e:
            try:
                LogManager.instance().warning(f"SQL执行失败: {e}")
            except Exception:
                pass
            return QueryResult(rows=[])
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def scalar(self, sql: str, params: list) -> Any:
        res = self.query(sql, params)
        if not res.rows:
            return 0
        r0 = res.rows[0]
        for v in r0.values():
            return v
        return 0

    def get_taxonomy_tree_stats(self, table_name: str) -> dict:
        if self._db is None:
            return {"tree": {}, "unclassified_image_count": 0}
        try:
            return self._db.get_taxonomy_tree_stats(table_name=table_name)
        except Exception:
            return {"tree": {}, "unclassified_image_count": 0}

    def update_user_field_batch(self, table_name: str, field_name: str, field_value: Any, file_items: list) -> None:
        if self._db is None:
            return
        try:
            self._db.update_user_field_batch_for_table(file_items, field_name, field_value, table_name=table_name)
        except Exception:
            return

    def build_where_from_conditions(self, conditions: list, exclude_fields: Optional[set] = None) -> tuple[str, list]:
        exclude = set(exclude_fields or set())
        conds = conditions if isinstance(conditions, list) else []
        expr = ""
        params: list = []

        def _normalize_time_range(v: str) -> tuple[str, str]:
            raw = str(v or "")
            parts = raw.split("||")
            if len(parts) != 2:
                return "", ""
            start = parts[0].strip()
            end = parts[1].strip()
            if start and len(start) == 10:
                start = start + " 00:00:00"
            if end and len(end) == 10:
                end = end + " 23:59:59"
            return start, end

        def _cond_sql(c: dict) -> tuple[str, list]:
            field = str((c or {}).get("field") or "").strip()
            if not field or field in exclude:
                return "", []
            op = str((c or {}).get("operator") or "").strip()
            value = (c or {}).get("value")
            fuzzy = bool((c or {}).get("fuzzy", False))

            if field == "文件名":
                if not str(value or "").strip():
                    return "", []
                if fuzzy:
                    return "file_name LIKE ?", ["%" + str(value) + "%"]
                return "file_name LIKE ?", [str(value)]
            if field == "路径":
                if not str(value or "").strip():
                    return "", []
                if fuzzy:
                    return "file_path LIKE ?", ["%" + str(value) + "%"]
                return "file_path LIKE ?", [str(value)]
            if field == "标签":
                if not str(value or "").strip():
                    return "", []
                return "tags LIKE ?", ["%" + str(value) + "%"]
            if field == "备注":
                if not str(value or "").strip():
                    return "", []
                if fuzzy:
                    return "description LIKE ?", ["%" + str(value) + "%"]
                return "description LIKE ?", [str(value)]
            if field == "拍摄地址":
                if not str(value or "").strip():
                    return "", []
                if fuzzy:
                    return "location LIKE ?", ["%" + str(value) + "%"]
                return "location LIKE ?", [str(value)]
            if field == "色标":
                v = str(value or "").strip()
                if not v:
                    return "", []
                if v.lower() == "none":
                    return "(label IS NULL OR label = '')", []
                return "label = ?", [v]
            if field in ("评分", "评星", "分数"):
                if field == "评分":
                    col = "rating"
                    try:
                        iv = int(value)
                    except Exception:
                        return "", []
                elif field == "评星":
                    col = "rating"
                    try:
                        iv = int(value)
                    except Exception:
                        return "", []
                else:
                    col = "score"
                    try:
                        iv = float(value)
                    except Exception:
                        return "", []
                if op not in ("=", ">=", "<="):
                    op = "="
                return f"{col} {op} ?", [iv]
            if field == "拍摄时间":
                start, end = _normalize_time_range(str(value or ""))
                if not start or not end:
                    return "", []
                return "(shot_time IS NOT NULL AND shot_time != '' AND shot_time >= ? AND shot_time <= ?)", [start, end]
            if field == "鸟的位置":
                v = str(value or "").strip()
                if not v:
                    return "", []
                return "position = ?", [v]
            if field == "目":
                v = str(value or "").strip()
                if not v:
                    return "", []
                if fuzzy:
                    return "order_cls LIKE ?", ["%" + v + "%"]
                return "order_cls LIKE ?", [v]
            if field == "科":
                v = str(value or "").strip()
                if not v:
                    return "", []
                if fuzzy:
                    return "family_cls LIKE ?", ["%" + v + "%"]
                return "family_cls LIKE ?", [v]
            if field == "属":
                v = str(value or "").strip()
                if not v:
                    return "", []
                if fuzzy:
                    return "genus_cls LIKE ?", ["%" + v + "%"]
                return "genus_cls LIKE ?", [v]
            if field == "种":
                v = str(value or "").strip()
                if not v:
                    return "", []
                if fuzzy:
                    return "species_cls LIKE ?", ["%" + v + "%"]
                return "species_cls LIKE ?", [v]

            return "", []

        for idx, c in enumerate(conds):
            sql_part, p = _cond_sql(c if isinstance(c, dict) else {})
            if not sql_part:
                continue
            logic = "AND"
            try:
                logic = str((c or {}).get("logic") or "AND").upper()
            except Exception:
                logic = "AND"
            if idx == 0:
                logic = "AND"
            if not expr:
                expr = f"({sql_part})"
                params.extend(p)
                continue
            if logic == "OR":
                expr = f"({expr}) OR ({sql_part})"
                params.extend(p)
                continue
            if logic == "NOT":
                expr = f"({expr}) AND NOT ({sql_part})"
                params.extend(p)
                continue
            expr = f"({expr}) AND ({sql_part})"
            params.extend(p)

        return expr, params

    def query_group_count(self, table_name: str, group_expr: str, where_expr: str, params: list, order_by: str, limit: int = 2000) -> QueryResult:
        return self.query_group_agg(
            table_name=table_name,
            group_expr=group_expr,
            y_expr="COUNT(*)",
            where_expr=where_expr,
            params=params,
            order_by=order_by,
            limit=limit,
        )

    def query_group_agg(
        self,
        table_name: str,
        group_expr: str,
        y_expr: str,
        where_expr: str,
        params: list,
        order_by: str,
        limit: int = 2000,
    ) -> QueryResult:
        if self._db is None:
            return QueryResult(rows=[])
        t = str(table_name or "")
        if t not in ("bird_results", "import_cache"):
            return QueryResult(rows=[])
        ge = str(group_expr or "").strip()
        ye = str(y_expr or "").strip()
        if not ge or not ye:
            return QueryResult(rows=[])
        where_sql = f" WHERE {where_expr}" if str(where_expr or "").strip() else ""
        ob = str(order_by or "").strip() or "x ASC"
        try:
            lim = int(limit)
        except Exception:
            lim = 2000
        sql = f"""
            SELECT {ge} AS x, {ye} AS y
            FROM {t}
            {where_sql}
            GROUP BY x
            ORDER BY {ob}
            LIMIT {lim}
        """
        return self.query(sql, params or [])
