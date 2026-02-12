import json
import os
import uuid

import qtawesome as qta
from PyQt6.QtCore import QPoint, QPointF, QRect, QThreadPool, QRunnable, QTimer, Qt, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    QWebEngineView = None
    QWebChannel = None
except Exception:
    QWebEngineView = None
    QWebChannel = None

from ui.utils.color_manager import ColorManager
from ui.widgets.advanced_filter_panel import AdvancedFilterPanel
from utils.sql.data_base import BirdLibraryDB


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _charts_store_path() -> str:
    return os.path.join(_project_root(), "data", "cache", "charts_layout.json")


def _ensure_dir(p: str) -> None:
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
    except Exception:
        pass


def _safe_int(v, default=0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


class ChartBridge(QObject):
    def __init__(self, get_payload_func):
        super().__init__()
        self._get_payload_func = get_payload_func

    @pyqtSlot(result=str)
    def getPayload(self) -> str:
        try:
            payload = self._get_payload_func()
        except Exception:
            payload = {}
        try:
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return "{}"


class CreateChartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建图表")
        self.setModal(True)
        self.setMinimumSize(760, 640)

        cm = ColorManager.instance()
        bg = cm.get("theme.background.light")
        text = cm.get("theme.text.dark")
        self.setStyleSheet(f"background-color: {bg}; color: {text};")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("表格名")
        form.addRow("表格名", self.name_edit)

        self.chart_type = QComboBox()
        self.chart_type.addItems(["直方图", "折线图", "树形图"])
        form.addRow("图表类型", self.chart_type)

        self.data_type = QComboBox()
        self.data_type.addItems(["评分(score)", "ISO(iso)", "快门(shutter)", "光圈(fnumber)", "焦距(focal_length)", "拍摄时间(shot_time)", "创建时间(created_at)", "物种(species_cls)"])
        form.addRow("数据类型", self.data_type)

        self.x_axis = QComboBox()
        self.x_axis.addItems(["评分(score)", "ISO(iso)", "快门(shutter)", "光圈(fnumber)", "焦距(focal_length)", "拍摄时间(shot_time)", "创建时间(created_at)"])
        form.addRow("横坐标", self.x_axis)

        self.y_axis = QComboBox()
        self.y_axis.addItems(["数量(count)", "平均值(mean)"])
        form.addRow("纵坐标", self.y_axis)

        self.title_font_size = QSpinBox()
        self.title_font_size.setRange(8, 48)
        self.title_font_size.setValue(14)
        form.addRow("标题字号", self.title_font_size)

        self.title_color = QComboBox()
        self.title_color.addItems(["主题文字色", "主题主色", "白", "黑"])
        form.addRow("标题颜色", self.title_color)

        self.text_font_size = QSpinBox()
        self.text_font_size.setRange(8, 48)
        self.text_font_size.setValue(11)
        form.addRow("文字字号", self.text_font_size)

        self.text_color = QComboBox()
        self.text_color.addItems(["主题文字色", "主题主色", "白", "黑"])
        form.addRow("文字颜色", self.text_color)

        self.title_shadow = QComboBox()
        self.title_shadow.addItems(["无阴影", "有阴影"])
        form.addRow("标题阴影", self.title_shadow)

        self.text_shadow = QComboBox()
        self.text_shadow.addItems(["无阴影", "有阴影"])
        form.addRow("文字阴影", self.text_shadow)

        root.addLayout(form)

        self.filter_panel = AdvancedFilterPanel()
        root.addWidget(self.filter_panel, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("取消")
        ok = QPushButton("创建")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)

        self.chart_type.currentIndexChanged.connect(self._sync_fields)
        self.data_type.currentIndexChanged.connect(self._sync_fields)
        self._sync_fields()

    def _sync_fields(self):
        t = self.chart_type.currentText()
        data = self.data_type.currentText()
        is_tree = (t == "树形图")
        self.x_axis.setEnabled(not is_tree and ("直方图" != t))
        self.y_axis.setEnabled(not is_tree)
        if is_tree:
            idx = self.data_type.findText("物种(species_cls)")
            if idx >= 0:
                self.data_type.setCurrentIndex(idx)
            self.data_type.setEnabled(False)
        else:
            self.data_type.setEnabled(True)
        if t == "直方图":
            self.x_axis.setEnabled(True)
            self.y_axis.setEnabled(False)

    def get_config(self) -> dict:
        t = self.chart_type.currentText()
        cfg = {
            "name": (self.name_edit.text() or "").strip() or "未命名图表",
            "type": t,
            "data_type": self.data_type.currentText(),
            "x": self.x_axis.currentText(),
            "y": self.y_axis.currentText(),
            "filters": self.filter_panel.get_all_conditions() if hasattr(self.filter_panel, "get_all_conditions") else [],
            "style": {
                "title_font_size": int(self.title_font_size.value()),
                "title_color": str(self.title_color.currentText()),
                "title_shadow": bool(self.title_shadow.currentIndex() == 1),
                "text_font_size": int(self.text_font_size.value()),
                "text_color": str(self.text_color.currentText()),
                "text_shadow": bool(self.text_shadow.currentIndex() == 1),
            },
        }
        return cfg


class ChartWindowWidget(QFrame):
    def __init__(self, parent, chart_id: str, config: dict):
        super().__init__(parent)
        self.chart_id = str(chart_id or "")
        self.config = config or {}
        self._tile_size = 80
        self._tile_gap = 8
        self._tile_margin = 12
        self._dragging = False
        self._drag_offset = QPoint()
        self._snap_timer = QTimer(self)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.setInterval(180)
        self._snap_timer.timeout.connect(self._snap_to_grid)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        cm = ColorManager.instance()
        bg = cm.get("theme.background.light")
        border = cm.get("popup.border.primary")
        self.setStyleSheet(f"background-color: {bg}; border: 1px solid {border}; border-radius: 6px;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(8, 6, 6, 6)
        head_layout.setSpacing(6)

        self.title_label = QLabel(str(self.config.get("name") or ""))
        self._apply_title_style()
        head_layout.addWidget(self.title_label, 1)

        self.menu_btn = QToolButton()
        self.menu_btn.setText("<")
        self.menu_btn.setFixedSize(22, 22)
        self.menu_btn.clicked.connect(self._show_menu)
        head_layout.addWidget(self.menu_btn, 0, Qt.AlignmentFlag.AlignRight)

        root.addWidget(head, 0)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(6, 0, 6, 6)
        body_layout.setSpacing(0)

        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView as _QWebEngineView
            from PyQt6.QtWebChannel import QWebChannel as _QWebChannel
        except Exception:
            _QWebEngineView = None
            _QWebChannel = None
        self._webengine_available = (_QWebEngineView is not None and _QWebChannel is not None)
        self.web = None
        self.channel = None
        self.bridge = None
        if self._webengine_available:
            self.web = _QWebEngineView()
            self.channel = _QWebChannel()
            self.bridge = ChartBridge(self._build_payload)
            self.channel.registerObject("bridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
            self.web.setHtml(self._html(), self._base_url())
            body_layout.addWidget(self.web, 1)
        else:
            tip = QLabel("当前环境未安装 WebEngine，无法渲染图表。\n请安装：pip install PyQt6-WebEngine")
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setWordWrap(True)
            body_layout.addWidget(tip, 1)

        root.addWidget(self.body, 1)

        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(14, 14)
        self.grip.raise_()

    def _apply_title_style(self):
        cm = ColorManager.instance()
        style = self.config.get("style") or {}
        fs = _safe_int(style.get("title_font_size"), 14)
        f = QFont(self.title_label.font())
        try:
            f.setPointSize(int(fs))
        except Exception:
            f.setPointSize(14)
        self.title_label.setFont(f)

        v = str(style.get("title_color") or "主题文字色")
        if v == "主题主色":
            color = cm.get("theme.primary")
        elif v == "白":
            color = "#FFFFFF"
        elif v == "黑":
            color = "#000000"
        else:
            color = cm.get("theme.text.dark")
        self.title_label.setStyleSheet(f"color: {color};")

    def set_grid_metrics(self, tile_size: int, tile_gap: int, tile_margin: int):
        self._tile_size = int(tile_size)
        self._tile_gap = int(tile_gap)
        self._tile_margin = int(tile_margin)
        self._snap_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self.grip.move(self.width() - self.grip.width(), self.height() - self.grip.height())
        except Exception:
            pass
        self._snap_timer.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() <= 34:
                self._dragging = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            p = event.globalPosition().toPoint() - self._drag_offset
            self.move(p)
            self._snap_timer.start()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._snap_timer.start()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _snap_to_grid(self):
        parent = self.parentWidget()
        if parent is None:
            return
        try:
            cols = int(getattr(parent, "grid_cols", 12))
        except Exception:
            cols = 12
        if cols <= 0:
            cols = 12
        u = int(self._tile_size + self._tile_gap)
        if u <= 0:
            return
        x0 = int(self._tile_margin)
        y0 = int(self._tile_margin)

        px = int(self.x())
        py = int(self.y())
        tw = max(1, int(round(float(max(1, self.width() - self._tile_gap)) / float(u))))
        th = max(1, int(round(float(max(1, self.height() - self._tile_gap)) / float(u))))
        tx = int(round(float(px - x0) / float(u)))
        ty = int(round(float(py - y0) / float(u)))
        tx = max(0, min(cols - 1, tx))
        ty = max(0, ty)
        tw = max(1, min(cols - tx, tw))
        th = max(1, th)

        nx = x0 + tx * u
        ny = y0 + ty * u
        nw = tw * u + self._tile_gap
        nh = th * u + self._tile_gap
        try:
            self.setGeometry(nx, ny, nw, nh)
        except Exception:
            self.move(nx, ny)
            self.resize(nw, nh)

        try:
            if hasattr(parent, "on_window_snapped"):
                parent.on_window_snapped(self)
        except Exception:
            pass

    def _data_dir(self) -> str:
        return os.path.join(_project_root(), "data")

    def _base_url(self):
        try:
            from PyQt6.QtCore import QUrl

            return QUrl.fromLocalFile(self._data_dir() + os.sep)
        except Exception:
            return None

    def _html(self) -> str:
        return """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <script src="qwebchannel.js"></script>
  <script src="echarts.min.js"></script>
  <style>
    html, body { height: 100%; width: 100%; margin: 0; padding: 0; overflow: hidden; background: transparent; }
    #chart { height: 100%; width: 100%; }
  </style>
</head>
<body>
  <div id="chart"></div>
  <script>
    const el = document.getElementById('chart');
    const chart = echarts.init(el);
    function render(payload) {
      if (!payload) return;
      const opt = payload.option || {};
      chart.setOption(opt, true);
    }
    new QWebChannel(qt.webChannelTransport, function(channel) {
      const bridge = channel.objects.bridge;
      bridge.getPayload(function(payloadJson) {
        try { render(JSON.parse(payloadJson)); } catch(e) {}
      });
    });
    window.addEventListener('resize', () => { try { chart.resize(); } catch(e) {} });
  </script>
</body>
</html>
"""

    def _build_payload(self) -> dict:
        option = ChartDataBuilder.build_option(self.config)
        return {"id": self.chart_id, "option": option}

    def refresh(self):
        if self.web is None:
            return
        try:
            self.web.page().runJavaScript("location.reload()")
        except Exception:
            pass

    def reset_style(self):
        style = self.config.get("style") or {}
        style["title_font_size"] = 14
        style["title_color"] = "主题文字色"
        style["title_shadow"] = False
        style["text_font_size"] = 11
        style["text_color"] = "主题文字色"
        style["text_shadow"] = False
        self.config["style"] = style
        try:
            self.title_label.setText(str(self.config.get("name") or ""))
            self._apply_title_style()
        except Exception:
            pass
        self.refresh()

    def _show_menu(self):
        menu = QMenu(self)
        act_refresh = menu.addAction("刷新数据")
        act_reset = menu.addAction("重置格式")
        act_del = menu.addAction("删除表格")
        act = menu.exec(self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height())))
        if act is act_refresh:
            self.refresh()
        elif act is act_reset:
            self.reset_style()
        elif act is act_del:
            try:
                parent = self.parentWidget()
                if parent is not None and hasattr(parent, "remove_window"):
                    parent.remove_window(self)
            except Exception:
                pass


class ChartDataBuilder:
    _FIELD_MAP = {
        "评分(score)": "score",
        "ISO(iso)": "iso",
        "快门(shutter)": "shutter",
        "光圈(fnumber)": "fnumber",
        "焦距(focal_length)": "focal_length",
        "拍摄时间(shot_time)": "shot_time",
        "创建时间(created_at)": "created_at",
        "物种(species_cls)": "species_cls",
    }

    @classmethod
    def _query_rows(cls, cfg: dict) -> list[dict]:
        db = BirdLibraryDB()
        conn = db._get_connection()
        cursor = conn.cursor()
        sql = "SELECT score, iso, shutter, fnumber, focal_length, shot_time, created_at, species_cls, tags, location, rating, is_favorite FROM bird_results WHERE 1=1"
        params = []
        conditions = cfg.get("filters") or []
        for c in conditions:
            try:
                field = c.get("field")
                val = c.get("value")
                logic = (c.get("logic") or "AND").upper()
            except Exception:
                continue
            if not field:
                continue
            if field == "__scope_fav__" and bool(val):
                sql += " AND is_favorite = 1"
                continue
            if field in ("目", "科", "属", "种"):
                fm = {"目": "order_cls", "科": "family_cls", "属": "genus_cls", "种": "species_cls"}
                col = fm.get(field)
                if not col:
                    continue
                fuzzy = bool(c.get("fuzzy", False))
                if fuzzy:
                    sql += f" AND {col} LIKE ?"
                    params.append(f"%{val}%")
                else:
                    sql += f" AND {col} = ?"
                    params.append(val)
                continue
            if field == "标签":
                sql += " AND tags LIKE ?"
                params.append(f"%{val}%")
                continue
            if field == "地址":
                sql += " AND location LIKE ?"
                params.append(f"%{val}%")
                continue
            if field == "评分":
                try:
                    v = float(val)
                except Exception:
                    continue
                op = c.get("operator", "=")
                if op == "=":
                    sql += " AND COALESCE(rating,0) BETWEEN ? AND ?"
                    params.extend([v - 0.1, v + 0.1])
                elif op == "≥":
                    sql += " AND COALESCE(rating,0) >= ?"
                    params.append(v - 0.1)
                elif op == "≤":
                    sql += " AND COALESCE(rating,0) <= ?"
                    params.append(v + 0.1)
                continue
        sql += " LIMIT 5000"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        out = []
        for r in rows:
            try:
                out.append(dict(r))
            except Exception:
                pass
        return out

    @classmethod
    def build_option(cls, cfg: dict) -> dict:
        cm = ColorManager.instance()
        primary = cm.get("theme.primary")
        text_default = cm.get("theme.text.dark")
        grid_bg = cm.get("theme.background.light")
        style = cfg.get("style") or {}
        title_fs = _safe_int(style.get("title_font_size"), 14)
        text_fs = _safe_int(style.get("text_font_size"), 11)
        title = str(cfg.get("name") or "")
        ctype = cfg.get("type") or "直方图"
        rows = cls._query_rows(cfg)

        def _resolve_color(key: str, fallback: str):
            v = str((style or {}).get(key) or "").strip()
            if v == "主题主色":
                return primary
            if v == "白":
                return "#FFFFFF"
            if v == "黑":
                return "#000000"
            if v == "主题文字色":
                return text_default
            return fallback

        title_color = _resolve_color("title_color", text_default)
        text_color = _resolve_color("text_color", text_default)
        title_shadow = bool((style or {}).get("title_shadow", False))
        text_shadow = bool((style or {}).get("text_shadow", False))

        def _shadow_block(enabled: bool):
            if not enabled:
                return {}
            return {"textShadowColor": "#00000080", "textShadowBlur": 6, "textShadowOffsetX": 0, "textShadowOffsetY": 1}

        def _to_float(x):
            try:
                if x is None:
                    return None
                if isinstance(x, (int, float)):
                    return float(x)
                s = str(x).strip()
                if not s:
                    return None
                return float(s)
            except Exception:
                return None

        if ctype == "树形图":
            counts = {}
            for r in rows:
                sp = (r.get("species_cls") or "").strip()
                if not sp:
                    sp = "未知"
                counts[sp] = counts.get(sp, 0) + 1
            children = [{"name": k, "value": int(v)} for k, v in sorted(counts.items(), key=lambda x: -x[1])[:200]]
            return {
                "backgroundColor": grid_bg,
                "title": {"text": title, "left": "center", "textStyle": {"color": title_color, "fontSize": title_fs, **_shadow_block(title_shadow)}},
                "tooltip": {"trigger": "item"},
                "series": [
                    {
                        "type": "treemap",
                        "data": children,
                        "label": {"show": True, "color": text_color, "fontSize": text_fs, **_shadow_block(text_shadow)},
                        "itemStyle": {"borderColor": grid_bg, "borderWidth": 2},
                    }
                ],
            }

        x_field = cls._FIELD_MAP.get(cfg.get("x") or cfg.get("data_type")) or "score"
        if ctype == "折线图":
            y_field = cls._FIELD_MAP.get(cfg.get("data_type")) or "score"
            points = []
            for r in rows:
                xv = r.get(x_field)
                yv = r.get(y_field)
                fx = _to_float(xv)
                fy = _to_float(yv)
                if fx is None or fy is None:
                    continue
                points.append((fx, fy))
            points.sort(key=lambda p: p[0])
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return {
                "backgroundColor": grid_bg,
                "title": {"text": title, "left": "center", "textStyle": {"color": title_color, "fontSize": title_fs, **_shadow_block(title_shadow)}},
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "value", "name": x_field, "axisLabel": {"color": text_color, "fontSize": text_fs, **_shadow_block(text_shadow)}},
                "yAxis": {"type": "value", "name": y_field, "axisLabel": {"color": text_color, "fontSize": text_fs, **_shadow_block(text_shadow)}},
                "series": [{"type": "line", "data": list(zip(xs, ys)), "smooth": True, "showSymbol": False, "lineStyle": {"color": primary}}],
            }

        vals = []
        for r in rows:
            v = _to_float(r.get(cls._FIELD_MAP.get(cfg.get("data_type")) or "score"))
            if v is None:
                continue
            vals.append(v)
        if not vals:
            bins = []
            counts = []
        else:
            mn = min(vals)
            mx = max(vals)
            if mx <= mn:
                mx = mn + 1.0
            nbin = 20
            step = (mx - mn) / float(nbin)
            bins = [mn + i * step for i in range(nbin)]
            counts = [0] * nbin
            for v in vals:
                idx = int((v - mn) / step)
                if idx >= nbin:
                    idx = nbin - 1
                if idx < 0:
                    idx = 0
                counts[idx] += 1
        x_labels = [round(b, 2) for b in bins]
        return {
            "backgroundColor": grid_bg,
            "title": {"text": title, "left": "center", "textStyle": {"color": title_color, "fontSize": title_fs, **_shadow_block(title_shadow)}},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": x_labels, "axisLabel": {"color": text_color, "fontSize": text_fs, **_shadow_block(text_shadow)}},
            "yAxis": {"type": "value", "axisLabel": {"color": text_color, "fontSize": text_fs, **_shadow_block(text_shadow)}},
            "series": [{"type": "bar", "data": counts, "itemStyle": {"color": primary}}],
        }


class GridCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid_cols = 12
        self.tile_gap = 8
        self.tile_margin = 12
        self.tile_size = 80
        self.rows = 24
        self._hover_tile = None
        self._plus_btn = QToolButton(self)
        self._plus_btn.setAutoRaise(True)
        self._plus_btn.setText("+")
        self._plus_btn.setVisible(False)
        self._plus_btn.clicked.connect(self._on_plus_clicked)
        self._plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plus_btn.setFixedSize(28, 28)
        self._plus_btn.setStyleSheet("QToolButton { background: rgba(0,0,0,0.0); border: none; font-size: 22px; }")

        self._windows: dict[str, ChartWindowWidget] = {}
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._save_layout_now)

        self._layout_cache = {}
        self.setMouseTracking(True)
        self._tile_cache_key = None
        self._tile_cache_pixmap = None
        self._tile_cache_rendering = False
        self._tile_cache_pool = QThreadPool.globalInstance()

    def set_rows(self, rows: int):
        self.rows = max(8, int(rows))
        self._update_min_size()
        self.update()

    def _update_min_size(self):
        u = self.tile_size + self.tile_gap
        w = self.tile_margin * 2 + self.grid_cols * u - self.tile_gap
        h = self.tile_margin * 2 + self.rows * u - self.tile_gap
        self.setMinimumSize(w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recompute_tile_size()
        self._request_tile_cache()
        self._update_min_size()
        for w in self._windows.values():
            w.set_grid_metrics(self.tile_size, self.tile_gap, self.tile_margin)
        self._place_plus_btn()

    def _recompute_tile_size(self):
        avail = max(200, int(self.width()) - self.tile_margin * 2)
        u = max(10, int((avail - (self.grid_cols - 1) * self.tile_gap) / self.grid_cols))
        self.tile_size = max(36, u)

    def request_tile_cache_rebuild(self):
        self._tile_cache_key = None
        self._tile_cache_pixmap = None
        self._request_tile_cache()
        self.update()

    def _current_tile_cache_key(self):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.light")
        line_color = cm.get("popup.border.primary")
        dot_color = cm.get("theme.primary")
        return (int(self.tile_size), int(self.tile_gap), int(self.tile_margin), str(bg), str(line_color), str(dot_color), float(self.devicePixelRatioF()))

    def _request_tile_cache(self):
        key = self._current_tile_cache_key()
        if self._tile_cache_key == key and self._tile_cache_pixmap is not None:
            return
        if self._tile_cache_rendering:
            return
        self._tile_cache_rendering = True

        class _Signals(QObject):
            done = pyqtSignal(object, object)

        signals = _Signals()

        class _Worker(QRunnable):
            def __init__(self, key2):
                super().__init__()
                self.key2 = key2

            def run(self):
                tile_size, tile_gap, _margin, bg, line_color, dot_color, dpr = self.key2
                u = max(4, int(tile_size + tile_gap))
                img = QImage(int(u * dpr), int(u * dpr), QImage.Format.Format_ARGB32_Premultiplied)
                img.setDevicePixelRatio(dpr)
                img.fill(QColor(bg))
                p = QPainter(img)
                pen = QPen(QColor(line_color))
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidth(1)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(0, 0, int(tile_size), int(tile_size))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(dot_color))
                d = 4
                p.drawEllipse(QPointF(0, 0), d / 2.0, d / 2.0)
                p.drawEllipse(QPointF(tile_size, 0), d / 2.0, d / 2.0)
                p.drawEllipse(QPointF(0, tile_size), d / 2.0, d / 2.0)
                p.drawEllipse(QPointF(tile_size, tile_size), d / 2.0, d / 2.0)
                p.end()
                signals.done.emit(img, self.key2)

        def _on_done(img, key2):
            self._tile_cache_rendering = False
            try:
                if key2 != self._current_tile_cache_key():
                    return
            except Exception:
                pass
            try:
                pm = QPixmap.fromImage(img)
            except Exception:
                pm = None
            self._tile_cache_key = key2
            self._tile_cache_pixmap = pm
            self.update()

        signals.done.connect(_on_done)
        self._tile_cache_pool.start(_Worker(key))

    def paintEvent(self, event):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.light")
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(bg))
        if self._tile_cache_pixmap is None:
            self._request_tile_cache()
            return

        u = int(self.tile_size + self.tile_gap)
        w = int(self.grid_cols * u)
        h = int(self.rows * u)
        p.drawTiledPixmap(QRect(int(self.tile_margin), int(self.tile_margin), w, h), self._tile_cache_pixmap)

    def mouseMoveEvent(self, event):
        self._hover_tile = self._tile_at(event.position().toPoint())
        self._place_plus_btn()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_tile = None
        self._plus_btn.setVisible(False)
        super().leaveEvent(event)

    def _tile_at(self, pos: QPoint):
        u = self.tile_size + self.tile_gap
        x = pos.x() - self.tile_margin
        y = pos.y() - self.tile_margin
        if x < 0 or y < 0:
            return None
        c = int(x // u)
        r = int(y // u)
        if c < 0 or c >= self.grid_cols or r < 0 or r >= self.rows:
            return None
        rx = x - c * u
        ry = y - r * u
        if rx < 0 or ry < 0 or rx > self.tile_size or ry > self.tile_size:
            return None
        return (r, c)

    def _tile_rect(self, r: int, c: int):
        u = self.tile_size + self.tile_gap
        x = self.tile_margin + c * u
        y = self.tile_margin + r * u
        return (x, y, self.tile_size, self.tile_size)

    def _place_plus_btn(self):
        if self._hover_tile is None:
            self._plus_btn.setVisible(False)
            return
        r, c = self._hover_tile
        if self._is_tile_occupied(r, c):
            self._plus_btn.setVisible(False)
            return
        try:
            self._plus_btn.setProperty("_tile_rc", (int(r), int(c)))
        except Exception:
            pass
        x, y, w, h = self._tile_rect(r, c)
        cx = x + w // 2 - self._plus_btn.width() // 2
        cy = y + h // 2 - self._plus_btn.height() // 2
        self._plus_btn.move(int(cx), int(cy))
        cm = ColorManager.instance()
        try:
            qc = cm.qcolor("theme.primary")
            qc.setAlphaF(0.55)
            rgba = f"rgba({qc.red()}, {qc.green()}, {qc.blue()}, {qc.alphaF():.2f})"
        except Exception:
            rgba = cm.get("theme.primary")
        self._plus_btn.setStyleSheet(f"QToolButton {{ color: {rgba}; background: rgba(0,0,0,0.0); border: none; font-size: 22px; }}")
        self._plus_btn.setVisible(True)

    def _is_tile_occupied(self, r: int, c: int) -> bool:
        u = self.tile_size + self.tile_gap
        x = self.tile_margin + c * u
        y = self.tile_margin + r * u
        tr = QRect(int(x), int(y), int(self.tile_size), int(self.tile_size))
        for w in self._windows.values():
            try:
                if w.geometry().intersects(tr):
                    return True
            except Exception:
                continue
        return False

    def _on_plus_clicked(self):
        tile = None
        try:
            tile = self._plus_btn.property("_tile_rc")
        except Exception:
            tile = None
        if tile is None:
            tile = self._hover_tile
        if not tile:
            return
        try:
            r, c = int(tile[0]), int(tile[1])
        except Exception:
            return
        try:
            self._plus_btn.setVisible(False)
        except Exception:
            pass
        dlg = CreateChartDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cfg = dlg.get_config()
        self.add_window_at_tile(cfg, r, c)

    def add_window_at_tile(self, cfg: dict, r: int, c: int):
        cid = str(uuid.uuid4())
        win = ChartWindowWidget(self, cid, cfg)
        win.set_grid_metrics(self.tile_size, self.tile_gap, self.tile_margin)
        u = self.tile_size + self.tile_gap
        x = self.tile_margin + c * u
        y = self.tile_margin + r * u
        tw, th = 4, 3
        win.setGeometry(x, y, tw * u + self.tile_gap, th * u + self.tile_gap)
        win.show()
        self._windows[cid] = win
        self._save_timer.start()

    def remove_window(self, w: ChartWindowWidget):
        try:
            cid = str(w.chart_id)
        except Exception:
            cid = ""
        if cid and cid in self._windows:
            self._windows.pop(cid, None)
        try:
            w.setParent(None)
            w.deleteLater()
        except Exception:
            pass
        self._save_timer.start()
        self._place_plus_btn()

    def on_window_snapped(self, w: ChartWindowWidget):
        self._save_timer.start()
        self._place_plus_btn()

    def load_layout(self, data: dict):
        if not isinstance(data, dict):
            return
        items = data.get("charts") or []
        if not isinstance(items, list):
            return
        for it in items:
            try:
                cid = str(it.get("id") or "")
                cfg = it.get("config") or {}
                tx = _safe_int(it.get("tx"), 0)
                ty = _safe_int(it.get("ty"), 0)
                tw = max(1, _safe_int(it.get("tw"), 4))
                th = max(1, _safe_int(it.get("th"), 3))
            except Exception:
                continue
            if not cid:
                continue
            if cid in self._windows:
                continue
            win = ChartWindowWidget(self, cid, cfg)
            win.set_grid_metrics(self.tile_size, self.tile_gap, self.tile_margin)
            u = self.tile_size + self.tile_gap
            x = self.tile_margin + tx * u
            y = self.tile_margin + ty * u
            win.setGeometry(x, y, tw * u + self.tile_gap, th * u + self.tile_gap)
            win.show()
            self._windows[cid] = win

    def dump_layout(self) -> dict:
        u = self.tile_size + self.tile_gap
        out = []
        for cid, w in self._windows.items():
            try:
                tx = int(round(float(w.x() - self.tile_margin) / float(u)))
                ty = int(round(float(w.y() - self.tile_margin) / float(u)))
                tw = max(1, int(round(float(max(1, w.width() - self.tile_gap)) / float(u))))
                th = max(1, int(round(float(max(1, w.height() - self.tile_gap)) / float(u))))
                out.append({"id": cid, "tx": tx, "ty": ty, "tw": tw, "th": th, "config": w.config})
            except Exception:
                continue
        return {"charts": out}

    def _save_layout_now(self):
        p = _charts_store_path()
        _ensure_dir(p)
        data = self.dump_layout()
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


class DataChartsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataChartsPage")
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self.canvas = GridCanvas()
        self.scroll.setWidget(self.canvas)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.scroll, 1)

        cm = ColorManager.instance()
        cm.register_listener(self._apply_theme)
        self._apply_theme()
        self._load_layout()

    def _apply_theme(self):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.light")
        self.setStyleSheet(f"background-color: {bg};")
        try:
            self.canvas.request_tile_cache_rebuild()
        except Exception:
            self.canvas.update()

    def _load_layout(self):
        p = _charts_store_path()
        try:
            if not os.path.isfile(p):
                return
        except Exception:
            return
        data = None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return
        self.canvas.load_layout(data)

    def _on_scroll(self, value: int):
        bar = self.scroll.verticalScrollBar()
        if bar is None:
            return
        try:
            if int(value) >= int(bar.maximum()) - 800:
                self.canvas.set_rows(self.canvas.rows + 20)
        except Exception:
            pass
