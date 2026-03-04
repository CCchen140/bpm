from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from utils.exif.exif_utils import get_exiftool_path, run_exiftool
from utils.log_manager import LogManager


@dataclass
class AfPoint:
    x: float
    y: float
    w: float | None = None
    h: float | None = None
    orig_w: float | None = None
    orig_h: float | None = None


def _extract_make(make_raw: str) -> str:
    t = str(make_raw or "")
    up = t.upper()
    if "OM DIGITAL" in up or "OLYMPUS" in up:
        return "OLYMPUS"
    for v in ("NIKON", "CANON", "SONY", "FUJIFILM", "PANASONIC", "PENTAX", "LEICA"):
        if v in up:
            return v
    return t.strip()


def _first_number(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and v:
        return _first_number(v[0])
    s = str(v).strip()
    if not s:
        return None
    parts = s.replace(",", " ").split()
    if not parts:
        return None
    try:
        return float(parts[0])
    except Exception:
        return None


def _parse_pair(v) -> tuple[float | None, float | None]:
    if v is None:
        return None, None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return float(v[0]), float(v[1])
        except Exception:
            return None, None
    s = str(v).strip()
    if not s:
        return None, None
    parts = s.replace(",", " ").split()
    if len(parts) < 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except Exception:
        return None, None


def _pick(meta: dict, contains: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for k, v in (meta or {}).items():
        try:
            ks = str(k)
        except Exception:
            continue
        if contains in ks:
            out.append((ks, v))
    return out


def _read_exiftool_af_tags(file_path: str, *, timeout_s: float = 1.2) -> dict | None:
    p = str(file_path or "")
    if not p or not os.path.exists(p):
        return None
    cmd = [
        get_exiftool_path(),
        "-j",
        "-struct",
        "-G",
        "-charset",
        "utf8",
        "-charset",
        "filename=utf8",
        "-Make",
        "-Model",
        "-ImageWidth",
        "-ImageHeight",
        "-ExifImageWidth",
        "-ExifImageHeight",
        "-ExifImageLength",
        "-ImageSize",
        "-RawImageFullWidth",
        "-RawImageFullHeight",
        "-RawImageWidth",
        "-RawImageHeight",
        "-AFAreaXPosition",
        "-AFAreaYPosition",
        "-AFAreaWidth",
        "-AFAreaHeight",
        "-AFAreaXPositions",
        "-AFAreaYPositions",
        "-AFAreaWidths",
        "-AFAreaHeights",
        "-AFAreas",
        "-AFPointSelected",
        "-AFPointPosition",
        "-AFAreaSize",
        "-FocusPixel",
        "-FocusLocation",
        "-FocalPlaneAFPointsUsed",
        "-FocalPlaneAFPointSelected",
        "-FocalPlaneAFPointArea",
        "-FocalPlaneAFPointLocation*",
        # 索尼相机额外对焦点标签
        "-FocusMode",
        "-AFAreaMode",
        "-FocusPosition2",
        "-SonyAFStatus",
        "-AFPoint",
        "-PrimaryAFPoint",
        "-AFPointsUsed",
        "-AFPointsSelected",
        "-FocusLocation",
        "-FocusPixel",
        "-AFImageWidth",
        "-AFImageHeight",
        "-AFAreaPositions",
        "-FocusFrameSize",
        "-FocusFrameLocation",
        "-FocusFrameCenter",
        "-FocusFrameCenterCoordinates",
        "-FocusFrameSize",
        "-FocusFrameSize",
        "-FocusPosition",
        "-FocusDistance",
        "-FocusDistance2",
        "-SourceFile",
        p,
    ]
    try:
        res = run_exiftool(cmd, timeout=float(timeout_s or 1.2))
    except Exception:
        return None
    if getattr(res, "returncode", 1) != 0:
        return None
    try:
        data = json.loads(getattr(res, "stdout", "") or "[]")
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    if not isinstance(data[0], dict):
        return None
    return data[0]


def _read_image_size(meta: dict) -> tuple[float | None, float | None]:
    w = None
    h = None
    for k, v in (meta or {}).items():
        ks = str(k)
        if w is None and ("ImageWidth" in ks or ks.endswith(":ImageWidth")):
            w = _first_number(v)
        if h is None and ("ImageHeight" in ks or ks.endswith(":ImageHeight")):
            h = _first_number(v)
        if w is None and ("ExifImageWidth" in ks or ks.endswith(":ExifImageWidth")):
            w = _first_number(v)
        if h is None and ("ExifImageHeight" in ks or ks.endswith(":ExifImageHeight")):
            h = _first_number(v)
        if h is None and ("ExifImageLength" in ks or ks.endswith(":ExifImageLength")):
            h = _first_number(v)
        if w is None and ("RawImageFullWidth" in ks or ks.endswith(":RawImageFullWidth")):
            w = _first_number(v)
        if h is None and ("RawImageFullHeight" in ks or ks.endswith(":RawImageFullHeight")):
            h = _first_number(v)
        if w is None and ("RawImageWidth" in ks or ks.endswith(":RawImageWidth")):
            w = _first_number(v)
        if h is None and ("RawImageHeight" in ks or ks.endswith(":RawImageHeight")):
            h = _first_number(v)
    if (w is None or h is None) and meta:
        for k, v in meta.items():
            if "ImageSize" not in str(k):
                continue
            s = str(v or "").replace("x", " ").replace("×", " ").strip()
            parts = s.split()
            if len(parts) >= 2:
                try:
                    w0 = float(parts[0])
                    h0 = float(parts[1])
                    if w is None:
                        w = w0
                    if h is None:
                        h = h0
                    break
                except Exception:
                    continue
    if w is not None and w <= 0:
        w = None
    if h is not None and h <= 0:
        h = None
    return w, h


def _sony_center(meta: dict, ow: float | None, oh: float | None) -> AfPoint | None:
    # 尝试从 FocusFrameCenterCoordinates 获取（索尼某些机型使用）
    for _, v in _pick(meta, "FocusFrameCenterCoordinates"):
        try:
            x, y = _parse_pair(v)
            if x is not None and y is not None and ow is not None and oh is not None:
                # 可能是百分比坐标
                if 0 <= x <= 1 and 0 <= y <= 1:
                    return AfPoint(x=float(x) * float(ow), y=float(y) * float(oh), orig_w=ow, orig_h=oh)
                # 或者是像素坐标
                if 0 <= x <= ow and 0 <= y <= oh:
                    return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
        except Exception:
            pass
    
    # 尝试从 FocusFrameCenter 获取
    for _, v in _pick(meta, "FocusFrameCenter"):
        try:
            x, y = _parse_pair(v)
            if x is not None and y is not None and ow is not None and oh is not None:
                if 0 <= x <= 1 and 0 <= y <= 1:
                    return AfPoint(x=float(x) * float(ow), y=float(y) * float(oh), orig_w=ow, orig_h=oh)
                if 0 <= x <= ow and 0 <= y <= oh:
                    return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
        except Exception:
            pass
    
    # 尝试从 FocusPosition 获取
    for _, v in _pick(meta, "FocusPosition"):
        try:
            x, y = _parse_pair(v)
            if x is not None and y is not None and ow is not None and oh is not None:
                if 0 <= x <= ow and 0 <= y <= oh:
                    return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
        except Exception:
            pass
    
    # 尝试从 FocusPixel 获取
    for _, v in _pick(meta, "FocusPixel"):
        try:
            x, y = _parse_pair(v)
            if x is not None and y is not None and ow is not None and oh is not None:
                if 0 <= x <= ow and 0 <= y <= oh:
                    return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
        except Exception:
            pass
    
    # 尝试从 FocusLocation 获取（索尼格式："图像宽度 图像高度 对焦点X 对焦点Y"）
    for _, v in _pick(meta, "FocusLocation"):
        try:
            parts = str(v or "").split()
            if len(parts) >= 4:
                # 格式：宽 高 x y
                img_w = float(parts[0])
                img_h = float(parts[1])
                af_x = float(parts[2])
                af_y = float(parts[3])
                # 验证坐标是否在有效范围内
                if img_w > 0 and img_h > 0 and af_x >= 0 and af_y >= 0:
                    # 如果提供了图像尺寸，进行坐标转换
                    if ow is not None and oh is not None and ow > 0 and oh > 0:
                        # 按比例转换坐标
                        scale_x = ow / img_w
                        scale_y = oh / img_h
                        af_x = af_x * scale_x
                        af_y = af_y * scale_y
                    return AfPoint(x=float(af_x), y=float(af_y), orig_w=ow, orig_h=oh)
        except Exception:
            pass

    # 首先尝试从 FocusPosition2 获取对焦点（索尼某些机型使用）
    for _, v in _pick(meta, "FocusPosition2"):
        try:
            x, y = _parse_pair(v)
            if x is not None and y is not None and ow is not None and oh is not None:
                # FocusPosition2 通常是像素坐标
                if 0 <= x <= ow and 0 <= y <= oh:
                    return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
        except Exception:
            pass
    
    # 尝试从 PrimaryAFPoint 获取
    for _, v in _pick(meta, "PrimaryAFPoint"):
        try:
            # 可能是 "123 456" 或 "123,456" 格式
            x, y = _parse_pair(v)
            if x is not None and y is not None and ow is not None and oh is not None:
                if 0 <= x <= ow and 0 <= y <= oh:
                    return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
        except Exception:
            pass
    
    # 尝试从 AFPoint 获取（过滤掉非坐标的值）
    for k, v in _pick(meta, "AFPoint"):
        try:
            # 跳过非坐标的值（如 'n/a'）
            if str(v).lower() in ('n/a', 'none', 'auto', 'unknown', ''):
                continue
            x, y = _parse_pair(v)
            if x is not None and y is not None and ow is not None and oh is not None:
                if 0 <= x <= ow and 0 <= y <= oh:
                    return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
        except Exception:
            pass
    
    # 原有的 FocalPlaneAFPointsUsed 逻辑
    selected = None
    for _, v in _pick(meta, "FocalPlaneAFPointsUsed"):
        try:
            selected = int(float(str(v).strip()))
        except Exception:
            selected = None
        if selected is not None:
            break
    if selected is None:
        for _, v in _pick(meta, "AFPointSelected"):
            try:
                selected = int(float(str(v).strip()))
            except Exception:
                selected = None
            break
    af_w = None
    af_h = None
    for _, v in _pick(meta, "FocalPlaneAFPointArea"):
        parts = str(v or "").split()
        if len(parts) >= 2:
            try:
                af_w = float(parts[0])
                af_h = float(parts[1])
            except Exception:
                af_w = af_h = None
        break
    locs: list[tuple[int | None, float, float]] = []
    for k, v in _pick(meta, "FocalPlaneAFPointLocation"):
        m = re.search(r"Location(\d+)", str(k))
        n = int(m.group(1)) if m else None
        x, y = _parse_pair(v)
        if x is None or y is None:
            continue
        locs.append((n, x, y))
    if not locs:
        return None
    locs.sort(key=lambda t: (t[0] is None, t[0] or 0))
    x0 = y0 = None
    # 处理选中的对焦点
    if selected is not None:
        # 如果 selected 是 0，使用第一个对焦点（编号为1）
        effective_selected = selected if selected > 0 else 1
        for n, x, y in locs:
            if n == effective_selected:
                x0, y0 = x, y
                break
        # 如果没找到，尝试使用索引
        if x0 is None and 0 <= effective_selected - 1 < len(locs):
            _, x0, y0 = locs[effective_selected - 1]
    if x0 is None:
        # 默认使用第一个对焦点
        _, x0, y0 = locs[0]
    return AfPoint(x=float(x0), y=float(y0), w=af_w, h=af_h, orig_w=ow, orig_h=oh)


def _olympus_center(meta: dict, ow: float | None, oh: float | None) -> AfPoint | None:
    if ow is None or oh is None:
        return None
    af_point_selected = None
    for _, v in _pick(meta, "AFPointSelected"):
        af_point_selected = v
        break
    af_areas = None
    for _, v in _pick(meta, "AFAreas"):
        af_areas = v
        break
    base_x = base_y = None
    if af_point_selected:
        m = re.search(r"\((\d+(?:\.\d+)?)%,\s*(\d+(?:\.\d+)?)%\)", str(af_point_selected))
        if m:
            try:
                base_x = float(ow) * float(m.group(1)) / 100.0
                base_y = float(oh) * float(m.group(2)) / 100.0
            except Exception:
                base_x = base_y = None
    if base_x is not None and base_y is not None and af_areas:
        m = re.match(r"\((\d+),(\d+)\)-\((\d+),(\d+)\)", str(af_areas))
        if m:
            a, b, c, d = [float(x) for x in m.groups()]
            x1 = base_x - a
            y1 = base_y - b
            x2 = base_x + c
            y2 = base_y + d
            return AfPoint(x=(x1 + x2) / 2.0, y=(y1 + y2) / 2.0, w=abs(x2 - x1), h=abs(y2 - y1), orig_w=ow, orig_h=oh)
    if af_areas:
        m = re.match(r"\((\d+),(\d+)\)-\((\d+),(\d+)\)", str(af_areas))
        if m:
            x1, y1, x2, y2 = [float(x) for x in m.groups()]
            return AfPoint(x=(x1 + x2) / 2.0, y=(y1 + y2) / 2.0, w=abs(x2 - x1), h=abs(y2 - y1), orig_w=ow, orig_h=oh)
    if base_x is not None and base_y is not None:
        return AfPoint(x=float(base_x), y=float(base_y), orig_w=ow, orig_h=oh)
    return None


def _panasonic_center(meta: dict, ow: float | None, oh: float | None) -> AfPoint | None:
    if ow is None or oh is None:
        return None
    pos = None
    size = None
    for _, v in _pick(meta, "AFPointPosition"):
        pos = v
        break
    for _, v in _pick(meta, "AFAreaSize"):
        size = v
        break
    nx, ny = _parse_pair(pos)
    if nx is None or ny is None:
        return None
    cx = float(ow) * float(nx)
    cy = float(oh) * float(ny)
    w = h = None
    sw, sh = _parse_pair(size)
    if sw is not None:
        w = float(ow) * float(sw)
    if sh is not None:
        h = float(oh) * float(sh)
    return AfPoint(x=cx, y=cy, w=w, h=h, orig_w=ow, orig_h=oh)


def _fujifilm_center(meta: dict, ow: float | None, oh: float | None) -> AfPoint | None:
    for _, v in _pick(meta, "FocusPixel"):
        x, y = _parse_pair(v)
        if x is None or y is None:
            return None
        return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)
    return None


def _canon_center(meta: dict, ow: float | None, oh: float | None) -> AfPoint | None:
    ax = ay = None
    aw = ah = None
    for k, v in _pick(meta, "AFAreaXPositions"):
        ax = _first_number(v)
        break
    for k, v in _pick(meta, "AFAreaYPositions"):
        ay = _first_number(v)
        break
    for k, v in _pick(meta, "AFAreaWidths"):
        aw = _first_number(v)
        break
    for k, v in _pick(meta, "AFAreaHeights"):
        ah = _first_number(v)
        break
    if ax is not None and ay is not None:
        return AfPoint(x=float(ax), y=float(ay), w=aw, h=ah, orig_w=ow, orig_h=oh)
    return None


def _nikon_center(meta: dict, ow: float | None, oh: float | None) -> AfPoint | None:
    ax = ay = None
    aw = ah = None
    for k, v in _pick(meta, "AFAreaXPosition"):
        ax = _first_number(v)
        break
    for k, v in _pick(meta, "AFAreaYPosition"):
        ay = _first_number(v)
        break
    for k, v in _pick(meta, "AFAreaWidth"):
        aw = _first_number(v)
        break
    for k, v in _pick(meta, "AFAreaHeight"):
        ah = _first_number(v)
        break
    if ax is not None and ay is not None:
        return AfPoint(x=float(ax), y=float(ay), w=aw, h=ah, orig_w=ow, orig_h=oh)
    return None


def _generic_center(meta: dict, ow: float | None, oh: float | None) -> AfPoint | None:
    for _, v in _pick(meta, "FocusPixel"):
        x, y = _parse_pair(v)
        if x is None or y is None:
            return None
        return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)

    for _, v in _pick(meta, "FocusLocation"):
        x, y = _parse_pair(v)
        if x is None or y is None:
            return None
        if ow is not None and oh is not None and ow > 1 and oh > 1 and 0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0:
            return AfPoint(x=float(x) * float(ow), y=float(y) * float(oh), orig_w=ow, orig_h=oh)
        return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)

    for _, v in _pick(meta, "AFPointPosition"):
        x, y = _parse_pair(v)
        if x is None or y is None:
            return None
        if ow is not None and oh is not None and ow > 1 and oh > 1 and 0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0:
            return AfPoint(x=float(x) * float(ow), y=float(y) * float(oh), orig_w=ow, orig_h=oh)
        return AfPoint(x=float(x), y=float(y), orig_w=ow, orig_h=oh)

    return None


def get_camera_af_center_point_from_meta(meta: dict) -> dict | None:
    if not isinstance(meta, dict):
        return None
    ow, oh = _read_image_size(meta)
    make_raw = ""
    for k, v in _pick(meta, "Make"):
        make_raw = str(v or "")
        break
    make = _extract_make(make_raw)
    try:
        up = make.upper()
    except Exception:
        up = ""
    pt = None
    if "SONY" in up:
        pt = _sony_center(meta, ow, oh)
    elif "OLYMPUS" in up:
        pt = _olympus_center(meta, ow, oh)
    elif "PANASONIC" in up:
        pt = _panasonic_center(meta, ow, oh)
    elif "FUJIFILM" in up:
        pt = _fujifilm_center(meta, ow, oh)
    elif "CANON" in up:
        pt = _canon_center(meta, ow, oh)
    elif "NIKON" in up:
        pt = _nikon_center(meta, ow, oh)
    else:
        pt = (
            _nikon_center(meta, ow, oh)
            or _canon_center(meta, ow, oh)
            or _fujifilm_center(meta, ow, oh)
            or _panasonic_center(meta, ow, oh)
            or _olympus_center(meta, ow, oh)
            or _generic_center(meta, ow, oh)
        )
    if pt is None:
        return None
    if pt.orig_w is None or pt.orig_h is None or pt.orig_w <= 1 or pt.orig_h <= 1:
        return {"x": float(pt.x), "y": float(pt.y), "mode": "global"}
    try:
        nx = float(pt.x) / float(pt.orig_w)
        ny = float(pt.y) / float(pt.orig_h)
    except Exception:
        return {"x": float(pt.x), "y": float(pt.y), "mode": "global"}
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        try:
            cx = (float(pt.x) + float(pt.orig_w) / 2.0) / float(pt.orig_w)
            cy = (float(pt.y) + float(pt.orig_h) / 2.0) / float(pt.orig_h)
        except Exception:
            cx = cy = None
        if cx is not None and cy is not None and (0.0 <= float(cx) <= 1.0 and 0.0 <= float(cy) <= 1.0):
            return {"x": float(cx), "y": float(cy), "mode": "global"}
        return {"x": float(pt.x), "y": float(pt.y), "mode": "global"}
    return {"x": float(nx), "y": float(ny), "mode": "global"}


def get_camera_af_center_point(file_path: str) -> dict | None:
    p = str(file_path or "")
    if not p:
        return None
    try:
        t0 = time.perf_counter()
    except Exception:
        t0 = 0.0
    tags = [
        "Make",
        "Model",
        "ImageWidth",
        "ImageHeight",
        "ExifImageWidth",
        "ExifImageHeight",
        "ExifImageLength",
        "ImageSize",
        "RawImageFullWidth",
        "RawImageFullHeight",
        "RawImageWidth",
        "RawImageHeight",
        "AFAreaXPosition",
        "AFAreaYPosition",
        "AFAreaWidth",
        "AFAreaHeight",
        "AFAreaXPositions",
        "AFAreaYPositions",
        "AFAreaWidths",
        "AFAreaHeights",
        "AFAreas",
        "AFPointSelected",
        "AFPointPosition",
        "AFAreaSize",
        "FocusPixel",
        "FocusLocation",
        "FocalPlaneAFPointsUsed",
        "FocalPlaneAFPointSelected",
        "FocalPlaneAFPointArea",
        "FocalPlaneAFPointLocation*",
    ]
    try:
        from utils.exif.exif_utils import get_instance as _get_exif_worker

        exif_worker = _get_exif_worker()
    except Exception:
        exif_worker = None
    if exif_worker is not None and hasattr(exif_worker, "get_tags_multi"):
        try:
            meta_by_path = exif_worker.get_tags_multi([p], tags, timeout=8, force_mode="file") or {}
        except Exception:
            meta_by_path = {}
        meta0 = meta_by_path.get(p)
        if isinstance(meta0, dict) and meta0:
            try:
                pt = get_camera_af_center_point_from_meta(meta0)
            except Exception:
                pt = None
            if isinstance(pt, dict) and pt:
                return pt
            else:
                # 尝试使用exiftool直接读取
                meta = _read_exiftool_af_tags(p, timeout_s=6.0)
                if isinstance(meta, dict) and meta:
                    out = get_camera_af_center_point_from_meta(meta)
                    if out:
                        return out
        else:
            pass
    else:
        pass
    meta = _read_exiftool_af_tags(p, timeout_s=6.0)
    if not isinstance(meta, dict) or not meta:
        return None
    out = get_camera_af_center_point_from_meta(meta)
    return out


def get_camera_af_center_points(
    file_paths: list[str],
    *,
    timeout: int = 16,
    chunk_size: int = 200,
    max_workers: int = 4,
    progress_callback=None,
    cancel_event: object | None = None,
) -> dict[str, dict]:
    paths = [str(p) for p in (file_paths or []) if p]
    if not paths:
        return {}

    try:
        from utils.exif.exif_utils import get_instance as _get_exif_worker
        exif_worker = _get_exif_worker()
    except Exception:
        exif_worker = None
    if exif_worker is None or not hasattr(exif_worker, "get_tags_multi"):
        out = {}
        for p in paths:
            try:
                pt = get_camera_af_center_point_or_none(p)
            except Exception:
                pt = None
            if isinstance(pt, dict) and pt:
                out[str(p)] = pt
        return out

    tags = [
        "Make",
        "Model",
        "ImageWidth",
        "ImageHeight",
        "ExifImageWidth",
        "ExifImageHeight",
        "ExifImageLength",
        "ImageSize",
        "RawImageFullWidth",
        "RawImageFullHeight",
        "RawImageWidth",
        "RawImageHeight",
        "AFAreaXPosition",
        "AFAreaYPosition",
        "AFAreaWidth",
        "AFAreaHeight",
        "AFAreaXPositions",
        "AFAreaYPositions",
        "AFAreaWidths",
        "AFAreaHeights",
        "AFAreas",
        "AFPointSelected",
        "AFPointPosition",
        "AFAreaSize",
        "FocusPixel",
        "FocusLocation",
        "FocalPlaneAFPointsUsed",
        "FocalPlaneAFPointSelected",
        "FocalPlaneAFPointArea",
        "FocalPlaneAFPointLocation*",
    ]

    total = len(paths)
    try:
        cs = int(chunk_size or 200)
    except Exception:
        cs = 200
    cs = int(max(20, min(800, cs)))
    chunks: list[list[str]] = [paths[i : i + cs] for i in range(0, len(paths), cs)]

    try:
        mw = int(max_workers or 0)
    except Exception:
        mw = 0
    mw = int(max(1, min(8, mw)))
    mw = int(min(mw, len(chunks)))

    def _is_cancelled() -> bool:
        try:
            return bool(cancel_event is not None and hasattr(cancel_event, "is_set") and bool(cancel_event.is_set()))
        except Exception:
            return False

    def _load_chunk(chunk: list[str]) -> dict[str, dict]:
        if not chunk:
            return {}
        if _is_cancelled():
            return {}
        try:
            meta_by_path = exif_worker.get_tags_multi(chunk, tags, timeout=int(timeout or 16), force_mode="file") or {}
        except Exception:
            meta_by_path = {}
        out0: dict[str, dict] = {}
        for p0, meta in (meta_by_path or {}).items():
            if not isinstance(meta, dict):
                continue
            # 如果meta为空，尝试使用_read_exiftool_af_tags直接读取
            if not meta:
                try:
                    meta = _read_exiftool_af_tags(p0, timeout_s=6.0)
                except Exception:
                    meta = None
                if meta is None:
                    meta = {}
            try:
                pt = get_camera_af_center_point_from_meta(meta)
            except Exception:
                pt = None
            if isinstance(pt, dict) and pt:
                out0[str(p0)] = pt
        return out0

    out: dict[str, dict] = {}
    done = 0
    
    if mw <= 1:
        for i, chunk in enumerate(chunks):
            if _is_cancelled():
                break
            t_chunk_start = time.perf_counter()
            chunk_result = _load_chunk(chunk)
            t_chunk_end = time.perf_counter()
            out.update(chunk_result)
            done += len(chunk)
            try:
                if progress_callback is not None:
                    progress_callback(int(done), int(total))
            except Exception:
                pass
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=mw) as ex:
            futs = [ex.submit(_load_chunk, c) for c in chunks]
            for f in as_completed(futs):
                if _is_cancelled():
                    break
                try:
                    part = f.result() or {}
                except Exception:
                    part = {}
                out.update(part)
                try:
                    done = min(total, done + cs)
                except Exception:
                    done = done
                try:
                    if progress_callback is not None:
                        progress_callback(int(min(done, total)), int(total))
                except Exception:
                    pass
    
    return out


def get_camera_af_center_point_or_none(file_path: str) -> dict | None:
    try:
        return get_camera_af_center_point(file_path)
    except Exception as e:
        try:
            LogManager.instance().warning(f"读取相机对焦点失败: {e}")
        except Exception:
            pass
        return None
