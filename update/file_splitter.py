#!/usr/bin/env python3
"""
栖图自动升级系统 - 文件分包工具

支持将大文件分割成多个小包（用于 GitHub Releases 上传）
以及将多个分包合并成原始文件
"""

import os
import hashlib
from typing import List, Dict, Tuple, Optional
from . import update_config as config


# 获取日志管理器实例
def _get_logger():
    """获取日志管理器实例"""
    try:
        from utils.log_manager import LogManager
        return LogManager.instance()
    except Exception:
        return None


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[FileSplitter] {msg}")


def _log_error(msg: str):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        logger.error(f"[FileSplitter] {msg}")


def calculate_sha256(file_path: str) -> str:
    """
    计算文件的 SHA256 哈希值
    
    参数:
        file_path: 文件路径
        
    返回:
        SHA256 哈希值（小写十六进制字符串）
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest().lower()


def get_file_size(file_path: str) -> int:
    """
    获取文件大小
    
    参数:
        file_path: 文件路径
        
    返回:
        文件大小（字节）
    """
    return os.path.getsize(file_path)


def split_file(file_path: str, output_dir: str, part_size: int = None) -> Tuple[bool, List[Dict]]:
    """
    将大文件分割成多个小包
    
    参数:
        file_path: 原始文件路径
        output_dir: 输出目录
        part_size: 每个分包的大小（字节），默认使用配置值
        
    返回:
        (是否成功, 分包信息列表)
        分包信息包含: part_num, filename, size, hash
    """
    if part_size is None:
        part_size = config.PART_SIZE
    
    if not os.path.exists(file_path):
        _log_error(f"文件不存在: {file_path}")
        return False, []

    file_size = get_file_size(file_path)

    # 如果文件小于限制，不需要分包
    if file_size <= config.GITHUB_FILE_SIZE_LIMIT:
        _log_info(f"文件大小 {format_size(file_size)} 未超过限制，无需分包")
        return False, []

    # 计算分包数量
    num_parts = (file_size + part_size - 1) // part_size

    if num_parts > config.MAX_PARTS:
        _log_error(f"分包数量 {num_parts} 超过最大限制 {config.MAX_PARTS}")
        return False, []

    _log_info(f"分割文件: {os.path.basename(file_path)}")
    _log_info(f"  原始大小: {format_size(file_size)}")
    _log_info(f"  分包大小: {format_size(part_size)}")
    _log_info(f"  分包数量: {num_parts}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    parts_info = []
    base_name = os.path.basename(file_path)
    
    with open(file_path, 'rb') as f:
        for part_num in range(1, num_parts + 1):
            # 生成分包文件名
            part_suffix = config.PART_SUFFIX_TEMPLATE.format(part_num=part_num)
            part_filename = f"{base_name}{part_suffix}"
            part_path = os.path.join(output_dir, part_filename)
            
            # 读取并写入分包
            remaining = part_size if part_num < num_parts else file_size - (part_num - 1) * part_size
            bytes_written = 0

            _log_info(f"  创建分包 {part_num}/{num_parts}: {part_filename}")

            with open(part_path, 'wb') as part_file:
                while bytes_written < remaining:
                    chunk_size = min(8192, remaining - bytes_written)
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    part_file.write(chunk)
                    bytes_written += len(chunk)

            # 计算分包哈希
            part_hash = calculate_sha256(part_path)
            part_size_actual = get_file_size(part_path)

            parts_info.append({
                "part_num": part_num,
                "filename": part_filename,
                "size": part_size_actual,
                "hash": f"sha256:{part_hash}"
            })

            _log_info(f"    大小: {format_size(part_size_actual)}, 哈希: {part_hash[:16]}...")

    _log_info(f"文件分割完成，共 {num_parts} 个分包")
    return True, parts_info


def merge_files(parts: List[str], output_path: str, verify_hash: str = None) -> bool:
    """
    将多个分包合并成原始文件
    
    参数:
        parts: 分包文件路径列表（按顺序）
        output_path: 输出文件路径
        verify_hash: 验证用的原始文件哈希（可选）
        
    返回:
        合并是否成功
    """
    _log_info(f"合并分包到: {output_path}")
    _log_info(f"  分包数量: {len(parts)}")

    # 检查所有分包是否存在
    for part in parts:
        if not os.path.exists(part):
            _log_error(f"分包不存在: {part}")
            return False

    # 创建输出目录
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 如果输出文件已存在，先删除
    if os.path.exists(output_path):
        os.remove(output_path)

    # 合并文件
    total_size = 0
    with open(output_path, 'wb') as outfile:
        for i, part_path in enumerate(parts, 1):
            part_size = get_file_size(part_path)
            _log_info(f"  [{i}/{len(parts)}] 合并: {os.path.basename(part_path)} ({format_size(part_size)})")

            with open(part_path, 'rb') as infile:
                while True:
                    chunk = infile.read(8192)
                    if not chunk:
                        break
                    outfile.write(chunk)

            total_size += part_size

    _log_info(f"合并完成，总大小: {format_size(total_size)}")

    # 验证哈希（如果提供）
    if verify_hash:
        _log_info("  验证文件完整性...")
        actual_hash = calculate_sha256(output_path)
        expected_hash = verify_hash.lower().replace('sha256:', '')

        if actual_hash == expected_hash:
            _log_info("  哈希验证通过")
            return True
        else:
            _log_error("  哈希验证失败")
            _log_error(f"    期望: {expected_hash}")
            _log_error(f"    实际: {actual_hash}")
            return False

    return True


def get_part_files(directory: str, base_filename: str) -> List[str]:
    """
    获取指定文件的所有分包
    
    参数:
        directory: 目录路径
        base_filename: 原始文件名
        
    返回:
        分包文件路径列表（按顺序排序）
    """
    parts = []
    part_num = 1
    
    while True:
        part_suffix = config.PART_SUFFIX_TEMPLATE.format(part_num=part_num)
        part_filename = f"{base_filename}{part_suffix}"
        part_path = os.path.join(directory, part_filename)
        
        if os.path.exists(part_path):
            parts.append(part_path)
            part_num += 1
        else:
            break
    
    return parts


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


def needs_splitting(file_path: str) -> bool:
    """
    检查文件是否需要分包
    
    参数:
        file_path: 文件路径
        
    返回:
        是否需要分包
    """
    if not os.path.exists(file_path):
        return False
    
    return get_file_size(file_path) > config.GITHUB_FILE_SIZE_LIMIT


if __name__ == "__main__":
    # 测试分包功能
    import sys
    
    if len(sys.argv) < 3:
        print("用法:")
        print("  分包: python file_splitter.py split <文件路径> [输出目录]")
        print("  合并: python file_splitter.py merge <分包文件前缀> <输出路径>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "split":
        file_path = sys.argv[2]
        output_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.dirname(file_path)
        success, parts = split_file(file_path, output_dir)
        if success:
            print("\n分包信息:")
            for part in parts:
                print(f"  {part['filename']}: {format_size(part['size'])}")
    
    elif command == "merge":
        parts_prefix = sys.argv[2]
        output_path = sys.argv[3]
        # 获取所有分包
        directory = os.path.dirname(parts_prefix)
        base_name = os.path.basename(parts_prefix)
        parts = get_part_files(directory, base_name)
        if parts:
            merge_files(parts, output_path)
        else:
            print(f"未找到分包: {parts_prefix}")
    
    else:
        print(f"未知命令: {command}")
