#!/usr/bin/env python3
"""
栖图升级包打包脚本

用于生成包含 innosetup 安装包和影响文件清单的升级包

使用方法:
    python build_update_package.py --version 0.0.5 --installer path/to/setup.exe --output dist/

参数:
    --version: 目标版本号
    --installer: innosetup 生成的安装包路径
    --output: 输出目录
    --from-version: 起始版本（用于生成差异文件列表）
    --affected-files: 受影响文件列表（逗号分隔的文件路径）
"""

import os
import sys
import json
import zipfile
import argparse
import hashlib
from datetime import datetime
from pathlib import Path


def calculate_sha256(file_path: str) -> str:
    """计算文件的 SHA256 哈希值"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_file_size(file_path: str) -> int:
    """获取文件大小"""
    return os.path.getsize(file_path)


def analyze_version_difference(from_version: str, to_version: str, app_dir: str) -> dict:
    """
    分析两个版本之间的文件差异

    参数:
        from_version: 起始版本
        to_version: 目标版本
        app_dir: 应用目录

    返回:
        包含 affected_files, new_files, deleted_files 的字典
    """
    # 这里可以实现文件对比逻辑
    # 例如对比两个版本的文件清单
    # 简化版本：返回空列表，需要手动指定
    return {
        "affected_files": [],
        "new_files": [],
        "deleted_files": []
    }


def create_update_package(
    version: str,
    installer_path: str,
    output_dir: str,
    from_version: str = None,
    affected_files: list = None,
    new_files: list = None,
    deleted_files: list = None
) -> str:
    """
    创建升级包

    参数:
        version: 目标版本号
        installer_path: 安装包路径
        output_dir: 输出目录
        from_version: 起始版本
        affected_files: 受影响文件列表
        new_files: 新增文件列表
        deleted_files: 删除文件列表

    返回:
        生成的升级包路径
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 生成升级包文件名
    package_name = f"qitu_V{version}.zip"
    package_path = os.path.join(output_dir, package_name)

    # 准备清单内容
    manifest = {
        "version": version,
        "from_version": from_version,
        "installer": os.path.basename(installer_path),
        "build_time": datetime.now().isoformat(),
        "affected_files": affected_files or [],
        "new_files": new_files or [],
        "deleted_files": deleted_files or []
    }

    # 创建 zip 包
    with zipfile.ZipFile(package_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 添加安装包
        installer_arcname = os.path.basename(installer_path)
        zf.write(installer_path, installer_arcname)
        print(f"添加安装包: {installer_arcname}")

        # 添加清单文件
        manifest_content = json.dumps(manifest, ensure_ascii=False, indent=2)
        zf.writestr('affected_files.json', manifest_content)
        print(f"添加清单文件: affected_files.json")

    # 计算文件信息
    file_size = get_file_size(package_path)
    file_hash = calculate_sha256(package_path)

    print(f"\n升级包生成成功!")
    print(f"  文件: {package_path}")
    print(f"  大小: {file_size / 1024 / 1024:.2f} MB")
    print(f"  SHA256: {file_hash}")
    print(f"\n清单内容:")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    # 同时生成更新清单条目（用于 update_manifest.json）
    manifest_entry = {
        "version": version,
        "package": package_name,
        "tag": f"v{version}",
        "size": file_size,
        "hash": f"sha256:{file_hash}"
    }

    print(f"\n更新清单条目:")
    print(json.dumps(manifest_entry, ensure_ascii=False, indent=2))

    return package_path


def main():
    parser = argparse.ArgumentParser(description='栖图升级包打包工具')
    parser.add_argument('--version', required=True, help='目标版本号 (例如: 0.0.5)')
    parser.add_argument('--installer', required=True, help='innosetup 安装包路径')
    parser.add_argument('--output', default='dist', help='输出目录 (默认: dist)')
    parser.add_argument('--from-version', help='起始版本号')
    parser.add_argument('--affected-files', help='受影响文件列表（逗号分隔）')
    parser.add_argument('--new-files', help='新增文件列表（逗号分隔）')
    parser.add_argument('--deleted-files', help='删除文件列表（逗号分隔）')

    args = parser.parse_args()

    # 检查安装包是否存在
    if not os.path.exists(args.installer):
        print(f"错误: 安装包不存在: {args.installer}")
        sys.exit(1)

    # 解析文件列表
    affected_files = None
    if args.affected_files:
        affected_files = [f.strip() for f in args.affected_files.split(',')]

    new_files = None
    if args.new_files:
        new_files = [f.strip() for f in args.new_files.split(',')]

    deleted_files = None
    if args.deleted_files:
        deleted_files = [f.strip() for f in args.deleted_files.split(',')]

    # 创建升级包
    create_update_package(
        version=args.version,
        installer_path=args.installer,
        output_dir=args.output,
        from_version=args.from_version,
        affected_files=affected_files,
        new_files=new_files,
        deleted_files=deleted_files
    )


if __name__ == '__main__':
    main()
