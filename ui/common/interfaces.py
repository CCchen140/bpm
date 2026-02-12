from abc import ABC, abstractmethod
from typing import List, Any, Protocol
from ui.common.types import ImageFile

class IImageGrid(Protocol):
    """图片网格视图接口"""
    def add_thumbnail(self, thumbnail: Any) -> None: ...
    def clear_thumbnails(self) -> None: ...
    def arrange_thumbnails(self) -> None: ...
    
class IToolbarAction(Protocol):
    """工具栏动作接口"""
    def execute(self) -> None: ...
    
class IDataLoader(ABC):
    """数据加载器抽象基类"""
    @abstractmethod
    def load_data(self, source: str) -> List[ImageFile]:
        pass
