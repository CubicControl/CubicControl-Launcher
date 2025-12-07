@echo off
setlocal

:: Check if running as Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo This script requires Administrator privileges.
    echo Please right-click and run as Administrator.
    pause
    exit /b
)

rem Folder of this .bat (always ends with a backslash)
set "SCRIPT_DIR=%~dp0"

rem Full path to your exe
set "EXE_PATH=%SCRIPT_DIR%main.exe"

set "RULE_NAME=Minecraft API Server"
set "TASK_NAME=MinecraftServerController"
set "TASK_XML=%SCRIPT_DIR%SetupFiles\MinecraftServerController.xml"
set "TASK_XML_TEMP=%SCRIPT_DIR%SetupFiles\MinecraftServerController_temp.xml"

echo Adding firewall rule for "%EXE_PATH%"...

:: Check if rule exists
netsh advfirewall firewall show rule name="%RULE_NAME%" | findstr /I "%RULE_NAME%" >nul
if %errorlevel%==0 (
    echo Removing existing firewall rule...
    netsh advfirewall firewall delete rule name="%RULE_NAME%" >nul
)

:: Always add the rule fresh
netsh advfirewall firewall add rule name="%RULE_NAME%" ^
    dir=in action=allow program="%EXE_PATH%" enable=yes profile=any

echo New "%RULE_NAME%" firewall rule added.

echo.
echo Adding new task in Task Scheduler...
echo.

:: Delete existing task if present
schtasks /Query /TN "%TASK_NAME%" >nul 2>&1
if %errorlevel%==0 (
    echo Removing existing scheduled task "%TASK_NAME%"...
    schtasks /Delete /TN "%TASK_NAME%" /F >nul
)

:: Replace placeholder __SCRIPT_DIR__ with actual folder path (without trailing backslash)
set "SCRIPT_DIR_NO_SLASH=%SCRIPT_DIR:~0,-1%"
powershell -Command "(Get-Content '%TASK_XML%') -replace '__SCRIPT_DIR__','%SCRIPT_DIR_NO_SLASH%\MinecraftServerController.exe' | Set-Content '%TASK_XML_TEMP%'"

:: Create the task from processed XML
schtasks /Create /TN "%TASK_NAME%" /XML "%TASK_XML_TEMP%"

if %errorlevel%==0 (
    echo Task "%TASK_NAME%" created successfully.
) else (
    echo Failed to create task "%TASK_NAME%". Please check "%TASK_XML%".
)

:: Clean up temp XML
del "%TASK_XML_TEMP%" >nul 2>&1

echo.
echo Done. Press any key to exit...
pause >nul
endlocal