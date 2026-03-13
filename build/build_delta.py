#!/usr/bin/env python3
"""
BirdPictureManager 增量升级包打包脚本

使用方法:
    python build/build_delta.py --from "dist/栖图_V0.0.4_o1" --to "dist/栖图_V0.0.4_gpu" --version "0.0.4" --flavor gpu --update 1

参数:
    --from: 旧版本 dist 目录路径
    --to: 新版本 dist 目录路径（默认为最新版本）
    --version: 升级包版本号
    --flavor: cpu/gpu，自动从目录名检测
    --update: update 编号，默认 1
"""

import argparse
import os
import sys
import shutil
import hashlib
import re
from datetime import datetime


def _walk_dist_files(root_dir: str) -> dict[str, tuple[str, int, int]]:
    """遍历目录，返回文件信息字典"""
    root_dir = os.path.abspath(str(root_dir or ""))
    out: dict[str, tuple[str, int, int]] = {}
    if not root_dir or not os.path.isdir(root_dir):
        return out
    
    for base, dirs, files in os.walk(root_dir):
        try:
            rel_base = os.path.relpath(base, root_dir)
        except Exception:
            rel_base = "."
        if rel_base == ".":
            rel_base = ""
        try:
            parts = [p for p in rel_base.replace("\\", "/").split("/") if p]
        except Exception:
            parts = []
        if parts:
            top = str(parts[0] or "").lower()
            if top in ("data", "cache"):
                try:
                    dirs[:] = []
                except Exception:
                    pass
                continue
        
        for name in files:
            if not name:
                continue
            if str(name).lower() in ("thumbs.db", "desktop.ini"):
                continue
            
            abs_path = os.path.join(base, name)
            try:
                st = os.stat(abs_path)
                size = int(st.st_size)
                mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            except Exception:
                continue
            
            try:
                rel_path = os.path.relpath(abs_path, root_dir).replace("/", "\\")
            except Exception:
                rel_path = name
            
            out[rel_path] = (abs_path, size, mtime_ns)
    
    return out


def _detect_flavor_from_dir_name(dir_name: str) -> str:
    name = str(dir_name or "").strip().lower()
    if "_gpu" in name:
        return "gpu"
    if "_cpu" in name:
        return "cpu"
    return ""


def _extract_version_from_dist_name(dir_name: str) -> str:
    m = re.match(r"^栖图_V([^_]+)", str(dir_name or ""))
    if not m:
        return ""
    return str(m.group(1) or "").strip()


def _version_sort_key(version: str):
    parts = re.findall(r"\d+|[A-Za-z]+", str(version or ""))
    key = []
    for p in parts:
        if str(p).isdigit():
            key.append((0, int(p)))
        else:
            key.append((1, str(p).lower()))
    return tuple(key)


def _select_latest_dist_dir(dist_root: str, preferred_flavor: str = "") -> str:
    candidates: list[tuple[tuple, str]] = []
    preferred_flavor = str(preferred_flavor or "").strip().lower()
    for name in os.listdir(dist_root):
        full = os.path.join(dist_root, name)
        if not os.path.isdir(full):
            continue
        if not str(name).startswith("栖图_V"):
            continue
        if "_update" in str(name).lower():
            continue
        version = _extract_version_from_dist_name(name)
        if not version:
            continue
        flavor = _detect_flavor_from_dir_name(name)
        if preferred_flavor and flavor and flavor != preferred_flavor:
            continue
        candidates.append((_version_sort_key(version), name))
    if not candidates and preferred_flavor:
        for name in os.listdir(dist_root):
            full = os.path.join(dist_root, name)
            if not os.path.isdir(full):
                continue
            if not str(name).startswith("栖图_V"):
                continue
            if "_update" in str(name).lower():
                continue
            version = _extract_version_from_dist_name(name)
            if not version:
                continue
            candidates.append((_version_sort_key(version), name))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return os.path.join(dist_root, candidates[0][1])


def _hash_file(path: str, max_bytes: int = 64 * 1024 * 1024) -> str:
    """计算文件 SHA1 哈希"""
    try:
        st = os.stat(path)
        if int(st.st_size) > int(max_bytes):
            return ""
    except Exception:
        return ""
    
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def compute_delta_files(old_dist_dir: str, new_dist_dir: str) -> dict[str, list[str]]:
    """计算两个版本之间的差异文件"""
    old_map = _walk_dist_files(old_dist_dir)
    new_map = _walk_dist_files(new_dist_dir)
    
    # 创建小写映射用于大小写不敏感比较
    old_map_lower = {k.lower(): k for k in old_map.keys()}
    new_map_lower = {k.lower(): k for k in new_map.keys()}
    
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []  # (旧名称, 新名称)
    
    # 检查新增和修改的文件
    for rel, (new_abs, new_size, new_mtime) in new_map.items():
        rel_lower = rel.lower()
        old_key = old_map_lower.get(rel_lower)
        
        if old_key is None:
            # 检查是否有大小写不同的同名文件
            added.append(rel)
            continue
        
        # 如果文件名大小写不同，记录为重命名
        if old_key != rel:
            renamed.append((old_key, rel))
            continue
        
        old = old_map.get(old_key)
        _, old_size, old_mtime = old
        if int(old_size) != int(new_size):
            modified.append(rel)
            continue
        
        if int(old_mtime) == int(new_mtime):
            continue
        
        old_hash = _hash_file(old[0])
        new_hash = _hash_file(new_abs)
        if old_hash and new_hash:
            if old_hash != new_hash:
                modified.append(rel)
            continue
        
        modified.append(rel)
    
    # 检查删除的文件（排除已重命名的）
    renamed_old_keys = set(r[0] for r in renamed)
    for rel in old_map.keys():
        rel_lower = rel.lower()
        if rel_lower not in new_map_lower and rel not in renamed_old_keys:
            deleted.append(rel)
    
    added.sort()
    modified.sort()
    deleted.sort()
    renamed.sort()
    
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "renamed": renamed
    }


def create_delta_package(
    old_dist_dir: str,
    new_dist_dir: str,
    output_dir: str,
    delta_files: dict,
    app_flavor: str = ""
) -> dict:
    """创建差分升级包文件夹"""
    
    # 清空并创建输出目录
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir, exist_ok=True)
    
    # 创建 build_flavor.txt 标记文件
    try:
        flavor = str(app_flavor or "").strip().lower()
        if flavor not in ("cpu", "gpu"):
            flavor = "cpu"
        marker_path = os.path.join(output_dir, "build_flavor.txt")
        with open(marker_path, "w", encoding="utf-8") as f:
            f.write(flavor)
    except Exception:
        pass
    
    copied_files = []
    deleted_files = list(delta_files.get("deleted", []) or [])
    renamed_files = list(delta_files.get("renamed", []) or [])
    
    # 复制新增和修改的文件
    for category in ["added", "modified"]:
        for rel_path in delta_files.get(category, []):
            src_path = os.path.join(new_dist_dir, rel_path)
            dst_path = os.path.join(output_dir, rel_path)
            
            if not os.path.exists(src_path):
                print(f"  警告: 源文件不存在: {rel_path}")
                continue
            
            # 创建目标目录
            dst_dir = os.path.dirname(dst_path)
            os.makedirs(dst_dir, exist_ok=True)
            
            # 复制文件
            shutil.copy2(src_path, dst_path)
            copied_files.append(rel_path)
            print(f"  [{category.upper()}] {rel_path}")
    
    # 处理重命名的文件（大小写变化）
    for old_name, new_name in renamed_files:
        src_path = os.path.join(new_dist_dir, new_name)
        dst_path = os.path.join(output_dir, new_name)
        
        if not os.path.exists(src_path):
            print(f"  警告: 源文件不存在: {new_name}")
            continue
        
        # 创建目标目录
        dst_dir = os.path.dirname(dst_path)
        os.makedirs(dst_dir, exist_ok=True)
        
        # 复制新文件
        shutil.copy2(src_path, dst_path)
        copied_files.append(new_name)
        # 将旧文件名添加到删除列表
        deleted_files.append(old_name)
        print(f"  [RENAMED] {old_name} -> {new_name}")
    
    # 创建删除文件列表
    if deleted_files:
        delete_list_path = os.path.join(output_dir, "_delete_files.txt")
        with open(delete_list_path, "w", encoding="utf-8") as f:
            f.write("# 以下文件需要在新版本中删除\n")
            f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for rel_path in deleted_files:
                f.write(f"{rel_path}\n")
                print(f"  [DELETE] {rel_path}")
    
    return {
        "copied": copied_files,
        "deleted": deleted_files,
        "output_dir": output_dir
    }


def write_iss_script(
    iss_output_path: str,
    dist_dir: str,
    app_version: str,
    app_flavor: str,
    update_num: str,
    deleted_files: list = None
):
    """生成简化的 iss 安装脚本，只打包实际存在的文件"""
    
    # 在 Pascal 字符串中，反斜杠需要转义为双反斜杠
    abs_dist_dir = os.path.abspath(dist_dir).replace('\\', '\\\\')
    flavor_suffix = f"_{app_flavor}" if app_flavor else ""
    iss_output_dir = os.path.dirname(os.path.abspath(iss_output_path))
    try:
        os.makedirs(iss_output_dir, exist_ok=True)
    except Exception:
        pass
    icon_line = ""
    try:
        build_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
        icon_candidates = [
            os.path.join(build_root, "ph.bird-fill.ico"),
            os.path.join(os.path.dirname(build_root), "assets", "icons", "bpm_512.ico"),
        ]
        for icon_path in icon_candidates:
            if not os.path.isfile(icon_path):
                continue
            rel_icon = os.path.relpath(icon_path, iss_output_dir).replace("\\", "\\\\")
            icon_line = f"SetupIconFile={rel_icon}"
            break
    except Exception:
        icon_line = ""
    
    # 生成 [Files] 段，只包含实际存在的文件
    files_section = []
    for root, dirs, files in os.walk(dist_dir):
        # 跳过特殊文件
        files = [f for f in files if not f.startswith('_')]
        
        for filename in files:
            src_path = os.path.join(root, filename)
            rel_path = os.path.relpath(src_path, dist_dir).replace('/', '\\')
            
            # 计算目标目录
            rel_dir = os.path.dirname(rel_path)
            if rel_dir:
                dest_dir = "{app}\\" + rel_dir.replace('\\', '\\\\')
            else:
                dest_dir = "{app}"
            
            # 转义反斜杠用于 ISS
            rel_path_escaped = rel_path.replace('\\', '\\\\')
            
            files_section.append('Source: "{#MyAppDistDir}\\' + rel_path_escaped + '"; DestDir: "' + dest_dir + '"; Flags: ignoreversion')
    
    files_content = '\n'.join(files_section) if files_section else '; 没有需要打包的文件'
    
    # 生成完整的 ISS 内容 - 使用字符串拼接避免转义问题
    lines = []
    lines.append('; 增量升级包安装脚本')
    lines.append('; 由 build_delta.py 自动生成')
    lines.append('')
    lines.append('#define MyAppName "栖图"')
    lines.append('#define MyAppVersion "' + app_version + '"')
    lines.append('#define MyAppPublisher "cCc"')
    lines.append('#define MyAppExeName "栖图.exe"')
    lines.append('#define MyAppId "74F28464-C26A-47D9-AE73-22E79631B472"')
    lines.append('#define MyAppFlavor "' + app_flavor + '"')
    lines.append('#define MyAppUpdate "' + update_num + '"')
    lines.append('#define MyAppDistDir "' + abs_dist_dir + '"')
    lines.append('')
    lines.append('[Setup]')
    lines.append('AppId={#MyAppId}')
    lines.append('AppName={#MyAppName} Upgrade Pack')
    lines.append('AppVersion={#MyAppVersion}')
    lines.append('AppPublisher={#MyAppPublisher}')
    lines.append('DefaultDirName={autopf}\\\\{#MyAppName}')
    lines.append('UninstallDisplayIcon={app}\\\\{#MyAppExeName}')
    lines.append('ArchitecturesAllowed=x64compatible')
    lines.append('ArchitecturesInstallIn64BitMode=x64compatible')
    lines.append('DisableProgramGroupPage=yes')
    lines.append('OutputDir={#SourcePath}')
    lines.append('OutputBaseFilename={#MyAppName}_V{#MyAppVersion}' + flavor_suffix + '_update{#MyAppUpdate}')
    if icon_line:
        lines.append(icon_line)
    lines.append('SolidCompression=yes')
    lines.append('Compression=lzma2/ultra64')
    lines.append('InternalCompressLevel=ultra64')
    lines.append('CompressionThreads=auto')
    lines.append('WizardStyle=modern')
    lines.append('; 使用之前安装的目录')
    lines.append('UsePreviousAppDir=yes')
    lines.append('; 完全禁用目录选择页面（使用已安装的路径）')
    lines.append('DisableDirPage=yes')
    lines.append('')
    lines.append('[Languages]')
    lines.append('Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"')
    lines.append('')
    lines.append('[Messages]')
    lines.append('; 自定义消息，以升级为前提')
    lines.append('SetupAppTitle=升级 {#MyAppName}')
    lines.append('SetupWindowTitle=升级 {#MyAppName} - V{#MyAppVersion}')
    lines.append('SelectDirDesc=选择之前安装 {#MyAppName} 的文件夹进行升级。')
    lines.append('SelectDirLabel3=安装程序将升级 {#MyAppName} 到以下文件夹。')
    lines.append('SelectDirBrowseLabel=要继续，请单击"下一步"。如果您想选择其他文件夹，请单击"浏览"。')
    lines.append('InstallingLabel=正在升级 {#MyAppName}，请稍候...')
    lines.append('FinishedLabel=已完成 {#MyAppName} 的升级。')
    lines.append('FinishedHeadingLabel=升级完成')
    lines.append('FinishedLabelNoIcons=已完成 {#MyAppName} 的升级。')
    lines.append('')
    lines.append('[Code]')
    lines.append('var')
    lines.append('  IsUpgrade: Boolean;')
    lines.append('  InstalledPath: String;')
    lines.append('  UpgradeConfirmed: Boolean;')
    lines.append('')
    lines.append('function GetInstalledPath(): String;')
    lines.append('var')
    lines.append('  Path: String;')
    lines.append('  UninstallStr: String;')
    lines.append('begin')
    lines.append('  Path := \'\';')
    lines.append('  UninstallStr := \'\';')
    lines.append('  ')
    lines.append('  // 首先尝试从 InstallLocation 读取')
    lines.append('  RegQueryStringValue(HKLM, \'SOFTWARE\\\\\\\\Microsoft\\\\\\\\Windows\\\\\\\\CurrentVersion\\\\\\\\Uninstall\\\\\\\\{#MyAppId}_is1\', \'InstallLocation\', Path);')
    lines.append('  if (Path = \'\') then')
    lines.append('    RegQueryStringValue(HKLM, \'SOFTWARE\\\\\\\\Microsoft\\\\\\\\Windows\\\\\\\\CurrentVersion\\\\\\\\Uninstall\\\\\\\\{#MyAppId}_is1\', \'Inno Setup: App Path\', Path);')
    lines.append('  ')
    lines.append('  // 如果还是没有，尝试从 UninstallString 提取路径')
    lines.append('  if (Path = \'\') then')
    lines.append('  begin')
    lines.append('    RegQueryStringValue(HKLM, \'SOFTWARE\\\\\\\\Microsoft\\\\\\\\Windows\\\\\\\\CurrentVersion\\\\\\\\Uninstall\\\\\\\\{#MyAppId}_is1\', \'UninstallString\', UninstallStr);')
    lines.append('    if (UninstallStr <> \'\') then')
    lines.append('    begin')
    lines.append('      // UninstallString 格式通常是 "D:\\path\\uninstall.exe" 或 "D:\\path\\uninstall.exe" /x')
    lines.append('      // 提取路径部分')
    lines.append('      Path := ExtractFilePath(UninstallStr);')
    lines.append('      if (Path <> \'\') then')
    lines.append('        Path := RemoveBackslashUnlessRoot(Path);')
    lines.append('    end;')
    lines.append('  end;')
    lines.append('  ')
    lines.append('  Result := Path;')
    lines.append('end;')
    lines.append('')
    lines.append('function InitializeSetup(): Boolean;')
    lines.append('var')
    lines.append('  Msg: String;')
    lines.append('begin')
    lines.append('  // 检查是否已安装')
    lines.append('  if not RegKeyExists(HKLM, \'SOFTWARE\\\\\\\\Microsoft\\\\\\\\Windows\\\\\\\\CurrentVersion\\\\\\\\Uninstall\\\\\\\\{#MyAppId}_is1\') then')
    lines.append('  begin')
    lines.append('    MsgBox(\'未检测到已安装的 {#MyAppName}。\' + #13#10 + ')
    lines.append('           \'此升级包只能用于升级已安装的版本。\' + #13#10 + #13#10 +')
    lines.append('           \'请先安装完整版程序。\', mbError, MB_OK);')
    lines.append('    Result := false;')
    lines.append('    Exit;')
    lines.append('  end;')
    lines.append('  ')
    lines.append('  // 获取已安装路径')
    lines.append('  InstalledPath := GetInstalledPath();')
    lines.append('  if InstalledPath = \'\' then')
    lines.append('    InstalledPath := \'未知路径\';')
    lines.append('  ')
    lines.append('  // 显示确认对话框')
    lines.append('  Msg := \'检测到已安装的 {#MyAppName}\' + #13#10 + #13#10 +')
    lines.append('         \'安装位置：\' + InstalledPath + #13#10 + #13#10 +')
    lines.append('         \'是否要将程序升级到 V{#MyAppVersion}？\';')
    lines.append('  ')
    lines.append('  if MsgBox(Msg, mbConfirmation, MB_YESNO) = IDYES then')
    lines.append('  begin')
    lines.append('    IsUpgrade := True;')
    lines.append('    UpgradeConfirmed := True;')
    lines.append('    Result := True;')
    lines.append('  end')
    lines.append('  else')
    lines.append('  begin')
    lines.append('    UpgradeConfirmed := False;')
    lines.append('    Result := False;')
    lines.append('  end;')
    lines.append('end;')
    lines.append('')
    lines.append('[Tasks]')
    lines.append('Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "其他任务:"; Flags: unchecked')
    lines.append('')
    lines.append('[Dirs]')
    lines.append('Name: "{app}"; Permissions: users-full')
    lines.append('')
    lines.append('[Files]')
    lines.append('; 以下文件由 build_delta.py 自动生成，只包含实际存在的差异文件')
    lines.append(files_content)
    lines.append('')
    
    # 添加删除文件的处理
    if deleted_files:
        lines.append('[InstallDelete]')
        lines.append('; 删除旧版本中不再需要的文件')
        for rel_path in deleted_files:
            # 转义反斜杠用于 ISS
            rel_path_escaped = rel_path.replace('\\', '\\\\')
            lines.append(f'Type: files; Name: "{{app}}\\\\{rel_path_escaped}"')
        lines.append('')
    
    lines.append('[Icons]')
    lines.append('Name: "{autoprograms}\\\\{#MyAppName}"; Filename: "{app}\\\\{#MyAppExeName}"')
    lines.append('Name: "{autodesktop}\\\\{#MyAppName}"; Filename: "{app}\\\\{#MyAppExeName}"; Tasks: desktopicon')
    lines.append('')
    lines.append('[Run]')
    lines.append('; 升级包不自动启动程序，避免有问题的升级导致无限重启')
    lines.append('; 用户需要手动启动程序来验证升级是否成功')
    lines.append('; Filename: "{app}\\\\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent')
    
    iss_content = '\n'.join(lines)
    
    # 写入输出文件
    with open(iss_output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(iss_content)
    
    return iss_output_path


def main():
    parser = argparse.ArgumentParser(
        description="BirdPictureManager 增量升级包打包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本用法
  python build/build_delta.py --from "dist/栖图_V1.0.0_gpu"
  
  # 指定所有参数
  python build/build_delta.py --from "dist/栖图_V1.0.0_gpu" --to "dist/栖图_V1.0.1_gpu" --version "1.0.1" --flavor gpu --update 1
        """
    )
    parser.add_argument("--from", dest="from_dir", required=True, help="旧版本 dist 目录路径")
    parser.add_argument("--to", dest="to_dir", default="", help="新版本 dist 目录路径（默认自动查找最新版本）")
    parser.add_argument("--version", dest="version", default="", help="升级包版本号（默认从目录名提取）")
    parser.add_argument("--flavor", dest="flavor", default="", help="cpu/gpu（默认自动检测）")
    parser.add_argument("--update", dest="update_num", default="1", help="update 编号，默认 1")
    parser.add_argument("--output", dest="output_dir", default="", help="输出目录（默认在 dist 下创建）")
    args = parser.parse_args()
    
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # 解析旧版本目录
    old_dist_dir = os.path.abspath(args.from_dir)
    if not os.path.isdir(old_dist_dir):
        print(f"错误: 旧版本目录不存在: {old_dist_dir}")
        return 1
    
    print(f"旧版本目录: {old_dist_dir}")
    
    old_flavor = _detect_flavor_from_dir_name(os.path.basename(old_dist_dir))

    # 解析新版本目录
    if args.to_dir:
        new_dist_dir = os.path.abspath(args.to_dir)
    else:
        # 自动查找最新版本
        dist_root = os.path.join(root, "dist")
        if not os.path.isdir(dist_root):
            print(f"错误: dist 目录不存在: {dist_root}")
            return 1
        
        preferred_flavor = str(args.flavor or old_flavor or "").strip().lower()
        new_dist_dir = _select_latest_dist_dir(dist_root, preferred_flavor=preferred_flavor)
        
        if not new_dist_dir:
            print(f"错误: 未找到任何版本目录")
            return 1
    
    if not os.path.isdir(new_dist_dir):
        print(f"错误: 新版本目录不存在: {new_dist_dir}")
        return 1
    if os.path.normcase(os.path.normpath(new_dist_dir)) == os.path.normcase(os.path.normpath(old_dist_dir)):
        print("错误: 新旧版本目录相同，无法生成差分升级包")
        return 1
    
    print(f"新版本目录: {new_dist_dir}")
    
    # 提取版本号
    if args.version:
        app_version = args.version
    else:
        # 从目录名提取版本号
        dir_name = os.path.basename(new_dist_dir)
        if "_V" in dir_name:
            parts = dir_name.split("_V")
            if len(parts) >= 2:
                app_version = parts[1].split("_")[0]
            else:
                app_version = "1.0.0"
        else:
            app_version = "1.0.0"
    
    print(f"版本号: {app_version}")
    
    # 提取 flavor
    if args.flavor:
        app_flavor = args.flavor.lower()
    else:
        # 从目录名检测
        dir_name = os.path.basename(new_dist_dir).lower()
        if "_gpu" in dir_name:
            app_flavor = "gpu"
        elif "_cpu" in dir_name:
            app_flavor = "cpu"
        else:
            app_flavor = ""
    if not app_flavor:
        app_flavor = old_flavor
    
    print(f"Flavor: {app_flavor or '无'}")
    
    # 计算差异文件
    print("\n正在计算文件差异...")
    delta_files = compute_delta_files(old_dist_dir, new_dist_dir)
    
    added_count = len(delta_files["added"])
    modified_count = len(delta_files["modified"])
    deleted_count = len(delta_files["deleted"])
    
    print(f"新增: {added_count} 个文件")
    print(f"修改: {modified_count} 个文件")
    print(f"删除: {deleted_count} 个文件")
    
    if added_count + modified_count + deleted_count == 0:
        print("\n警告: 没有发现任何文件变化")
        return 0
    
    # 创建输出目录
    if args.output_dir:
        output_dir = os.path.abspath(args.output_dir)
    else:
        # 默认在 dist 下创建差分升级目录
        # app_version 可能已经包含 V 前缀，需要处理
        v_token = str(app_version or "").strip()
        if v_token.upper().startswith('V'):
            v_token = v_token[1:]  # 移除 V 前缀
        flavor_suffix = f"_{app_flavor}" if app_flavor else ""
        output_dir = os.path.join(root, "dist", f"栖图_V{v_token}{flavor_suffix}_update{args.update_num}")
    
    print(f"\n创建差分升级包...")
    print(f"输出目录: {output_dir}")
    
    result = create_delta_package(old_dist_dir, new_dist_dir, output_dir, delta_files, app_flavor)
    
    # 生成 iss 脚本
    print("\\n生成安装脚本...")
    iss_output = os.path.join(root, "build", "installer", f"update_V{app_version}_{app_flavor or 'none'}_update{args.update_num}.iss")
    
    iss_path = write_iss_script(
        iss_output,
        output_dir,
        app_version,
        app_flavor,
        args.update_num,
        delta_files.get("deleted", [])
    )
    
    print(f"ISS 脚本: {iss_path}")
    
    # 生成报告
    report_path = os.path.join(output_dir, "_delta_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("BirdPictureManager 增量升级包文件列表\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"旧版本: {old_dist_dir}\n")
        f.write(f"新版本: {new_dist_dir}\n")
        f.write(f"输出目录: {output_dir}\n")
        f.write(f"新增: {added_count} 个文件\n")
        f.write(f"修改: {modified_count} 个文件\n")
        f.write(f"删除: {deleted_count} 个文件\n\n")
        
        if delta_files["added"]:
            f.write("-" * 80 + "\n")
            f.write("新增的文件:\n")
            f.write("-" * 80 + "\n")
            for rel in delta_files["added"]:
                f.write(f"  [+] {rel}\n")
            f.write("\n")
        
        if delta_files["modified"]:
            f.write("-" * 80 + "\n")
            f.write("修改的文件:\n")
            f.write("-" * 80 + "\n")
            for rel in delta_files["modified"]:
                f.write(f"  [*] {rel}\n")
            f.write("\n")
        
        if delta_files["deleted"]:
            f.write("-" * 80 + "\n")
            f.write("删除的文件:\n")
            f.write("-" * 80 + "\n")
            for rel in delta_files["deleted"]:
                f.write(f"  [-] {rel}\n")
            f.write("\n")
        
        f.write("=" * 80 + "\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n")
    
    print(f"差异报告: {report_path}")
    
    # 检查关键文件
    print("\n检查关键文件...")
    critical_files = ["栖图.exe"]
    missing_critical = []
    
    for critical in critical_files:
        # 检查是否在新增或修改列表中
        found = False
        for category in ["added", "modified"]:
            for f in delta_files.get(category, []):
                if f == critical or f.endswith("\\" + critical):
                    found = True
                    break
            if found:
                break
        
        if found:
            print(f"  [OK] {critical}")
        else:
            print(f"  [警告] {critical} 未在升级包中")
    
    # 输出总结
    print("\n" + "=" * 80)
    print("增量升级包创建成功!")
    print("=" * 80)
    print(f"\n输出目录: {output_dir}")
    print(f"ISS 脚本: {iss_path}")
    print(f"\n文件统计:")
    print(f"  - 新增: {added_count} 个")
    print(f"  - 修改: {modified_count} 个")
    print(f"  - 删除: {deleted_count} 个")
    print(f"  - 总计: {added_count + modified_count + deleted_count} 个")
    print(f"\n下一步:")
    print(f"  1. 使用 Inno Setup 打开: {iss_path}")
    print(f"  2. 点击 Build -> Compile 编译安装包")
    print(f"  3. 输出文件: build/installer/栖图_V{app_version}_{app_flavor or 'none'}_update{args.update_num}.exe")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
