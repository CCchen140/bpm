import os
import re
import shutil
import tempfile
from datetime import datetime
from threading import Thread
from typing import Any

import cv2
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QEvent, QTimer, QStringListModel, QSize
from PyQt6.QtGui import QPixmap, QPen, QBrush, QImage
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QPushButton,
    QSizePolicy,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QCompleter,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QCheckBox,
)
import qtawesome as qta

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

from core.classifier.bird_biological_classifier import BirdBiologicalClassifier
from core.recognizer.bird_species_recognizer import BirdSpeciesRecognizer
from core.check_cli import detect_subject_bbox_async
from ui.panels.image_detail_panel import MagnifierGraphicsView
from ui.utils.color_manager import ColorManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.status_manager import StatusManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from utils.exif.exif_utils import EXIF_TAG, ExifHandleWorker
from utils.file.file import load_image
from utils.file.file_util import get_fast_id
from utils.file.fingerprint import get_unique_id
from utils.setting.settings_manager import SettingsManager
from utils.sql.data_base import BirdLibraryDB


class ImportToLibraryDialog(BasePopupDialog):
    _detect_done = pyqtSignal(int, str, object, str)
    _species_done = pyqtSignal(int, str, str)
    _bg_detect_done = pyqtSignal(int, str, object, str)
    _bg_species_done = pyqtSignal(int, str, str, str)
    _import_done = pyqtSignal(int, bool, int, str)
    _location_done = pyqtSignal(str)
    _shot_time_done = pyqtSignal(str)
    import_succeeded = pyqtSignal(str)

    _species_text_alias_rules_cache: list[dict[str, str]] | None = None

    def __init__(self, parent=None, selected_files=None):
        super().__init__(parent=parent, title="导入图库", size=(1100, 780))
        self._settings_manager = SettingsManager()
        self._db = BirdLibraryDB()
        self._selected_files = selected_files or []
        self._current_file = self._selected_files[0] if self._selected_files else {}
        self._current_path = str(self._current_file.get("path") or "")
        self._current_index = 0

        self._orig_w = 0
        self._orig_h = 0
        self._preview_scale = 1.0
        self._bbox_xyxy: list[int] | None = None
        self._rect_item: QGraphicsRectItem | None = None
        self._file_states: dict[str, dict[str, Any]] = {}
        self._switching_image = False
        self._loop_enabled = False
        self._loop_running = False
        self._bg_token = 0
        self._bg_running = False
        self._bg_inflight = False
        self._bg_inflight_path = ""
        self._bg_inflight_kind = ""
        self._bg_queue: list[str] = []
        self._bg_pos = 0
        self._bg_current_path = ""
        self._bg_priority_path = ""
        self._path_to_file: dict[str, dict] = {}
        try:
            for f in (self._selected_files or []):
                p = str((f or {}).get("path") or "")
                if p:
                    self._path_to_file[p] = f
        except Exception:
            pass

        self._preview_map: dict[str, str] = {}
        self._preview_meta_map: dict[str, dict[str, str]] = {}
        self._import_running = False
        self._detect_req_id = 0
        self._species_req_id = 0
        self._detect_tasks: dict[int, int] = {}
        self._species_tasks: dict[int, int] = {}
        self._import_req_id = 0
        self._import_task_id: int | None = None
        self._species_index: list[dict[str, str]] = []
        self._species_display_map: dict[str, dict[str, str]] = {}
        self._species_completer: QCompleter | None = None
        self._species_model: QStringListModel | None = None
        self._species_update_timer: QTimer | None = None
        self._pinyin_available = lazy_pinyin is not None
        self._pinyin_warned = False
        self._suppress_species_suggestions = False
        self._last_import_target_folder: str = ""

        self._init_ui()
        self._detect_done.connect(self._on_detect_done)
        self._species_done.connect(self._on_species_done)
        self._bg_detect_done.connect(self._on_bg_detect_done)
        self._bg_species_done.connect(self._on_bg_species_done)
        self._import_done.connect(self._on_import_done)
        self._location_done.connect(self._on_location_done)
        self._shot_time_done.connect(self._on_shot_time_done)
        self._init_species_suggestions()
        self._load_preview_image()
        self._load_default_location()
        self._load_default_shot_time()
        self._restore_state_for_current()
        self._update_import_preview()
        self._update_nav_visible_state()
        self._update_nav_buttons_pos()

    def _init_ui(self):
        cm = ColorManager.instance()
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        primary_color = cm.get("theme.primary", "#2196F3")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        table_header_bg = cm.get("settings.shortcut_table.header.background", "#F5F5F5")
        table_header_border = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        scrollbar_bg = cm.get("settings.shortcut_table.header.background", "#F5F5F5")
        scrollbar_handle = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        scrollbar_handle_hover = cm.get("settings.shortcut_table.row.hover_border", "#D7E3F5")

        self.set_title_bar_style(cm.get("popup.header.background", "#2c3e50"), cm.get("popup.header.text", "#FFFFFF"), hover_bg)
        self.set_bottom_bar_style(self.get_footer_background(), border_color)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_layout.addWidget(main_splitter)

        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_layout.addWidget(top_splitter)
        main_splitter.addWidget(top_widget)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self._scene = QGraphicsScene()
        self._pix_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pix_item)

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

        self._btn_container = QWidget()
        btn_row = QHBoxLayout(self._btn_container)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)
        left_layout.addWidget(self._btn_container, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
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
        btn_row.addStretch()

        for b in (self.detect_btn, self.draw_btn, self.recognize_btn, self.apply_undetected_btn):
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
                    background-color: {table_header_bg};
                    color: #A0A0A0;
                    border: 1px solid {table_header_border};
                }}
            """)
            try:
                w = int(b.sizeHint().width())
                b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                b.setMinimumWidth(w)
                b.setMaximumWidth(w)
            except Exception:
                pass
        try:
            self.apply_undetected_btn.setVisible(bool(len(self._selected_files) > 1))
        except Exception:
            pass

        try:
            self._btn_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._btn_container.setFixedSize(self._btn_container.sizeHint())
        except Exception:
            pass

        loop_row_container = QWidget()
        loop_row = QHBoxLayout(loop_row_container)
        loop_row.setContentsMargins(0, 0, 0, 0)
        loop_row.setSpacing(10)

        self.loop_label = QLabel("循环检查:")
        self.loop_label.setStyleSheet(f"font-size: 13px; color: {text_color};")
        loop_row.addWidget(self.loop_label)

        self.loop_check = QCheckBox("启用")
        self.loop_check.setChecked(False)
        self.loop_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.loop_check.stateChanged.connect(self._on_loop_check_mode_changed)
        self.loop_check.setStyleSheet(f"font-size: 12px; color: {text_color};")
        loop_row.addWidget(self.loop_check)

        self.use_default_label_cb = QCheckBox("使用默认色标（不覆盖手动色标）")
        self.use_default_label_cb.setChecked(bool(self._settings_manager.get("import_to_library/use_default_label", True)))
        self.use_default_label_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.use_default_label_cb.setStyleSheet(f"font-size: 12px; color: {text_color};")
        try:
            self.use_default_label_cb.stateChanged.connect(lambda _v=None: self._settings_manager.set("import_to_library/use_default_label", bool(self.use_default_label_cb.isChecked())))
        except Exception:
            pass
        loop_row.addWidget(self.use_default_label_cb)

        self.loop_start_btn = QPushButton(qta.icon("mdi6.play", color=text_color), "开始循环检测")
        self.loop_start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.loop_start_btn.clicked.connect(self._on_loop_start_clicked)
        self.loop_start_btn.setToolTip("循环检测所有图片")
        self.loop_start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {control_bg};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
                color: {text_color};
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border: 1px solid {primary_color};
            }}
        """)
        loop_row.addWidget(self.loop_start_btn)

        self.loop_status_label = QLabel("")
        self.loop_status_label.setStyleSheet(f"font-size: 12px; color: {text_color};")
        loop_row.addWidget(self.loop_status_label, 1)

        left_layout.addWidget(loop_row_container, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        try:
            multi = len(self._selected_files) > 1
            loop_row_container.setVisible(multi)
            self.loop_check.setEnabled(multi)
            self.loop_start_btn.setEnabled(multi and bool(self.loop_check.isChecked()))
        except Exception:
            pass
        try:
            has_auto = any(bool((f or {}).get("auto_label")) for f in (self._selected_files or []))
            if hasattr(self, "use_default_label_cb") and self.use_default_label_cb is not None:
                self.use_default_label_cb.setVisible(bool(has_auto))
        except Exception:
            pass

        top_splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        form_container = QWidget()
        form_container.setMaximumWidth(380)
        form_container_layout = QVBoxLayout(form_container)
        form_container_layout.setContentsMargins(0, 0, 0, 0)
        form_container_layout.setSpacing(0)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_container_layout.addLayout(form)

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
        form.addRow(_form_label("拍摄位置:"), self.location_input)

        self.shot_time_input = QLineEdit()
        self.shot_time_input.setPlaceholderText("自动读取拍摄时间（可手动修改）")
        self.shot_time_input.setStyleSheet(f"""
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
        form.addRow(_form_label("拍摄时间:"), self.shot_time_input)

        self.species_input = QLineEdit()
        self.species_input.setPlaceholderText("请输入种名")
        self.species_input.textChanged.connect(self._on_species_changed)
        self.species_input.textChanged.connect(self._on_species_text_changed)
        form.addRow(_form_label("种名:"), self.species_input)

        self.order_input = QLineEdit()
        self.order_input.setPlaceholderText("目（例如：鸵鸟目）")
        self.order_input.textChanged.connect(self._on_classification_field_changed)
        form.addRow(_form_label("目:"), self.order_input)

        self.family_input = QLineEdit()
        self.family_input.setPlaceholderText("科（例如：鸵鸟科）")
        self.family_input.textChanged.connect(self._on_classification_field_changed)
        form.addRow(_form_label("科:"), self.family_input)

        self.genus_input = QLineEdit()
        self.genus_input.setPlaceholderText("属（例如：鸵鸟属）")
        self.genus_input.textChanged.connect(self._on_classification_field_changed)
        form.addRow(_form_label("属:"), self.genus_input)

        for le in (self.species_input, self.order_input, self.family_input, self.genus_input):
            le.setStyleSheet(f"""
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

        right_layout.addStretch()
        right_layout.addWidget(form_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        right_layout.addStretch()
        top_splitter.addWidget(right_panel)
        top_splitter.setSizes([820, 280])

        bottom_panel = QWidget()
        bottom_layout = QVBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        rule_panel = QWidget()
        rule_layout = QVBoxLayout(rule_panel)
        rule_layout.setContentsMargins(0, 0, 0, 0)
        rule_layout.setSpacing(6)

        rule_row = QHBoxLayout()
        rule_row.setContentsMargins(0, 0, 0, 0)
        rule_row.setSpacing(8)
        rule_layout.addLayout(rule_row)

        rule_title = QLabel("命名规则:")
        rule_title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {text_color};")
        rule_row.addWidget(rule_title)

        self.rule_edit = QLineEdit("{Order}_{Family}_{Genus}_{Species}_{Index}")
        self.rule_edit.setPlaceholderText("例如: {Order}_{Family}_{Genus}_{Species}_{Index}")
        self.rule_edit.textChanged.connect(self._update_import_preview)
        self.rule_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 13px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        rule_row.addWidget(self.rule_edit, 1)

        self.start_index_spin = QSpinBox()
        self.start_index_spin.setRange(1, 999999)
        self.start_index_spin.setValue(1)
        self.start_index_spin.valueChanged.connect(self._update_import_preview)
        self.start_index_spin.setStyleSheet(f"""
            QSpinBox {{
                padding: 6px 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {control_bg};
                color: {text_color};
                min-width: 70px;
            }}
            QSpinBox:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        rule_row.addWidget(QLabel("起始序号:"), 0)
        rule_row.addWidget(self.start_index_spin, 0)

        self.index_width_spin = QSpinBox()
        self.index_width_spin.setRange(1, 8)
        self.index_width_spin.setValue(3)
        self.index_width_spin.valueChanged.connect(self._update_import_preview)
        self.index_width_spin.setStyleSheet(f"""
            QSpinBox {{
                padding: 6px 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {control_bg};
                color: {text_color};
                min-width: 60px;
            }}
            QSpinBox:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        rule_row.addWidget(QLabel("序号位数:"), 0)
        rule_row.addWidget(self.index_width_spin, 0)

        tags_layout = QHBoxLayout()
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(8)
        rule_layout.addLayout(tags_layout)

        tags = [
            ("{Species}", "种"),
            ("{Order}", "目"),
            ("{Family}", "科"),
            ("{Genus}", "属"),
            ("{Date}", "日期"),
            ("{Time}", "时间"),
            ("{Index}", "序号"),
            ("{Original}", "原名"),
        ]

        for tag, name in tags:
            btn = QPushButton(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, t=tag: self.insert_tag(t))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {control_bg};
                    border: 1px solid {border_color};
                    border-radius: 3px;
                    padding: 4px 8px;
                    font-size: 12px;
                    color: {text_color};
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                    border: 1px solid {primary_color};
                }}
            """)
            tags_layout.addWidget(btn)

        tags_layout.addStretch()
        bottom_layout.addWidget(rule_panel)

        self.dest_label = QLabel("")
        self.dest_label.setStyleSheet(f"color: {text_color}; font-size: 13px;")
        bottom_layout.addWidget(self.dest_label)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(["原文件名", "新文件名", "状态"])
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setWordWrap(True)
        try:
            self.preview_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        except Exception:
            pass
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        header_style = f"""
            QHeaderView::section {{
                background-color: {table_header_bg};
                padding: 6px;
                border: 1px solid {table_header_border};
                font-weight: bold;
                color: {text_color};
            }}
        """
        try:
            self.preview_table.horizontalHeader().setStyleSheet(header_style)
            self.preview_table.verticalHeader().setStyleSheet(header_style)
        except Exception:
            pass

        self.preview_table.setStyleSheet(f"""
            QTableWidget {{
                border: 1px solid {table_header_border};
                background-color: {control_bg};
                gridline-color: {table_header_border};
                alternate-background-color: {table_header_bg};
                color: {text_color};
            }}
            QHeaderView::section {{
                background-color: {table_header_bg};
                padding: 6px;
                border: 1px solid {table_header_border};
                font-weight: bold;
                color: {text_color};
            }}
            QTableCornerButton::section {{
                background-color: {table_header_bg};
                border: 1px solid {table_header_border};
            }}
            QTableWidget::item {{
                padding: 6px 6px 10px 6px;
            }}
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {scrollbar_handle};
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {scrollbar_handle_hover};
            }}
        """)
        bottom_layout.addWidget(self.preview_table, 1)

        main_splitter.addWidget(bottom_panel)
        try:
            self.preview_table.setMinimumHeight(280)
        except Exception:
            pass
        main_splitter.setSizes([400, 320])

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        self.bottom_layout.addWidget(self.cancel_btn)

        self.import_btn = QPushButton(qta.icon("mdi6.database-import", color="#FFFFFF"), "导入")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.clicked.connect(self._on_import_clicked)
        self.bottom_layout.addWidget(self.import_btn)

        self.cancel_btn.setStyleSheet(f"""
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
        self.import_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary_color};
                border: 1px solid {primary_color};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                color: #FFFFFF;
            }}
            QPushButton:hover {{
                background-color: {primary_color};
                border: 1px solid {primary_color};
            }}
            QPushButton:disabled {{
                background-color: {table_header_border};
                border: 1px solid {table_header_border};
                color: #FFFFFF;
            }}
        """)

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
                try:
                    from utils.file.file import load_raw_full
                    img = load_raw_full(self._current_path)
                except Exception:
                    img = None
            if img is None:
                return
            try:
                import numpy as np
                if isinstance(img, np.ndarray):
                    if len(img.shape) == 2:
                        rgb = img
                        fmt = QImage.Format.Format_Grayscale8
                        bytes_per_line = int(rgb.strides[0])
                        qimg = QImage(rgb.data, int(rgb.shape[1]), int(rgb.shape[0]), bytes_per_line, fmt).copy()
                        pix = QPixmap.fromImage(qimg)
                    elif len(img.shape) == 3 and int(img.shape[2]) >= 3:
                        if int(img.shape[2]) == 4:
                            rgba = img
                            bytes_per_line = int(rgba.strides[0])
                            qimg = QImage(rgba.data, int(rgba.shape[1]), int(rgba.shape[0]), bytes_per_line, QImage.Format.Format_RGBA8888).copy()
                            pix = QPixmap.fromImage(qimg)
                        else:
                            bgr = img
                            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
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
        self._update_button_container_width()

    def eventFilter(self, obj, event):
        try:
            if obj is getattr(self, "_view", None) or obj is getattr(getattr(self, "_view", None), "viewport", lambda: None)():
                if event.type() == QEvent.Type.Resize:
                    self._update_button_container_width()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _update_button_container_width(self):
        try:
            if not hasattr(self, "_btn_container") or self._btn_container is None:
                return
            if not hasattr(self, "_view") or self._view is None:
                return
            pix = self._pix_item.pixmap() if hasattr(self, "_pix_item") else QPixmap()
            if pix.isNull():
                return
            viewport = self._view.viewport()
            viewport_w = int(viewport.width()) if viewport is not None else 0
            if viewport_w <= 0:
                return
            tr = self._view.transform()
            try:
                scale = float(min(tr.m11(), tr.m22()))
            except Exception:
                scale = float(tr.m11())
            if scale <= 0:
                scale = 1.0
            shown_w = int(pix.width() * scale)
            shown_w = max(260, min(viewport_w, shown_w))
            need_w = int(self._btn_container.sizeHint().width()) if self._btn_container is not None else 0
            self._btn_container.setFixedWidth(max(shown_w, need_w))
        except Exception:
            pass
        try:
            self._update_nav_buttons_pos()
        except Exception:
            pass

    def _update_nav_buttons_pos(self):
        if not hasattr(self, "_view") or self._view is None:
            return
        viewport = self._view.viewport()
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
            if hasattr(self, "_nav_prev") and self._nav_prev:
                self._nav_prev.move(8, y)
        except Exception:
            pass
        try:
            if hasattr(self, "_nav_next") and self._nav_next:
                self._nav_next.move(max(0, vw - btn_w - 8), y)
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

        self._bbox_xyxy = None
        try:
            bbox = st.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                self._bbox_xyxy = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
        except Exception:
            self._bbox_xyxy = None

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
            if hasattr(self, "loop_status_label") and self.loop_status_label is not None:
                total = len(self._selected_files)
                if total > 1:
                    self.loop_status_label.setText(f"{int(self._current_index) + 1}/{total}")
        except Exception:
            pass
        try:
            lbl = getattr(self, "current_file_name_label", None)
            if lbl is not None:
                name = os.path.basename(str(path or "")) if path else ""
                lbl.setText(name)
                lbl.setToolTip(str(path or ""))
        except Exception:
            pass

        self._update_import_preview()

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
        try:
            if self._bg_running:
                self._bg_priority_path = str(self._current_path or "")
                QTimer.singleShot(0, self._bg_process_next)
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
        try:
            self._update_nav_buttons_pos()
        except Exception:
            pass

    def _on_prev_image_clicked(self):
        self._set_current_index(int(getattr(self, "_current_index", 0)) - 1)

    def _on_next_image_clicked(self):
        self._set_current_index(int(getattr(self, "_current_index", 0)) + 1)

    def _on_loop_check_mode_changed(self, _state: int):
        enabled = False
        try:
            enabled = bool(self.loop_check.isChecked())
        except Exception:
            enabled = False
        if not enabled and self._bg_running:
            self._stop_background_loop()
        try:
            multi = len(self._selected_files) > 1
            self.loop_start_btn.setEnabled(multi and enabled)
        except Exception:
            pass
        self._update_import_preview()

    def _on_loop_start_clicked(self):
        if not (len(self._selected_files) > 1):
            return
        try:
            if not bool(self.loop_check.isChecked()):
                NotificationManager.instance().show_toast("请先勾选循环检查")
                return
        except Exception:
            return
        if self._bg_running:
            self._stop_background_loop()
        else:
            self._start_background_loop()

    def _start_background_loop(self):
        if self._import_running:
            return
        if not (len(self._selected_files) > 1):
            return
        self._bg_token += 1
        token = int(self._bg_token)
        self._bg_running = True
        self._bg_inflight = False
        self._bg_pos = 0
        self._bg_priority_path = str(getattr(self, "_current_path", "") or "")
        self._bg_queue = []
        try:
            for f in (self._selected_files or []):
                p = str((f or {}).get("path") or "")
                if p:
                    self._state_for_path(p)
                    self._bg_queue.append(p)
        except Exception:
            self._bg_queue = []
        self._loop_running = True
        self._loop_enabled = True
        try:
            self.loop_start_btn.setIcon(qta.icon("mdi6.stop", color=ColorManager.instance().get("popup.text.primary", "#333333")))
            self.loop_start_btn.setText("停止循环检测")
        except Exception:
            pass
        self._bg_update_progress_text()
        QTimer.singleShot(0, lambda: self._bg_process_next(token))

    def _stop_background_loop(self):
        self._bg_token += 1
        self._bg_running = False
        self._bg_inflight = False
        self._loop_running = False
        self._loop_enabled = False
        try:
            self.loop_start_btn.setIcon(qta.icon("mdi6.play", color=ColorManager.instance().get("popup.text.primary", "#333333")))
            self.loop_start_btn.setText("开始循环检测")
        except Exception:
            pass
        try:
            self.loop_status_label.setText("")
        except Exception:
            pass

    def _bg_completed_count(self) -> int:
        n = 0
        try:
            for p in (self._bg_queue or []):
                st = self._state_for_path(p)
                bbox_ok = bool(st.get("bbox"))
                species_ok = bool(str(st.get("species", "") or "").strip())
                order_ok = bool(str(st.get("order", "") or "").strip())
                family_ok = bool(str(st.get("family", "") or "").strip())
                genus_ok = bool(str(st.get("genus", "") or "").strip())
                if bbox_ok and species_ok and order_ok and family_ok and genus_ok:
                    n += 1
        except Exception:
            return n
        return n

    def _bg_update_progress_text(self):
        try:
            total = len(self._bg_queue or [])
            done = self._bg_completed_count()
            if not self._bg_running:
                self.loop_status_label.setText("")
            else:
                current = ""
                try:
                    p = str(getattr(self, "_bg_current_path", "") or "")
                    current = os.path.basename(p) if p else ""
                except Exception:
                    current = ""
                if current:
                    self.loop_status_label.setText(f"后台处理中 {done}/{total}  |  {current}")
                else:
                    self.loop_status_label.setText(f"后台处理中 {done}/{total}")
        except Exception:
            pass

    def _bg_process_next(self, token: int | None = None):
        if token is None:
            token = int(getattr(self, "_bg_token", 0))
        if int(token) != int(getattr(self, "_bg_token", 0)):
            return
        if not self._bg_running:
            return
        if self._import_running:
            return
        if self._bg_inflight:
            return
        if not self._bg_queue:
            self._stop_background_loop()
            return

        prio = str(getattr(self, "_bg_priority_path", "") or "")
        if prio:
            self._bg_priority_path = ""
            if prio in self._bg_queue and not self._bg_is_path_complete(prio):
                self._bg_start_process_path(prio, token)
                return

        while self._bg_pos < len(self._bg_queue):
            p = self._bg_queue[self._bg_pos]
            if self._bg_is_path_complete(p):
                self._bg_pos += 1
                continue
            self._bg_start_process_path(p, token)
            return

        self._bg_update_progress_text()
        self._update_import_preview()
        self._bg_running = False
        self._loop_running = False
        self._loop_enabled = False
        try:
            NotificationManager.instance().show_toast("后台循环检测完成")
        except Exception:
            pass
        self._stop_background_loop()

    def _bg_is_path_complete(self, path: str) -> bool:
        st = self._state_for_path(str(path or ""))
        bbox_ok = bool(st.get("bbox"))
        species_ok = bool(str(st.get("species", "") or "").strip())
        order_ok = bool(str(st.get("order", "") or "").strip())
        family_ok = bool(str(st.get("family", "") or "").strip())
        genus_ok = bool(str(st.get("genus", "") or "").strip())
        return bbox_ok and species_ok and order_ok and family_ok and genus_ok

    def _bg_start_process_path(self, path: str, token: int):
        if int(token) != int(getattr(self, "_bg_token", 0)):
            return
        if not self._bg_running:
            return
        p = str(path or "")
        if not p:
            self._bg_pos += 1
            QTimer.singleShot(0, lambda: self._bg_process_next(token))
            return
        self._bg_inflight = True
        self._bg_inflight_path = p
        self._bg_current_path = p
        st = self._state_for_path(p)
        bbox = st.get("bbox")
        if not bbox:
            self._bg_inflight_kind = "detect"
            QTimer.singleShot(60000, lambda: self._bg_on_timeout(p, token))
            def cb(cb_path, cb_bbox, focus_point, position, err):
                _ = focus_point
                _ = position
                try:
                    self._bg_detect_done.emit(int(token), str(p or ""), cb_bbox, str(err or ""))
                except Exception:
                    pass
            try:
                detect_subject_bbox_async(p, callback=cb, targets=["bbox_orig"])
            except Exception as e:
                try:
                    self._bg_detect_done.emit(int(token), str(p or ""), None, str(e))
                except Exception:
                    pass
            return

        self._bg_start_species_recognition(p, bbox, token)

    def _bg_on_timeout(self, path: str, token: int):
        if int(token) != int(getattr(self, "_bg_token", 0)):
            return
        if not self._bg_running:
            return
        if not self._bg_inflight:
            return
        if str(getattr(self, "_bg_inflight_path", "") or "") != str(path or ""):
            return
        kind = str(getattr(self, "_bg_inflight_kind", "") or "")
        self._bg_inflight = False
        self._bg_inflight_path = ""
        self._bg_inflight_kind = ""
        try:
            st = self._state_for_path(str(path or ""))
            if kind == "detect":
                st["bbox"] = None
        except Exception:
            pass
        try:
            if 0 <= int(self._bg_pos) < len(self._bg_queue) and str(self._bg_queue[int(self._bg_pos)] or "") == str(path or ""):
                self._bg_pos += 1
        except Exception:
            pass
        self._bg_update_progress_text()
        self._update_import_preview()
        QTimer.singleShot(0, lambda: self._bg_process_next(token))

    def _on_bg_detect_done(self, token: int, path: str, bbox: object, err: str):
        try:
            self._bg_on_detect_done(str(path or ""), bbox, str(err or ""), int(token))
        except Exception:
            pass

    def _bg_on_detect_done(self, path: str, bbox: Any, err: str, token: int):
        if int(token) != int(getattr(self, "_bg_token", 0)):
            return
        if not self._bg_running:
            return
        p = str(path or "")
        st = self._state_for_path(p)
        self._bg_inflight_kind = ""
        if err:
            try:
                st["bbox"] = None
            except Exception:
                pass
            self._bg_inflight = False
            self._bg_inflight_path = ""
            try:
                if 0 <= int(self._bg_pos) < len(self._bg_queue) and str(self._bg_queue[int(self._bg_pos)] or "") == p:
                    self._bg_pos += 1
            except Exception:
                pass
            self._bg_update_progress_text()
            self._update_import_preview()
            QTimer.singleShot(0, lambda: self._bg_process_next(token))
            return

        xyxy = self._parse_xyxy_bbox(bbox)
        try:
            st["bbox"] = xyxy
        except Exception:
            pass
        if p == str(getattr(self, "_current_path", "") or "") and xyxy:
            self._bbox_xyxy = list(xyxy)
            self._draw_bbox_on_preview(self._bbox_xyxy)
        if not xyxy:
            self._bg_inflight = False
            self._bg_inflight_path = ""
            try:
                if 0 <= int(self._bg_pos) < len(self._bg_queue) and str(self._bg_queue[int(self._bg_pos)] or "") == p:
                    self._bg_pos += 1
            except Exception:
                pass
            self._bg_update_progress_text()
            self._update_import_preview()
            QTimer.singleShot(0, lambda: self._bg_process_next(token))
            return

        self._bg_start_species_recognition(p, xyxy, token)

    def _bg_start_species_recognition(self, path: str, bbox_xyxy: Any, token: int):
        if int(token) != int(getattr(self, "_bg_token", 0)):
            return
        if not self._bg_running:
            return
        p = str(path or "")
        bbox = list(bbox_xyxy) if isinstance(bbox_xyxy, (list, tuple)) else None
        if not bbox or len(bbox) < 4:
            self._bg_inflight = False
            self._bg_inflight_path = ""
            try:
                if 0 <= int(self._bg_pos) < len(self._bg_queue) and str(self._bg_queue[int(self._bg_pos)] or "") == p:
                    self._bg_pos += 1
            except Exception:
                pass
            QTimer.singleShot(0, lambda: self._bg_process_next(token))
            return
        self._bg_inflight_kind = "species"
        QTimer.singleShot(120000, lambda: self._bg_on_timeout(p, token))

        def run():
            try:
                img = load_image(p)
                if img is None:
                    raise RuntimeError("读取图片失败")
                h, w = img.shape[:2]
                x1 = max(0, min(int(bbox[0]), w - 1))
                y1 = max(0, min(int(bbox[1]), h - 1))
                x2 = max(0, min(int(bbox[2]), w))
                y2 = max(0, min(int(bbox[3]), h))
                if x2 <= x1 or y2 <= y1:
                    raise RuntimeError("主体框无效")
                crop = img[y1:y2, x1:x2]

                fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
                os.close(fd)
                try:
                    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    if not ok:
                        raise RuntimeError("裁剪图片编码失败")
                    with open(tmp_path, "wb") as f:
                        f.write(bytes(buf))
                    location_hint = ""
                    try:
                        location_hint = (self.location_input.text() or "").strip()
                    except Exception:
                        location_hint = ""
                    time_hint = ""
                    try:
                        fi = self._path_to_file.get(p, {}) or {}
                        time_hint = str(fi.get("shot_time") or fi.get("create_time") or "")
                    except Exception:
                        time_hint = ""
                    text = BirdSpeciesRecognizer().recognize(tmp_path, location_hint=location_hint, time_hint=time_hint).text
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

                species = self._extract_species_name(text)
                try:
                    self._bg_species_done.emit(int(token), str(p or ""), str(species or ""), "")
                except Exception:
                    pass
            except Exception as e:
                try:
                    self._bg_species_done.emit(int(token), str(p or ""), "", str(e))
                except Exception:
                    pass

        Thread(target=run, daemon=True).start()

    def _on_bg_species_done(self, token: int, path: str, species: str, err: str):
        try:
            self._bg_on_species_done(str(path or ""), str(species or ""), str(err or ""), int(token))
        except Exception:
            pass

    def _bg_on_species_done(self, path: str, species: str, err: str, token: int):
        if int(token) != int(getattr(self, "_bg_token", 0)):
            return
        if not self._bg_running:
            return
        p = str(path or "")
        st = self._state_for_path(p)
        self._bg_inflight_kind = ""
        if err:
            self._bg_inflight = False
            self._bg_inflight_path = ""
            try:
                if 0 <= int(self._bg_pos) < len(self._bg_queue) and str(self._bg_queue[int(self._bg_pos)] or "") == p:
                    self._bg_pos += 1
            except Exception:
                pass
            self._bg_update_progress_text()
            self._update_import_preview()
            QTimer.singleShot(0, lambda: self._bg_process_next(token))
            return

        s = str(species or "").strip()
        if s:
            try:
                st["species"] = s
            except Exception:
                pass
            try:
                looks_latin = bool(re.fullmatch(r"[A-Za-z][A-Za-z\s\.\-]*", s)) and not bool(re.search(r"[\u4e00-\u9fff]", s))
            except Exception:
                looks_latin = False
            if not looks_latin:
                try:
                    t = BirdBiologicalClassifier().classify(self._normalize_species_text(s))
                except Exception:
                    t = None
                if t is not None:
                    try:
                        if not str(st.get("order") or "").strip():
                            st["order"] = t.order_cn
                        if not str(st.get("family") or "").strip():
                            st["family"] = t.family_cn
                        if not str(st.get("genus") or "").strip():
                            st["genus"] = t.genus_cn
                    except Exception:
                        pass

        if p == str(getattr(self, "_current_path", "") or ""):
            self._restore_state_for_current()
        self._bg_inflight = False
        self._bg_inflight_path = ""
        try:
            if 0 <= int(self._bg_pos) < len(self._bg_queue) and str(self._bg_queue[int(self._bg_pos)] or "") == p:
                self._bg_pos += 1
        except Exception:
            pass
        self._bg_update_progress_text()
        self._update_import_preview()
        QTimer.singleShot(0, lambda: self._bg_process_next(token))

    def _set_busy(self, busy: bool):
        self._import_running = bool(busy)
        for w in (
            self.detect_btn,
            self.draw_btn,
            self.recognize_btn,
            getattr(self, "loop_start_btn", None),
            getattr(self, "_nav_prev", None),
            getattr(self, "_nav_next", None),
            self.location_input,
            self.shot_time_input,
            self.species_input,
            self.order_input,
            self.family_input,
            self.genus_input,
            self.rule_edit,
            self.start_index_spin,
            self.index_width_spin,
            self.cancel_btn,
            self.import_btn,
        ):
            try:
                if w is None:
                    continue
                w.setEnabled(not busy)
            except Exception:
                pass
        self._update_import_preview()

    def insert_tag(self, tag: str):
        try:
            self.rule_edit.insert(tag)
            self.rule_edit.setFocus()
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
            try:
                raw = ExifHandleWorker.get_instance().read_tag(self._current_path, EXIF_TAG.Location.value, timeout=3)
            except Exception:
                raw = None
            text = self._extract_country_province(raw)
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

    def _on_toggle_draw_clicked(self):
        if self._import_running:
            return
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
            try:
                self._save_current_state()
            except Exception:
                pass
            if self._loop_running:
                QTimer.singleShot(0, self._loop_process_current)
        except Exception:
            pass

    def _on_detect_subject_clicked(self):
        if not self._current_path:
            return
        if self._import_running:
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
            StatusManager.instance().finish_task(task_id)
            try:
                self._detect_tasks.pop(req_id, None)
            except Exception:
                pass
            self.detect_btn.setEnabled(True)
            NotificationManager.instance().show_warning("错误", f"启动主体检测失败: {e}")

    def _on_detect_done(self, req_id: int, path: str, bbox: object, err: str):
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
        self._apply_detect_result(path, bbox, err)

    def _apply_detect_result(self, path: str, bbox: Any, err: str):
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
        try:
            self._save_current_state()
        except Exception:
            pass
        NotificationManager.instance().show_toast("已检测到主体位置")
        if self._loop_running:
            QTimer.singleShot(0, self._loop_process_current)

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
        if self._import_running:
            return
        if not self._current_path:
            return
        if self._bbox_xyxy is None:
            NotificationManager.instance().show_warning("提示", "请先检测或手动框选主体位置")
            return

        bbox = list(self._bbox_xyxy)
        self.recognize_btn.setEnabled(False)
        task_id = StatusManager.instance().start_task("正在识别物种...")
        self._species_req_id += 1
        req_id = int(self._species_req_id)
        self._species_tasks[req_id] = int(task_id)

        def run():
            try:
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
                crop = img[y1:y2, x1:x2]

                fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
                os.close(fd)
                try:
                    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    if not ok:
                        raise RuntimeError("裁剪图片编码失败")
                    with open(tmp_path, "wb") as f:
                        f.write(bytes(buf))
                    location_hint = ""
                    try:
                        location_hint = (self.location_input.text() or "").strip()
                    except Exception:
                        location_hint = ""
                    time_hint = ""
                    try:
                        time_hint = (self.shot_time_input.text() or "").strip()
                    except Exception:
                        time_hint = ""
                    text = BirdSpeciesRecognizer().recognize(tmp_path, location_hint=location_hint, time_hint=time_hint).text
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
            self._apply_species_error(err)
            return
        self._apply_species_result(species)

    def _apply_species_result(self, species: str):
        s = (species or "").strip()
        if not s:
            NotificationManager.instance().show_warning("提示", "物种识别失败")
            return
        try:
            self._suppress_species_suggestions = True
        except Exception:
            pass
        try:
            self.species_input.setText(s)
        finally:
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
        NotificationManager.instance().show_toast("已填充物种名称")
        try:
            self._save_current_state()
        except Exception:
            pass
        if self._loop_running:
            QTimer.singleShot(0, self._loop_process_current)

    def _on_apply_undetected_clicked(self):
        if self._import_running:
            return
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
            applied += 1
        if applied > 0:
            try:
                NotificationManager.instance().show_toast(f"已应用到未检测文件：{applied} 张")
            except Exception:
                pass
        self._update_import_preview()

    def _apply_species_error(self, err: str):
        NotificationManager.instance().show_warning("错误", f"物种识别失败: {err}")

    def _on_classification_field_changed(self, _text: str = ""):
        if getattr(self, "_switching_image", False):
            self._update_import_preview()
            return
        try:
            self._save_current_state()
        except Exception:
            pass
        self._update_import_preview()

    def _on_species_changed(self, _text: str = ""):
        if getattr(self, "_switching_image", False):
            self._update_import_preview()
            return
        species = (self.species_input.text() or "").strip()
        if not species:
            self._update_import_preview()
            return
        species_for_classifier = self._normalize_species_text(species)
        try:
            looks_latin = bool(re.fullmatch(r"[A-Za-z][A-Za-z\s\.\-]*", species)) and not bool(re.search(r"[\u4e00-\u9fff]", species))
        except Exception:
            looks_latin = False
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
            self._save_current_state()
        except Exception:
            pass
        self._update_import_preview()

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
            import json
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
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

        if any(t.isascii() and t.isalpha() for t in tokens) and not self._pinyin_available and not self._pinyin_warned:
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
        """
        对种名输入做兜底归一化，解决少数“异体字/常见替代写法”导致无法匹配的问题。

        说明：
        - 该函数只影响联想匹配与分类器输入，不改变你最终实际保存/导入的字符串逻辑（仍以输入框内容为准）。
        - 归一化规则来自独立 JSON 文件，便于后续维护与扩展。

        参数：
        - text: 用户输入的种名（可能包含空格）
        """
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
        """
        读取“种名兜底归一化规则”映射表。

        说明：
        - 映射表使用 JSON 文件维护，避免把规则写死在代码里，方便后续按需增补。
        - 读取结果会做进程内缓存：对话框多次打开时不会反复读文件。
        - 文件不存在或格式不合法时，返回空列表（不影响主流程）。

        返回：
        - 规则列表：每条包含 from/to 字段，例如 {"from": "鸊鷉", "to": "䴙䴘"}
        """
        cached = getattr(ImportToLibraryDialog, "_species_text_alias_rules_cache", None)
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

        ImportToLibraryDialog._species_text_alias_rules_cache = rules
        return rules

    def _get_library_root(self) -> str:
        root = str(self._settings_manager.get("general/root_path", "") or "").strip()
        return root

    def _get_target_folder(self) -> str:
        root = self._get_library_root()
        order_name = (self.order_input.text() or "").strip()
        family_name = (self.family_input.text() or "").strip()
        genus_name = (self.genus_input.text() or "").strip()
        species_name = (self.species_input.text() or "").strip()
        if not root or not order_name or not family_name or not genus_name or not species_name:
            return ""
        return os.path.join(root, order_name, family_name, genus_name, species_name)

    def _get_target_folder_from_meta(self, meta: dict[str, str]) -> str:
        root = self._get_library_root()
        if not root:
            return ""
        try:
            order_name = str(meta.get("order") or "").strip()
            family_name = str(meta.get("family") or "").strip()
            genus_name = str(meta.get("genus") or "").strip()
            species_name = str(meta.get("species") or "").strip()
        except Exception:
            return ""
        if not order_name or not family_name or not genus_name or not species_name:
            return ""
        return os.path.join(root, order_name, family_name, genus_name, species_name)

    def _parse_date_time(self, shot_time: str) -> tuple[str, str]:
        s = str(shot_time or "").strip()
        if not s:
            return "", ""
        try:
            clean = s.replace(":", "").replace("-", "").replace(" ", "")
            date_str = clean[:8] if len(clean) >= 8 else ""
            time_str = clean[8:14] if len(clean) >= 14 else ""
            return date_str, time_str
        except Exception:
            return "", ""

    def _sanitize_filename_base(self, name: str) -> str:
        s = str(name or "").strip()
        s = re.sub(r'[<>:"/\\\\|?*]', "_", s)
        s = re.sub(r"\s+", " ", s).strip()
        s = s.rstrip(".")
        return s

    def _get_effective_meta_for_file(self, file_info: dict) -> dict[str, str]:
        src = str((file_info or {}).get("path") or "")
        multi = len(getattr(self, "_selected_files", []) or []) > 1
        if not multi:
            return {
                "species": str(self.species_input.text() or "").strip(),
                "order": str(self.order_input.text() or "").strip(),
                "family": str(self.family_input.text() or "").strip(),
                "genus": str(self.genus_input.text() or "").strip(),
            }
        st = self._file_states.get(src) if (multi and src) else (self._state_for_path(src) if src else {})
        is_current = bool(src) and src == str(getattr(self, "_current_path", "") or "")
        if multi and (not st) and (not is_current):
            return {"species": "", "order": "", "family": "", "genus": ""}
        meta = {
            "species": str((st.get("species") if st else "") or ((self.species_input.text() or "") if is_current else "")).strip(),
            "order": str((st.get("order") if st else "") or ((self.order_input.text() or "") if is_current else "")).strip(),
            "family": str((st.get("family") if st else "") or ((self.family_input.text() or "") if is_current else "")).strip(),
            "genus": str((st.get("genus") if st else "") or ((self.genus_input.text() or "") if is_current else "")).strip(),
        }
        return meta

    def _build_candidate_name(self, file_info: dict, current_index: int, meta: dict[str, str] | None = None) -> tuple[str, int]:
        old_path = str(file_info.get("path") or "")
        old_name = os.path.basename(old_path)
        old_no_ext, ext = os.path.splitext(old_name)
        pattern = str(self.rule_edit.text() or "").strip()
        if not pattern:
            pattern = "{Order}_{Family}_{Genus}_{Species}_{Index}"

        m = meta or {
            "species": (self.species_input.text() or "").strip(),
            "genus": (self.genus_input.text() or "").strip(),
            "family": (self.family_input.text() or "").strip(),
            "order": (self.order_input.text() or "").strip(),
        }
        species = str(m.get("species") or "").strip()
        genus = str(m.get("genus") or "").strip()
        family = str(m.get("family") or "").strip()
        order = str(m.get("order") or "").strip()

        shot_time = str(file_info.get("shot_time") or file_info.get("create_time") or "")
        date_str, time_str = self._parse_date_time(shot_time)

        name_base = pattern
        name_base = name_base.replace("{Species}", str(species))
        name_base = name_base.replace("{Genus}", str(genus))
        name_base = name_base.replace("{Family}", str(family))
        name_base = name_base.replace("{Order}", str(order))
        name_base = name_base.replace("{Date}", str(date_str))
        name_base = name_base.replace("{Time}", str(time_str))
        name_base = name_base.replace("{Original}", str(old_no_ext))

        if "{Index}" in name_base:
            width = int(self.index_width_spin.value())
            name_base = name_base.replace("{Index}", f"{current_index:0{width}d}")
            current_index += 1
        else:
            name_base = name_base.replace("{Index}", "")

        name_base = self._sanitize_filename_base(name_base)
        if not name_base:
            name_base = self._sanitize_filename_base(old_no_ext) or "Unknown"

        return f"{name_base}{ext}", current_index

    def _update_import_preview(self):
        count = len(self._selected_files)
        root = self._get_library_root()
        folder_used: dict[str, set[str]] = {}
        preview_map: dict[str, str] = {}
        preview_meta_map: dict[str, dict[str, str]] = {}
        rows = []
        current_index = int(self.start_index_spin.value())
        missing = 0
        target_folders: set[str] = set()
        for f in self._selected_files:
            src = str(f.get("path") or "")
            if not src:
                continue
            original_name = os.path.basename(src)
            meta = self._get_effective_meta_for_file(f)
            target_folder = self._get_target_folder_from_meta(meta)
            if not target_folder:
                missing += 1
                rows.append((original_name, "", "缺少分类"))
                continue
            target_folders.add(target_folder)
            used = folder_used.setdefault(target_folder, set())
            candidate_name, current_index = self._build_candidate_name(f, current_index, meta=meta)
            dest_name, status = self._resolve_conflict_name(target_folder, candidate_name, used, src)
            dest_path = os.path.join(target_folder, dest_name)
            preview_map[src] = dest_path
            preview_meta_map[src] = meta
            rows.append((original_name, dest_name, status))

        self._preview_map = preview_map
        self._preview_meta_map = preview_meta_map
        if not preview_map:
            self.dest_label.setText(f"目标目录: (请先为每张图片补全 种名/目/科/属)  |  选中 {count} 张  |  根目录: {root}")
            self.preview_table.setRowCount(len(rows))
        else:
            if len(target_folders) == 1:
                only_folder = next(iter(target_folders))
                will_create = "将创建" if not os.path.exists(only_folder) else "已存在"
                extra = f" ({will_create})"
                self.dest_label.setText(f"目标目录: {only_folder}{extra}  |  选中 {count} 张  |  根目录: {root}" + (f"  |  未完成 {missing} 张" if missing else ""))
            else:
                self.dest_label.setText(f"目标目录: (多目录 {len(target_folders)} 个)  |  选中 {count} 张  |  根目录: {root}" + (f"  |  未完成 {missing} 张" if missing else ""))
        self.preview_table.setRowCount(len(rows))
        for r, (orig_name, dest_name, status) in enumerate(rows):
            item_old = QTableWidgetItem(orig_name)
            item_old.setToolTip(orig_name)
            self.preview_table.setItem(r, 0, item_old)

            item_new = QTableWidgetItem(dest_name)
            item_new.setToolTip(dest_name)
            self.preview_table.setItem(r, 1, item_new)
            item_status = QTableWidgetItem(status)
            try:
                if "已存在" in status:
                    item_status.setForeground(Qt.GlobalColor.red)
                elif "自动解决" in status:
                    item_status.setForeground(Qt.GlobalColor.blue)
                elif "缺少" in status:
                    item_status.setForeground(Qt.GlobalColor.red)
                else:
                    item_status.setForeground(Qt.GlobalColor.green)
            except Exception:
                pass
            self.preview_table.setItem(r, 2, item_status)
        try:
            self.preview_table.resizeRowsToContents()
        except Exception:
            pass
        try:
            for r in range(self.preview_table.rowCount()):
                self.preview_table.setRowHeight(r, int(self.preview_table.rowHeight(r)) + 6)
        except Exception:
            pass

        self.import_btn.setEnabled((not self._import_running) and bool(self._preview_map) and missing == 0)

    def _resolve_conflict_name(self, folder: str, file_name: str, used: set[str], src_path: str) -> tuple[str, str]:
        base, ext = os.path.splitext(file_name)
        ext = ext or ""
        candidate = f"{base}{ext}"
        key = candidate.lower()

        def is_fs_conflict(name: str) -> bool:
            full = os.path.join(folder, name)
            if not os.path.exists(full):
                return False
            try:
                return os.path.normcase(os.path.normpath(full)) != os.path.normcase(os.path.normpath(src_path))
            except Exception:
                return True

        if key not in used and not is_fs_conflict(candidate):
            used.add(key)
            return candidate, "OK"

        counter = 1
        while True:
            candidate = f"{base}_{counter}{ext}"
            key = candidate.lower()
            if key in used:
                counter += 1
                continue
            if is_fs_conflict(candidate):
                counter += 1
                continue
            used.add(key)
            return candidate, "自动解决冲突"

    def _on_import_clicked(self):
        if self._import_running:
            return
        if not self._preview_map:
            NotificationManager.instance().show_warning("提示", "没有可导入的文件")
            return
        try:
            missing = max(0, len([x for x in (self._selected_files or []) if str(x.get("path") or "") not in set(self._preview_map.keys())]))
        except Exception:
            missing = 0
        if missing:
            NotificationManager.instance().show_warning("提示", "请先为每张图片补全 种名/目/科/属")
            return
        target_folders = set()
        try:
            for dst in (self._preview_map or {}).values():
                if not dst:
                    continue
                target_folders.add(os.path.dirname(str(dst)))
        except Exception:
            target_folders = set()
        if len(target_folders) == 1:
            self._last_import_target_folder = str(next(iter(target_folders)) or "")
        else:
            self._last_import_target_folder = str(self._get_library_root() or "")

        folder_hint = f"（{len(target_folders)} 个目录）" if len(target_folders) > 1 else ""
        if not NotificationManager.instance().ask_confirmation("确认导入", f"确定要导入选中的 {len(self._preview_map)} 张图片到图库吗？{folder_hint}"):
            return

        self._set_busy(True)
        task_id = StatusManager.instance().start_task("正在导入到图库...")
        self._import_task_id = int(task_id)
        self._import_req_id += 1
        req_id = int(self._import_req_id)

        meta_map = dict(getattr(self, "_preview_meta_map", {}) or {})
        user_location = ""
        try:
            user_location = (self.location_input.text() or "").strip()
        except Exception:
            user_location = ""

        def run():
            moved = []
            db_rows = []
            try:
                exif_worker = ExifHandleWorker.get_instance()
                for src, dst in self._preview_map.items():
                    if not src or not dst:
                        continue
                    dst_dir = os.path.dirname(dst)
                    os.makedirs(dst_dir, exist_ok=True)
                    shutil.move(src, dst)
                    moved.append((src, dst))

                    try:
                        uuid = get_unique_id()
                    except Exception:
                        uuid = ""

                    try:
                        fast_id = get_fast_id(dst)
                    except Exception:
                        fast_id = None
                    if fast_id is None:
                        fast_id = ""

                    shot_time = ""
                    try:
                        src_info = next((x for x in self._selected_files if str(x.get("path") or "") == str(src)), None)
                        if src_info:
                            shot_time = str(src_info.get("shot_time") or "")
                    except Exception:
                        shot_time = ""
                    if not shot_time:
                        try:
                            dt = exif_worker.get_time(dst)
                            if dt is not None:
                                shot_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                    if not shot_time:
                        try:
                            src_info = next((x for x in self._selected_files if str(x.get("path") or "") == str(src)), None)
                            if src_info:
                                shot_time = str(src_info.get("create_time") or "")
                        except Exception:
                            shot_time = ""
                    if not shot_time:
                        try:
                            st = os.stat(dst)
                            shot_time = datetime.fromtimestamp(float(st.st_ctime)).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            shot_time = ""

                    meta = {}
                    try:
                        meta = exif_worker.get_metadata(dst) or {}
                    except Exception:
                        meta = {}

                    try:
                        label = str(meta.get(EXIF_TAG.Label.value, "") or "")
                    except Exception:
                        label = ""
                    if bool(getattr(self, "use_default_label_cb", None) is not None and self.use_default_label_cb.isChecked()):
                        try:
                            src_info = next((x for x in self._selected_files if str(x.get("path") or "") == str(src)), None)
                        except Exception:
                            src_info = None
                        try:
                            manual_label = str(label or "")
                        except Exception:
                            manual_label = ""
                        if not manual_label and isinstance(src_info, dict):
                            try:
                                manual_label = str(src_info.get("label") or "")
                            except Exception:
                                manual_label = ""
                        if manual_label:
                            label = manual_label
                        else:
                            try:
                                auto_label = str(src_info.get("auto_label") or "") if isinstance(src_info, dict) else ""
                            except Exception:
                                auto_label = ""
                            if auto_label:
                                label = auto_label
                    try:
                        rating = int(meta.get(EXIF_TAG.Rating.value, 0) or 0)
                    except Exception:
                        rating = 0
                    try:
                        is_favorite = 1 if str(meta.get(EXIF_TAG.Favorite.value, "") or "").lower() == "true" else 0
                    except Exception:
                        is_favorite = 0
                    try:
                        fnumber = float(meta.get(EXIF_TAG.FNumber.value, 0.0) or 0.0)
                    except Exception:
                        fnumber = 0.0
                    try:
                        shutter = meta.get(EXIF_TAG.ShutterSpeed.value) or meta.get(EXIF_TAG.ExposureTime.value) or ""
                        shutter = str(shutter or "")
                    except Exception:
                        shutter = ""
                    try:
                        iso = int(meta.get(EXIF_TAG.ISO.value, 0) or 0)
                    except Exception:
                        iso = 0
                    try:
                        focal_length = str(meta.get(EXIF_TAG.FocalLength.value, "") or "")
                    except Exception:
                        focal_length = ""
                    try:
                        camera_model = str(meta.get(EXIF_TAG.CameraModel.value, "") or "")
                    except Exception:
                        camera_model = ""
                    try:
                        lens_model = str(meta.get(EXIF_TAG.LensModel.value, "") or "")
                    except Exception:
                        lens_model = ""
                    try:
                        focus_distance = str(meta.get(EXIF_TAG.FocusDistance.value, "") or "")
                    except Exception:
                        focus_distance = ""
                    try:
                        tags = str(meta.get(EXIF_TAG.Tags.value, "") or "")
                    except Exception:
                        tags = ""
                    try:
                        location = str(meta.get(EXIF_TAG.Location.value, "") or "")
                    except Exception:
                        location = ""
                    if not location and user_location:
                        location = user_location

                    src_meta = meta_map.get(str(src), {}) or {}
                    try:
                        order_name = str(src_meta.get("order") or "").strip() or str(self.order_input.text() or "").strip()
                    except Exception:
                        order_name = str(self.order_input.text() or "").strip()
                    try:
                        family_name = str(src_meta.get("family") or "").strip() or str(self.family_input.text() or "").strip()
                    except Exception:
                        family_name = str(self.family_input.text() or "").strip()
                    try:
                        genus_name = str(src_meta.get("genus") or "").strip() or str(self.genus_input.text() or "").strip()
                    except Exception:
                        genus_name = str(self.genus_input.text() or "").strip()
                    try:
                        species_name = str(src_meta.get("species") or "").strip() or str(self.species_input.text() or "").strip()
                    except Exception:
                        species_name = str(self.species_input.text() or "").strip()

                    latitude = 0.0
                    longitude = 0.0
                    try:
                        latitude = float(meta.get(EXIF_TAG.GPSLatitude.value, 0.0) or 0.0)
                    except Exception:
                        latitude = 0.0
                    try:
                        longitude = float(meta.get(EXIF_TAG.GPSLongitude.value, 0.0) or 0.0)
                    except Exception:
                        longitude = 0.0

                    try:
                        exif_worker.write_tags(
                            dst,
                            {
                                EXIF_TAG.Uuid.value: uuid,
                                EXIF_TAG.Fastid.value: fast_id,
                                EXIF_TAG.OrderCls.value: order_name,
                                EXIF_TAG.FamilyCls.value: family_name,
                                EXIF_TAG.GenusCls.value: genus_name,
                                EXIF_TAG.SpeciesCls.value: species_name,
                            },
                        )
                    except Exception:
                        pass
                    
                    src_rec = None
                    try:
                        src_rec = next((x for x in (self._selected_files or []) if str(x.get("path") or "") == str(src)), None)
                    except Exception:
                        src_rec = None
                    bbox = None
                    focus_point = None
                    focus_detect_json = ""
                    position = ""
                    pixel_count = 0
                    area_ratio = 0.0
                    eye_coordinates = None
                    description = ""
                    try:
                        if isinstance(src_rec, dict):
                            bbox = src_rec.get("bbox")
                            focus_point = src_rec.get("focus_point")
                            focus_detect_json = str(src_rec.get("focus_detect_json") or "").strip()
                            position = str(src_rec.get("position") or "").strip()
                            try:
                                pixel_count = int(src_rec.get("pixel_count") or 0)
                            except Exception:
                                pixel_count = 0
                            try:
                                area_ratio = float(src_rec.get("area_ratio") or 0.0)
                            except Exception:
                                area_ratio = 0.0
                            eye_coordinates = src_rec.get("eye_coordinates")
                            description = str(src_rec.get("description") or "").strip()
                    except Exception:
                        pass

                    db_rows.append(
                        {
                            "uuid": uuid,
                            "fast_id": fast_id,
                            "path": dst,
                            "file": os.path.basename(dst),
                            "shot_time": shot_time,
                            "order_cls": order_name,
                            "family_cls": family_name,
                            "genus_cls": genus_name,
                            "species_cls": species_name,
                            "label": label,
                            "score": 0.0,
                            "norm_score": 0,
                            "bbox": bbox,
                            "position": position,
                            "pixel_count": pixel_count,
                            "area_ratio": area_ratio,
                            "focus_point": focus_point,
                            "object": species_name,
                            "eye_coordinates": eye_coordinates,
                            "description": description,
                            "focus_detect_json": focus_detect_json,
                            "is_favorite": is_favorite,
                            "rating": rating,
                            "fnumber": fnumber,
                            "shutter": shutter,
                            "iso": iso,
                            "focal_length": focal_length,
                            "camera_model": camera_model,
                            "lens_model": lens_model,
                            "focus_distance": focus_distance,
                            "latitude": latitude,
                            "longitude": longitude,
                            "location": location,
                            "tags": tags,
                        }
                    )

                if db_rows:
                    self._db.save_results_batch(db_rows, table_name="bird_results")
                try:
                    self._import_done.emit(req_id, True, int(len(db_rows)), "")
                except Exception:
                    pass
            except Exception as e:
                try:
                    self._import_done.emit(req_id, False, 0, str(e))
                except Exception:
                    pass

        Thread(target=run, daemon=True).start()

    def _on_import_done(self, req_id: int, ok: bool, count: int, err: str):
        if int(req_id) != int(getattr(self, "_import_req_id", 0)):
            return
        task_id = self._import_task_id
        self._import_task_id = None
        if task_id is not None:
            try:
                StatusManager.instance().finish_task(task_id)
            except Exception:
                pass
        self._set_busy(False)
        if ok:
            NotificationManager.instance().show_toast(f"导入完成：{int(count)} 张")
            try:
                self.import_succeeded.emit(str(self._last_import_target_folder or ""))
            except Exception:
                pass
            self.accept()
        else:
            NotificationManager.instance().show_warning("错误", f"导入失败: {err}")
