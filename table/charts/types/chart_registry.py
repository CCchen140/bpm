from __future__ import annotations

from typing import Dict, Type, Optional, Any
import importlib
import os

from table.charts.types.chart_data_builder import ChartDataBuilder


class ChartRegistry:
    """图表类型注册中心
    
    管理所有图表类型的数据生成器，提供统一的获取接口。
    """
    
    _builders: Dict[str, Type[ChartDataBuilder]] = {}
    
    @classmethod
    def register(cls, chart_type: str, builder_class: Type[ChartDataBuilder]):
        """注册图表类型数据生成器
        
        Args:
            chart_type: 图表类型标识，如 "bar", "pie", "number" 等
            builder_class: 继承自 ChartDataBuilder 的类
        """
        cls._builders[chart_type] = builder_class
    
    @classmethod
    def get_builder(cls, chart_type: str, db_manager: Any, display_options: Optional[Dict] = None) -> Optional[ChartDataBuilder]:
        """获取图表数据生成器实例
        
        Args:
            chart_type: 图表类型标识
            db_manager: 数据库管理器
            display_options: 显示选项
            
        Returns:
            图表数据生成器实例，如果未找到则返回 None
        """
        builder_class = cls._builders.get(chart_type)
        if builder_class:
            return builder_class(db_manager, display_options)
        return None
    
    @classmethod
    def has_builder(cls, chart_type: str) -> bool:
        """检查是否支持指定的图表类型"""
        return chart_type in cls._builders
    
    @classmethod
    def list_types(cls) -> list:
        """列出所有已注册的图表类型"""
        return list(cls._builders.keys())
    
    @classmethod
    def auto_discover(cls):
        """自动发现并注册所有图表类型
        
        扫描 /charts/types/ 目录下的所有子目录，
        导入其中的 data_builder.py 模块并注册。
        """
        types_dir = os.path.dirname(os.path.abspath(__file__))
        
        for item in os.listdir(types_dir):
            item_path = os.path.join(types_dir, item)
            # 检查是否是目录且不是特殊目录
            if os.path.isdir(item_path) and not item.startswith('_'):
                builder_file = os.path.join(item_path, 'data_builder.py')
                if os.path.exists(builder_file):
                    try:
                        # 动态导入模块
                        module_name = f'table.charts.types.{item}.data_builder'
                        module = importlib.import_module(module_name)
                        
                        # 查找模块中的 Builder 类
                        builder_class_name = f'{item.capitalize()}DataBuilder'
                        if hasattr(module, builder_class_name):
                            builder_class = getattr(module, builder_class_name)
                            if issubclass(builder_class, ChartDataBuilder):
                                cls.register(item, builder_class)
                    except Exception as e:
                        print(f"Failed to load chart type '{item}': {e}")


# 提供一个便捷的注册装饰器
def register_chart(chart_type: str):
    """图表类型注册装饰器
    
    用法：
        @register_chart("bar")
        class BarDataBuilder(ChartDataBuilder):
            def build_payload(self, table_name, options, chart_type):
                ...
    """
    def decorator(cls: Type[ChartDataBuilder]):
        ChartRegistry.register(chart_type, cls)
        return cls
    return decorator
