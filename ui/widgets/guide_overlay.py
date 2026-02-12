from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
import qtawesome as qta

class GuideTooltip(QWidget):
    """引导提示窗口"""
    next_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()

    def __init__(self, parent=None, text="", show_skip=True, is_last=False):
        super().__init__(parent)
        # 改为顶层窗口模式，彻底解决被遮挡或不显示的问题
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) # 不抢占焦点
        
        self._setup_ui()
        self.update_content(text, show_skip, is_last)
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        # 增加边距以防止阴影被裁切 (阴影半径15 + 偏移4)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 主容器
        container = QWidget()
        container.setObjectName("guideTooltipContainer")
        container.setStyleSheet("""
            QWidget#guideTooltipContainer {
                background-color: #ffffff;
                border-radius: 8px;
                border: 1px solid #e0e0e0;
            }
        """)
        
        # 阴影效果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        container.setGraphicsEffect(shadow)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(16, 16, 16, 16)
        container_layout.setSpacing(12)
        
        # 提示文本
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 14px; color: #333333; line-height: 1.4;")
        container_layout.addWidget(self.label)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.skip_btn = QPushButton("跳过向导")
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.setStyleSheet("""
            QPushButton {
                border: none;
                color: #999999;
                font-size: 12px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                color: #666666;
            }
        """)
        self.skip_btn.clicked.connect(self.skip_clicked.emit)
        btn_layout.addWidget(self.skip_btn)
            
        self.next_btn = QPushButton("下一步")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #2573a7;
            }
        """)
        self.next_btn.clicked.connect(self.next_clicked.emit)
        btn_layout.addWidget(self.next_btn)
        
        container_layout.addLayout(btn_layout)
        layout.addWidget(container)

    def update_content(self, text, show_skip, is_last):
        """更新内容"""
        self.label.setText(text)
        self.skip_btn.setVisible(show_skip)
        self.next_btn.setText("完成" if is_last else "下一步")
        
    def paintEvent(self, event):
        # 即使使用了样式表，对于 WA_TranslucentBackground 的子窗口，有时也需要显式绘制以确保显示
        # 但这里主要依赖样式表和容器。
        # 如果仍然不显示，可能是因为顶层窗口的背景透明导致。
        # 这里重写 paintEvent 留空，或者调用父类（虽然 QWidget 默认不绘制）
        # 但我们使用了 QGraphicsDropShadowEffect，这通常需要父控件有内容。
        # 容器 widget#guideTooltipContainer 应该会绘制自己。
        pass

class GuideOverlay(QWidget):
    """引导遮罩层，支持挖孔"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False) # 拦截鼠标事件
        
        self.target_rect = QRect() # 挖孔区域
        self.mask_color = QColor(0, 0, 0, 180) # 半透明黑色背景
        self.padding = 4 # 挖孔内边距
        
    def set_target_rect(self, rect):
        """设置高亮区域（相对于 parent）"""
        self.target_rect = rect
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 创建全屏路径
        path = QPainterPath()
        path.addRect(0, 0, self.width(), self.height())
        
        # 如果有目标区域，减去该区域（挖孔）
        if not self.target_rect.isEmpty():
            hole_path = QPainterPath()
            # 稍微扩大一点区域，并添加圆角
            hole_rect = self.target_rect.adjusted(-self.padding, -self.padding, self.padding, self.padding)
            hole_path.addRoundedRect(hole_rect.x(), hole_rect.y(), hole_rect.width(), hole_rect.height(), 4, 4)
            path = path.subtracted(hole_path)
            
            # 绘制高亮边框
            painter.setPen(QPen(QColor(52, 152, 219), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(hole_rect, 4, 4)
            
        # 绘制遮罩
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.mask_color)
        painter.drawPath(path)

    def mousePressEvent(self, event):
        # 拦截点击事件，防止穿透到下层（除了高亮区域）
        # 如果点击在 target_rect 内，理论上应该允许穿透？
        # 为了简单起见，引导模式下通常需要点击“下一步”才能继续，所以这里完全拦截
        # 或者：如果用户点击了高亮区域，可以视为一种交互，但目前需求是显示提示窗口
        pass
