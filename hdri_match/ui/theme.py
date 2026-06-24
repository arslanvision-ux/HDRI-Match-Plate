DARK_THEME = """
QMainWindow, QDialog, #SidePanel, QScrollArea, QScrollArea > QWidget {
    background-color: #1a1a1a;
    color: #d4d4d4;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}
QGraphicsView {
    border: none;
}
QLabel {
    color: #c8c8c8;
    padding: 1px;
}
QLabel[title="true"] {
    color: #ffffff;
    font-weight: bold;
    font-size: 13px;
    padding-bottom: 4px;
}
QPushButton {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #3a3a3a;
    border-color: #555555;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #252525;
}
QPushButton:checked {
    background-color: #0078d7;
    border-color: #005a9e;
    color: #ffffff;
}
QPushButton#btn_auto_calib {
    background-color: #2a5c2a;
    color: #90ee90;
    border-color: #3d7a3d;
    font-weight: bold;
    font-size: 13px;
    min-height: 30px;
}
QPushButton#btn_auto_calib:hover {
    background-color: #347034;
}
QPushButton#btn_export, QPushButton#btn_export_sequence {
    background-color: #1e3f6e;
    color: #7eb8f7;
    border-color: #2a5490;
    font-weight: bold;
    min-height: 30px;
}
QPushButton#btn_export:hover, QPushButton#btn_export_sequence:hover {
    background-color: #25508a;
}
QPushButton#btn_export_cg {
    background-color: #6b3d00;
    color: #ffb84d;
    border-color: #8a5200;
    font-weight: bold;
    min-height: 30px;
}
QPushButton#btn_export_cg:hover {
    background-color: #854d00;
}
QSlider::groove:horizontal {
    height: 4px;
    background-color: #333333;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #5a8fc4;
    border: 1px solid #3d6f9e;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #72a8e0;
}
QSlider::sub-page:horizontal {
    background-color: #3d6f9e;
    border-radius: 2px;
}
QComboBox {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
}
QComboBox:hover {
    border-color: #555555;
}
QComboBox QAbstractItemView {
    background-color: #252525;
    border: 1px solid #3d3d3d;
    selection-background-color: #3d6f9e;
    color: #d4d4d4;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 4px;
}
QLineEdit {
    background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
}
QLineEdit:focus {
    border-color: #5a8fc4;
}
QCheckBox {
    color: #c8c8c8;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: #2d2d2d;
}
QCheckBox::indicator:checked {
    background-color: #3d6f9e;
    border-color: #5a8fc4;
    image: none;
}
QCheckBox::indicator:hover {
    border-color: #7ab0d4;
}
QTabWidget::pane {
    border: 1px solid #333333;
    background-color: #1e1e1e;
}
QTabBar::tab {
    background-color: #252525;
    color: #909090;
    padding: 7px 16px;
    border: 1px solid #333333;
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    min-width: 120px;
}
QTabBar::tab:selected {
    background-color: #1e1e1e;
    color: #ffffff;
    border-color: #444444;
}
QTabBar::tab:hover:!selected {
    background-color: #2d2d2d;
    color: #cccccc;
}
QGroupBox {
    color: #aaaaaa;
    border: 1px solid #333333;
    border-radius: 5px;
    margin-top: 10px;
    padding: 8px 6px 6px 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #88b8e8;
}
QScrollArea {
    border: none;
    background-color: #1a1a1a;
}
QScrollBar:vertical {
    background-color: #1e1e1e;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #444444;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background-color: #555555;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background-color: #1e1e1e;
    height: 10px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background-color: #444444;
    border-radius: 5px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background-color: #555555; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle {
    background-color: #333333;
    width: 3px;
}
QSplitter::handle:hover {
}
"""

LIGHT_THEME = """
QMainWindow, QDialog, #SidePanel, QScrollArea, QScrollArea > QWidget {
    background-color: #f0f0f0;
    color: #333333;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}
QGraphicsView {
    border: none;
}
QLabel {
    color: #333333;
    padding: 1px;
}
QLabel[title="true"] {
    color: #000000;
    font-weight: bold;
    font-size: 13px;
    padding-bottom: 4px;
}
QPushButton {
    background-color: #e0e0e0;
    color: #333333;
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 6px 12px;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #d0d0d0;
    border-color: #b0b0b0;
    color: #000000;
}
QPushButton:pressed {
    background-color: #c0c0c0;
}
QPushButton:checked {
    background-color: #0078d7;
    border-color: #005a9e;
    color: #ffffff;
}
QPushButton#btn_auto_calib {
    background-color: #d4edda;
    color: #155724;
    border-color: #c3e6cb;
    font-weight: bold;
    font-size: 13px;
    min-height: 30px;
}
QPushButton#btn_auto_calib:hover {
    background-color: #c3e6cb;
}
QPushButton#btn_export, QPushButton#btn_export_sequence {
    background-color: #cce5ff;
    color: #004085;
    border-color: #b8daff;
    font-weight: bold;
    min-height: 30px;
}
QPushButton#btn_export:hover, QPushButton#btn_export_sequence:hover {
    background-color: #b8daff;
}
QPushButton#btn_export_cg {
    background-color: #fff3cd;
    color: #856404;
    border-color: #ffeeba;
    font-weight: bold;
    min-height: 30px;
}
QPushButton#btn_export_cg:hover {
    background-color: #ffeeba;
}
QSlider::groove:horizontal {
    height: 4px;
    background-color: #cccccc;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #007bff;
    border: 1px solid #0056b3;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #0056b3;
}
QSlider::sub-page:horizontal {
    background-color: #0056b3;
    border-radius: 2px;
}
QComboBox {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
}
QComboBox:hover {
    border-color: #b0b0b0;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    selection-background-color: #007bff;
    color: #333333;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 4px;
}
QLineEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 22px;
}
QLineEdit:focus {
    border-color: #5a8fc4;
}
QCheckBox {
    color: #333333;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #cccccc;
    border-radius: 3px;
    background-color: #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #007bff;
    border-color: #0056b3;
    image: none;
}
QCheckBox::indicator:hover {
    border-color: #80bdff;
}
QTabWidget::pane {
    border: 1px solid #cccccc;
    background-color: #ffffff;
}
QTabBar::tab {
    background-color: #e0e0e0;
    color: #666666;
    padding: 7px 16px;
    border: 1px solid #cccccc;
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    min-width: 120px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #333333;
    border-color: #b0b0b0;
}
QTabBar::tab:hover:!selected {
    background-color: #d0d0d0;
    color: #333333;
}
QGroupBox {
    color: #555555;
    border: 1px solid #cccccc;
    border-radius: 5px;
    margin-top: 10px;
    padding: 8px 6px 6px 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #007bff;
}
QScrollArea {
    border: none;
    background-color: #f0f0f0;
}
QScrollBar:vertical {
    background-color: #e0e0e0;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #b0b0b0;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background-color: #888888;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background-color: #e0e0e0;
    height: 10px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background-color: #b0b0b0;
    border-radius: 5px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background-color: #888888; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle {
    background-color: #cccccc;
    width: 4px;
}
QSplitter::handle:hover {
    background-color: #007bff;
}
"""

OLED_THEME = DARK_THEME.replace("#1a1a1a", "#000000").replace("#1e1e1e", "#050505").replace("#252525", "#0a0a0a")

NUKE_THEME = """
QMainWindow, QDialog, #SidePanel, QScrollArea, QScrollArea > QWidget {
    background-color: #282828;
    color: #e6e6e6;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 11px;
}
QGraphicsView {
    border: none;
}
QLabel {
    color: #e6e6e6;
    padding: 1px;
}
QLabel[title="true"] {
    color: #f0f0f0;
    font-weight: bold;
    font-size: 12px;
    padding-bottom: 4px;
}
QPushButton {
    background-color: #3b3b3b;
    color: #e6e6e6;
    border: 1px solid #1a1a1a;
    border-radius: 3px;
    padding: 5px 12px;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #4f4f4f;
    border-color: #f2a900;
}
QPushButton:pressed {
    background-color: #f2a900;
    color: #1a1a1a;
}
QPushButton:checked {
    background-color: #f2a900;
    border: 1px solid #c98c00;
    color: #1a1a1a;
    font-weight: bold;
}
QPushButton#btn_auto_calib {
    background-color: #2a5c2a;
    color: #90ee90;
    border-color: #3d7a3d;
    font-weight: bold;
    font-size: 12px;
    min-height: 28px;
}
QPushButton#btn_auto_calib:hover {
    background-color: #347034;
}
QPushButton#btn_export, QPushButton#btn_export_sequence {
    background-color: #1e3f6e;
    color: #7eb8f7;
    border-color: #2a5490;
    font-weight: bold;
    min-height: 28px;
}
QPushButton#btn_export:hover, QPushButton#btn_export_sequence:hover {
    background-color: #25508a;
}
QPushButton#btn_export_cg {
    background-color: #6b3d00;
    color: #ffb84d;
    border-color: #8a5200;
    font-weight: bold;
    min-height: 28px;
}
QPushButton#btn_export_cg:hover {
    background-color: #854d00;
}
QSlider::groove:horizontal {
    height: 4px;
    background-color: #1a1a1a;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #f2a900;
    border: 1px solid #1a1a1a;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #ffb833;
}
QSlider::sub-page:horizontal {
    background-color: #cc8e00;
    border-radius: 2px;
}
QComboBox {
    background-color: #3b3b3b;
    color: #e6e6e6;
    border: 1px solid #1a1a1a;
    border-radius: 3px;
    padding: 3px 8px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #f2a900;
}
QComboBox QAbstractItemView {
    background-color: #282828;
    border: 1px solid #1a1a1a;
    selection-background-color: #f2a900;
    selection-color: #1a1a1a;
    color: #e6e6e6;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 4px;
}
QLineEdit {
    background-color: #3b3b3b;
    color: #e6e6e6;
    border: 1px solid #1a1a1a;
    border-radius: 3px;
    padding: 3px 8px;
    min-height: 20px;
}
QLineEdit:focus {
    border-color: #f2a900;
}
QCheckBox {
    color: #e6e6e6;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border: 1px solid #1a1a1a;
    border-radius: 2px;
    background-color: #3b3b3b;
}
QCheckBox::indicator:checked {
    background-color: #f2a900;
    border-color: #cc8e00;
    image: none;
}
QCheckBox::indicator:hover {
    border-color: #ffb833;
}
QTabWidget::pane {
    border: 1px solid #1a1a1a;
    background-color: #282828;
}
QTabBar::tab {
    background-color: #3b3b3b;
    color: #aaaaaa;
    padding: 6px 14px;
    border: 1px solid #1a1a1a;
    border-bottom: none;
    border-radius: 3px 3px 0 0;
    min-width: 100px;
}
QTabBar::tab:selected {
    background-color: #282828;
    color: #f2a900;
    border-color: #1a1a1a;
}
QTabBar::tab:hover:!selected {
    background-color: #4f4f4f;
    color: #e6e6e6;
}
QGroupBox {
    color: #aaaaaa;
    border: 1px solid #1a1a1a;
    border-radius: 4px;
    margin-top: 10px;
    padding: 8px 6px 6px 6px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #f2a900;
}
QScrollArea {
    border: none;
    background-color: #282828;
}
QScrollBar:vertical {
    background-color: #282828;
    width: 12px;
    border-radius: 0px;
}
QScrollBar::handle:vertical {
    background-color: #4f4f4f;
    border-radius: 6px;
    min-height: 20px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background-color: #f2a900;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background-color: #282828;
    height: 12px;
    border-radius: 0px;
}
QScrollBar::handle:horizontal {
    background-color: #4f4f4f;
    border-radius: 6px;
    min-width: 20px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background-color: #f2a900; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle {
    background-color: #1a1a1a;
    width: 4px;
}
QSplitter::handle:hover {
    background-color: #f2a900;
}
"""

SYSTEM_THEME = """
#SidePanel, QScrollArea, QScrollArea > QWidget {
    background-color: palette(window);
}
"""

def get_theme(theme_name):
    if theme_name == "Dark":
        return DARK_THEME
    elif theme_name == "Light":
        return LIGHT_THEME
    elif theme_name == "OLED Dark":
        return OLED_THEME
    elif theme_name == "Nuke":
        return NUKE_THEME
    return SYSTEM_THEME
