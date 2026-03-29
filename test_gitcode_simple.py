#!/usr/bin/env python3
"""
简化版 GitCode 测试
"""

import json
import urllib.request

# 配置
OWNER = "c0255tz"
REPO = "qitupage"
TAG = "V0.0.4"
FILENAME = "update_manifest.json"

# 构建 URL
url = f"https://gitcode.com/{OWNER}/{REPO}/releases/download/{TAG}/{FILENAME}"

print(f"测试 URL: {url}")
print()

# 创建请求 - 使用简单的请求头
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}

try:
    # 直接发送 GET 请求，让 urllib 自动处理重定向
    req = urllib.request.Request(url, headers=headers)
    
    print("发送请求...")
    with urllib.request.urlopen(req, timeout=30) as response:
        final_url = response.geturl()
        print(f"最终 URL: {final_url[:80]}...")
        
        content_type = response.headers.get('Content-Type', '')
        print(f"Content-Type: {content_type}")
        
        # 读取数据
        data = response.read()
        print(f"数据大小: {len(data)} 字节")
        
        # 尝试解析为 JSON
        try:
            text = data.decode('utf-8')
            manifest = json.loads(text)
            print("\n✓ 成功获取 JSON 数据!")
            print(f"\n最新版本: {manifest.get('latest_version', 'N/A')}")
            print(f"发布日期: {manifest.get('release_date', 'N/A')}")
            
            # 保存到文件
            save_path = f"gitcode_{FILENAME}"
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f"\n已保存到: {save_path}")
            
        except json.JSONDecodeError:
            print("\n✗ 不是有效的 JSON 数据")
            print(f"内容: {data[:200]}")
            
except urllib.error.HTTPError as e:
    print(f"✗ HTTP 错误: {e.code} - {e.reason}")
    try:
        error_body = e.read().decode('utf-8')
        print(f"错误详情: {error_body[:500]}")
    except:
        pass
except Exception as e:
    print(f"✗ 错误: {e}")
