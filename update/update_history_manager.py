#!/usr/bin/env python3
"""
栖图自动升级系统 - 升级历史记录管理器

管理升级历史记录
"""

import os
import json
import zipfile
from datetime import datetime
from typing import List, Dict, Optional
from PyQt6.QtCore import QObject

from . import update_config as config


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
        logger.debug(f"[UpdateHistory] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[UpdateHistory] {msg}")


def _log_warning(msg: str):
    """记录warning日志"""
    logger = _get_logger()
    if logger:
        logger.warning(f"[UpdateHistory] {msg}")


def _log_error(msg: str, exc: Exception = None):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        if exc:
            logger.exception(f"[UpdateHistory] {msg}", exc)
        else:
            logger.error(f"[UpdateHistory] {msg}")


class UpdateHistoryManager(QObject):
    """
    升级历史记录管理器
    
    功能：
    1. 记录每次升级的详细信息
    2. 在升级前创建备份
    """
    
    def __init__(self):
        super().__init__()
        self._ensure_history_dir()
    
    def _ensure_history_dir(self):
        """确保历史记录目录存在"""
        os.makedirs(config.HISTORY_DIR, exist_ok=True)
    
    def _get_history_file_path(self) -> str:
        """获取历史记录文件路径"""
        return os.path.join(config.HISTORY_DIR, "update_history.json")
    
    def load_history(self) -> List[Dict]:
        """
        加载升级历史记录
        
        返回:
            历史记录列表，按时间倒序排列
        """
        history_file = self._get_history_file_path()
        if not os.path.exists(history_file):
            return []
        
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            _log_error("加载升级历史失败", e)
            return []
    
    def save_history(self, history: List[Dict]):
        """
        保存升级历史记录
        
        参数:
            history: 历史记录列表
        """
        history_file = self._get_history_file_path()
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _log_error("保存升级历史失败", e)
    
    def add_history_entry(
        self,
        from_version: str,
        to_version: str,
        package_name: str,
        affected_files: List[str] = None,
        backup_path: str = "",
        success: bool = True,
        error_msg: str = ""
    ) -> Dict:
        """
        添加升级历史记录
        
        参数:
            from_version: 升级前版本
            to_version: 升级后版本
            package_name: 升级包名称
            affected_files: 受影响的文件列表
            backup_path: 备份文件路径
            success: 是否成功
            error_msg: 错误信息（如果失败）
            
        返回:
            添加的历史记录项
        """
        entry = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S"),
            "timestamp": datetime.now().isoformat(),
            "from_version": from_version,
            "to_version": to_version,
            "package_name": package_name,
            "affected_files": affected_files or [],
            "backup_path": backup_path,
            "success": success,
            "error_msg": error_msg
        }
        
        history = self.load_history()
        history.insert(0, entry)  # 添加到开头（最新的在前）
        
        # 限制历史记录数量
        max_entries = 50
        if len(history) > max_entries:
            # 删除旧记录的同时清理备份文件
            for old_entry in history[max_entries:]:
                if old_entry.get("backup_path"):
                    try:
                        if os.path.exists(old_entry["backup_path"]):
                            os.remove(old_entry["backup_path"])
                    except Exception:
                        pass
            history = history[:max_entries]
        
        self.save_history(history)
        return entry
    
    def create_backup(self, app_dir: str, affected_files: List[str] = None) -> str:
        """
        创建应用备份（只备份受影响的文件）
        
        参数:
            app_dir: 应用目录
            affected_files: 受影响的文件列表（相对路径），如果为None或空列表则不创建备份
            
        返回:
            备份文件路径，如果没有需要备份的文件则返回空字符串
        """
        # 如果没有需要备份的文件，直接返回空字符串
        if not affected_files:
            _log_info("没有需要备份的文件，跳过备份创建")
            return ""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.zip"
        backup_path = os.path.join(config.BACKUP_DIR, backup_filename)
        
        # 确保备份目录存在
        os.makedirs(config.BACKUP_DIR, exist_ok=True)
        
        # 创建备份
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 只备份受影响的文件
                for rel_path in affected_files:
                    file_path = os.path.join(app_dir, rel_path)
                    if os.path.exists(file_path):
                        zf.write(file_path, rel_path)
            
            return backup_path
        except Exception as e:
            _log_error("创建备份失败", e)
            return ""
    
    def delete_history_entry(self, entry_id: str) -> bool:
        """
        删除历史记录项
        
        参数:
            entry_id: 历史记录项ID
            
        返回:
            是否删除成功
        """
        history = self.load_history()
        for i, entry in enumerate(history):
            if entry.get("id") == entry_id:
                # 删除备份文件
                backup_path = entry.get("backup_path", "")
                if backup_path and os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                    except Exception as e:
                        _log_error("删除备份文件失败", e)
                
                # 从历史记录中移除
                history.pop(i)
                self.save_history(history)
                return True
        return False
    
    def get_latest_successful_update(self) -> Optional[Dict]:
        """
        获取最近一次成功的升级记录
        
        返回:
            历史记录项，如果没有则返回 None
        """
        history = self.load_history()
        for entry in history:
            if entry.get("success", False):
                return entry
        return None
    
    def cleanup_old_backups(self, keep_count: int = 10):
        """
        清理旧的备份文件

        参数:
            keep_count: 保留的备份数量
        """
        if not os.path.exists(config.BACKUP_DIR):
            return

        try:
            # 获取所有备份文件
            backups = []
            for filename in os.listdir(config.BACKUP_DIR):
                if filename.startswith("backup_") and filename.endswith(".zip"):
                    filepath = os.path.join(config.BACKUP_DIR, filename)
                    backups.append({
                        "path": filepath,
                        "mtime": os.path.getmtime(filepath)
                    })

            # 按修改时间排序
            backups.sort(key=lambda x: x["mtime"], reverse=True)

            # 删除旧的备份
            for backup in backups[keep_count:]:
                try:
                    os.remove(backup["path"])
                except Exception:
                    pass
        except Exception as e:
            _log_error("清理旧备份失败", e)

    def clear_all_history(self) -> bool:
        """
        清除全部历史记录

        返回:
            是否清除成功
        """
        try:
            history = self.load_history()

            # 删除所有备份文件
            for entry in history:
                backup_path = entry.get("backup_path", "")
                if backup_path and os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                    except Exception:
                        pass

            # 清空历史记录
            self.save_history([])
            return True
        except Exception as e:
            _log_error("清除全部历史记录失败", e)
            return False


# 全局实例
_history_manager = None


def get_history_manager() -> UpdateHistoryManager:
    """获取升级历史记录管理器全局实例"""
    global _history_manager
    if _history_manager is None:
        _history_manager = UpdateHistoryManager()
    return _history_manager
