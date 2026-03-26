from PyQt6.QtGui import QImage
import os
import sys
import threading
import time

# 延迟导入 cv2 和 numpy，避免启动时加载重型依赖
_cv2 = None
_numpy = None

def _get_cv2():
    """延迟加载 cv2 模块"""
    global _cv2
    if _cv2 is None:
        import cv2
        _cv2 = cv2
    return _cv2

def _get_numpy():
    """延迟加载 numpy 模块"""
    global _numpy
    if _numpy is None:
        import numpy as np
        _numpy = np
    return _numpy


def _detect_gpu_type() -> str:
    """
    检测GPU类型
    
    返回:
        "nvidia" - 检测到NVIDIA GPU
        "amd" - 检测到AMD GPU
        "unknown" - 检测失败或没有独立GPU
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


_build_flavor_cache: str | None = None
_torch_cuda_probe_cache: tuple[bool, str, int, float] | None = None
_torch_cuda_probe_thread_started: bool = False
_torch_cuda_probe_thread_lock = threading.Lock()
_gpu_summary_thread_started: bool = False
_gpu_summary_thread_lock = threading.Lock()

# 日志限流控制
_gpu_log_last_time: dict[str, float] = {}
_gpu_log_min_interval: float = 5.0  # 相同日志的最小输出间隔（秒）


def _gpu_log(level: str, msg: str, throttle_key: str | None = None) -> None:
    """
    输出 GPU 相关日志，支持限流控制。
    
    参数：
        level: 日志级别 (debug, info, warning, error)
        msg: 日志消息
        throttle_key: 限流标识，相同 key 的日志在 _gpu_log_min_interval 秒内只输出一次
    """
    global _gpu_log_last_time
    try:
        if throttle_key is not None:
            now = float(time.monotonic())
            last_time = _gpu_log_last_time.get(str(throttle_key), 0.0)
            if float(now - last_time) < float(_gpu_log_min_interval):
                return
            _gpu_log_last_time[str(throttle_key)] = now
    except Exception:
        pass
    
    try:
        from utils.log_manager import LogManager

        logger = LogManager.instance()
        log_fn = getattr(logger, str(level or "debug").lower(), None)
        if callable(log_fn):
            log_fn(f"[TorchCUDA] {msg}")
            return
        logger.debug(f"[TorchCUDA] {msg}")
    except Exception:
        pass


def log_gpu_summary_async(reason: str = "manual", force: bool = False) -> None:
    """
    在后台线程输出一条 GPU/CUDA 环境摘要日志。

    默认做轻量去重，避免短时间内重复刷屏；`force=True` 可强制输出。
    """
    global _gpu_summary_thread_started
    try:
        with _gpu_summary_thread_lock:
            if bool(_gpu_summary_thread_started) and (not bool(force)):
                _gpu_log("debug", f"skip gpu summary: thread already started reason={reason}")
                return
            _gpu_summary_thread_started = True
    except Exception:
        return

    def _run():
        global _gpu_summary_thread_started
        try:
            summary = str(get_gpu_summary() or "").strip()
            if summary:
                _gpu_log("info", f"summary reason={reason} {summary}")
            else:
                _gpu_log("info", f"summary reason={reason} empty")
        except Exception as e:
            _gpu_log("warning", f"summary failed reason={reason} err={e}")
        finally:
            try:
                with _gpu_summary_thread_lock:
                    _gpu_summary_thread_started = False
            except Exception:
                _gpu_summary_thread_started = False

    try:
        t = threading.Thread(target=_run, name=f"GpuSummary-{reason}", daemon=True)
        t.start()
    except Exception as e:
        _gpu_log("warning", f"failed to start gpu summary thread reason={reason} err={e}")


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


def _should_probe_torch_cuda() -> bool:
    """
    判断当前运行形态下是否应该执行 torch CUDA 可用性探测。

    规则：
    - 开发态直接允许探测，避免源码运行时被固定判成 False；
    - 打包态仅 GPU 构建执行探测，CPU 包直接视为不可用。
    """
    try:
        if not bool(getattr(sys, "frozen", False)):
            return True
    except Exception:
        return True
    try:
        return bool(is_gpu_build())
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
    - 探测放到后台子线程中执行，避免阻塞调用线程；
    - 后续调用 is_torch_cuda_usable()/get_torch_cuda_check_brief() 直接复用缓存结果。

    参数：
    - force: True 表示强制重新启动探测（会清空缓存并重新探测）。
    """
    global _torch_cuda_probe_thread_started
    try:
        if not bool(_should_probe_torch_cuda()):
            _gpu_log("debug", "skip async probe: current runtime should not probe CUDA")
            return
    except Exception:
        return

    if bool(force):
        try:
            reset_torch_cuda_cache()
            _gpu_log("debug", "async probe requested with force=True, cache reset")
        except Exception:
            pass

    try:
        if bool(_torch_cuda_checked) or (_torch_cuda_probe_cache is not None):
            _gpu_log("debug", "skip async probe: cached result already exists")
            return
    except Exception:
        pass

    try:
        with _torch_cuda_probe_thread_lock:
            if bool(_torch_cuda_probe_thread_started):
                _gpu_log("debug", "skip async probe: background probe thread already started")
                return
            _torch_cuda_probe_thread_started = True
    except Exception:
        return

    def _run():
        global _torch_cuda_cache, _torch_cuda_checked, _torch_cuda_checked_at, _torch_cuda_checked_code
        try:
            _gpu_log("info", f"background probe start timeout_s={_get_torch_cuda_probe_timeout_s():.1f}")
            ok, _, code = _probe_torch_cuda(timeout_s=_get_torch_cuda_probe_timeout_s())
            try:
                _torch_cuda_cache = bool(ok)
                _torch_cuda_checked_code = int(code)
                _torch_cuda_checked = True
                _torch_cuda_checked_at = float(time.monotonic())
                _gpu_log(
                    "info" if bool(ok) else "warning",
                    f"background probe done ok={bool(ok)} code={int(code)} brief={get_torch_cuda_check_brief()}",
                )
                log_gpu_summary_async(reason="background_probe_done", force=True)
            except Exception:
                pass
        except Exception:
            try:
                _torch_cuda_cache = False
                _torch_cuda_checked = True
                _torch_cuda_checked_code = 12
                _torch_cuda_checked_at = float(time.monotonic())
                _gpu_log("warning", "background probe failed with unexpected exception, fallback to unavailable")
                log_gpu_summary_async(reason="background_probe_exception", force=True)
            except Exception:
                pass

    try:
        t = threading.Thread(target=_run, name="TorchCudaProbe", daemon=True)
        t.start()
        _gpu_log("debug", "background probe thread started")
    except Exception:
        _gpu_log("warning", "failed to start background probe thread")


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
        ok, out, code = _probe_torch_cuda(timeout_s=_get_torch_cuda_probe_timeout_s())
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
    global _torch_cuda_probe_cache, _torch_cuda_probe_thread_started
    _torch_cuda_probe_cache = None
    _torch_cuda_probe_thread_started = False
    _gpu_log("debug", "CUDA probe cache reset")


def _run_torch_cuda_action_in_thread(action: str, timeout_s: float = 5.0) -> tuple[bool, str, int]:
    """
    在子线程中执行 torch/CUDA 相关操作，避免阻塞调用线程。

    返回：
    - ok: 是否成功
    - out: 单行摘要文本
    - code: 0=成功, 2=不可用/未执行, 3=导入失败, 11=超时, 12=异常
    """
    result: dict[str, tuple[bool, str, int]] = {}
    done = threading.Event()
    t0 = float(time.perf_counter())

    try:
        _gpu_log("debug", f"thread action start action={action} timeout_s={float(timeout_s):.1f}")
    except Exception:
        pass

    def _worker():
        try:
            import torch

            if str(action) == "probe":
                v = str(getattr(torch, "__version__", "") or "")
                cuda = getattr(getattr(torch, "version", None), "cuda", None)
                ok = 0
                dc = -1
                name = ""
                err = ""
                try:
                    if bool(torch.cuda.is_available()):
                        dc = int(torch.cuda.device_count() or 0)
                        if dc > 0:
                            ok = 1
                            try:
                                name = str(torch.cuda.get_device_name(0) or "")
                            except Exception:
                                name = ""
                except Exception as e:
                    err = str(e)
                out = f"torch={v}|torch_cuda={cuda}|ok={ok}|dc={dc}|name0={name}|err={err}"
                result["value"] = (bool(ok), out, 0 if ok else 2)
                return

            if str(action) == "clear_cache":
                ok = 0
                err = ""
                try:
                    if bool(torch.cuda.is_available()):
                        torch.cuda.empty_cache()
                        ok = 1
                except Exception as e:
                    err = str(e)
                out = f"torch_cuda_cache_cleared={ok}|err={err}"
                result["value"] = (bool(ok), out, 0 if ok else 2)
                return

            result["value"] = (False, f"unknown_action={action}", 12)
        except Exception as e:
            if str(action) == "clear_cache":
                result["value"] = (False, f"torch_clear_cache_error={e}", 3)
            else:
                result["value"] = (False, f"torch_probe_error={e}", 3)
        finally:
            done.set()

    try:
        t = threading.Thread(target=_worker, name=f"TorchCudaAction-{action}", daemon=True)
        t.start()
    except Exception as e:
        _gpu_log("warning", f"thread action launch failed action={action} err={e}")
        return (False, f"run_error={e}", 12)

    if not done.wait(timeout=float(timeout_s)):
        elapsed_ms = float((time.perf_counter() - t0) * 1000.0)
        _gpu_log("warning", f"thread action timeout action={action} elapsed_ms={elapsed_ms:.1f}")
        return (False, "timeout", 11)

    out = result.get("value", (False, "thread_no_result", 12))
    try:
        elapsed_ms = float((time.perf_counter() - t0) * 1000.0)
        ok, out_txt, code = out
        level = "info" if bool(ok) else ("warning" if int(code) in (3, 11, 12) else "debug")
        _gpu_log(level, f"thread action done action={action} ok={bool(ok)} code={int(code)} elapsed_ms={elapsed_ms:.1f} out={str(out_txt)[:240]}")
    except Exception:
        pass
    return out


def _probe_torch_cuda(timeout_s: float = 5.0) -> tuple[bool, str, int]:
    global _torch_cuda_probe_cache
    
    # 在AMD GPU上跳过CUDA探测，直接返回不可用
    # 因为AMD GPU不支持CUDA，探测会导致torch导入错误
    gpu_type = _detect_gpu_type()
    if gpu_type == "amd":
        _gpu_log("info", "AMD GPU detected, skipping CUDA probe")
        return False, "amd_gpu_no_cuda", 2
    
    if _torch_cuda_probe_cache is not None:
        try:
            ok0, out0, code0, ts0 = _torch_cuda_probe_cache
            now = float(time.monotonic())
            age_s = float(now - float(ts0))
            ttl_s = 300.0 if (bool(ok0) or int(code0) == 2) else 30.0
            if age_s <= ttl_s:
                _gpu_log("debug", f"probe cache hit ok={bool(ok0)} code={int(code0)} age_s={age_s:.1f}")
                return bool(ok0), str(out0 or ""), int(code0)
            _torch_cuda_probe_cache = None
            _gpu_log("debug", f"probe cache expired code={int(code0)} age_s={age_s:.1f}")
        except Exception:
            _torch_cuda_probe_cache = None

    try:
        now = float(time.monotonic())
        ok, out_one, code = _run_torch_cuda_action_in_thread("probe", timeout_s=float(timeout_s))
        _torch_cuda_probe_cache = (bool(ok), str(out_one or ""), int(code), now)
        _gpu_log("debug", f"probe cache store ok={bool(ok)} code={int(code)}")
        return (bool(ok), str(out_one or ""), int(code))
    except Exception as e:
        now = float(time.monotonic())
        _torch_cuda_probe_cache = (False, f"run_error={e}", 12, now)
        _gpu_log("warning", f"probe execution failed err={e}")
        return (False, f"run_error={e}", 12)


def get_torch_cuda_check_brief() -> str:
    """
    获取 torch CUDA 探测的简短状态文本（不主动触发新的探测）。

    设计目标：
    - UI/日志需要展示“是否可用”与“为什么不可用”的关键原因；
    - 该函数尽量只读取已有缓存，避免在 UI 线程里触发新的探测并阻塞。
    """
    try:
        if not bool(_should_probe_torch_cuda()):
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


def _clear_torch_cuda_cache(timeout_s: float = 5.0) -> tuple[bool, str, int]:
    """
    在子线程中尝试执行 torch.cuda.empty_cache()。

    目的：
    - 避免在调用线程中直接执行清缓存逻辑，降低 UI 卡顿风险。

    参数：
    - timeout_s: 子线程等待时长上限（秒），超时后直接返回失败。

    返回：
    - (是否成功, 输出摘要, 退出码)
    """
    try:
        out = _run_torch_cuda_action_in_thread("clear_cache", timeout_s=float(timeout_s))
        try:
            ok, out_txt, code = out
            _gpu_log(
                "info" if bool(ok) else "warning",
                f"clear cache result ok={bool(ok)} code={int(code)} out={str(out_txt)[:240]}",
            )
        except Exception:
            pass
        return out
    except Exception as e:
        _gpu_log("warning", f"clear cache failed err={e}")
        return (False, f"run_error={e}", 12)


def try_clear_torch_cuda_cache(timeout_s: float = 4.0) -> bool:
    """
    尝试清理 torch CUDA 缓存（如果是 GPU 构建）。

    设计说明：
    - 开发态允许直接探测/清理；打包态仅 GPU 构建尝试执行；
    - 实际执行在子线程中完成，避免阻塞调用线程。

    参数：
    - timeout_s: 子线程等待时长上限（秒）。

    返回：
    - True 表示清理执行成功；False 表示未清理或清理失败（含超时/异常/非 GPU 构建）。
    """
    try:
        if not bool(_should_probe_torch_cuda()):
            return False
    except Exception:
        return False
    try:
        ok, _, _ = _clear_torch_cuda_cache(timeout_s=float(timeout_s))
        return bool(ok)
    except Exception:
        return False


def is_torch_cuda_usable() -> bool:
    global _torch_cuda_cache, _torch_cuda_checked, _torch_cuda_checked_at, _torch_cuda_checked_code
    
    # 如果已经检查过，直接返回缓存结果
    if _torch_cuda_checked:
        try:
            if bool(_torch_cuda_cache):
                _gpu_log("debug", "is_torch_cuda_usable return cached True", throttle_key="cuda_cached_true")
                return True
            if _torch_cuda_checked_at is None:
                _gpu_log("debug", "is_torch_cuda_usable return cached value without timestamp", throttle_key="cuda_cached_no_ts")
                return bool(_torch_cuda_cache)
            now = float(time.monotonic())
            age_s = float(now - float(_torch_cuda_checked_at))
            if float(age_s) <= 30.0:
                # 使用限流，避免频繁输出相同的缓存日志
                _gpu_log("debug", f"is_torch_cuda_usable return cached False age_s={age_s:.1f}", throttle_key="cuda_cached_false")
                return False
            _torch_cuda_checked = False
            _gpu_log("debug", "is_torch_cuda_usable cached False expired, re-probing")
        except Exception:
            return bool(_torch_cuda_cache)

    try:
        if not bool(_should_probe_torch_cuda()):
            _torch_cuda_cache = False
            _torch_cuda_checked = True
            _gpu_log("debug", "is_torch_cuda_usable skip probe because runtime should not probe")
            return False
    except Exception:
        _torch_cuda_cache = False
        _torch_cuda_checked = True
        _gpu_log("warning", "is_torch_cuda_usable failed to evaluate probe policy")
        return False
    
    try:
        ok, _, code = _probe_torch_cuda(timeout_s=_get_torch_cuda_probe_timeout_s())
        _torch_cuda_cache = bool(ok)
        _torch_cuda_checked_code = int(code)
        _gpu_log("info" if bool(ok) else "warning", f"is_torch_cuda_usable fresh probe result ok={bool(ok)} code={int(code)}")
    except Exception:
        _torch_cuda_cache = False
        _torch_cuda_checked_code = 12
        _gpu_log("warning", "is_torch_cuda_usable fresh probe raised exception")
    
    _torch_cuda_checked = True
    try:
        _torch_cuda_checked_at = float(time.monotonic())
    except Exception:
        _torch_cuda_checked_at = None
    return bool(_torch_cuda_cache)


def is_opencv_cuda_usable() -> bool:
    try:
        cv2 = _get_cv2()
        if not hasattr(cv2, "cuda"):
            return False
        return int(cv2.cuda.getCudaEnabledDeviceCount() or 0) > 0
    except Exception:
        return False


def _gpu_utils_debug(msg: str) -> None:
    """Debug log for GPU utils; no-op if LogManager unavailable."""
    try:
        from utils.log_manager import LogManager
        LogManager.instance().debug(f"[GPUUtils] {msg}")
    except Exception:
        pass


def get_gpu_vram_info() -> dict:
    """
    获取当前 GPU 显存信息。无 CUDA 时返回 available=False，不抛错。

    返回: {
        "total_mb": int,
        "free_mb": int,
        "used_mb": int,
        "device_name": str,
        "available": bool,
        "error": str,
    }
    """
    result = {
        "total_mb": 0,
        "free_mb": 0,
        "used_mb": 0,
        "device_name": "",
        "available": False,
        "error": "",
    }
    try:
        import torch
        if not torch.cuda.is_available():
            result["error"] = "CUDA not available"
            _gpu_utils_debug(f"get_gpu_vram_info: {result['error']}")
            return result
        dev = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(dev)
        total_bytes = int(getattr(props, "total_memory", 0) or 0)
        result["total_mb"] = total_bytes // (1024 * 1024)
        result["device_name"] = str(getattr(props, "name", "") or "")
        try:
            free_bytes, total_alloc = torch.cuda.mem_get_info(dev)
            result["free_mb"] = int(free_bytes) // (1024 * 1024)
            result["used_mb"] = result["total_mb"] - result["free_mb"]
        except Exception:
            try:
                result["used_mb"] = int(torch.cuda.memory_allocated(dev)) // (1024 * 1024)
                result["free_mb"] = max(0, result["total_mb"] - result["used_mb"])
            except Exception:
                result["free_mb"] = 0
        result["available"] = True
        _gpu_utils_debug(
            f"get_gpu_vram_info: total_mb={result['total_mb']} free_mb={result['free_mb']} "
            f"used_mb={result['used_mb']} device={result['device_name'][:32]}"
        )
        return result
    except ImportError:
        result["error"] = "PyTorch not installed"
        _gpu_utils_debug(f"get_gpu_vram_info: {result['error']}")
        return result
    except Exception as e:
        result["error"] = str(e)
        _gpu_utils_debug(f"get_gpu_vram_info: error={e}")
        return result


def recommend_gpu_batch_size(
    model_size: str,
    target_size: int,
    vram_info: dict | None = None,
) -> int:
    """
    根据显存与模型规模推荐 GPU batch size。
    无 GPU 或 vram_info["available"] 为 False 时返回 1。
    """
    if vram_info is None:
        vram_info = get_gpu_vram_info()
    if not vram_info.get("available", False):
        _gpu_utils_debug("recommend_gpu_batch_size: no GPU, return 1")
        return 1
    free_mb = int(vram_info.get("free_mb", 0) or 0)
    reserve_mb = 500
    available_mb = max(0, free_mb - reserve_mb)
    model_lower = str(model_size or "x").strip().lower()
    base_mb = {"n": 200, "s": 300, "m": 500, "l": 700, "x": 900}.get(model_lower, 900)
    per_image_mb = {"n": 50, "s": 80, "m": 120, "l": 180, "x": 250}.get(model_lower, 250)
    try:
        ts = int(target_size or 640)
    except Exception:
        ts = 640
    scale = (ts / 640.0) ** 2
    per_image_mb = int(per_image_mb * scale)
    if available_mb <= base_mb:
        _gpu_utils_debug(f"recommend_gpu_batch_size: available_mb={available_mb} <= base_mb={base_mb}, return 1")
        return 1
    batch = (available_mb - base_mb) // max(1, per_image_mb)
    batch = max(1, min(16, batch))
    _gpu_utils_debug(
        f"recommend_gpu_batch_size: model={model_lower} target_size={ts} "
        f"free_mb={free_mb} -> batch={batch}"
    )
    return batch


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
                cv2 = _get_cv2()
                if hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                    cls._backend = "cuda"
            except Exception:
                cls._backend = None
            if cls._backend is None:
                try:
                    cv2 = _get_cv2()
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
            np = _get_numpy()
            cv2 = _get_cv2()
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

    @classmethod
    def scale_numpy(
        cls,
        arr: np.ndarray,
        target_w: int,
        target_h: int,
        interpolation=None,
        keep_aspect: bool = True,
    ) -> np.ndarray | None:
        """
        直接对 numpy BGR 数组做 GPU 缩放，省去 QImage 转换。
        CUDA/OpenCL 路径: upload → resize → download（3 步）。
        不可用或异常时返回 None，调用方需 fallback 到 cv2.resize。
        """
        if arr is None or not hasattr(arr, "shape") or arr.size == 0:
            return None
        try:
            if bool(getattr(cls, "_suspended", False)):
                return None
        except Exception:
            return None
        if not cls.is_available():
            return None
        try:
            cv2 = _get_cv2()
            np = _get_numpy()
            h, w = int(arr.shape[0]), int(arr.shape[1])
            if w <= 0 or h <= 0:
                return None
            if keep_aspect:
                scale = min(float(target_w) / w, float(target_h) / h)
                new_w = max(1, int(round(w * scale)))
                new_h = max(1, int(round(h * scale)))
            else:
                new_w = max(1, int(target_w))
                new_h = max(1, int(target_h))
            if new_w == w and new_h == h:
                return arr.copy()
            interp = interpolation if interpolation is not None else cv2.INTER_LINEAR
            if cls._backend == "cuda":
                gpu_mat = cv2.cuda_GpuMat()
                gpu_mat.upload(arr)
                resized = cv2.cuda.resize(gpu_mat, (new_w, new_h), interpolation=interp)
                out = resized.download()
            elif cls._backend == "opencl":
                umat = cv2.UMat(arr)
                resized = cv2.resize(umat, (new_w, new_h), interpolation=interp)
                out = resized.get()
            else:
                return None
            if out is None:
                return None
            _gpu_utils_debug(f"scale_numpy: {w}x{h} -> {new_w}x{new_h} backend={cls._backend}")
            return np.ascontiguousarray(out)
        except Exception as e:
            _gpu_utils_debug(f"scale_numpy: error={e}")
            return None
