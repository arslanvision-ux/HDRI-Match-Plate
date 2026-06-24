import hou
import os
import sys

def import_hdri_match_plate():
    # Prompt the user to select the export directory
    export_dir = hou.ui.selectFile(title="Select HDRI Match Plate Export Directory", file_type=hou.fileType.Directory)
    
    if not export_dir or not os.path.exists(export_dir):
        return
        
    export_dir = hou.expandString(export_dir)
    
    # Switch to Solaris / Stage context
    desktop = hou.ui.mainPaneTab().pane().desktop()
    pane = desktop.paneTabOfType(hou.paneTabType.NetworkEditor)
    if pane:
        pane.setPwd(hou.node('/stage'))

    stage_node = hou.node('/stage')
    
    # Find generated Python scripts from HDRI Match Plate
    solaris_scripts = []
    for f in os.listdir(export_dir):
        if f.endswith('.py') and ('solaris' in f or 'export' in f or 'lookdev' in f):
            solaris_scripts.append(os.path.join(export_dir, f))
            
    if not solaris_scripts:
        hou.ui.displayMessage("No Solaris Python scripts found in the selected directory.")
        return
        
    # Create a Python LOP for each script and execute it
    prev_node = None
    for script_path in solaris_scripts:
        script_name = os.path.basename(script_path).replace('.py', '')
        
        # Create Python LOP
        py_lop = stage_node.createNode('pythonscript', node_name=script_name)
        
        # Read the script content
        with open(script_path, 'r') as file:
            script_content = file.read()
            
        # Set the python code parameter
        py_lop.parm('python').set(script_content)
        
        # Connect nodes in a chain
        if prev_node:
            py_lop.setInput(0, prev_node)
            
        prev_node = py_lop
        
    # Layout nodes neatly
    stage_node.layoutChildren()
    
    if prev_node:
        prev_node.setDisplayFlag(True)
        
    hou.ui.displayMessage("Successfully imported HDRI Match Plate Solaris data!")

# Execute the tool
import_hdri_match_plate()
