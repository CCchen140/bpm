#!/usr/bin/env python3
"""BirdPictureManager 增量升级包打包脚本

使用方法:
    python build/build_delta.py --from "dist/V0.0.4" --to "dist/V0.0.5" --version "0.0.5" --update 1

参数:
    --from: 旧版本 dist 目录路径
    --to: 新版本 dist 目录路径（默认为最新版本）
    --version: 升级包版本号
    --update: update 编号，默认 1
    --output-zip: 输出为 zip 压缩包（GitHub 发布用）
    --update-manifest: 同时更新 update_manifest.json

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


def _select_latest_dist_dir(dist_root: str) -> str:
    """选择最新的 dist 目录"""
    candidates: list[tuple[tuple, str]] = []
    for name in os.listdir(dist_root):
        full = os.path.join(dist_root, name)
        if not os.path.isdir(full):
            continue
        # 支持两种格式: qitu_V0.0.4 (旧) 或 V0.0.4 (新)
        if not (str(name).startswith("qitu_V") or str(name).startswith("V")):
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


def compute_delta_files(old_dist_dir: str, new_dist_dir: str) -> dict:
    """计算两个版本之间的差异文件"""
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
    
    return {
        "copied": copied_files,
        "deleted": deleted_files,
        "output_dir": output_dir
    }


def create_zip_package(source_dir: str, zip_path: str) -> bool:
    """
    将升级包目录打包为 zip 文件
    
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
    parser.add_argument("--output-zip", action="store_true", help="输出为 zip 压缩包")
    parser.add_argument("--update-manifest", action="store_true", help="同时更新 update_manifest.json")
    parser.add_argument("--manifest-path", default="", help="manifest.json 文件路径（默认: dist/update_manifest.json）")
    parser.add_argument("--changelog", default="", help="更新日志内容（支持 \\n 换行）")
    args = parser.parse_args()
    
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # 解析旧版本目录
    old_dist_dir = os.path.abspath(args.from_dir)
    if not os.path.isdir(old_dist_dir):
        print(f"错误: 旧版本目录不存在: {old_dist_dir}")
        return 1
    
    print(f"旧版本目录: {old_dist_dir}")
    
    # 提取旧版本号
    old_version = _extract_version_from_dist_name(os.path.basename(old_dist_dir))
    print(f"旧版本号: {old_version}")

    # 解析新版本目录
    if args.to_dir:
        new_dist_dir = os.path.abspath(args.to_dir)
    else:
        dist_root = os.path.join(root, "dist")
        if not os.path.isdir(dist_root):
            print(f"错误: dist 目录不存在: {dist_root}")
            return 1
        new_dist_dir = _select_latest_dist_dir(dist_root)
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
        dir_name = os.path.basename(new_dist_dir)
        if "_V" in dir_name:
            parts = dir_name.split("_V")
            if len(parts) >= 2:
                app_version = parts[1].split("_")[0]
            else:
                app_version = "1.0.0"
        else:
            app_version = "1.0.0"
    
    print(f"新版本号: {app_version}")
    
    # 获取 flavor
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
    v_token = str(app_version or "").strip()
    if v_token.upper().startswith('V'):
        v_token = v_token[1:]
    
    if args.output_dir:
        output_dir = os.path.abspath(args.output_dir)
    else:
        output_dir = os.path.join(root, "dist", f"qitu_V{v_token}_update{args.update_num}")
    
    print(f"\n创建差分升级包...")
    print(f"输出目录: {output_dir}")
    
    result = create_delta_package(old_dist_dir, new_dist_dir, output_dir, delta_files, app_flavor)
    
    # 生成 ISS 脚本（传统方式）
    print("\n生成安装脚本...")
    iss_output = os.path.join(root, "build", "installer", f"update_V{v_token}_update{args.update_num}.iss")
    # ISS 脚本生成代码保留...
    
    # 生成 zip 压缩包
    zip_path = ""
    parts_info = []
    if args.output_zip:
        print("\n创建 zip 压缩包...")
        zip_filename = f"qitu_V{v_token}_update{args.update_num}.zip"
        zip_path = os.path.join(root, "dist", zip_filename)
        
        if create_zip_package(output_dir, zip_path):
            print(f"Zip 包: {zip_path}")
            
            # 计算并显示哈希
            file_hash = calculate_sha256(zip_path)
            file_size = get_file_size(zip_path)
            print(f"文件大小: {file_size:,} 字节 ({file_size / (1024*1024*1024):.2f} GB)")
            print(f"SHA256: {file_hash}")
            
            # 检查是否需要分包
            needs_split, parts_info = split_large_package(zip_path, os.path.dirname(zip_path))
            if needs_split:
                print(f"\n⚠ 注意: 文件已分包，需要将以下文件上传到 GitHub Releases:")
                print(f"  1. {os.path.basename(zip_path)} (原始文件，可选)")
                for part in parts_info:
                    print(f"  2. {part['filename']} (必须)")
        else:
            print("创建 zip 包失败")
            return 1
    
    # 更新 manifest
    if args.update_manifest and zip_path:
        print("\n更新 update_manifest.json...")
        
        manifest_path = args.manifest_path
        if not manifest_path:
            manifest_path = os.path.join(root, "dist", "update_manifest.json")
        
        # 判断是否是跨版本升级
        is_cross = old_version != app_version
        
        # 处理 changelog 参数（将 \n 替换为实际换行符）
        changelog = args.changelog.replace('\\n', '\n') if args.changelog else ""
        
        # 如果是跨版本升级（完整包）且需要分包，调用分包脚本处理
        if is_cross and parts_info:
            print("  检测到完整包需要分包，调用分包脚本处理...")
            import subprocess
            split_script = os.path.join(root, "build", "split_package.py")
            split_cmd = [
                sys.executable,
                split_script,
                "--file", zip_path,
                "--manifest", manifest_path
            ]
            try:
                result = subprocess.run(split_cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"  ✓ 分包脚本执行成功")
                    print(f"Manifest 已更新: {manifest_path}")
                else:
                    print(f"  ✗ 分包脚本执行失败")
                    if result.stderr:
                        print(f"  错误: {result.stderr}")
            except Exception as e:
                print(f"  ✗ 调用分包脚本失败: {e}")
                print("  尝试直接更新 manifest...")
                # 回退到直接更新
                if update_manifest_json(
                    manifest_path,
                    app_version,
                    args.update_num,
                    zip_path,
                    old_version,
                    is_cross,
                    changelog,
                    parts_info
                ):
                    print(f"Manifest 已更新: {manifest_path}")
        else:
            # 增量更新包直接更新 manifest
            if update_manifest_json(
                manifest_path,
                app_version,
                args.update_num,
                zip_path,
                old_version,
                is_cross,
                changelog,
                parts_info if parts_info else None
            ):
                print(f"Manifest 已更新: {manifest_path}")
            else:
                print("更新 manifest 失败")
    
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
    if args.output_zip:
        print(f"Zip 包: {zip_path}")
    print(f"\n文件统计:")
    print(f"  - 新增: {added_count} 个")
    print(f"  - 修改: {modified_count} 个")
    print(f"  - 删除: {deleted_count} 个")
    print(f"  - 总计: {added_count + modified_count + deleted_count} 个")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
