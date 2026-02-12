import os
from enum import Enum
from threading import Lock
from utils.log_manager import LogManager

class TaskType(Enum):
    LIBRARY_LOADER = "library_loader"
    IMPORT_LOADER = "import_loader"
    CACHE_SAVER = "cache_saver"
    DEFAULT = "default"

class TaskScheduler:
    """任务调度器：根据 CPU 核心数动态分配线程资源"""
    _instance = None
    _lock = Lock()

    @classmethod
    def instance(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = TaskScheduler()
        return cls._instance

    def __init__(self):
        # 获取 CPU 核心数
        try:
            self._cpu_count = os.cpu_count() or 4
        except Exception:
            self._cpu_count = 4
            
        self._allocations = self._calculate_allocations()
        try:
            LogManager.instance().debug(f"[TaskScheduler] CPUs={self._cpu_count} allocations={self._allocations}")
        except Exception:
            pass

    def _calculate_allocations(self):
        # 策略：
        # 保留 1-2 个核心给 UI 和系统
        # 剩余核心分配给 IO/计算密集型任务
        
        # 可用于后台任务的核心数 (至少保留1个给主线程/UI)
        available = max(1, self._cpu_count - 1)
        if self._cpu_count >= 8:
            available = self._cpu_count - 2
        
        allocs = {}
        
        # 图库加载器 (IO + 解码)：
        # 4核 -> 3
        # 8核 -> 6
        # 16核 -> 8 (设置上限，避免磁盘 IO 瓶颈)
        allocs[TaskType.LIBRARY_LOADER] = max(2, min(available, 8))
        
        # 导入页面加载器：同上
        allocs[TaskType.IMPORT_LOADER] = max(2, min(available, 8))
        
        # 缓存保存 (纯 CPU 编码)：利用更多核心加速退出
        allocs[TaskType.CACHE_SAVER] = max(2, available)
        
        allocs[TaskType.DEFAULT] = max(1, available // 2)
        
        return allocs

    def get_thread_count(self, task_type: TaskType = TaskType.DEFAULT) -> int:
        return self._allocations.get(task_type, 4)

    def get_cpu_count(self):
        return self._cpu_count
