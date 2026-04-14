# 测试 pynput 导入的脚本
# 用于验证打包后 pynput 是否可以正常工作

import sys
import os

print("=" * 80)
print("pynput 导入测试")
print("=" * 80)

# 测试步骤 1：直接导入 pynput.keyboard 的类
print("\n步骤 1：尝试直接导入 pynput.keyboard 的类...")
try:
    from pynput.keyboard import GlobalHotKeys, Listener, Key, KeyCode
    print("✓ 成功导入: GlobalHotKeys, Listener, Key, KeyCode")
except ImportError as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)

# 测试步骤 2：导入 pynput 主模块
print("\n步骤 2：尝试导入 pynput 主模块...")
try:
    import pynput
    print(f"✓ 成功导入 pynput: {pynput.__file__}")
except ImportError as e:
    print(f"✗ 导入失败: {e}")

# 测试步骤 3：导入 pynput.keyboard 子模块
print("\n步骤 3：尝试导入 pynput.keyboard 子模块...")
try:
    from pynput import keyboard
    print(f"✓ 成功导入 keyboard: {keyboard.__file__}")
except ImportError as e:
    print(f"✗ 导入失败: {e}")

# 测试步骤 4：检查 sys.modules 中的 pynput 相关模块
print("\n步骤 4：检查 sys.modules 中的 pynput 相关模块...")
pynput_modules = {k: v for k, v in sys.modules.items() if 'pynput' in k.lower()}
print(f"找到 {len(pynput_modules)} 个 pynput 相关模块:")
for mod_name in sorted(pynput_modules.keys()):
    mod = sys.modules[mod_name]
    if hasattr(mod, '__file__'):
        print(f"  - {mod_name}: {mod.__file__}")
    else:
        print(f"  - {mod_name}: (无 __file__ 属性)")

# 测试步骤 5：尝试创建 GlobalHotKeys 实例
print("\n步骤 5：尝试创建 GlobalHotKeys 实例...")
try:
    def test_callback():
        print("测试回调被触发")
    
    hotkey_mapping = {
        '<ctrl>+<shift>+t': test_callback
    }
    
    hotkeys = GlobalHotKeys(hotkey_mapping)
    print("✓ 成功创建 GlobalHotKeys 实例")
    print(f"  快捷键映射: {hotkey_mapping}")
except Exception as e:
    print(f"✗ 创建失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
