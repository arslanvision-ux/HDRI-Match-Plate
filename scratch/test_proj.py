import numpy as np
import cv2

def equi_to_rect(equi_img, cx, cy, pw, ph, fov_h):
    H, W = equi_img.shape[:2]
    lambda_0 = (cx / W - 0.5) * 2 * np.pi
    phi_1 = (0.5 - cy / H) * np.pi
    f = (pw / 2) / np.tan(fov_h / 2)

    u, v = np.meshgrid(np.arange(pw), np.arange(ph))
    x = u - pw / 2
    y = ph / 2 - v
    rho = np.sqrt(x**2 + y**2)
    c = np.arctan2(rho, f)
    
    sin_c = np.sin(c)
    cos_c = np.cos(c)
    
    # Avoid division by zero
    safe_rho = np.where(rho == 0, 1e-5, rho)
    
    lat = np.arcsin(cos_c * np.sin(phi_1) + y * sin_c * np.cos(phi_1) / safe_rho)
    lon = lambda_0 + np.arctan2(x * sin_c, safe_rho * np.cos(phi_1) * cos_c - y * np.sin(phi_1) * sin_c)
    
    # Normalize lon to [-pi, pi]
    lon = (lon + np.pi) % (2 * np.pi) - np.pi
    
    equi_u = (lon / (2 * np.pi) + 0.5) * W
    equi_v = (0.5 - lat / np.pi) * H
    
    # Remap
    rect_img = cv2.remap(equi_img, equi_u.astype(np.float32), equi_v.astype(np.float32), interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    return rect_img

def rect_to_equi(rect_img, cx, cy, fov_h, out_h, out_w):
    ph, pw = rect_img.shape[:2]
    lambda_0 = (cx / out_w - 0.5) * 2 * np.pi
    phi_1 = (0.5 - cy / out_h) * np.pi
    f = (pw / 2) / np.tan(fov_h / 2)
    
    # We only need to remap the bounding box that covers this rect.
    # But for simplicity, let's remap the whole out_h x out_w and see if it works.
    equi_u, equi_v = np.meshgrid(np.arange(out_w), np.arange(out_h))
    lon = (equi_u / out_w - 0.5) * 2 * np.pi
    lat = (0.5 - equi_v / out_h) * np.pi
    
    cos_c = np.sin(phi_1) * np.sin(lat) + np.cos(phi_1) * np.cos(lat) * np.cos(lon - lambda_0)
    
    # valid mask: front hemisphere
    valid = cos_c > 0
    
    safe_cos_c = np.where(cos_c == 0, 1e-5, cos_c)
    x = (f * np.cos(lat) * np.sin(lon - lambda_0)) / safe_cos_c
    y = (f * (np.cos(phi_1) * np.sin(lat) - np.sin(phi_1) * np.cos(lat) * np.cos(lon - lambda_0))) / safe_cos_c
    
    u = x + pw / 2
    v = ph / 2 - y
    
    # Set invalid pixels out of bounds
    u[~valid] = -1
    v[~valid] = -1
    
    equi_proj = cv2.remap(rect_img, u.astype(np.float32), v.astype(np.float32), interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_TRANSPARENT)
    return equi_proj

print("Projections compiled successfully.")
