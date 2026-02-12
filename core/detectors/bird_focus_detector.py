from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import hashlib
import json
import os
import threading
import time

import rawpy
import torch
import cv2
import numpy as np
import exifread
from ultralytics import YOLO

import utils.file.file as FileUtils
from utils.system.gpu_utils import GPUScaler
from PyQt6.QtGui import QImage
from utils.log_manager import LogManager
from utils.system.stderr_suppressor import suppress_stderr_fd

_debug_settings = None
_scaled_cache_lock = threading.Lock()


def _get_project_root() -> str:
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    except Exception:
        return os.getcwd()


def get_focus_scaled_cache_dir() -> str:
    try:
        return os.path.join(_get_project_root(), "data", "cache", "focus_scaled")
    except Exception:
        return ""


def _is_focus_save_output_enabled() -> bool:
    global _debug_settings
    if _debug_settings is None:
        try:
            from utils.setting.settings_manager import SettingsManager

            _debug_settings = SettingsManager()
        except Exception:
            _debug_settings = False
    if not _debug_settings:
        return False
    try:
        return bool(_debug_settings.get("debug/focus_save_output", False))
    except Exception:
        return False


def _get_focus_save_output_root() -> str:
    global _debug_settings
    if _debug_settings is None:
        try:
            from utils.setting.settings_manager import SettingsManager

            _debug_settings = SettingsManager()
        except Exception:
            _debug_settings = False
    if not _debug_settings:
        return ""
    try:
        configured = str(_debug_settings.get("debug/focus_save_output_dir", "") or "").strip()
    except Exception:
        configured = ""

    if configured:
        try:
            if os.path.isabs(configured):
                return configured
            return os.path.abspath(os.path.join(_get_project_root(), configured))
        except Exception:
            return configured

    try:
        return os.path.join(_get_project_root(), "data", "debug", "focus_output")
    except Exception:
        return ""


def _save_focus_debug_image(vis_img: np.ndarray, filename: str):
    if not _is_focus_save_output_enabled():
        return
    output_root = _get_focus_save_output_root()
    if not output_root:
        return
    try:
        out_dir = os.path.join(output_root, "result_mark")
        os.makedirs(out_dir, exist_ok=True)
        stem, ext = os.path.splitext(str(filename or ""))
        ext_only = str(ext or "").lstrip(".")
        if ext_only:
            out_name = f"analyzed_{stem}_{ext_only}.jpg"
        else:
            out_name = f"analyzed_{stem}.jpg"
        save_path = os.path.join(out_dir, out_name)
        cv2.imencode(".jpg", vis_img)[1].tofile(save_path)
    except Exception:
        pass

class BirdFocusDetector:
    def __init__(
        self,
        model_path: str = "yolo26n-seg.pt",
        *,
        target_size: int = 512,
        initial_conf: float = 0.15,
        sharp_threshold: int = 60,
        norm_sharp_threshold: int = 110,
        good_contrast_threshold: float = 1.8,
        normal_contrast_threshold: float = 0.8,
        too_small_threshold: float = 0.003,
        minimal_threshold: float = 0.001,
        multi_check: bool = True,
        exp_frame_check: bool = True,
        save_output: bool = True,
        print_focus_point: bool = True,
    ):
        self.model_path = model_path
        self.device = self._select_device()
        self.model = YOLO(model_path, verbose=False)

        self.target_size = target_size
        try:
            v = float(initial_conf)
        except Exception:
            v = 0.15
        if not np.isfinite(v):
            v = 0.15
        self.initial_conf = float(max(0.0, min(1.0, v)))
        self.sharp_threshold = sharp_threshold
        self.norm_sharp_threshold = norm_sharp_threshold
        self.good_contrast_threshold = good_contrast_threshold
        self.normal_contrast_threshold = normal_contrast_threshold
        self.too_small_threshold = too_small_threshold
        self.minimal_threshold = minimal_threshold
        self.multi_check = multi_check
        self.exp_frame_check = exp_frame_check
        self.save_output = save_output
        self.print_focus_point = print_focus_point
        self.output_path = "debug"
        self._scaled_cache_enabled = False
        self._scaled_cache_dir = get_focus_scaled_cache_dir()
        self._scaled_cache_quality = 90

    def enable_scaled_cache(self, enabled: bool = True, cache_dir: str | None = None):
        self._scaled_cache_enabled = bool(enabled)
        if cache_dir is not None:
            try:
                self._scaled_cache_dir = str(cache_dir or "")
            except Exception:
                self._scaled_cache_dir = ""
        return self

    @staticmethod
    def _select_device():
        try:
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def _get_scaled_cache_max_count(self) -> int:
        try:
            from utils.setting.settings_manager import SettingsManager

            sm = SettingsManager()
            v = int(sm.get("import/cache_size", 500))
            return max(50, v)
        except Exception:
            return 500

    def _scaled_cache_key(self, image_path: str) -> str:
        try:
            st = os.stat(image_path)
            token = f"{image_path}|{int(st.st_size)}|{int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))}|{int(self.target_size)}"
        except Exception:
            token = f"{image_path}|0|0|{int(self.target_size)}"
        return hashlib.sha1(token.encode("utf-8", errors="ignore")).hexdigest()

    def _scaled_cache_paths(self, key: str) -> tuple[str, str]:
        base = str(getattr(self, "_scaled_cache_dir", "") or "")
        return os.path.join(base, f"{key}.jpg"), os.path.join(base, f"{key}.json")

    def _scaled_cache_try_load(self, image_path: str):
        if not bool(getattr(self, "_scaled_cache_enabled", False)):
            return None
        cache_dir = str(getattr(self, "_scaled_cache_dir", "") or "")
        if not cache_dir:
            return None
        key = self._scaled_cache_key(image_path)
        jpg_path, meta_path = self._scaled_cache_paths(key)
        try:
            if not os.path.isfile(jpg_path) or not os.path.isfile(meta_path):
                return None
        except Exception:
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = None
        try:
            buf = np.fromfile(jpg_path, dtype=np.uint8)
            with suppress_stderr_fd():
                img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:
            img = None
        if img is None or not isinstance(img, np.ndarray) or img.size <= 0:
            return None
        try:
            os.utime(jpg_path, None)
        except Exception:
            pass
        return img, meta

    def _scaled_cache_save(self, image_path: str, scaled_img: np.ndarray, orig_w: int, orig_h: int):
        if not bool(getattr(self, "_scaled_cache_enabled", False)):
            return
        cache_dir = str(getattr(self, "_scaled_cache_dir", "") or "")
        if not cache_dir:
            return
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception:
            return
        key = self._scaled_cache_key(image_path)
        jpg_path, meta_path = self._scaled_cache_paths(key)
        try:
            encoded = cv2.imencode(".jpg", scaled_img, [int(cv2.IMWRITE_JPEG_QUALITY), int(getattr(self, "_scaled_cache_quality", 90))])[1]
        except Exception:
            return
        tmp = f"{jpg_path}.tmp.{os.getpid()}"
        tmp_meta = f"{meta_path}.tmp.{os.getpid()}"
        try:
            with _scaled_cache_lock:
                try:
                    if os.path.isfile(jpg_path) and os.path.isfile(meta_path):
                        return
                except Exception:
                    pass
                try:
                    encoded.tofile(tmp)
                    meta = {"orig_w": int(orig_w or 0), "orig_h": int(orig_h or 0)}
                    with open(tmp_meta, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False)
                    os.replace(tmp, jpg_path)
                    os.replace(tmp_meta, meta_path)
                finally:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except Exception:
                        pass
                    try:
                        if os.path.exists(tmp_meta):
                            os.remove(tmp_meta)
                    except Exception:
                        pass
        finally:
            self._scaled_cache_enforce_limit()

    def _scaled_cache_enforce_limit(self):
        if not bool(getattr(self, "_scaled_cache_enabled", False)):
            return
        cache_dir = str(getattr(self, "_scaled_cache_dir", "") or "")
        if not cache_dir:
            return
        try:
            max_count = int(self._get_scaled_cache_max_count())
        except Exception:
            max_count = 500
        if max_count <= 0:
            return
        try:
            entries = []
            for name in os.listdir(cache_dir):
                if not name.lower().endswith(".jpg"):
                    continue
                p = os.path.join(cache_dir, name)
                try:
                    ts = os.path.getmtime(p)
                except Exception:
                    ts = 0.0
                entries.append((ts, p))
        except Exception:
            return
        if len(entries) <= max_count:
            return
        entries.sort(key=lambda x: x[0])
        remove_n = max(0, len(entries) - max_count)
        for _, jpg_path in entries[:remove_n]:
            try:
                meta_path = os.path.splitext(jpg_path)[0] + ".json"
            except Exception:
                meta_path = ""
            try:
                if os.path.isfile(jpg_path):
                    os.remove(jpg_path)
            except Exception:
                pass
            if meta_path:
                try:
                    if os.path.isfile(meta_path):
                        os.remove(meta_path)
                except Exception:
                    pass

    def _resize_for_target(self, image: np.ndarray, target_width: int):
        h, w = image.shape[:2]
        if w <= target_width:
            return image
        new_h = int(h * (float(target_width) / float(w)))
        if new_h <= 0:
            return image
        try:
            if isinstance(image, np.ndarray) and image.size > 0:
                rgb = None
                try:
                    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                except Exception:
                    rgb = None
                if rgb is not None:
                    hh, ww = rgb.shape[:2]
                    bpl = int(3 * ww)
                    qimg = QImage(rgb.data, ww, hh, bpl, QImage.Format.Format_RGB888).copy()
                    scaled = GPUScaler.scale_qimage(qimg, int(target_width), int(new_h), keep_aspect=False, fast_mode=True)
                    if scaled is not None and not scaled.isNull():
                        src = scaled.convertToFormat(QImage.Format.Format_RGB888)
                        sw = int(src.width())
                        sh = int(src.height())
                        if sw > 0 and sh > 0:
                            bytes_per_line = int(src.bytesPerLine())
                            ptr = src.bits()
                            ptr.setsize(sh * bytes_per_line)
                            arr = np.frombuffer(ptr, np.uint8).reshape((sh, bytes_per_line))
                            arr = arr[:, : sw * 3].reshape((sh, sw, 3))
                            try:
                                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                            except Exception:
                                return image
        except Exception:
            pass
        return cv2.resize(image, (int(target_width), int(new_h)), interpolation=cv2.INTER_AREA)

    def load_image_scaled_for_detection(self, image_path: str):
        cached = self._scaled_cache_try_load(image_path)
        if cached is not None:
            img_small, meta = cached
            orig_w = 0
            orig_h = 0
            try:
                if isinstance(meta, dict):
                    orig_w = int(meta.get("orig_w") or 0)
                    orig_h = int(meta.get("orig_h") or 0)
            except Exception:
                orig_w = 0
                orig_h = 0
            if orig_w > 0 and orig_h > 0:
                h, w = img_small.shape[:2]
                scale_x = float(orig_w) / float(max(1, w))
                scale_y = float(orig_h) / float(max(1, h))
                return img_small, scale_x, scale_y, orig_w, orig_h

        image = self.load_image_for_detection(image_path)
        if image is None:
            return None, 1.0, 1.0, 0, 0
        orig_h, orig_w = image.shape[:2]
        img_small = self._resize_for_target(image, int(self.target_size or 640))
        h, w = img_small.shape[:2]
        scale_x = float(orig_w) / float(max(1, w))
        scale_y = float(orig_h) / float(max(1, h))
        try:
            self._scaled_cache_save(image_path, img_small, int(orig_w), int(orig_h))
        except Exception:
            pass
        return img_small, float(scale_x), float(scale_y), int(orig_w), int(orig_h)

    def _run_model(self, source, **kwargs):
        used_device = str(getattr(self, "device", "cpu") or "cpu")
        fallback = False
        total_dt = 0.0
        out = None
        t0 = time.perf_counter()
        try:
            out = self.model(source, device=used_device, **kwargs)
        except Exception:
            if used_device != "cpu":
                fallback = True
                self.device = "cpu"
                used_device = "cpu"
                out = self.model(source, device="cpu", **kwargs)
            else:
                raise
        finally:
            try:
                total_dt = float(time.perf_counter() - float(t0))
            except Exception:
                total_dt = 0.0
            try:
                self._prof_model_calls = int(getattr(self, "_prof_model_calls", 0) or 0) + 1
            except Exception:
                self._prof_model_calls = 1
            try:
                self._prof_model_s = float(getattr(self, "_prof_model_s", 0.0) or 0.0) + float(total_dt)
            except Exception:
                self._prof_model_s = float(total_dt)
            try:
                self._prof_model_max_s = float(max(float(getattr(self, "_prof_model_max_s", 0.0) or 0.0), float(total_dt)))
            except Exception:
                self._prof_model_max_s = float(total_dt)
            if fallback:
                try:
                    self._prof_model_fallback = int(getattr(self, "_prof_model_fallback", 0) or 0) + 1
                except Exception:
                    self._prof_model_fallback = 1
            if total_dt >= 0.8:
                try:
                    h = w = 0
                    try:
                        h, w = source.shape[:2]
                    except Exception:
                        h = w = 0
                    conf = kwargs.get("conf", None)
                    LogManager.instance().debug(f"[FocusDetect] model_slow elapsed_s={total_dt:.3f} device={used_device} fallback={int(bool(fallback))} conf={conf} shape={h}x{w}")
                except Exception:
                    pass
        return out

    @staticmethod
    def load_image(file_path):
        ext = os.path.splitext(file_path)[1].lower()

        try:
            if ext.upper() in FileUtils.raw_exts:
                with rawpy.imread(file_path) as raw:
                    try:
                        thumb = raw.extract_thumb()
                    except rawpy.LibRawNoThumbnailError:
                        try:
                            LogManager.instance().debug(f"{os.path.basename(file_path)}: 无缩略图")
                        except Exception:
                            pass
                        return None

                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        img_array = np.frombuffer(thumb.data, dtype=np.uint8)
                        with suppress_stderr_fd():
                            image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                        return image
                    return None

            if ext.upper() in FileUtils.img_exts:
                img_array = np.fromfile(file_path, dtype=np.uint8)
                with suppress_stderr_fd():
                    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        except Exception as e:
            try:
                LogManager.instance().warning(f"读取失败 {file_path}: {e}")
            except Exception:
                pass
            return None

        return None

    def extract_thumbnail(self, file_path):
        try:
            with open(file_path, "rb") as f:
                tags = exifread.process_file(f, details=False)
                if "JPEGThumbnail" in tags:
                    thumb_data = tags["JPEGThumbnail"]
                    img_array = np.frombuffer(thumb_data, dtype=np.uint8)
                    with suppress_stderr_fd():
                        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except ImportError:
            pass
        except Exception as e:
            try:
                LogManager.instance().warning(f"EXIF 读取失败: {e}")
            except Exception:
                pass
        return None

    def safe_get_masks_xy_list(self, masks):
        if masks is None:
            return []
        return list(masks.xy)

    def enhance_contrast(self, gray_img):
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray_img)

    def is_exp_frame(self, poly, shape, margin=1):
        if poly is None or len(poly) == 0:
            return False
        h, w = shape[:2]
        x_min = poly[:, 0].min()
        x_max = poly[:, 0].max()
        y_min = poly[:, 1].min()
        y_max = poly[:, 1].max()
        return (x_min <= margin) or (y_min <= margin) or (x_max >= w - margin - 1) or (y_max >= h - margin - 1)

    def calculate_sharpness_score(
        self,
        laplacian,
        mask,
        min_pixels=500,
        percentile=95,
        multiplier=1.2,
        erosion_kernel=(5, 5),
        erosion_iter=1,
        preprocess_mask=True,
    ):
        if preprocess_mask and erosion_iter > 0:
            binary_mask = (mask > 0).astype(np.uint8) * 255
            kernel = np.ones(erosion_kernel, np.uint8)
            processed_mask = cv2.erode(binary_mask, kernel, iterations=erosion_iter)
        else:
            processed_mask = mask

        valid_pixels = np.abs(laplacian[processed_mask > 0])

        if len(valid_pixels) < min_pixels:
            return 0

        limit_val = np.percentile(valid_pixels, percentile)
        trimmed = valid_pixels[valid_pixels <= limit_val]
        if len(trimmed) > 0:
            return np.mean(trimmed**2) * multiplier
        return 0

    def calculate_texture_richness(self, gray_img: np.ndarray, bird_mask: np.ndarray, background_mask: np.ndarray | None = None) -> Dict[str, float]:
        if gray_img is None or not isinstance(gray_img, np.ndarray) or gray_img.size <= 0:
            return {"edge_density": 0.0, "edge_density_bg": 0.0, "edge_density_ratio": 1.0, "entropy": 0.0, "entropy_bg": 0.0, "entropy_ratio": 1.0}
        if bird_mask is None or not isinstance(bird_mask, np.ndarray) or bird_mask.size <= 0:
            return {"edge_density": 0.0, "edge_density_bg": 0.0, "edge_density_ratio": 1.0, "entropy": 0.0, "entropy_bg": 0.0, "entropy_ratio": 1.0}

        try:
            work = gray_img
            if work.dtype != np.uint8:
                work = np.clip(work, 0, 255).astype(np.uint8)
            sx = cv2.Sobel(work, cv2.CV_32F, 1, 0, ksize=3)
            sy = cv2.Sobel(work, cv2.CV_32F, 0, 1, ksize=3)
            mag = cv2.magnitude(sx, sy)
        except Exception:
            return {"edge_density": 0.0, "edge_density_bg": 0.0, "edge_density_ratio": 1.0, "entropy": 0.0, "entropy_bg": 0.0, "entropy_ratio": 1.0}

        bird = None
        bg = None
        try:
            bird = mag[bird_mask > 0]
        except Exception:
            bird = None
        if background_mask is not None:
            try:
                bg = mag[background_mask > 0]
            except Exception:
                bg = None

        def _entropy(vals: np.ndarray) -> float:
            try:
                if vals is None or not isinstance(vals, np.ndarray) or vals.size <= 0:
                    return 0.0
                v = vals.astype(np.float32, copy=False)
                lo = float(np.min(v))
                hi = float(np.max(v))
                if not (hi > lo):
                    return 0.0
                hist = np.histogram(v, bins=32, range=(lo, hi))[0].astype(np.float64)
                s = float(hist.sum())
                if s <= 0:
                    return 0.0
                p = hist / s
                p = p[p > 0]
                return float(-(p * np.log2(p)).sum())
            except Exception:
                return 0.0

        edge_thr = 0.0
        try:
            ref = bg if (bg is not None and isinstance(bg, np.ndarray) and bg.size >= 200) else mag.reshape(-1)
            if ref is not None and isinstance(ref, np.ndarray) and ref.size > 0:
                edge_thr = float(np.percentile(ref, 85.0))
        except Exception:
            edge_thr = 0.0

        def _edge_density(vals: np.ndarray) -> float:
            try:
                if vals is None or not isinstance(vals, np.ndarray) or vals.size <= 0:
                    return 0.0
                if edge_thr <= 0:
                    return 0.0
                return float(np.mean(vals > edge_thr))
            except Exception:
                return 0.0

        ed_bird = _edge_density(bird)
        ed_bg = _edge_density(bg)
        ent_bird = _entropy(bird)
        ent_bg = _entropy(bg)
        return {
            "edge_density": float(ed_bird),
            "edge_density_bg": float(ed_bg),
            "edge_density_ratio": float(ed_bird / (ed_bg + 1e-6)) if ed_bg > 0 else (float(ed_bird / 1e-6) if ed_bird > 0 else 1.0),
            "entropy": float(ent_bird),
            "entropy_bg": float(ent_bg),
            "entropy_ratio": float(ent_bird / (ent_bg + 1e-6)) if ent_bg > 0 else (float(ent_bird / 1e-6) if ent_bird > 0 else 1.0),
        }

    def detect_motion_blur(self, gray_img, mask=None):
        if mask is not None:
            work = cv2.bitwise_and(gray_img, gray_img, mask=mask)
        else:
            work = gray_img
        lap = cv2.Laplacian(work, cv2.CV_64F)
        lap_var = float(lap.var())
        sx = cv2.Sobel(work, cv2.CV_64F, 1, 0, ksize=3)
        sy = cv2.Sobel(work, cv2.CV_64F, 0, 1, ksize=3)
        ex = float(np.mean(np.abs(sx)))
        ey = float(np.mean(np.abs(sy)))
        dir_ratio = abs(ex - ey) / (ex + ey + 1e-6)
        try:
            jxx = float(np.mean(sx * sx))
            jyy = float(np.mean(sy * sy))
            jxy = float(np.mean(sx * sy))
            coherence = (((jxx - jyy) * (jxx - jyy) + 4.0 * jxy * jxy) ** 0.5) / (jxx + jyy + 1e-6)
        except Exception:
            coherence = 0.0
        motion_flag = (lap_var < 25) and (dir_ratio > 0.15)
        severity = "none"
        try:
            if bool(motion_flag):
                severity = "heavy" if float(lap_var) < 10.0 else "light"
        except Exception:
            severity = "none"
        try:
            motion_score = float(max(float(dir_ratio), float(coherence))) * float(max(0.0, min(1.0, 1.0 - (float(lap_var) / 25.0))))
        except Exception:
            motion_score = 0.0
        return {"motion": motion_flag, "severity": severity, "score": motion_score, "lap_var": lap_var, "dir_ratio": dir_ratio, "coherence": float(coherence), "energy_x": ex, "energy_y": ey}

    def load_image_for_detection(self, image_path: str):
        image = BirdFocusDetector.load_image(image_path)
        if image is None:
            image = self.extract_thumbnail(image_path)
        return image

    def resize_for_scoring(self, image: np.ndarray) -> Tuple[np.ndarray, float, float]:
        target_width = self.target_size
        h, w = image.shape[:2]
        scale_x = 1.0
        scale_y = 1.0
        if w > target_width:
            scale = target_width / w
            new_h = int(h * scale)
            if new_h <= 0:
                return image, scale_x, scale_y
            scale_x = w / target_width
            scale_y = h / new_h
            image = cv2.resize(image, (target_width, new_h), interpolation=cv2.INTER_AREA)
        return image, float(scale_x), float(scale_y)

    def segment_bird_contours(self, image: np.ndarray, filename: str, focus_point=None, image_path: str | None = None):
        t_all0 = time.perf_counter()
        t_exif_s = 0.0
        calls = 0
        last_tag = ""
        def _log_slow(tag: str):
            try:
                dt = float(time.perf_counter() - float(t_all0))
            except Exception:
                dt = 0.0
            if dt >= 1.0:
                try:
                    LogManager.instance().debug(
                        f"[FocusDetect] segment_slow elapsed_s={dt:.3f} calls={int(calls)} exif_s={float(t_exif_s):.3f} tag={str(tag or '')} file={str(filename or '')}"
                    )
                except Exception:
                    pass
        def _set_stats(tag: str):
            nonlocal last_tag
            last_tag = str(tag or "")
            try:
                self._prof_seg_calls = int(calls)
            except Exception:
                self._prof_seg_calls = 0
            try:
                self._prof_seg_exif_s = float(t_exif_s)
            except Exception:
                self._prof_seg_exif_s = 0.0
            try:
                self._prof_seg_tag = str(last_tag)
            except Exception:
                self._prof_seg_tag = str(last_tag)
        try:
            conf0 = float(getattr(self, "initial_conf", 0.15) or 0.15)
        except Exception:
            conf0 = 0.15
        if not np.isfinite(conf0):
            conf0 = 0.15
        conf0 = float(max(0.0, min(1.0, conf0)))
        results = self._run_model(image, conf=conf0, classes=[14], verbose=False, retina_masks=True)
        calls += 1

        if results and results[0].masks:
            masks_xy_list = self.safe_get_masks_xy_list(results[0].masks)
            results[0]._masks_xy_list = masks_xy_list
            _set_stats("first")
            _log_slow("first")
            return results, masks_xy_list

        def _try_focus_crop(conf: float):
            if focus_point is None:
                return None, []
            try:
                fx = float(getattr(focus_point, "get", lambda k, d=None: d)("x", None))
                fy = float(getattr(focus_point, "get", lambda k, d=None: d)("y", None))
            except Exception:
                return None, []
            if not np.isfinite(fx) or not np.isfinite(fy):
                return None, []
            h, w = image.shape[:2]
            if w <= 1 or h <= 1:
                return None, []
            if 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0:
                cx = int(round(fx * float(w - 1)))
                cy = int(round(fy * float(h - 1)))
            else:
                cx = int(round(fx))
                cy = int(round(fy))
            cx = max(0, min(int(cx), int(w - 1)))
            cy = max(0, min(int(cy), int(h - 1)))
            crop_w, crop_h = max(2, int(w // 2)), max(2, int(h // 2))
            x1 = int(cx - crop_w // 2)
            y1 = int(cy - crop_h // 2)
            x1 = max(0, min(int(x1), int(w - crop_w)))
            y1 = max(0, min(int(y1), int(h - crop_h)))
            x2 = int(x1 + crop_w)
            y2 = int(y1 + crop_h)
            crop = image[y1:y2, x1:x2]
            if crop is None or crop.size <= 0:
                return None, []
            r0 = self._run_model(crop, conf=float(conf), classes=[14], verbose=False)
            if not r0 or not r0[0].masks:
                return r0, []
            m0 = self.safe_get_masks_xy_list(r0[0].masks)
            if not m0:
                return r0, []
            for i in range(len(m0)):
                mask_xy = m0[i]
                if mask_xy is not None and len(mask_xy) > 0:
                    mask_xy[:, 0] += x1
                    mask_xy[:, 1] += y1
                    mask_xy[:, 0] = np.clip(mask_xy[:, 0], 0, w - 1)
                    mask_xy[:, 1] = np.clip(mask_xy[:, 1], 0, h - 1)
            r0[0]._masks_xy_list = m0
            return r0, m0

        fp0 = focus_point
        if fp0 is None and image_path:
            try:
                from utils.exif.camera_af_point import get_camera_af_center_point_or_none
                _t0 = time.perf_counter()
                fp0 = get_camera_af_center_point_or_none(str(image_path))
                _t1 = time.perf_counter()
                try:
                    t_exif_s = float(_t1 - _t0)
                except Exception:
                    t_exif_s = 0.0
            except Exception:
                fp0 = None

        focus_point = fp0
        results_focus, masks_focus = _try_focus_crop(conf=0.05)
        if masks_focus:
            _set_stats("focus_crop")
            _log_slow("focus_crop")
            return results_focus, masks_focus
        if results_focus is not None:
            calls += 1

        results = self._run_model(image, conf=0.05, classes=[14], verbose=False)
        calls += 1
        if results and results[0].masks:
            masks_xy_list = self.safe_get_masks_xy_list(results[0].masks)
            results[0]._masks_xy_list = masks_xy_list
            _set_stats("low_conf_full")
            _log_slow("low_conf_full")
            return results, masks_xy_list

        if not self.multi_check:
            _set_stats("low_conf_full_nomask")
            _log_slow("low_conf_full_nomask")
            return results, []

        h, w = image.shape[:2]
        center_x, center_y = w // 2, h // 2
        crop_w, crop_h = w // 2, h // 2
        x1 = center_x - crop_w // 2
        y1 = center_y - crop_h // 2
        x1 = max(0, min(int(x1), int(w - crop_w)))
        y1 = max(0, min(int(y1), int(h - crop_h)))
        x2 = x1 + crop_w
        y2 = y1 + crop_h
        center_crop = image[y1:y2, x1:x2]
        results = self._run_model(center_crop, conf=0.05, classes=[14], verbose=False)
        calls += 1
        if not results or not results[0].masks:
            _set_stats("center_crop_nomask")
            _log_slow("center_crop_nomask")
            return results, []
        masks_xy_list = self.safe_get_masks_xy_list(results[0].masks)
        num_masks = len(masks_xy_list)
        if num_masks == 0:
            _set_stats("center_crop_empty")
            _log_slow("center_crop_empty")
            return results, []

        for i in range(num_masks):
            mask_xy = masks_xy_list[i]
            if mask_xy is not None and len(mask_xy) > 0:
                mask_xy[:, 0] += x1
                mask_xy[:, 1] += y1
                mask_xy[:, 0] = np.clip(mask_xy[:, 0], 0, w - 1)
                mask_xy[:, 1] = np.clip(mask_xy[:, 1], 0, h - 1)

        results[0]._masks_xy_list = masks_xy_list
        _set_stats("center_crop")
        _log_slow("center_crop")
        return results, masks_xy_list

    def detect_bird_contours(self, image: np.ndarray, filename: str = ""):
        return self.segment_bird_contours(image, filename)

    def score_birds(self, image: np.ndarray, results, masks_xy_list, filename: str):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = self.enhance_contrast(gray)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        abs_laplacian = np.abs(laplacian)
        global_hf_thr = None
        try:
            global_hf_thr = float(np.percentile(abs_laplacian.reshape(-1), 97))
        except Exception:
            global_hf_thr = None
        if global_hf_thr is None or not np.isfinite(global_hf_thr) or global_hf_thr <= 0:
            try:
                global_hf_thr = float(abs_laplacian.mean() + 1e-6)
            except Exception:
                global_hf_thr = 0.0

        global_mask = np.ones(gray.shape, dtype=np.uint8) * 255
        global_score = self.calculate_sharpness_score(
            laplacian,
            global_mask,
            min_pixels=300,
            percentile=95,
            multiplier=1.0,
            erosion_kernel=(2, 2),
            erosion_iter=0,
            preprocess_mask=False,
        )

        vis_img = image.copy()

        bird_stats: List[Dict[str, Any]] = []
        max_conf = 1.0
        try:
            if results and results[0].boxes is not None and len(results[0].boxes.conf) > 0:
                max_conf = float(results[0].boxes.conf.max())
        except Exception:
            max_conf = 1.0

        for i, mask_points in enumerate(masks_xy_list):
            isMinimal = False
            if mask_points is None or len(mask_points) == 0:
                continue

            single_mask = np.zeros(gray.shape, dtype=np.uint8)
            poly = mask_points.astype(int)
            cv2.fillPoly(single_mask, [poly], 255)

            raw_score = self.calculate_sharpness_score(
                laplacian,
                single_mask,
                min_pixels=300,
                percentile=95,
                multiplier=1.2,
                erosion_kernel=(2, 2),
                erosion_iter=1,
                preprocess_mask=True,
            )
            peak_score = 0.0
            hf_density = 0.0
            try:
                binary_mask = (single_mask > 0).astype(np.uint8) * 255
                processed_mask = cv2.erode(binary_mask, np.ones((2, 2), np.uint8), iterations=1)
                valid = abs_laplacian[processed_mask > 0]
                if valid.size >= 300:
                    try:
                        t = float(np.percentile(valid, 95))
                    except Exception:
                        t = None
                    if t is None or not np.isfinite(t) or t <= 0:
                        t = float(valid.mean() + 1e-6)
                    top = valid[valid >= t]
                    if top.size > 0:
                        peak_score = float(np.mean(top * top) * 1.2)
                    if global_hf_thr is not None and float(global_hf_thr) > 0:
                        hf_density = float(np.mean(valid >= float(global_hf_thr)))
            except Exception:
                peak_score = 0.0
                hf_density = 0.0

            if raw_score == 0:
                isMinimal = True

            if results and results[0].boxes is not None and len(results[0].boxes) > i:
                conf = float(results[0].boxes.conf[i])
            else:
                conf = 0.5

            conf_ratio = conf / max_conf if max_conf > 0 else 0
            penalty_factor = conf_ratio**2
            raw_score *= penalty_factor
            peak_score *= penalty_factor

            motion_info = self.detect_motion_blur(gray, mask=single_mask)
            if motion_info["motion"]:
                raw_score *= 0.1
                peak_score *= 0.1

            size_penalty = 1.0
            target_pixels = cv2.countNonZero(single_mask)
            total_pixels = gray.size
            area_ratio = target_pixels / total_pixels if total_pixels > 0 else 0.0

            if area_ratio < self.minimal_threshold:
                isMinimal = True
            elif area_ratio < self.too_small_threshold:
                size_penalty = (area_ratio / self.too_small_threshold) ** 1.5

            raw_score *= size_penalty
            peak_score *= size_penalty
            norm_score = (raw_score / global_score) * 100 if global_score > 0 else 0.0
            peak_norm_score = (peak_score / global_score) * 100 if global_score > 0 else 0.0
            x, y, w_box, h_box = cv2.boundingRect(poly.astype(np.int32))

            bird_stats.append(
                {
                    "score": raw_score,
                    "norm_score": norm_score,
                    "peak_score": float(peak_score),
                    "peak_norm_score": float(peak_norm_score),
                    "hf_density": float(hf_density),
                    "poly": poly,
                    "mask": single_mask,
                    "conf": conf,
                    "area_ratio": area_ratio,
                    "size_penalty": size_penalty,
                    "motion_info": motion_info,
                    "isMinimal": isMinimal,
                    "status": "None",
                    "bbox": (x, y, x + w_box, y + h_box),
                }
            )

        bird_stats.sort(key=lambda x: x["norm_score"], reverse=True)
        return bird_stats, gray, laplacian, float(global_score), vis_img

    def calculate_bird_score(self, image: np.ndarray, results, masks_xy_list, filename: str = ""):
        return self.score_birds(image, results, masks_xy_list, filename)

    def compute_background_score(self, laplacian: np.ndarray, global_score: float, bird_stats: Sequence[Dict[str, Any]]):
        if not bird_stats:
            return 0.0, 0.0, None, None

        best_bird = max(bird_stats, key=lambda x: x["score"])
        best_bird_mask = best_bird["mask"]
        kernel = np.ones((5, 5), np.uint8)
        eroded_best_bird_mask = cv2.erode(best_bird_mask, kernel, iterations=1)
        background_mask = cv2.bitwise_not(eroded_best_bird_mask)

        raw_bg_score = self.calculate_sharpness_score(
            laplacian,
            background_mask,
            min_pixels=300,
            percentile=95,
            multiplier=1.0,
            erosion_kernel=(2, 2),
            erosion_iter=0,
            preprocess_mask=False,
        )
        bg_score = (raw_bg_score / global_score) * 100 if global_score > 0 else 0.0
        return float(raw_bg_score), float(bg_score), background_mask, best_bird

    def compute_bird_position(self, target_bird: Dict[str, Any], image_shape):
        try:
            img_h, img_w = image_shape[:2]
            M = cv2.moments(target_bird["mask"])
            if M["m00"] != 0:
                cx, cy = (M["m10"] / M["m00"]), (M["m01"] / M["m00"])
            else:
                cx, cy = target_bird["poly"][0][0], target_bird["poly"][0][1]
            x_th1, x_th2 = img_w * 0.4, img_w * 0.6
            y_th1, y_th2 = img_h * 0.4, img_h * 0.6
            if cx < x_th1:
                pos_x = "L"
            elif cx > x_th2:
                pos_x = "R"
            else:
                pos_x = "C"
            if cy < y_th1:
                pos_y = "T"
            elif cy > y_th2:
                pos_y = "B"
            else:
                pos_y = "M"
            pos_map = {
                ("C", "C"): "Center",
                ("L", "C"): "Left",
                ("R", "C"): "Right",
                ("C", "T"): "Top",
                ("C", "B"): "Bottom",
                ("L", "T"): "LeftTop",
                ("L", "B"): "LeftBottom",
                ("R", "T"): "RightTop",
                ("R", "B"): "RightBottom",
                ("L", "M"): "Left",
                ("R", "M"): "Right",
                ("C", "M"): "Center",
            }
            return pos_map.get((pos_x, pos_y), "Center"), float(cx), float(cy)
        except Exception:
            return "Center", 0.0, 0.0

    def get_bird_position(self, bird_mask: np.ndarray, image_shape):
        try:
            img_h, img_w = image_shape[:2]
            M = cv2.moments(bird_mask)
            if M["m00"] != 0:
                cx, cy = (M["m10"] / M["m00"]), (M["m01"] / M["m00"])
            else:
                cx, cy = img_w * 0.5, img_h * 0.5

            x_th1, x_th2 = img_w * 0.4, img_w * 0.6
            y_th1, y_th2 = img_h * 0.4, img_h * 0.6

            if cx < x_th1:
                pos_x = "L"
            elif cx > x_th2:
                pos_x = "R"
            else:
                pos_x = "C"

            if cy < y_th1:
                pos_y = "T"
            elif cy > y_th2:
                pos_y = "B"
            else:
                pos_y = "M"

            pos_map = {
                ("C", "C"): "Center",
                ("L", "C"): "Left",
                ("R", "C"): "Right",
                ("C", "T"): "Top",
                ("C", "B"): "Bottom",
                ("L", "T"): "LeftTop",
                ("L", "B"): "LeftBottom",
                ("R", "T"): "RightTop",
                ("R", "B"): "RightBottom",
                ("L", "M"): "Left",
                ("R", "M"): "Right",
                ("C", "M"): "Center",
            }
            return pos_map.get((pos_x, pos_y), "Center"), float(cx), float(cy)
        except Exception:
            return "Center", 0.0, 0.0

    def judge_best_bird(
        self,
        bird_stats: List[Dict[str, Any]],
        gray: np.ndarray,
        laplacian: np.ndarray,
        global_score: float,
        raw_bg_score: float,
        bg_score: float,
        background_mask: np.ndarray,
        filename: str,
        output_path: str | None = None,
        vis_img: np.ndarray | None = None,
    ):
        if output_path is None:
            output_path = self.output_path

        base_threshold = self.sharp_threshold

        final_status = None
        final_score_correction = ""
        final_bird = None
        final_ratio = 0.0
        final_ratio_local = 0.0
        final_hf_ratio = 0.0
        final_hf_margin = 0.0
        final_ratio_best = 0.0

        img_h, img_w = gray.shape[:2]
        ring_w = max(3, int(max(img_w, img_h) * 0.01))
        if ring_w % 2 == 0:
            ring_w += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ring_w, ring_w))
        abs_laplacian = np.abs(laplacian)
        bg_hf_global = 0.0
        try:
            bg_vals = abs_laplacian[background_mask > 0]
            if bg_vals.size > 0:
                bg_hf_global = float(np.percentile(bg_vals, 95))
        except Exception:
            bg_hf_global = 0.0

        for target_bird in bird_stats:
            if target_bird is None:
                continue

            ratio = target_bird["norm_score"] / max(bg_score, 1e-6)
            ratio_local = ratio
            hf_ratio = 1.0
            hf_margin = 0.0

            try:
                if (not target_bird.get("isMinimal", False)) and (kernel is not None) and (abs_laplacian is not None):
                    ring = cv2.dilate(target_bird["mask"], kernel, iterations=1)
                    ring = cv2.subtract(ring, target_bird["mask"])
                    ring = cv2.bitwise_and(ring, background_mask)

                    bg_hf = bg_hf_global
                    if cv2.countNonZero(ring) > 0:
                        ring_std = cv2.meanStdDev(laplacian, mask=ring)[1][0][0]
                        ring_score_raw = ring_std * ring_std
                        ring_score_norm = (max(float(ring_score_raw), 1.0) / global_score) * 100 if global_score > 0 else 0.0
                        ratio_local = target_bird["norm_score"] / max(ring_score_norm, 1e-6)

                        try:
                            ring_vals = abs_laplacian[ring > 0]
                            if ring_vals.size >= 20:
                                bg_hf = float(np.percentile(ring_vals, 95))
                        except Exception:
                            bg_hf = bg_hf_global

                    try:
                        bird_vals = abs_laplacian[target_bird["mask"] > 0]
                        if bird_vals.size > 0:
                            if bird_vals.size >= 20:
                                bird_hf = float(np.percentile(bird_vals, 95))
                            else:
                                bird_hf = float(bird_vals.max())
                        else:
                            bird_hf = 0.0
                    except Exception:
                        bird_hf = 0.0

                    hf_ratio = bird_hf / (bg_hf + 1e-6)
                    hf_margin = bird_hf - bg_hf
            except Exception:
                pass

            partial_abs_sharp = False
            try:
                partial_abs_sharp = (
                    float(target_bird.get("peak_score", 0.0)) > float(base_threshold)
                    and float(target_bird.get("peak_norm_score", 0.0)) > float(self.norm_sharp_threshold)
                    and float(target_bird.get("hf_density", 0.0)) >= 0.01
                )
            except Exception:
                partial_abs_sharp = False

            is_abs_sharp = (
                (target_bird["score"] > base_threshold) and (target_bird["norm_score"] > self.norm_sharp_threshold)
            ) or partial_abs_sharp

            current_good_ratio = self.good_contrast_threshold
            current_normal_ratio = self.normal_contrast_threshold
            if global_score > 100:
                current_normal_ratio *= 1.2
                current_good_ratio *= 1.2

            score_correction = ""
            ratio_best = max(ratio, ratio_local)
            is_ratio_good = (ratio_best > current_normal_ratio) or (hf_ratio > 1.15) or (partial_abs_sharp and hf_ratio > 1.05)
            flat_bg = (raw_bg_score < (target_bird["score"] * 0.2)) or (bg_score < 20)
            if (not partial_abs_sharp) and flat_bg and (hf_ratio < 1.15 or hf_margin < 5) and target_bird["score"] < (base_threshold * 1.3):
                is_ratio_good = False
                score_correction = "Flat BG Penalty"
            is_focused = is_abs_sharp and is_ratio_good

            bak_is_sharp = raw_bg_score > (target_bird["score"] * 0.65)

            if target_bird["isMinimal"]:
                status = "Minimal"
            else:
                if is_focused:
                    status = "Sharp"
                else:
                    if bak_is_sharp and target_bird["score"] < base_threshold:
                        status = "Blurry"
                    else:
                        status = "Normal" if (partial_abs_sharp or (target_bird["score"] > base_threshold * 0.8)) else "Blurry"

            if self.exp_frame_check:
                if self.is_exp_frame(target_bird["poly"], gray.shape, margin=1):
                    if status in ("Sharp", "Normal"):
                        status = "ExpFrame"

            target_bird["status"] = status

            if status in ("Sharp", "Normal", "ExpFrame"):
                final_status = status
                final_score_correction = score_correction
                final_bird = target_bird
                final_ratio = ratio
                final_ratio_local = ratio_local
                final_hf_ratio = hf_ratio
                final_hf_margin = hf_margin
                final_ratio_best = ratio_best
                break

            if status in ("Blurry", "Minimal"):
                if final_bird is None:
                    final_status = status
                    final_score_correction = score_correction
                    final_bird = target_bird
                    final_ratio = ratio
                    final_ratio_local = ratio_local
                    final_hf_ratio = hf_ratio
                    final_hf_margin = hf_margin
                    final_ratio_best = ratio_best
                continue

        if _is_focus_save_output_enabled():
            try:
                output_root = str(output_path or "").strip() or _get_focus_save_output_root()
                if not output_root:
                    raise RuntimeError("no_output_root")

                if vis_img is None or not isinstance(vis_img, np.ndarray) or vis_img.size <= 0:
                    try:
                        vis_img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                    except Exception:
                        vis_img = None

                if vis_img is not None and isinstance(vis_img, np.ndarray) and vis_img.size > 0:
                    img_h, img_w = vis_img.shape[:2]

                    base_color = (180, 180, 180)
                    if isinstance(bird_stats, list):
                        for b in bird_stats:
                            try:
                                poly = b.get("poly")
                                if poly is None:
                                    continue
                                poly = np.asarray(poly, dtype=np.int32)
                                if poly.size <= 0:
                                    continue
                                cv2.polylines(vis_img, [poly], isClosed=True, color=base_color, thickness=1, lineType=cv2.LINE_AA)
                            except Exception:
                                continue

                    status = str(final_status or "NoBird")
                    status_color_map = {
                        "Sharp": (0, 200, 0),
                        "Normal": (220, 130, 20),
                        "Blurry": (0, 220, 220),
                        "Minimal": (200, 80, 200),
                        "ExpFrame": (245, 245, 245),
                        "NoBird": (120, 120, 120),
                    }
                    main_color = status_color_map.get(status, (0, 160, 255))
                    if final_bird is not None:
                        try:
                            poly = np.asarray(final_bird.get("poly"), dtype=np.int32)
                            if poly.size > 0:
                                cv2.polylines(vis_img, [poly], isClosed=True, color=main_color, thickness=3, lineType=cv2.LINE_AA)
                        except Exception:
                            pass

                        try:
                            x1, y1, x2, y2 = final_bird.get("bbox", (0, 0, 0, 0))
                            cv2.rectangle(vis_img, (int(x1), int(y1)), (int(x2), int(y2)), main_color, 2, lineType=cv2.LINE_AA)
                        except Exception:
                            pass

                        cx = img_w * 0.5
                        cy = img_h * 0.5
                        try:
                            mask = final_bird.get("mask")
                            if mask is not None:
                                M = cv2.moments(mask)
                                if float(M.get("m00", 0.0)) != 0.0:
                                    cx = float(M["m10"] / M["m00"])
                                    cy = float(M["m01"] / M["m00"])
                        except Exception:
                            pass
                        try:
                            cx_i, cy_i = int(cx + 0.5), int(cy + 0.5)
                            cv2.drawMarker(vis_img, (cx_i, cy_i), main_color, markerType=cv2.MARKER_CROSS, markerSize=18, thickness=2, line_type=cv2.LINE_AA)
                        except Exception:
                            pass

                        try:
                            font_scale_small = max(0.45, min(1.0, float(img_w) / 1200.0))
                            font_scale_large = max(0.65, min(1.25, float(img_w) / 900.0))
                            font_thickness_small = 1 if img_w < 1200 else 2
                            font_thickness_large = 2 if img_w < 1200 else 3
                            text_status = status or "Unknown"
                            score_correction = str(final_score_correction or "")
                            label1 = f"S:{float(final_bird.get('norm_score', 0.0)):.0f}({float(final_bird.get('score', 0.0)):.0f}/{float(final_bird.get('conf', 0.0)):.2f}) area_ratio {float(final_bird.get('area_ratio', 0.0)):.5f}"
                            label2 = f"R:{float(final_ratio_best):.2f} g:{float(final_ratio):.2f} l:{float(final_ratio_local):.2f} hf:{float(final_hf_ratio):.2f} motion:{bool((final_bird.get('motion_info') or {}).get('motion', False))}"
                            label3 = f"{text_status} {score_correction}".strip()
                            if "pos" in final_bird:
                                try:
                                    label3 += f" pos:{str(final_bird.get('pos') or '')}"
                                except Exception:
                                    pass

                            def _put_text(s: str, x: int, y: int, scale: float, thickness: int):
                                cv2.putText(vis_img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2, lineType=cv2.LINE_AA)
                                cv2.putText(vis_img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, main_color, thickness, lineType=cv2.LINE_AA)

                            (w1, h1), _ = cv2.getTextSize(label1, cv2.FONT_HERSHEY_SIMPLEX, font_scale_small, font_thickness_small)
                            (w2, h2), _ = cv2.getTextSize(label2, cv2.FONT_HERSHEY_SIMPLEX, font_scale_small, font_thickness_small)
                            (w3, h3), _ = cv2.getTextSize(label3, cv2.FONT_HERSHEY_SIMPLEX, font_scale_large, font_thickness_large)

                            x1_t = max(10, min(int(cx - w1 / 2), img_w - w1 - 10))
                            y1_t = max(h1 + 10, min(int(cy), img_h - 30))
                            x2_t = max(10, min(int(cx - w2 / 2), img_w - w2 - 10))
                            y2_t = max(y1_t + h2 + 6, min(y1_t + h2 + 20, img_h - 20))
                            x3_t = max(10, min(int(cx - w3 / 2), img_w - w3 - 10))
                            y3_t = max(y2_t + h3 + 6, min(y2_t + h3 + 24, img_h - 10))

                            _put_text(label1, x1_t, y1_t, font_scale_small, font_thickness_small)
                            _put_text(label2, x2_t, y2_t, font_scale_small, font_thickness_small)
                            _put_text(label3, x3_t, y3_t, font_scale_large, font_thickness_large)
                        except Exception:
                            pass
                    else:
                        try:
                            cv2.putText(vis_img, status, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, lineType=cv2.LINE_AA)
                            cv2.putText(vis_img, status, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, main_color, 2, lineType=cv2.LINE_AA)
                        except Exception:
                            pass

                    out_dir = os.path.join(output_root, "result_mark")
                    os.makedirs(out_dir, exist_ok=True)
                    stem, ext = os.path.splitext(str(filename or ""))
                    ext_only = str(ext or "").lstrip(".")
                    if ext_only:
                        out_name = f"analyzed_{stem}_{ext_only}.jpg"
                    else:
                        out_name = f"analyzed_{stem}.jpg"
                    save_path = os.path.join(out_dir, out_name)
                    cv2.imencode(".jpg", vis_img)[1].tofile(save_path)
            except Exception:
                pass

        return (
            final_bird,
            final_status,
            final_score_correction,
            final_ratio,
            final_ratio_local,
            final_hf_ratio,
            final_hf_margin,
            final_ratio_best,
        )

    def judge_result(
        self,
        bird_stats: List[Dict[str, Any]],
        gray: np.ndarray,
        laplacian: np.ndarray,
        global_score: float,
        raw_bg_score: float,
        bg_score: float,
        background_mask: np.ndarray,
        filename: str = "",
    ):
        return self.judge_best_bird(bird_stats, gray, laplacian, global_score, raw_bg_score, bg_score, background_mask, filename)

    def quick_detect_file(self, image_path: str):
        filename = os.path.basename(image_path)
        image_small, scale_x, scale_y, orig_w, orig_h = self.load_image_scaled_for_detection(image_path)
        if image_small is None:
            return None
        results, masks_xy_list = self.segment_bird_contours(image_small, filename, image_path=str(image_path))
        if not masks_xy_list:
            return None
        best_idx = 0
        best_score = -1.0
        for i, poly in enumerate(masks_xy_list):
            if poly is None or len(poly) == 0:
                continue
            area = float(cv2.contourArea(poly.astype(np.float32)))
            conf = 0.5
            try:
                if results and results[0].boxes is not None and len(results[0].boxes) > i:
                    conf = float(results[0].boxes.conf[i])
            except Exception:
                conf = 0.5
            score = area * conf
            if score > best_score:
                best_score = score
                best_idx = i
        poly = masks_xy_list[best_idx].astype(np.int32)
        x, y, w_box, h_box = cv2.boundingRect(poly)
        bbox = (x, y, x + w_box, y + h_box)
        bbox_orig = (int(x * scale_x), int(y * scale_y), int((x + w_box) * scale_x), int((y + h_box) * scale_y))
        return {
            "filename": filename,
            "bbox": bbox,
            "bbox_orig": bbox_orig,
            "poly": poly,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "orig_w": orig_w,
            "orig_h": orig_h,
        }

    def quick_detect(self, image_path: str):
        return self.quick_detect_file(image_path)

    def detect_file(self, image_path: str):
        filename = os.path.basename(image_path)
        image = self.load_image_for_detection(image_path)
        if image is None:
            return {"filename": filename, "status": "NoBird", "score": 0.0, "area": 0.0, "best_bird": None}

        image, scale_x, scale_y = self.resize_for_scoring(image)
        results, masks_xy_list = self.segment_bird_contours(image, filename, image_path=str(image_path))
        if not masks_xy_list:
            return {"filename": filename, "status": "NoBird", "score": 0.0, "area": 0.0, "best_bird": None}

        bird_stats, gray, laplacian, global_score, _ = self.score_birds(image, results, masks_xy_list, filename)
        if not bird_stats:
            return {"filename": filename, "status": "NoBird", "score": 0.0, "area": 0.0, "best_bird": None}

        raw_bg_score, bg_score, background_mask, _ = self.compute_background_score(laplacian, global_score, bird_stats)
        if background_mask is None:
            return {"filename": filename, "status": "NoBird", "score": 0.0, "area": 0.0, "best_bird": None}

        final_bird, final_status, score_correction, ratio, ratio_local, hf_ratio, hf_margin, ratio_best = self.judge_best_bird(
            bird_stats, gray, laplacian, global_score, raw_bg_score, bg_score, background_mask, filename
        )

        if final_bird is None or final_status is None:
            return {"filename": filename, "status": "NoBird", "score": 0.0, "area": 0.0, "best_bird": None}

        pos_label, cx, cy = self.compute_bird_position(final_bird, gray.shape)

        x1, y1, x2, y2 = final_bird.get("bbox", (0, 0, 0, 0))
        bbox_orig = (int(x1 * scale_x), int(y1 * scale_y), int(x2 * scale_x), int(y2 * scale_y))

        return {
            "filename": filename,
            "status": final_status,
            "score": float(final_bird.get("score", 0.0)),
            "norm_score": float(final_bird.get("norm_score", 0.0)),
            "area": float(final_bird.get("area_ratio", 0.0)),
            "pos": pos_label,
            "center": (float(cx), float(cy)),
            "bbox": (int(x1), int(y1), int(x2), int(y2)),
            "bbox_orig": bbox_orig,
            "ratio": float(ratio),
            "ratio_local": float(ratio_local),
            "hf_ratio": float(hf_ratio),
            "hf_margin": float(hf_margin),
            "ratio_best": float(ratio_best),
            "score_correction": score_correction,
        }

    def detect_files(self, image_paths: Sequence[str]):
        return [self.detect_file(p) for p in image_paths]

    def _pos_label_from_center(self, cx: float, cy: float, w: int, h: int) -> str:
        x_th1, x_th2 = w * 0.4, w * 0.6
        y_th1, y_th2 = h * 0.4, h * 0.6
        if cx < x_th1:
            pos_x = "L"
        elif cx > x_th2:
            pos_x = "R"
        else:
            pos_x = "C"
        if cy < y_th1:
            pos_y = "T"
        elif cy > y_th2:
            pos_y = "B"
        else:
            pos_y = "M"
        pos_map = {
            ("C", "C"): "Center",
            ("L", "C"): "Left",
            ("R", "C"): "Right",
            ("C", "T"): "Top",
            ("C", "B"): "Bottom",
            ("L", "T"): "LeftTop",
            ("L", "B"): "LeftBottom",
            ("R", "T"): "RightTop",
            ("R", "B"): "RightBottom",
            ("L", "M"): "Left",
            ("R", "M"): "Right",
            ("C", "M"): "Center",
        }
        return pos_map.get((pos_x, pos_y), "Center")

    @staticmethod
    def pos_label_from_center(cx: float, cy: float, w: int, h: int) -> str:
        x_th1, x_th2 = w * 0.4, w * 0.6
        y_th1, y_th2 = h * 0.4, h * 0.6
        if cx < x_th1:
            pos_x = "L"
        elif cx > x_th2:
            pos_x = "R"
        else:
            pos_x = "C"
        if cy < y_th1:
            pos_y = "T"
        elif cy > y_th2:
            pos_y = "B"
        else:
            pos_y = "M"
        pos_map = {
            ("C", "C"): "Center",
            ("L", "C"): "Left",
            ("R", "C"): "Right",
            ("C", "T"): "Top",
            ("C", "B"): "Bottom",
            ("L", "T"): "LeftTop",
            ("L", "B"): "LeftBottom",
            ("R", "T"): "RightTop",
            ("R", "B"): "RightBottom",
            ("L", "M"): "Left",
            ("R", "M"): "Right",
            ("C", "M"): "Center",
        }
        return pos_map.get((pos_x, pos_y), "Center")

    def _compute_focus_point(self, laplacian: np.ndarray, target_mask: np.ndarray | None, scale_x: float, scale_y: float):
        lap_abs = np.abs(laplacian).astype(np.float32)
        if target_mask is not None:
            lap_abs = cv2.bitwise_and(lap_abs, lap_abs, mask=target_mask)
        h, w = lap_abs.shape[:2]
        focus_win = int(max(15, min(h, w) * 0.06))
        if focus_win % 2 == 0:
            focus_win += 1
        local_sharp = cv2.blur(lap_abs, (focus_win, focus_win))
        _, _, _, sharp_loc = cv2.minMaxLoc(local_sharp)
        fx, fy = int(sharp_loc[0]), int(sharp_loc[1])
        return {
            "focus_point": (fx, fy),
            "focus_point_orig": (int(fx * scale_x), int(fy * scale_y)),
        }

    def analyze_file(self, image_path: str, targets: Sequence[str] | None = None) -> Dict[str, Any]:
        t_all0 = time.perf_counter()
        t_load_s = 0.0
        t_seg_s = 0.0
        t_score_s = 0.0
        t_tex_s = 0.0
        t_focus_s = 0.0
        try:
            self._prof_model_calls = 0
            self._prof_model_s = 0.0
            self._prof_model_max_s = 0.0
            self._prof_model_fallback = 0
        except Exception:
            pass
        try:
            self._prof_seg_calls = 0
            self._prof_seg_exif_s = 0.0
            self._prof_seg_tag = ""
        except Exception:
            pass
        wanted = set([t for t in (targets or []) if t])
        if not wanted:
            wanted = {
                "score",
                "norm_score",
                "area",
                "conf",
                "is_minimal",
                "exp_frame",
                "raw_bg_score",
                "bg_score",
                "bg_hf_p90",
                "bg_hf_p95",
                "bird_hf_p90",
                "pos",
                "center",
                "bbox",
                "bbox_orig",
                "ratio",
                "ratio_local",
                "hf_ratio",
                "hf_margin",
                "hf_ratio_robust",
                "hf_margin_robust",
                "ratio_best",
                "has_bird",
                "texture_edge_density",
                "texture_edge_density_bg",
                "texture_edge_density_ratio",
                "texture_entropy",
                "texture_entropy_bg",
                "texture_entropy_ratio",
            }

        filename = os.path.basename(image_path)
        _t0 = time.perf_counter()
        image_small, scale_x, scale_y, orig_w, orig_h = self.load_image_scaled_for_detection(image_path)
        _t1 = time.perf_counter()
        try:
            t_load_s = float(_t1 - _t0)
        except Exception:
            t_load_s = 0.0
        if image_small is None:
            return {"filename": filename, "has_bird": False, "score": 0.0, "norm_score": 0.0, "area": 0.0, "conf": 0.0}

        need_full = any(
            k
            in wanted
            for k in (
                "score",
                "norm_score",
                "area",
                "conf",
                "is_minimal",
                "exp_frame",
                "raw_bg_score",
                "bg_score",
                "bg_hf_p90",
                "bg_hf_p95",
                "bird_hf_p90",
                "ratio",
                "ratio_local",
                "hf_ratio",
                "hf_margin",
                "hf_ratio_robust",
                "hf_margin_robust",
                "ratio_best",
                "has_bird",
                "focus_point",
                "focus_point_orig",
                "texture_edge_density",
                "texture_edge_density_bg",
                "texture_edge_density_ratio",
                "texture_entropy",
                "texture_entropy_bg",
                "texture_entropy_ratio",
            )
        )

        if not need_full and wanted.issubset({"bbox", "bbox_orig", "pos", "center", "filename"}):
            quick = self.quick_detect_file(image_path)
            if not quick:
                return {"filename": filename, "has_bird": False, "score": 0.0, "norm_score": 0.0, "area": 0.0, "conf": 0.0}
            bbox_orig = quick.get("bbox_orig")
            if bbox_orig:
                x1, y1, x2, y2 = bbox_orig
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                pos = self._pos_label_from_center(cx, cy, orig_w, orig_h)
            else:
                cx = orig_w * 0.5
                cy = orig_h * 0.5
                pos = "Center"
            out: Dict[str, Any] = {"filename": filename}
            if "bbox" in wanted:
                out["bbox"] = quick.get("bbox")
            if "bbox_orig" in wanted:
                out["bbox_orig"] = bbox_orig
            if "center" in wanted:
                out["center"] = (float(cx), float(cy))
            if "pos" in wanted:
                out["pos"] = pos
            return out

        _t0 = time.perf_counter()
        results, masks_xy_list = self.segment_bird_contours(image_small, filename, image_path=str(image_path))
        _t1 = time.perf_counter()
        try:
            t_seg_s = float(_t1 - _t0)
        except Exception:
            t_seg_s = 0.0
        if not masks_xy_list:
            try:
                if _is_focus_save_output_enabled() and isinstance(image_small, np.ndarray) and image_small.size > 0:
                    vis = image_small.copy()
                    cv2.putText(vis, "NoBird", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, lineType=cv2.LINE_AA)
                    cv2.putText(vis, "NoBird", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 120, 120), 2, lineType=cv2.LINE_AA)
                    _save_focus_debug_image(vis, filename)
            except Exception:
                pass
            return {"filename": filename, "has_bird": False, "score": 0.0, "norm_score": 0.0, "area": 0.0, "conf": 0.0}

        _t0 = time.perf_counter()
        bird_stats, gray, laplacian, global_score, vis_img = self.score_birds(image_small, results, masks_xy_list, filename)
        _t1 = time.perf_counter()
        try:
            t_score_s = float(_t1 - _t0)
        except Exception:
            t_score_s = 0.0
        if not bird_stats:
            try:
                if _is_focus_save_output_enabled() and isinstance(vis_img, np.ndarray) and vis_img.size > 0:
                    vis = vis_img.copy()
                    cv2.putText(vis, "NoBird", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, lineType=cv2.LINE_AA)
                    cv2.putText(vis, "NoBird", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 120, 120), 2, lineType=cv2.LINE_AA)
                    _save_focus_debug_image(vis, filename)
            except Exception:
                pass
            return {"filename": filename, "has_bird": False, "score": 0.0, "norm_score": 0.0, "area": 0.0, "conf": 0.0}

        best_bird = bird_stats[0]
        kernel_bg = np.ones((5, 5), np.uint8)
        eroded_best_bird_mask = cv2.erode(best_bird["mask"], kernel_bg, iterations=1)
        background_mask = cv2.bitwise_not(eroded_best_bird_mask)
        raw_bg_score = self.calculate_sharpness_score(
            laplacian,
            background_mask,
            min_pixels=300,
            percentile=95,
            multiplier=1.0,
            erosion_kernel=(2, 2),
            erosion_iter=0,
            preprocess_mask=False,
        )
        bg_score = (raw_bg_score / global_score) * 100 if global_score > 0 else 0.0

        ratio = float(best_bird.get("norm_score", 0.0)) / max(float(bg_score), 1e-6)
        ratio_local = ratio
        hf_ratio = 1.0
        hf_margin = 0.0
        hf_ratio_robust = 1.0
        hf_margin_robust = 0.0
        bird_hf_p90 = 0.0
        bg_hf_p90 = 0.0
        bg_hf_p95 = 0.0
        try:
            img_h, img_w = gray.shape[:2]
            ring_w = max(3, int(max(img_w, img_h) * 0.01))
            if ring_w % 2 == 0:
                ring_w += 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ring_w, ring_w))
            ring = cv2.dilate(best_bird["mask"], kernel, iterations=1)
            ring = cv2.subtract(ring, best_bird["mask"])
            ring = cv2.bitwise_and(ring, background_mask)

            if cv2.countNonZero(ring) > 0:
                ring_std = cv2.meanStdDev(laplacian, mask=ring)[1][0][0]
                ring_score_raw = ring_std * ring_std
                ring_score_norm = (max(float(ring_score_raw), 1.0) / global_score) * 100 if global_score > 0 else 0.0
                ratio_local = float(best_bird.get("norm_score", 0.0)) / max(float(ring_score_norm), 1e-6)

            abs_laplacian = np.abs(laplacian)
            bird_vals = abs_laplacian[best_bird["mask"] > 0]
            bg_vals = abs_laplacian[background_mask > 0]
            ring_vals = abs_laplacian[ring > 0] if cv2.countNonZero(ring) > 0 else None

            def _p(a: np.ndarray, q: float) -> float:
                try:
                    if a is None or not isinstance(a, np.ndarray):
                        return 0.0
                    if a.size <= 0:
                        return 0.0
                    if a.size >= 20:
                        return float(np.percentile(a, float(q)))
                    return float(a.max())
                except Exception:
                    try:
                        return float(a.max())
                    except Exception:
                        return 0.0

            bg_src = ring_vals if (ring_vals is not None and isinstance(ring_vals, np.ndarray) and ring_vals.size >= 20) else bg_vals
            bird_hf_p90 = _p(bird_vals, 90)
            bg_hf_p90 = _p(bg_src, 90)
            bg_hf_p95 = _p(bg_src, 95)

            hf_ratio = bird_hf_p90 / (bg_hf_p90 + 1e-6)
            hf_margin = bird_hf_p90 - bg_hf_p90
            hf_ratio_robust = bird_hf_p90 / (bg_hf_p95 + 1e-6)
            hf_margin_robust = bird_hf_p90 - bg_hf_p95
        except Exception:
            pass

        ratio_best = float(max(float(ratio), float(ratio_local)))

        pos_label, cx, cy = self.compute_bird_position(best_bird, gray.shape)

        x1, y1, x2, y2 = best_bird.get("bbox", (0, 0, 0, 0))
        bbox = (int(x1), int(y1), int(x2), int(y2))
        bbox_orig = (int(x1 * scale_x), int(y1 * scale_y), int(x2 * scale_x), int(y2 * scale_y))

        base: Dict[str, Any] = {"filename": filename}
        if "has_bird" in wanted:
            base["has_bird"] = True
        if "score" in wanted:
            base["score"] = float(best_bird.get("score", 0.0))
        if "norm_score" in wanted:
            base["norm_score"] = float(best_bird.get("norm_score", 0.0))
        if "area" in wanted:
            base["area"] = float(best_bird.get("area_ratio", 0.0))
        if "conf" in wanted:
            base["conf"] = float(best_bird.get("conf", 0.0))
        if "is_minimal" in wanted:
            base["is_minimal"] = bool(best_bird.get("isMinimal", False))
        if "exp_frame" in wanted:
            base["exp_frame"] = bool(self.exp_frame_check and self.is_exp_frame(best_bird.get("poly"), gray.shape, margin=1))
        if "raw_bg_score" in wanted:
            base["raw_bg_score"] = float(raw_bg_score or 0.0)
        if "bg_score" in wanted:
            base["bg_score"] = float(bg_score or 0.0)
        if "bg_hf_p90" in wanted:
            base["bg_hf_p90"] = float(bg_hf_p90 or 0.0)
        if "bg_hf_p95" in wanted:
            base["bg_hf_p95"] = float(bg_hf_p95 or 0.0)
        if "bird_hf_p90" in wanted:
            base["bird_hf_p90"] = float(bird_hf_p90 or 0.0)
        if "pos" in wanted:
            base["pos"] = pos_label
        if "center" in wanted:
            base["center"] = (float(cx * scale_x), float(cy * scale_y))
        if "bbox" in wanted:
            base["bbox"] = bbox
        if "bbox_orig" in wanted:
            base["bbox_orig"] = bbox_orig
        if "ratio" in wanted:
            base["ratio"] = float(ratio)
        if "ratio_local" in wanted:
            base["ratio_local"] = float(ratio_local)
        if "hf_ratio" in wanted:
            base["hf_ratio"] = float(hf_ratio)
        if "hf_margin" in wanted:
            base["hf_margin"] = float(hf_margin)
        if "hf_ratio_robust" in wanted:
            base["hf_ratio_robust"] = float(hf_ratio_robust)
        if "hf_margin_robust" in wanted:
            base["hf_margin_robust"] = float(hf_margin_robust)
        if "ratio_best" in wanted:
            base["ratio_best"] = float(ratio_best)

        if (
            "texture_edge_density" in wanted
            or "texture_edge_density_bg" in wanted
            or "texture_edge_density_ratio" in wanted
            or "texture_entropy" in wanted
            or "texture_entropy_bg" in wanted
            or "texture_entropy_ratio" in wanted
        ):
            try:
                _t0 = time.perf_counter()
                tex = self.calculate_texture_richness(gray, best_bird.get("mask"), background_mask)
                _t1 = time.perf_counter()
                try:
                    t_tex_s = float(_t1 - _t0)
                except Exception:
                    t_tex_s = 0.0
            except Exception:
                tex = {}
            if "texture_edge_density" in wanted:
                base["texture_edge_density"] = float((tex or {}).get("edge_density", 0.0) or 0.0)
            if "texture_edge_density_bg" in wanted:
                base["texture_edge_density_bg"] = float((tex or {}).get("edge_density_bg", 0.0) or 0.0)
            if "texture_edge_density_ratio" in wanted:
                base["texture_edge_density_ratio"] = float((tex or {}).get("edge_density_ratio", 1.0) or 1.0)
            if "texture_entropy" in wanted:
                base["texture_entropy"] = float((tex or {}).get("entropy", 0.0) or 0.0)
            if "texture_entropy_bg" in wanted:
                base["texture_entropy_bg"] = float((tex or {}).get("entropy_bg", 0.0) or 0.0)
            if "texture_entropy_ratio" in wanted:
                base["texture_entropy_ratio"] = float((tex or {}).get("entropy_ratio", 1.0) or 1.0)

        if "focus_point" in wanted or "focus_point_orig" in wanted:
            _t0 = time.perf_counter()
            focus = self._compute_focus_point(laplacian, best_bird.get("mask"), scale_x, scale_y)
            _t1 = time.perf_counter()
            try:
                t_focus_s = float(_t1 - _t0)
            except Exception:
                t_focus_s = 0.0
            if "focus_point" in wanted:
                base["focus_point"] = focus["focus_point"]
            if "focus_point_orig" in wanted:
                base["focus_point_orig"] = focus["focus_point_orig"]

        try:
            base["_device"] = str(getattr(self, "device", "cpu") or "cpu")
        except Exception:
            pass
        try:
            base["_model_calls"] = int(getattr(self, "_prof_model_calls", 0) or 0)
        except Exception:
            pass
        try:
            base["_model_s"] = float(getattr(self, "_prof_model_s", 0.0) or 0.0)
        except Exception:
            pass
        try:
            base["_model_max_s"] = float(getattr(self, "_prof_model_max_s", 0.0) or 0.0)
        except Exception:
            pass
        try:
            base["_model_fallback"] = int(getattr(self, "_prof_model_fallback", 0) or 0)
        except Exception:
            pass
        try:
            base["_seg_calls"] = int(getattr(self, "_prof_seg_calls", 0) or 0)
        except Exception:
            pass
        try:
            base["_seg_exif_s"] = float(getattr(self, "_prof_seg_exif_s", 0.0) or 0.0)
        except Exception:
            pass
        try:
            base["_seg_tag"] = str(getattr(self, "_prof_seg_tag", "") or "")
        except Exception:
            pass
        try:
            base["_t_load_s"] = float(t_load_s)
            base["_t_seg_s"] = float(t_seg_s)
            base["_t_score_s"] = float(t_score_s)
            base["_t_tex_s"] = float(t_tex_s)
            base["_t_focus_s"] = float(t_focus_s)
        except Exception:
            pass
        try:
            total_s = float(time.perf_counter() - float(t_all0))
        except Exception:
            total_s = 0.0
        if total_s >= 1.0:
            try:
                LogManager.instance().debug(
                    f"[FocusDetect] analyze_slow elapsed_s={total_s:.3f} load_s={t_load_s:.3f} seg_s={t_seg_s:.3f} score_s={t_score_s:.3f} tex_s={t_tex_s:.3f} focus_s={t_focus_s:.3f} file={filename}"
                )
            except Exception:
                pass
        return base

    def process_image_combine(self, image_name, image_path, output_path):
        filename = os.path.basename(image_path)
        log_name = filename
        try:
            log_name = os.path.basename(image_path)
        except Exception:
            pass

        def _log_final(status: str, final_score: float, area_ratio: float):
            try:
                LogManager.instance().info(
                    f"[FocusDetect] {log_name} status={status} score={float(final_score):.4f} area_ratio={float(area_ratio):.4f}"
                )
            except Exception:
                pass

        image = self.load_image_for_detection(image_path)

        if image is None:
            _log_final("NoBird", 0.0, 0.0)
            return "NoBird", 0.0, 0.0

        image, scale_x, scale_y = self.resize_for_scoring(image)

        results, masks_xy_list = self.segment_bird_contours(image, filename)

        if not masks_xy_list:
            _log_final("NoBird", 0.0, 0.0)
            return "NoBird", 0.0, 0.0

        bird_stats, gray, laplacian, global_score, vis_img = self.score_birds(image, results, masks_xy_list, filename)
        if not bird_stats:
            _log_final("NoBird", 0.0, 0.0)
            return "NoBird", 0.0, 0.0

        raw_bg_score, bg_score, background_mask, _ = self.compute_background_score(laplacian, global_score, bird_stats)
        if background_mask is None:
            _log_final("NoBird", 0.0, 0.0)
            return "NoBird", 0.0, 0.0

        final_bird, final_status, score_correction, ratio, ratio_local, hf_ratio, hf_margin, ratio_best = self.judge_best_bird(
            bird_stats,
            gray,
            laplacian,
            global_score,
            raw_bg_score,
            bg_score,
            background_mask,
            filename,
            output_path=output_path,
            vis_img=vis_img,
        )

        if final_bird is None or final_status is None:
            _log_final("NoBird", 0.0, 0.0)
            return "NoBird", 0.0, 0.0

        target_bird = final_bird
        status = final_status
        is_focused = status in ("Sharp", "Normal", "ExpFrame")

        try:
            pos_label, cx, cy = self.compute_bird_position(target_bird, gray.shape)
            target_bird["pos"] = pos_label
        except Exception:
            pass

        area_ratio = float(target_bird.get("area_ratio", 0.0))
        final_score = float(target_bird.get("norm_score", 0.0))
        _log_final(status, float(final_score), float(area_ratio))
        return status, float(final_score), float(area_ratio)

    @staticmethod
    def get_last_extension_simple(text):
        parts = text.split(".")
        if len(parts) > 1:
            return parts[-1]
        return ""

    @staticmethod
    def get_all_extension_simple(text):
        ext = BirdFocusDetector.get_last_extension_simple(text)
        if ext != "":
            return "." + ext
        return ext

    @staticmethod
    def calculate_dhash(image_path, hash_size=8):
        image = BirdFocusDetector.load_image(image_path)
        if image is None:
            return 0
        resized = cv2.resize(image, (hash_size + 1, hash_size), interpolation=cv2.INTER_LINEAR)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        dct = cv2.dct(np.float32(gray))
        dct_low = dct[:8, :8]
        avg = np.mean(dct_low)
        hash_value = (dct_low > avg).flatten()
        return hash_value

