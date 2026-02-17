"""图片网格 Web 页面通信桥梁"""
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
import json
import base64
from typing import Optional

from utils.log_manager import LogManager


class ImageGridBridge(QObject):
    """图片网格通信桥梁"""
    
    # 信号：后端主动推送到前端
    imagesUpdated = pyqtSignal()  # 图片列表更新
    
    def __init__(self, manager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = manager
    
    def _log_debug(self, msg: str):
        try:
            LogManager.instance().debug(f"[ImageGridBridge] {msg}")
        except Exception:
            pass
    
    def _log_error(self, msg: str):
        try:
            LogManager.instance().error(f"[ImageGridBridge] {msg}")
        except Exception:
            pass
    
    def _success_response(self, data) -> str:
        """成功响应"""
        return json.dumps({
            "ok": True,
            "data": data,
            "error": None
        }, ensure_ascii=False)
    
    def _error_response(self, error: str) -> str:
        """错误响应"""
        return json.dumps({
            "ok": False,
            "data": None,
            "error": error
        }, ensure_ascii=False)
    
    @pyqtSlot(str, result=str)
    def getImages(self, params: str) -> str:
        """
        获取图片列表
        
        Args:
            params: JSON 字符串，格式: {"page": 1, "pageSize": 100, "filters": {...}}
        
        Returns:
            JSON 响应
        """
        try:
            self._log_debug(f"getImages 调用: {params}")
            
            # 解析参数
            try:
                param_obj = json.loads(params) if params else {}
            except Exception:
                param_obj = {}
            
            page = int(param_obj.get('page', 1))
            page_size = int(param_obj.get('pageSize', 100))
            filters = param_obj.get('filters', {})
            
            # 调用管理器获取数据
            images = self._manager.get_images(page, page_size, filters)
            
            result = {
                "images": images,
                "page": page,
                "pageSize": page_size,
                "total": len(images)
            }
            
            self._log_debug(f"返回 {len(images)} 张图片")
            return self._success_response(result)
            
        except Exception as e:
            self._log_error(f"getImages 失败: {e}")
            return self._error_response(str(e))
    
    @pyqtSlot(str, result=str)
    def getThumbnail(self, file_path: str) -> str:
        """
        获取缩略图（Base64）
        
        Args:
            file_path: 图片文件路径
        
        Returns:
            JSON 响应，包含 Base64 编码的缩略图
        """
        try:
            # 调用管理器获取缩略图
            thumbnail_b64 = self._manager.get_thumbnail(file_path)
            
            result = {
                "thumbnail": thumbnail_b64,
                "file_path": file_path
            }
            
            return self._success_response(result)
            
        except Exception as e:
            self._log_error(f"getThumbnail 失败 ({file_path}): {e}")
            return self._error_response(str(e))
    
    @pyqtSlot(str, result=str)
    def openImage(self, file_path: str) -> str:
        """
        打开图片（通知主窗口显示预览）
        
        Args:
            file_path: 图片文件路径
        
        Returns:
            JSON 响应
        """
        try:
            self._log_debug(f"openImage: {file_path}")
            self._manager.open_image(file_path)
            return self._success_response({"opened": True})
        except Exception as e:
            self._log_error(f"openImage 失败: {e}")
            return self._error_response(str(e))
    
    @pyqtSlot(str, int, result=str)
    def updateRating(self, file_path: str, rating: int) -> str:
        """
        更新图片评分
        
        Args:
            file_path: 图片文件路径
            rating: 评分 (1-5)
        
        Returns:
            JSON 响应
        """
        try:
            self._log_debug(f"updateRating: {file_path} -> {rating}")
            self._manager.update_rating(file_path, rating)
            return self._success_response({"updated": True})
        except Exception as e:
            self._log_error(f"updateRating 失败: {e}")
            return self._error_response(str(e))
    
    @pyqtSlot(str, bool, result=str)
    def updateFavorite(self, file_path: str, is_favorite: bool) -> str:
        """
        更新收藏状态
        
        Args:
            file_path: 图片文件路径
            is_favorite: 是否收藏
        
        Returns:
            JSON 响应
        """
        try:
            self._log_debug(f"updateFavorite: {file_path} -> {is_favorite}")
            self._manager.update_favorite(file_path, is_favorite)
            return self._success_response({"updated": True})
        except Exception as e:
            self._log_error(f"updateFavorite 失败: {e}")
            return self._error_response(str(e))
    
    @pyqtSlot(str, str, result=str)
    def updateLabel(self, file_path: str, label: str) -> str:
        """
        更新色标
        
        Args:
            file_path: 图片文件路径
            label: 色标 (Red/Green/Blue/Yellow/Purple/Orange/Pink/White/Black)
        
        Returns:
            JSON 响应
        """
        try:
            self._log_debug(f"updateLabel: {file_path} -> {label}")
            self._manager.update_label(file_path, label)
            return self._success_response({"updated": True})
        except Exception as e:
            self._log_error(f"updateLabel 失败: {e}")
            return self._error_response(str(e))
    
    @pyqtSlot(str, result=str)
    def deleteImages(self, file_paths_json: str) -> str:
        """
        删除图片
        
        Args:
            file_paths_json: JSON 数组，文件路径列表
        
        Returns:
            JSON 响应
        """
        try:
            file_paths = json.loads(file_paths_json)
            self._log_debug(f"deleteImages: {len(file_paths)} 张")
            self._manager.delete_images(file_paths)
            return self._success_response({"deleted": len(file_paths)})
        except Exception as e:
            self._log_error(f"deleteImages 失败: {e}")
            return self._error_response(str(e))
    
    def notify_images_updated(self):
        """通知前端图片列表已更新"""
        try:
            self.imagesUpdated.emit()
        except Exception as e:
            self._log_error(f"notify_images_updated 失败: {e}")


