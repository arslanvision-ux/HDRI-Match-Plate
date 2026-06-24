import nuke
import os
import sys

# Define the root of the tool (assuming this menu.py is placed in ~/.nuke or sourced)
# Adjust the path below to point to the directory containing hdri_match
TOOL_ROOT = r"e:\PROJECTS\HDRI_Match_Plate"
if TOOL_ROOT not in sys.path:
    sys.path.append(TOOL_ROOT)

try:
    from hdri_match import nuke_panel
    nuke_panel.register_panel()
    nuke.tprint("HDRI Match Plate: Dockable panel registered successfully.")
except ImportError as e:
    nuke.tprint(f"HDRI Match Plate: Failed to register panel. Error: {e}")
