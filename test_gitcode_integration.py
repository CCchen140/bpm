#!/usr/bin/env python3
"""
测试 GitCode 集成到更新系统

验证 GitCode 是否被正确设置为优先源
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from update import update_config as config
from update.mirror_selector import get_manifest_urls, clear_cache


def test_config():
    """测试配置是否正确"""
    print("=" * 60)
    print("测试 1: 验证 GitCode 配置")
    print("=" * 60)
    
    # 检查 GitCode 配置
    print(f"\nGitCode 配置:")
    print(f"  Owner: {config.GITCODE_OWNER}")
    print(f"  Repo: {config.GITCODE_REPO}")
    print(f"  Manifest URL: {config.GITCODE_UPDATE_MANIFEST_URL}")
    
    # 检查 GitHub 配置
    print(f"\nGitHub 配置:")
    print(f"  Owner: {config.GITHUB_OWNER}")
    print(f"  Repo: {config.GITHUB_REPO}")
    print(f"  Manifest URL: {config.GITHUB_UPDATE_MANIFEST_URL}")
    
    # 检查默认 URL
    print(f"\n默认 UPDATE_MANIFEST_URL:")
    print(f"  {config.UPDATE_MANIFEST_URL}")
    
    # 验证默认是 GitCode
    if config.UPDATE_MANIFEST_URL == config.GITCODE_UPDATE_MANIFEST_URL:
        print("\n✓ 默认使用 GitCode 作为主源")
        return True
    else:
        print("\n✗ 默认不是 GitCode")
        return False


def test_mirror_selector():
    """测试镜像选择器"""
    print("\n" + "=" * 60)
    print("测试 2: 验证镜像选择器优先使用 GitCode")
    print("=" * 60)
    
    # 清除缓存，确保获取最新的 URL 列表
    clear_cache()
    print("\n已清除镜像缓存")
    
    # 获取 URL 列表
    print("\n获取版本清单 URL 列表...")
    urls = get_manifest_urls(use_cache=False)
    
    print(f"\n共 {len(urls)} 个 URL:")
    print("-" * 60)
    
    for i, (url, desc) in enumerate(urls, 1):
        print(f"{i}. [{desc}]")
        print(f"   {url[:80]}...")
    
    # 验证第一个是 GitCode
    if urls and len(urls) > 0:
        first_url, first_desc = urls[0]
        if 'gitcode' in first_desc.lower():
            print("\n✓ GitCode 被设置为第一优先源")
            return True
        else:
            print(f"\n✗ 第一优先源是 {first_desc}，不是 GitCode")
            return False
    else:
        print("\n✗ URL 列表为空")
        return False


def test_manifest_fetch():
    """测试从 GitCode 获取版本清单"""
    print("\n" + "=" * 60)
    print("测试 3: 从 GitCode 获取版本清单")
    print("=" * 60)
    
    import urllib.request
    import json
    
    url = config.GITCODE_UPDATE_MANIFEST_URL
    print(f"\nURL: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        
        print("发送请求...")
        with urllib.request.urlopen(req, timeout=30) as response:
            final_url = response.geturl()
            if final_url != url:
                print(f"✓ 已重定向到 CDN")
            
            content_type = response.headers.get('Content-Type', '')
            print(f"Content-Type: {content_type}")
            
            data = response.read()
            print(f"数据大小: {len(data)} 字节")
            
            # 解析 JSON
            text = data.decode('utf-8')
            manifest = json.loads(text)
            
            print("\n✓ 成功获取版本清单!")
            print(f"\n版本信息:")
            print(f"  最新版本: {manifest.get('latest_version', 'N/A')}")
            print(f"  发布日期: {manifest.get('release_date', 'N/A')}")
            print(f"  强制更新: {manifest.get('force_update', False)}")
            
            if 'releases' in manifest:
                print(f"  发布版本数: {len(manifest['releases'])}")
            
            return True
            
    except Exception as e:
        print(f"\n✗ 获取失败: {e}")
        return False


def main():
    """主函数"""
    print("GitCode 集成测试")
    print()
    
    # 测试 1: 配置验证
    success1 = test_config()
    
    # 测试 2: 镜像选择器
    success2 = test_mirror_selector()
    
    # 测试 3: 实际获取
    success3 = test_manifest_fetch()
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    if success1 and success2 and success3:
        print("\n✓ 所有测试通过!")
        print("\nGitCode 已成功集成到更新系统中:")
        print("  - 配置正确")
        print("  - 优先使用 GitCode")
        print("  - 可以正常获取版本清单")
        return 0
    else:
        print("\n✗ 部分测试失败:")
        if not success1:
            print("  - 配置测试失败")
        if not success2:
            print("  - 镜像选择器测试失败")
        if not success3:
            print("  - 版本清单获取失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
