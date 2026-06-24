import sys
import os

# Ensure the root path is in sys.path
if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    application_path = sys._MEIPASS
    sys.path.insert(0, application_path)
else:
    # Running in a normal Python environment
    application_path = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, application_path)

try:
    from hdri_match.ui.qt_shim import QtWidgets
except ImportError as e:
    print(f"Failed to import qt_shim: {e}")
    sys.exit(1)

from hdri_match.ui.main_window import HdriCalibWindow

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("HDRI Match Plate")
    
    # Set default OCIO if bundled
    bundled_ocio = os.path.join(application_path, "ocio_configs", "config.ocio")
    if os.path.exists(bundled_ocio) and not os.environ.get("OCIO"):
        os.environ["OCIO"] = bundled_ocio
        print(f"Using bundled OCIO config: {bundled_ocio}")

    window = HdriCalibWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
