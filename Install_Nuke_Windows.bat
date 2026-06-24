@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   HDRI Match Plate - Automatic Nuke Installer
echo ===================================================
echo.

set "NUKE_DIR=%USERPROFILE%\.nuke"
if not exist "%NUKE_DIR%" (
    echo Creating .nuke directory at %NUKE_DIR%
    mkdir "%NUKE_DIR%"
)

echo Found Nuke directory: %NUKE_DIR%
echo.
echo [1] Install as Nuke Docked Panel (Recommended - Supports Live Link)
echo [2] Install as Nuke Floating Window
echo [3] Cancel Installation
echo.
set /p choice="Select an installation mode (1/2/3): "

if "%choice%"=="3" goto end
if "%choice%"=="" goto end

echo.
echo Copying hdri_match package...
xcopy /E /I /Y "hdri_match" "%NUKE_DIR%\hdri_match" >nul

if "%choice%"=="1" (
    echo.
    echo Configuring Docked Panel...
    findstr /C:"hdri_match.nuke_panel" "%NUKE_DIR%\menu.py" >nul 2>&1
    if errorlevel 1 (
        echo. >> "%NUKE_DIR%\menu.py"
        echo import nuke >> "%NUKE_DIR%\menu.py"
        echo import hdri_match.nuke_panel >> "%NUKE_DIR%\menu.py"
        echo hdri_match.nuke_panel.register_panel() >> "%NUKE_DIR%\menu.py"
        echo Docked Panel registered in menu.py!
    ) else (
        echo HDRI Match Panel is already registered in menu.py.
    )
)

if "%choice%"=="2" (
    echo.
    echo Configuring Floating Window...
    findstr /C:"Match Plate Calibration" "%NUKE_DIR%\menu.py" >nul 2>&1
    if errorlevel 1 (
        type "menu.py" >> "%NUKE_DIR%\menu.py"
        echo Floating Window registered in menu.py!
    ) else (
        echo HDRI Match Menu is already registered in menu.py.
    )
    
    findstr /C:"hdri_match" "%NUKE_DIR%\init.py" >nul 2>&1
    if errorlevel 1 (
        type "init.py" >> "%NUKE_DIR%\init.py"
        echo Plugin paths added to init.py!
    ) else (
        echo Plugin paths already exist in init.py.
    )
)

echo.
echo ===================================================
echo Installation Complete! Please restart Nuke.
echo ===================================================
pause
:end
