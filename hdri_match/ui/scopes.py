import numpy as np
import cv2
from hdri_match.ui.qt_shim import QtWidgets, QtCore, QtGui

class ScopesWidget(QtWidgets.QGroupBox):
    """A dockable widget that displays live Video Scopes (Waveform & RGB Parade)."""
    
    def __init__(self, parent=None):
        super().__init__("Video Scopes", parent)
        self.setCheckable(True)
        self.setChecked(False)  # Collapsed by default
        self.toggled.connect(self._toggle_content)
        
        # Minimum size when expanded
        self._expanded_min_height = 200
        
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # Container for everything inside so we can hide/show it easily
        self.container = QtWidgets.QWidget()
        self.container_layout = QtWidgets.QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        
        self.toolbar = QtWidgets.QHBoxLayout()
        self.toolbar.setContentsMargins(0, 0, 0, 0)
        
        self.combo_mode = QtWidgets.QComboBox()
        self.combo_mode.addItems(["Disabled", "RGB Parade", "Luma Waveform"])
        self.combo_mode.setCurrentText("Disabled")
        self.toolbar.addWidget(self.combo_mode)
        self.toolbar.addStretch()
        
        self.container_layout.addLayout(self.toolbar)
        
        self.lbl_scope = QtWidgets.QLabel()
        self.lbl_scope.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_scope.setStyleSheet("background-color: #111;")
        self.container_layout.addWidget(self.lbl_scope, 1)
        
        self.layout.addWidget(self.container)
        
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        
        self._current_image = None
        self._scope_width = 768
        self._scope_height = 256
        
        # Initialize visibility state
        self._toggle_content(False)
        
    def _toggle_content(self, checked):
        if checked:
            self.container.show()
            self._on_mode_changed()
        else:
            self.container.hide()
            self.setMinimumHeight(24) # Just the groupbox header height
            self.setMaximumHeight(24)
            
    def _on_mode_changed(self):
        if not self.isChecked():
            return
            
        if self.combo_mode.currentText() == "Disabled":
            self.lbl_scope.hide()
            self.setMinimumHeight(60) # Header + toolbar
            self.setMaximumHeight(60)
        else:
            self.lbl_scope.show()
            self.setMinimumHeight(self._expanded_min_height)
            self.setMaximumHeight(16777215) # QWIDGETSIZE_MAX
            self._refresh_display()
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_width = self.lbl_scope.width()
        if new_width > 100:
            self._scope_width = new_width
            self._refresh_display()

    def update_scopes(self, img_8u, img_8u_right=None):
        """Update scopes from one or two 8-bit RGB numpy arrays (H, W, 3)."""
        if self.combo_mode.currentText() == "Disabled":
            return
        self._current_image = img_8u
        self._current_image_right = img_8u_right
        self._refresh_display()
        
    def _refresh_display(self):
        img_left = getattr(self, '_current_image', None)
        img_right = getattr(self, '_current_image_right', None)
        
        if img_left is None and img_right is None:
            self.lbl_scope.clear()
            return
            
        mode = self.combo_mode.currentText()
        
        if img_right is not None:
            # Dual scopes (Split half width each)
            w_half = self._scope_width // 2
            
            if mode == "RGB Parade":
                arr_left = self._generate_rgb_parade(img_left, w_total=w_half)
                arr_right = self._generate_rgb_parade(img_right, w_total=w_half)
            else:
                arr_left = self._generate_luma_waveform(img_left, w_total=w_half)
                arr_right = self._generate_luma_waveform(img_right, w_total=w_half)
                
            # Concatenate and add a bright white separator line in the middle
            scope_arr = np.concatenate((arr_left, arr_right), axis=1)
            mid = scope_arr.shape[1] // 2
            scope_arr[:, mid-1:mid+1, :] = 200
        else:
            # Single scope
            if mode == "RGB Parade":
                scope_arr = self._generate_rgb_parade(img_left, w_total=self._scope_width)
            else:
                scope_arr = self._generate_luma_waveform(img_left, w_total=self._scope_width)
            
        if scope_arr is not None:
            h, w, c = scope_arr.shape
            bytes_per_line = w * c
            qimg = QtGui.QImage(scope_arr.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
            pix = QtGui.QPixmap.fromImage(qimg)
            self.lbl_scope.setPixmap(pix)

    def _generate_rgb_parade(self, img_8u, w_total=None):
        if img_8u is None:
            return np.zeros((256, w_total, 3), dtype=np.uint8)
            
        w_total = w_total or self._scope_width
        sec_w = w_total // 3
        
        img_small = cv2.resize(img_8u, (sec_w, 256), interpolation=cv2.INTER_AREA)
        parade = np.zeros((256, sec_w * 3, 3), dtype=np.uint8)
        
        for ch in range(3):
            x_offset = ch * sec_w
            for x in range(sec_w):
                counts = np.bincount(img_small[:, x, ch], minlength=256)
                intensity = np.clip(np.sqrt(counts) * 25.0, 0, 255).astype(np.uint8)
                parade[:, x + x_offset, ch] = intensity[::-1]
                
        parade[:, sec_w-1:sec_w+1, :] = 50
        parade[:, 2*sec_w-1:2*sec_w+1, :] = 50
        return parade

    def _generate_luma_waveform(self, img_8u, w_total=None):
        if img_8u is None:
            return np.zeros((256, w_total, 3), dtype=np.uint8)
            
        w_total = w_total or self._scope_width
        img_small = cv2.resize(img_8u, (w_total, 256), interpolation=cv2.INTER_AREA)
        luma = np.dot(img_small[..., :3], [0.2126, 0.7152, 0.0722]).astype(np.uint8)
        
        waveform = np.zeros((256, w_total, 3), dtype=np.uint8)
        for x in range(w_total):
            counts = np.bincount(luma[:, x], minlength=256)
            intensity = np.clip(np.sqrt(counts) * 25.0, 0, 255).astype(np.uint8)
            waveform[:, x, 1] = intensity[::-1]
        return waveform
