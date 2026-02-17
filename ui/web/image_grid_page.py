"""图片网格 Web 页面组件"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, pyqtSignal

from ui.web.image_grid_html import build_image_grid_html
from ui.web.image_grid_bridge import ImageGridBridge
from ui.web.image_grid_manager import ImageGridManager
from utils.log_manager import LogManager


class ImageGridWebPage(QWidget):
    """图片网格 Web 页面"""
    
    # 信号
    imageOpened = pyqtSignal(str)  # 打开图片
    selectionChanged = pyqtSignal(int)  # 选择变化
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImageGridWebPage")
        self._init_ui()
    
    def _init_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 创建业务逻辑管理器
        self.manager = ImageGridManager()
        
        # 创建通信桥梁
        self.bridge = ImageGridBridge(self.manager, self)
        
        # 创建 WebView
        self.web_view = QWebEngineView()
        
        # 设置 WebChannel
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        
        # 配置 WebEngine 设置
        self._configure_webengine()
        
        # 加载 HTML
        html = build_image_grid_html()
        base_url = QUrl.fromLocalFile("./")
        self.web_view.setHtml(html, base_url)
        
        # 监听加载完成
        self.web_view.loadFinished.connect(self._on_load_finished)
        
        layout.addWidget(self.web_view)
        
        LogManager.instance().debug("[ImageGridWebPage] 初始化完成")
    
    def _configure_webengine(self):
        """配置 WebEngine 设置"""
        try:
            settings = self.web_view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False)
            
            # 尝试配置 profile 设置
            try:
                profile_settings = self.web_view.page().profile().settings()
                profile_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
                profile_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            except Exception:
                pass
            
            LogManager.instance().debug("[ImageGridWebPage] WebEngine 配置完成")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] WebEngine 配置失败: {e}")
    
    def _on_load_finished(self, ok: bool):
        """页面加载完成"""
        if ok:
            LogManager.instance().debug("[ImageGridWebPage] 页面加载成功")
        else:
            LogManager.instance().error("[ImageGridWebPage] 页面加载失败")
    
    def set_folder(self, folder_path: str):
        """
        设置当前文件夹
        
        Args:
            folder_path: 文件夹路径
        """
        try:
            self.manager.set_current_folder(folder_path)
            self.refresh()
            LogManager.instance().debug(f"[ImageGridWebPage] 设置文件夹: {folder_path}")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] 设置文件夹失败: {e}")
    
    def set_filters(self, filters: dict):
        """
        设置筛选条件
        
        Args:
            filters: 筛选条件字典
        """
        try:
            self.manager.set_filters(filters)
            self.refresh()
            LogManager.instance().debug(f"[ImageGridWebPage] 设置筛选条件: {filters}")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] 设置筛选条件失败: {e}")
    
    def refresh(self):
        """刷新图片列表"""
        try:
            self.bridge.notify_images_updated()
            LogManager.instance().debug("[ImageGridWebPage] 刷新图片列表")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] 刷新失败: {e}")
    
    def reload_html(self):
        """重新加载 HTML"""
        try:
            html = build_image_grid_html()
            base_url = QUrl.fromLocalFile("./")
            self.web_view.setHtml(html, base_url)
            LogManager.instance().debug("[ImageGridWebPage] 重新加载 HTML")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] 重新加载 HTML 失败: {e}")
    
    def release_cache(self):
        """释放缓存"""
        try:
            self.manager.release_cache()
            LogManager.instance().debug("[ImageGridWebPage] 释放缓存")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] 释放缓存失败: {e}")
    
    def get_selected_count(self) -> int:
        """获取选中的图片数量"""
        # TODO: 从前端获取选中数量
        return 0
    
    def clear_selection(self):
        """清除选择"""
        try:
            # 调用前端 JavaScript
            self.web_view.page().runJavaScript("clearSelection();")
            LogManager.instance().debug("[ImageGridWebPage] 清除选择")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] 清除选择失败: {e}")
    
    def select_all(self):
        """全选"""
        try:
            # 调用前端 JavaScript
            self.web_view.page().runJavaScript("selectAll();")
            LogManager.instance().debug("[ImageGridWebPage] 全选")
        except Exception as e:
            LogManager.instance().error(f"[ImageGridWebPage] 全选失败: {e}")


