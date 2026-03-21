#!/usr/bin/env python3
"""
栖图自动升级系统 - 设置页面升级管理标签页

在设置中显示升级历史记录
"""

import os
from datetime import datetime
from typing import Optional, Dict, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QGroupBox, QProgressBar, QTextEdit, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont

from ui.utils.color_manager import ColorManager
from ui.utils.notification_manager import NotificationManager
from ui.utils.icon_loader import qta
from update.update_history_manager import get_history_manager
from update.update_checker import UpdateChecker, CheckUpdateThread


# 获取日志管理器实例
def _get_logger():
    """获取日志管理器实例"""
    try:
        from utils.log_manager import LogManager
        return LogManager.instance()
    except Exception:
        return None


def _log_debug(msg: str):
    """记录debug日志"""
    logger = _get_logger()
    if logger:
        logger.debug(f"[UpdateSettings] {msg}")


def _log_error(msg: str):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        logger.error(f"[UpdateSettings] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[UpdateSettings] {msg}")


class UpdateCheckWorker(QThread):
    """
    升级检查工作线程
    """
    check_completed = pyqtSignal(dict)
    check_failed = pyqtSignal(str)
    
    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version
        self._result = None
        self._error = None
    
    def run(self):
        """执行升级检查"""
        _log_debug(f"UpdateCheckWorker 开始检查，当前版本: {self.current_version}")
        try:
            # 直接执行检查，不使用子线程
            from update.update_checker import UpdateChecker, CheckUpdateThread, VersionInfo
            from update import update_config as config
            from update.mirror_selector import get_manifest_urls, is_url_disabled, record_url_failure, clear_cache
            import urllib.request
            import json

            # 获取版本清单
            urls = get_manifest_urls()
            _log_debug(f"将尝试 {len(urls)} 个地址获取版本清单")

            manifest = None
            last_error = None
            failed_urls = []  # 记录失败的URL
            
            for url_index, (url, desc) in enumerate(urls):
                # 检查URL是否被禁用
                if is_url_disabled(url):
                    _log_debug(f"跳过被禁用的地址 [{desc}]: {url}")
                    continue
                
                _log_debug(f"尝试地址 {url_index + 1}/{len(urls)} [{desc}]")

                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'BirdPictureManager-UpdateChecker/1.0',
                        'Accept': 'application/json'
                    }
                )

                max_retries = 2
                url_failed = True
                for attempt in range(max_retries):
                    try:
                        _log_debug(f"正在获取版本清单... (尝试 {attempt + 1}/{max_retries})")
                        with urllib.request.urlopen(req, timeout=10) as response:
                            data = response.read().decode('utf-8')
                            manifest = json.loads(data)
                            _log_debug(f"版本清单获取成功，使用镜像: {desc}")
                            url_failed = False
                            break
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(1)
                        else:
                            break

                if manifest:
                    break
                
                if url_failed:
                    failed_urls.append(url)

            # 记录失败的URL
            for failed_url in failed_urls:
                record_url_failure(failed_url)
            
            if not manifest:
                _log_debug(f"无法获取版本清单: {last_error}")
                # 清除镜像缓存
                clear_cache()
                
                # 立即启动镜像可用测试
                _log_info("检查失败，立即启动镜像可用测试...")
                try:
                    from update.mirror_selector import test_all_mirrors
                    test_all_mirrors()
                    _log_info("镜像可用测试完成")
                except Exception as test_error:
                    _log_debug(f"镜像可用测试失败: {test_error}")
                
                self.check_failed.emit(f"无法获取版本清单: {last_error}")
                return

            # 获取最新版本
            latest_version = manifest.get("latest_version", "")
            if not latest_version:
                _log_debug("版本清单中未找到最新版本信息")
                self.check_failed.emit("版本清单中未找到最新版本信息")
                return

            _log_debug(f"最新版本: {latest_version}")

            # 检查是否为测试版本
            latest_v = VersionInfo(latest_version)
            if latest_v.is_test and not config.LINK_TEST_MODE:
                _log_debug("链路测试模式未启用，跳过测试版本")
                self.check_completed.emit({
                    "has_update": False,
                    "current_version": self.current_version,
                    "latest_version": latest_version,
                    "message": "链路测试模式未启用，跳过测试版本"
                })
                return

            # 比较版本
            checker = UpdateChecker()
            comparison = checker.compare_versions(self.current_version, latest_version)

            # 检查是否为同版本（忽略 _test 后缀）
            current_v = VersionInfo(self.current_version)
            is_same_version = (current_v.base == latest_v.base and 
                              current_v.update == latest_v.update)
            
            if comparison >= 0 and not (is_same_version and config.SAME_VERSION_UPGRADE):
                # 当前版本已是最新或更新，且不满足同版本升级条件
                _log_debug(f"当前版本已是最新: {self.current_version}")
                self.check_completed.emit({
                    "has_update": False,
                    "current_version": self.current_version,
                    "latest_version": latest_version
                })
                return

            # 有更新，计算升级路径
            _log_debug(f"发现新版本: {latest_version}")
            try:
                upgrade_steps = checker.calculate_upgrade_path(
                    self.current_version,
                    latest_version,
                    manifest
                )
            except ValueError as e:
                _log_debug(f"计算升级路径失败: {e}")
                self.check_failed.emit(str(e))
                return

            _log_debug(f"升级路径计算完成，共 {len(upgrade_steps)} 步")

            # 组装更新信息
            update_info = {
                "has_update": True,
                "current_version": self.current_version,
                "latest_version": latest_version,
                "release_date": manifest.get("release_date", ""),
                "changelog": manifest.get("changelog", ""),
                "force_update": manifest.get("force_update", False),
                "min_supported_version": manifest.get("min_supported_version", config.MIN_SUPPORTED_VERSION),
                "upgrade_steps": upgrade_steps,
                "total_steps": len(upgrade_steps),
                "total_size": sum(step.get("size", 0) for step in upgrade_steps),
                "is_test_version": latest_v.is_test
            }

            _log_debug(f"发射 check_completed 信号")
            self.check_completed.emit(update_info)

        except Exception as e:
            _log_debug(f"UpdateCheckWorker 异常: {e}")
            self.check_failed.emit(str(e))


class UpdateSettingsPage(QWidget):
    """
    升级管理设置页面
    
    功能：
    1. 显示升级历史记录列表
    2. 显示当前版本信息
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history_manager = get_history_manager()
        self.update_check_worker: Optional[UpdateCheckWorker] = None
        self.update_info: Optional[Dict] = None
        self._history_loaded = False  # 标记历史记录是否已加载
        self.init_ui()
        self._apply_theme_styles()
        
        # 注册主题变更监听
        ColorManager.instance().register_listener(self._apply_theme_styles)
        
        # 连接到全局 UpdateManager 的信号，接收自动检查的结果
        self._connect_to_update_manager()
        
        # 获取之前的检查结果（如果已经检查过）
        self._load_previous_check_result()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 升级检查组
        self.update_check_group = QGroupBox("升级检查")
        self.update_check_layout = QVBoxLayout(self.update_check_group)
        
        # 检查状态
        self.update_status_label = QLabel("检查状态: 未检查")
        self.update_status_label.setStyleSheet("font-size: 14px;")
        self.update_check_layout.addWidget(self.update_status_label)
        
        # 版本信息
        self.available_version_label = QLabel("可升级版本: 无")
        self.available_version_label.setStyleSheet("font-size: 14px;")
        self.update_check_layout.addWidget(self.available_version_label)
        
        # 包大小
        self.package_size_label = QLabel("升级包大小: 0 MB")
        self.package_size_label.setStyleSheet("font-size: 14px;")
        self.update_check_layout.addWidget(self.package_size_label)
        
        # 操作按钮
        check_btn_layout = QHBoxLayout()
        check_btn_layout.addStretch()
        
        self.check_update_btn = QPushButton("检查更新")
        self.check_update_btn.setFixedSize(100, 36)
        self.check_update_btn.clicked.connect(self.check_for_updates)
        check_btn_layout.addWidget(self.check_update_btn)
        
        self.upgrade_btn = QPushButton("立即升级")
        self.upgrade_btn.setFixedSize(100, 36)
        self.upgrade_btn.setEnabled(False)
        self.upgrade_btn.clicked.connect(self.start_upgrade)
        check_btn_layout.addWidget(self.upgrade_btn)
        
        self.update_check_layout.addLayout(check_btn_layout)
        
        layout.addWidget(self.update_check_group)
        
        # 当前版本信息组
        self.current_version_group = QGroupBox("当前版本信息")
        self.current_version_layout = QVBoxLayout(self.current_version_group)
        
        self.current_version_label = QLabel("当前版本: 加载中...")
        self.current_version_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.current_version_layout.addWidget(self.current_version_label)
        
        self.last_update_label = QLabel("上次升级: 无记录")
        self.current_version_layout.addWidget(self.last_update_label)
        
        layout.addWidget(self.current_version_group)
        
        # 升级历史记录组
        self.history_group = QGroupBox("升级历史记录")
        self.history_layout = QVBoxLayout(self.history_group)
        
        # 历史记录表格
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels([
            "时间", "从版本", "到版本", "升级包", "状态"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(0, 150)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        
        self.history_layout.addWidget(self.history_table)
        
        # 按钮布局
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        # 清除全部记录按钮（左侧）
        self.clear_all_btn = QPushButton("清除全部记录")
        self.clear_all_btn.setFixedSize(120, 36)
        self.clear_all_btn.clicked.connect(self.clear_all_history)
        btn_layout.addWidget(self.clear_all_btn)

        btn_layout.addSpacing(10)

        # 刷新按钮
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setFixedSize(100, 36)
        self.refresh_btn.clicked.connect(self.load_history)
        btn_layout.addWidget(self.refresh_btn)

        btn_layout.addSpacing(10)

        # 清理选中记录按钮（右侧）
        self.clear_selected_btn = QPushButton("清理记录")
        self.clear_selected_btn.setFixedSize(100, 36)
        self.clear_selected_btn.clicked.connect(self.clear_selected_history)
        btn_layout.addWidget(self.clear_selected_btn)

        self.history_layout.addLayout(btn_layout)
        
        layout.addWidget(self.history_group)
        
        # 说明文字
        self.info_label = QLabel(
            "说明：\n"
            "• 升级历史记录会保存最近 50 次升级操作\n"
            "• 每次升级前会备份受影响的文件\n"
            "• 建议定期清理旧的历史记录以释放空间"
        )
        self.info_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(self.info_label)
        
        layout.addStretch()
    
    def _get_diff_cache_dir(self) -> str:
        """
        获取差异文件清单缓存目录

        返回:
            差异清单缓存目录路径 (/cache/diff/)，与下载目录分开，避免被误删除
        """
        from update import update_config as config
        return config.get_diff_cache_dir()

    def _load_affected_files_from_diff(self, from_version: str, to_version: str) -> List[str]:
        """
        从/cache/diff/目录加载差异文件清单

        参数:
            from_version: 旧版本号
            to_version: 新版本号

        返回:
            受影响的文件列表
        """
        import json
        diff_dir = self._get_diff_cache_dir()
        diff_filename = f"diff_V{from_version}_to_V{to_version}.json"
        diff_path = os.path.join(diff_dir, diff_filename)

        if os.path.exists(diff_path):
            try:
                with open(diff_path, 'r', encoding='utf-8') as f:
                    diff_manifest = json.load(f)
                    return diff_manifest.get('affected_files', [])
            except Exception as e:
                _log_error(f"读取差异清单失败: {e}")

        return []

    def load_history(self):
        """加载升级历史记录"""
        # 加载当前版本信息，使用完整版本号（包含update后缀）
        try:
            from utils.system.app_info_manager import AppInfoManager
            full_version = AppInfoManager.instance().get_full_version()
            self.current_version_label.setText(f"当前版本: {full_version}")
        except Exception:
            self.current_version_label.setText("当前版本: 未知")

        # 加载历史记录
        history = self.history_manager.load_history()

        # 更新上次升级信息
        if history:
            latest = history[0]
            if latest.get("success"):
                time_str = self._format_time(latest.get("timestamp", ""))
                self.last_update_label.setText(
                    f"上次升级: {time_str} 从 {latest.get('from_version', '')} 升级到 {latest.get('to_version', '')}"
                )
            else:
                self.last_update_label.setText("上次升级: 失败")
        else:
            self.last_update_label.setText("上次升级: 无记录")

        # 填充表格
        self.history_table.setRowCount(len(history))

        for row, entry in enumerate(history):
            # 时间
            time_str = self._format_time(entry.get("timestamp", ""))
            time_item = QTableWidgetItem(time_str)
            time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.history_table.setItem(row, 0, time_item)

            # 从版本
            from_ver = entry.get("from_version", "")
            from_item = QTableWidgetItem(from_ver)
            from_item.setFlags(from_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.history_table.setItem(row, 1, from_item)

            # 到版本
            to_ver = entry.get("to_version", "")
            to_item = QTableWidgetItem(to_ver)
            to_item.setFlags(to_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.history_table.setItem(row, 2, to_item)

            # 升级包（显示受影响的文件数量）
            package = entry.get("package_name", "")
            # 优先从/cache/diff/读取差异文件
            affected_files = entry.get("affected_files", [])
            if not affected_files and from_ver and to_ver:
                affected_files = self._load_affected_files_from_diff(from_ver, to_ver)

            if affected_files:
                package_display = f"{package}\n({len(affected_files)} 个文件)"
            else:
                package_display = package
            package_item = QTableWidgetItem(package_display)
            package_item.setFlags(package_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.history_table.setItem(row, 3, package_item)

            # 状态
            if entry.get("success"):
                status = "成功"
            else:
                status = f"失败: {entry.get('error_msg', '')[:20]}"

            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(Qt.GlobalColor.darkGreen if entry.get("success") else Qt.GlobalColor.darkRed)
            self.history_table.setItem(row, 4, status_item)
    
    def clear_selected_history(self):
        """清理选中的历史记录"""
        # 获取选中的行
        selected_rows = self.history_table.selectedItems()
        if not selected_rows:
            NotificationManager.instance().show_toast(
                "请先选中要删除的记录",
                duration=3000
            )
            return

        # 获取选中行的索引
        row = selected_rows[0].row()

        # 获取历史记录
        history = self.history_manager.load_history()
        if row >= len(history):
            return

        entry = history[row]
        entry_id = entry.get("id", "")
        from_version = entry.get("from_version", "")
        to_version = entry.get("to_version", "")

        # 确认对话框
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("确认删除")
        msg_box.setText(
            f"确定要删除这条升级记录吗？\n\n"
            f"时间: {self._format_time(entry.get('timestamp', ''))}\n"
            f"从版本: {from_version}\n"
            f"到版本: {to_version}\n\n"
            "此操作不可恢复，是否继续？"
        )
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Ok)
        msg_box.button(QMessageBox.StandardButton.Ok).setText("确定")
        msg_box.button(QMessageBox.StandardButton.Cancel).setText("取消")

        if msg_box.exec() != QMessageBox.StandardButton.Ok:
            return

        try:
            # 删除选中的记录
            if self.history_manager.delete_history_entry(entry_id):
                # 清除表格选中状态
                self.history_table.clearSelection()

                # 重新加载表格数据
                self.load_history()

                NotificationManager.instance().show_toast(
                    "已删除选中的记录",
                    duration=3000
                )
            else:
                NotificationManager.instance().show_toast(
                    "删除失败: 未找到记录",
                    duration=3000
                )
        except Exception as e:
            NotificationManager.instance().show_toast(
                f"删除失败: {str(e)}",
                duration=3000
            )

    def clear_all_history(self):
        """清除全部历史记录"""
        # 确认对话框
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("确认清除全部")
        msg_box.setText(
            "确定要清除全部升级记录吗？\n\n"
            "这将删除：\n"
            "• 所有升级历史记录\n"
            "• 所有备份文件\n"
            "• 所有差异清单文件\n\n"
            "此操作不可恢复，是否继续？"
        )
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        msg_box.button(QMessageBox.StandardButton.Ok).setText("确定")
        msg_box.button(QMessageBox.StandardButton.Cancel).setText("取消")

        if msg_box.exec() != QMessageBox.StandardButton.Ok:
            return

        try:
            # 清除全部历史记录
            if self.history_manager.clear_all_history():
                # 清除差异清单文件
                diff_dir = self._get_diff_cache_dir()
                if os.path.exists(diff_dir):
                    for filename in os.listdir(diff_dir):
                        if filename.startswith('diff_V') and filename.endswith('.json'):
                            file_path = os.path.join(diff_dir, filename)
                            try:
                                os.remove(file_path)
                            except Exception:
                                pass

                # 清除表格选中状态
                self.history_table.clearSelection()

                # 重新加载表格数据（会清空表格）
                self.load_history()

                NotificationManager.instance().show_toast(
                    "已清除全部历史记录",
                    duration=3000
                )
            else:
                NotificationManager.instance().show_toast(
                    "清除失败",
                    duration=3000
                )
        except Exception as e:
            NotificationManager.instance().show_toast(
                f"清除失败: {str(e)}",
                duration=3000
            )
    
    def _format_time(self, timestamp_str: str) -> str:
        """
        格式化时间字符串
        
        参数:
            timestamp_str: ISO格式时间字符串
            
        返回:
            格式化后的时间字符串
        """
        try:
            dt = datetime.fromisoformat(timestamp_str)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return timestamp_str
    
    def _apply_theme_styles(self):
        """应用主题样式"""
        cm = ColorManager.instance()
        
        # 获取颜色值
        bg_primary = cm.get("theme.background.primary")
        bg_light = cm.get("theme.background.light")
        text_dark = cm.get("theme.text.dark")
        text_light = cm.get("theme.text.light")
        primary = cm.get("theme.primary")
        border = cm.get("theme.border")
        
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_primary};
                color: {text_dark};
            }}
            
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {border};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
                padding-left: 12px;
                padding-right: 12px;
                padding-bottom: 12px;
            }}
            
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            
            QTableWidget {{
                background-color: {bg_light};
                border: 1px solid {border};
                border-radius: 4px;
                gridline-color: {border};
            }}
            
            QTableWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {border};
            }}
            
            QTableWidget::item:selected {{
                background-color: {primary}33;
                color: {text_dark};
            }}
            
            QHeaderView::section {{
                background-color: {bg_primary};
                color: {text_dark};
                padding: 8px;
                border: none;
                border-bottom: 2px solid {primary};
                font-weight: bold;
            }}
            
            QPushButton {{
                background-color: {primary};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            
            QPushButton:hover {{
                background-color: {primary}dd;
            }}
            
            QPushButton:pressed {{
                background-color: {primary}aa;
            }}
            
            QPushButton:disabled {{
                background-color: {border};
                color: {text_light};
            }}
            
            QProgressBar {{
                border: 1px solid {border};
                border-radius: 4px;
                text-align: center;
                background-color: {bg_light};
            }}
            
            QProgressBar::chunk {{
                background-color: {primary};
                border-radius: 3px;
            }}
            
            QLabel {{
                color: {text_dark};
            }}
        """)
    
    def _connect_to_update_manager(self):
        """
        连接到全局 UpdateManager 的信号
        用于接收启动时自动检查的结果
        """
        try:
            from update.update_manager import get_update_manager
            update_manager = get_update_manager()
            
            # 连接检查完成和失败信号
            update_manager.check_completed.connect(self._on_auto_check_completed)
            update_manager.check_failed.connect(self._on_auto_check_failed)
            
            _log_debug("UpdateSettingsPage connected to UpdateManager signals")
        except Exception as e:
            _log_error(f"Failed to connect to UpdateManager: {e}")
    
    def _on_auto_check_completed(self, result: Dict):
        """
        自动检查完成回调（来自 UpdateManager）
        
        参数:
            result: 检查结果
        """
        # 只在不是手动检查时才更新UI（避免重复更新）
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            return
        
        # 自动检查不显示toast，只更新UI状态
        _log_debug(f"自动检查完成，更新UI但不显示toast")
        
        # 检查结果是否有效
        if not isinstance(result, dict):
            _log_error(f"自动检查完成回调收到无效结果: {result}")
            self.update_status_label.setText("检查状态: 检查失败")
            self.update_status_label.setStyleSheet("font-size: 14px; color: #F44336;")
            return
        
        if result.get("has_update", False):
            # 有更新 - 更新UI但不弹toast
            latest_version = result.get("latest_version", "")
            total_size = result.get("total_size", 0)
            size_mb = total_size / (1024 * 1024)
            is_test = result.get("is_test_version", False)
            
            self.update_status_label.setText("检查状态: 发现更新" + (" (测试版本)" if is_test else ""))
            self.update_status_label.setStyleSheet("font-size: 14px; color: #4CAF50;")
            self.available_version_label.setText(f"可升级版本: {latest_version}")
            self.package_size_label.setText(f"升级包大小: {size_mb:.1f} MB")
            self.upgrade_btn.setEnabled(True)
            
            # 保存更新信息
            self.update_info = result
        else:
            # 无更新 - 更新UI但不弹toast
            self.update_status_label.setText("检查状态: 已是最新版本")
            self.update_status_label.setStyleSheet("font-size: 14px; color: #4CAF50;")
            
            self.available_version_label.setText("可升级版本: 无")
            self.package_size_label.setText("升级包大小: 0 MB")
            self.upgrade_btn.setEnabled(False)
    
    def _on_auto_check_failed(self, error_msg: str):
        """
        自动检查失败回调（来自 UpdateManager）
        
        参数:
            error_msg: 错误信息
        """
        # 只在不是手动检查时才更新UI（避免重复更新）
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            return
        
        # 更新UI显示检查失败
        self.on_check_failed(error_msg)
    
    def _load_previous_check_result(self):
        """
        加载之前的检查结果
        
        在页面创建时调用，获取启动时自动检查的结果
        """
        try:
            from update.update_manager import get_update_manager
            update_manager = get_update_manager()
            
            # 获取最后一次检查结果
            last_result = update_manager.get_last_check_result()
            last_failed = update_manager.get_last_check_failed()
            
            if last_result is not None:
                _log_debug("加载到之前的检查结果")
                self.on_check_completed(last_result)
            elif last_failed is not None:
                _log_debug("加载到之前的检查失败信息")
                self.on_check_failed(last_failed)
            else:
                _log_debug("没有之前的检查结果")
                
        except Exception as e:
            _log_debug(f"加载之前的检查结果失败: {e}")
    
    def showEvent(self, event):
        """显示事件 - 刷新数据"""
        super().showEvent(event)
        # 延迟加载历史记录，避免阻塞UI初始化
        if not self._history_loaded:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, self._delayed_load_history)
        else:
            self.load_history()
    
    def _delayed_load_history(self):
        """延迟加载历史记录"""
        self.load_history()
        self._history_loaded = True
    
    def check_for_updates(self):
        """检查更新"""
        # 获取当前完整版本号（包含update后缀）
        try:
            from utils.system.app_info_manager import AppInfoManager
            current_version = AppInfoManager.instance().get_full_version()
        except Exception:
            current_version = "0.0.0"
        
        # 禁用按钮
        self.check_update_btn.setEnabled(False)
        self.upgrade_btn.setEnabled(False)
        self.update_status_label.setText("检查状态: 正在检查...")
        self.update_status_label.setStyleSheet("font-size: 14px; color: #2196F3;")
        
        # 创建工作线程
        self.update_check_worker = UpdateCheckWorker(current_version)
        self.update_check_worker.check_completed.connect(self.on_check_completed)
        self.update_check_worker.check_failed.connect(self.on_check_failed)
        self.update_check_worker.start()
    
    def on_check_completed(self, result: Dict):
        """检查完成回调"""
        _log_debug(f"on_check_completed 被调用，结果: {result}")
        # 启用按钮
        self.check_update_btn.setEnabled(True)

        # 检查结果是否有效
        if not isinstance(result, dict):
            _log_error(f"检查完成回调收到无效结果: {result}")
            self.update_status_label.setText("检查状态: 检查失败")
            self.update_status_label.setStyleSheet("font-size: 14px; color: #F44336;")
            return

        _log_debug(f"检查结果 - has_update: {result.get('has_update', False)}")
        if result.get("has_update", False):
            # 有更新
            latest_version = result.get("latest_version", "")
            total_size = result.get("total_size", 0)
            size_mb = total_size / (1024 * 1024)
            is_test = result.get("is_test_version", False)
            
            self.update_status_label.setText("检查状态: 发现更新" + (" (测试版本)" if is_test else ""))
            self.update_status_label.setStyleSheet("font-size: 14px; color: #4CAF50;")
            self.available_version_label.setText(f"可升级版本: {latest_version}")
            self.package_size_label.setText(f"升级包大小: {size_mb:.1f} MB")
            self.upgrade_btn.setEnabled(True)
            
            # 保存更新信息
            self.update_info = result
            
            NotificationManager.instance().show_toast(
                f"发现新版本: {latest_version}",
                duration=3000
            )
        else:
            # 无更新 - 统一显示为已是最新版本，不区分测试版本
            self.update_status_label.setText("检查状态: 已是最新版本")
            self.update_status_label.setStyleSheet("font-size: 14px; color: #4CAF50;")
            
            self.available_version_label.setText("可升级版本: 无")
            self.package_size_label.setText("升级包大小: 0 MB")
            self.upgrade_btn.setEnabled(False)
            
            NotificationManager.instance().show_toast(
                "当前已是最新版本",
                duration=3000
            )
    
    def on_check_failed(self, error_msg: str):
        """检查失败回调"""
        _log_debug(f"on_check_failed 被调用，错误: {error_msg}")
        # 启用按钮
        self.check_update_btn.setEnabled(True)
        
        # 根据错误类型显示不同的状态
        if "网络" in error_msg or "连接" in error_msg or "HTTP" in error_msg:
            self.update_status_label.setText("检查状态: 无法连接服务器")
            self.update_status_label.setStyleSheet("font-size: 14px; color: #F44336;")
        elif "超时" in error_msg:
            self.update_status_label.setText("检查状态: 连接超时")
            self.update_status_label.setStyleSheet("font-size: 14px; color: #F44336;")
        else:
            self.update_status_label.setText(f"检查状态: 检查失败")
            self.update_status_label.setStyleSheet("font-size: 14px; color: #F44336;")
        
        self.available_version_label.setText("可升级版本: 获取失败")
        self.package_size_label.setText("升级包大小: 未知")
        
        NotificationManager.instance().show_toast(
            f"检查更新失败: {error_msg}",
            duration=3000
        )
    
    def start_upgrade(self):
        """开始升级"""
        if not self.update_info:
            return
        
        # 确认对话框 - 使用中文按钮
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("确认升级")
        msg_box.setText(
            f"确定要升级到版本 {self.update_info.get('latest_version', '')} 吗？\n\n"
            f"升级包大小: {self.update_info.get('total_size', 0) / (1024 * 1024):.1f} MB\n\n"
            "升级会：\n"
            "• 下载并安装升级包\n"
            "• 备份受影响的文件\n"
            "• 重启程序\n\n"
            "是否继续？"
        )
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Ok)
        msg_box.button(QMessageBox.StandardButton.Ok).setText("确定")
        msg_box.button(QMessageBox.StandardButton.Cancel).setText("取消")

        if msg_box.exec() != QMessageBox.StandardButton.Ok:
            return
        
        # 跳转到升级页面
        try:
            # 获取主窗口
            main_window = self.window()
            if not main_window:
                NotificationManager.instance().show_toast(
                    "无法获取主窗口",
                    duration=3000
                )
                return
            
            # 确保升级页面存在
            if not hasattr(main_window, '_update_page') or main_window._update_page is None:
                from ui.update_page import UpdatePage
                main_window._update_page = UpdatePage()
                main_window._update_page.update_completed.connect(self._on_update_completed)
                main_window._update_page.update_cancelled.connect(self._on_update_cancelled)
                
                # 添加到页面栈
                if hasattr(main_window, 'pages'):
                    main_window.pages.addWidget(main_window._update_page)
            
            # 准备升级信息
            update_data = {
                'current_version': self.update_info.get('current_version', ''),
                'latest_version': self.update_info.get('latest_version', ''),
                'total_size': self.update_info.get('total_size', 0),
                'upgrade_steps': self.update_info.get('upgrade_steps', []),
                'packages': self.update_info.get('packages', [])
            }
            
            # 启动升级
            main_window._update_page.start_update(update_data)
            
            # 切换到升级页面
            if hasattr(main_window, 'pages'):
                main_window.pages.setCurrentWidget(main_window._update_page)
            
        except Exception as e:
            NotificationManager.instance().show_toast(
                f"启动升级失败: {str(e)}",
                duration=3000
            )
    
    def _on_update_completed(self):
        """升级完成回调"""
        # 升级完成后，可以显示重启提示或自动重启
        NotificationManager.instance().show_toast(
            "升级完成！请重启程序以应用更新",
            duration=5000
        )
    
    def _on_update_cancelled(self):
        """升级取消回调"""
        # 返回设置页面
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'pages'):
                # 找到设置页面的索引
                for i in range(main_window.pages.count()):
                    widget = main_window.pages.widget(i)
                    if widget == self:
                        main_window.pages.setCurrentIndex(i)
                        break
        except Exception as e:
            _log_debug(f"返回设置页面失败: {e}")
