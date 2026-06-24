import nuke
import sys

def _launch_hdri_tool():
    """Deferred import so the tool only loads when actually invoked."""
    try:
        # Check PySide2 availability first to avoid NumPy 2.x shiboken2 crash
        try:
            from PySide2 import QtWidgets
        except Exception as e:
            nuke.message(
                "HDRI Match Plate cannot launch.\n\n"
                "Nuke's PySide2 failed to load — likely due to a NumPy 1.x vs 2.x ABI conflict.\n"
                "Run this in Nuke's Python interpreter to fix:\n"
                "<nuke_python> -m pip install 'numpy<2' --force-reinstall"
            )
            nuke.tprint(f"[HDRI Match Plate] PySide2 load failed: {e}")
            return

        from hdri_match.ui.main_window import show_window
        show_window()
    except Exception as e:
        nuke.message(f"HDRI Match Plate failed to launch:\n\n{e}")

def _reload_hdri_tool():
    """Clears hdri_match from sys.modules so the next launch uses fresh code."""
    import sys
    import nuke
    
    # Try to gracefully close any open window before reloading
    try:
        if 'hdri_match.ui.main_window' in sys.modules:
            mw = sys.modules['hdri_match.ui.main_window']
            if hasattr(mw, 'hdri_calib_app') and mw.hdri_calib_app is not None:
                mw.hdri_calib_app.close()
    except Exception as e:
        nuke.tprint(f"[HDRI Match Plate] Error closing existing window: {e}")

    # Remove all hdri_match modules from memory
    modules_to_delete = [mod for mod in sys.modules if mod.startswith('hdri_match')]
    for mod in modules_to_delete:
        del sys.modules[mod]
        
    nuke.message(f"Successfully flushed {len(modules_to_delete)} HDRI Match modules from memory.\n\nThe next time you launch the tool, it will load the latest code.")

try:
    nuke_menu = nuke.menu('Nuke')
    custom_menu = nuke_menu.addMenu('HDRI Tools')
    custom_menu.addCommand('Match Plate Calibration', _launch_hdri_tool)
    custom_menu.addSeparator()
    custom_menu.addCommand('Reload Tool (Dev)', _reload_hdri_tool)
    nuke.tprint("HDRI Match Plate Calibration Tool registered successfully.")
except Exception as e:
    nuke.tprint(f"Failed to register HDRI Match Plate menu: {e}")
