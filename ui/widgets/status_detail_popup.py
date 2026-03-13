from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.utils.color_manager import ColorManager
from ui.utils.icon_loader import qta


class StatusDetailPopup(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self._title = str(title or "")
        self._pinned = False
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("statusDetailPopup")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.title_label = QLabel(self._title)
        header.addWidget(self.title_label, 1)

        self.pin_button = QPushButton("")
        self.pin_button.setCheckable(True)
        self.pin_button.setFixedSize(24, 22)
        self.pin_button.clicked.connect(self._on_pin_toggled)
        header.addWidget(self.pin_button, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(header)

        self.rows_widget = QWidget(self)
        self.rows_layout = QGridLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setHorizontalSpacing(12)
        self.rows_layout.setVerticalSpacing(4)
        root.addWidget(self.rows_widget)
        self.setMinimumWidth(240)
        self.refresh_theme()

    def _on_pin_toggled(self, checked: bool):
        self._pinned = bool(checked)

    def is_pinned(self) -> bool:
        return bool(self._pinned)

    def set_rows(self, rows):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for row_idx, (label_text, value_text) in enumerate(rows or []):
            key_label = QLabel(str(label_text or ""))
            key_label.setStyleSheet("font-weight: 600;")
            value_label = QLabel(str(value_text or "--"))
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.rows_layout.addWidget(key_label, row_idx, 0)
            self.rows_layout.addWidget(value_label, row_idx, 1)
        self.adjustSize()

    def refresh_theme(self):
        cm = ColorManager.instance()
        bg = cm.get("popup.background.primary", "#FFFFFF")
        border = cm.get("popup.border.primary", "#D0D0D0")
        text_dark = cm.get("theme.text.dark", "#333333")
        text_muted = cm.get("theme.text.light", "#FFFFFF")
        primary = cm.get("theme.primary", "#2196F3")
        secondary = cm.get("theme.background.secondary", "#F5F5F5")
        self.setStyleSheet(
            f"""
            QFrame#statusDetailPopup {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QLabel {{
                color: {text_dark};
                background: transparent;
            }}
            QPushButton {{
                background-color: {secondary};
                color: {text_dark};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 1px 4px;
            }}
            QPushButton:checked {{
                background-color: {primary};
                color: {text_muted};
            }}
            """
        )
        try:
            self.title_label.setStyleSheet(f"font-weight: 600; color: {text_dark};")
        except Exception:
            pass
        try:
            self.pin_button.setIcon(qta.icon("ri.pushpin-fill", color=text_dark))
            self.pin_button.setIconSize(QSize(14, 14))
            self.pin_button.setText("")
        except Exception:
            self.pin_button.setText("Pin")

    def event(self, event):
        try:
            if event.type() == QEvent.Type.WindowDeactivate and not self.is_pinned():
                self.hide()
        except Exception:
            pass
        return super().event(event)
