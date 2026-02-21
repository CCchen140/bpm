#!/usr/bin/env python3
"""
XMP接口验证脚本
测试程序中的XMP读写接口是否正确工作
"""

import os
import sys
import tempfile
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.exif.exif_utils import ExifHandleWorker, EXIF_TAG, _get_exif_write_mode, _to_sidecar_xmp_path
from utils.setting.settings_manager import SettingsManager


def create_test_image():
    """创建一个测试用的图片文件"""
    # 创建一个简单的测试图片
    try:
        from PIL import Image
        img = Image.new('RGB', (100, 100), color='red')
        fd, path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        img.save(path, 'JPEG')
        return path
    except ImportError:
        # 如果没有PIL，创建一个空文件
        fd, path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        with open(path, 'wb') as f:
            # 写入最小的JPEG头
            f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9')
        return path


def test_xmp_path_conversion():
    """测试XMP路径转换函数"""
    print("\n=== 测试XMP路径转换 ===")
    
    test_cases = [
        ("C:/photos/image.jpg", "C:/photos/image.xmp"),
        ("/home/user/photo.png", "/home/user/photo.xmp"),
        ("C:/photos/image.XMP", "C:/photos/image.XMP"),  # 已经是XMP
        ("image.jpeg", "image.xmp"),
    ]
    
    all_passed = True
    for input_path, expected in test_cases:
        result = _to_sidecar_xmp_path(input_path)
        # 统一路径分隔符进行比较
        result_norm = result.replace('\\', '/')
        expected_norm = expected.replace('\\', '/')
        
        if result_norm == expected_norm:
            print(f"✓ PASS: {input_path} -> {result}")
        else:
            print(f"✗ FAIL: {input_path}")
            print(f"  期望: {expected}")
            print(f"  实际: {result}")
            all_passed = False
    
    return all_passed


def test_write_mode():
    """测试写入模式获取"""
    print("\n=== 测试写入模式获取 ===")
    
    sm = SettingsManager.instance()
    
    # 保存原始设置
    original_mode = sm.get("exif/write_mode", "file")
    original_disable = sm.get("exif/disable_write", False)
    
    try:
        # 测试 file 模式
        sm.set("exif/write_mode", "file")
        sm.set("exif/disable_write", False)
        mode = _get_exif_write_mode()
        if mode == "file":
            print("✓ PASS: file 模式")
        else:
            print(f"✗ FAIL: 期望 'file', 实际 '{mode}'")
            return False
        
        # 测试 xmp 模式
        sm.set("exif/write_mode", "xmp")
        mode = _get_exif_write_mode()
        if mode == "xmp":
            print("✓ PASS: xmp 模式")
        else:
            print(f"✗ FAIL: 期望 'xmp', 实际 '{mode}'")
            return False
        
        # 测试 none 模式
        sm.set("exif/write_mode", "none")
        mode = _get_exif_write_mode()
        if mode == "none":
            print("✓ PASS: none 模式")
        else:
            print(f"✗ FAIL: 期望 'none', 实际 '{mode}'")
            return False
        
        # 测试 disable_write 覆盖
        sm.set("exif/write_mode", "file")
        sm.set("exif/disable_write", True)
        mode = _get_exif_write_mode()
        if mode == "none":
            print("✓ PASS: disable_write 覆盖生效")
        else:
            print(f"✗ FAIL: disable_write 未生效，模式为 '{mode}'")
            return False
        
        return True
        
    finally:
        # 恢复原始设置
        sm.set("exif/write_mode", original_mode)
        sm.set("exif/disable_write", original_disable)


def test_single_write_read():
    """测试单个文件XMP写入和读取"""
    print("\n=== 测试单个文件XMP写入和读取 ===")
    
    sm = SettingsManager.instance()
    original_mode = sm.get("exif/write_mode", "file")
    
    try:
        # 设置为XMP模式
        sm.set("exif/write_mode", "xmp")
        sm.set("exif/disable_write", False)
        
        # 创建测试图片
        test_image = create_test_image()
        xmp_path = _to_sidecar_xmp_path(test_image)
        
        print(f"测试图片: {test_image}")
        print(f"XMP路径: {xmp_path}")
        
        try:
            worker = ExifHandleWorker.get_instance()
            
            # 测试写入标签
            test_tags = {
                EXIF_TAG.Label.value: "Green",
                EXIF_TAG.Rating.value: "5",
                EXIF_TAG.Object.value: "测试鸟种",
                EXIF_TAG.Description.value: "测试描述",
            }
            
            print("写入标签...")
            worker.write_tags(test_image, test_tags)
            
            # 等待写入完成
            time.sleep(1)
            
            # 检查XMP文件是否创建
            if os.path.exists(xmp_path):
                print(f"✓ XMP文件已创建: {xmp_path}")
                print(f"  文件大小: {os.path.getsize(xmp_path)} bytes")
            else:
                print(f"✗ XMP文件未创建: {xmp_path}")
                return False
            
            # 测试读取标签
            print("读取标签...")
            time.sleep(0.5)
            
            # 读取单个标签
            label = worker.read_tag(test_image, EXIF_TAG.Label.value)
            rating = worker.read_tag(test_image, EXIF_TAG.Rating.value)
            obj = worker.read_tag(test_image, EXIF_TAG.Object.value)
            desc = worker.read_tag(test_image, EXIF_TAG.Description.value)
            
            print(f"  Label: {label} (期望: Green)")
            print(f"  Rating: {rating} (期望: 5)")
            print(f"  Object: {obj} (期望: 测试鸟种)")
            print(f"  Description: {desc} (期望: 测试描述)")
            
            # 验证结果
            passed = True
            if label != "Green":
                print(f"✗ Label 不匹配")
                passed = False
            else:
                print("✓ Label 正确")
                
            if str(rating) != "5":
                print(f"✗ Rating 不匹配: {rating}")
                passed = False
            else:
                print("✓ Rating 正确")
            
            if obj != "测试鸟种":
                print(f"✗ Object 不匹配: {obj}")
                passed = False
            else:
                print("✓ Object 正确")
            
            return passed
            
        finally:
            # 清理
            try:
                if os.path.exists(test_image):
                    os.remove(test_image)
                if os.path.exists(xmp_path):
                    os.remove(xmp_path)
            except:
                pass
                
    finally:
        sm.set("exif/write_mode", original_mode)


def test_batch_write_read():
    """测试批量XMP写入和读取"""
    print("\n=== 测试批量XMP写入和读取 ===")
    
    sm = SettingsManager.instance()
    original_mode = sm.get("exif/write_mode", "file")
    
    try:
        sm.set("exif/write_mode", "xmp")
        sm.set("exif/disable_write", False)
        
        # 创建多个测试图片
        test_images = []
        xmp_paths = []
        for i in range(3):
            img_path = create_test_image()
            test_images.append(img_path)
            xmp_paths.append(_to_sidecar_xmp_path(img_path))
        
        print(f"创建了 {len(test_images)} 个测试图片")
        
        try:
            worker = ExifHandleWorker.get_instance()
            
            # 准备批量任务
            tasks = []
            for i, img_path in enumerate(test_images):
                tags = {
                    EXIF_TAG.Label.value: ["Red", "Green", "Blue"][i],
                    EXIF_TAG.Rating.value: str(i + 1),
                    EXIF_TAG.Object.value: f"鸟种{i+1}",
                }
                tasks.append((img_path, tags))
            
            print("批量写入标签...")
            worker.batch_update_tags(tasks)
            
            # 等待写入完成
            time.sleep(2)
            
            # 检查XMP文件
            all_created = True
            for xmp_path in xmp_paths:
                if os.path.exists(xmp_path):
                    print(f"✓ XMP文件已创建: {os.path.basename(xmp_path)}")
                else:
                    print(f"✗ XMP文件未创建: {xmp_path}")
                    all_created = False
            
            if not all_created:
                return False
            
            # 批量读取验证
            print("批量读取验证...")
            time.sleep(0.5)
            
            passed = True
            for i, img_path in enumerate(test_images):
                label = worker.read_tag(img_path, EXIF_TAG.Label.value)
                rating = worker.read_tag(img_path, EXIF_TAG.Rating.value)
                obj = worker.read_tag(img_path, EXIF_TAG.Object.value)
                
                expected_label = ["Red", "Green", "Blue"][i]
                expected_rating = str(i + 1)
                expected_obj = f"鸟种{i+1}"
                
                if label != expected_label:
                    print(f"✗ 图片{i} Label 不匹配: {label} != {expected_label}")
                    passed = False
                else:
                    print(f"✓ 图片{i} Label 正确")
                
                if str(rating) != expected_rating:
                    print(f"✗ 图片{i} Rating 不匹配: {rating} != {expected_rating}")
                    passed = False
                else:
                    print(f"✓ 图片{i} Rating 正确")
            
            return passed
            
        finally:
            # 清理
            for img_path, xmp_path in zip(test_images, xmp_paths):
                try:
                    if os.path.exists(img_path):
                        os.remove(img_path)
                    if os.path.exists(xmp_path):
                        os.remove(xmp_path)
                except:
                    pass
                    
    finally:
        sm.set("exif/write_mode", original_mode)


def test_xmp_content_validation():
    """测试XMP文件内容格式是否正确"""
    print("\n=== 测试XMP文件内容格式 ===")
    
    sm = SettingsManager.instance()
    original_mode = sm.get("exif/write_mode", "file")
    
    try:
        sm.set("exif/write_mode", "xmp")
        sm.set("exif/disable_write", False)
        
        test_image = create_test_image()
        xmp_path = _to_sidecar_xmp_path(test_image)
        
        try:
            worker = ExifHandleWorker.get_instance()
            
            # 写入测试数据
            test_tags = {
                EXIF_TAG.Label.value: "Yellow",
                EXIF_TAG.Rating.value: "4",
                EXIF_TAG.Object.value: "测试鸟",
                EXIF_TAG.OrderCls.value: "雀形目",
                EXIF_TAG.FamilyCls.value: "鹟科",
            }
            
            worker.write_tags(test_image, test_tags)
            time.sleep(1)
            
            if not os.path.exists(xmp_path):
                print(f"✗ XMP文件未创建")
                return False
            
            # 读取XMP文件内容
            with open(xmp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            print(f"XMP文件内容预览 (前500字符):")
            print(content[:500])
            print("...")
            
            # 验证XMP基本结构
            checks = [
                ("<?xpacket", "XMP包头"),
                ("<x:xmpmeta", "XMP元数据标签"),
                ("<rdf:RDF", "RDF根元素"),
                ("Yellow", "Label值"),
                ("测试鸟", "Object值"),
                ("雀形目", "OrderCls值"),
            ]
            
            passed = True
            for keyword, desc in checks:
                if keyword in content:
                    print(f"✓ 包含{desc}")
                else:
                    print(f"✗ 缺少{desc}")
                    passed = False
            
            return passed
            
        finally:
            try:
                if os.path.exists(test_image):
                    os.remove(test_image)
                if os.path.exists(xmp_path):
                    os.remove(xmp_path)
            except:
                pass
                
    finally:
        sm.set("exif/write_mode", original_mode)


def main():
    """主测试函数"""
    print("=" * 60)
    print("XMP接口验证测试")
    print("=" * 60)
    
    results = []
    
    # 运行所有测试
    results.append(("XMP路径转换", test_xmp_path_conversion()))
    results.append(("写入模式获取", test_write_mode()))
    results.append(("单个文件读写", test_single_write_read()))
    results.append(("批量文件读写", test_batch_write_read()))
    results.append(("XMP内容格式", test_xmp_content_validation()))
    
    # 打印总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)
    
    passed_count = sum(1 for _, result in results if result)
    total_count = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print("-" * 60)
    print(f"总计: {passed_count}/{total_count} 通过")
    
    if passed_count == total_count:
        print("\n🎉 所有测试通过！XMP接口工作正常。")
        return 0
    else:
        print(f"\n⚠️ 有 {total_count - passed_count} 个测试失败，请检查实现。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
