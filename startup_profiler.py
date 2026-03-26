#!/usr/bin/env python3
"""
启动性能分析脚本
用于测量和验证启动优化效果

使用方法:
    python startup_profiler.py

输出:
    启动各阶段的耗时报告
"""

import time
import sys
import os

# 记录启动开始时间
_STARTUP_T0 = time.perf_counter()
_MARKS = []

def mark(label: str):
    """记录一个时间点"""
    elapsed = (time.perf_counter() - _STARTUP_T0) * 1000
    _MARKS.append((elapsed, label))
    print(f"[PERF] +{elapsed:6.0f}ms  {label}")

def report():
    """输出性能报告"""
    print("\n" + "="*60)
    print("启动性能报告")
    print("="*60)
    prev = 0
    for ms, label in _MARKS:
        delta = ms - prev
        bar = "█" * max(1, int(delta // 20))
        print(f"  {ms:6.0f}ms (+{delta:4.0f}ms) {bar} {label}")
        prev = ms
    print("="*60)

# 在 main.py 开始处插入以下代码:
# from startup_profiler import mark, report
# mark("程序启动")

# 在关键位置插入 mark() 调用:
# mark("QApplication 创建")
# mark("MainWindow.__init__ 开始")
# mark("MainWindow.__init__ 完成")
# mark("show_main_interface 开始")
# mark("ImageLibraryPage 构造完成")
# mark("启动完成，用户可交互")

# 在程序完全加载后调用:
# report()

if __name__ == "__main__":
    print("启动性能分析模块已加载")
    print("将此模块导入到 main.py 中，在关键位置调用 mark() 和 report()")
