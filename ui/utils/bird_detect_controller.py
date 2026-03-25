# -*- coding: utf-8 -*-
"""
全局快捷键识鸟功能控制器
整合全局快捷键监听、屏幕截图、鸟种识别等功能
"""

import os
import tempfile
import time
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import QApplication

from ui.utils.global_hotkey_manager import GlobalHotkeyManager, register_global_hotkey
from ui.utils.shortcut_manager import ShortcutManager
from ui.utils.notification_manager import NotificationManager
from ui.widgets.screen_capture_overlay import ScreenCaptureOverlay
from utils.log_manager import LogManager


def show_notification(title: str, message: str, success: bool = True):
    """
    显示鸟种识别通知
    - 成功时：使用 smart_notify（前台 Toast，后台系统通知）
    - 失败时：只显示"无法识别鸟种"

    参数:
        title: 通知标题
        message: 通知内容
        success: 是否识别成功
    """
    from PyQt6.QtWidgets import QMessageBox, QApplication
    from PyQt6.QtCore import Qt
    from ui.utils.app_icon import get_app_icon

    if success:
        # 识别成功，使用智能通知
        NotificationManager.instance().smart_notify(title, message, duration=5000)
    else:
        # 识别失败，显示系统通知
        NotificationManager.instance().show_system_notify(title, "无法识别鸟种")


class BirdRecognitionWorker(QThread):
    """鸟种识别工作线程"""
    recognition_finished = pyqtSignal(str, bool, str)  # 结果文本, 是否成功, 错误信息
    
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        
    def run(self):
        """执行识别"""
        try:
            from core.recognizer.bird_species_recognizer import BirdSpeciesRecognizer
            
            recognizer = BirdSpeciesRecognizer()
            result = recognizer.recognize(self.image_path)
            
            if result and result.text:
                self.recognition_finished.emit(result.text, True, "")
            else:
                self.recognition_finished.emit("", False, "识别结果为空")
                
        except Exception as e:
            LogManager.instance().error(f"鸟种识别失败: {e}")
            self.recognition_finished.emit("", False, str(e))


class BirdDetectController(QObject):
    """
    全局快捷键识鸟功能控制器
    单例模式管理整个识鸟流程
    """
    _instance = None
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = BirdDetectController()
        return cls._instance
    
    def __init__(self):
        super().__init__()
        self._initialized = False
        self._overlay = None
        self._recognition_worker = None
        
    def initialize(self):
        """初始化控制器"""
        if self._initialized:
            LogManager.instance().info("全局快捷键识鸟功能已初始化，跳过")
            return
            
        try:
            # 连接全局快捷键信号
            GlobalHotkeyManager.instance().hotkey_triggered.connect(self._on_hotkey_triggered)

            # 先注册全局快捷键（在监听器启动前注册，因为监听器会读取已注册的热键）
            self._register_global_hotkey()

            # 启动全局快捷键监听
            success = GlobalHotkeyManager.instance().start()
            if not success:
                LogManager.instance().warning("全局快捷键监听启动失败，识鸟功能不可用")
                return

            self._initialized = True
            LogManager.instance().info("全局快捷键识鸟功能已初始化")

        except Exception as e:
            LogManager.instance().error(f"初始化全局快捷键识鸟功能失败: {e}")
            
    def _register_global_hotkey(self):
        """注册全局快捷键"""
        # 从 ShortcutManager 获取快捷键配置
        shortcut_str = ShortcutManager.instance().get_sequence_str("Global.BirdDetect")
        if shortcut_str:
            # 转换快捷键格式 (Ctrl+Shift+R -> ctrl+shift+r)
            hotkey_str = shortcut_str.lower().replace("+", "+")
            register_global_hotkey(hotkey_str, "bird_detect")
        else:
            # 使用默认快捷键
            register_global_hotkey("ctrl+shift+r", "bird_detect")
            
    def _on_hotkey_triggered(self, action_id: str):
        """全局快捷键触发回调"""
        if action_id == "bird_detect":
            self.start_capture()
            
    def start_capture(self):
        """开始截图识鸟流程"""
        try:
            # 如果已有截图窗口，先关闭
            if self._overlay and self._overlay.isVisible():
                self._overlay.close()
                
            # 创建截图蒙层窗口
            self._overlay = ScreenCaptureOverlay()
            self._overlay.capture_confirmed.connect(self._on_capture_confirmed)
            self._overlay.capture_cancelled.connect(self._on_capture_cancelled)
            self._overlay.show()
            
            # 确保窗口置顶
            self._overlay.raise_()
            self._overlay.activateWindow()
            
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"启动截图识鸟失败: {e}")
            LogManager.instance().error(f"启动截图识鸟失败: {e}")
            
    def _on_capture_confirmed(self, rect):
        """截图确认回调"""
        try:
            # 获取截图
            pixmap = self._overlay.get_captured_pixmap()
            if not pixmap:
                NotificationManager.instance().show_warning("错误", "获取截图失败")
                return
                
            # 保存截图到临时文件
            temp_path = self._save_pixmap_to_temp(pixmap)
            if not temp_path:
                NotificationManager.instance().show_warning("错误", "保存截图失败")
                return
                
            # 开始识别
            self._start_recognition(temp_path)
            
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"处理截图失败: {e}")
            LogManager.instance().error(f"处理截图失败: {e}")
            
    def _on_capture_cancelled(self):
        """截图取消回调"""
        LogManager.instance().info("截图识鸟已取消")
        
    def _save_pixmap_to_temp(self, pixmap: QPixmap) -> Optional[str]:
        """将 QPixmap 保存到临时文件"""
        try:
            # 创建临时文件
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, f"bird_detect_{int(time.time())}.png")
            
            # 保存图片
            if pixmap.save(temp_path, "PNG"):
                return temp_path
            return None
            
        except Exception as e:
            LogManager.instance().error(f"保存截图到临时文件失败: {e}")
            return None
            
    def _start_recognition(self, image_path: str):
        """开始鸟种识别"""
        try:
            # 显示识别中提示
            NotificationManager.instance().show_toast("正在识别鸟种，请稍候...")
            
            # 创建工作线程
            self._recognition_worker = BirdRecognitionWorker(image_path)
            self._recognition_worker.recognition_finished.connect(self._on_recognition_finished)
            self._recognition_worker.start()
            
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"启动识别失败: {e}")
            LogManager.instance().error(f"启动识别失败: {e}")
            
    def _on_recognition_finished(self, result_text: str, success: bool, error_msg: str):
        """识别完成回调"""
        try:
            # 清理临时文件
            if self._recognition_worker and self._recognition_worker.image_path:
                try:
                    temp_path = self._recognition_worker.image_path
                    if os.path.exists(temp_path) and temp_path.startswith(tempfile.gettempdir()):
                        os.remove(temp_path)
                except Exception:
                    pass

            if success and result_text and result_text != "无法识别":
                # 识别成功，复制到剪贴板并显示通知
                self._handle_recognition_success(result_text)
            else:
                # 识别失败或无法识别
                show_notification("识别失败", "无法识别鸟种", success=False)
                LogManager.instance().info("鸟种识别失败: 无法识别")

        except Exception as e:
            LogManager.instance().error(f"处理识别结果失败: {e}")
            
    def _handle_recognition_success(self, result_text: str):
        """处理识别成功 - 复制到剪贴板并显示通知"""
        try:
            # 复制结果到剪贴板
            clipboard = QApplication.clipboard()
            clipboard.setText(result_text)

            # 构建显示信息
            display_message = f"识别结果: {result_text}"

            # 显示通知
            show_notification("识别成功", display_message, success=True)
            LogManager.instance().info(f"鸟种识别成功: {result_text}")
        except Exception as e:
            LogManager.instance().error(f"处理识别成功结果失败: {e}")
            
    def _show_recognition_result(self, result_text: str):
        """显示识别结果详情"""
        try:
            # 构建提示信息
            message = f"识别结果: {result_text}\n\n结果已自动复制到剪贴板"
            
            NotificationManager.instance().show_info(
                "鸟种识别成功",
                message
            )
            
        except Exception as e:
            LogManager.instance().error(f"显示识别结果失败: {e}")
            
    def shutdown(self):
        """关闭控制器"""
        try:
            # 停止全局快捷键监听
            GlobalHotkeyManager.instance().stop()
            
            # 关闭截图窗口
            if self._overlay:
                self._overlay.close()
                self._overlay = None
                
            # 停止识别线程
            if self._recognition_worker and self._recognition_worker.isRunning():
                self._recognition_worker.quit()
                self._recognition_worker.wait(3000)
                
            self._initialized = False
            LogManager.instance().info("全局快捷键识鸟功能已关闭")
            
        except Exception as e:
            LogManager.instance().error(f"关闭全局快捷键识鸟功能失败: {e}")


# 便捷函数
def init_bird_detect_controller():
    """初始化全局快捷键识鸟控制器"""
    BirdDetectController.instance().initialize()

def shutdown_bird_detect_controller():
    """关闭全局快捷键识鸟控制器"""
    BirdDetectController.instance().shutdown()
