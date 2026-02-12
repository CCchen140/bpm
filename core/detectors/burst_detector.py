import configparser
import os
import sys
import time
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2

from utils.exif.burst_time_reader import read_subsec_create_ts
from utils.log_manager import LogManager


def _setup_opencv_logging():
    """尽量关闭 OpenCV 在 stderr 的图片解码告警/错误输出，避免批量检测时刷屏"""
    try:
        if hasattr(cv2, "utils") and hasattr(cv2.utils, "logging") and hasattr(cv2.utils.logging, "setLogLevel"):
            level = getattr(cv2.utils.logging, "LOG_LEVEL_SILENT", None)
            if level is None:
                level = getattr(cv2.utils.logging, "LOG_LEVEL_ERROR", None)
            if level is not None:
                cv2.utils.logging.setLogLevel(level)
                return
    except Exception:
        pass

    try:
        if hasattr(cv2, "setLogLevel"):
            level = getattr(cv2, "LOG_LEVEL_SILENT", None)
            if level is None:
                level = getattr(cv2, "LOG_LEVEL_ERROR", None)
            if level is None:
                level = 3
            cv2.setLogLevel(level)
    except Exception:
        pass


_setup_opencv_logging()


@dataclass
class FileInfo:
    """文件信息类"""

    file_path: str
    file_name: str
    sub_dir: str
    is_root_dir: bool
    timestamp: Optional[float] = None
    dhash: Optional[int] = None


class BurstDetector:
    """连拍检测器"""

    def __init__(
        self,
        burst_fps: float = 0,
        burst_time_threshold: int = 3,
        burst_check_by_similarity: bool = False,
        burst_similarity_threshold: float = 0.85,
        allowable_error: float = 0.4,
    ):
        self.burst_fps = burst_fps
        self.burst_time_threshold = burst_time_threshold
        self.burst_check_by_similarity = burst_check_by_similarity
        self.burst_similarity_threshold = burst_similarity_threshold
        self.allowable_error = allowable_error

        self.check_burst = burst_fps > 0
        self.brust_interval = (1.0 / burst_fps) * 1000 if burst_fps > 0 else 0

        self.current_burst_group: List[FileInfo] = []
        self.saved_burst_group: List[FileInfo] = []
        self.previous_file: Optional[FileInfo] = None

        self._time_cache: Dict[str, Optional[float]] = {}
        self._dhash_cache: Dict[str, Optional[int]] = {}

        config = configparser.ConfigParser()
        if not os.path.exists("config.ini"):
            self.LanguageSelect = "zh"
            return

        config.read("config.ini", encoding="utf-8")
        self.LanguageSelect = config.get("config", "LanguageSelect", fallback="zh")

        if self.check_burst:
            try:
                LogManager.instance().info(
                    f"连拍模式: 目标间隔={self.brust_interval:.3f}ms 允许误差=±{self.allowable_error*100:.0f}%"
                )
            except Exception:
                pass

    def _get_file_time(self, file_path: str) -> Optional[float]:
        """获取文件拍摄时间（带缓存，使用 exifread 读取子秒时间）"""
        if not file_path:
            return None
        if file_path in self._time_cache:
            return self._time_cache[file_path]

        try:
            ts = read_subsec_create_ts(file_path)
            if ts is None:
                try:
                    ts = float(os.path.getmtime(file_path))
                except Exception:
                    ts = None
            self._time_cache[file_path] = ts
            return ts
        except Exception as e:
            try:
                LogManager.instance().warning(f"读取文件时间失败 {file_path}: {e}")
            except Exception:
                pass
            self._time_cache[file_path] = None
            return None

    def _get_file_dhash(self, file_path: str) -> Optional[int]:
        if not file_path:
            return None
        if file_path in self._dhash_cache:
            return self._dhash_cache[file_path]
        try:
            v = int(self.calculate_dhash(file_path, 8))
        except Exception:
            v = 0
        if v <= 0:
            self._dhash_cache[file_path] = None
            return None
        self._dhash_cache[file_path] = v
        return v

    def _prefetch_times(
        self,
        file_infos: List[FileInfo],
        batch_size: int = 500,
        timeout: int = 20,
        max_workers: Optional[int] = None,
    ):
        """
        批量预取时间，核心目标是减少重复 IO 并避免阻塞主流程。

        - 使用 exifread 读取 DateTimeOriginal/DateTimeDigitized + SubSecTime* 组合成带子秒的时间
        - 使用多进程并行读取，提升大批量目录的处理速度
        - 对取不到 EXIF 时间的文件，回退到 mtime，保证排序和间隔判断可用
        """
        paths: List[str] = []
        seen = set()
        for fi in file_infos or []:
            p = ""
            try:
                p = str(fi.file_path or "")
            except Exception:
                p = ""
            if p and p not in seen:
                seen.add(p)
                paths.append(p)
        if not paths:
            return

        if max_workers is None:
            try:
                cpu_count = int(os.cpu_count() or 4)
            except Exception:
                cpu_count = 4
            max_workers = min(8, max(1, cpu_count // 2))
        try:
            max_workers = int(max_workers)
        except Exception:
            max_workers = 1
        max_workers = max(1, max_workers)

        def _fill_with_fallback(p: str, ts: Optional[float]):
            if ts is None:
                try:
                    ts = float(os.path.getmtime(p))
                except Exception:
                    ts = None
            self._time_cache[p] = ts

        if max_workers <= 1:
            for p in paths:
                _fill_with_fallback(p, read_subsec_create_ts(p))
        else:
            try:
                ctx = mp.get_context("spawn")
                chunksize = 32
                bs = max(1, int(batch_size or 1))
                with ctx.Pool(processes=int(max_workers)) as pool:
                    for start in range(0, len(paths), bs):
                        chunk = paths[start : start + bs]
                        results = pool.map(read_subsec_create_ts, chunk, chunksize=chunksize)
                        for p, ts in zip(chunk, results):
                            _fill_with_fallback(p, ts)
            except Exception:
                for p in paths:
                    _fill_with_fallback(p, read_subsec_create_ts(p))

        for fi in file_infos or []:
            try:
                fi.timestamp = self._time_cache.get(str(fi.file_path or ""))
            except Exception:
                fi.timestamp = None

    def calculate_similarity(self, file_path: str, previous_dhash: int) -> float:
        """计算两张图片的相似度"""
        try:
            current_dhash = self._get_file_dhash(file_path) or 0
            _, sim = self.hamming_distance(int(current_dhash), int(previous_dhash or 0))
            return sim
        except Exception as e:
            try:
                LogManager.instance().warning(f"计算相似度失败: {e}")
            except Exception:
                pass
            return 0.0

    def is_burst_interval(self, interval: float) -> bool:
        """判断是否为连拍间隔"""
        if not self.check_burst:
            return False

        lower_bound = self.brust_interval * (1.0 - self.allowable_error)
        upper_bound = self.brust_interval * (1.0 + self.allowable_error)
        return lower_bound <= interval <= upper_bound

    def should_check_similarity(self, interval: float) -> bool:
        """判断是否需要检查相似度"""
        return (
            interval < 1000
            and self.burst_check_by_similarity
            and self.previous_file is not None
        )

    def process_file(
        self,
        file_info: FileInfo,
        get_exif_time_func: Callable,
        get_time_interval_func: Callable,
    ) -> Tuple[bool, Optional[str]]:
        """
        处理单个文件，判断是否属于当前连拍组

        返回:
            (是否结束当前连拍组, 连拍组第一张文件名)
        """
        if not self.check_burst or not self.previous_file:
            self.current_burst_group.append(file_info)
            self.previous_file = file_info
            return False, None

        current_timestamp = file_info.timestamp
        previous_timestamp = self.previous_file.timestamp

        if current_timestamp is None:
            current_timestamp = self._get_file_time(file_info.file_path)
            file_info.timestamp = current_timestamp
        if previous_timestamp is None:
            previous_timestamp = self._get_file_time(self.previous_file.file_path)
            self.previous_file.timestamp = previous_timestamp

        if current_timestamp is None and previous_timestamp is None:
            return False, None

        interval = float("inf")
        try:
            if current_timestamp is not None and previous_timestamp is not None:
                interval = abs((current_timestamp - previous_timestamp) * 1000.0)
        except Exception:
            interval = float("inf")

        if (
            interval == 0.0
            and current_timestamp is not None
            and previous_timestamp is not None
            and float(current_timestamp) == float(previous_timestamp)
        ):
            try:
                st1 = os.stat(str(file_info.file_path))
                st0 = os.stat(str(self.previous_file.file_path))
                t1 = float(getattr(st1, "st_mtime_ns", 0) or 0) / 1e9
                t0 = float(getattr(st0, "st_mtime_ns", 0) or 0) / 1e9
                if t1 > 0.0 and t0 > 0.0:
                    interval_fs = abs((t1 - t0) * 1000.0)
                    if interval_fs > 0.0:
                        interval = float(interval_fs)
            except Exception:
                pass

        try:
            LogManager.instance().debug(f"文件间隔: {file_info.file_name} curr={current_timestamp} prev={previous_timestamp} interval_ms={interval}")
        except Exception:
            pass

        is_burst = self.is_burst_interval(interval)
        if not is_burst and interval == 0.0 and current_timestamp is not None and previous_timestamp is not None:
            try:
                ext = os.path.splitext(str(file_info.file_path or ""))[1].lower()
            except Exception:
                ext = ""
            if ext in (".cr3", ".cr2", ".nef", ".arw", ".raf", ".dng", ".rw2", ".orf"):
                is_burst = True

        if not is_burst and self.should_check_similarity(interval):
            prev_dhash = self.previous_file.dhash
            if prev_dhash is None:
                prev_dhash = self._get_file_dhash(self.previous_file.file_path)
                self.previous_file.dhash = prev_dhash
            if prev_dhash is not None:
                similarity = self.calculate_similarity(file_info.file_path, prev_dhash)
                is_burst = similarity > self.burst_similarity_threshold
                try:
                    LogManager.instance().debug(f"相似度检测: {similarity:.3f}")
                except Exception:
                    pass

        if is_burst:
            self.current_burst_group.append(file_info)
            self.previous_file = file_info
            return False, None

        burst_first_file = ""
        if len(self.current_burst_group) >= self.burst_time_threshold:
            burst_first_file = self.current_burst_group[0].file_name

        self.saved_burst_group = self.current_burst_group.copy()
        self.previous_file = None
        self.current_burst_group = [file_info]
        return True, burst_first_file

    def finish_current_group(self) -> Tuple[List[FileInfo], Optional[str]]:
        """结束当前连拍组"""
        burst_first_file = ""
        if len(self.saved_burst_group) >= self.burst_time_threshold:
            burst_first_file = self.saved_burst_group[0].file_name

        finished_group = self.saved_burst_group.copy()
        self.saved_burst_group = []
        self.previous_file = None
        return finished_group, burst_first_file

    @staticmethod
    def calculate_dhash(image_path: str, hash_size: int = 8) -> int:
        """计算图片的差异哈希"""
        try:
            reduced_flag = getattr(cv2, "IMREAD_REDUCED_GRAYSCALE_8", None)
            if reduced_flag is None:
                reduced_flag = cv2.IMREAD_GRAYSCALE
            gray = cv2.imread(image_path, int(reduced_flag))
            if gray is None and reduced_flag != cv2.IMREAD_GRAYSCALE:
                gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        except Exception:
            return 0
        if gray is None:
            return 0

        resized = cv2.resize(gray, (hash_size + 1, hash_size))
        diff = resized[:, 1:] > resized[:, :-1]
        return sum([2**i for i, v in enumerate(diff.flatten()) if v])

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> Tuple[int, float]:
        """计算汉明距离和相似度"""
        hamming_dist = bin(hash1 ^ hash2).count("1")
        max_bits = 64
        similarity = 1 - (hamming_dist / max_bits)
        return hamming_dist, similarity

    @staticmethod
    def find_image_files(
        image_path: str,
        raw_exts: set,
        img_exts: set,
        exclude_dirs: Optional[set] = None,
    ) -> List[FileInfo]:
        """查找所有图片文件"""
        if exclude_dirs is None:
            exclude_dirs = {"hide"}

        image_files: List[FileInfo] = []

        def process_directory(dir_path: str, is_root: bool = True):
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        name = entry.name
                        if entry.is_file():
                            ext = os.path.splitext(name)[1].upper()
                            if ext in raw_exts or ext in img_exts:
                                sub_dir = "" if is_root else os.path.basename(dir_path)
                                image_files.append(
                                    FileInfo(
                                        file_path=entry.path,
                                        file_name=name,
                                        sub_dir=sub_dir,
                                        is_root_dir=is_root,
                                    )
                                )
                        elif entry.is_dir() and name not in exclude_dirs and is_root:
                            process_directory(entry.path, False)
            except PermissionError:
                try:
                    LogManager.instance().warning(f"无法访问目录: {dir_path}")
                except Exception:
                    pass
            except Exception as e:
                try:
                    LogManager.instance().warning(f"处理目录失败: {dir_path}: {e}")
                except Exception:
                    pass

        process_directory(image_path)
        return image_files

    @staticmethod
    def _get_time_interval_ms(t1: Optional[float], t2: Optional[float]) -> float:
        """获取两张图片拍摄时间的间隔（毫秒）"""
        if t1 is None or t2 is None:
            return float("inf")
        return abs((t2 - t1) * 1000.0)

    def process_image_directory(
        self,
        image_path: str,
        model_path: str,
        output_path: str,
        raw_exts: Optional[set] = None,
        img_exts: Optional[set] = None,
    ) -> List[Tuple]:
        """
        主处理函数：扫描目录并检测连拍

        返回:
            [(file_path, is_root_dir, sub_dir, file_name, model_path, output_path, burst_first_file), ...]
        """
        if raw_exts is None:
            raw_exts = {".CR2", ".CR3", ".NEF", ".ARW", ".DNG"}
        if img_exts is None:
            img_exts = {".JPG", ".JPEG", ".PNG", ".TIF", ".TIFF"}

        all_start_time = time.time()
        image_files = BurstDetector.find_image_files(image_path, raw_exts, img_exts)
        if not image_files:
            try:
                LogManager.instance().warning("未找到可处理的图片")
            except Exception:
                pass
            return []

        self._prefetch_times(image_files, batch_size=800, timeout=20)
        try:
            image_files.sort(key=lambda x: (x.timestamp is None, x.timestamp or 0.0, str(x.file_name or "")))
        except Exception:
            pass

        file_select: List[Tuple] = []

        for file_info in image_files:
            group_finished, burst_first_file = self.process_file(
                file_info, self._get_file_time, BurstDetector._get_time_interval_ms
            )
            if group_finished:
                finished_group, _ = self.finish_current_group()
                for item in finished_group:
                    file_select.append(
                        (
                            item.file_path,
                            item.is_root_dir,
                            item.sub_dir,
                            item.file_name,
                            model_path,
                            output_path,
                            burst_first_file,
                        )
                    )
            elif not self.check_burst:
                file_select.append(
                    (
                        file_info.file_path,
                        file_info.is_root_dir,
                        file_info.sub_dir,
                        file_info.file_name,
                        model_path,
                        output_path,
                        "",
                    )
                )

        if self.check_burst and self.current_burst_group:
            burst_first_file = ""
            if len(self.current_burst_group) >= self.burst_time_threshold:
                burst_first_file = self.current_burst_group[0].file_name
                for item in self.current_burst_group:
                    file_select.append(
                        (
                            item.file_path,
                            item.is_root_dir,
                            item.sub_dir,
                            item.file_name,
                            model_path,
                            output_path,
                            burst_first_file,
                        )
                    )
            else:
                for item in self.current_burst_group:
                    file_select.append(
                        (
                            item.file_path,
                            item.is_root_dir,
                            item.sub_dir,
                            item.file_name,
                            model_path,
                            output_path,
                            "",
                        )
                    )

        elapsed_time = time.time() - all_start_time
        try:
            LogManager.instance().info(f"连拍检测完成: 耗时={elapsed_time:.2f}s 文件数={len(file_select)}")
        except Exception:
            pass
        return file_select
