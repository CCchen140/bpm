import os
import shutil

from utils.log_manager import LogManager


def _xmp_sidecar_path(file_path: str) -> str | None:
    p = str(file_path or "")
    if not p:
        return None
    try:
        if os.path.splitext(p)[1].lower() == ".xmp":
            return None
    except Exception:
        return None
    try:
        base, _ = os.path.splitext(p)
    except Exception:
        return None
    if not base:
        return None
    return f"{base}.xmp"


def send2trash_file(file_path: str) -> bool:
    p = str(file_path or "")
    if not p:
        return False
    try:
        if not os.path.exists(p):
            return True
    except Exception:
        pass
    try:
        from send2trash import send2trash
        send2trash(p)
        return True
    except Exception as e:
        try:
            LogManager.instance().warning(f"send2trash 失败: {p}: {e}")
        except Exception:
            pass
        return False


def delete_with_sidecar(file_path: str, *, prefer_trash: bool = True) -> bool:
    p = str(file_path or "")
    if not p:
        return False
    xmp = _xmp_sidecar_path(p)

    ok_main = True
    if prefer_trash:
        ok_main = send2trash_file(p)
        if not ok_main:
            try:
                if os.path.exists(p):
                    os.remove(p)
                    ok_main = True
            except Exception:
                ok_main = False
    else:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            ok_main = False

    ok_xmp = True
    if xmp:
        if prefer_trash:
            ok_xmp = send2trash_file(xmp)
            if not ok_xmp:
                try:
                    if os.path.exists(xmp):
                        os.remove(xmp)
                        ok_xmp = True
                except Exception:
                    ok_xmp = False
        else:
            try:
                if os.path.exists(xmp):
                    os.remove(xmp)
            except Exception:
                ok_xmp = False

    return bool(ok_main and ok_xmp)


def rename_with_sidecar(old_path: str, new_path: str) -> bool:
    old_p = str(old_path or "")
    new_p = str(new_path or "")
    if not old_p or not new_p:
        return False

    old_xmp = _xmp_sidecar_path(old_p)
    new_xmp = _xmp_sidecar_path(new_p)

    os.rename(old_p, new_p)

    if old_xmp and new_xmp:
        try:
            if os.path.exists(old_xmp):
                try:
                    if os.path.exists(new_xmp):
                        try:
                            os.remove(new_xmp)
                        except Exception:
                            try:
                                send2trash_file(new_xmp)
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    os.rename(old_xmp, new_xmp)
                except Exception:
                    try:
                        shutil.copy2(old_xmp, new_xmp)
                        try:
                            os.remove(old_xmp)
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass
    return True


def move_with_sidecar(src_path: str, dst_path: str) -> bool:
    src = str(src_path or "")
    dst = str(dst_path or "")
    if not src or not dst:
        return False
    src_xmp = _xmp_sidecar_path(src)
    dst_xmp = _xmp_sidecar_path(dst)

    shutil.move(src, dst)

    if src_xmp and dst_xmp:
        try:
            if os.path.exists(src_xmp):
                try:
                    if os.path.exists(dst_xmp):
                        try:
                            os.remove(dst_xmp)
                        except Exception:
                            try:
                                send2trash_file(dst_xmp)
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    shutil.move(src_xmp, dst_xmp)
                except Exception:
                    try:
                        shutil.copy2(src_xmp, dst_xmp)
                        try:
                            os.remove(src_xmp)
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass
    return True


def copy2_with_sidecar(src_path: str, dst_path: str) -> bool:
    src = str(src_path or "")
    dst = str(dst_path or "")
    if not src or not dst:
        return False
    src_xmp = _xmp_sidecar_path(src)
    dst_xmp = _xmp_sidecar_path(dst)

    shutil.copy2(src, dst)

    if src_xmp and dst_xmp:
        try:
            if os.path.exists(src_xmp):
                try:
                    if os.path.exists(dst_xmp):
                        try:
                            os.remove(dst_xmp)
                        except Exception:
                            try:
                                send2trash_file(dst_xmp)
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    shutil.copy2(src_xmp, dst_xmp)
                except Exception:
                    pass
        except Exception:
            pass
    return True

