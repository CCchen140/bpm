from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel, QSlider, QFrame, QStyledItemDelegate, QToolButton, QMenu, QInputDialog, QApplication)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QPoint, QRect, QEvent
from PyQt6.QtGui import QPainter, QAction
from ui.utils.icon_loader import qta
from ui.common.base_toolbar import BaseToolbar
from ui.common.styles import TOOLBAR_BTN_STYLE
from ui.utils.color_manager import ColorManager
from ui.widgets.rating_filter_button import RatingFilterButton
from ui.widgets.rating_filter_widget import StarRatingWidget, StarMenuAction
from ui.widgets.advanced_filter_panel import AdvancedFilterPanel
from ui.widgets.themed_combo_box import ThemedComboBox

class SortDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, combo=None):
        super().__init__(parent)
        self.combo = combo

    def paint(self, painter, option, index):
        # 显式处理分割线绘制
        # 兼容性修复：使用 AccessibleDescriptionRole 判断分割线，避免 ItemFlag 属性错误
        is_separator = False
        try:
            if str(index.data(Qt.ItemDataRole.AccessibleDescriptionRole)) == "separator":
                is_separator = True
        except:
            pass
            
        if is_separator:
            painter.save()
            r = option.rect
            y = r.center().y()
            # 绘制灰色分割线
            painter.setPen(Qt.GlobalColor.lightGray)
            painter.drawLine(r.left() + 5, y, r.right() - 5, y)
            painter.restore()
            return

        super().paint(painter, option, index)
        
        text = index.data(Qt.ItemDataRole.DisplayRole)
        sort_order = self.combo.property("sort_order") if self.combo else None
        
        if (text == "递增" and sort_order == "asc") or \
           (text == "递减" and sort_order == "desc"):
            
            painter.save()
            # Draw a simple dot indicator
            r = option.rect
            dot_size = 6
            # Right aligned with some padding
            dot_rect = QRect(r.right() - 25, r.top() + (r.height() - dot_size) // 2, dot_size, dot_size)
            
            # Use text color for the dot to match theme
            text_color = option.palette.text().color()
            painter.setBrush(text_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot_rect)
            
            painter.restore()

class ToolbarView(BaseToolbar):
    # 信号定义
    newFolderRequested = pyqtSignal()
    renameRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    compareRequested = pyqtSignal()
    favToggled = pyqtSignal(bool)
    ratingOperatorChanged = pyqtSignal() # 具体的 operator 状态由调用者通过 getter 获取
    ratingChanged = pyqtSignal(int)
    advancedSearchRequested = pyqtSignal(list)
    saveFilterRequested = pyqtSignal()
    loadFilterRequested = pyqtSignal()
    viewModeChanged = pyqtSignal(int)
    sortModeChanged = pyqtSignal(int) # index
    thumbnailSizeChanged = pyqtSignal(int)
    sprayModeChanged = pyqtSignal(bool, str, object) # active, type, value

    def __init__(self, parent=None, settings_manager=None, config=None):
        self.settings_manager = settings_manager
        self.config = config or {}
        super().__init__(parent)
        self.setup_ui()
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()
        try:
            QApplication.instance().installEventFilter(self)
        except Exception:
            pass

    def setup_ui(self):
        self.setup_file_actions()
        if self.config.get("show_spray", True):
            self.setup_spray_tool()
            self.add_separator()
        self.setup_filter_actions()
        if not bool(self.config.get("compact_quick_filter_spacing", False)):
            self.add_separator()
        self.setup_view_actions()

    def setup_spray_tool(self):
        ICON_SIZE = 22
        BTN_SIZE = 32
        
        self.spray_btn = QToolButton()
        try:
            self.spray_btn.setIcon(qta.icon('fa5s.spray-can', color=ColorManager.instance().get("theme.text.dark")))
        except Exception:
            try:
                self.spray_btn.setIcon(qta.icon('mdi6.spray-can', color=ColorManager.instance().get("theme.text.dark")))
            except Exception:
                try:
                    self.spray_btn.setIcon(qta.icon('mdi6.spray-can-variant', color=ColorManager.instance().get("theme.text.dark")))
                except Exception:
                    self.spray_btn.setIcon(qta.icon('mdi6.spray', color=ColorManager.instance().get("theme.text.dark")))
        self.spray_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.spray_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
        self.spray_btn.setToolTip("喷漆工具 (点击开启/关闭，下拉选择模式)")
        self.spray_btn.setCheckable(True)
        self.spray_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        
        # Menu
        self.spray_menu = QMenu(self)
        
        # 1. 收藏 (Favorite)
        fav_menu = self.spray_menu.addMenu("收藏")
        
        action_fav_true = fav_menu.addAction(qta.icon('mdi6.heart', color='#e74c3c'), "收藏")
        action_fav_true.triggered.connect(lambda: self.set_spray_action('favorite', True))
        
        action_fav_false = fav_menu.addAction(qta.icon('mdi6.heart-outline', color='#999'), "取消收藏")
        action_fav_false.triggered.connect(lambda: self.set_spray_action('favorite', False))

        if bool((self.config or {}).get("show_stash", True)):
            stash_menu = self.spray_menu.addMenu("暂存")
            action_stash_true = stash_menu.addAction(qta.icon('mdi6.tag-check', color='#4CAF50'), "暂存")
            action_stash_true.triggered.connect(lambda: self.set_spray_action('stash', True))
            action_stash_false = stash_menu.addAction(qta.icon('mdi6.tag-remove', color='#999'), "取消暂存")
            action_stash_false.triggered.connect(lambda: self.set_spray_action('stash', False))
        
        # 2. 色标 (Label)
        label_menu = self.spray_menu.addMenu("色标")
        
        # Use same colors as elsewhere
        labels = [("Red", "红色", "#e74c3c"), ("Orange", "橙色", "#e67e22"), ("Yellow", "黄色", "#f1c40f"), 
                 ("Green", "绿色", "#27ae60"), ("Cyan", "青色", "#1abc9c"), ("Blue", "蓝色", "#2980b9"), 
                 ("Purple", "紫色", "#9b59b6"), ("Pink", "粉色", "#fd79a8"), ("White", "白色", "#ecf0f1"), 
                 ("Gray", "灰色", "#95a5a6"), ("Black", "黑色", "#34495e"), ("", "无色标", "#bdc3c7")]
        
        for en, cn, color_hex in labels:
            icon = qta.icon('mdi6.circle', color=color_hex) if en else qta.icon('mdi6.circle-outline', color='#999')
            action = label_menu.addAction(icon, cn)
            action.triggered.connect(lambda checked=False, val=en: self.set_spray_action('label', val))
            
        # 3. 评分 (Rating)
        rating_menu = self.spray_menu.addMenu("评分")
        
        action_rating_0 = rating_menu.addAction(qta.icon('mdi6.star-outline', color='#999'), "清除评分")
        action_rating_0.triggered.connect(lambda: self.set_spray_action('rating', 0))
        
        for i in range(1, 6):
            action = StarMenuAction(i, rating_menu)
            action.triggered_rating.connect(lambda val: self.set_spray_action('rating', val))
            rating_menu.addAction(action)
            
        # 4. 标签 (Tag)
        tag_menu = self.spray_menu.addMenu("标签")
        
        action_set_tag = tag_menu.addAction(qta.icon('mdi6.tag-plus', color='#555'), "设置标签...")
        action_set_tag.triggered.connect(self.on_set_tag_clicked)

        self.spray_btn.setMenu(self.spray_menu)
        
        self.current_spray_action = None
        self.add_widget(self.spray_btn)
        
    def on_set_tag_clicked(self):
        from ui.dialogs.spray_tag_selection_dialog import SprayTagSelectionDialog
        from utils.tag_manager import TagManager
        
        dialog = SprayTagSelectionDialog(self)
        
        def on_tags_selected(tags, is_append):
            # tags is a list of strings
            if not tags and not is_append:
                # "Clear all" case: tags=[], is_append=False -> overwrite with empty
                value = {'tags': '', 'mode': 'overwrite'}
                self.set_spray_action('tag', value)
            elif tags:
                tags_str = "|".join(tags)
                mode = 'append' if is_append else 'overwrite'
                value = {'tags': tags_str, 'mode': mode}
                self.set_spray_action('tag', value)
            else:
                # tags=[], is_append=True -> No-op? Or just keep existing?
                # User likely didn't select anything but clicked OK?
                # If they clicked OK with empty selection in append mode, it does nothing.
                pass
                
        dialog.tagsSelected.connect(on_tags_selected)
        dialog.exec()

    def set_spray_action(self, action_type, value):
        self.current_spray_action = (action_type, value)
        self.spray_btn.setChecked(True)
        # Update tooltip or icon to show current action?
        # Maybe change icon color?
        self.sprayModeChanged.emit(True, action_type, value)

    def deactivate_spray_mode(self):
        self.spray_btn.setChecked(False)
        self.sprayModeChanged.emit(False, "", None)
        
    def toggle_spray_mode(self):
        is_checked = self.spray_btn.isChecked()
        if is_checked:
            if not self.current_spray_action:
                self.spray_btn.showMenu()
                self.spray_btn.setChecked(False)
                return
            
            action_type, value = self.current_spray_action
            self.sprayModeChanged.emit(True, action_type, value)
        else:
            self.sprayModeChanged.emit(False, "", None)

    def setup_file_actions(self):
        ICON_SIZE = 22
        BTN_SIZE = 32
        
        # New Folder
        if self.config.get('show_new_folder', True):
            self.new_folder_btn = QPushButton()
            self.new_folder_btn.setIcon(qta.icon('mdi6.folder-plus', color='#555', options=[{'scale_factor': 1.1}]))
            self.new_folder_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.new_folder_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            self.new_folder_btn.setToolTip("新建文件夹")
            self.new_folder_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.new_folder_btn.clicked.connect(self.newFolderRequested.emit)
            self.add_widget(self.new_folder_btn)
        
        # Rename
        if self.config.get('show_rename', True):
            self.rename_btn = QPushButton()
            self.rename_btn.setIcon(qta.icon('mdi6.rename-box', color='#555', options=[{'scale_factor': 1.1}]))
            self.rename_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.rename_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            self.rename_btn.setToolTip("批量重命名")
            self.rename_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.rename_btn.clicked.connect(self.renameRequested.emit)
            self.add_widget(self.rename_btn)
        
        # Delete
        if self.config.get('show_delete', True):
            self.delete_btn = QPushButton()
            self.delete_btn.setIcon(qta.icon('mdi6.trash-can-outline', color='#555', options=[{'scale_factor': 1.1}]))
            self.delete_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.delete_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            self.delete_btn.setToolTip("删除")
            self.delete_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    padding: 4px;
                }
                QPushButton:hover {
                    background-color: #ffcccc;
                }
                QPushButton:pressed {
                    background-color: #ff9999;
                }
            """)
            self.delete_btn.clicked.connect(self.deleteRequested.emit)
            self.add_widget(self.delete_btn)

        # Compare
        if self.config.get('show_compare', True):
            self.compare_btn = QPushButton()
            self.compare_btn.setIcon(qta.icon('mdi6.compare', color='#555', options=[{'scale_factor': 1.1}]))
            self.compare_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.compare_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            self.compare_btn.setToolTip("对比 (选中2张图片)")
            self.compare_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.compare_btn.clicked.connect(self.compareRequested.emit)
            self.add_widget(self.compare_btn)

    def setup_filter_actions(self):
        ICON_SIZE = 22
        BTN_SIZE = 32

        # Fav
        if self.config.get('show_fav', True):
            self.fav_btn = QPushButton()
            self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
            self.fav_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.fav_btn.setCheckable(True)
            self.fav_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            self.fav_btn.setToolTip("收藏")
            self.fav_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    padding: 4px;
                }
                QPushButton:hover {
                    background-color: #ffe0e0;
                }
            """)
            self.fav_btn.toggled.connect(self._on_fav_btn_toggled)
            self.add_widget(self.fav_btn)

        # Rating Group
        if self.config.get('show_rating', True):
            rating_group = QWidget()
            rating_group.setStyleSheet("background: transparent; border: none;") # 确保背景透明
            rating_group_layout = QHBoxLayout(rating_group)
            rating_group_layout.setContentsMargins(0, 0, 0, 0)
            rating_group_layout.setSpacing(4)
            
            self.rating_filter_btn = RatingFilterButton()
            self.rating_filter_btn.clicked.connect(self.ratingOperatorChanged.emit)
            rating_group_layout.addWidget(self.rating_filter_btn)
            
            self.star_rating = StarRatingWidget(size=28, font_size=20)
            self.star_rating.ratingChanged.connect(self.ratingChanged.emit)
            rating_group_layout.addWidget(self.star_rating)
            
            self.add_widget(rating_group)
        
        if self.config.get('show_rating', True) and self.config.get('show_filter', True):
            if not bool(self.config.get("compact_quick_filter_spacing", False)):
                self.add_separator()
        
        # Filter
        if self.config.get('show_filter', True):
            self.filter_btn = QPushButton()
            try:
                icon_color = ColorManager.instance().get("theme.text.dark")
            except Exception:
                icon_color = "#555"
            self.filter_btn.setIcon(qta.icon('mdi6.filter-outline', color=icon_color, options=[{'scale_factor': 1.1}]))
            self.filter_btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            self.filter_btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            self.filter_btn.setToolTip("快速过滤")
            self.filter_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.filter_btn.setCheckable(True)
            self.filter_btn.toggled.connect(self.toggle_filter_panel)
            self.add_widget(self.filter_btn)
            
            # Filter Panel
            filter_class = self.config.get('filter_panel_class', AdvancedFilterPanel)
            if filter_class:
                # 不指定父对象，由外部布局管理
                self.filter_panel = filter_class() 
                self.filter_panel.hide()
                # Connect signals if they exist
                if hasattr(self.filter_panel, 'search_requested'):
                    self.filter_panel.search_requested.connect(self.advancedSearchRequested.emit)
                if hasattr(self.filter_panel, 'save_requested'):
                    self.filter_panel.save_requested.connect(self.saveFilterRequested.emit)
                if hasattr(self.filter_panel, 'load_requested'):
                    self.filter_panel.load_requested.connect(self.loadFilterRequested.emit)

    def setup_view_actions(self):
        ICON_SIZE = 22
        BTN_SIZE = 32

        # View Mode
        if self.config.get('show_view_mode', True):
            view_icon = QLabel()
            view_icon.setPixmap(qta.icon('mdi6.view-grid', color=ColorManager.instance().get("theme.text.dark"), options=[{'scale_factor': 1.1}]).pixmap(ICON_SIZE, ICON_SIZE))
            view_icon.setFixedSize(ICON_SIZE, ICON_SIZE)
            view_icon.setStyleSheet("background: transparent; border: none;")
            self.view_icon = view_icon
            self.add_widget(self.view_icon)
            
            self.view_combo = ThemedComboBox(font_size=12, padding="4px 8px")
            view_options = self.config.get('view_options', ["仅缩略图", "缩略图+文件名", "缩略图+详情"])
            self.view_combo.addItems(view_options)
            if self.settings_manager:
                setting_key = self.config.get("view_mode_setting_key", "library/view_mode")
                self.view_combo.setCurrentIndex(self.settings_manager.get(setting_key, 1))
            self.view_combo.setToolTip("显示格式")
            self.view_combo.currentIndexChanged.connect(self.viewModeChanged.emit)
            self.add_widget(self.view_combo)
        
        # Sort Mode
        if self.config.get('show_sort', True):
            sort_icon = QLabel()
            sort_icon.setPixmap(qta.icon('mdi6.sort', color=ColorManager.instance().get("theme.text.dark"), options=[{'scale_factor': 1.1}]).pixmap(ICON_SIZE, ICON_SIZE))
            sort_icon.setFixedSize(ICON_SIZE, ICON_SIZE)
            sort_icon.setStyleSheet("background: transparent; border: none;")
            self.sort_icon = sort_icon
            self.add_widget(self.sort_icon)
            
            self.sort_combo = ThemedComboBox(font_size=12, padding="4px 8px")
            # 移除“分数”选项
            sort_options = self.config.get('sort_options', ["文件名", "拍摄时间", "评分", "物种", "文件大小", "ISO"])
            # 确保彻底过滤掉“分数”，防止从旧配置中读取到
            if "分数" in sort_options:
                sort_options = [opt for opt in sort_options if opt != "分数"]
                
            self.sort_combo.addItems(sort_options)
            self.sort_combo.insertSeparator(self.sort_combo.count())
            self.sort_combo.addItems(["递增", "递减"])
            self.sort_combo.setToolTip("排序方式")
            
            # 设置自定义 Delegate 以显示排序方向标记
            self.sort_combo.setItemDelegate(SortDelegate(self.sort_combo, self.sort_combo))
            
            self.sort_combo.currentIndexChanged.connect(self.sortModeChanged.emit)
            self.add_widget(self.sort_combo)
        
        self.add_stretch()
        
        # Zoom Slider
        if self.config.get('show_slider', True):
            self.thumbnail_size_btn = QPushButton()
            self.thumbnail_size_btn.setFixedSize(32, 32)
            self.thumbnail_size_btn.setToolTip("缩略图大小")
            self.thumbnail_size_btn.setStyleSheet(TOOLBAR_BTN_STYLE)
            self.thumbnail_size_btn.setCheckable(True)
            self.thumbnail_size_btn.toggled.connect(self.toggle_thumbnail_size_panel)
            self.add_widget(self.thumbnail_size_btn)

            parent_widget = self.parent() or self
            self.thumbnail_size_panel = QFrame(parent_widget)
            self.thumbnail_size_panel.setFixedWidth(320)
            self.thumbnail_size_panel.setFixedHeight(52)
            self.thumbnail_size_panel.hide()
            layout = QHBoxLayout(self.thumbnail_size_panel)
            layout.setContentsMargins(12, 6, 12, 6)
            layout.setSpacing(8)

            self.preview_slider = QSlider(Qt.Orientation.Horizontal)
            self.preview_slider.setMinimum(0)
            self.preview_slider.setMaximum(200)
            self.preview_slider.setValue(0)
            self.preview_slider.setFixedHeight(36)
            self.preview_slider.valueChanged.connect(self.thumbnailSizeChanged.emit)
            layout.addWidget(self.preview_slider)

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        text_dark = cm.get("theme.text.dark")
        hover_bg = cm.get("theme.background.dark")
        checked_bg = cm.get("theme.primary")
        border = cm.get("popup.border.primary")
        menu_bg = cm.get("theme.background.light")
        menu_text = cm.get("theme.text.dark")
        menu_hover = cm.get("theme.background.dark")
        tooltip_bg = cm.get("theme.text.light")
        tooltip_text = cm.get("tooltip.text")
        tooltip_border = cm.get("tooltip.border")
        spray_btn = getattr(self, "spray_btn", None)
        if spray_btn is not None:
            spray_btn.setIcon(qta.icon('fa5s.spray-can', color=text_dark))
            spray_btn.setStyleSheet(f"""
                QToolButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                }}
                QToolButton:hover {{
                    background-color: {hover_bg};
                }}
                QToolButton:checked {{
                    background-color: {checked_bg};
                    border: 1px solid {border};
                }}
                QToolButton::menu-indicator {{
                    image: none;
                }}
                QToolTip {{
                    color: {tooltip_text};
                    background-color: {tooltip_bg};
                    border: 1px solid {tooltip_border};
                }}
            """)
        spray_menu = getattr(self, "spray_menu", None)
        if spray_menu:
            spray_menu.setStyleSheet(f"""
                    QMenu {{
                        background-color: {menu_bg};
                        border: 1px solid {border};
                        border-radius: 4px;
                        padding: 4px;
                    }}
                    QMenu::item {{
                        padding: 6px 24px 6px 36px;
                        border-radius: 2px;
                        color: {menu_text};
                    }}
                    QMenu::item:selected {{
                        background-color: {menu_hover};
                        color: {menu_text};
                    }}
                    QMenu::separator {{
                        height: 1px;
                        background: {border};
                        margin: 2px 4px;
                    }}
                """)
        if getattr(self, "view_icon", None):
            self.view_icon.setPixmap(qta.icon('mdi6.view-grid', color=text_dark, options=[{'scale_factor': 1.1}]).pixmap(22, 22))
        if getattr(self, "sort_icon", None):
            self.sort_icon.setPixmap(qta.icon('mdi6.sort', color=text_dark, options=[{'scale_factor': 1.1}]).pixmap(22, 22))
        if getattr(self, "thumbnail_size_btn", None):
            try:
                color = cm.get("theme.primary") if bool(self.thumbnail_size_btn.isChecked()) else text_dark
            except Exception:
                color = text_dark
            try:
                self.thumbnail_size_btn.setIcon(qta.icon("mdi.image-size-select-large", color=color, options=[{"scale_factor": 1.1}]))
            except Exception:
                pass
            self.thumbnail_size_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                }}
                QPushButton:pressed {{
                    background-color: {hover_bg};
                }}
                QPushButton:checked {{
                    background-color: {hover_bg};
                    border: 1px solid {border};
                }}
            """)
        if getattr(self, "thumbnail_size_panel", None):
            try:
                panel_bg = cm.get("theme.background.light")
            except Exception:
                panel_bg = "#ffffff"
            self.thumbnail_size_panel.setStyleSheet(f"""
                QFrame {{
                    background-color: {panel_bg};
                    border: 1px solid {border};
                    border-radius: 8px;
                }}
            """)
        if getattr(self, "preview_slider", None) is not None:
            slider_bg = cm.get("theme.background.primary")
            slider_groove = cm.get("theme.background.dark")
            slider_handle = cm.get("theme.primary")
            slider_handle_hover = cm.get("theme.primary")
            slider_sub = cm.get("theme.primary")
            slider_add = cm.get("theme.background.light")
            self.preview_slider.setStyleSheet(f"""
                QSlider {{
                    background: {slider_bg};
                }}
                QSlider::groove:horizontal {{
                    border: none;
                    height: 6px;
                    background: {slider_groove};
                    margin: 15px 0;
                }}
                QSlider::handle:horizontal {{
                    width: 12px;
                    height: 20px;
                    background: {slider_handle};
                    border-radius: 2px;
                    margin: -7px 0;
                }}
                QSlider::handle:horizontal:hover {{
                    background: {slider_handle_hover};
                }}
                QSlider::sub-page:horizontal {{
                    background: {slider_sub};
                    height: 6px;
                    margin: 15px 0;
                }}
                QSlider::add-page:horizontal {{
                    background: {slider_add};
                    height: 6px;
                    margin: 15px 0;
                }}
            """)
        
        # Apply tooltip styles to all buttons
        tooltip_style = f"""
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
            }}
        """
        
        # File action buttons
        if getattr(self, "new_folder_btn", None):
            try:
                self.new_folder_btn.setIcon(qta.icon('mdi6.folder-plus', color=text_dark, options=[{'scale_factor': 1.1}]))
            except Exception:
                pass
            self.new_folder_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                }}
                QPushButton:pressed {{
                    background-color: {hover_bg};
                }}
                {tooltip_style}
            """)
        if getattr(self, "rename_btn", None):
            try:
                self.rename_btn.setIcon(qta.icon('mdi6.rename-box', color=text_dark, options=[{'scale_factor': 1.1}]))
            except Exception:
                pass
            self.rename_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                }}
                QPushButton:pressed {{
                    background-color: {hover_bg};
                }}
                {tooltip_style}
            """)
        if getattr(self, "delete_btn", None):
            self.delete_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: #ffcccc;
                }}
                QPushButton:pressed {{
                    background-color: #ff9999;
                }}
                {tooltip_style}
            """)
        if getattr(self, "compare_btn", None):
            try:
                self.compare_btn.setIcon(qta.icon('mdi6.compare', color=text_dark, options=[{'scale_factor': 1.1}]))
            except Exception:
                pass
            self.compare_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 16px;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                }}
                QPushButton:pressed {{
                    background-color: {hover_bg};
                }}
                {tooltip_style}
            """)
        
        # Filter action buttons
        if getattr(self, "fav_btn", None):
            self.fav_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: #ffe0e0;
                }}
                {tooltip_style}
            """)
        if getattr(self, "filter_btn", None):
            self.filter_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    padding: 4px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                }}
                QPushButton:pressed {{
                    background-color: {hover_bg};
                }}
                QPushButton:checked {{
                    background-color: {hover_bg};
                    border: 1px solid {border};
                }}
                {tooltip_style}
            """)
        
        # Rating group
        if getattr(self, "rating_filter_btn", None):
            self.rating_filter_btn.setStyleSheet(self.rating_filter_btn.styleSheet() + tooltip_style)
        if getattr(self, "star_rating", None):
            self.star_rating.setStyleSheet(tooltip_style)

    def set_sort_direction(self, direction: str):
        # if not hasattr(self, 'sort_dir_label') or self.sort_dir_label is None:
        #     return
        # if direction == "asc":
        #     self.sort_dir_label.setText("↑")
        # elif direction == "desc":
        #     self.sort_dir_label.setText("↓")
        # else:
        #     self.sort_dir_label.setText("")
        pass

    def toggle_filter_panel(self, checked):
        if checked:
            if not self.filter_panel:
                return
            try:
                if getattr(self, "thumbnail_size_btn", None) is not None and bool(self.thumbnail_size_btn.isChecked()):
                    self.thumbnail_size_btn.setChecked(False)
            except Exception:
                pass
            
            parent_widget = self.filter_panel.parent()
            if not parent_widget:
                self.filter_panel.show()
                return

            panel_width = 600
            self.filter_panel.setFixedWidth(panel_width)
            self.filter_panel.adjustSize()
            
            # Position relative to the filter button
            # We want the panel to be centered below the button, but clamped to the window edges
            
            # 1. Get button position relative to the panel's parent
            btn_pos = self.filter_btn.mapTo(parent_widget, QPoint(0, 0))
            
            # 2. Calculate target X: center align with button
            target_x = btn_pos.x() + (self.filter_btn.width() - panel_width) // 2
            
            # 3. Boundary checks (keep within parent width)
            parent_width = parent_widget.width()
            if target_x + panel_width > parent_width - 10:
                target_x = parent_width - panel_width - 10
            if target_x < 10:
                target_x = 10
            
            # 4. Calculate target Y: just below the button
            target_y = btn_pos.y() + self.filter_btn.height() + 4
            
            self.filter_panel.move(target_x, target_y)
            self.filter_panel.show()
            self.filter_panel.raise_()
            try:
                color_on = ColorManager.instance().get("theme.primary")
            except Exception:
                color_on = "#2196f3"
            self.filter_btn.setIcon(qta.icon('mdi6.filter', color=color_on, options=[{'scale_factor': 1.1}]))
        else:
            if self.filter_panel:
                self.filter_panel.hide()
            try:
                color_off = ColorManager.instance().get("theme.text.dark")
            except Exception:
                color_off = "#555"
            self.filter_btn.setIcon(qta.icon('mdi6.filter-outline', color=color_off, options=[{'scale_factor': 1.1}]))

    def toggle_thumbnail_size_panel(self, checked: bool):
        panel = getattr(self, "thumbnail_size_panel", None)
        btn = getattr(self, "thumbnail_size_btn", None)
        if panel is None or btn is None:
            return
        if checked:
            try:
                if getattr(self, "filter_btn", None) is not None and bool(self.filter_btn.isChecked()):
                    self.filter_btn.setChecked(False)
            except Exception:
                pass
            parent_widget = panel.parent()
            if not parent_widget:
                panel.show()
                panel.raise_()
                return
            try:
                panel_w = int(panel.width() or 320)
            except Exception:
                panel_w = 320
            btn_pos = btn.mapTo(parent_widget, QPoint(0, 0))
            target_x = int(btn_pos.x() + (btn.width() - panel_w) // 2)
            parent_width = int(parent_widget.width() or 0)
            if parent_width > 0:
                if target_x + panel_w > parent_width - 10:
                    target_x = parent_width - panel_w - 10
                if target_x < 10:
                    target_x = 10
            target_y = int(btn_pos.y() + btn.height() + 4)
            panel.move(target_x, target_y)
            panel.show()
            panel.raise_()
            try:
                color_on = ColorManager.instance().get("theme.primary")
            except Exception:
                color_on = "#2196f3"
            try:
                btn.setIcon(qta.icon("mdi.image-size-select-large", color=color_on, options=[{"scale_factor": 1.1}]))
            except Exception:
                pass
        else:
            try:
                panel.hide()
            except Exception:
                pass
            try:
                color_off = ColorManager.instance().get("theme.text.dark")
            except Exception:
                color_off = "#555"
            try:
                btn.setIcon(qta.icon("mdi.image-size-select-large", color=color_off, options=[{"scale_factor": 1.1}]))
            except Exception:
                pass

    def eventFilter(self, obj, event):
        try:
            et = event.type()
        except Exception:
            et = None
        if et == QEvent.Type.MouseButtonPress:
            try:
                btn = getattr(self, "thumbnail_size_btn", None)
                panel = getattr(self, "thumbnail_size_panel", None)
                if btn is not None and panel is not None and panel.isVisible():
                    try:
                        p = event.globalPosition().toPoint()
                    except Exception:
                        p = None
                    if p is not None:
                        inside_panel = panel.rect().contains(panel.mapFromGlobal(p))
                        inside_btn = btn.rect().contains(btn.mapFromGlobal(p))
                        if not inside_panel and not inside_btn:
                            try:
                                btn.setChecked(False)
                            except Exception:
                                panel.hide()
            except Exception:
                pass
        return super().eventFilter(obj, event)
            
    # Helper methods for updating UI state
    def set_fav_checked(self, checked):
        self.fav_btn.blockSignals(True)
        self.fav_btn.setChecked(checked)
        if checked:
            self.fav_btn.setIcon(qta.icon('mdi6.heart', color='#e74c3c', options=[{'scale_factor': 1.1}]))
        else:
            self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
        self.fav_btn.blockSignals(False)

    def _on_fav_btn_toggled(self, checked: bool):
        try:
            if checked:
                self.fav_btn.setIcon(qta.icon('mdi6.heart', color='#e74c3c', options=[{'scale_factor': 1.1}]))
            else:
                self.fav_btn.setIcon(qta.icon('mdi6.heart-outline', color='#999', options=[{'scale_factor': 1.1}]))
        except Exception:
            pass
        self.favToggled.emit(bool(checked))
        
    def set_rating(self, rating, emit_signal=False):
        self.star_rating.set_rating(rating, emit_signal)

    def get_sort_mode(self):
        return self.sort_combo.currentText()
