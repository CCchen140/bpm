# -*- coding: utf-8 -*-
"""
地理物种索引

使用嵌入的Python数据模块存储全球鸟类分布数据，支持快速的区域物种查询。
数据直接打包到exe中，无需运行时加载外部文件。
"""

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from utils.log_manager import LogManager


@dataclass
class GeoRegion:
    """地理区域信息"""
    code: str
    name: str
    bounds: Tuple[float, float, float, float]  # (south, north, west, east)
    species_ids: Set[int]


class GeoSpeciesIndex:
    """
    地理物种索引
    
    使用嵌入的Python数据模块存储全球鸟类地理分布数据，提供高效的位置查询能力。
    数据直接编译到exe中，无需运行时加载外部文件。
    """
    
    _instance = None
    _lock = threading.Lock()
    
    # 大洲级别的区域代码
    CONTINENT_CODES = {
        "ASIA": ("亚洲", (-10, 81, 26, 170)),
        "EUROPE": ("欧洲", (34, 71, -25, 45)),
        "AFRICA": ("非洲", (-35, 37, -17, 51)),
        "NAMERICA": ("北美洲", (14, 83, -168, -52)),
        "SAMERICA": ("南美洲", (-56, 13, -81, -34)),
        "OCEANIA": ("大洋洲", (-47, -10, 110, 180)),
    }
    
    def __init__(self):
        """初始化地理物种索引"""
        self._regions: Dict[str, GeoRegion] = {}
        self._code_to_class: Dict[str, int] = {}
        self._loaded = False
        self._load_lock = threading.Lock()
    
    @classmethod
    def get_instance(cls) -> "GeoSpeciesIndex":
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def _ensure_loaded(self):
        """确保索引数据已加载"""
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            self._load_embedded_data()
            self._loaded = True
    
    def _load_embedded_data(self):
        """加载嵌入的数据模块"""
        try:
            from core.recognizer.geo_filter._geo_data import CODE_TO_CLASS, REGIONS
            
            # 加载代码映射
            self._code_to_class = dict(CODE_TO_CLASS)
            
            # 加载区域数据
            for region_code, info in REGIONS.items():
                try:
                    bounds = tuple(info.get("bounds", [0, 0, 0, 0]))
                    species_codes = info.get("species", [])
                    species_ids = set()
                    for sp_code in species_codes:
                        class_id = self._code_to_class.get(sp_code)
                        if class_id is not None:
                            species_ids.add(class_id)
                    
                    self._regions[region_code] = GeoRegion(
                        code=region_code,
                        name=info.get("name", region_code),
                        bounds=bounds,
                        species_ids=species_ids
                    )
                except Exception as e:
                    try:
                        LogManager.instance().debug(f"[GeoIndex] 加载区域失败 {region_code}: {e}")
                    except Exception:
                        pass
                        
        except ImportError as e:
            try:
                LogManager.instance().error(f"[GeoIndex] 无法加载嵌入数据模块: {e}")
            except Exception:
                pass
    
    def query_by_location(self, lat: float, lon: float) -> Tuple[Set[int], Optional[str]]:
        """
        根据GPS坐标查询候选物种
        
        Args:
            lat: 纬度 (-90 到 90)
            lon: 经度 (-180 到 180)
        
        Returns:
            (物种class_id集合, 匹配的区域代码)
        """
        self._ensure_loaded()
        
        # 查找包含该坐标的最小区域
        matched_region = self._find_smallest_region(lat, lon)
        if not matched_region:
            return set(), None
        
        species_ids = self._regions[matched_region].species_ids
        return species_ids, matched_region
    
    def query_by_region(self, region_code: str) -> Set[int]:
        """
        根据区域代码查询候选物种
        
        Args:
            region_code: 区域代码（如 "CN", "CN-44", "US-CA"）
        
        Returns:
            物种class_id集合
        """
        self._ensure_loaded()
        region_code = region_code.upper()
        
        # 直接查询区域
        if region_code in self._regions:
            return self._regions[region_code].species_ids
        
        # 如果是省级代码，回退到国家级
        if "-" in region_code:
            country = region_code.split("-")[0]
            if country in self._regions:
                return self._regions[country].species_ids
        
        return set()
    
    def _find_smallest_region(self, lat: float, lon: float) -> Optional[str]:
        """
        查找包含指定坐标的最小区域
        
        优先返回面积最小的区域（更精确）
        
        Args:
            lat: 纬度
            lon: 经度
        
        Returns:
            区域代码
        """
        candidates = []
        
        for code, region in self._regions.items():
            if code in self.CONTINENT_CODES:
                continue  # 跳过大洲级别
            
            south, north, west, east = region.bounds
            if south <= lat <= north and west <= lon <= east:
                area = (north - south) * (east - west)
                candidates.append((area, code))
        
        if not candidates:
            return None
        
        # 返回面积最小的区域（最精确）
        candidates.sort()
        return candidates[0][1]
    
    def get_region_name(self, region_code: str) -> str:
        """获取区域名称"""
        self._ensure_loaded()
        region = self._regions.get(region_code.upper())
        return region.name if region else region_code
    
    def get_region_bounds(self, region_code: str) -> Optional[Tuple[float, float, float, float]]:
        """获取区域边界"""
        self._ensure_loaded()
        region = self._regions.get(region_code.upper())
        return region.bounds if region else None
    
    def list_regions(self) -> List[str]:
        """获取所有区域代码列表"""
        self._ensure_loaded()
        return sorted(self._regions.keys())
    
    def get_species_count(self, region_code: str) -> int:
        """获取区域物种数量"""
        self._ensure_loaded()
        region = self._regions.get(region_code.upper())
        return len(region.species_ids) if region else 0
    
    def detect_region_from_gps(self, lat: float, lon: float) -> Optional[str]:
        """
        根据GPS坐标检测区域代码
        
        Args:
            lat: 纬度
            lon: 经度
        
        Returns:
            区域代码
        """
        self._ensure_loaded()
        return self._find_smallest_region(lat, lon)


def get_geo_index() -> GeoSpeciesIndex:
    """获取地理物种索引单例"""
    return GeoSpeciesIndex.get_instance()
