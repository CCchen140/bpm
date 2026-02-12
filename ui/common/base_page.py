from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QFrame
from PyQt6.QtCore import Qt
from ui.common.styles import SPLITTER_STYLE
from ui.utils.color_manager import ColorManager

class BaseImageBrowserPage(QWidget):
    """
    基础图片浏览页面组件
    包含：
    1. 左右分栏布局 (Left Panel + Right Content)
    2. 右侧内容区包含：Toolbar(Top) + Grid(Center) + StatusBar(Bottom)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_base_ui()
        ColorManager.instance().register_listener(self._apply_toolbar_container_style)
        self._apply_toolbar_container_style()

    def init_base_ui(self):
        # Main Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Splitter (Left: Folder/Tree, Right: Content)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setStyleSheet(SPLITTER_STYLE)
        self.content_splitter.setHandleWidth(1)
        self.content_splitter.setChildrenCollapsible(False)
        self.main_layout.addWidget(self.content_splitter)

        # 1. Left Panel Container (Optional, Hidden by default)
        self.left_panel_container = QWidget()
        self.left_panel_layout = QVBoxLayout(self.left_panel_container)
        self.left_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.left_panel_layout.setSpacing(0)
        self.left_panel_container.hide() 
        self.left_panel_container.setMinimumWidth(30)  # 设置最小宽度
        self.content_splitter.addWidget(self.left_panel_container)

        # 2. Right Content Container
        self.right_content_container = QWidget()
        self.right_content_layout = QVBoxLayout(self.right_content_container)
        self.right_content_layout.setContentsMargins(0, 0, 0, 0)
        self.right_content_layout.setSpacing(0)
        self.content_splitter.addWidget(self.right_content_container)
        
        # 2.1 Toolbar Container
        self.toolbar_container = QWidget()
        self.toolbar_layout = QVBoxLayout(self.toolbar_container)
        self.toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self.right_content_layout.addWidget(self.toolbar_container)
        
        # 2.2 Grid/Content Container
        self.grid_container = QWidget()
        self.grid_layout = QVBoxLayout(self.grid_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.right_content_layout.addWidget(self.grid_container)
        
        # 2.3 Status Bar Container
        self.status_container = QWidget()
        self.status_layout = QVBoxLayout(self.status_container)
        self.status_layout.setContentsMargins(0, 0, 0, 0)
        self.right_content_layout.addWidget(self.status_container)

    def _apply_toolbar_container_style(self):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.primary")
        if hasattr(self, "toolbar_container"):
            self.toolbar_container.setStyleSheet(f"""
                QWidget {{
                    background-color: {bg};
                }}
            """)

    def set_left_panel(self, widget: QWidget, width: int = 250):
        """设置左侧面板"""
        self.clear_layout(self.left_panel_layout)
        self.left_panel_layout.addWidget(widget)
        # self.left_panel_container.setMinimumWidth(100) # Removed hardcoded minimum width
        self.left_panel_container.show()
        
        # 设置初始比例 (假设总宽1000)
        self.content_splitter.setSizes([width, 1000 - width])

    def set_toolbar(self, widget: QWidget):
        """设置工具栏"""
        self.clear_layout(self.toolbar_layout)
        self.toolbar_layout.addWidget(widget)

    def set_grid(self, widget: QWidget):
        """设置网格/内容视图"""
        self.clear_layout(self.grid_layout)
        self.grid_layout.addWidget(widget)

    def set_status_bar(self, widget: QWidget):
        """设置状态栏"""
        self.clear_layout(self.status_layout)
        self.status_layout.addWidget(widget)

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
