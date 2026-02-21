"""
图库前后端通信桥梁
处理Web前端和PyQt后端之间的通信
"""
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal
from typing import List, Dict
import json
from utils.log_manager import LogManager


class ImageLibraryBridge(QObject):
    """图库通信桥梁"""
    
    # 信号：通知前端更新
    treeUpdated = pyqtSignal(str)  # 文件树更新
    imagesUpdated = pyqtSignal(str)  # 图片列表更新
    imageDetailUpdated = pyqtSignal(str)  # 图片详情更新
    
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        LogManager.instance().debug("[ImageLibraryBridge] 初始化")
    
    @pyqtSlot(result=str)
    def getFolderTree(self) -> str:
        """
        获取文件夹树
        
        Returns:
            JSON格式的树结构
        """
        try:
            tree_data = self.manager.get_folder_tree()
            result = json.dumps(tree_data, ensure_ascii=False)
            LogManager.instance().debug(f"[ImageLibraryBridge] 获取文件树: {len(tree_data)} 个节点")
            return result
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 获取文件树失败: {e}")
            return '[]'
    
    @pyqtSlot(str, result=str)
    def getImagesByFolder(self, folder_id: str) -> str:
        """
        根据文件夹ID获取图片列表
        
        Args:
            folder_id: 文件夹ID
            
        Returns:
            JSON格式的图片列表
        """
        try:
            images = self.manager.get_images_by_folder(folder_id, limit=100)
            result = json.dumps(images, ensure_ascii=False)
            LogManager.instance().debug(f"[ImageLibraryBridge] 获取图片列表: {folder_id}, {len(images)} 张")
            return result
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 获取图片列表失败: {e}")
            return '[]'
    
    @pyqtSlot(str, result=str)
    def getImageDetail(self, image_id: str) -> str:
        """
        获取图片详细信息
        
        Args:
            image_id: 图片ID
            
        Returns:
            JSON格式的图片详情
        """
        try:
            detail = self.manager.get_image_detail(image_id)
            if detail:
                result = json.dumps(detail, ensure_ascii=False)
                LogManager.instance().debug(f"[ImageLibraryBridge] 获取图片详情: {image_id}")
                return result
            else:
                return '{}'
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 获取图片详情失败: {e}")
            return '{}'
    
    @pyqtSlot(str, int, result=bool)
    def updateRating(self, image_id: str, rating: int) -> bool:
        """
        更新图片评分
        
        Args:
            image_id: 图片ID
            rating: 评分 (0-5)
            
        Returns:
            是否成功
        """
        try:
            success = self.manager.update_rating(image_id, rating)
            LogManager.instance().debug(f"[ImageLibraryBridge] 更新评分: {image_id} -> {rating}, 结果: {success}")
            return success
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 更新评分失败: {e}")
            return False
    
    @pyqtSlot(str, bool, result=bool)
    def updateFavorite(self, image_id: str, favorite: bool) -> bool:
        """
        更新图片收藏状态
        
        Args:
            image_id: 图片ID
            favorite: 是否收藏
            
        Returns:
            是否成功
        """
        try:
            success = self.manager.update_favorite(image_id, favorite)
            LogManager.instance().debug(f"[ImageLibraryBridge] 更新收藏: {image_id} -> {favorite}, 结果: {success}")
            return success
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 更新收藏失败: {e}")
            return False
    
    @pyqtSlot(str)
    def logMessage(self, message: str):
        """
        前端日志
        
        Args:
            message: 日志消息
        """
        try:
            LogManager.instance().debug(f"[前端] {message}")
        except Exception:
            pass
    
    @pyqtSlot(str)
    def logError(self, message: str):
        """
        前端错误日志
        
        Args:
            message: 错误消息
        """
        try:
            LogManager.instance().error(f"[前端] {message}")
        except Exception:
            pass
    
    def notify_tree_updated(self):
        """通知前端文件树已更新"""
        try:
            tree_data = self.manager.get_folder_tree()
            result = json.dumps(tree_data, ensure_ascii=False)
            self.treeUpdated.emit(result)
            LogManager.instance().debug("[ImageLibraryBridge] 通知文件树更新")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 通知文件树更新失败: {e}")
    
    def notify_images_updated(self, folder_id: str = None):
        """
        通知前端图片列表已更新
        
        Args:
            folder_id: 文件夹ID，如果为None则使用当前文件夹
        """
        try:
            if folder_id is None:
                folder_id = self.manager.current_folder or ''
            
            images = self.manager.get_images_by_folder(folder_id, limit=100)
            result = json.dumps(images, ensure_ascii=False)
            self.imagesUpdated.emit(result)
            LogManager.instance().debug(f"[ImageLibraryBridge] 通知图片列表更新: {folder_id}")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 通知图片列表更新失败: {e}")
    
    def notify_image_detail_updated(self, image_id: str):
        """
        通知前端图片详情已更新
        
        Args:
            image_id: 图片ID
        """
        try:
            detail = self.manager.get_image_detail(image_id)
            if detail:
                result = json.dumps(detail, ensure_ascii=False)
                self.imageDetailUpdated.emit(result)
                LogManager.instance().debug(f"[ImageLibraryBridge] 通知图片详情更新: {image_id}")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryBridge] 通知图片详情更新失败: {e}")

