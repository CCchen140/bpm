#!/bin/bash
# Linux服务器环境安装脚本

echo "=========================================="
echo "  安装YOLOv11训练环境依赖"
echo "=========================================="

# 更新包列表
sudo apt-get update

# 安装OpenCV所需的系统库
echo "安装OpenCV系统依赖..."
sudo apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libglib2.0-0

# 可选：安装其他常用工具
echo "安装其他工具..."
sudo apt-get install -y \
    wget \
    git \
    vim

echo ""
echo "系统依赖安装完成！"
echo "接下来请运行: pip install -r requirements.txt"
