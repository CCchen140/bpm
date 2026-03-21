#!/usr/bin/env python3
"""
栖图自动升级系统 - 升级页面

以内嵌页面形式显示升级进度，替代独立的升级启动器
UI 设计完全仿照向导页面，适配主题色
"""

import os
import sys
from typing import Optional, Dict, List
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont, QLinearGradient, QColor, QPainter

from ui.utils.icon_loader import qta
from ui.utils.color_manager import ColorManager
from ui.utils.notification_manager import NotificationManager


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
        logger.debug(f"[UpdatePage] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[UpdatePage] {msg}")


def _log_warning(msg: str):
    """记录warning日志"""
    logger = _get_logger()
    if logger:
        logger.warning(f"[UpdatePage] {msg}")


def _log_error(msg: str, exc: Exception = None):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        if exc:
            logger.exception(f"[UpdatePage] {msg}", exc)
        else:
            logger.error(f"[UpdatePage] {msg}")


class UpdateWorker(QThread):
    """升级工作线程"""
    download_progress = pyqtSignal(int)
    install_progress = pyqtSignal(int, str)
    status_changed = pyqtSignal(str)
    current_file_changed = pyqtSignal(str)
    phase_changed = pyqtSignal(str)
    download_completed = pyqtSignal()
    download_failed = pyqtSignal(str)
    install_completed = pyqtSignal()
    install_failed = pyqtSignal(str)

    def __init__(self, update_info: Dict):
        super().__init__()
        self._update_info = update_info
        self._is_cancelled = False
        self._downloader = None
        self._installer_path = None  # 安装程序路径

    def run(self):
        """执行升级"""
        try:
            # 第一步：下载
            self.phase_changed.emit("下载")
            if not self._download_packages():
                return

            if self._is_cancelled:
                return

            # 第二步：安装
            self.phase_changed.emit("安装")
            if not self._install_packages():
                return

            self.install_completed.emit()

        except Exception as e:
            self.install_failed.emit(str(e))

    def _get_diff_cache_dir(self) -> str:
        """
        获取差异文件清单缓存目录

        返回:
            差异清单缓存目录路径 (/cache/diff/)，与下载目录分开，避免被误删除
        """
        from update import update_config as config
        return config.get_diff_cache_dir()

    def _download_diff_manifests(self, packages: List[Dict], download_dir: str):
        """
        下载差异文件清单到 /cache/update/ 目录（临时存放，安装完成后移动到 /cache/diff/）

        参数:
            packages: 升级包列表
            download_dir: 下载目录（/cache/update/）
        """
        import urllib.request
        import os
        from update import update_config as config

        self.status_changed.emit(f"正在下载差异文件清单到: {download_dir}")

        for pkg in packages:
            if self._is_cancelled:
                return

            from_version = pkg.get('from', '')
            to_version = pkg.get('to', '')

            if not from_version or not to_version:
                continue

            # 构建差异清单文件名
            diff_filename = f"diff_V{from_version}_to_V{to_version}.json"

            # 构建下载 URL
            tag = pkg.get('tag', '')
            if not tag and to_version:
                tag = to_version if to_version.startswith('v') else f"v{to_version}"

            if not tag:
                continue

            diff_url = f"https://github.com/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/download/{tag}/{diff_filename}"
            # 先下载到 /cache/update/ 目录
            diff_save_path = os.path.join(download_dir, diff_filename)

            # 检查文件是否已存在（在 /cache/update/ 或 /cache/diff/）
            diff_cache_path = os.path.join(self._get_diff_cache_dir(), diff_filename)
            if os.path.exists(diff_save_path) or os.path.exists(diff_cache_path):
                self.status_changed.emit(f"差异清单已存在: {diff_filename}")
                continue

            # 下载差异清单
            try:
                self.status_changed.emit(f"下载差异清单: {diff_filename}")
                req = urllib.request.Request(
                    diff_url,
                    headers={
                        'User-Agent': 'BirdPictureManager-UpdateDownloader/1.0',
                        'Accept': 'application/json'
                    }
                )

                with urllib.request.urlopen(req, timeout=10) as response:
                    with open(diff_save_path, 'wb') as f:
                        f.write(response.read())

                self.status_changed.emit(f"差异清单下载成功: {diff_filename}")

            except Exception as e:
                # 差异清单下载失败不影响升级流程，继续执行
                self.status_changed.emit(f"差异清单下载失败（可忽略）: {diff_filename}")
                continue

    def _download_packages(self) -> bool:
        """下载升级包 - 使用同步方式"""
        try:
            from update import update_config as config
            import urllib.request
            import os

            packages = self._update_info.get('upgrade_steps', [])
            self.status_changed.emit(f"需要下载 {len(packages)} 个包")

            if not packages:
                self.status_changed.emit("没有需要下载的包")
                return True

            download_dir = config.get_update_cache_dir()
            os.makedirs(download_dir, exist_ok=True)
            self.status_changed.emit(f"下载目录: {download_dir}")

            # 首先下载差异文件清单
            self._download_diff_manifests(packages, download_dir)

            total_packages = len(packages)

            for i, pkg in enumerate(packages):
                if self._is_cancelled:
                    self.status_changed.emit("下载已取消")
                    return False

                url = pkg.get('url', '')
                filename = pkg.get('package', '')
                expected_hash = pkg.get('hash', '')

                # 如果 URL 为空，自动生成 GitHub Release 下载 URL
                if not url and filename:
                    from update import update_config as config
                    # 获取目标版本号
                    to_version = pkg.get('to', '')
                    # 尝试从 upgrade_step 获取 tag
                    tag = pkg.get('tag', '')
                    if tag:
                        # 使用 manifest 中定义的 tag
                        url = f"https://github.com/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/download/{tag}/{filename}"
                        # 仅在非打包版本显示完整URL
                        if not getattr(sys, 'frozen', False):
                            self.status_changed.emit(f"自动生成 URL (使用tag): {url}")
                    elif to_version:
                        # 没有 tag，使用版本号生成，GitHub Release 的 tag 通常以 'v' 开头
                        tag = to_version if to_version.startswith('v') else f"v{to_version}"
                        url = f"https://github.com/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/download/{tag}/{filename}"
                        # 仅在非打包版本显示完整URL
                        if not getattr(sys, 'frozen', False):
                            self.status_changed.emit(f"自动生成 URL (使用版本号): {url}")
                    else:
                        self.status_changed.emit("警告: 无法获取 tag 或版本号")

                # 仅在非打包版本显示URL前缀
                if not getattr(sys, 'frozen', False):
                    self.status_changed.emit(f"包 {i+1}/{total_packages}: URL={url[:50] if url else '空'}..., 文件名={filename}")
                else:
                    self.status_changed.emit(f"包 {i+1}/{total_packages}: 文件名={filename}")

                if not url:
                    error_msg = f"错误: 包 {i+1} 的URL为空且无法自动生成"
                    self.status_changed.emit(error_msg)
                    self.download_failed.emit(error_msg)
                    return False

                if not filename:
                    error_msg = f"错误: 包 {i+1} 的文件名为空"
                    self.status_changed.emit(error_msg)
                    self.download_failed.emit(error_msg)
                    return False

                self.current_file_changed.emit(f"正在下载: {filename} ({i+1}/{total_packages})")

                save_path = os.path.join(download_dir, filename)
                self.status_changed.emit(f"保存路径: {save_path}")

                # 检查文件是否已存在
                if os.path.exists(save_path):
                    file_size = os.path.getsize(save_path)
                    self.status_changed.emit(f"文件已存在，跳过下载: {filename} (大小: {file_size} 字节)")
                    continue

                # 同步下载文件
                try:
                    self.status_changed.emit(f"开始下载: {filename}")

                    # 创建请求
                    req = urllib.request.Request(
                        url,
                        headers={
                            'User-Agent': 'BirdPictureManager-UpdateDownloader/1.0',
                            'Accept': '*/*'
                        }
                    )

                    # 仅在非打包版本显示请求URL
                    if not getattr(sys, 'frozen', False):
                        self.status_changed.emit(f"发送请求到: {url[:60]}...")

                    # 下载文件
                    with urllib.request.urlopen(req, timeout=config.DOWNLOAD_TIMEOUT) as response:
                        self.status_changed.emit(f"服务器响应: {response.status}")

                        total_size = response.headers.get('Content-Length')
                        if total_size:
                            total_size = int(total_size)
                            self.status_changed.emit(f"文件总大小: {total_size} 字节")
                        else:
                            self.status_changed.emit("无法获取文件总大小")

                        downloaded_size = 0
                        last_progress = 0
                        chunk_count = 0

                        with open(save_path, 'wb') as f:
                            self.status_changed.emit(f"开始写入文件: {save_path}")

                            while not self._is_cancelled:
                                chunk = response.read(config.DOWNLOAD_CHUNK_SIZE)
                                if not chunk:
                                    break

                                f.write(chunk)
                                downloaded_size += len(chunk)
                                chunk_count += 1

                                # 每100个块输出一次日志
                                if chunk_count % 100 == 0:
                                    self.status_changed.emit(f"已下载 {downloaded_size} 字节 ({chunk_count} 块)")

                                # 计算并发送进度
                                if total_size:
                                    progress = int((downloaded_size / total_size) * 100)
                                    if progress != last_progress:
                                        self.download_progress.emit(progress)
                                        last_progress = progress
                                else:
                                    # 无法获取总大小时，每1MB增加5%进度
                                    if downloaded_size % (1024 * 1024) < config.DOWNLOAD_CHUNK_SIZE:
                                        last_progress = min(last_progress + 5, 99)
                                        self.download_progress.emit(last_progress)

                    if self._is_cancelled:
                        self.status_changed.emit("下载已取消，删除未完成文件")
                        # 删除未完成的文件
                        if os.path.exists(save_path):
                            os.remove(save_path)
                        return False

                    # 验证文件
                    if os.path.exists(save_path):
                        final_size = os.path.getsize(save_path)
                        self.status_changed.emit(f"下载完成: {filename} (最终大小: {final_size} 字节)")
                    else:
                        self.status_changed.emit(f"错误: 文件未找到: {save_path}")
                        return False

                except Exception as e:
                    error_msg = f"下载失败 {filename}: {str(e)}"
                    self.status_changed.emit(error_msg)
                    self.download_failed.emit(error_msg)
                    return False

            self.status_changed.emit(f"所有 {total_packages} 个包下载完成")
            self.download_completed.emit()
            self.download_progress.emit(100)
            return True

        except Exception as e:
            error_msg = f"下载过程异常: {str(e)}"
            self.status_changed.emit(error_msg)
            self.download_failed.emit(error_msg)
            return False

    def _install_packages(self) -> bool:
        """安装升级包 - 解压zip包并准备启动安装程序"""
        try:
            self.status_changed.emit("正在解压升级包...")

            import zipfile
            import time

            packages = self._update_info.get('upgrade_steps', [])
            if not packages:
                self.status_changed.emit("没有需要解压的包")
                return True

            from update import update_config as config
            from update.update_history_manager import get_history_manager
            download_dir = config.get_update_cache_dir()
            app_dir = config.get_app_dir()

            # 检查是否为链路测试模式
            is_test_mode = config.LINK_TEST_MODE

            if is_test_mode:
                # 链路测试模式：不创建增量备份
                self.status_changed.emit("链路测试模式：跳过增量备份")
                affected_files = []
            else:
                # 正常模式：在解压前创建增量备份
                self.status_changed.emit("正在分析升级包内容...")
                affected_files = self._analyze_upgrade_packages(packages, download_dir)
                self.status_changed.emit(f"将影响 {len(affected_files)} 个文件")

                # 创建增量备份
                if affected_files:
                    self.status_changed.emit("正在创建增量备份...")
                    history_manager = get_history_manager()
                    backup_path = history_manager.create_backup(app_dir, affected_files)
                    if backup_path:
                        self.status_changed.emit(f"备份已创建: {os.path.basename(backup_path)}")
                        # 保存备份信息到升级信息中
                        self._update_info['backup_path'] = backup_path
                        self._update_info['affected_files'] = affected_files
                    else:
                        self.status_changed.emit("警告: 备份创建失败，继续升级...")
                else:
                    self.status_changed.emit("没有需要备份的文件，跳过备份...")
                    self._update_info['backup_path'] = ''
                    self._update_info['affected_files'] = []

            # 解压所有包
            total_packages = len(packages)
            for i, pkg in enumerate(packages):
                if self._is_cancelled:
                    return False

                filename = pkg.get('package', '')
                if not filename:
                    continue

                zip_path = os.path.join(download_dir, filename)
                if not os.path.exists(zip_path):
                    self.status_changed.emit(f"错误: 找不到文件 {filename}")
                    self.install_failed.emit(f"找不到文件: {filename}")
                    return False

                self.status_changed.emit(f"正在解压 {filename} ({i+1}/{total_packages})...")

                # 解压zip包
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        # 解压到下载目录
                        zip_ref.extractall(download_dir)
                        self.status_changed.emit(f"已解压 {filename}")

                    # 查找解压后的安装包（.exe文件）
                    # 只在还没有找到安装程序时查找
                    if not self._installer_path:
                        extracted_files = os.listdir(download_dir)
                        self.status_changed.emit(f"解压后文件列表: {extracted_files}")
                        installer_files = [f for f in extracted_files if f.endswith('.exe')]
                        self.status_changed.emit(f"找到exe文件: {installer_files}")

                        if installer_files:
                            self._installer_path = os.path.join(download_dir, installer_files[0])
                            self.status_changed.emit(f"设置安装程序路径: {self._installer_path}")
                            # 验证文件是否存在
                            if os.path.exists(self._installer_path):
                                self.status_changed.emit(f"找到安装程序: {installer_files[0]}")
                            else:
                                self.status_changed.emit(f"警告: 安装程序路径不存在: {self._installer_path}")
                                self._installer_path = None
                        else:
                            self.status_changed.emit(f"警告: 未找到安装程序")
                    else:
                        self.status_changed.emit(f"已找到安装程序，跳过查找: {self._installer_path}")

                except Exception as e:
                    self.status_changed.emit(f"解压失败: {str(e)}")
                    self.install_failed.emit(f"解压失败: {str(e)}")
                    return False

                # 更新进度
                progress = int(((i + 1) / total_packages) * 100)
                self.install_progress.emit(progress, f"正在解压 {filename}...")
                time.sleep(0.1)

            self.status_changed.emit(f"解压完成，安装程序路径: {self._installer_path}")
            return True

        except Exception as e:
            self.install_failed.emit(str(e))
            return False

    def _analyze_upgrade_packages(self, packages: List[Dict], download_dir: str) -> List[str]:
        """
        分析升级包内容，获取将被影响的文件列表

        支持三种方式（按优先级排序）：
        1. 从 /cache/diff/ 目录读取下载的差异文件清单（推荐，用于回退）
        2. 从升级包中的 affected_files.json 读取
        3. 自动分析 zip 包内容（兼容旧版本）

        参数:
            packages: 升级包列表
            download_dir: 下载目录（/cache/update/）

        返回:
            将被影响的文件列表（相对于应用目录的相对路径）
        """
        import zipfile
        import os
        import json
        from update import update_config as config

        app_dir = config.get_app_dir()
        affected_files = []

        # 获取差异清单缓存目录
        diff_cache_dir = self._get_diff_cache_dir()

        for pkg in packages:
            filename = pkg.get('package', '')
            if not filename:
                continue

            zip_path = os.path.join(download_dir, filename)
            if not os.path.exists(zip_path):
                continue

            # 获取版本信息
            from_version = pkg.get('from', '')
            to_version = pkg.get('to', '')

            # 尝试从 /cache/update/ 或 /cache/diff/ 目录读取差异文件清单
            diff_manifest_loaded = False
            try:
                if from_version and to_version:
                    diff_manifest_name = f"diff_V{from_version}_to_V{to_version}.json"

                    # 首先尝试从 /cache/update/ 读取（下载的临时位置）
                    diff_manifest_path = os.path.join(download_dir, diff_manifest_name)
                    if not os.path.exists(diff_manifest_path):
                        # 如果没有，尝试从 /cache/diff/ 读取（已安装的位置）
                        diff_manifest_path = os.path.join(diff_cache_dir, diff_manifest_name)

                    if os.path.exists(diff_manifest_path):
                        with open(diff_manifest_path, 'r', encoding='utf-8') as f:
                            diff_manifest = json.load(f)
                            files_from_diff = diff_manifest.get('affected_files', [])
                            affected_files.extend(files_from_diff)
                            self.status_changed.emit(f"从差异清单读取到 {len(files_from_diff)} 个受影响文件")
                            diff_manifest_loaded = True
                            continue  # 成功读取差异清单，跳过后续分析
            except Exception as e:
                self.status_changed.emit(f"读取差异清单失败: {e}，尝试其他方式...")

            # 如果差异清单加载失败，尝试从升级包中读取
            if not diff_manifest_loaded:
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        # 尝试从 affected_files.json 读取
                        manifest_name = 'affected_files.json'
                        if manifest_name in zip_ref.namelist():
                            try:
                                manifest_content = zip_ref.read(manifest_name)
                                manifest = json.loads(manifest_content.decode('utf-8'))
                                files_from_manifest = manifest.get('affected_files', [])
                                affected_files.extend(files_from_manifest)
                                self.status_changed.emit(f"从升级包清单读取到 {len(files_from_manifest)} 个受影响文件")
                                continue  # 成功读取清单，跳过自动分析
                            except Exception as e:
                                self.status_changed.emit(f"读取升级包清单失败: {e}，尝试自动分析...")

                        # 自动分析 zip 包内容（兼容旧版本）
                        self.status_changed.emit(f"自动分析升级包: {filename}")
                        for item in zip_ref.namelist():
                            # 跳过目录和清单文件
                            if item.endswith('/') or item == manifest_name:
                                continue

                            # 跳过安装包本身（exe文件）
                            if item.endswith('.exe'):
                                continue

                            # 检查文件是否已存在于当前程序目录
                            target_path = os.path.join(app_dir, item)
                            if os.path.exists(target_path):
                                # 文件将被覆盖，加入备份列表
                                affected_files.append(item)

                except Exception as e:
                    _log_error(f"分析升级包失败 {filename}: {e}")
                    continue

        # 去重
        affected_files = list(set(affected_files))
        return affected_files

    def cancel(self):
        """取消升级"""
        self._is_cancelled = True
        if self._downloader:
            self._downloader.cancel_download()


class UpdatePage(QWidget):
    """升级页面 - 完全仿照向导页面设计"""

    update_completed = pyqtSignal()  # 升级完成信号
    update_cancelled = pyqtSignal()  # 升级取消信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updatePageRoot")
        self._update_info: Optional[Dict] = None
        self._worker: Optional[UpdateWorker] = None

        # 初始化背景渐变颜色
        self._bg_top_color = QColor("#E3F2FD")
        self._bg_bottom_color = QColor("#FFFFFF")

        self._setup_ui()
        self._apply_background()

    def _apply_background(self):
        """
        刷新升级页背景渐变的颜色参数。
        使用与向导页面相同的渐变背景：从主题侧边栏颜色渐变到白色
        """
        cm = ColorManager.instance()
        top_color = cm.get("theme.sidebar", "#E3F2FD")
        bottom_color = "#FFFFFF"
        try:
            self._bg_top_color = QColor(str(top_color))
        except Exception:
            self._bg_top_color = QColor("#E3F2FD")
        try:
            self._bg_bottom_color = QColor(str(bottom_color))
        except Exception:
            self._bg_bottom_color = QColor("#FFFFFF")
        self.update()

    def paintEvent(self, event):
        """
        绘制整页的背景渐变。
        采用 paintEvent 绘制是为了保证在任何样式表/主题切换/控件覆盖场景下，
        背景依然稳定显示，不会退化成纯白。
        """
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, self._bg_top_color)
            gradient.setColorAt(1.0, self._bg_bottom_color)
            painter.fillRect(self.rect(), gradient)
        except Exception:
            pass
        super().paintEvent(event)

    def _setup_ui(self):
        """设置UI界面 - 完全仿照向导页面设计"""
        cm = ColorManager.instance()

        # 注册主题变化监听
        try:
            ColorManager.instance().register_listener(self._apply_background)
        except Exception:
            pass

        # 主布局 - 与向导页面一致
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 居中容器（限制最大宽度）- 与向导页面一致
        center_container = QWidget()
        center_container.setFixedWidth(800)
        # 让中间容器背景透明，显示父级渐变
        center_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        center_container.setAutoFillBackground(False)
        center_container.setStyleSheet("background: transparent;")

        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 40, 0, 40)
        center_layout.setSpacing(20)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 图标 - 与向导页面一致
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_icon("mdi6.update")
        center_layout.addWidget(self.icon_label)

        # 标题 - 与向导页面一致
        title_color = cm.get("theme.text.dark")
        self.title_label = QLabel("正在升级")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(f"""
            font-size: 28px;
            font-weight: bold;
            color: {title_color};
            font-family: "Microsoft YaHei";
            background: transparent;
        """)
        center_layout.addWidget(self.title_label)

        # 副标题 - 显示版本信息 - 与向导页面描述文字样式一致
        desc_color = cm.get("theme.text.dark")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet(f"""
            font-size: 16px;
            color: {desc_color};
            line-height: 24px;
            background: transparent;
        """)
        center_layout.addWidget(self.subtitle_label)

        # 进度区域 - 仿照向导页面的进度条区域样式
        progress_container = QWidget()
        progress_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        progress_container.setAutoFillBackground(False)
        progress_container.setStyleSheet("background: transparent;")
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setSpacing(10)
        progress_layout.setContentsMargins(40, 20, 40, 20)
        progress_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 阶段标签
        self.phase_label = QLabel("准备中...")
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet(f"""
            font-size: 16px;
            color: {title_color};
            background: transparent;
        """)
        progress_layout.addWidget(self.phase_label)

        # 当前文件标签
        self.current_file_label = QLabel("")
        self.current_file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_file_label.setStyleSheet(f"""
            font-size: 13px;
            color: {cm.get("theme.text.secondary")};
            background: transparent;
        """)
        progress_layout.addWidget(self.current_file_label)

        # 下载进度条 - 仿照向导页面样式（细条，无文字）
        self.download_progress_label = QLabel("下载进度")
        self.download_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.download_progress_label.setStyleSheet(f"color: {title_color}; font-size: 13px; background: transparent;")
        progress_layout.addWidget(self.download_progress_label)

        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setRange(0, 100)
        self.download_progress_bar.setValue(0)
        self.download_progress_bar.setTextVisible(False)
        self.download_progress_bar.setFixedHeight(6)
        self._style_progress_bar(self.download_progress_bar)
        progress_layout.addWidget(self.download_progress_bar)

        # 安装进度条 - 仿照向导页面样式（细条，无文字）
        self.install_progress_label = QLabel("安装进度")
        self.install_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.install_progress_label.setStyleSheet(f"color: {title_color}; font-size: 13px; background: transparent;")
        progress_layout.addWidget(self.install_progress_label)

        self.install_progress_bar = QProgressBar()
        self.install_progress_bar.setRange(0, 100)
        self.install_progress_bar.setValue(0)
        self.install_progress_bar.setTextVisible(False)
        self.install_progress_bar.setFixedHeight(6)
        self._style_progress_bar(self.install_progress_bar)
        progress_layout.addWidget(self.install_progress_bar)

        # 状态标签
        self.status_label = QLabel("准备开始升级...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(f"""
            font-size: 13px;
            color: {cm.get("theme.text.secondary")};
            background: transparent;
        """)
        progress_layout.addWidget(self.status_label)

        center_layout.addWidget(progress_container)

        # 按钮区域 - 仿照向导页面导航栏样式，只保留一个取消按钮
        nav_bar = QHBoxLayout()
        nav_bar.setContentsMargins(40, 20, 40, 20)

        # 左侧占位（用于平衡右侧按钮，使中间内容居中）
        left_container = QWidget()
        left_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        left_container.setStyleSheet("background: transparent;")
        nav_bar.addWidget(left_container, 1)

        # 中间按钮容器
        center_btn_widget = QWidget()
        center_btn_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        center_btn_widget.setStyleSheet("background: transparent;")
        center_btn_layout = QHBoxLayout(center_btn_widget)
        center_btn_layout.setContentsMargins(0, 0, 0, 0)
        center_btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 取消按钮 - 仿照向导页面上一步按钮样式
        prev_bg = cm.to_qss_color("guide.nav.prev.background")
        prev_hover_bg = cm.to_qss_color("guide.nav.prev.hover_background")
        prev_text = cm.get("theme.text.dark")
        prev_border = cm.get("popup.border.primary")

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {prev_bg};
                color: {prev_text};
                border: 1px solid {prev_border};
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {prev_hover_bg};
            }}
        """)
        self.cancel_btn.clicked.connect(self._on_cancel)
        center_btn_layout.addWidget(self.cancel_btn)

        nav_bar.addWidget(center_btn_widget, 0, Qt.AlignmentFlag.AlignCenter)

        # 右侧占位（与左侧平衡）
        right_container = QWidget()
        right_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        right_container.setStyleSheet("background: transparent;")
        nav_bar.addWidget(right_container, 1)

        center_layout.addLayout(nav_bar)

        # 日志区域 - 放在底部，使用现代风格滚动条
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setPlaceholderText("升级日志...")
        log_bg = cm.get("theme.popup")
        log_border = cm.get("popup.border.primary")
        log_text_color = cm.get("theme.text.dark")
        scrollbar_bg = cm.get("theme.background.light")
        scrollbar_handle = cm.get("popup.border.primary")
        scrollbar_handle_hover = cm.get("theme.primary")
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {log_bg};
                border: 1px solid {log_border};
                border-radius: 4px;
                padding: 10px;
                color: {log_text_color};
                font-family: "Consolas", "Microsoft YaHei";
                font-size: 12px;
            }}
            /* 垂直滚动条 - 现代风格 */
            QScrollBar:vertical {{
                background-color: {scrollbar_bg};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {scrollbar_handle};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {scrollbar_handle_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            /* 水平滚动条 - 现代风格 */
            QScrollBar:horizontal {{
                background-color: {scrollbar_bg};
                height: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {scrollbar_handle};
                min-width: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {scrollbar_handle_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """)
        center_layout.addWidget(self.log_text)

        # 添加弹簧使内容水平居中
        main_layout.addStretch()
        main_layout.addWidget(center_container, 0, Qt.AlignmentFlag.AlignHCenter)
        main_layout.addStretch()

    def resizeEvent(self, event):
        """窗口大小改变时刷新背景"""
        self._apply_background()
        super().resizeEvent(event)

    def _set_icon(self, icon_name: str):
        """设置图标 - 与向导页面一致"""
        icon_color = ColorManager.instance().get("theme.text.dark")
        icon_pixmap = qta.icon(icon_name, color=icon_color).pixmap(128, 128)
        self.icon_label.setPixmap(icon_pixmap)

    def _style_progress_bar(self, progress_bar: QProgressBar):
        """设置进度条样式 - 仿照向导页面"""
        cm = ColorManager.instance()
        progress_bg = cm.get("theme.popup")
        progress_chunk = cm.get("theme.primary")
        progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {progress_bg};
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {progress_chunk};
                border-radius: 3px;
            }}
        """)

    def start_update(self, update_info: Dict):
        """开始升级"""
        self._update_info = update_info

        # 更新标题
        current_version = update_info.get('current_version', '')
        target_version = update_info.get('latest_version', '')
        self.subtitle_label.setText(f"从 {current_version} 升级到 {target_version}")

        # 重置进度
        self.download_progress_bar.setValue(0)
        self.install_progress_bar.setValue(0)
        self.cancel_btn.setText("取消")
        self.cancel_btn.setEnabled(True)

        # 启动工作线程
        self._worker = UpdateWorker(update_info)
        self._worker.download_progress.connect(self._on_download_progress)
        self._worker.install_progress.connect(self._on_install_progress)
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.current_file_changed.connect(self._on_current_file_changed)
        self._worker.phase_changed.connect(self._on_phase_changed)
        self._worker.download_completed.connect(self._on_download_completed)
        self._worker.download_failed.connect(self._on_download_failed)
        self._worker.install_completed.connect(self._on_install_completed)
        self._worker.install_failed.connect(self._on_install_failed)
        self._worker.start()

        self._log("升级开始")

    def _on_download_progress(self, progress: int):
        """下载进度更新"""
        self.download_progress_bar.setValue(progress)

    def _on_install_progress(self, progress: int, message: str):
        """安装进度更新"""
        self.install_progress_bar.setValue(progress)
        self.status_label.setText(message)

    def _on_status_changed(self, status: str):
        """状态更新"""
        self.status_label.setText(status)
        self._log(status)

    def _on_current_file_changed(self, filename: str):
        """当前文件更新"""
        self.current_file_label.setText(filename)
        self._log(filename)

    def _on_phase_changed(self, phase: str):
        """阶段更新"""
        self.phase_label.setText(phase)
        self._log(f"进入阶段: {phase}")

    def _on_download_completed(self):
        """下载完成"""
        self._log("下载完成")

    def _on_download_failed(self, error: str):
        """下载失败"""
        self._log(f"下载失败: {error}")
        self.status_label.setText(f"下载失败: {error}")
        self.cancel_btn.setText("返回")
        self.cancel_btn.setEnabled(True)
        NotificationManager.instance().show_toast(f"下载失败: {error}", duration=5000)

    def _save_upgrade_pending(self):
        """
        保存升级待处理状态到临时文件
        软件重启后会检查此文件并完成升级后续操作
        """
        try:
            from update import update_config as config
            import json

            pending_file = os.path.join(config.get_update_cache_dir(), 'upgrade_pending.json')
            download_dir = config.get_update_cache_dir()

            # 查找安装程序路径
            # 首先尝试从 worker 获取已记录的安装程序路径
            installer_path = ''
            if self._worker and self._worker._installer_path:
                installer_path = self._worker._installer_path
                self._log(f"从 worker 获取安装程序路径: {installer_path}")

            # 如果 worker 中没有，则从下载目录扫描
            if not installer_path and os.path.isdir(download_dir):
                exe_files = [f for f in os.listdir(download_dir) if f.endswith('.exe')]
                if exe_files:
                    installer_path = os.path.join(download_dir, exe_files[0])
                    self._log(f"从下载目录扫描获取安装程序路径: {installer_path}")

            pending_data = {
                'status': 'pending',
                'timestamp': datetime.now().isoformat(),
                'from_version': self._update_info.get('current_version', ''),
                'to_version': self._update_info.get('latest_version', ''),
                'package_name': self._update_info.get('upgrade_steps', [{}])[0].get('package', ''),
                'affected_files': self._update_info.get('affected_files', []),
                'backup_path': self._update_info.get('backup_path', ''),
                'installer_path': installer_path
            }

            with open(pending_file, 'w', encoding='utf-8') as f:
                json.dump(pending_data, f, ensure_ascii=False, indent=2)

            self._log(f"已保存升级待处理状态: {pending_file}")
            self._log(f"安装程序路径: {installer_path}")
            return True
        except Exception as e:
            self._log(f"保存升级待处理状态失败: {e}")
            return False

    def _on_install_completed(self):
        """安装完成"""
        self._log("解压完成")
        self.phase_label.setText("完成")
        self.title_label.setText("准备安装")
        self._set_icon("mdi6.check-circle")

        # 检查是否处于链路测试模式
        from update import update_config as config
        if config.LINK_TEST_MODE:
            # 链路测试模式：不启动安装包，显示测试完成信息
            self.status_label.setText("链路测试完成！已下载并解压测试包")
            self._log("链路测试模式：跳过启动安装程序")
            # 显示返回按钮
            self.cancel_btn.setText("返回")
            self.cancel_btn.setEnabled(True)
            NotificationManager.instance().show_toast("链路测试完成！", duration=3000)
        else:
            # 正常模式：保存升级待处理状态，然后启动安装程序
            # 软件重启后会完成记录历史和移动差异文件的操作
            self.status_label.setText("解压完成！正在准备安装...")
            self._log("保存升级待处理状态")

            # 保存升级待处理状态
            self._save_upgrade_pending()

            # 启动安装程序
            self.status_label.setText("解压完成！正在启动安装程序...")
            # 隐藏取消按钮，直接自动启动安装程序
            self.cancel_btn.setVisible(False)
            NotificationManager.instance().show_toast("解压完成！正在启动安装程序...", duration=3000)
            # 延迟3秒后自动启动安装程序并退出
            QTimer.singleShot(3000, self._launch_installer_and_exit)

    def _record_upgrade_history(self, success: bool = True, error_msg: str = ""):
        """
        记录升级历史

        参数:
            success: 是否成功
            error_msg: 错误信息
        """
        try:
            from update.update_history_manager import get_history_manager

            history_manager = get_history_manager()

            # 获取升级信息
            from_version = self._update_info.get('current_version', '')
            to_version = self._update_info.get('latest_version', '')
            packages = self._update_info.get('upgrade_steps', [])
            package_name = packages[0].get('package', '') if packages else ''
            backup_path = self._update_info.get('backup_path', '')
            affected_files = self._update_info.get('affected_files', [])

            # 添加历史记录
            entry = history_manager.add_history_entry(
                from_version=from_version,
                to_version=to_version,
                package_name=package_name,
                affected_files=affected_files,
                backup_path=backup_path,
                success=success,
                error_msg=error_msg
            )

            self._log(f"升级历史已记录: {entry.get('id', '')}")

        except Exception as e:
            self._log(f"记录升级历史失败: {e}")

    def _on_install_failed(self, error: str):
        """安装失败"""
        self._log(f"安装失败: {error}")
        self.status_label.setText(f"安装失败: {error}")
        self.cancel_btn.setText("返回")
        self.cancel_btn.setEnabled(True)
        NotificationManager.instance().show_toast(f"安装失败: {error}", duration=5000)

    def _on_cancel(self):
        """取消按钮点击"""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(1000)
        self.update_cancelled.emit()

    def _launch_installer_and_exit(self):
        """启动安装程序并退出当前程序"""
        self._log("正在启动安装程序...")

        try:
            import subprocess
            import shutil

            # 设置跳过退出确认标志，避免显示"是否退出栖图"弹窗
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app:
                app.setProperty("skip_exit_confirm", True)

            # 获取安装程序路径
            # 首先尝试从_update_info中获取（从upgrade_pending.json读取）
            installer_path = self._update_info.get('installer_path', '')
            self._log(f"从_update_info获取安装程序路径: {installer_path}")

            # 如果路径为空或不存在，从下载目录查找
            if not installer_path or not os.path.exists(installer_path):
                from update import update_config as config
                download_dir = config.get_update_cache_dir()
                self._log(f"从下载目录查找: {download_dir}")

                if os.path.isdir(download_dir):
                    exe_files = [f for f in os.listdir(download_dir) if f.endswith('.exe')]
                    self._log(f"找到exe文件: {exe_files}")
                    if exe_files:
                        installer_path = os.path.join(download_dir, exe_files[0])
                        self._log(f"使用找到的安装程序: {installer_path}")

            if not installer_path:
                self._log(f"错误: 安装程序路径为空")
                from update import update_config as config
                download_dir = config.get_update_cache_dir()
                # 获取下载目录中的所有文件列表
                all_files = []
                if os.path.isdir(download_dir):
                    try:
                        all_files = os.listdir(download_dir)
                    except Exception as e:
                        all_files = [f"无法读取目录: {e}"]
                else:
                    all_files = ["目录不存在"]
                self.status_label.setText(f"错误: 找不到安装程序\n下载目录: {download_dir}\n目录内容: {all_files}")
                return

            if not os.path.exists(installer_path):
                self._log(f"错误: 安装程序文件不存在: {installer_path}")
                from update import update_config as config
                download_dir = config.get_update_cache_dir()
                # 获取下载目录中的所有文件列表
                all_files = []
                if os.path.isdir(download_dir):
                    try:
                        all_files = os.listdir(download_dir)
                    except Exception as e:
                        all_files = [f"无法读取目录: {e}"]
                else:
                    all_files = ["目录不存在"]
                self.status_label.setText(f"错误: 找不到安装程序\n期望路径: {installer_path}\n下载目录: {download_dir}\n目录内容: {all_files}")
                return

            # 直接启动安装程序，不显示弹窗
            to_version = self._update_info.get('latest_version', '')
            self._log(f"解压完成，直接启动安装程序: {installer_path}")

            # 启动安装程序（静默安装模式，/SILENT 表示静默安装）
            subprocess.Popen([installer_path, '/SILENT'])

            self._log("安装程序已启动")

            # 清理下载的安装包和临时文件（不重复记录历史）
            self._cleanup_downloaded_files(record_history=False)

            self._log("已清理临时文件，退出当前程序")

            # 使用 os._exit 立即退出，不触发 closeEvent，避免显示确认弹窗
            os._exit(0)

        except Exception as e:
            self._log(f"启动安装程序失败: {e}")
            self.status_label.setText(f"启动安装程序失败: {e}，请手动安装")

    def _move_diff_manifests_to_cache(self, packages: List[Dict], download_dir: str):
        """
        将差异文件从 /cache/update/ 移动到 /cache/diff/

        参数:
            packages: 升级包列表
            download_dir: 下载目录（/cache/update/）
        """
        try:
            diff_cache_dir = self._get_diff_cache_dir()
            self._log(f"正在移动差异文件到: {diff_cache_dir}")

            for pkg in packages:
                from_version = pkg.get('from', '')
                to_version = pkg.get('to', '')

                if not from_version or not to_version:
                    continue

                diff_filename = f"diff_V{from_version}_to_V{to_version}.json"
                src_path = os.path.join(download_dir, diff_filename)
                dst_path = os.path.join(diff_cache_dir, diff_filename)

                if os.path.exists(src_path) and not os.path.exists(dst_path):
                    import shutil
                    shutil.move(src_path, dst_path)
                    self._log(f"已移动差异文件: {diff_filename}")

        except Exception as e:
            self._log(f"移动差异文件时出错: {e}")

    def _cleanup_downloaded_files(self, record_history: bool = True):
        """
        清理下载的安装包和临时文件

        参数:
            record_history: 是否记录升级历史（默认True）
            注意：历史记录现在由程序重启后的 update_manager.py 统一记录，
                  此参数保留用于兼容性，但不再在下载页面记录历史
        """
        try:
            from update import update_config as config
            import shutil

            download_dir = config.get_update_cache_dir()
            packages = self._update_info.get('upgrade_steps', [])

            # 注意：历史记录现在由程序重启后的 update_manager.py 统一记录
            # 不再在下载阶段记录历史，避免下载未完成就有历史记录的问题

            # 将差异文件移动到 /cache/diff/
            self._move_diff_manifests_to_cache(packages, download_dir)

            # 3. 删除下载的安装包文件
            self._log(f"清理下载目录: {download_dir}")
            for pkg in packages:
                filename = pkg.get('package', '')
                if filename:
                    file_path = os.path.join(download_dir, filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        self._log(f"已删除: {filename}")

            # 4. 删除解压后的安装程序
            # 从 _update_info 获取安装程序路径（由 _save_upgrade_pending 保存）
            installer_path = self._update_info.get('installer_path', '')
            if installer_path and os.path.exists(installer_path):
                os.remove(installer_path)
                self._log(f"已删除安装程序: {os.path.basename(installer_path)}")

            self._log("清理完成")

        except Exception as e:
            self._log(f"清理文件时出错: {e}")

    def _log(self, message: str):
        """添加日志"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
