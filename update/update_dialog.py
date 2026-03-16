#!/usr/bin/env python3
"""
栖图自动升级系统 - 更新提示对话框

显示新版本信息，提供忽略、升级、取消三个选项
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QWidget, QFrame, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from . import update_config as config
from .update_downloader import format_size


class UpdateDialog(QDialog):
    """
    更新提示对话框
    
    显示新版本信息和更新日志，提供三个操作按钮：
    - 忽略当前版本：不再提示此版本
    - 开始升级：启动升级流程
    - 取消：关闭对话框，下次启动再提示
    """
    
    # 信号定义
    ignore_clicked = pyqtSignal()      # 点击忽略当前版本
    upgrade_clicked = pyqtSignal()     # 点击开始升级
    cancel_clicked = pyqtSignal()      # 点击取消
    
    def __init__(self, update_info: dict, parent=None):
        """
        初始化更新对话框
        
        参数:
            update_info: 更新信息字典，包含版本号、更新日志等
            parent: 父窗口
        """
        super().__init__(parent)
        self.update_info = update_info
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self):
        """设置UI界面"""
        # 设置窗口属性
        self.setWindowTitle(config.UPDATE_DIALOG_TITLE)
        self.setFixedSize(config.UPDATE_DIALOG_WIDTH, config.UPDATE_DIALOG_HEIGHT)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 标题区域
        title_label = QLabel("发现新版本")
        title_label.setObjectName("titleLabel")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 版本信息区域
        info_frame = QFrame()
        info_frame.setObjectName("infoFrame")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(8)
        
        # 当前版本
        current_version = self.update_info.get('current_version', '未知')
        current_label = QLabel(f"当前版本: V{current_version}")
        current_label.setObjectName("versionLabel")
        info_layout.addWidget(current_label)
        
        # 最新版本
        latest_version = self.update_info.get('latest_version', '未知')
        latest_label = QLabel(f"最新版本: V{latest_version}")
        latest_label.setObjectName("versionLabel")
        latest_font = QFont()
        latest_font.setBold(True)
        latest_label.setFont(latest_font)
        info_layout.addWidget(latest_label)
        
        # 发布日期
        release_date = self.update_info.get('release_date', '')
        if release_date:
            date_label = QLabel(f"发布日期: {release_date}")
            date_label.setObjectName("dateLabel")
            info_layout.addWidget(date_label)
        
        # 更新大小
        total_size = self.update_info.get('total_size', 0)
        if total_size > 0:
            size_label = QLabel(f"更新大小: {format_size(total_size)}")
            size_label.setObjectName("sizeLabel")
            info_layout.addWidget(size_label)
        
        main_layout.addWidget(info_frame)
        
        # 更新日志区域
        changelog_label = QLabel("更新内容:")
        changelog_label.setObjectName("sectionLabel")
        main_layout.addWidget(changelog_label)
        
        self.changelog_edit = QTextEdit()
        self.changelog_edit.setObjectName("changelogEdit")
        self.changelog_edit.setReadOnly(True)
        self.changelog_edit.setPlaceholderText("暂无更新日志")
        
        # 设置更新日志内容
        changelog = self.update_info.get('changelog', '')
        if changelog:
            self.changelog_edit.setPlainText(changelog)
        
        main_layout.addWidget(self.changelog_edit)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        # 左侧按钮（忽略）
        self.ignore_btn = QPushButton("忽略当前版本")
        self.ignore_btn.setObjectName("ignoreBtn")
        self.ignore_btn.setToolTip("不再提示此版本的更新")
        self.ignore_btn.clicked.connect(self._on_ignore)
        button_layout.addWidget(self.ignore_btn)
        
        # 弹性空间
        button_layout.addStretch()
        
        # 右侧按钮（取消和升级）
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_btn)
        
        self.upgrade_btn = QPushButton("开始升级")
        self.upgrade_btn.setObjectName("upgradeBtn")
        self.upgrade_btn.setDefault(True)
        self.upgrade_btn.clicked.connect(self._on_upgrade)
        button_layout.addWidget(self.upgrade_btn)
        
        main_layout.addLayout(button_layout)
    
    def _apply_styles(self):
        """应用样式"""
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
            }
            
            #titleLabel {
                color: #333333;
                margin-bottom: 10px;
            }
            
            #infoFrame {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 10px;
            }
            
            #versionLabel {
                color: #555555;
                font-size: 13px;
            }
            
            #dateLabel, #sizeLabel {
                color: #777777;
                font-size: 12px;
            }
            
            #sectionLabel {
                color: #333333;
                font-size: 13px;
                font-weight: bold;
                margin-top: 5px;
            }
            
            #changelogEdit {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                line-height: 1.5;
            }
            
            QPushButton {
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
                min-width: 80px;
            }
            
            #ignoreBtn {
                background-color: transparent;
                color: #999999;
                border: 1px solid #cccccc;
            }
            
            #ignoreBtn:hover {
                background-color: #f0f0f0;
                color: #666666;
            }
            
            #cancelBtn {
                background-color: white;
                color: #555555;
                border: 1px solid #cccccc;
            }
            
            #cancelBtn:hover {
                background-color: #f5f5f5;
            }
            
            #upgradeBtn {
                background-color: #1890ff;
                color: white;
                border: none;
            }
            
            #upgradeBtn:hover {
                background-color: #40a9ff;
            }
            
            #upgradeBtn:pressed {
                background-color: #096dd9;
            }
        """)
    
    def _on_ignore(self):
        """处理忽略按钮点击"""
        self.ignore_clicked.emit()
        self.reject()
    
    def _on_upgrade(self):
        """处理升级按钮点击"""
        self.upgrade_clicked.emit()
        self.accept()
    
    def _on_cancel(self):
        """处理取消按钮点击"""
        self.cancel_clicked.emit()
        self.reject()
    
    def set_changelog(self, changelog: str):
        """
        设置更新日志
        
        参数:
            changelog: 更新日志内容
        """
        self.changelog_edit.setPlainText(changelog)
    
    def set_version_info(self, current: str, latest: str):
        """
        设置版本信息
        
        参数:
            current: 当前版本
            latest: 最新版本
        """
        # 更新UI中的版本信息
        for child in self.findChildren(QLabel):
            if child.text().startswith("当前版本:"):
                child.setText(f"当前版本: V{current}")
            elif child.text().startswith("最新版本:"):
                child.setText(f"最新版本: V{latest}")


def show_update_dialog(update_info: dict, parent=None) -> int:
    """
    显示更新对话框
    
    参数:
        update_info: 更新信息字典
        parent: 父窗口
        
    返回:
        QDialog.DialogCode: Accepted 或 Rejected
    """
    dialog = UpdateDialog(update_info, parent)
    return dialog.exec()


if __name__ == "__main__":
    # 测试对话框
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 测试数据
    test_info = {
        "current_version": "0.0.4",
        "latest_version": "0.0.5_update2",
        "release_date": "2026-03-15",
        "changelog": """## V0.0.5_update2
- 修复了图片加载时的内存泄漏问题
- 优化了大图浏览时的性能
- 新增支持 WebP 格式图片
- 改进了搜索功能的响应速度

## V0.0.5
- 全新设计的用户界面
- 支持批量导出功能
- 新增图片编辑工具
""",
        "total_size": 52428800,
        "total_steps": 2
    }
    
    dialog = UpdateDialog(test_info)
    dialog.ignore_clicked.connect(lambda: print("忽略当前版本"))
    dialog.upgrade_clicked.connect(lambda: print("开始升级"))
    dialog.cancel_clicked.connect(lambda: print("取消"))
    
    result = dialog.exec()
    print(f"对话框结果: {'Accepted' if result == QDialog.DialogCode.Accepted else 'Rejected'}")
    
    sys.exit(0)
