# -*- coding: utf-8 -*-
"""
图标工具函数

提供图标相关的通用功能，解决带中文字符的图标路径在Qt样式表中的编码问题。
"""

import base64
from typing import Optional


def get_arrow_down_svg_base64(color: str = "#333333") -> str:
    """
    生成下箭头SVG的Base64编码
    
    Args:
        color: 箭头颜色（十六进制格式，如 "#333333"）
    
    Returns:
        Base64编码的SVG data URL，可直接用于Qt样式表
    """
    svg_template = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="12" height="12">
        <path d="M4 6 L8 10 L12 6" stroke="{color}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>'''
    svg_content = svg_template.format(color=color)
    svg_bytes = svg_content.encode('utf-8')
    b64 = base64.b64encode(svg_bytes).decode('ascii')
    return f"data:image/svg+xml;base64,{b64}"


def get_arrow_up_svg_base64(color: str = "#333333") -> str:
    """
    生成上箭头SVG的Base64编码
    """
    svg_template = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="12" height="12">
        <path d="M4 10 L8 6 L12 10" stroke="{color}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>'''
    svg_content = svg_template.format(color=color)
    svg_bytes = svg_content.encode('utf-8')
    b64 = base64.b64encode(svg_bytes).decode('ascii')
    return f"data:image/svg+xml;base64,{b64}"


def get_arrow_right_svg_base64(color: str = "#333333") -> str:
    """
    生成右箭头SVG的Base64编码
    """
    svg_template = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="12" height="12">
        <path d="M6 4 L10 8 L6 12" stroke="{color}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>'''
    svg_content = svg_template.format(color=color)
    svg_bytes = svg_content.encode('utf-8')
    b64 = base64.b64encode(svg_bytes).decode('ascii')
    return f"data:image/svg+xml;base64,{b64}"


def get_arrow_left_svg_base64(color: str = "#333333") -> str:
    """
    生成左箭头SVG的Base64编码
    """
    svg_template = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="12" height="12">
        <path d="M10 4 L6 8 L10 12" stroke="{color}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>'''
    svg_content = svg_template.format(color=color)
    svg_bytes = svg_content.encode('utf-8')
    b64 = base64.b64encode(svg_bytes).decode('ascii')
    return f"data:image/svg+xml;base64,{b64}"
