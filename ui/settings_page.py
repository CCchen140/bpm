import os
import json
import sys
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QFileDialog, QGroupBox, 
                             QFormLayout, QMessageBox, QSpinBox, QCheckBox,
                             QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
                             QComboBox, QScrollArea, QApplication)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QProcess, QObject, QEvent, QUrl
from PyQt6.QtGui import QColor, QPalette
from utils.setting.settings_manager import SettingsManager
from utils.sql.data_base import get_default_db_path
from ui.utils.notification_manager import NotificationManager
from cache.cache_manager import ImageCacheManager
from ui.widgets.loading_overlay import LoadingOverlay
from utils.worker.scan_worker import ScanWorker
from ui.utils.shortcut_manager import ShortcutManager
from ui.utils.flow_layout import FlowLayout
from ui.widgets.shortcut_recorder import ShortcutRecorder
from ui.utils.color_manager import ColorManager
from ui.widgets.themed_color_dialog import ThemedColorDialog
from ui.utils.icon_loader import qta
from utils.log_manager import LogManager
from ui.update_settings_page import UpdateSettingsPage

class ModernSpinBox(QWidget):
    """自定义现代风格 SpinBox，两侧为加减按钮，中间为数值"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 整体容器样式
        self.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                color: #555;
                font-size: 16px;
                font-weight: bold;
                min-width: 32px;
                max-width: 32px;
                min-height: 36px;
            }
            QPushButton:hover {
                background-color: #f5f5f5;
                color: #2196f3;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
            /* 左边按钮：右边框 */
            QPushButton#minus_btn {
                border-right: 1px solid #d0d0d0;
                border-top-left-radius: 4px;
                border-bottom-left-radius: 4px;
            }
            /* 右边按钮：左边框 */
            QPushButton#plus_btn {
                border-left: 1px solid #d0d0d0;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            /* 中间 SpinBox */
            QSpinBox {
                border: none;
                background: transparent;
                min-height: 36px;
                padding: 0 4px;
                font-size: 14px;
                selection-background-color: #2196f3;
            }
        """)
        
        # 减号按钮
        self.minus_btn = QPushButton("-")
        self.minus_btn.setObjectName("minus_btn")
        self.minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.minus_btn.clicked.connect(self.step_down)
        layout.addWidget(self.minus_btn)
        
        # 中间 SpinBox (隐藏自带按钮)
        self.spinbox = QSpinBox()
        self.spinbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinbox.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons) # 隐藏自带按钮
        self.spinbox.setFrame(False) # 无边框，由外层容器提供
        layout.addWidget(self.spinbox, 1) # 占据剩余空间
        
        # 加载号按钮
        self.plus_btn = QPushButton("+")
        self.plus_btn.setObjectName("plus_btn")
        self.plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plus_btn.clicked.connect(self.step_up)
        layout.addWidget(self.plus_btn)
        
    def step_up(self):
        self.spinbox.stepUp()
        
    def step_down(self):
        self.spinbox.stepDown()
        
    # 代理 QSpinBox 的常用方法
    def value(self):
        return self.spinbox.value()
        
    def setValue(self, val):
        self.spinbox.setValue(val)
        
    def setRange(self, min_val, max_val):
        self.spinbox.setRange(min_val, max_val)
        
    def setSingleStep(self, step):
        self.spinbox.setSingleStep(step)
        
    def setSuffix(self, suffix):
        self.spinbox.setSuffix(suffix)


class _WheelAdjustFilter(QObject):
    def eventFilter(self, obj, event):
        try:
            if event.type() != QEvent.Type.Wheel:
                return False
        except Exception:
            return False
        try:
            if not isinstance(obj, (QComboBox, QSpinBox, QLineEdit)):
                return False
        except Exception:
            return False

        scroll_area = None
        try:
            w = obj
            while w is not None:
                if isinstance(w, QScrollArea):
                    scroll_area = w
                    break
                w = w.parent()
        except Exception:
            scroll_area = None
        try:
            if scroll_area is not None:
                QApplication.sendEvent(scroll_area.viewport(), event)
        except Exception:
            pass
        try:
            event.accept()
        except Exception:
            pass
        return True
        
    def setMaximumWidth(self, w):
        super().setMaximumWidth(w)

class SettingsPage(QWidget):
    library_thumbnail_setting_changed = pyqtSignal()
    import_thumbnail_setting_changed = pyqtSignal()
    thumbnail_ui_perf_setting_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings_manager = SettingsManager()
        self._settings_sync_timer = QTimer(self)
        self._settings_sync_timer.setSingleShot(True)
        self._settings_sync_timer.setInterval(350)
        self._settings_sync_timer.timeout.connect(self._sync_settings_now)
        self._font_apply_timer = QTimer(self)
        self._font_apply_timer.setSingleShot(True)
        self._font_apply_timer.setInterval(350)
        self._font_apply_timer.timeout.connect(self._apply_pending_font_choice)
        self._pending_font_choice = None
        self._rebuild_thumb_worker = None
        self._rebuild_thumb_overlay = None
        self.shortcut_recorders = {}
        self.shortcut_reset_buttons = []
        self.init_ui()
        self._wheel_adjust_filter = _WheelAdjustFilter(self)
        try:
            for w in self.findChildren(QComboBox):
                w.installEventFilter(self._wheel_adjust_filter)
        except Exception:
            pass
        try:
            for w in self.findChildren(QSpinBox):
                w.installEventFilter(self._wheel_adjust_filter)
        except Exception:
            pass
        try:
            for w in self.findChildren(QLineEdit):
                w.installEventFilter(self._wheel_adjust_filter)
        except Exception:
            pass
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()
        
        # 监听快捷键变更，更新UI
        ShortcutManager.instance().shortcuts_changed.connect(self.update_shortcut_inputs)

        # 应用保存的字体
        saved_font = self.settings_manager.get("general/font_name", "中等")
        if saved_font:
            self._apply_font_to_application(saved_font)

    def _queue_settings_sync(self):
        try:
            if self._settings_sync_timer.isActive():
                self._settings_sync_timer.stop()
            self._settings_sync_timer.start()
        except Exception:
            pass

    def _sync_settings_now(self):
        try:
            self.settings_manager.sync()
        except Exception:
            pass

    def init_ui(self):
        cm = ColorManager.instance()
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"background-color: {cm.get('theme.background.primary')};")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._main_container = QWidget(self)
        self._main_container.setObjectName("settingsMainContainer")
        root_layout.addWidget(self._main_container)

        main_layout = QVBoxLayout(self._main_container)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(15)

        # 标题
        self._title_label = QLabel("设置")
        self._title_label.setStyleSheet(f"color: {cm.get('theme.text.dark')};")
        main_layout.addWidget(self._title_label)

        # Tabs
        self.tabs = QTabWidget()
        
        # Tab 1: General
        self.general_tab = QWidget()
        self.init_general_tab()
        self.tabs.addTab(self.general_tab, "常规设置")
        
        # Tab 2: Performance
        self.perf_tab = QWidget()
        self.init_perf_tab()
        self.tabs.addTab(self.perf_tab, "性能设置")
        
        # Tab 3: Shortcuts
        self.shortcut_tab = QWidget()
        self.init_shortcut_tab()
        self.tabs.addTab(self.shortcut_tab, "快捷键设置")

        # Tab 4: Update Management - 延迟创建
        self.update_tab = None
        self.tabs.addTab(QWidget(), "升级管理")  # 先添加占位页面
        self.tabs.currentChanged.connect(self._on_tab_changed)

        main_layout.addWidget(self.tabs)
        
        # 底部按钮栏
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(15)
        
        # 恢复默认配置按钮（保留根目录和首次运行状态）
        reset_config_btn = QPushButton("恢复默认配置")
        reset_config_btn.setFixedSize(160, 45)
        reset_config_btn.clicked.connect(self.restore_user_settings)
        bottom_layout.addWidget(reset_config_btn)
        self._reset_config_btn = reset_config_btn

        # 恢复初始状态按钮
        reset_all_btn = QPushButton("恢复初始状态")
        reset_all_btn.setFixedSize(160, 45)
        reset_all_btn.clicked.connect(self.restore_defaults)
        bottom_layout.addWidget(reset_all_btn)
        self._reset_all_btn = reset_all_btn
        
        bottom_layout.addStretch()

        # 保存按钮
        save_btn = QPushButton("保存设置")
        save_btn.setFixedSize(140, 45)
        save_btn.clicked.connect(self.save_settings)
        bottom_layout.addWidget(save_btn)
        self._save_btn = save_btn
        
        main_layout.addLayout(bottom_layout)

    def _on_tab_changed(self, index: int):
        """标签页切换事件 - 延迟创建升级管理页面"""
        # 升级管理页面是第4个标签（索引3）
        if index == 3 and self.update_tab is None:
            # 延迟创建升级管理页面
            self.update_tab = UpdateSettingsPage()
            # 替换占位页面
            self.tabs.removeTab(3)
            self.tabs.insertTab(3, self.update_tab, "升级管理")
            self.tabs.setCurrentIndex(3)

    def _change_user_data_path(self):
        from utils.paths import PathManager
        from utils.migration import MigrationManager
        
        current_path = PathManager.instance().get_user_data_path()
        new_path_str = QFileDialog.getExistingDirectory(self, "选择新的数据保存位置", str(current_path))
        
        if not new_path_str:
            return
            
        new_path = Path(new_path_str)
        try:
            if new_path.resolve() == current_path.resolve():
                return
        except Exception:
            pass
            
        reply = QMessageBox.question(self, "确认更改", 
                                     f"即将把数据迁移到:\n{new_path}\n\n这需要移动所有个人配置文件和数据库，并重启应用程序。\n是否继续？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                                     
        if reply == QMessageBox.StandardButton.Yes:
            try:
                MigrationManager().schedule_move(new_path)
                QMessageBox.information(self, "需重启生效", "设置已保存。应用程序将立即重启以完成数据迁移。")
                
                # Restart Application
                QApplication.quit()
                process = QProcess()
                process.setProgram(sys.executable)
                process.setArguments(sys.argv)
                process.startDetached()
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"设置失败: {e}")

    def _on_detail_auto_switch_interval_changed(self, value: int):
        try:
            v = int(value)
        except Exception:
            v = 800
        v = int(max(50, min(5000, v)))
        try:
            self.settings_manager.set("image_detail/auto_switch_interval_ms", v)
        except Exception:
            pass

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        page_bg = cm.get("theme.background.primary")
        text_dark = cm.get("theme.text.dark")
        text_light = cm.get("theme.text.light")
        border = cm.get("popup.border.primary")
        light_bg = cm.get("theme.background.light")
        dark_bg = cm.get("theme.background.dark")
        primary = cm.get("theme.primary")
        # 使用Base64编码的SVG箭头，避免中文路径问题
        from ui.common.icon_utils import get_arrow_down_svg_base64
        arrow_url = get_arrow_down_svg_base64(text_dark)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(page_bg))
        self.setPalette(palette)
        self.setStyleSheet(f"""
            QWidget#settingsMainContainer {{
                background-color: {page_bg};
            }}
            SettingsPage {{
                background-color: {page_bg};
            }}
            QLineEdit {{
                min-height: 36px;
                font-size: 14px;
                padding: 0 8px;
                border: 1px solid {border};
                border-radius: 4px;
                color: {text_dark};
                background-color: {light_bg};
            }}
            QLabel {{
                font-size: 14px;
                color: {text_dark};
                background: transparent;
            }}
            QComboBox {{
                min-height: 36px;
                font-size: 14px;
                padding: 0 8px;
                border: 1px solid {border};
                border-radius: 4px;
                color: {text_dark};
                background-color: {light_bg};
            }}
            QComboBox:hover {{
                border: 1px solid {primary};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({arrow_url});
                width: 12px;
                height: 12px;
                margin-right: 6px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {border};
                background-color: {light_bg};
                selection-background-color: {primary};
                selection-color: {text_light};
                color: {text_dark};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {dark_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {primary};
                color: {text_light};
            }}
            QComboBox QAbstractItemView QScrollBar:vertical {{
                background-color: {light_bg};
                width: 8px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical {{
                background-color: {border};
                min-height: 24px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {{
                background-color: {primary};
            }}
            QComboBox QAbstractItemView QScrollBar::add-line:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QComboBox QAbstractItemView QScrollBar::add-page:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        if hasattr(self, "_title_label") and self._title_label:
            self._title_label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {text_dark}; margin-bottom: 10px;")
        if hasattr(self, "tabs") and self.tabs:
            self.tabs.setStyleSheet(f"""
                QTabWidget::pane {{ border: 1px solid {border}; border-radius: 6px; background: {light_bg}; top: -1px; }}
                QTabBar::tab {{ 
                    height: 40px; 
                    width: 120px; 
                    font-size: 14px; 
                    font-weight: bold;
                    color: {text_dark};
                    background: {dark_bg};
                    border: 1px solid {border};
                    margin-right: 2px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                }}
                QTabBar::tab:selected {{ 
                    background: {light_bg}; 
                    border-bottom-color: {light_bg}; 
                    color: {primary};
                }}
                QTabBar::tab:hover {{
                    background: {light_bg};
                }}
            """)
        if getattr(self, "shortcut_tab", None):
            self.shortcut_tab.setStyleSheet(f"background-color: {page_bg};")
        if getattr(self, "_reset_config_btn", None):
            self._reset_config_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {light_bg};
                    color: {text_dark};
                    border: 1px solid {border};
                    border-radius: 6px;
                    font-size: 15px;
                }}
                QPushButton:hover {{
                    background-color: {dark_bg};
                }}
            """)
        if getattr(self, "_reset_all_btn", None):
            self._reset_all_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {primary};
                    color: {text_light};
                    border: none;
                    border-radius: 6px;
                    font-size: 15px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {dark_bg};
                }}
            """)
        if getattr(self, "_save_btn", None):
            self._save_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {primary};
                    color: {text_light};
                    border: none;
                    border-radius: 6px;
                    font-size: 15px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {dark_bg};
                }}
            """)
        group_style = f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """
        if getattr(self, "_perf_general_group", None):
            self._perf_general_group.setStyleSheet(group_style)
        if getattr(self, "_perf_cache_group", None):
            self._perf_cache_group.setStyleSheet(group_style)
        if getattr(self, "_perf_import_group", None):
            self._perf_import_group.setStyleSheet(group_style)
        if getattr(self, "_perf_scroll_area", None):
            self._perf_scroll_area.setStyleSheet(f"""
                QScrollArea {{
                    border: none;
                    background-color: {page_bg};
                }}
                QScrollArea > QWidget > QWidget {{
                    background-color: {page_bg};
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
            """)
        if getattr(self, "_perf_scroll_content", None):
            self._perf_scroll_content.setStyleSheet(f"background-color: {page_bg};")
        if getattr(self, "_perf_import_tip_label", None):
            tip_text = cm.to_qss_color("theme.text.dark")
            self._perf_import_tip_label.setStyleSheet(f"color: {tip_text}; font-size: 13px; font-style: italic;")
        if getattr(self, "_perf_perf_tip_label", None):
            tip_text = cm.to_qss_color("theme.text.dark")
            self._perf_perf_tip_label.setStyleSheet(f"color: {tip_text}; font-size: 13px; font-style: italic;")
        if getattr(self, "_general_scroll_area", None):
            self._general_scroll_area.setStyleSheet(f"""
                QScrollArea {{
                    border: none;
                    background-color: {page_bg};
                }}
                QScrollArea > QWidget > QWidget {{
                    background-color: {page_bg};
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
            """)
        if getattr(self, "_general_scroll_content", None):
            self._general_scroll_content.setStyleSheet(f"background-color: {page_bg};")
        if any(getattr(self, k, None) is not None for k in ("_general_base_group", "_general_geo_group", "_general_recognizer_group")):
            group_style = f"""
                QGroupBox {{
                    font-size: 16px;
                    font-weight: bold;
                    border: 1px solid {border};
                    border-radius: 6px;
                    margin-top: 12px;
                    padding-top: 20px;
                    color: {text_dark};
                    background-color: transparent;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 0 8px;
                    left: 12px;
                }}
            """
            for g in (getattr(self, "_general_base_group", None), getattr(self, "_general_geo_group", None), getattr(self, "_general_recognizer_group", None), getattr(self, "_general_log_group", None)):
                if g is not None:
                    try:
                        g.setStyleSheet(group_style)
                    except Exception:
                        pass
        if getattr(self, "_general_theme_group", None):
            theme_border = cm.get("settings.shortcut_table.header.border")
            self._general_theme_group.setStyleSheet(f"""
                QGroupBox {{
                    font-size: 16px;
                    font-weight: bold;
                    border: 1px solid {theme_border};
                    border-radius: 6px;
                    margin-top: 12px;
                    padding-top: 20px;
                    color: {text_dark};
                    background-color: transparent;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 0 8px;
                    left: 12px;
                }}
            """)
        if getattr(self, "_perf_clear_cache_btn", None):
            self._perf_clear_cache_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {primary};
                    color: {text_light};
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background-color: {dark_bg};
                }}
            """)
        if getattr(self, "_delete_logs_btn", None):
            self._delete_logs_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {primary};
                    color: {text_light};
                    border: none;
                    border-radius: 4px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    opacity: 0.8;
                }}
            """)
        self._apply_shortcut_table_styles()
        for btn in getattr(self, "shortcut_reset_buttons", []):
            self._apply_shortcut_reset_button_style(btn)
        checkbox_style = f"""
            QCheckBox {{
                color: {text_dark};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {border};
                border-radius: 3px;
                background-color: {light_bg};
            }}
            QCheckBox::indicator:checked {{
                background-color: {primary};
                border: 1px solid {primary};
            }}
        """
        for cb in getattr(self, "_perf_checkboxes", []):
            cb.setStyleSheet(checkbox_style)
        for cb in getattr(self, "_general_checkboxes", []):
            cb.setStyleSheet(checkbox_style)
        spinbox_style = f"""
            QWidget {{
                background-color: {light_bg};
                border: 1px solid {border};
                border-radius: 4px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {text_dark};
                font-size: 16px;
                font-weight: bold;
                min-width: 32px;
                max-width: 32px;
                min-height: 36px;
            }}
            QPushButton:hover {{
                background-color: {dark_bg};
                color: {primary};
            }}
            QPushButton:pressed {{
                background-color: {dark_bg};
            }}
            QPushButton#minus_btn {{
                border-right: 1px solid {border};
                border-top-left-radius: 4px;
                border-bottom-left-radius: 4px;
            }}
            QPushButton#plus_btn {{
                border-left: 1px solid {border};
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }}
            QSpinBox {{
                border: none;
                background: transparent;
                min-height: 36px;
                padding: 0 4px;
                font-size: 14px;
                color: {text_dark};
                selection-background-color: {primary};
            }}
        """
        all_spinboxes = []
        try:
            all_spinboxes.extend(list(getattr(self, "_perf_spinboxes", []) or []))
        except Exception:
            pass
        try:
            all_spinboxes.extend(list(getattr(self, "_general_spinboxes", []) or []))
        except Exception:
            pass
        for sb in all_spinboxes:
            try:
                sb.setStyleSheet(spinbox_style)
            except Exception:
                pass
        if getattr(self, "shortcut_table", None):
            self._apply_shortcut_table_styles()
        for btn in getattr(self, "shortcut_reset_buttons", []):
            self._apply_shortcut_reset_button_style(btn)
        for recorder in getattr(self, "shortcut_recorders", {}).values():
            if hasattr(recorder, "_apply_theme_styles"):
                recorder._apply_theme_styles()
        self._apply_restore_all_button_style()

    def init_general_tab(self):
        outer_layout = QVBoxLayout(self.general_tab)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        cm = ColorManager.instance()
        page_bg = cm.get("theme.background.primary")
        border = cm.get("popup.border.primary")
        text_dark = cm.get("theme.text.dark")

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {page_bg};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {page_bg};
            }}
        """)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 25, 20, 25)
        content_layout.setSpacing(15)
        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)
        layout = content_layout
        self._general_scroll_area = scroll_area
        self._general_scroll_content = content
        
        group = QGroupBox("基础选项")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        form_layout = QFormLayout(group)
        form_layout.setContentsMargins(20, 25, 20, 25)
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._general_base_group = group
        
        # 个人数据位置
        data_path_layout = QHBoxLayout()
        self.data_path_input = QLineEdit()
        self.data_path_input.setReadOnly(True)
        from utils.paths import PathManager
        self.data_path_input.setText(str(PathManager.instance().get_user_data_path()))
        data_path_layout.addWidget(self.data_path_input)
        
        change_data_path_btn = QPushButton("更改")
        change_data_path_btn.setFixedWidth(60)
        change_data_path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        change_data_path_btn.clicked.connect(self._change_user_data_path)
        data_path_layout.addWidget(change_data_path_btn)
        
        form_layout.addRow("个人数据位置:", data_path_layout)

        # 根目录显示（只读）
        path_layout = QHBoxLayout()
        self.root_path_input = QLineEdit()
        self.root_path_input.setPlaceholderText("未设置")
        self.root_path_input.setReadOnly(True)
        current_root = self.settings_manager.get("general/root_path", "")
        self.root_path_input.setText(current_root)
        
        path_layout.addWidget(self.root_path_input)
        path_layout.addStretch()

        form_layout.addRow("图片库根目录:", path_layout)
        
        tip_label = QLabel("注：根目录只能在初始引导页中修改，如需修改请点击下方“恢复初始状态”按钮。")
        tip_label.setStyleSheet("color: #666; font-size: 13px; font-style: italic;")
        form_layout.addRow("", tip_label)

        self.use_config_checkbox = QCheckBox("使用 config.ini 中的配置")
        use_config = self.settings_manager.get("general/use_config_ini", False)
        self.use_config_checkbox.setChecked(bool(use_config))
        self.use_config_checkbox.stateChanged.connect(self.on_use_config_toggled)
        checkbox_border = cm.get("popup.border.primary")
        checkbox_text = cm.get("theme.text.dark")
        checkbox_checked_bg = cm.get("theme.primary")
        checkbox_unchecked_bg = cm.get("theme.background.light")
        checkbox_style = f"""
            QCheckBox {{
                color: {checkbox_text};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {checkbox_border};
                border-radius: 3px;
                background-color: {checkbox_unchecked_bg};
            }}
            QCheckBox::indicator:checked {{
                background-color: {checkbox_checked_bg};
                border: 1px solid {checkbox_checked_bg};
            }}
        """
        self.use_config_checkbox.setStyleSheet(checkbox_style)
        form_layout.addRow("配置来源:", self.use_config_checkbox)
        
        self.exif_write_mode_combo = QComboBox()
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
        self.exif_write_mode_combo.currentIndexChanged.connect(self._on_exif_write_mode_changed)
        self.settings_manager.setting_changed.connect(self._on_setting_changed_externally)
        form_layout.addRow("元数据写入:", self.exif_write_mode_combo)

        # 字体选择（单级）：将所有字体合并到一个下拉框中
        self.font_combo = QComboBox()
        font_layout = QHBoxLayout()
        font_layout.addWidget(self.font_combo, 1)
        font_layout.addStretch()
        form_layout.addRow("字体选择:", font_layout)
        self._font_catalog = self._build_font_catalog()
        self._font_choices = self._build_font_choices(self._font_catalog)
        self.font_combo.currentIndexChanged.connect(self._on_font_choice_changed)
        self._init_font_choice_selection()

        self._general_checkboxes = [
            self.use_config_checkbox,
        ]
        
        layout.addWidget(group)

        detail_group = QGroupBox("大图浏览")
        detail_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        detail_form = QFormLayout(detail_group)
        detail_form.setContentsMargins(20, 25, 20, 25)
        detail_form.setSpacing(15)
        detail_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        detail_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        detail_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.detail_auto_switch_interval_spin = ModernSpinBox()
        self.detail_auto_switch_interval_spin.setRange(50, 5000)
        self.detail_auto_switch_interval_spin.setSingleStep(50)
        self.detail_auto_switch_interval_spin.setSuffix(" ms")
        self.detail_auto_switch_interval_spin.setMaximumWidth(200)
        self.detail_auto_switch_interval_spin.setValue(int(self.settings_manager.get("image_detail/auto_switch_interval_ms", 800) or 800))
        self.detail_auto_switch_interval_spin.spinbox.valueChanged.connect(self._on_detail_auto_switch_interval_changed)
        detail_form.addRow("自动切换间隔:", self.detail_auto_switch_interval_spin)

        layout.addWidget(detail_group)

        external_group = QGroupBox("外部软件")
        external_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        external_form = QFormLayout(external_group)
        external_form.setContentsMargins(20, 25, 20, 25)
        external_form.setSpacing(15)
        external_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        external_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        external_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.external_open_app_input = QLineEdit()
        self.external_open_app_input.setPlaceholderText("留空使用系统默认关联程序")
        self.external_open_app_input.setText(str(self.settings_manager.get("external/open_image_app", "") or ""))
        self.external_open_app_input.editingFinished.connect(lambda: self._on_external_open_app_changed(self.external_open_app_input.text()))
        open_app_row = QHBoxLayout()
        open_app_row.addWidget(self.external_open_app_input, 1)
        open_app_browse = QPushButton("选择")
        open_app_browse.clicked.connect(self._browse_external_open_app)
        open_app_row.addWidget(open_app_browse)
        external_form.addRow("外部打开图片:", open_app_row)

        self.external_edit_app_input = QLineEdit()
        self.external_edit_app_input.setPlaceholderText("留空使用系统默认关联程序（可填 Lightroom 等）")
        self.external_edit_app_input.setText(str(self.settings_manager.get("external/edit_image_app", "") or ""))
        self.external_edit_app_input.editingFinished.connect(lambda: self._on_external_edit_app_changed(self.external_edit_app_input.text()))
        edit_app_row = QHBoxLayout()
        edit_app_row.addWidget(self.external_edit_app_input, 1)
        edit_app_browse = QPushButton("选择")
        edit_app_browse.clicked.connect(self._browse_external_edit_app)
        edit_app_row.addWidget(edit_app_browse)
        external_form.addRow("编辑图片软件:", edit_app_row)

        layout.addWidget(external_group)

        thumb_group = QGroupBox("缩略图显示设置")
        thumb_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        thumb_form_layout = QFormLayout(thumb_group)
        thumb_form_layout.setContentsMargins(20, 25, 20, 25)
        thumb_form_layout.setSpacing(15)
        thumb_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        thumb_form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        thumb_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.library_info_font_size_spin = ModernSpinBox()
        self.library_info_font_size_spin.setRange(8, 20)
        self.library_info_font_size_spin.setSingleStep(1)
        self.library_info_font_size_spin.setMaximumWidth(200)
        self.library_info_font_size_spin.setValue(int(self.settings_manager.get("library/thumbnail_info_font_size", 11)))
        font_row = QHBoxLayout()
        font_row.addWidget(self.library_info_font_size_spin)
        font_row.addStretch()
        thumb_form_layout.addRow("信息文字字号:", font_row)

        layout.addWidget(thumb_group)
        self._general_thumb_group = thumb_group
        self._general_spinboxes = [
            self.detail_auto_switch_interval_spin,
            self.library_info_font_size_spin,
        ]

        # Removed duplicate log management group

        theme_group = QGroupBox("主题色设置")
        cm = ColorManager.instance()
        theme_border = cm.get("settings.shortcut_table.header.border")
        theme_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {theme_border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        theme_layout = QVBoxLayout(theme_group)
        theme_layout.setContentsMargins(20, 25, 20, 25)
        theme_layout.setSpacing(10)

        grid_container = QWidget()
        grid_layout = FlowLayout()
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(10)
        grid_container.setLayout(grid_layout)

        current_colors, default_colors = self._ensure_theme_color_settings()
        self._theme_color_widgets = {}
        self._theme_presets = self._build_theme_presets(default_colors)
        preset_row = QHBoxLayout()
        preset_label = QLabel("主题预设:")
        preset_row.addWidget(preset_label)
        self._theme_preset_combo = QComboBox()
        self._theme_preset_combo.addItems(list(self._theme_presets.keys()))
        saved_preset = self.settings_manager.get("theme/preset_name", "原色")
        
        # 校验：如果保存的预设不是“原色”，但当前实际颜色与该预设不匹配，则回退到“原色”
        # 这通常发生在配置文件(colors.json)丢失或被重置，但 settings.ini 中仍保留旧预设名的情况下
        if saved_preset != "原色" and saved_preset in self._theme_presets:
            preset_colors = self._theme_presets[saved_preset]
            is_match = True
            for token, p_color in preset_colors.items():
                if not p_color: continue
                c_color = cm.get(token)
                if str(p_color).strip().upper() != str(c_color).strip().upper():
                    is_match = False
                    break
            if not is_match:
                saved_preset = "原色"
                self.settings_manager.set("theme/preset_name", "原色")

        if saved_preset in self._theme_presets:
            self._theme_preset_combo.setCurrentText(saved_preset)
        preset_row.addWidget(self._theme_preset_combo)
        self._theme_preset_combo.currentTextChanged.connect(self._on_apply_theme_preset)
        preset_row.addStretch()
        theme_layout.addLayout(preset_row)
        for item in self._theme_color_items():
            token = item["token"]
            color_btn = QPushButton()
            color_btn.setFixedSize(32, 32)
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setToolTip(item["label"])
            color_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            color_btn.clicked.connect(lambda _, t=token: self._on_choose_theme_color(t))
            color_btn.customContextMenuRequested.connect(lambda _, t=token: self._on_restore_theme_color(t))
            grid_layout.addWidget(color_btn)

            self._theme_color_widgets[token] = {
                "button": color_btn
            }
            self._update_theme_color_preview(token, current_colors.get(token, cm.get(token)))
        theme_layout.addWidget(grid_container)
        layout.addWidget(theme_group)
        self._general_theme_group = theme_group

        # Geolocation Settings
        geo_group = QGroupBox("地理定位设置")
        geo_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        geo_form_layout = QFormLayout(geo_group)
        geo_form_layout.setContentsMargins(20, 25, 20, 25)
        geo_form_layout.setSpacing(15)
        geo_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        geo_form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        geo_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._general_geo_group = geo_group

        # Service Selection
        self.geo_service_combo = QComboBox()
        self.geo_service_combo.addItems(["Nominatim (OpenStreetMap)", "高德地图 (Gaode)", "天地图 (Tianditu)"])
        current_service = self.settings_manager.get("geolocation/service", "tianditu")
        if current_service == "gaode":
            self.geo_service_combo.setCurrentIndex(1)
        elif current_service == "tianditu":
            self.geo_service_combo.setCurrentIndex(2)
        else:
            self.geo_service_combo.setCurrentIndex(0)
        self.geo_service_combo.currentIndexChanged.connect(self._on_geo_service_changed)
        geo_form_layout.addRow("服务提供商:", self.geo_service_combo)

        # Coordinate Format
        self.coord_format_combo = QComboBox()
        self.coord_format_combo.addItems(["十进制 (Decimal)", "度分秒 (DMS)"])
        current_format = self.settings_manager.get("geolocation/coord_format", "decimal")
        self.coord_format_combo.setCurrentIndex(1 if current_format == "dms" else 0)
        geo_form_layout.addRow("坐标显示格式:", self.coord_format_combo)

        # Gaode API Key
        self.gaode_key_input = QLineEdit()
        self.gaode_key_input.setPlaceholderText("请输入高德地图 API Key")
        self.gaode_key_input.setText(self.settings_manager.get("geolocation/gaode_key", ""))
        geo_form_layout.addRow("高德 API Key:", self.gaode_key_input)

        self.tianditu_key_input = QLineEdit()
        self.tianditu_key_input.setPlaceholderText("请输入天地图 API Key")
        current_key = self.settings_manager.get("geolocation/tianditu_key", "")
        if current_key == "6b4610fa57e689d864d4db5f7ee80a14":
            current_key = ""
        self.tianditu_key_input.setText(current_key)
        geo_form_layout.addRow("天地图 API Key:", self.tianditu_key_input)
        
        # Initial state update
        self._on_geo_service_changed(self.geo_service_combo.currentIndex())

        layout.addWidget(geo_group)

        log_group = QGroupBox("日志设置")
        log_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        log_form_layout = QFormLayout(log_group)
        log_form_layout.setContentsMargins(20, 25, 20, 25)
        log_form_layout.setSpacing(15)
        log_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        log_form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        log_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        cur_level = str(self.settings_manager.get("log/level", "warning") or "").strip().lower()
        if cur_level == "debug":
            self.log_level_combo.setCurrentIndex(0)
        elif cur_level == "info":
            self.log_level_combo.setCurrentIndex(1)
        elif cur_level in ("error", "err"):
            self.log_level_combo.setCurrentIndex(3)
        else:
            self.log_level_combo.setCurrentIndex(2)
        log_form_layout.addRow("打印等级:", self.log_level_combo)

        self.log_max_mb_spin = ModernSpinBox()
        self.log_max_mb_spin.setRange(64, 102400)
        self.log_max_mb_spin.setSingleStep(256)
        self.log_max_mb_spin.setSuffix(" MB")
        self.log_max_mb_spin.setMaximumWidth(200)
        try:
            cur_max_bytes = int(self.settings_manager.get("log/max_bytes", 2 * 1024 * 1024 * 1024) or 0)
        except Exception:
            cur_max_bytes = 2 * 1024 * 1024 * 1024
        cur_max_mb = int(max(64, min(102400, int(round(cur_max_bytes / 1024 / 1024)))))
        self.log_max_mb_spin.setValue(cur_max_mb)
        log_form_layout.addRow("日志上限:", self.log_max_mb_spin)
        try:
            if not hasattr(self, "_general_spinboxes") or self._general_spinboxes is None:
                self._general_spinboxes = []
            self._general_spinboxes.append(self.log_max_mb_spin)
        except Exception:
            pass

        self.log_print_console_checkbox = QCheckBox("使用控制台输出日志（不写入文件）")
        self.log_print_console_checkbox.setChecked(bool(self.settings_manager.get("log/print_to_console", False)))
        self.log_print_console_checkbox.setStyleSheet(checkbox_style)
        log_form_layout.addRow("输出方式:", self.log_print_console_checkbox)
        try:
            if not hasattr(self, "_general_checkboxes") or self._general_checkboxes is None:
                self._general_checkboxes = []
            self._general_checkboxes.append(self.log_print_console_checkbox)
        except Exception:
            pass

        log_tip = QLabel("说明：日志目录位于 /cache/logs。超过上限会自动清理到一半；超过 30 天的日志会自动清理。")
        log_tip.setStyleSheet("color: #666; font-size: 13px; font-style: italic;")
        log_form_layout.addRow("", log_tip)

        self._delete_logs_btn = QPushButton("删除所有日志")
        self._delete_logs_btn.setFixedSize(140, 36)
        self._delete_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_logs_btn.clicked.connect(self._on_delete_all_logs)
        # Apply button style
        btn_bg = cm.get("theme.primary")
        btn_text = cm.get("theme.text.light")
        self._delete_logs_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn_bg};
                color: {btn_text};
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                opacity: 0.8;
            }}
        """)
        log_form_layout.addRow("操作:", self._delete_logs_btn)

        layout.addWidget(log_group)
        self._general_log_group = log_group

        recognizer_group = QGroupBox("识别设置")
        recognizer_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        recognizer_form_layout = QFormLayout(recognizer_group)
        recognizer_form_layout.setContentsMargins(20, 25, 20, 25)
        recognizer_form_layout.setSpacing(15)
        recognizer_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        recognizer_form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        recognizer_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._general_recognizer_group = recognizer_group

        self.recognizer_service_combo = QComboBox()
        self.recognizer_service_combo.addItem("本地服务", "local")
        self.recognizer_service_combo.addItem("豆包", "doubao")
        self.recognizer_service_combo.addItem("懂鸟", "dongniao")
        try:
            cur = str(self.settings_manager.get("recognizer/service", "local") or "local").strip().lower()
        except Exception:
            cur = "local"
        try:
            for i in range(self.recognizer_service_combo.count()):
                if str(self.recognizer_service_combo.itemData(i) or "") == cur:
                    self.recognizer_service_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass
        recognizer_form_layout.addRow("识别服务:", self.recognizer_service_combo)

        self.doubao_api_key_input = QLineEdit()
        self.doubao_api_key_input.setPlaceholderText("请输入豆包 API Key")
        self.doubao_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.doubao_api_key_input.setText(self.settings_manager.get("recognizer/doubao_api_key", ""))
        recognizer_form_layout.addRow("豆包 API Key:", self.doubao_api_key_input)

        layout.addWidget(recognizer_group)
        layout.addStretch()

    def _on_geo_service_changed(self, index):
        is_gaode = (index == 1)
        is_tianditu = (index == 2)
        self.gaode_key_input.setEnabled(is_gaode)
        if hasattr(self, "tianditu_key_input"):
            self.tianditu_key_input.setEnabled(is_tianditu)
        if is_gaode:
            self.gaode_key_input.setStyleSheet("")
        else:
            self.gaode_key_input.setStyleSheet("background-color: #f5f5f5; color: #a0a0a0;")
        if hasattr(self, "tianditu_key_input"):
            if is_tianditu:
                self.tianditu_key_input.setStyleSheet("")
            else:
                self.tianditu_key_input.setStyleSheet("background-color: #f5f5f5; color: #a0a0a0;")

    def _theme_color_items(self):
        return [
            {"token": "theme.sidebar", "label": "重点色", "current_key": "theme/sidebar_color", "default_key": "theme/sidebar_color_default"},
            {"token": "theme.primary", "label": "强调色", "current_key": "theme/primary_color", "default_key": "theme/primary_color_default"},
            {"token": "theme.background.primary", "label": "背景色", "current_key": "theme/background_primary_color", "default_key": "theme/background_primary_color_default"},
            {"token": "theme.background.light", "label": "浅背景色", "current_key": "theme/background_light_color", "default_key": "theme/background_light_color_default"},
            {"token": "theme.background.dark", "label": "深背景色", "current_key": "theme/background_dark_color", "default_key": "theme/background_dark_color_default"},
            {"token": "theme.text.dark", "label": "深色文字", "current_key": "theme/text_dark_color", "default_key": "theme/text_dark_color_default"},
            {"token": "theme.text.light", "label": "浅色文字", "current_key": "theme/text_light_color", "default_key": "theme/text_light_color_default"},
        ]

    def _get_theme_preset_base_color(self, default_colors, token):
        color = (default_colors or {}).get(token)
        if not color:
            color = ColorManager.instance().get(token)
        return color

    def _build_theme_presets(self, default_colors):
        cm = ColorManager.instance()
        base_preset = {}
        factory_colors = {}
        try:
            ok, colors, _aliases, _version = cm.load_config_data()
            if ok and isinstance(colors, dict):
                factory_colors = colors
        except Exception:
            factory_colors = {}
        try:
            if getattr(cm, "factory_path", None) and os.path.exists(cm.factory_path):
                with open(cm.factory_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                c = data.get("colors") if isinstance(data, dict) else None
                if isinstance(c, dict) and c:
                    factory_colors = c
        except Exception:
            factory_colors = factory_colors or {}
        for item in self._theme_color_items():
            token = item["token"]
            base_preset[token] = factory_colors.get(token) or self._get_theme_preset_base_color(default_colors, token)
        token_map = {
            "theme.sidebar": "sidebar",
            "theme.primary": "primary",
            "theme.background.primary": "background.primary",
            "theme.background.light": "background.light",
            "theme.background.dark": "background.dark",
            "theme.text.dark": "text.dark",
            "theme.text.light": "text.light",
        }
        preset_map = {
            "暗黑": "dark",
            "夏日沙滩": "summer_beach",
            "樱花树下": "sakura",
            "霓虹灯": "neon",
            "赛博朋克": "cyberpunk",
            "海底世界": "ocean",
            "古风仙境": "oriental",
            "流星": "meteor",
            "科技感": "tech",
            "冬日飘雪": "winter",
            "新年": "new_year",
            "圣诞节": "christmas",
            "极光": "aurora",
            "暮色森林": "dusk_forest",
            "琥珀暖夜": "amber_night",
            "珊瑚礁": "coral_reef",
            "薄荷清风": "mint_breeze",
            "晨雾晴空": "morning_mist",
            "黑橙脉冲": "black_orange",
        }
        presets = {"原色": base_preset}
        for name, key in preset_map.items():
            preset = {}
            for token, suffix in token_map.items():
                preset[token] = cm.get(f"theme.preset.{key}.{suffix}")
            presets[name] = preset
        return presets

    def _on_apply_theme_preset(self, preset_name=None):
        name = preset_name or self._theme_preset_combo.currentText()
        preset = self._theme_presets.get(name)
        if not preset:
            return
        self.settings_manager.set("theme/preset_name", name)
        self._apply_theme_colors(preset)

    def _ensure_theme_color_settings(self):
        cm = ColorManager.instance()
        factory_colors = {}
        try:
            if getattr(cm, "factory_path", None) and os.path.exists(cm.factory_path):
                with open(cm.factory_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                c = data.get("colors") if isinstance(data, dict) else None
                if isinstance(c, dict):
                    factory_colors = c
        except Exception:
            factory_colors = {}
        current_colors = {}
        default_colors = {}
        for item in self._theme_color_items():
            token = item["token"]
            factory_default = factory_colors.get(token) or ""
            default_color = self.settings_manager.get(item["default_key"], "")
            if factory_default and str(default_color or "").strip().upper() != str(factory_default).strip().upper():
                default_color = factory_default
                self.settings_manager.set(item["default_key"], default_color)
            if not default_color:
                default_color = factory_default or cm.get(token)
                self.settings_manager.set(item["default_key"], default_color)
            current_color = self.settings_manager.get(item["current_key"], "")
            if not current_color:
                current_color = cm.get(token, default_color)
                self.settings_manager.set(item["current_key"], current_color)
            current_colors[token] = current_color
            default_colors[token] = default_color
        self._queue_settings_sync()
        return current_colors, default_colors

    def _read_color_config(self):
        cm = ColorManager.instance()
        write_path = cm.config_path
        ok, colors, aliases, version = cm.load_config_data()
        if not ok:
            return None
        return write_path, colors, aliases, version

    def _write_color_config(self, path, colors, aliases, version):
        data = {"version": version, "colors": colors, "aliases": aliases}
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception:
            return False
        return True

    def _apply_theme_colors(self, token_color_map, show_toast=True):
        config = self._read_color_config()
        if not config:
            NotificationManager.instance().show_warning("错误", "主题色配置文件读取失败")
            return
        path, colors, aliases, version = config
        token_to_setting = {item["token"]: item for item in self._theme_color_items()}
        for token, color_hex in token_color_map.items():
            if not isinstance(color_hex, str):
                continue
            color_hex = color_hex.strip()
            if not color_hex:
                continue
            colors[token] = color_hex.upper()
            item = token_to_setting.get(token)
            if item:
                self.settings_manager.set(item["current_key"], color_hex.upper())
        if colors.get("theme.primary"):
            colors["guide.background.top"] = colors.get("theme.primary")
        if colors.get("theme.background.primary"):
            colors["guide.background.bottom"] = colors.get("theme.background.primary")
        if not self._write_color_config(path, colors, aliases, version):
            NotificationManager.instance().show_warning("错误", "主题色配置文件写入失败")
            return
        cm = ColorManager.instance()
        cm.reload()
        for cb in list(getattr(cm, "_listeners", [])):
            try:
                cb()
            except Exception:
                pass
        self._queue_settings_sync()
        for token, color_hex in token_color_map.items():
            self._update_theme_color_preview(token, color_hex.upper())

    def _update_theme_color_preview(self, token, color_hex):
        widgets = self._theme_color_widgets.get(token)
        if not widgets:
            return
        cm = ColorManager.instance()
        border = cm.get("settings.shortcut_table.header.border")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        btn = widgets.get("button")
        if btn:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color_hex};
                    border: 1px solid {border};
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    border: 1px solid {border};
                }}
                QToolTip {{
                    color: {tooltip_text};
                    background-color: {tooltip_bg};
                    border: 1px solid {tooltip_border};
                }}
            """)

    def _refresh_theme_color_button_styles(self):
        return

    def _on_choose_theme_color(self, token):
        cm = ColorManager.instance()
        item_map = {item["token"]: item for item in self._theme_color_items()}
        item = item_map.get(token)
        if not item:
            return
        current_color = self.settings_manager.get(item["current_key"], cm.get(token))
        try:
            qc0 = QColor(str(current_color or ""))
            init_rgba = [int(qc0.red()), int(qc0.green()), int(qc0.blue()), 255]
        except Exception:
            init_rgba = [33, 150, 243, 255]
        qcolor = ThemedColorDialog.get_color(self, "选择主题色", init_rgba, show_alpha=False)
        if qcolor is None or not isinstance(qcolor, QColor) or not qcolor.isValid():
            return
        self._apply_theme_colors({token: qcolor.name().upper()})

    def _on_restore_theme_color(self, token):
        item_map = {item["token"]: item for item in self._theme_color_items()}
        item = item_map.get(token)
        if not item:
            return
        default_color = self.settings_manager.get(item["default_key"], "")
        if not default_color:
            cm = ColorManager.instance()
            default_color = cm.get(token)
            self.settings_manager.set(item["default_key"], default_color)
            self._queue_settings_sync()
        self._apply_theme_colors({token: default_color})


    def init_perf_tab(self):
        layout = QVBoxLayout(self.perf_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        cm = ColorManager.instance()
        page_bg = cm.get("theme.background.primary")
        border = cm.get("popup.border.primary")
        text_dark = cm.get("theme.text.dark")
        text_light = cm.get("theme.text.light")
        light_bg = cm.get("theme.background.light")
        dark_bg = cm.get("theme.background.dark")
        primary = cm.get("theme.primary")
        tip_text = cm.to_qss_color("theme.text.dark")
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {page_bg};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {page_bg};
            }}
        """)
        content = QWidget()
        self._perf_scroll_area = scroll_area
        self._perf_scroll_content = content
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 25, 20, 25)
        content_layout.setSpacing(15)
        
        # 通用设置
        general_group = QGroupBox("通用设置")
        general_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        general_form_layout = QFormLayout(general_group)
        general_form_layout.setContentsMargins(20, 25, 20, 25)
        general_form_layout.setSpacing(15)
        general_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        general_form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        general_form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        checkbox_border = border
        checkbox_text = text_dark
        checkbox_checked_bg = primary
        checkbox_unchecked_bg = light_bg
        checkbox_style = f"""
            QCheckBox {{
                color: {checkbox_text};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {checkbox_border};
                border-radius: 3px;
                background-color: {checkbox_unchecked_bg};
            }}
            QCheckBox::indicator:checked {{
                background-color: {checkbox_checked_bg};
                border: 1px solid {checkbox_checked_bg};
            }}
        """
        self.disable_thumbnail_scaling_checkbox = QCheckBox("禁用缩放")
        disable_scaling = self.settings_manager.get("performance/thumbnail_disable_scaling", False)
        self.disable_thumbnail_scaling_checkbox.setChecked(bool(disable_scaling))
        self.disable_thumbnail_scaling_checkbox.setStyleSheet(checkbox_style)
        disable_layout = QHBoxLayout()
        disable_layout.addWidget(self.disable_thumbnail_scaling_checkbox)
        disable_layout.addStretch()
        general_form_layout.addRow("缩略图缩放:", disable_layout)
        
        self.use_gpu_scaling_checkbox = QCheckBox("使用GPU缩放")
        use_gpu_scaling = self.settings_manager.get("performance/use_gpu_scaling", True)
        self.use_gpu_scaling_checkbox.setChecked(bool(use_gpu_scaling))
        self.use_gpu_scaling_checkbox.setStyleSheet(checkbox_style)
        # 添加提示标签说明GPU缩放的作用
        gpu_tip_label = QLabel("(使用GPU加速缩略图缩放，提升性能)")
        gpu_tip_label.setStyleSheet("color: #888; font-size: 11px;")
        gpu_layout = QHBoxLayout()
        gpu_layout.addWidget(self.use_gpu_scaling_checkbox)
        gpu_layout.addWidget(gpu_tip_label)
        gpu_layout.addStretch()
        general_form_layout.addRow("GPU缩放:", gpu_layout)

        self.disable_thumbnail_persistence_checkbox = QCheckBox("关闭本地缩略图读写")
        disable_persistence = self.settings_manager.get("performance/disable_thumbnail_persistence", False)
        self.disable_thumbnail_persistence_checkbox.setChecked(bool(disable_persistence))
        self.disable_thumbnail_persistence_checkbox.setStyleSheet(checkbox_style)
        persistence_layout = QHBoxLayout()
        persistence_layout.addWidget(self.disable_thumbnail_persistence_checkbox)
        persistence_layout.addStretch()
        general_form_layout.addRow("本地缩略图缓存:", persistence_layout)

        self.disk_cache_max_mb_spin = ModernSpinBox()
        self.disk_cache_max_mb_spin.setRange(256, 102400)
        self.disk_cache_max_mb_spin.setSingleStep(256)
        self.disk_cache_max_mb_spin.setSuffix(" MB")
        self.disk_cache_max_mb_spin.setMaximumWidth(200)
        max_bytes = int(self.settings_manager.get("performance/disk_thumbnail_cache_max_bytes", 2147483648))
        max_mb = max(0, int(max_bytes // (1024 * 1024)))
        if max_mb <= 0:
            max_mb = 2048
        self.disk_cache_max_mb_spin.setValue(max_mb)
        dmax_layout = QHBoxLayout()
        dmax_layout.addWidget(self.disk_cache_max_mb_spin)
        dmax_layout.addStretch()
        general_form_layout.addRow("磁盘缓存上限:", dmax_layout)

        self.disk_cache_cleanup_batch_spin = ModernSpinBox()
        self.disk_cache_cleanup_batch_spin.setRange(10, 20000)
        self.disk_cache_cleanup_batch_spin.setSingleStep(50)
        self.disk_cache_cleanup_batch_spin.setMaximumWidth(200)
        self.disk_cache_cleanup_batch_spin.setValue(int(self.settings_manager.get("performance/disk_thumbnail_cache_cleanup_batch", 500)))
        dbatch_layout = QHBoxLayout()
        dbatch_layout.addWidget(self.disk_cache_cleanup_batch_spin)
        dbatch_layout.addStretch()
        general_form_layout.addRow("单次清理数量:", dbatch_layout)

        self.library_scale_quality_combo = QComboBox()
        self.library_scale_quality_combo.addItems(["低质量", "高质量"])
        library_quality = str(self.settings_manager.get("library/thumbnail_scale_quality", "high")).lower()
        if library_quality not in ["low", "high"]:
            library_quality = str(self.settings_manager.get("performance/thumbnail_scale_quality", "high")).lower()
        self.library_scale_quality_combo.setCurrentIndex(1 if library_quality == "high" else 0)
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(self.library_scale_quality_combo)
        quality_layout.addStretch()
        general_form_layout.addRow("缩放质量:", quality_layout)
        
        self.import_low_quality_checkbox = QCheckBox("导入页面强制使用低质量缩略图")
        import_low_quality = self.settings_manager.get("import/force_low_quality", True)
        self.import_low_quality_checkbox.setChecked(bool(import_low_quality))
        self.import_low_quality_checkbox.setStyleSheet(checkbox_style)
        import_quality_layout = QHBoxLayout()
        import_quality_layout.addWidget(self.import_low_quality_checkbox)
        import_quality_layout.addStretch()
        general_form_layout.addRow("导入页面控制:", import_quality_layout)

        self.focus_detect_auto_switch_checkbox = QCheckBox("开始对焦检测后自动跳转至扫描文件模式")
        auto_switch_scan = self.settings_manager.get("focus_detect/auto_switch_to_scan_mode", True)
        self.focus_detect_auto_switch_checkbox.setChecked(bool(auto_switch_scan))
        self.focus_detect_auto_switch_checkbox.setStyleSheet(checkbox_style)
        fad_layout = QHBoxLayout()
        fad_layout.addWidget(self.focus_detect_auto_switch_checkbox)
        fad_layout.addStretch()
        general_form_layout.addRow("对焦检测控制:", fad_layout)

        # 导入页面加载线程数
        self.import_threads_input = ModernSpinBox()
        cpu_count = os.cpu_count() or 4
        max_threads = max(1, cpu_count - 2)
        self.import_threads_input.setRange(1, max_threads)
        self.import_threads_input.setSingleStep(1)
        self.import_threads_input.setSuffix(" 线程")
        self.import_threads_input.setMaximumWidth(200)
        cur_threads = int(self.settings_manager.get("import/loader_threads", max_threads))
        cur_threads = max(1, min(cur_threads, max_threads))
        self.import_threads_input.setValue(cur_threads)
        self.import_threads_input.spinbox.valueChanged.connect(
            lambda v: self.settings_manager.set("import/loader_threads", v)
        )
        it_layout = QHBoxLayout()
        it_layout.addWidget(self.import_threads_input)
        it_layout.addStretch()
        general_form_layout.addRow("加载线程数:", it_layout)

        import_tip = QLabel(f"注: 最大线程数限制为 {max_threads} (CPU核心数 - 2)。")
        import_tip.setStyleSheet(f"color: {tip_text}; font-size: 13px; font-style: italic;")
        general_form_layout.addRow("", import_tip)

        def _format_release_seconds(sec: int) -> str:
            v = int(sec)
            if v <= 0:
                return "永不"
            if v < 60:
                return f"{v} 秒"
            m = v // 60
            s = v % 60
            if s == 0:
                return f"{m} 分钟"
            return f"{m} 分 {s} 秒"

        self.page_cache_release_combo = QComboBox()
        values = [30] + [60 * i for i in range(1, 11)]
        for v in values:
            self.page_cache_release_combo.addItem(_format_release_seconds(v), int(v))
        self.page_cache_release_combo.addItem("永不", -1)
        try:
            cur_release = int(self.settings_manager.get("performance/page_cache_release_seconds", 120) or 120)
        except Exception:
            cur_release = 120
        if cur_release <= 0:
            cur_release = -1
        try:
            idx = self.page_cache_release_combo.findData(int(cur_release))
            if idx >= 0:
                self.page_cache_release_combo.setCurrentIndex(int(idx))
            else:
                if int(cur_release) > 0:
                    nearest = int(min(values, key=lambda x: abs(int(x) - int(cur_release))))
                    idx2 = self.page_cache_release_combo.findData(int(nearest))
                    if idx2 >= 0:
                        self.page_cache_release_combo.setCurrentIndex(int(idx2))
        except Exception:
            pass
        release_layout = QHBoxLayout()
        release_layout.addWidget(self.page_cache_release_combo)
        release_layout.addStretch()
        general_form_layout.addRow("离开页面释放缓存:", release_layout)

        # 清除缓存按钮
        clear_cache_btn = QPushButton("释放本地缓存")
        clear_cache_btn.setFixedSize(120, 36)
        clear_cache_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary};
                color: {text_light};
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {dark_bg};
            }}
        """)
        clear_cache_btn.clicked.connect(self.clear_cache)
        clear_cache_layout = QHBoxLayout()
        clear_cache_layout.addWidget(clear_cache_btn)
        clear_cache_layout.addStretch()
        general_form_layout.addRow("", clear_cache_layout)
        
        perf_tip_label = QLabel("注：增加缓存可以提高流畅度，但会占用更多内存。修改后需保存。")
        perf_tip_label.setStyleSheet(f"color: {tip_text}; font-size: 13px; font-style: italic;")
        perf_tip_layout = QHBoxLayout()
        perf_tip_layout.addWidget(perf_tip_label)
        perf_tip_layout.addStretch()
        general_form_layout.addRow("", perf_tip_layout)

        content_layout.addWidget(general_group)

        group = QGroupBox("图库缓存设置")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        form_layout = QFormLayout(group)
        form_layout.setContentsMargins(20, 25, 20, 25)
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # 缩略图缓存尺寸
        self.cache_size_spin = ModernSpinBox()
        self.cache_size_spin.setRange(100, 2000)
        self.cache_size_spin.setSingleStep(50)
        self.cache_size_spin.setSuffix(" px")
        self.cache_size_spin.setMaximumWidth(200)
        library_cache_size = int(self.settings_manager.get("library/thumbnail_cache_size", 150))
        legacy_cache_size = int(self.settings_manager.get("performance/thumbnail_cache_size", 150))
        if library_cache_size == 300 and legacy_cache_size != 300:
            library_cache_size = legacy_cache_size
        self.cache_size_spin.setValue(library_cache_size)
        try:
            self._last_applied_library_thumb_cache_size = int(library_cache_size)
        except Exception:
            self._last_applied_library_thumb_cache_size = 0
        try:
            self.cache_size_spin.spinbox.valueChanged.connect(lambda v: self._on_thumbnail_cache_size_changed("library", v))
        except Exception:
            pass
        
        cache_size_layout = QHBoxLayout()
        cache_size_layout.addWidget(self.cache_size_spin)
        cache_size_layout.addStretch()
        
        form_layout.addRow("缩略图缓存尺寸:", cache_size_layout)

        # 缩略图缓存数量
        self.cache_count_spin = ModernSpinBox()
        self.cache_count_spin.setRange(100, 5000)
        self.cache_count_spin.setSingleStep(100)
        self.cache_count_spin.setMaximumWidth(200)
        self.cache_count_spin.setValue(int(self.settings_manager.get("performance/thumbnail_cache_count", 800)))
        
        cache_count_layout = QHBoxLayout()
        cache_count_layout.addWidget(self.cache_count_spin)
        cache_count_layout.addStretch()
        
        form_layout.addRow("缩略图缓存数量:", cache_count_layout)

        content_layout.addWidget(group)

        # 导入页面设置
        import_group = QGroupBox("导入缓存设置")
        import_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: 16px;
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 20px;
                color: {text_dark};
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                left: 12px;
            }}
        """)
        import_form = QFormLayout(import_group)
        import_form.setContentsMargins(20, 25, 20, 25)
        import_form.setSpacing(15)
        import_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # 导入页面缓存尺寸
        self.import_cache_size_input = ModernSpinBox()
        self.import_cache_size_input.setRange(100, 2000)
        self.import_cache_size_input.setSingleStep(50)
        self.import_cache_size_input.setSuffix(" px")
        self.import_cache_size_input.setMaximumWidth(200)
        import_cache_size = int(self.settings_manager.get("import/thumbnail_cache_size", 150))
        import_legacy_cache_size = int(self.settings_manager.get("performance/thumbnail_cache_size", 150))
        if import_cache_size == 300 and import_legacy_cache_size != 300:
            import_cache_size = import_legacy_cache_size
        self.import_cache_size_input.setValue(import_cache_size)
        try:
            self._last_applied_import_thumb_cache_size = int(import_cache_size)
        except Exception:
            self._last_applied_import_thumb_cache_size = 0
        try:
            self.import_cache_size_input.spinbox.valueChanged.connect(lambda v: self._on_thumbnail_cache_size_changed("import", v))
        except Exception:
            pass

        ics_layout = QHBoxLayout()
        ics_layout.addWidget(self.import_cache_size_input)
        ics_layout.addStretch()
        import_form.addRow("缩略图缓存尺寸:", ics_layout)

        # 导入页面缓存数量
        self.import_cache_count_input = ModernSpinBox()
        self.import_cache_count_input.setRange(100, 5000)
        self.import_cache_count_input.setSingleStep(100)
        self.import_cache_count_input.setMaximumWidth(200)
        # 增加默认值到2000，以支持更多的对焦检测缓存
        self.import_cache_count_input.setValue(int(self.settings_manager.get("import/cache_size", 2000)))
        self.import_cache_count_input.spinbox.valueChanged.connect(
            lambda v: self.settings_manager.set("import/cache_size", v)
        )

        ic_layout = QHBoxLayout()
        ic_layout.addWidget(self.import_cache_count_input)
        ic_layout.addStretch()
        import_form.addRow("缩略图缓存数量:", ic_layout)

        self._perf_general_group = general_group
        self._perf_cache_group = group
        self._perf_import_group = import_group
        self._perf_import_tip_label = import_tip
        self._perf_perf_tip_label = perf_tip_label
        self._perf_clear_cache_btn = clear_cache_btn
        self._perf_checkboxes = [
            self.disable_thumbnail_scaling_checkbox,
            self.use_gpu_scaling_checkbox,
            self.disable_thumbnail_persistence_checkbox,
            self.import_low_quality_checkbox,
            self.focus_detect_auto_switch_checkbox,
        ]
        self._perf_spinboxes = [
            self.import_threads_input,
            self.disk_cache_max_mb_spin,
            self.disk_cache_cleanup_batch_spin,
            self.cache_size_spin,
            self.cache_count_spin,
            self.import_cache_size_input,
            self.import_cache_count_input
        ]
        content_layout.addWidget(import_group)
        content_layout.addStretch()
        scroll_area.setWidget(content)
        layout.addWidget(scroll_area)

    def init_shortcut_tab(self):
        layout = QVBoxLayout(self.shortcut_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        self.shortcut_tab.setAutoFillBackground(True)
        
        self.shortcut_table = QTableWidget()
        self.shortcut_table.setColumnCount(3)
        self.shortcut_table.setHorizontalHeaderLabels(["功能说明", "快捷键", "操作"])
        
        header = self.shortcut_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.shortcut_table.setColumnWidth(1, 200)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.shortcut_table.setColumnWidth(2, 100)
        
        self.shortcut_table.verticalHeader().setVisible(False)
        self.shortcut_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.shortcut_table.setAlternatingRowColors(True)
        self._apply_shortcut_table_styles()
        
        layout.addWidget(self.shortcut_table)

        # Add Restore All Defaults button
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(10, 10, 20, 10)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.restore_all_btn = QPushButton("全部恢复默认")
        self.restore_all_btn.setFixedSize(120, 36)
        self.restore_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_all_btn.clicked.connect(self.restore_all_shortcuts)
        self._apply_restore_all_button_style()
        
        btn_layout.addWidget(self.restore_all_btn)
        layout.addWidget(btn_container)
        
        self.refresh_shortcut_table()

    def restore_all_shortcuts(self):
        """恢复所有设置到默认状态，包括快捷键"""
        # 1. 恢复快捷键
        ShortcutManager.instance().reset_to_defaults()
        
        # 2. 恢复配置文件 (settings.json)
        # 警告：这会清除所有用户设置！
        # 但通常用户点击"恢复默认"就是这个预期。
        # 注意：不要清除 first_run 标记，否则下次启动又要进向导
        
        # 备份 first_run 状态
        is_first_run = self.settings_manager.get("general/first_run", False)
        
        # 清除所有设置
        self.settings_manager.settings.clear()
        
        # 恢复 first_run 标记
        self.settings_manager.set("general/first_run", is_first_run)
        # 标记为已完成设置（防止意外进入向导）
        self.settings_manager.set("general/setup_completed", True)
        # 标记不需要清理缓存
        self.settings_manager.set("general/guide_cache_cleared", True)
        
        # 保存到磁盘
        self.settings_manager.sync()
        
        # 刷新界面状态
        self.load_settings()
        self.refresh_shortcut_table()
        
        NotificationManager.instance().show_toast("已恢复所有默认设置")

    def _apply_restore_all_button_style(self):
        if not getattr(self, "restore_all_btn", None):
            return
        cm = ColorManager.instance()
        btn_text = cm.to_qss_color("theme.primary")
        btn_border = cm.to_qss_color("theme.primary")
        btn_hover_bg = cm.to_qss_color("theme.primary")
        btn_hover_text = cm.to_qss_color("theme.text.light")
        
        self.restore_all_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {btn_text};
                border: 1px solid {btn_border};
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {btn_hover_bg};
                color: {btn_hover_text};
                border: 1px solid {btn_hover_bg};
            }}
        """)

    def refresh_shortcut_table(self):
        self.shortcut_table.setRowCount(0)
        shortcuts = ShortcutManager.instance().get_all_shortcuts()
        self.shortcut_recorders = {}
        self.shortcut_reset_buttons = []
        
        def _shortcut_sort_key(item):
            sid = str(item[0] or "")
            prefix = sid.split(".", 1)[0] if "." in sid else sid
            prefix_order = {
                "ImageDetail": 0,
                "ImageDetailRight": 1,
                "ThumbnailGrid": 2,
                "ImageLibrary": 3,
                "General": 4,
            }.get(prefix, 99)
            return (int(prefix_order), prefix, sid)
        
        sorted_shortcuts = sorted(shortcuts.items(), key=_shortcut_sort_key)
        
        for row, (sid, info) in enumerate(sorted_shortcuts):
            self.shortcut_table.insertRow(row)
            self.shortcut_table.setRowHeight(row, 65)
            
            # Col 0: Description
            desc = info.get('desc', sid)
            desc_item = QTableWidgetItem(desc)
            desc_item.setFlags(Qt.ItemFlag.ItemIsEnabled) # Read only
            desc_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.shortcut_table.setItem(row, 0, desc_item)
            
            # Col 1: Recorder
            seq = str(info.get('sequence', ''))
            recorder = ShortcutRecorder(seq)
            recorder.shortcut_changed.connect(lambda s, i=sid: self.on_shortcut_edited(i, s))
            
            # Wrap recorder in a widget for padding/alignment
            recorder_container = QWidget()
            recorder_layout = QHBoxLayout(recorder_container)
            recorder_layout.setContentsMargins(5, 4, 5, 4)
            recorder_layout.addWidget(recorder)
            
            self.shortcut_table.setCellWidget(row, 1, recorder_container)
            self.shortcut_recorders[sid] = recorder
            
            # Col 2: Reset Button
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            reset_btn = QPushButton("恢复")
            reset_btn.setFixedSize(60, 30)
            reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._apply_shortcut_reset_button_style(reset_btn)
            reset_btn.clicked.connect(lambda _, i=sid: self.reset_single_shortcut(i))
            
            btn_layout.addWidget(reset_btn)
            self.shortcut_table.setCellWidget(row, 2, btn_widget)
            self.shortcut_reset_buttons.append(reset_btn)

    def _apply_shortcut_table_styles(self):
        if not getattr(self, "shortcut_table", None):
            return
        cm = ColorManager.instance()
        table_bg = cm.to_qss_color("theme.background.light")
        table_alt_bg = cm.to_qss_color("theme.background.primary")
        table_grid = cm.to_qss_color("popup.border.primary")
        header_bg = cm.to_qss_color("theme.background.dark")
        header_text = cm.to_qss_color("theme.text.dark")
        header_border = cm.to_qss_color("popup.border.primary")
        row_hover_bg = cm.to_qss_color("theme.background.dark")
        row_hover_border = cm.to_qss_color("popup.border.primary")
        item_text = cm.to_qss_color("theme.text.dark")
        combo_bg = cm.to_qss_color("theme.background.light")
        combo_text = cm.to_qss_color("theme.text.dark")
        combo_border = cm.to_qss_color("popup.border.primary")
        combo_hover_border = cm.to_qss_color("theme.primary")
        combo_primary = cm.to_qss_color("theme.primary")
        combo_selected_text = cm.to_qss_color("theme.text.light")
        # 使用Base64编码的SVG箭头，避免中文路径问题
        from ui.common.icon_utils import get_arrow_down_svg_base64
        arrow_url = get_arrow_down_svg_base64(combo_text.lstrip('#') if combo_text.startswith('#') else "#333333")
        self.shortcut_table.setStyleSheet(f"""
            QTableWidget {{ 
                border: none; 
                background-color: {table_bg};
                alternate-background-color: {table_alt_bg};
                gridline-color: {table_grid};
                color: {item_text};
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                padding: 8px;
                border: none;
                border-bottom: 1px solid {header_border};
                font-weight: bold;
                color: {header_text};
            }}
            QTableWidget::item {{
                padding: 5px;
                color: {item_text};
            }}
            QTableWidget::item:hover {{
                background-color: {row_hover_bg};
                border: 1px solid {row_hover_border};
            }}
            QTableWidget::item:selected {{
                background-color: transparent;
                color: {item_text};
            }}
            QTableWidget::item:alternate {{
                background-color: {table_alt_bg};
            }}
            QComboBox {{
                padding: 4px 8px;
                border: 1px solid {combo_border};
                background-color: {combo_bg};
                font-size: 12px;
                color: {combo_text};
            }}
            QComboBox:hover {{
                border: 1px solid {combo_hover_border};
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
                margin-right: 5px;
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {combo_border};
                background-color: {combo_bg};
                selection-background-color: {combo_primary};
                color: {combo_text};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {row_hover_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {combo_primary};
                color: {combo_selected_text};
            }}
            QScrollBar:vertical {{
                background-color: {header_bg};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {header_border};
                min-height: 30px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {row_hover_border};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                background-color: {header_bg};
                height: 10px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {header_border};
                min-width: 30px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {row_hover_border};
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """)

    def _apply_shortcut_reset_button_style(self, button):
        if not button:
            return
        cm = ColorManager.instance()
        reset_text = cm.to_qss_color("theme.primary")
        reset_border = cm.to_qss_color("theme.primary")
        reset_hover_bg = cm.to_qss_color("theme.primary")
        reset_hover_text = cm.to_qss_color("theme.text.light")
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {reset_text};
                border: 1px solid {reset_border};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {reset_hover_bg};
                color: {reset_hover_text};
                border: 1px solid {reset_hover_bg};
            }}
        """)

    def on_shortcut_edited(self, sid, new_seq):
        if new_seq:
            ShortcutManager.instance().set_shortcut(sid, new_seq)
            NotificationManager.instance().show_toast(f"快捷键已更新")
            
    def reset_single_shortcut(self, sid):
        ShortcutManager.instance().reset_shortcut(sid)
        
    def update_shortcut_inputs(self):
        """当外部（或重置）改变快捷键时更新UI"""
        shortcuts = ShortcutManager.instance().get_all_shortcuts()
        for sid, info in shortcuts.items():
            if sid in self.shortcut_recorders:
                seq = str(info.get('sequence', ''))
                self.shortcut_recorders[sid].setText(seq)

    def _clear_thumbnail_caches(self, clear_library=True, clear_import=True, clear_disk=True, clear_memory=True, clear_persistent=True, emit_signals=True, toast_text=None):
        """
        清理缩略图缓存（独立接口，供“清除本地缓存 / 恢复初始状态 / 设置变更触发重建”复用）
        
        参数:
            clear_library: 是否清理图库页（library）域的缓存
            clear_import: 是否清理导入页（import）域的缓存
            clear_disk: 是否清理磁盘缩略图缓存（cache/pictures/... + 数据库映射表）
            clear_memory: 是否清理内存中的缩略图缓存（LRU）
            clear_persistent: 是否清理持久化缩略图缓存文件（cache/thumbnails/*.pkl）
            emit_signals: 是否发出缩略图设置变更信号以触发两页重新加载
            toast_text: 操作完成后要显示的提示文案（None 表示不提示）
        """
        library_cache = None
        import_cache = None
        try:
            if clear_library:
                library_cache = ImageCacheManager.instance()
            if clear_import:
                import_cache = ImageCacheManager(context="import", enable_preload=False)
        except Exception:
            library_cache = None
            import_cache = None

        if clear_memory:
            if library_cache is not None:
                try:
                    library_cache.clear()
                except Exception:
                    pass
            if import_cache is not None:
                try:
                    import_cache.clear()
                except Exception:
                    pass

        if clear_persistent:
            if library_cache is not None:
                try:
                    library_cache.clear_persistent_cache()
                except Exception:
                    pass
            if import_cache is not None:
                try:
                    import_cache.clear_persistent_cache()
                except Exception:
                    pass

        if clear_disk:
            try:
                from cache.thumbnail_disk_cache import ThumbnailDiskCache
                if library_cache is not None:
                    try:
                        ThumbnailDiskCache(library_cache, scope="library").clear_all()
                    except Exception:
                        pass
                if import_cache is not None:
                    try:
                        ThumbnailDiskCache(import_cache, scope="import").clear_all()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if clear_import:
                    import shutil
                    from cache.focus_scaled_cache import get_cache_dir

                    d = get_cache_dir("import_focus")
                    if d and os.path.isdir(d):
                        shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

        if emit_signals:
            if clear_library:
                try:
                    self.library_thumbnail_setting_changed.emit()
                except Exception:
                    pass
            if clear_import:
                try:
                    self.import_thumbnail_setting_changed.emit()
                except Exception:
                    pass

        if toast_text:
            NotificationManager.instance().show_toast(str(toast_text))

    def _on_thumbnail_cache_size_changed(self, scope, value):
        try:
            scope = str(scope or "").lower()
        except Exception:
            scope = ""
        if scope not in ("library", "import"):
            return

        if not hasattr(self, "_thumb_cache_size_change_timer"):
            self._thumb_cache_size_change_timer = QTimer(self)
            self._thumb_cache_size_change_timer.setSingleShot(True)
            self._thumb_cache_size_change_timer.timeout.connect(self._apply_thumbnail_cache_size_change)

        if not hasattr(self, "_thumb_cache_size_change_scopes"):
            self._thumb_cache_size_change_scopes = set()

        try:
            self._thumb_cache_size_change_scopes.add(scope)
        except Exception:
            pass
        try:
            self._thumb_cache_size_change_timer.start(500)
        except Exception:
            pass

    def _apply_thumbnail_cache_size_change(self):
        scopes = set(getattr(self, "_thumb_cache_size_change_scopes", set()) or set())
        try:
            self._thumb_cache_size_change_scopes = set()
        except Exception:
            pass

        library_changed = False
        import_changed = False
        try:
            if "library" in scopes and hasattr(self, "cache_size_spin"):
                new_v = int(self.cache_size_spin.value())
                old_v = int(getattr(self, "_last_applied_library_thumb_cache_size", 0) or 0)
                if new_v and new_v != old_v:
                    self._last_applied_library_thumb_cache_size = new_v
                    self.settings_manager.set("library/thumbnail_cache_size", new_v)
                    self.settings_manager.set("performance/thumbnail_cache_size", new_v)
                    library_changed = True
        except Exception:
            pass

        try:
            if "import" in scopes and hasattr(self, "import_cache_size_input"):
                new_v = int(self.import_cache_size_input.value())
                old_v = int(getattr(self, "_last_applied_import_thumb_cache_size", 0) or 0)
                if new_v and new_v != old_v:
                    self._last_applied_import_thumb_cache_size = new_v
                    self.settings_manager.set("import/thumbnail_cache_size", new_v)
                    import_changed = True
        except Exception:
            pass

        if not library_changed and not import_changed:
            return

        try:
            self.settings_manager.sync()
        except Exception:
            pass

        try:
            from cache.cache_manager import ImageCacheManager
            if library_changed:
                try:
                    ImageCacheManager.instance().update_settings()
                except Exception:
                    pass
            if import_changed:
                try:
                    ImageCacheManager(context="import", enable_preload=False).update_settings()
                except Exception:
                    pass
        except Exception:
            pass

        self._clear_thumbnail_caches(
            clear_library=library_changed,
            clear_import=import_changed,
            clear_disk=True,
            clear_memory=True,
            clear_persistent=True,
            emit_signals=True,
            toast_text="缩略图缓存尺寸已修改，已清理旧缓存"
        )

    def save_settings(self):
        """保存设置"""
        old_values = {}
        try:
            watch_keys = [
                "exif/disable_write",
                "exif/write_mode",
                "geolocation/service",
                "geolocation/coord_format",
                "log/level",
                "log/max_bytes",
                "log/cleanup_target_bytes",
                "log/print_to_console",
            ]
            for k in watch_keys:
                try:
                    old_values[k] = self.settings_manager.get(k)
                except Exception:
                    pass
        except Exception:
            old_values = {}
            
        # 注意：exif/write_mode 已经在 _on_exif_write_mode_changed 中即时保存了
        # 这里不需要重复保存，除非我们想覆盖它。
        # 但 save_settings 通常在点击“保存”或关闭时调用？
        # 不，这个 SettingsPage 是即时生效的，save_settings 似乎是一个遗留方法或者用于特定场景
        # 检查代码发现 _on_...changed 都会调用 settings_manager.set + sync
        # 所以这里的逻辑可能是冗余的，或者用于非即时生效的控件。
        # 既然我们已经在 changed 信号中处理了 Exif 切换逻辑（含弹窗），这里就不应该再简单覆盖了，否则会绕过弹窗。
        # 因此，移除这里的 Exif 保存逻辑，让 _on_exif_write_mode_changed 全权负责。
        
        # 保存字体设置
        if hasattr(self, "font_combo"):
            font_name = self.font_combo.currentText()
            if font_name:
                self.settings_manager.set("general/font_name", font_name)
        
        # Save Geolocation settings
        idx = int(self.geo_service_combo.currentIndex())
        if idx == 1:
            service = "gaode"
        elif idx == 2:
            service = "tianditu"
        else:
            service = "nominatim"
        self.settings_manager.set("geolocation/service", service)
        
        coord_fmt = "dms" if self.coord_format_combo.currentIndex() == 1 else "decimal"
        self.settings_manager.set("geolocation/coord_format", coord_fmt)
        
        self.settings_manager.set("geolocation/gaode_key", self.gaode_key_input.text().strip())
        if hasattr(self, "tianditu_key_input"):
            self.settings_manager.set("geolocation/tianditu_key", self.tianditu_key_input.text().strip())

        if hasattr(self, "doubao_api_key_input"):
            self.settings_manager.set("recognizer/doubao_api_key", self.doubao_api_key_input.text().strip())
        try:
            if hasattr(self, "recognizer_service_combo"):
                svc = str(self.recognizer_service_combo.currentData() or "local").strip().lower()
                if svc not in ("local", "doubao", "dongniao"):
                    svc = "local"
                self.settings_manager.set("recognizer/service", svc)
        except Exception:
            pass

        try:
            if hasattr(self, "log_level_combo"):
                idx = int(self.log_level_combo.currentIndex())
                level = "warning"
                if idx == 0:
                    level = "debug"
                elif idx == 1:
                    level = "info"
                elif idx == 3:
                    level = "error"
                else:
                    level = "warning"
                self.settings_manager.set("log/level", str(level))
        except Exception:
            pass
        try:
            if hasattr(self, "log_max_mb_spin"):
                max_mb = int(self.log_max_mb_spin.value())
                max_bytes = int(max_mb) * 1024 * 1024
                self.settings_manager.set("log/max_bytes", int(max_bytes))
                self.settings_manager.set("log/cleanup_target_bytes", int(max_bytes / 2))
        except Exception:
            pass
        try:
            if hasattr(self, "log_print_console_checkbox"):
                self.settings_manager.set("log/print_to_console", bool(self.log_print_console_checkbox.isChecked()))
        except Exception:
            pass
        
        old_library_size = int(self.settings_manager.get("library/thumbnail_cache_size", 300))
        old_legacy_size = int(self.settings_manager.get("performance/thumbnail_cache_size", 300))
        if old_library_size == 300 and old_legacy_size != 300:
            old_library_size = old_legacy_size
        old_import_size = int(self.settings_manager.get("import/thumbnail_cache_size", 300))
        old_disable_scaling = bool(self.settings_manager.get("performance/thumbnail_disable_scaling", False))
        old_library_quality = str(self.settings_manager.get("library/thumbnail_scale_quality", "high")).lower()
        old_import_quality = str(self.settings_manager.get("import/thumbnail_scale_quality", "high")).lower()
        old_import_force_low_quality = bool(self.settings_manager.get("import/force_low_quality", True))
        old_use_gpu_scaling = bool(self.settings_manager.get("performance/use_gpu_scaling", False))
        old_info_font_px = int(self.settings_manager.get("library/thumbnail_info_font_size", 11))
        new_library_size = self.cache_size_spin.value()
        new_import_size = self.import_cache_size_input.value()
        new_disable_scaling = self.disable_thumbnail_scaling_checkbox.isChecked()
        new_library_quality = "high" if self.library_scale_quality_combo.currentIndex() == 1 else "low"
        new_use_gpu_scaling = self.use_gpu_scaling_checkbox.isChecked()
        new_disable_persistence = self.disable_thumbnail_persistence_checkbox.isChecked()
        new_import_force_low_quality = self.import_low_quality_checkbox.isChecked()
        new_disk_cache_max_bytes = int(self.disk_cache_max_mb_spin.value()) * 1024 * 1024
        new_disk_cache_cleanup_batch = int(self.disk_cache_cleanup_batch_spin.value())
        new_info_font_px = int(self.library_info_font_size_spin.value()) if hasattr(self, "library_info_font_size_spin") else int(old_info_font_px)
        new_info_font_px = int(max(8, min(20, new_info_font_px)))
        ui_perf_changed = False
        font_changed = int(old_info_font_px) != int(new_info_font_px)
        
        self.settings_manager.set("library/thumbnail_cache_size", new_library_size)
        self.settings_manager.set("performance/thumbnail_cache_size", new_library_size)
        self.settings_manager.set("performance/thumbnail_cache_count", self.cache_count_spin.value())
        self.settings_manager.set("performance/thumbnail_disable_scaling", new_disable_scaling)
        self.settings_manager.set("performance/thumbnail_scale_quality", new_library_quality)
        self.settings_manager.set("performance/use_gpu_scaling", new_use_gpu_scaling)
        self.settings_manager.set("performance/disable_thumbnail_persistence", new_disable_persistence)
        self.settings_manager.set("performance/disk_thumbnail_cache_max_bytes", new_disk_cache_max_bytes)
        self.settings_manager.set("performance/disk_thumbnail_cache_cleanup_batch", new_disk_cache_cleanup_batch)
        self.settings_manager.set("library/thumbnail_scale_quality", new_library_quality)
        self.settings_manager.set("library/thumbnail_info_font_size", int(new_info_font_px))
        # 导入页面缩略图质量默认跟随全局设置，但如果勾选了强制低质量，则会被覆盖
        self.settings_manager.set("import/thumbnail_scale_quality", new_library_quality)
        self.settings_manager.set("import/thumbnail_cache_size", new_import_size)
        self.settings_manager.set("import/cache_size", self.import_cache_count_input.value())
        self.settings_manager.set("import/force_low_quality", new_import_force_low_quality)
        try:
            if hasattr(self, "focus_detect_auto_switch_checkbox") and self.focus_detect_auto_switch_checkbox is not None:
                self.settings_manager.set("focus_detect/auto_switch_to_scan_mode", bool(self.focus_detect_auto_switch_checkbox.isChecked()))
        except Exception:
            pass
        try:
            if hasattr(self, "page_cache_release_combo") and self.page_cache_release_combo is not None:
                v = self.page_cache_release_combo.currentData()
                sec = int(v) if v is not None else 120
                self.settings_manager.set("performance/page_cache_release_seconds", int(sec))
        except Exception:
            pass
        self.settings_manager.sync()
        try:
            LogManager.instance().reload_settings()
        except Exception:
            pass
        try:
            changed = []
            for k, ov in (old_values or {}).items():
                try:
                    nv = self.settings_manager.get(k)
                except Exception:
                    continue
                if str(ov) != str(nv):
                    changed.append(f"{k}: {ov} -> {nv}")
            if changed:
                LogManager.instance().info("设置变更: " + "; ".join(changed))
        except Exception:
            pass

        if ui_perf_changed:
            try:
                self.thumbnail_ui_perf_setting_changed.emit()
            except Exception:
                pass
        
        # 更新缓存管理器
        try:
            from cache.cache_manager import ImageCacheManager
            library_cache = ImageCacheManager.instance()
            library_cache.update_settings()
            import_cache = ImageCacheManager(context="import", enable_preload=False)
            import_cache.update_settings()
            
            library_size_changed = old_library_size != new_library_size
            import_size_changed = old_import_size != new_import_size
            scale_changed = (
                old_disable_scaling != new_disable_scaling
                or old_library_quality != new_library_quality
                or old_import_quality != new_library_quality
                or old_import_force_low_quality != new_import_force_low_quality
                or old_use_gpu_scaling != new_use_gpu_scaling
            )
            
            if scale_changed:
                self._clear_thumbnail_caches(
                    clear_library=True,
                    clear_import=True,
                    clear_disk=True,
                    clear_memory=True,
                    clear_persistent=True,
                    emit_signals=True,
                    toast_text="缩略图设置已更新，正在重新生成缓存..."
                )
            else:
                any_rebuild = False
                if library_size_changed:
                    self._clear_thumbnail_caches(
                        clear_library=True,
                        clear_import=False,
                        clear_disk=True,
                        clear_memory=True,
                        clear_persistent=True,
                        emit_signals=True,
                        toast_text=None
                    )
                    any_rebuild = True
                if import_size_changed:
                    self._clear_thumbnail_caches(
                        clear_library=False,
                        clear_import=True,
                        clear_disk=True,
                        clear_memory=True,
                        clear_persistent=True,
                        emit_signals=True,
                        toast_text=None
                    )
                    any_rebuild = True
                if any_rebuild:
                    NotificationManager.instance().show_toast("缩略图设置已更新，正在重新生成缓存...")
                else:
                    if ui_perf_changed:
                        NotificationManager.instance().show_toast("滚动回填设置已更新")
                    elif font_changed:
                        try:
                            self.library_thumbnail_setting_changed.emit()
                        except Exception:
                            pass
                        NotificationManager.instance().show_toast("缩略图信息文字字号已更新")
                    else:
                        NotificationManager.instance().show_toast("设置已保存")
                
        except Exception as e:
            try:
                LogManager.instance().error(f"更新缓存设置失败: {e}")
            except Exception:
                pass
            NotificationManager.instance().show_warning("错误", f"保存设置失败: {e}")

    def clear_cache(self):
        """清除本地缓存"""
        from ui.widgets.custom_message_box import CustomMessageBox
        
        reply = CustomMessageBox(self, "确认清除", "确定要清除本地所有的缩略图缓存吗？\n下次加载图片时需要重新生成缩略图。", CustomMessageBox.QUESTION).exec()
        
        if reply:
            self._clear_thumbnail_caches(
                clear_library=True,
                clear_import=True,
                clear_disk=True,
                clear_memory=True,
                clear_persistent=True,
                emit_signals=True,
                toast_text="本地缓存已清除"
            )

    def restore_user_settings(self):
        """恢复默认配置（保留根目录）"""
        from ui.widgets.custom_message_box import CustomMessageBox
        if CustomMessageBox(self, "恢复默认", "确定要恢复默认设置吗？\n（将保留图片库根目录设置）", CustomMessageBox.QUESTION).exec():
            # 保存当前的根目录设置
            root_path = self.settings_manager.get("general/root_path")
            use_config = self.settings_manager.get("general/use_config_ini")
            
            # 清除所有设置
            self.settings_manager.clear()
            
            # 恢复根目录
            if root_path:
                self.settings_manager.set("general/root_path", root_path)
            if use_config is not None:
                self.settings_manager.set("general/use_config_ini", use_config)
                
            self.settings_manager.sync()
            
            # 刷新UI
            self.cache_size_spin.setValue(300)
            self.cache_count_spin.setValue(500)
            self.disable_thumbnail_scaling_checkbox.setChecked(False)
            if hasattr(self, "library_scale_quality_combo"):
                self.library_scale_quality_combo.setCurrentIndex(0)
            if hasattr(self, "import_scale_quality_combo"):
                self.import_scale_quality_combo.setCurrentIndex(0)
            if hasattr(self, "import_cache_size_input"):
                self.import_cache_size_input.setValue(300)
            if hasattr(self, "import_cache_count_input"):
                self.import_cache_count_input.setValue(500)
            
            NotificationManager.instance().show_toast("已恢复默认配置")

    def restore_defaults(self):
        """恢复初始状态（清除所有设置，包括根目录）"""
        from ui.widgets.custom_message_box import CustomMessageBox
        if CustomMessageBox(self, "恢复初始状态", "确定要清除所有设置吗？\n下次启动将需要重新选择图片库根目录。\n注意：这将删除所有的数据库记录和缩略图缓存，并清空 data 下的可自定义配置项（会保留固定配置文件与日志文件）。\n操作完成后将自动重启应用。", CustomMessageBox.WARNING).exec():
            try:
                from utils.exif.exif_utils import ExifHandleWorker
                ExifHandleWorker.get_instance().stop(force=True)
            except Exception:
                pass
            try:
                cm = ColorManager.instance()
                ok = False
                colors = {}
                aliases = {}
                version = 1
                try:
                    if getattr(cm, "factory_path", None) and os.path.exists(cm.factory_path):
                        with open(cm.factory_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        c = data.get("colors") if isinstance(data, dict) else None
                        a = data.get("aliases") if isinstance(data, dict) else None
                        v = data.get("version", 1) if isinstance(data, dict) else 1
                        if isinstance(c, dict) and isinstance(a, dict):
                            colors = c
                            aliases = a
                            version = v
                            ok = True
                except Exception:
                    ok = False
                if not ok:
                    ok, colors, aliases, version = cm.load_config_data()
                if not ok:
                    raise RuntimeError("读取主题默认配置失败")
                self._write_color_config(cm.config_path, colors, aliases, version)
                cm.reload()
                for cb in list(getattr(cm, "_listeners", [])):
                    try:
                        cb()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                self._clear_thumbnail_caches(
                    clear_library=True,
                    clear_import=True,
                    clear_disk=True,
                    clear_memory=True,
                    clear_persistent=True,
                    emit_signals=False,
                    toast_text=None
                )
            except Exception:
                pass

            # 删除数据库文件
            try:
                db_path = get_default_db_path()
                targets = [db_path]
                
                for db_path in targets:
                    try:
                        if os.path.exists(db_path):
                            os.remove(db_path)
                    except Exception as e:
                        try:
                            LogManager.instance().error(f"Failed to delete DB file: {e}")
                        except Exception:
                            pass
                    for ext in ["-wal", "-shm"]:
                        p = str(db_path) + ext
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                from utils.paths import PathManager
                pm = PathManager.instance()
                
                # 清空 data 目录下的用户文件
                data_dir = pm.get_user_data_path()
                try:
                    # Clear tags
                    tags_path = data_dir / "tags.json"
                    if tags_path.exists():
                        with open(tags_path, "w", encoding="utf-8") as f:
                            json.dump([], f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

                # Clear other user directories
                # Note: This logic seems to assume user data is structured like the old data folder.
                # Now that user data IS the data folder, we can just clear contents of specific subdirs.
                
                subdirs_to_clear = ["setting", "filter", "cache", "db", "exif_presets", "exif_read_presets", "remark_presets"]
                
                for dir_name in subdirs_to_clear:
                    target_dir = data_dir / dir_name
                    if not target_dir.exists():
                        continue
                        
                    for entry in target_dir.iterdir():
                        if entry.name == ".gitkeep":
                            continue
                        
                        # Preserve colors.json (we handled it above)
                        if dir_name == "setting" and entry.name == "colors.json":
                            continue
                            
                        # Preserve import_stash structure but clear content? 
                        # Original code cleared import_stash.json content but kept file.
                        if dir_name == "cache" and entry.name == "import_stash.json":
                             try:
                                with open(entry, "w", encoding="utf-8") as f:
                                    json.dump(
                                        {
                                            "version": 1,
                                            "stash_filter_mode": 0,
                                            "stash_filter_enabled": False,
                                            "stash_by_folder": {},
                                            "updated_at": 0,
                                        },
                                        f,
                                        ensure_ascii=False,
                                        indent=2,
                                    )
                             except Exception:
                                pass
                             continue

                        try:
                            if entry.is_dir():
                                shutil.rmtree(entry, ignore_errors=True)
                            else:
                                os.remove(entry)
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                exclude_key = "geolocation/tianditu_last_call_ts"
                preserved_ts = self.settings_manager.get(exclude_key, 0)
                try:
                    self.settings_manager.set(exclude_key, preserved_ts)
                except Exception:
                    pass
                self.settings_manager.restore_defaults(exclude_keys=[exclude_key])
            except Exception:
                try:
                    self.settings_manager.clear()
                except Exception:
                    pass
                try:
                    self.settings_manager.sync()
                except Exception:
                    pass
            
            NotificationManager.instance().show_toast("已恢复初始状态，正在重启应用...")

            def _restart_app():
                try:
                    if getattr(sys, "frozen", False):
                        program = sys.executable
                        args = sys.argv[1:]
                    else:
                        program = sys.executable
                        args = sys.argv
                    QProcess.startDetached(program, args)
                except Exception:
                    pass
                try:
                    app = QApplication.instance()
                    if app:
                        try:
                            app.setProperty("skip_exit_confirm", True)
                        except Exception:
                            pass
                        app.quit()
                except Exception:
                    pass

            try:
                QTimer.singleShot(200, _restart_app)
            except Exception:
                _restart_app()

    def _on_rebuild_thumb_finished(self, count):
        if self._rebuild_thumb_overlay:
            self._rebuild_thumb_overlay.hide()
            self._rebuild_thumb_overlay = None
        self._rebuild_thumb_worker = None
        NotificationManager.instance().show_toast(f"缩略图缓存重建完成（{count}张）")
        self.library_thumbnail_setting_changed.emit()

    def _on_external_open_app_changed(self, text: str):
        try:
            self.settings_manager.set("external/open_image_app", str(text or "").strip())
            self._queue_settings_sync()
        except Exception:
            pass

    def _on_external_edit_app_changed(self, text: str):
        try:
            self.settings_manager.set("external/edit_image_app", str(text or "").strip())
            self._queue_settings_sync()
        except Exception:
            pass

    def _browse_external_open_app(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "选择外部打开图片的软件", "", "应用程序 (*.exe);;所有文件 (*.*)")
        except Exception:
            path = ""
        if not path:
            return
        try:
            self.external_open_app_input.setText(str(path))
        except Exception:
            pass

    def _browse_external_edit_app(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "选择编辑图片的软件", "", "应用程序 (*.exe);;所有文件 (*.*)")
        except Exception:
            path = ""
        if not path:
            return
        try:
            self.external_edit_app_input.setText(str(path))
        except Exception:
            pass

    def on_use_config_toggled(self, state):
        checked = state == Qt.CheckState.Checked.value or state == True
        self.settings_manager.set("general/use_config_ini", checked)
        self._queue_settings_sync()
        if checked:
            NotificationManager.instance().show_toast("已启用 config.ini 配置优先")
        else:
            NotificationManager.instance().show_toast("已禁用 config.ini 配置优先")

    def _on_delete_all_logs(self):
        """删除所有日志"""
        from ui.widgets.custom_message_box import CustomMessageBox
        if CustomMessageBox(self, "确认删除", "确定要删除所有日志文件吗？此操作不可恢复。", CustomMessageBox.QUESTION).exec():
            try:
                LogManager.instance().delete_all_logs()
                NotificationManager.instance().show_toast("日志文件已删除")
            except Exception as e:
                NotificationManager.instance().show_warning("错误", f"删除日志失败: {e}")

    def _build_font_catalog(self):
        """扫描 assets/fonts 并构建字体目录结构映射（字体种类 -> 子类型列表）"""
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
        families = {
            "思源黑体": "siyuan",
        }
        catalog = {}
        for display_name, folder in families.items():
            folder_path = os.path.join(base_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            variants = []
            for fn in sorted(os.listdir(folder_path)):
                if not fn.lower().endswith((".ttf", ".otf", ".ttc")):
                    continue
                full_path = os.path.join(folder_path, fn)
                vname = self._derive_variant_name(folder, fn)
                variants.append({"name": vname, "file": fn, "path": full_path, "folder": folder})
            if variants:
                catalog[display_name] = {"folder": folder, "variants": variants}
        return catalog

    def _derive_variant_name(self, folder, filename):
        """根据字体文件名生成最适合的中文子类型名称"""
        name = filename
        lower = filename.lower()
        if folder == "Harmony":
            if "black" in lower:
                return "黑体"
            if "bold" in lower:
                return "粗体"
            if "semibold" in lower:
                return "半粗体"
            if "medium" in lower:
                return "中等"
            if "regular" in lower or "normal" in lower:
                return "常规"
            if "light" in lower:
                return "细线"
            if "thin" in lower:
                return "细体"
        if folder == "siyuan":
            if "heavy" in lower:
                return "特粗"
            if "bold" in lower:
                return "粗体"
            if "medium" in lower:
                return "中等"
            if "light" in lower:
                return "细体"
            if "regular" in lower or "normal" in lower:
                return "常规"
        if folder == "wenyuan":
            if "heavy" in lower:
                return "特粗"
            if "bold" in lower:
                return "粗体"
            if "medium" in lower:
                return "中等"
            if "light" in lower:
                return "细体"
            if "thin" in lower:
                return "细体"
            if "regular" in lower or "normal" in lower:
                return "常规"
        if folder == "OPPOSans":
            return "常规"
        if folder == "nami":
            if "mono" in lower:
                return "等宽常规"
            return "常规"
        if folder == "wqy":
            if "lite" in lower:
                return "细微米黑"
            return "微米黑标准版"
        return name

    def _build_font_choices(self, catalog):
        """将字体目录结构平铺为单个下拉框的选项"""
        out = []
        seen_variants = set()
        for family_display, entry in (catalog or {}).items():
            variants = entry.get("variants") or []
            for v in variants:
                variant_name = v.get("name") or ""
                if variant_name in seen_variants:
                    continue
                seen_variants.add(variant_name)
                text = f"{variant_name}"
                out.append({
                    "text": text,
                    "family": family_display,
                    "variant": variant_name,
                    "file": v.get("file"),
                    "path": v.get("path"),
                })
        return out

    def _init_font_choice_selection(self):
        """根据已保存设置回填单级字体下拉框，并避免初始化时触发切换逻辑"""
        try:
            self.font_combo.blockSignals(True)
        except Exception:
            pass
        self.font_combo.clear()
        for item in (getattr(self, "_font_choices", None) or []):
            self.font_combo.addItem(str(item.get("text") or ""))

        saved_variant = str(self.settings_manager.get("general/font_variant", "") or "")
        if not saved_variant:
            saved_variant = str(self.settings_manager.get("general/font_name", "") or "")

        idx = None
        if saved_variant:
            for i, it in enumerate(self._font_choices):
                if str(it.get("variant") or "") == saved_variant:
                    idx = i
                    break
        if idx is None:
            for i, it in enumerate(self._font_choices):
                if str(it.get("variant") or "") == "常规":
                    idx = i
                    break
        if idx is None:
            idx = 0
        try:
            self.font_combo.setCurrentIndex(int(max(0, idx)))
        except Exception:
            pass
        try:
            self.font_combo.blockSignals(False)
        except Exception:
            pass

    def _on_exif_write_mode_changed(self, _index):
        try:
            mode = str(self.exif_write_mode_combo.currentData() or "file").strip().lower()
        except Exception:
            mode = "file"
        if mode not in ("file", "xmp", "none"):
            mode = "file"
        try:
            self.settings_manager.set("exif/write_mode", mode)
            self.settings_manager.set("exif/disable_write", mode == "none")
            self._queue_settings_sync()
        except Exception:
            pass

    def _on_setting_changed_externally(self, key, value):
        """处理外部设置变更"""
        if key in ("exif/write_mode", "exif/disable_write"):
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
                        if int(self.exif_write_mode_combo.currentIndex()) != int(i):
                            self.exif_write_mode_combo.blockSignals(True)
                            self.exif_write_mode_combo.setCurrentIndex(i)
                            self.exif_write_mode_combo.blockSignals(False)
                        break
            except Exception:
                try:
                    self.exif_write_mode_combo.blockSignals(False)
                except Exception:
                    pass

    def _on_font_choice_changed(self, index):
        """字体切换处理：保存设置并立即对全软件控件生效"""
        try:
            idx = int(index)
        except Exception:
            idx = -1
        choices = getattr(self, "_font_choices", None) or []
        if idx < 0 or idx >= len(choices):
            return
        item = choices[idx]
        family = str(item.get("family") or "")
        variant = str(item.get("variant") or "")
        if not family or not variant:
            return
        self.settings_manager.set("general/font_family", family)
        self.settings_manager.set("general/font_variant", variant)
        self.settings_manager.set("general/font_name", variant)
        self._queue_settings_sync()
        try:
            self._pending_font_choice = (family, variant)
            if self._font_apply_timer.isActive():
                self._font_apply_timer.stop()
            self._font_apply_timer.start()
        except Exception:
            self._pending_font_choice = None

    def _apply_pending_font_choice(self):
        try:
            pending = getattr(self, "_pending_font_choice", None)
        except Exception:
            pending = None
        if not pending:
            return
        family, variant = pending
        try:
            self._apply_selected_font(family, variant)
        except Exception:
            return
        try:
            NotificationManager.instance().show_toast(f"字体已切换为：{variant}")
        except Exception:
            pass

    def _apply_selected_font(self, family_name, variant_name):
        entry = self._font_catalog.get(family_name, {})
        variants = entry.get("variants", [])
        target = None
        for v in variants:
            if v["name"] == variant_name:
                target = v
                break
        if not target:
            return
        font_path = target["path"]
        if not os.path.exists(font_path):
            try:
                LogManager.instance().warning(f"字体文件不存在: {font_path}")
            except Exception:
                pass
            return
        from PyQt6.QtGui import QFontDatabase, QFont
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id < 0:
            try:
                LogManager.instance().warning(f"加载字体失败: {font_path}")
            except Exception:
                pass
            return
        families = QFontDatabase.applicationFontFamilies(font_id)
        font_family = families[0] if families else ""
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        current_font = app.font() if app else QFont()
        app_font = QFont(font_family)
        try:
            if current_font.pointSize() and current_font.pointSize() > 0:
                app_font.setPointSize(int(current_font.pointSize()))
            elif current_font.pixelSize() and current_font.pixelSize() > 0:
                app_font.setPixelSize(int(current_font.pixelSize()))
        except Exception:
            pass
        if app:
            app.setFont(app_font)
            try:
                self._apply_font_to_all_widgets(app_font)
            except Exception:
                pass
            try:
                from PyQt6.QtGui import QFont
                tooltip_font = QFont(app_font)
                if current_font.pointSize() and current_font.pointSize() > 0:
                    tooltip_font.setPointSize(10)
                app.setFont(tooltip_font, "QToolTip")
            except Exception:
                pass

    def _apply_font_to_all_widgets(self, app_font):
        """将字体强制应用到所有已创建控件，保证运行时立即切换生效"""
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        try:
            widgets = list(app.allWidgets())
        except Exception:
            widgets = []
        for w in widgets:
            try:
                w.setFont(app_font)
            except Exception:
                pass
            try:
                w.update()
            except Exception:
                pass
        try:
            for tlw in app.topLevelWidgets():
                try:
                    tlw.setFont(app_font)
                except Exception:
                    pass
                try:
                    tlw.update()
                except Exception:
                    pass
        except Exception:
            pass
    
    def _apply_font_to_application(self, font_name):
        family = str(self.settings_manager.get("general/font_family", "") or "")
        if not family or family not in self._font_catalog:
            family = next(iter(self._font_catalog.keys()), "")
        variant = str(self.settings_manager.get("general/font_variant", "") or "") or str(font_name or "")
        if not variant:
            variant = "常规"
        if not family:
            return
        self._apply_selected_font(family, variant)
