"""
PyInstaller runtime hook: 隐藏 multiprocessing 子进程的控制台窗口

这个钩子必须在任何使用 multiprocessing 的模块之前加载，
以确保所有子进程都不会显示控制台窗口。
"""
import sys

# Windows: 全局 monkey-patch multiprocessing，隐藏子进程控制台窗口
# 必须在任何 multiprocessing 导入之前执行
if sys.platform == "win32":
    try:
        import _winapi
        
        # 检查是否已经 patch 过（避免重复 patch）
        if not hasattr(_winapi.CreateProcess, '_no_window_patched'):
            # 保存原始的 _winapi.CreateProcess
            _original_create_process = _winapi.CreateProcess
            
            def _no_window_create_process(*args, **kwargs):
                # 修改 creation_flags 参数（第6个参数，索引为5）
                if len(args) >= 6:
                    args = list(args)
                    args[5] = args[5] | 0x08000000  # CREATE_NO_WINDOW
                    args = tuple(args)
                # 直接调用原始函数，不要通过 _winapi.CreateProcess
                return _original_create_process(*args, **kwargs)
            
            # 标记为已 patch
            _no_window_create_process._no_window_patched = True
            
            # 替换 _winapi.CreateProcess
            _winapi.CreateProcess = _no_window_create_process
    except Exception:
        pass
