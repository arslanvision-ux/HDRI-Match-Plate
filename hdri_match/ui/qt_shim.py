try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtWidgets import QOpenGLWidget
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtOpenGLWidgets import QOpenGLWidget
    except ImportError:
        raise ImportError("No PySide2 or PySide6 module found.")
