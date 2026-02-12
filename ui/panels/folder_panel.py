import os
import subprocess
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLineEdit, QListWidget, QListWidgetItem, QTreeWidget, 
                             QTreeWidgetItem, QTreeWidgetItemIterator, QMenu, 
                             QAbstractItemView, QHeaderView, QSpacerItem, QSizePolicy)
from PyQt6.QtCore import Qt, QSize, QPoint, pyqtSignal, QTimer, QEvent, QModelIndex
import qtawesome as qta
try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

from ui.widgets.custom_input_dialog import CustomInputDialog
from ui.utils.notification_manager import NotificationManager
from ui.utils.color_manager import ColorManager
from ui.utils.shortcut_manager import ShortcutManager
from utils.log_manager import LogManager
from PyQt6.QtGui import QShortcut, QPainter, QPen, QColor

class _DropSplitOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._zone = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        try:
            self.hide()
        except Exception:
            pass

    def set_active(self, active: bool):
        self._active = bool(active)
        try:
            self.setVisible(bool(active))
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    def set_zone(self, zone: str):
        z = str(zone or "")
        if z == self._zone:
            return
        self._zone = z
        try:
            self.update()
        except Exception:
            pass

    def paintEvent(self, event):
        if not bool(self._active):
            return
        cm = ColorManager.instance()
        primary = cm.get("theme.primary")
        try:
            c = QColor(str(primary))
        except Exception:
            c = QColor("#2196F3")
        try:
            base_fill = QColor(c)
            base_fill.setAlpha(34)
        except Exception:
            base_fill = None
        try:
            hover = QColor(c)
            hover.setAlpha(56)
        except Exception:
            hover = None

        r = self.rect()
        m = 14
        gap = 12
        try:
            w = max(0, int(r.width()) - m * 2)
            h = max(0, int(r.height()) - m * 2)
        except Exception:
            return
        if w <= 10 or h <= 10:
            return
        h2 = max(0, (h - gap) // 2)
        top_rect = r.adjusted(m, m, -m, -(m + h2 + gap))
        bot_rect = r.adjusted(m, m + h2 + gap, -m, -m)

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        except Exception:
            pass
        pen = QPen(c, 2, Qt.PenStyle.DashLine)
        try:
            pen.setDashPattern([6.0, 4.0])
        except Exception:
            pass
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = 10.0

        if base_fill is not None:
            try:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(base_fill)
                painter.drawRoundedRect(top_rect, radius, radius)
                painter.drawRoundedRect(bot_rect, radius, radius)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            except Exception:
                try:
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                except Exception:
                    pass

        if hover is not None:
            try:
                if self._zone == "top":
                    painter.setBrush(hover)
                    painter.drawRoundedRect(top_rect, radius, radius)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                elif self._zone == "bottom":
                    painter.setBrush(hover)
                    painter.drawRoundedRect(bot_rect, radius, radius)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
            except Exception:
                painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.drawRoundedRect(top_rect, radius, radius)
        painter.drawRoundedRect(bot_rect, radius, radius)

        painter.setPen(QPen(c, 1))
        try:
            painter.drawText(top_rect, int(Qt.AlignmentFlag.AlignCenter), "导入")
            painter.drawText(bot_rect, int(Qt.AlignmentFlag.AlignCenter), "对焦检测")
        except Exception:
            pass

class _GuidedTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._branch_color_token = "theme.primary"
        self._branch_color_fallback = "#2196F3"

    def drawBranches(self, painter: QPainter, rect, index: QModelIndex):
        try:
            super().drawBranches(painter, rect, index)
        except Exception:
            pass
        try:
            if not bool(self.property("show_guides")):
                return
        except Exception:
            return

        if not index or not index.isValid():
            return
        try:
            parent = index.parent()
        except Exception:
            parent = QModelIndex()
        if not parent or not parent.isValid():
            return

        try:
            item_rect = self.visualRect(index)
        except Exception:
            return
        if not item_rect or item_rect.isNull():
            return

        try:
            indent = int(self.indentation())
        except Exception:
            indent = 16
        if indent <= 0:
            return

        level = 0
        try:
            p = index.parent()
            while p.isValid():
                level += 1
                p = p.parent()
        except Exception:
            level = 1
        if level <= 0:
            return

        try:
            c = QColor("#000000")
            try:
                c.setAlpha(200)
            except Exception:
                pass
        except Exception:
            c = QColor("#000000")

        painter.save()
        try:
            pen = QPen(c, 1, Qt.PenStyle.DashLine)
            try:
                pen.setDashPattern([3.0, 3.0])
            except Exception:
                pass
            painter.setPen(pen)
        except Exception:
            pass

        mid_y = int(item_rect.center().y())

        try:
            model = self.model()
        except Exception:
            model = None

        def has_next_sibling(idx: QModelIndex) -> bool:
            if model is None:
                return False
            try:
                par = idx.parent()
                row_count = int(model.rowCount(par))
                return int(idx.row()) < row_count - 1
            except Exception:
                return False

        is_leaf = False
        try:
            if model is not None:
                is_leaf = int(model.rowCount(index)) <= 0
        except Exception:
            is_leaf = False

        x_self = int(item_rect.left() - indent * 1.5)
        if x_self < 0:
            x_self = 0

        try:
            if bool(is_leaf):
                painter.drawLine(x_self, int(item_rect.top()), x_self, mid_y)
            else:
                if has_next_sibling(index):
                    painter.drawLine(x_self, int(item_rect.top()), x_self, int(item_rect.bottom()))
                else:
                    painter.drawLine(x_self, int(item_rect.top()), x_self, mid_y)
        except Exception:
            pass
        try:
            end_x = int(item_rect.left()) - int(indent) - 2
            painter.drawLine(x_self, mid_y, max(x_self, end_x), mid_y)
        except Exception:
            pass

        try:
            chain = []
            p = index.parent()
            while p.isValid():
                chain.append(p)
                p = p.parent()
        except Exception:
            chain = []

        for depth, anc in enumerate(chain, start=1):
            if not has_next_sibling(anc):
                continue
            x = int(item_rect.left() - indent * (depth + 0.5))
            if x < 0:
                continue
            try:
                if bool(is_leaf):
                    painter.drawLine(x, int(item_rect.top()), x, mid_y)
                else:
                    painter.drawLine(x, int(item_rect.top()), x, int(item_rect.bottom()))
            except Exception:
                pass

        painter.restore()

class FolderPanel(QWidget):
    # Signals
    folderSelected = pyqtSignal(str, int) # path, depth
    folderClicked = pyqtSignal(str) # path
    folderRenamed = pyqtSignal(str, str) # old_path, new_path
    toggleRequested = pyqtSignal(bool) # visible
    
    # New Signals for replaced buttons
    importClicked = pyqtSignal()
    recognitionClicked = pyqtSignal()
    modeSwitchClicked = pyqtSignal()
    folderRemovedFromTree = pyqtSignal(str)  # path
    folderDeletedOnDisk = pyqtSignal(str)  # path
    rootFoldersChanged = pyqtSignal()
    focusDetectFoldersDropped = pyqtSignal(object)

    def __init__(self, db, settings_manager, parent=None, context="library"):
        super().__init__(parent)
        self.db = db
        self.settings_manager = settings_manager
        self.context = str(context or "library").lower()
        
        self.folder_sort_mode = "pinyin"
        self.folder_tree_visible = True
        
        self.tool_buttons = [] # Store dynamically added buttons
        self.spacers = [] # Store spacers for layout management
        self.search_btn = None # Initialize as None
        self.sort_btn = None
        
        self.override_strict_mode = None # Allow overriding strict mode setting
        self.show_db_stats = True # 是否显示数据库统计信息
        
        self.init_ui()
        self._apply_theme_styles()
        ColorManager.instance().register_listener(self._apply_theme_styles)
        try:
            self._init_tree_shortcuts()
        except Exception:
            pass

    def _init_tree_shortcuts(self):
        if hasattr(self, "_tree_shortcuts_by_id") and isinstance(getattr(self, "_tree_shortcuts_by_id", None), dict) and self._tree_shortcuts_by_id:
            return
        self._tree_shortcuts_by_id = {}
        tree = getattr(self, "folder_tree", None)
        if tree is None:
            return
        try:
            sc = QShortcut(tree)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._toggle_current_folder_expand)
            self._tree_shortcuts_by_id["FolderTree.ToggleExpand"] = sc
        except Exception:
            pass
        try:
            self._update_tree_shortcuts()
            ShortcutManager.instance().shortcuts_changed.connect(self._update_tree_shortcuts)
        except Exception:
            pass

    def _update_tree_shortcuts(self):
        mp = getattr(self, "_tree_shortcuts_by_id", None)
        if not isinstance(mp, dict) or not mp:
            return
        sm = ShortcutManager.instance()
        for sid, sc in mp.items():
            if sc is None:
                continue
            try:
                seq = sm.get_sequence(str(sid))
            except Exception:
                continue
            if isinstance(seq, str):
                continue
            try:
                sc.setKey(seq)
            except Exception:
                pass

    def _toggle_current_folder_expand(self):
        tree = getattr(self, "folder_tree", None)
        if tree is None:
            return
        try:
            it = tree.currentItem()
        except Exception:
            it = None
        if it is None:
            return
        try:
            expanded = bool(it.isExpanded())
        except Exception:
            expanded = False
        try:
            it.setExpanded(not expanded)
        except Exception:
            pass

    def _set_shortcut_nav_guard(self):
        try:
            self._shortcut_nav_guard = True
        except Exception:
            return
        try:
            QTimer.singleShot(160, lambda: setattr(self, "_shortcut_nav_guard", False))
        except Exception:
            try:
                self._shortcut_nav_guard = False
            except Exception:
                pass
        
    def set_override_strict_mode(self, mode):
        """设置是否覆盖严格模式设置"""
        self.override_strict_mode = mode
        
    def set_show_db_stats(self, show):
        """设置是否显示数据库统计信息"""
        self.show_db_stats = show

    def update_root_title(self, title):
        """更新根节点标题"""
        if self.folder_tree.topLevelItemCount() > 0:
            root_item = self.folder_tree.topLevelItem(0)
            root_item.setText(0, title)

    def _is_strict_mode(self):
        """检查是否启用严格模式"""
        if self.override_strict_mode is not None:
            return self.override_strict_mode
        
        val = self.settings_manager.get("setting/bird_strict", True)
        if isinstance(val, str):
            return val.lower() == 'true'
        return bool(val)
        
    def init_ui(self):
        self.setMinimumWidth(120)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Search Container
        self.setup_search_area(layout)
        
        # Search Results
        self.setup_search_results()
        
        # Folder Tree
        self.setup_folder_tree(layout)

    def _apply_theme_styles(self):
        """同步文件夹面板的主题样式

        参数:
            无
        """
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.sidebar")
        border = cm.get("popup.border.primary")
        text_dark = cm.get("theme.text.dark")
        text_light = cm.get("theme.text.light")
        primary = cm.get("theme.primary")
        popup_bg = cm.get("popup.background.primary")
        input_bg = cm.get("theme.background.primary")
        back_dark = cm.get("theme.background.dark")
        hover_bg = cm.get("theme.background.light")
        tree_bg = cm.get("theme.background.primary")
        toolbar_icon_color = cm.get("theme.text.dark")
        tree_icon_color = text_dark
        scrollbar_bg = tree_bg
        scrollbar_handle = cm.get("popup.border.primary")
        scrollbar_handle_hover = primary
        drag_over_bg = self._to_rgba(primary, 0.12)

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {popup_bg};
                border-top: 1px solid {border};
            }}
        """)
        if self.search_container:
            self.search_container.setStyleSheet(f"""
                #folderSearchContainer {{
                    background-color: {tree_bg};
                    border-bottom: 1px solid {border};
                }}
            """)
        if self.search_panel:
            self.search_panel.setStyleSheet(f"""
                QWidget {{
                    background-color: {popup_bg};
                    border: 1px solid {tree_bg};
                    border-radius: 4px;
                }}
            """)
        if self.search_input:
            self.search_input.setStyleSheet(f"""
                QLineEdit {{
                    padding: 4px 8px;
                    border: 1px solid {text_dark};
                    border-radius: 3px;
                    background-color: {input_bg};
                    font-size: 12px;
                    color: {text_dark};
                }}
                QLineEdit:focus {{
                    border: 1px solid {text_dark};
                    background-color: {input_bg};
                    color: {text_dark};
                }}
            """)
        if self.search_results:
            self.search_results.setStyleSheet(f"""
                QListWidget#folderSearchResults {{
                    background-color: {tree_bg};
                    border: 1px solid {border};
                    border-radius: 4px;
                    font-size: 12px;
                    padding: 2px;
                    color: {text_dark};
                }}
                QListWidget#folderSearchResults::item {{
                    padding: 4px 12px;
                    border: none;
                }}
                QListWidget#folderSearchResults::item:hover {{
                    background-color: {hover_bg};
                }}
                QListWidget#folderSearchResults::item:selected {{
                    background-color: {primary};
                    color: {text_dark};
                }}
                QListWidget#folderSearchResults QScrollBar:vertical {{
                    background-color: {back_dark};
                    width: 10px;
                }}
                QListWidget#folderSearchResults QScrollBar::handle:vertical {{
                    background-color: {scrollbar_handle};
                    min-height: 30px;
                }}
                QListWidget#folderSearchResults QScrollBar::handle:vertical:hover {{
                    background-color: {primary};
                }}
                QListWidget#folderSearchResults QScrollBar::add-line:vertical,
                QListWidget#folderSearchResults QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
                QListWidget#folderSearchResults QScrollBar::add-page:vertical,
                QListWidget#folderSearchResults QScrollBar::sub-page:vertical {{
                    background: transparent;
                }}
            """)
            try:
                sb_style = f"""
                    QScrollBar:vertical {{
                        background-color: {back_dark};
                        width: 10px;
                    }}
                    QScrollBar::handle:vertical {{
                        background-color: {scrollbar_handle};
                        min-height: 30px;
                    }}
                    QScrollBar::handle:vertical:hover {{
                        background-color: {primary};
                    }}
                    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                        height: 0px;
                    }}
                    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                        background: transparent;
                    }}
                """
                self.search_results.verticalScrollBar().setStyleSheet(sb_style)
            except Exception:
                pass
        if self.folder_tree:
            self.folder_tree.setStyleSheet(f"""
                QTreeWidget {{
                    background-color: {tree_bg};
                    border: none;
                    font-size: 12px;
                    outline: none;
                    color: {text_dark};
                }}
                QTreeWidget[drag_over="true"] {{
                    background-color: {tree_bg};
                    border: none;
                    border-radius: 0px;
                }}
                QTreeWidget:focus {{
                    outline: none;
                }}
                QTreeWidget::item {{
                    padding: 4px 8px 4px 8px;
                    border: none;
                    show-decoration-selected: 0;
                }}
                QTreeWidget::item:hover {{
                    background-color: {primary};
                    border-radius: 3px;
                    padding-right: 8px;
                }}
                QTreeWidget::item:selected {{
                    background-color: transparent;
                    color: {primary};
                    border: none;
                    outline: none;
                }}
                QTreeWidget::item:selected:hover {{
                    background-color: transparent;
                    border: none;
                    outline: none;
                }}
                QTreeWidget::item:selected:focus {{
                    background-color: transparent;
                    border: none;
                    outline: none;
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
                QScrollBar:horizontal {{
                    background-color: {scrollbar_bg};
                    height: 10px;
                }}
                QScrollBar::handle:horizontal {{
                    background-color: {scrollbar_handle};
                    min-width: 30px;
                }}
                QScrollBar::handle:horizontal:hover {{
                    background-color: {scrollbar_handle_hover};
                }}
            """)
        if self.toggle_btn:
            icon_name = self.toggle_btn.property("icon_name") or "mdi6.chevron-left"
            self.toggle_btn.setIcon(qta.icon(icon_name, color=toolbar_icon_color, options=[{'scale_factor': 1.1}]))
            self.style_tool_btn(self.toggle_btn, primary)
        if self.search_btn:
            icon_name = self.search_btn.property("icon_name") or "mdi6.magnify"
            self.search_btn.setIcon(qta.icon(icon_name, color=toolbar_icon_color, options=[{'scale_factor': 1.1}]))
            self.style_tool_btn(self.search_btn, primary)
        if self.sort_btn:
            icon_name = self.sort_btn.property("icon_name") or "mdi6.sort-alphabetical-ascending"
            self.sort_btn.setIcon(qta.icon(icon_name, color=toolbar_icon_color, options=[{'scale_factor': 1.1}]))
            self.style_tool_btn(self.sort_btn, primary)
        for btn in self.tool_buttons:
            if not isinstance(btn, QPushButton):
                continue
            icon_name = btn.property("icon_name")
            if icon_name:
                btn.setIcon(qta.icon(icon_name, color=toolbar_icon_color, options=[{'scale_factor': 1.1}]))
            self.style_tool_btn(btn, primary)
        if self.folder_tree:
            root = self.folder_tree.invisibleRootItem()
            root_icon = qta.icon("mdi6.harddisk", color=text_dark)
            folder_icon = qta.icon("mdi6.folder", color=primary)
            loading_icon = qta.icon("mdi6.loading", color=tree_icon_color)
            for i in range(root.childCount()):
                top = root.child(i)
                top.setIcon(0, root_icon)
                stack = [top]
                while stack:
                    item = stack.pop()
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data == "__placeholder__":
                        item.setIcon(0, loading_icon)
                    elif item is not top:
                        item.setIcon(0, folder_icon)
                    for j in range(item.childCount()):
                        stack.append(item.child(j))
            
    def setup_search_area(self, parent_layout):
        self.search_container = QWidget()
        self.search_container.setObjectName("folderSearchContainer")
        self.search_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        layout = QHBoxLayout(self.search_container)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(16)
        self.search_layout = layout # Save reference for toggle logic
        
        # Initialize search functionality (popup panel) regardless of button presence
        self._init_search_panel()

        # No initial stretch. Buttons will be distributed evenly using spacers.
        
        # Toggle Button (Always present)
        icon_color = ColorManager.instance().get("theme.text.dark")
        self.toggle_btn = QPushButton()
        self.toggle_btn.setProperty("icon_name", "mdi6.chevron-left")
        self.toggle_btn.setIcon(qta.icon('mdi6.chevron-left', color=icon_color, options=[{'scale_factor': 1.1}]))
        self.toggle_btn.setIconSize(QSize(18, 18))
        self.toggle_btn.setFixedSize(24, 24)
        self.toggle_btn.setToolTip("折叠文件夹")
        self.style_tool_btn(self.toggle_btn)
        self.toggle_btn.clicked.connect(self.on_toggle_clicked)
        layout.addWidget(self.toggle_btn)
        
        parent_layout.addWidget(self.search_container)

    def _init_search_panel(self):
        # Search Panel (Popup)
        self.search_panel = QWidget(self)
        self.search_panel.setFixedHeight(36)
        self.search_panel.hide()
        
        search_panel_layout = QHBoxLayout(self.search_panel)
        search_panel_layout.setContentsMargins(8, 4, 8, 4)
        search_panel_layout.setSpacing(6)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索文件夹...")
        self.search_input.textChanged.connect(self.on_search_text_changed)
        search_panel_layout.addWidget(self.search_input)

    def _insert_tool_btn(self, btn):
        """Helper to insert tool button at the correct position with distributed spacing"""
        # Layout structure: [Btn1, Spacer, Btn2, Spacer, ..., Toggle]
        # We want to insert the button and a spacer before the toggle button
        
        index = self.search_layout.indexOf(self.toggle_btn)
        
        # 1. Insert Button
        self.search_layout.insertWidget(index, btn)
        
        # 2. Insert Spacer (after the button, before Toggle)
        # Note: insertWidget shifts Toggle to index+1.
        # We want spacer at index+1 (between new btn and Toggle)
        spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.search_layout.insertItem(index + 1, spacer)
        self.spacers.append(spacer)

    def add_tool_button(self, icon, tooltip, callback=None):
        """动态添加工具栏按钮"""
        btn = QPushButton()
        if isinstance(icon, str):
            icon_color = ColorManager.instance().get("theme.text.dark")
            btn.setProperty("icon_name", icon)
            btn.setIcon(qta.icon(icon, color=icon_color, options=[{'scale_factor': 1.1}]))
        else:
            btn.setIcon(icon)
            
        btn.setIconSize(QSize(16, 16))
        btn.setFixedSize(24, 24)
        btn.setToolTip(tooltip)
        self.style_tool_btn(btn)
        
        if callback:
            btn.clicked.connect(callback)
            
        self.tool_buttons.append(btn)
        self._insert_tool_btn(btn)
        return btn

    def add_widget(self, widget):
        """Add a custom widget to the toolbar"""
        self._insert_tool_btn(widget)
        self.tool_buttons.append(widget)
        return widget

    def add_search_button(self):
        """添加搜索按钮"""
        if self.search_btn: return self.search_btn
        
        self.search_btn = QPushButton()
        icon_color = ColorManager.instance().get("theme.text.dark")
        self.search_btn.setProperty("icon_name", "mdi6.magnify")
        self.search_btn.setIcon(qta.icon('mdi6.magnify', color=icon_color, options=[{'scale_factor': 1.1}]))
        self.search_btn.setIconSize(QSize(18, 18))
        self.search_btn.setFixedSize(24, 24)
        self.search_btn.setToolTip("搜索文件夹")
        self.search_btn.setCheckable(True)
        self.style_tool_btn(self.search_btn)
        self.search_btn.toggled.connect(self.toggle_search_panel)
        
        self.tool_buttons.append(self.search_btn)
        self._insert_tool_btn(self.search_btn)
        return self.search_btn

    def add_sort_button(self):
        """添加排序按钮"""
        if self.sort_btn: return self.sort_btn
        
        self.sort_btn = QPushButton()
        icon_color = ColorManager.instance().get("theme.text.dark")
        self.sort_btn.setProperty("icon_name", "mdi6.sort-alphabetical-ascending")
        self.sort_btn.setIcon(qta.icon('mdi6.sort-alphabetical-ascending', color=icon_color, options=[{'scale_factor': 1.1}]))
        self.sort_btn.setIconSize(QSize(18, 18))
        self.sort_btn.setFixedSize(24, 24)
        self.sort_btn.setToolTip("排序")
        self.style_tool_btn(self.sort_btn)
        self.sort_btn.clicked.connect(self.show_sort_menu)
        
        self.tool_buttons.append(self.sort_btn)
        self._insert_tool_btn(self.sort_btn)
        return self.sort_btn

    def setup_search_results(self):
        self.search_results = QListWidget(self)
        self.search_results.setObjectName("folderSearchResults")
        self.search_results.setMinimumHeight(190)
        self.search_results.setMaximumHeight(200)
        self.search_results.setIconSize(QSize(16, 16))
        self.search_results.hide()
        self.search_results.itemClicked.connect(self.on_search_result_clicked)

    def setup_folder_tree(self, parent_layout):
        self.folder_tree = _GuidedTreeWidget()
        try:
            self.folder_tree.setProperty("show_guides", False)
        except Exception:
            pass
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setColumnCount(2)
        self.folder_tree.setColumnHidden(1, True)
        self.folder_tree.setSortingEnabled(True)
        self.folder_tree.header().setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        
        self.folder_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.folder_tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.folder_tree.header().setStretchLastSection(False)
        self.folder_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.folder_tree.setIndentation(16)
        self.folder_tree.setAnimated(True)
        self.folder_tree.setIconSize(QSize(16, 16))
        try:
            if str(self.context or "").lower() == "import":
                self.folder_tree.setAcceptDrops(True)
                self.folder_tree.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
                self.folder_tree.viewport().setAcceptDrops(True)
        except Exception:
            pass
        
        self.folder_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self.on_context_menu)
        self.folder_tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.folder_tree.itemExpanded.connect(self.on_folder_expanded)
        self.folder_tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        self.folder_tree.itemClicked.connect(self.on_tree_item_clicked)
        try:
            self.folder_tree.verticalScrollBar().valueChanged.connect(lambda _: self.folder_tree.viewport().update())
        except Exception:
            pass
        try:
            self.folder_tree.setMouseTracking(True)
            self.folder_tree.viewport().setMouseTracking(True)
            self.folder_tree.viewport().installEventFilter(self)
        except Exception:
            pass
        try:
            self._drop_split_overlay = _DropSplitOverlay(self.folder_tree.viewport())
            self._drop_split_overlay.setGeometry(self.folder_tree.viewport().rect())
            self._drop_split_overlay.raise_()
            self._drop_drop_zone = ""
        except Exception:
            self._drop_split_overlay = None
            self._drop_drop_zone = ""
        
        parent_layout.addWidget(self.folder_tree)

    def _to_rgba(self, color: str, alpha: float) -> str:
        s = str(color or "").strip()
        if s.startswith("#") and len(s) == 7:
            try:
                r = int(s[1:3], 16)
                g = int(s[3:5], 16)
                b = int(s[5:7], 16)
                a = max(0.0, min(1.0, float(alpha)))
                return f"rgba({r}, {g}, {b}, {a})"
            except Exception:
                return s
        return s

    def _set_drag_over(self, enabled: bool):
        tree = getattr(self, "folder_tree", None)
        if tree is None:
            return
        try:
            ov = getattr(self, "_drop_split_overlay", None)
            if ov is not None:
                try:
                    ov.setGeometry(tree.viewport().rect())
                except Exception:
                    pass
                ov.set_active(bool(enabled))
        except Exception:
            pass
        try:
            tree.setProperty("drag_over", bool(enabled))
            tree.style().unpolish(tree)
            tree.style().polish(tree)
            tree.update()
            tree.viewport().update()
        except Exception:
            pass

    def _update_drop_zone(self, event):
        ov = getattr(self, "_drop_split_overlay", None)
        if ov is None:
            return ""
        tree = getattr(self, "folder_tree", None)
        if tree is None:
            return ""
        vp = tree.viewport()
        if vp is None:
            return ""
        try:
            pos = event.position().toPoint()
        except Exception:
            try:
                pos = event.pos()
            except Exception:
                pos = None
        if pos is None:
            return ""
        try:
            h = int(vp.height() or 0)
        except Exception:
            h = 0
        if h <= 0:
            return ""
        zone = "top" if int(pos.y()) < (h // 2) else "bottom"
        try:
            self._drop_drop_zone = zone
        except Exception:
            pass
        try:
            ov.set_zone(zone)
        except Exception:
            pass
        return zone

    def _get_drop_dirs(self, event):
        try:
            md = event.mimeData()
        except Exception:
            return []
        if md is None:
            return []
        urls = []
        try:
            urls = md.urls() or []
        except Exception:
            urls = []
        out = []
        seen = set()
        for u in urls:
            try:
                p = str(u.toLocalFile() or "").strip()
            except Exception:
                p = ""
            if not p:
                continue
            try:
                if not os.path.isdir(p):
                    continue
            except Exception:
                continue
            try:
                norm = os.path.normcase(os.path.normpath(p))
            except Exception:
                norm = p
            if norm in seen:
                continue
            seen.add(norm)
            out.append(p)
        return out

    def _activate_top_window(self):
        try:
            w = self.window()
        except Exception:
            w = None
        if w is None:
            return
        try:
            if hasattr(w, "isMinimized") and w.isMinimized():
                w.showNormal()
        except Exception:
            pass
        try:
            w.raise_()
        except Exception:
            pass
        try:
            w.activateWindow()
        except Exception:
            pass

    def _collect_import_root_paths_from_tree(self):
        tree = getattr(self, "folder_tree", None)
        if tree is None:
            return []
        roots = []
        seen = set()
        try:
            n = int(tree.topLevelItemCount())
        except Exception:
            n = 0
        for i in range(n):
            try:
                it = tree.topLevelItem(i)
            except Exception:
                it = None
            if it is None:
                continue
            try:
                p = it.data(0, Qt.ItemDataRole.UserRole)
            except Exception:
                p = None
            if not p:
                continue
            try:
                s = str(p)
            except Exception:
                continue
            try:
                if not os.path.isdir(s):
                    continue
            except Exception:
                continue
            try:
                norm = os.path.normcase(os.path.normpath(s))
            except Exception:
                norm = s
            if norm in seen:
                continue
            seen.add(norm)
            roots.append(s)
        return roots

    def eventFilter(self, obj, event):
        try:
            if hasattr(self, "folder_tree") and self.folder_tree is not None:
                if obj is self.folder_tree.viewport():
                    t = event.type()
                    if str(self.context or "").lower() == "import":
                        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                            dirs = self._get_drop_dirs(event)
                            if dirs:
                                self._set_drag_over(True)
                                self._update_drop_zone(event)
                                try:
                                    event.acceptProposedAction()
                                except Exception:
                                    pass
                                return True
                            self._set_drag_over(False)
                        elif t in (QEvent.Type.DragLeave,):
                            self._set_drag_over(False)
                            return True
                        elif t in (QEvent.Type.Drop,):
                            dirs = self._get_drop_dirs(event)
                            self._set_drag_over(False)
                            if dirs:
                                try:
                                    zone_global = ""
                                    try:
                                        gp = QCursor.pos()
                                        vp = self.folder_tree.viewport()
                                        pos = vp.mapFromGlobal(gp)
                                        h = int(vp.height() or 0)
                                        if h > 0:
                                            zone_global = "top" if int(pos.y()) < (h // 2) else "bottom"
                                    except Exception:
                                        zone_global = ""

                                    zone_event = ""
                                    try:
                                        zone_event = str(self._update_drop_zone(event) or "")
                                    except Exception:
                                        zone_event = ""

                                    if zone_global == "bottom" or zone_event == "bottom":
                                        zone = "bottom"
                                    elif zone_global:
                                        zone = zone_global
                                    else:
                                        zone = zone_event
                                except Exception:
                                    zone = ""
                                if not zone:
                                    try:
                                        zone = str(getattr(self, "_drop_drop_zone", "") or "")
                                    except Exception:
                                        zone = ""
                                if zone == "bottom":
                                    try:
                                        payload = list(dirs)
                                        QTimer.singleShot(0, lambda p=payload: self.focusDetectFoldersDropped.emit(p))
                                    except Exception:
                                        try:
                                            self.focusDetectFoldersDropped.emit(list(dirs))
                                        except Exception:
                                            pass
                                    try:
                                        event.acceptProposedAction()
                                    except Exception:
                                        pass
                                    return True
                                before = set()
                                before_count = 0
                                try:
                                    before_count = int(self.folder_tree.topLevelItemCount())
                                    for i in range(self.folder_tree.topLevelItemCount()):
                                        it = self.folder_tree.topLevelItem(i)
                                        p = it.data(0, Qt.ItemDataRole.UserRole)
                                        if p:
                                            before.add(os.path.normcase(os.path.normpath(str(p))))
                                except Exception:
                                    before = set()
                                try:
                                    self.add_root_folders(dirs)
                                except Exception:
                                    pass
                                try:
                                    after = set()
                                    for i in range(self.folder_tree.topLevelItemCount()):
                                        it = self.folder_tree.topLevelItem(i)
                                        p = it.data(0, Qt.ItemDataRole.UserRole)
                                        if p:
                                            after.add(os.path.normcase(os.path.normpath(str(p))))
                                    try:
                                        self.folder_tree.sortItems(1, Qt.SortOrder.AscendingOrder)
                                    except Exception:
                                        pass
                                    try:
                                        after_count = int(self.folder_tree.topLevelItemCount())
                                        for i in range(before_count, after_count):
                                            try:
                                                self.folder_tree.topLevelItem(i).setExpanded(True)
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                    try:
                                        QTimer.singleShot(0, lambda: self.folder_tree.viewport().update())
                                    except Exception:
                                        try:
                                            self.folder_tree.viewport().update()
                                        except Exception:
                                            pass
                                    added = max(0, len(after - before))
                                    skipped = max(0, len(dirs) - added)
                                    if skipped > 0:
                                        NotificationManager.instance().show_toast(f"已添加 {added} 个目录，已忽略 {skipped} 个已存在目录")
                                    else:
                                        NotificationManager.instance().show_toast(f"已添加 {added} 个目录")
                                except Exception:
                                    pass
                                try:
                                    self.rootFoldersChanged.emit()
                                except Exception:
                                    pass
                                try:
                                    event.acceptProposedAction()
                                except Exception:
                                    pass
                                try:
                                    QTimer.singleShot(0, self._activate_top_window)
                                except Exception:
                                    pass
                                return True
                    if t in (QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.Leave, QEvent.Type.HoverLeave):
                        try:
                            self.folder_tree.viewport().update()
                        except Exception:
                            pass
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def style_tool_btn(self, btn, hover_bg=None):
        if not hover_bg:
            hover_bg = ColorManager.instance().get("theme.primary")
        tooltip_bg = ColorManager.instance().get("theme.text.light")
        tooltip_text = ColorManager.instance().get("tooltip.text")
        tooltip_border = ColorManager.instance().get("tooltip.border")
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border-radius: 3px;
            }}
            QPushButton:checked {{
                background-color: {hover_bg};
                border-radius: 3px;
            }}
            QToolTip {{
                color: {tooltip_text};
                background-color: {tooltip_bg};
                border: 1px solid {tooltip_border};
            }}
        """)

    def populate_tree(self, root_path):
        """填充文件夹树"""
        self.folder_tree.clear()

        if str(self.context or "").lower() == "library":
            self._populate_taxonomy_tree(root_path)
            return
        
        root_item = QTreeWidgetItem(self.folder_tree, [root_path])
        icon_color = ColorManager.instance().get("theme.text.dark")
        root_item.setIcon(0, qta.icon('mdi6.harddisk', color=icon_color))
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
        
        if self.show_db_stats:
            try:
                stats = self.db.get_folder_stats() 
                species_count = stats.get('species_count', 0)
                image_count = stats.get('image_count', 0)
                root_item.setText(0, f"{root_path} (物种: {species_count}, 图片: {image_count})")
            except Exception as e:
                try:
                    LogManager.instance().warning(f"获取根目录统计失败: {e}")
                except Exception:
                    pass
                root_item.setText(0, root_path)
        else:
            root_item.setText(0, root_path)

        skip_preload = False
        try:
            if not self._is_strict_mode():
                seen = 0
                with os.scandir(root_path) as it:
                    for entry in it:
                        if entry.is_dir(follow_symlinks=False):
                            seen += 1
                            if seen > 300:
                                skip_preload = True
                                break
        except Exception:
            skip_preload = False
        if skip_preload:
            try:
                placeholder = QTreeWidgetItem(root_item, ["加载中..."])
                loading_icon_color = ColorManager.instance().get("theme.text.light")
                placeholder.setIcon(0, qta.icon('mdi6.loading', color=loading_icon_color))
                placeholder.setData(0, Qt.ItemDataRole.UserRole, "__placeholder__")
            except Exception:
                pass
        else:
            self._add_subfolders(root_item, root_path, depth=0, max_depth=1)
        # root_item.setExpanded(True)

    def _populate_taxonomy_tree(self, root_title):
        root_title = str(root_title or "")
        root_item = QTreeWidgetItem(self.folder_tree, [root_title])
        icon_color = ColorManager.instance().get("theme.text.dark")
        root_item.setIcon(0, qta.icon('mdi6.harddisk', color=icon_color))
        root_item.setData(0, Qt.ItemDataRole.UserRole, "virtual://taxonomy/root")

        stats = {"tree": {}, "unclassified_image_count": 0}
        try:
            stats = self.db.get_taxonomy_tree_stats(table_name="bird_results") or stats
        except Exception:
            stats = {"tree": {}, "unclassified_image_count": 0}

        try:
            total_images = 0
            total_species = 0
            for _o, n in (stats.get("tree") or {}).items():
                total_images += int(n.get("image_count") or 0)
                total_species += int(n.get("species_count") or 0)
        except Exception:
            total_images = 0
            total_species = 0
        try:
            total_images_all = total_images + int(stats.get("unclassified_image_count") or 0)
        except Exception:
            total_images_all = total_images

        if self.show_db_stats:
            root_item.setText(0, f"{root_title} (物种: {total_species}, 图片: {total_images_all})")
        else:
            root_item.setText(0, root_title)

        tree = stats.get("tree") or {}
        for order_name in sorted(tree.keys()):
            o_node = tree.get(order_name) or {}
            o_item = QTreeWidgetItem(root_item, [str(order_name)])
            o_item.setIcon(0, qta.icon('mdi6.folder', color=ColorManager.instance().get("theme.primary")))
            o_item.setData(0, Qt.ItemDataRole.UserRole, f"virtual://taxonomy?order={order_name}")
            if self.show_db_stats:
                o_item.setText(0, f"{order_name} (物种: {int(o_node.get('species_count') or 0)}, 图片: {int(o_node.get('image_count') or 0)})")
            families = (o_node.get("children") or {})
            for family_name in sorted(families.keys()):
                f_node = families.get(family_name) or {}
                f_item = QTreeWidgetItem(o_item, [str(family_name)])
                f_item.setIcon(0, qta.icon('mdi6.folder', color=ColorManager.instance().get("theme.primary")))
                f_item.setData(0, Qt.ItemDataRole.UserRole, f"virtual://taxonomy?order={order_name}&family={family_name}")
                if self.show_db_stats:
                    f_item.setText(0, f"{family_name} (物种: {int(f_node.get('species_count') or 0)}, 图片: {int(f_node.get('image_count') or 0)})")
                genera = (f_node.get("children") or {})
                for genus_name in sorted(genera.keys()):
                    g_node = genera.get(genus_name) or {}
                    g_item = QTreeWidgetItem(f_item, [str(genus_name)])
                    g_item.setIcon(0, qta.icon('mdi6.folder', color=ColorManager.instance().get("theme.primary")))
                    g_item.setData(0, Qt.ItemDataRole.UserRole, f"virtual://taxonomy?order={order_name}&family={family_name}&genus={genus_name}")
                    if self.show_db_stats:
                        g_item.setText(0, f"{genus_name} (物种: {int(g_node.get('species_count') or 0)}, 图片: {int(g_node.get('image_count') or 0)})")
                    species = (g_node.get("children") or {})
                    for species_name in sorted(species.keys()):
                        s_node = species.get(species_name) or {}
                        s_item = QTreeWidgetItem(g_item, [str(species_name)])
                        s_item.setIcon(0, qta.icon('mdi6.folder', color=ColorManager.instance().get("theme.primary")))
                        s_item.setData(0, Qt.ItemDataRole.UserRole, f"virtual://taxonomy?order={order_name}&family={family_name}&genus={genus_name}&species={species_name}")
                        if self.show_db_stats:
                            s_item.setText(0, f"{species_name} (图片: {int(s_node.get('image_count') or 0)})")

        unclassified_count = int(stats.get("unclassified_image_count") or 0)
        un_item = QTreeWidgetItem(root_item, ["未分类"])
        un_item.setIcon(0, qta.icon('mdi6.folder', color=ColorManager.instance().get("theme.primary")))
        un_item.setData(0, Qt.ItemDataRole.UserRole, "virtual://taxonomy/unclassified")
        if self.show_db_stats:
            un_item.setText(0, f"未分类 (图片: {unclassified_count})")
        try:
            root_path = str(self.settings_manager.get("general/root_path", "") or "")
        except Exception:
            root_path = ""
        try:
            groups = self.db.get_unclassified_folder_groups(root_path=root_path, table_name="bird_results") or []
        except Exception:
            groups = []
        try:
            from urllib.parse import quote
        except Exception:
            quote = None
        for g in (groups or []):
            try:
                folder_abs = str(g.get("folder") or "")
                rel = str(g.get("rel") or folder_abs)
                cnt = int(g.get("count") or 0)
            except Exception:
                continue
            if not folder_abs:
                continue
            label = rel
            if self.show_db_stats:
                label = f"{rel} (图片: {cnt})"
            child = QTreeWidgetItem(un_item, [label])
            child.setIcon(0, qta.icon('mdi6.folder', color=ColorManager.instance().get("theme.primary")))
            enc = folder_abs
            if quote:
                try:
                    enc = quote(folder_abs, safe="")
                except Exception:
                    enc = folder_abs
            child.setData(0, Qt.ItemDataRole.UserRole, f"virtual://taxonomy/unclassified?dir={enc}")
        
        # root_item.setExpanded(True)

    def add_root_folders(self, root_paths):
        """在现有树上追加多个根目录（用于导入页多选导入）"""
        def _norm(p):
            try:
                return os.path.normcase(os.path.normpath(str(p)))
            except Exception:
                return str(p)

        def _is_descendant(child, parent):
            if not child or not parent:
                return False
            if child == parent:
                return False
            if child.startswith(parent + os.sep):
                return True
            return False

        paths = root_paths or []
        if isinstance(paths, (str, bytes)):
            paths = [paths]
        try:
            paths = [str(p) for p in paths if p]
        except Exception:
            paths = []
        if not paths:
            return

        expanded_paths = self._collect_expanded_paths()
        root = self.folder_tree.invisibleRootItem()

        existing_items = []
        for i in range(root.childCount()):
            it = root.child(i)
            p = it.data(0, Qt.ItemDataRole.UserRole)
            if p:
                existing_items.append((it, _norm(p)))

        try:
            paths_sorted = sorted(paths, key=lambda x: len(_norm(x)))
        except Exception:
            paths_sorted = paths

        for p in paths_sorted:
            np = _norm(p)
            if not np:
                continue

            already = False
            for it, n_it in list(existing_items):
                if n_it == np:
                    already = True
                    try:
                        self.refresh_root(p, expanded_paths=expanded_paths)
                    except Exception:
                        pass
                    break
            if already:
                continue

            covered_by_existing = False
            for _it, n_it in existing_items:
                if _is_descendant(np, n_it):
                    covered_by_existing = True
                    break
            if covered_by_existing:
                continue

            to_move = []
            for it, n_it in list(existing_items):
                if _is_descendant(n_it, np):
                    to_move.append((it, n_it))

            new_root_item = self._append_root(p, expanded_paths=expanded_paths)
            if new_root_item is None:
                continue

            if to_move:
                for old_item, old_norm in to_move:
                    try:
                        old_path = old_item.data(0, Qt.ItemDataRole.UserRole)
                    except Exception:
                        old_path = None

                    try:
                        for j in range(new_root_item.childCount()):
                            child = new_root_item.child(j)
                            cp = child.data(0, Qt.ItemDataRole.UserRole)
                            if cp and _norm(cp) == old_norm:
                                new_root_item.removeChild(child)
                                break
                    except Exception:
                        pass

                    try:
                        idx = -1
                        for k in range(root.childCount()):
                            if root.child(k) is old_item:
                                idx = k
                                break
                        if idx >= 0:
                            moved = root.takeChild(idx)
                        else:
                            moved = old_item
                    except Exception:
                        moved = old_item

                    try:
                        folder_icon_color = ColorManager.instance().get("theme.primary")
                        moved.setIcon(0, qta.icon('mdi6.folder', color=folder_icon_color))
                        if old_path:
                            moved.setText(0, os.path.basename(str(old_path)) or str(old_path))
                            try:
                                moved.setToolTip(0, str(old_path))
                            except Exception:
                                pass
                            moved.setText(1, self._get_sort_key(os.path.basename(str(old_path)) or str(old_path)))
                    except Exception:
                        pass

                    try:
                        new_root_item.addChild(moved)
                    except Exception:
                        pass

                try:
                    new_root_item.sortChildren(1, Qt.SortOrder.AscendingOrder)
                except Exception:
                    pass

                existing_items = [(it, n) for it, n in existing_items if not _is_descendant(n, np) and n != np]
                existing_items.append((new_root_item, np))
            else:
                existing_items.append((new_root_item, np))

    def refresh_root(self, root_path, expanded_paths=None):
        """刷新某个根目录节点（不清空整个树）"""
        if not root_path:
            return
        if expanded_paths is None:
            expanded_paths = self._collect_expanded_paths()
        target = os.path.normcase(os.path.normpath(root_path))
        root = self.folder_tree.invisibleRootItem()
        for i in range(root.childCount()):
            it = root.child(i)
            p = it.data(0, Qt.ItemDataRole.UserRole)
            if not p:
                continue
            try:
                if os.path.normcase(os.path.normpath(p)) == target:
                    it.takeChildren()
                    self._add_subfolders(it, p, depth=0, max_depth=1)
                    for j in range(it.childCount()):
                        child = it.child(j)
                        child_path = child.data(0, Qt.ItemDataRole.UserRole)
                        if child_path and os.path.normcase(os.path.normpath(child_path)) in expanded_paths:
                            child.setExpanded(True)
                            self._refresh_item_children(child, child_path, expanded_paths)
                    it.setExpanded(True)
                    return
            except Exception:
                continue

    def _append_root(self, root_path, expanded_paths=None):
        if not root_path:
            return None
        if expanded_paths is None:
            expanded_paths = set()
        root_item = QTreeWidgetItem(self.folder_tree, [root_path])
        icon_color = ColorManager.instance().get("theme.text.dark")
        root_item.setIcon(0, qta.icon('mdi6.harddisk', color=icon_color))
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
        root_item.setText(0, root_path)
        self._add_subfolders(root_item, root_path, depth=0, max_depth=1)
        # root_item.setExpanded(True)
        return root_item

    def refresh_tree(self, root_path=None, target_path=None):
        if str(self.context or "").lower() == "library":
            expanded_roles = set()
            current_role = None
            scroll_val = None
            try:
                expanded_roles = self._collect_expanded_roles()
            except Exception:
                expanded_roles = set()
            try:
                it = self.folder_tree.currentItem()
                current_role = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
            except Exception:
                current_role = None
            try:
                scroll_val = self.folder_tree.verticalScrollBar().value()
            except Exception:
                scroll_val = None

            title = root_path
            if not title and self.folder_tree.topLevelItemCount() > 0:
                try:
                    title = self.folder_tree.topLevelItem(0).text(0)
                except Exception:
                    title = ""
            try:
                self.folder_tree.blockSignals(True)
            except Exception:
                pass
            try:
                self.populate_tree(title or (root_path or ""))
                try:
                    if expanded_roles:
                        self._restore_expanded_roles(expanded_roles)
                except Exception:
                    pass
                try:
                    if current_role:
                        found = self._find_item_by_role(current_role)
                        if found is not None:
                            try:
                                self.folder_tree.setCurrentItem(found)
                            except Exception:
                                pass
                            try:
                                p = found.parent()
                                while p is not None:
                                    p.setExpanded(True)
                                    p = p.parent()
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    if scroll_val is not None:
                        self.folder_tree.verticalScrollBar().setValue(int(scroll_val))
                except Exception:
                    pass
            finally:
                try:
                    self.folder_tree.blockSignals(False)
                except Exception:
                    pass
            return
        if self.folder_tree.topLevelItemCount() == 0:
            if root_path:
                self.populate_tree(root_path)
            return

        root_item = self.folder_tree.topLevelItem(0)
        current_root = root_item.data(0, Qt.ItemDataRole.UserRole)
        if root_path and current_root:
            if os.path.normcase(os.path.normpath(root_path)) != os.path.normcase(os.path.normpath(current_root)):
                self.populate_tree(root_path)
                return

        expanded_paths = self._collect_expanded_paths()
        if target_path:
            p = os.path.normcase(os.path.normpath(target_path))
            while p:
                expanded_paths.add(p)
                parent = os.path.dirname(p)
                if parent == p:
                    break
                p = parent

        if self.show_db_stats and current_root:
            try:
                stats = self.db.get_folder_stats() 
                species_count = stats.get('species_count', 0)
                image_count = stats.get('image_count', 0)
                root_item.setText(0, f"{current_root} (物种: {species_count}, 图片: {image_count})")
            except Exception:
                root_item.setText(0, current_root)
        elif current_root:
            root_item.setText(0, current_root)

        self._refresh_item_children(root_item, current_root, expanded_paths)
        # root_item.setExpanded(True)

    def _collect_expanded_paths(self):
        expanded = set()
        root = self.folder_tree.invisibleRootItem()
        for i in range(root.childCount()):
            self._collect_expanded_paths_from_item(root.child(i), expanded)
        return expanded

    def _collect_expanded_paths_from_item(self, item, expanded):
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and item.isExpanded():
            expanded.add(os.path.normcase(os.path.normpath(path)))
        for i in range(item.childCount()):
            self._collect_expanded_paths_from_item(item.child(i), expanded)

    def _collect_expanded_roles(self):
        expanded = set()
        root = self.folder_tree.invisibleRootItem()
        for i in range(root.childCount()):
            self._collect_expanded_roles_from_item(root.child(i), expanded)
        return expanded

    def _collect_expanded_roles_from_item(self, item, expanded):
        if not item:
            return
        try:
            role = item.data(0, Qt.ItemDataRole.UserRole)
        except Exception:
            role = None
        if role and item.isExpanded():
            expanded.add(str(role))
        for i in range(item.childCount()):
            self._collect_expanded_roles_from_item(item.child(i), expanded)

    def _restore_expanded_roles(self, expanded_roles: set):
        if not expanded_roles:
            return
        root = self.folder_tree.invisibleRootItem()
        for i in range(root.childCount()):
            self._restore_expanded_roles_on_item(root.child(i), expanded_roles)

    def _restore_expanded_roles_on_item(self, item, expanded_roles: set):
        if not item:
            return
        try:
            role = item.data(0, Qt.ItemDataRole.UserRole)
        except Exception:
            role = None
        if role is not None and str(role) in expanded_roles:
            try:
                item.setExpanded(True)
            except Exception:
                pass
        for i in range(item.childCount()):
            self._restore_expanded_roles_on_item(item.child(i), expanded_roles)

    def _find_item_by_role(self, role_value):
        if role_value is None:
            return None
        target = str(role_value)
        root = self.folder_tree.invisibleRootItem()
        stack = []
        try:
            for i in range(root.childCount()):
                it = root.child(i)
                if it is not None:
                    stack.append(it)
        except Exception:
            stack = []
        while stack:
            it = stack.pop()
            try:
                role = it.data(0, Qt.ItemDataRole.UserRole)
            except Exception:
                role = None
            if role is not None and str(role) == target:
                return it
            try:
                for j in range(it.childCount()):
                    c = it.child(j)
                    if c is not None:
                        stack.append(c)
            except Exception:
                pass
        return None

    def _get_item_depth(self, item):
        depth = 0
        temp = item
        while temp and temp.parent():
            depth += 1
            temp = temp.parent()
        return depth

    def _refresh_item_children(self, item, path, expanded_paths):
        if not item or not path or not os.path.exists(path):
            return
        item.takeChildren()
        depth = self._get_item_depth(item)
        self._add_subfolders(item, path, depth=depth, max_depth=1)
        for i in range(item.childCount()):
            child = item.child(i)
            child_path = child.data(0, Qt.ItemDataRole.UserRole)
            if child_path and os.path.normcase(os.path.normpath(child_path)) in expanded_paths:
                child.setExpanded(True)
                self._refresh_item_children(child, child_path, expanded_paths)

    def _add_subfolders(self, parent_item, path, depth, max_depth):
        try:
            if isinstance(path, str) and path.startswith("virtual://"):
                return
        except Exception:
            pass
        bird_strict = self._is_strict_mode()
            
        if bird_strict and depth >= 4:
            return

        try:
            entries = sorted(os.listdir(path))
            for entry in entries:
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    if entry.startswith('.') or entry.startswith('$'):
                        continue
                        
                    if bird_strict:
                        if depth == 0 and not entry.endswith("目"): continue
                        elif depth == 1 and not entry.endswith("科"): continue
                        elif depth == 2 and not entry.endswith("属"): continue
                            
                    child_item = QTreeWidgetItem(parent_item, [entry])
                    folder_icon_color = ColorManager.instance().get("theme.primary")
                    child_item.setIcon(0, qta.icon('mdi6.folder', color=folder_icon_color))
                    child_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
                    child_item.setText(1, self._get_sort_key(entry))
                    
                    if bird_strict and depth >= 3:
                        continue

                    if depth < max_depth:
                        self._add_subfolders(child_item, full_path, depth + 1, max_depth)
                    else:
                        try:
                            placeholder = QTreeWidgetItem(child_item, ["加载中..."])
                            loading_icon_color = ColorManager.instance().get("theme.text.light")
                            placeholder.setIcon(0, qta.icon('mdi6.loading', color=loading_icon_color))
                            placeholder.setData(0, Qt.ItemDataRole.UserRole, "__placeholder__")
                        except PermissionError:
                            pass
        except PermissionError:
            pass
        except Exception as e:
            try:
                LogManager.instance().warning(f"读取文件夹失败: {path}, 错误: {e}")
            except Exception:
                pass

    def on_folder_expanded(self, item):
        if item.childCount() == 1:
            child = item.child(0)
            if child and child.data(0, Qt.ItemDataRole.UserRole) == "__placeholder__":
                folder_path = item.data(0, Qt.ItemDataRole.UserRole)
                if folder_path:
                    try:
                        if isinstance(folder_path, str) and folder_path.startswith("virtual://"):
                            return
                    except Exception:
                        pass
                    item.removeChild(child)
                    current_depth = 0
                    temp = item
                    while temp.parent():
                        current_depth += 1
                        temp = temp.parent()
                    
                    self._add_subfolders(item, folder_path, depth=current_depth, max_depth=1)
                    try:
                        suppress_auto = bool(getattr(self, "_shortcut_nav_guard", False))
                    except Exception:
                        suppress_auto = False
                    if not suppress_auto and item.childCount() == 1:
                        single_child = item.child(0)
                        if single_child.childCount() > 0 or single_child.data(0, Qt.ItemDataRole.UserRole) != "__placeholder__":
                            single_child.setExpanded(True)

    def locate_taxonomy_node(self, order=None, family=None, genus=None, species=None, file_path=None, emit_signal=False):
        """Locate and select the taxonomy node in the tree."""
        if not self.folder_tree or not self.folder_tree.invisibleRootItem():
            return
            
        root = self.folder_tree.topLevelItem(0)
        if not root:
            return

        def _norm(s):
            return str(s or "").strip()

        order = _norm(order)
        family = _norm(family)
        genus = _norm(genus)
        species = _norm(species)

        if not emit_signal:
            self.folder_tree.blockSignals(True)

        try:
            # Case 1: Unclassified
            if not (order and family and genus and species):
                un_item = None
                for i in range(root.childCount()):
                    child = root.child(i)
                    data = str(child.data(0, Qt.ItemDataRole.UserRole) or "")
                    if "virtual://taxonomy/unclassified" in data and "dir=" not in data:
                        un_item = child
                        break
                
                if not un_item:
                    return

                # Don't expand/select unclassified root by default if we can't find specific folder
                # unless the user is explicitly browsing unclassified items (which is handled by selection logic elsewhere)
                target_item = None

                if file_path:
                    try:
                        file_dir = os.path.dirname(file_path)
                        # Normalize paths for comparison
                        norm_file_dir = os.path.normcase(os.path.normpath(file_dir))
                        
                        un_item.setExpanded(True) # Expand to search children
                        
                        for i in range(un_item.childCount()):
                            child = un_item.child(i)
                            data = str(child.data(0, Qt.ItemDataRole.UserRole) or "")
                            if "dir=" in data:
                                try:
                                    from urllib.parse import unquote
                                    enc = data.split("dir=")[1]
                                    grp_dir = unquote(enc)
                                    norm_grp = os.path.normcase(os.path.normpath(grp_dir))
                                    if norm_file_dir == norm_grp:
                                        target_item = child
                                        break
                                    # Handle case where file_path is inside a subfolder of the group folder
                                    if norm_file_dir.startswith(norm_grp + os.sep):
                                        target_item = child
                                        break
                                except:
                                    pass
                    except:
                        pass
                
                if target_item:
                    self.folder_tree.setCurrentItem(target_item)
                    target_item.setSelected(True)
                    self.folder_tree.scrollToItem(target_item)
                # Else: do nothing, don't jump to unclassified root
                return

            # Case 2: Classified
            current_item = root
            
            # Find Order
            found = False
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                data = str(child.data(0, Qt.ItemDataRole.UserRole) or "")
                if f"order={order}" in data and "family=" not in data:
                    current_item = child
                    current_item.setExpanded(True)
                    found = True
                    break
            if not found: return

            # Find Family
            found = False
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                data = str(child.data(0, Qt.ItemDataRole.UserRole) or "")
                if f"family={family}" in data and "genus=" not in data:
                    current_item = child
                    current_item.setExpanded(True)
                    found = True
                    break
            if not found:
                self.folder_tree.setCurrentItem(current_item)
                self.folder_tree.scrollToItem(current_item)
                return

            # Find Genus
            found = False
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                data = str(child.data(0, Qt.ItemDataRole.UserRole) or "")
                if f"genus={genus}" in data and "species=" not in data:
                    current_item = child
                    current_item.setExpanded(True)
                    found = True
                    break
            if not found:
                self.folder_tree.setCurrentItem(current_item)
                self.folder_tree.scrollToItem(current_item)
                return

            # Find Species
            found = False
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                data = str(child.data(0, Qt.ItemDataRole.UserRole) or "")
                if f"species={species}" in data:
                    current_item = child
                    found = True
                    break
            
            self.folder_tree.setCurrentItem(current_item)
            current_item.setSelected(True)
            self.folder_tree.scrollToItem(current_item)

        except Exception as e:
            try:
                LogManager.instance().warning(f"Locate taxonomy node error: {e}")
            except:
                pass
        finally:
            if not emit_signal:
                self.folder_tree.blockSignals(False)

    def on_tree_selection_changed(self):
        selected_items = self.folder_tree.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_path or folder_path == "__placeholder__":
            return

        try:
            if isinstance(folder_path, str) and folder_path.startswith("virtual://"):
                depth = 0
                temp = item
                while temp.parent():
                    depth += 1
                    temp = temp.parent()
                self.folderSelected.emit(folder_path, depth)
                return
        except Exception:
            pass
        
        if os.path.isfile(folder_path):
            folder_path = os.path.dirname(folder_path)
        if not os.path.isdir(folder_path):
            return

        # Calculate depth
        depth = 0
        temp = item
        while temp.parent():
            depth += 1
            temp = temp.parent()
            
        self.folderSelected.emit(folder_path, depth)

    def on_tree_item_clicked(self, item, column):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path == "__recycle_bin__":
            self.folderClicked.emit(path)
            return
            
        if path and path != "__placeholder__":
             try:
                 if not bool(getattr(self, "_upper_nav_guard", False)):
                     self._upper_nav_stack = []
             except Exception:
                 pass
             if os.path.isfile(path):
                 path = os.path.dirname(path)
             
             # Calculate depth for virtual paths too if needed, or just pass 0
             depth = 0
             temp = item
             while temp.parent():
                 depth += 1
                 temp = temp.parent()

             # Emit both signals to ensure correct handling
             self.folderClicked.emit(path)
             
             # For virtual paths (taxonomy), we also want to emit folderSelected to trigger load
             # because on_tree_selection_changed might not fire if item is already selected
             if isinstance(path, str) and path.startswith("virtual://"):
                 self.folderSelected.emit(path, depth)
             elif os.path.isdir(path):
                 self.folderSelected.emit(path, depth)

    def toggle_search_panel(self, checked):
        if checked:
            container_pos = self.search_container.pos()
            panel_width = min(220, max(180, self.width() - 8))
            panel_x = container_pos.x() + 4
            panel_y = container_pos.y() + self.search_container.height() + 2
            self.search_panel.setFixedWidth(panel_width)
            self.search_panel.move(panel_x, panel_y)
            self.search_panel.show()
            self.search_panel.raise_()
            self.search_input.setFocus()
        else:
            self.search_panel.hide()
            self.search_results.hide()
            self.search_input.clear()

    def on_search_text_changed(self, text):
        if not text.strip():
            self.search_results.hide()
            return
        results = self._search_folders(text.strip())
        self.search_results.clear()
        for folder_name, folder_path in results[:20]:
            item = QListWidgetItem(str(folder_name))
            item.setData(Qt.ItemDataRole.UserRole, folder_path)
            item.setToolTip(folder_path)
            try:
                icon_color = ColorManager.instance().get("theme.primary")
                item.setIcon(qta.icon("mdi6.folder", color=icon_color))
            except Exception:
                pass
            self.search_results.addItem(item)
        if results:
            search_pos = self.search_panel.mapTo(self, self.search_input.geometry().bottomLeft())
            panel_pos = self.search_panel.pos()
            self.search_results.setFixedWidth(self.search_panel.width())
            self.search_results.move(panel_pos.x(), panel_pos.y() + self.search_panel.height())
            self.search_results.show()
            self.search_results.raise_()
        else:
            self.search_results.hide()

    def _search_folders(self, keyword):
        results = []
        query = str(keyword or "").strip()
        if not query:
            return results

        def _norm(s: str) -> str:
            if s is None:
                return ""
            try:
                t = str(s).lower()
            except Exception:
                t = ""
            return "".join(ch for ch in t if not ch.isspace())

        def _strip_stats(label: str) -> str:
            if not label:
                return ""
            s = str(label)
            idx = s.rfind(" (")
            if idx > 0:
                s = s[:idx]
            return s.strip()

        def _pinyin_full_and_initials(s: str) -> tuple[str, str]:
            if not s:
                return "", ""
            if lazy_pinyin is None:
                return "", ""
            try:
                parts = lazy_pinyin(s) or []
            except Exception:
                parts = []
            full = "".join(str(p or "") for p in parts)
            initials = "".join((str(p or "")[0:1]) for p in parts if p)
            return _norm(full), _norm(initials)

        tokens = [_norm(t) for t in query.split() if _norm(t)]
        if not tokens:
            return results

        is_library = str(getattr(self, "context", "") or "").lower() == "library"

        def _item_label(item, folder_path):
            try:
                if is_library:
                    t = _strip_stats(item.text(0))
                    return t or _strip_stats(os.path.basename(str(folder_path or ""))) or str(folder_path or "")
                return _strip_stats(os.path.basename(str(folder_path or "")) or str(folder_path or ""))
            except Exception:
                return str(folder_path or "")

        def _matches(label: str) -> bool:
            base = _norm(label)
            py_full, py_init = _pinyin_full_and_initials(label)
            for tk in tokens:
                if not tk:
                    continue
                if tk in base:
                    continue
                if py_full and tk in py_full:
                    continue
                if py_init and tk in py_init:
                    continue
                return False
            return True

        def _search_item(item):
            folder_path = item.data(0, Qt.ItemDataRole.UserRole)
            if folder_path and folder_path != "__placeholder__":
                try:
                    fp = str(folder_path)
                except Exception:
                    fp = folder_path
                if is_library and fp == "virtual://taxonomy/root":
                    pass
                else:
                    folder_name = _item_label(item, fp)
                    if _matches(folder_name):
                        results.append((folder_name, fp))
            for i in range(item.childCount()):
                _search_item(item.child(i))
                
        root = self.folder_tree.invisibleRootItem()
        for i in range(root.childCount()):
            _search_item(root.child(i))
            
        if (not is_library) and len(results) < 20:
            root_path = self.settings_manager.get("general/root_path", "D:/")
            self._search_filesystem(root_path, _norm(query), results, max_results=20)
            
        return results

    def _search_filesystem(self, root_path, keyword, results, max_results=20):
        if not os.path.exists(root_path): return
        
        bird_strict = self._is_strict_mode()

        try:
            for root, dirs, files in os.walk(root_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and not d.startswith('$')]
                
                if bird_strict:
                    rel_path = os.path.relpath(root, root_path)
                    if rel_path == '.': current_depth = 0
                    else: current_depth = len(rel_path.split(os.sep))
                    
                    if current_depth >= 4:
                        dirs[:] = []
                        continue
                        
                    valid_dirs = []
                    for d in dirs:
                        if current_depth == 0 and not d.endswith("目"): continue
                        elif current_depth == 1 and not d.endswith("科"): continue
                        elif current_depth == 2 and not d.endswith("属"): continue
                        valid_dirs.append(d)
                    dirs[:] = valid_dirs
                
                for d in dirs:
                    if keyword in d.lower():
                        full_path = os.path.join(root, d)
                        if not any(os.path.normpath(r[1]) == os.path.normpath(full_path) for r in results):
                            results.append((d, full_path))
                            if len(results) >= max_results:
                                return
        except Exception:
            pass

    def on_search_result_clicked(self, item):
        folder_path = item.data(Qt.ItemDataRole.UserRole)
        if folder_path:
            try:
                fp = str(folder_path)
            except Exception:
                fp = folder_path
            if isinstance(fp, str) and fp.startswith("virtual://"):
                found = self.navigate_to_virtual_folder(fp)
                if found:
                    try:
                        depth = 0
                        temp = found
                        while temp.parent():
                            depth += 1
                            temp = temp.parent()
                    except Exception:
                        depth = 0
                    try:
                        self.folderClicked.emit(fp)
                    except Exception:
                        pass
                    try:
                        self.folderSelected.emit(fp, depth)
                    except Exception:
                        pass
            else:
                self.navigate_to_folder(fp)
        self.search_results.hide()
        self.search_input.clear()
        self.search_btn.setChecked(False)

    def navigate_to_virtual_folder(self, target_uri: str):
        if not target_uri or not getattr(self, "folder_tree", None):
            return None
        try:
            uri = str(target_uri)
        except Exception:
            uri = target_uri
        it = QTreeWidgetItemIterator(self.folder_tree)
        while it.value():
            cur = it.value()
            try:
                data = cur.data(0, Qt.ItemDataRole.UserRole)
            except Exception:
                data = None
            if data == uri:
                p = cur.parent()
                while p:
                    try:
                        p.setExpanded(True)
                    except Exception:
                        pass
                    p = p.parent()
                try:
                    self.folder_tree.setCurrentItem(cur)
                    self.folder_tree.scrollToItem(cur)
                except Exception:
                    pass
                return cur
            it += 1
        return None

    def navigate_to_folder(self, target_path):
        target_path = os.path.normcase(os.path.normpath(target_path))
        
        def _find_and_expand(item, path_parts, current_depth):
            if current_depth >= len(path_parts):
                return item
            target_name = path_parts[current_depth]
            
            if item.childCount() == 1:
                child = item.child(0)
                if child and child.data(0, Qt.ItemDataRole.UserRole) == "__placeholder__":
                    item.removeChild(child)
                    folder_path = item.data(0, Qt.ItemDataRole.UserRole)
                    if folder_path:
                        current_depth_in_tree = 0
                        temp = item
                        while temp.parent():
                            current_depth_in_tree += 1
                            temp = temp.parent()
                        self._add_subfolders(item, folder_path, depth=current_depth_in_tree, max_depth=1)

            for i in range(item.childCount()):
                child = item.child(i)
                child_path = child.data(0, Qt.ItemDataRole.UserRole)
                if child_path:
                    child_name = os.path.basename(child_path) or child_path
                    if child_name.lower() == target_name.lower():
                        item.setExpanded(True)
                        if current_depth == len(path_parts) - 1:
                            return child
                        return _find_and_expand(child, path_parts, current_depth + 1)
            return None

        root = self.folder_tree.invisibleRootItem()
        if root.childCount() == 0:
            return False

        for i in range(root.childCount()):
            root_item = root.child(i)
            root_path = root_item.data(0, Qt.ItemDataRole.UserRole)
            if not root_path:
                continue
            root_path = os.path.normcase(os.path.normpath(root_path))
            try:
                rel_path = os.path.relpath(target_path, root_path)
            except ValueError:
                continue
            if rel_path == '.':
                self.folder_tree.setCurrentItem(root_item)
                self.folder_tree.scrollToItem(root_item)
                return True
            if rel_path.startswith('..'):
                continue
            path_parts = rel_path.split(os.sep)
            found_item = _find_and_expand(root_item, path_parts, 0)
            if found_item:
                self.folder_tree.setCurrentItem(found_item)
                self.folder_tree.scrollToItem(found_item)
                return True

        return False

    def select_first_folder(self):
        """自动选择第一个文件夹"""
        if self.folder_tree.topLevelItemCount() == 0:
            return
        root_item = self.folder_tree.topLevelItem(0)
        if not root_item.isExpanded():
            root_item.setExpanded(True)
        try:
            it = QTreeWidgetItemIterator(self.folder_tree, QTreeWidgetItemIterator.IteratorFlag.Visible)
        except Exception:
            it = QTreeWidgetItemIterator(self.folder_tree)
        skipped_first = False
        while it.value():
            item = it.value()
            if not skipped_first:
                skipped_first = True
                it += 1
                continue
            try:
                data = item.data(0, Qt.ItemDataRole.UserRole)
            except Exception:
                data = None
            try:
                if str(data) == "__recycle_bin__":
                    it += 1
                    continue
            except Exception:
                pass
            if self._select_folder_item(item):
                return
            it += 1
        self._select_folder_item(root_item)

    def _is_navigable_folder_item(self, item: QTreeWidgetItem) -> bool:
        if item is None:
            return False
        try:
            data = item.data(0, Qt.ItemDataRole.UserRole)
        except Exception:
            data = None
        if not data:
            return False
        try:
            if str(data) == "__placeholder__":
                return False
        except Exception:
            return False
        return True

    def _select_folder_item(self, item: QTreeWidgetItem) -> bool:
        if not self._is_navigable_folder_item(item):
            return False
        try:
            self.folder_tree.setCurrentItem(item)
            self.folder_tree.scrollToItem(item)
        except Exception:
            return False
        return True

    def select_prev_visible_folder(self) -> bool:
        try:
            self._set_shortcut_nav_guard()
        except Exception:
            pass
        try:
            cur = self.folder_tree.currentItem()
        except Exception:
            cur = None
        items = []
        try:
            it = QTreeWidgetItemIterator(self.folder_tree, QTreeWidgetItemIterator.IteratorFlag.Visible)
        except Exception:
            it = QTreeWidgetItemIterator(self.folder_tree)
        while it.value():
            v = it.value()
            if self._is_navigable_folder_item(v):
                items.append(v)
            it += 1
        if not items:
            return False
        idx = -1
        try:
            if cur in items:
                idx = items.index(cur)
        except Exception:
            idx = -1
        if idx < 0:
            return self._select_folder_item(items[0])
        if idx <= 0:
            return False
        return self._select_folder_item(items[idx - 1])

    def select_next_visible_folder(self) -> bool:
        try:
            self._set_shortcut_nav_guard()
        except Exception:
            pass
        try:
            cur = self.folder_tree.currentItem()
        except Exception:
            cur = None
        items = []
        try:
            it = QTreeWidgetItemIterator(self.folder_tree, QTreeWidgetItemIterator.IteratorFlag.Visible)
        except Exception:
            it = QTreeWidgetItemIterator(self.folder_tree)
        while it.value():
            v = it.value()
            if self._is_navigable_folder_item(v):
                items.append(v)
            it += 1
        if not items:
            return False
        idx = -1
        try:
            if cur in items:
                idx = items.index(cur)
        except Exception:
            idx = -1
        if idx < 0:
            return self._select_folder_item(items[0])
        if idx >= len(items) - 1:
            return False
        return self._select_folder_item(items[idx + 1])

    def select_prev_sibling_folder(self) -> bool:
        try:
            self._set_shortcut_nav_guard()
        except Exception:
            pass
        try:
            cur = self.folder_tree.currentItem()
        except Exception:
            cur = None
        if cur is None:
            return False
        parent = cur.parent()
        container = parent if parent is not None else self.folder_tree.invisibleRootItem()
        try:
            idx = int(container.indexOfChild(cur))
        except Exception:
            return False
        for j in range(idx - 1, -1, -1):
            try:
                cand = container.child(j)
            except Exception:
                cand = None
            if self._is_navigable_folder_item(cand):
                return self._select_folder_item(cand)
        return False

    def select_next_sibling_folder(self) -> bool:
        try:
            self._set_shortcut_nav_guard()
        except Exception:
            pass
        try:
            cur = self.folder_tree.currentItem()
        except Exception:
            cur = None
        if cur is None:
            return False
        parent = cur.parent()
        container = parent if parent is not None else self.folder_tree.invisibleRootItem()
        try:
            idx = int(container.indexOfChild(cur))
        except Exception:
            return False
        try:
            n = int(container.childCount())
        except Exception:
            n = 0
        for j in range(idx + 1, n):
            try:
                cand = container.child(j)
            except Exception:
                cand = None
            if self._is_navigable_folder_item(cand):
                return self._select_folder_item(cand)
        return False

    def select_parent_folder_level(self, level: int = 1) -> bool:
        try:
            level = int(level)
        except Exception:
            level = 1
        level = max(1, min(20, level))
        try:
            cur = self.folder_tree.currentItem()
        except Exception:
            cur = None
        if cur is None:
            return False
        p = cur
        for _ in range(level):
            try:
                p = p.parent()
            except Exception:
                p = None
            if p is None:
                return False
        return self._select_folder_item(p)

    def select_prev_upper_folder(self) -> bool:
        try:
            self._set_shortcut_nav_guard()
        except Exception:
            pass
        try:
            cur = self.folder_tree.currentItem()
        except Exception:
            cur = None
        if cur is None:
            return False
        try:
            parent = cur.parent()
        except Exception:
            parent = None
        if parent is None:
            return False
        try:
            if parent.parent() is None:
                return False
        except Exception:
            return False
        return self._select_folder_item(parent)

    def select_next_upper_folder(self) -> bool:
        try:
            self._set_shortcut_nav_guard()
        except Exception:
            pass
        try:
            cur = self.folder_tree.currentItem()
        except Exception:
            cur = None
        if cur is None:
            return False
        try:
            parent = cur.parent()
        except Exception:
            parent = None
        if parent is None:
            return False
        try:
            grandparent = parent.parent()
        except Exception:
            grandparent = None
        if grandparent is None:
            return False
        try:
            idx = int(grandparent.indexOfChild(parent))
        except Exception:
            idx = -1
        try:
            n = int(grandparent.childCount())
        except Exception:
            n = 0
        if idx < 0 or n <= 0:
            return False
        for j in range(idx + 1, n):
            try:
                cand = grandparent.child(j)
            except Exception:
                cand = None
            if self._is_navigable_folder_item(cand):
                return self._select_folder_item(cand)
        return False

    def on_context_menu(self, position):
        item = self.folder_tree.itemAt(position)
        if not item: return
        
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or path == "__placeholder__": return
        try:
            if isinstance(path, str) and path.startswith("virtual://taxonomy"):
                return
        except Exception:
            pass
        try:
            if str(getattr(self, "context", "library") or "").lower() == "library":
                base = os.path.basename(str(path))
                if base == "未分类":
                    return
        except Exception:
            pass
            
        menu = QMenu(self)
        self.style_menu(menu)

        is_import_context = getattr(self, "context", "library") == "import"
        is_root_item = item.parent() is None

        # New Folder
        new_folder_action = menu.addAction(qta.icon('mdi6.folder-plus', color='#555'), "新建文件夹")
        new_folder_action.triggered.connect(self.create_new_folder)
        
        menu.addSeparator()

        if item.parent():
            rename_action = menu.addAction(qta.icon('mdi6.rename-box', color='#555'), "重命名")
            rename_action.triggered.connect(lambda: self.rename_folder(item))
            
        if is_import_context:
            if is_root_item:
                try:
                    remove_action = menu.addAction(qta.icon('mdi6.folder-remove', color='#555'), "移除文件夹")
                except Exception:
                    remove_action = menu.addAction("移除文件夹")
                remove_action.triggered.connect(lambda: self.remove_folder_from_tree(item))
            delete_action = menu.addAction(qta.icon('mdi6.trash-can-outline', color='#e74c3c'), "删除文件夹")
            delete_action.triggered.connect(lambda: self.delete_folder_item(item, allow_root_delete=True))
            menu.addSeparator()
        else:
            if item.parent():
                delete_action = menu.addAction(qta.icon('mdi6.trash-can-outline', color='#e74c3c'), "删除")
                delete_action.triggered.connect(self.delete_folder)
                menu.addSeparator()

        if os.path.exists(path):
            open_action = menu.addAction(qta.icon('mdi6.folder-open', color='#555'), "在文件管理器中打开")
            open_action.triggered.connect(lambda: self.open_in_explorer(path))

        menu.exec(self.folder_tree.viewport().mapToGlobal(position))

    def style_menu(self, menu):
        cm = ColorManager.instance()
        menu_bg = cm.get("theme.background.light")
        menu_border = cm.get("popup.border.primary")
        menu_text = cm.get("theme.text.dark")
        menu_hover = cm.get("theme.background.dark")
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {menu_bg};
                border: 1px solid {menu_border};
                padding: 2px;
            }}
            QMenu::item {{
                padding: 4px 20px 4px 30px;
                border: none;
                color: {menu_text};
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
                color: {menu_text};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {menu_border};
                margin: 2px 4px;
            }}
        """)

    def create_new_folder(self):
        """新建文件夹"""
        current_item = self.folder_tree.currentItem()
        if not current_item:
            return

        folder_path = current_item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_path or not os.path.isdir(folder_path):
            return

        # 计算当前深度
        depth = 0
        temp = current_item
        while temp.parent():
            depth += 1
            temp = temp.parent()

        # 检查严格模式
        bird_strict = self._is_strict_mode()

        # 确定目标父目录和父节点
        target_parent_path = folder_path
        target_parent_item = current_item
        
        # 如果是严格模式且处于种级目录(depth=4)，则创建平行目录(在属级目录下创建)
        # 注意：这里假设 depth 是从 root (0) 开始
        # 这里的 depth 计算方式和 ImageLibraryPage 保持一致
        if bird_strict and depth == 4:
            target_parent_path = os.path.dirname(folder_path)
            target_parent_item = current_item.parent()

        new_name, ok = CustomInputDialog.getText(self, "新建文件夹", "文件夹名称:", text="新建文件夹")
        if ok and new_name:
            # 检查非法字符
            if any(c in new_name for c in '<>:"/\\|?*'):
                 NotificationManager.instance().show_warning("错误", "文件名包含非法字符")
                 return
                 
            new_path = os.path.join(target_parent_path, new_name)
            if os.path.exists(new_path):
                NotificationManager.instance().show_warning("错误", "文件夹已存在")
                return
                
            try:
                os.mkdir(new_path)
                # 刷新文件夹树中目标父节点
                if target_parent_item:
                    # 手动添加子节点，避免完全重载
                    child_item = QTreeWidgetItem(target_parent_item, [new_name])
                    icon_color = ColorManager.instance().get("theme.primary")
                    child_item.setIcon(0, qta.icon("mdi6.folder", color=icon_color))
                    child_item.setData(0, Qt.ItemDataRole.UserRole, new_path)
                    child_item.setText(1, self._get_sort_key(new_name))
                    target_parent_item.setExpanded(True)
                    self.folder_tree.sortItems(1, Qt.SortOrder.AscendingOrder)
            except Exception as e:
                 NotificationManager.instance().show_warning("错误", f"新建文件夹失败: {e}")

    def delete_folder(self):
        """删除当前文件夹"""
        tree = getattr(self, "folder_tree", None)
        if tree is None:
            return
        try:
            items = list(tree.selectedItems() or [])
        except Exception:
            items = []
        if not items:
            try:
                it0 = tree.currentItem()
                if it0 is not None:
                    items = [it0]
            except Exception:
                items = []
        if not items:
            return

        targets = []
        for it in items:
            try:
                if it is None:
                    continue
                if it.parent() is None:
                    continue
                p = it.data(0, Qt.ItemDataRole.UserRole)
            except Exception:
                p = None
            try:
                p = str(p or "")
            except Exception:
                p = ""
            if not p or p == "__placeholder__":
                continue
            try:
                if not os.path.exists(p):
                    continue
            except Exception:
                continue
            targets.append((it, p))
        if not targets:
            NotificationManager.instance().show_warning("提示", "不能删除根目录")
            return

        sample = ""
        try:
            sample = "\n".join([x[1] for x in targets[:3]])
            if len(targets) > 3:
                sample = sample + f"\n...（共 {len(targets)} 个）"
        except Exception:
            sample = ""

        if not NotificationManager.instance().ask_confirmation(
            "确认删除",
            f"确定要删除选中的 {len(targets)} 个文件夹及其所有内容吗？\n{sample}\n此操作不可恢复！",
        ):
            return

        import shutil
        failed = []
        deleted_paths = []
        for it, path in targets:
            try:
                shutil.rmtree(path)
                deleted_paths.append(path)
                parent = it.parent()
                if parent is not None:
                    parent.removeChild(it)
            except Exception as e:
                failed.append(f"{path}（{e}）")
                continue

        try:
            if tree.topLevelItemCount() > 0:
                tree.setCurrentItem(tree.topLevelItem(0))
                self.on_tree_selection_changed()
        except Exception:
            pass

        for p in deleted_paths:
            try:
                self.folderDeletedOnDisk.emit(p)
            except Exception:
                pass

        if failed:
            NotificationManager.instance().show_warning("错误", "部分文件夹删除失败：\n" + "\n".join(failed[:8]))

    def delete_folder_item(self, item, allow_root_delete=False):
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or not os.path.exists(path):
            return
        if item.parent() is None and not allow_root_delete:
            NotificationManager.instance().show_warning("提示", "不能删除根目录")
            return
        if not NotificationManager.instance().ask_confirmation("确认删除", f"确定要删除文件夹及其所有内容吗？\n{path}\n此操作不可恢复！"):
            return
        try:
            import shutil
            shutil.rmtree(path)
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"删除失败: {e}")
            return
        try:
            self.remove_folder_from_tree(item, emit_signal=False)
        except Exception:
            pass
        try:
            self.folderDeletedOnDisk.emit(path)
        except Exception:
            pass

    def remove_folder_from_tree(self, item, emit_signal=True):
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or path == "__placeholder__":
            return
        is_root_item = item.parent() is None
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
            self.folder_tree.setCurrentItem(parent)
            try:
                self.on_tree_selection_changed()
            except Exception:
                pass
        else:
            try:
                idx = int(self.folder_tree.indexOfTopLevelItem(item))
            except Exception:
                idx = -1
            if idx >= 0:
                try:
                    self.folder_tree.takeTopLevelItem(idx)
                except Exception:
                    pass
            else:
                root = self.folder_tree.invisibleRootItem()
                for i in range(root.childCount()):
                    if root.child(i) is item:
                        root.removeChild(item)
                        break
            try:
                if self.folder_tree.topLevelItemCount() > 0:
                    self.folder_tree.setCurrentItem(self.folder_tree.topLevelItem(0))
                    self.on_tree_selection_changed()
            except Exception:
                pass
        if is_root_item and str(self.context or "").lower() == "import":
            try:
                removed = os.path.normcase(os.path.normpath(str(path)))
            except Exception:
                removed = str(path)
            out = self._collect_import_root_paths_from_tree()
            try:
                self.settings_manager.set("import/root_paths", out)
                try:
                    last_path = str(self.settings_manager.get("import/last_path", "") or "")
                except Exception:
                    last_path = ""
                try:
                    last_folder = str(self.settings_manager.get("import/last_folder", "") or "")
                except Exception:
                    last_folder = ""
                try:
                    last_norm = os.path.normcase(os.path.normpath(last_path)) if last_path else ""
                except Exception:
                    last_norm = last_path
                try:
                    last_folder_norm = os.path.normcase(os.path.normpath(last_folder)) if last_folder else ""
                except Exception:
                    last_folder_norm = last_folder
                try:
                    if last_norm and (last_norm == removed or last_norm.startswith(removed + os.sep)):
                        self.settings_manager.set("import/last_path", out[0] if out else "")
                except Exception:
                    pass
                try:
                    if last_folder_norm and (last_folder_norm == removed or last_folder_norm.startswith(removed + os.sep)):
                        self.settings_manager.set("import/last_folder", "")
                except Exception:
                    pass
                self.settings_manager.sync()
            except Exception:
                pass
        if emit_signal:
            try:
                self.folderRemovedFromTree.emit(str(path))
            except Exception:
                pass
        try:
            if str(self.context or "").lower() == "import":
                self.rootFoldersChanged.emit()
        except Exception:
            pass

    def rename_folder(self, item=None):
        if item is None:
            item = self.folder_tree.currentItem()
        if not item: return

        old_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not old_path or not os.path.exists(old_path): return
        
        old_name = os.path.basename(old_path)
        new_name, ok = CustomInputDialog.getText(self, "重命名文件夹", "新名称:", text=old_name)
        
        if ok and new_name and new_name != old_name:
            if any(c in new_name for c in '<>:"/\\|?*'):
                 NotificationManager.instance().show_warning("错误", "文件名包含非法字符")
                 return
                 
            parent_path = os.path.dirname(old_path)
            new_path = os.path.join(parent_path, new_name)
            
            if os.path.exists(new_path):
                NotificationManager.instance().show_warning("错误", "目标文件夹已存在")
                return

            try:
                os.rename(old_path, new_path)
                
                # Update Tree Item
                item.setText(0, new_name)
                item.setData(0, Qt.ItemDataRole.UserRole, new_path)
                # Update sort key
                item.setText(1, self._get_sort_key(new_name))
                
                # Update all children paths
                # This is tricky because children paths need to be updated recursively
                # Simplest way is to reload the parent
                parent_item = item.parent()
                if parent_item:
                    # Refresh parent
                    was_expanded = item.isExpanded()
                    parent_item.takeChildren()
                    parent_path_data = parent_item.data(0, Qt.ItemDataRole.UserRole)
                    
                    # Calculate depth
                    depth = 0
                    temp = parent_item
                    while temp.parent():
                        depth += 1
                        temp = temp.parent()
                        
                    self._add_subfolders(parent_item, parent_path_data, depth, max_depth=1)
                    
                    # Try to re-expand/re-select
                    for i in range(parent_item.childCount()):
                        child = parent_item.child(i)
                        if child.text(0) == new_name:
                            child.setExpanded(was_expanded)
                            self.folder_tree.setCurrentItem(child)
                            break
                
                self.folderRenamed.emit(old_path, new_path)
                
            except Exception as e:
                NotificationManager.instance().show_warning("错误", f"重命名失败: {e}")

    def open_in_explorer(self, folder_path):
        try:
            import platform
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", folder_path])
            else:
                subprocess.Popen(["xdg-open", folder_path])
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"无法打开文件夹: {e}")

    def show_sort_menu(self):
        menu = QMenu(self)
        self.style_menu(menu)
        
        action_pinyin = menu.addAction("按拼音排序")
        action_pinyin.setCheckable(True)
        action_pinyin.setChecked(self.folder_sort_mode == "pinyin")
        action_pinyin.triggered.connect(lambda: self.change_sort_mode("pinyin"))
        
        action_eng = menu.addAction("按英文排序")
        action_eng.setCheckable(True)
        action_eng.setChecked(self.folder_sort_mode == "english")
        action_eng.triggered.connect(lambda: self.change_sort_mode("english"))
        
        menu.exec(self.sort_btn.mapToGlobal(QPoint(0, self.sort_btn.height())))

    def change_sort_mode(self, mode):
        # Always refresh even if mode is same, in case items changed
        self.folder_sort_mode = mode
        self.refresh_sort()
        
        # 提示用户排序模式已切换
        mode_name = "拼音" if mode == "pinyin" else "英文"
        NotificationManager.instance().show_toast(f"已切换为{mode_name}排序")

    def _get_sort_key(self, text):
        if self.folder_sort_mode == "pinyin":
            try:
                from pypinyin import lazy_pinyin
                # 使用 lazy_pinyin 进行全拼排序，更准确
                py_list = lazy_pinyin(text, errors='default')
                return ''.join(py_list).lower()
            except ImportError:
                # 只有导入失败才提示，避免每次调用都提示
                NotificationManager.instance().show_warning("提示", "未安装 pypinyin 库，无法使用拼音排序，将回退到英文排序。")
                return text.lower()
            except Exception: # Catch all other exceptions
                return text.lower()
        elif self.folder_sort_mode == "english":
            return text.lower()
        return text

    def refresh_sort(self):
        self.folder_tree.setSortingEnabled(False) # Disable sorting while updating
        
        # 强制更新所有项的排序键
        iterator = QTreeWidgetItemIterator(self.folder_tree)
        while iterator.value():
            item = iterator.value()
            item.setText(1, self._get_sort_key(item.text(0)))
            iterator += 1
            
        self.folder_tree.setSortingEnabled(True)
        # 强制触发排序
        self.folder_tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def set_panel_visible(self, visible):
        """设置面板可见性"""
        if self.folder_tree_visible == visible:
            return
            
        self.folder_tree_visible = visible
        
        if self.folder_tree_visible:
            self.folder_tree.show()
            for btn in self.tool_buttons:
                btn.show()
            
            # Restore spacers to Expanding
            for spacer in self.spacers:
                spacer.changeSize(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

            # Remove the centering spacer added at the end during collapse
            if self.search_layout.count() > 0:
                last_item = self.search_layout.itemAt(self.search_layout.count() - 1)
                # Ensure it's not one of our managed spacers
                is_managed = False
                for s in self.spacers:
                    if last_item == s:
                        is_managed = True
                        break
                
                # Also ensure it's not the toggle button (shouldn't be, but safety first)
                if not is_managed and last_item.widget() != self.toggle_btn:
                     self.search_layout.removeItem(last_item)
                
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.search_layout.setContentsMargins(12, 6, 12, 6)
            self.setMinimumWidth(120)
            self.setMaximumWidth(400)
            
            icon_color = ColorManager.instance().get("theme.text.dark")
            self.toggle_btn.setProperty("icon_name", "mdi6.chevron-left")
            self.toggle_btn.setIcon(qta.icon('mdi6.chevron-left', color=icon_color, options=[{'scale_factor': 1.1}]))
            self.toggle_btn.setToolTip("折叠文件夹")
        else:
            self.folder_tree.hide()
            for btn in self.tool_buttons:
                btn.hide()
            try:
                if hasattr(self, "search_panel") and self.search_panel is not None:
                    self.search_panel.hide()
                if hasattr(self, "search_results") and self.search_results is not None:
                    self.search_results.hide()
            except Exception:
                pass
            
            # Squash all spacers except the last one (to keep structure clean)
            # Actually, to center Toggle, we want [Stretch, Toggle, Stretch]
            # Our structure is [Btn, Spacer, Btn, Spacer, Toggle]
            # If we squash all spacers to 0, we get [Toggle] (at left).
            # So we need to add a stretch before Toggle and after Toggle.
            
            # Strategy: Squash ALL managed spacers. Add one before Toggle, one after.
            # But wait, 'addStretch' adds to end. 'insertStretch' adds at index.
            # Easier: 
            # 1. Squash all managed spacers.
            # 2. But the last managed spacer is right before Toggle.
            #    If we keep it Expanding, we have [..., Stretch, Toggle]. This pushes Toggle to right.
            #    If we add another Stretch at end: [..., Stretch, Toggle, Stretch]. Centered!
            
            # So: Keep the last managed spacer Expanding. Squash others. Add new Stretch at end.
            # If no managed spacers (only Toggle), add Stretch before and after.
            
            if self.spacers:
                # Keep last spacer expanding, others fixed 0
                for i, spacer in enumerate(self.spacers):
                    if i == len(self.spacers) - 1:
                        spacer.changeSize(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                    else:
                        spacer.changeSize(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            else:
                 # No spacers (no buttons). Insert one before Toggle.
                 # But we removed the initial stretch. So we must insert one.
                 index = self.search_layout.indexOf(self.toggle_btn)
                 self.search_layout.insertStretch(index)
                 # We don't track this temporary spacer in self.spacers because it's only for empty state
                 # But wait, next time we expand, we need to remove it?
                 # Actually, if tool_buttons is empty, we probably don't care much about layout restoration complexity.
                 # Let's assume tool_buttons is not empty for now as per use case.
            
            # Add spacer at the end to center Toggle (assuming there is a stretch before it)
            self.search_layout.addStretch()
            
            self.layout().setContentsMargins(2, 2, 2, 2)
            self.search_layout.setContentsMargins(2, 6, 2, 6)
            self.setMinimumWidth(34)
            self.setMaximumWidth(34)
            
            icon_color = ColorManager.instance().get("theme.text.dark")
            self.toggle_btn.setProperty("icon_name", "mdi6.chevron-right")
            self.toggle_btn.setIcon(qta.icon('mdi6.chevron-right', color=icon_color, options=[{'scale_factor': 1.1}]))
            self.toggle_btn.setToolTip("展开文件夹")
        
        # Invalidate layout to apply spacer changes
        self.search_layout.invalidate()
        self.toggleRequested.emit(self.folder_tree_visible)

    def on_toggle_clicked(self):
        self.set_panel_visible(not self.folder_tree_visible)

    def handle_click_outside(self, global_pos):
        """处理外部点击，关闭搜索面板"""
        if self.search_panel.isVisible():
            # 检查点击是否在搜索面板、结果列表或搜索按钮内
            widgets = [self.search_panel, self.search_results]
            if self.search_btn:
                widgets.append(self.search_btn)
            
            clicked_inside = False
            for w in widgets:
                if w.isVisible():
                    # 将全局坐标转换为控件局部坐标
                    local_pos = w.mapFromGlobal(global_pos)
                    if w.rect().contains(local_pos):
                        clicked_inside = True
                        break
            
            if not clicked_inside:
                if self.search_btn:
                    self.search_btn.setChecked(False)
                else:
                    self.search_panel.hide()
                    self.search_results.hide()
