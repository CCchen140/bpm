#!/usr/bin/env python3
"""
栖图自动升级系统 - 版本检查模块

负责从 GitHub 获取最新版本信息，计算升级路径
支持链路测试模式，可识别 _test 结尾的测试版本
"""

import json
import re
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal, QThread

from . import update_config as config


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
        logger.debug(f"[UpdateChecker] {msg}")


def _log_info(msg: str):
    """记录info日志"""
    logger = _get_logger()
    if logger:
        logger.info(f"[UpdateChecker] {msg}")


def _log_warning(msg: str):
    """记录warning日志"""
    logger = _get_logger()
    if logger:
        logger.warning(f"[UpdateChecker] {msg}")


def _log_error(msg: str, exc: Exception = None):
    """记录error日志"""
    logger = _get_logger()
    if logger:
        if exc:
            logger.exception(f"[UpdateChecker] {msg}", exc)
        else:
            logger.error(f"[UpdateChecker] {msg}")


class VersionInfo:
    """版本信息类"""
    
    def __init__(self, version_str: str):
        """
        初始化版本信息
        
        参数:
            version_str: 版本号字符串，如 "0.0.4" 或 "0.0.4_update2"
        """
        self.original = version_str
        self.base = ""
        self.update = 0
        self.is_test = False
        self._parse(version_str)
    
    def _parse(self, version_str: str):
        """
        解析版本号
        
        参数:
            version_str: 版本号字符串
        """
        # 移除 V/v 前缀
        v = version_str.strip()
        if v.upper().startswith('V'):
            v = v[1:]
        
        # 检查是否为测试版本
        if v.endswith(config.TEST_VERSION_SUFFIX):
            self.is_test = True
            v = v[:-len(config.TEST_VERSION_SUFFIX)]
        
        # 匹配版本号格式
        pattern = config.VERSION_PATTERN
        match = re.match(pattern, v)
        
        if match:
            major, minor, patch, update = match.groups()
            self.base = f"{major}.{minor}.{patch}"
            self.update = int(update) if update else 0
        else:
            # 尝试简单解析
            parts = v.split('_update')
            self.base = parts[0]
            self.update = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    
    def __str__(self) -> str:
        """返回完整版本号"""
        result = f"{self.base}_update{self.update}" if self.update > 0 else self.base
        if self.is_test:
            result += config.TEST_VERSION_SUFFIX
        return result
    
    def __eq__(self, other) -> bool:
        """比较相等（默认忽略 _test 后缀）"""
        if isinstance(other, VersionInfo):
            return (self.base == other.base and 
                    self.update == other.update)
        return False
    
    def __lt__(self, other) -> bool:
        """比较小于（默认忽略 _test 后缀）"""
        if not isinstance(other, VersionInfo):
            other = VersionInfo(str(other))
        
        # 比较基础版本
        self_base = [int(x) for x in self.base.split('.')]
        other_base = [int(x) for x in other.base.split('.')]
        
        if self_base != other_base:
            return self_base < other_base
        
        # 基础版本相同，比较 update 号
        return self.update < other.update
    
    def __le__(self, other) -> bool:
        """比较小于等于"""
        return self == other or self < other
    
    def __gt__(self, other) -> bool:
        """比较大于"""
        return not self <= other
    
    def __ge__(self, other) -> bool:
        """比较大于等于"""
        return not self < other


class UpdateChecker(QObject):
    """
    版本检查器 - 从 GitHub 获取最新版本信息
    """
    
    # 信号定义
    check_completed = pyqtSignal(dict)   # 检查完成，返回更新信息
    check_failed = pyqtSignal(str)       # 检查失败，返回错误信息
    
    def __init__(self):
        """初始化版本检查器"""
        super().__init__()
        self._manifest: Optional[Dict] = None
    
    def check_for_updates(self, current_version: str) -> None:
        """
        检查是否有更新
        
        参数:
            current_version: 当前版本号
        """
        # 在后台线程执行检查
        self._check_thread = CheckUpdateThread(current_version)
        self._check_thread.check_completed.connect(self.check_completed)
        self._check_thread.check_failed.connect(self.check_failed)
        self._check_thread.start()
    
    def parse_version(self, version_str: str) -> VersionInfo:
        """
        解析版本号
        
        参数:
            version_str: 版本号字符串
            
        返回:
            版本信息对象
        """
        return VersionInfo(version_str)
    
    def compare_versions(self, v1: str, v2: str) -> int:
        """
        比较两个版本号
        
        参数:
            v1: 版本1
            v2: 版本2
            
        返回:
            -1: v1 < v2
             0: v1 = v2
             1: v1 > v2
        """
        vi1 = VersionInfo(v1)
        vi2 = VersionInfo(v2)
        
        if vi1 < vi2:
            return -1
        elif vi1 > vi2:
            return 1
        return 0
    
    def calculate_upgrade_path(self, current: str, target: str, manifest: Dict) -> List[Dict]:
        """
        计算升级路径
        
        从当前版本升级到目标版本所需的步骤
        
        参数:
            current: 当前版本
            target: 目标版本
            manifest: 版本清单
            
        返回:
            升级步骤列表
        """
        _log_debug(f"计算升级路径: {current} -> {target}")
        
        current_v = VersionInfo(current)
        target_v = VersionInfo(target)
        
        steps = []
        step_num = 1
        
        # 获取 releases 信息
        releases = manifest.get("releases", {})
        
        # 情况1：同一大版本内的升级
        if current_v.base == target_v.base:
            _log_debug(f"同一大版本内升级: {current_v.base}")
            # 只需要升级 update 版本
            for update_num in range(current_v.update + 1, target_v.update + 1):
                update_key = str(update_num)
                if current_v.base in releases and update_key in releases[current_v.base].get("updates", {}):
                    update_info = releases[current_v.base]["updates"][update_key]
                    step_info = {
                        "step": step_num,
                        "from": str(current_v) if step_num == 1 else f"{current_v.base}_update{update_num - 1}",
                        "to": f"{current_v.base}_update{update_num}",
                        "package": update_info.get("package", f"qitu_V{current_v.base}_update{update_num}.zip"),
                        "url": update_info.get("url", ""),
                        "size": update_info.get("size", 0),
                        "hash": update_info.get("hash", ""),
                        "download_path": "",
                        "tag": update_info.get("tag", "")
                    }
                    # 添加分包信息（如果有）
                    if update_info.get("is_split", False):
                        step_info["is_split"] = True
                        step_info["parts"] = update_info.get("parts", [])
                    steps.append(step_info)
                    step_num += 1
            return steps
        
        # 情况2：跨大版本升级
        _log_debug(f"跨大版本升级: {current_v.base} -> {target_v.base}")
        
        # 第一步：升级到目标大版本的基础版（使用增量包）
        if target_v.base in releases:
            release_info = releases[target_v.base]
            cross_upgrade = release_info.get("cross_upgrade", {})
            
            # 检查是否有从当前基础版本升级的包
            if cross_upgrade.get("from_base") == current_v.base:
                # 构建包名，测试版本使用 _test 后缀
                if target_v.is_test:
                    package_name = f"qitu_V{target_v.base}{config.TEST_VERSION_SUFFIX}.zip"
                else:
                    package_name = f"qitu_V{target_v.base}.zip"
                
                _log_debug(f"找到跨版本升级包: {package_name}")
                
                step_info = {
                    "step": step_num,
                    "from": str(current_v),
                    "to": target_v.base,
                    "package": cross_upgrade.get("package", package_name),
                    "url": cross_upgrade.get("url", ""),
                    "size": cross_upgrade.get("size", 0),
                    "hash": cross_upgrade.get("hash", ""),
                    "download_path": "",
                    "tag": cross_upgrade.get("tag", "")
                }
                # 添加分包信息（如果有）
                if cross_upgrade.get("is_split", False):
                    step_info["is_split"] = True
                    step_info["parts"] = cross_upgrade.get("parts", [])
                steps.append(step_info)
                step_num += 1
            else:
                # 没有直接的跨版本包，需要找到中间版本
                # 这里简化处理，假设总是有跨版本包
                _log_error(f"不支持从 {current_v.base} 直接升级到 {target_v.base}")
                raise ValueError(f"不支持从 {current_v.base} 直接升级到 {target_v.base}")
        
        # 第二步：如果目标有 update，继续升级
        if target_v.update > 0:
            for update_num in range(1, target_v.update + 1):
                update_key = str(update_num)
                if target_v.base in releases and update_key in releases[target_v.base].get("updates", {}):
                    update_info = releases[target_v.base]["updates"][update_key]
                    from_version = target_v.base if update_num == 1 else f"{target_v.base}_update{update_num - 1}"
                    step_info = {
                        "step": step_num,
                        "from": from_version,
                        "to": f"{target_v.base}_update{update_num}",
                        "package": update_info.get("package", f"qitu_V{target_v.base}_update{update_num}.zip"),
                        "url": update_info.get("url", ""),
                        "size": update_info.get("size", 0),
                        "hash": update_info.get("hash", ""),
                        "download_path": "",
                        "tag": update_info.get("tag", "")
                    }
                    # 添加分包信息（如果有）
                    if update_info.get("is_split", False):
                        step_info["is_split"] = True
                        step_info["parts"] = update_info.get("parts", [])
                    steps.append(step_info)
                    step_num += 1
        
        return steps


class CheckUpdateThread(QThread):
    """
    检查更新后台线程
    """
    
    check_completed = pyqtSignal(dict)
    check_failed = pyqtSignal(str)
    
    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version
    
    def run(self):
        """执行检查"""
        try:
            # 获取版本清单
            manifest = self._fetch_manifest()
            if not manifest:
                self.check_failed.emit("无法获取版本清单")
                return
            
            # 获取最新版本
            latest_version = manifest.get("latest_version", "")
            if not latest_version:
                self.check_failed.emit("版本清单中未找到最新版本信息")
                return
            
            # 检查是否为测试版本
            latest_v = VersionInfo(latest_version)
            _log_debug(f"最新版本: {latest_version}, 测试版本: {latest_v.is_test}")
            
            if latest_v.is_test and not config.LINK_TEST_MODE:
                # 最新版本是测试版本，但链路测试模式未启用
                _log_info("链路测试模式未启用，跳过测试版本")
                self.check_completed.emit({
                    "has_update": False,
                    "current_version": self.current_version,
                    "latest_version": latest_version,
                    "message": "链路测试模式未启用，跳过测试版本"
                })
                return
            
            # 比较版本
            checker = UpdateChecker()
            comparison = checker.compare_versions(self.current_version, latest_version)
            
            # 检查是否为同版本（忽略 _test 后缀）
            current_v = VersionInfo(self.current_version)
            is_same_version = (current_v.base == latest_v.base and 
                              current_v.update == latest_v.update)
            
            if comparison >= 0 and not (is_same_version and config.SAME_VERSION_UPGRADE):
                # 当前版本已是最新或更新，且不满足同版本升级条件
                _log_info(f"当前版本已是最新: {self.current_version}")
                self.check_completed.emit({
                    "has_update": False,
                    "current_version": self.current_version,
                    "latest_version": latest_version
                })
                return
            
            # 有更新，计算升级路径
            _log_info(f"发现新版本: {latest_version}")
            try:
                upgrade_steps = checker.calculate_upgrade_path(
                    self.current_version, 
                    latest_version, 
                    manifest
                )
            except ValueError as e:
                _log_error("计算升级路径失败", e)
                self.check_failed.emit(str(e))
                return
            
            _log_info(f"升级路径计算完成，共 {len(upgrade_steps)} 步")

            # 获取目标版本的更新内容
            # 从 manifest 的 releases 中获取对应版本的 changelog
            target_changelog = ""
            releases = manifest.get("releases", {})
            if latest_v.base in releases:
                release_info = releases[latest_v.base]
                if latest_v.update > 0:
                    # 获取 update 版本的 changelog
                    update_key = str(latest_v.update)
                    if update_key in release_info.get("updates", {}):
                        target_changelog = release_info["updates"][update_key].get("changelog", "")
                else:
                    # 获取基础版本的 changelog
                    target_changelog = release_info.get("changelog", "")

            # 如果目标版本没有 changelog，使用全局 changelog
            if not target_changelog:
                target_changelog = manifest.get("changelog", "")

            # 组装更新信息
            update_info = {
                "has_update": True,
                "current_version": self.current_version,
                "latest_version": latest_version,
                "release_date": manifest.get("release_date", ""),
                "changelog": target_changelog,
                "force_update": manifest.get("force_update", False),
                "min_supported_version": manifest.get("min_supported_version", config.MIN_SUPPORTED_VERSION),
                "upgrade_steps": upgrade_steps,
                "total_steps": len(upgrade_steps),
                "total_size": sum(step.get("size", 0) for step in upgrade_steps),
                "is_test_version": latest_v.is_test  # 标记是否为测试版本
            }
            
            self.check_completed.emit(update_info)
            
        except Exception as e:
            _log_error("检查更新时发生错误", e)
            self.check_failed.emit(f"检查更新时发生错误: {str(e)}")
    
    def _fetch_manifest(self) -> Optional[Dict]:
        """
        获取版本清单
        
        支持自动切换到镜像地址（使用ping检测选择最优镜像）
        
        返回:
            版本清单字典
        """
        # 根据链路测试模式选择 manifest URL
        if config.LINK_TEST_MODE and config.LINK_TEST_MANIFEST_URL:
            urls = [(config.LINK_TEST_MANIFEST_URL, "link-test")]
            _log_debug(f"使用链路测试模式 manifest URL")
        else:
            # 使用镜像选择器获取排序后的 URL 列表
            from .mirror_selector import get_manifest_urls
            urls = get_manifest_urls()
            _log_debug(f"将尝试 {len(urls)} 个地址获取版本清单")
        
        # 尝试所有 URL
        last_error = None
        for url_index, (url, desc) in enumerate(urls):
            _log_debug(f"尝试地址 {url_index + 1}/{len(urls)} [{desc}]")
            
            # 创建请求
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'BirdPictureManager-UpdateChecker/1.0',
                    'Accept': 'application/json'
                }
            )
            
            # 带重试的请求
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    _log_debug(f"正在获取版本清单... (尝试 {attempt + 1}/{max_retries})")
                    with urllib.request.urlopen(
                        req, 
                        timeout=10  # 检查更新使用10秒超时，避免等待太久
                    ) as response:
                        data = response.read().decode('utf-8')
                        manifest = json.loads(data)
                        _log_info(f"版本清单获取成功，使用镜像: {desc}")
                        return manifest
                except (TimeoutError, urllib.error.URLError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        _log_warning(f"获取清单失败，1秒后重试...")
                        import time
                        time.sleep(1)
                    else:
                        break
                except Exception as e:
                    last_error = e
                    break
        
        # 所有地址都失败了
        _log_error("所有地址都无法获取版本清单")
        
        # 清除镜像缓存，下次检查时会重新测试镜像可用性
        from .mirror_selector import clear_cache
        clear_cache()
        _log_info("已清除镜像缓存，下次检查时将重新测试镜像可用性")
        
        if isinstance(last_error, urllib.error.HTTPError):
            _log_error(f"HTTP 错误: {last_error.code} - {last_error.reason}")
            raise Exception(f"HTTP 错误: {last_error.code} - {last_error.reason}")
        elif isinstance(last_error, urllib.error.URLError):
            # URLError 的 reason 可能是 TimeoutError 或其他异常
            reason = last_error.reason
            if isinstance(reason, TimeoutError) or (isinstance(reason, str) and 'timed out' in str(reason).lower()):
                _log_error("获取版本清单超时")
                raise Exception("连接超时，请检查网络或稍后重试")
            else:
                _log_error(f"网络错误: {reason}")
                raise Exception(f"网络错误: {reason}")
        elif isinstance(last_error, TimeoutError):
            _log_error("获取版本清单超时")
            raise Exception("连接超时，请检查网络或稍后重试")
        elif isinstance(last_error, json.JSONDecodeError):
            _log_error(f"JSON 解析错误: {str(last_error)}")
            raise Exception(f"JSON 解析错误: {str(last_error)}")
        else:
            _log_error(f"获取清单失败: {str(last_error)}")
            raise Exception(f"获取清单失败: {str(last_error)}")


def test_version_comparison():
    """测试版本比较"""
    checker = UpdateChecker()
    
    # 测试用例
    test_cases = [
        ("0.0.4", "0.0.5", -1),
        ("0.0.5", "0.0.4", 1),
        ("0.0.4", "0.0.4", 0),
        ("0.0.4_update1", "0.0.4_update2", -1),
        ("0.0.4_update2", "0.0.4_update1", 1),
        ("0.0.4", "0.0.4_update1", -1),
        ("0.0.4_update1", "0.0.5", -1),
        ("V0.0.4", "0.0.5", -1),
        # 测试版本测试
        ("0.0.4", "0.0.5_test", -1),
        ("0.0.5", "0.0.5_test", -1),  # 正式版本 < 测试版本
        ("0.0.5_test", "0.0.5", 1),   # 测试版本 > 正式版本
    ]
    
    for v1, v2, expected in test_cases:
        result = checker.compare_versions(v1, v2)
        status = "✓" if result == expected else "✗"
        print(f"{status} compare_versions({v1}, {v2}) = {result} (expected {expected})")


if __name__ == "__main__":
    # 运行测试
    test_version_comparison()
