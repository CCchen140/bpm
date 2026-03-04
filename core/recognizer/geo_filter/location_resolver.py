# -*- coding: utf-8 -*-
"""
位置解析器

从多个来源获取图片的地理位置信息：
1. 数据库中的区域代码（优先级最高）
2. 数据库中用户设置的地理位置
3. 图片EXIF中的区域代码
4. 图片EXIF中的GPS数据
"""

import re
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

from utils.log_manager import LogManager


@dataclass
class ImageLocation:
    """图片位置信息"""
    latitude: float
    longitude: float
    source: str  # "user_setting" 或 "exif"
    location_name: Optional[str] = None
    region_code: Optional[str] = None  # 区域代码


class LocationResolver:
    """
    位置解析器
    
    负责从多个来源获取图片的地理位置，优先使用区域代码。
    
    优先级：
    1. 数据库中的region_code字段
    2. 数据库中的latitude/longitude
    3. EXIF中的RegionCode标签
    4. EXIF中的GPS数据
    """
    
    _instance = None
    _lock = threading.Lock()
    _db = None  # 数据库连接缓存
    
    def __init__(self):
        """初始化位置解析器"""
        pass
    
    def _get_db(self):
        """获取数据库连接（使用单例缓存）"""
        if LocationResolver._db is None:
            try:
                from utils.sql.data_base import BirdLibraryDB
                LocationResolver._db = BirdLibraryDB()
            except Exception:
                pass
        return LocationResolver._db
    
    @classmethod
    def get_instance(cls) -> "LocationResolver":
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def resolve(self, image_path: str, db_record: Optional[dict] = None) -> Optional[ImageLocation]:
        """
        解析图片的地理位置
        
        Args:
            image_path: 图片路径
            db_record: 数据库记录（包含latitude/longitude/location/region_code字段）
        
        Returns:
            ImageLocation对象，无法获取则返回None
        """
        # 优先使用数据库中的数据
        if db_record:
            location = self._extract_from_database(db_record)
            if location:
                return location
        
        # 回退到EXIF
        return self._extract_from_exif(image_path)
    
    def _extract_from_database(self, record: dict) -> Optional[ImageLocation]:
        """
        从数据库记录提取位置
        
        Args:
            record: 数据库记录
        
        Returns:
            ImageLocation对象
        """
        try:
            # 优先读取区域代码
            region_code = record.get("region_code")
            lat = record.get("latitude")
            lon = record.get("longitude")
            name = record.get("location")
            
            # 如果有区域代码但没有GPS，尝试从区域代码推断
            if region_code and (lat is None or lon is None):
                lat, lon = self._get_region_center(region_code)
            
            if lat is None or lon is None:
                return None
            
            lat = float(lat)
            lon = float(lon)
            
            # 过滤无效坐标
            if abs(lat) < 0.001 and abs(lon) < 0.001:
                return None
            if abs(lat) > 90 or abs(lon) > 180:
                return None
            
            return ImageLocation(
                latitude=lat,
                longitude=lon,
                source="user_setting",
                location_name=str(name) if name else None,
                region_code=str(region_code) if region_code else None
            )
        except (ValueError, TypeError):
            return None
    
    def _get_region_center(self, region_code: str) -> Tuple[Optional[float], Optional[float]]:
        """
        获取区域中心坐标
        
        Args:
            region_code: 区域代码
        
        Returns:
            (lat, lon) 元组
        """
        try:
            from core.recognizer.geo_filter import get_geo_index
            geo_index = get_geo_index()
            bounds = geo_index.get_region_bounds(region_code)
            if bounds:
                south, north, west, east = bounds
                lat = (south + north) / 2
                lon = (west + east) / 2
                return lat, lon
        except Exception:
            pass
        return None, None
    
    def _extract_from_exif(self, image_path: str) -> Optional[ImageLocation]:
        """
        从EXIF提取GPS坐标和区域代码
        
        Args:
            image_path: 图片路径
        
        Returns:
            ImageLocation对象
        """
        try:
            from utils.exif.exif_utils import ExifHandleWorker
            exif = ExifHandleWorker.get_instance()
            
            # 尝试读取区域代码
            region_code = exif.read_tag(image_path, "XMP-bmp:RegionCode")
            
            # 读取GPS坐标
            lat_val = exif.read_tag(image_path, "GPS:GPSLatitude")
            lon_val = exif.read_tag(image_path, "GPS:GPSLongitude")
            lat_ref = exif.read_tag(image_path, "GPS:GPSLatitudeRef")
            lon_ref = exif.read_tag(image_path, "GPS:GPSLongitudeRef")
            
            lat = None
            lon = None
            
            if lat_val and lon_val:
                lat = self._parse_coordinate(lat_val, lat_ref)
                lon = self._parse_coordinate(lon_val, lon_ref)
            
            # 如果有区域代码但没有GPS，尝试从区域代码推断
            if region_code and (lat is None or lon is None):
                lat, lon = self._get_region_center(region_code)
            
            if lat is None or lon is None:
                return None
            
            return ImageLocation(
                latitude=lat,
                longitude=lon,
                source="exif",
                region_code=str(region_code) if region_code else None
            )
        except Exception as e:
            try:
                LogManager.instance().debug(f"[LocationResolver] EXIF读取失败: {e}")
            except Exception:
                pass
            return None
    
    def _parse_coordinate(self, value: Optional[str], ref: Optional[str]) -> Optional[float]:
        """
        解析GPS坐标值
        
        支持格式：
        - 度分秒: "39 deg 5' 4.99""
        - 十进制: "39.08472"
        - 分数: "39/1, 5/1, 499/100"
        
        Args:
            value: 坐标值字符串
            ref: 方向参考（N/S/E/W）
        
        Returns:
            十进制坐标值
        """
        if not value:
            return None
        
        coord_str = str(value).strip()
        if not coord_str:
            return None
        
        decimal = None
        
        # 尝试度分秒格式
        dms_match = re.match(
            r"(\d+(?:\.\d+)?)\s*(?:deg|°)\s*(\d+(?:\.\d+)?)\s*['']\s*(\d+(?:\.\d+)?)\s*[\"']?",
            coord_str,
            re.IGNORECASE
        )
        if dms_match:
            degrees = float(dms_match.group(1))
            minutes = float(dms_match.group(2))
            seconds = float(dms_match.group(3))
            decimal = degrees + minutes / 60 + seconds / 3600
        else:
            # 尝试分数格式
            frac_match = re.match(
                r"(\d+)/(\d+)\s*,\s*(\d+)/(\d+)\s*,\s*(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)",
                coord_str
            )
            if frac_match:
                degrees = float(frac_match.group(1)) / float(frac_match.group(2))
                minutes = float(frac_match.group(3)) / float(frac_match.group(4))
                seconds = float(frac_match.group(5)) / float(frac_match.group(6))
                decimal = degrees + minutes / 60 + seconds / 3600
            else:
                # 尝试直接解析十进制
                try:
                    decimal = float(coord_str)
                except ValueError:
                    pass
        
        if decimal is None:
            return None
        
        # 处理南纬/西经
        if ref:
            ref_str = str(ref).strip().upper()
            if ref_str.startswith("S") or ref_str.startswith("W"):
                decimal = -decimal
        
        return decimal
    
    def resolve_for_image(self, image_path: str, table: str = "bird_results") -> Optional[ImageLocation]:
        """
        解析图片位置（便捷方法）
        
        自动从数据库查询记录并解析位置。
        
        Args:
            image_path: 图片路径
            table: 数据库表名
        
        Returns:
            ImageLocation对象
        """
        try:
            db = self._get_db()
            if db:
                record = db.get_result_by_path(image_path, table_name=table)
                return self.resolve(image_path, db_record=record)
        except Exception as e:
            try:
                LogManager.instance().debug(f"[LocationResolver] 解析位置失败: {e}")
            except Exception:
                pass
        return self.resolve(image_path, db_record=None)
    
    def get_region_code_for_image(self, image_path: str, table: str = "bird_results") -> Optional[str]:
        """
        获取图片的区域代码（便捷方法）
        
        优先级：
        1. 数据库中的region_code字段
        2. EXIF中的RegionCode标签
        3. 根据GPS坐标推断
        
        Args:
            image_path: 图片路径
            table: 数据库表名
        
        Returns:
            区域代码
        """
        record = None
        try:
            db = self._get_db()
            if db:
                record = db.get_result_by_path(image_path, table_name=table)
                
                # 优先从数据库读取
                if record:
                    region_code = record.get("region_code")
                    if region_code:
                        return str(region_code)
        except Exception:
            pass
        
        # 从EXIF读取
        try:
            from utils.exif.exif_utils import ExifHandleWorker
            exif = ExifHandleWorker.get_instance()
            region_code = exif.read_tag(image_path, "XMP-bmp:RegionCode")
            if region_code:
                return str(region_code)
        except Exception:
            pass
        
        # 根据GPS推断
        try:
            location = self.resolve(image_path, db_record=record)
            if location and location.latitude and location.longitude:
                from core.recognizer.geo_filter import get_geo_index
                geo_index = get_geo_index()
                return geo_index.detect_region_from_gps(location.latitude, location.longitude)
            
        except Exception as e:
            try:
                LogManager.instance().debug(f"[LocationResolver] 获取区域代码失败: {e}")
            except Exception:
                pass
        
        return None


def resolve_image_location(image_path: str, table: str = "bird_results") -> Optional[ImageLocation]:
    """
    解析图片位置（便捷函数）
    
    Args:
        image_path: 图片路径
        table: 数据库表名
    
    Returns:
        ImageLocation对象
    """
    return LocationResolver.get_instance().resolve_for_image(image_path, table)


def get_region_code_for_image(image_path: str, table: str = "bird_results") -> Optional[str]:
    """
    获取图片的区域代码（便捷函数）
    
    Args:
        image_path: 图片路径
        table: 数据库表名
    
    Returns:
        区域代码
    """
    return LocationResolver.get_instance().get_region_code_for_image(image_path, table)
