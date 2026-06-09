@echo off
cd /d "%~dp0"

set "PYEXE=%~dp0python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
set "APP_PORT=3010"
if defined OCT_BOX_PORT set "APP_PORT=%OCT_BOX_PORT%"
set "APP_URL=http://127.0.0.1:%APP_PORT%/"
set "OCT_OPEN_BROWSER=1"

set "LAN_IP=127.0.0.1"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ip=(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } | Select-Object -First 1 -ExpandProperty IPv4Address).IPAddress; if(-not $ip){$ip=(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Sort-Object InterfaceMetric | Select-Object -First 1 -ExpandProperty IPAddress)}; if($ip){$ip}else{'127.0.0.1'}"`) do set "LAN_IP=%%I"
set "LAN_URL=http://%LAN_IP%:%APP_PORT%/"

echo Starting OCT Studio...
echo Visit: %APP_URL%
echo LAN: %LAN_URL%
echo Local: http://127.0.0.1:%APP_PORT%/
echo Press Ctrl+C to stop.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:APP_PORT; if((Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet)){exit 0}else{exit 1}" >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    echo Server is already running. Opening %APP_URL%
    start "" "%APP_URL%"
    pause
    exit /b 0
)

"%PYEXE%" main.py --port %APP_PORT%

echo.
echo Server stopped.
pause
