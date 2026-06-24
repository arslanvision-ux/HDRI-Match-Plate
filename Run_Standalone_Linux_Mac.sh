#!/bin/bash
echo "Launching HDRI Match Plate from Source..."
# Ensure dependencies are installed
python3 -c "import PySide6" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "PySide6 not found. Installing dependencies..."
    pip3 install PySide6 opencv-python colour-science numpy
fi
export PYTHONPATH="$(pwd):$PYTHONPATH"
python3 -m hdri_match.ui.main_window
