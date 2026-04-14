# -*- coding: utf-8 -*-
"""
全局快捷键管理器
用于监听全局快捷键，即使应用不在前台也能响应
"""

import threading
import time
from typing import Callable, Optional, Dict

# 尝试导入 pynput 库，用于全局快捷键
# 注意：在打包后的程序中，需要确保 pynput 的所有子模块都被正确包含
PYNPUT_AVAILABLE = False
_pynput_error_detail = ""
_pynput_import_steps = []

try:
    # 第一步：尝试直接导入 keyboard 子模块（避免延迟导入问题）
    # 这是关键：直接从 pynput.keyboard 导入，而不是先导入 pynput
    try:
        from pynput.keyboard import GlobalHotKeys, Listener, Key, KeyCode
        _pynput_import_steps.append(f"1. pynput.keyboard 类导入成功")
    except ImportError as e:
        _pynput_import_steps.append(f"1. pynput.keyboard 类导入失败: {e}")
        raise
    
    # 第二步：尝试导入 pynput 主模块（验证）
    try:
        import pynput as _pynput_module
        _pynput_import_steps.append(f"2. pynput 主模块导入成功: {_pynput_module.__file__}")
    except ImportError as e:
        _pynput_import_steps.append(f"2. pynput 主模块导入失败: {e}")
        # 不抛出异常，因为关键的 keyboard 模块已经导入成功
    
    # 第三步：尝试导入 keyboard 子模块（验证）
    try:
        from pynput import keyboard
        _pynput_import_steps.append(f"3. pynput.keyboard 导入成功: {keyboard.__file__}")
    except ImportError as e:
        _pynput_import_steps.append(f"3. pynput.keyboard 导入失败: {e}")
        # 不抛出异常，因为关键的类已经导入成功
    
    PYNPUT_AVAILABLE = True
except ImportError as _pynput_import_error:
    PYNPUT_AVAILABLE = False
    # 记录详细的导入错误信息，便于调试打包问题
    try:
        import traceback
        _pynput_error_detail = traceback.format_exc()
    except Exception:
        _pynput_error_detail = str(_pynput_import_error)
    
    # 将导入步骤信息添加到错误详情中
    if _pynput_import_steps:
        _pynput_error_detail = "\n".join(_pynput_import_steps) + "\n\n最终错误:\n" + _pynput_error_detail

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication
from utils.log_manager import LogManager


class GlobalHotkeyManager(QObject):
    """
    全局快捷键管理器 (Singleton)
    使用 pynput 库实现全局快捷键监听
    """
    _instance = None
    _lock = threading.Lock()
    
    # 信号：当全局快捷键被触发时发射
    hotkey_triggered = pyqtSignal(str)
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = GlobalHotkeyManager()
        return cls._instance
    
    def __init__(self):
        super().__init__()
        self._listener = None
        self._hotkeys: Dict[str, str] = {}  # 快捷键组合 -> 功能ID
        self._running = False
        self._thread = None
        self._qt_shortcuts = []  # Qt 快捷键备用方案
        self._use_qt_fallback = False  # 是否使用 Qt 备用方案
        
    def start(self):
        """启动全局快捷键监听"""
        if not PYNPUT_AVAILABLE:
            try:
                LogManager.instance().warning(f"pynput 库导入失败，使用 Qt 快捷键备用方案（仅前台有效）。错误详情: {_pynput_error_detail}")
            except Exception:
                LogManager.instance().warning("pynput 库导入失败，使用 Qt 快捷键备用方案（仅前台有效）")
            self._use_qt_fallback = True
            # 重新注册所有已注册的快捷键到 Qt 备用方案
            for hotkey_str, action_id in list(self._hotkeys.items()):
                QTimer.singleShot(100, lambda h=hotkey_str, a=action_id: self._register_qt_shortcut_delayed(h, a))
            return True
            
        if self._running:
            LogManager.instance().info("全局快捷键监听已在运行中")
            return True
            
        try:
            self._running = True
            self._thread = threading.Thread(target=self._listen, daemon=True)
            self._thread.start()
            LogManager.instance().info("全局快捷键监听已启动")
            return True
        except Exception as e:
            LogManager.instance().error(f"启动全局快捷键监听失败: {e}")
            import traceback
            LogManager.instance().error(traceback.format_exc())
            self._running = False
            # 启用 Qt 备用方案
            self._use_qt_fallback = True
            LogManager.instance().info("切换到 Qt 快捷键备用方案（仅前台有效）")
            # 重新注册所有已注册的快捷键到 Qt 备用方案
            for hotkey_str, action_id in list(self._hotkeys.items()):
                QTimer.singleShot(100, lambda h=hotkey_str, a=action_id: self._register_qt_shortcut_delayed(h, a))
            return True  # 返回 True 以启用备用方案
    
    def stop(self):
        """停止全局快捷键监听"""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception as e:
                LogManager.instance().warning(f"停止监听器异常: {e}")
            self._listener = None
        
        # 清理 Qt 快捷键
        for shortcut in self._qt_shortcuts:
            try:
                shortcut.setEnabled(False)
            except Exception:
                pass
        self._qt_shortcuts.clear()
        
        LogManager.instance().info("全局快捷键监听已停止")
    
    def register_hotkey(self, hotkey_str: str, action_id: str):
        """
        注册全局快捷键
        
        Args:
            hotkey_str: 快捷键字符串，如 "ctrl+shift+r"
            action_id: 功能标识符
        """
        try:
            hotkey_str = hotkey_str.lower().strip()
            self._hotkeys[hotkey_str] = action_id
            
            # 如果 pynput 不可用或已启用 Qt 备用方案，立即注册 Qt 快捷键
            if not PYNPUT_AVAILABLE or self._use_qt_fallback:
                # 使用 Qt 备用方案
                # 延迟注册，等待窗口创建完成
                QTimer.singleShot(100, lambda h=hotkey_str, a=action_id: self._register_qt_shortcut_delayed(h, a))

        except Exception as e:
            LogManager.instance().error(f"注册全局快捷键失败 {hotkey_str}: {e}")
    
    def _register_qt_shortcut_delayed(self, hotkey_str: str, action_id: str):
        """延迟注册 Qt 快捷键，确保窗口已创建"""
        self._register_qt_shortcut(hotkey_str, action_id)
    
    def _register_qt_shortcut(self, hotkey_str: str, action_id: str):
        """注册 Qt 快捷键（备用方案）"""
        try:
            # 转换快捷键格式为 Qt 格式
            # pynput 格式: ctrl+shift+r -> Qt 格式: Ctrl+Shift+R
            parts = hotkey_str.split('+')
            qt_parts = []
            for part in parts:
                part = part.strip()
                if part in ('ctrl', 'control'):
                    qt_parts.append('Ctrl')
                elif part == 'shift':
                    qt_parts.append('Shift')
                elif part == 'alt':
                    qt_parts.append('Alt')
                elif len(part) == 1:
                    # 单字符键，转大写
                    qt_parts.append(part.upper())
                else:
                    # 其他键，首字母大写
                    qt_parts.append(part.capitalize())
            qt_seq = '+'.join(qt_parts)
            
            # 获取主窗口作为父对象
            parent_widget = None
            app = QApplication.instance()
            if app:
                # 尝试获取活动窗口或顶层窗口
                parent_widget = app.activeWindow()
                if not parent_widget:
                    # 如果没有活动窗口，尝试获取第一个顶层窗口
                    for widget in app.topLevelWidgets():
                        if widget.isWindow() and widget.isVisible():
                            parent_widget = widget
                            break
            
            if not parent_widget:
                LogManager.instance().warning(f"无法找到合适的父窗口注册 Qt 快捷键 {hotkey_str}")
                return
            
            shortcut = QShortcut(QKeySequence(qt_seq), parent_widget)
            # Qt 备用方案直接发射信号，不经过 _on_hotkey_activated
            shortcut.activated.connect(lambda a=action_id: self.hotkey_triggered.emit(a))
            self._qt_shortcuts.append(shortcut)
            LogManager.instance().info(f"Qt 快捷键已注册: {hotkey_str} -> {action_id}")
        except Exception as e:
            LogManager.instance().error(f"注册 Qt 快捷键失败 {hotkey_str}: {e}")
    
    def unregister_hotkey(self, hotkey_str: str):
        """注销全局快捷键"""
        hotkey_str = hotkey_str.lower().strip()
        if hotkey_str in self._hotkeys:
            del self._hotkeys[hotkey_str]
    
    def _on_hotkey_activated(self, action_id: str):
        """快捷键被激活时的回调"""
        try:
            self.hotkey_triggered.emit(action_id)
        except Exception as e:
            LogManager.instance().error(f"处理快捷键激活失败: {e}")
    
    def _listen(self):
        """监听线程 - 使用 GlobalHotKeys"""
        try:
            # 构建热键映射
            hotkey_mapping = {}
            for hotkey_str, action_id in self._hotkeys.items():
                try:
                    # 转换快捷键格式为 pynput 格式
                    # ctrl+shift+r -> <ctrl>+<shift>+r
                    pynput_parts = []
                    for part in hotkey_str.split('+'):
                        part = part.strip()
                        if part in ('ctrl', 'control'):
                            pynput_parts.append('<ctrl>')
                        elif part == 'shift':
                            pynput_parts.append('<shift>')
                        elif part == 'alt':
                            pynput_parts.append('<alt>')
                        else:
                            pynput_parts.append(part)
                    pynput_str = '+'.join(pynput_parts)

                    # 创建回调函数
                    def make_callback(aid):
                        return lambda: self._on_hotkey_activated(aid)

                    hotkey_mapping[pynput_str] = make_callback(action_id)

                except Exception as e:
                    LogManager.instance().error(f"转换快捷键失败 {hotkey_str}: {e}")

            if not hotkey_mapping:
                self._running = False
                return

            # 使用 GlobalHotKeys 注册热键
            try:
                with GlobalHotKeys(hotkey_mapping) as h:
                    self._listener = h
                    # 保持运行直到停止
                    while self._running:
                        time.sleep(0.1)
            except Exception as e:
                LogManager.instance().error(f"GlobalHotKeys 异常: {e}")
                # 检查是否是权限问题
                if "access is denied" in str(e).lower() or "权限" in str(e):
                    LogManager.instance().error("全局快捷键需要管理员权限，请尝试以管理员身份运行程序")
                raise

        except Exception as e:
            LogManager.instance().error(f"全局快捷键监听异常: {e}")
            # 启用 Qt 备用方案
            self._use_qt_fallback = True
            QTimer.singleShot(0, self._enable_qt_fallback)
        finally:
            self._running = False
            LogManager.instance().info("全局快捷键监听线程已结束")
    
    def _enable_qt_fallback(self):
        """启用 Qt 备用方案"""
        try:
            self._use_qt_fallback = True
            LogManager.instance().info("启用 Qt 快捷键备用方案")
            for hotkey_str, action_id in list(self._hotkeys.items()):
                self._register_qt_shortcut(hotkey_str, action_id)
        except Exception as e:
            LogManager.instance().error(f"启用 Qt 备用方案失败: {e}")


# 便捷函数
def start_global_hotkey_listener():
    """启动全局快捷键监听"""
    return GlobalHotkeyManager.instance().start()

def stop_global_hotkey_listener():
    """停止全局快捷键监听"""
    GlobalHotkeyManager.instance().stop()

def register_global_hotkey(hotkey_str: str, action_id: str):
    """注册全局快捷键"""
    GlobalHotkeyManager.instance().register_hotkey(hotkey_str, action_id)

def unregister_global_hotkey(hotkey_str: str):
    """注销全局快捷键"""
    GlobalHotkeyManager.instance().unregister_hotkey(hotkey_str)
