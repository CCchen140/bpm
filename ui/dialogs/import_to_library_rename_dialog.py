import os
import re
import shutil
import tempfile
from datetime import datetime
from threading import Thread
from typing import Any

import cv2
from ui.utils.icon_loader import qta
from PyQt6.QtCore import Qt, QTimer, QStringListModel, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QCompleter,
    QHBoxLayout,
    QHeaderView,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.classifier.bird_biological_classifier import BirdBiologicalClassifier
from core.recognizer.bird_species_recognizer import BirdSpeciesRecognizer
from ui.utils.color_manager import ColorManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.status_manager import StatusManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from utils.exif.exif_utils import EXIF_TAG, ExifHandleWorker, READ_PICTURE_METADATA_TAG, READ_PICTURE_TIME_TAG
from utils.file.file import load_image
from utils.file.file_util import get_fast_id
from utils.file.fingerprint import get_unique_id
from utils.setting.settings_manager import SettingsManager
from utils.sql.data_base import BirdLibraryDB

try:
    from pypinyin import lazy_pinyin
except Exception:
    lazy_pinyin = None


class ImportToLibraryRenameDialog(BasePopupDialog):
    _import_finished = pyqtSignal(int, bool, int, str)
    import_succeeded = pyqtSignal(str)
    _quick_detect_done = pyqtSignal(int, str, str)
    _species_text_alias_rules_cache: list[dict[str, str]] | None = None

    def __init__(self, parent=None, selected_files=None, is_virtual_mode: bool = False):
        super().__init__(parent=parent, title="导入图库", size=(1100, 720))
        self._settings_manager = SettingsManager()
        self._db = BirdLibraryDB()
        self._selected_files = selected_files or []
        self._is_virtual_mode = bool(is_virtual_mode)
        self._import_running = False

        self._preview_map: dict[str, str] = {}
        self._preview_meta_map: dict[str, dict[str, str]] = {}
        self._manual_name_map: dict[str, str] = {}
        self._suppress_table_change = False
        self._db_record_map: dict[str, dict] = {}
        self._suppress_meta_change = False
        self._checked_map: dict[str, bool] = {}
        self._species_completer: QCompleter | None = None
        self._species_model: QStringListModel | None = None
        self._species_update_timer: QTimer | None = None
        self._species_index: list[dict[str, str]] = []
        self._species_display_map: dict[str, dict[str, str]] = {}
        self._suppress_species_suggestions = False
        self._pinyin_available = lazy_pinyin is not None
        self._pinyin_warned = False

        self._init_ui()
        self._import_finished.connect(self._on_import_finished)
        self._quick_detect_done.connect(self._on_quick_detect_done)
        self._reload_db_records()
        self._update_import_preview()

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

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.content_layout.addWidget(wrapper)

        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)
        layout.addWidget(top_row, 0)

        self.rule_edit = QLineEdit("{Order}_{Family}_{Genus}_{Species}_{Index}")
        self.rule_edit.setPlaceholderText("例如: {Order}_{Family}_{Genus}_{Species}_{Index}")
        self.rule_edit.textChanged.connect(self._update_import_preview)
        self.rule_edit.setStyleSheet(f"""
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
        top_layout.addWidget(self.rule_edit, 1)

        self.start_index_spin = QSpinBox()
        self.start_index_spin.setRange(1, 999999)
        self.start_index_spin.setValue(1)
        self.start_index_spin.valueChanged.connect(self._update_import_preview)
        self.start_index_spin.setStyleSheet(f"""
            QSpinBox {{
                padding: 6px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 13px;
                background-color: {control_bg};
                color: {text_color};
                min-width: 80px;
            }}
            QSpinBox:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        top_layout.addWidget(self.start_index_spin, 0)

        self.index_width_spin = QSpinBox()
        self.index_width_spin.setRange(1, 8)
        self.index_width_spin.setValue(3)
        self.index_width_spin.valueChanged.connect(self._update_import_preview)
        self.index_width_spin.setStyleSheet(self.start_index_spin.styleSheet())
        top_layout.addWidget(self.index_width_spin, 0)

        meta_row = QWidget()
        meta_layout = QHBoxLayout(meta_row)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(10)
        layout.addWidget(meta_row, 0)

        meta_form = QFormLayout()
        meta_form.setContentsMargins(0, 0, 0, 0)
        meta_form.setSpacing(8)
        meta_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        meta_layout.addLayout(meta_form, 1)

        form_label_style = f"font-size: 13px; color: {text_color};"

        def _form_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setStyleSheet(form_label_style)
            return lbl

        self.species_input = QLineEdit()
        self.species_input.setPlaceholderText("物种（输入后可自动补全目科属）")
        self.species_input.textChanged.connect(self._on_species_changed)
        self.species_input.textEdited.connect(self._on_species_text_changed)
        self.species_input.setStyleSheet(self.rule_edit.styleSheet())
        try:
            self.species_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        meta_form.addRow(_form_label("物种:"), self.species_input)
        self._init_species_suggestions()

        self.order_input = QLineEdit()
        self.order_input.setPlaceholderText("目")
        self.order_input.textChanged.connect(self._on_classification_field_changed)
        self.order_input.setStyleSheet(self.rule_edit.styleSheet())
        try:
            self.order_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        meta_form.addRow(_form_label("目:"), self.order_input)

        self.family_input = QLineEdit()
        self.family_input.setPlaceholderText("科")
        self.family_input.textChanged.connect(self._on_classification_field_changed)
        self.family_input.setStyleSheet(self.rule_edit.styleSheet())
        try:
            self.family_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        meta_form.addRow(_form_label("科:"), self.family_input)

        self.genus_input = QLineEdit()
        self.genus_input.setPlaceholderText("属")
        self.genus_input.textChanged.connect(self._on_classification_field_changed)
        self.genus_input.setStyleSheet(self.rule_edit.styleSheet())
        try:
            self.genus_input.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        except Exception:
            pass
        meta_form.addRow(_form_label("属:"), self.genus_input)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        btn_row_layout.setSpacing(10)
        meta_layout.addWidget(btn_row, 0)

        self.apply_virtual_label_cb = QCheckBox("应用虚拟色标")
        self.apply_virtual_label_cb.setChecked(True)
        self.apply_virtual_label_cb.setVisible(bool(self._is_virtual_mode))
        self.apply_virtual_label_cb.setStyleSheet(f"color: {text_color};")
        btn_row_layout.addWidget(self.apply_virtual_label_cb, 0)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_btn.clicked.connect(self._on_select_all_clicked)
        self.select_all_btn.setStyleSheet(self.cancel_btn.styleSheet() if hasattr(self, "cancel_btn") else "")
        btn_row_layout.addWidget(self.select_all_btn, 0)

        self.select_none_btn = QPushButton("全不选")
        self.select_none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_none_btn.clicked.connect(self._on_select_none_clicked)
        self.select_none_btn.setStyleSheet(self.cancel_btn.styleSheet() if hasattr(self, "cancel_btn") else "")
        btn_row_layout.addWidget(self.select_none_btn, 0)

        self.apply_species_btn = QPushButton("设置到已选文件")
        self.apply_species_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_species_btn.clicked.connect(self._on_apply_species_to_selected_clicked)
        self.apply_species_btn.setStyleSheet(self.cancel_btn.styleSheet() if hasattr(self, "cancel_btn") else "")
        btn_row_layout.addWidget(self.apply_species_btn, 0)

        self.quick_detect_btn = QPushButton(qta.icon("ri.voice-recognition-fill", color=text_color), "快速检测")
        self.quick_detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_detect_btn.clicked.connect(self._on_quick_detect_clicked)
        self.quick_detect_btn.setStyleSheet(self.cancel_btn.styleSheet() if hasattr(self, "cancel_btn") else "")
        btn_row_layout.addWidget(self.quick_detect_btn, 0)

        btn_row_layout.addStretch(1)

        self.dest_label = QLabel("")
        self.dest_label.setStyleSheet(f"font-size: 12px; color: {text_color};")
        self.dest_label.setWordWrap(True)
        layout.addWidget(self.dest_label, 0)

        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(5)
        self.preview_table.setHorizontalHeaderLabels(["选择", "原文件名", "新文件名", "物种", "状态"])
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setWordWrap(True)
        try:
            self.preview_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        except Exception:
            pass
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
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
        self.preview_table.itemChanged.connect(self._on_table_item_changed)
        try:
            self.preview_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        except Exception:
            pass
        layout.addWidget(self.preview_table, 1)

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
        try:
            for b in (self.select_all_btn, self.select_none_btn, self.apply_species_btn, self.quick_detect_btn):
                b.setStyleSheet(self.cancel_btn.styleSheet())
        except Exception:
            pass
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

    def _on_classification_field_changed(self, _text: str = ""):
        if self._suppress_meta_change:
            return
        self._update_import_preview()

    def _on_species_changed(self, _text: str = ""):
        if self._suppress_meta_change:
            return
        species = (self.species_input.text() or "").strip()
        if not species:
            self._update_import_preview()
            return
        species_for_classifier = self._normalize_species_text(species)
        try:
            t = BirdBiologicalClassifier().classify(species_for_classifier)
        except Exception:
            t = None
        if t is not None:
            self._suppress_meta_change = True
            try:
                if not (self.order_input.text() or "").strip():
                    self.order_input.setText(str(getattr(t, "order_cn", "") or ""))
                if not (self.family_input.text() or "").strip():
                    self.family_input.setText(str(getattr(t, "family_cn", "") or ""))
                if not (self.genus_input.text() or "").strip():
                    self.genus_input.setText(str(getattr(t, "genus_cn", "") or ""))
            finally:
                self._suppress_meta_change = False
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
        cached = getattr(ImportToLibraryRenameDialog, "_species_text_alias_rules_cache", None)
        if cached is not None:
            return cached
        data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "species_text_aliases.json"))
        if not os.path.exists(data_path):
            data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "species_text_aliases.json"))
        rules: list[dict[str, str]] = []
        try:
            import json as _json
            with open(data_path, "r", encoding="utf-8") as f:
                raw = _json.load(f)
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
        ImportToLibraryRenameDialog._species_text_alias_rules_cache = rules
        return rules

    def _on_quick_detect_clicked(self):
        if self._import_running:
            return
        paths = self._get_checked_paths()
        if not paths:
            NotificationManager.instance().show_warning("提示", "请先选择文件")
            return
        p = str(paths[0] or "")
        if not p or not os.path.exists(p):
            NotificationManager.instance().show_warning("错误", "文件不存在")
            return
        task_id = StatusManager.instance().start_task("正在识别物种...")
        try:
            self.quick_detect_btn.setEnabled(False)
        except Exception:
            pass

        def extract_species_name(text: str) -> str:
            s = str(text or "").strip()
            if not s:
                return ""
            for sep in ("，", ",", "|", "｜", "；", ";"):
                if sep in s:
                    parts = [x.strip() for x in s.split(sep) if x.strip()]
                    if parts:
                        return parts[-1]
            return s

        def run():
            out = ""
            err = ""
            tmp_path = None
            try:
                # 检查是否为RAW文件，如果是则先转换为临时JPG
                raw_exts = {'.nef', '.raw', '.cr2', '.cr3', '.raf', '.orf', '.dng', '.arw'}
                ext = os.path.splitext(p)[1].lower()
                if ext in raw_exts:
                    # 使用load_image加载RAW文件（提取缩略图）
                    img = load_image(p)
                    if img is None:
                        raise RuntimeError("读取RAW图片失败：无法提取缩略图")
                    # 创建临时JPG文件
                    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
                    os.close(fd)
                    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    if not ok:
                        raise RuntimeError("RAW图片编码失败")
                    with open(tmp_path, "wb") as f:
                        f.write(bytes(buf))
                    # 使用临时文件路径进行识别
                    recognize_path = tmp_path
                else:
                    recognize_path = p

                # 定义状态回调函数，用于更新任务状态
                def status_callback(message):
                    try:
                        StatusManager.instance().update_task(task_id, message)
                    except Exception:
                        pass

                text = BirdSpeciesRecognizer().recognize(
                    recognize_path,
                    location_hint="",
                    time_hint="",
                    status_callback=status_callback
                ).text
                out = extract_species_name(text)
                if out == "无法识别":
                    out = ""
            except Exception as e:
                err = str(e)
            finally:
                # 清理临时文件
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
            try:
                self._quick_detect_done.emit(int(task_id), str(out or ""), str(err or ""))
            except Exception:
                pass

        Thread(target=run, daemon=True).start()

    def _on_quick_detect_done(self, task_id: int, species: str, err: str):
        try:
            StatusManager.instance().finish_task(int(task_id))
        except Exception:
            pass
        try:
            self.quick_detect_btn.setEnabled(not self._import_running)
        except Exception:
            pass
        if err and not species:
            NotificationManager.instance().show_warning("错误", f"物种识别失败: {err}")
            return
        s = str(species or "").strip()
        if not s:
            NotificationManager.instance().show_warning("提示", "物种识别失败")
            return
        try:
            self.species_input.setText(s)
        except Exception:
            pass
        NotificationManager.instance().show_toast("已填充物种名称")

    def _reload_db_records(self):
        paths = []
        for f in (self._selected_files or []):
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "")
            if p:
                paths.append(p)
        if not paths:
            self._db_record_map = {}
            return
        m = {}
        try:
            m.update(self._db.get_results_by_paths(paths, table_name="import_cache") or {})
        except Exception:
            pass
        try:
            m.update(self._db.get_results_by_paths(paths, table_name="bird_results") or {})
        except Exception:
            pass
        self._db_record_map = m

    def _get_library_root(self) -> str:
        root = str(self._settings_manager.get("general/root_path", "") or "").strip()
        return root

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

    def _sanitize_filename_base(self, name: str) -> str:
        s = str(name or "").strip()
        s = re.sub(r'[<>:"/\\\\|?*]', "_", s)
        s = re.sub(r"\s+", " ", s).strip()
        s = s.rstrip(".")
        return s

    def _build_candidate_name(self, file_info: dict, current_index: int, meta: dict[str, str]) -> tuple[str, int]:
        old_path = str(file_info.get("path") or "")
        old_name = os.path.basename(old_path)
        old_no_ext, ext = os.path.splitext(old_name)
        pattern = str(self.rule_edit.text() or "").strip()
        if not pattern:
            pattern = "{Original}_{Index}"

        name_base = pattern
        name_base = name_base.replace("{Species}", str(meta.get("species") or ""))
        name_base = name_base.replace("{Genus}", str(meta.get("genus") or ""))
        name_base = name_base.replace("{Family}", str(meta.get("family") or ""))
        name_base = name_base.replace("{Order}", str(meta.get("order") or ""))
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

    def _get_effective_meta_for_file(self, file_info: dict) -> dict[str, str]:
        src = str((file_info or {}).get("path") or "")
        rec = (self._db_record_map or {}).get(src) if src else None
        species = ""
        order = ""
        family = ""
        genus = ""
        try:
            if isinstance(rec, dict) and rec:
                species = str(rec.get("species_cls") or rec.get("object") or "").strip()
                order = str(rec.get("order_cls") or "").strip()
                family = str(rec.get("family_cls") or "").strip()
                genus = str(rec.get("genus_cls") or "").strip()
        except Exception:
            species = ""
            order = ""
            family = ""
            genus = ""
        if not species:
            try:
                species = str((file_info or {}).get("object") or (file_info or {}).get("species") or "").strip()
            except Exception:
                species = ""
        if species and (not order or not family or not genus):
            try:
                t = BirdBiologicalClassifier().classify(species)
            except Exception:
                t = None
            if t is not None:
                order = order or str(getattr(t, "order_cn", "") or "").strip()
                family = family or str(getattr(t, "family_cn", "") or "").strip()
                genus = genus or str(getattr(t, "genus_cn", "") or "").strip()
        return {"species": species, "order": order, "family": family, "genus": genus}

    def _get_checked_paths(self) -> list[str]:
        out = []
        for f in (self._selected_files or []):
            if not isinstance(f, dict):
                continue
            p = str(f.get("path") or "")
            if not p:
                continue
            if bool(self._checked_map.get(p, True)):
                out.append(p)
        return out

    def _set_all_checked(self, checked: bool):
        self._suppress_table_change = True
        try:
            for f in (self._selected_files or []):
                if not isinstance(f, dict):
                    continue
                p = str(f.get("path") or "")
                if not p:
                    continue
                self._checked_map[p] = bool(checked)
            for row in range(int(self.preview_table.rowCount())):
                it = self.preview_table.item(row, 0)
                if it is None:
                    continue
                it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self._suppress_table_change = False

    def _on_select_all_clicked(self):
        self._set_all_checked(True)

    def _on_select_none_clicked(self):
        self._set_all_checked(False)

    def _on_apply_species_to_selected_clicked(self):
        species = str(self.species_input.text() or "").strip()
        order = str(self.order_input.text() or "").strip()
        family = str(self.family_input.text() or "").strip()
        genus = str(self.genus_input.text() or "").strip()
        if not species or not order or not family or not genus:
            NotificationManager.instance().show_warning("提示", "请先补全 物种/目/科/属")
            return
        paths = self._get_checked_paths()
        if not paths:
            NotificationManager.instance().show_warning("提示", "请先选择文件")
            return
        updates = []
        for p in paths:
            updates.append(
                {
                    "path": p,
                    "object": species,
                    "order_cls": order,
                    "family_cls": family,
                    "genus_cls": genus,
                    "species_cls": species,
                }
            )
        try:
            self._db.update_taxonomy_batch_for_table(updates, table_name="import_cache")
        except Exception:
            pass
        try:
            self._db.update_taxonomy_batch_for_table(updates, table_name="bird_results")
        except Exception:
            pass
        try:
            for u in updates:
                p = str(u.get("path") or "")
                if not p:
                    continue
                rec = self._db_record_map.get(p)
                if not isinstance(rec, dict):
                    rec = {}
                    self._db_record_map[p] = rec
                rec["object"] = species
                rec["species_cls"] = species
                rec["order_cls"] = order
                rec["family_cls"] = family
                rec["genus_cls"] = genus
        except Exception:
            pass
        NotificationManager.instance().show_toast(f"已设置到 {len(paths)} 个文件")
        self._update_import_preview()

    def _update_import_preview(self):
        root = self._get_library_root()
        folder_used: dict[str, set[str]] = {}
        preview_map: dict[str, str] = {}
        preview_meta_map: dict[str, dict[str, str]] = {}
        rows = []
        current_index = int(self.start_index_spin.value())
        missing = 0
        target_folders: set[str] = set()

        for f in (self._selected_files or []):
            src = str((f or {}).get("path") or "")
            if not src:
                continue
            original_name = os.path.basename(src)
            meta = self._get_effective_meta_for_file(f)
            target_folder = self._get_target_folder_from_meta(meta)
            if not target_folder:
                missing += 1
                if src not in self._checked_map:
                    self._checked_map[src] = True
                rows.append((src, bool(self._checked_map.get(src, True)), original_name, "", str(meta.get("species") or ""), "缺少分类"))
                continue
            target_folders.add(target_folder)
            used = folder_used.setdefault(target_folder, set())

            manual_name = str(self._manual_name_map.get(src) or "").strip()
            if manual_name:
                candidate_name = manual_name
            else:
                candidate_name, current_index = self._build_candidate_name(f, current_index, meta=meta)
            dest_name, status = self._resolve_conflict_name(target_folder, candidate_name, used, src)
            dest_path = os.path.join(target_folder, dest_name)
            preview_map[src] = dest_path
            preview_meta_map[src] = meta
            if src not in self._checked_map:
                self._checked_map[src] = True
            rows.append((src, bool(self._checked_map.get(src, True)), original_name, dest_name, str(meta.get("species") or ""), status))

        self._preview_map = preview_map
        self._preview_meta_map = preview_meta_map

        count = len(self._selected_files)
        if not preview_map:
            self.dest_label.setText(f"目标目录: (请先补全 物种/目/科/属)  |  选中 {count} 张  |  根目录: {root}")
        else:
            if len(target_folders) == 1:
                only_folder = next(iter(target_folders))
                will_create = "将创建" if not os.path.exists(only_folder) else "已存在"
                extra = f" ({will_create})"
                self.dest_label.setText(f"目标目录: {only_folder}{extra}  |  选中 {count} 张  |  根目录: {root}" + (f"  |  未完成 {missing} 张" if missing else ""))
            else:
                self.dest_label.setText(f"目标目录: (多目录 {len(target_folders)} 个)  |  选中 {count} 张  |  根目录: {root}" + (f"  |  未完成 {missing} 张" if missing else ""))

        self._suppress_table_change = True
        try:
            self.preview_table.setRowCount(len(rows))
            for r, (src, checked, orig_name, dest_name, species, status) in enumerate(rows):
                item_check = QTableWidgetItem("")
                item_check.setFlags((item_check.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
                item_check.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item_check.setData(Qt.ItemDataRole.UserRole, src)
                self.preview_table.setItem(r, 0, item_check)

                item_old = QTableWidgetItem(orig_name)
                item_old.setToolTip(src)
                item_old.setFlags(item_old.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_old.setData(Qt.ItemDataRole.UserRole, src)
                self.preview_table.setItem(r, 1, item_old)

                item_new = QTableWidgetItem(dest_name)
                item_new.setToolTip(dest_name)
                item_new.setData(Qt.ItemDataRole.UserRole, src)
                self.preview_table.setItem(r, 2, item_new)

                item_species = QTableWidgetItem(str(species or ""))
                item_species.setToolTip(str(species or ""))
                item_species.setFlags(item_species.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.preview_table.setItem(r, 3, item_species)

                item_status = QTableWidgetItem(status)
                item_status.setFlags(item_status.flags() & ~Qt.ItemFlag.ItemIsEditable)
                try:
                    if "已存在" in status:
                        item_status.setForeground(Qt.GlobalColor.red)
                    elif "自动解决" in status:
                        item_status.setForeground(Qt.GlobalColor.blue)
                    elif status in ("未检测", "缺少分类"):
                        item_status.setForeground(Qt.GlobalColor.red)
                    else:
                        item_status.setForeground(Qt.GlobalColor.green)
                except Exception:
                    pass
                self.preview_table.setItem(r, 4, item_status)
        finally:
            self._suppress_table_change = False

        self.import_btn.setEnabled((not self._import_running) and bool(self._preview_map) and missing == 0)

    def _on_table_item_changed(self, item: QTableWidgetItem):
        if self._suppress_table_change:
            return
        if item is None:
            return
        col = int(item.column())
        try:
            src = str(item.data(Qt.ItemDataRole.UserRole) or "")
        except Exception:
            src = ""
        if not src:
            return

        if col == 0:
            desired = False
            try:
                desired = bool(item.checkState() == Qt.CheckState.Checked)
            except Exception:
                desired = True
            rows = []
            try:
                sm = self.preview_table.selectionModel()
                if sm is not None:
                    rows = [idx.row() for idx in (sm.selectedRows() or [])]
            except Exception:
                rows = []
            if not rows:
                try:
                    rows = [int(item.row())]
                except Exception:
                    rows = []
            if rows:
                self._suppress_table_change = True
                try:
                    for r in rows:
                        it2 = self.preview_table.item(int(r), 0)
                        if it2 is None:
                            continue
                        it2.setCheckState(Qt.CheckState.Checked if desired else Qt.CheckState.Unchecked)
                finally:
                    self._suppress_table_change = False
                for r in rows:
                    it2 = self.preview_table.item(int(r), 0)
                    if it2 is None:
                        continue
                    try:
                        src2 = str(it2.data(Qt.ItemDataRole.UserRole) or "")
                    except Exception:
                        src2 = ""
                    if not src2:
                        continue
                    self._checked_map[src2] = bool(desired)
            return

        if col != 2:
            return
        name = str(item.text() or "").strip()
        if not name:
            self._manual_name_map.pop(src, None)
            self._update_import_preview()
            return
        base, ext = os.path.splitext(name)
        if not ext:
            orig = os.path.basename(src)
            _, orig_ext = os.path.splitext(orig)
            ext = orig_ext
        clean_base = self._sanitize_filename_base(base)
        if not clean_base:
            return
        final = f"{clean_base}{ext}"
        self._manual_name_map[src] = final
        if final != name:
            self._suppress_table_change = True
            try:
                item.setText(final)
            finally:
                self._suppress_table_change = False
        self._update_import_preview()

    def _on_table_selection_changed(self):
        try:
            sm = self.preview_table.selectionModel()
            rows = [idx.row() for idx in (sm.selectedRows() or [])] if sm is not None else []
        except Exception:
            rows = []
        if not rows:
            return
        r = int(rows[0])
        try:
            src = str((self.preview_table.item(r, 1).data(Qt.ItemDataRole.UserRole) or "") if self.preview_table.item(r, 1) is not None else "")
        except Exception:
            src = ""
        if not src:
            return
        rec = None
        try:
            rec = self._db_record_map.get(src)
        except Exception:
            rec = None
        if not isinstance(rec, dict) or not rec:
            try:
                meta = self._preview_meta_map.get(src)
            except Exception:
                meta = None
            if isinstance(meta, dict) and meta:
                rec = {
                    "species_cls": meta.get("species"),
                    "order_cls": meta.get("order"),
                    "family_cls": meta.get("family"),
                    "genus_cls": meta.get("genus"),
                    "object": meta.get("species"),
                }
        if not isinstance(rec, dict) or not rec:
            return

        try:
            species = str(rec.get("species_cls") or rec.get("object") or "").strip()
            order = str(rec.get("order_cls") or "").strip()
            family = str(rec.get("family_cls") or "").strip()
            genus = str(rec.get("genus_cls") or "").strip()
        except Exception:
            species = ""
            order = ""
            family = ""
            genus = ""

        if species and (not order or not family or not genus):
            try:
                t = BirdBiologicalClassifier().classify(self._normalize_species_text(species))
            except Exception:
                t = None
            if t is not None:
                order = order or str(getattr(t, "order_cn", "") or "").strip()
                family = family or str(getattr(t, "family_cn", "") or "").strip()
                genus = genus or str(getattr(t, "genus_cn", "") or "").strip()

        if not species and not order and not family and not genus:
            return

        self._suppress_meta_change = True
        self._suppress_species_suggestions = True
        try:
            if species:
                self.species_input.setText(species)
            if order:
                self.order_input.setText(order)
            if family:
                self.family_input.setText(family)
            if genus:
                self.genus_input.setText(genus)
        finally:
            self._suppress_meta_change = False
            try:
                QTimer.singleShot(0, lambda: setattr(self, "_suppress_species_suggestions", False))
            except Exception:
                self._suppress_species_suggestions = False
        self._update_import_preview()

    def _set_busy(self, busy: bool):
        self._import_running = bool(busy)
        try:
            self.import_btn.setEnabled(not busy)
        except Exception:
            pass
        try:
            self.cancel_btn.setEnabled(not busy)
        except Exception:
            pass
        try:
            self.rule_edit.setEnabled(not busy)
            self.start_index_spin.setEnabled(not busy)
            self.index_width_spin.setEnabled(not busy)
            self.preview_table.setEnabled(not busy)
            self.species_input.setEnabled(not busy)
            self.order_input.setEnabled(not busy)
            self.family_input.setEnabled(not busy)
            self.genus_input.setEnabled(not busy)
            self.apply_virtual_label_cb.setEnabled(not busy)
            self.select_all_btn.setEnabled(not busy)
            self.select_none_btn.setEnabled(not busy)
            self.apply_species_btn.setEnabled(not busy)
            self.quick_detect_btn.setEnabled(not busy)
        except Exception:
            pass

    def _on_import_clicked(self):
        if self._import_running:
            return
        if not self._preview_map:
            NotificationManager.instance().show_warning("提示", "没有可导入的文件")
            return
        try:
            missing = max(0, len([x for x in (self._selected_files or []) if str((x or {}).get("path") or "") not in set(self._preview_map.keys())]))
        except Exception:
            missing = 0
        if missing:
            NotificationManager.instance().show_warning("提示", "请先补全 物种/目/科/属")
            return
        self._set_busy(True)
        task_id = StatusManager.instance().start_task("正在导入到图库...")

        def run():
            ok = True
            err = ""
            imported = 0
            db_rows = []
            try:
                exif_worker = ExifHandleWorker.get_instance()
                imported_at_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                apply_virtual_label = False
                try:
                    apply_virtual_label = bool(self._is_virtual_mode and self.apply_virtual_label_cb.isVisible() and self.apply_virtual_label_cb.isChecked())
                except Exception:
                    apply_virtual_label = False

                src_db_map = {}
                try:
                    # 原图数据始终在 import_cache 表中（导入页面的数据存储位置）
                    src_db_map = self._db.get_results_by_paths(list((self._preview_map or {}).keys()), table_name="import_cache") or {}
                except Exception:
                    src_db_map = {}

                def _first(meta: dict, keys: list[str]):
                    if not isinstance(meta, dict):
                        return None
                    for k in keys:
                        try:
                            if k in meta and meta.get(k) is not None:
                                return meta.get(k)
                        except Exception:
                            continue
                    return None

                def _parse_float(v, default=0.0):
                    if v is None:
                        return float(default)
                    try:
                        return float(v)
                    except Exception:
                        pass
                    try:
                        s = str(v).strip()
                        if not s:
                            return float(default)
                        if "/" in s:
                            a, b = s.split("/", 1)
                            return float(a) / float(b)
                        return float(s)
                    except Exception:
                        return float(default)

                def _parse_int(v, default=0):
                    if v is None:
                        return int(default)
                    try:
                        return int(float(v))
                    except Exception:
                        pass
                    try:
                        s = str(v).strip()
                        if not s:
                            return int(default)
                        return int(float(s))
                    except Exception:
                        return int(default)

                library_root = ""
                try:
                    library_root = str(self._get_library_root() or "").strip()
                except Exception:
                    library_root = ""

                def _is_under_root(path: str, root: str) -> bool:
                    if not path or not root:
                        return False
                    try:
                        p = os.path.normcase(os.path.normpath(os.path.abspath(path)))
                        r = os.path.normcase(os.path.normpath(os.path.abspath(root)))
                        return os.path.commonpath([p, r]) == r
                    except Exception:
                        try:
                            return os.path.normcase(os.path.normpath(path)).startswith(os.path.normcase(os.path.normpath(root)))
                        except Exception:
                            return False

                def _same_path(a: str, b: str) -> bool:
                    if not a or not b:
                        return False
                    try:
                        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))
                    except Exception:
                        return str(a) == str(b)

                for src, dst in (self._preview_map or {}).items():
                    if not src or not dst:
                        continue
                    try:
                        if os.path.normcase(os.path.normpath(str(src))) == os.path.normcase(os.path.normpath(str(dst))):
                            continue
                    except Exception:
                        if str(src) == str(dst):
                            continue
                    folder = os.path.dirname(dst)
                    os.makedirs(folder, exist_ok=True)
                    existing_rec = None
                    src_fast_id = ""
                    try:
                        src_fast_id = str(get_fast_id(src) or "").strip()
                    except Exception:
                        src_fast_id = ""
                    if src_fast_id:
                        try:
                            fast_map = self._db.get_results_by_fast_ids([src_fast_id], table_name="bird_results") or {}
                            rec = fast_map.get(src_fast_id)
                            if isinstance(rec, dict) and _same_path(str(rec.get("file_path") or ""), str(src)):
                                existing_rec = rec
                        except Exception:
                            existing_rec = None
                    if _is_under_root(src, library_root):
                        shutil.move(src, dst)
                    else:
                        shutil.copy2(src, dst)
                    imported += 1

                    meta_cls = {}
                    try:
                        meta_cls = dict((self._preview_meta_map or {}).get(str(src)) or {})
                    except Exception:
                        meta_cls = {}

                    exif_meta = {}
                    try:
                        exif_meta = exif_worker._read_sync(dst, READ_PICTURE_METADATA_TAG, timeout=12) or {}
                    except Exception:
                        try:
                            exif_meta = exif_worker.get_metadata(dst) or {}
                        except Exception:
                            exif_meta = {}

                    src_rec = existing_rec
                    if src_rec is None and src_db_map:
                        try:
                            src_rec = src_db_map.get(str(src))
                        except Exception:
                            src_rec = None

                    uuid = ""
                    # 检查原图是否被移动（不在原位置）
                    src_was_moved = not os.path.exists(str(src))
                    # 只有在原图被移动时才复用原图的uuid
                    if src_was_moved and isinstance(src_rec, dict) and src_rec.get("uuid"):
                        try:
                            uuid = str(src_rec.get("uuid") or "").strip()
                        except Exception:
                            uuid = ""
                    # 如果是复制（原图仍然存在），生成新的uuid，不读取exif中的uuid
                    # 避免和原图的uuid冲突
                    if not uuid and src_was_moved:
                        # 只有原图被移动时，才尝试从exif读取uuid
                        try:
                            uuid = str(
                                _first(
                                    exif_meta,
                                    [EXIF_TAG.Uuid.value, "Uuid", "XMP-bmp:Uuid", "XMP:bmp:Uuid"],
                                )
                                or ""
                            ).strip()
                        except Exception:
                            uuid = ""
                    if not uuid:
                        uuid = get_unique_id()

                    fast_id = ""
                    try:
                        fast_id = str(get_fast_id(dst) or "").strip()
                    except Exception:
                        fast_id = ""

                    # 只有在原图被移动（不在原位置）时才更新数据库记录
                    # 如果原图被复制（原位置仍然存在），则插入新记录
                    if isinstance(existing_rec, dict) and uuid and dst:
                        try:
                            # 检查原图是否被移动
                            src_exists = os.path.exists(str(src))
                            if not src_exists:
                                # 原图被移动，更新数据库记录
                                self._db.update_file_path_by_uuid(uuid, dst, table_name="bird_results")
                            # 如果原图仍然存在（被复制），则生成新的uuid，插入新记录
                        except Exception:
                            pass

                    try:
                        tags_to_write = {}
                        if uuid:
                            tags_to_write[EXIF_TAG.Uuid.value] = uuid
                        if fast_id:
                            tags_to_write[EXIF_TAG.Fastid.value] = fast_id
                        if apply_virtual_label and isinstance(src_rec, dict):
                            try:
                                vlabel = str(src_rec.get("label") or "").strip()
                            except Exception:
                                vlabel = ""
                            if vlabel:
                                tags_to_write[EXIF_TAG.Label.value] = vlabel
                        if tags_to_write:
                            exif_worker.write_tags(dst, tags_to_write)
                    except Exception:
                        pass

                    shot_time = ""
                    if isinstance(src_rec, dict) and str(src_rec.get("shot_time") or "").strip():
                        try:
                            shot_time = str(src_rec.get("shot_time") or "").strip()
                        except Exception:
                            shot_time = ""
                    try:
                        if not shot_time:
                            dt = exif_worker._read_sync(dst, READ_PICTURE_TIME_TAG, timeout=12)
                            if dt is not None:
                                shot_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        shot_time = ""
                    if not shot_time:
                        try:
                            ts = os.path.getctime(dst)
                            shot_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            shot_time = ""

                    fnumber = 0.0
                    if isinstance(src_rec, dict):
                        fnumber = _parse_float(src_rec.get("fnumber"), default=0.0)
                    if not fnumber:
                        fnumber = _parse_float(_first(exif_meta, ["ApertureValue", "EXIF:ApertureValue", "FNumber", "EXIF:FNumber"]), default=0.0)
                    shutter = ""
                    if isinstance(src_rec, dict):
                        try:
                            shutter = str(src_rec.get("shutter") or "").strip()
                        except Exception:
                            shutter = ""
                    try:
                        if not shutter:
                            shutter = str(
                                _first(
                                    exif_meta,
                                    ["ExposureTime", "EXIF:ExposureTime", "ShutterSpeedValue", "EXIF:ShutterSpeedValue"],
                                )
                                or ""
                            ).strip()
                    except Exception:
                        shutter = ""
                    iso = 0
                    if isinstance(src_rec, dict):
                        iso = _parse_int(src_rec.get("iso"), default=0)
                    if not iso:
                        iso = _parse_int(_first(exif_meta, ["ISO", "EXIF:ISO", "PhotographicSensitivity", "EXIF:PhotographicSensitivity"]), default=0)
                    focal_length = ""
                    if isinstance(src_rec, dict):
                        try:
                            focal_length = str(src_rec.get("focal_length") or "").strip()
                        except Exception:
                            focal_length = ""
                    try:
                        if not focal_length:
                            focal_length = str(_first(exif_meta, ["FocalLength", "EXIF:FocalLength"]) or "").strip()
                    except Exception:
                        focal_length = ""
                    camera_model = ""
                    if isinstance(src_rec, dict):
                        try:
                            camera_model = str(src_rec.get("camera_model") or "").strip()
                        except Exception:
                            camera_model = ""
                    try:
                        if not camera_model:
                            camera_model = str(_first(exif_meta, ["Model", "EXIF:Model"]) or "").strip()
                    except Exception:
                        camera_model = ""
                    lens_model = ""
                    if isinstance(src_rec, dict):
                        try:
                            lens_model = str(src_rec.get("lens_model") or "").strip()
                        except Exception:
                            lens_model = ""
                    try:
                        if not lens_model:
                            lens_model = str(_first(exif_meta, ["LensModel", "EXIF:LensModel"]) or "").strip()
                    except Exception:
                        lens_model = ""
                    focus_distance = ""
                    if isinstance(src_rec, dict):
                        try:
                            focus_distance = str(src_rec.get("focus_distance") or "").strip()
                        except Exception:
                            focus_distance = ""
                    try:
                        if not focus_distance:
                            focus_distance = str(_first(exif_meta, ["FocusDistance", "EXIF:FocusDistance"]) or "").strip()
                    except Exception:
                        focus_distance = ""

                    label = ""
                    if apply_virtual_label and isinstance(src_rec, dict) and str(src_rec.get("label") or "").strip():
                        try:
                            label = str(src_rec.get("label") or "").strip()
                        except Exception:
                            label = ""
                    if (not label) and (not bool(getattr(self, "_is_virtual_mode", False))) and isinstance(src_rec, dict) and str(src_rec.get("label") or "").strip():
                        try:
                            label = str(src_rec.get("label") or "").strip()
                        except Exception:
                            label = ""
                    if not label:
                        try:
                            label = str(_first(exif_meta, [EXIF_TAG.Label.value, "Label", "XMP:Label"]) or "").strip()
                        except Exception:
                            label = ""
                    rating = 0
                    if isinstance(src_rec, dict):
                        rating = _parse_int(src_rec.get("rating"), default=0)
                    try:
                        if not rating:
                            rating = _parse_int(_first(exif_meta, [EXIF_TAG.Rating.value, "Rating", "XMP:Rating"]), default=0)
                    except Exception:
                        rating = 0
                    is_favorite = 0
                    if isinstance(src_rec, dict):
                        try:
                            is_favorite = 1 if int(src_rec.get("is_favorite") or 0) == 1 else 0
                        except Exception:
                            is_favorite = 0
                    try:
                        if not is_favorite:
                            fav = str(_first(exif_meta, [EXIF_TAG.Favorite.value, "Favorite"]) or "").strip().lower()
                            is_favorite = 1 if fav == "true" else 0
                    except Exception:
                        is_favorite = 0
                    location = ""
                    if isinstance(src_rec, dict):
                        try:
                            location = str(src_rec.get("location") or "").strip()
                        except Exception:
                            location = ""
                    try:
                        if not location:
                            location = str(_first(exif_meta, [EXIF_TAG.Location.value, "Location"]) or "").strip()
                    except Exception:
                        location = ""
                    tags = ""
                    if isinstance(src_rec, dict):
                        try:
                            tags = str(src_rec.get("tags") or "").strip()
                        except Exception:
                            tags = ""
                    try:
                        if not tags:
                            tags = str(_first(exif_meta, [EXIF_TAG.Tags.value, "Tags"]) or "").strip()
                    except Exception:
                        tags = ""

                    species = str(meta_cls.get("species") or "").strip()
                    order_cls = str(meta_cls.get("order") or "").strip()
                    family_cls = str(meta_cls.get("family") or "").strip()
                    genus_cls = str(meta_cls.get("genus") or "").strip()
                    if isinstance(src_rec, dict):
                        try:
                            species = species or str(src_rec.get("species_cls") or src_rec.get("object") or "").strip()
                        except Exception:
                            pass
                        try:
                            order_cls = order_cls or str(src_rec.get("order_cls") or "").strip()
                            family_cls = family_cls or str(src_rec.get("family_cls") or "").strip()
                            genus_cls = genus_cls or str(src_rec.get("genus_cls") or "").strip()
                        except Exception:
                            pass

                    score = 0.0
                    norm_score = 0.0
                    bbox = None
                    position = ""
                    pixel_count = 0
                    area_ratio = 0.0
                    focus_point = None
                    eye_coordinates = None
                    description = ""
                    focus_detect_json = ""
                    lat = 0.0
                    lng = 0.0
                    if isinstance(src_rec, dict):
                        try:
                            score = float(src_rec.get("score") or 0.0)
                        except Exception:
                            score = 0.0
                        try:
                            norm_score = float(src_rec.get("norm_score") or 0.0)
                        except Exception:
                            norm_score = 0.0
                        try:
                            bbox = src_rec.get("bbox")
                        except Exception:
                            bbox = None
                        try:
                            position = str(src_rec.get("position") or "").strip()
                        except Exception:
                            position = ""
                        try:
                            pixel_count = int(src_rec.get("pixel_count") or 0)
                        except Exception:
                            pixel_count = 0
                        try:
                            area_ratio = float(src_rec.get("area_ratio") or 0.0)
                        except Exception:
                            area_ratio = 0.0
                        try:
                            focus_point = src_rec.get("focus_point")
                        except Exception:
                            focus_point = None
                        try:
                            eye_coordinates = src_rec.get("eye_coordinates")
                        except Exception:
                            eye_coordinates = None
                        try:
                            description = str(src_rec.get("description") or "").strip()
                        except Exception:
                            description = ""
                        try:
                            focus_detect_json = str(src_rec.get("focus_detect_json") or "").strip()
                        except Exception:
                            focus_detect_json = ""
                        try:
                            lat = float(src_rec.get("latitude") or 0.0)
                            lng = float(src_rec.get("longitude") or 0.0)
                        except Exception:
                            lat = 0.0
                            lng = 0.0

                    db_rows.append(
                        {
                            "uuid": uuid,
                            "fast_id": fast_id,
                            "path": dst,
                            "file": os.path.basename(dst),
                            "label": label,
                            "score": score,
                            "norm_score": norm_score,
                            "bbox": bbox,
                            "position": position,
                            "pixel_count": pixel_count,
                            "area_ratio": area_ratio,
                            "focus_point": focus_point,
                            "object": species,
                            "order_cls": order_cls,
                            "family_cls": family_cls,
                            "genus_cls": genus_cls,
                            "species_cls": species,
                            "eye_coordinates": eye_coordinates,
                            "description": description,
                            "focus_detect_json": focus_detect_json,
                            "is_favorite": is_favorite,
                            "rating": rating,
                            "shot_time": shot_time,
                            "fnumber": float(fnumber or 0.0),
                            "shutter": shutter,
                            "iso": float(iso or 0),
                            "focal_length": focal_length,
                            "camera_model": camera_model,
                            "lens_model": lens_model,
                            "focus_distance": focus_distance,
                            "latitude": lat,
                            "longitude": lng,
                            "location": location,
                            "tags": tags,
                            "imported_at": imported_at_now,
                        }
                    )
            except Exception as e:
                ok = False
                err = str(e)
            if ok:
                try:
                    if db_rows:
                        self._db.save_results_batch(db_rows, table_name="bird_results")
                except Exception as e:
                    ok = False
                    err = str(e)
            try:
                self._import_finished.emit(int(task_id), ok, imported, err)
            except Exception:
                pass

        Thread(target=run, daemon=True).start()

    def _on_import_finished(self, task_id: int, ok: bool, imported: int, err: str):
        try:
            StatusManager.instance().finish_task(int(task_id))
        except Exception:
            pass
        self._set_busy(False)
        if not ok:
            NotificationManager.instance().show_warning("错误", f"导入失败: {err}")
            return
        try:
            target_folders = set()
            for dst in (self._preview_map or {}).values():
                if not dst:
                    continue
                target_folders.add(os.path.dirname(str(dst)))
            if len(target_folders) == 1:
                target_folder = str(next(iter(target_folders)) or "")
            else:
                target_folder = str(self._get_library_root() or "")
        except Exception:
            target_folder = str(self._get_library_root() or "")
        try:
            self.import_succeeded.emit(target_folder)
        except Exception:
            pass
        NotificationManager.instance().show_toast(f"导入完成：{imported} 张")
        self.accept()
