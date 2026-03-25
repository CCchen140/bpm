# Windows 系统通知实现行动文档

## 1. 目标

在应用最小化或在后台运行时，通过 **Windows 系统通知**（右下角弹出的 Toast 通知）提醒用户关键事件，例如：

- 对焦检测已完成
- 图片导入完成
- 轨迹匹配完成
- 后台任务出错

与现有的应用内 Toast（`NotificationManager.show_toast`）互补：应用在前台时用应用内 Toast，在后台/最小化时用系统通知。

---

## 2. 现有架构分析

| 组件 | 说明 |
|---|---|
| `ui/utils/notification_manager.py` | 应用内 Toast 通知（`ToastWidget`），仅在窗口可见时有效 |
| `ui/utils/app_icon.py` | 动态生成应用图标（`get_app_icon`），优先使用 `ph.bird-fill` |
| `QSystemTrayIcon` | **当前未使用** |
| 第三方 Windows 通知库 | **当前未引入** |

**核心问题**：当前 `ToastWidget` 依赖父窗口可见，应用在后台时用户看不到任何通知。

---

## 3. 方案对比

### 方案 A：QSystemTrayIcon（推荐）

PyQt6 内置的系统托盘图标，自带 `showMessage()` 方法。

```python
from PyQt6.QtWidgets import QSystemTrayIcon
from PyQt6.QtGui import QIcon

tray = QSystemTrayIcon(icon, parent)
tray.show()
tray.showMessage("标题", "内容", QSystemTrayIcon.MessageIcon.Information, 5000)
```

| 优点 | 缺点 |
|---|---|
| 零额外依赖，PyQt6 原生支持 | Windows 10+ 显示为 Action Center 通知，外观由系统控制 |
| 跨平台（Linux/macOS 也可用） | 不支持自定义按钮/操作 |
| 与 Qt 事件循环天然集成 | 不支持自定义音效 |
| 可附带系统托盘菜单 | 图标必须是系统托盘图标的图标 |
| `messageClicked` 信号可响应点击 | |

### 方案 B：winotify

纯 Python 库，调用 Windows 原生 Toast API。

```python
from winotify import Notification
toast = Notification(app_id="栖图", title="对焦检测", msg="检测已完成")
toast.set_audio(winotify.audio.Default, loop=False)
toast.show()
```

| 优点 | 缺点 |
|---|---|
| 现代 Windows 10/11 Toast 外观 | 仅支持 Windows |
| 支持自定义按钮和动作链接 | 需要额外安装（`pip install winotify`） |
| 支持自定义图片/图标 | 通知回调需要启动 HTTP 服务或协议注册 |
| 支持自定义音效 | 与 Qt 事件循环无直接集成 |
| 轻量，无 C 扩展依赖 | |

### 方案 C：windows-toasts

基于 WinRT API 的完整 Toast 通知库。

```python
from windows_toasts import Toast, WindowsToaster
toaster = WindowsToaster("栖图")
toast = Toast()
toast.text_fields = ["对焦检测已完成"]
toaster.show_toast(toast)
```

| 优点 | 缺点 |
|---|---|
| 功能最全（进度条、按钮、输入框） | 依赖 `winsdk`，安装体积较大 |
| 原生 WinRT 调用，最「正宗」 | 仅 Windows 10 1903+ |
| 支持 Toast 内交互回调 | 打包时需包含额外 DLL |

### 推荐：方案 A（QSystemTrayIcon）

理由：
1. **零额外依赖**——不增加打包体积，不引入新的故障点
2. **跨平台兼容**——将来若需支持 macOS/Linux 无需改动
3. **与 Qt 信号槽天然集成**——通知点击可直接触发窗口恢复/跳转
4. **附带系统托盘功能**——最小化到托盘、右键菜单等一并解决
5. **在 Windows 10/11 上已经是现代 Toast 样式**

如果后续需要按钮交互（如「查看结果」按钮），可补充引入 `winotify` 作为增强。

---

## 4. 实现方案（基于方案 A）

### 4.1 架构设计

```
NotificationManager (单例，已有)
├── show_toast()          ← 应用内 Toast（已有）
├── show_system_notify()  ← 新增：系统通知
├── smart_notify()        ← 新增：智能选择（前台→内部Toast，后台→系统通知）
│
└── SystemTrayManager (新增，单例)
    ├── QSystemTrayIcon
    ├── 托盘右键菜单
    ├── 双击托盘图标 → 恢复窗口
    └── showMessage() → 系统通知
```

### 4.2 新增文件

#### `ui/utils/system_tray_manager.py`

```python
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QObject

class SystemTrayManager(QObject):
    _instance = None

    def __init__(self):
        super().__init__()
        self._tray_icon: QSystemTrayIcon | None = None
        self._main_window = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = SystemTrayManager()
        return cls._instance

    def initialize(self, main_window, icon: QIcon):
        """初始化系统托盘图标，在 MainWindow 创建后调用一次"""
        self._main_window = main_window

        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self._tray_icon = QSystemTrayIcon(icon, main_window)

        # 右键菜单
        menu = QMenu()
        action_show = QAction("显示主窗口", menu)
        action_show.triggered.connect(self._restore_window)
        menu.addAction(action_show)

        menu.addSeparator()

        action_quit = QAction("退出", menu)
        action_quit.triggered.connect(self._quit_app)
        menu.addAction(action_quit)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.setToolTip("栖图")

        # 双击托盘图标 → 恢复窗口
        self._tray_icon.activated.connect(self._on_activated)

        # 通知点击 → 恢复窗口
        self._tray_icon.messageClicked.connect(self._restore_window)

        self._tray_icon.show()

    def show_notification(self, title: str, message: str,
                          icon_type: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
                          duration_ms: int = 5000):
        """发送系统通知"""
        if self._tray_icon and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, icon_type, duration_ms)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_window()

    def _restore_window(self):
        if self._main_window:
            self._main_window.showNormal()
            self._main_window.activateWindow()
            self._main_window.raise_()

    def _quit_app(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def set_icon(self, icon: QIcon):
        """主题切换时更新托盘图标"""
        if self._tray_icon:
            self._tray_icon.setIcon(icon)
```

### 4.3 修改 NotificationManager

在现有 `notification_manager.py` 中新增两个方法：

```python
def show_system_notify(self, title: str, message: str, icon_type=None):
    """发送 Windows 系统通知（右下角 Toast）"""
    from ui.utils.system_tray_manager import SystemTrayManager
    from PyQt6.QtWidgets import QSystemTrayIcon
    if icon_type is None:
        icon_type = QSystemTrayIcon.MessageIcon.Information
    SystemTrayManager.instance().show_notification(title, message, icon_type)

def smart_notify(self, title: str, message: str, duration=2000,
                 position: str = "bottom"):
    """
    智能通知：
    - 窗口在前台且可见 → 应用内 Toast
    - 窗口在后台或最小化 → 系统通知
    """
    if self.parent_widget and self.parent_widget.isActiveWindow():
        self.show_toast(f"{title}: {message}" if title else message,
                        duration=duration, position=position)
    else:
        self.show_system_notify(title, message)
```

### 4.4 初始化时机

在 `main.py` 中，`MainWindow` 创建完成后初始化托盘：

```python
# main.py 中 window 创建之后
from ui.utils.system_tray_manager import SystemTrayManager
SystemTrayManager.instance().initialize(window, app_icon)
```

### 4.5 主题切换同步

在 `MainWindow._apply_theme()` 中更新托盘图标：

```python
def _apply_theme(self):
    # ... 现有逻辑 ...
    try:
        from ui.utils.system_tray_manager import SystemTrayManager
        icon_color = cm.get("theme.primary", "#2196F3")
        tray_icon = get_app_icon(icon_color)
        SystemTrayManager.instance().set_icon(tray_icon)
    except Exception:
        pass
```

---

## 5. 调用示例

### 5.1 后台任务完成时

```python
# 在对焦检测完成的回调中
from ui.utils.notification_manager import NotificationManager

NotificationManager.instance().smart_notify(
    "对焦检测完成",
    f"已完成 {count} 张图片的对焦检测"
)
```

### 5.2 导入完成时

```python
NotificationManager.instance().smart_notify(
    "导入完成",
    f"成功导入 {success_count} 张图片，失败 {fail_count} 张"
)
```

### 5.3 强制系统通知（无论前后台）

```python
NotificationManager.instance().show_system_notify(
    "后台任务",
    "轨迹匹配已完成，共匹配 200 张照片"
)
```

---

## 6. 可选增强

### 6.1 最小化到托盘（而非任务栏）

重写 `MainWindow.closeEvent` 或 `changeEvent`：

```python
def changeEvent(self, event):
    if event.type() == QEvent.Type.WindowStateChange:
        if self.isMinimized():
            # 可选：最小化时隐藏任务栏图标，仅保留托盘
            # self.hide()
            # SystemTrayManager.instance().show_notification(
            #     "栖图", "程序已最小化到系统托盘"
            # )
            pass
    super().changeEvent(event)
```

### 6.2 通知频率限制

避免短时间内发送大量系统通知（如批量处理每张都通知）：

```python
import time

class SystemTrayManager:
    def __init__(self):
        # ...
        self._last_notify_time = 0
        self._min_interval = 3.0  # 最少间隔3秒

    def show_notification(self, title, message, icon_type=..., duration_ms=5000):
        now = time.monotonic()
        if now - self._last_notify_time < self._min_interval:
            return  # 跳过过于频繁的通知
        self._last_notify_time = now
        if self._tray_icon and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, icon_type, duration_ms)
```

### 6.3 通知声音控制

在设置中添加开关：

```python
# settings_manager 中添加
"notification/system_notify_enabled": True    # 是否启用系统通知
"notification/system_notify_sound": True      # 是否播放声音（系统控制）
```

### 6.4 升级到 winotify（若需要按钮交互）

如果后续需要在通知中添加「查看结果」「打开文件夹」等交互按钮：

```bash
pip install winotify
```

```python
from winotify import Notification, audio

def show_rich_notification(self, title, message, icon_path=None):
    toast = Notification(
        app_id="栖图",
        title=title,
        msg=message,
        icon=icon_path or "",
        duration="short"
    )
    toast.set_audio(audio.Default, loop=False)
    toast.add_actions(label="查看结果", launch="app://show_results")
    toast.show()
```

---

## 7. 实施步骤

| 步骤 | 内容 | 预估工作量 |
|---|---|---|
| 1 | 新建 `ui/utils/system_tray_manager.py` | 0.5h |
| 2 | 在 `NotificationManager` 中添加 `show_system_notify` 和 `smart_notify` | 0.5h |
| 3 | `main.py` 中初始化 `SystemTrayManager` | 10min |
| 4 | `MainWindow._apply_theme` 中同步更新托盘图标 | 10min |
| 5 | 在对焦检测、导入等后台任务完成处调用 `smart_notify` | 0.5h |
| 6 | 设置页面添加「系统通知开关」 | 0.5h（可选） |
| 7 | 测试各场景（前台/后台/最小化/多屏） | 0.5h |

**总计约 2-3 小时**（含测试）。

---

## 8. 注意事项

1. **`QSystemTrayIcon.isSystemTrayAvailable()`**：少数极简 Linux 桌面可能不支持，需要做容错
2. **打包后图标**：确保 `.ico` 文件被正确包含到打包产物中；若图标为动态生成的 `QIcon`，`QSystemTrayIcon` 可直接使用
3. **Windows 通知中心设置**：用户可能在 Windows 设置中关闭了该应用的通知权限，此为系统行为，无法绕过
4. **多次 `showMessage`**：如果上一条通知尚未消失就发新通知，系统会将旧通知折叠到通知中心
5. **`messageClicked` 信号**：仅在用户主动点击通知时触发，通知自动消失不触发
6. **退出时清理**：`QSystemTrayIcon` 随 `QApplication` 结束自动清理，一般无需手动处理


