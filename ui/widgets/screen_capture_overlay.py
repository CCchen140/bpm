# -*- coding: utf-8 -*-
"""
屏幕截图蒙层和框选窗口
用于全局快捷键识鸟功能
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QRect, QPoint, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap, 
    QScreen, QCursor, QFont, QIcon
)
import qtawesome as qta

from ui.utils.color_manager import ColorManager
from ui.utils.notification_manager import NotificationManager


class SelectionRect:
    """选区矩形，支持四个角缩放"""
    def __init__(self, x=0, y=0, width=0, height=0):
        self.rect = QRect(x, y, width, height)
        self.dragging = False
        self.resizing = False
        self.resize_corner = None  # 'tl', 'tr', 'bl', 'br' (top-left, top-right, bottom-left, bottom-right)
        self.drag_start_pos = QPoint()
        self.start_rect = QRect()
    
    def get_handle_rects(self, handle_size=8):
        """获取四个角的拖拽手柄矩形"""
        r = self.rect
        hs = handle_size
        return {
            'tl': QRect(r.left() - hs//2, r.top() - hs//2, hs, hs),
            'tr': QRect(r.right() - hs//2, r.top() - hs//2, hs, hs),
            'bl': QRect(r.left() - hs//2, r.bottom() - hs//2, hs, hs),
            'br': QRect(r.right() - hs//2, r.bottom() - hs//2, hs, hs),
        }
    
    def get_corner_at_pos(self, pos, handle_size=12):
        """检查位置是否在哪个角上"""
        handles = self.get_handle_rects(handle_size)
        for corner, rect in handles.items():
            if rect.contains(pos):
                return corner
        return None
    
    def contains(self, pos):
        """检查位置是否在矩形内"""
        return self.rect.contains(pos)


class ScreenCaptureOverlay(QWidget):
    """
    屏幕截图蒙层窗口
    透明黑色蒙层 + 鼠标框选 + 工具栏
    """
    # 信号
    capture_confirmed = pyqtSignal(QRect)  # 确认截图，发送选区矩形
    capture_cancelled = pyqtSignal()  # 取消截图
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("截图识鸟")
        self._setup_window()
        self._init_ui()
        self._init_state()
        
    def _setup_window(self):
        """设置窗口属性"""
        # 全屏无边框窗口
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 启用鼠标跟踪，使鼠标移动时不点击也能触发mouseMoveEvent
        self.setMouseTracking(True)
        # 默认使用箭头光标，框选时再切换为十字
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # 获取当前鼠标所在屏幕的尺寸
        screen = QApplication.screenAt(QCursor.pos())
        if not screen:
            screen = QApplication.primaryScreen()
        self.screen_geometry = screen.geometry()
        self.setGeometry(self.screen_geometry)
        
    def _init_ui(self):
        """初始化UI"""
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 提示标签
        self.tip_label = QLabel("按住鼠标左键框选区域，松开完成选择")
        self.tip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tip_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                background-color: rgba(0, 0, 0, 180);
                padding: 10px 20px;
                border-radius: 5px;
            }
        """)
        self.tip_label.setFixedHeight(50)
        layout.addWidget(self.tip_label, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()

        # 工具栏（初始隐藏，使用绝对定位）
        self.toolbar = QWidget(self)
        self.toolbar.setStyleSheet("""
            QWidget {
                background-color: rgba(40, 40, 40, 230);
                border-radius: 8px;
                padding: 5px;
            }
        """)

        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect(self.toolbar)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 4)
        self.toolbar.setGraphicsEffect(shadow)

        toolbar_inner = QHBoxLayout(self.toolbar)
        toolbar_inner.setContentsMargins(10, 5, 10, 5)
        toolbar_inner.setSpacing(15)

        # 确认按钮（对号）
        self.confirm_btn = QPushButton()
        self.confirm_btn.setIcon(qta.icon('mdi6.check', color='#4CAF50'))
        self.confirm_btn.setIconSize(QSize(24, 24))
        self.confirm_btn.setFixedSize(40, 40)
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 30);
            }
        """)
        self.confirm_btn.setToolTip("开始识别 (Enter)")
        self.confirm_btn.clicked.connect(self._on_confirm)
        toolbar_inner.addWidget(self.confirm_btn)

        # 取消按钮（错号）
        self.cancel_btn = QPushButton()
        self.cancel_btn.setIcon(qta.icon('mdi6.close', color='#f44336'))
        self.cancel_btn.setIconSize(QSize(24, 24))
        self.cancel_btn.setFixedSize(40, 40)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: rgba(244, 67, 54, 30);
            }
        """)
        self.cancel_btn.setToolTip("取消 (Esc/右键)")
        self.cancel_btn.clicked.connect(self._on_cancel)
        toolbar_inner.addWidget(self.cancel_btn)

        self.toolbar.hide()
        
    def _init_state(self):
        """初始化状态"""
        self.selection = SelectionRect()
        self.is_selecting = False
        self.select_start_pos = QPoint()  # 框选起始位置
        self.screenshot = None
        self.has_selection = False  # 是否已完成框选
        
    def showEvent(self, event):
        """窗口显示时捕获屏幕"""
        super().showEvent(event)
        self._capture_screen()
        
    def _capture_screen(self):
        """捕获屏幕截图"""
        try:
            # 获取当前窗口所在的屏幕
            screen = QApplication.screenAt(QCursor.pos())
            if not screen:
                screen = QApplication.primaryScreen()
            self.capture_screen = screen
            # 获取屏幕的DPI缩放比例
            self.device_pixel_ratio = screen.devicePixelRatio()
            # 只捕获当前屏幕的内容
            self.screenshot = screen.grabWindow(0)
            # 记录窗口在虚拟桌面的偏移
            self.window_offset = self.mapToGlobal(QPoint(0, 0))
        except Exception as e:
            NotificationManager.instance().show_warning("错误", f"屏幕捕获失败: {e}")
            
    def paintEvent(self, event):
        """绘制蒙层和选区"""
        painter = QPainter(self)
        
        # 绘制半透明黑色蒙层
        overlay_color = QColor(0, 0, 0, 160)
        painter.fillRect(self.rect(), overlay_color)
        
        if self.selection.rect.isValid() and self.selection.rect.width() > 0:
            # 绘制选区内的清晰图像
            if self.screenshot:
                # 考虑DPI缩放，将窗口坐标转换为设备像素坐标
                source_rect = QRect(
                    int(self.selection.rect.x() * self.device_pixel_ratio),
                    int(self.selection.rect.y() * self.device_pixel_ratio),
                    int(self.selection.rect.width() * self.device_pixel_ratio),
                    int(self.selection.rect.height() * self.device_pixel_ratio)
                )
                painter.drawPixmap(self.selection.rect, self.screenshot, source_rect)
            
            # 绘制选区边框
            pen = QPen(QColor(0, 150, 255), 2)
            painter.setPen(pen)
            painter.drawRect(self.selection.rect)
            
            # 绘制四个角的拖拽手柄（12像素大小）
            handles = self.selection.get_handle_rects(12)
            handle_color = QColor(0, 150, 255)
            painter.setBrush(QBrush(handle_color))
            painter.setPen(Qt.PenStyle.NoPen)

            for corner, rect in handles.items():
                painter.drawEllipse(rect)
                
        painter.end()
        
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()

            # 检查是否点击了某个角（用于缩放，使用16像素检测区域）
            corner = self.selection.get_corner_at_pos(pos, handle_size=16)
            if corner and self.has_selection:
                self.selection.resizing = True
                self.selection.resize_corner = corner
                self.selection.drag_start_pos = pos
                self.selection.start_rect = QRect(self.selection.rect)
                # 设置对应的光标
                if corner in ('tl', 'br'):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif corner in ('tr', 'bl'):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                return

            # 检查是否点击在选区内（用于拖动）
            if self.selection.contains(pos) and self.has_selection:
                self.selection.dragging = True
                self.selection.drag_start_pos = pos
                self.selection.start_rect = QRect(self.selection.rect)
                self.setCursor(Qt.CursorShape.SizeAllCursor)  # 拖动时使用移动光标
                return

            # 开始新的选择（隐藏工具栏）
            self.toolbar.hide()
            self.has_selection = False
            self.is_selecting = True
            self.setCursor(Qt.CursorShape.CrossCursor)  # 框选时使用十字光标
            self.select_start_pos = pos  # 记录框选起始位置
            self.selection.rect.setTopLeft(pos)
            self.selection.rect.setBottomRight(pos)
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            # 右键取消
            self._on_cancel()
            
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        pos = event.pos()

        # 处理矩形操作
        if self.is_selecting:
            # 正在框选 - 根据起始点和当前点计算矩形（支持任意方向拖动）
            left = min(self.select_start_pos.x(), pos.x())
            top = min(self.select_start_pos.y(), pos.y())
            right = max(self.select_start_pos.x(), pos.x())
            bottom = max(self.select_start_pos.y(), pos.y())
            self.selection.rect = QRect(left, top, right - left, bottom - top)
            self.update()

        elif self.selection.resizing:
            # 正在缩放
            delta = pos - self.selection.drag_start_pos
            start_rect = self.selection.start_rect

            if self.selection.resize_corner == 'br':
                new_rect = QRect(start_rect.topLeft(), start_rect.bottomRight() + delta)
            elif self.selection.resize_corner == 'tr':
                new_rect = QRect(
                    QPoint(start_rect.left(), start_rect.top() + delta.y()),
                    QPoint(start_rect.right() + delta.x(), start_rect.bottom())
                )
            elif self.selection.resize_corner == 'bl':
                new_rect = QRect(
                    QPoint(start_rect.left() + delta.x(), start_rect.top()),
                    QPoint(start_rect.right(), start_rect.bottom() + delta.y())
                )
            elif self.selection.resize_corner == 'tl':
                new_rect = QRect(start_rect.topLeft() + delta, start_rect.bottomRight())

            if new_rect.width() >= 50 and new_rect.height() >= 50:
                self.selection.rect = new_rect.normalized()
                self.update()
                self._update_toolbar_position()

        elif self.selection.dragging:
            # 正在拖动
            delta = pos - self.selection.drag_start_pos
            new_rect = QRect(self.selection.start_rect)
            new_rect.translate(delta)

            # 限制在屏幕范围内
            screen_rect = self.rect()
            if new_rect.left() < 0:
                new_rect.moveLeft(0)
            if new_rect.top() < 0:
                new_rect.moveTop(0)
            if new_rect.right() > screen_rect.right():
                new_rect.moveRight(screen_rect.right())
            if new_rect.bottom() > screen_rect.bottom():
                new_rect.moveBottom(screen_rect.bottom())

            self.selection.rect = new_rect
            self.update()
            self._update_toolbar_position()

        # 无论是否正在操作，都根据位置更新光标（空闲状态）
        if not self.is_selecting and not self.selection.resizing and not self.selection.dragging:
            self._update_cursor_at_pos(pos)

    def leaveEvent(self, event):
        """鼠标离开窗口时恢复箭头光标"""
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _update_cursor_at_pos(self, pos):
        """根据位置更新鼠标光标形状（仅在已完成框选后有效）"""
        if not self.has_selection:
            # 未完成框选时，保持箭头光标
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        # 使用更大的检测区域（16像素）来检测缩放点
        corner = self.selection.get_corner_at_pos(pos, handle_size=16)
        if corner in ('tl', 'br'):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif corner in ('tr', 'bl'):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif self.selection.contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            # 在选区外，使用箭头光标
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_selecting:
                # 完成框选
                self.is_selecting = False
                self.has_selection = True  # 标记已完成框选
                self.selection.rect = self.selection.rect.normalized()

                # 确保最小尺寸
                if self.selection.rect.width() < 50:
                    self.selection.rect.setWidth(50)
                if self.selection.rect.height() < 50:
                    self.selection.rect.setHeight(50)

                self.update()
                self._show_toolbar()

            elif self.selection.resizing:
                self.selection.resizing = False
                self.selection.resize_corner = None

            elif self.selection.dragging:
                self.selection.dragging = False

            # 释放鼠标后立即根据当前位置更新光标
            current_pos = self.mapFromGlobal(QCursor.pos())
            self._update_cursor_at_pos(current_pos)
                
    def keyPressEvent(self, event):
        """键盘事件"""
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.selection.rect.isValid() and self.selection.rect.width() > 0:
                self._on_confirm()
                
    def _show_toolbar(self):
        """显示工具栏"""
        if self.selection.rect.isValid() and self.selection.rect.width() > 0:
            self._update_toolbar_position()
            self.toolbar.show()
            self.tip_label.setText("调整选区大小或点击对号开始识别")

    def _update_toolbar_position(self):
        """更新工具栏位置（显示在选区下方）"""
        if self.selection.rect.isValid():
            # 获取工具栏实际大小（使用实际尺寸）
            self.toolbar.adjustSize()
            toolbar_width = self.toolbar.width()
            toolbar_height = self.toolbar.height()

            # 工具栏显示在选区下方居中
            toolbar_x = self.selection.rect.center().x() - toolbar_width // 2
            toolbar_y = self.selection.rect.bottom() + 10

            # 确保不超出屏幕底部
            screen_bottom = self.height() - toolbar_height - 20
            if toolbar_y > screen_bottom:
                toolbar_y = self.selection.rect.top() - toolbar_height - 10

            # 确保不超出屏幕左右边界
            if toolbar_x < 10:
                toolbar_x = 10
            if toolbar_x + toolbar_width > self.width() - 10:
                toolbar_x = self.width() - toolbar_width - 10

            self.toolbar.move(toolbar_x, toolbar_y)
            self.toolbar.raise_()  # 确保工具栏在最上层
            
    def _on_confirm(self):
        """确认截图"""
        if self.selection.rect.isValid() and self.selection.rect.width() > 0:
            self.capture_confirmed.emit(self.selection.rect)
            self.close()
            
    def _on_cancel(self):
        """取消截图"""
        self.capture_cancelled.emit()
        self.close()
        
    def get_captured_pixmap(self):
        """获取截图的 QPixmap"""
        if self.screenshot and self.selection.rect.isValid():
            # 考虑DPI缩放，将窗口坐标转换为设备像素坐标
            source_rect = QRect(
                int(self.selection.rect.x() * self.device_pixel_ratio),
                int(self.selection.rect.y() * self.device_pixel_ratio),
                int(self.selection.rect.width() * self.device_pixel_ratio),
                int(self.selection.rect.height() * self.device_pixel_ratio)
            )
            return self.screenshot.copy(source_rect)
        return None


def show_capture_overlay():
    """显示截图蒙层窗口"""
    overlay = ScreenCaptureOverlay()
    overlay.show()
    return overlay
