from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
    QComboBox,
    QSizePolicy,
    QInputDialog,
)
from PyQt6.QtCore import Qt, QObject, pyqtSlot, QRunnable, QThreadPool, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QValidator


import json
import os
import time
from ui.utils.icon_loader import qta
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebChannel import QWebChannel
except Exception:
    QWebEngineView = None
    QWebChannel = None

from ui.utils.notification_manager import NotificationManager
from ui.widgets.custom_input_dialog import CustomInputDialog
from ui.widgets.custom_selection_dialog import CustomSelectionDialog
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.utils.geo_manager import (
    GeoInfoManager,
    GeocodeSignals,
    GeocodeRunnable,
    ReverseGeocodeSignals,
    ReverseGeocodeRunnable,
    DmsOrDecimalValidator
)
from utils.setting.settings_manager import SettingsManager
from utils.sql.data_base import BirdLibraryDB
from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG

class GeoWriteSignals(QObject):
    """地理信息写入完成信号"""
    finished = pyqtSignal(list)  # 参数：file_paths

class GeoWriteRunnable(QRunnable):
    def __init__(self, file_paths, lat, lng, location_name, table_name: str = "bird_results"):
        super().__init__()
        self.file_paths = file_paths
        self.lat = lat
        self.lng = lng
        self.location_name = location_name
        self.table_name = str(table_name or "bird_results")
        self.db = BirdLibraryDB()
        self.exif_worker = ExifHandleWorker.get_instance()
        self.signals = GeoWriteSignals()
        # 计算区域代码
        self.region_code = self._detect_region_code(lat, lng)
    
    def _detect_region_code(self, lat: float, lon: float) -> str:
        """根据GPS坐标检测区域代码"""
        try:
            from core.recognizer.geo_filter import get_geo_index
            geo_index = get_geo_index()
            region_code = geo_index.detect_region_from_gps(lat, lon)
            return region_code or ""
        except Exception:
            return ""
    
    def _format_coordinate_for_exif(self, value):
        # value is float degrees
        # return string like: 39 deg 5' 4.99"
        abs_val = abs(value)
        d = int(abs_val)
        m_full = (abs_val - d) * 60
        m = int(m_full)
        s = (m_full - m) * 60
        return f'{d} deg {m}\' {s:.2f}"'

    def run(self):
        # Prepare EXIF tags
        lat_ref = "North" if self.lat >= 0 else "South"
        lon_ref = "East" if self.lng >= 0 else "West"
        
        lat_str = self._format_coordinate_for_exif(self.lat)
        lon_str = self._format_coordinate_for_exif(self.lng)
        
        tags = {
            EXIF_TAG.GPSLatitudeRef.value: lat_ref,
            EXIF_TAG.GPSLatitude.value: lat_str,
            EXIF_TAG.GPSLongitudeRef.value: lon_ref,
            EXIF_TAG.GPSLongitude.value: lon_str,
        }
        
        if self.location_name:
            tags[EXIF_TAG.Location.value] = self.location_name
        
        # 添加区域代码到EXIF
        if self.region_code:
            tags[EXIF_TAG.RegionCode.value] = self.region_code
        
        written_paths = []
        for path in self.file_paths:
            if not path or not os.path.exists(path):
                continue
                
            # Update DB（包含区域代码）
            self.db.update_geolocation(path, self.lat, self.lng, self.location_name or "", region_code=self.region_code, table_name=self.table_name)
            
            # Queue EXIF write
            self.exif_worker.write_tags(path, tags)
            written_paths.append(path)
        
        # 发送完成信号
        if written_paths:
            self.signals.finished.emit(written_paths)

class MapBridge(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._callback = None

    def set_callback(self, callback):
        self._callback = callback

    @pyqtSlot(float, float)
    def onMapClick(self, lat, lng):
        if self._callback:
            self._callback(float(lat), float(lng))


class GeoLocationDialog(BasePopupDialog):
    # 写入完成信号
    geo_updated = pyqtSignal(list)  # 参数：file_paths
    
    def __init__(self, parent=None, selected_count: int = 1, file_paths=None, table_name: str = "bird_results"):
        super().__init__(parent=parent, title="设置地理位置", size=(860, 720))
        self.selected_count = max(1, int(selected_count or 1))
        self.file_paths = file_paths or []
        self.table_name = str(table_name or "bird_results")
        self._webengine_available = self._detect_webengine_available()
        self._tile_proxy_port = GeoInfoManager.instance().ensure_tile_proxy_server() if self._webengine_available else None
        self._thread_pool = QThreadPool()
        self.init_ui()

    def _toast(self, message: str, duration: int = 2000):
        NotificationManager.instance().show_toast(str(message or ""), int(duration), parent=self, position="top")

    def _is_tianditu_service(self) -> bool:
        try:
            return str(SettingsManager().get("geolocation/service", "tianditu") or "").strip().lower() == "tianditu"
        except Exception:
            return False

    def _tianditu_cooldown_remaining(self) -> int:
        return 0

    def _apply_tianditu_cooldown_ui(self):
        return

    def _start_tianditu_cooldown(self):
        return

    def _detect_webengine_available(self) -> bool:
        global QWebEngineView, QWebChannel
        if QWebEngineView is not None and QWebChannel is not None:
            return True
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView as _QWebEngineView
            from PyQt6.QtWebChannel import QWebChannel as _QWebChannel
            QWebEngineView = _QWebEngineView
            QWebChannel = _QWebChannel
            return True
        except Exception:
            return False

    def init_ui(self):
        cm = ColorManager.instance()
        popup_bg = cm.get("popup.background.primary", "#FFFFFF")
        control_bg = cm.get("theme.background.light", "#FFFFFF")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        header_bg = cm.get("popup.header.background", "#2C3E50")
        header_text_color = cm.get("popup.header.text", "#FFFFFF")
        primary_color = cm.get("theme.primary", "#2196F3")
        text_light_color = cm.get("theme.text.light", "#FFFFFF")

        self.setWindowTitle("设置地理位置")
        self.setModal(True)
        hover_bg = cm.get("popup.header.close_button.hover_background", "#FFFFFF1A")
        self.set_title_bar_style(header_bg, header_text_color, hover_bg)
        self.set_bottom_bar_style(self.get_footer_background(), border_color)

        content_layout = self.content_layout
        content_layout.setContentsMargins(20, 20, 20, 10)
        content_layout.setSpacing(12)

        input_style = f"""
            QLineEdit {{
                padding: 6px 10px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 13px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """

        # 使用Base64编码的SVG箭头，避免中文路径问题
        from ui.common.icon_utils import get_arrow_down_svg_base64
        arrow_url = get_arrow_down_svg_base64(text_color)
        combo_style = f"""
            QComboBox {{
                padding: 6px 10px;
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {control_bg};
                font-size: 13px;
                min-width: 90px;
                color: {text_color};
            }}
            QComboBox:hover {{
                border: 1px solid {primary_color};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({arrow_url});
                width: 12px;
                height: 12px;
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {border_color};
                background-color: {popup_bg};
                selection-background-color: {primary_color};
                selection-color: {text_light_color};
                color: {text_color};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {control_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {primary_color};
                color: {text_light_color};
            }}
            QComboBox QAbstractItemView QScrollBar:vertical {{
                background-color: {control_bg};
                width: 10px;
                margin: 0px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical {{
                background-color: {border_color};
                min-height: 30px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {{
                background-color: {primary_color};
            }}
            QComboBox QAbstractItemView QScrollBar::add-line:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QComboBox QAbstractItemView QScrollBar::add-page:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """

        label_style = f"color: {text_color}; font-size: 13px;"

        # 第一行：地理位置输入栏
        row_place = QHBoxLayout()
        row_place.setSpacing(12)
        place_label = QLabel("地理位置:")
        place_label.setStyleSheet(label_style)
        place_label.setFixedWidth(80)
        self.edit_place = QLineEdit()
        self.edit_place.setPlaceholderText("地理位置")
        self.edit_place.setStyleSheet(input_style)
        self.btn_place_search = QPushButton()
        self.btn_place_search.setIcon(qta.icon("mdi6.magnify", color=text_color))
        self.btn_place_search.setFixedSize(34, 34)
        self.btn_place_search.setStyleSheet(f"""
            QPushButton {{
                background-color: {control_bg};
                border: 1px solid {border_color};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {popup_bg};
            }}
            QPushButton:pressed {{
                background-color: {control_bg};
            }}
            QPushButton:disabled {{
                color: {text_color};
                border: 1px solid {border_color};
                background-color: {control_bg};
            }}
        """)
        self.btn_place_search.clicked.connect(self._geocode_place)
        self.edit_place.returnPressed.connect(self._geocode_place)
        row_place.addWidget(place_label)
        row_place.addWidget(self.edit_place, 1)
        row_place.addWidget(self.btn_place_search)
        content_layout.addLayout(row_place)

        # 第二行：纬度输入栏（北纬/南纬 + 数值）
        row_lat = QHBoxLayout()
        row_lat.setSpacing(12)
        lat_label = QLabel("纬度:")
        lat_label.setStyleSheet(label_style)
        lat_label.setFixedWidth(80)
        self.combo_lat_dir = QComboBox()
        self.combo_lat_dir.addItems(["北纬", "南纬"])
        self.combo_lat_dir.setStyleSheet(combo_style)
        self.edit_lat = QLineEdit()
        self.edit_lat.setPlaceholderText('例如：22.543096 或 39° 5\' 4.99″')
        self.edit_lat.setStyleSheet(input_style)
        self.edit_lat.setValidator(DmsOrDecimalValidator(90.0, self.edit_lat))
        row_lat.addWidget(lat_label)
        row_lat.addWidget(self.combo_lat_dir)
        row_lat.addWidget(self.edit_lat, 1)
        content_layout.addLayout(row_lat)

        # 第三行：经度输入栏（东经/西经 + 数值）
        row_lon = QHBoxLayout()
        row_lon.setSpacing(12)
        lon_label = QLabel("经度:")
        lon_label.setStyleSheet(label_style)
        lon_label.setFixedWidth(80)
        self.combo_lon_dir = QComboBox()
        self.combo_lon_dir.addItems(["东经", "西经"])
        self.combo_lon_dir.setStyleSheet(combo_style)
        self.edit_lon = QLineEdit()
        self.edit_lon.setPlaceholderText('例如：114.057865 或 39° 5\' 4.99″')
        self.edit_lon.setStyleSheet(input_style)
        self.edit_lon.setValidator(DmsOrDecimalValidator(180.0, self.edit_lon))
        row_lon.addWidget(lon_label)
        row_lon.addWidget(self.combo_lon_dir)
        row_lon.addWidget(self.edit_lon, 1)
        content_layout.addLayout(row_lon)

        control_btn_style = f"""
            QPushButton {{
                background-color: {control_bg};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {popup_bg};
            }}
            QPushButton:pressed {{
                background-color: {control_bg};
            }}
            QPushButton:disabled {{
                color: {text_color};
                border: 1px solid {border_color};
                background-color: {control_bg};
            }}
        """

        # 常用地点管理
        favorites_layout = QHBoxLayout()
        favorites_layout.setSpacing(10)
        
        fav_label = QLabel("常用地点:")
        fav_label.setStyleSheet(label_style)
        fav_label.setFixedWidth(80)
        favorites_layout.addWidget(fav_label)

        self.btn_load_fav = QPushButton("加载")
        self.btn_load_fav.setToolTip("加载常用地点")
        self.btn_load_fav.setStyleSheet(control_btn_style)
        self.btn_load_fav.clicked.connect(self._on_load_favorite)
        
        self.btn_save_fav = QPushButton("保存")
        self.btn_save_fav.setToolTip("保存当前位置到常用地点")
        self.btn_save_fav.setStyleSheet(control_btn_style)
        self.btn_save_fav.clicked.connect(self._on_save_favorite)
        
        self.btn_del_fav = QPushButton("删除")
        self.btn_del_fav.setToolTip("删除常用地点")
        self.btn_del_fav.setStyleSheet(control_btn_style)
        self.btn_del_fav.clicked.connect(self._on_delete_favorite)

        favorites_layout.addWidget(self.btn_load_fav)
        favorites_layout.addWidget(self.btn_save_fav)
        favorites_layout.addWidget(self.btn_del_fav)
        favorites_layout.addStretch(1)
        
        content_layout.addLayout(favorites_layout)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        style_label = QLabel("地图样式:")
        style_label.setStyleSheet(label_style)
        style_label.setFixedWidth(80)
        self.combo_style = QComboBox()
        self.combo_style.setStyleSheet(combo_style)
        for style_id, title in GeoInfoManager.instance().get_map_styles():
            self.combo_style.addItem(title, style_id)
        try:
            saved_style_id = str(SettingsManager().get("geolocation/map_style_id", "esri_imagery") or "").strip()
        except Exception:
            saved_style_id = "esri_imagery"
        idx = self.combo_style.findData(saved_style_id)
        if idx < 0:
            idx = self.combo_style.findData("esri_imagery")
        if idx >= 0:
            try:
                self.combo_style.blockSignals(True)
            except Exception:
                pass
            self.combo_style.setCurrentIndex(idx)
            try:
                self.combo_style.blockSignals(False)
            except Exception:
                pass
        self.combo_style.currentIndexChanged.connect(self._on_style_changed)

        self.btn_3d = QPushButton("3D")
        self.btn_3d.setFixedHeight(30)
        self.btn_3d.setStyleSheet(control_btn_style)
        self.btn_3d.clicked.connect(self._toggle_3d)
        self._is_3d_enabled = False

        self.btn_rotate_left = QPushButton("↺")
        self.btn_rotate_left.setFixedSize(34, 30)
        self.btn_rotate_left.setStyleSheet(control_btn_style)
        self.btn_rotate_left.clicked.connect(lambda: self._rotate_map(-15))

        self.btn_rotate_right = QPushButton("↻")
        self.btn_rotate_right.setFixedSize(34, 30)
        self.btn_rotate_right.setStyleSheet(control_btn_style)
        self.btn_rotate_right.clicked.connect(lambda: self._rotate_map(15))

        self.btn_reset_view = QPushButton("重置视角")
        self.btn_reset_view.setFixedHeight(30)
        self.btn_reset_view.setStyleSheet(control_btn_style)
        self.btn_reset_view.clicked.connect(self._reset_view)

        self.btn_goto = QPushButton("定位")
        self.btn_goto.setFixedHeight(30)
        self.btn_goto.setStyleSheet(control_btn_style)
        self.btn_goto.clicked.connect(self._fly_to_input_coords)

        controls_layout.addWidget(style_label)
        controls_layout.addWidget(self.combo_style, 1)
        controls_layout.addWidget(self.btn_3d)
        controls_layout.addWidget(self.btn_rotate_left)
        controls_layout.addWidget(self.btn_rotate_right)
        controls_layout.addWidget(self.btn_reset_view)
        controls_layout.addWidget(self.btn_goto)
        content_layout.addLayout(controls_layout)

        self.map_container = QWidget()
        self.map_container.setObjectName("mapContainer")
        self.map_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.map_container.setMinimumHeight(420)
        self.map_container.setStyleSheet(f"""
            QWidget#mapContainer {{
                background-color: {control_bg};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)

        map_container_layout = QVBoxLayout(self.map_container)
        map_container_layout.setContentsMargins(0, 0, 0, 0)

        if self._webengine_available:
            self.map_view = QWebEngineView()
            self.map_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.map_view.setStyleSheet("border: none;")

            page = self.map_view.page()
            profile = page.profile()
            profile.setHttpUserAgent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            self.channel = QWebChannel()
            self.bridge = MapBridge()
            self.bridge.set_callback(self._on_map_click)
            self.channel.registerObject("bridge", self.bridge)
            self.map_view.page().setWebChannel(self.channel)

            self.map_view.setHtml(self._get_map_html())
            map_container_layout.addWidget(self.map_view, 1)
        else:
            self.map_view = None
            self.channel = None
            self.bridge = None

            tip = QLabel("当前环境未安装 WebEngine，无法在窗口内显示地图。\n请安装：pip install -i https://mirrors.aliyun.com/pypi/simple PyQt6-WebEngine")
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color: {text_color}; font-size: 12px; padding: 16px;")
            map_container_layout.addWidget(tip, 1)
            NotificationManager.instance().show_warning("提示", "地图组件不可用（可能未安装或打包未包含 PyQt6-WebEngine）")

            self.combo_style.setEnabled(False)
            self.btn_3d.setEnabled(False)
            self.btn_rotate_left.setEnabled(False)
            self.btn_rotate_right.setEnabled(False)
            self.btn_reset_view.setEnabled(False)
            self.btn_goto.setEnabled(False)
            self.btn_place_search.setEnabled(False)

        map_wrapper = QWidget()
        map_wrapper_layout = QVBoxLayout(map_wrapper)
        map_wrapper_layout.setContentsMargins(12, 0, 12, 12)
        map_wrapper_layout.setSpacing(0)
        map_wrapper_layout.addWidget(self.map_container, 1)
        content_layout.addWidget(map_wrapper, 1)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        cancel_btn.setAutoDefault(False)
        self.apply_dialog_button_style(cancel_btn, "secondary")
        cancel_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton("确定")
        confirm_btn.setFixedSize(80, 32)
        confirm_btn.setAutoDefault(False)
        self.apply_dialog_button_style(confirm_btn, "primary")
        confirm_btn.clicked.connect(self._on_confirm)
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(confirm_btn)

    def _get_map_html(self, lat: float = 39.9042, lng: float = 116.4074, zoom: int = 10):
        safe_lat = float(lat)
        safe_lng = float(lng)
        safe_zoom = int(zoom)
        safe_zoom = max(1, min(18, safe_zoom))
        tile_base = f"http://127.0.0.1:{int(self._tile_proxy_port)}" if self._tile_proxy_port else ""
        style_catalog_json = GeoInfoManager.instance().get_style_catalog_json(int(self._tile_proxy_port) if self._tile_proxy_port else 0)
        try:
            default_style_id = str(SettingsManager().get("geolocation/map_style_id", "esri_imagery") or "").strip()
        except Exception:
            default_style_id = "esri_imagery"

        return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <style>
    html, body {{ height: 100%; width: 100%; margin: 0; padding: 0; background: #ffffff; }}
    #map {{ height: 100%; width: 100%; }}
    #overlay {{
      position: absolute;
      left: 0;
      top: 0;
      right: 0;
      bottom: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: "Microsoft YaHei", sans-serif;
      font-size: 12px;
      color: #666666;
      background: rgba(255, 255, 255, 0.75);
      pointer-events: none;
      user-select: none;
      z-index: 10;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div id="overlay">地图加载中…</div>
  <script>
    function setOverlay(text) {{
      const el = document.getElementById("overlay");
      if (!el) return;
      el.textContent = text || "";
      el.style.display = text ? "flex" : "none";
    }}

    function loadCss(url, onload, onerror) {{
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = url;
      link.onload = onload;
      link.onerror = onerror;
      document.head.appendChild(link);
    }}

    function loadScript(url, onload, onerror) {{
      const script = document.createElement("script");
      script.src = url;
      script.onload = onload;
      script.onerror = onerror;
      document.head.appendChild(script);
    }}

    const cssCandidates = [
      "http://registry.npmmirror.com/maplibre-gl/4.7.1/files/dist/maplibre-gl.css",
      "http://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css",
      "http://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
      "https://registry.npmmirror.com/maplibre-gl/4.7.1/files/dist/maplibre-gl.css",
      "https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css",
      "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"
    ];
    const jsCandidates = [
      "http://registry.npmmirror.com/maplibre-gl/4.7.1/files/dist/maplibre-gl.js",
      "http://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js",
      "http://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js",
      "https://registry.npmmirror.com/maplibre-gl/4.7.1/files/dist/maplibre-gl.js",
      "https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js",
      "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"
    ];

    function tryLoadFromList(loadFn, list, index, onDone) {{
      if (index >= list.length) {{
        onDone(false);
        return;
      }}
      loadFn(
        list[index],
        function() {{ onDone(true); }},
        function() {{ tryLoadFromList(loadFn, list, index + 1, onDone); }}
      );
    }}

    function initMap() {{
      try {{

        const STYLE_CATALOG = {style_catalog_json};

        const preferredStyleId = {json.dumps(default_style_id)};
        let initialStyle = STYLE_CATALOG[0].value;
        try {{
          for (let i = 0; i < STYLE_CATALOG.length; i++) {{
            if (STYLE_CATALOG[i] && STYLE_CATALOG[i].id === preferredStyleId) {{
              initialStyle = STYLE_CATALOG[i].value;
              break;
            }}
          }}
        }} catch (e) {{}}
        const initialCenter = [{safe_lng}, {safe_lat}];
        const initialZoom = {safe_zoom};

        const map = new maplibregl.Map({{
          container: "map",
          style: initialStyle,
          center: initialCenter,
          zoom: initialZoom,
          attributionControl: false
        }});

        let marker = null;
        let lastLngLat = {{ lat: {safe_lat}, lng: {safe_lng} }};
        let lastPitch = 0;
        let lastBearing = 0;
        function setMarker(lat, lng) {{
          if (marker) {{
            marker.remove();
            marker = null;
          }}
          marker = new maplibregl.Marker({{ color: "#e74c3c" }})
            .setLngLat([lng, lat])
            .addTo(map);
          lastLngLat = {{ lat: lat, lng: lng }};
        }}

        map.on("load", () => {{
          setMarker({safe_lat}, {safe_lng});
          setOverlay("");
        }});

        let bridge = null;
        try {{
          if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {{
            new QWebChannel(qt.webChannelTransport, function(channel) {{
              bridge = channel.objects.bridge;
            }});
          }}
        }} catch (e) {{
        }}

        map.on("click", (e) => {{
          const lat = e.lngLat.lat;
          const lng = e.lngLat.lng;
          setMarker(lat, lng);
          if (bridge && bridge.onMapClick) {{
            bridge.onMapClick(lat, lng);
          }}
        }});

        map.on("error", (e) => {{
          try {{
            const msg = (e && e.error && e.error.message) ? String(e.error.message) : "";
            if (msg.includes("Failed to fetch")) {{
              setOverlay("地图请求失败（Failed to fetch），请检查网络或更换样式");
            }}
          }} catch (err) {{
          }}
        }});

        window.addEventListener("error", function(ev) {{
          try {{
            const msg = (ev && ev.message) ? String(ev.message) : "";
            if (msg.includes("Failed to fetch")) {{
              setOverlay("地图请求失败（Failed to fetch），请检查网络或更换样式");
            }}
          }} catch (e) {{
          }}
        }});

        function findStyleById(styleId) {{
          for (const s of STYLE_CATALOG) {{
            if (s.id === styleId) return s;
          }}
          return null;
        }}

        window.bpmSetStyle = function(styleId) {{
          const s = findStyleById(styleId);
          if (!s) return;
          setOverlay("切换样式中…");
          let done = false;
          const timer = setTimeout(() => {{
            if (done) return;
            done = true;
            setOverlay("切换样式失败");
            setTimeout(() => setOverlay(""), 1200);
          }}, 8000);
          try {{
            map.setStyle(s.value);
            const finish = () => {{
              if (done) return;
              done = true;
              clearTimeout(timer);
              setMarker(lastLngLat.lat, lastLngLat.lng);
              setOverlay("");
            }};
            map.once("style.load", finish);
            map.once("idle", finish);
          }} catch (e) {{
            if (!done) {{
              done = true;
              clearTimeout(timer);
              setOverlay("切换样式失败");
              setTimeout(() => setOverlay(""), 1200);
            }}
          }}
        }};

        window.bpmToggle3D = function(enable) {{
          try {{
            const on = !!enable;
            const targetPitch = on ? 60 : 0;
            map.easeTo({{ pitch: targetPitch, duration: 500 }});
            lastPitch = targetPitch;
          }} catch (e) {{
          }}
        }};

        window.bpmRotate = function(delta) {{
          try {{
            const d = Number(delta) || 0;
            const bearing = map.getBearing() + d;
            map.easeTo({{ bearing: bearing, duration: 250 }});
            lastBearing = bearing;
          }} catch (e) {{
          }}
        }};

        window.bpmReset = function() {{
          try {{
            map.easeTo({{
              center: [lastLngLat.lng, lastLngLat.lat],
              zoom: initialZoom,
              pitch: 0,
              bearing: 0,
              duration: 500
            }});
            lastPitch = 0;
            lastBearing = 0;
            setOverlay("");
          }} catch (e) {{
          }}
        }};

        window.bpmFlyTo = function(lat, lng, zoom) {{
          try {{
            const tLat = Number(lat);
            const tLng = Number(lng);
            if (Number.isNaN(tLat) || Number.isNaN(tLng)) return;
            const z = (zoom === undefined || zoom === null) ? Math.max(12, map.getZoom()) : Number(zoom);
            map.flyTo({{
              center: [tLng, tLat],
              zoom: z,
              duration: 650
            }});
            setMarker(tLat, tLng);
          }} catch (e) {{
          }}
        }};
      }} catch (e) {{
        setOverlay("地图初始化失败");
      }}
    }}

    tryLoadFromList(loadCss, cssCandidates, 0, function(cssOk) {{
      tryLoadFromList(loadScript, jsCandidates, 0, function(jsOk) {{
        if (!cssOk || !jsOk) {{
          setOverlay("地图资源加载失败");
          return;
        }}
        if (typeof maplibregl === "undefined") {{
          setOverlay("地图资源加载失败");
          return;
        }}
        initMap();
      }});
    }});
  </script>
</body>
</html>
"""

    def _run_map_js(self, js: str):
        mv = getattr(self, "map_view", None)
        if mv is None:
            return
        try:
            mv.page().runJavaScript(js)
        except Exception:
            pass

    def _get_signed_lat_lng_from_inputs(self):
        lat_abs = GeoInfoManager.instance().parse_coord_abs(self.edit_lat.text())
        lng_abs = GeoInfoManager.instance().parse_coord_abs(self.edit_lon.text())
        if lat_abs is None or lng_abs is None:
            return None, None

        lat_dir = self.combo_lat_dir.currentText()
        lon_dir = self.combo_lon_dir.currentText()

        lat = float(lat_abs) * (-1.0 if lat_dir == "南纬" else 1.0)
        lng = float(lng_abs) * (-1.0 if lon_dir == "西经" else 1.0)
        return lat, lng

    def _on_style_changed(self, index: int):
        if index < 0:
            return
        style_id = self.combo_style.itemData(index)
        if not style_id:
            return
        try:
            SettingsManager().set("geolocation/map_style_id", str(style_id))
        except Exception:
            pass
        self._run_map_js(f"window.bpmSetStyle && window.bpmSetStyle({json.dumps(style_id)});")

    def _toggle_3d(self):
        self._is_3d_enabled = not bool(self._is_3d_enabled)
        self._run_map_js(f"window.bpmToggle3D && window.bpmToggle3D({str(self._is_3d_enabled).lower()});")

    def _rotate_map(self, delta: int):
        self._run_map_js(f"window.bpmRotate && window.bpmRotate({int(delta)});")

    def _reset_view(self):
        self._is_3d_enabled = False
        self._run_map_js("window.bpmReset && window.bpmReset();")

    def _fly_to_input_coords(self):
        lat, lng = self._get_signed_lat_lng_from_inputs()
        if lat is None or lng is None:
            NotificationManager.instance().show_warning("提示", "请输入有效的经纬度")
            return
        self._run_map_js(f"window.bpmFlyTo && window.bpmFlyTo({lat:.8f}, {lng:.8f}, 13);")

    def _geocode_place(self):
        if not hasattr(self, "btn_place_search"):
            return
        remain = self._tianditu_cooldown_remaining()
        if remain > 0:
            try:
                self._apply_tianditu_cooldown_ui()
                if hasattr(self, "_tianditu_cooldown_timer"):
                    self._tianditu_cooldown_timer.start()
            except Exception:
                pass
            self._toast(f"天地图接口冷却中：{int(remain)} 秒后可再次调用")
            return
        query = (self.edit_place.text() or "").strip()
        if not query:
            NotificationManager.instance().show_warning("提示", "请输入地理位置")
            return

        self.btn_place_search.setEnabled(False)
        self._toast("正在搜索地理位置…")

        if not hasattr(self, "_geocode_request_id"):
            self._geocode_request_id = 0
        self._geocode_request_id += 1
        request_id = int(self._geocode_request_id)

        signals = GeocodeSignals()

        def on_success(lat: float, lon: float, display_name: str):
            if request_id != getattr(self, "_geocode_request_id", request_id):
                return
            try:
                self.btn_place_search.setEnabled(True)
                lat_dir = "北纬" if lat >= 0 else "南纬"
                lon_dir = "东经" if lon >= 0 else "西经"
                self.combo_lat_dir.setCurrentText(lat_dir)
                self.combo_lon_dir.setCurrentText(lon_dir)
                self.edit_lat.setText(GeoInfoManager.instance().format_coordinate(abs(lat)))
                self.edit_lon.setText(GeoInfoManager.instance().format_coordinate(abs(lon)))
                self._run_map_js(f"window.bpmFlyTo && window.bpmFlyTo({lat:.8f}, {lon:.8f}, 13);")
                self._perform_reverse_geocode(float(lat), float(lon), cooldown_on_finish=self._is_tianditu_service())
                self._toast("已定位到搜索结果")
            except Exception:
                try:
                    self.btn_place_search.setEnabled(True)
                except Exception:
                    pass

        def on_error(message: str):
            if request_id != getattr(self, "_geocode_request_id", request_id):
                return
            try:
                self.btn_place_search.setEnabled(True)
            except Exception:
                pass
            self._toast(f"搜索失败：{message}")

        signals.success.connect(on_success)
        signals.error.connect(on_error)
        self._thread_pool.start(GeocodeRunnable(query, signals))

        def on_timeout():
            if request_id != getattr(self, "_geocode_request_id", request_id):
                return
            try:
                if self.btn_place_search.isEnabled():
                    return
                self.btn_place_search.setEnabled(True)
            except Exception:
                return
            self._toast("搜索超时，请检查网络或更换关键词")

        QTimer.singleShot(8000, on_timeout)

    def _on_map_click(self, lat: float, lng: float):
        remain = self._tianditu_cooldown_remaining()
        if remain > 0:
            try:
                self._apply_tianditu_cooldown_ui()
                if hasattr(self, "_tianditu_cooldown_timer"):
                    self._tianditu_cooldown_timer.start()
            except Exception:
                pass
            self._toast(f"天地图接口冷却中：{int(remain)} 秒后可再次调用")
            return
        lat_dir = "北纬" if lat >= 0 else "南纬"
        lon_dir = "东经" if lng >= 0 else "西经"
        lat_value = abs(float(lat))
        lon_value = abs(float(lng))

        self.combo_lat_dir.setCurrentText(lat_dir)
        self.combo_lon_dir.setCurrentText(lon_dir)
        self.edit_lat.setText(GeoInfoManager.instance().format_coordinate(lat_value))
        self.edit_lon.setText(GeoInfoManager.instance().format_coordinate(lon_value))

        # Reverse geocoding
        self._perform_reverse_geocode(float(lat), float(lng), cooldown_on_finish=self._is_tianditu_service())

    def _perform_reverse_geocode(self, lat: float, lng: float, cooldown_on_finish: bool = False):
        """在后台执行反向地理编码"""
        # 如果需要的话，取消之前的请求？
        # 使用 request_id 机制来忽略过期的请求结果
        if not hasattr(self, "_reverse_geocode_request_id"):
            self._reverse_geocode_request_id = 0
        self._reverse_geocode_request_id += 1
        current_request_id = self._reverse_geocode_request_id
        
        signals = ReverseGeocodeSignals()
        
        def on_success(address: str):
            # 检查是否是最新请求
            if getattr(self, "_reverse_geocode_request_id", 0) != current_request_id:
                return
            try:
                self.edit_place.setText(address)
                # NotificationManager.instance().show_toast("已更新地址信息")
            except Exception:
                pass
            if bool(cooldown_on_finish) and self._is_tianditu_service():
                self._start_tianditu_cooldown()

        def on_error(message: str):
            # 检查是否是最新请求
            if getattr(self, "_reverse_geocode_request_id", 0) != current_request_id:
                return
            # 可选：记录错误或显示Toast
            # NotificationManager.instance().show_toast(f"获取地址失败: {message}")
            if bool(cooldown_on_finish) and self._is_tianditu_service():
                self._start_tianditu_cooldown()

        signals.success.connect(on_success)
        signals.error.connect(on_error)
        self._thread_pool.start(ReverseGeocodeRunnable(lat, lng, signals))

    def _update_lat_lng_inputs(self, lat: float, lng: float):
        """更新经纬度输入框"""
        lat_dir = "北纬" if lat >= 0 else "南纬"
        lon_dir = "东经" if lng >= 0 else "西经"
        lat_value = abs(float(lat))
        lon_value = abs(float(lng))

        self.combo_lat_dir.setCurrentText(lat_dir)
        self.combo_lon_dir.setCurrentText(lon_dir)
        self.edit_lat.setText(GeoInfoManager.instance().format_coordinate(lat_value))
        self.edit_lon.setText(GeoInfoManager.instance().format_coordinate(lon_value))

    @pyqtSlot()
    def _on_save_favorite(self):
        """保存常用地点"""
        # 获取当前坐标
        lat, lng = self._get_signed_lat_lng_from_inputs()
        if lat is None or lng is None:
            NotificationManager.instance().show_warning("提示", "当前没有有效的坐标信息，无法保存")
            return
            
        # 获取位置名称（默认使用地理位置输入框的内容，如果为空则提示输入）
        default_name = self.edit_place.text().strip()
        
        # 弹出输入框
        name, ok = CustomInputDialog.getText(
            self, 
            "保存常用地点", 
            "请输入地点名称:", 
            text=default_name,
            placeholder="例如：北京鸟巢"
        )
        
        if ok and name.strip():
            if GeoInfoManager.instance().save_favorite_location(name.strip(), lat, lng):
                self._toast(f"已保存地点：{name}")
            else:
                NotificationManager.instance().show_error("错误", "保存地点失败")

    @pyqtSlot()
    def _on_load_favorite(self):
        """加载常用地点"""
        favorites = GeoInfoManager.instance().load_favorite_locations()
        if not favorites:
            NotificationManager.instance().show_info("提示", "暂无常用地点记录")
            return
            
        names = sorted(favorites.keys())
        item, ok = CustomSelectionDialog.getItem(self, "加载常用地点", "请选择地点:", names, 0, False)
        
        if ok and item:
            data = favorites.get(item)
            if data:
                lat = data.get('lat')
                lng = data.get('lng')
                if lat is not None and lng is not None:
                    # 填充坐标并跳转
                    self._update_lat_lng_inputs(lat, lng)
                    self.edit_place.setText(item)
                    self._fly_to_input_coords()
                    self._toast(f"已加载地点：{item}")

    @pyqtSlot()
    def _on_delete_favorite(self):
        """删除常用地点"""
        favorites = GeoInfoManager.instance().load_favorite_locations()
        if not favorites:
            NotificationManager.instance().show_info("提示", "暂无常用地点记录")
            return
            
        names = sorted(favorites.keys())
        item, ok = CustomSelectionDialog.getItem(self, "删除常用地点", "请选择要删除的地点:", names, 0, False)
        
        if ok and item:
            if GeoInfoManager.instance().delete_favorite_location(item):
                self._toast(f"已删除地点：{item}")
            else:
                NotificationManager.instance().show_error("错误", "删除地点失败")

    @pyqtSlot()
    def _on_confirm(self):
        """点击确定按钮"""
        lat, lng = self._get_signed_lat_lng_from_inputs()
        if lat is None or lng is None:
            NotificationManager.instance().show_warning("提示", "请输入有效的经纬度")
            return

        location_name = self.edit_place.text().strip()
        
        # 在后台写入 DB 和 EXIF
        runnable = GeoWriteRunnable(self.file_paths, lat, lng, location_name, table_name=self.table_name)
        runnable.signals.finished.connect(self._on_write_finished)
        QThreadPool.globalInstance().start(runnable)
        
        self._toast("正在后台写入地理位置信息...")
        self.accept()
    
    def _on_write_finished(self, file_paths):
        """写入完成回调"""
        if file_paths:
            self.geo_updated.emit(file_paths)

    def keyPressEvent(self, event):
        """
        重写键盘事件，防止回车键触发确定按钮关闭窗口
        除非焦点在特定控件上（如搜索按钮），否则忽略回车键对Dialog的默认Accept行为
        """
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # 如果焦点在搜索输入框，且不是由按钮触发的（QLineEdit的returnPressed会自动处理）
            # 我们只需要阻止它传递给 QDialog 的 accept
            
            # 检查当前焦点控件
            focus_widget = self.focusWidget()
            
            # 如果是多行文本框等需要回车的控件，可以放行
            # 这里主要是 QLineEdit，我们希望 QLineEdit 的 returnPressed 信号工作，但不希望关闭窗口
            
            # 对于 QLineEdit，returnPressed 信号会在 keyPressEvent 之前或之中触发
            # 如果我们在这里 ignore，可能不会影响 returnPressed，但会阻止 QDialog accept
            
            # 但为了安全起见，我们直接忽略回车键对窗口关闭的作用
            # 除非是显式点击确定按钮
            
            # 注意：如果有其他需要在回车时执行的操作（如搜索），需要确保它们绑定了 returnPressed
            # 我们的 edit_place 绑定了 returnPressed -> _geocode_place
            # 所以这里只需要 consume 掉事件，不调用 super().keyPressEvent
            return
            
        super().keyPressEvent(event)
