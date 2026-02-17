from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QPushButton, QLabel, QScrollArea, QWidget, QCheckBox, 
                             QLayout, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect, QPoint
from ui.utils.icon_loader import qta
from ui.utils.color_manager import ColorManager
from utils.tag_manager import TagManager
from ui.dialogs.tag_manager_dialog import TagWidget

class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super(FlowLayout, self).__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

        self.itemList = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if index >= 0 and index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if index >= 0 and index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = self.doLayout(QRect(0, 0, width, 0), True)
        return height

    def setGeometry(self, rect):
        super(FlowLayout, self).setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        spacing = self.spacing()

        for item in self.itemList:
            wid = item.widget()
            spaceX = spacing + wid.style().layoutSpacing(QSizePolicy.ControlType.PushButton, QSizePolicy.ControlType.PushButton, Qt.Orientation.Horizontal)
            spaceY = spacing + wid.style().layoutSpacing(QSizePolicy.ControlType.PushButton, QSizePolicy.ControlType.PushButton, Qt.Orientation.Vertical)
            
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()

class SprayTagSelectionDialog(QDialog):
    # tags_list: list of strings, is_append: bool
    tagsSelected = pyqtSignal(list, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(500, 450) # Increased size
        self.drag_pos = None
        
        self.all_tags = TagManager.instance().get_all_tags()
        self.all_tags.sort()
        
        self.selected_tags = set()
        
        self._init_ui()
        
    def _init_ui(self):
        cm = ColorManager.instance()
        bg_color = cm.get("popup.background.primary", "#FFFFFF")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        header_bg = cm.get("popup.header.background", "#2c3e50")
        header_text_color = cm.get("popup.header.text", "#FFFFFF")
        hover_bg = cm.get("theme.background.dark")
        primary = cm.get("theme.primary")
        light_text = cm.get("theme.text.light")

        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Container
        self.container = QWidget()
        self.container.setObjectName("container")
        self.container.setStyleSheet(f"""
            QWidget#container {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 1. Title Bar
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {header_bg};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border-bottom: 1px solid {header_bg};
            }}
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(15, 0, 5, 0)
        
        title_label = QLabel("选择喷漆标签")
        title_label.setStyleSheet(f"""
            color: {header_text_color};
            font-size: 14px;
            font-weight: bold;
            border: none;
            background: transparent;
        """)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        close_btn = QPushButton()
        close_btn.setIcon(qta.icon('mdi6.close', color=header_text_color))
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)
        close_btn.clicked.connect(self.reject)
        title_layout.addWidget(close_btn)
        
        layout.addWidget(title_bar)
        
        # 2. Content
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)
        
        # Input & Add
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入新标签...")
        self.input_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {bg_color};
                color: {text_color};
                font-size: 13px;
                height: 20px;
            }}
        """)
        self.input_edit.returnPressed.connect(self._add_new_tag)
        input_layout.addWidget(self.input_edit)

        self.add_btn = QPushButton("添加")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setFixedWidth(60)
        self.add_btn.setFixedHeight(38)
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary};
                color: {light_text};
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)
        self.add_btn.clicked.connect(self._add_new_tag)
        input_layout.addWidget(self.add_btn)

        content_layout.addLayout(input_layout)
        
        # Tags List
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        self.flow_layout = FlowLayout(scroll_content, margin=0, spacing=8)
        scroll_content.setLayout(self.flow_layout)
        scroll.setWidget(scroll_content)
        
        self._populate_tags()
        
        content_layout.addWidget(scroll)
        
        # Bottom Controls
        bottom_layout = QHBoxLayout()
        
        # Append Mode Checkbox
        self.append_check = QCheckBox("补加模式（不覆盖已有标签）")
        self.append_check.setChecked(False) # Default overwrite as requested ("默认是覆盖")
        self.append_check.setStyleSheet(f"""
            QCheckBox {{
                color: {text_color};
                font-size: 13px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
            }}
        """)
        bottom_layout.addWidget(self.append_check)
        
        bottom_layout.addStretch()
        
        # Clear All Button
        self.clear_btn = QPushButton("清除所有标签")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                color: {primary};
                background: transparent;
                border: 1px solid {primary};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)
        self.clear_btn.clicked.connect(self._on_clear_all)
        bottom_layout.addWidget(self.clear_btn)
        
        # Confirm Button
        self.confirm_btn = QPushButton("确定")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary};
                color: {light_text};
                border: none;
                border-radius: 4px;
                padding: 6px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)
        self.confirm_btn.clicked.connect(self._on_confirm)
        bottom_layout.addWidget(self.confirm_btn)
        
        content_layout.addLayout(bottom_layout)
        layout.addWidget(content_widget)

    def _populate_tags(self):
        # Clear existing
        while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        # Sort: Selected first, then A-Z
        sorted_tags = sorted(self.all_tags, key=lambda x: (0 if x in self.selected_tags else 1, x))
                
        for tag in sorted_tags:
            is_sel = tag in self.selected_tags
            # Use TagWidget from TagManagerDialog for consistency
            widget = TagWidget(tag, is_selected=is_sel)
            widget.toggled.connect(self._on_tag_toggled)
            # We don't connect deleted signal here because this is just a selector, 
            # unless we want to allow deleting tags globally from here too.
            # TagManagerDialog allows it. Let's allow it for consistency if user wants management.
            # But the requirement is "Select tags".
            # "Clear all tags" option requested by user is different (clearing from target images).
            # The delete button on TagWidget deletes from the *list of available tags* usually?
            # In TagManagerDialog, it calls deleted signal which removes from list.
            # Let's keep it but maybe not connect it or implement it if needed.
            # I'll connect it to update the view.
            widget.deleted.connect(self._on_tag_deleted_from_list)
            
            self.flow_layout.addWidget(widget)

    def _add_new_tag(self):
        text = self.input_edit.text().strip()
        if not text:
            return
            
        if text not in self.all_tags:
            self.all_tags.append(text)
            TagManager.instance().add_tag(text)
            
        self.selected_tags.add(text)
        self.input_edit.clear()
        self._populate_tags()

    def _on_tag_toggled(self, tag, is_selected):
        if is_selected:
            self.selected_tags.add(tag)
        else:
            self.selected_tags.discard(tag)

    def _on_tag_deleted_from_list(self, tag):
        if tag in self.all_tags:
            self.all_tags.remove(tag)
            TagManager.instance().delete_tag(tag)
        self.selected_tags.discard(tag)
        self._populate_tags()

    def _on_clear_all(self):
        # "Clear all tags" option.
        # This implies: Select NO tags, and ensure we overwrite with empty.
        self.selected_tags.clear()
        self.append_check.setChecked(False) # Force overwrite
        self._populate_tags()
        # Optionally we could auto-confirm, but maybe user wants to see it cleared.
        
    def _on_confirm(self):
        final_tags = sorted(list(self.selected_tags))
        is_append = self.append_check.isChecked()
        self.tagsSelected.emit(final_tags, is_append)
        self.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() < 50: # Title bar area
                self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None
