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
    from PyQt6.QtCore import Qt, QCoreApplication, QLoggingCategory

    print("Setting OpenGL context sharing...")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    try:
        print("Importing QtWebEngineWidgets...")
        from PyQt6 import QtWebEngineWidgets
        print("QtWebEngineWidgets imported")
    except Exception as e:
        print(f"QtWebEngineWidgets import failed: {e}")
        QtWebEngineWidgets = None

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
    tooltip_bg = cm.get("theme.text.light")
    tooltip_text = cm.get("tooltip.text")
    tooltip_border = cm.get("tooltip.border")
    def _apply_global_styles():
        tooltip_bg0 = cm.get("theme.text.light")
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
        
        # 强制显示主界面，防止因初始化异常导致窗口永远不显示
        try:
            print(f"[{time.time()}] Starting initialization sequence...")
            if hasattr(window, "page_library") and hasattr(window.page_library, "cache_manager"):
                print(f"[{time.time()}] Starting cache loading...")
                window.page_library._library_cache_loading_started = True
                cache_thread = Thread(target=window.page_library.cache_manager.load_persistent_cache, daemon=True, name="LibraryCacheLoader")
                cache_thread.start()
                cache_wait_start = time.time()
                print(f"[{time.time()}] Entering cache wait loop...")
                while cache_thread.is_alive():
                    app.processEvents()
                    if time.time() - cache_wait_start > 1.5:
                        print(f"[{time.time()}] Cache loading backgrounded (timeout)")
                        break
                    time.sleep(0.01)
                print(f"[{time.time()}] Exited cache wait loop")
            
            page_library = getattr(window, "page_library", None)
            page_import = getattr(window, "page_import", None)
            
            if page_library is not None:
                print(f"[{time.time()}] Initializing Library Page (this might block)...")
                page_library._startup_blocking_show = True
                page_library.initialize()
                print(f"[{time.time()}] Library Page initialized")
            
            if page_import is not None:
                print(f"[{time.time()}] Initializing Import Page...")
                page_import._start_cache_loading()
                print(f"[{time.time()}] Import Page initialized")
            
            try:
                print(f"[{time.time()}] Warming up WebEngine...")
                window._warmup_webengine_once()
                print(f"[{time.time()}] WebEngine warmed up")
            except Exception as e:
                print(f"WebEngine warmup failed: {e}")
            
            window._startup_preloaded = True
            
            if page_library is not None:
                # 等待首页缩略图加载完成的超时时间 (秒)
                print(f"[{time.time()}] Waiting for thumbnails (timeout=5s)...")
                wait_start_time = time.time()
                WAIT_TIMEOUT = 5.0 
                
                loop_count = 0
                while True:
                    loop_count += 1
                    if loop_count % 50 == 0: # 每0.5秒打印一次
                        print(f"[{time.time()}] Waiting for thumbnails loop... {loop_count}")
                    
                    app.processEvents()
                    
                    # 超时保护，避免死循环
                    if time.time() - wait_start_time > WAIT_TIMEOUT:
                        try:
                            print(f"[{time.time()}] Thumbnail wait timeout!")
                            LogManager.instance().warning("Startup thumbnail wait timeout, proceeding...")
                        except Exception:
                            pass
                        break
                        
                    if not getattr(page_library, "all_image_files", None):
                        print(f"[{time.time()}] No images to load")
                        break
                        
                    # 检查 grid_view 是否存在
                    grid_view = getattr(page_library, "grid_view", None)
                    if not grid_view:
                        time.sleep(0.01)
                        continue
                        
                    thumbs = getattr(grid_view, "thumbnails", None)
                    # 如果没有缩略图控件，但有图片文件，说明可能还没开始构建缩略图
                    if not thumbs:
                        # 如果已经有文件但没有缩略图控件，可能需要给点时间让布局生效
                        # 或者直接跳过，让界面显示出来再加载
                        if len(page_library.all_image_files) > 0:
                             # 简单的超时检查已经足够
                             time.sleep(0.01)
                             continue
                        else:
                            break # 没有文件，直接结束等待
                            
                    start_idx, end_idx, _ = grid_view.get_visible_index_range(extra_rows=0)
                    if end_idx < start_idx:
                        # 可能是窗口还不可见，无法计算可视区域
                        # 这种情况下强行等待可能导致死锁（因为窗口显示需要此循环结束）
                        # 尝试几次后跳过
                        if time.time() - wait_start_time > 1.0:
                             try:
                                 print(f"[{time.time()}] Visible range check failed, skipping")
                                 LogManager.instance().warning("Cannot determine visible range, proceeding...")
                             except Exception:
                                 pass
                             break
                        time.sleep(0.01)
                        continue
                        
                    all_ready = True
                    # 检查可视区域内的缩略图是否已加载
                    check_range_end = min(end_idx, len(thumbs) - 1)
                    
                    # 如果没有任何可见的缩略图需要检查，视为就绪
                    if start_idx > check_range_end:
                         break
    
                    for i in range(start_idx, check_range_end + 1):
                        thumb = thumbs[i]
                        existing_pix = getattr(thumb, "thumbnail_pixmap", None)
                        existing_img = getattr(thumb, "_thumbnail_image", None)
                        # 也要检查是否有错误状态，如果有错误也视为"就绪"（不再等待）
                        has_error = getattr(thumb, "_has_error", False)
                        
                        has_existing_pix = existing_pix is not None and not (hasattr(existing_pix, "isNull") and existing_pix.isNull())
                        has_existing_img = existing_img is not None and not (hasattr(existing_img, "isNull") and existing_img.isNull())
                        
                        if not (has_existing_pix or has_existing_img or has_error):
                            all_ready = False
                            break
                    
                    if all_ready:
                        print(f"[{time.time()}] Thumbnails ready")
                        break
                    time.sleep(0.01)
                page_library._startup_blocking_show = False
                print(f"[{time.time()}] Initialization sequence finished")
        except Exception as e:
            print(f"CRITICAL INIT ERROR: {e}")
            import traceback
            traceback.print_exc()
            try:
                LogManager.instance().error(f"Startup initialization failed: {e}")
            except:
                pass
        
        # 无论上述初始化是否成功，都要显示主窗口并关闭加载遮罩
        window.show_main_interface()
        window.setWindowOpacity(1)
        try:
            if loading_dialog:
                loading_dialog.close()
                loading_dialog.deleteLater()
        except Exception:
            pass
    exit_code = app.exec()
            
    sys.exit(exit_code)
