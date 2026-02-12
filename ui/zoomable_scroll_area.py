from PyQt6.QtWidgets import QWidget, QScrollArea
from PyQt6.QtCore import Qt, pyqtSignal, QRect
from ui.utils.shortcut_manager import ShortcutManager
from ui.utils.color_manager import ColorManager

class ZoomableScrollArea(QScrollArea):
    """支持Ctrl+滚轮缩放和框选的滚动区域"""
    # 缩放信号：delta > 0 放大，delta < 0 缩小
    zoom_requested = pyqtSignal(int)
    # 框选信号：发送选择矩形 (rect, is_finished)
    box_select_requested = pyqtSignal(object, bool)
    # 空白区域点击信号
    blank_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.box_selecting = False
        self.box_start_pos = None
        self.box_end_pos = None
        self.selection_overlay = None

    def start_box_select(self, content_pos):
        if content_pos is None:
            return
        self.box_selecting = True
        self.box_start_pos = content_pos
        self.box_end_pos = content_pos
        if not self.selection_overlay:
            self.selection_overlay = QWidget(self.widget())
            cm = ColorManager.instance()
            bg = cm.to_qss_color("zoomable_scroll_area.selection_overlay.background", default="#2196F333")
            self.selection_overlay.setStyleSheet(f"""
                background-color: {bg};
                border: 1px solid #2196f3;
            """)
        self.selection_overlay.raise_()
        self.selection_overlay.show()
        self._update_overlay()
        self.box_select_requested.emit(self._get_select_rect(), False)

    def update_box_select(self, content_pos):
        if not self.box_selecting or self.box_start_pos is None or content_pos is None:
            return
        self.box_end_pos = content_pos
        if self.selection_overlay:
            self.selection_overlay.raise_()
        self._update_overlay()
        self.box_select_requested.emit(self._get_select_rect(), False)

    def finish_box_select(self):
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
        
        # 优先处理快捷键定义的缩放
        if sm.check_library_zoom_in(event, on_zoom) or sm.check_library_zoom_out(event, on_zoom):
            event.accept()
            return

        # 正常滚动
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        """鼠标按下，开始框选（只在空白区域）"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 获取相对于内容的位置
            content_pos = self.widget().mapFrom(self, event.position().toPoint())
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
            content_pos = self.widget().mapFrom(self, event.position().toPoint())
            self.update_box_select(content_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放，结束框选"""
        if event.button() == Qt.MouseButton.LeftButton and self.box_selecting:
            self.finish_box_select()
        super().mouseReleaseEvent(event)

    def _update_overlay(self):
        """更新选择框覆盖层"""
        if self.selection_overlay and self.box_start_pos and self.box_end_pos:
            rect = QRect(self.box_start_pos, self.box_end_pos).normalized()
            self.selection_overlay.setGeometry(rect)

    def _get_select_rect(self):
        """获取选择矩形"""
        if self.box_start_pos and self.box_end_pos:
            return QRect(self.box_start_pos, self.box_end_pos).normalized()
        return None
