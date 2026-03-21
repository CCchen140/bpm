#!/usr/bin/env python3
"""
栖图自动升级系统 - 升级管理器

核心协调模块，负责整个升级流程的管理
"""

import os
import json
import sys
import traceback
from typing import Optional, Dict, List
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from . import update_config as config
from .update_checker import UpdateChecker
from .update_downloader import UpdateDownloader
from .update_installer import UpdateInstaller, get_install_dir
from .update_dialog import UpdateDialog
from .update_progress_dialog import UpdateProgressDialog


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
        logger.debug(f"[Update] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[Update] {msg}")


def _log_warning(msg: str):
    """记录warning日志"""
    logger = _get_logger()
    if logger:
        logger.warning(f"[Update] {msg}")


def _log_error(msg: str, exc: Exception = None):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        if exc:
            logger.exception(f"[Update] {msg}", exc)
        else:
            logger.error(f"[Update] {msg}")


class UpdateManager(QObject):
    """
    升级管理器 - 协调整个升级流程
    
    主要职责：
    1. 检查更新
    2. 显示更新对话框
    3. 管理忽略版本列表
    4. 启动升级流程
    """
    
    # 信号定义
    update_available = pyqtSignal(dict)      # 发现新版本
    update_ignored = pyqtSignal(str)          # 用户忽略当前版本
    update_cancelled = pyqtSignal()           # 用户取消升级
    update_started = pyqtSignal()             # 开始升级
    update_error = pyqtSignal(str)            # 升级错误
    check_completed = pyqtSignal(dict)        # 检查完成（用于设置页面显示状态）
    check_failed = pyqtSignal(str)            # 检查失败（用于设置页面显示状态）
    
    def __init__(self, parent=None):
        """
        初始化升级管理器
        
        参数:
            parent: 父对象
        """
        super().__init__(parent)
        self._checker = UpdateChecker()
        self._update_info: Optional[Dict] = None
        self._dialog: Optional[UpdateDialog] = None
        self._main_window_loaded = False  # 主窗口是否已加载
        self._pending_update_info: Optional[Dict] = None  # 待显示的更新信息
        
        # 保存最后一次检查结果（供设置页面获取）
        self._last_check_result: Optional[Dict] = None
        self._last_check_failed: Optional[str] = None
        
        # 连接检查器信号
        self._checker.check_completed.connect(self._on_check_completed)
        self._checker.check_failed.connect(self._on_check_failed)

        # 在后台线程中预加载镜像缓存
        self._preload_mirror_cache()

        # 检查并完成待处理的升级（软件重启后）
        self._check_and_complete_pending_upgrade()
    
    def _preload_mirror_cache(self):
        """
        在后台线程中预加载镜像缓存
        
        程序启动时自动运行，选择最优镜像并缓存结果
        """
        def _do_preload():
            try:
                from .mirror_selector import get_manifest_urls
                _log_info("开始预加载镜像缓存...")
                urls = get_manifest_urls(use_cache=True)
                _log_info(f"镜像缓存预加载完成，共 {len(urls)} 个地址")
            except Exception as e:
                _log_debug(f"预加载镜像缓存失败: {e}")
        
        # 在后台线程中执行
        import threading
        thread = threading.Thread(target=_do_preload, daemon=True)
        thread.start()

    def _check_and_complete_pending_upgrade(self):
        """
        检查并完成待处理的升级（软件重启后调用）
        完成以下操作：
        1. 记录升级历史
        2. 移动差异文件到 /cache/diff/
        3. 清理临时文件
        4. 显示升级成功提示
        """
        try:
            pending_file = os.path.join(config.get_update_cache_dir(), 'upgrade_pending.json')

            if not os.path.exists(pending_file):
                return

            _log_info("检测到待处理的升级，开始完成后续操作...")

            # 读取待处理状态
            with open(pending_file, 'r', encoding='utf-8') as f:
                pending_data = json.load(f)

            from_version = pending_data.get('from_version', '')
            to_version = pending_data.get('to_version', '')
            package_name = pending_data.get('package_name', '')
            affected_files = pending_data.get('affected_files', [])
            backup_path = pending_data.get('backup_path', '')

            _log_info(f"升级信息: {from_version} -> {to_version}")

            # 1. 记录升级历史
            from .update_history_manager import get_history_manager
            history_manager = get_history_manager()
            entry = history_manager.add_history_entry(
                from_version=from_version,
                to_version=to_version,
                package_name=package_name,
                affected_files=affected_files,
                backup_path=backup_path,
                success=True
            )
            _log_info(f"已记录升级历史: {entry.get('id', '')}")

            # 2. 移动所有差异文件到 /cache/diff/
            download_dir = config.get_update_cache_dir()
            diff_cache_dir = config.get_diff_cache_dir()

            # 查找并移动所有差异文件
            import shutil
            for filename in os.listdir(download_dir):
                if filename.startswith('diff_V') and filename.endswith('.json'):
                    src_path = os.path.join(download_dir, filename)
                    dst_path = os.path.join(diff_cache_dir, filename)
                    if os.path.exists(src_path) and not os.path.exists(dst_path):
                        shutil.move(src_path, dst_path)
                        _log_info(f"已移动差异文件: {filename}")

            # 3. 清理临时文件
            # 删除下载的安装包
            if package_name:
                package_path = os.path.join(download_dir, package_name)
                if os.path.exists(package_path):
                    os.remove(package_path)
                    _log_info(f"已删除安装包: {package_name}")

            # 删除解压后的安装程序（如果存在）
            installer_path = pending_data.get('installer_path', '')
            if installer_path and os.path.exists(installer_path):
                os.remove(installer_path)
                _log_info(f"已删除安装程序: {os.path.basename(installer_path)}")

            # 4. 删除待处理状态文件
            os.remove(pending_file)
            _log_info("已删除待处理状态文件")

            # 5. 显示升级成功提示（延迟显示，等待主窗口加载完成）
            def show_success_notification():
                try:
                    # 检查当前版本是否匹配升级目标版本
                    try:
                        from utils.system.app_info_manager import AppInfoManager
                        current_version = AppInfoManager.instance().get_full_version()
                    except Exception:
                        current_version = ""

                    # 只有当当前版本匹配目标版本时才显示升级成功提示
                    if current_version and current_version == to_version:
                        from ui.utils.notification_manager import NotificationManager
                        NotificationManager.instance().show_toast(
                            f"升级成功！已升级到版本 {to_version}",
                            duration=5000
                        )
                        _log_info(f"显示升级成功提示: {to_version}")
                    else:
                        _log_info(f"当前版本 {current_version} 与目标版本 {to_version} 不匹配，跳过升级成功提示")
                except Exception as e:
                    _log_error(f"显示升级成功提示失败: {e}")

            # 延迟3秒后显示提示
            QTimer.singleShot(3000, show_success_notification)

            _log_info("升级后续操作完成")

        except Exception as e:
            _log_error(f"完成待处理升级失败: {e}")
            import traceback
            _log_error(traceback.format_exc())

    def set_main_window_loaded(self, loaded: bool = True):
        """
        设置主窗口加载状态
        
        参数:
            loaded: 是否已加载
        """
        _log_debug(f"设置主窗口加载状态: {loaded}")
        self._main_window_loaded = loaded
        
        # 如果有待显示的更新信息，现在显示
        if loaded and self._pending_update_info:
            _log_info(f"显示待处理的更新信息: {self._pending_update_info.get('latest_version', '')}")
            self._show_update_dialog(self._pending_update_info)
            self._pending_update_info = None
    
    def check_update(self, silent: bool = False, force: bool = False) -> None:
        """
        检查更新
        
        参数:
            silent: 是否静默检查（不弹窗提示）
            force: 是否强制检查（忽略检查间隔）
        """
        # 获取当前版本
        current_version = self._get_current_version()
        _log_info(f"开始检查更新，当前版本: {current_version}, 静默模式: {silent}, 强制检查: {force}")
        
        # 检查是否应该跳过（检查间隔）
        if not force and not silent and not self._should_check():
            _log_debug("跳过检查，未到达检查间隔")
            return
        
        # 执行检查
        _log_debug("启动更新检查器")
        self._checker.check_for_updates(current_version)
    
    def check_update_after_load(self, delay_ms: int = 3000) -> None:
        """
        在主窗口加载后检查更新
        
        参数:
            delay_ms: 延迟时间（毫秒），默认 3 秒
        """
        _log_info(f"主窗口加载后检查更新，延迟: {delay_ms}ms")
        # 启动时的自动检查使用 force=True 跳过间隔检查
        QTimer.singleShot(delay_ms, lambda: self.check_update(silent=False, force=True))
    
    def _get_current_version(self) -> str:
        """
        获取当前版本号
        
        返回:
            当前版本号
        """
        try:
            # 尝试从 app_info_manager 获取
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from utils.system.app_info_manager import AppInfoManager
            version = AppInfoManager.instance().get_full_version()
            # 移除 V 前缀
            if version.upper().startswith('V'):
                version = version[1:]
            return version
        except Exception:
            # 回退到默认值
            return "0.0.0"
    
    def _should_check(self) -> bool:
        """
        检查是否应该执行更新检查（基于检查间隔）
        
        返回:
            是否应该检查
        """
        try:
            ignored_path = config.get_ignored_versions_path()
            if os.path.exists(ignored_path):
                with open(ignored_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    last_check = data.get('last_check_time', '')
                    if last_check:
                        from datetime import datetime, timedelta
                        last_time = datetime.fromisoformat(last_check)
                        if datetime.now() - last_time < timedelta(hours=config.CHECK_INTERVAL_HOURS):
                            return False
        except Exception:
            pass
        return True
    
    def _on_check_completed(self, result: Dict):
        """
        检查完成回调
        
        参数:
            result: 检查结果
        """
        has_update = result.get('has_update', False)
        latest_version = result.get('latest_version', '')
        
        if has_update:
            _log_info(f"检查完成，发现新版本: {latest_version}")
        else:
            _log_debug("检查完成，当前已是最新版本")
        
        # 保存检查结果（供设置页面获取）
        self._last_check_result = result
        self._last_check_failed = None
        
        # 更新最后检查时间
        self._update_check_time()
        
        # 发送检查完成信号（供设置页面使用）
        self.check_completed.emit(result)
        
        if not has_update:
            # 没有更新
            return
        
        # 检查是否被忽略（强制提示模式下不跳过）
        if not config.FORCE_SHOW_IGNORED_VERSION and self.is_version_ignored(latest_version):
            _log_info(f"版本 {latest_version} 已被忽略，不显示更新对话框")
            return
        
        # 保存更新信息
        self._update_info = result
        
        # 发送信号
        self.update_available.emit(result)
        
        # 显示更新对话框（如果主窗口已加载，否则等待）
        if self._main_window_loaded:
            _log_debug("主窗口已加载，显示更新对话框")
            self._show_update_dialog(result)
        else:
            # 保存到待显示队列
            _log_debug("主窗口未加载，保存更新信息到待显示队列")
            self._pending_update_info = result
    
    def _on_check_failed(self, error_msg: str):
        """
        检查失败回调
        
        参数:
            error_msg: 错误信息
        """
        _log_error(f"检查更新失败: {error_msg}")
        
        # 保存检查结果（供设置页面获取）
        self._last_check_result = None
        self._last_check_failed = error_msg
        
        # 发送检查失败信号（供设置页面使用）
        self.check_failed.emit(error_msg)
        self.update_error.emit(error_msg)
    
    def _show_update_dialog(self, update_info: Dict):
        """
        显示更新对话框
        
        参数:
            update_info: 更新信息
        """
        _log_debug("显示更新对话框")
        self._dialog = UpdateDialog(update_info)
        self._dialog.ignore_clicked.connect(self._on_ignore_clicked)
        self._dialog.upgrade_clicked.connect(self._on_upgrade_clicked)
        self._dialog.cancel_clicked.connect(self._on_cancel_clicked)
        self._dialog.show()
    
    def _on_ignore_clicked(self):
        """处理忽略按钮点击"""
        if self._update_info:
            version = self._update_info.get('latest_version', '')
            _log_info(f"用户忽略版本: {version}")
            self.ignore_version(version)
            self.update_ignored.emit(version)
    
    def _on_upgrade_clicked(self):
        """处理升级按钮点击"""
        target_version = self._update_info.get('latest_version', '') if self._update_info else 'unknown'
        _log_info(f"用户确认升级，目标版本: {target_version}")
        self.update_started.emit()
        
        # 关闭更新对话框
        if self._dialog:
            self._dialog.close()
            self._dialog = None
        
        # 跳转到升级页面（不启动独立进程）
        self._show_update_page()
    
    def _on_cancel_clicked(self):
        """处理取消按钮点击"""
        _log_debug("用户取消升级")
        self.update_cancelled.emit()
    
    def _show_update_page(self):
        """显示升级页面"""
        try:
            _log_debug("_show_update_page 开始执行")

            # 获取主窗口
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if not app:
                _log_error("无法获取 QApplication 实例")
                return

            # 获取主窗口（假设主窗口是应用程序的顶层窗口）
            main_window = None
            for widget in app.topLevelWidgets():
                if widget.objectName() == "MainWindow" or hasattr(widget, 'pages'):
                    main_window = widget
                    break

            if not main_window:
                _log_error("无法获取主窗口")
                return

            _log_debug(f"获取到主窗口: {main_window}")

            # 检查更新信息
            if not self._update_info:
                _log_error("没有更新信息")
                return

            _log_debug(f"更新信息: {self._update_info}")

            # 记录当前页面，以便取消时返回
            self._previous_page = None
            if hasattr(main_window, 'pages'):
                self._previous_page = main_window.pages.currentWidget()
                _log_debug(f"记录当前页面: {self._previous_page}")

            # 确保升级页面存在
            if not hasattr(main_window, '_update_page') or main_window._update_page is None:
                _log_debug("创建升级页面")
                from ui.update_page import UpdatePage
                main_window._update_page = UpdatePage()

                # 添加到页面栈
                if hasattr(main_window, 'pages'):
                    main_window.pages.addWidget(main_window._update_page)
                    _log_debug("升级页面已添加到页面栈")

            # 连接取消信号（如果尚未连接）
            try:
                main_window._update_page.update_cancelled.disconnect()
            except Exception:
                pass  # 信号未连接时会抛出异常，忽略
            main_window._update_page.update_cancelled.connect(
                lambda: self._on_update_page_cancelled(main_window)
            )

            # 准备升级信息
            update_data = {
                'current_version': self._update_info.get('current_version', ''),
                'latest_version': self._update_info.get('latest_version', ''),
                'total_size': self._update_info.get('total_size', 0),
                'upgrade_steps': self._update_info.get('upgrade_steps', [])
            }

            _log_debug(f"准备启动升级，数据: {update_data}")

            # 启动升级
            main_window._update_page.start_update(update_data)

            # 切换到升级页面
            if hasattr(main_window, 'pages'):
                main_window.pages.setCurrentWidget(main_window._update_page)
                _log_info("已跳转到升级页面")
            else:
                _log_error("主窗口没有 pages 属性")

            # 隐藏侧边栏，使升级页面占据整个窗口（仿照向导页面的行为）
            if hasattr(main_window, 'icon_toolbar'):
                main_window.icon_toolbar.hide()
                _log_debug("侧边栏已隐藏")

        except Exception as e:
            _log_error(f"显示升级页面失败: {e}")
            import traceback
            _log_error(traceback.format_exc())

    def _on_update_page_cancelled(self, main_window):
        """
        升级页面取消/返回处理

        参数:
            main_window: 主窗口
        """
        _log_info("用户取消升级，返回主界面")

        try:
            # 显示侧边栏
            if hasattr(main_window, 'icon_toolbar'):
                main_window.icon_toolbar.show()
                _log_debug("侧边栏已显示")

            # 切换回之前的页面（如果有记录）
            if hasattr(main_window, 'pages'):
                if hasattr(self, '_previous_page') and self._previous_page:
                    main_window.pages.setCurrentWidget(self._previous_page)
                    _log_debug(f"已切换回之前的页面: {self._previous_page}")
                elif hasattr(main_window, 'settings_page'):
                    main_window.pages.setCurrentWidget(main_window.settings_page)
                    _log_debug("已切换回设置页面")
                elif hasattr(main_window, 'main_page'):
                    main_window.pages.setCurrentWidget(main_window.main_page)
                    _log_debug("已切换回主页面")

            # 发送取消信号
            self.update_cancelled.emit()

        except Exception as e:
            _log_error(f"处理取消升级失败: {e}")

    def _start_update_process(self):
        """启动升级流程"""
        if not self._update_info:
            _log_error("启动升级流程失败: 没有更新信息")
            return
        
        target_version = self._update_info.get('latest_version', '')
        _log_info(f"启动升级流程，目标版本: {target_version}")
        
        # 保存升级计划
        _log_debug("保存升级计划")
        self._save_update_plan()
        
        # 启动升级启动器（独立进程）
        _log_info("启动升级启动器")
        self._launch_updater()
        
        # 注意：不再退出主程序，升级以内嵌页面形式进行
        _log_info("升级启动器已启动，主程序保持运行")
    
    def _save_update_plan(self):
        """保存升级计划到文件"""
        try:
            plan = {
                "created_at": self._get_iso_time(),
                "current_version": self._update_info.get('current_version', ''),
                "target_version": self._update_info.get('latest_version', ''),
                "total_steps": self._update_info.get('total_steps', 0),
                "packages": [],
                "main_app_path": sys.executable if getattr(sys, 'frozen', False) else sys.argv[0],
                "install_dir": get_install_dir(),
                "download_dir": config.get_update_cache_dir()
            }
            
            # 添加升级包信息
            for step in self._update_info.get('upgrade_steps', []):
                plan["packages"].append({
                    "step": step.get('step', 0),
                    "filename": step.get('package', ''),
                    "url": step.get('url', ''),
                    "size": step.get('size', 0),
                    "hash": step.get('hash', ''),
                    "is_split": step.get('is_split', False),
                    "parts": step.get('parts', [])
                })
            
            # 确保目录存在
            plan_path = config.get_update_plan_path()
            os.makedirs(os.path.dirname(plan_path), exist_ok=True)
            
            # 保存到文件
            with open(plan_path, 'w', encoding='utf-8') as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)
            
            _log_debug(f"升级计划已保存到: {plan_path}")
                
        except Exception as e:
            _log_error("保存升级计划失败", e)
    
    def _launch_updater(self):
        """启动升级启动器"""
        try:
            import subprocess
            
            # 获取项目根目录
            if getattr(sys, 'frozen', False):
                # 打包后的程序
                project_root = os.path.dirname(sys.executable)
                updater_path = os.path.join(project_root, "update_launcher.exe")
            else:
                # 开发环境
                update_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(update_dir)
                updater_path = os.path.join(update_dir, "update_launcher.py")
            
            # 获取升级计划文件路径
            plan_path = config.get_update_plan_path()
            
            # 检查计划文件是否存在
            if not os.path.exists(plan_path):
                _log_error(f"升级计划文件不存在: {plan_path}")
                return
            
            _log_debug(f"项目根目录: {project_root}")
            _log_debug(f"升级计划文件路径: {plan_path}")
            _log_debug(f"升级启动器路径: {updater_path}")
            
            # 构建命令
            if updater_path.endswith('.py'):
                cmd = [sys.executable, updater_path, "--plan", plan_path]
            else:
                cmd = [updater_path, "--plan", plan_path]
            
            # 启动独立进程
            _log_info(f"启动升级启动器进程: {' '.join(cmd)}")
            
            # 使用 CREATE_NEW_CONSOLE 创建新控制台窗口
            # 工作目录设置为项目根目录，确保 Python 路径正确
            creation_flags = subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            
            process = subprocess.Popen(
                cmd,
                cwd=project_root,
                creationflags=creation_flags
            )
            _log_info(f"升级启动器进程已启动，PID: {process.pid}")
            
        except Exception as e:
            _log_error("启动升级启动器失败", e)
    
    def _exit_main_app(self):
        """退出主程序"""
        _log_debug("正在退出主程序...")
        # 设置跳过退出确认标志
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.setProperty("skip_exit_confirm", True)
        
        # 使用 QApplication 退出
        if app:
            app.quit()
            _log_debug("主程序已退出")
        else:
            _log_warning("无法获取 QApplication 实例，退出可能失败")
    
    def _update_check_time(self):
        """更新最后检查时间"""
        try:
            ignored_path = config.get_ignored_versions_path()
            os.makedirs(os.path.dirname(ignored_path), exist_ok=True)
            
            data = {}
            if os.path.exists(ignored_path):
                with open(ignored_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            data['last_check_time'] = self._get_iso_time()
            
            with open(ignored_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception:
            pass
    
    def _get_iso_time(self) -> str:
        """获取 ISO 格式时间字符串"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_last_check_result(self) -> Optional[Dict]:
        """
        获取最后一次检查结果
        
        返回:
            检查结果字典，如果没有则返回 None
        """
        return self._last_check_result
    
    def get_last_check_failed(self) -> Optional[str]:
        """
        获取最后一次检查失败的错误信息
        
        返回:
            错误信息，如果没有则返回 None
        """
        return self._last_check_failed
    
    def ignore_version(self, version: str) -> None:
        """
        忽略指定版本
        
        参数:
            version: 要忽略的版本号
        """
        try:
            ignored_path = config.get_ignored_versions_path()
            os.makedirs(os.path.dirname(ignored_path), exist_ok=True)
            
            data = {"ignored_versions": [], "last_check_time": ""}
            if os.path.exists(ignored_path):
                with open(ignored_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    # 确保 loaded_data 是字典且包含必要的键
                    if isinstance(loaded_data, dict):
                        data["ignored_versions"] = loaded_data.get("ignored_versions", [])
                        data["last_check_time"] = loaded_data.get("last_check_time", "")
            
            if version not in data["ignored_versions"]:
                data["ignored_versions"].append(version)
                _log_info(f"已将版本 {version} 添加到忽略列表")
            
            with open(ignored_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            _log_error(f"保存忽略版本失败: {version}", e)
    
    def is_version_ignored(self, version: str) -> bool:
        """
        检查版本是否被忽略
        
        参数:
            version: 版本号
            
        返回:
            是否被忽略
        """
        try:
            ignored_path = config.get_ignored_versions_path()
            if os.path.exists(ignored_path):
                with open(ignored_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return version in data.get("ignored_versions", [])
        except Exception:
            pass
        return False
    
    def clear_ignored_versions(self) -> None:
        """清除所有忽略的版本"""
        try:
            ignored_path = config.get_ignored_versions_path()
            if os.path.exists(ignored_path):
                data = {"ignored_versions": [], "last_check_time": ""}
                with open(ignored_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _log_error("清除忽略版本失败", e)


# 全局实例
_update_manager = None


def get_update_manager() -> UpdateManager:
    """获取升级管理器全局实例"""
    global _update_manager
    if _update_manager is None:
        _update_manager = UpdateManager()
    return _update_manager
