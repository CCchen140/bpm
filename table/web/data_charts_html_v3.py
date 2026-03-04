from __future__ import annotations

import json
import os
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="gbk")
        except Exception:
            return ""


def _rgba_to_hex(s: str) -> str:
    try:
        p = s.replace("rgba(", "").replace(")", "").split(",")
        if float(p[3].strip()) < 0.3:
            return "#ffffff"
        return f"#{int(float(p[0])):02x}{int(float(p[1])):02x}{int(float(p[2])):02x}"
    except Exception:
        return "#ffffff"


def _is_dark(c: str) -> bool:
    h = c.lstrip("#")
    if len(h) != 6:
        return False
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140


def _extract_ui(obj: dict) -> dict:
    bg_raw = obj.get("backgroundColor", "") or ""
    body_bg = "#ffffff"
    if bg_raw and bg_raw != "transparent":
        body_bg = _rgba_to_hex(bg_raw) if str(bg_raw).startswith("rgba") else str(bg_raw)
    dark = _is_dark(body_bg)
    tc = (
        obj.get("title", {}).get("subtextStyle", {}).get("color", "")
        or obj.get("title", {}).get("textStyle", {}).get("color", "")
        or ("#B9B8CE" if dark else "#333333")
    )
    ttc = obj.get("title", {}).get("textStyle", {}).get("color", "") or ("#EEF1FA" if dark else "#111111")
    palette = obj.get("color", []) or []
    return {
        "bodyBg": body_bg,
        "dark": bool(dark),
        "textColor": str(tc),
        "titleColor": str(ttc),
        "colorPalette": list(palette[:8]) if isinstance(palette, list) else [],
    }


def _escape_html(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _load_theme_presets() -> tuple[list[str], str, dict]:
    fallback_ui = {
        "dark": {
            "bodyBg": "#100C2A",
            "dark": True,
            "textColor": "#B9B8CE",
            "titleColor": "#EEF1FA",
            "colorPalette": ["#4992FF", "#7CFFB2", "#FDDD60", "#FF6E76", "#58D9F9", "#05C091"],
        }
    }

    candidates = [
        _project_root() / "data" / "echart" / "theme",
    ]

    reg: dict[str, str] = {}
    ui: dict[str, dict] = {}
    for theme_dir in candidates:
        if not theme_dir.exists() or not theme_dir.is_dir():
            continue
        files: list[Path] = []
        for p in theme_dir.rglob("*"):
            if not p.is_file():
                continue
            suf = p.suffix.lower()
            if suf not in (".js", ".mjs", ".json"):
                continue
            rel = p.relative_to(theme_dir)
            if rel.name.startswith("."):
                continue
            files.append(p)

        def _pri(p: Path) -> int:
            suf = p.suffix.lower()
            if suf == ".json":
                return 0
            if suf == ".js":
                return 1
            return 2

        for p in sorted(files, key=lambda x: (_pri(x), str(x).lower())):
            suf = p.suffix.lower()
            rel = p.relative_to(theme_dir)
            key = rel.with_suffix("").as_posix()
            if key in reg:
                continue
            if suf in (".js", ".mjs"):
                code = _read_text(p)
                if code:
                    reg[key] = code
                    ui[key] = fallback_ui["dark"]
            elif suf == ".json":
                c = _read_text(p)
                if not c:
                    continue
                reg[key] = f"echarts.registerTheme('{key}', {c});\n"
                try:
                    ui[key] = _extract_ui(json.loads(c))
                except Exception:
                    ui[key] = fallback_ui["dark"]

    names = sorted(reg.keys()) if reg else ["dark"]
    register_code = "\n".join(reg.values())
    ui_map = ui if ui else fallback_ui
    return (names, register_code, ui_map)


def build_html() -> str:
    theme_names, register_code, theme_ui = _load_theme_presets()
    default_theme = "dark" if "dark" in theme_names else (theme_names[0] if theme_names else "dark")
    # 主题名称映射：英文名 -> 中文名
    theme_name_map = {
        "dark": "深色",
        "light": "浅色",
        "chalk": "粉笔",
        "essos": "埃索斯",
        "infographic": "信息图",
        "macarons": "马卡龙",
        "purple-passion": "紫色激情",
        "roma": "罗马",
        "shine": "闪耀",
        "vintage": "复古",
        "walden": "瓦尔登",
        "westeros": "维斯特洛",
        "wonderland": "仙境",
    }
    theme_opts = "".join(
        f'<option value="{_escape_html(t)}"{" selected" if t == default_theme else ""}>{_escape_html(theme_name_map.get(t, t))}</option>'
        for t in theme_names
    )
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>数据图表</title>
  <style>
    :root{
      --toolbar-h:46px;
      --radius-xs:4px;
      --radius-sm:6px;
      --radius-md:10px;
      --radius-lg:14px;
      --space-1:4px;
      --space-2:8px;
      --space-3:12px;
      --space-4:16px;
      --control-h:28px;
      --font-sm:11.5px;
      --font-md:12.5px;
      --font-lg:14px;
      --font-ui:"Fira Sans","Segoe UI","Microsoft YaHei",sans-serif;
      --motion-fast:110ms;
      --motion-mid:170ms;
      --motion-slow:260ms;
      --easing-standard:cubic-bezier(.22,.61,.36,1);
      --bg:#0c0e1a;
      --scene-bg:#080a14;
      --primary:#3B82F6;
      --secondary:#3B82F6;
      --scene-gradient:
        radial-gradient(ellipse 110% 80% at 8% 0%, rgba(59,130,246,0.14) 0%, transparent 58%),
        radial-gradient(ellipse 90% 70% at 92% 4%, rgba(139,92,246,0.12) 0%, transparent 56%),
        radial-gradient(ellipse 120% 90% at 50% 110%, rgba(16,185,129,0.08) 0%, transparent 62%),
        linear-gradient(168deg, #0d1020 0%, #0a0c18 50%, #0e1024 100%);
      --scene-texture:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200' viewBox='0 0 200 200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.78' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.7'/%3E%3C/svg%3E");
      --scene-texture-opacity:.035;
      --scene-style-overlay:none;
      --text:#94a3b8;
      --text-title:#e2e8f0;
      --text-muted:rgba(148,163,184,0.56);
      --muted:var(--text-muted);
      --border:rgba(255,255,255,0.08);
      --danger:#ef4444;
      --close-hover:#ef4444;
      --shadow:rgba(0,0,0,0.5);
      --card-bg:rgba(16,20,38,0.82);
      --card-header-bg:rgba(22,28,52,0.88);
      --card-shadow:0 1px 2px rgba(0,0,0,0.24),0 4px 12px rgba(0,0,0,0.18),0 12px 28px rgba(0,0,0,0.12);
      --card-border-color:rgba(255,255,255,0.07);
      --focus-ring:rgba(59,130,246,0.56);
      --focus-ring-soft:rgba(59,130,246,0.20);
      --toolbar-bg:rgba(12,14,26,0.92);
      --toolbar-blur:0px;
      --toolbar-border:rgba(255,255,255,0.06);
      --toolbar-group-bg:rgba(255,255,255,0.025);
      --toolbar-group-border:rgba(59,130,246,0.16);
      --toolbar-highlight:linear-gradient(90deg,transparent,rgba(59,130,246,0.24),rgba(16,185,129,0.16),transparent);
      --btn-bg:rgba(59,130,246,0.08);
      --btn-border:rgba(59,130,246,0.20);
      --btn-hover:rgba(59,130,246,0.16);
      --select-bg:rgba(16,20,38,0.92);
      --menu-bg:rgba(14,17,32,0.96);
      --menu-hover:rgba(59,130,246,0.12);
      --card-blur:0px;
      --card-saturate:140%;
      --card-layer-blur:0px;
      --card-layer-opacity:0;
      --card-layer-scale:1;
      --card-overlay-opacity:0;
      --card-overlay-color:transparent;
      --card-overlay-image:none;
      --card-noise-opacity:0;

      --btn-h:34px;
      --grid: 20px;
    }
    *{box-sizing:border-box}
    html,body{height:100%}
    body{
      margin:0;
      font-family:var(--font-ui);
      background:var(--bg);
      color:var(--text);
      overflow:hidden;
    }
    body.modal-open #app{pointer-events:none}
    body.modal-open #panel{pointer-events:none}
    body.modal-open{overflow:hidden}
    #app{height:100%;display:flex;flex-direction:column}

    .btn{
      height:var(--control-h);
      padding:0 var(--space-3);
      border-radius:var(--radius-xs);
      border:1px solid var(--btn-border);
      background:var(--btn-bg);
      color:var(--text);
      display:inline-flex;align-items:center;gap:8px;
      cursor:pointer;user-select:none;
      transition:all var(--motion-fast) var(--easing-standard);
      letter-spacing:.01em;
    }
    .btn:hover{border-color:var(--accent);background:var(--btn-hover);color:var(--text-title);box-shadow:0 0 8px rgba(59,130,246,0.12)}
    .btn:active{transform:scale(.97)}
    .btn.primary{background:rgba(59,130,246,0.12);color:#60a5fa;border-color:rgba(59,130,246,0.40);font-weight:500}
    .btn.primary:hover{background:rgba(59,130,246,0.20);box-shadow:0 0 12px rgba(59,130,246,0.18)}
    .btn.danger{border-color:rgba(239,68,68,.50);background:rgba(239,68,68,0.12);color:#fecaca}
    .btn[disabled]{opacity:.45;cursor:not-allowed;transform:none}
    .btn .dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
    .btn.primary .dot{background:var(--secondary)}
    .btn.danger .dot{background:var(--danger)}
    .boatWrap{display:flex;align-items:center;justify-content:center;gap:10px}
    .boatWrap .boatText{font-size:12px;font-weight:900;color:var(--text);opacity:.70;user-select:none}
    .boatWrap[data-on="0"] .boatText.off{opacity:1;color:var(--text-title)}
    .boatWrap[data-on="1"] .boatText.on{opacity:1;color:var(--text-title)}
    .btn.boat{
      border-radius:999px;
      position:relative;
      padding:0;
      width:46px;
      height:24px;
      background:rgba(255,255,255,0.06);
      border:1px solid rgba(255,255,255,0.10);
      box-shadow:0 10px 24px rgba(0,0,0,0.22),0 0 0 1px rgba(255,255,255,0.04) inset;
      overflow:hidden;
    }
    .btn.boat:hover{border-color:rgba(59,130,246,0.34);box-shadow:0 12px 26px rgba(0,0,0,0.24),0 0 0 3px rgba(59,130,246,0.10)}
    .btn.boat:active{transform:scale(.98)}
    .btn.boat[data-on="1"]{
      background:linear-gradient(180deg, rgba(59,130,246,0.26), rgba(59,130,246,0.12));
      border-color:rgba(59,130,246,0.46);
      box-shadow:0 14px 34px rgba(0,0,0,0.24),0 0 0 3px rgba(59,130,246,0.12);
    }
    .btn.boat .boat-thumb{
      position:absolute;
      top:50%;
      left:3px;
      width:18px;height:18px;border-radius:999px;
      transform:translateY(-50%);
      background:rgba(255,255,255,0.88);
      box-shadow:0 10px 22px rgba(0,0,0,0.30),0 0 0 1px rgba(0,0,0,0.16) inset;
      transition:left var(--motion-fast) var(--easing-standard), background var(--motion-fast) var(--easing-standard);
    }
    .btn.boat[data-on="1"] .boat-thumb{left:calc(100% - 21px);background:rgba(255,255,255,0.94)}
    #panel, #panel *{-webkit-tap-highlight-color:transparent}
    #panel ::selection{background:transparent}
    /* 禁止所有文字被选中 */
    html, body, #desk, #panel, .win, .win-content, .win-header, .win-tools, .modal, .modal-content{
      user-select:none;
      -webkit-user-select:none;
      -moz-user-select:none;
      -ms-user-select:none;
    }
    /* 允许输入框和文本域中的文字被选中 */
    input, textarea, [contenteditable="true"]{
      user-select:text;
      -webkit-user-select:text;
      -moz-user-select:text;
      -ms-user-select:text;
    }

    .workspace{flex:1;min-height:0;position:relative;overflow-y:auto;overflow-x:auto}
    .workspace::-webkit-scrollbar{display:none}
    .workspace{scrollbar-width:none;-ms-overflow-style:none}
    #desk{
      position:relative;
      background-color:var(--scene-bg);
      background-image:var(--scene-style-overlay),var(--scene-gradient);
      background-size:cover,cover;
      background-repeat:no-repeat,no-repeat;
      background-attachment:fixed,fixed;
      background-position:center center,center center;
      isolation:isolate;
      overflow:visible;
      min-height:100%;
      min-width:100%;
    }
    #desk::before{
      content:"";
      position:fixed;inset:0;z-index:0;pointer-events:none;
      background-image:var(--scene-texture);
      background-size:200px 200px;
      background-repeat:repeat;
      opacity:var(--scene-texture-opacity);
      mix-blend-mode:overlay;
    }
    #gridGuideCanvas{
      position:absolute;left:0;top:0;z-index:6;pointer-events:none;
      opacity:0;transition:opacity .15s ease;
    }
    #desk.show-dash-grid #gridGuideCanvas{opacity:1}
    #ghost{
      position:absolute;z-index:9998;pointer-events:none;
      border:1.5px dashed rgba(126,196,255,0.50);
      border-radius:var(--radius-lg);
      background:rgba(126,196,255,0.06);
      box-shadow:0 0 20px rgba(126,196,255,0.12);
      display:none;
    }
    #ghost.show{display:block}

    .win{
      position:absolute;
      width:520px;height:360px;
      background:var(--card-bg);
      border:1px solid var(--card-border-color);
      border-radius:var(--radius-lg);
      box-shadow:var(--card-shadow);
      overflow:hidden;
      display:flex;flex-direction:column;
      backdrop-filter:blur(var(--card-blur)) saturate(var(--card-saturate));
      -webkit-backdrop-filter:blur(var(--card-blur)) saturate(var(--card-saturate));
      touch-action:none;
      z-index:7;
      isolation:isolate;
    }
    .win::before{
      content:"";
      position:absolute;top:0;left:10%;right:10%;height:1px;z-index:3;pointer-events:none;
      background:linear-gradient(90deg,transparent,rgba(255,255,255,0.15),transparent);
    }
    .win::after{
      content:"";
      position:absolute;inset:0;z-index:1;pointer-events:none;
      border-radius:inherit;
      background-color:var(--card-overlay-color);
      background-image:var(--card-overlay-image);
      opacity:var(--card-overlay-opacity);
      backdrop-filter:blur(var(--card-layer-blur)) saturate(1.2);
      -webkit-backdrop-filter:blur(var(--card-layer-blur)) saturate(1.2);
    }
    .win-noise{
      position:absolute;inset:0;z-index:2;pointer-events:none;
      border-radius:inherit;
      opacity:var(--card-noise-opacity);
      background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
      background-repeat:repeat;
      mix-blend-mode:overlay;
    }
    .refreshLamp{
      position:absolute;
      left:10px;
      top:10px;
      z-index:35;
      width:10px;
      height:10px;
      border-radius:999px;
      background:rgba(239,68,68,0.95);
      box-shadow:0 0 0 2px rgba(0,0,0,0.28), 0 0 10px rgba(239,68,68,0.28);
      display:none;
      pointer-events:none;
    }
    body.bp-debug .refreshLamp{display:block}
    .win[data-active-refresh="1"] .refreshLamp{
      background:rgba(34,197,94,0.95);
      box-shadow:0 0 0 2px rgba(0,0,0,0.28), 0 0 10px rgba(34,197,94,0.28);
    }
    .win[data-paused="1"] .refreshLamp{
      background:rgba(239,68,68,0.95);
      box-shadow:0 0 0 2px rgba(0,0,0,0.28), 0 0 10px rgba(239,68,68,0.18);
    }
    .drag-zone{
      position:absolute;left:0;top:0;right:0;height:26px;
      cursor:grab;user-select:none;
      z-index:30;
      background:transparent;
      touch-action:none;
    }
    .drag-zone:active{cursor:grabbing}
    body:not(.edit-mode) .drag-zone{display:none}
    .win-body{flex:1;min-height:0;position:relative;z-index:4}
    .chart{position:absolute;inset:0}
    .resizer{
      position:absolute;right:6px;bottom:6px;width:14px;height:14px;
      border-right:2px solid rgba(255,255,255,.40);
      border-bottom:2px solid rgba(255,255,255,.40);
      cursor:nwse-resize;
      opacity:.32;
      z-index: 20;
      pointer-events: auto;
      touch-action: none;
    }
    .resizer:hover{opacity:.52}
    body:not(.edit-mode) .resizer{display:none}

    .win-tools{
      position:absolute;
      top:6px;
      right:6px;
      z-index:40;
      display:none;
      gap:6px;
    }
    body.edit-mode .win-tools{display:flex}
    .win-tools .tool{
      height:26px;
      padding:0 10px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,0.12);
      background:rgba(0,0,0,0.22);
      color:var(--text-title);
      font-size:12px;
      cursor:pointer;
      user-select:none;
      -webkit-user-select:none;
      -webkit-tap-highlight-color:transparent;
    }
    .win-tools .tool:hover{border-color:var(--accent);background:rgba(0,0,0,0.28)}
    .win[data-lock="1"] .win-tools .tool.lock{
      border-color:rgba(59,130,246,0.85);
      background:rgba(59,130,246,0.62);
      color:#ffffff;
    }
    .win-tools .tool.danger{border-color:rgba(239,68,68,.45);color:#fecaca}
    .win-tools .tool.danger:hover{border-color:rgba(239,68,68,.75);background:rgba(239,68,68,0.10)}

    .overlay{
      position:absolute;inset:0;
      background:rgba(10,12,22,.45);
      display:none;align-items:center;justify-content:center;
      backdrop-filter:blur(4px);
      z-index:999999;
      pointer-events:none;
    }
    .overlay.show{display:flex}
    .spinner{
      width:34px;height:34px;border-radius:50%;
      border:3px solid rgba(255,255,255,.15);
      border-top-color:var(--primary);
      animation:spin 1s linear infinite;
    }
    @keyframes spin{to{transform:rotate(360deg)}}

    .modal{
      position:fixed;inset:0;display:none;align-items:center;justify-content:center;
      background:rgba(0,0,0,.55);backdrop-filter:none;z-index:9999999;
    }
    .modal.show{display:flex}
    .modalCard{
      width:min(920px, calc(100vw - 24px));
      max-height:calc(100vh - 24px);
      overflow:auto;
      background:var(--card-bg);
      border:1px solid var(--card-border-color);
      border-radius:var(--radius-lg);
      box-shadow:var(--card-shadow);
      backdrop-filter:none;
      -webkit-backdrop-filter:none;
      padding:14px;
      position:relative;
      isolation:isolate;
    }
    .modalCard::before{
      content:"";
      position:absolute;top:0;left:10%;right:10%;height:1px;z-index:1;pointer-events:none;
      background:linear-gradient(90deg,transparent,rgba(255,255,255,0.10),transparent);
    }
    .modalCard::after{
      content:"";
      position:absolute;inset:0;z-index:0;pointer-events:none;
      border-radius:inherit;
      background-color:var(--card-overlay-color);
      background-image:var(--card-overlay-image);
      opacity:var(--card-overlay-opacity);
    }
    .modalCard > *{position:relative;z-index:2}
    .modalHead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
    .modalHead .t{font-size:14px;font-weight:700;color:var(--text-title);letter-spacing:.01em}
    .formGrid{display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:10px}
    .field{display:flex;flex-direction:column;gap:6px}
    .field.full{grid-column:1 / -1}
    label{font-size:12px;color:var(--text-muted)}

    .select,input[type="text"],input[type="number"]{
      height:var(--control-h);
      width:100%;
      border-radius:var(--radius-sm);
      border:1px solid rgba(255,255,255,0.08);
      background:linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
      background-color:var(--select-bg);
      color:var(--text-title);
      padding:0 10px;
      outline:none;
      backdrop-filter:blur(12px) saturate(var(--card-saturate));
      -webkit-backdrop-filter:blur(12px) saturate(var(--card-saturate));
      box-shadow:0 6px 16px rgba(0,0,0,0.18),0 0 0 1px rgba(255,255,255,0.03) inset;
      transition:border-color .15s ease, background-color .15s ease, box-shadow .15s ease;
      appearance:none;
    }
    .select:hover{border-color:rgba(255,255,255,0.14)}
    .select:focus,input[type="text"]:focus,input[type="number"]:focus{border-color:var(--accent);box-shadow:0 10px 26px rgba(0,0,0,0.20),0 0 0 3px rgba(59,130,246,0.18)}

    .toggleRow{
      display:flex;align-items:center;justify-content:space-between;gap:10px;
      padding:10px 12px;
      border:1px solid rgba(255,255,255,0.08);
      border-radius:var(--radius-md);
      background:var(--toolbar-group-bg);
      box-shadow:inset 0 1px 0 rgba(255,255,255,0.03);
      transition:border-color var(--motion-fast) var(--easing-standard), background var(--motion-fast) var(--easing-standard);
    }
    .toggleRow:hover{border-color:rgba(59,130,246,0.28)}
    .toggleRow .k{font-size:12px;color:var(--text);opacity:.92}
    .filterList{display:flex;flex-direction:column;gap:8px}
    .filterRow{
      display:flex;flex-wrap:nowrap;align-items:center;gap:8px;
      padding:8px 10px;
      border:1px solid rgba(255,255,255,0.08);
      border-radius:var(--radius-md);
      background:var(--toolbar-group-bg);
      box-shadow:inset 0 1px 0 rgba(255,255,255,0.03);
      overflow-x:auto;
    }
    .filterRow .mini{width:auto;min-width:88px}
    .filterRow .op{width:auto;min-width:70px}
    .filterRow .bp-select{width:auto;flex:0 0 auto;max-width:190px}
    .filterRow .bp-select-btn{width:auto;max-width:190px}
    .filterRow .bp-select.bp-role-logic{max-width:72px}
    .filterRow .bp-select.bp-role-op{max-width:96px}
    .filterRow .val{flex:1;min-width:180px}
    .filterRow .valRange{display:flex;gap:8px;align-items:center;flex:1;min-width:220px}
    .filterRow .valRange .btn{flex:0 0 auto;white-space:nowrap;min-width:74px}
    .filterRow .valRange .sep{color:var(--text-muted);font-size:12px}
    .filterRow .fuzzy{display:flex;align-items:center;gap:6px;color:var(--text-muted);font-size:12px;user-select:none}
    .filterRow .fuzzy input[type="checkbox"]{
      width:16px;height:16px;
      border-radius:6px;
      border:1px solid rgba(255,255,255,0.14);
      background:rgba(255,255,255,0.04);
      box-shadow:0 6px 16px rgba(0,0,0,0.18),0 0 0 1px rgba(255,255,255,0.03) inset;
      appearance:none;
      -webkit-appearance:none;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      cursor:pointer;
      transition:background-color .12s ease, border-color .12s ease, box-shadow .12s ease;
      flex:0 0 auto;
    }
    .filterRow .fuzzy input[type="checkbox"]:hover{
      border-color:rgba(59,130,246,0.34);
      background:rgba(59,130,246,0.08);
    }
    .filterRow .fuzzy input[type="checkbox"]:focus{
      outline:none;
      border-color:var(--accent);
      box-shadow:0 10px 26px rgba(0,0,0,0.20),0 0 0 2px var(--focus-ring-soft),0 0 0 1px var(--focus-ring) inset;
    }
    .filterRow .fuzzy input[type="checkbox"]::after{
      content:"";
      width:8px;height:5px;
      border-left:2px solid rgba(255,255,255,0.0);
      border-bottom:2px solid rgba(255,255,255,0.0);
      transform:rotate(-45deg) translateY(-1px);
      transition:border-color .12s ease;
    }
    .filterRow .fuzzy input[type="checkbox"]:checked{
      border-color:rgba(59,130,246,0.46);
      background:rgba(59,130,246,0.22);
      box-shadow:0 14px 34px rgba(0,0,0,0.24),0 0 0 3px rgba(59,130,246,0.10);
    }
    .filterRow .fuzzy input[type="checkbox"]:checked::after{
      border-left-color:rgba(147,197,253,0.96);
      border-bottom-color:rgba(147,197,253,0.96);
    }
    .filterRow .fuzzy input[type="checkbox"][disabled]{
      opacity:.45;
      cursor:not-allowed;
      box-shadow:none;
    }
    .filterRow .btn{height:32px;padding:0 10px}
    .scrollPanel{
      max-height:220px;
      overflow:auto;
      border:1px solid rgba(255,255,255,0.08);
      border-radius:var(--radius-md);
      padding:8px;
      background:rgba(0,0,0,0.06);
    }
    .barInlineRow{
      display:flex;
      align-items:center;
      gap:8px;
      padding:0;
      border:none;
      background:transparent;
      box-shadow:none;
      overflow:visible;
      min-height:var(--control-h);
    }
    .barInlineRow .valRange{
      display:flex;
      flex-wrap:nowrap;
      gap:8px;
      min-width:0;
      flex:1;
      align-items:center;
      overflow:visible;
      padding:3px;
    }
    .barInlineRow .valRange .sep{color:var(--text-muted);font-size:12px;flex:0 0 auto}
    .barInlineRow .valRange .btn{flex:0 0 auto;white-space:nowrap;min-width:0;padding:0 10px}
    #btnBarPickTime{width:auto}
    #barTimeRangeWrap .valRange .select{
      flex:1 1 0;
      width:auto;
      min-width:0;
    }
    #fBarTimeStartShow, #fBarTimeEndShow{
      user-select:none;
      -webkit-user-select:none;
      caret-color:transparent;
      cursor:pointer;
    }
    .barInlineRow .select,
    .barInlineRow input.select{
      position:relative;
      z-index:1;
      box-sizing:border-box;
    }
    #fBarTimeStep{max-width:110px}
    input[type="date"].select{
      appearance:auto;
      -webkit-appearance:auto;
    }

    #modalSettings, #modalSettings *,
    #modalBarTime, #modalBarTime *,
    #modalAdd, #modalAdd *,
    #modalManage, #modalManage *,
    #panel, #panel *{
      user-select:none;
      -webkit-user-select:none;
      -webkit-tap-highlight-color:transparent;
    }
    #modalSettings input, #modalSettings textarea,
    #modalBarTime input, #modalBarTime textarea,
    #modalAdd input, #modalAdd textarea,
    #modalManage input, #modalManage textarea{
      user-select:text;
      -webkit-user-select:text;
    }
    #modalSettings ::selection,
    #modalBarTime ::selection,
    #modalAdd ::selection,
    #modalManage ::selection,
    #panel ::selection,
    .win-tools ::selection{
      background:transparent;
    }
    .bp-toggle{
      position:relative;
      display:inline-flex;
      width:42px;
      height:22px;
      flex:0 0 auto;
      cursor:pointer;
      user-select:none;
    }
    .bp-toggle input{
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      margin:0;
      opacity:0;
      cursor:pointer;
    }
    .bp-toggle .ui{
      width:42px;height:22px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,0.10);
      background:rgba(255,255,255,0.06);
      position:relative;
      transition:background var(--motion-fast) var(--easing-standard), border-color var(--motion-fast) var(--easing-standard);
    }
    .bp-toggle .ui::after{
      content:"";
      position:absolute;top:50%;left:3px;
      width:16px;height:16px;border-radius:50%;
      background:rgba(226,232,240,0.82);
      transform:translateY(-50%);
      box-shadow:0 4px 12px rgba(0,0,0,0.30);
      transition:left var(--motion-fast) var(--easing-standard), background var(--motion-fast) var(--easing-standard);
      will-change:left;
    }
    .bp-toggle input:checked + .ui,
    .bp-toggle[data-on="1"] .ui{
      background:rgba(59,130,246,0.22);
      border-color:rgba(59,130,246,0.45);
    }
    .bp-toggle input:checked + .ui::after,
    .bp-toggle[data-on="1"] .ui::after{
      left:23px;
      background:rgba(255,255,255,0.92);
    }
    .modalCard .bp-toggle .ui,
    .modalCard .bp-toggle .ui::after{
      transition:none;
    }

    .modalFoot{display:flex;justify-content:flex-end;gap:10px;margin-top:12px}

    #panel{
      position:fixed;top:10px;left:0;z-index:9999998;
      background:var(--toolbar-bg);border:1px solid var(--toolbar-border);border-left:none;border-radius:0 var(--radius-sm) var(--radius-sm) 0;
      color:var(--text);font-size:12.5px;
      backdrop-filter:blur(14px) saturate(var(--card-saturate));-webkit-backdrop-filter:blur(14px) saturate(var(--card-saturate));
      overflow:hidden;transform-origin:top left;
      box-shadow:0 8px 32px rgba(0,0,0,0.32),0 0 0 1px rgba(255,255,255,0.04) inset;
      transform:translateX(calc(-100% + 10px));
      transition:transform var(--motion-slow) var(--easing-standard);
    }
    #panel:hover{transform:translateX(0)}
    #panel:focus-within{transform:translateX(0)}
    #panel-toggle{
      position:absolute;top:0;left:0;width:36px;height:36px;
      display:flex;align-items:center;justify-content:center;
      cursor:pointer;user-select:none;z-index:2;
      color:var(--text-title);font-size:16px;transition:transform .3s;
    }
    #wmCanvas{
      position:fixed;
      inset:0;
      z-index:500000;
      pointer-events:none;
      opacity:0.92;
    }
    #statusBadge{
      position:fixed;
      right:14px;
      top:14px;
      z-index:10000000;
      display:block;
      max-width: 42vw;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(0,0,0,0.28);
      border: 1px solid rgba(255,255,255,0.14);
      color: var(--text-title);
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      pointer-events: none;
      box-shadow: 0 10px 26px rgba(0,0,0,0.18);
      opacity: .92;
    }
    #panel-body{
      padding:10px 14px 12px 42px;display:flex;flex-direction:column;gap:10px;white-space:nowrap;
    }
    .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .stitle{color:var(--text-muted);font-size:11px;white-space:nowrap}
    #panel .select, #panel select{
      background:var(--select-bg);color:var(--text-title);border:1px solid rgba(255,255,255,0.08);
      border-radius:4px;padding:4px 8px;font-size:13px;cursor:pointer;transition:all .3s;
    }
    #panel .bp-select-btn{
      height:var(--control-h);
      border-radius:4px;
      padding:0 8px;
      font-size:12px;
      box-shadow:none;
    }
    #panel .bp-select-caret{border-top-color:rgba(226,232,240,0.62)}
    #panel .bp-select-menu{padding:4px;border-radius:10px}
    #panel .bp-select-item{
      height:26px;
      padding:0 8px;
      border-radius:8px;
      font-size:12px;
    }
    #panel .btn{height:30px;border-radius:8px;padding:0 10px}
    #panel .btn.boat{
      border-radius:999px;
      padding:0;
      min-width: 0;
      width:46px;
      height:24px;
      justify-content:center;
    }

    .bp-select{position:relative;width:100%}
    .bp-select-btn{
      height:var(--control-h);
      width:100%;
      border-radius:var(--radius-sm);
      border:1px solid rgba(255,255,255,0.08);
      background:linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
      background-color:var(--select-bg);
      color:var(--text-title);
      padding:0 10px;
      outline:none;
      display:flex;align-items:center;justify-content:space-between;gap:10px;
      cursor:pointer;
      backdrop-filter:blur(12px) saturate(var(--card-saturate));
      -webkit-backdrop-filter:blur(12px) saturate(var(--card-saturate));
      box-shadow:0 6px 16px rgba(0,0,0,0.18),0 0 0 1px rgba(255,255,255,0.03) inset;
      transition:border-color .15s ease, background-color .15s ease, box-shadow .15s ease;
      user-select:none;
    }
    .bp-select-btn *{user-select:none;-webkit-user-select:none}
    .bp-select-btn:hover{border-color:rgba(255,255,255,0.14)}
    .bp-select-btn:focus{border-color:var(--accent);box-shadow:0 10px 26px rgba(0,0,0,0.20),0 0 0 2px var(--focus-ring-soft),0 0 0 1px var(--focus-ring) inset}
    .bp-select-caret{
      width:0;height:0;
      border-left:5px solid transparent;
      border-right:5px solid transparent;
      border-top:6px solid rgba(226,232,240,0.70);
      opacity:0.9;
      transform:translateY(1px);
      flex:0 0 auto;
    }
    .bp-select-menu{
      position:fixed;
      z-index:99999999;
      min-width:160px;
      max-width:420px;
      max-height:min(320px, calc(100vh - 24px));
      overflow:auto;
      padding:6px;
      border-radius:12px;
      border:1px solid rgba(255,255,255,0.08);
      background:var(--menu-bg);
      backdrop-filter:blur(16px) saturate(var(--card-saturate));
      -webkit-backdrop-filter:blur(16px) saturate(var(--card-saturate));
      box-shadow:0 16px 44px rgba(0,0,0,0.40),0 0 0 1px rgba(255,255,255,0.04) inset;
      user-select:none;
      -webkit-user-select:none;
    }
    .bp-select-item{
      height:30px;
      display:flex;align-items:center;
      padding:0 10px;
      border-radius:10px;
      cursor:pointer;
      color:var(--text-title);
      background:transparent;
      border:1px solid transparent;
      transition:background-color .12s ease, border-color .12s ease;
      white-space:nowrap;
      user-select:none;
      -webkit-user-select:none;
    }
    .bp-select-menu ::selection{background:transparent}
    .bp-select-item:hover{background:var(--menu-hover)}
    .bp-select-item.active{background:var(--menu-hover);border-color:var(--btn-border)}
    .bp-select-item.disabled{
      opacity:.45;
      cursor:not-allowed;
      background:transparent !important;
      border-color:transparent !important;
    }
    .bp-native-hidden{position:absolute !important;left:-99999px !important;top:-99999px !important;width:1px !important;height:1px !important;opacity:0 !important;pointer-events:none !important}
    .bp-date-pop{
      position:fixed;
      z-index:99999999;
      width:262px;
      padding:10px;
      border-radius:14px;
      border:1px solid rgba(255,255,255,0.08);
      background:var(--menu-bg);
      backdrop-filter:blur(16px) saturate(var(--card-saturate));
      -webkit-backdrop-filter:blur(16px) saturate(var(--card-saturate));
      box-shadow:0 16px 44px rgba(0,0,0,0.42),0 0 0 1px rgba(255,255,255,0.04) inset;
      user-select:none;
      -webkit-user-select:none;
    }
    .bp-date-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
    .bp-date-nav{
      width:28px;height:28px;border-radius:10px;
      border:1px solid var(--btn-border);
      background:var(--btn-bg);
      color:var(--text-title);
      display:flex;align-items:center;justify-content:center;
      cursor:pointer;
    }
    .bp-date-nav:hover{border-color:var(--accent);background:var(--btn-hover)}
    .bp-date-title{flex:1;text-align:center;font-size:12px;font-weight:900;color:var(--text-title);letter-spacing:.01em;cursor:pointer;border-radius:10px;padding:6px 8px}
    .bp-date-title:hover{background:rgba(255,255,255,0.05)}
    .bp-date-grid{display:grid;grid-template-columns:repeat(7, 1fr);gap:4px}
    .bp-date-dow{font-size:11px;color:var(--text-muted);text-align:center;padding:2px 0}
    .bp-date-day{
      height:30px;border-radius:10px;
      border:1px solid transparent;
      background:transparent;
      color:var(--text-title);
      cursor:pointer;
      display:flex;align-items:center;justify-content:center;
      font-size:12px;
      transition:background-color .12s ease, border-color .12s ease;
    }
    .bp-date-day:hover{background:var(--menu-hover)}
    .bp-date-day.muted{opacity:.45}
    .bp-date-day.sel{background:rgba(59,130,246,0.20);border-color:rgba(59,130,246,0.38);color:#93c5fd;font-weight:800}
    .bp-date-day.today{border-color:rgba(255,255,255,0.10)}

    @media (max-width: 720px){
      .formGrid{grid-template-columns:1fr}
      .win{width:92vw;height:46vh}
    }
  </style>
</head>
<body>
  <div id="statusBadge">准备就绪</div>
  <canvas id="wmCanvas"></canvas>
  <div id="app">
    <div class="workspace">
      <div id="desk">
        <canvas id="gridGuideCanvas"></canvas>
        <div id="ghost"></div>
      </div>
      <div class="overlay" id="overlay"><div class="spinner"></div></div>
    </div>
  </div>

  <div id="panel">
    <div id="panel-toggle" title="控制中心">&#9881;</div>
    <div id="panel-body">
      <div class="row">
        <div class="boatWrap" id="boatWrap" data-on="0">
          <span class="boatText off">显示</span>
          <button class="btn boat" id="btnEditMode" role="switch" aria-checked="false" data-on="0">
            <span class="boat-thumb" aria-hidden="true"></span>
          </button>
          <span class="boatText on">编辑</span>
        </div>
      </div>
      <div class="row">
        <button class="btn primary" id="btnAdd"><span class="dot"></span>添加</button>
        <button class="btn" id="btnRefreshAll"><span class="dot"></span>刷新</button>
        <button class="btn" id="btnOpenSettings"><span class="dot"></span>设置</button>
      </div>
      <div class="row">
        <span class="stitle">主题</span>
        <select id="echartsThemeSelect" class="select">__THEME_OPTS__</select>
        <span class="stitle">显示模式</span>
        <select id="styleSelect" class="select">
          <option value="acrylic" selected>亚克力</option>
          <option value="frosted">磨砂玻璃</option>
          <option value="glass">水晶玻璃</option>
          <option value="glass-dark">暗夜玻璃</option>
          <option value="neon">霓虹光效</option>
          <option value="cyber">赛博朋克</option>
          <option value="paper">纸质质感</option>
          <option value="transparent">透明</option>
          <option value="opaque">不透明</option>
          <option value="flat">极简扁平</option>
          <option value="executive">商务深空</option>
        </select>
      </div>
    </div>
  </div>
  <span id="statusText" style="display:none">准备就绪</span>

  <div class="modal" id="modalAdd">
    <div class="modalCard">
      <div class="modalHead">
        <div class="t">添加图表</div>
        <button class="btn" id="btnCloseAdd" onclick="try{if(window.closeAnyModal){closeAnyModal('modalAdd');}else{document.getElementById('modalAdd').classList.remove('show');document.body.classList.remove('modal-open');}}catch(e){}">关闭</button>
      </div>
      <div class="formGrid">
        <div class="field full">
          <label>图表名称</label>
          <input class="select" type="text" id="fName" placeholder="请输入图表名称" />
        </div>
        <div class="field">
          <label>图表类型</label>
        <select class="select" id="fType"><option value="">加载中…</option></select>
        </div>

        <div class="field full">
          <div style="font-weight:800;color:var(--text-title);margin-top:2px">数据设置</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:2px">根据图表类型自动切换可用字段</div>
        </div>

        <div class="field" data-scope="xy">
          <label>横坐标字段</label>
          <select class="select" id="fXField"><option value="">加载中…</option></select>
        </div>
        <div class="field" data-scope="xy">
          <label>纵坐标统计</label>
          <select class="select" id="fYAgg"><option value="">加载中…</option></select>
        </div>
        <div class="field full" data-scope="xy">
          <label>分组字段</label>
          <select class="select" id="fGroup"><option value="">加载中…</option></select>
        </div>

        <div class="field full" data-scope="bar">
          <label>横坐标参数</label>
          <select class="select" id="fBarXKind">
            <option value="time" selected>时间</option>
            <option value="score">评分</option>
            <option value="rating">评星</option>
            <option value="iso">ISO</option>
            <option value="shutter">快门</option>
            <option value="fnumber">光圈</option>
            <option value="focal_length">焦距</option>
            <option value="species">物种</option>
            <option value="order">目</option>
            <option value="family">科</option>
            <option value="genus">属</option>
            <option value="location">地点</option>
            <option value="label">色标</option>
          </select>
        </div>
        <div class="field full" data-scope="bar" id="barTimeTypeWrap">
          <label>时间类型</label>
          <select class="select" id="fBarTimeType">
            <option value="shot_time" selected>拍摄时间</option>
            <option value="imported_at">导入时间</option>
            <option value="created_at">创建时间</option>
          </select>
        </div>
        <div class="field full" data-scope="bar">
          <label>纵坐标</label>
          <select class="select" id="fBarYKind">
            <option value="count" selected>图片数量</option>
            <option value="new_species">加新次数</option>
            <option value="species_count">鸟种数</option>
          </select>
        </div>
        <div class="field full" data-scope="bar" id="barTimeRangeWrap">
          <label>时间范围</label>
          <div class="barInlineRow">
            <div class="valRange">
              <input class="select" type="text" id="fBarTimeStartShow" readonly />
              <span class="sep">至</span>
              <input class="select" type="text" id="fBarTimeEndShow" readonly />
              <button class="btn" id="btnBarPickTime" type="button">选择范围</button>
            </div>
          </div>
        </div>
        <div class="field full" data-scope="bar" id="barTimeUnitWrap">
          <label>间隔</label>
          <div class="barInlineRow">
            <div class="valRange">
              <input class="select" type="number" id="fBarTimeStep" min="1" step="1" value="1" />
              <select class="select" id="fBarTimeUnit">
                <option value="day" selected>天</option>
                <option value="month">月</option>
                <option value="year">年</option>
              </select>
            </div>
          </div>
        </div>
        <div class="field full" data-scope="bar" id="barHideEmptyTimeWrap">
          <label>显示选项</label>
          <div class="barInlineRow">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px;color:var(--text-muted);">
              <input type="checkbox" id="fBarHideEmptyTime" style="width:16px;height:16px;cursor:pointer;" />
              <span>隐藏无数据的时间</span>
            </label>
          </div>
        </div>
        <div class="field" data-scope="bar" id="barLocLevelWrap">
          <label>地点层级(暂仅 UI)</label>
          <select class="select" id="fBarLocLevel">
            <option value="country" selected>国</option>
            <option value="province">省</option>
            <option value="city">市</option>
          </select>
        </div>
        <div class="field full" data-scope="bar">
          <div style="font-weight:800;color:var(--text-title);margin-top:2px">筛选</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:2px">参照图库筛选面板，支持 与 / 或 / 非；横坐标字段不会出现在筛选项中</div>
        </div>
        <div class="field full" data-scope="bar">
          <div class="scrollPanel">
            <div id="barFilterList" class="filterList"></div>
          </div>
          <div class="row" style="justify-content:flex-start;gap:10px;margin-top:8px">
            <button class="btn" id="btnBarAddCond" type="button">添加条件</button>
            <button class="btn" id="btnBarClearCond" type="button">清空</button>
          </div>
        </div>

        <!-- 数据图（Number）配置 -->
        <div class="field full" data-scope="number">
          <label>数据类型</label>
          <select class="select" id="fNumberType">
            <option value="count" selected>图片数量</option>
            <option value="species_count">鸟种数</option>
            <option value="new_species">加新数量</option>
          </select>
        </div>
        <div class="field full" data-scope="number">
          <label>时间类型</label>
          <select class="select" id="fNumberTimeType">
            <option value="shot_time" selected>拍摄时间</option>
            <option value="imported_at">导入时间</option>
            <option value="created_at">创建时间</option>
          </select>
        </div>
        <div class="field full" data-scope="number">
          <label>时间范围</label>
          <div class="barInlineRow">
            <div class="valRange">
              <input class="select" type="text" id="fNumberTimeStartShow" readonly />
              <span class="sep">至</span>
              <input class="select" type="text" id="fNumberTimeEndShow" readonly />
              <button class="btn" id="btnNumberPickTime" type="button">选择范围</button>
            </div>
          </div>
        </div>
        <div class="field full" data-scope="number">
          <div style="font-weight:800;color:var(--text-title);margin-top:2px">筛选</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:2px">参照图库筛选面板，支持 与 / 或 / 非</div>
        </div>
        <div class="field full" data-scope="number">
          <div class="scrollPanel">
            <div id="numberFilterList" class="filterList"></div>
          </div>
          <div class="row" style="justify-content:flex-start;gap:10px;margin-top:8px">
            <button class="btn" id="btnNumberAddCond" type="button">添加条件</button>
            <button class="btn" id="btnNumberClearCond" type="button">清空</button>
          </div>
        </div>

        <div class="field full" data-scope="pie">
          <label>分类字段</label>
          <select class="select" id="fPieCat">
            <option value="order">目</option>
            <option value="family">科</option>
            <option value="genus">属</option>
            <option value="species" selected>种</option>
            <option value="rating">评星</option>
            <option value="label">色标</option>
            <option value="location">地点</option>
          </select>
        </div>
        <div class="field full" data-scope="pie">
          <label>数值统计</label>
          <select class="select" id="fPieAgg">
            <option value="count" selected>图片数量</option>
            <option value="species_count">鸟种数</option>
          </select>
        </div>
        <div class="field full" data-scope="pie">
          <label>时间类型</label>
          <select class="select" id="fPieTimeType">
            <option value="all" selected>所有时间</option>
            <option value="shot_time">拍摄时间</option>
            <option value="imported_at">导入时间</option>
            <option value="created_at">创建时间</option>
          </select>
        </div>
        <div class="field full" data-scope="pie" id="pieTimeRangeWrap" style="display:none;">
          <label>时间范围</label>
          <div class="barInlineRow">
            <div class="valRange">
              <input class="select" type="text" id="fPieTimeStartShow" readonly />
              <span class="sep">至</span>
              <input class="select" type="text" id="fPieTimeEndShow" readonly />
              <button class="btn" id="btnPiePickTime" type="button">选择范围</button>
            </div>
          </div>
        </div>
        <div class="field full" data-scope="pie">
          <div style="font-weight:800;color:var(--text-title);margin-top:2px">筛选</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:2px">参照图库筛选面板，支持 与 / 或 / 非；分类字段不会出现在筛选项中</div>
        </div>
        <div class="field full" data-scope="pie">
          <div class="scrollPanel">
            <div id="pieFilterList" class="filterList"></div>
          </div>
          <div class="row" style="justify-content:flex-start;gap:10px;margin-top:8px">
            <button class="btn" id="btnPieAddCond" type="button">添加条件</button>
            <button class="btn" id="btnPieClearCond" type="button">清空</button>
          </div>
        </div>

        <div class="field full" data-scope="tree">
          <label>显示层级</label>
          <div class="checkbox-group">
            <label class="checkbox-label"><input type="checkbox" id="fTreeLevelOrder" checked /><span>目</span></label>
            <label class="checkbox-label"><input type="checkbox" id="fTreeLevelFamily" checked /><span>科</span></label>
            <label class="checkbox-label"><input type="checkbox" id="fTreeLevelGenus" checked /><span>属</span></label>
            <label class="checkbox-label"><input type="checkbox" id="fTreeLevelSpecies" checked /><span>种</span></label>
          </div>
        </div>
        <div class="field full" data-scope="tree">
          <label>显示图片数量</label>
          <label class="checkbox-label">
            <input type="checkbox" id="fTreeShowCount" checked />
            <span>在节点上显示对应物种的图片数量</span>
          </label>
        </div>
        <div class="field full" data-scope="tree">
          <label>树图布局</label>
          <select class="select" id="fTreeLayout">
            <option value="LR" selected>从左到右</option>
            <option value="RL">从右到左</option>
            <option value="TB">从上到下</option>
            <option value="BT">从下到上</option>
            <option value="radial">径向</option>
          </select>
        </div>
        <div class="field full" data-scope="tree">
          <label>时间范围</label>
          <select class="select" id="fTreeTimeType">
            <option value="all" selected>全部时间</option>
            <option value="custom">自定义范围</option>
          </select>
        </div>
        <div class="field full" data-scope="tree" id="treeTimeRangeWrap" style="display:none;">
          <label>时间范围</label>
          <div class="barInlineRow">
            <div class="valRange">
              <input class="select" type="text" id="fTreeTimeStartShow" readonly />
              <span class="sep">至</span>
              <input class="select" type="text" id="fTreeTimeEndShow" readonly />
              <button class="btn" id="btnTreePickTime" type="button">选择范围</button>
            </div>
          </div>
        </div>
        <div class="field full" data-scope="tree">
          <div style="font-weight:800;color:var(--text-title);margin-top:2px">筛选</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:2px">参照图库筛选面板，支持 与 / 或 / 非；分类字段不会出现在筛选项中</div>
        </div>
        <div class="field full" data-scope="tree">
          <div class="scrollPanel">
            <div id="treeFilterList" class="filterList"></div>
          </div>
          <div class="row" style="justify-content:flex-start;gap:10px;margin-top:8px">
            <button class="btn" id="btnTreeAddCond" type="button">添加条件</button>
            <button class="btn" id="btnTreeClearCond" type="button">清空</button>
          </div>
        </div>

        <div class="field full" data-scope="scatter">
          <label>X轴字段</label>
          <select class="select" id="fSX">
            <option value="score">评分</option>
            <option value="rating" selected>评星</option>
            <option value="iso">ISO</option>
            <option value="shutter">快门</option>
            <option value="fnumber">光圈</option>
            <option value="focal_length">焦距</option>
            <option value="shot_time">拍摄时间</option>
            <option value="created_at">创建时间</option>
          </select>
        </div>
        <div class="field full" data-scope="scatter">
          <label>Y轴字段</label>
          <select class="select" id="fSY">
            <option value="count" selected>图片数量</option>
            <option value="species_count">鸟种数</option>
            <option value="new_count">加新数量</option>
          </select>
        </div>
        <div class="field full" data-scope="scatter">
          <label>气泡大小</label>
          <label class="checkbox-label">
            <input type="checkbox" id="fScatterAutoSize" />
            <span>根据Y轴数据自动调整</span>
          </label>
        </div>
        <div class="field full" data-scope="scatter" id="scatterTimeRangeWrap" style="display:none;">
          <label>时间范围</label>
          <div class="barInlineRow">
            <div class="valRange">
              <input class="select" type="text" id="fScatterTimeStartShow" readonly />
              <span class="sep">至</span>
              <input class="select" type="text" id="fScatterTimeEndShow" readonly />
              <button class="btn" id="btnScatterPickTime" type="button">选择范围</button>
            </div>
          </div>
        </div>
        <div class="field full" data-scope="scatter" id="scatterTimeGroupWrap" style="display:none;">
          <label>时间分组</label>
          <select class="select" id="fScatterTimeGroup">
            <option value="day" selected>按天</option>
            <option value="week">按周</option>
            <option value="month">按月</option>
            <option value="year">按年</option>
          </select>
        </div>
        <div class="field full" data-scope="scatter">
          <div style="font-weight:800;color:var(--text-title);margin-top:2px">筛选</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:2px">参照图库筛选面板，支持 与 / 或 / 非；X轴和Y轴字段不会出现在筛选项中</div>
        </div>
        <div class="field full" data-scope="scatter">
          <div class="scrollPanel">
            <div id="scatterFilterList" class="filterList"></div>
          </div>
          <div class="row" style="justify-content:flex-start;gap:10px;margin-top:8px">
            <button class="btn" id="btnScatterAddCond" type="button">添加条件</button>
            <button class="btn" id="btnScatterClearCond" type="button">清空</button>
          </div>
        </div>
      </div>
      <div class="modalFoot">
        <button class="btn" id="btnCancelAdd" onclick="try{if(window.closeAnyModal){closeAnyModal('modalAdd');}else{document.getElementById('modalAdd').classList.remove('show');document.body.classList.remove('modal-open');}}catch(e){}">取消</button>
        <button class="btn primary" id="btnSubmitAdd">创建</button>
      </div>
    </div>
  </div>

  <div class="modal" id="modalBarTime">
    <div class="modalCard" style="width:min(560px, calc(100vw - 24px));">
      <div class="modalHead">
        <div class="t">选择时间范围</div>
        <button class="btn" id="btnCloseBarTime" onclick="try{closeModal('modalBarTime');}catch(e){}">关闭</button>
      </div>
      <div class="formGrid">
        <div class="field full">
          <label>动态时间</label>
          <div class="row" style="justify-content:flex-start;gap:10px;flex-wrap:wrap">
            <button class="btn" id="btnBarQuickNow" type="button">至今</button>
            <button class="btn" id="btnBarQuickToday" type="button">当天</button>
            <button class="btn" id="btnBarQuickWeek" type="button">近一周</button>
            <button class="btn" id="btnBarQuickMonth" type="button">近一月</button>
            <button class="btn" id="btnBarQuickYear" type="button">近一年</button>
          </div>
        </div>
        <div class="field">
          <label>开始日期</label>
          <input class="select" type="text" id="barTimePickStart" readonly />
        </div>
        <div class="field">
          <label>结束日期</label>
          <input class="select" type="text" id="barTimePickEnd" readonly />
        </div>
      </div>
      <div class="modalFoot">
        <button class="btn" id="btnCancelBarTime" onclick="try{closeModal('modalBarTime');}catch(e){}">取消</button>
        <button class="btn primary" id="btnApplyBarTime" type="button">应用</button>
      </div>
    </div>
  </div>

  <div class="modal" id="modalSettings">
    <div class="modalCard">
      <div class="modalHead">
        <div class="t">设置</div>
        <button class="btn" id="btnCloseSettings" onclick="try{if(window.closeAnyModal){closeAnyModal('modalSettings');}else{document.getElementById('modalSettings').classList.remove('show');document.body.classList.remove('modal-open');}}catch(e){}">关闭</button>
      </div>
      <div class="formGrid">
        <div class="field">
          <label>主题</label>
          <select class="select" id="themeSelect">
            <option value="follow">跟随软件主题</option>
            <option value="dark">深色</option>
            <option value="light">浅色</option>
          </select>
        </div>
        <div class="field">
          <label>字体大小</label>
          <input class="select" type="number" id="fontSize" min="10" max="22" step="1" />
        </div>

        <div class="field full">
          <div class="toggleRow"><div class="k">显示标题</div><label class="bp-toggle"><input type="checkbox" id="cbTitle" /><span class="ui"></span></label></div>
        </div>
        <div class="field full">
          <div class="toggleRow"><div class="k">显示图例</div><label class="bp-toggle"><input type="checkbox" id="cbLegend" /><span class="ui"></span></label></div>
        </div>
        <div class="field full">
          <div class="toggleRow"><div class="k">动画</div><label class="bp-toggle"><input type="checkbox" id="cbAnim" /><span class="ui"></span></label></div>
        </div>
        <div class="field full">
          <div class="toggleRow"><div class="k">鼠标离开停止刷新</div><label class="bp-toggle"><input type="checkbox" id="cbPauseRefresh" /><span class="ui"></span></label></div>
        </div>
        <div class="field full">
          <div class="toggleRow"><div class="k">忽略无图片日期</div><label class="bp-toggle"><input type="checkbox" id="cbIgnoreEmptyDates" /><span class="ui"></span></label></div>
        </div>
        <div class="field full">
          <div class="toggleRow"><div class="k">水印</div><label class="bp-toggle"><input type="checkbox" id="cbWatermark" /><span class="ui"></span></label></div>
        </div>
        <div class="field full">
          <label>水印内容</label>
          <input class="select" id="wmText" placeholder="输入水印文字" />
        </div>
        <div class="field">
          <label>水印字体大小</label>
          <input class="select" type="number" id="wmSize" min="10" max="64" step="1" />
        </div>
        <div class="field full">
          <div class="toggleRow"><div class="k">GPU 渲染(偏好)</div><label class="bp-toggle"><input type="checkbox" id="cbGpu" /><span class="ui"></span></label></div>
        </div>
      </div>
    </div>
  </div>

  <div class="modal" id="modalManage">
    <div class="modalCard">
      <div class="modalHead">
        <div class="t">图表管理</div>
        <button class="btn" id="btnCloseManage" onclick="try{if(window.closeAnyModal){closeAnyModal('modalManage');}else{document.getElementById('modalManage').classList.remove('show');document.body.classList.remove('modal-open');}}catch(e){}">关闭</button>
      </div>
      <div id="manageList" style="display:flex;flex-direction:column;gap:10px"></div>
    </div>
  </div>

  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script src="data/echart/echarts.min.js"></script>
  <script>__REGISTER_CODE__</script>
  <script>
    try{ window.__bpScriptOk = 1; }catch(e){}
    const $ = (id) => document.getElementById(id);
    const overlay = $("overlay");
    const statusText = $("statusText");
    const statusBadge = $("statusBadge");
    const wmCanvas = $("wmCanvas");
    const desk = $("desk");

    try{
      window.__bpDebug = !!window.__bpDebug;
    }catch(e){}
    window.addEventListener("error", (ev) => {
      try{
        const msg = (ev && ev.message) ? String(ev.message) : "unknown";
        const src = (ev && ev.filename) ? String(ev.filename).split("/").pop() : "";
        const ln = (ev && ev.lineno) ? String(ev.lineno) : "";
        const col = (ev && ev.colno) ? String(ev.colno) : "";
        const txt = "JS错误: " + msg + (src ? (" @" + src + ":" + ln + ":" + col) : "");
        try{ if(statusText) statusText.textContent = txt; }catch(e){}
        try{ if(window.__bpDebug && statusBadge) statusBadge.textContent = txt; }catch(e){}
      }catch(e){}
    });
    window.addEventListener("unhandledrejection", (ev) => {
      try{
        const r = ev && ev.reason;
        const msg = (r && r.message) ? String(r.message) : String(r || "unknown");
        const txt = "Promise错误: " + msg;
        try{ if(statusText) statusText.textContent = txt; }catch(e){}
        try{ if(window.__bpDebug && statusBadge) statusBadge.textContent = txt; }catch(e){}
      }catch(e){}
    });
    function setBadge(t){
      try{
        if(!statusBadge) return;
        statusBadge.textContent = String(t || "");
      }catch(e){}
    }
    try{ setBadge("脚本启动…"); }catch(e){}

    function setLoading(v){ v ? overlay.classList.add("show") : overlay.classList.remove("show"); }
    function setStatus(t){
      const v = String(t || "");
      try{ statusText.textContent = v; }catch(e){}
      try{ setBadge(v); }catch(e){}
    }
    function setDisabled(id, v){
      const el = $(id);
      if(!el) return;
      try{ el.disabled = !!v; }catch(e){}
    }

    function perfNow(){
      try{
        if(window.performance && typeof performance.now === "function"){ return performance.now(); }
      }catch(e){}
      return Date.now();
    }
    function afterPaint(fn){
      try{
        requestAnimationFrame(() => {
          requestAnimationFrame(() => { try{ fn(); }catch(e){} });
        });
      }catch(e){
        try{ setTimeout(() => { try{ fn(); }catch(ex){} }, 0); }catch(ex){}
      }
    }
    function probeNextFrame(label){
      const t0 = perfNow();
      try{
        requestAnimationFrame(() => {
          const dt = perfNow() - t0;
          if(dt > 350){
            try{ slowLog(String(label || "UI") + " 延迟", dt); }catch(e){}
          }
        });
      }catch(e){}
    }
    let __bpRerenderJobId = 0;
    let __bpRerenderPending = false;
    function requestRerenderAllCharts(reason){
      __bpRerenderJobId += 1;
      const jobId = __bpRerenderJobId;
      if(__bpRerenderPending) return;
      __bpRerenderPending = true;
      afterPaint(() => {
        __bpRerenderPending = false;
        try{ rerenderAllChartsYielding(jobId, reason); }catch(e){}
      });
    }

    let __bpPrefSaveTimer = null;
    let __bpPrefSaveInFlight = false;
    let __bpPrefSavePending = false;
    async function __bpSavePreferencesNow(){
      if(!bridge){
        setStatus("桥接未就绪");
        return;
      }
      const t0 = perfNow();
      const theme = $("themeSelect").value || "follow";
      const fontSize = Number($("fontSize").value || 12);
      watermarkOn = !!$("cbWatermark").checked;
      try{ watermarkText = String($("wmText").value || "").trim(); }catch(e){ watermarkText = ""; }
      try{ watermarkFontSize = clamp(Number($("wmSize").value || 22), 10, 64); }catch(e){ watermarkFontSize = 22; }
      const next = {
        show_title: !!$("cbTitle").checked,
        show_legend: !!$("cbLegend").checked,
        enable_animation: !!$("cbAnim").checked,
        pause_refresh_on_mouse_leave: !!$("cbPauseRefresh").checked,
        ignore_empty_dates: !!$("cbIgnoreEmptyDates").checked,
        echarts_theme: String(currentTheme || "dark"),
        window_style: String(windowStyle || "acrylic"),
        font_size: Math.max(10, Math.min(22, fontSize)),
        watermark_enabled: !!watermarkOn,
        watermark_text: watermarkText,
        watermark_font_size: watermarkFontSize
      };
      const gpuEnabled = !!$("cbGpu").checked;
      setStatus("保存中…");
      let r = await bridgeCall(bridge, "set_preferences", {theme, options: next, gpu_enabled: gpuEnabled}, token);
      if(!r.ok){
        const [r1, r2, r3] = await Promise.all([
          bridgeCall(bridge, "set_theme", {theme}, token),
          bridgeCall(bridge, "set_display_options", {options: next}, token),
          bridgeCall(bridge, "set_gpu", {enabled: gpuEnabled}, token),
        ]);
        r = {ok: !!(r1.ok && r2.ok && r3.ok), error: (r.error || r1.error || r2.error || r3.error || "fallback_failed")};
      }
      try{ slowLog("自动保存", perfNow() - t0); }catch(e){}
      if(!r.ok){
        setStatus("保存失败: " + String(r.error || "unknown"));
        return;
      }
      state.theme = theme;
      state.display_options = next;
      state.gpu_rendering_enabled = gpuEnabled;
      setStatus("已保存");
    }
    function schedulePreferencesSave(){
      if(__bpPrefSaveTimer){ clearTimeout(__bpPrefSaveTimer); }
      __bpPrefSaveTimer = setTimeout(async () => {
        if(__bpPrefSaveInFlight){
          __bpPrefSavePending = true;
          return;
        }
        __bpPrefSaveInFlight = true;
        try{
          await __bpSavePreferencesNow();
        }finally{
          __bpPrefSaveInFlight = false;
        }
        if(__bpPrefSavePending){
          __bpPrefSavePending = false;
          schedulePreferencesSave();
        }
      }, 280);
    }

    let __bpWmTimer = null;
    function schedulePageWatermark(){
      const jobId = (window.__bpWmJobId = (window.__bpWmJobId || 0) + 1);
      if(!wmCanvas) return;
      if(!watermarkOn){
        try{ wmCanvas.style.display = "none"; }catch(e){}
        if(__bpWmTimer){ clearTimeout(__bpWmTimer); __bpWmTimer = null; }
        return;
      }
      try{ wmCanvas.style.display = "block"; }catch(e){}
      if(__bpWmTimer){ clearTimeout(__bpWmTimer); }
      __bpWmTimer = setTimeout(() => {
        afterPaint(() => { try{ applyPageWatermark(jobId); }catch(e){} });
      }, 120);
    }
    let __bpLastSlowLog = 0;
    function slowLog(msg, ms){
      const t = Math.round(Number(ms || 0));
      if(!(t > 350)) return;
      const now = perfNow();
      if(now - __bpLastSlowLog < 600) return;
      __bpLastSlowLog = now;
      const prev = String((statusText && statusText.textContent) ? statusText.textContent : "");
      try{ statusText.textContent = String(msg || "") + " " + t + "ms"; }catch(e){}
      try{ setBadge(String(msg || "") + " " + t + "ms"); }catch(e){}
      setTimeout(() => {
        try{
          if(statusText && String(statusText.textContent || "") === (String(msg || "") + " " + t + "ms")){
            statusText.textContent = prev || "就绪";
          }
        }catch(e){}
      }, 1200);
    }
    function syncModalOpenFlag(){
      try{
        const anyOpen = !!document.querySelector(".modal.show");
        document.body.classList.toggle("modal-open", anyOpen);
      }catch(e){}
    }
    function openModal(id){
      const el = $(id);
      if(!el){ setStatus("窗口不存在"); return; }
      el.classList.add("show");
      syncModalOpenFlag();
    }
    function closeModal(id){
      const el = $(id);
      if(!el) return;
      el.classList.remove("show");
      syncModalOpenFlag();
    }
    function closeAnyModal(id){ closeModal(id); }
    function setAddModalMode(mode){
      try{
        const t = document.querySelector("#modalAdd .modalHead .t");
        if(t) t.textContent = (mode === "edit") ? "编辑图表" : "添加图表";
      }catch(e){}
      try{
        const b = $("btnSubmitAdd");
        if(b) b.textContent = (mode === "edit") ? "保存" : "创建";
      }catch(e){}
    }
    function openAddModal(){
      if(!editMode){
        try{ setStatus("请先开启编辑模式"); }catch(e){}
        return;
      }
      editingChartId = null;
      setAddModalMode("add");
      openModal("modalAdd");
      try{ syncAddFields(); }catch(e){}
      try{
        const tsel = $("fType");
        if(tsel && (!tsel.options || tsel.options.length <= 1) && bridge){
          bootstrap();
        }
      }catch(e){}
    }
    async function openEditChart(chartId){
      const cid = String(chartId || "");
      const c = chartsById.get(cid);
      if(!c) return;
      if(bridge && !state){
        try{ await bootstrap(); }catch(e){}
      }
      editingChartId = cid;
      setAddModalMode("edit");
      openModal("modalAdd");
      try{
        $("fName").value = String(c.name || "");
      }catch(e){}
      try{
        const t = $("fType");
        if(t){ t.value = String(c.type || "bar"); refreshSelectLabel(t); }
      }catch(e){}
      try{
      }catch(e){}
      try{ syncAddFields(); }catch(e){}
      const opt = c.options || {};
      const scope = pickTypeScopeByOptions(String(c.type || ""), opt);
      try{ syncAddFields(scope); }catch(e){}
      if(scope === "bar"){
        try{ barEnsureInit(); }catch(e){}
        try{ barLoadFromOptions(opt); }catch(e){}
      }else if(scope === "number"){
        try{ numberEnsureInit(); }catch(e){}
        try{ numberLoadFromOptions(opt); }catch(e){}
      }else if(scope === "xy"){
        try{ $("fXField").value = String(opt.x_field || ""); refreshSelectLabel($("fXField")); }catch(e){}
        try{ $("fYAgg").value = String(opt.y_agg || "count"); refreshSelectLabel($("fYAgg")); }catch(e){}
        try{ $("fGroup").value = String(opt.group_field || ""); refreshSelectLabel($("fGroup")); }catch(e){}
      }else if(scope === "pie"){
        try{ pieEnsureInit(); }catch(e){}
        try{ pieLoadFromOptions(opt); }catch(e){}
      }else if(scope === "tree"){
        try{ treeEnsureInit(); }catch(e){}
        try{ treeLoadFromOptions(opt); }catch(e){}
      }else if(scope === "scatter"){
        try{ scatterEnsureInit(); }catch(e){}
        try{ scatterLoadFromOptions(opt); }catch(e){}
      }
    }
    function openManageModal(){ openModal("modalManage"); try{ refreshManageList(); }catch(e){} }
    function openSettingsModal(){
      openModal("modalSettings");
    }

    let activeSelectMenu = null;
    let activeSelectBtn = null;
    function closeActiveSelect(){
      if(activeSelectMenu){
        try{ activeSelectMenu.remove(); }catch(e){}
      }
      activeSelectMenu = null;
      activeSelectBtn = null;
    }
    function openSelectMenu(btn, selectEl){
      closeActiveSelect();
      const menu = document.createElement("div");
      menu.className = "bp-select-menu";
      menu.addEventListener("mousedown", (ev) => { ev.preventDefault(); }, true);
      menu.addEventListener("mousemove", (ev) => { if(ev.buttons === 1){ ev.preventDefault(); } }, true);
      menu.addEventListener("selectstart", (ev) => { ev.preventDefault(); }, true);
      const opts = Array.from(selectEl.options || []);
      const current = selectEl.value;
      for(const o of opts){
        const item = document.createElement("div");
        const dis = !!o.disabled;
        item.className = "bp-select-item" + (o.value === current ? " active" : "") + (dis ? " disabled" : "");
        item.textContent = o.textContent || o.value || "";
        item.addEventListener("pointerdown", (ev) => { ev.preventDefault(); ev.stopPropagation(); });
        if(!dis){
          item.addEventListener("click", () => {
            selectEl.value = o.value;
            btn.querySelector("[data-label]").textContent = o.textContent || o.value || "";
            try{ selectEl.dispatchEvent(new Event("change", {bubbles:true})); }catch(e){}
            closeActiveSelect();
          });
        }
        menu.appendChild(item);
      }
      document.body.appendChild(menu);
      const r = btn.getBoundingClientRect();
      const mw = Math.max(r.width, 180);
      menu.style.minWidth = mw + "px";
      const mh = Math.min(320, window.innerHeight - 24);
      const rect = menu.getBoundingClientRect();
      let top = r.bottom + 6;
      if(top + rect.height > window.innerHeight - 8){
        top = Math.max(8, r.top - rect.height - 6);
      }
      let left = r.left;
      if(left + rect.width > window.innerWidth - 8){
        left = Math.max(8, window.innerWidth - rect.width - 8);
      }
      menu.style.left = Math.round(left) + "px";
      menu.style.top = Math.round(top) + "px";
      activeSelectMenu = menu;
      activeSelectBtn = btn;
    }
    function upgradeSelect(selectEl){
      if(!selectEl || selectEl.__bpUpgraded) return;
      selectEl.__bpUpgraded = true;
      selectEl.classList.add("bp-native-hidden");
      const wrap = document.createElement("div");
      wrap.className = "bp-select";
      try{
        const role = String(selectEl.getAttribute("data-role") || "").trim();
        if(role) wrap.classList.add("bp-role-" + role);
      }catch(e){}
      const btn = document.createElement("div");
      btn.className = "bp-select-btn";
      btn.tabIndex = 0;
      const label = document.createElement("div");
      label.setAttribute("data-label", "1");
      label.style.flex = "1 1 auto";
      label.style.overflow = "hidden";
      label.style.textOverflow = "ellipsis";
      label.style.whiteSpace = "nowrap";
      const caret = document.createElement("div");
      caret.className = "bp-select-caret";
      const curOpt = selectEl.options && selectEl.selectedIndex >= 0 ? selectEl.options[selectEl.selectedIndex] : null;
      label.textContent = (curOpt && (curOpt.textContent || curOpt.value)) || selectEl.value || "";
      btn.appendChild(label);
      btn.appendChild(caret);
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if(activeSelectBtn === btn){ closeActiveSelect(); return; }
        openSelectMenu(btn, selectEl);
      });
      btn.addEventListener("keydown", (ev) => {
        if(ev.key === "Enter" || ev.key === " "){
          ev.preventDefault();
          btn.click();
        }
        if(ev.key === "Escape"){
          closeActiveSelect();
        }
      });
      wrap.appendChild(btn);
      selectEl.parentNode.insertBefore(wrap, selectEl);
      wrap.appendChild(selectEl);
    }
    function upgradeAllSelects(){
      document.querySelectorAll("select.select").forEach(upgradeSelect);
      document.addEventListener("click", (ev) => {
        if(!activeSelectMenu) return;
        const t = ev.target;
        if(activeSelectMenu.contains(t)) return;
        if(activeSelectBtn && activeSelectBtn.contains(t)) return;
        closeActiveSelect();
      }, true);
      window.addEventListener("resize", () => closeActiveSelect());
      window.addEventListener("scroll", (ev) => {
        if(!activeSelectMenu) return;
        const t = ev && ev.target;
        if(t && activeSelectMenu.contains(t)) return;
        closeActiveSelect();
      }, true);
    }

    let activeDatePop = null;
    function closeActiveDatePop(){
      if(activeDatePop && activeDatePop.el){
        try{ activeDatePop.el.remove(); }catch(e){}
      }
      activeDatePop = null;
    }
    function parseYmd(s){
      const t = String(s || "").trim();
      const m = t.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
      if(!m) return null;
      const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
      if(!y || mo < 1 || mo > 12 || d < 1 || d > 31) return null;
      const dt = new Date(y, mo - 1, d);
      if(dt.getFullYear() !== y || (dt.getMonth() + 1) !== mo || dt.getDate() !== d) return null;
      return dt;
    }
    function fmtYmd(dt){
      const y = dt.getFullYear();
      const m = dt.getMonth() + 1;
      const d = dt.getDate();
      const p2 = (n) => (n < 10 ? ("0" + n) : String(n));
      return String(y) + "-" + p2(m) + "-" + p2(d);
    }
    function daysInMonth(y, m){ return new Date(y, m, 0).getDate(); }
    function openDatePop(anchor, initialValue, onPick){
      closeActiveSelect();
      closeActiveDatePop();
      const today = new Date();
      const sel = parseYmd(initialValue) || null;
      const base = sel || today;
      let viewY = base.getFullYear();
      let viewM = base.getMonth() + 1;
      let mode = "day";
      const el = document.createElement("div");
      el.className = "bp-date-pop";
      el.addEventListener("mousedown", (ev) => { ev.preventDefault(); }, true);
      const render = () => {
        el.innerHTML = "";
        const head = document.createElement("div");
        head.className = "bp-date-head";
        const prev = document.createElement("div");
        prev.className = "bp-date-nav";
        prev.textContent = "‹";
        prev.addEventListener("click", () => {
          if(mode === "year"){
            viewY -= 12;
          }else if(mode === "month"){
            viewY -= 1;
          }else{
            viewM -= 1;
            if(viewM <= 0){ viewM = 12; viewY -= 1; }
          }
          render();
        });
        const next = document.createElement("div");
        next.className = "bp-date-nav";
        next.textContent = "›";
        next.addEventListener("click", () => {
          if(mode === "year"){
            viewY += 12;
          }else if(mode === "month"){
            viewY += 1;
          }else{
            viewM += 1;
            if(viewM >= 13){ viewM = 1; viewY += 1; }
          }
          render();
        });
        const title = document.createElement("div");
        title.className = "bp-date-title";
        const p2 = (n) => (n < 10 ? ("0" + n) : String(n));
        const yearStart = viewY - 6;
        const yearEnd = yearStart + 11;
        title.textContent = (mode === "year") ? (String(yearStart) + "-" + String(yearEnd)) : ((mode === "month") ? String(viewY) : (String(viewY) + "-" + p2(viewM)));
        title.addEventListener("click", () => {
          if(mode === "day"){
            mode = "year";
          }else if(mode === "month"){
            mode = "year";
          }else{
            mode = "day";
          }
          render();
        });
        head.appendChild(prev);
        head.appendChild(title);
        head.appendChild(next);
        el.appendChild(head);
        const grid = document.createElement("div");
        grid.className = "bp-date-grid";
        if(mode === "year"){
          grid.style.gridTemplateColumns = "repeat(4, 1fr)";
          const sYear = yearStart;
          for(let i=0;i<12;i++){
            const y = sYear + i;
            const b = document.createElement("div");
            b.className = "bp-date-day";
            b.textContent = String(y);
            if(sel && sel.getFullYear() === y) b.classList.add("sel");
            if(today.getFullYear() === y) b.classList.add("today");
            b.addEventListener("click", () => {
              viewY = y;
              mode = "month";
              render();
            });
            grid.appendChild(b);
          }
        }else if(mode === "month"){
          grid.style.gridTemplateColumns = "repeat(4, 1fr)";
          for(let m=1;m<=12;m++){
            const b = document.createElement("div");
            b.className = "bp-date-day";
            b.textContent = String(m) + "月";
            if(sel && sel.getFullYear() === viewY && (sel.getMonth()+1) === m) b.classList.add("sel");
            if(today.getFullYear() === viewY && (today.getMonth()+1) === m) b.classList.add("today");
            b.addEventListener("click", () => {
              viewM = m;
              mode = "day";
              render();
            });
            grid.appendChild(b);
          }
        }else{
          grid.style.gridTemplateColumns = "repeat(7, 1fr)";
          for(const k of ["一","二","三","四","五","六","日"]){
            const d = document.createElement("div");
            d.className = "bp-date-dow";
            d.textContent = k;
            grid.appendChild(d);
          }
          const first = new Date(viewY, viewM - 1, 1);
          const startDow = (first.getDay() + 6) % 7;
          const dm = daysInMonth(viewY, viewM);
          const prevDm = daysInMonth(viewY, viewM - 1 <= 0 ? 12 : viewM - 1);
          const prevY = viewM - 1 <= 0 ? (viewY - 1) : viewY;
          const prevM = viewM - 1 <= 0 ? 12 : (viewM - 1);
          const nextY = viewM + 1 >= 13 ? (viewY + 1) : viewY;
          const nextM = viewM + 1 >= 13 ? 1 : (viewM + 1);
          const cells = [];
          for(let i=0;i<startDow;i++){
            const day = prevDm - (startDow - 1 - i);
            cells.push({y:prevY, m:prevM, d:day, muted:true});
          }
          for(let d=1; d<=dm; d++){
            cells.push({y:viewY, m:viewM, d:d, muted:false});
          }
          while(cells.length < 42){
            const d = cells.length - (startDow + dm) + 1;
            cells.push({y:nextY, m:nextM, d:d, muted:true});
          }
          for(const c of cells){
            const b = document.createElement("div");
            b.className = "bp-date-day" + (c.muted ? " muted" : "");
            b.textContent = String(c.d);
            const isToday = (today.getFullYear() === c.y && (today.getMonth()+1) === c.m && today.getDate() === c.d);
            if(isToday) b.classList.add("today");
            if(sel && sel.getFullYear() === c.y && (sel.getMonth()+1) === c.m && sel.getDate() === c.d){
              b.classList.add("sel");
            }
            b.addEventListener("click", () => {
              const v = fmtYmd(new Date(c.y, c.m - 1, c.d));
              try{ onPick && onPick(v); }catch(e){}
              closeActiveDatePop();
            });
            grid.appendChild(b);
          }
        }
        el.appendChild(grid);
      };
      render();
      document.body.appendChild(el);
      try{
        const r = anchor.getBoundingClientRect();
        const pad = 8;
        const w = el.offsetWidth || 262;
        const h = el.offsetHeight || 320;
        let left = r.left;
        let top = r.bottom + 6;
        if(left + w + pad > window.innerWidth) left = Math.max(pad, window.innerWidth - w - pad);
        if(top + h + pad > window.innerHeight) top = Math.max(pad, r.top - h - 6);
        el.style.left = Math.round(left) + "px";
        el.style.top = Math.round(top) + "px";
      }catch(e){}
      activeDatePop = {el, anchor};
    }
    function wireDateInput(inp){
      if(!inp || inp.__bpDateWired) return;
      inp.__bpDateWired = true;
      inp.addEventListener("click", (ev) => {
        try{
          const t = ev && ev.target ? ev.target : inp;
          openDatePop(t, String(t.value || ""), (v) => {
            try{ t.value = String(v || ""); }catch(e){}
            try{ t.dispatchEvent(new Event("change", {bubbles:true})); }catch(e){}
          });
        }catch(e){}
      });
    }
    document.addEventListener("click", (ev) => {
      if(!activeDatePop || !activeDatePop.el) return;
      const t = ev.target;
      if(activeDatePop.el.contains(t)) return;
      if(activeDatePop.anchor && activeDatePop.anchor.contains && activeDatePop.anchor.contains(t)) return;
      closeActiveDatePop();
    }, true);
    window.addEventListener("resize", () => closeActiveDatePop());
    window.addEventListener("scroll", (ev) => {
      if(!activeDatePop || !activeDatePop.el) return;
      const t = ev && ev.target;
      if(t && activeDatePop.el.contains(t)) return;
      closeActiveDatePop();
    }, true);

    function bytesToB64(buf){
      const bytes = new Uint8Array(buf);
      let bin = "";
      for(let i=0;i<bytes.length;i++){ bin += String.fromCharCode(bytes[i]); }
      return btoa(bin);
    }
    let __bpHmacKey = null;
    let __bpHmacKeyToken = "";
    async function hmacSign(token, action, payload){
      const enc = new TextEncoder();
      const t = String(token || "");
      if(!__bpHmacKey || __bpHmacKeyToken !== t){
        const keyData = enc.encode(t);
        __bpHmacKey = await crypto.subtle.importKey("raw", keyData, {name:"HMAC", hash:"SHA-256"}, false, ["sign"]);
        __bpHmacKeyToken = t;
      }
      const msg = enc.encode(String(action||"") + "\\n" + String(payload||""));
      const sig = await crypto.subtle.sign("HMAC", __bpHmacKey, msg);
      return bytesToB64(sig);
    }
    function bridgeCall(bridge, action, payloadObj, token){
      return new Promise(async (resolve) => {
        const t0 = perfNow();
        const payload = JSON.stringify(payloadObj || {});
        const done = (resp) => {
          const dt = perfNow() - t0;
          try{ slowLog("桥接 " + String(action||""), dt); }catch(e){}
          try{ resolve(JSON.parse(resp||"{}")); }
          catch(e){ resolve({ok:false, error:"bad_response"}); }
        };
        const callSimple = () => {
          try{
            if(bridge && typeof bridge.requestSimple === "function"){
              bridge.requestSimple(action, payload, done);
              return true;
            }
          }catch(e){}
          return false;
        };
        try{
          if(!window.crypto || !crypto.subtle || typeof crypto.subtle.importKey !== "function"){
            if(callSimple()) return;
            try{ slowLog("桥接 " + String(action||""), perfNow() - t0); }catch(e){}
            resolve({ok:false, error:"crypto_unavailable"});
            return;
          }
          const sig = await hmacSign(token, action, payload);
          bridge.request(action, payload, token, sig, done);
        }catch(e){
          if(callSimple()) return;
          try{ slowLog("桥接 " + String(action||""), perfNow() - t0); }catch(e){}
          resolve({ok:false, error:"bridge_call_failed"});
        }
      });
    }

    let bridge = null;
    let token = "";
    let state = null;
    let watermarkOn = false;
    let watermarkText = "";
    let watermarkFontSize = 22;
    let virtualGridOn = true;
    let windowStyle = "acrylic";
    let currentTheme = "dark";
    const THEME_UI = __THEME_UI__;
    const chartsById = new Map();
    const chartViews = new Map();
    const chartPayloadCache = new Map();
    const chartOrder = new Map();
    let orderTop = 0;
    let zTop = 20;
    let editMode = false;
    let editingChartId = null;
    let activeChartId = null;
    const chartHover = new Map();
    const chartRefreshing = new Map();
    const chartRefreshingToken = new Map();
    const chartHoverRefreshTimers = new Map();
    const chartActiveUntil = new Map();
    const HOVER_REFRESH_MS = 1500;
    const GRACE_REFRESH_MS = 5000;
    const MIN_REFRESH_LAMP_MS = 450;
    function __bpSetDebug(on){
      const v = !!on;
      try{ window.__bpDebug = v; }catch(e){}
      try{ document.body.classList.toggle("bp-debug", v); }catch(e){}
      try{
        const a = $("statusBadge");
        if(a){
          a.style.display = v ? "block" : "none";
          if(v && !String(a.textContent || "").trim()){ a.textContent = "DEBUG: ON"; }
        }
      }catch(e){}
    }
    try{ window.__bpSetDebug = __bpSetDebug; }catch(e){}
    try{
      __bpSetDebug(!!window.__bpDebug);
    }catch(e){}

    function pauseRefreshOnMouseLeave(){
      try{
        const opt = (state && state.display_options) ? state.display_options : {};
        return !!opt.pause_refresh_on_mouse_leave;
      }catch(e){}
      return false;
    }
    function syncToggleVisualById(id){
      const inp = $(id);
      if(!inp) return;
      let lab = null;
      try{ lab = inp.closest(".bp-toggle"); }catch(e){ lab = null; }
      if(!lab) return;
      try{ lab.setAttribute("data-on", inp.checked ? "1" : "0"); }catch(e){}
    }
    function syncAllToggleVisuals(){
      ["cbTitle","cbLegend","cbAnim","cbPauseRefresh","cbIgnoreEmptyDates","cbWatermark","cbGpu"].forEach(id => {
        try{ syncToggleVisualById(id); }catch(e){}
      });
    }
    function isChartHovered(cid){
      return chartHover.get(String(cid || "")) === true;
    }
    function isChartActive(cid){
      const id = String(cid || "");
      if(isChartHovered(id)) return true;
      const until = chartActiveUntil.get(id);
      return (typeof until === "number" && isFinite(until) && until > perfNow());
    }
    function bumpChartActive(cid, ms){
      const id = String(cid || "");
      const dt = (typeof ms === "number" && isFinite(ms) && ms > 0) ? ms : GRACE_REFRESH_MS;
      chartActiveUntil.set(id, perfNow() + dt);
      try{ syncChartRefreshState(id); }catch(e){}
      try{ startHoverRefresh(id); }catch(e){}
    }
    function setChartHovered(cid, on){
      chartHover.set(String(cid || ""), !!on);
      syncChartRefreshState(cid);
    }
    function setChartRefreshing(cid, on){
      chartRefreshing.set(String(cid || ""), !!on);
      syncChartRefreshState(cid);
    }
    function syncChartRefreshState(cid){
      const id = String(cid || "");
      let el = null;
      try{ el = document.querySelector('.win[data-id="'+id+'"]'); }catch(e){}
      if(!el) return;
      const paused = pauseRefreshOnMouseLeave() && !isChartActive(id);
      try{ el.setAttribute("data-paused", paused ? "1" : "0"); }catch(e){}
      const active = pauseRefreshOnMouseLeave() && isChartActive(id);
      try{ el.setAttribute("data-active-refresh", active ? "1" : "0"); }catch(e){}
      const refreshing = chartRefreshing.get(id) === true;
      try{ el.setAttribute("data-refreshing", refreshing ? "1" : "0"); }catch(e){}
    }

    function startHoverRefresh(cid){
      const id = String(cid || "");
      if(chartHoverRefreshTimers.has(id)) return;
      try{ syncChartRefreshState(id); }catch(e){}
      const tid = setInterval(() => {
        try{
          if(!pauseRefreshOnMouseLeave()){
            stopHoverRefresh(id);
            return;
          }
          if(!isChartActive(id)){
            stopHoverRefresh(id);
            return;
          }
          if(chartRefreshing.get(id) === true) return;
          renderChart(id);
        }catch(e){}
      }, HOVER_REFRESH_MS);
      chartHoverRefreshTimers.set(id, tid);
    }
    function stopHoverRefresh(cid){
      const id = String(cid || "");
      const tid = chartHoverRefreshTimers.get(id);
      if(tid){
        try{ clearInterval(tid); }catch(e){}
      }
      chartHoverRefreshTimers.delete(id);
      try{ syncChartRefreshState(id); }catch(e){}
    }
    function stopAllHoverRefresh(){
      for(const [id, tid] of chartHoverRefreshTimers.entries()){
        try{ clearInterval(tid); }catch(e){}
      }
      chartHoverRefreshTimers.clear();
    }

    function setEditMode(on){
      const wasEditMode = editMode;
      editMode = !!on;
      // 从编辑模式切换到显示模式时，保存图表位置
      if(wasEditMode && !editMode){
        try{ saveAllChartLayouts(); }catch(e){}
      }
      try{ document.body.classList.toggle("edit-mode", editMode); }catch(e){}
      try{ setDisabled("btnAdd", !editMode); }catch(e){}
      try{
        const b = $("btnEditMode");
        if(b){
          b.setAttribute("data-on", editMode ? "1" : "0");
          try{ b.setAttribute("aria-checked", editMode ? "true" : "false"); }catch(e){}
        }
      }catch(e){}
      try{
        const w = $("boatWrap");
        if(w) w.setAttribute("data-on", editMode ? "1" : "0");
      }catch(e){}
    }
    
    // 保存所有图表位置
    async function saveAllChartLayouts(){
      if(!bridge) return;
      const layouts = [];
      document.querySelectorAll("#desk .win").forEach(el => {
        const cid = String(el.getAttribute("data-id") || "");
        if(cid){
          layouts.push({
            chart_id: cid,
            layout: {
              x: parseFloat(el.style.left || "0"),
              y: parseFloat(el.style.top || "0"),
              w: parseFloat(el.style.width || "520"),
              h: parseFloat(el.style.height || "360"),
              z: parseInt(el.style.zIndex || "1"),
              locked: String(el.getAttribute("data-lock") || "") === "1"
            }
          });
        }
      });
      if(layouts.length > 0){
        try{
          await bridgeCall(bridge, "update_chart_layouts", {layouts}, token);
        }catch(e){}
      }
    }

    function pickTypeScope(t){
      if(t === "bar") return "bar";
      if(t === "line") return "bar";
      if(t === "number") return "number";
      const xy = ["timelineLine","bar3D"];
      if(xy.includes(t)) return "xy";
      if(t === "pie") return "pie";
      if(t === "scatter") return "scatter";
      if(t === "tree") return "tree";
      return "none";
    }
    function pickTypeScopeByOptions(t, opt){
      const type = String(t || "");
      const options = (opt && typeof opt === "object") ? opt : {};
      if(type === "line"){
        if(String(options.bar_x_kind || "").trim()) return "bar";
        if(String(options.x_field || "").trim()) return "xy";
        return "bar";
      }
      return pickTypeScope(type);
    }
    function syncAddFields(scopeOverride){
      const t = $("fType").value || "";
      const scope = scopeOverride ? String(scopeOverride || "") : pickTypeScope(t);
      document.querySelectorAll("[data-scope]").forEach(el => {
        el.style.display = (el.getAttribute("data-scope") === scope) ? "" : "none";
      });
      if(scope === "bar"){
        try{ barEnsureInit(); }catch(e){}
        try{ barSyncModeUI(); }catch(e){}
      }
      if(scope === "number"){
        try{ numberEnsureInit(); }catch(e){}
      }
    }

    let barInited = false;
    let barTimeStart = "";
    let barTimeEnd = "";
    let barTimeEndNow = false;
    let barTimePreset = "";

    // 数据图变量
    let numberInited = false;
    let numberTimeStart = "";
    let numberTimeEnd = "";
    let numberTimeEndNow = false;
    let numberTimePreset = "";

    // 饼图变量
    let pieInited = false;
    let pieTimeStart = "";
    let pieTimeEnd = "";
    let pieTimeEndNow = false;
    let pieTimePreset = "";

    function barXExcludeField(kind){
      const k = String(kind || "time");
      if(k === "time") return "拍摄时间";
      if(k === "location") return "拍摄地址";
      if(k === "rating") return "评星";
      if(k === "label") return "色标";
      if(k === "score") return "分数";
      if(k === "species") return "种";
      if(k === "order") return "目";
      if(k === "family") return "科";
      if(k === "genus") return "属";
      return "";
    }
    function barAllFilterFields(){
      return ["文件名","标签","路径","评星","分数","鸟的位置","色标","目","科","属","种","备注","拍摄时间","拍摄地址"];
    }
    function barEnsureInit(){
      if(barInited) return;
      barInited = true;
      try{
        const now = new Date();
        const end = now.toISOString().slice(0, 10);
        const startDt = new Date(now.getTime() - 29 * 24 * 3600 * 1000);
        const start = startDt.toISOString().slice(0, 10);
        if(!barTimeStart) barTimeStart = start;
        if(!barTimeEnd && !barTimeEndNow) barTimeEnd = end;
        try{ barSyncTimeRangeUI(); }catch(e){}
      }catch(e){}
      try{
        $("btnBarAddCond").addEventListener("click", () => { barAddFilterRow(null); });
        $("btnBarClearCond").addEventListener("click", () => { barClearFilters(); });
      }catch(e){}
      try{
        $("fBarXKind").addEventListener("change", () => { barSyncModeUI(); });
      }catch(e){}
      try{
        $("btnBarPickTime").addEventListener("click", () => { barOpenTimePicker(); });
        try{
          const a = $("fBarTimeStartShow");
          if(a){
            a.addEventListener("click", (ev) => {
              const t = ev && ev.target ? ev.target : a;
              openDatePop(t, String(barTimeStart || ""), (v) => {
                try{
                  barTimeStart = String(v || "");
                  if(barTimePreset){
                    barTimePreset = "";
                    try{ barSyncTimePickerPresetUI(); }catch(e){}
                  }
                  if(barTimeEndNow){
                    barTimeEndNow = false;
                  }
                  barSyncTimeRangeUI();
                }catch(e){}
              });
            });
            a.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); a.click(); } });
          }
          const b = $("fBarTimeEndShow");
          if(b){
            b.addEventListener("click", (ev) => {
              const t = ev && ev.target ? ev.target : b;
              openDatePop(t, String(barTimeEnd || ""), (v) => {
                try{
                  barTimeEnd = String(v || "");
                  if(barTimePreset){
                    barTimePreset = "";
                    try{ barSyncTimePickerPresetUI(); }catch(e){}
                  }
                  if(barTimeEndNow){
                    barTimeEndNow = false;
                  }
                  barSyncTimeRangeUI();
                }catch(e){}
              });
            });
            b.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); b.click(); } });
          }
        }catch(e){}
        $("btnApplyBarTime").addEventListener("click", () => { barApplyTimePicker(); });
        $("btnBarQuickNow").addEventListener("click", () => { barSetQuickRange("now"); });
        $("btnBarQuickToday").addEventListener("click", () => { barSetQuickRange("today"); });
        $("btnBarQuickWeek").addEventListener("click", () => { barSetQuickRange("week"); });
        $("btnBarQuickMonth").addEventListener("click", () => { barSetQuickRange("month"); });
        $("btnBarQuickYear").addEventListener("click", () => { barSetQuickRange("year"); });
        $("barTimePickStart").addEventListener("change", () => {
          try{
            if(barTimePreset){
              barTimePreset = "";
              try{ barSyncTimePickerPresetUI(); }catch(e){}
            }
            if(barTimeEndNow){
              barTimeEndNow = false;
            }
          }catch(e){}
        });
        try{ wireDateInput($("barTimePickStart")); }catch(e){}
        $("barTimePickEnd").addEventListener("change", () => {
          try{
            if(barTimePreset){
              barTimePreset = "";
              try{ barSyncTimePickerPresetUI(); }catch(e){}
            }
            barTimeEndNow = false;
          }catch(e){}
        });
        try{ wireDateInput($("barTimePickEnd")); }catch(e){}
      }catch(e){}
    }
    function barFmtDate(d){
      const dd = d instanceof Date ? d : new Date();
      const y = dd.getFullYear();
      const m = dd.getMonth() + 1;
      const da = dd.getDate();
      const p2 = (n) => (n < 10 ? ("0" + n) : String(n));
      return String(y) + "-" + p2(m) + "-" + p2(da);
    }
    function barSetQuickRange(kind){
      const k = String(kind || "");
      const now = new Date();
      // 检查是否为饼图上下文
      const isPieContext = !!window._tempPieContext;
      const isNumberContext = !!window._tempNumberContext;
      const isScatterContext = !!window._tempScatterContext;
      // 散点图上下文
      if(isScatterContext){
        if(k === "now"){
          try{
            const nextNow = !scatterTimeEndNow;
            scatterTimeEndNow = nextNow;
            if(nextNow){
              scatterTimePreset = "now";
            }else{
              scatterTimePreset = "";
            }
            try{ $("barTimePickStart").disabled = false; }catch(e){}
            try{ $("barTimePickEnd").disabled = nextNow; }catch(e){}
            try{ barSyncTimePickerPresetUI(); }catch(e){}
          }catch(e){}
          return;
        }
        let start = "";
        let end = barFmtDate(now);
        if(k === "today"){
          start = end;
        }else if(k === "week"){
          const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
          start = barFmtDate(s);
        }else if(k === "month"){
          const s = new Date(now.getFullYear(), now.getMonth(), 1);
          start = barFmtDate(s);
        }else if(k === "year"){
          const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
          start = barFmtDate(s);
        }else{
          return;
        }
        try{
          scatterTimePreset = k;
          scatterTimeEndNow = true;
          if($("barTimePickStart")) $("barTimePickStart").value = start;
          if($("barTimePickEnd")) $("barTimePickEnd").value = end;
          try{
            $("barTimePickStart").disabled = true;
            $("barTimePickEnd").disabled = true;
          }catch(e){}
          try{ barSyncTimePickerPresetUI(); }catch(e){}
        }catch(e){}
        return;
      }
      // 饼图上下文
      if(isPieContext){
        if(k === "now"){
          try{
            const nextNow = !pieTimeEndNow;
            pieTimeEndNow = nextNow;
            if(nextNow){
              pieTimePreset = "now";
            }else{
              pieTimePreset = "";
            }
            try{ $("barTimePickStart").disabled = false; }catch(e){}
            try{ $("barTimePickEnd").disabled = nextNow; }catch(e){}
            try{ barSyncTimePickerPresetUI(); }catch(e){}
          }catch(e){}
          return;
        }
        let start = "";
        let end = barFmtDate(now);
        if(k === "today"){
          start = end;
        }else if(k === "week"){
          const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
          start = barFmtDate(s);
        }else if(k === "month"){
          const s = new Date(now.getFullYear(), now.getMonth(), 1);
          start = barFmtDate(s);
        }else if(k === "year"){
          const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
          start = barFmtDate(s);
        }else{
          return;
        }
        try{
          const nextPreset = (pieTimePreset === k) ? "" : k;
          pieTimePreset = nextPreset;
          if(pieTimePreset){
            pieTimeEndNow = true;
            if($("barTimePickStart")) $("barTimePickStart").value = start;
            if($("barTimePickEnd")) $("barTimePickEnd").value = end;
            try{
              $("barTimePickStart").disabled = true;
              $("barTimePickEnd").disabled = true;
            }catch(e){}
          }else{
            try{
              $("barTimePickStart").disabled = false;
              $("barTimePickEnd").disabled = !!pieTimeEndNow;
            }catch(e){}
          }
          try{ barSyncTimePickerPresetUI(); }catch(e){}
        }catch(e){}
        return;
      }
      // 数据图上下文
      if(isNumberContext){
        if(k === "now"){
          try{
            const nextNow = !numberTimeEndNow;
            numberTimeEndNow = nextNow;
            if(nextNow){
              numberTimePreset = "now";
            }else{
              numberTimePreset = "";
            }
            try{ $("barTimePickStart").disabled = false; }catch(e){}
            try{ $("barTimePickEnd").disabled = nextNow; }catch(e){}
            try{ barSyncTimePickerPresetUI(); }catch(e){}
          }catch(e){}
          return;
        }
        let start = "";
        let end = barFmtDate(now);
        if(k === "today"){
          start = end;
        }else if(k === "week"){
          const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
          start = barFmtDate(s);
        }else if(k === "month"){
          const s = new Date(now.getFullYear(), now.getMonth(), 1);
          start = barFmtDate(s);
        }else if(k === "year"){
          const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
          start = barFmtDate(s);
        }else{
          return;
        }
        try{
          const nextPreset = (numberTimePreset === k) ? "" : k;
          numberTimePreset = nextPreset;
          if(numberTimePreset){
            numberTimeEndNow = true;
            if($("barTimePickStart")) $("barTimePickStart").value = start;
            if($("barTimePickEnd")) $("barTimePickEnd").value = end;
            try{
              $("barTimePickStart").disabled = true;
              $("barTimePickEnd").disabled = true;
            }catch(e){}
          }else{
            try{
              $("barTimePickStart").disabled = false;
              $("barTimePickEnd").disabled = !!numberTimeEndNow;
            }catch(e){}
          }
          try{ barSyncTimePickerPresetUI(); }catch(e){}
        }catch(e){}
        return;
      }
      // 柱状图上下文
      if(k === "now"){
        try{
          const nextNow = !barTimeEndNow;
          barTimeEndNow = nextNow;
          if(nextNow){
            barTimePreset = "now";
          }else{
            barTimePreset = "";
          }
          try{ $("barTimePickStart").disabled = false; }catch(e){}
          try{ $("barTimePickEnd").disabled = nextNow; }catch(e){}
          try{ barSyncTimePickerPresetUI(); }catch(e){}
        }catch(e){}
        return;
      }
      let start = "";
      let end = barFmtDate(now);
      if(k === "today"){
        start = end;
      }else if(k === "week"){
        const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
        start = barFmtDate(s);
      }else if(k === "month"){
        const s = new Date(now.getFullYear(), now.getMonth(), 1);
        start = barFmtDate(s);
      }else if(k === "year"){
        const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
        start = barFmtDate(s);
      }else{
        return;
      }
      try{
        const nextPreset = (barTimePreset === k) ? "" : k;
        barTimePreset = nextPreset;
        if(barTimePreset){
          barTimeEndNow = true;
          if($("barTimePickStart")) $("barTimePickStart").value = start;
          if($("barTimePickEnd")) $("barTimePickEnd").value = end;
          try{
            $("barTimePickStart").disabled = true;
            $("barTimePickEnd").disabled = true;
          }catch(e){}
        }else{
          try{
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = !!barTimeEndNow;
          }catch(e){}
        }
        try{ barSyncTimePickerPresetUI(); }catch(e){}
      }catch(e){}
    }
    function barSyncTimePickerPresetUI(){
      const map = [
        ["today","btnBarQuickToday"],
        ["week","btnBarQuickWeek"],
        ["month","btnBarQuickMonth"],
        ["year","btnBarQuickYear"],
      ];
      for(const [k, id] of map){
        const b = $(id);
        if(!b) continue;
        b.classList.toggle("primary", barTimePreset === k);
      }
      try{
        const nowBtn = $("btnBarQuickNow");
        if(nowBtn){
          nowBtn.classList.toggle("primary", barTimePreset === "now" || (!barTimePreset && barTimeEndNow));
        }
      }catch(e){}
      if(barTimePreset === "now"){
        try{ $("barTimePickStart").disabled = false; }catch(e){}
        try{ $("barTimePickEnd").disabled = true; }catch(e){}
      }else{
        try{ $("barTimePickStart").disabled = false; }catch(e){}
        try{ $("barTimePickEnd").disabled = !!barTimeEndNow; }catch(e){}
      }
    }
    function barSyncTimeRangeUI(){
      try{
        const s = $("fBarTimeStartShow");
        const e = $("fBarTimeEndShow");
        if(barTimePreset){
          const name = (barTimePreset === "today") ? "当天" : (barTimePreset === "week" ? "近一周" : (barTimePreset === "month" ? "近一月" : (barTimePreset === "year" ? "近一年" : (barTimePreset === "now" ? "至今" : barTimePreset))));
          if(barTimePreset === "now"){
            if(s) s.value = String(barTimeStart || "");
            if(e) e.value = "至今";
          }else{
            if(s) s.value = name;
            if(e) e.value = name;
          }
          return;
        }
        if(s) s.value = String(barTimeStart || "");
        if(e) e.value = barTimeEndNow ? "至今" : String(barTimeEnd || "");
      }catch(e){}
    }
    function barOpenTimePicker(){
      try{ barEnsureInit(); }catch(e){}
      try{
        const now = new Date();
        let displayStart = barTimeStart || "";
        let displayEnd = barTimeEnd || "";
        if(barTimePreset && barTimePreset !== "now"){
          const today = barFmtDate(now);
          if(barTimePreset === "today"){
            displayStart = today;
            displayEnd = today;
          }else if(barTimePreset === "week"){
            const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(barTimePreset === "month"){
            const s = new Date(now.getFullYear(), now.getMonth(), 1);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(barTimePreset === "year"){
            const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }
        }
        if($("barTimePickStart")) $("barTimePickStart").value = String(displayStart || "");
        if($("barTimePickEnd")) $("barTimePickEnd").value = String(displayEnd || "");
        try{
          if(barTimePreset === "now"){
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = true;
          }else{
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = !!barTimeEndNow;
          }
        }catch(e){}
        try{ barSyncTimePickerPresetUI(); }catch(e){}
      }catch(e){}
      try{ upgradeAllSelects(); }catch(e){}
      openModal("modalBarTime");
    }
    function barApplyTimePicker(){
      // 检查是否为饼图上下文
      const isPieContext = !!window._tempPieContext;
      const isNumberContext = !!window._tempNumberContext;
      const isScatterContext = !!window._tempScatterContext;
      try{
        // 散点图上下文
        if(isScatterContext){
          const preset = String(scatterTimePreset || "").trim();
          if(preset && preset !== "now"){
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            if(s) scatterTimeStart = s;
            scatterTimeEndNow = true;
            scatterTimeEnd = "";
          }else if(preset === "now"){
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            if(s) scatterTimeStart = s;
            scatterTimeEndNow = true;
            scatterTimeEnd = "";
          }else{
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            const e = String(($("barTimePickEnd") && $("barTimePickEnd").value) || "").trim();
            if(s) scatterTimeStart = s;
            if(e){
              scatterTimeEndNow = false;
              scatterTimeEnd = e;
            }else if(scatterTimeEndNow){
              scatterTimeEnd = "";
            }
          }
          scatterSyncTimeRangeUI();
          window._tempScatterContext = false;
          closeModal("modalBarTime");
          return;
        }
        // 饼图上下文
        if(isPieContext){
          const preset = String(pieTimePreset || "").trim();
          if(preset && preset !== "now"){
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            if(s) pieTimeStart = s;
            pieTimeEndNow = true;
            pieTimeEnd = "";
          }else if(preset === "now"){
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            if(s) pieTimeStart = s;
            pieTimeEndNow = true;
            pieTimeEnd = "";
          }else{
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            const e = String(($("barTimePickEnd") && $("barTimePickEnd").value) || "").trim();
            if(s) pieTimeStart = s;
            if(e){
              pieTimeEndNow = false;
              pieTimeEnd = e;
            }else if(pieTimeEndNow){
              pieTimeEnd = "";
            }
          }
          pieSyncTimeRangeUI();
          window._tempPieContext = false;
          closeModal("modalBarTime");
          return;
        }
        // 数据图上下文
        if(isNumberContext){
          const preset = String(numberTimePreset || "").trim();
          if(preset && preset !== "now"){
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            if(s) numberTimeStart = s;
            numberTimeEndNow = true;
            numberTimeEnd = "";
          }else if(preset === "now"){
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            if(s) numberTimeStart = s;
            numberTimeEndNow = true;
            numberTimeEnd = "";
          }else{
            const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
            const e = String(($("barTimePickEnd") && $("barTimePickEnd").value) || "").trim();
            if(s) numberTimeStart = s;
            if(e){
              numberTimeEndNow = false;
              numberTimeEnd = e;
            }else if(numberTimeEndNow){
              numberTimeEnd = "";
            }
          }
          numberSyncTimeRangeUI();
          window._tempNumberContext = false;
          closeModal("modalBarTime");
          return;
        }
        // 柱状图上下文
        const preset = String(barTimePreset || "").trim();
        if(preset && preset !== "now"){
          barTimeEndNow = true;
          barTimeEnd = "";
        }else if(preset === "now"){
          const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
          if(s) barTimeStart = s;
          barTimeEndNow = true;
          barTimeEnd = "";
        }else{
          const s = String(($("barTimePickStart") && $("barTimePickStart").value) || "").trim();
          const e = String(($("barTimePickEnd") && $("barTimePickEnd").value) || "").trim();
          if(s) barTimeStart = s;
          if(e){
            barTimeEndNow = false;
            barTimeEnd = e;
          }else if(barTimeEndNow){
            barTimeEnd = "";
          }
        }
        barSyncTimeRangeUI();
        closeModal("modalBarTime");
      }catch(e){}
    }
    function barSyncModeUI(){
      const kind = String(($("fBarXKind") && $("fBarXKind").value) || "time");
      const timeOn = (kind === "time");
      const locOn = (kind === "location");
      // 控制时间相关选项的显示/隐藏
      try{ $("barTimeRangeWrap").style.display = timeOn ? "" : "none"; }catch(e){}
      try{ $("barTimeUnitWrap").style.display = timeOn ? "" : "none"; }catch(e){}
      // 控制时间类型选择框的显示/隐藏，仅在横坐标选择时间时显示
      try{ $("barTimeTypeWrap").style.display = timeOn ? "" : "none"; }catch(e){}
      // 控制隐藏无数据时间选项的显示/隐藏
      try{ $("barHideEmptyTimeWrap").style.display = timeOn ? "" : "none"; }catch(e){}
      try{ $("barLocLevelWrap").style.display = locOn ? "" : "none"; }catch(e){}
      try{ barRefreshFilterFieldOptions(); }catch(e){}
    }

    // ==================== 数据图（Number）相关函数 ====================

    function numberEnsureInit(){
      if(numberInited) return;
      numberInited = true;
      // 数据图默认不设置时间范围（即所有时间），让用户自己选择
      try{ numberSyncTimeRangeUI(); }catch(e){}
      try{
        // 使用柱状图的筛选函数，传入数据图的列表ID
        $("btnNumberAddCond").addEventListener("click", () => { barAddFilterRow(null, "numberFilterList"); });
        $("btnNumberClearCond").addEventListener("click", () => { barClearFilters("numberFilterList"); });
      }catch(e){}
      try{
        $("btnNumberPickTime").addEventListener("click", () => { numberOpenTimePicker(); });
        try{
          const a = $("fNumberTimeStartShow");
          if(a){
            a.addEventListener("click", (ev) => {
              const t = ev && ev.target ? ev.target : a;
              openDatePop(t, String(numberTimeStart || ""), (v) => {
                try{
                  numberTimeStart = String(v || "");
                  if(numberTimePreset){
                    numberTimePreset = "";
                  }
                  if(numberTimeEndNow){
                    numberTimeEndNow = false;
                  }
                  numberSyncTimeRangeUI();
                }catch(e){}
              });
            });
            a.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); a.click(); } });
          }
          const b = $("fNumberTimeEndShow");
          if(b){
            b.addEventListener("click", (ev) => {
              const t = ev && ev.target ? ev.target : b;
              openDatePop(t, String(numberTimeEnd || ""), (v) => {
                try{
                  numberTimeEnd = String(v || "");
                  if(numberTimePreset){
                    numberTimePreset = "";
                  }
                  if(numberTimeEndNow){
                    numberTimeEndNow = false;
                  }
                  numberSyncTimeRangeUI();
                }catch(e){}
              });
            });
            b.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); b.click(); } });
          }
        }catch(e){}
      }catch(e){}
    }

    function numberSyncTimeRangeUI(){
      try{
        const s = $("fNumberTimeStartShow");
        const e = $("fNumberTimeEndShow");
        if(!s || !e) return;
        if(numberTimePreset){
          const name = numberTimePreset === "now" ? "至今" :
                       numberTimePreset === "today" ? "今天" :
                       numberTimePreset === "week" ? "最近7天" :
                       numberTimePreset === "month" ? "本月" :
                       numberTimePreset === "year" ? "最近一年" : numberTimePreset;
          if(numberTimePreset === "now"){
            if(s) s.value = String(numberTimeStart || "");
            if(e) e.value = "至今";
          }else{
            if(s) s.value = name;
            if(e) e.value = name;
          }
          return;
        }
        if(s) s.value = String(numberTimeStart || "");
        if(e) e.value = numberTimeEndNow ? "至今" : String(numberTimeEnd || "");
      }catch(e){}
    }

    function numberOpenTimePicker(){
      try{ numberEnsureInit(); }catch(e){}
      try{
        const now = new Date();
        let displayStart = numberTimeStart || "";
        let displayEnd = numberTimeEnd || "";
        if(numberTimePreset && numberTimePreset !== "now"){
          const today = barFmtDate(now);
          if(numberTimePreset === "today"){
            displayStart = today;
            displayEnd = today;
          }else if(numberTimePreset === "week"){
            const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(numberTimePreset === "month"){
            const s = new Date(now.getFullYear(), now.getMonth(), 1);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(numberTimePreset === "year"){
            const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }
        }
        // 复用柱状图的时间选择器
        if($("barTimePickStart")) $("barTimePickStart").value = String(displayStart || "");
        if($("barTimePickEnd")) $("barTimePickEnd").value = String(displayEnd || "");
        try{
          if(numberTimePreset === "now"){
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = true;
          }else{
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = !!numberTimeEndNow;
          }
        }catch(e){}
        try{ barSyncTimePickerPresetUI(); }catch(e){}
      }catch(e){}
      try{ upgradeAllSelects(); }catch(e){}
      openModal("modalBarTime");
      // 临时保存当前上下文为数据图
      window._tempNumberContext = true;
    }

    function numberAllFilterFields(){
      return ["文件名","标签","路径","评星","分数","鸟的位置","色标","目","科","属","种","备注","拍摄时间","拍摄地址"];
    }

    function numberGetFilters(){
      // 使用柱状图的筛选获取函数，传入数据图的列表ID
      return barGetFilters("numberFilterList");
    }

    function numberLoadFromOptions(opt){
      const o = opt && typeof opt === "object" ? opt : {};
      try{ $("fNumberType").value = String(o.number_type || "count"); refreshSelectLabel($("fNumberType")); }catch(e){}
      try{ $("fNumberTimeType").value = String(o.number_time_type || "shot_time"); refreshSelectLabel($("fNumberTimeType")); }catch(e){}
      try{ numberTimePreset = String(o.number_time_preset || ""); }catch(e){ numberTimePreset = ""; }
      try{ numberTimeStart = String(o.number_time_start || ""); }catch(e){ numberTimeStart = ""; }
      try{ numberTimeEnd = String(o.number_time_end || ""); }catch(e){ numberTimeEnd = ""; }
      try{ numberTimeEndNow = !!o.number_time_end_now; }catch(e){ numberTimeEndNow = false; }
      try{ numberSyncTimeRangeUI(); }catch(e){}
      try{
        barClearFilters("numberFilterList");
        const filters = o.number_filters || [];
        for(const c of filters){
          try{ barAddFilterRow(c, "numberFilterList"); }catch(e){}
        }
      }catch(e){}
    }

    // ========== 饼图相关函数 ==========

    // 饼图分类字段与筛选项的映射关系
    function pieCategoryToFilterField(cat){
      const map = {
        "order": "目",
        "family": "科",
        "genus": "属",
        "species": "种",
        "rating": "评星",
        "label": "色标",
        "location": "拍摄地址"
      };
      return map[cat] || "";
    }

    // 获取饼图可用的筛选字段（排除当前分类字段）
    function pieAllFilterFields(){
      const all = ["文件名","标签","路径","评星","分数","鸟的位置","色标","目","科","属","种","备注","拍摄时间","拍摄地址"];
      const cat = String(($("fPieCat") && $("fPieCat").value) || "species");
      const excluded = pieCategoryToFilterField(cat);
      if(excluded){
        return all.filter(f => f !== excluded);
      }
      return all;
    }

    // 刷新饼图筛选字段选项
    function pieRefreshFilterFieldOptions(){
      const list = $("pieFilterList");
      if(!list) return;
      const rows = Array.from(list.querySelectorAll(".filterRow"));
      const availableFields = pieAllFilterFields();
      for(const row of rows){
        const fieldSel = row.querySelector("select[data-role='field']");
        if(!fieldSel) continue;
        const prev = String(fieldSel.value || "");
        fieldSel.innerHTML = "";
        for(const f of availableFields){
          const o = document.createElement("option");
          o.value = f;
          o.textContent = f;
          fieldSel.appendChild(o);
        }
        try{
          if(prev && Array.from(fieldSel.options).some(o => String(o.value) === prev)){
            fieldSel.value = prev;
          }else{
            fieldSel.selectedIndex = 0;
          }
        }catch(e){}
        try{ refreshSelectLabel(fieldSel); }catch(e){}
        try{ barUpdateRowUI(row); }catch(e){}
      }
    }

    // 饼图初始化
    function pieEnsureInit(){
      if(pieInited) return;
      pieInited = true;
      try{ pieSyncTimeRangeUI(); }catch(e){}
      try{ pieSyncTimeTypeUI(); }catch(e){}
      // 绑定筛选按钮事件
      try{
        $("btnPieAddCond").addEventListener("click", () => { barAddFilterRow(null, "pieFilterList"); pieRefreshFilterFieldOptions(); });
        $("btnPieClearCond").addEventListener("click", () => { barClearFilters("pieFilterList"); });
      }catch(e){}
      // 绑定时间选择按钮事件
      try{
        $("btnPiePickTime").addEventListener("click", () => { pieOpenTimePicker(); });
        const a = $("fPieTimeStartShow");
        if(a){
          a.addEventListener("click", (ev) => {
            const t = ev && ev.target ? ev.target : a;
            openDatePop(t, String(pieTimeStart || ""), (v) => {
              try{
                pieTimeStart = String(v || "");
                if(pieTimePreset) pieTimePreset = "";
                if(pieTimeEndNow) pieTimeEndNow = false;
                pieSyncTimeRangeUI();
              }catch(e){}
            });
          });
          a.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); a.click(); } });
        }
        const b = $("fPieTimeEndShow");
        if(b){
          b.addEventListener("click", (ev) => {
            const t = ev && ev.target ? ev.target : b;
            openDatePop(t, String(pieTimeEnd || ""), (v) => {
              try{
                pieTimeEnd = String(v || "");
                if(pieTimePreset) pieTimePreset = "";
                if(pieTimeEndNow) pieTimeEndNow = false;
                pieSyncTimeRangeUI();
              }catch(e){}
            });
          });
          b.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); b.click(); } });
        }
      }catch(e){}
      // 绑定分类字段变化事件
      try{
        $("fPieCat").addEventListener("change", () => { pieRefreshFilterFieldOptions(); });
      }catch(e){}
      // 绑定时间类型变化事件
      try{
        $("fPieTimeType").addEventListener("change", () => { pieSyncTimeTypeUI(); });
      }catch(e){}
    }

    // 同步时间类型UI显示
    function pieSyncTimeTypeUI(){
      try{
        const timeType = String(($("fPieTimeType") && $("fPieTimeType").value) || "all");
        const showTimeOptions = timeType !== "all";
        const rangeWrap = $("pieTimeRangeWrap");
        if(rangeWrap) rangeWrap.style.display = showTimeOptions ? "" : "none";
      }catch(e){}
    }

    // 同步时间范围UI显示
    function pieSyncTimeRangeUI(){
      try{
        const s = $("fPieTimeStartShow");
        const e = $("fPieTimeEndShow");
        if(!s || !e) return;
        if(pieTimePreset){
          const name = pieTimePreset === "now" ? "至今" :
                       pieTimePreset === "today" ? "今天" :
                       pieTimePreset === "week" ? "最近7天" :
                       pieTimePreset === "month" ? "本月" :
                       pieTimePreset === "year" ? "最近一年" : pieTimePreset;
          if(pieTimePreset === "now"){
            if(s) s.value = String(pieTimeStart || "");
            if(e) e.value = "至今";
          }else{
            if(s) s.value = name;
            if(e) e.value = name;
          }
          return;
        }
        if(s) s.value = String(pieTimeStart || "");
        if(e) e.value = pieTimeEndNow ? "至今" : String(pieTimeEnd || "");
      }catch(e){}
    }

    // 打开时间选择器
    function pieOpenTimePicker(){
      try{ pieEnsureInit(); }catch(e){}
      try{
        const now = new Date();
        let displayStart = pieTimeStart || "";
        let displayEnd = pieTimeEnd || "";
        if(pieTimePreset && pieTimePreset !== "now"){
          const today = barFmtDate(now);
          if(pieTimePreset === "today"){
            displayStart = today;
            displayEnd = today;
          }else if(pieTimePreset === "week"){
            const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(pieTimePreset === "month"){
            const s = new Date(now.getFullYear(), now.getMonth(), 1);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(pieTimePreset === "year"){
            const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }
        }
        // 复用柱状图的时间选择器
        if($("barTimePickStart")) $("barTimePickStart").value = String(displayStart || "");
        if($("barTimePickEnd")) $("barTimePickEnd").value = String(displayEnd || "");
        try{
          if(pieTimePreset === "now"){
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = true;
          }else{
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = !!pieTimeEndNow;
          }
        }catch(e){}
        try{ barSyncTimePickerPresetUI(); }catch(e){}
      }catch(e){}
      try{ upgradeAllSelects(); }catch(e){}
      openModal("modalBarTime");
      // 临时保存当前上下文为饼图
      window._tempPieContext = true;
    }

    // 获取饼图筛选条件
    function pieGetFilters(){
      return barGetFilters("pieFilterList");
    }

    // 从配置加载饼图选项
    function pieLoadFromOptions(opt){
      try{ pieEnsureInit(); }catch(e){}
      const o = opt && typeof opt === "object" ? opt : {};
      try{ $("fPieCat").value = String(o.category_field || "species"); refreshSelectLabel($("fPieCat")); }catch(e){}
      try{ $("fPieAgg").value = String(o.value_agg || "count"); refreshSelectLabel($("fPieAgg")); }catch(e){}
      try{ $("fPieTimeType").value = String(o.pie_time_type || "all"); refreshSelectLabel($("fPieTimeType")); }catch(e){}
      try{ pieTimePreset = String(o.pie_time_preset || ""); }catch(e){ pieTimePreset = ""; }
      try{ pieTimeStart = String(o.pie_time_start || ""); }catch(e){ pieTimeStart = ""; }
      try{ pieTimeEnd = String(o.pie_time_end || ""); }catch(e){ pieTimeEnd = ""; }
      try{ pieTimeEndNow = !!o.pie_time_end_now; }catch(e){ pieTimeEndNow = false; }
      try{ pieSyncTimeTypeUI(); }catch(e){}
      try{ pieSyncTimeRangeUI(); }catch(e){}
      try{
        barClearFilters("pieFilterList");
        const filters = o.pie_filters || [];
        for(const c of filters){
          try{ barAddFilterRow(c, "pieFilterList"); }catch(e){}
        }
        try{ pieRefreshFilterFieldOptions(); }catch(e){}
      }catch(e){}
    }

    
    // ========== 散点图相关函数 ==========
    let scatterInited = false;
    let scatterTimeStart = "";
    let scatterTimeEnd = "";
    let scatterTimeEndNow = false;
    let scatterTimePreset = "";
    
    // 散点图字段与筛选项的映射关系
    function scatterFieldToFilterField(field){
      const map = {
        "score": "分数",
        "rating": "评星",
        "shot_time": "拍摄时间",
        "created_at": "创建时间"
      };
      return map[field] || "";
    }
    
    // 同步散点图时间类型UI显示
    function scatterSyncTimeTypeUI(){
      try{
        const xField = String(($("fSX") && $("fSX").value) || "rating");
        const isXTime = (xField === "shot_time" || xField === "created_at");
        const timeRangeWrap = $("scatterTimeRangeWrap");
        const timeGroupWrap = $("scatterTimeGroupWrap");
        if(timeRangeWrap) timeRangeWrap.style.display = isXTime ? "" : "none";
        if(timeGroupWrap) timeGroupWrap.style.display = isXTime ? "" : "none";
      }catch(e){}
    }
    
    // 同步散点图时间范围UI显示
    function scatterSyncTimeRangeUI(){
      try{
        const s = $("fScatterTimeStartShow");
        const e = $("fScatterTimeEndShow");
        if(!s || !e) return;
        if(scatterTimePreset){
          const name = scatterTimePreset === "now" ? "至今" :
                       scatterTimePreset === "today" ? "今天" :
                       scatterTimePreset === "week" ? "最近7天" :
                       scatterTimePreset === "month" ? "本月" :
                       scatterTimePreset === "year" ? "最近一年" : scatterTimePreset;
          if(scatterTimePreset === "now"){
            if(s) s.value = String(scatterTimeStart || "");
            if(e) e.value = "至今";
          }else{
            if(s) s.value = name;
            if(e) e.value = name;
          }
          return;
        }
        if(s) s.value = String(scatterTimeStart || "");
        if(e) e.value = scatterTimeEndNow ? "至今" : String(scatterTimeEnd || "");
      }catch(e){}
    }
    
    // 打开散点图时间选择器
    function scatterOpenTimePicker(){
      try{ scatterEnsureInit(); }catch(e){}
      try{
        const now = new Date();
        let displayStart = scatterTimeStart || "";
        let displayEnd = scatterTimeEnd || "";
        if(scatterTimePreset && scatterTimePreset !== "now"){
          const today = barFmtDate(now);
          if(scatterTimePreset === "today"){
            displayStart = today;
            displayEnd = today;
          }else if(scatterTimePreset === "week"){
            const s = new Date(now.getTime() - 6 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(scatterTimePreset === "month"){
            const s = new Date(now.getFullYear(), now.getMonth(), 1);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }else if(scatterTimePreset === "year"){
            const s = new Date(now.getTime() - 364 * 24 * 3600 * 1000);
            displayStart = barFmtDate(s);
            displayEnd = today;
          }
        }
        if($("barTimePickStart")) $("barTimePickStart").value = String(displayStart || "");
        if($("barTimePickEnd")) $("barTimePickEnd").value = String(displayEnd || "");
        try{
          if(scatterTimePreset === "now"){
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = true;
          }else{
            $("barTimePickStart").disabled = false;
            $("barTimePickEnd").disabled = !!scatterTimeEndNow;
          }
        }catch(e){}
        try{ barSyncTimePickerPresetUI(); }catch(e){}
      }catch(e){}
      try{ upgradeAllSelects(); }catch(e){}
      openModal("modalBarTime");
      window._tempScatterContext = true;
    }
    
    // 获取散点图可用的筛选字段（排除当前X和Y字段）
    function scatterAllFilterFields(){
      const all = ["文件名","标签","路径","评星","分数","鸟的位置","色标","目","科","属","种","备注","拍摄时间","拍摄地址"];
      const xField = String(($("fSX") && $("fSX").value) || "");
      const yField = String(($("fSY") && $("fSY").value) || "");
      const excludedX = scatterFieldToFilterField(xField);
      const excludedY = scatterFieldToFilterField(yField);
      return all.filter(f => f !== excludedX && f !== excludedY);
    }
    
    // 刷新散点图筛选字段选项
    function scatterRefreshFilterFieldOptions(){
      const list = $("scatterFilterList");
      if(!list) return;
      const rows = Array.from(list.querySelectorAll(".filterRow"));
      const availableFields = scatterAllFilterFields();
      for(const row of rows){
        const fieldSel = row.querySelector("select[data-role='field']");
        if(!fieldSel) continue;
        const prev = String(fieldSel.value || "");
        fieldSel.innerHTML = "";
        for(const f of availableFields){
          const o = document.createElement("option");
          o.value = f;
          o.textContent = f;
          fieldSel.appendChild(o);
        }
        try{
          if(prev && Array.from(fieldSel.options).some(o => String(o.value) === prev)){
            fieldSel.value = prev;
          }else{
            fieldSel.selectedIndex = 0;
          }
        }catch(e){}
        try{ refreshSelectLabel(fieldSel); }catch(e){}
        try{ barUpdateRowUI(row); }catch(e){}
      }
    }
    
    // 树图相关变量
    let treeInited = false;
    let treeTimeStart = "";
    let treeTimeEnd = "";
    
    // 树图初始化
    function treeEnsureInit(){
      if(treeInited) return;
      treeInited = true;
      try{ treeSyncLayoutUI(); }catch(e){}
      try{ treeSyncTimeTypeUI(); }catch(e){}
      try{ treeSyncTimeRangeUI(); }catch(e){}
      // 绑定筛选按钮事件
      try{
        $("btnTreeAddCond").addEventListener("click", () => { barAddFilterRow(null, "treeFilterList"); treeRefreshFilterFieldOptions(); });
        $("btnTreeClearCond").addEventListener("click", () => { barClearFilters("treeFilterList"); });
      }catch(e){}
      // 绑定布局变化事件
      try{
        $("fTreeLayout").addEventListener("change", () => { treeSyncLayoutUI(); });
      }catch(e){}
      // 绑定时间类型变化事件
      try{
        $("fTreeTimeType").addEventListener("change", () => { treeSyncTimeTypeUI(); });
      }catch(e){}
      // 绑定时间选择按钮事件
      try{
        $("btnTreePickTime").addEventListener("click", () => { treeOpenTimePicker(); });
        const a = $("fTreeTimeStartShow");
        if(a){
          a.addEventListener("click", (ev) => {
            const t = ev && ev.target ? ev.target : a;
            openDatePop(t, String(treeTimeStart || ""), (v) => {
              try{
                treeTimeStart = String(v || "");
                treeSyncTimeRangeUI();
              }catch(e){}
            });
          });
        }
        const b = $("fTreeTimeEndShow");
        if(b){
          b.addEventListener("click", (ev) => {
            const t = ev && ev.target ? ev.target : b;
            openDatePop(t, String(treeTimeEnd || ""), (v) => {
              try{
                treeTimeEnd = String(v || "");
                treeSyncTimeRangeUI();
              }catch(e){}
            });
          });
        }
      }catch(e){}
    }
    
    // 同步树图布局UI
    function treeSyncLayoutUI(){
      // 布局选项已合并，无需额外处理
    }
    
    // 同步树图时间类型UI
    function treeSyncTimeTypeUI(){
      try{
        const timeType = String(($("fTreeTimeType") && $("fTreeTimeType").value) || "all");
        const timeRangeWrap = $("treeTimeRangeWrap");
        if(timeRangeWrap) timeRangeWrap.style.display = timeType === "custom" ? "" : "none";
      }catch(e){}
    }
    
    // 同步树图时间范围UI
    function treeSyncTimeRangeUI(){
      try{
        const s = $("fTreeTimeStartShow");
        const e = $("fTreeTimeEndShow");
        if(s) s.value = String(treeTimeStart || "");
        if(e) e.value = String(treeTimeEnd || "");
      }catch(e){}
    }
    
    // 树图时间选择器
    function treeOpenTimePicker(){
      try{
        if(window.openBarTimePickerModal){
          openBarTimePickerModal("tree");
        }
      }catch(e){}
    }
    
    // 获取树图筛选条件
    function treeGetFilters(){
      return barGetFilters("treeFilterList");
    }
    
    // 刷新树图筛选字段选项
    function treeRefreshFilterFieldOptions(){
      try{
        const excluded = new Set(["目", "科", "属", "种", "拍摄时间"]);
        barRefreshFilterFieldOptionsFor("treeFilterList", excluded);
      }catch(e){}
    }
    
    // 加载树图配置
    function treeLoadFromOptions(opt){
      try{ treeEnsureInit(); }catch(e){}
      const o = opt && typeof opt === "object" ? opt : {};
      // 加载层级
      const levels = o.tree_levels || ["order", "family", "genus", "species"];
      try{ $("fTreeLevelOrder").checked = levels.includes("order"); }catch(e){}
      try{ $("fTreeLevelFamily").checked = levels.includes("family"); }catch(e){}
      try{ $("fTreeLevelGenus").checked = levels.includes("genus"); }catch(e){}
      try{ $("fTreeLevelSpecies").checked = levels.includes("species"); }catch(e){}
      // 加载其他选项
      try{ $("fTreeShowCount").checked = o.tree_show_count !== false; }catch(e){}
      try{ $("fTreeLayout").value = String(o.tree_layout || "LR"); refreshSelectLabel($("fTreeLayout")); }catch(e){}
      try{ $("fTreeTimeType").value = String(o.tree_time_type || "all"); refreshSelectLabel($("fTreeTimeType")); }catch(e){}
      try{ treeTimeStart = String(o.tree_time_start || ""); }catch(e){ treeTimeStart = ""; }
      try{ treeTimeEnd = String(o.tree_time_end || ""); }catch(e){ treeTimeEnd = ""; }
      try{ treeSyncLayoutUI(); }catch(e){}
      try{ treeSyncTimeTypeUI(); }catch(e){}
      try{ treeSyncTimeRangeUI(); }catch(e){}
      // 加载筛选条件
      try{
        barClearFilters("treeFilterList");
        const filters = o.tree_filters || [];
        for(const c of filters){
          try{ barAddFilterRow(c, "treeFilterList"); }catch(e){}
        }
        try{ treeRefreshFilterFieldOptions(); }catch(e){}
      }catch(e){}
    }
    
    // 散点图初始化
    function scatterEnsureInit(){
      if(scatterInited) return;
      scatterInited = true;
      try{ scatterSyncTimeTypeUI(); }catch(e){}
      try{ scatterSyncTimeRangeUI(); }catch(e){}
      // 绑定筛选按钮事件
      try{
        $("btnScatterAddCond").addEventListener("click", () => { barAddFilterRow(null, "scatterFilterList"); scatterRefreshFilterFieldOptions(); });
        $("btnScatterClearCond").addEventListener("click", () => { barClearFilters("scatterFilterList"); });
      }catch(e){}
      // 绑定X/Y字段变化事件
      try{
        $("fSX").addEventListener("change", () => { scatterRefreshFilterFieldOptions(); scatterSyncTimeTypeUI(); });
        $("fSY").addEventListener("change", () => { scatterRefreshFilterFieldOptions(); scatterSyncTimeTypeUI(); });
      }catch(e){}
      // 绑定时间选择按钮事件
      try{
        $("btnScatterPickTime").addEventListener("click", () => { scatterOpenTimePicker(); });
        const a = $("fScatterTimeStartShow");
        if(a){
          a.addEventListener("click", (ev) => {
            const t = ev && ev.target ? ev.target : a;
            openDatePop(t, String(scatterTimeStart || ""), (v) => {
              try{
                scatterTimeStart = String(v || "");
                if(scatterTimePreset) scatterTimePreset = "";
                if(scatterTimeEndNow) scatterTimeEndNow = false;
                scatterSyncTimeRangeUI();
              }catch(e){}
            });
          });
          a.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); a.click(); } });
        }
        const b = $("fScatterTimeEndShow");
        if(b){
          b.addEventListener("click", (ev) => {
            const t = ev && ev.target ? ev.target : b;
            openDatePop(t, String(scatterTimeEnd || ""), (v) => {
              try{
                scatterTimeEnd = String(v || "");
                if(scatterTimePreset) scatterTimePreset = "";
                if(scatterTimeEndNow) scatterTimeEndNow = false;
                scatterSyncTimeRangeUI();
              }catch(e){}
            });
          });
          b.addEventListener("keydown", (ev) => { if(ev && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); b.click(); } });
        }
      }catch(e){}
    }
    
    // 获取散点图筛选条件
    function scatterGetFilters(){
      return barGetFilters("scatterFilterList");
    }
    
    // 从配置加载散点图选项
    function scatterLoadFromOptions(opt){
      try{ scatterEnsureInit(); }catch(e){}
      const o = opt && typeof opt === "object" ? opt : {};
      try{ $("fSX").value = String(o.x_field || "score"); refreshSelectLabel($("fSX")); }catch(e){}
      try{ $("fSY").value = String(o.y_field || "count"); refreshSelectLabel($("fSY")); }catch(e){}
      try{ $("fScatterAutoSize").checked = !!o.scatter_auto_size; }catch(e){}
      try{ $("fScatterTimeGroup").value = String(o.scatter_time_group || "day"); refreshSelectLabel($("fScatterTimeGroup")); }catch(e){}
      try{ scatterTimePreset = String(o.scatter_time_preset || ""); }catch(e){ scatterTimePreset = ""; }
      try{ scatterTimeStart = String(o.scatter_time_start || ""); }catch(e){ scatterTimeStart = ""; }
      try{ scatterTimeEnd = String(o.scatter_time_end || ""); }catch(e){ scatterTimeEnd = ""; }
      try{ scatterTimeEndNow = !!o.scatter_time_end_now; }catch(e){ scatterTimeEndNow = false; }
      try{ scatterSyncTimeTypeUI(); }catch(e){}
      try{ scatterSyncTimeRangeUI(); }catch(e){}
      try{
        barClearFilters("scatterFilterList");
        const filters = o.scatter_filters || [];
        for(const c of filters){
          try{ barAddFilterRow(c, "scatterFilterList"); }catch(e){}
        }
        try{ scatterRefreshFilterFieldOptions(); }catch(e){}
      }catch(e){}
    }

    function barRefreshFilterFieldOptions(){
      const kind = String(($("fBarXKind") && $("fBarXKind").value) || "time");
      const excluded = barXExcludeField(kind);
      const list = $("barFilterList");
      if(!list) return;
      const rows = Array.from(list.querySelectorAll(".filterRow"));
      for(const row of rows){
        const fieldSel = row.querySelector("select[data-role='field']");
        if(!fieldSel) continue;
        const prev = String(fieldSel.value || "");
        fieldSel.innerHTML = "";
        for(const f of barAllFilterFields()){
          if(excluded && f === excluded) continue;
          const o = document.createElement("option");
          o.value = f;
          o.textContent = f;
          fieldSel.appendChild(o);
        }
        try{
          if(prev && Array.from(fieldSel.options).some(o => String(o.value) === prev)){
            fieldSel.value = prev;
          }else{
            fieldSel.selectedIndex = 0;
          }
        }catch(e){}
        try{ refreshSelectLabel(fieldSel); }catch(e){}
        try{ barUpdateRowUI(row); }catch(e){}
      }
    }
    function barClearFilters(listId){
      const list = $(listId || "barFilterList");
      if(!list) return;
      list.innerHTML = "";
    }
    function barAddFilterRow(data, listId){
      const list = $(listId || "barFilterList");
      if(!list) return;
      const isFirst = list.children.length === 0;
      const row = document.createElement("div");
      row.className = "filterRow";

      const logicSel = document.createElement("select");
      logicSel.className = "select mini";
      logicSel.setAttribute("data-role", "logic");
      for(const v of ["AND","OR","NOT"]){
        const o = document.createElement("option");
        o.value = v;
        o.textContent = (v === "AND") ? "与" : (v === "OR" ? "或" : "非");
        logicSel.appendChild(o);
      }
      if(isFirst){
        logicSel.value = "AND";
        logicSel.disabled = true;
        logicSel.style.opacity = "0.6";
      }

      const fieldSel = document.createElement("select");
      fieldSel.className = "select mini";
      fieldSel.setAttribute("data-role", "field");

      const opSel = document.createElement("select");
      opSel.className = "select op";
      opSel.setAttribute("data-role", "op");
      const opMap = {"=": "等于", ">=": "大于等于", "<=": "小于等于"};
      for(const v of ["=" , ">=", "<="]){
        const o = document.createElement("option");
        o.value = v;
        o.textContent = opMap[v] || v;
        opSel.appendChild(o);
      }
      opSel.style.display = "none";
      opSel.disabled = true;

      const valWrap = document.createElement("div");
      valWrap.className = "val";
      valWrap.setAttribute("data-role", "val");

      const fuzzyLab = document.createElement("label");
      fuzzyLab.className = "fuzzy";
      fuzzyLab.setAttribute("data-role", "fuzzy");
      const fuzzyCb = document.createElement("input");
      fuzzyCb.type = "checkbox";
      const fuzzyTxt = document.createElement("span");
      fuzzyTxt.textContent = "模糊";
      fuzzyLab.appendChild(fuzzyCb);
      fuzzyLab.appendChild(fuzzyTxt);

      const rmBtn = document.createElement("button");
      rmBtn.className = "btn";
      rmBtn.type = "button";
      rmBtn.textContent = "删";
      rmBtn.addEventListener("click", () => {
        try{ row.remove(); }catch(e){}
        try{
          const first = $(listId || "barFilterList") && $(listId || "barFilterList").firstElementChild;
          if(first){
            const ls = first.querySelector("select[data-role='logic']");
            if(ls){
              ls.value = "AND";
              ls.disabled = true;
              ls.style.opacity = "0.6";
            }
          }
        }catch(e){}
      });

      fieldSel.addEventListener("change", () => { barUpdateRowUI(row); });

      row.appendChild(logicSel);
      row.appendChild(fieldSel);
      row.appendChild(opSel);
      row.appendChild(valWrap);
      row.appendChild(fuzzyLab);
      row.appendChild(rmBtn);

      list.appendChild(row);
      try{
        upgradeSelect(logicSel);
        upgradeSelect(fieldSel);
        upgradeSelect(opSel);
      }catch(e){}
      try{ barRefreshFilterFieldOptions(); }catch(e){}
      if(data && typeof data === "object"){
        try{ logicSel.value = isFirst ? "AND" : String(data.logic || "AND").toUpperCase(); }catch(e){}
        try{ fuzzyCb.checked = !!data.fuzzy; }catch(e){}
        try{ opSel.value = String(data.operator || "="); }catch(e){}
        try{
          let f = String(data.field || "文件名");
          if(f === "评分") f = "评星";
          fieldSel.value = f;
        }catch(e){}
        try{ refreshSelectLabel(logicSel); }catch(e){}
        try{ refreshSelectLabel(opSel); }catch(e){}
        try{ refreshSelectLabel(fieldSel); }catch(e){}
        try{ barUpdateRowUI(row, data); }catch(e){}
      }else{
        try{ barUpdateRowUI(row); }catch(e){}
      }
    }
    function barUpdateRowUI(row, preset){
      const fieldSel = row.querySelector("select[data-role='field']");
      const opSel = row.querySelector("select[data-role='op']");
      const valWrap = row.querySelector("[data-role='val']");
      const fuzzyLab = row.querySelector("[data-role='fuzzy']");
      const fuzzyCb = fuzzyLab ? fuzzyLab.querySelector("input[type='checkbox']") : null;
      const field = String(fieldSel ? fieldSel.value : "");
      const setFuzzyVisible = (on) => {
        if(!fuzzyLab) return;
        fuzzyLab.style.display = on ? "" : "none";
      };
      const setOpVisible = (on) => {
        if(!opSel) return;
        try{
          const wrap = opSel.__bpUpgraded ? opSel.parentNode : null;
          if(wrap && wrap.classList && wrap.classList.contains("bp-select")){
            wrap.style.display = on ? "" : "none";
          }
        }catch(e){}
        opSel.style.display = on ? "" : "none";
        opSel.disabled = !on;
      };
      if(!valWrap) return;
      valWrap.innerHTML = "";

      if(field === "评星"){
        setOpVisible(false);
        setFuzzyVisible(false);
        const sel = document.createElement("select");
        sel.className = "select";
        sel.style.minWidth = "120px";
        for(let i=1;i<=5;i++){
          const o = document.createElement("option");
          o.value = String(i);
          o.textContent = i + " 星";
          sel.appendChild(o);
        }
        valWrap.appendChild(sel);
        try{ upgradeSelect(sel); }catch(e){}
        try{
          const v = preset ? String(preset.value || "1") : "1";
          sel.value = v;
          refreshSelectLabel(sel);
        }catch(e){}
        return;
      }
      if(field === "分数"){
        setOpVisible(true);
        setFuzzyVisible(false);
        const inp = document.createElement("input");
        inp.className = "select";
        inp.type = "number";
        inp.step = "1";
        inp.placeholder = "输入分数";
        try{ if(preset) inp.value = String(preset.value || ""); }catch(e){}
        valWrap.appendChild(inp);
        return;
      }
      if(field === "色标"){
        setOpVisible(false);
        setFuzzyVisible(false);
        const sel = document.createElement("select");
        sel.className = "select";
        const labels = [
          ["红色","Red"],["橙色","Orange"],["黄色","Yellow"],["绿色","Green"],["青色","Cyan"],["蓝色","Blue"],
          ["紫色","Purple"],["粉色","Pink"],["白色","White"],["灰色","Gray"],["黑色","Black"],["无色标","None"]
        ];
        for(const [cn, en] of labels){
          const o = document.createElement("option");
          o.value = en;
          o.textContent = cn;
          sel.appendChild(o);
        }
        valWrap.appendChild(sel);
        try{ upgradeSelect(sel); }catch(e){}
        try{
          const v = preset ? String(preset.value || "Green") : "Green";
          sel.value = v;
          refreshSelectLabel(sel);
        }catch(e){}
        return;
      }
      if(field === "鸟的位置"){
        setOpVisible(false);
        setFuzzyVisible(false);
        const sel = document.createElement("select");
        sel.className = "select";
        const items = [
          ["中间","Center"],["上","Top"],["下","Bottom"],["左","Left"],["右","Right"],
          ["左上","TopLeft"],["右上","TopRight"],["左下","BottomLeft"],["右下","BottomRight"]
        ];
        for(const [cn, v] of items){
          const o = document.createElement("option");
          o.value = v;
          o.textContent = cn;
          sel.appendChild(o);
        }
        valWrap.appendChild(sel);
        try{ upgradeSelect(sel); }catch(e){}
        try{
          const v = preset ? String(preset.value || "Center") : "Center";
          sel.value = v;
          refreshSelectLabel(sel);
        }catch(e){}
        return;
      }
      if(field === "标签"){
        try{
          const tags = (state && Array.isArray(state.tags)) ? state.tags : [];
          if(tags && tags.length){
            setOpVisible(false);
            setFuzzyVisible(false);
            const sel = document.createElement("select");
            sel.className = "select";
            for(const it of tags){
              const o = document.createElement("option");
              o.value = it.id;
              o.textContent = it.title || it.id;
              sel.appendChild(o);
            }
            valWrap.appendChild(sel);
            try{ upgradeSelect(sel); }catch(e){}
            try{
              const v = preset ? String(preset.value || "") : "";
              if(v) sel.value = v;
              refreshSelectLabel(sel);
            }catch(e){}
            return;
          }
        }catch(e){}
      }
      if(field === "拍摄时间"){
        setOpVisible(false);
        setFuzzyVisible(false);
        const wrap = document.createElement("div");
        wrap.className = "valRange";
        const a = document.createElement("input");
        a.className = "select";
        a.type = "text";
        a.readOnly = true;
        const b = document.createElement("input");
        b.className = "select";
        b.type = "text";
        b.readOnly = true;
        const sep = document.createElement("span");
        sep.className = "sep";
        sep.textContent = "至";
        wrap.appendChild(a);
        wrap.appendChild(sep);
        wrap.appendChild(b);
        valWrap.classList.remove("val");
        valWrap.appendChild(wrap);
        try{
          wireDateInput(a);
          wireDateInput(b);
        }catch(e){}
        try{
          const raw = preset ? String(preset.value || "") : "";
          const parts = raw.split("||");
          if(parts.length === 2){
            const s = parts[0].trim().slice(0, 10);
            const e = parts[1].trim().slice(0, 10);
            if(s) a.value = s;
            if(e) b.value = e;
          }
        }catch(e){}
        return;
      }

      setOpVisible(false);
      setFuzzyVisible(true);
      if(fuzzyCb && preset && typeof preset.fuzzy !== "undefined"){
        try{ fuzzyCb.checked = !!preset.fuzzy; }catch(e){}
      }
      const inp = document.createElement("input");
      inp.className = "select";
      inp.type = "text";
      inp.placeholder = "搜索内容...";
      try{ if(preset) inp.value = String(preset.value || ""); }catch(e){}
      valWrap.appendChild(inp);
    }
    function barGetFilters(listId){
      const list = $(listId || "barFilterList");
      if(!list) return [];
      const rows = Array.from(list.querySelectorAll(".filterRow"));
      const out = [];
      rows.forEach((row, idx) => {
        const logicSel = row.querySelector("select[data-role='logic']");
        const fieldSel = row.querySelector("select[data-role='field']");
        const opSel = row.querySelector("select[data-role='op']");
        const fuzzyCb = row.querySelector("[data-role='fuzzy'] input[type='checkbox']");
        const field = String(fieldSel ? fieldSel.value : "");
        let value = "";
        if(field === "评星" || field === "色标" || field === "鸟的位置" || field === "标签"){
          const sel = row.querySelector("[data-role='val'] select");
          value = sel ? String(sel.value || "") : "";
        }else if(field === "分数"){
          const inp = row.querySelector("[data-role='val'] input[type='number']");
          value = inp ? String(inp.value || "").trim() : "";
        }else if(field === "拍摄时间"){
          const dates = row.querySelectorAll("[data-role='val'] input.select");
          const a = dates && dates[0] ? String(dates[0].value || "").trim() : "";
          const b = dates && dates[1] ? String(dates[1].value || "").trim() : "";
          value = a && b ? (a + "||" + b) : "";
        }else{
          const inp = row.querySelector("[data-role='val'] input[type='text']");
          value = inp ? String(inp.value || "").trim() : "";
        }
        const logic = idx === 0 ? "AND" : String((logicSel ? logicSel.value : "AND") || "AND").toUpperCase();
        const operator = (field === "分数") ? String((opSel ? opSel.value : "=") || "=") : (field === "拍摄时间" ? "between" : "");
        const fuzzy = (field !== "评星" && field !== "分数" && field !== "色标" && field !== "标签" && field !== "拍摄时间") ? !!(fuzzyCb && fuzzyCb.checked) : false;
        if(!field || !value) return;
        out.push({logic, field, operator, value, fuzzy});
      });
      return out;
    }
    function barLoadFromOptions(opt){
      const o = opt && typeof opt === "object" ? opt : {};
      try{ $("fBarXKind").value = String(o.bar_x_kind || "time"); refreshSelectLabel($("fBarXKind")); }catch(e){}
      try{ $("fBarYKind").value = String(o.bar_y_kind || "count"); refreshSelectLabel($("fBarYKind")); }catch(e){}
      // 加载时间类型选择，默认为拍摄时间
      try{ $("fBarTimeType").value = String(o.bar_time_type || "shot_time"); refreshSelectLabel($("fBarTimeType")); }catch(e){}
      try{ barTimePreset = String(o.bar_time_preset || ""); }catch(e){ barTimePreset = ""; }
      try{ barTimeStart = String(o.bar_time_start || barTimeStart || ""); }catch(e){}
      try{ barTimeEnd = String(o.bar_time_end || ""); }catch(e){}
      try{
        const endRaw = String(o.bar_time_end || "").trim().toLowerCase();
        barTimeEndNow = !!(o.bar_time_end_now || ["now","__now__","today","至今"].includes(endRaw));
      }catch(e){
        barTimeEndNow = !!(o.bar_time_end_now);
      }
      try{ barSyncTimeRangeUI(); }catch(e){}
      try{ $("fBarTimeStep").value = String(o.bar_time_step || 1); }catch(e){}
      try{ $("fBarTimeUnit").value = String(o.bar_time_unit || "day"); refreshSelectLabel($("fBarTimeUnit")); }catch(e){}
      try{ $("fBarLocLevel").value = String(o.bar_location_level || "country"); refreshSelectLabel($("fBarLocLevel")); }catch(e){}
      try{ $("fBarHideEmptyTime").checked = !!o.bar_ignore_empty_dates; }catch(e){}
      try{ barClearFilters(); }catch(e){}
      try{
        const fs = o.bar_filters;
        if(Array.isArray(fs) && fs.length){
          const list = $("barFilterList");
          if(list) list.innerHTML = "";
          fs.forEach((c, idx) => {
            barAddFilterRow(Object.assign({logic: idx === 0 ? "AND" : (c.logic || "AND")}, c));
          });
        }
      }catch(e){}
      try{ barSyncModeUI(); }catch(e){}
    }
    function refreshSelectLabel(sel){
      try{
        if(!sel || !sel.__bpUpgraded) return;
        const wrap = sel.parentNode;
        if(!wrap || !wrap.querySelector) return;
        const label = wrap.querySelector(".bp-select-btn [data-label]");
        if(!label) return;
        const curOpt = sel.options && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex] : null;
        label.textContent = (curOpt && (curOpt.textContent || curOpt.value)) || sel.value || "";
      }catch(e){}
    }
    function fillSelect(sel, items, withEmpty){
      const prev = sel ? (sel.value || "") : "";
      sel.innerHTML = "";
      if(withEmpty){
        const o = document.createElement("option");
        o.value = "";
        o.textContent = "不分组";
        sel.appendChild(o);
      }
      (items||[]).forEach(it => {
        const o = document.createElement("option");
        o.value = it.id;
        o.textContent = it.title;
        if(it && it.disabled === true){
          o.disabled = true;
        }
        sel.appendChild(o);
      });
      try{
        if(prev){
          for(const o of Array.from(sel.options || [])){
            if(String(o.value) === String(prev)){
              sel.value = prev;
              break;
            }
          }
        }
        if((sel.selectedIndex < 0) && sel.options && sel.options.length > 0){
          sel.selectedIndex = 0;
        }
      }catch(e){}
      refreshSelectLabel(sel);
    }

    function snap(n){
      const g = Number(getComputedStyle(document.documentElement).getPropertyValue("--grid").replace("px","")) || 10;
      return Math.round(n / g) * g;
    }
    function clamp(v, min, max){ return Math.max(min, Math.min(max, v)); }
    function deskRect(){ 
      const rect = desk.getBoundingClientRect();
      // 返回一个足够大的矩形，允许动态扩展
      return {
        x: rect.x,
        y: rect.y,
        width: Math.max(rect.width, getMinDeskWidth()),
        height: Math.max(rect.height, getMinDeskHeight()),
        left: rect.left,
        top: rect.top,
        right: Math.max(rect.right, getMinDeskWidth()),
        bottom: Math.max(rect.bottom, getMinDeskHeight())
      };
    }
    
    function getMinDeskHeight(){
      // 计算所有图表的底部位置，确保desk足够高
      let maxY = window.innerHeight;
      const wins = document.querySelectorAll("#desk .win");
      wins.forEach(el => {
        const y = parseFloat(el.style.top || "0");
        const h = parseFloat(el.style.height || "360");
        maxY = Math.max(maxY, y + h + 100);
      });
      return maxY;
    }
    
    function getMinDeskWidth(){
      // 计算所有图表的右边界位置，确保desk足够宽
      let maxX = window.innerWidth;
      const wins = document.querySelectorAll("#desk .win");
      wins.forEach(el => {
        const x = parseFloat(el.style.left || "0");
        const w = parseFloat(el.style.width || "520");
        maxX = Math.max(maxX, x + w + 100);
      });
      return maxX;
    }
    
    function expandDeskIfNeeded(){
      const minH = getMinDeskHeight();
      const minW = getMinDeskWidth();
      const currentH = desk.offsetHeight;
      const currentW = desk.offsetWidth;
      if(minH > currentH){
        desk.style.height = minH + "px";
        desk.style.minHeight = minH + "px";
      }
      if(minW > currentW){
        desk.style.width = minW + "px";
        desk.style.minWidth = minW + "px";
      }
      // 同时更新背景canvas的大小
      try{
        const gridCanvas = $("gridGuideCanvas");
        if(gridCanvas){
          gridCanvas.width = desk.offsetWidth;
          gridCanvas.height = desk.offsetHeight;
        }
      }catch(e){}
    }
    
    // 拖拽空白处移动视图
    let isPanning = false;
    let panStartX = 0;
    let panStartY = 0;
    let panStartScrollX = 0;
    let panStartScrollY = 0;
    
    function initPanning(){
      const workspace = document.querySelector('.workspace');
      if(!workspace) return;
      
      workspace.addEventListener('pointerdown', (e) => {
        // 只在点击空白处（不是图表）时触发
        if(e.target.closest('.win')) return;
        if(e.button !== 0) return;
        
        isPanning = true;
        panStartX = e.clientX;
        panStartY = e.clientY;
        panStartScrollX = workspace.scrollLeft;
        panStartScrollY = workspace.scrollTop;
        workspace.setPointerCapture(e.pointerId);
        workspace.style.cursor = 'grabbing';
        e.preventDefault();
      });
      
      workspace.addEventListener('pointermove', (e) => {
        if(!isPanning) return;
        
        const dx = e.clientX - panStartX;
        const dy = e.clientY - panStartY;
        workspace.scrollLeft = panStartScrollX - dx;
        workspace.scrollTop = panStartScrollY - dy;
      });
      
      workspace.addEventListener('pointerup', (e) => {
        if(!isPanning) return;
        isPanning = false;
        workspace.releasePointerCapture(e.pointerId);
        workspace.style.cursor = '';
      });
      
      workspace.addEventListener('pointercancel', (e) => {
        if(!isPanning) return;
        isPanning = false;
        workspace.releasePointerCapture(e.pointerId);
        workspace.style.cursor = '';
      });
    }

    function cssVar(name, fallback){
      try{
        const v = getComputedStyle(document.documentElement).getPropertyValue(name);
        return (v && v.trim()) ? v.trim() : (fallback || "");
      }catch(e){
        return fallback || "";
      }
    }

    function hexToRgb(hex){
      const h = String(hex||"").replace("#","").trim();
      if(h.length !== 6) return null;
      const r = parseInt(h.slice(0,2), 16);
      const g = parseInt(h.slice(2,4), 16);
      const b = parseInt(h.slice(4,6), 16);
      if(Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) return null;
      return {r,g,b};
    }
    function rgbaOf(hex, a){
      const c = hexToRgb(hex);
      if(!c) return `rgba(59,130,246,${a})`;
      return `rgba(${c.r},${c.g},${c.b},${a})`;
    }
    function mixRgb(a, b, t){
      const tt = clamp(t, 0, 1);
      return {
        r: Math.round(a.r + (b.r - a.r) * tt),
        g: Math.round(a.g + (b.g - a.g) * tt),
        b: Math.round(a.b + (b.b - a.b) * tt),
      };
    }
    function rgbStr(c){ return `rgb(${c.r},${c.g},${c.b})`; }
    function shade(hex, amount){
      const base = hexToRgb(hex) || {r:12,g:14,b:26};
      const tgt = amount >= 0 ? {r:255,g:255,b:255} : {r:0,g:0,b:0};
      return rgbStr(mixRgb(base, tgt, Math.abs(amount)));
    }

    function ui(){
      const d = THEME_UI && (THEME_UI[currentTheme] || THEME_UI.dark);
      if(d && typeof d === "object"){
        const pal = Array.isArray(d.colorPalette) ? d.colorPalette : [];
        return {
          bodyBg: String(d.bodyBg || "#0c0e1a"),
          dark: !!d.dark,
          textColor: String(d.textColor || (d.dark ? "#94a3b8" : "#475569")),
          titleColor: String(d.titleColor || (d.dark ? "#e2e8f0" : "#1e293b")),
          colorPalette: pal.slice(0, 8)
        };
      }
      return {bodyBg:"#0c0e1a", dark:true, textColor:"#94a3b8", titleColor:"#e2e8f0", colorPalette:["#4992FF","#7CFFB2","#FDDD60","#FF6E76","#58D9F9","#05C091"]};
    }

    function applyThemeVars(){
      const u = ui();
      const r = document.documentElement.style;
      document.body.style.background = u.bodyBg;
      r.setProperty("--bg", u.bodyBg);
      r.setProperty("--scene-bg", u.bodyBg);
      r.setProperty("--text", u.textColor);
      r.setProperty("--text-title", u.titleColor);
      r.setProperty("--text-muted", u.dark ? "rgba(148,163,184,0.56)" : "rgba(71,85,105,0.56)");
      r.setProperty("--muted", "var(--text-muted)");
      const acc = (u.colorPalette && u.colorPalette.length) ? u.colorPalette[0] : "#3B82F6";
      r.setProperty("--accent", acc);
      r.setProperty("--btn-border", rgbaOf(acc, u.dark ? 0.20 : 0.22));
      r.setProperty("--btn-bg", rgbaOf(acc, u.dark ? 0.08 : 0.06));
      r.setProperty("--btn-hover", rgbaOf(acc, u.dark ? 0.16 : 0.12));
      r.setProperty("--menu-hover", rgbaOf(acc, u.dark ? 0.12 : 0.08));
      r.setProperty("--focus-ring", rgbaOf(acc, 0.56));
      r.setProperty("--focus-ring-soft", rgbaOf(acc, 0.20));
      r.setProperty("--toolbar-group-border", rgbaOf(acc, 0.16));
      r.setProperty("--toolbar-group-primary-border", rgbaOf(acc, 0.36));
      r.setProperty("--toolbar-bg", u.dark ? "rgba(12,14,26,0.92)" : "rgba(255,255,255,0.94)");
      r.setProperty("--toolbar-border", u.dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)");
      r.setProperty("--card-bg", u.dark ? "rgba(16,20,38,0.82)" : "rgba(255,255,255,0.92)");
      r.setProperty("--card-header-bg", u.dark ? "rgba(22,28,52,0.88)" : "rgba(240,243,250,0.94)");
      r.setProperty("--menu-bg", u.dark ? "rgba(14,17,32,0.96)" : "rgba(255,255,255,0.98)");
      r.setProperty("--select-bg", u.dark ? "rgba(12,14,26,0.56)" : "rgba(255,255,255,0.62)");
      const p1 = (u.colorPalette && u.colorPalette.length) ? u.colorPalette[0] : "#3B82F6";
      const p2 = (u.colorPalette && u.colorPalette.length > 1) ? u.colorPalette[1] : "#8B5CF6";
      const p3 = (u.colorPalette && u.colorPalette.length > 2) ? u.colorPalette[2] : "#10B981";
      const bg1 = shade(u.bodyBg, u.dark ? -0.28 : 0.10);
      const bg2 = shade(u.bodyBg, u.dark ? -0.16 : 0.04);
      const bg3 = shade(u.bodyBg, u.dark ? -0.34 : -0.02);
      r.setProperty("--scene-gradient",
        `radial-gradient(ellipse 110% 80% at 8% 0%, ${rgbaOf(p1, u.dark ? 0.18 : 0.12)} 0%, transparent 58%),` +
        `radial-gradient(ellipse 90% 70% at 92% 4%, ${rgbaOf(p2, u.dark ? 0.12 : 0.08)} 0%, transparent 56%),` +
        `radial-gradient(ellipse 120% 90% at 50% 110%, ${rgbaOf(p3, u.dark ? 0.10 : 0.06)} 0%, transparent 62%),` +
        `linear-gradient(168deg, ${bg2} 0%, ${bg1} 52%, ${bg3} 100%)`
      );
      r.setProperty("--scene-texture", "url(\\\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200' viewBox='0 0 200 200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.78' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.7'/%3E%3C/svg%3E\\\")");
      r.setProperty("--scene-texture-opacity", u.dark ? "0.035" : "0.022");
      applyWindowStyle();
    }

    function applyWindowStyle(){
      const r = document.documentElement.style;
      const dk = ui().dark;
      // 亚克力 - 默认模式，类似Windows 11的亚克力材质
      // 特点：背景模糊、噪点纹理、半透明、柔和边缘
      r.setProperty("--card-saturate", "200%");
      r.setProperty("--card-border-color", dk ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.08)");
      r.setProperty("--card-shadow", dk 
        ? "0 2px 8px rgba(0,0,0,0.22),0 8px 24px rgba(0,0,0,0.18),0 16px 48px rgba(0,0,0,0.12)"
        : "0 2px 6px rgba(0,0,0,0.06),0 8px 20px rgba(0,0,0,0.04),0 16px 40px rgba(0,0,0,0.02)");
      r.setProperty("--card-blur", dk ? "24px" : "20px");
      r.setProperty("--card-layer-blur", dk ? "12px" : "10px");
      r.setProperty("--card-layer-opacity", dk ? "0.20" : "0.12");
      r.setProperty("--card-layer-scale", "1.012");
      r.setProperty("--card-overlay-color", dk ? "rgba(25,30,45,0.55)" : "rgba(248,250,255,0.45)");
      r.setProperty("--card-overlay-opacity", dk ? "0.70" : "0.55");
      r.setProperty("--card-overlay-image", dk 
        ? "linear-gradient(180deg,rgba(50,60,90,0.15) 0%,rgba(25,30,45,0.35) 100%)"
        : "linear-gradient(180deg,rgba(255,255,255,0.60) 0%,rgba(248,250,255,0.30) 50%,rgba(240,245,255,0.10) 100%)");
      r.setProperty("--scene-texture-opacity", dk ? "0.040" : "0.028");
      r.setProperty("--card-noise-opacity", dk ? "0.035" : "0.025");

      if(windowStyle === "flat"){
        r.setProperty("--card-saturate","100%");
        r.setProperty("--card-shadow","0 2px 8px rgba(10,18,36,0.14)");
        r.setProperty("--toolbar-bg", dk ? "#1A223F" : "#F5F7FC");
        r.setProperty("--card-bg", dk ? "#253053" : "#FFFFFF");
        r.setProperty("--card-header-bg", dk ? "#2E3B66" : "#EEF3FB");
        r.setProperty("--menu-bg", dk ? "#1F294A" : "#FFFFFF");
        r.setProperty("--scene-texture-opacity", dk ? "0.012" : "0.008");
        r.setProperty("--card-noise-opacity", "0");
        return;
      }
      if(windowStyle === "executive"){
        r.setProperty("--card-saturate","130%");
        r.setProperty("--card-border-color", dk ? "rgba(120,160,220,0.16)" : "rgba(80,110,160,0.18)");
        r.setProperty("--card-layer-blur","6px");
        r.setProperty("--card-layer-opacity","0.14");
        r.setProperty("--card-layer-scale","1.01");
        r.setProperty("--card-overlay-color", dk ? "rgba(80,120,200,0.06)" : "rgba(255,255,255,0.08)");
        r.setProperty("--card-overlay-opacity","0.10");
        r.setProperty("--card-overlay-image","linear-gradient(135deg,rgba(255,255,255,0.10) 0%,rgba(255,255,255,0.02) 40%,transparent 100%)");
        r.setProperty("--card-shadow","0 2px 4px rgba(0,0,0,0.20),0 8px 20px rgba(0,0,0,0.22),0 16px 36px rgba(0,0,0,0.14)");
        r.setProperty("--toolbar-bg", dk ? "rgba(8,12,24,0.86)" : "rgba(250,252,255,0.84)");
        r.setProperty("--card-bg", dk ? "rgba(14,22,44,0.64)" : "rgba(255,255,255,0.70)");
        r.setProperty("--card-header-bg", dk ? "rgba(20,32,60,0.60)" : "rgba(248,250,255,0.68)");
        r.setProperty("--menu-bg", dk ? "rgba(10,16,34,0.92)" : "rgba(255,255,255,0.95)");
        r.setProperty("--scene-texture-opacity", dk ? "0.022" : "0.016");
        r.setProperty("--card-noise-opacity", "0");
        return;
      }
      if(windowStyle === "opaque"){
        r.setProperty("--toolbar-bg", dk ? "#1B2342" : "#F4F7FC");
        r.setProperty("--card-bg", dk ? "#232D4F" : "#FFFFFF");
        r.setProperty("--card-header-bg", dk ? "#2E3A66" : "#EDF2FA");
        r.setProperty("--menu-bg", dk ? "#1F294B" : "#FFFFFF");
        r.setProperty("--scene-texture-opacity", dk ? "0.024" : "0.018");
        r.setProperty("--card-noise-opacity", "0");
        r.setProperty("--toolbar-border", dk ? "rgba(255,255,255,0.10)" : "rgba(26,39,72,0.12)");
        return;
      }
      if(windowStyle === "transparent"){
        r.setProperty("--card-saturate","105%");
        r.setProperty("--card-border-color", dk ? "rgba(165,190,255,0.20)" : "rgba(70,100,150,0.16)");
        r.setProperty("--toolbar-bg", dk ? "rgba(18,24,52,0.16)" : "rgba(255,255,255,0.24)");
        r.setProperty("--card-bg", dk ? "rgba(36,50,94,0.14)" : "rgba(255,255,255,0.28)");
        r.setProperty("--card-header-bg", dk ? "rgba(58,76,126,0.16)" : "rgba(242,245,250,0.24)");
        r.setProperty("--menu-bg", dk ? "rgba(28,34,62,0.26)" : "rgba(255,255,255,0.30)");
        r.setProperty("--scene-texture-opacity", dk ? "0.018" : "0.014");
        r.setProperty("--card-noise-opacity", "0");
        return;
      }
      if(windowStyle === "frosted"){
        // 磨砂玻璃 - 柔和的毛玻璃效果，类似磨砂窗户
        r.setProperty("--card-saturate","88%");
        r.setProperty("--card-border-color","rgba(180,190,200,0.35)");
        r.setProperty("--card-shadow","0 4px 16px rgba(0,0,0,0.08),0 1px 3px rgba(0,0,0,0.04)");
        r.setProperty("--card-blur","20px");
        r.setProperty("--card-layer-blur","10px");
        r.setProperty("--card-layer-opacity","0.25");
        r.setProperty("--card-layer-scale","1.02");
        r.setProperty("--card-overlay-color","rgba(255,255,255,0.28)");
        r.setProperty("--card-overlay-opacity","0.65");
        r.setProperty("--card-overlay-image","linear-gradient(180deg,rgba(255,255,255,0.40) 0%,rgba(255,255,255,0.15) 50%,rgba(255,255,255,0.05) 100%)");
        r.setProperty("--toolbar-bg","rgba(245,248,252,0.72)");
        r.setProperty("--card-bg","rgba(250,253,255,0.38)");
        r.setProperty("--card-header-bg","rgba(255,255,255,0.35)");
        r.setProperty("--menu-bg","rgba(248,251,255,0.90)");
        r.setProperty("--text","#2D3748");
        r.setProperty("--text-title","#1A202C");
        r.setProperty("--scene-texture-opacity","0.020");
        r.setProperty("--card-noise-opacity","0.020");
        return;
      }
      if(windowStyle === "glass"){
        // 水晶玻璃 - 清澈透明，高光折射效果
        r.setProperty("--card-saturate","115%");
        r.setProperty("--card-border-color","rgba(255,255,255,0.65)");
        r.setProperty("--card-shadow","0 2px 12px rgba(100,150,200,0.12),0 8px 32px rgba(100,150,200,0.08),inset 0 1px 0 rgba(255,255,255,0.80)");
        r.setProperty("--card-blur","6px");
        r.setProperty("--card-layer-blur","3px");
        r.setProperty("--card-layer-opacity","0.08");
        r.setProperty("--card-layer-scale","1.003");
        r.setProperty("--card-overlay-color","rgba(255,255,255,0.45)");
        r.setProperty("--card-overlay-opacity","0.35");
        r.setProperty("--card-overlay-image","linear-gradient(135deg,rgba(255,255,255,0.70) 0%,rgba(255,255,255,0.25) 30%,rgba(200,220,255,0.15) 60%,rgba(255,255,255,0.10) 100%)");
        r.setProperty("--toolbar-bg","rgba(255,255,255,0.58)");
        r.setProperty("--card-bg","rgba(255,255,255,0.48)");
        r.setProperty("--card-header-bg","rgba(255,255,255,0.55)");
        r.setProperty("--menu-bg","rgba(255,255,255,0.82)");
        r.setProperty("--text","#1e3a5f");
        r.setProperty("--text-title","#0f2942");
        r.setProperty("--scene-texture-opacity","0.008");
        r.setProperty("--card-noise-opacity","0.010");
        return;
      }
      if(windowStyle === "glass-dark"){
        // 暗夜玻璃 - 深邃神秘的暗色玻璃，带有微妙的反光
        r.setProperty("--card-saturate","90%");
        r.setProperty("--card-border-color","rgba(255,255,255,0.08)");
        r.setProperty("--card-shadow","0 8px 40px rgba(0,0,0,0.50),0 2px 10px rgba(0,0,0,0.30),inset 0 1px 0 rgba(255,255,255,0.05)");
        r.setProperty("--card-blur","24px");
        r.setProperty("--card-layer-blur","12px");
        r.setProperty("--card-layer-opacity","0.30");
        r.setProperty("--card-layer-scale","1.02");
        r.setProperty("--card-overlay-color","rgba(20,25,40,0.70)");
        r.setProperty("--card-overlay-opacity","0.75");
        r.setProperty("--card-overlay-image","linear-gradient(180deg,rgba(60,70,100,0.25) 0%,rgba(30,35,55,0.50) 50%,rgba(15,20,35,0.60) 100%)");
        r.setProperty("--toolbar-bg","rgba(15,18,30,0.75)");
        r.setProperty("--card-bg","rgba(20,25,45,0.50)");
        r.setProperty("--card-header-bg","rgba(30,35,60,0.45)");
        r.setProperty("--menu-bg","rgba(15,18,30,0.88)");
        r.setProperty("--text","#c8cad8");
        r.setProperty("--text-title","#e8eaf6");
        r.setProperty("--scene-texture-opacity","0.030");
        r.setProperty("--card-noise-opacity","0.025");
        return;
      }
      if(windowStyle === "neon"){
        // 霓虹光效 - 发光边框效果
        r.setProperty("--card-saturate","120%");
        r.setProperty("--card-border-color","rgba(100,200,255,0.60)");
        r.setProperty("--card-shadow","0 0 20px rgba(100,200,255,0.30),0 0 40px rgba(100,200,255,0.15),0 4px 12px rgba(0,0,0,0.20)");
        r.setProperty("--card-blur","12px");
        r.setProperty("--card-layer-blur","6px");
        r.setProperty("--card-layer-opacity","0.20");
        r.setProperty("--card-layer-scale","1.01");
        r.setProperty("--card-overlay-color","rgba(100,200,255,0.10)");
        r.setProperty("--card-overlay-opacity","0.50");
        r.setProperty("--card-overlay-image","linear-gradient(180deg,rgba(100,200,255,0.15) 0%,rgba(50,100,200,0.05) 100%)");
        r.setProperty("--toolbar-bg","rgba(10,20,40,0.80)");
        r.setProperty("--card-bg","rgba(15,25,50,0.65)");
        r.setProperty("--card-header-bg","rgba(20,35,70,0.55)");
        r.setProperty("--menu-bg","rgba(10,20,40,0.90)");
        r.setProperty("--text","#a0d8ff");
        r.setProperty("--text-title","#64c8ff");
        r.setProperty("--scene-texture-opacity","0.030");
        r.setProperty("--card-noise-opacity","0.020");
        return;
      }
      if(windowStyle === "cyber"){
        // 赛博朋克 - 科技感效果
        r.setProperty("--card-saturate","130%");
        r.setProperty("--card-border-color","rgba(255,50,150,0.50)");
        r.setProperty("--card-shadow","0 0 15px rgba(255,50,150,0.25),0 0 30px rgba(50,200,255,0.15),0 4px 15px rgba(0,0,0,0.30)");
        r.setProperty("--card-blur","10px");
        r.setProperty("--card-layer-blur","5px");
        r.setProperty("--card-layer-opacity","0.22");
        r.setProperty("--card-layer-scale","1.008");
        r.setProperty("--card-overlay-color","rgba(255,50,150,0.08)");
        r.setProperty("--card-overlay-opacity","0.55");
        r.setProperty("--card-overlay-image","linear-gradient(135deg,rgba(255,50,150,0.12) 0%,rgba(50,200,255,0.08) 50%,rgba(100,50,200,0.12) 100%)");
        r.setProperty("--toolbar-bg","rgba(20,10,30,0.85)");
        r.setProperty("--card-bg","rgba(30,15,40,0.70)");
        r.setProperty("--card-header-bg","rgba(40,20,55,0.60)");
        r.setProperty("--menu-bg","rgba(20,10,30,0.92)");
        r.setProperty("--text","#ff99cc");
        r.setProperty("--text-title","#ff66aa");
        r.setProperty("--scene-texture-opacity","0.035");
        r.setProperty("--card-noise-opacity","0.025");
        return;
      }
      if(windowStyle === "paper"){
        // 纸质质感 - 温暖的纸张纹理，柔和的阴影
        r.setProperty("--card-saturate","98%");
        r.setProperty("--card-border-color","rgba(180,170,155,0.45)");
        r.setProperty("--card-shadow","0 1px 3px rgba(0,0,0,0.06),0 4px 12px rgba(0,0,0,0.04),0 8px 24px rgba(0,0,0,0.02)");
        r.setProperty("--card-blur","0px");
        r.setProperty("--card-layer-blur","0px");
        r.setProperty("--card-layer-opacity","0.02");
        r.setProperty("--card-layer-scale","1.0");
        r.setProperty("--card-overlay-color","rgba(252,250,245,0.96)");
        r.setProperty("--card-overlay-opacity","0.95");
        r.setProperty("--card-overlay-image","linear-gradient(180deg,rgba(255,254,250,0.98) 0%,rgba(250,248,242,0.96) 100%)");
        r.setProperty("--toolbar-bg","rgba(248,246,240,0.98)");
        r.setProperty("--card-bg","rgba(255,253,248,0.96)");
        r.setProperty("--card-header-bg","rgba(252,250,245,0.98)");
        r.setProperty("--menu-bg","rgba(255,254,250,0.99)");
        r.setProperty("--text","#3d3d3b");
        r.setProperty("--text-title","#1f1f1d");
        r.setProperty("--scene-texture-opacity","0.065");
        r.setProperty("--card-noise-opacity","0.050");
        return;
      }
    }

    function applyChartsDemoStyle(opt, chartType){
      if(!opt || typeof opt !== "object") return opt;
      const u = ui();
      const muted = cssVar("--text-muted", u.dark ? "rgba(148,163,184,0.56)" : "rgba(71,85,105,0.56)");
      opt.backgroundColor = "transparent";
      if(!opt.textStyle) opt.textStyle = {};
      if(opt.textStyle.color === undefined) opt.textStyle.color = u.textColor;
      if(opt.title !== undefined){
        if(opt.title === null) opt.title = {};
        if(opt.title && typeof opt.title === "object"){
          opt.title.textStyle = opt.title.textStyle || {};
          if(opt.title.textStyle.color === undefined) opt.title.textStyle.color = u.titleColor;
          if(opt.title.textStyle.fontSize === undefined) opt.title.textStyle.fontSize = 12;
          if(opt.title.left === undefined) opt.title.left = "center";
          if(opt.title.top === undefined) opt.title.top = 10;
        }
      }
      opt.tooltip = opt.tooltip || {};
      if(opt.tooltip && typeof opt.tooltip === "object"){
        if(opt.tooltip.confine === undefined) opt.tooltip.confine = true;
        if(opt.tooltip.backgroundColor === undefined) opt.tooltip.backgroundColor = cssVar("--menu-bg", "rgba(14,17,32,0.92)");
        if(opt.tooltip.borderColor === undefined) opt.tooltip.borderColor = "rgba(255,255,255,0.08)";
        if(opt.tooltip.borderWidth === undefined) opt.tooltip.borderWidth = 1;
        opt.tooltip.textStyle = opt.tooltip.textStyle || {};
        if(opt.tooltip.textStyle.color === undefined) opt.tooltip.textStyle.color = u.titleColor;
        if(opt.tooltip.textStyle.fontSize === undefined) opt.tooltip.textStyle.fontSize = 11;
      }
      if(!opt.color && u.colorPalette && u.colorPalette.length){
        opt.color = u.colorPalette.slice(0);
      }
      const axisLine = {lineStyle:{color:"rgba(148,163,184,0.24)"}};
      const axisTick = {show:false};
      const axisLabel = {color:u.textColor, fontSize: 10};
      const splitLine = {show:true, lineStyle:{color:"rgba(148,163,184,0.12)", type:"dashed"}};
      const splitArea = {show:false};
      function ensureAxis(ax){
        if(!ax || typeof ax !== "object") return;
        ax.axisLine = ax.axisLine || axisLine;
        ax.axisTick = ax.axisTick || axisTick;
        ax.axisLabel = ax.axisLabel || axisLabel;
        if(ax.splitLine === undefined) ax.splitLine = splitLine;
        if(ax.splitArea === undefined) ax.splitArea = splitArea;
        if(ax.nameTextStyle === undefined) ax.nameTextStyle = {color:muted, fontSize: 10};
      }
      if(opt.xAxis){
        if(Array.isArray(opt.xAxis)) opt.xAxis.forEach(ensureAxis);
        else ensureAxis(opt.xAxis);
      }
      if(opt.yAxis){
        if(Array.isArray(opt.yAxis)) opt.yAxis.forEach(ensureAxis);
        else ensureAxis(opt.yAxis);
      }
      if(opt.legend){
        const lg = opt.legend;
        if(typeof lg === "object"){
          lg.textStyle = lg.textStyle || {};
          if(lg.textStyle.color === undefined) lg.textStyle.color = u.textColor;
          if(lg.textStyle.fontSize === undefined) lg.textStyle.fontSize = 11;
          if(lg.top === undefined) lg.top = 30;
        }
      }
      if(opt.grid && typeof opt.grid === "object"){
        if(opt.grid.left === undefined) opt.grid.left = 46;
        if(opt.grid.right === undefined) opt.grid.right = 18;
        if(opt.grid.top === undefined) opt.grid.top = 58;
        if(opt.grid.bottom === undefined) opt.grid.bottom = 36;
      }
      if(Array.isArray(opt.series)){
        opt.series.forEach(function(s){
          if(!s || typeof s !== "object") return;
          if(s.type === "line" && s.smooth === undefined) s.smooth = true;
          if(s.type === "pie"){
            s.label = s.label || {};
            if(s.label.color === undefined) s.label.color = u.textColor;
            s.labelLine = s.labelLine || {};
            if(s.labelLine.lineStyle === undefined) s.labelLine.lineStyle = {color:"rgba(148,163,184,0.30)"};
          }
          if(s.type === "radar"){
            s.areaStyle = s.areaStyle || {opacity:0.15};
            s.lineStyle = s.lineStyle || {width:2};
          }
          if(s.type === "graph"){
            s.label = s.label || {show:true, color:u.textColor};
          }
        });
      }
      return opt;
    }

    function stabilizeOption(opt, chartType){
      return applyChartsDemoStyle(opt, chartType);
    }

    function applyPageWatermark(jobId){
      if(!wmCanvas) return;
      if(!watermarkOn){
        try{ wmCanvas.style.display = "none"; }catch(e){}
        return;
      }
      try{ wmCanvas.style.display = "block"; }catch(e){}
      if(window.__bpWmJobId !== jobId) return;
        const dpr = window.devicePixelRatio || 1;
        const w = Math.max(1, window.innerWidth || document.documentElement.clientWidth || 1);
        const h = Math.max(1, window.innerHeight || document.documentElement.clientHeight || 1);
        try{
          wmCanvas.style.width = w + "px";
          wmCanvas.style.height = h + "px";
          const pw = Math.floor(w * dpr);
          const ph = Math.floor(h * dpr);
          if(wmCanvas.__bpWmW !== pw || wmCanvas.__bpWmH !== ph){
            wmCanvas.width = pw;
            wmCanvas.height = ph;
            wmCanvas.__bpWmW = pw;
            wmCanvas.__bpWmH = ph;
          }
        }catch(e){}
        const ctx = wmCanvas.getContext("2d");
        if(!ctx) return;
        try{
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, w, h);
        }catch(e){}

        const text = String(watermarkText || "").trim() || "Bird";
        const fs = clamp(Number(watermarkFontSize || 22), 10, 64);
        const wmFill = (() => {
          try{
            const u = ui();
            return u && u.dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.12)";
          }catch(e){
            return "rgba(255,255,255,0.08)";
          }
        })();
        const stepX = Math.max(140, Math.round(fs * 7.2));
        const stepY = Math.max(90, Math.round(fs * 4.2));
        const angle = -Math.PI / 6;
        try{
          const key = `${dpr}|${text}|${fs}|${stepX}|${stepY}|${angle}`;
          let cache = window.__bpWmPatternCache;
          if(!cache || cache.key !== key || !cache.tile){
            const tile = document.createElement("canvas");
            tile.width = Math.max(1, Math.floor(stepX * dpr));
            tile.height = Math.max(1, Math.floor(stepY * dpr));
            const tctx = tile.getContext("2d");
            if(tctx){
              try{
                tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                tctx.clearRect(0, 0, stepX, stepY);
                tctx.save();
                tctx.translate(stepX / 2, stepY / 2);
                tctx.rotate(angle);
                tctx.font = `700 ${fs}px sans-serif`;
                tctx.fillStyle = wmFill;
                tctx.textAlign = "center";
                tctx.textBaseline = "middle";
                tctx.fillText(text, 0, 0);
                tctx.restore();
              }catch(e){}
            }
            cache = {key, tile};
            window.__bpWmPatternCache = cache;
          }
          if(window.__bpWmJobId !== jobId) return;
          const pat = ctx.createPattern(cache.tile, "repeat");
          if(!pat) return;
          ctx.save();
          ctx.fillStyle = pat;
          ctx.fillRect(0, 0, w, h);
          ctx.restore();
        }catch(e){}
    }

    function applyVisualTheme(){
      applyThemeVars();
      if(gridInteracting){
        try{ drawDashGrid(); }catch(e){}
      }
      try{ schedulePageWatermark(); }catch(e){}
    }

    function rebuildChartInstance(chartId){
      const prev = chartViews.get(chartId);
      if(prev){
        try{ prev.dispose(); }catch(e){}
      }
      const node = document.getElementById("c_" + chartId);
      if(!node) return;
      const inst = echarts.init(node, currentTheme);
      chartViews.set(chartId, inst);
      attachChartWheelZoom(chartId, node);
    }

    async function switchTheme(theme){
      currentTheme = String(theme || currentTheme || "dark");
      applyVisualTheme();
      for(const cid of chartsById.keys()){
        rebuildChartInstance(cid);
      }
      try{ requestRerenderAllCharts("主题重绘"); }catch(e){}
    }

    const chartWheelScale = new Map();
    function chartScaleOf(chartId){
      const v = chartWheelScale.get(chartId);
      return (typeof v === "number" && isFinite(v)) ? v : 1;
    }
    function setChartScale(chartId, node, nextScale, originX, originY){
      const s = clamp(nextScale, 0.5, 3.0);
      chartWheelScale.set(chartId, s);
      if(node){
        node.style.transformOrigin = `${Math.round(originX)}px ${Math.round(originY)}px`;
        node.style.transform = `scale(${s})`;
      }
    }
    function attachChartWheelZoom(chartId, node){
      if(!node) return;
      if(node.__bpWheelBound) return;
      node.__bpWheelBound = true;
      node.addEventListener("wheel", (ev) => {
        if(!editMode) return;
        if(ev.ctrlKey){
          ev.preventDefault();
          ev.stopPropagation();
          const rect = node.getBoundingClientRect();
          const ox = (ev.clientX - rect.left);
          const oy = (ev.clientY - rect.top);
          const dy = ev.deltaY || 0;
          const factor = dy < 0 ? 1.08 : 0.92;
          setChartScale(chartId, node, chartScaleOf(chartId) * factor, ox, oy);
          const inst = chartViews.get(chartId);
          try{ if(inst) inst.resize(); }catch(e){}
          return;
        }
        ev.preventDefault();
        ev.stopPropagation();
      }, {passive:false, capture:true});
    }

    const gridCanvas = $("gridGuideCanvas");
    const ghost = $("ghost");
    let gridInteracting = false;

    function drawDashGrid(){
      if(!gridCanvas) return;
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(1, desk.clientWidth);
      const h = Math.max(1, desk.clientHeight);
      gridCanvas.style.width = w + "px";
      gridCanvas.style.height = h + "px";
      gridCanvas.width = Math.floor(w * dpr);
      gridCanvas.height = Math.floor(h * dpr);
      const ctx = gridCanvas.getContext("2d");
      if(!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const g = Number(getComputedStyle(document.documentElement).getPropertyValue("--grid").replace("px","")) || 20;
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(126,196,255,0.38)";
      ctx.setLineDash([6, 6]);
      for(let x=0; x<=w; x+=g){
        const xx = Math.round(x) + 0.5;
        ctx.beginPath();
        ctx.moveTo(xx, 0);
        ctx.lineTo(xx, h);
        ctx.stroke();
      }
      for(let y=0; y<=h; y+=g){
        const yy = Math.round(y) + 0.5;
        ctx.beginPath();
        ctx.moveTo(0, yy);
        ctx.lineTo(w, yy);
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    function setDashGridVisible(show){
      const v = !!(show && virtualGridOn);
      desk.classList.toggle("show-dash-grid", v);
      if(v) drawDashGrid();
    }

    function showGhost(x, y, w, h){
      if(!ghost) return;
      ghost.classList.add("show");
      ghost.style.left = x + "px";
      ghost.style.top = y + "px";
      ghost.style.width = w + "px";
      ghost.style.height = h + "px";
    }

    function hideGhost(){
      if(!ghost) return;
      ghost.classList.remove("show");
    }

    function beginGridInteract(el){
      gridInteracting = true;
      setDashGridVisible(true);
      try{
        const x = parseFloat(el.style.left || "0");
        const y = parseFloat(el.style.top || "0");
        const w = parseFloat(el.style.width || "520");
        const h = parseFloat(el.style.height || "360");
        showGhost(x, y, w, h);
      }catch(e){}
    }

    function endGridInteract(){
      gridInteracting = false;
      setDashGridVisible(false);
      hideGhost();
    }

    let layoutSaveTimer = null;
    function scheduleLayoutSave(chartId, el){
      if(layoutSaveTimer){ clearTimeout(layoutSaveTimer); }
      layoutSaveTimer = setTimeout(async () => {
        const r = deskRect();
        const x = parseFloat(el.style.left || "0");
        const y = parseFloat(el.style.top || "0");
        const w = parseFloat(el.style.width || "520");
        const h = parseFloat(el.style.height || "360");
        const z = parseInt(el.style.zIndex || "1");
        const locked = String(el.getAttribute("data-lock") || "") === "1";
        await bridgeCall(bridge, "update_layout", {chart_id: chartId, layout:{x,y,w,h,z,locked}}, token);
      }, 320);
    }

    let layoutSaveAllTimer = null;
    function scheduleAllLayoutSave(){
      if(layoutSaveAllTimer){ clearTimeout(layoutSaveAllTimer); }
      layoutSaveAllTimer = setTimeout(async () => {
        if(!bridge) return;
        const r = deskRect();
        const wins = Array.from(document.querySelectorAll("#desk .win"));
        for(const el of wins){
          try{
            const chartId = String(el.getAttribute("data-id") || "");
            if(!chartId) continue;
            const x = parseFloat(el.style.left || "0");
            const y = parseFloat(el.style.top || "0");
            const w = parseFloat(el.style.width || "520");
            const h = parseFloat(el.style.height || "360");
            const z = parseInt(el.style.zIndex || "1");
            const locked = String(el.getAttribute("data-lock") || "") === "1";
            const nx = clamp(x, 0, Math.max(0, r.width - w));
            const ny = clamp(y, 0, Math.max(0, r.height - h));
            if(nx !== x) el.style.left = snap(nx) + "px";
            if(ny !== y) el.style.top = snap(ny) + "px";
            await bridgeCall(bridge, "update_layout", {chart_id: chartId, layout:{x:nx,y:ny,w,h,z,locked}}, token);
          }catch(e){}
        }
      }, 320);
    }

    function focusWin(el){
      zTop += 1;
      el.style.zIndex = String(zTop);
      try{
        activeChartId = String(el.getAttribute("data-id") || "") || null;
      }catch(e){
        activeChartId = null;
      }
    }

    function winRects(){
      const out = [];
      document.querySelectorAll("#desk .win").forEach(el => {
        try{
          const x = parseFloat(el.style.left || "0");
          const y = parseFloat(el.style.top || "0");
          const w = parseFloat(el.style.width || "0");
          const h = parseFloat(el.style.height || "0");
          if(isFinite(x) && isFinite(y) && isFinite(w) && isFinite(h)){
            out.push({x,y,w,h});
          }
        }catch(e){}
      });
      return out;
    }
    function rectHit(a, b){
      return !(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y);
    }
    function hitLockedWithGap(id, cand){
      try{
        const gap = snap(gridSize());
        const wins = Array.from(document.querySelectorAll("#desk .win[data-lock='1']"));
        for(const el of wins){
          try{
            const cid = String(el.getAttribute("data-id") || "");
            if(!cid || cid === String(id || "")) continue;
            const bx = parseFloat(el.style.left || "0");
            const by = parseFloat(el.style.top || "0");
            const bw = parseFloat(el.style.width || "0");
            const bh = parseFloat(el.style.height || "0");
            const b = {x:bx-gap, y:by-gap, w:bw+2*gap, h:bh+2*gap};
            if(rectHit(cand, b)) return true;
          }catch(e){}
        }
      }catch(e){}
      return false;
    }
    function findFreeSpot(w, h){
      const r = deskRect();
      const gap = snap(12);
      const rects = winRects();
      const step = snap(20);
      const maxX = Math.max(0, r.width - w);
      const maxY = Math.max(0, r.height - h);
      for(let y = 0; y <= maxY; y += step){
        for(let x = 0; x <= maxX; x += step){
          const cand = {x:x+gap, y:y+gap, w:w-gap*2, h:h-gap*2};
          let ok = true;
          for(const ex of rects){
            if(rectHit(cand, ex)){ ok = false; break; }
          }
          if(ok){
            return {x, y};
          }
        }
      }
      // 没有找到空闲位置，返回底部新位置
      let bottomY = 0;
      for(const ex of rects){
        const exBottom = (ex.y || 0) + (ex.h || 0);
        if(exBottom > bottomY) bottomY = exBottom;
      }
      return {x: gap, y: bottomY + gap};
    }

    function gridSize(){
      try{
        const v = getComputedStyle(document.documentElement).getPropertyValue("--grid");
        const n = parseFloat(String(v || "").replace("px","").trim());
        return (typeof n === "number" && isFinite(n) && n > 0) ? n : 20;
      }catch(e){
        return 20;
      }
    }

    let arrangeRaf = 0;
    let arrangePendingLockedId = null;
    let arrangeLastTs = 0;
    function scheduleAutoArrange(lockedId){
      const now = (window.performance && typeof performance.now === "function") ? performance.now() : Date.now();
      if(now - arrangeLastTs < 70) return;
      arrangeLastTs = now;
      arrangePendingLockedId = String(lockedId || "") || null;
      if(arrangeRaf) return;
      arrangeRaf = requestAnimationFrame(() => {
        arrangeRaf = 0;
        autoArrangeWins(arrangePendingLockedId, false);
      });
    }

    function autoArrangeWins(lockedId, saveNow){
      const r = deskRect();
      const g = snap(gridSize());
      const wins = Array.from(document.querySelectorAll("#desk .win"));
      const lockId = String(lockedId || "");
      let lockedEl = null;
      if(lockId){
        try{
          lockedEl = document.querySelector('.win[data-id="'+lockId+'"]');
        }catch(e){
          lockedEl = null;
        }
      }
      const fixedIds = new Set();
      if(lockId) fixedIds.add(lockId);
      try{
        for(const el of wins){
          try{
            const id = String(el.getAttribute("data-id") || "");
            if(!id) continue;
            if(String(el.getAttribute("data-lock") || "") === "1"){
              fixedIds.add(id);
            }
          }catch(e){}
        }
      }catch(e){}
      if(lockedEl && lockId){
        try{
          if(String(lockedEl.getAttribute("data-lock") || "") !== "1"){
            const a = {
              x: parseFloat(lockedEl.style.left || "0"),
              y: parseFloat(lockedEl.style.top || "0"),
              w: parseFloat(lockedEl.style.width || "0"),
              h: parseFloat(lockedEl.style.height || "0"),
            };
            let hitLocked = false;
            for(const el of wins){
              try{
                if(el === lockedEl) continue;
                if(String(el.getAttribute("data-lock") || "") !== "1") continue;
                const b = {
                  x: parseFloat(el.style.left || "0"),
                  y: parseFloat(el.style.top || "0"),
                  w: parseFloat(el.style.width || "0"),
                  h: parseFloat(el.style.height || "0"),
                };
                if(rectHit(a, b)){ hitLocked = true; break; }
              }catch(e){}
            }
            if(hitLocked){
              fixedIds.delete(lockId);
              lockedEl = null;
            }
          }
        }catch(e){}
      }
      wins.sort((a,b) => {
        const ao = parseInt(a.getAttribute("data-ord") || "0");
        const bo = parseInt(b.getAttribute("data-ord") || "0");
        if(ao !== bo) return ao - bo;
        const ay = parseFloat(a.style.top || "0");
        const by = parseFloat(b.style.top || "0");
        if(ay !== by) return ay - by;
        const ax = parseFloat(a.style.left || "0");
        const bx = parseFloat(b.style.left || "0");
        return ax - bx;
      });
      const placed = [];
      const pad = Math.max(4, g / 2);
      const asGapRect = (x, y, w, h) => ({x:x-pad, y:y-pad, w:w+2*pad, h:h+2*pad});
      if(lockedEl){
        try{
          const lx = parseFloat(lockedEl.style.left || "0");
          const ly = parseFloat(lockedEl.style.top || "0");
          const lw = parseFloat(lockedEl.style.width || "520");
          const lh = parseFloat(lockedEl.style.height || "360");
          placed.push(asGapRect(lx, ly, lw, lh));
        }catch(e){}
      }
      try{
        for(const el of wins){
          const id = String(el.getAttribute("data-id") || "");
          if(!id || !fixedIds.has(id)) continue;
          if(lockedEl && el === lockedEl) continue;
          try{
            const lx = parseFloat(el.style.left || "0");
            const ly = parseFloat(el.style.top || "0");
            const lw = parseFloat(el.style.width || "520");
            const lh = parseFloat(el.style.height || "360");
            placed.push(asGapRect(lx, ly, lw, lh));
          }catch(e){}
        }
      }catch(e){}
      let x = g;
      let y = g;
      let rowH = 0;
      const maxW = Math.max(0, r.width - g);
      const maxH = Math.max(0, r.height - g);
      for(const el of wins){
        try{
          const id = String(el.getAttribute("data-id") || "");
          if(id && fixedIds.has(id)) continue;
        }catch(e){}
        if(lockedEl && el === lockedEl) continue;
        // 最小尺寸：8x4 个格子，使用 gridSize() 获取当前格子大小
        const minW = 8 * gridSize();
        const minH = 4 * gridSize();
        const w0 = clamp(parseFloat(el.style.width || "520"), minW, Math.max(minW, r.width - g*2));
        const h0 = clamp(parseFloat(el.style.height || "360"), minH, Math.max(minH, r.height - g*2));
        let guard = 0;
        while(guard++ < 2000){
          if(x + w0 > maxW){
            x = g;
            y = y + rowH + g;
            rowH = 0;
          }
          const nx = clamp(x, 0, Math.max(0, r.width - w0));
          const ny = clamp(y, 0, Math.max(0, r.height - h0));
          const cand = asGapRect(nx, ny, w0, h0);
          let ok = true;
          for(const ex of placed){
            if(rectHit(cand, ex)){ ok = false; break; }
          }
          if(ok){
            el.style.left = snap(nx) + "px";
            el.style.top = snap(ny) + "px";
            el.style.width = snap(w0) + "px";
            el.style.height = snap(h0) + "px";
            placed.push(cand);
            x = x + w0 + g;
            rowH = Math.max(rowH, h0);
            if(ny >= maxH) guard = 9999;
            break;
          }else{
            x = x + g;
          }
        }
      }
      if(saveNow !== false){
        scheduleAllLayoutSave();
      }
    }

    function createWin(chartObj){
      const cid = chartObj.chart_id;
      if(document.querySelector('.win[data-id="'+cid+'"]')) return;

      const el = document.createElement("div");
      el.className = "win";
      el.setAttribute("data-id", cid);
      try{
        let ord = chartOrder.get(cid);
        if(!(typeof ord === "number" && isFinite(ord))){
          ord = orderTop + 1;
          orderTop = ord;
          chartOrder.set(cid, ord);
        }
        el.setAttribute("data-ord", String(ord));
      }catch(e){}
      el.innerHTML = `
        <div class="win-tools">
          <button class="tool lock" data-act="lock">锁定</button>
          <button class="tool" data-act="edit">编辑</button>
          <button class="tool danger" data-act="delete">删除</button>
        </div>
        <div class="refreshLamp"></div>
        <div class="win-noise"></div>
        <div class="win-body"><div class="chart" id="c_${cid}"></div></div>
        <div class="drag-zone" title="拖拽移动"></div>
        <div class="resizer" title="拖拽缩放"></div>
      `;

      const lay = chartObj.layout || {};
      try{
        if(lay.locked === true || String(lay.locked || "") === "1"){
          el.setAttribute("data-lock", "1");
        }else{
          el.setAttribute("data-lock", "0");
        }
      }catch(e){
        el.setAttribute("data-lock", "0");
      }
      // 最小尺寸：8x4 个格子，使用 gridSize() 获取当前格子大小
      const minW = 8 * gridSize();
      const minH = 4 * gridSize();
      // 宽度和高度不再限制在当前窗口内，允许超出边界
      const w = Math.max(minW, Number(lay.w || 520));
      const h = Math.max(minH, Number(lay.h || 360));
      const hasX = (lay.x !== undefined && lay.x !== null);
      const hasY = (lay.y !== undefined && lay.y !== null);
      let x = hasX ? Number(lay.x) : NaN;
      let y = hasY ? Number(lay.y) : NaN;
      if(!(isFinite(x) && isFinite(y))){
        const spot = findFreeSpot(w, h);
        if(spot){
          x = spot.x;
          y = spot.y;
        }else{
          x = 20 + (chartsById.size*18)%240;
          y = 20 + (chartsById.size*14)%180;
        }
      }
      // 位置不再限制在当前窗口内，允许超出边界
      // 但如果位置无效，则使用计算出的位置
      const z = Number(lay.z || (zTop+=1));
      el.style.left = snap(x) + "px";
      el.style.top = snap(y) + "px";
      el.style.width = snap(w) + "px";
      el.style.height = snap(h) + "px";
      el.style.zIndex = String(z);
      
      // 扩展desk区域以容纳新图表
      expandDeskIfNeeded();

      el.addEventListener("pointerdown", () => focusWin(el));
      try{
        setChartHovered(cid, false);
        const onEnter = () => {
          setChartHovered(cid, true);
          if(pauseRefreshOnMouseLeave()){
            try{ renderChart(cid); }catch(e){}
            try{ startHoverRefresh(cid); }catch(e){}
          }
        };
        const onLeave = () => {
          setChartHovered(cid, false);
          if(pauseRefreshOnMouseLeave()){
            try{ bumpChartActive(cid, GRACE_REFRESH_MS); }catch(e){}
          }else{
            try{ stopHoverRefresh(cid); }catch(e){}
          }
        };
        el.addEventListener("pointerenter", onEnter);
        el.addEventListener("pointerleave", onLeave);
        el.addEventListener("mouseenter", onEnter);
        el.addEventListener("mouseleave", onLeave);
        el.addEventListener("mouseover", onEnter);
        el.addEventListener("mouseout", (ev) => {
          try{
            const to = ev && ev.relatedTarget;
            if(to && el.contains(to)) return;
          }catch(e){}
          onLeave();
        });
      }catch(e){}

      try{
        const tools = el.querySelector(".win-tools");
        if(tools){
          try{
            const lockBtn = tools.querySelector('[data-act="lock"]');
            if(lockBtn){
              const locked = String(el.getAttribute("data-lock") || "") === "1";
              lockBtn.textContent = locked ? "已锁" : "锁定";
            }
          }catch(e){}
          tools.addEventListener("click", async (ev) => {
            const t = ev && ev.target;
            const act = t && t.getAttribute ? t.getAttribute("data-act") : "";
            if(act === "lock"){
              const locked = String(el.getAttribute("data-lock") || "") === "1";
              const next = !locked;
              el.setAttribute("data-lock", next ? "1" : "0");
              try{ t.textContent = next ? "已锁" : "锁定"; }catch(e){}
              try{ scheduleLayoutSave(cid, el); }catch(e){}
              // 锁定图表时不自动触发重排，保持其他图表位置不变
              // 只有在解锁时才可能需要重排，但这里也不自动触发，让用户手动控制
              try{ setStatus(next ? "已锁定" : "已解锁"); }catch(e){}
              return;
            }
            if(act === "edit"){
              try{ openEditChart(cid); }catch(e){}
              return;
            }
            if(act === "delete"){
              try{
                setLoading(true);
                const resp = await bridgeCall(bridge, "remove_chart", {chart_id: cid}, token);
                setLoading(false);
                if(resp.ok){
                  chartsById.delete(cid);
                  destroyWin(cid);
                  try{ autoArrangeWins(); }catch(e){}
                  refreshManageList();
                }
              }catch(e){
                try{ setLoading(false); }catch(ex){}
              }
            }
          });
        }
      }catch(e){}

      const dragZone = el.querySelector(".drag-zone");
      dragZone.addEventListener("pointerdown", (ev) => {
        if(!editMode) return;
        if(String(el.getAttribute("data-lock") || "") === "1"){ try{ setStatus("已锁定"); }catch(e){}; return; }
        if(ev.button !== 0 && ev.button !== -1) return;
        focusWin(el);
        try{ if(pauseRefreshOnMouseLeave()) bumpChartActive(cid, GRACE_REFRESH_MS); }catch(e){}
        beginGridInteract(el);
        dragZone.setPointerCapture(ev.pointerId);
        const startX = ev.clientX;
        let startY = ev.clientY; // 改为let以便在滚动时更新
        const ox = parseFloat(el.style.left || "0");
        let oy = parseFloat(el.style.top || "0"); // 改为let以便在滚动时更新
        const rect = deskRect();
        const w0 = parseFloat(el.style.width || "520");
        const h0 = parseFloat(el.style.height || "360");
        let lastX = ox;
        let lastY = oy;
        // 记录上次重排时的位置
        let lastArrangeX = ox;
        let lastArrangeY = oy;
        // 获取当前格子大小
        const gSize = gridSize();

        // 检测当前图表是否与其他图表重叠（距离小于一个格子）
        function isOverlappingWithOthers(x, y, w, h) {
          const gap = gSize; // 使用一个格子作为间隙阈值
          const wins = Array.from(document.querySelectorAll("#desk .win"));
          for(const other of wins){
            const oid = String(other.getAttribute("data-id") || "");
            if(oid === cid) continue; // 跳过自己
            const ox = parseFloat(other.style.left || "0");
            const oy = parseFloat(other.style.top || "0");
            const ow = parseFloat(other.style.width || "520");
            const oh = parseFloat(other.style.height || "360");
            // 计算两个矩形之间的距离
            const xDist = Math.max(0, Math.max(ox - (x + w), x - (ox + ow)));
            const yDist = Math.max(0, Math.max(oy - (y + h), y - (oy + oh)));
            // 如果距离小于一个格子，认为有重叠
            if(xDist < gap && yDist < gap) {
              return true;
            }
          }
          return false;
        }

        let scrollAnimationId = null;
        let scrollDirection = 0;
        let lastClientY = 0;
        let lastClientX = 0;
        let lastScrollTop = 0;

        function checkAndScroll(){
          const workspace = document.querySelector('.workspace');
          if(!workspace){
            scrollAnimationId = null;
            return;
          }
          // 使用鼠标位置判断是否仍在滚动区域（而不是图表边缘）
          const workspaceRect = workspace.getBoundingClientRect();
          const scrollZone = 80;
          const viewBottom = workspace.scrollTop + workspaceRect.height;
          const viewTop = workspace.scrollTop;
          const viewRight = workspace.scrollLeft + workspaceRect.width;
          const viewLeft = workspace.scrollLeft;

          // 禁止在顶部时继续向上滚动
          if(scrollDirection === -1 && workspace.scrollTop <= 0){
            scrollDirection = 0;
            scrollAnimationId = null;
            return;
          }

          // 使用鼠标位置判断是否离开滚动区域
          if(scrollDirection === 1 && lastClientY <= workspaceRect.bottom - scrollZone){
            // 鼠标已离开底部滚动区域
            scrollDirection = 0;
            scrollAnimationId = null;
            return;
          }
          if(scrollDirection === -1 && lastClientY >= workspaceRect.top + scrollZone){
            // 鼠标已离开顶部滚动区域
            scrollDirection = 0;
            scrollAnimationId = null;
            return;
          }
          if(scrollDirection === 0){
            scrollAnimationId = null;
            return;
          }

          // 计算滚动量
          const scrollDelta = scrollDirection * 15;
          workspace.scrollTop += scrollDelta;

          // 滚动时图表在desk上的位置不变，但需要调整startY来保持鼠标和图表的相对位置
          // 因为：ny = oy + (e.clientY - startY)
          // 滚动后，图表在屏幕上的位置变了，需要调整startY来补偿
          startY -= scrollDelta;

          showGhost(parseFloat(el.style.left), parseFloat(el.style.top), w0, h0);
          expandDeskIfNeeded();

          scrollAnimationId = requestAnimationFrame(checkAndScroll);
        }
        
        function startScrolling(direction){
          if(scrollDirection === direction && scrollAnimationId) return;
          scrollDirection = direction;
          if(!scrollAnimationId){
            scrollAnimationId = requestAnimationFrame(checkAndScroll);
          }
        }
        
        function stopAutoScroll(){
          scrollDirection = 0;
          if(scrollAnimationId){
            cancelAnimationFrame(scrollAnimationId);
            scrollAnimationId = null;
          }
        }
        
        function onMove(e){
          const dx = e.clientX - startX;
          const dy = e.clientY - startY;
          // 只有当实际移动距离超过阈值时才处理
          if(Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
          
          // 先计算新位置，X方向允许超出边界
          const nx = snap(ox + dx);
          let ny = snap(oy + dy);
          // 限制图表不能拖动到顶部以上
          if(ny < 0) ny = 0;
          
          // 更新鼠标位置
          lastClientY = e.clientY;
          lastClientX = e.clientX;

          // 使用鼠标位置判断是否接近页面边缘，触发滚动（而不是图表边缘）
          const workspace = document.querySelector('.workspace');
          const workspaceRect = workspace.getBoundingClientRect();
          const scrollZone = 80; // 触发滚动的区域大小
          const viewBottom = workspace.scrollTop + workspaceRect.height; // 可见区域底部
          const viewTop = workspace.scrollTop; // 可见区域顶部
          const viewRight = workspace.scrollLeft + workspaceRect.width; // 可见区域右边界
          const viewLeft = workspace.scrollLeft; // 可见区域左边界

          // 向下滚动：鼠标接近可见区域底部
          if(lastClientY > workspaceRect.bottom - scrollZone){
            startScrolling(1);
          }
          // 向上滚动：鼠标接近可见区域顶部，且不在最顶部
          else if(lastClientY < workspaceRect.top + scrollZone && workspace.scrollTop > 0){
            startScrolling(-1);
          }else{
            stopAutoScroll();
          }

          // 水平方向自动滚动（也使用鼠标位置）
          if(lastClientX > workspaceRect.right - scrollZone){
            workspace.scrollLeft += 15;
          }else if(lastClientX < workspaceRect.left + scrollZone && workspace.scrollLeft > 0){
            workspace.scrollLeft -= 15;
          }
          
          // 只有当位置实际变化时才更新
          if(nx === lastX && ny === lastY) return;
          lastX = nx;
          lastY = ny;
          const cand = {x:nx, y:ny, w:w0, h:h0};
          if(hitLockedWithGap(cid, cand)){
            const candX = {x:nx, y:lastY, w:w0, h:h0};
            const candY = {x:lastX, y:ny, w:w0, h:h0};
            if(!hitLockedWithGap(cid, candX)){
              lastX = nx;
            }else if(!hitLockedWithGap(cid, candY)){
              lastY = ny;
            }
            el.style.left = snap(lastX) + "px";
            el.style.top = snap(lastY) + "px";
            showGhost(snap(lastX), snap(lastY), w0, h0);
            expandDeskIfNeeded();
            // 只有当与上次重排位置相差超过1个格子且与其他图表重叠时才触发重排
            if((Math.abs(lastX - lastArrangeX) >= gSize || Math.abs(lastY - lastArrangeY) >= gSize) &&
               isOverlappingWithOthers(lastX, lastY, w0, h0)){
              lastArrangeX = lastX;
              lastArrangeY = lastY;
              try{ autoArrangeWins(cid, false); }catch(ex){}
            }
            return;
          }
          el.style.left = nx + "px";
          el.style.top = ny + "px";
          showGhost(nx, ny, w0, h0);
          expandDeskIfNeeded();
          // 只有当与上次重排位置相差超过1个格子且与其他图表重叠时才触发重排
          if((Math.abs(nx - lastArrangeX) >= gSize || Math.abs(ny - lastArrangeY) >= gSize) &&
             isOverlappingWithOthers(nx, ny, w0, h0)){
            lastArrangeX = nx;
            lastArrangeY = ny;
            try{ autoArrangeWins(cid, false); }catch(ex){}
          }
        }
        function onUp(e){
          stopAutoScroll();
          dragZone.releasePointerCapture(ev.pointerId);
          dragZone.removeEventListener("pointermove", onMove);
          dragZone.removeEventListener("pointerup", onUp);
          dragZone.removeEventListener("pointercancel", onUp);
          // 只有当位置实际变化且与其他图表重叠时才触发重排
          const finalX = parseFloat(el.style.left || "0");
          const finalY = parseFloat(el.style.top || "0");
          if((finalX !== ox || finalY !== oy) && isOverlappingWithOthers(finalX, finalY, w0, h0)){
            try{ autoArrangeWins(cid); }catch(ex){}
          }
          endGridInteract();
          expandDeskIfNeeded();
          try{ if(pauseRefreshOnMouseLeave()) bumpChartActive(cid, GRACE_REFRESH_MS); }catch(ex){}
        }
        dragZone.addEventListener("pointermove", onMove);
        dragZone.addEventListener("pointerup", onUp);
        dragZone.addEventListener("pointercancel", onUp);
      });

      const resizer = el.querySelector(".resizer");
      resizer.addEventListener("pointerdown", (ev) => {
        if(!editMode) return;
        if(String(el.getAttribute("data-lock") || "") === "1"){ try{ setStatus("已锁定"); }catch(e){}; return; }
        if(ev.button !== 0 && ev.button !== -1) return;
        focusWin(el);
        try{ if(pauseRefreshOnMouseLeave()) bumpChartActive(cid, GRACE_REFRESH_MS); }catch(e){}
        beginGridInteract(el);
        resizer.setPointerCapture(ev.pointerId);
        const startX = ev.clientX;
        const startY = ev.clientY;
        const ow = parseFloat(el.style.width || "520");
        const oh = parseFloat(el.style.height || "360");
        const ox = parseFloat(el.style.left || "0");
        const oy = parseFloat(el.style.top || "0");
        const rect = deskRect();
        let lastW = ow;
        let lastH = oh;
        // 最小尺寸：8x4 个格子，使用 gridSize() 获取当前格子大小
        const minResizeW = 8 * gridSize();
        const minResizeH = 4 * gridSize();
        // 获取当前格子大小用于重叠检测
        const gSize = gridSize();
        // 检测当前图表是否与其他图表重叠（距离小于一个格子）
        function isOverlappingWithOthers(x, y, w, h) {
          const gap = gSize; // 使用一个格子作为间隙阈值
          const wins = Array.from(document.querySelectorAll("#desk .win"));
          for(const other of wins){
            const oid = String(other.getAttribute("data-id") || "");
            if(oid === cid) continue; // 跳过自己
            const oox = parseFloat(other.style.left || "0");
            const ooy = parseFloat(other.style.top || "0");
            const oow = parseFloat(other.style.width || "520");
            const ooh = parseFloat(other.style.height || "360");
            // 计算两个矩形之间的距离
            const xDist = Math.max(0, Math.max(oox - (x + w), x - (oox + oow)));
            const yDist = Math.max(0, Math.max(ooy - (y + h), y - (ooy + ooh)));
            // 如果距离小于一个格子，认为有重叠
            if(xDist < gap && yDist < gap) {
              return true;
            }
          }
          return false;
        }
        function onMove(e){
          const dx = e.clientX - startX;
          const dy = e.clientY - startY;
          // 宽度和高度都允许超出边界
          const nw = Math.max(minResizeW, snap(ow + dx));
          const nh = Math.max(minResizeH, snap(oh + dy));
          const cand = {x:ox, y:oy, w:nw, h:nh};
          if(hitLockedWithGap(cid, cand)){
            const candW = {x:ox, y:oy, w:nw, h:lastH};
            const candH = {x:ox, y:oy, w:lastW, h:nh};
            if(!hitLockedWithGap(cid, candW)){
              lastW = nw;
            }else if(!hitLockedWithGap(cid, candH)){
              lastH = nh;
            }
            el.style.width = snap(lastW) + "px";
            el.style.height = snap(lastH) + "px";
            showGhost(ox, oy, snap(lastW), snap(lastH));
            return;
          }
          lastW = nw;
          lastH = nh;
          el.style.width = nw + "px";
          el.style.height = nh + "px";
          showGhost(ox, oy, nw, nh);
          const inst = chartViews.get(cid);
          try{ if(inst) inst.resize(); }catch(ex){}
          // 数据图需要重新渲染以更新数字位置
          try{
            const chartData = chartsById.get(cid);
            if(chartData && chartData.type === "number"){
              const payload = chartData._lastPayload;
              if(payload){
                renderChartFromPayload(cid, chartData, payload);
              }
            }
          }catch(ex){}
        }
        function onUp(){
          resizer.releasePointerCapture(ev.pointerId);
          resizer.removeEventListener("pointermove", onMove);
          resizer.removeEventListener("pointerup", onUp);
          resizer.removeEventListener("pointercancel", onUp);
          // 保存新的尺寸到布局
          try{ scheduleLayoutSave(cid, el); }catch(ex){}
          // 只有当尺寸实际变化且与其他图表重叠时才触发重排
          const finalW = parseFloat(el.style.width || "520");
          const finalH = parseFloat(el.style.height || "360");
          if((finalW !== ow || finalH !== oh) && isOverlappingWithOthers(ox, oy, finalW, finalH)){
            try{ autoArrangeWins(cid); }catch(ex){}
          }
          endGridInteract();
          expandDeskIfNeeded();
          try{ if(pauseRefreshOnMouseLeave()) bumpChartActive(cid, GRACE_REFRESH_MS); }catch(ex){}
        }
        resizer.addEventListener("pointermove", onMove);
        resizer.addEventListener("pointerup", onUp);
        resizer.addEventListener("pointercancel", onUp);
      });

      desk.appendChild(el);
      focusWin(el);
      expandDeskIfNeeded();

      const node = el.querySelector("#c_"+cid);
      const inst = echarts.init(node, currentTheme);
      chartViews.set(cid, inst);
      attachChartWheelZoom(cid, node);
    }

    function destroyWin(chartId){
      const el = document.querySelector('.win[data-id="'+chartId+'"]');
      if(el){ el.remove(); }
      const inst = chartViews.get(chartId);
      if(inst){
        try{ inst.dispose(); }catch(e){}
        chartViews.delete(chartId);
      }
      try{ stopHoverRefresh(chartId); }catch(e){}
      try{ chartHover.delete(String(chartId||"")); }catch(e){}
      try{ chartRefreshing.delete(String(chartId||"")); }catch(e){}
      try{ chartRefreshingToken.delete(String(chartId||"")); }catch(e){}
      try{ chartActiveUntil.delete(String(chartId||"")); }catch(e){}
    }

    function makeWatermarkGraphic(){
      const items = [];
      const text = String(watermarkText || "").trim() || "Bird";
      const fs = clamp(Number(watermarkFontSize || 22), 10, 64);
      const c = (() => {
        try{
          const u = ui();
          return u && u.dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.10)";
        }catch(e){
          return "rgba(255,255,255,0.06)";
        }
      })();
      const stepY = Math.max(52, Math.round(fs * 3.8));
      const stepX = Math.max(120, Math.round(fs * 7.5));
      for(let y=-120;y<1400;y+=stepY){
        for(let x=-140;x<2200;x+=stepX){
          items.push({type:"text", left:x, top:y, rotation:-Math.PI/6, z:100, silent:true, style:{text:text, font:`bold ${fs}px sans-serif`, fill:c}});
        }
      }
      return items;
    }

    function baseOption(){
      const opt = state && state.display_options ? state.display_options : {};
      const showLegend = !!(opt.show_legend !== false);
      const showGrid = !!(opt.show_grid !== false);
      const enableAnimation = !!(opt.enable_animation !== false);
      const fontSize = opt.font_size ? Number(opt.font_size) : 12;
      const u = ui();
      return stabilizeOption({
        textStyle: {color:u.textColor, fontSize: fontSize},
        animation: enableAnimation,
        legend: showLegend ? {} : undefined,
        grid: showGrid ? {} : undefined,
      }, "base");
    }

    function toTreeSeries(data, hasTitle, chartHeight){
      // 计算树图的布局位置
      const titleBottom = 24;
      const padding = 10;
      let top = padding;
      let bottom = padding;
      if(hasTitle && chartHeight){
        // 有标题时：树图区域在标题下方和容器底部之间居中
        const contentHeight = chartHeight - titleBottom - padding * 2;
        top = titleBottom + padding;
        bottom = padding;
      }
      return [{type:"tree", data:[data], top: top, left: padding, bottom: bottom, right: padding, symbolSize: 6, roam: true, initialTreeDepth: 3, label:{position:"left"}, leaves:{label:{position:"right"}}}];
    }

    function setChartOption(chartId, title, option){
      const inst = chartViews.get(chartId);
      if(!inst) return;
      const opt = stabilizeOption(Object.assign({}, option || {}), "base");
      // 根据设置决定是否显示标题
      const showTitle = !!(state && state.display_options && state.display_options.show_title);
      if(showTitle && title){
        opt.title = {
          text: title,
          left: "center",
          top: 10,
          textStyle: {
            fontSize: 14,
            fontWeight: "bold"
          }
        };
      }else{
        try{ if(opt && typeof opt === "object" && opt.title !== undefined) delete opt.title; }catch(e){}
      }
      const g = [];
      if(Array.isArray(opt.graphic)){
        g.push(...opt.graphic);
      }else if(opt.graphic && typeof opt.graphic === "object"){
        g.push(opt.graphic);
      }
      opt.graphic = g;
      // 保留 legend 的选中状态
      try{
        const currentOpt = inst.getOption();
        if(currentOpt && currentOpt.legend && currentOpt.legend[0] && currentOpt.legend[0].selected){
          const selected = currentOpt.legend[0].selected;
          if(opt.legend && typeof opt.legend === "object"){
            opt.legend.selected = selected;
          }
        }
      }catch(e){}
      inst.setOption(opt, true, true);
      try{ inst.resize(); }catch(e){}
    }

    function messageGraphic(text){
      return [{
        type:"text",
        left:"center",
        top:"middle",
        silent:true,
        style:{
          text:String(text||""),
          fill:"rgba(148,163,184,0.72)",
          font:"600 13px " + (cssVar("--font-ui","sans-serif") || "sans-serif")
        }
      }];
    }

    function renderChartFromPayload(chartId, c, payload){
      const kind = (payload && payload.kind) ? payload.kind : "empty";
      if(kind === "empty"){
        setChartOption(chartId, c.name, {graphic: messageGraphic(payload.message || "暂无数据")});
        return;
      }
      if(kind === "number"){
        // 保存 payload 以便缩放时重新渲染
        const chartData = chartsById.get(chartId);
        if(chartData){
          chartData._lastPayload = payload;
        }
        // 数据图：显示单个数字
        const value = payload.value || 0;
        const inst = chartViews.get(chartId);
        if(!inst) return;
        // 获取当前主题颜色
        const u = ui();
        // 使用主题调色板的第一个颜色，如果没有则使用默认颜色
        const themeColor = u && u.colorPalette && u.colorPalette[0] ? u.colorPalette[0] : "#4992FF";
        // 检查是否显示标题（遵循全局设置）
        const showTitle = !!(state && state.display_options && state.display_options.show_title);
        // 检查图表是否有名称（作为标题）
        const chartName = c.name;
        const hasTitle = !!(showTitle && chartName && String(chartName).trim());
        // 获取图表容器尺寸
        const chartDom = inst.getDom();
        const chartWidth = chartDom ? chartDom.clientWidth : 520;
        const chartHeight = chartDom ? chartDom.clientHeight : 360;
        // 数字字体大小
        const fontSize = 72;
        // 计算数字的垂直位置（像素）
        // 标题底部约24px
        const titleBottom = 24;
        // 字体高度
        const fontHeight = fontSize;
        // 无标题时：容器高度的一半，减去字体高度的一半（让文字中心对齐）
        // 有标题时：标题底部和容器底部的中间，减去字体高度的一半
        const numCenterPx = hasTitle ? (titleBottom + chartHeight) / 2 : chartHeight / 2;
        // ECharts 的 top 是文字顶部位置，所以要减去字体高度的一半
        const numTopPx = Math.round(numCenterPx - fontHeight / 2);
        // 数据图直接设置选项，不通过 setChartOption
        const opt = {
          backgroundColor: "transparent",
          tooltip: {show: false},
          grid: {left: 0, right: 0, top: 0, bottom: 0},
          xAxis: {show: false, min: 0, max: 1},
          yAxis: {show: false, min: 0, max: 1},
          series: [],
          graphic: [
            {
              type: "text",
              left: "center",
              top: numTopPx,
              style: {
                text: String(value),
                fontSize: fontSize,
                fontWeight: "bold",
                // 使用当前主题的颜色
                fill: themeColor,
                textAlign: "center",
                textVerticalAlign: "middle"
              }
            }
          ]
        };
        // 只要图表有名称就显示标题
        if(hasTitle){
          opt.title = {
            text: c.name,
            left: "center",
            top: 10,
            textStyle: {
              fontSize: 14,
              fontWeight: "bold"
            }
          };
        }
        inst.setOption(opt, true, true);
        try{ inst.resize(); }catch(e){}
        return;
      }
      if(kind === "xy"){
        const opt = baseOption();
        const ct = payload.chart_type || c.type;
        const xs = payload.x || [];
        const series = (payload.series||[]).map(s => {
          return {name:s.name || "数值", type:(ct === "line" || ct === "timelineLine") ? "line" : "bar", smooth: !!(payload.meta && payload.meta.smooth), data: s.data || []};
        });
        let xAxis = {type:"category", data: xs};
        try{
          const meta = payload.meta || {};
          if(String(meta.bar_x_kind || "") === "time"){
            const unit = String(meta.unit || "day");
            xAxis.axisLabel = xAxis.axisLabel || {};
            xAxis.axisLabel.formatter = (v) => {
              // 将所有冒号替换为横线，确保时间格式统一为2025-11而不是2025:11
              const s = String(v == null ? "" : v).replace(/:/g, "-");
              if(unit === "month"){
                return s.length >= 7 ? s.slice(0, 7) : s;
              }
              if(unit === "year"){
                return s.length >= 4 ? s.slice(0, 4) : s;
              }
              return s.length >= 10 ? s.slice(0, 10) : s;
            };
          }
        }catch(e){}
        let finalSeries = series;
        try{
          const isBar = !(ct === "line" || ct === "timelineLine");
          if(isBar){
            const count = Array.isArray(xs) ? xs.length : 0;
            xAxis.axisLabel = xAxis.axisLabel || {};
            if(xAxis.axisLabel.interval === undefined) xAxis.axisLabel.interval = 0;
            let rotate = 0;
            if(count > 28){ rotate = 45; }
            else if(count > 16){ rotate = 30; }
            xAxis.axisLabel.rotate = rotate;
            xAxis.axisLabel.hideOverlap = false;
            xAxis.axisTick = xAxis.axisTick || {};
            xAxis.axisTick.alignWithLabel = true;
            if(!opt.grid || typeof opt.grid !== "object"){ opt.grid = {}; }
            if(opt.grid.containLabel === undefined) opt.grid.containLabel = true;
            if(opt.grid.left === undefined) opt.grid.left = 42;
            if(opt.grid.right === undefined) opt.grid.right = 12;
            // 计算grid的top和bottom实现居中
            const xyInst = chartViews.get(chartId);
            if(xyInst){
              const chartDom = xyInst.getDom();
              const chartHeight = chartDom ? chartDom.clientHeight : 360;
              const showTitle = !!(state && state.display_options && state.display_options.show_title);
              const chartName = c.name;
              const hasTitle = !!(showTitle && chartName && String(chartName).trim());
              // X轴标签高度（考虑旋转）
              const labelHeight = rotate ? 40 : 24;
              // 图表内容高度
              const contentHeight = chartHeight - labelHeight - (hasTitle ? 44 : 0);
              // 有标题时：标题底部约24px，图表区域在标题下方和容器底部之间居中
              if(hasTitle){
                const titleBottom = 24;
                const gridTop = titleBottom + contentHeight * 0.1;
                const gridBottom = chartHeight - titleBottom - contentHeight * 0.9;
                if(opt.grid.top === undefined) opt.grid.top = Math.max(10, Math.round(gridTop));
                if(opt.grid.bottom === undefined) opt.grid.bottom = Math.max(labelHeight, Math.round(labelHeight + (chartHeight - titleBottom - contentHeight) / 2));
              }else{
                // 无标题时：图表区域在容器中间
                const gridTop = contentHeight * 0.1;
                if(opt.grid.top === undefined) opt.grid.top = Math.max(10, Math.round(gridTop));
                if(opt.grid.bottom === undefined) opt.grid.bottom = Math.max(labelHeight, Math.round(labelHeight + (chartHeight - contentHeight) / 2));
              }
            }else{
              if(opt.grid.top === undefined) opt.grid.top = 58;
              if(opt.grid.bottom === undefined) opt.grid.bottom = rotate ? 52 : 34;
            }
            let w = 0;
            try{
              const inst = chartViews.get(chartId);
              if(inst && inst.getWidth){ w = Number(inst.getWidth() || 0); }
            }catch(e){}
            if(w > 0 && count > 0){
              const per = Math.max(2, Math.floor((w - 80) / count));
              const bw = Math.max(2, Math.min(36, per - 2));
              finalSeries = series.map(s => Object.assign({}, s, {barWidth: bw, barMaxWidth: Math.max(2, Math.min(36, bw))}));
            }
          }
        }catch(e){}
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(
            Object.assign(opt, {tooltip:{trigger:"axis"}, xAxis: xAxis, yAxis:{type:"value"}, series: finalSeries}),
            (ct === "line" || ct === "timelineLine") ? "line" : "bar"
          )
        );
        return;
      }
      if(kind === "pie"){
        const opt = baseOption();
        const inst = chartViews.get(chartId);
        // 计算饼图中心位置
        let pieCenter = ['50%', '50%'];
        if(inst){
          const chartDom = inst.getDom();
          const chartHeight = chartDom ? chartDom.clientHeight : 360;
          // 检查是否显示标题
          const showTitle = !!(state && state.display_options && state.display_options.show_title);
          const chartName = c.name;
          const hasTitle = !!(showTitle && chartName && String(chartName).trim());
          // 检查是否显示图例
          const showLegend = !!(state && state.display_options && state.display_options.show_legend !== false);
          // 计算顶部占用高度
          let topOffset = 0;
          if(hasTitle){
            topOffset = 34; // 标题高度
          }
          if(showLegend){
            // 图例高度：根据数据项数量估算，每行约22px，最多2行
            const itemCount = (payload.items || []).length;
            const legendRows = Math.min(2, Math.ceil(itemCount / 4));
            topOffset += legendRows * 22 + 10; // 图例高度 + 间距
          }
          // 饼图中心在顶部占用区域下方和容器底部之间居中
          const centerY = (topOffset + chartHeight) / 2;
          pieCenter = ['50%', Math.round(centerY) + 'px'];
        }
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {tooltip:{trigger:"item"}, series:[{type:"pie", radius:["30%","65%"], center: pieCenter, label:{distance: 25}, data:(payload.items||[])}]}), "pie")
        );
        return;
      }
      if(kind === "tree"){
        const opt = baseOption();
        const treeData = payload.data || {name: "鸟种", children: []};
        const layout = payload.layout || "LR";
        const showCount = payload.show_count !== false;
        
        // 获取主题颜色
        const u = ui();
        const textColor = u.textColor;
        const lineColor = u.dark ? 'rgba(148,163,184,0.3)' : 'rgba(71,85,105,0.3)';
        const colorPalette = u.colorPalette || ["#4992FF","#7CFFB2","#FDDD60","#FF6E76","#58D9F9","#05C091"];
        
        // 根据布局方向设置边距
        let left, right, top, bottom;
        if(layout === "LR"){
          left = "5%"; right = "15%"; top = "5%"; bottom = "5%";
        }else if(layout === "RL"){
          left = "15%"; right = "5%"; top = "5%"; bottom = "5%";
        }else if(layout === "TB"){
          left = "5%"; right = "5%"; top = "8%"; bottom = "8%";
        }else if(layout === "BT"){
          left = "5%"; right = "5%"; top = "8%"; bottom = "8%";
        }else{
          left = "10%"; right = "10%"; top = "10%"; bottom = "10%";
        }
        
        // 为树图节点添加层级颜色
        function addLevelColor(node, level){
          if(!node) return;
          node.itemStyle = node.itemStyle || {};
          node.itemStyle.color = colorPalette[level % colorPalette.length];
          if(node.children && node.children.length > 0){
            for(let i = 0; i < node.children.length; i++){
              addLevelColor(node.children[i], level + 1);
            }
          }
        }
        addLevelColor(treeData, 0);
        
        // 根据布局配置树图
        let seriesConfig;
        if(layout === "radial"){
          seriesConfig = {
            type: "tree",
            data: [treeData],
            layout: "radial",
            symbol: "circle",
            symbolSize: 6,
            initialTreeDepth: -1,
            animationDurationUpdate: 750,
            roam: false,
            silent: true,
            left: left,
            right: right,
            top: top,
            bottom: bottom,
            lineStyle: {
              color: lineColor,
              width: 1
            },
            label: {
              show: true,
              position: "right",
              fontSize: 11,
              color: textColor,
              formatter: showCount ? function(params){ return params.name + (params.value ? ` (${params.value})` : ""); } : "{b}"
            },
            leaves: {
              label: {
                position: "right"
              }
            }
          };
        }else{
          seriesConfig = {
            type: "tree",
            data: [treeData],
            layout: "orthogonal",
            orient: layout,
            symbol: "circle",
            symbolSize: 6,
            initialTreeDepth: -1,
            animationDurationUpdate: 750,
            roam: false,
            silent: true,
            left: left,
            right: right,
            top: top,
            bottom: bottom,
            lineStyle: {
              color: lineColor,
              width: 1
            },
            label: {
              show: true,
              position: layout === "LR" ? "right" : layout === "RL" ? "left" : layout === "TB" ? "top" : "bottom",
              fontSize: 11,
              color: textColor,
              formatter: showCount ? function(params){ return params.name + (params.value ? ` (${params.value})` : ""); } : "{b}"
            },
            leaves: {
              label: {
                position: layout === "LR" ? "right" : layout === "RL" ? "left" : layout === "TB" ? "top" : "bottom"
              }
            }
          };
        }
        
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {
            color: colorPalette,
            series: [seriesConfig]
          }), "tree")
        );
        return;
      }
      if(kind === "scatter"){
        const opt = baseOption();
        const pts = payload.points || [];
        const autoSize = !!payload.auto_size;
        // 处理数据，将size信息合并到数据中
        const seriesData = [];
        let timeFormat = null; // null=数值, day=日期, week=周, month=月, year=年
        
        // 先收集所有Y值，用于计算气泡大小
        let yMin = Infinity, yMax = -Infinity;
        for(let i = 0; i < pts.length; i++){
          const p = pts[i];
          if(!Array.isArray(p) || p.length < 2) continue;
          const y = parseFloat(p[1]);
          if(!isNaN(y)){
            if(y < yMin) yMin = y;
            if(y > yMax) yMax = y;
          }
        }
        const yRange = yMax - yMin;
        
        for(let i = 0; i < pts.length; i++){
          const p = pts[i];
          if(!Array.isArray(p) || p.length < 2){
            continue;
          }
          const xRaw = p[0];
          const y = parseFloat(p[1]);
          if(isNaN(y)){
            continue;
          }
          // 检测X轴时间格式
          if(typeof xRaw === "string"){
            if(/^\d{4}-\d{2}-\d{2}$/.test(xRaw)){
              timeFormat = "day";
            }else if(/^\d{4}-W\d{2}$/.test(xRaw)){
              timeFormat = "week";
            }else if(/^\d{4}-\d{2}$/.test(xRaw)){
              timeFormat = "month";
            }else if(/^\d{4}$/.test(xRaw)){
              timeFormat = "year";
            }
          }
          // 计算气泡大小
          let size = 8;
          if(autoSize && yRange > 0){
            // 根据Y值在范围内的比例计算大小，范围4-20
            const ratio = (y - yMin) / yRange;
            size = Math.max(4, Math.min(20, 4 + ratio * 16));
          }
          seriesData.push({value: [xRaw, y], symbolSize: size});
        }
        // 计算grid实现居中
        if(!opt.grid || typeof opt.grid !== "object"){ opt.grid = {}; }
        const scatterInst = chartViews.get(chartId);
        if(scatterInst){
          const chartDom = scatterInst.getDom();
          const chartHeight = chartDom ? chartDom.clientHeight : 360;
          const showTitle = !!(state && state.display_options && state.display_options.show_title);
          const chartName = c.name;
          const hasTitle = !!(showTitle && chartName && String(chartName).trim());
          const labelHeight = 24;
          const contentHeight = chartHeight - labelHeight - (hasTitle ? 44 : 0);
          if(hasTitle){
            const titleBottom = 24;
            const gridTop = titleBottom + contentHeight * 0.1;
            if(opt.grid.top === undefined) opt.grid.top = Math.max(10, Math.round(gridTop));
            if(opt.grid.bottom === undefined) opt.grid.bottom = Math.max(labelHeight, Math.round(labelHeight + (chartHeight - titleBottom - contentHeight) / 2));
          }else{
            const gridTop = contentHeight * 0.1;
            if(opt.grid.top === undefined) opt.grid.top = Math.max(10, Math.round(gridTop));
            if(opt.grid.bottom === undefined) opt.grid.bottom = Math.max(labelHeight, Math.round(labelHeight + (chartHeight - contentHeight) / 2));
          }
        }
        if(opt.grid.containLabel === undefined) opt.grid.containLabel = true;
        if(opt.grid.left === undefined) opt.grid.left = 42;
        if(opt.grid.right === undefined) opt.grid.right = 12;
        
        // 根据时间格式配置X轴
        let xAxisConfig;
        if(timeFormat === "day"){
          // 按天：使用时间轴，自动计算标签间隔避免重叠
          xAxisConfig = {
            type: "time",
            axisLabel: {
              formatter: "{MM}-{dd}",
              rotate: 45,
              interval: "auto"
            }
          };
        }else if(timeFormat === "week"){
          // 按周：使用类目轴，旋转标签
          xAxisConfig = {
            type: "category",
            axisLabel: {
              rotate: 45,
              interval: 0
            }
          };
        }else if(timeFormat === "month"){
          // 按月：使用类目轴
          xAxisConfig = {
            type: "category",
            axisLabel: {
              interval: 0
            }
          };
        }else if(timeFormat === "year"){
          // 按年：使用类目轴
          xAxisConfig = {
            type: "category"
          };
        }else{
          xAxisConfig = { type: "value" };
        }
        
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {
            tooltip:{trigger:"item"},
            xAxis: xAxisConfig,
            yAxis:{type:"value"},
            series:[{type:"scatter", data: seriesData}]
          }), "scatter")
        );
        return;
      }
      if(kind === "tree"){
        const opt = baseOption();
        // 计算树图位置
        const treeInst = chartViews.get(chartId);
        let chartHeight = 360;
        let hasTitle = false;
        if(treeInst){
          const chartDom = treeInst.getDom();
          chartHeight = chartDom ? chartDom.clientHeight : 360;
          const showTitle = !!(state && state.display_options && state.display_options.show_title);
          hasTitle = !!(showTitle && c.name && String(c.name).trim());
        }
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {tooltip:{trigger:"item"}, series: toTreeSeries(payload.data, hasTitle, chartHeight)}), "tree")
        );
        return;
      }
      if(kind === "graph"){
        const opt = baseOption();
        // 计算graph位置
        const graphInst = chartViews.get(chartId);
        let chartHeight = 360;
        let hasTitle = false;
        if(graphInst){
          const chartDom = graphInst.getDom();
          chartHeight = chartDom ? chartDom.clientHeight : 360;
          const showTitle = !!(state && state.display_options && state.display_options.show_title);
          hasTitle = !!(showTitle && c.name && String(c.name).trim());
        }
        // 计算graph的中心位置
        let graphCenter = ['50%', '50%'];
        if(hasTitle){
          const titleBottom = 24;
          const centerY = (titleBottom + chartHeight) / 2;
          graphCenter = ['50%', Math.round(centerY) + 'px'];
        }else{
          graphCenter = ['50%', Math.round(chartHeight / 2) + 'px'];
        }
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {
            tooltip:{},
            legend:[{data:(payload.categories||[]).map(x=>x.name)}],
            series:[{type:"graph", layout:"force", center: graphCenter, data:(payload.nodes||[]), links:(payload.links||[]), categories:(payload.categories||[]), roam:true, label:{show:true}, force:{repulsion: 120, edgeLength: 70}}]
          }), "graph")
        );
        return;
      }
      if(kind === "geo_points"){
        const opt = baseOption();
        const pts = payload.points || [];
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {
            tooltip:{trigger:"item"},
            xAxis:{type:"value", name:"经度"},
            yAxis:{type:"value", name:"纬度"},
            series:[{type:"scatter", data: pts.map(p => [p[0], p[1], p[2]]), symbolSize: (v)=>Math.max(3, Math.min(18, (v[2]||1))) }]
          }), "geo")
        );
        return;
      }
      if(kind === "gauge"){
        const opt = baseOption();
        const ms = payload.metrics || [];
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {
            tooltip:{},
            series: ms.map((m, idx) => {
              return {
                type:"gauge",
                startAngle: 210,
                endAngle: -30,
                radius: (ms.length<=1) ? "80%" : (idx===0 ? "65%" : "45%"),
                center: ms.length<=1 ? ["50%","60%"] : ["50%", idx===0 ? "55%" : "70%"],
                pointer:{show:true},
                detail:{valueAnimation:true, formatter:"{value}"},
                title:{offsetCenter:[0,"85%"], fontSize:12},
                data:[{value: Number(m.value||0), name: m.name||""}]
              };
            })
          }), "gauge")
        );
        return;
      }
      if(kind === "radar"){
        const opt = baseOption();
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {tooltip:{}, radar:{indicator:(payload.indicators||[])}, series:[{type:"radar", data:[{value:(payload.value||[]), name:"指标"}]}]}), "radar")
        );
        return;
      }
      if(kind === "calendar"){
        const opt = baseOption();
        const d = payload.data || [];
        const years = d.map(x => String(x[0]||"").slice(0,4)).filter(Boolean);
        const year = years.length ? years[0] : new Date().getFullYear();
        setChartOption(
          chartId,
          c.name,
          stabilizeOption(Object.assign(opt, {
            tooltip:{},
            visualMap:{min:0, max: Math.max(1, ...d.map(x=>x[1]||0)), orient:"horizontal", left:"center", bottom:10, textStyle:{color: ui().textColor, fontSize: 10}},
            calendar:{top:60, left:50, right:30, cellSize:[14, 14], range:String(year)},
            series:[{type:"heatmap", coordinateSystem:"calendar", data:d}]
          }), "calendar")
        );
        return;
      }
      setChartOption(chartId, c.name, {graphic: messageGraphic("暂不支持该图表渲染")});
    }

    async function rerenderAllChartsYielding(jobId, reason){
      const ids = Array.from(chartsById.keys());
      const rid = Number(jobId || 0);
      const label = String(reason || "");
      await new Promise(r => requestAnimationFrame(() => r()));
      for(const cid of ids){
        if(rid && rid !== __bpRerenderJobId) return;
        const c = chartsById.get(cid);
        const p = chartPayloadCache.get(cid);
        if(c && p){
          try{ renderChartFromPayload(cid, c, p); }catch(e){}
        }else{
          try{ await renderChart(cid); }catch(e){}
        }
        if(label){ try{ probeNextFrame(label); }catch(e){} }
        await new Promise(r => requestAnimationFrame(() => r()));
      }
    }

    async function renderChart(chartId){
      const c = chartsById.get(chartId);
      if(!c) return;
      const id = String(chartId || "");
      const tokenId = (chartRefreshingToken.get(id) || 0) + 1;
      chartRefreshingToken.set(id, tokenId);
      const t0 = perfNow();
      setChartRefreshing(id, true);
      try{
        const resp = await bridgeCall(bridge, "get_chart_payload", {chart_id: c.chart_id, config: c}, token);
        if(!resp.ok){
          setChartOption(chartId, c.name, {graphic: messageGraphic("数据加载失败")});
          return;
        }
        const payload = resp.data || {};
        try{ chartPayloadCache.set(chartId, payload); }catch(e){}
        renderChartFromPayload(chartId, c, payload);
      }finally{
        const dt = perfNow() - t0;
        const wait = Math.max(0, MIN_REFRESH_LAMP_MS - dt);
        if(wait > 0){
          setTimeout(() => {
            try{
              const cur = chartRefreshingToken.get(id) || 0;
              if(cur !== tokenId) return;
              setChartRefreshing(id, false);
            }catch(e){}
          }, Math.round(wait));
        }else{
          setChartRefreshing(id, false);
        }
      }
    }

    function refreshManageList(){
      const wrap = $("manageList");
      wrap.innerHTML = "";
      const arr = Array.from(chartsById.values());
      if(!arr.length){
        const div = document.createElement("div");
        div.style.color = "var(--muted)";
        div.textContent = "暂无图表";
        wrap.appendChild(div);
        return;
      }
      arr.forEach(c => {
        const row = document.createElement("div");
        row.style.display = "flex";
        row.style.alignItems = "center";
        row.style.justifyContent = "space-between";
        row.style.gap = "10px";
        row.style.padding = "10px";
        row.style.border = "1px solid var(--border)";
        row.style.borderRadius = "12px";
        row.style.background = "rgba(0,0,0,.12)";
        const left = document.createElement("div");
        left.style.minWidth = "0";
        left.innerHTML = `<div style="font-weight:800;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${c.name}</div>
          <div style="color:var(--muted);font-size:12px">${c.type_title}</div>`;
        const right = document.createElement("div");
        right.style.display="flex";
        right.style.gap="8px";
        const b1 = document.createElement("button");
        b1.className = "btn";
        b1.textContent = "定位";
        b1.addEventListener("click", () => {
          closeModal("modalManage");
          const w = document.querySelector('.win[data-id="'+c.chart_id+'"]');
          if(w){ focusWin(w); }
        });
        const b2 = document.createElement("button");
        b2.className = "btn danger";
        b2.textContent = "删除";
        b2.addEventListener("click", async () => {
          setLoading(true);
          const resp = await bridgeCall(bridge, "remove_chart", {chart_id: c.chart_id}, token);
          setLoading(false);
          if(resp.ok){
            chartsById.delete(c.chart_id);
            destroyWin(c.chart_id);
            try{ autoArrangeWins(); }catch(e){}
            refreshManageList();
          }
        });
        right.appendChild(b1);
        right.appendChild(b2);
        row.appendChild(left);
        row.appendChild(right);
        wrap.appendChild(row);
      });
    }

    async function bootstrap(skipLoading = false){
      // 如果不是首次加载，跳过加载遮罩以避免页面切换时的闪烁
      if(!skipLoading){
        setLoading(true);
      }
      setStatus("初始化中…");
      const resp = await bridgeCall(bridge, "bootstrap", {}, token);
      if(!skipLoading){
        setLoading(false);
      }
      if(!resp.ok){
        setStatus("初始化失败");
        return;
      }
      state = resp.data || {};
      fillSelect($("fType"), state.chart_types || []);
      fillSelect($("fXField"), state.fields || []);
      fillSelect($("fYAgg"), state.aggs || []);
      fillSelect($("fGroup"), state.fields || [], true);
      fillSelect($("fPieCat"), state.fields || []);
      fillSelect($("fPieAgg"), state.aggs || []);
      fillSelect($("fSX"), state.fields || []);
      // Y轴字段使用HTML中定义的静态选项（图片数量、鸟种数、加新数量）
      // fillSelect($("fSY"), state.fields || []);
      syncAddFields();
      if(state.db_ready === false){
        const reason = String(state.db_error || "");
        setStatus(reason ? ("数据库不可用: " + reason) : "数据库不可用");
        setDisabled("btnAdd", true);
        setDisabled("btnEditMode", true);
        setDisabled("btnRefreshAll", true);
        return;
      }
      setDisabled("btnAdd", !editMode);
      setDisabled("btnEditMode", false);
      setDisabled("btnRefreshAll", false);

      const opt = state.display_options || {};
      $("themeSelect").value = String(state.theme || "follow");
      try{ refreshSelectLabel($("themeSelect")); }catch(e){}
      try{
        currentTheme = String(opt.echarts_theme || currentTheme || "dark");
      }catch(e){
        currentTheme = "dark";
      }
      try{
        windowStyle = String(opt.window_style || windowStyle || "acrylic");
      }catch(e){
        windowStyle = "acrylic";
      }
      try{
        const sel = $("echartsThemeSelect");
        if(sel){
          try{ sel.value = currentTheme; }catch(e){}
          let ok = false;
          try{
            for(const o of sel.options || []){
              if(String(o.value) === String(currentTheme)){ ok = true; break; }
            }
          }catch(e){}
          if(!ok){ currentTheme = String(sel.value || "dark"); }
          try{ refreshSelectLabel(sel); }catch(e){}
        }
      }catch(e){}
      try{
        const sel = $("styleSelect");
        if(sel){
          try{ sel.value = windowStyle; }catch(e){}
          let ok = false;
          try{
            for(const o of sel.options || []){
              if(String(o.value) === String(windowStyle)){ ok = true; break; }
            }
          }catch(e){}
          if(!ok){ windowStyle = String(sel.value || "acrylic"); }
          try{ refreshSelectLabel(sel); }catch(e){}
        }
      }catch(e){}
      try{ applyVisualTheme(); }catch(e){}
      $("fontSize").value = String(opt.font_size || 12);
      $("cbTitle").checked = !(opt.show_title === false);
      $("cbLegend").checked = !(opt.show_legend === false);
      $("cbAnim").checked = !(opt.enable_animation === false);
      try{ $("cbPauseRefresh").checked = !!opt.pause_refresh_on_mouse_leave; }catch(e){}
      try{ $("cbIgnoreEmptyDates").checked = !!opt.ignore_empty_dates; }catch(e){}
      $("cbGpu").checked = !!state.gpu_rendering_enabled;
      try{
        watermarkText = String(opt.watermark_text || "").trim();
      }catch(e){
        watermarkText = "";
      }
      try{
        watermarkFontSize = clamp(Number(opt.watermark_font_size || 22), 10, 64);
      }catch(e){
        watermarkFontSize = 22;
      }
      watermarkOn = !!(opt.watermark_enabled !== false);
      try{ $("cbWatermark").checked = !!watermarkOn; }catch(e){}
      try{ $("wmText").value = watermarkText; }catch(e){}
      try{ $("wmSize").value = String(watermarkFontSize); }catch(e){}
      try{ schedulePageWatermark(); }catch(e){}
      try{ syncAllToggleVisuals(); }catch(e){}

      const arr = state.charts || [];
      // 保存当前窗口的位置信息
      const currentLayouts = new Map();
      document.querySelectorAll("#desk .win").forEach(el => {
        const cid = String(el.getAttribute("data-id") || "");
        if(cid){
          currentLayouts.set(cid, {
            x: parseFloat(el.style.left || "0"),
            y: parseFloat(el.style.top || "0"),
            w: parseFloat(el.style.width || "520"),
            h: parseFloat(el.style.height || "360"),
            z: parseInt(el.style.zIndex || "1"),
            locked: String(el.getAttribute("data-lock") || "") === "1"
          });
        }
      });
      chartOrder.clear();
      orderTop = 0;
      chartsById.clear();
      chartPayloadCache.clear();
      arr.forEach((c, idx) => {
        // 使用当前位置覆盖后端返回的位置
        if(currentLayouts.has(c.chart_id)){
          c.layout = Object.assign({}, c.layout || {}, currentLayouts.get(c.chart_id));
        }
        chartsById.set(c.chart_id, c);
        const ord = idx + 1;
        chartOrder.set(c.chart_id, ord);
        orderTop = ord;
      });
      try{
        document.querySelectorAll("#desk .win").forEach(el => el.remove());
      }catch(e){}
      for(const inst of chartViews.values()){
        try{ inst.dispose(); }catch(e){}
      }
      chartViews.clear();

      arr.forEach(c => createWin(c));
      for(const c of arr){
        await renderChart(c.chart_id);
      }
      refreshManageList();
      setStatus("就绪");
    }

    function ensureBridge(){
      return new Promise((resolve) => {
        new QWebChannel(qt.webChannelTransport, function(channel){
          bridge = channel.objects.bridge;
          bridge.getToken(function(t){
            token = String(t || "");
            try{
              if(bridge.push && bridge.push.connect){
                bridge.push.connect(async function(eventName, payload){
                  const ev = String(eventName||"");
                  if(ev === "state_changed"){
                    await bootstrap();
                    return;
                  }
                  if(ev === "data_changed"){
                    if(pauseRefreshOnMouseLeave()){
                      const ids = [];
                      for(const cid of chartsById.keys()){
                        if(isChartActive(cid)) ids.push(cid);
                      }
                      if(!ids.length) return;
                      for(const cid of ids){
                        try{ await renderChart(cid); }catch(e){}
                        await new Promise(r => requestAnimationFrame(() => r()));
                      }
                      return;
                    }
                    await bootstrap();
                    return;
                  }
                });
              }
            }catch(e){}
            resolve();
          });
        });
      });
    }

    let eventsWired = false;
    let submitBusy = false;
    async function __bpSubmitAdd(){
      if(submitBusy) return;
      if(!bridge){
        setStatus("桥接未就绪");
        return;
      }
      const name = ($("fName").value || "").trim() || "未命名图表";
      const type = $("fType").value || "bar";
      let scope = pickTypeScope(type);
      try{
        if(editingChartId){
          const prev = chartsById.get(String(editingChartId || ""));
          if(prev) scope = pickTypeScopeByOptions(type, prev.options || {});
        }
      }catch(e){}
      let options = {};
      if(scope === "bar"){
        try{ barEnsureInit(); }catch(e){}
        const barKind = String(($("fBarXKind") && $("fBarXKind").value) || "time");
        options = {
          bar_x_kind: barKind,
          bar_y_kind: String(($("fBarYKind") && $("fBarYKind").value) || "count"),
          bar_time_type: String(($("fBarTimeType") && $("fBarTimeType").value) || "shot_time"),
          bar_time_start: String(barTimeStart || ""),
          bar_time_end: String(barTimeEnd || ""),
          bar_time_end_now: !!barTimeEndNow,
          bar_time_preset: String(barTimePreset || ""),
          bar_time_step: Math.max(1, Math.min(3650, Number(($("fBarTimeStep") && $("fBarTimeStep").value) || 1) || 1)),
          bar_time_unit: String(($("fBarTimeUnit") && $("fBarTimeUnit").value) || "day"),
          bar_location_level: String(($("fBarLocLevel") && $("fBarLocLevel").value) || "country"),
          bar_ignore_empty_dates: !!($("fBarHideEmptyTime") && $("fBarHideEmptyTime").checked),
          bar_filters: barGetFilters()
        };
      }else if(scope === "number"){
        options = {
          number_type: String(($("fNumberType") && $("fNumberType").value) || "count"),
          number_time_type: String(($("fNumberTimeType") && $("fNumberTimeType").value) || "shot_time"),
          number_time_start: String(numberTimeStart || ""),
          number_time_end: String(numberTimeEnd || ""),
          number_time_end_now: !!numberTimeEndNow,
          number_time_preset: String(numberTimePreset || ""),
          number_filters: numberGetFilters()
        };
      }else if(scope === "xy"){
        options = {x_field:$("fXField").value||"", y_agg:$("fYAgg").value||"count", group_field:$("fGroup").value||""};
      }else if(scope === "pie"){
        try{ pieEnsureInit(); }catch(e){}
        options = {
          category_field: String(($("fPieCat") && $("fPieCat").value) || "species"),
          value_agg: String(($("fPieAgg") && $("fPieAgg").value) || "count"),
          pie_time_type: String(($("fPieTimeType") && $("fPieTimeType").value) || "all"),
          pie_time_start: String(pieTimeStart || ""),
          pie_time_end: String(pieTimeEnd || ""),
          pie_time_end_now: !!pieTimeEndNow,
          pie_time_preset: String(pieTimePreset || ""),
          pie_filters: pieGetFilters()
        };
      }else if(scope === "tree"){
        try{ treeEnsureInit(); }catch(e){}
        const timeType = String(($("fTreeTimeType") && $("fTreeTimeType").value) || "all");
        const levels = [];
        if($("fTreeLevelOrder") && $("fTreeLevelOrder").checked) levels.push("order");
        if($("fTreeLevelFamily") && $("fTreeLevelFamily").checked) levels.push("family");
        if($("fTreeLevelGenus") && $("fTreeLevelGenus").checked) levels.push("genus");
        if($("fTreeLevelSpecies") && $("fTreeLevelSpecies").checked) levels.push("species");
        options = {
          tree_levels: levels,
          tree_show_count: !!($("fTreeShowCount") && $("fTreeShowCount").checked),
          tree_layout: String(($("fTreeLayout") && $("fTreeLayout").value) || "LR"),
          tree_time_type: timeType,
          tree_time_start: timeType === "custom" ? String(treeTimeStart || "") : "",
          tree_time_end: timeType === "custom" ? String(treeTimeEnd || "") : "",
          tree_filters: treeGetFilters()
        };
      }else if(scope === "scatter"){
        try{ scatterEnsureInit(); }catch(e){}
        const xField = String(($("fSX") && $("fSX").value) || "score");
        const isXTime = (xField === "shot_time" || xField === "created_at");
        const autoSize = !!($("fScatterAutoSize") && $("fScatterAutoSize").checked);
        options = {
          x_field: xField,
          y_field: String(($("fSY") && $("fSY").value) || "count"),
          scatter_auto_size: autoSize,
          scatter_time_group: isXTime ? String(($("fScatterTimeGroup") && $("fScatterTimeGroup").value) || "day") : "day",
          scatter_time_start: isXTime ? String(scatterTimeStart || "") : "",
          scatter_time_end: isXTime ? String(scatterTimeEnd || "") : "",
          scatter_time_end_now: isXTime ? !!scatterTimeEndNow : false,
          scatter_time_preset: isXTime ? String(scatterTimePreset || "") : "",
          scatter_filters: scatterGetFilters()
        };
      }
      submitBusy = true;
      try{
        setLoading(true);
        const cid = editingChartId ? String(editingChartId || "") : "";
        const act = cid ? "update_chart" : "add_chart";
        const payload = cid ? {chart_id: cid, name, type, options} : {name, type, options};
        const resp = await bridgeCall(bridge, act, payload, token);
        setLoading(false);
        if(resp.ok){
          const c = resp.data;
          chartsById.set(c.chart_id, c);
          try{
            if(!cid){
              const ord = orderTop + 1;
              orderTop = ord;
              chartOrder.set(c.chart_id, ord);
            }
          }catch(e){}
          if(cid){
            // 编辑图表时，先保存当前布局，然后使用当前布局创建新窗口
            const el = document.querySelector('.win[data-id="'+cid+'"]');
            let currentLayout = null;
            if(el){
              currentLayout = {
                x: parseFloat(el.style.left || "0"),
                y: parseFloat(el.style.top || "0"),
                w: parseFloat(el.style.width || "520"),
                h: parseFloat(el.style.height || "360"),
                z: parseInt(el.style.zIndex || "1"),
                locked: String(el.getAttribute("data-lock") || "") === "1"
              };
            }
            destroyWin(c.chart_id);
            // 使用当前布局覆盖后端返回的布局
            if(currentLayout){
              c.layout = Object.assign({}, c.layout || {}, currentLayout);
            }
          }
          createWin(c);
          try{ if(pauseRefreshOnMouseLeave()) bumpChartActive(c.chart_id, GRACE_REFRESH_MS); }catch(e){}
          // 编辑图表时不调用 autoArrangeWins，保持当前位置
          if(!cid){
            try{ autoArrangeWins(); }catch(e){}
          }
          await renderChart(c.chart_id);
          refreshManageList();
          closeModal("modalAdd");
          editingChartId = null;
          setAddModalMode("add");
        }
      }finally{
        submitBusy = false;
        try{ setLoading(false); }catch(e){}
      }
    }
    function wireEvents(){
      if(eventsWired) return;
      eventsWired = true;
      const on = (id, evt, fn, opts) => {
        const el = $(id);
        if(!el){ try{ setStatus("控件缺失: " + id); }catch(e){}; return null; }
        try{ el.addEventListener(evt, fn, opts); }catch(e){ try{ setStatus("绑定失败: " + id); }catch(ex){} }
        return el;
      };

      on("btnAdd", "click", () => { openAddModal(); });
      on("btnEditMode", "click", () => {
        setEditMode(!editMode);
      });
      on("btnRefreshAll", "click", async () => {
        for(const cid of chartsById.keys()){
          await renderChart(cid);
        }
      });
      on("btnOpenSettings", "click", () => { openSettingsModal(); });
      on("echartsThemeSelect", "change", async (e) => {
        const t = (e && e.target && e.target.value) ? e.target.value : "dark";
        currentTheme = String(t || "dark");
        try{ if(state && state.display_options){ state.display_options.echarts_theme = currentTheme; } }catch(ex){}
        try{ setStatus("主题: " + t); }catch(e){}
        await switchTheme(t);
        try{ schedulePreferencesSave(); }catch(e){}
      });
      on("styleSelect", "change", async (e) => {
        windowStyle = (e && e.target && e.target.value) ? e.target.value : "acrylic";
        try{ if(state && state.display_options){ state.display_options.window_style = windowStyle; } }catch(ex){}
        try{ setStatus("模式: " + windowStyle); }catch(e){}
        applyVisualTheme();
        try{ requestRerenderAllCharts("模式重绘"); }catch(e){}
        try{ schedulePreferencesSave(); }catch(e){}
      });

      on("btnCloseAdd", "click", () => closeModal("modalAdd"));
      on("btnCancelAdd", "click", () => closeModal("modalAdd"));
      on("fType", "change", () => syncAddFields());
      on("btnSubmitAdd", "click", __bpSubmitAdd);

      on("btnCloseManage", "click", () => closeModal("modalManage"));

      on("btnCloseSettings", "click", () => closeModal("modalSettings"));
      on("cbTitle", "change", () => {
        try{
          try{ syncToggleVisualById("cbTitle"); }catch(e){}
          const v = !!$("cbTitle").checked;
          if(state && state.display_options){ state.display_options.show_title = v; }
          setStatus("标题: " + (v ? "开" : "关"));
          try{ probeNextFrame("标题开关"); }catch(e){}
          requestRerenderAllCharts("标题重绘");
          schedulePreferencesSave();
        }catch(e){}
      });
      on("cbLegend", "change", () => {
        try{
          try{ syncToggleVisualById("cbLegend"); }catch(e){}
          const v = !!$("cbLegend").checked;
          if(state && state.display_options){ state.display_options.show_legend = v; }
          setStatus("图例: " + (v ? "开" : "关"));
          try{ probeNextFrame("图例开关"); }catch(e){}
          requestRerenderAllCharts("图例重绘");
          schedulePreferencesSave();
        }catch(e){}
      });
      on("cbAnim", "change", () => {
        try{
          try{ syncToggleVisualById("cbAnim"); }catch(e){}
          const v = !!$("cbAnim").checked;
          if(state && state.display_options){ state.display_options.enable_animation = v; }
          setStatus("动画: " + (v ? "开" : "关"));
          try{ probeNextFrame("动画开关"); }catch(e){}
          requestRerenderAllCharts("动画重绘");
          schedulePreferencesSave();
        }catch(e){}
      });
      on("cbPauseRefresh", "change", () => {
        try{
          try{ syncToggleVisualById("cbPauseRefresh"); }catch(e){}
          const v = !!$("cbPauseRefresh").checked;
          if(state && state.display_options){ state.display_options.pause_refresh_on_mouse_leave = v; }
          setStatus("离开暂停刷新: " + (v ? "开" : "关"));
          if(!v){
            try{ stopAllHoverRefresh(); }catch(e){}
          }else{
            for(const cid of chartsById.keys()){
              if(isChartActive(cid)){
                try{ startHoverRefresh(cid); }catch(e){}
              }
            }
          }
          for(const cid of chartsById.keys()){
            try{ syncChartRefreshState(cid); }catch(e){}
          }
          schedulePreferencesSave();
        }catch(e){}
      });
      on("cbIgnoreEmptyDates", "change", () => {
        try{
          try{ syncToggleVisualById("cbIgnoreEmptyDates"); }catch(e){}
          const v = !!$("cbIgnoreEmptyDates").checked;
          if(state && state.display_options){ state.display_options.ignore_empty_dates = v; }
          setStatus("忽略无图片日期: " + (v ? "开" : "关"));
          requestRerenderAllCharts("日期补零切换");
          schedulePreferencesSave();
        }catch(e){}
      });
      on("cbGpu", "change", () => {
        try{ syncToggleVisualById("cbGpu"); }catch(e){}
        try{ setStatus("GPU: " + ($("cbGpu").checked ? "开" : "关")); }catch(e){}
        try{ schedulePreferencesSave(); }catch(e){}
      });
      on("cbWatermark", "change", () => {
        try{
          try{ syncToggleVisualById("cbWatermark"); }catch(e){}
          watermarkOn = !!$("cbWatermark").checked;
          if(state && state.display_options){ state.display_options.watermark_enabled = watermarkOn; }
          setStatus("水印: " + (watermarkOn ? "开" : "关"));
          try{ probeNextFrame("水印开关"); }catch(e){}
          try{ schedulePageWatermark(); }catch(e){}
          schedulePreferencesSave();
        }catch(e){}
      });
      on("themeSelect", "change", () => { try{ schedulePreferencesSave(); }catch(e){}; });
      on("fontSize", "input", () => { try{ schedulePreferencesSave(); }catch(e){}; });
      on("wmText", "input", () => {
        try{
          watermarkText = String($("wmText").value || "").trim();
          schedulePageWatermark();
          schedulePreferencesSave();
        }catch(e){}
      });
      on("wmSize", "input", () => {
        try{
          watermarkFontSize = clamp(Number($("wmSize").value || 22), 10, 64);
          schedulePageWatermark();
          schedulePreferencesSave();
        }catch(e){}
      });

      window.addEventListener("resize", () => {
        for(const inst of chartViews.values()){
          try{ inst.resize(); }catch(e){}
        }
        try{ schedulePageWatermark(); }catch(e){}
        try{ expandDeskIfNeeded(); }catch(e){}
      });
      
      // 初始化拖拽空白处移动功能
      try{ initPanning(); }catch(e){}
      
      // 页面关闭前保存图表位置
      window.addEventListener("beforeunload", (e) => {
        try{
          if(typeof saveAllChartLayouts === 'function'){
            saveAllChartLayouts();
          }
        }catch(ex){}
      });
    }

    (async function(){
      try{
        document.addEventListener("contextmenu", (e) => { e.preventDefault(); }, {capture:true});
      }catch(e){}
      try{
        document.addEventListener("wheel", (e) => {
          if(e.ctrlKey){ e.preventDefault(); }
        }, {passive:false, capture:true});
      }catch(e){}
      try{
      }catch(e){}
      try{ setEditMode(false); }catch(e){}
      try{ upgradeAllSelects(); }catch(e){}
      try{ wireEvents(); }catch(e){ try{ setStatus("事件绑定失败"); }catch(ex){} }

      try{
        await ensureBridge();
      }catch(e){
        try{ setStatus("桥接失败"); }catch(ex){}
        return;
      }
      try{
        await bootstrap();
      }catch(e){
        try{ setStatus("数据加载失败"); }catch(ex){}
      }
    })();
  </script>
</body>
</html>
"""
    html = html.replace("__REGISTER_CODE__", register_code or "")
    html = html.replace("__THEME_OPTS__", theme_opts or "")
    html = html.replace("__THEME_UI__", json.dumps(theme_ui or {}, ensure_ascii=False))
    return html
