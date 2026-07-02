param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$bundledCli = Join-Path $repoRoot "tools\dreamina\dreamina.exe"
$userBin = Join-Path $HOME "bin"
$userCli = Join-Path $userBin "dreamina.exe"
$installerUrl = "https://jimeng.jianying.com/cli"

function Write-Step {
    param([string]$Message)
    Write-Host "[Dreamina] $Message"
}

function Find-DreaminaCli {
    $cmd = Get-Command dreamina -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }
    if (Test-Path $userCli) {
        return $userCli
    }
    if (Test-Path $bundledCli) {
        return $bundledCli
    }
    return ""
}

function Test-DreaminaCli {
    param([string]$CliPath)
    if (-not $CliPath) {
        return $false
    }
    try {
        & $CliPath -h *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Add-UserBinToPath {
    if (-not (Test-Path $userBin)) {
        return
    }
    $env:Path = "$userBin;$env:Path"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) {
        [Environment]::SetEnvironmentVariable("Path", $userBin, "User")
        Write-Step "Added $userBin to user PATH. Reopen terminals to use dreamina directly."
        return
    }
    $parts = $userPath -split ";" | Where-Object { $_ }
    $already = $false
    foreach ($part in $parts) {
        if ($part.TrimEnd("\") -ieq $userBin.TrimEnd("\")) {
            $already = $true
            break
        }
    }
    if (-not $already) {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$userBin", "User")
        Write-Step "Added $userBin to user PATH. Reopen terminals to use dreamina directly."
    }
}

function Install-BundledDreaminaCli {
    if (-not (Test-Path $bundledCli)) {
        return $false
    }
    Write-Step "Using bundled CLI: $bundledCli"
    New-Item -ItemType Directory -Force -Path $userBin | Out-Null
    Copy-Item -LiteralPath $bundledCli -Destination $userCli -Force
    Add-UserBinToPath
    return $true
}

function Find-Bash {
    $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return $cmd.Source
    }
    $candidates = @(
        "$env:ProgramFiles\Git\bin\bash.exe",
        "$env:ProgramFiles\Git\usr\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\usr\bin\bash.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    return ""
}

function Install-OfficialDreaminaCli {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl -or -not $curl.Source) {
        throw "curl.exe was not found. Install curl or place dreamina.exe at tools\dreamina\dreamina.exe."
    }
    $bash = Find-Bash
    if (-not $bash) {
        throw "bash.exe was not found. Install Git for Windows, or place dreamina.exe at tools\dreamina\dreamina.exe."
    }

    $installer = Join-Path $env:TEMP ("dreamina-install-" + [guid]::NewGuid().ToString("N") + ".sh")
    try {
        Write-Step "Downloading official installer..."
        & $curl.Source -fsSL $installerUrl -o $installer
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $installer)) {
            throw "Failed to download Dreamina installer from $installerUrl."
        }
        Write-Step "Running official installer with $bash..."
        & $bash $installer
        if ($LASTEXITCODE -ne 0) {
            throw "Dreamina official installer failed with exit code $LASTEXITCODE."
        }
        Add-UserBinToPath
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
}

$existing = Find-DreaminaCli
if ($existing -and (Test-DreaminaCli $existing)) {
    Write-Step "CLI already available: $existing"
    if (-not $CheckOnly) {
        Add-UserBinToPath
    }
    exit 0
}

if ($CheckOnly) {
    Write-Step "CLI not available yet. Installer script syntax is OK."
    exit 0
}

if (-not (Install-BundledDreaminaCli)) {
    Install-OfficialDreaminaCli
}

$installed = Find-DreaminaCli
if (-not (Test-DreaminaCli $installed)) {
    throw "Dreamina CLI installation finished, but the dreamina command could not be verified."
}

Write-Step "CLI is ready: $installed"
Write-Step "Login is still account-specific. Run 'dreamina login' once on each new computer before generating."