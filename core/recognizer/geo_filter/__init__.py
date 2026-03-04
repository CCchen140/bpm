# -*- coding: utf-8 -*-
"""
地理物种索引模块

提供基于地理位置的鸟种候选范围限定功能，通过缩小搜索空间提高识别准确率。
数据直接嵌入Python模块，打包到exe中，无需运行时加载外部文件。
"""

from .geo_species_index import GeoSpeciesIndex, get_geo_index
from .location_resolver import LocationResolver, resolve_image_location, get_region_code_for_image

__all__ = [
    "GeoSpeciesIndex",
    "get_geo_index",
    "LocationResolver", 
    "resolve_image_location",
    "get_region_code_for_image",
]
