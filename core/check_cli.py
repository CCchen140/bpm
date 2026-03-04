from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence
import os
import queue
import shutil
import threading
import time
import zipfile
import multiprocessing as mp
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import datetime

from utils.log_manager import LogManager


def _get_project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    except Exception:
        return os.getcwd()


_project_root = _get_project_root()


def _safe_write_text(path: str, text: str):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def focus_trace(msg: str):
    try:
        LogManager.instance().debug(f"[FocusDetectCLI] {msg}")
        return
    except Exception:
        pass
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except Exception:
        ts = ""
    line = f"[FocusDetectCLI] {ts} {msg}\n"
    _safe_write_text(os.path.join(_project_root, "cache", "logs", "focus_detect_cli_fallback.log"), line)


def _is_focus_cuda_usable() -> bool:
    try:
        from utils.system.gpu_utils import is_torch_cuda_usable

        return bool(is_torch_cuda_usable())
    except Exception:
        return False


def _resolve_yolo_seg_model_path(model: str) -> str:
    raw = str(model or "").strip()
    if raw:
        try:
            if os.path.isfile(raw):
                return raw
        except Exception:
            pass
        try:
            if raw.lower().endswith(".pt"):
                filename = os.path.basename(raw)
            else:
                filename = ""
        except Exception:
            filename = ""
    else:
        filename = ""
    if not filename:
        model_map = {
            "n": "yolov8n-seg.pt",
            "s": "yolov8s-seg.pt",
            "m": "yolov8m-seg.pt",
            "l": "yolov8l-seg.pt",
            "x": "yolov8x-seg.pt",
        }
        filename = model_map.get((model or "").lower(), "yolov8x-seg.pt")
    candidates = [
        os.path.join(os.getcwd(), "models", filename),
        os.path.join(_project_root, "assets", "models", filename),
        os.path.join(_project_root, "models", filename),
    ]
    for p in candidates:
        try:
            if os.path.isfile(p):
                return p
        except Exception:
            continue
    return candidates[0]


def _resolve_valid_yolo_seg_model_path(model: str) -> str:
    raw = str(model or "").strip()
    if raw:
        try:
            if os.path.isfile(raw):
                size = int(os.path.getsize(raw))
                if size >= 3 * 1024 * 1024:
                    try:
                        if zipfile.is_zipfile(raw):
                            return raw
                    except Exception:
                        pass
                    try:
                        if str(raw).lower().endswith(".pt"):
                            return raw
                    except Exception:
                        pass
        except Exception:
            pass
    filename = os.path.basename(_resolve_yolo_seg_model_path(model))
    candidates = [
        os.path.join(os.getcwd(), "models", filename),
        os.path.join(_project_root, "assets", "models", filename),
        os.path.join(_project_root, "models", filename),
    ]
    try:
        candidates = list(dict.fromkeys([str(p) for p in candidates if p]))
    except Exception:
        pass

    errors: list[str] = []
    for p in candidates:
        try:
            if not os.path.isfile(p):
                continue
            size = int(os.path.getsize(p))
            if size < 3 * 1024 * 1024:
                errors.append(f"{p} 文件过小({size} bytes)，可能未下载完整或已损坏")
                continue
            ok_zip = False
            try:
                ok_zip = bool(zipfile.is_zipfile(p))
            except Exception:
                ok_zip = False
            if not ok_zip:
                try:
                    if str(p).lower().endswith(".pt"):
                        return p
                except Exception:
                    pass
                errors.append(f"{p} 不是有效的模型文件(Zip结构无效)，可能已损坏")
                continue
            return p
        except Exception as e:
            errors.append(f"{p} 检查失败: {e}")
            continue

    hint = "；".join(errors) if errors else "未找到模型文件"
    raise RuntimeError(f"YOLO 分割模型文件不可用：{hint}。请将正确的 {filename} 放到 models/ 目录后重试。")


_FOCUS_DETECTOR_WORKER_INSTANCE = None
_FOCUS_DETECT_EYE_ENABLED = False


def clear_focus_detector():
    global _FOCUS_DETECTOR_WORKER_INSTANCE
    det = _FOCUS_DETECTOR_WORKER_INSTANCE
    _FOCUS_DETECTOR_WORKER_INSTANCE = None
    try:
        focus_trace("clear_focus_detector: begin")
    except Exception:
        pass
    try:
        if det is not None:
            try:
                setattr(det, "model", None)
            except Exception:
                pass
            try:
                del det
            except Exception:
                pass
    except Exception:
        pass
    try:
        import torch

        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    except Exception:
        pass
    try:
        focus_trace("clear_focus_detector: done")
    except Exception:
        pass


def _focus_detect_worker_init(
    model_path: str,
    target_size: int,
    use_gpu: bool,
    multi_check: bool,
    exp_frame_check: bool,
    initial_conf: float = 0.15,
    enable_eye_detect: bool = False,
):
    global _FOCUS_DETECTOR_WORKER_INSTANCE, _FOCUS_DETECT_EYE_ENABLED
    t0 = time.time()
    try:
        focus_trace(
            f"worker_init start pid={os.getpid()} model={model_path} target_size={int(target_size or 0)} use_gpu={bool(use_gpu)}"
        )
    except Exception:
        pass
    try:
        import cv2
        if hasattr(cv2, "ocl"):
            try:
                cv2.ocl.setUseOpenCL(False)
            except Exception:
                pass
    except Exception:
        pass
    from core.detectors.bird_focus_detector import BirdFocusDetector

    det = BirdFocusDetector(
        str(model_path),
        target_size=int(target_size or 640),
        initial_conf=float(initial_conf or 0.15),
        multi_check=bool(multi_check),
        exp_frame_check=bool(exp_frame_check),
        save_output=False,
        print_focus_point=False,
    )
    try:
        _FOCUS_DETECT_EYE_ENABLED = bool(enable_eye_detect)
    except Exception:
        _FOCUS_DETECT_EYE_ENABLED = False
    try:
        det.enable_scaled_cache(True)
    except Exception:
        pass
    try:
        effective_gpu = bool(use_gpu)
        if effective_gpu and (not _is_focus_cuda_usable()):
            effective_gpu = False
        det.device = "cuda" if bool(effective_gpu) else "cpu"
    except Exception:
        pass
    try:
        if not bool(locals().get("effective_gpu", False)):
            from utils.system.gpu_utils import GPUScaler
            GPUScaler.set_suspended(True)
    except Exception:
        pass
    _FOCUS_DETECTOR_WORKER_INSTANCE = det
    try:
        focus_trace(f"worker_init done pid={os.getpid()} elapsed_ms={int((time.time()-t0)*1000)}")
    except Exception:
        pass


def prewarm_focus_detector(
    *,
    model: str = "x",
    target_size: int = 640,
    use_gpu: bool = True,
    multi_check: bool = True,
    exp_frame_check: bool = True,
    enable_eye_detect: bool = False,
    initial_conf: float = 0.15,
):
    model_path = _resolve_valid_yolo_seg_model_path(model)
    effective_gpu = bool(use_gpu)
    if effective_gpu and (not _is_focus_cuda_usable()):
        effective_gpu = False
    _focus_detect_worker_init(
        model_path,
        int(target_size or 640),
        bool(effective_gpu),
        bool(multi_check),
        bool(exp_frame_check),
        float(initial_conf or 0.15),
        bool(enable_eye_detect),
    )


def _focus_detect_one_path(image_path: str, af_focus_point=None):
    global _FOCUS_DETECTOR_WORKER_INSTANCE, _FOCUS_DETECT_EYE_ENABLED
    if _FOCUS_DETECTOR_WORKER_INSTANCE is None:
        _focus_detect_worker_init(_resolve_valid_yolo_seg_model_path("x"), 640, _is_focus_cuda_usable(), True, True, 0.15, bool(_FOCUS_DETECT_EYE_ENABLED))
    det = _FOCUS_DETECTOR_WORKER_INSTANCE
    targets = [
        "score",
        "norm_score",
        "area",
        "pos",
        "center",
        "conf",
        "is_minimal",
        "exp_frame",
        "raw_bg_score",
        "bg_score",
        "bbox_orig",
        "ratio",
        "ratio_local",
        "hf_ratio",
        "hf_margin",
        "texture_edge_density",
        "texture_edge_density_bg",
        "texture_edge_density_ratio",
        "texture_entropy",
        "texture_entropy_bg",
        "texture_entropy_ratio",
        "ratio_best",
        "has_bird",
    ]
    if bool(_FOCUS_DETECT_EYE_ENABLED) and "eye_coordinates" not in targets:
        targets.append("eye_coordinates")
    try:
        p0 = str(image_path)
        try:
            st = os.stat(p0)
            _file_size = int(st.st_size)
            _file_mtime = float(st.st_mtime)
        except Exception:
            _file_size = 0
            _file_mtime = 0.0
        _fh = None
        _need_close = False
        try:
            import faulthandler
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pid = os.getpid()
            lm = LogManager.instance()
            try:
                th = getattr(lm, "_thread", None)
                if th is None or (hasattr(th, "is_alive") and not th.is_alive()):
                    lm.start()
            except Exception:
                pass
            _fh = getattr(lm, "_file_handle", None)
            if _fh is None:
                try:
                    out_dir = os.path.join(_project_root, "cache", "logs")
                    os.makedirs(out_dir, exist_ok=True)
                    _fh = open(os.path.join(out_dir, "focus_detect_cli_fallback.log"), "a", encoding="utf-8")
                    _need_close = True
                except Exception:
                    try:
                        import sys
                        _fh = sys.stderr
                    except Exception:
                        _fh = None
            try:
                if _fh is not None:
                    _fh.write(f"\n[FocusDetectCLI] hang_watchdog_start pid={pid} ts={ts}\npath={p0}\nsize={_file_size}\nmtime={_file_mtime}\n")
                    try:
                        _fh.flush()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if _fh is not None:
                    faulthandler.dump_traceback_later(45, file=_fh, repeat=False)
            except Exception:
                pass
        except Exception:
            _fh = None
        t0 = time.perf_counter()
        res = det.analyze_file(p0, targets=targets, af_focus_point=af_focus_point)
        t1 = time.perf_counter()
        if not isinstance(res, dict):
            res = {}
        res["path"] = p0
        if isinstance(af_focus_point, dict) and af_focus_point:
            try:
                res["focus_point"] = af_focus_point
            except Exception:
                pass
        try:
            res["_file_size"] = int(_file_size)
            res["_file_mtime"] = float(_file_mtime)
        except Exception:
            pass
        try:
            from cache.focus_scaled_cache import save_scaled_cv_bgr

            do_save = True
            try:
                if int(_file_size or 0) >= 20 * 1024 * 1024:
                    do_save = False
            except Exception:
                do_save = True
            if do_save:
                _t_sc0 = time.perf_counter()
                img_small, _sx, _sy, ow, oh = det.load_image_scaled_for_detection(p0)
                if img_small is not None and hasattr(img_small, "shape"):
                    save_scaled_cv_bgr(
                        p0,
                        int(getattr(det, "target_size", 640) or 640),
                        img_small,
                        orig_w=int(ow or 0),
                        orig_h=int(oh or 0),
                        scope="import_focus",
                        quality=90,
                    )
                _t_sc1 = time.perf_counter()
                try:
                    res["_scaled_cache_ms"] = float((_t_sc1 - _t_sc0) * 1000.0)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            res["_elapsed_ms"] = float((t1 - t0) * 1000.0)
        except Exception:
            pass
        try:
            import faulthandler
            faulthandler.cancel_dump_traceback_later()
        except Exception:
            pass
        try:
            if _need_close and _fh is not None:
                _fh.close()
        except Exception:
            pass
        return res
    except Exception as e:
        return {"path": str(image_path), "_error": str(e)}


def detect_focus_batch_for_import(
    image_paths: Sequence[str],
    *,
    enable_burst: bool = True,
    enable_similarity: bool = True,
    use_multiprocess: bool = True,
    use_gpu: bool = True,
    multi_check: bool = True,
    exp_frame_check: bool = True,
    enable_eye_detect: bool = False,
    enable_af_point_detect: bool = True,
    model: str = "x",
    initial_conf: float = 0.15,
    target_size: int = 640,
    burst_min_count: int = 10,
    burst_fps: int = 20,
    reserve_cpu: int = 4,
    per_file_timeout_sec: int = 240,
    progress_callback: Callable[[str, int, int, float], None] | None = None,
    cancel_event: object | None = None,
) -> Dict[str, Any]:
    paths = [str(p) for p in (image_paths or []) if p]
    if not paths:
        return {"results": {}, "options": {}}

    _all_start_ts = time.time()
    _t_all = time.perf_counter()
    _t_init0 = _t_all
    
    effective_use_gpu = bool(use_gpu)
    enable_eye_detect = bool(enable_eye_detect)
    try:
        global _FOCUS_DETECT_EYE_ENABLED
        _FOCUS_DETECT_EYE_ENABLED = bool(enable_eye_detect)
    except Exception:
        pass
    
    if effective_use_gpu and (not _is_focus_cuda_usable()):
        effective_use_gpu = False

    model_path = _resolve_valid_yolo_seg_model_path(model)

    if not bool(use_multiprocess):
        try:
            _focus_detect_worker_init(
                model_path,
                int(target_size or 640),
                bool(effective_use_gpu),
                bool(multi_check),
                bool(exp_frame_check),
                float(initial_conf or 0.15),
                bool(enable_eye_detect),
            )
        except Exception:
            pass

    _t_settings0 = time.perf_counter()
    try:
        from utils.setting.settings_manager import SettingsManager

        sm = SettingsManager()
        if bool(sm.get("debug/focus_save_output", False)):
            out_root = str(sm.get("debug/focus_save_output_dir", "") or "").strip()
            if not out_root:
                out_root = os.path.join(_project_root, "data", "debug", "focus_output")
            out_abs = os.path.abspath(out_root)
            if os.path.isdir(out_abs):
                drive, tail = os.path.splitdrive(out_abs)
                if tail not in ("\\", "/") and out_abs not in (drive + "\\", drive + "/"):
                    shutil.rmtree(out_abs, ignore_errors=True)
    except Exception:
        pass
    _t_settings1 = time.perf_counter()
    try:
        focus_trace(f"stage=init.settings elapsed_s={float(_t_settings1 - _t_settings0):.3f}")
    except Exception:
        pass

    _t_db0 = time.perf_counter()
    db = None
    get_fast_id = None
    get_unique_id = None
    json_mod = None
    try:
        from utils.sql.data_base import BirdLibraryDB
        from utils.file.file_util import get_fast_id as _get_fast_id
        from utils.file.fingerprint import get_unique_id as _get_unique_id
        import json as _json

        db = BirdLibraryDB()
        get_fast_id = _get_fast_id
        get_unique_id = _get_unique_id
        json_mod = _json
    except Exception:
        db = None
    _t_db1 = time.perf_counter()
    try:
        focus_trace(f"stage=init.db elapsed_s={float(_t_db1 - _t_db0):.3f} enabled={bool(db is not None)}")
    except Exception:
        pass

    preserved_by_path = {}
    _t_preserve0 = time.perf_counter()
    try:
        if db is not None and hasattr(db, "get_results_by_paths") and hasattr(db, "_normalize_file_path_for_db"):
            db_paths = []
            for p in paths:
                try:
                    p_db = db._normalize_file_path_for_db(p)
                except Exception:
                    p_db = p
                if p_db:
                    db_paths.append(str(p_db))
            preserved_raw = db.get_results_by_paths(db_paths, table_name="import_cache") or {}
            if isinstance(preserved_raw, dict) and preserved_raw:
                preserved_by_path = {}
                for k, v in preserved_raw.items():
                    try:
                        nk = db._norm_path_key(k)
                    except Exception:
                        nk = str(k)
                    if nk:
                        preserved_by_path[str(nk)] = v
    except Exception:
        preserved_by_path = {}
    _t_preserve1 = time.perf_counter()
    try:
        focus_trace(
            f"stage=init.preserved elapsed_s={float(_t_preserve1 - _t_preserve0):.3f} records={len(preserved_by_path or {})}"
        )
    except Exception:
        pass

    _t_init1 = time.perf_counter()
    try:
        init_s = float(_t_init1 - _t_init0)
        init_avg_ms = (init_s * 1000.0 / float(len(paths))) if paths else 0.0
        focus_trace(f"stage=init elapsed_s={init_s:.3f} avg_ms_per_file={init_avg_ms:.1f} files={len(paths)} gpu={bool(effective_use_gpu)} mp={bool(use_multiprocess)}")
    except Exception:
        pass

    if bool(enable_similarity):
        try:
            focus_trace("stage=similarity elapsed_s=0.000 note=not_implemented")
        except Exception:
            pass

    _db_flush_time_s = 0.0
    _db_flush_batches = 0
    _db_flush_rows = 0
    _db_writer_queue: queue.Queue = queue.Queue(maxsize=50000)
    _db_writer_stop = threading.Event()
    _db_batch = 800
    _db_writer_thread = None

    def _db_writer_run():
        nonlocal _db_flush_time_s, _db_flush_batches, _db_flush_rows
        if db is None or get_fast_id is None or get_unique_id is None or json_mod is None:
            return
        buf = []
        last_flush_ts = 0.0

        def _flush_now():
            nonlocal buf, _db_flush_time_s, _db_flush_batches, _db_flush_rows, last_flush_ts
            if not buf:
                return
            try:
                n0 = int(len(buf))
            except Exception:
                n0 = 0
            t0 = time.perf_counter()
            try:
                db.save_results_batch(buf, table_name="import_cache")
            except Exception:
                pass
            t1 = time.perf_counter()
            try:
                elapsed = float(t1 - t0)
                if elapsed >= 0.8:
                    focus_trace(f"stage=db.flush elapsed_s={elapsed:.3f} rows={int(n0)}")
            except Exception:
                pass
            try:
                _db_flush_time_s = float(_db_flush_time_s) + float(t1 - t0)
                _db_flush_batches = int(_db_flush_batches) + 1
                _db_flush_rows = int(_db_flush_rows) + int(n0)
                last_flush_ts = float(time.time())
            except Exception:
                pass
            buf = []
            try:
                qn = int(_db_writer_queue.qsize())
            except Exception:
                qn = 0
            if qn >= 2000:
                try:
                    focus_trace(f"stage=db.backlog qsize={qn} last_flush_rows={int(n0)}")
                except Exception:
                    pass

        while True:
            try:
                item = _db_writer_queue.get(timeout=0.2)
            except Exception:
                item = None
            if item is None:
                if _db_writer_stop.is_set():
                    break
                try:
                    if buf and (time.time() - float(last_flush_ts or 0.0)) > 1.2:
                        _flush_now()
                except Exception:
                    pass
                continue
            try:
                p, r = item
            except Exception:
                continue
            try:
                p = str(p or "")
            except Exception:
                p = ""
            if not p:
                continue
            if not isinstance(r, dict):
                r = {}
            try:
                bbox = r.get("bbox_orig") or r.get("bbox") or None
                score = r.get("score")
                norm_score = r.get("norm_score")
                area_ratio = r.get("area")
                pos = r.get("pos") or ""
                try:
                    nk = db._norm_path_key(p) if hasattr(db, "_norm_path_key") else str(p)
                except Exception:
                    nk = str(p)
                preserved = preserved_by_path.get(str(nk)) if isinstance(preserved_by_path, dict) else None
                label = preserved.get("label") if isinstance(preserved, dict) else None
                rating = preserved.get("rating") if isinstance(preserved, dict) else None
                is_favorite = preserved.get("is_favorite") if isinstance(preserved, dict) else None
                tags = preserved.get("tags") if isinstance(preserved, dict) else None
                fp = None
                try:
                    fp = r.get("focus_point") if isinstance(r, dict) else None
                except Exception:
                    fp = None
                if fp is None and isinstance(preserved, dict):
                    try:
                        fp = preserved.get("focus_point")
                    except Exception:
                        fp = None
                extra = dict(r)
                try:
                    extra.pop("bbox", None)
                    extra.pop("bbox_orig", None)
                    extra.pop("focus_point", None)
                except Exception:
                    pass
                focus_detect_json = ""
                try:
                    focus_detect_json = json_mod.dumps(extra, ensure_ascii=False)
                except Exception:
                    focus_detect_json = ""
                try:
                    desc = preserved.get("description") if isinstance(preserved, dict) else ""
                except Exception:
                    desc = ""
                try:
                    st = os.stat(p)
                    pixel_count = int(st.st_size)
                except Exception:
                    pixel_count = 0
                buf.append(
                    {
                        "uuid": get_unique_id(),
                        "fast_id": get_fast_id(p),
                        "path": p,
                        "file": os.path.basename(p),
                        "label": label,
                        "score": score,
                        "norm_score": norm_score,
                        "bbox": bbox,
                        "position": pos,
                        "pixel_count": pixel_count,
                        "area_ratio": area_ratio,
                        "focus_point": fp,
                        "description": desc,
                        "focus_detect_json": focus_detect_json,
                        "rating": int(rating or 0),
                        "is_favorite": int(is_favorite or 0),
                        "tags": str(tags or ""),
                    }
                )
            except Exception:
                continue
            if len(buf) >= int(_db_batch):
                _flush_now()
        try:
            _flush_now()
        except Exception:
            pass

    if db is not None and get_fast_id is not None and get_unique_id is not None and json_mod is not None:
        try:
            _db_writer_thread = threading.Thread(target=_db_writer_run, daemon=True, name="FocusDetectDBWriter")
            _db_writer_thread.start()
        except Exception:
            _db_writer_thread = None

    def _record_result(p: str, r: dict):
        if _db_writer_thread is None:
            return
        try:
            _db_writer_queue.put_nowait((str(p or ""), r if isinstance(r, dict) else {}))
        except Exception:
            try:
                focus_trace("stage=db.queue_full drop=1")
            except Exception:
                pass
            return

    burst_first_by_path: Dict[str, str] = {}
    if enable_burst:
        _t_burst0 = time.perf_counter()
        try:
            from core.detectors.burst_detector import BurstDetector, FileInfo

            bd = BurstDetector(
                burst_fps=float(burst_fps or 0),
                burst_time_threshold=int(burst_min_count or 1),
                burst_check_by_similarity=False,
            )
            fis = []
            for p in paths:
                fis.append(FileInfo(file_path=p, file_name=os.path.basename(p), sub_dir="", is_root_dir=True))
            _t_burst_prefetch0 = time.perf_counter()
            bd._prefetch_times(fis, batch_size=800, timeout=20)
            _t_burst_prefetch1 = time.perf_counter()
            try:
                focus_trace(f"stage=burst.prefetch elapsed_s={float(_t_burst_prefetch1 - _t_burst_prefetch0):.3f} files={len(fis)}")
            except Exception:
                pass
            try:
                fis.sort(key=lambda x: (x.timestamp is None, x.timestamp or 0.0, str(x.file_name or "")))
            except Exception:
                pass
            _t_burst_group0 = time.perf_counter()
            for fi in fis:
                if not bd.current_burst_group:
                    bd.previous_file = fi
                    bd.current_burst_group = [fi]
                    continue
                end, first_name = bd.process_file(fi, lambda _: None, lambda a, b: 0.0)
                if end:
                    finished = bd.saved_burst_group or []
                    if len(finished) >= int(burst_min_count or 1):
                        first_file_name = str(first_name or finished[0].file_name or "")
                        for x in finished:
                            burst_first_by_path[str(x.file_path)] = first_file_name
                    else:
                        for x in finished:
                            burst_first_by_path[str(x.file_path)] = ""
            if bd.current_burst_group:
                tail = bd.current_burst_group
                if len(tail) >= int(burst_min_count or 1):
                    first_file_name = str(tail[0].file_name or "")
                    for x in tail:
                        burst_first_by_path[str(x.file_path)] = first_file_name
                else:
                    for x in tail:
                        burst_first_by_path[str(x.file_path)] = ""
            _t_burst_group1 = time.perf_counter()
            try:
                focus_trace(f"stage=burst.group elapsed_s={float(_t_burst_group1 - _t_burst_group0):.3f} files={len(fis)}")
            except Exception:
                pass
        except Exception:
            burst_first_by_path = {}
        _t_burst1 = time.perf_counter()
        try:
            burst_s = float(_t_burst1 - _t_burst0)
            burst_avg_ms = (burst_s * 1000.0 / float(len(paths))) if paths else 0.0
            focus_trace(f"stage=burst elapsed_s={burst_s:.3f} avg_ms_per_file={burst_avg_ms:.1f} files={len(paths)}")
        except Exception:
            pass

    results_by_path: Dict[str, Dict[str, Any]] = {}
    try:
        if callable(progress_callback):
            progress_callback("初始化", 0, int(len(paths)), float(time.time()))
    except Exception:
        pass

    _t_focus0 = time.perf_counter()
    _sum_worker_ms = 0.0
    _max_worker_ms = 0.0
    _worker_ms_count = 0
    _error_count = 0
    _slow_samples: list[tuple[float, str]] = []
    def _track_slow_sample(ms: float, p: str):
        nonlocal _slow_samples
        try:
            ms0 = float(ms or 0.0)
        except Exception:
            return
        if ms0 <= 0.0:
            return
        if ms0 < 5000.0:
            return
        try:
            p0 = str(p or "")
        except Exception:
            p0 = ""
        if not p0:
            return
        try:
            _slow_samples.append((ms0, p0))
            _slow_samples.sort(key=lambda x: float(x[0]), reverse=True)
            if len(_slow_samples) > 10:
                _slow_samples = _slow_samples[:10]
        except Exception:
            pass
    cancelled = False

    af_point_by_norm_path: dict[str, dict] = {}
    try:
        enable_af_point_detect = bool(enable_af_point_detect)
    except Exception:
        enable_af_point_detect = True
    if bool(enable_af_point_detect):
        try:
            if callable(progress_callback):
                progress_callback("读取对焦点", 0, int(len(paths)), float(time.time()))
        except Exception:
            pass
        try:
            from utils.exif.camera_af_point import get_camera_af_center_points

            try:
                cpu_count = int(os.cpu_count() or 4)
            except Exception:
                cpu_count = 4
            try:
                reserve = int(reserve_cpu or 0)
            except Exception:
                reserve = 0
            max_workers = max(1, min(4, int(cpu_count - max(0, reserve))))

            def _af_progress(done: int, total: int):
                try:
                    if callable(progress_callback):
                        progress_callback("读取对焦点", int(done), int(total), float(time.time()))
                except Exception:
                    pass

            af_raw = get_camera_af_center_points(
                list(paths),
                timeout=16,
                chunk_size=4,
                max_workers=int(max_workers),
                progress_callback=_af_progress,
                cancel_event=cancel_event,
            )
            for p0, fp in (af_raw or {}).items():
                if not isinstance(fp, dict) or not fp:
                    continue
                try:
                    nk = os.path.normcase(os.path.normpath(str(p0)))
                except Exception:
                    nk = str(p0)
                if nk:
                    af_point_by_norm_path[str(nk)] = fp
        except Exception:
            af_point_by_norm_path = {}
        _t_af1 = time.perf_counter()
        try:
            focus_trace(
                f"stage=exif.af elapsed_s={float(_t_af1 - _t_af0):.3f} "
                f"files={len(paths)} hits={len(af_point_by_norm_path or {})} enabled={bool(enable_af_point_detect)}"
            )
        except Exception:
            pass
    # 对焦点检测完成后，显示初始化进度
    try:
        if callable(progress_callback):
            progress_callback("初始化对焦检测", 0, int(len(paths)), float(time.time()))
    except Exception:
        pass
    if use_multiprocess:
        try:
            cpu_count = int(os.cpu_count() or 4)
        except Exception:
            cpu_count = 4
        try:
            reserve = int(reserve_cpu or 0)
        except Exception:
            reserve = 0
        proc = max(1, cpu_count - max(0, reserve))
        proc = min(proc, 12)
        if bool(effective_use_gpu):
            proc = 1
        ctx = mp.get_context("spawn")
        _t_pool0 = time.perf_counter()
        pool = ctx.Pool(
            processes=proc,
            initializer=_focus_detect_worker_init,
            initargs=(
                model_path,
                int(target_size or 640),
                bool(effective_use_gpu),
                bool(multi_check),
                bool(exp_frame_check),
                float(initial_conf or 0.15),
                bool(enable_eye_detect),
            ),
        )
        _t_pool1 = time.perf_counter()
        try:
            total = len(paths)
            done = 0
            start_ts = time.time()
            _t_iter0 = time.perf_counter()
            _first_result_ms = None
            last_progress_ts = float(time.time())
            stall_grace_s = 6.0
            pool_restart_count = 0
            last_diag_ts = 0.0
            try:
                timeout_sec = int(per_file_timeout_sec or 0)
            except Exception:
                timeout_sec = 0
            timeout_sec = int(max(30, min(3600, timeout_sec))) if timeout_sec > 0 else 240
            try:
                max_inflight = int(max(1, int(proc)))
            except Exception:
                max_inflight = 1
            try:
                from collections import deque
                _queue = deque(paths)
            except Exception:
                _queue = list(paths)
            inflight = []
            start_by_path = {}
            while True:
                try:
                    if cancel_event is not None and hasattr(cancel_event, "is_set") and bool(cancel_event.is_set()):
                        cancelled = True
                        try:
                            for p0, _ar0 in inflight:
                                r = {"path": str(p0), "_error": "cancelled"}
                                results_by_path[str(p0)] = r
                                _record_result(str(p0), r)
                                _error_count += 1
                        except Exception:
                            pass
                        try:
                            for p0 in list(_queue):
                                if not p0:
                                    continue
                                r = {"path": str(p0), "_error": "cancelled"}
                                results_by_path[str(p0)] = r
                                _record_result(str(p0), r)
                                _error_count += 1
                        except Exception:
                            pass
                        done = total
                        break
                except Exception:
                    pass
                try:
                    while _queue and len(inflight) < max_inflight:
                        try:
                            p0 = _queue.popleft()
                        except Exception:
                            p0 = _queue.pop(0)
                        if not p0:
                            continue
                        try:
                            nk = os.path.normcase(os.path.normpath(str(p0)))
                        except Exception:
                            nk = str(p0)
                        af_focus_point = (af_point_by_norm_path or {}).get(str(nk)) if nk else None
                        try:
                            ar = pool.apply_async(_focus_detect_one_path, (p0, af_focus_point))
                        except Exception:
                            ar = None
                        if ar is None:
                            r = {"path": str(p0), "_error": "submit_failed"}
                            results_by_path[str(p0)] = r
                            _record_result(str(p0), r)
                            _error_count += 1
                            done += 1
                            if callable(progress_callback):
                                try:
                                    progress_callback("对焦检测", int(done), int(total), float(start_ts))
                                except Exception:
                                    pass
                            continue
                        inflight.append((str(p0), ar))
                        start_by_path[str(p0)] = float(time.time())
                except Exception:
                    pass

                progressed = False
                try:
                    for i in range(len(inflight) - 1, -1, -1):
                        p0, ar0 = inflight[i]
                        try:
                            ready0 = bool(ar0.ready())
                        except Exception:
                            ready0 = False
                        if not ready0:
                            continue
                        try:
                            r = ar0.get(timeout=0.1)
                        except Exception as e:
                            r = {"path": str(p0), "_error": str(e)}
                        inflight.pop(i)
                        try:
                            start_by_path.pop(str(p0), None)
                        except Exception:
                            pass
                        progressed = True

                        if _first_result_ms is None:
                            try:
                                _first_result_ms = float((time.perf_counter() - _t_iter0) * 1000.0)
                            except Exception:
                                _first_result_ms = 0.0

                        if not isinstance(r, dict):
                            r = {"path": str(p0)}
                        p = str(r.get("path") or p0 or "")
                        if not p:
                            p = str(p0)
                            r["path"] = p
                        if r.get("_error"):
                            _error_count += 1
                        try:
                            ems = float(r.get("_elapsed_ms") or 0.0)
                        except Exception:
                            ems = 0.0
                        if ems > 0.0:
                            _sum_worker_ms += ems
                            _worker_ms_count += 1
                            if ems > _max_worker_ms:
                                _max_worker_ms = ems
                            _track_slow_sample(float(ems), p)
                        if ems >= 1200.0 and isinstance(r, dict):
                            try:
                                device = str(r.get("_device") or "")
                            except Exception:
                                device = ""
                            try:
                                seg_tag = str(r.get("_seg_tag") or "")
                            except Exception:
                                seg_tag = ""
                            try:
                                focus_trace(
                                    "stage=focus.profile "
                                    f"path={p} elapsed_ms={ems:.1f} "
                                    f"device={device} "
                                    f"load_ms={float(r.get('_t_load_s') or 0.0)*1000.0:.1f} "
                                    f"seg_ms={float(r.get('_t_seg_s') or 0.0)*1000.0:.1f} "
                                    f"score_ms={float(r.get('_t_score_s') or 0.0)*1000.0:.1f} "
                                    f"tex_ms={float(r.get('_t_tex_s') or 0.0)*1000.0:.1f} "
                                    f"focus_ms={float(r.get('_t_focus_s') or 0.0)*1000.0:.1f} "
                                    f"model_calls={int(r.get('_model_calls') or 0)} "
                                    f"model_s={float(r.get('_model_s') or 0.0):.3f} "
                                    f"model_max_s={float(r.get('_model_max_s') or 0.0):.3f} "
                                    f"model_fallback={int(r.get('_model_fallback') or 0)} "
                                    f"seg_calls={int(r.get('_seg_calls') or 0)} "
                                    f"seg_exif_ms={float(r.get('_seg_exif_s') or 0.0)*1000.0:.1f} "
                                    f"seg_tag={seg_tag}"
                                )
                            except Exception:
                                pass
                        results_by_path[p] = r
                        _record_result(p, r)
                        done += 1
                        if callable(progress_callback):
                            try:
                                progress_callback("对焦检测", int(done), int(total), float(start_ts))
                            except Exception:
                                pass
                except Exception:
                    progressed = False

                if done >= total:
                    break
                if progressed:
                    last_progress_ts = float(time.time())
                    continue

                timed_out_path = None
                now_ts = float(time.time())
                if inflight:
                    try:
                        stall_s = float(now_ts - float(last_progress_ts))
                    except Exception:
                        stall_s = 0.0
                    if stall_s >= 3.0:
                        try:
                            if (not last_diag_ts) or (float(now_ts - float(last_diag_ts)) >= 10.0):
                                last_diag_ts = float(now_ts)
                                samples = []
                                try:
                                    pairs = []
                                    for p0, _ar0 in inflight:
                                        st0 = float(start_by_path.get(str(p0), now_ts))
                                        pairs.append((float(now_ts - st0), str(p0)))
                                    pairs.sort(key=lambda x: float(x[0]), reverse=True)
                                    for dur, p0 in pairs[:5]:
                                        samples.append(f"{dur:.1f}s:{os.path.basename(p0)}")
                                except Exception:
                                    samples = []
                                try:
                                    qlen = int(len(_queue))
                                except Exception:
                                    try:
                                        qlen = int(_queue.qsize())
                                    except Exception:
                                        qlen = 0
                                focus_trace(
                                    f"stage=focus.stall stall_s={stall_s:.1f} done={done}/{total} inflight={len(inflight)} queue={qlen} slowest={';'.join(samples)}"
                                )
                        except Exception:
                            pass
                try:
                    if inflight and (now_ts - float(last_progress_ts)) > float(stall_grace_s):
                        for p0, _ar0 in inflight:
                            st0 = float(start_by_path.get(str(p0), now_ts))
                            if (now_ts - st0) > float(timeout_sec):
                                timed_out_path = str(p0)
                                break
                except Exception:
                    timed_out_path = None

                if not timed_out_path:
                    try:
                        qleft = int(len(_queue))
                    except Exception:
                        qleft = 1
                    try:
                        if inflight and (now_ts - float(last_progress_ts)) > 30.0 and qleft > 0:
                            timed_out_path = str(min(start_by_path.items(), key=lambda kv: float(kv[1] or now_ts))[0])
                    except Exception:
                        timed_out_path = None

                if timed_out_path:
                    r = {"path": str(timed_out_path), "_error": f"timeout>{int(timeout_sec)}s"}
                    results_by_path[str(timed_out_path)] = r
                    _record_result(str(timed_out_path), r)
                    _error_count += 1
                    done += 1
                    if callable(progress_callback):
                        try:
                            progress_callback("对焦检测", int(done), int(total), float(start_ts))
                        except Exception:
                            pass
                    try:
                        samples = []
                        try:
                            pairs = []
                            for p0, _ar0 in inflight:
                                st0 = float(start_by_path.get(str(p0), now_ts))
                                pairs.append((float(now_ts - st0), str(p0)))
                            pairs.sort(key=lambda x: float(x[0]), reverse=True)
                            for dur, p0 in pairs[:5]:
                                samples.append(f"{dur:.1f}s:{os.path.basename(p0)}")
                        except Exception:
                            samples = []
                        focus_trace(
                            f"stage=focus.timeout path={timed_out_path} timeout_s={int(timeout_sec)} inflight={len(inflight)} slowest={';'.join(samples)}"
                        )
                    except Exception:
                        pass

                    try:
                        rest = [p for p, _ in inflight if str(p) != str(timed_out_path)]
                    except Exception:
                        rest = []
                    inflight = []
                    start_by_path = {}
                    try:
                        pool.terminate()
                    except Exception:
                        pass
                    try:
                        pool.join()
                    except Exception:
                        pass
                    try:
                        pool_restart_count += 1
                    except Exception:
                        pass
                    if pool_restart_count >= 5:
                        try:
                            remain_paths = []
                            try:
                                remain_paths.extend(list(rest))
                            except Exception:
                                pass
                            try:
                                remain_paths.extend(list(_queue))
                            except Exception:
                                pass
                            for p_bad in remain_paths:
                                try:
                                    p_bad = str(p_bad or "")
                                except Exception:
                                    p_bad = ""
                                if not p_bad:
                                    continue
                                r = {"path": p_bad, "_error": "timeout_restart_limit"}
                                results_by_path[p_bad] = r
                                _record_result(p_bad, r)
                                _error_count += 1
                                done += 1
                                if callable(progress_callback):
                                    try:
                                        progress_callback("对焦检测", int(done), int(total), float(start_ts))
                                    except Exception:
                                        pass
                            done = total
                        except Exception:
                            pass
                        break
                    try:
                        remaining = int(len(rest) + len(_queue))
                    except Exception:
                        remaining = int(len(rest))
                    if remaining <= 0:
                        break
                    try:
                        new_proc = int(proc)
                        if len(rest) > 0:
                            new_proc = max(1, min(int(proc), int(len(rest))))
                    except Exception:
                        new_proc = int(proc)
                    pool = ctx.Pool(
                        processes=new_proc,
                        initializer=_focus_detect_worker_init,
                        initargs=(
                            model_path,
                            int(target_size or 640),
                            bool(effective_use_gpu),
                            bool(multi_check),
                            bool(exp_frame_check),
                            float(initial_conf or 0.15),
                            bool(enable_eye_detect),
                        ),
                    )
                    try:
                        if hasattr(_queue, "extendleft"):
                            _queue.extendleft(reversed(rest))
                        else:
                            _queue = list(rest) + list(_queue)
                    except Exception:
                        pass
                    continue

                try:
                    time.sleep(0.03)
                except Exception:
                    pass
            _t_iter1 = time.perf_counter()
            try:
                if _first_result_ms is None:
                    _first_result_ms = float((time.perf_counter() - _t_iter0) * 1000.0)
            except Exception:
                _first_result_ms = 0.0
            try:
                focus_trace(f"stage=focus.first_result first_result_ms={float(_first_result_ms):.1f}")
                focus_trace(f"stage=focus.loop elapsed_s={float(_t_iter1 - _t_iter0):.3f} done={done} errors={_error_count}")
            except Exception:
                pass
        finally:
            try:
                if cancelled:
                    pool.terminate()
                    procs = getattr(pool, "_pool", None)
                    if isinstance(procs, list):
                        for p0 in procs:
                            try:
                                p0.join(timeout=0.6)
                            except Exception:
                                pass
                else:
                    try:
                        pool.close()
                    except Exception:
                        pool.terminate()
            except Exception:
                pass
            try:
                if not cancelled:
                    pool.join()
            except Exception:
                pass
    else:
        _focus_detect_worker_init(
            model_path,
            int(target_size or 640),
            bool(effective_use_gpu),
            bool(multi_check),
            bool(exp_frame_check),
            float(initial_conf or 0.15),
            bool(enable_eye_detect),
        )
        total = len(paths)
        done = 0
        start_ts = time.time()
        _t_iter0 = time.perf_counter()
        for idx, p in enumerate(paths):
            try:
                if cancel_event is not None and hasattr(cancel_event, "is_set") and bool(cancel_event.is_set()):
                    cancelled = True
                    for p2 in (paths[idx:] or []):
                        if not p2:
                            continue
                        r2 = {"path": str(p2), "_error": "cancelled"}
                        results_by_path[str(p2)] = r2
                        _record_result(str(p2), r2)
                        _error_count += 1
                    done = total
                    break
            except Exception:
                pass
            try:
                nk = os.path.normcase(os.path.normpath(str(p)))
            except Exception:
                nk = str(p)
            af_focus_point = (af_point_by_norm_path or {}).get(str(nk)) if nk else None
            r = _focus_detect_one_path(p, af_focus_point)
            if not isinstance(r, dict):
                r = {"path": str(p)}
            if r.get("_error"):
                _error_count += 1
            try:
                ems = float(r.get("_elapsed_ms") or 0.0)
            except Exception:
                ems = 0.0
            if ems > 0.0:
                _sum_worker_ms += ems
                _worker_ms_count += 1
                if ems > _max_worker_ms:
                    _max_worker_ms = ems
                _track_slow_sample(float(ems), str(p))
            results_by_path[p] = r
            _record_result(str(p), r)
            done += 1
            if callable(progress_callback):
                try:
                    progress_callback("对焦检测", int(done), int(total), float(start_ts))
                except Exception:
                    pass
        _t_iter1 = time.perf_counter()
        try:
            focus_trace(f"stage=focus.loop elapsed_s={float(_t_iter1 - _t_iter0):.3f} done={done} errors={_error_count}")
        except Exception:
            pass
    _t_focus1 = time.perf_counter()
    try:
        focus_s = float(_t_focus1 - _t_focus0)
        focus_avg_ms = (focus_s * 1000.0 / float(len(paths))) if paths else 0.0
        avg_worker_ms = (_sum_worker_ms / float(_worker_ms_count)) if _worker_ms_count > 0 else 0.0
        focus_trace(f"stage=focus elapsed_s={focus_s:.3f} avg_ms_per_file={focus_avg_ms:.1f} files={len(paths)} worker_avg_ms={avg_worker_ms:.1f} worker_max_ms={float(_max_worker_ms):.1f} errors={_error_count}")
    except Exception:
        pass
    try:
        if _slow_samples:
            items = []
            for ms0, p0 in _slow_samples[:10]:
                try:
                    items.append(f"{ms0/1000.0:.2f}s:{p0}")
                except Exception:
                    continue
            if items:
                focus_trace(f"stage=focus.slowest samples={';'.join(items)}")
    except Exception:
        pass

    _t_dbflush0 = time.perf_counter()
    try:
        if callable(progress_callback):
            progress_callback("写入数据库", 0, 1, float(time.time()))
    except Exception:
        pass
    try:
        _db_writer_stop.set()
    except Exception:
        pass
    try:
        _db_writer_queue.put(None)
    except Exception:
        pass
    try:
        if _db_writer_thread is not None:
            _db_writer_thread.join(timeout=30.0)
    except Exception:
        pass
    _t_dbflush1 = time.perf_counter()
    try:
        if callable(progress_callback):
            progress_callback("写入数据库", 1, 1, float(time.time()))
    except Exception:
        pass
    try:
        flush_s = float(_t_dbflush1 - _t_dbflush0)
        avg_ms_per_row = (float(_db_flush_time_s) * 1000.0 / float(_db_flush_rows)) if int(_db_flush_rows) > 0 else 0.0
        focus_trace(f"stage=db_flush elapsed_s={flush_s:.3f} io_s={float(_db_flush_time_s):.3f} batches={int(_db_flush_batches)} rows={int(_db_flush_rows)} avg_ms_per_row={avg_ms_per_row:.3f}")
    except Exception:
        pass

    _t_post0 = time.perf_counter()
    for p in paths:
        r = results_by_path.get(p)
        if not isinstance(r, dict):
            r = {"path": p}
            results_by_path[p] = r
        r["burst_first_file"] = burst_first_by_path.get(p, "")
    _t_post1 = time.perf_counter()
    try:
        focus_trace(f"stage=postprocess elapsed_s={float(_t_post1 - _t_post0):.3f}")
    except Exception:
        pass

    try:
        elapsed = float(time.time() - float(_all_start_ts or time.time()))
        processed = int(len(results_by_path or {}))
        avg_ms = (elapsed * 1000.0 / processed) if processed > 0 else 0.0
        all_s = float(time.perf_counter() - _t_all)
        all_avg_ms = (all_s * 1000.0 / float(processed)) if processed > 0 else 0.0
        focus_trace(f"detect_focus_batch_for_import done processed={processed} elapsed_s={elapsed:.3f} avg_ms_per_file={avg_ms:.1f} wall_s={all_s:.3f} wall_avg_ms_per_file={all_avg_ms:.1f}")
    except Exception:
        pass

    return {
        "results": results_by_path,
        "options": {
            "enable_burst": bool(enable_burst),
            "enable_similarity": bool(enable_similarity),
            "use_multiprocess": bool(use_multiprocess),
            "use_gpu": bool(effective_use_gpu),
            "multi_check": bool(multi_check),
            "exp_frame_check": bool(exp_frame_check),
            "enable_eye_detect": bool(enable_eye_detect),
            "enable_af_point_detect": bool(enable_af_point_detect),
            "cancelled": bool(cancelled),
            "model": str(model or "x").lower(),
            "target_size": int(target_size or 640),
            "burst_min_count": int(burst_min_count or 1),
            "burst_fps": int(burst_fps or 0),
            "reserve_cpu": int(reserve_cpu or 0),
            "per_file_timeout_sec": int(per_file_timeout_sec or 0),
        },
    }


_SUBJECT_DETECTOR_INSTANCE = None
_SUBJECT_DETECTOR_LOCK = threading.Lock()
_SUBJECT_DETECT_PROCESS_EXECUTOR: ProcessPoolExecutor | None = None
_SUBJECT_DETECT_PROCESS_LOCK = threading.Lock()


def _subject_detect_should_use_subprocess(err: str) -> bool:
    s = str(err or "")
    if not s:
        return False
    low = s.lower()
    if "缺少依赖" in s:
        return True
    if ("pytorch" in low) or ("torch" in low) or ("ultralytics" in low):
        return True
    if ("c10.dll" in low) or ("winerror 1114" in low) or ("winerror" in low and "1114" in low):
        return True
    if ("dll" in low and "load" in low) or ("dll" in low and "初始化" in s):
        return True
    return False


def _get_subject_detect_process_executor() -> ProcessPoolExecutor:
    global _SUBJECT_DETECT_PROCESS_EXECUTOR
    with _SUBJECT_DETECT_PROCESS_LOCK:
        if _SUBJECT_DETECT_PROCESS_EXECUTOR is not None:
            return _SUBJECT_DETECT_PROCESS_EXECUTOR
        try:
            ctx = mp.get_context("spawn")
            _SUBJECT_DETECT_PROCESS_EXECUTOR = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
        except Exception:
            _SUBJECT_DETECT_PROCESS_EXECUTOR = ProcessPoolExecutor(max_workers=1)
        return _SUBJECT_DETECT_PROCESS_EXECUTOR


def _subject_detect_one(det, image_path: str, targets):
    try:
        from utils.log_manager import LogManager
    except Exception:
        LogManager = None
    try:
        from utils.exif.camera_af_point import get_camera_af_center_point_or_none
    except Exception as e:
        if LogManager is not None:
            try:
                LogManager.instance().debug(f"[对焦点] 导入camera_af_point模块失败: {e}")
            except Exception:
                pass
        get_camera_af_center_point_or_none = None
    cam_fp = None
    if callable(get_camera_af_center_point_or_none):
        try:
            cam_fp = get_camera_af_center_point_or_none(str(image_path or ""))
            if LogManager is not None:
                try:
                    LogManager.instance().debug(f"[对焦点] 获取相机对焦点结果: path={image_path} cam_fp={'Y' if cam_fp else 'N'} value={cam_fp}")
                except Exception:
                    pass
        except Exception as e:
            if LogManager is not None:
                try:
                    LogManager.instance().debug(f"[对焦点] 获取相机对焦点异常: path={image_path} error={e}")
                except Exception:
                    pass
            cam_fp = None
    else:
        if LogManager is not None:
            try:
                LogManager.instance().debug(f"[对焦点] get_camera_af_center_point_or_none不可用")
            except Exception:
                pass

    focus_requested = False
    if targets is not None:
        try:
            focus_requested = ("focus_point_orig" in targets) or ("focus_point" in targets)
        except Exception:
            focus_requested = False
    if targets is None:
        targets = ["pos", "bbox_orig"]
    try:
        if LogManager is not None:
            LogManager.instance().debug(f"[对焦点] 请求对焦点: path={image_path} cam_fp={'Y' if cam_fp else 'N'} targets={targets} focus_requested={focus_requested}")
    except Exception:
        pass
    try:
        info = det.analyze_file(str(image_path), targets=list(targets or []), af_focus_point=cam_fp)
    except Exception as e:
        try:
            cur_dev = str(getattr(det, "device", "cpu") or "cpu")
        except Exception:
            cur_dev = "cpu"
        if cur_dev != "cpu":
            try:
                det.device = "cpu"
            except Exception:
                pass
            try:
                info = det.analyze_file(str(image_path), targets=list(targets or []), af_focus_point=cam_fp)
            except Exception as e2:
                return None, None, None, str(e2)
        else:
            return None, None, None, str(e)
    if not isinstance(info, dict):
        return None, None, None, ""
    fp = cam_fp
    try:
        if LogManager is not None and focus_requested:
            LogManager.instance().debug(f"[对焦点] 返回对焦点: path={image_path} cam_fp={'Y' if cam_fp else 'N'} out_fp={'Y' if fp else 'N'}")
    except Exception:
        pass
    return info.get("bbox_orig"), fp, info.get("pos"), str(info.get("_error") or "")


def _subject_detect_warmup_in_subprocess(targets):
    try:
        import cv2
        if hasattr(cv2, "ocl"):
            try:
                cv2.ocl.setUseOpenCL(False)
            except Exception:
                pass
    except Exception:
        pass
    try:
        _get_subject_detector(targets)
        return True
    except Exception:
        return False


def _subject_detect_one_in_subprocess(image_path: str, targets):
    try:
        import cv2
        if hasattr(cv2, "ocl"):
            try:
                cv2.ocl.setUseOpenCL(False)
            except Exception:
                pass
    except Exception:
        pass
    try:
        det = _get_subject_detector(targets)
    except Exception as e:
        return None, None, None, str(e)
    try:
        return _subject_detect_one(det, str(image_path or ""), targets)
    except Exception as e:
        return None, None, None, str(e)


def _get_subject_detector(targets: Optional[Sequence[str]] = None):
    global _SUBJECT_DETECTOR_INSTANCE
    with _SUBJECT_DETECTOR_LOCK:
        if _SUBJECT_DETECTOR_INSTANCE is not None:
            return _SUBJECT_DETECTOR_INSTANCE
        from core.detectors.bird_focus_detector import BirdFocusDetector

        model = "x"
        target_size = 640
        initial_conf = 0.15
        use_gpu = True
        try:
            from utils.setting.settings_manager import SettingsManager

            sm = SettingsManager.instance()
            model = str(sm.get("focus_detect/model", "x") or "x").lower()
            target_size = int(sm.get("focus_detect/target_size", 640) or 640)
            initial_conf = float(sm.get("focus_detect/initial_conf", 0.15) or 0.15)
            use_gpu = bool(sm.get("focus_detect/use_gpu", True))
        except Exception:
            pass
        model_path = _resolve_valid_yolo_seg_model_path(model)
        det = BirdFocusDetector(
            str(model_path),
            target_size=int(target_size or 640),
            initial_conf=float(initial_conf or 0.15),
            multi_check=False,
            exp_frame_check=False,
            save_output=False,
            print_focus_point=False,
        )
        try:
            det.enable_scaled_cache(True)
        except Exception:
            pass
        try:
            effective_gpu = bool(use_gpu) and bool(_is_focus_cuda_usable())
            det.device = "cuda" if bool(effective_gpu) else "cpu"
        except Exception:
            pass
        try:
            if not bool(locals().get("effective_gpu", False)):
                from utils.system.gpu_utils import GPUScaler
                GPUScaler.set_suspended(True)
        except Exception:
            pass
        _SUBJECT_DETECTOR_INSTANCE = det
        return det


class _SubjectDetectService:
    _instance: Optional["_SubjectDetectService"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._queue: "queue.Queue[tuple[str, Sequence[str], Optional[Future], Any, Any]]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @classmethod
    def get_instance(cls) -> "_SubjectDetectService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def warmup(self) -> Future:
        future: Future = Future()
        self._queue.put(("warmup", [], future, None, None))
        return future

    def submit_one(self, image_path: str, callback=None, targets=None) -> Future:
        future: Future = Future()
        self._queue.put(("one", [str(image_path or "")], future, callback, targets))
        return future

    def submit_many(self, image_paths: Sequence[str], callback=None, targets=None) -> Future:
        future: Future = Future()
        self._queue.put(("many", [str(p) for p in (image_paths or []) if p], future, callback, targets))
        return future

    def _run(self):
        while True:
            kind, paths, future, callback, targets = self._queue.get()
            try:
                if kind == "warmup":
                    try:
                        _get_subject_detector(targets)
                        ok = True
                    except Exception as e:
                        if _subject_detect_should_use_subprocess(str(e)):
                            try:
                                ex = _get_subject_detect_process_executor()
                                ok = bool(ex.submit(_subject_detect_warmup_in_subprocess, targets).result())
                            except Exception:
                                ok = False
                        else:
                            ok = False
                    if future is not None and not future.done():
                        future.set_result(bool(ok))
                    continue

                det = None
                init_err = ""
                try:
                    det = _get_subject_detector(targets)
                except Exception as e:
                    init_err = str(e)
                if kind == "one":
                    p = paths[0] if paths else ""
                    bbox = fp = pos = None
                    err = ""
                    if det is None:
                        err = init_err
                    else:
                        bbox, fp, pos, err = _subject_detect_one(det, p, targets)
                    if (det is None or _subject_detect_should_use_subprocess(err)) and p:
                        try:
                            ex = _get_subject_detect_process_executor()
                            bbox, fp, pos, err = ex.submit(_subject_detect_one_in_subprocess, p, targets).result()
                        except Exception as e:
                            bbox = fp = pos = None
                            err = str(e)
                    if future is not None and not future.done():
                        future.set_result({"bbox": bbox, "focus_point": fp, "position": pos})
                    if callable(callback):
                        callback(p, bbox, fp, pos, err)
                    continue

                results: Dict[str, Dict[str, Any]] = {}
                for p in paths:
                    bbox = fp = pos = None
                    err = ""
                    if det is None:
                        err = init_err
                    else:
                        bbox, fp, pos, err = _subject_detect_one(det, p, targets)
                    if (det is None or _subject_detect_should_use_subprocess(err)) and p:
                        try:
                            ex = _get_subject_detect_process_executor()
                            bbox, fp, pos, err = ex.submit(_subject_detect_one_in_subprocess, p, targets).result()
                        except Exception as e:
                            bbox = fp = pos = None
                            err = str(e)
                    results[p] = {"bbox": bbox, "focus_point": fp, "position": pos, "err": err}
                    if callable(callback):
                        callback(p, bbox, fp, pos, err)
                if future is not None and not future.done():
                    future.set_result(results)
            except Exception as e:
                if future is not None and not future.done():
                    try:
                        future.set_exception(e)
                    except Exception:
                        pass
                if callable(callback):
                    for p in paths:
                        try:
                            callback(p, None, None, None, str(e))
                        except Exception:
                            pass
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass


def detect_subject_bbox_async(image_path: str, callback=None, targets=None) -> Future:
    return _SubjectDetectService.get_instance().submit_one(image_path, callback=callback, targets=targets)


def detect_subject_bbox_multi_async(image_paths: Sequence[str], callback=None, targets=None) -> Future:
    return _SubjectDetectService.get_instance().submit_many(image_paths, callback=callback, targets=targets)


def warmup_subject_detector_async() -> Future:
    return _SubjectDetectService.get_instance().warmup()
