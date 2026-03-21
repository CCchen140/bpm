from __future__ import annotations

import os
from typing import Any
from threading import Thread
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QFormLayout,
    QGridLayout,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QSizePolicy,
    QFileDialog,
    QSplitter,
    QScrollArea,
    QSlider,
)
from ui.utils.icon_loader import qta

from ui.widgets.base_popup_dialog import BasePopupDialog
from ui.utils.color_manager import ColorManager
from ui.widgets.themed_combo_box import ThemedComboBox
from utils.setting.settings_manager import SettingsManager
from ui.utils.notification_manager import NotificationManager


class FocusDetectDialog(BasePopupDialog):
    def __init__(self, parent=None, folders: list[str] | None = None, folder_image_counts: dict[str, int] | None = None):
        super().__init__(parent=parent, title="对焦检测", size=(980, 760))
        self.settings_manager = SettingsManager()
        self._folders = [str(p) for p in (folders or []) if p]
        self._folder_image_counts = dict(folder_image_counts or {})
        self._folder_time_ranges: dict[str, tuple[float | None, float | None]] = {}
        self._saved_selected_folders: list[str] = []
        self._force_select_all_once = False
        self._force_select_none_once = False
        self._default_folder_check_state = None
        self._override_saved_folder_selection = False
        self._folder_extensions_map: dict[str, set[str]] = {}
        self._unchecked_extensions: set[str] = set()
        self._scanning = False
        self._yolo_prewarm_cancel = False
        self._yolo_prewarm_thread = None
        self._folder_build_timer = None
        self._folder_build_token = 0
        self._folder_build_index = 0
        self._folder_prev_states = {}
        self.selected_folders: list[str] = []
        self.options: dict[str, Any] = {}
        self._loading_settings = False
        self._settings_sync_timer = None
        self._init_ui()
        try:
            self.setMinimumWidth(900)
        except Exception:
            pass
        self._load_settings()
        try:
            self._wire_settings_persistence()
        except Exception:
            pass
        try:
            self.set_folders_and_counts(self._folders, self._folder_image_counts)
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._start_folder_build)
        except Exception:
            self._start_folder_build()
        try:
            self._yolo_prewarm_thread = None
            self._yolo_prewarm_cancel = True
        except Exception:
            pass

    def _normalize_folder_key(self, p: str) -> str:
        try:
            return os.path.normcase(os.path.normpath(str(p)))
        except Exception:
            try:
                return str(p)
            except Exception:
                return ""

    def _dedup_folders_with_counts(self, folders: list[str], folder_image_counts: dict[str, int] | None):
        raw_folders = [str(p) for p in (folders or []) if p]
        raw_counts = dict(folder_image_counts or {})
        norm_to_rep: dict[str, str] = {}
        rep_counts: dict[str, int] = {}
        for p in (raw_folders or []):
            k = self._normalize_folder_key(p)
            if not k:
                continue
            rep = norm_to_rep.get(k)
            if not rep:
                rep = str(p)
                norm_to_rep[k] = rep
            try:
                cnt = int(raw_counts.get(str(p)) or 0)
            except Exception:
                cnt = 0
            prev = rep_counts.get(rep)
            if prev is None:
                rep_counts[rep] = cnt
            else:
                rep_counts[rep] = max(int(prev), int(cnt))
        return list(norm_to_rep.values()), dict(rep_counts)

    def _start_yolo_prewarm(self):
        if self._yolo_prewarm_thread is not None:
            return
        self._yolo_prewarm_cancel = False

        def run():
            try:
                if bool(getattr(self, "_yolo_prewarm_cancel", False)):
                    return
            except Exception:
                pass
            try:
                model = str(self.model_combo.currentText() or "x").lower()
            except Exception:
                model = "x"
            try:
                target_size = int(self.target_size_spin.value())
            except Exception:
                target_size = 640
            try:
                use_gpu = bool((self._option_items or {}).get("use_gpu").isChecked())
            except Exception:
                use_gpu = True
            try:
                multi_check = bool((self._option_items or {}).get("multi_check").isChecked())
            except Exception:
                multi_check = True
            try:
                exp_frame_check = bool((self._option_items or {}).get("exp_frame_check").isChecked())
            except Exception:
                exp_frame_check = True

            try:
                from core.check_cli import prewarm_focus_detector

                prewarm_focus_detector(
                    model=model,
                    target_size=target_size,
                    use_gpu=use_gpu,
                    multi_check=multi_check,
                    exp_frame_check=exp_frame_check,
                )
            except Exception:
                pass
            return

        t = Thread(target=run, daemon=True, name="YoloPrewarm")
        self._yolo_prewarm_thread = t
        t.start()

    def _cancel_yolo_prewarm(self):
        self._yolo_prewarm_cancel = True
        return

    def reject(self):
        try:
            self._cancel_yolo_prewarm()
        except Exception:
            pass
        return super().reject()

    def closeEvent(self, event):
        try:
            self._cancel_yolo_prewarm()
        except Exception:
            pass
        return super().closeEvent(event)

    def _init_ui(self):
        cm = ColorManager.instance()
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        text_color = cm.get("popup.text.primary", "#333333")
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        primary_color = cm.get("theme.primary", "#2196F3")
        light_bg = cm.get("theme.background.light", "#FFFFFF")

        self.set_bottom_bar_style(self.get_footer_background(), border_color)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {light_bg};
            }}
            QScrollBar:vertical {{
                background-color: transparent;
                width: 10px;
                margin: 2px 0 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background-color: {border_color};
                min-height: 30px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {primary_color};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)
        scroll_container = QWidget()
        scroll_container.setStyleSheet(f"background-color: {light_bg};")
        scroll_layout = QVBoxLayout(scroll_container)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)
        scroll_area.setWidget(scroll_container)
        self.content_layout.addWidget(scroll_area, 1)

        folder_group = QGroupBox("选择检测文件夹")
        folder_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {border_color};
                border-radius: 8px;
                padding: 12px;
                margin-top: 8px;
                background-color: {light_bg};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {text_color};
                font-weight: 600;
            }}
        """)
        folder_layout = QVBoxLayout(folder_group)
        folder_layout.setContentsMargins(10, 15, 10, 10)
        folder_layout.setSpacing(8)

        self.folder_search_input = QLineEdit()
        self.folder_search_input.setPlaceholderText("搜索文件夹（支持模糊）")
        try:
            self.folder_search_input.setClearButtonEnabled(True)
        except Exception:
            pass
        try:
            self.folder_search_input.setFixedHeight(28)
        except Exception:
            pass
        self.folder_search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {light_bg};
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 4px 8px;
                color: {text_color};
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        try:
            self.folder_search_input.textChanged.connect(lambda _t=None: self._apply_folder_filter())
        except Exception:
            pass
        folder_search_row = QWidget()
        folder_search_row_layout = QHBoxLayout(folder_search_row)
        folder_search_row_layout.setContentsMargins(0, 0, 0, 0)
        folder_search_row_layout.setSpacing(0)
        folder_search_row_layout.addWidget(self.folder_search_input, 1)
        folder_layout.addWidget(folder_search_row)

        folder_toolbar = QWidget()
        folder_toolbar_layout = QHBoxLayout(folder_toolbar)
        folder_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        folder_toolbar_layout.setSpacing(8)

        self.select_all_btn = QPushButton("全选")
        self.select_none_btn = QPushButton("全不选")
        self.select_all_btn.clicked.connect(self._select_all_folders)
        self.select_none_btn.clicked.connect(self._select_none_folders)
        for b in (self.select_all_btn, self.select_none_btn):
            b.setStyleSheet(f"""
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
        folder_toolbar_layout.addWidget(self.select_all_btn)
        folder_toolbar_layout.addWidget(self.select_none_btn)

        self.folder_sort_key_combo = ThemedComboBox()
        self.folder_sort_key_combo.addItem("最晚时间", "max")
        self.folder_sort_key_combo.addItem("最早时间", "min")
        self.folder_sort_key_combo.addItem("文件夹名", "name")
        try:
            self.folder_sort_key_combo.setFixedHeight(28)
        except Exception:
            pass
        try:
            self.folder_sort_key_combo.currentIndexChanged.connect(lambda _i=None: self._reapply_folder_sort())
        except Exception:
            pass
        folder_toolbar_layout.addWidget(self.folder_sort_key_combo)

        self.folder_sort_order_combo = ThemedComboBox()
        self.folder_sort_order_combo.addItem("倒序", "desc")
        self.folder_sort_order_combo.addItem("正序", "asc")
        try:
            self.folder_sort_order_combo.setFixedHeight(28)
        except Exception:
            pass
        try:
            self.folder_sort_order_combo.currentIndexChanged.connect(lambda _i=None: self._reapply_folder_sort())
        except Exception:
            pass
        folder_toolbar_layout.addWidget(self.folder_sort_order_combo)

        folder_toolbar_layout.addStretch(1)

        folder_layout.addWidget(folder_toolbar)

        self.folder_selection_label = QLabel("")
        self.folder_selection_label.setStyleSheet(f"color: {text_color}; font-size: 12px;")
        try:
            self.folder_selection_label.setWordWrap(True)
            self.folder_selection_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        except Exception:
            pass
        folder_layout.addWidget(self.folder_selection_label)

        self.scan_status_label = QLabel("")
        self.scan_status_label.setStyleSheet(f"color: {text_color}; font-size: 12px;")
        try:
            self.scan_status_label.setWordWrap(True)
            self.scan_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        except Exception:
            pass
        folder_layout.addWidget(self.scan_status_label)

        self.folder_list = QListWidget()
        self.folder_list.setStyleSheet(f"""
            QListWidget {{
                border: 1px solid {border_color};
                border-radius: 4px;
                color: {text_color};
                background-color: {light_bg};
            }}
            QListWidget::item {{
                padding: 7px 10px;
            }}
            QListWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QListWidget::item:selected {{
                background-color: {primary_color};
                color: white;
            }}
            QScrollBar:vertical {{
                background-color: {light_bg};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {border_color};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {primary_color};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                background-color: {light_bg};
                height: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {border_color};
                min-width: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {primary_color};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """)
        try:
            self.folder_list.setMinimumHeight(170)
        except Exception:
            pass
        try:
            self.folder_list.itemChanged.connect(lambda _it: (self._update_folder_selection_label(), self._apply_folder_filter(), self._update_detect_threads()))
        except Exception:
            pass
        folder_layout.addWidget(self.folder_list, 1)

        params_group = QGroupBox("参数设置")
        params_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {border_color};
                border-radius: 8px;
                padding: 12px;
                margin-top: 8px;
                background-color: {light_bg};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {text_color};
                font-weight: 600;
            }}
            QLabel {{
                color: {text_color};
            }}
        """)
        params_layout = QVBoxLayout(params_group)
        params_layout.setContentsMargins(10, 15, 10, 10)
        params_layout.setSpacing(10)

        options_card = QWidget()
        options_card.setStyleSheet(f"""
            QWidget {{
                border: 1px solid {border_color};
                border-radius: 6px;
                background-color: {light_bg};
            }}
            QCheckBox {{
                padding: 6px 10px;
                font-size: 13px;
                color: {text_color};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid {border_color};
                background-color: {light_bg};
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {primary_color};
            }}
            QCheckBox::indicator:checked {{
                background-color: {primary_color};
                border: 1px solid {primary_color};
            }}
        """)
        options_grid = QGridLayout(options_card)
        options_grid.setContentsMargins(6, 6, 6, 6)
        options_grid.setHorizontalSpacing(18)
        options_grid.setVerticalSpacing(6)

        self._option_items: dict[str, QCheckBox] = {}
        option_defs = [
            ("enable_burst", "进行连拍检测", True),
            ("enable_similarity", "进行相似度检测", True),
            ("use_multiprocess", "使用多进程加速", True),
            ("use_gpu", "使用GPU加速", True),
            ("multi_check", "进行多次检测", True),
            ("exp_frame_check", "进行爆框检测", True),
            ("enable_eye_detect", "进行鸟眼检测", True),
            ("enable_af_point_detect", "识别对焦点", True),
            ("append_detect", "追加检测", False),
            ("no_db_write", "不写入数据库", False),
        ]
        for idx, (key, text, default_checked) in enumerate(option_defs):
            cb = QCheckBox(text)
            cb.setChecked(bool(default_checked))
            self._option_items[key] = cb
            r = idx // 2
            c = idx % 2
            options_grid.addWidget(cb, r, c)

        params_layout.addWidget(options_card)

        exif_row = QWidget()
        exif_row_layout = QHBoxLayout(exif_row)
        exif_row_layout.setContentsMargins(0, 0, 0, 0)
        exif_row_layout.setSpacing(10)
        exif_label = QLabel("元数据写入：")
        exif_label.setStyleSheet(f"color: {text_color}; font-size: 13px;")
        self.exif_write_mode_combo = ThemedComboBox()
        self.exif_write_mode_combo.addItem("写入文件EXIF", "file")
        self.exif_write_mode_combo.addItem("写入XMP文件", "xmp")
        self.exif_write_mode_combo.addItem("不写入EXIF", "none")
        try:
            mode = str(self.settings_manager.get("exif/write_mode", "file") or "file").strip().lower()
        except Exception:
            mode = "file"
        try:
            if bool(self.settings_manager.get("exif/disable_write", False)):
                mode = "none"
        except Exception:
            pass
        if mode not in ("file", "xmp", "none"):
            mode = "file"
        try:
            for i in range(self.exif_write_mode_combo.count()):
                if str(self.exif_write_mode_combo.itemData(i) or "") == mode:
                    self.exif_write_mode_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass
        exif_row_layout.addWidget(exif_label)
        exif_row_layout.addWidget(self.exif_write_mode_combo, 1)
        params_layout.addWidget(exif_row)

        # File Types Group
        self.file_type_group = QGroupBox("文件类型")
        self.file_type_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {border_color};
                border-radius: 6px;
                background-color: {light_bg};
                margin-top: 8px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: {text_color};
                font-weight: 600;
            }}
            QCheckBox {{
                padding: 6px 10px;
                font-size: 13px;
                color: {text_color};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid {border_color};
                background-color: {light_bg};
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {primary_color};
            }}
            QCheckBox::indicator:checked {{
                background-color: {primary_color};
                border: 1px solid {primary_color};
            }}
        """)
        self.file_type_layout = QGridLayout(self.file_type_group)
        self.file_type_layout.setContentsMargins(10, 15, 10, 10)
        self.file_type_layout.setHorizontalSpacing(18)
        self.file_type_layout.setVerticalSpacing(6)
        params_layout.addWidget(self.file_type_group)
        self.extension_checkboxes: dict[str, QCheckBox] = {}
        self.file_type_group.setVisible(False)  # Hide initially until extensions are found

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.model_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        self.model_combo.addItems(["n", "s", "m", "l", "x"])
        self.model_combo.setCurrentText("x")
        form.addRow("检测模型:", self.model_combo)

        self.initial_conf_spin = QDoubleSpinBox()
        self.initial_conf_spin.setRange(0.0, 1.0)
        self.initial_conf_spin.setSingleStep(0.01)
        try:
            self.initial_conf_spin.setDecimals(2)
        except Exception:
            pass
        self.initial_conf_spin.setValue(0.15)
        self.initial_conf_spin.setStyleSheet(f"padding: 6px 10px; border: 1px solid {border_color}; border-radius: 4px; color: {text_color}; background-color: {light_bg};")
        form.addRow("初始置信度:", self.initial_conf_spin)

        self.target_size_spin = QSpinBox()
        self.target_size_spin.setRange(256, 2048)
        self.target_size_spin.setSingleStep(32)
        self.target_size_spin.setValue(640)
        self.target_size_spin.setStyleSheet(f"padding: 6px 10px; border: 1px solid {border_color}; border-radius: 4px; color: {text_color}; background-color: {light_bg};")
        form.addRow("缩放尺寸:", self.target_size_spin)

        self.burst_min_count_spin = QSpinBox()
        self.burst_min_count_spin.setRange(1, 999)
        self.burst_min_count_spin.setValue(10)
        self.burst_min_count_spin.setStyleSheet(f"padding: 6px 10px; border: 1px solid {border_color}; border-radius: 4px; color: {text_color}; background-color: {light_bg};")
        form.addRow("连拍检测最小张数:", self.burst_min_count_spin)

        self.burst_fps_spin = QSpinBox()
        self.burst_fps_spin.setRange(1, 120)
        self.burst_fps_spin.setValue(20)
        self.burst_fps_spin.setStyleSheet(f"padding: 6px 10px; border: 1px solid {border_color}; border-radius: 4px; color: {text_color}; background-color: {light_bg};")
        form.addRow("连拍频率(FPS):", self.burst_fps_spin)

        # 检测CPU核心数，计算检测线程数
        try:
            cpu_count = int(os.cpu_count() or 4)
        except Exception:
            cpu_count = 4
        cpu_count = max(4, cpu_count)
        # 默认检测线程数：全部CPU核心数减4
        default_threads = max(1, cpu_count - 4)
        
        self.detect_threads_spin = QSpinBox()
        self.detect_threads_spin.setRange(1, cpu_count)
        self.detect_threads_spin.setValue(default_threads)
        self.detect_threads_spin.setStyleSheet(f"padding: 6px 10px; border: 1px solid {border_color}; border-radius: 4px; color: {text_color}; background-color: {light_bg};")
        self.detect_threads_label = QLabel(f"自动")
        self.detect_threads_label.setStyleSheet(f"color: {text_color}; font-size: 11px;")
        threads_row = QHBoxLayout()
        threads_row.addWidget(self.detect_threads_spin)
        threads_row.addWidget(self.detect_threads_label, 1)
        form.addRow("检测线程数:", threads_row)

        params_layout.addLayout(form)

        post_group = QGroupBox("检测后处理")
        post_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {border_color};
                border-radius: 8px;
                padding: 12px;
                margin-top: 8px;
                background-color: {light_bg};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {text_color};
                font-weight: 600;
            }}
            QLabel {{
                color: {text_color};
            }}
        """)
        post_layout = QFormLayout(post_group)
        post_layout.setContentsMargins(10, 15, 10, 10)
        post_layout.setSpacing(10)
        post_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.post_action_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        self.post_action_combo.addItem("不处理", "none")
        self.post_action_combo.addItem("复制到目标目录", "copy")
        self.post_action_combo.addItem("剪切到目标目录", "move")
        self.post_action_combo.addItem("按虚拟文件分类复制到目标目录", "copy_by_status")
        self.post_action_combo.addItem("按虚拟文件分类剪切到目标目录", "move_by_status")
        self.post_action_combo.addItem("按虚拟文件分类复制到原目录", "copy_by_status_to_source")
        self.post_action_combo.addItem("按虚拟文件分类剪切到原目录", "move_by_status_to_source")
        try:
            self.post_action_combo.currentIndexChanged.connect(self._update_post_action_ui)
        except Exception:
            pass
        post_layout.addRow("文件处理:", self.post_action_combo)

        post_dir_row = QWidget()
        post_dir_row_layout = QHBoxLayout(post_dir_row)
        post_dir_row_layout.setContentsMargins(0, 0, 0, 0)
        post_dir_row_layout.setSpacing(8)
        self.post_dir_label = QLabel("")
        self.post_dir_label.setStyleSheet(f"color: {text_color}; font-size: 12px;")
        try:
            self.post_dir_label.setWordWrap(False)
            self.post_dir_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        except Exception:
            pass
        self.post_dir_choose_btn = QPushButton("选择")
        self.post_dir_clear_btn = QPushButton("清除")
        for b in (self.post_dir_choose_btn, self.post_dir_clear_btn):
            b.setStyleSheet(f"""
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
        try:
            self.post_dir_choose_btn.clicked.connect(self._choose_post_dir)
            self.post_dir_clear_btn.clicked.connect(self._clear_post_dir)
        except Exception:
            pass
        post_dir_row_layout.addWidget(self.post_dir_label, 1)
        post_dir_row_layout.addWidget(self.post_dir_choose_btn)
        post_dir_row_layout.addWidget(self.post_dir_clear_btn)
        post_layout.addRow("目标目录:", post_dir_row)

        self.finish_action_combo = ThemedComboBox(font_size=12, padding="6px 10px")
        self.finish_action_combo.addItem("无操作", "none")
        self.finish_action_combo.addItem("关闭程序", "quit_app")
        self.finish_action_combo.addItem("关闭计算机", "shutdown_pc")
        self.finish_action_combo.addItem("执行脚本", "run_script")
        post_layout.addRow("检测结束执行:", self.finish_action_combo)

        finish_script_row = QWidget()
        finish_script_row_layout = QHBoxLayout(finish_script_row)
        finish_script_row_layout.setContentsMargins(0, 0, 0, 0)
        finish_script_row_layout.setSpacing(8)
        self.finish_script_label = QLabel("")
        self.finish_script_label.setStyleSheet(f"color: {text_color}; font-size: 12px;")
        try:
            self.finish_script_label.setWordWrap(False)
            self.finish_script_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        except Exception:
            pass
        self.finish_script_choose_btn = QPushButton("选择")
        self.finish_script_clear_btn = QPushButton("清除")
        for b in (self.finish_script_choose_btn, self.finish_script_clear_btn):
            b.setStyleSheet(f"""
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
        try:
            self.finish_script_choose_btn.clicked.connect(self._choose_finish_script)
            self.finish_script_clear_btn.clicked.connect(self._clear_finish_script)
        except Exception:
            pass
        finish_script_row_layout.addWidget(self.finish_script_label, 1)
        finish_script_row_layout.addWidget(self.finish_script_choose_btn)
        finish_script_row_layout.addWidget(self.finish_script_clear_btn)
        post_layout.addRow("脚本路径:", finish_script_row)

        params_layout.addWidget(post_group)

        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.addWidget(folder_group)
        top_splitter.addWidget(params_group)
        try:
            top_splitter.setStretchFactor(0, 2)
            top_splitter.setStretchFactor(1, 3)
        except Exception:
            pass
        scroll_layout.addWidget(top_splitter)

        self.cancel_btn = QPushButton(qta.icon("mdi6.close", color=text_color), "取消")
        self.ok_btn = QPushButton(qta.icon("mdi6.check", color=text_color), "开始检测")
        for b in (self.cancel_btn, self.ok_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {control_bg};
                    border: 1px solid {border_color};
                    border-radius: 4px;
                    padding: 8px 14px;
                    font-size: 13px;
                    color: {text_color};
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                    border: 1px solid {primary_color};
                }}
            """)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._on_ok_clicked)
        self.bottom_layout.addWidget(self.cancel_btn)
        self.bottom_layout.addWidget(self.ok_btn)
        try:
            self.folder_list.clear()
            self.folder_list.addItem(QListWidgetItem("正在加载文件夹列表..."))
        except Exception:
            pass

        try:
            self._update_post_action_ui()
        except Exception:
            pass
        try:
            self._update_finish_action_ui()
        except Exception:
            pass

    def _get_post_action(self) -> str:
        try:
            v = self.post_action_combo.currentData()
            if isinstance(v, str) and v:
                return str(v)
        except Exception:
            pass
        try:
            t = str(self.post_action_combo.currentText() or "")
        except Exception:
            t = ""
        t = t.strip()
        if t == "复制到目标目录":
            return "copy"
        if t == "剪切到目标目录":
            return "move"
        if t == "按虚拟文件分类复制到目标目录":
            return "copy_by_status"
        if t == "按虚拟文件分类剪切到目标目录":
            return "move_by_status"
        if t == "按虚拟文件分类复制到原目录":
            return "copy_by_status_to_source"
        if t == "按虚拟文件分类剪切到原目录":
            return "move_by_status_to_source"
        return "none"

    def _update_post_action_ui(self):
        action = self._get_post_action()
        enabled = action in ("copy", "move", "copy_by_status", "move_by_status")
        try:
            self.post_dir_choose_btn.setEnabled(bool(enabled))
            self.post_dir_clear_btn.setEnabled(bool(enabled))
            self.post_dir_label.setEnabled(bool(enabled))
        except Exception:
            pass

    def _get_finish_action(self) -> str:
        try:
            v = self.finish_action_combo.currentData()
            if isinstance(v, str) and v:
                return str(v)
        except Exception:
            pass
        return "none"

    def _update_finish_action_ui(self):
        enabled = self._get_finish_action() == "run_script"
        try:
            self.finish_script_choose_btn.setEnabled(bool(enabled))
            self.finish_script_clear_btn.setEnabled(bool(enabled))
            self.finish_script_label.setEnabled(bool(enabled))
        except Exception:
            pass

    def _choose_finish_script(self):
        try:
            current = str(self.finish_script_label.text() or "").strip()
        except Exception:
            current = ""
        try:
            path, _ = QFileDialog.getOpenFileName(self, "选择脚本", current or os.getcwd(), "Python 脚本 (*.py)")
        except Exception:
            path = ""
        path = str(path or "").strip()
        if not path:
            return
        try:
            self.finish_script_label.setText(path)
            self.finish_script_label.setToolTip(path)
        except Exception:
            pass
        try:
            self._set_setting("focus_detect/finish_script", path)
        except Exception:
            pass

    def _clear_finish_script(self):
        try:
            self.finish_script_label.setText("")
            self.finish_script_label.setToolTip("")
        except Exception:
            pass
        try:
            self._set_setting("focus_detect/finish_script", "")
        except Exception:
            pass

    def _choose_post_dir(self):
        try:
            current = str(self.post_dir_label.text() or "").strip()
        except Exception:
            current = ""
        try:
            d = QFileDialog.getExistingDirectory(self, "选择目标目录", current or os.getcwd())
        except Exception:
            d = ""
        d = str(d or "").strip()
        if not d:
            return
        try:
            self.post_dir_label.setText(d)
            self.post_dir_label.setToolTip(d)
        except Exception:
            pass

    def _clear_post_dir(self):
        try:
            self.post_dir_label.setText("")
            self.post_dir_label.setToolTip("")
        except Exception:
            pass

    def _rebuild_folder_items(self):
        prev_states = {}
        try:
            for i in range(self.folder_list.count()):
                it = self.folder_list.item(i)
                if not it:
                    continue
                p = str(it.data(Qt.ItemDataRole.UserRole) or "")
                if p:
                    prev_states[p] = it.checkState()
        except Exception:
            prev_states = {}

        try:
            self.folder_list.blockSignals(True)
        except Exception:
            pass
        self.folder_list.clear()
        for p in (self._folders or []):
            name = os.path.basename(p) or p
            cnt = int(self._folder_image_counts.get(p) or 0)
            text = f"{name}  ({cnt})" if cnt > 0 else name
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if p in prev_states:
                it.setCheckState(prev_states[p])
            elif bool(getattr(self, "_force_select_all_once", False)):
                it.setCheckState(Qt.CheckState.Checked)
            elif bool(getattr(self, "_force_select_none_once", False)):
                it.setCheckState(Qt.CheckState.Unchecked)
            elif bool(getattr(self, "_override_saved_folder_selection", False)) and getattr(self, "_default_folder_check_state", None) is not None:
                it.setCheckState(self._default_folder_check_state)
            elif self._saved_selected_folders:
                it.setCheckState(Qt.CheckState.Checked if p in self._saved_selected_folders else Qt.CheckState.Unchecked)
            elif getattr(self, "_default_folder_check_state", None) is not None:
                it.setCheckState(self._default_folder_check_state)
            else:
                it.setCheckState(Qt.CheckState.Checked)
            self.folder_list.addItem(it)
        try:
            self._apply_folder_filter()
        except Exception:
            pass
        try:
            self.folder_list.blockSignals(False)
        except Exception:
            pass
        try:
            self._force_select_all_once = False
        except Exception:
            pass
        try:
            self._force_select_none_once = False
        except Exception:
            pass
        self._update_folder_selection_label()

    def _start_folder_build(self):
        try:
            if self._folder_build_timer is not None:
                try:
                    self._folder_build_timer.stop()
                except Exception:
                    pass
                try:
                    self._folder_build_timer.timeout.disconnect()
                except Exception:
                    pass
                try:
                    self._folder_build_timer.deleteLater()
                except Exception:
                    pass
                self._folder_build_timer = None
        except Exception:
            self._folder_build_timer = None
        try:
            self._folders = list(self._dedup_folders_with_counts(self._folders, self._folder_image_counts)[0] or [])
        except Exception:
            pass
        prev_states = {}
        try:
            for i in range(self.folder_list.count()):
                it = self.folder_list.item(i)
                if not it:
                    continue
                p = str(it.data(Qt.ItemDataRole.UserRole) or "")
                if p:
                    prev_states[p] = it.checkState()
        except Exception:
            prev_states = {}
        self._folder_prev_states = prev_states
        self._folder_build_index = 0
        try:
            self.folder_list.blockSignals(True)
        except Exception:
            pass
        try:
            self.folder_list.clear()
        except Exception:
            pass
        try:
            self._folder_build_token = int(getattr(self, "_folder_build_token", 0) or 0) + 1
        except Exception:
            self._folder_build_token = 1
        self._folder_build_timer = QTimer(self)
        try:
            self._folder_build_timer.setProperty("_token", int(self._folder_build_token))
        except Exception:
            pass
        self._folder_build_timer.setInterval(0)
        self._folder_build_timer.timeout.connect(self._build_folder_chunk)
        self._folder_build_timer.start()

    def _build_folder_chunk(self):
        try:
            if self._folder_build_timer is None:
                return
            tok = int(self._folder_build_timer.property("_token") or 0)
            if tok != int(getattr(self, "_folder_build_token", 0) or 0):
                try:
                    self._folder_build_timer.stop()
                except Exception:
                    pass
                return
        except Exception:
            pass
        chunk = 200
        start = int(getattr(self, "_folder_build_index", 0) or 0)
        folders = list(self._folders or [])
        if start >= len(folders):
            try:
                if self._folder_build_timer is not None:
                    self._folder_build_timer.stop()
            except Exception:
                pass
            self._folder_build_timer = None
            try:
                self.folder_list.blockSignals(False)
            except Exception:
                pass
            try:
                self._force_select_all_once = False
            except Exception:
                pass
            try:
                self._force_select_none_once = False
            except Exception:
                pass
            self._update_folder_selection_label()
            self._update_ok_enabled()
            return
        end = min(len(folders), start + chunk)
        seen = set()
        try:
            for i in range(self.folder_list.count()):
                it = self.folder_list.item(i)
                if not it:
                    continue
                pp = str(it.data(Qt.ItemDataRole.UserRole) or "")
                if pp:
                    seen.add(self._normalize_folder_key(pp))
        except Exception:
            seen = set()
        for p in folders[start:end]:
            k = ""
            try:
                k = self._normalize_folder_key(p)
            except Exception:
                k = str(p)
            if k and k in seen:
                continue
            if k:
                seen.add(k)
            try:
                name = os.path.basename(p) or p
                cnt = int(self._folder_image_counts.get(p) or 0)
                text = f"{name}  ({cnt})" if cnt > 0 else name
                it = QListWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setToolTip(p)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                if p in (self._folder_prev_states or {}):
                    it.setCheckState(self._folder_prev_states[p])
                elif bool(getattr(self, "_force_select_all_once", False)):
                    it.setCheckState(Qt.CheckState.Checked)
                elif bool(getattr(self, "_force_select_none_once", False)):
                    it.setCheckState(Qt.CheckState.Unchecked)
                elif bool(getattr(self, "_override_saved_folder_selection", False)) and getattr(self, "_default_folder_check_state", None) is not None:
                    it.setCheckState(self._default_folder_check_state)
                elif self._saved_selected_folders:
                    it.setCheckState(Qt.CheckState.Checked if p in self._saved_selected_folders else Qt.CheckState.Unchecked)
                elif getattr(self, "_default_folder_check_state", None) is not None:
                    it.setCheckState(self._default_folder_check_state)
                else:
                    it.setCheckState(Qt.CheckState.Checked)
                self.folder_list.addItem(it)
            except Exception:
                continue
        self._folder_build_index = end
        try:
            self._apply_folder_filter()
        except Exception:
            pass

    def _update_folder_selection_label(self):
        folders = self._collect_selected_folders()
        folder_count = len(folders)
        img_count = 0
        for f in folders:
            try:
                img_count += int(self._folder_image_counts.get(f) or 0)
            except Exception:
                pass
        if folder_count <= 0:
            self.folder_selection_label.setText("已选择 0 个文件夹，0 张图片")
        else:
            self.folder_selection_label.setText(f"已选择 {folder_count} 个文件夹，{img_count} 张图片")
        self._update_ok_enabled()
        self._refresh_visible_extensions()

    def _update_ok_enabled(self):
        try:
            has_items = self.folder_list.count() > 0
        except Exception:
            has_items = False
        try:
            has_selected = len(self._collect_selected_folders()) > 0
        except Exception:
            has_selected = False
        try:
            self.ok_btn.setEnabled(bool(has_items and has_selected))
        except Exception:
            pass

    def set_scanning(self, scanning: bool, text: str | None = None):
        self._scanning = bool(scanning)
        if self._scanning:
            self.scan_status_label.setText(str(text or "正在统计文件夹..."))
        else:
            self.scan_status_label.setText(str(text or ""))
        self._update_ok_enabled()

    def set_folders_and_counts(self, folders: list[str], folder_image_counts: dict[str, int] | None = None):
        try:
            deduped_folders, deduped_counts = self._dedup_folders_with_counts(folders, folder_image_counts)
        except Exception:
            deduped_folders, deduped_counts = [str(p) for p in (folders or []) if p], dict(folder_image_counts or {})
        self._folders = list(deduped_folders or [])
        self._folder_image_counts = dict(deduped_counts or {})
        try:
            self._start_folder_build()
        except Exception:
            self._rebuild_folder_items()

    def set_folder_time_ranges(self, folder_time_ranges: dict[str, tuple[float | None, float | None]] | None = None):
        self._folder_time_ranges = dict(folder_time_ranges or {})
        try:
            self._reapply_folder_sort()
        except Exception:
            pass

    def _reapply_folder_sort(self):
        try:
            key = str(self.folder_sort_key_combo.currentData() or "max")
        except Exception:
            key = "max"
        try:
            order = str(self.folder_sort_order_combo.currentData() or "desc")
        except Exception:
            order = "desc"
        reverse = str(order).lower() != "asc"

        def _time_key(p: str, use_max: bool):
            rng = self._folder_time_ranges.get(str(p) or "")
            if not rng:
                return 0.0
            t0, t1 = rng
            v = t1 if use_max else t0
            try:
                return float(v or 0.0)
            except Exception:
                return 0.0

        def _sort_key(p: str):
            ps = str(p or "")
            if key == "name":
                return (os.path.basename(ps).lower(), ps.lower())
            if key == "min":
                return (_time_key(ps, use_max=False), os.path.basename(ps).lower(), ps.lower())
            return (_time_key(ps, use_max=True), os.path.basename(ps).lower(), ps.lower())

        try:
            self._folders = sorted(list(self._folders or []), key=_sort_key, reverse=bool(reverse))
        except Exception:
            pass
        try:
            self._rebuild_folder_items()
        except Exception:
            pass

    def _apply_folder_filter(self):
        try:
            q = str(self.folder_search_input.text() or "").strip().lower()
        except Exception:
            q = ""

        def _fuzzy_match(needle: str, haystack: str) -> bool:
            n = str(needle or "").strip().lower()
            h = str(haystack or "").lower()
            if not n:
                return True
            if n in h:
                return True
            i = 0
            for ch in n:
                i = h.find(ch, i)
                if i < 0:
                    return False
                i += 1
            return True

        terms = [t for t in str(q or "").split() if t]
        for i in range(self.folder_list.count()):
            it = self.folder_list.item(i)
            if not it:
                continue
            if not q:
                it.setHidden(False)
                continue
            try:
                p = str(it.data(Qt.ItemDataRole.UserRole) or "")
            except Exception:
                p = ""
            try:
                t = str(it.text() or "")
            except Exception:
                t = ""
            hay = (t + "\n" + p).lower()
            ok = True
            for term in (terms or [q]):
                if not _fuzzy_match(term, hay):
                    ok = False
                    break
            it.setHidden(not bool(ok))

    def _select_all_folders(self):
        try:
            self._default_folder_check_state = Qt.CheckState.Checked
            self._override_saved_folder_selection = True
        except Exception:
            pass
        for i in range(self.folder_list.count()):
            it = self.folder_list.item(i)
            if it:
                it.setCheckState(Qt.CheckState.Checked)

    def _select_none_folders(self):
        try:
            self._default_folder_check_state = Qt.CheckState.Unchecked
            self._override_saved_folder_selection = True
        except Exception:
            pass
        for i in range(self.folder_list.count()):
            it = self.folder_list.item(i)
            if it:
                it.setCheckState(Qt.CheckState.Unchecked)

    def _load_settings(self):
        self._loading_settings = True
        try:
            selected = self.settings_manager.get("focus_detect/folders", []) or []
            selected = [str(x) for x in selected if x]
        except Exception:
            selected = []
        self._saved_selected_folders = selected

        try:
            for k, it in (self._option_items or {}).items():
                default_val = False if str(k) in ("append_detect", "no_db_write") else True
                val = bool(self.settings_manager.get(f"focus_detect/{k}", default_val))
                try:
                    it.setChecked(bool(val))
                except Exception:
                    pass
        except Exception:
            pass

        model = str(self.settings_manager.get("focus_detect/model", "x") or "x").lower()
        if model in ["n", "s", "m", "l", "x"]:
            self.model_combo.setCurrentText(model)
        try:
            self.initial_conf_spin.setValue(float(self.settings_manager.get("focus_detect/initial_conf", 0.15) or 0.15))
        except Exception:
            try:
                self.initial_conf_spin.setValue(0.15)
            except Exception:
                pass
        self.target_size_spin.setValue(int(self.settings_manager.get("focus_detect/target_size", 640)))
        self.burst_min_count_spin.setValue(int(self.settings_manager.get("focus_detect/burst_min_count", 10)))
        self.burst_fps_spin.setValue(int(self.settings_manager.get("focus_detect/burst_fps", 20)))
        # 计算默认检测线程数（全部CPU核心数减4）
        try:
            cpu_count = int(os.cpu_count() or 4)
        except Exception:
            cpu_count = 4
        cpu_count = max(4, cpu_count)
        default_threads = max(1, cpu_count - 4)
        # 检测线程数设置（兼容旧版reserve_cpu设置）
        threads_value = int(self.settings_manager.get("focus_detect/detect_threads", 0))
        if threads_value <= 0:
            # 尝试读取旧版设置
            old_reserve = int(self.settings_manager.get("focus_detect/reserve_cpu", 0))
            if old_reserve > 0:
                threads_value = max(1, cpu_count - old_reserve)
            else:
                threads_value = default_threads
        self.detect_threads_spin.setValue(threads_value)
        try:
            action = str(self.settings_manager.get("focus_detect/post_action", "none") or "none").strip().lower()
        except Exception:
            action = "none"
        if action not in ("none", "copy", "move", "copy_by_status", "move_by_status", "copy_by_status_to_source", "move_by_status_to_source"):
            action = "none"
        try:
            for i in range(self.post_action_combo.count()):
                if str(self.post_action_combo.itemData(i) or "") == action:
                    self.post_action_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass
        try:
            fa = str(self.settings_manager.get("focus_detect/finish_action", "none") or "none").strip().lower()
        except Exception:
            fa = "none"
        if fa not in ("none", "quit_app", "shutdown_pc", "run_script"):
            fa = "none"
        try:
            if hasattr(self, "finish_action_combo"):
                for i in range(self.finish_action_combo.count()):
                    if str(self.finish_action_combo.itemData(i) or "") == fa:
                        self.finish_action_combo.setCurrentIndex(i)
                        break
        except Exception:
            pass
        try:
            finish_script = str(self.settings_manager.get("focus_detect/finish_script", "") or "").strip()
        except Exception:
            finish_script = ""
        try:
            if hasattr(self, "finish_script_label"):
                self.finish_script_label.setText(finish_script)
                self.finish_script_label.setToolTip(finish_script)
        except Exception:
            pass
        try:
            post_dir = str(self.settings_manager.get("focus_detect/post_dir", "") or "").strip()
        except Exception:
            post_dir = ""
        try:
            self.post_dir_label.setText(post_dir)
            self.post_dir_label.setToolTip(post_dir)
        except Exception:
            pass
        try:
            self._update_post_action_ui()
        except Exception:
            pass
        try:
            self._update_finish_action_ui()
        except Exception:
            pass
        try:
            self._init_gpu_controls()
        except Exception:
            pass
        self._loading_settings = False

    def _calc_detect_threads(self, use_gpu: bool = False, task_count: int = 0) -> int:
        """计算推荐的检测线程数
        
        参数:
            use_gpu: 是否使用GPU
            task_count: 任务数量
            
        返回:
            推荐的检测线程数
        """
        try:
            cpu_count = int(os.cpu_count() or 4)
        except Exception:
            cpu_count = 4
        cpu_count = max(4, cpu_count)
        
        # 根据任务数量计算推荐的线程数
        # 线性增长模式：GPU模式每8个文件1个线程，CPU模式每4个文件1个线程
        if task_count > 0:
            if use_gpu:
                # GPU模式：每8个文件增加1个线程
                recommended = max(1, (task_count + 7) // 8)
                # GPU模式上限可以更高
                recommended = min(recommended, 16)
            else:
                # CPU模式：每4个文件增加1个线程
                recommended = max(1, (task_count + 3) // 4)
                # CPU模式上限为CPU核心数-4
                recommended = min(recommended, max(1, cpu_count - 4))
            
            # 确保不超过CPU核心数
            return min(recommended, cpu_count)
        
        # 没有任务数信息时，使用默认计算
        if not use_gpu:
            # 纯CPU模式：使用全部-4
            threads = max(1, cpu_count - 4)
        else:
            # GPU模式：使用大部分核心
            threads = max(1, cpu_count - 2)
        
        return min(threads, cpu_count)

    def _on_use_gpu_toggled(self, checked: bool):
        try:
            enabled = bool(checked)
            
            # 根据GPU开关状态更新推荐的检测线程数
            if hasattr(self, "detect_threads_spin") and self.detect_threads_spin:
                # 获取当前选中的文件总数
                task_count = self._get_selected_image_count()
                recommended = self._calc_detect_threads(use_gpu=enabled, task_count=task_count)
                self.detect_threads_spin.setValue(recommended)
                # 更新标签显示
                mode = "GPU" if enabled else "CPU"
                self.detect_threads_label.setText(f"{mode}模式推荐 ({task_count}个文件)")
        except Exception:
            pass

    def _update_detect_threads(self):
        """根据当前选中的文件数量更新检测线程数"""
        try:
            if not hasattr(self, "detect_threads_spin") or not self.detect_threads_spin:
                return
            
            # 获取当前是否使用GPU
            use_gpu = False
            if hasattr(self, "_option_items") and self._option_items:
                use_gpu_cb = self._option_items.get("use_gpu")
                if use_gpu_cb and use_gpu_cb.isChecked():
                    use_gpu = True
            
            # 获取选中的文件数量
            task_count = self._get_selected_image_count()
            
            # 计算推荐的线程数
            recommended = self._calc_detect_threads(use_gpu=use_gpu, task_count=task_count)
            
            # 更新控件值和标签
            self.detect_threads_spin.setValue(recommended)
            mode = "GPU" if use_gpu else "CPU"
            self.detect_threads_label.setText(f"{mode}模式推荐 ({task_count}个文件)")
        except Exception:
            pass

    def _get_selected_image_count(self) -> int:
        """获取当前选中的文件总数"""
        try:
            selected_folders = self._collect_selected_folders()
            if not selected_folders:
                return 0
            total = 0
            for folder in selected_folders:
                count = int(self._folder_image_counts.get(folder, 0) or 0)
                if count > 0:
                    total += count
            return total
        except Exception:
            return 0

    def _init_gpu_controls(self):
        # 先设置为默认状态（CPU模式），避免卡顿
        self._cuda_checking = True
        try:
            use_gpu_cb = (self._option_items or {}).get("use_gpu")
            if use_gpu_cb is not None:
                # 暂时禁用GPU选项，等待检测完成
                use_gpu_cb.setEnabled(False)
                use_gpu_cb.setToolTip("正在检测CUDA环境...")
        except Exception:
            pass
        try:
            self.gpu_batch_size_spin.setEnabled(False)
            self.gpu_recommend_label.setText("检测中...")
        except Exception:
            pass
        
        # 在后台线程中执行CUDA检测
        from threading import Thread
        def _check_cuda_async():
            cuda_available = False
            try:
                from utils.system.gpu_utils import is_torch_cuda_usable
                cuda_available = bool(is_torch_cuda_usable())
            except Exception:
                cuda_available = False
            
            # 在主线程中更新UI
            try:
                from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_on_cuda_check_finished",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(bool, cuda_available)
                )
            except Exception:
                # 如果invokeMethod失败，直接调用
                try:
                    self._on_cuda_check_finished(cuda_available)
                except Exception:
                    pass
        
        Thread(target=_check_cuda_async, daemon=True, name="CUDACheck").start()
    
    def _on_cuda_check_finished(self, cuda_available: bool):
        """CUDA检测完成后的回调"""
        self._cuda_checking = False
        try:
            from utils.log_manager import LogManager
            LogManager.instance().debug(f"[FocusDetectDialog] _on_cuda_check_finished cuda_available={cuda_available}")
        except Exception:
            pass
        
        if not cuda_available:
            try:
                use_gpu_cb = (self._option_items or {}).get("use_gpu")
                if use_gpu_cb is not None:
                    use_gpu_cb.setChecked(False)
                    use_gpu_cb.setEnabled(False)
                    use_gpu_cb.setToolTip("未检测到可用的CUDA环境")
            except Exception:
                pass
        else:
            try:
                use_gpu_cb = (self._option_items or {}).get("use_gpu")
                if use_gpu_cb is not None:
                    use_gpu_cb.setEnabled(True)
                    use_gpu_cb.setToolTip("")
            except Exception:
                pass
            self._on_use_gpu_toggled(bool((self._option_items or {}).get("use_gpu") and (self._option_items or {}).get("use_gpu").isChecked()))

    def _queue_settings_sync(self):
        if getattr(self, "_loading_settings", False):
            return
        try:
            if self._settings_sync_timer is None:
                self._settings_sync_timer = QTimer(self)
                self._settings_sync_timer.setSingleShot(True)
                self._settings_sync_timer.timeout.connect(self._sync_settings_now)
            self._settings_sync_timer.start(250)
        except Exception:
            pass

    def _sync_settings_now(self):
        try:
            self.settings_manager.sync()
        except Exception:
            pass

    def _set_setting(self, key: str, value):
        if getattr(self, "_loading_settings", False):
            return
        try:
            self.settings_manager.set(str(key), value)
        except Exception:
            return
        self._queue_settings_sync()

    def _wire_settings_persistence(self):
        for k, cb in (self._option_items or {}).items():
            if not cb:
                continue
            cb.toggled.connect(lambda checked, kk=str(k): self._set_setting(f"focus_detect/{kk}", bool(checked)))
        try:
            if hasattr(self, "exif_write_mode_combo") and self.exif_write_mode_combo is not None:
                self.exif_write_mode_combo.currentIndexChanged.connect(lambda _i=None: self._persist_exif_write_mode())
        except Exception:
            pass
        try:
            self.model_combo.currentTextChanged.connect(lambda t: self._set_setting("focus_detect/model", str(t or "x").lower()))
        except Exception:
            pass
        try:
            self.initial_conf_spin.valueChanged.connect(lambda v: self._set_setting("focus_detect/initial_conf", float(v)))
        except Exception:
            pass
        try:
            self.target_size_spin.valueChanged.connect(lambda v: self._set_setting("focus_detect/target_size", int(v)))
        except Exception:
            pass
        try:
            self.burst_min_count_spin.valueChanged.connect(lambda v: self._set_setting("focus_detect/burst_min_count", int(v)))
        except Exception:
            pass
        try:
            self.burst_fps_spin.valueChanged.connect(lambda v: self._set_setting("focus_detect/burst_fps", int(v)))
        except Exception:
            pass
        try:
            self.detect_threads_spin.valueChanged.connect(lambda v: self._set_setting("focus_detect/detect_threads", int(v)))
        except Exception:
            pass
        try:
            use_gpu_cb = (self._option_items or {}).get("use_gpu")
            if use_gpu_cb is not None:
                use_gpu_cb.toggled.connect(self._on_use_gpu_toggled)
        except Exception:
            pass
        try:
            self.post_action_combo.currentIndexChanged.connect(lambda _: self._set_setting("focus_detect/post_action", self._get_post_action()))
        except Exception:
            pass
        try:
            if hasattr(self, "finish_action_combo"):
                self.finish_action_combo.currentIndexChanged.connect(
                    lambda _: (self._set_setting("focus_detect/finish_action", str(self.finish_action_combo.currentData() or "none")), self._update_finish_action_ui())
                )
        except Exception:
            pass

    def _persist_exif_write_mode(self):
        try:
            mode = str(self.exif_write_mode_combo.currentData() or "file").strip().lower()
        except Exception:
            mode = "file"
        if mode not in ("file", "xmp", "none"):
            mode = "file"
        try:
            self._set_setting("exif/write_mode", mode)
            self._set_setting("exif/disable_write", mode == "none")
        except Exception:
            pass

    def set_folder_extensions_map(self, mapping: dict[str, list[str]]):
        """设置文件夹到扩展名的映射并更新UI"""
        try:
            self._folder_extensions_map = {str(k): set(v) for k, v in mapping.items()}
            self._refresh_visible_extensions()
        except Exception:
            pass

    def _refresh_visible_extensions(self):
        """根据当前选中的文件夹刷新可见的扩展名"""
        try:
            selected_folders = self._collect_selected_folders()
            if not self._folder_extensions_map:
                return

            visible_exts = set()
            for f in selected_folders:
                if f in self._folder_extensions_map:
                    visible_exts.update(self._folder_extensions_map[f])
            
            self._render_extension_checkboxes(list(visible_exts))
        except Exception:
            pass

    def _render_extension_checkboxes(self, extensions: list[str]):
        """创建扩展名复选框"""
        try:
            # 保存当前所有checkbox的状态到 _unchecked_extensions (如果尚未保存)
            # 但实际上我们在 toggled 时实时更新 _unchecked_extensions，所以这里只需读取
            
            # 清除旧控件前，不需要再次保存，因为 _unchecked_extensions 是 source of truth
            
            # 移除旧控件
            while self.file_type_layout.count():
                child = self.file_type_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.extension_checkboxes.clear()
            
            exts = sorted(list(set(extensions or [])))
            if not exts:
                self.file_type_group.setVisible(False)
                return
                
            self.file_type_group.setVisible(True)
            for idx, ext in enumerate(exts):
                cb = QCheckBox(ext.upper())
                # 如果该扩展名在 _unchecked_extensions 中，则不勾选；否则默认勾选
                is_checked = ext not in self._unchecked_extensions
                cb.setChecked(is_checked)
                
                # 连接信号：勾选时从 unchecked 移除，取消勾选时加入 unchecked
                cb.toggled.connect(lambda checked, e=ext: self._unchecked_extensions.discard(e) if checked else self._unchecked_extensions.add(e))
                
                self.extension_checkboxes[ext] = cb
                r = idx // 4
                c = idx % 4
                self.file_type_layout.addWidget(cb, r, c)
        except Exception:
            pass

    def set_found_extensions(self, extensions: list[str]):
        """设置发现的文件扩展名并更新UI (兼容旧接口)"""
        self._render_extension_checkboxes(extensions)

    def _collect_selected_extensions(self) -> list[str]:
        out = []
        if not self.extension_checkboxes:
            return []
        for ext, cb in self.extension_checkboxes.items():
            if cb.isChecked():
                out.append(ext)
        return out

    def _collect_selected_folders(self) -> list[str]:
        out: list[str] = []
        for i in range(self.folder_list.count()):
            it = self.folder_list.item(i)
            if not it:
                continue
            if it.checkState() != Qt.CheckState.Checked:
                continue
            p = str(it.data(Qt.ItemDataRole.UserRole) or "")
            if p:
                out.append(p)
        return out

    def _on_ok_clicked(self):
        self.selected_folders = self._collect_selected_folders()
        self.options = {
            "enable_burst": self._option_checked("enable_burst"),
            "enable_similarity": self._option_checked("enable_similarity"),
            "use_multiprocess": self._option_checked("use_multiprocess"),
            "use_gpu": self._option_checked("use_gpu"),
            "multi_check": self._option_checked("multi_check"),
            "exp_frame_check": self._option_checked("exp_frame_check"),
            "enable_eye_detect": self._option_checked("enable_eye_detect"),
            "enable_af_point_detect": self._option_checked("enable_af_point_detect"),
            "append_detect": self._option_checked("append_detect"),
            "no_db_write": self._option_checked("no_db_write"),
            "model": str(self.model_combo.currentText() or "x").lower(),
            "initial_conf": float(self.initial_conf_spin.value()),
            "target_size": int(self.target_size_spin.value()),
            "burst_min_count": int(self.burst_min_count_spin.value()),
            "burst_fps": int(self.burst_fps_spin.value()),
            "detect_threads": int(self.detect_threads_spin.value()),
            "reserve_cpu": max(1, int(os.cpu_count() or 4) - int(self.detect_threads_spin.value())),  # 兼容旧版
            "post_action": self._get_post_action(),
            "post_dir": str(self.post_dir_label.text() or "").strip(),
            "finish_action": str(self.finish_action_combo.currentData() if hasattr(self, "finish_action_combo") else "none" or "none"),
            "finish_script": str(self.finish_script_label.text() if hasattr(self, "finish_script_label") else "" or "").strip(),
            "file_extensions": self._collect_selected_extensions(),
        }

        try:
            self.settings_manager.set("focus_detect/folders", self.selected_folders)
            for k, v in self.options.items():
                self.settings_manager.set(f"focus_detect/{k}", v)
            self.settings_manager.sync()
        except Exception:
            pass

        self.accept()

    def _option_checked(self, key: str) -> bool:
        try:
            it = (self._option_items or {}).get(str(key))
            if it is None:
                default_val = False if str(key) in ("append_detect", "no_db_write") else True
                return bool(self.settings_manager.get(f"focus_detect/{str(key)}", default_val))
            return bool(it.isChecked())
        except Exception:
            default_val = False if str(key) in ("append_detect", "no_db_write") else True
            try:
                return bool(self.settings_manager.get(f"focus_detect/{str(key)}", default_val))
            except Exception:
                return bool(default_val)
