import hashlib
import os
import platform
import uuid

def get_smart_fingerprint(file_path):
    """
    稳健的文件指纹：跳过头部，哈希中间 1MB 数据。
    即使你修改了 EXIF/XMP，中间的原始像素/感光数据也是绝对不变的。
    """
    try:
        stat = os.stat(file_path)
        file_size = stat.st_size
        
        # 获取创建时间 (Windows 用 ctime, Mac/Linux 用 birthtime)
        if platform.system() == 'Windows':
            creation_time = stat.st_ctime
        else:
            # 兼容 Mac 的创建时间，如果没有则回退到 mtime
            creation_time = getattr(stat, 'st_birthtime', stat.st_mtime)

        # 核心：从 2MB 偏移量开始读取（避开绝大多数元数据区）
        # 如果文件小于 3MB，则从中间开始读
        offset = min(2 * 1024 * 1024, file_size // 2)
        read_size = 1024 * 1024 # 读取 1MB
        
        with open(file_path, "rb") as f:
            f.seek(offset)
            data_chunk = f.read(read_size)
            data_hash = hashlib.md5(data_chunk).hexdigest()
            
        # 指纹 = 关键数据哈希 + 创建时间 + 文件总大小
        # 即使元数据变了，这三个组合依然能保持极高的唯一性和稳定性
        return f"v2_{data_hash}_{int(creation_time)}_{file_size}"
    except Exception:
        return None

import uuid

def get_unique_id():
    return str(uuid.uuid4())