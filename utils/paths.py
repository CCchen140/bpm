import os
import sys
from pathlib import Path
from PyQt6.QtCore import QSettings, QStandardPaths

class PathManager:
    _instance = None
    
    ORGANIZATION = "BirdPictureManager"
    APPLICATION = "BirdManager_Global" 

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)
    
    def get_project_root(self):
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).parent
        else:
            # Assuming this file is in utils/paths.py, root is ../../
            return Path(__file__).parent.parent

    def get_app_data_path(self):
        """Returns the static app data path (installation directory/data)."""
        return self.get_project_root() / "data"

    def get_default_user_data_path(self):
        """Returns the default user data path (~/Documents/qitu/data)."""
        docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(docs) / "qitu" / "data"

    def get_user_data_path(self):
        """Returns the current user data path from settings, or default."""
        path_str = self._settings.value("UserDataPath")
        if path_str:
            return Path(path_str)
        return self.get_default_user_data_path()

    def set_user_data_path(self, path):
        """Sets the user data path."""
        self._settings.setValue("UserDataPath", str(path))

    def get_user_setting_dir(self):
        return self.get_user_data_path() / "setting"

    def get_user_db_dir(self):
        return self.get_user_data_path() / "db"
    
    def get_user_db_path(self):
        return self.get_user_db_dir() / "data_base.db"

    def get_user_config_path(self):
        return self.get_user_setting_dir() / "config.ini"

    def get_user_colors_path(self):
        return self.get_user_setting_dir() / "colors.json"

    def get_user_shortcuts_path(self):
        return self.get_user_data_path() / "shortcuts.json"
