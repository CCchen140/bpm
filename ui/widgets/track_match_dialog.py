from __future__ import annotations

import json
import os
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ui.utils.icon_loader import qta
from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QThread, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QSizePolicy,
    QHeaderView,
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebChannel import QWebChannel
except Exception:
    QWebEngineView = None
    QWebChannel = None

from ui.utils.color_manager import ColorManager
from ui.utils.geo_manager import GeoInfoManager
from ui.utils.notification_manager import NotificationManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.widgets.themed_combo_box import ThemedComboBox
from utils.setting.settings_manager import SettingsManager
from utils.sql.data_base import BirdLibraryDB
from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG


@dataclass
class TrackPoint:
    lat: float
    lon: float
    time_str: str | None
    ts: float | None


@dataclass
class PhotoItem:
    file_path: str
    file_name: str
    shot_time_str: str
    shot_ts: float | None
    matched_lat: float | None = None
    matched_lon: float | None = None
    location_text: str = ""


class _TrackMatchWorker(QThread):
    loaded = pyqtSignal(list, list)  # track_points: list[TrackPoint], photos: list[PhotoItem]
    failed = pyqtSignal(str)

    def __init__(self, track_file_path: str, file_paths: list[str], table_name: str):
        super().__init__()
        self.track_file_path = str(track_file_path or "")
        self.file_paths = list(file_paths or [])
        self.table_name = str(table_name or "bird_results")

    def run(self):
        try:
            track_points = _load_track_points(self.track_file_path)
        except Exception as e:
            self.failed.emit(f"轨迹解析失败: {e}")
            return

        try:
            photos = _load_photo_items(self.file_paths, self.table_name)
        except Exception as e:
            self.failed.emit(f"图片信息读取失败: {e}")
            return

        self.loaded.emit(track_points, photos)

class _PhotoLoadWorker(QThread):
    loaded = pyqtSignal(list)  # photos: list[PhotoItem]
    failed = pyqtSignal(str)

    def __init__(self, file_paths: list[str], table_name: str):
        super().__init__()
        self.file_paths = list(file_paths or [])
        self.table_name = str(table_name or "bird_results")

    def run(self):
        try:
            photos = _load_photo_items(self.file_paths, self.table_name)
            self.loaded.emit(photos)
        except Exception as e:
            self.failed.emit(f"图片信息读取失败: {e}")


class _ReverseGeocodeWorker(QThread):
    done = pyqtSignal(int, str)

    def __init__(self, row_index: int, lat: float, lng: float, service_id: str):
        super().__init__()
        self.row_index = int(row_index)
        self.lat = float(lat)
        self.lng = float(lng)
        self.service_id = str(service_id or "")

    def run(self):
        addr = ""
        try:
            gm = GeoInfoManager.instance()
            if self.service_id == "__follow__":
                r = gm.reverse_geocode(self.lat, self.lng) or ""
            elif self.service_id == "tianditu":
                r = gm._reverse_tianditu(self.lat, self.lng) or ""
            elif self.service_id == "gaode":
                r = gm._reverse_gaode(self.lat, self.lng) or ""
            elif self.service_id == "nominatim":
                r = gm._reverse_nominatim(self.lat, self.lng) or ""
            else:
                r = gm.reverse_geocode(self.lat, self.lng) or ""
            addr = str(r or "").strip()
        except Exception:
            addr = ""
        self.done.emit(self.row_index, addr)

class _ReverseGeocodeBatchWorker(QThread):
    progressed = pyqtSignal(int, str)  # row_index, addr
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, tasks: list[tuple[int, float, float]], service_id: str):
        super().__init__()
        self.tasks = list(tasks or [])
        self.service_id = str(service_id or "")

    def run(self):
        try:
            gm = GeoInfoManager.instance()
            for row_index, lat, lng in self.tasks:
                if self.isInterruptionRequested():
                    break
                addr = ""
                try:
                    if self.service_id == "__follow__":
                        r = gm.reverse_geocode(float(lat), float(lng)) or ""
                    elif self.service_id == "tianditu":
                        r = gm._reverse_tianditu(float(lat), float(lng)) or ""
                    elif self.service_id == "gaode":
                        r = gm._reverse_gaode(float(lat), float(lng)) or ""
                    elif self.service_id == "nominatim":
                        r = gm._reverse_nominatim(float(lat), float(lng)) or ""
                    else:
                        r = gm.reverse_geocode(float(lat), float(lng)) or ""
                    addr = str(r or "").strip()
                except Exception:
                    addr = ""
                self.progressed.emit(int(row_index), addr)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(f"获取位置失败: {e}")

class _GeoSaveWorker(QThread):
    finished_ok = pyqtSignal(int, int)  # saved_count, skipped_count
    failed = pyqtSignal(str)

    def __init__(self, photos: list[PhotoItem], table_name: str):
        super().__init__()
        self.photos = list(photos or [])
        self.table_name = str(table_name or "bird_results")
        self.db = BirdLibraryDB()
        self.exif_worker = ExifHandleWorker.get_instance()

    def _format_coordinate_for_exif(self, value: float) -> str:
        abs_val = abs(float(value))
        d = int(abs_val)
        m_full = (abs_val - d) * 60.0
        m = int(m_full)
        s = (m_full - m) * 60.0
        return f'{d} deg {m}\' {s:.2f}"'

    def run(self):
        try:
            saved = 0
            skipped = 0
            for p in self.photos:
                try:
                    if not p.file_path or not os.path.exists(p.file_path):
                        skipped += 1
                        continue
                    if p.matched_lat is None or p.matched_lon is None:
                        skipped += 1
                        continue
                    lat = float(p.matched_lat)
                    lng = float(p.matched_lon)
                    location_text = str(p.location_text or "").strip()

                    self.db.update_geolocation(p.file_path, lat, lng, location_text, table_name=self.table_name)

                    lat_ref = "North" if lat >= 0 else "South"
                    lon_ref = "East" if lng >= 0 else "West"
                    tags = {
                        EXIF_TAG.GPSLatitudeRef.value: lat_ref,
                        EXIF_TAG.GPSLatitude.value: self._format_coordinate_for_exif(lat),
                        EXIF_TAG.GPSLongitudeRef.value: lon_ref,
                        EXIF_TAG.GPSLongitude.value: self._format_coordinate_for_exif(lng),
                    }
                    if location_text:
                        tags[EXIF_TAG.Location.value] = location_text
                    self.exif_worker.write_tags(p.file_path, tags)
                    saved += 1
                except Exception:
                    skipped += 1
                    continue

            self.finished_ok.emit(int(saved), int(skipped))
        except Exception as e:
            self.failed.emit(f"保存失败: {e}")


class TrackMapBridge(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._track_point_callback = None

    def set_track_point_callback(self, callback):
        self._track_point_callback = callback

    @pyqtSlot(float, float, str)
    def onTrackPointClick(self, lat: float, lng: float, time_iso: str):
        if self._track_point_callback:
            self._track_point_callback(float(lat), float(lng), str(time_iso or ""))


class TrackMatchDialog(BasePopupDialog):
    def __init__(self, parent=None, file_paths: list[str] | None = None, table_name: str = "bird_results"):
        super().__init__(parent=parent, title="轨迹匹配", size=(980, 780))
        self.file_paths = list(file_paths or [])
        self.table_name = str(table_name or "bird_results")

        self._webengine_available = self._detect_webengine_available()
        self._tile_proxy_port = GeoInfoManager.instance().ensure_tile_proxy_server() if self._webengine_available else None

        self._track_file_path = ""
        self._track_points: list[TrackPoint] = []
        self._track_ts: list[float] = []
        self._time_offset_seconds = 0.0
        self._calibration_deltas: list[float] = []
        self._allow_geocode = False
        try:
            self._max_match_time_diff_seconds = int(SettingsManager().get("track_match/max_time_diff_seconds", 60) or 60)
        except Exception:
            self._max_match_time_diff_seconds = 60

        self._photos: list[PhotoItem] = []
        self._calibrating_row: int | None = None

        self._reverse_workers: dict[int, _ReverseGeocodeWorker] = {}
        self._load_worker: _TrackMatchWorker | None = None
        self._photo_load_worker: _PhotoLoadWorker | None = None
        self._save_worker: _GeoSaveWorker | None = None
        self._batch_geo_worker: _ReverseGeocodeBatchWorker | None = None
        self._apply_track_btn_default_text = "应用轨迹"

        self._build_ui()
        ColorManager.instance().register_listener(self.apply_theme_styles)
        self.apply_theme_styles()
        self._init_tianditu_cooldown()
        self._start_load_photos_only()
    
    def _toast(self, message: str, duration: int = 2000):
        NotificationManager.instance().show_toast(str(message or ""), int(duration), parent=self, position="top")

    def _build_ui(self):
        cm = ColorManager.instance()
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        control_bg = cm.get("theme.background.light", "#FFFFFF")

        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        lbl = QLabel("轨迹文件:")
        lbl.setStyleSheet(f"color: {text_color};")
        lbl.setFixedWidth(70)
        top_layout.addWidget(lbl)

        self.track_path_edit = QLineEdit()
        self.track_path_edit.setReadOnly(True)
        self.track_path_edit.setPlaceholderText("请选择 GPX / KML / KMZ 轨迹文件")
        self.track_path_edit.setStyleSheet(
            f"QLineEdit {{ padding: 6px 8px; border: 1px solid {border_color}; border-radius: 6px; color: {text_color}; background: {control_bg}; }}"
        )
        top_layout.addWidget(self.track_path_edit, 1)

        self.pick_btn = QPushButton("选择文件")
        self.pick_btn.setFixedSize(92, 32)
        self.apply_dialog_button_style(self.pick_btn, "secondary")
        self.pick_btn.clicked.connect(self._pick_track_file)
        top_layout.addWidget(self.pick_btn)

        self.location_service_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        self.location_service_combo.setFixedWidth(160)
        self.location_service_combo.addItem("位置服务(跟随设置)", "__follow__")
        self.location_service_combo.addItem("天地图", "tianditu")
        self.location_service_combo.addItem("Nominatim", "nominatim")
        self.location_service_combo.addItem("高德", "gaode")
        self.location_service_combo.currentIndexChanged.connect(self._on_location_options_changed)
        top_layout.addWidget(self.location_service_combo)

        self.location_mode_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        self.location_mode_combo.setFixedWidth(170)
        self.location_mode_combo.addItem("每张图片获取位置", "per_photo")
        self.location_mode_combo.addItem("使用最早拍摄照片位置", "earliest_photo")
        self.location_mode_combo.addItem("使用居中拍摄照片位置", "middle_photo")
        self.location_mode_combo.addItem("使用最晚拍摄照片位置", "latest_photo")
        self.location_mode_combo.currentIndexChanged.connect(self._on_location_mode_changed)
        self.location_mode_combo.currentIndexChanged.connect(self._on_location_options_changed)
        top_layout.addWidget(self.location_mode_combo)

        self.apply_track_btn = QPushButton("应用轨迹")
        self.apply_track_btn.setFixedSize(92, 32)
        self.apply_track_btn.clicked.connect(self._on_apply_track_clicked)
        top_layout.addWidget(self.apply_track_btn)

        self.content_layout.addWidget(top)

        self.map_container = QWidget()
        self.map_container.setObjectName("mapContainer")
        self.map_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.map_container.setMinimumHeight(420)
        self.map_container.setStyleSheet(
            f"QWidget#mapContainer {{ background-color: {control_bg}; border: 1px solid {border_color}; border-radius: 6px; }}"
        )
        map_layout = QVBoxLayout(self.map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.setSpacing(0)

        if self._webengine_available:
            self.map_view = QWebEngineView()
            self.map_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.map_view.setStyleSheet("border: none;")
            try:
                page = self.map_view.page()
                profile = page.profile()
                profile.setHttpUserAgent(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            except Exception:
                pass

            self.channel = QWebChannel()
            self.bridge = TrackMapBridge()
            self.bridge.set_track_point_callback(self._on_track_point_clicked)
            self.channel.registerObject("bridge", self.bridge)
            self.map_view.page().setWebChannel(self.channel)

            self.map_view.setHtml(self._get_map_html())
            map_layout.addWidget(self.map_view, 1)
        else:
            self.map_view = None
            self.channel = None
            self.bridge = None
            tip = QLabel("当前环境未安装 WebEngine，无法在窗口内显示地图。")
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color: {text_color}; font-size: 12px; padding: 16px;")
            map_layout.addWidget(tip, 1)
            NotificationManager.instance().show_warning("提示", "地图组件不可用（可能未安装或打包未包含 PyQt6-WebEngine）")

        self.content_layout.addWidget(self.map_container, 1)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["文件名", "拍摄时间", "匹配经纬度", "具体位置"])
        self.table.setMinimumHeight(240)
        self.table.setRowCount(0)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed)
        try:
            self.table.verticalHeader().setDefaultSectionSize(36)
        except Exception:
            pass
        try:
            self.table.itemChanged.connect(self._on_table_item_changed)
        except Exception:
            pass
        try:
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass

        self.content_layout.addWidget(self.table, 0)
        try:
            self._apply_table_scrollbar_style()
        except Exception:
            pass

        calibrate_bar = QWidget()
        # 设置背景透明，避免显示灰色长条
        calibrate_bar.setStyleSheet("background-color: transparent; border: none;")
        calibrate_layout = QHBoxLayout(calibrate_bar)
        calibrate_layout.setContentsMargins(0, 8, 0, 0)
        calibrate_layout.setSpacing(10)
        calibrate_layout.addStretch(1)
        self.calibrate_btn = QPushButton("时间校准")
        self.calibrate_btn.setFixedSize(92, 32)
        self.apply_dialog_button_style(self.calibrate_btn, "secondary")
        self.calibrate_btn.clicked.connect(self._on_calibrate_clicked)
        calibrate_layout.addWidget(self.calibrate_btn)
        self.content_layout.addWidget(calibrate_bar, 0)

        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(92, 32)
        self.apply_dialog_button_style(close_btn, "secondary")
        close_btn.clicked.connect(self.reject)
        self.bottom_layout.addWidget(close_btn)

        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedSize(92, 32)
        self.apply_dialog_button_style(self.save_btn, "primary")
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.bottom_layout.addWidget(self.save_btn)

        self._on_location_mode_changed()
        self._refresh_location_mode_options()
        self._on_location_mode_changed()
        self._apply_top_controls_style()
        try:
            self._apply_table_scrollbar_style()
        except Exception:
            pass

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

    def _tianditu_cooldown_seconds(self) -> int:
        try:
            k = str(SettingsManager().get("geolocation/tianditu_key", "") or "").strip()
        except Exception:
            k = ""
        if k and k != "6b4610fa57e689d864d4db5f7ee80a14":
            return 0
        return 30

    def _is_tianditu_service_selected(self) -> bool:
        try:
            sid = str(self.location_service_combo.currentData() or "").strip().lower()
            if sid == "tianditu":
                return True
            if sid == "__follow__":
                return str(SettingsManager().get("geolocation/service", "tianditu") or "").strip().lower() == "tianditu"
            return False
        except Exception:
            return False

    def _tianditu_cooldown_remaining(self) -> int:
        if not self._is_tianditu_service_selected():
            return 0
        if int(self._tianditu_cooldown_seconds()) <= 0:
            return 0
        try:
            last_ts = float(SettingsManager().get("geolocation/tianditu_last_call_ts", 0) or 0)
        except Exception:
            last_ts = 0.0
        if last_ts <= 0:
            return 0
        remain = int(round((last_ts + float(self._tianditu_cooldown_seconds())) - float(time.time())))
        return int(max(0, remain))

    def _init_tianditu_cooldown(self):
        if not hasattr(self, "_tianditu_cooldown_timer"):
            self._tianditu_cooldown_timer = QTimer(self)
            self._tianditu_cooldown_timer.setInterval(1000)
            self._tianditu_cooldown_timer.timeout.connect(self._tick_tianditu_cooldown)
        self._apply_tianditu_cooldown_ui()
        try:
            if self._tianditu_cooldown_remaining() > 0:
                self._tianditu_cooldown_timer.start()
        except Exception:
            pass

    def _start_tianditu_cooldown(self):
        if int(self._tianditu_cooldown_seconds()) <= 0:
            try:
                sm = SettingsManager()
                sm.set("geolocation/tianditu_last_call_ts", 0.0)
                sm.sync()
            except Exception:
                pass
            self._apply_tianditu_cooldown_ui()
            return
        try:
            sm = SettingsManager()
            sm.set("geolocation/tianditu_last_call_ts", float(time.time()))
            sm.sync()
        except Exception:
            pass
        self._apply_tianditu_cooldown_ui()
        try:
            self._tianditu_cooldown_timer.start()
        except Exception:
            pass

    def _tick_tianditu_cooldown(self):
        self._apply_tianditu_cooldown_ui()

    def _apply_tianditu_cooldown_ui(self):
        remain = self._tianditu_cooldown_remaining()
        try:
            if not self._is_tianditu_service_selected():
                if hasattr(self, "_tianditu_cooldown_timer"):
                    self._tianditu_cooldown_timer.stop()
                if hasattr(self, "apply_track_btn") and self.apply_track_btn:
                    self.apply_track_btn.setText(str(self._apply_track_btn_default_text))
                return
        except Exception:
            pass
        try:
            if remain <= 0:
                try:
                    if hasattr(self, "apply_track_btn") and self.apply_track_btn:
                        self.apply_track_btn.setText(str(self._apply_track_btn_default_text))
                except Exception:
                    pass
                try:
                    if hasattr(self, "_tianditu_cooldown_timer"):
                        self._tianditu_cooldown_timer.stop()
                except Exception:
                    pass
                return
        except Exception:
            return
        try:
            if hasattr(self, "apply_track_btn") and self.apply_track_btn:
                self.apply_track_btn.setText(f"{int(remain)}秒")
        except Exception:
            pass
        try:
            if hasattr(self, "_tianditu_cooldown_timer") and not self._tianditu_cooldown_timer.isActive():
                self._tianditu_cooldown_timer.start()
        except Exception:
            pass

    def _on_location_mode_changed(self):
        _ = self.location_mode_combo

    def _on_location_options_changed(self):
        self._refresh_location_mode_options()
        self._on_location_mode_changed()
        try:
            self._apply_tianditu_cooldown_ui()
        except Exception:
            pass
        self._render_table()

    def _refresh_location_mode_options(self):
        current = ""
        try:
            current = str(self.location_mode_combo.currentData() or "")
        except Exception:
            current = ""

        is_tianditu = bool(self._is_tianditu_service_selected())

        allowed = []
        if is_tianditu:
            allowed = [
                ("使用最早拍摄照片位置", "earliest_photo"),
                ("使用居中拍摄照片位置", "middle_photo"),
                ("使用最晚拍摄照片位置", "latest_photo"),
            ]
        else:
            allowed = [
                ("每张图片获取位置", "per_photo"),
                ("使用最早拍摄照片位置", "earliest_photo"),
                ("使用居中拍摄照片位置", "middle_photo"),
                ("使用最晚拍摄照片位置", "latest_photo"),
            ]

        try:
            self.location_mode_combo.blockSignals(True)
            self.location_mode_combo.clear()
            for text, val in allowed:
                self.location_mode_combo.addItem(text, val)
            if current and any(v == current for _, v in allowed):
                self.location_mode_combo.setCurrentIndex([v for _, v in allowed].index(current))
            else:
                self.location_mode_combo.setCurrentIndex(0)
        except Exception:
            pass
        finally:
            try:
                self.location_mode_combo.blockSignals(False)
            except Exception:
                pass

    def _apply_top_controls_style(self):
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary", "#D0D0D0")
        text_color = cm.get("popup.text.primary", "#333333")
        primary = cm.get("theme.primary", "#2196F3")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        bg = cm.get("theme.background.light", "#FFFFFF")

        def _btn_style():
            return f"""
                QPushButton {{
                    background-color: {bg};
                    color: {text_color};
                    border: 1px solid {border};
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                    border: 1px solid {primary};
                }}
                QPushButton:pressed {{
                    background-color: {hover_bg};
                    border: 1px solid {primary};
                }}
            """

        try:
            if hasattr(self, "pick_btn") and self.pick_btn:
                self.pick_btn.setStyleSheet(_btn_style())
        except Exception:
            pass
        try:
            if hasattr(self, "apply_track_btn") and self.apply_track_btn:
                self.apply_track_btn.setStyleSheet(_btn_style())
        except Exception:
            pass
        # 时间校准按钮样式：移除灰色背景，添加边框
        try:
            if hasattr(self, "calibrate_btn") and self.calibrate_btn:
                self.calibrate_btn.setStyleSheet(_btn_style())
        except Exception:
            pass

    def _pick_track_file(self):
        try:
            start_dir = ""
            if self._track_file_path and os.path.exists(self._track_file_path):
                start_dir = os.path.dirname(self._track_file_path)
            if not start_dir:
                try:
                    last_dir = str(SettingsManager().get("track_match/last_track_dir", "") or "").strip()
                except Exception:
                    last_dir = ""
                if last_dir and os.path.exists(last_dir):
                    start_dir = last_dir
            dialog = QFileDialog(self)
            dialog.setWindowTitle("选择轨迹文件")
            dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
            dialog.setNameFilter("轨迹文件 (*.gpx *.kml *.kmz)")
            if start_dir:
                dialog.setDirectory(start_dir)
            if dialog.exec():
                files = dialog.selectedFiles()
                if files:
                    self._set_track_file(files[0])
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"选择文件失败: {e}")

    def _set_track_file(self, path: str):
        p = str(path or "")
        if not p or not os.path.exists(p):
            NotificationManager.instance().show_warning("提示", "轨迹文件不存在")
            return
        self._track_file_path = p
        self.track_path_edit.setText(p)
        try:
            sm = SettingsManager()
            sm.set("track_match/last_track_dir", os.path.dirname(p))
            sm.sync()
        except Exception:
            pass
        self._allow_geocode = False
        self._start_load_and_match()

    def _start_load_photos_only(self):
        if not self.file_paths:
            return
        try:
            if self._photo_load_worker and self._photo_load_worker.isRunning():
                self._photo_load_worker.requestInterruption()
        except Exception:
            pass

        self._photo_load_worker = _PhotoLoadWorker(self.file_paths, self.table_name)
        self._photo_load_worker.loaded.connect(self._on_photos_loaded_only)
        self._photo_load_worker.failed.connect(lambda msg: NotificationManager.instance().show_warning("错误", str(msg)))
        self._photo_load_worker.start()

    def _on_photos_loaded_only(self, photos: list[PhotoItem]):
        self._photos = list(photos or [])
        self._render_table()

    def _start_load_and_match(self):
        if not self._track_file_path:
            return
        if not self.file_paths:
            NotificationManager.instance().show_warning("提示", "没有可匹配的图片")
            return
        try:
            if self._load_worker and self._load_worker.isRunning():
                self._load_worker.requestInterruption()
        except Exception:
            pass

        self.pick_btn.setEnabled(False)
        self._toast("正在加载轨迹并匹配…")

        self._load_worker = _TrackMatchWorker(self._track_file_path, self.file_paths, self.table_name)
        self._load_worker.loaded.connect(self._on_loaded)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.finished.connect(lambda: self.pick_btn.setEnabled(True))
        self._load_worker.start()

    def _on_load_failed(self, msg: str):
        self.pick_btn.setEnabled(True)
        NotificationManager.instance().show_warning("错误", str(msg or "加载失败"))

    def _on_loaded(self, track_points: list[TrackPoint], photos: list[PhotoItem]):
        self._track_points = list(track_points or [])
        self._photos = list(photos or [])
        self._calibrating_row = None
        self._calibration_deltas = []
        self._time_offset_seconds = 0.0
        self._rebuild_track_ts()
        self._update_map_track()
        self._apply_track_coords_only(clear_location=False)
        try:
            total = int(len(self._photos))
            matched = int(sum(1 for p in self._photos if p.matched_lat is not None and p.matched_lon is not None))
            if total > 0:
                self._toast(f"已匹配坐标：{matched}/{total}")
        except Exception:
            pass

    def _rebuild_track_ts(self):
        self._track_ts = []
        for pt in self._track_points:
            self._track_ts.append(pt.ts if pt.ts is not None else float("nan"))

    def _run_map_js(self, js: str):
        if not self.map_view:
            return
        try:
            self.map_view.page().runJavaScript(js)
        except Exception:
            pass

    def _get_map_html(self):
        tile_base = f"http://127.0.0.1:{int(self._tile_proxy_port)}" if self._tile_proxy_port else ""
        style_catalog_json = GeoInfoManager.instance().get_style_catalog_json(int(self._tile_proxy_port) if self._tile_proxy_port else 0)
        _ = tile_base

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
        function findStyleValueById(styleId) {{
          try {{
            for (const s of STYLE_CATALOG) {{
              if (s && s.id === styleId) return s.value;
            }}
          }} catch (e) {{
          }}
          return null;
        }}
        const initialStyle = findStyleValueById("esri_imagery") || STYLE_CATALOG[0].value;
        const map = new maplibregl.Map({{
          container: "map",
          style: initialStyle,
          center: [116.4074, 39.9042],
          zoom: 10,
          attributionControl: false,
          dragPan: false,
          scrollZoom: false,
          boxZoom: false,
          dragRotate: false,
          keyboard: false,
          doubleClickZoom: false,
          touchZoomRotate: false
        }});

        map.on("load", () => {{
          setOverlay("");
          try {{
            map.addSource("bpm-track", {{
              type: "geojson",
              data: {{
                type: "FeatureCollection",
                features: []
              }}
            }});
            map.addLayer({{
              id: "bpm-track-line",
              type: "line",
              source: "bpm-track",
              filter: ["==", ["get", "kind"], "line"],
              paint: {{
                "line-color": "#2196F3",
                "line-width": 3
              }}
            }});
            map.addLayer({{
              id: "bpm-track-points",
              type: "circle",
              source: "bpm-track",
              filter: ["==", ["get", "kind"], "point"],
              paint: {{
                "circle-radius": 4,
                "circle-color": "#E74C3C",
                "circle-stroke-width": 1,
                "circle-stroke-color": "#FFFFFF"
              }}
            }});
          }} catch (e) {{
          }}
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

        function fitToLine(coords) {{
          try {{
            if (!coords || coords.length < 2) return;
            let minLng = coords[0][0], maxLng = coords[0][0], minLat = coords[0][1], maxLat = coords[0][1];
            for (const c of coords) {{
              if (c[0] < minLng) minLng = c[0];
              if (c[0] > maxLng) maxLng = c[0];
              if (c[1] < minLat) minLat = c[1];
              if (c[1] > maxLat) maxLat = c[1];
            }}
            map.fitBounds([[minLng, minLat], [maxLng, maxLat]], {{ padding: 40, duration: 0 }});
          }} catch (e) {{
          }}
        }}

        window.bpmSetTrack = function(trackPoints) {{
          try {{
            if (!trackPoints || !trackPoints.length) return;
            const coords = [];
            const features = [];
            for (let i = 0; i < trackPoints.length; i++) {{
              const p = trackPoints[i];
              const lng = Number(p.lng);
              const lat = Number(p.lat);
              if (Number.isNaN(lng) || Number.isNaN(lat)) continue;
              coords.push([lng, lat]);
              features.push({{
                type: "Feature",
                geometry: {{ type: "Point", coordinates: [lng, lat] }},
                properties: {{ kind: "point", time: String(p.time || ""), idx: i }}
              }});
            }}
            if (coords.length >= 2) {{
              features.unshift({{
                type: "Feature",
                geometry: {{ type: "LineString", coordinates: coords }},
                properties: {{ kind: "line" }}
              }});
              fitToLine(coords);
            }} else if (coords.length === 1) {{
              map.jumpTo({{ center: coords[0], zoom: 14 }});
            }}
            const fc = {{ type: "FeatureCollection", features: features }};
            const src = map.getSource("bpm-track");
            if (src) src.setData(fc);
          }} catch (e) {{
          }}
        }};

        map.on("click", "bpm-track-points", (e) => {{
          try {{
            const f = e.features && e.features[0];
            if (!f) return;
            const coords = f.geometry && f.geometry.coordinates;
            const props = f.properties || {{}};
            const lng = coords[0];
            const lat = coords[1];
            const t = String(props.time || "");
            if (bridge && bridge.onTrackPointClick) {{
              bridge.onTrackPointClick(lat, lng, t);
            }}
          }} catch (err) {{
          }}
        }});
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

    def apply_theme_styles(self):
        cm = ColorManager.instance()
        content_bg = cm.get("theme.background.light", "#FFFFFF")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        footer_bg = cm.get("theme.background.dark", "#E7E7E7")
        header_bg = cm.get("popup.header.background", "#2c3e50")
        header_text = cm.get("popup.header.text", "#FFFFFF")
        close_hover_bg = cm.get("popup.header.close_button.hover_background", "#FFFFFF1A")

        try:
            if self.container:
                self.container.setStyleSheet(
                    f"QWidget#container {{ background-color: {content_bg}; border: 1px solid {border_color}; border-radius: 8px; }}"
                )
        except Exception:
            pass

        try:
            if self.title_bar:
                self.set_title_bar_style(header_bg, header_text, hover_background=close_hover_bg)
        except Exception:
            pass

        try:
            if self.bottom_bar:
                self.set_bottom_bar_style(footer_bg, border_color=border_color)
        except Exception:
            pass
        try:
            self._apply_top_controls_style()
        except Exception:
            pass
        try:
            self._apply_table_scrollbar_style()
        except Exception:
            pass

    def _apply_table_scrollbar_style(self):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.light", "#FFFFFF")
        dark_bg = cm.get("theme.background.dark", "#E7E7E7")
        border = cm.get("popup.border.primary", "#D0D0D0")
        primary = cm.get("theme.primary", "#2196F3")
        text = cm.get("popup.text.primary", "#333333")

        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            QHeaderView::section {{
                background-color: {dark_bg};
                color: {text};
                border: none;
                padding: 6px 8px;
            }}
            QTableWidget::item:selected {{
                background-color: {primary};
                color: {bg};
            }}
            QScrollBar:vertical {{
                background-color: {dark_bg};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {border};
                min-height: 30px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {primary};
            }}
            QScrollBar:horizontal {{
                background-color: {dark_bg};
                height: 10px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {border};
                min-width: 30px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {primary};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
            """
        )

    def _update_map_track(self):
        if not self._track_points:
            return
        payload = [{"lat": p.lat, "lng": p.lon, "time": p.time_str or ""} for p in self._track_points]
        self._run_map_js(f"window.bpmSetTrack && window.bpmSetTrack({json.dumps(payload)});")

    def _match_all_photos(self):
        if not self._photos:
            return
        if not self._track_points:
            return
        track_ts = []
        track_pts = []
        for pt in self._track_points:
            if pt.ts is None:
                continue
            track_ts.append(float(pt.ts))
            track_pts.append(pt)

        if not track_ts:
            for p in self._photos:
                p.matched_lat = None
                p.matched_lon = None
            NotificationManager.instance().show_warning("提示", "轨迹文件缺少时间信息，无法按时间匹配")
            return

        paired = sorted(zip(track_ts, track_pts), key=lambda x: x[0])
        ts_sorted = [x[0] for x in paired]
        pts_sorted = [x[1] for x in paired]

        for p in self._photos:
            p.matched_lat = None
            p.matched_lon = None
            if p.shot_ts is None:
                continue
            target = float(p.shot_ts) - float(self._time_offset_seconds)
            idx = _bisect_left(ts_sorted, target)
            best_i = None
            best_diff = None
            for cand in (idx - 1, idx, idx + 1):
                if cand < 0 or cand >= len(ts_sorted):
                    continue
                d = abs(ts_sorted[cand] - target)
                if best_diff is None or d < best_diff:
                    best_diff = d
                    best_i = cand
            if best_i is None:
                continue
            try:
                if best_diff is not None and float(best_diff) > float(self._max_match_time_diff_seconds):
                    continue
            except Exception:
                pass
            pt = pts_sorted[best_i]
            p.matched_lat = float(pt.lat)
            p.matched_lon = float(pt.lon)

    def _apply_track_coords_only(self, clear_location: bool):
        if not self._track_points:
            return
        self._match_all_photos()
        if bool(clear_location):
            for p in self._photos:
                p.location_text = ""
        self._render_table()

    def _apply_track_to_all(self):
        if not self._track_points:
            return
        self._allow_geocode = True
        service_id = str(self.location_service_combo.currentData() or "__follow__")
        can_geocode_now = True
        if self._is_tianditu_service_selected() and service_id in ("tianditu", "__follow__"):
            try:
                can_geocode_now = self._tianditu_cooldown_remaining() <= 0
            except Exception:
                can_geocode_now = True
        mode = str(self.location_mode_combo.currentData() or "per_photo")
        self._apply_track_coords_only(clear_location=bool(can_geocode_now))
        tasks = self._build_reverse_tasks_from_mode()
        if not tasks:
            try:
                if self._is_tianditu_service_selected() and service_id in ("tianditu", "__follow__"):
                    self._apply_tianditu_cooldown_ui()
            except Exception:
                pass
            try:
                total = int(len(self._photos))
                matched = int(sum(1 for p in self._photos if p.matched_lat is not None and p.matched_lon is not None))
                if total > 0 and matched == 0:
                    NotificationManager.instance().show_warning(
                        "提示",
                        f"没有可用坐标进行地理编码（匹配阈值：{int(self._max_match_time_diff_seconds)} 秒）。可尝试时间校准或检查照片时间。",
                    )
                else:
                    NotificationManager.instance().show_warning("提示", "没有可用坐标进行地理编码")
            except Exception:
                NotificationManager.instance().show_warning("提示", "没有可用坐标进行地理编码")
            return
        fill_all = mode in ("earliest_photo", "middle_photo", "latest_photo")
        self._start_batch_reverse_geocode(tasks, fill_all_from_anchor=bool(fill_all))

    def _on_apply_track_clicked(self):
        if not self._track_points:
            NotificationManager.instance().show_warning("提示", "请先选择轨迹文件")
            return
        self._toast("正在应用轨迹并更新位置…")
        self._apply_track_to_all()

    def _build_reverse_tasks_from_mode(self) -> list[tuple[int, float, float]]:
        if not self._photos:
            return []
        mode = str(self.location_mode_combo.currentData() or "per_photo")
        tasks: list[tuple[int, float, float]] = []
        if mode == "per_photo":
            for i, p in enumerate(self._photos):
                if p.matched_lat is None or p.matched_lon is None:
                    continue
                tasks.append((int(i), float(p.matched_lat), float(p.matched_lon)))
            return tasks

        if mode in ("earliest_photo", "middle_photo", "latest_photo"):
            idx = self._pick_photo_index_for_location_mode(mode)
            if idx is None:
                return []
            p = self._photos[int(idx)]
            if p.matched_lat is None or p.matched_lon is None:
                return []
            tasks.append((int(idx), float(p.matched_lat), float(p.matched_lon)))
            return tasks

        return []

    def _pick_photo_index_for_location_mode(self, mode: str) -> int | None:
        m = str(mode or "").strip()
        candidates: list[tuple[float, int]] = []
        fallback: list[int] = []
        for i, p in enumerate(self._photos):
            if p.matched_lat is None or p.matched_lon is None:
                continue
            if p.shot_ts is None:
                fallback.append(int(i))
                continue
            candidates.append((float(p.shot_ts), int(i)))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            indices = [i for _, i in candidates]
        elif fallback:
            indices = list(fallback)
        else:
            return None

        if m == "earliest_photo":
            return int(indices[0])
        if m == "latest_photo":
            return int(indices[-1])
        if m == "middle_photo":
            return int(indices[len(indices) // 2])
        return int(indices[0])

    def _start_batch_reverse_geocode(self, tasks: list[tuple[int, float, float]], fill_all_from_anchor: bool):
        if not tasks:
            return
        if not bool(getattr(self, "_allow_geocode", False)):
            NotificationManager.instance().show_warning("提示", "请先点击“应用轨迹”后再获取具体位置")
            return
        service_id = str(self.location_service_combo.currentData() or "__follow__")
        if self._is_tianditu_service_selected() and service_id in ("tianditu", "__follow__"):
            remain = self._tianditu_cooldown_remaining()
            if remain > 0:
                try:
                    self._apply_tianditu_cooldown_ui()
                except Exception:
                    pass
                return
        try:
            if self._batch_geo_worker and self._batch_geo_worker.isRunning():
                self._batch_geo_worker.requestInterruption()
        except Exception:
            pass

        self._batch_fill_all_from_anchor = bool(fill_all_from_anchor)
        self._batch_geo_worker = _ReverseGeocodeBatchWorker(tasks, service_id)
        self._batch_geo_worker.progressed.connect(self._on_batch_reverse_progress)
        self._batch_geo_worker.failed.connect(lambda msg: NotificationManager.instance().show_warning("错误", str(msg)))
        self._batch_geo_worker.finished_ok.connect(lambda: self._toast("位置更新完成"))
        self._batch_geo_worker.start()

    def _on_batch_reverse_progress(self, row_index: int, addr: str):
        a = str(addr or "").strip()
        if not a:
            return
        if row_index < 0 or row_index >= len(self._photos):
            return
        self._photos[row_index].location_text = a
        if bool(getattr(self, "_batch_fill_all_from_anchor", False)):
            for p in self._photos:
                if p.matched_lat is None or p.matched_lon is None:
                    continue
                p.location_text = a
        self._render_table()
        if self._is_tianditu_service_selected():
            self._start_tianditu_cooldown()

    def _render_table(self):
        max_visible = 8
        row_count = min(int(len(self._photos)), int(max_visible))
        try:
            self.table.blockSignals(True)
            self.table.setRowCount(int(row_count))
            for row in range(int(row_count)):
                p = self._photos[row]
                item0 = QTableWidgetItem(p.file_name)
                item0.setFlags(item0.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 0, item0)

                item1 = QTableWidgetItem(p.shot_time_str)
                item1.setFlags(item1.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 1, item1)

                if p.matched_lat is not None and p.matched_lon is not None:
                    coord_text = f"{p.matched_lat:.6f}, {p.matched_lon:.6f}"
                else:
                    coord_text = "-"
                item2 = QTableWidgetItem(coord_text)
                item2.setFlags(item2.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 2, item2)

                item3 = QTableWidgetItem(p.location_text or "")
                item3.setFlags(item3.flags() | Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 3, item3)
                try:
                    self.table.setRowHeight(int(row), 36)
                except Exception:
                    pass
        finally:
            try:
                self.table.blockSignals(False)
            except Exception:
                pass

        if self._calibrating_row is not None and 0 <= self._calibrating_row < int(row_count):
            try:
                self.table.selectRow(int(self._calibrating_row))
            except Exception:
                pass

    def _on_calibrate_clicked(self):
        try:
            row = int(self.table.currentRow())
        except Exception:
            row = -1
        if row < 0:
            NotificationManager.instance().show_warning("提示", "请先在表格中选中一张图片")
            return
        self._enter_calibration(int(row))

    def _enter_calibration(self, row: int):
        if row < 0 or row >= len(self._photos):
            return
        if not self._track_points:
            NotificationManager.instance().show_warning("提示", "请先选择轨迹文件")
            return
        if self._photos[row].shot_ts is None:
            NotificationManager.instance().show_warning("提示", "该图片缺少拍摄时间，无法校准")
            return
        self._calibrating_row = int(row)
        try:
            self.table.selectRow(int(row))
        except Exception:
            pass
        self._toast("请在轨迹上点击一个点，用于时间校准")

    def _on_track_point_clicked(self, lat: float, lng: float, time_iso: str):
        row = None
        if self._calibrating_row is not None:
            row = int(self._calibrating_row)
        else:
            try:
                row = int(self.table.currentRow())
            except Exception:
                row = None
        if row is None or row < 0:
            if self._photos:
                row = 0
                try:
                    self.table.selectRow(0)
                except Exception:
                    pass
            else:
                return
        if row < 0 or row >= len(self._photos):
            return

        photo = self._photos[row]
        if self._calibrating_row is not None:
            if photo.shot_ts is None:
                return
            tp_ts = _parse_iso_to_ts(time_iso)
            if tp_ts is None:
                NotificationManager.instance().show_warning("提示", "该轨迹点缺少时间信息，无法校准")
                return

            delta = float(photo.shot_ts) - float(tp_ts)
            self._calibration_deltas.append(delta)
            self._time_offset_seconds = _median(self._calibration_deltas)
            self._match_all_photos()
            try:
                self._photos[row].matched_lat = float(lat)
                self._photos[row].matched_lon = float(lng)
            except Exception:
                pass
            self._render_table()

            self._toast("已应用时间校准并重新匹配")
            self._calibrating_row = None
        else:
            try:
                self._photos[row].matched_lat = float(lat)
                self._photos[row].matched_lon = float(lng)
            except Exception:
                pass
            self._render_table()

    def _start_reverse_geocode(self, row_index: int, lat: float, lng: float, service_id: str):
        if row_index < 0 or row_index >= len(self._photos):
            return
        if not bool(getattr(self, "_allow_geocode", False)):
            return
        if self._is_tianditu_service_selected() and (service_id in ("tianditu", "__follow__")):
            remain = self._tianditu_cooldown_remaining()
            if remain > 0:
                try:
                    self._apply_tianditu_cooldown_ui()
                except Exception:
                    pass
                return

        try:
            worker = self._reverse_workers.get(int(row_index))
            if worker and worker.isRunning():
                return
        except Exception:
            pass

        w = _ReverseGeocodeWorker(int(row_index), float(lat), float(lng), str(service_id or "__follow__"))
        w.done.connect(self._on_reverse_done)
        self._reverse_workers[int(row_index)] = w
        w.start()

    def _on_reverse_done(self, row_index: int, addr: str):
        if row_index < 0 or row_index >= len(self._photos):
            return
        a = str(addr or "").strip()
        if a:
            self._photos[row_index].location_text = a
            self._render_table()
            if self._is_tianditu_service_selected():
                self._start_tianditu_cooldown()

    def _sync_location_edits_from_table(self):
        if not getattr(self, "table", None):
            return
        try:
            row_count = int(self.table.rowCount())
        except Exception:
            row_count = 0
        if row_count <= 0:
            return
        for row in range(row_count):
            try:
                if row >= len(self._photos):
                    continue
                item = self.table.item(row, 3)
                if item is None:
                    continue
                self._photos[row].location_text = str(item.text() or "")
            except Exception:
                continue

    def _on_table_item_changed(self, item: QTableWidgetItem):
        try:
            if item is None:
                return
            col = int(item.column())
            row = int(item.row())
        except Exception:
            return
        if col != 3:
            return
        if row < 0 or row >= len(self._photos):
            return
        try:
            self._photos[row].location_text = str(item.text() or "")
        except Exception:
            pass

    def _on_save_clicked(self):
        if not self._photos:
            NotificationManager.instance().show_warning("提示", "没有可保存的图片")
            return
        try:
            self._sync_location_edits_from_table()
        except Exception:
            pass
        valid = [p for p in self._photos if p.file_path and p.matched_lat is not None and p.matched_lon is not None]
        if not valid:
            NotificationManager.instance().show_warning("提示", "请先应用轨迹并生成坐标")
            return
        try:
            if self._save_worker and self._save_worker.isRunning():
                self._toast("正在保存中…")
                return
        except Exception:
            pass

        self._toast("正在保存到数据库和Exif…")
        self.save_btn.setEnabled(False)
        self._save_worker = _GeoSaveWorker(self._photos, self.table_name)
        self._save_worker.finished_ok.connect(self._on_save_done)
        self._save_worker.failed.connect(self._on_save_failed)
        self._save_worker.finished.connect(lambda: self.save_btn.setEnabled(True))
        self._save_worker.start()

    def _on_save_done(self, saved: int, skipped: int):
        self._toast(f"保存完成：成功 {int(saved)}，跳过 {int(skipped)}")
        try:
            self.accept()
        except Exception:
            try:
                self.close()
            except Exception:
                pass

    def _on_save_failed(self, msg: str):
        NotificationManager.instance().show_warning("错误", str(msg or "保存失败"))


def _bisect_left(arr: list[float], x: float) -> int:
    lo = 0
    hi = len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    v = sorted(float(x) for x in values)
    n = len(v)
    mid = n // 2
    if n % 2 == 1:
        return float(v[mid])
    return float((v[mid - 1] + v[mid]) / 2.0)


def _parse_iso_to_ts(time_str: str | None) -> float | None:
    s = str(time_str or "").strip()
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        return float(dt.timestamp())
    except Exception:
        return None


def _parse_photo_time_to_ts(value: Any) -> float | None:
    s = str(value or "").strip()
    if not s:
        return None
    s2 = s.replace("T", " ").strip()
    if s2.endswith("Z"):
        s2 = s2[:-1].strip()
    fmts = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y:%m:%d %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y:%m:%d",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s2, fmt)
            return float(dt.timestamp())
        except Exception:
            continue
    try:
        if len(s2) >= 19 and s2[4] == ":" and s2[7] == ":":
            s3 = f"{s2[0:4]}-{s2[5:7]}-{s2[8:10]}{s2[10:]}"
            dt = datetime.strptime(s3, "%Y-%m-%d %H:%M:%S")
            return float(dt.timestamp())
    except Exception:
        pass
    return None


def _load_photo_items(file_paths: list[str], table_name: str) -> list[PhotoItem]:
    if not file_paths:
        return []
    db = BirdLibraryDB()
    conn = db._get_connection()
    cursor = conn.cursor()

    norm_map: dict[str, str] = {}
    norm_keys: list[str] = []
    for p in file_paths:
        if not p:
            continue
        np = os.path.normcase(os.path.normpath(str(p)))
        norm_map[np] = str(p)
        norm_keys.append(np)

    rows_map: dict[str, Any] = {}
    chunk_size = 500
    for i in range(0, len(norm_keys), chunk_size):
        chunk = norm_keys[i:i + chunk_size]
        if not chunk:
            continue
        placeholders = ",".join(["?"] * len(chunk))
        if os.name == "nt":
            clause = "lower(replace(file_path, '/', '\\'))"
            query_vals = [os.path.normcase(p) for p in chunk]
        else:
            clause = "lower(file_path)"
            query_vals = [p.lower() for p in chunk]
        cursor.execute(
            f"SELECT file_path, shot_time, created_at FROM {table_name} WHERE {clause} IN ({placeholders})",
            query_vals,
        )
        rows = cursor.fetchall()
        for r in rows:
            try:
                rp = str(r["file_path"])
            except Exception:
                try:
                    rp = str(r[0])
                except Exception:
                    continue
            key = os.path.normcase(os.path.normpath(rp))
            rows_map[key] = r

    try:
        conn.close()
    except Exception:
        pass

    items: list[PhotoItem] = []
    for np, orig in norm_map.items():
        shot_time_str = ""
        shot_ts = None
        row = rows_map.get(np)
        if row:
            try:
                shot_time_str = str(row["shot_time"] or "").strip()
            except Exception:
                shot_time_str = ""
            if not shot_time_str:
                try:
                    shot_time_str = str(row["created_at"] or "").strip()
                except Exception:
                    shot_time_str = ""
            shot_ts = _parse_photo_time_to_ts(shot_time_str)
        if shot_ts is None:
            try:
                stat = os.stat(orig)
                shot_ts = float(stat.st_mtime)
                shot_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(shot_ts)))
            except Exception:
                shot_ts = None
                shot_time_str = ""
        items.append(
            PhotoItem(
                file_path=orig,
                file_name=os.path.basename(orig),
                shot_time_str=shot_time_str,
                shot_ts=shot_ts,
            )
        )
    return items


def _load_track_points(track_file_path: str) -> list[TrackPoint]:
    p = str(track_file_path or "")
    if not p or not os.path.exists(p):
        raise FileNotFoundError("轨迹文件不存在")
    ext = os.path.splitext(p)[1].lower().lstrip(".")
    if ext == "gpx":
        return _parse_gpx(p)
    if ext == "kml":
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            return _parse_kml_text(f.read())
    if ext == "kmz":
        return _parse_kmz(p)
    raise ValueError("不支持的轨迹文件格式")


def _parse_gpx(file_path: str) -> list[TrackPoint]:
    tree = ET.parse(file_path)
    root = tree.getroot()
    points: list[TrackPoint] = []
    for tag in ("trkpt", "rtept"):
        for el in root.findall(f".//{{*}}{tag}"):
            lat = el.attrib.get("lat")
            lon = el.attrib.get("lon")
            if lat is None or lon is None:
                continue
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                continue
            time_el = el.find(".//{*}time")
            time_str = (time_el.text.strip() if (time_el is not None and time_el.text) else None)
            ts = _parse_iso_to_ts(time_str) if time_str else None
            points.append(TrackPoint(lat=lat_f, lon=lon_f, time_str=time_str, ts=ts))
    return points


def _parse_kml_text(kml_text: str) -> list[TrackPoint]:
    root = ET.fromstring(kml_text)
    points: list[TrackPoint] = []

    for track in root.findall(".//{*}Track"):
        whens = [w.text.strip() for w in track.findall(".//{*}when") if w.text and w.text.strip()]
        coords = [c.text.strip() for c in track.findall(".//{*}coord") if c.text and c.text.strip()]
        for i, raw in enumerate(coords):
            parts = raw.split()
            if len(parts) < 2:
                continue
            try:
                lon = float(parts[0])
                lat = float(parts[1])
            except Exception:
                continue
            time_str = whens[i] if i < len(whens) else None
            ts = _parse_iso_to_ts(time_str) if time_str else None
            points.append(TrackPoint(lat=lat, lon=lon, time_str=time_str, ts=ts))

    if points:
        return points

    for el in root.findall(".//{*}coordinates"):
        if not el.text:
            continue
        raw = el.text.strip()
        if not raw:
            continue
        parts = raw.replace("\n", " ").replace("\t", " ").split()
        for p in parts:
            vals = p.split(",")
            if len(vals) < 2:
                continue
            try:
                lon = float(vals[0])
                lat = float(vals[1])
            except Exception:
                continue
            points.append(TrackPoint(lat=lat, lon=lon, time_str=None, ts=None))
    return points


def _parse_kmz(file_path: str) -> list[TrackPoint]:
    with zipfile.ZipFile(file_path, "r") as zf:
        kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            return []
        with zf.open(kml_names[0]) as fp:
            data = fp.read()
        for enc in ("utf-8", "gbk"):
            try:
                return _parse_kml_text(data.decode(enc))
            except Exception:
                continue
    return []
