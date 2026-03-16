#!/usr/bin/env python3
"""
栖图自动升级系统 - 升级进度对话框

显示下载和安装进度，退出按钮置灰
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QWidget, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from . import update_config as config


class UpdateProgressDialog(QDialog):
    """
    升级进度对话框
    
    显示下载和安装进度，提供取消功能（仅在可取消时启用）
    """
    
    # 信号定义
    cancel_requested = pyqtSignal()    # 请求取消
    
    def __init__(self, parent=None):
        """
        初始化进度对话框
        
        参数:
            parent: 父窗口
        """
        super().__init__(parent)
        self._total_steps = 1
        self._current_step = 0
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self):
        """设置UI界面"""
        # 设置窗口属性
        self.setWindowTitle(config.PROGRESS_DIALOG_TITLE)
        self.setFixedSize(config.PROGRESS_DIALOG_WIDTH, config.PROGRESS_DIALOG_HEIGHT)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        # 设置为模态对话框，阻止用户操作其他窗口
        self.setModal(True)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(20)
        
        # 标题区域
        self.title_label = QLabel("正在升级...")
        self.title_label.setObjectName("titleLabel")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.title_label)
        
        # 状态信息区域
        info_frame = QFrame()
        info_frame.setObjectName("infoFrame")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(10)
        
        # 当前步骤
        self.step_label = QLabel("准备下载...")
        self.step_label.setObjectName("stepLabel")
        info_layout.addWidget(self.step_label)
        
        # 当前文件
        self.file_label = QLabel("")
        self.file_label.setObjectName("fileLabel")
        self.file_label.setWordWrap(True)
        info_layout.addWidget(self.file_label)
        
        main_layout.addWidget(info_frame)
        
        # 下载进度区域
        download_frame = QFrame()
        download_frame.setObjectName("progressFrame")
        download_layout = QVBoxLayout(download_frame)
        download_layout.setSpacing(8)
        
        # 下载进度标签
        download_header = QHBoxLayout()
        download_label = QLabel("下载进度:")
        download_label.setObjectName("progressLabel")
        download_header.addWidget(download_label)
        
        self.download_percent_label = QLabel("0%")
        self.download_percent_label.setObjectName("percentLabel")
        download_header.addStretch()
        download_header.addWidget(self.download_percent_label)
        
        download_layout.addLayout(download_header)
        
        # 下载进度条
        self.download_progress = QProgressBar()
        self.download_progress.setObjectName("progressBar")
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setTextVisible(False)
        download_layout.addWidget(self.download_progress)
        
        main_layout.addWidget(download_frame)
        
        # 安装进度区域
        install_frame = QFrame()
        install_frame.setObjectName("progressFrame")
        install_layout = QVBoxLayout(install_frame)
        install_layout.setSpacing(8)
        
        # 安装进度标签
        install_header = QHBoxLayout()
        install_label = QLabel("安装进度:")
        install_label.setObjectName("progressLabel")
        install_header.addWidget(install_label)
        
        self.install_percent_label = QLabel("0%")
        self.install_percent_label.setObjectName("percentLabel")
        install_header.addStretch()
        install_header.addWidget(self.install_percent_label)
        
        install_layout.addLayout(install_header)
        
        # 安装进度条
        self.install_progress = QProgressBar()
        self.install_progress.setObjectName("progressBar")
        self.install_progress.setRange(0, 100)
        self.install_progress.setValue(0)
        self.install_progress.setTextVisible(False)
        install_layout.addWidget(self.install_progress)
        
        main_layout.addWidget(install_frame)
        
        # 弹性空间
        main_layout.addStretch()
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setEnabled(False)  # 默认禁用
        self.cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.cancel_btn)
        
        main_layout.addLayout(button_layout)
    
    def _apply_styles(self):
        """应用样式"""
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
            }
            
            #titleLabel {
                color: #333333;
                margin-bottom: 5px;
            }
            
            #infoFrame {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 15px;
            }
            
            #stepLabel {
                color: #333333;
                font-size: 13px;
                font-weight: bold;
            }
            
            #fileLabel {
                color: #666666;
                font-size: 12px;
            }
            
            #progressFrame {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 12px;
            }
            
            #progressLabel {
                color: #555555;
                font-size: 12px;
            }
            
            #percentLabel {
                color: #1890ff;
                font-size: 12px;
                font-weight: bold;
            }
            
            QProgressBar {
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                background-color: #f0f0f0;
                height: 8px;
            }
            
            QProgressBar::chunk {
                background-color: #1890ff;
                border-radius: 3px;
            }
            
            #cancelBtn {
                background-color: white;
                color: #555555;
                border: 1px solid #cccccc;
                padding: 8px 25px;
                border-radius: 4px;
                font-size: 13px;
                min-width: 80px;
            }
            
            #cancelBtn:hover {
                background-color: #f5f5f5;
            }
            
            #cancelBtn:disabled {
                background-color: #f0f0f0;
                color: #999999;
                border-color: #e0e0e0;
            }
        """)
    
    def set_total_steps(self, total: int):
        """
        设置总步骤数
        
        参数:
            total: 总步骤数
        """
        self._total_steps = max(1, total)
        self._update_step_label()
    
    def set_current_step(self, step: int, description: str = ""):
        """
        设置当前步骤
        
        参数:
            step: 当前步骤序号（从1开始）
            description: 步骤描述
        """
        self._current_step = step
        if description:
            self.step_label.setText(description)
        else:
            self._update_step_label()
    
    def _update_step_label(self):
        """更新步骤标签"""
        self.step_label.setText(
            f"步骤 {self._current_step}/{self._total_steps}"
        )
    
    def set_download_progress(self, progress: int):
        """
        设置下载进度
        
        参数:
            progress: 进度百分比 0-100
        """
        progress = max(0, min(100, progress))
        self.download_progress.setValue(progress)
        self.download_percent_label.setText(f"{progress}%")
    
    def set_install_progress(self, progress: int):
        """
        设置安装进度
        
        参数:
            progress: 进度百分比 0-100
        """
        progress = max(0, min(100, progress))
        self.install_progress.setValue(progress)
        self.install_percent_label.setText(f"{progress}%")
    
    def set_status_text(self, text: str):
        """
        设置状态文本
        
        参数:
            text: 状态文本
        """
        self.step_label.setText(text)
    
    def set_current_file(self, filename: str):
        """
        设置当前处理的文件名
        
        参数:
            filename: 文件名
        """
        if filename:
            self.file_label.setText(f"当前文件: {filename}")
            self.file_label.setVisible(True)
        else:
            self.file_label.setVisible(False)
    
    def enable_cancel_button(self, enabled: bool):
        """
        启用/禁用取消按钮
        
        参数:
            enabled: 是否启用
        """
        self.cancel_btn.setEnabled(enabled)
    
    def set_cancel_enabled(self, enabled: bool):
        """
        设置取消按钮是否可用（同 enable_cancel_button）
        
        参数:
            enabled: 是否可用
        """
        self.enable_cancel_button(enabled)
    
    def _on_cancel(self):
        """处理取消按钮点击"""
        self.cancel_requested.emit()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("正在取消...")
    
    def set_title(self, title: str):
        """
        设置对话框标题
        
        参数:
            title: 标题文本
        """
        self.setWindowTitle(title)
    
    def set_phase(self, phase: str):
        """
        设置当前阶段（下载/安装）
        
        参数:
            phase: 阶段名称
        """
        self.title_label.setText(f"正在{phase}...")


if __name__ == "__main__":
    # 测试进度对话框
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    dialog = UpdateProgressDialog()
    dialog.set_total_steps(3)
    dialog.set_current_step(1, "正在下载升级包...")
    dialog.set_current_file("qitu_V0.0.5.zip")
    dialog.set_download_progress(45)
    dialog.enable_cancel_button(True)
    
    dialog.cancel_requested.connect(lambda: print("请求取消"))
    
    # 模拟进度更新
    from PyQt6.QtCore import QTimer
    
    progress = 0
    def update_progress():
        global progress
        progress += 5
        dialog.set_download_progress(progress)
        if progress >= 100:
            timer.stop()
            dialog.set_phase("安装")
            dialog.set_current_step(2, "正在安装升级包...")
            dialog.set_install_progress(0)
    
    timer = QTimer()
    timer.timeout.connect(update_progress)
    timer.start(200)
    
    dialog.show()
    sys.exit(app.exec())
