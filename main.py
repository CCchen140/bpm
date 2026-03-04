import sys
import multiprocessing as mp
from threading import Thread
import time
import os

# 可选导入：pyecharts（用于思维导图功能，新 UI 不需要）
# from pyecharts import options as opts
# from pyecharts.charts import Tree

if __name__ == "__main__":
    mp.freeze_support()
    print("Multiprocessing support frozen")
    try:
        if "--bird-ipc-service" in sys.argv:
            try:
                import torch
            except Exception:
                pass
            from core.recognizer.bird_species_recognizer import run_local_bird_ipc_service

            run_local_bird_ipc_service()
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Start bird ipc service failed: {e}")
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BirdPictureManager.QiTu")
            print("Set AppUserModelID success")
    except Exception as e:
        print(f"Set AppUserModelID failed: {e}")
    try:
        from utils.system.subprocess_patch import patch_subprocess_no_console

        patch_subprocess_no_console()
        print("Patched subprocess")
    except Exception as e:
        print(f"Patch subprocess failed: {e}")

    print("Importing PyQt6 widgets...")
    from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QFrame
    from PyQt6.QtGui import QIcon, QGuiApplication, QPalette, QBrush, QLinearGradient, QColor, QFont
    from PyQt6.QtCore import Qt, QCoreApplication, QLoggingCategory, QTimer

    print("Setting OpenGL context sharing...")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    try:
        from utils.log_manager import LogManager

        print("Starting LogManager...")
        LogManager.instance().start()
        print("install_print_hook")
        # LogManager.instance().install_print_hook()
        from utils.system.app_info_manager import AppInfoManager
        print("AppInfoManager started")
        AppInfoManager.instance().log_startup_info()
        print("LogManager started")
    except Exception as e:
        print(f"Logger init failed: {e}")

    try:
        print("Setting logging rules...")
        QLoggingCategory.setFilterRules("\n".join([
            "qt.imageformats.tiff.debug=false",
            "qt.imageformats.tiff.info=false",
            "qt.imageformats.tiff.warning=false",
            "qt.imageformats.tiff.critical=false",
        ]))
    except Exception as e:
        print(f"Set logging rules failed: {e}")
    
    print("Creating QApplication...")
    app = QApplication(sys.argv)

    try:
        print("Checking for data migration...")
        from utils.migration import MigrationManager
        MigrationManager().check_and_migrate()
    except Exception as e:
        print(f"Migration failed: {e}")

    print("Importing managers...")
    from ui.utils.color_manager import ColorManager
    from ui.utils.app_icon import get_app_icon

    # 在后台线程预加载 CUDA 信息，避免后续对焦检测时卡顿
    def _preload_cuda_info():
        try:
            from utils.system.gpu_utils import is_torch_cuda_usable
            print("Preloading CUDA info in background...")
            result = is_torch_cuda_usable()
            print(f"CUDA preload complete: available={result}")
        except Exception as e:
            print(f"CUDA preload failed: {e}")
    
    Thread(target=_preload_cuda_info, daemon=True).start()

    cm = ColorManager.instance()
    try:
        icon_color = cm.get("theme.primary", "#2196F3")
    except Exception as e:
        print(f"Get icon color failed: {e}")
        icon_color = "#2196F3"
    
    print("Loading app icon...")
    app_icon = get_app_icon(icon_color)
    loading_dialog = None
    try:
        print("Creating loading dialog...")
        loading_dialog = QDialog()
        loading_dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        loading_dialog.setModal(False)
        loading_dialog.setFixedSize(560, 360)
        dialog_layout = QVBoxLayout(loading_dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.setSpacing(0)
        bg_top = cm.get("theme.sidebar", "#E3F2FD")
        bg_bottom = "#FFFFFF"
        text_color = cm.get("theme.primary", "#2C3E50")
        icon_color = cm.get("theme.primary", "#2196F3")
        gradient = QLinearGradient(0, 0, 0, loading_dialog.height())
        gradient.setColorAt(0.0, QColor(bg_top))
        gradient.setColorAt(1.0, QColor(bg_bottom))
        palette = loading_dialog.palette()
        palette.setBrush(QPalette.ColorRole.Window, QBrush(gradient))
        loading_dialog.setAutoFillBackground(True)
        loading_dialog.setPalette(palette)
        content = QFrame(loading_dialog)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 40, 40, 30)
        content_layout.setSpacing(0)
        icon_label = QLabel(content)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            if app_icon:
                pixmap = app_icon.pixmap(120, 120)
                if pixmap is not None and not pixmap.isNull():
                    icon_label.setPixmap(pixmap)
        except Exception as e:
            print(f"Set loading icon failed: {e}")
        content_layout.addStretch()
        content_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        content_layout.addStretch()
        loading_label = QLabel("正在加载中", content)
        loading_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: 14px;
                background: transparent;
            }}
        """)
        content_layout.addWidget(loading_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        dialog_layout.addWidget(content)
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.left() + int((geo.width() - loading_dialog.width()) / 2)
            y = geo.top() + int((geo.height() - loading_dialog.height()) / 2)
            loading_dialog.move(x, y)
        try:
            if app_icon:
                loading_dialog.setWindowIcon(app_icon)
        except Exception as e:
            print(f"Set dialog icon failed: {e}")
        loading_dialog.show()
        loading_dialog.raise_()
        loading_dialog.activateWindow()
        try:
            app.processEvents()
        except Exception as e:
            print(f"Process events failed: {e}")
        print("Loading dialog shown")
    except Exception as e:
        print(f"Create loading dialog failed: {e}")
        loading_dialog = None

    from utils.sql.data_base import get_default_db_path
    from utils.setting.settings_manager import SettingsManager
    from utils.log_manager import LogManager
    try:
        _sm = SettingsManager()
        db_path = get_default_db_path()
        is_first_run = _sm.get("general/first_run")
        if isinstance(is_first_run, str):
            is_first_run = is_first_run.lower() == "true"
        if bool(is_first_run) and os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception as e:
                print(f"Remove old DB failed: {e}")
            for ext in ["-wal", "-shm"]:
                try:
                    p = str(db_path) + ext
                    if os.path.exists(p):
                        os.remove(p)
                except Exception as e:
                    print(f"Remove DB WAL/SHM failed: {e}")
        if not os.path.exists(db_path):
            _sm.set("general/first_run", True)
            _sm.sync()
    except Exception as e:
        print(f"First run DB cleanup failed: {e}")

    print("Importing MainWindow...")
    from ui.main_window import MainWindow
    tooltip_bg = cm.get("tooltip.background")
    tooltip_text = cm.get("tooltip.text")
    tooltip_border = cm.get("tooltip.border")
    def _apply_global_styles():
        tooltip_bg0 = cm.get("tooltip.background")
        tooltip_text0 = cm.get("tooltip.text")
        tooltip_border0 = cm.get("tooltip.border")
        combo_hover_bg = cm.get("theme.background.dark")
        combo_selected_bg = cm.get("theme.primary")
        combo_selected_text = cm.get("theme.text.light")
        combo_text = cm.get("theme.text.dark")
        combo_border = cm.get("popup.border.primary")
        combo_bg = cm.get("theme.background.light")
        app.setStyleSheet(f"""
            QToolTip {{
                background-color: {tooltip_bg0};
                color: {tooltip_text0};
                border: 1px solid {tooltip_border0};
                font-size: 11px;
            }}
            QMenu::item:selected {{
                background-color: {combo_selected_bg};
                color: {combo_selected_text};
            }}
            QAbstractItemView {{
                outline: none;
                selection-background-color: {combo_selected_bg};
                selection-color: {combo_selected_text};
            }}
            QAbstractItemView::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QAbstractItemView::item:hover {{
                background-color: {combo_hover_bg};
            }}
            QAbstractItemView::item:selected {{
                background-color: {combo_selected_bg};
                color: {combo_selected_text};
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {combo_border};
                background-color: {combo_bg};
                color: {combo_text};
                outline: none;
                selection-background-color: {combo_selected_bg};
                selection-color: {combo_selected_text};
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {combo_hover_bg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {combo_selected_bg};
                color: {combo_selected_text};
            }}
        """)

    try:
        ColorManager.instance().register_listener(_apply_global_styles)
    except Exception:
        pass
    _apply_global_styles()
    tooltip_font = app.font()
    tooltip_font.setPointSize(10)
    app.setFont(tooltip_font, "QToolTip")
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
    icon_path = os.path.join(base_path, "assets", "icons", "bpm_512.ico")
    if app_icon:
        app.setWindowIcon(app_icon)
    
    print("Instantiating MainWindow...")
    try:
        window = MainWindow(defer_startup=True)
        print("MainWindow instantiated")
    except Exception as e:
        print(f"MainWindow instantiation failed: {e}")
        import traceback
        traceback.print_exc()
        raise e

    if app_icon:
        window.setWindowIcon(app_icon)
    is_first_run = window.settings_manager.get("general/first_run")
    if isinstance(is_first_run, str):
        is_first_run = is_first_run.lower() == "true"
    
    print(f"Is first run: {is_first_run}")
    if is_first_run:
        print("Showing guide...")
        window.show_guide()
        window.show()
        window.setWindowOpacity(1)
        try:
            if loading_dialog:
                loading_dialog.close()
        except Exception as e:
            print(f"Close loading dialog failed: {e}")
    else:
        print("Showing main window (hidden initially)...")
        window.setWindowOpacity(0)
        window.show()
        try:
            if loading_dialog:
                loading_dialog.show()
                loading_dialog.raise_()
                loading_dialog.activateWindow()
        except Exception as e:
            print(f"Show loading dialog failed: {e}")
        app.processEvents()
        
        def _start_async_init():
            try:
                if hasattr(window, "page_library") and hasattr(window.page_library, "cache_manager"):
                    window.page_library._library_cache_loading_started = True
                    cache_thread = Thread(
                        target=window.page_library.cache_manager.load_persistent_cache,
                        daemon=True,
                        name="LibraryCacheLoader",
                    )
                    cache_thread.start()
            except Exception:
                pass
            page_library = getattr(window, "page_library", None)
            page_import = getattr(window, "page_import", None)
            if page_library is not None:
                try:
                    page_library._startup_blocking_show = False
                except Exception:
                    pass
                QTimer.singleShot(0, page_library.initialize)
            if page_import is not None:
                QTimer.singleShot(0, page_import._start_cache_loading)
            try:
                QTimer.singleShot(0, window._warmup_webengine_once)
            except Exception:
                pass
            try:
                window.show_main_interface()
                window.setWindowOpacity(1)
                window.raise_()
                window.activateWindow()
            except Exception:
                pass
            try:
                if loading_dialog:
                    def _close_loading():
                        try:
                            loading_dialog.close()
                            loading_dialog.deleteLater()
                        except Exception:
                            pass
                    QTimer.singleShot(50, _close_loading)
            except Exception:
                pass
        try:
            if loading_dialog:
                loading_dialog.show()
                loading_dialog.raise_()
                loading_dialog.activateWindow()
        except Exception:
            pass
        QTimer.singleShot(0, _start_async_init)
    exit_code = app.exec()
            
    sys.exit(exit_code)
