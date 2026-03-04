import csv
import io
import os
import re
import shutil
import subprocess
import sys
import time

_WIN_GPU_BACKEND_HINT = None
_SUPPRESS_UNTIL = 0.0
_PAUSE_COUNT = 0


def suppress_gpu_query(seconds: float = 1.8):
    global _SUPPRESS_UNTIL
    try:
        now = float(time.monotonic())
    except Exception:
        return
    try:
        sec = float(seconds)
    except Exception:
        sec = 1.8
    if sec <= 0:
        return
    try:
        _SUPPRESS_UNTIL = max(float(_SUPPRESS_UNTIL or 0.0), now + sec)
    except Exception:
        _SUPPRESS_UNTIL = now + sec


def enter_gpu_query_pause() -> bool:
    global _PAUSE_COUNT
    try:
        _PAUSE_COUNT = int(_PAUSE_COUNT or 0) + 1
        return True
    except Exception:
        _PAUSE_COUNT = 1
        return True


def exit_gpu_query_pause():
    global _PAUSE_COUNT
    try:
        c = int(_PAUSE_COUNT or 0) - 1
    except Exception:
        c = 0
    _PAUSE_COUNT = max(0, int(c))


def _subprocess_no_console_kwargs() -> dict:
    try:
        if sys.platform != "win32":
            return {}
        try:
            from utils.setting.settings_manager import SettingsManager

            hide = bool(SettingsManager.instance().get("system/hide_subprocess_console", True))
        except Exception:
            hide = True
        if not hide:
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
    except Exception:
        return {}


def _run_cmd(args: list[str], timeout_s: float) -> str:
    try:
        if int(_PAUSE_COUNT or 0) > 0:
            return ""
    except Exception:
        pass
    try:
        if os.name == "nt" and float(time.monotonic()) < float(_SUPPRESS_UNTIL or 0.0):
            return ""
    except Exception:
        pass
    try:
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, timeout=float(timeout_s), **_subprocess_no_console_kwargs())
        return out.decode("utf-8", errors="ignore").strip()
    except subprocess.CalledProcessError as e:
        try:
            out = e.output or b""
            return out.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""
    except Exception:
        return ""


def _parse_float_loose(s: str) -> float | None:
    if not s:
        return None
    try:
        raw = str(s).strip().strip('"').strip()
    except Exception:
        return None
    if not raw:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", raw)
    if not m:
        return None
    t = m.group(0)
    try:
        t = t.replace(",", ".")
    except Exception:
        t = t
    try:
        return float(t)
    except Exception:
        return None


def _format_percent(v: float | None) -> str:
    if v is None:
        return "--"
    try:
        if v < 0:
            return "--"
        if v > 10000:
            return "--"
        v = float(v)
        if v < 1.0:
            return f"{v:.2f}%"
        return f"{v:.1f}%"
    except Exception:
        return "--"


def _try_gputil() -> float | None:
    try:
        import GPUtil
    except Exception:
        GPUtil = None
    if not GPUtil:
        return None
    try:
        gpus = GPUtil.getGPUs() or []
    except Exception:
        gpus = []
    if not gpus:
        return None
    discrete = []
    for gpu in gpus:
        try:
            name = str(getattr(gpu, "name", "") or "").lower()
        except Exception:
            name = ""
        if "intel" in name or "uhd" in name or "iris" in name:
            continue
        discrete.append(gpu)
    candidates = discrete if discrete else gpus
    values = []
    for gpu in candidates:
        try:
            values.append(float(getattr(gpu, "load", 0.0) or 0.0) * 100.0)
        except Exception:
            continue
    if not values:
        return None
    try:
        return float(max(values))
    except Exception:
        return None


def _try_nvidia_smi(timeout_s: float) -> float | None:
    exe = None
    try:
        exe = shutil.which("nvidia-smi")
    except Exception:
        exe = None
    if not exe:
        try:
            cands = [
                os.path.join(os.environ.get("ProgramW6432", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"),
                os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"),
                os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"),
            ]
        except Exception:
            cands = []
        for p in cands:
            try:
                if p and os.path.exists(p):
                    exe = p
                    break
            except Exception:
                continue
    if not exe:
        return None
    out = _run_cmd(
        [str(exe), "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
        timeout_s=timeout_s,
    )
    if not out:
        return None
    values = []
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        v = _parse_float_loose(s)
        if v is not None:
            values.append(v)
    if not values:
        return None
    try:
        return float(max(values))
    except Exception:
        return None


def _try_windows_gpu_engine_typeperf(timeout_s: float) -> float | None:
    if os.name != "nt":
        return None
    if shutil.which("typeperf") is None:
        return None
    out = _run_cmd(["typeperf", r"\GPU Engine(*)\Utilization Percentage", "-sc", "2"], timeout_s=max(1.0, float(timeout_s)))
    if not out:
        return None
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return None
    best_values: list[float] = []
    for line in reversed(lines):
        try:
            hits = re.findall(r"\"(-?\d+(?:[.,]\d+)?)\"", line)
        except Exception:
            hits = []
        values = []
        if hits:
            for h in hits:
                v = _parse_float_loose(h)
                if v is not None:
                    values.append(v)
        if not values:
            try:
                reader = csv.reader(io.StringIO(line))
                row = next(reader, [])
            except Exception:
                row = []
            if isinstance(row, list) and len(row) >= 2:
                for item in row[1:]:
                    v = _parse_float_loose(item)
                    if v is not None:
                        values.append(v)
        if values:
            best_values = values
            break
    if not best_values:
        return None
    try:
        mx = float(max(best_values))
        s = float(sum(best_values))
        v = mx if mx >= s else s
        if v > 100.0:
            v = 100.0
        return float(v)
    except Exception:
        return None


def _try_windows_gpu_engine_powershell(timeout_s: float) -> float | None:
    if os.name != "nt":
        return None
    if shutil.which("powershell") is None:
        return None
    out = _run_cmd(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -SampleInterval 1 -MaxSamples 2 | Select -ExpandProperty CounterSamples | Select -ExpandProperty CookedValue",
        ],
        timeout_s=max(1.0, float(timeout_s)),
    )
    if not out:
        return None
    values = []
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        v = _parse_float_loose(s)
        if v is not None:
            values.append(v)
    if not values:
        return None
    try:
        mx = float(max(values))
        s = float(sum(values))
        v = mx if mx >= s else s
        if v > 100.0:
            v = 100.0
        return float(v)
    except Exception:
        return None


def _try_windows_gpu_engine_powershell_burst(timeout_s: float) -> float | None:
    if os.name != "nt":
        return None
    if shutil.which("powershell") is None:
        return None
    try:
        t = float(timeout_s)
    except Exception:
        t = 2.0
    if t <= 1.2:
        sample_interval = 0.1
        max_samples = 3
    elif t <= 2.4:
        sample_interval = 0.2
        max_samples = 5
    else:
        sample_interval = 0.2
        max_samples = 8
    out = _run_cmd(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -SampleInterval {sample_interval} -MaxSamples {max_samples} | Select -ExpandProperty CounterSamples | Select -ExpandProperty CookedValue",
        ],
        timeout_s=max(1.2, t),
    )
    if not out:
        return None
    values = []
    for line in out.splitlines():
        v = _parse_float_loose(line)
        if v is not None:
            values.append(v)
    if not values:
        return None
    try:
        mx = float(max(values))
        s = float(sum(values))
        v = mx if mx >= s else s
        if v > 100.0:
            v = 100.0
        return float(v)
    except Exception:
        return None


def _try_windows_gpu_engine_autodiscover(timeout_s: float) -> float | None:
    if os.name != "nt":
        return None
    if shutil.which("powershell") is None:
        return None
    ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = @()
try {
  $sets = Get-Counter -ListSet '*GPU*'
  foreach ($s in $sets) { $paths += $s.PathsWithInstances }
} catch {}
$paths = $paths | Where-Object { $_ }
$paths = $paths | Where-Object { $_ -match 'GPU' }
$paths = $paths | Where-Object { $_ -match 'Engine' -or $_ -match '引擎' -or $_ -match 'Adapter' -or $_ -match '适配器' }
$paths = $paths | Where-Object { $_ -match 'Util' -or $_ -match '利用率' -or $_ -match '使用率' -or $_ -match 'Percentage' -or $_ -match '百分比' }
$paths = $paths | Select-Object -Unique
$paths = $paths | Select-Object -First 200
if (-not $paths -or $paths.Count -le 0) { exit 0 }
(Get-Counter -Counter $paths -SampleInterval 0.2 -MaxSamples 5).CounterSamples | Select -ExpandProperty CookedValue
"""
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(1.5, float(timeout_s)))
    if not out:
        return None
    values = []
    for line in out.splitlines():
        v = _parse_float_loose(line)
        if v is not None:
            values.append(v)
    if not values:
        return None
    try:
        mx = float(max(values))
        s = float(sum(values))
        v = mx if mx >= s else s
        if v > 100.0:
            v = 100.0
        return float(v)
    except Exception:
        return None


def _try_macos_powermetrics(timeout_s: float) -> float | None:
    if sys.platform != "darwin":
        return None
    pm = shutil.which("powermetrics") or "/usr/sbin/powermetrics"
    if not pm or not os.path.exists(pm):
        return None
    out = _run_cmd([pm, "-n", "1", "--samplers", "gpu_power"], timeout_s=max(1.0, float(timeout_s)))
    if not out:
        return None
    m = re.search(r"GPU\s+active\s+residency:\s*([0-9]+(?:\.[0-9]+)?)%", out, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"GPU\s+utilization:\s*([0-9]+(?:\.[0-9]+)?)%", out, flags=re.IGNORECASE)
    if not m:
        return None
    return _parse_float_loose(m.group(1))


def _try_linux_rocm_smi(timeout_s: float) -> float | None:
    if not sys.platform.startswith("linux"):
        return None
    tool = shutil.which("rocm-smi")
    if not tool:
        return None
    out = _run_cmd([tool, "--showuse"], timeout_s=timeout_s)
    if not out:
        return None
    values = []
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.search(r"GPU\s+use\s*\(%\)\s*:\s*([0-9]+)", s, flags=re.IGNORECASE)
        if not m:
            continue
        v = _parse_float_loose(m.group(1))
        if v is not None:
            values.append(v)
    if not values:
        return None
    try:
        return float(max(values))
    except Exception:
        return None


def _try_windows_gpu_engine_cim(timeout_s: float) -> float | None:
    if os.name != "nt":
        return None
    if shutil.which("powershell") is None:
        return None
    cmds = [
        "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | Select -ExpandProperty UtilizationPercentage",
        "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapter | Select -ExpandProperty UtilizationPercentage",
    ]
    for ps in cmds:
        out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(0.8, float(timeout_s)))
        if not out:
            continue
        values = []
        for line in out.splitlines():
            v = _parse_float_loose(line)
            if v is not None:
                values.append(v)
        if values:
            try:
                mx = float(max(values))
                s = float(sum(values))
                v = mx if mx >= s else s
                if v > 100.0:
                    v = 100.0
                return float(v)
            except Exception:
                return None
    return None


def get_gpu_util_percent(timeout_s: float = 1.0) -> float | None:
    global _WIN_GPU_BACKEND_HINT
    try:
        if int(_PAUSE_COUNT or 0) > 0:
            return None
    except Exception:
        pass
    try:
        if os.name == "nt" and float(time.monotonic()) < float(_SUPPRESS_UNTIL or 0.0):
            return None
    except Exception:
        pass
    best = None
    best_backend = None
    funcs: list[tuple[str, callable]] = [
        ("nvidia-smi", lambda: _try_nvidia_smi(timeout_s=timeout_s)),
        ("gputil", lambda: _try_gputil()),
        ("typeperf", lambda: _try_windows_gpu_engine_typeperf(timeout_s=timeout_s)),
        ("cim", lambda: _try_windows_gpu_engine_cim(timeout_s=max(0.8, timeout_s * 1.2))),
        ("get-counter", lambda: _try_windows_gpu_engine_powershell(timeout_s=max(0.5, timeout_s * 1.5))),
        ("rocm-smi", lambda: _try_linux_rocm_smi(timeout_s=timeout_s)),
        ("powermetrics", lambda: _try_macos_powermetrics(timeout_s=max(1.0, timeout_s * 2.0))),
    ]
    if os.name == "nt" and _WIN_GPU_BACKEND_HINT:
        try:
            hint = str(_WIN_GPU_BACKEND_HINT or "")
        except Exception:
            hint = ""
        if hint:
            try:
                i = next((idx for idx, (n, _) in enumerate(funcs) if n == hint), None)
            except Exception:
                i = None
            if isinstance(i, int):
                funcs = [funcs[i]] + [x for j, x in enumerate(funcs) if j != i]
    for fn in funcs:
        try:
            name, f = fn
            v = f()
        except Exception:
            v = None
        if v is None:
            continue
        try:
            v = float(v)
        except Exception:
            continue
        if best is None or v > best:
            best = v
            best_backend = name
        if best is not None and best >= 95.0:
            if os.name == "nt" and best_backend:
                _WIN_GPU_BACKEND_HINT = str(best_backend)
            return best
    if best is None or best <= 0.0:
        try:
            v = _try_windows_gpu_engine_powershell_burst(timeout_s=max(1.5, timeout_s * 2.0))
        except Exception:
            v = None
        if v is not None:
            try:
                v = float(v)
            except Exception:
                v = None
            if v is not None and (best is None or v > best):
                best = v
                best_backend = "get-counter-burst"
    if best is None or best <= 0.0:
        try:
            v = _try_windows_gpu_engine_autodiscover(timeout_s=max(2.0, timeout_s * 2.5))
        except Exception:
            v = None
        if v is not None:
            try:
                v = float(v)
            except Exception:
                v = None
            if v is not None and (best is None or v > best):
                best = v
                best_backend = "autodiscover"
    if os.name == "nt" and best_backend and best is not None and best > 0.0:
        _WIN_GPU_BACKEND_HINT = str(best_backend)
    return best


def get_gpu_util_text(timeout_s: float = 1.0) -> str:
    return _format_percent(get_gpu_util_percent(timeout_s=timeout_s))
