from PyQt6.QtWidgets import QWidget, QScrollArea, QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from ui.utils.shortcut_manager import ShortcutManager
from ui.utils.color_manager import ColorManager

class ZoomableScrollArea(QScrollArea):
    """支持Ctrl+滚轮缩放和框选的滚动区域"""
    zoom_requested = pyqtSignal(int)
    box_select_requested = pyqtSignal(object, bool)
    blank_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.box_selecting = False
        self.box_start_pos = None
        self.box_end_pos = None
        self.selection_overlay = None

    def _ensure_selection_overlay(self):
        """确保选择框覆盖层已创建"""
        if not self.selection_overlay:
            # 使用viewport作为父控件，而不是widget()
            # 这样覆盖层不会遮挡缩略图内部的图标覆盖层
            self.selection_overlay = QFrame(self.viewport())
            self.selection_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.selection_overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.selection_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            cm = ColorManager.instance()
            bg = cm.to_qss_color("zoomable_scroll_area.selection_overlay.background", default="#2196F333")
            self.selection_overlay.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg};
                    border: 1px solid #2196f3;
                }}
            """)
            self.selection_overlay.setFrameShape(QFrame.Shape.NoFrame)

    def start_box_select(self, content_pos):
        """开始框选
        
        参数:
            content_pos: 相对于内容容器的位置
        """
        if content_pos is None:
            return
        self.box_selecting = True
        self.box_start_pos = content_pos
        self.box_end_pos = content_pos
        self._ensure_selection_overlay()
        self._update_overlay()
        self.selection_overlay.show()
        self.box_select_requested.emit(self._get_select_rect(), False)

    def update_box_select(self, content_pos):
        """更新框选
        
        参数:
            content_pos: 相对于内容容器的位置
        """
        if not self.box_selecting or self.box_start_pos is None or content_pos is None:
            return
        self.box_end_pos = content_pos
        self._update_overlay()
        self.box_select_requested.emit(self._get_select_rect(), False)

    def finish_box_select(self):
        """结束框选"""
        if not self.box_selecting:
            return
        self.box_selecting = False
        if self.box_start_pos and self.box_end_pos:
            self.box_select_requested.emit(self._get_select_rect(), True)
        if self.selection_overlay:
            self.selection_overlay.hide()
        self.box_start_pos = None
        self.box_end_pos = None

    def wheelEvent(self, event):
        sm = ShortcutManager.instance()
        
        def on_zoom():
            delta = event.angleDelta().y()
            self.zoom_requested.emit(delta)
        
        if sm.check_library_zoom_in(event, on_zoom) or sm.check_library_zoom_out(event, on_zoom):
            event.accept()
            return

        super().wheelEvent(event)

    def mousePressEvent(self, event):
        """鼠标按下，开始框选（只在空白区域）"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 获取相对于内容的位置
            content_pos = self.widget().mapFrom(self.viewport(), event.position().toPoint())
            # 检查点击位置是否在空白区域（不在任何子控件上）
            child_at_pos = self.widget().childAt(content_pos)
            if child_at_pos is None:
                # 点击了空白区域
                self.blank_clicked.emit()
                self.start_box_select(content_pos)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动，更新选择框"""
        if self.box_selecting and self.box_start_pos:
            content_pos = self.widget().mapFrom(self.viewport(), event.position().toPoint())
            self.update_box_select(content_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放，结束框选"""
        if event.button() == Qt.MouseButton.LeftButton and self.box_selecting:
            self.finish_box_select()
        super().mouseReleaseEvent(event)

    def _update_overlay(self):
        """更新选择框覆盖层
        
        将内容容器坐标系中的选择矩形转换为viewport坐标系中的位置
        """
        if self.selection_overlay and self.box_start_pos and self.box_end_pos:
            # 计算内容容器中的选择矩形
            content_rect = QRect(self.box_start_pos, self.box_end_pos).normalized()
            
            # 获取滚动偏移量
            h_offset = self.horizontalScrollBar().value()
            v_offset = self.verticalScrollBar().value()
            
            # 将内容坐标转换为viewport坐标
            viewport_rect = QRect(
                content_rect.x() - h_offset,
                content_rect.y() - v_offset,
                content_rect.width(),
                content_rect.height()
            )
            
            self.selection_overlay.setGeometry(viewport_rect)

    def _get_select_rect(self):
        """获取选择矩形（内容容器坐标系）"""
        if self.box_start_pos and self.box_end_pos:
            return QRect(self.box_start_pos, self.box_end_pos).normalized()
        return None
