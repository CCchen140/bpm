from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, Qt, QSize
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

class ThumbnailRunnable(QRunnable):
    """缩略图加载任务"""
    def __init__(self, path, size, cache_manager, disk_cache, signals, cache_type='general', request_id=None, priority=3, request_id_ref=None):
        super().__init__()
        self.path = path
        self.size = size
        self.cache_manager = cache_manager
        self.disk_cache = disk_cache
        self.signals = signals
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
                                mode = transformation_mode
                                if ratio > 1.02:
                                    mode = Qt.TransformationMode.SmoothTransformation
                                if use_gpu_scaling:
                                    scaled = GPUScaler.scale_qimage(
                                        cached_image,
                                        w,
                                        h,
                                        keep_aspect=True,
                                        fast_mode=mode == Qt.TransformationMode.FastTransformation
                                    )
                                    output_image = scaled if scaled is not None else cached_image.scaled(
                                        w,
                                        h,
                                        Qt.AspectRatioMode.KeepAspectRatio,
                                        mode
                                    )
                                else:
                                    output_image = cached_image.scaled(
                                        w,
                                        h,
                                        Qt.AspectRatioMode.KeepAspectRatio,
                                        mode
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

                self.signals.loaded.emit(self.path, output_image)
                if hasattr(self.signals, "loaded_metrics"):
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.signals.loaded_metrics.emit(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
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
                self.signals.loaded.emit(self.path, output_image)
                if hasattr(self.signals, "loaded_metrics"):
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.signals.loaded_metrics.emit(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                return

            # 2. 加载图片
            if os.path.exists(self.path):
                ext = os.path.splitext(self.path)[1].upper()
                image = None
                if is_import_ctx:
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
                if target_size > 2048:
                    target_size = 2048
                if image is None or (hasattr(image, "isNull") and image.isNull()):
                    for attempt in range(3):
                        attempts = attempt + 1
                        if ext not in raw_exts and ext not in (".TIF", ".TIFF"):
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
                                        mode = transformation_mode
                                        if ratio > 1.02:
                                            mode = Qt.TransformationMode.SmoothTransformation
                                        if use_gpu_scaling:
                                            scaled = GPUScaler.scale_qimage(
                                                scaled_image,
                                                w,
                                                h,
                                                keep_aspect=True,
                                                fast_mode=mode == Qt.TransformationMode.FastTransformation
                                            )
                                            output_image = scaled if scaled is not None else scaled_image.scaled(
                                                w,
                                                h,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                mode
                                            )
                                        else:
                                            output_image = scaled_image.scaled(
                                                w,
                                                h,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                mode
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

                        self.signals.loaded.emit(self.path, output_image)
                        if hasattr(self.signals, "loaded_metrics"):
                            elapsed_ms = (time.time() - start_time) * 1000.0
                            self.signals.loaded_metrics.emit(self.path, output_image, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                    else:
                        self.signals.loaded.emit(self.path, None)
                        if hasattr(self.signals, "loaded_metrics"):
                            elapsed_ms = (time.time() - start_time) * 1000.0
                            self.signals.loaded_metrics.emit(self.path, None, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
                else:
                    self.signals.loaded.emit(self.path, None)
                    if hasattr(self.signals, "loaded_metrics"):
                        elapsed_ms = (time.time() - start_time) * 1000.0
                        self.signals.loaded_metrics.emit(self.path, None, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
        except Exception as e:
            try:
                LogManager.instance().warning(f"加载缩略图失败: {self.path}: {e}")
            except Exception:
                pass
            try:
                self.signals.loaded.emit(self.path, None)
                if hasattr(self.signals, "loaded_metrics"):
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    self.signals.loaded_metrics.emit(self.path, None, int(self.request_id or 0), elapsed_ms, from_cache, attempts)
            except Exception:
                pass

class ThumbnailLoaderSignals(QObject):
    """信号类，因为 QRunnable 不是 QObject"""
    loaded = pyqtSignal(str, object) # path, QImage
    loaded_metrics = pyqtSignal(str, object, int, float, bool, int)

class ThumbnailLoader(QObject):
    """缩略图多线程加载器"""
    def __init__(self, cache_manager, task_type=TaskType.DEFAULT):
        super().__init__()
        self.cache_manager = cache_manager
        scope = "import" if str(getattr(cache_manager, "context", "")).lower() == "import" else "library"
        self.disk_cache = ThumbnailDiskCache(cache_manager, scope=scope)
        try:
            self.disk_cache.cleanup_async(delay_sec=8.0)
        except Exception:
            pass
        self.thread_pool = QThreadPool()
        # 使用 TaskScheduler 动态分配线程数
        scheduler = TaskScheduler.instance()
        thread_count = scheduler.get_thread_count(task_type)
        self.thread_pool.setMaxThreadCount(thread_count)

        self.signals = ThumbnailLoaderSignals()
        self._task_queue = queue.PriorityQueue()
        self._queue_lock = Lock()
        self._seq = 0
        self._front_seq = 0
        self._running = True
        self._active_request_id = None
        self._request_id_ref = {"value": None}
        self._dispatcher = Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher.start()
        
    def set_max_thread_count(self, count):
        """设置最大线程数"""
        if count > 0:
            self.thread_pool.setMaxThreadCount(count)

    def shutdown(self):
        """停止加载器并清理资源"""
        self._running = False
        self.cancel_all()
        # 尝试等待正在运行的任务结束，避免退出崩溃
        # 设置较短的超时时间，保证"及时关闭"
        self.thread_pool.waitForDone(200)
        
    def load_thumbnails(self, paths, current_display_size, cache_type='general', request_id=None, default_priority=3):
        """提交加载任务"""
        if not paths:
            return
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
            self._enqueue_task(path, current_display_size, cache_type, priority, request_id, front)

    def _enqueue_task(self, path, size, cache_type, priority, request_id, front=False):
        with self._queue_lock:
            if front:
                self._front_seq -= 1
                seq = self._front_seq
            else:
                self._seq += 1
                seq = self._seq
        self._task_queue.put((int(priority), seq, path, size, cache_type, request_id))

    def _dispatch_loop(self):
        while self._running:
            try:
                priority, seq, path, size, cache_type, request_id = self._task_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._active_request_id is not None and request_id is not None and int(request_id) != int(self._active_request_id):
                continue
            task = ThumbnailRunnable(path, size, self.cache_manager, self.disk_cache, self.signals, cache_type, request_id, priority, self._request_id_ref)
            self.thread_pool.start(task)

    def cancel_all(self):
        """取消所有任务 (实际上只能等待正在运行的任务结束，但可以清除队列如果支持)"""
        # QThreadPool.clear() 在 Qt 5.9+ 可用
        try:
            self.thread_pool.clear()
        except:
            pass
        self.cancel_pending()

    def cancel_pending(self):
        """取消队列中等待的任务"""
        try:
            # 清空任务队列
            with self._task_queue.mutex:
                self._task_queue.queue.clear()
            
            # 清空线程池中等待的任务 (Qt 5.9+)
            if hasattr(self.thread_pool, "clear"):
                self.thread_pool.clear()
                
        except Exception as e:
            try:
                LogManager.instance().warning(f"取消缩略图待处理任务失败: {e}")
            except Exception:
                pass

    def set_active_request_id(self, request_id):
        self._active_request_id = request_id
        self._request_id_ref["value"] = request_id
