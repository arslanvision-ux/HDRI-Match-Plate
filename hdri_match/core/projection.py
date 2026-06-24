import numpy as np
import cv2

class SphericalProjector:
    @staticmethod
    def equi_to_rect(equi_img, cx, cy, pw_eq, ph_eq):
        """Extract a rectilinear (perspective) patch from an equirectangular image."""
        H, W = equi_img.shape[:2]
        
        f = W / (2 * np.pi)
        lambda_0 = (cx / W - 0.5) * 2 * np.pi
        phi_1 = (0.5 - cy / H) * np.pi
        
        # Calculate required rectilinear dimensions to encompass the equirectangular ROI
        lon_min = lambda_0 - (pw_eq / W) * np.pi
        lon_max = lambda_0 + (pw_eq / W) * np.pi
        lat_min = (0.5 - (cy + ph_eq/2) / H) * np.pi
        lat_max = (0.5 - (cy - ph_eq/2) / H) * np.pi
        
        # Sample points along the 4 edges of the bounding box
        edge_pts = 50
        lons = np.concatenate([
            np.linspace(lon_min, lon_max, edge_pts),
            np.linspace(lon_min, lon_max, edge_pts),
            np.full(edge_pts, lon_min),
            np.full(edge_pts, lon_max)
        ])
        lats = np.concatenate([
            np.full(edge_pts, lat_min),
            np.full(edge_pts, lat_max),
            np.linspace(lat_min, lat_max, edge_pts),
            np.linspace(lat_min, lat_max, edge_pts)
        ])
        
        cos_c = np.sin(phi_1) * np.sin(lats) + np.cos(phi_1) * np.cos(lats) * np.cos(lons - lambda_0)
        valid = cos_c > 1e-5
        
        if np.any(valid):
            x = (f * np.cos(lats[valid]) * np.sin(lons[valid] - lambda_0)) / cos_c[valid]
            y = (f * (np.cos(phi_1) * np.sin(lats[valid]) - np.sin(phi_1) * np.cos(lats[valid]) * np.cos(lons[valid] - lambda_0))) / cos_c[valid]
            
            max_x = min(np.max(np.abs(x)), W * 2)
            max_y = min(np.max(np.abs(y)), H * 2)
        else:
            max_x = pw_eq / 2
            max_y = ph_eq / 2
            
        pw = int(np.ceil(max_x * 2)) + 4
        ph = int(np.ceil(max_y * 2)) + 4
        
        # Ensure minimum size
        pw = max(pw, int(pw_eq))
        ph = max(ph, int(ph_eq))

        u, v = np.meshgrid(np.arange(pw), np.arange(ph))
        x = u - pw / 2
        y = ph / 2 - v
        rho = np.sqrt(x**2 + y**2)
        c = np.arctan2(rho, f)
        
        sin_c = np.sin(c)
        cos_c = np.cos(c)
        
        safe_rho = np.where(rho == 0, 1e-5, rho)
        
        lat = np.arcsin(cos_c * np.sin(phi_1) + y * sin_c * np.cos(phi_1) / safe_rho)
        lon = lambda_0 + np.arctan2(x * sin_c, safe_rho * np.cos(phi_1) * cos_c - y * np.sin(phi_1) * sin_c)
        
        # Normalize lon to [-pi, pi]
        lon = (lon + np.pi) % (2 * np.pi) - np.pi
        
        equi_u = (lon / (2 * np.pi) + 0.5) * W
        equi_v = (0.5 - lat / np.pi) * H
        
        rect_img = cv2.remap(equi_img, equi_u.astype(np.float32), equi_v.astype(np.float32), interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        return rect_img

    @staticmethod
    def rect_to_equi_roi(rect_img, cx, cy, out_h, out_w, px1, px2, py1, py2):
        """Warp a rectilinear patch back into an equirectangular ROI bounding box."""
        ph, pw = rect_img.shape[:2]
        lambda_0 = (cx / out_w - 0.5) * 2 * np.pi
        phi_1 = (0.5 - cy / out_h) * np.pi
        f = out_w / (2 * np.pi)
        
        roi_w = px2 - px1
        roi_h = py2 - py1
        
        if roi_w <= 0 or roi_h <= 0:
            return np.zeros((roi_h, roi_w, rect_img.shape[2]), dtype=rect_img.dtype)
            
        equi_u, equi_v = np.meshgrid(np.arange(px1, px2), np.arange(py1, py2))
        lon = (equi_u / out_w - 0.5) * 2 * np.pi
        lat = (0.5 - equi_v / out_h) * np.pi
        
        cos_c = np.sin(phi_1) * np.sin(lat) + np.cos(phi_1) * np.cos(lat) * np.cos(lon - lambda_0)
        valid = cos_c > 0
        
        safe_cos_c = np.where(cos_c == 0, 1e-5, cos_c)
        x = (f * np.cos(lat) * np.sin(lon - lambda_0)) / safe_cos_c
        y = (f * (np.cos(phi_1) * np.sin(lat) - np.sin(phi_1) * np.cos(lat) * np.cos(lon - lambda_0))) / safe_cos_c
        
        u = x + pw / 2
        v = ph / 2 - y
        
        u[~valid] = -1
        v[~valid] = -1
        
        roi_proj = cv2.remap(rect_img, u.astype(np.float32), v.astype(np.float32), interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
        return roi_proj
