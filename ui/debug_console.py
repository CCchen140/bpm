from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QPushButton, QHBoxLayout, QHeaderView, QMessageBox, QComboBox)
from PyQt6.QtCore import Qt, QByteArray
from utils.setting.settings_manager import SettingsManager
from ui.utils.notification_manager import NotificationManager

class DebugConsole(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("调试控制台 - 设置编辑器")
        self.resize(700, 500)
        self.settings_manager = SettingsManager()
        self.deleted_keys = set()
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Key", "Type", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 80)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self.add_row)
        btn_layout.addWidget(add_btn)
        
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self.delete_row)
        btn_layout.addWidget(del_btn)
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_settings)
        btn_layout.addWidget(refresh_btn)
        
        save_btn = QPushButton("保存修改")
        save_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(save_btn)
        
        # 测试按钮区域
        test_layout = QHBoxLayout()
        test_warn_btn = QPushButton("测试警告")
        test_warn_btn.setStyleSheet("background-color: #ff9800; color: white; border: none; padding: 5px;")
        test_warn_btn.clicked.connect(lambda: NotificationManager.instance().show_warning("测试警告", "这是一个测试警告窗口！\n内容内容内容..."))
        test_layout.addWidget(test_warn_btn)
        
        test_err_btn = QPushButton("测试错误")
        test_err_btn.setStyleSheet("background-color: #f44336; color: white; border: none; padding: 5px;")
        test_err_btn.clicked.connect(lambda: NotificationManager.instance().show_error("测试错误", "这是一个测试错误窗口！\n发生了严重错误！"))
        test_layout.addWidget(test_err_btn)

        layout.addLayout(btn_layout)
        layout.addLayout(test_layout)

    def test_loading(self):
        from ui.widgets.loading_overlay import LoadingOverlay
        from PyQt6.QtCore import QTimer
        
        # 找到主窗口
        parent = self.parent()
        if not parent:
            return
            
        overlay = LoadingOverlay(parent)
        overlay.show()
        overlay.update_progress(0, 100, "正在测试加载进度条...")
        
        self.progress_val = 0
        self.loading_timer = QTimer(self)
        
        def update():
            self.progress_val += 5
            overlay.update_progress(self.progress_val, 100, f"正在加载 {self.progress_val}%")
            if self.progress_val >= 100:
                self.loading_timer.stop()
                overlay.hide()
                overlay.deleteLater()
                
        self.loading_timer.timeout.connect(update)
        self.loading_timer.start(100)

    def add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("new/key"))
        
        combo = QComboBox()
        combo.addItems(["str", "int", "bool", "float"])
        self.table.setCellWidget(row, 1, combo)
        
        self.table.setItem(row, 2, QTableWidgetItem(""))

    def delete_row(self):
        rows = set(item.row() for item in self.table.selectedItems())
        if not rows:
            return
            
        for row in sorted(rows, reverse=True):
            item = self.table.item(row, 0)
            if item:
                self.deleted_keys.add(item.text())
            self.table.removeRow(row)

    def load_settings(self):
        self.deleted_keys.clear()
        self.table.setRowCount(0)
        
        # Get all keys from storage
        stored_keys = set(self.settings_manager.settings.allKeys())
        # Also include keys from definitions that might not be stored yet
        defined_keys = set(self.settings_manager.SETTINGS_DEFINITIONS.keys())
        all_keys = sorted(list(stored_keys | defined_keys))
        
        self.table.setRowCount(len(all_keys))
        for i, key in enumerate(all_keys):
            val = self.settings_manager.get(key)
            self.table.setItem(i, 0, QTableWidgetItem(str(key)))
            
            # Setup Type ComboBox
            combo = QComboBox()
            combo.addItems(["str", "int", "bool", "float", "bytes"])
            
            # Determine type from definition first, then value
            def_meta = self.settings_manager.get_definition(key)
            type_str = "str"
            
            if "type" in def_meta:
                t = def_meta["type"]
                if t == bool: type_str = "bool"
                elif t == int: type_str = "int"
                elif t == float: type_str = "float"
                elif t == QByteArray: type_str = "bytes"
            else:
                # Infer from value
                if isinstance(val, bool) or str(val).lower() in ['true', 'false']:
                    type_str = "bool"
                    if isinstance(val, str): val = val.lower()
                elif isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
                    type_str = "int"
                elif isinstance(val, float):
                    type_str = "float"
                elif isinstance(val, (QByteArray, bytes)):
                    type_str = "bytes"
                
            combo.setCurrentText(type_str)
            # 连接类型改变信号，如果变为 bool，则将 value 列的 widget 替换为 ComboBox
            # 这里简单起见，如果 type 是 bool，直接在第3列放一个 ComboBox，否则放 TableWidgetItem
            
            self.table.setCellWidget(i, 1, combo)
            
            # Format value for display
            display_val = str(val)
            if type_str == "bytes":
                if isinstance(val, QByteArray):
                    display_val = val.toHex().data().decode('ascii')
                elif isinstance(val, bytes):
                    display_val = val.hex()
                elif val is None:
                    display_val = ""
            
            if type_str == "bool":
                val_combo = QComboBox()
                val_combo.addItems(["True", "False"])
                # 设置当前选中项
                # val 可能是 bool(True/False) 或 str('true'/'false') 或 int(1/0)
                is_true = str(val).lower() == 'true' or val == True or val == 1
                val_combo.setCurrentText("True" if is_true else "False")
                self.table.setCellWidget(i, 2, val_combo)
            else:
                self.table.setItem(i, 2, QTableWidgetItem(display_val))

    def save_settings(self):
        # Delete removed keys
        saved_count = 0
        for key in self.deleted_keys:
            self.settings_manager.remove(key)
            saved_count += 1
            
        for i in range(self.table.rowCount()):
            key_item = self.table.item(i, 0)
            
            # 获取类型
            type_combo = self.table.cellWidget(i, 1)
            type_str = type_combo.currentText()
            
            # 获取值
            val_str = ""
            if type_str == "bool":
                val_widget = self.table.cellWidget(i, 2)
                if isinstance(val_widget, QComboBox):
                    val_str = val_widget.currentText()
                else:
                    # Fallback if widget is not combo (should not happen with logic above)
                    item = self.table.item(i, 2)
                    val_str = item.text() if item else ""
            else:
                val_item = self.table.item(i, 2)
                if not val_item: continue
                val_str = val_item.text()
            
            if not key_item:
                continue
                
            key = key_item.text()
            
            try:
                if type_str == "int":
                    val = int(val_str)
                elif type_str == "float":
                    val = float(val_str)
                elif type_str == "bool":
                    val = val_str.lower() == 'true'
                elif type_str == "bytes":
                    val = QByteArray.fromHex(val_str.encode('ascii'))
                else:
                    val = val_str
                
                # 仅保存修改过的项
                current_val = self.settings_manager.get(key)
                # 注意：如果类型不同但值看起来一样（如 1 和 1.0），这里也会视为不同并保存，这是符合预期的
                if current_val != val:
                    self.settings_manager.set(key, val)
                    saved_count += 1
                    
            except ValueError:
                NotificationManager.instance().show_warning("错误", f"键 '{key}' 的值无法转换为 {type_str}")
                return
            
        self.settings_manager.sync()
        self.deleted_keys.clear()
        NotificationManager.instance().show_info("提示", f"设置已保存 ({saved_count} 项变更)")