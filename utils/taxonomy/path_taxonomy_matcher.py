import os
import re


_CHINESE_RE = re.compile(r"^[\u4e00-\u9fff]+$")
# 匹配全英文字符串（包含字母、空格、连字符、下划线等常见英文命名字符）
_ENGLISH_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-\s]*$")


def _is_english_name(name: str) -> bool:
    """
    判断文件夹名是否为全英文命名

    参数：
        name: 文件夹名

    返回：
        如果是全英文命名返回True，否则返回False
    """
    if not name:
        return False
    return bool(_ENGLISH_RE.match(str(name).strip()))


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
        if not o:
            continue

        # 判断当前文件夹名是否为全英文
        is_english_order = _is_english_name(o)

        # 如果不是全英文，则需要以"目"结尾
        if not is_english_order and not str(o).endswith("目"):
            continue

        if i + 3 >= len(folder_parts):
            continue
        f = folder_parts[i + 1]
        g = folder_parts[i + 2]
        s = folder_parts[i + 3]

        # 判断科、属文件夹名是否为全英文
        is_english_family = _is_english_name(f)
        is_english_genus = _is_english_name(g)

        # 如果不是全英文，则需要以对应的后缀结尾
        if not is_english_family and not str(f).endswith("科"):
            continue
        if not is_english_genus and not str(g).endswith("属"):
            continue

        try:
            s_str = str(s or "").strip()
        except Exception:
            s_str = ""
        # 对于种名，如果是全英文则直接接受，否则需要是中文
        is_english_species = _is_english_name(s_str)
        if not s_str or (not is_english_species and not _CHINESE_RE.match(s_str)):
            continue
        return {
            "order_cls": str(o),
            "family_cls": str(f),
            "genus_cls": str(g),
            "species_cls": str(s_str),
        }
    return None

