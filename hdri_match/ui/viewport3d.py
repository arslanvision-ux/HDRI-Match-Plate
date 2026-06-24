import math
import numpy as np
from hdri_match.ui.qt_shim import QtWidgets, QtCore, QtGui
import OpenGL.GL as gl
import OpenGL.GLU as glu

try:
    # PySide6
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except ImportError:
    try:
        # PySide2
        from PySide2.QtWidgets import QOpenGLWidget
    except ImportError:
        raise ImportError("Could not find QOpenGLWidget in PySide6 or PySide2")

# QAction moved from QtWidgets (PySide2) to QtGui (PySide6)
if hasattr(QtGui, 'QAction'):
    QAction = QtGui.QAction
else:
    QAction = QtWidgets.QAction

class Camera3D:
    def __init__(self):
        self.distance = 10.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.pan_z = 0.0
        self.rotation_x = 30.0  # Elevation
        self.rotation_y = -45.0 # Azimuth
        self.focal_length = 50.0 # mm
        self.sensor_height = 24.0 # mm
        self.focus_distance = 100.0 # units (e.g. cm)
        
    def get_fov(self):
        # fov = 2 * arctan(sensor_height / (2 * focal_length))
        return math.degrees(2 * math.atan(self.sensor_height / (2.0 * max(0.1, self.focal_length))))
        
    def apply(self):
        gl.glLoadIdentity()
        
        # Apply translation (distance)
        gl.glTranslatef(0.0, 0.0, -self.distance)
        
        # Apply rotation
        gl.glRotatef(self.rotation_x, 1.0, 0.0, 0.0)
        gl.glRotatef(self.rotation_y, 0.0, 1.0, 0.0)
        
        # Apply pan
        gl.glTranslatef(-self.pan_x, -self.pan_y, -self.pan_z)
        
    def pan(self, dx, dy):
        # Calculate camera basis vectors to pan relative to view
        # This is simplified for a basic orbit camera
        rad_y = math.radians(self.rotation_y)
        rad_x = math.radians(self.rotation_x)
        
        right_x = math.cos(rad_y)
        right_z = math.sin(rad_y)
        
        up_x = -math.sin(rad_x) * math.sin(rad_y)
        up_y = math.cos(rad_x)
        up_z = math.sin(rad_x) * math.cos(rad_y)
        
        factor = self.distance * 0.002
        
        self.pan_x -= (right_x * dx - up_x * dy) * factor
        self.pan_y -= (up_y * dy) * factor
        self.pan_z -= (right_z * dx - up_z * dy) * factor

class Viewport3D(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        
        self.camera = Camera3D()
        self.last_pos = QtCore.QPoint()
        
        # Scene data
        self.meshes = [] # List of dicts: {'name': str, 'v': ..., 'n': ..., 'i': ..., 't': [0,0,0], 'r': [0,0,0], 's': [1,1,1]}
        self.hdri_texture_id = None
        self.hdri_shape = None
        
        # Transform data
        self.hdri_radius = 50.0
        self.hdri_translate = [0.0, 0.0, 0.0]
        self.hdri_rotate = [0.0, 0.0, 0.0]
        
        self.selected_object = None # 'HDRI' or mesh dict
        self.tool_mode = 'W' # Q=Select, W=Translate, E=Rotate, R=Scale
        self.active_gizmo_axis = 0 # 0=none, 1=X, 2=Y, 3=Z, 4=Center
        
        # New Display Features
        self.show_bg = False
        self.show_frustum = False
        self.show_ground_plane = True
        self.dome_ev = 0.0
        self.plate_texture_id = None
        self.plate_shape = None
        
        self.undo_stack = []
        self._drag_start_state = None
        
    def _get_scene_state(self):
        import copy
        state = {
            'hdri_radius': self.hdri_radius,
            'hdri_translate': list(self.hdri_translate),
            'hdri_rotate': list(self.hdri_rotate),
            'meshes': []
        }
        for m in self.meshes:
            state['meshes'].append({
                't': list(m['t']),
                'r': list(m['r']),
                's': list(m['s'])
            })
        return state
        
    def _apply_scene_state(self, state):
        self.hdri_radius = state['hdri_radius']
        self.hdri_translate = list(state['hdri_translate'])
        self.hdri_rotate = list(state['hdri_rotate'])
        for i, m_state in enumerate(state['meshes']):
            if i < len(self.meshes):
                self.meshes[i]['t'] = list(m_state['t'])
                self.meshes[i]['r'] = list(m_state['r'])
                self.meshes[i]['s'] = list(m_state['s'])
        
        self.update()
        if hasattr(self.window(), '_sync_obj_ui'):
            self.window()._sync_obj_ui()
            
    def initializeGL(self):
        gl.glClearColor(0.15, 0.15, 0.15, 1.0)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_LIGHTING)
        gl.glEnable(gl.GL_LIGHT0)
        
        # Enable textures
        gl.glEnable(gl.GL_TEXTURE_2D)
        
        # Nuke style default shading setup
        gl.glEnable(gl.GL_COLOR_MATERIAL)
        gl.glColorMaterial(gl.GL_FRONT_AND_BACK, gl.GL_AMBIENT_AND_DIFFUSE)
        
        # Soft directional light (Key)
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_POSITION, [1.0, 1.0, 1.0, 0.0])
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_DIFFUSE, [0.8, 0.8, 0.8, 1.0])
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_SPECULAR, [0.5, 0.5, 0.5, 1.0])
        
        # Fill light
        gl.glEnable(gl.GL_LIGHT1)
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_POSITION, [-1.0, -0.5, -1.0, 0.0])
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_DIFFUSE, [0.2, 0.2, 0.3, 1.0])
        
        # Global Ambient
        gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT, [0.1, 0.1, 0.1, 1.0])
        
        # Material setup
        gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_SPECULAR, [0.5, 0.5, 0.5, 1.0])
        gl.glMateriali(gl.GL_FRONT_AND_BACK, gl.GL_SHININESS, 32)
        
    def resizeGL(self, w, h):
        gl.glViewport(0, 0, w, h)
        self.update_projection()
        
    def update_projection(self):
        w = self.width()
        h = self.height()
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        
        aspect = float(w) / max(1.0, float(h))
        fov = self.camera.get_fov()
        glu.gluPerspective(fov, aspect, 0.1, 10000.0)
        
        gl.glMatrixMode(gl.GL_MODELVIEW)
        
    def paintGL(self):
        # Update lights with Dome EV multiplier
        ev_mult = 2.0 ** getattr(self, 'dome_ev', 0.0)
        
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_DIFFUSE, [0.8 * ev_mult, 0.8 * ev_mult, 0.8 * ev_mult, 1.0])
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_SPECULAR, [0.5 * ev_mult, 0.5 * ev_mult, 0.5 * ev_mult, 1.0])
        
        gl.glLightfv(gl.GL_LIGHT1, gl.GL_DIFFUSE, [0.2 * ev_mult, 0.2 * ev_mult, 0.3 * ev_mult, 1.0])
        
        # Image-Based Ambient Lighting
        if hasattr(self, 'hdri_ambient_color'):
            gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT, self.hdri_ambient_color)
        else:
            gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT, [0.1 * ev_mult, 0.1 * ev_mult, 0.1 * ev_mult, 1.0])
        
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        
        is_locked_to_cam = (
            abs(self.camera.distance) < 0.001 and
            abs(self.camera.pan_x) < 0.001 and
            abs(self.camera.pan_y) < 0.001 and
            abs(self.camera.pan_z) < 0.001 and
            abs(self.camera.rotation_x) < 0.001 and
            abs(self.camera.rotation_y) < 0.001
        )
        self.is_locked_to_cam = is_locked_to_cam
        
        if self.show_bg and self.is_locked_to_cam:
            self.draw_background_plate()
            
        self.camera.apply()
        
        if self.show_frustum:
            self.draw_frustum()
            
        if getattr(self, 'show_ground_plane', False):
            self.draw_ground_plane()
        else:
            self.draw_grid()
            
        self.draw_axes()
        
        self.draw_meshes()
        self.draw_pipeline_data()
        self.draw_gizmo()
        
    def draw_gizmo(self, picking=False):
        if not self.selected_object or self.tool_mode == 'Q': return
        
        is_mask = False
        theta = phi = 0.0
        x = y = z = 0.0
        mask_t = mask_r = [0,0,0]
        
        pos = [0,0,0]
        if self.selected_object == 'HDRI':
            pos = self.hdri_translate
        elif isinstance(self.selected_object, dict):
            pos = self.selected_object['t']
        elif isinstance(self.selected_object, str) and self.selected_object.startswith("Mask_"):
            is_mask = True
            mask_id = self.selected_object.split("_")[1]
            main_window = self.window().parent()
            if hasattr(main_window, 'pipeline'):
                for mask in main_window.pipeline.state.masks:
                    if mask.id == mask_id and hasattr(mask, 'transform_3d'):
                        if mask.rect:
                            rx, ry, rx2, ry2 = mask.rect
                            u = (rx + rx2) / 2.0
                            v = (ry + ry2) / 2.0
                            yaw_norm = getattr(main_window, '_mask_yaw', 0.0) / 360.0
                            vis_u = (u + yaw_norm) % 1.0
                            theta = vis_u * 2 * math.pi
                            phi = (1.0 - v) * math.pi
                            x = math.sin(phi) * math.cos(theta)
                            y = math.cos(phi)
                            z = -math.sin(phi) * math.sin(theta)
                            mask_t = mask.transform_3d['t']
                            mask_r = mask.transform_3d['r']
                        break
            
        if not picking:
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_LIGHTING)
            gl.glDisable(gl.GL_TEXTURE_2D)
        
        gl.glPushMatrix()
        
        if is_mask:
            R = self.hdri_radius - 1.0
            gl.glTranslatef(x * R, y * R, z * R)
            gl.glRotatef(math.degrees(theta) - 90, 0, 1, 0)
            gl.glRotatef(90 - math.degrees(phi), 1, 0, 0)
            
            gl.glRotatef(mask_r[0], 1, 0, 0)
            gl.glRotatef(mask_r[1], 0, 1, 0)
            gl.glRotatef(mask_r[2], 0, 0, 1)
            gl.glTranslatef(*mask_t)
        else:
            gl.glTranslatef(*pos)
            
        if not picking:
            try:
                modelview = gl.glGetDoublev(gl.GL_MODELVIEW_MATRIX)
                projection = gl.glGetDoublev(gl.GL_PROJECTION_MATRIX)
                viewport = gl.glGetIntegerv(gl.GL_VIEWPORT)
                
                p0 = glu.gluProject(0.0, 0.0, 0.0, modelview, projection, viewport)
                p1 = glu.gluProject(1.0, 0.0, 0.0, modelview, projection, viewport)
                p2 = glu.gluProject(0.0, 1.0, 0.0, modelview, projection, viewport)
                p3 = glu.gluProject(0.0, 0.0, 1.0, modelview, projection, viewport)
                
                if p0 and p1 and p2 and p3:
                    self._screen_axes = {
                        1: (p1[0]-p0[0], p1[1]-p0[1]),
                        2: (p2[0]-p0[0], p2[1]-p0[1]),
                        3: (p3[0]-p0[0], p3[1]-p0[1])
                    }
            except Exception:
                pass
        
        scale = self.camera.distance * 0.1
        gl.glScalef(scale, scale, scale)
        
        def set_color(r, g, b, pick_id):
            if picking:
                gl.glColor3ub(pick_id, 0, 0)
            else:
                gl.glColor3f(r, g, b)
                
        def draw_ring(axis):
            gl.glBegin(gl.GL_LINE_LOOP)
            for i in range(36):
                ang = i * 10.0 * math.pi / 180.0
                if axis == 1: gl.glVertex3f(0, math.cos(ang), math.sin(ang))
                elif axis == 2: gl.glVertex3f(math.cos(ang), 0, math.sin(ang))
                elif axis == 3: gl.glVertex3f(math.cos(ang), math.sin(ang), 0)
            gl.glEnd()
            
        def draw_box():
            s = 0.15 if picking else 0.05
            gl.glBegin(gl.GL_QUADS)
            gl.glVertex3f(-s,-s,-s); gl.glVertex3f(s,-s,-s); gl.glVertex3f(s,s,-s); gl.glVertex3f(-s,s,-s)
            gl.glVertex3f(-s,-s,s); gl.glVertex3f(s,-s,s); gl.glVertex3f(s,s,s); gl.glVertex3f(-s,s,s)
            gl.glVertex3f(-s,-s,-s); gl.glVertex3f(-s,s,-s); gl.glVertex3f(-s,s,s); gl.glVertex3f(-s,-s,s)
            gl.glVertex3f(s,-s,-s); gl.glVertex3f(s,s,-s); gl.glVertex3f(s,s,s); gl.glVertex3f(s,-s,s)
            gl.glVertex3f(-s,-s,-s); gl.glVertex3f(s,-s,-s); gl.glVertex3f(s,-s,s); gl.glVertex3f(-s,-s,s)
            gl.glVertex3f(-s,s,-s); gl.glVertex3f(s,s,-s); gl.glVertex3f(s,s,s); gl.glVertex3f(-s,s,s)
            gl.glEnd()
            
        # Draw axes
        for axis, (r, g, b, rot_args, trans_args) in enumerate([
            (1.0, 0.0, 0.0, (90, 0, 1, 0), (1, 0, 0)), # X
            (0.0, 1.0, 0.0, (-90, 1, 0, 0), (0, 1, 0)), # Y
            (0.0, 0.0, 1.0, (0, 0, 1, 0), (0, 0, 1))   # Z
        ]):
            set_color(r, g, b, 201 + axis)
            
            if self.tool_mode == 'W':
                if picking:
                    gl.glPushMatrix(); gl.glTranslatef(*trans_args); gl.glRotatef(*rot_args); glu.gluCylinder(glu.gluNewQuadric(), 0.05, 0.05, 0.5, 10, 1); gl.glPopMatrix()
                else:
                    gl.glBegin(gl.GL_LINES)
                    gl.glVertex3f(0, 0, 0); gl.glVertex3f(*trans_args)
                    gl.glEnd()
                    gl.glPushMatrix(); gl.glTranslatef(*trans_args); gl.glRotatef(*rot_args); glu.gluCylinder(glu.gluNewQuadric(), 0.05, 0.0, 0.2, 10, 1); gl.glPopMatrix()
            elif self.tool_mode == 'E':
                gl.glLineWidth(3.0 if not picking else 10.0) # Fatter for picking
                draw_ring(axis + 1)
                gl.glLineWidth(1.0)
            elif self.tool_mode == 'R':
                gl.glBegin(gl.GL_LINES)
                gl.glVertex3f(0, 0, 0); gl.glVertex3f(*trans_args)
                gl.glEnd()
                gl.glPushMatrix(); gl.glTranslatef(*trans_args); draw_box(); gl.glPopMatrix()
                
        # Draw center box
        set_color(1.0, 1.0, 0.0, 204)
        s = 0.2 if picking else 0.1
        gl.glBegin(gl.GL_QUADS)
        gl.glVertex3f(-s,-s,0); gl.glVertex3f(s,-s,0); gl.glVertex3f(s,s,0); gl.glVertex3f(-s,s,0)
        gl.glEnd()
        
        gl.glPopMatrix()
        
        if not picking:
            gl.glEnable(gl.GL_LIGHTING)
            gl.glEnable(gl.GL_DEPTH_TEST)
        
    def update_hdri_texture(self):
        main_window = self.window().parent()
        if not hasattr(main_window, 'pipeline'): return
        
        # Use proxy instead of full array for speed
        hdri_array = main_window.pipeline.state.hdri_proxy
        if hdri_array is None: 
            hdri_array = main_window.pipeline.state.hdri_array
        if hdri_array is None: return
        
        current_ev = getattr(self, 'dome_ev', 0.0)
        last_ev = getattr(self, '_last_texture_ev', None)
        
        # Only update if the shape/array changed, or if EV changed
        if self.hdri_shape == hdri_array.shape and self.hdri_texture_id is not None and current_ev == last_ev:
            return
            
        self.hdri_shape = hdri_array.shape
        self._last_texture_ev = current_ev
        h, w, c = hdri_array.shape
        
        # Basic downsample if still too huge for viewer
        step = max(1, w // 2048)
        preview_arr = hdri_array[::step, ::step, :3].astype(np.float32)
        ph, pw, _ = preview_arr.shape
        
        # Apply EV
        if current_ev != 0.0:
            preview_arr = preview_arr * (2.0 ** current_ev)
            
        # Calculate true linear average color for ambient image-based lighting
        mean_color = np.mean(preview_arr, axis=(0, 1))
        # Ensure it doesn't blow out the ambient term completely, keep it subtle
        self.hdri_ambient_color = [min(mean_color[0]*0.5, 0.8), min(mean_color[1]*0.5, 0.8), min(mean_color[2]*0.5, 0.8), 1.0]
            
        # Tonemap slightly for UI (simple gamma)
        preview_arr = np.clip(preview_arr, 0.0, 10.0)
        preview_arr = np.power(preview_arr, 1.0/2.2)
        
        if self.hdri_texture_id is None:
            self.hdri_texture_id = gl.glGenTextures(1)
            
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.hdri_texture_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        
        # Upload
        # Flip vertically for OpenGL
        preview_arr = np.flipud(preview_arr)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB32F, pw, ph, 0, gl.GL_RGB, gl.GL_FLOAT, preview_arr)
        
    def draw_pipeline_data(self):
        main_window = self.window().parent()
        if not hasattr(main_window, 'pipeline'): return
        state = main_window.pipeline.state
        
        # Ensure texture is loaded
        self.update_hdri_texture()
        
        # Draw HDRI Dome
        if self.hdri_texture_id is not None:
            gl.glDisable(gl.GL_LIGHTING)
            gl.glEnable(gl.GL_TEXTURE_2D)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.hdri_texture_id)
            
            gl.glPushMatrix()
            
            # Apply user transforms
            gl.glTranslatef(*self.hdri_translate)
            gl.glRotatef(self.hdri_rotate[0], 1, 0, 0)
            gl.glRotatef(self.hdri_rotate[1], 0, 1, 0)
            gl.glRotatef(self.hdri_rotate[2], 0, 0, 1)
            
            # Apply global yaw rotation to dome
            yaw = getattr(main_window, '_mask_yaw', 0.0)
            gl.glRotatef(-yaw, 0, 1, 0)
            
            # Transparency if showing backplate
            gl.glColor4f(1.0, 1.0, 1.0, 1.0)
            
            # Draw sphere
            qobj = glu.gluNewQuadric()
            glu.gluQuadricTexture(qobj, gl.GL_TRUE)
            glu.gluQuadricNormals(qobj, glu.GLU_NONE)
            glu.gluQuadricOrientation(qobj, glu.GLU_INSIDE) # Render inside
            
            # We must rotate the sphere so poles are Y axis. gluSphere poles are Z axis.
            gl.glRotatef(-90.0, 1.0, 0.0, 0.0)
            # Offset rotation so center matches Nuke (U=0.5 is front)
            gl.glRotatef(-90.0, 0.0, 0.0, 1.0)
            
            # Draw dome only if we aren't looking perfectly through the backplate camera
            # or if the user disabled the background
            if not (self.show_bg and getattr(self, 'is_locked_to_cam', False)):
                # Enable culling to look through the outside of the sphere
                gl.glEnable(gl.GL_CULL_FACE)
                gl.glCullFace(gl.GL_BACK)
                
                glu.gluSphere(qobj, self.hdri_radius, 64, 32)
                
                gl.glDisable(gl.GL_CULL_FACE)
                
            glu.gluDeleteQuadric(qobj)
            
            gl.glPopMatrix()
            
            gl.glDisable(gl.GL_TEXTURE_2D)
            gl.glEnable(gl.GL_LIGHTING)
        
        # Draw Sun
        if state.sun_auto_detected or getattr(state, 'sun_relight_enabled', False):
            # Calculate sun vector from u,v (simplified)
            u, v = state.sun_target_u, state.sun_target_v
            
            # Apply yaw to visually match what is shown in UI
            yaw_norm = getattr(main_window, '_mask_yaw', 0.0) / 360.0
            vis_u = (u + yaw_norm) % 1.0
            
            theta = vis_u * 2 * math.pi
            phi = (1.0 - v) * math.pi # 0 is top, 1 is bottom
            
            x = math.sin(phi) * math.cos(theta)
            y = math.cos(phi)
            z = -math.sin(phi) * math.sin(theta)
            
            gl.glDisable(gl.GL_LIGHTING)
            gl.glLineWidth(3.0)
            gl.glBegin(gl.GL_LINES)
            gl.glColor3f(1.0, 1.0, 0.8) # Sun color
            gl.glVertex3f(0.0, 0.0, 0.0)
            gl.glVertex3f(x * 15, y * 15, z * 15)
            gl.glEnd()
            gl.glLineWidth(1.0)
            
            # Draw a marker at the end of the line
            gl.glPushMatrix()
            gl.glTranslatef(x * 15, y * 15, z * 15)
            # A little star/diamond
            s = 0.5
            gl.glBegin(gl.GL_LINES)
            gl.glVertex3f(-s, 0, 0); gl.glVertex3f(s, 0, 0)
            gl.glVertex3f(0, -s, 0); gl.glVertex3f(0, s, 0)
            gl.glVertex3f(0, 0, -s); gl.glVertex3f(0, 0, s)
            gl.glEnd()
            
            # Also a tiny sphere
            qobj = glu.gluNewQuadric()
            glu.gluQuadricNormals(qobj, glu.GLU_NONE)
            glu.gluSphere(qobj, 0.2, 8, 8)
            glu.gluDeleteQuadric(qobj)
            
            gl.glPopMatrix()
            gl.glEnable(gl.GL_LIGHTING)
            
        # Draw Masks
        if getattr(state, 'masks_enabled', False):
            gl.glDisable(gl.GL_LIGHTING)
            for mask in getattr(state, 'masks', []):
                if not getattr(mask, 'enabled', True) or not mask.rect: continue
                # Basic center point of rect
                rx, ry, rx2, ry2 = mask.rect
                u = (rx + rx2) / 2.0
                v = (ry + ry2) / 2.0
                
                yaw_norm = getattr(main_window, '_mask_yaw', 0.0) / 360.0
                vis_u = (u + yaw_norm) % 1.0
                
                theta = vis_u * 2 * math.pi
                phi = (1.0 - v) * math.pi
                
                x = math.sin(phi) * math.cos(theta)
                y = math.cos(phi)
                z = -math.sin(phi) * math.sin(theta)
                
                # Initialize 3D transform if it doesn't exist
                if not hasattr(mask, 'transform_3d'):
                    mask.transform_3d = {'t': [0.0, 0.0, 0.0], 'r': [0.0, 0.0, 0.0], 's': [1.0, 1.0, 1.0]}
                
                R = self.hdri_radius - 1.0
                gl.glPushMatrix()
                
                # 1. Base Spherical Translation
                gl.glTranslatef(x * R, y * R, z * R)
                
                # 2. Base Spherical Orientation (Face the origin)
                gl.glRotatef(math.degrees(theta) - 90, 0, 1, 0)
                gl.glRotatef(90 - math.degrees(phi), 1, 0, 0)
                
                # 3. Local User Rotation
                gl.glRotatef(mask.transform_3d['r'][0], 1, 0, 0)
                gl.glRotatef(mask.transform_3d['r'][1], 0, 1, 0)
                gl.glRotatef(mask.transform_3d['r'][2], 0, 0, 1)
                
                # 4. Local User Translation
                gl.glTranslatef(*mask.transform_3d['t'])
                
                # 5. Local User Scale
                gl.glScalef(*mask.transform_3d['s'])
                
                # Active mask is green, others are cyan
                if mask.id == getattr(state, 'active_mask_id', None):
                    gl.glColor4f(0.0, 1.0, 0.0, 0.5) # semi-transparent
                else:
                    gl.glColor4f(0.0, 0.5, 1.0, 0.5)
                    
                # Calculate actual physical dimensions of the card based on UV size
                w_uv = rx2 - rx
                h_uv = ry2 - ry
                
                # Arc length: s = r * theta. 
                # Multiply by sin(phi) to account for pole pinching
                card_width = (w_uv * 2.0 * math.pi * R) * math.sin(phi)
                card_height = (h_uv * math.pi * R)
                
                hw = card_width / 2.0
                hh = card_height / 2.0
                
                gl.glEnable(gl.GL_BLEND)
                gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
                
                gl.glBegin(gl.GL_QUADS)
                gl.glVertex3f(-hw, -hh, 0)
                gl.glVertex3f(hw, -hh, 0)
                gl.glVertex3f(hw, hh, 0)
                gl.glVertex3f(-hw, hh, 0)
                gl.glEnd()
                
                # Draw border
                if mask.id == getattr(state, 'active_mask_id', None):
                    gl.glColor3f(0.0, 1.0, 0.0)
                else:
                    gl.glColor3f(0.0, 0.8, 1.0)
                gl.glLineWidth(2.0)
                gl.glBegin(gl.GL_LINE_LOOP)
                gl.glVertex3f(-hw, -hh, 0)
                gl.glVertex3f(hw, -hh, 0)
                gl.glVertex3f(hw, hh, 0)
                gl.glVertex3f(-hw, hh, 0)
                gl.glEnd()
                gl.glLineWidth(1.0)
                
                gl.glDisable(gl.GL_BLEND)
                gl.glPopMatrix()
            gl.glEnable(gl.GL_LIGHTING)
            
    def draw_background_plate(self):
        main_window = self.window().parent()
        if not hasattr(main_window, 'pipeline'): return
        
        plate_array = main_window.pipeline.state.plate_proxy
        if plate_array is None:
            plate_array = main_window.pipeline.state.plate_array
        if plate_array is None: return
        
        h, w, c = plate_array.shape
        
        # Load texture if needed
        if self.plate_shape != plate_array.shape or self.plate_texture_id is None:
            self.plate_shape = plate_array.shape
            step = max(1, w // 2048)
            preview_arr = plate_array[::step, ::step, :3].astype(np.float32)
            ph, pw, _ = preview_arr.shape
            
            # Simple sRGB-ish gamma for preview
            preview_arr = np.clip(preview_arr, 0.0, 10.0)
            preview_arr = np.power(preview_arr, 1.0/2.2)
            preview_arr = np.flipud(preview_arr)
            
            if self.plate_texture_id is None:
                self.plate_texture_id = gl.glGenTextures(1)
                
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.plate_texture_id)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB32F, pw, ph, 0, gl.GL_RGB, gl.GL_FLOAT, preview_arr)
            
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        
        # Draw full screen quad (orthographic)
        aspect_screen = self.width() / max(1, self.height())
        aspect_image = w / h
        
        # Fit image into screen
        if aspect_screen > aspect_image:
            # Screen is wider, image fits vertically, pad horizontally
            scale_x = aspect_image / aspect_screen
            scale_y = 1.0
        else:
            scale_x = 1.0
            scale_y = aspect_screen / aspect_image
            
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_LIGHTING)
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.plate_texture_id)
        
        gl.glColor3f(1.0, 1.0, 1.0)
        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0, 0); gl.glVertex3f(-scale_x, -scale_y, -1)
        gl.glTexCoord2f(1, 0); gl.glVertex3f( scale_x, -scale_y, -1)
        gl.glTexCoord2f(1, 1); gl.glVertex3f( scale_x,  scale_y, -1)
        gl.glTexCoord2f(0, 1); gl.glVertex3f(-scale_x,  scale_y, -1)
        gl.glEnd()
        
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)
        
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_MODELVIEW)

    def draw_frustum(self):
        # Draw the camera frustum at the origin
        gl.glDisable(gl.GL_LIGHTING)
        gl.glColor3f(1.0, 0.5, 0.0)
        
        f = self.camera.focal_length
        s = self.camera.sensor_height
        
        # Assume 16:9 aspect for the sensor width if not specified
        aspect = 16.0 / 9.0 
        w = (s * aspect) / 2.0
        h = s / 2.0
        d = -f # Look down -Z
        
        # Scale down for visualization
        scale = 0.1
        w *= scale
        h *= scale
        d *= scale
        
        gl.glBegin(gl.GL_LINES)
        # Pyramid lines
        gl.glVertex3f(0, 0, 0); gl.glVertex3f(-w, -h, d)
        gl.glVertex3f(0, 0, 0); gl.glVertex3f( w, -h, d)
        gl.glVertex3f(0, 0, 0); gl.glVertex3f( w,  h, d)
        gl.glVertex3f(0, 0, 0); gl.glVertex3f(-w,  h, d)
        
        # Front plane
        gl.glVertex3f(-w, -h, d); gl.glVertex3f( w, -h, d)
        gl.glVertex3f( w, -h, d); gl.glVertex3f( w,  h, d)
        gl.glVertex3f( w,  h, d); gl.glVertex3f(-w,  h, d)
        gl.glVertex3f(-w,  h, d); gl.glVertex3f(-w, -h, d)
        gl.glEnd()
        
        # Draw camera body box
        gl.glColor3f(0.5, 0.5, 0.5)
        gl.glPushMatrix()
        gl.glTranslatef(0, 0, 1.0)
        s = 0.5
        gl.glBegin(gl.GL_LINE_LOOP)
        gl.glVertex3f(-s,-s,-s); gl.glVertex3f(s,-s,-s); gl.glVertex3f(s,s,-s); gl.glVertex3f(-s,s,-s)
        gl.glEnd()
        gl.glPopMatrix()
        
        # Draw Focus Plane
        if getattr(self, 'show_focus_plane', False):
            fd = -self.camera.focus_distance
            # Scale the plane relative to focus distance
            fw = (w / scale) * (abs(fd) / f)
            fh = (h / scale) * (abs(fd) / f)
            
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            
            # Draw semi-transparent fill
            gl.glColor4f(0.2, 0.8, 0.2, 0.15)
            gl.glBegin(gl.GL_QUADS)
            gl.glVertex3f(-fw, -fh, fd)
            gl.glVertex3f( fw, -fh, fd)
            gl.glVertex3f( fw,  fh, fd)
            gl.glVertex3f(-fw,  fh, fd)
            gl.glEnd()
            
            # Draw outline
            gl.glColor4f(0.2, 0.8, 0.2, 0.8)
            gl.glBegin(gl.GL_LINE_LOOP)
            gl.glVertex3f(-fw, -fh, fd)
            gl.glVertex3f( fw, -fh, fd)
            gl.glVertex3f( fw,  fh, fd)
            gl.glVertex3f(-fw,  fh, fd)
            gl.glEnd()
            
            # Crosshair
            gl.glBegin(gl.GL_LINES)
            gl.glVertex3f(-fw*0.1, 0, fd); gl.glVertex3f(fw*0.1, 0, fd)
            gl.glVertex3f(0, -fh*0.1, fd); gl.glVertex3f(0, fh*0.1, fd)
            gl.glEnd()
            
            gl.glDisable(gl.GL_BLEND)
        
        gl.glEnable(gl.GL_LIGHTING)

    def draw_ground_plane(self, size=20):
        # Draw a large checkerboard that receives scene lighting
        gl.glEnable(gl.GL_LIGHTING)
        gl.glEnable(gl.GL_COLOR_MATERIAL)
        gl.glColorMaterial(gl.GL_FRONT_AND_BACK, gl.GL_AMBIENT_AND_DIFFUSE)
        
        # Specular off for ground
        gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_SPECULAR, [0.0, 0.0, 0.0, 1.0])
        gl.glNormal3f(0.0, 1.0, 0.0)
        
        gl.glBegin(gl.GL_QUADS)
        for x in range(-size, size):
            for z in range(-size, size):
                if (x + z) % 2 == 0:
                    gl.glColor3f(0.12, 0.12, 0.12)
                else:
                    gl.glColor3f(0.08, 0.08, 0.08)
                
                gl.glVertex3f(x, 0, z)
                gl.glVertex3f(x + 1, 0, z)
                gl.glVertex3f(x + 1, 0, z + 1)
                gl.glVertex3f(x, 0, z + 1)
        gl.glEnd()
        
        gl.glDisable(gl.GL_COLOR_MATERIAL)

    def draw_grid(self, size=10, step=1):
        gl.glDisable(gl.GL_LIGHTING)
        gl.glBegin(gl.GL_LINES)
        gl.glColor3f(0.3, 0.3, 0.3)
        for i in range(-size, size + 1, step):
            gl.glVertex3f(i, 0, -size)
            gl.glVertex3f(i, 0, size)
            gl.glVertex3f(-size, 0, i)
            gl.glVertex3f(size, 0, i)
        gl.glEnd()
        gl.glEnable(gl.GL_LIGHTING)
        
    def draw_axes(self):
        gl.glDisable(gl.GL_LIGHTING)
        gl.glLineWidth(2.0)
        gl.glBegin(gl.GL_LINES)
        # X axis (Red)
        gl.glColor3f(1.0, 0.0, 0.0)
        gl.glVertex3f(0.0, 0.0, 0.0)
        gl.glVertex3f(1.0, 0.0, 0.0)
        # Y axis (Green)
        gl.glColor3f(0.0, 1.0, 0.0)
        gl.glVertex3f(0.0, 0.0, 0.0)
        gl.glVertex3f(0.0, 1.0, 0.0)
        # Z axis (Blue)
        gl.glColor3f(0.0, 0.5, 1.0)
        gl.glVertex3f(0.0, 0.0, 0.0)
        gl.glVertex3f(0.0, 0.0, 1.0)
        gl.glEnd()
        gl.glLineWidth(1.0)
        gl.glEnable(gl.GL_LIGHTING)
        
    def draw_meshes(self):
        for item in self.meshes:
            mesh = item['mesh']
            mat_type = item.get('material')
            
            gl.glPushMatrix()
            
            # Apply individual transform
            gl.glTranslatef(*item['t'])
            gl.glRotatef(item['r'][0], 1, 0, 0)
            gl.glRotatef(item['r'][1], 0, 1, 0)
            gl.glRotatef(item['r'][2], 0, 0, 1)
            gl.glScalef(*item['s'])
            
            # Material setup
            # Material setup
            is_ibl = False
            if mat_type == 'Chrome' and self.hdri_texture_id is not None:
                is_ibl = True
                gl.glEnable(gl.GL_TEXTURE_2D)
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.hdri_texture_id)
                gl.glEnable(gl.GL_TEXTURE_GEN_S)
                gl.glEnable(gl.GL_TEXTURE_GEN_T)
                gl.glTexGeni(gl.GL_S, gl.GL_TEXTURE_GEN_MODE, gl.GL_SPHERE_MAP)
                gl.glTexGeni(gl.GL_T, gl.GL_TEXTURE_GEN_MODE, gl.GL_SPHERE_MAP)
                
                # Rotate the texture matrix to match the HDRI dome
                gl.glMatrixMode(gl.GL_TEXTURE)
                gl.glPushMatrix()
                gl.glLoadIdentity()
                
                main_window = getattr(self, 'main_window', None)
                if not main_window: main_window = self.window().parent()
                yaw = getattr(main_window, '_mask_yaw', 0.0) if main_window else 0.0
                
                gl.glRotatef(self.hdri_rotate[0], 1, 0, 0)
                gl.glRotatef(self.hdri_rotate[1], 0, 1, 0)
                gl.glRotatef(self.hdri_rotate[2], 0, 0, 1)
                gl.glRotatef(-yaw, 0, 1, 0)
                
                gl.glMatrixMode(gl.GL_MODELVIEW)
                
                gl.glColor3f(1.0, 1.0, 1.0)
                gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_SPECULAR, [1.0, 1.0, 1.0, 1.0])
                gl.glMateriali(gl.GL_FRONT_AND_BACK, gl.GL_SHININESS, 128)
            elif mat_type == 'Grey':
                # True 18% Grey Diffuse material
                gl.glColor3f(0.18, 0.18, 0.18)
                gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_SPECULAR, [0.0, 0.0, 0.0, 1.0])
                gl.glMateriali(gl.GL_FRONT_AND_BACK, gl.GL_SHININESS, 0)
            else:
                if self.selected_object is item:
                    gl.glColor3f(1.0, 0.5, 0.0) # Highlight selected
                else:
                    gl.glColor3f(0.6, 0.6, 0.6)
            
            # Override color if selected (even for IBL, add a tint)
            if self.selected_object is item and is_ibl:
                gl.glColor3f(1.0, 0.7, 0.3)
            
            if 'dl' in item and item['dl'] is not None:
                gl.glCallList(item['dl'])
            else:
                # Fallback if display list failed
                if hasattr(mesh, 'faces'):
                    gl.glBegin(gl.GL_TRIANGLES)
                    for face in mesh.faces:
                        for v_idx in face:
                            v = mesh.vertices[v_idx]
                            if hasattr(mesh, 'vertex_normals') and len(mesh.vertex_normals) > v_idx:
                                n = mesh.vertex_normals[v_idx]
                                gl.glNormal3f(n[0], n[1], n[2])
                            gl.glVertex3f(v[0], v[1], v[2])
                    gl.glEnd()
                
            if is_ibl:
                gl.glMatrixMode(gl.GL_TEXTURE)
                gl.glPopMatrix()
                gl.glMatrixMode(gl.GL_MODELVIEW)
                
                gl.glDisable(gl.GL_TEXTURE_GEN_S)
                gl.glDisable(gl.GL_TEXTURE_GEN_T)
                gl.glDisable(gl.GL_TEXTURE_2D)
                # Reset default material
                gl.glMaterialfv(gl.GL_FRONT_AND_BACK, gl.GL_SPECULAR, [0.5, 0.5, 0.5, 1.0])
                gl.glMateriali(gl.GL_FRONT_AND_BACK, gl.GL_SHININESS, 32)
                
            gl.glPopMatrix()
            
    def load_mesh(self, file_path):
        import os
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext in ['.usd', '.usda', '.usdc', '.abc']:
                # Attempt to load USD/Alembic using pxr
                try:
                    from pxr import Usd, UsdGeom
                    stage = Usd.Stage.Open(file_path)
                    if not stage:
                        print("Failed to open USD stage.")
                        return False
                        
                    # Extract meshes (very basic USD mesh extraction)
                    import trimesh
                    for prim in stage.Traverse():
                        if prim.IsA(UsdGeom.Mesh):
                            mesh_geom = UsdGeom.Mesh(prim)
                            points = mesh_geom.GetPointsAttr().Get()
                            face_vertex_counts = mesh_geom.GetFaceVertexCountsAttr().Get()
                            face_vertex_indices = mesh_geom.GetFaceVertexIndicesAttr().Get()
                            
                            if points and face_vertex_counts and face_vertex_indices:
                                # Convert to trimesh format (assuming triangle or quad meshes)
                                # This is a simplified extraction
                                vertices = np.array(points)
                                
                                # Triangulate faces
                                faces = []
                                idx = 0
                                for count in face_vertex_counts:
                                    face_indices = face_vertex_indices[idx:idx+count]
                                    if count == 3:
                                        faces.append(face_indices)
                                    elif count == 4:
                                        faces.append([face_indices[0], face_indices[1], face_indices[2]])
                                        faces.append([face_indices[0], face_indices[2], face_indices[3]])
                                    # Ignore >4 gons for now in this simple preview
                                    idx += count
                                    
                                if faces:
                                    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
                                    self.meshes.append({
                                        'name': prim.GetName() or "USD Mesh",
                                        'mesh': mesh,
                                        't': [0.0, 0.0, 0.0],
                                        'r': [0.0, 0.0, 0.0],
                                        's': [1.0, 1.0, 1.0]
                                    })
                    self.update()
                    return True
                except ImportError:
                    print("USD Python API (pxr) not found. Cannot load USD.")
                    from hdri_match.ui.qt_shim import QtWidgets
                    QtWidgets.QMessageBox.warning(self, "Missing Dependency", "The 'pxr' module (OpenUSD) is required to load USD files.")
                    return False
            else:
                import trimesh
                mesh = trimesh.load(file_path, force='mesh')
                
                # Handle scenes with multiple meshes
                if isinstance(mesh, trimesh.Scene):
                    for name, geom in mesh.geometry.items():
                        self.meshes.append({
                            'name': str(name),
                            'mesh': geom,
                            't': [0.0, 0.0, 0.0],
                            'r': [0.0, 0.0, 0.0],
                            's': [1.0, 1.0, 1.0]
                        })
                else:
                    import os
                    self.meshes.append({
                        'name': os.path.basename(file_path),
                        'mesh': mesh,
                        't': [0.0, 0.0, 0.0],
                        'r': [0.0, 0.0, 0.0],
                        's': [1.0, 1.0, 1.0]
                    })
                self.update()
                
            # Compile display lists for any new meshes
            for item in self.meshes:
                if 'dl' not in item:
                    mesh = item['mesh']
                    dl_id = gl.glGenLists(1)
                    gl.glNewList(dl_id, gl.GL_COMPILE)
                    gl.glBegin(gl.GL_TRIANGLES)
                    for face in mesh.faces:
                        for v_idx in face:
                            v = mesh.vertices[v_idx]
                            if hasattr(mesh, 'vertex_normals') and len(mesh.vertex_normals) > v_idx:
                                n = mesh.vertex_normals[v_idx]
                                gl.glNormal3f(n[0], n[1], n[2])
                            gl.glVertex3f(v[0], v[1], v[2])
                    gl.glEnd()
                    gl.glEndList()
                    item['dl'] = dl_id
                    
            return True
        except Exception as e:
            print(f"Failed to load mesh: {e}")
            from hdri_match.ui.qt_shim import QtWidgets
            QtWidgets.QMessageBox.critical(self, "Load Error", f"Failed to load mesh:\n{e}")
            return False
            
    def perform_picking(self, pos):
        if not hasattr(self, 'context') or not self.context(): return
        self.makeCurrent()
        
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        
        gl.glDisable(gl.GL_LIGHTING)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glDisable(gl.GL_BLEND)
        
        self.camera.apply()
        
        # Draw HDRI as ID 1
        gl.glPushMatrix()
        gl.glTranslatef(*self.hdri_translate)
        gl.glRotatef(self.hdri_rotate[0], 1, 0, 0)
        gl.glRotatef(self.hdri_rotate[1], 0, 1, 0)
        gl.glRotatef(self.hdri_rotate[2], 0, 0, 1)
        yaw = getattr(self.window().parent(), '_mask_yaw', 0.0) if hasattr(self.window(), 'parent') else 0.0
        gl.glRotatef(-yaw, 0, 1, 0)
        
        qobj = glu.gluNewQuadric()
        glu.gluQuadricNormals(qobj, glu.GLU_NONE)
        gl.glColor3ub(1, 0, 0)
        gl.glRotatef(-90.0, 1.0, 0.0, 0.0)
        gl.glRotatef(-90.0, 0.0, 0.0, 1.0)
        glu.gluSphere(qobj, self.hdri_radius, 32, 16)
        glu.gluDeleteQuadric(qobj)
        gl.glPopMatrix()
        
        # Draw meshes as ID 2+i
        for i, item in enumerate(self.meshes):
            gl.glPushMatrix()
            gl.glTranslatef(*item['t'])
            gl.glRotatef(item['r'][0], 1, 0, 0)
            gl.glRotatef(item['r'][1], 0, 1, 0)
            gl.glRotatef(item['r'][2], 0, 0, 1)
            gl.glScalef(*item['s'])
            
            gl.glColor3ub(i + 2, 0, 0)
            
            if 'dl' in item:
                gl.glCallList(item['dl'])
            else:
                mesh = item['mesh']
                gl.glBegin(gl.GL_TRIANGLES)
                for face in mesh.faces:
                    for v_idx in face:
                        v = mesh.vertices[v_idx]
                        gl.glVertex3f(v[0], v[1], v[2])
                gl.glEnd()
            gl.glPopMatrix()
        
        # Draw Gizmo as ID 201-204
        gl.glDisable(gl.GL_DEPTH_TEST) # Gizmo always on top
        if self.selected_object:
            # Only draw gizmo if it's not the camera
            if self.selected_object != 'Camera':
                self.draw_gizmo(picking=True)
        gl.glEnable(gl.GL_DEPTH_TEST)
        
        # Read pixel
        x = int(pos.x())
        y = int(self.height() - pos.y())
        self.active_gizmo_axis = 0
        if x >= 0 and y >= 0 and x < self.width() and y < self.height():
            pixel = gl.glReadPixels(x, y, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
            if pixel:
                r_val = pixel[0]
                if r_val >= 201 and r_val <= 204:
                    self.active_gizmo_axis = r_val - 200
                else:
                    if r_val == 1:
                        self.selected_object = 'HDRI'
                    elif r_val >= 2 and (r_val - 2) < len(self.meshes):
                        self.selected_object = self.meshes[r_val - 2]
                    else:
                        self.selected_object = None
            else:
                self.selected_object = None
        
        # Restore state
        gl.glEnable(gl.GL_LIGHTING)
        gl.glEnable(gl.GL_DEPTH_TEST)
        self.update()
        if hasattr(self.window(), '_sync_obj_ui'):
            self.window()._sync_obj_ui()
            
    def mousePressEvent(self, event):
        pos_func = getattr(event, 'position', getattr(event, 'pos', None))
        self.last_pos = pos_func() if pos_func else QtCore.QPoint()
        
        # Save state for undo
        self._drag_start_state = self._get_scene_state()
        
        # Left click without Alt picks object
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if event.button() == QtCore.Qt.LeftButton and modifiers != QtCore.Qt.AltModifier:
            self.perform_picking(self.last_pos)
            
    def mouseReleaseEvent(self, event):
        self.active_gizmo_axis = 0
        # Push undo state if something changed
        if self._drag_start_state is not None:
            current_state = self._get_scene_state()
            if current_state != self._drag_start_state:
                self.undo_stack.append(self._drag_start_state)
                # Cap undo stack
                if len(self.undo_stack) > 50:
                    self.undo_stack.pop(0)
            self._drag_start_state = None
        
    def mouseMoveEvent(self, event):
        pos_func = getattr(event, 'position', getattr(event, 'pos', None))
        pos = pos_func() if pos_func else QtCore.QPoint()
        dx = pos.x() - self.last_pos.x()
        dy = pos.y() - self.last_pos.y()
        
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        
        # QWERT Tool transformations
        if event.buttons() == QtCore.Qt.LeftButton and modifiers != QtCore.Qt.AltModifier:
            if self.selected_object and self.tool_mode in ['W', 'E', 'R']:
                if self.active_gizmo_axis > 0:
                    move_scale = self.camera.distance * 0.002
                    
                    # Determine constraint
                    axis = self.active_gizmo_axis
                    
                    amount = 0.0
                    if hasattr(self, '_screen_axes') and axis in self._screen_axes:
                        sx, sy = self._screen_axes[axis]
                        length = math.hypot(sx, sy)
                        if length > 0.001:
                            sx, sy = sx / length, sy / length
                        else:
                            sx, sy = 1.0, 0.0
                        
                        # Project mouse delta (dx, -dy) onto normalized screen axis
                        amount = (dx * sx + (-dy) * sy)
                    else:
                        amount = dx # fallback
                    
                    world_x, world_y, world_z = 0.0, 0.0, 0.0
                    rot_x, rot_y, rot_z = 0.0, 0.0, 0.0
                    scale_x, scale_y, scale_z = 1.0, 1.0, 1.0
                    
                    if self.tool_mode == 'W':
                        if axis == 1: world_x = amount * move_scale
                        elif axis == 2: world_y = amount * move_scale
                        elif axis == 3: world_z = amount * move_scale
                        else: # Center (screen space)
                            yaw = math.radians(self.camera.rotation_y)
                            world_x = dx * move_scale * math.cos(yaw)
                            world_z = dx * move_scale * math.sin(yaw)
                            world_y = -dy * move_scale
                    elif self.tool_mode == 'E':
                        if axis == 1: rot_x = amount * 0.5
                        elif axis == 2: rot_y = amount * 0.5
                        elif axis == 3: rot_z = amount * 0.5
                        else: # Center (free)
                            rot_x = dy * 0.5
                            rot_y = dx * 0.5
                    elif self.tool_mode == 'R':
                        scale_delta = 1.0 + (amount) * 0.01
                        if axis == 1: scale_x = scale_delta
                        elif axis == 2: scale_y = scale_delta
                        elif axis == 3: scale_z = scale_delta
                        else: # Uniform
                            scale_x = scale_y = scale_z = scale_delta
                            
                    if self.selected_object == 'HDRI':
                        if self.tool_mode == 'W':
                            self.hdri_translate[0] += world_x
                            self.hdri_translate[1] += world_y
                            self.hdri_translate[2] += world_z
                        elif self.tool_mode == 'E':
                            self.hdri_rotate[0] += rot_x
                            self.hdri_rotate[1] += rot_y
                            self.hdri_rotate[2] += rot_z
                        elif self.tool_mode == 'R':
                            self.hdri_radius *= scale_x # Only uniform for dome
                    elif isinstance(self.selected_object, dict):
                        if self.tool_mode == 'W':
                            self.selected_object['t'][0] += world_x
                            self.selected_object['t'][1] += world_y
                            self.selected_object['t'][2] += world_z
                        elif self.tool_mode == 'E':
                            self.selected_object['r'][0] += rot_x
                            self.selected_object['r'][1] += rot_y
                            self.selected_object['r'][2] += rot_z
                        elif self.tool_mode == 'R':
                            self.selected_object['s'][0] *= scale_x
                            self.selected_object['s'][1] *= scale_y
                            self.selected_object['s'][2] *= scale_z
                    elif isinstance(self.selected_object, str) and self.selected_object.startswith('Mask_'):
                        mask_id = self.selected_object.split('_')[1]
                        main_window = self.window().parent()
                        if hasattr(main_window, 'pipeline'):
                            for mask in main_window.pipeline.state.masks:
                                if mask.id == mask_id and hasattr(mask, 'transform_3d'):
                                    if self.tool_mode == 'W':
                                        mask.transform_3d['t'][0] += world_x
                                        mask.transform_3d['t'][1] += world_y
                                        mask.transform_3d['t'][2] += world_z
                                    elif self.tool_mode == 'E':
                                        mask.transform_3d['r'][0] += rot_x
                                        mask.transform_3d['r'][1] += rot_y
                                        mask.transform_3d['r'][2] += rot_z
                                    elif self.tool_mode == 'R':
                                        mask.transform_3d['s'][0] *= scale_x
                                        mask.transform_3d['s'][1] *= scale_y
                                        mask.transform_3d['s'][2] *= scale_z
                                    break
                        
                    self.update()
                    if hasattr(self.window(), '_sync_obj_ui'):
                        self.window()._sync_obj_ui()
                self.last_pos = pos
            return
            
        # Nuke style controls: Alt + Mouse buttons
        if modifiers == QtCore.Qt.AltModifier:
            if event.buttons() == QtCore.Qt.LeftButton:
                # Orbit
                self.camera.rotation_y += dx * 0.5
                self.camera.rotation_x += dy * 0.5
                # Clamp elevation
                self.camera.rotation_x = max(-90.0, min(90.0, self.camera.rotation_x))
            elif event.buttons() == QtCore.Qt.MiddleButton:
                # Pan
                self.camera.pan(dx, dy)
            elif event.buttons() == QtCore.Qt.RightButton:
                # Zoom
                self.camera.distance *= (1.0 + dy * 0.01)
                self.camera.distance = max(0.1, min(1000.0, self.camera.distance))
                
            self.update()
            
            # Sync UI if it exists
            if hasattr(self.window(), '_sync_cam_ui'):
                self.window()._sync_cam_ui()
            
        self.last_pos = pos
        
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.camera.distance *= 0.9
        else:
            self.camera.distance *= 1.1
        self.camera.distance = max(0.1, min(10000.0, self.camera.distance))
        self.update()
        if hasattr(self.window(), '_sync_cam_ui'):
            self.window()._sync_cam_ui()

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        
        if key == QtCore.Qt.Key_Z and modifiers == QtCore.Qt.ControlModifier:
            if self.undo_stack:
                last_state = self.undo_stack.pop()
                self._apply_scene_state(last_state)
            return
            
        if key == QtCore.Qt.Key_Q:
            self.tool_mode = 'Q'
        elif key == QtCore.Qt.Key_W:
            self.tool_mode = 'W'
        elif key == QtCore.Qt.Key_E:
            self.tool_mode = 'E'
        elif key == QtCore.Qt.Key_R:
            self.tool_mode = 'R'
        elif key == QtCore.Qt.Key_F:
            self.frame_selected()
            
        # Highlight active mode in window title or visually
        if hasattr(self.window(), 'setWindowTitle'):
            tools = {'Q': 'Select', 'W': 'Translate', 'E': 'Rotate', 'R': 'Scale'}
            self.window().setWindowTitle(f"3D Viewport - Tool: {tools.get(self.tool_mode, '')}")
            
        super().keyPressEvent(event)

    def frame_selected(self):
        if not self.selected_object: return
        
        target_pos = None
        target_size = 10.0
        
        if self.selected_object == 'HDRI':
            target_pos = self.hdri_translate
            target_size = self.hdri_radius * 2.0
        elif isinstance(self.selected_object, dict): # Mesh
            target_pos = self.selected_object['t']
            target_size = 10.0 * max(self.selected_object['s'])
        elif isinstance(self.selected_object, str) and self.selected_object.startswith("Mask_"):
            mask_id = self.selected_object.split("_")[1]
            main_window = self.window().parent()
            if hasattr(main_window, 'pipeline'):
                for mask in main_window.pipeline.state.masks:
                    if mask.id == mask_id and hasattr(mask, 'transform_3d') and mask.rect:
                        rx, ry, rx2, ry2 = mask.rect
                        u = (rx + rx2) / 2.0
                        v = (ry + ry2) / 2.0
                        yaw_norm = getattr(main_window, '_mask_yaw', 0.0) / 360.0
                        vis_u = (u + yaw_norm) % 1.0
                        theta = vis_u * 2 * math.pi
                        phi = (1.0 - v) * math.pi
                        R = self.hdri_radius - 1.0
                        x = math.sin(phi) * math.cos(theta) * R
                        y = math.cos(phi) * R
                        z = -math.sin(phi) * math.sin(theta) * R
                        
                        import numpy as np
                        def rotY(ang):
                            c, s = np.cos(ang), np.sin(ang)
                            return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]])
                        def rotX(ang):
                            c, s = np.cos(ang), np.sin(ang)
                            return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]])
                        
                        T_base = np.eye(4)
                        T_base[0:3, 3] = [x, y, z]
                        Ry = rotY(theta - math.pi/2)
                        Rx = rotX(math.pi/2 - phi)
                        T_local = np.eye(4)
                        T_local[0:3, 3] = mask.transform_3d['t']
                        
                        final_mat = T_base @ Ry @ Rx @ T_local
                        
                        target_pos = final_mat[0:3, 3]
                        
                        w = (rx2 - rx) * mask.transform_3d['s'][0]
                        h = (ry2 - ry) * mask.transform_3d['s'][1]
                        target_size = max(w, h) * R * 1.5
                        break
        
        if target_pos is not None:
            self.camera.pan_x = target_pos[0]
            self.camera.pan_y = target_pos[1]
            self.camera.pan_z = target_pos[2]
            
            fov_rad = math.radians(self.camera.get_fov())
            if fov_rad > 0:
                self.camera.distance = (target_size / 2.0) / math.tan(fov_rad / 2.0)
            
            self.update()
            if hasattr(self.window(), '_sync_cam_ui'):
                self.window()._sync_cam_ui()

class ViewportWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("3D Viewport")
        self.resize(800, 600)
        
        # Create central widget and layout
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        toolbar = QtWidgets.QToolBar("Tools")
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #2b2b2b;
                border-bottom: 1px solid #1a1a1a;
                spacing: 5px;
            }
            QToolButton {
                background-color: transparent;
                border: none;
                font-weight: normal;
                text-shadow: none;
            }
            QToolButton:hover {
                background-color: #555555;
                border-radius: 2px;
            }
        """)
        self.addToolBar(toolbar)
        
        self.btn_load = QAction("Load Geometry", self)
        self.btn_load.triggered.connect(self.load_geometry)
        toolbar.addAction(self.btn_load)
        
        self.btn_clear = QAction("Clear Scene", self)
        self.btn_clear.triggered.connect(self.clear_scene)
        toolbar.addAction(self.btn_clear)
        
        toolbar.addSeparator()

        self.btn_add_chrome = QAction("Add Chrome Ball", self)
        self.btn_add_chrome.triggered.connect(lambda: self.add_ibl_sphere("Chrome"))
        toolbar.addAction(self.btn_add_chrome)

        self.btn_add_grey = QAction("Add Grey Ball", self)
        self.btn_add_grey.triggered.connect(lambda: self.add_ibl_sphere("Grey"))
        toolbar.addAction(self.btn_add_grey)
        
        toolbar.addSeparator()
        
        self.btn_apply = QAction("Apply to Project", self)
        self.btn_apply.triggered.connect(self.apply_to_project)
        toolbar.addAction(self.btn_apply)
        
        self.btn_nuke_export = QAction("Export Nuke Setup", self)
        self.btn_nuke_export.triggered.connect(self.export_nuke_setup)
        toolbar.addAction(self.btn_nuke_export)
        
        # Viewport
        self.viewport = Viewport3D()
        layout.addWidget(self.viewport)
        
        # Outliner setup
        outliner_dock = QtWidgets.QDockWidget("Outliner", self)
        outliner_dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        
        self.outliner = QtWidgets.QTreeWidget()
        self.outliner.setHeaderLabels(["Scene Objects"])
        self.outliner.itemSelectionChanged.connect(self._on_outliner_select)
        outliner_dock.setWidget(self.outliner)
        
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, outliner_dock)
        
        # Properties Panel
        self.create_properties_panel()
        
        self._refresh_outliner()
    def export_nuke_setup(self):
        main_window = self.main_window
        if not hasattr(main_window, 'pipeline'):
            return
            
        vp_state = {
            'hdri_radius': self.viewport.hdri_radius,
            'hdri_translate': self.viewport.hdri_translate,
            'hdri_rotate': self.viewport.hdri_rotate,
            'cam_fl': self.viewport.camera.focal_length,
            'cam_sensor': self.viewport.camera.sensor_height,
            'cam_focus': self.viewport.camera.focus_distance,
            'cam_dist': self.viewport.camera.distance,
            'cam_pan_x': self.viewport.camera.pan_x,
            'cam_pan_y': self.viewport.camera.pan_y,
            'cam_pan_z': self.viewport.camera.pan_z,
            'cam_rot_x': self.viewport.camera.rotation_x,
            'cam_rot_y': self.viewport.camera.rotation_y,
            'meshes': self.viewport.meshes
        }
        
        from hdri_match.io.nuke_export import export_nuke_3d_scene
        nuke_script = export_nuke_3d_scene(main_window.pipeline.state, vp_state)
        QtWidgets.QApplication.clipboard().setText(nuke_script)
        QtWidgets.QMessageBox.information(self, "Export Nuke Setup", "Basic Nuke 3D Scene copied to clipboard!")

    def apply_to_project(self):
        main_window = self.main_window
        if not hasattr(main_window, 'pipeline'):
            return
            
        import math
        import numpy as np
        
        # 1. Sync HDRI Rotation
        yaw_offset = self.viewport.hdri_rotate[1]
        if yaw_offset != 0.0:
            current_yaw = main_window.slider_yaw.value()
            new_yaw = int((current_yaw + yaw_offset) % 360)
            if new_yaw > 180: new_yaw -= 360
            if new_yaw < -180: new_yaw += 360
            main_window.slider_yaw.setValue(new_yaw)
            main_window.on_yaw_slider_changed()
            self.viewport.hdri_rotate[1] = 0.0
            
        # 2. Sync Masks
        for mask in main_window.pipeline.state.masks:
            if hasattr(mask, 'transform_3d') and mask.rect:
                rx, ry, rx2, ry2 = mask.rect
                u = (rx + rx2) / 2.0
                v = (ry + ry2) / 2.0
                w = rx2 - rx
                h = ry2 - ry
                
                # Scale
                s_x, s_y, s_z = mask.transform_3d['s']
                new_w = w * s_x
                new_h = h * s_y
                
                # Translation
                yaw_norm = getattr(main_window, '_mask_yaw', 0.0) / 360.0
                vis_u = (u + yaw_norm) % 1.0
                theta = vis_u * 2 * math.pi
                phi = (1.0 - v) * math.pi
                
                R = self.viewport.hdri_radius - 1.0
                base_x = math.sin(phi) * math.cos(theta)
                base_y = math.cos(phi)
                base_z = -math.sin(phi) * math.sin(theta)
                
                def rotY(ang):
                    c, s = np.cos(ang), np.sin(ang)
                    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]])
                def rotX(ang):
                    c, s = np.cos(ang), np.sin(ang)
                    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]])
                
                T_base = np.eye(4)
                T_base[0:3, 3] = [base_x*R, base_y*R, base_z*R]
                
                Ry = rotY(theta - math.pi/2)
                Rx = rotX(math.pi/2 - phi)
                
                # Local user rotation
                def rotZ(ang):
                    c, s = np.cos(ang), np.sin(ang)
                    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
                    
                R_lx = rotX(math.radians(mask.transform_3d['r'][0]))
                R_ly = rotY(math.radians(mask.transform_3d['r'][1]))
                R_lz = rotZ(math.radians(mask.transform_3d['r'][2]))
                
                T_local = np.eye(4)
                T_local[0:3, 3] = mask.transform_3d['t']
                
                final_mat = T_base @ Ry @ Rx @ R_lx @ R_ly @ R_lz @ T_local
                new_pos = final_mat[0:3, 3]
                
                r = np.linalg.norm(new_pos)
                if r > 0.0001:
                    new_x, new_y, new_z = new_pos
                    new_phi = math.acos(max(-1.0, min(1.0, new_y / r)))
                    new_theta = math.atan2(-new_z, new_x)
                    if new_theta < 0:
                        new_theta += 2 * math.pi
                        
                    new_v = 1.0 - (new_phi / math.pi)
                    new_vis_u = new_theta / (2 * math.pi)
                    new_u = (new_vis_u - yaw_norm) % 1.0
                    
                    mask.rect = [new_u - new_w/2, new_v - new_h/2, new_u + new_w/2, new_v + new_h/2]
                
                mask.transform_3d = {'t': [0.0, 0.0, 0.0], 'r': [0.0, 0.0, 0.0], 's': [1.0, 1.0, 1.0]}
                
        main_window._trigger_update()
        
        # Force the 2D UI to redraw the visual rectangle of the currently active mask
        active_mask = main_window.get_active_mask()
        if active_mask and active_mask.rect:
            main_window.viewer_left.set_mask_rect_normalized(active_mask.rect)
            
        self.viewport.update()
        QtWidgets.QMessageBox.information(self, "Success", "3D adjustments successfully baked into 2D project!")
        
    def _refresh_outliner(self):
        self.outliner.clear()
        
        root = QtWidgets.QTreeWidgetItem(self.outliner, ["Scene"])
        
        cam_item = QtWidgets.QTreeWidgetItem(root, ["Camera"])
        cam_item.setData(0, QtCore.Qt.UserRole, "Camera")
        
        hdri_item = QtWidgets.QTreeWidgetItem(root, ["HDRI Dome"])
        hdri_item.setData(0, QtCore.Qt.UserRole, "HDRI")
        
        # Add Masks from Pipeline under Scene, not HDRI
        main_window = self.window().parent()
        if hasattr(main_window, 'pipeline'):
            masks = main_window.pipeline.state.masks
            if masks:
                masks_root = QtWidgets.QTreeWidgetItem(root, ["Mask Cards"])
                for i, mask in enumerate(masks):
                    m_item = QtWidgets.QTreeWidgetItem(masks_root, [f"Mask {mask.id}"])
                    m_item.setData(0, QtCore.Qt.UserRole, f"Mask_{mask.id}")
                    
        if self.viewport.meshes:
            geo_root = QtWidgets.QTreeWidgetItem(root, ["Geometry"])
            for idx, mesh in enumerate(self.viewport.meshes):
                item = QtWidgets.QTreeWidgetItem(geo_root, [mesh['name']])
                item.setData(0, QtCore.Qt.UserRole, idx) # Store index
                
        self.outliner.expandAll()
        
    def _on_outliner_select(self):
        items = self.outliner.selectedItems()
        if not items:
            self.viewport.selected_object = None
            self._sync_obj_ui()
            self.viewport.update()
            return
            
        data = items[0].data(0, QtCore.Qt.UserRole)
        if data == "HDRI":
            self.viewport.selected_object = 'HDRI'
        elif data == "Camera":
            self.viewport.selected_object = 'Camera'
        elif isinstance(data, str) and data.startswith("Mask_"):
            self.viewport.selected_object = data
            # Sync selection to main UI mask list
            main_window = self.window().parent()
            if hasattr(main_window, 'mask_list'):
                mask_id = data.split("_")[1]
                for i in range(main_window.mask_list.count()):
                    item = main_window.mask_list.item(i)
                    if item.data(QtCore.Qt.UserRole).id == mask_id:
                        main_window.mask_list.setCurrentRow(i)
                        break
        elif isinstance(data, int):
            self.viewport.selected_object = self.viewport.meshes[data]
        else:
            self.viewport.selected_object = None
            
        self._sync_obj_ui()
        self.viewport.update()
        
    def create_properties_panel(self):
        dock = QtWidgets.QDockWidget("Properties", self)
        dock.setAllowedAreas(QtCore.Qt.RightDockWidgetArea | QtCore.Qt.LeftDockWidgetArea)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFloatable)
        
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QtWidgets.QWidget()
        scroll.setWidget(panel)
        layout = QtWidgets.QFormLayout(panel)
        
        # Display Settings
        layout.addRow(QtWidgets.QLabel("<b>Display</b>"))

        self.chk_show_bg = QtWidgets.QCheckBox("Show Match Plate BG")
        self.chk_show_bg.setChecked(self.viewport.show_bg)
        self.chk_show_bg.toggled.connect(self._update_display)
        layout.addRow(self.chk_show_bg)

        self.chk_show_frustum = QtWidgets.QCheckBox("Show Camera Frustum")
        self.chk_show_frustum.setChecked(self.viewport.show_frustum)
        self.chk_show_frustum.toggled.connect(self._update_display)
        layout.addRow(self.chk_show_frustum)
        
        self.chk_show_ground = QtWidgets.QCheckBox("Show Ground Plane")
        self.chk_show_ground.setChecked(getattr(self.viewport, 'show_ground_plane', True))
        self.chk_show_ground.toggled.connect(self._update_display)
        layout.addRow(self.chk_show_ground)

        ev_layout = QtWidgets.QHBoxLayout()
        
        self.slider_dome_ev = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_dome_ev.setRange(-100, 100)
        self.slider_dome_ev.setValue(int(self.viewport.dome_ev * 10))
        self.slider_dome_ev.valueChanged.connect(lambda v: self.spin_dome_ev.setValue(v / 10.0))
        
        self.spin_dome_ev = QtWidgets.QDoubleSpinBox()
        self.spin_dome_ev.setRange(-10.0, 10.0)
        self.spin_dome_ev.setSingleStep(0.5)
        self.spin_dome_ev.setValue(self.viewport.dome_ev)
        
        def on_spin_ev(v):
            self.slider_dome_ev.blockSignals(True)
            self.slider_dome_ev.setValue(int(v * 10))
            self.slider_dome_ev.blockSignals(False)
            self._update_display()
            
        self.spin_dome_ev.valueChanged.connect(on_spin_ev)
        
        self.btn_reset_dome_ev = QtWidgets.QPushButton("⟳")
        self.btn_reset_dome_ev.setFixedWidth(24)
        self.btn_reset_dome_ev.clicked.connect(lambda: self.spin_dome_ev.setValue(0.0))
        
        ev_layout.addWidget(self.slider_dome_ev)
        ev_layout.addWidget(self.spin_dome_ev)
        ev_layout.addWidget(self.btn_reset_dome_ev)
        
        layout.addRow("Dome EV:", ev_layout)

        # Camera Settings
        layout.addRow(QtWidgets.QLabel("<br><b>Camera</b>"))

        self.btn_reset_cam = QtWidgets.QPushButton("Reset to Match Camera (Origin)")
        self.btn_reset_cam.clicked.connect(self._reset_to_match_camera)
        layout.addRow(self.btn_reset_cam)
        
        self.cam_fl = QtWidgets.QDoubleSpinBox()
        self.cam_fl.setRange(1.0, 1000.0)
        self.cam_fl.setValue(self.viewport.camera.focal_length)
        self.cam_fl.valueChanged.connect(self._update_cam)
        layout.addRow("Focal Length (mm):", self.cam_fl)
        
        self.cam_sensor = QtWidgets.QDoubleSpinBox()
        self.cam_sensor.setRange(1.0, 100.0)
        self.cam_sensor.setValue(self.viewport.camera.sensor_height)
        self.cam_sensor.valueChanged.connect(self._update_cam)
        layout.addRow("Sensor Height (mm):", self.cam_sensor)
        
        self.cam_focus = QtWidgets.QDoubleSpinBox()
        self.cam_focus.setRange(0.1, 10000.0)
        self.cam_focus.setValue(self.viewport.camera.focus_distance)
        self.cam_focus.valueChanged.connect(self._update_cam)
        layout.addRow("Focus Distance:", self.cam_focus)
        
        self.chk_show_focus = QtWidgets.QCheckBox("Show Focus Plane")
        self.chk_show_focus.setChecked(getattr(self.viewport, 'show_focus_plane', False))
        self.chk_show_focus.toggled.connect(self._update_display)
        layout.addRow(self.chk_show_focus)
        
        self.cam_dist = QtWidgets.QDoubleSpinBox()
        self.cam_dist.setRange(0.1, 10000.0)
        self.cam_dist.setValue(self.viewport.camera.distance)
        self.cam_dist.valueChanged.connect(self._update_cam)
        layout.addRow("Distance:", self.cam_dist)
        
        self.cam_pan_x = QtWidgets.QDoubleSpinBox()
        self.cam_pan_x.setRange(-10000.0, 10000.0)
        self.cam_pan_x.setValue(self.viewport.camera.pan_x)
        self.cam_pan_x.valueChanged.connect(self._update_cam)
        layout.addRow("Pan X:", self.cam_pan_x)
        
        self.cam_pan_y = QtWidgets.QDoubleSpinBox()
        self.cam_pan_y.setRange(-10000.0, 10000.0)
        self.cam_pan_y.setValue(self.viewport.camera.pan_y)
        self.cam_pan_y.valueChanged.connect(self._update_cam)
        layout.addRow("Pan Y:", self.cam_pan_y)
        
        self.cam_pan_z = QtWidgets.QDoubleSpinBox()
        self.cam_pan_z.setRange(-10000.0, 10000.0)
        self.cam_pan_z.setValue(self.viewport.camera.pan_z)
        self.cam_pan_z.valueChanged.connect(self._update_cam)
        layout.addRow("Pan Z:", self.cam_pan_z)
        
        self.cam_rot_x = QtWidgets.QDoubleSpinBox()
        self.cam_rot_x.setRange(-90.0, 90.0)
        self.cam_rot_x.setValue(self.viewport.camera.rotation_x)
        self.cam_rot_x.valueChanged.connect(self._update_cam)
        layout.addRow("Elevation (Pitch):", self.cam_rot_x)
        
        self.cam_rot_y = QtWidgets.QDoubleSpinBox()
        self.cam_rot_y.setRange(-360.0, 360.0)
        self.cam_rot_y.setValue(self.viewport.camera.rotation_y)
        self.cam_rot_y.valueChanged.connect(self._update_cam)
        layout.addRow("Azimuth (Yaw):", self.cam_rot_y)
        
        # Object Transform Settings (Dynamic based on selection)
        layout.addRow(QtWidgets.QLabel("<br><b>Object Transform</b>"))
        
        self.obj_rad = QtWidgets.QDoubleSpinBox()
        self.obj_rad.setRange(0.001, 10000.0)
        self.obj_rad.valueChanged.connect(self._update_obj)
        layout.addRow("Scale/Radius:", self.obj_rad)
        
        self.obj_tx = QtWidgets.QDoubleSpinBox()
        self.obj_tx.setRange(-10000.0, 10000.0)
        self.obj_tx.valueChanged.connect(self._update_obj)
        layout.addRow("Translate X:", self.obj_tx)
        
        self.obj_ty = QtWidgets.QDoubleSpinBox()
        self.obj_ty.setRange(-10000.0, 10000.0)
        self.obj_ty.valueChanged.connect(self._update_obj)
        layout.addRow("Translate Y:", self.obj_ty)
        
        self.obj_tz = QtWidgets.QDoubleSpinBox()
        self.obj_tz.setRange(-10000.0, 10000.0)
        self.obj_tz.valueChanged.connect(self._update_obj)
        layout.addRow("Translate Z:", self.obj_tz)
        
        self.obj_rx = QtWidgets.QDoubleSpinBox()
        self.obj_rx.setRange(-360.0, 360.0)
        self.obj_rx.valueChanged.connect(self._update_obj)
        layout.addRow("Rotate X:", self.obj_rx)
        
        self.obj_ry = QtWidgets.QDoubleSpinBox()
        self.obj_ry.setRange(-360.0, 360.0)
        self.obj_ry.valueChanged.connect(self._update_obj)
        layout.addRow("Rotate Y:", self.obj_ry)
        
        self.obj_rz = QtWidgets.QDoubleSpinBox()
        self.obj_rz.setRange(-360.0, 360.0)
        self.obj_rz.valueChanged.connect(self._update_obj)
        layout.addRow("Rotate Z:", self.obj_rz)
        
        dock.setWidget(scroll)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    def _update_display(self):
        self.viewport.show_bg = self.chk_show_bg.isChecked()
        self.viewport.show_frustum = self.chk_show_frustum.isChecked()
        self.viewport.show_focus_plane = self.chk_show_focus.isChecked()
        self.viewport.show_ground_plane = self.chk_show_ground.isChecked()
        self.viewport.dome_ev = self.spin_dome_ev.value()
        self.viewport.update()

    def _reset_to_match_camera(self):
        self.viewport.camera.distance = 0.0
        self.viewport.camera.pan_x = 0.0
        self.viewport.camera.pan_y = 0.0
        self.viewport.camera.pan_z = 0.0
        self.viewport.camera.rotation_x = 0.0
        self.viewport.camera.rotation_y = 0.0
        self._sync_cam_ui()
        self.viewport.update_projection()
        self.viewport.update()

    def _update_cam(self):
        self.viewport.camera.focal_length = self.cam_fl.value()
        self.viewport.camera.sensor_height = self.cam_sensor.value()
        self.viewport.camera.focus_distance = self.cam_focus.value()
        self.viewport.camera.distance = self.cam_dist.value()
        self.viewport.camera.pan_x = self.cam_pan_x.value()
        self.viewport.camera.pan_y = self.cam_pan_y.value()
        self.viewport.camera.pan_z = self.cam_pan_z.value()
        self.viewport.camera.rotation_x = self.cam_rot_x.value()
        self.viewport.camera.rotation_y = self.cam_rot_y.value()
        self.viewport.update_projection()
        self.viewport.update()
        
    def _sync_cam_ui(self):
        self.cam_dist.blockSignals(True)
        self.cam_pan_x.blockSignals(True)
        self.cam_pan_y.blockSignals(True)
        self.cam_pan_z.blockSignals(True)
        self.cam_rot_x.blockSignals(True)
        self.cam_rot_y.blockSignals(True)
        self.cam_focus.blockSignals(True)
        
        self.cam_dist.setValue(self.viewport.camera.distance)
        self.cam_pan_x.setValue(self.viewport.camera.pan_x)
        self.cam_pan_y.setValue(self.viewport.camera.pan_y)
        self.cam_pan_z.setValue(self.viewport.camera.pan_z)
        self.cam_rot_x.setValue(self.viewport.camera.rotation_x)
        self.cam_rot_y.setValue(self.viewport.camera.rotation_y)
        self.cam_focus.setValue(self.viewport.camera.focus_distance)
        
        self.cam_dist.blockSignals(False)
        self.cam_pan_x.blockSignals(False)
        self.cam_pan_y.blockSignals(False)
        self.cam_pan_z.blockSignals(False)
        self.cam_rot_x.blockSignals(False)
        self.cam_rot_y.blockSignals(False)
        self.cam_focus.blockSignals(False)
        
    def _update_obj(self):
        obj = self.viewport.selected_object
        if not obj: return
        
        if obj == 'HDRI':
            self.viewport.hdri_radius = self.obj_rad.value()
            self.viewport.hdri_translate = [self.obj_tx.value(), self.obj_ty.value(), self.obj_tz.value()]
            self.viewport.hdri_rotate = [self.obj_rx.value(), self.obj_ry.value(), self.obj_rz.value()]
        elif isinstance(obj, dict):
            obj['s'] = [self.obj_rad.value()]*3
            obj['t'] = [self.obj_tx.value(), self.obj_ty.value(), self.obj_tz.value()]
            obj['r'] = [self.obj_rx.value(), self.obj_ry.value(), self.obj_rz.value()]
        elif isinstance(obj, str) and obj.startswith('Mask_'):
            mask_id = obj.split('_')[1]
            main_window = self.viewport.window().parent()
            if hasattr(main_window, 'pipeline'):
                for mask in main_window.pipeline.state.masks:
                    if mask.id == mask_id and hasattr(mask, 'transform_3d'):
                        mask.transform_3d['s'] = [self.obj_rad.value()]*3
                        mask.transform_3d['t'] = [self.obj_tx.value(), self.obj_ty.value(), self.obj_tz.value()]
                        mask.transform_3d['r'] = [self.obj_rx.value(), self.obj_ry.value(), self.obj_rz.value()]
                        break
            
        self.viewport.update()
        
    def _sync_obj_ui(self):
        obj = self.viewport.selected_object
        
        widgets = [self.obj_rad, self.obj_tx, self.obj_ty, self.obj_tz, 
                   self.obj_rx, self.obj_ry, self.obj_rz]
                   
        for w in widgets: w.blockSignals(True)
        
        if not obj:
            for w in widgets: w.setEnabled(False)
        else:
            for w in widgets: w.setEnabled(True)
            if obj == 'HDRI':
                self.obj_rad.setValue(self.viewport.hdri_radius)
                self.obj_tx.setValue(self.viewport.hdri_translate[0])
                self.obj_ty.setValue(self.viewport.hdri_translate[1])
                self.obj_tz.setValue(self.viewport.hdri_translate[2])
                self.obj_rx.setValue(self.viewport.hdri_rotate[0])
                self.obj_ry.setValue(self.viewport.hdri_rotate[1])
                self.obj_rz.setValue(self.viewport.hdri_rotate[2])
            elif isinstance(obj, dict):
                self.obj_rad.setValue(obj['s'][0]) # Assuming uniform scale for now
                self.obj_tx.setValue(obj['t'][0])
                self.obj_ty.setValue(obj['t'][1])
                self.obj_tz.setValue(obj['t'][2])
                self.obj_rx.setValue(obj['r'][0])
                self.obj_ry.setValue(obj['r'][1])
                self.obj_rz.setValue(obj['r'][2])
            elif isinstance(obj, str) and obj.startswith('Mask_'):
                mask_id = obj.split('_')[1]
                main_window = self.viewport.window().parent()
                if hasattr(main_window, 'pipeline'):
                    for mask in main_window.pipeline.state.masks:
                        if mask.id == mask_id and hasattr(mask, 'transform_3d'):
                            self.obj_rad.setValue(mask.transform_3d['s'][0])
                            self.obj_tx.setValue(mask.transform_3d['t'][0])
                            self.obj_ty.setValue(mask.transform_3d['t'][1])
                            self.obj_tz.setValue(mask.transform_3d['t'][2])
                            self.obj_rx.setValue(mask.transform_3d['r'][0])
                            self.obj_ry.setValue(mask.transform_3d['r'][1])
                            self.obj_rz.setValue(mask.transform_3d['r'][2])
                            break
                
        for w in widgets: w.blockSignals(False)
        
    def load_geometry(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Geometry", "", "3D Files (*.obj *.fbx *.stl *.ply *.usd *.usda *.usdc *.abc)"
        )
        if file_path:
            if self.viewport.load_mesh(file_path):
                self._refresh_outliner()
                
    def clear_scene(self):
        self.viewport.meshes.clear()
        self.viewport.selected_object = None
        self._refresh_outliner()
        self._sync_obj_ui()
        self.viewport.update()

    def add_ibl_sphere(self, material_type):
        from OpenGL import GL as gl
        from OpenGL import GLU as glu
        
        # Place them in the top-left of the camera frustum (Z = -10.0)
        # We can offset them slightly so they don't overlap if both added
        # Using a radius of 0.2, diameter is 0.4.
        offset_x = -3.2 if material_type == "Chrome" else -3.8

        # Compile display list for performance
        self.viewport.makeCurrent()
        dl = gl.glGenLists(1)
        gl.glNewList(dl, gl.GL_COMPILE)
        
        qobj = glu.gluNewQuadric()
        glu.gluQuadricTexture(qobj, gl.GL_TRUE)
        glu.gluQuadricNormals(qobj, glu.GLU_SMOOTH)
        
        # We must rotate the sphere so poles are Y axis. gluSphere poles are Z axis.
        gl.glPushMatrix()
        gl.glRotatef(-90.0, 1.0, 0.0, 0.0)
        gl.glRotatef(-90.0, 0.0, 0.0, 1.0)
        glu.gluSphere(qobj, 0.2, 32, 32)
        gl.glPopMatrix()
        
        glu.gluDeleteQuadric(qobj)
        
        gl.glEndList()
        self.viewport.doneCurrent()

        mesh_dict = {
            'name': f"{material_type} Ball",
            'mesh': None, # We no longer need trimesh
            'dl': dl,
            'material': material_type, # We'll use this in draw_meshes to apply IBL shading
            't': [offset_x, 2.0, -10.0],
            'r': [0.0, 0.0, 0.0],
            's': [1.0, 1.0, 1.0]
        }
        
        self.viewport.meshes.append(mesh_dict)
        self.viewport.selected_object = mesh_dict
        self._refresh_outliner()
        self._sync_obj_ui()
        self.viewport.update()

