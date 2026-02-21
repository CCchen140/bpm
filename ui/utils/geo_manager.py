import threading
import urllib.parse
import urllib.request
import re
import json
import math
import os
import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable
from PyQt6.QtGui import QValidator
from utils.setting.settings_manager import SettingsManager
from utils.log_manager import LogManager

try:
    from geopy.geocoders import Nominatim
    from geopy.adapters import RequestsAdapter
    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False

class _TileProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) != 5 or parts[0] != "tiles":
                self.send_response(404)
                self._send_cors_headers()
                self.end_headers()
                return

            style_id = parts[1]
            z = int(parts[2])
            x = int(parts[3])
            y_part = parts[4]
            y_str = y_part.split(".")[0]
            y = int(y_str)

            templates = getattr(self.server, "style_templates", {}).get(style_id) or []
            if not templates:
                self.send_response(404)
                self._send_cors_headers()
                self.end_headers()
                return

            cache_key = f"{style_id}/{z}/{x}/{y}"
            cache = getattr(self.server, "tile_cache", None)
            if isinstance(cache, dict) and cache_key in cache:
                payload, content_type = cache[cache_key]
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(payload)
                return

            last_err = None
            for tpl in templates:
                url = tpl.format(z=z, x=x, y=y)
                try:
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "BirdPictureManager/1.0 (tile-proxy)",
                            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        },
                        method="GET",
                    )
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        payload = resp.read()
                        content_type = resp.headers.get_content_type() or "image/png"
                    if isinstance(cache, dict):
                        if len(cache) > 512:
                            try:
                                cache.clear()
                            except Exception:
                                pass
                        cache[cache_key] = (payload, content_type)
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                except Exception as e:
                    last_err = e
                    continue

            self.send_response(502)
            self._send_cors_headers()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"upstream error: {last_err}".encode("utf-8", errors="replace"))
        except Exception:
            try:
                self.send_response(500)
                self._send_cors_headers()
                self.end_headers()
            except Exception:
                pass


class GeocodeSignals(QObject):
    success = pyqtSignal(float, float, str)
    error = pyqtSignal(str)


class GeocodeRunnable(QRunnable):
    def __init__(self, query: str, signals: GeocodeSignals):
        super().__init__()
        self.query = query
        self.signals = signals

    def run(self):
        try:
            q = (self.query or "").strip()
            if not q:
                self.signals.error.emit("请输入地理位置")
                return

            result = GeoInfoManager.instance().geocode(q)
            if result:
                lat, lon, display_name = result
                self.signals.success.emit(lat, lon, display_name)
            else:
                self.signals.error.emit("未找到对应地点或服务不可用")

        except Exception as e:
            self.signals.error.emit(f"搜索失败: {e}")


class ReverseGeocodeSignals(QObject):
    success = pyqtSignal(str)
    error = pyqtSignal(str)


class ReverseGeocodeRunnable(QRunnable):
    def __init__(self, lat: float, lng: float, signals: ReverseGeocodeSignals):
        super().__init__()
        self.lat = lat
        self.lng = lng
        self.signals = signals

    def run(self):
        try:
            result = GeoInfoManager.instance().reverse_geocode(self.lat, self.lng)
            if result:
                self.signals.success.emit(result)
            else:
                self.signals.error.emit("未找到地址信息")
        except Exception as e:
            self.signals.error.emit(f"获取地址失败: {e}")


class DmsOrDecimalValidator(QValidator):
    def __init__(self, max_abs: float, parent=None):
        super().__init__(parent)
        self._max_abs = float(max_abs)
        self._allowed_chars_re = re.compile(r'^[\d\.\-\s°deg\'"″’′”]*$', re.IGNORECASE)
        self._dms_re = re.compile(
            r'^\s*(?P<deg>-?\d+)\s*(?:deg|°)\s*(?P<min>\d+(?:\.\d+)?)\s*(?:\'|’|′)\s*(?P<sec>\d+(?:\.\d+)?)\s*(?:"|″|”)?\s*$',
            re.IGNORECASE,
        )

    def validate(self, input_str: str, pos: int):
        _ = pos
        s = (input_str or "").strip()
        if not s:
            return (QValidator.State.Intermediate, input_str, pos)

        try:
            v = float(s)
            if abs(v) <= self._max_abs:
                return (QValidator.State.Acceptable, input_str, pos)
            return (QValidator.State.Invalid, input_str, pos)
        except Exception:
            pass

        m = self._dms_re.fullmatch(s)
        if m:
            try:
                deg = int(m.group("deg"))
                minutes = float(m.group("min"))
                seconds = float(m.group("sec"))
            except Exception:
                return (QValidator.State.Invalid, input_str, pos)

            if minutes < 0 or minutes >= 60:
                return (QValidator.State.Invalid, input_str, pos)
            if seconds < 0 or seconds >= 60:
                return (QValidator.State.Invalid, input_str, pos)

            decimal_abs = abs(deg) + (minutes / 60.0) + (seconds / 3600.0)
            if decimal_abs <= self._max_abs:
                return (QValidator.State.Acceptable, input_str, pos)
            return (QValidator.State.Invalid, input_str, pos)

        if self._allowed_chars_re.fullmatch(s):
            return (QValidator.State.Intermediate, input_str, pos)
        return (QValidator.State.Invalid, input_str, pos)


class GeoInfoManager(QObject):
    _instance = None
    _tile_proxy_server = None
    _tile_proxy_lock = threading.Lock()

    MAP_STYLES = [
        {
            "id": "osm_hot",
            "title": "🎨 OSM HOT",
            "name": "OSM HOT",
            "urls": [
                "https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
                "https://b.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
                "https://c.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
                "http://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
                "http://b.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
                "http://c.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "osm_standard",
            "title": "🗺️ OpenStreetMap 标准",
            "name": "OpenStreetMap",
            "urls": [
                "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "http://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "http://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
                "http://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "osm_de",
            "title": "🗺️ OpenStreetMap DE",
            "name": "OpenStreetMap DE",
            "urls": [
                "https://tile.openstreetmap.de/{z}/{x}/{y}.png",
                "http://tile.openstreetmap.de/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "osm_fr",
            "title": "🗺️ OpenStreetMap FR",
            "name": "OpenStreetMap FR",
            "urls": [
                "https://a.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
                "https://b.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
                "https://c.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
                "http://a.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
                "http://b.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
                "http://c.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "carto_dark",
            "title": "🌙 CartoDB Dark",
            "name": "CartoDB Dark",
            "urls": [
                "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "http://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "http://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
                "http://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "carto_light",
            "title": "☀️ CartoDB Light",
            "name": "CartoDB Light",
            "urls": [
                "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "http://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "http://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
                "http://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "opentopomap",
            "title": "⛰️ OpenTopoMap（地形图）",
            "name": "OpenTopoMap",
            "urls": [
                "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
                "https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
                "https://c.tile.opentopomap.org/{z}/{x}/{y}.png",
                "http://a.tile.opentopomap.org/{z}/{x}/{y}.png",
                "http://b.tile.opentopomap.org/{z}/{x}/{y}.png",
                "http://c.tile.opentopomap.org/{z}/{x}/{y}.png",
            ],
            "maxzoom": 17,
        },
        {
            "id": "cyclosm",
            "title": "🚴 CyclOSM（自行车地图）",
            "name": "CyclOSM",
            "urls": [
                "https://a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
                "https://b.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
                "https://c.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
                "http://a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
                "http://b.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
                "http://c.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
            ],
            "maxzoom": 20,
        },
        {
            "id": "carto_voyager",
            "title": "🌈 CartoDB Voyager",
            "name": "CartoDB Voyager",
            "urls": [
                "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                "http://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                "http://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
                "http://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "opencyclemap",
            "title": "🚵 OpenCycleMap（地形+自行车）",
            "name": "OpenCycleMap",
            "urls": [
                "https://a.tile.opencyclemap.org/cycle/{z}/{x}/{y}.png",
                "https://b.tile.opencyclemap.org/cycle/{z}/{x}/{y}.png",
                "https://c.tile.opencyclemap.org/cycle/{z}/{x}/{y}.png",
                "http://a.tile.opencyclemap.org/cycle/{z}/{x}/{y}.png",
                "http://b.tile.opencyclemap.org/cycle/{z}/{x}/{y}.png",
                "http://c.tile.opencyclemap.org/cycle/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "stamen_terrain",
            "title": "⛰️ Stamen Terrain（地形）",
            "name": "Stamen Terrain",
            "urls": [
                "https://stamen-tiles-a.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
                "https://stamen-tiles-b.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
                "https://stamen-tiles-c.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
                "http://stamen-tiles-a.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
                "http://stamen-tiles-b.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
                "http://stamen-tiles-c.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
            ],
            "maxzoom": 18,
        },
        {
            "id": "stamen_toner",
            "title": "⚫ Stamen Toner（黑白）",
            "name": "Stamen Toner",
            "urls": [
                "https://stamen-tiles-a.a.ssl.fastly.net/toner/{z}/{x}/{y}.png",
                "https://stamen-tiles-b.a.ssl.fastly.net/toner/{z}/{x}/{y}.png",
                "https://stamen-tiles-c.a.ssl.fastly.net/toner/{z}/{x}/{y}.png",
                "http://stamen-tiles-a.a.ssl.fastly.net/toner/{z}/{x}/{y}.png",
                "http://stamen-tiles-b.a.ssl.fastly.net/toner/{z}/{x}/{y}.png",
                "http://stamen-tiles-c.a.ssl.fastly.net/toner/{z}/{x}/{y}.png",
            ],
            "maxzoom": 20,
        },
        {
            "id": "stamen_watercolor",
            "title": "🎨 Stamen Watercolor（水彩）",
            "name": "Stamen Watercolor",
            "urls": [
                "https://stamen-tiles-a.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.jpg",
                "https://stamen-tiles-b.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.jpg",
                "https://stamen-tiles-c.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.jpg",
                "http://stamen-tiles-a.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.jpg",
                "http://stamen-tiles-b.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.jpg",
                "http://stamen-tiles-c.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.jpg",
            ],
            "maxzoom": 18,
        },
        {
            "id": "wikimedia",
            "title": "📚 Wikimedia Maps",
            "name": "Wikimedia",
            "urls": [
                "https://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png",
                "http://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png",
            ],
            "maxzoom": 19,
        },
        {
            "id": "esri_imagery",
            "title": "🛰️ Esri 卫星（无标注影像）",
            "name": "Esri Imagery",
            "urls": [
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "http://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            ],
            "maxzoom": 19,
        },
        {
            "id": "esri_shaded_relief",
            "title": "🏔️ Esri Shaded Relief（阴影地形）",
            "name": "Esri Shaded Relief",
            "urls": [
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}",
                "http://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}",
            ],
            "maxzoom": 13,
        },
        {
            "id": "esri_topo",
            "title": "🗺️ Esri World Topo（地形图）",
            "name": "Esri World Topo",
            "urls": [
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
                "http://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
            ],
            "maxzoom": 19,
        },
        {
            "id": "esri_street",
            "title": "🛣️ Esri World Street（街道图）",
            "name": "Esri World Street",
            "urls": [
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                "http://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
            ],
            "maxzoom": 19,
        },
        {
            "id": "esri_light_gray",
            "title": "🧊 Esri Light Gray（浅灰）",
            "name": "Esri Light Gray",
            "urls": [
                "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                "http://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
            ],
            "maxzoom": 16,
        },
        {
            "id": "esri_dark_gray",
            "title": "🌑 Esri Dark Gray（深灰）",
            "name": "Esri Dark Gray",
            "urls": [
                "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                "http://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
            ],
            "maxzoom": 16,
        },
        {
            "id": "gibs_bluemarble",
            "title": "🛰️ NASA GIBS BlueMarble",
            "name": "NASA GIBS BlueMarble",
            "urls": [
                "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief/default/2013-12-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg",
                "http://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief/default/2013-12-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg",
            ],
            "maxzoom": 8,
        },
    ]
    _ALLOWED_STYLE_IDS = {
        "esri_imagery",
        "esri_street",
        "esri_light_gray",
        "esri_dark_gray",
    }
    _tmp_styles = []
    for _s in MAP_STYLES:
        try:
            if str(_s.get("id") or "") in _ALLOWED_STYLE_IDS:
                _tmp_styles.append(_s)
        except Exception:
            continue
    MAP_STYLES = _tmp_styles
    del _tmp_styles
    del _s
    del _ALLOWED_STYLE_IDS

    @classmethod
    def instance(cls):
        """
        获取 GeoInfoManager 的单例实例。
        如果实例不存在，则创建一个新实例。
        
        返回:
            GeoInfoManager: 单例实例
        """
        if not cls._instance:
            cls._instance = GeoInfoManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.api_keys = {
            'gaode': None,
            'baidu': None,
            'tencent': None,
            'tianditu': None,
        }

    def _get_api_key(self, service):
        """获取 API Key，优先从设置中获取高德 Key"""
        if service == 'gaode':
            key = SettingsManager().get("geolocation/gaode_key")
            if key and key.strip():
                return key.strip()
        if service == "tianditu":
            key = SettingsManager().get("geolocation/tianditu_key")
            if key and str(key).strip():
                return str(key).strip()
            else:
                return "6b4610fa57e689d864d4db5f7ee80a14"
        return self.api_keys.get(service)

    @staticmethod
    def _wgs84_to_gcj02(lng, lat):
        """
        WGS84坐标系转GCJ02坐标系（火星坐标系）
        高德地图、腾讯地图使用GCJ02坐标系
        """
        a = 6378245.0  # 长半轴
        ee = 0.00669342162296594323  # 偏心率平方
        
        if GeoInfoManager._out_of_china(lng, lat):
            return lng, lat
            
        dlat = GeoInfoManager._transform_lat(lng - 105.0, lat - 35.0)
        dlng = GeoInfoManager._transform_lng(lng - 105.0, lat - 35.0)
        
        radlat = lat / 180.0 * math.pi
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
        
        mglat = lat + dlat
        mglng = lng + dlng
        return mglng, mglat
    
    @staticmethod
    def _gcj02_to_wgs84(lng, lat):
        """
        GCJ02坐标系转WGS84坐标系
        将高德地图返回的坐标转换为WGS84用于地图显示
        """
        a = 6378245.0  # 长半轴
        ee = 0.00669342162296594323  # 偏心率平方
        
        if GeoInfoManager._out_of_china(lng, lat):
            return lng, lat
            
        dlat = GeoInfoManager._transform_lat(lng - 105.0, lat - 35.0)
        dlng = GeoInfoManager._transform_lng(lng - 105.0, lat - 35.0)
        
        radlat = lat / 180.0 * math.pi
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
        
        mglat = lat + dlat
        mglng = lng + dlng
        
        return lng * 2 - mglng, lat * 2 - mglat

    @staticmethod
    def _transform_lat(lng, lat):
        """纬度转换"""
        ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + \
              0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
        ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 *
                math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(lat * math.pi) + 40.0 *
                math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 *
                math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
        return ret
    
    @staticmethod
    def _transform_lng(lng, lat):
        """经度转换"""
        ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + \
              0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
        ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 *
                math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(lng * math.pi) + 40.0 *
                math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 *
                math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
        return ret

    @staticmethod
    def _out_of_china(lng, lat):
        """判断是否在中国境外"""
        if lng < 72.004 or lng > 137.8347:
            return True
        if lat < 0.8293 or lat > 55.8271:
            return True
        return False

    def geocode(self, query: str) -> tuple[float, float, str] | None:
        """
        地理编码：根据地点名称获取经纬度
        返回: (latitude, longitude, display_name) 或 None
        """
        preferred_service = SettingsManager().get("geolocation/service", "tianditu")
        
        # 定义服务尝试顺序
        services = []
        if preferred_service == "tianditu":
            services = ["tianditu"]
        elif preferred_service == 'gaode':
            services = ['gaode', 'baidu', 'tencent', 'nominatim', 'free']
        else:
            services = ['nominatim', 'free', 'gaode', 'baidu', 'tencent']
        for service in services:
            result = None
            if service == 'gaode':
                result = self._geocode_gaode(query)
            elif service == 'baidu':
                result = self._geocode_baidu(query)
            elif service == 'tencent':
                result = self._geocode_tencent(query)
            elif service == "tianditu":
                result = self._geocode_tianditu(query)
            elif service == 'nominatim':
                result = self._geocode_nominatim(query)
            elif service == 'free':
                result = self._geocode_free_service(query)
                
            if result:
                return result
                
        return None

    def reverse_geocode(self, lat: float, lng: float) -> str | None:
        """
        反向地理编码：根据经纬度获取地址
        返回: 地址字符串 或 None
        """
        preferred_service = SettingsManager().get("geolocation/service", "tianditu")
        
        # 定义服务尝试顺序
        services = []
        if preferred_service == "tianditu":
            services = ["tianditu"]
        elif preferred_service == 'gaode':
            services = ['gaode', 'baidu', 'tencent', 'nominatim']
        else:
            services = ['nominatim', 'gaode', 'baidu', 'tencent']
            
        for service in services:
            result = None
            if service == 'gaode':
                result = self._reverse_gaode(lat, lng)
            elif service == 'baidu':
                result = self._reverse_baidu(lat, lng)
            elif service == 'tencent':
                result = self._reverse_tencent(lat, lng)
            elif service == "tianditu":
                result = self._reverse_tianditu(lat, lng)
            elif service == 'nominatim':
                result = self._reverse_nominatim(lat, lng)
                
            if result:
                return result
                
        return None

    def _normalize_cn_part(self, text: str | None) -> str:
        s = str(text or "").strip()
        if not s:
            return ""
        return s.replace(" ", "")

    def _format_cn_address(self, country: str | None, province: str | None, city: str | None, district: str | None, township: str | None, street: str | None, street_number: str | None) -> str:
        c = self._normalize_cn_part(country)
        p = self._normalize_cn_part(province)
        ci = self._normalize_cn_part(city)
        d = self._normalize_cn_part(district)
        t = self._normalize_cn_part(township)
        s = self._normalize_cn_part(street)
        n = self._normalize_cn_part(street_number)

        if not c:
            c = "中国"
        if ci and p and ci == p:
            ci = ""
        if d in ("市辖区", "县"):
            d = ""

        parts = [c, p, ci, d, t, s, n]
        merged: list[str] = []
        seen: set[str] = set()
        for part in parts:
            if not part:
                continue
            if part in seen:
                continue
            seen.add(part)
            merged.append(part)
        return "".join(merged)

    def _format_cn_address_from_comma_string(self, address: str | None) -> str:
        s = str(address or "").strip()
        if not s:
            return ""
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if not parts:
            return ""
        if parts[-1] != "中国" and "中国" not in parts:
            return ""
        ordered = list(reversed(parts))
        if ordered and ordered[0] != "中国" and "中国" in parts:
            ordered.insert(0, "中国")
        merged = []
        seen = set()
        for p in ordered:
            p2 = self._normalize_cn_part(p)
            if not p2:
                continue
            if p2 in seen:
                continue
            seen.add(p2)
            merged.append(p2)
        return "".join(merged)

    def _geocode_gaode(self, query: str):
        key = self._get_api_key('gaode')
        if not key: return None
        try:
            url = "https://restapi.amap.com/v3/geocode/geo"
            params = {'key': key, 'address': query, 'output': 'json'}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get('status') == '1' and data.get('geocodes'):
                location_str = data['geocodes'][0]['location']
                lng, lat = map(float, location_str.split(','))
                # 直接使用返回的坐标，不再进行 GCJ-02 转换
                return (lat, lng, data['geocodes'][0]['formatted_address'])
        except Exception:
            pass
        return None

    def _geocode_baidu(self, query: str):
        key = self._get_api_key('baidu')
        if not key: return None
        try:
            url = "https://api.map.baidu.com/geocoding/v3/"
            params = {'ak': key, 'address': query, 'output': 'json'}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get('status') == 0 and data.get('result'):
                location = data['result']['location']
                # 百度坐标需要转换，这里暂时简化，实际应该有 BD09 -> WGS84 转换
                # 为了保持简单，假设误差可接受或后续添加 BD09 转换
                # 这里暂时直接返回，或者如果精度要求高需要 BD09->GCJ02->WGS84
                return (location['lat'], location['lng'], query) 
        except Exception:
            pass
        return None

    def _geocode_tencent(self, query: str):
        key = self._get_api_key('tencent')
        if not key: return None
        try:
            url = "https://apis.map.qq.com/ws/geocoder/v1/"
            params = {'key': key, 'address': query}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get('status') == 0 and data.get('result'):
                location = data['result']['location']
                lng = location['lng']
                lat = location['lat']
                # 直接使用返回的坐标，不再进行 GCJ-02 转换
                return (lat, lng, query)
        except Exception:
            pass
        return None

    def _geocode_nominatim(self, query: str):
        if not GEOPY_AVAILABLE: return None
        try:
            geolocator = Nominatim(user_agent="bird_picture_manager")
            location = geolocator.geocode(query, timeout=10)
            if location:
                return (location.latitude, location.longitude, location.address)
        except Exception:
            pass
        return None

    def _geocode_free_service(self, query: str):
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {'q': query, 'format': 'json', 'limit': 1}
            headers = {'User-Agent': 'bird_picture_manager'}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()
            if data and len(data) > 0:
                return (float(data[0]['lat']), float(data[0]['lon']), data[0]['display_name'])
        except Exception:
            pass
        return None

    def _geocode_tianditu(self, query: str):
        key = self._get_api_key("tianditu")
        if not key:
            return None
        try:
            url = "http://api.tianditu.gov.cn/geocoder"
            params = {"ds": json.dumps({"keyWord": query}, ensure_ascii=False), "tk": key}

            # Log request
            try:
                LogManager.instance().info(f"Tianditu geocode request: url={url} query={query}")
            except Exception:
                pass

            response = requests.get(url, params=params, timeout=10)

            # Log response
            try:
                LogManager.instance().info(f"Tianditu geocode response: status={response.status_code} body={response.text[:1000]}")
            except Exception:
                pass

            data = response.json()
            if str(data.get("status")) == "0" and data.get("location"):
                loc = data.get("location") if isinstance(data.get("location"), dict) else {}
                lng = float(loc.get("lon"))
                lat = float(loc.get("lat"))
                # 直接使用返回的坐标，不再进行 GCJ-02 转换
                return (float(lat), float(lng), str(query or ""))
            else:
                try:
                    LogManager.instance().warning(f"Tianditu geocode failed: {data}")
                except Exception:
                    pass
        except Exception as e:
            try:
                LogManager.instance().error(f"Tianditu geocode error: {e}")
            except Exception:
                pass
            pass
        return None

    def _reverse_gaode(self, lat, lng):
        key = self._get_api_key('gaode')
        if not key: return None
        try:
            # 直接使用 WGS84 坐标查询，不再转换为 GCJ-02
            url = "https://restapi.amap.com/v3/geocode/regeo"
            params = {'key': key, 'location': f"{lng},{lat}", 'output': 'json'}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get('status') == '1' and data.get('regeocode'):
                comp = data['regeocode'].get('addressComponent', {})
                if isinstance(comp, dict) and comp:
                    country = comp.get('country') or "中国"
                    province = comp.get('province')
                    city = comp.get('city')
                    if isinstance(city, list):
                        city = city[0] if city else ""
                    district = comp.get('district')
                    township = comp.get('township')
                    sn = comp.get('streetNumber') if isinstance(comp.get('streetNumber'), dict) else {}
                    street = sn.get('street')
                    number = sn.get('number')
                    addr = self._format_cn_address(country, province, city, district, township, street, number)
                    return addr or data['regeocode'].get('formatted_address')
                return data['regeocode'].get('formatted_address')
        except Exception:
            pass
        return None

    def _reverse_baidu(self, lat, lng):
        key = self._get_api_key('baidu')
        if not key: return None
        try:
            url = "https://api.map.baidu.com/reverse_geocoding/v3/"
            params = {'ak': key, 'output': 'json', 'coordtype': 'wgs84ll', 'location': f"{lat},{lng}"}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get('status') == 0 and data.get('result'):
                comp = data['result'].get('addressComponent', {})
                if isinstance(comp, dict) and comp:
                    country = comp.get('country') or "中国"
                    province = comp.get('province')
                    city = comp.get('city')
                    district = comp.get('district')
                    township = comp.get('town') or comp.get('township')
                    street = comp.get('street')
                    number = comp.get('street_number')
                    addr = self._format_cn_address(country, province, city, district, township, street, number)
                    return addr or data['result'].get('formatted_address')
                return data['result'].get('formatted_address')
        except Exception:
            pass
        return None

    def _reverse_tencent(self, lat, lng):
        key = self._get_api_key('tencent')
        if not key: return None
        try:
            # 直接使用 WGS84 坐标查询，不再转换为 GCJ-02
            url = "https://apis.map.qq.com/ws/geocoder/v1/"
            params = {'key': key, 'location': f"{lat},{lng}"}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data.get('status') == 0 and data.get('result'):
                comp = data['result'].get('address_component', {})
                if isinstance(comp, dict) and comp:
                    country = comp.get('nation') or "中国"
                    province = comp.get('province')
                    city = comp.get('city')
                    district = comp.get('district')
                    township = comp.get('town') or comp.get('township')
                    street = comp.get('street')
                    number = comp.get('street_number')
                    addr = self._format_cn_address(country, province, city, district, township, street, number)
                    return addr or data['result'].get('address')
                return data['result'].get('address')
        except Exception:
            pass
        return None

    def _reverse_nominatim(self, lat, lng):
        if not GEOPY_AVAILABLE: return None
        try:
            geolocator = Nominatim(user_agent="bird_picture_manager")
            location = geolocator.reverse(f"{lat}, {lng}", language='zh', timeout=10)
            if location and location.raw and 'address' in location.raw:
                addr_dict = location.raw['address']
                is_cn = False
                try:
                    is_cn = (addr_dict.get('country_code') == 'cn') or (addr_dict.get('country') == '中国')
                except Exception:
                    is_cn = False
                if not is_cn:
                    try:
                        is_cn = "中国" in str(getattr(location, "address", "") or "")
                    except Exception:
                        is_cn = False

                if is_cn:
                    country = addr_dict.get('country') or "中国"
                    province = addr_dict.get('state')
                    city = addr_dict.get('city') or addr_dict.get('town') or addr_dict.get('county')
                    district = addr_dict.get('district') or addr_dict.get('suburb')
                    township = addr_dict.get('quarter') or addr_dict.get('neighbourhood') or addr_dict.get('village')
                    street = addr_dict.get('road') or addr_dict.get('hamlet')
                    number = addr_dict.get('house_number')
                    addr = self._format_cn_address(country, province, city, district, township, street, number)
                    if addr:
                        return addr
                    addr2 = self._format_cn_address_from_comma_string(getattr(location, "address", "") or "")
                    if addr2:
                        return addr2
                
                # 如果不是国内地址，或者构建失败，则使用默认格式，但尝试去除邮编
                # 简单做法：直接返回 location.address，Nominatim 的默认格式通常包含邮编
                # 如果要严格去除邮编，需要重新拼装
                parts = []
                # 常用字段顺序 (西方习惯: 号, 路, 区, 市, 省, 国家)
                ordered_keys = ['house_number', 'road', 'village', 'suburb', 'district', 'town', 'city', 'county', 'state', 'country']
                for k in ordered_keys:
                    if k in addr_dict:
                        parts.append(addr_dict[k])
                if parts:
                    return ", ".join(parts)
                return location.address
        except Exception:
            pass
        return None

    def _reverse_tianditu(self, lat, lng):
        key = self._get_api_key("tianditu")
        if not key:
            return None
        try:
            # 直接使用 WGS84 坐标查询，不再转换为 GCJ-02
            url = "http://api.tianditu.gov.cn/geocoder"
            post_str = f"{{'lon':{lng},'lat':{lat},'ver':1}}"
            params = {"postStr": post_str, "type": "geocode", "tk": key}

            # Log request
            try:
                LogManager.instance().info(f"Tianditu reverse geocode request: url={url} lat={lat} lng={lng} params={params}")
            except Exception:
                pass

            response = requests.get(url, params=params, timeout=10)

            # Log response
            try:
                LogManager.instance().info(f"Tianditu reverse geocode response: status={response.status_code} body={response.text[:1000]}")
            except Exception:
                pass

            data = response.json()
            if str(data.get("status")) == "0" and data.get("result"):
                result = data.get("result") if isinstance(data.get("result"), dict) else {}
                addr = result.get("formatted_address")
                if addr:
                    return str(addr)
            else:
                try:
                    LogManager.instance().warning(f"Tianditu reverse geocode failed: {data}")
                except Exception:
                    pass
        except Exception as e:
            try:
                LogManager.instance().error(f"Tianditu reverse geocode error: {e}")
            except Exception:
                pass
            pass
        return None

    def get_map_styles(self):
        """
        获取所有可用的地图样式列表。
        
        返回:
            list: 包含 (id, title) 元组的列表，用于 UI 显示。
        """
        return [(s["id"], s["title"]) for s in self.MAP_STYLES]

    def get_style_catalog_json(self, tile_proxy_port: int) -> str:
        """
        生成用于前端地图显示的样式目录 JSON 字符串。
        
        参数:
            tile_proxy_port (int): 本地瓦片代理服务器的端口号。
            
        返回:
            str: 包含所有地图样式配置的 JSON 字符串。
        """
        catalog = []
        tile_base = f"http://127.0.0.1:{tile_proxy_port}" if tile_proxy_port else ""
        for style in self.MAP_STYLES:
            catalog.append({
                "id": style["id"],
                "title": style["title"],
                "value": {
                    "version": 8,
                    "name": style["name"],
                    "sources": {
                        "raster0": {
                            "type": "raster",
                            "tiles": [f"{tile_base}/tiles/{style['id']}/{{z}}/{{x}}/{{y}}.png"],
                            "tileSize": 256,
                            "minzoom": style.get("minzoom", 0),
                            "maxzoom": style.get("maxzoom", 22)
                        }
                    },
                    "layers": [{
                        "id": "raster0",
                        "type": "raster",
                        "source": "raster0"
                    }]
                }
            })
        return json.dumps(catalog, ensure_ascii=False)

    def ensure_tile_proxy_server(self) -> int:
        """
        确保瓦片代理服务器正在运行，并返回其端口号。
        如果服务器尚未启动，则启动一个新的服务器。
        
        返回:
            int: 代理服务器的端口号。
        """
        with self._tile_proxy_lock:
            style_templates = {s["id"]: s["urls"] for s in self.MAP_STYLES}
            
            if self._tile_proxy_server is not None:
                try:
                    self._tile_proxy_server.style_templates.update(style_templates)
                except Exception:
                    pass
                return int(self._tile_proxy_server.server_address[1])

            server = ThreadingHTTPServer(("127.0.0.1", 0), _TileProxyHandler)
            server.style_templates = style_templates
            server.tile_cache = {}

            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            self._tile_proxy_server = server
            return int(server.server_address[1])


    def parse_coord_abs(self, text: str) -> float | None:
        """
        解析坐标字符串（支持十进制或度分秒格式），返回其绝对值。
        
        参数:
            text (str): 输入的坐标字符串，可以是 "22.5" 或 "22 deg 30' 0"" 等格式。
            
        返回:
            float | None: 解析后的坐标绝对值，如果解析失败则返回 None。
        """
        s = (text or "").strip()
        if not s:
            return None
        try:
            return abs(float(s))
        except Exception:
            pass

        m = re.fullmatch(
            r'^\s*(?P<deg>-?\d+)\s*(?:deg|°)\s*(?P<min>\d+(?:\.\d+)?)\s*(?:\'|’|′)\s*(?P<sec>\d+(?:\.\d+)?)\s*(?:"|″|”)?\s*$',
            s,
            re.IGNORECASE,
        )
        if not m:
            return None
        try:
            deg = int(m.group("deg"))
            minutes = float(m.group("min"))
            seconds = float(m.group("sec"))
        except Exception:
            return None
        if minutes < 0 or minutes >= 60:
            return None
        if seconds < 0 or seconds >= 60:
            return None
        return abs(deg) + (minutes / 60.0) + (seconds / 3600.0)

    def dms_to_decimal(self, text: str) -> float | None:
        """
        将度分秒(DMS)格式字符串转换为十进制坐标数值。
        这是 parse_coord_abs 的别名，但返回带符号的数值（如果 regex 捕获了符号）。
        注意：parse_coord_abs 目前实现只返回绝对值。为了完整性，这里实现一个返回带符号版本。
        
        参数:
            text (str): DMS 格式字符串，如 "22 deg 14' 0.43"" 或 "-22 deg..."
            
        返回:
            float | None: 转换后的十进制数值。
        """
        # 复用 parse_coord_abs 的逻辑，但这里我们可能需要符号。
        # 既然 parse_coord_abs 已经存在且被 UI 使用（UI 可能处理了符号），
        # 我们先看 parse_coord_abs 的实现。它在最后返回了 abs(deg)... 
        # 如果需要反向转换，通常意味着要保留符号。
        # 让我们重新实现一个完整的带符号解析逻辑，或者修改 parse_coord_abs（风险较大）。
        # 安全起见，这里独立实现一个带符号的解析，逻辑相似。
        
        s = (text or "").strip()
        if not s:
            return None
        
        # 尝试直接解析浮点数
        try:
            return float(s)
        except Exception:
            pass

        # 尝试解析 DMS
        m = re.fullmatch(
            r'^\s*(?P<deg>-?\d+)\s*(?:deg|°)\s*(?P<min>\d+(?:\.\d+)?)\s*(?:\'|’|′)\s*(?P<sec>\d+(?:\.\d+)?)\s*(?:"|″|”)?\s*$',
            s,
            re.IGNORECASE,
        )
        if not m:
            return None
            
        try:
            deg = int(m.group("deg"))
            minutes = float(m.group("min"))
            seconds = float(m.group("sec"))
        except Exception:
            return None
            
        if minutes < 0 or minutes >= 60:
            return None
        if seconds < 0 or seconds >= 60:
            return None
            
        sign = 1 if deg >= 0 else -1
        return sign * (abs(deg) + (minutes / 60.0) + (seconds / 3600.0))

    def decimal_to_dms(self, value: float) -> str:
        """
        将十进制坐标数值转换为度分秒(DMS)格式字符串。
        只处理绝对值，符号由外部处理（如 N/S/E/W）。
        
        参数:
            value (float): 十进制坐标数值。
            
        返回:
            str: 格式化后的 DMS 字符串，例如 30° 15' 20.50"
        """
        val = abs(float(value))
        degrees = int(val)
        temp_min = (val - degrees) * 60
        minutes = int(temp_min)
        seconds = (temp_min - minutes) * 60
        
        return f"{degrees}° {minutes}' {seconds:.2f}\""

    def get_coordinate_format(self) -> str:
        """
        获取当前设置的坐标显示格式。
        
        返回:
            str: 'decimal' (默认) 或 'dms'
        """
        return SettingsManager().get("geolocation/coord_format", "decimal")

    def format_coordinate(self, value: float) -> str:
        """
        根据当前设置格式化坐标数值。
        
        参数:
            value (float): 坐标数值（通常传入绝对值，因为 UI 有独立的方向选择）。
            
        返回:
            str: 格式化后的字符串。
        """
        fmt = self.get_coordinate_format()
        if fmt == 'dms':
            return self.decimal_to_dms(value)
        else:
            # 默认十进制，保留6位小数
            return f"{value:.6f}"

    def get_favorite_locations_file(self):
        """获取常用地点配置文件路径"""
        from utils.setting.settings_manager import CONFIG_DIR
        return os.path.join(CONFIG_DIR, "favorite_locations.json")

    def load_favorite_locations(self):
        """加载常用地点"""
        try:
            path = self.get_favorite_locations_file()
            if not os.path.exists(path):
                return {}
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().warning(f"加载收藏地点失败: {e}")
            except Exception:
                pass
            return {}

    def save_favorite_location(self, name, lat, lng):
        """保存常用地点"""
        favorites = self.load_favorite_locations()
        favorites[name] = {'lat': lat, 'lng': lng}
        try:
            path = self.get_favorite_locations_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(favorites, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            try:
                from utils.log_manager import LogManager

                LogManager.instance().warning(f"保存收藏地点失败: {e}")
            except Exception:
                pass
            return False

    def delete_favorite_location(self, name):
        """删除常用地点"""
        favorites = self.load_favorite_locations()
        if name in favorites:
            del favorites[name]
            try:
                path = self.get_favorite_locations_file()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(favorites, f, ensure_ascii=False, indent=2)
                return True
            except Exception as e:
                try:
                    from utils.log_manager import LogManager

                    LogManager.instance().warning(f"删除收藏地点失败: {e}")
                except Exception:
                    pass
                return False
        return False
