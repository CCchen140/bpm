@echo off
chcp 65001 >nul
echo ==========================================
echo   鸟和鸟眼两阶段检测
echo ==========================================
echo.

REM 设置路径
set INPUT_DIR=D:\BaiduNetdiskDownload\temp\output
set OUTPUT_DIR=D:\BaiduNetdiskDownload\temp\output\detected
set BIRD_MODEL=yolo11n.pt
set EYE_MODEL=best.pt

echo 输入目录: %INPUT_DIR%
echo 输出目录: %OUTPUT_DIR%
echo 鸟类模型: %BIRD_MODEL%
echo 鸟眼模型: %EYE_MODEL%
echo.

REM 检查模型文件是否存在
if not exist "%BIRD_MODEL%" (
    echo 错误: 找不到鸟类模型 %BIRD_MODEL%
    pause
    exit /b
)

if not exist "%EYE_MODEL%" (
    echo 错误: 找不到鸟眼模型 %EYE_MODEL%
    pause
    exit /b
)

echo 请选择检测模式:
echo 1. 检测整个文件夹
echo 2. 检测单张图片
echo.

set /p choice="请输入选项 (1-2): "

if "%choice%"=="1" (
    echo.
    echo 开始批量检测...
    python detect_bird_and_eye.py --input "%INPUT_DIR%" --output "%OUTPUT_DIR%" --bird-model "%BIRD_MODEL%" --eye-model "%EYE_MODEL%"
) else if "%choice%"=="2" (
    echo.
    set /p image_path="请输入图片完整路径: "
    python detect_bird_and_eye.py --image "!image_path!" --output "%OUTPUT_DIR%" --bird-model "%BIRD_MODEL%" --eye-model "%EYE_MODEL%"
) else (
    echo 无效选项
    pause
    exit /b
)

echo.
echo 检测完成!
pause
