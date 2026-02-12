from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional
import builtins
import os
import platform
import queue
import sys
import threading
import time
import traceback


class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


def _now_local_str() -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    except Exception:
        return ""


def _sanitize_message(msg: Any) -> str:
    try:
        s = str(msg)
    except Exception:
        s = repr(msg)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s


def _get_project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    except Exception:
        return os.getcwd()


def _get_logs_dir() -> str:
    return os.path.join(_get_project_root(), "cache", "logs")


def _level_from_setting(v: Any) -> int:
    s = str(v or "").strip().lower()
    if s in ("debug", "d"):
        return int(LogLevel.DEBUG)
    if s in ("info", "i"):
        return int(LogLevel.INFO)
    if s in ("warn", "warning", "w"):
        return int(LogLevel.WARNING)
    if s in ("err", "error", "e"):
        return int(LogLevel.ERROR)
    return int(LogLevel.WARNING)


def _level_to_name(level: int) -> str:
    if int(level) >= int(LogLevel.ERROR):
        return "ERROR"
    if int(level) >= int(LogLevel.WARNING):
        return "WARNING"
    if int(level) >= int(LogLevel.INFO):
        return "INFO"
    return "DEBUG"


@dataclass(frozen=True)
class _LogEvent:
    ts: float
    level: int
    message: str
    thread_name: str


class LogManager:
    _instance: Optional["LogManager"] = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "LogManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._queue: "queue.Queue[_LogEvent]" = queue.Queue(maxsize=20000)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None
        self._level = int(LogLevel.WARNING)
        self._print_to_console = False
        self._max_bytes = 2 * 1024 * 1024 * 1024
        self._cleanup_target_bytes = 1 * 1024 * 1024 * 1024
        self._log_file_path: Optional[str] = None
        self._file_handle = None
        self._orig_print = getattr(builtins, "print", None)
        self._print_hook_installed = False

    def start(self):
        self.reload_settings()
        self._ensure_log_target()
        self._start_worker()
        self._start_cleanup_worker()
        # 异步记录启动信息，避免 GPU 检测阻塞主线程
        threading.Thread(target=self.log_startup_info, name="LogStartupInfo", daemon=True).start()
        # 禁用 print hook，防止无限递归死循环
        # self.install_print_hook()

    def stop(self):
        try:
            self._stop_event.set()
        except Exception:
            pass
        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self._file_handle:
                self._file_handle.flush()
                self._file_handle.close()
        except Exception:
            pass
        self._file_handle = None

    def install_print_hook(self):
        if self._print_hook_installed:
            return
        orig = getattr(builtins, "print", None)
        if not callable(orig):
            return
        self._orig_print = orig

        def _hook(*args, **kwargs):
            try:
                sep = kwargs.get("sep", " ")
                end = kwargs.get("end", "\n")
            except Exception:
                sep = " "
                end = "\n"
            try:
                msg = sep.join([_sanitize_message(a) for a in args]) + _sanitize_message(end)
            except Exception:
                try:
                    msg = " ".join([_sanitize_message(a) for a in args]) + "\n"
                except Exception:
                    msg = ""
            msg = msg.rstrip("\n")
            if msg:
                self.debug(msg)

        try:
            builtins.print = _hook
            self._print_hook_installed = True
        except Exception:
            self._print_hook_installed = False

    def reload_settings(self):
        try:
            from utils.setting.settings_manager import SettingsManager

            sm = SettingsManager()
            self._level = _level_from_setting(sm.get("log/level", "warning"))
            self._print_to_console = bool(sm.get("log/print_to_console", False))
            try:
                self._max_bytes = int(sm.get("log/max_bytes", 2 * 1024 * 1024 * 1024) or 0)
            except Exception:
                self._max_bytes = 2 * 1024 * 1024 * 1024
            if self._max_bytes <= 0:
                self._max_bytes = 2 * 1024 * 1024 * 1024
            try:
                self._cleanup_target_bytes = int(sm.get("log/cleanup_target_bytes", int(self._max_bytes / 2)) or 0)
            except Exception:
                self._cleanup_target_bytes = int(self._max_bytes / 2)
            if self._cleanup_target_bytes <= 0 or self._cleanup_target_bytes >= self._max_bytes:
                self._cleanup_target_bytes = int(self._max_bytes / 2)
        except Exception:
            self._level = int(LogLevel.WARNING)
            self._print_to_console = False
            self._max_bytes = 2 * 1024 * 1024 * 1024
            self._cleanup_target_bytes = 1 * 1024 * 1024 * 1024

        if bool(self._print_to_console):
            self._close_file()
        else:
            self._ensure_log_target()

    def _ensure_log_target(self):
        if self._log_file_path and self._file_handle:
            return
        logs_dir = _get_logs_dir()
        try:
            os.makedirs(logs_dir, exist_ok=True)
        except Exception:
            pass
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        self._log_file_path = os.path.join(logs_dir, f"{ts}.txt")
        try:
            if not os.path.exists(self._log_file_path):
                with open(self._log_file_path, "a", encoding="utf-8"):
                    pass
        except Exception:
            pass
        if bool(self._print_to_console):
            return
        try:
            self._file_handle = open(self._log_file_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._file_handle = None

    def _close_file(self):
        try:
            if self._file_handle:
                self._file_handle.flush()
                self._file_handle.close()
        except Exception:
            pass
        self._file_handle = None
        self._log_file_path = None

    def delete_all_logs(self):
        """删除所有日志文件"""
        logs_dir = _get_logs_dir()
        if not os.path.exists(logs_dir):
            return

        # 先关闭当前文件
        self._close_file()

        try:
            for name in os.listdir(logs_dir):
                p = os.path.join(logs_dir, name)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass
            
        # 重新打开（如果需要）
        self._ensure_log_target()

    def _start_worker(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="LogWriter", daemon=True)
        self._thread.start()

    def _start_cleanup_worker(self):
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return
        self._cleanup_thread = threading.Thread(target=self._run_cleanup, name="LogCleaner", daemon=True)
        self._cleanup_thread.start()

    def _emit(self, level: int, msg: Any):
        if int(level) < int(self._level):
            return
        ev = _LogEvent(
            ts=float(time.time()),
            level=int(level),
            message=_sanitize_message(msg),
            thread_name=threading.current_thread().name,
        )
        try:
            self._queue.put_nowait(ev)
        except Exception:
            return

    def debug(self, msg: Any):
        self._emit(int(LogLevel.DEBUG), msg)

    def info(self, msg: Any):
        self._emit(int(LogLevel.INFO), msg)

    def warning(self, msg: Any):
        self._emit(int(LogLevel.WARNING), msg)

    def error(self, msg: Any):
        self._emit(int(LogLevel.ERROR), msg)

    def exception(self, msg: Any, exc: BaseException | None = None):
        try:
            if exc is None:
                exc = sys.exc_info()[1]
        except Exception:
            exc = None
        tail = ""
        if exc is not None:
            try:
                tail = "\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            except Exception:
                tail = ""
        self._emit(int(LogLevel.ERROR), f"{_sanitize_message(msg)}{tail}")

    def log_startup_info(self):
        try:
            self.info(f"App start: pid={os.getpid()} frozen={bool(getattr(sys, 'frozen', False))}")
            self.info(f"Python: {platform.python_version()} ({sys.executable})")
            self.info(f"OS: {platform.platform()}")
            try:
                self.info(f"CPU: {os.cpu_count()} cores")
            except Exception:
                pass
            try:
                import psutil

                vm = psutil.virtual_memory()
                self.info(f"Memory: total={int(vm.total)} available={int(vm.available)}")
            except Exception:
                pass
            try:
                from utils.system.gpu_utils import get_gpu_summary

                g = get_gpu_summary()
                if g:
                    self.info(f"GPU: {g}")
            except Exception:
                pass
        except Exception:
            pass

    def _format_line(self, ev: _LogEvent) -> str:
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ev.ts))
        except Exception:
            ts = _now_local_str()
        level = _level_to_name(ev.level)
        return f"[{ts}][{level}][{ev.thread_name}] {ev.message}\n"

    def _write_line(self, line: str):
        if self._print_to_console:
            if callable(self._orig_print):
                try:
                    self._orig_print(line.rstrip("\n"))
                except Exception:
                    pass
            return
        if self._file_handle is None:
            self._ensure_log_target()
        try:
            if self._file_handle:
                self._file_handle.write(line)
        except Exception:
            pass

    def _run(self):
        while not self._stop_event.is_set():
            try:
                ev = self._queue.get(timeout=0.2)
            except Exception:
                continue
            try:
                self._write_line(self._format_line(ev))
            except Exception:
                pass
            try:
                self._queue.task_done()
            except Exception:
                pass

    def _run_cleanup(self):
        self._cleanup_once()
        while not self._stop_event.is_set():
            try:
                time.sleep(600)
            except Exception:
                continue
            self._cleanup_once()

    def _cleanup_once(self):
        logs_dir = _get_logs_dir()
        try:
            if not os.path.isdir(logs_dir):
                return
        except Exception:
            return

        now = time.time()
        max_age_s = 30 * 24 * 3600
        try:
            for name in os.listdir(logs_dir):
                p = os.path.join(logs_dir, name)
                try:
                    if not os.path.isfile(p):
                        continue
                    mtime = float(os.path.getmtime(p))
                except Exception:
                    continue
                if (now - mtime) > max_age_s:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            entries = []
            total = 0
            for name in os.listdir(logs_dir):
                p = os.path.join(logs_dir, name)
                try:
                    if not os.path.isfile(p):
                        continue
                    size = int(os.path.getsize(p))
                    mtime = float(os.path.getmtime(p))
                except Exception:
                    continue
                total += size
                entries.append((mtime, p, size))
        except Exception:
            return

        max_bytes = int(self._max_bytes or 0)
        target = int(self._cleanup_target_bytes or 0)
        if max_bytes <= 0 or target <= 0:
            return
        if total <= max_bytes:
            return

        current = str(self._log_file_path or "")
        try:
            entries.sort(key=lambda x: x[0])
        except Exception:
            pass

        for _, p, size in entries:
            if total <= target:
                break
            if current and os.path.abspath(p) == os.path.abspath(current):
                continue
            try:
                os.remove(p)
                total -= int(size)
            except Exception:
                continue
