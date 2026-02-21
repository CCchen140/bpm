"""
图标加载工具
使用qtawesome库加载Material Design Icons
"""
from PyQt6.QtGui import QIcon

try:
    import qtawesome as qta_real
    _QTA_AVAILABLE = True
except ImportError:
    _QTA_AVAILABLE = False


def icon(*names, color=None, options=None, style='line', **kwargs):
    """
    加载图标
    
    :param names: 图标名称（支持多个图标叠加，如'mdi.circle', 'mdi.circle-outline'）
    :param color: 图标颜色（十六进制字符串或列表，如'#ffffff'或['#ff0000', '#00ff00']）
    :param options: 选项字典（传递给qtawesome）
    :param style: 'line' 或 'fill'（自动处理outline/fill版本）
    :param kwargs: 其他参数传递给qtawesome
    :return: QIcon对象
    """
    if not _QTA_AVAILABLE:
        return QIcon()
    
    try:
        # 使用qtawesome加载图标
        if color is not None:
            kwargs['color'] = color
        if options is not None:
            kwargs['options'] = options
        
        return qta_real.icon(*names, **kwargs)
    except Exception as e:
        # 如果加载失败，返回空图标
        return QIcon()


# 为了兼容 import qtawesome as qta 的用法
class IconModule:
    """模拟qtawesome模块"""
    @staticmethod
    def icon(*names, color=None, options=None, style='line', **kwargs):
        return icon(*names, color=color, options=options, style=style, **kwargs)


# 创建模块实例
qta = IconModule()

