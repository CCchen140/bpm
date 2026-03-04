from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget
from PyQt6.QtCore import Qt, QEvent, QPoint
from PyQt6.QtGui import QGuiApplication
from ui.utils.icon_loader import qta
from ui.utils.color_manager import ColorManager


class BasePopupDialog(QDialog):
    def __init__(self, parent=None, title="", size=None, translucent_background: bool = True):
        super().__init__(parent)
        self._title = title
        self._size = size
        self._translucent_background = bool(translucent_background)
        self._dragging = False
        self._drag_offset = QPoint()
        self.container = None
        self.title_bar = None
        self.title_label = None
        self.close_btn = None
        self.content_widget = None
        self.content_layout = None
        self.bottom_bar = None
        self.bottom_layout = None
        self._init_base_ui()

    def _init_base_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, bool(self._translucent_background))
        except Exception:
            try:
                if self._translucent_background:
                    self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            except Exception:
                pass
        if self._size:
            req_w, req_h = int(self._size[0]), int(self._size[1])
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                max_w = max(480, int(geom.width()) - 40)
                max_h = max(360, int(geom.height()) - 40)
                req_w = min(req_w, max_w)
                req_h = min(req_h, max_h)
            self.resize(req_w, req_h)

        cm = ColorManager.instance()
        self._content_bg = cm.get("theme.background.light", "#FFFFFF")
        self._footer_bg = cm.get("theme.background.dark", "#E7E7E7")
        self._border_color = cm.get("theme.background.light", "#D0D0D0")
        self._header_bg = cm.get("popup.header.background", "#2c3e50")
        self._header_text = cm.get("popup.header.text", "#FFFFFF")
        self._close_hover_bg = cm.get("popup.header.close_button.hover_background", "#FFFFFF1A")
        self._close_hover_icon = cm.get("border.subject_rect", "#F50F0F")
        self._primary_color = cm.get("theme.primary", "#2196F3")
        self._text_color = cm.get("popup.text.primary", "#333333")
        self._disabled_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        self._hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")

        main_layout = QVBoxLayout(self)
        # 使用透明背景，设置边距用于阴影效果
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QWidget()
        self.container.setObjectName("container")
        # 统一使用圆角和边框样式
        self.container.setStyleSheet(f"""
            QWidget#container {{
                background-color: {self._content_bg};
                border: 1px solid {self._border_color};
                border-radius: 8px;
            }}
        """)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.title_bar = QWidget()
        self.title_bar.setFixedHeight(40)
        # 统一使用圆角样式
        self.title_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {self._header_bg};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border-bottom: 1px solid {self._header_bg};
            }}
        """)
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(15, 0, 5, 0)

        self.title_label = QLabel(self._title)
        self.title_label.setStyleSheet(f"""
            color: {self._header_text};
            font-size: 14px;
            font-weight: bold;
            border: none;
            background: transparent;
        """)
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()

        self.close_btn = QPushButton()
        self.close_btn.setIcon(qta.icon('mdi6.close', color=self._header_text))
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {self._close_hover_bg};
            }}
        """)
        self.close_btn.clicked.connect(self.reject)
        title_layout.addWidget(self.close_btn)
        self.close_btn.installEventFilter(self)
        self.title_bar.installEventFilter(self)
        self.title_label.installEventFilter(self)

        container_layout.addWidget(self.title_bar)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("contentWidget")
        self.content_widget.setStyleSheet(f"""
            QWidget#contentWidget {{
                background-color: {self._content_bg};
            }}
            QWidget#contentWidget, 
            QWidget#contentWidget QLabel, 
            QWidget#contentWidget QCheckBox, 
            QWidget#contentWidget QRadioButton, 
            QWidget#contentWidget QPushButton, 
            QWidget#contentWidget QLineEdit, 
            QWidget#contentWidget QComboBox, 
            QWidget#contentWidget QListWidget, 
            QWidget#contentWidget QListView, 
            QWidget#contentWidget QTreeView, 
            QWidget#contentWidget QSpinBox, 
            QWidget#contentWidget QProgressBar {{
                color: {self._text_color};
            }}
            QWidget#contentWidget QLabel {{
                background: transparent;
            }}
            QWidget#contentWidget QLineEdit {{
                background-color: {self._content_bg};
            }}
            QWidget#contentWidget QPlainTextEdit {{
                background-color: {self._content_bg};
            }}
            QWidget#contentWidget QTextEdit {{
                background-color: {self._content_bg};
            }}
            QWidget#contentWidget QComboBox {{
                background-color: {self._content_bg};
            }}
            QWidget#contentWidget QComboBox QAbstractItemView {{
                background-color: {self._content_bg};
            }}
        """)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(10)
        container_layout.addWidget(self.content_widget)

        self.bottom_bar = QWidget()
        self.bottom_bar.setObjectName("bottomBar")
        self.bottom_bar.setFixedHeight(60)
        # 统一使用圆角样式
        self.bottom_bar.setStyleSheet(f"""
            QWidget#bottomBar {{
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
                background-color: {self._footer_bg};
                border-top: 1px solid {self._border_color};
            }}
        """)
        self.bottom_layout = QHBoxLayout(self.bottom_bar)
        self.bottom_layout.setContentsMargins(0, 0, 20, 0)
        self.bottom_layout.setSpacing(10)
        self.bottom_layout.addStretch()
        container_layout.addWidget(self.bottom_bar)

        main_layout.addWidget(self.container)

    def eventFilter(self, obj, event):
        if obj in (self.title_bar, self.title_label):
            try:
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    self._dragging = True
                    try:
                        self._drag_offset = event.globalPosition().toPoint() - self.pos()
                    except Exception:
                        self._drag_offset = QPoint()
                    return True
                if event.type() == QEvent.Type.MouseMove and self._dragging:
                    try:
                        self.move(event.globalPosition().toPoint() - self._drag_offset)
                        return True
                    except Exception:
                        return False
                if event.type() == QEvent.Type.MouseButtonRelease and self._dragging:
                    self._dragging = False
                    return True
            except Exception:
                self._dragging = False
        if obj is self.close_btn:
            if event.type() == QEvent.Type.Enter:
                self.close_btn.setIcon(qta.icon('mdi6.close', color=self._close_hover_icon))
            elif event.type() == QEvent.Type.Leave:
                self.close_btn.setIcon(qta.icon('mdi6.close', color=self._header_text))
        return super().eventFilter(obj, event)

    def set_title(self, title):
        self._title = title
        if self.title_label:
            self.title_label.setText(title)

    def set_title_bar_style(self, background, text_color, hover_background=None):
        self._header_bg = background
        self._header_text = text_color
        self.title_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {self._header_bg};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border-bottom: 1px solid {self._header_bg};
            }}
        """)
        if self.title_label:
            self.title_label.setStyleSheet(f"""
                color: {self._header_text};
                font-size: 14px;
                font-weight: bold;
                border: none;
                background: transparent;
            """)
        if hover_background:
            self._close_hover_bg = hover_background
        self.close_btn.setIcon(qta.icon('mdi6.close', color=self._header_text))
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {self._close_hover_bg};
            }}
        """)

    def set_bottom_bar_style(self, background, border_color=None):
        self._footer_bg = background
        if border_color:
            self._border_color = border_color
        # 统一使用圆角样式
        self.bottom_bar.setStyleSheet(f"""
            QWidget#bottomBar {{
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
                background-color: {self._footer_bg};
                border-top: 1px solid {self._border_color};
            }}
        """)

    def set_bottom_bar_visible(self, visible):
        if self.bottom_bar:
            self.bottom_bar.setVisible(bool(visible))

    def get_content_background(self):
        return self._content_bg

    def get_footer_background(self):
        return self._footer_bg

    def get_primary_color(self):
        return self._primary_color

    def apply_dialog_button_style(self, button, role="secondary"):
        if role == "primary":
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self._primary_color};
                    color: {self._header_text};
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {self._primary_color};
                }}
                QPushButton:pressed {{
                    background-color: {self._primary_color};
                }}
                QPushButton:disabled {{
                    background-color: {self._disabled_bg};
                }}
            """)
            return
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._content_bg};
                color: {self._text_color};
                border: 1px solid {self._border_color};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {self._hover_bg};
            }}
        """)
