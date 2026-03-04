from typing import Any, Dict, List, Optional

from table.charts.types.chart_data_builder import ChartDataBuilder
from table.charts.types.chart_registry import register_chart


@register_chart("graph")
class GraphDataBuilder(ChartDataBuilder):
    """
    关系图数据构建器

    用于构建分类关系图数据，展示目、科、属、种之间的关联关系
    """

    def build_payload(self, table_name: str, options: dict, chart_type: str = "graph") -> dict:
        """
        构建关系图数据载荷

        参数:
            table_name: 数据库表名
            options: 图表配置选项
            chart_type: 图表类型标识

        返回:
            包含关系图数据的字典
        """
        # 检查数据库是否可用
        if not self._db or not hasattr(self._db, 'is_ready') or not self._db.is_ready():
            return {"kind": "empty", "message": "数据库不可用"}

        # 获取分类树统计信息
        stats = self._db.get_taxonomy_tree_stats(table_name=table_name)
        tree = stats.get("tree") or {}

        nodes = []
        links = []
        node_idx: Dict[str, int] = {}

        def add_node(name: str, category: str, value: int) -> None:
            """添加节点到图中"""
            key = f"{category}:{name}"
            if key in node_idx:
                return
            node_idx[key] = len(nodes)
            nodes.append({"id": key, "name": name, "category": category, "value": int(value)})

        def add_link(src: str, dst: str, value: int) -> None:
            """添加连接到图中"""
            links.append({"source": src, "target": dst, "value": int(value)})

        # 遍历分类树构建节点和连接
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
