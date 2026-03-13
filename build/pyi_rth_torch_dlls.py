"""
PyInstaller runtime hook: configure DLL search paths for torch CUDA before any imports.

This hook runs at the very start of the packaged application, before any user code
or library imports. It ensures that CUDA DLLs (from nvidia packages, now placed in
torch/lib/) are discoverable by the Windows DLL loader.
"""
import os
import sys


def _detect_gpu_type():
    """
    检测GPU类型
    
    返回:
        "nvidia" - 检测到NVIDIA GPU
        "amd" - 检测到AMD GPU
        "unknown" - 检测失败
    """
    try:
        import subprocess
        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name"],
            capture_output=True,
            text=True,
            timeout=5
        )
        output = result.stdout.lower()
        
        # 检查NVIDIA GPU
        if any(kw in output for kw in ["nvidia", "geforce", "quadro", "tesla"]):
            return "nvidia"
        
        # 检查AMD GPU
        if any(kw in output for kw in ["amd", "radeon", "rx ", "ryzen"]):
            return "amd"
        
        return "unknown"
    except Exception:
        return "unknown"


def _setup_torch_dll_paths():
    if sys.platform != "win32":
        return

    if not getattr(sys, "frozen", False):
        return

    try:
        base = os.path.dirname(sys.executable)
    except Exception:
        return

    if not base:
        return

    # 检测GPU类型
    gpu_type = _detect_gpu_type()
    
    # 调试输出（使用stderr，因为此时日志系统可能还未初始化）
    import sys as _sys
    print(f"[pyi_rth_torch_dlls] GPU type detected: {gpu_type}", file=_sys.stderr)
    
    # 在AMD GPU上禁用CUDA，强制使用CPU模式
    if gpu_type == "amd":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""  # 禁用CUDA设备
        os.environ["USE_CUDA"] = "0"  # 禁用CUDA
        os.environ["TORCH_CUDA_ARCH_LIST"] = ""  # 禁用CUDA架构列表
        # 关键：设置这个变量让torch在导入时不初始化CUDA
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "backend:native"
        # 不添加nvidia DLL目录
        has_nvidia = False
        print(f"[pyi_rth_torch_dlls] AMD GPU detected, CUDA disabled", file=_sys.stderr)
    else:
        has_nvidia = (gpu_type == "nvidia")
        print(f"[pyi_rth_torch_dlls] NVIDIA GPU: {has_nvidia}", file=_sys.stderr)

    dll_dirs = [
        base,
        os.path.join(base, "torch", "lib"),
        os.path.join(base, "lib"),
    ]

    # 只有检测到NVIDIA GPU时才添加nvidia DLL目录
    if has_nvidia:
        nvidia_root = os.path.join(base, "nvidia")
        if os.path.isdir(nvidia_root):
            try:
                for dirpath, _, filenames in os.walk(nvidia_root):
                    if any(fn.lower().endswith(".dll") for fn in filenames):
                        dll_dirs.append(dirpath)
            except Exception:
                pass

    existing_dirs = []
    for d in dll_dirs:
        try:
            if d and os.path.isdir(d):
                existing_dirs.append(d)
        except Exception:
            pass

    try:
        old_path = os.environ.get("PATH", "")
        new_entries = [d for d in existing_dirs if d not in old_path]
        if new_entries:
            os.environ["PATH"] = os.pathsep.join(new_entries) + os.pathsep + old_path
    except Exception:
        pass

    if hasattr(os, "add_dll_directory"):
        for d in existing_dirs:
            try:
                os.add_dll_directory(d)
            except OSError:
                pass


_setup_torch_dll_paths()
