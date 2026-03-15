from PyQt6.QtCore import QSettings, QByteArray, QStandardPaths, QObject, pyqtSignal
import os
import configparser
import sys
import threading
from utils.paths import PathManager


class SettingsManager(QObject):
    setting_changed = pyqtSignal(str, object) # key, value

    # 定义设置项元数据：默认值、类型、描述
    SETTINGS_DEFINITIONS = {
        "general/root_path": {"default": QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation), "type": str, "label": "图片库根目录"},
        "general/first_run": {"default": True, "type": bool, "label": "首次运行"},
        "general/guide_cache_cleared": {"default": False, "type": bool, "label": "引导页缓存已清理"},
        "general/use_config_ini": {"default": False, "type": bool, "label": "使用 config.ini 配置"},
        "general/version": {"default": "V0.0.1", "type": str, "label": "软件版本"},
        "theme/sidebar_color": {"default": "", "type": str, "label": "侧边栏颜色"},
        "theme/background_color": {"default": "", "type": str, "label": "背景颜色"},
        "theme/background_primary_color": {"default": "", "type": str, "label": "背景色"},
        "theme/background_light_color": {"default": "", "type": str, "label": "浅背景色"},
        "theme/background_dark_color": {"default": "", "type": str, "label": "深背景色"},
        "theme/primary_color": {"default": "", "type": str, "label": "强调色"},
        "theme/popup_color": {"default": "", "type": str, "label": "弹窗背景色"},
        "theme/text_dark_color": {"default": "", "type": str, "label": "深色文字"},
        "theme/text_light_color": {"default": "", "type": str, "label": "浅色文字"},
        "theme/preset_name": {"default": "原色", "type": str, "label": "主题预设名称"},
        "theme/sidebar_color_default": {"default": "", "type": str, "label": "侧边栏默认颜色"},
        "theme/background_color_default": {"default": "", "type": str, "label": "背景默认颜色"},
        "theme/background_primary_color_default": {"default": "", "type": str, "label": "背景色默认值"},
        "theme/background_light_color_default": {"default": "", "type": str, "label": "浅背景色默认值"},
        "theme/background_dark_color_default": {"default": "", "type": str, "label": "深背景色默认值"},
        "theme/primary_color_default": {"default": "", "type": str, "label": "强调色默认值"},
        "theme/popup_color_default": {"default": "", "type": str, "label": "弹窗默认背景色"},
        "theme/text_dark_color_default": {"default": "", "type": str, "label": "深色文字默认值"},
        "theme/text_light_color_default": {"default": "", "type": str, "label": "浅色文字默认值"},
        "setting/bird_strict": {"default": True, "type": bool, "label": "鸟类层级严格模式"},
        "general/font_name": {"default": "半粗体", "type": str, "label": "字体名称"},
        "general/font_family": {"default": "", "type": str, "label": "字体种类"},
        "general/font_variant": {"default": "", "type": str, "label": "字体子类型"},
        "library/folder_visible": {"default": True, "type": bool, "label": "显示文件夹栏"},
        "library/preview_visible": {"default": True, "type": bool, "label": "显示预览栏"},
        "library/folder_width": {"default": 280, "type": int, "label": "文件夹栏宽度"},
        "library/preview_width": {"default": 340, "type": int, "label": "预览栏宽度"},
        "library/last_folder": {"default": "", "type": str, "label": "上次打开文件夹"},
        "library/display_mode": {"default": 0, "type": int, "label": "显示模式"},
        "library/thumbnail_size": {"default": 0, "type": int, "label": "缩略图大小"},
        "library/thumbnail_info_font_size": {"default": 12, "type": int, "label": "缩略图信息文字字号"},
        "library/scan_depth": {"default": 0, "type": int, "label": "首次扫描深度"},
        "library/scan_exclude_dirs": {"default": "", "type": list, "label": "首次扫描排除目录"},
        "library/scan_exclude_regex": {"default": "", "type": str, "label": "首次扫描排除正则"},
        "library/sort_field": {"default": "文件名", "type": str, "label": "排序字段"},
        "library/sort_order": {"default": "", "type": str, "label": "排序顺序"},
        "library/spray_range_size": {"default": 1, "type": int, "label": "喷漆范围大小"},
        "library/delete_local_file_enabled": {"default": True, "type": bool, "label": "图库删除时同时删除本地文件"},
        "library/splitter_state": {"default": QByteArray(), "type": QByteArray, "label": "内容分割器状态"},
        "library/vertical_splitter_state": {"default": QByteArray(), "type": QByteArray, "label": "垂直分割器状态"},
        "library/preview_info_splitter_state": {"default": QByteArray(), "type": QByteArray, "label": "预览信息分割器状态"},
        "library/thumbnail_cache_size": {"default": 150, "type": int, "label": "图库缩略图缓存尺寸"},
        "library/thumbnail_scale_quality": {"default": "high", "type": str, "label": "图库缩放质量"},
        "performance/thumbnail_cache_size": {"default": 150, "type": int, "label": "缩略图缓存尺寸"},
        "performance/thumbnail_cache_count": {"default": 800, "type": int, "label": "缩略图缓存数量"},
        "performance/thumbnail_disable_scaling": {"default": False, "type": bool, "label": "缩略图禁用缩放"},
        "performance/thumbnail_scale_quality": {"default": "high", "type": str, "label": "缩放质量"},
        "performance/use_gpu_scaling": {"default": True, "type": bool, "label": "使用GPU缩放"},
        "performance/disable_thumbnail_persistence": {"default": False, "type": bool, "label": "禁用本地缩略图持久化"},
        "performance/disk_thumbnail_cache_max_bytes": {"default": 2147483648, "type": int, "label": "磁盘缩略图缓存上限字节"},
        "performance/disk_thumbnail_cache_cleanup_batch": {"default": 800, "type": int, "label": "磁盘缩略图单次清理文件数"},
        "performance/disk_thumbnail_cache_meta_library": {"default": "", "type": str, "label": "磁盘缩略图缓存元信息(图库)"},
        "performance/disk_thumbnail_cache_meta_import": {"default": "", "type": str, "label": "磁盘缩略图缓存元信息(导入)"},
        "window/geometry": {"default": None, "type": QByteArray, "label": "窗口位置大小"},
        "window/maximized": {"default": False, "type": bool, "label": "窗口最大化状态"},
        "window/fullscreen": {"default": False, "type": bool, "label": "窗口全屏状态"},
        "window/normal_rect": {"default": None, "type": list, "label": "窗口非最大化时的位置大小"},
        "geolocation/service": {"default": "tianditu", "type": str, "label": "地理编码服务"},
        "geolocation/gaode_key": {"default": "", "type": str, "label": "高德地图 API Key"},
        "geolocation/tianditu_key": {"default": "", "type": str, "label": "天地图 API Key"},
        "geolocation/coord_format": {"default": "decimal", "type": str, "label": "坐标显示格式"},
        "geolocation/tianditu_last_call_ts": {"default": 0, "type": float, "label": "天地图接口最后调用时间戳"},
        "track_match/max_time_diff_seconds": {"default": 60, "type": int, "label": "轨迹匹配的最大容差时间"},
        "image_detail/all_info_overlay_collapsed": {"default": False, "type": bool, "label": "大图信息浮窗折叠"},
        "log/level": {"default": "info", "type": str, "label": "日志等级"},
        "log/max_bytes": {"default": 2147483648, "type": int, "label": "日志目录最大占用字节"},
        "log/cleanup_target_bytes": {"default": 1073741824, "type": int, "label": "日志清理目标占用字节"},
        "log/print_to_console": {"default": False, "type": bool, "label": "日志输出到控制台"},
        "recognizer/service": {"default": "local", "type": str, "label": "物种识别服务"},
        "recognizer/doubao_api_key": {"default": "", "type": str, "label": "豆包 API Key"},
        "recognizer/dongniao_last_call_ts": {"default": 0, "type": float, "label": "懂鸟接口最后调用时间戳"},
        # Import Page Settings
        "import/thumbnail_size": {"default": 0, "type": int, "label": "导入页缩略图大小"},
        "import/thumbnail_cache_size": {"default": 300, "type": int, "label": "导入页缩略图缓存尺寸"},
        "import/thumbnail_scale_quality": {"default": "high", "type": str, "label": "导入页缩放质量"},
        "import/cache_size": {"default": 500, "type": int, "label": "导入页缩略图缓存数量"},
        "import/loader_threads": {"default": 4, "type": int, "label": "导入页加载线程数"},
        "import/root_paths": {"default": [], "type": list, "label": "导入页根目录列表"},
        "import/splitter_state": {"default": QByteArray(), "type": QByteArray, "label": "导入页内容分割器状态"},
        "import/vertical_splitter_state": {"default": QByteArray(), "type": QByteArray, "label": "导入页垂直分割器状态"},
        "import/preview_info_splitter_state": {"default": QByteArray(), "type": QByteArray, "label": "导入页预览信息分割器状态"},
        "import/folder_visible": {"default": True, "type": bool, "label": "导入页显示文件夹栏"},
        "import/preview_visible": {"default": True, "type": bool, "label": "导入页显示预览栏"},
        "import/delete_local_file_in_virtual_mode": {"default": False, "type": bool, "label": "虚拟模式删除记录时同时删除本地文件"},
        "image_detail/auto_switch_interval_ms": {"default": 800, "type": int, "label": "大图自动切换间隔(ms)"},
        "image_detail/zoom_scale": {"default": 1.0, "type": float, "label": "大图缩放比例"},
        "image_detail/magnifier_lens_radius": {"default": 150, "type": int, "label": "大图放大镜大小"},
        "external/open_image_app": {"default": "", "type": str, "label": "外部打开图片的软件"},
        "external/edit_image_app": {"default": "", "type": str, "label": "编辑图片的软件"},
        "focus_detect/folders": {"default": [], "type": list, "label": "对焦检测选择的文件夹"},
        "focus_detect/enable_burst": {"default": True, "type": bool, "label": "对焦检测启用连拍检测"},
        "focus_detect/enable_similarity": {"default": True, "type": bool, "label": "对焦检测启用相似度检测"},
        "focus_detect/use_multiprocess": {"default": True, "type": bool, "label": "对焦检测使用多进程加速"},
        "focus_detect/use_gpu": {"default": True, "type": bool, "label": "对焦检测使用GPU加速"},
        "focus_detect/multi_check": {"default": True, "type": bool, "label": "对焦检测多次检测"},
        "focus_detect/exp_frame_check": {"default": True, "type": bool, "label": "对焦检测爆框检测"},
        "focus_detect/enable_eye_detect": {"default": True, "type": bool, "label": "对焦检测鸟眼检测"},
        "focus_detect/enable_af_point_detect": {"default": True, "type": bool, "label": "对焦检测识别对焦点"},
        "focus_detect/append_detect": {"default": False, "type": bool, "label": "对焦检测追加检测"},
        "focus_detect/no_db_write": {"default": False, "type": bool, "label": "对焦检测不写入数据库"},
        "focus_detect/no_exif_write": {"default": False, "type": bool, "label": "对焦检测不写入EXIF信息"},
        "focus_detect/auto_switch_to_scan_mode": {"default": True, "type": bool, "label": "开始对焦检测后自动跳转至扫描文件模式"},
        "focus_detect/write_rating": {"default": True, "type": bool, "label": "对焦检测写入评星"},
        "focus_detect/write_label": {"default": True, "type": bool, "label": "对焦检测写入色标"},
        "focus_detect/model": {"default": "x", "type": str, "label": "对焦检测模型"},
        "focus_detect/target_size": {"default": 640, "type": int, "label": "对焦检测缩放尺寸"},
        "focus_detect/burst_min_count": {"default": 10, "type": int, "label": "连拍检测最小张数"},
        "focus_detect/burst_fps": {"default": 20, "type": int, "label": "连拍频率"},
        "focus_detect/reserve_cpu": {"default": 4, "type": int, "label": "最低CPU保留核心数"},
        "focus_detect/post_action": {"default": "none", "type": str, "label": "对焦检测后处理动作"},
        "focus_detect/post_dir": {"default": "", "type": str, "label": "对焦检测后处理目录"},
        "focus_detect/finish_action": {"default": "none", "type": str, "label": "对焦检测完成后动作"},
        "focus_detect/initial_conf": {"default": 0.15, "type": float, "label": "对焦检测初始置信度"},
        "focus_detect/detect_threads": {"default": 0, "type": int, "label": "检测线程数（0=自动）"},
        "focus_detect/gpu_batch_size": {"default": 0, "type": int, "label": "GPU批量推理数量（0=自动）"},
        "focus_detect/postprocess_workers": {"default": 0, "type": int, "label": "后处理并行worker数（0=自动）"},
        "focus_detect/cpu_gpu_ratio": {"default": 20, "type": int, "label": "CPU/GPU检测比例（0=纯GPU，100=纯CPU）"},
        "focus_detect_ui/show_subject_rect": {"default": True, "type": bool, "label": "对焦虚拟视图显示主体框"},
        "focus_detect_ui/show_focus_point": {"default": True, "type": bool, "label": "对焦虚拟视图显示对焦点"},
        "focus_detect_ui/sharp_threshold": {"default": 80, "type": int, "label": "对焦虚拟视图锐度阈值"},
        "focus_detect_ui/norm_sharp_threshold": {"default": 130, "type": int, "label": "对焦虚拟视图归一化锐度阈值"},
        "focus_detect_ui/normal_contrast_threshold": {"default": 0.8, "type": float, "label": "对焦虚拟视图普通对比阈值"},
        "focus_detect_ui/conf_threshold": {"default": 0.1, "type": float, "label": "对焦虚拟视图置信度阈值"},
        "focus_detect_ui/minimal_area_threshold": {"default": 0.001, "type": float, "label": "对焦虚拟视图极小占比阈值"},
        "focus_detect_ui/hf_ratio_threshold": {"default": 1.15, "type": float, "label": "对焦虚拟视图高频比例阈值"},
        "focus_detect_ui/hf_margin_threshold": {"default": 5.0, "type": float, "label": "对焦虚拟视图高频差值阈值"},
        "focus_detect_ui/texture_ratio_threshold": {"default": 1.1, "type": float, "label": "对焦虚拟视图纹理比例阈值"},
        "focus_detect_ui/texture_weight": {"default": 0.0, "type": float, "label": "对焦虚拟视图纹理权重"},
        "focus_detect_ui/focus_point_in_bird_sharp": {"default": False, "type": bool, "label": "对焦点在鸟上时默认锐利"},
        "import/virtual_auto_label": {"default": True, "type": bool, "label": "导入页虚拟视图自动色标"},
        "debug/focus_bbox_log": {"default": False, "type": bool, "label": "调试：记录对焦检测主体框写库异常"},
        "debug/focus_virtual_counts_log": {"default": False, "type": bool, "label": "调试：记录对焦虚拟文件夹统计"},
        "debug/focus_save_output": {"default": False, "type": bool, "label": "对焦检测保存调试输出"},
        "debug/focus_save_output_dir": {"default": "", "type": str, "label": "对焦检测调试输出目录"},
        "debug/charts_web_debug": {"default": False, "type": bool, "label": "数据图表 Web 调试"},
        "debug/watermark_dialog_disable_meta_load": {"default": False, "type": bool, "label": "调试：添加水印禁用元数据加载"},
        "debug/watermark_dialog_disable_preview_load": {"default": False, "type": bool, "label": "调试：添加水印禁用预览加载"},
        "charts/theme": {"default": "follow", "type": str, "label": "数据图表主题"},
        "charts/display_options_json": {"default": "{}", "type": str, "label": "数据图表显示选项(JSON)"},
        "charts/gpu_rendering_enabled": {"default": False, "type": bool, "label": "数据图表 GPU 渲染"},
        "charts/show_title": {"default": True, "type": bool, "label": "数据图表显示标题"},
        "charts/show_legend": {"default": True, "type": bool, "label": "数据图表显示图例"},
        "charts/show_grid": {"default": True, "type": bool, "label": "数据图表显示网格"},
        "charts/enable_animation": {"default": True, "type": bool, "label": "数据图表启用动画"},
        "charts/pause_refresh_on_mouse_leave": {"default": True, "type": bool, "label": "数据图表离开暂停刷新"},
        "charts/font_size": {"default": 12, "type": int, "label": "数据图表字号"},
        "charts/watermark_enabled": {"default": False, "type": bool, "label": "数据图表水印开关"},
        "charts/watermark_text": {"default": "", "type": str, "label": "数据图表水印文字"},
        "charts/watermark_font_size": {"default": 22, "type": int, "label": "数据图表水印字号"},
        "charts/echarts_theme": {"default": "dark", "type": str, "label": "数据图表 ECharts 主题"},
        "charts/window_style": {"default": "acrylic", "type": str, "label": "数据图表窗口样式"},
        "charts/ignore_empty_dates": {"default": False, "type": bool, "label": "数据图表忽略无图片日期"},
        "exif/disable_write": {"default": False, "type": bool, "label": "禁用 EXIF 写入"},
        "exif/write_mode": {"default": "xmp", "type": str, "label": "EXIF写入方式"},
        "system/hide_subprocess_console": {"default": True, "type": bool, "label": "隐藏外部命令行窗口"},
        "debug/test_guide_overlay": {"default": False, "type": bool, "label": "测试引导遮罩"},
    }

    """
    通用设置管理器，使用 QSettings 存储配置。
    默认存储位置取决于操作系统（Windows 下为注册表）。
    """
    _instances = {}
    _instance_lock = threading.Lock()

    @classmethod
    def _default_profile(cls):
        is_frozen = bool(getattr(sys, "frozen", False))
        if is_frozen:
            try:
                v = str(os.environ.get("BPM_SETTINGS_PROFILE_PACKAGED") or os.environ.get("BPM_PROFILE_PACKAGED") or "").strip()
            except Exception:
                v = ""
            if v:
                return v
            return "packaged"
        try:
            v = str(os.environ.get("BPM_SETTINGS_PROFILE") or os.environ.get("BPM_PROFILE") or "").strip()
        except Exception:
            v = ""
        if v:
            return v
        return "dev"

    @classmethod
    def instance(cls, profile=None, organization="BirdPictureManager", application="BirdManager"):
        if profile is None:
            profile = cls._default_profile()
        key = (str(organization), str(application), str(profile))
        with cls._instance_lock:
            inst = cls._instances.get(key)
            if inst is None:
                inst = cls(organization=organization, application=application, profile=profile)
                cls._instances[key] = inst
            return inst

    def __init__(self, organization="BirdPictureManager", application="BirdManager", profile=None):
        super().__init__()
        if profile is None:
            profile = self._default_profile()
        self.profile = str(profile or "").strip()
        app_name = f"{application}_{profile}" if profile else str(application)
        self.settings = QSettings(organization, app_name)
        self._use_config_ini = False
        self._config_sync_lock = threading.Lock()
        self._config_sync_timer = None
        self._config_sync_delay_sec = 0.25
        self._config_sync_pending = False
        try:
            self._migrate_from_legacy_qsettings(organization, application)
        except Exception:
            pass
        self._init_config_file()
        use_config = self.get("general/use_config_ini", False)
        self._use_config_ini = bool(use_config)
        if use_config:
            self.load_from_config()

    def _migrate_from_legacy_qsettings(self, organization, application):
        try:
            if bool(getattr(sys, "frozen", False)):
                return
        except Exception:
            return
        important_keys = [
            "general/root_path",
            "general/first_run",
            "library/last_folder",
            "library/folder_width",
            "library/preview_width",
            "library/folder_visible",
            "library/preview_visible",
            "window/geometry",
            "window/normal_rect",
            "window/maximized",
            "window/fullscreen",
        ]
        try:
            migrated = self.settings.value("system/_migrated_from_legacy_v1", False) in [True, "true", "True", "1", 1]
        except Exception:
            migrated = False
        try:
            legacy = QSettings(str(organization), str(application))
        except Exception:
            return
        if migrated:
            try:
                for k in important_keys:
                    try:
                        if self.settings.contains(k):
                            continue
                    except Exception:
                        continue
                    try:
                        if legacy.contains(k):
                            self.settings.setValue(k, legacy.value(k))
                    except Exception:
                        pass
                self.settings.sync()
            except Exception:
                pass
            return
        try:
            keys = legacy.allKeys() or []
        except Exception:
            keys = []
        if not keys:
            try:
                self.settings.setValue("system/_migrated_from_legacy_v1", True)
                self.settings.sync()
            except Exception:
                pass
            return
        for k in keys:
            try:
                if self.settings.contains(k):
                    continue
            except Exception:
                pass
            try:
                self.settings.setValue(k, legacy.value(k))
            except Exception:
                pass
        try:
            self.settings.setValue("system/_migrated_from_legacy_v1", True)
            self.settings.sync()
        except Exception:
            pass

    def get_definition(self, key):
        """获取设置定义"""
        return self.SETTINGS_DEFINITIONS.get(key, {})

    def get(self, key, default=None):
        """获取设置值"""
        # 1. 确定使用的默认值
        def_val = None
        if key in self.SETTINGS_DEFINITIONS:
            def_val = self.SETTINGS_DEFINITIONS[key]["default"]
        
        # 调用者提供的 default 优先级更高
        final_default = default if default is not None else def_val
            
        # 2. 从 QSettings 获取原始值
        val = self.settings.value(key, final_default)
        
        # 3. 类型转换（即使提供了 default 也要检查，防止 QSettings 返回字符串）
        if key in self.SETTINGS_DEFINITIONS:
            target_type = self.SETTINGS_DEFINITIONS[key]["type"]
            
            # 特殊处理 QByteArray
            if target_type == QByteArray:
                if isinstance(val, QByteArray):
                    return val
                if isinstance(val, bytes):
                    return QByteArray(val)
                if isinstance(val, str):
                    try:
                        return QByteArray.fromBase64(val.encode("ascii"))
                    except Exception:
                        return def_val
                return def_val

            if target_type == bool:
                if isinstance(val, bool):
                    return val
                if isinstance(val, str):
                    return val.lower() == 'true'
                # 显式处理 int/bool 类型，避免 bool("False") 为 True 的情况
                try:
                    return bool(int(val)) # 尝试转 int 再转 bool (针对 "0"/"1" 字符串)
                except:
                    return bool(val)

            if target_type == list:
                # 确保 list 类型被正确解析（QSettings 可能存为字符串）
                if isinstance(val, str):
                    # 尝试解析字符串列表，这里简单假设是逗号分隔或者是 repr 格式
                    try:
                        import ast
                        parsed = ast.literal_eval(val)
                        if isinstance(parsed, list):
                            try:
                                return [int(x) for x in parsed]
                            except Exception:
                                return parsed
                    except:
                        pass
                if isinstance(val, list):
                    # 转换列表中的元素类型，这里假设都是 int (针对 rect)
                    try:
                        return [int(x) for x in val]
                    except:
                        return val
                return def_val

            try:
                if val is not None:
                    return target_type(val)
            except:
                pass
                
        return val

    def set(self, key, value):
        """保存设置值"""
        self.settings.setValue(key, value)
        if str(key or "") == "general/use_config_ini":
            try:
                self._use_config_ini = bool(self.get("general/use_config_ini", False))
            except Exception:
                self._use_config_ini = bool(value)
            if self._use_config_ini:
                self._schedule_sync_to_config()
        if self._use_config_ini:
            self._schedule_sync_to_config()
        self.setting_changed.emit(key, value)

    def _schedule_sync_to_config(self):
        if not self._use_config_ini:
            return
        try:
            delay = float(self._config_sync_delay_sec)
        except Exception:
            delay = 0.25
        with self._config_sync_lock:
            self._config_sync_pending = True
            t = self._config_sync_timer
            if t is not None:
                try:
                    t.cancel()
                except Exception:
                    pass
            timer = threading.Timer(delay, self._flush_scheduled_sync_to_config)
            timer.daemon = True
            self._config_sync_timer = timer
            try:
                timer.start()
            except Exception:
                self._config_sync_timer = None

    def _flush_scheduled_sync_to_config(self):
        with self._config_sync_lock:
            pending = bool(self._config_sync_pending)
            self._config_sync_pending = False
            self._config_sync_timer = None
        if not pending:
            return
        try:
            self.sync_to_config()
        except Exception:
            pass
        
    def contains(self, key):
        """检查键是否存在"""
        return self.settings.contains(key)
        
    def remove(self, key):
        """删除键"""
        self.settings.remove(key)

    def clear(self):
        self.settings.clear()
        self.sync()
        self.sync_to_config()
        
    def sync(self):
        """强制写入磁盘/注册表"""
        self.settings.sync()

    def _read_config_parser(self, config_path):
        parser = configparser.ConfigParser()
        parser.optionxform = str
        if not config_path.exists():
            return parser, False
        try:
            parser.read(config_path, encoding="utf-8")
            return parser, False
        except (configparser.DuplicateSectionError, configparser.DuplicateOptionError, configparser.ParsingError):
            parser2 = configparser.ConfigParser(strict=False)
            parser2.optionxform = str
            parser2.read(config_path, encoding="utf-8")
            return parser2, True

    def _init_config_file(self):
        config_path = PathManager.instance().get_user_config_path()
        config_dir = config_path.parent
        if not config_dir.exists():
            os.makedirs(config_dir, exist_ok=True)

        parser, repaired = self._read_config_parser(config_path)

        changed = bool(repaired)

        for key, meta in self.SETTINGS_DEFINITIONS.items():
            section, sep, name = key.partition("/")
            if not section:
                section = "DEFAULT"
            if section not in parser:
                parser[section] = {}
                changed = True
            if name not in parser[section]:
                default = meta["default"]
                if isinstance(default, QByteArray):
                    if default is not None and not default.isEmpty():
                        value_str = bytes(default.toBase64()).decode("ascii")
                    else:
                        value_str = ""
                elif isinstance(default, (list, tuple)):
                    value_str = repr(list(default))
                else:
                    value_str = "" if default is None else str(default)
                parser[section][name] = value_str
                changed = True
            if not self.contains(key):
                self.settings.setValue(key, meta["default"])

        if changed or not config_path.exists():
            with open(config_path, "w", encoding="utf-8") as f:
                parser.write(f)

    def sync_to_config(self, key=None):
        config_path = PathManager.instance().get_user_config_path()
        config_dir = config_path.parent
        if not config_dir.exists():
            os.makedirs(config_dir, exist_ok=True)
        parser, repaired = self._read_config_parser(config_path)

        def _write_value_to_parser(k):
            section, sep, name = k.partition("/")
            if not section:
                section = "DEFAULT"
            if section not in parser:
                parser[section] = {}
            val = self.settings.value(k)
            if isinstance(val, QByteArray):
                if val is not None and not val.isEmpty():
                    value_str = bytes(val.toBase64()).decode("ascii")
                else:
                    value_str = ""
            elif isinstance(val, (list, tuple)):
                value_str = repr(list(val))
            else:
                value_str = "" if val is None else str(val)
            parser[section][name] = value_str

        if key is None:
            parser.clear()
            for k in self.settings.allKeys():
                _write_value_to_parser(k)
        else:
            _write_value_to_parser(key)

        with open(config_path, "w", encoding="utf-8") as f:
            parser.write(f)

    def load_from_config(self):
        config_path = PathManager.instance().get_user_config_path()
        if not config_path.exists():
            return
        parser, repaired = self._read_config_parser(config_path)
        for section in parser.sections():
            for name, value in parser.items(section):
                if section == "DEFAULT":
                    full_key = name
                else:
                    full_key = f"{section}/{name}"
                self.settings.setValue(full_key, value)
        if parser.defaults():
            for name, value in parser.defaults().items():
                self.settings.setValue(name, value)
        if repaired:
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    parser.write(f)
            except Exception:
                pass
        self.sync()

    def restore_defaults(self, exclude_keys=None):
        """
        恢复所有用户设置到默认值，包括清理未定义的键
        :param exclude_keys: 不需要恢复的键列表
        """
        if exclude_keys is None:
            exclude_keys = []
            
        # 1. 备份需要保留的设置
        preserved_values = {}
        for key in exclude_keys:
            if self.contains(key):
                preserved_values[key] = self.settings.value(key)
        
        # 2. 清除所有现有设置
        self.settings.clear()
        
        # 3. 重新写入默认值
        for key, meta in self.SETTINGS_DEFINITIONS.items():
            self.settings.setValue(key, meta["default"])
            
        # 4. 恢复备份的设置
        for key, value in preserved_values.items():
            self.settings.setValue(key, value)
            
        self.sync()
        self.sync_to_config()
