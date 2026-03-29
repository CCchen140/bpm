#!/usr/bin/env python3
"""
测试 GitCode 公开仓库的访问权限
"""

import urllib.request
import urllib.error


def test_url(url: str, description: str):
    """测试 URL 访问"""
    print(f"\n测试: {description}")
    print(f"URL: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            content_type = response.headers.get('Content-Type', '')
            print(f"✓ 成功! Content-Type: {content_type}")
            
            # 读取部分内容
            data = response.read(1000)
            try:
                text = data.decode('utf-8')
                if '<html' in text.lower():
                    print("⚠ 返回的是 HTML 页面（可能是登录页）")
                elif '{' in text or '[' in text:
                    print("✓ 返回的可能是 JSON 数据")
                else:
                    print(f"内容预览: {text[:100]}")
            except:
                print(f"✓ 返回的是二进制数据")
            return True
    except urllib.error.HTTPError as e:
        print(f"✗ HTTP 错误: {e.code} - {e.reason}")
        return False
    except Exception as e:
        print(f"✗ 错误: {e}")
        return False


def main():
    print("=" * 60)
    print("测试 GitCode 公开仓库访问")
    print("=" * 60)
    
    owner = "c0255tz"
    repo = "qitupage"
    
    # 测试 1: 仓库主页
    test_url(
        f"https://gitcode.com/{owner}/{repo}",
        "仓库主页"
    )
    
    # 测试 2: Release 页面
    test_url(
        f"https://gitcode.com/{owner}/{repo}/releases",
        "Release 列表页面"
    )
    
    # 测试 3: 特定 Release 页面
    test_url(
        f"https://gitcode.com/{owner}/{repo}/releases/tag/V0.0.4",
        "V0.0.4 Release 页面"
    )
    
    # 测试 4: Raw 文件（不带 token）
    test_url(
        f"https://gitcode.com/{owner}/{repo}/raw/V0.0.4/update_manifest.json",
        "Raw 文件访问"
    )
    
    # 测试 5: 尝试添加 raw=true 参数
    test_url(
        f"https://gitcode.com/{owner}/{repo}/blob/V0.0.4/update_manifest.json?raw=true",
        "Blob + raw=true"
    )
    
    print("\n" + "=" * 60)
    print("结论:")
    print("=" * 60)
    print("""
GitCode 的访问限制:
1. 仓库主页 - 通常可以公开访问
2. Release 页面 - 可能需要登录才能查看
3. Raw 文件 - 需要登录才能访问
4. 文件下载 - 需要登录

这与 GitHub/Gitee 不同，GitCode 对公开仓库的
文件访问也有严格的登录要求。

解决方案:
1. 使用 Gitee 替代（推荐）
2. 使用 GitHub + 镜像加速
3. 使用对象存储服务（OSS/COS）
    """)


if __name__ == "__main__":
    main()
