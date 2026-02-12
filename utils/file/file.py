import os
import rawpy
import cv2
import numpy as np
import exifread
from utils.file.file_util import get_fast_id
from utils.log_manager import LogManager
from utils.system.stderr_suppressor import suppress_stderr_fd

raw_exts = ['.NEF', '.RAW', '.CR2', '.CR3', '.RAF', '.ORF', '.DNG',  '.ARW',]
img_exts = ['.JPG', '.JPEG', '.PNG', '.BMP', '.GIF', '.TIFF', '.TIF', '.WEBP']

def load_image(file_path):
    """
    智能加载函数：
    - 如果是普通图片，直接读取
    - 如果是 RAW，提取嵌入的 JPEG 缩略图 (速度极快)
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    try:
        # 1. 处理 RAW 文件
        if ext.upper() in raw_exts:
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
                    # 解码二进制流为图像
                    img_array = np.frombuffer(thumb.data, dtype=np.uint8)
                    with suppress_stderr_fd():
                        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    return image
                else:
                    # 极少情况是 Bitmap 格式
                    return None

        # 2. 处理普通图片
        elif ext.upper() in img_exts:
            # 使用 imdecode 支持中文路径
            img_array = np.fromfile(file_path, dtype=np.uint8)
            with suppress_stderr_fd():
                return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
    except Exception as e:
        try:
            LogManager.instance().warning(f"读取图片失败: {file_path}: {e}")
        except Exception:
            pass
        return None
    
    return None

def extract_thumbnail(file_path):
    try:
        # 这里必须重新 open，因为上面的 with open 可能已经关闭了文件或指针位置不对
        with open(file_path, 'rb') as f:
            tags = exifread.process_file(f, details=False)
            if 'JPEGThumbnail' in tags:
                thumb_data = tags['JPEGThumbnail']
                img_array = np.frombuffer(thumb_data, dtype=np.uint8)
                with suppress_stderr_fd():
                    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except ImportError:
        pass
    except Exception as e:
        try:
            LogManager.instance().warning(f"读取缩略图 EXIF 失败: {e}")
        except Exception:
            pass

    return None

def load_raw_full(file_path):
    """
    加载 RAW 原图（解码）
    Returns:
        numpy array (RGB) or None
    """
    try:
        with rawpy.imread(file_path) as raw:
            rgb = raw.postprocess()
            return rgb
    except Exception as e:
        try:
            LogManager.instance().warning(f"加载 RAW 原图失败: {file_path}: {e}")
        except Exception:
            pass
        return None
