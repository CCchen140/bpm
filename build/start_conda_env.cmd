@echo off
echo starting bird_cuda conda env...
echo python build/build.py --flavor gpu --delta-from "dist/qitu_V0.0.4" --delta
echo python build/build_delta.py --from "dist/qitu_V0.0.4" --to "dist/qitu_V0.0.5" --version "0.0.5" --flavor gpu --update 1
call conda activate bird_cuda
if errorlevel 1 (
    echo error
    pause
    exit /b 1
)
cd /d "%~dp0\.."
echo cd: %cd%
echo.
cmd /k
