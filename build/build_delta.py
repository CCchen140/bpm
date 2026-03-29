#!/usr/bin/env python3
"""BirdPictureManager 增量升级包打包脚本

使用方法:
    python build/build_delta.py --from "dist/V0.0.4" --to "dist/V0.0.5" --version "0.0.5" --update 1

参数:
    --from: 旧版本 dist 目录路径（必需）
    --to: 新版本 dist 目录路径（默认为最新版本）
    --version: 升级包版本号
    --update: update 编号，默认 1
    --setup: 生成 ISS 脚本并编译为 exe 安装包
    --output-zip: 输出为 zip 压缩包（GitHub 发布用，与 --setup 互斥，优先）
    --update-manifest: 同时更新 update_manifest.json（需配合 --output-zip）
    --changelog: 更新日志内容（支持 \\n 换行）

执行模式:
    1. 无 --setup 和 --output-zip: 只生成差异文件和 ISS 脚本，不编译
    2. --setup: 生成 ISS 脚本并编译为 exe 安装包，不创建 zip
    3. --output-zip: 完整流程（生成 ISS、编译、创建 zip、可选更新 manifest）
    4. 同时指定 --setup 和 --output-zip: --output-zip 优先，执行完整流程

注意: GitHub 不支持中文文件名，所有文件名使用 qitu_ 前缀
"""

import argparse
import os
import sys
import shutil
import hashlib
import re
import zipfile
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple


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
            # 忽略系统文件
            name_lower = str(name).lower()
            if name_lower in ("thumbs.db", "desktop.ini"):
                continue
            
            abs_path = os.path.join(base, name)
            try:
                st = os.stat(abs_path)
                size = int(st.st_size)
                mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            except Exception:
                continue
            
            try:
                # 统一使用正斜杠作为路径分隔符
                rel_path = os.path.relpath(abs_path, root_dir).replace("\\", "/")
            except Exception:
                rel_path = name
            
            out[rel_path] = (abs_path, size, mtime_ns)
    
    return out


def _extract_version_from_dist_name(dir_name: str) -> str:
    """从目录名提取版本号，如 V0.0.4 -> 0.0.4"""
    # 支持两种格式: qitu_V0.0.4 (旧) 或 V0.0.4 (新)
    m = re.match(r"^(?:qitu_)?V([^_]+)", str(dir_name or ""))
    if not m:
        return ""
    return str(m.group(1) or "").strip()


def _version_sort_key(version: str):
    """版本号排序键"""
    parts = re.findall(r"\d+|[A-Za-z]+", str(version or ""))
    key = []
    for p in parts:
        if str(p).isdigit():
            key.append((0, int(p)))
        else:
            key.append((1, str(p).lower()))
    return tuple(key)


def _select_latest_dist_dir(dist_root: str, suffix: str = "fr") -> str:
    """选择最新的 dist 目录
    
    参数:
        dist_root: dist 目录根路径
        suffix: 目录后缀，如 "fr" (完整包) 或 "u1" (update1包)
    """
    candidates: list[tuple[tuple, str]] = []
    for name in os.listdir(dist_root):
        full = os.path.join(dist_root, name)
        if not os.path.isdir(full):
            continue
        # 支持格式: qitu_V0.0.4_fr 或 qitu_V0.0.4_u1
        if not str(name).startswith("qitu_V"):
            continue
        # 检查是否匹配指定的后缀
        if suffix and not str(name).endswith(f"_{suffix}"):
            continue
        version = _extract_version_from_dist_name(name)
        if not version:
            continue
        candidates.append((_version_sort_key(version), name))
    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return os.path.join(dist_root, candidates[0][1])


def _hash_file(path: str, max_bytes: int = 512 * 1024 * 1024) -> str:
    """计算文件 SHA256 哈希，支持最大 512MB 的文件"""
    try:
        st = os.stat(path)
        file_size = int(st.st_size)
    except Exception:
        return ""
    
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            bytes_read = 0
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                bytes_read += len(chunk)
                if bytes_read >= max_bytes:
                    break
        h.update(str(file_size).encode())
        return h.hexdigest()
    except Exception:
        return ""


def read_changelog_from_release_note(root_dir: str, version: str, update_num: str = "") -> str:
    """从ReleaseNote.md文件中读取指定版本的changelog
    
    参数:
        root_dir: 项目根目录
        version: 版本号，如 "0.0.4"
        update_num: update编号，如 "1"，为空表示读取基础版本
        
    返回:
        对应版本的changelog内容，如果未找到则返回空字符串
    """
    release_note_path = os.path.join(root_dir, "ReleaseNote.md")
    if not os.path.exists(release_note_path):
        print(f"  警告: ReleaseNote.md 不存在: {release_note_path}")
        return ""
    
    try:
        with open(release_note_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 构建版本标签，ReleaseNote.md中使用连字符格式，如 V0.0.4-update1
        if update_num:
            version_tag = f"V{version}-update{update_num}"
        else:
            version_tag = f"V{version}"
        
        # 查找对应版本的changelog
        # 格式: V0.0.4-update1\n    1.xxx\n    2.xxx
        # 使用多行模式匹配，直到遇到下一个版本标签或文件结束
        pattern = rf"^{re.escape(version_tag)}\s*\n((?:(?!^V\d+\.\d+\.\d+).+\n?)*)"
        match = re.search(pattern, content, re.MULTILINE)
        
        if match:
            # 提取并清理changelog内容
            changelog = match.group(1).strip()
            # 移除每行前面的空格
            lines = [line.strip() for line in changelog.split('\n') if line.strip()]
            content_body = '\n'.join(lines)
            # 构建带版本标题的changelog格式: ## V0.0.4_update2\n1.xxx\n2.xxx
            if update_num:
                display_version = f"V{version}_update{update_num}"
            else:
                display_version = f"V{version}"
            result = f"## {display_version}\n{content_body}"
            print(f"  从 ReleaseNote.md 读取到 {version_tag} 的 changelog")
            return result
        else:
            print(f"  警告: 在 ReleaseNote.md 中未找到 {version_tag} 的 changelog")
            return ""
            
    except Exception as e:
        print(f"  警告: 读取 ReleaseNote.md 失败: {e}")
        return ""


def compute_delta_files(old_dist_dir: str, new_dist_dir: str) -> dict:
    old_map = _walk_dist_files(old_dist_dir)
    new_map = _walk_dist_files(new_dist_dir)
    
    # 创建小写映射用于大小写不敏感比较
    old_map_lower = {k.lower(): k for k in old_map.keys()}
    new_map_lower = {k.lower(): k for k in new_map.keys()}
    
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []
    
    # 检查新增和修改的文件
    for rel, (new_abs, new_size, new_mtime) in new_map.items():
        rel_lower = rel.lower()
        old_key = old_map_lower.get(rel_lower)
        
        if old_key is None:
            added.append(rel)
            continue
        
        # 如果文件名大小写不同，记录为重命名
        if old_key != rel:
            renamed.append((old_key, rel))
            continue
        
        old = old_map.get(old_key)
        _, old_size, old_mtime = old
        
        # 1. 大小不同 -> 肯定是修改
        if int(old_size) != int(new_size):
            modified.append(rel)
            continue
        
        # 2. 大小相同，时间戳也相同 -> 认为是未修改
        if int(old_mtime) == int(new_mtime):
            continue
        
        # 3. 大小相同，时间戳不同 -> 计算哈希进一步比较
        old_hash = _hash_file(old[0])
        new_hash = _hash_file(new_abs)
        if old_hash and new_hash:
            if old_hash != new_hash:
                modified.append(rel)
            continue
        
        # 4. 无法计算哈希，保守起见认为是修改
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


def create_diff_manifest(
    delta_files: dict,
    old_version: str,
    new_version: str,
    diff_dir: str,
    output_dir: str = None
) -> str:
    """
    创建差异文件清单

    参数:
        delta_files: 差异文件信息
        old_version: 旧版本号
        new_version: 新版本号
        diff_dir: 差异文件输出目录（保存到 /dist/diff/）
        output_dir: 升级包输出目录（可选，用于复制清单到升级包）

    返回:
        清单文件路径
    """
    # 确保输出目录存在
    os.makedirs(diff_dir, exist_ok=True)

    # 生成清单文件名
    manifest_filename = f"diff_V{old_version}_to_V{new_version}.json"
    manifest_path = os.path.join(diff_dir, manifest_filename)

    # 准备清单内容
    manifest = {
        "version": "1.0",
        "from_version": old_version,
        "to_version": new_version,
        "build_time": datetime.now().isoformat(),
        "affected_files": delta_files.get("modified", []) + delta_files.get("renamed", []),
        "new_files": delta_files.get("added", []),
        "deleted_files": delta_files.get("deleted", []),
        "renamed_files": [
            {"from": old_name, "to": new_name}
            for old_name, new_name in delta_files.get("renamed", [])
        ]
    }

    # 保存清单文件到 /dist/diff/
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"  差异清单已生成: {manifest_path}")
    print(f"    - 受影响文件: {len(manifest['affected_files'])} 个")
    print(f"    - 新增文件: {len(manifest['new_files'])} 个")
    print(f"    - 删除文件: {len(manifest['deleted_files'])} 个")

    # 同时复制到升级包目录（如果指定了输出目录）
    if output_dir and os.path.exists(output_dir):
        dest_path = os.path.join(output_dir, manifest_filename)
        shutil.copy2(manifest_path, dest_path)
        print(f"  差异清单已复制到升级包: {dest_path}")

    return manifest_path


def create_delta_package(
    old_dist_dir: str,
    new_dist_dir: str,
    output_dir: str,
    delta_files: dict,
    app_flavor: str = "",
    old_version: str = "",
    new_version: str = ""
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
            flavor = "gpu"
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

        dst_dir = os.path.dirname(dst_path)
        os.makedirs(dst_dir, exist_ok=True)

        shutil.copy2(src_path, dst_path)
        copied_files.append(new_name)
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

    # 生成差异文件清单
    diff_manifest_path = ""
    if old_version and new_version:
        print("\n生成差异文件清单...")
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        diff_dir = os.path.join(root, "dist", "diff")
        diff_manifest_path = create_diff_manifest(
            delta_files, old_version, new_version, diff_dir, output_dir
        )

    return {
        "copied": copied_files,
        "deleted": deleted_files,
        "output_dir": output_dir,
        "diff_manifest": diff_manifest_path
    }


def generate_iss_script(
    output_path: str,
    source_dir: str,
    app_version: str,
    app_flavor: str,
    update_num: str,
    deleted_files: list = None
) -> bool:
    """
    生成 Inno Setup 升级包脚本，包含优化的卸载处理（复选框选择删除用户数据）

    参数:
        output_path: 输出 ISS 文件路径
        source_dir: 源目录（升级包文件所在目录）
        app_version: 应用版本号
        app_flavor: 构建类型 (cpu/gpu)
        update_num: 更新编号
        deleted_files: 需要删除的文件列表

    返回:
        生成是否成功
    """
    try:
        # 收集所有需要打包的文件
        files_entries = []
        for root, dirs, files in os.walk(source_dir):
            for filename in files:
                if filename.startswith('_'):
                    continue
                src_path = os.path.join(root, filename)
                rel_path = os.path.relpath(src_path, source_dir).replace('/', '\\')
                rel_dir = os.path.dirname(rel_path)

                if rel_dir:
                    dest_dir = "{app}\\" + rel_dir.replace('\\', '\\\\')
                else:
                    dest_dir = "{app}"

                rel_path_escaped = rel_path.replace('\\', '\\\\')
                files_entries.append(f'Source: "{{#MyAppDistDir}}\\{rel_path_escaped}"; DestDir: "{dest_dir}"; Flags: ignoreversion')

        files_content = '\n'.join(files_entries) if files_entries else '; 没有需要打包的文件'

        # 构建删除文件段
        delete_section = ""
        if deleted_files:
            delete_lines = ["; 删除旧版本中不再需要的文件"]
            for rel_path in deleted_files:
                rel_path_escaped = rel_path.replace('\\', '\\\\')
                delete_lines.append(f'Type: files; Name: "{{app}}\\{rel_path_escaped}"')
            delete_section = "\n[InstallDelete]\n" + "\n".join(delete_lines)

        # ISS 脚本内容
        # 预先处理路径转义，避免在f-string中使用反斜杠转义
        source_dir_escaped = os.path.abspath(source_dir).replace('\\', '\\\\')
        iss_content = f'''; 增量升级包安装脚本
; 由 build_delta.py 自动生成

#define MyAppName "栖图"
#define MyAppVersion "{app_version}"
#define MyAppPublisher "cCc"
#define MyAppExeName "qitu.exe"
#define MyAppId "74F28464-C26A-47D9-AE73-22E79631B472"
#define MyAppFlavor "{app_flavor}"
#define MyAppUpdate "{update_num}"
#define MyAppDistDir "{source_dir_escaped}"
#define MyAppFullVersion "V{app_version}_update{update_num}"

[Setup]
AppId={{#MyAppId}}
AppName={{#MyAppName}} Upgrade Pack
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
UninstallDisplayIcon={{app}}\\{{#MyAppExeName}}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputDir={{#SourcePath}}
OutputBaseFilename={{#MyAppName}}_V{{#MyAppVersion}}_update{{#MyAppUpdate}}
SolidCompression=yes
Compression=lzma2/ultra64
InternalCompressLevel=ultra64
CompressionThreads=auto
WizardStyle=modern
UsePreviousAppDir=yes
; 对于升级包，显示目录页面但禁止用户修改（通过代码强制设置路径）
DisableDirPage=no
; 不提示文件夹已存在（因为是升级，文件夹肯定存在）
DirExistsWarning=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=升级 {{#MyAppName}}
SetupWindowTitle=升级 {{#MyAppName}} - V{{#MyAppVersion}}
SelectDirDesc=选择之前安装 {{#MyAppName}} 的文件夹进行升级。
SelectDirLabel3=安装程序将升级 {{#MyAppName}} 到以下文件夹。
InstallingLabel=正在升级 {{#MyAppName}}，请稍候...
FinishedLabel=已完成 {{#MyAppName}} 的升级。
FinishedHeadingLabel=升级完成
FinishedLabelNoIcons=已完成 {{#MyAppName}} 的升级。

[Code]
var
  IsUpgrade: Boolean;
  InstalledPath: String;
  UpgradeConfirmed: Boolean;

// 卸载步骤变化时的处理
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataPath: String;
  DeleteData: Boolean;
begin
  // 在卸载开始时询问用户是否删除数据
  if CurUninstallStep = usUninstall then
  begin
    DeleteData := MsgBox('是否同时删除所有用户数据（配置文件、数据库、收藏等）？' + Chr(13) + Chr(10) + Chr(13) + Chr(10) +
                         '如果您计划重新安装软件，建议选择"否"保留数据。' + Chr(13) + Chr(10) +
                         '选择"是"将彻底删除包括数据库在内的所有用户数据。',
                         mbConfirmation, MB_YESNO) = IDYES;
    
    // 将用户选择保存到注册表，供后续步骤读取
    if DeleteData then
      RegWriteStringValue(HKCU, 'Software\\BirdPictureManager\\Uninstall', 'DeleteData', '1')
    else
      RegWriteStringValue(HKCU, 'Software\\BirdPictureManager\\Uninstall', 'DeleteData', '0');
  end;

  // 在卸载完成后执行删除操作
  if CurUninstallStep = usPostUninstall then
  begin
    // 读取用户选择
    DeleteData := False;
    try
      if RegValueExists(HKCU, 'Software\\BirdPictureManager\\Uninstall', 'DeleteData') then
      begin
        DeleteData := RegQueryStringValue(HKCU, 'Software\\BirdPictureManager\\Uninstall', 'DeleteData', UserDataPath) and (UserDataPath = '1');
      end;
    except
      DeleteData := False;
    end;
    
    // 清理临时注册表项
    try
      if RegKeyExists(HKCU, 'Software\\BirdPictureManager\\Uninstall') then
        RegDeleteKeyIncludingSubkeys(HKCU, 'Software\\BirdPictureManager\\Uninstall');
    except
    end;
    
    // 如果用户选择删除数据
    if DeleteData then
    begin
      // 1. 从注册表获取 UserDataPath
      if RegQueryStringValue(HKCU, 'Software\\BirdPictureManager\\BirdManager_Global', 'UserDataPath', UserDataPath) then
      begin
        if (UserDataPath <> '') and DirExists(UserDataPath) then
        begin
           DelTree(UserDataPath, True, True, True);
        end;
      end;

      // 2. 同时尝试默认路径: Documents/qitu/data
      UserDataPath := ExpandConstant('{{userdocs}}\\qitu\\data');
      if DirExists(UserDataPath) then
      begin
         DelTree(UserDataPath, True, True, True);
      end;

      // 3. 尝试其他可能的配置路径
      UserDataPath := ExpandConstant('{{localappdata}}\\qitu');
      if DirExists(UserDataPath) then
      begin
         DelTree(UserDataPath, True, True, True);
      end;

      // 4. 删除注册表项
      if RegKeyExists(HKCU, 'Software\\BirdPictureManager') then
      begin
        RegDeleteKeyIncludingSubkeys(HKCU, 'Software\\BirdPictureManager');
      end;
    end;
  end;
end;

function GetInstalledPath(): String;
var
  Path: String;
  UninstallStr: String;
begin
  Path := '';
  UninstallStr := '';

  // 首先尝试从 InstallLocation 读取
  RegQueryStringValue(HKLM, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{{#MyAppId}}_is1', 'InstallLocation', Path);
  if (Path = '') then
    RegQueryStringValue(HKLM, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{{#MyAppId}}_is1', 'Inno Setup: App Path', Path);

  // 如果还是没有，尝试从 UninstallString 提取路径
  if (Path = '') then
  begin
    RegQueryStringValue(HKLM, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{{#MyAppId}}_is1', 'UninstallString', UninstallStr);
    if (UninstallStr <> '') then
    begin
      Path := ExtractFilePath(UninstallStr);
    end;
  end;

  Result := Path;
end;

procedure InitializeWizard();
begin
  // 在向导初始化时设置安装目录为已检测到的路径
  // 注意：InstalledPath 在 InitializeSetup 中已经获取
  // 只有在路径有效且不是默认值时才设置
  if (InstalledPath <> '') and (InstalledPath <> '未知路径') and DirExists(InstalledPath) then
  begin
    WizardForm.DirEdit.Text := InstalledPath;
  end;
end;

function InitializeSetup(): Boolean;
var
  Msg: String;
begin
  // 检查是否已安装
  if not RegKeyExists(HKLM, 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{{#MyAppId}}_is1') then
  begin
    MsgBox('未检测到已安装的 {{#MyAppName}}。' + Chr(13) + Chr(10) +
           '此升级包只能用于升级已安装的版本。' + Chr(13) + Chr(10) + Chr(13) + Chr(10) +
           '请先安装完整版程序。', mbError, MB_OK);
    Result := false;
    Exit;
  end;

  // 获取已安装路径
  InstalledPath := GetInstalledPath();
  if InstalledPath = '' then
    InstalledPath := '未知路径';

  // 显示确认对话框
  Msg := '检测到已安装的 {{#MyAppName}}' + Chr(13) + Chr(10) + Chr(13) + Chr(10) +
         '安装位置：' + InstalledPath + Chr(13) + Chr(10) + Chr(13) + Chr(10) +
         '是否要将程序升级到 {{#MyAppFullVersion}}？';

  if MsgBox(Msg, mbConfirmation, MB_YESNO) = IDYES then
  begin
    IsUpgrade := True;
    UpgradeConfirmed := True;
    Result := True;
  end
  else
  begin
    UpgradeConfirmed := False;
    Result := False;
  end;
end;



[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "其他任务:"; Flags: checkablealone

[Dirs]
Name: "{{app}}"; Permissions: users-full

[Files]
; 以下文件由 build_delta.py 自动生成，只包含实际存在的差异文件
{files_content}{delete_section}

[Icons]
Name: "{{autoprograms}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "启动 {{#MyAppName}}"; Flags: nowait postinstall skipifsilent
'''

        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 写入 ISS 文件
        with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(iss_content)

        return True
    except Exception as e:
        print(f"生成 ISS 脚本失败: {e}")
        return False


def compile_iss_script(iss_path: str, inno_setup_dir: str = None) -> Tuple[bool, str]:
    """
    使用 Inno Setup 编译 ISS 脚本

    参数:
        iss_path: ISS 脚本路径
        inno_setup_dir: Inno Setup 安装目录（可选，自动检测）

    返回:
        (编译是否成功, 生成的 exe 路径)
    """
    try:
        # 自动检测 Inno Setup 目录
        if not inno_setup_dir:
            # 常见安装路径
            possible_paths = [
                r"C:\Program Files (x86)\Inno Setup 6",
                r"C:\Program Files\Inno Setup 6",
                r"D:\Program Files (x86)\Inno Setup 6",
                r"D:\Program Files\Inno Setup 6",
            ]
            for path in possible_paths:
                if os.path.isdir(path) and os.path.exists(os.path.join(path, "ISCC.exe")):
                    inno_setup_dir = path
                    break

        if not inno_setup_dir:
            print("  错误: 未找到 Inno Setup，请确保已安装并添加到 PATH")
            return False, ""

        iscc_exe = os.path.join(inno_setup_dir, "ISCC.exe")
        if not os.path.exists(iscc_exe):
            print(f"  错误: 未找到 ISCC.exe: {iscc_exe}")
            return False, ""

        print(f"  使用 Inno Setup: {inno_setup_dir}")
        print(f"  编译脚本: {iss_path}")

        # 执行编译
        import subprocess
        result = subprocess.run(
            [iscc_exe, iss_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        if result.returncode != 0:
            print(f"  编译失败: {result.stderr}")
            return False, ""

        # 从输出中提取 exe 路径
        exe_path = ""
        for line in result.stdout.split('\n'):
            if 'Output:' in line or '输出:' in line:
                # 提取路径
                parts = line.split(':', 1)
                if len(parts) > 1:
                    exe_path = parts[1].strip()
                    break

        # 如果无法从输出提取，尝试从ISS脚本内容解析OutputBaseFilename
        if not exe_path:
            try:
                with open(iss_path, 'r', encoding='utf-8') as f:
                    iss_content = f.read()
                
                # 先提取#define定义的宏值
                defines = {}
                for line in iss_content.split('\n'):
                    if line.strip().startswith('#define'):
                        parts = line.strip().split(None, 2)
                        if len(parts) >= 3:
                            defines[parts[1]] = parts[2].strip('"')
                
                # 查找 OutputBaseFilename 行
                for line in iss_content.split('\n'):
                    if 'OutputBaseFilename=' in line:
                        # 提取文件名
                        parts = line.split('=', 1)
                        if len(parts) > 1:
                            base_name = parts[1].strip()
                            # 替换ISS宏 {#MacroName} -> 对应的值
                            for macro, value in defines.items():
                                base_name = base_name.replace(f'{{#{macro}}}', value)
                            # 清理多余的_
                            while '__' in base_name:
                                base_name = base_name.replace('__', '_')
                            base_name = base_name.strip('_')
                            if base_name:
                                iss_dir = os.path.dirname(iss_path)
                                possible_exe = os.path.join(iss_dir, f"{base_name}.exe")
                                if os.path.exists(possible_exe):
                                    exe_path = possible_exe
                                    break
            except Exception:
                pass

        if exe_path:
            print(f"  编译成功: {exe_path}")
            return True, exe_path
        else:
            print(f"  编译成功但无法确定 exe 路径，尝试查找...")
            # 从 ISS 脚本内容提取版本信息用于匹配
            iss_version = None
            iss_update = None
            try:
                with open(iss_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '#define MyAppVersion' in line:
                            parts = line.strip().split('"')
                            if len(parts) >= 2:
                                iss_version = parts[1]
                        elif '#define MyAppUpdate' in line:
                            parts = line.strip().split('"')
                            if len(parts) >= 2:
                                iss_update = parts[1]
            except Exception:
                pass
            
            # 构建匹配模式
            version_patterns = []
            if iss_version and iss_update:
                # 优先匹配完整版本号，如 V0.0.4_update1
                version_patterns.append(f"V{iss_version}_update{iss_update}")
                version_patterns.append(f"V{iss_version}_u{iss_update}")
            
            # 从 ISS 文件名提取版本作为备选
            iss_name = os.path.splitext(os.path.basename(iss_path))[0]
            if '_V' in iss_name:
                version_match = iss_name.split('_V', 1)[1]  # 0.0.4_update1
                if version_match not in version_patterns:
                    version_patterns.append(version_match)
            
            # 尝试查找 ISS 目录下的 exe 文件
            iss_dir = os.path.dirname(iss_path)
            for pattern in version_patterns:
                for f in os.listdir(iss_dir):
                    if f.endswith('.exe') and pattern in f:
                        exe_path = os.path.join(iss_dir, f)
                        print(f"  找到匹配的 exe: {exe_path}")
                        return True, exe_path
            
            # 如果 ISS 目录找不到，尝试查找 build/installer 目录
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            installer_dir = os.path.join(root, "build", "installer")
            if os.path.isdir(installer_dir):
                # 优先查找匹配的版本
                for pattern in version_patterns:
                    for f in os.listdir(installer_dir):
                        if f.endswith('.exe') and pattern in f:
                            exe_path = os.path.join(installer_dir, f)
                            print(f"  找到匹配的 exe: {exe_path}")
                            return True, exe_path
                # 如果没有匹配的，找最新的（包含 update 或 u 的）
                for f in sorted(os.listdir(installer_dir), reverse=True):
                    if f.endswith('.exe') and ('update' in f.lower() or '_u' in f.lower()):
                        exe_path = os.path.join(installer_dir, f)
                        print(f"  找到 exe: {exe_path}")
                        return True, exe_path
            print(f"  警告: 未找到生成的 exe 文件")
            return True, ""

    except Exception as e:
        print(f"  编译失败: {e}")
        return False, ""


def create_zip_with_exe(exe_path: str, diff_manifest_path: str, output_zip_path: str, build_flavor: str) -> bool:
    """
    创建包含 exe 安装包和差异清单的 zip 文件

    参数:
        exe_path: exe 安装包路径
        diff_manifest_path: 差异清单文件路径
        output_zip_path: 输出 zip 文件路径
        build_flavor: 构建类型 (cpu/gpu)

    返回:
        打包是否成功
    """
    try:
        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)

        # 如果 zip 文件已存在，先删除
        if os.path.exists(output_zip_path):
            os.remove(output_zip_path)

        # 创建 zip 文件
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            # 添加 exe 文件
            if os.path.exists(exe_path):
                exe_name = os.path.basename(exe_path)
                zf.write(exe_path, exe_name)
                print(f"  添加: {exe_name}")

            # 添加差异清单
            if os.path.exists(diff_manifest_path):
                manifest_name = os.path.basename(diff_manifest_path)
                zf.write(diff_manifest_path, manifest_name)
                print(f"  添加: {manifest_name}")

            # 添加构建类型标记文件
            zf.writestr("build_flavor.txt", build_flavor)
            print(f"  添加: build_flavor.txt ({build_flavor})")

        return True
    except Exception as e:
        print(f"创建 zip 包失败: {e}")
        return False


def calculate_file_hash(file_path: str) -> str:
    """
    计算文件的 SHA256 哈希值

    参数:
        file_path: 文件路径

    返回:
        SHA256 哈希值（小写十六进制字符串）
    """
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest().lower()
    except Exception as e:
        print(f"计算哈希失败: {e}")
        return ""


def create_zip_package(source_dir: str, zip_path: str) -> bool:
    """
    将升级包目录打包为 zip 文件（旧版本兼容）

    参数:
        source_dir: 源目录
        zip_path: 输出 zip 文件路径

    返回:
        打包是否成功
    """
    try:
        # 确保输出目录存在
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)

        # 如果 zip 文件已存在，先删除
        if os.path.exists(zip_path):
            os.remove(zip_path)

        # 创建 zip 文件
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # 计算相对路径
                    arcname = os.path.relpath(file_path, source_dir).replace("\\", "/")
                    zf.write(file_path, arcname)

        return True
    except Exception as e:
        print(f"创建 zip 包失败: {e}")
        return False


def split_large_package(zip_path: str, output_dir: str) -> Tuple[bool, List[Dict]]:
    """
    如果 zip 包超过 GitHub 限制，自动分包
    
    参数:
        zip_path: zip 文件路径
        output_dir: 输出目录
        
    返回:
        (是否需要分包, 分包信息列表)
    """
    # 导入分包工具
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "update"))
    from file_splitter import split_file, needs_splitting, format_size
    
    if not needs_splitting(zip_path):
        return False, []
    
    print(f"\n检测到文件超过 GitHub 2GB 限制，自动分包...")
    print(f"  文件: {os.path.basename(zip_path)}")
    print(f"  大小: {format_size(os.path.getsize(zip_path))}")
    
    success, parts_info = split_file(zip_path, output_dir)
    
    if success:
        print(f"\n✓ 分包完成，共 {len(parts_info)} 个分包")
        print("\n请将所有分包文件上传到 GitHub Releases:")
        for part in parts_info:
            print(f"  - {part['filename']}")
    
    return success, parts_info


def calculate_sha256(file_path: str) -> str:
    """计算文件的 SHA256 哈希值"""
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception:
        return ""


def get_file_size(file_path: str) -> int:
    """获取文件大小"""
    try:
        return os.path.getsize(file_path)
    except Exception:
        return 0


def update_manifest_json(
    manifest_path: str,
    version: str,
    update_num: str,
    zip_path: str,
    from_version: str,
    is_cross_upgrade: bool = False,
    changelog: str = "",
    parts_info: List[Dict] = None
) -> bool:
    """
    更新 update_manifest.json 文件
    
    支持追加到已有文件，保留原有的 changelog 等信息
    支持分包信息记录
    
    参数:
        manifest_path: manifest 文件路径
        version: 版本号
        update_num: update 编号
        zip_path: zip 文件路径
        from_version: 从哪个版本升级
        is_cross_upgrade: 是否是跨版本升级
        changelog: 更新日志（可选，为空时保留原有）
        parts_info: 分包信息列表（可选）
        
    返回:
        更新是否成功
    """
    try:
        # 加载现有 manifest
        manifest = {}
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            print(f"  已加载现有 manifest: {manifest_path}")
        else:
            print(f"  创建新的 manifest: {manifest_path}")
        
        # 确保基本结构存在
        if "releases" not in manifest:
            manifest["releases"] = {}
        
        # 保留或设置默认值
        if "force_update" not in manifest:
            manifest["force_update"] = False
        if "min_supported_version" not in manifest:
            manifest["min_supported_version"] = from_version
        
        # 更新 changelog（如果提供了新的）
        if changelog:
            manifest["changelog"] = changelog
        elif "changelog" not in manifest:
            manifest["changelog"] = ""
        
        # 计算文件哈希和大小
        file_hash = calculate_sha256(zip_path)
        file_size = get_file_size(zip_path)
        
        # 构建包信息
        package_info = {
            "package": os.path.basename(zip_path),
            "hash": f"sha256:{file_hash}",
            "size": file_size
        }
        
        # 如果有分包信息，添加到包信息中
        if parts_info:
            package_info["is_split"] = True
            package_info["parts"] = parts_info
            print(f"  记录 {len(parts_info)} 个分包信息")
        
        if is_cross_upgrade:
            # 跨版本升级包
            if version not in manifest["releases"]:
                manifest["releases"][version] = {
                    "base_version": version,
                    "cross_upgrade": {},
                    "updates": {}
                }
            manifest["releases"][version]["cross_upgrade"] = {
                "from_base": from_version,
                "tag": f"V{version}",
                **package_info
            }
            print(f"  添加跨版本升级包: V{from_version} → V{version}")
        else:
            # 同版本内的 update 包
            if version not in manifest["releases"]:
                manifest["releases"][version] = {
                    "base_version": version,
                    "cross_upgrade": {},
                    "updates": {}
                }
            manifest["releases"][version]["updates"][update_num] = {
                "version": f"{version}_update{update_num}",
                "tag": f"V{version}_update{update_num}",
                **package_info
            }
            print(f"  添加 update 包: V{version}_update{update_num}")
        
        # 更新最新版本
        new_latest = f"{version}_update{update_num}" if not is_cross_upgrade else version
        manifest["latest_version"] = new_latest
        manifest["release_date"] = datetime.now().strftime("%Y-%m-%d")
        
        # 保存 manifest
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        print(f"  最新版本已更新为: V{new_latest}")
        return True
    except Exception as e:
        print(f"更新 manifest 失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="BirdPictureManager 增量升级包打包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 基本用法（生成 ISS 脚本）
  python build/build_delta.py --from "dist/qitu_V0.0.4"
  
  # 生成 zip 压缩包（GitHub 发布用）
  python build/build_delta.py --from "dist/qitu_V0.0.4" --output-zip
  
  # 生成 zip 并更新 manifest
  python build/build_delta.py --from "dist/qitu_V0.0.4" --output-zip --update-manifest
        """
    )
    parser.add_argument("--from", dest="from_dir", required=True, help="旧版本 dist 目录路径")
    parser.add_argument("--to", dest="to_dir", default="", help="新版本 dist 目录路径（默认自动查找最新版本）")
    parser.add_argument("--version", dest="version", default="", help="升级包版本号（默认从目录名提取）")
    parser.add_argument("--flavor", dest="flavor", default="gpu", help="构建类型，默认 gpu")
    parser.add_argument("--update", dest="update_num", default="1", help="update 编号，默认 1")
    parser.add_argument("--output", dest="output_dir", default="", help="输出目录（默认在 dist 下创建）")
    parser.add_argument("--output-zip", action="store_true", help="输出为 zip 压缩包（与 --setup 互斥，优先）")
    parser.add_argument("--setup", action="store_true", help="生成 InnoSetup 脚本并编译为 exe 安装包")
    parser.add_argument("--update-manifest", action="store_true", help="同时更新 update_manifest.json")
    parser.add_argument("--manifest-path", default="", help="manifest.json 文件路径（默认: dist/update_manifest.json）")
    parser.add_argument("--changelog", default="", help="更新日志内容（支持 \\n 换行）")
    args = parser.parse_args()
    
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # 自动从代码中读取update版本号
    try:
        sys.path.insert(0, root)
        from utils.system.app_info_manager import APP_UPDATE
        # 如果APP_UPDATE不为空，提取数字部分作为update_num
        if APP_UPDATE:
            # 支持格式: "update1" -> "1", "u1" -> "1"
            update_str = str(APP_UPDATE).strip()
            if update_str.lower().startswith('update'):
                update_num = update_str[6:]  # 去掉"update"前缀
            elif update_str.lower().startswith('u'):
                update_num = update_str[1:]  # 去掉"u"前缀
            else:
                update_num = update_str
            # 验证是否是数字
            if update_num.isdigit():
                args.update_num = update_num
                print(f"[自动检测] 从代码中读取到update版本: {APP_UPDATE} (编号: {update_num})")
    except Exception as e:
        print(f"[警告] 无法从代码读取update版本: {e}")
        pass

    # 解析旧版本目录
    # 如果指定的是基础版本（如 qitu_V0.0.4），自动查找对应的 fr 目录
    old_dist_dir_input = os.path.abspath(args.from_dir)
    old_dist_dir = old_dist_dir_input

    # 如果目录不存在，尝试查找 fr 后缀的目录
    if not os.path.isdir(old_dist_dir):
        fr_dir = f"{old_dist_dir_input}_fr"
        if os.path.isdir(fr_dir):
            old_dist_dir = fr_dir
            print(f"  自动找到完整包目录: {old_dist_dir}")

    if not os.path.isdir(old_dist_dir):
        print(f"错误: 旧版本目录不存在: {old_dist_dir}")
        return 1

    print(f"旧版本目录: {old_dist_dir}")

    # 提取旧版本号
    old_version = _extract_version_from_dist_name(os.path.basename(old_dist_dir))
    print(f"旧版本号: V{old_version}")

    # 解析新版本目录
    if args.to_dir:
        new_dist_dir = os.path.abspath(args.to_dir)
    else:
        dist_root = os.path.join(root, "dist")
        if not os.path.isdir(dist_root):
            print(f"错误: dist 目录不存在: {dist_root}")
            return 1
        # 根据 update 参数查找对应后缀的目录
        # update 1 -> 查找 u1 目录（完整包使用u1格式），如果不存在则查找 fr 目录
        update_suffix = f"u{args.update_num}"
        new_dist_dir = _select_latest_dist_dir(dist_root, suffix=update_suffix)
        if not new_dist_dir:
            # 如果找不到 u1 目录，尝试找 fr 目录
            new_dist_dir = _select_latest_dist_dir(dist_root, suffix="fr")
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
        # 去除可能传入的V前缀
        if app_version.upper().startswith('V'):
            app_version = app_version[1:]
    else:
        # 使用统一的版本提取函数，确保不包含V前缀
        app_version = _extract_version_from_dist_name(os.path.basename(new_dist_dir))
        if not app_version:
            app_version = "1.0.0"

    # 构建完整的新版本号（包含update编号）用于显示
    display_version = f"V{app_version}_update{args.update_num}"
    print(f"新版本号: {display_version}")

    # 获取 flavor（从目录名或参数）
    app_flavor = str(args.flavor or "gpu").strip().lower()
    print(f"Flavor: {app_flavor}")
    
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
    # 新的命名方式: qitu_Vx.x.x_u1 (update1)
    v_token = str(app_version or "").strip()
    if v_token.upper().startswith('V'):
        v_token = v_token[1:]

    if args.output_dir:
        output_dir = os.path.abspath(args.output_dir)
    else:
        # 使用新的命名格式: qitu_V0.0.4_update1
        output_dir = os.path.join(root, "dist", f"qitu_V{v_token}_update{args.update_num}")

    print(f"\n创建差分升级包...")
    print(f"输出目录: {output_dir}")

    # 构建完整的新版本号（包含update编号）
    new_version_full = f"{app_version}_update{args.update_num}"

    result = create_delta_package(
        old_dist_dir, new_dist_dir, output_dir, delta_files,
        app_flavor, old_version, new_version_full
    )

    # 生成 ISS 脚本
    print("\n生成安装脚本...")
    iss_output = os.path.join(root, "build", "installer", f"update_V{v_token}_update{args.update_num}.iss")
    iss_success = generate_iss_script(
        output_path=iss_output,
        source_dir=output_dir,
        app_version=v_token,
        app_flavor=app_flavor,
        update_num=args.update_num,
        deleted_files=result.get("deleted", [])
    )
    if not iss_success:
        print(f"  警告: ISS 脚本生成失败")
        return 1
    print(f"  ISS 脚本已生成: {iss_output}")

    # 获取差异清单路径
    diff_manifest_path = result.get("diff_manifest", "")

    # 确定执行模式：
    # 1. --output-zip: 完整流程（生成 ISS、编译、创建 zip、更新 manifest）
    # 2. --setup（无 --output-zip）: 只生成 ISS 脚本并编译 exe，不创建 zip
    # 3. 无参数: 只生成差异文件和 ISS 脚本，不编译
    run_compile = args.output_zip or args.setup
    run_zip = args.output_zip

    # 编译 ISS 脚本生成 exe 安装包（当 --output-zip 或 --setup 时）
    exe_path = ""
    if run_compile:
        print("\n编译安装包...")
        compile_success, exe_path = compile_iss_script(iss_output)
        if not compile_success or not exe_path:
            print("  错误: 安装包编译失败")
            return 1
    else:
        print("\n跳过编译（使用 --setup 或 --output-zip 启用）")

    # 创建 zip 包（包含 exe 和差异清单，仅当 --output-zip 时）
    zip_path = ""
    if run_zip and exe_path:
        print("\n创建 zip 升级包...")
        # 新的命名格式: qitu_V0.0.4_update1.zip
        zip_filename = f"qitu_V{v_token}_update{args.update_num}.zip"
        zip_path = os.path.join(root, "dist", zip_filename)

        zip_success = create_zip_with_exe(
            exe_path=exe_path,
            diff_manifest_path=diff_manifest_path,
            output_zip_path=zip_path,
            build_flavor=app_flavor
        )
        if zip_success:
            print(f"  zip 包已创建: {zip_path}")
        else:
            print(f"  警告: zip 包创建失败")
            zip_path = ""

        # 更新 manifest（仅当 --output-zip 且 --update-manifest 时）
        if args.update_manifest and zip_path and os.path.exists(zip_path):
            print("\n更新 update_manifest.json...")

            manifest_path = args.manifest_path
            if not manifest_path:
                manifest_path = os.path.join(root, "dist", "update_manifest.json")

            # 判断是否是跨版本升级
            is_cross = old_version != app_version

            # 优先从 ReleaseNote.md 读取 changelog，如果没有则使用命令行参数
            changelog = read_changelog_from_release_note(root, app_version, args.update_num)
            if not changelog and args.changelog:
                # 处理 changelog 参数（将 \n 替换为实际换行符）
                changelog = args.changelog.replace('\\n', '\n')

            # 更新 manifest
            manifest_success = update_manifest_json(
                manifest_path=manifest_path,
                version=app_version,
                update_num=args.update_num,
                zip_path=zip_path,
                from_version=old_version,
                is_cross_upgrade=is_cross,
                changelog=changelog
            )

            if manifest_success:
                print(f"  manifest 已更新: {manifest_path}")
            else:
                print(f"  警告: manifest 更新失败")
    
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
    
    # 输出总结
    print("\n" + "=" * 80)
    print("增量升级包创建成功!")
    print("=" * 80)
    print(f"\n输出目录: {output_dir}")
    print(f"ISS 脚本: {iss_output}")
    print(f"差异清单: {result.get('diff_manifest', '')}")
    print(f"\n文件统计:")
    print(f"  - 新增: {added_count} 个")
    print(f"  - 修改: {modified_count} 个")
    print(f"  - 删除: {deleted_count} 个")
    print(f"  - 总计: {added_count + modified_count + deleted_count} 个")
    print("\n下一步:")
    print("  1. 使用 Inno Setup 编译 ISS 脚本生成安装包")
    print("  2. 如需 zip 包，使用 --output-zip 参数重新运行")
    print("  3. 将安装包和差异清单上传到 GitHub Releases")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
