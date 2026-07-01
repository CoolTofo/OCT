@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "REMOTE=origin"
set "BRANCH=master"
set "REPO_URL=http://gitlab.ds.com/aigc/oct_aiflow.git"

if /I "%~1"=="--self-test" goto :self_test

echo ============================================
echo   更新 OCT 到 GitLab 最新版
echo ============================================
echo.
echo 更新源: %REPO_URL%
echo 分支:   %BRANCH%
echo.

call :check_git || goto :fail
call :check_repo || goto :fail
call :ensure_remote || goto :fail

echo [1/4] 正在连接 GitLab 获取最新版本...
git fetch --prune "%REMOTE%" "%BRANCH%"
if errorlevel 1 (
    echo.
    echo [ERROR] 无法连接 GitLab 或拉取失败，请检查网络、账号登录或 GitLab 访问权限。
    goto :fail
)

git rev-parse --verify "%REMOTE%/%BRANCH%" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] 没有找到 %REMOTE%/%BRANCH%，请检查远程仓库和分支名。
    goto :fail
)

call :stash_local_changes || goto :fail
call :switch_update_branch || goto :fail

echo.
echo [3/4] 正在把本地代码更新到 %REMOTE%/%BRANCH%...
git merge --ff-only "%REMOTE%/%BRANCH%"
if errorlevel 1 (
    echo [INFO] 当前分支存在本地提交，尝试用 rebase 保留本地提交并更新...
    git rebase "%REMOTE%/%BRANCH%"
    if errorlevel 1 goto :rebase_failed
)

echo.
echo [4/4] 更新完成。
if defined DID_STASH (
    echo.
    echo [INFO] 更新前检测到本地未提交改动，已保存到 Git stash，暂未自动恢复，避免再次产生冲突。
    echo [INFO] 最近的备份如下：
    git stash list -n 1
    echo.
    echo 需要恢复这些本地改动时，可在此目录运行：
    echo   git stash pop
)

echo.
git status --short
echo.
echo [OK] 已更新到 GitLab 最新版。
pause
exit /b 0

:self_test
call :check_git || exit /b 1
call :check_repo || exit /b 1
echo [OK] GitLab 更新脚本自检通过。
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
) else (
    git remote set-url "%REMOTE%" "%REPO_URL%"
)
exit /b 0

:switch_update_branch
set "CURRENT_BRANCH="
for /f "usebackq delims=" %%B in (`git branch --show-current 2^>nul`) do set "CURRENT_BRANCH=%%B"
if /I "!CURRENT_BRANCH!"=="%BRANCH%" exit /b 0

echo.
echo [2/4] 当前分支是 !CURRENT_BRANCH!，正在切换到 %BRANCH%...
git show-ref --verify --quiet "refs/heads/%BRANCH%"
if errorlevel 1 (
    git switch -c "%BRANCH%" "%REMOTE%/%BRANCH%"
) else (
    git switch "%BRANCH%"
)
if errorlevel 1 (
    echo [ERROR] 无法切换到 %BRANCH% 分支，请手动检查当前仓库状态。
    exit /b 1
)
exit /b 0

:stash_local_changes
set "HAS_LOCAL_CHANGES="
for /f "usebackq delims=" %%S in (`git status --porcelain`) do (
    set "HAS_LOCAL_CHANGES=1"
    goto :after_status_scan
)
:after_status_scan
if not defined HAS_LOCAL_CHANGES exit /b 0

for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "STAMP=%%T"
if not defined STAMP set "STAMP=manual-backup"
echo.
echo [INFO] 检测到本地未提交改动，先保存到 Git stash，防止更新时被覆盖。
git stash push -u -m "OCT GitLab auto update backup !STAMP!"
if errorlevel 1 (
    echo [ERROR] 保存本地改动失败，已停止更新。
    exit /b 1
)
set "DID_STASH=1"
exit /b 0

:rebase_failed
echo.
echo [ERROR] 更新时发生提交冲突，已尝试回到更新前状态。
git rebase --abort >nul 2>nul
if defined DID_STASH (
    echo [INFO] 你的本地未提交改动仍保存在 Git stash 中，可稍后用 git stash list 查看。
)
goto :fail

:fail
echo.
echo [FAILED] 更新没有完成。
pause
exit /b 1
