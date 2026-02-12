import ctypes
import os
import uuid
from ctypes import wintypes


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

    @classmethod
    def from_str(cls, s):
        u = uuid.UUID(str(s))
        data4 = (wintypes.BYTE * 8).from_buffer_copy(u.bytes[8:])
        return cls(u.time_low, u.time_mid, u.time_hi_version, data4)


def _hresult_failed(hr):
    return hr < 0


def _vtable_method(ptr, index, restype, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn


def _release(ptr):
    if not ptr:
        return
    try:
        _vtable_method(ptr, 2, wintypes.ULONG)  # IUnknown::Release
        _vtable_method(ptr, 2, wintypes.ULONG)(ptr)
    except Exception:
        pass


def select_folders(parent_hwnd=0, title="选择导入目录（可多选）", initial_dir=None):
    if os.name != "nt":
        return []

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    COINIT_APARTMENTTHREADED = 0x2
    CLSCTX_INPROC_SERVER = 0x1

    CLSID_FileOpenDialog = _GUID.from_str("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
    IID_IFileOpenDialog = _GUID.from_str("{D57C7288-D4AD-4768-BE02-9D969532D960}")

    FOS_PICKFOLDERS = 0x00000020
    FOS_FORCEFILESYSTEM = 0x00000040
    FOS_ALLOWMULTISELECT = 0x00000200
    FOS_PATHMUSTEXIST = 0x00000800
    FOS_NOCHANGEDIR = 0x00000008

    SIGDN_FILESYSPATH = 0x80058000

    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if _hresult_failed(hr):
        return []

    dialog = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_FileOpenDialog),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_IFileOpenDialog),
            ctypes.byref(dialog),
        )
        if _hresult_failed(hr) or not dialog:
            return []

        get_options = _vtable_method(dialog, 10, wintypes.HRESULT, ctypes.POINTER(wintypes.DWORD))
        set_options = _vtable_method(dialog, 9, wintypes.HRESULT, wintypes.DWORD)
        set_title = _vtable_method(dialog, 17, wintypes.HRESULT, wintypes.LPCWSTR)
        show = _vtable_method(dialog, 3, wintypes.HRESULT, wintypes.HWND)
        get_results = _vtable_method(dialog, 27, wintypes.HRESULT, ctypes.POINTER(ctypes.c_void_p))

        opts = wintypes.DWORD(0)
        hr = get_options(dialog, ctypes.byref(opts))
        if not _hresult_failed(hr):
            new_opts = int(opts.value) | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_ALLOWMULTISELECT | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR
            set_options(dialog, wintypes.DWORD(new_opts))

        try:
            set_title(dialog, str(title or "选择导入目录（可多选）"))
        except Exception:
            pass

        hr = show(dialog, wintypes.HWND(int(parent_hwnd or 0)))
        if hr == 0x800704C7:
            return []
        if _hresult_failed(hr):
            return []

        results = ctypes.c_void_p()
        hr = get_results(dialog, ctypes.byref(results))
        if _hresult_failed(hr) or not results:
            return []

        get_count = _vtable_method(results, 7, wintypes.HRESULT, ctypes.POINTER(wintypes.DWORD))
        get_item_at = _vtable_method(results, 8, wintypes.HRESULT, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))

        count = wintypes.DWORD(0)
        hr = get_count(results, ctypes.byref(count))
        if _hresult_failed(hr):
            _release(results)
            return []

        out = []
        for i in range(int(count.value)):
            item = ctypes.c_void_p()
            hr = get_item_at(results, wintypes.DWORD(i), ctypes.byref(item))
            if _hresult_failed(hr) or not item:
                continue

            get_display_name = _vtable_method(item, 5, wintypes.HRESULT, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))
            psz = wintypes.LPWSTR()
            hr = get_display_name(item, wintypes.DWORD(SIGDN_FILESYSPATH), ctypes.byref(psz))
            if not _hresult_failed(hr) and psz:
                try:
                    out.append(str(psz))
                except Exception:
                    pass
                try:
                    ole32.CoTaskMemFree(psz)
                except Exception:
                    pass
            _release(item)

        _release(results)
        return [p for p in out if p]
    finally:
        _release(dialog)
        try:
            ole32.CoUninitialize()
        except Exception:
            pass

