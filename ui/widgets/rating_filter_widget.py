from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QVBoxLayout, QWidgetAction, QLabel)
from PyQt6.QtCore import pyqtSignal, QEvent, QSize, Qt

from PyQt6.QtGui import QIcon, QPainter, QColor, QCursor
import qtawesome as qta

class StarMenuWidget(QWidget):
    clicked = pyqtSignal()
    
    def __init__(self, rating, parent=None):
        super().__init__(parent)
        self.rating = rating
        self.layout = QHBoxLayout(self)
        # 模拟 QMenu item 的 padding: top/bottom=4, left=30 (icon area) + padding, right=20
        # 实际调整以视觉为准
        self.layout.setContentsMargins(30, 4, 20, 4)
        self.layout.setSpacing(2)
        
        icon = qta.icon('fa5s.star', color='#FFCC00')
        pixmap = icon.pixmap(16, 16)
        
        for _ in range(rating):
            lbl = QLabel()
            lbl.setPixmap(pixmap)
            lbl.setFixedSize(16, 16)
            lbl.setStyleSheet("background: transparent;")
            # 让 label 透传鼠标事件，确保 StarMenuWidget 能接收到所有事件
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.layout.addWidget(lbl)
            
        self.layout.addStretch()
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setMouseTracking(True)
        
    def paintEvent(self, event):
        # 使用 paintEvent 绘制背景，避免 setStyleSheet 的性能问题和状态滞后
        painter = QPainter(self)
        # 严格判断鼠标是否在控件范围内
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            painter.fillRect(self.rect(), QColor("#e3f2fd"))
        super().paintEvent(event)
        
    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)
        
    def mouseMoveEvent(self, event):
        self.update()
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

class StarMenuAction(QWidgetAction):
    triggered_rating = pyqtSignal(int)
    
    def __init__(self, rating, parent=None):
        super().__init__(parent)
        self.rating = rating
        self.widget = StarMenuWidget(rating)
        self.setDefaultWidget(self.widget)
        self.widget.clicked.connect(self.on_clicked)
        
    def on_clicked(self):
        self.triggered_rating.emit(self.rating)
        self.trigger()

class StarButton(QPushButton):
    hovered = pyqtSignal(int)
    
    def __init__(self, index, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.index = index
        self.setMouseTracking(True)
        self.setFlat(True)
        
    def enterEvent(self, event):
        self.hovered.emit(self.index)
        super().enterEvent(event)
        
    # def leaveEvent(self, event):
    #     super().leaveEvent(event)

# 五星评分控件（1-5星）
class StarRatingWidget(QWidget):
    ratingChanged = pyqtSignal(int)

    def __init__(self, size=28, font_size=20, orientation='horizontal'):
        super().__init__()
        self.rating = 0
        self.buttons = []
        self.size = size
        self.font_size = font_size
        self.orientation = orientation
        
        # 预加载图标
        # 使用 Apple Yellow (#FFCC00)
        self.icon_selected = qta.icon('fa5s.star', color='#FFCC00')
        self.icon_unselected = qta.icon('fa5s.star', color='#CCCCCC')
        
        if orientation == 'vertical':
            layout = QVBoxLayout(self)
        else:
            layout = QHBoxLayout(self)
            
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 创建5个按钮代表星星（1-5星）
        # 如果是垂直排列，且要求最上面是1星，那么正常添加顺序即可 (layout 从上到下)
        # 1, 2, 3, 4, 5
        range_iter = range(1, 6)
        
        for i in range_iter:
            btn = StarButton(i, "")
            btn.setFixedSize(size, size)
            btn.setIconSize(QSize(font_size, font_size))
            # Use MouseTracking to prevent auto-focus/selection on hover
            btn.setMouseTracking(True) 
            btn.setStyleSheet("border: none; background: transparent;")
            
            btn.clicked.connect(lambda checked, r=i: self.set_rating(r))
            btn.hovered.connect(self.on_button_hovered)
            
            layout.addWidget(btn)
            self.buttons.append(btn)
            
        self.update_display(0)

    def on_button_hovered(self, index):
        # 当鼠标悬停在第 index 个星星上时，1到 index 都显示为选中状态
        self.update_display(preview_rating=index)

    def leaveEvent(self, event):
        # 鼠标离开整个控件时，恢复实际评分显示
        self.update_display(preview_rating=self.rating)
        super().leaveEvent(event)

    def update_display(self, preview_rating):
        for i, btn in enumerate(self.buttons):
            # i 是 0-4，对应星星 1-5
            star_val = i + 1
            is_selected = star_val <= preview_rating
            
            if is_selected:
                btn.setIcon(self.icon_selected)
            else:
                btn.setIcon(self.icon_unselected)


    def set_rating(self, rating, emit_signal=True):
        if self.rating == rating and emit_signal:
            rating = 0 # 取消评分
            
        self.rating = rating
        self.update_display(self.rating)
        
        if emit_signal:
            self.ratingChanged.emit(self.rating)

    def get_rating(self):
        return self.rating