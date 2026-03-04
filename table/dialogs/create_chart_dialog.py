from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from table.chart_types import CHART_TYPES
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.widgets.themed_combo_box import ThemedComboBox


# 允许选择的图表类型列表（不在此列表中的将被禁用）
ENABLED_CHART_TYPES = {"number", "bar", "line", "pie", "scatter", "tree"}


DATASET_OPTIONS = [
    ("library", "图片库数据"),
    ("import", "导入数据"),
    ("custom", "自定义数据集（占位）"),
]


FIELD_OPTIONS = [
    ("score", "评分"),
    ("iso", "ISO"),
    ("shutter", "快门"),
    ("fnumber", "光圈"),
    ("focal_length", "焦距"),
    ("shot_time", "拍摄时间"),
    ("created_at", "创建时间"),
    ("species", "物种"),
    ("order", "目"),
    ("family", "科"),
    ("genus", "属"),
]


AGG_OPTIONS = [
    ("count", "数量"),
    ("mean", "平均值"),
    ("sum", "求和"),
]


class CreateChartDialog(BasePopupDialog):
    def __init__(self, parent=None):
        super().__init__(parent=parent, title="添加图表", size=(860, 680))
        self._build_ui()
        try:
            ColorManager.instance().register_listener(self.apply_theme_styles)
        except Exception:
            pass
        self.apply_theme_styles()

    def _build_ui(self):
        header = QLabel("图表基础信息")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.content_layout.addWidget(header)

        base_form_wrap = QWidget()
        base_form = QFormLayout(base_form_wrap)
        base_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        base_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        base_form.setHorizontalSpacing(12)
        base_form.setVerticalSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("请输入图表名称")
        base_form.addRow("图表名称", self.name_edit)

        self.type_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        # 使用自定义模型来支持禁用特定选项
        type_model = QStandardItemModel()
        for opt in CHART_TYPES:
            item = QStandardItem(opt.title)
            item.setData(opt.chart_type, Qt.ItemDataRole.UserRole)
            # 如果图表类型不在允许列表中，则禁用该项
            if opt.chart_type not in ENABLED_CHART_TYPES:
                item.setEnabled(False)
                # 设置禁用项的样式（灰色显示）
                item.setForeground(Qt.GlobalColor.gray)
            type_model.appendRow(item)
        self.type_combo.setModel(type_model)
        base_form.addRow("图表类型", self.type_combo)

        self.dataset_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in DATASET_OPTIONS:
            self.dataset_combo.addItem(title, key)
        base_form.addRow("数据集", self.dataset_combo)

        self.content_layout.addWidget(base_form_wrap)

        sub_header = QLabel("图表配置")
        sub_header.setStyleSheet("font-size: 16px; font-weight: 600; margin-top: 6px;")
        self.content_layout.addWidget(sub_header)

        self.stack = QStackedWidget()
        self.page_xy = self._build_xy_page()
        self.page_pie = self._build_pie_page()
        self.page_scatter = self._build_scatter_page()
        self.page_geo = self._build_geo_page()
        self.page_hierarchy = self._build_hierarchy_page()
        self.page_graph = self._build_graph_page()
        self.page_gauge = self._build_gauge_page()
        self.page_radar = self._build_radar_page()
        self.page_calendar = self._build_calendar_page()
        self.page_gallery = self._build_gallery_page()
        self.page_placeholder = self._build_placeholder_page()

        self.stack.addWidget(self.page_xy)
        self.stack.addWidget(self.page_pie)
        self.stack.addWidget(self.page_scatter)
        self.stack.addWidget(self.page_geo)
        self.stack.addWidget(self.page_hierarchy)
        self.stack.addWidget(self.page_graph)
        self.stack.addWidget(self.page_gauge)
        self.stack.addWidget(self.page_radar)
        self.stack.addWidget(self.page_calendar)
        self.stack.addWidget(self.page_gallery)
        self.stack.addWidget(self.page_placeholder)
        self.content_layout.addWidget(self.stack, 1)

        self._type_to_page = self._build_type_to_page_map()
        self.type_combo.currentIndexChanged.connect(self._sync_type_page)
        self._sync_type_page()

        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确定")
        self.apply_dialog_button_style(cancel_btn, "secondary")
        self.apply_dialog_button_style(ok_btn, "primary")
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(ok_btn)

    def _build_type_to_page_map(self) -> dict[str, QWidget]:
        return {
            "bar": self.page_xy,
            "line": self.page_xy,
            "timelineLine": self.page_xy,
            "bar3D": self.page_xy,
            "pie": self.page_pie,
            "scatter": self.page_scatter,
            "map": self.page_geo,
            "geo": self.page_geo,
            "lines": self.page_geo,
            "geoGraph": self.page_geo,
            "globe3D": self.page_geo,
            "tree": self.page_hierarchy,
            "treemap": self.page_hierarchy,
            "sunburst": self.page_hierarchy,
            "graph": self.page_graph,
            "gauge": self.page_gauge,
            "customGauge": self.page_gauge,
            "radar": self.page_radar,
            "radarCustom": self.page_radar,
            "radarMulti": self.page_radar,
            "calendar": self.page_calendar,
            "calendarH": self.page_calendar,
            "scrollLegend": self.page_gallery,
            "timelineGallery": self.page_gallery,
        }

    def _build_xy_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.xy_x_field = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.xy_x_field.addItem(title, key)
        form.addRow("横坐标字段", self.xy_x_field)

        self.xy_y_agg = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in AGG_OPTIONS:
            self.xy_y_agg.addItem(title, key)
        form.addRow("纵坐标统计", self.xy_y_agg)

        self.xy_group_field = ThemedComboBox(font_size=12, padding="6px 10px")
        self.xy_group_field.addItem("不分组", "")
        for key, title in FIELD_OPTIONS:
            self.xy_group_field.addItem(title, key)
        form.addRow("分组字段", self.xy_group_field)

        self.xy_smooth = QCheckBox("平滑曲线（占位）")
        form.addRow("折线设置", self.xy_smooth)

        return wrap

    def _build_pie_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.pie_category_field = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.pie_category_field.addItem(title, key)
        form.addRow("分类字段", self.pie_category_field)

        self.pie_value_agg = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in AGG_OPTIONS:
            self.pie_value_agg.addItem(title, key)
        form.addRow("数值统计", self.pie_value_agg)

        return wrap

    def _build_scatter_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.scatter_x_field = ThemedComboBox(font_size=12, padding="6px 10px")
        self.scatter_y_field = ThemedComboBox(font_size=12, padding="6px 10px")
        self.scatter_size_field = ThemedComboBox(font_size=12, padding="6px 10px")

        for key, title in FIELD_OPTIONS:
            self.scatter_x_field.addItem(title, key)
            self.scatter_y_field.addItem(title, key)
            self.scatter_size_field.addItem(title, key)

        form.addRow("X字段", self.scatter_x_field)
        form.addRow("Y字段", self.scatter_y_field)
        form.addRow("大小字段", self.scatter_size_field)

        return wrap

    def _build_geo_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.geo_base = ThemedComboBox(font_size=12, padding="6px 10px")
        self.geo_base.addItem("中国（省市）", "china")
        self.geo_base.addItem("世界（占位）", "world")
        self.geo_base.addItem("北京（占位）", "beijing")
        self.geo_base.addItem("自定义GeoJSON（占位）", "custom")
        form.addRow("地理底图", self.geo_base)

        self.geo_value_agg = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in AGG_OPTIONS:
            self.geo_value_agg.addItem(title, key)
        form.addRow("数值统计", self.geo_value_agg)

        self.geo_region_field = ThemedComboBox(font_size=12, padding="6px 10px")
        self.geo_region_field.addItem("地区字段（占位）", "region")
        self.geo_region_field.setEnabled(False)
        form.addRow("地区字段", self.geo_region_field)

        self.geo_effect = QCheckBox("启用特效（涟漪/飞线等，占位）")
        form.addRow("显示效果", self.geo_effect)

        return wrap

    def _build_hierarchy_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.h_level_1 = ThemedComboBox(font_size=12, padding="6px 10px")
        self.h_level_2 = ThemedComboBox(font_size=12, padding="6px 10px")
        self.h_level_3 = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.h_level_1.addItem(title, key)
            self.h_level_2.addItem(title, key)
            self.h_level_3.addItem(title, key)
        form.addRow("第一层字段", self.h_level_1)
        form.addRow("第二层字段", self.h_level_2)
        form.addRow("第三层字段", self.h_level_3)

        self.h_value_agg = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in AGG_OPTIONS:
            self.h_value_agg.addItem(title, key)
        form.addRow("数值统计", self.h_value_agg)

        return wrap

    def _build_graph_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.graph_node_field = ThemedComboBox(font_size=12, padding="6px 10px")
        self.graph_group_field = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.graph_node_field.addItem(title, key)
            self.graph_group_field.addItem(title, key)
        form.addRow("节点字段", self.graph_node_field)
        form.addRow("分组字段", self.graph_group_field)

        self.graph_link_strength = QSpinBox()
        self.graph_link_strength.setRange(1, 1000)
        self.graph_link_strength.setValue(200)
        form.addRow("连线强度（占位）", self.graph_link_strength)

        return wrap

    def _build_gauge_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.gauge_value_field = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.gauge_value_field.addItem(title, key)
        form.addRow("数值字段", self.gauge_value_field)

        self.gauge_max = QSpinBox()
        self.gauge_max.setRange(1, 100000)
        self.gauge_max.setValue(100)
        form.addRow("最大值（占位）", self.gauge_max)

        self.gauge_multi = QCheckBox("多指标面板（占位）")
        form.addRow("模式", self.gauge_multi)

        return wrap

    def _build_radar_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.radar_dim_1 = ThemedComboBox(font_size=12, padding="6px 10px")
        self.radar_dim_2 = ThemedComboBox(font_size=12, padding="6px 10px")
        self.radar_dim_3 = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.radar_dim_1.addItem(title, key)
            self.radar_dim_2.addItem(title, key)
            self.radar_dim_3.addItem(title, key)
        form.addRow("维度1字段", self.radar_dim_1)
        form.addRow("维度2字段", self.radar_dim_2)
        form.addRow("维度3字段", self.radar_dim_3)

        self.radar_value_agg = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in AGG_OPTIONS:
            self.radar_value_agg.addItem(title, key)
        form.addRow("数值统计", self.radar_value_agg)

        return wrap

    def _build_calendar_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.calendar_date_field = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.calendar_date_field.addItem(title, key)
        form.addRow("日期字段", self.calendar_date_field)

        self.calendar_value_agg = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in AGG_OPTIONS:
            self.calendar_value_agg.addItem(title, key)
        form.addRow("数值统计", self.calendar_value_agg)

        return wrap

    def _build_gallery_page(self) -> QWidget:
        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.gallery_category_field = ThemedComboBox(font_size=12, padding="6px 10px")
        self.gallery_value_agg = ThemedComboBox(font_size=12, padding="6px 10px")
        for key, title in FIELD_OPTIONS:
            self.gallery_category_field.addItem(title, key)
        for key, title in AGG_OPTIONS:
            self.gallery_value_agg.addItem(title, key)
        form.addRow("分类字段", self.gallery_category_field)
        form.addRow("数值统计", self.gallery_value_agg)

        self.gallery_max_items = QSpinBox()
        self.gallery_max_items.setRange(10, 500)
        self.gallery_max_items.setValue(50)
        form.addRow("最大条目（占位）", self.gallery_max_items)

        return wrap

    def _build_placeholder_page(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder_label = QLabel("该图表类型的配置 UI 暂未细化")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.placeholder_label, 1)
        return wrap

    def _sync_type_page(self):
        t = str(self.type_combo.currentData() or "")
        page = self._type_to_page.get(t)
        if page is None:
            try:
                self.placeholder_label.setText("该图表类型的配置 UI 暂未细化")
            except Exception:
                pass
            self.stack.setCurrentWidget(self.page_placeholder)
            return
        self.stack.setCurrentWidget(page)

    def apply_theme_styles(self):
        cm = ColorManager.instance()

        content_bg = cm.get("theme.background.light", "#FFFFFF")
        footer_bg = cm.get("theme.background.dark", "#E7E7E7")
        border = cm.get("popup.border.primary", "#D0D0D0")
        header_bg = cm.get("popup.header.background", "#2c3e50")
        header_text = cm.get("popup.header.text", "#FFFFFF")
        close_hover_bg = cm.get("popup.header.close_button.hover_background", "#FFFFFF1A")

        self.set_title_bar_style(header_bg, header_text, hover_background=close_hover_bg)
        self.set_bottom_bar_style(footer_bg, border_color=border)

        try:
            if self.container:
                self.container.setStyleSheet(f"""
                    QWidget#container {{
                        background-color: {content_bg};
                        border: 1px solid {border};
                        border-radius: 8px;
                    }}
                """)
        except Exception:
            pass

        try:
            if self.content_widget:
                self.content_widget.setStyleSheet(f"""
                    QWidget#contentWidget {{
                        background-color: {content_bg};
                    }}
                    QWidget#contentWidget QLabel {{
                        background: transparent;
                    }}
                """)
        except Exception:
            pass

        text = cm.get("popup.text.primary", "#333333")
        input_bg = cm.get("settings.shortcut_input.background", content_bg)
        primary = cm.get("theme.primary", "#2196F3")

        try:
            self.name_edit.setStyleSheet(f"""
                QLineEdit {{
                    padding: 6px 10px;
                    border: 1px solid {border};
                    border-radius: 4px;
                    font-size: 12px;
                    background-color: {input_bg};
                    color: {text};
                }}
                QLineEdit:focus {{
                    border: 1px solid {primary};
                }}
            """)
        except Exception:
            pass

    def get_config(self) -> dict:
        chart_type = str(self.type_combo.currentData() or "")
        dataset = str(self.dataset_combo.currentData() or "")
        name = (self.name_edit.text() or "").strip() or "未命名图表"

        cfg = {
            "name": name,
            "type": chart_type,
            "dataset": dataset,
            "options": {},
        }

        if chart_type in ("bar", "line", "timelineLine", "bar3D"):
            cfg["options"] = {
                "x_field": str(self.xy_x_field.currentData() or ""),
                "y_agg": str(self.xy_y_agg.currentData() or ""),
                "group_field": str(self.xy_group_field.currentData() or ""),
                "smooth": bool(self.xy_smooth.isChecked()),
            }
            return cfg

        if chart_type == "pie":
            cfg["options"] = {
                "category_field": str(self.pie_category_field.currentData() or ""),
                "value_agg": str(self.pie_value_agg.currentData() or ""),
            }
            return cfg

        if chart_type == "scatter":
            cfg["options"] = {
                "x_field": str(self.scatter_x_field.currentData() or ""),
                "y_field": str(self.scatter_y_field.currentData() or ""),
                "size_field": str(self.scatter_size_field.currentData() or ""),
            }
            return cfg

        if chart_type in ("map", "geo", "lines", "geoGraph", "globe3D"):
            cfg["options"] = {
                "base": str(self.geo_base.currentData() or ""),
                "value_agg": str(self.geo_value_agg.currentData() or ""),
                "effect": bool(self.geo_effect.isChecked()),
            }
            return cfg

        if chart_type in ("tree", "treemap", "sunburst"):
            cfg["options"] = {
                "level_1": str(self.h_level_1.currentData() or ""),
                "level_2": str(self.h_level_2.currentData() or ""),
                "level_3": str(self.h_level_3.currentData() or ""),
                "value_agg": str(self.h_value_agg.currentData() or ""),
            }
            return cfg

        if chart_type == "graph":
            cfg["options"] = {
                "node_field": str(self.graph_node_field.currentData() or ""),
                "group_field": str(self.graph_group_field.currentData() or ""),
                "link_strength": int(self.graph_link_strength.value()),
            }
            return cfg

        if chart_type in ("gauge", "customGauge"):
            cfg["options"] = {
                "value_field": str(self.gauge_value_field.currentData() or ""),
                "max_value": int(self.gauge_max.value()),
                "multi": bool(self.gauge_multi.isChecked()),
            }
            return cfg

        if chart_type in ("radar", "radarCustom", "radarMulti"):
            cfg["options"] = {
                "dim_1": str(self.radar_dim_1.currentData() or ""),
                "dim_2": str(self.radar_dim_2.currentData() or ""),
                "dim_3": str(self.radar_dim_3.currentData() or ""),
                "value_agg": str(self.radar_value_agg.currentData() or ""),
            }
            return cfg

        if chart_type in ("calendar", "calendarH"):
            cfg["options"] = {
                "date_field": str(self.calendar_date_field.currentData() or ""),
                "value_agg": str(self.calendar_value_agg.currentData() or ""),
            }
            return cfg

        if chart_type in ("scrollLegend", "timelineGallery"):
            cfg["options"] = {
                "category_field": str(self.gallery_category_field.currentData() or ""),
                "value_agg": str(self.gallery_value_agg.currentData() or ""),
                "max_items": int(self.gallery_max_items.value()),
            }
            return cfg

        return cfg
