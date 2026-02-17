"""
ECharts 北京拍鸟数据可视化 - 仪表盘版 (PyQt6 + GridStack + ECharts)

功能:
- 基于 gridstack.js 的可拖拽 / 可缩放网格仪表盘
- 用户可自由添加 / 删除 8 种图表类型
- 图表按虚拟方格吸附, 可拖拽改变位置, 拖拽边缘改变大小
- 支持多 ECharts 主题切换
- 布局可手动保存 / 恢复 (localStorage)

依赖:
  pip install PyQt6 PyQt6-WebEngine

注意:
  gridstack-all.js 和 gridstack.min.css 需放在脚本同目录下
  所有资源均为本地加载, 无需网络连接

运行:
  python echarts_map_demo.py

渲染模式:
  默认使用 GPU 渲染(性能更好)
  鼠标不在窗口内时暂停图表渲染, 进入窗口后恢复
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Tuple

# 渲染模式默认 GPU，可通过环境变量切到 CPU
RENDER_MODE = os.environ.get("WB_RENDER_MODE", "balanced").strip().lower()
if RENDER_MODE not in ("balanced", "safe"):
    RENDER_MODE = "balanced"
ARCH_MODE = os.environ.get("WB_ARCH_MODE", "single").strip().lower()
DEBUG_OPTS: Dict[str, Any] = {
    "lite_layout": False,
    "disable_tooltip": False,
    "disable_emphasis": False,
    "disable_ripple": False,
    "disable_map_roam": False,
    "disable_grid_animate": False,
}

CHART_TYPE_LABELS: List[Tuple[str, str]] = [
    ("map_density", "观测密度地图"),
    ("map_scatter", "拍摄点位地图"),
    ("map_heatmap", "观鸟热力地图"),
    ("map_graph", "观鸟路线图"),
    ("bar", "鸟种数量柱状图"),
    ("pie", "分类占比饼图"),
    ("line", "月度趋势折线图"),
    ("gauge", "年度观测完成率"),
    ("bird_list", "鸟名列表"),
    ("scatter", "散点图"),
    ("tree", "树图"),
    ("treemap", "矩形树图"),
    ("sunburst", "旭日图"),
    ("map", "地图"),
    ("lines", "线图"),
    ("graph", "关系图"),
    ("geo", "地理坐标系"),
    ("calendar", "日历"),
    ("customGauge", "自定义仪表"),
    ("customGaugeMini", "自定义仪表-迷你卡"),
    ("customGaugeProgress", "自定义仪表-进度环"),
    ("radar", "基础雷达图"),
    ("radarCustom", "自定义雷达图"),
    ("radarStudio", "自定义雷达图-工作室"),
    ("radarContrast", "自定义雷达图-对比"),
    ("radarMulti", "多雷达图"),
    ("geoGraph", "地理关系图"),
    ("scrollLegend", "可滚动图例"),
    ("globe3D", "中国观鸟热力图"),
    ("timelineLine", "时间轴折线图"),
    ("timelineGallery", "时间轴图片表格"),
    ("bar3D", "3D柱状图"),
]

# 必须在 QApplication / QWebEngine 初始化前设置 Chromium flags
if RENDER_MODE == "safe":
    # 强制稳定模式: 即使外部已设置 flags, 也覆盖为无 GPU 路径
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--disable-gpu "
        "--disable-gpu-compositing "
        "--disable-gpu-vsync "
        "--disable-frame-rate-limit "
        "--disable-features=UseSkiaRenderer,CanvasOopRasterization"
    )
    os.environ["QT_OPENGL"] = "software"
    os.environ["QSG_RHI_BACKEND"] = "software"
else:
    # balanced: 保留硬件加速, 仅关闭已知容易抖动的栅格路径
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--use-angle=d3d11 "
        "--enable-gpu-rasterization "
        "--disable-gpu-vsync "
        "--disable-features=CanvasOopRasterization"
    )

from PyQt6.QtCore import QMimeData, QPoint, Qt, QUrl
from PyQt6.QtGui import QColor, QDrag, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage

# ════════════════════════════ 路径 ════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GEOJSON_PATH = os.path.join(BASE_DIR, "data", "geographic", "world", "中国-area.json")
CHINA_GEOJSON_PATH = os.path.join(BASE_DIR, "data", "geographic", "world", "中国-area.json")
ECHARTS_JS_PATH = os.path.join(BASE_DIR, "data", "echart", "echarts.js")
THEME_DIR = os.path.join(BASE_DIR, "data", "echart", "theme")
GRIDSTACK_JS_PATH = os.path.join(BASE_DIR, "data", "gridstack", "gridstack-all.js")
GRIDSTACK_CSS_PATH = os.path.join(BASE_DIR, "data", "gridstack", "gridstack.min.css")

# ════════════════════════════ 工具函数 ════════════════════════════


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_geojson() -> Dict[str, Any]:
    try:
        with open(GEOJSON_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError:
        with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


def read_json_file(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


# ════════════════════════════ 主题 ════════════════════════════

_DARK_GEO_INJECT = """
    theme.map = {
        itemStyle: { areaColor: '#1B2444', borderColor: '#58D9F9', borderWidth: 1 },
        label: { color: '#B9B8CE' },
        emphasis: { itemStyle: { areaColor: '#2B6A9E', borderColor: '#444' }, label: { color: '#EEF1FA' } }
    };
    theme.geo = {
        itemStyle: { areaColor: '#1B2444', borderColor: '#58D9F9', borderWidth: 1 },
        label: { color: '#B9B8CE' },
        emphasis: { itemStyle: { areaColor: '#2B6A9E', borderColor: '#444' }, label: { color: '#EEF1FA' } }
    };
"""

_DARK_UI: Dict[str, Any] = {
    "bodyBg": "#100C2A", "dark": True,
    "textColor": "#B9B8CE", "titleColor": "#EEF1FA",
    "geoArea": "#1B2444", "geoBorder": "#58D9F9",
    "geoEmphArea": "#2B6A9E", "geoEmphBorder": "#444", "geoLabelColor": "#B9B8CE",
    "colorPalette": ["#4992FF", "#7CFFB2", "#FDDD60", "#FF6E76", "#58D9F9", "#05C091"],
}


def _rgba_to_hex(s: str) -> str:
    try:
        p = s.replace("rgba(", "").replace(")", "").split(",")
        if float(p[3].strip()) < 0.3:
            return "#ffffff"
        return f"#{int(p[0]):02x}{int(p[1]):02x}{int(p[2]):02x}"
    except (IndexError, ValueError):
        return "#ffffff"


def _is_dark(c: str) -> bool:
    h = c.lstrip("#")
    if len(h) != 6:
        return False
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140


def _extract_ui(obj: Dict) -> Dict[str, Any]:
    bg_raw = obj.get("backgroundColor", "")
    body_bg = "#ffffff"
    if bg_raw and bg_raw != "transparent":
        body_bg = _rgba_to_hex(bg_raw) if bg_raw.startswith("rgba") else bg_raw
    dark = _is_dark(body_bg)
    tc = obj.get("title", {}).get("subtextStyle", {}).get("color", "") or \
         obj.get("title", {}).get("textStyle", {}).get("color", "") or ("#B9B8CE" if dark else "#333")
    ttc = obj.get("title", {}).get("textStyle", {}).get("color", "") or ("#EEF1FA" if dark else "#111")
    g = obj.get("geo", obj.get("map", {}))
    gi, ge = g.get("itemStyle", {}), g.get("emphasis", {}).get("itemStyle", {})
    palette = obj.get("color", [])
    return {
        "bodyBg": body_bg, "dark": dark, "textColor": tc, "titleColor": ttc,
        "geoArea": gi.get("areaColor", "#eee" if not dark else "#1B2444"),
        "geoBorder": gi.get("borderColor", "#444" if not dark else "#58D9F9"),
        "geoEmphArea": ge.get("areaColor", "rgba(255,215,0,0.8)"),
        "geoEmphBorder": ge.get("borderColor", "#444"),
        "geoLabelColor": g.get("label", {}).get("color", tc),
        "colorPalette": palette[:8] if palette else [],
    }


def load_themes() -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    reg: Dict[str, str] = {}
    ui: Dict[str, Dict[str, Any]] = {}
    for f in os.listdir(THEME_DIR):
        fp, n = os.path.join(THEME_DIR, f), os.path.splitext(f)[0]
        if f.endswith(".js"):
            code = read_text(fp).replace(
                "echarts.registerTheme('dark', theme);",
                _DARK_GEO_INJECT + "    echarts.registerTheme('dark', theme);")
            reg[n] = code
            ui[n] = _DARK_UI
        elif f.endswith(".json"):
            c = read_text(fp)
            reg[n] = f"echarts.registerTheme('{n}', {c});\n"
            try:
                ui[n] = _extract_ui(json.loads(c))
            except json.JSONDecodeError:
                ui[n] = _DARK_UI
    return reg, ui


# ════════════════════════════ 地理数据 ════════════════════════════


def get_district_centers(geojson: Dict[str, Any]) -> List[Dict[str, Any]]:
    centers = []
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        name = props.get("name", "")
        geom = feat.get("geometry", {})
        coords, gtype = geom.get("coordinates", []), geom.get("type", "")
        pts: List[List[float]] = []
        if gtype == "Polygon" and coords:
            pts = [p for p in coords[0] if isinstance(p, list) and len(p) >= 2]
        elif gtype == "MultiPolygon" and coords:
            for poly in coords:
                if poly and poly[0]:
                    pts.extend(p for p in poly[0] if isinstance(p, list) and len(p) >= 2)
        if pts and name:
            centers.append({"name": name,
                            "lon": sum(p[0] for p in pts) / len(pts),
                            "lat": sum(p[1] for p in pts) / len(pts)})
    return centers


# ════════════════════════════ 拍鸟数据 ════════════════════════════

BIRD_ORDERS = ["雀形目", "鹰形目", "雁形目", "鸻形目", "鹤形目", "鸡形目", "鸮形目", "其他"]
BIRD_SPECIES = [
    "大山雀", "喜鹊", "麻雀", "北红尾鸲", "白头鹎", "珠颈斑鸠",
    "灰椋鸟", "戴胜", "红隼", "苍鹭", "绿头鸭", "夜鹭",
    "普通鵟", "黑翅长脚鹬", "白鹡鸰", "棕背伯劳", "黄腹山雀", "红嘴蓝鹊",
    "小䴙䴘", "白鹭", "黑卷尾", "斑鸫", "褐马鸡", "灰喜鹊",
]


def gen_all_data(districts: List[Dict]) -> Dict[str, str]:
    """生成所有图表所需的随机数据, 返回 key -> JSON 字符串 的字典."""
    density = [{"name": d["name"], "value": random.randint(20, 800)} for d in districts]

    scatter = []
    for d in districts:
        for _ in range(random.randint(3, 8)):
            scatter.append([round(d["lon"] + random.uniform(-.05, .05), 4),
                            round(d["lat"] + random.uniform(-.05, .05), 4),
                            random.randint(5, 120)])

    heatmap = []
    for d in districts:
        for _ in range(random.randint(10, 25)):
            heatmap.append([round(d["lon"] + random.uniform(-.08, .08), 4),
                            round(d["lat"] + random.uniform(-.08, .08), 4),
                            random.randint(1, 100)])

    bar = [{"name": d["name"], "value": random.randint(30, 260)} for d in districts]
    pie = [{"name": o, "value": random.randint(50, 600)} for o in BIRD_ORDERS]

    cnt = min(8, len(districts))
    sel = random.sample(districts, cnt)
    gn = [{"name": d["name"], "value": [d["lon"], d["lat"]],
           "symbolSize": random.randint(12, 25)} for d in sel]
    gl = [{"source": sel[i]["name"], "target": sel[(i + 1) % cnt]["name"]}
          for i in range(cnt)]
    for _ in range(3):
        a, b = random.sample(range(cnt), 2)
        gl.append({"source": sel[a]["name"], "target": sel[b]["name"]})

    # ── 新增: 折线图月度数据 ──
    months = [f"{m}月" for m in range(1, 13)]
    line_observe = [random.randint(50, 300) for _ in range(12)]
    line_photo = [random.randint(30, 200) for _ in range(12)]
    line_species = [random.randint(5, 50) for _ in range(12)]

    # ── 新增: 仪表盘数据 ──
    gauge_value = random.randint(45, 95)
    bird_names = random.sample(BIRD_SPECIES, min(16, len(BIRD_SPECIES)))

    return {k: json.dumps(v, ensure_ascii=False) for k, v in {
        "density": density,
        "scatter": scatter,
        "heatmap": heatmap,
        "barNames": [d["name"] for d in districts],
        "barValues": [b["value"] for b in bar],
        "pie": pie,
        "graphNodes": gn,
        "graphLinks": gl,
        "lineMonths": months,
        "lineObserve": line_observe,
        "linePhoto": line_photo,
        "lineSpecies": line_species,
        "gaugeValue": gauge_value,
        "birdNames": bird_names,
    }.items()}


# ════════════════════════════ HTML 仪表盘模板 ════════════════════════════

HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>__GRIDSTACK_CSS__</style>
<style>
/* ── Reset ── */
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden;font-family:var(--font-ui);-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}

/* ── CSS Variables (dark defaults) ── */
:root{
  --toolbar-h:46px;
  --radius-xs:4px;
  --radius-sm:6px;
  --radius-md:10px;
  --radius-lg:14px;
  --radius-xl:20px;
  --space-1:4px;
  --space-2:8px;
  --space-3:12px;
  --space-4:16px;
  --control-h:28px;
  --font-sm:11.5px;
  --font-md:12.5px;
  --font-lg:14px;
  --font-ui:"Fira Sans","Segoe UI","Microsoft YaHei",sans-serif;
  --font-mono:"Fira Code","Consolas","Courier New",monospace;
  --motion-fast:110ms;
  --motion-mid:170ms;
  --motion-slow:260ms;
  --easing-standard:cubic-bezier(.22,.61,.36,1);
  --easing-bounce:cubic-bezier(.34,1.56,.64,1);
  --chart-font-xs:10px;
  --chart-font-sm:11px;
  --chart-font-md:12px;
  --chart-font-lg:14px;
  --chart-gap-sm:8px;
  --chart-gap-md:12px;
  --bg:#0c0e1a;
  --scene-bg:#080a14;
  --primary:#1E40AF;
  --secondary:#3B82F6;
  --cta:#F59E0B;
  --ink-strong:#1E3A8A;
  --scene-gradient:
    radial-gradient(ellipse 110% 80% at 8% 0%, rgba(59,130,246,0.14) 0%, transparent 58%),
    radial-gradient(ellipse 90% 70% at 92% 4%, rgba(139,92,246,0.12) 0%, transparent 56%),
    radial-gradient(ellipse 120% 90% at 50% 110%, rgba(16,185,129,0.08) 0%, transparent 62%),
    linear-gradient(168deg, #0d1020 0%, #0a0c18 50%, #0e1024 100%);
  --scene-texture:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200' viewBox='0 0 200 200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.78' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.7'/%3E%3C/svg%3E");
  --scene-texture-opacity:.035;
  --scene-style-overlay:none;
  --toolbar-bg:rgba(12,14,26,0.92);
  --toolbar-blur:0px;
  --toolbar-border:rgba(255,255,255,0.06);
  --card-bg:rgba(16,20,38,0.82);
  --card-header-bg:rgba(22,28,52,0.88);
  --card-blur:0px;
  --card-saturate:140%;
  --card-border-alpha:0.10;
  --card-layer-blur:0px;
  --card-layer-opacity:0;
  --card-layer-scale:1;
  --card-overlay-opacity:0;
  --card-overlay-color:transparent;
  --card-overlay-image:none;
  --glass-blur:10px;
  --text:#94a3b8;
  --text-title:#e2e8f0;
  --text-muted:rgba(148,163,184,0.56);
  --accent:var(--secondary);
  --close-hover:#ef4444;
  --btn-bg:rgba(59,130,246,0.08);
  --btn-border:rgba(59,130,246,0.20);
  --btn-hover:rgba(59,130,246,0.16);
  --select-bg:rgba(16,20,38,0.92);
  --grid-dot:rgba(255,255,255,0.02);
  --menu-bg:rgba(14,17,32,0.96);
  --menu-hover:rgba(59,130,246,0.12);
  --shadow:rgba(0,0,0,0.5);
  --card-shadow:0 1px 2px rgba(0,0,0,0.24),0 4px 12px rgba(0,0,0,0.18),0 12px 28px rgba(0,0,0,0.12);
  --card-border-color:rgba(255,255,255,0.07);
  --focus-ring:rgba(59,130,246,0.56);
  --focus-ring-soft:rgba(59,130,246,0.20);
  --toolbar-group-bg:rgba(255,255,255,0.025);
  --toolbar-group-border:rgba(59,130,246,0.16);
  --toolbar-group-primary-border:rgba(59,130,246,0.36);
  --toolbar-highlight:linear-gradient(90deg,transparent,rgba(59,130,246,0.24),rgba(16,185,129,0.16),transparent);
  --card-head-text:rgba(226,232,240,0.90);
  --card-head-shadow:none;
  --glow-primary:rgba(59,130,246,0.40);
  --glow-success:rgba(16,185,129,0.50);
}
body{background:var(--bg);color:var(--text)}

/* ── Toolbar ── */
#toolbar{
  position:fixed;top:0;left:0;right:0;z-index:1000;height:var(--toolbar-h);
  display:flex;align-items:center;justify-content:space-between;padding:0 var(--space-4);gap:8px;
  background:var(--toolbar-bg);border-bottom:1px solid var(--toolbar-border);
  backdrop-filter:blur(var(--toolbar-blur));-webkit-backdrop-filter:blur(var(--toolbar-blur));
  transform:translateZ(0);
}
/* 工具栏底部发光条 */
#toolbar::after{
  content:"";position:absolute;left:0;right:0;bottom:-1px;height:1px;
  background:var(--toolbar-highlight);opacity:.7;pointer-events:none;
}
.toolbar-title{
  font-size:13.5px;font-weight:600;color:var(--text-title);letter-spacing:.01em;
  display:flex;align-items:center;gap:6px;white-space:nowrap;flex-shrink:0;
}
.toolbar-title span:first-child{font-size:16px;filter:drop-shadow(0 0 4px var(--glow-primary))}
.toolbar-actions{
  display:flex;align-items:center;gap:6px;min-width:0;flex:1;justify-content:flex-end;
  overflow-x:visible;overflow-y:visible;scrollbar-width:none;-ms-overflow-style:none;
}
.toolbar-actions::-webkit-scrollbar{display:none;width:0;height:0}
.toolbar-group{
  display:flex;align-items:center;gap:var(--space-2);
  height:calc(var(--toolbar-h) - 14px);
  padding:0 var(--space-2);
  border:1px solid var(--toolbar-group-border);
  border-radius:var(--radius-sm);
  background:var(--toolbar-group-bg);
  box-shadow:inset 0 1px 0 rgba(255,255,255,0.03);
  transition:border-color var(--motion-fast) var(--easing-standard);
}
.toolbar-group:hover{border-color:rgba(59,130,246,0.28)}
.toolbar-group[data-kind="primary"]{
  border-color:var(--toolbar-group-primary-border);
  box-shadow:inset 0 1px 0 rgba(59,130,246,0.08),0 0 0 1px rgba(59,130,246,0.08);
}
.toolbar-group-title{
  font-size:10px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--text-muted,var(--text));
  white-space:nowrap;
  font-family:var(--font-mono);
}
.toolbar-actions select{
  background:var(--select-bg);color:var(--text);border:1px solid var(--btn-border);
  border-radius:var(--radius-xs);padding:0 var(--space-2);height:var(--control-h);font-size:var(--font-sm);cursor:pointer;
  transition:border-color var(--motion-fast) var(--easing-standard),background var(--motion-fast) var(--easing-standard),box-shadow var(--motion-fast) var(--easing-standard);
  font-family:inherit;outline:none;
}
.toolbar-actions select:hover,.toolbar-actions select:focus{border-color:var(--accent);box-shadow:0 0 0 1px rgba(59,130,246,0.12)}
.btn{
  background:var(--btn-bg);color:var(--text);border:1px solid var(--btn-border);
  border-radius:var(--radius-xs);padding:0 var(--space-3);height:var(--control-h);font-size:var(--font-sm);cursor:pointer;
  transition:all var(--motion-fast) var(--easing-standard);
  white-space:nowrap;font-family:inherit;letter-spacing:.01em;
}
.btn:hover{background:var(--btn-hover);border-color:var(--accent);color:var(--text-title);box-shadow:0 0 8px rgba(59,130,246,0.12)}
.btn:active{transform:scale(.97)}
.btn-primary{
  background:rgba(59,130,246,0.12);color:#60a5fa;border-color:rgba(59,130,246,0.40);
  font-weight:500;
}
.btn-primary:hover{background:rgba(59,130,246,0.20);box-shadow:0 0 12px rgba(59,130,246,0.18)}
.ui-inline{
  display:flex;align-items:center;gap:var(--space-1);
  font-size:var(--font-sm);color:var(--text);white-space:nowrap;
}
.ui-number-sm{
  width:48px;height:var(--control-h);
  background:var(--select-bg);color:var(--text);
  border:1px solid var(--btn-border);border-radius:var(--radius-xs);
  padding:0 6px;font-size:var(--font-sm);
}
.ui-color-sm{
  width:28px;height:24px;border:1px solid var(--btn-border);
  border-radius:var(--radius-xs);cursor:pointer;background:transparent;padding:0;
}
.ui-range-sm{
  width:96px;height:var(--control-h);
  accent-color:var(--accent);
  cursor:pointer;
}
.ui-badge-sm{
  min-width:44px;
  text-align:center;
  font-size:11px;
  color:var(--text-title);
  padding:2px 6px;
  border-radius:999px;
  border:1px solid var(--btn-border);
  background:var(--btn-bg);
}

/* ── Dropdown ── */
.dropdown{position:relative}
.dropdown-menu{
  display:none;position:absolute;top:calc(100% + 4px);right:0;min-width:210px;
  background:var(--menu-bg);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-md);padding:4px;
  box-shadow:0 4px 6px rgba(0,0,0,0.16),0 12px 28px rgba(0,0,0,0.28),0 0 0 1px rgba(0,0,0,0.10);
  backdrop-filter:blur(16px) saturate(160%);-webkit-backdrop-filter:blur(16px) saturate(160%);z-index:1001;
  max-height:calc(100vh - 72px);overflow-y:auto;
  scrollbar-width:none;-ms-overflow-style:none;
}
.dropdown-menu::-webkit-scrollbar{display:none;width:0;height:0}
.dropdown.open .dropdown-menu{display:block}
.menu-item{
  padding:6px 12px;cursor:pointer;font-size:var(--font-sm);border-radius:var(--radius-xs);
  transition:all var(--motion-fast) var(--easing-standard);
  color:var(--text);display:flex;align-items:center;gap:8px;margin:1px 0;
}
.menu-item:hover{background:var(--menu-hover);color:var(--text-title)}
.menu-item:active{transform:scale(.98)}
.menu-label{
  padding:6px 12px 3px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--text-muted,var(--text));opacity:.7;cursor:default;font-family:var(--font-mono);
}
.menu-sep{height:1px;background:rgba(255,255,255,0.05);margin:4px 8px}
.menu-item,.btn,.card-close,.card-drag{cursor:pointer}
.btn:focus-visible,.toolbar-actions select:focus-visible,.menu-item:focus-visible,.card-close:focus-visible,.card-drag:focus-visible{
  outline:none;
  box-shadow:0 0 0 2px var(--focus-ring-soft),0 0 0 1px var(--focus-ring) inset;
}

/* ── Grid Container ── */
#gridWrap{
  position:fixed;top:var(--toolbar-h);left:0;right:0;bottom:0;padding:0 6px 6px 6px;overflow-y:auto;
  background-color:var(--scene-bg);
  background-image:var(--scene-style-overlay),var(--scene-gradient);
  background-size:cover,cover;
  background-repeat:no-repeat,no-repeat;
  background-position:center center,center center;
  isolation:isolate;
  overscroll-behavior:contain;
  -webkit-overflow-scrolling:touch;
  scrollbar-width:none;
  -ms-overflow-style:none;
}
#gridWrap::before{
  content:"";
  position:absolute;inset:0;z-index:0;pointer-events:none;
  background-image:var(--scene-texture);
  background-size:200px 200px;
  background-repeat:repeat;
  opacity:var(--scene-texture-opacity);
  mix-blend-mode:overlay;
}
#gridWrap::-webkit-scrollbar{display:none;width:0;height:0}
#gridGuideCanvas{
  position:absolute;left:0;top:0;z-index:6;pointer-events:none;
  opacity:0;transition:opacity .15s ease;
}
#gridWrap.show-dash-grid #gridGuideCanvas{opacity:1}
#grid{
  position:relative;min-height:100%;width:100%;z-index:7;
}
.empty-state{
  position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
  z-index:8;pointer-events:none;text-align:center;
  padding:28px 36px;border-radius:16px;
  border:1px solid rgba(255,255,255,0.06);
  background:rgba(14,17,32,0.60);
  backdrop-filter:blur(20px) saturate(140%);
  -webkit-backdrop-filter:blur(20px) saturate(140%);
  color:var(--text);
  box-shadow:0 8px 32px rgba(0,0,0,0.32),0 0 0 1px rgba(255,255,255,0.04) inset;
}
.empty-state::before{
  content:"";position:absolute;top:0;left:20%;right:20%;height:1px;
  background:linear-gradient(90deg,transparent,rgba(59,130,246,0.30),transparent);
  pointer-events:none;
}
.empty-state-icon{
  font-size:28px;margin-bottom:8px;opacity:.6;
  filter:drop-shadow(0 0 6px var(--glow-primary));
}
.empty-state-title{
  font-size:13px;font-weight:600;color:var(--text-title);margin-bottom:6px;letter-spacing:.02em;
}
.empty-state-sub{
  font-size:11px;color:var(--text);opacity:.64;line-height:1.5;
}
.empty-state.is-hidden{display:none}

/* ── GridStack Overrides ── */
.grid-stack{min-height:100%}
.grid-stack-item-content{
  border-radius:var(--radius-lg)!important;overflow:hidden!important;
  box-shadow:var(--card-shadow);
  transition:box-shadow var(--motion-mid) var(--easing-standard);
  will-change:box-shadow;
}
.grid-stack-item-content:hover{
  box-shadow:0 2px 4px rgba(0,0,0,0.28),0 8px 18px rgba(0,0,0,0.22),0 16px 36px rgba(0,0,0,0.16);
}
/* 拖拽中 */
.grid-stack-item.ui-draggable-dragging .grid-stack-item-content,
.grid-stack-item.ui-resizable-resizing .grid-stack-item-content{
  box-shadow:0 4px 8px rgba(0,0,0,0.32),0 16px 40px rgba(0,0,0,0.28),0 0 0 1px rgba(59,130,246,0.20)!important;
}
.grid-stack-item.is-active .grid-stack-item-content{
  box-shadow:0 2px 4px rgba(0,0,0,0.28),0 8px 18px rgba(0,0,0,0.22),0 16px 36px rgba(0,0,0,0.16);
}
.grid-stack-item.is-active .card{
  border-color:rgba(59,130,246,0.14);
}
.grid-stack-item.is-active .card-drag,
.grid-stack-item.is-active .card-close{
  color:var(--text-title);
}
.grid-stack-placeholder>.placeholder-content{
  border:1.5px dashed rgba(59,130,246,0.50)!important;border-radius:var(--radius-lg)!important;
  background:rgba(59,130,246,0.06)!important;
  box-shadow:0 0 20px rgba(59,130,246,0.12)!important;
}
/* GridStack 缩放手柄 */
.grid-stack-item>.ui-resizable-handle{opacity:.32;transition:opacity var(--motion-fast)}
.grid-stack-item:hover>.ui-resizable-handle{opacity:.52}

/* ── Card (borderless, controls always visible) ── */
.card{
  display:flex;flex-direction:column;height:100%;
  background:var(--card-bg);
  border:1px solid var(--card-border-color);
  border-radius:var(--radius-lg);overflow:hidden;position:relative;
  isolation:isolate;
  backdrop-filter:blur(var(--card-blur)) saturate(var(--card-saturate));
  -webkit-backdrop-filter:blur(var(--card-blur)) saturate(var(--card-saturate));
  transition:border-color var(--motion-mid) var(--easing-standard),background var(--motion-mid) var(--easing-standard);
}
/* 顶部光带 —— 赋予卡片深度与立体感 */
.card::before{
  content:"";
  position:absolute;top:0;left:10%;right:10%;height:1px;z-index:3;pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,0.10),transparent);
}
/* 内部纹理层 */
.card::after{
  content:"";
  position:absolute;inset:0;z-index:1;pointer-events:none;
  border-radius:inherit;
  background-color:var(--card-overlay-color);
  background-image:var(--card-overlay-image);
  opacity:var(--card-overlay-opacity);
}
.card > *{position:relative;z-index:2}
.card.is-loading .card-body{opacity:.0}
.card-loading{
  position:absolute;left:8px;right:8px;top:40px;bottom:8px;z-index:3;
  border-radius:10px;pointer-events:none;overflow:hidden;
  background:linear-gradient(105deg,
    rgba(59,130,246,0.00) 0%,rgba(59,130,246,0.04) 25%,
    rgba(59,130,246,0.08) 40%,rgba(59,130,246,0.04) 55%,
    rgba(59,130,246,0.00) 100%);
  background-size:250% 100%;
  animation:cardShimmer 1.6s ease-in-out infinite;
  display:none;
}
.card.is-loading .card-loading{display:block}
@keyframes cardShimmer{
  from{background-position:200% 0}
  to{background-position:-100% 0}
}
/* 状态点 —— 呼吸脉冲 */
.card-status-dot{
  width:6px;height:6px;border-radius:999px;flex:none;display:inline-block;
  transition:background var(--motion-fast),box-shadow var(--motion-fast);
}
.card-status-dot.is-running{
  background:#34d399;
  box-shadow:0 0 0 2px rgba(52,211,153,0.20),0 0 6px rgba(52,211,153,0.40);
  animation:statusPulse 2.4s ease-in-out infinite;
}
.card-status-dot.is-paused{background:rgba(148,163,184,0.50);box-shadow:none}
@keyframes statusPulse{
  0%,100%{box-shadow:0 0 0 2px rgba(52,211,153,0.20),0 0 6px rgba(52,211,153,0.40)}
  50%{box-shadow:0 0 0 3px rgba(52,211,153,0.10),0 0 10px rgba(52,211,153,0.24)}
}
.pause-tag{
  position:absolute;left:8px;top:8px;z-index:12;
  padding:1px 7px;border-radius:6px;font-size:10px;font-weight:600;letter-spacing:.02em;
  color:rgba(255,255,255,0.90);background:rgba(239,68,68,0.72);display:none;
  box-shadow:0 2px 6px rgba(0,0,0,0.28);pointer-events:none;
  backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);
}
.card-header{
  position:absolute;top:6px;left:6px;right:6px;z-index:10;height:28px;
  display:flex;align-items:center;
  background:transparent;padding:0;opacity:1;pointer-events:auto;
  border:none;
  backdrop-filter:none;
  -webkit-backdrop-filter:none;
  border-radius:8px;
}
.card-drag{
  flex:1;padding:0 8px;font-size:11px;font-weight:500;color:var(--card-head-text);letter-spacing:.01em;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  display:flex;align-items:center;gap:4px;height:100%;user-select:none;cursor:grab;
  background:transparent;border:none;border-radius:6px;
  transition:color var(--motion-fast) var(--easing-standard);
}
.card-drag:active{cursor:grabbing}
.card-close{
  flex-shrink:0;width:28px;height:28px;display:flex;align-items:center;justify-content:center;
  cursor:pointer;color:var(--card-head-text);font-size:14px;border-radius:6px;
  background:transparent;border:none;opacity:.6;
  transition:all var(--motion-fast) var(--easing-standard);
}
.card-close:hover{color:#fff;background:rgba(239,68,68,0.70);opacity:1;box-shadow:0 0 8px rgba(239,68,68,0.20)}
.card-body{flex:1;min-height:0;position:relative;z-index:2}

/* ── Scrollbar ── */
/* 隐藏滚动条但保留滚动能力 */

/* ── Toast ── */
.toast{
  position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(6px);
  padding:8px 22px;border-radius:8px;font-size:12px;font-weight:500;letter-spacing:.01em;
  background:rgba(14,17,32,0.88);color:#e2e8f0;
  border:1px solid rgba(59,130,246,0.18);
  box-shadow:0 4px 20px rgba(0,0,0,0.36),0 0 0 1px rgba(59,130,246,0.08);
  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
  opacity:0;transition:all var(--motion-slow) var(--easing-standard);pointer-events:none;z-index:9999;
}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

/* ── Fade-in animation ── */
@keyframes cardIn{
  from{opacity:0;transform:translateY(8px) scale(.98)}
  to{opacity:1;transform:translateY(0) scale(1)}
}
.grid-stack-item{animation:cardIn var(--motion-slow) var(--easing-standard)}
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
}
</style></head>
<body>

<!-- ══ Toolbar ══ -->
<div id="toolbar">
  <div class="toolbar-title"><span>&#x1f426;</span><span>北京拍鸟数据仪表盘</span></div>
  <div class="toolbar-actions">
    <div class="toolbar-group">
      <span class="toolbar-group-title">渲染</span>
      <label class="ui-inline" title="切换渲染模式（重启生效）">
        <select id="renderModeSelect">
          <option value="balanced" __RENDER_GPU_SELECTED__>GPU</option>
          <option value="safe" __RENDER_CPU_SELECTED__>CPU</option>
        </select>
      </label>
      <label class="ui-inline" title="鼠标离开窗口后暂停渲染">
        <input type="checkbox" id="pauseWhenOut" checked>离开暂停
      </label>
      <label class="ui-inline" title="窗口内静止 N 秒后自动暂停">
        静止
        <input id="idleSec" class="ui-number-sm" type="number" min="0" max="60" value="3">
        秒
      </label>
    </div>
    <div class="toolbar-group">
      <span class="toolbar-group-title">外观</span>
      <label class="ui-inline" title="自定义背景颜色">背景
        <input type="color" id="bgColor" class="ui-color-sm" value="#1a1a2e">
      </label>
      <label class="ui-inline" title="悬浮窗口风格">风格
        <select id="windowStyleSelect">
          <option value="opaque">不透明</option>
          <option value="transparent">透明</option>
          <option value="acrylic" selected>亚克力</option>
          <option value="frosted">磨砂玻璃</option>
          <option value="flat">极简扁平</option>
          <option value="executive">商务深空</option>
        </select>
      </label>
      <label class="ui-inline" title="风格强度（影响透明度/模糊/光感）">强度
        <input id="styleStrength" class="ui-range-sm" type="range" min="60" max="140" step="5" value="100">
        <span id="styleStrengthVal" class="ui-badge-sm">100%</span>
      </label>
      <label class="ui-inline" title="3D柱状图渲染模式">3D模式
        <select id="bar3DModeSelect">
          <option value="auto" selected>自动</option>
          <option value="native">真3D</option>
          <option value="pseudo">兼容伪3D</option>
        </select>
      </label>
      <label class="ui-inline" title="切换主题">主题
        <select id="themeSelect">__THEME_OPTS__</select>
      </label>
    </div>
    <div class="toolbar-group" data-kind="primary">
      <span class="toolbar-group-title">布局</span>
      <div class="dropdown" id="addDropdown">
        <button class="btn btn-primary" id="addBtn">+ 添加图表</button>
        <div class="dropdown-menu" id="chartMenu">
        <div class="menu-label">── 地图类 ──</div>
        <div class="menu-item" data-type="map_density"><span>&#x1f5fa;&#xfe0f;</span>观测密度地图</div>
        <div class="menu-item" data-type="map_scatter"><span>&#x1f4cd;</span>拍摄点位地图</div>
        <div class="menu-item" data-type="map_heatmap"><span>&#x1f525;</span>观鸟热力地图</div>
        <div class="menu-item" data-type="map_graph"><span>&#x1f517;</span>观鸟路线图</div>
        <div class="menu-sep"></div>
        <div class="menu-label">── 统计类 ──</div>
        <div class="menu-item" data-type="bar"><span>&#x1f4ca;</span>鸟种数量柱状图</div>
        <div class="menu-item" data-type="pie"><span>&#x1f967;</span>分类占比饼图</div>
        <div class="menu-item" data-type="line"><span>&#x1f4c8;</span>月度趋势折线图</div>
        <div class="menu-item" data-type="gauge"><span>&#x1f3af;</span>年度观测完成率</div>
        <div class="menu-item" data-type="bird_list"><span>&#x1f9fe;</span>鸟名列表</div>
        <div class="menu-item" data-type="scatter"><span>&#x1f535;</span>散点图</div>
        <div class="menu-item" data-type="tree"><span>&#x1f333;</span>树图</div>
        <div class="menu-item" data-type="treemap"><span>&#x1f9e9;</span>矩形树图</div>
        <div class="menu-item" data-type="sunburst"><span>&#x2600;&#xfe0f;</span>旭日图</div>
        <div class="menu-item" data-type="radar"><span>&#x1f4e1;</span>基础雷达图</div>
        <div class="menu-item" data-type="radarCustom"><span>&#x1f6f0;&#xfe0f;</span>自定义雷达图</div>
        <div class="menu-item" data-type="radarStudio"><span>&#x1f3a8;</span>自定义雷达图-工作室</div>
        <div class="menu-item" data-type="radarContrast"><span>&#x1f3af;</span>自定义雷达图-对比</div>
        <div class="menu-item" data-type="radarMulti"><span>&#x1f4f6;</span>多雷达图</div>
        <div class="menu-item" data-type="calendar"><span>&#x1f4c5;</span>日历图</div>
        <div class="menu-item" data-type="customGauge"><span>&#x1f527;</span>自定义仪表</div>
        <div class="menu-item" data-type="customGaugeMini"><span>&#x1f9ed;</span>自定义仪表-迷你卡</div>
        <div class="menu-item" data-type="customGaugeProgress"><span>&#x1f4a0;</span>自定义仪表-进度环</div>
        <div class="menu-item" data-type="lines"><span>&#x27a1;&#xfe0f;</span>迁飞线图</div>
        <div class="menu-item" data-type="graph"><span>&#x1f517;</span>关系图</div>
        <div class="menu-item" data-type="geo"><span>&#x1f30d;</span>地理坐标图</div>
        <div class="menu-item" data-type="geoGraph"><span>&#x1f5fa;&#xfe0f;</span>地理关系图</div>
        <div class="menu-item" data-type="scrollLegend"><span>&#x1f4dc;</span>可滚动图例</div>
        <div class="menu-item" data-type="timelineLine"><span>&#x23f2;&#xfe0f;</span>时间轴折线图</div>
        <div class="menu-item" data-type="timelineGallery"><span>&#x1f5bc;&#xfe0f;</span>时间轴图片表格</div>
        <div class="menu-item" data-type="globe3D"><span>&#x1f30e;</span>中国观鸟热力图</div>
        <div class="menu-item" data-type="bar3D"><span>&#x1f4ca;</span>3D柱状图</div>
        </div>
      </div>
      <button class="btn" id="btnSave" title="保存当前布局">&#x1f4be; 保存</button>
      <button class="btn" id="btnRestore" title="恢复已保存的布局">&#x1f4c2; 恢复</button>
      <button class="btn" id="btnClear" title="清空所有图表">&#x1f5d1; 清空</button>
    </div>
  </div>
</div>

<!-- ══ Grid Container ══ -->
<div id="gridWrap">
  <canvas id="gridGuideCanvas"></canvas>
  <div id="emptyState" class="empty-state is-hidden">
    <div class="empty-state-icon">&#x1f4ca;</div>
    <div class="empty-state-title">数据中控台就绪</div>
    <div class="empty-state-sub">点击“添加图表”开始构建你的中控屏</div>
  </div>
  <div id="grid"></div>
</div>

<!-- ══ Toast ══ -->
<div class="toast" id="toast"></div>

<!-- ══ ECharts ══ -->
<script src="echart/resource/echarts.js"></script>
<script src="echart/resource/echarts-gl.min.js"></script>
<script>__REGISTER_CODE__</script>

<!-- ══ GridStack ══ -->
<script src="gridstack-all.js"></script>

<!-- ══ 修复: GridStack v12 的 renderCB 使用 textContent, 需改为 innerHTML ══ -->
<script>GridStack.renderCB=function(el,w){if(el&&w&&w.content)el.innerHTML=w.content};</script>

<!-- ══ Dashboard Logic ══ -->
<script>
(function(){
  /* ──────── 数据 ──────── */
  var GEO=__GEOJSON__;
  echarts.registerMap('beijing',GEO);
  var CHINA_GEO=__CHINA_GEOJSON__;
  if(CHINA_GEO&&CHINA_GEO.features&&CHINA_GEO.features.length){
    echarts.registerMap('china',CHINA_GEO);
  }
  var UI=__UI_MAP__;
  var DATA=__DATA__;
  var DBG=__DEBUG_OPTS__;

  /* ──────── 状态 ──────── */
  var currentTheme='dark';
  var charts={};
  var singleChart=null;
  var nextId=1;
  var resizeTimer;
  var renderActive=true;
  var idlePauseSec=3;
  var idleTimer=null;
  var pauseWhenOut=true;
  var windowStyle='acrylic';
  var styleStrength=100;        /* 风格强度: 60~140 */
  var bar3DMode='auto';          /* auto/native/pseudo */
  var chartActiveMap={};        /* 每个图表是否处于刷新状态 */
  var chartIdleTimers={};       /* 每个图表的静止计时器 */
  var themeRefreshing=false;    /* 主题切换刷新锁 */
  var gridInteracting=false;    /* 拖拽/缩放进行中: 允许更大的下方拖拽缓冲区 */
  var gridBaseMinRow=0;         /* 交互前 minRow 基线 */
  var activeCardId=null;        /* 当前选中的卡片 */

  /* ──────── 工具 ──────── */
  function ui(){
    var base=UI[currentTheme]||UI['dark']||{
      bodyBg:'#1a1a2e',dark:true,textColor:'#B9B8CE',titleColor:'#EEF1FA',
      geoArea:'#1B2444',geoBorder:'#58D9F9',geoEmphArea:'#2B6A9E',
      geoEmphBorder:'#444',geoLabelColor:'#B9B8CE',colorPalette:[]
    };
    /* 磨砂玻璃模式统一使用深色图表文字，提升坐标轴/图例可读性 */
    if(windowStyle==='frosted'){
      var deepText='#1f2430';
      var deepTitle='#121722';
      var deepSub='rgba(31,36,48,0.82)';
      var merged={};
      Object.keys(base).forEach(function(k){merged[k]=base[k]});
      /* 磨砂玻璃统一按浅色分支处理，避免图表内大量 dk 分支走白字 */
      merged.dark=false;
      merged.textColor=deepText;
      merged.titleColor=deepTitle;
      merged.geoLabelColor=deepSub;
      merged.geoEmphBorder='rgba(18,23,34,0.45)';
      return merged;
    }
    return base;
  }
  function toast(msg){
    var el=document.getElementById('toast');el.textContent=msg;
    el.classList.add('show');setTimeout(function(){el.classList.remove('show')},2000);
  }
  function setChartRenderActive(inst,active){
    if(!inst)return;
    try{
      var zr=inst.getZr();
      if(zr&&zr.animation){
        if(active)zr.animation.start();
        else zr.animation.stop();
      }
    }catch(e){}
  }
  function forceChartTransparent(inst){
    if(!inst)return;
    try{
      var dom=inst.getDom&&inst.getDom();
      if(dom){
        dom.style.background='transparent';
        var cvs=dom.querySelectorAll('canvas');
        cvs.forEach(function(cv){
          try{
            cv.style.background='transparent';
            cv.style.backgroundColor='transparent';
          }catch(e){}
        });
      }
      var zr=inst.getZr&&inst.getZr();
      var painter=zr&&zr.painter;
      if(painter&&painter._layers){
        Object.keys(painter._layers).forEach(function(k){
          var layer=painter._layers[k];
          if(layer&&layer.dom&&layer.dom.style){
            layer.dom.style.background='transparent';
            layer.dom.style.backgroundColor='transparent';
          }
          if(layer&&layer.ctx&&typeof layer.ctx.clearColor==='function'){
            try{layer.ctx.clearColor(0,0,0,0)}catch(e){}
          }
        });
      }
    }catch(e){}
  }
  function setPauseTagById(id,paused){
    var tag=document.querySelector('.grid-stack-item[gs-id="'+id+'"] .pause-tag');
    if(tag)tag.style.display=paused?'inline-flex':'none';
    var dot=document.querySelector('.grid-stack-item[gs-id="'+id+'"] [data-role="status-dot"]');
    if(dot){
      dot.classList.remove('is-running','is-paused');
      dot.classList.add(paused?'is-paused':'is-running');
    }
  }
  function setSinglePauseTag(paused){
    var tag=document.querySelector('.pause-tag');
    if(tag)tag.style.display=paused?'inline-flex':'none';
  }
  function setChartActive(id,active){
    if(!id||!charts[id]||!charts[id].instance)return;
    chartActiveMap[id]=!!active;
    setChartRenderActive(charts[id].instance,!!active);
    setPauseTagById(id,!active);
  }
  function setCardLoading(id,loading){
    var card=document.querySelector('.grid-stack-item[gs-id="'+id+'"] .card');
    if(!card)return;
    card.classList.toggle('is-loading',!!loading);
  }
  function updateEmptyState(){
    var es=document.getElementById('emptyState');
    var gridEl=document.getElementById('grid');
    if(!es||!gridEl)return;
    var hasItems=!!gridEl.querySelector('.grid-stack-item');
    es.classList.toggle('is-hidden',hasItems);
  }
  function pauseAllCharts(){
    Object.keys(charts).forEach(function(id){setChartActive(id,false)});
  }
  function pauseAllChartsExcept(keepId){
    Object.keys(charts).forEach(function(id){
      if(id!==keepId)setChartActive(id,false);
    });
  }
  function clearChartIdleTimer(id){
    if(chartIdleTimers[id]){
      clearTimeout(chartIdleTimers[id]);
      delete chartIdleTimers[id];
    }
  }
  function clearAllChartIdleTimers(){
    Object.keys(chartIdleTimers).forEach(function(id){
      clearChartIdleTimer(id);
    });
  }
  function touchChartActivity(id){
    if(!id||!charts[id])return;
    pauseAllChartsExcept(id);
    setChartActive(id,true);
    clearChartIdleTimer(id);
    if(idlePauseSec>0){
      chartIdleTimers[id]=setTimeout(function(){
        setChartActive(id,false);
        delete chartIdleTimers[id];
      },idlePauseSec*1000);
    }
  }
  function chartIdFromTarget(t){
    if(!t||!t.closest)return null;
    var item=t.closest('.grid-stack-item[gs-id]');
    return item?item.getAttribute('gs-id'):null;
  }
  function setActiveCard(id){
    if(!id){
      activeCardId=null;
      document.querySelectorAll('.grid-stack-item.is-active').forEach(function(el){el.classList.remove('is-active')});
      return;
    }
    activeCardId=id;
    document.querySelectorAll('.grid-stack-item.is-active').forEach(function(el){el.classList.remove('is-active')});
    var el=document.querySelector('.grid-stack-item[gs-id="'+id+'"]');
    if(el)el.classList.add('is-active');
  }
  function applyRenderStateToAll(){
    if(singleChart){
      setChartRenderActive(singleChart,renderActive);
      setSinglePauseTag(!renderActive);
      return;
    }
    Object.keys(charts).forEach(function(id){
      setChartActive(id,!!chartActiveMap[id]);
    });
  }
  function getGridMetrics(){
    var wrapEl=document.getElementById('gridWrap');
    var cols=(grid&&grid.opts&&grid.opts.column)?parseInt(grid.opts.column,10):12;
    if(!wrapEl)return {cols:cols,colW:80,rowPitch:80,margin:0,innerW:cols*80};
    var cs=window.getComputedStyle(wrapEl);
    var pl=parseFloat(cs.paddingLeft||'0')||0;
    var pr=parseFloat(cs.paddingRight||'0')||0;
    var innerW=Math.max(1,wrapEl.clientWidth-pl-pr);
    var colW=innerW/Math.max(1,cols);
    var mg=(grid&&grid.opts&&grid.opts.margin!==undefined)?parseFloat(grid.opts.margin||0):0;
    var cellH=(grid&&typeof grid.getCellHeight==='function')?parseFloat(grid.getCellHeight()||0):0;
    if(!(cellH>0))cellH=Math.max(24,colW-mg);
    return {cols:cols,colW:colW,rowPitch:cellH+mg,margin:mg,innerW:innerW};
  }
  function applySquareGridSizing(){
    if(!grid||typeof grid.cellHeight!=='function')return;
    var m=getGridMetrics();
    /* 让每个网格单元接近正方形: 行步距 ~= 列宽 */
    var targetCell=Math.max(24,m.colW-m.margin);
    try{grid.cellHeight(targetCell)}catch(e){}
  }
  function syncGridHeight(){
    var gridEl=document.getElementById('grid');
    var wrapEl=document.getElementById('gridWrap');
    if(!gridEl||!wrapEl)return;

    var maxRow=0;
    try{
      if(typeof grid!=='undefined'&&grid&&typeof grid.getRow==='function'){
        maxRow=grid.getRow()||0;
      }
    }catch(e){}
    if(maxRow<=0){
      document.querySelectorAll('#grid .grid-stack-item[gs-y][gs-h], #grid.grid-stack .grid-stack-item[gs-y][gs-h]').forEach(function(el){
        var y=parseInt(el.getAttribute('gs-y')||'0',10);
        var h=parseInt(el.getAttribute('gs-h')||'1',10);
        if(y+h>maxRow)maxRow=y+h;
      });
    }

    var m=getGridMetrics();
    var tailRows=gridInteracting?24:2;
    var target=Math.max(wrapEl.clientHeight, (maxRow+tailRows)*m.rowPitch+24);
    gridEl.style.minHeight=target+'px';
    gridEl.style.height=target+'px';
    drawDashGrid();
  }
  function drawDashGrid(){
    var wrap=document.getElementById('gridWrap');
    var cvs=document.getElementById('gridGuideCanvas');
    var gridEl=document.getElementById('grid');
    if(!wrap||!cvs)return;
    var dpr=window.devicePixelRatio||1;
    var w=Math.max(1,wrap.clientWidth);
    var h=Math.max(wrap.clientHeight,wrap.scrollHeight);
    var cs=window.getComputedStyle(wrap);
    var pl=parseFloat(cs.paddingLeft||'0')||0;
    var pr=parseFloat(cs.paddingRight||'0')||0;
    var pt=parseFloat(cs.paddingTop||'0')||0;
    var pb=parseFloat(cs.paddingBottom||'0')||0;
    var innerW=Math.max(1,w-pl-pr);
    var gridH=0;
    try{
      if(gridEl){
        var gh=parseFloat(gridEl.style.height||'0')||0;
        gridH=Math.max(gh,gridEl.scrollHeight||0);
      }
    }catch(e){}
    var innerH=Math.max(1,(gridH>0?gridH:(h-pt-pb)));
    cvs.style.width=w+'px';
    cvs.style.height=h+'px';
    cvs.width=Math.floor(w*dpr);
    cvs.height=Math.floor(h*dpr);
    var ctx=cvs.getContext('2d');
    if(!ctx)return;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,w,h);
    var m=getGridMetrics();
    var cols=Math.max(1,m.cols||12);
    var colW=m.colW;
    var rowH=m.rowPitch;
    var xOrigin=pl;
    var yOrigin=0;

    /* 优先使用 placeholder 反推网格参数, 保证与当前拖拽吸附位置一致 */
    if(gridEl){
      var gridRect=gridEl.getBoundingClientRect();
      var ph=gridEl.querySelector('.grid-stack-placeholder[gs-x][gs-y][gs-w][gs-h]');
      if(ph){
        var pr=ph.getBoundingClientRect();
        var gx=parseInt(ph.getAttribute('gs-x')||'0',10);
        var gy=parseInt(ph.getAttribute('gs-y')||'0',10);
        var gw=Math.max(1,parseInt(ph.getAttribute('gs-w')||'1',10));
        var gh=Math.max(1,parseInt(ph.getAttribute('gs-h')||'1',10));
        var pW=pr.width, pH=pr.height;
        if(pW>8)colW=pW/gw;
        if(pH>8)rowH=pH/gh;
        xOrigin=(pr.left-gridRect.left)-gx*colW;
        yOrigin=0;
      }else{
        var first=gridEl.querySelector('.grid-stack-item[gs-x][gs-y]');
        if(first){
          var fr=first.getBoundingClientRect();
          var fgx=parseInt(first.getAttribute('gs-x')||'0',10);
          xOrigin=(fr.left-gridRect.left)-fgx*colW;
        }
      }
    }
    ctx.lineWidth=1;
    ctx.strokeStyle='rgba(126,196,255,0.38)';
    ctx.setLineDash([6,6]);
    for(var c=0;c<=cols;c++){
      var xx=Math.round(xOrigin+c*colW)+0.5;
      ctx.beginPath();
      ctx.moveTo(xx,yOrigin);
      ctx.lineTo(xx,yOrigin+innerH);
      ctx.stroke();
    }
    for(var y=0;y<=innerH+0.5;y+=rowH){
      var yy=Math.round(yOrigin+y)+0.5;
      ctx.beginPath();
      ctx.moveTo(xOrigin,yy);
      ctx.lineTo(xOrigin+cols*colW,yy);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }
  function setDashGridVisible(show){
    var wrap=document.getElementById('gridWrap');
    if(!wrap)return;
    if(show){
      drawDashGrid();
      wrap.classList.add('show-dash-grid');
    }else{
      wrap.classList.remove('show-dash-grid');
    }
  }
  function setRenderActive(active){
    if(renderActive===active)return;
    renderActive=active;
    applyRenderStateToAll();
  }
  function scheduleIdlePause(){
    if(idleTimer){clearTimeout(idleTimer);idleTimer=null}
    if(idlePauseSec>0){
      idleTimer=setTimeout(function(){setRenderActive(false)}, idlePauseSec*1000);
    }
  }
  function userBecameActive(){
    setRenderActive(true);
    scheduleIdlePause();
  }
  function setupRenderPolicyUI(rootEl){
    var pChk=rootEl.querySelector('#pauseWhenOut');
    var iSec=rootEl.querySelector('#idleSec');
    try{
      var pv=localStorage.getItem('render_pause_when_out_v1');
      if(pv!==null)pauseWhenOut=(pv==='1');
      var iv=localStorage.getItem('render_idle_sec_v1');
      if(iv!==null)idlePauseSec=Math.max(0,Math.min(60,parseInt(iv,10)||0));
    }catch(e){}
    if(pChk)pChk.checked=pauseWhenOut;
    if(iSec)iSec.value=String(idlePauseSec);
    if(pChk){
      pChk.addEventListener('change',function(){
        pauseWhenOut=!!pChk.checked;
        try{localStorage.setItem('render_pause_when_out_v1',pauseWhenOut?'1':'0')}catch(e){}
      });
    }
    if(iSec){
      iSec.addEventListener('change',function(){
        idlePauseSec=Math.max(0,Math.min(60,parseInt(iSec.value,10)||0));
        iSec.value=String(idlePauseSec);
        try{localStorage.setItem('render_idle_sec_v1',String(idlePauseSec))}catch(e){}
        scheduleIdlePause();
      });
    }
  }
  function rebuildChartsByTypes(typeList){
    if(!Array.isArray(typeList)||!typeList.length)return;
    Object.keys(charts).forEach(function(id){
      var c=charts[id],el=document.getElementById(id);
      if(!c||!el||typeList.indexOf(c.type)<0)return;
      var wasActive=!!chartActiveMap[id];
      try{
        c.instance.dispose();
      }catch(e){}
      c.instance=echarts.init(el,currentTheme);
      c.instance.setOption(stabilizeOption(CT[c.type].build(),c.type),true);
      forceChartTransparent(c.instance);
      setChartActive(id,wasActive);
    });
  }
  function applyWindowStyle(){
    var r=document.documentElement.style;
    var dk=ui().dark;
    var si=Math.max(60,Math.min(140,styleStrength||100))/100;
    function a(v,min,max){
      var x=v*si;
      if(min!==undefined&&x<min)x=min;
      if(max!==undefined&&x>max)x=max;
      return x;
    }
    function f3(v){return (Math.round(v*1000)/1000).toFixed(3);}
    /* 每次先恢复主题基线，避免切风格后颜色残留 */
    r.setProperty('--text',dk?'#94a3b8':'#475569');
    r.setProperty('--text-title',dk?'#e2e8f0':'#1e293b');
    r.setProperty('--text-muted',dk?'rgba(148,163,184,0.56)':'rgba(71,85,105,0.56)');
    r.setProperty('--select-bg',dk?'rgba(16,20,38,0.92)':'#f8fafc');
    r.setProperty('--btn-border',dk?'rgba(59,130,246,0.20)':'rgba(59,130,246,0.28)');
    r.setProperty('--btn-bg',dk?'rgba(59,130,246,0.08)':'rgba(59,130,246,0.08)');
    r.setProperty('--btn-hover',dk?'rgba(59,130,246,0.16)':'rgba(59,130,246,0.14)');
    r.setProperty('--grid-dot',dk?'rgba(255,255,255,0.02)':'rgba(0,0,0,0.03)');
    r.setProperty('--menu-hover',dk?'rgba(59,130,246,0.12)':'rgba(59,130,246,0.08)');
    r.setProperty('--card-saturate','140%');
    r.setProperty('--card-border-alpha','0.07');
    r.setProperty('--card-border-color',dk?'rgba(255,255,255,0.07)':'rgba(0,0,0,0.06)');
    r.setProperty('--focus-ring','rgba(59,130,246,0.56)');
    r.setProperty('--focus-ring-soft','rgba(59,130,246,0.20)');
    r.setProperty('--card-head-text',dk?'rgba(226,232,240,0.90)':'rgba(30,41,59,0.92)');
    r.setProperty('--card-head-shadow','none');
    r.setProperty('--card-shadow','0 1px 2px rgba(0,0,0,0.24),0 4px 12px rgba(0,0,0,0.18),0 12px 28px rgba(0,0,0,0.12)');
    r.setProperty('--card-layer-blur','0px');
    r.setProperty('--card-layer-opacity','0');
    r.setProperty('--card-layer-scale','1');
    r.setProperty('--card-overlay-color','transparent');
    r.setProperty('--card-overlay-opacity','0');
    r.setProperty('--card-overlay-image','none');
    r.setProperty('--toolbar-group-bg',dk?'rgba(255,255,255,0.025)':'rgba(255,255,255,0.64)');
    r.setProperty('--toolbar-group-border',dk?'rgba(59,130,246,0.16)':'rgba(59,130,246,0.16)');
    r.setProperty('--toolbar-group-primary-border',dk?'rgba(59,130,246,0.36)':'rgba(59,130,246,0.36)');
    r.setProperty('--scene-style-overlay','none');
    r.setProperty('--toolbar-highlight',dk
      ?'linear-gradient(90deg,transparent,rgba(59,130,246,0.24),rgba(16,185,129,0.16),transparent)'
      :'linear-gradient(90deg,transparent,rgba(59,130,246,0.20),rgba(16,185,129,0.12),transparent)');
    if(windowStyle==='flat'){
      r.setProperty('--glass-blur','0px');
      r.setProperty('--toolbar-blur','0px');
      r.setProperty('--card-blur','0px');
      r.setProperty('--card-saturate','100%');
      r.setProperty('--card-border-alpha',f3(a(0.10,0.06,0.18)));
      r.setProperty('--card-border-color',dk?'rgba(96,120,170,0.24)':'rgba(80,108,158,0.18)');
      r.setProperty('--card-layer-blur','0px');
      r.setProperty('--card-layer-opacity','0');
      r.setProperty('--card-overlay-opacity','0');
      r.setProperty('--card-overlay-image','none');
      r.setProperty('--card-shadow','0 2px 8px rgba(10,18,36,0.14)');
      r.setProperty('--toolbar-bg',dk?'#1A223F':'#F5F7FC');
      r.setProperty('--card-bg',dk?'#253053':'#FFFFFF');
      r.setProperty('--card-header-bg',dk?'#2E3B66':'#EEF3FB');
      r.setProperty('--menu-bg',dk?'#1F294A':'#FFFFFF');
      r.setProperty('--scene-style-overlay','none');
      r.setProperty('--scene-texture-opacity',dk?'0.012':'0.008');
      return;
    }
    if(windowStyle==='executive'){
      r.setProperty('--glass-blur','10px');
      r.setProperty('--toolbar-blur','12px');
      r.setProperty('--card-blur','12px');
      r.setProperty('--card-saturate','130%');
      r.setProperty('--card-border-alpha',f3(a(0.12,0.08,0.20)));
      r.setProperty('--card-border-color',dk?'rgba(120,160,220,0.16)':'rgba(80,110,160,0.18)');
      r.setProperty('--card-layer-blur','6px');
      r.setProperty('--card-layer-opacity',f3(a(0.14,0.06,0.24)));
      r.setProperty('--card-layer-scale','1.01');
      r.setProperty('--card-overlay-color',dk?'rgba(80,120,200,0.06)':'rgba(255,255,255,0.08)');
      r.setProperty('--card-overlay-opacity',f3(a(0.10,0.04,0.18)));
      r.setProperty('--card-overlay-image','linear-gradient(135deg,rgba(255,255,255,0.10) 0%,rgba(255,255,255,0.02) 40%,transparent 100%)');
      r.setProperty('--card-shadow','0 2px 4px rgba(0,0,0,0.20),0 8px 20px rgba(0,0,0,0.22),0 16px 36px rgba(0,0,0,0.14)');
      r.setProperty('--toolbar-bg',dk?'rgba(8,12,24,0.86)':'rgba(250,252,255,0.84)');
      r.setProperty('--card-bg',dk?'rgba(14,22,44,0.64)':'rgba(255,255,255,0.70)');
      r.setProperty('--card-header-bg',dk?'rgba(20,32,60,0.60)':'rgba(248,250,255,0.68)');
      r.setProperty('--menu-bg',dk?'rgba(10,16,34,0.92)':'rgba(255,255,255,0.95)');
      r.setProperty('--scene-style-overlay',dk
        ?'radial-gradient(ellipse 90% 50% at 50% -8%,rgba(59,130,246,0.14) 0%,transparent 68%),linear-gradient(180deg,rgba(6,10,22,0.24) 0%,transparent 100%)'
        :'radial-gradient(ellipse 90% 50% at 50% -8%,rgba(59,130,246,0.08) 0%,transparent 68%)');
      r.setProperty('--scene-texture-opacity',dk?'0.022':'0.016');
      return;
    }
    if(windowStyle==='opaque'){
      r.setProperty('--glass-blur','0px');
      r.setProperty('--toolbar-blur','0px');
      r.setProperty('--card-blur','0px');
      r.setProperty('--card-saturate','100%');
      r.setProperty('--card-border-alpha',f3(a(0.10,0.06,0.18)));
      r.setProperty('--card-border-color',dk?'rgba(255,255,255,0.10)':'rgba(26,39,72,0.14)');
      r.setProperty('--card-layer-blur','0px');
      r.setProperty('--card-layer-opacity','0');
      r.setProperty('--toolbar-bg',dk?'#1B2342':'#F4F7FC');
      r.setProperty('--card-bg',dk?'#232D4F':'#FFFFFF');
      r.setProperty('--card-header-bg',dk?'#2E3A66':'#EDF2FA');
      r.setProperty('--menu-bg',dk?'#1F294B':'#FFFFFF');
      r.setProperty('--scene-texture-opacity',dk?'0.024':'0.018');
      r.setProperty('--toolbar-group-bg',dk?'rgba(255,255,255,0.02)':'rgba(255,255,255,0.72)');
      r.setProperty('--toolbar-group-border',dk?'rgba(73,146,255,0.16)':'rgba(57,80,130,0.18)');
      r.setProperty('--toolbar-border',dk?'rgba(255,255,255,0.10)':'rgba(26,39,72,0.12)');
      r.setProperty('--scene-style-overlay',dk
        ?'linear-gradient(180deg,rgba(23,32,60,0.34) 0%,rgba(18,26,50,0.18) 36%,rgba(13,19,36,0.08) 100%)'
        :'linear-gradient(180deg,rgba(255,255,255,0.40) 0%,rgba(255,255,255,0.20) 36%,rgba(255,255,255,0.08) 100%)');
      if(!dk){
        r.setProperty('--text','#2b3247');
        r.setProperty('--text-title','#161b29');
        r.setProperty('--select-bg','#ffffff');
        r.setProperty('--btn-border','rgba(57,80,130,0.24)');
        r.setProperty('--btn-bg','rgba(244,247,254,1)');
        r.setProperty('--btn-hover','rgba(233,240,252,1)');
        r.setProperty('--grid-dot','rgba(30,45,80,0.06)');
      }
      return;
    }
    if(windowStyle==='transparent'){
      r.setProperty('--glass-blur','0px');
      r.setProperty('--toolbar-blur','0px');
      r.setProperty('--card-blur','0px');
      r.setProperty('--card-saturate','105%');
      r.setProperty('--card-border-alpha',f3(a(0.08,0.04,0.16)));
      r.setProperty('--card-border-color',dk?'rgba(165,190,255,0.20)':'rgba(70,100,150,0.16)');
      r.setProperty('--card-layer-blur','0px');
      r.setProperty('--card-layer-opacity','0');
      r.setProperty('--toolbar-bg',dk?'rgba(18,24,52,0.16)':'rgba(255,255,255,0.24)');
      r.setProperty('--card-bg',dk?'rgba(36,50,94,0.14)':'rgba(255,255,255,0.28)');
      r.setProperty('--card-header-bg',dk?'rgba(58,76,126,0.16)':'rgba(242,245,250,0.24)');
      r.setProperty('--menu-bg',dk?'rgba(28,34,62,0.26)':'rgba(255,255,255,0.30)');
      r.setProperty('--scene-texture-opacity',dk?f3(a(0.018,0.010,0.034)):f3(a(0.014,0.008,0.026)));
      r.setProperty('--toolbar-group-bg',dk?'rgba(255,255,255,0.015)':'rgba(255,255,255,0.42)');
      r.setProperty('--toolbar-group-border',dk?'rgba(120,170,255,0.20)':'rgba(70,110,170,0.16)');
      r.setProperty('--scene-style-overlay',dk
        ?'radial-gradient(88% 64% at 50% -12%,rgba(59,130,246,0.16) 0%,rgba(59,130,246,0.00) 74%)'
        :'radial-gradient(88% 64% at 50% -12%,rgba(59,130,246,0.10) 0%,rgba(59,130,246,0.00) 74%)');
      return;
    }
    if(windowStyle==='frosted'){
      r.setProperty('--glass-blur',Math.round(a(20,14,28))+'px');
      r.setProperty('--toolbar-blur',Math.round(a(14,10,22))+'px');
      r.setProperty('--card-blur',Math.round(a(20,14,28))+'px');
      r.setProperty('--card-saturate','92%');
      r.setProperty('--card-border-alpha',f3(a(0.42,0.28,0.62)));
      r.setProperty('--card-border-color','rgba(116,136,166,0.34)');
      r.setProperty('--card-shadow','0 6px 14px rgba(15,23,42,0.12),0 1px 4px rgba(15,23,42,0.08)');
      r.setProperty('--card-layer-blur',Math.round(a(6,3,10))+'px');
      r.setProperty('--card-layer-opacity',f3(a(0.18,0.10,0.32)));
      r.setProperty('--card-layer-scale','1.01');
      r.setProperty('--card-overlay-color','rgba(255,255,255,0.20)');
      r.setProperty('--card-overlay-opacity',f3(a(0.56,0.34,0.82)));
      r.setProperty('--card-overlay-image','linear-gradient(180deg,rgba(255,255,255,0.28) 0%,rgba(255,255,255,0.12) 45%,rgba(255,255,255,0.04) 100%)');
      /* 磨砂玻璃仅作用于窗口本体 */
      r.setProperty('--toolbar-bg','rgba(246,250,255,0.80)');
      r.setProperty('--card-bg','rgba(252,255,255,0.44)');
      r.setProperty('--card-header-bg','rgba(255,255,255,0.30)');
      r.setProperty('--menu-bg','rgba(250,253,255,0.92)');
      r.setProperty('--text','#1F2E45');
      r.setProperty('--text-title','#0F172A');
      r.setProperty('--card-head-text','rgba(25,38,60,0.96)');
      r.setProperty('--card-head-shadow','none');
      r.setProperty('--focus-ring','rgba(67,128,235,0.70)');
      r.setProperty('--focus-ring-soft','rgba(67,128,235,0.20)');
      r.setProperty('--select-bg','rgba(255,255,255,0.84)');
      r.setProperty('--btn-border','rgba(59,130,246,0.28)');
      r.setProperty('--btn-bg','rgba(255,255,255,0.56)');
      r.setProperty('--btn-hover','rgba(255,255,255,0.76)');
      r.setProperty('--grid-dot','rgba(30,45,80,0.06)');
      r.setProperty('--menu-hover','rgba(73,146,255,0.12)');
      r.setProperty('--toolbar-group-bg','rgba(255,255,255,0.52)');
      r.setProperty('--toolbar-group-border','rgba(59,130,246,0.24)');
      r.setProperty('--toolbar-group-primary-border','rgba(73,146,255,0.46)');
      r.setProperty('--toolbar-highlight','linear-gradient(90deg,rgba(73,146,255,0.0),rgba(73,146,255,0.30),rgba(5,192,145,0.22),rgba(73,146,255,0.0))');
      r.setProperty('--scene-texture-opacity',dk?f3(a(0.018,0.010,0.034)):f3(a(0.014,0.008,0.026)));
      return;
    }
    /* 默认: 亚克力 */
    r.setProperty('--glass-blur',Math.round(a(14,10,20))+'px');
    r.setProperty('--toolbar-blur',Math.round(a(14,10,20))+'px');
    r.setProperty('--card-blur',Math.round(a(14,10,20))+'px');
    r.setProperty('--card-saturate','150%');
    r.setProperty('--card-border-alpha',f3(a(0.10,0.06,0.18)));
    r.setProperty('--card-border-color',dk?'rgba(148,196,255,0.14)':'rgba(100,140,220,0.16)');
    r.setProperty('--card-layer-blur',Math.round(a(8,4,14))+'px');
    r.setProperty('--card-layer-opacity',f3(a(0.20,0.10,0.36)));
    r.setProperty('--card-layer-scale','1.02');
    r.setProperty('--card-overlay-color',dk?'rgba(120,170,255,0.04)':'rgba(255,255,255,0.08)');
    r.setProperty('--card-overlay-opacity',f3(a(0.12,0.06,0.24)));
    r.setProperty('--card-overlay-image','linear-gradient(135deg,rgba(255,255,255,0.12) 0%,rgba(255,255,255,0.04) 40%,transparent 100%)');
    r.setProperty('--toolbar-bg',dk?'rgba(10,14,28,0.72)':'rgba(255,255,255,0.78)');
    r.setProperty('--card-bg',dk?'rgba(16,24,48,0.32)':'rgba(255,255,255,0.44)');
    r.setProperty('--card-header-bg',dk?'rgba(28,40,72,0.24)':'rgba(248,250,255,0.42)');
    r.setProperty('--menu-bg',dk?'rgba(12,16,32,0.82)':'rgba(255,255,255,0.90)');
    r.setProperty('--scene-style-overlay',dk
      ?'radial-gradient(ellipse 84% 56% at 0% 0%,rgba(59,130,246,0.16) 0%,transparent 70%),radial-gradient(ellipse 78% 52% at 100% 0%,rgba(139,92,246,0.12) 0%,transparent 68%)'
      :'radial-gradient(ellipse 84% 56% at 0% 0%,rgba(59,130,246,0.10) 0%,transparent 70%),radial-gradient(ellipse 78% 52% at 100% 0%,rgba(139,92,246,0.08) 0%,transparent 68%)');
    r.setProperty('--scene-texture-opacity',dk?f3(a(0.028,0.014,0.046)):f3(a(0.018,0.008,0.032)));
  }
  function applyChartsDemoStyle(opt, chartType){
    if(!opt||typeof opt!=='object')return opt;
    var u=ui(),dk=!!u.dark;
    var isFrosted=windowStyle==='frosted';
    var rs=getComputedStyle(document.documentElement);
    function tokPx(name, fallback){
      var v=parseFloat((rs.getPropertyValue(name)||'').trim());
      return isFinite(v)&&v>0?v:fallback;
    }
    var fsXS=tokPx('--chart-font-xs',10);
    var fsSM=tokPx('--chart-font-sm',11);
    var fsLG=tokPx('--chart-font-lg',14);
    var gapSM=tokPx('--chart-gap-sm',8);
    var gapMD=tokPx('--chart-gap-md',12);
    var tc=u.textColor||'#B9B8CE';
    var ttc=u.titleColor||'#EEF1FA';
    var lc=isFrosted?'rgba(18,23,34,0.28)':(dk?'rgba(255,255,255,0.10)':'rgba(0,0,0,0.10)');
    var split=isFrosted?'rgba(18,23,34,0.12)':(dk?'rgba(255,255,255,0.06)':'rgba(0,0,0,0.06)');
    var fontUI=(rs.getPropertyValue('--font-ui')||'').trim()||'Segoe UI,Microsoft YaHei,sans-serif';
    if(!opt.textStyle)opt.textStyle={};
    if(opt.textStyle.color===undefined)opt.textStyle.color=tc;
    if(opt.textStyle.fontFamily===undefined)opt.textStyle.fontFamily=fontUI;
    if(opt.animationDuration===undefined)opt.animationDuration=260;
    if(opt.animationDurationUpdate===undefined)opt.animationDurationUpdate=220;
    if(opt.animationEasing===undefined)opt.animationEasing='cubicOut';
    if(opt.animationEasingUpdate===undefined)opt.animationEasingUpdate='cubicOut';
    if(!Array.isArray(opt.color)||!opt.color.length){
      if(Array.isArray(u.colorPalette)&&u.colorPalette.length)opt.color=u.colorPalette.slice(0);
    }
    if(opt.tooltip&&typeof opt.tooltip==='object'){
      if(opt.tooltip.confine===undefined)opt.tooltip.confine=true;
      if(opt.tooltip.backgroundColor===undefined)opt.tooltip.backgroundColor=dk?'rgba(12,16,36,0.92)':'rgba(255,255,255,0.96)';
      if(opt.tooltip.borderColor===undefined)opt.tooltip.borderColor=dk?'rgba(120,170,255,0.34)':'rgba(57,80,130,0.24)';
      if(opt.tooltip.borderWidth===undefined)opt.tooltip.borderWidth=1;
      if(!opt.tooltip.textStyle)opt.tooltip.textStyle={};
      if(opt.tooltip.textStyle.color===undefined)opt.tooltip.textStyle.color=tc;
      if(opt.tooltip.textStyle.fontSize===undefined)opt.tooltip.textStyle.fontSize=fsSM;
      if(opt.tooltip.textStyle.fontFamily===undefined)opt.tooltip.textStyle.fontFamily=fontUI;
      if(opt.tooltip.extraCssText===undefined)opt.tooltip.extraCssText='backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);border-radius:8px;padding:8px 10px;';
      if(!opt.tooltip.axisPointer)opt.tooltip.axisPointer={};
      /* 去掉滚动/悬浮时的带状高亮，统一为细线指示 */
      if(opt.tooltip.axisPointer.type==='shadow'||opt.tooltip.axisPointer.type==='cross'){
        opt.tooltip.axisPointer.type='line';
      }
      if(!opt.tooltip.axisPointer.lineStyle)opt.tooltip.axisPointer.lineStyle={};
      if(opt.tooltip.axisPointer.lineStyle.color===undefined)opt.tooltip.axisPointer.lineStyle.color=dk?'rgba(143,193,255,0.52)':'rgba(47,114,214,0.42)';
      if(opt.tooltip.axisPointer.lineStyle.width===undefined)opt.tooltip.axisPointer.lineStyle.width=1;
      if(!opt.tooltip.axisPointer.label)opt.tooltip.axisPointer.label={};
      opt.tooltip.axisPointer.label.show=false;
      if(opt.tooltip.axisPointer.shadowStyle&&typeof opt.tooltip.axisPointer.shadowStyle==='object'){
        opt.tooltip.axisPointer.shadowStyle.color='rgba(0,0,0,0)';
      }
    }
    if(opt.legend){
      var legends=Array.isArray(opt.legend)?opt.legend:[opt.legend];
      legends.forEach(function(lg){
        if(!lg||typeof lg!=='object')return;
        if(!lg.textStyle)lg.textStyle={};
        if(isFrosted||lg.textStyle.color===undefined)lg.textStyle.color=tc;
        if(lg.textStyle.fontSize===undefined)lg.textStyle.fontSize=fsSM;
        if(lg.textStyle.fontFamily===undefined)lg.textStyle.fontFamily=fontUI;
        if(!lg.pageTextStyle)lg.pageTextStyle={};
        if(isFrosted||lg.pageTextStyle.color===undefined)lg.pageTextStyle.color=tc;
        if(isFrosted||lg.pageIconColor===undefined)lg.pageIconColor=tc;
        if(isFrosted||lg.pageIconInactiveColor===undefined)lg.pageIconInactiveColor='rgba(36,50,72,0.36)';
        if(isFrosted||lg.inactiveColor===undefined)lg.inactiveColor='rgba(36,50,72,0.46)';
        if(lg.selectorLabel&&typeof lg.selectorLabel==='object'){
          if(!lg.selectorLabel.color||isFrosted)lg.selectorLabel.color=tc;
        }
        if(lg.type===undefined)lg.type='scroll';
      });
      opt.legend=Array.isArray(opt.legend)?legends:legends[0];
    }
    function styleTitle(tt){
      if(!tt||typeof tt!=='object')return;
      if(!tt.textStyle)tt.textStyle={};
      if(isFrosted||tt.textStyle.color===undefined)tt.textStyle.color=ttc;
      if(tt.textStyle.fontSize===undefined)tt.textStyle.fontSize=fsLG;
      if(tt.textStyle.fontWeight===undefined)tt.textStyle.fontWeight=600;
      if(tt.textStyle.fontFamily===undefined)tt.textStyle.fontFamily=fontUI;
      if(!tt.subtextStyle)tt.subtextStyle={};
      if(isFrosted||tt.subtextStyle.color===undefined)tt.subtextStyle.color=tc;
      if(tt.subtextStyle.fontSize===undefined)tt.subtextStyle.fontSize=fsSM;
      if(tt.subtextStyle.fontFamily===undefined)tt.subtextStyle.fontFamily=fontUI;
      if(tt.itemGap===undefined)tt.itemGap=gapSM;
      if(tt.top===undefined)tt.top=gapSM;
    }
    if(Array.isArray(opt.title))opt.title.forEach(styleTitle);else styleTitle(opt.title);
    function styleAxis(ax){
      if(!ax||typeof ax!=='object')return;
      if(!ax.axisLabel)ax.axisLabel={};
      if(isFrosted||ax.axisLabel.color===undefined)ax.axisLabel.color=tc;
      if(ax.axisLabel.fontSize===undefined)ax.axisLabel.fontSize=fsSM;
      if(ax.axisLabel.fontFamily===undefined)ax.axisLabel.fontFamily=fontUI;
      if(!ax.axisLine)ax.axisLine={};
      if(!ax.axisLine.lineStyle)ax.axisLine.lineStyle={};
      if(isFrosted||ax.axisLine.lineStyle.color===undefined)ax.axisLine.lineStyle.color=lc;
      if(!ax.axisTick)ax.axisTick={};
      if(!ax.axisTick.lineStyle)ax.axisTick.lineStyle={};
      if(isFrosted||ax.axisTick.lineStyle.color===undefined)ax.axisTick.lineStyle.color=lc;
      if(ax.splitLine===undefined)ax.splitLine={lineStyle:{color:split}};
      else if(ax.splitLine&&typeof ax.splitLine==='object'){
        if(!ax.splitLine.lineStyle)ax.splitLine.lineStyle={};
        if(isFrosted||ax.splitLine.lineStyle.color===undefined)ax.splitLine.lineStyle.color=split;
      }
      if(ax.minorSplitLine&&typeof ax.minorSplitLine==='object'){
        if(!ax.minorSplitLine.lineStyle)ax.minorSplitLine.lineStyle={};
        if(isFrosted||ax.minorSplitLine.lineStyle.color===undefined)ax.minorSplitLine.lineStyle.color=split;
      }
      if(ax.nameTextStyle===undefined)ax.nameTextStyle={};
      if(ax.nameTextStyle&&typeof ax.nameTextStyle==='object'){
        if(isFrosted||ax.nameTextStyle.color===undefined)ax.nameTextStyle.color=tc;
        if(ax.nameTextStyle.fontSize===undefined)ax.nameTextStyle.fontSize=fsSM;
        if(ax.nameTextStyle.fontFamily===undefined)ax.nameTextStyle.fontFamily=fontUI;
      }
    }
    if(Array.isArray(opt.xAxis))opt.xAxis.forEach(styleAxis);else styleAxis(opt.xAxis);
    if(Array.isArray(opt.yAxis))opt.yAxis.forEach(styleAxis);else styleAxis(opt.yAxis);
    function styleAxis3D(ax){
      if(!ax||typeof ax!=='object')return;
      if(!ax.axisLabel)ax.axisLabel={};
      if(isFrosted||ax.axisLabel.color===undefined)ax.axisLabel.color=tc;
      if(ax.axisLabel.fontSize===undefined)ax.axisLabel.fontSize=fsSM;
      if(!ax.nameTextStyle)ax.nameTextStyle={};
      if(isFrosted||ax.nameTextStyle.color===undefined)ax.nameTextStyle.color=tc;
      if(ax.nameTextStyle.fontSize===undefined)ax.nameTextStyle.fontSize=fsSM;
      if(ax.nameTextStyle.fontFamily===undefined)ax.nameTextStyle.fontFamily=fontUI;
    }
    styleAxis3D(opt.xAxis3D);
    styleAxis3D(opt.yAxis3D);
    styleAxis3D(opt.zAxis3D);
    if(opt.radar){
      var radars=Array.isArray(opt.radar)?opt.radar:[opt.radar];
      radars.forEach(function(r){
        if(!r||typeof r!=='object')return;
        if(!r.axisName)r.axisName={};
        if(isFrosted||r.axisName.color===undefined)r.axisName.color=tc;
        if(r.axisName.fontSize===undefined)r.axisName.fontSize=fsSM;
        if(!r.splitLine)r.splitLine={lineStyle:{color:lc}};
        if(!r.axisLine)r.axisLine={lineStyle:{color:lc}};
      });
      opt.radar=Array.isArray(opt.radar)?radars:radars[0];
    }
    if(opt.calendar&&typeof opt.calendar==='object'){
      if(!opt.calendar.monthLabel)opt.calendar.monthLabel={};
      if(!opt.calendar.dayLabel)opt.calendar.dayLabel={};
      if(isFrosted||opt.calendar.monthLabel.color===undefined)opt.calendar.monthLabel.color=tc;
      if(isFrosted||opt.calendar.dayLabel.color===undefined)opt.calendar.dayLabel.color=tc;
      if(opt.calendar.monthLabel.fontSize===undefined)opt.calendar.monthLabel.fontSize=fsSM;
      if(opt.calendar.dayLabel.fontSize===undefined)opt.calendar.dayLabel.fontSize=fsXS;
    }
    if(opt.visualMap){
      var vms=Array.isArray(opt.visualMap)?opt.visualMap:[opt.visualMap];
      vms.forEach(function(vm){
        if(!vm||typeof vm!=='object')return;
        if(vm.calculable===undefined)vm.calculable=true;
        if(!vm.textStyle)vm.textStyle={};
        if(isFrosted||vm.textStyle.color===undefined)vm.textStyle.color=tc;
        if(vm.textStyle.fontSize===undefined)vm.textStyle.fontSize=fsSM;
      });
      opt.visualMap=Array.isArray(opt.visualMap)?vms:vms[0];
    }
    if(opt.grid&&typeof opt.grid==='object'){
      if(opt.grid.top===undefined)opt.grid.top=gapMD*2;
      if(opt.grid.bottom===undefined)opt.grid.bottom=gapMD*2;
    }
    function cleanLabelStyle(lb){
      if(!lb||typeof lb!=='object')return;
      if(lb.color===undefined)lb.color=tc;
      if(lb.fontSize===undefined)lb.fontSize=fsSM;
      if(lb.fontFamily===undefined)lb.fontFamily=fontUI;
      lb.textBorderWidth=0;
      lb.textBorderColor='transparent';
      if(lb.textShadowBlur===undefined)lb.textShadowBlur=0;
    }
    if(Array.isArray(opt.series)){
      opt.series.forEach(function(s){
        if(!s||typeof s!=='object')return;
        cleanLabelStyle(s.label);
        if(s.emphasis&&typeof s.emphasis==='object')cleanLabelStyle(s.emphasis.label);
        if(s.type==='line'){
          if(s.smooth===undefined)s.smooth=true;
          if(s.symbol===undefined)s.symbol='circle';
          if(s.symbolSize===undefined)s.symbolSize=6;
          if(!s.lineStyle)s.lineStyle={};
          if(s.lineStyle.width===undefined)s.lineStyle.width=2;
        }else if(s.type==='bar'){
          if(!s.itemStyle)s.itemStyle={};
          if(s.itemStyle.borderRadius===undefined)s.itemStyle.borderRadius=[4,4,0,0];
        }else if(s.type==='pie'){
          if(s.avoidLabelOverlap===undefined)s.avoidLabelOverlap=true;
          if(!s.labelLine)s.labelLine={};
          if(s.labelLine.length===undefined)s.labelLine.length=10;
          if(s.labelLine.length2===undefined)s.labelLine.length2=8;
        }else if(s.type==='tree'){
          if(s.top===undefined)s.top=60;
          if(s.bottom===undefined)s.bottom=30;
          if(s.left===undefined)s.left=80;
          if(s.right===undefined)s.right=200;
          if(s.orient===undefined)s.orient='LR';
          if(s.symbolSize===undefined)s.symbolSize=10;
        }else if(s.type==='treemap'){
          if(s.top===undefined)s.top=50;
          if(s.bottom===undefined)s.bottom=10;
          if(s.left===undefined)s.left=10;
          if(s.right===undefined)s.right=10;
          if(!s.breadcrumb)s.breadcrumb={show:true,bottom:5};
        }else if(s.type==='sunburst'){
          if(!s.radius)s.radius=['8%','92%'];
          if(!s.label)s.label={rotate:'radial',fontSize:10};
          if(!s.emphasis)s.emphasis={focus:'ancestor'};
        }else if(s.type==='graph'){
          if(!s.emphasis)s.emphasis={focus:'adjacency',lineStyle:{width:3}};
        }else if(s.type==='lines'){
          if(!s.effect)s.effect={show:true,period:4,trailLength:0.2,symbol:'arrow',symbolSize:8};
          if(!s.lineStyle)s.lineStyle={width:2,opacity:0.6,curveness:0.3};
        }else if(s.type==='radar'){
          if(!s.areaStyle)s.areaStyle={opacity:0.15};
          if(!s.lineStyle)s.lineStyle={width:2};
        }
      });
    }
    /* 对齐 echarts_charts_demo 的关键布局差异 */
    if(chartType==='scatter'){
      opt.legend=opt.legend||{};
      opt.legend.top=40;
      opt.grid={left:60,right:30,top:80,bottom:50};
    }else if(chartType==='tree'){
      if(Array.isArray(opt.series)&&opt.series[0]){opt.series[0].top=60;opt.series[0].bottom=30;opt.series[0].left=80;opt.series[0].right=200;}
    }else if(chartType==='treemap'){
      if(Array.isArray(opt.series)&&opt.series[0]){opt.series[0].top=50;opt.series[0].bottom=10;opt.series[0].left=10;opt.series[0].right=10;}
    }else if(chartType==='sunburst'){
      if(Array.isArray(opt.series)&&opt.series[0]&&!opt.series[0].levels){
        opt.series[0].levels=[{}, {r0:'8%',r:'25%'}, {r0:'25%',r:'46%'}, {r0:'46%',r:'70%'}, {r0:'70%',r:'92%'}];
      }
    }else if(chartType==='radarMulti'){
      if(opt.legend&&typeof opt.legend==='object')opt.legend.top=30;
    }else if(chartType==='calendar'){
      opt.calendar=opt.calendar||{};
      if(opt.calendar.top===undefined)opt.calendar.top=60;
      if(opt.calendar.left===undefined)opt.calendar.left=50;
      if(opt.calendar.right===undefined)opt.calendar.right=30;
      /* 不设 bottom —— 让 cellSize 决定日历本体高度，避免被撑开留白 */
      opt.calendar.cellSize=Array.isArray(opt.calendar.cellSize)?opt.calendar.cellSize:[14,14];
    }else if(chartType==='scrollLegend'){
      opt.legend=opt.legend||{};
      opt.legend.type='scroll';
      if(opt.legend.selector===undefined)opt.legend.selector=[{type:'all',title:'全选'},{type:'inverse',title:'反选'}];
    }else if(chartType==='timelineLine'&&opt.baseOption){
      var bo=opt.baseOption;
      bo.legend=bo.legend||{};
      bo.legend.type='scroll';
      if(bo.legend.top===undefined)bo.legend.top=55;
      bo.grid=bo.grid||{};
      if(bo.grid.top===undefined)bo.grid.top=90;
      if(bo.grid.bottom===undefined)bo.grid.bottom=65;
      if(!bo.dataZoom)bo.dataZoom=[{type:'inside',start:0,end:100}];
    }
    if(opt.baseOption&&typeof opt.baseOption==='object'){
      opt.baseOption=applyChartsDemoStyle(opt.baseOption,chartType);
    }
    if(Array.isArray(opt.options)){
      opt.options=opt.options.map(function(item){
        return (item&&typeof item==='object')?applyChartsDemoStyle(item,chartType):item;
      });
    }
    return opt;
  }
  /* 交互优先: 保留图表默认交互能力 */
  function stabilizeOption(opt, chartType){
    if(!opt||typeof opt!=='object')return opt;
    opt=applyChartsDemoStyle(opt,chartType);
    /* 通过 DBG 开关做最小侵入排查 */
    if(DBG.disable_tooltip&&opt.tooltip&&typeof opt.tooltip==='object'){
      opt.tooltip.show=false;
      opt.tooltip.triggerOn='none';
    }
    if(DBG.disable_emphasis){
      if(opt.geo&&typeof opt.geo==='object'){
        if(!opt.geo.emphasis||typeof opt.geo.emphasis!=='object')opt.geo.emphasis={};
        opt.geo.emphasis.disabled=true;
      }
      if(Array.isArray(opt.series)){
        opt.series.forEach(function(s){
          if(!s||typeof s!=='object')return;
          if(!s.emphasis||typeof s.emphasis!=='object')s.emphasis={};
          s.emphasis.disabled=true;
          if(s.hoverAnimation!==undefined)s.hoverAnimation=false;
        });
      }
    }
    if(Array.isArray(opt.series)){
      opt.series.forEach(function(s){
        if(!s||typeof s!=='object')return;
        if(s.type==='line'&&s.smooth===undefined)s.smooth=true;
        if(DBG.disable_ripple&&s.type==='effectScatter'){
          s.type='scatter';
          if(s.rippleEffect)delete s.rippleEffect;
        }
      });
    }
    return opt;
  }
  function geoBase(){
    var u=ui();
    return{
      map:'beijing',roam:!DBG.disable_map_roam,zoom:1.05,
      label:{show:true,fontSize:9,color:u.geoLabelColor},
      itemStyle:{areaColor:u.geoArea,borderColor:u.geoBorder,borderWidth:1},
      emphasis:{itemStyle:{areaColor:u.geoEmphArea,borderColor:u.geoEmphBorder},
                label:{color:u.titleColor,fontSize:11}}
    };
  }

  /* ──────── 图表类型注册表 ──────── */
  var CT={
    map_density:{
      name:'观测密度地图',icon:'&#x1f5fa;&#xfe0f;',w:6,h:5,minW:3,minH:3,
      build:function(){
        var u=ui(),pal=u.colorPalette||[];
        var grad=(pal.length>=3)?[u.geoArea].concat(pal.slice(0,4)):['#0B1437','#1B3A6B','#2B6A9E','#4992FF','#7CFFB2'];
        return{
          backgroundColor:'transparent',
          tooltip:{trigger:'item',confine:true},
          visualMap:{min:20,max:800,left:10,bottom:10,text:['密','疏'],calculable:true,
            inRange:{color:grad},textStyle:{color:u.textColor,fontSize:10}},
          geo:geoBase(),
          series:[{type:'map',map:'beijing',geoIndex:0,data:DATA.density,
            itemStyle:{areaColor:u.geoArea,borderColor:u.geoBorder}}]
        };
      }
    },
    map_scatter:{
      name:'拍摄点位地图',icon:'&#x1f4cd;',w:6,h:5,minW:3,minH:3,
      build:function(){
        var u=ui();
        return{
          backgroundColor:'transparent',
          tooltip:{trigger:'item',confine:true,formatter:function(p){return'拍摄数: '+p.value[2]}},
          geo:geoBase(),
          series:[{type:'effectScatter',coordinateSystem:'geo',data:DATA.scatter,
            encode:{value:2},symbolSize:function(v){return Math.max(4,v[2]/8)},
            rippleEffect:{brushType:'stroke',scale:3},
            itemStyle:{shadowBlur:10,shadowColor:'rgba(73,146,255,0.4)'}}]
        };
      }
    },
    map_heatmap:{
      name:'观鸟热力地图',icon:'&#x1f525;',w:6,h:5,minW:3,minH:3,
      build:function(){
        var u=ui(),pal=u.colorPalette||[];
        var hg=(pal.length>=4)?[u.geoArea,pal[0],pal[2]||pal[1],pal[3]||pal[1],pal[1]]
          :['#313695','#4575b4','#74add1','#fee090','#f46d43','#d73027'];
        return{
          backgroundColor:'transparent',
          tooltip:{confine:true},
          visualMap:{min:1,max:100,left:10,bottom:10,text:['热','冷'],calculable:true,
            inRange:{color:hg},textStyle:{color:u.textColor,fontSize:10}},
          geo:geoBase(),
          series:[{type:'heatmap',coordinateSystem:'geo',data:DATA.heatmap,pointSize:14,blurSize:20}]
        };
      }
    },
    map_graph:{
      name:'观鸟路线图',icon:'&#x1f517;',w:6,h:5,minW:3,minH:3,
      build:function(){
        var u=ui();
        return{
          backgroundColor:'transparent',
          tooltip:{confine:true},
          geo:geoBase(),
          series:[{type:'graph',coordinateSystem:'geo',
            data:DATA.graphNodes,links:DATA.graphLinks,
            symbol:'circle',label:{show:true,position:'right',fontSize:9,color:u.textColor},
            lineStyle:{width:1.5,curveness:.2,opacity:.7},
            edgeSymbol:['none','arrow'],edgeSymbolSize:8,
            itemStyle:{shadowBlur:8}}]
        };
      }
    },
    bar:{
      name:'鸟种数量柱状图',icon:'&#x1f4ca;',w:6,h:4,minW:3,minH:3,
      build:function(){
        var u=ui(),tc=u.textColor||'#9aa6bf',dk=u.dark,pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B'];
        var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981';
        var names=(DATA.barNames||[]).slice(0,10);
        var vals=(DATA.barValues||[]).slice(0,names.length);
        var grad={
          type:'linear',x:0,y:0,x2:0,y2:1,
          colorStops:[
            {offset:0,color:p0},
            {offset:1,color:withAlpha(p0,dk?0.38:0.62)}
          ]
        };
        return{
          backgroundColor:'transparent',
          title:{text:'鸟种观测 TOP10',subtext:'近30天累计观测热度',left:12,top:8},
          tooltip:{trigger:'axis',confine:true,axisPointer:{type:'line'}},
          grid:{left:62,right:18,top:56,bottom:42},
          xAxis:{type:'category',data:names,
            axisLabel:{fontSize:10,rotate:28,interval:0,color:tc},
            axisLine:{lineStyle:{color:withAlpha(p0,dk?0.30:0.26)}}},
          yAxis:{type:'value',name:'观测数',
            nameTextStyle:{color:tc,padding:[0,0,0,4]},
            splitLine:{lineStyle:{color:withAlpha(p0,dk?0.16:0.12)}},
            axisLabel:{color:tc,fontSize:10}},
          series:[{type:'bar',data:vals,barMaxWidth:24,
            itemStyle:{borderRadius:[6,6,0,0],color:grad},
            emphasis:{itemStyle:{color:p1}}}]
        };
      }
    },
    pie:{
      name:'分类占比饼图',icon:'&#x1f967;',w:4,h:4,minW:3,minH:3,
      build:function(){
        var u=ui();
        return{
          backgroundColor:'transparent',
          tooltip:{trigger:'item',confine:true,formatter:'{b}: {c} ({d}%)'},
          legend:{bottom:5,textStyle:{color:u.textColor,fontSize:10},type:'scroll'},
          series:[{type:'pie',radius:['30%','65%'],center:['50%','45%'],data:DATA.pie,
            label:{show:false,color:u.textColor,textBorderWidth:0,textBorderColor:'transparent',textShadowBlur:0},
            emphasis:{label:{show:true,fontSize:13,fontWeight:'bold',color:u.textColor,textBorderWidth:0,textBorderColor:'transparent',textShadowBlur:0}},
            itemStyle:{borderRadius:6,borderColor:'transparent',borderWidth:2}}]
        };
      }
    },
    line:{
      name:'月度趋势折线图',icon:'&#x1f4c8;',w:6,h:4,minW:3,minH:3,
      build:function(){
        var u=ui(),tc=u.textColor||'#9aa6bf',dk=u.dark;
        var m=DATA.lineMonths||[];
        function area(c0,c1){return {type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:c0},{offset:1,color:c1}]};}
        return{
          backgroundColor:'transparent',
          title:{text:'鸟类活跃趋势',subtext:'观测/拍摄/新增鸟种',left:12,top:8},
          tooltip:{trigger:'axis',confine:true,axisPointer:{type:'line'}},
          legend:{top:30,left:12,textStyle:{color:tc,fontSize:10},type:'scroll'},
          grid:{left:52,right:18,top:64,bottom:34},
          xAxis:{type:'category',data:m,boundaryGap:false,
            axisLabel:{color:tc,fontSize:10},
            axisLine:{lineStyle:{color:dk?'rgba(163,188,235,0.30)':'rgba(49,89,163,0.26)'}}},
          yAxis:{type:'value',splitLine:{lineStyle:{color:dk?'rgba(163,188,235,0.16)':'rgba(49,89,163,0.12)'}},
            axisLabel:{color:tc,fontSize:10}},
          series:[
            {name:'观测次数',type:'line',smooth:true,symbol:'circle',symbolSize:5,data:DATA.lineObserve,
              lineStyle:{width:2,color:'#3B82F6'},itemStyle:{color:'#3B82F6'},areaStyle:{color:area('rgba(59,130,246,0.20)','rgba(59,130,246,0.02)')}},
            {name:'拍摄数量',type:'line',smooth:true,symbol:'circle',symbolSize:5,data:DATA.linePhoto,
              lineStyle:{width:2,color:'#10B981'},itemStyle:{color:'#10B981'},areaStyle:{color:area('rgba(16,185,129,0.16)','rgba(16,185,129,0.02)')}},
            {name:'新增鸟种',type:'line',smooth:true,symbol:'circle',symbolSize:5,data:DATA.lineSpecies,
              lineStyle:{width:2,color:'#F59E0B'},itemStyle:{color:'#F59E0B'},areaStyle:{color:area('rgba(245,158,11,0.16)','rgba(245,158,11,0.02)')}}
          ]
        };
      }
    },
    gauge:{
      name:'仪表盘',icon:'&#x1f3af;',w:6,h:5,minW:3,minH:3,
      build:function(){
        var u=ui(),tc=u.textColor||'#ccc',dk=u.dark;
        var pal=u.colorPalette||['#4992FF','#7CFFB2','#FDDD60','#FF6E76','#58D9F9','#05C091'];
        var p0=pal[0]||'#4992FF',p1=pal[1]||'#7CFFB2',p2=pal[2]||'#FDDD60',p3=pal[3]||'#FF6E76',p4=pal[4]||'#58D9F9';
        /* 分阶段小仪表使用高差异色，避免主题色过近导致辨识度下降 */
        var stageCols=[
          pal[4]||'#38BDF8', /* 清晨 */
          pal[1]||'#22C55E', /* 上午 */
          pal[2]||'#F59E0B', /* 下午 */
          pal[3]||'#EF4444'  /* 傍晚 */
        ];
        var trk=dk?'rgba(255,255,255,0.08)':'rgba(0,0,0,0.06)';
        var photos=Math.floor(Math.random()*150+30);
        var sObs=Math.floor(Math.random()*38+60),sPhoto=Math.floor(Math.random()*45+50),sCover=Math.floor(Math.random()*50+40);
        var sp1=Math.floor(Math.random()*17+8),sp2=Math.floor(Math.random()*15+5),sp3=Math.floor(Math.random()*12+3),sp4=Math.floor(Math.random()*16+6);
        var bSpec=Math.floor(Math.random()*45+40),bSpd=Math.floor(Math.random()*35+5),bAct=Math.floor(Math.random()*40+55);
        function ring(r,w,c0,c1,val,nm,dOff,tOff){
          return {type:'gauge',center:['18%','44%'],radius:r,min:0,max:100,startAngle:90,endAngle:-270,
            axisLine:{lineStyle:{width:w,color:[[1,trk]]}},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},pointer:{show:false},
            progress:{show:true,width:w,roundCap:true,itemStyle:{color:{type:'linear',x:0,y:0,x2:1,y2:0,colorStops:[{offset:0,color:c0},{offset:1,color:c1}]}}},
            detail:{valueAnimation:true,formatter:'{value}',fontSize:14,fontWeight:'bold',offsetCenter:dOff,color:c1},
            title:{show:true,offsetCenter:tOff,fontSize:9,color:tc},data:[{value:val,name:nm}]};
        }
        function spd(cx,cy,clr,val,nm){
          return {type:'gauge',center:[cx,cy],radius:'11%',min:0,max:30,startAngle:210,endAngle:-30,
            axisLine:{lineStyle:{width:8,color:[[val/30,clr],[1,trk]]}},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},
            pointer:{length:'60%',width:3,itemStyle:{color:clr}},anchor:{show:true,size:5,itemStyle:{color:clr}},
            detail:{valueAnimation:true,formatter:'{value}',fontSize:14,fontWeight:'bold',offsetCenter:[0,'60%'],color:clr},
            title:{show:true,offsetCenter:[0,'90%'],fontSize:10,color:tc},data:[{value:val,name:nm}]};
        }
        function btm(cx,c0,c1,val,nm,fmt,mx){
          return {type:'gauge',center:[cx,'86%'],radius:'13%',min:0,max:mx||100,startAngle:90,endAngle:-270,
            axisLine:{lineStyle:{width:10,color:[[1,trk]]}},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},pointer:{show:false},
            progress:{show:true,width:10,roundCap:true,itemStyle:{color:{type:'linear',x:0,y:0,x2:1,y2:0,colorStops:[{offset:0,color:c0},{offset:1,color:c1}]}}},
            detail:{valueAnimation:true,formatter:fmt,fontSize:16,fontWeight:'bold',offsetCenter:[0,0],color:tc},
            title:{show:true,offsetCenter:[0,'140%'],fontSize:11,color:tc},data:[{value:val,name:nm}]};
        }
        return {backgroundColor:'transparent',
          title:[{text:'今日拍鸟数据面板',left:'center',top:5},
            {text:'得分环',left:'18%',top:'16%',textAlign:'center',textStyle:{fontSize:12,color:tc}},
            {text:'阶段速度(张/h)',left:'83%',top:'16%',textAlign:'center',textStyle:{fontSize:12,color:tc}}],
          series:[
            ring('26%',10,p0,p4,sObs,'观测',[0,'-18%'],[0,'-34%']),
            ring('19%',10,p1,p0,sPhoto,'摄影',[0,'5%'],[0,'-10%']),
            ring('12%',10,p3,p2,sCover,'覆盖',[0,'42%'],[0,'24%']),
            {type:'gauge',center:['50%','44%'],radius:'28%',min:0,max:200,startAngle:225,endAngle:-45,
              axisLine:{lineStyle:{width:16,color:[[0.3,p4],[0.6,p1],[0.85,p2],[1,p3]]}},
              pointer:{length:'55%',width:5,itemStyle:{color:'auto',shadowColor:'rgba(0,0,0,0.3)',shadowBlur:5,shadowOffsetY:2}},
              anchor:{show:true,size:14,showAbove:true,itemStyle:{borderWidth:2,borderColor:dk?'#555':'#aaa',color:dk?'#222':'#fff'}},
              axisTick:{distance:-16,length:5,lineStyle:{color:dk?'#666':'#999',width:1}},
              splitLine:{distance:-18,length:12,lineStyle:{color:dk?'#777':'#999',width:2}},
              axisLabel:{color:tc,distance:26,fontSize:10,formatter:function(v){if(v%50===0)return v;return ''}},
              progress:{show:true,width:16,roundCap:true},
              detail:{valueAnimation:true,formatter:'{value} 张',fontSize:24,fontWeight:'bold',offsetCenter:[0,'65%'],color:'inherit'},
              title:{show:true,offsetCenter:[0,'85%'],fontSize:13,color:tc},data:[{value:photos,name:'今日照片'}]},
            spd('76%','30%',stageCols[0],sp1,'清晨'),spd('90%','30%',stageCols[1],sp2,'上午'),
            spd('76%','58%',stageCols[2],sp3,'下午'),spd('90%','58%',stageCols[3],sp4,'傍晚'),
            btm('18%',p4,p0,bSpec,'鸟种完成率','{value}%'),
            btm('50%',p1,p0,bSpd,'拍摄速度','{value} 张/h',60),
            btm('82%',p2,p3,bAct,'活跃度','{value} 分')
          ]};
      }
    },
    bird_list:{
      name:'鸟名列表',icon:'&#x1f9fe;',w:4,h:5,minW:2,minH:3,
      build:function(){
        var u=ui(),tc=u.textColor||'#9aa6bf',dk=u.dark,names=(DATA.birdNames||[]).slice(0,16);
        var pal=u.colorPalette||['#3B82F6','#10B981'],p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981';
        var vals=names.map(function(_,i){return names.length-i+rnd(0,2);});
        var mx=Math.max.apply(null,vals.concat([1]));
        return{
          backgroundColor:'transparent',
          title:{text:'高频鸟名榜',subtext:'实时识别热度',left:12,top:8},
          tooltip:{trigger:'axis',axisPointer:{type:'none'},formatter:function(p){var d=(p&&p[0])||{};return (d.name||'')+'<br/>热度: '+(d.value||0);}},
          grid:{left:12,right:14,top:56,bottom:10,containLabel:true},
          xAxis:{type:'value',show:false,max:mx+2},
          yAxis:{
            type:'category',
            data:names,
            inverse:true,
            axisTick:{show:false},
            axisLine:{show:false},
            axisLabel:{color:tc,fontSize:12,margin:10}
          },
          series:[{
            type:'bar',
            data:vals,
            barWidth:14,
            itemStyle:{
              color:{
                type:'linear',x:0,y:0,x2:1,y2:0,
                colorStops:[
                  {offset:0,color:withAlpha(p0,dk?0.28:0.44)},
                  {offset:1,color:withAlpha(p1,dk?0.22:0.36)}
                ]
              },
              borderColor:withAlpha(p0,dk?0.28:0.26),
              borderWidth:1,borderRadius:10
            },
            label:{show:true,position:'right',color:tc,fontSize:10,formatter:'{c}'},
            emphasis:{itemStyle:{color:withAlpha(p0,dk?0.34:0.52)}}
          }]
        };
      }
    }
  };

  /* ──────── 扩展图表(对齐 echarts_charts_demo 可添加类型) ──────── */
  function rnd(a,b){return Math.floor(Math.random()*(b-a+1))+a}
  function months12(){return ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月']}
  function withAlpha(color,a){
    if(!color||typeof color!=='string')return 'rgba(59,130,246,'+a+')';
    var c=color.trim();
    if(c.indexOf('rgba(')===0){
      return c.replace(/rgba\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*[\d.]+\)/,'rgba($1,$2,$3,'+a+')');
    }
    if(c.indexOf('rgb(')===0){
      return c.replace(/rgb\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)/,'rgba($1,$2,$3,'+a+')');
    }
    if(c.charAt(0)==='#'){
      var h=c.slice(1);
      if(h.length===3)h=h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
      if(h.length===6){
        var r=parseInt(h.slice(0,2),16),g=parseInt(h.slice(2,4),16),b=parseInt(h.slice(4,6),16);
        if(isFinite(r)&&isFinite(g)&&isFinite(b))return 'rgba('+r+','+g+','+b+','+a+')';
      }
    }
    return c;
  }
  var EXT_CT={
    scatter:{
      name:'散点图',icon:'&#x1f535;',w:6,h:4,minW:3,minH:3,
      build:function(){
        var names=['大山雀','喜鹊','麻雀','苍鹭','红隼','绿头鸭'];
        var ss=names.map(function(n){
          var pts=[];for(var i=0;i<18;i++)pts.push([rnd(1,11),rnd(10,220)]);
          return {name:n,type:'scatter',data:pts,symbolSize:function(v){return Math.max(5,v[1]/15)}};
        });
        return {backgroundColor:'transparent',tooltip:{trigger:'item'},legend:{type:'scroll',top:4},
          grid:{left:50,right:16,top:36,bottom:28},xAxis:{type:'value',name:'体重(g)'},yAxis:{type:'value',name:'频次'},series:ss};
      }
    },
    tree:{name:'树图',icon:'&#x1f333;',w:6,h:5,minW:3,minH:3,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',dk=u.dark,pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#6366F1'];
      var orders=['雀形目','雁形目','鹰形目','鹳形目'],species=['大山雀','麻雀','喜鹊','绿头鸭','苍鹭','红隼','白头鹎','北红尾鸲','银喉长尾山雀','戴胜'];
      var children=orders.map(function(o,oi){
        var kids=[],n=rnd(2,4);
        for(var i=0;i<n;i++){
          kids.push({name:species[rnd(0,species.length-1)],value:rnd(12,120),itemStyle:{color:pal[(oi+i+1)%pal.length]}});
        }
        return {name:o,itemStyle:{color:pal[oi%pal.length]},children:kids};
      });
      return {backgroundColor:'transparent',
        title:{text:'鸟类分类树',subtext:'目 -> 物种结构',left:12,top:8,subtextStyle:{color:tc,opacity:0.78}},
        tooltip:{trigger:'item',formatter:function(p){return p.name+(p.value?('<br/>观测值: '+p.value):'');}},
        series:[{type:'tree',data:[{name:'北京观鸟记录',children:children}],top:58,bottom:22,left:70,right:170,
          orient:'LR',symbol:'circle',symbolSize:9,
          lineStyle:{color:dk?'rgba(148,163,184,0.36)':'rgba(71,98,141,0.34)',width:1.2,curveness:0.35},
          label:{position:'left',verticalAlign:'middle',align:'right',fontSize:11,color:tc},
          leaves:{label:{position:'right',align:'left',color:tc,fontSize:11}},
          emphasis:{focus:'descendant'},
          expandAndCollapse:true,initialTreeDepth:2,animationDuration:500}]};
    }},
    treemap:{name:'矩形树图',icon:'&#x1f9e9;',w:6,h:5,minW:3,minH:3,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#6366F1','#14B8A6'];
      function mk(name,base,idx){
        return {name:name,value:rnd(base,base+220),itemStyle:{color:pal[idx%pal.length]},children:[
          {name:name+'-常见',value:rnd(40,120),itemStyle:{color:pal[(idx+1)%pal.length]}},
          {name:name+'-稀有',value:rnd(12,70),itemStyle:{color:pal[(idx+2)%pal.length]}},
          {name:name+'-迁徙',value:rnd(20,90),itemStyle:{color:pal[(idx+3)%pal.length]}}
        ]};
      }
      return {backgroundColor:'transparent',
        title:{text:'鸟类分群矩形树图',subtext:'类型规模与结构占比',left:12,top:8,subtextStyle:{color:tc,opacity:0.78}},
        tooltip:{formatter:function(p){return p.name+': '+(p.value||0)+' 次';}},
        series:[{type:'treemap',top:54,bottom:10,left:10,right:10,nodeClick:false,breadcrumb:{show:false},
          label:{show:true,formatter:'{b}',fontSize:11,color:'#0f172a'},
          upperLabel:{show:true,height:20,color:tc,fontSize:11},
          itemStyle:{gapWidth:3,borderColor:'rgba(255,255,255,0.22)',borderWidth:1,borderRadius:8},
          levels:[{itemStyle:{borderColor:'transparent',borderWidth:0,gapWidth:4}},
                  {itemStyle:{borderColor:'rgba(255,255,255,0.26)',borderWidth:1,gapWidth:3},upperLabel:{show:true}},
                  {itemStyle:{borderColor:'rgba(255,255,255,0.18)',borderWidth:1,gapWidth:2}}],
          data:[mk('雀形目',220,0),mk('鹰形目',120,1),mk('雁形目',150,2),mk('涉禽类',130,3)]}]};
    }},
    sunburst:{name:'旭日图',icon:'&#x2600;&#xfe0f;',w:6,h:5,minW:3,minH:3,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',dk=u.dark,pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#8B5CF6','#14B8A6','#EC4899'];
      /* 确保至少 3 个色用于 3 个目 */
      var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981',p2=pal[2]||'#F59E0B';
      var branchPal=[p0,p1,p2];
      var borderBase=dk?'rgba(255,255,255,0.12)':'rgba(0,0,0,0.08)';
      /* ── 层级透明度：从内到外递减（中心饱和、外圈清淡） ── */
      var lvlAlpha=[1, dk?0.88:0.92, dk?0.68:0.76, dk?0.50:0.60, dk?0.36:0.46];
      var orders=['雀形目','鹰形目','雁形目'];
      var familyMap={'雀形目':['鹟科','鸦科','百灵科'],'鹰形目':['鹰科','隼科','鹗科'],'雁形目':['雁科','鸭科','天鹅科']};
      var generaMap={'鹟科':['山雀属','鹊鸲属'],'鸦科':['喜鹊属','松鸦属'],'百灵科':['百灵属','云雀属'],'鹰科':['鹰属','雕属'],'隼科':['隼属','矛隼属'],'鹗科':['鹗属'],'雁科':['雁属','天鹅属'],'鸭科':['鸭属','潜鸭属'],'天鹅科':['天鹅属','疣鼻属']};
      var speciesPool=['大山雀','麻雀','绿头鸭','红隼','苍鹭','白鹭','斑嘴鸭','喜鹊','松鸦','百灵','云雀','金雕','游隼','翠鸟','白鹳'];
      function ri(arr){return arr[rnd(0,arr.length-1)]}
      var data=orders.map(function(o,oi){
        var base=branchPal[oi%branchPal.length];
        var fams=familyMap[o]||['科A','科B'];
        var fKids=fams.map(function(f,fi){
          var gens=generaMap[f]||['属A','属B'];
          var gKids=gens.map(function(g,gi){
            var sKids=[];
            for(var si=0;si<rnd(2,3);si++){
              sKids.push({name:ri(speciesPool),value:rnd(30,140),
                itemStyle:{color:withAlpha(base,lvlAlpha[4])}});
            }
            return {name:g,children:sKids,
              itemStyle:{color:withAlpha(base,lvlAlpha[3])}};
          });
          return {name:f,children:gKids,
            itemStyle:{color:withAlpha(base,lvlAlpha[2])}};
        });
        return {name:o,children:fKids,
          itemStyle:{color:withAlpha(base,lvlAlpha[1])}};
      });
      return {backgroundColor:'transparent',
        title:{text:'鸟类分类旭日图',subtext:'目 \u2192 科 \u2192 属 \u2192 种',left:12,top:8,subtextStyle:{color:tc,opacity:0.72}},
        tooltip:{confine:true,formatter:function(p){
          var path=p.treePathInfo?p.treePathInfo.map(function(n){return n.name}).filter(Boolean).join(' \u203a '):'';
          return '<b>'+p.name+'</b><br/>'+(path?'<span style="opacity:.6;font-size:11px">'+path+'</span><br/>':'')+'观测: '+(p.value||0)+' 次';}},
        series:[{type:'sunburst',data:data,center:['50%','55%'],radius:['8%','88%'],sort:null,nodeClick:'rootToNode',
          label:{rotate:'radial',fontSize:10,color:dk?'rgba(255,255,255,0.88)':'rgba(30,41,59,0.88)',
            textBorderWidth:0,textBorderColor:'transparent',textShadowBlur:0},
          itemStyle:{borderWidth:1.5,borderColor:borderBase,borderRadius:3},
          emphasis:{focus:'ancestor',
            itemStyle:{shadowBlur:16,shadowOffsetY:2,shadowColor:dk?'rgba(0,0,0,0.45)':'rgba(0,0,0,0.18)',
              borderColor:dk?'rgba(255,255,255,0.28)':'rgba(0,0,0,0.14)',borderWidth:2}},
          levels:[
            {/* center */},
            {r0:'8%',r:'24%',label:{fontSize:13,fontWeight:'bold',color:dk?'#fff':'#1e293b'},
              itemStyle:{borderWidth:2.5,borderColor:dk?'rgba(255,255,255,0.18)':'rgba(0,0,0,0.10)',shadowBlur:6,shadowColor:'rgba(0,0,0,0.08)'}},
            {r0:'24%',r:'44%',label:{fontSize:11},
              itemStyle:{borderWidth:1.8,borderColor:dk?'rgba(255,255,255,0.14)':'rgba(0,0,0,0.07)'}},
            {r0:'44%',r:'66%',label:{fontSize:9},
              itemStyle:{borderWidth:1.2,borderColor:dk?'rgba(255,255,255,0.10)':'rgba(0,0,0,0.05)'}},
            {r0:'66%',r:'88%',label:{fontSize:8,color:dk?'rgba(255,255,255,0.70)':'rgba(30,41,59,0.60)'},
              itemStyle:{borderWidth:0.8,borderColor:dk?'rgba(255,255,255,0.06)':'rgba(0,0,0,0.03)'}}
          ]}]};
    }},
    radar:{name:'基础雷达图',icon:'&#x1f4e1;',w:5,h:4,minW:3,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#8B5CF6'];
      var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981',p2=pal[2]||'#F59E0B';
      var dims=['观测次数','拍摄数量','鸟种数','稀有度','出行天数','器材评分'];
      var ind=dims.map(function(n){return {name:n,max:100}});
      var sp=['大山雀','喜鹊','苍鹭','红隼','绿头鸭'];
      var ss=sp.map(function(n){return {name:n,value:dims.map(function(){return rnd(20,100)})};});
      return {backgroundColor:'transparent',title:{text:'鸟种综合观测雷达图',left:'center',top:10},
        tooltip:{trigger:'item'},legend:{data:sp,top:40,textStyle:{color:tc}},
        radar:{center:['50%','58%'],radius:'60%',indicator:ind,axisName:{color:tc,fontSize:11},
          splitArea:{areaStyle:{color:[withAlpha(p0,0.03),withAlpha(p0,0.08)]}},
          splitLine:{lineStyle:{color:withAlpha(p0,dk?0.22:0.16)}},
          axisLine:{lineStyle:{color:withAlpha(p0,dk?0.28:0.20)}}},
        series:[{type:'radar',data:ss,areaStyle:{opacity:0.15},lineStyle:{width:2},emphasis:{areaStyle:{opacity:0.3},lineStyle:{width:3}}}]};
    }},
    radarCustom:{name:'自定义雷达图',icon:'&#x1f6f0;&#xfe0f;',w:5,h:4,minW:3,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#8B5CF6'];
      var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981';
      var dims=['光线条件','构图水平','对焦精度','曝光控制','后期处理','耐心指数','伪装技巧','器材运用'];
      var ind=dims.map(function(n){return {name:n,max:100}});
      var v1=dims.map(function(){return rnd(55,95)}),v2=dims.map(function(){return rnd(30,82)});
      var grad1={type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:withAlpha(p0,0.55)},{offset:1,color:withAlpha(p0,0.05)}]};
      var grad2={type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:withAlpha(p1,0.50)},{offset:1,color:withAlpha(p1,0.05)}]};
      return {backgroundColor:'transparent',tooltip:{trigger:'item'},legend:{data:['本月','上月'],top:40,textStyle:{color:tc}},
        radar:{center:['50%','58%'],radius:'58%',startAngle:90,shape:'circle',indicator:ind,splitNumber:5,
          axisName:{color:tc,fontSize:11},splitArea:{show:true,areaStyle:{color:[withAlpha(p0,0.02),withAlpha(p0,0.06)]}},
          splitLine:{lineStyle:{color:withAlpha(p0,dk?0.20:0.12)}},
          axisLine:{lineStyle:{color:withAlpha(p0,dk?0.25:0.16)}}},
        series:[{type:'radar',data:[
          {name:'本月',value:v1,symbol:'circle',symbolSize:6,lineStyle:{width:2,color:p0,shadowColor:withAlpha(p0,0.50),shadowBlur:8},areaStyle:{color:grad1},itemStyle:{color:p0,borderColor:'#fff',borderWidth:1}},
          {name:'上月',value:v2,symbol:'diamond',symbolSize:6,lineStyle:{width:2,color:p1,type:'dashed'},areaStyle:{color:grad2},itemStyle:{color:p1,borderColor:'#fff',borderWidth:1}}
        ],emphasis:{areaStyle:{opacity:0.5}}}]};
    }},
    radarStudio:{name:'自定义雷达图-工作室',icon:'&#x1f3a8;',w:6,h:4,minW:3,minH:3,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',pal=u.colorPalette||['#3B82F6','#10B981'];
      var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981';
      var dims=['构图','光影','色彩','叙事','清晰度','时机'];
      var ind=dims.map(function(n){return {name:n,max:100}});
      function mk(min,max){return dims.map(function(){return rnd(min,max)})}
      return {backgroundColor:'transparent',
        title:{text:'摄影工作室能力雷达',subtext:'个人/团队维度评分',left:12,top:8},
        legend:{top:32,left:12,data:['个人','团队'],textStyle:{color:tc}},
        tooltip:{trigger:'item'},
        radar:{center:['52%','58%'],radius:'62%',shape:'circle',splitNumber:5,indicator:ind,
          axisName:{color:tc,fontSize:11},
          splitArea:{areaStyle:{color:[withAlpha(p0,0.03),withAlpha(p0,0.07)]}},
          splitLine:{lineStyle:{color:withAlpha(p0,0.22)}},
          axisLine:{lineStyle:{color:withAlpha(p0,0.26)}}},
        series:[{type:'radar',data:[
          {name:'个人',value:mk(58,95),lineStyle:{width:2,color:p0},areaStyle:{color:withAlpha(p0,0.20)}},
          {name:'团队',value:mk(50,90),lineStyle:{width:2,color:p1},areaStyle:{color:withAlpha(p1,0.16)}}
        ]}]
      };
    }},
    radarContrast:{name:'自定义雷达图-对比',icon:'&#x1f3af;',w:6,h:4,minW:3,minH:3,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#64748B'];
      var p0=pal[2]||pal[0]||'#F59E0B',p1=pal[3]||pal[1]||'#64748B';
      var dims=['清晨','上午','中午','下午','傍晚','夜拍'];
      var ind=dims.map(function(n){return {name:n,max:100}});
      var a=dims.map(function(){return rnd(40,95)});
      var b=dims.map(function(){return rnd(35,88)});
      return {backgroundColor:'transparent',
        title:{text:'时段表现对比雷达',subtext:'本周 vs 上周',left:12,top:8},
        legend:{top:32,left:12,data:['本周','上周'],textStyle:{color:tc}},
        tooltip:{trigger:'item'},
        radar:{center:['52%','58%'],radius:'62%',splitNumber:5,indicator:ind,
          axisName:{color:tc,fontSize:11},
          splitArea:{areaStyle:{color:[withAlpha(p0,0.03),withAlpha(p0,0.07)]}},
          splitLine:{lineStyle:{color:withAlpha(p0,0.20)}},
          axisLine:{lineStyle:{color:withAlpha(p0,0.24)}}},
        series:[{type:'radar',data:[
          {name:'本周',value:a,symbol:'circle',symbolSize:5,lineStyle:{width:2,color:p0},areaStyle:{color:withAlpha(p0,0.18)}},
          {name:'上周',value:b,symbol:'diamond',symbolSize:5,lineStyle:{width:2,color:p1,type:'dashed'},areaStyle:{color:withAlpha(p1,0.14)}}
        ]}]
      };
    }},
    radarMulti:{name:'多雷达图',icon:'&#x1f4f6;',w:7,h:5,minW:4,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B'];
      var p0=pal[0]||'#3B82F6';
      var i1=['观测次数','照片数','鸟种数','出行天数','行程公里'].map(function(n){return {name:n,max:100}});
      var i2=['画质','构图','光影','色彩','清晰度','创意'].map(function(n){return {name:n,max:100}});
      var i3=['城区','郊区','湿地','山地','公园','农田'].map(function(n){return {name:n,max:100}});
      function rv(it){return it.map(function(){return rnd(30,95)})}
      var rs={splitArea:{areaStyle:{color:[withAlpha(p0,0.02),withAlpha(p0,0.06)]}},
              splitLine:{lineStyle:{color:withAlpha(p0,dk?0.20:0.12)}},
              axisLine:{lineStyle:{color:withAlpha(p0,dk?0.26:0.16)}},
              axisName:{color:tc,fontSize:10}};
      return {backgroundColor:'transparent',
        title:[{text:'多维度拍鸟数据雷达',left:'center',top:5},
               {text:'活跃度',left:'16%',top:'28%',textAlign:'center',textStyle:{fontSize:13,color:tc}},
               {text:'作品质量',left:'50%',top:'28%',textAlign:'center',textStyle:{fontSize:13,color:tc}},
               {text:'场景分布',left:'84%',top:'28%',textAlign:'center',textStyle:{fontSize:13,color:tc}}],
        tooltip:{trigger:'item'},legend:{data:['摄影师A','摄影师B','摄影师C'],top:30,textStyle:{color:tc}},
        radar:[
          Object.assign({center:['16%','62%'],radius:'30%',indicator:i1},rs),
          Object.assign({center:['50%','62%'],radius:'30%',indicator:i2,shape:'circle'},rs),
          Object.assign({center:['84%','62%'],radius:'30%',indicator:i3},rs)
        ],
        series:[
          {type:'radar',radarIndex:0,data:[{name:'摄影师A',value:rv(i1),areaStyle:{opacity:0.2}},{name:'摄影师B',value:rv(i1),areaStyle:{opacity:0.2}},{name:'摄影师C',value:rv(i1),areaStyle:{opacity:0.2}}]},
          {type:'radar',radarIndex:1,data:[{name:'摄影师A',value:rv(i2),areaStyle:{opacity:0.2}},{name:'摄影师B',value:rv(i2),areaStyle:{opacity:0.2}},{name:'摄影师C',value:rv(i2),areaStyle:{opacity:0.2}}]},
          {type:'radar',radarIndex:2,data:[{name:'摄影师A',value:rv(i3),areaStyle:{opacity:0.2}},{name:'摄影师B',value:rv(i3),areaStyle:{opacity:0.2}},{name:'摄影师C',value:rv(i3),areaStyle:{opacity:0.2}}]}
        ]};
    }},
    calendar:{name:'日历图',icon:'&#x1f4c5;',w:7,h:3,minW:4,minH:2,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#8B5CF6'];
      var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981',p2=pal[2]||'#F59E0B',p3=pal[3]||'#8B5CF6';
      var d=[];for(var m=1;m<=12;m++){var days=new Date(2025,m,0).getDate();for(var i=1;i<=days;i++){var ds='2025-'+(m<10?'0'+m:m)+'-'+(i<10?'0'+i:i);d.push([ds,rnd(6,95)])}}
      return {backgroundColor:'transparent',
        title:{text:'年度观测热力日历',subtext:'2025 每日活跃度',left:12,top:8,subtextStyle:{color:tc,opacity:0.78}},
        tooltip:{position:'top',formatter:function(p){return p.data[0]+'<br/>活跃度: '+p.data[1];}},
        visualMap:{min:0,max:100,orient:'horizontal',left:18,right:18,top:162,text:['高','低'],calculable:true,
          textStyle:{color:tc},
          inRange:{color:[withAlpha(p0,0.08),withAlpha(p0,0.32),p0,p1]}},
        calendar:{top:56,left:40,right:20,range:'2025',cellSize:[14,14],
          splitLine:{lineStyle:{color:'rgba(148,163,184,0.2)',width:1}},
          itemStyle:{borderWidth:0.6,borderColor:'rgba(148,163,184,0.24)'},
          yearLabel:{show:false},
          monthLabel:{nameMap:'cn',color:tc},
          dayLabel:{firstDay:1,nameMap:'cn',color:tc}},
        series:[{type:'heatmap',coordinateSystem:'calendar',data:d}]};
    }},
    calendarH:{name:'横向日历图',icon:'&#x1f4c6;',w:8,h:3,minW:4,minH:3,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B','#8B5CF6'];
      var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981',p2=pal[2]||'#F59E0B',p3=pal[3]||'#8B5CF6';
      function getVirtualData(year){
        var date=+echarts.time.parse(year+'-01-01');
        var end=+echarts.time.parse((+year+1)+'-01-01');
        var dayTime=3600*24*1000;
        var data=[];
        for(var time=date;time<end;time+=dayTime){
          data.push([
            echarts.time.format(time,'{yyyy}-{MM}-{dd}',false),
            Math.floor(Math.random()*9800+200)
          ]);
        }
        return data;
      }
      return {
        backgroundColor:'transparent',
        title:{text:'横向年度热力日历',subtext:'按周展开，观察季节节奏',left:12,top:8,subtextStyle:{color:tc,opacity:0.78}},
        tooltip:{formatter:function(p){return p.data[0]+'<br/>记录值: '+p.data[1];}},
        visualMap:{
          min:0,max:10000,
          type:'continuous',
          orient:'horizontal',
          left:12,right:12,top:34,textStyle:{color:tc},
          inRange:{color:[withAlpha(p0,0.08),withAlpha(p0,0.30),p0,p1]}
        },
        calendar:{
          top:68,
          left:30,
          right:30,
          bottom:8,
          cellSize:[15,15],
          range:'2025',
          splitLine:{show:true,lineStyle:{color:'rgba(148,163,184,0.2)',width:1}},
          itemStyle:{borderWidth:0.6,borderColor:'rgba(148,163,184,0.24)'},
          yearLabel:{show:false},
          monthLabel:{nameMap:'cn',color:tc},
          dayLabel:{nameMap:'cn',color:tc}
        },
        series:{
          type:'heatmap',
          coordinateSystem:'calendar',
          data:getVirtualData('2025')
        }
      };
    }},
    customGauge:{name:'自定义仪表',icon:'&#x1f527;',w:4,h:4,minW:3,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc';
      var pal=u.colorPalette||['#4992FF','#7CFFB2','#FDDD60','#FF6E76','#58D9F9','#05C091'];
      var p0=pal[0]||'#4992FF',p1=pal[1]||'#7CFFB2',p2=pal[2]||'#FDDD60',p3=pal[3]||'#FF6E76',p4=pal[4]||'#58D9F9';
      var OR=95,IR=78,PIR=24,IPR=62,MAX=200;
      var GC=[
        {c0:p0,c1:p4,tc:p4,bg:dk?'#151530':'#fff',sh:withAlpha(p4,0.34),lb:'拍摄得分',sub:'综合摄影能力评估'},
        {c0:p1,c1:p4,tc:p1,bg:dk?'#152015':'#fff',sh:withAlpha(p1,0.34),lb:'鸟种图鉴',sub:'已记录鸟种覆盖率'},
        {c0:p2,c1:p3,tc:p2,bg:dk?'#201a10':'#fff',sh:withAlpha(p2,0.34),lb:'照片精选',sub:'作品入选精华比例'},
        {c0:p3,c1:p0,tc:p3,bg:dk?'#1a1028':'#fff',sh:withAlpha(p3,0.34),lb:'观鸟时长',sub:'本月野外观测时长'}
      ];
      var trkColor=dk?'rgba(255,255,255,0.06)':'rgba(0,0,0,0.05)';
      function toP(cx,cy,r,rd){return [Math.cos(rd)*r+cx,-Math.sin(rd)*r+cy]}
      function mkPts(cx,cy,pr){return [toP(cx,cy,OR,pr),toP(cx,cy,OR,pr+Math.PI*0.03),toP(cx,cy,PIR,pr)]}
      function mkTxt(v){return ((v/MAX)*100).toFixed(0)+'%'}
      function renderItem(params,api){
        var idx=api.value(2),cfg=GC[idx];
        var vr=api.value(1),coords=api.coord([api.value(0),vr]),pr=coords[3];
        var cx=params.coordSys.cx,cy=params.coordSys.cy;
        var ticks=[];
        for(var t=0;t<12;t++){
          var a=t*Math.PI/6,c=Math.cos(a),s=Math.sin(a);
          ticks.push({type:'line',
            shape:{x1:cx+c*(OR+3),y1:cy-s*(OR+3),x2:cx+c*(OR+10),y2:cy-s*(OR+10)},
            style:{stroke:dk?'rgba(255,255,255,0.12)':'rgba(0,0,0,0.08)',lineWidth:t%3===0?2:1}});
        }
        return {type:'group',children:[
          {type:'sector',shape:{cx:cx,cy:cy,r:OR,r0:IR,startAngle:0,endAngle:-Math.PI*2},style:{fill:trkColor}},
          {type:'sector',shape:{cx:cx,cy:cy,r:OR,r0:IR,startAngle:0,endAngle:-pr,transition:'endAngle',enterFrom:{endAngle:0}},
            style:{fill:{type:'linear',x:0,y:0,x2:1,y2:1,colorStops:[{offset:0,color:cfg.c0},{offset:1,color:cfg.c1}]}}},
          {type:'polygon',shape:{points:mkPts(cx,cy,pr)},style:{fill:cfg.c1},
            extra:{pr:pr,transition:'pr',enterFrom:{pr:0}},
            during:function(ad){ad.setShape('points',mkPts(cx,cy,ad.getExtra('pr')))}},
          {type:'circle',shape:{cx:cx,cy:cy,r:IPR},style:{fill:cfg.bg,shadowBlur:25,shadowColor:cfg.sh}},
          {type:'text',extra:{vr:vr,transition:'vr',enterFrom:{vr:0}},
            style:{text:mkTxt(vr),fontSize:30,fontWeight:700,x:cx,y:cy-10,fill:cfg.tc,align:'center',verticalAlign:'middle',enterFrom:{opacity:0}},
            during:function(ad){ad.setStyle('text',mkTxt(ad.getExtra('vr')))}},
          {type:'text',style:{text:cfg.lb,fontSize:13,fontWeight:600,x:cx,y:cy+14,fill:cfg.tc,align:'center',verticalAlign:'middle'}},
          {type:'text',style:{text:cfg.sub,fontSize:10,x:cx,y:cy+30,fill:tc,align:'center',verticalAlign:'middle',opacity:0.7}}
        ].concat(ticks)};
      }
      var pols=[],aAxes=[],rAxes=[],srs=[],dss=[];
      var cens=[['28%','38%'],['72%','38%'],['28%','78%'],['72%','78%']];
      for(var i=0;i<4;i++){
        var val=Math.round(Math.random()*MAX);
        pols.push({center:cens[i],radius:OR});
        aAxes.push({type:'value',startAngle:0,show:false,min:0,max:MAX,polarIndex:i});
        rAxes.push({type:'value',show:false,polarIndex:i});
        dss.push({source:[[1,val,i]]});
        srs.push({type:'custom',coordinateSystem:'polar',polarIndex:i,renderItem:renderItem,
          datasetIndex:i,animationEasing:'quarticInOut',animationDuration:1000,
          animationDurationUpdate:1000,animationEasingUpdate:'quarticInOut'});
      }
      return {backgroundColor:'transparent',
        title:{text:'鸟类摄影指标面板',subtext:'每 3 秒自动刷新',left:'center',top:5,subtextStyle:{color:tc,fontSize:11}},
        tooltip:{},dataset:dss,polar:pols,angleAxis:aAxes,radiusAxis:rAxes,series:srs};
    }},
    customGaugeMini:{name:'自定义仪表-迷你卡',icon:'&#x1f9ed;',w:5,h:3,minW:3,minH:2,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B'];
      var cards=[
        {n:'对焦稳定',v:rnd(65,98),c:pal[0]||'#3B82F6'},
        {n:'跟拍成功',v:rnd(55,94),c:pal[1]||'#10B981'},
        {n:'作品精选率',v:rnd(38,88),c:pal[2]||'#F59E0B'}
      ];
      var series=[];
      cards.forEach(function(it,idx){
        var cx=(18+idx*32)+'%';
        series.push({
          type:'gauge',center:[cx,'58%'],radius:'34%',
          min:0,max:100,startAngle:220,endAngle:-40,
          axisLine:{lineStyle:{width:8,color:[[1,'rgba(148,163,184,0.20)']]}},
          progress:{show:true,width:8,roundCap:true,itemStyle:{color:it.c}},
          pointer:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},
          detail:{valueAnimation:true,formatter:'{value}%',offsetCenter:[0,'10%'],fontSize:16,fontWeight:700,color:it.c},
          title:{show:true,offsetCenter:[0,'95%'],fontSize:11,color:tc},
          data:[{value:it.v,name:it.n}]
        });
      });
      return {backgroundColor:'transparent',title:{text:'核心拍摄指标',left:12,top:8},series:series};
    }},
    customGaugeProgress:{name:'自定义仪表-进度环',icon:'&#x1f4a0;',w:5,h:3,minW:3,minH:2,build:function(){
      var u=ui(),tc=u.textColor||'#9aa6bf',pal=u.colorPalette||['#3B82F6','#10B981','#F59E0B'];
      var p0=pal[0]||'#3B82F6',p1=pal[1]||'#10B981',p2=pal[2]||'#F59E0B';
      var val=rnd(55,96),val2=rnd(45,92),val3=rnd(60,98);
      return {backgroundColor:'transparent',
        title:{text:'任务完成进度',subtext:'观测 / 拍摄 / 整理',left:12,top:8,subtextStyle:{color:tc}},
        series:[
          {type:'gauge',center:['22%','64%'],radius:'44%',startAngle:90,endAngle:-270,min:0,max:100,
            axisLine:{lineStyle:{width:10,color:[[1,'rgba(148,163,184,0.20)']]}},progress:{show:true,width:10,roundCap:true,itemStyle:{color:p0}},
            pointer:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},
            detail:{formatter:'{value}%',fontSize:16,fontWeight:700,color:p0,offsetCenter:[0,0]},title:{show:true,offsetCenter:[0,'110%'],fontSize:11,color:tc},
            data:[{value:val,name:'观测'}]},
          {type:'gauge',center:['50%','64%'],radius:'44%',startAngle:90,endAngle:-270,min:0,max:100,
            axisLine:{lineStyle:{width:10,color:[[1,'rgba(148,163,184,0.20)']]}},progress:{show:true,width:10,roundCap:true,itemStyle:{color:p1}},
            pointer:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},
            detail:{formatter:'{value}%',fontSize:16,fontWeight:700,color:p1,offsetCenter:[0,0]},title:{show:true,offsetCenter:[0,'110%'],fontSize:11,color:tc},
            data:[{value:val2,name:'拍摄'}]},
          {type:'gauge',center:['78%','64%'],radius:'44%',startAngle:90,endAngle:-270,min:0,max:100,
            axisLine:{lineStyle:{width:10,color:[[1,'rgba(148,163,184,0.20)']]}},progress:{show:true,width:10,roundCap:true,itemStyle:{color:p2}},
            pointer:{show:false},axisTick:{show:false},splitLine:{show:false},axisLabel:{show:false},
            detail:{formatter:'{value}%',fontSize:16,fontWeight:700,color:p2,offsetCenter:[0,0]},title:{show:true,offsetCenter:[0,'110%'],fontSize:11,color:tc},
            data:[{value:val3,name:'整理'}]}
        ]};
    }},
    map:{name:'地图',icon:'&#x1f5fa;&#xfe0f;',w:6,h:5,minW:3,minH:3,build:function(){return CT.map_density.build();}},
    lines:{name:'线图',icon:'&#x27a1;&#xfe0f;',w:6,h:5,minW:3,minH:3,build:function(){
      var pts=DATA.scatter.slice(0,18),ls=[];for(var i=0;i<pts.length-1;i++)ls.push({coords:[pts[i].slice(0,2),pts[i+1].slice(0,2)]});
      return {backgroundColor:'transparent',geo:geoBase(),tooltip:{},
        series:[{type:'lines',coordinateSystem:'geo',data:ls,effect:{show:true,period:4,symbol:'arrow',symbolSize:7},lineStyle:{width:2,opacity:.7,curveness:.2}}]};
    }},
    graph:{name:'关系图',icon:'&#x1f517;',w:6,h:4,minW:3,minH:3,build:function(){
      var ns=['大山雀','喜鹊','麻雀','苍鹭','红隼','绿头鸭'].map(function(n){return {name:n,symbolSize:rnd(14,30),value:rnd(10,100)}});
      var lk=[];for(var i=0;i<ns.length;i++){lk.push({source:ns[i].name,target:ns[(i+1)%ns.length].name});if(Math.random()>0.5)lk.push({source:ns[i].name,target:ns[rnd(0,ns.length-1)].name});}
      return {backgroundColor:'transparent',tooltip:{},series:[{type:'graph',layout:'force',roam:true,data:ns,links:lk,label:{show:true,fontSize:10},force:{repulsion:180,edgeLength:[60,140]},lineStyle:{curveness:.2,opacity:.6}}]};
    }},
    geo:{name:'地理坐标图',icon:'&#x1f30d;',w:6,h:5,minW:3,minH:3,build:function(){
      var u=ui();
      return {backgroundColor:'transparent',title:{text:'拍鸟地理热力分布',left:'center',top:10},tooltip:{},
        visualMap:{min:1,max:100,left:20,bottom:20,text:['热','冷'],calculable:true,seriesIndex:[1],
          inRange:{color:['#313695','#74add1','#fee090','#f46d43','#d73027']}},
        geo:{map:'beijing',roam:!DBG.disable_map_roam,zoom:1.1,center:[116.4,39.9],
          label:{show:true,fontSize:10,color:u.geoLabelColor},
          itemStyle:{areaColor:u.geoArea,borderColor:u.geoBorder},
          emphasis:{itemStyle:{areaColor:u.geoEmphArea}}},
        series:[
          {type:'effectScatter',coordinateSystem:'geo',data:DATA.scatter,encode:{value:2},
            symbolSize:function(v){return Math.max(6,v[2]/8)},rippleEffect:{brushType:'stroke',scale:4}},
          {type:'heatmap',coordinateSystem:'geo',data:DATA.heatmap,pointSize:16,blurSize:22}
        ]};
    }},
    geoGraph:{name:'地理关系图',icon:'&#x1f5fa;&#xfe0f;',w:6,h:5,minW:3,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc';
      var sites=[
        {name:'奥森公园',lon:116.395,lat:40.015},{name:'圆明园',lon:116.298,lat:40.010},
        {name:'天坛公园',lon:116.411,lat:39.882},{name:'植物园',lon:116.207,lat:40.002},
        {name:'野鸭湖',lon:115.820,lat:40.380},{name:'翠湖湿地',lon:116.155,lat:40.100},
        {name:'沙河水库',lon:116.310,lat:40.160},{name:'密云水库',lon:116.980,lat:40.480},
        {name:'十三陵水库',lon:116.260,lat:40.260},{name:'怀柔水库',lon:116.620,lat:40.380},
        {name:'房山十渡',lon:115.660,lat:39.680},{name:'百花山',lon:115.570,lat:39.850}
      ];
      var cats=[{name:'公园'},{name:'湿地'},{name:'水库'},{name:'山地'}];
      var cmap={0:0,1:0,2:0,3:0,4:1,5:1,6:2,7:2,8:2,9:2,10:3,11:3};
      var birds=['大山雀','麻雀','喜鹊','苍鹭','红隼','绿头鸭','白头鹎','北红尾鸲','斑嘴鸭','乌鸫','黄鹂','戴胜'];
      var nodes=sites.map(function(s,i){var cnt=rnd(20,95);return {name:s.name,value:[s.lon,s.lat,cnt],symbolSize:Math.max(12,cnt/4),category:cmap[i]||0,bird:birds[i%birds.length],cnt:cnt};});
      var links=[];for(var i=0;i<nodes.length;i++){if(i<nodes.length-1)links.push({source:nodes[i].name,target:nodes[i+1].name,value:rnd(10,60)});if(Math.random()>0.45){var t=rnd(0,nodes.length-1);if(t!==i)links.push({source:nodes[i].name,target:nodes[t].name,value:rnd(6,35)});}}
      links.push({source:'野鸭湖',target:'密云水库',value:80},{source:'密云水库',target:'怀柔水库',value:65},{source:'沙河水库',target:'翠湖湿地',value:55},{source:'奥森公园',target:'圆明园',value:70},{source:'房山十渡',target:'百花山',value:45});
      return {backgroundColor:'transparent',
        title:{text:'北京观鸟站点关系网络',subtext:'节点大小=鸟种数 / 连线粗细=迁移频次',left:'center',top:10,subtextStyle:{color:tc}},
        tooltip:{trigger:'item',formatter:function(p){if(p.dataType==='node')return '<b>'+p.name+'</b><br/>鸟种数: '+p.data.cnt+'<br/>代表鸟种: '+p.data.bird; if(p.dataType==='edge')return p.data.source+' → '+p.data.target+'<br/>迁移频次: '+p.value; return p.name;}},
        legend:{data:['公园','湿地','水库','山地'],top:50,textStyle:{color:tc}},
        geo:{map:'beijing',roam:true,zoom:1.05,center:[116.3,40.0],label:{show:true,fontSize:9,color:dk?'rgba(255,255,255,0.35)':'rgba(0,0,0,0.25)'},itemStyle:{areaColor:u.geoArea,borderColor:u.geoBorder,borderWidth:1},emphasis:{itemStyle:{areaColor:u.geoEmphArea},label:{color:u.titleColor,fontSize:11}}},
        series:[
          {type:'graph',coordinateSystem:'geo',data:nodes,links:links,categories:cats,symbol:'circle',label:{show:true,position:'right',fontSize:10,color:tc},lineStyle:{color:'source',curveness:0.2,opacity:0.7,width:2},edgeSymbol:['none','arrow'],edgeSymbolSize:[0,8],emphasis:{focus:'adjacency',lineStyle:{width:4,opacity:0.9}}},
          {type:'effectScatter',coordinateSystem:'geo',data:nodes.filter(function(n){return n.cnt>60}).map(function(n){return {name:n.name,value:[n.value[0],n.value[1],n.cnt]};}),encode:{value:2},symbolSize:function(v){return Math.max(8,v[2]/5)},showEffectOn:'render',rippleEffect:{brushType:'stroke',scale:4,period:3},itemStyle:{color:dk?'#FDDD60':'#ff9800',shadowBlur:10,shadowColor:dk?'rgba(253,221,96,0.5)':'rgba(255,152,0,0.5)'},zlevel:1}
        ]};
    }},
    scrollLegend:{name:'可滚动图例',icon:'&#x1f4dc;',w:6,h:4,minW:3,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#9aa6bf';
      var prefixes=['大','小','白','黑','灰','红','黄','绿','蓝','褐','棕','银','金','花','斑','纹'];
      var middles=['头','胸','腹','背','翅','尾','嘴','脚','眉','颈','腰','喉'];
      var suffixes=['雀','鹎','鸲','鹟','鸦','鹭','鸭','鹬','鹰','隼','鸮','燕','鸫','鹂','鸠','鸥','鹊','鹤'];
      var used={},legendData=[],seriesData=[];
      for(var i=0;i<50;i++){
        var name='';
        while(!name||used[name]){
          name=prefixes[rnd(0,prefixes.length-1)]+middles[rnd(0,middles.length-1)]+suffixes[rnd(0,suffixes.length-1)];
        }
        used[name]=1;
        legendData.push(name);
        seriesData.push({name:name,value:rnd(10,1010)});
      }
      return {backgroundColor:'transparent',
        title:{text:'可滚动图例 - 鸟种分布',subtext:'支持全选/反选，分页滚动',left:12,top:8,subtextStyle:{color:tc,opacity:0.78}},
        tooltip:{trigger:'item',formatter:'{a} <br/>{b} : {c} 次 ({d}%)'},
        legend:{type:'scroll',orient:'vertical',right:8,top:56,bottom:14,textStyle:{color:tc,fontSize:11},pageTextStyle:{color:tc},
          pageIconColor:dk?'#8FC1FF':'#2F72D6',pageIconInactiveColor:dk?'#444':'#ccc',data:legendData,
          selector:[{type:'all',title:'全选'},{type:'inverse',title:'反选'}],
          selectorLabel:{color:tc,borderColor:dk?'rgba(148,163,184,0.44)':'rgba(71,98,141,0.35)',fontSize:10,borderWidth:1,borderRadius:6,padding:[3,7]}},
        series:[{name:'观测次数',type:'pie',radius:['40%','66%'],center:['36%','58%'],data:seriesData,
          selectedMode:'single',avoidLabelOverlap:true,minAngle:2,
          label:{show:false,color:tc},
          emphasis:{scale:true,label:{show:true,color:tc,formatter:'{b}\\n{d}%'}},
          itemStyle:{borderWidth:1,borderColor:'rgba(255,255,255,0.2)'}}]};
    }},
    timelineLine:{name:'时间轴折线图',icon:'&#x23f2;&#xfe0f;',w:8,h:4,minW:4,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc';
      var months=months12(),years=['2019','2020','2021','2022','2023','2024','2025'];
      var species=['大山雀','喜鹊','麻雀','北红尾鸲','白头鹎','苍鹭','红隼','绿头鸭'];
      var yearData={};
      years.forEach(function(y,yi){
        yearData[y]={};
        species.forEach(function(s){
          var base=30+yi*12+Math.random()*20;
          yearData[y][s]=months.map(function(_,mi){
            var seasonal=1.0;
            if(mi>=2&&mi<=4)seasonal=1.6+Math.random()*0.4;
            else if(mi>=8&&mi<=10)seasonal=1.4+Math.random()*0.3;
            else if(mi===0||mi===11)seasonal=0.5+Math.random()*0.2;
            return Math.floor(base*seasonal+Math.random()*30);
          });
        });
      });
      var options=years.map(function(y){
        var series=species.map(function(s){
          return {name:s,type:'line',smooth:true,symbol:'circle',symbolSize:6,lineStyle:{width:2},areaStyle:{opacity:0.08},emphasis:{focus:'series',lineStyle:{width:3}},data:yearData[y][s]};
        });
        var totalByMonth=months.map(function(_,mi){var sum=0;species.forEach(function(s){sum+=yearData[y][s][mi]});return sum;});
        var yearTotal=totalByMonth.reduce(function(a,b){return a+b},0);
        var peakMonth=months[totalByMonth.indexOf(Math.max.apply(null,totalByMonth))];
        return {title:[{text:y+'年 鸟类月度观测趋势',left:'center',top:8},{text:'年度总量: '+yearTotal+' 次  |  峰值月份: '+peakMonth,left:'center',top:32,textStyle:{fontSize:12,fontWeight:'normal',color:tc,opacity:0.7}}],series:series};
      });
      return {baseOption:{backgroundColor:'transparent',
          timeline:{axisType:'category',data:years,autoPlay:true,playInterval:2500,left:'10%',right:'10%',bottom:10,height:40,
            controlStyle:{showPlayBtn:true,showPrevBtn:true,showNextBtn:true,color:dk?'#58D9F9':'#4992ff',borderColor:dk?'#58D9F9':'#4992ff'},
            lineStyle:{color:dk?'#444':'#ccc'},itemStyle:{color:dk?'#58D9F9':'#4992ff',borderColor:dk?'#58D9F9':'#4992ff'},
            checkpointStyle:{color:dk?'#FDDD60':'#ff9800',borderColor:dk?'#FDDD60':'#ff9800',symbolSize:12},
            label:{color:tc,fontSize:12},
            progress:{lineStyle:{color:dk?'#58D9F9':'#4992ff'},itemStyle:{color:dk?'#58D9F9':'#4992ff'}}},
          tooltip:{trigger:'axis',axisPointer:{type:'cross',label:{backgroundColor:dk?'#333':'#aaa'}}},
          legend:{type:'scroll',data:species,top:55,textStyle:{color:tc},pageIconColor:dk?'#8FC1FF':'#2F72D6',pageIconInactiveColor:dk?'#444':'#ccc',pageTextStyle:{color:tc}},
          grid:{left:55,right:30,top:90,bottom:65},
          xAxis:{type:'category',data:months,boundaryGap:false,axisLabel:{color:tc},axisLine:{lineStyle:{color:dk?'#444':'#ccc'}},splitLine:{show:false}},
          yAxis:{type:'value',name:'观测次数',nameTextStyle:{color:tc},axisLabel:{color:tc},splitLine:{lineStyle:{color:dk?'rgba(255,255,255,0.06)':'rgba(0,0,0,0.06)'}}},
          series:species.map(function(s){return {name:s,type:'line'}}),
          dataZoom:[{type:'inside',start:0,end:100}],
          toolbox:{show:true,right:20,top:55,feature:{dataZoom:{yAxisIndex:'none'},restore:{},saveAsImage:{}},iconStyle:{borderColor:tc}}
        },
        options:options};
    }},
    timelineGallery:{name:'时间轴图片表格',icon:'&#x1f5bc;&#xfe0f;',w:8,h:4,minW:4,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#9aa6bf';
      var months=months12();
      var species=(Array.isArray(DATA.birdNames)&&DATA.birdNames.length?DATA.birdNames.slice(0):['大山雀','喜鹊','麻雀','苍鹭','红隼','绿头鸭','白头鹎','北红尾鸲']);
      if(species.length<10){
        ['大山雀','喜鹊','麻雀','苍鹭','红隼','绿头鸭','白头鹎','北红尾鸲','戴胜','银喉长尾山雀'].forEach(function(n){
          if(species.indexOf(n)<0)species.push(n);
        });
      }
      var orders=['雀形目','鹰形目','雁形目','鹳形目','鸻形目','鹭形目'];
      var palette=(u.colorPalette&&u.colorPalette.length)?u.colorPalette:['#3B82F6','#2563EB','#10B981','#F59E0B','#8B5CF6','#14B8A6'];
      var COLS=4,ROWS=3,TOTAL=COLS*ROWS;
      var colLabels=[],rowLabels=[];
      for(var c=0;c<COLS;c++)colLabels.push('P'+(c+1));
      for(var r=0;r<ROWS;r++)rowLabels.push('R'+(ROWS-r));
      function level(score){
        if(score>=90)return 'S';
        if(score>=80)return 'A';
        if(score>=70)return 'B';
        if(score>=60)return 'C';
        return 'D';
      }
      function genMonth(){
        var items=[];
        for(var i=0;i<TOTAL;i++){
          var sp=species[rnd(0,species.length-1)];
          var od=orders[rnd(0,orders.length-1)];
          var score=rnd(52,99);
          var col=i%COLS,row=ROWS-1-Math.floor(i/COLS);
          var pi=(i+score)%palette.length;
          items.push({
            value:[col,row,score],
            bird:sp,order:od,score:score,
            tint:palette[pi],rank:level(score),
            shots:rnd(18,260),site:['奥森','圆明园','翠湖','野鸭湖','密云'][rnd(0,4)]
          });
        }
        return items;
      }
      var allData={};months.forEach(function(m){allData[m]=genMonth();});

      function renderItem(params,api){
        var pos=api.coord([api.value(0),api.value(1)]);
        var idx=params.dataIndex,d=params.context.__data||[];
        var it=d[idx]||{},score=Number(it.score||0),rank=it.rank||'B',tint=it.tint||'#3B82F6';
        var cw=params.coordSys.width/COLS,ch=params.coordSys.height/ROWS;
        var w=Math.max(74,Math.min(136,cw*0.9)),h=Math.max(58,Math.min(96,ch*0.82));
        var x=pos[0]-w/2,y=pos[1]-h/2;
        var titleColor=(windowStyle==='frosted')?'#111827':tc;
        var badgeBg=(rank==='S'||rank==='A')?'#F59E0B':(rank==='B'?'#3B82F6':'#64748B');
        var cardBg=dk?'rgba(15,23,42,0.52)':'rgba(255,255,255,0.72)';
        return {
          type:'group',
          children:[
            {type:'rect',shape:{x:x,y:y,width:w,height:h,r:10},style:{
              fill:cardBg,stroke:dk?'rgba(148,163,184,0.34)':'rgba(71,98,141,0.24)',lineWidth:1
            }},
            {type:'rect',shape:{x:x+1,y:y+1,width:w-2,height:18,r:[10,10,0,0]},style:{
              fill:tint,opacity:dk?0.28:0.22
            }},
            {type:'rect',shape:{x:x+8,y:y+24,width:w-16,height:h-34,r:7},style:{
              fill:{type:'linear',x:0,y:0,x2:1,y2:1,colorStops:[
                {offset:0,color:tint},
                {offset:1,color:dk?'rgba(15,23,42,0.85)':'rgba(255,255,255,0.68)'}
              ]},
              opacity:0.34
            }},
            {type:'text',style:{
              text:it.bird||'',x:x+9,y:y+4,font:'600 10px "Microsoft YaHei","Segoe UI",sans-serif',
              fill:titleColor,textVerticalAlign:'top'
            }},
            {type:'rect',shape:{x:x+w-28,y:y+4,width:20,height:12,r:6},style:{fill:badgeBg,opacity:0.95}},
            {type:'text',style:{
              text:rank,x:x+w-18,y:y+5,font:'700 9px "Microsoft YaHei","Segoe UI",sans-serif',
              fill:'#fff',textAlign:'center',textVerticalAlign:'top'
            }},
            {type:'text',style:{
              text:score+'分',x:x+10,y:y+h-18,font:'700 12px "Microsoft YaHei","Segoe UI",sans-serif',
              fill:(windowStyle==='frosted')?'#111827':'#f8fafc',textVerticalAlign:'top'
            }}
          ]
        };
      }

      var options=months.map(function(m){
        var d=allData[m],birdSet={};
        d.forEach(function(it){birdSet[it.bird]=1;});
        var birdCount=Object.keys(birdSet).length;
        var avgScore=Math.floor(d.reduce(function(a,b){return a+b.score;},0)/Math.max(1,d.length));
        var topItem=d.slice().sort(function(a,b){return b.score-a.score;})[0]||{};
        return {
          title:[
            {text:m+' 影像作品时间轴画廊',left:12,top:8},
            {text:'本月 '+TOTAL+' 张 | '+birdCount+' 种鸟类 | 均分 '+avgScore+' | TOP: '+(topItem.bird||'-'),left:12,top:32,textStyle:{fontSize:11,fontWeight:'normal',color:tc,opacity:0.8}}
          ],
          series:[{
            type:'custom',
            renderItem:function(params,api){params.context.__data=d;return renderItem(params,api);},
            data:d.map(function(it){return {value:it.value,bird:it.bird,order:it.order,score:it.score,shots:it.shots,site:it.site,rank:it.rank,tint:it.tint};})
          }]
        };
      });

      return {baseOption:{
          backgroundColor:'transparent',
          timeline:{
            axisType:'category',data:months,autoPlay:true,playInterval:2200,left:'8%',right:'8%',bottom:8,height:38,
            checkpointStyle:{color:'#F59E0B',borderColor:'#F59E0B',symbolSize:11,animation:true},
            controlStyle:{showPlayBtn:true,showPrevBtn:true,showNextBtn:true,color:'#3B82F6',borderColor:'#3B82F6'},
            lineStyle:{color:dk?'rgba(148,163,184,0.45)':'rgba(71,98,141,0.35)'},
            itemStyle:{color:'#3B82F6',borderColor:'#3B82F6'},
            label:{color:tc,fontSize:11},
            emphasis:{itemStyle:{color:'#F59E0B'},label:{color:tc,fontWeight:'bold'}},
            progress:{lineStyle:{color:'#2563EB'},itemStyle:{color:'#2563EB'}}
          },
          tooltip:{confine:true,formatter:function(p){
            var d=p.data;if(!d)return '';
            return '<b>'+d.bird+'</b><br/>目: '+d.order+'<br/>评分: '+d.score+' 分<br/>片数: '+d.shots+' 张<br/>地点: '+d.site;
          }},
          grid:{left:58,right:30,top:66,bottom:58},
          xAxis:{type:'category',data:colLabels,axisLabel:{show:false,color:tc},axisLine:{show:false},axisTick:{show:false},
            splitLine:{show:true,lineStyle:{color:dk?'rgba(148,163,184,0.10)':'rgba(71,98,141,0.10)'}}},
          yAxis:{type:'category',data:rowLabels,axisLabel:{show:false,color:tc},axisLine:{show:false},axisTick:{show:false},
            splitLine:{show:true,lineStyle:{color:dk?'rgba(148,163,184,0.10)':'rgba(71,98,141,0.10)'}}},
          series:[{type:'custom',encode:{x:0,y:1}}]
        },
        options:options
      };
    }},
    globe3D:{name:'中国观鸟热力图',icon:'&#x1f30e;',w:8,h:5,minW:4,minH:3,build:function(){
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc';
      if(!(window.echarts&&typeof window.echarts.getMap==='function'&&window.echarts.getMap('china'))){
        return CT.map_heatmap.build();
      }
      var hotspots=[
        [116.40,39.90,'北京',95],[117.20,39.08,'天津',68],[114.51,38.04,'石家庄',52],
        [115.82,40.38,'野鸭湖',88],[116.98,40.48,'密云水库',75],[112.55,37.87,'太原',45],
        [126.63,45.75,'哈尔滨',72],[123.43,41.80,'沈阳',65],[125.32,43.88,'长春',58],
        [121.62,38.92,'大连',80],[131.00,46.63,'兴凯湖',90],[124.35,40.12,'丹东鸭绿江',85],
        [121.47,31.23,'上海',82],[120.15,30.28,'杭州',78],[118.80,32.06,'南京',70],
        [117.28,31.86,'合肥',55],[119.30,26.08,'福州',62],[122.10,30.00,'舟山',87],
        [114.30,30.58,'武汉',76],[112.98,28.23,'长沙',60],[113.65,34.76,'郑州',50],
        [114.07,30.53,'沉湖湿地',92],[111.70,29.05,'洞庭湖',98],[116.00,29.70,'鄱阳湖',99],
        [113.26,23.13,'广州',73],[114.06,22.54,'深圳',70],[110.35,20.02,'海口',82],
        [109.50,18.25,'三亚',78],[104.07,30.67,'成都',74],[102.73,25.04,'昆明',85],
        [100.23,26.87,'丽江',80],[97.13,27.83,'德钦',68],[91.11,29.97,'拉萨',42],
        [108.95,34.26,'西安',60],[87.62,43.79,'乌鲁木齐',48],[97.37,37.37,'青海湖',94],
        [121.52,25.05,'台北',76]
      ];
      var scatterData=hotspots.map(function(h){return {name:h[2],value:[h[0],h[1],h[3]]};});
      var effectData=hotspots.filter(function(h){return h[3]>80}).map(function(h){return {name:h[2],value:[h[0],h[1],h[3]]};});
      var heatData=[];hotspots.forEach(function(h){heatData.push([h[0],h[1],h[3]]);for(var k=0;k<Math.floor(h[3]/20)+1;k++)heatData.push([h[0]+(Math.random()-0.5)*2.2,h[1]+(Math.random()-0.5)*2.2,Math.floor(h[3]*(0.35+Math.random()*0.45))]);});
      var routes=[
        {name:'东亚-澳大利西亚迁飞路线',color:dk?'#58D9F9':'#4992ff',trail:dk?'#FDDD60':'#ff9800',coords:[[126.6,45.8],[121.5,31.2],[113.6,23.1],[109.5,18.3]]},
        {name:'鄱阳湖-洞庭湖候鸟通道',color:dk?'#7CFFB2':'#4caf50',trail:dk?'#7CFFB2':'#4caf50',coords:[[116.0,29.7],[114.3,30.5],[111.7,29.1]]},
        {name:'中亚迁飞路线',color:dk?'#FF6E76':'#e53935',trail:dk?'#FF6E76':'#e53935',coords:[[87.6,43.8],[97.4,37.4],[108.9,34.3],[116.4,39.9]]},
        {name:'环渤海湿地通道',color:dk?'#4992FF':'#1976d2',trail:dk?'#4992FF':'#1976d2',coords:[[121.6,38.9],[117.2,39.1],[116.4,39.9],[115.8,40.4],[117,40.5]]}
      ];
      var linesSeries=routes.map(function(r){var segs=[];for(var i=0;i<r.coords.length-1;i++)segs.push({name:r.name,coords:[r.coords[i],r.coords[i+1]]});return {type:'lines',coordinateSystem:'geo',name:r.name,effect:{show:true,period:4+Math.random()*2,trailLength:0.2,symbol:'arrow',symbolSize:6,color:r.trail},lineStyle:{color:r.color,width:2,opacity:0.6,curveness:0.15},data:segs,zlevel:4};});
      return {backgroundColor:'transparent',
        title:{text:'全国观鸟热力分布',subtext:'散点=站点 | 涟漪=重点站点 | 热力=密度 | 飞线=迁徙路线',left:'center',top:8,textStyle:{color:dk?'#fff':'#eee',fontSize:16},subtextStyle:{color:dk?'rgba(255,255,255,0.55)':'rgba(255,255,255,0.45)'}},
        tooltip:{trigger:'item',formatter:function(p){if(p.seriesType==='effectScatter'||p.seriesType==='scatter')return '<b>'+p.name+'</b><br/>观测热度: '+p.value[2];if(p.seriesType==='lines')return '<b>'+(p.data.name||p.seriesName)+'</b>';return p.name||'';}},
        geo:{map:'china',roam:true,zoom:1.2,center:[105,35],itemStyle:{areaColor:dk?'#0e1b3d':'#1a2a4a',borderColor:dk?'rgba(88,217,249,0.3)':'rgba(47,114,214,0.3)',borderWidth:1},emphasis:{itemStyle:{areaColor:dk?'#1e3870':'#2a5090'},label:{show:true,color:dk?'#58D9F9':'#4992ff',fontSize:12}},label:{show:true,color:dk?'rgba(255,255,255,0.3)':'rgba(0,0,0,0.2)',fontSize:9}},
        visualMap:{show:true,min:0,max:100,calculable:true,orient:'vertical',right:15,bottom:60,text:['高','低'],textStyle:{color:tc},inRange:{color:dk?['rgba(10,20,50,0)','#0d47a1','#1565c0','#1e88e5','#42a5f5','#64ffda','#69f0ae','#b2ff59','#eeff41','#ffca28','#ff5722']:['rgba(20,30,60,0)','#1565c0','#42a5f5','#4fc3f7','#80deea','#a5d6a7','#fff59d','#ffe082','#ffab40','#ff7043']},seriesIndex:[2]},
        legend:{type:'scroll',orient:'vertical',left:10,top:60,bottom:60,textStyle:{color:tc,fontSize:11},pageTextStyle:{color:tc},pageIconColor:dk?'#8FC1FF':'#2F72D6',data:routes.map(function(r){return r.name})},
        series:[
          {type:'scatter',coordinateSystem:'geo',name:'观鸟站点',data:scatterData,encode:{value:2},symbolSize:function(v){return Math.max(6,v[2]/6)},itemStyle:{color:dk?'#58D9F9':'#4992ff',opacity:0.85,shadowBlur:8,shadowColor:dk?'rgba(88,217,249,0.5)':'rgba(73,146,255,0.5)'},zlevel:2},
          {type:'effectScatter',coordinateSystem:'geo',name:'重点站点',data:effectData,encode:{value:2},symbolSize:function(v){return Math.max(10,v[2]/4)},showEffectOn:'render',rippleEffect:{brushType:'stroke',scale:4,period:3,number:2},itemStyle:{color:dk?'#FDDD60':'#ff9800',shadowBlur:12,shadowColor:dk?'rgba(253,221,96,0.6)':'rgba(255,152,0,0.6)'},label:{show:true,position:'right',fontSize:10,color:dk?'#FDDD60':'#ff9800',formatter:function(p){return p.name}},zlevel:3},
          {type:'heatmap',coordinateSystem:'geo',data:heatData,pointSize:12,blurSize:18,zlevel:1}
        ].concat(linesSeries)};
    }},
    bar3D:{name:'3D柱状图',icon:'&#x1f4ca;',w:8,h:5,minW:4,minH:3,build:function(){
      function buildPseudo3D(u,dk,tc,hours,cities,data){
        var usedCities=cities.slice(0,Math.min(6,cities.length));
        if(!usedCities.length)return {backgroundColor:'transparent',title:{text:'3D柱状图',subtext:'无可用数据',left:'center'}};
        var byCity={};
        usedCities.forEach(function(c){byCity[c]=hours.map(function(){return 0;});});
        data.forEach(function(d){
          var hi=d[0],ci=d[1],v=d[2];
          var cName=cities[ci];
          if(byCity[cName])byCity[cName][hi]=v;
        });
        var palette=(u.colorPalette&&u.colorPalette.length)?u.colorPalette:['#4992FF','#7CFFB2','#FDDD60','#FF6E76','#58D9F9','#05C091'];
        var series=[];
        usedCities.forEach(function(c,idx){
          var col=palette[idx%palette.length];
          series.push({
            name:c,
            type:'bar',
            barMaxWidth:18,
            data:byCity[c],
            itemStyle:{
              borderRadius:[4,4,0,0],
              color:{
                type:'linear',x:0,y:0,x2:0,y2:1,
                colorStops:[
                  {offset:0,color:col},
                  {offset:1,color:dk?'rgba(255,255,255,0.20)':'rgba(0,0,0,0.15)'}
                ]
              }
            }
          });
          series.push({
            name:c+'-cap',
            type:'pictorialBar',
            symbol:'diamond',
            symbolSize:[18,7],
            symbolOffset:[0,-4],
            symbolPosition:'end',
            z:10,
            tooltip:{show:false},
            itemStyle:{color:col,opacity:0.95},
            data:byCity[c]
          });
        });
        return {
          backgroundColor:'transparent',
          title:{text:'各区分时段观鸟活跃度',subtext:'透明风格兼容: 伪3D渲染',left:'center',top:8,textStyle:{color:dk?'#fff':'#333'},subtextStyle:{color:tc}},
          tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
          legend:{type:'scroll',top:34,textStyle:{color:tc}},
          grid:{left:56,right:24,top:64,bottom:40},
          xAxis:{type:'category',data:hours,axisLabel:{color:tc,interval:0},axisLine:{lineStyle:{color:dk?'#444':'#ccc'}}},
          yAxis:{type:'value',name:'观测数',nameTextStyle:{color:tc},axisLabel:{color:tc},
            splitLine:{lineStyle:{color:dk?'rgba(255,255,255,0.08)':'rgba(0,0,0,0.08)'}}},
          series:series
        };
      }
      if(typeof window.echarts==='undefined'){
        var u0=ui(),tc0=u0.textColor||'#ccc',dk0=u0.dark;
        return {backgroundColor:'transparent',
          title:{text:'各区分时段观鸟活跃度',subtext:'当前环境未启用 echarts-gl，已自动切换为 2D 显示',left:'center',top:8,textStyle:{color:dk0?'#fff':'#333'},subtextStyle:{color:tc0}},
          tooltip:{trigger:'axis'},grid:{left:50,right:18,top:60,bottom:34},
          xAxis:{type:'category',data:DATA.barNames,axisLabel:{rotate:30,color:tc0}},yAxis:{type:'value',axisLabel:{color:tc0},
            splitLine:{lineStyle:{color:dk0?'rgba(255,255,255,0.08)':'rgba(0,0,0,0.08)'}}},
          series:[{type:'bar',data:DATA.barValues}]};
      }
      var u=ui(),dk=u.dark,tc=u.textColor||'#ccc';
      var hours=['6:00','7:00','8:00','9:00','10:00','11:00','12:00','13:00','14:00','15:00','16:00','17:00','18:00','19:00'];
      var cities=DATA.barNames||[];
      var nCities=cities.length,nHours=hours.length,data=[];
      for(var ci=0;ci<nCities;ci++){
        for(var hi=0;hi<nHours;hi++){
          var base=2;
          if(hi<=2||hi>=11)base=8+Math.random()*6;
          else if(hi>=3&&hi<=5)base=12+Math.random()*8;
          else base=3+Math.random()*4;
          data.push([hi,ci,Math.floor(base+Math.random()*5)]);
        }
      }
      var maxVal=Math.max.apply(null,data.map(function(x){return x[2];}));
      var depthPerCity=18,boxDepth=Math.max(80,nCities*depthPerCity),boxWidth=Math.max(160,nHours*12);
      var barSz=Math.max(3,Math.min(10,Math.floor(depthPerCity*0.7)));
      var dist=Math.max(250,180+nCities*8);
      /* QtWebEngine + echarts-gl 在透明材质卡片中常出现黑底, 透明风格下切换到伪3D保证材质可见 */
      var preferPseudo=(bar3DMode==='pseudo')||(bar3DMode==='auto'&&(windowStyle==='transparent'||windowStyle==='acrylic'||windowStyle==='frosted'||windowStyle==='executive'));
      if(preferPseudo){
        return buildPseudo3D(u,dk,tc,hours,cities,data);
      }
      return {backgroundColor:'transparent',
        title:{text:'各区分时段观鸟活跃度',subtext:'X轴=时间 / Y轴=城区 / Z轴=观测数量',left:'center',top:8,textStyle:{color:dk?'#fff':'#333'},subtextStyle:{color:tc}},
        tooltip:{formatter:function(p){var v=p.value;return cities[v[1]]+'<br/>时段: '+hours[v[0]]+'<br/>观测: <b>'+v[2]+'</b> 次';}},
        visualMap:{max:maxVal,calculable:true,orient:'vertical',right:10,top:'middle',text:['多','少'],textStyle:{color:tc},
          inRange:{color:['#313695','#4575b4','#74add1','#abd9e9','#e0f3f8','#ffffbf','#fee090','#fdae61','#f46d43','#d73027','#a50026']}},
        xAxis3D:{type:'category',data:hours,name:'时段',axisLabel:{color:tc,interval:0},nameTextStyle:{color:tc}},
        yAxis3D:{type:'category',data:cities,name:'城区',axisLabel:{color:tc,fontSize:10,interval:0},nameTextStyle:{color:tc}},
        zAxis3D:{type:'value',name:'观测数',axisLabel:{color:tc},nameTextStyle:{color:tc}},
        grid3D:{boxWidth:boxWidth,boxDepth:boxDepth,boxHeight:80,environment:'rgba(0,0,0,0)',
          viewControl:{distance:dist,alpha:25,beta:35,autoRotate:false},
          light:{main:{intensity:1.2,shadow:true,shadowQuality:'high',alpha:40,beta:20},ambient:{intensity:0.4}},
          postEffect:{enable:false},
          temporalSuperSampling:{enable:false}},
        series:[{type:'bar3D',data:data.map(function(item){return {value:[item[0],item[1],item[2]]};}),
          shading:'lambert',barSize:barSz,label:{show:false,fontSize:10,borderWidth:0},
          emphasis:{label:{show:true,fontSize:14,color:(windowStyle==='frosted'?'#1f2430':'#fff'),formatter:function(p){return p.value[2];}},itemStyle:{color:dk?'#FDDD60':'#ff9800'}},
          itemStyle:{opacity:0.9}}]
      };
    }}
  };
  Object.keys(EXT_CT).forEach(function(k){if(!CT[k])CT[k]=EXT_CT[k]});

  /* ──────── 单图模式: 用于多 QWebEngineView 架构 ──────── */
  var sp=new URLSearchParams(window.location.search||'');
  var singleType=sp.get('single');
  var singleTheme=sp.get('theme');
  if(singleTheme&&UI[singleTheme])currentTheme=singleTheme;
  if(singleType&&CT[singleType]){
    var tb=document.getElementById('toolbar');
    if(tb)tb.style.display='none';
    var gridEl=document.getElementById('grid');
    var wrapEl=document.getElementById('gridWrap');
    if(wrapEl){
      wrapEl.style.padding='0';
      wrapEl.style.background='transparent';
      wrapEl.style.overflow='hidden';
    }
    var sid='single_chart';
    gridEl.innerHTML='<div style="position:absolute;right:8px;top:8px;z-index:2000;background:rgba(20,16,50,0.85);border:1px solid rgba(255,255,255,0.15);border-radius:8px;padding:6px 8px;display:flex;align-items:center;gap:8px;color:#eef1fa;font-size:12px">'
      +'<label style="display:flex;align-items:center;gap:4px"><input type="checkbox" id="pauseWhenOut" checked>离开暂停</label>'
      +'<label style="display:flex;align-items:center;gap:4px">静止<input id="idleSec" type="number" min="0" max="60" value="3" style="width:44px;background:#2b2742;color:#eef1fa;border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:2px 4px">秒</label>'
      +'</div>'
      +'<div class="card" style="height:100%;border-radius:0">'
      +'<div class="pause-tag">已暂停</div>'
      +'<div class="card-body" id="'+sid+'" style="width:100%;height:100%;pointer-events:auto"></div>'
      +'</div>';
    applyThemeVars();
    setupRenderPolicyUI(document);
    var sc=echarts.init(document.getElementById(sid),currentTheme);
    sc.setOption(stabilizeOption(CT[singleType].build(),singleType),true);
    enforceCalendarSquareCells(sc,singleType);
    if(singleType==='scrollLegend')bindScrollLegendCenterLabel(sc);
    forceChartTransparent(sc);
    singleChart=sc;
    applyRenderStateToAll();
    window.addEventListener('resize',function(){
      try{sc.resize()}catch(e){}
      try{enforceCalendarSquareCells(sc,singleType)}catch(e){}
    });
    window.addEventListener('mouseenter',function(){userBecameActive();});
    window.addEventListener('mousemove',function(){userBecameActive();});
    window.addEventListener('wheel',function(){userBecameActive();},{passive:true});
    window.addEventListener('keydown',function(){userBecameActive();});
    window.addEventListener('mouseleave',function(){if(pauseWhenOut)setRenderActive(false);});
    scheduleIdlePause();
    return;
  }

  /* ──────── GridStack 初始化 ──────── */
  var grid=GridStack.init({
    column:12,
    cellHeight:80,
    margin:10,
    animate:!DBG.disable_grid_animate,
    float:true,
    handle:'.card-drag',
    removable:false,
    disableOneColumnMode:true,
    acceptWidgets:false
  },'#grid');
  try{
    gridBaseMinRow=(grid&&grid.opts&&grid.opts.minRow)?parseInt(grid.opts.minRow,10)||0:0;
  }catch(e){gridBaseMinRow=0}
  setTimeout(function(){applySquareGridSizing();syncGridHeight()},0);
  grid.on('dragstart',function(){
    gridInteracting=true;
    try{
      if(grid&&typeof grid.getRow==='function'&&typeof grid.minRow==='function'){
        grid.minRow((grid.getRow()||0)+24);
      }
    }catch(e){}
    syncGridHeight();
    setDashGridVisible(true);
    requestAnimationFrame(function(){drawDashGrid()});
    setTimeout(drawDashGrid,30);
  });
  grid.on('drag',function(){
    if(gridInteracting)syncGridHeight();
  });
  grid.on('dragstop',function(){
    gridInteracting=false;
    try{
      if(grid&&typeof grid.minRow==='function')grid.minRow(gridBaseMinRow||0);
    }catch(e){}
    setDashGridVisible(false);
    setTimeout(syncGridHeight,20);
  });
  grid.on('dropped',function(){setDashGridVisible(false)});
  grid.on('resizestart',function(){
    gridInteracting=true;
    try{
      if(grid&&typeof grid.getRow==='function'&&typeof grid.minRow==='function'){
        grid.minRow((grid.getRow()||0)+24);
      }
    }catch(e){}
    syncGridHeight();
    setDashGridVisible(true);
    requestAnimationFrame(function(){drawDashGrid()});
    setTimeout(drawDashGrid,30);
  });
  grid.on('resize',function(){
    if(gridInteracting)syncGridHeight();
  });
  grid.on('resizestop',function(){
    gridInteracting=false;
    try{
      if(grid&&typeof grid.minRow==='function')grid.minRow(gridBaseMinRow||0);
    }catch(e){}
    setDashGridVisible(false);
    setTimeout(syncGridHeight,20);
  });
  /* 兜底: 某些场景 stop 事件可能未触发 */
  window.addEventListener('mouseup',function(){
    gridInteracting=false;
    try{if(grid&&typeof grid.minRow==='function')grid.minRow(gridBaseMinRow||0)}catch(e){}
    setDashGridVisible(false);setTimeout(syncGridHeight,20)
  });
  window.addEventListener('pointerup',function(){
    gridInteracting=false;
    try{if(grid&&typeof grid.minRow==='function')grid.minRow(gridBaseMinRow||0)}catch(e){}
    setDashGridVisible(false);setTimeout(syncGridHeight,20)
  });
  window.addEventListener('blur',function(){
    gridInteracting=false;
    try{if(grid&&typeof grid.minRow==='function')grid.minRow(gridBaseMinRow||0)}catch(e){}
    setDashGridVisible(false);setTimeout(syncGridHeight,20)
  });

  /* ──────── 添加图表 ──────── */
  function bindScrollLegendCenterLabel(chart){
    if(!chart)return;
    try{
      if(chart.__slLegendHandler)chart.off('legendselectchanged',chart.__slLegendHandler);
      if(chart.__slPieHandler)chart.off('pieselectchanged',chart.__slPieHandler);
      chart.__slLegendHandler=null;
      chart.__slPieHandler=null;
      chart.setOption({graphic:[{id:'sl_center_label',$action:'remove'}]},false,false);
    }catch(e){}
  }
  function enforceCalendarSquareCells(inst, chartType){
    if(!inst||chartType!=='calendar')return;
    try{
      var w=Math.max(120,inst.getWidth?inst.getWidth():0);
      var h=Math.max(120,inst.getHeight?inst.getHeight():0);
      var opt=inst.getOption()||{};
      var cal=Array.isArray(opt.calendar)?opt.calendar[0]:opt.calendar;
      if(!cal||typeof cal!=='object')return;
      var left=(typeof cal.left==='number')?cal.left:40;
      var right=(typeof cal.right==='number')?cal.right:20;
      /* ---- 布局参数 ---- */
      var titleH=40;   /* 标题区高度 */
      var vmH=24;       /* visualMap 高度 */
      var gap=4;        /* 日历与 visualMap 间距 */
      /* 宽度决定格子边长；高度做上限保护 */
      var availW=Math.max(80,w-left-right);
      var maxSideH=Math.max(6,Math.floor((h-titleH-gap-vmH)/7));
      var side=Math.floor(Math.min(availW/54, maxSideH));
      side=Math.max(6,Math.min(24,side));
      /* 内容块（标题+日历+拖动条）整体垂直居中 */
      var calH=side*7;
      var totalH=titleH+calH+gap+vmH;
      var calTop=Math.max(titleH,Math.floor((h-totalH)/2)+titleH);
      /* 修正日历配置 */
      cal.orient='horizontal';
      cal.cellSize=[side,side];
      cal.width=side*54;
      cal.height=calH;
      cal.left=left;
      cal.top=calTop;
      try{delete cal.right;}catch(e){}
      try{delete cal.bottom;}catch(e){}
      /* visualMap 紧贴日历本体下方 */
      var curVm=opt.visualMap;
      var vm=Array.isArray(curVm)?curVm[0]:curVm;
      if(vm&&typeof vm==='object'){
        vm.top=calTop+calH+gap;
        vm.left=left;
        try{delete vm.bottom;}catch(e){}
      }
      /* 标题也动态居上 */
      var curTitle=opt.title;
      var tt=Array.isArray(curTitle)?curTitle[0]:curTitle;
      if(tt&&typeof tt==='object'){
        tt.top=Math.max(2,calTop-titleH);
      }
      /* calendar + visualMap + title 一次性 setOption */
      var patch={};
      patch.calendar=Array.isArray(opt.calendar)?[cal]:cal;
      if(vm)patch.visualMap=Array.isArray(curVm)?[vm]:vm;
      if(tt)patch.title=Array.isArray(curTitle)?[tt]:tt;
      inst.setOption(patch,false,false);
    }catch(e){}
  }

  function addChart(type,pos){
    var ct=CT[type];
    if(!ct)return;
    var id='c_'+(nextId++);
    var content='<div class="card is-loading">'
      +'<div class="pause-tag">已暂停</div>'
      +'<div class="card-header">'
      +'<div class="card-drag"><span class="card-status-dot is-running" data-role="status-dot"></span><span>'+ct.icon+'</span> '+ct.name+'</div>'
      +'<div class="card-close" data-id="'+id+'">&times;</div>'
      +'</div>'
      +'<div class="card-loading"></div>'
      +'<div class="card-body" id="'+id+'" style="width:100%;height:100%"></div>'
      +'</div>';
    var opts={id:id,w:(pos&&pos.w)||ct.w,h:(pos&&pos.h)||ct.h,
      minW:ct.minW,minH:ct.minH,content:content};
    if(pos&&pos.x!==undefined){opts.x=pos.x;opts.y=pos.y}
    grid.addWidget(opts);
    updateEmptyState();
    setTimeout(function(){setActiveCard(id)},0);
    /* 等 DOM 就绪后初始化 ECharts */
    setTimeout(function(){
      var el=document.getElementById(id);
      if(!el)return;
      var chart=echarts.init(el,currentTheme);
      charts[id]={instance:chart,type:type};
      /* 新增图表先渲染, finished 后再进入暂停 */
      chartActiveMap[id]=true;
      setChartActive(id,true);
      var firstPaintStart=Date.now();
      var firstPaintFinished=false;
      var pausedAfterFirstPaint=false;
      function pauseAfterFirstPaint(){
        if(pausedAfterFirstPaint)return;
        pausedAfterFirstPaint=true;
        if(!charts[id]||charts[id].instance!==chart)return;
        setCardLoading(id,false);
        setChartActive(id,false);
      }
      function schedulePauseAfterStablePaint(){
        if(pausedAfterFirstPaint||!firstPaintFinished)return;
        var wait=Math.max(0,450-(Date.now()-firstPaintStart));
        setTimeout(pauseAfterFirstPaint,wait);
      }
      try{
        chart.on('finished',function onFirstDone(){
          try{chart.off('finished',onFirstDone)}catch(e){}
          firstPaintFinished=true;
          setTimeout(schedulePauseAfterStablePaint,80);
        });
      }catch(e){}
      chart.setOption(stabilizeOption(ct.build(),type), true);
      enforceCalendarSquareCells(chart,type);
      setTimeout(function(){enforceCalendarSquareCells(chart,type)},120);
      if(type==='scrollLegend')bindScrollLegendCenterLabel(chart);
      forceChartTransparent(chart);
      /* 兜底: 个别图表不触发 finished 时也会在首轮展示后暂停 */
      setTimeout(function(){firstPaintFinished=true;schedulePauseAfterStablePaint();},2000);
      syncGridHeight();
    },60);
    /* 关闭下拉菜单 */
    document.getElementById('addDropdown').classList.remove('open');
  }

  /* ──────── 删除图表 ──────── */
  function removeChart(id){
    if(charts[id]){charts[id].instance.dispose();delete charts[id]}
    clearChartIdleTimer(id);
    delete chartActiveMap[id];
    var el=document.querySelector('.grid-stack-item[gs-id="'+id+'"]');
    if(el)grid.removeWidget(el);
    if(activeCardId===id)setActiveCard(null);
    updateEmptyState();
    setTimeout(syncGridHeight,20);
  }

  /* ──────── 清空 ──────── */
  function clearAllSilent(){
    Object.keys(charts).forEach(function(id){
      if(charts[id]&&charts[id].instance)charts[id].instance.dispose();
      clearChartIdleTimer(id);
    });
    charts={};chartActiveMap={};grid.removeAll();
    setActiveCard(null);
    updateEmptyState();
    setTimeout(syncGridHeight,20);
  }

  /* ──────── Resize 处理 ──────── */
  function resizeAll(){
    Object.keys(charts).forEach(function(id){
      if(charts[id]&&charts[id].instance){
        try{charts[id].instance.resize()}catch(e){}
        try{enforceCalendarSquareCells(charts[id].instance,charts[id].type)}catch(e){}
      }
    });
  }
  grid.on('resizestop',function(){setTimeout(resizeAll,80)});
  grid.on('change',function(){setTimeout(syncGridHeight,40)});
  window.addEventListener('resize',function(){
    applySquareGridSizing();
    clearTimeout(resizeTimer);resizeTimer=setTimeout(resizeAll,200);
    setTimeout(syncGridHeight,80);
  });

  /* ──────── 主题切换 ──────── */
  var customBg=null; /* 用户通过颜色选择器自定义的背景 */
  function applyThemeVars(){
    var u=ui(),dk=u.dark,r=document.documentElement.style;
    var bg=customBg||u.bodyBg;
    document.body.style.background=bg;
    r.setProperty('--bg',bg);
    var cp=document.getElementById('bgColor');
    if(cp)cp.value=bg;
    r.setProperty('--toolbar-bg',dk?'rgba(12,14,26,0.92)':'rgba(255,255,255,0.94)');
    r.setProperty('--toolbar-border',dk?'rgba(255,255,255,0.06)':'rgba(0,0,0,0.06)');
    r.setProperty('--card-bg',dk?'rgba(16,20,38,0.82)':'rgba(255,255,255,0.92)');
    r.setProperty('--card-header-bg',dk?'rgba(22,28,52,0.88)':'rgba(240,243,250,0.94)');
    r.setProperty('--text',dk?'#94a3b8':'#475569');
    r.setProperty('--text-title',dk?'#e2e8f0':'#1e293b');
    r.setProperty('--text-muted',dk?'rgba(148,163,184,0.56)':'rgba(71,85,105,0.56)');
    r.setProperty('--select-bg',dk?'rgba(16,20,38,0.92)':'#f8fafc');
    r.setProperty('--btn-border',dk?'rgba(59,130,246,0.20)':'rgba(59,130,246,0.28)');
    r.setProperty('--menu-bg',dk?'rgba(14,17,32,0.96)':'rgba(255,255,255,0.98)');
    r.setProperty('--grid-dot',dk?'rgba(255,255,255,0.02)':'rgba(0,0,0,0.03)');
    r.setProperty('--menu-hover',dk?'rgba(59,130,246,0.12)':'rgba(59,130,246,0.08)');
    r.setProperty('--scene-bg',bg);
    r.setProperty('--scene-gradient',dk
      ?'radial-gradient(ellipse 110% 80% at 8% 0%,rgba(59,130,246,0.14) 0%,transparent 58%),radial-gradient(ellipse 90% 70% at 92% 4%,rgba(139,92,246,0.12) 0%,transparent 56%),radial-gradient(ellipse 120% 90% at 50% 110%,rgba(16,185,129,0.08) 0%,transparent 62%),linear-gradient(168deg,#0d1020 0%,#0a0c18 50%,#0e1024 100%)'
      :'radial-gradient(ellipse 110% 80% at 8% 0%,rgba(96,165,250,0.12) 0%,transparent 58%),radial-gradient(ellipse 90% 70% at 92% 4%,rgba(167,139,250,0.10) 0%,transparent 56%),radial-gradient(ellipse 120% 90% at 50% 110%,rgba(52,211,153,0.06) 0%,transparent 62%),linear-gradient(168deg,#f8fafc 0%,#f1f5f9 50%,#e2e8f0 100%)');
    r.setProperty('--scene-texture','url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%27200%27 height=%27200%27 viewBox=%270 0 200 200%27%3E%3Cfilter id=%27n%27%3E%3CfeTurbulence type=%27fractalNoise%27 baseFrequency=%270.78%27 numOctaves=%273%27 stitchTiles=%27stitch%27/%3E%3C/filter%3E%3Crect width=%27100%25%27 height=%27100%25%27 filter=%27url(%23n)%27 opacity=%270.7%27/%3E%3C/svg%3E")');
    r.setProperty('--scene-texture-opacity',dk?'0.035':'0.022');
    applyWindowStyle();
  }
  function switchTheme(theme){
    currentTheme=theme;applyThemeVars();
    /* 切换主题后: 等所有图表 finished 再统一暂停 */
    themeRefreshing=true;
    var pending=0,done=false;
    function finishThemeRefresh(){
      if(done)return;
      done=true;
      /* 先做两轮 resize, 确保布局和渲染完成后再暂停 */
      setTimeout(function(){
        try{resizeAll()}catch(e){}
        setTimeout(function(){
          try{resizeAll()}catch(e){}
          /* 再给一段稳定展示时间，防止未完整显示就暂停 */
          setTimeout(function(){
            try{resizeAll()}catch(e){}
            themeRefreshing=false;
            pauseAllCharts();
            applyRenderStateToAll();
          },120);
        },100);
      },60);
    }
    clearAllChartIdleTimers();
    Object.keys(charts).forEach(function(id){
      var c=charts[id],el=document.getElementById(id);
      if(!el||!c)return;
      c.instance.dispose();
      c.instance=echarts.init(el,theme);
      pending++;
      (function(inst){
        var onDone=function(){
          try{inst.off('finished',onDone)}catch(e){}
          pending--;
          if(pending<=0)setTimeout(finishThemeRefresh,80);
        };
        try{inst.on('finished',onDone)}catch(e){}
      })(c.instance);
      c.instance.setOption(stabilizeOption(CT[c.type].build(),c.type), true);
      enforceCalendarSquareCells(c.instance,c.type);
      setTimeout(function(){try{enforceCalendarSquareCells(c.instance,c.type)}catch(e){}},120);
      if(c.type==='scrollLegend')bindScrollLegendCenterLabel(c.instance);
      forceChartTransparent(c.instance);
      setChartActive(id,true);
    });
    if(pending===0){
      setTimeout(finishThemeRefresh,220);
      return;
    }
    /* 兜底: 防止个别图表不触发 finished (给足刷新时间) */
    setTimeout(finishThemeRefresh,2200);
  }

  /* ──────── 布局保存 / 恢复 ──────── */
  var LK='bird_dashboard_layout_v1';

  function saveLayout(){
    var layout=[];
    document.querySelectorAll('.grid-stack-item[gs-id]').forEach(function(el){
      var id=el.getAttribute('gs-id');
      if(charts[id]){
        layout.push({
          x:parseInt(el.getAttribute('gs-x')||0),
          y:parseInt(el.getAttribute('gs-y')||0),
          w:parseInt(el.getAttribute('gs-w')||4),
          h:parseInt(el.getAttribute('gs-h')||4),
          type:charts[id].type
        });
      }
    });
    try{localStorage.setItem(LK,JSON.stringify(layout));toast('布局已保存')}
    catch(e){toast('保存失败')}
  }

  function restoreLayout(){
    var saved;
    try{saved=localStorage.getItem(LK)}catch(e){}
    if(!saved){toast('没有已保存的布局');return}
    try{
      var layout=JSON.parse(saved);
      clearAllSilent();
      layout.forEach(function(item){
        addChart(item.type,{x:item.x,y:item.y,w:item.w,h:item.h});
      });
      setTimeout(syncGridHeight,120);
      toast('布局已恢复');
    }catch(e){toast('恢复失败')}
  }

  /* ──────── 事件委托 ──────── */

  /* 关闭按钮 */
  document.getElementById('grid').addEventListener('click',function(e){
    var clickedId=chartIdFromTarget(e.target);
    if(clickedId)setActiveCard(clickedId);
    var btn=e.target.closest('.card-close');
    if(btn){
      var closeId=btn.getAttribute('data-id');
      if(closeId)removeChart(closeId);
    }
  });

  /* 下拉菜单 */
  document.getElementById('addBtn').addEventListener('click',function(e){
    e.stopPropagation();
    document.getElementById('addDropdown').classList.toggle('open');
  });
  document.getElementById('chartMenu').addEventListener('click',function(e){
    var item=e.target.closest('.menu-item[data-type]');
    if(item)addChart(item.getAttribute('data-type'));
  });
  document.addEventListener('click',function(e){
    var dd=document.getElementById('addDropdown');
    if(!dd.contains(e.target))dd.classList.remove('open');
    var g=document.getElementById('grid');
    var t=document.getElementById('toolbar');
    if(g&&!g.contains(e.target)&&t&&!t.contains(e.target))setActiveCard(null);
  });

  /* 工具栏按钮 */
  document.getElementById('btnSave').addEventListener('click',saveLayout);
  document.getElementById('btnRestore').addEventListener('click',restoreLayout);
  document.getElementById('btnClear').addEventListener('click',function(){
    clearAllSilent();toast('已清空所有图表');
  });

  /* 主题选择 */
  document.getElementById('themeSelect').addEventListener('change',function(){
    customBg=null; /* 切换主题时清除自定义背景 */
    switchTheme(this.value);
  });

  /* 背景颜色选择器 */
  document.getElementById('bgColor').addEventListener('input',function(){
    customBg=this.value;
    applyThemeVars();
  });
  (function initWindowStyle(){
    var ss=document.getElementById('windowStyleSelect');
    if(!ss)return;
    try{
      var saved=localStorage.getItem('window_style_v1');
      if(saved&&['opaque','transparent','acrylic','frosted','flat','executive'].indexOf(saved)>=0){
        windowStyle=saved;
      }
    }catch(e){}
    ss.value=windowStyle;
    applyWindowStyle();
    ss.addEventListener('change',function(){
      var v=this.value;
      if(['opaque','transparent','acrylic','frosted','flat','executive'].indexOf(v)<0)v='acrylic';
      windowStyle=v;
      applyWindowStyle();
      rebuildChartsByTypes(['bar3D']);
      try{localStorage.setItem('window_style_v1',windowStyle)}catch(e){}
    });
  })();
  (function initStyleStrength(){
    var s=document.getElementById('styleStrength');
    var v=document.getElementById('styleStrengthVal');
    if(!s||!v)return;
    try{
      var saved=localStorage.getItem('style_strength_v1');
      if(saved!==null){
        var n=parseInt(saved,10);
        if(isFinite(n))styleStrength=Math.max(60,Math.min(140,n));
      }
    }catch(e){}
    s.value=String(styleStrength);
    v.textContent=styleStrength+'%';
    applyWindowStyle();
    s.addEventListener('input',function(){
      var n=parseInt(s.value,10);
      styleStrength=Math.max(60,Math.min(140,isFinite(n)?n:100));
      v.textContent=styleStrength+'%';
      applyWindowStyle();
      try{localStorage.setItem('style_strength_v1',String(styleStrength))}catch(e){}
    });
  })();
  (function initBar3DMode(){
    var s=document.getElementById('bar3DModeSelect');
    if(!s)return;
    try{
      var saved=localStorage.getItem('bar3d_mode_v1');
      if(saved&&['auto','native','pseudo'].indexOf(saved)>=0)bar3DMode=saved;
    }catch(e){}
    s.value=bar3DMode;
    s.addEventListener('change',function(){
      var v=this.value;
      if(['auto','native','pseudo'].indexOf(v)<0)v='auto';
      bar3DMode=v;
      try{localStorage.setItem('bar3d_mode_v1',bar3DMode)}catch(e){}
      rebuildChartsByTypes(['bar3D']);
    });
  })();
  document.getElementById('renderModeSelect').addEventListener('change',function(){
    var v=this.value==='safe'?'safe':'balanced';
    window.location.href='appcmd://render?mode='+v;
  });
  setupRenderPolicyUI(document);

  /* 多图模式: 只有鼠标所在图表恢复刷新 */
  var gridElForPolicy=document.getElementById('grid');
  var toolbarEl=document.getElementById('toolbar');
  if(gridElForPolicy){
    gridElForPolicy.addEventListener('mousemove',function(e){
      if(themeRefreshing)return;
      var cid=chartIdFromTarget(e.target);
      if(cid)touchChartActivity(cid);
    });
    gridElForPolicy.addEventListener('wheel',function(e){
      if(themeRefreshing)return;
      var cid=chartIdFromTarget(e.target);
      if(cid)touchChartActivity(cid);
    },{passive:true});
    gridElForPolicy.addEventListener('mouseenter',function(e){
      if(themeRefreshing)return;
      var cid=chartIdFromTarget(e.target);
      if(cid)touchChartActivity(cid);
    },true);
    gridElForPolicy.addEventListener('mouseout',function(e){
      if(themeRefreshing)return;
      if(!pauseWhenOut)return;
      var fromId=chartIdFromTarget(e.target);
      if(!fromId)return;
      var toId=chartIdFromTarget(e.relatedTarget);
      if(fromId===toId)return;
      clearChartIdleTimer(fromId);
      setChartActive(fromId,false);
    },true);
  }
  if(toolbarEl){
    toolbarEl.addEventListener('mouseenter',function(){
      /* 在工具栏内不触发图表状态切换, 仅保持现状 */
    });
  }

  /* 修复滚动: 在图表上滚轮也优先滚动容器 (按住 Shift 可让图表自己处理滚轮) */
  window.addEventListener('wheel',function(e){
    var g=document.getElementById('gridWrap');
    if(!g||!g.contains(e.target))return;
    /* 默认不把滚轮传给图表; 按住 Ctrl 才允许图表响应 */
    if(e.ctrlKey)return;
    if(g.scrollHeight<=g.clientHeight+2)return;
    g.scrollTop+=e.deltaY;
    e.preventDefault();
  },{capture:true,passive:false});

  /* ──────── 默认布局 ──────── */
  function defaultLayout(){
    if(DBG.lite_layout){
      addChart('map_density',{x:0,y:0,w:8,h:5});
      addChart('bar',{x:8,y:0,w:4,h:5});
      return;
    }
    addChart('map_density',{x:0,y:0,w:8,h:5});
    addChart('pie',{x:8,y:0,w:4,h:5});
    addChart('bar',{x:0,y:5,w:6,h:4});
    addChart('line',{x:6,y:5,w:6,h:4});
  }

  applyThemeVars();
  defaultLayout();
  updateEmptyState();
  setTimeout(function(){
    pauseAllCharts();
    applyRenderStateToAll();
    setTimeout(syncGridHeight,80);
  },120);

  /* 修复: 首次加载时 GridStack 尚未完成布局, ECharts 拿到的容器尺寸可能不对 */
  setTimeout(resizeAll, 200);
  setTimeout(resizeAll, 600);
  setTimeout(resizeAll, 1500);

})();
</script>
</body></html>"""


# ════════════════════════════ 构建 HTML ════════════════════════════


def build_dashboard_html(
    register_code: Dict[str, str],
    ui_map: Dict[str, Dict[str, Any]],
    geojson_str: str,
    china_geojson_str: str,
    data: Dict[str, str],
    debug_opts: Dict[str, Any],
    render_mode: str,
) -> str:
    all_register = "\n".join(register_code.values())
    theme_names = sorted(register_code.keys())
    theme_opts = "".join(
        f'<option value="{t}"{"selected" if t == "dark" else ""}>{t}</option>'
        for t in theme_names
    )
    data_js = "{\n" + ",\n".join(f"  {k}: {v}" for k, v in data.items()) + "\n}"

    # gridstack CSS 体积小, 内联到 HTML
    gridstack_css = read_text(GRIDSTACK_CSS_PATH)

    html = HTML_TEMPLATE
    replacements = {
        "__GRIDSTACK_CSS__": gridstack_css,
        "__REGISTER_CODE__": all_register,
        "__THEME_OPTS__": theme_opts,
        "__UI_MAP__": json.dumps(ui_map, ensure_ascii=False),
        "__GEOJSON__": geojson_str,
        "__CHINA_GEOJSON__": china_geojson_str,
        "__DATA__": data_js,
        "__DEBUG_OPTS__": json.dumps(debug_opts, ensure_ascii=False),
        "__RENDER_GPU_SELECTED__": "selected" if render_mode == "balanced" else "",
        "__RENDER_CPU_SELECTED__": "selected" if render_mode == "safe" else "",
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html


# ════════════════════════════ PyQt6 窗口 ════════════════════════════


def restart_with_render_mode(mode: str) -> None:
    env = os.environ.copy()
    env["WB_RENDER_MODE"] = mode
    subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=BASE_DIR, env=env)
    QApplication.quit()


class CommandWebPage(QWebEnginePage):
    def __init__(self, parent: Any, command_cb: Any) -> None:
        super().__init__(parent)
        self._command_cb = command_cb

    def acceptNavigationRequest(self, url: QUrl, nav_type: Any, is_main_frame: bool) -> bool:
        if url.scheme().lower() == "appcmd":
            cmd = (url.host() or "").strip().lower()
            params: Dict[str, str] = {}
            if url.hasQuery():
                for item in url.query().split("&"):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        params[k] = v
            try:
                self._command_cb(cmd, params)
            except Exception:
                pass
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class DashboardWindow(QMainWindow):
    def __init__(self, html_path: str) -> None:
        super().__init__()
        self.setWindowTitle("北京市拍鸟数据可视化 - 仪表盘")
        self.resize(1400, 900)

        # 强制不透明窗口与稳定背景, 减少合成层抖动
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1a1a2e"))
        self.setPalette(pal)

        self.web = QWebEngineView(self)
        self.web.setPage(CommandWebPage(self.web, self._handle_command))
        self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.web.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.web.setAutoFillBackground(True)
        web_pal = self.web.palette()
        web_pal.setColor(QPalette.ColorRole.Base, QColor("#1a1a2e"))
        web_pal.setColor(QPalette.ColorRole.Window, QColor("#1a1a2e"))
        self.web.setPalette(web_pal)
        self.web.page().setBackgroundColor(QColor("#1a1a2e"))
        self.web.setUrl(QUrl.fromLocalFile(html_path))
        self.setCentralWidget(self.web)

    def _handle_command(self, cmd: str, params: Dict[str, str]) -> None:
        if cmd == "render":
            mode = params.get("mode", "").strip().lower()
            if mode in ("safe", "balanced") and mode != RENDER_MODE:
                restart_with_render_mode(mode)


class ChartCard(QFrame):
    def __init__(
        self,
        html_path: str,
        chart_type: str,
        chart_label: str,
        theme: str,
        card_id: str,
        on_close: Any,
        on_resize: Any,
        on_swap: Any,
    ) -> None:
        super().__init__()
        self.html_path = html_path
        self.chart_type = chart_type
        self.chart_label = chart_label
        self.theme = theme
        self.card_id = card_id
        self._on_close = on_close
        self._on_resize = on_resize
        self._on_swap = on_swap
        self._drag_start = QPoint()
        self._drag_enabled = False

        self.setAcceptDrops(True)
        self.setObjectName("ChartCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "#ChartCard{background:#1a1a2e;border:1px solid rgba(255,255,255,0.08);border-radius:8px;}"
            "QPushButton{background:#26223a;color:#eef1fa;border:1px solid rgba(255,255,255,0.12);"
            "border-radius:5px;padding:2px 6px;font-size:11px;}"
            "QPushButton:hover{background:#34304a;}"
        )
        self.setMinimumSize(320, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.header = QWidget(self)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(4, 0, 4, 0)
        hl.setSpacing(6)

        self.title_btn = QPushButton(f"{chart_label}")
        self.title_btn.setEnabled(False)
        self.title_btn.setStyleSheet(
            "QPushButton{color:#eef1fa;background:transparent;border:none;text-align:left;"
            "font-size:12px;font-weight:600;}"
        )
        self.size_label = QPushButton("1x1")
        self.size_label.setEnabled(False)
        self.size_label.setFixedWidth(44)
        self.size_label.setStyleSheet(
            "QPushButton{color:#B9B8CE;background:transparent;border:none;font-size:11px;}"
        )
        w_minus = QPushButton("W-")
        w_plus = QPushButton("W+")
        h_minus = QPushButton("H-")
        h_plus = QPushButton("H+")
        close_btn = QPushButton("x")
        close_btn.setFixedWidth(26)
        close_btn.setStyleSheet(
            "QPushButton{color:#B9B8CE;background:transparent;border:none;font-size:14px;}"
            "QPushButton:hover{color:#fff;background:rgba(255,71,87,0.3);border-radius:4px;}"
        )

        w_minus.clicked.connect(lambda: self._on_resize(self, -1, 0))
        w_plus.clicked.connect(lambda: self._on_resize(self, +1, 0))
        h_minus.clicked.connect(lambda: self._on_resize(self, 0, -1))
        h_plus.clicked.connect(lambda: self._on_resize(self, 0, +1))
        close_btn.clicked.connect(lambda: self._on_close(self))

        hl.addWidget(self.title_btn, 1)
        hl.addWidget(self.size_label, 0)
        hl.addWidget(w_minus, 0)
        hl.addWidget(w_plus, 0)
        hl.addWidget(h_minus, 0)
        hl.addWidget(h_plus, 0)
        hl.addWidget(close_btn, 0)

        self.web = QWebEngineView(self)
        self.web.setPage(CommandWebPage(self.web, self._handle_command))
        self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.web.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.web.setAutoFillBackground(True)
        p = self.web.palette()
        p.setColor(QPalette.ColorRole.Base, QColor("#1a1a2e"))
        p.setColor(QPalette.ColorRole.Window, QColor("#1a1a2e"))
        self.web.setPalette(p)
        self.web.page().setBackgroundColor(QColor("#1a1a2e"))

        root.addWidget(self.header, 0)
        root.addWidget(self.web, 1)
        self.reload_chart(theme)

    def _handle_command(self, cmd: str, params: Dict[str, str]) -> None:
        if cmd == "render":
            mode = params.get("mode", "").strip().lower()
            if mode in ("safe", "balanced") and mode != RENDER_MODE:
                restart_with_render_mode(mode)

    def set_span_text(self, w: int, h: int) -> None:
        self.size_label.setText(f"{w}x{h}")

    def reload_chart(self, theme: str) -> None:
        self.theme = theme
        url = QUrl.fromLocalFile(self.html_path)
        url.setQuery(f"single={self.chart_type}&theme={self.theme}")
        self.web.setUrl(url)

    def mousePressEvent(self, event: Any) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().y() <= 40
        ):
            self._drag_start = event.position().toPoint()
            self._drag_enabled = True
        else:
            self._drag_enabled = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if not self._drag_enabled:
            return super().mouseMoveEvent(event)
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
            return super().mouseMoveEvent(event)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.card_id)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_enabled = False
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        self._drag_enabled = False
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasText() and event.mimeData().text() != self.card_id:
            event.acceptProposedAction()
            self.setStyleSheet(
                self.styleSheet()
                + "#ChartCard{border:1px solid rgba(73,146,255,0.8);background:#1b1731;}"
            )
        else:
            event.ignore()

    def dragLeaveEvent(self, event: Any) -> None:
        self.setStyleSheet(
            self.styleSheet().replace(
                "#ChartCard{border:1px solid rgba(73,146,255,0.8);background:#1b1731;}",
                "",
            )
        )
        super().dragLeaveEvent(event)

    def dropEvent(self, event: Any) -> None:
        src_id = event.mimeData().text()
        if src_id and src_id != self.card_id:
            self._on_swap(src_id, self.card_id)
            event.acceptProposedAction()
        self.setStyleSheet(
            self.styleSheet().replace(
                "#ChartCard{border:1px solid rgba(73,146,255,0.8);background:#1b1731;}",
                "",
            )
        )


class MultiViewDashboardWindow(QMainWindow):
    GRID_COLS = 4
    ROW_HEIGHT = 230
    MIN_W, MAX_W = 1, 4
    MIN_H, MAX_H = 1, 3

    def __init__(self, html_path: str, themes: List[str]) -> None:
        super().__init__()
        self.html_path = html_path
        self.themes = themes or ["dark"]
        self.cards: List[ChartCard] = []
        self.spans: Dict[str, Tuple[int, int]] = {}
        self.current_theme = "dark" if "dark" in self.themes else self.themes[0]
        self._card_seq = 0
        self._last_rows = 0

        self.setWindowTitle("北京市拍鸟数据可视化 - 多视图仪表盘")
        self.resize(1560, 960)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1a1a2e"))
        self.setPalette(pal)

        root = QWidget(self)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        bar = QWidget(root)
        bar.setStyleSheet("background:#151026;border:1px solid rgba(255,255,255,0.08);border-radius:8px;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(8)

        self.type_combo = QComboBox(bar)
        for t, label in CHART_TYPE_LABELS:
            self.type_combo.addItem(label, t)
        self.theme_combo = QComboBox(bar)
        for t in self.themes:
            self.theme_combo.addItem(t)
        idx = self.theme_combo.findText(self.current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentTextChanged.connect(self.change_theme)

        add_btn = QPushButton("+ 添加图表", bar)
        add_btn.clicked.connect(self.add_chart_from_combo)
        clear_btn = QPushButton("清空", bar)
        clear_btn.clicked.connect(self.clear_cards)

        for w in (self.type_combo, self.theme_combo, add_btn, clear_btn):
            w.setStyleSheet(
                "QComboBox,QPushButton{background:#26223a;color:#eef1fa;border:1px solid rgba(255,255,255,0.12);"
                "border-radius:6px;padding:5px 10px;font-size:12px;}"
                "QPushButton:hover{background:#34304a;}"
            )

        bl.addWidget(self.type_combo, 0)
        bl.addWidget(add_btn, 0)
        bl.addSpacing(10)
        bl.addWidget(self.theme_combo, 0)
        bl.addWidget(clear_btn, 0)
        bl.addStretch(1)

        self.scroll = QScrollArea(root)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background:transparent;border:none;")

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.scroll.setWidget(self.grid_host)

        outer.addWidget(bar, 0)
        outer.addWidget(self.scroll, 1)
        self.setCentralWidget(root)

        self.add_chart("map_density")
        self.add_chart("pie")
        self.add_chart("bar")
        self.add_chart("line")

    def _default_span(self, chart_type: str) -> Tuple[int, int]:
        defaults: Dict[str, Tuple[int, int]] = {
            "map_density": (2, 2),
            "map_scatter": (2, 2),
            "map_heatmap": (2, 2),
            "map_graph": (2, 2),
            "bar": (2, 2),
            "line": (2, 2),
            "pie": (1, 2),
            "gauge": (1, 1),
            "bird_list": (1, 2),
            "customGaugeMini": (2, 1),
            "customGaugeProgress": (2, 1),
            "radarStudio": (2, 2),
            "radarContrast": (2, 2),
        }
        return defaults.get(chart_type, (1, 1))

    def add_chart_from_combo(self) -> None:
        self.add_chart(str(self.type_combo.currentData()))

    def add_chart(self, chart_type: str) -> None:
        label = dict(CHART_TYPE_LABELS).get(chart_type, chart_type)
        self._card_seq += 1
        card_id = f"card_{self._card_seq}"
        card = ChartCard(
            self.html_path,
            chart_type,
            label,
            self.current_theme,
            card_id,
            self.remove_card,
            self.resize_card_span,
            self.swap_cards,
        )
        self.cards.append(card)
        self.spans[card_id] = self._default_span(chart_type)
        self.relayout_cards()

    def remove_card(self, card: ChartCard) -> None:
        if card in self.cards:
            self.cards.remove(card)
            self.spans.pop(card.card_id, None)
            card.setParent(None)
            card.deleteLater()
            self.relayout_cards()

    def clear_cards(self) -> None:
        for c in self.cards[:]:
            c.setParent(None)
            c.deleteLater()
        self.cards.clear()
        self.spans.clear()
        self.relayout_cards()

    def change_theme(self, theme: str) -> None:
        self.current_theme = theme or self.current_theme
        for card in self.cards:
            card.reload_chart(self.current_theme)

    def resize_card_span(self, card: ChartCard, dw: int, dh: int) -> None:
        w, h = self.spans.get(card.card_id, (1, 1))
        nw = max(self.MIN_W, min(self.MAX_W, w + dw))
        nh = max(self.MIN_H, min(self.MAX_H, h + dh))
        self.spans[card.card_id] = (nw, nh)
        self.relayout_cards()

    def swap_cards(self, src_id: str, target_id: str) -> None:
        src_i = next((i for i, c in enumerate(self.cards) if c.card_id == src_id), -1)
        tgt_i = next((i for i, c in enumerate(self.cards) if c.card_id == target_id), -1)
        if src_i < 0 or tgt_i < 0 or src_i == tgt_i:
            return
        card = self.cards.pop(src_i)
        if src_i < tgt_i:
            tgt_i -= 1
        self.cards.insert(tgt_i, card)
        self.relayout_cards()

    def _can_place(
        self, occ: List[List[bool]], row: int, col: int, w: int, h: int
    ) -> bool:
        if col + w > self.GRID_COLS:
            return False
        for rr in range(row, row + h):
            while rr >= len(occ):
                occ.append([False] * self.GRID_COLS)
            for cc in range(col, col + w):
                if occ[rr][cc]:
                    return False
        return True

    def _mark_place(
        self, occ: List[List[bool]], row: int, col: int, w: int, h: int
    ) -> None:
        for rr in range(row, row + h):
            while rr >= len(occ):
                occ.append([False] * self.GRID_COLS)
            for cc in range(col, col + w):
                occ[rr][cc] = True

    def relayout_cards(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        occ: List[List[bool]] = []
        placed_rows = 0
        for card in self.cards:
            w, h = self.spans.get(card.card_id, (1, 1))
            w = max(self.MIN_W, min(self.MAX_W, w))
            h = max(self.MIN_H, min(self.MAX_H, h))
            self.spans[card.card_id] = (w, h)
            card.set_span_text(w, h)
            card.setMinimumHeight(self.ROW_HEIGHT * h)

            placed = False
            row = 0
            while not placed:
                for col in range(0, self.GRID_COLS):
                    if self._can_place(occ, row, col, w, h):
                        self._mark_place(occ, row, col, w, h)
                        self.grid.addWidget(card, row, col, h, w)
                        placed_rows = max(placed_rows, row + h)
                        placed = True
                        break
                row += 1

        for r in range(max(self._last_rows, placed_rows) + 2):
            self.grid.setRowMinimumHeight(r, self.ROW_HEIGHT if r < placed_rows else 0)
            self.grid.setRowStretch(r, 1 if r < placed_rows else 0)
        self._last_rows = placed_rows

        for col in range(self.GRID_COLS):
            self.grid.setColumnStretch(col, 1)


# ════════════════════════════ 入口 ════════════════════════════


def main() -> None:
    # safe 模式才强制软件 OpenGL
    if RENDER_MODE == "safe":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)

    geojson = read_geojson()
    geojson_str = json.dumps(geojson, ensure_ascii=False)
    china_geojson_str = json.dumps(read_json_file(CHINA_GEOJSON_PATH), ensure_ascii=False)
    register_code, ui_map = load_themes()
    districts = get_district_centers(geojson)
    if not districts:
        print("未从 GeoJSON 中提取到区划信息。")
        sys.exit(1)
    data = gen_all_data(districts)
    html = build_dashboard_html(
        register_code, ui_map, geojson_str, china_geojson_str, data, DEBUG_OPTS, RENDER_MODE
    )

    # 写入脚本同目录, 确保相对路径 src= 能解析到本地 JS 文件
    hp = os.path.join(BASE_DIR, "_dashboard.html")
    with open(hp, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard HTML: {hp} ({len(html)//1024} KB)")
    print(f"Render mode: {RENDER_MODE}")
    print(f"Arch mode: {ARCH_MODE}")

    app = QApplication(sys.argv)
    abs_hp = os.path.abspath(hp)
    if ARCH_MODE == "single":
        w = DashboardWindow(abs_hp)
    else:
        theme_names = sorted(register_code.keys())
        w = MultiViewDashboardWindow(abs_hp, theme_names)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
