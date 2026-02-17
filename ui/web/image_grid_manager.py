"""图片网格业务逻辑管理器"""
import os
import base64
from typing import List, Dict, Any
from io import BytesIO

from utils.sql.data_base import BirdLibraryDB
from cache.cache_manager import ImageCacheManager
from utils.log_manager import LogManager
from utils.exif.exif_utils import ExifHandleWorker


class ImageGridManager:
    """图片网格业务逻辑管理器"""
    
    def __init__(self):
        self._db = None
        self._cache_manager = None
        self._current_folder = None
        self._current_filters = {}
        self._init_db()
        self._init_cache()
    
    def _init_db(self):
        """初始化数据库"""
        try:
            self._db = BirdLibraryDB()
            LogManager.instance().debug("[ImageGridManager] 数据库初始化成功")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 数据库初始化失败: {e}")
    
    def _init_cache(self):
        """初始化缓存管理器"""
        try:
            self._cache_manager = ImageCacheManager()
            LogManager.instance().debug("[ImageGridManager] 缓存管理器初始化成功")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 缓存管理器初始化失败: {e}")
    
    def set_current_folder(self, folder_path: str):
        """设置当前文件夹"""
        self._current_folder = folder_path
    
    def set_filters(self, filters: dict):
        """设置筛选条件"""
        self._current_filters = filters or {}
    
    def get_images(self, page: int = 1, page_size: int = 100, filters: dict = None) -> List[Dict[str, Any]]:
        """
        获取图片列表
        
        Args:
            page: 页码（从 1 开始）
            page_size: 每页数量
            filters: 筛选条件
        
        Returns:
            图片列表
        """
        if not self._db:
            return []
        
        try:
            # 构建查询条件
            where_clauses = []
            params = []
            
            # 当前文件夹筛选
            if self._current_folder:
                where_clauses.append("file_path LIKE ?")
                params.append(f"{self._current_folder}%")
            
            # 应用筛选条件
            if filters:
                # 物种筛选
                if filters.get('species'):
                    where_clauses.append("species_cls = ?")
                    params.append(filters['species'])
                
                # 评分筛选
                if filters.get('rating'):
                    where_clauses.append("rating >= ?")
                    params.append(filters['rating'])
                
                # 收藏筛选
                if filters.get('favorite'):
                    where_clauses.append("is_favorite = 1")
                
                # 色标筛选
                if filters.get('label'):
                    where_clauses.append("label = ?")
                    params.append(filters['label'])
            
            # 构建 SQL
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            offset = (page - 1) * page_size
            
            sql = f"""
                SELECT 
                    file_path,
                    species_cls,
                    rating,
                    score,
                    is_favorite,
                    label,
                    created_at,
                    shot_time,
                    order_cls,
                    family_cls,
                    genus_cls
                FROM bird_results
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            
            params.extend([page_size, offset])
            
            # 执行查询
            rows = self._db.execute_query(sql, params)
            
            # 转换为字典列表
            images = []
            for row in rows:
                images.append({
                    'file_path': row[0],
                    'species': row[1] or '未识别',
                    'rating': row[2] or 0,
                    'score': float(row[3]) if row[3] else 0.0,
                    'is_favorite': bool(row[4]),
                    'label': row[5] or '',
                    'created_at': row[6] or '',
                    'shot_time': row[7] or '',
                    'order': row[8] or '',
                    'family': row[9] or '',
                    'genus': row[10] or ''
                })
            
            LogManager.instance().debug(f"[ImageGridManager] 查询到 {len(images)} 张图片")
            return images
            
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 获取图片列表失败: {e}")
            return []
    
    def get_thumbnail(self, file_path: str) -> str:
        """
        获取缩略图（Base64 编码）
        
        Args:
            file_path: 图片文件路径
        
        Returns:
            Base64 编码的缩略图（data URL 格式）
        """
        try:
            # 尝试从缓存获取
            if self._cache_manager:
                pixmap = self._cache_manager.get_thumbnail(file_path)
                if pixmap and not pixmap.isNull():
                    return self._pixmap_to_base64(pixmap)
            
            # 缓存未命中，生成缩略图
            from PyQt6.QtGui import QPixmap
            pixmap = QPixmap(file_path)
            
            if pixmap.isNull():
                # 返回占位图
                return self._get_placeholder_image()
            
            # 缩放到合适大小
            max_size = 300
            if pixmap.width() > max_size or pixmap.height() > max_size:
                pixmap = pixmap.scaled(
                    max_size, max_size,
                    aspectRatioMode=1,  # Qt.AspectRatioMode.KeepAspectRatio
                    transformMode=1     # Qt.TransformationMode.SmoothTransformation
                )
            
            # 存入缓存
            if self._cache_manager:
                self._cache_manager.add_thumbnail(file_path, pixmap)
            
            return self._pixmap_to_base64(pixmap)
            
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 获取缩略图失败 ({file_path}): {e}")
            return self._get_placeholder_image()
    
    def _pixmap_to_base64(self, pixmap) -> str:
        """将 QPixmap 转换为 Base64 data URL"""
        try:
            from PyQt6.QtCore import QBuffer, QIODevice
            
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "JPEG", 85)
            
            image_data = buffer.data()
            b64 = base64.b64encode(image_data).decode('ascii')
            
            return f"data:image/jpeg;base64,{b64}"
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] Pixmap 转 Base64 失败: {e}")
            return self._get_placeholder_image()
    
    def _get_placeholder_image(self) -> str:
        """获取占位图"""
        # 返回一个简单的 SVG 占位图
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
            <rect width="200" height="200" fill="#1a1a2e"/>
            <text x="100" y="100" text-anchor="middle" dominant-baseline="middle" 
                  font-family="Arial" font-size="48" fill="#666">📷</text>
        </svg>'''
        b64 = base64.b64encode(svg.encode()).decode()
        return f"data:image/svg+xml;base64,{b64}"
    
    def open_image(self, file_path: str):
        """
        打开图片（通知主窗口显示预览）
        
        Args:
            file_path: 图片文件路径
        """
        try:
            # 这里可以发送信号给主窗口，让它显示预览面板
            LogManager.instance().debug(f"[ImageGridManager] 打开图片: {file_path}")
            # TODO: 实现与主窗口的通信
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 打开图片失败: {e}")
    
    def update_rating(self, file_path: str, rating: int):
        """
        更新图片评分
        
        Args:
            file_path: 图片文件路径
            rating: 评分 (1-5)
        """
        if not self._db:
            return
        
        try:
            # 更新数据库
            sql = "UPDATE bird_results SET rating = ? WHERE file_path = ?"
            self._db.execute_update(sql, (rating, file_path))
            
            # 更新 EXIF
            ExifHandleWorker.get_instance().update_rating(file_path, rating)
            
            LogManager.instance().debug(f"[ImageGridManager] 更新评分: {file_path} -> {rating}")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 更新评分失败: {e}")
    
    def update_favorite(self, file_path: str, is_favorite: bool):
        """
        更新收藏状态
        
        Args:
            file_path: 图片文件路径
            is_favorite: 是否收藏
        """
        if not self._db:
            return
        
        try:
            sql = "UPDATE bird_results SET is_favorite = ? WHERE file_path = ?"
            self._db.execute_update(sql, (1 if is_favorite else 0, file_path))
            
            LogManager.instance().debug(f"[ImageGridManager] 更新收藏: {file_path} -> {is_favorite}")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 更新收藏失败: {e}")
    
    def update_label(self, file_path: str, label: str):
        """
        更新色标
        
        Args:
            file_path: 图片文件路径
            label: 色标
        """
        if not self._db:
            return
        
        try:
            sql = "UPDATE bird_results SET label = ? WHERE file_path = ?"
            self._db.execute_update(sql, (label, file_path))
            
            # 更新 EXIF
            ExifHandleWorker.get_instance().update_label(file_path, label)
            
            LogManager.instance().debug(f"[ImageGridManager] 更新色标: {file_path} -> {label}")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 更新色标失败: {e}")
    
    def delete_images(self, file_paths: List[str]):
        """
        删除图片
        
        Args:
            file_paths: 文件路径列表
        """
        if not self._db:
            return
        
        try:
            for file_path in file_paths:
                # 从数据库删除
                sql = "DELETE FROM bird_results WHERE file_path = ?"
                self._db.execute_update(sql, (file_path,))
                
                # 删除文件
                if os.path.exists(file_path):
                    os.remove(file_path)
            
            LogManager.instance().debug(f"[ImageGridManager] 删除 {len(file_paths)} 张图片")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 删除图片失败: {e}")
    
    def release_cache(self):
        """释放缓存"""
        try:
            if self._cache_manager:
                self._cache_manager.clear()
                LogManager.instance().debug("[ImageGridManager] 缓存已释放")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridManager] 释放缓存失败: {e}")


