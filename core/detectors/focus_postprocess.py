"""
对焦检测后处理函数集 — 无状态、可并行
所有函数仅依赖 numpy/opencv，不依赖 BirdFocusDetector 实例。
"""

import cv2
import numpy as np
from typing import Dict, Any


def compute_sharpness_score(
    laplacian: np.ndarray,
    mask: np.ndarray,
    min_pixels: int = 500,
    percentile: float = 95,
    multiplier: float = 1.2,
    erosion_kernel: tuple = (5, 5),
    erosion_iter: int = 1,
    preprocess_mask: bool = True,
) -> float:
    """
    计算清晰度评分（无状态版本）
    
    参数:
        laplacian: 拉普拉斯响应图
        mask: 掩码区域
        min_pixels: 最小有效像素数
        percentile: 百分位阈值
        multiplier: 乘数因子
        erosion_kernel: 腐蚀核大小
        erosion_iter: 腐蚀迭代次数
        preprocess_mask: 是否预处理掩码
        
    返回:
        清晰度评分，值越高表示越清晰
    """
    if laplacian is None or mask is None:
        return 0.0
    
    if preprocess_mask and erosion_iter > 0:
        binary_mask = (mask > 0).astype(np.uint8) * 255
        kernel = np.ones(erosion_kernel, np.uint8)
        processed_mask = cv2.erode(binary_mask, kernel, iterations=erosion_iter)
    else:
        processed_mask = mask

    try:
        valid_pixels = np.abs(laplacian[processed_mask > 0])
    except Exception:
        return 0.0

    if len(valid_pixels) < min_pixels:
        return 0.0

    # 计算鲁棒的统计量
    median_val = float(np.median(valid_pixels))
    mad_val = float(np.median(np.abs(valid_pixels - median_val)))
    
    # 绝对模糊判断: 如果中位数太低，直接返回0
    ABSOLUTE_BLUR_THRESHOLD = 3.0
    if median_val < ABSOLUTE_BLUR_THRESHOLD:
        return 0.0

    # 使用鲁棒的分数计算
    base_score = median_val * median_val
    
    # 使用MAD作为离散度的鲁棒度量
    mad_factor = 1.0 + (mad_val / (median_val + 1e-6))
    mad_factor = min(mad_factor, 2.0)
    
    # 计算高分区域贡献
    limit_val = np.percentile(valid_pixels, percentile)
    trimmed = valid_pixels[valid_pixels <= limit_val]
    if len(trimmed) > 0:
        high_percentile_val = float(np.percentile(trimmed, 75))
        high_score_contribution = high_percentile_val * 0.5
    else:
        high_score_contribution = 0.0
    
    # 综合评分
    final_score = (base_score * mad_factor + high_score_contribution) * multiplier
    
    if not np.isfinite(final_score) or final_score <= 0:
        return 0.0
        
    return float(final_score)


def compute_texture_richness(
    gray_img: np.ndarray,
    bird_mask: np.ndarray,
    background_mask: np.ndarray | None = None,
) -> Dict[str, float]:
    """
    计算纹理丰富度（无状态版本）
    
    返回:
        {
            "edge_density": float,
            "edge_density_bg": float,
            "edge_density_ratio": float,
            "entropy": float,
            "entropy_bg": float,
            "entropy_ratio": float,
        }
    """
    if gray_img is None or not isinstance(gray_img, np.ndarray) or gray_img.size <= 0:
        return {
            "edge_density": 0.0, "edge_density_bg": 0.0, "edge_density_ratio": 1.0,
            "entropy": 0.0, "entropy_bg": 0.0, "entropy_ratio": 1.0
        }
    if bird_mask is None or not isinstance(bird_mask, np.ndarray) or bird_mask.size <= 0:
        return {
            "edge_density": 0.0, "edge_density_bg": 0.0, "edge_density_ratio": 1.0,
            "entropy": 0.0, "entropy_bg": 0.0, "entropy_ratio": 1.0
        }
    
    try:
        # 计算边缘密度
        sobelx = cv2.Sobel(gray_img, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray_img, cv2.CV_64F, 0, 1, ksize=3)
        sobel_mag = np.sqrt(sobelx**2 + sobely**2)
        
        bird_pixels = np.sum(bird_mask > 0)
        if bird_pixels > 0:
            edge_density = float(np.mean(sobel_mag[bird_mask > 0]))
        else:
            edge_density = 0.0
        
        # 背景边缘密度
        edge_density_bg = 0.0
        if background_mask is not None and background_mask.size > 0:
            bg_pixels = np.sum(background_mask > 0)
            if bg_pixels > 0:
                edge_density_bg = float(np.mean(sobel_mag[background_mask > 0]))
        
        edge_density_ratio = edge_density / (edge_density_bg + 1e-6)
        
        # 计算熵
        def _compute_entropy(img, mask):
            if mask is None or np.sum(mask > 0) == 0:
                return 0.0
            try:
                roi = img[mask > 0]
                hist = cv2.calcHist([roi.astype(np.uint8)], [0], None, [256], [0, 256])
                hist = hist.flatten() / (hist.sum() + 1e-10)
                entropy = -np.sum(hist * np.log2(hist + 1e-10))
                return float(entropy)
            except Exception:
                return 0.0
        
        entropy = _compute_entropy(gray_img, bird_mask)
        entropy_bg = _compute_entropy(gray_img, background_mask) if background_mask is not None else 0.0
        entropy_ratio = entropy / (entropy_bg + 1e-6)
        
        return {
            "edge_density": edge_density,
            "edge_density_bg": edge_density_bg,
            "edge_density_ratio": edge_density_ratio,
            "entropy": entropy,
            "entropy_bg": entropy_bg,
            "entropy_ratio": entropy_ratio,
        }
    except Exception:
        return {
            "edge_density": 0.0, "edge_density_bg": 0.0, "edge_density_ratio": 1.0,
            "entropy": 0.0, "entropy_bg": 0.0, "entropy_ratio": 1.0
        }


def compute_absolute_blur_metrics(
    gray_img: np.ndarray,
    mask: np.ndarray | None = None,
) -> Dict[str, Any]:
    """
    计算绝对模糊指标（无状态版本）
    
    返回:
        {
            "is_blur": bool,
            "confidence": float,
            "metrics": dict,
        }
    """
    if gray_img is None or not isinstance(gray_img, np.ndarray) or gray_img.size <= 0:
        return {"is_blur": True, "confidence": 1.0, "metrics": {}}
    
    try:
        if mask is not None and mask.size > 0:
            roi = gray_img[mask > 0]
        else:
            roi = gray_img
        
        if roi.size == 0:
            return {"is_blur": True, "confidence": 1.0, "metrics": {}}
        
        # 拉普拉斯方差
        laplacian = cv2.Laplacian(roi, cv2.CV_64F)
        lap_var = float(np.var(laplacian))
        
        # Sobel 边缘检测
        sobelx = cv2.Sobel(roi, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(roi, cv2.CV_64F, 0, 1, ksize=3)
        sobel_mean = float(np.mean(np.sqrt(sobelx**2 + sobely**2)))
        
        # 高频成分分析
        fft = np.fft.fft2(roi)
        fft_shift = np.fft.fftshift(fft)
        magnitude = np.abs(fft_shift)
        h, w = magnitude.shape
        cy, cx = h // 2, w // 2
        
        # 计算高频能量比例
        low_freq_radius = min(h, w) // 8
        y, x = np.ogrid[:h, :w]
        mask_low = (x - cx)**2 + (y - cy)**2 <= low_freq_radius**2
        low_energy = np.sum(magnitude[mask_low])
        total_energy = np.sum(magnitude)
        high_freq_ratio = 1.0 - (low_energy / (total_energy + 1e-10))
        
        metrics = {
            "laplacian_var": lap_var,
            "sobel_mean": sobel_mean,
            "high_freq_ratio": high_freq_ratio,
        }
        
        # 模糊判断阈值
        BLUR_THRESHOLD_LAP_VAR = 100.0
        BLUR_THRESHOLD_SOBEL = 10.0
        BLUR_THRESHOLD_HF = 0.1
        
        blur_votes = 0
        if lap_var < BLUR_THRESHOLD_LAP_VAR:
            blur_votes += 1
        if sobel_mean < BLUR_THRESHOLD_SOBEL:
            blur_votes += 1
        if high_freq_ratio < BLUR_THRESHOLD_HF:
            blur_votes += 1
        
        is_blur = blur_votes >= 2
        confidence = blur_votes / 3.0
        
        return {
            "is_blur": is_blur,
            "confidence": confidence,
            "metrics": metrics,
        }
    except Exception:
        return {"is_blur": True, "confidence": 1.0, "metrics": {}}


def postprocess_single_image(detector, item: dict, wanted: set) -> dict:
    """
    对单张图片的 YOLO 分割结果执行完整 CPU 后处理。
    
    参数:
        detector: BirdFocusDetector 实例（用于调用部分方法）
        item: 包含预处理结果和分割结果的字典
        wanted: 需要返回的字段集合
        
    返回:
        包含后处理结果的字典
    """
    result = {
        "path": item.get("path", ""),
        "filename": item.get("filename", ""),
        "has_bird": False,
        "score": 0.0,
        "norm_score": 0.0,
    }
    
    image_small = item.get("image_small")
    masks_xy_list = item.get("masks_xy_list", [])
    
    if not masks_xy_list or image_small is None:
        return result
    
    result["has_bird"] = True
    
    try:
        # 转换为灰度图
        if len(image_small.shape) == 3:
            gray = cv2.cvtColor(image_small, cv2.COLOR_BGR2GRAY)
        else:
            gray = image_small
        
        # CLAHE 增强
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
        except Exception:
            pass
        
        # 拉普拉斯计算
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        
        # 获取第一个鸟的掩码
        first_mask = masks_xy_list[0] if masks_xy_list else None
        if first_mask is not None and len(first_mask) > 0:
            # 创建掩码图像
            h, w = gray.shape[:2]
            mask_img = np.zeros((h, w), dtype=np.uint8)
            try:
                pts = first_mask.reshape((-1, 1, 2)).astype(np.int32)
                cv2.fillPoly(mask_img, [pts], 255)
            except Exception:
                pass
            
            # 计算清晰度评分
            if np.sum(mask_img > 0) > 0:
                score = compute_sharpness_score(laplacian, mask_img)
                result["score"] = score
                # 归一化分数：使用全局背景作为基准进行归一化
                # 计算全局拉普拉斯响应作为基准
                global_lap = np.abs(laplacian).mean()
                global_score = global_lap * 100.0  # 缩放因子
                if global_score > 0:
                    norm_score = (score / global_score) * 100.0
                else:
                    # 全局模糊但鸟区域可能清晰，使用绝对分数
                    norm_score = score
                result["norm_score"] = float(max(0.0, min(200.0, norm_score)))
                
                # 纹理丰富度
                if "texture" in wanted or "texture_edge_density" in wanted:
                    texture = compute_texture_richness(gray, mask_img)
                    result.update({
                        "texture_edge_density": texture.get("edge_density", 0.0),
                        "texture_edge_density_bg": texture.get("edge_density_bg", 0.0),
                        "texture_edge_density_ratio": texture.get("edge_density_ratio", 1.0),
                        "texture_entropy": texture.get("entropy", 0.0),
                        "texture_entropy_bg": texture.get("entropy_bg", 0.0),
                        "texture_entropy_ratio": texture.get("entropy_ratio", 1.0),
                    })
                
                # 模糊检测
                blur_metrics = compute_absolute_blur_metrics(gray, mask_img)
                result["is_blur"] = blur_metrics.get("is_blur", False)
                result["blur_confidence"] = blur_metrics.get("confidence", 0.0)
        
    except Exception as e:
        result["_error"] = str(e)
    
    return result
