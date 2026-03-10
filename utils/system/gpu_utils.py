import cv2
import numpy as np
from PyQt6.QtGui import QImage
import os
import subprocess
import sys
import threading
import time


_build_flavor_cache: str | None = None
_torch_cuda_probe_cache: tuple[bool, str, int, float] | None = None
_torch_cuda_probe_thread_started: bool = False
_torch_cuda_probe_thread_lock = threading.Lock()


def _get_build_flavor() -> str:
    global _build_flavor_cache
    if _build_flavor_cache is not None:
        return str(_build_flavor_cache)
    if not bool(getattr(__import__("sys"), "frozen", False)):
        _build_flavor_cache = "dev"
        return "dev"
    marker = None
    try:
        from utils.paths import PathManager

        root = PathManager.instance().get_project_root()
        marker = root / "build_flavor.txt"
        try:
            txt = marker.read_text(encoding="utf-8", errors="ignore").strip().lower()
        except Exception:
            txt = ""
        if txt in ("cpu", "gpu"):
            _build_flavor_cache = txt
            return txt
    except Exception:
        marker = None
    try:
        from utils.paths import PathManager

        root = PathManager.instance().get_project_root()
        torch_lib = root / "torch" / "lib"
        is_gpu = False
        try:
            is_gpu = bool((torch_lib / "c10_cuda.dll").exists()) or bool((torch_lib / "torch_cuda.dll").exists())
        except Exception:
            is_gpu = False
        _build_flavor_cache = "gpu" if bool(is_gpu) else "cpu"
        if marker is not None:
            try:
                marker.write_text(str(_build_flavor_cache), encoding="utf-8")
            except Exception:
                pass
        return str(_build_flavor_cache)
    except Exception:
        _build_flavor_cache = "cpu"
        if marker is not None:
            try:
                marker.write_text("cpu", encoding="utf-8")
            except Exception:
                pass
        return "cpu"


def is_gpu_build() -> bool:
    try:
        return str(_get_build_flavor()).lower() == "gpu"
    except Exception:
        return False


def _get_torch_cuda_probe_timeout_s() -> float:
    try:
        if bool(getattr(sys, "frozen", False)):
            return 45.0
    except Exception:
        pass
    return 8.0


def start_torch_cuda_probe_async(force: bool = False) -> None:
    """
    在后台尽早启动一次 torch CUDA 可用性探测，并把结果写入全局缓存。

    设计目标：
    - 启动阶段尽快开始探测，减少后续业务（例如对焦检测）第一次触发时的等待；
    - 探测在子进程中进行，避免主进程因 CUDA 相关原生崩溃被带走；
    - 后续调用 is_torch_cuda_usable()/get_torch_cuda_check_brief() 直接复用缓存结果。

    参数：
    - force: True 表示强制重新启动探测（会清空缓存并重新探测）。
    """
    global _torch_cuda_probe_thread_started
    try:
        if not bool(is_gpu_build()):
            return
    except Exception:
        return

    if bool(force):
        try:
            reset_torch_cuda_cache()
        except Exception:
            pass

    try:
        if bool(_torch_cuda_checked) or (_torch_cuda_probe_cache is not None):
            return
    except Exception:
        pass

    try:
        with _torch_cuda_probe_thread_lock:
            if bool(_torch_cuda_probe_thread_started):
                return
            _torch_cuda_probe_thread_started = True
    except Exception:
        return

    def _run():
        global _torch_cuda_cache, _torch_cuda_checked, _torch_cuda_checked_at, _torch_cuda_checked_code
        try:
            ok, _, code = _probe_torch_cuda_via_subprocess(timeout_s=_get_torch_cuda_probe_timeout_s())
            try:
                _torch_cuda_cache = bool(ok)
                _torch_cuda_checked_code = int(code)
                _torch_cuda_checked = True
                _torch_cuda_checked_at = float(time.monotonic())
            except Exception:
                pass
        except Exception:
            try:
                _torch_cuda_cache = False
                _torch_cuda_checked = True
                _torch_cuda_checked_code = 12
                _torch_cuda_checked_at = float(time.monotonic())
            except Exception:
                pass

    try:
        t = threading.Thread(target=_run, name="TorchCudaProbe", daemon=True)
        t.start()
    except Exception:
        pass


def get_gpu_summary() -> str:
    parts = []
    try:
        flavor = str(_get_build_flavor() or "").strip().lower()
    except Exception:
        flavor = ""
    if flavor:
        parts.append(f"build_flavor={flavor}")
    try:
        from utils.paths import PathManager

        root = PathManager.instance().get_project_root()
        marker = root / "build_flavor.txt"
        try:
            exists = bool(marker.exists())
        except Exception:
            exists = False
        if exists:
            try:
                txt = marker.read_text(encoding="utf-8", errors="ignore").strip().lower()
            except Exception:
                txt = ""
            if txt:
                parts.append(f"build_flavor_file={txt}")
            else:
                parts.append("build_flavor_file=empty")
        else:
            parts.append("build_flavor_file=missing")
    except Exception:
        pass
    try:
        ok, out, code = _probe_torch_cuda_via_subprocess(timeout_s=_get_torch_cuda_probe_timeout_s())
        if bool(ok):
            parts.append("torch.cuda=True")
        else:
            parts.append("torch.cuda=False")
        if out:
            parts.append(f"torch.cuda_probe={out}")
        if int(code) not in (0, 2, 3):
            parts.append(f"torch.cuda_probe_exit={int(code)}")
        try:
            kv = {}
            for part in str(out or "").split("|"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    kv[str(k).strip()] = str(v)
            v = str(kv.get("torch", "") or "").strip()
            cuda_ver = str(kv.get("torch_cuda", "") or "").strip()
            if v or cuda_ver:
                parts.append(f"torch={v} torch.version.cuda={cuda_ver}")
        except Exception:
            pass
    except Exception as e:
        parts.append(f"torch.cuda_probe_error={e}")
    try:
        ok_cv = is_opencv_cuda_usable()
        parts.append(f"opencv.cuda={bool(ok_cv)}")
    except Exception:
        pass
    return " | ".join([p for p in parts if p])


# 缓存 torch CUDA 检查结果，避免重复检查导致卡顿
_torch_cuda_cache: bool | None = None
_torch_cuda_checked: bool = False
_torch_cuda_checked_at: float | None = None
_torch_cuda_checked_code: int | None = None

def reset_torch_cuda_cache():
    """重置 torch CUDA 检查缓存，下次调用时会重新检查"""
    global _torch_cuda_cache, _torch_cuda_checked, _torch_cuda_checked_at, _torch_cuda_checked_code
    _torch_cuda_cache = None
    _torch_cuda_checked = False
    _torch_cuda_checked_at = None
    _torch_cuda_checked_code = None
    global _torch_cuda_probe_cache
    _torch_cuda_probe_cache = None


def _subprocess_no_window_kwargs() -> dict:
    if os.name != "nt":
        return {}
    creationflags = 0
    try:
        creationflags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    except Exception:
        creationflags |= 0x08000000
    try:
        creationflags |= int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    except Exception:
        creationflags |= 0x00000008
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {"creationflags": int(creationflags), "startupinfo": si}
    except Exception:
        return {"creationflags": int(creationflags)}


def _probe_torch_cuda_via_subprocess(timeout_s: float = 5.0) -> tuple[bool, str, int]:
    global _torch_cuda_probe_cache
    if _torch_cuda_probe_cache is not None:
        try:
            ok0, out0, code0, ts0 = _torch_cuda_probe_cache
            now = float(time.monotonic())
            age_s = float(now - float(ts0))
            ttl_s = 300.0 if (bool(ok0) or int(code0) == 2) else 30.0
            if age_s <= ttl_s:
                return bool(ok0), str(out0 or ""), int(code0)
            _torch_cuda_probe_cache = None
        except Exception:
            _torch_cuda_probe_cache = None

    exe = str(sys.executable or "")
    if not exe:
        now = float(time.monotonic())
        _torch_cuda_probe_cache = (False, "no_executable", 10, now)
        return (False, "no_executable", 10)

    is_frozen = bool(getattr(sys, "frozen", False))
    if is_frozen:
        args = [exe, "--torch-cuda-probe"]
    else:
        code = (
            "import sys\n"
            "try:\n"
            " import torch\n"
            " v=str(getattr(torch,'__version__','') or '')\n"
            " cuda=getattr(getattr(torch,'version',None),'cuda',None)\n"
            " ok=0\n"
            " dc=-1\n"
            " name=''\n"
            " err=''\n"
            " try:\n"
            "  if bool(torch.cuda.is_available()):\n"
            "   dc=int(torch.cuda.device_count() or 0)\n"
            "   if dc>0:\n"
            "    ok=1\n"
            "    try:\n"
            "     name=str(torch.cuda.get_device_name(0) or '')\n"
            "    except Exception:\n"
            "     name=''\n"
            " except Exception as e:\n"
            "  err=str(e)\n"
            " print(f'torch={v}|torch_cuda={cuda}|ok={ok}|dc={dc}|name0={name}|err={err}')\n"
            " sys.exit(0 if ok else 2)\n"
            "except Exception as e:\n"
            " print('torch_probe_error='+str(e))\n"
            " sys.exit(3)\n"
        )
        args = [exe, "-c", code]

    try:
        now = float(time.monotonic())
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
            **_subprocess_no_window_kwargs(),
        )
        out = (str(cp.stdout or "") + "\n" + str(cp.stderr or "")).strip()
        out = out.replace("\r\n", "\n").replace("\r", "\n")
        out_lines = []
        try:
            out_lines = [str(x).strip() for x in str(out or "").splitlines()]
        except Exception:
            out_lines = []
        out_lines = [x for x in out_lines if x]
        out_one = ""
        for line in reversed(out_lines):
            s = str(line or "").strip()
            if not s:
                continue
            if s.startswith("torch=") or s.startswith("torch_probe_error=") or s.startswith("torch_import_error="):
                out_one = s
                break
        if not out_one:
            out_one = (out_lines[-1] if out_lines else "").strip()
        ok = int(cp.returncode) == 0
        _torch_cuda_probe_cache = (bool(ok), str(out_one or ""), int(cp.returncode), now)
        return (bool(ok), str(out_one or ""), int(cp.returncode))
    except subprocess.TimeoutExpired:
        now = float(time.monotonic())
        _torch_cuda_probe_cache = (False, "timeout", 11, now)
        return (False, "timeout", 11)
    except Exception as e:
        now = float(time.monotonic())
        _torch_cuda_probe_cache = (False, f"run_error={e}", 12, now)
        return (False, f"run_error={e}", 12)


def get_torch_cuda_check_brief() -> str:
    """
    获取 torch CUDA 探测的简短状态文本（不主动触发新的探测）。

    设计目标：
    - UI/日志需要展示“是否可用”与“为什么不可用”的关键原因；
    - 该函数尽量只读取已有缓存，避免在 UI 线程里启动子进程或阻塞。
    """
    try:
        if not bool(is_gpu_build()):
            return "否"
    except Exception:
        pass

    try:
        if bool(_torch_cuda_checked):
            if bool(_torch_cuda_cache):
                return "是"
            try:
                code = _torch_cuda_checked_code
            except Exception:
                code = None
            if int(code or 0) == 11:
                return "否（超时）"
            if int(code or 0) == 12:
                return "否（异常）"
            if int(code or 0) == 3:
                return "否（导入失败）"
            return "否"
    except Exception:
        pass

    try:
        if _torch_cuda_probe_cache is not None:
            ok0, out0, code0, _ = _torch_cuda_probe_cache
            if bool(ok0):
                return "是"
            if int(code0) == 11:
                return "否（超时）"
            if int(code0) == 12:
                return "否（异常）"
            if int(code0) == 3:
                return "否（导入失败）"
            if str(out0 or "").strip() == "timeout":
                return "否（超时）"
            return "否"
    except Exception:
        pass

    return "未知"


def _clear_torch_cuda_cache_via_subprocess(timeout_s: float = 5.0) -> tuple[bool, str, int]:
    """
    在子进程中尝试执行 torch.cuda.empty_cache()。

    目的：
    - 避免主进程直接触发 torch 的 CUDA 初始化逻辑，从而规避 c10_cuda.dll 这类原生崩溃把主进程带走。

    参数：
    - timeout_s: 子进程最大执行时长（秒），超时会被终止并返回失败。

    返回：
    - (是否成功, 输出摘要, 退出码)
    """
    exe = str(sys.executable or "")
    if not exe:
        return (False, "no_executable", 10)

    is_frozen = bool(getattr(sys, "frozen", False))
    if is_frozen:
        args = [exe, "--torch-cuda-clear-cache"]
    else:
        code = (
            "import sys\n"
            "try:\n"
            " import torch\n"
            " ok=0\n"
            " err=''\n"
            " try:\n"
            "  if bool(torch.cuda.is_available()):\n"
            "   torch.cuda.empty_cache()\n"
            "   ok=1\n"
            " except Exception as e:\n"
            "  err=str(e)\n"
            " print(f'torch_cuda_cache_cleared={ok}|err={err}')\n"
            " sys.exit(0 if ok else 2)\n"
            "except Exception as e:\n"
            " print('torch_clear_cache_error='+str(e))\n"
            " sys.exit(3)\n"
        )
        args = [exe, "-c", code]

    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
            **_subprocess_no_window_kwargs(),
        )
        out = (str(cp.stdout or "") + "\n" + str(cp.stderr or "")).strip()
        out = out.replace("\r\n", "\n").replace("\r", "\n")
        out_one = (out.splitlines()[-1] if out else "").strip()
        ok = int(cp.returncode) == 0
        return (bool(ok), str(out_one or ""), int(cp.returncode))
    except subprocess.TimeoutExpired:
        return (False, "timeout", 11)
    except Exception as e:
        return (False, f"run_error={e}", 12)


def try_clear_torch_cuda_cache(timeout_s: float = 4.0) -> bool:
    """
    尝试清理 torch CUDA 缓存（如果是 GPU 构建）。

    设计说明：
    - 仅在检测到 GPU 构建时才尝试执行；
    - 实际执行在子进程中完成，尽量避免主进程因 CUDA 驱动/运行库问题发生原生崩溃。

    参数：
    - timeout_s: 子进程最大执行时长（秒）。

    返回：
    - True 表示清理执行成功；False 表示未清理或清理失败（含超时/异常/非 GPU 构建）。
    """
    try:
        if not bool(is_gpu_build()):
            return False
    except Exception:
        return False
    try:
        ok, _, _ = _clear_torch_cuda_cache_via_subprocess(timeout_s=float(timeout_s))
        return bool(ok)
    except Exception:
        return False


def is_torch_cuda_usable() -> bool:
    global _torch_cuda_cache, _torch_cuda_checked, _torch_cuda_checked_at, _torch_cuda_checked_code
    
    # 如果已经检查过，直接返回缓存结果
    if _torch_cuda_checked:
        try:
            if bool(_torch_cuda_cache):
                return True
            if _torch_cuda_checked_at is None:
                return bool(_torch_cuda_cache)
            now = float(time.monotonic())
            if float(now - float(_torch_cuda_checked_at)) <= 30.0:
                return False
            _torch_cuda_checked = False
        except Exception:
            return bool(_torch_cuda_cache)

    try:
        if not bool(is_gpu_build()):
            _torch_cuda_cache = False
            _torch_cuda_checked = True
            return False
    except Exception:
        _torch_cuda_cache = False
        _torch_cuda_checked = True
        return False
    
    try:
        ok, _, code = _probe_torch_cuda_via_subprocess(timeout_s=_get_torch_cuda_probe_timeout_s())
        _torch_cuda_cache = bool(ok)
        _torch_cuda_checked_code = int(code)
    except Exception:
        _torch_cuda_cache = False
        _torch_cuda_checked_code = 12
    
    _torch_cuda_checked = True
    try:
        _torch_cuda_checked_at = float(time.monotonic())
    except Exception:
        _torch_cuda_checked_at = None
    return bool(_torch_cuda_cache)


def is_opencv_cuda_usable() -> bool:
    try:
        if not hasattr(cv2, "cuda"):
            return False
        return int(cv2.cuda.getCudaEnabledDeviceCount() or 0) > 0
    except Exception:
        return False


class GPUScaler:
    _checked = False
    _available = False
    _backend = None
    _suspended = False

    @classmethod
    def is_available(cls):
        try:
            if not bool(is_gpu_build()):
                return False
        except Exception:
            return False
        try:
            if bool(getattr(cls, "_suspended", False)):
                return False
        except Exception:
            pass
        if not cls._checked:
            try:
                if hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                    cls._backend = "cuda"
            except Exception:
                cls._backend = None
            if cls._backend is None:
                try:
                    if hasattr(cv2, "ocl") and cv2.ocl.haveOpenCL():
                        cv2.ocl.setUseOpenCL(True)
                        if cv2.ocl.useOpenCL():
                            cls._backend = "opencl"
                except Exception:
                    cls._backend = None
            cls._available = cls._backend is not None
            cls._checked = True
        return cls._available

    @classmethod
    def set_suspended(cls, suspended: bool = True):
        try:
            cls._suspended = bool(suspended)
        except Exception:
            cls._suspended = True

    @classmethod
    def scale_qimage(cls, image, target_w, target_h, keep_aspect=True, fast_mode=False):
        if image is None or image.isNull():
            return None
        try:
            if bool(getattr(cls, "_suspended", False)):
                return None
        except Exception:
            return None
        if not cls.is_available():
            return None
        try:
            src = image.convertToFormat(QImage.Format.Format_RGB888)
            src_w = int(src.width())
            src_h = int(src.height())
            if src_w <= 0 or src_h <= 0:
                return None
            if keep_aspect:
                scale = min(float(target_w) / src_w, float(target_h) / src_h)
                new_w = max(1, int(round(src_w * scale)))
                new_h = max(1, int(round(src_h * scale)))
            else:
                new_w = max(1, int(target_w))
                new_h = max(1, int(target_h))
            if new_w == src_w and new_h == src_h:
                return src
            bytes_per_line = int(src.bytesPerLine())
            ptr = src.bits()
            ptr.setsize(src_h * bytes_per_line)
            arr = np.frombuffer(ptr, np.uint8).reshape((src_h, bytes_per_line))
            arr = arr[:, :src_w * 3].reshape((src_h, src_w, 3))
            interpolation = cv2.INTER_NEAREST if fast_mode else cv2.INTER_LINEAR
            if cls._backend == "cuda":
                gpu_mat = cv2.cuda_GpuMat()
                gpu_mat.upload(arr)
                resized = cv2.cuda.resize(gpu_mat, (new_w, new_h), interpolation=interpolation)
                out = resized.download()
            elif cls._backend == "opencl":
                umat = cv2.UMat(arr)
                resized = cv2.resize(umat, (new_w, new_h), interpolation=interpolation)
                out = resized.get()
            else:
                return None
            if out is None:
                return None
            out_bpl = int(out.strides[0])
            return QImage(out.data, new_w, new_h, out_bpl, QImage.Format.Format_RGB888).copy()
        except Exception:
            return None
