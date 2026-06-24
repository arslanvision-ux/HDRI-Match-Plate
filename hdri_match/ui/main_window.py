import os
from hdri_match.ui.qt_shim import QtWidgets, QtCore, QtGui

from hdri_match.core.pipeline import CalibrationPipeline
from hdri_match.core.data_models import ImageState
from hdri_match.ui.viewer import ViewerWidget
from hdri_match.io.exporter import save_numpy_to_image, export_cg_light_data
from hdri_match.ui.theme import DARK_THEME, get_theme
import numpy as np

class CropDialog(QtWidgets.QDialog):
    def __init__(self, image_array, parent=None):
        super(CropDialog, self).__init__(parent)
        self.setWindowTitle("Crop Reference Image")
        self.resize(800, 600)
        self.image_array = image_array
        
        layout = QtWidgets.QVBoxLayout(self)
        
        from hdri_match.ui.viewer import ViewerWidget
        self.viewer = ViewerWidget()
        layout.addWidget(self.viewer)
        
        lbl_tip = QtWidgets.QLabel("Draw a rectangle over the target area, then click Apply Crop.")
        lbl_tip.setStyleSheet("color: #00ccff; font-weight: bold;")
        
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_apply = QtWidgets.QPushButton("Apply Crop")
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_layout.addWidget(lbl_tip)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_apply)
        layout.addLayout(btn_layout)
        
        self.btn_apply.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        self.viewer.set_image(image_array, reset_view=True)
        self.viewer.set_draw_mode(True, shape="Rectangle")
        
    def get_cropped_image(self):
        rect = self.viewer.get_mask_rect_normalized()
        if not rect:
            return None
        nx1, ny1, nx2, ny2 = rect
        h, w = self.image_array.shape[:2]
        x1, x2 = int(min(nx1, nx2) * w), int(max(nx1, nx2) * w)
        y1, y2 = int(min(ny1, ny2) * h), int(max(ny1, ny2) * h)
        if x2 > x1 and y2 > y1:
            return self.image_array[y1:y2, x1:x2]
        return None

class TimelineSlider(QtWidgets.QSlider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cached_frames = set()

    def set_cached_frames(self, frames):
        self.cached_frames = set(frames)
        self.update()

    def paintEvent(self, event):
        # Draw default slider first
        super().paintEvent(event)
        
        if not self.cached_frames:
            return
            
        min_v = self.minimum()
        max_v = self.maximum()
        if max_v <= min_v: return
        
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 220, 0, 150)) # Nuke green
        
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        rect = self.style().subControlRect(QtWidgets.QStyle.CC_Slider, opt, QtWidgets.QStyle.SC_SliderGroove, self)
        
        range_val = float(max_v - min_v)
        bar_y = rect.bottom() - 2
        
        for frame in self.cached_frames:
            if min_v <= frame <= max_v:
                x = rect.left() + (frame - min_v) / range_val * rect.width()
                painter.drawRect(QtCore.QRectF(x - 1, bar_y, 3, 3))

class CollapsibleGroupBox(QtWidgets.QGroupBox):
    def __init__(self, title, parent=None):
        super(CollapsibleGroupBox, self).__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(True)
        self.toggled.connect(self._toggle_content)

    def _toggle_content(self, checked):
        layout = self.layout()
        if layout:
            self._set_visible_recursive(layout, checked)

    def _set_visible_recursive(self, layout, visible):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w:
                w.setVisible(visible)
            elif item.layout():
                self._set_visible_recursive(item.layout(), visible)

class HdriCalibWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super(HdriCalibWindow, self).__init__(parent)
        self.setWindowTitle("HDRI Match Plate Calibration")
        self.resize(1900, 1000)
        
        self.pipeline = CalibrationPipeline()
        self._viewer_left_source_key = None
        self._viewer_right_source_key = None
        
        self._update_timer = QtCore.QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_deferred_update)
        self._pending_proxy = False
        
        self._playback_timer = QtCore.QTimer()
        self._playback_timer.timeout.connect(self.on_playback_tick)
        self._playback_cache = {}
        
        self.init_ui()
        self.connect_signals()
        self.populate_colorspaces()
        self.on_theme_changed("Dark")
        
    def init_ui(self):
        self.central_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QtWidgets.QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.main_layout.addWidget(self.main_splitter)
        
        # --- LEFT PANEL (I/O) ---
        self.left_scroll = QtWidgets.QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setMinimumWidth(320)
        self.left_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        
        self.left_panel = QtWidgets.QWidget()
        self.left_panel.setObjectName("SidePanel")
        self.left_layout = QtWidgets.QVBoxLayout(self.left_panel)
        self.left_scroll.setWidget(self.left_panel)
        
        io_header_layout = QtWidgets.QHBoxLayout()
        io_header_layout.addWidget(QtWidgets.QLabel("<b>I/O Settings</b>"))
        self.btn_new_project = QtWidgets.QPushButton("New Project")
        self.btn_save_project = QtWidgets.QPushButton("Save Project...")
        self.btn_load_project = QtWidgets.QPushButton("Load Project...")
        io_header_layout.addWidget(self.btn_new_project)
        io_header_layout.addWidget(self.btn_save_project)
        io_header_layout.addWidget(self.btn_load_project)
        self.left_layout.addLayout(io_header_layout)
        
        self.btn_open_3d = QtWidgets.QPushButton("Open 3D Scene Viewer")
        self.left_layout.addWidget(self.btn_open_3d)
        
        hdri_row = QtWidgets.QHBoxLayout()
        self.btn_load_hdri = QtWidgets.QPushButton("Browse HDRI...")
        self.btn_clear_hdri = QtWidgets.QPushButton("X")
        self.btn_clear_hdri.setFixedWidth(30)
        self.btn_clear_hdri.setToolTip("Clear HDRI")
        hdri_row.addWidget(self.btn_load_hdri)
        hdri_row.addWidget(self.btn_clear_hdri)
        self.left_layout.addLayout(hdri_row)
        self.lbl_hdri_path = QtWidgets.QLabel("No file selected")
        self.lbl_hdri_path.setFixedWidth(50)
        self.lbl_hdri_path.setWordWrap(True)
        self.left_layout.addWidget(self.lbl_hdri_path)
        
        plate_row = QtWidgets.QHBoxLayout()
        self.btn_load_plate = QtWidgets.QPushButton("Browse Plate...")
        self.btn_clear_plate = QtWidgets.QPushButton("X")
        self.btn_clear_plate.setFixedWidth(30)
        self.btn_clear_plate.setToolTip("Clear Plate")
        plate_row.addWidget(self.btn_load_plate)
        plate_row.addWidget(self.btn_clear_plate)
        self.left_layout.addLayout(plate_row)
        self.lbl_plate_path = QtWidgets.QLabel("No file selected")
        self.lbl_plate_path.setFixedWidth(50)
        self.lbl_plate_path.setWordWrap(True)
        self.left_layout.addWidget(self.lbl_plate_path)
        
        self.left_layout.addSpacing(15)
        
        self.left_layout.addWidget(QtWidgets.QLabel("<b>Calibration References</b>"))
        
        row_macbeth = QtWidgets.QHBoxLayout()
        self.btn_load_macbeth = QtWidgets.QPushButton("Load Macbeth Chart...")
        self.btn_auto_macbeth = QtWidgets.QPushButton("Auto")
        self.btn_auto_macbeth.setFixedWidth(55)
        self.btn_auto_macbeth.setToolTip("Auto-Detect Macbeth Chart & Generate 3x3 Color Matrix")
        self.btn_crop_macbeth = QtWidgets.QPushButton("Crop")
        self.btn_crop_macbeth.setFixedWidth(55)
        self.btn_crop_macbeth.setToolTip("Manually crop the loaded Macbeth Chart")
        self.btn_clear_macbeth = QtWidgets.QPushButton("X")
        self.btn_clear_macbeth.setFixedWidth(35)
        self.btn_clear_macbeth.setToolTip("Remove Macbeth Chart")
        row_macbeth.addWidget(self.btn_load_macbeth)
        row_macbeth.addWidget(self.btn_auto_macbeth)
        row_macbeth.addWidget(self.btn_crop_macbeth)
        row_macbeth.addWidget(self.btn_clear_macbeth)
        self.left_layout.addLayout(row_macbeth)
        
        row_chrome = QtWidgets.QHBoxLayout()
        self.btn_load_chrome = QtWidgets.QPushButton("Load Chrome Ball...")
        self.btn_crop_chrome = QtWidgets.QPushButton("Crop")
        self.btn_crop_chrome.setFixedWidth(55)
        self.btn_crop_chrome.setToolTip("Manually crop the loaded Chrome Ball")
        self.btn_clear_chrome = QtWidgets.QPushButton("X")
        self.btn_clear_chrome.setFixedWidth(35)
        self.btn_clear_chrome.setToolTip("Remove Chrome Ball")
        row_chrome.addWidget(self.btn_load_chrome)
        row_chrome.addWidget(self.btn_crop_chrome)
        row_chrome.addWidget(self.btn_clear_chrome)
        self.left_layout.addLayout(row_chrome)
        
        row_grey = QtWidgets.QHBoxLayout()
        self.btn_load_grey = QtWidgets.QPushButton("Load Grey Ball...")
        self.btn_crop_grey = QtWidgets.QPushButton("Crop")
        self.btn_crop_grey.setFixedWidth(55)
        self.btn_crop_grey.setToolTip("Manually crop the loaded Grey Ball")
        self.btn_clear_grey = QtWidgets.QPushButton("X")
        self.btn_clear_grey.setFixedWidth(35)
        self.btn_clear_grey.setToolTip("Remove Grey Ball")
        row_grey.addWidget(self.btn_load_grey)
        row_grey.addWidget(self.btn_crop_grey)
        row_grey.addWidget(self.btn_clear_grey)
        self.left_layout.addLayout(row_grey)
        
        self.left_layout.addSpacing(10)
        self.chk_autocrop = QtWidgets.QCheckBox("Auto-Crop on Load")
        self.chk_autocrop.setChecked(True)
        self.chk_autocrop.setToolTip("Automatically detect and crop references (Macbeth, Chrome, Grey) when loading.\nIf unchecked, it will crop using the active mask drawn in the viewer (if any).")
        self.left_layout.addWidget(self.chk_autocrop)
        
        self.chk_show_refs = QtWidgets.QCheckBox("Show References in Panel")
        self.chk_show_refs.setChecked(False) # Disabled by default for performance
        self.left_layout.addWidget(self.chk_show_refs)
        
        from hdri_match.ui.viewer import RefLabel
        self.lbl_ref_macbeth = RefLabel()
        self.lbl_ref_macbeth.hide()
        self.lbl_ref_macbeth.setToolTip("Macbeth Chart")
        
        self.lbl_ref_chrome = RefLabel()
        self.lbl_ref_chrome.hide()
        self.lbl_ref_chrome.setToolTip("Chrome Ball")
        
        self.lbl_ref_grey = RefLabel()
        self.lbl_ref_grey.hide()
        self.lbl_ref_grey.setToolTip("Grey Ball")
        
        self.left_layout.addWidget(self.lbl_ref_macbeth)
        self.left_layout.addWidget(self.lbl_ref_chrome)
        self.left_layout.addWidget(self.lbl_ref_grey)
        
        self.left_layout.addStretch()
        
        self.btn_export = QtWidgets.QPushButton("Export Calibrated HDRI...")
        self.btn_export.setObjectName("btn_export")
        self.btn_export_sequence = QtWidgets.QPushButton("Export HDRI Sequence...")
        self.btn_export_sequence.setObjectName("btn_export_sequence")
        self.btn_export_nuke = QtWidgets.QPushButton("Copy Nuke Nodes")
        self.btn_export_nuke.setToolTip("Copy the calibration math as live Nuke nodes to your clipboard.")
        
        self.btn_extract_lights = QtWidgets.QPushButton("Extract Lights (Sun)...")
        self.btn_extract_lights.setToolTip("Extract brightest regions from HDRI as Lights and generate Nuke patch script.")
        
        self.btn_export_camera = QtWidgets.QPushButton("Export Camera to Solaris...")
        self.btn_export_camera.setToolTip("Extract camera metadata from Plate EXR and generate Houdini Solaris script.")
        
        self.main_splitter.addWidget(self.left_scroll)
        
        # --- CENTER PANEL (Viewer) ---
        self.center_panel = QtWidgets.QFrame()
        self.center_layout = QtWidgets.QVBoxLayout(self.center_panel)
        
        self.viewer_toolbar = QtWidgets.QHBoxLayout()
        self.combo_view_mode = QtWidgets.QComboBox()
        self.combo_view_mode.addItems(["HDRI", "Plate", "CG Reconstructed", "CG Over Plate", "CG Alpha", "Difference Matte", "Split Comparison", "False Color"])
        self.viewer_toolbar.addWidget(QtWidgets.QLabel("View:"))
        self.viewer_toolbar.addWidget(self.combo_view_mode)
        
        self.viewer_toolbar.addSpacing(20)
        self.viewer_toolbar.addWidget(QtWidgets.QLabel("Viewport EV:"))
        
        self.slider_viewport_ev = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_viewport_ev.setRange(-1000, 1000)
        self.slider_viewport_ev.setValue(0)
        self.slider_viewport_ev.setFixedWidth(100)
        self.slider_viewport_ev.setToolTip("Exposure adjustment for the viewer only (does not affect data or export)")
        self.viewer_toolbar.addWidget(self.slider_viewport_ev)
        
        self.lbl_viewport_ev = QtWidgets.QLabel("0.00")
        self.lbl_viewport_ev.setFixedWidth(50)
        self.viewer_toolbar.addWidget(self.lbl_viewport_ev)
        
        self.btn_reset_viewport_ev = QtWidgets.QPushButton("Reset")
        self.btn_reset_viewport_ev.setFixedWidth(65)
        self.viewer_toolbar.addWidget(self.btn_reset_viewport_ev)
        
        self.viewer_toolbar.addStretch()
        
        self.viewer_toolbar.addWidget(QtWidgets.QLabel("Display View:"))
        self.combo_display_transform = QtWidgets.QComboBox()
        self.combo_display_transform.setMinimumWidth(150)
        self.viewer_toolbar.addWidget(self.combo_display_transform)
        
        self.viewer_toolbar.addWidget(QtWidgets.QLabel("Reformat:"))
        self.combo_reformat = QtWidgets.QComboBox()
        self.combo_reformat.addItems(["Native", "Match Plate", "640x360", "960x540", "1280x720", "1920x1080", "2048x1080", "2048x1556", "3840x2160", "4096x2160"])
        self.combo_reformat.setCurrentText("640x360") # Lightweight proxy by default
        self.combo_reformat.setToolTip("Resizes all images to this format for display and compositing")
        self.viewer_toolbar.addWidget(self.combo_reformat)
        
        self.btn_reset_view = QtWidgets.QPushButton("Reset View")
        self.btn_reset_view.setToolTip("Reset pan and zoom for both viewers to fit the image to the screen.")
        self.viewer_toolbar.addWidget(self.btn_reset_view)
        
        self.viewer_toolbar.addSpacing(20)
        self.viewer_toolbar.addWidget(QtWidgets.QLabel("Theme:"))
        self.combo_theme = QtWidgets.QComboBox()
        self.combo_theme.addItems(["Dark", "OLED Dark", "Nuke", "Light", "System"])
        self.combo_theme.setCurrentText("Dark")
        self.viewer_toolbar.addWidget(self.combo_theme)
        
        self.center_layout.addLayout(self.viewer_toolbar)
        
        self.center_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        
        self.viewer_container = QtWidgets.QWidget()
        self.viewer_vlayout = QtWidgets.QVBoxLayout(self.viewer_container)
        self.viewer_vlayout.setContentsMargins(0, 0, 0, 0)
        
        self.viewer_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.viewer_left = ViewerWidget()
        self.viewer_right = ViewerWidget()
        self.viewer_splitter.addWidget(self.viewer_left)
        self.viewer_splitter.addWidget(self.viewer_right)
        
        self.viewer_right.hide()
        self.viewer_vlayout.addWidget(self.viewer_splitter)
        
        self.center_splitter.addWidget(self.viewer_container)
        
        from hdri_match.ui.scopes import ScopesWidget
        self.scopes_widget = ScopesWidget()
        self.center_splitter.addWidget(self.scopes_widget)
        
        self.center_layout.addWidget(self.center_splitter)
        
        # --- TIMELINE (Sequence Support) ---
        self.timeline_layout = QtWidgets.QHBoxLayout()
        
        self.btn_first_frame = QtWidgets.QPushButton("|<")
        self.btn_first_frame.setFixedSize(35, 28)
        self.btn_first_frame.setToolTip("Go to First Frame")
        
        self.btn_prev_frame = QtWidgets.QPushButton("<")
        self.btn_prev_frame.setFixedSize(35, 28)
        self.btn_prev_frame.setToolTip("Previous Frame")
        
        self.btn_play_pause = QtWidgets.QPushButton("▶")
        self.btn_play_pause.setFixedSize(35, 28)
        self.btn_play_pause.setCheckable(True)
        self.btn_play_pause.setToolTip("Play/Pause")
        
        self.btn_next_frame = QtWidgets.QPushButton(">")
        self.btn_next_frame.setFixedSize(35, 28)
        self.btn_next_frame.setToolTip("Next Frame")
        
        self.btn_last_frame = QtWidgets.QPushButton(">|")
        self.btn_last_frame.setFixedSize(35, 28)
        self.btn_last_frame.setToolTip("Go to Last Frame")
        
        class TimelineSlider(QtWidgets.QSlider):
            def __init__(self, orientation):
                super().__init__(orientation)
                self.cached_frames = set()
            def set_cached_frames(self, frames):
                self.cached_frames = set(frames)
                self.update()
            def paintEvent(self, event):
                super().paintEvent(event)
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor(0, 255, 128, 150))
                
                min_v, max_v = self.minimum(), self.maximum()
                span = max_v - min_v
                if span <= 0: return
                
                rect = self.contentsRect()
                h = 4
                y = rect.bottom() - h - 2
                w = rect.width() - 10
                
                for f in self.cached_frames:
                    x = 5 + int((f - min_v) / span * w)
                    painter.drawRect(x, y, 2, h)
        
        self.slider_timeline = TimelineSlider(QtCore.Qt.Horizontal)
        self.slider_timeline.setEnabled(False)
        self.slider_timeline.setToolTip("Time Slider")
        
        self.lbl_timeline_frame = QtWidgets.QLabel("Frame: 0 / 0")
        self.lbl_timeline_frame.setFixedWidth(50)
        self.lbl_timeline_frame.setMinimumWidth(80)
        
        self.lbl_fps = QtWidgets.QLabel("FPS:")
        self.lbl_fps.setFixedWidth(50)
        self.combo_fps = QtWidgets.QComboBox()
        self.combo_fps.addItems(["12", "23.976", "24", "25", "29.97", "30", "48", "50", "59.94", "60"])
        self.combo_fps.setCurrentText("24")
        self.combo_fps.setToolTip("Playback Framerate")
        
        self.btn_reset_cache = QtWidgets.QPushButton("⟳ Cache")
        self.btn_reset_cache.setFixedHeight(28)
        self.btn_reset_cache.setToolTip("Clear the RAM frame buffer and re-cache the sequence on next playback")
        self.btn_reset_cache.setObjectName("btn_reset_cache")
        
        self.timeline_layout.addWidget(self.btn_first_frame)
        self.timeline_layout.addWidget(self.btn_prev_frame)
        self.timeline_layout.addWidget(self.btn_play_pause)
        self.timeline_layout.addWidget(self.btn_next_frame)
        self.timeline_layout.addWidget(self.btn_last_frame)
        self.timeline_layout.addWidget(self.slider_timeline, 1)
        self.timeline_layout.addWidget(self.lbl_timeline_frame)
        self.timeline_layout.addSpacing(6)
        self.timeline_layout.addWidget(self.lbl_fps)
        self.timeline_layout.addWidget(self.combo_fps)
        self.timeline_layout.addSpacing(6)
        self.timeline_layout.addWidget(self.btn_reset_cache)
        self.center_layout.addLayout(self.timeline_layout)
        
        self.main_splitter.addWidget(self.center_panel)
        
        # --- RIGHT PANEL (Tabs) ---
        self.right_panel = QtWidgets.QFrame()
        self.right_panel.setObjectName("SidePanel")
        self.right_panel.setMinimumWidth(360)
        self.right_layout = QtWidgets.QVBoxLayout(self.right_panel)
        
        self.right_tabs = QtWidgets.QTabWidget()
        
        # TAB 1: HDRI Match
        self.tab_hdri = QtWidgets.QScrollArea()
        self.tab_hdri.setWidgetResizable(True)
        self.tab_hdri.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tab_hdri_content = QtWidgets.QWidget()
        self.tab_hdri_content.setObjectName("SidePanel")
        self.layout_hdri = QtWidgets.QVBoxLayout(self.tab_hdri_content)
        self.tab_hdri.setWidget(self.tab_hdri_content)
        
        # --- Colorspace settings ---
        self.layout_hdri.addWidget(QtWidgets.QLabel("<b>OCIO Colorspace</b>"))
        
        ocio_row = QtWidgets.QHBoxLayout()
        ocio_row.addWidget(QtWidgets.QLabel("Config:"))
        self.lbl_ocio_path = QtWidgets.QLabel("Default (Env)")
        self.lbl_ocio_path.setFixedWidth(50)
        self.btn_load_ocio = QtWidgets.QPushButton("Browse...")
        self.btn_ocio_nuke = QtWidgets.QPushButton("From Nuke")
        
        try:
            import nuke
        except ImportError:
            self.btn_ocio_nuke.setVisible(False)
            
        ocio_row.addWidget(self.lbl_ocio_path, 1)
        ocio_row.addWidget(self.btn_ocio_nuke)
        ocio_row.addWidget(self.btn_load_ocio)
        self.layout_hdri.addLayout(ocio_row)
        
        cs_row1 = QtWidgets.QHBoxLayout()
        cs_row1.addWidget(QtWidgets.QLabel("Input:"))
        self.combo_cs_input = QtWidgets.QComboBox()
        self.combo_cs_input.setEditable(True)
        self.combo_cs_input.addItems(["ACEScg", "Linear", "sRGB", "Rec709", "ACES2065-1", "scene_linear"])
        self.combo_cs_input.setCurrentText("ACEScg")
        self.combo_cs_input.setToolTip("Colorspace of input EXR files (HDRI, Plate, CG)")
        cs_row1.addWidget(self.combo_cs_input, 1)
        self.layout_hdri.addLayout(cs_row1)
        
        cs_row2 = QtWidgets.QHBoxLayout()
        cs_row2.addWidget(QtWidgets.QLabel("Output:"))
        self.combo_cs_output = QtWidgets.QComboBox()
        self.combo_cs_output.setEditable(True)
        self.combo_cs_output.addItems(["Linear", "ACEScg", "sRGB", "Rec709", "ACES2065-1", "scene_linear"])
        self.combo_cs_output.setCurrentText("ACEScg")
        self.combo_cs_output.setToolTip("Working/export space for calibration and HDRI export")
        cs_row2.addWidget(self.combo_cs_output, 1)
        self.layout_hdri.addLayout(cs_row2)
        self.layout_hdri.addSpacing(10)
        
        self.btn_auto_calib = QtWidgets.QPushButton("Auto Match Plate")
        self.btn_auto_calib.setObjectName("btn_auto_calib")
        self.layout_hdri.addWidget(self.btn_auto_calib)
        
        self.chk_ai_awb = QtWidgets.QCheckBox("Use AI Auto White Balance (ONNX)")
        self.chk_ai_awb.setChecked(False) # Disabled by default for performance
        self.chk_ai_awb.setToolTip("Use ONNX deep learning model to estimate the true scene illuminant from the plate, falling back to Gray-World if unavailable.")
        self.layout_hdri.addWidget(self.chk_ai_awb)
        
        calib_row = QtWidgets.QHBoxLayout()
        self.btn_pick_wb = QtWidgets.QPushButton("Pick White Balance (Grey)")
        self.btn_pick_wb.setCheckable(True)
        self.btn_pick_wb.setToolTip("Toggle to pick a neutral grey patch in the viewer to auto-balance Temp and Tint.")
        self.btn_reset_calib = QtWidgets.QPushButton("Reset")
        self.btn_reset_calib.setToolTip("Reset HDRI adjustments and auto-match to defaults")
        calib_row.addWidget(self.btn_pick_wb, 3)
        calib_row.addWidget(self.btn_reset_calib, 1)
        self.layout_hdri.addLayout(calib_row)
        
        self.combo_sky_mode = QtWidgets.QComboBox()
        self.combo_sky_mode.addItems(["Off", "Sky Top 40%"])
        self.combo_sky_mode.setCurrentIndex(1)  # Default: Top 40%
        self.combo_sky_mode.setToolTip(
            "Off: full-frame gray world\n"
            "Top 40%: use upper 40% of HDRI (equirectangular sky)")
        sky_row = QtWidgets.QHBoxLayout()
        sky_row.addWidget(QtWidgets.QLabel("Sky Mode:"))
        sky_row.addWidget(self.combo_sky_mode, 1)
        self.layout_hdri.addLayout(sky_row)
        
        # Multi-Mask Editor
        self.group_masks = CollapsibleGroupBox("Multi-Mask Editor")
        self.group_masks.setCheckable(True)
        self.group_masks.setChecked(True)
        mask_main_layout = QtWidgets.QVBoxLayout(self.group_masks)
        
        mask_list_row = QtWidgets.QHBoxLayout()
        self.list_masks = QtWidgets.QListWidget()
        self.list_masks.setMaximumHeight(80)
        self.list_masks.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        mask_list_row.addWidget(self.list_masks)
        
        mask_btns_layout = QtWidgets.QVBoxLayout()
        self.btn_add_mask = QtWidgets.QPushButton("+ Add")
        self.btn_remove_mask = QtWidgets.QPushButton("- Remove")
        self.btn_deselect_mask = QtWidgets.QPushButton("Deselect")
        mask_btns_layout.addWidget(self.btn_add_mask)
        mask_btns_layout.addWidget(self.btn_remove_mask)
        mask_btns_layout.addWidget(self.btn_deselect_mask)
        mask_btns_layout.addStretch()
        mask_list_row.addLayout(mask_btns_layout)
        mask_main_layout.addLayout(mask_list_row)
        
        self.btn_export_mask_lights = QtWidgets.QPushButton("Export Masks as Solaris Lights")
        self.btn_export_mask_lights.setToolTip("Export the selected regions as physically correct textured Lights for Houdini Solaris.")
        self.btn_export_mask_lights.hide() # Hidden because masks auto-export with Solaris Publish
        # mask_main_layout.addWidget(self.btn_export_mask_lights)
        
        self.mask_options_widget = QtWidgets.QWidget()
        self.mask_options_widget.setEnabled(False) # Disabled when no mask selected
        mask_opt_layout = QtWidgets.QVBoxLayout(self.mask_options_widget)
        mask_opt_layout.setContentsMargins(0, 0, 0, 0)
        
        enable_row = QtWidgets.QHBoxLayout()
        self.chk_enable_mask = QtWidgets.QCheckBox("Enable Layer")
        self.chk_enable_mask.setChecked(True)
        enable_row.addWidget(self.chk_enable_mask)
        enable_row.addStretch()
        mask_opt_layout.addLayout(enable_row)
        
        target_row = QtWidgets.QHBoxLayout()
        target_row.addWidget(QtWidgets.QLabel("Target:"))
        self.combo_mask_target = QtWidgets.QComboBox()
        self.combo_mask_target.addItems(["HDRI", "Plate"])
        target_row.addWidget(self.combo_mask_target, 1)
        mask_opt_layout.addLayout(target_row)
        
        shape_row = QtWidgets.QHBoxLayout()
        shape_row.addWidget(QtWidgets.QLabel("Mask Shape:"))
        self.combo_mask_shape = QtWidgets.QComboBox()
        self.combo_mask_shape.addItems(["Rectangle", "Ellipse", "Polygon", "Lasso", "Brush", "Image"])
        shape_row.addWidget(self.combo_mask_shape, 1)
        mask_opt_layout.addLayout(shape_row)
        
        self.widget_image_decal = QtWidgets.QWidget()
        decal_row = QtWidgets.QHBoxLayout(self.widget_image_decal)
        decal_row.setContentsMargins(0, 0, 0, 0)
        decal_row.addWidget(QtWidgets.QLabel("Image File:"))
        self.line_edit_mask_image = QtWidgets.QLineEdit()
        self.btn_mask_image = QtWidgets.QPushButton("Browse...")
        self.btn_mask_image.clicked.connect(self.on_browse_mask_image_clicked)
        decal_row.addWidget(self.line_edit_mask_image, 1)
        decal_row.addWidget(self.btn_mask_image)
        mask_opt_layout.addWidget(self.widget_image_decal)
        self.widget_image_decal.setVisible(False)
        
        brush_row = QtWidgets.QHBoxLayout()
        brush_row.addWidget(QtWidgets.QLabel("Brush Size:"))
        self.slider_mask_brush = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_brush.setRange(1, 500)
        self.slider_mask_brush.setValue(20)
        self.lbl_mask_brush = QtWidgets.QLabel("20 px")
        self.lbl_mask_brush.setFixedWidth(50)
        brush_row.addWidget(self.slider_mask_brush)
        brush_row.addWidget(self.lbl_mask_brush)
        self.widget_brush = QtWidgets.QWidget()
        self.widget_brush.setLayout(brush_row)
        mask_opt_layout.addWidget(self.widget_brush)
        
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Mask Mode:"))
        self.combo_mask_mode = QtWidgets.QComboBox()
        self.combo_mask_mode.addItems(["Grade", "Solid Fill", "Chroma Replace", "AI Inpaint"])
        mode_row.addWidget(self.combo_mask_mode, 1)
        mask_opt_layout.addLayout(mode_row)
        
        ltype_row = QtWidgets.QHBoxLayout()
        ltype_row.addWidget(QtWidgets.QLabel("Light Type:"))
        self.combo_light_type = QtWidgets.QComboBox()
        self.combo_light_type.addItems(["Dome Light", "Rect Light"])
        ltype_row.addWidget(self.combo_light_type, 1)
        mask_opt_layout.addLayout(ltype_row)
        
        feather_row = QtWidgets.QHBoxLayout()
        feather_row.addWidget(QtWidgets.QLabel("Feather:"))
        self.slider_mask_feather = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_feather.setRange(0, 500)
        self.slider_mask_feather.setValue(0)
        self.lbl_mask_feather = QtWidgets.QLabel("0 px")
        self.lbl_mask_feather.setFixedWidth(50)
        feather_row.addWidget(self.slider_mask_feather)
        feather_row.addWidget(self.lbl_mask_feather)
        mask_opt_layout.addLayout(feather_row)
        
        mask_blend_row = QtWidgets.QHBoxLayout()
        mask_blend_row.addWidget(QtWidgets.QLabel("Blend/Mode:"))
        
        self.combo_mask_blend_mode = QtWidgets.QComboBox()
        self.combo_mask_blend_mode.addItems(["over", "plus", "multiply", "screen"])
        mask_blend_row.addWidget(self.combo_mask_blend_mode)
        
        self.slider_mask_blend = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_blend.setRange(0, 100)
        self.slider_mask_blend.setValue(100)
        self.lbl_mask_blend = QtWidgets.QLabel("100 %")
        self.lbl_mask_blend.setFixedWidth(50)
        mask_blend_row.addWidget(self.slider_mask_blend)
        mask_blend_row.addWidget(self.lbl_mask_blend)
        mask_opt_layout.addLayout(mask_blend_row)
        
        mask_blur_row = QtWidgets.QHBoxLayout()
        mask_blur_row.addWidget(QtWidgets.QLabel("Mask Blur:"))
        self.slider_mask_blur = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_blur.setRange(0, 1000)
        self.slider_mask_blur.setValue(0)
        self.lbl_mask_blur = QtWidgets.QLabel("0 px")
        self.lbl_mask_blur.setFixedWidth(50)
        mask_blur_row.addWidget(self.slider_mask_blur)
        mask_blur_row.addWidget(self.lbl_mask_blur)
        mask_opt_layout.addLayout(mask_blur_row)
        
        # Transform Group
        self.group_mask_transform = QtWidgets.QGroupBox("Transform")
        transform_layout = QtWidgets.QVBoxLayout(self.group_mask_transform)
        transform_layout.setContentsMargins(8, 8, 8, 8)
        mask_opt_layout.addWidget(self.group_mask_transform)
        
        # Transform: Translate X
        tx_row = QtWidgets.QHBoxLayout()
        tx_row.addWidget(QtWidgets.QLabel("Translate X:"))
        self.slider_mask_tx = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_tx.setRange(-4000, 4000)
        self.slider_mask_tx.setValue(0)
        self.spin_mask_tx = QtWidgets.QDoubleSpinBox()
        self.spin_mask_tx.setRange(-4000.0, 4000.0)
        self.spin_mask_tx.setSingleStep(5.0)
        self.spin_mask_tx.setFixedWidth(80)
        tx_row.addWidget(self.slider_mask_tx)
        tx_row.addWidget(self.spin_mask_tx)
        transform_layout.addLayout(tx_row)
        
        # Transform: Translate Y
        ty_row = QtWidgets.QHBoxLayout()
        ty_row.addWidget(QtWidgets.QLabel("Translate Y:"))
        self.slider_mask_ty = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_ty.setRange(-4000, 4000)
        self.slider_mask_ty.setValue(0)
        self.spin_mask_ty = QtWidgets.QDoubleSpinBox()
        self.spin_mask_ty.setRange(-4000.0, 4000.0)
        self.spin_mask_ty.setSingleStep(5.0)
        self.spin_mask_ty.setFixedWidth(80)
        ty_row.addWidget(self.slider_mask_ty)
        ty_row.addWidget(self.spin_mask_ty)
        transform_layout.addLayout(ty_row)

        # Transform: Scale
        scale_row = QtWidgets.QHBoxLayout()
        scale_row.addWidget(QtWidgets.QLabel("Scale:"))
        self.slider_mask_scale = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_scale.setRange(1, 1000)
        self.slider_mask_scale.setValue(100)
        self.spin_mask_scale = QtWidgets.QDoubleSpinBox()
        self.spin_mask_scale.setRange(0.01, 10.0)
        self.spin_mask_scale.setValue(1.0)
        self.spin_mask_scale.setSingleStep(0.05)
        self.spin_mask_scale.setFixedWidth(80)
        scale_row.addWidget(self.slider_mask_scale)
        scale_row.addWidget(self.spin_mask_scale)
        transform_layout.addLayout(scale_row)
        
        # Transform: Rotate
        rot_row = QtWidgets.QHBoxLayout()
        rot_row.addWidget(QtWidgets.QLabel("Rotate:"))
        self.slider_mask_rotate = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_rotate.setRange(-360, 360)
        self.slider_mask_rotate.setValue(0)
        self.spin_mask_rotate = QtWidgets.QDoubleSpinBox()
        self.spin_mask_rotate.setRange(-360.0, 360.0)
        self.spin_mask_rotate.setSingleStep(1.0)
        self.spin_mask_rotate.setFixedWidth(80)
        rot_row.addWidget(self.slider_mask_rotate)
        rot_row.addWidget(self.spin_mask_rotate)
        transform_layout.addLayout(rot_row)
        
        stencil_row1 = QtWidgets.QHBoxLayout()
        self.chk_stencil = QtWidgets.QCheckBox("Enable Keyer Stencil")
        self.chk_stencil.setToolTip("Isolates the mask behind/in-front of specific scene elements (protects trees/skies).")
        
        self.combo_stencil_mode = QtWidgets.QComboBox()
        self.combo_stencil_mode.addItems(["Luminance", "Green Key", "Blue Key"])
        
        self.chk_stencil_invert = QtWidgets.QCheckBox("Invert")
        
        stencil_row1.addWidget(self.chk_stencil)
        stencil_row1.addWidget(self.combo_stencil_mode)
        stencil_row1.addWidget(self.chk_stencil_invert)
        stencil_row1.addStretch()
        mask_opt_layout.addLayout(stencil_row1)
        
        stencil_row2 = QtWidgets.QHBoxLayout()
        stencil_row2.addWidget(QtWidgets.QLabel("Threshold/Tol:"))
        self.slider_stencil_thresh = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_stencil_thresh.setRange(0, 100)
        self.slider_stencil_thresh.setValue(50)
        self.lbl_stencil_thresh = QtWidgets.QLabel("0.50")
        self.lbl_stencil_thresh.setFixedWidth(50)
        stencil_row2.addWidget(self.slider_stencil_thresh)
        stencil_row2.addWidget(self.lbl_stencil_thresh)
        mask_opt_layout.addLayout(stencil_row2)
        
        mask_ev_row = QtWidgets.QHBoxLayout()
        mask_ev_row.addWidget(QtWidgets.QLabel("Grade EV:"))
        self.slider_mask_ev = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_ev.setRange(-1000, 1000)
        self.slider_mask_ev.setValue(0)
        self.lbl_mask_ev = QtWidgets.QLabel("0.00 EV")
        self.lbl_mask_ev.setFixedWidth(50)
        mask_ev_row.addWidget(self.slider_mask_ev)
        mask_ev_row.addWidget(self.lbl_mask_ev)
        mask_opt_layout.addLayout(mask_ev_row)
        
        mask_temp_row = QtWidgets.QHBoxLayout()
        mask_temp_row.addWidget(QtWidgets.QLabel("Grade Temp:"))
        self.slider_mask_temp = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_temp.setRange(-100, 100)
        self.slider_mask_temp.setValue(0)
        self.lbl_mask_temp = QtWidgets.QLabel("0.00")
        self.lbl_mask_temp.setFixedWidth(50)
        mask_temp_row.addWidget(self.slider_mask_temp)
        mask_temp_row.addWidget(self.lbl_mask_temp)
        mask_opt_layout.addLayout(mask_temp_row)
        
        mask_tint_row = QtWidgets.QHBoxLayout()
        mask_tint_row.addWidget(QtWidgets.QLabel("Grade Tint:"))
        self.slider_mask_tint = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_mask_tint.setRange(-100, 100)
        self.slider_mask_tint.setValue(0)
        self.lbl_mask_tint = QtWidgets.QLabel("0.00")
        self.lbl_mask_tint.setFixedWidth(50)
        mask_tint_row.addWidget(self.slider_mask_tint)
        mask_tint_row.addWidget(self.lbl_mask_tint)
        mask_opt_layout.addLayout(mask_tint_row)
        
        # Grading rows container for easy show/hide
        self.widget_grade = QtWidgets.QWidget()
        grade_layout = QtWidgets.QVBoxLayout(self.widget_grade)
        grade_layout.setContentsMargins(0,0,0,0)
        grade_layout.addLayout(mask_ev_row)
        grade_layout.addLayout(mask_temp_row)
        grade_layout.addLayout(mask_tint_row)
        mask_opt_layout.addWidget(self.widget_grade)
        
        self.btn_mask_color = QtWidgets.QPushButton("Pick Fill Color...")
        self.btn_mask_color.hide()
        mask_opt_layout.addWidget(self.btn_mask_color)
        
        self.chroma_widget = QtWidgets.QWidget()
        self.chroma_widget.hide()
        chroma_layout = QtWidgets.QVBoxLayout(self.chroma_widget)
        chroma_layout.setContentsMargins(0,0,0,0)
        
        c_row1 = QtWidgets.QHBoxLayout()
        c_row1.addWidget(QtWidgets.QLabel("Chroma Target:"))
        self.combo_chroma = QtWidgets.QComboBox()
        self.combo_chroma.addItems(["Green Screen", "Blue Screen"])
        c_row1.addWidget(self.combo_chroma)
        chroma_layout.addLayout(c_row1)
        
        c_row2 = QtWidgets.QHBoxLayout()
        c_row2.addWidget(QtWidgets.QLabel("Tolerance:"))
        self.slider_chroma_tol = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_chroma_tol.setRange(0, 100)
        self.slider_chroma_tol.setValue(50)
        c_row2.addWidget(self.slider_chroma_tol)
        chroma_layout.addLayout(c_row2)
        
        mask_opt_layout.addWidget(self.chroma_widget)
        
        # --- AI Inpaint Widget ---
        self.inpaint_widget = QtWidgets.QWidget()
        self.inpaint_widget.hide()
        inpaint_layout = QtWidgets.QVBoxLayout(self.inpaint_widget)
        inpaint_layout.setContentsMargins(0,0,0,0)
        
        backend_row = QtWidgets.QHBoxLayout()
        backend_row.addWidget(QtWidgets.QLabel("AI Backend:"))
        self.combo_inpaint_backend = QtWidgets.QComboBox()
        self.combo_inpaint_backend.addItems([
            "ComfyUI (Local)",
            "Google GenAI (Nano Banana)"
        ])
        backend_row.addWidget(self.combo_inpaint_backend)
        inpaint_layout.addLayout(backend_row)
        
        self.line_edit_inpaint_prompt = QtWidgets.QLineEdit("clear blue sky, empty dirt road")
        self.line_edit_inpaint_neg_prompt = QtWidgets.QLineEdit("bad quality, blurry, text, watermark")
        self.line_edit_inpaint_prompt.hide()
        self.line_edit_inpaint_neg_prompt.hide()

        self.btn_edit_prompts = QtWidgets.QPushButton("Edit AI Prompts...")
        self.btn_edit_prompts.setToolTip("Open the prompt editor window.")
        self.btn_edit_prompts.clicked.connect(self.open_prompt_editor)
        inpaint_layout.addWidget(self.btn_edit_prompts)
        
        self.api_label = QtWidgets.QLabel("API URL:")
        api_row = QtWidgets.QHBoxLayout()
        api_row.addWidget(self.api_label)
        self.line_edit_inpaint_api = QtWidgets.QLineEdit("http://127.0.0.1:8188")
        self.line_edit_inpaint_api.setToolTip("URL for ComfyUI, or API Key for Cloud services.")
        api_row.addWidget(self.line_edit_inpaint_api)
        inpaint_layout.addLayout(api_row)
        
        self.model_dir_label = QtWidgets.QLabel("Models Dir:")
        model_dir_row = QtWidgets.QHBoxLayout()
        model_dir_row.addWidget(self.model_dir_label)
        self.line_edit_model_dir = QtWidgets.QLineEdit(r"E:\ComfyUI\ComfyUI\models")
        self.line_edit_model_dir.setToolTip("Path to your ComfyUI models folder.")
        model_dir_row.addWidget(self.line_edit_model_dir)
        self.btn_browse_model_dir = QtWidgets.QPushButton("Browse...")
        self.btn_browse_model_dir.clicked.connect(self.on_browse_model_dir_clicked)
        model_dir_row.addWidget(self.btn_browse_model_dir)
        inpaint_layout.addLayout(model_dir_row)
        
        self.unet_label = QtWidgets.QLabel("Unet:")
        unet_row = QtWidgets.QHBoxLayout()
        unet_row.addWidget(self.unet_label)
        self.line_edit_inpaint_unet = QtWidgets.QLineEdit("")
        self.line_edit_inpaint_unet.setToolTip("Filename of your diffusion model in ComfyUI/models/unet/")
        unet_row.addWidget(self.line_edit_inpaint_unet)
        self.btn_browse_unet = QtWidgets.QPushButton("Browse...")
        self.btn_browse_unet.clicked.connect(self.on_browse_unet_clicked)
        unet_row.addWidget(self.btn_browse_unet)
        inpaint_layout.addLayout(unet_row)

        self.clip_label = QtWidgets.QLabel("CLIP:")
        clip_row = QtWidgets.QHBoxLayout()
        clip_row.addWidget(self.clip_label)
        self.line_edit_inpaint_clip = QtWidgets.QLineEdit("qwen_3_8b_fp8mixed.safetensors")
        self.line_edit_inpaint_clip.setToolTip("Filename of your CLIP model in ComfyUI/models/clip/")
        clip_row.addWidget(self.line_edit_inpaint_clip)
        self.btn_browse_clip = QtWidgets.QPushButton("Browse...")
        self.btn_browse_clip.clicked.connect(self.on_browse_clip_clicked)
        clip_row.addWidget(self.btn_browse_clip)
        inpaint_layout.addLayout(clip_row)

        self.vae_label = QtWidgets.QLabel("VAE:")
        vae_row = QtWidgets.QHBoxLayout()
        vae_row.addWidget(self.vae_label)
        self.line_edit_inpaint_vae = QtWidgets.QLineEdit("flux2-vae.safetensors")
        self.line_edit_inpaint_vae.setToolTip("Filename of your VAE model in ComfyUI/models/vae/")
        vae_row.addWidget(self.line_edit_inpaint_vae)
        self.btn_browse_vae = QtWidgets.QPushButton("Browse...")
        self.btn_browse_vae.clicked.connect(self.on_browse_vae_clicked)
        vae_row.addWidget(self.btn_browse_vae)
        inpaint_layout.addLayout(vae_row)

        self.ckpt_label = QtWidgets.QLabel("Checkpoint:")
        ckpt_row = QtWidgets.QHBoxLayout()
        ckpt_row.addWidget(self.ckpt_label)
        self.line_edit_inpaint_ckpt = QtWidgets.QLineEdit("flux-2-klein-9b-fp8mixed.safetensors")
        self.line_edit_inpaint_ckpt.setToolTip("Filename of your model in ComfyUI/models/checkpoints/ (Used if separate models are empty)")
        ckpt_row.addWidget(self.line_edit_inpaint_ckpt)
        self.btn_browse_ckpt = QtWidgets.QPushButton("Browse...")
        self.btn_browse_ckpt.clicked.connect(self.on_browse_ckpt_clicked)
        ckpt_row.addWidget(self.btn_browse_ckpt)
        inpaint_layout.addLayout(ckpt_row)
        
        self.upscaler_label = QtWidgets.QLabel("Upscaler:")
        upscaler_row = QtWidgets.QHBoxLayout()
        upscaler_row.addWidget(self.upscaler_label)
        self.line_edit_inpaint_upscaler = QtWidgets.QLineEdit("None")
        self.line_edit_inpaint_upscaler.setToolTip("Filename of your upscale model in ComfyUI/models/upscale_models/. Set to 'None' to disable.")
        upscaler_row.addWidget(self.line_edit_inpaint_upscaler)
        self.btn_browse_upscaler = QtWidgets.QPushButton("Browse...")
        self.btn_browse_upscaler.clicked.connect(self.on_browse_upscaler_clicked)
        upscaler_row.addWidget(self.btn_browse_upscaler)
        inpaint_layout.addLayout(upscaler_row)
        
        # Profile
        profile_row = QtWidgets.QHBoxLayout()
        profile_row.addWidget(QtWidgets.QLabel("Model Profile:"))
        self.combo_inpaint_profile = QtWidgets.QComboBox()
        self.combo_inpaint_profile.addItems([
            "Auto-Detect",
            "Flux Dev",
            "Flux Schnell/Klein",
            "SDXL Turbo",
            "Z-Image Turbo",
            "LTX-2",
            "Standard SD/SDXL"
        ])
        self.combo_inpaint_profile.setToolTip("Select the model architecture to automatically apply the best hyper-parameters.")
        profile_row.addWidget(self.combo_inpaint_profile)
        inpaint_layout.addLayout(profile_row)
        
        # Steps and CFG
        params_row = QtWidgets.QHBoxLayout()
        params_row.addWidget(QtWidgets.QLabel("Steps:"))
        self.spin_inpaint_steps = QtWidgets.QSpinBox()
        self.spin_inpaint_steps.setRange(1, 100)
        self.spin_inpaint_steps.setValue(20)
        self.spin_inpaint_steps.setToolTip("Higher steps = better quality but slower. (Use 20-30 for realistic models)")
        params_row.addWidget(self.spin_inpaint_steps)
        
        params_row.addWidget(QtWidgets.QLabel("CFG:"))
        self.spin_inpaint_cfg = QtWidgets.QDoubleSpinBox()
        self.spin_inpaint_cfg.setRange(1.0, 20.0)
        self.spin_inpaint_cfg.setSingleStep(0.5)
        self.spin_inpaint_cfg.setValue(4.0)
        self.spin_inpaint_cfg.setToolTip("How strictly to follow the prompt. (Use 4.0-8.0 for realistic models)")
        params_row.addWidget(self.spin_inpaint_cfg)
        
        params_row.addWidget(QtWidgets.QLabel("Denoise:"))
        self.spin_inpaint_denoise = QtWidgets.QDoubleSpinBox()
        self.spin_inpaint_denoise.setRange(0.01, 1.0)
        self.spin_inpaint_denoise.setSingleStep(0.05)
        self.spin_inpaint_denoise.setValue(1.0)
        self.spin_inpaint_denoise.setToolTip("Denoise strength. 1.0 = overwrite everything. 0.6 = keep base image and blend.")
        params_row.addWidget(self.spin_inpaint_denoise)
        
        inpaint_layout.addLayout(params_row)
        
        # Second Params Row for Seed, etc
        params_row2 = QtWidgets.QHBoxLayout()
        params_row2.addWidget(QtWidgets.QLabel("Seed:"))
        self.spin_inpaint_seed = QtWidgets.QSpinBox()
        self.spin_inpaint_seed.setRange(0, 2147483647)
        self.spin_inpaint_seed.setValue(0)
        params_row2.addWidget(self.spin_inpaint_seed)
        
        self.combo_inpaint_seed_method = QtWidgets.QComboBox()
        self.combo_inpaint_seed_method.addItems(["randomize", "fixed", "increment", "decrement"])
        params_row2.addWidget(self.combo_inpaint_seed_method)
        
        self.chk_inpaint_rembg = QtWidgets.QCheckBox("Remove BG (Requires ComfyUI-rembg)")
        self.chk_inpaint_rembg.setToolTip("Adds an ImageRemBG node to the ComfyUI workflow to remove the AI's generated background.")
        params_row2.addWidget(self.chk_inpaint_rembg)
        
        self.chk_inpaint_key_green = QtWidgets.QCheckBox("Key Green Screen")
        self.chk_inpaint_key_green.setToolTip("Automatically keys out pure green backgrounds and converts them to transparent alpha.")
        params_row2.addWidget(self.chk_inpaint_key_green)
        
        self.chk_spherical_proj = QtWidgets.QCheckBox("Spherical Proj")
        self.chk_spherical_proj.setToolTip("Extracts and applies the patch using proper equirectangular mapping to avoid distortion at poles.")
        params_row2.addWidget(self.chk_spherical_proj)
        
        inpaint_layout.addLayout(params_row2)
        
        # Custom Workflow
        custom_wf_row = QtWidgets.QHBoxLayout()
        self.chk_custom_wf = QtWidgets.QCheckBox("Use Custom API JSON")
        self.chk_custom_wf.stateChanged.connect(self.on_custom_wf_toggled)
        custom_wf_row.addWidget(self.chk_custom_wf)
        self.line_edit_custom_wf = QtWidgets.QLineEdit()
        self.line_edit_custom_wf.setPlaceholderText("Path to ComfyUI API workflow.json...")
        self.line_edit_custom_wf.setEnabled(False)
        custom_wf_row.addWidget(self.line_edit_custom_wf)
        self.btn_browse_custom_wf = QtWidgets.QPushButton("Browse...")
        self.btn_browse_custom_wf.setEnabled(False)
        self.btn_browse_custom_wf.clicked.connect(self.on_browse_custom_wf_clicked)
        custom_wf_row.addWidget(self.btn_browse_custom_wf)
        inpaint_layout.addLayout(custom_wf_row)
        
        self.btn_run_inpaint = QtWidgets.QPushButton("Run AI Inpaint")
        self.btn_run_inpaint.setToolTip("Sends masked HDRI to local ComfyUI API for inpainting.")
        inpaint_layout.addWidget(self.btn_run_inpaint)
        
        # Connect signals so values persist when editing other mask properties
        self.line_edit_inpaint_prompt.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_inpaint_neg_prompt.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_inpaint_api.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_inpaint_unet.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_inpaint_clip.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_inpaint_vae.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_inpaint_ckpt.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_inpaint_upscaler.textChanged.connect(self.on_inpaint_ui_changed)
        self.spin_inpaint_steps.valueChanged.connect(self.on_inpaint_ui_changed)
        self.spin_inpaint_cfg.valueChanged.connect(self.on_inpaint_ui_changed)
        self.spin_inpaint_denoise.valueChanged.connect(self.on_inpaint_ui_changed)
        self.spin_inpaint_seed.valueChanged.connect(self.on_inpaint_ui_changed)
        self.combo_inpaint_seed_method.currentIndexChanged.connect(self.on_inpaint_ui_changed)
        self.combo_inpaint_profile.currentTextChanged.connect(self.on_inpaint_profile_changed)
        self.chk_inpaint_rembg.stateChanged.connect(self.on_inpaint_ui_changed)
        self.chk_inpaint_key_green.stateChanged.connect(self.on_inpaint_ui_changed)
        self.chk_spherical_proj.stateChanged.connect(self.on_inpaint_ui_changed)
        self.chk_custom_wf.stateChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_custom_wf.textChanged.connect(self.on_inpaint_ui_changed)
        self.line_edit_model_dir.textChanged.connect(self.on_inpaint_ui_changed)
        
        mask_opt_layout.addWidget(self.inpaint_widget)
        
        mask_main_layout.addWidget(self.mask_options_widget)
        self.layout_hdri.addWidget(self.group_masks)

        # --- Interactive Sun Relighting ---
        self.layout_hdri.addSpacing(10)
        self.group_sun_relight = CollapsibleGroupBox("Interactive Sun Relighting")
        self.group_sun_relight.setChecked(False)
        self.layout_sun_relight = QtWidgets.QVBoxLayout(self.group_sun_relight)
        
        self.chk_enable_sun_relight = QtWidgets.QCheckBox("Enable Sun Relighting")
        self.chk_enable_sun_relight.setToolTip("Moves the sun to a new position using spherical inpainting.")
        self.layout_sun_relight.addWidget(self.chk_enable_sun_relight)
        
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_auto_detect_sun = QtWidgets.QPushButton("Auto-Detect Sun")
        self.btn_auto_detect_sun.setToolTip("Find the brightest point and set it as the sun source.")
        self.btn_interactive_sun = QtWidgets.QPushButton("Place Sun Interactively")
        self.btn_interactive_sun.setCheckable(True)
        self.btn_interactive_sun.setToolTip("Click and drag on the viewer to move the sun.")
        btn_layout.addWidget(self.btn_auto_detect_sun)
        btn_layout.addWidget(self.btn_interactive_sun)
        self.layout_sun_relight.addLayout(btn_layout)
        
        sun_options_layout = QtWidgets.QGridLayout()
        sun_options_layout.addWidget(QtWidgets.QLabel("Extraction Radius:"), 0, 0)
        self.slider_sun_radius = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_sun_radius.setRange(1, 100) # 0.001 to 0.1
        self.slider_sun_radius.setValue(30) # 0.03
        sun_options_layout.addWidget(self.slider_sun_radius, 0, 1)
        
        sun_options_layout.addWidget(QtWidgets.QLabel("Feather:"), 1, 0)
        self.slider_sun_feather = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_sun_feather.setRange(1, 100) # 0.001 to 0.1
        self.slider_sun_feather.setValue(15) # 0.015
        sun_options_layout.addWidget(self.slider_sun_feather, 1, 1)
        self.layout_sun_relight.addLayout(sun_options_layout)
        
        self.layout_hdri.addWidget(self.group_sun_relight)

        self.group_global = CollapsibleGroupBox("Global Exposure & Color")
        self.layout_global = QtWidgets.QVBoxLayout(self.group_global)

        self.chk_protect_sun = QtWidgets.QCheckBox("Protect Sun / Highlights")
        self.chk_protect_sun.setChecked(True)
        self.chk_protect_sun.setToolTip(
            "Excludes extreme highlights (>10 stops above mid-grey) from\n"
            "white balance and exposure analysis so the sun disc doesn't\n"
            "bias the calibration result.")
        self.layout_global.addWidget(self.chk_protect_sun)

        self.chk_apply_hdri_exposure = QtWidgets.QCheckBox("Bake Plate Exposure into HDRI")
        self.chk_apply_hdri_exposure.setChecked(False)
        self.chk_apply_hdri_exposure.setToolTip(
            "Off preserves the HDRI's physical intensity for lighting export.\n"
            "On is an artistic tone match and can create large non-physical EV offsets.")
        self.layout_global.addWidget(self.chk_apply_hdri_exposure)
        self.layout_global.addSpacing(15)
        
        self.layout_global.addWidget(QtWidgets.QLabel("Rotation Y (Yaw):"))
        self.slider_yaw = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_yaw.setRange(0, 3600)  # 0.0 to 360.0 degrees
        self.slider_yaw.setValue(0)
        self.lbl_yaw_value = QtWidgets.QLabel("0.0°")
        self.lbl_yaw_value.setFixedWidth(50)
        yaw_layout = QtWidgets.QHBoxLayout()
        yaw_layout.addWidget(self.slider_yaw)
        yaw_layout.addWidget(self.lbl_yaw_value)
        self.layout_global.addLayout(yaw_layout)
        
        self.layout_global.addSpacing(10)
        
        self.layout_global.addWidget(QtWidgets.QLabel("EV Offset:"))
        self.slider_ev = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_ev.setRange(-1000, 1000) 
        self.slider_ev.setValue(0)
        self.lbl_ev_value = QtWidgets.QLabel("0.0 EV")
        self.lbl_ev_value.setFixedWidth(50)
        ev_layout = QtWidgets.QHBoxLayout()
        ev_layout.addWidget(self.slider_ev)
        ev_layout.addWidget(self.lbl_ev_value)
        self.layout_global.addLayout(ev_layout)
        
        self.layout_global.addSpacing(10)
        
        self.layout_global.addWidget(QtWidgets.QLabel("Temperature:"))
        self.slider_temp = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_temp.setRange(-100, 100) 
        self.slider_temp.setValue(0)
        self.lbl_temp_value = QtWidgets.QLabel("0.0")
        self.lbl_temp_value.setFixedWidth(50)
        temp_layout = QtWidgets.QHBoxLayout()
        temp_layout.addWidget(self.slider_temp)
        temp_layout.addWidget(self.lbl_temp_value)
        self.layout_global.addLayout(temp_layout)
        
        self.layout_global.addWidget(QtWidgets.QLabel("Tint:"))
        self.slider_tint = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_tint.setRange(-100, 100) 
        self.slider_tint.setValue(0)
        self.lbl_tint_value = QtWidgets.QLabel("0.0")
        self.lbl_tint_value.setFixedWidth(50)
        tint_layout = QtWidgets.QHBoxLayout()
        tint_layout.addWidget(self.slider_tint)
        tint_layout.addWidget(self.lbl_tint_value)
        self.layout_global.addLayout(tint_layout)
        
        self.layout_hdri.addWidget(self.group_global)
        
        # --- Horizon / Hemisphere Separation ---
        self.layout_hdri.addSpacing(10)
        self.group_ground = CollapsibleGroupBox("Horizon / Hemisphere Separation")
        self.group_ground.setChecked(False)
        self.layout_ground = QtWidgets.QVBoxLayout(self.group_ground)
        self.layout_ground.setContentsMargins(10, 15, 10, 10)
        
        # Height
        h_row = QtWidgets.QHBoxLayout()
        h_row.addWidget(QtWidgets.QLabel("Horizon Height:"))
        self.slider_ground_height = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_ground_height.setRange(0, 100)
        self.slider_ground_height.setValue(50)
        self.lbl_ground_height = QtWidgets.QLabel("0.50")
        self.lbl_ground_height.setFixedWidth(50)
        h_row.addWidget(self.slider_ground_height)
        h_row.addWidget(self.lbl_ground_height)
        self.layout_ground.addLayout(h_row)
        
        # Feather
        f_row = QtWidgets.QHBoxLayout()
        f_row.addWidget(QtWidgets.QLabel("Feather:"))
        self.slider_ground_feather = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_ground_feather.setRange(0, 50)
        self.slider_ground_feather.setValue(10)
        self.lbl_ground_feather = QtWidgets.QLabel("0.10")
        self.lbl_ground_feather.setFixedWidth(50)
        f_row.addWidget(self.slider_ground_feather)
        f_row.addWidget(self.lbl_ground_feather)
        self.layout_ground.addLayout(f_row)
        
        # Sky Group
        self.sky_group = CollapsibleGroupBox("Sky Hemisphere")
        self.sky_layout = QtWidgets.QGridLayout(self.sky_group)
        
        self.slider_sky_ev = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_sky_ev.setRange(-1000, 1000)
        self.slider_sky_ev.setValue(0)
        self.lbl_sky_ev = QtWidgets.QLabel("0.00 EV")
        self.lbl_sky_ev.setFixedWidth(50)
        self.sky_layout.addWidget(QtWidgets.QLabel("EV:"), 0, 0)
        self.sky_layout.addWidget(self.slider_sky_ev, 0, 1)
        self.sky_layout.addWidget(self.lbl_sky_ev, 0, 2)
        
        self.slider_sky_temp = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_sky_temp.setRange(-100, 100)
        self.slider_sky_temp.setValue(0)
        self.lbl_sky_temp = QtWidgets.QLabel("0.00")
        self.lbl_sky_temp.setFixedWidth(50)
        self.sky_layout.addWidget(QtWidgets.QLabel("Temp:"), 1, 0)
        self.sky_layout.addWidget(self.slider_sky_temp, 1, 1)
        self.sky_layout.addWidget(self.lbl_sky_temp, 1, 2)
        
        self.slider_sky_tint = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_sky_tint.setRange(-100, 100)
        self.slider_sky_tint.setValue(0)
        self.lbl_sky_tint = QtWidgets.QLabel("0.00")
        self.lbl_sky_tint.setFixedWidth(50)
        self.sky_layout.addWidget(QtWidgets.QLabel("Tint:"), 2, 0)
        self.sky_layout.addWidget(self.slider_sky_tint, 2, 1)
        self.sky_layout.addWidget(self.lbl_sky_tint, 2, 2)
        
        self.slider_sky_desat = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_sky_desat.setRange(0, 100)
        self.slider_sky_desat.setValue(0)
        self.lbl_sky_desat = QtWidgets.QLabel("0 %")
        self.lbl_sky_desat.setFixedWidth(50)
        self.sky_layout.addWidget(QtWidgets.QLabel("Desat:"), 3, 0)
        self.sky_layout.addWidget(self.slider_sky_desat, 3, 1)
        self.sky_layout.addWidget(self.lbl_sky_desat, 3, 2)
        
        self.layout_ground.addWidget(self.sky_group)
        
        # Ground Group
        self.grnd_group = CollapsibleGroupBox("Ground Hemisphere")
        self.grnd_layout = QtWidgets.QGridLayout(self.grnd_group)
        
        self.slider_ground_ev = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_ground_ev.setRange(-1000, 1000)
        self.slider_ground_ev.setValue(0)
        self.lbl_ground_ev = QtWidgets.QLabel("0.00 EV")
        self.lbl_ground_ev.setFixedWidth(50)
        self.grnd_layout.addWidget(QtWidgets.QLabel("EV:"), 0, 0)
        self.grnd_layout.addWidget(self.slider_ground_ev, 0, 1)
        self.grnd_layout.addWidget(self.lbl_ground_ev, 0, 2)
        
        self.slider_ground_temp = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_ground_temp.setRange(-100, 100)
        self.slider_ground_temp.setValue(0)
        self.lbl_ground_temp = QtWidgets.QLabel("0.00")
        self.lbl_ground_temp.setFixedWidth(50)
        self.grnd_layout.addWidget(QtWidgets.QLabel("Temp:"), 1, 0)
        self.grnd_layout.addWidget(self.slider_ground_temp, 1, 1)
        self.grnd_layout.addWidget(self.lbl_ground_temp, 1, 2)
        
        self.slider_ground_tint = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_ground_tint.setRange(-100, 100)
        self.slider_ground_tint.setValue(0)
        self.lbl_ground_tint = QtWidgets.QLabel("0.00")
        self.lbl_ground_tint.setFixedWidth(50)
        self.grnd_layout.addWidget(QtWidgets.QLabel("Tint:"), 2, 0)
        self.grnd_layout.addWidget(self.slider_ground_tint, 2, 1)
        self.grnd_layout.addWidget(self.lbl_ground_tint, 2, 2)
        
        self.slider_ground_desat = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_ground_desat.setRange(0, 100)
        self.slider_ground_desat.setValue(0)
        self.lbl_ground_desat = QtWidgets.QLabel("0 %")
        self.lbl_ground_desat.setFixedWidth(50)
        self.grnd_layout.addWidget(QtWidgets.QLabel("Desat:"), 3, 0)
        self.grnd_layout.addWidget(self.slider_ground_desat, 3, 1)
        self.grnd_layout.addWidget(self.lbl_ground_desat, 3, 2)
        
        self.layout_ground.addWidget(self.grnd_group)
        self.layout_hdri.addWidget(self.group_ground)
        
        # --- Highlight Compression (Soft-Clip) ---
        self.layout_hdri.addSpacing(10)
        self.group_softclip = CollapsibleGroupBox("Highlight Compression (Soft-Clip)")
        self.group_softclip.setChecked(False)
        self.layout_softclip = QtWidgets.QGridLayout(self.group_softclip)
        self.layout_softclip.setContentsMargins(10, 15, 10, 10)
        
        self.slider_softclip_thresh = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_softclip_thresh.setRange(10, 150) # 1.0 to 15.0 EV
        self.slider_softclip_thresh.setValue(50)
        self.lbl_softclip_thresh = QtWidgets.QLabel("5.0 EV")
        self.lbl_softclip_thresh.setFixedWidth(50)
        self.slider_softclip_thresh.setToolTip("EV stops above mid-grey where the compression begins.")
        self.layout_softclip.addWidget(QtWidgets.QLabel("Threshold:"), 0, 0)
        self.layout_softclip.addWidget(self.slider_softclip_thresh, 0, 1)
        self.layout_softclip.addWidget(self.lbl_softclip_thresh, 0, 2)
        
        self.slider_softclip_rolloff = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_softclip_rolloff.setRange(10, 100) # 1.0 to 10.0 EV headroom
        self.slider_softclip_rolloff.setValue(20)
        self.lbl_softclip_rolloff = QtWidgets.QLabel("2.0 EV")
        self.lbl_softclip_rolloff.setFixedWidth(50)
        self.slider_softclip_rolloff.setToolTip("Maximum EV headroom available above the threshold.")
        self.layout_softclip.addWidget(QtWidgets.QLabel("Rolloff limit:"), 1, 0)
        self.layout_softclip.addWidget(self.slider_softclip_rolloff, 1, 1)
        self.layout_softclip.addWidget(self.lbl_softclip_rolloff, 1, 2)
        
        self.layout_hdri.addWidget(self.group_softclip)
        
        # --- Plate Adjustments (independent of HDRI calibration) ---
        self.layout_hdri.addSpacing(10)
        self.group_plate = CollapsibleGroupBox("Plate Adjustments (Independent)")
        self.group_plate.setChecked(False) # Collapsed by default
        self.layout_plate = QtWidgets.QVBoxLayout(self.group_plate)
        
        self.layout_plate.addWidget(QtWidgets.QLabel("Plate EV Offset:"))
        self.slider_plate_ev = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_plate_ev.setRange(-500, 500)
        self.slider_plate_ev.setValue(0)
        self.slider_plate_ev.setToolTip(
            "Exposure offset for the plate image only (does NOT affect HDRI calibration).\n"
            "Use this to visually match the plate brightness for compositing preview.")
        self.lbl_plate_ev_value = QtWidgets.QLabel("0.00 EV")
        self.lbl_plate_ev_value.setFixedWidth(50)
        plate_ev_layout = QtWidgets.QHBoxLayout()
        plate_ev_layout.addWidget(self.slider_plate_ev)
        plate_ev_layout.addWidget(self.lbl_plate_ev_value)
        self.layout_plate.addLayout(plate_ev_layout)
        
        self.layout_plate.addWidget(QtWidgets.QLabel("Saturation:"))
        self.slider_plate_sat = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_plate_sat.setRange(0, 200)
        self.slider_plate_sat.setValue(100)  # 1.0 = unchanged
        self.slider_plate_sat.setToolTip(
            "Saturation multiplier for the plate image only.\n"
            "0 = monochrome, 1.0 = unchanged, 2.0 = double saturation.\n"
            "Does NOT affect HDRI calibration or CG light matching.")
        self.lbl_plate_sat_value = QtWidgets.QLabel("1.00")
        self.lbl_plate_sat_value.setFixedWidth(50)
        plate_sat_layout = QtWidgets.QHBoxLayout()
        plate_sat_layout.addWidget(self.slider_plate_sat)
        plate_sat_layout.addWidget(self.lbl_plate_sat_value)
        self.layout_plate.addLayout(plate_sat_layout)
        
        self.layout_plate.addWidget(QtWidgets.QLabel("Temperature:"))
        self.slider_plate_temp = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_plate_temp.setRange(-100, 100) 
        self.slider_plate_temp.setValue(0)
        self.slider_plate_temp.setToolTip("Blue (-1.0) to Yellow (1.0) for the plate image only.")
        self.lbl_plate_temp_value = QtWidgets.QLabel("0.00")
        self.lbl_plate_temp_value.setFixedWidth(50)
        plate_temp_layout = QtWidgets.QHBoxLayout()
        plate_temp_layout.addWidget(self.slider_plate_temp)
        plate_temp_layout.addWidget(self.lbl_plate_temp_value)
        self.layout_plate.addLayout(plate_temp_layout)
        
        self.layout_plate.addWidget(QtWidgets.QLabel("Tint:"))
        self.slider_plate_tint = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_plate_tint.setRange(-100, 100) 
        self.slider_plate_tint.setValue(0)
        self.slider_plate_tint.setToolTip("Green (-1.0) to Magenta (1.0) for the plate image only.")
        self.lbl_plate_tint_value = QtWidgets.QLabel("0.00")
        self.lbl_plate_tint_value.setFixedWidth(50)
        plate_tint_layout = QtWidgets.QHBoxLayout()
        plate_tint_layout.addWidget(self.slider_plate_tint)
        plate_tint_layout.addWidget(self.lbl_plate_tint_value)
        self.layout_plate.addLayout(plate_tint_layout)
        
        self.layout_hdri.addWidget(self.group_plate)
        self.layout_hdri.addStretch()
        
        # TAB 2: CG Light Match
        self.tab_cg_content = QtWidgets.QWidget()
        self.tab_cg_content.setObjectName("SidePanel")
        self.layout_cg = QtWidgets.QVBoxLayout(self.tab_cg_content)
        
        self.btn_load_cg = QtWidgets.QPushButton("Load CG Multi-Pass EXR...")
        self.btn_clear_cg = QtWidgets.QPushButton("Clear")
        self.btn_clear_cg.setFixedWidth(60)
        self.btn_clear_cg.setToolTip("Clear loaded CG EXR and Light AOVs")
        
        load_cg_layout = QtWidgets.QHBoxLayout()
        load_cg_layout.addWidget(self.btn_load_cg)
        load_cg_layout.addWidget(self.btn_clear_cg)
        
        self.lbl_cg_path = QtWidgets.QLabel("No EXR Loaded")
        self.lbl_cg_path.setFixedWidth(50)
        
        # Renderer preset dropdown
        renderer_layout = QtWidgets.QHBoxLayout()
        renderer_layout.addWidget(QtWidgets.QLabel("Renderer:"))
        self.combo_renderer_preset = QtWidgets.QComboBox()
        self.combo_renderer_preset.addItems([
            "Arnold",
            "V-Ray",
            "Redshift",
            "RenderMan",
            "Karma / Solaris",
            "Custom"
        ])
        self.combo_renderer_preset.setToolTip(
            "Auto-populates AOV prefix patterns for common renderers.\n"
            "Select 'Custom' to manually enter your own prefixes.")
        renderer_layout.addWidget(self.combo_renderer_preset, 1)
        self.layout_cg.addLayout(renderer_layout)
        
        prefix_layout = QtWidgets.QHBoxLayout()
        prefix_layout.addWidget(QtWidgets.QLabel("AOV Prefixes:"))
        self.line_edit_prefix = QtWidgets.QLineEdit("C_Light_, light_, key, fill, rim, bounce, warm, cool")
        self.line_edit_prefix.setToolTip("Comma-separated list of prefixes to filter light AOVs. Leave blank to load all RGB passes.")
        prefix_layout.addWidget(self.line_edit_prefix)
        
        self.layout_cg.addLayout(prefix_layout)
        self.layout_cg.addLayout(load_cg_layout)
        self.layout_cg.addWidget(self.lbl_cg_path)
        
        # --- CG Comp Adjustments ---
        self.group_cg_comp = CollapsibleGroupBox("Composite Options")
        self.group_cg_comp.setChecked(True)
        self.layout_cg_comp = QtWidgets.QVBoxLayout(self.group_cg_comp)

        self.layout_cg_comp.addWidget(QtWidgets.QLabel("Ground Shadow Intensity:"))
        self.slider_cg_shadow = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_cg_shadow.setRange(0, 200) # 0.0 to 2.0
        self.slider_cg_shadow.setValue(100) # 1.0
        self.slider_cg_shadow.setToolTip(
            "Multiplier for the shadow_catch or shadow_matte AOV.")
        self.lbl_cg_shadow = QtWidgets.QLabel("1.00")
        self.lbl_cg_shadow.setFixedWidth(50)
        shadow_layout = QtWidgets.QHBoxLayout()
        shadow_layout.addWidget(self.slider_cg_shadow)
        shadow_layout.addWidget(self.lbl_cg_shadow)
        self.layout_cg_comp.addLayout(shadow_layout)

        self.layout_cg_comp.addWidget(QtWidgets.QLabel("Reflection Intensity:"))
        self.slider_cg_refl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_cg_refl.setRange(0, 200) # 0.0 to 2.0
        self.slider_cg_refl.setValue(100) # 1.0
        self.slider_cg_refl.setToolTip("Multiplier for the reflection_catch AOV.")
        self.lbl_cg_refl = QtWidgets.QLabel("1.00")
        self.lbl_cg_refl.setFixedWidth(40)
        refl_layout = QtWidgets.QHBoxLayout()
        refl_layout.addWidget(self.slider_cg_refl)
        refl_layout.addWidget(self.lbl_cg_refl)
        self.layout_cg_comp.addLayout(refl_layout)

        self.layout_cg_comp.addWidget(QtWidgets.QLabel("CG Opacity Mix:"))
        self.slider_cg_blend = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_cg_blend.setRange(0, 100) # 0.0 to 1.0
        self.slider_cg_blend.setValue(100) # 1.0
        self.slider_cg_blend.setToolTip("Global mix / opacity for the entire CG render over the plate.")
        self.lbl_cg_blend = QtWidgets.QLabel("1.00")
        self.lbl_cg_blend.setFixedWidth(40)
        blend_layout = QtWidgets.QHBoxLayout()
        blend_layout.addWidget(self.slider_cg_blend)
        blend_layout.addWidget(self.lbl_cg_blend)
        self.layout_cg_comp.addLayout(blend_layout)

        self.lbl_wipe_hint = QtWidgets.QLabel("<i>Hint: Press <b>W</b> in the viewer to toggle an interactive A/B wipe tool.</i>")
        self.lbl_wipe_hint.setFixedWidth(50)
        self.lbl_wipe_hint.setStyleSheet("color: #888888; margin-top: 5px;")
        self.lbl_wipe_hint.setWordWrap(True)
        self.layout_cg_comp.addWidget(self.lbl_wipe_hint)

        self.layout_cg.addWidget(self.group_cg_comp)
        
        self.cg_scroll = QtWidgets.QScrollArea()
        self.cg_scroll.setWidgetResizable(True)
        self.cg_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.cg_content = QtWidgets.QWidget()
        self.cg_content.setObjectName("SidePanel")
        self.cg_scroll_layout = QtWidgets.QVBoxLayout(self.cg_content)
        self.cg_scroll.setWidget(self.cg_content)
        self.layout_cg.addWidget(self.cg_scroll)
        
        self.btn_export_cg = QtWidgets.QPushButton("Export CG Light Multipliers to Houdini...")
        self.btn_export_cg.setObjectName("btn_export_cg")
        self.layout_cg.addWidget(self.btn_export_cg)
        
        self.btn_export_cg_blender = QtWidgets.QPushButton("Export CG Light Multipliers to Blender...")
        self.btn_export_cg_blender.setToolTip("Generate a Blender Python script that applies light match EV/color to scene lights.")
        self.layout_cg.addWidget(self.btn_export_cg_blender)
        
        self.btn_detect_sun = QtWidgets.QPushButton("Extract Sun Vector to Clipboard")
        
        self.right_tabs.addTab(self.tab_hdri, "HDRI Calibration")
        self.right_tabs.addTab(self.tab_cg_content, "CG Lookdev Match")
        
        # TAB 3: Export
        self.tab_export_content = QtWidgets.QWidget()
        self.tab_export_content.setObjectName("SidePanel")
        self.layout_export = QtWidgets.QVBoxLayout(self.tab_export_content)
        
        # Output Nuke group
        self.group_export_nuke = QtWidgets.QGroupBox("Nuke Export")
        nuke_export_layout = QtWidgets.QVBoxLayout(self.group_export_nuke)
        nuke_export_layout.addWidget(self.btn_export)
        nuke_export_layout.addWidget(self.btn_export_sequence)
        nuke_export_layout.addWidget(self.btn_export_nuke)
        
        self.btn_extract_backplate = QtWidgets.QPushButton("Extract HDRI Backplate to Nuke...")
        self.btn_extract_backplate.setToolTip("Generate Nuke nodes to extract a perspective-corrected rectilinear backplate from the HDRI.")
        nuke_export_layout.addWidget(self.btn_extract_backplate)
        
        nuke_export_layout.addWidget(self.btn_extract_lights)
        self.layout_export.addWidget(self.group_export_nuke)
        
        # Output Houdini group
        self.group_export_hou = QtWidgets.QGroupBox("Houdini / Solaris Export")
        hou_export_layout = QtWidgets.QVBoxLayout(self.group_export_hou)
        hou_export_layout.addWidget(self.btn_export_camera)
        
        self.btn_publish_solaris = QtWidgets.QPushButton("Publish to Solaris")
        self.btn_publish_solaris.setToolTip("Exports HDRI, Plate, Mask textures, and JSON manifest for the Houdini Shelf Tool.")
        self.btn_publish_solaris.setStyleSheet("font-weight: bold; padding: 6px; background-color: #d86c00; color: #fff;")
        hou_export_layout.addWidget(self.btn_publish_solaris)
        
        self.layout_export.addWidget(self.group_export_hou)
        
        # Output Blender group
        self.group_export_blender = QtWidgets.QGroupBox("Blender Export")
        blender_export_layout = QtWidgets.QVBoxLayout(self.group_export_blender)
        
        self.btn_export_blender_world = QtWidgets.QPushButton("Export Blender World Setup...")
        self.btn_export_blender_world.setToolTip(
            "Generate a Blender Python script that sets up the World environment\n"
            "with the calibrated HDRI, rotation, exposure, and white balance.")
        blender_export_layout.addWidget(self.btn_export_blender_world)
        
        self.btn_export_blender_lights = QtWidgets.QPushButton("Export Mask Lights to Blender...")
        self.btn_export_blender_lights.setToolTip(
            "Generate a Blender Python script that creates Area Lights\n"
            "from your HDRI mask regions with correct position and color.")
        blender_export_layout.addWidget(self.btn_export_blender_lights)
        
        self.layout_export.addWidget(self.group_export_blender)
        
        # QC Report
        self.group_export_qc = QtWidgets.QGroupBox("HDRI QC Report")
        qc_layout = QtWidgets.QVBoxLayout(self.group_export_qc)
        
        self.btn_qc_report = QtWidgets.QPushButton("Generate QC Report")
        self.btn_qc_report.setToolTip(
            "Analyze the loaded HDRI and generate a comprehensive report:\n"
            "Dynamic range, sun position, CCT (Kelvin), coverage stats.")
        qc_layout.addWidget(self.btn_qc_report)
        
        self.btn_copy_qc = QtWidgets.QPushButton("Copy Report to Clipboard")
        self.btn_copy_qc.setToolTip("Copy the QC report as formatted text to the clipboard.")
        self.btn_copy_qc.setEnabled(False)
        qc_layout.addWidget(self.btn_copy_qc)
        
        self.btn_mobile_report = QtWidgets.QPushButton("Generate On-Set Mobile Report (HTML)")
        self.btn_mobile_report.setToolTip("Generate a self-contained HTML QC report for mobile viewing.")
        qc_layout.addWidget(self.btn_mobile_report)
        
        self.txt_qc_report = QtWidgets.QTextEdit()
        self.txt_qc_report.setReadOnly(True)
        self.txt_qc_report.setMaximumHeight(300)
        self.txt_qc_report.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;"
            "background-color: #1a1a2e; color: #e0e0e0; border: 1px solid #333;")
        self.txt_qc_report.setPlaceholderText("Load an HDRI and click 'Generate QC Report'...")
        qc_layout.addWidget(self.txt_qc_report)
        
        self.layout_export.addWidget(self.group_export_qc)
        
        # Utilities
        self.group_export_utils = QtWidgets.QGroupBox("Utilities")
        util_export_layout = QtWidgets.QVBoxLayout(self.group_export_utils)
        util_export_layout.addWidget(self.btn_detect_sun)
        self.layout_export.addWidget(self.group_export_utils)
        
        self.layout_export.addStretch()
        
        self.right_tabs.addTab(self.tab_export_content, "Export")
        
        self.right_layout.addWidget(self.right_tabs)
        self.main_splitter.addWidget(self.right_panel)
        
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1) # Make center panel stretchy
        self.main_splitter.setStretchFactor(2, 0)
        
        self.main_splitter.setSizes([320, 1200, 380])
        
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setCollapsible(2, False)
        
        self.pipeline.state.plate_adjustments_enabled = self.group_plate.isChecked()

    def connect_signals(self):
        self.btn_open_3d.clicked.connect(self.open_3d_viewer)
        self.btn_new_project.clicked.connect(self.new_project)
        self.btn_load_hdri.clicked.connect(self.load_hdri)
        self.btn_clear_hdri.clicked.connect(self.clear_hdri)
        self.btn_load_plate.clicked.connect(self.load_plate)
        self.btn_clear_plate.clicked.connect(self.clear_plate)
        self.btn_save_project.clicked.connect(self.save_project)
        self.btn_load_project.clicked.connect(self.load_project)
        self.btn_load_macbeth.clicked.connect(self.load_macbeth)
        self.btn_clear_macbeth.clicked.connect(self.clear_macbeth)
        self.btn_auto_macbeth.clicked.connect(self.auto_detect_macbeth)
        self.btn_export_nuke.clicked.connect(self.export_nuke_nodes)
        self.btn_extract_backplate.clicked.connect(self.export_backplate_nodes)
        self.btn_extract_lights.clicked.connect(self.on_extract_lights_clicked)
        self.btn_export_camera.clicked.connect(self.on_export_camera_clicked)
        self.btn_publish_solaris.clicked.connect(self.export_solaris_package)
        self.btn_detect_sun.clicked.connect(self.extract_sun)
        
        # Blender Export Signals
        self.btn_export_blender_world.clicked.connect(self.export_blender_world)
        self.btn_export_blender_lights.clicked.connect(self.export_blender_lights)
        
        # QC Report Signals
        self.btn_qc_report.clicked.connect(self.generate_qc_report)
        self.btn_copy_qc.clicked.connect(self.copy_qc_report)
        self.btn_mobile_report.clicked.connect(self.generate_mobile_report)
        
        # CG Signals
        self.btn_load_cg.clicked.connect(self.load_cg)
        self.btn_clear_cg.clicked.connect(self.clear_cg)
        self.btn_export_cg.clicked.connect(self.export_cg_json)
        self.btn_export_cg_blender.clicked.connect(self.export_cg_blender)
        self.slider_cg_shadow.valueChanged.connect(self.on_cg_shadow_slider_changed)
        self.slider_cg_refl.valueChanged.connect(self.on_cg_refl_slider_changed)
        self.slider_cg_blend.valueChanged.connect(self.on_cg_blend_slider_changed)
        
        self.slider_cg_shadow.sliderReleased.connect(self.on_slider_released)
        self.slider_cg_refl.sliderReleased.connect(self.on_slider_released)
        self.slider_cg_blend.sliderReleased.connect(self.on_slider_released)
        
        # Renderer Preset Signal
        self.combo_renderer_preset.currentTextChanged.connect(self.on_renderer_preset_changed)
        self.right_tabs.currentChanged.connect(self.on_tab_changed)
        
        self.combo_theme.currentTextChanged.connect(self.on_theme_changed)
        
        self.btn_load_chrome.clicked.connect(self.load_chrome)
        self.btn_clear_chrome.clicked.connect(self.clear_chrome)
        
        self.btn_load_grey.clicked.connect(self.load_grey)
        self.btn_clear_grey.clicked.connect(self.clear_grey)
        
        self.btn_crop_macbeth.clicked.connect(lambda: self.start_interactive_crop("macbeth"))
        self.btn_crop_chrome.clicked.connect(lambda: self.start_interactive_crop("chrome"))
        self.btn_crop_grey.clicked.connect(lambda: self.start_interactive_crop("grey"))
        
        self.btn_auto_calib.clicked.connect(self.run_calibration)
        self.btn_pick_wb.toggled.connect(self.on_pick_wb_toggled)
        self.viewer_left.pixelPicked.connect(self.on_pixel_picked)
        self.btn_reset_calib.clicked.connect(self.reset_hdri_calibration)
        self.combo_view_mode.currentTextChanged.connect(self.update_viewer)
        self.combo_display_transform.currentTextChanged.connect(self.update_viewer)
        self.combo_reformat.currentTextChanged.connect(self.on_reformat_changed)
        self.btn_export.clicked.connect(self.export_image)
        self.btn_export_sequence.clicked.connect(self.export_sequence)
        self.btn_reset_view.clicked.connect(self.on_reset_view_clicked)
        self.slider_viewport_ev.valueChanged.connect(self.on_viewport_ev_changed)
        self.btn_reset_viewport_ev.clicked.connect(self.on_reset_viewport_ev_clicked)
        
        # Timeline Signals
        self.slider_timeline.valueChanged.connect(self.on_timeline_changed)
        self.btn_play_pause.toggled.connect(self.on_play_toggled)
        self.btn_first_frame.clicked.connect(self.on_first_frame)
        self.btn_prev_frame.clicked.connect(self.on_prev_frame)
        self.btn_next_frame.clicked.connect(self.on_next_frame)
        self.btn_last_frame.clicked.connect(self.on_last_frame)
        self.combo_fps.currentTextChanged.connect(self.on_fps_changed)
        self.btn_reset_cache.clicked.connect(self.on_reset_cache)

        self.lbl_ref_macbeth.clicked_uv.connect(lambda u,v: self.on_ref_clicked("macbeth", u, v))
        self.lbl_ref_chrome.clicked_uv.connect(lambda u,v: self.on_ref_clicked("chrome", u, v))
        self.lbl_ref_grey.clicked_uv.connect(lambda u,v: self.on_ref_clicked("grey", u, v))
        
        self.chk_show_refs.stateChanged.connect(self.on_show_refs_changed)
        self.combo_sky_mode.currentIndexChanged.connect(self.on_sky_mode_changed)
        self.chk_ai_awb.stateChanged.connect(self.on_sky_mode_changed)
        self.chk_enable_mask.stateChanged.connect(self.on_enable_mask_changed)
        self.chk_apply_hdri_exposure.stateChanged.connect(self.on_hdri_exposure_policy_changed)
        self.chk_protect_sun.stateChanged.connect(self.on_protect_sun_changed)
        self.group_ground.toggled.connect(self.on_ground_toggled)
        
        self.slider_yaw.valueChanged.connect(self.on_yaw_slider_changed)
        self.slider_ev.valueChanged.connect(self.on_ev_slider_changed)
        self.slider_temp.valueChanged.connect(self.on_color_slider_changed)
        self.slider_tint.valueChanged.connect(self.on_color_slider_changed)
        
        self.slider_yaw.sliderReleased.connect(self.on_slider_released)
        self.slider_ev.sliderReleased.connect(self.on_slider_released)
        self.slider_temp.sliderReleased.connect(self.on_slider_released)
        self.slider_tint.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_feather.sliderReleased.connect(self.on_slider_released)
        
        # Sun Relight Signals
        self.chk_enable_sun_relight.stateChanged.connect(self.on_sun_relight_toggled)
        self.btn_auto_detect_sun.clicked.connect(self.on_auto_detect_sun)
        self.btn_interactive_sun.toggled.connect(self.on_interactive_sun_toggled)
        self.slider_sun_radius.sliderReleased.connect(self.on_sun_relight_options_changed)
        self.slider_sun_feather.sliderReleased.connect(self.on_sun_relight_options_changed)
        self.viewer_left.sunMoved.connect(self.on_sun_moved)
        self.viewer_left.transformDragStarted.connect(self.on_transform_drag_started)
        self.viewer_left.transformDragged.connect(self.on_transform_dragged)
        self.viewer_right.transformDragStarted.connect(self.on_transform_drag_started)
        self.viewer_right.transformDragged.connect(self.on_transform_dragged)
        self.viewer_left.transformDragStarted.connect(self.on_transform_drag_started)
        self.viewer_left.transformDragged.connect(self.on_transform_dragged)
        self.viewer_right.transformDragStarted.connect(self.on_transform_drag_started)
        self.viewer_right.transformDragged.connect(self.on_transform_dragged)
        
        self.btn_run_inpaint.clicked.connect(self.on_run_inpaint_clicked)
        self.combo_inpaint_backend.currentTextChanged.connect(self.on_inpaint_backend_changed)
        
        self.btn_add_mask.clicked.connect(self.add_mask)
        self.btn_remove_mask.clicked.connect(self.remove_mask)
        self.btn_deselect_mask.clicked.connect(self.deselect_mask)
        self.list_masks.currentRowChanged.connect(self.on_mask_selected)
        self.list_masks.itemChanged.connect(self.on_mask_name_changed)
        self.list_masks.model().rowsMoved.connect(self.on_mask_reordered)
        
        self.combo_mask_mode.currentTextChanged.connect(self.on_mask_mode_changed)
        self.combo_light_type.currentTextChanged.connect(self.on_mask_light_type_changed)
        self.btn_mask_color.clicked.connect(self.on_mask_color_clicked)
        self.combo_chroma.currentTextChanged.connect(self.on_mask_chroma_changed)
        self.slider_chroma_tol.valueChanged.connect(self.on_mask_chroma_changed)
        self.slider_chroma_tol.sliderReleased.connect(self.on_slider_released)
        
        self.combo_mask_shape.currentTextChanged.connect(self.on_mask_shape_changed)
        self.combo_mask_target.currentTextChanged.connect(self.on_mask_target_changed)
        self.slider_mask_feather.valueChanged.connect(self.on_mask_feather_changed)
        
        self.slider_mask_ev.valueChanged.connect(self.on_mask_ev_slider_changed)
        self.slider_mask_temp.valueChanged.connect(self.on_mask_color_slider_changed)
        self.slider_mask_tint.valueChanged.connect(self.on_mask_color_slider_changed)
        self.combo_mask_blend_mode.currentTextChanged.connect(self.on_mask_blend_mode_changed)
        self.slider_mask_blend.valueChanged.connect(self.on_mask_blend_changed)
        self.slider_mask_blur.valueChanged.connect(self.on_mask_blur_changed)
        self.slider_mask_brush.valueChanged.connect(self.on_mask_brush_changed)
        
        self.slider_mask_tx.valueChanged.connect(lambda v: self.spin_mask_tx.setValue(v))
        self.spin_mask_tx.valueChanged.connect(lambda v: self.slider_mask_tx.setValue(int(v)))
        self.spin_mask_tx.valueChanged.connect(self.on_mask_transform_changed)
        
        self.slider_mask_ty.valueChanged.connect(lambda v: self.spin_mask_ty.setValue(v))
        self.spin_mask_ty.valueChanged.connect(lambda v: self.slider_mask_ty.setValue(int(v)))
        self.spin_mask_ty.valueChanged.connect(self.on_mask_transform_changed)
        
        self.slider_mask_scale.valueChanged.connect(lambda v: self.spin_mask_scale.setValue(v / 100.0))
        self.spin_mask_scale.valueChanged.connect(lambda v: self.slider_mask_scale.setValue(int(v * 100)))
        self.spin_mask_scale.valueChanged.connect(self.on_mask_transform_changed)
        
        self.slider_mask_rotate.valueChanged.connect(lambda v: self.spin_mask_rotate.setValue(v))
        self.spin_mask_rotate.valueChanged.connect(lambda v: self.slider_mask_rotate.setValue(int(v)))
        self.spin_mask_rotate.valueChanged.connect(self.on_mask_transform_changed)
        
        self.slider_mask_tx.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_ty.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_scale.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_rotate.sliderReleased.connect(self.on_slider_released)
        
        self.chk_stencil.stateChanged.connect(self.on_mask_stencil_changed)
        self.combo_stencil_mode.currentTextChanged.connect(self.on_mask_stencil_changed)
        self.chk_stencil_invert.stateChanged.connect(self.on_mask_stencil_changed)
        self.slider_stencil_thresh.valueChanged.connect(self.on_mask_stencil_changed)
        self.slider_stencil_thresh.sliderReleased.connect(self.on_slider_released)
        
        self.slider_mask_ev.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_temp.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_tint.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_blend.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_blur.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_brush.sliderReleased.connect(self.on_slider_released)
        self.slider_mask_brush.valueChanged.connect(self.on_mask_brush_changed)
        
        self.group_masks.toggled.connect(self.on_multi_mask_toggled)
        
        # Horizon / Hemisphere Signals
        self.slider_ground_height.valueChanged.connect(self.on_horizon_slider_changed)
        self.slider_ground_feather.valueChanged.connect(self.on_horizon_slider_changed)
        
        self.slider_sky_ev.valueChanged.connect(self.on_horizon_slider_changed)
        self.slider_sky_temp.valueChanged.connect(self.on_horizon_slider_changed)
        self.slider_sky_tint.valueChanged.connect(self.on_horizon_slider_changed)
        self.slider_sky_desat.valueChanged.connect(self.on_horizon_slider_changed)
        
        self.slider_ground_ev.valueChanged.connect(self.on_horizon_slider_changed)
        self.slider_ground_temp.valueChanged.connect(self.on_horizon_slider_changed)
        self.slider_ground_tint.valueChanged.connect(self.on_horizon_slider_changed)
        self.slider_ground_desat.valueChanged.connect(self.on_horizon_slider_changed)
        
        self.slider_ground_height.sliderReleased.connect(self.on_slider_released)
        self.slider_ground_feather.sliderReleased.connect(self.on_slider_released)
        
        self.slider_sky_ev.sliderReleased.connect(self.on_slider_released)
        self.slider_sky_temp.sliderReleased.connect(self.on_slider_released)
        self.slider_sky_tint.sliderReleased.connect(self.on_slider_released)
        self.slider_sky_desat.sliderReleased.connect(self.on_slider_released)
        
        self.slider_ground_ev.sliderReleased.connect(self.on_slider_released)
        self.slider_ground_temp.sliderReleased.connect(self.on_slider_released)
        self.slider_ground_tint.sliderReleased.connect(self.on_slider_released)
        self.slider_ground_desat.sliderReleased.connect(self.on_slider_released)
        
        # Soft-Clip Signals
        self.group_softclip.toggled.connect(self.on_softclip_toggled)
        self.slider_softclip_thresh.valueChanged.connect(self.on_softclip_slider_changed)
        self.slider_softclip_rolloff.valueChanged.connect(self.on_softclip_slider_changed)
        self.slider_softclip_thresh.sliderReleased.connect(self.on_slider_released)
        self.slider_softclip_rolloff.sliderReleased.connect(self.on_slider_released)
        
        # Plate Adjustment Signals
        self.group_plate.toggled.connect(self.on_plate_group_toggled)
        self.slider_plate_ev.valueChanged.connect(self.on_plate_ev_slider_changed)
        self.slider_plate_sat.valueChanged.connect(self.on_plate_sat_slider_changed)
        self.slider_plate_temp.valueChanged.connect(self.on_plate_temp_slider_changed)
        self.slider_plate_tint.valueChanged.connect(self.on_plate_tint_slider_changed)
        self.slider_plate_ev.sliderReleased.connect(self.on_plate_slider_released)
        self.slider_plate_sat.sliderReleased.connect(self.on_plate_slider_released)
        self.slider_plate_temp.sliderReleased.connect(self.on_plate_slider_released)
        self.slider_plate_tint.sliderReleased.connect(self.on_plate_slider_released)
        
        # OCIO and Colorspace Signals
        self.btn_load_ocio.clicked.connect(self.load_ocio_config)
        self.btn_ocio_nuke.clicked.connect(self.load_ocio_from_nuke)
        self.combo_cs_input.currentTextChanged.connect(self.reload_all_images)
        self.combo_cs_output.currentTextChanged.connect(self.reload_all_images)
        
        # Viewer signals
        self.viewer_left.maskDrawn.connect(self.on_mask_drawn)
        self.viewer_right.maskDrawn.connect(self.on_mask_drawn)
        
        # Apply QStyledItemDelegate to all QComboBoxes to fix item height bug on Windows PySide6
        for cb in self.findChildren(QtWidgets.QComboBox):
            cb.setItemDelegate(QtWidgets.QStyledItemDelegate(cb))
    def open_3d_viewer(self):
        QtWidgets.QMessageBox.information(
            self, 
            "Coming Soon", 
            "The 3D Scene Viewer is currently disabled and undergoing improvements. We will bring it back in a future update!"
        )
        return

    def on_extract_lights_clicked(self):
        self.extract_sun()

        if self.pipeline.state.hdri_array is None or not self.pipeline.state.hdri_path:
            QtWidgets.QMessageBox.warning(self, "No HDRI", "Please load an HDRI first.")
            return
            
        export_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Export Directory for Extracted Lights")
        if not export_dir:
            return
            
        # Optional: Ask user for number of lights and mask radius
        num_lights, ok = QtWidgets.QInputDialog.getInt(self, "Extract Lights", "Number of Lights to Extract:", 1, 1, 10)
        if not ok: return
        
        radius_px, ok = QtWidgets.QInputDialog.getInt(self, "Extract Lights", "Mask Radius (pixels):", 100, 10, 1000)
        if not ok: return
        
        try:
            from hdri_match.io.exporter import export_extracted_lights
            nk_path, solaris_path = export_extracted_lights(
                self.pipeline.state.hdri_array,
                export_dir,
                self.pipeline.state.hdri_path,
                num_lights=num_lights,
                mask_radius_px=radius_px
            )
            
            if nk_path and solaris_path:
                QtWidgets.QMessageBox.information(
                    self, 
                    "Extraction Complete", 
                    f"Successfully extracted {num_lights} light(s)!\n\n"
                    f"Nuke Patch Script: {os.path.basename(nk_path)}\n"
                    f"Solaris Light Script: {os.path.basename(solaris_path)}"
                )
            else:
                QtWidgets.QMessageBox.warning(self, "Extraction Failed", "Could not extract lights.")
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to extract lights:\n{e}")
        
    def on_reformat_changed(self, mode_str):
        target_shape = None
        if mode_str == "Native":
            target_shape = "Native"
        elif mode_str == "Match Plate" and self.pipeline.state.plate_array is not None:
            target_shape = self.pipeline.state.plate_array.shape[:2]
        elif mode_str not in ["Native", "Match Plate", "Proxy (Fast)"]:
            parts = mode_str.split("x")
            if len(parts) == 2:
                target_shape = (int(parts[1]), int(parts[0]))
                
        self.pipeline.set_proxy_resolution(target_shape)
        # Force a full rebuild using the newly sized proxies
        self._trigger_update(hdri=True, plate=True, cg=True)

    def on_tab_changed(self, index):
        cg_ready = (self.pipeline.state.cg_reconstructed is not None or
                    self.pipeline.state.cg_reconstructed_proxy is not None)
        if index == 1:
            if cg_ready:
                self.combo_view_mode.setCurrentText("CG Over Plate")
            self.viewer_left.set_draw_mode(False)
            self.viewer_left.clear_mask_rect()
            self.viewer_left.set_bg_masks([])
        else:
            self.on_mask_selected(self.list_masks.currentRow())
            self._update_bg_masks()
            
        self.refresh_ui_from_state()
        
    def load_cg(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Multi-Pass CG EXR", "", "EXR Images (*.exr)")
        if path:
            self.lbl_cg_path.setText(os.path.basename(path))
            try:
                input_cs = self.combo_cs_input.currentText()
                out_cs = self.combo_cs_output.currentText()
                
                # Parse prefixes from UI, filtering out empty strings
                raw_prefixes = self.line_edit_prefix.text().split(",")
                prefixes = tuple(p.strip() for p in raw_prefixes if p.strip())
                
                self.pipeline.load_cg_lights(path, prefixes=prefixes, input_colorspace=input_cs, working_space=out_cs)
                self.build_cg_light_sliders()
                self.on_reformat_changed(self.combo_reformat.currentText()) # Force proxies to match current UI reformat resolution
                self.combo_view_mode.setCurrentText("CG Over Plate")
                self.update_viewer(reset_view=True)
                QtWidgets.QMessageBox.information(self, "Success", f"Loaded {len(self.pipeline.state.cg_lights)} Light AOVs successfully.")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load Error", str(e))
                
    def clear_cg(self):
        self.pipeline.state.cg_exr_path = ""
        self.pipeline.state.cg_lights.clear()
        self.pipeline.state.cg_light_params.clear()
        self.pipeline.state.cg_array = None
        self.pipeline.state.cg_light_match_array = None
        self.pipeline.state.cg_alpha = None
        self.pipeline.state.cg_alpha_proxy = None
        self.pipeline.state.cg_reconstructed = None
        self.pipeline.state.cg_reconstructed_proxy = None
        self.pipeline.state.cg_beauty = None
        self.pipeline.state.cg_beauty_proxy = None
        
        self.lbl_cg_path.setText("No EXR Loaded")
        self.build_cg_light_sliders()
        
        if self.combo_view_mode.currentText() in ["CG Over Plate", "CG Match Over Plate"]:
            self.combo_view_mode.setCurrentText("HDRI Over Plate")
            
        self.update_viewer(reset_view=False)
                
    def build_cg_light_sliders(self):
        # Clear existing layout (both widgets and spacers)
        while self.cg_scroll_layout.count():
            item = self.cg_scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        if not self.pipeline.state.cg_lights:
            return
            
        self._cg_pickers = []
        self._cg_sliders = getattr(self, '_cg_sliders', {})
        self._cg_sliders.clear()
        self.active_cg_picker = None
            
        for name in sorted(self.pipeline.state.cg_lights.keys()):
            box = QtWidgets.QGroupBox(f"Light: {name}")
            box.setCheckable(True)
            box.setChecked(True)
            
            def on_check(state, n=name):
                self.pipeline.state.cg_light_params[n]["enabled"] = bool(state)
                self._trigger_update()
                
            box.toggled.connect(on_check)
            l = QtWidgets.QVBoxLayout(box)
            
            btn_solo = QtWidgets.QPushButton("Solo")
            btn_solo.setCheckable(True)
            btn_solo.setFixedWidth(55)
            def on_solo(state, n=name):
                self.pipeline.state.cg_light_params[n]["solo"] = bool(state)
                self._trigger_update()
            btn_solo.toggled.connect(on_solo)
            
            btn_pick = QtWidgets.QPushButton("Sample Color")
            btn_pick.setCheckable(True)
            self._cg_pickers.append(btn_pick)
            
            def on_pick(state, n=name, btn=btn_pick):
                if state:
                    self.active_cg_picker = n
                    self.viewer_left.set_picker_mode(True)
                    for b in self._cg_pickers:
                        if b != btn: b.setChecked(False)
                    self.btn_pick_wb.setChecked(False)
                else:
                    if getattr(self, 'active_cg_picker', None) == n:
                        self.active_cg_picker = None
                        self.viewer_left.set_picker_mode(False)
            btn_pick.toggled.connect(on_pick)
            
            solo_row = QtWidgets.QHBoxLayout()
            solo_row.addWidget(btn_pick)
            
            btn_reset = QtWidgets.QPushButton("Reset")
            btn_reset.setFixedWidth(65)
            def on_reset(*args, n=name):
                if n in getattr(self, '_cg_sliders', {}):
                    self._cg_sliders[n]["ev"].setValue(0)
                    self._cg_sliders[n]["temp"].setValue(0)
                    self._cg_sliders[n]["tint"].setValue(0)
                if n in self.pipeline.state.cg_light_params:
                    self.pipeline.state.cg_light_params[n]["color"] = [1.0, 1.0, 1.0]
                self._trigger_update()
            btn_reset.clicked.connect(on_reset)
            
            solo_row.addStretch()
            solo_row.addWidget(btn_reset)
            solo_row.addWidget(btn_solo)
            l.addLayout(solo_row)
            
            def create_slider_row(label, min_val, max_val, param_key):
                row = QtWidgets.QHBoxLayout()
                name_lbl = QtWidgets.QLabel(label)
                name_lbl.setFixedWidth(45)
                row.addWidget(name_lbl)
                
                sl = QtWidgets.QSlider(QtCore.Qt.Horizontal)
                sl.setRange(min_val, max_val)
                sl.setValue(0)
                
                lbl = QtWidgets.QLabel("0.00")
                lbl.setFixedWidth(50)
                
                row.addWidget(sl)
                row.addWidget(lbl)
                
                def on_change(v, n=name, p=param_key, lb=lbl):
                    val = v / 100.0
                    lb.setText(f"{val:.2f}")
                    self.pipeline.state.cg_light_params[n][p] = val
                    self._trigger_update(hdri=False, plate=False, cg=True)

                def on_release():
                    pass # Handled entirely by proxy now
                    
                sl.valueChanged.connect(on_change)
                sl.sliderReleased.connect(on_release)
                return row, sl, lbl
                
            r1, sl_ev, _ = create_slider_row("EV:", -500, 500, "ev")
            r2, sl_temp, _ = create_slider_row("Temp:", -100, 100, "temp")
            r3, sl_tint, _ = create_slider_row("Tint:", -100, 100, "tint")
            
            self._cg_sliders[name] = {
                "ev": sl_ev,
                "temp": sl_temp,
                "tint": sl_tint
            }
            
            l.addLayout(r1)
            l.addLayout(r2)
            l.addLayout(r3)
            self.cg_scroll_layout.addWidget(box)
            
        self.cg_scroll_layout.addStretch()
        
    def export_cg_json(self):
        if not self.pipeline.state.cg_light_params:
            QtWidgets.QMessageBox.warning(self, "Error", "No CG Lights loaded to export.")
            return
            
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export JSON", "", "JSON Files (*.json)")
        if path:
            try:
                json_path, solaris_script_path = export_cg_light_data(self.pipeline.state.cg_light_params, path)
                msg = f"Exported multipliers to:\n{json_path}\n\nGenerated Solaris LOP Script:\n{solaris_script_path}\n\n(A standard OBJ script was also generated in the same directory)"
                QtWidgets.QMessageBox.information(self, "Success", msg)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", str(e))

    def export_cg_blender(self):
        """Export CG light match parameters as a Blender Python script."""
        if not self.pipeline.state.cg_light_params:
            QtWidgets.QMessageBox.warning(self, "Error", "No CG Lights loaded to export.")
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export JSON for Blender", "", "JSON Files (*.json)")
        if path:
            try:
                from hdri_match.io.blender_export import export_cg_lights_blender
                script_path = export_cg_lights_blender(self.pipeline.state.cg_light_params, path)
                msg = (f"Exported CG light data to:\n{path}\n\n"
                       f"Blender script generated:\n{os.path.basename(script_path)}\n\n"
                       f"Run this script in Blender's Text Editor to apply light adjustments.")
                QtWidgets.QMessageBox.information(self, "Success", msg)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", str(e))

    # --- Renderer Preset ---
    _RENDERER_PRESETS = {
        "Arnold": "C_Light_, light_, key, fill, rim, bounce, warm, cool",
        "V-Ray": "VRayLightSelect_, lightselect_, VRay_Light_",
        "Redshift": "rsLightGroup_, RS_Light_, lightgroup_",
        "RenderMan": "lpe:C<L.'*, lpe_light_, light_",
        "Karma / Solaris": "C_Light_, light_, LPE_light_, lpe:C<L.'*",
        "Custom": "",
    }

    def on_renderer_preset_changed(self, renderer_name):
        """Auto-populate the AOV prefix field when renderer preset changes."""
        preset = self._RENDERER_PRESETS.get(renderer_name, "")
        if renderer_name != "Custom":
            self.line_edit_prefix.setText(preset)

    # --- Blender Export ---
    def export_blender_world(self):
        """Export a Blender Python script for World environment HDRI setup."""
        if self.pipeline.state.calibrated_hdri is None:
            QtWidgets.QMessageBox.warning(self, "No Calibrated HDRI",
                "Please load and calibrate an HDRI first (run Auto Match Plate).\n"
                "Or at minimum, load an HDRI so its path is available.")
            return

        export_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Export Directory for Blender Scripts")
        if not export_dir:
            return

        try:
            from hdri_match.io.blender_export import export_blender_world_setup
            hdri_path = self.pipeline.state.hdri_path or "HDRI_NOT_SET.exr"
            script_path = export_blender_world_setup(
                hdri_path, self.pipeline.state, export_dir)

            QtWidgets.QMessageBox.information(
                self, "Success",
                f"Blender World script exported to:\n{os.path.basename(script_path)}\n\n"
                f"Open Blender → Scripting tab → Open → Run Script")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to export Blender script:\n{e}")

    def export_blender_lights(self):
        """Export mask regions as Blender Area Lights."""
        if self.pipeline.state.hdri_array is None:
            QtWidgets.QMessageBox.warning(self, "No HDRI", "Please load an HDRI first.")
            return

        if not self.pipeline.state.masks:
            QtWidgets.QMessageBox.warning(self, "No Masks",
                "No mask regions defined. Add masks in the HDRI Calibration tab first.")
            return

        export_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Export Directory for Blender Light Scripts")
        if not export_dir:
            return

        try:
            from hdri_match.io.blender_export import export_blender_lights as _export_bl
            hdri_src = self.pipeline.state.calibrated_hdri
            if hdri_src is None:
                hdri_src = self.pipeline.state.hdri_array

            script_path = _export_bl(self.pipeline.state.masks, hdri_src, export_dir)

            QtWidgets.QMessageBox.information(
                self, "Success",
                f"Blender Lights script exported to:\n{os.path.basename(script_path)}\n\n"
                f"Open Blender → Scripting tab → Open → Run Script")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to export Blender lights:\n{e}")

    # --- QC Report ---
    _last_qc_text = ""

    def generate_qc_report(self):
        """Analyze the loaded HDRI and display a QC report."""
        if self.pipeline.state.hdri_array is None:
            QtWidgets.QMessageBox.warning(self, "No HDRI", "Please load an HDRI first.")
            return

        try:
            from hdri_match.analysis.hdri_stats import HDRIStats

            report = HDRIStats.generate_full_report(
                self.pipeline.state.hdri_array,
                hdri_path=self.pipeline.state.hdri_path,
                yaw_offset=self.pipeline.state.hdri_yaw
            )

            report_text = HDRIStats.format_report_text(report)
            self._last_qc_text = report_text
            self.txt_qc_report.setPlainText(report_text)
            self.btn_copy_qc.setEnabled(True)

        except Exception as e:
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to generate QC report:\n{e}")

    def copy_qc_report(self):
        """Copy the QC report text to the clipboard."""
        if self._last_qc_text:
            QtWidgets.QApplication.clipboard().setText(self._last_qc_text)
            QtWidgets.QMessageBox.information(self, "Copied",
                "QC Report copied to clipboard!")

    def generate_mobile_report(self):
        if self.pipeline.state.hdri_array is None:
            QtWidgets.QMessageBox.warning(self, "No HDRI", "Please load an HDRI first.")
            return

        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Mobile Report", "HDRI_QC_Report.html", "HTML Files (*.html)")
        if not out_path:
            return

        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            # Ensure full-res state is computed for accurate CCT/EV
            self.pipeline.build_full_res_cache()
            
            from hdri_match.io.html_report import generate_html_report
            generate_html_report(self.pipeline.state, out_path)
            
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.information(self, "Success", f"Mobile QC report generated:\n{out_path}")
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to generate mobile report:\n{e}")

    # --- OCIO & Colorspace ---
    def load_ocio_from_nuke(self):
        try:
            import nuke
            import os
            
            root = nuke.root()
            color_mgt = root.knob('colorManagement').value()
            if color_mgt != 'OCIO':
                QtWidgets.QMessageBox.information(self, "OCIO", "Nuke is not using OCIO color management.")
                return
                
            config_name = root.knob('OCIO_config').value()
            custom_path = root.knob('customOCIOConfigPath').evaluate() if root.knob('customOCIOConfigPath') else None
            
            ocio_path = None
            if config_name == "custom" and custom_path and os.path.exists(custom_path):
                ocio_path = custom_path
            elif config_name != "custom":
                # Resolve Nuke's built-in configs
                nuke_dir = os.path.dirname(nuke.env['ExecutablePath'])
                built_in = os.path.join(nuke_dir, 'plugins', 'OCIOConfigs', 'configs', config_name, 'config.ocio')
                if os.path.exists(built_in):
                    ocio_path = built_in
                else:
                    # Fallback search inside configs directory
                    search_dir = os.path.join(nuke_dir, 'plugins', 'OCIOConfigs', 'configs')
                    if os.path.exists(search_dir):
                        for root_dir, _, files in os.walk(search_dir):
                            if 'config.ocio' in files and config_name in root_dir:
                                ocio_path = os.path.join(root_dir, 'config.ocio')
                                break
                                
            if ocio_path and os.path.exists(ocio_path):
                self.lbl_ocio_path.setText(f"Nuke ({config_name})")
                self.pipeline.set_ocio_config(ocio_path)
            elif os.environ.get('OCIO'):
                self.lbl_ocio_path.setText("Nuke Env ($OCIO)")
                self.pipeline.set_ocio_config(os.environ.get('OCIO'))
            else:
                QtWidgets.QMessageBox.information(self, "OCIO", "Could not resolve Nuke OCIO config path.")
                return
                
            self.populate_colorspaces()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to get OCIO from Nuke: {e}")

    def load_ocio_config(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select OCIO Config", "", "OCIO Config (*.ocio *.ocio.xml);;All Files (*)")
        if path:
            self.lbl_ocio_path.setText(os.path.basename(path))
            try:
                self.pipeline.set_ocio_config(path)
                self.populate_colorspaces()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "OCIO Error", f"Failed to load config:\n{e}")

    def populate_colorspaces(self):
        spaces = self.pipeline.colorspace_manager.get_color_spaces()
        if not spaces:
            return
            
        current_in = self.combo_cs_input.currentText()
        current_out = self.combo_cs_output.currentText()
        
        self.combo_cs_input.blockSignals(True)
        self.combo_cs_output.blockSignals(True)
        
        self.combo_cs_input.clear()
        self.combo_cs_output.clear()
        self.combo_cs_input.addItems(spaces)
        self.combo_cs_output.addItems(spaces)
        
        
        self.combo_display_transform.blockSignals(True)
        current_dt = self.combo_display_transform.currentText()
        self.combo_display_transform.clear()
        dt_views = self.pipeline.colorspace_manager.get_display_views()
        if dt_views:
            self.combo_display_transform.addItems(dt_views)
            # Always try to default to sRGB when loading a new config
            for v in ["sRGB (ACES)", "sRGB", "Output - sRGB"]:
                if v in dt_views:
                    self.combo_display_transform.setCurrentText(v)
                    break
        self.combo_display_transform.blockSignals(False)
        
        # Try to restore previous selection
        found_in = current_in in spaces
        found_out = current_out in spaces
        
        # Auto-detect Input
        if self.pipeline.colorspace_manager.config:
            best_in = self._find_best_colorspace(spaces, 
                prefer=["Utility - Raw", "Raw", "raw", "Utility - Linear - sRGB", "Linear - sRGB", "Linear"],
                keywords=["raw", "utility"],
                avoid=["acescg", "aces2065", "ap0", "ap1", "log", "display"])
        else:
            best_in = self._find_best_colorspace(spaces, 
                prefer=["Linear - sRGB", "Linear", "scene_linear"],
                keywords=["linear"])
                
        if best_in:
            self.combo_cs_input.setCurrentText(best_in)
            print(f"[OCIO] Auto-selected Input: '{best_in}'")
        # Auto-detect Output
        if self.pipeline.colorspace_manager.config:
            # Auto-detect Output: ACEScg working space
            best_out = self._find_best_colorspace(spaces,
                prefer=["ACES - ACEScg", "ACEScg", "acescg", 
                         "scene-linear DCI-P3 D65"],
                keywords=["acescg"],
                avoid=["aces2065", "ap0", "log", "display", "srgb"])
        else:
            best_out = self._find_best_colorspace(spaces,
                prefer=["Linear - sRGB", "Linear", "scene_linear"],
                keywords=["linear"])
                
        if best_out:
            self.combo_cs_output.setCurrentText(best_out)
            print(f"[OCIO] Auto-selected Output: '{best_out}'")
            
        self.combo_cs_input.blockSignals(False)
        self.combo_cs_output.blockSignals(False)
        self.reload_all_images()
    
    def _find_best_colorspace(self, spaces, prefer=None, keywords=None, avoid=None):
        """Find the best matching color space from a list."""
        # First pass: exact match from preferred list
        if prefer:
            for p in prefer:
                for s in spaces:
                    if s.lower() == p.lower():
                        return s
        # Second pass: partial match from preferred list
        if prefer:
            for p in prefer:
                for s in spaces:
                    if p.lower() in s.lower():
                        return s
        # Third pass: keyword match (all keywords must match, none of avoid)
        if keywords:
            for s in spaces:
                s_lower = s.lower()
                if all(k in s_lower for k in keywords):
                    if avoid and any(a in s_lower for a in avoid):
                        continue
                    return s
        return None
        
    def reload_all_images(self, *_args):
        in_cs = self.combo_cs_input.currentText()
        out_cs = self.combo_cs_output.currentText()
        
        # Reload HDRI and Plate
        if self.pipeline.state.hdri_path or self.pipeline.state.plate_path:
            try:
                self.pipeline.load_inputs(self.pipeline.state.hdri_path, self.pipeline.state.plate_path, input_space=in_cs, working_space=out_cs)
                if self.pipeline.state.hdri_path and self.pipeline.state.plate_path:
                    if self.pipeline.state.sky_mode != "custom_rect":
                        self.run_calibration()
                    else:
                        self.pipeline.process_hdri(use_proxy=False)
            except Exception as e:
                print(f"Error reloading HDRI/Plate colorspace: {e}")
                
        # Reload CG Lights
        if hasattr(self.pipeline.state, 'cg_exr_path') and self.pipeline.state.cg_exr_path:
            try:
                raw_prefixes = self.line_edit_prefix.text().split(",")
                prefixes = tuple(p.strip() for p in raw_prefixes if p.strip())
                self.pipeline.load_cg_lights(self.pipeline.state.cg_exr_path, prefixes=prefixes, input_colorspace=in_cs, working_space=out_cs)
            except Exception as e:
                print(f"Error reloading CG colorspace: {e}")
                
        self.update_viewer(reset_view=True)

    # --- Existing HDRI Methods ---
    def open_3d_viewer(self):
        from hdri_match.ui.viewport3d import ViewportWindow
        self._3d_window = ViewportWindow(self)
        self._3d_window.show()
        
    def new_project(self):
        reply = QtWidgets.QMessageBox.question(
            self, "New Project", 
            "Are you sure you want to clear the current project? Unsaved changes will be lost.", 
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.pipeline.state = ImageState()
            self.viewer_left.clear_mask_rect()
            self.viewer_left.set_bg_masks([])
            self.viewer_right.clear_mask_rect()
            self.viewer_right.set_bg_masks([])
            self.lbl_hdri_path.setText("No file selected")
            self.lbl_plate_path.setText("No file selected")
            self.lbl_cg_path.setText("No file selected")
            self.refresh_ui_from_state()
            self.update_viewer(reset_view=True)
            self._trigger_update(hdri=True, plate=True, cg=True)
            
    def clear_hdri(self):
        self.pipeline.state.hdri_path = ""
        self.pipeline.state.hdri_sequence = []
        self.pipeline.state.hdri_array = None
        self.pipeline.state.hdri_proxy = None
        self.pipeline.state.calibrated_hdri = None
        self.pipeline.state.calibrated_proxy = None
        self.lbl_hdri_path.setText("No file selected")
        self.update_timeline_range()
        self._trigger_update(hdri=True)
        self.update_viewer(reset_view=True)
        
    def clear_plate(self):
        self.pipeline.state.plate_path = ""
        self.pipeline.state.plate_sequence = []
        self.pipeline.state.plate_array = None
        self.pipeline.state.plate_proxy = None
        self.pipeline.state.plate_graded = None
        self.pipeline.state.plate_graded_proxy = None
        self.lbl_plate_path.setText("No file selected")
        self.update_timeline_range()
        self._trigger_update(plate=True)
        self.update_viewer(reset_view=True)

    def detect_sequence(self, file_path):
        import re, glob
        m = re.search(r'([._-]?\d+)\.(exr|hdr|jpg|jpeg|png|tif|tiff)$', file_path, re.IGNORECASE)
        if not m: return [file_path]
        prefix = file_path[:m.start(1)]
        ext = m.group(2)
        pattern = f"{prefix}*.{ext}"
        files = sorted(glob.glob(pattern))
        return files if len(files) > 1 else [file_path]
        
    def update_timeline_range(self):
        seq_len = max(len(self.pipeline.state.hdri_sequence), len(self.pipeline.state.plate_sequence))
        if seq_len > 1:
            self.slider_timeline.setEnabled(True)
            self.slider_timeline.blockSignals(True)
            self.slider_timeline.setRange(0, seq_len - 1)
            self.slider_timeline.setValue(self.pipeline.state.current_frame_index)
            self.slider_timeline.blockSignals(False)
            self.lbl_timeline_frame.setText(f"Frame: {self.pipeline.state.current_frame_index + 1} / {seq_len}")
        else:
            self.slider_timeline.setEnabled(False)
            self.lbl_timeline_frame.setText("Frame: 0 / 0")

    def _process_and_cache_frame(self, frame_idx):
        """Load, process, display and cache a single frame. Returns True on success."""
        st = self.pipeline.state
        hdri_path = st.hdri_sequence[frame_idx] if frame_idx < len(st.hdri_sequence) else None
        plate_path = st.plate_sequence[frame_idx] if frame_idx < len(st.plate_sequence) else None
        
        if not hdri_path and not plate_path:
            return False

        in_cs = self.combo_cs_input.currentText()
        out_cs = self.combo_cs_output.currentText()
        try:
            self.pipeline.load_inputs(hdri_path=hdri_path, plate_path=plate_path,
                                      input_space=in_cs, working_space=out_cs)
            if hdri_path and plate_path and st.sky_mode != "custom_rect":
                self.pipeline.compute_calibration(
                    use_chrome_ball=st.chrome_ball_array is not None,
                    use_grey_ball=st.grey_ball_array is not None,
                    use_macbeth_chart=st.macbeth_chart_array is not None,
                    protect_sun=self.chk_protect_sun.isChecked()
                )
            self.pipeline.process_hdri(use_proxy=True)
            if st.plate_array is not None:
                self.pipeline.process_plate(use_proxy=True)
            if st.cg_lights:
                self.pipeline.reconstruct_cg_beauty(use_proxy=True)

            # Tell update_viewer we are in a timeline update so _trigger_update
            # does NOT get called (and does NOT clear the cache).
            self._is_timeline_update = True
            self.update_viewer(use_proxy=True)
            self._is_timeline_update = False

            # Snapshot the rendered 8-bit frame into the persistent cache.
            left_u8 = self.viewer_left.last_8u.copy() if getattr(self.viewer_left, 'last_8u', None) is not None else None
            right_u8 = self.viewer_right.last_8u.copy() if getattr(self.viewer_right, 'last_8u', None) is not None else None
            scope_u8 = left_u8  # scopes always use the left viewer
            if left_u8 is not None:
                self._playback_cache[frame_idx] = (left_u8, right_u8, scope_u8)
                self.slider_timeline.set_cached_frames(self._playback_cache.keys())
            return True
        except Exception as e:
            print(f"[Timeline] Frame {frame_idx} load error: {e}")
            return False

    def _display_cached_frame(self, frame_idx):
        """Fast-path: display a cached u8 frame via the viewer's set_image_u8()."""
        if frame_idx not in self._playback_cache:
            return False
        left_u8, right_u8, scope = self._playback_cache[frame_idx]
        if left_u8 is not None:
            self.viewer_left.set_image_u8(left_u8)
        if right_u8 is not None:
            self.viewer_right.set_image_u8(right_u8)
        if scope is not None:
            self.scopes_widget.update_scopes(scope)
        return True

    def on_timeline_changed(self, frame_idx):
        """Called ONLY by manual scrubbing (slider drag). Never called during playback."""
        st = self.pipeline.state
        st.current_frame_index = frame_idx
        seq_len = max(len(st.hdri_sequence), len(st.plate_sequence))
        self.lbl_timeline_frame.setText(f"Frame: {frame_idx + 1} / {seq_len}")

        if hdri_path := (st.hdri_sequence[frame_idx] if frame_idx < len(st.hdri_sequence) else None):
            self.lbl_hdri_path.setText(os.path.basename(hdri_path) +
                (f" ({len(st.hdri_sequence)} frames)" if len(st.hdri_sequence) > 1 else ""))
        if plate_path := (st.plate_sequence[frame_idx] if frame_idx < len(st.plate_sequence) else None):
            self.lbl_plate_path.setText(os.path.basename(plate_path) +
                (f" ({len(st.plate_sequence)} frames)" if len(st.plate_sequence) > 1 else ""))

        # If already cached: fast-path display, no processing needed.
        if self._display_cached_frame(frame_idx):
            return

        # Not yet cached: process and cache this frame.
        self._process_and_cache_frame(frame_idx)

    def on_play_toggled(self, checked):
        if checked:
            self.btn_play_pause.setText("⏸")
            # Determine framerate
            fps_val = 24.0
            try:
                fps_val = float(self.combo_fps.currentText())
            except ValueError:
                pass
            if fps_val <= 0:
                fps_val = 24.0
            interval = getattr(self, '_playback_interval_ms', int(1000 / fps_val))
            self._playback_timer.start(interval)
        else:
            self.btn_play_pause.setText("▶")
            self._playback_timer.stop()
            
    def on_playback_tick(self):
        """Timer tick: advance one frame. Uses cache fast-path; processes only on cache miss."""
        st = self.pipeline.state
        seq_len = max(len(st.hdri_sequence), len(st.plate_sequence))
        if seq_len <= 1:
            self.btn_play_pause.setChecked(False)
            return

        next_frame = (st.current_frame_index + 1) % seq_len
        st.current_frame_index = next_frame
        self.lbl_timeline_frame.setText(f"Frame: {next_frame + 1} / {seq_len}")

        # Update slider position WITHOUT triggering on_timeline_changed
        self.slider_timeline.blockSignals(True)
        self.slider_timeline.setValue(next_frame)
        self.slider_timeline.blockSignals(False)

        if next_frame in self._playback_cache:
            # ─── FAST PATH: frame already in RAM cache ───────────────────────
            self._display_cached_frame(next_frame)
        else:
            # ─── CACHE MISS: load, process and store this frame ──────────────
            self._process_and_cache_frame(next_frame)

    def on_fps_changed(self, value):
        try:
            fps = float(value)
            if fps <= 0:
                fps = 24.0
            # Store the interval so on_play_toggled picks it up
            self._playback_interval_ms = int(1000 / fps)
            # Update live timer if currently playing
            if self._playback_timer.isActive():
                self._playback_timer.start(self._playback_interval_ms)
            # Cache built at one FPS is invalid for a different FPS
            # (user changed rate, probably wants a clean re-cache)
            self.invalidate_playback_cache()
        except ValueError:
            pass

    def on_reset_cache(self):
        """Wipe the RAM frame buffer so the next playback re-caches from scratch."""
        # Stop playback first so the timer isn't mid-tick
        was_playing = self._playback_timer.isActive()
        if was_playing:
            self.btn_play_pause.setChecked(False)

        self.invalidate_playback_cache()

        # Visual feedback — briefly change button text
        self.btn_reset_cache.setText("✓ Cleared")
        self.btn_reset_cache.setEnabled(False)
        QtCore.QTimer.singleShot(1200, lambda: (
            self.btn_reset_cache.setText("⟳ Cache"),
            self.btn_reset_cache.setEnabled(True)
        ))

    def on_first_frame(self):
        if self.slider_timeline.isEnabled():
            self.slider_timeline.setValue(0)

    def on_prev_frame(self):
        if self.slider_timeline.isEnabled():
            self.slider_timeline.setValue(max(0, self.pipeline.state.current_frame_index - 1))

    def on_next_frame(self):
        if self.slider_timeline.isEnabled():
            seq_len = max(len(self.pipeline.state.hdri_sequence), len(self.pipeline.state.plate_sequence))
            self.slider_timeline.setValue(min(seq_len - 1, self.pipeline.state.current_frame_index + 1))

    def on_last_frame(self):
        if self.slider_timeline.isEnabled():
            seq_len = max(len(self.pipeline.state.hdri_sequence), len(self.pipeline.state.plate_sequence))
            self.slider_timeline.setValue(max(0, seq_len - 1))

    def _guess_colorspace(self, path):
        ext = os.path.splitext(path)[1].lower()
        spaces = [self.combo_cs_input.itemText(i) for i in range(self.combo_cs_input.count())]
        if not spaces:
            return None
            
        if ext in ['.exr', '.hdr']:
            if self.pipeline.colorspace_manager.config:
                candidates = ["Utility - Raw", "Raw", "ACES - ACEScg", "ACEScg", "scene_linear", "linear", "Linear - sRGB"]
            else:
                candidates = ["scene_linear", "Linear - sRGB", "linear", "ACES - ACEScg", "ACEScg"]
                
            for c in candidates:
                for s in spaces:
                    if c.lower() in s.lower() and "display" not in s.lower() and "texture" not in s.lower():
                        return s
            for s in spaces:
                if "utility - raw" in s.lower() or "raw" in s.lower():
                    return s
        else:
            candidates = ["Utility - sRGB - Texture", "sRGB - Texture", "sRGB", "Gamma2.2"]
            for c in candidates:
                for s in spaces:
                    if c.lower() in s.lower() and "linear" not in s.lower() and "raw" not in s.lower():
                        return s
        return None

    def load_hdri(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select HDRI", "", "Images (*.exr *.hdr *.arw *.cr2 *.nef *.dng *.tif *.tiff *.png *.jpg *.jpeg);;All Files (*)")
        if path:
            seq = self.detect_sequence(path)
            self.pipeline.state.hdri_sequence = seq
            self.update_timeline_range()
            path = seq[self.pipeline.state.current_frame_index] if self.pipeline.state.current_frame_index < len(seq) else seq[0]
            self.lbl_hdri_path.setText(os.path.basename(path) + (f" ({len(seq)} frames)" if len(seq)>1 else ""))
            try:
                guessed_cs = self._guess_colorspace(path)
                if guessed_cs:
                    self.combo_cs_input.setCurrentText(guessed_cs)
                in_cs = self.combo_cs_input.currentText()
                out_cs = self.combo_cs_output.currentText()
                self.pipeline.load_inputs(hdri_path=path, plate_path=self.pipeline.state.plate_path, input_space=in_cs, working_space=out_cs)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load Error", str(e))
            self.combo_view_mode.setCurrentText("Split Comparison")
            self._trigger_update()
            self.update_viewer(reset_view=True)
            
    def load_plate(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Plate", "", "Plate Images (*.exr *.hdr *.jpg *.jpeg *.png *.tif *.tiff *.arw *.cr2 *.nef *.dng);;All Files (*)")
        if path:
            seq = self.detect_sequence(path)
            self.pipeline.state.plate_sequence = seq
            self.update_timeline_range()
            path = seq[self.pipeline.state.current_frame_index] if self.pipeline.state.current_frame_index < len(seq) else seq[0]
            self.lbl_plate_path.setText(os.path.basename(path) + (f" ({len(seq)} frames)" if len(seq)>1 else ""))
            try:
                guessed_cs = self._guess_colorspace(path)
                if guessed_cs:
                    self.combo_cs_input.setCurrentText(guessed_cs)
                in_cs = self.combo_cs_input.currentText()
                out_cs = self.combo_cs_output.currentText()
                self.pipeline.load_inputs(hdri_path=self.pipeline.state.hdri_path, plate_path=path, input_space=in_cs, working_space=out_cs)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load Error", str(e))
            self.combo_view_mode.setCurrentText("Split Comparison")
            self._trigger_update()
            self.update_viewer(reset_view=True)

    def load_macbeth(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Macbeth Chart", "", "Reference Images (*.exr *.hdr *.arw *.cr2 *.nef *.dng *.tif *.tiff *.png *.jpg *.jpeg);;All Files (*)")
        if path:
            try:
                from hdri_match.io.loader import load_exr_to_numpy
                from hdri_match.calibration.autocrop import AutoCropper
                arr = load_exr_to_numpy(path)
                if self.chk_autocrop.isChecked():
                    self.pipeline.state.macbeth_chart_array = AutoCropper.autocrop_macbeth(arr)
                else:
                    rect = self.viewer_left.get_mask_rect_normalized()
                    if rect is not None:
                        nx1, ny1, nx2, ny2 = rect
                        h, w = arr.shape[:2]
                        x1, x2 = int(min(nx1, nx2) * w), int(max(nx1, nx2) * w)
                        y1, y2 = int(min(ny1, ny2) * h), int(max(ny1, ny2) * h)
                        if x2 > x1 and y2 > y1:
                            arr = arr[y1:y2, x1:x2]
                    self.pipeline.state.macbeth_chart_array = arr
                self._cache_macbeth_pixmap = None
                self.update_viewer()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load Error", str(e))

    def load_chrome(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Chrome Ball", "", "Reference Images (*.exr *.hdr *.arw *.cr2 *.nef *.dng *.tif *.tiff *.png *.jpg *.jpeg);;All Files (*)")
        if path:
            try:
                from hdri_match.io.loader import load_exr_to_numpy
                from hdri_match.calibration.autocrop import AutoCropper
                arr = load_exr_to_numpy(path)
                if self.chk_autocrop.isChecked():
                    self.pipeline.state.chrome_ball_array = AutoCropper.autocrop_ball(arr)
                else:
                    rect = self.viewer_left.get_mask_rect_normalized()
                    if rect is not None:
                        nx1, ny1, nx2, ny2 = rect
                        h, w = arr.shape[:2]
                        x1, x2 = int(min(nx1, nx2) * w), int(max(nx1, nx2) * w)
                        y1, y2 = int(min(ny1, ny2) * h), int(max(ny1, ny2) * h)
                        if x2 > x1 and y2 > y1:
                            arr = arr[y1:y2, x1:x2]
                    self.pipeline.state.chrome_ball_array = arr
                self._cache_chrome_pixmap = None
                self.update_viewer()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load Error", str(e))
                
    def load_grey(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Grey Ball", "", "Reference Images (*.exr *.hdr *.arw *.cr2 *.nef *.dng *.tif *.tiff *.png *.jpg *.jpeg);;All Files (*)")
        if path:
            try:
                from hdri_match.io.loader import load_exr_to_numpy
                from hdri_match.calibration.autocrop import AutoCropper
                arr = load_exr_to_numpy(path)
                if self.chk_autocrop.isChecked():
                    self.pipeline.state.grey_ball_array = AutoCropper.autocrop_ball(arr)
                else:
                    rect = self.viewer_left.get_mask_rect_normalized()
                    if rect is not None:
                        nx1, ny1, nx2, ny2 = rect
                        h, w = arr.shape[:2]
                        x1, x2 = int(min(nx1, nx2) * w), int(max(nx1, nx2) * w)
                        y1, y2 = int(min(ny1, ny2) * h), int(max(ny1, ny2) * h)
                        if x2 > x1 and y2 > y1:
                            arr = arr[y1:y2, x1:x2]
                    self.pipeline.state.grey_ball_array = arr
                self._cache_grey_pixmap = None
                self.update_viewer()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Load Error", str(e))
            
    def clear_macbeth(self):
        self.pipeline.state.macbeth_chart_array = None
        self.pipeline.state.macbeth_matrix = None
        self._cache_macbeth_pixmap = None
        self.pipeline.process_hdri(use_proxy=True)
        self.update_viewer(use_proxy=True, reset_view=True)
        QtCore.QTimer.singleShot(100, lambda: self._trigger_update())

    def clear_chrome(self):
        self.pipeline.state.chrome_ball_array = None
        self._cache_chrome_pixmap = None
        self.update_viewer(reset_view=True)

    def clear_grey(self):
        self.pipeline.state.grey_ball_array = None
        self._cache_grey_pixmap = None
        self.update_viewer(reset_view=True)



    def start_interactive_crop(self, ref_type):
        st = self.pipeline.state
        arr = None
        if ref_type == "macbeth":
            arr = st.macbeth_chart_array
        elif ref_type == "chrome":
            arr = st.chrome_ball_array
        elif ref_type == "grey":
            arr = st.grey_ball_array
            
        if arr is None:
            QtWidgets.QMessageBox.warning(self, "Error", f"Please load a {ref_type.capitalize()} reference first.")
            return
            
        dialog = CropDialog(arr, self)
        if dialog.exec_():
            cropped = dialog.get_cropped_image()
            if cropped is not None:
                if ref_type == "macbeth":
                    st.macbeth_chart_array = cropped
                    self._cache_macbeth_pixmap = None
                elif ref_type == "chrome":
                    st.chrome_ball_array = cropped
                    self._cache_chrome_pixmap = None
                elif ref_type == "grey":
                    st.grey_ball_array = cropped
                    self._cache_grey_pixmap = None
                
                self.update_viewer(reset_view=True)
            else:
                QtWidgets.QMessageBox.warning(self, "Crop Failed", "Please draw a valid rectangle to crop.")

    def auto_detect_macbeth(self):
        if self.pipeline.state.macbeth_chart_array is None:
            QtWidgets.QMessageBox.warning(self, "Error", "Please load a Macbeth Chart image first.")
            return
            
        try:
            from hdri_match.calibration.macbeth import MacbethDetector
            color_space = self.combo_cs_output.currentText()
            matrix = MacbethDetector.detect_and_build_matrix(self.pipeline.state.macbeth_chart_array, color_space=color_space)
            # We trust the matrix solver. If the matrix is bad, the user can clear it.
            self.pipeline.state.macbeth_matrix = matrix
            self.pipeline.process_hdri(use_proxy=True)
            self.update_viewer(use_proxy=True)
            
            msg = "Successfully detected 24 patches and built Color Matrix:\n\n"
            msg += f"[{matrix[0,0]:.4f}, {matrix[0,1]:.4f}, {matrix[0,2]:.4f}]\n"
            msg += f"[{matrix[1,0]:.4f}, {matrix[1,1]:.4f}, {matrix[1,2]:.4f}]\n"
            msg += f"[{matrix[2,0]:.4f}, {matrix[2,1]:.4f}, {matrix[2,2]:.4f}]\n\n"
            msg += "Note: In a full pipeline, this matrix replaces the simple Temp/Tint sliders.\nThe matrix has been applied to the HDRI."
            QtWidgets.QMessageBox.information(self, "Macbeth Matrix", msg)
            
            # Rebuild full-res in background
            QtCore.QTimer.singleShot(100, lambda: self._trigger_update())
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Detection Failed", str(e))

    def on_reset_view_clicked(self):
        self.viewer_left.reset_view()
        self.viewer_right.reset_view()

    def on_viewport_ev_changed(self, value):
        ev = value / 100.0
        self.lbl_viewport_ev.setText(f"{ev:.2f}")
        self.viewer_left.set_viewport_ev(ev)
        self.viewer_right.set_viewport_ev(ev)

    def on_reset_viewport_ev_clicked(self):
        self.slider_viewport_ev.setValue(0)

    def refresh_ui_from_state(self):
        """Synchronize UI controls with the current pipeline state."""
        st = self.pipeline.state
        
        # 1. Sync CG Light parameters
        if hasattr(self, '_cg_sliders') and st.cg_light_params:
            for name, params in st.cg_light_params.items():
                if name in self._cg_sliders:
                    sliders = self._cg_sliders[name]
                    ev = params.get("ev", 0.0)
                    temp = params.get("temp", 0.0)
                    tint = params.get("tint", 0.0)
                    
                    sliders["ev"].setValue(int(ev * 100))
                    sliders["temp"].setValue(int(temp * 100))
                    sliders["tint"].setValue(int(tint * 100))

        # 2. Force viewer update to correctly reflect synced state
        self.update_viewer(use_proxy=True, reset_view=False)

    def export_nuke_nodes(self):
        st = self.pipeline.state
        
        from hdri_match.io.nuke_export import export_nuke_nodes as _export_nuke_nodes
        nuke_script = _export_nuke_nodes(st)
        QtWidgets.QApplication.clipboard().setText(nuke_script)
        QtWidgets.QMessageBox.information(self, "Success", "Nuke nodes copied to clipboard!\nPaste (Ctrl+V) directly into your Nuke node graph.")

    def export_backplate_nodes(self):
        st = self.pipeline.state
        if st.hdri_array is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No HDRI loaded.")
            return
            
        fov, ok1 = QtWidgets.QInputDialog.getDouble(self, "Camera FOV", "Enter Lens FOV (degrees):", 60.0, 10.0, 150.0, 1)
        if not ok1: return
        
        res_list = ["HD_1080", "UHD_4K", "8K_LatLong", "square_2K"]
        res, ok2 = QtWidgets.QInputDialog.getItem(self, "Resolution", "Select Output Resolution:", res_list, 1, False)
        if not ok2: return
        
        from hdri_match.io.nuke_export import export_backplate_nuke_nodes
        nuke_script = export_backplate_nuke_nodes(st, resolution=res, fov=fov)
        QtWidgets.QApplication.clipboard().setText(nuke_script)
        QtWidgets.QMessageBox.information(self, "Success", f"Backplate extraction Nuke script copied to clipboard!\n\nParameters:\nFOV: {fov}°\nFormat: {res}")

    def extract_sun(self):
        if self.pipeline.state.hdri_array is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No HDRI loaded.")
            return
            
        from hdri_match.analysis.light_extractor import LightExtractor
        lights = LightExtractor.extract_lights(self.pipeline.state.hdri_array, num_lights=1, mask_radius_px=100)
        if lights:
            sun = lights[0]
            dx, dy, dz = sun['vector']
            import math
            azimuth = math.degrees(math.atan2(dx, dz))
            elevation = math.degrees(math.asin(dy))
            msg = f"Sun Vector Extracted:\n\nAzimuth: {azimuth:.2f}°\nElevation: {elevation:.2f}°\nIntensity: {sun['intensity']:.2f}\n\nValues copied to clipboard!"
            QtWidgets.QApplication.clipboard().setText(f"Azimuth: {azimuth:.2f}, Elevation: {elevation:.2f}")
            QtWidgets.QMessageBox.information(self, "Sun Detected", msg)
        else:
            QtWidgets.QMessageBox.warning(self, "Error", "Could not detect a clear light source.")

    def run_calibration(self):
        try:
            use_chrome = self.pipeline.state.chrome_ball_array is not None
            use_grey = self.pipeline.state.grey_ball_array is not None
            use_macbeth = self.pipeline.state.macbeth_chart_array is not None
            protect_sun = self.chk_protect_sun.isChecked()
            self.pipeline.state.apply_exposure_match = self.chk_apply_hdri_exposure.isChecked()
            
            # Sync user-drawn mask rect from viewer into pipeline state.
            active_mask = self.get_active_mask()
            has_mask = active_mask is not None and getattr(active_mask, 'enabled', False)
            
            if has_mask:
                norm_rect = self.viewer_left.get_mask_rect_normalized()
                # Store as plate_mask_rect (for plate-based EV and illuminant sampling)
                self.pipeline.state.plate_mask_rect = norm_rect
                # Also store as HDRI mask_rect if drawing was done on the HDRI view
                current_view = self.combo_view_mode.currentText()
                if current_view in ("HDRI", "Split Comparison"):
                    self.pipeline.state.mask_rect = norm_rect
                    self.pipeline.state.plate_mask_rect = None
                else:
                    self.pipeline.state.mask_rect = None
            else:
                self.pipeline.state.mask_rect = None
                self.pipeline.state.plate_mask_rect = None

            self.slider_temp.blockSignals(True)
            self.slider_tint.blockSignals(True)
            self.slider_temp.setValue(0)
            self.slider_tint.setValue(0)
            self.lbl_temp_value.setText("0.00")
            self.lbl_tint_value.setText("0.00")
            self.pipeline.state.temperature = 0.0
            self.pipeline.state.tint = 0.0
            self.slider_temp.blockSignals(False)
            self.slider_tint.blockSignals(False)

            self.pipeline.compute_calibration(use_chrome_ball=use_chrome, use_grey_ball=use_grey, use_macbeth_chart=use_macbeth, protect_sun=protect_sun)
            self.pipeline.process_hdri(use_proxy=False)
            self.slider_ev.blockSignals(True)
            self.slider_ev.setValue(int(self.pipeline.state.ev_offset * 100))
            black = self.pipeline.state.black_offset
            ev_display = self.pipeline.state.ev_offset
            # Show black_offset alongside EV so the user knows the full tonal correction.
            if abs(black) > 0.001:
                self.lbl_ev_value.setText(
                    f"{ev_display:.2f} EV  (black {black:+.4f})")
            else:
                self.lbl_ev_value.setText(f"{ev_display:.2f} EV")
            if not self.pipeline.state.apply_exposure_match:
                self.lbl_ev_value.setText("0.00 EV  (preserved)")
            self.slider_ev.blockSignals(False)
            
            self.combo_view_mode.setCurrentText("Split Comparison") 
            self.update_viewer()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", str(e))
            
    def on_pick_wb_toggled(self, checked):
        self.viewer_left.set_picker_mode(checked)
        
    def on_pixel_picked(self, r, g, b):
        self.btn_pick_wb.setChecked(False) # Turn off button
        
        # Check if we are picking for a CG light
        if getattr(self, 'active_cg_picker', None) is not None:
            name = self.active_cg_picker
            
            import math
            fr, fg, fb = float(r), float(g), float(b)
            max_val = max(fr, fg, fb)
            
            if max_val > 1e-6:
                ev_offset = math.log2(max_val)
                norm_color = [fr/max_val, fg/max_val, fb/max_val]
            else:
                ev_offset = 0.0
                norm_color = [fr, fg, fb]
                
            # Apply sampled color and extracted EV
            self.pipeline.state.cg_light_params[name]["color"] = norm_color
            self.pipeline.state.cg_light_params[name]["ev"] = ev_offset
            self.pipeline.state.cg_light_params[name]["temp"] = 0.0
            self.pipeline.state.cg_light_params[name]["tint"] = 0.0
            
            # Update UI sliders
            sliders = getattr(self, '_cg_sliders', {}).get(name)
            if sliders:
                sliders["ev"].blockSignals(True)
                sliders["temp"].blockSignals(True)
                sliders["tint"].blockSignals(True)
                
                sliders["ev"].setValue(int(ev_offset * 100))
                sliders["temp"].setValue(0)
                sliders["tint"].setValue(0)
                
                # Update labels (assuming they are next sibling, but easiest to let user see 0)
                # We'll just trigger update
                sliders["ev"].blockSignals(False)
                sliders["temp"].blockSignals(False)
                sliders["tint"].blockSignals(False)
            
            # Turn off picker UI
            self.active_cg_picker = None
            self.viewer_left.set_picker_mode(False)
            if hasattr(self, '_cg_pickers'):
                for btn in self._cg_pickers:
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
            
            self._trigger_update()
            self.on_slider_released()
            return

        
        L = (r + g + b) / 3.0
        if r < 1e-6 or g < 1e-6 or b < 1e-6 or L < 1e-6:
            return
            
        r_scale = L / r
        g_scale = L / g
        b_scale = L / b
        norm = (r_scale + g_scale + b_scale) / 3.0
        
        # Calculate offsets needed to neutralize this color
        tint = 1.0 - (g_scale / norm)
        temp = 1.0 - (b_scale / norm)
        
        # We ADD these offsets to the current global temperature/tint sliders
        new_temp = self.pipeline.state.temperature + temp
        new_tint = self.pipeline.state.tint + tint
        
        # Clamp to -1.0 to 1.0 bounds
        new_temp = max(-1.0, min(1.0, new_temp))
        new_tint = max(-1.0, min(1.0, new_tint))
        
        self.slider_temp.blockSignals(True)
        self.slider_tint.blockSignals(True)
        
        self.slider_temp.setValue(int(new_temp * 100))
        self.slider_tint.setValue(int(new_tint * 100))
        self.lbl_temp_value.setText(f"{new_temp:.2f}")
        self.lbl_tint_value.setText(f"{new_tint:.2f}")
        
        self.slider_temp.blockSignals(False)
        self.slider_tint.blockSignals(False)
        
        self.pipeline.state.temperature = new_temp
        self.pipeline.state.tint = new_tint
        self._trigger_update()
        self.on_slider_released()

    def on_ref_clicked(self, ref_type, u, v):
        if not self.viewer_left._picker_mode:
            return
        arr = None
        if ref_type == "macbeth":
            arr = self.pipeline.state.macbeth_chart_array
        elif ref_type == "chrome":
            arr = self.pipeline.state.chrome_ball_array
        elif ref_type == "grey":
            arr = self.pipeline.state.grey_ball_array
            
        if arr is not None:
            h, w = arr.shape[:2]
            px = min(int(u * w), w - 1)
            py = min(int(v * h), h - 1)
            r, g, b = arr[py, px, :3]
            self.on_pixel_picked(float(r), float(g), float(b))
            self.viewer_left.set_picker_mode(False)

    def reset_hdri_calibration(self):
        """Reset all HDRI calibration values and illuminants to their defaults."""
        self.pipeline.state.ev_offset = 0.0
        self.pipeline.state.black_offset = 0.0
        self.pipeline.state.hdri_yaw = 0.0
        self.pipeline.state.temperature = 0.0
        self.pipeline.state.tint = 0.0
        self.pipeline.state.apply_exposure_match = False
        self.pipeline.state.hdri_illuminant = None
        self.pipeline.state.plate_illuminant = None
        
        # Block signals while resetting UI
        self.slider_ev.blockSignals(True)
        self.slider_yaw.blockSignals(True)
        self.slider_temp.blockSignals(True)
        self.slider_tint.blockSignals(True)
        self.chk_apply_hdri_exposure.blockSignals(True)
        
        self.slider_ev.setValue(0)
        self.slider_yaw.setValue(0)
        self.slider_temp.setValue(0)
        self.slider_tint.setValue(0)
        self.chk_apply_hdri_exposure.setChecked(False)
        
        self.lbl_ev_value.setText("0.00 EV")
        self.lbl_yaw_value.setText("0.0°")
        self.lbl_temp_value.setText("0.00")
        self.lbl_tint_value.setText("0.00")
        
        self.slider_ev.blockSignals(False)
        self.slider_yaw.blockSignals(False)
        self.slider_temp.blockSignals(False)
        self.slider_tint.blockSignals(False)
        self.chk_apply_hdri_exposure.blockSignals(False)
        
        if self.pipeline.state.hdri_array is not None:
            self._trigger_update()
            
    def on_show_refs_changed(self, state):
        self.update_viewer(use_proxy=True)

    def on_hdri_exposure_policy_changed(self, state):
        self.pipeline.state.apply_exposure_match = bool(state)
        if self.pipeline.state.hdri_array is not None:
            if not self.pipeline.state.apply_exposure_match:
                self.pipeline.state.ev_offset = 0.0
                self.pipeline.state.black_offset = 0.0
                self.slider_ev.blockSignals(True)
                self.slider_ev.setValue(0)
                self.lbl_ev_value.setText("0.00 EV")
                self.slider_ev.blockSignals(False)
            self.pipeline.process_hdri(use_proxy=False)
            self.update_viewer(reset_view=True)

    def on_protect_sun_changed(self, state):
        self.pipeline.state.protect_sun = bool(state)

    def on_sky_mode_changed(self, index):
        # Map UI to pipeline state
        self.pipeline.state.sky_mode = ["off", "top_40", "custom_rect"][self.combo_sky_mode.currentIndex()]
        self.pipeline.state.ai_awb_enable = self.chk_ai_awb.isChecked()
        
        self.pipeline.state.sky_priority = (self.pipeline.state.sky_mode == "top_40")

        if (self.pipeline.state.hdri_array is not None
                and self.pipeline.state.plate_array is not None):
            self.run_calibration()
            
    def get_active_mask(self):
        for mask in self.pipeline.state.masks:
            if mask.id == self.pipeline.state.active_mask_id:
                return mask
        return None
        
    def update_mask_list(self):
        self.list_masks.blockSignals(True)
        self.list_masks.clear()
        for mask in self.pipeline.state.masks:
            item = QtWidgets.QListWidgetItem(mask.name)
            item.setData(QtCore.Qt.UserRole, mask.id)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            self.list_masks.addItem(item)
        self.list_masks.blockSignals(False)
        
        if self.pipeline.state.masks:
            self.list_masks.setCurrentRow(0)
            self.on_mask_selected(0)
        else:
            self.on_mask_selected(-1)
        
    def add_mask(self):
        from hdri_match.core.data_models import MaskLayer
        target = "Plate" if self.combo_view_mode.currentText() == "Plate" else "HDRI"
        new_mask = MaskLayer(name=f"Mask {len(self.pipeline.state.masks) + 1}", target=target)
        self.pipeline.state.masks.append(new_mask)
        
        item = QtWidgets.QListWidgetItem(new_mask.name)
        item.setData(QtCore.Qt.UserRole, new_mask.id)
        item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
        self.list_masks.addItem(item)
        self.list_masks.setCurrentRow(len(self.pipeline.state.masks) - 1)
        
    def on_mask_name_changed(self, item):
        row = self.list_masks.row(item)
        if 0 <= row < len(self.pipeline.state.masks):
            self.pipeline.state.masks[row].name = item.text()

    def remove_mask(self):
        row = self.list_masks.currentRow()
        if row >= 0:
            self.list_masks.blockSignals(True)
            self.pipeline.state.masks.pop(row)
            self.list_masks.takeItem(row)
            self.list_masks.blockSignals(False)
            
            if self.pipeline.state.masks:
                self.list_masks.setCurrentRow(max(0, row - 1))
                self.on_mask_selected(self.list_masks.currentRow())
            else:
                self.on_mask_selected(-1)
            self._update_bg_masks()
            self._trigger_update()
            
    def deselect_mask(self):
        self.list_masks.clearSelection()
        self.list_masks.setCurrentRow(-1)
        self.on_mask_selected(-1)
            
    def on_mask_selected(self, row):
        if row >= 0 and row < len(self.pipeline.state.masks):
            self.pipeline.state.active_mask_id = self.pipeline.state.masks[row].id
            self._update_mask_ui_from_state()
            self.mask_options_widget.setEnabled(True)
            
            # Setup viewer to draw this mask
            active_mask = self.get_active_mask()
            
            # Switch viewer to match mask target
            target = getattr(active_mask, 'target', 'HDRI')
            
            # Auto-switch ONLY if triggered directly by the list
            if self.sender() == self.list_masks:
                if target == 'Plate':
                    if self.combo_view_mode.currentText() not in ["Plate", "Split Comparison", "CG Over Plate"]:
                        self.combo_view_mode.setCurrentText("Plate")
                else:
                    if self.combo_view_mode.currentText() not in ["HDRI", "Split Comparison"]:
                        self.combo_view_mode.setCurrentText("HDRI")
                        
            # Determine which viewer gets the draw mode
            current_mode = self.combo_view_mode.currentText()
            v_left = self.viewer_left
            v_right = self.viewer_right
            
            # Clear both first
            v_left.set_draw_mode(False)
            v_right.set_draw_mode(False)
            
            active_viewer = None
            if current_mode == "Split Comparison":
                if target == "Plate":
                    active_viewer = v_right
                else:
                    active_viewer = v_left
            elif current_mode in ["Plate", "CG Over Plate"] and target == "Plate":
                active_viewer = v_left
            elif current_mode in ["HDRI", "False Color"] and target == "HDRI":
                active_viewer = v_left
                
            if active_viewer and self.pipeline.state.masks_enabled:
                # Calculate normalized brush size relative to full res image
                norm_brush = 0.0
                if active_mask.shape == "Brush" and active_mask.brush_size > 0:
                    arr = self.pipeline.state.hdri_array if getattr(active_mask, 'target', 'HDRI') == 'HDRI' else self.pipeline.state.plate_array
                    if arr is not None:
                        norm_brush = active_mask.brush_size / float(arr.shape[1])
                active_viewer.set_draw_mode(True, shape=active_mask.shape, brush_size_norm=norm_brush)
                if active_mask.shape in ["Polygon", "Lasso", "Brush"]:
                    if getattr(active_mask, 'points', None):
                        active_viewer.set_mask_points_normalized(active_mask.points)
                    else:
                        active_viewer.clear_mask_rect()
                else:
                    if active_mask.rect:
                        active_viewer.set_mask_rect_normalized(active_mask.rect)
                    else:
                        active_viewer.clear_mask_rect()
            else:
                v_left.clear_mask_rect()
                v_right.clear_mask_rect()
        else:
            self.pipeline.state.active_mask_id = None
            self.mask_options_widget.setEnabled(False)
            self.viewer_left.set_draw_mode(False)
            self.viewer_left.clear_mask_rect()
            self.viewer_right.set_draw_mode(False)
            self.viewer_right.clear_mask_rect()
            
        self._update_bg_masks()
        self._trigger_update()
        
    def _update_bg_masks(self):
        view_mode = self.combo_view_mode.currentText()
        bg_masks_left = []
        bg_masks_right = []
        
        if self.pipeline.state.masks_enabled and self.right_tabs.currentIndex() == 0:
            for mask in self.pipeline.state.masks:
                target = getattr(mask, 'target', 'HDRI')
                
                norm_brush = 0.0
                if mask.shape == "Brush" and mask.brush_size > 0:
                    arr = self.pipeline.state.hdri_array if target == 'HDRI' else self.pipeline.state.plate_array
                    if arr is not None:
                        norm_brush = mask.brush_size / float(arr.shape[1])
                        
                # Filter masks for Left Viewer
                left_target = "Plate" if view_mode in ["Plate", "CG Over Plate"] else "HDRI"
                if target == left_target and mask.id != self.pipeline.state.active_mask_id and mask.rect:
                    bg_masks_left.append({'rect': mask.rect, 'shape': mask.shape, 'points': getattr(mask, 'points', None), 'brush_size_norm': norm_brush})
                    
                # Filter masks for Right Viewer (only used in Split Comparison)
                if view_mode == "Split Comparison" and target == "Plate":
                    if mask.id != self.pipeline.state.active_mask_id and mask.rect:
                        bg_masks_right.append({'rect': mask.rect, 'shape': mask.shape, 'points': getattr(mask, 'points', None), 'brush_size_norm': norm_brush})
                        
        self.viewer_left.set_bg_masks(bg_masks_left)
        self.viewer_right.set_bg_masks(bg_masks_right)

    def on_multi_mask_toggled(self, state):
        self.pipeline.state.masks_enabled = state
        if not state:
            self.viewer_left.set_draw_mode(False)
            self.viewer_left.clear_mask_rect()
            self.viewer_left.set_bg_masks([])
        else:
            self.on_mask_selected(self.list_masks.currentRow())
            self._update_bg_masks()
        self._trigger_update()

    def _update_mask_ui_from_state(self):
        mask = self.get_active_mask()
        if not mask:
            self.mask_options_widget.setEnabled(False)
            return
            
        self.chk_enable_mask.blockSignals(True)
        self.combo_mask_shape.blockSignals(True)
        self.combo_mask_target.blockSignals(True)
        self.slider_mask_feather.blockSignals(True)
        self.slider_mask_blend.blockSignals(True)
        self.slider_mask_blur.blockSignals(True)
        self.slider_mask_brush.blockSignals(True)
        
        self.spin_mask_tx.blockSignals(True)
        self.spin_mask_ty.blockSignals(True)
        self.spin_mask_scale.blockSignals(True)
        self.spin_mask_rotate.blockSignals(True)
        
        self.slider_mask_ev.blockSignals(True)
        self.slider_mask_temp.blockSignals(True)
        self.slider_mask_tint.blockSignals(True)
        self.combo_mask_mode.blockSignals(True)
        self.combo_chroma.blockSignals(True)
        self.slider_chroma_tol.blockSignals(True)
        self.combo_inpaint_backend.blockSignals(True)
        self.line_edit_inpaint_api.blockSignals(True)
        self.line_edit_inpaint_unet.blockSignals(True)
        self.line_edit_inpaint_clip.blockSignals(True)
        self.line_edit_inpaint_vae.blockSignals(True)
        self.line_edit_inpaint_ckpt.blockSignals(True)
        self.spin_inpaint_steps.blockSignals(True)
        self.spin_inpaint_cfg.blockSignals(True)
        self.chk_inpaint_rembg.blockSignals(True)
        self.chk_inpaint_key_green.blockSignals(True)
        self.spin_inpaint_denoise.blockSignals(True)
        self.chk_stencil.blockSignals(True)
        self.combo_stencil_mode.blockSignals(True)
        self.chk_stencil_invert.blockSignals(True)
        self.slider_stencil_thresh.blockSignals(True)
        
        self.chk_enable_mask.setChecked(mask.enabled)
        self.combo_mask_shape.setCurrentText(mask.shape)
        self.line_edit_mask_image.setText(getattr(mask, 'image_path', ""))
        self.combo_mask_target.setCurrentText(mask.target)
        self.slider_mask_feather.setValue(int(mask.feather))
        self.lbl_mask_feather.setText(f"{int(mask.feather)} px")
        self.slider_mask_brush.setValue(int(mask.brush_size))
        self.lbl_mask_brush.setText(f"{int(mask.brush_size)} px")
        
        self.widget_brush.setVisible(mask.shape == "Brush")
        self.widget_image_decal.setVisible(mask.shape == "Image")
        
        self.combo_mask_blend_mode.blockSignals(True)
        self.combo_mask_blend_mode.setCurrentText(getattr(mask, 'blend_mode', 'over'))
        self.combo_mask_blend_mode.blockSignals(False)
        
        self.slider_mask_blend.setValue(int(mask.blend * 100))
        self.lbl_mask_blend.setText(f"{int(mask.blend*100)} %")
        self.slider_mask_blur.setValue(int(mask.blur))
        self.lbl_mask_blur.setText(f"{int(mask.blur)} px")
        
        self.spin_mask_tx.setValue(getattr(mask, 'offset_x', 0.0))
        self.spin_mask_ty.setValue(getattr(mask, 'offset_y', 0.0))
        self.spin_mask_scale.setValue(getattr(mask, 'scale', 1.0))
        self.spin_mask_rotate.setValue(getattr(mask, 'rotation', 0.0))
        
        self.slider_mask_ev.setValue(int(mask.ev_offset * 100))
        self.lbl_mask_ev.setText(f"{mask.ev_offset:+.2f} EV")
        self.slider_mask_temp.setValue(int(mask.temperature * 100))
        self.lbl_mask_temp.setText(f"{mask.temperature:.2f}")
        self.slider_mask_tint.setValue(int(mask.tint * 100))
        self.lbl_mask_tint.setText(f"{mask.tint:.2f}")
        
        self.chk_stencil.setChecked(getattr(mask, 'stencil_enable', False))
        self.combo_stencil_mode.setCurrentText(getattr(mask, 'stencil_mode', 'Luminance'))
        self.chk_stencil_invert.setChecked(getattr(mask, 'stencil_invert', False))
        self.slider_stencil_thresh.setValue(int(getattr(mask, 'stencil_threshold', 0.5) * 100))
        self.lbl_stencil_thresh.setText(f"{getattr(mask, 'stencil_threshold', 0.5):.2f}")
        
        self.combo_mask_mode.setCurrentText(mask.mode)
        self.combo_light_type.setCurrentText("Dome Light" if getattr(mask, 'light_type', 'Dome') == 'Dome' else "Rect Light")
        self.combo_chroma.setCurrentText("Green Screen" if mask.chroma_hue < 180 else "Blue Screen")
        self.slider_chroma_tol.setValue(int(mask.chroma_tolerance * 100))
        
        self.combo_inpaint_backend.setCurrentText(mask.inpaint_backend)
        self.line_edit_inpaint_api.setText(mask.inpaint_api)
        self.line_edit_inpaint_unet.setText(mask.inpaint_unet)
        self.line_edit_inpaint_clip.setText(mask.inpaint_clip)
        self.line_edit_inpaint_vae.setText(mask.inpaint_vae)
        self.line_edit_inpaint_ckpt.setText(mask.inpaint_ckpt)
        self.line_edit_inpaint_prompt.setText(mask.inpaint_prompt)
        self.line_edit_inpaint_neg_prompt.setText(mask.inpaint_negative_prompt)
        self.spin_inpaint_steps.setValue(mask.inpaint_steps)
        self.spin_inpaint_cfg.setValue(mask.inpaint_cfg)
        self.spin_inpaint_denoise.setValue(getattr(mask, 'inpaint_denoise', 1.0))
        
        self.spin_inpaint_seed.blockSignals(True)
        self.combo_inpaint_seed_method.blockSignals(True)
        self.line_edit_model_dir.blockSignals(True)
        
        self.spin_inpaint_seed.setValue(getattr(mask, 'inpaint_seed', 0))
        self.combo_inpaint_seed_method.setCurrentText(getattr(mask, 'inpaint_seed_method', "randomize"))
        self.line_edit_model_dir.setText(getattr(mask, 'inpaint_model_dir', r"E:\ComfyUI\ComfyUI\models"))
        
        self.spin_inpaint_seed.blockSignals(False)
        self.combo_inpaint_seed_method.blockSignals(False)
        self.line_edit_model_dir.blockSignals(False)
        
        self.combo_inpaint_profile.setCurrentText(getattr(mask, 'inpaint_profile', 'Auto-Detect'))
        self.chk_inpaint_rembg.setChecked(getattr(mask, 'inpaint_rembg', False))
        self.chk_inpaint_key_green.setChecked(getattr(mask, 'inpaint_key_green', False))
        self.chk_spherical_proj.setChecked(getattr(mask, 'spherical_projection', False))
        
        use_custom_wf = getattr(mask, 'inpaint_use_custom_wf', False)
        custom_wf = getattr(mask, 'inpaint_custom_workflow', "")
        self.chk_custom_wf.setChecked(use_custom_wf)
        self.line_edit_custom_wf.setText(custom_wf)
        self.on_custom_wf_toggled()
        self.on_inpaint_backend_changed(mask.inpaint_backend)
        
        r, g, b = mask.fill_color
        r_srgb = int(max(0, min(1, r**(1/2.2))) * 255)
        g_srgb = int(max(0, min(1, g**(1/2.2))) * 255)
        b_srgb = int(max(0, min(1, b**(1/2.2))) * 255)
        color = QtGui.QColor(r_srgb, g_srgb, b_srgb)
        self.btn_mask_color.setStyleSheet(f"background-color: {color.name()}; color: {'#000' if color.lightness() > 128 else '#fff'};")
        
        self.update_mask_ui_visibility(mask.mode)
        
        self.chk_enable_mask.blockSignals(False)
        self.combo_mask_shape.blockSignals(False)
        self.combo_mask_target.blockSignals(False)
        self.slider_mask_feather.blockSignals(False)
        self.slider_mask_blend.blockSignals(False)
        self.slider_mask_blur.blockSignals(False)
        self.slider_mask_brush.blockSignals(False)
        
        self.spin_mask_tx.blockSignals(False)
        self.spin_mask_ty.blockSignals(False)
        self.spin_mask_scale.blockSignals(False)
        self.spin_mask_rotate.blockSignals(False)
        
        self.slider_mask_ev.blockSignals(False)
        self.slider_mask_temp.blockSignals(False)
        self.slider_mask_tint.blockSignals(False)
        self.combo_mask_mode.blockSignals(False)
        self.combo_light_type.blockSignals(False)
        self.combo_chroma.blockSignals(False)
        self.slider_chroma_tol.blockSignals(False)
        self.combo_inpaint_backend.blockSignals(False)
        self.line_edit_inpaint_api.blockSignals(False)
        self.line_edit_inpaint_unet.blockSignals(False)
        self.line_edit_inpaint_clip.blockSignals(False)
        self.line_edit_inpaint_vae.blockSignals(False)
        self.line_edit_inpaint_ckpt.blockSignals(False)
        self.spin_inpaint_steps.blockSignals(False)
        self.spin_inpaint_cfg.blockSignals(False)
        self.spin_inpaint_denoise.blockSignals(False)
        self.combo_inpaint_profile.blockSignals(False)
        self.chk_inpaint_rembg.blockSignals(False)
        self.chk_inpaint_key_green.blockSignals(False)
        self.chk_spherical_proj.blockSignals(False)
        self.chk_custom_wf.blockSignals(False)
        self.line_edit_custom_wf.blockSignals(False)
        self.chk_stencil.blockSignals(False)
        self.combo_stencil_mode.blockSignals(False)
        self.chk_stencil_invert.blockSignals(False)
        self.slider_stencil_thresh.blockSignals(False)

    def on_mask_stencil_changed(self, *_):
        mask = self.get_active_mask()
        if mask:
            mask.stencil_enable = self.chk_stencil.isChecked()
            mask.stencil_mode = self.combo_stencil_mode.currentText()
            mask.stencil_invert = self.chk_stencil_invert.isChecked()
            val = self.slider_stencil_thresh.value() / 100.0
            mask.stencil_threshold = val
            self.lbl_stencil_thresh.setText(f"{val:.2f}")
            self._trigger_update()

    def on_mask_blend_mode_changed(self, mode_str):
        mask = self.get_active_mask()
        if mask:
            mask.blend_mode = mode_str
            self._trigger_update()

    def on_mask_reordered(self, parent, start, end, destination, row):
        # QListWidget drag and drop completed, update self.pipeline.state.masks order
        items = [self.list_masks.item(i) for i in range(self.list_masks.count())]
        new_masks = []
        for item in items:
            mask_id = item.data(QtCore.Qt.UserRole)
            for m in self.pipeline.state.masks:
                if m.id == mask_id:
                    new_masks.append(m)
                    break
        self.pipeline.state.masks = new_masks
        self._trigger_update()

    def on_mask_mode_changed(self, mode_str):
        mask = self.get_active_mask()
        if mask:
            mask.mode = mode_str
            self.update_mask_ui_visibility(mode_str)
            self._trigger_update()
            
    def on_mask_light_type_changed(self, ltype_str):
        mask = self.get_active_mask()
        if mask:
            mask.light_type = "Dome" if "Dome" in ltype_str else "Rect"
            
    def update_mask_ui_visibility(self, mode_str):
        if mode_str == "Grade":
            self.widget_grade.show()
            self.btn_mask_color.hide()
            self.chroma_widget.hide()
            self.inpaint_widget.hide()
        elif mode_str == "Solid Fill":
            self.widget_grade.hide()
            self.btn_mask_color.show()
            self.chroma_widget.hide()
            self.inpaint_widget.hide()
        elif mode_str == "Chroma Replace":
            self.widget_grade.hide()
            self.btn_mask_color.show()
            self.chroma_widget.show()
            self.inpaint_widget.hide()
        elif mode_str == "AI Inpaint":
            self.widget_grade.hide()
            self.btn_mask_color.hide()
            self.chroma_widget.hide()
            self.inpaint_widget.show()
            
    def on_mask_color_clicked(self):
        mask = self.get_active_mask()
        if mask:
            r, g, b = mask.fill_color
            r_srgb = int(max(0, min(1, r**(1/2.2))) * 255)
            g_srgb = int(max(0, min(1, g**(1/2.2))) * 255)
            b_srgb = int(max(0, min(1, b**(1/2.2))) * 255)
            initial_color = QtGui.QColor(r_srgb, g_srgb, b_srgb)
            
            color = QtWidgets.QColorDialog.getColor(initial_color, self, "Select Fill Color")
            if color.isValid():
                r_lin = (color.red() / 255.0) ** 2.2
                g_lin = (color.green() / 255.0) ** 2.2
                b_lin = (color.blue() / 255.0) ** 2.2
                mask.fill_color = (r_lin, g_lin, b_lin)
                
                self.btn_mask_color.setStyleSheet(f"background-color: {color.name()}; color: {'#000' if color.lightness() > 128 else '#fff'};")
                self._trigger_update()
                
    def on_mask_chroma_changed(self, *_):
        mask = self.get_active_mask()
        if mask:
            target = self.combo_chroma.currentText()
            mask.chroma_hue = 120.0 if target == "Green Screen" else 240.0
            mask.chroma_tolerance = self.slider_chroma_tol.value() / 100.0
            self._trigger_update()

    def on_inpaint_backend_changed(self, text):
        mask = self.get_active_mask()
        if mask:
            mask.inpaint_backend = text
            
        if "Cloud" in text or "Serverless" in text or "Free" in text or "GenAI" in text:
            self.api_label.setText("API Key:")
            if self.line_edit_inpaint_api.text() == "http://127.0.0.1:8188":
                self.line_edit_inpaint_api.setText("")
            self.line_edit_inpaint_unet.setEnabled(False)
            self.line_edit_inpaint_clip.setEnabled(False)
            self.line_edit_inpaint_vae.setEnabled(False)
            self.line_edit_inpaint_ckpt.setEnabled(False)
            self.btn_browse_unet.setEnabled(False)
            self.btn_browse_clip.setEnabled(False)
            self.btn_browse_vae.setEnabled(False)
            self.btn_browse_ckpt.setEnabled(False)
            self.line_edit_model_dir.setEnabled(False)
            self.btn_browse_model_dir.setEnabled(False)
        else:
            self.api_label.setText("API URL:")
            if not self.line_edit_inpaint_api.text():
                self.line_edit_inpaint_api.setText("http://127.0.0.1:8188")
            
            is_custom = self.chk_custom_wf.isChecked()
            self.line_edit_inpaint_unet.setEnabled(not is_custom)
            self.line_edit_inpaint_clip.setEnabled(not is_custom)
            self.line_edit_inpaint_vae.setEnabled(not is_custom)
            self.line_edit_inpaint_ckpt.setEnabled(not is_custom)
            self.btn_browse_unet.setEnabled(not is_custom)
            self.btn_browse_clip.setEnabled(not is_custom)
            self.btn_browse_vae.setEnabled(not is_custom)
            self.btn_browse_ckpt.setEnabled(not is_custom)
            self.line_edit_model_dir.setEnabled(True)
            self.btn_browse_model_dir.setEnabled(True)
            
    def on_inpaint_profile_changed(self, text):
        self.combo_inpaint_profile.blockSignals(True)
        if text == "Flux Dev":
            self.spin_inpaint_steps.setValue(20)
            self.spin_inpaint_cfg.setValue(3.5)
            self.line_edit_inpaint_unet.setText("flux1-dev.safetensors")
            self.line_edit_inpaint_clip.setText("t5xxl_fp8_e4m3fn.safetensors")
            self.line_edit_inpaint_vae.setText("ae.safetensors")
            self.line_edit_inpaint_ckpt.setText("")
        elif text == "Flux Schnell/Klein":
            self.spin_inpaint_steps.setValue(4)
            self.spin_inpaint_cfg.setValue(1.5)
            self.line_edit_inpaint_unet.setText("")
            self.line_edit_inpaint_clip.setText("")
            self.line_edit_inpaint_vae.setText("")
            self.line_edit_inpaint_ckpt.setText("flux-2-klein-9b-fp8mixed.safetensors")
        elif text == "SDXL Turbo":
            self.spin_inpaint_steps.setValue(4)
            self.spin_inpaint_cfg.setValue(1.5)
            self.line_edit_inpaint_unet.setText("")
            self.line_edit_inpaint_clip.setText("")
            self.line_edit_inpaint_vae.setText("")
            self.line_edit_inpaint_ckpt.setText("sd_xl_turbo_1.0_fp16.safetensors")
        elif text == "Z-Image Turbo":
            self.spin_inpaint_steps.setValue(8)
            self.spin_inpaint_cfg.setValue(1.5)
            self.line_edit_inpaint_unet.setText("z_image_turbo_bf16.safetensors")
            self.line_edit_inpaint_clip.setText("qwen_3_4b.safetensors")
            self.line_edit_inpaint_vae.setText("ae.safetensors")
            self.line_edit_inpaint_ckpt.setText("")
        elif text == "LTX-2":
            self.spin_inpaint_steps.setValue(20)
            self.spin_inpaint_cfg.setValue(3.0)
            self.line_edit_inpaint_unet.setText("")
            self.line_edit_inpaint_clip.setText("")
            self.line_edit_inpaint_vae.setText("")
            self.line_edit_inpaint_ckpt.setText("ltx2.safetensors")
        elif text == "Standard SD/SDXL":
            self.spin_inpaint_steps.setValue(20)
            self.spin_inpaint_cfg.setValue(7.0)
            self.line_edit_inpaint_unet.setText("")
            self.line_edit_inpaint_clip.setText("")
            self.line_edit_inpaint_vae.setText("")
            self.line_edit_inpaint_ckpt.setText("sd_xl_base_1.0.safetensors")
        self.combo_inpaint_profile.blockSignals(False)
        self.on_inpaint_ui_changed()
            
    def on_browse_model_dir_clicked(self):
        start_dir = self.line_edit_model_dir.text()
        import os
        if not os.path.exists(start_dir):
            start_dir = ""
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select ComfyUI Models Directory", start_dir
        )
        if dir_path:
            self.line_edit_model_dir.setText(dir_path.replace("\\", "/"))

    def _browse_model(self, line_edit, subfolder):
        import os
        base_dir = self.line_edit_model_dir.text()
        start_dir = os.path.join(base_dir, subfolder).replace("\\", "/")
        if not os.path.exists(start_dir):
            start_dir = base_dir.replace("\\", "/")
            
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Select {subfolder.upper()} Model", start_dir, "Safetensors (*.safetensors);;All Files (*.*)"
        )
        if file_path:
            rel_path = os.path.relpath(file_path, start_dir)
            if rel_path.startswith(".."):
                rel_path = os.path.basename(file_path)
            line_edit.setText(rel_path.replace("\\", "/"))
            
    def on_browse_unet_clicked(self):
        self._browse_model(self.line_edit_inpaint_unet, "unet")
        
    def on_browse_clip_clicked(self):
        self._browse_model(self.line_edit_inpaint_clip, "clip")
        
    def on_browse_vae_clicked(self):
        self._browse_model(self.line_edit_inpaint_vae, "vae")
        
    def on_browse_ckpt_clicked(self):
        self._browse_model(self.line_edit_inpaint_ckpt, "checkpoints")
        
    def on_browse_upscaler_clicked(self):
        self._browse_model(self.line_edit_inpaint_upscaler, "upscale_models")
        
    def on_custom_wf_toggled(self):
        is_custom = self.chk_custom_wf.isChecked()
        self.line_edit_custom_wf.setEnabled(is_custom)
        self.btn_browse_custom_wf.setEnabled(is_custom)
        
        # Disable standard model inputs if using custom workflow
        self.line_edit_inpaint_unet.setEnabled(not is_custom)
        self.btn_browse_unet.setEnabled(not is_custom)
        self.line_edit_inpaint_clip.setEnabled(not is_custom)
        self.btn_browse_clip.setEnabled(not is_custom)
        self.line_edit_inpaint_vae.setEnabled(not is_custom)
        self.btn_browse_vae.setEnabled(not is_custom)
        self.line_edit_inpaint_ckpt.setEnabled(not is_custom)
        self.btn_browse_ckpt.setEnabled(not is_custom)
        self.line_edit_inpaint_upscaler.setEnabled(not is_custom)
        self.btn_browse_upscaler.setEnabled(not is_custom)
        
    def on_theme_changed(self, theme_name):
        from hdri_match.ui.theme import get_theme
        self.setStyleSheet(get_theme(theme_name))
        
    def on_browse_custom_wf_clicked(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select ComfyUI API JSON Workflow", "", "JSON Files (*.json);;All Files (*.*)"
        )
        if file_path:
            # Validate workflow immediately
            import json
            try:
                with open(file_path, 'r') as f:
                    wf = json.load(f)
                
                # Check models against ComfyUI API
                from hdri_match.ml.comfyui_bridge import ComfyUIBridge
                bridge = ComfyUIBridge(api_url=self.line_edit_inpaint_api.text(), backend="ComfyUI")
                is_valid, errors = bridge.validate_custom_workflow(wf)
                
                if not is_valid:
                    error_msg = "\n".join(errors)
                    QtWidgets.QMessageBox.warning(self, "Missing Models", f"The following models required by your workflow are missing from your ComfyUI server:\n\n{error_msg}")
                    # Allow them to keep it selected anyway, but they've been warned
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Workflow Error", f"Failed to parse workflow: {e}")
                
            self.line_edit_custom_wf.setText(file_path.replace("\\", "/"))
            self.on_inpaint_ui_changed()
                
    def on_run_inpaint_clicked(self):
        mask = self.get_active_mask()
        if not mask or (not mask.rect and not mask.points):
            QtWidgets.QMessageBox.warning(self, "No Mask", "Please draw a mask over the area you want to inpaint.")
            return
            
        prompt = self.line_edit_inpaint_prompt.text()
        neg_prompt = self.line_edit_inpaint_neg_prompt.text()
        api_url = self.line_edit_inpaint_api.text()
        backend = self.combo_inpaint_backend.currentText()
        unet = self.line_edit_inpaint_unet.text()
        clip = self.line_edit_inpaint_clip.text()
        vae = self.line_edit_inpaint_vae.text()
        ckpt = self.line_edit_inpaint_ckpt.text()
        upscaler = self.line_edit_inpaint_upscaler.text()
        seed = self.spin_inpaint_seed.value()
        
        mask.inpaint_prompt = prompt
        mask.inpaint_negative_prompt = neg_prompt
        mask.inpaint_backend = backend
        mask.inpaint_api = api_url
        mask.inpaint_unet = unet
        mask.inpaint_clip = clip
        mask.inpaint_vae = vae
        mask.inpaint_ckpt = ckpt
        mask.inpaint_upscaler = upscaler
        mask.inpaint_seed = seed
        mask.inpaint_steps = self.spin_inpaint_steps.value()
        mask.inpaint_cfg = self.spin_inpaint_cfg.value()
        mask.inpaint_denoise = self.spin_inpaint_denoise.value()
        mask.inpaint_rembg = self.chk_inpaint_rembg.isChecked()
        mask.inpaint_key_green = self.chk_inpaint_key_green.isChecked()
        mask.spherical_projection = self.chk_spherical_proj.isChecked()
        mask.inpaint_use_custom_wf = self.chk_custom_wf.isChecked()
        mask.inpaint_custom_workflow = self.line_edit_custom_wf.text()
        mask.inpaint_seed = self.spin_inpaint_seed.value()
        mask.inpaint_seed_method = self.combo_inpaint_seed_method.currentText()
        mask.inpaint_model_dir = self.line_edit_model_dir.text()
        
        # Process seed method before running
        import numpy as np
        seed_method = self.combo_inpaint_seed_method.currentText()
        if seed_method == "randomize":
            new_seed = int(np.random.randint(0, 2147483647))
            self.spin_inpaint_seed.setValue(new_seed)
        elif seed_method == "increment":
            new_seed = (self.spin_inpaint_seed.value() + 1) % 2147483647
            self.spin_inpaint_seed.setValue(new_seed)
        elif seed_method == "decrement":
            new_seed = (self.spin_inpaint_seed.value() - 1) % 2147483647
            self.spin_inpaint_seed.setValue(new_seed)
            
        mask.inpaint_seed = self.spin_inpaint_seed.value()
        mask.inpaint_seed_method = seed_method
        
        mask.is_inpainted = True
        
        error = self.pipeline.run_ai_inpaint(mask)
        
        # Explicitly process the target array so the new patch is rendered into the image cache
        if getattr(mask, 'target', 'HDRI') == 'Plate':
            self.pipeline.process_plate(use_proxy=True)
        else:
            self.pipeline.process_hdri(use_proxy=True)
            
        self._trigger_update()
        
        if error:
            QtWidgets.QMessageBox.warning(self, "AI Inpaint Error", f"The AI Server returned an error:\n\n{error}")

    def on_inpaint_ui_changed(self, *args):
        mask = self.get_active_mask()
        if mask:
            mask.inpaint_prompt = self.line_edit_inpaint_prompt.text()
            mask.inpaint_negative_prompt = self.line_edit_inpaint_neg_prompt.text()
            mask.inpaint_api = self.line_edit_inpaint_api.text()
            mask.inpaint_unet = self.line_edit_inpaint_unet.text()
            mask.inpaint_clip = self.line_edit_inpaint_clip.text()
            mask.inpaint_vae = self.line_edit_inpaint_vae.text()
            mask.inpaint_ckpt = self.line_edit_inpaint_ckpt.text()
            mask.inpaint_upscaler = self.line_edit_inpaint_upscaler.text()
            mask.inpaint_steps = self.spin_inpaint_steps.value()
            mask.inpaint_cfg = self.spin_inpaint_cfg.value()
            mask.inpaint_denoise = self.spin_inpaint_denoise.value()
            mask.inpaint_seed = self.spin_inpaint_seed.value()
            mask.inpaint_seed_method = self.combo_inpaint_seed_method.currentText()
            mask.inpaint_profile = self.combo_inpaint_profile.currentText()
            mask.inpaint_rembg = self.chk_inpaint_rembg.isChecked()
            mask.inpaint_key_green = self.chk_inpaint_key_green.isChecked()
            mask.spherical_projection = self.chk_spherical_proj.isChecked()
            mask.inpaint_use_custom_wf = self.chk_custom_wf.isChecked()
            mask.inpaint_custom_workflow = self.line_edit_custom_wf.text()
            mask.inpaint_model_dir = self.line_edit_model_dir.text()

    def open_prompt_editor(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("AI Inpaint Prompts")
        dialog.resize(500, 400)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        layout.addWidget(QtWidgets.QLabel("Positive Prompt:"))
        pos_edit = QtWidgets.QPlainTextEdit()
        pos_edit.setPlainText(self.line_edit_inpaint_prompt.text())
        layout.addWidget(pos_edit)
        
        layout.addWidget(QtWidgets.QLabel("Negative Prompt:"))
        neg_edit = QtWidgets.QPlainTextEdit()
        neg_edit.setPlainText(self.line_edit_inpaint_neg_prompt.text())
        layout.addWidget(neg_edit)
        
        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)
        
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.line_edit_inpaint_prompt.setText(pos_edit.toPlainText().replace('\n', ' '))
            self.line_edit_inpaint_neg_prompt.setText(neg_edit.toPlainText().replace('\n', ' '))

    def on_enable_mask_changed(self, state):
        mask = self.get_active_mask()
        if mask:
            mask.enabled = bool(state)
            self._trigger_update()
            
    def on_mask_shape_changed(self, shape):
        mask = self.get_active_mask()
        if mask:
            mask.shape = shape
            self.widget_brush.setVisible(shape == "Brush")
            self.widget_image_decal.setVisible(shape == "Image")
            
            norm_brush = 0.0
            if shape == "Brush" and mask.brush_size > 0:
                arr = self.pipeline.state.hdri_array if getattr(mask, 'target', 'HDRI') == 'HDRI' else self.pipeline.state.plate_array
                if arr is not None:
                    norm_brush = mask.brush_size / float(arr.shape[1])
                    
            if self.viewer_left._draw_mode:
                self.viewer_left.set_draw_mode(True, shape=shape, brush_size_norm=norm_brush)
            if self.viewer_right._draw_mode:
                self.viewer_right.set_draw_mode(True, shape=shape, brush_size_norm=norm_brush)
                
            self._trigger_update()
            
    def on_mask_target_changed(self, target_str):
        mask = self.get_active_mask()
        if mask:
            mask.target = target_str
            if target_str == "Plate":
                self.combo_view_mode.setCurrentText("Plate")
            else:
                if self.combo_view_mode.currentText() == "Plate":
                    self.combo_view_mode.setCurrentText("HDRI")
            self._update_bg_masks()
            self._trigger_update()
            
    def on_mask_feather_changed(self, value):
        mask = self.get_active_mask()
        if mask:
            mask.feather = float(value)
            self.lbl_mask_feather.setText(f"{value} px")
            self._trigger_update()
        
    def on_mask_blend_changed(self, value):
        mask = self.get_active_mask()
        if mask:
            mask.blend = value / 100.0
            self.lbl_mask_blend.setText(f"{value} %")
            self._trigger_update()
        
    def on_mask_blur_changed(self, value):
        mask = self.get_active_mask()
        if mask:
            mask.blur = float(value)
            self.lbl_mask_blur.setText(f"{value} px")
            self._trigger_update()
            
    def on_mask_brush_changed(self, value):
        mask = self.get_active_mask()
        if mask:
            mask.brush_size = float(value)
            self.lbl_mask_brush.setText(f"{value} px")
            
            norm_brush = 0.0
            if mask.shape == "Brush" and mask.brush_size > 0:
                arr = self.pipeline.state.hdri_array if getattr(mask, 'target', 'HDRI') == 'HDRI' else self.pipeline.state.plate_array
                if arr is not None:
                    norm_brush = mask.brush_size / float(arr.shape[1])
            
            if self.viewer_left._draw_mode:
                self.viewer_left.set_draw_mode(True, shape=mask.shape, brush_size_norm=norm_brush)
                if hasattr(self.viewer_left, '_mask_path_item') and self.viewer_left._mask_path_item.isVisible():
                    # Refresh visual
                    self.viewer_left.set_mask_points_normalized(mask.points)
            if self.viewer_right._draw_mode:
                self.viewer_right.set_draw_mode(True, shape=mask.shape, brush_size_norm=norm_brush)
                if hasattr(self.viewer_right, '_mask_path_item') and self.viewer_right._mask_path_item.isVisible():
                    self.viewer_right.set_mask_points_normalized(mask.points)
                    
            self._trigger_update()

    def on_transform_drag_started(self):
        mask = self.get_active_mask()
        if mask:
            self._drag_start_tx = getattr(mask, 'offset_x', 0.0)
            self._drag_start_ty = getattr(mask, 'offset_y', 0.0)
            self._drag_start_scale = getattr(mask, 'scale', 1.0)
            self._drag_start_rotate = getattr(mask, 'rotation', 0.0)

    def on_transform_dragged(self, mode, dx, dy):
        mask = self.get_active_mask()
        if mask and hasattr(self, '_drag_start_tx'):
            if mode == "Translate":
                self.spin_mask_tx.setValue(self._drag_start_tx + dx)
                self.spin_mask_ty.setValue(self._drag_start_ty + dy)
            elif mode == "Scale":
                delta = (dx - dy) * 0.005
                self.spin_mask_scale.setValue(max(0.01, self._drag_start_scale + delta))
            elif mode == "Rotate":
                delta = (dx - dy) * 0.5
                self.spin_mask_rotate.setValue(self._drag_start_rotate + delta)

    def on_transform_drag_started(self):
        mask = self.get_active_mask()
        if mask:
            self._drag_start_tx = getattr(mask, 'offset_x', 0.0)
            self._drag_start_ty = getattr(mask, 'offset_y', 0.0)
            self._drag_start_scale = getattr(mask, 'scale', 1.0)
            self._drag_start_rotate = getattr(mask, 'rotation', 0.0)

    def on_transform_dragged(self, mode, dx, dy):
        mask = self.get_active_mask()
        if mask and hasattr(self, '_drag_start_tx'):
            if mode == "Translate":
                self.spin_mask_tx.setValue(self._drag_start_tx + dx)
                self.spin_mask_ty.setValue(self._drag_start_ty + dy)
            elif mode == "Scale":
                delta = (dx - dy) * 0.005
                self.spin_mask_scale.setValue(max(0.01, self._drag_start_scale + delta))
            elif mode == "Rotate":
                delta = (dx - dy) * 0.5
                self.spin_mask_rotate.setValue(self._drag_start_rotate + delta)

    def on_mask_transform_changed(self):
        mask = self.get_active_mask()
        if mask:
            mask.offset_x = self.spin_mask_tx.value()
            mask.offset_y = self.spin_mask_ty.value()
            mask.scale = self.spin_mask_scale.value()
            mask.rotation = self.spin_mask_rotate.value()
            self._trigger_update()

    def on_transform_drag_started(self):
        mask = self.get_active_mask()
        if mask:
            self._drag_start_tx = getattr(mask, 'offset_x', 0.0)
            self._drag_start_ty = getattr(mask, 'offset_y', 0.0)
            self._drag_start_scale = getattr(mask, 'scale', 1.0)
            self._drag_start_rotate = getattr(mask, 'rotation', 0.0)

    def on_transform_dragged(self, mode, dx, dy):
        mask = self.get_active_mask()
        if mask and hasattr(self, '_drag_start_tx'):
            if mode == "Translate":
                self.spin_mask_tx.setValue(self._drag_start_tx + dx)
                self.spin_mask_ty.setValue(self._drag_start_ty + dy)
            elif mode == "Scale":
                delta = (dx - dy) * 0.005
                self.spin_mask_scale.setValue(max(0.01, self._drag_start_scale + delta))
            elif mode == "Rotate":
                delta = (dx - dy) * 0.5
                self.spin_mask_rotate.setValue(self._drag_start_rotate + delta)

    def on_mask_transform_changed(self):
        mask = self.get_active_mask()
        if mask:
            mask.offset_x = self.spin_mask_tx.value()
            mask.offset_y = self.spin_mask_ty.value()
            mask.scale = self.spin_mask_scale.value()
            mask.rotation = self.spin_mask_rotate.value()
            self._trigger_update()

    def on_browse_mask_image_clicked(self):
        mask = self.get_active_mask()
        if not mask:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Image Decal", "", "Images (*.png *.jpg *.jpeg *.exr)")
        if path:
            self.line_edit_mask_image.setText(path)
            mask.image_path = path
            self._trigger_update()

    def on_mask_ev_slider_changed(self, value):
        mask = self.get_active_mask()
        if mask:
            mask.ev_offset = value / 100.0
            self.lbl_mask_ev.setText(f"{mask.ev_offset:+.2f} EV")
            self._trigger_update()
        
    def on_mask_color_slider_changed(self):
        mask = self.get_active_mask()
        if mask:
            mask.temperature = self.slider_mask_temp.value() / 100.0
            mask.tint = self.slider_mask_tint.value() / 100.0
            self.lbl_mask_temp.setText(f"{mask.temperature:.2f}")
            self.lbl_mask_tint.setText(f"{mask.tint:.2f}")
            self._trigger_update()
        
    def on_ground_toggled(self, state):
        self.pipeline.state.horizon_enable = bool(state)
        self._trigger_update()
        
    def on_horizon_slider_changed(self):
        h = self.slider_ground_height.value() / 100.0
        f = self.slider_ground_feather.value() / 100.0
        
        s_ev = self.slider_sky_ev.value() / 100.0
        s_t = self.slider_sky_temp.value() / 100.0
        s_ti = self.slider_sky_tint.value() / 100.0
        s_desat = self.slider_sky_desat.value() / 100.0
        
        g_ev = self.slider_ground_ev.value() / 100.0
        g_t = self.slider_ground_temp.value() / 100.0
        g_ti = self.slider_ground_tint.value() / 100.0
        desat = self.slider_ground_desat.value() / 100.0
        
        self.lbl_ground_height.setText(f"{h:.2f}")
        self.lbl_ground_feather.setText(f"{f:.2f}")
        
        self.lbl_sky_ev.setText(f"{s_ev:+.2f} EV")
        self.lbl_sky_temp.setText(f"{s_t:.2f}")
        self.lbl_sky_tint.setText(f"{s_ti:.2f}")
        self.lbl_sky_desat.setText(f"{int(s_desat*100)} %")
        
        self.lbl_ground_ev.setText(f"{g_ev:+.2f} EV")
        self.lbl_ground_temp.setText(f"{g_t:.2f}")
        self.lbl_ground_tint.setText(f"{g_ti:.2f}")
        self.lbl_ground_desat.setText(f"{int(desat*100)} %")
        
        self.pipeline.state.horizon_height = h
        self.pipeline.state.horizon_feather = f
        
        self.pipeline.state.sky_ev_offset = s_ev
        self.pipeline.state.sky_temperature = s_t
        self.pipeline.state.sky_tint = s_ti
        self.pipeline.state.sky_desat = s_desat
        
        self.pipeline.state.ground_ev_offset = g_ev
        self.pipeline.state.ground_temperature = g_t
        self.pipeline.state.ground_tint = g_ti
        self.pipeline.state.ground_desat = desat
        
        self._trigger_update()

    def on_softclip_toggled(self, state):
        self.pipeline.state.softclip_enable = bool(state)
        self._trigger_update()
        
    def on_softclip_slider_changed(self):
        t = self.slider_softclip_thresh.value() / 10.0
        r = self.slider_softclip_rolloff.value() / 10.0
        
        self.lbl_softclip_thresh.setText(f"{t:.1f} EV")
        self.lbl_softclip_rolloff.setText(f"{r:.1f} EV")
        
        self.pipeline.state.softclip_threshold = t
        self.pipeline.state.softclip_rolloff = r
        
        self._trigger_update()

    def on_mask_drawn(self):
        active_mask = self.get_active_mask()
        if active_mask:
            viewer = self.viewer_left
            if self.combo_view_mode.currentText() == "Split Comparison" and getattr(active_mask, 'target', 'HDRI') == 'Plate':
                viewer = self.viewer_right
                
            if active_mask.shape in ["Polygon", "Lasso", "Brush"]:
                active_mask.points = viewer.get_mask_points_normalized()
                active_mask.rect = viewer.get_mask_rect_normalized()
            else:
                active_mask.rect = viewer.get_mask_rect_normalized()
                
            # Only invalidate the target image pipeline if the mask actually affects pixel values
            has_effect = False
            if active_mask.mode == "AI Inpaint":
                if getattr(active_mask, 'inpainted_patch', None) is not None:
                    has_effect = True
            elif active_mask.mode in ["Solid Fill", "Chroma Replace"]:
                has_effect = True
            elif abs(active_mask.ev_offset) > 1e-8 or abs(active_mask.temperature) > 1e-4 or abs(active_mask.tint) > 1e-4 or active_mask.blur > 1e-4:
                has_effect = True
                
            if getattr(active_mask, 'target', 'HDRI') == 'Plate':
                self._trigger_update(hdri=False, plate=has_effect, cg=False)
            else:
                self._trigger_update(hdri=has_effect, plate=False, cg=False)

    # --- Sun Relighting Handlers ---
    def on_sun_relight_toggled(self, state):
        is_enabled = (state == QtCore.Qt.Checked)
        self.pipeline.state.sun_relight_enabled = is_enabled
        if not is_enabled:
            self.btn_interactive_sun.setChecked(False)
            self.viewer_left.set_sun_mode(False)
            
        if is_enabled and not self.pipeline.state.sun_auto_detected:
            self.on_auto_detect_sun()
        else:
            self._trigger_update()

    def on_sun_relight_options_changed(self):
        self.pipeline.state.sun_radius = self.slider_sun_radius.value() / 1000.0
        self.pipeline.state.sun_feather = self.slider_sun_feather.value() / 1000.0
        if self.pipeline.state.sun_relight_enabled:
            self._trigger_update()

    def on_auto_detect_sun(self):
        if self.pipeline.state.hdri_array is None:
            return
        from hdri_match.analysis.sun_relighter import SunRelighter
        u, v, _ = SunRelighter.detect_sun(self.pipeline.state.hdri_array)
        
        # Reset source and target to original position
        self.pipeline.state.sun_source_u = u
        self.pipeline.state.sun_source_v = v
        self.pipeline.state.sun_target_u = u
        self.pipeline.state.sun_target_v = v
        self.pipeline.state.sun_auto_detected = True
        
        self.viewer_left.set_sun_positions(u, v, u, v)
        if self.pipeline.state.sun_relight_enabled:
            self._trigger_update()

    def on_interactive_sun_toggled(self, checked):
        if checked:
            # Turn off other interactive modes
            self.viewer_left.set_draw_mode(False)
            self.btn_pick_wb.setChecked(False)
            self.viewer_left.set_sun_mode(True)
            
            # Ensure we have a sun position
            if not self.pipeline.state.sun_auto_detected:
                self.on_auto_detect_sun()
            else:
                self.viewer_left.set_sun_positions(
                    self.pipeline.state.sun_source_u,
                    self.pipeline.state.sun_source_v,
                    self.pipeline.state.sun_target_u,
                    self.pipeline.state.sun_target_v
                )
        else:
            self.viewer_left.set_sun_mode(False)

    def on_sun_moved(self, target_u, target_v):
        self.pipeline.state.sun_target_u = target_u
        self.pipeline.state.sun_target_v = target_v
        
        if self.pipeline.state.sun_relight_enabled:
            self._trigger_update()

    def invalidate_playback_cache(self):
        """Explicitly wipe the RAM frame buffer when processing parameters change."""
        if hasattr(self, '_playback_cache'):
            self._playback_cache.clear()
        if hasattr(self, 'slider_timeline'):
            self.slider_timeline.set_cached_frames([])

    def _trigger_update(self, hdri=True, plate=True, cg=True):
        # Only invalidate the frame cache when the playback timer is NOT running.
        # During active playback the cache is sacred — only the user changing a
        # parameter while paused should wipe it.
        if not getattr(self._playback_timer, 'isActive', lambda: False)():
            self.invalidate_playback_cache()
        self._dirty_hdri = getattr(self, '_dirty_hdri', False) or hdri
        self._dirty_plate = getattr(self, '_dirty_plate', False) or plate
        self._dirty_cg = getattr(self, '_dirty_cg', False) or cg
        if not self._update_timer.isActive():
            self._update_timer.start(33) # ~30fps
        
        if hasattr(self, '_viewport_3d') and self._viewport_3d and self._viewport_3d.isVisible():
            self._viewport_3d.viewport.update()

    def _do_deferred_update(self):
        # During active playback the playback tick owns all frame display.
        # Skip the deferred pipeline update entirely to avoid overwriting cached frames.
        if self._playback_timer.isActive():
            return

        use_proxy = True # Always use proxy (working resolution) for UI
        do_hdri = getattr(self, '_dirty_hdri', True)
        do_plate = getattr(self, '_dirty_plate', True)
        do_cg = getattr(self, '_dirty_cg', True)
        
        self._dirty_hdri = False
        self._dirty_plate = False
        self._dirty_cg = False
        
        current_view = self.combo_view_mode.currentText()
        if current_view not in ("HDRI", "Split Comparison"):
            self.pipeline.state.plate_mask_rect = self.viewer_left.get_mask_rect_normalized()
        else:
            self.pipeline.state.plate_mask_rect = None

        if do_hdri and self.pipeline.state.hdri_array is not None:
            self.pipeline.process_hdri(use_proxy=use_proxy)
        if do_plate and self.pipeline.state.plate_array is not None:
            self.pipeline.process_plate(use_proxy=use_proxy)
        if do_cg and self.pipeline.state.cg_lights:
            self.pipeline.reconstruct_cg_beauty(use_proxy=use_proxy)
        self.update_viewer(use_proxy=use_proxy)

    def on_ev_slider_changed(self, value):
        ev = value / 100.0
        self.pipeline.state.ev_offset = ev
        self.lbl_ev_value.setText(f"{ev:+.2f} EV")
        
        if not self.pipeline.state.apply_exposure_match and ev != 0.0:
            self.chk_apply_hdri_exposure.blockSignals(True)
            self.chk_apply_hdri_exposure.setChecked(True)
            self.pipeline.state.apply_exposure_match = True
            self.chk_apply_hdri_exposure.blockSignals(False)

        # When dragging EV, we update the viewer's visual EV offset
        # without doing a full 32-bit math pipeline rebuild for speed.
        if not self.pipeline.state.apply_exposure_match:
            self.viewer_left.set_ev_offset(ev)
            self.viewer_right.set_ev_offset(ev)
        else:
            self.viewer_left.set_ev_offset(0.0)
            self.viewer_right.set_ev_offset(0.0)
            self._trigger_update(hdri=True, plate=False, cg=False)

    def on_yaw_slider_changed(self, value):
        val = value / 10.0
        self.pipeline.state.hdri_yaw = val
        self.viewer_left._mask_yaw = val
        self.lbl_yaw_value.setText(f"{val:.1f}°")
        
        # Shift the active draw rect on screen so it stays pinned to the underlying image
        active_mask = self.get_active_mask()
        if active_mask and active_mask.rect:
            self.viewer_left.set_mask_rect_normalized(active_mask.rect)
            
        self._update_bg_masks()
        self._trigger_update(hdri=True, plate=False, cg=False)
            
    def on_color_slider_changed(self):
        temp = self.slider_temp.value() / 100.0
        tint = self.slider_tint.value() / 100.0
        self.lbl_temp_value.setText(f"{temp:.2f}")
        self.lbl_tint_value.setText(f"{tint:.2f}")
        
        self.pipeline.state.temperature = temp
        self.pipeline.state.tint = tint
        self._trigger_update(hdri=True, plate=False, cg=False)
            
    def on_slider_released(self):
        pass # No need to trigger full update, always uses working resolution
            
    def on_plate_ev_slider_changed(self, value):
        ev = value / 100.0
        self.lbl_plate_ev_value.setText(f"{ev:.2f} EV")
        if self.pipeline.state.plate_array is not None:
            self.pipeline.state.plate_ev_offset = ev
            self._trigger_update(hdri=False, plate=True, cg=False)
            
    def on_plate_sat_slider_changed(self, value):
        sat = value / 100.0
        self.lbl_plate_sat_value.setText(f"{sat:.2f}")
        if self.pipeline.state.plate_array is not None:
            self.pipeline.state.plate_saturation = sat
            self._trigger_update(hdri=False, plate=True, cg=False)

    def on_plate_temp_slider_changed(self, value):
        temp = value / 100.0
        self.lbl_plate_temp_value.setText(f"{temp:.2f}")
        if self.pipeline.state.plate_array is not None:
            self.pipeline.state.plate_temperature = temp
            self._trigger_update(hdri=False, plate=True, cg=False)
            
    def on_plate_tint_slider_changed(self, value):
        tint = value / 100.0
        self.lbl_plate_tint_value.setText(f"{tint:.2f}")
        if self.pipeline.state.plate_array is not None:
            self.pipeline.state.plate_tint = tint
            self._trigger_update(hdri=False, plate=True, cg=False)
    
    def on_plate_slider_released(self):
        if self.pipeline.state.plate_array is not None:
            self._trigger_plate_update(use_proxy=False)

    def on_plate_group_toggled(self, state):
        self.pipeline.state.plate_adjustments_enabled = state
        self._trigger_plate_update(use_proxy=False)
    
    def on_cg_shadow_slider_changed(self, value):
        shadow = value / 100.0
        self.lbl_cg_shadow.setText(f"{shadow:.2f}")
        self.pipeline.state.cg_comp_shadow = shadow
        self._trigger_update(hdri=False, plate=False, cg=False)

    def on_cg_refl_slider_changed(self, value):
        refl = value / 100.0
        self.lbl_cg_refl.setText(f"{refl:.2f}")
        self.pipeline.state.cg_comp_refl = refl
        self._trigger_update(hdri=False, plate=False, cg=False)

    def on_cg_blend_slider_changed(self, value):
        blend = value / 100.0
        self.lbl_cg_blend.setText(f"{blend:.2f}")
        self.pipeline.state.cg_comp_blend = blend
        self._trigger_update(hdri=False, plate=False, cg=False)
    
    def _trigger_plate_update(self, use_proxy=False):
        """Process plate grading and refresh the viewer."""
        self.pipeline.process_plate(use_proxy=use_proxy)
        self.update_viewer(use_proxy=use_proxy)
            
    def _get_auto_ev(self, arr):
        import numpy as np
        luma = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
        if luma.size > 100000:
            luma = luma[::10, ::10]
        p99 = np.percentile(luma, 99.0)
        return float(np.log2(0.8 / p99)) if p99 > 1e-6 else 0.0

    def _resize_to_match(self, src_arr, target_shape):
        if src_arr is None or src_arr.shape[:2] == target_shape[:2]:
            return src_arr
        
        target_h, target_w = target_shape[:2]
        try:
            import cv2
            return cv2.resize(src_arr, (target_w, target_h), interpolation=cv2.INTER_AREA)
        except ImportError:
            try:
                from scipy.ndimage import zoom
                sy = target_h / src_arr.shape[0]
                sx = target_w / src_arr.shape[1]
                if src_arr.ndim == 3:
                    return zoom(src_arr, (sy, sx, 1), order=1)
                else:
                    return zoom(src_arr, (sy, sx), order=1)
            except ImportError:
                # Pure numpy nearest-neighbor fallback when cv2/scipy are missing (e.g. inside Nuke)
                import numpy as np
                y = np.linspace(0, src_arr.shape[0] - 1, target_h).astype(int)
                x = np.linspace(0, src_arr.shape[1] - 1, target_w).astype(int)
                if src_arr.ndim == 3:
                    return src_arr[y, :][:, x, :]
                else:
                    return src_arr[y, :][:, x]

    def _set_viewer_image(self, viewer, side: str, image_array, source_key,
                          ev_offset=0.0, reset_view=False, tone_reference=None, wipe_image_array=None):
        viewer.invalidate_tone_cache()
        if tone_reference is not None:
            viewer.set_tone_reference(tone_reference)
        viewer.set_image(image_array, ev_offset=ev_offset, reset_view=reset_view, wipe_image_array=wipe_image_array)

    def update_viewer(self, use_proxy=False, reset_view=False):
        if not getattr(self, '_is_timeline_update', False):
            pass # Cache clearing is now handled by _trigger_update
            
        if not isinstance(use_proxy, bool):
            use_proxy = False
        if not isinstance(reset_view, bool):
            reset_view = False

        mode = self.combo_view_mode.currentText()
        view_name = self.combo_display_transform.currentText()
        output_space = self.combo_cs_output.currentText()
        
        self.viewer_left.display_mode = "sRGB"
        self.viewer_right.display_mode = "sRGB"
        
        def _dt_func(img):
            return self.pipeline.colorspace_manager.apply_display_transform(img, output_space, view_name)
            
        self.viewer_left.display_transform_func = _dt_func
        self.viewer_right.display_transform_func = _dt_func
        
        if mode in ("HDRI", "Split Comparison", "False Color"):
            self.viewer_left._mask_yaw = self.pipeline.state.hdri_yaw
        else:
            self.viewer_left._mask_yaw = 0.0
            
        self._update_bg_masks()
        
        if self.pipeline.state.sun_relight_enabled:
            self.viewer_left.set_sun_positions(
                self.pipeline.state.sun_source_u,
                self.pipeline.state.sun_source_v,
                self.pipeline.state.sun_target_u,
                self.pipeline.state.sun_target_v,
                from_pipeline=True
            )
            
        show_refs = self.chk_show_refs.isChecked()
        macbeth = self.pipeline.state.macbeth_chart_array if show_refs else None
        chrome = self.pipeline.state.chrome_ball_array if show_refs else None
        grey = self.pipeline.state.grey_ball_array if show_refs else None
        
        for lbl, arr, cache_name in ((self.lbl_ref_macbeth, macbeth, '_cache_macbeth_pixmap'),
                                     (self.lbl_ref_chrome, chrome, '_cache_chrome_pixmap'),
                                     (self.lbl_ref_grey, grey, '_cache_grey_pixmap')):
            if arr is not None:
                cached_pix = getattr(self, cache_name, None)
                if cached_pix is None:
                    auto_ev = self._get_auto_ev(arr)
                    pix = self.viewer_left._make_pixmap(arr, update_cache=False, apply_ev=True, override_ev=auto_ev)
                    cached_pix = pix.scaledToWidth(280, QtCore.Qt.SmoothTransformation)
                    setattr(self, cache_name, cached_pix)
                
                lbl.setPixmap(cached_pix)
                lbl.show()
            else:
                lbl.hide()
        
        self.viewer_left.set_references(None, None, None)
        self.viewer_right.set_references(None, None, None)
        
        st = self.pipeline.state
        
        # Plate — use graded plate when adjustments are active, otherwise raw plate.
        # Fallback to full-res if proxy not available.
        has_active_plate_masks = st.masks_enabled and any(m.enabled and getattr(m, 'target', 'HDRI') == 'Plate' for m in st.masks)
        plate_has_adjustments = has_active_plate_masks or (st.plate_adjustments_enabled and (
                                 abs(st.plate_ev_offset) > 1e-8
                                 or abs(st.plate_saturation - 1.0) > 1e-6
                                 or abs(st.plate_temperature) > 1e-4
                                 or abs(st.plate_tint) > 1e-4))
        if plate_has_adjustments:
            plate_arr = (st.plate_graded_proxy if (use_proxy and st.plate_graded_proxy is not None)
                         else st.plate_graded)
            # Fall back to raw plate if grading hasn't been computed yet
            if plate_arr is None:
                plate_arr = (st.plate_proxy if (use_proxy and st.plate_proxy is not None)
                             else st.plate_array)
        else:
            plate_arr = (st.plate_proxy if (use_proxy and st.plate_proxy is not None)
                         else st.plate_array)
        
        # Calibrated HDRI
        if use_proxy and st.calibrated_proxy is not None:
            hdri_arr = st.calibrated_proxy
        elif st.calibrated_hdri is not None:
            hdri_arr = st.calibrated_hdri
        else:
            hdri_arr = (st.hdri_proxy if (use_proxy and st.hdri_proxy is not None)
                        else st.hdri_array)
        
        # CG reconstruction — prefer proxy during drag, full-res otherwise.
        # Fallback chain: cg_reconstructed → cg_reconstructed_proxy → None
        # This ensures the viewer always shows the CG even if the full-res
        # reconstruct hasn't finished yet (e.g. right after load).
        if use_proxy and st.cg_reconstructed_proxy is not None:
            cg_arr = st.cg_reconstructed_proxy
        elif st.cg_reconstructed is not None:
            cg_arr = st.cg_reconstructed
        elif st.cg_reconstructed_proxy is not None:
            cg_arr = st.cg_reconstructed_proxy  # fallback — use proxy if full-res missing
        else:
            cg_arr = None
            
        alpha_arr = (st.cg_alpha_proxy if (use_proxy and st.cg_alpha_proxy is not None)
                     else st.cg_alpha)
        
        # Handle Reformat (Viewer matching)
        reformat_mode = self.combo_reformat.currentText()
        
        is_cg_tab = self.right_tabs.currentIndex() == 1
        
        # Viewer applies EV globally unless it's baked into the pixel array (apply_exposure_match)
        viewer_ev_offset = 0.0 if st.apply_exposure_match else st.ev_offset
        
        display_space = (self.combo_cs_input.currentText(),
                         self.combo_cs_output.currentText())
        hdri_key = ("calibrated_hdri", st.hdri_path, reformat_mode, display_space)
        plate_key = ("plate", st.plate_path, reformat_mode, display_space)
        # Include a hash of the current light params so key changes whenever
        # sliders are adjusted — this forces the tone cache to update and makes
        # AOV edits immediately visible in the viewer.
        _params_hash = hash(repr(st.cg_light_params)) if st.cg_light_params else 0
        cg_key = ("cg_reconstructed", st.cg_exr_path, st.plate_path,
                  reformat_mode, display_space, "plate_tone", _params_hash)
        composite_key = ("cg_over_plate", st.cg_exr_path, st.plate_path,
                         reformat_mode, display_space, "plate_tone", _params_hash)

        # Always preserve the current zoom/pan when updating display — only
        # reset the view when loading a brand-new file (handled explicitly
        # in load_hdri / load_plate).
        if mode == "Split Comparison":
            self.viewer_right.show()
            sizes = self.viewer_splitter.sizes()
            if sum(sizes) > 0 and (sizes[0] == 0 or sizes[1] == 0):
                half = sum(sizes) // 2
                self.viewer_splitter.setSizes([half, sum(sizes) - half])
                
            left_arr = cg_arr if (is_cg_tab and cg_arr is not None) else hdri_arr
            left_ev = 0.0 if (is_cg_tab and cg_arr is not None) else viewer_ev_offset
            left_key = cg_key if (is_cg_tab and cg_arr is not None) else hdri_key
            self._set_viewer_image(self.viewer_left, "left", left_arr,
                                   left_key, ev_offset=left_ev,
                                   reset_view=reset_view,
                                   tone_reference=plate_arr if left_key == cg_key else None)
            self._set_viewer_image(self.viewer_right, "right", plate_arr,
                                   plate_key, ev_offset=0.0,
                                   reset_view=reset_view)
        else:
            self.viewer_right.hide()
            if mode == "HDRI":
                self._set_viewer_image(self.viewer_left, "left", hdri_arr,
                                       hdri_key, ev_offset=viewer_ev_offset,
                                       reset_view=reset_view)
            elif mode == "Plate":
                self._set_viewer_image(self.viewer_left, "left", plate_arr,
                                       plate_key, ev_offset=0.0,
                                       reset_view=reset_view)
            elif mode == "CG Reconstructed":
                self._set_viewer_image(self.viewer_left, "left", cg_arr,
                                       cg_key, ev_offset=0.0,
                                       reset_view=reset_view,
                                       tone_reference=plate_arr)
            elif mode == "CG Over Plate":
                # Porter-Duff 'over': CG is input A (foreground), plate is B (background).
                # Arnold EXR beauty passes are PRE-MULTIPLIED — the RGB channels
                # already have alpha baked in.  The correct formula is:
                #
                #   result = A_premult + B * (1 - alpha_A)
                #
                # DO NOT multiply cg_arr by alpha again (that would square it and
                # make the object nearly invisible at partial-coverage pixels).

                # --- Diagnostic removed for performance ---
                if cg_arr is not None and plate_arr is not None:
                    # Enforce matching sizes if not already reformatted
                    if cg_arr.shape[:2] != plate_arr.shape[:2]:
                        cg_arr = self._resize_to_match(cg_arr, plate_arr.shape)
                        if alpha_arr is not None:
                            alpha_arr = self._resize_to_match(alpha_arr, plate_arr.shape)

                    if alpha_arr is not None:
                        alpha_2d = np.squeeze(alpha_arr)
                        if alpha_2d.ndim != 2:
                            alpha_2d = alpha_2d[..., 0]
                        alpha_2d = np.clip(alpha_2d, 0.0, 1.0)
                        
                        shadow_intensity = getattr(st, 'cg_comp_shadow', 1.0)
                        refl_intensity = getattr(st, 'cg_comp_refl', 1.0)
                        
                        alpha_3d = alpha_2d[:, :, np.newaxis]  # (H,W,1) for broadcast

                        plate_shadowed = plate_arr[..., :3].copy()
                        plate_reflection = np.zeros_like(plate_shadowed)
                        
                        # Find shadow and reflection passes
                        cg_lights = st.cg_light_proxies if use_proxy and st.cg_light_proxies else st.cg_lights
                        if cg_lights:
                            for layer_name, aov_arr in cg_lights.items():
                                layer_lower = layer_name.lower()
                                if "shadow" in layer_lower:
                                    if aov_arr.shape[:2] != plate_shadowed.shape[:2]:
                                        aov_arr = self._resize_to_match(aov_arr, plate_shadowed.shape)
                                    # shadow_matte is usually white (no shadow) and dark (shadow)
                                    shadow_mult = 1.0 - ((1.0 - aov_arr[..., :3]) * shadow_intensity)
                                    plate_shadowed *= shadow_mult
                                elif "refl" in layer_lower:
                                    if aov_arr.shape[:2] != plate_reflection.shape[:2]:
                                        aov_arr = self._resize_to_match(aov_arr, plate_reflection.shape)
                                    plate_reflection += aov_arr[..., :3] * refl_intensity
                        
                        # Pre-multiplied 'over': A_premult + B*(1-alpha)
                        # Arnold EXR beauty and light AOVs are pre-multiplied by default.
                        cg_blend = getattr(st, 'cg_comp_blend', 1.0)
                        
                        cg_rgb = cg_arr[..., :3] * cg_blend
                        alpha_blend = alpha_3d * cg_blend
                        
                        plate_shadowed_mixed = plate_arr[..., :3] * (1.0 - cg_blend) + plate_shadowed * cg_blend
                        plate_reflection_mixed = plate_reflection * cg_blend
                        
                        composite = cg_rgb + plate_shadowed_mixed * (1.0 - alpha_blend) + plate_reflection_mixed
                        self._set_viewer_image(self.viewer_left, "left", composite,
                                               composite_key, ev_offset=0.0,
                                               reset_view=reset_view,
                                               tone_reference=plate_arr,
                                               wipe_image_array=plate_arr)
                    else:
                        # No alpha — show CG directly over plate (additive)
                        cg_blend = getattr(st, 'cg_comp_blend', 1.0)
                        composite = np.clip((cg_arr[..., :3] * cg_blend) + plate_arr[..., :3], 0.0, None)
                        self._set_viewer_image(self.viewer_left, "left", composite,
                                               composite_key, ev_offset=0.0,
                                               reset_view=reset_view,
                                               tone_reference=plate_arr,
                                               wipe_image_array=plate_arr)
                elif cg_arr is not None:
                    # Plate not loaded — display raw CG reconstructed alone
                    self._set_viewer_image(self.viewer_left, "left", cg_arr,
                                           cg_key, ev_offset=0.0,
                                           reset_view=reset_view)
                elif plate_arr is not None:
                    # CG not loaded — display plate alone
                    self._set_viewer_image(self.viewer_left, "left", plate_arr,
                                           plate_key, ev_offset=0.0,
                                           reset_view=reset_view)
                else:
                    # Nothing to show
                    self.viewer_left.set_image(None)
            elif mode == "Difference Matte":
                base_arr = cg_arr if (is_cg_tab and cg_arr is not None) else hdri_arr
                if base_arr is not None and plate_arr is not None:
                    if base_arr.shape[:2] != plate_arr.shape[:2]:
                        base_arr = self._resize_to_match(base_arr, plate_arr.shape)
                    diff = np.abs(base_arr[..., :3] - plate_arr[..., :3])
                    diff_key = ("difference_matte", cg_key if is_cg_tab else hdri_key, plate_key)
                    self._set_viewer_image(self.viewer_left, "left", diff,
                                           diff_key, ev_offset=0.0,
                                           reset_view=reset_view)
                else:
                    self.viewer_left.set_image(None)
            elif mode == "CG Alpha":
                # Display the CG alpha channel as a greyscale image
                if alpha_arr is not None:
                    alpha_2d = np.squeeze(alpha_arr)
                    if alpha_2d.ndim != 2:
                        alpha_2d = alpha_2d[..., 0]
                    alpha_vis = np.stack([alpha_2d, alpha_2d, alpha_2d], axis=-1)
                    alpha_key = ("cg_alpha", st.cg_exr_path, reformat_mode)
                    self._set_viewer_image(self.viewer_left, "left", alpha_vis,
                                           alpha_key, ev_offset=0.0,
                                           reset_view=reset_view)
                else:
                    self.viewer_left.set_image(None)
            elif mode == "False Color":
                base_arr = cg_arr if (is_cg_tab and cg_arr is not None) else hdri_arr
                if base_arr is not None:
                    from hdri_match.analysis.false_color import FalseColorEngine
                    heatmap = FalseColorEngine.generate_heatmap(base_arr)
                    false_key = ("false_color", cg_key if is_cg_tab else hdri_key)
                    self._set_viewer_image(self.viewer_left, "left", heatmap,
                                           false_key, ev_offset=0.0,
                                           reset_view=reset_view)  # ev already baked into calibrated array
                                           
        # Update Scopes
        img_right = None
        if mode == "Split Comparison" and hasattr(self.viewer_right, 'last_8u'):
            img_right = self.viewer_right.last_8u
            
        scope_img = None
        if mode == "CG Over Plate" and cg_arr is not None:
            # The user requested the scopes to display ONLY the CG render when in CG Over Plate, 
            # rather than the composite. We generate an 8-bit representation of the CG here.
            scope_img = self.viewer_left._hdr_to_uint8(
                cg_arr, 
                update_cache=False, 
                apply_ev=True, 
                override_ev=0.0
            )
        elif hasattr(self.viewer_left, 'last_8u') and self.viewer_left.last_8u is not None:
            scope_img = self.viewer_left.last_8u
            
        if scope_img is not None:
            self.scopes_widget.update_scopes(scope_img, img_8u_right=img_right)
        # Ensure mask overlays scale correctly if the image resolution changed
        if self.right_tabs.currentIndex() == 0:
            self.on_mask_selected(self.list_masks.currentRow())
            self._update_bg_masks()
                
    def export_sequence(self):
        if not self.pipeline.state.hdri_sequence or len(self.pipeline.state.hdri_sequence) < 1:
            QtWidgets.QMessageBox.warning(self, "No Sequence", "Please load an HDRI image sequence first.")
            return
            
        from hdri_match.io.exporter import save_numpy_to_image
        import os
        
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Output Directory for Sequence")
        if not out_dir: return
        
        prefix, ok = QtWidgets.QInputDialog.getText(self, "Sequence Prefix", "Enter filename prefix (e.g. 'hdri_calibrated_'): ", text="hdri_calibrated_")
        if not ok: return
        
        pad, ok = QtWidgets.QInputDialog.getInt(self, "Frame Padding", "Enter frame padding:", 4, 1, 8)
        if not ok: return
        
        ext, ok = QtWidgets.QInputDialog.getItem(self, "Format", "Select Format:", [".exr", ".hdr"], 0, False)
        if not ok: return
        
        progress = QtWidgets.QProgressDialog("Exporting sequence...", "Cancel", 0, len(self.pipeline.state.hdri_sequence), self)
        progress.setWindowModality(QtCore.Qt.WindowModal)
        
        orig_idx = self.pipeline.state.current_frame_index
        
        try:
            for i, frame_path in enumerate(self.pipeline.state.hdri_sequence):
                if progress.wasCanceled():
                    break
                    
                progress.setValue(i)
                QtWidgets.QApplication.processEvents()
                
                in_cs = self.combo_cs_input.currentText()
                out_cs = self.combo_cs_output.currentText()
                plate_path = self.pipeline.state.plate_sequence[i] if i < len(self.pipeline.state.plate_sequence) else None
                self.pipeline.load_inputs(hdri_path=frame_path, plate_path=plate_path, input_space=in_cs, working_space=out_cs)
                self.pipeline.process_hdri(use_proxy=False)
                
                frame_num = str(i+1).zfill(pad)
                out_name = f"{prefix}{frame_num}{ext}"
                out_path = os.path.join(out_dir, out_name)
                
                save_numpy_to_image(self.pipeline.state.calibrated_hdri, out_path)
                
            progress.setValue(len(self.pipeline.state.hdri_sequence))
            QtWidgets.QMessageBox.information(self, "Success", f"Exported {len(self.pipeline.state.hdri_sequence)} frames to {out_dir}")
            
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to export sequence: {e}")
        finally:
            if 0 <= orig_idx < len(self.pipeline.state.hdri_sequence):
                self.on_timeline_changed(orig_idx)

    def export_image(self):
        from hdri_match.io.exporter import save_numpy_to_image
        import os
        import subprocess, shutil

        if getattr(self.pipeline.state, 'is_sequence', False):
            out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Output Directory for Sequence")
            if not out_dir: return
            
            prefix, ok = QtWidgets.QInputDialog.getText(self, "Sequence Prefix", "Enter filename prefix (e.g. 'hdri_calibrated_'): ", text="hdri_calibrated_")
            if not ok: return
            
            pad, ok = QtWidgets.QInputDialog.getInt(self, "Frame Padding", "Enter frame padding:", 4, 1, 8)
            if not ok: return
            
            ext, ok = QtWidgets.QInputDialog.getItem(self, "Format", "Select Format:", [".exr", ".hdr"], 0, False)
            if not ok: return
            
            progress = QtWidgets.QProgressDialog("Exporting sequence...", "Cancel", 0, len(self.pipeline.state.sequence_files), self)
            progress.setWindowModality(QtCore.Qt.WindowModal)
            
            orig_idx = self.pipeline.state.current_frame_index
            
            try:
                for i, frame_path in enumerate(self.pipeline.state.sequence_files):
                    if progress.wasCanceled():
                        break
                        
                    progress.setValue(i)
                    QtWidgets.QApplication.processEvents()
                    
                    self.pipeline.load_hdri(frame_path)
                    self.pipeline.build_full_res_cache()
                    
                    frame_num = str(i+1).zfill(pad)
                    out_name = f"{prefix}{frame_num}{ext}"
                    out_path = os.path.join(out_dir, out_name)
                    
                    save_numpy_to_image(self.pipeline.state.calibrated_hdri, out_path)
                    
                progress.setValue(len(self.pipeline.state.sequence_files))
                QtWidgets.QMessageBox.information(self, "Success", f"Exported {len(self.pipeline.state.sequence_files)} frames to {out_dir}")
                
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Failed to export sequence: {e}")
            finally:
                if 0 <= orig_idx < len(self.pipeline.state.sequence_files):
                    self.pipeline.state.current_frame_index = orig_idx
                    self.pipeline.load_hdri(self.pipeline.state.sequence_files[orig_idx])
                    self.pipeline.build_full_res_cache()
                    self.update_viewers()
        else:
            self.pipeline.build_full_res_cache()
            if self.pipeline.state.calibrated_hdri is None:
                QtWidgets.QMessageBox.warning(self, "Error", "No calibrated HDRI available to export.")
                return
                
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Image", "", "EXR Files (*.exr);;HDR Files (*.hdr)")
            if path:
                try:
                    save_numpy_to_image(self.pipeline.state.calibrated_hdri, path)
                    
                    # Try to generate tx/rat
                    maketx_path = shutil.which("maketx")
                    iconvert_path = shutil.which("iconvert")
                    
                    msg = f"Exported to {path}"
                    if maketx_path:
                        tx_path = os.path.splitext(path)[0] + ".tx"
                        subprocess.Popen([maketx_path, "-v", "-u", "--oiio", "--filter", "lanczos3", path, "-o", tx_path])
                        msg += "\n\nBackground process started to generate .tx file for Arnold/Karma."
                    elif iconvert_path:
                        rat_path = os.path.splitext(path)[0] + ".rat"
                        subprocess.Popen([iconvert_path, path, rat_path])
                        msg += "\n\nBackground process started to generate .rat file for Mantra."
                        
                    QtWidgets.QMessageBox.information(self, "Success", msg)
                except Exception as e:
                    QtWidgets.QMessageBox.warning(self, "Error", str(e))

    def export_mask_lights(self):
        self.pipeline.build_full_res_cache()
        if self.pipeline.state.hdri_array is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No HDRI loaded.")
            return
            
        masks_to_export = [m for m in self.pipeline.state.masks if m.enabled and m.rect is not None]
        if not masks_to_export:
            QtWidgets.QMessageBox.warning(self, "Error", "No valid masks enabled to export.")
            return
            
        export_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Export Directory for Mask Lights")
        if not export_dir:
            return
            
        try:
            from hdri_match.io.exporter import export_masks_as_solaris_lights
            # Use calibrated hdri if available, otherwise raw hdri array
            base_img = self.pipeline.state.calibrated_hdri
            if base_img is None:
                base_img = self.pipeline.state.hdri_array
                
            script_path = export_masks_as_solaris_lights(masks_to_export, base_img, export_dir)
            QtWidgets.QMessageBox.information(self, "Success", f"Exported {len(masks_to_export)} lights to:\n{script_path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to export mask lights:\n{e}")

    def on_export_camera_clicked(self):
        paths_to_try = []
        if self.pipeline.state.plate_path and self.pipeline.state.plate_path.lower().strip().endswith('.exr'):
            paths_to_try.append(self.pipeline.state.plate_path)
        if hasattr(self.pipeline.state, 'cg_exr_path') and self.pipeline.state.cg_exr_path and self.pipeline.state.cg_exr_path.lower().strip().endswith('.exr'):
            paths_to_try.append(self.pipeline.state.cg_exr_path)
        if self.pipeline.state.hdri_path and self.pipeline.state.hdri_path.lower().strip().endswith('.exr'):
            paths_to_try.append(self.pipeline.state.hdri_path)
            
        if not paths_to_try:
            QtWidgets.QMessageBox.warning(self, "Error", "A valid EXR file must be loaded to extract camera metadata.")
            return
            
        export_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Export Directory for Camera")
        if not export_dir:
            return
            
        try:
            from hdri_match.io.exporter import export_camera_to_solaris
            script_path = None
            for p in paths_to_try:
                script_path = export_camera_to_solaris(p, export_dir)
                if script_path:
                    break
                    
            if script_path:
                QtWidgets.QMessageBox.information(self, "Success", f"Exported Camera Solaris script to:\n{script_path}")
            else:
                # Fallback: Generate a default 50mm camera
                fallback_script = os.path.join(export_dir, "export_default_camera.py")
                script_lines = [
                    "import hou",
                    "from pxr import Usd, UsdGeom, Gf",
                    "node = hou.pwd()",
                    "stage = node.editableStage()",
                    "if not stage:",
                    "    print('Please run inside a Python LOP')",
                    "    pass",
                    "",
                    "cam_path = '/cameras/plate_cam'",
                    "cam = UsdGeom.Camera.Define(stage, cam_path)",
                    "cam.GetFocalLengthAttr().Set(50.0)",
                    "cam.GetHorizontalApertureAttr().Set(36.0)",
                    "print('Generated default 50mm camera at', cam_path)"
                ]
                with open(fallback_script, 'w') as f:
                    f.write("\n".join(script_lines))
                    
                QtWidgets.QMessageBox.warning(self, "No Camera Data Found", 
                    "No lens or camera metadata could be found in any loaded EXR.\n\n"
                    f"A DEFAULT 50mm Camera script has been exported instead to:\n{fallback_script}\n\n"
                    "You will need to manually adjust the focal length in Houdini to match your plate.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "Export Error", f"Failed to export camera:\n{e}")

    def save_project(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Project", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            self.pipeline.state.cg_aov_prefixes = self.line_edit_prefix.text()
            view_mode = self.combo_view_mode.currentText()
            proxy_resolution = self.combo_reformat.currentText()
            split_ratio = self.viewer_splitter.sizes()
            self.pipeline.save_project(path, view_mode=view_mode, proxy_resolution=proxy_resolution, split_ratio=split_ratio)
            QtWidgets.QMessageBox.information(self, "Success", f"Project saved to:\n{path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to save project:\n{str(e)}")

    def load_project(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load Project", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            result = self.pipeline.load_project(path)
            if len(result) == 4:
                hdri_path, plate_path, cg_exr_path, view_mode = result
                proxy_resolution, split_ratio = None, None
            else:
                hdri_path, plate_path, cg_exr_path, view_mode, proxy_resolution, split_ratio = result
            
            # Sync UI Controls
            if hasattr(self.pipeline.state, 'cg_aov_prefixes'):
                self.line_edit_prefix.setText(self.pipeline.state.cg_aov_prefixes)
                
            self.slider_yaw.blockSignals(True)
            self.slider_yaw.setValue(int(self.pipeline.state.hdri_yaw * 10))
            self.lbl_yaw_value.setText(f"{self.pipeline.state.hdri_yaw:.1f}°")
            self.slider_yaw.blockSignals(False)
            
            self.slider_ev.blockSignals(True)
            self.slider_ev.setValue(int(self.pipeline.state.ev_offset * 100))
            self.lbl_ev_value.setText(f"{self.pipeline.state.ev_offset:.2f} EV")
            self.slider_ev.blockSignals(False)
            
            self.slider_temp.blockSignals(True)
            self.slider_temp.setValue(int(self.pipeline.state.temperature * 100))
            self.lbl_temp_value.setText(f"{self.pipeline.state.temperature:.2f}")
            self.slider_temp.blockSignals(False)
            
            self.slider_tint.blockSignals(True)
            self.slider_tint.setValue(int(self.pipeline.state.tint * 100))
            self.lbl_tint_value.setText(f"{self.pipeline.state.tint:.2f}")
            self.slider_tint.blockSignals(False)
            
            self.chk_apply_hdri_exposure.blockSignals(True)
            self.chk_apply_hdri_exposure.setChecked(self.pipeline.state.apply_exposure_match)
            self.chk_apply_hdri_exposure.blockSignals(False)
            
            if hasattr(self.pipeline.state, 'protect_sun'):
                self.chk_protect_sun.blockSignals(True)
                self.chk_protect_sun.setChecked(self.pipeline.state.protect_sun)
                self.chk_protect_sun.blockSignals(False)
                
            if hasattr(self.pipeline.state, 'sky_mode') and self.pipeline.state.sky_mode:
                self.combo_sky_mode.blockSignals(True)
                try:
                    sky_mode_idx = ["off", "top_40", "custom_rect"].index(self.pipeline.state.sky_mode)
                    self.combo_sky_mode.setCurrentIndex(sky_mode_idx)
                except ValueError:
                    pass
                self.combo_sky_mode.blockSignals(False)
            
            self.chk_ai_awb.setChecked(self.pipeline.state.ai_awb_enable)
            
            # Horizon Settings
            self.group_ground.blockSignals(True)
            self.group_ground.setChecked(self.pipeline.state.horizon_enable)
            self.group_ground.blockSignals(False)
            
            def sync_slider(slider, lbl, val, mult=100.0, fmt="{:.2f}", suffix=""):
                slider.blockSignals(True)
                slider.setValue(int(val * mult))
                lbl.setText(fmt.format(val) + suffix)
                slider.blockSignals(False)
                
            sync_slider(self.slider_ground_height, self.lbl_ground_height, self.pipeline.state.horizon_height)
            sync_slider(self.slider_ground_feather, self.lbl_ground_feather, self.pipeline.state.horizon_feather)
            
            sync_slider(self.slider_sky_ev, self.lbl_sky_ev, self.pipeline.state.sky_ev_offset, fmt="{:+.2f}", suffix=" EV")
            sync_slider(self.slider_sky_temp, self.lbl_sky_temp, self.pipeline.state.sky_temperature)
            sync_slider(self.slider_sky_tint, self.lbl_sky_tint, self.pipeline.state.sky_tint)
            sync_slider(self.slider_sky_desat, self.lbl_sky_desat, self.pipeline.state.sky_desat, mult=100.0, fmt="{:.0f}", suffix=" %")
            
            sync_slider(self.slider_ground_ev, self.lbl_ground_ev, self.pipeline.state.ground_ev_offset, fmt="{:+.2f}", suffix=" EV")
            sync_slider(self.slider_ground_temp, self.lbl_ground_temp, self.pipeline.state.ground_temperature)
            sync_slider(self.slider_ground_tint, self.lbl_ground_tint, self.pipeline.state.ground_tint)
            sync_slider(self.slider_ground_desat, self.lbl_ground_desat, self.pipeline.state.ground_desat, mult=100.0, fmt="{:.0f}", suffix=" %")
            
            # Soft-clip Settings
            self.group_softclip.blockSignals(True)
            self.group_softclip.setChecked(self.pipeline.state.softclip_enable)
            self.group_softclip.blockSignals(False)
            
            sync_slider(self.slider_softclip_thresh, self.lbl_softclip_thresh, self.pipeline.state.softclip_threshold, mult=10.0, fmt="{:.1f}", suffix=" EV")
            sync_slider(self.slider_softclip_rolloff, self.lbl_softclip_rolloff, self.pipeline.state.softclip_rolloff, mult=10.0, fmt="{:.1f}", suffix=" EV")
            
            # Plate adjustments
            self.group_plate.blockSignals(True)
            self.group_plate.setChecked(self.pipeline.state.plate_adjustments_enabled)
            self.group_plate.blockSignals(False)
            
            sync_slider(self.slider_plate_ev, self.lbl_plate_ev_value, self.pipeline.state.plate_ev_offset, fmt="{:.2f}", suffix=" EV")
            sync_slider(self.slider_plate_sat, self.lbl_plate_sat_value, self.pipeline.state.plate_saturation)
            sync_slider(self.slider_plate_temp, self.lbl_plate_temp_value, self.pipeline.state.plate_temperature)
            sync_slider(self.slider_plate_tint, self.lbl_plate_tint_value, self.pipeline.state.plate_tint)
            # Sun Relighting
            if hasattr(self.pipeline.state, 'sun_relight_enabled'):
                self.group_sun_relight.blockSignals(True)
                self.chk_enable_sun_relight.blockSignals(True)
                
                self.group_sun_relight.setChecked(self.pipeline.state.sun_relight_enabled)
                self.chk_enable_sun_relight.setChecked(self.pipeline.state.sun_relight_enabled)
                
                self.group_sun_relight.blockSignals(False)
                self.chk_enable_sun_relight.blockSignals(False)
                
                self.slider_sun_radius.blockSignals(True)
                self.slider_sun_radius.setValue(int(self.pipeline.state.sun_radius * 1000))
                self.slider_sun_radius.blockSignals(False)
                
                self.slider_sun_feather.blockSignals(True)
                self.slider_sun_feather.setValue(int(self.pipeline.state.sun_feather * 1000))
                self.slider_sun_feather.blockSignals(False)
                
                if self.pipeline.state.sun_relight_enabled:
                    self.viewer_left.set_sun_positions(
                        self.pipeline.state.sun_source_u,
                        self.pipeline.state.sun_source_v,
                        self.pipeline.state.sun_target_u,
                        self.pipeline.state.sun_target_v
                    )
                    
            # CG Comp
            if hasattr(self.pipeline.state, 'cg_comp_shadow'):
                sync_slider(self.slider_cg_shadow, self.lbl_cg_shadow, self.pipeline.state.cg_comp_shadow)
            if hasattr(self.pipeline.state, 'cg_comp_wipe'):
                sync_slider(self.slider_cg_wipe, self.lbl_cg_wipe, self.pipeline.state.cg_comp_wipe, mult=100.0, fmt="{:.0f}", suffix=" %")
            
            # Masks
            self.update_mask_list()
            
            # Load images
            try:
                self.pipeline.load_inputs(hdri_path, plate_path, 
                    self.combo_cs_input.currentText(), self.combo_cs_output.currentText())
                self.lbl_hdri_path.setText(os.path.basename(hdri_path) if hdri_path else "No file selected")
                self.lbl_plate_path.setText(os.path.basename(plate_path) if plate_path else "No file selected")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Image Load Error", f"Failed to load images:\n{e}")
                
            if cg_exr_path:
                try:
                    saved_params = getattr(self.pipeline.state, 'cg_light_params', {}).copy()
                    self.pipeline.load_cg_lights(cg_exr_path,
                        prefixes=tuple([p.strip() for p in self.line_edit_prefix.text().split(',')]),
                        input_colorspace=self.combo_cs_input.currentText(),
                        working_space=self.combo_cs_output.currentText())
                    if saved_params:
                        for k, v in saved_params.items():
                            if k in self.pipeline.state.cg_light_params:
                                self.pipeline.state.cg_light_params[k].update(v)
                    self.lbl_cg_path.setText(os.path.basename(cg_exr_path))
                    self.build_cg_light_sliders()
                except Exception as e:
                    QtWidgets.QMessageBox.warning(self, "CG Load Error", f"Failed to load CG passes:\n{e}")
                    
            if view_mode:
                self.combo_view_mode.blockSignals(True)
                self.combo_view_mode.setCurrentText(view_mode)
                self.combo_view_mode.blockSignals(False)
                
            if proxy_resolution:
                idx = self.combo_reformat.findText(proxy_resolution)
                if idx >= 0: 
                    self.combo_reformat.setCurrentIndex(idx)
                    
            if split_ratio is not None and len(split_ratio) == 2:
                self.viewer_splitter.setSizes(split_ratio)
            
            self._do_deferred_update()
            QtWidgets.QMessageBox.information(self, "Success", f"Project loaded from:\n{path}")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to load project:\n{str(e)}")

    def on_detect_sun_clicked(self):
        st = self.pipeline.state
        hdri = st.calibrated_hdri if st.calibrated_hdri is not None else st.hdri_array
        if hdri is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No HDRI loaded.")
            return

        import numpy as np
        luma = 0.2126 * hdri[..., 0] + 0.7152 * hdri[..., 1] + 0.0722 * hdri[..., 2]
        flat_idx = int(np.argmax(luma))
        h, w = hdri.shape[:2]
        py, px = divmod(flat_idx, w)

        # Apply user yaw rotation
        u = (px / float(w))
        v = (py / float(h))
        
        # Yaw is in degrees, positive means shifting the map right
        yaw_offset = st.hdri_yaw / 360.0
        u = (u - yaw_offset) % 1.0

        # Convert to polar coordinates
        # Equirectangular mapping:
        # u = 0.5 is front, u = 0 is back, u = 1 is back
        # v = 0 is top, v = 1 is bottom
        import math
        theta = (1.0 - u) * 2 * math.pi - (math.pi / 2.0)
        phi = (1.0 - v) * math.pi
        
        # Convert to Houdini/Nuke standard (Y-up right-handed)
        # X = right, Y = up, Z = forward (or backward depending on DCC)
        dir_x = math.cos(theta) * math.sin(phi)
        dir_y = math.cos(phi)
        dir_z = math.sin(theta) * math.sin(phi)
        
        vector_str = f"{dir_x:.5f}, {dir_y:.5f}, {dir_z:.5f}"
        
        cb = QtWidgets.QApplication.clipboard()
        cb.setText(vector_str)
        
        msg = (f"The brightest point (Sun) was found at pixel ({px}, {py}).\n\n"
               f"Direction Vector (X, Y, Z):\n{vector_str}\n\n"
               "This vector has been copied to your clipboard.\n"
               "You can paste it into the Direction parameter of a Distant Light in Nuke, Houdini, Maya, or Unreal Engine.")
        QtWidgets.QMessageBox.information(self, "Sun Vector Extracted", msg)

    def export_solaris_package(self):
        st = self.pipeline.state
        if st.calibrated_hdri is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No calibrated HDRI available to export.")
            return

        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Publish Directory")
        if not out_dir:
            return
            
        import os, json, math
        import numpy as np
        from hdri_match.io.exporter import save_numpy_to_image
        
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        
        try:
            # 1. Save Plate
            plate_path = ""
            if st.plate_graded is not None:
                plate_path = os.path.join(out_dir, "plate_graded.exr")
                save_numpy_to_image(st.plate_graded, plate_path)
            
            # 2. Save HDRI
            hdri_path = os.path.join(out_dir, "hdri_calibrated.exr")
            save_numpy_to_image(st.calibrated_hdri, hdri_path)
            
            # 3. Export Masks
            mask_lights = []
            if st.masks_enabled:
                h, w = st.calibrated_hdri.shape[:2]
                y_idx, x_idx = np.ogrid[:h, :w]
                
                for i, mask in enumerate(st.masks):
                    if not mask.enabled or mask.rect is None:
                        continue
                        
                    mask_img = np.zeros_like(st.calibrated_hdri)
                    nx1, ny1, nx2, ny2 = mask.rect
                    sx1, sx2 = nx1 * w, nx2 * w
                    sy1, sy2 = ny1 * h, ny2 * h
                    
                    alpha = np.zeros((h, w), dtype=np.float32)
                    feather = mask.feather
                    
                    if mask.shape in ["Polygon", "Lasso", "Brush"] and getattr(mask, 'points', None):
                        import cv2
                        poly_pts = [[nx * w, ny * h] for (nx, ny) in mask.points]
                        poly_arr = np.array(poly_pts, np.int32)
                        poly_mask = np.zeros((h, w), dtype=np.uint8)
                        
                        if mask.shape in ["Polygon", "Lasso"]:
                            cv2.fillPoly(poly_mask, [poly_arr], 1)
                            if feather < 1.0:
                                alpha = poly_mask.astype(np.float32)
                            else:
                                dist_in = cv2.distanceTransform(poly_mask, cv2.DIST_L2, 5)
                                dist_out = cv2.distanceTransform(1 - poly_mask, cv2.DIST_L2, 5)
                                val = 0.5 - ((dist_out - dist_in) / feather)
                                alpha = np.clip(val, 0.0, 1.0)
                                alpha = alpha * alpha * (3.0 - 2.0 * alpha)
                        else:
                            cv2.polylines(poly_mask, [poly_arr], isClosed=False, color=1, thickness=1, lineType=cv2.LINE_8)
                            dist_out = cv2.distanceTransform(1 - poly_mask, cv2.DIST_L2, 5)
                            radius = mask.brush_size / 2.0
                            val = 0.5 - ((dist_out - radius) / max(1.0, feather))
                            a = np.clip(val, 0.0, 1.0)
                            alpha = a * a * (3.0 - 2.0 * a)
                    else:
                        cx, cy = (sx1 + sx2) / 2.0, (sy1 + sy2) / 2.0
                        if mask.shape == "Ellipse":
                            rx, ry = max((sx2 - sx1) / 2.0, 1e-5), max((sy2 - sy1) / 2.0, 1e-5)
                            dist = np.sqrt(((x_idx - cx) / rx)**2 + ((y_idx - cy) / ry)**2)
                            dist_px = (dist - 1.0) * ((rx + ry) / 2.0)
                        else:
                            w_half, h_half = (sx2 - sx1) / 2.0, (sy2 - sy1) / 2.0
                            dx = np.abs(x_idx - cx) - w_half
                            dy = np.abs(y_idx - cy) - h_half
                            dist_px = np.sqrt(np.maximum(dx, 0)**2 + np.maximum(dy, 0)**2) + np.minimum(np.maximum(dx, dy), 0)
                        
                        if feather < 1.0:
                            alpha = np.where(dist_px <= 0, 1.0, 0.0).astype(np.float32)
                        else:
                            val = 0.5 - (dist_px / feather)
                            a = np.clip(val, 0.0, 1.0)
                            alpha = a * a * (3.0 - 2.0 * a)
                            
                    safe_name = mask.name.replace(" ", "_").lower()
                    light_type = getattr(mask, 'light_type', 'Dome')
                    
                    if light_type == "Rect" and mask.rect is not None:
                        # RectLight: Crop the RAW HDRI directly to fill the texture
                        nx1, ny1, nx2, ny2 = mask.rect
                        h_full, w_full = st.calibrated_hdri.shape[:2]
                        px1 = max(0, int(nx1 * w_full))
                        py1 = max(0, int(ny1 * h_full))
                        px2 = min(w_full, int(nx2 * w_full))
                        py2 = min(h_full, int(ny2 * h_full))
                        
                        if px2 > px1 and py2 > py1:
                            mask_img = st.calibrated_hdri[py1:py2, px1:px2].copy()
                            print(f"  [RectLight] Cropped '{mask.name}': {w_full}x{h_full} -> {mask_img.shape[1]}x{mask_img.shape[0]}")
                        else:
                            # Fallback: use alpha-multiplied full image
                            mask_img = st.calibrated_hdri * alpha[..., np.newaxis]
                            print(f"  [RectLight] Warning: Invalid crop for '{mask.name}', using full texture")
                    else:
                        # DomeLight: Full equirectangular with alpha mask applied
                        mask_img = st.calibrated_hdri * alpha[..., np.newaxis]
                    
                    mask_path = os.path.join(out_dir, f"mask_{i+1:02d}_{safe_name}.exr")
                    save_numpy_to_image(mask_img, mask_path)
                    
                    # Store texture resolution for RectLight aspect ratio
                    tex_h, tex_w = mask_img.shape[:2]
                    
                    mask_lights.append({
                        "name": mask.name,
                        "texture": mask_path.replace("\\", "/"),
                        "light_type": light_type,
                        "rect": mask.rect,
                        "texture_width": tex_w,
                        "texture_height": tex_h,
                        "ev_offset": mask.ev_offset,
                        "temperature": mask.temperature,
                        "tint": mask.tint
                    })

            # 4. Extract Sun Vector
            luma = 0.2126 * st.calibrated_hdri[..., 0] + 0.7152 * st.calibrated_hdri[..., 1] + 0.0722 * st.calibrated_hdri[..., 2]
            flat_idx = int(np.argmax(luma))
            py, px = divmod(flat_idx, st.calibrated_hdri.shape[1])
            u, v = (px / float(st.calibrated_hdri.shape[1])), (py / float(st.calibrated_hdri.shape[0]))
            
            # Match Houdini Dome Light Y-Rotation
            u = (u + (st.hdri_yaw / 360.0)) % 1.0
            
            # Standard USD Spherical Mapping (Mirrored X and Z to match Houdini Dome Light Top View)
            theta = (1.0 - u) * 2.0 * math.pi
            phi = v * math.pi
            
            dir_x = -math.sin(theta) * math.sin(phi)
            dir_y = math.cos(phi)
            dir_z = -math.cos(theta) * math.sin(phi)
            
            intensity = float(luma[py, px])
            color = st.calibrated_hdri[py, px, :3].tolist()
            
            # 5. Extract Camera Metadata (or Defaults)
            cam_data = {
                "focal_length": 50.0,
                "aperture": 36.0,
                "matrix": None,
                "is_world_to_cam": False
            }
            if st.plate_path and os.path.exists(st.plate_path):
                from hdri_match.io.exr_pure import read_multipart_exr_parts
                import struct
                try:
                    parts = read_multipart_exr_parts(st.plate_path)
                    if parts:
                        attrs = parts[0].get('attrs', {})
                        for k, v in attrs.items():
                            k_lower = k.lower()
                            if 'cameratransform' in k_lower and len(v[1]) >= 64:
                                cam_data["matrix"] = struct.unpack('<16f', v[1][:64])
                                cam_data["is_world_to_cam"] = False
                            elif 'worldtocamera' in k_lower and not cam_data["matrix"] and len(v[1]) >= 64:
                                cam_data["matrix"] = struct.unpack('<16f', v[1][:64])
                                cam_data["is_world_to_cam"] = True
                            elif 'focallength' in k_lower and len(v[1]) >= 4:
                                cam_data["focal_length"] = struct.unpack('<f', v[1][:4])[0]
                            elif 'aperture' in k_lower and len(v[1]) >= 4:
                                cam_data["aperture"] = struct.unpack('<f', v[1][:4])[0]
                except Exception:
                    pass

            # 6. Build JSON
            data = {
                "plate": plate_path.replace("\\\\", "/"),
                "hdri": {
                    "path": hdri_path.replace("\\\\", "/"),
                    "yaw_rotation": st.hdri_yaw,
                    "exposure": st.ev_offset
                },
                "camera": cam_data,
                "mask_lights": mask_lights,
                "sun_vector": {
                    "enabled": True,
                    "direction": [dir_x, dir_y, dir_z],
                    "intensity": intensity,
                    "exposure": float(np.log2(max(intensity, 1e-10))),
                    "color": color
                }
            }
            
            json_path = os.path.join(out_dir, "solaris_build.json")
            with open(json_path, "w") as f:
                json.dump(data, f, indent=4)
                
            # 7. Generate Lookdev Balls script
            from hdri_match.io.exporter import export_lookdev_balls_solaris
            export_lookdev_balls_solaris(out_dir)
                
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.information(self, "Success", f"Published Solaris Package to:\\n{out_dir}")
            
        except Exception as e:
            QtWidgets.QApplication.restoreOverrideCursor()
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to publish package:\\n{str(e)}")
            


def show_window():
    global hdri_calib_app
    try:
        import nuke
        app_parent = QtWidgets.QApplication.activeWindow()
    except ImportError:
        app_parent = None
        
    hdri_calib_app = HdriCalibWindow(parent=app_parent)
    hdri_calib_app.show()

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    window = HdriCalibWindow()
    window.show()
    sys.exit(app.exec_())
