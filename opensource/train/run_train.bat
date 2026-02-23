@echo off
chcp 65001 >nul
echo ==========================================
echo   YOLOv11n 鸟眼识别模型训练脚本
echo ==========================================
echo.

REM 检查是否安装了ultralytics
python -c "import ultralytics" 2>nul
if errorlevel 1 (
    echo 正在安装 ultralytics...
    pip install ultralytics -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo.
echo 请选择训练模式:
echo 1. 快速训练 (50轮，适合测试)
echo 2. 标准训练 (100轮，推荐)
echo 3. 高精度训练 (200轮)
echo 4. 仅验证模型
echo.

set /p choice="请输入选项 (1-4): "

if "%choice%"=="1" (
    echo.
    echo 开始快速训练...
    python train_yolo.py --epochs 50 --batch 16 --name birdeye_yolo11n_fast
) else if "%choice%"=="2" (
    echo.
    echo 开始标准训练...
    python train_yolo.py --epochs 100 --batch 16 --name birdeye_yolo11n
) else if "%choice%"=="3" (
    echo.
    echo 开始高精度训练...
    python train_yolo.py --epochs 200 --batch 16 --name birdeye_yolo11n_best
) else if "%choice%"=="4" (
    echo.
    echo 开始验证模型...
    python train_yolo.py --val-only
) else (
    echo 无效选项
    pause
    exit /b
)

echo.
echo 训练完成!
echo 结果保存在 runs/train 目录下
pause
