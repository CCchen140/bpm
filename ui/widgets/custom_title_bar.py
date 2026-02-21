import os
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap

from ui.utils.icon_loader import qta
from ui.utils.color_manager import ColorManager

class CustomTitleBar(QWidget):
    """自定义标题栏"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._drag_pos = None
        self._is_guide = False
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # 左侧图标区域（与左边栏对齐）
        self.icon_container = QWidget()
        self.icon_container.setFixedSize(60, 36)
        icon_layout = QHBoxLayout(self.icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.app_icon_label = QLabel()
        self.set_app_icon()  # 设置默认图标
        self.app_icon_label.setFixedSize(24, 24)
        icon_layout.addWidget(self.app_icon_label)
        layout.addWidget(self.icon_container)
        # 右侧标题区域（浅色背景）
        self.title_container = QWidget()
        title_layout = QHBoxLayout(self.title_container)
        title_layout.setContentsMargins(12, 0, 5, 0)
        title_layout.setSpacing(0)
        # 标题
        self.title_label = QLabel("栖图")
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        # 最小化按钮
        self.min_btn = QPushButton()
        self.min_btn.setIconSize(QSize(16, 16))
        self.min_btn.setFixedSize(46, 36)
        self.min_btn.clicked.connect(self._minimize)
        title_layout.addWidget(self.min_btn)
        # 最大化/还原按钮
        self.max_btn = QPushButton()
        self.max_btn.setIconSize(QSize(16, 16))
        self.max_btn.setFixedSize(46, 36)
        self.max_btn.clicked.connect(self._maximize_restore)
        title_layout.addWidget(self.max_btn)
        # 关闭按钮
        self.close_btn = QPushButton()
        self.close_btn.setIconSize(QSize(16, 16))
        self.close_btn.setFixedSize(46, 36)
        self.close_btn.clicked.connect(self._close)
        title_layout.addWidget(self.close_btn)
        layout.addWidget(self.title_container, 1)
        try:
            ColorManager.instance().register_listener(self._apply_theme_styles)
        except Exception:
            pass
        self._apply_theme_styles()

    def set_guide_style(self, is_guide=False):
        """设置引导页模式的样式"""
        self._is_guide = bool(is_guide)
        if is_guide:
            cm = ColorManager.instance()
            guide_top = cm.get("guide.background.top")
            guide_text = cm.get("theme.text.light")
            # 引导/数据加载页：小鸟图标颜色与标题文字一致，保持视觉统一
            guide_icon = cm.get("theme.text.light")
            # 引导模式：全透明或与引导页背景一致
            # 左侧图标区域
            self.icon_container.setStyleSheet(f"background-color: {guide_top};")
            self.app_icon_label.setPixmap(qta.icon('ph.bird-fill', color=guide_icon).pixmap(24, 24))
            
            # 右侧标题区域
            self.title_container.setStyleSheet(f"background-color: {guide_top};")
            self.title_label.setStyleSheet(f"""
                QLabel {
                    color: {guide_text};
                    font-size: 13px;
                    font-weight: bold;
                    background: transparent;
                }
            """)
        else:
            self._apply_theme_styles()

    def _minimize(self):
        self.parent_window.showMinimized()

    def _maximize_restore(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
            try:
                self._apply_theme_styles()
            except Exception:
                pass
        else:
            self.parent_window.showMaximized()
            try:
                self._apply_theme_styles()
            except Exception:
                pass

    def _close(self):
        self.parent_window.close()

    def set_app_icon(self, icon_path=None):
        """设置应用图标
        Args:
            icon_path: 图标文件路径，如果为 None 则使用默认图标
        """
        if icon_path and os.path.exists(icon_path):
            # 使用自定义图标
            pixmap = QPixmap(icon_path).scaled(24, 24,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.app_icon_label.setPixmap(pixmap)
        else:
            # 使用默认图标
            # 默认模式：小鸟图标颜色与标题文字一致，避免在“数据加载/初始化”等场景出现颜色不一致
            cm = ColorManager.instance()
            self.app_icon_label.setPixmap(qta.icon('ph.bird-fill', color=cm.get("theme.text.dark")).pixmap(24, 24))

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        if bool(getattr(self, "_is_guide", False)):
            guide_top = cm.get("guide.background.top")
            guide_text = cm.get("theme.text.light")
            # 引导/数据加载页：小鸟图标颜色与标题文字一致，保持视觉统一
            guide_icon = cm.get("theme.text.light")
            self.icon_container.setStyleSheet(f"background-color: {guide_top};")
            try:
                self.app_icon_label.setPixmap(qta.icon("ph.bird-fill", color=guide_icon).pixmap(24, 24))
            except Exception:
                self.set_app_icon()
            self.title_container.setStyleSheet(f"background-color: {guide_top};")
            self.title_label.setStyleSheet(
                f"color: {guide_text}; font-size: 13px; font-weight: bold; background: transparent;"
            )
        else:
            sidebar_bg = cm.get("theme.sidebar")
            title_bg = cm.get("theme.background")
            title_text = cm.get("theme.text.dark")
            hover_bg = cm.get("theme.popup")
            close_hover_bg = cm.get("theme.primary")
            icon_color = cm.get("theme.text.dark")
            self.icon_container.setStyleSheet(f"background-color: {sidebar_bg};")
            self.set_app_icon()
            self.title_container.setStyleSheet(f"background-color: {title_bg};")
            self.title_label.setStyleSheet(
                f"color: {title_text}; font-size: 13px; font-weight: bold; background: transparent;"
            )
            btn_style = f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                    padding: 8px 12px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                }}
            """
            close_btn_style = f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                    padding: 8px 12px;
                }}
                QPushButton:hover {{
                    background-color: {close_hover_bg};
                }}
            """
            try:
                self.min_btn.setStyleSheet(btn_style)
                self.max_btn.setStyleSheet(btn_style)
                self.close_btn.setStyleSheet(close_btn_style)
            except Exception:
                pass
            try:
                self.min_btn.setIcon(qta.icon("mdi6.window-minimize", color=icon_color))
            except Exception:
                pass
            try:
                if self.parent_window is not None and self.parent_window.isMaximized():
                    self.max_btn.setIcon(qta.icon("mdi6.window-restore", color=icon_color))
                else:
                    self.max_btn.setIcon(qta.icon("mdi6.window-maximize", color=icon_color))
            except Exception:
                pass
            try:
                self.close_btn.setIcon(qta.icon("mdi6.close", color=icon_color))
            except Exception:
                pass

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_position = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_start_position'):
            delta = event.globalPosition().toPoint() - self.drag_start_position
            self.parent_window.move(self.parent_window.pos() + delta)
            self.drag_start_position = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        if hasattr(self, 'drag_start_position'):
            delattr(self, 'drag_start_position')
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._maximize_restore()
