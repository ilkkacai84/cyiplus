@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  汇率查询程序 - 打包工具
echo  将 exrate.py 编译成单个 exe 文件
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 未找到 Python，请先安装:
        echo https://www.python.org/downloads/
        echo 安装时请勾选 "Add Python to PATH"
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

echo 正在安装 PyInstaller...
%PYTHON% -m pip install pyinstaller -q
echo.

echo 正在打包 exrate.py → exrate.exe...
%PYTHON% -m PyInstaller --onefile exrate.py --distpath . --clean -n exrate
echo.

REM 清理临时文件
rmdir /s /q build >nul 2>&1
del /q *.spec >nul 2>&1
rmdir /s /q __pycache__ >nul 2>&1

echo ========================================
echo  打包完成！
echo.
echo  生成的 exe 文件:
echo  %CD%\exrate.exe
echo.
echo  双击 exrate.exe 即可运行
echo ========================================
pause
