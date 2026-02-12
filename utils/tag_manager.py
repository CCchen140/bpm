import os
import json
import threading
from utils.log_manager import LogManager

class TagManager:
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.tags_json_path = os.path.join(self.project_root, 'data', 'tags.json')
        self._tags_cache = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = TagManager()
        return cls._instance

    def _load_tags_from_json(self):
        """从 JSON 文件加载标签"""
        if not os.path.exists(self.tags_json_path):
            return None
        try:
            with open(self.tags_json_path, 'r', encoding='utf-8') as f:
                tags = json.load(f)
                if isinstance(tags, list):
                    return sorted(list(set(tags))) # 去重并排序
        except Exception as e:
            try:
                LogManager.instance().warning(f"加载 tags.json 失败: {e}")
            except Exception:
                pass
        return []

    def _save_tags_to_json(self, tags):
        """保存标签到 JSON 文件"""
        try:
            # 确保存储目录存在
            os.makedirs(os.path.dirname(self.tags_json_path), exist_ok=True)
            with open(self.tags_json_path, 'w', encoding='utf-8') as f:
                json.dump(sorted(list(set(tags))), f, ensure_ascii=False, indent=2)
        except Exception as e:
            try:
                LogManager.instance().warning(f"保存 tags.json 失败: {e}")
            except Exception:
                pass

    def get_all_tags(self):
        """
        获取所有已使用的标签
        """
        with self._lock:
            if self._tags_cache is not None:
                return list(self._tags_cache)

            # 1. 尝试从 JSON 加载
            tags = self._load_tags_from_json()
            
            # 2. 如果 JSON 不存在，返回空列表
            if tags is None:
                tags = []
            
            self._tags_cache = tags
            return list(self._tags_cache)

    def add_tag(self, tag_name):
        """添加新标签"""
        if not tag_name:
            return
        with self._lock:
            # 确保存存已加载
            if self._tags_cache is None:
                self._tags_cache = self._load_tags_from_json() or []

            if tag_name not in self._tags_cache:
                self._tags_cache.append(tag_name)
                self._save_tags_to_json(self._tags_cache)

    def delete_tag(self, tag_name):
        """删除标签"""
        if not tag_name:
            return
        with self._lock:
            # 确保缓存已加载
            if self._tags_cache is None:
                self._tags_cache = self._load_tags_from_json() or []

            if tag_name in self._tags_cache:
                self._tags_cache.remove(tag_name)
                self._save_tags_to_json(self._tags_cache)
