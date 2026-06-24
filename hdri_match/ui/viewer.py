import numpy as np

try:
    import torch
    HAS_TORCH = torch.cuda.is_available()
except ImportError:
    HAS_TORCH = False

from hdri_match.ui.qt_shim import QtWidgets, QtCore, QtGui, QOpenGLWidget


class RefLabel(QtWidgets.QLabel):
    clicked_uv = QtCore.Signal(float, float)
    
    def __init__(self, parent=None):
        super(RefLabel, self).__init__(parent)
        self.setCursor(QtCore.Qt.CrossCursor)
        
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            w, h = self.width(), self.height()
            if w > 0 and h > 0:
                self.clicked_uv.emit(event.x() / w, event.y() / h)
        super(RefLabel, self).mousePressEvent(event)

class PolyHandleItem(QtWidgets.QGraphicsRectItem):
    def __init__(self, index, parent_viewer, x, y):
        super(PolyHandleItem, self).__init__(-8, -8, 16, 16)
        self.index = index
        self.parent_viewer = parent_viewer
        self.setPos(x, y)
        self.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
        self.setBrush(QtGui.QBrush(QtGui.QColor(0, 180, 255, 200)))
        self.setZValue(100)
        self.setCursor(QtCore.Qt.SizeAllCursor)
        self._is_dragging = False
        self.setAcceptHoverEvents(True)
        
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._is_dragging = True
            event.accept()
        else:
            super(PolyHandleItem, self).mousePressEvent(event)
            
    def mouseMoveEvent(self, event):
        if self._is_dragging:
            new_pos = event.scenePos()
            self.setPos(new_pos)
            if self.parent_viewer:
                self.parent_viewer._on_poly_handle_moved(self.index, new_pos)
            event.accept()
        else:
            super(PolyHandleItem, self).mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._is_dragging:
            self._is_dragging = False
            event.accept()
            if self.parent_viewer:
                self.parent_viewer.maskDrawn.emit()
        else:
            super(PolyHandleItem, self).mouseReleaseEvent(event)

class ViewerWidget(QtWidgets.QGraphicsView):
    """
    HDR image viewer built on QGraphicsView.
    - Handles float32 linear arrays of any luminance range via auto-tone-mapping.
    - Scroll-wheel zoom, middle-mouse pan.
    - Corner overlay for reference thumbnails (Macbeth / balls).
    - Keeps tone-mapping stable so manual exposure adjustments are visible.
    - Rectangle draw mode: press R to toggle, click-drag to draw a mask region.
    - G = find hotspot, H = toggle HUD.
    """
    
    maskDrawn = QtCore.Signal()
    pixelPicked = QtCore.Signal(float, float, float)
    sunMoved = QtCore.Signal(float, float)
    transformDragStarted = QtCore.Signal()
    transformDragged = QtCore.Signal(str, float, float)

    def __init__(self, parent=None):
        super(ViewerWidget, self).__init__(parent)
        
        # Enable hardware OpenGL acceleration for the viewport
        import sys
        if not getattr(sys, 'frozen', False):
            try:
                self.setViewport(QOpenGLWidget())
                self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
            except Exception as e:
                print(f"Warning: Could not initialize OpenGL viewport - {e}")

        self.image_array = None
        self.display_mode = "sRGB"   # "sRGB" | "Linear"
        self._ev_offset = 0.0        # Stored for callers that track display EV state.
        self._viewport_ev = 0.0      # Temporary viewport-only exposure offset.

        # Display caching for fast A/B wipe redraws
        self._cache_key_u8 = None
        self._cached_u8 = None
        self._cache_key_wipe = None
        self._cached_wipe_u8 = None

        # Stable references so Qt doesn't GC our pixel data
        self._img_bytes = None
        self._q_image   = None

        # Cached 98th-percentile luminance for tone-mapping stability.
        # Computed once on reset_view=True; reused on proxy<->full-res swaps
        # so the image never jumps in brightness when sliders are dragged.
        self._cached_p98 = None

        # --- Hottest spot tracking ---
        self._hotspot_xy = None
        self._hotspot_visible = False

        # --- Rectangle/Ellipse/Polygon draw mode ---
        self._draw_mode = False
        self._mask_shape = "Rectangle"
        self._draw_start = None
        self._drawing = False
        self._draw_rect = None
        self._poly_points = []
        self._poly_drawn_points = []
        self._poly_handles = []
        self._picker_mode = False

        # --- Scene setup ---
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        # --- Hotspot marker ---
        self._hotspot_item = QtWidgets.QGraphicsEllipseItem(-6, -6, 12, 12)
        self._hotspot_item.setPen(QtGui.QPen(QtGui.QColor(255, 50, 50), 2))
        self._hotspot_item.setBrush(QtGui.QBrush(QtCore.Qt.NoBrush))
        self._hotspot_item.setZValue(10)
        self._hotspot_item.hide()
        self._scene.addItem(self._hotspot_item)

        # --- Rubber band (during draw) ---
        self._rubber_band = QtWidgets.QGraphicsRectItem()
        self._rubber_band.setPen(QtGui.QPen(QtGui.QColor(0, 180, 255, 220), 2, QtCore.Qt.DashLine))
        self._rubber_band.setBrush(QtGui.QBrush(QtGui.QColor(0, 120, 255, 40)))
        self._rubber_band.setZValue(20)
        self._rubber_band.hide()
        self._scene.addItem(self._rubber_band)
        
        self._rubber_ellipse = QtWidgets.QGraphicsEllipseItem()
        self._rubber_ellipse.setPen(QtGui.QPen(QtGui.QColor(0, 180, 255, 220), 2, QtCore.Qt.DashLine))
        self._rubber_ellipse.setBrush(QtGui.QBrush(QtGui.QColor(0, 120, 255, 40)))
        self._rubber_ellipse.setZValue(20)
        self._rubber_ellipse.hide()
        self._scene.addItem(self._rubber_ellipse)

        # --- Finalised mask rectangle ---
        self._mask_rect_item = QtWidgets.QGraphicsRectItem()
        self._mask_rect_item.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
        self._mask_rect_item.setBrush(QtGui.QBrush(QtGui.QColor(0, 220, 100, 30)))
        self._mask_rect_item.setZValue(19)
        self._mask_rect_item.hide()
        self._scene.addItem(self._mask_rect_item)
        
        self._mask_rect_item_2 = QtWidgets.QGraphicsRectItem()
        self._mask_rect_item_2.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
        self._mask_rect_item_2.setBrush(QtGui.QBrush(QtGui.QColor(0, 220, 100, 30)))
        self._mask_rect_item_2.setZValue(19)
        self._mask_rect_item_2.hide()
        self._scene.addItem(self._mask_rect_item_2)
        
        self._mask_ellipse_item = QtWidgets.QGraphicsEllipseItem()
        self._mask_ellipse_item.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
        self._mask_ellipse_item.setBrush(QtGui.QBrush(QtGui.QColor(0, 220, 100, 30)))
        self._mask_ellipse_item.setZValue(19)
        self._mask_ellipse_item.hide()
        self._scene.addItem(self._mask_ellipse_item)
        
        self._mask_ellipse_item_2 = QtWidgets.QGraphicsEllipseItem()
        self._mask_ellipse_item_2.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
        self._mask_ellipse_item_2.setBrush(QtGui.QBrush(QtGui.QColor(0, 220, 100, 30)))
        self._mask_ellipse_item_2.setZValue(19)
        self._mask_ellipse_item_2.hide()
        self._scene.addItem(self._mask_ellipse_item_2)

        self._rubber_poly = QtWidgets.QGraphicsPolygonItem()
        self._rubber_poly.setPen(QtGui.QPen(QtGui.QColor(0, 180, 255, 220), 2, QtCore.Qt.DashLine))
        self._rubber_poly.setBrush(QtGui.QBrush(QtGui.QColor(0, 120, 255, 40)))
        self._rubber_poly.setZValue(20)
        self._rubber_poly.hide()
        self._scene.addItem(self._rubber_poly)

        self._mask_poly_item = QtWidgets.QGraphicsPolygonItem()
        self._mask_poly_item.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
        self._mask_poly_item.setBrush(QtGui.QBrush(QtGui.QColor(0, 220, 100, 30)))
        self._mask_poly_item.setZValue(19)
        self._mask_poly_item.hide()
        self._scene.addItem(self._mask_poly_item)
        
        self._rubber_path = QtWidgets.QGraphicsPathItem()
        self._rubber_path.setPen(QtGui.QPen(QtGui.QColor(0, 180, 255, 220), 2))
        self._rubber_path.setZValue(20)
        self._rubber_path.hide()
        self._scene.addItem(self._rubber_path)

        self._mask_path_item = QtWidgets.QGraphicsPathItem()
        self._mask_path_item.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
        self._mask_path_item.setZValue(19)
        self._mask_path_item.hide()
        self._scene.addItem(self._mask_path_item)
        
        self._mask_path_item.hide()
        self._scene.addItem(self._mask_path_item)
        
        # --- Sun Relighting Mode ---
        self._sun_mode = False
        self._sun_source_uv = None
        self._sun_target_uv = None
        
        # --- Display Settings ---
        self.display_mode = "sRGB"
        self.use_aces_filmic = False
        
        # Sun Marker
        self._sun_source_item = QtWidgets.QGraphicsEllipseItem(-10, -10, 20, 20)
        self._sun_source_item.setPen(QtGui.QPen(QtGui.QColor(255, 200, 50, 150), 2, QtCore.Qt.DashLine))
        self._sun_source_item.setBrush(QtGui.QBrush(QtGui.QColor(255, 200, 50, 40)))
        self._sun_source_item.setZValue(25)
        self._sun_source_item.hide()
        self._scene.addItem(self._sun_source_item)
        
        self._sun_target_item = QtWidgets.QGraphicsEllipseItem(-10, -10, 20, 20)
        self._sun_target_item.setPen(QtGui.QPen(QtGui.QColor(255, 100, 50), 3))
        self._sun_target_item.setBrush(QtGui.QBrush(QtGui.QColor(255, 150, 50, 80)))
        self._sun_target_item.setZValue(26)
        self._sun_target_item.hide()
        self._scene.addItem(self._sun_target_item)
        
        self._sun_line_item = QtWidgets.QGraphicsLineItem()
        self._sun_line_item.setPen(QtGui.QPen(QtGui.QColor(255, 200, 50, 200), 2, QtCore.Qt.DotLine))
        self._sun_line_item.setZValue(24)
        self._sun_line_item.hide()
        self._scene.addItem(self._sun_line_item)
        
        # --- Background Masks (Multi-mask system) ---
        self._bg_mask_items = []

        # --- A/B Wipe ---
        self._wipe_mode = False
        self._wipe_x_ratio = 0.5
        self.wipe_image_array = None
        
        self._wipe_line_item = QtWidgets.QGraphicsLineItem()
        self._wipe_line_item.setPen(QtGui.QPen(QtGui.QColor(255, 150, 0, 255), 2))
        self._wipe_line_item.setZValue(30)
        self._wipe_line_item.hide()
        self._scene.addItem(self._wipe_line_item)

        # --- View behaviour ---
        self.setMouseTracking(True)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        self.setRenderHint(QtGui.QPainter.Antialiasing, False)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(30, 30, 30)))
        
        # FullViewportUpdate ensures rapid pixmap swaps during playback are never
        # batched/dropped by Qt's update coalescing.
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        # QOpenGLWidget is intentionally NOT used. With QGraphicsView + QGraphicsPixmapItem,
        # OpenGL gives no throughput benefit for pre-computed uint8 buffers.
        # More critically, calling viewport().repaint() from an external QTimer with
        # a QOpenGLWidget viewport requires the GL context to be current first --
        # failing silently and producing a "frozen frame" during cached playback.
        # Software rasteriser handles repaint() from any context reliably.

        # Placeholder text item when no image is loaded
        self._placeholder = self._scene.addText("No Image Loaded")
        self._placeholder.setDefaultTextColor(QtGui.QColor(80, 80, 80))
        f = self._placeholder.font()
        f.setPointSize(16)
        self._placeholder.setFont(f)

        # --- Overlay widget (top-left refs, top-right draw label, bottom-right HUD) ---
        self._overlay = QtWidgets.QWidget(self)
        self._overlay.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self._ol_layout = QtWidgets.QVBoxLayout(self._overlay)
        self._ol_layout.setContentsMargins(12, 12, 12, 12)
        self._ol_layout.setSpacing(5)
        self._ol_layout.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        # Row 1: refs title (left) + draw label (right)
        self._ol_row1 = QtWidgets.QHBoxLayout()
        self._ol_row1.setContentsMargins(0, 0, 0, 0)

        self._lbl_title = QtWidgets.QLabel("<b>References</b>")
        self._lbl_title.setStyleSheet(
            "color:#ffffff; background:rgba(0,0,0,160); "
            "padding:4px 8px; border-radius:3px;")
        self._lbl_title.hide()
        self._ol_row1.addWidget(self._lbl_title)
        self._ol_row1.addStretch()

        self._draw_label = QtWidgets.QLabel("")
        self._draw_label.setStyleSheet(
            "color:#00ccff; background:rgba(0,0,0,160); "
            "padding:4px 10px; border-radius:3px; font-weight:bold;")
        self._draw_label.hide()
        self._ol_row1.addWidget(self._draw_label)
        self._ol_layout.addLayout(self._ol_row1)

        # Reference thumbnails are now in the left panel
        
        # Spacer + bottom-right HUD
        self._pixel_hud = QtWidgets.QLabel("")
        self._pixel_hud.setStyleSheet(
            "color:#00ff88; background:rgba(0,0,0,180); "
            "padding:6px 10px; border-radius:4px; "
            "font-family:'Consolas','Courier New',monospace; font-size:12px;")
        self._pixel_hud.setAlignment(QtCore.Qt.AlignLeft)
        self._pixel_hud.hide()
        self._hud_row = QtWidgets.QHBoxLayout()
        self._hud_row.setContentsMargins(0, 0, 12, 12)
        self._hud_row.addStretch()
        self._hud_row.addWidget(self._pixel_hud)

        self._ol_layout.addStretch()
        self._ol_layout.addLayout(self._hud_row)

        self._overlay.installEventFilter(self)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------



    def _hdr_to_uint8(self, arr: np.ndarray, use_cached_p98: bool = False,
                      update_cache: bool = True, apply_ev: bool = True, override_ev: float = None) -> np.ndarray:
        """Auto-exposes and gamma-encodes linear float32 → uint8 RGB."""
        global HAS_TORCH
        
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
            
        if HAS_TORCH:
            try:
                with torch.no_grad():
                    t_img = torch.from_numpy(arr[..., :3].astype(np.float32)).cuda()
                    t_img = torch.nan_to_num(t_img, nan=0.0, posinf=65504.0, neginf=0.0)
                    
                    if apply_ev:
                        base_ev = getattr(self, '_ev_offset', 0.0) if override_ev is None else override_ev
                        ev = base_ev + getattr(self, '_viewport_ev', 0.0)
                        if ev != 0.0:
                            t_img = t_img * (2.0 ** ev)
                    
                    if self.display_mode == "sRGB":
                        if getattr(self, 'use_aces_filmic', False):
                            a, b, c, d, e_const = 2.51, 0.03, 2.43, 0.59, 0.14
                            t_img = (t_img * (a * t_img + b)) / (t_img * (c * t_img + d) + e_const)
                            t_img = torch.clamp(t_img, 0.0, 1.0)
                            t_img = torch.pow(t_img, 1.0 / 2.2)
                        else:
                            t_img = torch.clamp(t_img, 0.0, 1.0)
                            t_img = torch.pow(t_img, 1.0 / 2.2)
                    else:
                        t_img = torch.clamp(t_img, 0.0, 1.0)
                        
                    t_img = t_img * 255.0
                    return t_img.to(torch.uint8).cpu().numpy()
            except Exception as e:
                print(f"[Viewer] PyTorch GPU acceleration failed, falling back to CPU: {e}")
                HAS_TORCH = False
                
        # CPU Fallback
        img = np.array(arr[..., :3], dtype=np.float32, copy=True)
        np.nan_to_num(img, copy=False, nan=0.0, posinf=65504.0, neginf=0.0)

        if apply_ev:
            base_ev = getattr(self, '_ev_offset', 0.0) if override_ev is None else override_ev
            ev = base_ev + getattr(self, '_viewport_ev', 0.0)
            if ev != 0.0:
                img = img * (2.0 ** ev)

        if self.display_mode == "sRGB":
            if getattr(self, 'display_transform_func', None):
                img = self.display_transform_func(img)
                # Ensure the display transform doesn't leave NaNs and is clamped properly for uint8
                img = np.clip(img, 0.0, 1.0)
            elif getattr(self, 'use_aces_filmic', False):
                # ACEScg approximate filmic tone mapping (Narkowicz fit)
                a = 2.51
                b = 0.03
                c = 2.43
                d = 0.59
                e = 0.14
                img = (img * (a * img + b)) / (img * (c * img + d) + e)
                img = np.clip(img, 0.0, 1.0)
                np.power(img, 1.0 / 2.2, out=img)
            else:
                # Standard sRGB piecewise gamma
                img = np.clip(img, 0.0, 1.0)
                # Fast approximation of sRGB
                np.power(img, 1.0 / 2.2, out=img)
        else:
            np.clip(img, 0.0, 1.0, out=img)

        return (img * 255.0).astype(np.uint8)

    def _make_pixmap(self, arr: np.ndarray, use_cached_p98: bool = False,
                     update_cache: bool = True, apply_ev: bool = True, override_ev: float = None) -> QtGui.QPixmap:
        
        current_ev = getattr(self, '_ev_offset', 0.0)
        current_vp = getattr(self, '_viewport_ev', 0.0)
        key_u8 = (id(arr), current_ev, current_vp, self.display_mode, override_ev)
        
        is_dragging = getattr(self, '_vp_dragging', False)
        
        if not is_dragging and getattr(self, '_cache_key_u8', None) == key_u8 and getattr(self, '_cached_u8', None) is not None:
            u8 = self._cached_u8
        else:
            if is_dragging and max(arr.shape[:2]) > 800:
                try:
                    import cv2
                    h, w = arr.shape[:2]
                    scale = 800 / max(h, w)
                    nh, nw = int(h * scale), int(w * scale)
                    proxy_arr = cv2.resize(arr, (nw, nh), interpolation=cv2.INTER_AREA)
                    u8 = self._hdr_to_uint8(proxy_arr, use_cached_p98=use_cached_p98,
                                                  update_cache=update_cache, apply_ev=apply_ev, override_ev=override_ev)
                    self._current_pixmap_scale = 1.0 / scale
                except ImportError:
                    u8 = self._hdr_to_uint8(arr, use_cached_p98=use_cached_p98,
                                            update_cache=update_cache, apply_ev=apply_ev, override_ev=override_ev)
            else:
                u8 = self._hdr_to_uint8(arr, use_cached_p98=use_cached_p98,
                                        update_cache=update_cache, apply_ev=apply_ev, override_ev=override_ev)
                
            if not is_dragging:
                self._cached_u8 = u8
                self._cache_key_u8 = key_u8
                                
        if getattr(self, '_wipe_mode', False) and getattr(self, 'wipe_image_array', None) is not None:
            try:
                key_wipe = (id(self.wipe_image_array), current_ev, current_vp, self.display_mode, override_ev)
                if getattr(self, '_cache_key_wipe', None) == key_wipe and getattr(self, '_cached_wipe_u8', None) is not None:
                    wipe_u8 = self._cached_wipe_u8
                else:
                    wipe_u8 = self._hdr_to_uint8(self.wipe_image_array, use_cached_p98=use_cached_p98,
                                                 update_cache=False, apply_ev=apply_ev, override_ev=override_ev)
                    self._cached_wipe_u8 = wipe_u8
                    self._cache_key_wipe = key_wipe

                h, w = u8.shape[:2]
                split_x = int(w * getattr(self, '_wipe_x_ratio', 0.5))
                u8_comp = u8.copy()
                if wipe_u8.shape == u8_comp.shape:
                    u8_comp[:, :split_x] = wipe_u8[:, :split_x]
                u8 = u8_comp
                self._wipe_line_item.setLine(split_x, 0, split_x, h)
                self._wipe_line_item.show()
            except Exception as e:
                print(f"[Viewer] Wipe error: {e}")
                self._wipe_line_item.hide()
        else:
            if hasattr(self, '_wipe_line_item'):
                self._wipe_line_item.hide()
                                
        self.last_8u = u8
        h, w, c = u8.shape
        raw = u8.tobytes()
        qimg = QtGui.QImage(raw, w, h, w * c, QtGui.QImage.Format_RGB888)
        self._img_bytes = raw
        self._q_image = qimg
        if qimg.isNull():
            print(f"[Viewer] WARNING: QImage is null! shape={u8.shape}")
        return QtGui.QPixmap.fromImage(qimg)

    def _fit_view(self):
        rect = self._pixmap_item.boundingRect()
        if rect.isNull():
            return
        self.fitInView(rect, QtCore.Qt.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Rectangle draw public API
    # ------------------------------------------------------------------

    def has_mask_rect(self) -> bool:
        return self._draw_rect is not None

    def get_mask_rect_normalized(self):
        """
        Returns the drawn shape in NORMALIZED coords as
        (nx1, ny1, nx2, ny2) where values are 0.0 to 1.0.
        """
        if self._draw_rect is None or self.image_array is None:
            return None
        h, w = self.image_array.shape[:2]
        rx1, ry1, rx2, ry2 = self._draw_rect  # already sorted by mouseReleaseEvent
        x1, x2 = min(rx1, rx2), max(rx1, rx2)
        y1, y2 = min(ry1, ry2), max(ry1, ry2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
            
        nx1, nx2 = float(x1) / w, float(x2) / w
        ny1, ny2 = float(y1) / h, float(y2) / h
        
        yaw = getattr(self, '_mask_yaw', 0.0)
        if yaw > 0.0:
            shift = yaw / 360.0
            nx1 = (nx1 - shift)
            nx2 = (nx2 - shift)
            
        return (nx1, ny1, nx2, ny2)

    def get_mask_points_normalized(self):
        if not self._poly_points or self.image_array is None:
            return None
        h, w = self.image_array.shape[:2]
        yaw = getattr(self, '_mask_yaw', 0.0)
        shift = yaw / 360.0 if yaw > 0.0 else 0.0
        
        norm_pts = []
        for (x, y) in self._poly_points:
            nx, ny = float(x) / w, float(y) / h
            if shift > 0.0:
                nx = (nx - shift)
            norm_pts.append((nx, ny))
        return norm_pts

    def set_mask_rect_normalized(self, rect):
        """Set the active draw rect from normalized unrotated coordinates."""
        if not rect or self.image_array is None:
            self.clear_mask_rect()
            return
            
        nx1, ny1, nx2, ny2 = rect
        yaw = getattr(self, '_mask_yaw', 0.0)
        if yaw > 0.0:
            shift = yaw / 360.0
            nx1 = (nx1 + shift)
            nx2 = (nx2 + shift)
            
        h, w = self.image_array.shape[:2]
        rx1, rx2 = nx1 * w, nx2 * w
        ry1, ry2 = ny1 * h, ny2 * h
        
        # QGraphicsRectItem can handle rx1 > rx2 visually, but it's cleaner to sort for drawing
        # If it wraps, we draw two parts
        
        self._draw_rect = (rx1, ry1, rx2, ry2)
        self._mask_rect_item.hide()
        self._mask_rect_item_2.hide()
        self._mask_ellipse_item.hide()
        self._mask_ellipse_item_2.hide()
        self._mask_poly_item.hide()
        if hasattr(self, '_mask_path_item'):
            self._mask_path_item.hide()
            
        wrap = rx1 > rx2
        ry_min, ry_max = min(ry1, ry2), max(ry1, ry2)
        h_rect = ry_max - ry_min
        
        if getattr(self, '_mask_shape', "Rectangle") == "Ellipse":
            if wrap:
                # Drawing an ellipse split in two is tricky with QGraphicsEllipseItem
                # We'll draw two arcs using bounding boxes that go off-screen
                # Left part (from rx1 to w): width is (rx2 + w - rx1)
                full_w = rx2 + w - rx1
                self._mask_ellipse_item.setRect(rx1, ry_min, full_w, h_rect)
                self._mask_ellipse_item.show()
                # Right part (from 0 to rx2):
                self._mask_ellipse_item_2.setRect(rx1 - w, ry_min, full_w, h_rect)
                self._mask_ellipse_item_2.show()
            else:
                self._mask_ellipse_item.setRect(min(rx1,rx2), ry_min, abs(rx2-rx1), h_rect)
                self._mask_ellipse_item.show()
        elif getattr(self, '_mask_shape', "Rectangle") == "Rectangle":
            if wrap:
                self._mask_rect_item.setRect(rx1, ry_min, w - rx1, h_rect)
                self._mask_rect_item.show()
                self._mask_rect_item_2.setRect(0, ry_min, rx2, h_rect)
                self._mask_rect_item_2.show()
            else:
                self._mask_rect_item.setRect(min(rx1,rx2), ry_min, abs(rx2-rx1), h_rect)
                self._mask_rect_item.show()

    def set_mask_points_normalized(self, points):
        if not points or self.image_array is None:
            self.clear_mask_rect()
            return
        
        h, w = self.image_array.shape[:2]
        yaw = getattr(self, '_mask_yaw', 0.0)
        shift = yaw / 360.0 if yaw > 0.0 else 0.0
        
        self._poly_points = []
        qpts = []
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        
        for pt in points:
            if pt is None:
                self._poly_points.append(None)
                qpts.append(None)
            else:
                nx, ny = pt
                if shift > 0.0:
                    nx = (nx + shift)
                rx, ry = nx * w, ny * h
                self._poly_points.append((rx, ry))
                qpts.append(QtCore.QPointF(rx, ry))
                min_x = min(min_x, rx)
                max_x = max(max_x, rx)
                min_y = min(min_y, ry)
                max_y = max(max_y, ry)
            
        self._draw_rect = (min_x, min_y, max_x, max_y)
        self._mask_rect_item.hide()
        self._mask_rect_item_2.hide()
        self._mask_ellipse_item.hide()
        self._mask_ellipse_item_2.hide()
        if hasattr(self, '_mask_path_item'):
            self._mask_path_item.hide()
        
        if getattr(self, '_mask_shape', "Rectangle") in ["Polygon", "Lasso"]:
            self._mask_poly_item.setPolygon(QtGui.QPolygonF(qpts))
            self._mask_poly_item.show()
            self._update_poly_handles()
        elif getattr(self, '_mask_shape', "Rectangle") == "Brush":
            path = QtGui.QPainterPath()
            is_new_stroke = True
            for p in qpts:
                if p is None:
                    is_new_stroke = True
                    continue
                if is_new_stroke:
                    path.moveTo(p)
                    is_new_stroke = False
                else:
                    path.lineTo(p)
            self._mask_path_item.setPath(path)
            
            if getattr(self, '_brush_size_norm', 0.0) > 0.0 and self.image_array is not None:
                w = self.image_array.shape[1]
                px_size = max(2.0, self._brush_size_norm * w)
                pen = QtGui.QPen(QtGui.QColor(0, 220, 100, 220), px_size)
                pen.setCapStyle(QtCore.Qt.RoundCap)
                pen.setJoinStyle(QtCore.Qt.RoundJoin)
                self._mask_path_item.setPen(pen)
            else:
                self._mask_path_item.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
                
            self._mask_path_item.show()

    def set_draw_mode(self, enabled: bool, shape: str = "Rectangle", brush_size_norm: float = 0.0):
        """Enable/disable rectangle/ellipse draw mode."""
        self._draw_mode = enabled
        self._mask_shape = shape
        self._brush_size_norm = brush_size_norm
        
        # Update existing pen if path item is active
        if shape == "Brush" and hasattr(self, '_mask_path_item') and self.image_array is not None:
            w = self.image_array.shape[1]
            px_size = max(2.0, brush_size_norm * w)
            pen = QtGui.QPen(QtGui.QColor(0, 220, 100, 220), px_size)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            self._mask_path_item.setPen(pen)
            
        self.setCursor(QtCore.Qt.CrossCursor if enabled else QtCore.Qt.ArrowCursor)
        
    def set_picker_mode(self, enabled: bool):
        self._picker_mode = enabled
        if enabled:
            self.setCursor(QtCore.Qt.CrossCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
        if not enabled:
            # Exit drawing without committing
            self._drawing = False
            self._draw_start = None
            self._poly_drawn_points = []
            self._rubber_band.hide()
            self._rubber_ellipse.hide()
            self._rubber_poly.hide()
            if hasattr(self, '_rubber_path'):
                self._rubber_path.hide()
            self._draw_label.hide()
        else:
            self._draw_label.setText(f"DRAW: click-drag {shape.lower()}")
            self._draw_label.show()

    def set_sun_mode(self, enabled: bool):
        self._sun_mode = enabled
        if enabled:
            self.setCursor(QtCore.Qt.CrossCursor)
            self._draw_label.setText("SUN RELIGHT: Click & Drag to move sun")
            self._draw_label.show()
            if self._sun_source_uv:
                self._sun_source_item.show()
                self._sun_target_item.show()
                self._sun_line_item.show()
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
            self._draw_label.hide()
            self._sun_source_item.hide()
            self._sun_target_item.hide()
            self._sun_line_item.hide()

    def set_transform_mode(self, mode_type: str):
        # mode_type can be "Translate", "Scale", "Rotate", or None/False
        self._transform_mode = mode_type
        if mode_type:
            self._draw_label.setText(f"TRANSFORM: Click & Drag to {mode_type.lower()} mask")
            self._draw_label.show()
            # Disable other modes
            self._draw_mode = False
            self._sun_mode = False
            
            if mode_type == "Translate":
                self.setCursor(QtCore.Qt.SizeAllCursor)
            elif mode_type == "Scale":
                self.setCursor(QtCore.Qt.SizeFDiagCursor)
            elif mode_type == "Rotate":
                self.setCursor(QtCore.Qt.CrossCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
            self._draw_label.hide()

    def set_sun_positions(self, source_u, source_v, target_u, target_v, from_pipeline=False):
        if from_pipeline and getattr(self, '_drawing', False):
            return  # Prevent pipeline updates from snapping the handle while user is actively dragging
        
        self._sun_source_uv = (source_u, source_v)
        self._sun_target_uv = (target_u, target_v)
        if self.image_array is not None:
            h, w = self.image_array.shape[:2]
            yaw_norm = getattr(self, '_mask_yaw', 0.0) / 360.0
            
            vis_source_u = (source_u + yaw_norm) % 1.0
            vis_target_u = (target_u + yaw_norm) % 1.0
            
            sx, sy = vis_source_u * w, source_v * h
            tx, ty = vis_target_u * w, target_v * h
            self._sun_source_item.setPos(sx, sy)
            self._sun_target_item.setPos(tx, ty)
            
            # Draw line directly between them if they don't wrap around the edge
            if abs(vis_target_u - vis_source_u) < 0.5:
                self._sun_line_item.setLine(sx, sy, tx, ty)
            else:
                self._sun_line_item.setLine(tx, ty, tx, ty) # Hide line if it wraps
                
            
            if self._sun_mode:
                self._sun_source_item.show()
                self._sun_target_item.show()
                self._sun_line_item.show()

    def clear_mask_rect(self):
        """Remove the drawn mask."""
        self._draw_rect = None
        self._poly_points = []
        self._mask_rect_item.hide()
        self._mask_rect_item_2.hide()
        self._mask_ellipse_item.hide()
        self._mask_ellipse_item_2.hide()
        if hasattr(self, '_mask_poly_item'):
            self._mask_poly_item.hide()
        if hasattr(self, '_mask_path_item'):
            self._mask_path_item.hide()
        self._clear_poly_handles()

    def _clear_poly_handles(self):
        for h in self._poly_handles:
            self._scene.removeItem(h)
        self._poly_handles.clear()

    def _update_poly_handles(self):
        self._clear_poly_handles()
        # Only show handles for Polygon, not Lasso or Brush (too many points)
        if getattr(self, '_mask_shape', "Rectangle") == "Polygon":
            for i, (x, y) in enumerate(self._poly_points):
                handle = PolyHandleItem(i, self, x, y)
                self._scene.addItem(handle)
                self._poly_handles.append(handle)

    def _on_poly_handle_moved(self, index, new_pos):
        if 0 <= index < len(self._poly_points):
            self._poly_points[index] = (new_pos.x(), new_pos.y())
            qpts = [QtCore.QPointF(x, y) for (x, y) in self._poly_points]
            self._mask_poly_item.setPolygon(QtGui.QPolygonF(qpts))

    def set_bg_masks(self, masks_info):
        """
        Draw inactive background masks.
        masks_info: list of dicts: {'rect': (nx1, ny1, nx2, ny2), 'shape': 'Rectangle'}
        """
        for item in self._bg_mask_items:
            self._scene.removeItem(item)
        self._bg_mask_items.clear()
        
        if self.image_array is None:
            return
            
        h, w = self.image_array.shape[:2]
        
        yaw = getattr(self, '_mask_yaw', 0.0)
        shift = yaw / 360.0 if yaw > 0.0 else 0.0
        
        for m in masks_info:
            nx1, ny1, nx2, ny2 = m['rect']
            shape = m.get('shape', 'Rectangle')
            
            if shift > 0.0:
                nx1 = (nx1 + shift) % 1.0
                nx2 = (nx2 + shift) % 1.0
                
            rx1, ry1 = nx1 * w, ny1 * h
            rx2, ry2 = nx2 * w, ny2 * h
            
            x, y = min(rx1, rx2), min(ry1, ry2)
            rw, rh = abs(rx2 - rx1), abs(ry2 - ry1)
            
            if shape in ["Polygon", "Lasso", "Brush"]:
                # For background masks, if it's a polygon/lasso/brush, we need the points
                points = m.get('points')
                if points:
                    qpts = []
                    for (nx, ny) in points:
                        if shift > 0.0:
                            nx = (nx + shift) % 1.0
                        qpts.append(QtCore.QPointF(nx * w, ny * h))
                    if shape == "Brush":
                        path = QtGui.QPainterPath(qpts[0])
                        for p in qpts[1:]:
                            path.lineTo(p)
                        item = QtWidgets.QGraphicsPathItem(path)
                        
                        b_norm = m.get('brush_size_norm', 0.0)
                        if b_norm > 0.0:
                            px_size = max(2.0, b_norm * w)
                            pen = QtGui.QPen(QtGui.QColor(100, 100, 100, 180), px_size)
                            pen.setCapStyle(QtCore.Qt.RoundCap)
                            pen.setJoinStyle(QtCore.Qt.RoundJoin)
                            item.setPen(pen)
                        else:
                            item.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 180), 2))
                            
                        item.setZValue(18)
                        self._scene.addItem(item)
                        self._bg_mask_items.append(item)
                        continue
                    else:
                        item = QtWidgets.QGraphicsPolygonItem(QtGui.QPolygonF(qpts))
                else:
                    if rx1 > rx2:
                        item = QtWidgets.QGraphicsRectItem(rx1, y, w - rx1, rh)
                        item2 = QtWidgets.QGraphicsRectItem(0, y, rx2, rh)
                        item2.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 180), 2, QtCore.Qt.DashLine))
                        item2.setBrush(QtGui.QBrush(QtGui.QColor(100, 100, 100, 20)))
                        item2.setZValue(18)
                        self._scene.addItem(item2)
                        self._bg_mask_items.append(item2)
                    else:
                        item = QtWidgets.QGraphicsRectItem(x, y, rw, rh)
            elif shape == "Ellipse":
                if rx1 > rx2:
                    full_w = rx2 + w - rx1
                    item = QtWidgets.QGraphicsEllipseItem(rx1, y, full_w, rh)
                    item2 = QtWidgets.QGraphicsEllipseItem(rx1 - w, y, full_w, rh)
                    item2.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 180), 2, QtCore.Qt.DashLine))
                    item2.setBrush(QtGui.QBrush(QtGui.QColor(100, 100, 100, 20)))
                    item2.setZValue(18)
                    self._scene.addItem(item2)
                    self._bg_mask_items.append(item2)
                else:
                    item = QtWidgets.QGraphicsEllipseItem(x, y, rw, rh)
            else:
                if rx1 > rx2:
                    item = QtWidgets.QGraphicsRectItem(rx1, y, w - rx1, rh)
                    item2 = QtWidgets.QGraphicsRectItem(0, y, rx2, rh)
                    item2.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 180), 2, QtCore.Qt.DashLine))
                    item2.setBrush(QtGui.QBrush(QtGui.QColor(100, 100, 100, 20)))
                    item2.setZValue(18)
                    self._scene.addItem(item2)
                    self._bg_mask_items.append(item2)
                else:
                    item = QtWidgets.QGraphicsRectItem(x, y, rw, rh)
                
            item.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 180), 2, QtCore.Qt.DashLine))
            item.setBrush(QtGui.QBrush(QtGui.QColor(100, 100, 100, 20)))
            item.setZValue(18)
            self._scene.addItem(item)
            self._bg_mask_items.append(item)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def invalidate_tone_cache(self):
        pass

    def set_tone_reference(self, reference_array):
        pass

    def set_ev_offset(self, ev_offset: float):
        self._ev_offset = ev_offset

    def set_viewport_ev(self, ev_offset: float, dragging: bool = False):
        self._viewport_ev = ev_offset
        self._vp_dragging = dragging
        self.update_display()

    def set_image(self, image_array, ev_offset=0.0, reset_view=True, wipe_image_array=None):
        self._ev_offset = ev_offset
        self.wipe_image_array = wipe_image_array

        old_shape = self.image_array.shape[:2] if self.image_array is not None else None
        old_h, old_w = old_shape if old_shape else (0, 0)

        # ------------------------------------------------------------------
        # Capture view state BEFORE anything changes.
        # Strategy:
        #   • Same image size (normal slider drag): save/restore the full
        #     QTransform + raw scrollbar integers — pixel-perfect, no drift.
        #   • Different size (proxy <-> full-res swap): scale only m11/m22
        #     proportionally and re-centre on the relative scene point.
        # ------------------------------------------------------------------
        saved_transform = None
        saved_hscroll   = None
        saved_vscroll   = None
        rel_center      = None

        if not reset_view and old_w > 0:
            saved_transform = self.transform()
            saved_hscroll   = self.horizontalScrollBar().value()
            saved_vscroll   = self.verticalScrollBar().value()
            vp_center    = self.viewport().rect().center()
            scene_center = self.mapToScene(vp_center)
            rel_center   = (scene_center.x() / old_w, scene_center.y() / old_h)

        self.image_array = image_array

        self._scene.setSceneRect(QtCore.QRectF())
        if image_array is None:
            self._pixmap_item.setPixmap(QtGui.QPixmap())
            self._placeholder.setVisible(True)
            return

        self._placeholder.setVisible(False)

        if reset_view:
            # Fresh load: clear cached p98 so it's recomputed for this image
            self._cached_p98 = None

        new_h, new_w = self.image_array.shape[:2]

        self._current_pixmap_scale = 1.0
        pix = self._make_pixmap(image_array, use_cached_p98=(not reset_view))
        self._pixmap_item.setPixmap(pix)
        self._pixmap_item.setScale(self._current_pixmap_scale)
        self._scene.setSceneRect(0, 0, new_w, new_h)

        if reset_view:
            self._fit_view()
            return

        if saved_transform is None:
            return

        if old_w == new_w and old_h == new_h:
            # ── Same size: restore transform + scroll exactly (zero drift) ──
            self.setTransform(saved_transform)
            self.horizontalScrollBar().setValue(saved_hscroll)
            self.verticalScrollBar().setValue(saved_vscroll)
        else:
            # ── Size changed: scale zoom proportionally, re-centre ──
            ratio    = old_w / new_w if new_w > 0 else 1.0
            zoom_x   = saved_transform.m11() * ratio
            zoom_y   = saved_transform.m22() * ratio
            self.setTransform(QtGui.QTransform.fromScale(zoom_x, zoom_y))
            if rel_center is not None:
                self.centerOn(QtCore.QPointF(
                    rel_center[0] * new_w,
                    rel_center[1] * new_h
                ))

    def set_image_u8(self, u8: np.ndarray):
        """Fast-path for cached playback: display a pre-rendered uint8 (H,W,3) frame.

        Unlike set_image(), this skips HDR tone-mapping entirely.  It also
        updates ALL internal viewer state so that any subsequent repaint
        triggered by mouse-move, overlay paint or resize will display THIS
        frame rather than re-rendering from the stale float32 image_array.
        """
        if u8 is None or not hasattr(self, '_pixmap_item'):
            return

        h, w, c = u8.shape
        raw = u8.tobytes()
        qimg = QtGui.QImage(raw, w, h, w * c, QtGui.QImage.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(qimg)

        # Update pixmap and scene rect
        self._pixmap_item.setPixmap(pix)
        self._scene.setSceneRect(0, 0, w, h)

        # Keep internal bookkeeping consistent so update_display() / any overlay
        # repaint uses this frame, not the previous float32 image_array.
        self.last_8u = u8
        self._img_bytes = raw
        self._q_image = qimg

        # Poison the u8 pixel cache so the next _make_pixmap() call (e.g. after
        # a zoom event) recomputes from image_array rather than serving stale data.
        self._cached_u8 = u8
        self._cache_key_u8 = None  # invalidate key so next HDR render recomputes

        # Synchronous repaint — with software rasteriser this is immediate.
        self.viewport().repaint()

    def set_references(self, macbeth=None, chrome=None, grey=None):
        pass # Moving to main_window.py

    def reset_view(self):
        self._fit_view()

    def update_display(self):
        if self.image_array is not None:
            self.set_image(self.image_array, ev_offset=self._ev_offset, reset_view=False, wipe_image_array=getattr(self, 'wipe_image_array', None))

    # ------------------------------------------------------------------
    # Pixel / hotspot helpers
    # ------------------------------------------------------------------

    def _get_pixel_at(self, viewport_x: int, viewport_y: int):
        if self.image_array is None:
            return None
        scene_pt = self.mapToScene(viewport_x, viewport_y)
        px = int(round(scene_pt.x()))
        py = int(round(scene_pt.y()))
        h, w = self.image_array.shape[:2]
        if px < 0 or px >= w or py < 0 or py >= h:
            return None
        r, g, b = self.image_array[py, px, :3].tolist()
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return (px, py, r, g, b, luma)

    def _build_pixel_hud_text(self, px, py, r, g, b, luma):
        ev = np.log2(max(luma / 0.18, 1e-8))
        return (
            f"<b>XY</b> ({px}, {py})  "
            f"<b>R</b> {r:.4f}  <b>G</b> {g:.4f}  <b>B</b> {b:.4f}  "
            f"<b>Luma</b> {luma:.4f}  <b>EV</b> {ev:+.2f}"
        )

    def _find_and_show_hotspot(self):
        if self.image_array is None:
            return
        luma = (0.2126 * self.image_array[..., 0]
              + 0.7152 * self.image_array[..., 1]
              + 0.0722 * self.image_array[..., 2])
        flat_idx = int(np.argmax(luma))
        py, px = divmod(flat_idx, luma.shape[1])
        r, g, b = self.image_array[py, px, :3].tolist()
        peak_luma = float(luma[py, px])
        ev = np.log2(max(peak_luma / 0.18, 1e-8))
        self._hotspot_xy = (px, py)
        self._hotspot_item.setPos(px, py)
        self._hotspot_item.show()
        self._hotspot_visible = True
        self._pixel_hud.setText(
            f"<b style='color:#ff4444;'>HOTSPOT</b> "
            f"<b>XY</b> ({px}, {py})  "
            f"<b>R</b> {r:.4f}  <b>G</b> {g:.4f}  <b>B</b> {b:.4f}  "
            f"<b>Luma</b> {peak_luma:.2f}  <b>EV</b> {ev:+.2f}"
        )
        self._pixel_hud.show()

    # ------------------------------------------------------------------
    # Qt events — zoom, pan, pixel info, rectangle draw
    # ------------------------------------------------------------------

    def mouseMoveEvent(self, event):
        super(ViewerWidget, self).mouseMoveEvent(event)

        # Sun relighting drag
        if getattr(self, '_sun_mode', False) and getattr(self, '_drawing', False):
            scene_pt = self.mapToScene(event.x(), event.y())
            if self.image_array is not None:
                h, w = self.image_array.shape[:2]
                
                vis_u = max(0.0, min(1.0, scene_pt.x() / w))
                v = max(0.0, min(1.0, scene_pt.y() / h))
                
                yaw_norm = getattr(self, '_mask_yaw', 0.0) / 360.0
                unrotated_u = (vis_u - yaw_norm) % 1.0
                
                if self._sun_source_uv:
                    self.set_sun_positions(self._sun_source_uv[0], self._sun_source_uv[1], unrotated_u, v)
            return

        # A/B wipe drag
        if getattr(self, '_wipe_mode', False) and (event.buttons() & QtCore.Qt.LeftButton) and self.image_array is not None:
            scene_pt = self.mapToScene(event.x(), event.y())
            w = self.image_array.shape[1]
            self._wipe_x_ratio = max(0.0, min(1.0, scene_pt.x() / w))
            self.update_display()
            return

        # Transform drag
        if getattr(self, '_transform_mode', False) and getattr(self, '_transform_start', None) is not None:
            scene_pt = self.mapToScene(event.x(), event.y())
            dx = scene_pt.x() - self._transform_start.x()
            dy = scene_pt.y() - self._transform_start.y()
            
            self.transformDragged.emit(self._transform_mode, dx, dy)
            return

        # If drawing, update rubber band
        if self._draw_mode and self._drawing:
            scene_pt = self.mapToScene(event.x(), event.y())
            self._rubber_band.hide()
            self._rubber_ellipse.hide()
            self._rubber_poly.hide()
            if hasattr(self, '_rubber_path'):
                self._rubber_path.hide()
            
            if self._mask_shape == "Polygon":
                pts = self._poly_drawn_points + [QtCore.QPointF(scene_pt.x(), scene_pt.y())]
                poly = QtGui.QPolygonF(pts)
                self._rubber_poly.setPolygon(poly)
                self._rubber_poly.show()
            elif self._mask_shape in ["Lasso", "Brush"]:
                self._poly_drawn_points.append(QtCore.QPointF(scene_pt.x(), scene_pt.y()))
                path = self._rubber_path.path()
                path.lineTo(scene_pt.x(), scene_pt.y())
                self._rubber_path.setPath(path)
                self._rubber_path.show()
            elif self._draw_start is not None:
                x1, y1 = self._draw_start
                x2, y2 = scene_pt.x(), scene_pt.y()
                rx, ry, rw, rh = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
                
                if self._mask_shape == "Ellipse":
                    self._rubber_ellipse.setRect(rx, ry, rw, rh)
                    self._rubber_ellipse.show()
                else:
                    self._rubber_band.setRect(rx, ry, rw, rh)
                    self._rubber_band.show()
            return  # Don't update pixel HUD while drawing

        # Normal pixel HUD update
        pixel = self._get_pixel_at(event.x(), event.y())
        if pixel is not None:
            px, py, r, g, b, luma = pixel
            txt = self._build_pixel_hud_text(px, py, r, g, b, luma)
            self._pixel_hud.setText(txt)
            self._pixel_hud.show()
            if self._hotspot_visible:
                self._hotspot_item.hide()
        else:
            if self.image_array is None:
                self._pixel_hud.hide()

    def keyPressEvent(self, event):
        """F = frame view, G = hotspot, H = toggle HUD, D = toggle draw mode, Q = clear mask, W = toggle wipe, T = translate, R = rotate, S = scale."""
        if event.key() == QtCore.Qt.Key_G:
            self._find_and_show_hotspot()
        elif event.key() == QtCore.Qt.Key_H:
            self._pixel_hud.setVisible(not self._pixel_hud.isVisible())
        elif event.key() == QtCore.Qt.Key_D:
            self.set_draw_mode(not self._draw_mode)
        elif event.key() == QtCore.Qt.Key_Q:
            self.clear_mask_rect()
        elif event.key() == QtCore.Qt.Key_T:
            self.set_transform_mode("Translate" if getattr(self, '_transform_mode', None) != "Translate" else None)
        elif event.key() == QtCore.Qt.Key_R:
            self.set_transform_mode("Rotate" if getattr(self, '_transform_mode', None) != "Rotate" else None)
        elif event.key() == QtCore.Qt.Key_S:
            self.set_transform_mode("Scale" if getattr(self, '_transform_mode', None) != "Scale" else None)
        elif event.key() == QtCore.Qt.Key_W:
            if getattr(self, 'wipe_image_array', None) is not None:
                self._wipe_mode = not getattr(self, '_wipe_mode', False)
                self.update_display()
        elif event.key() == QtCore.Qt.Key_F:
            self._fit_view()
        else:
            super(ViewerWidget, self).keyPressEvent(event)

    def wheelEvent(self, event):
        factor = 1.18 if event.angleDelta().y() > 0 else (1.0 / 1.18)
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        # Check if we clicked on a poly handle first
        if event.button() == QtCore.Qt.LeftButton:
            for item in self.items(event.pos()):
                if isinstance(item, PolyHandleItem):
                    super(ViewerWidget, self).mousePressEvent(event)
                    return

        # Middle-mouse = pan
        if event.button() == QtCore.Qt.MiddleButton:
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
            fake = QtGui.QMouseEvent(
                QtCore.QEvent.MouseButtonPress, event.pos(),
                QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
            super(ViewerWidget, self).mousePressEvent(fake)
            return

        # Left-click in sun relight mode
        if event.button() == QtCore.Qt.LeftButton and getattr(self, '_sun_mode', False) and self.image_array is not None:
            scene_pt = self.mapToScene(event.x(), event.y())
            h, w = self.image_array.shape[:2]
            vis_u = max(0.0, min(1.0, scene_pt.x() / w))
            v = max(0.0, min(1.0, scene_pt.y() / h))
            
            yaw_norm = getattr(self, '_mask_yaw', 0.0) / 360.0
            unrotated_u = (vis_u - yaw_norm) % 1.0
            
            if self._sun_source_uv is None:
                self._sun_source_uv = (unrotated_u, v)
            self.set_sun_positions(self._sun_source_uv[0], self._sun_source_uv[1], unrotated_u, v)
            self._drawing = True # reuse drawing flag to track drag
            return

        # A/B wipe drag start
        if event.button() == QtCore.Qt.LeftButton and getattr(self, '_wipe_mode', False) and self.image_array is not None:
            scene_pt = self.mapToScene(event.x(), event.y())
            w = self.image_array.shape[1]
            self._wipe_x_ratio = max(0.0, min(1.0, scene_pt.x() / w))
            self.update_display()
            return

        # Transform drag start
        if event.button() == QtCore.Qt.LeftButton and getattr(self, '_transform_mode', False) and self.image_array is not None:
            if self._draw_rect or self._poly_points:
                self._transform_start = self.mapToScene(event.x(), event.y())
                self.transformDragStarted.emit()
                return

        # Left-click in draw mode = start drawing or add polygon point
        if event.button() == QtCore.Qt.LeftButton and self._draw_mode and self.image_array is not None:
            scene_pt = self.mapToScene(event.x(), event.y())
            if self._mask_shape in ["Polygon", "Lasso", "Brush"]:
                if self._mask_shape == "Polygon" and not self._drawing:
                    self._drawing = True
                    self._poly_drawn_points = [QtCore.QPointF(scene_pt.x(), scene_pt.y())]
                    pts = self._poly_drawn_points + [QtCore.QPointF(scene_pt.x(), scene_pt.y())]
                    self._rubber_poly.setPolygon(QtGui.QPolygonF(pts))
                    self._rubber_poly.show()
                elif self._mask_shape == "Polygon":
                    self._poly_drawn_points.append(QtCore.QPointF(scene_pt.x(), scene_pt.y()))
                    pts = self._poly_drawn_points + [QtCore.QPointF(scene_pt.x(), scene_pt.y())]
                    self._rubber_poly.setPolygon(QtGui.QPolygonF(pts))
                    self._rubber_poly.show()
                else: # Lasso, Brush
                    self._drawing = True
                    if self._mask_shape == "Brush" and getattr(self, '_poly_drawn_points', None):
                        self._poly_drawn_points.append(None)
                        self._poly_drawn_points.append(QtCore.QPointF(scene_pt.x(), scene_pt.y()))
                        path = self._rubber_path.path()
                        path.moveTo(scene_pt.x(), scene_pt.y())
                    else:
                        self._poly_drawn_points = [QtCore.QPointF(scene_pt.x(), scene_pt.y())]
                        path = QtGui.QPainterPath(QtCore.QPointF(scene_pt.x(), scene_pt.y()))
                        
                    self._rubber_path.setPath(path)
                    
                    if self._mask_shape == "Brush" and getattr(self, '_brush_size_norm', 0.0) > 0.0 and self.image_array is not None:
                        w = self.image_array.shape[1]
                        px_size = max(2.0, self._brush_size_norm * w)
                        pen = QtGui.QPen(QtGui.QColor(0, 180, 255, 220), px_size)
                        pen.setCapStyle(QtCore.Qt.RoundCap)
                        pen.setJoinStyle(QtCore.Qt.RoundJoin)
                        self._rubber_path.setPen(pen)
                    else:
                        self._rubber_path.setPen(QtGui.QPen(QtGui.QColor(0, 180, 255, 220), 2))
                        
                    self._rubber_path.show()
                return
            else:
                self._draw_start = (int(round(scene_pt.x())), int(round(scene_pt.y())))
                self._drawing = True
                return
                
        # Right-click in draw mode = finish polygon
        if event.button() == QtCore.Qt.RightButton and self._draw_mode and self._mask_shape == "Polygon" and self._drawing:
            self._finish_polygon()
            return

        # Left-click in picker mode
        if event.button() == QtCore.Qt.LeftButton and self._picker_mode and self.image_array is not None:
            return # Wait for release to sample

        super(ViewerWidget, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Middle-mouse release
        if event.button() == QtCore.Qt.MiddleButton:
            fake = QtGui.QMouseEvent(
                QtCore.QEvent.MouseButtonRelease, event.pos(),
                QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
            super(ViewerWidget, self).mouseReleaseEvent(fake)
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
            return

        # Left-click release in sun mode
        if event.button() == QtCore.Qt.LeftButton and getattr(self, '_sun_mode', False) and getattr(self, '_drawing', False):
            self._drawing = False
            if self._sun_target_uv:
                self.sunMoved.emit(self._sun_target_uv[0], self._sun_target_uv[1])
            return

        # Transform release
        if event.button() == QtCore.Qt.LeftButton and getattr(self, '_transform_mode', False) and getattr(self, '_transform_start', None) is not None:
            self._transform_start = None
            self.maskDrawn.emit()
            return

        # Left-click release in draw mode = finalise shape (only for Rect/Ellipse/Lasso/Brush)
        if event.button() == QtCore.Qt.LeftButton and self._drawing:
            if self._mask_shape in ["Lasso", "Brush"]:
                self._finish_polygon()
                return
            if self._mask_shape == "Polygon":
                return
                
            if self._draw_start is not None:
                self._drawing = False
                scene_pt = self.mapToScene(event.x(), event.y())
                x1, y1 = self._draw_start
                x2, y2 = int(round(scene_pt.x())), int(round(scene_pt.y()))
                # Normalise: x1 < x2, y1 < y2
                rx1, rx2 = min(x1, x2), max(x1, x2)
                ry1, ry2 = min(y1, y2), max(y1, y2)
                if abs(rx2 - rx1) > 2 and abs(ry2 - ry1) > 2:
                    self._draw_rect = (rx1, ry1, rx2, ry2)
                    self._mask_rect_item.hide()
                    self._mask_ellipse_item.hide()
                    
                    if self._mask_shape == "Ellipse":
                        self._mask_ellipse_item.setRect(rx1, ry1, rx2 - rx1, ry2 - ry1)
                        self._mask_ellipse_item.show()
                    else:
                        self._mask_rect_item.setRect(rx1, ry1, rx2 - rx1, ry2 - ry1)
                        self._mask_rect_item.show()
                    self._draw_label.setText(f"MASK: ({rx1},{ry1})→({rx2},{ry2})")
                    self.maskDrawn.emit()
                else:
                    # Too small — cancel
                    self._draw_label.setText("DRAW: mask too small, try again")
                self._rubber_band.hide()
                self._rubber_ellipse.hide()
                self._draw_start = None
            return

        if event.button() == QtCore.Qt.LeftButton and self._picker_mode and self.image_array is not None:
            pixel = self._get_pixel_at(event.x(), event.y())
            if pixel is not None:
                px, py, r, g, b, luma = pixel
                self.pixelPicked.emit(r, g, b)
            self.set_picker_mode(False) # Turn off after one pick
            return

        super(ViewerWidget, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._draw_mode and self._mask_shape == "Polygon" and self._drawing:
            self._finish_polygon()
            return
        super(ViewerWidget, self).mouseDoubleClickEvent(event)

    def _finish_polygon(self):
        if len(self._poly_drawn_points) > 1:
            self._poly_points = [(p.x(), p.y()) if p is not None else None for p in self._poly_drawn_points]
            
            self._mask_rect_item.hide()
            self._mask_ellipse_item.hide()
            self._mask_poly_item.hide()
            if hasattr(self, '_mask_path_item'):
                self._mask_path_item.hide()
                
            if self._mask_shape in ["Lasso", "Polygon"]:
                clean_points = [p for p in self._poly_drawn_points if p is not None]
                poly = QtGui.QPolygonF(clean_points)
                self._mask_poly_item.setPolygon(poly)
                self._mask_poly_item.show()
                br = poly.boundingRect()
                if self._mask_shape == "Polygon":
                    self._update_poly_handles()
            else: # Brush
                if self._poly_drawn_points[0] is not None:
                    path = QtGui.QPainterPath(self._poly_drawn_points[0])
                else:
                    path = QtGui.QPainterPath()
                for p in self._poly_drawn_points[1:]:
                    if p is None:
                        continue
                    if path.isEmpty():
                        path.moveTo(p)
                    # If previous was None, we need to moveTo instead of lineTo
                    # Wait, QPainterPath doesn't let us easily know if previous was None without tracking.
                
                # Rebuild path cleanly
                path = QtGui.QPainterPath()
                is_new_stroke = True
                for p in self._poly_drawn_points:
                    if p is None:
                        is_new_stroke = True
                        continue
                    if is_new_stroke:
                        path.moveTo(p)
                        is_new_stroke = False
                    else:
                        path.lineTo(p)
                        
                self._mask_path_item.setPath(path)
                
                if getattr(self, '_brush_size_norm', 0.0) > 0.0 and self.image_array is not None:
                    w = self.image_array.shape[1]
                    px_size = max(2.0, self._brush_size_norm * w)
                    pen = QtGui.QPen(QtGui.QColor(0, 220, 100, 220), px_size)
                    pen.setCapStyle(QtCore.Qt.RoundCap)
                    pen.setJoinStyle(QtCore.Qt.RoundJoin)
                    self._mask_path_item.setPen(pen)
                else:
                    self._mask_path_item.setPen(QtGui.QPen(QtGui.QColor(0, 220, 100, 220), 2))
                    
                self._mask_path_item.show()
                br = path.boundingRect()
            
            self._draw_rect = (br.left(), br.top(), br.right(), br.bottom())
            
            self._draw_label.setText(f"MASK: {self._mask_shape} ({len(self._poly_points)} pts)")
            self.maskDrawn.emit()
            
        self._drawing = False
        self._poly_drawn_points = []
        self._rubber_poly.hide()
        if hasattr(self, '_rubber_path'):
            self._rubber_path.hide()

    def resizeEvent(self, event):
        super(ViewerWidget, self).resizeEvent(event)
        self._overlay.resize(self.size())
        # Do NOT re-fit on resize — that would reset the user's zoom/pan
        # whenever dock/widget boundaries change (splitter drag, panel toggle,
        # window resize). The view is only fitted once when set_image() is
        # called with reset_view=True (i.e. when loading a brand new file).

    def eventFilter(self, obj, event):
        if obj is self._overlay and event.type() == QtCore.QEvent.Wheel:
            self.wheelEvent(event)
            return True
        return super().eventFilter(obj, event)
