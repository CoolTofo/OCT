@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "REMOTE=origin"
set "BRANCH=main"
set "REPO_URL=https://github.com/CoolTofo/OCT.git"

if /I "%~1"=="--self-test" goto :self_test

echo ============================================
echo   上传 OCT 本地代码到 GitHub
echo ============================================
echo.
echo 上传目标: %REPO_URL%
echo 分支:     %BRANCH%
echo.

call :check_git || goto :fail
call :check_repo || goto :fail
call :ensure_remote || goto :fail
call :ensure_branch || goto :fail
call :timestamp || goto :fail

echo [1/5] 正在连接 GitHub 获取远端状态...
git fetch --prune "%REMOTE%" "%BRANCH%"
if errorlevel 1 (
    echo.
    echo [ERROR] 无法连接 GitHub 或获取远端状态失败，请检查网络、代理或 GitHub 访问权限。
    goto :fail
)

echo.
echo [2/5] 正在暂存本地代码改动...
git add -A -- . ^
    ":(exclude)API/.env" ^
    ":(exclude)history.json" ^
    ":(exclude)global_config.json" ^
    ":(exclude)assets/input/**" ^
    ":(exclude)assets/output/**" ^
    ":(exclude)output/**" ^
    ":(exclude)data/canvases/**" ^
    ":(exclude)data/conversations/**" ^
    ":(exclude)data/update_backups/**" ^
    ":(exclude)__pycache__/**" ^
    ":(exclude)dist/**" ^
    ":(exclude)dist_clean/**" ^
    ":(exclude)dist_migration/**" ^
    ":(exclude)packages/**" ^
    ":(exclude)python/**" ^
    ":(exclude)*.zip" ^
    ":(exclude)*.log"
if errorlevel 1 goto :fail

call :unstage_local_data || goto :fail

set "HAS_STAGED="
for /f "usebackq delims=" %%S in (`git diff --cached --name-only`) do (
    set "HAS_STAGED=1"
    goto :after_staged_scan
)
:after_staged_scan

if defined HAS_STAGED (
    echo.
    echo [3/5] 正在创建本地提交...
    git diff --cached --name-status
    echo.
    git commit -m "Upload local changes %STAMP%"
    if errorlevel 1 goto :fail
) else (
    echo.
    echo [3/5] 没有发现需要提交的代码改动。
)

echo.
echo [4/5] 正在同步远端最新提交...
git pull --rebase "%REMOTE%" "%BRANCH%"
if errorlevel 1 goto :rebase_failed

echo.
echo [5/5] 正在上传到 GitHub...
git push "%REMOTE%" "%BRANCH%"
if errorlevel 1 goto :fail

echo.
git status --short
echo.
echo [OK] 已上传到 GitHub。
pause
exit /b 0

:self_test
call :check_git || exit /b 1
call :check_repo || exit /b 1
echo [OK] 上传脚本自检通过。
exit /b 0

:check_git
git --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 没有找到 Git，请先安装 Git for Windows。
    exit /b 1
)
exit /b 0

:check_repo
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 当前目录不是 Git 仓库，请把此文件放在 OCT 项目根目录运行。
    echo [INFO] 如你是下载的 ZIP 包，请先使用 Git 克隆：git clone %REPO_URL%
    exit /b 1
)
exit /b 0

:ensure_remote
git remote get-url "%REMOTE%" >nul 2>nul
if errorlevel 1 (
    echo [INFO] 未找到远程仓库 %REMOTE%，正在自动添加：%REPO_URL%
    git remote add "%REMOTE%" "%REPO_URL%"
    if errorlevel 1 (
        echo [ERROR] 添加远程仓库失败，请检查 Git 配置。
        exit /b 1
    )
)
exit /b 0

:ensure_branch
set "CURRENT_BRANCH="
for /f "usebackq delims=" %%B in (`git branch --show-current 2^>nul`) do set "CURRENT_BRANCH=%%B"
if /I "!CURRENT_BRANCH!"=="%BRANCH%" exit /b 0

echo [ERROR] 当前分支是 !CURRENT_BRANCH!，上传脚本只会上传到 %BRANCH%。
echo [INFO] 请先运行：git switch %BRANCH%
exit /b 1

:timestamp
set "STAMP="
for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "STAMP=%%T"
if not defined STAMP set "STAMP=manual-upload"
exit /b 0

:unstage_local_data
git reset -q HEAD -- ^
    API/.env ^
    history.json ^
    global_config.json ^
    assets/input ^
    assets/output ^
    output ^
    data/canvases ^
    data/conversations ^
    data/update_backups ^
    __pycache__ ^
    dist ^
    dist_clean ^
    dist_migration ^
    packages ^
    python ^
    python.zip ^
    "*.zip" ^
    "*.log" 2>nul
exit /b 0

:rebase_failed
echo.
echo [ERROR] 同步远端最新提交时发生冲突，已尝试停止 rebase。
git rebase --abort >nul 2>nul
echo [INFO] 请先手动解决冲突，再重新运行本脚本。
goto :fail

:fail
echo.
echo [FAILED] 上传没有完成。
pause
exit /b 1
