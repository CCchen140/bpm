import argparse
import importlib
import importlib.util
import os
import subprocess
import sys
import shutil
import re


def _prune_dist_tree(dist_dir: str):
    """
    清理打包后的目录，删除不必要的文件以减小体积
    注意：不删除 torch 相关的任何文件，避免导致 torch 无法加载
    """
    dist_dir = os.path.abspath(str(dist_dir or ""))
    if not dist_dir or not os.path.isdir(dist_dir):
        return

    # 只删除 __pycache__ 文件夹，不删除 torch 相关的任何文件
    for root, dirs, _ in os.walk(dist_dir):
        for d in dirs:
            if d == "__pycache__":
                pycache_path = os.path.join(root, d)
                try:
                    shutil.rmtree(pycache_path, ignore_errors=True)
                except Exception:
                    pass


def _write_build_flavor_marker(dist_dir: str, flavor: str):
    dist_dir = os.path.abspath(str(dist_dir or ""))
    if not dist_dir or not os.path.isdir(dist_dir):
        return
    try:
        v = str(flavor or "").strip().lower()
    except Exception:
        v = ""
    if v not in ("cpu", "gpu"):
        v = "cpu"
    marker = os.path.join(dist_dir, "build_flavor.txt")
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(v)
    except Exception:
        pass


def _get_module_origin(module_name: str) -> str:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return ""
    origin = getattr(spec, "origin", None)
    if isinstance(origin, str) and origin:
        return origin
    search_locations = getattr(spec, "submodule_search_locations", None)
    if search_locations:
        try:
            return str(next(iter(search_locations), "") or "")
        except Exception:
            return ""
    return ""


def _verify_packaging_environment(flavor: str):
    pyinstaller_origin = _get_module_origin("PyInstaller")
    if not pyinstaller_origin:
        raise RuntimeError(
            "当前 Python 环境未安装 PyInstaller。\n"
            f"解释器: {sys.executable}\n"
            "请先在用于打包的同一个 Python 环境中安装 PyInstaller。"
        )

    print(f"[打包环境] Python: {sys.executable}")
    print(f"[打包环境] PyInstaller: {pyinstaller_origin}")

    required_modules = [
        ("qtawesome", "UI 图标"),
        ("pypinyin", "拼音排序"),
        ("PyQt6.QtWebEngineWidgets", "地图/WebEngine"),
        ("torch", f"{str(flavor or 'cpu').upper()} 推理"),
        ("ultralytics", "YOLO 推理"),
    ]

    missing: list[str] = []
    for module_name, usage in required_modules:
        origin = _get_module_origin(module_name)
        if not origin:
            missing.append(f"{module_name} ({usage})")
            continue
        print(f"[打包环境] {module_name}: {origin}")

    if missing:
        missing_txt = "\n".join(f"  - {item}" for item in missing)
        raise RuntimeError(
            "当前用于打包的 Python 环境缺少关键依赖，继续打包会导致程序运行时缺图标、缺拼音排序或模型不可用。\n"
            f"解释器: {sys.executable}\n"
            "缺失依赖:\n"
            f"{missing_txt}\n"
            "请确认你执行 `build/build.py` 的解释器，就是安装这些依赖的同一个 Python 环境。"
        )


def _walk_dist_files(root_dir: str) -> dict[str, tuple[str, int, int]]:
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
            # 忽略系统文件和 .pyc 文件
            name_lower = str(name).lower()
            if name_lower in ("thumbs.db", "desktop.ini"):
                continue
            if name_lower.endswith(".pyc"):
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


def _hash_file(path: str, max_bytes: int = 64 * 1024 * 1024) -> str:
    import hashlib

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


def _compute_delta_files(old_dist_dir: str, new_dist_dir: str) -> dict[str, list[str]]:
    """
    计算两个版本之间的差异文件
    
    返回:
        {
            "added": [新增文件列表],
            "modified": [修改文件列表],
            "deleted": [删除文件列表]
        }
    """
    old_map = _walk_dist_files(old_dist_dir)
    new_map = _walk_dist_files(new_dist_dir)
    
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    
    # 检查新增和修改的文件
    for rel, (new_abs, new_size, new_mtime) in new_map.items():
        old = old_map.get(rel)
        if old is None:
            # 新文件
            added.append(rel)
            continue
        _, old_size, old_mtime = old
        if int(old_size) != int(new_size):
            # 大小不同，已修改
            modified.append(rel)
            continue
        if int(old_mtime) == int(new_mtime):
            # 时间戳相同，未修改
            continue
        # 时间戳不同，需要比较哈希
        old_hash = _hash_file(old[0])
        new_hash = _hash_file(new_abs)
        if old_hash and new_hash:
            if old_hash != new_hash:
                modified.append(rel)
            continue
        # 无法比较哈希，认为已修改
        modified.append(rel)
    
    # 检查删除的文件（在旧版本中存在但在新版本中不存在）
    for rel in old_map.keys():
        if rel not in new_map:
            deleted.append(rel)
    
    added.sort()
    modified.sort()
    deleted.sort()
    
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted
    }


def _rewrite_inno_files_section(iss_path: str, new_dist_dir: str, delta_files: dict[str, list[str]]):
    """
    重写 iss 文件的 [Files] 段，处理新增、修改、删除的文件
    
    Args:
        iss_path: iss 文件路径
        new_dist_dir: 新版本 dist 目录
        delta_files: 差异文件字典，包含 added、modified、deleted 三个列表
    """
    iss_path = os.path.abspath(str(iss_path or ""))
    if not iss_path or not os.path.isfile(iss_path):
        raise FileNotFoundError(iss_path)
    new_dist_dir = os.path.abspath(str(new_dist_dir or ""))
    if not new_dist_dir or not os.path.isdir(new_dist_dir):
        raise FileNotFoundError(new_dist_dir)
    try:
        with open(iss_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        with open(iss_path, "r", encoding="gbk", errors="ignore") as f:
            lines = f.read().splitlines()

    files_start = -1
    files_end = -1
    for i, line in enumerate(lines):
        if str(line).strip().lower() == "[files]":
            files_start = i
            continue
        if files_start >= 0 and i > files_start:
            if str(line).startswith("[") and str(line).endswith("]"):
                files_end = i
                break
    if files_start < 0:
        raise RuntimeError("未在 .iss 中找到 [Files] 段")
    if files_end < 0:
        files_end = len(lines)

    new_block: list[str] = []
    
    # 处理新增的文件
    added = delta_files.get("added", [])
    if added:
        new_block.append("; 新增的文件")
        for rel in added:
            rel = str(rel or "").strip().lstrip("\\/").replace("/", "\\")
            if not rel:
                continue
            abs_src = os.path.join(new_dist_dir, rel)
            if not os.path.isfile(abs_src):
                continue
            dest_sub = os.path.dirname(rel).replace("/", "\\")
            if dest_sub:
                dest = r"{app}\\" + dest_sub
            else:
                dest = r"{app}"
            src = r"{#MyAppDistDir}\\" + rel
            new_block.append(f'Source: "{src}"; DestDir: "{dest}"; Flags: ignoreversion')
        new_block.append("")
    
    # 处理修改的文件
    modified = delta_files.get("modified", [])
    if modified:
        new_block.append("; 修改的文件")
        for rel in modified:
            rel = str(rel or "").strip().lstrip("\\/").replace("/", "\\")
            if not rel:
                continue
            abs_src = os.path.join(new_dist_dir, rel)
            if not os.path.isfile(abs_src):
                continue
            dest_sub = os.path.dirname(rel).replace("/", "\\")
            if dest_sub:
                dest = r"{app}\\" + dest_sub
            else:
                dest = r"{app}"
            src = r"{#MyAppDistDir}\\" + rel
            new_block.append(f'Source: "{src}"; DestDir: "{dest}"; Flags: ignoreversion')
        new_block.append("")
    
    # 处理删除的文件（在 [InstallDelete] 段中添加）
    deleted = delta_files.get("deleted", [])
    if deleted:
        new_block.append("; 注意：以下文件将在 [InstallDelete] 段中删除")
        for rel in deleted:
            rel = str(rel or "").strip().lstrip("\\/").replace("/", "\\")
            new_block.append(f"; 删除: {rel}")
        new_block.append("")

    lines_out = lines[: files_start + 1] + new_block + lines[files_end:]
    
    # 添加 [InstallDelete] 段处理删除的文件
    if deleted:
        lines_out = _add_install_delete_section(lines_out, deleted)
    
    try:
        with open(iss_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines_out) + "\n")
    except Exception:
        with open(iss_path, "w", encoding="gbk", errors="ignore", newline="\n") as f:
            f.write("\n".join(lines_out) + "\n")


def _add_install_delete_section(lines: list[str], deleted_files: list[str]) -> list[str]:
    """
    添加或更新 [InstallDelete] 段，用于删除旧版本中不再需要的文件
    
    Args:
        lines: iss 文件的行列表
        deleted_files: 需要删除的文件列表
    
    Returns:
        更新后的行列表
    """
    # 查找 [InstallDelete] 段的位置
    install_delete_start = -1
    install_delete_end = -1
    files_section_start = -1
    
    for i, line in enumerate(lines):
        line_lower = str(line).strip().lower()
        if line_lower == "[installdelete]":
            install_delete_start = i
            continue
        if line_lower == "[files]":
            files_section_start = i
            continue
        if install_delete_start >= 0 and i > install_delete_start:
            if str(line).startswith("[") and str(line).endswith("]"):
                install_delete_end = i
                break
    
    # 构建删除指令列表
    delete_lines = ["; 删除旧版本中不再需要的文件"]
    for rel in deleted_files:
        rel = str(rel or "").strip().lstrip("\\/").replace("/", "\\")
        if not rel:
            continue
        # 使用 {app} 常量表示安装目录
        delete_lines.append(f'Type: files; Name: "{{app}}\\{rel}"')
    
    if install_delete_start >= 0:
        # 已存在 [InstallDelete] 段，替换内容
        if install_delete_end < 0:
            install_delete_end = len(lines)
        lines_out = lines[:install_delete_start + 1] + delete_lines + lines[install_delete_end:]
    else:
        # 不存在 [InstallDelete] 段，在 [Files] 段之前插入
        if files_section_start >= 0:
            lines_out = lines[:files_section_start] + ["[InstallDelete]"] + delete_lines + [""] + lines[files_section_start:]
        else:
            # 如果没有 [Files] 段，添加到文件末尾
            lines_out = lines + ["", "[InstallDelete]"] + delete_lines
    
    return lines_out


def _update_iss_version_info(iss_path: str, from_version: str, to_version: str):
    """更新 iss 文件的来源版本信息（用于增量包）"""
    iss_path = os.path.abspath(str(iss_path or ""))
    if not iss_path or not os.path.isfile(iss_path):
        return
    
    try:
        with open(iss_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        with open(iss_path, "r", encoding="gbk", errors="ignore") as f:
            content = f.read()
    
    # 更新 MyAppFromVersion
    from_v = str(from_version or "").strip()
    if from_v:
        # 移除版本号前的 V/v
        from_v_clean = from_v
        if from_v_clean.lower().startswith('v'):
            from_v_clean = from_v_clean[1:]
        
        # 替换 #define MyAppFromVersion
        import re
        pattern = r'(#define MyAppFromVersion\s+")([^"]*)"'
        replacement = r'\g<1>' + from_v_clean + '"'
        content = re.sub(pattern, replacement, content)
    
    try:
        with open(iss_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except Exception:
        with open(iss_path, "w", encoding="gbk", errors="ignore", newline="\n") as f:
            f.write(content)


def _write_delta_report(report_path: str, old_dist_dir: str, new_dist_dir: str, delta_files: dict):
    """生成增量包文件列表报告"""
    report_path = os.path.abspath(str(report_path or ""))
    if not report_path:
        return
    
    added = delta_files.get("added", [])
    modified = delta_files.get("modified", [])
    deleted = delta_files.get("deleted", [])
    
    lines = []
    lines.append("=" * 80)
    lines.append("BirdPictureManager 增量升级包文件列表")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"旧版本目录: {os.path.abspath(str(old_dist_dir or ''))}")
    lines.append(f"新版本目录: {os.path.abspath(str(new_dist_dir or ''))}")
    lines.append(f"新增文件数: {len(added)}")
    lines.append(f"修改文件数: {len(modified)}")
    lines.append(f"删除文件数: {len(deleted)}")
    lines.append(f"总计: {len(added) + len(modified) + len(deleted)} 个文件")
    lines.append("")
    
    # 新增的文件
    if added:
        lines.append("-" * 80)
        lines.append(f"新增的文件 ({len(added)} 个):")
        lines.append("-" * 80)
        for i, rel_path in enumerate(added, 1):
            new_abs = os.path.join(new_dist_dir, rel_path)
            try:
                size = os.path.getsize(new_abs)
                size_str = _format_size(size)
            except Exception:
                size_str = "未知"
            lines.append(f"{i:4d}. [新增] {rel_path} ({size_str})")
        lines.append("")
    
    # 修改的文件
    if modified:
        lines.append("-" * 80)
        lines.append(f"修改的文件 ({len(modified)} 个):")
        lines.append("-" * 80)
        for i, rel_path in enumerate(modified, 1):
            new_abs = os.path.join(new_dist_dir, rel_path)
            try:
                size = os.path.getsize(new_abs)
                size_str = _format_size(size)
            except Exception:
                size_str = "未知"
            lines.append(f"{i:4d}. [修改] {rel_path} ({size_str})")
        lines.append("")
    
    # 删除的文件
    if deleted:
        lines.append("-" * 80)
        lines.append(f"删除的文件 ({len(deleted)} 个):")
        lines.append("-" * 80)
        for i, rel_path in enumerate(deleted, 1):
            lines.append(f"{i:4d}. [删除] {rel_path}")
        lines.append("")
    
    lines.append("=" * 80)
    lines.append(f"生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 80)
    
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    try:
        size_bytes = int(size_bytes)
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    except Exception:
        return "未知"


def _validate_torch_flavor(flavor: str):
    v = str(flavor or "").strip().lower()
    if v not in ("cpu", "gpu"):
        return
    try:
        import torch  # type: ignore
    except Exception as e:
        raise RuntimeError(f"未检测到 torch，无法打包 {v.upper()} 版本：{e}") from e
    try:
        cuda_ver = getattr(getattr(torch, "version", None), "cuda", None)
    except Exception:
        cuda_ver = None
    try:
        ver_txt = str(getattr(torch, "__version__", "") or "")
    except Exception:
        ver_txt = ""
    is_cpu_build = (cuda_ver is None) and ("+cpu" in ver_txt.lower())
    is_cuda_build = (cuda_ver is not None)
    if v == "cpu":
        if is_cuda_build:
            raise RuntimeError(
                "当前环境的 torch 是 CUDA 版，打包 CPU 安装包会把 CUDA 依赖整套打进去，导致体积暴涨。\n"
                "请使用 CPU 版 torch 的 Python 环境再执行构建。"
            )
        return
    if v == "gpu":
        if not is_cuda_build:
            raise RuntimeError(
                "当前环境的 torch 不是 CUDA 版，打包 GPU 安装包无法获得 GPU 加速。\n"
                "请使用 CUDA 版 torch 的 Python 环境再执行构建。"
            )
        return


def main():
    parser = argparse.ArgumentParser(
        description="BirdPictureManager 打包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 完整包打包
  python build/build.py
  
  # 增量升级包打包（旧方式，修改 iss 文件）
  python build/build.py --delta-from "dist/qitu_V1.0.0" --from-version "V1.0.0"
  
  # 使用 build_delta 创建升级包（推荐）
  python build/build.py --delta-from "dist/qitu_V1.0.0" --delta
  
  # 完整发布流程（打包 → 创建差分包 → 生成zip → 更新manifest）
  python build/build.py u1 --delta-from "dist/qitu_V0.0.4_fr" --complete
  
  # CPU/GPU 版本打包
  python build/build.py --flavor cpu
  python build/build.py --flavor gpu
  
  # 混淆打包
  python build/build.py --obf
        """
    )
    parser.add_argument("suffix", nargs="?", default="", help="文件名后缀（如: beta, rc1）")
    parser.add_argument("--obf", action="store_true", help="启用代码混淆（需要 pyarmor）")
    parser.add_argument("--flavor", choices=["cpu", "gpu"], default="", help="PyTorch 版本类型")
    parser.add_argument("--delta-from", dest="delta_from", default="", help="增量包：旧版本 dist 目录路径")
    parser.add_argument("--from-version", dest="from_version", default="", help="增量包：来源版本号（如: V1.0.0）")
    parser.add_argument("--full", action="store_true", help="强制打包完整包（忽略 --delta-from）")
    parser.add_argument("--delta", action="store_true", help="使用 build_delta.py 创建升级包（需要 --delta-from）")
    parser.add_argument("--complete", action="store_true", help="完整发布流程：打包 → 创建差分包 → 生成zip → 更新manifest（需要 --delta-from）")
    parser.add_argument("--package", action="store_true", help="打包并生成安装包：打包 → 创建差分包 → 生成安装包（不生成zip，需要 --delta-from）")
    args = parser.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
    except Exception:
        pass

    # 自动从代码中读取update版本号
    try:
        from utils.system.app_info_manager import APP_UPDATE
        # 如果APP_UPDATE不为空，提取数字部分作为suffix
        if APP_UPDATE:
            # 支持格式: "update1" -> "update1", "u1" -> "u1"
            update_str = str(APP_UPDATE).strip()
            # 如果用户没有手动指定suffix，则使用代码中的版本
            if not args.suffix and update_str:
                args.suffix = update_str
                print(f"[自动检测] 从代码中读取到update版本: {APP_UPDATE}")
    except Exception as e:
        print(f"[警告] 无法从代码读取update版本: {e}")
        pass

    spec_path = os.path.join(root, "build", "bird_picture_manager.spec")
    icon_gen = os.path.join(root, "build", "generate_icon.py")

    suffix = str(args.suffix or "").strip()
    flavor = str(getattr(args, "flavor", "") or "").strip().lower()
    # 如果没有指定flavor，默认使用gpu
    if not flavor:
        flavor = "gpu"
    try:
        _validate_torch_flavor(flavor)
    except Exception:
        raise

    try:
        subprocess.check_call([sys.executable, icon_gen], cwd=root)
    except Exception:
        pass

    try:
        import PyQt6.QtWebEngineWidgets
        import PyQt6.QtWebEngineCore
        import PyQt6.QtWebChannel
    except Exception as e:
        raise RuntimeError(
            "未检测到 PyQt6-WebEngine（或其依赖无法加载），打包后地图会不可用。\n"
            "请在用于打包的 Python 环境中安装：pip install -i https://mirrors.aliyun.com/pypi/simple PyQt6-WebEngine"
        ) from e

    env = os.environ.copy()
    env["BPM_PROJECT_ROOT"] = root
    env["BPM_BUILD_DIR"] = os.path.join(root, "build")
    env["BPM_BUILD_FLAVOR"] = flavor
    if suffix:
        env["BPM_NAME_SUFFIX"] = suffix
    else:
        env.pop("BPM_NAME_SUFFIX", None)

    if args.obf:
        obf_dir = os.path.join(root, "build", "obf_src")
        if os.path.exists(obf_dir):
            shutil.rmtree(obf_dir, ignore_errors=True)
        os.makedirs(obf_dir, exist_ok=True)

        pyarmor_cmd = None
        for c in (["pyarmor"], [sys.executable, "-m", "pyarmor"]):
            try:
                subprocess.check_call(c + ["--version"], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                pyarmor_cmd = c
                break
            except Exception:
                continue
        if pyarmor_cmd is None:
            raise RuntimeError("未找到 pyarmor（请先安装 pyarmor，或关闭 --obf）")

        targets = ["main.py", "cache", "core", "ui", "utils"]
        subprocess.check_call(pyarmor_cmd + ["gen", "-r", "-O", obf_dir] + targets, cwd=root)

        env["BPM_SOURCE_ROOT"] = obf_dir
        env["BPM_ENTRY"] = os.path.join(obf_dir, "main.py")

    try:
        from utils.system.app_info_manager import APP_NAME, APP_VERSION

        app_name = str(APP_NAME or "BirdPictureManager")
        app_version = str(APP_VERSION or "V0.0.1")
    except Exception:
        app_name = "BirdPictureManager"
        app_version = "V0.0.1"

    # 构建版本号（移除 V/v 前缀）
    v_token = str(app_version or "").strip()
    if v_token:
        v_token = re.sub(r"[^0-9A-Za-z_.\\-]+", "_", v_token)
        # 移除版本号前的 V/v
        if v_token.lower().startswith('v'):
            v_token = v_token[1:]
    
    suffix_token = str(suffix or "").strip()

    # 构建 dist 目录名称
    # 完整包（不带update参数）：qitu_Vx.x.x_fr
    # update包（带update参数）：qitu_Vx.x.x_ux
    dist_name = "qitu"
    if v_token:
        dist_name = f"{dist_name}_V{v_token}"
    if suffix_token:
        # 如果suffix是update编号格式（如update1, u1），统一转换为u格式（完整包使用u1）
        if suffix_token.lower().startswith('update') and suffix_token[6:].isdigit():
            # update1 -> _u1
            dist_name = f"{dist_name}_u{suffix_token[6:]}"
        elif suffix_token.startswith('u') and suffix_token[1:].isdigit():
            # u1 -> _u1
            dist_name = f"{dist_name}_{suffix_token}"
        else:
            dist_name = f"{dist_name}_{suffix_token}"
    else:
        # 完整包默认添加 fr (full release) 后缀
        dist_name = f"{dist_name}_fr"
    
    # 保存原始 app_name 用于后续（如需要）
    original_app_name = app_name

    dist_dir = os.path.join(root, "dist", dist_name)
    if os.path.isdir(dist_dir):
        try:
            shutil.rmtree(dist_dir)
        except Exception as e:
            raise RuntimeError(f"无法清理旧的打包目录：{dist_dir}\n请先关闭正在运行的程序/资源管理器占用后重试。") from e

    workpath = os.path.join(root, "build", "_pyi_work", dist_name)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        os.path.join(root, "dist"),
        "--workpath",
        workpath,
        spec_path,
    ]
    code = subprocess.call(cmd, cwd=root, env=env)
    if int(code) == 0:
        try:
            _prune_dist_tree(dist_dir)
        except Exception:
            pass
        try:
            _write_build_flavor_marker(dist_dir, flavor)
        except Exception:
            pass
        delta_from = str(getattr(args, "delta_from", "") or "").strip()
        from_version = str(getattr(args, "from_version", "") or "").strip()
        is_full = bool(getattr(args, "full", False))
        is_complete = bool(getattr(args, "complete", False))
        is_package = bool(getattr(args, "package", False))
        
        print(f"\n[打包] delta_from={delta_from}")
        print(f"[打包] from_version={from_version}")
        print(f"[打包] is_full={is_full}")
        print(f"[打包] is_complete={is_complete}")
        print(f"[打包] is_package={is_package}")
        
        # 处理完整发布流程（--complete）
        if is_complete and delta_from:
            print("\n[完整发布流程] 开始执行...")
            delta_from_abs = os.path.abspath(delta_from)
            
            if not os.path.isdir(delta_from_abs):
                print(f"[完整发布流程] 错误: 旧版本目录不存在: {delta_from_abs}")
                print(f"[完整发布流程] 将只生成完整包")
            else:
                try:
                    delta_script = os.path.join(root, "build", "build_delta.py")
                    if not os.path.exists(delta_script):
                        print(f"[完整发布流程] 错误: build_delta.py 不存在: {delta_script}")
                    else:
                        # 提取update编号（从suffix）
                        update_num = ""
                        if suffix:
                            if suffix.lower().startswith('update') and suffix[6:].isdigit():
                                update_num = suffix[6:]
                            elif suffix.startswith('u') and suffix[1:].isdigit():
                                update_num = suffix[1:]
                        if not update_num:
                            update_num = "1"  # 默认update 1
                        
                        # 构建完整发布命令（包含 --output-zip 和 --update-manifest）
                        delta_cmd = [
                            sys.executable,
                            delta_script,
                            "--from", delta_from_abs,
                            "--to", dist_dir,
                            "--version", app_version,
                            "--flavor", flavor,
                            "--update", update_num,
                            "--output-zip",
                            "--update-manifest"
                        ]
                        
                        print(f"[完整发布流程] 执行: {' '.join(delta_cmd)}")
                        subprocess.check_call(delta_cmd, cwd=root)
                        print("\n[完整发布流程] 执行成功！")
                        print(f"[完整发布流程] 生成的文件:")
                        print(f"  - 安装包: build/installer/")
                        print(f"  - ZIP包: dist/qitu_V{app_version}_update{update_num}.zip")
                        print(f"  - Manifest: dist/update_manifest.json")
                except Exception as e:
                    print(f"[完整发布流程] 执行失败: {e}")
                    import traceback
                    traceback.print_exc()
        # 处理打包并生成安装包流程（--package）
        elif is_package and delta_from:
            print("\n[打包并生成安装包] 开始执行...")
            delta_from_abs = os.path.abspath(delta_from)
            
            if not os.path.isdir(delta_from_abs):
                print(f"[打包并生成安装包] 错误: 旧版本目录不存在: {delta_from_abs}")
                print(f"[打包并生成安装包] 将只生成完整包")
            else:
                try:
                    delta_script = os.path.join(root, "build", "build_delta.py")
                    if not os.path.exists(delta_script):
                        print(f"[打包并生成安装包] 错误: build_delta.py 不存在: {delta_script}")
                    else:
                        # 提取update编号（从suffix或自动检测）
                        update_num = ""
                        if suffix:
                            if suffix.lower().startswith('update') and suffix[6:].isdigit():
                                update_num = suffix[6:]
                            elif suffix.startswith('u') and suffix[1:].isdigit():
                                update_num = suffix[1:]
                        if not update_num:
                            update_num = "1"  # 默认update 1
                        
                        # 构建打包命令（使用 --setup 生成安装包，不生成zip）
                        delta_cmd = [
                            sys.executable,
                            delta_script,
                            "--from", delta_from_abs,
                            "--to", dist_dir,
                            "--version", app_version,
                            "--flavor", flavor,
                            "--update", update_num,
                            "--setup"  # 只生成安装包，不创建zip
                        ]
                        
                        print(f"[打包并生成安装包] 执行: {' '.join(delta_cmd)}")
                        subprocess.check_call(delta_cmd, cwd=root)
                        print("\n[打包并生成安装包] 执行成功！")
                        print(f"[打包并生成安装包] 生成的文件:")
                        print(f"  - 安装包: build/installer/")
                        print(f"  - 差异包: dist/qitu_V{app_version}_update{update_num}/")
                except Exception as e:
                    print(f"[打包并生成安装包] 执行失败: {e}")
                    import traceback
                    traceback.print_exc()
        elif delta_from and not is_full:
            # 检查旧版本目录是否存在
            delta_from_abs = os.path.abspath(delta_from)
            print(f"[打包] 检查旧版本目录: {delta_from_abs}")
            
            if not os.path.isdir(delta_from_abs):
                print(f"[增量包] 错误: 旧版本目录不存在: {delta_from_abs}")
                print(f"[增量包] 将生成完整包而不是增量包")
            else:
                # 统一使用 build_delta.py 创建升级包，避免依赖缺失的旧版 installer 模板
                if bool(getattr(args, "delta", False)):
                    print("\n[升级包] 使用 build_delta.py 创建升级包...")
                else:
                    print("\n[升级包] 旧版 ISS 增量模式已停用，自动切换为 build_delta.py ...")
                try:
                    delta_script = os.path.join(root, "build", "build_delta.py")
                    if not os.path.exists(delta_script):
                        print(f"[升级包] 错误: build_delta.py 不存在: {delta_script}")
                    else:
                        # 构建命令行参数
                        delta_cmd = [
                            sys.executable,
                            delta_script,
                            "--from", delta_from_abs,
                            "--to", dist_dir,
                            "--version", app_version,
                            "--flavor", flavor
                        ]
                        
                        print(f"[升级包] 执行: {' '.join(delta_cmd)}")
                        subprocess.check_call(delta_cmd, cwd=root)
                        print("\n[升级包] 创建成功！")
                except Exception as e:
                    print(f"[升级包] 创建失败: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            if not delta_from:
                print("[打包] 未指定 --delta-from，生成完整包")
            if is_full:
                print("[打包] 使用 --full 参数，强制生成完整包")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
