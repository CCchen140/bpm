import ctypes
from ctypes import c_int, byref, sizeof
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QColor
import sys
from utils.log_manager import LogManager

def apply_dark_title_bar(window: QWidget, color_str=None, text_color_str=None):
    """
    Apply dark title bar on Windows 10/11.
    Keeps native buttons but changes the background to dark and text/buttons to light.
    
    Args:
        window: The QWidget (usually QMainWindow)
        color_str: Optional hex color string (e.g. "#2c3e50") to set the title bar background.
                   If None, it just enables immersive dark mode (system default dark).
    """
    if sys.platform != "win32":
        return

    try:
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        
        # 1. Enable Immersive Dark Mode
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 20H1+, Windows 11)
        # For older Windows 10 versions (1903), it was 19, but 20 is standard now.
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(value), sizeof(value))
        
        # 2. Set Custom Caption Color (Windows 11 only)
        if color_str:
            qcolor = QColor(color_str)
            if qcolor.isValid():
                # COLORREF is 0x00BBGGRR
                r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()
                color_ref = (b << 16) | (g << 8) | r
                
                DWMWA_CAPTION_COLOR = 35
                dwm.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, byref(c_int(color_ref)), sizeof(c_int))
        text_color_ref = 0x00FFFFFF
        if text_color_str:
            qtext = QColor(text_color_str)
            if qtext.isValid():
                r, g, b = qtext.red(), qtext.green(), qtext.blue()
                text_color_ref = (b << 16) | (g << 8) | r
        DWMWA_TEXT_COLOR = 36
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, byref(c_int(text_color_ref)), sizeof(c_int))

    except Exception as e:
        try:
            LogManager.instance().warning(f"应用窗口标题栏样式失败: {e}")
        except Exception:
            pass
