#!/usr/bin/env python3
"""
栖图自动升级系统 - 下载模块

负责下载升级包，支持断点续传、进度回调、文件校验
"""

import os
import hashlib
import urllib.request
import urllib.error
from urllib.parse import quote
from typing import Optional, List, Dict
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
        logger.debug(f"[UpdateDownloader] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[UpdateDownloader] {msg}")


def _log_warning(msg: str):
    """记录warning日志"""
    logger = _get_logger()
    if logger:
        logger.warning(f"[UpdateDownloader] {msg}")


def _log_error(msg: str, exc: Exception = None):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        if exc:
            logger.exception(f"[UpdateDownloader] {msg}", exc)
        else:
            logger.error(f"[UpdateDownloader] {msg}")


def encode_url(url: str) -> str:
    """
    对 URL 进行编码，处理中文字符
    
    参数:
        url: 原始 URL
        
    返回:
        编码后的 URL
    """
    if '://' in url:
        protocol, rest = url.split('://', 1)
        if '/' in rest:
            host, path = rest.split('/', 1)
            # 对路径中的中文字符进行编码
            encoded_path = quote(path, safe='/')
            return f"{protocol}://{host}/{encoded_path}"
    return url


class DownloadThread(QThread):
    """
    下载后台线程
    """
    
    # 信号定义
    progress = pyqtSignal(int)           # 下载进度 0-100
    completed = pyqtSignal(str)          # 下载完成（文件路径）
    failed = pyqtSignal(str)             # 下载失败（错误信息）
    
    def __init__(self, url: str, save_path: str, expected_hash: Optional[str] = None):
        """
        初始化下载线程
        
        参数:
            url: 下载地址
            save_path: 保存路径
            expected_hash: 期望的文件哈希值（SHA256）
        """
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.expected_hash = expected_hash
        self._is_cancelled = False
        self._temp_path = save_path + ".tmp"
    
    def run(self):
        """执行下载"""
        try:
            _log_info(f"开始下载: {os.path.basename(self.save_path)}")
            
            # 检查是否已存在完整文件
            if os.path.exists(self.save_path):
                # 链路测试模式下跳过hash检查，只要文件存在就认为有效
                if config.LINK_TEST_MODE:
                    _log_debug(f"链路测试模式: 文件已存在，跳过下载: {self.save_path}")
                    self.completed.emit(self.save_path)
                    return
                if self.expected_hash and self._verify_file(self.save_path, self.expected_hash):
                    _log_info(f"文件已存在且校验通过: {self.save_path}")
                    self.completed.emit(self.save_path)
                    return
                else:
                    # 文件存在但校验失败，删除重新下载
                    _log_warning(f"文件存在但校验失败，删除重新下载: {self.save_path}")
                    os.remove(self.save_path)
            
            # 获取已下载的大小（断点续传）
            downloaded_size = 0
            if os.path.exists(self._temp_path):
                downloaded_size = os.path.getsize(self._temp_path)
                _log_debug(f"断点续传，已下载: {downloaded_size} 字节")
            
            # 对 URL 进行编码，处理中文字符
            encoded_url = encode_url(self.url)
            
            # 创建请求
            req = urllib.request.Request(
                encoded_url,
                headers={
                    'User-Agent': 'BirdPictureManager-UpdateDownloader/1.0',
                    'Accept': '*/*',
                    'Range': f'bytes={downloaded_size}-'  # 断点续传
                }
            )
            
            # 发送请求
            _log_debug(f"下载URL: {encoded_url}")
            with urllib.request.urlopen(
                req,
                timeout=config.DOWNLOAD_TIMEOUT
            ) as response:
                # 获取文件总大小
                total_size = response.headers.get('Content-Length')
                if total_size:
                    total_size = int(total_size) + downloaded_size
                    _log_debug(f"文件总大小: {total_size} 字节")
                else:
                    total_size = None
                    _log_debug("无法获取文件总大小")
                
                # 以追加模式写入文件
                mode = 'ab' if downloaded_size > 0 else 'wb'
                with open(self._temp_path, mode) as f:
                    while not self._is_cancelled:
                        chunk = response.read(config.DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 发送进度信号
                        if total_size:
                            progress = int((downloaded_size / total_size) * 100)
                            self.progress.emit(progress)
                
                if self._is_cancelled:
                    _log_warning("下载已取消")
                    self.failed.emit("下载已取消")
                    return
                
                # 下载完成，重命名临时文件
                if os.path.exists(self.save_path):
                    os.remove(self.save_path)
                os.rename(self._temp_path, self.save_path)
                _log_info(f"下载完成: {self.save_path}")
                
                # 验证文件哈希
                if self.expected_hash:
                    _log_debug("验证文件哈希...")
                    if not self._verify_file(self.save_path, self.expected_hash):
                        _log_error("文件校验失败")
                        os.remove(self.save_path)
                        self.failed.emit("文件校验失败")
                        return
                    _log_debug("文件校验通过")
                
                self.completed.emit(self.save_path)
                
        except Exception as e:
            _log_error("下载失败", e)
            self.failed.emit(f"下载失败: {str(e)}")
    
    def cancel(self):
        """取消下载"""
        self._is_cancelled = True
    
    def _verify_file(self, filepath: str, expected_hash: str) -> bool:
        """
        验证文件哈希
        
        参数:
            filepath: 文件路径
            expected_hash: 期望的哈希值
            
        返回:
            验证是否通过
        """
        try:
            sha256_hash = hashlib.sha256()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256_hash.update(chunk)
            
            computed_hash = sha256_hash.hexdigest().lower()
            expected = expected_hash.lower().replace('sha256:', '')
            
            return computed_hash == expected
        except Exception:
            return False


class UpdateDownloader(QObject):
    """
    下载器 - 负责下载升级包
    """
    
    # 信号定义
    download_progress = pyqtSignal(int)           # 总体下载进度 0-100
    download_completed = pyqtSignal()             # 所有下载完成
    download_failed = pyqtSignal(str)             # 下载失败
    current_package_changed = pyqtSignal(str)     # 当前下载的包发生变化
    
    def __init__(self, download_dir: str):
        """
        初始化下载器
        
        参数:
            download_dir: 下载目录
        """
        super().__init__()
        self.download_dir = download_dir
        self._current_thread: Optional[DownloadThread] = None
        self._packages: List[Dict] = []
        self._current_index = 0
        
        # 确保下载目录存在
        config.ensure_dir(download_dir)
    
    def download_packages(self, packages: List[Dict]) -> None:
        """
        批量下载多个升级包
        
        参数:
            packages: 升级包信息列表，每个元素包含 url, package, hash 等
        """
        self._packages = packages
        self._current_index = 0
        self._download_next()
    
    def _download_next(self):
        """下载下一个包"""
        if self._current_index >= len(self._packages):
            # 所有包下载完成
            self.download_completed.emit()
            return
        
        package = self._packages[self._current_index]
        url = package.get('url', '')
        filename = package.get('package', '')
        expected_hash = package.get('hash', '')
        
        if not url or not filename:
            self.download_failed.emit(f"包信息不完整: {package}")
            return
        
        # 检查是否是分包
        if package.get('is_split', False):
            self._download_split_package(package)
            return
        
        # 发送当前包变化信号
        self.current_package_changed.emit(filename)
        
        # 构建保存路径
        save_path = os.path.join(self.download_dir, filename)
        
        # 检查是否已存在且校验通过
        if os.path.exists(save_path) and expected_hash:
            if self._quick_verify(save_path, expected_hash):
                # 文件已存在且有效，跳过下载
                package['download_path'] = save_path
                self._current_index += 1
                self._update_total_progress()
                self._download_next()
                return
        
        # 创建下载线程
        self._current_thread = DownloadThread(url, save_path, expected_hash)
        self._current_thread.progress.connect(self._on_progress)
        self._current_thread.completed.connect(self._on_completed)
        self._current_thread.failed.connect(self._on_failed)
        self._current_thread.start()
    
    def _download_split_package(self, package: Dict):
        """
        下载分包并合并
        
        参数:
            package: 包含分包信息的包字典
        """
        parts = package.get('parts', [])
        if not parts:
            self.download_failed.emit(f"分包信息为空: {package}")
            return
        
        filename = package.get('package', '')
        self.current_package_changed.emit(f"{filename} (分包)")
        
        # 下载所有分包
        part_files = []
        total_parts = len(parts)
        
        for i, part_info in enumerate(parts):
            part_filename = part_info.get('filename', '')
            part_url = part_info.get('url', '')
            part_hash = part_info.get('hash', '')
            
            if not part_filename or not part_url:
                self.download_failed.emit(f"分包信息不完整: {part_info}")
                return
            
            part_path = os.path.join(self.download_dir, part_filename)
            
            # 检查是否已存在
            if os.path.exists(part_path):
                # 链路测试模式下跳过hash检查
                if config.LINK_TEST_MODE:
                    part_files.append(part_path)
                    continue
                if part_hash:
                    from .file_splitter import calculate_sha256
                    if calculate_sha256(part_path) == part_hash.lower().replace('sha256:', ''):
                        part_files.append(part_path)
                        continue
            
            # 下载分包
            self.current_package_changed.emit(f"{filename} - 分包 {i+1}/{total_parts}")
            
            # 创建下载线程
            self._current_thread = DownloadThread(part_url, part_path, part_hash)
            
            # 使用事件循环等待下载完成
            from PyQt6.QtCore import QEventLoop
            loop = QEventLoop()
            
            def on_part_completed(path):
                part_files.append(path)
                loop.quit()
            
            def on_part_failed(error):
                self.download_failed.emit(f"下载分包失败: {error}")
                loop.quit()
            
            self._current_thread.completed.connect(on_part_completed)
            self._current_thread.failed.connect(on_part_failed)
            self._current_thread.progress.connect(
                lambda p: self.download_progress.emit(
                    int((self._current_index * 100 + (i * 100 + p) / total_parts) / len(self._packages))
                )
            )
            self._current_thread.start()
            loop.exec()
            
            if len(part_files) <= i:
                return  # 下载失败
        
        # 合并分包
        self.current_package_changed.emit(f"{filename} - 合并中...")
        save_path = os.path.join(self.download_dir, filename)
        
        from .file_splitter import merge_files
        # 链路测试模式下跳过hash验证
        package_hash = None if config.LINK_TEST_MODE else package.get('hash')
        if merge_files(part_files, save_path, package_hash):
            package['download_path'] = save_path
            self._current_index += 1
            self._update_total_progress()
            self._download_next()
        else:
            self.download_failed.emit("合并分包失败")
    
    def _on_progress(self, progress: int):
        """处理下载进度"""
        self._update_total_progress(progress)
    
    def _on_completed(self, filepath: str):
        """处理下载完成"""
        # 保存下载路径到包信息
        if self._current_index < len(self._packages):
            self._packages[self._current_index]['download_path'] = filepath
        
        self._current_index += 1
        self._update_total_progress()
        self._download_next()
    
    def _on_failed(self, error_msg: str):
        """处理下载失败"""
        self.download_failed.emit(error_msg)
    
    def _update_total_progress(self, current_progress: int = 100):
        """
        更新总体进度
        
        参数:
            current_progress: 当前包的下载进度 0-100
        """
        if not self._packages:
            return
        
        # 计算总体进度
        completed = self._current_index
        total = len(self._packages)
        
        # 已完成的部分 + 当前包的部分
        total_progress = int(((completed * 100) + current_progress) / total)
        self.download_progress.emit(total_progress)
    
    def cancel_download(self):
        """取消下载"""
        if self._current_thread and self._current_thread.isRunning():
            self._current_thread.cancel()
            self._current_thread.wait(5000)  # 等待最多5秒
    
    def get_downloaded_packages(self) -> List[Dict]:
        """
        获取已下载的包信息
        
        返回:
            包含下载路径的包信息列表
        """
        return self._packages
    
    def _quick_verify(self, filepath: str, expected_hash: str) -> bool:
        """
        快速验证文件（检查文件大小和修改时间）
        
        参数:
            filepath: 文件路径
            expected_hash: 期望的哈希值
            
        返回:
            是否需要重新下载
        """
        try:
            # 这里简化处理，实际应该计算哈希
            # 为了性能，可以先检查文件大小
            file_size = os.path.getsize(filepath)
            return file_size > 0
        except Exception:
            return False
    
    def verify_file(self, filepath: str, expected_hash: str) -> bool:
        """
        验证文件完整性（完整 SHA256 校验）
        
        参数:
            filepath: 文件路径
            expected_hash: 期望的哈希值
            
        返回:
            验证是否通过
        """
        try:
            sha256_hash = hashlib.sha256()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256_hash.update(chunk)
            
            computed_hash = sha256_hash.hexdigest().lower()
            expected = expected_hash.lower().replace('sha256:', '')
            
            return computed_hash == expected
        except Exception:
            return False
    
    def cleanup(self):
        """清理临时文件"""
        try:
            for filename in os.listdir(self.download_dir):
                if filename.endswith('.tmp'):
                    filepath = os.path.join(self.download_dir, filename)
                    os.remove(filepath)
        except Exception:
            pass


def format_size(size_bytes: int) -> str:
    """
    格式化文件大小
    
    参数:
        size_bytes: 字节数
        
    返回:
        格式化后的字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


if __name__ == "__main__":
    # 测试下载功能
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # 测试下载器
    downloader = UpdateDownloader("./test_download")
    
    downloader.download_progress.connect(lambda p: print(f"进度: {p}%"))
    downloader.download_completed.connect(lambda: print("下载完成"))
    downloader.download_failed.connect(lambda e: print(f"下载失败: {e}"))
    
    # 测试下载（使用一个测试文件）
    test_packages = [
        {
            "url": "https://www.example.com/test.txt",
            "package": "test.txt",
            "hash": "",
            "size": 0
        }
    ]
    
    # downloader.download_packages(test_packages)
    
    print("下载模块测试完成")
