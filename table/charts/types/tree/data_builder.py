from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


@register_chart("tree")
class TreeDataBuilder(ChartDataBuilder):
    """
    树形图数据构建器

    用于构建分类树形结构数据，展示目、科、属、种的层级关系
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "tree") -> dict:
        """
        构建树形图数据载荷
        """
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        # 获取配置选项
        levels = options.get("tree_levels") or ["order", "family", "genus", "species"]
        show_count = bool(options.get("tree_show_count", True))
        layout = str(options.get("tree_layout") or "LR")
        time_type = str(options.get("tree_time_type") or "all")
        time_start = str(options.get("tree_time_start") or "")
        time_end = str(options.get("tree_time_end") or "")
        filters = options.get("tree_filters") or []

        # 构建时间筛选条件
        time_where = ""
        time_params = []
        if time_type != "all" and time_start:
            if time_end:
                time_where = "shot_time >= ? AND shot_time <= ?"
                time_params = [time_start, time_end]
            else:
                time_where = "shot_time >= ?"
                time_params = [time_start]

        # 构建筛选条件
        filter_where, filter_params = self._db.build_where_from_conditions(filters, exclude_fields={"拍摄时间"})
        
        # 合并筛选条件
        wheres = [w for w in [time_where, filter_where] if w]
        params = time_params + list(filter_params or [])
        where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

        # 数据库列名映射
        db_columns = {
            "order": "order_cls",
            "family": "family_cls",
            "genus": "genus_cls",
            "species": "species_cls"
        }

        # 构建SQL查询
        level_fields = []
        for level in levels:
            if level in db_columns:
                level_fields.append(db_columns[level])

        if not level_fields:
            level_fields = ["order_cls", "family_cls", "genus_cls", "species_cls"]

        # 构建HAVING子句
        having_clauses = []
        if "order" in levels:
            having_clauses.append("order_cls IS NOT NULL AND order_cls != ''")
        
        # 查询数据
        sql = f"""
            SELECT {', '.join(level_fields)}, COUNT(*) as cnt
            FROM {table_name}
            {where_sql}
            GROUP BY {', '.join(level_fields)}
            {"HAVING " + " AND ".join(having_clauses) if having_clauses else ""}
        """
        result = self._db.query(sql, params)
        rows = result.rows or []

        if not rows:
            return {"kind": "empty", "message": "暂无数据"}

        # 构建树形结构
        root = {"name": "鸟种", "children": []}
        
        # 使用字典来构建层级结构
        tree_dict = {}
        for row in rows:
            order = row.get("order_cls") or ""
            family = row.get("family_cls") or ""
            genus = row.get("genus_cls") or ""
            species = row.get("species_cls") or ""
            cnt = int(row.get("cnt") or 0)

            if not order:
                continue

            # 目层级
            if order not in tree_dict:
                tree_dict[order] = {"_count": 0, "_children": {}}
            tree_dict[order]["_count"] += cnt

            # 科层级
            if "family" in levels and family:
                if family not in tree_dict[order]["_children"]:
                    tree_dict[order]["_children"][family] = {"_count": 0, "_children": {}}
                tree_dict[order]["_children"][family]["_count"] += cnt

                # 属层级
                if "genus" in levels and genus:
                    if genus not in tree_dict[order]["_children"][family]["_children"]:
                        tree_dict[order]["_children"][family]["_children"][genus] = {"_count": 0, "_children": {}}
                    tree_dict[order]["_children"][family]["_children"][genus]["_count"] += cnt

                    # 种层级
                    if "species" in levels and species:
                        if species not in tree_dict[order]["_children"][family]["_children"][genus]["_children"]:
                            tree_dict[order]["_children"][family]["_children"][genus]["_children"][species] = {"_count": 0}
                        tree_dict[order]["_children"][family]["_children"][genus]["_children"][species]["_count"] += cnt

        # 转换为树形结构
        def build_node(name, data, level_idx):
            node = {"name": name}
            if show_count:
                node["value"] = data["_count"]
            
            children = data.get("_children", {})
            if children and level_idx < len(levels):
                node["children"] = []
                for child_name, child_data in sorted(children.items(), key=lambda x: -x[1]["_count"]):
                    node["children"].append(build_node(child_name, child_data, level_idx + 1))
            
            return node

        for order_name, order_data in sorted(tree_dict.items(), key=lambda x: -x[1]["_count"]):
            root["children"].append(build_node(order_name, order_data, 1))

        return {
            "kind": "tree",
            "data": root,
            "layout": layout,
            "show_count": show_count
        }
