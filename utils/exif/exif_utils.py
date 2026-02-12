import configparser
import subprocess
import threading
import queue
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
import os
import sys
import time
from enum import Enum
import json
import re
import hashlib
from utils.log_manager import LogManager

READ_PICTURE_TIME_TAG = 1 # 拍摄时间
READ_PICTURE_METADATA_TAG = 2 # 所有元数据
READ_PICTURE_XMP_DESCRIPTION_TAG = 3 # 描述
READ_PICTURE_DESCRIPTION_TAG = 4 # 包含: Data_Object-Bird_Status-xx_Score-xxx_Position-xx
READ_PICTURE_OBJECT_TAG = 5 # 物种
READ_PICTURE_STATUS_TAG = 6 # 最终状态
READ_PICTURE_SCORE_TAG = 7 # 最终得分
READ_PICTURE_POSITION_TAG = 8 # 最终位置
READ_PICTURE_AREA_RATIO_TAG = 9 # 区域比例
READ_PICTURE_POSITION_TAG = 10 # 九宫格位置
READ_PICTURE_OBJECT_COORDINATES_TAG = 11 # 主体的坐标
READ_PICTURE_EYE_COORDINATES_TAG = 12 # 眼睛的坐标

READ_MAX = 999

WRITE_MAX = 999
WRITE_BATCH_SIZE = 32

class LR_COLORS(Enum): 
    Red = "红色"       # 红色
    Yellow = "黄色" # 黄色
    Green = "绿色"   # 绿色
    Blue = "蓝色"     # 蓝色
    Purple = "紫色" # 紫色
    White = "白色"    # 自定义
    Orange = "橙色"
    Pink = "粉色"
    Black = "黑色"

class EXIF_TAG(Enum):
    Label = "XMP:Label"
    Rating = "XMP:Rating"
    Object = "XMP-bmp:Object"
    OrderCls = "XMP-bmp:OrderCls"
    FamilyCls = "XMP-bmp:FamilyCls"
    GenusCls = "XMP-bmp:GenusCls"
    SpeciesCls = "XMP-bmp:SpeciesCls"
    FocusPoint = "XMP-bmp:FocusPoint"
    Score = "XMP-bmp:Score"
    AreaRatio = "XMP-bmp:AreaRatio"
    Status = "XMP-bmp:Status"
    Position = "XMP-bmp:Position"
    ObjectCoordinates = "XMP-bmp:ObjectCoordinates"
    EyeCoordinates = "XMP-bmp:EyeCoordinates"
    Description = "XMP:Description"
    BmpDescription = "XMP-bmp:Description"
    Uuid = "XMP-bmp:Uuid"
    Fastid = "XMP-bmp:Fastid"
    Favorite = "XMP-bmp:Favorite"
    Tags = "XMP-bmp:Tags"
    Location = "Xmp-bmp:Location"
    FNumber = "ApertureValue"
    ShutterSpeed = "ShutterSpeedValue"
    ExposureTime = "ExposureTime"
    ISO = "ISO"
    FocalLength = "FocalLength"
    CameraModel = "Model"
    LensModel = "LensModel"
    FocusDistance = "FocusDistance"
    GPSLatitudeRef = "GPS:GPSLatitudeRef"
    GPSLongitudeRef = "GPS:GPSLongitudeRef"
    GPSLatitude = "GPS:GPSLatitude"
    GPSLongitude = "GPS:GPSLongitude"
    GPSDateStamp = "GPS:GPSDateStamp"

def _escape_perl_single_quoted(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def _get_exif_write_mode() -> str:
    try:
        from utils.setting.settings_manager import SettingsManager

        sm = SettingsManager.instance()
    except Exception:
        sm = None
    mode = "file"
    try:
        if sm is not None:
            mode = str(sm.get("exif/write_mode", "file") or "file").strip().lower()
    except Exception:
        mode = "file"
    if mode not in ("file", "xmp", "none"):
        mode = "file"
    try:
        if sm is not None and bool(sm.get("exif/disable_write", False)):
            mode = "none"
    except Exception:
        pass
    return mode


def _is_exif_write_disabled() -> bool:
    return _get_exif_write_mode() == "none"


def _to_sidecar_xmp_path(file_path: str) -> str:
    p = str(file_path or "").strip()
    if not p:
        return ""
    try:
        if p.lower().endswith(".xmp"):
            return p
    except Exception:
        pass
    try:
        base, _ext = os.path.splitext(p)
    except Exception:
        base = p
    return f"{base}.xmp"


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
        return {"creationflags": creationflags}
    except Exception:
        return {}


def _extract_xmp_bmp_tag_name(tag: str) -> str | None:
    if not tag or ":" not in tag:
        return None
    prefix, name = tag.split(":", 1)
    if prefix.strip().lower() != "xmp-bmp":
        return None
    name = (name or "").strip()
    return name or None


def _expand_xmp_bmp_tag_name_variants(tag_name: str) -> set[str]:
    name = (tag_name or "").strip()
    if not name:
        return set()
    lower = name.lower()
    out = {name}
    if lower == "uuid":
        out.update({"UUID", "Uuid"})
    elif lower == "fastid":
        out.update({"Fastid", "FastId", "FASTID"})
    return {t for t in out if t and str(t).strip()}


def _get_xmp_bmp_short_name_map() -> dict:
    mp = {}
    try:
        for tag in EXIF_TAG:
            try:
                full = str(tag.value or "")
            except Exception:
                continue
            name = _extract_xmp_bmp_tag_name(full)
            if not name:
                continue
            mp[str(name).strip().lower()] = full
    except Exception:
        mp = {}
    return mp


def _normalize_xmp_bmp_tag_for_write(tag: str) -> str:
    s = str(tag or "").strip()
    if not s:
        return s
    mp = _get_xmp_bmp_short_name_map()
    if ":" not in s:
        key = s.lower()
        return str(mp.get(key) or f"XMP-bmp:{s}")
    try:
        prefix, name = s.split(":", 1)
        if prefix.strip().lower() == "xmp-bmp":
            key = str(name or "").strip().lower()
            if key in mp:
                return str(mp[key])
    except Exception:
        pass
    return s


def _build_xmp_bmp_config_content(tag_names: set[str]) -> str:
    tag_names = {t.strip() for t in (tag_names or set()) if t and t.strip()}
    tags_lines = "\n".join([f"    '{_escape_perl_single_quoted(t)}' => {{ }}," for t in sorted(tag_names)])
    if tags_lines:
        tags_lines = "\n" + tags_lines + "\n"
    return (
        "%Image::ExifTool::UserDefined = (\n"
        "    'Image::ExifTool::XMP::Main' => {\n"
        "        bmp => {\n"
        "            SubDirectory => {\n"
        "                TagTable => 'Image::ExifTool::UserDefined::bmp',\n"
        "            },\n"
        "        },\n"
        "    },\n"
        ");\n"
        "\n"
        "%Image::ExifTool::UserDefined::bmp = (\n"
        "    GROUPS => { 0 => 'XMP', 1 => 'XMP-bmp', 2 => 'Image' },\n"
        "    NAMESPACE => { 'bmp' => 'http://ns.bird.picture/bmp/1.0/' },\n"
        "    WRITABLE => 'string',"
        f"{tags_lines}"
        ");\n"
        "1;\n"
    )


def _create_temp_xmp_bmp_config_file(tag_names: set[str]) -> str | None:
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".config", delete=False, encoding="utf-8") as cf:
            cf.write(_build_xmp_bmp_config_content(tag_names))
            return cf.name
    except Exception:
        return None


def create_temp_config_file() -> str | None:
    tag_names: set[str] = set()
    try:
        for tag in EXIF_TAG:
            name = _extract_xmp_bmp_tag_name(tag.value)
            if name:
                tag_names.update(_expand_xmp_bmp_tag_name_variants(name))
    except Exception:
        tag_names = set()
    return _create_temp_xmp_bmp_config_file(tag_names)

def get_exiftool_path():
    """
    判断程序是直接运行脚本，还是打包后的 exe 运行，
    从而返回正确的 exiftool 路径。
    """
    filename = "exiftool.exe" if sys.platform == "win32" else "exiftool"
    if getattr(sys, 'frozen', False):
        try:
            exe_dir = os.path.dirname(sys.executable)
        except Exception:
            exe_dir = ""
        try:
            p1 = os.path.join(exe_dir, "lib", filename) if exe_dir else ""
            if p1 and os.path.exists(p1):
                return p1
        except Exception:
            pass
        try:
            p1b = os.path.join(exe_dir, "libs", filename) if exe_dir else ""
            if p1b and os.path.exists(p1b):
                return p1b
        except Exception:
            pass
        try:
            base_path = sys._MEIPASS
            p2 = os.path.join(base_path, filename)
            if os.path.exists(p2):
                return p2
        except Exception:
            pass
        return os.path.join(exe_dir, filename) if exe_dir else filename
    else:
        try:
            base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
            abs_path = os.path.join(base_path, filename)
            if os.path.exists(abs_path):
                return abs_path
        except Exception:
            pass
        return "./exiftool.exe" if sys.platform == "win32" else "./exiftool"

def run_exiftool(cmd, *, timeout: float | None = None):
    """
    封装 subprocess.run 调用 exiftool
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            **_subprocess_no_console_kwargs(),
        )
    except subprocess.TimeoutExpired:
        try:
            return subprocess.CompletedProcess(cmd, 124, stdout="", stderr="timeout")
        except Exception:
            return subprocess.CompletedProcess([], 124, stdout="", stderr="timeout")

class ExifHandleWorker:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.running = True
        self.write_queue = queue.Queue() # 专门用于写入任务的队列
        self.read_queue = queue.Queue()  # 专门用于读取任务的队列
        self.read_results = {}  # 存储读取结果，键为任务ID (现在存储 Future 对象)
        self.task_counter = 0  # 任务计数器

        self._persistent_xmp_bmp_config_lock = threading.Lock()
        self._persistent_xmp_bmp_config_file = None

        self._recent_write_lock = threading.Lock()
        self._recent_write_requests = {}

        self._write_buffer_lock = threading.Lock()
        self._write_buffer = {}
        self._write_buffer_ts = {}
        self._write_debounce_seconds = 0.25

        self._active_processes_lock = threading.Lock()
        self._active_processes = set()

        self._stayopen_lock = threading.Lock()
        self._stayopen_process = None
        self._stayopen_stdout_queue = queue.Queue()
        self._stayopen_reader_thread = None

        self._file_write_locks = {}
        self._file_write_locks_lock = threading.Lock()
        
        self._active_batch_tasks = 0 # 活跃的批量任务计数
        self._batch_lock = threading.Lock() # 保护批量任务计数的锁
        
        self._total_write_tasks = 0 # 总写入任务数
        self._completed_write_tasks = 0 # 已完成写入任务数
        self._task_count_lock = threading.Lock() # 保护任务计数的锁
        self._write_executor = ThreadPoolExecutor(max_workers=min(4, max(1, (os.cpu_count() or 4) // 2)))
        self._write_futures = []
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()

    def _get_persistent_xmp_bmp_config_file(self) -> str | None:
        """
        获取一个“持久化”的 XMP-bmp 配置文件路径。
        - ExifTool 的 -config 参数只能接收文件路径，无法直接用内存字符串替代
        - 为了避免读取 tag 时反复创建/删除临时 config，这里在用户目录中生成一次并复用
        """
        with self._persistent_xmp_bmp_config_lock:
            try:
                if self._persistent_xmp_bmp_config_file and os.path.exists(self._persistent_xmp_bmp_config_file):
                    return self._persistent_xmp_bmp_config_file
            except Exception:
                pass

            base_dir = (
                os.getenv("LOCALAPPDATA")
                or os.getenv("APPDATA")
                or os.path.expanduser("~")
                or os.getcwd()
            )
            cfg_dir = os.path.join(str(base_dir), "BirdPictureManager", "exiftool")
            try:
                os.makedirs(cfg_dir, exist_ok=True)
            except Exception:
                cfg_dir = str(base_dir)

            cfg_path = os.path.join(cfg_dir, "xmp_bmp.config")
            try:
                tag_names: set[str] = set()
                for tag in EXIF_TAG:
                    name = _extract_xmp_bmp_tag_name(tag.value)
                    if name:
                        tag_names.update(_expand_xmp_bmp_tag_name_variants(name))
                content = _build_xmp_bmp_config_content(tag_names)

                need_write = True
                try:
                    if os.path.exists(cfg_path):
                        with open(cfg_path, "r", encoding="utf-8") as rf:
                            old = rf.read()
                        if old == content:
                            need_write = False
                except Exception:
                    need_write = True

                if need_write:
                    with open(cfg_path, "w", encoding="utf-8") as wf:
                        wf.write(content)
            except Exception:
                try:
                    import tempfile

                    fallback_path = os.path.join(str(tempfile.gettempdir()), "BirdPictureManager_xmp_bmp.config")
                    tag_names: set[str] = set()
                    for tag in EXIF_TAG:
                        name = _extract_xmp_bmp_tag_name(tag.value)
                        if name:
                            tag_names.update(_expand_xmp_bmp_tag_name_variants(name))
                    content = _build_xmp_bmp_config_content(tag_names)
                    with open(fallback_path, "w", encoding="utf-8") as wf:
                        wf.write(content)
                    cfg_path = fallback_path
                except Exception:
                    return None

            self._persistent_xmp_bmp_config_file = cfg_path
            return self._persistent_xmp_bmp_config_file

    def _should_skip_duplicate_write(self, file_path: str, tags: dict, window_seconds: float = 0.6) -> bool:
        """
        判断某次写入请求是否属于“短时间内重复请求”。
        - 解决某些信号/快捷键/界面链路导致同一写入被触发多次，进而出现“每次操作多出多个写入任务”
        - 规则：同一文件、相同 tags 内容，在 window_seconds 内重复出现则跳过
        """
        if not file_path or not tags:
            return False
        try:
            norm = os.path.normcase(os.path.normpath(str(file_path)))
        except Exception:
            norm = str(file_path)
        try:
            payload = json.dumps(tags, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            payload = str(tags)
        digest = hashlib.md5(payload.encode("utf-8", errors="ignore")).hexdigest()

        now = time.time()
        with self._recent_write_lock:
            try:
                expire_before = now - max(3.0, float(window_seconds) * 5.0)
                for k in list(self._recent_write_requests.keys()):
                    try:
                        if float(self._recent_write_requests[k][1]) < expire_before:
                            self._recent_write_requests.pop(k, None)
                    except Exception:
                        self._recent_write_requests.pop(k, None)
            except Exception:
                pass

            prev = self._recent_write_requests.get(norm)
            if prev and prev[0] == digest:
                try:
                    if (now - float(prev[1])) <= float(window_seconds):
                        return True
                except Exception:
                    return True
            self._recent_write_requests[norm] = (digest, now)
        return False

    def _buffer_write(self, file_path: str, tags: dict):
        if not file_path or not tags:
            return
        try:
            key = os.path.normcase(os.path.normpath(str(file_path)))
        except Exception:
            key = str(file_path)
        now = time.time()
        with self._write_buffer_lock:
            cur = self._write_buffer.get(key)
            if not isinstance(cur, dict):
                cur = {}
                self._write_buffer[key] = cur
            try:
                cur.update(tags)
            except Exception:
                self._write_buffer[key] = dict(tags)
            self._write_buffer_ts[key] = now

    def _flush_write_buffer_ready(self, now_ts: float | None = None):
        now = time.time() if now_ts is None else float(now_ts)
        ready = []
        try:
            debounce = float(getattr(self, "_write_debounce_seconds", 0.25) or 0.25)
        except Exception:
            debounce = 0.25
        if debounce < 0:
            debounce = 0.0
        with self._write_buffer_lock:
            for k in list(self._write_buffer_ts.keys()):
                try:
                    ts = float(self._write_buffer_ts.get(k) or 0.0)
                except Exception:
                    ts = 0.0
                if debounce > 0 and (now - ts) < debounce:
                    continue
                tags = self._write_buffer.pop(k, None)
                self._write_buffer_ts.pop(k, None)
                if isinstance(tags, dict) and tags:
                    ready.append((k, tags))
        if ready:
            with self._task_count_lock:
                self._total_write_tasks += len(ready)
            for item in ready:
                self.write_queue.put(item)

    def _register_active_process(self, proc):
        if proc is None:
            return
        with self._active_processes_lock:
            self._active_processes.add(proc)

    def _unregister_active_process(self, proc):
        if proc is None:
            return
        with self._active_processes_lock:
            try:
                self._active_processes.discard(proc)
            except Exception:
                pass

    def _terminate_active_processes(self, timeout: float = 2.0):
        with self._active_processes_lock:
            procs = list(self._active_processes)
        for p in procs:
            try:
                if p is None or p.poll() is not None:
                    continue
            except Exception:
                continue
            try:
                p.terminate()
            except Exception:
                pass
        deadline = time.time() + max(0.0, float(timeout or 0.0))
        for p in procs:
            try:
                if p is None or p.poll() is not None:
                    continue
            except Exception:
                continue
            remain = max(0.0, deadline - time.time())
            try:
                p.wait(timeout=remain)
            except Exception:
                pass
        for p in procs:
            try:
                if p is None or p.poll() is not None:
                    continue
            except Exception:
                continue
            try:
                p.kill()
            except Exception:
                pass

    def _acquire_file_locks(self, file_paths):
        paths = []
        try:
            for p in (file_paths or []):
                if p:
                    paths.append(os.path.normpath(str(p)))
        except Exception:
            paths = []
        paths = sorted(set(paths))
        acquired = []
        for p in paths:
            with self._file_write_locks_lock:
                lock = self._file_write_locks.get(p)
                if lock is None:
                    lock = threading.Lock()
                    self._file_write_locks[p] = lock
            lock.acquire()
            acquired.append(lock)
        return acquired

    def _release_file_locks(self, locks):
        for lock in reversed(list(locks or [])):
            try:
                lock.release()
            except Exception:
                pass

    def _cleanup_exiftool_tmp(self, file_paths):
        for p in (file_paths or []):
            if not p:
                continue
            tmp_path = f"{p}_exiftool_tmp"
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def has_pending_tasks(self):
        """检查是否有正在进行的写入任务（包括队列中的和批量处理中的）"""
        with self._batch_lock:
             active_batches = self._active_batch_tasks
        pending_futures = False
        for future, _ in (self._write_futures or []):
            if not future.done():
                pending_futures = True
                break
        return not self.write_queue.empty() or active_batches > 0 or pending_futures

    def get_pending_task_counts(self):
        queued = 0
        try:
            queued = int(self.write_queue.qsize() or 0)
        except Exception:
            queued = 0
        buffered = 0
        try:
            with self._write_buffer_lock:
                buffered = int(len(self._write_buffer) or 0)
        except Exception:
            buffered = 0

        inflight = 0
        inflight_unique_files = 0
        try:
            mp = {}
            for future, batch in (self._write_futures or []):
                try:
                    if future is None or future.done():
                        continue
                except Exception:
                    continue
                try:
                    inflight += len(batch or [])
                except Exception:
                    inflight += 0
                try:
                    for fp, _ in (batch or []):
                        if fp:
                            mp[os.path.normcase(os.path.normpath(str(fp)))] = 1
                except Exception:
                    pass
            inflight_unique_files = len(mp)
        except Exception:
            inflight = 0
            inflight_unique_files = 0

        pending = max(0, queued + buffered + inflight)
        return {"pending": pending, "queued": queued, "buffered": buffered, "inflight": inflight, "inflight_unique_files": inflight_unique_files}

    def get_task_progress(self):
        """获取任务进度"""
        with self._task_count_lock:
            return self._completed_write_tasks, self._total_write_tasks

    def _get_task_id(self):
        """生成唯一的任务ID"""
        with self._lock:
            self.task_counter += 1
            return self.task_counter
        
    def _popen_exiftool(self, args, timeout=None, config_file=None):
        if timeout is None:
            timeout = 30
        tool_path = get_exiftool_path()
        cmd = [tool_path]
        if config_file:
            cmd += ["-config", config_file]
        cmd += ["-charset", "utf8"]
        cmd += args

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_subprocess_no_console_kwargs(),
        )
        self._register_active_process(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except Exception:
                stdout, stderr = "", ""
            raise
        finally:
            self._unregister_active_process(process)
        return process.returncode, stdout, stderr

    def _start_stayopen_process(self):
        proc = getattr(self, "_stayopen_process", None)
        if proc is not None:
            try:
                if proc.poll() is None:
                    return
            except Exception:
                pass

        tool_path = get_exiftool_path()
        cmd = [tool_path]
        try:
            cfg = self._get_persistent_xmp_bmp_config_file()
        except Exception:
            cfg = None
        if cfg:
            cmd.extend(["-config", str(cfg)])
        cmd.extend(
            [
                "-stay_open",
                "True",
                "-@",
                "-",
                "-q",
                "-q",
                "-m",
                "-charset",
                "utf8",
                "-charset",
                "filename=utf8",
            ]
        )
        self._stayopen_process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_subprocess_no_console_kwargs(),
        )
        self._register_active_process(self._stayopen_process)
        self._stayopen_stdout_queue = queue.Queue()

        def _reader():
            p = self._stayopen_process
            if p is None or p.stdout is None:
                return
            try:
                for line in iter(p.stdout.readline, ""):
                    if line == "" and p.poll() is not None:
                        break
                    self._stayopen_stdout_queue.put(line)
            except Exception:
                return

        def _reader_err():
            p = self._stayopen_process
            if p is None or p.stderr is None:
                return
            try:
                for line in iter(p.stderr.readline, ""):
                    if line == "" and p.poll() is not None:
                        break
            except Exception:
                return

        self._stayopen_reader_thread = threading.Thread(target=_reader, daemon=True)
        self._stayopen_reader_thread.start()
        threading.Thread(target=_reader_err, daemon=True).start()

    def _stop_stayopen_process(self):
        proc = getattr(self, "_stayopen_process", None)
        self._stayopen_process = None
        try:
            if proc is None:
                return
            if proc.stdin is not None:
                try:
                    proc.stdin.write("-stay_open\nFalse\n-execute\n")
                    proc.stdin.flush()
                except Exception:
                    pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.5)
            except Exception:
                pass
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=1.5)
            except Exception:
                pass
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                if proc.stderr is not None:
                    proc.stderr.close()
            except Exception:
                pass
            self._unregister_active_process(proc)

    def _stayopen_exec(self, args, timeout=10):
        with self._stayopen_lock:
            self._start_stayopen_process()
            proc = self._stayopen_process
            if proc is None or proc.stdin is None:
                raise RuntimeError("ExifTool stay_open 启动失败")

            while True:
                try:
                    self._stayopen_stdout_queue.get_nowait()
                except queue.Empty:
                    break

            for a in (args or []):
                if a is None:
                    continue
                proc.stdin.write(str(a) + "\n")
            proc.stdin.write("-execute\n")
            proc.stdin.flush()

            out_lines = []
            deadline = time.time() + max(1, int(timeout))
            while True:
                remain = deadline - time.time()
                if remain <= 0:
                    self._stop_stayopen_process()
                    raise TimeoutError("ExifTool stay_open 超时")
                line = self._stayopen_stdout_queue.get(timeout=remain)
                if str(line).strip() == "{ready}":
                    break
                out_lines.append(line)
            return "".join(out_lines)

    def _read_json(self, file_path, tags=None, timeout=3, config_file=None):
        mode = _get_exif_write_mode()
        target_path = str(file_path or "")
        if mode == "xmp":
            target_path = _to_sidecar_xmp_path(target_path)
            try:
                if not os.path.exists(target_path):
                    return {}
            except Exception:
                return {}
        args = ["-j"]
        if tags:
            args += [f"-{t}" for t in tags]
        args.append(target_path)

        code, stdout, stderr = self._popen_exiftool(args, timeout=timeout, config_file=config_file)
        if code != 0:
            raise RuntimeError((stderr or stdout or "").strip())
        data = json.loads(stdout or "[]")
        if isinstance(data, list) and data:
            return data[0]
        return {}

    def _read_tags_popen(self, file_path, tags, timeout=3):
        meta = self._read_json(file_path, tags=tags, timeout=timeout)
        return [meta]

    def _read_metadata_popen(self, file_path, timeout=3):
        meta = self._read_json(file_path, tags=None, timeout=timeout)
        return meta

    def _read_time_popen(self, file_path, timeout=3):
        mode = _get_exif_write_mode()
        target_path = str(file_path or "")
        if mode == "xmp":
            target_path = _to_sidecar_xmp_path(target_path)
            try:
                if not os.path.exists(target_path):
                    return None
            except Exception:
                return None
        try:
            raw = self._stayopen_exec(
                [
                    "-j",
                    "-Composite:SubSecCreateDate",
                    "-DateTimeOriginal",
                    "-SubSecTimeOriginal",
                    "-CreateDate",
                    "-SubSecTimeDigitized",
                    "-MediaCreateDate",
                    "-TrackCreateDate",
                    "-ModifyDate",
                    "-FileModifyDate",
                    "-FileCreateDate",
                    "-SourceFile",
                    str(target_path),
                ],
                timeout=int(timeout),
            )
            data = json.loads(raw or "[]")
            if isinstance(data, list) and data:
                return self._parse_time_meta(data[0], file_path=str(file_path))
            return None
        except Exception:
            meta = self._read_json(
                file_path,
                tags=[
                    "Composite:SubSecCreateDate",
                    "DateTimeOriginal",
                    "SubSecTimeOriginal",
                    "CreateDate",
                    "SubSecTimeDigitized",
                    "MediaCreateDate",
                    "TrackCreateDate",
                    "ModifyDate",
                    "FileModifyDate",
                    "FileCreateDate",
                    "SourceFile",
                ],
                timeout=timeout,
            )
            return self._parse_time_meta(meta, file_path=str(file_path))

    def _parse_time_meta(self, meta: dict, file_path: str = ""):
        if not isinstance(meta, dict):
            return None
        file_name = meta.get("SourceFile") or file_path
        time_str = (
            meta.get("Composite:SubSecCreateDate")
            or meta.get("Composite:SubSecCreateDate".replace(":", "_"))
            or meta.get("Composite:SubSecCreateDate".replace(":", ""))
            or meta.get("EXIF:DateTimeOriginal")
            or meta.get("DateTimeOriginal")
            or meta.get("EXIF:CreateDate")
            or meta.get("CreateDate")
            or meta.get("QuickTime:MediaCreateDate")
            or meta.get("MediaCreateDate")
            or meta.get("QuickTime:TrackCreateDate")
            or meta.get("TrackCreateDate")
            or meta.get("EXIF:ModifyDate")
            or meta.get("ModifyDate")
            or meta.get("File:FileModifyDate")
            or meta.get("FileModifyDate")
            or meta.get("File:FileCreateDate")
            or meta.get("FileCreateDate")
            or ""
        )
        tag_subsec = (
            meta.get("EXIF:SubSecTimeOriginal")
            or meta.get("SubSecTimeOriginal")
            or meta.get("EXIF:SubSecTimeDigitized")
            or meta.get("SubSecTimeDigitized")
        )
        if not time_str:
            return None
        s0 = str(time_str).strip()
        for fmt in ("%Y:%m:%d %H:%M:%S.%f%z", "%Y:%m:%d %H:%M:%S.%f", "%Y:%m:%d %H:%M:%S%z", "%Y:%m:%d %H:%M:%S"):
            try:
                dt_obj = datetime.strptime(s0, fmt)
                if "%f" not in fmt and tag_subsec:
                    subsec_str = str(tag_subsec).strip()
                    if subsec_str.isdigit():
                        microsec_str = subsec_str.ljust(6, "0")[:6]
                        microsec = int(microsec_str)
                        return dt_obj + timedelta(microseconds=microsec)
                return dt_obj
            except Exception:
                continue
        try:
            tz_match = re.search(r"([+-]\d{2}):(\d{2})$", s0)
            if tz_match:
                fixed = s0[: tz_match.start()] + tz_match.group(1) + tz_match.group(2)
                for fmt in ("%Y:%m:%d %H:%M:%S.%f%z", "%Y:%m:%d %H:%M:%S%z"):
                    try:
                        dt_obj = datetime.strptime(fixed, fmt)
                        if "%f" not in fmt and tag_subsec:
                            subsec_str = str(tag_subsec).strip()
                            if subsec_str.isdigit():
                                microsec_str = subsec_str.ljust(6, "0")[:6]
                                microsec = int(microsec_str)
                                return dt_obj + timedelta(microseconds=microsec)
                        return dt_obj
                    except Exception:
                        continue
        except Exception:
            pass
        try:
            s1 = s0
            if len(s1) >= 10 and s1[4] == ":" and s1[7] == ":":
                s1 = s1.replace(":", "-", 2)
            if " " in s1:
                s1 = s1.replace(" ", "T", 1)
            dt_obj = datetime.fromisoformat(s1)
            if dt_obj and getattr(dt_obj, "tzinfo", None) is None and tag_subsec and "." not in s0:
                subsec_str = str(tag_subsec).strip()
                if subsec_str.isdigit():
                    microsec_str = subsec_str.ljust(6, "0")[:6]
                    microsec = int(microsec_str)
                    return dt_obj + timedelta(microseconds=microsec)
            return dt_obj
        except Exception:
            return None

    def _read_time_popen_multi(self, file_paths, timeout=10):
        orig_paths = []
        try:
            for p in (file_paths or []):
                if p:
                    orig_paths.append(str(p))
        except Exception:
            orig_paths = []
        if not orig_paths:
            return {}
        mode = _get_exif_write_mode()
        path_map = {}
        paths = []
        if mode == "xmp":
            for p in orig_paths:
                tp = _to_sidecar_xmp_path(p)
                try:
                    if not os.path.exists(tp):
                        continue
                except Exception:
                    continue
                paths.append(tp)
                path_map[tp] = p
        else:
            paths = list(orig_paths)
            for p in orig_paths:
                path_map[p] = p
        if not paths:
            return {p: None for p in orig_paths}
        try:
            args = [
                "-j",
                "-Composite:SubSecCreateDate",
                "-DateTimeOriginal",
                "-SubSecTimeOriginal",
                "-CreateDate",
                "-SubSecTimeDigitized",
                "-MediaCreateDate",
                "-TrackCreateDate",
                "-ModifyDate",
                "-FileModifyDate",
                "-FileCreateDate",
                "-SourceFile",
            ]
            args.extend(paths)
            raw = self._stayopen_exec(args, timeout=int(timeout))
            data = json.loads(raw or "[]")
            out = {}
            if isinstance(data, list):
                for meta in data:
                    if not isinstance(meta, dict):
                        continue
                    src = str(meta.get("SourceFile") or "")
                    if not src:
                        continue
                    orig = str(path_map.get(src) or "")
                    if not orig:
                        continue
                    out[orig] = self._parse_time_meta(meta, file_path=orig)
            for p in orig_paths:
                out.setdefault(p, None)
            return out
        except Exception:
            args = [
                "-j",
                "-Composite:SubSecCreateDate",
                "-DateTimeOriginal",
                "-SubSecTimeOriginal",
                "-CreateDate",
                "-SubSecTimeDigitized",
                "-MediaCreateDate",
                "-TrackCreateDate",
                "-ModifyDate",
                "-FileModifyDate",
                "-FileCreateDate",
                "-SourceFile",
            ]
            args.extend(paths)
            code, stdout, stderr = self._popen_exiftool(args, timeout=timeout)
            if code != 0:
                raise RuntimeError((stderr or stdout or "").strip())
            data = json.loads(stdout or "[]")
            out = {}
            if isinstance(data, list):
                for meta in data:
                    if not isinstance(meta, dict):
                        continue
                    src = str(meta.get("SourceFile") or "")
                    if not src:
                        continue
                    orig = str(path_map.get(src) or "")
                    if not orig:
                        continue
                    out[orig] = self._parse_time_meta(meta, file_path=orig)
            for p in orig_paths:
                out.setdefault(p, None)
            return out

    def _write_tags_popen(self, file_path, tags, timeout=30):
        # 使用 -overwrite_original_in_place：尽量直接写回原文件，避免“临时文件替换原文件”的写入方式
        # 同时使用 -P 保留原始文件时间戳，减少对外部工具（同步/备份/去重）的干扰
        args = ["-overwrite_original_in_place", "-P", "-m"]
        bmp_tag_names = set()
        file_locks = self._acquire_file_locks([file_path])
        self._cleanup_exiftool_tmp([file_path])
        for tag, value in (tags or {}).items():
            if not tag:
                continue
            
            tag = _normalize_xmp_bmp_tag_for_write(tag)
                
            bmp_name = _extract_xmp_bmp_tag_name(tag)
            if bmp_name:
                bmp_tag_names.add(bmp_name)
            args.append(f"-{tag}={value}")
        args.append(file_path)
        config_file = self._get_persistent_xmp_bmp_config_file() if bmp_tag_names else None
        try:
            max_retries = 1
            for attempt in range(max_retries + 1):
                code, stdout, stderr = self._popen_exiftool(args, timeout=timeout, config_file=config_file)
                if code != 0:
                    msg = (stderr or stdout or "").strip()
                    
                    # 检查是否为临时文件已存在的错误，尝试自动清理并重试
                    if "temporary file already exists" in msg.lower() and attempt < max_retries:
                        try:
                            LogManager.instance().warning(f"检测到临时文件冲突，尝试清理并重试: {file_path}")
                        except Exception:
                            pass
                        # 尝试查找并删除临时文件
                        # 错误信息通常格式: Error: Temporary file already exists: {file_path}_exiftool_tmp
                        matches = re.findall(r"Temporary file already exists: (.*?)(\n|$)", msg, re.IGNORECASE)
                        for match in matches:
                            temp_path = match[0].strip()
                            if os.path.exists(temp_path):
                                try:
                                    os.remove(temp_path)
                                    try:
                                        LogManager.instance().debug(f"已清理残留临时文件: {temp_path}")
                                    except Exception:
                                        pass
                                except Exception as del_e:
                                    try:
                                        LogManager.instance().warning(f"清理临时文件失败: {del_e}")
                                    except Exception:
                                        pass
                        continue

                    if "error" in msg.lower():
                        raise RuntimeError(msg)
                    else:
                        try:
                            LogManager.instance().warning(f"Exif 写入警告: {msg}")
                        except Exception:
                            pass
                break
        finally:
            self._release_file_locks(file_locks)

    def _write_tags_batch(self, tasks, timeout=120):
        if not tasks:
            return
        import tempfile
        arg_file = None
        config_file = None
        file_paths = []
        try:
            file_paths = [p for p, _ in tasks if p]
        except Exception:
            file_paths = []
        file_locks = self._acquire_file_locks(file_paths)
        try:
            bmp_tag_names = set()
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8-sig") as f:
                for file_path, tags in tasks:
                    if not file_path or not tags:
                        continue
                    f.write(f"{file_path}\n")
                    for tag, value in tags.items():
                        if not tag:
                            continue
                        
                        tag = _normalize_xmp_bmp_tag_for_write(tag)
                            
                        bmp_name = _extract_xmp_bmp_tag_name(tag)
                        if bmp_name:
                            bmp_tag_names.add(bmp_name)
                        f.write(f"-{tag}={value}\n")
                    f.write("-execute\n")
                arg_file = f.name
            # 使用 -overwrite_original_in_place：尽量直接写回原文件，避免“临时文件替换原文件”的写入方式
            # 同时使用 -P 保留原始文件时间戳
            args = ["-@", arg_file, "-common_args", "-overwrite_original_in_place", "-P", "-m"]
            config_file = self._get_persistent_xmp_bmp_config_file() if bmp_tag_names else None
            
            max_retries = 1
            for attempt in range(max_retries + 1):
                self._cleanup_exiftool_tmp(file_paths)
                try:
                    code, stdout, stderr = self._popen_exiftool(args, timeout=timeout, config_file=config_file)
                except subprocess.TimeoutExpired:
                    self._cleanup_exiftool_tmp(file_paths)
                    for p, tag_map in tasks:
                        if not p or not tag_map:
                            continue
                        self._write_tags_popen(p, tag_map, timeout=max(60, int(timeout)))
                    return
                if code != 0:
                    msg = (stderr or stdout or "").strip()
                    
                    # 检查是否为临时文件已存在的错误，尝试自动清理并重试
                    if "temporary file already exists" in msg.lower() and attempt < max_retries:
                        try:
                            LogManager.instance().warning("检测到批量写入时的临时文件冲突，尝试清理并重试")
                        except Exception:
                            pass
                        matches = re.findall(r"Temporary file already exists: (.*?)(\n|$)", msg, re.IGNORECASE)
                        for match in matches:
                            temp_path = match[0].strip()
                            if os.path.exists(temp_path):
                                try:
                                    os.remove(temp_path)
                                    try:
                                        LogManager.instance().debug(f"已清理残留临时文件: {temp_path}")
                                    except Exception:
                                        pass
                                except Exception as del_e:
                                    try:
                                        LogManager.instance().warning(f"清理临时文件失败: {del_e}")
                                    except Exception:
                                        pass
                        continue

                    if "error" in msg.lower():
                        raise RuntimeError(msg)
                    else:
                        try:
                            LogManager.instance().warning(f"Exif 批量写入警告: {msg}")
                        except Exception:
                            pass
                break
        finally:
            if arg_file and os.path.exists(arg_file):
                try:
                    os.remove(arg_file)
                except Exception:
                    pass
            self._release_file_locks(file_locks)

    def _process_loop(self):
        """后台线程：一直运行，等待队列里的任务"""
        while self.running:
            try:
                try:
                    self._flush_write_buffer_ready()
                except Exception:
                    pass
                if self._write_futures:
                    completed = []
                    for item in self._write_futures:
                        future, batch = item
                        if not future.done():
                            continue
                        completed.append(item)
                        try:
                            future.result()
                            with self._task_count_lock:
                                self._completed_write_tasks += len(batch)
                        except Exception as e:
                            try:
                                LogManager.instance().error(f"Exif 批量写入错误: {e}")
                            except Exception:
                                pass
                        finally:
                            for _ in batch:
                                self.write_queue.task_done()
                            with self._batch_lock:
                                self._active_batch_tasks -= 1
                    if completed:
                        self._write_futures = [item for item in self._write_futures if item not in completed]
                try:
                    write_task = self.write_queue.get(timeout=0.1)
                    if write_task is None:
                        break
                    batch = [write_task]
                    while len(batch) < WRITE_BATCH_SIZE:
                        try:
                            extra = self.write_queue.get_nowait()
                        except queue.Empty:
                            break
                        if extra is None:
                            self.write_queue.put(None)
                            break
                        batch.append(extra)
                    
                    # 任务合并去重
                    merged_map = {}
                    files_order = []
                    for fp, tags in batch:
                         if fp not in merged_map:
                             merged_map[fp] = {}
                             files_order.append(fp)
                         merged_map[fp].update(tags)
                    
                    merged_tasks = [(fp, merged_map[fp]) for fp in files_order]

                    with self._batch_lock:
                        self._active_batch_tasks += 1
                    future = self._write_executor.submit(self._write_tags_batch, merged_tasks)
                    self._write_futures.append((future, batch))
                except queue.Empty:
                    pass

                try:
                    read_task = self.read_queue.get(timeout=0.1)
                    if read_task is None:
                        break
                    future, file_path, task_type = read_task

                    if not future.set_running_or_notify_cancel():
                        self.read_queue.task_done()
                        continue

                    try:
                        if task_type == READ_PICTURE_TIME_TAG:
                            res = self._read_time_popen(file_path)
                        elif task_type == READ_PICTURE_METADATA_TAG:
                            res = self._read_metadata_popen(file_path)
                        else:
                            res = self._read_tags_popen(file_path, task_type)
                        future.set_result(res)
                    except Exception as e:
                        future.set_exception(e)
                    self.read_queue.task_done()
                except queue.Empty:
                    continue
            except Exception as e:
                try:
                    LogManager.instance().warning(f"处理错误: {e}")
                except Exception:
                    pass

    def _write_async(self, file_path, tags):
        if not file_path or not tags:
            return
        if _is_exif_write_disabled():
            return
        mode = _get_exif_write_mode()
        target_path = str(file_path or "")
        if mode == "xmp":
            target_path = _to_sidecar_xmp_path(target_path)
            try:
                if target_path and not os.path.exists(target_path):
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "a", encoding="utf-8"):
                        pass
            except Exception:
                return
        try:
            if self._should_skip_duplicate_write(target_path, tags):
                return
        except Exception:
            pass
        self._buffer_write(target_path, tags)
    
    def _read_async(self, file_path, tags=None):
        """
        异步读取标签
        Args:
            file_path: 文件路径
            tags: 要读取的标签列表，None表示读取所有
        Returns:
            Future: 任务的 Future 对象
        """
        future = Future()
        self.read_queue.put((future, file_path, tags))
        return future
    
    def _read_sync(self, file_path, tags=None, timeout=3):
        """
        同步读取标签（阻塞直到完成）
        Args:
            file_path: 文件路径
            tags: 要读取的标签列表，None表示读取所有
            timeout: 超时时间（秒）
        Returns:
            dict: 读取到的标签数据
        """
        future = self._read_async(file_path, tags)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            raise e

    def get_tag(self, file_path, tag):
        return self._read_sync(file_path, tag)

    def get_tags(self, file_path, tags):
        return self._read_sync(file_path, tags)
    
    def get_time(self, file_path):
        return self._read_sync(file_path, READ_PICTURE_TIME_TAG)

    def get_times(self, file_paths, timeout=10):
        try:
            return self._read_time_popen_multi(file_paths, timeout=int(timeout))
        except Exception:
            out = {}
            try:
                for p in (file_paths or []):
                    if p:
                        out[str(p)] = None
            except Exception:
                out = {}
            return out

    def get_tags_multi(self, file_paths, tags, timeout=10):
        orig_paths = []
        try:
            for p in (file_paths or []):
                if p:
                    orig_paths.append(str(p))
        except Exception:
            orig_paths = []
        if not orig_paths:
            return {}
        mode = _get_exif_write_mode()
        paths = []
        path_map = {}
        if mode == "xmp":
            for p in orig_paths:
                tp = _to_sidecar_xmp_path(p)
                try:
                    if not os.path.exists(tp):
                        continue
                except Exception:
                    continue
                paths.append(tp)
                path_map[tp] = p
        else:
            paths = list(orig_paths)
            for p in orig_paths:
                path_map[p] = p
        if not paths:
            return {p: {} for p in orig_paths}

        tag_args = []
        if tags:
            for t in (tags or []):
                if not t:
                    continue
                ts = str(t)
                if ts.startswith("-"):
                    tag_args.append(ts)
                else:
                    tag_args.append(f"-{ts}")

        try:
            args = ["-j", "-SourceFile"]
            args.extend(tag_args)
            args.extend(paths)
            raw = self._stayopen_exec(args, timeout=int(timeout))
            data = json.loads(raw or "[]")
        except Exception:
            try:
                args = ["-j", "-SourceFile"]
                args.extend(tag_args)
                args.extend(paths)
                code, stdout, stderr = self._popen_exiftool(args, timeout=timeout)
                if code != 0:
                    raise RuntimeError((stderr or stdout or "").strip())
                data = json.loads(stdout or "[]")
            except Exception:
                data = []

        out = {}
        if isinstance(data, list):
            for meta in data:
                if not isinstance(meta, dict):
                    continue
                src = str(meta.get("SourceFile") or "")
                if not src:
                    continue
                orig = str(path_map.get(src) or "")
                if not orig:
                    continue
                out[orig] = meta
        for p in orig_paths:
            out.setdefault(p, {})
        return out
    
    def get_metadata(self, file_path):
        return self._read_sync(file_path, READ_PICTURE_METADATA_TAG)
    
    def set_metadata(self, file_path, tags_values):
        self._write_async(file_path, tags_values)

    def write_tags(self, file_path, tag_dict):
        if not file_path or not tag_dict:
            return
        self._write_async(file_path, tag_dict)

    def enqueue_update_tags(self, tasks):
        if not tasks:
            return
        if _is_exif_write_disabled():
            return
        try:
            for fp, tag_map in (tasks or []):
                if not fp or not tag_map:
                    continue
                self._write_async(fp, tag_map)
        except Exception:
            pass

    def read_tag(self, file_path, tag_name, timeout=3, raise_on_error=False):
        if not file_path or not tag_name:
            return None
        bmp_name = _extract_xmp_bmp_tag_name(tag_name)
        config_file = self._get_persistent_xmp_bmp_config_file() if bmp_name else None
        try:
            meta = self._read_json(file_path, tags=[tag_name], timeout=timeout, config_file=config_file)

            short_key = tag_name.split(":")[-1]
            tag_lower = tag_name.lower()
            short_lower = short_key.lower()

            for k, v in meta.items():
                key_lower = k.lower()
                if k == tag_name or key_lower == tag_lower or key_lower == short_lower:
                    return v

            for k, v in meta.items():
                key_lower = k.lower()
                if key_lower == short_lower or key_lower.endswith(f":{short_lower}"):
                    return v

            meta_all = self._read_json(file_path, tags=None, timeout=timeout, config_file=config_file)

            for k, v in meta_all.items():
                key_lower = k.lower()
                if k == tag_name or key_lower == tag_lower or key_lower == short_lower:
                    return v

            for k, v in meta_all.items():
                key_lower = k.lower()
                if key_lower == short_lower or key_lower.endswith(f":{short_lower}"):
                    return v

            fuzzy = [k for k in meta_all.keys() if short_lower in k.lower()]
            if len(fuzzy) == 1:
                return meta_all.get(fuzzy[0])

            return None
        except Exception as e:
            if raise_on_error:
                raise e
            try:
                LogManager.instance().warning(f"[read_tag] error for {file_path}, {tag_name}: {e}")
            except Exception:
                pass
            return None
        finally:
            pass

    def stop(self, force: bool = True):
        """停止后台线程"""
        self.running = False
        if force:
            try:
                with self._write_buffer_lock:
                    self._write_buffer.clear()
                    self._write_buffer_ts.clear()
            except Exception:
                pass
        try:
            self.write_queue.put(None)
        except Exception:
            pass
        try:
            self.read_queue.put(None)
        except Exception:
            pass
        try:
            for future, _ in (self._write_futures or []):
                try:
                    future.cancel()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._stop_stayopen_process()
        except Exception:
            pass
        try:
            self._terminate_active_processes(timeout=2.0)
        except Exception:
            pass
        try:
            self.thread.join(timeout=6)
        except Exception:
            pass
        try:
            if getattr(self, "_write_executor", None):
                try:
                    self._write_executor.shutdown(wait=True, cancel_futures=True)
                except TypeError:
                    self._write_executor.shutdown(wait=True)
        except Exception:
            pass
    
    def _update_tags_chunk(self, chunk, worker_id):
        """内部函数：处理通用标签更新的一个分块"""
        if not chunk:
            return 0
        
        exe = get_exiftool_path()
        import tempfile
        arg_file = None
        config_file = None
        processed_count = 0
        file_locks = []

        try:
            bmp_tag_names = set()
            file_paths = []
            try:
                file_paths = [p for p, _ in chunk if p]
            except Exception:
                file_paths = []
            file_locks = self._acquire_file_locks(file_paths)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8-sig') as f:
                for path, tags in chunk:
                    f.write(f"{path}\n")
                    for tag, value in tags.items():
                        tag = _normalize_xmp_bmp_tag_for_write(tag)
                        bmp_name = _extract_xmp_bmp_tag_name(tag)
                        if bmp_name:
                            bmp_tag_names.add(bmp_name)
                        f.write(f"-{tag}={value}\n")
                    f.write("-execute\n")
                    processed_count += 1
                arg_file = f.name

            config_file = self._get_persistent_xmp_bmp_config_file() if bmp_tag_names else None
            cmd = [exe]
            if config_file:
                cmd += ["-config", config_file]
            cmd += ["-charset", "utf8", "-@", arg_file, "-common_args", "-overwrite_original_in_place", "-P", "-m"]
            max_retries = 1
            for attempt in range(max_retries + 1):
                self._cleanup_exiftool_tmp(file_paths)
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **_subprocess_no_console_kwargs(),
                )
                self._register_active_process(process)
                try:
                    try:
                        timeout = int(max(20, min(240, 20 * max(1, len(chunk)))))
                    except Exception:
                        timeout = 120
                    try:
                        stdout, stderr = process.communicate(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        try:
                            process.kill()
                        except Exception:
                            pass
                        try:
                            stdout, stderr = process.communicate(timeout=5)
                        except Exception:
                            stdout, stderr = "", ""
                        try:
                            LogManager.instance().warning(f"UpdateWorker-{worker_id} ExifTool 批量写入超时({timeout}s)，回退逐文件写入")
                        except Exception:
                            pass
                        raise TimeoutError("exiftool_batch_timeout")
                finally:
                    self._unregister_active_process(process)
                if process.returncode == 0:
                    break
                msg = (stderr or stdout or "").strip()
                lower = msg.lower()
                if ("temporary file already exists" in lower or "error creating file" in lower) and attempt < max_retries:
                    self._cleanup_exiftool_tmp(file_paths)
                    time.sleep(0.15)
                    continue
                if msg and "error:" not in lower and "warning:" in lower:
                    break
                try:
                    LogManager.instance().warning(f"UpdateWorker-{worker_id} ExifTool 错误: {msg}")
                except Exception:
                    pass
                try:
                    for p, tags in chunk:
                        if not p or not tags:
                            continue
                        self._write_tags_popen(p, tags, timeout=60)
                    break
                except Exception:
                    raise

        except Exception as e:
            try:
                LogManager.instance().warning(f"UpdateWorker-{worker_id} 批量更新异常: {e}")
            except Exception:
                pass
            processed_count = 0 # 异常时认为未成功处理
        finally:
            if arg_file and os.path.exists(arg_file):
                try:
                    os.remove(arg_file)
                except Exception:
                    pass
            self._release_file_locks(file_locks)
        
        return processed_count

    def batch_update_tags(self, tasks):
        """
        批量更新通用标签（多线程加速版）
        tasks: list of (file_path, tags_dict)
        """
        if not tasks:
            return
        if _is_exif_write_disabled():
            return
        
        exe = get_exiftool_path()
        if not (os.path.isfile(exe) and os.access(exe, os.X_OK)):
            try:
                LogManager.instance().warning("exiftool 不存在，跳过批量标签更新")
            except Exception:
                pass
            return

        # 任务合并去重
        merged_map = {}
        files_order = []
        for fp, tags in tasks:
                if not fp: continue
                if fp not in merged_map:
                    merged_map[fp] = {}
                    files_order.append(fp)
                merged_map[fp].update(tags)
        
        merged_tasks = [(fp, merged_map[fp]) for fp in files_order]
        if not merged_tasks:
            return

        # 跨调用去重：短时间内对同一文件写入相同内容时，只保留第一次
        filtered_tasks = []
        for fp, tag_map in merged_tasks:
            try:
                if self._should_skip_duplicate_write(fp, tag_map):
                    continue
            except Exception:
                pass
            filtered_tasks.append((fp, tag_map))
        if not filtered_tasks:
            return

        # 增加活跃任务计数
        with self._batch_lock:
            self._active_batch_tasks += 1
            
        # 增加总任务计数 (使用过滤后的数量，更真实反映实际操作)
        with self._task_count_lock:
            self._total_write_tasks += len(filtered_tasks)

        try:
            # 设定并行进程数
            num_workers = min(4, len(filtered_tasks) // 20 + 1)
            
            pass
            start_all = time.time()
            
            # 将任务平分给各个 worker
            chunks = [filtered_tasks[i::num_workers] for i in range(num_workers)]
            
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [executor.submit(self._update_tags_chunk, chunks[i], i+1) for i in range(num_workers)]
                for f in as_completed(futures):
                    try:
                        processed_count = f.result()
                        # 更新已完成任务计数
                        with self._task_count_lock:
                            self._completed_write_tasks += processed_count
                    except Exception as e:
                        try:
                            LogManager.instance().warning(f"标签更新执行失败: {e}")
                        except Exception:
                            pass
                    
            total_time = time.time() - start_all
            try:
                try:
                    LogManager.instance().info(f"[EXIF][Batch] 完成 总数={len(tasks)} 耗时={total_time:.2f}s")
                except Exception:
                    pass
            except Exception:
                pass
        finally:
            # 无论成功失败，减少活跃任务计数
            with self._batch_lock:
                self._active_batch_tasks -= 1


# 创建唯一实例
# instance = ExifHandleWorker()

# 对外提供访问函数
def get_instance():
    return ExifHandleWorker.get_instance()
