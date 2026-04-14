#!/usr/bin/env python3
"""
栖图自动升级系统 - 安装模块

负责安装升级包，支持增量更新和完整包安装
"""

import os
import shutil
import subprocess
import sys
from typing import List, Optional
from PyQt6.QtCore import QObject, pyqtSignal, QThread

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
        logger.debug(f"[UpdateInstaller] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[UpdateInstaller] {msg}")


def _log_warning(msg: str):
    """记录warning日志"""
    logger = _get_logger()
    if logger:
        logger.warning(f"[UpdateInstaller] {msg}")


def _log_error(msg: str, exc: Exception = None):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        if exc:
            logger.exception(f"[UpdateInstaller] {msg}", exc)
        else:
            logger.error(f"[UpdateInstaller] {msg}")


class InstallThread(QThread):
    """
    安装后台线程
    """

    # 信号定义
    progress = pyqtSignal(int, str)   # 安装进度 (百分比, 描述)
    completed = pyqtSignal(list)      # 安装完成（返回受影响的文件列表）
    failed = pyqtSignal(str)          # 安装失败 (错误信息)

    def __init__(self, package_paths: List[str], install_dir: str):
        """
        初始化安装线程

        参数:
            package_paths: 升级包路径列表
            install_dir: 安装目录
        """
        super().__init__()
        self.package_paths = package_paths
        self.install_dir = install_dir
        self._is_cancelled = False
        self._affected_files: List[str] = []  # 记录受影响的文件
    
    def run(self):
        """执行安装"""
        try:
            total = len(self.package_paths)
            self._affected_files = []  # 重置受影响的文件列表
            
            _log_info(f"开始安装，共 {total} 个升级包")

            for i, package_path in enumerate(self.package_paths):
                if self._is_cancelled:
                    _log_warning("安装已取消")
                    self.failed.emit("安装已取消")
                    return

                # 发送进度信号
                progress = int((i / total) * 100)
                package_name = os.path.basename(package_path)
                self.progress.emit(progress, f"正在安装 {package_name}...")
                _log_info(f"正在安装升级包 ({i+1}/{total}): {package_name}")

                # 执行安装
                affected = self._install_package_with_tracking(package_path)
                if affected is None:
                    _log_error(f"安装失败: {package_name}")
                    self.failed.emit(f"安装失败: {package_name}")
                    return

                # 记录受影响的文件
                self._affected_files.extend(affected)
                _log_debug(f"升级包 {package_name} 安装完成，影响 {len(affected)} 个文件")

            # 安装完成，返回受影响的文件列表（去重）
            self._affected_files = list(set(self._affected_files))
            _log_info(f"安装完成，共影响 {len(self._affected_files)} 个文件")
            self.progress.emit(100, "安装完成")
            self.completed.emit(self._affected_files)

        except Exception as e:
            _log_error("安装时发生错误", e)
            self.failed.emit(f"安装时发生错误: {str(e)}")
    
    def _install_package_with_tracking(self, package_path: str) -> Optional[List[str]]:
        """
        安装单个升级包并追踪受影响的文件

        参数:
            package_path: 升级包路径

        返回:
            受影响的文件列表，失败返回 None
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(package_path):
                _log_error(f"升级包不存在: {package_path}")
                return None

            # 获取文件扩展名
            _, ext = os.path.splitext(package_path)
            _log_debug(f"升级包类型: {ext}")

            affected_files: List[str] = []

            if ext.lower() == '.exe':
                # 执行安装程序（无法追踪具体文件）
                _log_info("执行安装程序")
                if self._run_installer(package_path):
                    affected_files.append(os.path.basename(package_path))
                    return affected_files
                return None
            elif ext.lower() in ['.zip', '.7z', '.rar']:
                # 解压压缩包并追踪文件
                _log_info("解压压缩包")
                return self._extract_package_with_tracking(package_path)
            else:
                # 其他类型
                _log_info("应用增量更新")
                if self._apply_delta_update(package_path):
                    affected_files.append(os.path.basename(package_path))
                    return affected_files
                return None

        except Exception as e:
            _log_error("安装包失败", e)
            return None

    def _install_package(self, package_path: str) -> bool:
        """
        安装单个升级包（不追踪文件，兼容旧版本）

        参数:
            package_path: 升级包路径

        返回:
            安装是否成功
        """
        result = self._install_package_with_tracking(package_path)
        return result is not None
    
    def _run_installer(self, installer_path: str) -> bool:
        """
        运行安装程序
        
        参数:
            installer_path: 安装程序路径
            
        返回:
            运行是否成功
        """
        try:
            # 静默安装参数
            # Inno Setup: /SILENT 或 /VERYSILENT
            # NSIS: /S
            # MSI: /qn
            
            # 先尝试检测安装程序类型
            args = [installer_path]
            
            # 尝试静默安装
            silent_args = [
                ['/SILENT'],           # Inno Setup
                ['/VERYSILENT'],       # Inno Setup (更静默)
                ['/S'],                # NSIS
                ['/qn'],               # MSI
            ]
            
            for silent in silent_args:
                try:
                    process = subprocess.Popen(
                        [installer_path] + silent,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=False,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    
                    # 等待安装完成（设置超时）
                    return_code = process.wait(timeout=300)  # 5分钟超时
                    
                    if return_code == 0:
                        return True
                        
                except subprocess.TimeoutExpired:
                    # 超时，尝试下一个参数
                    continue
                except Exception:
                    continue
            
            # 如果静默安装都失败，尝试普通安装
            process = subprocess.Popen(
                [installer_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            return_code = process.wait(timeout=600)  # 10分钟超时
            return return_code == 0
            
        except Exception as e:
            _log_error("运行安装程序失败", e)
            return False
    
    def _extract_package_with_tracking(self, package_path: str) -> Optional[List[str]]:
        """
        解压升级包并追踪受影响的文件

        参数:
            package_path: 升级包路径

        返回:
            受影响的文件列表，失败返回 None
        """
        try:
            affected_files: List[str] = []

            # 创建临时解压目录
            temp_dir = os.path.join(config.CACHE_DIR, "extract_temp")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)

            # 解压文件
            _, ext = os.path.splitext(package_path)

            if ext.lower() == '.zip':
                with zipfile.ZipFile(package_path, 'r') as zf:
                    # 获取所有文件列表
                    all_files = zf.namelist()
                    zf.extractall(temp_dir)
            else:
                # 其他压缩格式，使用外部工具
                import subprocess
                if ext.lower() == '.7z':
                    subprocess.run(['7z', 'x', package_path, f'-o{temp_dir}'], check=True)
                elif ext.lower() == '.rar':
                    subprocess.run(['unrar', 'x', package_path, temp_dir], check=True)
                # 对于外部工具，需要手动遍历目录获取文件列表
                all_files = []
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        rel_path = os.path.relpath(os.path.join(root, file), temp_dir)
                        all_files.append(rel_path)

            # 复制文件到安装目录并记录受影响的文件
            for item in os.listdir(temp_dir):
                src = os.path.join(temp_dir, item)
                dst = os.path.join(self.install_dir, item)

                if os.path.isdir(src):
                    # 记录目录中的所有文件
                    for root, dirs, files in os.walk(src):
                        for file in files:
                            rel_path = os.path.relpath(os.path.join(root, file), temp_dir)
                            affected_files.append(rel_path)

                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    # 记录单个文件
                    affected_files.append(item)
                    shutil.copy2(src, dst)

            # 清理临时目录
            shutil.rmtree(temp_dir)

            return affected_files

        except Exception as e:
            _log_error("解压升级包失败", e)
            return None

    def _extract_package(self, package_path: str) -> bool:
        """
        解压压缩包并应用增量更新（不追踪文件，兼容旧版本）
        
        参数:
            package_path: 压缩包路径
            
        返回:
            解压是否成功
        """
        try:
            import zipfile
            import tempfile
            
            if not package_path.endswith('.zip'):
                _log_error(f"不支持的压缩格式: {package_path}")
                return False
            
            # 创建临时目录解压
            with tempfile.TemporaryDirectory() as temp_dir:
                # 解压到临时目录
                with zipfile.ZipFile(package_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # 应用增量更新
                return self._apply_delta_update(temp_dir)
                
        except Exception as e:
            _log_error("解压失败", e)
            return False
    
    def _apply_delta_update(self, delta_path: str) -> bool:
        """
        应用增量更新
        
        处理逻辑：
        1. 复制所有新文件（新增和修改）到安装目录
        2. 删除 _delete_files.txt 中列出的文件
        
        参数:
            delta_path: 增量文件目录
            
        返回:
            应用是否成功
        """
        try:
            if not os.path.isdir(delta_path):
                _log_error(f"增量更新路径不是目录: {delta_path}")
                return False
            
            # 第一步：处理删除列表
            delete_list_path = os.path.join(delta_path, "_delete_files.txt")
            if os.path.exists(delete_list_path):
                _log_info("处理删除文件列表...")
                with open(delete_list_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        # 跳过注释和空行
                        if not line or line.startswith('#'):
                            continue

                        # 构建目标文件路径
                        file_to_delete = os.path.join(self.install_dir, line)
                        if os.path.exists(file_to_delete):
                            try:
                                os.remove(file_to_delete)
                                _log_debug(f"[DELETE] {line}")
                            except Exception as e:
                                _log_warning(f"无法删除 {line}: {e}")
                        else:
                            _log_debug(f"[SKIP] 文件不存在: {line}")
            
            # 第二步：复制新文件
            _log_info("复制新文件...")
            copied_count = 0
            for root, dirs, files in os.walk(delta_path):
                for file in files:
                    # 跳过特殊文件（但保留Python模块文件，如__init__.py和_pynput相关文件）
                    if file.startswith('_') and not (file.startswith('__') or 'pynput' in file.lower()):
                        continue

                    src_path = os.path.join(root, file)
                    # 计算相对路径（使用正斜杠统一路径分隔符）
                    rel_path = os.path.relpath(src_path, delta_path).replace("\\", "/")
                    dst_path = os.path.join(self.install_dir, rel_path)

                    # 确保目标目录存在
                    dst_dir = os.path.dirname(dst_path)
                    os.makedirs(dst_dir, exist_ok=True)

                    # 复制文件
                    try:
                        shutil.copy2(src_path, dst_path)
                        copied_count += 1
                        _log_debug(f"[COPY] {rel_path}")
                    except Exception as e:
                        _log_error(f"无法复制 {rel_path}: {e}")
                        return False

            _log_info(f"增量更新完成，共复制 {copied_count} 个文件")
            return True
                
        except Exception as e:
            _log_error("应用增量更新失败", e)
            return False
    
    def cancel(self):
        """取消安装"""
        self._is_cancelled = True


class UpdateInstaller(QObject):
    """
    安装器 - 负责安装升级包
    """

    # 信号定义
    install_progress = pyqtSignal(int, str)   # 安装进度 (百分比, 描述)
    install_completed = pyqtSignal(list)      # 安装完成（返回受影响的文件列表）
    install_failed = pyqtSignal(str)          # 安装失败

    def __init__(self, install_dir: str):
        """
        初始化安装器

        参数:
            install_dir: 安装目录
        """
        super().__init__()
        self.install_dir = install_dir
        self._install_thread: Optional[InstallThread] = None
        self._affected_files: List[str] = []

    def install_packages(self, package_paths: List[str]) -> None:
        """
        按顺序安装多个升级包

        参数:
            package_paths: 升级包路径列表
        """
        if not package_paths:
            self.install_failed.emit("没有要安装的包")
            return

        # 检查安装目录
        if not os.path.exists(self.install_dir):
            try:
                os.makedirs(self.install_dir, exist_ok=True)
            except Exception as e:
                self.install_failed.emit(f"无法创建安装目录: {e}")
                return

        # 检查写入权限
        if not self._check_write_permission():
            self.install_failed.emit("没有安装目录的写入权限")
            return

        # 创建安装线程
        self._install_thread = InstallThread(package_paths, self.install_dir)
        self._install_thread.progress.connect(self.install_progress)
        self._install_thread.completed.connect(self._on_install_completed)
        self._install_thread.failed.connect(self.install_failed)
        self._install_thread.start()

    def _on_install_completed(self, affected_files: List[str]):
        """
        安装完成回调

        参数:
            affected_files: 受影响的文件列表
        """
        self._affected_files = affected_files
        self.install_completed.emit(affected_files)
    
    def install_package(self, package_path: str) -> None:
        """
        安装单个升级包
        
        参数:
            package_path: 升级包路径
        """
        self.install_packages([package_path])
    
    def _check_write_permission(self) -> bool:
        """
        检查安装目录的写入权限
        
        返回:
            是否有写入权限
        """
        try:
            test_file = os.path.join(self.install_dir, ".write_test")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            return True
        except Exception:
            return False
    
    def cancel_install(self):
        """取消安装"""
        if self._install_thread and self._install_thread.isRunning():
            self._install_thread.cancel()
            self._install_thread.wait(5000)  # 等待最多5秒
    
    def is_installing(self) -> bool:
        """
        检查是否正在安装
        
        返回:
            是否正在安装
        """
        return self._install_thread is not None and self._install_thread.isRunning()


def get_install_dir() -> str:
    """
    获取安装目录
    
    返回:
        安装目录路径
    """
    # 如果是打包后的程序，使用可执行文件所在目录
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    
    # 开发环境，使用当前工作目录
    return os.getcwd()


def restart_application(app_path: str) -> bool:
    """
    重启应用程序
    
    参数:
        app_path: 应用程序路径
        
    返回:
        重启是否成功
    """
    try:
        subprocess.Popen(
            [app_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except Exception as e:
        _log_error("重启应用失败", e)
        return False


if __name__ == "__main__":
    # 测试安装功能
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 测试安装器
    installer = UpdateInstaller("./test_install")
    
    installer.install_progress.connect(lambda p, d: print(f"进度: {p}%, {d}"))
    installer.install_completed.connect(lambda files: print(f"安装完成，受影响文件: {len(files)} 个"))
    installer.install_failed.connect(lambda e: print(f"安装失败: {e}"))
    
    print("安装模块测试完成")
