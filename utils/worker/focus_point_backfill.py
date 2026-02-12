from __future__ import annotations

import json
import os
import queue
import threading
from typing import Callable

from utils.exif.camera_af_point import get_camera_af_center_point_or_none
from utils.exif.exif_utils import EXIF_TAG, ExifHandleWorker
from utils.log_manager import LogManager
from utils.sql.data_base import BirdLibraryDB


class FocusPointBackfillService:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "FocusPointBackfillService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._q: "queue.Queue[tuple[list[str], str, Callable[[dict], None] | None]]" = queue.Queue()
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True, name="FocusPointBackfill")
        self._thread.start()

    def submit(self, file_paths, *, table_name: str, callback: Callable[[dict], None] | None = None):
        try:
            paths = [str(p) for p in (file_paths or []) if p]
        except Exception:
            paths = []
        if not paths:
            return
        accepted = []
        with self._inflight_lock:
            for p in paths:
                k = os.path.normcase(os.path.normpath(str(p)))
                if k in self._inflight:
                    continue
                self._inflight.add(k)
                accepted.append(p)
        if not accepted:
            return
        self._q.put((accepted, str(table_name or "bird_results"), callback))

    def _run(self):
        while True:
            paths, table_name, callback = self._q.get()
            try:
                self._process(paths, table_name, callback)
            except Exception:
                pass
            finally:
                try:
                    self._q.task_done()
                except Exception:
                    pass

    def _process(self, paths: list[str], table_name: str, callback: Callable[[dict], None] | None):
        db = BirdLibraryDB()
        exif_worker = ExifHandleWorker.get_instance()
        updates: dict[str, dict] = {}

        db_paths = []
        for p in paths:
            try:
                p_db = db._normalize_file_path_for_db(p)
            except Exception:
                p_db = p
            if p_db:
                db_paths.append(str(p_db))
        existing = db.get_results_by_paths(db_paths, table_name=table_name) if db_paths else {}
        existing_norm = {}
        try:
            for k, v in (existing or {}).items():
                nk = db._norm_path_key(k)
                if nk:
                    existing_norm[str(nk)] = v
        except Exception:
            existing_norm = {}

        for p in paths:
            try:
                if not os.path.exists(p):
                    continue
            except Exception:
                continue
            try:
                nk = db._norm_path_key(p)
            except Exception:
                nk = os.path.normcase(os.path.normpath(str(p)))
            rec = existing_norm.get(str(nk)) if nk else None
            fp0 = None
            if isinstance(rec, dict):
                fp0 = rec.get("focus_point")
            fp = get_camera_af_center_point_or_none(p)
            if not fp:
                continue
            try:
                if fp0:
                    old_xy = None
                    try:
                        old_xy = fp0
                        if isinstance(old_xy, str) and old_xy.strip():
                            old_xy = json.loads(old_xy)
                    except Exception:
                        old_xy = fp0
                    old_x = old_y = None
                    if isinstance(old_xy, dict):
                        try:
                            old_x = float(old_xy.get("x"))
                            old_y = float(old_xy.get("y"))
                        except Exception:
                            old_x = old_y = None
                    elif isinstance(old_xy, (list, tuple)) and len(old_xy) >= 2:
                        try:
                            old_x = float(old_xy[0])
                            old_y = float(old_xy[1])
                        except Exception:
                            old_x = old_y = None
                    new_x = new_y = None
                    if isinstance(fp, dict):
                        try:
                            new_x = float(fp.get("x"))
                            new_y = float(fp.get("y"))
                        except Exception:
                            new_x = new_y = None
                    elif isinstance(fp, (list, tuple)) and len(fp) >= 2:
                        try:
                            new_x = float(fp[0])
                            new_y = float(fp[1])
                        except Exception:
                            new_x = new_y = None
                    if old_x is not None and old_y is not None and new_x is not None and new_y is not None:
                        if abs(float(old_x) - float(new_x)) < 1e-6 and abs(float(old_y) - float(new_y)) < 1e-6:
                            continue
            except Exception:
                pass
            try:
                db.update_subject_info(p, focus_point=fp, table_name=table_name)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"[FocusPointBackfill] 写入数据库失败: {e}")
                except Exception:
                    pass
            updates[str(nk or p)] = {"focus_point": fp}

        if callable(callback) and updates:
            try:
                callback(updates)
            except Exception:
                pass

        with self._inflight_lock:
            for p in paths:
                try:
                    k = os.path.normcase(os.path.normpath(str(p)))
                except Exception:
                    k = str(p)
                try:
                    self._inflight.discard(k)
                except Exception:
                    pass
