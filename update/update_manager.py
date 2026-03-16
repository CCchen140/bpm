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
        
        # 检查是否被忽略
        if self.is_version_ignored(latest_version):
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
        self._start_update_process()
    
    def _on_cancel_clicked(self):
        """处理取消按钮点击"""
        _log_debug("用户取消升级")
        self.update_cancelled.emit()
    
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
        
        # 退出主程序
        _log_info("退出主程序以完成升级")
        self._exit_main_app()
    
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
            
            # 获取升级启动器路径
            if getattr(sys, 'frozen', False):
                # 打包后的程序
                base_dir = os.path.dirname(sys.executable)
                updater_path = os.path.join(base_dir, "update_launcher.exe")
            else:
                # 开发环境
                base_dir = os.path.dirname(os.path.abspath(__file__))
                updater_path = os.path.join(base_dir, "update_launcher.py")
            
            # 构建命令
            if updater_path.endswith('.py'):
                cmd = [sys.executable, updater_path]
            else:
                cmd = [updater_path]
            
            # 启动独立进程
            _log_debug(f"启动升级启动器进程: {' '.join(cmd)}")
            subprocess.Popen(
                cmd,
                cwd=os.path.dirname(updater_path),
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            )
            _log_info("升级启动器进程已启动")
            
        except Exception as e:
            _log_error("启动升级启动器失败", e)
    
    def _exit_main_app(self):
        """退出主程序"""
        _log_debug("正在退出主程序...")
        # 使用 QApplication 退出
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
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
                    data = json.load(f)
            
            if version not in data.get("ignored_versions", []):
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
            print(f"清除忽略版本失败: {e}")


# 全局实例
_update_manager = None


def get_update_manager() -> UpdateManager:
    """获取升级管理器全局实例"""
    global _update_manager
    if _update_manager is None:
        _update_manager = UpdateManager()
    return _update_manager
