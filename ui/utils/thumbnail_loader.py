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
                # 缓存命中：快速路径，直接返回缓存图片
                output_image = cached_image

                # 只有当缓存图片比目标大很多时才进行缩放
                if self.size and not disable_scaling:
                    try:
                        w, h = self.size if isinstance(self.size, (tuple, list)) else (self.size, self.size)
                        if w > 0 and h > 0 and cached_image.width() > w * 1.2 and cached_image.height() > h * 1.2:
                            output_image = cached_image.scaled(
                                w,
                                h,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            )
                    except Exception:
                        pass

                # 注意：格式转换延迟到显示时进行，减少后台线程开销
                # 原代码：if output_image.format() != QImage.Format.Format_ARGB32_Premultiplied: ...

                if self.result_emitter:
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.result_emitter(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                return

            # 优化：简化磁盘缓存检查，减少try-except开销
            base_px = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
            disk_img = None
            if self.disk_cache is not None:
                disk_img = self.disk_cache.get(self.path, self.size, cache_type=self.cache_type, scale_quality=scale_quality, base_px=base_px)

            if disk_img is not None and not disk_img.isNull():
                from_cache = True
                # 磁盘缓存命中：快速路径
                output_image = disk_img

                # 保存到内存缓存
                self.cache_manager.put(self.path, disk_img, self.cache_type)

                # 注意：格式转换延迟到显示时进行

                if self.result_emitter:
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.result_emitter(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                return

            # 1.5 检查对焦检测缓存（导入页面优先使用）
            # 对焦检测时会生成缩略图并保存到focus_scaled_cache，这里直接读取
            # 导入页面（包括真实文件模式和虚拟文件模式）都可以使用对焦检测缓存
            # 缩放尺寸固定为640，与对焦检测保存时一致
            if is_import_ctx or self.cache_type == 'import':
                try:
                    from cache.focus_scaled_cache import try_load_qimage
                    focus_target = 640  # 固定为640，与对焦检测保存时一致
                    focus_img, focus_meta = try_load_qimage(self.path, focus_target, scope="import_focus")
                    if focus_img is not None and not focus_img.isNull():
                        from_cache = True
                        # 对焦检测缓存命中：直接使用，无需重新生成
                        output_image = focus_img
                        # 记录缓存命中
                        try:
                            from utils.log_manager import LogManager
                            LogManager.instance().info(f"[ThumbnailLoader] 对焦检测缓存命中: {os.path.basename(self.path)}")
                        except Exception:
                            pass

                        # 保存到内存缓存
                        self.cache_manager.put(self.path, focus_img, self.cache_type)

                        if self.result_emitter:
                            elapsed_ms = (time.time() - start_time) * 1000.0
                            self.result_emitter(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                        return
                except Exception as e:
                    # 记录异常
                    try:
                        from utils.log_manager import LogManager
                        LogManager.instance().info(f"[ThumbnailLoader] 加载对焦检测缓存异常: {os.path.basename(self.path)}: {e}")
                    except Exception:
                        pass

            # 2. 加载图片（统一使用一个try-except）
            # 优化：移除os.path.exists检查，直接尝试加载，减少一次系统调用
            ext = os.path.splitext(self.path)[1].upper() if self.path else ""
            image = None
            
            # 计算目标尺寸
            target_size = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
            if not disable_scaling:
                req_max = _get_req_max()
                if req_max > 0 and (target_size <= 0 or req_max > target_size):
                    target_size = req_max
            # 限制最大目标尺寸
            if target_size > 4096:
                target_size = 4096
            
            # XNView风格的高效加载策略：
            # 1. 首先尝试从EXIF加载内置缩略图（最快）
            # 2. 使用QImageReader的setScaledSize（在解码时缩放）
            # 3. 避免使用OpenCV加载完整图片（除非万不得已）
            
            # 第一次尝试：从EXIF加载内置缩略图（最快）
            if image is None and ext not in raw_exts:
                exif_thumb = extract_thumbnail(self.path)
                if exif_thumb is not None:
                    exif_thumb = cv2.cvtColor(exif_thumb, cv2.COLOR_BGR2RGB)
                    h, w, _ = exif_thumb.shape
                    image = QImage(exif_thumb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
                    attempts = 1
            
            # 第二次尝试：使用QImageReader（在解码时缩放）
            # 优化：如果开启GPU加速且GPU可用，使用GPUScaler进行缩放
            if image is None and ext not in raw_exts and ext not in (".TIF", ".TIFF"):
                from utils.system.stderr_suppressor import suppress_stderr_fd
                with suppress_stderr_fd():
                    reader = QImageReader(self.path)
                    if reader.canRead():
                        # 如果开启GPU加速，尝试使用GPU进行缩放
                        if use_gpu_scaling and GPUScaler.is_available() and target_size > 0:
                            # 先读取原始图片
                            orig_img = reader.read()
                            if orig_img is not None and not orig_img.isNull():
                                # 使用GPU进行缩放
                                scaled_img = GPUScaler.scale_qimage(
                                    orig_img,
                                    target_size,
                                    target_size,
                                    keep_aspect=True,
                                    fast_mode=True
                                )
                                if scaled_img is not None and not scaled_img.isNull():
                                    image = scaled_img
                                    attempts = 2
                        else:
                            # 使用Qt的setScaledSize进行缩放
                            orig_size = reader.size()
                            if orig_size.isValid() and orig_size.width() > 0 and orig_size.height() > 0:
                                orig_w = orig_size.width()
                                orig_h = orig_size.height()
                                if target_size > 0:
                                    if orig_w >= orig_h:
                                        scaled_w = int(target_size)
                                        scaled_h = int(max(1, round(orig_h * target_size / orig_w)))
                                    else:
                                        scaled_h = int(target_size)
                                        scaled_w = int(max(1, round(orig_w * target_size / orig_h)))
                                    reader.setScaledSize(QSize(scaled_w, scaled_h))
                            img = reader.read()
                            if img is not None and not img.isNull():
                                image = img
                                attempts = 2
            
            # 第三次尝试：对于RAW文件，提取内置缩略图
            if image is None and ext in raw_exts:
                raw_thumb = load_image(self.path)
                if raw_thumb is not None:
                    raw_thumb = cv2.cvtColor(raw_thumb, cv2.COLOR_BGR2RGB)
                    h, w, _ = raw_thumb.shape
                    image = QImage(raw_thumb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
                    attempts = 3
            
            # 最后一次尝试：直接读取文件数据（最慢但最兼容）
            if image is None:
                with open(self.path, "rb") as f:
                    data = f.read()
                image = QImage.fromData(data)
                if image is not None and not image.isNull() and target_size > 0 and (image.width() > target_size or image.height() > target_size):
                    image = image.scaled(
                        target_size,
                        target_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation
                    )
                    attempts = 4

            if image is not None and not image.isNull():
                # 使用平滑缩放模式，减少锯齿
                output_image = image

                # 计算目标尺寸
                if self.size and not disable_scaling:
                    w, h = self.size if isinstance(self.size, (tuple, list)) else (self.size, self.size)
                    if w > 0 and h > 0 and image.width() > 0 and image.height() > 0:
                        # 如果图片比目标大，进行缩放
                        if image.width() > w or image.height() > h:
                            output_image = image.scaled(
                                w,
                                h,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            )

                if not output_image.isNull():
                    # 保存到缓存（使用原始目标尺寸，不是显示尺寸）
                    if target_size > 0:
                        cache_image = output_image
                        if output_image.width() > target_size or output_image.height() > target_size:
                            cache_image = output_image.scaled(
                                target_size,
                                target_size,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            )
                        self.cache_manager.put(self.path, cache_image, self.cache_type)

                    # 确保图片格式为 ARGB32_Premultiplied，这是 QPixmap.fromImage 最快的格式
                    if output_image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                        output_image = output_image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

                    # 保存到磁盘缓存
                    if self.disk_cache is not None:
                        base_px = int(getattr(self.cache_manager, "cache_thumbnail_size", 0) or 0)
                        self.disk_cache.put(self.path, output_image, self.size, cache_type=self.cache_type, scale_quality=scale_quality, base_px=base_px)

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
            # 统一异常处理：记录日志并通知结果
            try:
                LogManager.instance().warning(f"加载缩略图失败: {self.path}: {e}")
            except Exception:
                pass
            if self.result_emitter:
                elapsed_ms = (time.time() - start_time) * 1000.0
                self.result_emitter(self.path, None, int(self.request_id or 0), elapsed_ms, from_cache, attempts)

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
    
    def __init__(self, cache_manager, task_type=TaskType.DEFAULT, thread_count=None):
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
        # 如果提供了线程数，直接使用；否则从TaskScheduler获取
        if thread_count is not None and thread_count > 0:
            self._default_thread_count = int(thread_count)
        else:
            scheduler = TaskScheduler.instance()
            self._default_thread_count = scheduler.get_thread_count(task_type)
        # 限制线程数：增加线程数以支持预加载任务并行执行
        # 可见区域任务和预加载任务可以并行执行
        self._max_thread_count = min(self._default_thread_count, 6)
        self.thread_pool.setMaxThreadCount(self._max_thread_count)
        
        self.signals = ThumbnailLoaderSignals()
        
        # 使用双队列系统：高优先级队列和普通队列
        self._high_priority_queue = queue.PriorityQueue()  # 优先级 <= 0
        self._normal_queue = queue.PriorityQueue()         # 优先级 > 0
        self._queue_lock = Lock()
        self._seq = 0
        self._front_seq = 0
        self._dispatch_counter = 0  # 调度计数器，用于轮询高优先级和普通队列
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
        # 使用16ms间隔（约60fps），平衡UI更新频率和性能
        # 过高的频率（如8ms）会导致主线程频繁中断，反而降低整体性能
        self._result_timer.setInterval(16)
        self._result_timer.timeout.connect(self._process_result_queue)
        self._result_timer.start()
        
        # 启动调度器线程
        self._dispatcher = Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher.start()
        
    def set_max_thread_count(self, count):
        """设置最大线程数"""
        if count > 0:
            # 增加最大线程数上限以支持更快的缩略图加载
            self._max_thread_count = min(int(count), 6)
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
        """处理结果队列，在主线程中异步发射信号 - 批量优化版

        优化点：
        1. 增加每批处理数量到8个，提高吞吐量
        2. 移除异常处理，依赖最外层保护
        3. 使用列表代替字典，减少哈希开销
        4. 批量发射信号，减少函数调用次数

        说明：
        - 批量处理可以减少主线程被中断的次数
        - 合并信号发射可以降低Qt信号系统的开销
        """
        max_per_frame = 8  # 增加批量大小
        processed = 0

        # 使用列表存储结果，避免字典的哈希开销
        results_to_emit = []

        while processed < max_per_frame:
            result = None
            with self._result_queue_lock:
                if self._result_queue:
                    result = self._result_queue.popleft()

            if result is None:
                break

            # 直接处理结果，不使用try-except
            result_type = result[0]
            path = result[1]
            image = result[2]

            if result_type == 'loaded':
                results_to_emit.append(('loaded', path, image))
            elif result_type == 'metrics':
                # metrics包含更多信息
                request_id = result[3]
                elapsed_ms = result[4]
                from_cache = result[5]
                attempts = result[6]
                results_to_emit.append(('metrics', path, image, request_id, elapsed_ms, from_cache, attempts))

            processed += 1

        # 批量发射信号
        for item in results_to_emit:
            if item[0] == 'loaded':
                # item = ('loaded', path, image)
                self.signals.loaded.emit(item[1], item[2])
            elif item[0] == 'metrics':
                # item = ('metrics', path, image, request_id, elapsed_ms, from_cache, attempts)
                self.signals.loaded.emit(item[1], item[2])  # 同时发射loaded信号
                self.signals.loaded_metrics.emit(item[1], item[2], item[3], item[4], item[5], item[6])

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

        # 第一步：立即处理缓存命中的图片（不走线程池，直接返回）
        cache_hits = []
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

            # 检查内存缓存
            cached_image = None
            try:
                cached_image = self.cache_manager.get_image(path)
            except Exception:
                pass

            if cached_image and not cached_image.isNull():
                # 检查尺寸是否足够
                size = current_display_size
                if size:
                    try:
                        w, h = size if isinstance(size, (tuple, list)) else (size, size)
                        req_max = max(int(w or 0), int(h or 0))
                        cached_max = max(cached_image.width(), cached_image.height())
                        # 如果缓存图片尺寸足够，直接返回
                        if cached_max >= req_max * 0.9:
                            cache_hits.append((path, cached_image))
                            continue
                    except Exception:
                        pass
                else:
                    # 没有指定尺寸，直接使用缓存
                    cache_hits.append((path, cached_image))
                    continue

            # 缓存未命中或尺寸不够，加入任务队列
            tasks_to_enqueue.append((priority, path, current_display_size, cache_type, request_id, front))

        # 立即返回缓存命中的结果（不走线程池，直接发射信号）
        for path, image in cache_hits:
            try:
                # 确保格式正确
                if image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                # 直接发射信号，不走线程池
                self.signals.loaded.emit(path, image)
                self.signals.loaded_metrics.emit(path, image, int(request_id or 0), 0.0, True, 0)
            except Exception:
                pass

        # 第二步：将未命中的任务加入队列，走线程池处理
        if not tasks_to_enqueue:
            return

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
            
            # 限制调度：生成缩略图时限制每帧分发任务数，避免UI卡顿
            tasks_per_frame = 0
            max_tasks_per_frame = 6  # 增加每帧分发任务数，支持更多并行加载

            # 优化调度策略：确保预加载任务和可见区域任务都能及时执行
            # 每帧先处理高优先级任务，然后处理普通队列任务
            # 这样预加载任务不会被完全阻塞

            while tasks_per_frame < max_tasks_per_frame:
                task = None
                # 优先从高优先级队列获取（可见缩略图）
                try:
                    task = self._high_priority_queue.get_nowait()
                except queue.Empty:
                    # 高优先级队列为空，尝试普通队列（预加载任务）
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
                runnable = ThumbnailRunnable(path, size, self.cache_manager, self.disk_cache, self._on_thumbnail_result, cache_type, request_id, priority, self._request_id_ref)

                # 包装任务以跟踪运行状态
                wrapped_runnable = self._wrap_runnable(runnable)
                self.thread_pool.start(wrapped_runnable)

                tasks_per_frame += 1

                # 让出时间片，避免阻塞UI
                time.sleep(0.001)

            # 空转等待，降低CPU占用
            if tasks_per_frame == 0:
                time.sleep(0.01)  # 10ms，平衡响应性和CPU占用

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
