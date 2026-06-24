import nuke
import os
import sys

# ---------------------------------------------------------------------------
# Environment diagnostics and safety guards for HDRI Match Plate
# ---------------------------------------------------------------------------

def _check_numpy_compatibility():
    """
    Checks if NumPy is compatible with Nuke's bundled PySide2/shiboken2.
    shiboken2 was compiled against NumPy 1.x ABI; NumPy 2.x will crash it.
    """
    try:
        import numpy as np
        major = np.__version__.split('.')[0]
        if int(major) >= 2:
            nuke.tprint(
                "[HDRI Match Plate] WARNING: NumPy 2.x detected in Nuke's Python. "
                "Nuke 15.2's bundled PySide2/shiboken2 was compiled against NumPy 1.x "
                "and WILL CRASH on import. To fix:"
            )
            nuke.tprint(
                "  1) Downgrade Nuke's NumPy to <2:"
                "     <nuke_python> -m pip install 'numpy<2' --force-reinstall"
            )
            nuke.tprint(
                "  2) Or ensure Nuke's site-packages are isolated from system numpy."
            )
            return False
        else:
            nuke.tprint(f"[HDRI Match Plate] NumPy {np.__version__} — compatible.")
            return True
    except ImportError:
        nuke.tprint("[HDRI Match Plate] NumPy not available.")
        return False


def _check_cuda_cache():
    """
    Warns if CUDA_CACHE_MAXSIZE is set too low (< 2048 MB).
    This causes Blink/AIR to constantly recompile kernels on modern NVIDIA GPUs.
    """
    val = os.environ.get("CUDA_CACHE_MAXSIZE", "")
    if val:
        try:
            mb = int(val)
            if mb < 2048:
                nuke.tprint(
                    "[HDRI Match Plate] CUDA_CACHE_MAXSIZE is set to "
                    f"{mb} MB (< 2 GB). This may cause AIR Plugins to "
                    "constantly recompile kernels. Recommended: remove the "
                    "env var entirely or set it to >= 2048."
                )
        except ValueError:
            pass  # Not a number, ignore


def _safe_load_pyside2():
    """
    Attempt to import PySide2 with a safe fallback if NumPy incompatibility
    prevents shiboken2 from loading. Nuke may be usable without PySide2
    if you only use script-mode (no custom UI).
    """
    try:
        from PySide2 import QtWidgets, QtCore, QtGui
        nuke.tprint("[HDRI Match Plate] PySide2 loaded successfully.")
        return True
    except Exception as e:
        nuke.tprint(
            "[HDRI Match Plate] Failed to load PySide2. "
            "The HDRI Match Plate UI tool will be unavailable. "
            f"Error: {e}"
        )
        return False


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

nuke.tprint("=" * 60)
nuke.tprint("Initializing HDRI Match Plate package...")
nuke.tprint(f"Python: {sys.version.split()[0]}")
nuke.tprint(f"Nuke:   {nuke.env['NukeVersionString']}")

_check_cuda_cache()
numpy_ok = _check_numpy_compatibility()

if numpy_ok:
    _safe_load_pyside2()
else:
    nuke.tprint(
        "[HDRI Match Plate] Skipping PySide2 load due to NumPy incompatibility. "
        "Fix the NumPy version to enable the UI tool."
    )

nuke.tprint("=" * 60)