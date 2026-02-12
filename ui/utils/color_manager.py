import json
import os
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypedDict

from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtGui import QColor


_BUILTIN_FACTORY_COLOR_CONFIG_JSON = """{
  "version": 1,
  "colors": {
    "theme.sidebar": "#2C2C2C",
    "theme.background.primary": "#F5F5F5",
    "theme.background.light": "#FFFFFF",
    "theme.background.dark": "#E7E7E7",
    "theme.primary": "#2196F3",
    "theme.text.dark": "#333333",
    "theme.text.light": "#FFFFFF",
    "theme.preset.dark.sidebar": "#1E242B",
    "theme.preset.dark.primary": "#7FB3A6",
    "theme.preset.dark.background.primary": "#0F1419",
    "theme.preset.dark.background.light": "#1A2128",
    "theme.preset.dark.background.dark": "#0B0F14",
    "theme.preset.dark.text.dark": "#E6EEF5",
    "theme.preset.dark.text.light": "#F7FBFF",
    "theme.preset.summer_beach.sidebar": "#B7D0DB",
    "theme.preset.summer_beach.primary": "#FFE0A3",
    "theme.preset.summer_beach.background.primary": "#FFF3D6",
    "theme.preset.summer_beach.background.light": "#FFF3D6",
    "theme.preset.summer_beach.background.dark": "#F3E4C2",
    "theme.preset.summer_beach.text.dark": "#3A2A1A",
    "theme.preset.summer_beach.text.light": "#FFF6E5",
    "theme.preset.sakura.sidebar": "#D4B9C7",
    "theme.preset.sakura.primary": "#FFC4D4",
    "theme.preset.sakura.background.primary": "#FFF5F8",
    "theme.preset.sakura.background.light": "#FFF5F8",
    "theme.preset.sakura.background.dark": "#F3E6ED",
    "theme.preset.sakura.text.dark": "#3A2430",
    "theme.preset.sakura.text.light": "#FFF1F6",
    "theme.preset.neon.sidebar": "#2B2450",
    "theme.preset.neon.primary": "#33F7FF",
    "theme.preset.neon.background.primary": "#EEF2FF",
    "theme.preset.neon.background.light": "#EEF2FF",
    "theme.preset.neon.background.dark": "#E0E6FF",
    "theme.preset.neon.text.dark": "#1E1B3A",
    "theme.preset.neon.text.light": "#EAF8FF",
    "theme.preset.cyberpunk.sidebar": "#2B2340",
    "theme.preset.cyberpunk.primary": "#FF5AB0",
    "theme.preset.cyberpunk.background.primary": "#F6EEFF",
    "theme.preset.cyberpunk.background.light": "#F6EEFF",
    "theme.preset.cyberpunk.background.dark": "#E6D8FF",
    "theme.preset.cyberpunk.text.dark": "#2A163C",
    "theme.preset.cyberpunk.text.light": "#F5E9FF",
    "theme.preset.ocean.sidebar": "#9CC9D6",
    "theme.preset.ocean.primary": "#9AE6D7",
    "theme.preset.ocean.background.primary": "#E6F7F3",
    "theme.preset.ocean.background.light": "#E6F7F3",
    "theme.preset.ocean.background.dark": "#D4EEE8",
    "theme.preset.ocean.text.dark": "#0E2F2A",
    "theme.preset.ocean.text.light": "#E7FFF8",
    "theme.preset.oriental.sidebar": "#A4B2A6",
    "theme.preset.oriental.primary": "#EAD3AD",
    "theme.preset.oriental.background.primary": "#F6F1E7",
    "theme.preset.oriental.background.light": "#F6F1E7",
    "theme.preset.oriental.background.dark": "#E8DFC9",
    "theme.preset.oriental.text.dark": "#3B2D1C",
    "theme.preset.oriental.text.light": "#F7F2E8",
    "theme.preset.meteor.sidebar": "#8AA1BA",
    "theme.preset.meteor.primary": "#C1D4FF",
    "theme.preset.meteor.background.primary": "#ECF2FF",
    "theme.preset.meteor.background.light": "#ECF2FF",
    "theme.preset.meteor.background.dark": "#DCE7FF",
    "theme.preset.meteor.text.dark": "#1D2C4A",
    "theme.preset.meteor.text.light": "#EAF0FF",
    "theme.preset.tech.sidebar": "#8BAAC0",
    "theme.preset.tech.primary": "#A7E6FA",
    "theme.preset.tech.background.primary": "#EAF7FF",
    "theme.preset.tech.background.light": "#EAF7FF",
    "theme.preset.tech.background.dark": "#D6ECFF",
    "theme.preset.tech.text.dark": "#0E2538",
    "theme.preset.tech.text.light": "#EAF6FF",
    "theme.preset.winter.sidebar": "#96AABC",
    "theme.preset.winter.primary": "#D7F2F3",
    "theme.preset.winter.background.primary": "#F2FAFF",
    "theme.preset.winter.background.light": "#F2FAFF",
    "theme.preset.winter.background.dark": "#E1F1F7",
    "theme.preset.winter.text.dark": "#223544",
    "theme.preset.winter.text.light": "#F2FBFF",
    "theme.preset.new_year.sidebar": "#3D2C2C",
    "theme.preset.new_year.primary": "#E15262",
    "theme.preset.new_year.background.primary": "#FFF1E6",
    "theme.preset.new_year.background.light": "#FFF1E6",
    "theme.preset.new_year.background.dark": "#F5E2D2",
    "theme.preset.new_year.text.dark": "#3B1E1E",
    "theme.preset.new_year.text.light": "#FFF4E6",
    "theme.preset.christmas.sidebar": "#8AA193",
    "theme.preset.christmas.primary": "#4C9650",
    "theme.preset.christmas.background.primary": "#EFF7F0",
    "theme.preset.christmas.background.light": "#EFF7F0",
    "theme.preset.christmas.background.dark": "#DEEADF",
    "theme.preset.christmas.text.dark": "#1E2F24",
    "theme.preset.christmas.text.light": "#F1FFF4",
    "theme.preset.aurora.sidebar": "#8BB3C2",
    "theme.preset.aurora.primary": "#C7FBFF",
    "theme.preset.aurora.background.primary": "#E7FBFF",
    "theme.preset.aurora.background.light": "#E7FBFF",
    "theme.preset.aurora.background.dark": "#D6F4FF",
    "theme.preset.aurora.text.dark": "#113043",
    "theme.preset.aurora.text.light": "#E6FFFE",
    "theme.preset.dusk_forest.sidebar": "#2E3F36",
    "theme.preset.dusk_forest.primary": "#9BC89A",
    "theme.preset.dusk_forest.background.primary": "#EEF6EE",
    "theme.preset.dusk_forest.background.light": "#EEF6EE",
    "theme.preset.dusk_forest.background.dark": "#DCE9DC",
    "theme.preset.dusk_forest.text.dark": "#223529",
    "theme.preset.dusk_forest.text.light": "#EAF5EA",
    "theme.preset.amber_night.sidebar": "#3D3025",
    "theme.preset.amber_night.primary": "#FFB34D",
    "theme.preset.amber_night.background.primary": "#FFF4E5",
    "theme.preset.amber_night.background.light": "#FFF4E5",
    "theme.preset.amber_night.background.dark": "#F3E2C8",
    "theme.preset.amber_night.text.dark": "#3B2817",
    "theme.preset.amber_night.text.light": "#FFF3E0",
    "theme.preset.coral_reef.sidebar": "#C3A3A8",
    "theme.preset.coral_reef.primary": "#FFB3B9",
    "theme.preset.coral_reef.background.primary": "#FFF0F0",
    "theme.preset.coral_reef.background.light": "#FFF0F0",
    "theme.preset.coral_reef.background.dark": "#F3DADA",
    "theme.preset.coral_reef.text.dark": "#3A1E21",
    "theme.preset.coral_reef.text.light": "#FFF1F1",
    "theme.preset.mint_breeze.sidebar": "#6CB1B6",
    "theme.preset.mint_breeze.primary": "#90DDD6",
    "theme.preset.mint_breeze.background.primary": "#EAFBF8",
    "theme.preset.mint_breeze.background.light": "#EAFBF8",
    "theme.preset.mint_breeze.background.dark": "#D7F2EE",
    "theme.preset.mint_breeze.text.dark": "#1E3A3A",
    "theme.preset.mint_breeze.text.light": "#F6FFFD",
    "theme.preset.morning_mist.sidebar": "#8AA6C2",
    "theme.preset.morning_mist.primary": "#B5D5EE",
    "theme.preset.morning_mist.background.primary": "#F2F7FD",
    "theme.preset.morning_mist.background.light": "#F2F7FD",
    "theme.preset.morning_mist.background.dark": "#E1ECF6",
    "theme.preset.morning_mist.text.dark": "#223449",
    "theme.preset.morning_mist.text.light": "#F7FBFF",
    "theme.preset.black_orange.sidebar": "#0F1419",
    "theme.preset.black_orange.primary": "#FF8A00",
    "theme.preset.black_orange.background.primary": "#11161C",
    "theme.preset.black_orange.background.light": "#1A2028",
    "theme.preset.black_orange.background.dark": "#0B0F14",
    "theme.preset.black_orange.text.dark": "#E8EDF2",
    "theme.preset.black_orange.text.light": "#FFFFFF",
    "settings.shortcut_table.background": "#FFFFFF",
    "settings.shortcut_table.gridline": "#F0F0F0",
    "settings.shortcut_table.header.background": "#F5F5F5",
    "settings.shortcut_table.header.text": "#555555",
    "settings.shortcut_table.header.border": "#D0D0D0",
    "settings.shortcut_table.row.hover_background": "#EEF3FA",
    "settings.shortcut_table.row.hover_border": "#D7E3F5",
    "settings.shortcut_input.border": "#CFCFCF",
    "settings.shortcut_input.hover_border": "#B8B8B8",
    "settings.shortcut_input.text": "#333333",
    "settings.shortcut_input.selection_background": "#CFE3FF",
    "settings.shortcut_input.selection_text": "#1A1A1A",
    "settings.shortcut_input.recording.background": "#E6F0FF",
    "settings.shortcut_input.recording.border": "#2D7FF9",
    "settings.shortcut_input.recording.text": "#1F5FBF",
    "settings.shortcut_reset.text": "#2196F3",
    "settings.shortcut_reset.border": "#2196F3",
    "settings.shortcut_reset.hover_background": "#2196F31A",
    "settings.shortcut_reset.hover_text": "#FFFFFF",
    "guide.nav.prev.background": "#FFFFFFCC",
    "guide.path_container.background": "#FFFFFFCC",
    "guide.background.top": "#2196F3",
    "guide.background.bottom": "#F5F5F5",
    "image_detail.back_button.hover_background": "#FFFFFF28",
    "image_detail.compare_button.active_background": "#FFFFFF32",
    "image_detail.splitter.handle_background": "#444444",
    "image_detail.nav_button.background": "#00000032",
    "image_detail.nav_button.hover_background": "#00000064",
    "image_detail.overlay.background": "#00000064",
    "image_detail.overlay.hover_background": "#FFFFFF1E",
    "image_detail.thumbnail.base_background": "#2C2C2C",
    "image_detail.thumbnail_strip.background": "#121212",
    "image_detail.thumbnail_strip.border_top": "#2A2A2A",
    "image_detail.thumbnail_strip.scrollbar.background": "#1C1C1C",
    "image_detail.thumbnail_strip.scrollbar.handle": "#3A3A3A",
    "image_detail.toolbar.button.hover_background": "#FFFFFF1E",
    "image_detail.toolbar.button.pressed_background": "#FFFFFF32",
    "loading_overlay.container.background": "#000000B4",
    "settings.rebuild_db.disabled_text": "#FFFFFFB4",
    "thumbnail_grid.spray_overlay.background": "#D2D2D238",
    "thumbnail_grid.spray_overlay.border": "#AAAAAA99",
    "zoomable_scroll_area.selection_overlay.background": "#2196F333",
    "page.background.primary": "#000000",
    "popup.border.primary": "#D0D0D0",
    "tooltip.background": "#FFFFFF",
    "tooltip.text": "#000000",
    "tooltip.border": "#000000",
    "notification.toast.background": "#999999",
    "border.subject_rect": "#F50F0F",
    "popup.header.close_button.hover_background": "#EDEFF2",
    "tag.delete.hover_background": "#FF000033",
    "preview.favorite.active": "#E74C3C"
  },
  "aliases": {
    "image_library.startup_mask.background": "theme.background.primary",
    "library_page.startup_mask.background": "theme.background.primary",
    "image_detail.toolbar.background": "theme.sidebar",
    "theme.background": "theme.background.primary",
    "theme.popup": "theme.background.light",
    "popup.background.primary": "theme.background.light",
    "settings.shortcut_input.background": "theme.background.light",
    "guide.nav.prev.hover_background": "theme.background.light",
    "popup.text.primary": "theme.text.dark",
    "popup.header.background": "theme.sidebar",
    "popup.header.text": "theme.text.light",
    "notification.toast.text": "theme.text.light",
    "text.primary": "theme.text.light"
  }
}"""


class ColorCategory(str, Enum):
    PAGE_BACKGROUND = "page_background"
    NOTIFICATION_BACKGROUND = "notification_background"
    POPUP_BACKGROUND = "popup_background"
    TEXT = "text"
    BORDER = "border"
    BUTTON = "button"
    OTHER = "other"

class ColorToken(str, Enum):
    PAGE_BACKGROUND_PRIMARY = "page.background.primary"
    POPUP_BACKGROUND_PRIMARY = "popup.background.primary"
    NOTIFICATION_TOAST_BACKGROUND = "notification.toast.background"
    NOTIFICATION_TOAST_TEXT = "notification.toast.text"
    TEXT_PRIMARY = "text.primary"
    BORDER_SUBJECT_RECT = "border.subject_rect"


class ColorConfigV1(TypedDict, total=False):
    version: int
    colors: Dict[str, str]
    aliases: Dict[str, str]


@dataclass(frozen=True)
class ColorFinding:
    file_path: str
    line_no: int
    raw: str
    normalized: str
    category: ColorCategory
    line_text: str


_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_RGB_RE = re.compile(r"\brgba?\(\s*([^)]+)\)")
_HSL_RE = re.compile(r"\bhsla?\(\s*([^)]+)\)")


def _clamp_int(v: int, lo: int = 0, hi: int = 255) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _float01_to_int255(v: float) -> int:
    if v <= 0:
        return 0
    if v >= 1:
        return 255
    return int(round(v * 255))


def _parse_css_number(token: str) -> Optional[float]:
    if token is None:
        return None
    t = str(token).strip()
    if not t:
        return None
    try:
        if t.endswith("%"):
            return float(t[:-1].strip()) / 100.0
        return float(t)
    except Exception:
        return None


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return "#{:02X}{:02X}{:02X}".format(_clamp_int(r), _clamp_int(g), _clamp_int(b))


def _rgba_to_hex8(r: int, g: int, b: int, a: int) -> str:
    return "#{:02X}{:02X}{:02X}{:02X}".format(_clamp_int(r), _clamp_int(g), _clamp_int(b), _clamp_int(a))


def _hsl_to_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
    h = (h % 360.0) / 360.0
    s = max(0.0, min(1.0, s))
    l = max(0.0, min(1.0, l))

    def hue2rgb(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    if s == 0:
        v = int(round(l * 255))
        return v, v, v

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r = hue2rgb(p, q, h + 1 / 3)
    g = hue2rgb(p, q, h)
    b = hue2rgb(p, q, h - 1 / 3)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def normalize_color(value: str) -> Optional[str]:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    low = raw.lower()
    if low in ("transparent",):
        return "transparent"
    if low in ("white", "black", "red", "green", "blue", "gray", "grey"):
        name_map = {
            "white": "#FFFFFF",
            "black": "#000000",
            "red": "#FF0000",
            "green": "#00FF00",
            "blue": "#0000FF",
            "gray": "#808080",
            "grey": "#808080",
        }
        return name_map.get(low)

    m = _HEX_RE.search(raw)
    if m:
        hex_part = m.group(1)
        if len(hex_part) in (3, 4):
            expanded = "".join([c * 2 for c in hex_part])
            hex_part = expanded
        if len(hex_part) == 6:
            return f"#{hex_part.upper()}"
        if len(hex_part) == 8:
            return f"#{hex_part.upper()}"

    m = _RGB_RE.search(raw)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) < 3:
            return None
        r = _parse_css_number(parts[0])
        g = _parse_css_number(parts[1])
        b = _parse_css_number(parts[2])
        if r is None or g is None or b is None:
            return None
        rr = int(round(r * 255)) if 0 <= r <= 1 and "." in parts[0] else int(round(r))
        gg = int(round(g * 255)) if 0 <= g <= 1 and "." in parts[1] else int(round(g))
        bb = int(round(b * 255)) if 0 <= b <= 1 and "." in parts[2] else int(round(b))
        if len(parts) >= 4:
            a = _parse_css_number(parts[3])
            if a is None:
                return None
            aa = _float01_to_int255(a) if 0 <= a <= 1 else int(round(a))
            return _rgba_to_hex8(rr, gg, bb, aa)
        return _rgb_to_hex(rr, gg, bb)

    m = _HSL_RE.search(raw)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) < 3:
            return None
        h = _parse_css_number(parts[0])
        s = _parse_css_number(parts[1])
        l = _parse_css_number(parts[2])
        if h is None or s is None or l is None:
            return None
        if 0 <= s <= 1 and not parts[1].endswith("%"):
            s01 = s
        else:
            s01 = s if 0 <= s <= 1 else max(0.0, min(1.0, s))
        if 0 <= l <= 1 and not parts[2].endswith("%"):
            l01 = l
        else:
            l01 = l if 0 <= l <= 1 else max(0.0, min(1.0, l))
        r, g, b = _hsl_to_rgb(h, s01, l01)
        if len(parts) >= 4:
            a = _parse_css_number(parts[3])
            if a is None:
                return None
            aa = _float01_to_int255(a) if 0 <= a <= 1 else int(round(a))
            return _rgba_to_hex8(r, g, b, aa)
        return _rgb_to_hex(r, g, b)

    return None


def _guess_category(file_path: str, line_text: str) -> ColorCategory:
    p = (file_path or "").replace("\\", "/").lower()
    t = (line_text or "").lower()

    if "notification" in p or "toast" in t or "warning" in t or "error" in t:
        return ColorCategory.NOTIFICATION_BACKGROUND
    if "message_box" in p or "dialog" in p or "popup" in t:
        return ColorCategory.POPUP_BACKGROUND
    if "background" in t or "background-color" in t:
        return ColorCategory.PAGE_BACKGROUND
    if "border" in t:
        return ColorCategory.BORDER
    if "button" in t or ":hover" in t or ":pressed" in t:
        return ColorCategory.BUTTON
    if "color" in t or "text" in t:
        return ColorCategory.TEXT
    return ColorCategory.OTHER


class ColorManager:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "ColorManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        from utils.paths import PathManager
        pm = PathManager.instance()
        self._factory_path = str(pm.get_app_data_path() / "colors.json")
        if config_path is None:
            config_path = str(pm.get_user_colors_path())

        self._config_path = config_path
        self._colors: Dict[str, str] = {}
        self._aliases: Dict[str, str] = {}
        self._listeners: List[Callable[[], None]] = []
        self._watch_thread = None
        self._stop_event = threading.Event()
        self._last_mtime: Optional[float] = None

        self.reload()
        self._start_watcher()

    @property
    def config_path(self) -> str:
        return self._config_path

    @property
    def factory_path(self) -> str:
        return self._factory_path

    def load_config_data(self) -> Tuple[bool, Dict[str, str], Dict[str, str], int]:
        data = None
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            elif os.path.exists(self._factory_path):
                with open(self._factory_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = json.loads(_BUILTIN_FACTORY_COLOR_CONFIG_JSON)
        except Exception:
            try:
                data = json.loads(_BUILTIN_FACTORY_COLOR_CONFIG_JSON)
            except Exception:
                data = None

        ok, colors, aliases = self._validate_and_normalize_config(data)
        if not ok:
            return False, {}, {}, 1
        try:
            version = int((data or {}).get("version", 1))
        except Exception:
            version = 1
        return True, colors, aliases, version

    def register_listener(self, callback: Callable[[], None]) -> None:
        if not callable(callback):
            return
        self._listeners.append(callback)

    def get(self, token: str, default: Optional[str] = None) -> str:
        key = (token or "").strip()
        if not key:
            return default or "#000000"
        for _ in range(10):
            if key in self._aliases:
                key = str(self._aliases.get(key) or "").strip()
                if not key:
                    break
            else:
                break
        v = self._colors.get(key)
        if v:
            return v
        return default or "#000000"

    def qcolor(self, token: str, default: Optional[str] = None) -> QColor:
        v = self.get(token, default=default)
        if v == "transparent":
            c = QColor(0, 0, 0, 0)
            return c
        if isinstance(v, str) and v.startswith("#") and len(v) == 9:
            try:
                r = int(v[1:3], 16)
                g = int(v[3:5], 16)
                b = int(v[5:7], 16)
                a = int(v[7:9], 16)
                return QColor(r, g, b, a)
            except Exception:
                return QColor(default or "#000000")
        return QColor(v)

    def to_qss_color(self, token: str, default: Optional[str] = None) -> str:
        v = self.get(token, default=default)
        if isinstance(v, str) and v.startswith("#") and len(v) == 9:
            try:
                r = int(v[1:3], 16)
                g = int(v[3:5], 16)
                b = int(v[5:7], 16)
                a = int(v[7:9], 16) / 255.0
                return "rgba({}, {}, {}, {:.3f})".format(r, g, b, a)
            except Exception:
                return default or "#000000"
        return v

    def reload(self) -> bool:
        ok, colors, aliases, _version = self.load_config_data()
        if not ok:
            return False
        self._colors = colors
        self._aliases = aliases
        return True

    def stop(self) -> None:
        self._stop_event.set()
        t = self._watch_thread
        if t and t.is_alive():
            try:
                t.join(timeout=1.0)
            except Exception:
                pass

    def _start_watcher(self) -> None:
        if self._watch_thread and self._watch_thread.is_alive():
            return

        def notify_listeners():
            for cb in list(self._listeners):
                try:
                    cb()
                except Exception:
                    pass

        def loop():
            while not self._stop_event.is_set():
                try:
                    mtime = None
                    if os.path.exists(self._factory_path):
                        mtime = os.path.getmtime(self._factory_path)
                    if os.path.exists(self._config_path):
                        m2 = os.path.getmtime(self._config_path)
                        if mtime is None or m2 > mtime:
                            mtime = m2
                except Exception:
                    mtime = None

                if mtime is not None and self._last_mtime is not None and mtime > self._last_mtime:
                    if self.reload():
                        app = QCoreApplication.instance()
                        if app is not None:
                            try:
                                QTimer.singleShot(0, notify_listeners)
                            except Exception:
                                notify_listeners()
                        else:
                            notify_listeners()

                self._last_mtime = mtime
                time.sleep(0.5)

        self._watch_thread = threading.Thread(target=loop, daemon=True)
        self._watch_thread.start()

    def _default_colors(self) -> Dict[str, str]:
        return {
            "page.background.primary": "#000000",
            "theme.background.primary": "#F5F5F5",
            "theme.background.light": "#FFFFFF",
            "theme.background.dark": "#E7E7E7",
            "text.primary": "#FFFFFF",
            "notification.toast.background": "#282828DC",
            "notification.toast.text": "#FFFFFF",
            "border.subject_rect": "#F50F0F",
            "settings.shortcut_table.background": "#FFFFFF",
            "settings.shortcut_table.gridline": "#F0F0F0",
            "settings.shortcut_table.header.background": "#F5F5F5",
            "settings.shortcut_table.header.text": "#555555",
            "settings.shortcut_table.header.border": "#D0D0D0",
            "settings.shortcut_table.row.hover_background": "#EEF3FA",
            "settings.shortcut_table.row.hover_border": "#D7E3F5",
            "settings.shortcut_input.background": "#FFFFFF",
            "settings.shortcut_input.border": "#CFCFCF",
            "settings.shortcut_input.hover_border": "#B8B8B8",
            "settings.shortcut_input.text": "#333333",
            "settings.shortcut_input.selection_background": "#CFE3FF",
            "settings.shortcut_input.selection_text": "#1A1A1A",
            "settings.shortcut_input.recording.background": "#E6F0FF",
            "settings.shortcut_input.recording.border": "#2D7FF9",
            "settings.shortcut_input.recording.text": "#1F5FBF",
            "settings.shortcut_reset.text": "#2196F3",
            "settings.shortcut_reset.border": "#2196F3",
            "settings.shortcut_reset.hover_background": "#2196F3",
            "settings.shortcut_reset.hover_text": "#FFFFFF",
        }

    def _validate_and_normalize_config(self, data: object) -> Tuple[bool, Dict[str, str], Dict[str, str]]:
        if not isinstance(data, dict):
            return False, {}, {}

        version = data.get("version")
        if version not in (1, "1"):
            return False, {}, {}

        raw_colors = data.get("colors") or {}
        raw_aliases = data.get("aliases") or {}
        if not isinstance(raw_colors, dict) or not isinstance(raw_aliases, dict):
            return False, {}, {}

        colors: Dict[str, str] = {}
        for k, v in raw_colors.items():
            key = str(k).strip()
            if not key:
                return False, {}, {}
            nv = normalize_color(str(v))
            if nv is None:
                return False, {}, {}
            colors[key] = nv

        aliases: Dict[str, str] = {}
        for k, v in raw_aliases.items():
            key = str(k).strip()
            val = str(v).strip()
            if not key or not val:
                return False, {}, {}
            aliases[key] = val

        return True, colors, aliases

    @staticmethod
    def scan_project(
        root_dir: str,
        include_globs: Sequence[str] = (".py", ".qss", ".css"),
        exclude_dirs: Sequence[str] = ("assets", "exiftool_files", ".venv", "__pycache__", ".git", "data"),
    ) -> List[ColorFinding]:
        findings: List[ColorFinding] = []
        root_dir = os.path.abspath(root_dir)

        for dirpath, dirnames, filenames in os.walk(root_dir):
            rel = os.path.relpath(dirpath, root_dir).replace("\\", "/")
            if rel == ".":
                rel = ""
            parts = [p for p in rel.split("/") if p]
            if any(p in set(exclude_dirs) for p in parts):
                dirnames[:] = []
                continue

            for fn in filenames:
                if not any(fn.lower().endswith(ext) for ext in include_globs):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, start=1):
                            for m in _HEX_RE.finditer(line):
                                raw = m.group(0)
                                norm = normalize_color(raw)
                                if not norm:
                                    continue
                                cat = _guess_category(fp, line)
                                findings.append(ColorFinding(fp, i, raw, norm, cat, line.rstrip("\n")))
                            for m in _RGB_RE.finditer(line):
                                raw = m.group(0)
                                norm = normalize_color(raw)
                                if not norm:
                                    continue
                                cat = _guess_category(fp, line)
                                findings.append(ColorFinding(fp, i, raw, norm, cat, line.rstrip("\n")))
                            for m in _HSL_RE.finditer(line):
                                raw = m.group(0)
                                norm = normalize_color(raw)
                                if not norm:
                                    continue
                                cat = _guess_category(fp, line)
                                findings.append(ColorFinding(fp, i, raw, norm, cat, line.rstrip("\n")))
                except Exception:
                    continue

        return findings

    @staticmethod
    def generate_config_from_findings(findings: Iterable[ColorFinding]) -> ColorConfigV1:
        category_prefix = {
            ColorCategory.PAGE_BACKGROUND: "page.background",
            ColorCategory.NOTIFICATION_BACKGROUND: "notification.background",
            ColorCategory.POPUP_BACKGROUND: "popup.background",
            ColorCategory.TEXT: "text",
            ColorCategory.BORDER: "border",
            ColorCategory.BUTTON: "button",
            ColorCategory.OTHER: "other",
        }

        buckets: Dict[ColorCategory, Dict[str, str]] = {}
        for f in findings:
            buckets.setdefault(f.category, {})
            buckets[f.category][f.normalized] = f.normalized

        colors: Dict[str, str] = {}
        for cat, cmap in buckets.items():
            prefix = category_prefix.get(cat, "other")
            uniq = sorted(set(cmap.values()))
            for idx, c in enumerate(uniq, start=1):
                token = f"{prefix}.{idx:02d}"
                colors[token] = c

        if "page.background.primary" not in colors:
            colors["page.background.primary"] = "#000000"
        if "text.primary" not in colors:
            colors["text.primary"] = "#FFFFFF"

        return {"version": 1, "colors": colors, "aliases": {}}
