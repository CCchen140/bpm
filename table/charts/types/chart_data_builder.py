from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List


class ChartDataBuilder(ABC):
    """图表数据生成器基类
    
    所有图表类型的数据生成逻辑都应该继承这个基类，
    并实现 build_payload 方法来生成图表所需的数据。
    """
    
    def __init__(self, db_manager: Any, display_options: Optional[Dict] = None):
        """初始化数据生成器
        
        Args:
            db_manager: 数据库管理器，用于执行查询
            display_options: 显示选项，如是否隐藏无数据的时间等
        """
        self._db = db_manager
        self._display_options = display_options or {}
    
    @abstractmethod
    def build_payload(self, table_name: str, options: dict, chart_type: str = "") -> dict:
        """构建图表数据
        
        Args:
            table_name: 数据库表名
            options: 图表配置选项
            chart_type: 图表类型标识
            
        Returns:
            包含图表数据的字典
        """
        ...
    
    def _query(self, sql: str, params: Optional[List] = None) -> List[Dict]:
        """执行数据库查询"""
        if hasattr(self._db, '_query'):
            return self._db._query(sql, params)
        return []
    
    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全地将值转换为浮点数"""
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            return default
