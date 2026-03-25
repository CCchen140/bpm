# -*- coding: utf-8 -*-
"""
系统托盘管理器
提供系统托盘图标和 Windows 系统通知功能
"""

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QObject

from utils.log_manager import LogManager


class SystemTrayManager(QObject):
    """系统托盘管理器单例"""
    _instance = None

    def __init__(self):
        super().__init__()
        self._tray_icon = None
        self._main_window = None

    @classmethod
    def instance(cls):
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = SystemTrayManager()
        return cls._instance

    def initialize(self, main_window, icon: QIcon):
        """
        初始化系统托盘图标

        参数:
            main_window: 主窗口实例
            icon: 应用图标
        """
        self._main_window = main_window

        # 检查系统是否支持系统托盘
        if not QSystemTrayIcon.isSystemTrayAvailable():
            LogManager.instance().warning("系统不支持系统托盘")
            return

        self._tray_icon = QSystemTrayIcon(icon, main_window)

        # 创建右键菜单
        menu = QMenu()

        show_action = QAction("显示主窗口", menu)
        show_action.triggered.connect(self._restore_window)
        menu.addAction(show_action)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.setToolTip("栖图")

        # 双击托盘图标恢复窗口
        self._tray_icon.activated.connect(self._on_activated)

        # 通知点击恢复窗口
        self._tray_icon.messageClicked.connect(self._restore_window)

        self._tray_icon.show()
        LogManager.instance().info("系统托盘已初始化")

    def show_notification(self, title: str, message: str,
                          icon_type=None,
                          duration_ms: int = 5000):
        """
        显示系统通知（Windows 右下角 Toast）

        参数:
            title: 通知标题
            message: 通知内容
            icon_type: 图标类型，默认使用 NoIcon（无声音）
            duration_ms: 显示时长（毫秒）
        """
        if icon_type is None:
            # 使用 NoIcon 类型，通知不会播放声音
            icon_type = QSystemTrayIcon.MessageIcon.NoIcon

        if self._tray_icon and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, icon_type, duration_ms)
            LogManager.instance().info(f"[系统通知] 已发送: {title}")
        else:
            LogManager.instance().warning("[系统通知] 系统托盘未初始化，无法发送通知")

    def _on_activated(self, reason):
        """托盘图标被激活时的处理"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_window()

    def _restore_window(self):
        """恢复主窗口"""
        if self._main_window:
            self._main_window.showNormal()
            self._main_window.activateWindow()
            self._main_window.raise_()

    def _quit_app(self):
        """退出应用"""
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def set_icon(self, icon: QIcon):
        """更新托盘图标"""
        if self._tray_icon:
            self._tray_icon.setIcon(icon)
