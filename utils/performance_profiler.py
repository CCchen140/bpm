"""性能分析工具 - 用于定位UI阻塞点

使用方法:
    from utils.performance_profiler import PerformanceProfiler
    
    # 方法1: 使用装饰器
    @PerformanceProfiler.profile("function_name")
    def my_function():
        pass
    
    # 方法2: 使用上下文管理器
    with PerformanceProfiler.profile_context("block_name"):
        # 代码块
        pass
    
    # 方法3: 手动计时
    profiler = PerformanceProfiler()
    profiler.start("task_name")
    # 执行任务
    profiler.end("task_name")
"""

import time
import functools
from typing import Dict, List, Optional
from collections import defaultdict


class PerformanceProfiler:
    """性能分析器 - 用于检测耗时操作"""
    
    # 全局实例
    _instance = None
    
    # 阈值（毫秒）- 超过此值会记录警告
    WARNING_THRESHOLD_MS = 16  # 60fps = 16.67ms per frame
    ERROR_THRESHOLD_MS = 33    # 30fps = 33.33ms per frame
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self._timings: Dict[str, List[float]] = defaultdict(list)
        self._active_timers: Dict[str, float] = {}
        self._enabled = True
        
    def enable(self):
        self._enabled = True
        
    def disable(self):
        self._enabled = False
        
    def start(self, name: str):
        """开始计时"""
        if not self._enabled:
            return
        self._active_timers[name] = time.perf_counter()
        
    def end(self, name: str) -> float:
        """结束计时并返回耗时（毫秒）"""
        if not self._enabled or name not in self._active_timers:
            return 0.0
        
        elapsed = (time.perf_counter() - self._active_timers[name]) * 1000
        self._timings[name].append(elapsed)
        
        # 只保留最近的100个记录
        if len(self._timings[name]) > 100:
            self._timings[name] = self._timings[name][-100:]
        
        del self._active_timers[name]
        
        # 如果耗时超过阈值，打印警告
        if elapsed > self.ERROR_THRESHOLD_MS:
            print(f"[PERF ERROR] {name}: {elapsed:.2f}ms (超过 {self.ERROR_THRESHOLD_MS}ms)")
        elif elapsed > self.WARNING_THRESHOLD_MS:
            print(f"[PERF WARN] {name}: {elapsed:.2f}ms")
        
        return elapsed
    
    def get_stats(self, name: str) -> Optional[Dict]:
        """获取统计信息"""
        if name not in self._timings or not self._timings[name]:
            return None
        
        times = self._timings[name]
        return {
            "count": len(times),
            "avg": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
            "last": times[-1]
        }
    
    def print_all_stats(self):
        """打印所有统计信息"""
        print("\n" + "="*60)
        print("性能分析统计")
        print("="*60)
        
        for name in sorted(self._timings.keys()):
            stats = self.get_stats(name)
            if stats:
                print(f"{name:40s} 次数:{stats['count']:4d}  "
                      f"平均:{stats['avg']:7.2f}ms  "
                      f"最小:{stats['min']:7.2f}ms  "
                      f"最大:{stats['max']:7.2f}ms  "
                      f"最近:{stats['last']:7.2f}ms")
        
        print("="*60 + "\n")
    
    @classmethod
    def profile(cls, name: str):
        """装饰器 - 用于分析函数性能"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                profiler = cls.instance()
                profiler.start(name)
                try:
                    return func(*args, **kwargs)
                finally:
                    profiler.end(name)
            return wrapper
        return decorator
    
    @classmethod
    def profile_context(cls, name: str):
        """上下文管理器 - 用于分析代码块性能"""
        class _ProfileContext:
            def __enter__(self):
                cls.instance().start(name)
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                cls.instance().end(name)
                return False
        
        return _ProfileContext()


# 便捷函数
def profile(name: str):
    """便捷装饰器函数"""
    return PerformanceProfiler.profile(name)


def profile_context(name: str):
    """便捷上下文管理器函数"""
    return PerformanceProfiler.profile_context(name)


# 主线程检查器
class MainThreadChecker:
    """检查是否在主线程执行耗时操作"""
    
    @staticmethod
    def check_main_thread():
        """检查当前是否在主线程"""
        import threading
        return threading.current_thread() == threading.main_thread()
    
    @staticmethod
    def warn_if_main_thread(operation_name: str):
        """如果在主线程执行耗时操作，打印警告"""
        if MainThreadChecker.check_main_thread():
            print(f"[WARN] 在主线程执行耗时操作: {operation_name}")
            import traceback
            traceback.print_stack(limit=5)
