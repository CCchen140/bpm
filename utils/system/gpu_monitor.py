import csv
import io
import os
import re
import shutil
import subprocess
import sys

_WIN_GPU_BACKEND_HINT = None


def _run_cmd(args: list[str], timeout_s: float) -> str:
    try:
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, timeout=float(timeout_s))
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
    if shutil.which("nvidia-smi") is None:
        return None
    out = _run_cmd(
        ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
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
    best = None
    best_backend = None
    funcs: list[tuple[str, callable]] = [
        ("gputil", lambda: _try_gputil()),
        ("nvidia-smi", lambda: _try_nvidia_smi(timeout_s=timeout_s)),
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
