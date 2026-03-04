import os
import sys
import subprocess
import threading


_lock = threading.Lock()
_patched = False
_debug_enabled = False
_debug_limit = 0
_debug_stack_limit = 0
_debug_count = 0


def set_subprocess_debug(enabled: bool, *, limit: int = 25, stack_limit: int = 10):
    global _debug_enabled, _debug_limit, _debug_stack_limit, _debug_count
    with _lock:
        _debug_enabled = bool(enabled)
        try:
            _debug_limit = int(limit)
        except Exception:
            _debug_limit = 25
        try:
            _debug_stack_limit = int(stack_limit)
        except Exception:
            _debug_stack_limit = 10
        if not _debug_enabled:
            _debug_count = 0


def _should_hide_console() -> bool:
    if sys.platform != "win32":
        return False
    try:
        v = os.environ.get("BPM_HIDE_SUBPROCESS_CONSOLE")
        if v is not None and str(v).strip() != "":
            return str(v).strip().lower() not in {"0", "false", "no", "off"}
    except Exception:
        pass
    try:
        from utils.setting.settings_manager import SettingsManager

        return bool(SettingsManager.instance().get("system/hide_subprocess_console", True))
    except Exception:
        return True


def patch_subprocess_no_console():
    global _patched
    with _lock:
        if _patched:
            return
        if not _should_hide_console():
            return
        orig_popen = subprocess.Popen
        if not isinstance(orig_popen, type):
            return

        class NoConsolePopen(orig_popen):
            def __init__(self, *args, **kwargs):
                try:
                    if sys.platform == "win32":
                        try:
                            cf = int(kwargs.get("creationflags", 0) or 0)
                        except Exception:
                            cf = 0
                        try:
                            cf |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                        except Exception:
                            cf |= 0x08000000
                        try:
                            cf |= int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
                        except Exception:
                            cf |= 0x00000008
                        kwargs["creationflags"] = int(cf)
                        if "startupinfo" not in kwargs:
                            try:
                                si = subprocess.STARTUPINFO()
                                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                                si.wShowWindow = subprocess.SW_HIDE
                                kwargs["startupinfo"] = si
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    if bool(_debug_enabled) and int(_debug_limit) > 0 and int(_debug_count) < int(_debug_limit):
                        try:
                            import traceback
                        except Exception:
                            traceback = None
                        try:
                            from utils.log_manager import LogManager
                        except Exception:
                            LogManager = None

                        try:
                            cmd = args[0] if args else kwargs.get("args")
                        except Exception:
                            cmd = None
                        try:
                            shell = kwargs.get("shell", False)
                        except Exception:
                            shell = False
                        try:
                            cf = kwargs.get("creationflags", None)
                        except Exception:
                            cf = None
                        try:
                            si = kwargs.get("startupinfo", None)
                        except Exception:
                            si = None
                        try:
                            stack_txt = ""
                            if traceback is not None:
                                sl = int(_debug_stack_limit) if int(_debug_stack_limit) > 0 else 0
                                if sl > 0:
                                    stack_txt = "".join(traceback.format_stack(limit=sl))
                        except Exception:
                            stack_txt = ""

                        try:
                            globals()["_debug_count"] = int(globals().get("_debug_count", 0)) + 1
                            n = int(globals().get("_debug_count", 0))
                        except Exception:
                            n = 0
                        try:
                            if LogManager is not None:
                                LogManager.instance().warning(
                                    f"[Subprocess] popen#{n} shell={bool(shell)} creationflags={cf} startupinfo={'Y' if si is not None else 'N'} cmd={str(cmd)[:500]} stack={stack_txt[-4000:]}"
                                )
                        except Exception:
                            pass
                except Exception:
                    pass
                super().__init__(*args, **kwargs)

        subprocess.Popen = NoConsolePopen
        _patched = True
