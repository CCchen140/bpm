from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from ui.utils.color_manager import ColorManager

class LoadingOverlay(QWidget):
    """全屏加载遮罩层"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False) # 拦截鼠标事件
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 布局
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(50, 0, 50, 0)
        
        self.container = QWidget()
        self.container.setFixedSize(400, 200)
        container_layout = QVBoxLayout(self.container)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.setSpacing(20)
        
        # 标题
        self.title_label = QLabel("正在初始化图库...")
        container_layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        container_layout.addWidget(self.progress_bar)
        
        # 状态文字
        self.status_label = QLabel("准备中...")
        container_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignHCenter)
        
        layout.addWidget(self.container)
        
        self.hide()
        self._apply_styles()
        try:
            ColorManager.instance().register_listener(self._apply_styles)
        except Exception:
            pass

    def _apply_styles(self):
        cm = ColorManager.instance()
        primary = cm.get("theme.primary")
        bottom = cm.get("theme.background")
        text_light = cm.get("theme.text.light")
        bar_bg = cm.get("theme.sidebar")
        overlay_bg = cm.get("loading_overlay.container.background")
        gradient = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {primary}, stop:1 {bottom})"
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {overlay_bg};
            }}
        """)
        self.container.setStyleSheet(f"""
            QWidget {{
                background: {gradient};
                border-radius: 10px;
            }}
        """)
        self.title_label.setStyleSheet(f"color: {text_light}; font-size: 18px; font-weight: bold; background: transparent;")
        self.status_label.setStyleSheet(f"color: {text_light}; font-size: 14px; background: transparent;")
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {bar_bg};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {primary};
                border-radius: 4px;
            }}
        """)

    def show_loading(self, title="", message=""):
        if title:
            self.title_label.setText(title)
        if message:
            self.status_label.setText(message)
        else:
            self.status_label.setText("")
        self.progress_bar.setMaximum(0)
        if self.parent():
            try:
                self.resize(self.parent().size())
            except Exception:
                pass
        self.show()
        self.raise_()

    def hide_loading(self):
        self.hide()

    def update_message(self, message=""):
        self.status_label.setText(message or "")

    def update_progress(self, current, total, message=""):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            percent = int((current / total) * 100)
            self.title_label.setText(f"正在初始化图库... {percent}%")
        else:
            self.progress_bar.setMaximum(0) # 忙碌状态
            
        if message:
            try:
                from utils.system.gpu_utils import get_torch_cuda_check_brief

                gpu_txt = str(get_torch_cuda_check_brief() or "").strip()
            except Exception:
                gpu_txt = ""
            if gpu_txt and ("GPU检测：" not in str(message)):
                message = f"{message} | GPU检测：{gpu_txt}"
            self.status_label.setText(message)

    def resizeEvent(self, event):
        self.resize(self.parent().size())
        super().resizeEvent(event)
