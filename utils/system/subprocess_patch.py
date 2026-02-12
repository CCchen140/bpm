import os
import sys
import subprocess
import threading


_lock = threading.Lock()
_patched = False


def _should_hide_console() -> bool:
    if sys.platform != "win32":
        return False
    is_frozen = bool(getattr(sys, "frozen", False))
    try:
        v = os.environ.get("BPM_HIDE_SUBPROCESS_CONSOLE")
        if v is not None and str(v).strip() != "":
            return str(v).strip().lower() not in {"0", "false", "no", "off"}
    except Exception:
        pass
    if not is_frozen:
        return False
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
        _patched = True

    if not _should_hide_console():
        return

    orig_popen = subprocess.Popen
    if not isinstance(orig_popen, type):
        return

    class NoConsolePopen(orig_popen):
        def __init__(self, *args, **kwargs):
            try:
                if sys.platform == "win32":
                    if "creationflags" not in kwargs:
                        try:
                            kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                        except Exception:
                            kwargs["creationflags"] = 0x08000000
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
            super().__init__(*args, **kwargs)

    subprocess.Popen = NoConsolePopen
