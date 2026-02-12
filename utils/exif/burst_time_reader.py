from __future__ import annotations

import os
from datetime import datetime, timedelta

try:
    import exifread
except Exception:
    exifread = None


def _to_str(v) -> str:
    if v is None:
        return ""
    try:
        return str(getattr(v, "printable", v) or "").strip()
    except Exception:
        try:
            return str(v).strip()
        except Exception:
            return ""


def _parse_dt_with_subsec(dt_str: str, subsec_str: str) -> datetime | None:
    if not dt_str:
        return None
    try:
        base = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    ss = (subsec_str or "").strip()
    if ss and ss.isdigit():
        micro = int(ss.ljust(6, "0")[:6])
        return base + timedelta(microseconds=micro)
    return base


def _parse_dt_str(s: str) -> datetime | None:
    if not s:
        return None
    t = str(s).strip()
    if not t:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S.%f%z", "%Y:%m:%d %H:%M:%S.%f", "%Y:%m:%d %H:%M:%S%z", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.strptime(t, fmt)
        except Exception:
            continue
    return None


def read_subsec_create_ts(file_path: str) -> float | None:
    p = str(file_path or "")
    if not p:
        return None
    if not os.path.exists(p):
        return None
    if exifread is None:
        return None

    try:
        with open(p, "rb") as f:
            tags = exifread.process_file(f, details=False, strict=False)
    except Exception:
        return None

    try:
        for k, v in (tags or {}).items():
            try:
                ks = str(k or "")
            except Exception:
                ks = ""
            if "SubSecCreateDate" in ks:
                dt0 = _parse_dt_str(_to_str(v))
                if dt0 is not None:
                    try:
                        return float(dt0.timestamp())
                    except Exception:
                        return None
                break
    except Exception:
        pass

    def _get(*keys: str) -> str:
        for k in keys:
            if not k:
                continue
            if k in tags:
                s = _to_str(tags.get(k))
                if s:
                    return s
        return ""

    dt_str = _get(
        "EXIF DateTimeOriginal",
        "EXIF DateTimeDigitized",
        "Image DateTime",
    )
    if not dt_str:
        return None

    subsec = _get(
        "EXIF SubSecTimeOriginal",
        "EXIF SubSecTimeDigitized",
    )
    dt_obj = _parse_dt_with_subsec(dt_str, subsec)
    if dt_obj is None:
        return None
    try:
        return float(dt_obj.timestamp())
    except Exception:
        return None
