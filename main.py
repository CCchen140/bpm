import sys
import multiprocessing as mp
from threading import Thread
import time
import os
import json
import traceback
from datetime import datetime

# Windows: 全局 monkey-patch multiprocessing，隐藏子进程控制台窗口
if sys.platform == "win32":
    try:
        import _winapi
        
        # 检查是否已经 patch 过（避免重复 patch）
        if not hasattr(_winapi.CreateProcess, '_no_window_patched'):
            # 保存原始的 _winapi.CreateProcess
            _original_create_process = _winapi.CreateProcess
            
            def _no_window_create_process(*args, **kwargs):
                # 修改 creation_flags 参数（第6个参数，索引为5）
                if len(args) >= 6:
                    args = list(args)
                    args[5] = args[5] | 0x08000000  # CREATE_NO_WINDOW
                    args = tuple(args)
                # 直接调用原始函数，不要通过 _winapi.CreateProcess
                return _original_create_process(*args, **kwargs)
            
            # 标记为已 patch
            _no_window_create_process._no_window_patched = True
            
            # 替换 _winapi.CreateProcess
            _winapi.CreateProcess = _no_window_create_process
    except Exception:
        pass

# 可选导入：pyecharts（用于思维导图功能，新 UI 不需要）
# from pyecharts import options as opts
# from pyecharts.charts import Tree

def _write_crash_log(message: str):
    """写入崩溃日志到文件"""
    try:
        # 获取程序根目录
        if getattr(sys, "frozen", False):
            root_dir = os.path.dirname(sys.executable)
        else:
            root_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 日志保存到 cache/logs/crash 目录
        log_dir = os.path.join(root_dir, "cache", "logs", "crash")
        os.makedirs(log_dir, exist_ok=True)
        
        # 按日期命名日志文件
        log_file = os.path.join(log_dir, f"crash_{datetime.now().strftime('%Y%m%d')}.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
            f.write(message)
            f.write("\n")
    except Exception:
        pass

def check_single_instance():
    """检查是否已有实例在运行，防止程序被多次启动"""
    try:
        import ctypes
        from ctypes import wintypes
        
        # 创建一个命名互斥量
        mutex_name = "Global\\BirdPictureManager_QiTu_SingleInstance"
        kernel32 = ctypes.windll.kernel32
        
        # 尝试创建互斥量
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = kernel32.GetLastError()
        
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            # 互斥量已存在，说明已有实例在运行
            print("Another instance is already running. Exiting.")
            _write_crash_log("已存在另一个实例，退出启动")
            return False
        
        return True
    except Exception as e:
        print(f"Single instance check failed: {e}")
        _write_crash_log(f"单实例检查失败: {e}\n{traceback.format_exc()}")
        # 如果检查失败，允许启动（避免阻止正常启动）
        return True

def setup_exception_hook():
    """设置全局异常钩子，记录崩溃信息"""
    def exception_hook(exc_type, exc_value, exc_tb):
        try:
            error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
            if exc_type is MemoryError:
                print(f"Memory low: {exc_value}")
                _write_crash_log(f"内存不足:\n{error_msg}")
            else:
                print(f"CRASH: {error_msg}")
                _write_crash_log(f"程序崩溃:\n{error_msg}")
        except Exception:
            pass
        # 调用原始异常处理
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    
    sys.excepthook = exception_hook


def _configure_windows_dll_search_paths():
    try:
        if sys.platform != "win32":
            return
    except Exception:
        return

    try:
        if bool(getattr(sys, "frozen", False)):
            base_dir = os.path.dirname(str(getattr(sys, "executable", "") or ""))
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base_dir = ""

    if not base_dir:
        return

    dll_dirs = []
    try:
        dll_dirs.append(base_dir)
        dll_dirs.append(os.path.join(base_dir, "torch", "lib"))
        dll_dirs.append(os.path.join(base_dir, "lib"))
    except Exception:
        pass

    try:
        nvidia_root = os.path.join(base_dir, "nvidia")
    except Exception:
        nvidia_root = ""
    if nvidia_root and os.path.isdir(nvidia_root):
        try:
            for root, _, filenames in os.walk(nvidia_root):
                try:
                    if any(str(fn).lower().endswith(".dll") for fn in filenames):
                        dll_dirs.append(root)
                except Exception:
                    pass
        except Exception:
            pass

    existing_dirs = []
    for p in dll_dirs:
        try:
            if p and os.path.isdir(p):
                existing_dirs.append(p)
        except Exception:
            pass

    try:
        old_path = os.environ.get("PATH", "")
        new_entries = [d for d in existing_dirs if d not in old_path]
        if new_entries:
            os.environ["PATH"] = os.pathsep.join(new_entries) + os.pathsep + old_path
    except Exception:
        pass

    if hasattr(os, "add_dll_directory"):
        for p in existing_dirs:
            try:
                os.add_dll_directory(p)
            except Exception:
                pass

if __name__ == "__main__":
    # 记录启动日志
    _write_crash_log(f"程序启动\nPID: {os.getpid()}\n命令行: {' '.join(sys.argv)}")
    
    mp.freeze_support()
    print("Multiprocessing support frozen")
    
    # 设置异常钩子
    setup_exception_hook()
    _configure_windows_dll_search_paths()
    
    # 检查是否是本地识别服务子进程
    is_bird_ipc_service = "--bird-ipc-service" in sys.argv
    
    # 检查是否已有实例在运行（本地识别服务子进程跳过此检查）
    if not is_bird_ipc_service and not check_single_instance():
        sys.exit(1)
    
    # 本地识别服务子进程
    if is_bird_ipc_service:
        try:
            print("[BirdIPC] 启动本地识别服务子进程...")
            try:
                import torch
                print(f"[BirdIPC] torch 导入成功: {torch.__version__}")
            except Exception as e:
                print(f"[BirdIPC] torch 导入失败: {e}")
                # 使用安全的方式打印异常信息，避免在打包环境下stderr无效导致OSError
                try:
                    import traceback
                    tb_str = traceback.format_exc()
                    print(f"[BirdIPC] torch导入异常详情: {tb_str}")
                except Exception:
                    pass
            from core.recognizer.bird_species_recognizer import run_local_bird_ipc_service
            run_local_bird_ipc_service()
            print("[BirdIPC] 本地识别服务子进程正常退出")
            sys.exit(0)
        except Exception as e:
            print(f"[BirdIPC] 本地识别服务子进程异常: {e}")
            # 使用安全的方式打印异常信息，避免在打包环境下stderr无效导致OSError
            try:
                import traceback
                tb_str = traceback.format_exc()
                print(f"[BirdIPC] 异常详情: {tb_str}")
            except Exception:
                pass
            sys.exit(1)
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

    print("Creating QApplication...")
    app = QApplication(sys.argv)

    # P1：立即显示加载框，将 LogManager/Migration/ColorManager 等放在其后，改善感知速度
    # 尝试从设置中读取主题配置，使加载窗口初始颜色与主题一致
    _theme_name = "default"
    try:
        from utils.paths import PathManager
        _pm = PathManager.instance()
        _setting_path = _pm.get_settings_path()
        if os.path.exists(_setting_path):
            with open(_setting_path, "r", encoding="utf-8") as _f:
                _setting_data = json.load(_f)
                _theme_name = str(_setting_data.get("general/theme", "default")).lower()
    except Exception:
        _theme_name = "default"
    
    # 根据主题设置初始颜色
    if _theme_name in ["dark", "black_orange"]:
        _bg_top, _bg_bottom, _text_color = "#1E242B", "#0F1419", "#E6EEF5"
    elif _theme_name == "summer_beach":
        _bg_top, _bg_bottom, _text_color = "#B7D0DB", "#FFF3D6", "#3A2A1A"
    elif _theme_name == "sakura":
        _bg_top, _bg_bottom, _text_color = "#D4B9C7", "#FFF5F8", "#3A2430"
    elif _theme_name == "neon":
        _bg_top, _bg_bottom, _text_color = "#2B2450", "#EEF2FF", "#1E1B3A"
    elif _theme_name == "cyberpunk":
        _bg_top, _bg_bottom, _text_color = "#2B2340", "#F6EEFF", "#2A163C"
    elif _theme_name == "ocean":
        _bg_top, _bg_bottom, _text_color = "#9CC9D6", "#E6F7F3", "#0E2F2A"
    elif _theme_name == "oriental":
        _bg_top, _bg_bottom, _text_color = "#A4B2A6", "#F6F1E7", "#3B2D1C"
    elif _theme_name == "meteor":
        _bg_top, _bg_bottom, _text_color = "#8AA1BA", "#ECF2FF", "#1D2C4A"
    elif _theme_name == "tech":
        _bg_top, _bg_bottom, _text_color = "#8BAAC0", "#E8F4F8", "#1A2E3B"
    elif _theme_name == "mint_breeze":
        _bg_top, _bg_bottom, _text_color = "#A8D5C7", "#E8F7F4", "#1E3A3A"
    elif _theme_name == "morning_mist":
        _bg_top, _bg_bottom, _text_color = "#8AA6C2", "#F2F7FD", "#223449"
    else:
        # 默认浅色主题
        _bg_top, _bg_bottom, _text_color = "#E3F2FD", "#FFFFFF", "#2C3E50"
    
    loading_dialog = None
    try:
        loading_dialog = QDialog()
        loading_dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        loading_dialog.setModal(False)
        loading_dialog.setFixedSize(560, 360)
        dialog_layout = QVBoxLayout(loading_dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.setSpacing(0)
        bg_top, bg_bottom, text_color = _bg_top, _bg_bottom, _text_color
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
        loading_dialog._icon_label = icon_label
        content_layout.addStretch()
        content_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        content_layout.addStretch()
        loading_label = QLabel("正在加载中", content)
        loading_label.setStyleSheet(f"QLabel {{ color: {text_color}; font-size: 14px; background: transparent; }}")
        content_layout.addWidget(loading_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        dialog_layout.addWidget(content)
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.left() + int((geo.width() - loading_dialog.width()) / 2)
            y = geo.top() + int((geo.height() - loading_dialog.height()) / 2)
            loading_dialog.move(x, y)
        loading_dialog.show()
        loading_dialog.raise_()
        loading_dialog.activateWindow()
        try:
            app.processEvents()
        except Exception:
            pass
    except Exception as e:
        print(f"Create loading dialog failed: {e}")
        loading_dialog = None

    try:
        print("Starting LogManager...")
        from utils.log_manager import LogManager
        LogManager.instance().start()
        from utils.system.app_info_manager import AppInfoManager
        AppInfoManager.instance().log_startup_info()
    except Exception as e:
        print(f"Logger init failed: {e}")
    try:
        QLoggingCategory.setFilterRules("\n".join([
            "qt.imageformats.tiff.debug=false",
            "qt.imageformats.tiff.info=false",
            "qt.imageformats.tiff.warning=false",
            "qt.imageformats.tiff.critical=false",
        ]))
    except Exception as e:
        print(f"Set logging rules failed: {e}")
    try:
        print("Checking for data migration...")
        from utils.migration import MigrationManager
        MigrationManager().check_and_migrate()
    except Exception as e:
        print(f"Migration failed: {e}")

    print("Importing managers...")
    from ui.utils.color_manager import ColorManager
    from ui.utils.app_icon import get_app_icon

    # 在后台启动 CUDA 探测线程，避免首次用到模型时卡顿
    try:
        from utils.system.gpu_utils import start_torch_cuda_probe_async, log_gpu_summary_async

        print("Starting CUDA probe in background...")
        start_torch_cuda_probe_async()
        log_gpu_summary_async(reason="startup")
    except Exception as e:
        print(f"Start CUDA probe failed: {e}")

    # 在后台启动本地鸟种检测服务端，避免首次识别时卡顿
    try:
        print("Starting local bird species detection service in background...")
        from core.recognizer.bird_species_recognizer import _get_local_bird_ipc_client
        
        def _start_bird_service_async():
            try:
                client = _get_local_bird_ipc_client()
                if client and client.ensure_service():
                    print("Local bird species detection service started successfully")
                else:
                    print("Failed to start local bird species detection service")
            except Exception as e:
                print(f"Start bird service failed: {e}")
        
        # 在后台线程中启动服务
        from threading import Thread
        bird_service_thread = Thread(target=_start_bird_service_async, daemon=True, name="BirdServiceStarter")
        bird_service_thread.start()
    except Exception as e:
        print(f"Start bird service thread failed: {e}")

    cm = ColorManager.instance()
    try:
        icon_color = cm.get("theme.primary", "#2196F3")
    except Exception as e:
        print(f"Get icon color failed: {e}")
        icon_color = "#2196F3"
    print("Loading app icon...")
    app_icon = get_app_icon(icon_color)

    # 用主题与图标更新已显示的加载框
    if loading_dialog:
        try:
            bg_top = cm.get("theme.sidebar", "#E3F2FD")
            bg_bottom = "#FFFFFF"
            text_color = cm.get("theme.primary", "#2C3E50")
            gradient = QLinearGradient(0, 0, 0, loading_dialog.height())
            gradient.setColorAt(0.0, QColor(bg_top))
            gradient.setColorAt(1.0, QColor(bg_bottom))
            palette = loading_dialog.palette()
            palette.setBrush(QPalette.ColorRole.Window, QBrush(gradient))
            loading_dialog.setPalette(palette)
            il = getattr(loading_dialog, "_icon_label", None)
            if il and app_icon:
                pixmap = app_icon.pixmap(120, 120)
                if pixmap is not None and not pixmap.isNull():
                    il.setPixmap(pixmap)
            if app_icon:
                loading_dialog.setWindowIcon(app_icon)
            app.processEvents()
        except Exception as e:
            print(f"Update loading dialog failed: {e}")

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
            
            # 主窗口加载完成后，启动自动更新检查
            try:
                def _start_auto_update_check():
                    try:
                        from update.update_manager import get_update_manager
                        update_manager = get_update_manager()
                        # 设置主窗口已加载
                        update_manager.set_main_window_loaded(True)
                        # 延迟 3 秒后执行后台检查
                        update_manager.check_update_after_load(delay_ms=3000)
                        print("Auto update check scheduled")
                    except Exception as e:
                        print(f"Start auto update check failed: {e}")
                
                # 延迟 5 秒后启动自动更新检查（确保主窗口完全加载）
                QTimer.singleShot(5000, _start_auto_update_check)
            except Exception as e:
                print(f"Schedule auto update check failed: {e}")
        
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
