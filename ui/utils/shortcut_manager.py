import json
import os
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QAction, QShortcut
from utils.log_manager import LogManager

class ShortcutManager(QObject):
    """
    全局快捷键管理器 (Singleton)
    用于统一管理应用内的快捷键配置
    """
    _instance = None
    shortcuts_changed = pyqtSignal() # 快捷键变更信号
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = ShortcutManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        # 存储快捷键配置: id -> {'sequence': str/QKeySequence, 'desc': str, 'default': str}
        self.shortcuts = {}
        self.actions = {} # id -> QAction or list of QActions
        from utils.paths import PathManager
        pm = PathManager.instance()
        self.config_path = str(pm.get_user_shortcuts_path())
        self.default_config_path = str(pm.get_app_data_path() / "shortcuts.json")
        self._init_defaults()
        self.load_shortcuts()

    def _init_defaults(self):
        """初始化默认快捷键"""
        # 这里的 ID 建议使用 "Context.Action" 的格式
        self.register_default("ImageDetail.ZoomIn", "W", "在大图模式下放大图片")
        self.register_default("ImageDetail.ZoomOut", "S", "在大图模式下缩小图片")
        self.register_default("ImageDetail.Rotate", "Q", "旋转图片")
        self.register_default("ImageDetail.ToggleMagnifier", "E", "切换放大镜模式")
        self.register_default("ImageDetail.ToggleCompareMode", "Z", "切换对比模式")
        self.register_default("ImageDetail.DetectSubject", "X", "检测主体")
        self.register_default("ImageDetail.ToggleSubjectRect", "C", "显示/隐藏主体框")
        self.register_default("ImageDetail.ZoomToBird", "V", "聚焦主体")
        self.register_default("ImageDetail.ToggleFocusPoint", "B", "显示/隐藏对焦点")
        self.register_default("ImageDetail.PrevImage", "A", "上一张图片")
        self.register_default("ImageDetail.NextImage", "D", "下一张图片")
        self.register_default("ImageDetail.AutoPrev", "Ctrl+A", "大图自动往前（快退）")
        self.register_default("ImageDetail.AutoNext", "Ctrl+D", "大图自动往后（快进）")
        self.register_default("ImageDetail.AutoPause", "Ctrl+Space", "暂停/继续大图自动切换")
        self.register_default("ImageDetail.ResetView", "Tab", "复原拖动和缩放")
        self.register_default("ImageDetail.ToggleFavorite", "`", "收藏/取消收藏（当前/选中图片）")
        self.register_default("ImageDetail.SetRating1", "1", "评分1星（重复按取消）")
        self.register_default("ImageDetail.SetRating2", "2", "评分2星（重复按取消）")
        self.register_default("ImageDetail.SetRating3", "3", "评分3星（重复按取消）")
        self.register_default("ImageDetail.SetRating4", "4", "评分4星（重复按取消）")
        self.register_default("ImageDetail.SetRating5", "5", "评分5星（重复按取消）")
        self.register_default("ImageDetail.SetLabel0", "Ctrl+0", "清除色标（重复按取消）")
        self.register_default("ImageDetail.SetLabel1", "Ctrl+1", "色标红色（重复按取消）")
        self.register_default("ImageDetail.SetLabel2", "Ctrl+2", "色标橙色（重复按取消）")
        self.register_default("ImageDetail.SetLabel3", "Ctrl+3", "色标黄色（重复按取消）")
        self.register_default("ImageDetail.SetLabel4", "Ctrl+4", "色标绿色（重复按取消）")
        self.register_default("ImageDetail.SetLabel5", "Ctrl+5", "色标青色（重复按取消）")
        self.register_default("ImageDetail.SetLabel6", "Ctrl+6", "色标蓝色（重复按取消）")
        self.register_default("ImageDetail.SetLabel7", "Ctrl+7", "色标紫色（重复按取消）")
        self.register_default("ImageDetail.SetLabel8", "Ctrl+8", "色标粉色（重复按取消）")
        self.register_default("ImageDetail.SetLabel9", "Ctrl+9", "色标白色（重复按取消）")
        self.register_default("ImageDetailRight.ToggleFavorite", "Alt+`", "收藏/取消收藏（当前/选中图片）")
        self.register_default("ImageDetailRight.SetRating1", "Alt+1", "评分1星（重复按取消）")
        self.register_default("ImageDetailRight.SetRating2", "Alt+2", "评分2星（重复按取消）")
        self.register_default("ImageDetailRight.SetRating3", "Alt+3", "评分3星（重复按取消）")
        self.register_default("ImageDetailRight.SetRating4", "Alt+4", "评分4星（重复按取消）")
        self.register_default("ImageDetailRight.SetRating5", "Alt+5", "评分5星（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel0", "Alt+Ctrl+0", "清除色标（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel1", "Alt+Ctrl+1", "色标红色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel2", "Alt+Ctrl+2", "色标橙色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel3", "Alt+Ctrl+3", "色标黄色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel4", "Alt+Ctrl+4", "色标绿色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel5", "Alt+Ctrl+5", "色标青色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel6", "Alt+Ctrl+6", "色标蓝色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel7", "Alt+Ctrl+7", "色标紫色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel8", "Alt+Ctrl+8", "色标粉色（重复按取消）")
        self.register_default("ImageDetailRight.SetLabel9", "Alt+Ctrl+9", "色标白色（重复按取消）")
        self.register_default("ImageDetail.PanUp", "Alt+W", "上移/移动放大镜（对比模式未放大时Alt+A/D切换左图）")
        self.register_default("ImageDetail.PanDown", "Alt+S", "下移/移动放大镜")
        self.register_default("ImageDetail.PanLeft", "Alt+A", "左移/移动放大镜（对比模式未放大时切换左图）")
        self.register_default("ImageDetail.PanRight", "Alt+D", "右移/移动放大镜（对比模式未放大时切换左图）")
        self.register_default("ImageDetail.MagnifierZoomInWheel", "WheelUp", "放大镜倍率增加（滚轮上）")
        self.register_default("ImageDetail.MagnifierZoomOutWheel", "WheelDown", "放大镜倍率减少（滚轮下）")
        self.register_default("ImageDetail.MagnifierLensBiggerWheel", "Shift+WheelUp", "放大镜大小增加（Shift+滚轮上）")
        self.register_default("ImageDetail.MagnifierLensSmallerWheel", "Shift+WheelDown", "放大镜大小减少（Shift+滚轮下）")
        self.register_default("ImageDetail.Close", "F", "退出大图模式")
        self.register_default("ImageLibrary.ZoomIn", "Ctrl+WheelUp", "在图库中放大缩略图")
        self.register_default("ImageLibrary.ZoomOut", "Ctrl+WheelDown", "在图库中缩小缩略图")
        self.register_default("ImageLibrary.SelectAll", "Ctrl+A", "在图库中全选图片")
        self.register_default("ThumbnailGrid.Prev", "A", "在缩略图中选择上一张")
        self.register_default("ThumbnailGrid.Next", "D", "在缩略图中选择下一张")
        self.register_default("ThumbnailGrid.Up", "W", "在缩略图中选择上一行")
        self.register_default("ThumbnailGrid.Down", "S", "在缩略图中选择下一行")
        self.register_default("ThumbnailGrid.OpenDetail", "F", "在缩略图中进入大图模式")
        self.register_default("FolderNav.PrevFolder", "W", "文件夹：上一个（按可见顺序，仅文件树）")
        self.register_default("FolderNav.NextFolder", "S", "文件夹：下一个（按可见顺序，仅文件树）")
        self.register_default("FolderNav.PrevSiblingFolder", "Ctrl+W", "文件夹：同级上一个")
        self.register_default("FolderNav.NextSiblingFolder", "Ctrl+S", "文件夹：同级下一个")
        self.register_default("FolderNav.ParentFolder", "Alt+W", "文件夹：上一个上级（不进入根目录）")
        self.register_default("FolderNav.ParentFolder2", "Alt+S", "文件夹：下一个上级")
        self.register_default("FolderTree.ToggleExpand", "Space", "文件树：展开/折叠当前文件夹")
        self.register_default("FolderTree.FocusToGrid", "D", "文件树：切换到缩略图并选中可见首项")
        self.register_default("ThumbnailGrid.FocusToTree", "Alt+A", "缩略图：切换到文件树并定位当前文件夹")
        self.register_default("General.Close", "Esc", "关闭当前窗口或返回")
        
    def register_default(self, shortcut_id, default_sequence, description=""):
        """注册默认快捷键"""
        if shortcut_id not in self.shortcuts:
            self.shortcuts[shortcut_id] = {
                'sequence': default_sequence,
                'default': default_sequence,
                'desc': description
            }

    def load_shortcuts(self):
        """从文件加载快捷键配置"""
        data = None
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                try:
                    LogManager.instance().warning(f"加载快捷键配置失败: {e}")
                except Exception:
                    pass
        elif os.path.exists(self.default_config_path):
            try:
                with open(self.default_config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                pass
        
        if data is None:
            # 如果文件不存在，保存当前默认配置
            self.save_shortcuts()
            return

        if isinstance(data, dict):
            for sid, seq in data.items():
                if sid in self.shortcuts:
                    self.shortcuts[sid]['sequence'] = seq
            changed = False
            try:
                if str(data.get("FolderNav.PrevFolder") or "") in ("Shift+W", "Shift+w") and str(self.shortcuts.get("FolderNav.PrevFolder", {}).get("default")) == "W":
                    self.shortcuts["FolderNav.PrevFolder"]["sequence"] = "W"
                    changed = True
            except Exception:
                pass
            try:
                if str(data.get("FolderNav.NextFolder") or "") in ("Shift+S", "Shift+s") and str(self.shortcuts.get("FolderNav.NextFolder", {}).get("default")) == "S":
                    self.shortcuts["FolderNav.NextFolder"]["sequence"] = "S"
                    changed = True
            except Exception:
                pass
            try:
                if changed:
                    self.save_shortcuts()
            except Exception:
                pass
            try:
                missing = any(sid not in data for sid in self.shortcuts.keys())
            except Exception:
                missing = False
            try:
                sr = self.shortcuts.get("ImageDetail.ToggleSubjectRect", {}).get("sequence")
                fp = self.shortcuts.get("ImageDetail.ToggleFocusPoint", {}).get("sequence")
                if sr and fp and str(sr).strip().lower() == str(fp).strip().lower():
                    if str(sr).strip().lower() == "b":
                        self.shortcuts["ImageDetail.ToggleFocusPoint"]["sequence"] = self.shortcuts["ImageDetail.ToggleFocusPoint"]["default"]
                        missing = True
            except Exception:
                pass
            if missing:
                self.save_shortcuts()

    def save_shortcuts(self):
        """保存快捷键配置到文件"""
        data = {sid: self.shortcuts[sid]['sequence'] for sid in self.shortcuts}
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            try:
                LogManager.instance().warning(f"保存快捷键配置失败: {e}")
            except Exception:
                pass

    def reset_to_defaults(self):
        """重置为默认设置"""
        for sid in self.shortcuts:
            self.shortcuts[sid]['sequence'] = self.shortcuts[sid]['default']
        self.save_shortcuts()
        self.shortcuts_changed.emit()

    def reset_shortcut(self, sid):
        """重置单个快捷键为默认设置"""
        if sid in self.shortcuts:
            self.shortcuts[sid]['sequence'] = self.shortcuts[sid]['default']
            self.save_shortcuts()
            self.shortcuts_changed.emit()

    def get_all_shortcuts(self):
        """获取所有快捷键配置 (用于UI显示)"""
        return self.shortcuts

    def get_sequence(self, shortcut_id):
        """获取指定功能的快捷键序列 (QKeySequence)"""
        if shortcut_id in self.shortcuts:
            seq = self.shortcuts[shortcut_id]['sequence']
            if isinstance(seq, str):
                # 特殊处理鼠标滚轮，虽然 QKeySequence 不支持 Wheel，但我们可以存储字符串用于 UI 显示或手动判断
                if "Wheel" in seq:
                    return seq
                return QKeySequence(seq)
            return seq
        return QKeySequence()

    def get_sequence_str(self, shortcut_id):
        """获取快捷键字符串"""
        if shortcut_id in self.shortcuts:
            seq = self.shortcuts[shortcut_id]['sequence']
            if isinstance(seq, QKeySequence):
                return seq.toString()
            return str(seq)
        return ""

    def set_shortcut(self, shortcut_id, new_sequence):
        """修改快捷键"""
        if shortcut_id in self.shortcuts:
            self.shortcuts[shortcut_id]['sequence'] = new_sequence
            self.save_shortcuts()
            self.shortcuts_changed.emit()
            # TODO: 如果有注册的 QAction，需要同步更新
            # self._update_registered_actions(shortcut_id)

    def is_match(self, shortcut_id, event, key_only=False):
        """
        检查事件是否匹配指定快捷键
        统一处理键盘事件和鼠标滚轮事件
        """
        target = self.get_sequence_str(shortcut_id)
        if not target:
            return False
            
        is_wheel_target = "Wheel" in target
        
        # 1. 处理鼠标滚轮事件
        if hasattr(event, "angleDelta"):
            if not is_wheel_target:
                return False
                
            # Parse target string: "Ctrl+Shift+WheelUp"
            parts = target.split('+')
            
            # Check modifiers
            modifiers = event.modifiers()
            
            # Check Ctrl
            has_ctrl = "Ctrl" in parts or "Control" in parts
            if has_ctrl != bool(modifiers & Qt.KeyboardModifier.ControlModifier):
                return False
                
            # Check Alt
            has_alt = "Alt" in parts
            if has_alt != bool(modifiers & Qt.KeyboardModifier.AltModifier):
                return False
                
            # Check Shift
            has_shift = "Shift" in parts
            if has_shift != bool(modifiers & Qt.KeyboardModifier.ShiftModifier):
                return False
                
            # Check Direction
            delta = event.angleDelta().y()
            if "WheelUp" in parts and delta > 0:
                return True
            if "WheelDown" in parts and delta < 0:
                return True
                
            return False

        # 2. 处理键盘事件
        elif hasattr(event, "key"):
            if is_wheel_target:
                return False
                
            # 获取按下的键
            key = event.key()
            modifiers = event.modifiers()
            
            # 构造当前按下的键序列
            current_seq = QKeySequence(key | modifiers.value)
            target_seq = QKeySequence(target)
            
            return current_seq == target_seq
            
        return False

    # =========================================================================
    # Image Detail Panel Shortcuts (大图详情页)
    # =========================================================================
    
    def check_detail_zoom_in(self, event, callback=None):
        """检查是否触发大图放大"""
        if self.is_match("ImageDetail.ZoomIn", event):
            if callback:
                callback()
            return True
        return False
        
    def check_detail_zoom_out(self, event, callback=None):
        """检查是否触发大图缩小"""
        if self.is_match("ImageDetail.ZoomOut", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_toggle_magnifier(self, event, callback=None):
        """检查是否触发放大镜开关"""
        if self.is_match("ImageDetail.ToggleMagnifier", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_prev_image(self, event, callback=None):
        """检查是否触发上一张"""
        if self.is_match("ImageDetail.PrevImage", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_next_image(self, event, callback=None):
        """检查是否触发下一张"""
        if self.is_match("ImageDetail.NextImage", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_close(self, event, callback=None):
        if self.is_match("ImageDetail.Close", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_toggle_subject_rect(self, event, callback=None):
        if self.is_match("ImageDetail.ToggleSubjectRect", event):
            if callback:
                callback()
            return True
        return False

    def check_thumbnail_prev(self, event, callback=None):
        if self.is_match("ThumbnailGrid.Prev", event):
            if callback:
                callback()
            return True
        return False

    def check_thumbnail_next(self, event, callback=None):
        if self.is_match("ThumbnailGrid.Next", event):
            if callback:
                callback()
            return True
        return False

    def check_thumbnail_up(self, event, callback=None):
        if self.is_match("ThumbnailGrid.Up", event):
            if callback:
                callback()
            return True
        return False

    def check_thumbnail_down(self, event, callback=None):
        if self.is_match("ThumbnailGrid.Down", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_rotate(self, event, callback=None):
        """检查是否触发旋转"""
        if self.is_match("ImageDetail.Rotate", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_detect_subject(self, event, callback=None):
        """检查是否触发主体检测"""
        if self.is_match("ImageDetail.DetectSubject", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_zoom_to_bird(self, event, callback=None):
        """检查是否触发聚焦主体"""
        if self.is_match("ImageDetail.ZoomToBird", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_toggle_focus_point(self, event, callback=None):
        """检查是否触发显示/隐藏对焦点"""
        if self.is_match("ImageDetail.ToggleFocusPoint", event):
            if callback:
                callback()
            return True
        return False

    def check_detail_toggle_compare_mode(self, event, callback=None):
        """检查是否触发切换对比模式"""
        if self.is_match("ImageDetail.ToggleCompareMode", event):
            if callback:
                callback()
            return True
        return False

    # =========================================================================
    # Image Library Shortcuts (图库页面)
    # =========================================================================
    
    def check_library_zoom_in(self, event, callback=None):
        """检查是否触发图库缩略图放大"""
        if self.is_match("ImageLibrary.ZoomIn", event):
            if callback:
                callback()
            return True
        return False

    def check_library_zoom_out(self, event, callback=None):
        """检查是否触发图库缩略图缩小"""
        if self.is_match("ImageLibrary.ZoomOut", event):
            if callback:
                callback()
            return True
        return False

    # =========================================================================
    # General Shortcuts (通用)
    # =========================================================================
    
    def check_general_close(self, event, callback=None):
        """检查是否触发关闭/返回"""
        if self.is_match("General.Close", event):
            if callback:
                callback()
            return True
        return False
