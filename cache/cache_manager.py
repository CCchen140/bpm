import os
import time
from collections import OrderedDict
from threading import Thread, Lock
import queue
from queue import PriorityQueue
import pickle
import concurrent.futures
from utils.system.task_scheduler import TaskScheduler, TaskType
from utils.system.gpu_utils import GPUScaler
from PyQt6.QtCore import Qt, QBuffer, QIODevice, QByteArray
from PyQt6.QtGui import QPixmap, QImage
from utils.file.file import load_image
from utils.setting.settings_manager import SettingsManager
from ui.utils.status_manager import StatusManager
from utils.log_manager import LogManager

# 延迟导入 cv2 和 numpy，避免启动时加载重型依赖
_cv2 = None
_numpy = None

def _get_cv2():
    """延迟加载 cv2 模块"""
    global _cv2
    if _cv2 is None:
        import cv2
        _cv2 = cv2
    return _cv2

def _get_numpy():
    """延迟加载 numpy 模块"""
    global _numpy
    if _numpy is None:
        import numpy as np
        _numpy = np
    return _numpy

# 图片缓存管理器（LRU 缓存）
class ImageCacheManager:
    """图片缓存管理器，使用 LRU（最近最少使用）策略"""
    _instance = None
    _instances = {}
    _lock = Lock()
    
    # 优先级常量 (数值越小优先级越高)
    PRIORITY_FAV = 1
    PRIORITY_SPECIES = 2
    PRIORITY_GENERAL = 3
    
    # 最大重试次数
    MAX_RETRIES = 3

    def __new__(cls, context="default", enable_preload=True):
        """单例/多例模式"""
        if context is None:
            context = "default"

        with cls._lock:
            if context not in cls._instances:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instances[context] = instance
                
                # 兼容旧的 _instance 访问
                if context == "default":
                    cls._instance = instance
                    
        return cls._instances[context]

    @classmethod
    def instance(cls):
        """获取单例实例"""
        return cls(context="default")

    def __init__(self, context="default", enable_preload=True):
        if getattr(self, '_initialized', False):
            # 即使已经初始化，也要确保新属性存在（针对热更新或旧实例）
            if not hasattr(self, '_preload_total'):
                self._preload_total = 0
                self._preload_current = 0
                self._preload_errors = 0
            return
        self._initialized = True
        self.context = context
        self.settings_manager = SettingsManager()
        self.persistent_cache_enabled = not bool(self.settings_manager.get("performance/disable_thumbnail_persistence", False))
        if self.context == "import":
            # 导入页面使用更大的默认缓存（2000），因为通常需要浏览大量图片
            self.max_cache_size = int(self.settings_manager.get("import/cache_size", 2000))
            import_size = int(self.settings_manager.get("import/thumbnail_cache_size", 300))
            legacy_size = int(self.settings_manager.get("performance/thumbnail_cache_size", 300))
            if import_size == 300 and legacy_size != 300:
                import_size = legacy_size
            self.cache_thumbnail_size = import_size
        else:
            self.max_cache_size = int(self.settings_manager.get("performance/thumbnail_cache_count", 800))
            library_size = int(self.settings_manager.get("library/thumbnail_cache_size", 300))
            legacy_size = int(self.settings_manager.get("performance/thumbnail_cache_size", 300))
            if library_size == 300 and legacy_size != 300:
                library_size = legacy_size
            self.cache_thumbnail_size = library_size
        
        # 独立的缓存池
        self._cache = OrderedDict()         # 通用缓存 (原有)
        self._species_cache = OrderedDict() # 物种缓存 (容量200)
        self._fav_cache = OrderedDict()     # 收藏缓存 (容量200)
        
        self.species_cache_size = 200
        self.fav_cache_size = 200
        
        # 持久化缓存文件路径
        if context == "import":
            self.persistent_cache_file = os.path.join('cache', 'thumbnails', 'import_thumbnail_cache.pkl')
            # 导入页面缓存限制可能不同，但在初始化时先用默认值，用户逻辑里再控制保存数量
        else:
            self.persistent_cache_file = os.path.join('cache', 'thumbnails', 'thumbnail_cache.pkl')
        
        self._lock = Lock()
        
        # 使用 Queue 实现线程安全的任务队列
        self._task_queue = queue.Queue()
        self._running = True
        self._is_saving = False
        
        # 预加载统计 (先初始化变量)
        self._preload_total = 0
        self._preload_current = 0
        self._preload_errors = 0
        self._preload_task_id = None # 预加载任务ID
        
        # 启动常驻后台线程 (使用多个线程加速预加载)
        self._worker_threads = []
        if enable_preload:
            for i in range(4): # 使用 4 个线程
                t = Thread(target=self._worker_loop, daemon=True, name=f"CacheWorker-{i}")
                t.start()
                self._worker_threads.append(t)

    def _normalize_path(self, path):
        if not path:
            return path
        try:
            p = str(path).replace("/", os.sep)
            p = os.path.normpath(p)
            if os.name == "nt":
                p = os.path.normcase(p)
            return p
        except Exception:
            return path

    def _safe_pickle_load(self, file_path):
        if not file_path:
            return {}
        try:
            if not os.path.exists(file_path):
                return {}
        except Exception:
            return {}
        try:
            if os.path.getsize(file_path) <= 0:
                return {}
        except Exception:
            pass

        try:
            with open(file_path, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, dict):
                return data
            return {}
        except (EOFError, pickle.UnpicklingError):
            try:
                os.remove(file_path)
            except Exception:
                pass
            return {}
        except Exception:
            return {}

    def _atomic_pickle_dump(self, file_path, data):
        if not file_path:
            return False
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
        except Exception:
            pass

        tmp_path = f"{file_path}.tmp"
        try:
            with open(tmp_path, "wb") as f:
                pickle.dump(data, f)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, file_path)
            return True
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False

    def update_settings(self):
        """更新设置"""
        self.persistent_cache_enabled = not bool(self.settings_manager.get("performance/disable_thumbnail_persistence", False))
        if self.context == "import":
            # 导入页面使用更大的默认缓存（2000），因为通常需要浏览大量图片
            self.max_cache_size = int(self.settings_manager.get("import/cache_size", 2000))
            import_size = int(self.settings_manager.get("import/thumbnail_cache_size", 300))
            legacy_size = int(self.settings_manager.get("performance/thumbnail_cache_size", 300))
            if import_size == 300 and legacy_size != 300:
                import_size = legacy_size
            self.cache_thumbnail_size = import_size
        else:
            self.max_cache_size = int(self.settings_manager.get("performance/thumbnail_cache_count", 800))
            library_size = int(self.settings_manager.get("library/thumbnail_cache_size", 300))
            legacy_size = int(self.settings_manager.get("performance/thumbnail_cache_size", 300))
            if library_size == 300 and legacy_size != 300:
                library_size = legacy_size
            self.cache_thumbnail_size = library_size
        # 如果缓存超过新限制，进行清理 (仅清理通用缓存)
        with self._lock:
            while len(self._cache) > self.max_cache_size:
                self._cache.popitem(last=False)

    def get_scale_quality(self):
        try:
            value = str(self.settings_manager.get("library/thumbnail_scale_quality", "high")).lower()
        except Exception:
            value = "high"
        if value not in ["low", "high"]:
            try:
                value = str(self.settings_manager.get("performance/thumbnail_scale_quality", "high")).lower()
            except Exception:
                value = "high"
        return "high" if value == "high" else "low"

    def _parse_cache_entry(self, entry):
        if isinstance(entry, dict):
            return (
                entry.get("data"),
                entry.get("width"),
                entry.get("height"),
                entry.get("size"),
                entry.get("quality"),
            )
        return entry, None, None, None, None

    def _build_cache_entry(self, data, width, height, size, quality):
        return {"data": data, "width": width, "height": height, "size": size, "quality": quality}

    def get(self, path):
        """获取缓存的图片，如果存在则移到最近使用位置
        Args:
            path: 图片路径
        Returns:
            QPixmap 或 None
        """
        t0 = time.perf_counter()
        path = self._normalize_path(path)
        cached_obj = None
        
        with self._lock:
            # 按顺序检查: 物种 -> 收藏 -> 通用
            
            # 1. 检查物种缓存
            if path in self._species_cache:
                self._species_cache.move_to_end(path)
                cached_obj = self._species_cache[path]
            # 2. 检查收藏缓存
            elif path in self._fav_cache:
                self._fav_cache.move_to_end(path)
                cached_obj = self._fav_cache[path]
            # 3. 检查通用缓存
            elif path in self._cache:
                self._cache.move_to_end(path)
                cached_obj = self._cache[path]
        
        t1 = time.perf_counter()
        
        if cached_obj is None:
            return None
            
        # 在锁外进行转换，避免阻塞其他线程
        if isinstance(cached_obj, QImage):
            res = QPixmap.fromImage(cached_obj)
            t2 = time.perf_counter()
            if t2 - t0 > 0.005:
                try:
                    LogManager.instance().debug(
                        f"[Cache] get slow: {t2-t0:.4f}s (lock: {t1-t0:.4f}s) for {os.path.basename(path)}"
                    )
                except Exception:
                    pass
            return res
        return cached_obj

    def get_image(self, path):
        """获取缓存的 QImage 对象（线程安全，用于后台线程）"""
        path = self._normalize_path(path)
        with self._lock:
            # 同样按顺序检查
            for cache in [self._species_cache, self._fav_cache, self._cache]:
                if path in cache:
                    cache.move_to_end(path)
                    cached_obj = cache[path]
                    if isinstance(cached_obj, QPixmap):
                        return None
                    return cached_obj
        return None

    def has_cache(self, path):
        path = self._normalize_path(path)
        with self._lock:
            if path in self._species_cache:
                return True
            if path in self._fav_cache:
                return True
            if path in self._cache:
                return True
        return False

    @staticmethod
    def _encode_image_static(path, qimg):
        try:
            if qimg.isNull():
                return path, None
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            qimg.save(buf, "PNG")
            return path, ba.data()
        except Exception:
            return path, None

    def save_persistent_cache(self, image_files=None, limit=1000, progress_callback=None):
        """保存缩略图到本地文件 (多线程并行编码优化)
        Args:
            image_files: 图片信息列表 (可选)。如果为 None，则保存内存中所有缓存。
            limit: 最大保存数量
            progress_callback: 进度回调函数
        """
        if not getattr(self, "persistent_cache_enabled", False):
            return
        if not image_files:
            with self._lock:
                if not self._cache and not self._species_cache and not self._fav_cache:
                    return
        
        task_id = StatusManager.instance().start_task("正在保存缓存...")
        
        # 使用 TaskScheduler 获取线程数
        thread_count = TaskScheduler.instance().get_thread_count(TaskType.CACHE_SAVER)
        
        try:
            # 1. 加载现有缓存
            cache_data = self._safe_pickle_load(self.persistent_cache_file)
            os.makedirs(os.path.dirname(self.persistent_cache_file), exist_ok=True)
            
            # 2. 收集待保存项
            items_to_process = []
            meta_map = {}
            current_quality = self.get_scale_quality()
            current_target_size = int(self.cache_thumbnail_size or 0)
            
            # 收集路径
            paths_to_check = []
            if image_files:
                paths_to_check = [f['path'] for f in image_files]
            else:
                with self._lock:
                    # 优先顺序: Species > Fav > General
                    paths_to_check.extend(list(self._species_cache.keys()))
                    paths_to_check.extend(list(self._fav_cache.keys()))
                    paths_to_check.extend(list(self._cache.keys()))
            
            added_count = 0
            seen_paths = set()
            
            # 准备数据 (在主线程/调用线程中获取 QImage，避免多线程访问 QPixmap)
            with self._lock:
                for path in paths_to_check:
                    if added_count >= limit:
                        break
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    
                    norm_path = self._normalize_path(path)
                    
                    if norm_path in cache_data and image_files is None:
                        entry = cache_data.get(norm_path)
                        data, width, height, size, quality = self._parse_cache_entry(entry)
                        size_match = False
                        if size is not None and current_target_size > 0:
                            size_match = int(size) == current_target_size
                        elif width and height and current_target_size > 0:
                            size_match = max(int(width), int(height)) == current_target_size
                        elif data and current_target_size > 0:
                            existing_qimg = QImage()
                            existing_qimg.loadFromData(data, "PNG")
                            if not existing_qimg.isNull():
                                size_match = max(existing_qimg.width(), existing_qimg.height()) == current_target_size
                        if size_match and quality == current_quality:
                            continue
                        
                    obj = None
                    if path in self._species_cache: obj = self._species_cache[path]
                    elif path in self._fav_cache: obj = self._fav_cache[path]
                    elif path in self._cache: obj = self._cache[path]
                    
                    if obj:
                        qimg = obj
                        if isinstance(obj, QPixmap):
                            qimg = obj.toImage()
                        
                        if isinstance(qimg, QImage) and not qimg.isNull():
                            try:
                                if current_target_size > 0:
                                    m = max(int(qimg.width() or 0), int(qimg.height() or 0))
                                    if m > 0 and m < int(current_target_size * 0.9):
                                        continue
                            except Exception:
                                pass
                            items_to_process.append((norm_path, qimg.copy()))
                            meta_map[norm_path] = (int(qimg.width()), int(qimg.height()))
                            added_count += 1

            # 3. 并行编码
            if items_to_process:
                with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
                    future_to_path = {
                        executor.submit(self._encode_image_static, path, img): path 
                        for path, img in items_to_process
                    }
                    
                    completed = 0
                    total = len(items_to_process)
                    
                    for future in concurrent.futures.as_completed(future_to_path):
                        path, data = future.result()
                        if data:
                            width, height = meta_map.get(path, (None, None))
                            cache_data[path] = self._build_cache_entry(data, width, height, current_target_size, current_quality)
                        
                        completed += 1
                        if progress_callback:
                            try:
                                progress_callback(completed, total)
                            except:
                                pass

            # 4. 写入文件
            self._atomic_pickle_dump(self.persistent_cache_file, cache_data)
            
        except Exception as e:
            try:
                LogManager.instance().warning(f"[Cache] Failed to save persistent cache: {e}")
            except Exception:
                pass
        finally:
            StatusManager.instance().finish_task(task_id)

    def load_persistent_cache(self):
        """从本地文件加载缓存"""
        if not getattr(self, "persistent_cache_enabled", False):
            return
        if not os.path.exists(self.persistent_cache_file):
            return
            
        try:
            # 耗时操作：读取和反序列化文件 (无需锁)
            cache_data = self._safe_pickle_load(self.persistent_cache_file)
                
            loaded_count = 0
            # 优化：不一次性锁住整个循环，而是分批处理或单次处理
            # 考虑到 decode QImage 也需要时间，应该先 decode 再加锁存入
            
            for path, entry in cache_data.items():
                try:
                    data, _, _, _, _ = self._parse_cache_entry(entry)
                    if not data:
                        continue
                    img = QImage()
                    img.loadFromData(data, "PNG")
                    if img.isNull():
                        continue

                    norm_path = self._normalize_path(path)
                    
                    # 存入缓存 (需要锁，且速度很快)
                    with self._lock:
                        # 检查是否已存在于任意缓存中
                        if norm_path in self._cache or norm_path in self._species_cache or norm_path in self._fav_cache:
                            continue
                            
                        # 从持久化缓存加载的图片，先放入通用缓存
                        if len(self._cache) >= self.max_cache_size:
                                self._cache.popitem(last=False)
                        self._cache[norm_path] = img
                        loaded_count += 1
                    
                except Exception:
                    continue
                    
        except Exception as e:
            try:
                LogManager.instance().warning(f"[Cache] Failed to load persistent cache: {e}")
            except Exception:
                pass
            # 出错则删除文件
            try:
                os.remove(self.persistent_cache_file)
            except:
                pass

    def clear_persistent_cache(self):
        """清除本地缓存文件"""
        if os.path.exists(self.persistent_cache_file):
            try:
                os.remove(self.persistent_cache_file)
                return True
            except Exception as e:
                try:
                    LogManager.instance().warning(f"[Cache] Failed to remove persistent cache file: {e}")
                except Exception:
                    pass
                return False
        return True

    def rebuild_persistent_cache(self, paths, limit=1000, progress_callback=None):
        if not getattr(self, "persistent_cache_enabled", False):
            return 0
        if limit is None:
            limit = 1000
        try:
            limit = int(limit)
        except Exception:
            limit = 1000
        if limit < 0:
            limit = 0

        task_id = StatusManager.instance().start_task("正在重建缩略图缓存...")
        try:
            try:
                os.makedirs(os.path.dirname(self.persistent_cache_file), exist_ok=True)
            except Exception:
                pass

            try:
                self.clear_persistent_cache()
            except Exception:
                pass

            cache_data = {}
            try:
                total = min(len(paths or []), limit)
            except Exception:
                total = 0

            for idx in range(total):
                p = paths[idx]
                if progress_callback:
                    try:
                        if idx == 0 or idx == total - 1 or ((idx + 1) % 10 == 0):
                            progress_callback(idx + 1, total)
                    except Exception:
                        pass

                try:
                    if not p or not os.path.exists(p):
                        continue
                except Exception:
                    continue

                qimg = None
                try:
                    cv_img = load_image(p)
                    if cv_img is not None:
                        cv2 = _get_cv2()
                        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                        height, width, channel = cv_img.shape
                        bytes_per_line = 3 * width
                        qimg = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
                except Exception:
                    qimg = None

                if qimg is None or qimg.isNull():
                    try:
                        qimg = QImage(p)
                    except Exception:
                        qimg = None

                if qimg is None or qimg.isNull():
                    continue

                try:
                    qimg = qimg.scaled(
                        self.cache_thumbnail_size,
                        self.cache_thumbnail_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                except Exception:
                    pass

                try:
                    ba = QByteArray()
                    buf = QBuffer(ba)
                    buf.open(QIODevice.OpenModeFlag.WriteOnly)
                    qimg.save(buf, "PNG")
                    cache_data[self._normalize_path(p)] = ba.data()
                except Exception:
                    pass

            try:
                ok = self._atomic_pickle_dump(self.persistent_cache_file, cache_data)
                if not ok:
                    raise RuntimeError("atomic write failed")
            except Exception as e:
                try:
                    LogManager.instance().warning(f"[Cache] Failed to rebuild persistent cache: {e}")
                except Exception:
                    pass
                return 0

            return len(cache_data)
        finally:
            StatusManager.instance().finish_task(task_id)

    def put(self, path, image, cache_type='general'):
        """添加图片到缓存
        Args:
            path: 图片路径
            image: 图片对象
            cache_type: 缓存类型 ('general', 'species', 'fav')
        """
        path = self._normalize_path(path)
        with self._lock:
            # 1. 检查是否已存在于任意缓存中，如果是，则更新该缓存并移到末尾
            if path in self._species_cache:
                self._species_cache.move_to_end(path)
                self._species_cache[path] = image
                return
            
            if path in self._fav_cache:
                self._fav_cache.move_to_end(path)
                self._fav_cache[path] = image
                return
                
            if path in self._cache:
                self._cache.move_to_end(path)
                self._cache[path] = image
                return

            # 2. 如果不存在，则根据类型存入对应缓存
            if cache_type == 'species':
                target_cache = self._species_cache
                max_size = self.species_cache_size
            elif cache_type == 'fav':
                target_cache = self._fav_cache
                max_size = self.fav_cache_size
            else: # general
                target_cache = self._cache
                max_size = self.max_cache_size
            
            # 检查容量并清理
            if len(target_cache) >= max_size:
                target_cache.popitem(last=False)
            
            target_cache[path] = image

    def preload(self, paths, cache_type='general', priority=None):
        """预加载图片（异步）
        Args:
            paths: 图片路径列表
            cache_type: 缓存类型 ('general', 'species', 'fav')
            priority: 优先级 (可选，默认根据 cache_type 决定)
        """
        if not paths:
            return

        # 如果没有启用预加载线程，不启动任务
        if not self._worker_threads:
            return

        # 确定优先级
        if priority is None:
            if cache_type == 'fav':
                priority = self.PRIORITY_FAV
            elif cache_type == 'species':
                priority = self.PRIORITY_SPECIES
            else:
                priority = self.PRIORITY_GENERAL

        with self._lock:
            self._preload_total += len(paths)
            if self._preload_task_id is None:
                self._preload_task_id = StatusManager.instance().start_task("正在加载缓存...")

        for path in paths:
            # 放入优先级队列: (priority, path, cache_type, retry_count)
            self._task_queue.put((priority, self._normalize_path(path), cache_type, 0))

    def get_preload_status(self):
        """获取预加载状态
        Returns:
            dict: {
                'total': int,
                'current': int,
                'errors': int,
                'queue_size': int,
                'is_idle': bool
            }
        """
        return {
            'total': self._preload_total,
            'current': self._preload_current,
            'errors': self._preload_errors,
            'queue_size': self._task_queue.qsize(),
            'is_idle': self._task_queue.empty()
        }

    def stop_preload(self):
        """停止所有待处理的预加载任务"""
        # PriorityQueue 没有 clear 方法，只能循环取出
        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
            except queue.Empty:
                break

    def _worker_loop(self):
        """常驻后台工作线程"""
        while self._running:
            try:
                # 从队列获取任务
                item = self._task_queue.get(timeout=1.0)
                
                # 解析任务参数
                priority = 3
                retry_count = 0
                
                if isinstance(item, tuple):
                    if len(item) == 4:
                        priority, path, cache_type, retry_count = item
                    elif len(item) == 2:
                        path, cache_type = item
                    else:
                        # 未知格式，跳过
                        self._task_queue.task_done()
                        continue
                else:
                    path, cache_type = item, 'general'
                    
                with self._lock:
                    self._preload_current += 1
            except queue.Empty:
                continue
                
            try:
                # 再次检查是否已缓存（双重检查）
                if self.get(path) is not None:
                    continue
                
                # 加载图片
                if os.path.exists(path):
                    # 使用智能加载函数 (支持 RAW 缩略图提取)
                    cv_img = load_image(path)
                    
                    if cv_img is not None:
                        # OpenCV BGR -> QImage RGB
                        # 注意：cv_img 是 numpy array
                        cv2 = _get_cv2()
                        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                        height, width, channel = cv_img.shape
                        bytes_per_line = 3 * width
                        # 必须 copy()，因为 QImage 默认只引用数据，如果不 copy，cv_img 被回收后会导致 crash
                        image = QImage(cv_img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
                    else:
                        # 尝试直接加载（兜底）
                        image = QImage(path)

                    if not image.isNull():
                        target_size = int(self.cache_thumbnail_size or 0)
                        disable_scaling = False
                        try:
                            disable_scaling = bool(self.settings_manager.get("performance/thumbnail_disable_scaling", False))
                        except Exception:
                            disable_scaling = False
                        use_gpu_scaling = True
                        try:
                            use_gpu_scaling = bool(self.settings_manager.get("performance/use_gpu_scaling", True))
                        except Exception:
                            use_gpu_scaling = True
                        scale_quality = self.get_scale_quality()
                        transformation_mode = Qt.TransformationMode.SmoothTransformation if scale_quality == "high" else Qt.TransformationMode.FastTransformation
                        if disable_scaling:
                            transformation_mode = Qt.TransformationMode.FastTransformation
                        # 根据设置决定是否使用GPUScaler
                        if target_size > 0 and (image.width() > target_size or image.height() > target_size):
                            if use_gpu_scaling:
                                scaled = GPUScaler.scale_qimage(
                                    image,
                                    target_size,
                                    target_size,
                                    keep_aspect=True,
                                    fast_mode=transformation_mode == Qt.TransformationMode.FastTransformation
                                )
                                image = scaled if scaled is not None else image.scaled(
                                    target_size,
                                    target_size,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    transformation_mode
                                )
                            else:
                                image = image.scaled(
                                    target_size,
                                    target_size,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    transformation_mode
                                )
                        self.put(path, image, cache_type)
                        
                        # Log progress every 50 images
                        with self._lock:
                            if self._preload_current % 50 == 0:
                                try:
                                    LogManager.instance().debug(
                                        f"[Cache] Worker loaded {self._preload_current} images so far."
                                    )
                                except Exception:
                                    pass
            except Exception as e:
                try:
                    LogManager.instance().warning(f"[Cache] Failed to preload image: {path}, {e}")
                except Exception:
                    pass
            finally:
                self._task_queue.task_done()
                
                # 检查是否全部完成
                with self._lock:
                    if self._task_queue.empty() and self._preload_task_id is not None:
                        # 简单判断：如果队列空了就认为完成了。
                        # 严格来说应该判断所有线程是否空闲，但这里为了简化，假设队列空了就很快结束
                        StatusManager.instance().finish_task(self._preload_task_id)
                        self._preload_task_id = None

    def trigger_background_save(self):
        """触发后台保存（等待预加载完成后保存）"""
        return

    def _background_save_worker(self):
        """后台保存线程"""
        if not getattr(self, "persistent_cache_enabled", False):
            return
        import time
        # task_id = StatusManager.instance().start_task("正在写入缓存...")
        try:
            try:
                LogManager.instance().debug("[Cache] Background save scheduled. Waiting for preload queue to drain...")
            except Exception:
                pass
            
            # 等待队列为空（最多等待 60 秒）
            wait_count = 0
            while not self._task_queue.empty():
                time.sleep(1)
                wait_count += 1
                if wait_count > 60:
                    try:
                        LogManager.instance().debug("[Cache] Timeout waiting for preload queue. Saving anyway.")
                    except Exception:
                        pass
                    break
            
            # 额外等待几秒，确保正在处理的任务完成
            time.sleep(3)
            
            try:
                LogManager.instance().debug("[Cache] Starting background save...")
            except Exception:
                pass
            self.save_persistent_cache()
            try:
                LogManager.instance().debug("[Cache] Background save completed.")
            except Exception:
                pass
        except Exception as e:
            try:
                LogManager.instance().warning(f"[Cache] Background save failed: {e}")
            except Exception:
                pass
        finally:
            self._is_saving = False
            # StatusManager.instance().finish_task(task_id)

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._species_cache.clear()
            self._fav_cache.clear()
        # 同时清空队列
        with self._task_queue.mutex:
            self._task_queue.queue.clear()

    def rename_cache(self, old_path, new_path):
        """重命名缓存索引"""
        with self._lock:
            for cache in [self._species_cache, self._fav_cache, self._cache]:
                if old_path in cache:
                    image = cache.pop(old_path)
                    cache[new_path] = image
                    cache.move_to_end(new_path)
                    # 假设同一张图片只存在于一个缓存中，找到后即可停止
                    return

    def invalidate(self, path):
        """使指定路径的缓存失效"""
        path = self._normalize_path(path)
        with self._lock:
            for cache in [self._species_cache, self._fav_cache, self._cache]:
                if path in cache:
                    del cache[path]
        
        # 同时清除持久化缓存中的条目
        if os.path.exists(self.persistent_cache_file):
            try:
                # 注意：这里为了安全起见，读取整个文件、删除条目、再写回
                # 这是一个相对昂贵的操作，但 invalidate 通常是用户手动触发的低频操作
                updated = False
                with open(self.persistent_cache_file, 'rb') as f:
                    try:
                        cache_data = pickle.load(f)
                        if path in cache_data:
                            del cache_data[path]
                            updated = True
                    except Exception:
                        pass
                
                if updated:
                    with open(self.persistent_cache_file, 'wb') as f:
                        pickle.dump(cache_data, f)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"[Cache] Failed to remove from persistent cache: {e}")
                except Exception:
                    pass

    def invalidate_many(self, paths):
        if not paths:
            return
        norm_paths = []
        for p in paths:
            try:
                np = self._normalize_path(p)
            except Exception:
                np = ""
            if np:
                norm_paths.append(np)
        if not norm_paths:
            return
        with self._lock:
            for cache in [self._species_cache, self._fav_cache, self._cache]:
                for p in norm_paths:
                    if p in cache:
                        try:
                            del cache[p]
                        except Exception:
                            pass
        if not os.path.exists(self.persistent_cache_file):
            return
        try:
            with open(self.persistent_cache_file, "rb") as f:
                try:
                    cache_data = pickle.load(f)
                except Exception:
                    cache_data = None
            if not isinstance(cache_data, dict):
                return
            updated = False
            for p in norm_paths:
                if p in cache_data:
                    try:
                        del cache_data[p]
                        updated = True
                    except Exception:
                        pass
            if updated:
                with open(self.persistent_cache_file, "wb") as f:
                    pickle.dump(cache_data, f)
        except Exception as e:
            try:
                LogManager.instance().warning(f"[Cache] Failed to remove from persistent cache: {e}")
            except Exception:
                pass

    def invalidate_memory_only(self, path):
        """仅使内存缓存失效（不触碰持久化缓存文件）
        
        说明：
            - 用于“缩略图尺寸临时变更”等高频场景
            - 只删除内存里的 LRU 缓存项，避免 invalidate() 读写 pkl 带来的卡顿
        参数：
            path: 图片路径
        """
        path = self._normalize_path(path)
        with self._lock:
            for cache in [self._species_cache, self._fav_cache, self._cache]:
                if path in cache:
                    try:
                        del cache[path]
                    except Exception:
                        pass

    def get_cache_info(self):
        """获取缓存信息"""
        with self._lock:
            return {
                'general_cached': len(self._cache),
                'species_cached': len(self._species_cache),
                'fav_cached': len(self._fav_cache),
                'max_size': self.max_cache_size,
                'preload_queue': self._task_queue.qsize()
            }
