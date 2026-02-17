"""
检查侧边栏按钮是否正确创建
"""
import sys
import os

project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

print("检查 main_window.py 中的按钮代码...")
print()

with open(os.path.join(project_root, "ui/main_window.py"), "r", encoding="utf-8") as f:
    content = f.read()

# 检查关键代码
checks = [
    ("Web 按钮创建", "self.btn_library_web = QPushButton()"),
    ("Web 按钮添加到布局", "icon_layout.addWidget(self.btn_library_web)"),
    ("Web 按钮添加到按钮组", "self.sidebar_btn_group.addButton(self.btn_library_web, 6)"),
    ("Web 按钮添加到列表", "self._sidebar_buttons.append(self.btn_library_web)"),
]

all_ok = True
for name, code in checks:
    if code in content:
        print(f"[OK] {name}")
    else:
        print(f"[FAIL] {name}")
        all_ok = False

print()
if all_ok:
    print("[SUCCESS] 所有代码都已正确添加！")
    print()
    print("如果运行程序后看不到按钮，可能是：")
    print("  1. 窗口高度不够，按钮在屏幕外")
    print("  2. 需要滚动侧边栏")
    print("  3. 图标加载失败（应该显示字母 W）")
    print()
    print("解决方法：")
    print("  - 最大化窗口")
    print("  - 查看侧边栏最下方")
    print("  - 查找显示 'W' 的按钮")
else:
    print("[FAIL] 代码不完整，请检查！")

