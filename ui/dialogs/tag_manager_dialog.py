import qtawesome as qta
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QPushButton, QLabel, QScrollArea, QWidget, QFrame, 
                             QLayout, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect, QPoint
from PyQt6.QtGui import QColor

from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog
from utils.tag_manager import TagManager

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

class TagWidget(QFrame):
    toggled = pyqtSignal(str, bool) # tag_name, is_selected
    deleted = pyqtSignal(str) # tag_name

    def __init__(self, text, is_selected=False, parent=None):
        super().__init__(parent)
        self.text = text
        self.is_selected = is_selected
        
        self.setObjectName("TagWidget")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(4)
        
        # Text
        self.text_label = QLabel(text)
        self.text_label.setStyleSheet("border: none; background: transparent; font-weight: bold;")
        layout.addWidget(self.text_label)
        
        # Delete Button
        self.delete_btn = QPushButton()
        self.delete_btn.setFixedSize(16, 16)
        self.delete_btn.setFlat(True)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(self._on_delete)
        layout.addWidget(self.delete_btn)
        
        self.update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 忽略删除按钮区域的点击 (虽然 delete_btn 会拦截，但 Frame 的点击也要处理)
            if self.delete_btn.geometry().contains(event.pos()):
                return super().mousePressEvent(event)
            
            self.is_selected = not self.is_selected
            self.update_style()
            self.toggled.emit(self.text, self.is_selected)

    def _on_delete(self):
        self.deleted.emit(self.text)

    def update_style(self):
        # 适配主题颜色
        cm = ColorManager.instance()
        bg_color = cm.get("settings.shortcut_table.row.hover_background", "#E0E0E0")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        delete_hover_bg = cm.get("tag.delete.hover_background", "#FF000033")
        selected_bg = cm.get("theme.primary", "#2196F3")
        selected_text = cm.get("theme.text.light", "#FFFFFF")
        
        if self.is_selected:
            self.setStyleSheet(f"""
                QFrame#TagWidget {{
                    background-color: {selected_bg};
                    border: 1px solid {selected_bg};
                    border-radius: 12px;
                }}
            """)
            self.text_label.setStyleSheet(f"color: {selected_text}; font-weight: bold; border: none; background: transparent;")
            self.delete_btn.setIcon(qta.icon('ph.x', color=selected_text))
        else:
            self.setStyleSheet(f"""
                QFrame#TagWidget {{
                    background-color: transparent;
                    border: 1px solid {border_color};
                    border-radius: 12px;
                }}
                QFrame#TagWidget:hover {{
                    background-color: {bg_color};
                }}
            """)
            self.text_label.setStyleSheet(f"color: {text_color}; border: none; background: transparent;")
            self.delete_btn.setIcon(qta.icon('ph.x', color=text_color))
        self.delete_btn.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {delete_hover_bg};
            }}
        """)


class TagManagerDialog(BasePopupDialog):
    tags_updated = pyqtSignal(list, str) # file_paths, new_tags_str

    def __init__(self, db, file_paths, parent=None, table_name: str = "bird_results"):
        self.db = db
        self.file_paths = file_paths
        self.table_name = str(table_name or "bird_results")
        self.title = "标签管理"
        self.drag_pos = None
        super().__init__(parent=parent, title=self.title, size=(500, 400))
        
        # 获取所有标签
        self.all_tags = TagManager.instance().get_all_tags()
        
        # 获取当前选中的标签 (取并集作为初始选中状态)
        self.selected_tags = set()
        self._init_selected_tags()

        # 检查是否有选中但未在全局列表中的标签
        tm = TagManager.instance()
        for tag in self.selected_tags:
            if tag not in self.all_tags:
                self.all_tags.append(tag)
                tm.add_tag(tag) # 保存到 json
        
        # 重新排序
        self.all_tags.sort()

        self._init_ui()
        self._load_tags_ui()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if click is on title bar (approx height 40)
            if event.position().y() < 40:
                self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def _init_selected_tags(self):
        self.selected_tags = set()
        if not self.file_paths:
            return

        # 批量获取文件信息
        results = self.db.get_user_fields_map(self.file_paths, table_name=self.table_name)
        
        for info in results.values():
            tags_str = info.get('tags')
            if tags_str:
                parts = str(tags_str).split('|')
                for p in parts:
                    t = p.strip()
                    if t:
                        self.selected_tags.add(t)

    def _init_ui(self):
        cm = ColorManager.instance()
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        hover_bg = cm.get("settings.shortcut_reset.hover_background", "#2196F31A")
        self.set_bottom_bar_style(self.get_footer_background(), border_color)
        
        # Input Area
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入新标签...")
        self.input_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 6px;
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {control_bg};
                color: {text_color};
            }}
        """)
        self.input_edit.returnPressed.connect(self._add_tag)
        
        self.add_btn = QPushButton("添加")
        self.add_btn.setIcon(qta.icon('ph.plus', color=text_color))
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                padding: 6px 12px;
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)
        self.add_btn.clicked.connect(self._add_tag)
        
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(self.add_btn)
        self.content_layout.addLayout(input_layout)
        
        # Tags Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        self.tags_container = QWidget()
        self.tags_container.setStyleSheet("background: transparent;")
        self.flow_layout = FlowLayout(self.tags_container, margin=0, spacing=8)
        scroll.setWidget(self.tags_container)
        
        self.content_layout.addWidget(scroll)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_dialog_button_style(cancel_btn, "secondary")
        cancel_btn.clicked.connect(self.reject)
        
        ok_btn = QPushButton("确定")
        ok_btn.setFixedSize(80, 32)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self._on_ok)
        self.apply_dialog_button_style(ok_btn, "primary")
        
        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(ok_btn)

    def _load_tags_ui(self):
        # Clear existing
        while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Sort: Selected first, then A-Z
        sorted_tags = sorted(self.all_tags, key=lambda x: (0 if x in self.selected_tags else 1, x))
        
        for tag in sorted_tags:
            self._create_tag_widget(tag)

    def _create_tag_widget(self, tag):
        is_sel = tag in self.selected_tags
        widget = TagWidget(tag, is_selected=is_sel)
        widget.toggled.connect(self._on_tag_toggled)
        widget.deleted.connect(self._on_tag_deleted)
        self.flow_layout.addWidget(widget)

    def _add_tag(self):
        text = self.input_edit.text().strip()
        if not text:
            return
            
        if text not in self.all_tags:
            self.all_tags.append(text)
            TagManager.instance().add_tag(text)
            
        # Add implies select
        self.selected_tags.add(text)
        
        # Refresh UI (simplest way to re-sort)
        self._load_tags_ui()
        self.input_edit.clear()

    def _on_tag_toggled(self, tag, is_selected):
        if is_selected:
            self.selected_tags.add(tag)
        else:
            self.selected_tags.discard(tag)

    def _on_tag_deleted(self, tag):
        if tag in self.all_tags:
            self.all_tags.remove(tag)
            TagManager.instance().delete_tag(tag)
        self.selected_tags.discard(tag)
        self._load_tags_ui()
            # Note: We don't delete from DB immediately here. 
            # We just remove it from the available list.
            # If user Canceels, the deletion is aborted? 
            # "Delete existing tag function" usually implies immediate action or part of the session.
            # Given this is a "Manager", maybe immediate deletion is better?
            # But that would require updating ALL photos in DB immediately.
            # Let's keep it local to the session, and apply on OK. 
            # But wait, if I delete a tag from the UI list, and click OK, 
            # then the tag is removed from the selected photos.
            # But what about OTHER photos not selected?
            # If "Delete" means "Delete from System", I should run a global update.
            # Given the requirement "Delete button next to each tag", I'll implement it as "Remove from this list and these photos".
            # Implementing Global Delete from a Dialog acting on specific photos is risky/ambiguous.
            # I will assume it just removes it from the 'available' list in this session and unchecks it.
            # If the tag is used by other photos, it will reappear next time unless I explicitly delete from DB.
            # Let's stick to "Remove from selection + Remove from view".

    def _on_ok(self):
        # Return the final list of tags
        final_tags = sorted(list(self.selected_tags))
        self.tags_updated.emit(self.file_paths, "|".join(final_tags))
        
        # We handle the actual update in the parent or here?
        # The parent usually handles the logic.
        # But `tags_updated` signal should probably pass the tags.
        self.accept()
        return final_tags
