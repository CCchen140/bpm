#!/usr/bin/env python3
"""
栖图自动升级系统 - 镜像选择器

负责检测和选择最优的镜像地址
支持缓存最优镜像结果
"""

import os
import json
import socket
import time
from urllib.parse import urlparse
from typing import List, Tuple, Optional, Dict

from . import update_config as config


# 缓存文件路径
_MIRROR_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.mirror_cache.json')

# 缓存有效期（小时）
_CACHE_VALID_HOURS = 24

# 全局缓存
_cached_mirror_order: Optional[List[Tuple[str, str]]] = None
_cache_timestamp: Optional[float] = None


# 获取日志管理器实例
def _get_logger():
    """获取日志管理器实例"""
    try:
        from utils.log_manager import LogManager
        return LogManager.instance()
    except Exception:
        return None


def _log_debug(msg: str):
    """记录debug日志"""
    logger = _get_logger()
    if logger:
        logger.debug(f"[MirrorSelector] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[MirrorSelector] {msg}")


def _log_warning(msg: str):
    """记录warning日志"""
    logger = _get_logger()
    if logger:
        logger.warning(f"[MirrorSelector] {msg}")


def _log_error(msg: str, exc: Exception = None):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        if exc:
            logger.exception(f"[MirrorSelector] {msg}", exc)
        else:
            logger.error(f"[MirrorSelector] {msg}")


def _load_cache() -> Optional[List[Tuple[str, str]]]:
    """
    从文件加载缓存的镜像顺序
    
    返回:
        缓存的URL列表，如果缓存无效返回 None
    """
    global _cached_mirror_order, _cache_timestamp
    
    # 如果内存中有缓存，直接返回
    if _cached_mirror_order is not None and _cache_timestamp is not None:
        # 检查内存缓存是否过期
        elapsed_hours = (time.time() - _cache_timestamp) / 3600
        if elapsed_hours < _CACHE_VALID_HOURS:
            _log_debug(f"使用内存缓存的镜像顺序（{elapsed_hours:.1f}小时前生成）")
            return _cached_mirror_order
        else:
            _log_debug("内存缓存已过期")
            _cached_mirror_order = None
    
    # 从文件加载缓存
    try:
        if not os.path.exists(_MIRROR_CACHE_FILE):
            return None
        
        with open(_MIRROR_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        # 检查缓存时间
        cache_time = cache_data.get('timestamp', 0)
        elapsed_hours = (time.time() - cache_time) / 3600
        
        if elapsed_hours >= _CACHE_VALID_HOURS:
            _log_debug(f"文件缓存已过期（{elapsed_hours:.1f}小时前生成）")
            return None
        
        # 加载镜像顺序
        mirror_order = cache_data.get('mirror_order', [])
        if not mirror_order:
            return None
        
        # 转换为元组列表
        result = [(item['url'], item['desc']) for item in mirror_order]
        
        # 更新内存缓存
        _cached_mirror_order = result
        _cache_timestamp = cache_time
        
        _log_info(f"从文件加载缓存的镜像顺序（{elapsed_hours:.1f}小时前生成）")
        return result
        
    except Exception as e:
        _log_debug(f"加载缓存失败: {e}")
        return None


def _save_cache(mirror_order: List[Tuple[str, str]]):
    """
    保存镜像顺序到缓存文件
    
    参数:
        mirror_order: 镜像URL列表
    """
    global _cached_mirror_order, _cache_timestamp
    
    try:
        cache_data = {
            'timestamp': time.time(),
            'mirror_order': [
                {'url': url, 'desc': desc}
                for url, desc in mirror_order
            ]
        }
        
        with open(_MIRROR_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        # 更新内存缓存
        _cached_mirror_order = mirror_order
        _cache_timestamp = time.time()
        
        _log_info(f"镜像顺序已缓存到文件: {_MIRROR_CACHE_FILE}")
        
    except Exception as e:
        _log_warning(f"保存缓存失败: {e}")


def clear_cache():
    """清除镜像缓存"""
    global _cached_mirror_order, _cache_timestamp
    
    _cached_mirror_order = None
    _cache_timestamp = None
    
    try:
        if os.path.exists(_MIRROR_CACHE_FILE):
            os.remove(_MIRROR_CACHE_FILE)
            _log_info("镜像缓存已清除")
    except Exception as e:
        _log_warning(f"清除缓存失败: {e}")


# 禁用列表文件路径
_DISABLED_URLS_FILE = os.path.join(os.path.dirname(__file__), '.disabled_urls.json')

# 禁用时长（秒）
_DISABLE_DURATION = 3600  # 1小时


def _load_disabled_urls() -> Dict[str, float]:
    """
    加载禁用的URL列表
    
    返回:
        禁用的URL字典，键为URL，值为禁用结束时间戳
    """
    try:
        if not os.path.exists(_DISABLED_URLS_FILE):
            return {}
        
        with open(_DISABLED_URLS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 清理已过期的禁用记录
        current_time = time.time()
        disabled_urls = {}
        for url, expire_time in data.items():
            if expire_time > current_time:
                disabled_urls[url] = expire_time
            else:
                _log_debug(f"URL 禁用已过期: {url}")
        
        # 如果有过期记录，保存清理后的数据
        if len(disabled_urls) != len(data):
            _save_disabled_urls(disabled_urls)
        
        return disabled_urls
    except Exception as e:
        _log_debug(f"加载禁用列表失败: {e}")
        return {}


def _save_disabled_urls(disabled_urls: Dict[str, float]):
    """
    保存禁用的URL列表
    
    参数:
        disabled_urls: 禁用的URL字典
    """
    try:
        with open(_DISABLED_URLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(disabled_urls, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log_warning(f"保存禁用列表失败: {e}")


def disable_url(url: str, duration: int = _DISABLE_DURATION):
    """
    禁用指定URL
    
    参数:
        url: 要禁用的URL
        duration: 禁用时长（秒），默认1小时
    """
    disabled_urls = _load_disabled_urls()
    expire_time = time.time() + duration
    disabled_urls[url] = expire_time
    _save_disabled_urls(disabled_urls)
    _log_info(f"URL 已禁用 {duration} 秒: {url}")


def is_url_disabled(url: str) -> bool:
    """
    检查URL是否被禁用
    
    参数:
        url: 要检查的URL
        
    返回:
        是否被禁用
    """
    disabled_urls = _load_disabled_urls()
    if url in disabled_urls:
        expire_time = disabled_urls[url]
        if time.time() < expire_time:
            remaining = int(expire_time - time.time())
            _log_debug(f"URL 仍被禁用（剩余 {remaining} 秒）: {url}")
            return True
        else:
            # 过期了，移除
            del disabled_urls[url]
            _save_disabled_urls(disabled_urls)
    return False


def record_url_failure(url: str):
    """
    记录URL失败，连续2次失败则禁用
    
    参数:
        url: 失败的URL
    """
    # 使用临时文件记录失败次数
    failure_file = os.path.join(os.path.dirname(__file__), '.url_failures.json')
    
    try:
        # 加载现有记录
        failures = {}
        if os.path.exists(failure_file):
            with open(failure_file, 'r', encoding='utf-8') as f:
                failures = json.load(f)
        
        # 清理30分钟前的记录
        current_time = time.time()
        cutoff_time = current_time - 1800  # 30分钟
        failures = {k: v for k, v in failures.items() if v['time'] > cutoff_time}
        
        # 记录本次失败
        if url not in failures:
            failures[url] = {'count': 0, 'time': current_time}
        
        failures[url]['count'] += 1
        failures[url]['time'] = current_time
        
        # 保存记录
        with open(failure_file, 'w', encoding='utf-8') as f:
            json.dump(failures, f, ensure_ascii=False, indent=2)
        
        # 检查是否达到禁用阈值（2次）
        if failures[url]['count'] >= 2:
            disable_url(url)
            # 清除失败记录
            del failures[url]
            with open(failure_file, 'w', encoding='utf-8') as f:
                json.dump(failures, f, ensure_ascii=False, indent=2)
            _log_info(f"URL 连续失败 2 次，已加入禁用列表: {url}")
        else:
            _log_debug(f"URL 失败次数: {failures[url]['count']}/2: {url}")
            
    except Exception as e:
        _log_warning(f"记录URL失败失败: {e}")


def clear_disabled_urls():
    """清除所有禁用的URL"""
    try:
        if os.path.exists(_DISABLED_URLS_FILE):
            os.remove(_DISABLED_URLS_FILE)
            _log_info("禁用列表已清除")
    except Exception as e:
        _log_warning(f"清除禁用列表失败: {e}")


def ping_host(host: str, port: int = 443, timeout: float = 3.0) -> Optional[float]:
    """
    检测主机连通性和延迟
    
    参数:
        host: 主机地址
        port: 端口号（默认443 for HTTPS）
        timeout: 超时时间（秒）
        
    返回:
        延迟时间（毫秒），如果失败返回 None
    """
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        elapsed = (time.time() - start_time) * 1000  # 转换为毫秒
        sock.close()
        
        if result == 0:
            return elapsed
        return None
    except Exception as e:
        _log_debug(f"ping {host}:{port} 失败: {e}")
        return None


def extract_host_from_url(url: str) -> Optional[str]:
    """
    从URL中提取主机地址
    
    参数:
        url: URL地址
        
    返回:
        主机地址
    """
    try:
        parsed = urlparse(url)
        return parsed.hostname
    except Exception as e:
        _log_error(f"解析URL失败: {url}", e)
        return None


def select_best_mirror(urls_with_meta: List[Tuple[str, str, bool]]) -> List[Tuple[str, str]]:
    """
    选择最优的镜像地址
    
    参数:
        urls_with_meta: URL列表，每个元素是 (url, description, enable_ping)
        
    返回:
        按优先级排序的URL列表，每个元素是 (url, description)
    """
    if not config.ENABLE_PING_CHECK:
        _log_debug("ping检测已禁用，按配置顺序使用镜像")
        return [(url, desc) for url, desc, _ in urls_with_meta]
    
    _log_info("开始检测镜像可用性...")
    
    # 检测每个镜像的延迟
    results = []
    for url, desc, enable_ping in urls_with_meta:
        if not enable_ping:
            # 不启用ping检测的镜像，赋予中等优先级
            results.append((url, desc, 500.0, True))  # 500ms 作为默认值
            _log_debug(f"镜像 {desc}: 跳过ping检测，使用默认优先级")
            continue
        
        host = extract_host_from_url(url)
        if not host:
            results.append((url, desc, float('inf'), False))
            continue
        
        # ping检测
        latency = ping_host(host, timeout=config.PING_TIMEOUT)
        if latency is not None:
            results.append((url, desc, latency, True))
            _log_info(f"镜像 {desc} ({host}): {latency:.1f}ms")
        else:
            results.append((url, desc, float('inf'), False))
            _log_warning(f"镜像 {desc} ({host}): 无法连接")
    
    # 按延迟排序（可用的排在前面）
    results.sort(key=lambda x: (not x[3], x[2]))
    
    # 返回排序后的URL列表
    sorted_urls = [(url, desc) for url, desc, _, available in results if available]
    
    if sorted_urls:
        best = sorted_urls[0]
        _log_info(f"最优镜像: {best[1]}")
    else:
        _log_warning("没有可用的镜像，将按原顺序尝试")
        sorted_urls = [(url, desc) for url, desc, _, _ in results]
    
    return sorted_urls


def get_manifest_urls(use_cache: bool = True) -> List[Tuple[str, str]]:
    """
    获取版本清单的URL列表（已排序）
    
    优先使用 GitCode，其次是 GitHub 及其镜像
    
    参数:
        use_cache: 是否使用缓存，默认为True
        
    返回:
        URL列表，每个元素是 (url, description)
    """
    # 尝试从缓存加载
    if use_cache:
        cached = _load_cache()
        if cached is not None:
            return cached
    
    # URL 列表，按优先级排序
    urls_with_meta = []
    
    # 1. GitCode - 国内优先
    gitcode_manifest_url = f"https://gitcode.com/{config.GITCODE_OWNER}/{config.GITCODE_REPO}/releases/download/latest/update_manifest.json"
    urls_with_meta.append((gitcode_manifest_url, "gitcode", True))
    _log_debug("添加 GitCode 主源")
    
    # 2. GitHub 主源
    urls_with_meta.append((config.GITHUB_UPDATE_MANIFEST_URL, "github-direct", True))
    _log_debug("添加 GitHub 主源")
    
    # 3. GitHub 镜像
    if config.ENABLE_MIRROR and config.MIRROR_URLS:
        for mirror_template, desc, enable_ping in config.MIRROR_URLS:
            try:
                # 构建镜像 URL
                mirror_url = mirror_template.format(
                    owner=config.GITHUB_OWNER,
                    repo=config.GITHUB_REPO,
                    tag="latest",
                    filename="update_manifest.json"
                )
                urls_with_meta.append((mirror_url, desc, enable_ping))
                _log_debug(f"添加镜像: {desc}")
            except Exception as e:
                _log_warning(f"构建镜像 URL 失败: {e}")
    
    # 检测并排序所有 URL
    if urls_with_meta:
        urls = select_best_mirror(urls_with_meta)
        
        # 保存到缓存
        if use_cache:
            _save_cache(urls)
    else:
        urls = []
    
    return urls


def refresh_mirror_cache() -> List[Tuple[str, str]]:
    """
    刷新镜像缓存
    
    强制重新检测所有镜像并更新缓存
    
    返回:
        新的镜像URL列表
    """
    _log_info("强制刷新镜像缓存...")
    clear_cache()
    return get_manifest_urls(use_cache=False)
