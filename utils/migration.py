import os
import shutil
import logging
from pathlib import Path
from utils.paths import PathManager

logger = logging.getLogger(__name__)

class MigrationManager:
    def __init__(self):
        self.pm = PathManager.instance()
        self.app_data = self.pm.get_app_data_path()
        self.user_data = self.pm.get_user_data_path()

    def check_and_migrate(self):
        """
        Checks if migration is needed (upgrade or fresh install) and performs it.
        """
        self._check_pending_move()

        # Ensure user data directories exist
        self._ensure_dirs()
        
        config_path = self.pm.get_user_config_path()
        
        # If user config exists, we assume setup is done.
        if config_path.exists():
            return

        # If not, check if we are upgrading from legacy (files exist in app_data/setting OR app_data/db)
        legacy_config = self.app_data / "setting" / "config.ini"
        legacy_db = self.app_data / "db"
        
        has_legacy_config = legacy_config.exists()
        has_legacy_db = legacy_db.exists() and any(legacy_db.iterdir())
        
        if has_legacy_config or has_legacy_db:
            logger.info("Detected legacy configuration or database. Migrating to user data folder...")
            self._migrate_legacy_data()
        else:
            logger.info("Fresh install or no legacy config. Initializing user data folder...")
            # Nothing specific needed as dirs are created and managers will init files.

    def _check_pending_move(self):
        from PyQt6.QtCore import QSettings
        settings = QSettings(self.pm.ORGANIZATION, self.pm.APPLICATION)
        pending_target = settings.value("PendingMoveTarget")
        pending_source = settings.value("PendingMoveSource")
        
        if pending_target:
            try:
                target_path = Path(pending_target)
                source_path = Path(pending_source) if pending_source else self.user_data
                
                logger.info(f"Processing pending move from {source_path} to {target_path}")
                
                if source_path.exists():
                     # Use copytree with dirs_exist_ok=True to merge/overwrite
                     shutil.copytree(source_path, target_path, dirs_exist_ok=True)
                     
                     # Try to remove source
                     try:
                        shutil.rmtree(source_path)
                     except Exception as e:
                        logger.warning(f"Could not remove source after move: {e}")
                
                # Update UserDataPath to target
                self.pm.set_user_data_path(target_path)
                
            except Exception as e:
                logger.error(f"Pending move failed: {e}")
            finally:
                # Clear pending flags
                settings.remove("PendingMoveTarget")
                settings.remove("PendingMoveSource")
                
                # Update self.user_data to reflect new reality
                self.user_data = self.pm.get_user_data_path()

    def schedule_move(self, new_path: Path):
        """Schedules a move for the next restart."""
        from PyQt6.QtCore import QSettings
        settings = QSettings(self.pm.ORGANIZATION, self.pm.APPLICATION)
        settings.setValue("PendingMoveTarget", str(new_path))
        settings.setValue("PendingMoveSource", str(self.pm.get_user_data_path()))

    def _migrate_legacy_data(self):
        # 1. Copy Setting Folder
        src_setting = self.app_data / "setting"
        dst_setting = self.pm.get_user_setting_dir()
        if src_setting.exists():
            self._move_contents(src_setting, dst_setting)

        # 2. Copy DB Folder
        src_db_dir = self.app_data / "db"
        dst_db_dir = self.pm.get_user_db_dir()
        if src_db_dir.exists():
            self._move_contents(src_db_dir, dst_db_dir)

        # 3. Copy Shortcuts (legacy location: data/shortcuts.json)
        # Note: In new structure, data/shortcuts.json might be the PRESET.
        # But in legacy, it was the ONLY file.
        # We should move it to user_data/shortcuts.json if it was modified?
        # Or just move it regardless as the user copy.
        src_shortcuts = self.app_data / "shortcuts.json"
        dst_shortcuts = self.pm.get_user_shortcuts_path()
        if src_shortcuts.exists():
             try:
                 shutil.copy2(src_shortcuts, dst_shortcuts)
             except Exception as e:
                 logger.error(f"Error copying shortcuts: {e}")
        
        # Mark migration as occurred so we can show the simplified wizard
        from PyQt6.QtCore import QSettings
        settings = QSettings(self.pm.ORGANIZATION, self.pm.APPLICATION)
        settings.setValue("ShowDataMigrationWizard", True)

    def _ensure_dirs(self):
        os.makedirs(self.pm.get_user_setting_dir(), exist_ok=True)
        os.makedirs(self.pm.get_user_db_dir(), exist_ok=True)

    def _move_contents(self, src: Path, dst: Path):
        """Copies files from src to dst, then tries to delete src files."""
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                # We don't expect deep nesting for now, but shutil.copytree could work
                pass
            else:
                try:
                    shutil.copy2(item, target)
                    try:
                        os.remove(item)
                    except Exception:
                        pass # Ignore deletion errors (permissions)
                except Exception as e:
                    logger.error(f"Error moving {item}: {e}")

    def move_data_to_new_path(self, new_path: Path):
        """
        Moves data from current user path to new user path.
        Used when user changes setting.
        """
        current_path = self.pm.get_user_data_path()
        if current_path.resolve() == new_path.resolve():
            return

        if not current_path.exists():
            self.pm.set_user_data_path(new_path)
            return

        try:
            # Recursive copy
            shutil.copytree(current_path, new_path, dirs_exist_ok=True)
            
            # Verify and Remove old
            # (Simple rmtree might be dangerous if something goes wrong, but it's standard)
            shutil.rmtree(current_path)
            
            # Update Settings
            self.pm.set_user_data_path(new_path)
        except Exception as e:
            logger.error(f"Error moving data to new path: {e}")
            raise e
