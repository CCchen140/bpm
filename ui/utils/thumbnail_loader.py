from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, Qt, QSize, QTimer
from PyQt6.QtGui import QImage, QImageReader
import os
import cv2
import numpy as np
from utils.file.file import load_image, extract_thumbnail, raw_exts
from utils.system.task_scheduler import TaskScheduler, TaskType
from utils.system.gpu_utils import GPUScaler
from cache.thumbnail_disk_cache import ThumbnailDiskCache
from utils.log_manager import LogManager

import time
import queue
from threading import Thread, Lock
from collections import deque

class ThumbnailRunnable(QRunnable):
    """缩略图加载任务"""
    def __init__(self, path, size, cache_manager, disk_cache, result_emitter, cache_type='general', request_id=None, priority=3, request_id_ref=None):
        super().__init__()
        self.path = path
        self.size = size
        self.cache_manager = cache_manager
        self.disk_cache = disk_cache
        self.result_emitter = result_emitter  # 结果发射回调函数，用于将结果放入队列
        self.cache_type = cache_type
        self.request_id = request_id
        self.priority = priority
        self.request_id_ref = request_id_ref

    def run(self):
        if self.request_id_ref is not None:
            active_id = self.request_id_ref.get("value")
            if active_id is not None and self.request_id is not None and int(self.request_id) != int(active_id):
                return
        start_time = time.time()
        from_cache = False
        attempts = 0
        try:
            disable_scaling = False
            try:
                if hasattr(self.cache_manager, "settings_manager"):
                    disable_scaling = bool(self.cache_manager.settings_manager.get("performance/thumbnail_disable_scaling", False))
            except Exception:
                disable_scaling = False
            use_gpu_scaling = True
            try:
                if hasattr(self.cache_manager, "settings_manager"):
                    use_gpu_scaling = bool(self.cache_manager.settings_manager.get("performance/use_gpu_scaling", True))
            except Exception:
                use_gpu_scaling = True
            scale_quality = "low"
            try:
                if hasattr(self.cache_manager, "get_scale_quality"):
                    scale_quality = str(self.cache_manager.get_scale_quality()).lower()
                elif hasattr(self.cache_manager, "settings_manager"):
                    scale_quality = str(self.cache_manager.settings_manager.get("performance/thumbnail_scale_quality", "low")).lower()
            except Exception:
                scale_quality = "low"
            is_import_ctx = False
            try:
                is_import_ctx = str(getattr(self.cache_manager, "context", "") or "").lower() == "import"
            except Exception:
                is_import_ctx = False

            if self.cache_type == "import":
                is_import_ctx = True

            # 导入页面强制使用低质量缩略图
            if is_import_ctx:
                try:
                    if hasattr(self.cache_manager, "settings_manager"):
                        force_low_quality = bool(self.cache_manager.settings_manager.get("import/force_low_quality", True))
                        if force_low_quality:
                            scale_quality = "low"
                except Exception:
                    pass
            transformation_mode = Qt.TransformationMode.SmoothTransformation if scale_quality == "high" else Qt.TransformationMode.FastTransformation
            if disable_scaling:
                transformation_mode = Qt.TransformationMode.FastTransformation
            try:
                if is_import_ctx and int(self.priority) <= 0:
                    transformation_mode = Qt.TransformationMode.SmoothTransformation
            except Exception:
                pass

            def _get_req_max():
                if not self.size:
                    return 0
                try:
                    rw, rh = self.size if isinstance(self.size, (tuple, list)) else (self.size, self.size)
                    rw = int(rw or 0)
                    rh = int(rh or 0)
                    return max(rw, rh)
                except Exception:
                    return 0

            # 1. 检查缓存
            try:
                cached_image = self.cache_manager.get_image(self.path)
            except Exception:
                cached_image = None

            if cached_image:
                try:
                    if self.size and not disable_scaling:
                        req_w, req_h = self.size if isinstance(self.size, (tuple, list)) else (self.size, self.size)
                        req_w = int(req_w or 0)
                        req_h = int(req_h or 0)
                        if req_w > 0 and req_h > 0:
                            req_max = max(req_w, req_h)
                            cached_max = max(int(cached_image.width() or 0), int(cached_image.height() or 0))
                            if cached_max > 0 and (req_max > cached_max * 1.15 or req_max - cached_max >= 24):
                                cached_image = None
                except Exception:
                    pass

            if cached_image:
                from_cache = True
                # Scale in background thread if size is provided
                output_image = cached_image
                if self.size and not disable_scaling:
                    try:
                        w, h = self.size if isinstance(self.size, (tuple, list)) else (self.size, self.size)
                        if (
                            w > 0
                            and h > 0
                            and not cached_image.isNull()
                            and cached_image.width() > 0
                            and cached_image.height() > 0
                        ):
                            ratio = min(w / cached_image.width(), h / cached_image.height())
                            new_w = int(max(1, round(cached_image.width() * ratio)))
                            new_h = int(max(1, round(cached_image.height() * ratio)))
                            if abs(new_w - cached_image.width()) >= 2 or abs(new_h - cached_image.height()) >= 2:
                                # 根据设置决定是否使用GPUScaler
                                if use_gpu_scaling:
                                    scaled = GPUScaler.scale_qimage(
                                        cached_image,
                                        w,
                                        h,
                                        keep_aspect=True,
                                        fast_mode=transformation_mode == Qt.TransformationMode.FastTransformation
                                    )
                                    output_image = scaled if scaled is not None else cached_image.scaled(
                                        new_w,
                                        new_h,
                                        Qt.AspectRatioMode.KeepAspectRatio,
                                        transformation_mode
                                    )
                                else:
                                    output_image = cached_image.scaled(
                                        new_w,
                                        new_h,
                                        Qt.AspectRatioMode.KeepAspectRatio,
                                        transformation_mode
                                    )
                    except Exception:
                        pass
                
                # 确保图片格式为 ARGB32_Premultiplied，这是 QPixmap.fromImage 最快的格式
                if output_image is not None and not output_image.isNull() and output_image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                    output_image = output_image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

                try:
                    base_px = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
                except Exception:
                    base_px = 0
                try:
                    if self.disk_cache is not None and not self.disk_cache.has(self.path, self.size, cache_type=self.cache_type, scale_quality=scale_quality, base_px=base_px):
                        self.disk_cache.put(self.path, output_image, self.size, cache_type=self.cache_type, scale_quality=scale_quality, base_px=base_px)
                except Exception:
                    pass

                if self.result_emitter:
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.result_emitter(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                return

            try:
                try:
                    base_px = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
                except Exception:
                    base_px = 0
                if self.disk_cache is not None:
                    disk_img = self.disk_cache.get(self.path, self.size, cache_type=self.cache_type, scale_quality=scale_quality, base_px=base_px)
                else:
                    disk_img = None
            except Exception:
                disk_img = None
            if disk_img is not None and not (hasattr(disk_img, "isNull") and disk_img.isNull()):
                from_cache = True
                try:
                    should_put = True
                    try:
                        base_px2 = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
                    except Exception:
                        base_px2 = 0
                    try:
                        disk_max = max(int(disk_img.width() or 0), int(disk_img.height() or 0))
                    except Exception:
                        disk_max = 0
                    if base_px2 > 0 and disk_max > 0 and disk_max < int(base_px2 * 0.9):
                        should_put = False
                    if should_put:
                        try:
                            existing = self.cache_manager.get_image(self.path)
                        except Exception:
                            existing = None
                        if existing is not None and hasattr(existing, "width") and hasattr(existing, "height"):
                            try:
                                existing_max = max(int(existing.width() or 0), int(existing.height() or 0))
                            except Exception:
                                existing_max = 0
                            if existing_max >= disk_max and existing_max > 0:
                                should_put = False
                    if should_put:
                        self.cache_manager.put(self.path, disk_img, self.cache_type)
                except Exception:
                    pass
                output_image = disk_img
                if output_image is not None and not output_image.isNull() and output_image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                    output_image = output_image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                if self.result_emitter:
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.result_emitter(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                return

            # 2. 加载图片
            if os.path.exists(self.path):
                ext = os.path.splitext(self.path)[1].upper()
                image = None
                # 尝试从 focus_scaled_cache 加载缩略图（对焦检测时生成的缓存）
                # 不仅限于导入页面，图库页面也可以使用这个缓存
                try:
                    focus_target = 640
                    if hasattr(self.cache_manager, "settings_manager") and self.cache_manager.settings_manager:
                        focus_target = int(self.cache_manager.settings_manager.get("focus_detect/target_size", 640) or 640)
                    from cache.focus_scaled_cache import try_load_qimage

                    img2, _meta2 = try_load_qimage(self.path, int(focus_target), scope="import_focus")
                    if img2 is not None and not img2.isNull():
                        image = img2
                        from_cache = True
                except Exception:
                    pass
                target_size = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
                if not disable_scaling:
                    req_max = _get_req_max()
                    if req_max > 0 and (target_size <= 0 or req_max > target_size):
                        target_size = req_max
                # 限制最大目标尺寸，避免内存占用过大
                # 支持更大的缩略图尺寸以适应高DPI显示器和放大查看需求
                max_target_size = 4096
                if target_size > max_target_size:
                    target_size = max_target_size
                
                # 检查从focus_scaled_cache加载的图片尺寸是否足够
                if image is not None and not image.isNull() and target_size > 0:
                    img_max = max(int(image.width() or 0), int(image.height() or 0))
                    if img_max > 0 and (img_max < int(target_size * 0.85) or target_size - img_max >= 32):
                        # 尺寸不够，丢弃并重新加载
                        image = None
                        from_cache = False
                
                if image is None or (hasattr(image, "isNull") and image.isNull()):
                    # 渐进式加载策略：
                    # 1. 首先尝试从EXIF加载内置缩略图（最快）
                    # 2. 然后使用QImageReader加载（中等速度）
                    # 3. 最后使用OpenCV加载（最慢但最兼容）
                    
                    for attempt in range(3):
                        attempts = attempt + 1
                        
                        # 第一次尝试：使用QImageReader快速加载
                        if attempt == 0 and ext not in raw_exts and ext not in (".TIF", ".TIFF"):
                            try:
                                from utils.system.stderr_suppressor import suppress_stderr_fd

                                with suppress_stderr_fd():
                                    reader = QImageReader(self.path)
                                    if reader.canRead():
                                        try:
                                            # 使用较小的目标尺寸进行快速加载
                                            # 如果目标尺寸很大，先加载一个中等尺寸的图片
                                            quick_target = target_size
                                            if target_size > 800:
                                                # 先加载一个中等尺寸的图片，让用户快速看到内容
                                                quick_target = min(400, target_size // 2)
                                            
                                            if quick_target:
                                                size = reader.size()
                                                if size.isValid():
                                                    w = size.width()
                                                    h = size.height()
                                                    if w > 0 and h > 0:
                                                        if w >= h:
                                                            scaled_w = int(quick_target)
                                                            scaled_h = int(max(1, round(h * quick_target / w)))
                                                        else:
                                                            scaled_h = int(quick_target)
                                                            scaled_w = int(max(1, round(w * quick_target / h)))
                                                        reader.setScaledSize(QSize(scaled_w, scaled_h))
                                            image = reader.read()
                                            
                                            # 如果加载成功且尺寸足够，直接返回
                                            # 否则继续尝试加载更高分辨率
                                            if image is not None and not image.isNull():
                                                img_max = max(int(image.width() or 0), int(image.height() or 0))
                                                if img_max >= int(target_size * 0.85):
                                                    break  # 尺寸足够，跳出循环
                                                # 尺寸不够，继续下一次尝试加载更高分辨率
                                        except Exception:
                                            image = None
                            except Exception:
                                image = None
                        
                        # 第二次尝试：使用QImageReader加载完整分辨率
                        elif attempt == 1 and ext not in raw_exts and ext not in (".TIF", ".TIFF"):
                            try:
                                from utils.system.stderr_suppressor import suppress_stderr_fd

                                with suppress_stderr_fd():
                                    reader = QImageReader(self.path)
                                    if reader.canRead():
                                        try:
                                            if target_size:
                                                size = reader.size()
                                                if size.isValid():
                                                    w = size.width()
                                                    h = size.height()
                                                    if w > 0 and h > 0:
                                                        if w >= h:
                                                            scaled_w = int(target_size)
                                                            scaled_h = int(max(1, round(h * target_size / w)))
                                                        else:
                                                            scaled_h = int(target_size)
                                                            scaled_w = int(max(1, round(w * target_size / h)))
                                                        reader.setScaledSize(QSize(scaled_w, scaled_h))
                                            image = reader.read()
                                        except Exception:
                                            image = None
                            except Exception:
                                image = None
                        if image is None or (hasattr(image, "isNull") and image.isNull()):
                            cv_img = None
                            try:
                                cv_img = load_image(self.path)
                            except Exception:
                                cv_img = None
                            if cv_img is None:
                                if ext in raw_exts:
                                    try:
                                        cv_img = extract_thumbnail(self.path)
                                    except Exception:
                                        cv_img = None
                            if cv_img is not None:
                                try:
                                    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                                    height, width, channel = cv_img.shape
                                    bytes_per_line = 3 * width
                                    image = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
                                except Exception:
                                    image = None
                        if image is None or (hasattr(image, "isNull") and image.isNull()):
                            try:
                                with open(self.path, "rb") as f:
                                    data = f.read()
                                image = QImage.fromData(data)
                            except Exception:
                                image = None
                        if image is not None and (not hasattr(image, "isNull") or not image.isNull()):
                            break
                        if attempt < 2:
                            time.sleep(0.05)

                if image is not None and (not hasattr(image, "isNull") or not image.isNull()):
                    scaled_image = image
                    # 根据设置决定是否使用GPUScaler
                    if target_size and (image.width() > target_size or image.height() > target_size):
                        if use_gpu_scaling:
                            scaled = GPUScaler.scale_qimage(
                                image,
                                target_size,
                                target_size,
                                keep_aspect=True,
                                fast_mode=transformation_mode == Qt.TransformationMode.FastTransformation
                            )
                            scaled_image = scaled if scaled is not None else image.scaled(
                                target_size,
                                target_size,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                transformation_mode
                            )
                        else:
                            scaled_image = image.scaled(
                                target_size,
                                target_size,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                transformation_mode
                            )
                    if not scaled_image.isNull():
                        self.cache_manager.put(self.path, scaled_image, self.cache_type)
                        
                        # Scale for display if needed (avoid main thread scaling)
                        output_image = scaled_image
                        if self.size and not disable_scaling:
                            try:
                                w, h = self.size if isinstance(self.size, (tuple, list)) else (self.size, self.size)
                                if (
                                    w > 0
                                    and h > 0
                                    and not scaled_image.isNull()
                                    and scaled_image.width() > 0
                                    and scaled_image.height() > 0
                                ):
                                    ratio = min(w / scaled_image.width(), h / scaled_image.height())
                                    new_w = int(max(1, round(scaled_image.width() * ratio)))
                                    new_h = int(max(1, round(scaled_image.height() * ratio)))
                                    if abs(new_w - scaled_image.width()) >= 2 or abs(new_h - scaled_image.height()) >= 2:
                                        # 根据设置决定是否使用GPUScaler
                                        if use_gpu_scaling:
                                            scaled = GPUScaler.scale_qimage(
                                                scaled_image,
                                                w,
                                                h,
                                                keep_aspect=True,
                                                fast_mode=transformation_mode == Qt.TransformationMode.FastTransformation
                                            )
                                            output_image = scaled if scaled is not None else scaled_image.scaled(
                                                new_w,
                                                new_h,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                transformation_mode
                                            )
                                        else:
                                            output_image = scaled_image.scaled(
                                                new_w,
                                                new_h,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                transformation_mode
                                            )
                            except Exception:
                                pass

                        # 确保图片格式为 ARGB32_Premultiplied，这是 QPixmap.fromImage 最快的格式
                        if output_image is not None and not output_image.isNull() and output_image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                            output_image = output_image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

                        try:
                            if self.disk_cache is not None:
                                try:
                                    base_px = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
                                except Exception:
                                    base_px = 0
                                self.disk_cache.put(self.path, output_image, self.size, cache_type=self.cache_type, scale_quality=scale_quality, base_px=base_px)
                        except Exception:
                            pass

                        if self.result_emitter:
                            elapsed_ms = (time.time() - start_time) * 1000.0
                            self.result_emitter(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                    else:
                        if self.result_emitter:
                            elapsed_ms = (time.time() - start_time) * 1000.0
                            self.result_emitter(self.path, None, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                else:
                    if self.result_emitter:
                        elapsed_ms = (time.time() - start_time) * 1000.0
                        self.result_emitter(self.path, None, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
        except Exception as e:
            try:
                LogManager.instance().warning(f"加载缩略图失败: {self.path}: {e}")
            except Exception:
                pass
            try:
                if self.result_emitter:
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.result_emitter(self.path, None, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
            except Exception:
                pass

class ThumbnailLoaderSignals(QObject):
    """信号类，因为 QRunnable 不是 QObject
    
    注意：这些信号会在主线程中通过队列异步发射，确保不会阻塞工作线程
    """
    loaded = pyqtSignal(str, object) # path, QImage
    loaded_metrics = pyqtSignal(str, object, int, float, bool, int)

class ThumbnailLoader(QObject):
    """缩略图多线程加载器 - 优化版
    
    优化点：
    1. 智能并发控制：限制同时运行的任务数，避免CPU过载
    2. 优先级调度：可见区域优先，预加载延后
    3. 批量处理：减少任务提交开销
    4. 动态线程数：根据系统负载调整
    """
    
    # 优先级常量
    PRIORITY_IMMEDIATE = -2  # 立即可见区域，最高优先级
    PRIORITY_VISIBLE = -1    # 可见区域
    PRIORITY_ADJACENT = 0    # 相邻区域（预加载）
    PRIORITY_PRELOAD = 1     # 预加载区域
    PRIORITY_BACKGROUND = 2  # 后台加载
    
    def __init__(self, cache_manager, task_type=TaskType.DEFAULT):
        super().__init__()
        self.cache_manager = cache_manager
        scope = "import" if str(getattr(cache_manager, "context", "")).lower() == "import" else "library"
        self.disk_cache = ThumbnailDiskCache(cache_manager, scope=scope)
        try:
            self.disk_cache.cleanup_async(delay_sec=8.0)
        except Exception:
            pass
        
        # 使用自定义线程池，更好地控制并发
        self.thread_pool = QThreadPool()
        scheduler = TaskScheduler.instance()
        self._default_thread_count = scheduler.get_thread_count(task_type)
        # 限制最大线程数，避免过多线程竞争
        self._max_thread_count = min(self._default_thread_count, 4)
        self.thread_pool.setMaxThreadCount(self._max_thread_count)
        
        self.signals = ThumbnailLoaderSignals()
        
        # 使用双队列系统：高优先级队列和普通队列
        self._high_priority_queue = queue.PriorityQueue()  # 优先级 <= 0
        self._normal_queue = queue.PriorityQueue()         # 优先级 > 0
        self._queue_lock = Lock()
        self._seq = 0
        self._front_seq = 0
        self._running = True
        self._active_request_id = None
        self._request_id_ref = {"value": None}
        
        # 正在运行的任务计数
        self._running_tasks = 0
        self._running_tasks_lock = Lock()
        
        # 批量处理相关
        self._batch_buffer = []
        self._batch_lock = Lock()
        self._batch_timer = None
        
        # 结果队列：工作线程将结果放入此队列，主线程定时器异步处理
        # 这样可以确保信号真正在主线程异步发射，避免阻塞工作线程
        self._result_queue = deque()
        self._result_queue_lock = Lock()
        self._result_timer = QTimer(self)
        # 使用8ms间隔（约120fps），提高UI更新频率，加快缩略图显示速度
        self._result_timer.setInterval(8)
        self._result_timer.timeout.connect(self._process_result_queue)
        self._result_timer.start()
        
        # 启动调度器线程
        self._dispatcher = Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher.start()
        
    def set_max_thread_count(self, count):
        """设置最大线程数"""
        if count > 0:
            # 限制最大线程数，避免过多线程竞争CPU
            self._max_thread_count = min(int(count), 4)
            self.thread_pool.setMaxThreadCount(self._max_thread_count)
    
    def _emit_loaded(self, path, image):
        """将加载结果放入队列，由主线程定时器异步处理
        
        参数:
            path: 图片路径
            image: 加载的图片
        """
        with self._result_queue_lock:
            self._result_queue.append(('loaded', path, image))
    
    def _emit_loaded_metrics(self, path, image, request_id, elapsed_ms, from_cache, attempts):
        """将加载指标放入队列，由主线程定时器异步处理
        
        参数:
            path: 图片路径
            image: 加载的图片
            request_id: 请求ID
            elapsed_ms: 耗时（毫秒）
            from_cache: 是否来自缓存
            attempts: 尝试次数
        """
        with self._result_queue_lock:
            self._result_queue.append(('metrics', path, image, request_id, elapsed_ms, from_cache, attempts))
    
    def _on_thumbnail_result(self, path, image, request_id, elapsed_ms, from_cache, attempts):
        """缩略图加载结果回调函数
        
        由工作线程调用，将结果放入队列，由主线程定时器异步发射信号
        
        参数:
            path: 图片路径
            image: 加载的图片
            request_id: 请求ID
            elapsed_ms: 耗时（毫秒）
            from_cache: 是否来自缓存
            attempts: 尝试次数
        """
        with self._result_queue_lock:
            self._result_queue.append(('loaded', path, image))
            self._result_queue.append(('metrics', path, image, request_id, elapsed_ms, from_cache, attempts))
    
    def _process_result_queue(self):
        """处理结果队列，在主线程中异步发射信号
        
        每帧最多处理5个结果，避免阻塞主线程
        配合8ms间隔，确保120fps流畅度，加快缩略图显示
        """
        max_per_frame = 5
        processed = 0
        
        while processed < max_per_frame:
            result = None
            with self._result_queue_lock:
                if self._result_queue:
                    result = self._result_queue.popleft()
            
            if result is None:
                break
            
            try:
                if result[0] == 'loaded':
                    # result = ('loaded', path, image)
                    self.signals.loaded.emit(result[1], result[2])
                elif result[0] == 'metrics':
                    # result = ('metrics', path, image, request_id, elapsed_ms, from_cache, attempts)
                    self.signals.loaded_metrics.emit(result[1], result[2], result[3], result[4], result[5], result[6])
            except Exception:
                pass
            
            processed += 1

    def shutdown(self):
        """停止加载器并清理资源"""
        self._running = False
        self._result_timer.stop()
        self.cancel_all()
        self.thread_pool.waitForDone(200)
        
    def load_thumbnails(self, paths, current_display_size, cache_type='general', request_id=None, default_priority=3):
        """提交加载任务 - 批量优化版
        
        参数:
            paths: 路径列表，可以是字符串或 (priority, path) 元组
            current_display_size: 当前显示尺寸
            cache_type: 缓存类型
            request_id: 请求ID，用于批量取消
            default_priority: 默认优先级
        """
        if not paths:
            return
            
        # 批量处理，减少锁竞争
        tasks_to_enqueue = []
        for item in paths:
            priority = default_priority
            path = item
            front = False
            if isinstance(item, dict):
                path = item.get("path")
                priority = item.get("priority", default_priority)
                front = bool(item.get("front", False))
            elif isinstance(item, (list, tuple)):
                if len(item) >= 2 and isinstance(item[0], (int, float)):
                    priority = int(item[0])
                    path = item[1]
                    if len(item) >= 3:
                        front = bool(item[2])
                elif len(item) >= 2:
                    path = item[0]
                    priority = int(item[1])
                    if len(item) >= 3:
                        front = bool(item[2])
            if not path:
                continue
            tasks_to_enqueue.append((priority, path, current_display_size, cache_type, request_id, front))
        
        # 批量入队
        with self._queue_lock:
            for priority, path, size, cache_type, request_id, front in tasks_to_enqueue:
                if front:
                    self._front_seq -= 1
                    seq = self._front_seq
                else:
                    self._seq += 1
                    seq = self._seq
                # 根据优先级选择队列
                if priority <= 0:
                    self._high_priority_queue.put((int(priority), seq, path, size, cache_type, request_id))
                else:
                    self._normal_queue.put((int(priority), seq, path, size, cache_type, request_id))

    def _dispatch_loop(self):
        """调度循环 - 优先处理高优先级任务 - 优化版
        
        优化点：
        1. 控制任务分发频率，避免CPU过载
        2. 使用更短的睡眠时间，提高响应性
        3. 批量检查队列状态，减少锁竞争
        4. 限制每帧分发的任务数，避免UI线程被信号淹没
        """
        while self._running:
            # 检查当前运行的任务数
            with self._running_tasks_lock:
                current_running = self._running_tasks
            
            # 如果已经有太多任务在运行，等待一下
            if current_running >= self._max_thread_count:
                time.sleep(0.005)  # 缩短等待时间，提高响应性
                continue
            
            # 限制每帧分发的任务数，避免一次性分发太多任务导致UI线程被信号淹没
            tasks_per_frame = 0
            max_tasks_per_frame = 4  # 每帧最多分发4个任务，提高并发度
            
            while tasks_per_frame < max_tasks_per_frame:
                task = None
                # 优先从高优先级队列获取
                try:
                    task = self._high_priority_queue.get_nowait()
                except queue.Empty:
                    # 高优先级队列为空，尝试普通队列
                    try:
                        task = self._normal_queue.get_nowait()
                    except queue.Empty:
                        # 两个队列都为空，跳出内层循环
                        break
                
                if task is None:
                    break
                    
                priority, seq, path, size, cache_type, request_id = task
                
                # 检查请求ID是否匹配
                if self._active_request_id is not None and request_id is not None and int(request_id) != int(self._active_request_id):
                    continue
                
                # 创建并启动任务
                # 使用结果发射回调函数，将结果放入队列，由主线程定时器异步处理
                runnable = ThumbnailRunnable(path, size, self.cache_manager, self.disk_cache, self._on_thumbnail_result, cache_type, request_id, priority, self._request_id_ref)
                
                # 包装任务以跟踪运行状态
                wrapped_runnable = self._wrap_runnable(runnable)
                self.thread_pool.start(wrapped_runnable)
                
                tasks_per_frame += 1
                
                # 每分发一个任务后，让出时间片，避免阻塞
                time.sleep(0.0005)
            
            # 如果本帧没有分发任何任务，等待一下
            if tasks_per_frame == 0:
                time.sleep(0.01)

    def _wrap_runnable(self, runnable):
        """包装runnable以跟踪运行状态"""
        original_run = runnable.run
        
        def wrapped_run():
            with self._running_tasks_lock:
                self._running_tasks += 1
            try:
                original_run()
            finally:
                with self._running_tasks_lock:
                    self._running_tasks -= 1
        
        runnable.run = wrapped_run
        return runnable

    def cancel_all(self):
        """取消所有任务"""
        try:
            self.thread_pool.clear()
        except:
            pass
        self.cancel_pending()

    def cancel_pending(self):
        """取消队列中等待的任务"""
        try:
            # 清空两个队列
            with self._queue_lock:
                try:
                    while not self._high_priority_queue.empty():
                        self._high_priority_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    while not self._normal_queue.empty():
                        self._normal_queue.get_nowait()
                except queue.Empty:
                    pass
            
            # 清空线程池中等待的任务
            if hasattr(self.thread_pool, "clear"):
                self.thread_pool.clear()
                
        except Exception as e:
            try:
                LogManager.instance().warning(f"取消缩略图待处理任务失败: {e}")
            except Exception:
                pass

    def set_active_request_id(self, request_id):
        """设置活动请求ID，用于批量取消旧请求的任务"""
        self._active_request_id = request_id
        self._request_id_ref["value"] = request_id
        
    def get_queue_stats(self):
        """获取队列统计信息，用于调试"""
        try:
            high_count = self._high_priority_queue.qsize()
            normal_count = self._normal_queue.qsize()
            with self._running_tasks_lock:
                running = self._running_tasks
            return {
                "high_priority": high_count,
                "normal": normal_count,
                "running": running,
                "max_threads": self._max_thread_count
            }
        except Exception:
            return {}
