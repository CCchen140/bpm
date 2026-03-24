import os
import re
import tempfile
from datetime import datetime
from threading import Thread
from typing import Any

try:
    import cv2
except Exception:
    cv2 = None
from ui.utils.icon_loader import qta
import json
from PyQt6.QtCore import Qt, QRectF, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QImage, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCompleter,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QStringListModel

try:
    from pypinyin import lazy_pinyin
except Exception:
    lazy_pinyin = None

from core.classifier.bird_biological_classifier import BirdBiologicalClassifier
from core.check_cli import detect_subject_bbox_async, detect_subject_bbox_multi_async
from core.recognizer.bird_species_recognizer import BirdSpeciesRecognizer
from ui.panels.image_detail_panel import MagnifierGraphicsView
from ui.utils.color_manager import ColorManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.status_manager import StatusManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.widgets.custom_progress_dialog import CustomProgressDialog
from utils.exif.exif_utils import EXIF_TAG, ExifHandleWorker
from utils.file.file import load_image
from utils.setting.settings_manager import SettingsManager


class BirdSpeciesDetectDialog(BasePopupDialog):
    _detect_done = pyqtSignal(int, str, object, str)
    _species_done = pyqtSignal(int, str, str)
    _location_done = pyqtSignal(str)
    _shot_time_done = pyqtSignal(str)
    _batch_progress = pyqtSignal(int, int, str)
    _batch_bbox_done = pyqtSignal(str, object, str)
    _batch_species_done = pyqtSignal(str, str, str)
    _batch_done = pyqtSignal(int, int, int, int)

    _species_text_alias_rules_cache: list[dict[str, str]] | None = None

    def __init__(self, parent=None, selected_files=None):
        super().__init__(parent=parent, title="鸟种检测", size=(1100, 760))
        self._settings_manager = SettingsManager()
        self._selected_files = selected_files or []
        self._current_index = 0
        self._current_file = self._selected_files[0] if self._selected_files else {}
        self._current_path = str(self._current_file.get("path") or "")
        self._path_to_file: dict[str, dict] = {}
        try:
            for f in (self._selected_files or []):
                p = str((f or {}).get("path") or "")
                if p:
                    self._path_to_file[p] = f
        except Exception:
            pass

        self._scene = QGraphicsScene()
        self._pix_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pix_item)
        self._rect_item: QGraphicsRectItem | None = None
        self._orig_w = 0
        self._orig_h = 0
        self._preview_scale = 1.0
        self._bbox_xyxy: list[int] | None = None

        self._file_states: dict[str, dict[str, Any]] = {}
        self._seed_file_states_from_selected()
        self._switching_image = False

        self._detect_req_id = 0
        self._species_req_id = 0
        self._detect_tasks: dict[int, int] = {}
        self._species_tasks: dict[int, int] = {}
        self._species_completer: QCompleter | None = None
        self._species_model: QStringListModel | None = None
        self._species_update_timer: QTimer | None = None
        self._species_index: list[dict[str, str]] = []
        self._species_display_map: dict[str, dict[str, str]] = {}
        self._suppress_species_suggestions = False
        self._pinyin_available = lazy_pinyin is not None
        self._pinyin_warned = False
        self._batch_running = False
        self._batch_progress_dialog: CustomProgressDialog | None = None
        self._batch_task_id: int | None = None

        self._init_ui()
        self._detect_done.connect(self._on_detect_done)
        self._species_done.connect(self._on_species_done)
        self._location_done.connect(self._on_location_done)
        self._shot_time_done.connect(self._on_shot_time_done)
        self._batch_progress.connect(self._on_batch_progress)
        self._batch_bbox_done.connect(self._on_batch_bbox_done)
        self._batch_species_done.connect(self._on_batch_species_done)
        self._batch_done.connect(self._on_batch_done)
        self._load_preview_image()
        self._restore_state_for_current()
        self._load_default_location()
        self._load_default_shot_time()
        self._update_nav_visible_state()
        self._update_nav_buttons_pos()

    def _seed_file_states_from_selected(self):
        def parse_bbox(v: Any) -> list[int] | None:
            if v is None:
                return None
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return None
                try:
                    vv = json.loads(s)
                except Exception:
                    vv = None
                v = vv if vv is not None else v
            if isinstance(v, (list, tuple)) and len(v) >= 4:
                try:
                    x1 = int(round(float(v[0])))
                    y1 = int(round(float(v[1])))
                    x2 = int(round(float(v[2])))
                    y2 = int(round(float(v[3])))
                    if x2 <= x1 or y2 <= y1:
                        return None
                    return [x1, y1, x2, y2]
                except Exception:
                    return None
            return None

        for f in (self._selected_files or []):
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "")
            if not p:
                continue
            st = self._file_states.get(p)
            if st is None:
                st = {"bbox": None, "species": "", "order": "", "family": "", "genus": ""}
                self._file_states[p] = st
            try:
                bb = parse_bbox(f.get("bbox"))
                if bb is not None:
                    st["bbox"] = bb
            except Exception:
                pass
            try:
                st["species"] = str(f.get("species") or f.get("object") or "").strip()
            except Exception:
                pass
            try:
                st["order"] = str(f.get("order") or f.get("order_cls") or "").strip()
            except Exception:
                pass
            try:
                st["family"] = str(f.get("family") or f.get("family_cls") or "").strip()
            except Exception:
                pass
            try:
                st["genus"] = str(f.get("genus") or f.get("genus_cls") or "").strip()
            except Exception:
                pass

    def _init_ui(self):
        cm = ColorManager.instance()
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        primary_color = cm.get("theme.primary", "#2196F3")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")

        self.set_title_bar_style(cm.get("popup.header.background", "#2c3e50"), cm.get("popup.header.text", "#FFFFFF"), hover_bg)
        self.set_bottom_bar_style(self.get_footer_background(), border_color)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self._view = MagnifierGraphicsView(self._scene, self)
        self._view.setDragMode(self._view.DragMode.ScrollHandDrag)
        self._view.set_drawing_mode(False)
        self._view.manual_rect_saved.connect(self._on_manual_rect_saved)
        self._view.setMinimumSize(780, 420)
        try:
            self._view.viewport().installEventFilter(self)
            self._view.installEventFilter(self)
        except Exception:
            pass
        left_layout.addWidget(self._view, 1)

        nav_bg = cm.to_qss_color("image_detail.nav_button.background", default="#00000032")
        nav_hover_bg = cm.to_qss_color("image_detail.nav_button.hover_background", default="#00000064")

        self._nav_prev = QPushButton(self._view.viewport())
        self._nav_prev.setIcon(qta.icon("mdi6.chevron-left", color="white"))
        self._nav_prev.setIconSize(QSize(48, 48))
        self._nav_prev.setFixedSize(60, 100)
        self._nav_prev.setStyleSheet(f"""
            QPushButton {{ background-color: {nav_bg}; border: none; border-radius: 5px; }}
            QPushButton:hover {{ background-color: {nav_hover_bg}; }}
        """)
        self._nav_prev.clicked.connect(self._on_prev_image_clicked)
        self._nav_prev.hide()

        self._nav_next = QPushButton(self._view.viewport())
        self._nav_next.setIcon(qta.icon("mdi6.chevron-right", color="white"))
        self._nav_next.setIconSize(QSize(48, 48))
        self._nav_next.setFixedSize(60, 100)
        self._nav_next.setStyleSheet(f"""
            QPushButton {{ background-color: {nav_bg}; border: none; border-radius: 5px; }}
            QPushButton:hover {{ background-color: {nav_hover_bg}; }}
        """)
        self._nav_next.clicked.connect(self._on_next_image_clicked)
        self._nav_next.hide()

        self.current_file_name_label = QLabel("")
        self.current_file_name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.current_file_name_label.setStyleSheet(f"font-size: 12px; color: {text_color};")
        self.current_file_name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        left_layout.addWidget(self.current_file_name_label, 0, alignment=Qt.AlignmentFlag.AlignHCenter)

        btn_container = QWidget()
        btn_row = QHBoxLayout(btn_container)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        left_layout.addWidget(btn_container, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        btn_row.addStretch()

        self.detect_btn = QPushButton(qta.icon("mdi6.target", color=text_color), "检测主体位置")
        self.detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detect_btn.clicked.connect(self._on_detect_subject_clicked)
        btn_row.addWidget(self.detect_btn)

        self.draw_btn = QPushButton(qta.icon("mdi6.vector-rectangle", color=text_color), "手动绘制主体位置")
        self.draw_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.draw_btn.clicked.connect(self._on_toggle_draw_clicked)
        btn_row.addWidget(self.draw_btn)

        self.recognize_btn = QPushButton(qta.icon("ri.voice-recognition-fill", color=text_color), "物种识别")
        self.recognize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recognize_btn.clicked.connect(self._on_recognize_species_clicked)
        btn_row.addWidget(self.recognize_btn)

        self.apply_undetected_btn = QPushButton(qta.icon("mdi6.check-all", color=text_color), "应用未检测文件")
        self.apply_undetected_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_undetected_btn.clicked.connect(self._on_apply_undetected_clicked)
        btn_row.addWidget(self.apply_undetected_btn)

        self.batch_detect_btn = QPushButton(qta.icon("mdi6.auto-fix", color=text_color), "批量检测")
        self.batch_detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.batch_detect_btn.clicked.connect(self._on_batch_detect_clicked)
        btn_row.addWidget(self.batch_detect_btn)

        btn_row.addStretch()

        for b in (self.detect_btn, self.draw_btn, self.recognize_btn, self.apply_undetected_btn, self.batch_detect_btn):
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {control_bg};
                    border: 1px solid {border_color};
                    border-radius: 4px;
                    padding: 8px 12px;
                    font-size: 13px;
                    color: {text_color};
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                    border: 1px solid {primary_color};
                }}
                QPushButton:disabled {{
                    background-color: {border_color};
                    color: #A0A0A0;
                    border: 1px solid {border_color};
                }}
            """)
            try:
                w = int(b.sizeHint().width())
                b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                b.setMinimumWidth(w)
                b.setMaximumWidth(w)
            except Exception:
                pass

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        form_container = QWidget()
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_container.setLayout(form)
        right_layout.addStretch(1)
        right_layout.addWidget(form_container, 0)
        right_layout.addStretch(1)

        form_label_style = f"font-size: 15px; color: {text_color};"

        def _form_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(form_label_style)
            return lbl

        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("输入国家与省份即可")
        self.location_input.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 14px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        try:
            self.location_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        form.addRow(_form_label("地点:"), self.location_input)

        self.shot_time_input = QLineEdit()
        self.shot_time_input.setPlaceholderText("自动读取拍摄时间（可手动修改）")
        self.shot_time_input.setStyleSheet(self.location_input.styleSheet())
        try:
            self.shot_time_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        form.addRow(_form_label("时间:"), self.shot_time_input)

        self.species_input = QLineEdit()
        self.species_input.setPlaceholderText("识别后自动填充（可手动修改）")
        self.species_input.textChanged.connect(self._on_species_changed)
        self.species_input.textEdited.connect(self._on_species_text_changed)
        self.species_input.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 14px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        try:
            self.species_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        form.addRow(_form_label("物种:"), self.species_input)
        self._init_species_suggestions()

        self.order_input = QLineEdit()
        self.order_input.setPlaceholderText("目（可自动补全）")
        self.order_input.textChanged.connect(self._on_classification_field_changed)
        self.order_input.setStyleSheet(self.species_input.styleSheet())
        try:
            self.order_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        form.addRow(_form_label("目:"), self.order_input)

        self.family_input = QLineEdit()
        self.family_input.setPlaceholderText("科（可自动补全）")
        self.family_input.textChanged.connect(self._on_classification_field_changed)
        self.family_input.setStyleSheet(self.species_input.styleSheet())
        try:
            self.family_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        form.addRow(_form_label("科:"), self.family_input)

        self.genus_input = QLineEdit()
        self.genus_input.setPlaceholderText("属（可自动补全）")
        self.genus_input.textChanged.connect(self._on_classification_field_changed)
        self.genus_input.setStyleSheet(self.species_input.styleSheet())
        try:
            self.genus_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        form.addRow(_form_label("属:"), self.genus_input)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        try:
            splitter.setSizes([760, 340])
        except Exception:
            pass

        try:
            self.apply_undetected_btn.setVisible(bool(len(self._selected_files) > 1))
        except Exception:
            pass
        try:
            self.batch_detect_btn.setVisible(bool(len(self._selected_files) > 1))
        except Exception:
            pass

        self.close_btn = QPushButton("取消")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self._on_close_clicked)
        
        self.confirm_btn = QPushButton("确定")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._on_confirm_clicked)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addWidget(self.confirm_btn)
        
        self.bottom_layout.addLayout(btn_layout)
        
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {control_bg};
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                color: {text_color};
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border: 1px solid {primary_color};
            }}
        """)
        
        self.confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary_color};
                border: 1px solid {primary_color};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                color: #FFFFFF;
            }}
            QPushButton:hover {{
                background-color: {cm.to_qss_color("theme.primary.hover", default="#1976D2")};
                border: 1px solid {cm.to_qss_color("theme.primary.hover", default="#1976D2")};
            }}
            QPushButton:disabled {{
                background-color: {border_color};
                color: #A0A0A0;
                border: 1px solid {border_color};
            }}
        """)
        try:
            self._update_confirm_enabled()
        except Exception:
            pass

    def _on_confirm_clicked(self):
        if bool(getattr(self, "_batch_running", False)):
            NotificationManager.instance().show_toast("批量检测正在进行，请稍候")
            return
        if not self._is_taxonomy_complete():
            NotificationManager.instance().show_warning("提示", "请先填写完整的生物学分类（物种/目/科/属）")
            return
        try:
            self._save_current_state()
        except Exception:
            pass
        self.accept()
        
    def _on_close_clicked(self):
        if bool(getattr(self, "_batch_running", False)):
            NotificationManager.instance().show_toast("批量检测正在进行，请稍候")
            return
        try:
            self._save_current_state()
        except Exception:
            pass
        self.reject()
        
    def get_results(self):
        return self._file_states

    def eventFilter(self, obj, event):
        try:
            if obj is getattr(self, "_view", None) or obj is getattr(getattr(self, "_view", None), "viewport", lambda: None)():
                if event.type() == event.Type.Resize:
                    self._update_nav_buttons_pos()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _update_nav_buttons_pos(self):
        viewport = getattr(self._view, "viewport", lambda: None)()
        if viewport is None:
            return
        vw = int(viewport.width())
        vh = int(viewport.height())
        if vw <= 0 or vh <= 0:
            return
        btn_h = 100
        btn_w = 60
        y = max(0, (vh - btn_h) // 2)
        try:
            self._nav_prev.move(8, y)
            self._nav_next.move(max(0, vw - btn_w - 8), y)
        except Exception:
            pass

    def _update_nav_visible_state(self):
        total = len(self._selected_files)
        show = total > 1
        try:
            self._nav_prev.setVisible(show and self._current_index > 0)
            self._nav_next.setVisible(show and self._current_index < total - 1)
        except Exception:
            pass

    def _state_for_path(self, path: str) -> dict[str, Any]:
        p = str(path or "")
        if not p:
            return {}
        st = self._file_states.get(p)
        if st is None:
            st = {"bbox": None, "species": "", "order": "", "family": "", "genus": ""}
            self._file_states[p] = st
        return st

    def _save_current_state(self):
        path = str(getattr(self, "_current_path", "") or "")
        if not path:
            return
        st = self._state_for_path(path)
        if not st:
            return
        try:
            st["bbox"] = list(self._bbox_xyxy) if self._bbox_xyxy else None
        except Exception:
            st["bbox"] = None
        try:
            st["species"] = str(self.species_input.text() or "").strip()
        except Exception:
            st["species"] = st.get("species", "")
        try:
            st["order"] = str(self.order_input.text() or "").strip()
        except Exception:
            st["order"] = st.get("order", "")
        try:
            st["family"] = str(self.family_input.text() or "").strip()
        except Exception:
            st["family"] = st.get("family", "")
        try:
            st["genus"] = str(self.genus_input.text() or "").strip()
        except Exception:
            st["genus"] = st.get("genus", "")
        f = self._path_to_file.get(path)
        if isinstance(f, dict):
            if st.get("bbox") is not None:
                f["bbox"] = st.get("bbox")
            f["species"] = st.get("species", "")
            f["order"] = st.get("order", "")
            f["family"] = st.get("family", "")
            f["genus"] = st.get("genus", "")

    def _restore_state_for_current(self):
        path = str(getattr(self, "_current_path", "") or "")
        st = self._state_for_path(path)
        self._switching_image = True
        try:
            for w in (self.species_input, self.order_input, self.family_input, self.genus_input):
                try:
                    w.blockSignals(True)
                except Exception:
                    pass
            self.species_input.setText(str(st.get("species", "") or ""))
            self.order_input.setText(str(st.get("order", "") or ""))
            self.family_input.setText(str(st.get("family", "") or ""))
            self.genus_input.setText(str(st.get("genus", "") or ""))
        finally:
            for w in (self.species_input, self.order_input, self.family_input, self.genus_input):
                try:
                    w.blockSignals(False)
                except Exception:
                    pass
            self._switching_image = False

        try:
            species = str(self.species_input.text() or "").strip()
        except Exception:
            species = ""
        if species:
            try:
                need = (not str(st.get("order") or "").strip()) or (not str(st.get("family") or "").strip()) or (not str(st.get("genus") or "").strip())
            except Exception:
                need = True
            if need:
                species2 = self._extract_species_name(species)
                species2 = str(species2 or "").strip()
                if species2:
                    species_for_classifier = self._normalize_species_text(species2)
                    try:
                        t = BirdBiologicalClassifier().classify(species_for_classifier)
                    except Exception:
                        t = None
                    if t is not None:
                        self._switching_image = True
                        try:
                            for w in (self.order_input, self.family_input, self.genus_input):
                                try:
                                    w.blockSignals(True)
                                except Exception:
                                    pass
                            if not (self.order_input.text() or "").strip() and str(getattr(t, "order_cn", "") or "").strip():
                                self.order_input.setText(str(getattr(t, "order_cn", "") or ""))
                                st["order"] = str(getattr(t, "order_cn", "") or "")
                            if not (self.family_input.text() or "").strip() and str(getattr(t, "family_cn", "") or "").strip():
                                self.family_input.setText(str(getattr(t, "family_cn", "") or ""))
                                st["family"] = str(getattr(t, "family_cn", "") or "")
                            if not (self.genus_input.text() or "").strip() and str(getattr(t, "genus_cn", "") or "").strip():
                                self.genus_input.setText(str(getattr(t, "genus_cn", "") or ""))
                                st["genus"] = str(getattr(t, "genus_cn", "") or "")
                        finally:
                            for w in (self.order_input, self.family_input, self.genus_input):
                                try:
                                    w.blockSignals(False)
                                except Exception:
                                    pass
                            self._switching_image = False
                        f = self._path_to_file.get(path)
                        if isinstance(f, dict):
                            f["order"] = st.get("order", "")
                            f["family"] = st.get("family", "")
                            f["genus"] = st.get("genus", "")

        self._bbox_xyxy = None
        try:
            bbox = st.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                self._bbox_xyxy = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
        except Exception:
            self._bbox_xyxy = None
        try:
            self._update_confirm_enabled()
        except Exception:
            pass

    def _is_taxonomy_complete(self) -> bool:
        try:
            species = str(self.species_input.text() or "").strip()
            order = str(self.order_input.text() or "").strip()
            family = str(self.family_input.text() or "").strip()
            genus = str(self.genus_input.text() or "").strip()
        except Exception:
            return False
        return bool(species and order and family and genus)

    def _update_confirm_enabled(self, *args, **kwargs):
        try:
            self.confirm_btn.setEnabled(self._is_taxonomy_complete())
        except Exception:
            pass

        try:
            if self._rect_item is not None:
                if self._rect_item.scene():
                    self._scene.removeItem(self._rect_item)
            self._rect_item = None
        except Exception:
            self._rect_item = None
        if self._bbox_xyxy:
            self._draw_bbox_on_preview(self._bbox_xyxy)

        try:
            lbl = getattr(self, "current_file_name_label", None)
            if lbl is not None:
                name = os.path.basename(str(path or "")) if path else ""
                lbl.setText(name)
                lbl.setToolTip(str(path or ""))
        except Exception:
            pass
        self._load_default_location()
        self._load_default_shot_time()

    def _set_current_index(self, index: int):
        if not self._selected_files:
            return
        try:
            idx = int(index)
        except Exception:
            idx = 0
        idx = max(0, min(idx, len(self._selected_files) - 1))
        if idx == int(getattr(self, "_current_index", 0)):
            return
        self._save_current_state()
        self._current_index = idx
        self._current_file = self._selected_files[idx]
        self._current_path = str(self._current_file.get("path") or "")
        self._load_preview_image()
        self._restore_state_for_current()
        self._update_nav_visible_state()

    def _on_prev_image_clicked(self):
        self._set_current_index(int(getattr(self, "_current_index", 0)) - 1)

    def _on_next_image_clicked(self):
        self._set_current_index(int(getattr(self, "_current_index", 0)) + 1)

    def _load_preview_image(self):
        if not self._current_path or not os.path.exists(self._current_path):
            return
        pix = QPixmap(self._current_path)
        if pix.isNull():
            try:
                img = load_image(self._current_path)
            except Exception:
                img = None
            if img is None:
                return
            try:
                import numpy as np
                if isinstance(img, np.ndarray):
                    if len(img.shape) == 2:
                        rgb = self._to_uint8_gray(img)
                        fmt = QImage.Format.Format_Grayscale8
                        bytes_per_line = int(rgb.strides[0])
                        qimg = QImage(rgb.data, int(rgb.shape[1]), int(rgb.shape[0]), bytes_per_line, fmt).copy()
                        pix = QPixmap.fromImage(qimg)
                    elif len(img.shape) == 3 and int(img.shape[2]) >= 3:
                        bgr = self._to_uint8_bgr(img)
                        rgb = bgr[:, :, ::-1].copy()
                        bytes_per_line = int(rgb.strides[0])
                        qimg = QImage(rgb.data, int(rgb.shape[1]), int(rgb.shape[0]), bytes_per_line, QImage.Format.Format_RGB888).copy()
                        pix = QPixmap.fromImage(qimg)
            except Exception:
                pix = QPixmap()
            if pix.isNull():
                return
        self._orig_w = int(pix.width())
        self._orig_h = int(pix.height())
        max_side = 980
        if max(self._orig_w, self._orig_h) > max_side:
            preview = pix.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        else:
            preview = pix
        self._preview_scale = float(preview.width()) / float(self._orig_w) if self._orig_w > 0 else 1.0
        self._pix_item.setPixmap(preview)
        self._scene.setSceneRect(QRectF(preview.rect()))
        try:
            self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        except Exception:
            pass

    @staticmethod
    def _to_uint8_gray(img):
        import numpy as np

        if not isinstance(img, np.ndarray):
            return None
        a = img
        try:
            if a.dtype == np.uint8:
                out = a
            elif a.dtype == np.uint16:
                out = (a // 257).astype(np.uint8)
            elif a.dtype.kind == "f":
                mx = float(np.nanmax(a)) if a.size else 0.0
                if mx <= 1.5:
                    out = np.clip(a * 255.0, 0, 255).astype(np.uint8)
                else:
                    out = np.clip(a, 0, 255).astype(np.uint8)
            else:
                out = np.clip(a, 0, 255).astype(np.uint8)
            return np.ascontiguousarray(out)
        except Exception:
            return None

    @staticmethod
    def _to_uint8_bgr(img):
        import numpy as np

        if not isinstance(img, np.ndarray):
            return None
        a = img
        try:
            if a.ndim == 2:
                g = BirdSpeciesDetectDialog._to_uint8_gray(a)
                if g is None:
                    return None
                bgr = np.dstack([g, g, g])
                return np.ascontiguousarray(bgr)
            if a.ndim != 3 or int(a.shape[2]) < 3:
                return None
            bgr = a[:, :, :3]
            if bgr.dtype == np.uint8:
                out = bgr
            elif bgr.dtype == np.uint16:
                out = (bgr // 257).astype(np.uint8)
            elif bgr.dtype.kind == "f":
                mx = float(np.nanmax(bgr)) if bgr.size else 0.0
                if mx <= 1.5:
                    out = np.clip(bgr * 255.0, 0, 255).astype(np.uint8)
                else:
                    out = np.clip(bgr, 0, 255).astype(np.uint8)
            else:
                out = np.clip(bgr, 0, 255).astype(np.uint8)
            return np.ascontiguousarray(out)
        except Exception:
            return None

    def _on_toggle_draw_clicked(self):
        try:
            enabled = bool(getattr(self._view, "drawing_mode", False))
        except Exception:
            enabled = False
        if enabled:
            try:
                self._view.set_drawing_mode(False)
            except Exception:
                pass
            return
        NotificationManager.instance().show_toast("左键拖动框选主体，右键保存并退出绘制")
        try:
            self._view.set_drawing_mode(True)
        except Exception:
            pass

    def _on_manual_rect_saved(self, rect: Any):
        try:
            if rect is None:
                return
            if self._preview_scale <= 0:
                return
            r = rect.normalized() if hasattr(rect, "normalized") else rect
            x1 = int(max(0, round(float(r.left()) / self._preview_scale)))
            y1 = int(max(0, round(float(r.top()) / self._preview_scale)))
            x2 = int(max(0, round(float(r.right()) / self._preview_scale)))
            y2 = int(max(0, round(float(r.bottom()) / self._preview_scale)))
            if x2 <= x1 or y2 <= y1:
                return
            self._bbox_xyxy = [x1, y1, x2, y2]
            self._draw_bbox_on_preview(self._bbox_xyxy)
            self._save_current_state()
        except Exception:
            pass

    def _on_detect_subject_clicked(self):
        if not self._current_path:
            return
        self.detect_btn.setEnabled(False)
        task_id = StatusManager.instance().start_task("正在检测主体位置...")
        self._detect_req_id += 1
        req_id = int(self._detect_req_id)
        self._detect_tasks[req_id] = int(task_id)

        def cb(path, bbox, focus_point, position, err):
            _ = focus_point
            _ = position
            try:
                self._detect_done.emit(req_id, str(path or ""), bbox, str(err or ""))
            except Exception:
                pass

        try:
            detect_subject_bbox_async(self._current_path, callback=cb, targets=["bbox_orig"])
        except Exception as e:
            try:
                StatusManager.instance().finish_task(task_id)
            except Exception:
                pass
            try:
                self.detect_btn.setEnabled(True)
            except Exception:
                pass
            NotificationManager.instance().show_warning("错误", f"主体检测失败: {e}")

    def _on_detect_done(self, req_id: int, path: str, bbox: Any, err: str):
        task_id = None
        try:
            task_id = self._detect_tasks.pop(int(req_id), None)
        except Exception:
            task_id = None
        if task_id is not None:
            try:
                StatusManager.instance().finish_task(task_id)
            except Exception:
                pass
        try:
            self.detect_btn.setEnabled(True)
        except Exception:
            pass
        if int(req_id) != int(getattr(self, "_detect_req_id", 0)):
            return
        if path != self._current_path:
            return
        if err:
            NotificationManager.instance().show_warning("错误", f"主体检测失败: {err}")
            return
        xyxy = self._parse_xyxy_bbox(bbox)
        if xyxy is None:
            NotificationManager.instance().show_warning("提示", "未检测到主体位置")
            return
        self._bbox_xyxy = xyxy
        self._draw_bbox_on_preview(xyxy)
        self._save_current_state()
        NotificationManager.instance().show_toast("已检测到主体位置")

    def _parse_xyxy_bbox(self, bbox: Any) -> list[int] | None:
        if bbox is None:
            return None
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                x1 = int(round(float(bbox[0])))
                y1 = int(round(float(bbox[1])))
                x2 = int(round(float(bbox[2])))
                y2 = int(round(float(bbox[3])))
                if x2 <= x1 or y2 <= y1:
                    return None
                return [x1, y1, x2, y2]
            except Exception:
                return None
        return None

    def _draw_bbox_on_preview(self, xyxy: list[int]):
        try:
            if not xyxy or self._preview_scale <= 0:
                return
            x1, y1, x2, y2 = xyxy
            px1 = float(x1) * self._preview_scale
            py1 = float(y1) * self._preview_scale
            pw = max(1.0, float(x2 - x1) * self._preview_scale)
            ph = max(1.0, float(y2 - y1) * self._preview_scale)
            if self._rect_item is not None:
                try:
                    if self._rect_item.scene():
                        self._scene.removeItem(self._rect_item)
                except Exception:
                    pass
                self._rect_item = None
            self._rect_item = QGraphicsRectItem(px1, py1, pw, ph)
            pen = QPen(ColorManager.instance().qcolor("border.subject_rect", default="#f50f0f"))
            pen.setWidth(2)
            self._rect_item.setPen(pen)
            self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._scene.addItem(self._rect_item)
            try:
                self._view.viewport().update()
            except Exception:
                pass
        except Exception:
            pass

    def _on_recognize_species_clicked(self):
        if not self._current_path:
            return
        if self._bbox_xyxy is None:
            NotificationManager.instance().show_warning("提示", "请先检测或手动框选主体位置")
            return
        if cv2 is None:
            NotificationManager.instance().show_warning("错误", "缺少依赖：opencv-python")
            return

        bbox = list(self._bbox_xyxy)
        try:
            location_hint = (self.location_input.text() or "").strip()
        except Exception:
            location_hint = ""
        try:
            time_hint = (self.shot_time_input.text() or "").strip()
        except Exception:
            time_hint = ""

        self.recognize_btn.setEnabled(False)
        task_id = StatusManager.instance().start_task("正在识别物种...")
        self._species_req_id += 1
        req_id = int(self._species_req_id)
        self._species_tasks[req_id] = int(task_id)

        def run():
            import time
            try:
                # 在后台线程中获取GPS信息（避免阻塞UI）
                try:
                    StatusManager.instance().update_task(task_id, "正在获取位置信息...")
                except Exception:
                    pass
                lat, lon, region_code = self._get_gps_for_current_image()

                # 更新状态：正在加载图片
                try:
                    StatusManager.instance().update_task(task_id, "正在加载图片...")
                except Exception:
                    pass

                img = load_image(self._current_path)

                if img is None:
                    raise RuntimeError("读取图片失败")
                h, w = img.shape[:2]
                x1 = max(0, min(int(bbox[0]), w - 1))
                y1 = max(0, min(int(bbox[1]), h - 1))
                x2 = max(0, min(int(bbox[2]), w))
                y2 = max(0, min(int(bbox[3]), h))
                if x2 <= x1 or y2 <= y1:
                    raise RuntimeError("主体框无效")

                # 更新状态：正在裁剪图片
                try:
                    StatusManager.instance().update_task(task_id, "正在裁剪图片...")
                except Exception:
                    pass

                crop = img[y1:y2, x1:x2]
                crop = self._to_uint8_bgr(crop)

                if crop is None:
                    raise RuntimeError("裁剪图片处理失败")

                fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
                os.close(fd)
                try:
                    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    if not ok:
                        raise RuntimeError("裁剪图片编码失败")
                    with open(tmp_path, "wb") as f:
                        f.write(bytes(buf))

                    # 定义状态回调函数，用于更新任务状态
                    def status_callback(message):
                        try:
                            StatusManager.instance().update_task(task_id, message)
                        except Exception:
                            pass

                    text = BirdSpeciesRecognizer().recognize(
                        tmp_path,
                        location_hint=str(location_hint or ""),
                        time_hint=str(time_hint or ""),
                        lat=lat,
                        lon=lon,
                        region_code=region_code,
                        status_callback=status_callback
                    ).text
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

                species = self._extract_species_name(text)
                try:
                    self._species_done.emit(req_id, str(species or ""), "")
                except Exception:
                    pass
            except Exception as e:
                try:
                    self._species_done.emit(req_id, "", str(e))
                except Exception:
                    pass

        Thread(target=run, daemon=True).start()

    def _get_gps_for_current_image(self) -> tuple:
        """
        获取当前图片的GPS坐标和区域代码
        
        优先级：
        1. 数据库中的区域代码
        2. 数据库中用户设置的地理位置
        3. EXIF信息中的区域代码
        4. EXIF信息中的GPS数据
        5. 文字版地理位置（通过地理编码转换）
        
        Returns:
            (lat, lon, region_code) 元组，如果无法获取则返回 (None, None, None)
        """
        # 优先获取区域代码
        try:
            from core.recognizer.geo_filter import get_region_code_for_image
            region_code = get_region_code_for_image(self._current_path)
            if region_code:
                # 有区域代码，尝试获取GPS
                try:
                    from core.recognizer.geo_filter import resolve_image_location
                    location = resolve_image_location(self._current_path)
                    if location:
                        return location.latitude, location.longitude, region_code
                except Exception:
                    pass
                return None, None, region_code
        except Exception:
            pass
        
        # 尝试从数据库/EXIF获取GPS
        try:
            from core.recognizer.geo_filter import resolve_image_location
            location = resolve_image_location(self._current_path)
            if location:
                return location.latitude, location.longitude, location.region_code
        except Exception:
            pass
        
        # 回退：尝试从文字版地理位置获取GPS
        try:
            location_text = (self.location_input.text() or "").strip()
            if location_text:
                from ui.utils.geo_manager import GeoInfoManager
                geo = GeoInfoManager.instance()
                result = geo.geocode(location_text)
                if result:
                    lat, lon, _ = result
                    # 根据GPS推断区域代码
                    try:
                        from core.recognizer.geo_filter import get_geo_index
                        geo_index = get_geo_index()
                        region_code = geo_index.detect_region_from_gps(lat, lon)
                        return lat, lon, region_code
                    except Exception:
                        pass
                    return lat, lon, None
        except Exception:
            pass
        
        return None, None, None

    def _on_species_done(self, req_id: int, species: str, err: str):
        task_id = None
        try:
            task_id = self._species_tasks.pop(int(req_id), None)
        except Exception:
            task_id = None
        if task_id is not None:
            try:
                StatusManager.instance().finish_task(task_id)
            except Exception:
                pass
        try:
            self.recognize_btn.setEnabled(True)
        except Exception:
            pass
        if int(req_id) != int(getattr(self, "_species_req_id", 0)):
            return
        if err:
            NotificationManager.instance().show_warning("错误", f"物种识别失败: {err}")
            return
        s = (species or "").strip()
        if not s:
            NotificationManager.instance().show_warning("提示", "物种识别失败")
            return
        try:
            self.species_input.setText(s)
        except Exception:
            pass
        NotificationManager.instance().show_toast("已填充物种名称")
        try:
            self._save_current_state()
        except Exception:
            pass

    def _on_classification_field_changed(self, _text: str = ""):
        if getattr(self, "_switching_image", False):
            return
        try:
            self._update_confirm_enabled()
        except Exception:
            pass
        try:
            self._save_current_state()
        except Exception:
            pass

    def _on_species_changed(self, _text: str = ""):
        if getattr(self, "_switching_image", False):
            return
        species = (self.species_input.text() or "").strip()
        if not species:
            try:
                self._update_confirm_enabled()
            except Exception:
                pass
            try:
                self._save_current_state()
            except Exception:
                pass
            return
        species_for_classifier = self._normalize_species_text(species)
        try:
            t = BirdBiologicalClassifier().classify(species_for_classifier)
        except Exception:
            t = None
        if t is not None:
            if not (self.order_input.text() or "").strip():
                self.order_input.setText(t.order_cn)
            if not (self.family_input.text() or "").strip():
                self.family_input.setText(t.family_cn)
            if not (self.genus_input.text() or "").strip():
                self.genus_input.setText(t.genus_cn)
        try:
            self._update_confirm_enabled()
        except Exception:
            pass
        try:
            self._save_current_state()
        except Exception:
            pass

    def _on_apply_undetected_clicked(self):
        try:
            multi = len(self._selected_files) > 1
        except Exception:
            multi = False
        if not multi:
            return
        species = (self.species_input.text() or "").strip()
        if not species:
            NotificationManager.instance().show_warning("提示", "请先识别或填写物种名称")
            return
        order = (self.order_input.text() or "").strip()
        family = (self.family_input.text() or "").strip()
        genus = (self.genus_input.text() or "").strip()
        applied = 0
        for f in (self._selected_files or []):
            try:
                src = str((f or {}).get("path") or "")
            except Exception:
                src = ""
            if not src:
                continue
            st = self._state_for_path(src)
            try:
                has_species = bool(str(st.get("species") or "").strip())
            except Exception:
                has_species = False
            if has_species:
                continue
            try:
                st["species"] = str(species)
            except Exception:
                pass
            if order and not str(st.get("order") or "").strip():
                st["order"] = str(order)
            if family and not str(st.get("family") or "").strip():
                st["family"] = str(family)
            if genus and not str(st.get("genus") or "").strip():
                st["genus"] = str(genus)
            f2 = self._path_to_file.get(src)
            if isinstance(f2, dict):
                f2["species"] = st.get("species", "")
                f2["order"] = st.get("order", "")
                f2["family"] = st.get("family", "")
                f2["genus"] = st.get("genus", "")
            applied += 1
        if applied > 0:
            try:
                NotificationManager.instance().show_toast(f"已应用到未检测文件：{applied} 张")
            except Exception:
                pass

    def _set_batch_controls_enabled(self, enabled: bool):
        for w in (
            getattr(self, "detect_btn", None),
            getattr(self, "draw_btn", None),
            getattr(self, "recognize_btn", None),
            getattr(self, "apply_undetected_btn", None),
            getattr(self, "batch_detect_btn", None),
            getattr(self, "close_btn", None),
            getattr(self, "confirm_btn", None),
        ):
            if w is None:
                continue
            try:
                w.setEnabled(bool(enabled))
            except Exception:
                pass

    def _on_batch_detect_clicked(self):
        try:
            multi = len(self._selected_files) > 1
        except Exception:
            multi = False
        if not multi:
            return
        if bool(getattr(self, "_batch_running", False)):
            NotificationManager.instance().show_toast("批量检测正在进行，请稍候")
            return
        if cv2 is None:
            NotificationManager.instance().show_warning("错误", "缺少依赖：opencv-python")
            return

        paths: list[str] = []
        for f in (self._selected_files or []):
            try:
                p = str((f or {}).get("path") or "").strip()
            except Exception:
                p = ""
            if not p:
                continue
            paths.append(p)
        paths = list(dict.fromkeys(paths))
        if not paths:
            return

        try:
            location_hint = (self.location_input.text() or "").strip()
        except Exception:
            location_hint = ""
        try:
            time_hint = (self.shot_time_input.text() or "").strip()
        except Exception:
            time_hint = ""

        self._batch_running = True
        self._batch_bbox_added = 0
        self._batch_species_added = 0
        self._batch_failed = 0

        try:
            self._batch_task_id = StatusManager.instance().start_task("正在批量检测...")
        except Exception:
            self._batch_task_id = None

        try:
            dlg = CustomProgressDialog(title="批量检测", message="正在准备...")
            dlg.setMaximum(1)
            dlg.setValue(0)
            dlg.show()
            self._batch_progress_dialog = dlg
        except Exception:
            self._batch_progress_dialog = None

        self._set_batch_controls_enabled(False)

        def run():
            try:
                needs_bbox: list[str] = []
                needs_species: list[str] = []
                for p in paths:
                    st = self._state_for_path(p)
                    try:
                        has_bbox = isinstance(st.get("bbox"), (list, tuple)) and len(st.get("bbox") or []) >= 4
                    except Exception:
                        has_bbox = False
                    if not has_bbox:
                        needs_bbox.append(p)
                    try:
                        has_species = bool(str(st.get("species") or "").strip())
                    except Exception:
                        has_species = False
                    if not has_species:
                        needs_species.append(p)

                if needs_bbox:
                    try:
                        self._batch_progress.emit(0, int(len(needs_bbox)), "正在批量检测主体框...")
                    except Exception:
                        pass
                    import threading

                    lock = threading.Lock()
                    done_event = threading.Event()
                    pending = set(needs_bbox)
                    done = 0

                    def cb(p, bbox, _fp, _pos, err):
                        nonlocal done
                        p2 = str(p or "").strip()
                        with lock:
                            if p2 in pending:
                                pending.remove(p2)
                            done += 1
                            done2 = int(done)
                            total2 = int(len(needs_bbox))
                        try:
                            self._batch_bbox_done.emit(str(p2), bbox, str(err or ""))
                        except Exception:
                            pass
                        try:
                            self._batch_progress.emit(int(done2), int(total2), f"正在检测主体框：{done2}/{total2}")
                        except Exception:
                            pass
                        if done2 >= int(total2):
                            try:
                                done_event.set()
                            except Exception:
                                pass

                    fut = None
                    try:
                        fut = detect_subject_bbox_multi_async(needs_bbox, callback=cb, targets=["bbox_orig"])
                    except Exception as e:
                        for p in list(needs_bbox):
                            try:
                                self._batch_bbox_done.emit(str(p), None, str(e))
                            except Exception:
                                pass
                        pending = set()
                        done_event.set()

                    timeout_seconds = 60 * 30
                    if fut is not None:
                        try:
                            fut.result(timeout=int(timeout_seconds))
                        except Exception:
                            pass
                    try:
                        done_event.wait(timeout=float(timeout_seconds))
                    except Exception:
                        pass
                    for p in list(pending):
                        try:
                            self._batch_bbox_done.emit(str(p), None, "检测超时")
                        except Exception:
                            pass

                needs_species2: list[str] = []
                for p in needs_species:
                    st = self._state_for_path(p)
                    try:
                        has_bbox = isinstance(st.get("bbox"), (list, tuple)) and len(st.get("bbox") or []) >= 4
                    except Exception:
                        has_bbox = False
                    if not has_bbox:
                        try:
                            self._batch_species_done.emit(str(p), "", "缺少主体框")
                        except Exception:
                            pass
                        continue
                    needs_species2.append(p)

                if needs_species2:
                    try:
                        self._batch_progress.emit(0, int(len(needs_species2)), "正在批量识别物种...")
                    except Exception:
                        pass
                    done2 = 0
                    for p in needs_species2:
                        done2 += 1
                        try:
                            st = self._state_for_path(p)
                            bbox = st.get("bbox")
                        except Exception:
                            bbox = None
                        xyxy = self._parse_xyxy_bbox(bbox)
                        if xyxy is None:
                            try:
                                self._batch_species_done.emit(str(p), "", "主体框无效")
                            except Exception:
                                pass
                            try:
                                self._batch_progress.emit(int(done2), int(len(needs_species2)), f"正在识别物种：{done2}/{len(needs_species2)}")
                            except Exception:
                                pass
                            continue

                        try:
                            img = load_image(p)
                            if img is None:
                                raise RuntimeError("读取图片失败")
                            h, w = img.shape[:2]
                            x1 = max(0, min(int(xyxy[0]), w - 1))
                            y1 = max(0, min(int(xyxy[1]), h - 1))
                            x2 = max(0, min(int(xyxy[2]), w))
                            y2 = max(0, min(int(xyxy[3]), h))
                            if x2 <= x1 or y2 <= y1:
                                raise RuntimeError("主体框无效")
                            crop = img[y1:y2, x1:x2]
                            crop = self._to_uint8_bgr(crop)
                            if crop is None:
                                raise RuntimeError("裁剪图片处理失败")
                            fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
                            os.close(fd)
                            try:
                                ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                                if not ok:
                                    raise RuntimeError("裁剪图片编码失败")
                                with open(tmp_path, "wb") as f:
                                    f.write(bytes(buf))
                                text = BirdSpeciesRecognizer().recognize(tmp_path, location_hint=str(location_hint or ""), time_hint=str(time_hint or "")).text
                            finally:
                                try:
                                    os.remove(tmp_path)
                                except Exception:
                                    pass
                            species = self._extract_species_name(text)
                            if not str(species or "").strip():
                                raise RuntimeError("物种识别失败")
                            try:
                                self._batch_species_done.emit(str(p), str(species), "")
                            except Exception:
                                pass
                        except Exception as e:
                            try:
                                self._batch_species_done.emit(str(p), "", str(e))
                            except Exception:
                                pass
                        try:
                            self._batch_progress.emit(int(done2), int(len(needs_species2)), f"正在识别物种：{done2}/{len(needs_species2)}")
                        except Exception:
                            pass
            finally:
                try:
                    self._batch_done.emit(int(len(paths)), 0, 0, 0)
                except Exception:
                    pass

        Thread(target=run, daemon=True).start()

    def _on_batch_progress(self, done: int, total: int, msg: str):
        dlg = getattr(self, "_batch_progress_dialog", None)
        if dlg is None:
            return
        try:
            dlg.setLabelText(str(msg or ""))
        except Exception:
            pass
        try:
            t = int(total)
        except Exception:
            t = 0
        if t <= 0:
            t = 1
        try:
            dlg.setMaximum(int(t))
        except Exception:
            pass
        try:
            v = int(done)
        except Exception:
            v = 0
        v = max(0, min(v, int(t)))
        try:
            dlg.setValue(int(v))
        except Exception:
            pass

    def _on_batch_bbox_done(self, path: str, bbox: Any, err: str):
        p = str(path or "").strip()
        if not p:
            return
        if str(err or "").strip():
            try:
                self._batch_failed += 1
            except Exception:
                pass
            return
        xyxy = self._parse_xyxy_bbox(bbox)
        if xyxy is None:
            try:
                self._batch_failed += 1
            except Exception:
                pass
            return
        st = self._state_for_path(p)
        try:
            had = isinstance(st.get("bbox"), (list, tuple)) and len(st.get("bbox") or []) >= 4
        except Exception:
            had = False
        if not had:
            try:
                st["bbox"] = list(xyxy)
            except Exception:
                pass
            try:
                self._batch_bbox_added += 1
            except Exception:
                pass
            f2 = self._path_to_file.get(p)
            if isinstance(f2, dict):
                try:
                    f2["bbox"] = list(xyxy)
                except Exception:
                    pass
        if p == getattr(self, "_current_path", ""):
            try:
                self._bbox_xyxy = list(xyxy)
                self._draw_bbox_on_preview(list(xyxy))
            except Exception:
                pass

    def _on_batch_species_done(self, path: str, species: str, err: str):
        p = str(path or "").strip()
        if not p:
            return
        if str(err or "").strip():
            try:
                self._batch_failed += 1
            except Exception:
                pass
            return
        s = str(species or "").strip()
        if not s:
            try:
                self._batch_failed += 1
            except Exception:
                pass
            return
        st = self._state_for_path(p)
        try:
            had = bool(str(st.get("species") or "").strip())
        except Exception:
            had = False
        if not had:
            try:
                st["species"] = str(s)
            except Exception:
                pass
            try:
                self._batch_species_added += 1
            except Exception:
                pass
            f2 = self._path_to_file.get(p)
            if isinstance(f2, dict):
                try:
                    f2["species"] = str(s)
                except Exception:
                    pass
        if p == getattr(self, "_current_path", ""):
            try:
                if not (self.species_input.text() or "").strip():
                    self.species_input.setText(str(s))
            except Exception:
                pass

    def _on_batch_done(self, total: int, _a: int, _b: int, _c: int):
        try:
            tid = getattr(self, "_batch_task_id", None)
            if tid is not None:
                StatusManager.instance().finish_task(int(tid))
        except Exception:
            pass
        try:
            self._batch_task_id = None
        except Exception:
            pass

        dlg = getattr(self, "_batch_progress_dialog", None)
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass
        try:
            self._batch_progress_dialog = None
        except Exception:
            pass

        self._batch_running = False
        self._set_batch_controls_enabled(True)

        try:
            cache: dict[str, Any] = {}
            for f in (self._selected_files or []):
                try:
                    p = str((f or {}).get("path") or "").strip()
                except Exception:
                    p = ""
                if not p:
                    continue
                st = self._state_for_path(p)
                try:
                    raw_species = str(st.get("species") or "").strip()
                except Exception:
                    raw_species = ""
                if not raw_species:
                    continue
                try:
                    need = (not str(st.get("order") or "").strip()) or (not str(st.get("family") or "").strip()) or (not str(st.get("genus") or "").strip())
                except Exception:
                    need = True
                if not need:
                    continue
                species2 = self._extract_species_name(raw_species)
                species2 = str(species2 or "").strip()
                if not species2:
                    continue
                species_for_classifier = self._normalize_species_text(species2)
                t = cache.get(species_for_classifier)
                if t is None and species_for_classifier not in cache:
                    try:
                        t = BirdBiologicalClassifier().classify(species_for_classifier)
                    except Exception:
                        t = None
                    cache[species_for_classifier] = t
                if t is None:
                    continue
                if not str(st.get("order") or "").strip():
                    st["order"] = str(getattr(t, "order_cn", "") or "")
                if not str(st.get("family") or "").strip():
                    st["family"] = str(getattr(t, "family_cn", "") or "")
                if not str(st.get("genus") or "").strip():
                    st["genus"] = str(getattr(t, "genus_cn", "") or "")
                f2 = self._path_to_file.get(p)
                if isinstance(f2, dict):
                    f2["order"] = st.get("order", "")
                    f2["family"] = st.get("family", "")
                    f2["genus"] = st.get("genus", "")
        except Exception:
            pass

        try:
            self._restore_state_for_current()
        except Exception:
            pass

        try:
            t = int(total)
        except Exception:
            t = 0
        try:
            added_bbox = int(getattr(self, "_batch_bbox_added", 0) or 0)
        except Exception:
            added_bbox = 0
        try:
            added_species = int(getattr(self, "_batch_species_added", 0) or 0)
        except Exception:
            added_species = 0
        try:
            failed = int(getattr(self, "_batch_failed", 0) or 0)
        except Exception:
            failed = 0

        msg = f"批量检测完成：共 {t} 张，新增主体框 {added_bbox} 张，新增物种 {added_species} 张，失败 {failed} 张"
        NotificationManager.instance().show_toast(msg)

    def _extract_species_name(self, text: str) -> str:
        s = str(text or "").strip()
        if not s:
            return ""
        for sep in ("，", ",", "|", "｜", "；", ";"):
            if sep in s:
                parts = [p.strip() for p in s.split(sep) if p.strip()]
                if parts:
                    return parts[-1]
        return s

    def _normalize_species_text(self, text: str) -> str:
        s = str(text or "")
        if not s:
            return ""
        rules = self._load_species_text_alias_rules()
        if not rules:
            return s
        out = s
        for r in rules:
            try:
                src = str(r.get("from") or "")
                dst = str(r.get("to") or "")
            except Exception:
                src = ""
                dst = ""
            if not src or not dst:
                continue
            out = out.replace(src, dst)
        return out

    def _load_species_text_alias_rules(self) -> list[dict[str, str]]:
        cached = getattr(BirdSpeciesDetectDialog, "_species_text_alias_rules_cache", None)
        if cached is not None:
            return cached
        data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "species_text_aliases.json"))
        if not os.path.exists(data_path):
            data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "species_text_aliases.json"))
        rules: list[dict[str, str]] = []
        try:
            import json
            with open(data_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = []
        if isinstance(raw, list):
            for it in raw:
                if not isinstance(it, dict):
                    continue
                src = str(it.get("from") or "").strip()
                dst = str(it.get("to") or "").strip()
                if not src or not dst:
                    continue
                rules.append({"from": src, "to": dst})
        BirdSpeciesDetectDialog._species_text_alias_rules_cache = rules
        return rules

    def _on_species_text_changed(self, _text: str = ""):
        if getattr(self, "_suppress_species_suggestions", False):
            return
        if self._species_update_timer is None:
            return
        try:
            self._species_update_timer.start()
        except Exception:
            pass

    def _init_species_suggestions(self):
        self._species_index = self._load_species_index()
        self._species_display_map = {}
        self._species_model = QStringListModel([])
        self._species_completer = QCompleter(self._species_model, self)
        self._species_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._species_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._species_completer.setMaxVisibleItems(20)
        self._species_completer.activated.connect(self._on_species_selected)
        self.species_input.setCompleter(self._species_completer)
        try:
            popup = self._species_completer.popup()
            row_h = max(18, int(popup.sizeHintForRow(0)) if popup is not None else 18)
            popup.setMinimumHeight(row_h * 10 + 8)
        except Exception:
            pass

        self._species_update_timer = QTimer(self)
        self._species_update_timer.setSingleShot(True)
        self._species_update_timer.setInterval(120)
        self._species_update_timer.timeout.connect(self._update_species_suggestions)
        self._update_species_suggestions()

    def _on_species_selected(self, text: str):
        try:
            s = str(text or "").strip()
        except Exception:
            s = ""
        if not s:
            return
        mapped_cn = ""
        mapped_la = ""
        try:
            mapped = self._species_display_map.get(s)
            if isinstance(mapped, dict):
                mapped_cn = str(mapped.get("cn") or "").strip()
                mapped_la = str(mapped.get("la") or "").strip()
        except Exception:
            mapped_cn = ""
            mapped_la = ""
        try:
            self._suppress_species_suggestions = True
            self.species_input.setText(mapped_cn or s)
            if mapped_la:
                self.species_input.setToolTip(f"拉丁名: {mapped_la}")
        except Exception:
            pass
        try:
            if self._species_update_timer is not None:
                self._species_update_timer.stop()
        except Exception:
            pass
        try:
            if self._species_completer is not None:
                self._species_completer.popup().hide()
        except Exception:
            pass
        try:
            QTimer.singleShot(0, lambda: setattr(self, "_suppress_species_suggestions", False))
        except Exception:
            self._suppress_species_suggestions = False

    def _load_species_index(self) -> list[dict[str, str]]:
        data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "bird_classification.json"))
        if not os.path.exists(data_path):
            data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "bird_classification.json"))
        try:
            import json as _json
            with open(data_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            return []

        items: list[dict[str, str]] = []
        for name, v in data.items():
            if not isinstance(name, str) or not isinstance(v, dict):
                continue
            cn = name.strip()
            if not cn:
                continue
            latin = str(v.get("name_la") or "").strip()
            latin_lower = latin.lower()
            latin_norm = re.sub(r"[^a-z\s\.\-]+", " ", latin_lower)
            latin_norm = re.sub(r"[\s\.\-]+", " ", latin_norm).strip()
            py = ""
            initials = ""
            if lazy_pinyin is not None:
                try:
                    py_list = lazy_pinyin(cn, errors="ignore")
                    py = "".join(py_list).lower()
                    initials = "".join([(p[0] if p else "") for p in py_list]).lower()
                except Exception:
                    py = ""
                    initials = ""
            items.append(
                {
                    "name": cn,
                    "name_lower": cn.lower(),
                    "pinyin": py,
                    "initials": initials,
                    "latin": latin,
                    "latin_norm": latin_norm,
                }
            )
        return items

    def _update_species_suggestions(self):
        if self._species_model is None:
            return
        if self._species_completer is None:
            return
        if getattr(self, "_suppress_species_suggestions", False):
            try:
                self._species_completer.popup().hide()
            except Exception:
                pass
            return
        q_raw = (self.species_input.text() or "").strip()
        q = self._normalize_species_text(q_raw).lower()
        if not q:
            self._species_model.setStringList([])
            try:
                self._species_completer.popup().hide()
            except Exception:
                pass
            return

        q_norm = re.sub(r"\s+", "", q)
        tokens = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", q_norm, flags=re.IGNORECASE)
        if not tokens:
            self._species_model.setStringList([])
            try:
                self._species_completer.popup().hide()
            except Exception:
                pass
            return

        if any(t.isascii() and t.isalpha() for t in tokens) and (not self._pinyin_available) and (not self._pinyin_warned):
            self._pinyin_warned = True
            NotificationManager.instance().show_toast("未安装 pypinyin，拼音联想不可用")

        matched: list[tuple[int, int, str]] = []
        display_map: dict[str, dict[str, str]] = {}
        for it in self._species_index:
            name = it.get("name", "")
            name_lower = it.get("name_lower", "")
            py = it.get("pinyin", "")
            initials = it.get("initials", "")
            latin = it.get("latin", "")
            latin_norm = it.get("latin_norm", "")

            score_sum = 0
            ok = True
            used_latin = False
            for t in tokens:
                if not t:
                    continue
                if not t.isascii():
                    token = self._normalize_species_text(t).lower()
                    if token not in name_lower:
                        ok = False
                        break
                    continue

                t2 = t.lower()
                if py and t2 in py:
                    score_sum += 1
                elif initials and t2 in initials:
                    score_sum += 2
                elif latin_norm and t2 in latin_norm:
                    used_latin = True
                    score_sum += 4
                else:
                    ok = False
                    break
            if not ok:
                continue
            if used_latin and latin:
                display = f"{str(name or '')}  —  {str(latin or '')}"
            else:
                display = str(name or "")
            matched.append((score_sum, len(name), display))
            if used_latin and latin:
                try:
                    display_map[display] = {"cn": str(name or ""), "la": str(latin or "")}
                except Exception:
                    pass

        matched.sort(key=lambda x: (x[0], x[1]))
        suggestions = []
        seen = set()
        for _, _, s in matched:
            key = str(s or "").strip()
            if not key:
                continue
            if "—" in key:
                cn_key = key.split("—", 1)[0].strip().lower()
            else:
                cn_key = key.lower()
            if cn_key in seen:
                continue
            seen.add(cn_key)
            suggestions.append(key)
            if len(suggestions) >= 300:
                break
        self._species_display_map = display_map
        self._species_model.setStringList(suggestions)
        if len(suggestions) <= 0:
            try:
                self._species_completer.popup().hide()
            except Exception:
                pass
            return
        try:
            self._species_completer.setCompletionPrefix("")
            self._species_completer.complete()
        except Exception:
            pass

    def _load_default_location(self):
        if not self._current_path:
            return
        if not hasattr(self, "location_input") or self.location_input is None:
            return
        try:
            if (self.location_input.text() or "").strip():
                return
        except Exception:
            pass

        def run():
            text = ""
            try:
                # 优先从数据库读取已设置的地理位置
                from utils.sql.data_base import BirdLibraryDB
                db = BirdLibraryDB()
                record = db.get_result_by_path(self._current_path, table_name="bird_results")
                if not record:
                    record = db.get_result_by_path(self._current_path, table_name="import_cache")
                if record:
                    loc = record.get("location")
                    if loc and str(loc).strip():
                        text = str(loc).strip()
            except Exception:
                pass
            
            # 如果数据库没有，回退到EXIF读取
            if not text:
                try:
                    raw = ExifHandleWorker.get_instance().read_tag(self._current_path, EXIF_TAG.Location.value, timeout=3)
                    text = self._extract_country_province(raw) or ""
                except Exception:
                    pass
            
            if text:
                try:
                    self._location_done.emit(text)
                except Exception:
                    pass

        Thread(target=run, daemon=True).start()

    def _on_location_done(self, text: str):
        try:
            if not text:
                return
            if (self.location_input.text() or "").strip():
                return
            self.location_input.setText(text)
        except Exception:
            pass

    def _load_default_shot_time(self):
        if not self._current_path:
            return
        if not hasattr(self, "shot_time_input") or self.shot_time_input is None:
            return
        try:
            if (self.shot_time_input.text() or "").strip():
                return
        except Exception:
            pass

        def run():
            text = ""
            try:
                dt = ExifHandleWorker.get_instance().get_time(self._current_path)
            except Exception:
                dt = None
            try:
                if dt is not None:
                    text = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                text = ""
            if not text:
                try:
                    ts = os.path.getctime(self._current_path)
                    text = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    text = ""
            try:
                self._shot_time_done.emit(text)
            except Exception:
                pass

        Thread(target=run, daemon=True).start()

    def _on_shot_time_done(self, text: str):
        try:
            if not text:
                return
            if (self.shot_time_input.text() or "").strip():
                return
            self.shot_time_input.setText(text)
        except Exception:
            pass

    def _extract_country_province(self, raw: Any) -> str:
        s = str(raw or "").strip()
        if not s:
            return ""
        s = s.replace("|", " ").replace("/", " ").replace("；", " ").replace(";", " ")
        s = s.replace("，", ",")
        parts = [p.strip() for p in re.split(r"[,\\s]+", s) if p.strip()]
        if len(parts) >= 2:
            return f"{parts[0]} {parts[1]}"
        if len(parts) == 1:
            single = parts[0]
            if "中国" in single:
                country = "中国"
                rest = single.replace("中华人民共和国", "").replace("中国", "")
                m = re.search(r"(.+?(省|自治区|特别行政区))", rest)
                if m:
                    return f"{country} {m.group(1)}"
                return country
            m = re.search(r"(.+?)(省|自治区|特别行政区)", single)
            if m:
                return m.group(0)
            return single
        return ""
