from PyQt6.QtCore import QObject, Qt, QRect, QTimer
from PyQt6.QtWidgets import QWidget
from ui.widgets.guide_overlay import GuideOverlay, GuideTooltip

class GuideManager(QObject):
    """引导管理器"""
    _instance = None
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = GuideManager()
        return cls._instance
        
    def __init__(self):
        super().__init__()
        self.steps = []
        self.current_step_index = -1
        self.overlay = None
        self.tooltip = None
        self.target_widget = None
        self.parent_widget = None
        self.on_finish_callback = None
        
        # 使用 QTimer 进行 resize 事件的防抖
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(100)
        self._resize_timer.timeout.connect(self._show_step)
        
    def start_guide(self, parent_widget: QWidget, steps: list, on_finish=None):
        """
        启动引导
        :param parent_widget: 引导层覆盖的父窗口（通常是 MainWindow 或 Page）
        :param steps: 引导步骤列表，每项为 dict:
                      {
                          "widget": QWidget,  # 高亮的目标控件
                          "text": str,        # 提示文字
                          "position": str     # "bottom", "top", "left", "right" (可选，默认自动)
                      }
        :param on_finish: 引导结束后的回调函数
        """
        if not steps or not parent_widget:
            return
            
        self.steps = steps
        self.parent_widget = parent_widget
        self.on_finish_callback = on_finish
        self.current_step_index = 0
        
        # 初始化遮罩
        if self.overlay:
            self.overlay.close()
        self.overlay = GuideOverlay(parent_widget)
        self.overlay.resize(parent_widget.size())
        self.overlay.show()
        
        # 监听父窗口大小变化，调整遮罩大小
        parent_widget.installEventFilter(self)
        
        self._show_step()
        
    def _show_step(self):
        if 0 <= self.current_step_index < len(self.steps):
            step = self.steps[self.current_step_index]
            widget = step.get("widget")
            text = step.get("text", "")
            
            # 计算高亮区域（相对于 parent_widget，用于遮罩挖孔）
            target_rect_local = QRect()
            # 计算高亮区域（相对于屏幕全局，用于 Tooltip 定位）
            target_rect_global = QRect()
            
            # 安全检查：防止访问已删除的 C++ 对象
            widget_valid = False
            try:
                # 增强检查：控件不仅要 Visible，还要宽/高大于0，且确实在父窗口树中
                if widget and widget.isVisible() and widget.width() > 0 and widget.height() > 0:
                    widget_valid = True
            except RuntimeError:
                pass
            
            if widget_valid:
                try:
                    # 本地坐标（用于 overlay）
                    pos_local = widget.mapTo(self.parent_widget, widget.rect().topLeft())
                    target_rect_local = QRect(pos_local, widget.size())
                    
                    # 全局坐标（用于 tooltip）
                    pos_global = widget.mapToGlobal(QPoint(0, 0))
                    target_rect_global = QRect(pos_global, widget.size())
                    
                    # 验证全局坐标是否合理 (例如是否完全在屏幕外)
                    screen = self.parent_widget.screen() if self.parent_widget else None
                    if screen:
                        screen_geo = screen.availableGeometry()
                        # 如果目标区域完全不在屏幕内，可能需要跳过或回退到屏幕中心
                        if not target_rect_global.intersects(screen_geo):
                            # 控件在屏幕外，回退到屏幕中心显示
                            target_rect_global = QRect(screen_geo.center(), QSize(0,0))
                except Exception:
                    pass
            
            # 更新遮罩 (使用本地坐标)
            if self.overlay:
                # 如果 target_rect_local 为空，遮罩会全黑，这符合预期（找不到目标时只显示文本）
                self.overlay.set_target_rect(target_rect_local)
                self.overlay.raise_()
            
            is_last = (self.current_step_index == len(self.steps) - 1)
            
            # 复用 Tooltip 实例，避免销毁重建
            if not self.tooltip:
                # Tooltip 作为独立顶层窗口
                self.tooltip = GuideTooltip(self.parent_widget, text, show_skip=True, is_last=is_last)
                self.tooltip.next_clicked.connect(self.next_step)
                self.tooltip.skip_clicked.connect(self.stop_guide)
            
            # 更新内容
            self.tooltip.update_content(text, show_skip=True, is_last=is_last)
            
            # 如果没有有效的目标区域（例如控件不可见），我们将 Tooltip 居中显示在主窗口
            final_target_rect = target_rect_global
            if final_target_rect.isEmpty():
                 # 使用主窗口的全局坐标中心
                 if self.parent_widget:
                     final_target_rect = QRect(self.parent_widget.mapToGlobal(self.parent_widget.rect().center()), QSize(0,0))
                 else:
                     final_target_rect = QRect(960, 540, 0, 0) # 最后的兜底
            
            # 计算提示框位置 (使用全局坐标)
            self._position_tooltip(final_target_rect)
            self.tooltip.show()
        else:
            self.stop_guide()
            
    def _position_tooltip(self, target_rect):
        """
        target_rect: 目标控件在屏幕上的绝对坐标区域 (Global Rect)
        """
        if not self.tooltip:
            return
            
        tooltip_width = 300
        spacing = 10
        
        # 设置固定宽度并强制刷新布局以准确计算高度
        self.tooltip.setFixedWidth(tooltip_width)
        # 强制布局更新，因为 adjustSize 在某些情况下可能不准确（特别是包含 wordWrap Label 时）
        if self.tooltip.layout():
             self.tooltip.layout().activate()
        self.tooltip.adjustSize()
        
        # 使用 sizeHint 可能更准确？对于 ToolWindow，adjustSize 通常有效，但多行文本可能滞后
        # 尝试再次获取高度
        tooltip_height = self.tooltip.height()
        
        # 尝试下方
        x = target_rect.center().x() - tooltip_width // 2
        y = target_rect.bottom() + spacing
        
        # 获取当前屏幕几何信息 (优先使用 parent_widget 所在的屏幕)
        screen = None
        if self.parent_widget:
            screen = self.parent_widget.screen()
        if not screen and self.tooltip:
            screen = self.tooltip.screen()
            
        if screen:
            screen_rect = screen.availableGeometry()
        else:
            # 降级处理
            screen_rect = QRect(0, 0, 1920, 1080)
        
        # 水平修正
        if x < screen_rect.left() + 10: 
            x = screen_rect.left() + 10
        if x + tooltip_width > screen_rect.right() - 10:
            x = screen_rect.right() - 10 - tooltip_width
            
        # 垂直修正
        # 如果下方超出屏幕底部
        if y + tooltip_height > screen_rect.bottom() - 10:
            # 尝试放上方
            y_top = target_rect.top() - tooltip_height - spacing
            
            # 检查上方是否超出屏幕顶部
            if y_top < screen_rect.top() + 10:
                # 上下都放不下，选择空间较大的一侧或强制贴边
                # 这里强制贴在屏幕可视区域内
                if screen_rect.bottom() - target_rect.bottom() > target_rect.top() - screen_rect.top():
                     # 下方空间更大，贴底显示
                     y = screen_rect.bottom() - 10 - tooltip_height
                else:
                     # 上方空间更大，贴顶显示
                     y = screen_rect.top() + 10
            else:
                y = y_top

        self.tooltip.move(int(x), int(y))
            
    def next_step(self):
        self.current_step_index += 1
        self._show_step()
        
    def stop_guide(self):
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        if self.tooltip:
            self.tooltip.close()
            self.tooltip = None
            
        if self.parent_widget:
            self.parent_widget.removeEventFilter(self)
            self.parent_widget = None # 断开引用，防止内存泄漏
            
        self.steps = [] # 清空步骤，释放对控件的引用
            
        if self.on_finish_callback:
            self.on_finish_callback()

    def eventFilter(self, obj, event):
        if obj == self.parent_widget and event.type() == event.Type.Resize:
            # [Fix] 增加尺寸变化检测，防止死循环
            # GuideTooltip 的创建或 adjustSize 可能触发父窗口的 Resize 事件（即使尺寸未变）
            # 如果不加此判断，会形成: Resize -> Timer -> show_step -> Tooltip.adjustSize -> Resize 的死循环
            if hasattr(self, '_last_parent_size') and self._last_parent_size == obj.size():
                return False
            self._last_parent_size = obj.size()

            if self.overlay:
                self.overlay.resize(obj.size())
                # 重新计算高亮和提示框位置
                # 修复：使用 _resize_timer (100ms) 进行防抖，替代原先的 singleShot(0)
                # 这避免了在 resize 过程中频繁调用 _show_step 和访问 layout
                self._resize_timer.start()
        return False
