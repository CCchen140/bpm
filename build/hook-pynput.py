# PyInstaller hook for pynput
# 确保 pynput 的所有子模块都被正确收集

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# 强制导入 pynput 以确保它被收集
try:
    import pynput
    from pynput import keyboard
    from pynput import mouse
    from pynput.keyboard import _win32, _base, _dummy
    from pynput.mouse import _win32, _base, _dummy
    from pynput._util import win32, win32_vks
    print(f"[hook-pynput] 成功导入 pynput: {pynput.__file__}")
    print(f"[hook-pynput] 成功导入 keyboard: {keyboard.__file__}")
except Exception as e:
    print(f"[hook-pynput] 导入 pynput 失败: {e}")

# 收集 pynput 的所有子模块、数据文件和二进制文件
datas, binaries, hiddenimports = collect_all("pynput")

# 额外收集所有子模块（递归）
try:
    all_submodules = collect_submodules("pynput")
    print(f"[hook-pynput] collect_submodules 收集到 {len(all_submodules)} 个模块")
    hiddenimports += all_submodules
except Exception as e:
    print(f"[hook-pynput] collect_submodules 失败: {e}")

# 收集数据文件
try:
    pynput_datas = collect_data_files("pynput")
    print(f"[hook-pynput] collect_data_files 收集到 {len(pynput_datas)} 个数据文件")
    datas += pynput_datas
except Exception as e:
    print(f"[hook-pynput] collect_data_files 失败: {e}")

# 显式添加可能被遗漏的模块（确保包含所有子包）
# 注意：不要包含 .__init__ 后缀，这会导致错误的文件结构
explicit_modules = [
    # pynput 主包
    "pynput",
    # keyboard 子包
    "pynput.keyboard",
    "pynput.keyboard._base",
    "pynput.keyboard._win32",
    "pynput.keyboard._dummy",
    "pynput.keyboard._darwin",
    "pynput.keyboard._xorg",
    "pynput.keyboard._uinput",
    # mouse 子包
    "pynput.mouse",
    "pynput.mouse._base",
    "pynput.mouse._win32",
    "pynput.mouse._dummy",
    "pynput.mouse._darwin",
    "pynput.mouse._xorg",
    # _util 子包
    "pynput._util",
    "pynput._util.win32",
    "pynput._util.win32_vks",
    "pynput._util.darwin",
    "pynput._util.darwin_vks",
    "pynput._util.xorg",
    "pynput._util.xorg_keysyms",
    "pynput._util.uinput",
]

# 添加显式模块到 hiddenimports
for mod in explicit_modules:
    if mod not in hiddenimports:
        hiddenimports.append(mod)

print(f"[hook-pynput] 最终收集到 {len(datas)} 个数据文件")
print(f"[hook-pynput] 最终收集到 {len(binaries)} 个二进制文件")
print(f"[hook-pynput] 最终收集到 {len(hiddenimports)} 个隐藏导入")
print(f"[hook-pynput] 隐藏导入列表: {hiddenimports}")
