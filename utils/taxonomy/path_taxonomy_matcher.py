import os
import re


_CHINESE_RE = re.compile(r"^[\u4e00-\u9fff]+$")


def match_taxonomy_from_path(file_path: str, root_path: str):
    try:
        norm_root = os.path.normpath(str(root_path or ""))
        norm_fpath = os.path.normpath(str(file_path or ""))
    except Exception:
        return None
    if not norm_root or not norm_fpath:
        return None
    try:
        rel_path = os.path.relpath(norm_fpath, norm_root)
    except Exception:
        return None
    parts = []
    try:
        parts = [p for p in rel_path.split(os.sep) if p]
    except Exception:
        parts = []
    if len(parts) < 2:
        return None
    folder_parts = parts[:-1]
    for i in range(0, len(folder_parts)):
        o = folder_parts[i]
        if not (o and str(o).endswith("目")):
            continue
        if i + 3 >= len(folder_parts):
            continue
        f = folder_parts[i + 1]
        g = folder_parts[i + 2]
        s = folder_parts[i + 3]
        if not (f and str(f).endswith("科")):
            continue
        if not (g and str(g).endswith("属")):
            continue
        try:
            s_str = str(s or "").strip()
        except Exception:
            s_str = ""
        if not s_str or not _CHINESE_RE.match(s_str):
            continue
        return {
            "order_cls": str(o),
            "family_cls": str(f),
            "genus_cls": str(g),
            "species_cls": str(s_str),
        }
    return None

