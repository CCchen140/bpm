import sys
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout, QMessageBox, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QObject
from ui.widgets.custom_message_box import CustomMessageBox
from ui.utils.color_manager import ColorManager
from utils.log_manager import LogManager

class ToastWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) # 允许鼠标穿透
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.hide()
        
        self._apply_styles()
        try:
            ColorManager.instance().register_listener(self._apply_styles)
        except Exception:
            pass
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        
        # 透明度效果
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        # 动画
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        
        # 定时器
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.start_fade_out)
        self._position = "bottom"

    def _apply_styles(self):
        cm = ColorManager.instance()
        bg = cm.to_qss_color("notification.toast.background", default="#282828DC")
        fg = cm.to_qss_color("notification.toast.text", default="#FFFFFF")
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg};
                border-radius: 18px;
            }}
            QLabel {{
                background: transparent;
                color: {fg};
                font-family: "Microsoft YaHei";
                font-size: 14px;
                font-weight: bold;
                padding: 8px 20px;
            }}
        """)

    def set_position(self, position: str):
        p = str(position or "").strip().lower()
        if p not in ("top", "bottom"):
            p = "bottom"
        self._position = p

    def show_message(self, message, duration=2000, position: str = "bottom"):
        self.set_position(position)
        self.label.setText(message)
        self.adjustSize()
        self.update_position()
        
        self.anim.stop()
        self.opacity_effect.setOpacity(0)
        self.show()
        self.raise_()
        
        # 淡入
        self.anim.setDuration(200)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        try:
            self.anim.finished.disconnect() # 移除之前的连接
        except TypeError:
            pass # 如果没有连接，会抛出 TypeError，忽略即可
        self.anim.start()
        
        self.timer.start(duration)

    def start_fade_out(self):
        self.anim.setDuration(500)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self.anim.finished.connect(self.hide)
        self.anim.start()
        
    def update_position(self):
        if not self.parent(): return
        parent_rect = self.parent().rect()
        x = (parent_rect.width() - self.width()) // 2
        if str(getattr(self, "_position", "bottom")) == "top":
            y = 60
        else:
            y = parent_rect.height() - self.height() - 80
        self.move(x, y)

class NotificationManager(QObject):
    _instance = None
    
    def __init__(self):
        super().__init__()
        self.parent_widget = None
        self.toast = None
        self._toast_by_parent = {}
        
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = NotificationManager()
        return cls._instance
        
    def set_parent(self, parent):
        """设置父窗口，通常是 MainWindow"""
        self.parent_widget = parent
        if parent is None:
            return
        try:
            toast = self._toast_by_parent.get(parent)
        except Exception:
            toast = None
        if toast is None:
            toast = ToastWidget(parent)
            try:
                self._toast_by_parent[parent] = toast
            except Exception:
                pass
        self.toast = toast
            
    def show_toast(self, message, duration=2000, parent=None, position: str = "bottom"):
        """显示静默提示文本"""
        target_parent = parent or self.parent_widget
        target_toast = None
        if target_parent is not None:
            try:
                target_toast = self._toast_by_parent.get(target_parent)
            except Exception:
                target_toast = None
            if target_toast is None:
                target_toast = ToastWidget(target_parent)
                try:
                    self._toast_by_parent[target_parent] = target_toast
                except Exception:
                    pass
        if target_toast is None:
            target_toast = self.toast
        if target_toast:
            target_toast.show_message(message, duration, position=position)
            
    def show_warning(self, title, message):
        """显示警告对话框"""
        try:
            LogManager.instance().warning(f"{title}: {message}")
        except Exception:
            pass
        if self.parent_widget:
            msg_box = CustomMessageBox(self.parent_widget, title, message, CustomMessageBox.WARNING)
            msg_box.exec()
            
    def show_error(self, title, message):
        """显示错误对话框"""
        try:
            LogManager.instance().error(f"{title}: {message}")
        except Exception:
            pass
        if self.parent_widget:
            msg_box = CustomMessageBox(self.parent_widget, title, message, CustomMessageBox.ERROR)
            msg_box.exec()
            sys.exit(0)
            
    def show_info(self, title, message):
        """显示信息对话框（如果需要强制弹窗），通常操作成功建议用 show_toast"""
        try:
            LogManager.instance().info(f"{title}: {message}")
        except Exception:
            pass
        if self.parent_widget:
            msg_box = CustomMessageBox(self.parent_widget, title, message, CustomMessageBox.INFO)
            msg_box.exec()
            
    def ask_confirmation(self, title, message, show_checkbox=False, checkbox_text="", default_checked=False):
        """
        显示确认对话框，返回 (confirmed, checkbox_checked)
        如果 show_checkbox=False (默认)，返回 confirmed (bool)
        """
        if self.parent_widget:
            msg_box = CustomMessageBox(self.parent_widget, title, message, CustomMessageBox.QUESTION)
            if show_checkbox and checkbox_text:
                msg_box.add_checkbox(checkbox_text, default_checked=default_checked)
            
            result = msg_box.exec() == CustomMessageBox.Accepted
            
            if show_checkbox:
                return result, msg_box.is_checkbox_checked()
            return result
        
        if show_checkbox:
            return False, False
        return False
