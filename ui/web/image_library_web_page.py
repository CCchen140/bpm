"""
图库Web页面组件
整合所有组件，提供完整的Web版图库功能
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, pyqtSignal

from ui.web.image_library_html import build_image_library_html
from ui.web.image_library_bridge import ImageLibraryBridge
from ui.web.image_library_manager import ImageLibraryManager
from ui.utils.color_manager import ColorManager
from utils.log_manager import LogManager


class ImageLibraryWebPage(QWidget):
    """图库Web页面"""
    
    # 信号
    imageOpened = pyqtSignal(str)  # 打开图片
    selectionChanged = pyqtSignal(int)  # 选择变化
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImageLibraryWebPage")
        self._init_ui()
        # 主题色变化时需要重新生成HTML中的CSS（Web端无法自动继承Qt样式表）
        try:
            ColorManager.instance().register_listener(self._on_theme_changed)
        except Exception:
            pass
    
    def _on_theme_changed(self):
        """主题变化时重载HTML，让预览背景等样式立即同步"""
        try:
            self.reload_html()
        except Exception:
            pass
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 创建业务逻辑管理器
        self.manager = ImageLibraryManager()
        
        # 创建通信桥梁
        self.bridge = ImageLibraryBridge(self.manager, self)
        
        # 创建WebView
        self.web_view = QWebEngineView()
        
        # 设置WebChannel
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
        # 配置WebEngine设置
        self._configure_webengine()
        
        # 加载HTML
        html = build_image_library_html()
        base_url = QUrl.fromLocalFile("./")
        self.web_view.setHtml(html, base_url)
        
        # 监听加载完成
        self.web_view.loadFinished.connect(self._on_load_finished)
        
        layout.addWidget(self.web_view)
        
        LogManager.instance().debug("[ImageLibraryWebPage] 初始化完成")
    
    def _configure_webengine(self):
        """配置WebEngine设置"""
        try:
            settings = self.web_view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False)
            
            # 尝试配置profile设置
            try:
                profile_settings = self.web_view.page().profile().settings()
                profile_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
                profile_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            except Exception:
                pass
            
            LogManager.instance().debug("[ImageLibraryWebPage] WebEngine配置完成")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] WebEngine配置失败: {e}")
    
    def _on_load_finished(self, ok: bool):
        """页面加载完成"""
        if ok:
            LogManager.instance().debug("[ImageLibraryWebPage] 页面加载成功")
            try:
                # 重载HTML后需要重新推送一次数据，保证树/列表/预览恢复
                self.refresh()
            except Exception:
                pass
        else:
            LogManager.instance().error("[ImageLibraryWebPage] 页面加载失败")
    
    def set_folder(self, folder_path: str):
        """
        设置当前文件夹
        
        Args:
            folder_path: 文件夹路径
        """
        try:
            self.manager.current_folder = folder_path
            self.refresh()
            LogManager.instance().debug(f"[ImageLibraryWebPage] 设置文件夹: {folder_path}")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 设置文件夹失败: {e}")
    
    def refresh(self):
        """刷新页面"""
        try:
            # 通知前端刷新文件树
            self.bridge.notify_tree_updated()
            
            # 如果有当前文件夹，刷新图片列表
            if self.manager.current_folder:
                self.bridge.notify_images_updated(self.manager.current_folder)
            
            LogManager.instance().debug("[ImageLibraryWebPage] 刷新页面")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 刷新失败: {e}")
    
    def reload_html(self):
        """重新加载HTML"""
        try:
            html = build_image_library_html()
            base_url = QUrl.fromLocalFile("./")
            self.web_view.setHtml(html, base_url)
            LogManager.instance().debug("[ImageLibraryWebPage] 重新加载HTML")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 重新加载HTML失败: {e}")
    
    def release_cache(self):
        """释放缓存"""
        try:
            self.manager.clear_cache()
            LogManager.instance().debug("[ImageLibraryWebPage] 释放缓存")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 释放缓存失败: {e}")
    
    def get_selected_count(self) -> int:
        """获取选中的图片数量"""
        # TODO: 从前端获取选中数量
        return 0
    
    def clear_selection(self):
        """清除选择"""
        try:
            # 调用前端JavaScript
            self.web_view.page().runJavaScript("clearSelection();")
            LogManager.instance().debug("[ImageLibraryWebPage] 清除选择")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 清除选择失败: {e}")
    
    def select_all(self):
        """全选"""
        try:
            # 调用前端JavaScript
            self.web_view.page().runJavaScript("selectAll();")
            LogManager.instance().debug("[ImageLibraryWebPage] 全选")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 全选失败: {e}")
    
    def initialize(self):
        """初始化页面（延迟加载）"""
        try:
            # 刷新文件树
            self.bridge.notify_tree_updated()
            LogManager.instance().debug("[ImageLibraryWebPage] 初始化页面")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 初始化失败: {e}")
    
    def shutdown(self):
        """关闭页面，清理资源"""
        try:
            self.release_cache()
            LogManager.instance().debug("[ImageLibraryWebPage] 关闭页面")
        except Exception as e:
            LogManager.instance().error(f"[ImageLibraryWebPage] 关闭失败: {e}")

