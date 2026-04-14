# Runtime hook for pynput
# 确保在程序启动时正确初始化 pynput 的子模块
# 解决打包后 pynput.keyboard 无法导入的问题

import sys
import os

# 在程序启动时预先导入 pynput 的关键模块
# 这可以解决延迟导入导致的模块无法找到的问题
try:
    # 强制导入 pynput.keyboard 的所有关键模块
    import pynput.keyboard
    import pynput.keyboard._base
    import pynput.keyboard._win32
    import pynput.keyboard._dummy
    
    # 强制导入 pynput.mouse 的所有关键模块（如果需要）
    import pynput.mouse
    import pynput.mouse._base
    import pynput.mouse._win32
    import pynput.mouse._dummy
    
    # 强制导入 pynput._util 的关键模块
    import pynput._util
    import pynput._util.win32
    import pynput._util.win32_vks
    
    # 确保这些模块在 sys.modules 中
    # 这样后续的导入就可以直接找到它们
    print("[Runtime Hook] pynput 模块预加载成功")
except Exception as e:
    print(f"[Runtime Hook] pynput 模块预加载失败: {e}")
    # 不抛出异常，允许程序继续运行
    # 程序会使用 Qt 快捷键备用方案
