#!/usr/bin/env python3
"""
栖图自动升级系统 - 配置文件

集中管理所有与升级相关的配置项
"""

import os
import sys

# =============================================================================
# GitHub 配置
# =============================================================================

# GitHub 仓库信息
GITHUB_OWNER = "CCchen140"  # GitHub 用户名
GITHUB_REPO = "qitupage"      # 仓库名称
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_RELEASES_URL = f"{GITHUB_API_BASE}/releases"
GITHUB_LATEST_RELEASE_URL = f"{GITHUB_API_BASE}/releases/latest"

# 版本清单文件 URL（可以放在 GitHub Release 的 Assets 中，或者放在其他 CDN）
# 建议将 update_manifest.json 上传到每个 Release 的 Assets 中
UPDATE_MANIFEST_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download/update_manifest.json"

# 备用镜像地址（可选）
# 当 GitHub 访问不稳定时，会尝试使用这些镜像
# 格式: (URL模板, 描述, 是否启用ping检测)
MIRROR_URLS = [
    # GitHub 代理镜像 - 下载加速
    ("https://ghproxy.com/https://github.com/{owner}/{repo}/releases/download/{tag}/{filename}", "ghproxy", True),
    ("https://mirror.ghproxy.com/https://github.com/{owner}/{repo}/releases/download/{tag}/{filename}", "mirror.ghproxy", True),
    ("https://hub.gitmirror.com/https://github.com/{owner}/{repo}/releases/download/{tag}/{filename}", "hub.gitmirror", True),
    
    # GitHub 访问加速 - 替换域名方式
    ("https://githubfast.com/{owner}/{repo}/releases/download/{tag}/{filename}", "githubfast", True),
    ("https://kgithub.com/{owner}/{repo}/releases/download/{tag}/{filename}", "kgithub", True),
    ("https://hub.fastgit.org/{owner}/{repo}/releases/download/{tag}/{filename}", "fastgit", True),
    ("https://github.com.cnpmjs.org/{owner}/{repo}/releases/download/{tag}/{filename}", "cnpmjs", True),
    
    # GitHub CDN - jsDelivr（适合静态文件）
    # 注意：jsDelivr 有缓存，可能不是最新版本
    # ("https://gcore.jsdelivr.net/gh/{owner}/{repo}@{tag}/{filename}", "jsdelivr-gcore", False),
    # ("https://fastly.jsdelivr.net/gh/{owner}/{repo}@{tag}/{filename}", "jsdelivr-fastly", False),
    # ("https://jsd.onmicrosoft.cn/gh/{owner}/{repo}@{tag}/{filename}", "jsdelivr-cn", False),
    # ("https://jsd.cdn.zzko.cn/gh/{owner}/{repo}@{tag}/{filename}", "jsdelivr-zzko", False),
]

# 是否启用镜像（自动切换）
ENABLE_MIRROR = True

# 镜像超时时间（秒）
MIRROR_TIMEOUT = 15

# 是否启用ping检测（检测哪个镜像最快）
ENABLE_PING_CHECK = True

# ping检测超时时间（秒）
PING_TIMEOUT = 3

# =============================================================================
# 测试模式配置
# =============================================================================

# 测试模式开关
# 设置为 True 时：
#   - 升级流程会在下载和解压完成后停止
#   - 不会执行实际的文件替换操作
#   - 不会清理临时文件
#   - 不会启动主程序
# 用于测试升级包是否正确下载和解压
TEST_MODE = False

# 测试模式下的模拟版本（用于测试版本检查逻辑）
TEST_CURRENT_VERSION = "0.0.4"
TEST_TARGET_VERSION = "0.0.5_update1"

# =============================================================================
# 链路测试模式配置
# =============================================================================

# 链路测试模式开关
# 开启后，可以识别和下载以 _test 结尾的测试版本
# 测试版本包内容为空，仅用于验证升级链路
LINK_TEST_MODE = False  # 默认 False

# 测试版本后缀
TEST_VERSION_SUFFIX = "_test"

# 测试版本 manifest URL（可选，用于测试不同的 manifest）
# 如果为空，则使用正常的 UPDATE_MANIFEST_URL
LINK_TEST_MANIFEST_URL = ""

# 同版本升级开关
# 开启后，即使当前版本与目标版本相同（忽略 _test 后缀），也允许升级
# 用于测试同版本的升级流程
SAME_VERSION_UPGRADE = False  # 默认 False

# 强制提示已忽略版本开关
# 开启后，检测到已忽略的版本时会按照未忽略来提示
# 用于测试忽略版本功能
FORCE_SHOW_IGNORED_VERSION = False  # 默认 False

# =============================================================================
# 路径配置
# =============================================================================

def get_update_cache_dir() -> str:
    """
    获取升级缓存目录

    返回:
        缓存目录路径
    """
    # 如果是打包后的程序，使用可执行文件所在目录
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境，使用代码目录
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "cache", "update")


def get_diff_cache_dir() -> str:
    """
    获取差异文件清单缓存目录

    返回:
        差异清单缓存目录路径 (/cache/diff/)
    """
    # 如果是打包后的程序，使用可执行文件所在目录
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境，使用代码目录
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    diff_dir = os.path.join(base_dir, "cache", "diff")
    os.makedirs(diff_dir, exist_ok=True)
    return diff_dir


def get_update_config_dir() -> str:
    """
    获取升级配置目录
    
    返回:
        配置目录路径
    """
    try:
        # 使用 PathManager 的统一用户配置目录
        from utils.paths import PathManager
        pm = PathManager.instance()
        config_dir = pm.get_user_setting_dir() / "update"
        config_dir.mkdir(parents=True, exist_ok=True)
        return str(config_dir)
    except Exception:
        # 回退到程序目录下的 config/update
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "config", "update")


# 升级计划文件名
UPDATE_PLAN_FILENAME = "update_plan.json"
IGNORED_VERSIONS_FILENAME = "ignored_versions.json"

# =============================================================================
# 分包配置
# =============================================================================

# GitHub Releases 单文件大小限制 (2GB = 2 * 1024 * 1024 * 1024 字节)
GITHUB_FILE_SIZE_LIMIT = 2 * 1024 * 1024 * 1024  # 2GB

# 分包大小（建议 1.9GB，留有余量）
PART_SIZE = 1900 * 1024 * 1024  # 1.9GB

# 分包文件后缀模板
PART_SUFFIX_TEMPLATE = ".part{part_num:03d}"

# 最大分包数量
MAX_PARTS = 10

# =============================================================================
# 网络配置
# =============================================================================

# 下载超时设置（秒）
DOWNLOAD_TIMEOUT = 300          # 总下载超时
DOWNLOAD_CONNECT_TIMEOUT = 30   # 连接超时
DOWNLOAD_READ_TIMEOUT = 60      # 读取超时

# 重试配置
DOWNLOAD_MAX_RETRIES = 3        # 最大重试次数
DOWNLOAD_RETRY_DELAY = 2        # 重试间隔（秒）

# 分块下载配置
DOWNLOAD_CHUNK_SIZE = 8192      # 下载块大小（字节）

# =============================================================================
# 升级配置
# =============================================================================

# 检查更新间隔（小时）
CHECK_INTERVAL_HOURS = 24

# 是否强制检查更新（忽略间隔）
FORCE_CHECK = False

# 升级包文件名模板
# 支持的变量: {version}, {update_num}
# 注意: GitHub 不支持中文文件名，使用 qitu_ 前缀
UPDATE_PACKAGE_NAME_TEMPLATE = "qitu_V{version}_update{update_num}.zip"
BASE_PACKAGE_NAME_TEMPLATE = "qitu_V{version}.zip"

# =============================================================================
# 版本配置
# =============================================================================

# 最低支持的版本（低于此版本必须强制升级）
MIN_SUPPORTED_VERSION = "0.0.1"

# 版本号解析正则
VERSION_PATTERN = r"^(\d+)\.(\d+)\.(\d+)(?:_update(\d+))?$"

# =============================================================================
# UI 配置
# =============================================================================

# 对话框标题
UPDATE_DIALOG_TITLE = "发现新版本"
PROGRESS_DIALOG_TITLE = "正在升级"

# 对话框尺寸
UPDATE_DIALOG_WIDTH = 560
UPDATE_DIALOG_HEIGHT = 480
PROGRESS_DIALOG_WIDTH = 500
PROGRESS_DIALOG_HEIGHT = 300

# =============================================================================
# 日志配置
# =============================================================================

# 升级日志文件名
UPDATE_LOG_FILENAME = "update.log"

# 日志级别
UPDATE_LOG_LEVEL = "INFO"

# =============================================================================
# 错误码定义
# =============================================================================

ERROR_CODES = {
    0: "成功",
    1: "网络错误",
    2: "下载失败",
    3: "文件校验失败",
    4: "安装失败",
    5: "权限不足",
    6: "磁盘空间不足",
    7: "升级包损坏",
    8: "升级被中断",
    9: "未知错误",
    10: "版本解析错误",
    11: "升级路径计算错误",
    12: "配置文件错误",
}


def get_error_message(code: int) -> str:
    """
    获取错误码对应的错误信息
    
    参数:
        code: 错误码
        
    返回:
        错误信息
    """
    return ERROR_CODES.get(code, f"未知错误 (代码: {code})")


# =============================================================================
# 辅助函数
# =============================================================================

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


def get_update_plan_path() -> str:
    """
    获取升级计划文件路径
    
    返回:
        文件路径
    """
    return os.path.join(get_update_cache_dir(), UPDATE_PLAN_FILENAME)


def get_ignored_versions_path() -> str:
    """
    获取忽略版本记录文件路径
    
    返回:
        文件路径
    """
    return os.path.join(get_update_config_dir(), IGNORED_VERSIONS_FILENAME)


def get_update_log_path() -> str:
    """
    获取升级日志文件路径
    
    返回:
        文件路径
    """
    return os.path.join(get_update_cache_dir(), UPDATE_LOG_FILENAME)


# =============================================================================
# 升级历史记录配置
# =============================================================================

# 升级历史记录目录名
HISTORY_DIR_NAME = "history"
BACKUP_DIR_NAME = "backups"


def get_history_dir() -> str:
    """
    获取升级历史记录目录
    
    返回:
        历史记录目录路径
    """
    base_dir = get_update_config_dir()
    return os.path.join(base_dir, HISTORY_DIR_NAME)


def get_backup_dir() -> str:
    """
    获取备份文件目录
    
    返回:
        备份目录路径
    """
    base_dir = get_update_config_dir()
    return os.path.join(base_dir, BACKUP_DIR_NAME)


# 历史记录文件名
HISTORY_FILENAME = "update_history.json"

# 最大历史记录数量
MAX_HISTORY_ENTRIES = 50

# 最大备份文件数量
MAX_BACKUP_COUNT = 10


# =============================================================================
# 应用目录配置
# =============================================================================

def get_app_dir() -> str:
    """
    获取应用主目录
    
    返回:
        应用目录路径
    """
    # 获取程序所在目录
    if getattr(sys, 'frozen', False):
        # 打包后的程序
        return os.path.dirname(sys.executable)
    else:
        # 开发环境
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 缓存目录
CACHE_DIR = get_update_cache_dir()

# 历史记录目录
HISTORY_DIR = get_history_dir()

# 备份目录
BACKUP_DIR = get_backup_dir()
