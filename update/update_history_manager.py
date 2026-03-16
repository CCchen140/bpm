#!/usr/bin/env python3
"""
栖图自动升级系统 - 升级历史记录管理器

管理升级历史记录，支持查看和回滚操作
"""

import os
import json
import shutil
import zipfile
from datetime import datetime
from typing import List, Dict, Optional
from PyQt6.QtCore import QObject, pyqtSignal

from . import update_config as config


class UpdateHistoryManager(QObject):
    """
    升级历史记录管理器
    
    功能：
    1. 记录每次升级的详细信息
    2. 在升级前创建备份
    3. 支持回滚到之前的版本
    """
    
    # 信号定义
    rollback_started = pyqtSignal(str)  # 开始回滚（目标版本）
    rollback_progress = pyqtSignal(int, str)  # 回滚进度（百分比，描述）
    rollback_completed = pyqtSignal(str)  # 回滚完成（版本号）
    rollback_failed = pyqtSignal(str)  # 回滚失败（错误信息）
    
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
            print(f"加载升级历史失败: {e}")
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
            print(f"保存升级历史失败: {e}")
    
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
            affected_files: 受影响的文件列表（用于回滚）
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
            "error_msg": error_msg,
            "can_rollback": bool(backup_path) and os.path.exists(backup_path)
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
            affected_files: 受影响的文件列表（相对路径），如果为None则备份所有文件
            
        返回:
            备份文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.zip"
        backup_path = os.path.join(config.BACKUP_DIR, backup_filename)
        
        # 确保备份目录存在
        os.makedirs(config.BACKUP_DIR, exist_ok=True)
        
        # 创建备份
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                if affected_files:
                    # 只备份受影响的文件
                    for rel_path in affected_files:
                        file_path = os.path.join(app_dir, rel_path)
                        if os.path.exists(file_path):
                            zf.write(file_path, rel_path)
                else:
                    # 备份所有文件（兼容旧版本）
                    for root, dirs, files in os.walk(app_dir):
                        # 跳过缓存和数据目录
                        dirs[:] = [d for d in dirs if d.lower() not in ('cache', 'data', '__pycache__')]
                        
                        for file in files:
                            # 跳过临时文件
                            if file.endswith(('.tmp', '.temp', '.log')):
                                continue
                            
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, app_dir)
                            zf.write(file_path, arcname)
            
            return backup_path
        except Exception as e:
            print(f"创建备份失败: {e}")
            return ""
    
    def rollback(self, entry_id: str) -> bool:
        """
        回滚到指定版本
        
        参数:
            entry_id: 历史记录项ID
            
        返回:
            回滚是否成功
        """
        history = self.load_history()
        entry = None
        for h in history:
            if h.get("id") == entry_id:
                entry = h
                break
        
        if not entry:
            self.rollback_failed.emit("未找到指定的历史记录")
            return False
        
        backup_path = entry.get("backup_path", "")
        if not backup_path or not os.path.exists(backup_path):
            self.rollback_failed.emit("备份文件不存在或已被删除")
            return False
        
        to_version = entry.get("from_version", "")
        self.rollback_started.emit(to_version)
        
        try:
            # 获取应用目录
            app_dir = config.get_app_dir()
            
            # 创建临时目录用于解压
            temp_dir = os.path.join(config.CACHE_DIR, f"rollback_{entry_id}")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)
            
            self.rollback_progress.emit(10, "正在解压备份...")
            
            # 解压备份
            with zipfile.ZipFile(backup_path, 'r') as zf:
                zf.extractall(temp_dir)
            
            self.rollback_progress.emit(30, "正在停止应用...")
            
            # 备份当前版本（以防回滚失败）
            current_backup = os.path.join(config.BACKUP_DIR, f"pre_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
            self._quick_backup(app_dir, current_backup)
            
            self.rollback_progress.emit(50, "正在替换文件...")
            
            # 替换文件
            self._replace_files(temp_dir, app_dir)
            
            self.rollback_progress.emit(80, "正在清理临时文件...")
            
            # 清理临时目录
            shutil.rmtree(temp_dir)
            
            self.rollback_progress.emit(100, "回滚完成")
            
            # 更新历史记录状态
            entry["rolled_back"] = True
            entry["rollback_time"] = datetime.now().isoformat()
            self.save_history(history)
            
            self.rollback_completed.emit(to_version)
            return True
            
        except Exception as e:
            error_msg = f"回滚失败: {str(e)}"
            self.rollback_failed.emit(error_msg)
            return False
    
    def _quick_backup(self, app_dir: str, backup_path: str):
        """
        快速备份当前版本
        
        参数:
            app_dir: 应用目录
            backup_path: 备份文件路径
        """
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(app_dir):
                    dirs[:] = [d for d in dirs if d.lower() not in ('cache', 'data', '__pycache__')]
                    for file in files:
                        if file.endswith(('.tmp', '.temp', '.log')):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, app_dir)
                        zf.write(file_path, arcname)
        except Exception as e:
            print(f"快速备份失败: {e}")
    
    def _replace_files(self, source_dir: str, target_dir: str):
        """
        替换文件
        
        参数:
            source_dir: 源目录（备份文件解压后的目录）
            target_dir: 目标目录（应用目录）
        """
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                src_path = os.path.join(root, file)
                rel_path = os.path.relpath(src_path, source_dir)
                dst_path = os.path.join(target_dir, rel_path)
                
                # 确保目标目录存在
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                
                # 复制文件
                shutil.copy2(src_path, dst_path)
    
    def can_rollback(self, entry_id: str) -> bool:
        """
        检查是否可以回滚到指定版本
        
        参数:
            entry_id: 历史记录项ID
            
        返回:
            是否可以回滚
        """
        history = self.load_history()
        for entry in history:
            if entry.get("id") == entry_id:
                backup_path = entry.get("backup_path", "")
                return bool(backup_path) and os.path.exists(backup_path)
        return False
    
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
                        print(f"删除备份文件失败: {e}")
                
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
            if entry.get("success", False) and not entry.get("rolled_back", False):
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
            print(f"清理旧备份失败: {e}")


# 全局实例
_history_manager = None


def get_history_manager() -> UpdateHistoryManager:
    """获取升级历史记录管理器全局实例"""
    global _history_manager
    if _history_manager is None:
        _history_manager = UpdateHistoryManager()
    return _history_manager
