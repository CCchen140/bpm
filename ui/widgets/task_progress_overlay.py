from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout
from PyQt6.QtCore import Qt

from ui.utils.color_manager import ColorManager


class TaskProgressOverlay(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskProgressOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._margin = 0
        self._full_text = ""
        self._device_text = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 16, 12, 16)
        root.setSpacing(8)

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(8)
        root.addLayout(bar_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bar_row.addWidget(self.progress_bar, 1)

        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.label)
        
        # 设备信息标签（显示 GPU/CPU 状态）
        self.device_label = QLabel("")
        self.device_label.setWordWrap(True)
        self.device_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.device_label)

        self.hide()
        self._apply_styles()
        try:
            ColorManager.instance().register_listener(self._apply_styles)
        except Exception:
            pass

    def _apply_styles(self):
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary", "#D0D0D0")
        bg = cm.get("theme.background.primary", "#FFFFFF")
        text_color = cm.get("popup.text.primary", "#333333")
        primary_color = cm.get("theme.primary", "#2196F3")
        bar_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        hover_bg = cm.get("theme.background.dark", "#EAECEF")

        self.setStyleSheet(f"""
            QFrame#taskProgressOverlay {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {bar_bg};
                border-radius: 4px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {primary_color};
                border-radius: 4px;
            }}
        """)
        self.label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: 12px;
                background: transparent;
                border: none;
            }}
        """)
        self.device_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: 11px;
                background: transparent;
                border: none;
            }}
        """)

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        try:
            rect = parent.rect()
        except Exception:
            return

        max_w = 560
        width = min(max_w, max(1, int(rect.width()) - 24))
        
        # 先设置宽度，让布局计算高度
        self.setFixedWidth(int(width))
        
        # 使用 sizeHint 获取布局推荐的高度
        try:
            hint = self.sizeHint()
            h = max(hint.height(), 80)  # 最小高度 80
        except Exception:
            h = 80
            
        x = int((int(rect.width()) - int(width)) / 2)
        try:
            y = int((int(rect.height()) - int(h)) / 2 + int(self._margin or 0))
        except Exception:
            y = int((int(rect.height()) - int(h)) / 2)
        try:
            if self.geometry().x() != int(x) or self.geometry().y() != int(y) or self.geometry().width() != int(width) or self.geometry().height() != int(h):
                self.setGeometry(int(x), int(y), int(width), int(h))
        except Exception:
            pass
        try:
            self.raise_()
        except Exception:
            pass
        try:
            self._update_elided_text()
        except Exception:
            pass

    def _update_elided_text(self):
        # 直接显示完整文本，不截断
        try:
            self.label.setText(str(self._full_text or ""))
        except Exception:
            pass

    def resizeEvent(self, event):
        try:
            self._update_elided_text()
        except Exception:
            pass
        try:
            return super().resizeEvent(event)
        except Exception:
            return

    def set_progress(self, *, visible: bool, current: int = 0, total: int = 0, text: str = "", device_text: str = ""):
        try:
            self._full_text = str(text or "")
        except Exception:
            self._full_text = ""
        try:
            self._device_text = str(device_text or "")
        except Exception:
            self._device_text = ""
        try:
            self._update_elided_text()
        except Exception:
            pass
        try:
            if self._device_text:
                self.device_label.setText(self._device_text)
                self.device_label.show()
            else:
                self.device_label.hide()
        except Exception:
            pass

        if not visible:
            self.hide()
            return

        if total and total > 0:
            try:
                self.progress_bar.setRange(0, int(total))
                self.progress_bar.setValue(min(int(current), int(total)))
            except Exception:
                pass
        else:
            try:
                self.progress_bar.setRange(0, 0)
            except Exception:
                pass

        self.reposition()
        try:
            if not self.isVisible():
                self.show()
        except Exception:
            self.show()
