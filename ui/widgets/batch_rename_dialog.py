import os
import re
from datetime import datetime
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QWidget, QLineEdit, QSpinBox, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox)
from PyQt6.QtCore import Qt
import qtawesome as qta
from ui.widgets.custom_input_dialog import CustomInputDialog
from ui.utils.color_manager import ColorManager
from ui.widgets.base_popup_dialog import BasePopupDialog

class BatchRenameDialog(BasePopupDialog):
    """批量重命名对话框"""
    
    def __init__(self, parent=None, file_list=None):
        super().__init__(parent=parent, title="批量重命名", size=(800, 600))
        self.file_list = file_list or []
        self.title = "批量重命名"
        
        # 默认规则
        self.pattern = "{Species}_{Date}_{Index}"
        self.start_index = 1
        self.index_width = 3
        
        # 预览结果 {original_path: new_name}
        self.preview_map = {}
        
        self.init_ui()
        self.update_preview()
        
    def init_ui(self):
        cm = ColorManager.instance()
        popup_bg = self.get_content_background()
        control_bg = cm.get("settings.shortcut_input.background", "#F2F2F2")
        text_color = cm.get("popup.text.primary", "#333333")
        border_color = cm.get("popup.border.primary", "#D0D0D0")
        header_bg = cm.get("popup.header.background", "#2c3e50")
        header_text_color = cm.get("popup.header.text", "#FFFFFF")
        primary_color = cm.get("theme.primary", "#2196F3")
        hover_bg = cm.get("settings.shortcut_table.row.hover_background", "#EEF3FA")
        table_header_bg = cm.get("settings.shortcut_table.header.background", "#F5F5F5")
        table_header_border = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        scrollbar_bg = cm.get("settings.shortcut_table.header.background", "#F5F5F5")
        scrollbar_handle = cm.get("settings.shortcut_table.header.border", "#D0D0D0")
        scrollbar_handle_hover = cm.get("settings.shortcut_table.row.hover_border", "#D7E3F5")
        disabled_bg = cm.get("settings.shortcut_table.header.border", "#D0D0D0")

        self.set_title_bar_style(header_bg, header_text_color, hover_bg)
        self.set_bottom_bar_style(self.get_footer_background(), border_color)
        
        # 规则输入区
        rule_group = QWidget()
        rule_layout = QVBoxLayout(rule_group)
        rule_layout.setContentsMargins(0, 0, 0, 0)
        
        rule_label = QLabel("命名规则:")
        rule_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {text_color};")
        rule_layout.addWidget(rule_label)
        
        input_row = QHBoxLayout()
        self.rule_edit = QLineEdit(self.pattern)
        self.rule_edit.setPlaceholderText("例如: {Species}_{Date}_{Index}")
        self.rule_edit.setStyleSheet(f"""
            QLineEdit {{
                padding: 8px;
                border: 1px solid {border_color};
                border-radius: 4px;
                font-size: 14px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QLineEdit:focus {{
                border: 1px solid {primary_color};
            }}
        """)
        self.rule_edit.textChanged.connect(self.update_preview)
        input_row.addWidget(self.rule_edit)
        rule_layout.addLayout(input_row)
        
        # 标签按钮区
        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(8)
        
        tags = [
            ("{Species}", "物种"),
            ("{Date}", "日期"),
            ("{Time}", "时间"),
            ("{Index}", "序号"),
            ("{Original}", "原名"),
            ("{Order}", "目"),
            ("{Family}", "科"),
            ("{Genus}", "属"),
            ("{Score}", "评分"),
            ("{Label}", "色标"),
            ("{Position}", "位置"),
        ]
        
        for tag, name in tags:
            btn = QPushButton(f"{name}")
            btn.setToolTip(f"插入 {tag}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {control_bg};
                    border: 1px solid {border_color};
                    border-radius: 3px;
                    padding: 4px 8px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: {hover_bg};
                    border: 1px solid {table_header_border};
                }}
            """)
            btn.clicked.connect(lambda checked, t=tag: self.insert_tag(t))
            tags_layout.addWidget(btn)
        
        tags_layout.addStretch()
        rule_layout.addLayout(tags_layout)
        
        # 序号设置
        index_layout = QHBoxLayout()
        index_layout.addWidget(QLabel("起始序号:"))
        self.start_index_spin = QSpinBox()
        self.start_index_spin.setRange(0, 999999)
        self.start_index_spin.setValue(self.start_index)
        self.start_index_spin.valueChanged.connect(self.update_preview)
        index_layout.addWidget(self.start_index_spin)
        
        index_layout.addSpacing(20)
        
        index_layout.addWidget(QLabel("序号位数:"))
        self.index_width_spin = QSpinBox()
        self.index_width_spin.setRange(1, 10)
        self.index_width_spin.setValue(self.index_width)
        self.index_width_spin.valueChanged.connect(self.update_preview)
        index_layout.addWidget(self.index_width_spin)
        
        index_layout.addStretch()
        rule_layout.addLayout(index_layout)
        
        self.content_layout.addWidget(rule_group)
        
        # 预览列表
        preview_label = QLabel("预览:")
        preview_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {text_color};")
        self.content_layout.addWidget(preview_label)
        
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(3)
        self.preview_table.setHorizontalHeaderLabels(["原文件名", "新文件名", "状态"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.setStyleSheet(f"""
            QTableWidget {{
                border: 1px solid {border_color};
                border-radius: 4px;
                background-color: {control_bg};
                color: {text_color};
            }}
            QHeaderView::section {{
                background-color: {table_header_bg};
                padding: 4px;
                border: none;
                border-bottom: 1px solid {table_header_border};
                border-right: 1px solid {table_header_border};
            }}
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 14px;
                border: none;
                border-radius: 7px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {scrollbar_handle};
                min-height: 30px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {scrollbar_handle_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background-color: {scrollbar_bg};
                height: 14px;
                border: none;
                border-radius: 7px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {scrollbar_handle};
                min-width: 30px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {scrollbar_handle_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """)
        self.content_layout.addWidget(self.preview_table)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        self.apply_dialog_button_style(cancel_btn, "secondary")
        cancel_btn.clicked.connect(self.reject)

        self.confirm_btn = QPushButton("开始重命名")
        self.confirm_btn.setFixedSize(100, 32)
        self.apply_dialog_button_style(self.confirm_btn, "primary")
        self.confirm_btn.clicked.connect(self.accept)

        self.bottom_layout.addWidget(cancel_btn)
        self.bottom_layout.addWidget(self.confirm_btn)

    def insert_tag(self, tag):
        self.rule_edit.insert(tag)
        self.rule_edit.setFocus()

    def update_preview(self):
        pattern = self.rule_edit.text()
        start_index = self.start_index_spin.value()
        index_width = self.index_width_spin.value()
        
        self.preview_table.setRowCount(0)
        self.preview_map = {}
        
        current_index = start_index
        generated_names = set()
        
        rows_data = []
        
        for file_info in self.file_list:
            old_path = file_info.get('path', '')
            if not old_path: continue
            
            old_name = os.path.basename(old_path)
            old_name_no_ext, ext = os.path.splitext(old_name)
            
            # 解析元数据
            species = file_info.get('species') or file_info.get('species_cls') or file_info.get('object') or 'Unknown'
            genus = file_info.get('genus') or file_info.get('genus_cls') or ''
            family = file_info.get('family') or file_info.get('family_cls') or ''
            order = file_info.get('order') or file_info.get('order_cls') or ''
            score = file_info.get('score')
            if score is None: score = ''
            label_val = file_info.get('label') or ''
            position = file_info.get('position') or ''
            
            shot_time = file_info.get('shot_time') or file_info.get('create_time') or ''
            date_str = ""
            time_str = ""
            if shot_time:
                # 尝试解析时间，常见格式 "2023:10:01 12:00:00" 或 "2023-10-01 12:00:00"
                try:
                    # 简单清理和解析
                    clean_time = shot_time.replace(':', '').replace('-', '').replace(' ', '')
                    if len(clean_time) >= 8:
                        date_str = clean_time[:8] # YYYYMMDD
                    if len(clean_time) >= 14:
                        time_str = clean_time[8:14] # HHMMSS
                except:
                    pass
            
            # 格式化文件名
            new_name_base = pattern
            new_name_base = new_name_base.replace("{Species}", str(species))
            new_name_base = new_name_base.replace("{Genus}", str(genus))
            new_name_base = new_name_base.replace("{Family}", str(family))
            new_name_base = new_name_base.replace("{Order}", str(order))
            new_name_base = new_name_base.replace("{Score}", str(score))
            new_name_base = new_name_base.replace("{Label}", str(label_val))
            new_name_base = new_name_base.replace("{Position}", str(position))
            new_name_base = new_name_base.replace("{Date}", date_str)
            new_name_base = new_name_base.replace("{Time}", time_str)
            new_name_base = new_name_base.replace("{Original}", old_name_no_ext)
            
            # 处理序号和冲突
            final_name_base = new_name_base
            
            # 如果模式包含 {Index}
            if "{Index}" in new_name_base:
                final_name_base = final_name_base.replace("{Index}", f"{current_index:0{index_width}d}")
                current_index += 1
            
            # 检查冲突（预览列表内的冲突）
            # 用户要求：如果有冲突的文件名就把序号往后挪
            # 如果模式本身没有Index，但出现重复，我们也需要处理
            
            temp_name = f"{final_name_base}{ext}"
            
            # 简单的冲突解决策略：如果重复，追加序号直到不重复
            conflict_count = 0
            base_for_conflict = final_name_base
            while temp_name in generated_names:
                conflict_count += 1
                # 如果是使用了 {Index} 的模式冲突了（可能是 Index 被手动指定了静态值？或者重置了），通常 Index 递增就不会冲突
                # 但如果是没用 {Index} 的模式（如只用 {Species}），则必须追加序号
                if "{Index}" in pattern:
                     # 如果原模式有Index还冲突，可能是外部文件冲突？这里只检查生成的集合
                     # 如果是集合内冲突，说明不同文件生成了相同的名字（比如物种、时间都一样，且Index没变或没用好）
                     # 按照用户需求"把序号往后挪"，这里应该是全局 Index 继续递增？
                     # 但我们是在循环里递增 Index 的。
                     # 如果是 {Species} 这种没 Index 的，只能追加 (1)
                     pass
                
                # 统一策略：追加 _N
                temp_name = f"{base_for_conflict}_{conflict_count}{ext}"

            generated_names.add(temp_name)
            
            # 检查文件系统冲突 (不在当前目录下检查，因为可能只是改名)
            # 但如果新名字和当前目录下的其他文件（未被选中的）冲突，也应该警告
            status = "OK"
            dir_path = os.path.dirname(old_path)
            full_new_path = os.path.join(dir_path, temp_name)
            
            if os.path.exists(full_new_path) and full_new_path.lower() != old_path.lower():
                status = "文件已存在 (将自动跳过或覆盖)" # 实际逻辑应该更严谨，这里先标记
                # 为了安全，这里应该再次重命名以避免覆盖
                # 但用户逻辑是“冲突就序号往后挪”，所以我们应该继续找可用的名字
                
                # 在文件系统层面解决冲突
                fs_conflict_count = 0
                fs_base = os.path.splitext(temp_name)[0]
                while os.path.exists(os.path.join(dir_path, temp_name)) and os.path.join(dir_path, temp_name).lower() != old_path.lower():
                     fs_conflict_count += 1
                     temp_name = f"{fs_base}_{fs_conflict_count}{ext}"
                
                status = "自动解决冲突"

            self.preview_map[old_path] = temp_name
            rows_data.append((old_name, temp_name, status))

        # 填充表格
        self.preview_table.setRowCount(len(rows_data))
        for r, (old, new, status) in enumerate(rows_data):
            self.preview_table.setItem(r, 0, QTableWidgetItem(old))
            self.preview_table.setItem(r, 1, QTableWidgetItem(new))
            item_status = QTableWidgetItem(status)
            if "已存在" in status:
                item_status.setForeground(Qt.GlobalColor.red)
            elif "自动解决" in status:
                item_status.setForeground(Qt.GlobalColor.blue)
            else:
                item_status.setForeground(Qt.GlobalColor.green)
            self.preview_table.setItem(r, 2, item_status)

    def get_results(self):
        """返回重命名映射表 {old_path: new_name}"""
        return self.preview_map
