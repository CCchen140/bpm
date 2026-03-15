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
        # 不设置 DETACHED_PROCESS，与 CREATE_NO_WINDOW 同时使用可能导致控制台闪烁
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
        ("adapter-total", lambda: _try_windows_gpu_adapter_total(timeout_s=max(1.0, timeout_s * 1.2))),
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
    if best is None or best <= 0.0:
        try:
            adapters = _try_windows_video_controller_info(timeout_s=max(0.8, timeout_s)) or []
        except Exception:
            adapters = []
        if adapters:
            best = 0.0
            best_backend = "fallback"
    if os.name == "nt" and best_backend and best is not None and best > 0.0:
        _WIN_GPU_BACKEND_HINT = str(best_backend)
    return best


def get_gpu_util_text(timeout_s: float = 1.0) -> str:
    return _format_percent(get_gpu_util_percent(timeout_s=timeout_s))


def _clamp_percent(v: float | None) -> float | None:
    if v is None:
        return None
    try:
        out = float(v)
    except Exception:
        return None
    if out < 0:
        out = 0.0
    if out > 100.0:
        out = 100.0
    return out


def _guess_gpu_vendor(name: str) -> str:
    try:
        low = str(name or "").strip().lower()
    except Exception:
        low = ""
    if not low:
        return ""
    if ("nvidia" in low) or ("geforce" in low) or ("quadro" in low) or ("rtx" in low) or ("gtx" in low):
        return "nvidia"
    if ("amd" in low) or ("radeon" in low) or ("firepro" in low) or ("rx " in low) or ("vega" in low):
        return "amd"
    if ("intel" in low) or ("uhd" in low) or ("iris" in low) or ("arc " in low):
        return "intel"
    return "other"


def _score_gpu_adapter(info: dict) -> tuple[int, float]:
    vendor = str(info.get("vendor") or "").strip().lower()
    if vendor == "nvidia":
        vendor_score = 4
    elif vendor == "amd":
        vendor_score = 3
    elif vendor == "intel":
        vendor_score = 2
    else:
        vendor_score = 1
    try:
        ram_mb = float(info.get("memory_total_mb") or 0.0)
    except Exception:
        ram_mb = 0.0
    return vendor_score, ram_mb


def _try_windows_video_controller_info(timeout_s: float) -> list[dict]:
    if os.name != "nt":
        return []
    if shutil.which("powershell") is None:
        return []
    ps = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM | ConvertTo-Csv -NoTypeInformation"
    )
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(0.8, float(timeout_s)))
    if not out:
        return []
    try:
        rows = csv.DictReader(io.StringIO(out))
    except Exception:
        rows = []
    items: list[dict] = []
    for row in rows:
        try:
            name = str((row or {}).get("Name", "") or "").strip()
        except Exception:
            name = ""
        if not name:
            continue
        low = name.lower()
        if ("microsoft basic" in low) or ("remote display" in low) or ("virtual" in low):
            continue
        ram_bytes = _parse_float_loose((row or {}).get("AdapterRAM", ""))
        item = {
            "name": name,
            "vendor": _guess_gpu_vendor(name),
            "memory_total_mb": None if ram_bytes is None else float(ram_bytes) / 1024.0 / 1024.0,
            "source": "win32-video-controller",
        }
        items.append(item)
    try:
        items.sort(key=_score_gpu_adapter, reverse=True)
    except Exception:
        pass
    return items


def _try_windows_gpu_memory_detail(timeout_s: float) -> dict:
    if os.name != "nt":
        return {}
    if shutil.which("powershell") is None:
        return {}
    ps = (
        "Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage','\\GPU Adapter Memory(*)\\Shared Usage' "
        "-SampleInterval 0.2 -MaxSamples 2 | "
        "Select-Object -ExpandProperty CounterSamples | "
        "Select-Object Path,CookedValue | ConvertTo-Csv -NoTypeInformation"
    )
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(1.2, float(timeout_s)))
    if not out:
        return {}
    dedicated_vals: list[float] = []
    shared_vals: list[float] = []
    try:
        rows = csv.DictReader(io.StringIO(out))
    except Exception:
        rows = []
    for row in rows:
        try:
            path = str((row or {}).get("Path", "") or "").strip().lower()
        except Exception:
            path = ""
        raw = _parse_float_loose((row or {}).get("CookedValue", ""))
        if raw is None:
            continue
        mb = float(raw) / 1024.0 / 1024.0
        if "dedicated usage" in path:
            dedicated_vals.append(mb)
        elif "shared usage" in path:
            shared_vals.append(mb)
    detail = {}
    if dedicated_vals:
        detail["memory_dedicated_mb"] = float(max(dedicated_vals))
    if shared_vals:
        detail["memory_shared_mb"] = float(max(shared_vals))
    if ("memory_dedicated_mb" in detail) or ("memory_shared_mb" in detail):
        detail["memory_used_mb"] = float(detail.get("memory_dedicated_mb", 0.0) or 0.0) + float(detail.get("memory_shared_mb", 0.0) or 0.0)
        detail["memory_source"] = "gpu-adapter-memory"
    return detail


def _try_nvidia_smi_detail(timeout_s: float) -> dict | None:
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
        [
            str(exe),
            "--query-gpu=name,utilization.gpu,utilization.memory,utilization.encoder,utilization.decoder,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout_s=max(1.0, float(timeout_s)),
    )
    if not out:
        return None
    best = None
    try:
        rows = csv.reader(io.StringIO(out))
    except Exception:
        rows = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            continue
        try:
            name = str(row[0] or "").strip()
        except Exception:
            name = ""
        total = _parse_float_loose(row[1] if len(row) > 1 else "")
        mem_util = _parse_float_loose(row[2] if len(row) > 2 else "")
        encode = _parse_float_loose(row[3] if len(row) > 3 else "")
        decode = _parse_float_loose(row[4] if len(row) > 4 else "")
        mem_used = _parse_float_loose(row[5] if len(row) > 5 else "")
        mem_total = _parse_float_loose(row[6] if len(row) > 6 else "")
        item = {
            "name": name,
            "total": _clamp_percent(total),
            "memory": _clamp_percent(mem_util),
            "encode": _clamp_percent(encode),
            "decode": _clamp_percent(decode),
            "memory_used_mb": mem_used,
            "memory_total_mb": mem_total,
            "source": "nvidia-smi",
        }
        score = item.get("total")
        try:
            score = float(score if score is not None else -1.0)
        except Exception:
            score = -1.0
        if best is None or score > float(best.get("total") if best.get("total") is not None else -1.0):
            best = item
    return best


def _try_windows_gpu_engine_groups(timeout_s: float) -> dict[str, float]:
    if os.name != "nt":
        return {}
    if shutil.which("powershell") is None:
        return {}
    ps = (
        "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | "
        "Select-Object Name,UtilizationPercentage | ConvertTo-Csv -NoTypeInformation"
    )
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(1.0, float(timeout_s)))
    if not out:
        return {}
    groups: dict[str, list[float]] = {
        "compute": [],
        "decode": [],
        "encode": [],
        "copy": [],
        "3d": [],
    }
    try:
        rows = csv.DictReader(io.StringIO(out))
    except Exception:
        rows = []
    for row in rows:
        try:
            name = str((row or {}).get("Name", "") or "").strip().lower()
        except Exception:
            name = ""
        val = _parse_float_loose((row or {}).get("UtilizationPercentage", ""))
        if val is None:
            continue
        if ("compute" in name) or ("cuda" in name):
            groups["compute"].append(val)
        if ("videodecode" in name) or ("video decode" in name) or ("decode" in name):
            groups["decode"].append(val)
        if ("videoencode" in name) or ("video encode" in name) or ("encode" in name):
            groups["encode"].append(val)
        if "copy" in name:
            groups["copy"].append(val)
        if re.search(r"(^|[^a-z0-9])3d([^a-z0-9]|$)", name):
            groups["3d"].append(val)
    out_groups: dict[str, float] = {}
    for key, values in groups.items():
        if not values:
            continue
        try:
            out_groups[key] = float(min(100.0, max(values)))
        except Exception:
            continue
    return out_groups


def _collect_gpu_engine_group(groups: dict[str, list[float]], name: str, value: float):
    try:
        low = str(name or "").strip().lower()
    except Exception:
        low = ""
    if not low:
        return
    if ("compute" in low) or ("cuda" in low) or ("engtype_compute" in low):
        groups["compute"].append(value)
    if ("videodecode" in low) or ("video decode" in low) or ("engtype_videodecode" in low):
        groups["decode"].append(value)
    if ("videoencode" in low) or ("video encode" in low) or ("engtype_videoencode" in low):
        groups["encode"].append(value)
    if "engtype_copy" in low or "copy" in low:
        groups["copy"].append(value)
    if re.search(r"(^|[^a-z0-9])3d([^a-z0-9]|$)", low) or "engtype_3d" in low:
        groups["3d"].append(value)


def _finalize_gpu_engine_groups(groups: dict[str, list[float]]) -> dict[str, float]:
    out_groups: dict[str, float] = {}
    for key, values in groups.items():
        if not values:
            continue
        try:
            out_groups[key] = float(min(100.0, max(values)))
        except Exception:
            continue
    return out_groups


def _try_windows_gpu_engine_groups_typeperf(timeout_s: float) -> dict[str, float]:
    if os.name != "nt":
        return {}
    if shutil.which("typeperf") is None:
        return {}
    out = _run_cmd(["typeperf", r"\GPU Engine(*)\Utilization Percentage", "-sc", "2"], timeout_s=max(1.0, float(timeout_s)))
    if not out:
        return {}
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if len(lines) < 2:
        return {}
    header_line = ""
    value_line = ""
    for line in lines:
        if "GPU Engine(" in line and "\\Utilization Percentage" in line:
            header_line = line
            continue
        if header_line:
            value_line = line
    if not header_line or not value_line:
        return {}
    try:
        headers = next(csv.reader(io.StringIO(header_line)))
        values = next(csv.reader(io.StringIO(value_line)))
    except Exception:
        return {}
    groups: dict[str, list[float]] = {
        "compute": [],
        "decode": [],
        "encode": [],
        "copy": [],
        "3d": [],
    }
    try:
        pairs = zip(headers[1:], values[1:])
    except Exception:
        pairs = []
    for header_name, raw_value in pairs:
        val = _parse_float_loose(raw_value)
        if val is None:
            continue
        _collect_gpu_engine_group(groups, str(header_name or ""), float(val))
    return _finalize_gpu_engine_groups(groups)


def _try_windows_gpu_engine_groups_powershell(timeout_s: float) -> dict[str, float]:
    if os.name != "nt":
        return {}
    if shutil.which("powershell") is None:
        return {}
    ps = (
        "Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -SampleInterval 0.2 -MaxSamples 3 | "
        "Select-Object -ExpandProperty CounterSamples | "
        "Select-Object Path,CookedValue | ConvertTo-Csv -NoTypeInformation"
    )
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(1.2, float(timeout_s)))
    if not out:
        return {}
    groups: dict[str, list[float]] = {
        "compute": [],
        "decode": [],
        "encode": [],
        "copy": [],
        "3d": [],
    }
    try:
        rows = csv.DictReader(io.StringIO(out))
    except Exception:
        rows = []
    for row in rows:
        try:
            path = str((row or {}).get("Path", "") or "")
        except Exception:
            path = ""
        val = _parse_float_loose((row or {}).get("CookedValue", ""))
        if val is None:
            continue
        _collect_gpu_engine_group(groups, path, float(val))
    return _finalize_gpu_engine_groups(groups)


def _try_generic_gpu_activity(timeout_s: float) -> dict[str, float] | None:
    """
    尝试通过通用的 GPU 性能计数器获取 GPU 活动信息。
    适用于 AMD 等没有专用引擎计数器的显卡。
    """
    if os.name != "nt":
        return None
    if shutil.which("powershell") is None:
        return None
    # 尝试查找所有 GPU 相关的性能计数器
    ps = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "$counters = @(); "
        "try { "
        "  $sets = Get-Counter -ListSet '*GPU*' | Where-Object { $_.CounterSetName -notmatch 'Engine|Process' } "
        "} catch { $sets = @() }; "
        "foreach ($s in $sets) { "
        "  foreach ($p in $s.PathsWithInstances) { "
        "    if ($p -match 'Utilization|Usage|Activity|Busy|Load') { $counters += $p } "
        "  } "
        "}; "
        "if ($counters.Count -eq 0) { exit 0 }; "
        "(Get-Counter -Counter $counters -SampleInterval 0.2 -MaxSamples 2).CounterSamples | "
        "Select-Object Path,CookedValue | ConvertTo-Csv -NoTypeInformation"
    )
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(1.5, float(timeout_s)))
    if not out:
        return None
    activity_vals: list[float] = []
    try:
        rows = csv.DictReader(io.StringIO(out))
    except Exception:
        rows = []
    for row in rows:
        try:
            path = str((row or {}).get("Path", "") or "").strip().lower()
        except Exception:
            path = ""
        val = _parse_float_loose((row or {}).get("CookedValue", ""))
        if val is None:
            continue
        # 过滤掉进程相关的计数器，只保留 GPU 整体活动
        if "process" in path or "pid" in path:
            continue
        # 接受各种 GPU 活动指标
        if any(k in path for k in ["utilization", "usage", "activity", "busy", "load"]):
            activity_vals.append(float(val))
    if not activity_vals:
        return None
    try:
        return {"total": float(min(100.0, max(activity_vals)))}
    except Exception:
        return None


def _try_amd_gpu_activity(timeout_s: float) -> dict[str, float] | None:
    """
    尝试通过 AMD 显卡特定的性能计数器获取 GPU 活动信息。
    AMD 显卡在 Windows 上通常使用 'GPU Activity' 或 'GPU Utilization' 计数器。
    """
    if os.name != "nt":
        return None
    if shutil.which("powershell") is None:
        return None
    # 尝试查找 AMD GPU 相关的性能计数器
    ps = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "$counters = @(); "
        "try { $sets = Get-Counter -ListSet '*GPU*' | Where-Object { $_.CounterSetName -match 'AMD|Radeon|GPU' } } catch { $sets = @() }; "
        "foreach ($s in $sets) { "
        "  foreach ($p in $s.PathsWithInstances) { "
        "    if ($p -match 'Activity|Utilization|Usage|Busy') { $counters += $p } "
        "  } "
        "}; "
        "if ($counters.Count -eq 0) { exit 0 }; "
        "(Get-Counter -Counter $counters -SampleInterval 0.2 -MaxSamples 2).CounterSamples | "
        "Select-Object Path,CookedValue | ConvertTo-Csv -NoTypeInformation"
    )
    out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(1.5, float(timeout_s)))
    if not out:
        return None
    activity_vals: list[float] = []
    try:
        rows = csv.DictReader(io.StringIO(out))
    except Exception:
        rows = []
    for row in rows:
        try:
            path = str((row or {}).get("Path", "") or "").strip().lower()
        except Exception:
            path = ""
        val = _parse_float_loose((row or {}).get("CookedValue", ""))
        if val is None:
            continue
        # AMD 显卡通常有 "GPU Activity" 或 "GPU Utilization" 计数器
        if any(k in path for k in ["activity", "utilization", "usage", "busy"]):
            activity_vals.append(float(val))
    if not activity_vals:
        return None
    try:
        return {"total": float(min(100.0, max(activity_vals)))}
    except Exception:
        return None


def _try_windows_gpu_adapter_total(timeout_s: float) -> float | None:
    if os.name != "nt":
        return None
    values: list[float] = []
    if shutil.which("typeperf") is not None:
        out = _run_cmd(["typeperf", r"\GPU Adapter(*)\Utilization Percentage", "-sc", "2"], timeout_s=max(1.0, float(timeout_s)))
        if out:
            lines = [line.strip() for line in out.splitlines() if line.strip()]
            for line in reversed(lines):
                try:
                    reader = csv.reader(io.StringIO(line))
                    row = next(reader, [])
                except Exception:
                    row = []
                tmp: list[float] = []
                if isinstance(row, list) and len(row) >= 2:
                    for item in row[1:]:
                        v = _parse_float_loose(item)
                        if v is not None:
                            tmp.append(v)
                if tmp:
                    values = tmp
                    break
    if not values and shutil.which("powershell") is not None:
        ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = @()
try {
  $sets = Get-Counter -ListSet '*GPU*'
  foreach ($s in $sets) { $paths += $s.PathsWithInstances }
} catch {}
$paths = $paths | Where-Object { $_ }
$paths = $paths | Where-Object { $_ -match 'GPU' }
$paths = $paths | Where-Object { $_ -match 'Adapter' -or $_ -match '适配器' }
$paths = $paths | Where-Object { $_ -match 'Util' -or $_ -match '利用率' -or $_ -match '使用率' -or $_ -match 'Percentage' -or $_ -match '百分比' }
$paths = $paths | Select-Object -Unique
$paths = $paths | Select-Object -First 80
if (-not $paths -or $paths.Count -le 0) { exit 0 }
(Get-Counter -Counter $paths -SampleInterval 0.2 -MaxSamples 3).CounterSamples | Select -ExpandProperty CookedValue
"""
        out = _run_cmd(["powershell", "-NoProfile", "-Command", ps], timeout_s=max(1.4, float(timeout_s)))
        if out:
            for line in out.splitlines():
                v = _parse_float_loose(line)
                if v is not None:
                    values.append(v)
    if not values:
        return None
    try:
        return float(min(100.0, max(values)))
    except Exception:
        return None


def get_gpu_detail_metrics(timeout_s: float = 1.2) -> dict:
    detail: dict = {}
    engine_source = ""
    try:
        adapters = _try_windows_video_controller_info(timeout_s=max(0.8, float(timeout_s))) or []
    except Exception:
        adapters = []
    if adapters:
        try:
            detail.update(adapters[0])
        except Exception:
            pass
    try:
        mem_detail = _try_windows_gpu_memory_detail(timeout_s=max(1.0, float(timeout_s))) or {}
    except Exception:
        mem_detail = {}
    try:
        nvidia = _try_nvidia_smi_detail(timeout_s=timeout_s) or {}
    except Exception:
        nvidia = {}
    try:
        engines = _try_windows_gpu_engine_groups_typeperf(timeout_s=max(1.0, float(timeout_s))) or {}
        if engines:
            engine_source = "typeperf"
    except Exception:
        engines = {}
    if not engines:
        try:
            engines = _try_windows_gpu_engine_groups_powershell(timeout_s=max(1.2, float(timeout_s * 1.2))) or {}
            if engines:
                engine_source = "get-counter"
        except Exception:
            engines = {}
    if not engines:
        try:
            engines = _try_windows_gpu_engine_groups(timeout_s=max(1.0, float(timeout_s))) or {}
            if engines:
                engine_source = "cim"
        except Exception:
            engines = {}
    # 对于 AMD 显卡，尝试使用特定的检测方法
    if not engines and detail.get("vendor") == "amd":
        try:
            amd_activity = _try_amd_gpu_activity(timeout_s=max(1.5, float(timeout_s)))
            if amd_activity:
                engines = amd_activity
                engine_source = "amd-activity"
        except Exception:
            pass
    # 如果仍然没有获取到引擎数据，尝试通用的 GPU 活动检测
    if not engines:
        try:
            generic_activity = _try_generic_gpu_activity(timeout_s=max(1.5, float(timeout_s)))
            if generic_activity:
                engines = generic_activity
                engine_source = "generic-gpu-activity"
        except Exception:
            pass
    if nvidia:
        detail.update(nvidia)
    elif mem_detail:
        detail.update(mem_detail)
    for key, value in engines.items():
        if value is None:
            continue
        detail[key] = _clamp_percent(value)
    # 调试日志
    try:
        from utils.log_manager import LogManager
        LogManager.instance().debug(f"[GPUDetail] source={engine_source} engines={engines} detail={detail}")
    except Exception:
        pass
    if mem_detail:
        for key, value in mem_detail.items():
            if detail.get(key) is None:
                detail[key] = value
    if detail.get("total") is None:
        try:
            detail["total"] = _clamp_percent(get_gpu_util_percent(timeout_s=timeout_s))
        except Exception:
            detail["total"] = None
    if detail.get("total") is None:
        try:
            detail["total"] = _clamp_percent(_try_windows_gpu_adapter_total(timeout_s=max(1.0, float(timeout_s))))
        except Exception:
            detail["total"] = None
    if detail.get("total") is None and os.name == "nt":
        try:
            if detail.get("name") or (_try_windows_video_controller_info(timeout_s=max(0.6, float(timeout_s))) or []):
                detail["total"] = 0.0
                engine_source = str(engine_source or "fallback")
        except Exception:
            pass
    detail["engine_source"] = str(engine_source or "")
    detail["detail_available"] = any(detail.get(k) is not None for k in ("compute", "3d"))
    try:
        detail["vendor"] = str(detail.get("vendor") or _guess_gpu_vendor(str(detail.get("name") or "")) or "")
    except Exception:
        detail["vendor"] = ""
    return detail
