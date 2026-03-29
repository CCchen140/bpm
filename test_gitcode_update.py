#!/usr/bin/env python3
"""
GitCode 更新测试 Demo

测试从 GitCode 获取版本清单和下载更新文件
"""

import json
import urllib.request
import urllib.error
import os
import sys
import gzip


# =============================================================================
# GitCode 配置
# =============================================================================

# GitCode 仓库信息
GITCODE_OWNER = "c0255tz"  # GitCode 用户名
GITCODE_REPO = "qitupage"   # 仓库名称

# 测试用的版本标签
TEST_TAG = "V0.0.4"

# 版本清单文件名
MANIFEST_FILENAME = "update_manifest.json"

# 下载保存路径
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "test_download")


def ensure_dir(directory: str) -> str:
    """
    确保目录存在，如果不存在则创建
    
    参数:
        directory: 目录路径
        
    返回:
        目录路径
    """
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    return directory


def get_request_headers() -> dict:
    """
    获取请求头
    
    返回:
        请求头字典
    """
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }


def fetch_from_gitcode_release(tag: str, filename: str, timeout: int = 30) -> tuple:
    """
    从 GitCode Release 下载文件
    
    GitCode Release 下载会返回 302 重定向到 CDN 地址
    
    参数:
        tag: 版本标签
        filename: 文件名
        timeout: 超时时间
        
    返回:
        (成功标志, 响应数据或错误信息)
    """
    url = f"https://gitcode.com/{GITCODE_OWNER}/{GITCODE_REPO}/releases/download/{tag}/{filename}"
    
    print(f"正在访问: {url}")
    
    headers = get_request_headers()
    
    try:
        # 首先获取重定向地址
        req = urllib.request.Request(url, headers=headers, method='HEAD')
        
        # 使用默认的 redirect handler 会自动跟随重定向
        opener = urllib.request.build_opener()
        
        with opener.open(req, timeout=timeout) as response:
            final_url = response.geturl()
            if final_url != url:
                print(f"✓ 已重定向到 CDN: {final_url[:80]}...")
            
            # 现在获取实际内容
            req = urllib.request.Request(final_url, headers=headers)
            with opener.open(req, timeout=timeout) as content_response:
                content_type = content_response.headers.get('Content-Type', '')
                print(f"✓ 下载成功! Content-Type: {content_type}")
                
                data = content_response.read()
                
                # 尝试解码
                try:
                    text_data = data.decode('utf-8')
                    return True, text_data
                except UnicodeDecodeError:
                    # 可能是二进制文件
                    return True, data
                
    except urllib.error.HTTPError as e:
        print(f"✗ HTTP 错误: {e.code} - {e.reason}")
        # 尝试读取错误响应
        try:
            error_data = e.read()
            try:
                error_text = error_data.decode('utf-8')
                print(f"  错误响应: {error_text[:300]}")
            except:
                pass
        except:
            pass
        return False, f"HTTP 错误: {e.code}"
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False, str(e)


def download_file(tag: str, filename: str, save_path: str, timeout: int = 60) -> bool:
    """
    下载文件到本地
    
    参数:
        tag: 版本标签
        filename: 文件名
        save_path: 保存路径
        timeout: 超时时间
        
    返回:
        下载是否成功
    """
    url = f"https://gitcode.com/{GITCODE_OWNER}/{GITCODE_REPO}/releases/download/{tag}/{filename}"
    
    print(f"\n下载文件: {filename}")
    print(f"保存到: {save_path}")
    
    headers = get_request_headers()
    
    try:
        # 使用支持重定向的 opener
        opener = urllib.request.build_opener()
        req = urllib.request.Request(url, headers=headers)
        
        with opener.open(req, timeout=timeout) as response:
            final_url = response.geturl()
            if final_url != url:
                print(f"✓ 已重定向到 CDN")
            
            # 获取文件大小
            total_size = response.headers.get('Content-Length')
            if total_size:
                total_size = int(total_size)
                print(f"文件大小: {total_size / 1024:.2f} KB")
            
            # 下载文件
            downloaded = 0
            chunk_size = 8192
            
            with open(save_path, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # 显示进度
                    if total_size:
                        progress = (downloaded / total_size) * 100
                        print(f"\r进度: {progress:.1f}%", end='', flush=True)
            
            print(f"\n✓ 下载完成!")
            return True
            
    except Exception as e:
        print(f"\n✗ 下载失败: {e}")
        return False


def test_fetch_manifest():
    """测试获取版本清单"""
    print("=" * 60)
    print("测试从 GitCode 获取版本清单")
    print("=" * 60)
    print(f"仓库: {GITCODE_OWNER}/{GITCODE_REPO}")
    print(f"版本: {TEST_TAG}")
    print(f"文件: {MANIFEST_FILENAME}")
    print()
    
    success, result = fetch_from_gitcode_release(TEST_TAG, MANIFEST_FILENAME)
    
    if success and isinstance(result, str):
        try:
            manifest = json.loads(result)
            print("\n✓ 成功获取版本清单!")
            
            # 显示关键信息
            print("\n版本清单内容:")
            print("-" * 40)
            
            if "latest_version" in manifest:
                print(f"最新版本: {manifest['latest_version']}")
            if "release_date" in manifest:
                print(f"发布日期: {manifest['release_date']}")
            if "changelog" in manifest:
                changelog = manifest['changelog']
                if len(changelog) > 200:
                    changelog = changelog[:200] + "..."
                print(f"更新日志: {changelog}")
            if "releases" in manifest:
                print(f"发布版本数: {len(manifest['releases'])}")
            
            print("-" * 40)
            print("\n完整清单内容 (JSON):")
            print(json.dumps(manifest, indent=2, ensure_ascii=False))
            
            return True, manifest
            
        except json.JSONDecodeError as e:
            print(f"\n✗ JSON 解析失败: {e}")
            print(f"响应内容: {result[:500]}")
            return False, None
    else:
        print(f"\n✗ 获取失败: {result}")
        return False, None


def test_download_manifest(manifest: dict):
    """测试下载版本清单文件到本地"""
    print("\n" + "=" * 60)
    print("测试下载版本清单文件")
    print("=" * 60)
    
    ensure_dir(DOWNLOAD_DIR)
    save_path = os.path.join(DOWNLOAD_DIR, f"gitcode_{MANIFEST_FILENAME}")
    
    success = download_file(TEST_TAG, MANIFEST_FILENAME, save_path)
    
    if success:
        # 验证文件
        try:
            with open(save_path, 'r', encoding='utf-8') as f:
                content = f.read()
                json.loads(content)  # 验证 JSON
                print(f"✓ 文件验证成功")
                print(f"  文件大小: {os.path.getsize(save_path)} 字节")
                return True
        except Exception as e:
            print(f"✗ 文件验证失败: {e}")
            return False
    
    return False


def test_download_update_package(manifest: dict):
    """测试下载更新包"""
    print("\n" + "=" * 60)
    print("测试下载更新包")
    print("=" * 60)
    
    if not manifest or "releases" not in manifest:
        print("✗ 版本清单中没有 releases 信息")
        return False
    
    # 获取最新版本的更新包信息
    latest_version = manifest.get("latest_version", "")
    releases = manifest.get("releases", {})
    
    # 解析版本号获取基础版本
    base_version = latest_version.split("_")[0] if "_" in latest_version else latest_version
    
    if base_version not in releases:
        print(f"✗ 未找到版本 {base_version} 的发布信息")
        return False
    
    release_info = releases[base_version]
    package_name = release_info.get("package", "")
    
    if not package_name:
        print("✗ 未找到更新包信息")
        return False
    
    print(f"更新包名称: {package_name}")
    print(f"更新包大小: {release_info.get('size', 0)} 字节")
    
    # 询问是否下载
    response = input(f"\n是否下载更新包 '{package_name}'? (y/n): ")
    if response.lower() != 'y':
        print("跳过下载")
        return True
    
    save_path = os.path.join(DOWNLOAD_DIR, package_name)
    success = download_file(TEST_TAG, package_name, save_path, timeout=300)
    
    return success


def main():
    """主函数"""
    print("GitCode 更新功能测试 Demo")
    print()
    
    # 测试 1: 获取版本清单
    success, manifest = test_fetch_manifest()
    if not success:
        print("\n✗ 测试失败")
        return 1
    
    # 测试 2: 下载版本清单文件
    test_download_manifest(manifest)
    
    # 测试 3: 下载更新包（可选）
    if manifest:
        test_download_update_package(manifest)
    
    print("\n" + "=" * 60)
    print("✓ 测试完成!")
    print("=" * 60)
    print(f"下载的文件保存在: {DOWNLOAD_DIR}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
