from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QFocusEvent
from ui.utils.color_manager import ColorManager

class ShortcutRecorder(QLineEdit):
    """
    快捷键录制控件
    点击后进入录制模式，捕获用户按键并生成快捷键字符串
    """
    shortcut_changed = pyqtSignal(str)

    def __init__(self, current_sequence="", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText(current_sequence)
        self.setPlaceholderText("点击设置快捷键")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu) # 禁用右键菜单
        
        self.recording = False
        self.current_sequence = current_sequence
        
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        input_bg = cm.to_qss_color("theme.background.light")
        input_border = cm.to_qss_color("popup.border.primary")
        input_hover_border = cm.to_qss_color("theme.primary")
        input_text = cm.to_qss_color("theme.text.dark")
        selection_bg = cm.to_qss_color("theme.primary")
        selection_text = cm.to_qss_color("theme.text.light")
        recording_bg = cm.to_qss_color("theme.background.dark")
        recording_border = cm.to_qss_color("theme.primary")
        recording_text = cm.to_qss_color("theme.text.dark")
        self.default_style = f"""
            QLineEdit {{
                border: 1px solid {input_border};
                border-radius: 4px;
                padding: 4px;
                background-color: {input_bg};
                color: {input_text};
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
            }}
            QLineEdit:hover {{
                border-color: {input_hover_border};
            }}
        """
        self.recording_style = f"""
            QLineEdit {{
                border: 1px solid {recording_border};
                border-radius: 4px;
                padding: 4px;
                background-color: {recording_bg};
                color: {recording_text};
                font-weight: bold;
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
            }}
        """
        if self.recording:
            self.setStyleSheet(self.recording_style)
        else:
            self.setStyleSheet(self.default_style)

    def setText(self, text):
        """重写 setText 以同步更新 current_sequence"""
        super().setText(text)
        self.current_sequence = text

    def mousePressEvent(self, event):
        if not self.recording:
            self.start_recording()
        # 不调用 super，防止光标移动

    def focusOutEvent(self, event):
        if self.recording:
            self.cancel_recording()
        super().focusOutEvent(event)

    def start_recording(self):
        self.recording = True
        self.setText("请输入快捷键...")
        self.setStyleSheet(self.recording_style)
        self.grabKeyboard() # 捕获键盘输入

    def finish_recording(self, sequence_str):
        self.recording = False
        self.releaseKeyboard()
        self.setText(sequence_str)
        self.current_sequence = sequence_str
        self.setStyleSheet(self.default_style)
        self.clearFocus()
        self.shortcut_changed.emit(sequence_str)

    def cancel_recording(self):
        self.recording = False
        self.releaseKeyboard()
        self.setText(self.current_sequence)
        self.setStyleSheet(self.default_style)
        self.clearFocus()

    def keyPressEvent(self, event):
        if not self.recording:
            return

        key = event.key()
        modifiers = event.modifiers()

        # 1. 处理取消 (Esc)
        if key == Qt.Key.Key_Escape:
            self.cancel_recording()
            return

        # 2. 处理删除 (Backspace/Delete) -> 清除快捷键
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.finish_recording("")
            return

        # 3. 忽略单独的修饰键 (Ctrl, Shift, Alt, Meta)
        # 注意：Qt 中单独按下修饰键时，key() 会返回对应的 Key_Control 等
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return

        # 4. 检查是否包含非法修饰键 (如 Meta/Win 键)
        # 需求：只能使用 Ctrl, Alt, Shift
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            # 如果按下了 Win 键，忽略该组合
            return

        # 5. 生成快捷键字符串
        # 移除 Keypad 修饰符等干扰
        clean_modifiers = modifiers & (Qt.KeyboardModifier.ShiftModifier | 
                                     Qt.KeyboardModifier.ControlModifier | 
                                     Qt.KeyboardModifier.AltModifier)
        
        # 使用 QKeySequence 生成标准字符串
        seq = QKeySequence(key | clean_modifiers.value)
        seq_str = seq.toString()
        
        # 简单的验证
        if seq_str:
            self.finish_recording(seq_str)

    def wheelEvent(self, event):
        if not self.recording:
            return

        # 捕获滚轮事件 (支持 Ctrl+WheelUp 等)
        modifiers = event.modifiers()
        
        # 需求检查：必须有修饰键吗？通常滚轮快捷键带有修饰键
        # 构建字符串
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
            
        delta = event.angleDelta().y()
        if delta > 0:
            parts.append("WheelUp")
        elif delta < 0:
            parts.append("WheelDown")
        else:
            return
            
        seq_str = "+".join(parts)
        if seq_str:
            self.finish_recording(seq_str)
