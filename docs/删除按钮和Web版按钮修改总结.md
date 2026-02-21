# 删除按钮和Web版按钮修改总结

## 修改日期
2024年（根据系统时间）

## 修改内容

### 1. Web版图库按钮 - 仅在数据图表debug模式下显示

**文件**: `ui/main_window.py`

**修改位置**: 
- 第265行左右：Web版按钮初始化时默认隐藏
- 第1050行左右：数据图表debug模式切换处理

**实现逻辑**:
```python
# 初始化时隐藏
self.btn_library_web.hide()

# 在数据图表debug模式切换时控制显示/隐藏
if enabled:
    self.btn_library_web.show()
else:
    self.btn_library_web.hide()
```

**使用方法**:
1. 右键点击"数据图表"按钮6次
2. 开启debug模式后，Web版按钮会显示在侧边栏
3. 关闭debug模式后，Web版按钮会自动隐藏

---

### 2. 大图模式删除按钮 - 双击缩略图后的全屏查看模式

**文件**: `ui/panels/image_detail_panel.py`

#### 2.1 工具栏添加删除按钮

**修改位置**: 第3895-3920行左右（`init_toolbar`方法）

**实现代码**:
```python
# 删除按钮（放在"显示对焦点"按钮后面）
self.btn_delete = QPushButton()
self.btn_delete.setIcon(qta.icon('mdi6.trash-can-outline', color='#e74c3c'))
self.btn_delete.setIconSize(QSize(24, 24))
self.btn_delete.setFixedSize(36, 36)
self.btn_delete.setToolTip("删除 (Ctrl+D)")
self.btn_delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
self.btn_delete.setStyleSheet(f"""
    QPushButton {{ background-color: transparent; border: none; border-radius: 4px; }}
    QPushButton:hover {{ background-color: #ffcccc; }}
    QPushButton:pressed {{ background-color: #ff9999; }}
    QToolTip {{ color: {tooltip_text}; background-color: {tooltip_bg}; border: 1px solid {tooltip_border}; }}
""")
self.btn_delete.clicked.connect(self._on_delete_clicked)
layout.addWidget(self.btn_delete)
```

**按钮特点**:
- 红色垃圾桶图标（`mdi6.trash-can-outline`）
- 悬停时显示浅红色背景（`#ffcccc`）
- 按下时显示深红色背景（`#ff9999`）
- 提示文字显示"删除 (Ctrl+D)"

#### 2.2 添加Ctrl+D快捷键

**修改位置**: 第1060-1070行左右（`__init__`方法中的快捷键初始化）

**实现代码**:
```python
try:
    if not hasattr(self, "_detail_delete_shortcut") or self._detail_delete_shortcut is None:
        self._detail_delete_shortcut = QShortcut("Ctrl+D", self)
        self._detail_delete_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._detail_delete_shortcut.activated.connect(self._on_delete_clicked)
except Exception:
    self._detail_delete_shortcut = None
```

#### 2.3 删除处理方法

**修改位置**: 第1813行后（`_on_stash_clicked`方法后）

**功能实现**:
1. 获取当前图片路径
2. 弹出确认对话框
3. 尝试将文件移到回收站：
   - 优先使用`send2trash`库（如果已安装）
   - 否则使用Windows Shell API (`SHFileOperationW`)
   - 最后使用`os.remove()`直接删除
4. 从数据库中删除记录
5. 从图片列表中移除
6. 如果列表为空，关闭详情面板
7. 否则加载下一张图片
8. 显示删除成功提示

**安全特性**:
- 删除前需要用户确认
- 优先移到回收站（可恢复）
- 即使没有安装`send2trash`也能正常工作
- 删除失败时显示错误提示
- 自动处理列表为空的情况

---

## 使用说明

### Web版按钮
1. 默认情况下，Web版按钮是隐藏的
2. 需要开启数据图表debug模式才能看到
3. 开启方法：右键点击"数据图表"按钮6次

### 删除按钮
1. 双击任意缩略图进入大图模式
2. 在底部工具栏找到红色垃圾桶图标（位于"显示对焦点"按钮右侧）
3. 点击删除按钮或按`Ctrl+D`快捷键
4. 确认删除后，图片会被移到回收站
5. 自动显示下一张图片

---

## 技术细节

### 依赖库
- `send2trash`: 可选，用于将文件移到回收站（如果未安装会使用Windows API）
- `qtawesome`: 用于图标显示
- `PyQt6`: UI框架

### 删除文件的实现
程序会按以下顺序尝试删除文件：
1. 首先尝试使用`send2trash`库（如果已安装）
2. 如果`send2trash`未安装，使用Windows Shell API (`SHFileOperationW`)
3. 如果Windows API失败，使用`os.remove()`直接删除

这样确保即使没有安装`send2trash`，删除功能也能正常工作。

### 数据库操作
- 使用`BirdLibraryDB.delete_image_by_path()`方法删除记录
- 支持`bird_results`和`import_cache`两个表

### 快捷键上下文
- 使用`Qt.ShortcutContext.WidgetWithChildrenShortcut`
- 确保快捷键只在大图模式下生效
- 不会与其他页面的快捷键冲突

---

## 注意事项

1. **删除操作会将文件移到回收站**（可以从回收站恢复）
2. **删除前会弹出确认对话框**，避免误操作
3. **Web版按钮默认隐藏**，避免普通用户误点
4. **删除按钮使用红色主题**，提醒用户这是危险操作
5. **快捷键Ctrl+D**与浏览器书签快捷键相同，但只在大图模式下生效
6. **不需要安装send2trash**，程序会自动使用Windows API作为备选方案

---

## 已知问题修复

### 问题1：对缩略图右键程序崩溃
**原因**: 删除功能中直接导入`send2trash`模块，但该模块未安装导致ImportError

**修复方案**: 
- 将`send2trash`改为可选依赖
- 如果未安装，自动使用Windows Shell API (`SHFileOperationW`)
- 确保删除功能在任何情况下都能正常工作

### 问题2：右键菜单导致程序崩溃
**原因**: 右键菜单处理过程中可能出现未捕获的异常导致程序崩溃

**修复方案**:
- 在 `ui/image_library_page.py` 的 `on_thumbnail_context_menu` 方法中添加完整的异常处理
- 在 `ui/widgets/image_thumbnail.py` 的 `contextMenuEvent` 方法中添加异常处理
- 在 `ui/library/views/virtual_thumbnail_grid_view.py` 的 `_on_context_menu_requested` 方法中添加异常处理
- 所有异常都会被记录到日志文件中，方便调试
- 程序不会因为右键菜单错误而崩溃，提升稳定性

---

## 测试建议

1. 测试删除单张图片
2. 测试删除最后一张图片（应自动关闭详情面板）
3. 测试Ctrl+D快捷键
4. 测试删除失败的情况（如文件被占用）
5. 测试从回收站恢复删除的图片
6. 测试Web版按钮的显示/隐藏逻辑

