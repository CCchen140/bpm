from PyQt6.QtWidgets import (QWidget, QGridLayout, QVBoxLayout, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint, QEvent, QSize, QTimer
from PyQt6.QtGui import QCursor, QPixmap
from ui.utils.icon_loader import qta
from ui.widgets.image_thumbnail import ImageThumbnail
from ui.zoomable_scroll_area import ZoomableScrollArea
from ui.utils.shortcut_manager import ShortcutManager
from ui.utils.color_manager import ColorManager

class ThumbnailGridView(QWidget):
    # Signals
    itemClicked = pyqtSignal(int, object) # index, modifiers
    itemDoubleClicked = pyqtSignal(int) # index
    contextMenuRequested = pyqtSignal(int, object) # index, pos (For thumbnail context menu)
    backgroundContextMenuRequested = pyqtSignal(QPoint)
    selectionChanged = pyqtSignal(int) # selected count
    zoomRequested = pyqtSignal(int)
    scrollValueChanged = pyqtSignal(int)
    blankClicked = pyqtSignal()
    sprayActionRequested = pyqtSignal(str, object, list) # type, value, indices
    sprayCancelRequested = pyqtSignal()
    
    # Internal signals to proxy from thumbnails
    thumbnailClicked = pyqtSignal(int, object) # index, modifiers

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbnails = []
        self.current_thumb_size = 120
        self._display_mode = ImageThumbnail.MODE_WITH_NAME
        self.last_selected_index = -1
        self.settings_manager = None
        self.spray_mode_active = False
        self.spray_action = None
        self._spray_cursor = None
        self.spray_range_cells = 1
        self._thumb_box_select_active = False
        self._thumb_box_start_pos = None
        self._last_cols = None
        self.init_ui()
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()

    def _update_minimum_width_for_single_thumb(self):
        try:
            mode = self._display_mode
        except Exception:
            mode = ImageThumbnail.MODE_WITH_NAME
        try:
            if self.thumbnails:
                mode = int(getattr(self.thumbnails[0], "display_mode", mode) or mode)
        except Exception:
            pass
        try:
            thumb_w, _thumb_h = ImageThumbnail.calculate_size(self.current_thumb_size, mode)
        except Exception:
            try:
                if isinstance(self.current_thumb_size, (tuple, list)):
                    thumb_w = int(self.current_thumb_size[0])
                else:
                    thumb_w = int(self.current_thumb_size)
            except Exception:
                thumb_w = 120
        try:
            min_w = max(1, int(thumb_w))
        except Exception:
            min_w = 120
        try:
            self.setMinimumWidth(min_w)
        except Exception:
            pass
        try:
            if hasattr(self, "scroll_area") and self.scroll_area is not None:
                self.scroll_area.setMinimumWidth(min_w)
        except Exception:
            pass
        try:
            if hasattr(self, "thumbnails_container") and self.thumbnails_container is not None:
                self.thumbnails_container.setMinimumWidth(min_w)
        except Exception:
            pass

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 容器 widget
        self.thumbnails_container = QWidget()
        self.thumbnails_layout = QGridLayout(self.thumbnails_container)
        self.thumbnails_layout.setSpacing(0)
        self.thumbnails_layout.setContentsMargins(0, 0, 0, 0) # 移除右侧预留的60px空间
        self.thumbnails_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.spray_range_overlay = QFrame(self.thumbnails_container)
        self.spray_range_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.spray_range_overlay.hide()
        
        # 启用背景右键菜单
        self.thumbnails_container.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnails_container.customContextMenuRequested.connect(self._on_background_context_menu_requested)

        # Scroll Area
        self.scroll_area = ZoomableScrollArea()
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scroll_area.blank_clicked.connect(self.blankClicked.emit)
        self.scroll_area.setWidget(self.thumbnails_container)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Install event filter to listen for resize
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.installEventFilter(self)
        try:
            self.scroll_area.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception:
            pass
        
        self.scroll_area.zoom_requested.connect(self.zoomRequested.emit)
        self.scroll_area.box_select_requested.connect(self.on_box_select)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.scrollValueChanged.emit)
        
        layout.addWidget(self.scroll_area)
        self._update_minimum_width_for_single_thumb()

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.primary")
        scrollbar_bg = cm.get("theme.background.dark")
        scrollbar_handle = cm.get("popup.border.primary")
        scrollbar_hover = cm.get("theme.primary")
        spray_bg = cm.to_qss_color("thumbnail_grid.spray_overlay.background")
        spray_border = cm.to_qss_color("thumbnail_grid.spray_overlay.border")
        self.thumbnails_container.setStyleSheet(f"background-color: {panel_bg};")
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {panel_bg};
            }}
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 10px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {scrollbar_handle};
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {scrollbar_hover};
            }}
            QScrollBar:horizontal {{
                background-color: {scrollbar_bg};
                height: 10px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {scrollbar_handle};
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {scrollbar_hover};
            }}
        """)
        self.spray_range_overlay.setStyleSheet(f"""
            background-color: {spray_bg};
            border: 1px solid {spray_border};
        """)
        for thumbnail in self.thumbnails:
            thumbnail.base_bg_color = panel_bg
            thumbnail.update()
        
        # 清除缓存的喷漆光标，以便下次获取时使用新的主题色
        self._spray_cursor = None
        if self.spray_mode_active:
            # 如果当前处于喷漆模式，立即更新光标
            cursor = self._create_spray_cursor()
            self.setCursor(cursor)
            self.scroll_area.viewport().setCursor(cursor)
            self.thumbnails_container.setCursor(cursor)
            for t in self.thumbnails:
                t.setCursor(cursor)

    def eventFilter(self, source, event):
        if isinstance(source, ImageThumbnail):
            if self.spray_mode_active:
                # 右键不再强制退出喷漆模式，而是允许透传以唤起菜单
                # if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
                #     self.sprayCancelRequested.emit()
                #     return True
                # if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.RightButton:
                #     return True
                # if event.type() == QEvent.Type.ContextMenu:
                #     self.sprayCancelRequested.emit()
                #     return True
                pass

            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._thumb_box_select_active = False
                self._thumb_box_start_pos = source.mapTo(self.thumbnails_container, event.position().toPoint())
            elif event.type() == QEvent.Type.MouseMove:
                if (event.buttons() & Qt.MouseButton.LeftButton) and self._thumb_box_start_pos is not None:
                    from PyQt6.QtWidgets import QApplication
                    current_pos = source.mapTo(self.thumbnails_container, event.position().toPoint())
                    if not self._thumb_box_select_active:
                        if (current_pos - self._thumb_box_start_pos).manhattanLength() >= QApplication.startDragDistance():
                            self._thumb_box_select_active = True
                            self.scroll_area.start_box_select(self._thumb_box_start_pos)
                    if self._thumb_box_select_active:
                        self.scroll_area.update_box_select(current_pos)
                if self.spray_mode_active:
                    try:
                        viewport_pos = self.scroll_area.viewport().mapFromGlobal(event.globalPosition().toPoint())
                    except Exception:
                        viewport_pos = self.scroll_area.viewport().mapFromGlobal(QCursor.pos())
                    self._update_spray_range_overlay(viewport_pos)
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._thumb_box_select_active:
                    self.scroll_area.finish_box_select()
                self._thumb_box_select_active = False
                self._thumb_box_start_pos = None

        if source == self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            # 延迟调用 arrange_thumbnails，避免频繁重绘
            # 优化：添加防抖动或限流机制
            # 但这里为了简单，先判断宽度是否发生实质性变化（影响列数）才重排
            
            # 假设我们已经有了 _last_viewport_width
            new_width = self.scroll_area.viewport().width()
            old_width = getattr(self, "_last_viewport_width", -1)
            
            if new_width != old_width:
                self._last_viewport_width = new_width
                
                # 计算新旧列数是否一致，如果不一致才需要重排
                thumb_size = self.current_thumb_size
                thumb_w = thumb_size
                if isinstance(thumb_size, (tuple, list)):
                    thumb_w = int(thumb_size[0])
                
                # 预估列数
                cols = max(1, new_width // thumb_w)
                
                # 如果列数变了，或者之前从未布局过
                if cols != getattr(self, "_last_cols", -1):
                    self.arrange_thumbnails()
                else:
                    # 列数没变，但可能宽度微调导致对齐变化（如果使用了居中对齐逻辑，但当前是左对齐）
                    # 当前布局是左对齐且自适应，列数不变时，QGridLayout 会自动处理拉伸
                    # 除非我们需要手动调整间距
                    pass
                    
        if source == self.scroll_area.viewport() and event.type() == QEvent.Type.MouseMove:
            if self.spray_mode_active:
                self._update_spray_range_overlay(event.position().toPoint())
        # if source == self.scroll_area.viewport() and event.type() == QEvent.Type.MouseButtonPress:
        #     if self.spray_mode_active and event.button() == Qt.MouseButton.RightButton:
        #         self.sprayCancelRequested.emit()
        #         return True
        # if source == self.scroll_area.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
        #     if self.spray_mode_active and event.button() == Qt.MouseButton.RightButton:
        #         return True
        # if source == self.scroll_area.viewport() and event.type() == QEvent.Type.ContextMenu:
        #     if self.spray_mode_active:
        #         self.sprayCancelRequested.emit()
        #         return True
        if source == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            if self.spray_mode_active:
                sm = ShortcutManager.instance()
                is_zoom_in = sm.check_library_zoom_in(event)
                is_zoom_out = sm.check_library_zoom_out(event)
                if is_zoom_in or is_zoom_out:
                    steps = 1 if is_zoom_in else -1
                    self._set_spray_range_cells(self.spray_range_cells + steps)
                    if self.settings_manager:
                        self.settings_manager.set("library/spray_range_size", int(self.spray_range_cells))
                    self._update_spray_range_overlay(event.position().toPoint())
                    event.accept()
                    return True
        if (source == self.scroll_area.viewport() or source == self.scroll_area) and event.type() == QEvent.Type.KeyPress:
            if self._handle_thumbnail_nav_key(event):
                event.accept()
                return True
        return super().eventFilter(source, event)

    def _handle_thumbnail_nav_key(self, event) -> bool:
        if not self.thumbnails:
            return False
        try:
            modifiers = event.modifiers()
            if modifiers != Qt.KeyboardModifier.NoModifier:
                return False
        except Exception:
            return False
        sm = ShortcutManager.instance()
        delta = None
        if sm.check_thumbnail_prev(event):
            delta = ("col", -1)
        elif sm.check_thumbnail_next(event):
            delta = ("col", 1)
        elif sm.check_thumbnail_up(event):
            delta = ("row", -1)
        elif sm.check_thumbnail_down(event):
            delta = ("row", 1)
        if delta is None:
            return False
        import time
        now = time.monotonic()
        last = getattr(self, "_last_nav_ts", 0.0)
        if now - last < 0.08:
            return True
        self._last_nav_ts = now
        cur = self._get_nav_current_index()
        if cur is None:
            cur = 0
        cols = self._get_nav_cols()
        axis, step = delta
        if axis == "col":
            if step < 0 and cur <= 0:
                nxt = len(self.thumbnails) - 1
            elif step > 0 and cur >= len(self.thumbnails) - 1:
                nxt = 0
            else:
                nxt = cur + step
        else:
            if step < 0 and cur < cols:
                col = int(cur) % int(cols)
                last_row = int((len(self.thumbnails) - 1) // int(cols))
                nxt = int(last_row * int(cols) + col)
                while nxt >= len(self.thumbnails) and nxt - cols >= 0:
                    nxt -= int(cols)
            elif step > 0 and (cur + cols) >= len(self.thumbnails):
                nxt = int(cur) % int(cols)
            else:
                nxt = cur + step * cols
        nxt = max(0, min(int(nxt), len(self.thumbnails) - 1))
        if nxt == cur:
            return True
        self.select_thumbnail(nxt, scroll_to=True)
        self.last_selected_index = nxt
        try:
            self.thumbnails_container.update()
        except Exception:
            pass
        def _post():
            try:
                self.refresh_visible_thumbnails(extra_rows=1)
            except Exception:
                pass
            try:
                self.itemClicked.emit(int(nxt), Qt.KeyboardModifier.NoModifier)
            except Exception:
                pass
        try:
            QTimer.singleShot(0, _post)
        except Exception:
            _post()
        return True

    def _get_nav_current_index(self):
        try:
            idx = int(getattr(self, "last_selected_index", -1))
        except Exception:
            idx = -1
        if 0 <= idx < len(self.thumbnails):
            return idx
        try:
            for i, t in enumerate(self.thumbnails):
                if getattr(t, "selected", False):
                    return i
        except Exception:
            pass
        return None

    def _get_nav_cols(self) -> int:
        try:
            metrics = self.get_viewport_metrics() or {}
            cols = int(metrics.get("cols", 0) or 0)
            if cols > 0:
                return int(cols)
        except Exception:
            pass
        try:
            viewport_w = int(self.scroll_area.viewport().width())
        except Exception:
            viewport_w = 800
        size = self.current_thumb_size
        if isinstance(size, (tuple, list)) and len(size) >= 1:
            thumb_w = int(size[0])
        else:
            thumb_w = int(size)
        thumb_w = max(1, thumb_w)
        return max(1, int(viewport_w // thumb_w))

    def set_settings_manager(self, settings_manager):
        self.settings_manager = settings_manager

    def _on_background_context_menu_requested(self, pos):
        if self.spray_mode_active:
            self.sprayCancelRequested.emit()
            return
            # pass
        self.backgroundContextMenuRequested.emit(pos)

    def _create_spray_cursor(self):
        if self._spray_cursor is None:
            # 获取主题色
            color = ColorManager.instance().get("theme.text.dark")
            try:
                pixmap = qta.icon('fa5s.spray-can', color=color).pixmap(32, 32)
            except Exception:
                try:
                    pixmap = qta.icon('mdi6.spray-can', color=color).pixmap(32, 32)
                except Exception:
                    try:
                        pixmap = qta.icon('mdi6.spray-can-variant', color=color).pixmap(32, 32)
                    except Exception:
                        pixmap = qta.icon('mdi6.spray', color=color).pixmap(32, 32)
            self._spray_cursor = QCursor(pixmap, 2, 2)
        return self._spray_cursor

    def add_thumbnail(self, thumbnail: ImageThumbnail):
        thumbnail.clicked.connect(self._on_thumbnail_clicked_proxy)
        thumbnail.doubleClicked.connect(self._on_thumbnail_double_clicked_proxy)
        thumbnail.contextMenuRequested.connect(self._on_thumbnail_context_menu_proxy)
        thumbnail.installEventFilter(self)
        thumbnail.base_bg_color = ColorManager.instance().get("theme.background.primary")
        
        # 预先设置尺寸，避免初始加载时尺寸跳变
        # 使用当前显示模式或默认模式
        display_mode = getattr(thumbnail, "display_mode", ImageThumbnail.MODE_WITH_NAME)
        # 如果已经添加到 grid，可能想用 grid 的模式设置
        # 但这里是 add_thumbnail，意味着还没布局。
        # 我们可以显式调用 resize
        w, h = ImageThumbnail.calculate_size(self.current_thumb_size, display_mode)
        thumbnail.setFixedSize(w, h)
        thumbnail.thumb_size = self.current_thumb_size # 确保内部状态同步
        
        if self.spray_mode_active:
            thumbnail.setCursor(self._create_spray_cursor())

        thumbnail.setParent(self.thumbnails_container)
        self.thumbnails.append(thumbnail)

    def clear_thumbnails(self):
        # Remove from layout and list
        while self.thumbnails_layout.count():
            item = self.thumbnails_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.thumbnails.clear()

    def get_available_width(self):
        """获取用于布局的可用宽度"""
        # 如果垂直滚动条可见，需要减去滚动条宽度
        # 但在 ZoomableScrollArea 中，通常通过 viewport().width() 获取实际可用宽度
        return self.scroll_area.viewport().width()

    def get_viewport_metrics(self):
        """获取视口布局的度量信息"""
        available_width = self.get_available_width()
        thumb_size = self.current_thumb_size
        if self.thumbnails:
            mode = self.thumbnails[0].display_mode
        else:
            mode = ImageThumbnail.MODE_WITH_NAME
        thumb_w, thumb_h = ImageThumbnail.calculate_size(thumb_size, mode)
        
        cols = max(1, available_width // thumb_w)
        viewport_h = self.scroll_area.viewport().height()
        
        return {
            "cols": cols,
            "thumb_w": thumb_w,
            "thumb_h": thumb_h,
            "viewport_h": viewport_h
        }

    def get_visible_index_range(self, extra_rows=0):
        metrics = self.get_viewport_metrics()
        if not metrics:
            return 0, -1, 0
        thumb_h = metrics["thumb_h"]
        cols = metrics["cols"]
        viewport_h = metrics["viewport_h"]
        scroll_val = self.scroll_area.verticalScrollBar().value()
        
        # 计算起始行 (向下取整)
        first_row = max(0, scroll_val // max(1, thumb_h))
        
        # 计算结束行
        # 使用 (scroll_val + viewport_h - 1) 找到视口底部的像素位置
        # 然后除以 thumb_h 得到该像素所在的行索引
        # 只要有一像素可见，该行就被视为可见
        view_bottom = scroll_val + viewport_h
        last_row = max(0, (view_bottom - 1) // max(1, thumb_h))
        
        # 添加额外预加载行
        last_row += extra_rows
        
        visible_rows = last_row - first_row + 1
        
        start_index = first_row * cols
        # end_index 是包含在内的
        end_index = min(len(self.thumbnails) - 1, max(0, (last_row + 1) * cols - 1))
        
        return start_index, end_index, visible_rows

    def set_thumbnail_size(self, size, scale_visible_only=False, extra_rows=0):
        """设置缩略图大小并刷新布局"""
        self.current_thumb_size = size
        if scale_visible_only:
            start_index, end_index, _ = self.get_visible_index_range(extra_rows=extra_rows)
            for i, thumb in enumerate(self.thumbnails):
                if start_index <= i <= end_index:
                    thumb.set_size(size, reload_thumbnail=False)
                else:
                    thumb.set_size(size, reload_thumbnail=False)
        else:
            for thumb in self.thumbnails:
                thumb.set_size(size, reload_thumbnail=False)
        self.arrange_thumbnails()
        self._update_minimum_width_for_single_thumb()

    def refresh_specific_thumbnails(self, file_paths):
        """刷新指定路径的缩略图（仅重绘，不重新加载）"""
        target_paths = set(file_paths)
        for thumb in self.thumbnails:
            if thumb.image_info and thumb.image_info['path'] in target_paths:
                thumb.update()

    def refresh_visible_thumbnails(self, extra_rows: int = 1):
        try:
            if not self.thumbnails:
                return
        except Exception:
            return
        try:
            start_index, end_index, _ = self.get_visible_index_range(extra_rows=int(extra_rows))
        except Exception:
            start_index, end_index = 0, len(self.thumbnails) - 1
        start_index = max(0, int(start_index))
        end_index = min(len(self.thumbnails) - 1, int(end_index))
        for i in range(start_index, end_index + 1):
            try:
                self.thumbnails[i].update()
            except Exception:
                pass

    def set_display_mode(self, mode):
        """设置显示模式"""
        try:
            self._display_mode = int(mode)
        except Exception:
            self._display_mode = ImageThumbnail.MODE_WITH_NAME
        for thumb in self.thumbnails:
            thumb.set_display_mode(mode)
        self._update_minimum_width_for_single_thumb()

    def arrange_thumbnails(self):
        """根据容器宽度和缩略图大小重新排列缩略图"""
        if not self.thumbnails:
            return

        # 清除当前布局中的所有项 (但不删除 widget，因为它们还在 self.thumbnails 中)
        # 注意：clear_thumbnails 会删除 widget，这里只是 detach
        while self.thumbnails_layout.count():
            item = self.thumbnails_layout.takeAt(0)
            # Don't delete widget here, just remove from layout
        
        # 重新添加 Header Label 需要被重新创建吗？
        # 原代码每次 arrange_thumbnails 都会重新创建 Header Label。
        # 这里我们也这样做。

        available_width = self.get_available_width()
        thumb_size = self.current_thumb_size
        thumb_w = thumb_size
        if isinstance(thumb_size, (tuple, list)):
            thumb_w = int(thumb_size[0])
        
        # 计算列数：只在连一张图片都放不下时才留白
        cols = max(1, available_width // thumb_w)
        self._last_cols = cols
        
        # 强制布局对齐到左上角
        self.thumbnails_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.thumbnails_container.setUpdatesEnabled(False)
        try:
            for i, thumb in enumerate(self.thumbnails):
                row = i // cols
                col = i % cols
                self.thumbnails_layout.addWidget(thumb, row, col)
                thumb.show()
        finally:
            self.thumbnails_container.setUpdatesEnabled(True)
                
        # 强制布局左对齐，确保列之间没有多余间距
        # 除非那是这一行末尾剩余的空间
        
        # 确保行伸展在最后，将内容顶上去
        self.thumbnails_layout.setRowStretch(self.thumbnails_layout.rowCount(), 1)
        # 确保列伸展在最后，将内容顶到左边
        self.thumbnails_layout.setColumnStretch(cols, 1)
        self.thumbnails_layout.activate()
        self.thumbnails_container.updateGeometry()
        self.thumbnails_container.adjustSize()
        self.thumbnails_container.update()
        self.spray_range_overlay.raise_()

    def append_batch_to_layout(self, start_index):
        """将新添加的缩略图追加到布局中（增量更新），避免全量重排
        
        Args:
            start_index: 新批次的起始索引
        """
        if not self.thumbnails or start_index >= len(self.thumbnails):
            return

        available_width = self.get_available_width()
        thumb_size = self.current_thumb_size
        thumb_w = thumb_size
        if isinstance(thumb_size, (tuple, list)):
            thumb_w = int(thumb_size[0])
        
        # 兼容处理：确保 thumb_w 是整数
        thumb_w = int(thumb_w)
        
        cols = max(1, available_width // thumb_w)
        
        if self._last_cols is not None and cols != self._last_cols:
            self.arrange_thumbnails()
            self.thumbnails_container.updateGeometry()
            self.thumbnails_container.adjustSize()
            return
            
        self._last_cols = cols
        
        # 优化：对于大量添加，暂时关闭布局更新
        # self.setUpdatesEnabled(False) 
        self.thumbnails_container.setUpdatesEnabled(False)
        try:
            for i in range(start_index, len(self.thumbnails)):
                thumb = self.thumbnails[i]
                row = i // cols
                col = i % cols
                self.thumbnails_layout.addWidget(thumb, row, col)
                thumb.show()
        finally:
            self.thumbnails_container.setUpdatesEnabled(True)

            
        # 更新伸展因子（虽然对于增量添加可能不是必须的，但保持一致性）
        self.thumbnails_layout.setRowStretch(self.thumbnails_layout.rowCount(), 1)
        self.thumbnails_layout.setColumnStretch(cols, 1)
        self.thumbnails_layout.activate()
        self.thumbnails_container.updateGeometry()
        self.thumbnails_container.adjustSize()
        self.thumbnails_container.update()
        self.spray_range_overlay.raise_()

    def set_spray_range_size(self, size):
        self._set_spray_range_cells(size)
        if self.spray_mode_active:
            self._update_spray_range_overlay(self.scroll_area.viewport().mapFromGlobal(QCursor.pos()))

    def set_spray_mode(self, active, action_type, value):
        self.spray_mode_active = active
        self.spray_action = (action_type, value)
        
        if active:
            cursor = self._create_spray_cursor()
            self.setCursor(cursor)
            self.scroll_area.viewport().setCursor(cursor)
            self.thumbnails_container.setCursor(cursor)
            for t in self.thumbnails:
                t.setCursor(cursor)
            self.spray_range_overlay.show()
            self.spray_range_overlay.raise_()
            self._update_spray_range_overlay(self.scroll_area.viewport().mapFromGlobal(QCursor.pos()))
        else:
            self.unsetCursor()
            self.scroll_area.viewport().unsetCursor()
            self.thumbnails_container.unsetCursor()
            for t in self.thumbnails:
                t.setCursor(Qt.CursorShape.PointingHandCursor)
            self._spray_cursor = None
            self.spray_range_overlay.hide()

    def _on_thumbnail_clicked_proxy(self, index, modifiers):
        if self.spray_mode_active:
            action_type, value = self.spray_action
            if 0 <= index < len(self.thumbnails):
                center = self.thumbnails_container.mapFromGlobal(QCursor.pos())
                rect = self._get_spray_rect_for_center(center)
                indices = self._get_indices_with_centers_in_rect(rect)
                if indices:
                    self.sprayActionRequested.emit(action_type, value, indices)
            return

        # 内部处理 Shift/Ctrl 逻辑，或者委托给外部 Controller?
        # 现在的要求是 SelectionController 处理。
        # 但为了逐步重构，我可以在这里保留逻辑，或者发出信号让 Controller 处理。
        # 为了 View 的纯粹性，View 应该只告诉 Controller "User clicked item X with modifiers Y".
        # Controller update selection model, and View updates visuals.
        
        # 但是，现在没有 Controller。
        # 所以我先照搬原逻辑，之后再拆分到 SelectionController。
        
        # P1 优化：批量更新选择状态，减少重绘次数
        self._batch_selecting = True
        try:
            if modifiers & Qt.KeyboardModifier.ShiftModifier and self.last_selected_index >= 0:
                start = min(self.last_selected_index, index)
                end = max(self.last_selected_index, index)
                for i, thumb in enumerate(self.thumbnails):
                    if start <= i <= end:
                        thumb.set_selected(True)
                    elif not (modifiers & Qt.KeyboardModifier.ControlModifier):
                        thumb.set_selected(False)
            elif modifiers & Qt.KeyboardModifier.ControlModifier:
                self.thumbnails[index].set_selected(not self.thumbnails[index].selected)
                self.last_selected_index = index
            else:
                # 普通点击：只更新之前选中的和新选中的，而不是全部
                prev_selected = getattr(self, 'last_selected_index', -1)
                if 0 <= prev_selected < len(self.thumbnails) and prev_selected != index:
                    self.thumbnails[prev_selected].set_selected(False)
                self.thumbnails[index].set_selected(True)
                self.last_selected_index = index
        finally:
            self._batch_selecting = False
            # 批量更新完成后统一刷新可见区域
            try:
                if hasattr(self, 'thumbnails_container'):
                    self.thumbnails_container.update()
            except Exception:
                pass

        self.selectionChanged.emit(self.get_selected_count())
        try:
            if hasattr(self, "scroll_area") and self.scroll_area:
                self.scroll_area.setFocus()
        except Exception:
            pass
        self.itemClicked.emit(index, modifiers) # Notify parent to preview image

    def _on_thumbnail_context_menu_proxy(self, index, pos):
        if self.spray_mode_active:
            self.sprayCancelRequested.emit()
            return
            # pass
        # ImageThumbnail emits (index, pos)
        # We emit signal for parent to handle menu with index
        self.contextMenuRequested.emit(index, pos)

    def _on_thumbnail_double_clicked_proxy(self, index):
        if self.spray_mode_active:
            return
        self.itemDoubleClicked.emit(index)

    def on_box_select(self, rect, is_finished):
        if not rect or not self.thumbnails:
            return
            
        if self.spray_mode_active:
            if is_finished:
                indices = self._get_indices_intersecting_rect(rect)
                
                if indices:
                    action_type, value = self.spray_action
                    self.sprayActionRequested.emit(action_type, value, indices)
            return
        
        # 暂时只支持单选模式的框选（即不考虑 Shift/Ctrl）
        # 或者框选就是覆盖选择
        
        for thumb in self.thumbnails:
            thumb_rect = QRect(thumb.pos(), thumb.size())
            if rect.intersects(thumb_rect):
                thumb.set_selected(True)
            else:
                thumb.set_selected(False)
        
        self.selectionChanged.emit(self.get_selected_count())
        
        if self.get_selected_count() == 0:
            self.blankClicked.emit()
            
        if is_finished:
             # Can emit a signal if needed
             pass

    def _get_spray_cell_size(self):
        if self.thumbnails:
            return max(1, self.thumbnails[0].width()), max(1, self.thumbnails[0].height())
        size = self.current_thumb_size
        if isinstance(size, (tuple, list)) and len(size) >= 2:
            return max(1, int(size[0])), max(1, int(size[1]))
        return max(1, int(size)), max(1, int(size))

    def _get_max_spray_range_cells(self):
        cell_w, cell_h = self._get_spray_cell_size()
        container_rect = self.thumbnails_container.rect()
        cols = max(1, (container_rect.width() + cell_w - 1) // cell_w)
        rows = max(1, (container_rect.height() + cell_h - 1) // cell_h)
        return max(cols, rows)

    def _set_spray_range_cells(self, value):
        max_cells = self._get_max_spray_range_cells()
        self.spray_range_cells = max(1, min(int(value), int(max_cells)))

    def _get_spray_rect_for_center(self, center_pos):
        cell_w, cell_h = self._get_spray_cell_size()
        span_w = cell_w * self.spray_range_cells
        span_h = cell_h * self.spray_range_cells
        top_left = QPoint(int(center_pos.x() - (span_w // 2)), int(center_pos.y() - (span_h // 2)))
        rect = QRect(top_left, QSize(int(span_w), int(span_h))).normalized()
        return rect.intersected(self.thumbnails_container.rect())

    def _get_indices_intersecting_rect(self, rect):
        indices = []
        for i, thumb in enumerate(self.thumbnails):
            thumb_rect = QRect(thumb.pos(), thumb.size())
            if rect.intersects(thumb_rect):
                indices.append(i)
        return indices

    def _get_indices_with_centers_in_rect(self, rect):
        if rect is None:
            return []
        hit_rect = QRect(rect)
        hit_rect.adjust(0, 0, -1, -1)
        indices = []
        for i, thumb in enumerate(self.thumbnails):
            if hit_rect.contains(thumb.geometry().center()):
                indices.append(i)
        return indices

    def _update_spray_range_overlay(self, viewport_pos):
        if not self.spray_mode_active or not self.thumbnails:
            self.spray_range_overlay.hide()
            return

        content_pos = self.thumbnails_container.mapFrom(self.scroll_area.viewport(), viewport_pos)
        center = content_pos

        rect = self._get_spray_rect_for_center(center)
        if rect.isEmpty():
            self.spray_range_overlay.hide()
            return

        self.spray_range_overlay.setGeometry(rect)
        self.spray_range_overlay.raise_()
        if not self.spray_range_overlay.isVisible():
            self.spray_range_overlay.show()

    def get_selected_count(self):
        return sum(1 for t in self.thumbnails if t.selected)
        
    def get_selected_thumbnails(self):
        return [t for t in self.thumbnails if t.selected]

    def select_all_thumbnails(self):
        if not self.thumbnails:
            return
        for thumb in self.thumbnails:
            thumb.set_selected(True)
        self.last_selected_index = -1
        self.selectionChanged.emit(self.get_selected_count())

    def clear_selection(self):
        if not self.thumbnails:
            return
        for thumb in self.thumbnails:
            thumb.set_selected(False)
        self.last_selected_index = -1
        try:
            self.selectionChanged.emit(0)
        except Exception:
            pass
        
    def select_thumbnail(self, index, scroll_to=True):
        """Programmatically select a thumbnail by index"""
        if 0 <= index < len(self.thumbnails):
            # Update visual state
            for i, thumb in enumerate(self.thumbnails):
                thumb.set_selected(i == index)
                
            self.last_selected_index = index
            self.selectionChanged.emit(1)
            
            if scroll_to:
                self.scroll_to_index(index)
                
    def scroll_to_index(self, index):
        """Scroll to make the thumbnail at index visible"""
        if 0 <= index < len(self.thumbnails):
            self.scroll_area.ensureWidgetVisible(self.thumbnails[index])
