#!/usr/bin/env python3
"""
栖图自动升级系统

提供软件自动升级功能，包括：
- 版本检查
- 下载升级包
- 安装升级
- 进度显示

使用示例:
    from update import UpdateManager
    
    update_manager = UpdateManager()
    update_manager.check_update(silent=True)
"""

# 版本号
__version__ = "1.0.0"

# 导出主要类
from .update_manager import UpdateManager
from .update_checker import UpdateChecker
from .update_downloader import UpdateDownloader
from .update_installer import UpdateInstaller
from .update_dialog import UpdateDialog
from .update_progress_dialog import UpdateProgressDialog

__all__ = [
    "UpdateManager",
    "UpdateChecker",
    "UpdateDownloader",
    "UpdateInstaller",
    "UpdateDialog",
    "UpdateProgressDialog",
]
