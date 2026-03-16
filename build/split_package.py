#!/usr/bin/env python3
"""
栖图自动升级系统 - 分包脚本

自动对指定的 zip 文件进行分包（如果超过 2GB），并更新 update_manifest.json

使用方法:
    # 对指定文件进行分包并更新 manifest
    python build/split_package.py --file "dist/qitu_V0.0.5.zip"
    
    # 指定 manifest 路径
    python build/split_package.py --file "dist/qitu_V0.0.5.zip" --manifest "dist/update_manifest.json"
    
    # 仅分包，不更新 manifest
    python build/split_package.py --file "dist/qitu_V0.0.5.zip" --no-update-manifest
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import List, Dict, Tuple, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update import update_config as config
from update.file_splitter import split_file, needs_splitting, calculate_sha256, get_file_size, format_size


def find_version_in_manifest(manifest: Dict, package_name: str) -> Tuple[Optional[str], Optional[str], Optional[Dict]]:
    """
    在 manifest 中查找包对应的版本信息
    
    参数:
        manifest: manifest 字典
        package_name: 包文件名
        
    返回:
        (基础版本, update编号, 包信息字典) 或 (None, None, None)
    """
    releases = manifest.get("releases", {})
    
    for base_version, release_info in releases.items():
        # 检查 cross_upgrade
        cross_upgrade = release_info.get("cross_upgrade", {})
        if cross_upgrade.get("package") == package_name:
            return base_version, None, cross_upgrade
        
        # 检查 updates
        updates = release_info.get("updates", {})
        for update_num, update_info in updates.items():
            if update_info.get("package") == package_name:
                return base_version, update_num, update_info
    
    return None, None, None


def update_manifest_with_parts(
    manifest_path: str,
    package_name: str,
    parts_info: List[Dict]
) -> bool:
    """
    更新 manifest 中的分包信息
    
    参数:
        manifest_path: manifest 文件路径
        package_name: 包文件名
        parts_info: 分包信息列表
        
    返回:
        更新是否成功
    """
    try:
        # 加载 manifest
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        # 查找包信息
        base_version, update_num, package_info = find_version_in_manifest(manifest, package_name)
        
        if not package_info:
            print(f"  ❌ 在 manifest 中未找到包: {package_name}")
            print(f"     请确保已运行 build_delta.py 生成基础 manifest")
            return False
        
        # 更新分包信息
        package_info["is_split"] = True
        package_info["parts"] = parts_info
        
        # 保存 manifest
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        
        version_str = f"{base_version}_update{update_num}" if update_num else base_version
        print(f"  ✓ 已更新 manifest: V{version_str} 的分包信息")
        return True
        
    except Exception as e:
        print(f"  ❌ 更新 manifest 失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="栖图升级包分包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 对文件进行分包并自动更新 manifest
  python build/split_package.py --file "dist/qitu_V0.0.5.zip"
  
  # 指定 manifest 路径
  python build/split_package.py --file "dist/qitu_V0.0.5.zip" --manifest "dist/update_manifest.json"
  
  # 仅分包，不更新 manifest
  python build/split_package.py --file "dist/qitu_V0.0.5.zip" --no-update-manifest
        """
    )
    parser.add_argument(
        "--file",
        required=True,
        help="要分包的 zip 文件路径"
    )
    parser.add_argument(
        "--manifest",
        default="",
        help="update_manifest.json 文件路径（默认: dist/update_manifest.json）"
    )
    parser.add_argument(
        "--no-update-manifest",
        action="store_true",
        help="不更新 manifest 文件"
    )
    parser.add_argument(
        "--part-size",
        type=int,
        default=config.PART_SIZE,
        help=f"每个分包的大小（字节，默认: {config.PART_SIZE} = 1.9GB）"
    )
    
    args = parser.parse_args()
    
    # 检查文件
    file_path = os.path.abspath(args.file)
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        return 1
    
    # 获取文件名
    package_name = os.path.basename(file_path)
    output_dir = os.path.dirname(file_path)
    
    print("=" * 80)
    print(" 栖图升级包分包工具")
    print("=" * 80)
    print()
    print(f"文件: {file_path}")
    print(f"大小: {format_size(get_file_size(file_path))}")
    print()
    
    # 检查是否需要分包
    if not needs_splitting(file_path):
        print(f"✓ 文件大小未超过 {format_size(config.GITHUB_FILE_SIZE_LIMIT)} 限制，无需分包")
        return 0
    
    # 执行分包
    print("开始分包...")
    success, parts_info = split_file(file_path, output_dir, args.part_size)
    
    if not success:
        print("\n❌ 分包失败")
        return 1
    
    print(f"\n✓ 分包完成")
    print(f"  共 {len(parts_info)} 个分包")
    print()
    
    # 显示分包详情
    print("分包详情:")
    for part in parts_info:
        print(f"  {part['filename']}: {format_size(part['size'])}")
    print()
    
    # 更新 manifest
    if not args.no_update_manifest:
        manifest_path = args.manifest
        if not manifest_path:
            manifest_path = os.path.join(output_dir, "update_manifest.json")
        
        if os.path.exists(manifest_path):
            print(f"更新 manifest: {manifest_path}")
            if update_manifest_with_parts(manifest_path, package_name, parts_info):
                print("\n✓ 全部完成")
            else:
                print("\n⚠ 分包成功，但 manifest 更新失败")
                print(f"  请手动更新 manifest，添加以下分包信息:")
                print(json.dumps(parts_info, ensure_ascii=False, indent=2))
        else:
            print(f"\n⚠ manifest 文件不存在: {manifest_path}")
            print(f"  请手动创建或运行 build_delta.py 生成基础 manifest")
            print(f"  分包信息:")
            print(json.dumps(parts_info, ensure_ascii=False, indent=2))
    else:
        print("\n⚠ 跳过 manifest 更新（--no-update-manifest）")
        print(f"  请手动更新 manifest，添加以下分包信息:")
        print(json.dumps(parts_info, ensure_ascii=False, indent=2))
    
    # 打印上传清单
    print("\n" + "=" * 80)
    print(" 请上传以下文件到 GitHub Releases:")
    print("=" * 80)
    print(f"  1. {package_name} (原始文件，可选)")
    for part in parts_info:
        print(f"  2. {part['filename']} (必须)")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
