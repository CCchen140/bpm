import platform
import psutil
import sys
from utils.log_manager import LogManager

APP_NAME = "栖图"
APP_VERSION = "V0.0.4"
APP_UPDATE = "update2"  # 升级版本号，例如 "update1"，空字符串表示非升级版本

class AppInfoManager:
    """
    Manager for application and device information.
    """
    _instance = None
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = AppInfoManager()
        return cls._instance

    def __init__(self):
        pass

    def get_app_name(self):
        return APP_NAME

    def get_app_version(self):
        return APP_VERSION

    def get_app_update(self):
        """获取升级版本号，空字符串表示非升级版本"""
        return APP_UPDATE

    def get_full_version(self):
        """获取完整版本号，包含升级版本号（如果有）"""
        if APP_UPDATE:
            return f"{APP_VERSION}_{APP_UPDATE}"
        return APP_VERSION

    def get_device_info(self):
        info = {
            "OS": f"{platform.system()} {platform.release()} ({platform.version()})",
            "Machine": platform.machine(),
            "Processor": platform.processor(),
            "Python": sys.version,
            "RAM_Total": f"{psutil.virtual_memory().total / (1024**3):.2f} GB",
            "RAM_Available": f"{psutil.virtual_memory().available / (1024**3):.2f} GB",
            "CPU_Cores": psutil.cpu_count(logical=False),
            "CPU_Threads": psutil.cpu_count(logical=True)
        }
        return info

    def log_startup_info(self):
        """Logs basic application and device information."""
        app_ver = self.get_app_version()
        device_info = self.get_device_info()
        
        log_msg = f"\n{'='*30}\n"
        log_msg += f"App Version: {app_ver}\n"
        log_msg += f"{'-'*30}\n"
        for key, value in device_info.items():
            log_msg += f"{key}: {value}\n"
        log_msg += f"{'='*30}"
        
        LogManager.instance().info(log_msg)
