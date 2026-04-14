import os
import threading
import time
from collections import OrderedDict
from queue import Queue, Empty
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtGui import QImage
from PyQt6.QtCore import Qt

from utils.file.file import load_image
from utils.setting.settings_manager import SettingsManager


class BigImageCacheManager:
    _instances = {}
    _instances_lock = threading.Lock()

    @classmethod
    def instance(cls, context: str = "library"):
        ctx = str(context or "library").strip().lower() or "library"
        with cls._instances_lock:
            inst = cls._instances.get(ctx)
            if inst is None:
                inst = BigImageCacheManager(context=ctx)
                cls._instances[ctx] = inst
            return inst

    def __init__(self, context: str = "library"):
        self.context = str(context or "library").strip().lower() or "library"
        self._lock = threading.Lock()
        self._items: "OrderedDict[str, QImage]" = OrderedDict()
        self._pending = set()
        self._queue: "Queue[tuple[int, str]]" = Queue()
        self._generation = 1
        self._max_items_override = None
        self._max_long_edge_override = None
        self._stop_evt = threading.Event()
        self._worker = threading.Thread(target=self._run, name=f"BigImageCache-{self.context}", daemon=True)
        self._worker.start()

    def _max_items(self) -> int:
        try:
            ov = getattr(self, "_max_items_override", None)
        except Exception:
            ov = None
        if ov is not None:
            try:
                v = int(ov)
                return max(1, min(300, v))
            except Exception:
                pass
        try:
            sm = SettingsManager.instance()
            v = int(sm.get("performance/big_image_cache_max_items", 100))
        except Exception:
            v = 100
        return max(10, min(300, v))

    def set_max_items_override(self, max_items: Optional[int]):
        if max_items is None:
            self._max_items_override = None
            try:
                with self._lock:
                    self._evict_if_needed()
            except Exception:
                pass
            return
        try:
            v = int(max_items)
        except Exception:
            return
        if v <= 0:
            self._max_items_override = None
            return
        self._max_items_override = max(1, min(300, v))
        try:
            with self._lock:
                self._evict_if_needed()
        except Exception:
            pass

    def set_max_long_edge_override(self, max_long_edge: Optional[int]):
        if max_long_edge is None:
            self._max_long_edge_override = None
            return
        try:
            v = int(max_long_edge)
        except Exception:
            return
        if v <= 0:
            self._max_long_edge_override = None
            return
        self._max_long_edge_override = max(800, min(8192, v))

    def _max_long_edge(self) -> int:
        try:
            ov = getattr(self, "_max_long_edge_override", None)
        except Exception:
            ov = None
        if ov is not None:
            try:
                v = int(ov)
                return max(800, min(8192, v))
            except Exception:
                pass
        try:
            sm = SettingsManager.instance()
            v = int(sm.get("performance/big_image_cache_long_edge", 5120))
        except Exception:
            v = 5120
        return max(1600, min(8192, v))

    def clear(self):
        with self._lock:
            self._items.clear()
            self._pending.clear()
            self._generation += 1

    def get(self, image_path: str) -> Optional[QImage]:
        p = self._norm_path(image_path)
        if not p:
            return None
        with self._lock:
            img = self._items.get(p)
            if img is not None:
                try:
                    self._items.move_to_end(p, last=True)
                except Exception:
                    pass
            return img

    def put(self, image_path: str, qimg: QImage) -> bool:
        p = self._norm_path(image_path)
        if not p:
            return False
        if qimg is None or qimg.isNull():
            return False
        qimg2 = self._scale_qimage(qimg, self._max_long_edge())
        with self._lock:
            self._items[p] = qimg2
            try:
                self._items.move_to_end(p, last=True)
            except Exception:
                pass
            self._evict_if_needed()
        return True

    def preload(self, image_paths):
        if not image_paths:
            return
        gen = int(self._generation)
        to_add = []
        for p in (image_paths or []):
            npth = self._norm_path(p)
            if not npth:
                continue
            to_add.append(npth)
        if not to_add:
            return
        with self._lock:
            for p in to_add:
                if p in self._items or p in self._pending:
                    continue
                self._pending.add(p)
                try:
                    self._queue.put_nowait((gen, p))
                except Exception:
                    try:
                        self._pending.discard(p)
                    except Exception:
                        pass

    def _evict_if_needed(self):
        max_items = int(self._max_items())
        while len(self._items) > max_items:
            try:
                self._items.popitem(last=False)
            except Exception:
                break

    def _norm_path(self, p: str) -> str:
        if not p:
            return ""
        try:
            s = str(p).replace("/", os.sep)
        except Exception:
            return ""
        try:
            s = os.path.normpath(s)
            if os.name == "nt":
                s = os.path.normcase(s)
        except Exception:
            pass
        return s

    def _scale_qimage(self, qimg: QImage, max_long_edge: int) -> QImage:
        try:
            w = int(qimg.width())
            h = int(qimg.height())
        except Exception:
            return qimg
        if w <= 0 or h <= 0:
            return qimg
        long_edge = max(w, h)
        if long_edge <= int(max_long_edge):
            return qimg
        try:
            if w >= h:
                tw = int(max_long_edge)
                th = max(1, int(h * (tw / max(1, w))))
            else:
                th = int(max_long_edge)
                tw = max(1, int(w * (th / max(1, h))))
            return qimg.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        except Exception:
            return qimg

    def _decode_to_qimage(self, image_path: str) -> Optional[QImage]:
        try:
            img = load_image(image_path)
        except Exception:
            img = None
        if img is None:
            try:
                qimg = QImage(image_path)
                return qimg if qimg is not None and not qimg.isNull() else None
            except Exception:
                return None
        try:
            if isinstance(img, np.ndarray) and img.ndim == 3:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                rgb = np.ascontiguousarray(rgb)
                height, width, _ = rgb.shape
                bytes_per_line = int(3 * width)
                return QImage(rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
        except Exception:
            return None
        return None

    def _run(self):
        while not self._stop_evt.is_set():
            try:
                gen, p = self._queue.get(timeout=0.25)
            except Empty:
                continue
            if int(gen) != int(getattr(self, "_generation", 0) or 0):
                with self._lock:
                    self._pending.discard(p)
                continue
            qimg = None
            try:
                qimg = self._decode_to_qimage(p)
            except Exception:
                qimg = None
            if qimg is not None and not qimg.isNull():
                try:
                    self.put(p, qimg)
                except Exception:
                    pass
            with self._lock:
                self._pending.discard(p)
            try:
                time.sleep(0.001)
            except Exception:
                pass
