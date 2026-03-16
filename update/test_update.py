#!/usr/bin/env python3
"""
栖图自动升级系统 - 测试脚本

用于测试自动升级功能，打印从仓库获取的版本信息

使用方法:
    python update/test_update.py
    
    # 测试模式（使用模拟版本）
    python update/test_update.py --test
"""

import os
import sys
import json
import argparse
from typing import Optional, Dict, List

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update import update_config as config
from update.update_checker import UpdateChecker, VersionInfo


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_section(title: str):
    """打印小节标题"""
    print(f"\n{'─' * 80}")
    print(f" {title}")
    print("─" * 80)


def fetch_manifest() -> Optional[Dict]:
    """
    从 GitHub 获取 update_manifest.json
    
    返回:
        manifest 字典或 None
    """
    import urllib.request
    import urllib.error
    
    try:
        url = config.UPDATE_MANIFEST_URL
        print(f"正在获取: {url}")
        
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'BirdPictureManager-UpdateTest/1.0',
                'Accept': 'application/json'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read().decode('utf-8')
            return json.loads(data)
            
    except urllib.error.HTTPError as e:
        print(f"HTTP 错误: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"网络错误: {e.reason}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}")
        return None
    except Exception as e:
        print(f"获取失败: {e}")
        return None


def print_version_list(manifest: Dict):
    """打印版本列表"""
    print_section("版本列表")
    
    releases = manifest.get("releases", {})
    if not releases:
        print("  未找到任何版本")
        return
    
    # 按版本号排序
    sorted_versions = sorted(
        releases.keys(),
        key=lambda v: VersionInfo(v)
    )
    
    print(f"\n  共 {len(sorted_versions)} 个基础版本:\n")
    
    for base_version in sorted_versions:
        release_info = releases[base_version]
        print(f"  📦 V{base_version}")
        
        # 显示跨版本升级包
        cross_upgrade = release_info.get("cross_upgrade", {})
        if cross_upgrade:
            from_base = cross_upgrade.get("from_base", "未知")
            package = cross_upgrade.get("package", "")
            size = cross_upgrade.get("size", 0)
            hash_val = cross_upgrade.get("hash", "")[:16] + "..." if cross_upgrade.get("hash") else ""
            is_split = cross_upgrade.get("is_split", False)
            print(f"     └─ 跨版本升级: 从 V{from_base}")
            print(f"        包名: {package}")
            print(f"        大小: {format_size(size)}")
            print(f"        哈希: {hash_val}")
            if is_split:
                parts = cross_upgrade.get("parts", [])
                print(f"        分包: {len(parts)} 个")
                for part in parts:
                    print(f"          - {part.get('filename', '')} ({format_size(part.get('size', 0))})")
        
        # 显示 update 版本
        updates = release_info.get("updates", {})
        if updates:
            sorted_updates = sorted(updates.keys(), key=int)
            for update_num in sorted_updates:
                update_info = updates[update_num]
                version = update_info.get("version", f"{base_version}_update{update_num}")
                package = update_info.get("package", "")
                size = update_info.get("size", 0)
                hash_val = update_info.get("hash", "")[:16] + "..." if update_info.get("hash") else ""
                is_split = update_info.get("is_split", False)
                print(f"     └─ {version}")
                print(f"        包名: {package}")
                print(f"        大小: {format_size(size)}")
                print(f"        哈希: {hash_val}")
                if is_split:
                    parts = update_info.get("parts", [])
                    print(f"        分包: {len(parts)} 个")
                    for part in parts:
                        print(f"          - {part.get('filename', '')} ({format_size(part.get('size', 0))})")
        
        print()


def print_latest_version(manifest: Dict):
    """打印最新版本信息"""
    print_section("最新版本")
    
    latest = manifest.get("latest_version", "未知")
    release_date = manifest.get("release_date", "未知")
    
    print(f"\n  最新版本: V{latest}")
    print(f"  发布日期: {release_date}")
    
    # 查找最新版本的详细信息
    releases = manifest.get("releases", {})
    for base_version, release_info in releases.items():
        # 检查是否是基础版本
        if base_version == latest.split("_update")[0]:
            updates = release_info.get("updates", {})
            # 查找匹配的 update
            for update_num, update_info in updates.items():
                if update_info.get("version") == latest:
                    print(f"\n  包名: {update_info.get('package', 'N/A')}")
                    print(f"  大小: {format_size(update_info.get('size', 0))}")
                    print(f"  哈希: {update_info.get('hash', 'N/A')}")
                    break
            break


def print_upgrade_path(manifest: Dict, current_version: str, target_version: str):
    """打印升级路径"""
    print_section(f"升级路径计算")
    print(f"\n  当前版本: V{current_version}")
    print(f"  目标版本: V{target_version}")

    checker = UpdateChecker()

    try:
        upgrade_steps = checker.calculate_upgrade_path(
            current_version,
            target_version,
            manifest
        )

        if not upgrade_steps:
            print("\n  ❌ 无法计算升级路径")
            return

        print(f"\n  升级步骤 ({len(upgrade_steps)} 步):\n")

        total_size = 0
        for step in upgrade_steps:
            step_num = step.get("step", 0)
            from_ver = step.get("from", "")
            to_ver = step.get("to", "")
            package = step.get("package", "")
            size = step.get("size", 0)
            url = step.get("url", "")
            is_split = step.get("is_split", False)

            total_size += size

            print(f"  步骤 {step_num}:")
            print(f"    {from_ver} → {to_ver}")
            print(f"    包名: {package}")
            print(f"    大小: {format_size(size)}")
            if is_split:
                parts = step.get("parts", [])
                print(f"    分包: {len(parts)} 个文件")
                for part in parts:
                    print(f"      - {part.get('filename', '')} ({format_size(part.get('size', 0))})")
            print(f"    URL: {url[:60]}..." if len(url) > 60 else f"    URL: {url}")
            print()

        print(f"  总下载大小: {format_size(total_size)}")

    except ValueError as e:
        print(f"\n  ❌ 错误: {e}")


def print_config_info():
    """打印配置信息"""
    print_section("配置信息")
    
    print(f"\n  GitHub 仓库:")
    print(f"    所有者: {config.GITHUB_OWNER}")
    print(f"    仓库名: {config.GITHUB_REPO}")
    print(f"    API: {config.GITHUB_API_BASE}")
    
    print(f"\n  Manifest URL:")
    print(f"    {config.UPDATE_MANIFEST_URL}")
    
    print(f"\n  缓存目录:")
    print(f"    {config.get_update_cache_dir()}")
    
    print(f"\n  测试模式:")
    print(f"    状态: {'开启' if config.TEST_MODE else '关闭'}")
    print(f"    模拟当前版本: {config.TEST_CURRENT_VERSION}")
    print(f"    模拟目标版本: {config.TEST_TARGET_VERSION}")


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def get_test_download_dir() -> str:
    """获取测试下载目录"""
    update_dir = os.path.dirname(os.path.abspath(__file__))
    test_dir = os.path.join(update_dir, "test")
    os.makedirs(test_dir, exist_ok=True)
    return test_dir


def download_file_with_progress(url: str, save_path: str) -> bool:
    """
    下载文件并显示进度
    
    参数:
        url: 下载地址
        save_path: 保存路径
        
    返回:
        下载是否成功
    """
    import urllib.request
    import urllib.error
    from urllib.parse import quote
    
    try:
        # 对 URL 进行编码，处理中文字符
        # 分割 URL，对路径部分进行编码
        if '://' in url:
            protocol, rest = url.split('://', 1)
            if '/' in rest:
                host, path = rest.split('/', 1)
                # 对路径中的中文字符进行编码
                encoded_path = quote(path, safe='/')
                encoded_url = f"{protocol}://{host}/{encoded_path}"
            else:
                encoded_url = url
        else:
            encoded_url = quote(url, safe='/')
        
        # 创建请求
        req = urllib.request.Request(
            encoded_url,
            headers={
                'User-Agent': 'BirdPictureManager-UpdateTest/1.0',
                'Accept': '*/*'
            }
        )
        
        # 打开连接
        with urllib.request.urlopen(req, timeout=300) as response:
            # 获取文件总大小
            total_size = response.headers.get('Content-Length')
            if total_size:
                total_size = int(total_size)
            else:
                total_size = None
            
            # 创建保存目录
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # 下载并显示进度
            downloaded = 0
            chunk_size = 8192
            last_percent = -1
            
            print(f"  保存到: {save_path}")
            if total_size:
                print(f"  文件大小: {format_size(total_size)}")
            print()
            
            with open(save_path, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # 显示进度
                    if total_size:
                        percent = int((downloaded / total_size) * 100)
                        if percent != last_percent and percent % 5 == 0:  # 每5%更新一次
                            bar_length = 40
                            filled = int(bar_length * percent / 100)
                            bar = '█' * filled + '░' * (bar_length - filled)
                            print(f"\r  进度: [{bar}] {percent}% ({format_size(downloaded)} / {format_size(total_size)})", end='', flush=True)
                            last_percent = percent
            
            print()  # 换行
            print(f"\n  ✓ 下载完成: {format_size(downloaded)}")
            return True
            
    except Exception as e:
        print(f"\n  ❌ 下载失败: {e}")
        return False


def download_latest_packages(manifest: Dict) -> bool:
    """
    下载最新版本的升级包
    
    参数:
        manifest: 版本清单
        
    返回:
        下载是否成功
    """
    print_section("下载最新版本升级包")
    
    latest_version = manifest.get("latest_version", "")
    if not latest_version:
        print("  ❌ 无法获取最新版本号")
        return False
    
    print(f"\n  最新版本: V{latest_version}")
    
    # 获取测试下载目录
    test_dir = get_test_download_dir()
    print(f"  下载目录: {test_dir}")
    
    # 构建 GitHub 下载 URL 前缀
    github_url = f"https://github.com/{config.GITHUB_OWNER}/{config.GITHUB_REPO}/releases/latest/download/"
    
    # 查找最新版本的升级包
    releases = manifest.get("releases", {})
    packages_to_download = []
    
    # 解析最新版本
    base_ver = latest_version.split("_update")[0]
    
    if base_ver in releases:
        release_info = releases[base_ver]
        
        # 检查是否有 update
        if "_update" in latest_version:
            update_num = latest_version.split("_update")[1]
            updates = release_info.get("updates", {})
            if update_num in updates:
                update_info = updates[update_num]
                # 检查是否分包
                if update_info.get("is_split", False):
                    # 下载所有分包
                    for part in update_info.get("parts", []):
                        packages_to_download.append({
                            "name": part.get("filename", ""),
                            "size": part.get("size", 0),
                            "type": f"update {update_num} part {part.get('part_num', 0)}",
                            "is_part": True,
                            "parent_package": update_info.get("package", "")
                        })
                else:
                    packages_to_download.append({
                        "name": update_info.get("package", ""),
                        "size": update_info.get("size", 0),
                        "type": f"update {update_num}",
                        "is_part": False
                    })
        
        # 检查是否有跨版本升级包（如果是跨版本升级）
        cross_upgrade = release_info.get("cross_upgrade", {})
        if cross_upgrade and packages_to_download:
            # 如果升级路径需要跨版本，也下载跨版本包
            # 检查是否分包
            if cross_upgrade.get("is_split", False):
                # 下载所有分包
                for part in cross_upgrade.get("parts", []):
                    packages_to_download.insert(0, {
                        "name": part.get("filename", ""),
                        "size": part.get("size", 0),
                        "type": f"cross upgrade part {part.get('part_num', 0)}",
                        "is_part": True,
                        "parent_package": cross_upgrade.get("package", "")
                    })
            else:
                packages_to_download.insert(0, {
                    "name": cross_upgrade.get("package", ""),
                    "size": cross_upgrade.get("size", 0),
                    "type": f"cross upgrade (from V{cross_upgrade.get('from_base', '')})",
                    "is_part": False
                })
    
    # 如果无法计算升级路径，直接下载最新版本的完整包
    if not packages_to_download:
        print("  ⚠ 无法计算升级路径，将直接下载最新版本的完整包")
        
        # 查找最新版本的完整包（基础版本）
        if base_ver in releases:
            release_info = releases[base_ver]
            
            # 优先下载跨版本升级包（如果存在）
            cross_upgrade = release_info.get("cross_upgrade", {})
            if cross_upgrade:
                # 检查是否分包
                if cross_upgrade.get("is_split", False):
                    # 下载所有分包
                    for part in cross_upgrade.get("parts", []):
                        packages_to_download.append({
                            "name": part.get("filename", ""),
                            "size": part.get("size", 0),
                            "type": f"cross upgrade part {part.get('part_num', 0)}",
                            "is_part": True,
                            "parent_package": cross_upgrade.get("package", "")
                        })
                else:
                    packages_to_download.append({
                        "name": cross_upgrade.get("package", ""),
                        "size": cross_upgrade.get("size", 0),
                        "type": f"cross upgrade (from V{cross_upgrade.get('from_base', 'unknown')})",
                        "is_part": False
                    })
            else:
                # 如果没有跨版本包，尝试下载基础版本的完整包
                # 这里假设完整包的命名规则
                full_package = f"qitu_V{base_ver}.zip"
                packages_to_download.append({
                    "name": full_package,
                    "size": 0,  # 未知大小
                    "type": "full package",
                    "is_part": False
                })
        
        if not packages_to_download:
            print("  ❌ 未找到可下载的安装包")
            return False
    
    print(f"\n  找到 {len(packages_to_download)} 个文件需要下载:\n")
    
    # 下载每个包
    success_count = 0
    for i, pkg in enumerate(packages_to_download, 1):
        package_name = pkg.get("name", "")
        if not package_name:
            continue
        
        print(f"  [{i}/{len(packages_to_download)}] 下载 {pkg['type']}")
        print(f"  文件名: {package_name}")
        print(f"  大小: {format_size(pkg.get('size', 0))}")
        
        # 构建下载 URL
        download_url = github_url + package_name
        save_path = os.path.join(test_dir, package_name)
        
        # 检查是否已存在
        if os.path.exists(save_path):
            existing_size = os.path.getsize(save_path)
            if existing_size == pkg.get("size", 0):
                print(f"  ✓ 文件已存在且大小匹配，跳过下载")
                success_count += 1
                continue
            else:
                print(f"  ⚠ 文件已存在但大小不匹配，重新下载")
        
        # 下载文件
        if download_file_with_progress(download_url, save_path):
            success_count += 1
        else:
            print(f"  ❌ 下载失败: {package_name}")
        
        print()
    
    # 打印下载结果
    print(f"\n  下载完成: {success_count}/{len(packages_to_download)} 个文件")
    print(f"  保存位置: {test_dir}")
    
    # 列出已下载的文件
    downloaded_files = [f for f in os.listdir(test_dir) if f.endswith('.zip') or f.endswith('.part001') or f.endswith('.part002')]
    if downloaded_files:
        print(f"\n  已下载文件:")
        for f in downloaded_files:
            fpath = os.path.join(test_dir, f)
            fsize = os.path.getsize(fpath)
            print(f"    - {f} ({format_size(fsize)})")
    
    return success_count == len(packages_to_download)


def test_version_comparison():
    """测试版本比较功能"""
    print_section("版本比较测试")
    
    test_cases = [
        ("0.0.4", "0.0.5"),
        ("0.0.4", "0.0.4_update1"),
        ("0.0.4_update1", "0.0.4_update2"),
        ("0.0.4_update2", "0.0.5"),
        ("0.0.5", "0.0.5_update1"),
    ]
    
    checker = UpdateChecker()
    
    print()
    for v1, v2 in test_cases:
        result = checker.compare_versions(v1, v2)
        symbol = "<" if result < 0 else (">" if result > 0 else "=")
        print(f"  V{v1} {symbol} V{v2}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="栖图自动升级系统测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 正常测试
  python update/test_update.py
  
  # 使用测试模式（模拟版本）
  python update/test_update.py --test
  
  # 指定当前版本
  python update/test_update.py --current 0.0.4
  
  # 下载最新版本升级包
  python update/test_update.py --download
        """
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="使用测试模式（读取 update_config.py 中的模拟版本）"
    )
    parser.add_argument(
        "--current",
        default="",
        help="指定当前版本号（如 0.0.4）"
    )
    parser.add_argument(
        "--target",
        default="",
        help="指定目标版本号（如 0.0.5_update1）"
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="下载最新版本的升级包到 update/test 目录"
    )
    
    args = parser.parse_args()
    
    # 打印标题
    print_header("栖图自动升级系统测试")
    
    # 打印配置信息
    print_config_info()
    
    # 测试版本比较
    test_version_comparison()
    
    # 获取 manifest
    print_section("获取版本清单")
    manifest = fetch_manifest()
    
    if not manifest:
        print("\n  ❌ 无法获取版本清单，请检查：")
        print("     1. 网络连接是否正常")
        print("     2. GitHub 仓库配置是否正确")
        print("     3. update_manifest.json 是否已上传到 Releases")
        return 1
    
    print("\n  ✓ 成功获取版本清单")
    
    # 打印版本列表
    print_version_list(manifest)
    
    # 打印最新版本
    print_latest_version(manifest)
    
    # 确定要测试的版本
    if args.test or config.TEST_MODE:
        current_version = config.TEST_CURRENT_VERSION
        target_version = config.TEST_TARGET_VERSION
        print(f"\n  [测试模式] 使用模拟版本")
    else:
        current_version = args.current or "0.0.4"
        target_version = args.target or manifest.get("latest_version", "")
    
    # 打印升级路径
    if target_version:
        print_upgrade_path(manifest, current_version, target_version)
    
    # 下载最新版本升级包
    if args.download:
        download_latest_packages(manifest)
    
    # 打印结束
    print("\n" + "=" * 80)
    print(" 测试完成")
    print("=" * 80 + "\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
