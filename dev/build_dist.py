import os, shutil

dist_dir = 'E:/PROJECTS/HDRI_Match_Plate/dist'
src_dir = 'E:/PROJECTS/HDRI_Match_Plate'
final_dir = os.path.join(dist_dir, 'HDRI_Match_Plate_Final')

if os.path.exists(final_dir):
    shutil.rmtree(final_dir, ignore_errors=True)
os.makedirs(final_dir, exist_ok=True)

# 1. Windows Standalone
standalone_dest = os.path.join(final_dir, 'HDRI_Match_Plate_Windows_Standalone')
if os.path.exists(os.path.join(dist_dir, 'HDRI_Match_Plate')):
    shutil.copytree(os.path.join(dist_dir, 'HDRI_Match_Plate'), standalone_dest, dirs_exist_ok=True)

# 2. Source & Nuke (Cross-Platform)
nuke_dest = os.path.join(final_dir, 'HDRI_Match_Plate_Source_And_Nuke')
os.makedirs(nuke_dest, exist_ok=True)

shutil.copy(os.path.join(src_dir, 'init.py'), nuke_dest)
shutil.copy(os.path.join(src_dir, 'menu.py'), nuke_dest)

dest_pkg = os.path.join(nuke_dest, 'hdri_match')
os.makedirs(dest_pkg, exist_ok=True)
for root, dirs, files in os.walk(os.path.join(src_dir, 'hdri_match')):
    if '__pycache__' in root or 'debug_output' in root or 'screenshots' in root:
        continue
    rel_path = os.path.relpath(root, os.path.join(src_dir, 'hdri_match'))
    cur_dest = dest_pkg if rel_path == '.' else os.path.join(dest_pkg, rel_path)
    if rel_path != '.':
        os.makedirs(cur_dest, exist_ok=True)
    for f in files:
        if f.startswith('test_') or f.endswith(('.png', '.jpg', '.ppm', '.exr')):
            continue
        shutil.copy(os.path.join(root, f), cur_dest)

# WRITE RUN LINUX STANDALONE SCRIPT
run_linux_path = os.path.join(nuke_dest, 'Run_Standalone_Linux_Mac.sh')
with open(run_linux_path, 'w', newline='\n') as f:
    f.write('''#!/bin/bash
echo "Launching HDRI Match Plate from Source..."
# Ensure dependencies are installed
python3 -c "import PySide6" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "PySide6 not found. Installing dependencies..."
    pip3 install PySide6 opencv-python colour-science numpy
fi
export PYTHONPATH="$(pwd):$PYTHONPATH"
python3 -m hdri_match.ui.main_window
''')

# WRITE BAT SCRIPT FOR NUKE
bat_path = os.path.join(nuke_dest, 'Install_Nuke_Windows.bat')
with open(bat_path, 'w') as f:
    f.write('''@echo off
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
''')

# WRITE SH SCRIPT FOR NUKE
sh_path = os.path.join(nuke_dest, 'Install_Nuke_Linux_Mac.sh')
with open(sh_path, 'w', newline='\n') as f:
    f.write('''#!/bin/bash
echo "==================================================="
echo "  HDRI Match Plate - Automatic Nuke Installer      "
echo "==================================================="
echo ""

NUKE_DIR="$HOME/.nuke"
if [ ! -d "$NUKE_DIR" ]; then
    echo "Creating .nuke directory at $NUKE_DIR"
    mkdir -p "$NUKE_DIR"
fi

echo "Found Nuke directory: $NUKE_DIR"
echo ""
echo "[1] Install as Nuke Docked Panel (Recommended - Supports Live Link)"
echo "[2] Install as Nuke Floating Window"
echo "[3] Cancel Installation"
echo ""
read -p "Select an installation mode (1/2/3): " choice

if [ "$choice" == "3" ] || [ -z "$choice" ]; then
    echo "Installation cancelled."
    exit 0
fi

echo ""
echo "Copying hdri_match package..."
cp -R "hdri_match" "$NUKE_DIR/hdri_match"

if [ "$choice" == "1" ]; then
    echo ""
    echo "Configuring Docked Panel..."
    touch "$NUKE_DIR/menu.py"
    if ! grep -q "hdri_match.nuke_panel" "$NUKE_DIR/menu.py"; then
        echo "" >> "$NUKE_DIR/menu.py"
        echo "import nuke" >> "$NUKE_DIR/menu.py"
        echo "import hdri_match.nuke_panel" >> "$NUKE_DIR/menu.py"
        echo "hdri_match.nuke_panel.register_panel()" >> "$NUKE_DIR/menu.py"
        echo "Docked Panel registered in menu.py!"
    else
        echo "HDRI Match Panel is already registered in menu.py."
    fi
fi

if [ "$choice" == "2" ]; then
    echo ""
    echo "Configuring Floating Window..."
    touch "$NUKE_DIR/menu.py"
    touch "$NUKE_DIR/init.py"
    
    if ! grep -q "Match Plate Calibration" "$NUKE_DIR/menu.py"; then
        cat "menu.py" >> "$NUKE_DIR/menu.py"
        echo "Floating Window registered in menu.py!"
    else
        echo "HDRI Match Menu is already registered in menu.py."
    fi
    
    if ! grep -q "hdri_match" "$NUKE_DIR/init.py"; then
        cat "init.py" >> "$NUKE_DIR/init.py"
        echo "Plugin paths added to init.py!"
    else
        echo "Plugin paths already exist in init.py."
    fi
fi

echo ""
echo "==================================================="
echo "Installation Complete! Please restart Nuke."
echo "==================================================="
''')

# 3. Docs & Install Guide
shutil.copy(os.path.join(src_dir, 'HDRI_Match_Plate_Tutorial.pdf'), final_dir)
install_md_path = os.path.join(final_dir, 'INSTALL.md')
with open(install_md_path, 'w') as f:
    f.write('''# HDRI Match Plate - Installation Guide

HDRI Match Plate is a powerful tool designed to run in multiple environments to suit your studio's workflow.

## 1. Windows Standalone Application
The Windows standalone version is a pre-compiled executable that does NOT require Python to be installed.
**Steps:**
1. Open the `HDRI_Match_Plate_Windows_Standalone` folder.
2. Double-click `HDRI_Match_Plate.exe` to launch the application.

---

## 2. Linux & macOS Standalone Application (From Source)
Because the pre-compiled executable is Windows-only, Linux and macOS users can easily run the Standalone tool directly from the Python source code.
**Steps:**
1. Open your terminal and navigate to the `HDRI_Match_Plate_Source_And_Nuke` folder.
2. Run `chmod +x Run_Standalone_Linux_Mac.sh` to make the script executable.
3. Execute the script: `./Run_Standalone_Linux_Mac.sh`
*(This script will automatically verify dependencies like PySide6 and launch the UI).*

---

## 3. Nuke Installation (Automated for ALL OS)
We have provided automated installation scripts for Windows, Linux, and macOS.

**Windows Users:**
1. Open the `HDRI_Match_Plate_Source_And_Nuke` folder.
2. Double-click the `Install_Nuke_Windows.bat` file.
3. The prompt will ask if you want to install it as a **Docked Panel** or a **Floating Window**.
4. Restart Nuke.

**Linux & macOS Users:**
1. Open your terminal and navigate to the `HDRI_Match_Plate_Source_And_Nuke` folder.
2. Run `chmod +x Install_Nuke_Linux_Mac.sh` to make the script executable.
3. Run `./Install_Nuke_Linux_Mac.sh`.
4. Follow the on-screen prompts to choose your installation mode.
5. Restart Nuke.

For a complete guide on how to use the tool, please read `HDRI_Match_Plate_Tutorial.pdf`.
''')

print('Final folder constructed.')
