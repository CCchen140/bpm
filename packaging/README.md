## Windows Installer（安装包）制作

推荐工具：Inno Setup（免费、上手简单，适合把 PyInstaller 的 dist 目录封装成一个 .exe 安装程序）。

### 1. 先生成 PyInstaller 的发布目录

在项目根目录执行：

```powershell
python build\build.py
```

生成后会得到类似目录：

- `dist\栖图_V0.0.1\`（里面包含 exe、dll、数据文件等）

### 2. 安装 Inno Setup

安装后打开 Inno Setup Compiler。

### 3. 生成安装包

1. 在 Inno Setup Compiler 中打开同目录下的 `inno_setup.iss`
2. 按需修改脚本顶部的 4 个变量：
   - `MyAppName`
   - `MyAppVersion`
   - `MyAppDistDir`（指向你当前 dist 产物目录）
   - `MyAppExeName`（dist 目录内的主程序 exe 名）
3. 点击菜单 `Build -> Compile`
4. 输出安装包默认在 `packaging\output\` 下（脚本已配置）

### 4. 常见注意事项

- dist 目录里应包含所有依赖文件；安装包只是“把 dist 原样拷贝到 {app} 并创建快捷方式”
- 如果你的 exe 名或 dist 目录名带了 suffix（例如 `_r3`），记得同步修改脚本变量
