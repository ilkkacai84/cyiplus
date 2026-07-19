@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  汇率查询 - 推送到外部 API
echo  数据来源: smbs.biz / chinamoney.com.cn
echo ========================================
echo.

REM 尝试 python 命令
python --version >nul 2>&1
if %errorlevel% equ 0 (
    python exrate.py --push
    goto :end
)

REM 回退到 py 启动器
py --version >nul 2>&1
if %errorlevel% equ 0 (
    py exrate.py --push
    goto :end
)

echo [错误] 未找到 Python 运行环境。
echo 请安装 Python 3 (https://www.python.org/downloads/)
echo 安装时请勾选 "Add Python to PATH"。

:end
echo.
if %errorlevel% neq 0 (
    echo 程序执行失败，详情请查看 logs 目录下的日志文件。
)
