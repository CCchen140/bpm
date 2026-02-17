"""
SVG图标加载工具
用于替代qtawesome，从本地/data/icon目录加载SVG图标
"""
import os
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtCore import Qt
from PyQt6.QtSvg import QSvgRenderer


# 图标映射表：将qtawesome图标名映射到本地SVG图标
ICON_MAP = {
    'mdi6.chevron-left': '左',
    'mdi6.chevron-right': '右',
    'mdi6.magnify': '搜索',
    'mdi6.sort-alphabetical-ascending': '排序',
    'mdi6.harddisk': '固态硬盘',
    'mdi6.folder': '文件夹-关',
    'mdi6.loading': '加载',
    'mdi6.folder-plus': '文件夹-添加',
    'mdi6.rename-box': '编辑2',
    'mdi6.folder-remove': '删除',
    'mdi6.trash-can-outline': '删除',
    'mdi6.folder-open': '文件夹-开',
    'mdi6.file-import-outline': '输入',
    'mdi6.file-import': '输入',
    'mdi6.database-import': '数据库下载',
    'mdi6.view-grid': '卡片查看模式',
    'mdi6.view-list': '表格',
    'mdi6.filter': '筛选',
    'mdi6.star': '星星',
    'mdi6.tag': '标签',
    'mdi6.delete': '删除',
    'mdi6.refresh': '刷新',
    'mdi6.cog': '设置',
    'mdi6.information': '信息',
    'mdi6.help': '帮助',
    'mdi6.close': '关闭',
    'mdi6.check': '校验',
    'mdi6.plus': '加',
    'mdi6.minus': '减',
    'mdi6.pencil': '编辑2',
    'mdi6.content-copy': '复制链接',
    'mdi6.download': '图片下载',
    'mdi6.upload': '输入',
    'mdi6.eye': '预览-打开',
    'mdi6.eye-off': '预览-关闭',
}


def icon(icon_name, color=None, options=None, style='line'):
    """
    加载SVG图标（兼容qtawesome的icon函数签名）
    
    :param icon_name: 图标名称（可以是qtawesome名称或中文名称）
    :param color: 图标颜色（十六进制字符串，如'#ffffff'）
    :param options: 选项字典（为了兼容qtawesome，但不使用）
    :param style: 'line' 或 'fill'
    :return: QIcon对象
    """
    # 如果是qtawesome图标名，转换为本地图标名
    if icon_name in ICON_MAP:
        icon_name = ICON_MAP[icon_name]
    
    # 获取图标目录
    base_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
        'data', 'icon', style
    )
    
    # 尝试查找匹配的图标文件
    icon_path = None
    if os.path.exists(base_path):
        try:
            for filename in os.listdir(base_path):
                if filename.endswith('.svg') and icon_name in filename:
                    icon_path = os.path.join(base_path, filename)
                    break
        except Exception:
            pass
    
    if not icon_path or not os.path.exists(icon_path):
        # 如果找不到图标，返回空图标
        return QIcon()
    
    try:
        # 读取SVG内容
        with open(icon_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # 如果指定了颜色，替换SVG中的颜色
        if color:
            import re
            # 移除颜色字符串中的#号
            if color.startswith('#'):
                color = color[1:]
            # 替换常见的颜色属性
            svg_content = re.sub(r'fill="[^"]*"', f'fill="#{color}"', svg_content)
            svg_content = re.sub(r'stroke="[^"]*"', f'stroke="#{color}"', svg_content)
        
        # 创建QIcon
        renderer = QSvgRenderer(svg_content.encode('utf-8'))
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)
    except Exception:
        return QIcon()


# 为了兼容 import qtawesome as qta 的用法
class IconModule:
    """模拟qtawesome模块"""
    @staticmethod
    def icon(icon_name, color=None, options=None):
        return icon(icon_name, color, options)


# 创建模块实例
qta = IconModule()

