#!/bin/bash
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
