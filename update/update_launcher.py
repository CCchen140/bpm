#!/usr/bin/env python3
"""
栖图自动升级系统 - 升级启动器

这是一个独立的程序，在主程序退出后运行
负责：
1. 显示升级进度对话框
2. 下载所有升级包
3. 按顺序安装升级包
4. 清理临时文件
5. 启动主程序

使用方法:
    python update/update_launcher.py --plan <plan_file_path>
"""

import os
import sys
import json
import argparse
import time
from typing import Optional, Dict, List

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QThread

from update import update_config as config
from update.update_downloader import UpdateDownloader, format_size
from update.update_installer import UpdateInstaller
from update.update_progress_dialog import UpdateProgressDialog
from update.update_history_manager import get_history_manager


class UpdateLauncher(QObject):
    """
    升级启动器 - 独立进程执行升级
    
    测试模式 (--test):
        开启测试模式后，升级流程会在下载和解压完成后停止，
        不会执行实际的文件替换操作，也不会清理临时文件或启动主程序。
        用于测试升级包是否正确下载和解压。
    """
    
    # 信号定义
    download_progress = pyqtSignal(int)
    install_progress = pyqtSignal(int, str)
    status_changed = pyqtSignal(str)
    current_file_changed = pyqtSignal(str)
    phase_changed = pyqtSignal(str)
    
    def __init__(self, test_mode: bool = False):
        super().__init__()
        self._plan: Optional[Dict] = None
        self._progress_dialog: Optional[UpdateProgressDialog] = None
        self._downloader: Optional[UpdateDownloader] = None
        self._installer: Optional[UpdateInstaller] = None
        self._is_cancelled = False
        self._test_mode = test_mode  # 测试模式标志
        self._affected_files: List[str] = []  # 受影响的文件列表
    
    def run(self, plan_path: str) -> int:
        """
        运行升级流程
        
        参数:
            plan_path: 升级计划文件路径
            
        返回:
            退出码
        """
        try:
            # 加载升级计划
            self._plan = self._load_update_plan(plan_path)
            if not self._plan:
                print("错误: 无法加载升级计划")
                return 1
            
            # 创建 Qt 应用
            app = QApplication(sys.argv)
            
            # 创建进度对话框
            self._progress_dialog = UpdateProgressDialog()
            self._progress_dialog.set_total_steps(self._plan.get('total_steps', 1))
            self._progress_dialog.cancel_requested.connect(self._on_cancel)
            self._progress_dialog.show()
            
            # 连接信号
            self.download_progress.connect(self._progress_dialog.set_download_progress)
            self.install_progress.connect(self._progress_dialog.set_install_progress)
            self.status_changed.connect(self._progress_dialog.set_status_text)
            self.current_file_changed.connect(self._progress_dialog.set_current_file)
            self.phase_changed.connect(self._progress_dialog.set_phase)
            
            # 执行升级
            success = self._do_update()
            
            if success:
                if self._test_mode:
                    # 测试模式：显示成功信息，不执行实际替换
                    self.status_changed.emit("测试模式：下载和解压已完成，跳过文件替换")
                    self.phase_changed.emit("测试完成")
                    print("\n" + "=" * 80)
                    print("测试模式完成！")
                    print("=" * 80)
                    print(f"升级包已下载到: {self._plan.get('download_dir', '')}")
                    print("文件替换、清理和启动主程序步骤已跳过")
                    print("=" * 80)
                    # 保持对话框显示，等待用户关闭
                    from PyQt6.QtCore import QEventLoop
                    loop = QEventLoop()
                    # 10秒后自动关闭，或用户可以手动关闭
                    import PyQt6.QtCore as QtCore
                    QtCore.QTimer.singleShot(10000, loop.quit)
                    loop.exec()
                    return 0
                else:
                    # 正常模式：记录历史、执行清理并启动主程序
                    self._record_update_history()
                    self._cleanup()
                    self._launch_main_app()
                    return 0
            else:
                return 1
                
        except Exception as e:
            print(f"升级失败: {e}")
            return 1
        finally:
            # 确保对话框关闭
            if self._progress_dialog:
                self._progress_dialog.close()
    
    def _load_update_plan(self, plan_path: str) -> Optional[Dict]:
        """
        加载升级计划
        
        参数:
            plan_path: 升级计划文件路径
            
        返回:
            升级计划字典
        """
        try:
            with open(plan_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载升级计划失败: {e}")
            return None
    
    def _do_update(self) -> bool:
        """
        执行升级
        
        返回:
            升级是否成功
        """
        # 第一步：下载所有升级包
        if not self._download_packages():
            return False
        
        if self._is_cancelled:
            return False
        
        # 第二步：安装所有升级包
        if not self._install_packages():
            return False
        
        return True
    
    def _download_packages(self) -> bool:
        """
        下载所有升级包
        
        返回:
            下载是否成功
        """
        packages = self._plan.get('packages', [])
        if not packages:
            print("没有需要下载的包")
            return True
        
        download_dir = self._plan.get('download_dir', config.get_update_cache_dir())
        config.ensure_dir(download_dir)
        
        # 更新UI
        self.phase_changed.emit("下载")
        self.status_changed.emit("正在下载升级包...")
        self._progress_dialog.enable_cancel_button(True)
        
        # 创建下载器
        self._downloader = UpdateDownloader(download_dir)
        
        # 连接信号
        self._downloader.download_progress.connect(self._on_download_progress)
        self._downloader.current_package_changed.connect(self._on_package_changed)
        
        # 使用事件循环等待下载完成
        from PyQt6.QtCore import QEventLoop
        
        self._download_success = False
        self._download_error = ""
        
        def on_completed():
            self._download_success = True
            loop.quit()
        
        def on_failed(error):
            self._download_error = error
            loop.quit()
        
        self._downloader.download_completed.connect(on_completed)
        self._downloader.download_failed.connect(on_failed)
        
        # 开始下载
        loop = QEventLoop()
        self._downloader.download_packages(packages)
        loop.exec()
        
        if not self._download_success:
            self.status_changed.emit(f"下载失败: {self._download_error}")
            return False
        
        return True
    
    def _on_download_progress(self, progress: int):
        """处理下载进度"""
        self.download_progress.emit(progress)
    
    def _on_package_changed(self, filename: str):
        """处理当前包变化"""
        self.current_file_changed.emit(filename)
    
    def _install_packages(self) -> bool:
        """
        安装所有升级包

        返回:
            安装是否成功
        """
        packages = self._plan.get('packages', [])
        if not packages:
            return True

        # 获取下载的包路径
        download_dir = self._plan.get('download_dir', config.get_update_cache_dir())
        package_paths = []

        for pkg in packages:
            filename = pkg.get('package', pkg.get('filename', ''))
            filepath = os.path.join(download_dir, filename)
            if os.path.exists(filepath):
                package_paths.append(filepath)
            else:
                print(f"警告: 找不到升级包: {filepath}")

        if not package_paths:
            print("错误: 没有可安装的升级包")
            return False

        # 更新UI
        self.phase_changed.emit("安装")
        self.status_changed.emit("正在安装升级包...")
        self._progress_dialog.enable_cancel_button(False)  # 安装时不能取消

        # 获取安装目录
        install_dir = self._plan.get('install_dir', config.get_update_cache_dir())

        # 创建安装器
        self._installer = UpdateInstaller(install_dir)

        # 连接信号
        self._installer.install_progress.connect(self._on_install_progress)

        # 使用事件循环等待安装完成
        from PyQt6.QtCore import QEventLoop

        self._install_success = False
        self._install_error = ""

        def on_completed(affected_files):
            self._install_success = True
            self._affected_files = affected_files
            loop.quit()

        def on_failed(error):
            self._install_error = error
            loop.quit()

        self._installer.install_completed.connect(on_completed)
        self._installer.install_failed.connect(on_failed)

        # 开始安装
        loop = QEventLoop()
        self._installer.install_packages(package_paths)
        loop.exec()

        if not self._install_success:
            self.status_changed.emit(f"安装失败: {self._install_error}")
            return False

        return True
    
    def _on_install_progress(self, progress: int, description: str):
        """处理安装进度"""
        self.install_progress.emit(progress, description)
    
    def _cleanup(self):
        """清理临时文件"""
        try:
            download_dir = self._plan.get('download_dir', config.get_update_cache_dir())
            
            # 删除下载的升级包
            if os.path.exists(download_dir):
                for filename in os.listdir(download_dir):
                    if filename.endswith('.exe') or filename.endswith('.tmp'):
                        filepath = os.path.join(download_dir, filename)
                        try:
                            os.remove(filepath)
                        except Exception:
                            pass
            
            # 删除升级计划文件
            plan_path = config.get_update_plan_path()
            if os.path.exists(plan_path):
                try:
                    os.remove(plan_path)
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"清理临时文件失败: {e}")
    
    def _launch_main_app(self):
        """启动主程序"""
        try:
            import subprocess
            
            main_app_path = self._plan.get('main_app_path', '')
            if not main_app_path or not os.path.exists(main_app_path):
                print(f"警告: 找不到主程序: {main_app_path}")
                return
            
            # 启动主程序
            subprocess.Popen(
                [main_app_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            print("主程序已启动")
            
        except Exception as e:
            print(f"启动主程序失败: {e}")
    
    def _on_cancel(self):
        """处理取消请求"""
        self._is_cancelled = True

        if self._downloader:
            self._downloader.cancel_download()

        if self._installer:
            self._installer.cancel_install()

    def _record_update_history(self):
        """记录升级历史"""
        try:
            # 获取版本信息
            from_version = self._plan.get('current_version', 'unknown')
            to_version = self._plan.get('target_version', 'unknown')

            # 获取包名
            packages = self._plan.get('packages', [])
            if packages:
                package_name = packages[0].get('package', packages[0].get('filename', 'unknown'))
            else:
                package_name = 'unknown'

            # 获取安装目录
            install_dir = self._plan.get('install_dir', config.get_app_dir())

            # 创建备份（只备份受影响的文件）
            history_manager = get_history_manager()
            backup_path = history_manager.create_backup(install_dir, self._affected_files)

            # 添加历史记录
            history_manager.add_history_entry(
                from_version=from_version,
                to_version=to_version,
                package_name=package_name,
                affected_files=self._affected_files,
                backup_path=backup_path,
                success=True
            )

            print(f"升级历史已记录: {from_version} -> {to_version}")
            print(f"受影响文件数: {len(self._affected_files)}")

        except Exception as e:
            print(f"记录升级历史失败: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="栖图升级启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 正常升级
  python update/update_launcher.py --plan update_plan.json
  
  # 测试模式（只下载解压，不替换文件）
  python update/update_launcher.py --plan update_plan.json --test
        """
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="升级计划文件路径"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="测试模式：只下载和解压，不执行文件替换"
    )
    
    args = parser.parse_args()
    
    # 检查计划文件
    if not os.path.exists(args.plan):
        print(f"错误: 升级计划文件不存在: {args.plan}")
        return 1
    
    # 创建启动器并运行
    launcher = UpdateLauncher(test_mode=args.test)
    return launcher.run(args.plan)


if __name__ == "__main__":
    sys.exit(main())
