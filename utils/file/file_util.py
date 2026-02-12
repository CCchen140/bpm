import os
import ctypes
from ctypes import wintypes


def _get_windows_file_id(file_path: str) -> str | None:
    """
    获取 Windows 下更稳定的“文件实例标识”。
    
    设计目标：
    - 计算非常快：只调用一次 Win32 API，不读文件内容
    - 不会轻易改变：同一文件在同一卷内重命名/移动路径时仍保持一致
    - 允许复制导致变化：复制本质上是新文件，fast_id 变化是合理的
    
    返回值：
    - 成功："{VolumeSerialNumber}_{FileIndex}" 字符串
    - 失败：None
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    CreateFileW.restype = wintypes.HANDLE

    GetFileInformationByHandle = kernel32.GetFileInformationByHandle
    GetFileInformationByHandle.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    GetFileInformationByHandle.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x00000080

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", FILETIME),
            ("ftLastAccessTime", FILETIME),
            ("ftLastWriteTime", FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    p = str(file_path or "")
    if not p:
        return None
    try:
        p = os.path.abspath(p)
    except Exception:
        pass

    handle = CreateFileW(
        p,
        0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        return None

    try:
        info = BY_HANDLE_FILE_INFORMATION()
        ok = GetFileInformationByHandle(handle, ctypes.byref(info))
        if not ok:
            return None
        file_index = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
        return f"{int(info.dwVolumeSerialNumber)}_{file_index}"
    finally:
        try:
            CloseHandle(handle)
        except Exception:
            pass


def get_fast_id(file_path: str) -> str | None:
    """
    计算 fast_id（快速且相对稳定的文件标识）。
    
    约束与选择：
    - 不能用 file_path 本身：路径会被移动/重命名改变
    - 不能读全文件做哈希：对大文件与批量场景太慢
    - 优先使用系统级文件标识（Windows FileIndex / 类 Unix inode）
    - 系统级标识不可用时，才降级到“创建时间/变更时间”等统计信息组合
    
    参数：
    - file_path: 文件绝对路径或可解析路径
    
    返回：
    - fast_id 字符串；失败返回 None
    """
    try:
        if os.name == "nt":
            fid = _get_windows_file_id(file_path)
            if fid:
                return fid

        st = os.stat(file_path)

        file_key = getattr(st, "st_ino", None)
        create_time = getattr(st, "st_birthtime", None)
        if create_time is None:
            create_time = getattr(st, "st_ctime", None)

        # 这里使用 inode + 创建时间（或 ctime）作为主组合，避免 mtime 变动导致 fast_id 频繁变化
        if file_key is not None and create_time is not None:
            return f"{int(file_key)}_{int(create_time)}"

        return f"{int(st.st_ctime)}"
    except Exception:
        return None

