from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtWidgets import QWidget

from table.charts.chart_controller import ChartController
from table.charts.simple_placeholder_controller import SimplePlaceholderChartController
from table.charts.types.bar.builder import create_controller as create_bar
from table.charts.types.bar3D.builder import create_controller as create_bar3d
from table.charts.types.calendar.builder import create_controller as create_calendar
from table.charts.types.calendarH.builder import create_controller as create_calendar_h
from table.charts.types.customGauge.builder import create_controller as create_custom_gauge
from table.charts.types.gauge.builder import create_controller as create_gauge
from table.charts.types.geo.builder import create_controller as create_geo
from table.charts.types.geoGraph.builder import create_controller as create_geo_graph
from table.charts.types.globe3D.builder import create_controller as create_globe3d
from table.charts.types.graph.builder import create_controller as create_graph
from table.charts.types.line.builder import create_controller as create_line
from table.charts.types.lines.builder import create_controller as create_lines
from table.charts.types.map.builder import create_controller as create_map
from table.charts.types.pie.builder import create_controller as create_pie
from table.charts.types.radar.builder import create_controller as create_radar
from table.charts.types.radarCustom.builder import create_controller as create_radar_custom
from table.charts.types.radarMulti.builder import create_controller as create_radar_multi
from table.charts.types.scatter.builder import create_controller as create_scatter
from table.charts.types.scrollLegend.builder import create_controller as create_scroll_legend
from table.charts.types.sunburst.builder import create_controller as create_sunburst
from table.charts.types.timelineGallery.builder import create_controller as create_timeline_gallery
from table.charts.types.timelineLine.builder import create_controller as create_timeline_line
from table.charts.types.tree.builder import create_controller as create_tree
from table.charts.types.treemap.builder import create_controller as create_treemap


CreateControllerFunc = Callable[[QWidget, dict], ChartController]


@dataclass
class ManagedChart:
    chart_id: str
    config: dict
    controller: ChartController


class ChartManager:
    def __init__(self):
        self._registry: Dict[str, CreateControllerFunc] = {}
        self._charts: Dict[str, ManagedChart] = {}
        self._theme: Optional[str] = None
        self._display_options: Dict[str, Any] = {}
        self._gpu_rendering_enabled: bool = False
        self._register_builtin()

    def _register_builtin(self):
        self.register_chart_type("bar", create_bar)
        self.register_chart_type("bar3D", create_bar3d)
        self.register_chart_type("calendar", create_calendar)
        self.register_chart_type("calendarH", create_calendar_h)
        self.register_chart_type("customGauge", create_custom_gauge)
        self.register_chart_type("gauge", create_gauge)
        self.register_chart_type("geo", create_geo)
        self.register_chart_type("geoGraph", create_geo_graph)
        self.register_chart_type("globe3D", create_globe3d)
        self.register_chart_type("graph", create_graph)
        self.register_chart_type("line", create_line)
        self.register_chart_type("lines", create_lines)
        self.register_chart_type("pie", create_pie)
        self.register_chart_type("radar", create_radar)
        self.register_chart_type("radarCustom", create_radar_custom)
        self.register_chart_type("radarMulti", create_radar_multi)
        self.register_chart_type("scatter", create_scatter)
        self.register_chart_type("scrollLegend", create_scroll_legend)
        self.register_chart_type("sunburst", create_sunburst)
        self.register_chart_type("timelineGallery", create_timeline_gallery)
        self.register_chart_type("timelineLine", create_timeline_line)
        self.register_chart_type("tree", create_tree)
        self.register_chart_type("treemap", create_treemap)
        self.register_chart_type("map", create_map)

    def register_chart_type(self, chart_type: str, factory: CreateControllerFunc) -> None:
        ct = str(chart_type or "").strip()
        if not ct:
            return
        self._registry[ct] = factory

    def create_chart(self, parent: QWidget, config: dict) -> ManagedChart:
        cfg = dict(config or {})
        chart_type = str(cfg.get("type") or "").strip()
        if not chart_type:
            chart_type = "bar"
            cfg["type"] = chart_type
        factory = self._registry.get(chart_type)
        if factory is None:
            controller = SimplePlaceholderChartController(parent, chart_type or "未知图表", cfg)
        else:
            controller = factory(parent, cfg)
        controller.set_theme(self._theme)
        controller.set_display_options(self._display_options)
        chart_id = uuid.uuid4().hex
        managed = ManagedChart(chart_id=chart_id, config=cfg, controller=controller)
        self._charts[chart_id] = managed
        return managed

    def remove_chart(self, chart_id: str) -> None:
        cid = str(chart_id or "")
        if not cid:
            return
        self._charts.pop(cid, None)

    def list_charts(self) -> List[ManagedChart]:
        return list(self._charts.values())

    def get_chart(self, chart_id: str) -> Optional[ManagedChart]:
        cid = str(chart_id or "")
        if not cid:
            return None
        return self._charts.get(cid)

    def set_theme(self, theme: Optional[str]) -> None:
        self._theme = theme
        for c in self._charts.values():
            try:
                c.controller.set_theme(theme)
            except Exception:
                pass

    def set_display_options(self, options: Dict[str, Any]) -> None:
        self._display_options = dict(options or {})
        for c in self._charts.values():
            try:
                c.controller.set_display_options(self._display_options)
            except Exception:
                pass

    def set_data_for_chart(self, chart_id: str, data: Any) -> None:
        c = self.get_chart(chart_id)
        if c is None:
            return
        try:
            c.controller.set_data(data)
        except Exception:
            pass

    def refresh(self, chart_id: Optional[str] = None) -> None:
        if chart_id:
            c = self.get_chart(chart_id)
            if c is None:
                return
            try:
                c.controller.refresh()
            except Exception:
                pass
            return
        for c in self._charts.values():
            try:
                c.controller.refresh()
            except Exception:
                pass

    def set_gpu_rendering_enabled(self, enabled: bool) -> None:
        self._gpu_rendering_enabled = bool(enabled)

    def is_gpu_rendering_enabled(self) -> bool:
        return bool(self._gpu_rendering_enabled)

    def get_theme(self) -> Optional[str]:
        return self._theme

    def get_display_options(self) -> Dict[str, Any]:
        return dict(self._display_options or {})
