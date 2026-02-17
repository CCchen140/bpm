from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, 
                             QLineEdit, QCheckBox, QPushButton, QButtonGroup, QRadioButton, QDateTimeEdit)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QDateTime
from ui.utils.icon_loader import qta
from utils.tag_manager import TagManager
from ui.widgets.rating_filter_button import RatingFilterButton
from ui.widgets.rating_filter_widget import StarRatingWidget
from ui.utils.color_manager import ColorManager

class FilterRow(QWidget):
    # 信号：行删除请求、行添加请求
    remove_requested = pyqtSignal(QWidget)
    add_requested = pyqtSignal()
    
    def __init__(self, parent=None, is_first=True):
        super().__init__(parent)
        self.is_first = is_first
        self.logic_state = 0 # 0: AND, 1: OR, 2: NOT
        self.init_ui()
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setMinimumHeight(36)  # 防止被压缩
        
        # 1. 逻辑按钮 (第一行隐藏，但占位或者直接不显示)
        self.logic_btn = QPushButton()
        self.logic_btn.setFixedSize(28, 28)
        self.logic_btn.setStyleSheet("border: none; background: transparent;")
        self.logic_btn.clicked.connect(self.toggle_logic)
        self.update_logic_icon()
        
        if self.is_first:
            self.logic_btn.hide()
            # 第一行左边加个空白占位，或者直接不加？
            # 根据需求，"最左边是一个下拉框"，所以第一行不需要逻辑按钮占位
            pass
        else:
            layout.addWidget(self.logic_btn)
            
        # 2. 字段选择下拉框
        self.field_combo = QComboBox()
        self.field_combo.addItems(["文件名", "标签", "路径", "评分", "分数", "鸟的位置", "色标", "目", "科", "属", "种", "备注", "拍摄时间", "拍摄地址"])
        self.field_combo.setFixedWidth(80)
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        layout.addWidget(self.field_combo)
        
        # 2.5 评分比较操作符按钮 (默认隐藏)
        self.rating_op_btn = RatingFilterButton()
        self.rating_op_btn.hide()
        layout.addWidget(self.rating_op_btn)
        
        # 2.6 评分选择控件 (默认隐藏)
        self.star_rating = StarRatingWidget(size=24, font_size=16)
        self.star_rating.hide()
        layout.addWidget(self.star_rating)
        
        # 3. 值输入框
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("搜索内容...")
        layout.addWidget(self.value_input)

        self.datetime_start = QDateTimeEdit()
        self.datetime_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.datetime_start.setCalendarPopup(True)
        self.datetime_start.setDateTime(QDateTime.currentDateTime().addDays(-7))
        self.datetime_start.hide()
        layout.addWidget(self.datetime_start)

        self.datetime_end = QDateTimeEdit()
        self.datetime_end.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.datetime_end.setCalendarPopup(True)
        self.datetime_end.setDateTime(QDateTime.currentDateTime())
        self.datetime_end.hide()
        layout.addWidget(self.datetime_end)
        
        # 3.5 值选择框 (默认隐藏)
        self.value_combo = QComboBox()
        self.value_combo.hide()
        layout.addWidget(self.value_combo)
        
        # 4. 模糊搜索复选框
        self.fuzzy_check = QCheckBox("模糊")
        self.fuzzy_check.stateChanged.connect(self._update_fuzzy_icon)
        self._update_fuzzy_icon() # 初始化图标
        # 默认隐藏，只有文字搜索字段时显示
        self.fuzzy_check.hide() 
        layout.addWidget(self.fuzzy_check)
        
        # 触发一次初始化逻辑，设置初始状态
        self.on_field_changed(self.field_combo.currentText())

        # 5. 操作按钮 (+ 或 -)
        self.action_btn = QPushButton()
        self.action_btn.setFixedSize(28, 28)
        self.action_btn.setStyleSheet("border: none; background: transparent;")
        
        if self.is_first:
            self.action_btn.setIcon(qta.icon('mdi6.plus', color='#2196f3'))
            self.action_btn.setToolTip("添加条件")
            self.action_btn.clicked.connect(self.add_requested.emit)
        else:
            self.action_btn.setIcon(qta.icon('mdi6.minus', color='#e74c3c'))
            self.action_btn.setToolTip("删除条件")
            self.action_btn.clicked.connect(lambda: self.remove_requested.emit(self))
            
        layout.addWidget(self.action_btn)
        
    def on_field_changed(self, text):
        """当字段改变时触发"""
        is_numeric = (text in ["评分", "分数"])
        self.rating_op_btn.setVisible(is_numeric)
        
        # 先隐藏所有值输入控件
        self.value_input.hide()
        self.datetime_start.hide()
        self.datetime_end.hide()
        self.value_combo.hide()
        self.star_rating.hide()
        self.fuzzy_check.setVisible(False)
        
        # 状态字段特殊处理
        if text == "状态":
            self.value_combo.clear()
            # 大小写可能需要根据数据库实际值调整，这里先用 Title Case
            self.value_combo.addItems(["Sharp", "Normal", "Blurry", "Minimal", "ExpFrame", "NoBird"])
            self.value_combo.show()
        elif text == "鸟的位置":
            self.value_combo.clear()
            # 上下左右，左上左下右上右下，中间
            self.value_combo.addItems([
                "Center", "Top", "Bottom", "Left", "Right", 
                "TopLeft", "TopRight", "BottomLeft", "BottomRight"
            ])
            self.value_combo.show()
        elif text == "色标":
            self.value_combo.clear()
            # 使用 (显示文本, 实际值) 的方式添加
            labels = [
                ("红色", "Red"), ("橙色", "Orange"), ("黄色", "Yellow"), 
                ("绿色", "Green"), ("青色", "Cyan"), ("蓝色", "Blue"), 
                ("紫色", "Purple"), ("粉色", "Pink"), ("白色", "White"), 
                ("灰色", "Gray"), ("黑色", "Black"), ("无色标", "None")
            ]
            for cn, en in labels:
                self.value_combo.addItem(cn, en)
            self.value_combo.show()
        elif text == "评分":
            self.star_rating.show()
        elif text == "标签":
            self.value_combo.clear()
            tags = TagManager.instance().get_all_tags()
            if tags:
                self.value_combo.addItems(tags)
            self.value_combo.show()
        elif text == "拍摄时间":
            self.datetime_start.show()
            self.datetime_end.show()
        else:
            # 其他情况显示文本输入框
            self.value_input.show()
            # 只有文本输入且不是数值类型时才显示模糊搜索
            self.fuzzy_check.setVisible(not is_numeric)
        
        if text == "分数":
            self.value_input.setPlaceholderText("得分")
        elif text not in ["评分", "状态", "鸟的位置"]:
            self.value_input.setPlaceholderText("搜索内容...")
        
    def toggle_logic(self):
        self.logic_state = (self.logic_state + 1) % 3
        self.update_logic_icon()
        
    def update_logic_icon(self):
        cm = ColorManager.instance()
        and_color = cm.get("theme.primary")
        or_color = cm.get("theme.text.dark")
        not_color = cm.get("border.subject_rect")
        if self.logic_state == 0: # AND
            self.logic_btn.setIcon(qta.icon('mdi6.ampersand', color=and_color))
            self.logic_btn.setToolTip("逻辑: 与 (AND)")
        elif self.logic_state == 1: # OR
            self.logic_btn.setIcon(qta.icon('mdi6.pipe', color=or_color))
            self.logic_btn.setToolTip("逻辑: 或 (OR)")
        else: # NOT
            self.logic_btn.setIcon(qta.icon('mdi6.exclamation-thick', color=not_color))
            self.logic_btn.setToolTip("逻辑: 非 (NOT)")

    def _update_fuzzy_icon(self):
        """更新模糊搜索复选框的图标"""
        cm = ColorManager.instance()
        checked_color = cm.get("theme.primary")
        unchecked_color = cm.get("popup.border.primary")
        if self.fuzzy_check.isChecked():
            self.fuzzy_check.setIcon(qta.icon('mdi6.checkbox-marked', color=checked_color))
        else:
            self.fuzzy_check.setIcon(qta.icon('mdi6.checkbox-blank-outline', color=unchecked_color))

    def _combo_style(self):
        cm = ColorManager.instance()
        combo_bg = cm.get("theme.background.light")
        combo_text = cm.get("theme.text.dark")
        combo_border = cm.get("popup.border.primary")
        combo_hover_border = cm.get("theme.primary")
        combo_primary = cm.get("theme.primary")
        selection_text = cm.get("theme.text.light")
        scrollbar_bg = cm.get("theme.background.dark")
        scrollbar_handle = cm.get("popup.border.primary")
        scrollbar_handle_hover = cm.get("theme.primary")
        return f"""
            QComboBox {{
                border: 1px solid {combo_border};
                border-radius: 3px;
                padding: 2px 4px;
                background-color: {combo_bg};
                color: {combo_text};
            }}
            QComboBox:hover {{
                border: 1px solid {combo_hover_border};
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                border: 1px solid {combo_border};
                background-color: {combo_bg};
                selection-background-color: {combo_primary};
                selection-color: {selection_text};
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {scrollbar_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {combo_primary};
                color: {selection_text};
            }}
            QComboBox QAbstractItemView QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 10px;
                border: none;
                border-radius: 5px;
                margin: 0px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical {{
                background-color: {scrollbar_handle};
                min-height: 30px;
                border-radius: 5px;
            }}
            QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {{
                background-color: {scrollbar_handle_hover};
            }}
            QComboBox QAbstractItemView QScrollBar::add-line:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QComboBox QAbstractItemView QScrollBar::add-page:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """

    def _line_edit_style(self):
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary")
        primary = cm.get("theme.primary")
        bg = cm.get("theme.background.light")
        text = cm.get("theme.text.dark")
        return f"""
            QLineEdit {{
                border: 1px solid {border};
                border-radius: 3px;
                padding: 3px;
                background-color: {bg};
                color: {text};
            }}
            QLineEdit:focus {{ border: 1px solid {primary}; }}
        """

    def _datetime_style(self):
        cm = ColorManager.instance()
        border = cm.get("popup.border.primary")
        hover_border = cm.get("theme.primary")
        bg = cm.get("theme.background.light")
        text = cm.get("theme.text.dark")
        selection_bg = cm.get("theme.primary")
        drop_bg = cm.get("theme.background.dark")
        return f"""
            QDateTimeEdit {{
                border: 1px solid {border};
                border-radius: 3px;
                padding: 3px 28px 3px 8px;
                background: {bg};
                color: {text};
                selection-background-color: {selection_bg};
            }}
            QDateTimeEdit:hover {{ border: 1px solid {hover_border}; }}
            QDateTimeEdit:focus {{ border: 1px solid {hover_border}; }}
            QDateTimeEdit::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 22px;
                border-left: 1px solid {border};
                background: {drop_bg};
                border-top-right-radius: 3px;
                border-bottom-right-radius: 3px;
            }}
            QDateTimeEdit::drop-down:hover {{ background: {drop_bg}; }}
        """

    def _calendar_style(self):
        cm = ColorManager.instance()
        bg = cm.get("theme.background.light")
        border = cm.get("popup.border.primary")
        text = cm.get("theme.text.dark")
        hover_bg = cm.get("theme.background.dark")
        selection_bg = cm.get("theme.primary")
        selection_text = cm.get("theme.text.light")
        gridline = cm.get("popup.border.primary")
        return f"""
            QCalendarWidget {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 4px;
            }}
            QCalendarWidget QWidget {{ color: {text}; }}
            QCalendarWidget QToolButton {{
                color: {text};
                background: transparent;
                padding: 4px 6px;
                border-radius: 3px;
                margin: 2px;
            }}
            QCalendarWidget QToolButton:hover {{ background: {hover_bg}; }}
            QCalendarWidget QToolButton:pressed {{ background: {hover_bg}; }}
            QCalendarWidget QToolButton#qt_calendar_monthbutton {{ min-width: 90px; }}
            QCalendarWidget QToolButton#qt_calendar_yearbutton {{ min-width: 60px; }}
            QCalendarWidget QToolButton#qt_calendar_prevmonth,
            QCalendarWidget QToolButton#qt_calendar_nextmonth {{ min-width: 24px; }}
            QCalendarWidget QSpinBox {{
                color: {text};
                background: {bg};
                border: 1px solid {border};
                border-radius: 3px;
                padding: 2px 6px;
                margin: 2px;
            }}
            QCalendarWidget QSpinBox::up-button,
            QCalendarWidget QSpinBox::down-button {{
                width: 0px;
                height: 0px;
            }}
            QCalendarWidget QAbstractItemView {{
                color: {text};
                background: {bg};
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
                outline: none;
                gridline-color: {gridline};
            }}
            QCalendarWidget QAbstractItemView::item {{
                padding: 6px;
                border-radius: 3px;
            }}
            QCalendarWidget QAbstractItemView::item:hover {{ background: {hover_bg}; }}
            QCalendarWidget QAbstractItemView::item:selected {{ background: {selection_bg}; }}
            QCalendarWidget QComboBox {{
                border: 1px solid {border};
                border-radius: 3px;
                padding: 2px 24px 2px 6px;
                background: {bg};
                color: {text};
            }}
            QCalendarWidget QComboBox::drop-down {{
                width: 20px;
                border-left: 1px solid {border};
                background: {hover_bg};
            }}
            QCalendarWidget QComboBox QAbstractItemView {{
                border: 1px solid {border};
                background-color: {bg};
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
                outline: none;
            }}
        """

    def _apply_theme_styles(self):
        self.field_combo.setStyleSheet(self._combo_style())
        self.value_combo.setStyleSheet(self._combo_style())
        self.value_input.setStyleSheet(self._line_edit_style())
        dt_style = self._datetime_style()
        cal_style = self._calendar_style()
        self.datetime_start.setStyleSheet(dt_style)
        self.datetime_end.setStyleSheet(dt_style)
        try:
            cw = self.datetime_start.calendarWidget()
            if cw:
                cw.setStyleSheet(cal_style)
        except Exception:
            pass
        try:
            cw = self.datetime_end.calendarWidget()
            if cw:
                cw.setStyleSheet(cal_style)
        except Exception:
            pass
        self._update_fuzzy_icon()
        self.update_logic_icon()
        cm = ColorManager.instance()
        add_color = cm.get("theme.primary")
        remove_color = cm.get("border.subject_rect")
        if self.is_first:
            self.action_btn.setIcon(qta.icon('mdi6.plus', color=add_color))
        else:
            self.action_btn.setIcon(qta.icon('mdi6.minus', color=remove_color))

    def get_data(self):
        # 获取值
        field = self.field_combo.currentText()
        if field in ["状态", "鸟的位置", "色标", "标签"]:
            data_val = self.value_combo.currentData()
            value = str(data_val) if data_val is not None else self.value_combo.currentText()
        elif field == "评分":
            value = str(self.star_rating.get_rating())
        elif field == "拍摄时间":
            start = self.datetime_start.dateTime().toString("yyyy-MM-dd HH:mm:ss")
            end = self.datetime_end.dateTime().toString("yyyy-MM-dd HH:mm:ss")
            value = f"{start}||{end}"
        else:
            value = self.value_input.text().strip()
            
        return {
            'logic': ['AND', 'OR', 'NOT'][self.logic_state] if not self.is_first else 'AND',
            'field': field,
            'operator': self.rating_op_btn.get_mode() if field in ["评分", "分数"] else ("between" if field == "拍摄时间" else ""),
            'value': value,
            'fuzzy': self.fuzzy_check.isChecked()
        }

    def set_data(self, data):
        if not data: return
        logic_map = {'AND': 0, 'OR': 1, 'NOT': 2}
        self.logic_state = logic_map.get(data.get('logic', 'AND'), 0)
        self.update_logic_icon()
        
        field = data.get('field', '文件名')
        if self.field_combo.findText(field) == -1:
            field = '文件名'
            data = {**data, 'field': field, 'value': ''}
        self.field_combo.setCurrentText(field)
        
        # 恢复操作符
        if data.get('field') in ["评分", "分数"]:
            operator = data.get('operator', '=')
            # RatingFilterButton 没有直接 set_mode 方法，需要循环切换或者添加方法
            # 这里简单循环直到匹配
            target_mode = operator
            for _ in range(3):
                if self.rating_op_btn.get_mode() == target_mode:
                    break
                self.rating_op_btn.toggle_mode()
                
        if data.get('field') in ["色标", "鸟的位置", "标签"]:
            self.value_combo.setCurrentText(data.get('value', ''))
        elif data.get('field') == "评分":
            try:
                rating = int(data.get('value', 0))
                self.star_rating.set_rating(rating)
            except ValueError:
                self.star_rating.set_rating(0)
        elif data.get('field') == "拍摄时间":
            try:
                raw = str(data.get('value', '') or '')
                start_s = ""
                end_s = ""
                if "||" in raw:
                    parts = raw.split("||", 1)
                    start_s = parts[0].strip()
                    end_s = parts[1].strip()
                elif "," in raw:
                    parts = raw.split(",", 1)
                    start_s = parts[0].strip()
                    end_s = parts[1].strip()
                else:
                    start_s = raw.strip()

                if start_s:
                    dt = QDateTime.fromString(start_s, "yyyy-MM-dd HH:mm:ss")
                    if dt and dt.isValid():
                        self.datetime_start.setDateTime(dt)
                if end_s:
                    dt = QDateTime.fromString(end_s, "yyyy-MM-dd HH:mm:ss")
                    if dt and dt.isValid():
                        self.datetime_end.setDateTime(dt)
            except Exception:
                pass
        else:
            self.value_input.setText(data.get('value', ''))
            
        self.fuzzy_check.setChecked(data.get('fuzzy', False))
        self._update_fuzzy_icon()


class AdvancedFilterPanel(QWidget):
    search_requested = pyqtSignal(list) # 发送过滤条件列表
    save_requested = pyqtSignal()
    load_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.init_ui()
        ColorManager.instance().register_listener(self._apply_theme_styles)
        self._apply_theme_styles()
        
    def init_ui(self):
        # 设置属性以确保能够接收鼠标事件并绘制背景
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setObjectName("advancedFilterPanel")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(8)
        
        # 白色背景，黑色细线边框 (1px solid black)
        # RadioButton 样式定制：
        # - 移除默认 Indicator，用图标代替
        # - 文字颜色为深色
        self.setStyleSheet("")
        
        # 1. 过滤条件行容器
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(4)
        self.main_layout.addWidget(self.rows_container)
        
        # 添加初始行
        self.add_row(is_first=True)
        
        # 2. 底部按钮区
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 4, 20, 0) # 右侧留白增加到 20
        
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self.save_requested.emit)
        
        self.load_btn = QPushButton("加载")
        self.load_btn.clicked.connect(self.load_requested.emit)
        
        # 搜索范围选择 (两个独立复选框)
        self.search_all_check = QCheckBox("全部文件")
        self.search_all_check.setChecked(False) # 默认未选中
        self.search_all_check.toggled.connect(self._update_check_icons)
        self.search_all_check.setMinimumWidth(120) # 增加最小宽度防止截断
        
        self.search_fav_check = QCheckBox("收藏文件")
        self.search_fav_check.setChecked(False) # 默认未选中
        self.search_fav_check.toggled.connect(self._update_check_icons)
        self.search_fav_check.setMinimumWidth(120) # 增加最小宽度防止截断
        
        # 初始化图标
        self._update_check_icons()
        
        bottom_layout.addWidget(self.save_btn)
        bottom_layout.addWidget(self.load_btn)
        bottom_layout.addSpacing(10)
        bottom_layout.addWidget(self.search_all_check)
        bottom_layout.addWidget(self.search_fav_check)
        
        bottom_layout.addStretch()
        
        # 重置/清除按钮
        self.clear_btn = QPushButton("重置")
        self.clear_btn.setToolTip("恢复到初始状态")
        self.clear_btn.clicked.connect(self.reset_to_default)
        bottom_layout.addWidget(self.clear_btn)
        
        bottom_layout.addSpacing(10)
        
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.on_search_clicked)
        
        bottom_layout.addWidget(self.search_btn)
        
        self.main_layout.addLayout(bottom_layout)

    def _update_check_icons(self):
        """更新复选框的图标以模拟自定义 Indicator"""
        # 使用 qtawesome 图标模拟选中/未选中状态
        cm = ColorManager.instance()
        checked_icon = qta.icon('mdi6.checkbox-marked', color=cm.get("theme.text.dark"))
        unchecked_icon = qta.icon('mdi6.checkbox-blank-outline', color=cm.get("popup.border.primary"))
        
        for btn in [self.search_all_check, self.search_fav_check]:
            if btn.isChecked():
                btn.setIcon(checked_icon)
            else:
                btn.setIcon(unchecked_icon)

    def _apply_theme_styles(self):
        cm = ColorManager.instance()
        panel_bg = cm.get("theme.background.primary")
        border = cm.get("popup.border.primary")
        text_dark = cm.get("theme.text.dark")
        text_light = cm.get("theme.text.light")
        light_bg = cm.get("theme.background.light")
        dark_bg = cm.get("theme.background.dark")
        primary = cm.get("theme.primary")
        self.setStyleSheet(f"""
            #advancedFilterPanel {{
                background-color: {panel_bg};
                border: 1px solid {border};
                border-radius: 4px;
            }}
            QRadioButton {{
                background-color: transparent;
                color: {text_dark};
                spacing: 4px;
            }}
            QRadioButton::indicator {{
                width: 0px; 
                height: 0px;
                border: none;
                background: transparent;
            }}
            QCheckBox {{
                background-color: transparent;
                color: {text_dark};
                spacing: 4px;
            }}
            QCheckBox::indicator {{
                width: 0px; 
                height: 0px;
                border: none;
                background: transparent;
            }}
        """)
        self.save_btn.setIcon(qta.icon('mdi6.content-save', color=text_dark))
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {light_bg};
                color: {text_dark};
                border: 1px solid {border};
                border-radius: 3px;
                padding: 4px 12px;
                min-width: 50px;
            }}
            QPushButton:hover {{ background-color: {dark_bg}; }}
            QPushButton:pressed {{ background-color: {dark_bg}; }}
        """)
        self.load_btn.setIcon(qta.icon('mdi6.folder-open', color=text_dark))
        self.load_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {light_bg};
                color: {text_dark};
                border: 1px solid {border};
                border-radius: 3px;
                padding: 4px 12px;
                min-width: 50px;
            }}
            QPushButton:hover {{ background-color: {dark_bg}; }}
            QPushButton:pressed {{ background-color: {dark_bg}; }}
        """)
        self.clear_btn.setIcon(qta.icon('mdi6.refresh', color=text_dark))
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {light_bg};
                color: {text_dark};
                border: 1px solid {border};
                border-radius: 3px;
                padding: 4px 12px;
                min-width: 50px;
            }}
            QPushButton:hover {{ background-color: {dark_bg}; }}
            QPushButton:pressed {{ background-color: {dark_bg}; }}
        """)
        self.search_btn.setIcon(qta.icon('mdi6.magnify', color=text_light))
        self.search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary};
                color: {text_light};
                border: none;
                border-radius: 3px;
                padding: 4px 16px;
                min-width: 60px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {dark_bg}; }}
            QPushButton:pressed {{ background-color: {dark_bg}; }}
        """)
        self._update_check_icons()
        for row in self.rows:
            row._apply_theme_styles()
        
    def add_row(self, is_first=False):
        row = FilterRow(self, is_first)
        row.add_requested.connect(lambda: self.add_row(False))
        row.remove_requested.connect(self.remove_row)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        
        # 延迟调整自身大小以适应新内容，确保布局已更新
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self.adjustSize)
        
    def remove_row(self, row):
        if row in self.rows:
            self.rows.remove(row)
            self.rows_layout.removeWidget(row)
            row.deleteLater()
            
            # 延迟调整大小，等待布局更新
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(10, self.adjustSize)
            
    def reset_to_default(self):
        # 移除除第一个之外的所有行
        while len(self.rows) > 1:
            row = self.rows[-1]
            self.remove_row(row)
        
        # 重置第一行
        if self.rows:
            first_row = self.rows[0]
            first_row.field_combo.setCurrentText("文件名")
            first_row.value_input.clear()
            first_row.value_combo.clear()
            first_row.logic_state = 0 # AND
            first_row.update_logic_icon()
            
        # 重置搜索范围
        self.search_all_check.setChecked(False)
        self.search_fav_check.setChecked(False)
        
        try:
            self.on_search_clicked()
        except Exception:
            pass

    def has_conditions(self):
        """检查是否有有效过滤条件"""
        # 1. 检查范围条件
        if self.search_all_check.isChecked() or self.search_fav_check.isChecked():
            return True
            
        # 2. 检查是否有多个条件行
        if len(self.rows) > 1:
            return True
            
        # 3. 检查第一行是否有值
        if self.rows:
            data = self.rows[0].get_data()
            if data.get('value'):
                return True
                
        return False

    def on_search_clicked(self):
        conditions = []
        for row in self.rows:
            data = row.get_data()
            if data['value']: # 只有当有输入值时才加入条件
                conditions.append(data)
        
        # 添加搜索范围条件 (两个独立参数)
        conditions.append({
            'field': '__scope_all__',
            'value': self.search_all_check.isChecked(),
            'logic': 'AND', 
            'fuzzy': False
        })
        conditions.append({
            'field': '__scope_fav__',
            'value': self.search_fav_check.isChecked(),
            'logic': 'AND', 
            'fuzzy': False
        })
        
        self.search_requested.emit(conditions)
        
    def get_all_conditions(self):
        conditions = [row.get_data() for row in self.rows]
        conditions.append({
            'field': '__scope_all__',
            'value': self.search_all_check.isChecked()
        })
        conditions.append({
            'field': '__scope_fav__',
            'value': self.search_fav_check.isChecked()
        })
        return conditions
        
    def set_conditions(self, conditions):
        if not conditions:
            return
            
        # 复制一份以免修改原列表
        conditions = list(conditions)
            
        # 提取并设置搜索范围状态
        scope_all_cond = next((c for c in conditions if c.get('field') == '__scope_all__'), None)
        if scope_all_cond:
            self.search_all_check.setChecked(scope_all_cond.get('value', False))
            conditions.remove(scope_all_cond)
        else:
            self.search_all_check.setChecked(False)
            
        scope_fav_cond = next((c for c in conditions if c.get('field') == '__scope_fav__'), None)
        if scope_fav_cond:
            self.search_fav_check.setChecked(scope_fav_cond.get('value', False))
            conditions.remove(scope_fav_cond)
        else:
            self.search_fav_check.setChecked(False)

        # 清空现有非首行
        while len(self.rows) > 1:
            self.remove_row(self.rows[-1])
        # 重置首行
        if self.rows:
            self.rows[0].value_input.clear()
            self.rows[0].fuzzy_check.setChecked(False)
            
        if not conditions:
            return
            
        # 设置首行
        if len(conditions) > 0:
            self.rows[0].set_data(conditions[0])
            
        # 添加后续行
        for i in range(1, len(conditions)):
            self.add_row(False)
            self.rows[i].set_data(conditions[i])
            
        # 强制更新布局
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self.adjustSize)

    def mousePressEvent(self, event):
        """Consume mouse press events to prevent propagation to parent"""
        # 显式接受事件，防止穿透到下层的 ImageLibraryPage/ZoomableScrollArea 触发框选
        event.accept()
