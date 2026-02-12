import cv2
import numpy as np
from PyQt6.QtGui import QImage


def get_gpu_summary() -> str:
    parts = []
    try:
        import torch

        try:
            if bool(torch.cuda.is_available()) and int(torch.cuda.device_count() or 0) > 0:
                try:
                    name = str(torch.cuda.get_device_name(0) or "")
                except Exception:
                    name = ""
                parts.append(f"torch.cuda={True} devices={int(torch.cuda.device_count() or 0)} name={name}".strip())
            else:
                parts.append("torch.cuda=False")
        except Exception:
            pass
    except Exception:
        pass
    try:
        ok_cv = is_opencv_cuda_usable()
        parts.append(f"opencv.cuda={bool(ok_cv)}")
    except Exception:
        pass
    return " | ".join([p for p in parts if p])


def is_torch_cuda_usable() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        ok = bool(torch.cuda.is_available())
    except Exception:
        return False
    if not ok:
        return False
    try:
        if int(getattr(torch.cuda, "device_count", lambda: 0)() or 0) <= 0:
            return False
    except Exception:
        return False
    try:
        torch.cuda.current_device()
        try:
            torch.cuda.get_device_name(0)
        except Exception:
            pass
    except Exception:
        return False
    try:
        _ = torch.empty((1,), device="cuda")
        del _
    except Exception:
        return False
    return True


def is_opencv_cuda_usable() -> bool:
    try:
        if not hasattr(cv2, "cuda"):
            return False
        return int(cv2.cuda.getCudaEnabledDeviceCount() or 0) > 0
    except Exception:
        return False


class GPUScaler:
    _checked = False
    _available = False
    _backend = None
    _suspended = False

    @classmethod
    def is_available(cls):
        try:
            if bool(getattr(cls, "_suspended", False)):
                return False
        except Exception:
            pass
        if not cls._checked:
            try:
                if hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0:
                    cls._backend = "cuda"
            except Exception:
                cls._backend = None
            if cls._backend is None:
                try:
                    if hasattr(cv2, "ocl") and cv2.ocl.haveOpenCL():
                        cv2.ocl.setUseOpenCL(True)
                        if cv2.ocl.useOpenCL():
                            cls._backend = "opencl"
                except Exception:
                    cls._backend = None
            cls._available = cls._backend is not None
            cls._checked = True
        return cls._available

    @classmethod
    def set_suspended(cls, suspended: bool = True):
        try:
            cls._suspended = bool(suspended)
        except Exception:
            cls._suspended = True

    @classmethod
    def scale_qimage(cls, image, target_w, target_h, keep_aspect=True, fast_mode=False):
        if image is None or image.isNull():
            return None
        try:
            if bool(getattr(cls, "_suspended", False)):
                return None
        except Exception:
            return None
        if not cls.is_available():
            return None
        try:
            src = image.convertToFormat(QImage.Format.Format_RGB888)
            src_w = int(src.width())
            src_h = int(src.height())
            if src_w <= 0 or src_h <= 0:
                return None
            if keep_aspect:
                scale = min(float(target_w) / src_w, float(target_h) / src_h)
                new_w = max(1, int(round(src_w * scale)))
                new_h = max(1, int(round(src_h * scale)))
            else:
                new_w = max(1, int(target_w))
                new_h = max(1, int(target_h))
            if new_w == src_w and new_h == src_h:
                return src
            bytes_per_line = int(src.bytesPerLine())
            ptr = src.bits()
            ptr.setsize(src_h * bytes_per_line)
            arr = np.frombuffer(ptr, np.uint8).reshape((src_h, bytes_per_line))
            arr = arr[:, :src_w * 3].reshape((src_h, src_w, 3))
            interpolation = cv2.INTER_NEAREST if fast_mode else cv2.INTER_LINEAR
            if cls._backend == "cuda":
                gpu_mat = cv2.cuda_GpuMat()
                gpu_mat.upload(arr)
                resized = cv2.cuda.resize(gpu_mat, (new_w, new_h), interpolation=interpolation)
                out = resized.download()
            elif cls._backend == "opencl":
                umat = cv2.UMat(arr)
                resized = cv2.resize(umat, (new_w, new_h), interpolation=interpolation)
                out = resized.get()
            else:
                return None
            if out is None:
                return None
            out_bpl = int(out.strides[0])
            return QImage(out.data, new_w, new_h, out_bpl, QImage.Format.Format_RGB888).copy()
        except Exception:
            return None
