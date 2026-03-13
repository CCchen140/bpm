import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, 
                             QLineEdit, QHBoxLayout, QFileDialog, QStackedWidget, QProgressBar, QComboBox, QListWidget, QListWidgetItem, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QUrl
from PyQt6.QtGui import QPixmap, QLinearGradient, QColor, QPalette, QBrush, QPainter
from ui.utils.icon_loader import qta
from utils.setting.settings_manager import SettingsManager
from utils.system.app_info_manager import AppInfoManager
from ui.utils.notification_manager import NotificationManager
from ui.widgets.loading_overlay import LoadingOverlay
from utils.worker.scan_worker import ScanWorker
from ui.utils.color_manager import ColorManager

class IntroPage(QWidget):
    """介绍页模板"""
    def __init__(self, title, description, icon_name, settings_manager=None, parent=None, show_progress=False, mode="scan"):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.settings_manager = settings_manager
        self.mode = mode
        
        # 保存默认状态
        self.default_title = title
        self.default_desc = description
        self.default_icon = icon_name
        
        layout = QVBoxLayout(self)
        layout.setSpacing(30)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cm = ColorManager.instance()
        title_color = cm.get("theme.text.dark")
        desc_color = cm.get("theme.text.dark")
        
        # 图标
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_icon(icon_name)
        layout.addWidget(self.icon_label)
        
        # 标题
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(f"""
            font-size: 28px;
            font-weight: bold;
            color: {title_color};
            font-family: "Microsoft YaHei";
        """)
        layout.addWidget(self.title_label)
        
        # 说明文字
        self.desc_label = QLabel(description)
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet(f"""
            font-size: 16px;
            color: {desc_color};
            line-height: 24px;
        """)
        layout.addWidget(self.desc_label)

        # 目录选择区域 (仅在提供了 settings_manager 时显示)
        if self.settings_manager:
            if self.mode == "scan":
                self.setup_path_selection(layout)
            elif self.mode == "data":
                self.setup_data_selection(layout)
            
        # 进度条区域 (仅在 show_progress 为 True 时显示)
        if show_progress:
            self.setup_progress_bar(layout)

    def set_icon(self, icon_name):
        # 引导页的小鸟图标需要与文字颜色保持一致，避免出现“图标很亮但文字偏暗”的割裂感
        icon_color = ColorManager.instance().get("theme.text.dark")
        icon_pixmap = qta.icon(icon_name, color=icon_color).pixmap(128, 128)
        self.icon_label.setPixmap(icon_pixmap)

    def update_content(self, title, description, icon_name=None):
        """动态更新页面内容"""
        self.title_label.setText(title)
        self.desc_label.setText(description)
        if icon_name:
            self.set_icon(icon_name)
            
    def restore_default_content(self):
        """恢复默认内容"""
        self.update_content(self.default_title, self.default_desc, self.default_icon)

    def setup_data_selection(self, layout):
        path_container = QWidget()
        cm = ColorManager.instance()
        path_bg = cm.to_qss_color("theme.popup")
        path_border = cm.get("popup.border.primary")
        path_text = cm.get("theme.text.dark")
        browse_bg = cm.get("theme.popup")
        browse_hover_bg = cm.get("theme.primary")
        browse_text = cm.get("theme.text.dark")
        browse_hover_text = cm.get("theme.text.light")
        combo_bg = cm.get("theme.background.light")
        path_container.setStyleSheet(f"""
            QWidget {{
                background-color: {path_bg};
                border-radius: 8px;
                border: 1px solid {path_border};
            }}
        """)
        path_layout = QHBoxLayout(path_container)
        path_layout.setContentsMargins(15, 15, 15, 15)
        
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        from utils.paths import PathManager
        self.path_input.setText(str(PathManager.instance().get_user_data_path()))
        self.path_input.setStyleSheet(f"""
            border: none;
            background: transparent;
            font-size: 14px;
            color: {path_text};
        """)
        
        browse_btn = QPushButton("浏览")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setIcon(qta.icon('mdi6.folder-open', color=browse_text))
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {browse_bg};
                border: 1px solid {path_border};
                border-radius: 4px;
                padding: 6px 15px;
                color: {browse_text};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {browse_hover_bg};
                color: {browse_hover_text};
            }}
        """)
        browse_btn.clicked.connect(self.browse_data_folder)
        
        path_layout.addWidget(self.path_input, 1)
        path_layout.addWidget(browse_btn)
        layout.addWidget(path_container)

    def browse_data_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择数据存储目录", self.path_input.text())
        if folder:
            self.path_input.setText(folder)
            # 检测是否存在已有数据
            self._check_existing_data(folder)

    def _check_existing_data(self, folder):
        """检测目录中是否存在已有数据，如果存在则提示用户"""
        import os
        from PyQt6.QtWidgets import QMessageBox

        # 检查数据库文件
        db_path = os.path.join(folder, "bird_library.db")
        settings_path = os.path.join(folder, "settings.json")

        has_db = os.path.exists(db_path)
        has_settings = os.path.exists(settings_path)

        if has_db or has_settings:
            # 存在已有数据，显示提示
            msg = "检测到该目录存在已有数据：\n\n"
            if has_db:
                msg += f"  • 数据库文件: {db_path}\n"
            if has_settings:
                msg += f"  • 设置文件: {settings_path}\n"
            msg += "\n是否使用之前的数据？\n"
            msg += "选择\"是\"将直接使用之前的数据，跳过扫描步骤。\n"
            msg += "选择\"否\"将重新扫描图片库。"

            reply = QMessageBox.question(
                self,
                "发现已有数据",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                # 用户选择使用之前的数据
                self._use_existing_data = True
                self._existing_data_path = folder
                # 更新说明文字
                self.desc_label.setText("已选择使用之前的数据，将跳过扫描步骤。\n点击\"下一步\"继续。")
            else:
                # 用户选择重新扫描
                self._use_existing_data = False
                self._existing_data_path = None

    def setup_path_selection(self, layout):
        path_container = QWidget()
        cm = ColorManager.instance()
        path_bg = cm.to_qss_color("theme.popup")
        path_border = cm.get("popup.border.primary")
        path_text = cm.get("theme.text.dark")
        browse_bg = cm.get("theme.popup")
        browse_hover_bg = cm.get("theme.primary")
        browse_text = cm.get("theme.text.dark")
        browse_hover_text = cm.get("theme.text.light")
        combo_bg = cm.get("theme.background.light")
        path_container.setStyleSheet(f"""
            QWidget {{
                background-color: {path_bg};
                border-radius: 8px;
                border: 1px solid {path_border};
            }}
        """)
        path_layout = QHBoxLayout(path_container)
        path_layout.setContentsMargins(15, 15, 15, 15)
        
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("请选择图片根目录...")
        self.path_input.setReadOnly(True)
        self.path_input.setStyleSheet(f"""
            border: none;
            background: transparent;
            font-size: 14px;
            color: {path_text};
        """)
        
        browse_btn = QPushButton("浏览")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setIcon(qta.icon('mdi6.folder-open', color=browse_text))
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {browse_bg};
                border: 1px solid {path_border};
                border-radius: 4px;
                padding: 6px 15px;
                color: {browse_text};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {browse_hover_bg};
                color: {browse_hover_text};
            }}
        """)
        browse_btn.clicked.connect(self.browse_folder)
        
        path_layout.addWidget(self.path_input, 1)
        path_layout.addWidget(browse_btn)
        layout.addWidget(path_container)

        exif_container = QWidget()
        exif_layout = QHBoxLayout(exif_container)
        exif_layout.setContentsMargins(0, 0, 0, 0)
        exif_layout.setSpacing(10)
        
        exif_label = QLabel("Exif写入模式:")
        exif_label.setStyleSheet(f"color: {path_text}; font-size: 14px;")
        
        self.exif_mode_combo = QComboBox()
        self.exif_mode_combo.addItem("写入同名XMP文件(推荐)", "xmp")
        self.exif_mode_combo.addItem("写入原始文件", "file")
        self.exif_mode_combo.addItem("不写入任何信息", "none")
        # 使用Base64编码的SVG箭头，避免中文路径问题
        from ui.common.icon_utils import get_arrow_down_svg_base64
        arrow_url = get_arrow_down_svg_base64(path_text)
        self.exif_mode_combo.setStyleSheet(f"""
            QComboBox {{
                padding: 4px 10px;
                border: 1px solid {path_border};
                border-radius: 4px;
                background-color: {combo_bg};
                color: {path_text};
                font-size: 14px;
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
                border: 1px solid {path_border};
                background-color: {combo_bg};
                selection-background-color: {browse_hover_bg};
                selection-color: {browse_hover_text};
                color: {path_text};
            }}
        """)
        
        # 初始化值
        try:
            disable = self.settings_manager.get("exif/disable_write", False)
            mode = self.settings_manager.get("exif/write_mode", "xmp")
            if disable:
                idx = 2 # none
            elif mode == "xmp":
                idx = 0
            else:
                idx = 1
            self.exif_mode_combo.setCurrentIndex(idx)
        except Exception:
            self.exif_mode_combo.setCurrentIndex(0)
            
        self.exif_mode_combo.currentIndexChanged.connect(self._on_exif_mode_changed)
        
        exif_layout.addWidget(exif_label)
        exif_layout.addWidget(self.exif_mode_combo, 1)
        layout.addWidget(exif_container)

        depth_container = QWidget()
        depth_layout = QHBoxLayout(depth_container)
        depth_layout.setContentsMargins(0, 0, 0, 0)
        depth_layout.setSpacing(10)
        depth_label = QLabel("扫描深度:")
        depth_label.setStyleSheet(f"color: {path_text}; font-size: 14px;")
        self.scan_depth_combo = QComboBox()
        self.scan_depth_combo.addItem("不扫描(推荐)", -1)
        self.scan_depth_combo.addItem("不限", 0)
        self.scan_depth_combo.addItem("4层(目科属种)", 4)
        self.scan_depth_combo.addItem("6层", 6)
        self.scan_depth_combo.addItem("8层", 8)
        self.scan_depth_combo.setStyleSheet(f"""
            QComboBox {{
                padding: 6px 10px;
                border: 1px solid {path_border};
                border-radius: 4px;
                background-color: {combo_bg};
                color: {path_text};
                font-size: 14px;
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
                border: 1px solid {path_border};
                background-color: {combo_bg};
                selection-background-color: {browse_hover_bg};
                selection-color: {browse_hover_text};
                color: {path_text};
            }}
        """)
        try:
            cur_depth = int(self.settings_manager.get("library/scan_depth", -1) or -1)
        except Exception:
            cur_depth = -1
        for i in range(self.scan_depth_combo.count()):
            if int(self.scan_depth_combo.itemData(i) or 0) == int(cur_depth):
                self.scan_depth_combo.setCurrentIndex(i)
                break
        self.scan_depth_combo.currentIndexChanged.connect(self._on_scan_depth_changed)
        depth_layout.addWidget(depth_label)
        depth_layout.addWidget(self.scan_depth_combo, 1)
        layout.addWidget(depth_container)

        tip = QLabel("Tip：如果没有以“目-科-属-种”分类的文件夹，建议使用“不扫描”模式，并在导入页面导入到图库。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {path_text}; font-size: 12px;")
        layout.addWidget(tip)

        exclude_title = QLabel("排除目录（不扫描）:")
        exclude_title.setStyleSheet(f"color: {path_text}; font-size: 14px;")
        layout.addWidget(exclude_title)

        excl_container = QWidget()
        excl_layout = QVBoxLayout(excl_container)
        excl_layout.setContentsMargins(0, 0, 0, 0)
        excl_layout.setSpacing(6)

        self.exclude_list = QListWidget()
        self.exclude_list.setStyleSheet(f"""
            QListWidget {{
                border: 1px solid {path_border};
                border-radius: 6px;
                background-color: {browse_bg};
                color: {path_text};
                padding: 4px;
            }}
            QListWidget::item:selected {{
                background-color: {browse_hover_bg};
                color: {browse_hover_text};
            }}
        """)
        self.exclude_list.setMaximumHeight(120)
        excl_layout.addWidget(self.exclude_list)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        add_btn = QPushButton("添加排除目录")
        add_btn.clicked.connect(self._add_exclude_dir)
        remove_btn = QPushButton("移除选中")
        remove_btn.clicked.connect(self._remove_exclude_dir)
        add_btn.setStyleSheet(browse_btn.styleSheet())
        remove_btn.setStyleSheet(browse_btn.styleSheet())
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        excl_layout.addLayout(btn_row)
        layout.addWidget(excl_container)

        self._reload_exclude_dirs()

    def _on_exif_mode_changed(self, index):
        try:
            data = self.exif_mode_combo.currentData()
            if data == "none":
                self.settings_manager.set("exif/disable_write", True)
                self.settings_manager.set("exif/write_mode", "none")
            else:
                self.settings_manager.set("exif/disable_write", False)
                self.settings_manager.set("exif/write_mode", data)
            self.settings_manager.sync()
        except Exception:
            pass

    def _on_scan_depth_changed(self, _):
        try:
            v = int(self.scan_depth_combo.currentData() or 0)
        except Exception:
            v = 0
        try:
            self.settings_manager.set("library/scan_depth", int(v))
            self.settings_manager.sync()
        except Exception:
            pass

    def _reload_exclude_dirs(self):
        self.exclude_list.clear()
        dirs = []
        try:
            dirs = self.settings_manager.get("library/scan_exclude_dirs", []) or []
        except Exception:
            dirs = []
        for p in dirs:
            try:
                txt = str(p)
            except Exception:
                txt = ""
            if not txt:
                continue
            self.exclude_list.addItem(QListWidgetItem(txt))

    def _save_exclude_dirs(self):
        dirs = []
        for i in range(self.exclude_list.count()):
            try:
                t = str(self.exclude_list.item(i).text() or "").strip()
            except Exception:
                t = ""
            if t:
                dirs.append(t)
        try:
            self.settings_manager.set("library/scan_exclude_dirs", dirs)
            self.settings_manager.sync()
        except Exception:
            pass

    def _add_exclude_dir(self):
        try:
            base = self.path_input.text()
        except Exception:
            base = ""
        folder = QFileDialog.getExistingDirectory(self, "选择要排除的目录", base or "")
        if not folder:
            return
        for i in range(self.exclude_list.count()):
            try:
                if os.path.normcase(os.path.normpath(self.exclude_list.item(i).text())) == os.path.normcase(os.path.normpath(folder)):
                    return
            except Exception:
                continue
        self.exclude_list.addItem(QListWidgetItem(folder))
        self._save_exclude_dirs()

    def _remove_exclude_dir(self):
        it = self.exclude_list.currentItem()
        if not it:
            return
        row = self.exclude_list.row(it)
        try:
            self.exclude_list.takeItem(row)
        except Exception:
            pass
        self._save_exclude_dirs()

    def setup_progress_bar(self, layout):
        """设置进度条区域"""
        self.progress_container = QWidget()
        self.progress_container.hide() # 默认隐藏
        progress_layout = QVBoxLayout(self.progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(5)
        
        self.progress_label = QLabel("正在准备...")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cm = ColorManager.instance()
        progress_text = cm.get("theme.text.dark")
        progress_bg = cm.get("theme.popup")
        progress_chunk = cm.get("theme.primary")
        self.progress_label.setStyleSheet(f"color: {progress_text}; font-size: 13px;")
        progress_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {progress_bg};
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {progress_chunk};
                border-radius: 3px;
            }}
        """)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addWidget(self.progress_container)

    def update_progress(self, current, total, message):
        """更新进度条"""
        if not hasattr(self, 'progress_container'):
            return
            
        if not self.progress_container.isVisible():
            self.progress_container.show()
            
        try:
            from utils.system.gpu_utils import get_torch_cuda_check_brief

            gpu_txt = str(get_torch_cuda_check_brief() or "").strip()
        except Exception:
            gpu_txt = ""
        try:
            if gpu_txt and ("GPU检测：" not in str(message)):
                message = f"{message} | GPU检测：{gpu_txt}"
        except Exception:
            pass
        self.progress_label.setText(message)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0) # 忙碌状态

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片根目录", self.path_input.text())
        if folder:
            self.path_input.setText(folder)

    def get_path(self):
        if hasattr(self, 'path_input'):
            return self.path_input.text()
        return None

class GuidePage(QWidget):
    """首次启动引导页面（多页向导模式）"""
    setup_completed = pyqtSignal() # 设置完成信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guidePageRoot")
        self._bg_top_color = QColor("#E3F2FD")
        self._bg_bottom_color = QColor("#FFFFFF")
        self.settings_manager = SettingsManager()
        self.scan_worker = None
        self.is_scanning = False # 显式扫描状态标志
        self.waiting_for_finish = False # 标志位：是否正在等待扫描完成以结束引导
        self.mode = "full"
        self._use_existing_data = False # 是否使用已有数据
        self._existing_data_path = None # 已有数据的路径
            
        self.init_ui()
        
        # 初始化遮罩层
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()

    def set_mode(self, mode):
        if self.mode == mode:
            return
        self.mode = mode
        # Rebuild UI
        # Remove existing layout to rebuild cleanly
        if self.layout():
            QWidget().setLayout(self.layout()) # Trick to delete layout
            
        self.init_ui()
        
        # Resize overlay if exists
        if hasattr(self, 'loading_overlay'):
             self.loading_overlay.raise_()

    def _apply_background(self):
        """
        刷新引导页背景渐变的颜色参数。
        这里不使用 setStyleSheet 来画背景，是因为部分 Qt 样式/平台组合下，
        子控件或样式表可能导致父级背景样式不生效，从而出现“纯白”。
        改为在 paintEvent 中用 QPainter 直接绘制，可以避免样式优先级问题。
        """
        cm = ColorManager.instance()
        top_color = cm.get("theme.sidebar", "#E3F2FD")
        bottom_color = "#FFFFFF"
        try:
            self._bg_top_color = QColor(str(top_color))
        except Exception:
            self._bg_top_color = QColor("#E3F2FD")
        try:
            self._bg_bottom_color = QColor(str(bottom_color))
        except Exception:
            self._bg_bottom_color = QColor("#FFFFFF")
        self.update()

    def paintEvent(self, event):
        """
        绘制整页的背景渐变。
        采用 paintEvent 绘制是为了保证在任何样式表/主题切换/控件覆盖场景下，
        背景依然稳定显示，不会退化成纯白。
        """
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, self._bg_top_color)
            gradient.setColorAt(1.0, self._bg_bottom_color)
            painter.fillRect(self.rect(), gradient)
        except Exception:
            pass
        super().paintEvent(event)

    def init_ui(self):
        cm = ColorManager.instance()
        self._apply_background()
        try:
            ColorManager.instance().register_listener(self._apply_background)
        except Exception:
            pass
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 居中容器（限制最大宽度）
        center_container = QWidget()
        center_container.setFixedWidth(800)
        # 让中间容器背景透明，显示父级渐变
        center_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        center_container.setAutoFillBackground(False)
        center_container.setStyleSheet("background: transparent;")
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 40, 0, 40)
        center_layout.setSpacing(20)

        # 页面堆栈
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.stacked_widget.setAutoFillBackground(False)
        self.stacked_widget.setStyleSheet("background: transparent;")
        
        # 页码 1: 数据存储位置页
        self.data_page = IntroPage(
            "数据存储位置",
            "选择您的个人数据（设置、数据库、收藏等）保存位置。\n默认为文档目录下的 BirdManager/data。",
            "mdi6.database",
            settings_manager=self.settings_manager,
            mode="data"
        )
        self.stacked_widget.addWidget(self.data_page)

        if self.mode == "full":
            # 页码 2: 欢迎页 + 路径选择
            app_name = AppInfoManager.instance().get_app_name()
            self.intro_page = IntroPage(
                f"欢迎使用{app_name}",
                "这是一款专为鸟类摄影爱好者设计的图片管理工具\n请先选择您的图片库根目录，以便我为您建立索引!",
                "ph.bird-fill",
                settings_manager=self.settings_manager # 传入 settings_manager 以启用路径选择
            )
            self.stacked_widget.addWidget(self.intro_page)
            
            # 页码 2~7: 功能亮点介绍
            self.stacked_widget.addWidget(IntroPage(
                "智能分类",
                "支持按科、属、种层级自动分类管理。\n告别混乱的文件夹，让每一张照片都有迹可循。",
                "mdi6.file-tree"
            ))
            
            self.stacked_widget.addWidget(IntroPage(
                "快速筛图",
                "支持显示主体框与对焦点，结合阈值面板快速区分清晰/虚焦。\n把时间留给好照片。",
                "mdi6.image-search"
            ))

            self.stacked_widget.addWidget(IntroPage(
                "对焦检测",
                "在导入页一键启动对焦检测：连拍/相似度/爆框等多种策略可选。\n检测结果可用于快速筛选与批量处理。",
                "mdi6.focus-field"
            ))

            self.stacked_widget.addWidget(IntroPage(
                "大图浏览",
                "支持放大镜、对比模式、主体检测与聚焦。\n用快捷键快速翻片、评分、上色标。",
                "mdi6.magnify"
            ))

            # 删除了喷漆工具和高度可定制页面

            # 最后一页: 准备就绪 + 进度条
            self.ready_page = IntroPage(
                "准备就绪",
                "一切准备就绪，点击“开始使用”开启您的鸟类摄影之旅！",
                "mdi6.check-circle-outline",
                show_progress=True # 启用进度条
            )
            self.stacked_widget.addWidget(self.ready_page)
        
        center_layout.addWidget(self.stacked_widget)
        
        # 底部导航栏
        nav_bar = QHBoxLayout()
        nav_bar.setContentsMargins(40, 20, 40, 20)
        
        # 移除了跳过按钮
        
        # 左侧占位（用于平衡右侧按钮，使中间指示器居中）
        # 但由于右侧按钮宽度不固定，简单的 addStretch 可能无法完美居中
        # 更好的方法是使用三栏布局：左（空）、中（指示器）、右（按钮）
        
        # 左侧容器（空）
        left_container = QWidget()
        nav_bar.addWidget(left_container, 1)
        
        # 指示器（简单的圆点）
        self.indicator_layout = QHBoxLayout()
        self.indicators = []
        indicator_color = cm.get("theme.text.dark")
        for i in range(self.stacked_widget.count()):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {indicator_color}; font-size: 12px; background: transparent;")
            self.indicator_layout.addWidget(dot)
            self.indicators.append(dot)
        
        # 中间容器（包含指示器，居中）
        center_indicator_widget = QWidget()
        center_indicator_layout = QHBoxLayout(center_indicator_widget)
        center_indicator_layout.setContentsMargins(0, 0, 0, 0)
        center_indicator_layout.addLayout(self.indicator_layout)
        nav_bar.addWidget(center_indicator_widget, 0, Qt.AlignmentFlag.AlignCenter)
        
        # 右侧容器（按钮）
        right_container = QWidget()
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.prev_btn = QPushButton("上一步")
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        prev_bg = cm.to_qss_color("guide.nav.prev.background")
        prev_hover_bg = cm.to_qss_color("guide.nav.prev.hover_background")
        prev_text = cm.get("theme.text.dark")
        prev_border = cm.get("popup.border.primary")
        self.prev_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {prev_bg};
                color: {prev_text};
                border: 1px solid {prev_border};
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {prev_hover_bg};
            }}
        """)
        self.prev_btn.clicked.connect(self.on_prev_clicked)
        right_layout.addWidget(self.prev_btn)
        
        self.next_btn = QPushButton("下一步")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_bg = cm.get("theme.primary")
        next_text = cm.get("theme.text.light")
        self.next_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {next_bg};
                color: {next_text};
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {next_bg};
            }}
        """)
        self.next_btn.clicked.connect(self.on_next_clicked)
        right_layout.addWidget(self.next_btn)
        
        nav_bar.addWidget(right_container, 1) # 右侧容器占比 1，与左侧平衡
        
        center_layout.addLayout(nav_bar)
        
        # 添加弹簧使内容水平居中
        main_layout.addStretch()
        main_layout.addWidget(center_container, 0, Qt.AlignmentFlag.AlignHCenter)
        main_layout.addStretch()

        # 初始化状态
        self.update_nav_buttons()
        self.stacked_widget.currentChanged.connect(self.update_nav_buttons)

    def resizeEvent(self, event):
        self._apply_background()
        
        # 调整遮罩层大小
        if hasattr(self, 'loading_overlay'):
             self.loading_overlay.resize(self.size())
             
        super().resizeEvent(event)

    def update_nav_buttons(self):
        idx = self.stacked_widget.currentIndex()
        count = self.stacked_widget.count()
        
        # 更新按钮状态
        is_last = idx == count - 1
        self.prev_btn.setEnabled((idx > 0) and (not is_last))
        self.prev_btn.setVisible((idx > 0) and (not is_last))
        
        if is_last:
            self.next_btn.setText("开始使用" if self.mode == "full" else "完成")
            # 如果正在扫描，显示扫描状态，隐藏“开始使用”按钮
            # 使用显式标志位判断，比 isRunning 更可靠且无延迟
            if self.is_scanning:
                self.next_btn.setVisible(False)
                if hasattr(self, 'ready_page'):
                    self.ready_page.update_content(
                        "正在建立索引", 
                        "正在为您扫描图片库并建立索引，请稍候...", 
                        "mdi6.database-sync"
                    )
            else:
                self.next_btn.setVisible(True)
                self.next_btn.setEnabled(True)
                if hasattr(self, 'ready_page'):
                    self.ready_page.restore_default_content()
        else:
            self.next_btn.setText("下一步")
            self.next_btn.setVisible(True)
            self.next_btn.setEnabled(True)
            
        # 更新指示器
        active_color = ColorManager.instance().get("theme.primary")
        inactive_color = ColorManager.instance().get("theme.text.dark")
        for i, dot in enumerate(self.indicators):
            if i == idx:
                dot.setStyleSheet(f"color: {active_color}; font-size: 12px; background: transparent;")
            else:
                dot.setStyleSheet(f"color: {inactive_color}; font-size: 12px; background: transparent;")

    def on_prev_clicked(self):
        idx = self.stacked_widget.currentIndex()
        if idx > 0:
            self.stacked_widget.setCurrentIndex(idx - 1)

    def on_next_clicked(self):
        idx = self.stacked_widget.currentIndex()
        count = self.stacked_widget.count()
        
        # Page 0: Data Path
        if idx == 0:
            path = self.data_page.path_input.text()
            if not path:
                NotificationManager.instance().show_warning("提示", "请选择数据存储目录")
                return
            
            from utils.paths import PathManager
            PathManager.instance().set_user_data_path(path)
            
            # Update Managers
            from ui.utils.color_manager import ColorManager
            from ui.utils.shortcut_manager import ShortcutManager
            
            pm = PathManager.instance()
            
            # ColorManager
            cm = ColorManager.instance()
            cm._config_path = str(pm.get_user_colors_path())
            cm.reload()
            
            # ShortcutManager
            sm = ShortcutManager.instance()
            sm.config_path = str(pm.get_user_shortcuts_path())
            sm.load_shortcuts()

        # Page 1: Picture Path
        elif idx == 1:
            path = self.intro_page.get_path()
            if not path or not os.path.exists(path):
                NotificationManager.instance().show_warning("提示", "请先选择有效的图片根目录")
                return
            # 检查是否使用已有数据
            if getattr(self.data_page, '_use_existing_data', False):
                # 使用已有数据，跳过扫描
                self._use_existing_data = True
                self._existing_data_path = self.data_page._existing_data_path
                # 直接跳到最后一页
                self.stacked_widget.setCurrentIndex(self.stacked_widget.count() - 1)
                # 更新最后一页显示
                if hasattr(self, 'ready_page'):
                    self.ready_page.update_content(
                        "准备就绪",
                        "已加载之前的数据，点击\"开始使用\"继续。",
                        "mdi6.check-circle-outline"
                    )
                    self.ready_page.restore_default_content()
                return
            # 启动后台扫描
            self.start_background_scan(path)

        if idx < count - 1:
            self.stacked_widget.setCurrentIndex(idx + 1)
        else:
            # 最后一页，完成设置
            self.finish_setup()

    def start_background_scan(self, path):
        """启动后台扫描任务"""
        # 如果有旧任务在运行，先停止
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.scan_worker.wait()
            
        self.is_scanning = True # 标记开始扫描
        self.scan_worker = ScanWorker(path)
        self.scan_worker.progress_updated.connect(self.on_scan_progress)
        self.scan_worker.scan_finished.connect(self.on_scan_finished)
        self.scan_worker.start()
        
        # 立即刷新按钮状态（如果当前就在最后一页）
        self.update_nav_buttons()

    def on_scan_progress(self, current, total, message):
        # 优先更新 ready_page 上的进度条
        if hasattr(self, 'ready_page'):
            self.ready_page.update_progress(current, total, message)
            
        # 同时更新 loading_overlay (如果显示)
        if self.loading_overlay.isVisible():
            self.loading_overlay.update_progress(current, total, message)
        
    def on_scan_finished(self):
        # 扫描完成
        self.is_scanning = False # 标记扫描结束
        
        if self.loading_overlay.isVisible():
             self.loading_overlay.hide()
             
        # 更新 ready_page 状态
        if hasattr(self, 'ready_page'):
            self.ready_page.update_progress(100, 100, "扫描完成")
            self.ready_page.restore_default_content()
        
        # 更新按钮状态（显示并启用“开始使用”）
        if self.stacked_widget.currentIndex() == self.stacked_widget.count() - 1:
            self.next_btn.setVisible(True)
            self.next_btn.setEnabled(True)
        
        # 如果用户之前点击了完成，但被阻断了，现在继续完成流程
        if self.waiting_for_finish:
            self.finish_setup_internal()

    def on_skip_clicked(self):
        pass # 跳过按钮已移除

    def finish_setup(self):
        if self.mode == "full":
            # 如果使用已有数据，不需要检查图片根目录
            if not self._use_existing_data:
                path = self.intro_page.get_path()
                if not path:
                    NotificationManager.instance().show_warning("提示", "请先选择根目录")
                    return

                if not os.path.exists(path):
                    NotificationManager.instance().show_warning("错误", "所选路径不存在")
                    return

            # 检查是否正在扫描（仅当不使用已有数据时）
            if not self._use_existing_data and self.scan_worker and self.scan_worker.isRunning():
                # 关键：转移 ScanWorker 的所有权，防止 GuidePage 销毁时线程被杀
                self.scan_worker.setParent(None)

        self.finish_setup_internal()

    def finish_setup_internal(self):
        """实际执行完成设置的逻辑"""
        if self.mode == "full":
            # 备份关键配置
            exclude_dirs = self.settings_manager.get("library/scan_exclude_dirs", [])
            exclude_regex = self.settings_manager.get("library/scan_exclude_regex", "")

            if self._use_existing_data:
                # 使用已有数据，不清除配置，直接从设置文件中读取根目录
                try:
                    path = self.settings_manager.get("general/root_path", "")
                except Exception:
                    path = ""
                if not path:
                    # 如果设置中没有根目录，尝试从数据库中推断
                    NotificationManager.instance().show_warning("提示", "无法确定图片库根目录，请手动选择")
                    return
            else:
                # 新数据，需要清除旧配置
                path = self.intro_page.get_path()

                # 在应用新设置前，先清除所有旧配置
                self.settings_manager.settings.clear()

                # 恢复关键配置
                if exclude_dirs:
                    self.settings_manager.set("library/scan_exclude_dirs", exclude_dirs)
                if exclude_regex:
                    self.settings_manager.set("library/scan_exclude_regex", exclude_regex)

                # 保存设置
                self.settings_manager.set("general/root_path", path)

            # 标记不再是首次运行
            self.settings_manager.set("general/first_run", False)

        self.settings_manager.sync() # 强制写入磁盘

        # 发送完成信号
        self.setup_completed.emit()
