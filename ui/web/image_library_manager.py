"""
图库业务逻辑管理器
负责从数据库读取图库数据、处理图片编码等
"""
import os
import base64
from typing import List, Dict, Optional
from utils.sql.data_base import BirdLibraryDB
from utils.log_manager import LogManager


class ImageLibraryManager:
    """图库管理器"""
    
    def __init__(self):
        self.db = BirdLibraryDB()
        self.current_folder = None
        self.current_image = None
        self._tree_cache = None
        self._image_cache = {}
        
    def get_folder_tree(self) -> List[Dict]:
        """
        获取文件夹树结构
        
        Returns:
            树结构列表
        """
        try:
            if self._tree_cache is not None:
                return self._tree_cache
            
            # 从数据库获取所有物种分类
            tree_data = []
            
            # 获取所有目
            orders = self.db.get_all_orders()
            for order in orders:
                order_node = {
                    'id': f'order_{order}',
                    'label': order,
                    'type': 'order',
                    'children': []
                }
                
                # 获取该目下的所有科
                families = self.db.get_families_by_order(order)
                for family in families:
                    family_node = {
                        'id': f'family_{family}',
                        'label': family,
                        'type': 'family',
                        'children': []
                    }
                    
                    # 获取该科下的所有属
                    genera = self.db.get_genera_by_family(family)
                    for genus in genera:
                        genus_node = {
                            'id': f'genus_{genus}',
                            'label': genus,
                            'type': 'genus',
                            'children': []
                        }
                        
                        # 获取该属下的所有种
                        species = self.db.get_species_by_genus(genus)
                        for sp in species:
                            species_node = {
                                'id': f'species_{sp}',
                                'label': sp,
                                'type': 'species',
                                'count': self.db.get_image_count_by_species(sp)
                            }
                            genus_node['children'].append(species_node)
                        
                        if genus_node['children']:
                            family_node['children'].append(genus_node)
                    
                    if family_node['children']:
                        order_node['children'].append(family_node)
                
                if order_node['children']:
                    tree_data.append(order_node)
            
            self._tree_cache = tree_data
            LogManager.instance().debug(f"[ImageLibraryManager] 加载文件树: {len(tree_data)} 个目")
            return tree_data
            
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryManager] 获取文件树失败: {e}")
            return []
    
    def get_images_by_folder(self, folder_id: str, limit: int = 100) -> List[Dict]:
        """
        根据文件夹ID获取图片列表
        
        Args:
            folder_id: 文件夹ID (如 'species_白头鹎')
            limit: 最大返回数量
            
        Returns:
            图片信息列表
        """
        try:
            # 解析folder_id
            parts = folder_id.split('_', 1)
            if len(parts) != 2:
                return []
            
            folder_type, folder_name = parts
            
            # 根据类型查询图片
            images = []
            if folder_type == 'species':
                images = self.db.get_images_by_species(folder_name, limit=limit)
            elif folder_type == 'genus':
                images = self.db.get_images_by_genus(folder_name, limit=limit)
            elif folder_type == 'family':
                images = self.db.get_images_by_family(folder_name, limit=limit)
            elif folder_type == 'order':
                images = self.db.get_images_by_order(folder_name, limit=limit)
            
            # 转换为前端需要的格式
            result = []
            for img in images[:limit]:
                result.append({
                    'id': img.get('id', ''),
                    'path': img.get('path', ''),
                    'name': os.path.basename(img.get('path', '')),
                    'thumbnail': self._get_image_thumbnail(img.get('path', '')),
                    'species': img.get('species', ''),
                    'rating': img.get('rating', 0),
                    'favorite': img.get('favorite', False),
                    'width': img.get('width', 0),
                    'height': img.get('height', 0),
                    'size': img.get('size', 0),
                    'date': img.get('date_taken', ''),
                })
            
            LogManager.instance().debug(f"[ImageLibraryManager] 加载图片: {folder_id}, 数量: {len(result)}")
            return result
            
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryManager] 获取图片列表失败: {e}")
            return []
    
    def get_image_detail(self, image_id: str) -> Optional[Dict]:
        """
        获取图片详细信息
        
        Args:
            image_id: 图片ID
            
        Returns:
            图片详细信息
        """
        try:
            img = self.db.get_image_by_id(image_id)
            if not img:
                return None
            
            # 格式化坐标显示
            lat = img.get('latitude')
            lon = img.get('longitude')
            lat_str = ""
            lon_str = ""
            if lat is not None and lon is not None:
                try:
                    from ui.utils.geo_manager import GeoInfoManager
                    geo = GeoInfoManager.instance()
                    lat_str = geo.format_coordinate(float(lat))
                    lon_str = geo.format_coordinate(float(lon))
                except Exception:
                    lat_str = str(lat) if lat else ""
                    lon_str = str(lon) if lon else ""
            
            return {
                'id': img.get('id', ''),
                'path': img.get('path', ''),
                'name': os.path.basename(img.get('path', '')),
                'preview': self._get_image_preview(img.get('path', '')),
                'species': img.get('species', ''),
                'genus': img.get('genus', ''),
                'family': img.get('family', ''),
                'order': img.get('order', ''),
                'rating': img.get('rating', 0),
                'favorite': img.get('favorite', False),
                'width': img.get('width', 0),
                'height': img.get('height', 0),
                'size': img.get('size', 0),
                'date': img.get('date_taken', ''),
                'camera': img.get('camera', ''),
                'lens': img.get('lens', ''),
                'iso': img.get('iso', ''),
                'aperture': img.get('aperture', ''),
                'shutter': img.get('shutter_speed', ''),
                'focal_length': img.get('focal_length', ''),
                'latitude': lat_str,
                'longitude': lon_str,
            }
            
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryManager] 获取图片详情失败: {e}")
            return None
    
    def _get_image_thumbnail(self, image_path: str) -> str:
        """
        获取图片缩略图的Base64编码
        
        Args:
            image_path: 图片路径
            
        Returns:
            Base64编码的图片数据
        """
        try:
            # 检查缓存
            if image_path in self._image_cache:
                return self._image_cache[image_path]
            
            # 检查文件是否存在
            if not os.path.exists(image_path):
                return ''
            
            # 读取图片并转换为Base64
            # 这里应该使用缩略图缓存，暂时直接读取原图（需要优化）
            from PIL import Image
            import io
            
            # 打开图片并创建缩略图
            img = Image.open(image_path)
            img.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            # 转换为Base64
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            img_data = buffer.getvalue()
            base64_data = base64.b64encode(img_data).decode('utf-8')
            
            # 缓存结果
            result = f'data:image/jpeg;base64,{base64_data}'
            self._image_cache[image_path] = result
            
            return result
            
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryManager] 获取缩略图失败: {e}")
            return ''
    
    def _get_image_preview(self, image_path: str) -> str:
        """
        获取图片预览的Base64编码
        
        Args:
            image_path: 图片路径
            
        Returns:
            Base64编码的图片数据
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(image_path):
                return ''
            
            # 读取图片并转换为Base64
            from PIL import Image
            import io
            
            # 打开图片并创建预览图（中等尺寸）
            img = Image.open(image_path)
            img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            
            # 转换为Base64
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=90)
            img_data = buffer.getvalue()
            base64_data = base64.b64encode(img_data).decode('utf-8')
            
            return f'data:image/jpeg;base64,{base64_data}'
            
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryManager] 获取预览图失败: {e}")
            return ''
    
    def update_rating(self, image_id: str, rating: int) -> bool:
        """
        更新图片评分
        
        Args:
            image_id: 图片ID
            rating: 评分 (0-5)
            
        Returns:
            是否成功
        """
        try:
            self.db.update_image_rating(image_id, rating)
            LogManager.instance().debug(f"[ImageLibraryManager] 更新评分: {image_id} -> {rating}")
            return True
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryManager] 更新评分失败: {e}")
            return False
    
    def update_favorite(self, image_id: str, favorite: bool) -> bool:
        """
        更新图片收藏状态
        
        Args:
            image_id: 图片ID
            favorite: 是否收藏
            
        Returns:
            是否成功
        """
        try:
            self.db.update_image_favorite(image_id, favorite)
            LogManager.instance().debug(f"[ImageLibraryManager] 更新收藏: {image_id} -> {favorite}")
            return True
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryManager] 更新收藏失败: {e}")
            return False
    
    def clear_cache(self):
        """清除缓存"""
        self._tree_cache = None
        self._image_cache.clear()
        LogManager.instance().debug("[ImageLibraryManager] 清除缓存")

