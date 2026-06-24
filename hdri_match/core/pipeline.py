import os
import numpy as np
from hdri_match.core.data_models import ImageState
from hdri_match.core.colorspace import ColorSpaceManager
from hdri_match.io.loader import load_exr_to_numpy
from hdri_match.calibration.exposure import ExposureAnalyzer
from hdri_match.calibration.white_balance import WhiteBalanceEstimator
from hdri_match.calibration.sun_detection import SunDetector


class CalibrationPipeline:
    """Central processing pipeline for HDRI calibration."""

    def __init__(self):
        self.state = ImageState()
        self.colorspace_manager = ColorSpaceManager()

    def set_ocio_config(self, config_path: str):
        self.colorspace_manager = ColorSpaceManager(config_path)

    def _create_proxy(self, img: np.ndarray, max_dim: int = 800) -> np.ndarray:
        h, w = img.shape[:2]
        if max(w, h) <= max_dim:
            return img.copy()
        scale = max_dim / max(w, h)
        try:
            import cv2
            return cv2.resize(img, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_AREA)
        except ImportError:
            try:
                from scipy.ndimage import zoom
                return zoom(img, (scale, scale, 1), order=1)
            except ImportError:
                import numpy as np
                target_h, target_w = int(h * scale), int(w * scale)
                y = np.linspace(0, h - 1, target_h).astype(int)
                x = np.linspace(0, w - 1, target_w).astype(int)
                if img.ndim == 3:
                    return img[y, :][:, x, :]
                else:
                    return img[y, :][:, x]

    def run_ai_inpaint(self, mask_layer):
        """Extracts the masked ROI, runs the ComfyUI inpainting API, and stores the patch."""
        if not mask_layer or not getattr(mask_layer, 'is_inpainted', False):
            return
            
        from hdri_match.ml.comfyui_bridge import ComfyUIBridge
        import cv2
        
        arr = self.state.plate_proxy if getattr(mask_layer, 'target', 'HDRI') == 'Plate' else self.state.hdri_proxy
        if arr is None:
            arr = self.state.plate_array if getattr(mask_layer, 'target', 'HDRI') == 'Plate' else self.state.hdri_array
        if arr is None or mask_layer.rect is None:
            return
            
        h, w = arr.shape[:2]
        nx1, ny1, nx2, ny2 = mask_layer.rect
        sx1, sx2 = nx1 * w, nx2 * w
        sy1, sy2 = ny1 * h, ny2 * h
        is_hdri = getattr(mask_layer, 'target', 'HDRI') == 'HDRI'
        if is_hdri and sx1 > sx2:
            px1, px2 = 0, w
        else:
            px1, px2 = max(0, int(min(sx1, sx2))), min(w, int(max(sx1, sx2)))
            
        py1, py2 = max(0, int(min(sy1, sy2))), min(h, int(max(sy1, sy2)))
        
        if px2 - px1 < 2 or py2 - py1 < 2:
            return
            
        # Extract Region
        roi_img = arr[py1:py2, px1:px2].copy()
        
        # Build binary mask
        roi_mask = np.zeros((py2-py1, px2-px1), dtype=np.float32)
        if mask_layer.shape in ["Polygon", "Lasso", "Brush"] and getattr(mask_layer, 'points', None):
            pts = []
            prev_x = None
            for (nx, ny) in mask_layer.points:
                x = nx * w
                if prev_x is not None and is_hdri:
                    if x - prev_x > w / 2: x -= w
                    elif prev_x - x > w / 2: x += w
                pts.append([x - px1, (ny * h) - py1])
                prev_x = x
            poly_arr = np.array(pts, np.int32)
            
            if is_hdri:
                poly_arr_left = poly_arr.copy(); poly_arr_left[:, 0] -= w
                poly_arr_right = poly_arr.copy(); poly_arr_right[:, 0] += w
                draw_polys = [poly_arr_left, poly_arr, poly_arr_right]
            else:
                draw_polys = [poly_arr]
                
            roi_mask_u8 = np.zeros((py2-py1, px2-px1), dtype=np.uint8)
            if mask_layer.shape == "Brush":
                cv2.polylines(roi_mask_u8, draw_polys, isClosed=False, color=1, thickness=int(mask_layer.brush_size), lineType=cv2.LINE_8)
            else:
                cv2.fillPoly(roi_mask_u8, draw_polys, 1)
            roi_mask = roi_mask_u8.astype(np.float32)
        else:
            if is_hdri and sx1 > sx2:
                # Mask crosses seam, only edges are masked
                roi_mask[:, 0:int(sx2)] = 1.0
                roi_mask[:, int(sx1):w] = 1.0
            else:
                roi_mask.fill(1.0)
                
        # --- Advanced Keyer Stencil Integration ---
        if getattr(mask_layer, 'stencil_enable', False):
            stencil = self.calculate_stencil(roi_img, mask_layer)
            roi_mask = roi_mask * stencil
            
        # --- Image Decal (Img2Img) Integration ---
        if mask_layer.shape == "Image" and getattr(mask_layer, 'image_path', ''):
            import os
            if os.path.exists(mask_layer.image_path):
                img_decal = cv2.imread(mask_layer.image_path, cv2.IMREAD_UNCHANGED)
                if img_decal is not None:
                    if img_decal.ndim == 3:
                        if img_decal.shape[2] == 4:
                            img_decal = cv2.cvtColor(img_decal, cv2.COLOR_BGRA2RGBA)
                        elif img_decal.shape[2] == 3:
                            img_decal = cv2.cvtColor(img_decal, cv2.COLOR_BGR2RGB)
                            
                    ph, pw = py2 - py1, px2 - px1
                    img_decal = cv2.resize(img_decal, (pw, ph), interpolation=cv2.INTER_AREA)
                    # Convert to float linear
                    img_decal_f = img_decal.astype(np.float32) / 255.0
                    if img_decal_f.ndim == 3 and img_decal_f.shape[-1] == 4:
                        alpha = img_decal_f[..., 3:4]
                        rgb = img_decal_f[..., :3]
                        # sRGB to linear approx for decal
                        rgb = np.power(np.clip(rgb, 0, 1), 2.2)
                        roi_img = roi_img * (1.0 - alpha) + rgb * alpha
                        roi_mask = alpha[..., 0] # Make the mask tight around the decal alpha
                    elif img_decal_f.ndim == 3 and img_decal_f.shape[-1] == 3:
                        rgb = np.power(np.clip(img_decal_f, 0, 1), 2.2)
                        roi_img = rgb
                        roi_mask.fill(1.0)
            
        if is_hdri and getattr(mask_layer, 'spherical_projection', False):
            from hdri_match.core.projection import SphericalProjector
            if sx1 > sx2:
                cx = (sx1 + sx2 + w) / 2.0
                if cx >= w: cx -= w
                pw = int(sx2 + w - sx1)
            else:
                cx = (px1 + px2) / 2.0
                pw = px2 - px1
            cy = (py1 + py2) / 2.0
            ph = py2 - py1
            roi_img = SphericalProjector.equi_to_rect(arr, cx, cy, pw, ph)
            full_mask = np.zeros((h, w), dtype=np.float32)
            full_mask[py1:py2, px1:px2] = roi_mask
            roi_mask = SphericalProjector.equi_to_rect(full_mask, cx, cy, pw, ph)
            if roi_mask.ndim == 3:
                roi_mask = roi_mask[..., 0]
            
        backend = getattr(mask_layer, 'inpaint_backend', "ComfyUI (Local)")
        
        prompt = getattr(mask_layer, 'inpaint_prompt', "")
        neg_prompt = getattr(mask_layer, 'inpaint_negative_prompt', "bad quality, blurry, text, watermark")
        ckpt = getattr(mask_layer, 'inpaint_ckpt', "flux-2-klein-9b-fp8mixed.safetensors")
        unet = getattr(mask_layer, 'inpaint_unet', "")
        clip = getattr(mask_layer, 'inpaint_clip', "qwen_3_8b_fp8mixed.safetensors")
        vae = getattr(mask_layer, 'inpaint_vae', "flux2-vae.safetensors")
        steps = getattr(mask_layer, 'inpaint_steps', 20)
        cfg = getattr(mask_layer, 'inpaint_cfg', 4.0)
        rembg = getattr(mask_layer, 'inpaint_rembg', False)
        denoise = getattr(mask_layer, 'inpaint_denoise', 1.0)
        seed = getattr(mask_layer, 'inpaint_seed', 0)
        profile = getattr(mask_layer, 'inpaint_profile', 'Auto-Detect')
        use_custom_wf = getattr(mask_layer, 'inpaint_use_custom_wf', False)
        custom_wf_path = getattr(mask_layer, 'inpaint_custom_workflow', '') if use_custom_wf else ''
        upscaler = getattr(mask_layer, 'inpaint_upscaler', 'None')
        
        if backend == "Google GenAI (Nano Banana)":
            from hdri_match.ml.genai_bridge import GenAIBridge
            api_key = getattr(mask_layer, 'inpaint_api', "")
            bridge = GenAIBridge(api_key=api_key)
            patch, error = bridge.generate_inpaint(roi_img, roi_mask, prompt, neg_prompt, ckpt, steps, cfg)
        else:
            bridge = ComfyUIBridge(
                api_url=getattr(mask_layer, 'inpaint_api', "http://127.0.0.1:8188"),
                backend=backend
            )
            patch, error = bridge.generate_inpaint(roi_img, roi_mask, prompt, neg_prompt, ckpt, steps, cfg, unet=unet, clip=clip, vae=vae, rembg=rembg, denoise=denoise, profile=profile, custom_wf_path=custom_wf_path, seed=seed, upscaler=upscaler)
        
        mask_layer.inpainted_patch = patch
        
        # Invalidate the graded caches so they get rebuilt with the new patch
        if getattr(mask_layer, 'target', 'HDRI') == 'Plate':
            self.state.plate_graded = None
            self.state.plate_graded_proxy = None
        else:
            self.state.calibrated_hdri = None
            self.state.calibrated_proxy = None
        
        return error

    def build_full_res_cache(self):
        """Forces a rebuild of the full-resolution arrays (used immediately before export)."""
        if self.state.hdri_array is not None:
            self.process_hdri(use_proxy=False)
        if self.state.plate_array is not None:
            self.process_plate(use_proxy=False)
        if self.state.cg_lights:
            self.reconstruct_cg_beauty(use_proxy=False)

    @staticmethod
    def calculate_stencil(img_array: np.ndarray, mask_layer) -> np.ndarray:
        """Returns a 2D float32 alpha mask based on the Advanced Keyer Stencil settings."""
        mode = getattr(mask_layer, 'stencil_mode', 'Luminance')
        th = getattr(mask_layer, 'stencil_threshold', 0.5)
        invert = getattr(mask_layer, 'stencil_invert', False)
        
        r, g, b = img_array[..., 0], img_array[..., 1], img_array[..., 2]
        
        if mode == "Luminance":
            key = 0.2126 * r + 0.7152 * g + 0.0722 * b
        elif mode == "Green Key":
            key = g - np.maximum(r, b)
            max_c = np.maximum(np.maximum(r, g), b)
            key = key / np.maximum(max_c, 1e-6)
        elif mode == "Blue Key":
            key = b - np.maximum(r, g)
            max_c = np.maximum(np.maximum(r, g), b)
            key = key / np.maximum(max_c, 1e-6)
        else:
            return np.ones(img_array.shape[:2], dtype=np.float32)
            
        edge0 = max(0.001, th - 0.1)
        edge1 = min(0.999, th + 0.1)
        if edge1 <= edge0: edge1 = edge0 + 1e-4
            
        t = np.clip((key - edge0) / (edge1 - edge0), 0.0, 1.0)
        alpha = t * t * (3.0 - 2.0 * t)
        
        if invert:
            alpha = 1.0 - alpha
            
        return alpha.astype(np.float32)

    def _apply_masks(self, arr: np.ndarray, target_name: str) -> np.ndarray:
        if not self.state.masks_enabled:
            return arr
            
        h, w = arr.shape[:2]
        if target_name == "Plate":
            orig_h, orig_w = self.state.plate_array.shape[:2]
        else:
            orig_h, orig_w = self.state.hdri_array.shape[:2]
            
        scale_x = w / orig_w
        y_idx, x_idx = np.ogrid[:h, :w]
        
        calibrated = arr
        # Ensure calibrated is a new array before in-place mask operations
        if calibrated is arr:
            calibrated = arr.copy()
        elif not calibrated.flags.owndata:
            calibrated = calibrated.copy()
            
        # Reverse order: index 0 (top of UI list) is processed LAST so it renders ON TOP
        for mask_layer in reversed(self.state.masks):
            if not mask_layer.enabled or mask_layer.rect is None:
                continue
            if getattr(mask_layer, 'target', 'HDRI') != target_name:
                continue
                
            has_effect = False
            if mask_layer.mode == "AI Inpaint":
                if getattr(mask_layer, 'inpainted_patch', None) is not None:
                    has_effect = True
            elif mask_layer.mode in ["Solid Fill", "Chroma Replace"]:
                has_effect = True
            elif mask_layer.shape == "Image" and getattr(mask_layer, 'image_path', ''):
                has_effect = True
            else:
                if abs(mask_layer.ev_offset) > 1e-8 or abs(mask_layer.temperature) > 1e-4 or abs(mask_layer.tint) > 1e-4:
                    has_effect = True
                    
            if mask_layer.blur > 1e-4:
                has_effect = True
                
            if not has_effect:
                continue
                
            nx1, ny1, nx2, ny2 = mask_layer.rect
            sx1, sx2 = nx1 * w, nx2 * w
            sy1, sy2 = ny1 * h, ny2 * h
            
            mask = np.zeros((h, w, 1), dtype=np.float32)
            feather = mask_layer.feather * scale_x
            
            if mask_layer.shape in ["Polygon", "Lasso", "Brush"] and getattr(mask_layer, 'points', None):
                try:
                    import cv2
                    
                    strokes = []
                    current_stroke = []
                    prev_x = None
                    for pt in mask_layer.points:
                        if pt is None:
                            if current_stroke: strokes.append(current_stroke)
                            current_stroke = []
                            prev_x = None
                        else:
                            nx, ny = pt
                            x = nx * w
                            if prev_x is not None and getattr(mask_layer, 'target', 'HDRI') == 'HDRI':
                                if x - prev_x > w / 2: x -= w
                                elif prev_x - x > w / 2: x += w
                            current_stroke.append([x, ny * h])
                            prev_x = x
                    if current_stroke: strokes.append(current_stroke)
                    
                    draw_polys = []
                    for stroke in strokes:
                        poly_arr = np.array(stroke, np.int32)
                        if getattr(mask_layer, 'target', 'HDRI') == 'HDRI':
                            poly_arr_left = poly_arr.copy(); poly_arr_left[:, 0] -= w
                            poly_arr_right = poly_arr.copy(); poly_arr_right[:, 0] += w
                            draw_polys.extend([poly_arr_left, poly_arr, poly_arr_right])
                        else:
                            draw_polys.append(poly_arr)
                    
                    poly_mask = np.zeros((h, w), dtype=np.uint8)
                    
                    if mask_layer.shape in ["Polygon", "Lasso"]:
                        cv2.fillPoly(poly_mask, draw_polys, 1)
                        
                        if feather < 1.0:
                            mask[..., 0] = poly_mask.astype(np.float32)
                        else:
                            dist_in = cv2.distanceTransform(poly_mask, cv2.DIST_L2, 5)
                            dist_out = cv2.distanceTransform(1 - poly_mask, cv2.DIST_L2, 5)
                            dist_combined = dist_out - dist_in
                            
                            val = 0.5 - (dist_combined / feather)
                            alpha = np.clip(val, 0.0, 1.0)
                            alpha = alpha * alpha * (3.0 - 2.0 * alpha)
                            mask[..., 0] = alpha
                    else:
                        # Brush: mathematically perfect euclidean capsule stroke
                        cv2.polylines(poly_mask, draw_polys, isClosed=False, color=1, thickness=1, lineType=cv2.LINE_8)
                        dist_out = cv2.distanceTransform(1 - poly_mask, cv2.DIST_L2, 5)
                        
                        radius = (mask_layer.brush_size * scale_x) / 2.0
                        # Base anti-aliasing + user feather
                        effective_feather = max(1.0, feather)
                        
                        dist_combined = dist_out - radius
                        val = 0.5 - (dist_combined / effective_feather)
                        alpha = np.clip(val, 0.0, 1.0)
                        alpha = alpha * alpha * (3.0 - 2.0 * alpha)
                        mask[..., 0] = alpha
                except ImportError:
                    pass
            else:
                is_hdri = getattr(mask_layer, 'target', 'HDRI') == 'HDRI'
                
                if is_hdri and sx1 > sx2:
                    cx = (sx1 + sx2 + w) / 2.0
                    if cx >= w: cx -= w
                    rx = (sx2 + w - sx1) / 2.0
                else:
                    cx = (sx1 + sx2) / 2.0
                    rx = max((sx2 - sx1) / 2.0, 1e-5)
                    
                cy = (sy1 + sy2) / 2.0
                ry = max(abs(sy2 - sy1) / 2.0, 1e-5)
                
                dx = np.abs(x_idx - cx)
                if is_hdri:
                    dx = np.minimum(dx, w - dx)  # Toroidal wrapping
                
                if mask_layer.shape == "Ellipse":
                    dist = np.sqrt((dx / rx)**2 + ((y_idx - cy) / ry)**2)
                    avg_r = (rx + ry) / 2.0
                    dist_px = (dist - 1.0) * avg_r
                else:
                    dy = np.abs(y_idx - cy)
                    dx_box = np.maximum(dx - rx, 0)
                    dy_box = np.maximum(dy - ry, 0)
                    dist_px = np.sqrt(dx_box**2 + dy_box**2) + np.minimum(np.maximum(dx - rx, dy - ry), 0)
                              
                if feather < 1.0:
                    mask[..., 0] = np.where(dist_px <= 0, 1.0, 0.0)
                else:
                    val = 0.5 - (dist_px / feather)
                    alpha = np.clip(val, 0.0, 1.0)
                    alpha = alpha * alpha * (3.0 - 2.0 * alpha)
                    mask[..., 0] = alpha
                
            mask = mask * mask_layer.blend
                
            ox = getattr(mask_layer, 'offset_x', 0.0)
            oy = getattr(mask_layer, 'offset_y', 0.0)
            scale = getattr(mask_layer, 'scale', 1.0)
            rot = getattr(mask_layer, 'rotation', 0.0)
            is_transformed = abs(ox) > 1e-4 or abs(oy) > 1e-4 or abs(scale - 1.0) > 1e-4 or abs(rot) > 1e-4
            
            decal = None
            if mask_layer.mode == "AI Inpaint" and getattr(mask_layer, 'inpainted_patch', None) is not None:
                patch = mask_layer.inpainted_patch
                full_w = int(max(sx1, sx2)) - int(min(sx1, sx2))
                full_h = int(max(sy1, sy2)) - int(min(sy1, sy2))
                
                if full_w > 0 and full_h > 0:
                    import cv2
                    is_spherical = is_hdri and getattr(mask_layer, 'spherical_projection', False)
                    if not is_spherical and (patch.shape[1] != full_w or patch.shape[0] != full_h):
                        patch = cv2.resize(patch, (full_w, full_h), interpolation=cv2.INTER_LINEAR)
                        
                    if getattr(mask_layer, 'inpaint_key_green', False):
                        r, g, b = patch[..., 0], patch[..., 1], patch[..., 2]
                        max_rb = np.maximum(r, b)
                        diff = np.clip(g - max_rb, 0.0, 100.0)
                        key_alpha = np.clip(1.0 - (diff * 4.0), 0.0, 1.0)
                        spill_mask = g > max_rb
                        new_g = np.where(spill_mask, max_rb, g)
                        if patch.ndim == 3 and patch.shape[-1] == 4:
                            patch[..., 1] = new_g
                            patch[..., 3] *= key_alpha
                        else:
                            patch = np.concatenate([patch[..., 0:1], new_g[..., np.newaxis], patch[..., 2:3], key_alpha[..., np.newaxis]], axis=-1)
                    else:
                        if patch.ndim == 3 and patch.shape[-1] == 3:
                            patch = np.concatenate([patch, np.ones((patch.shape[0], patch.shape[1], 1), dtype=np.float32)], axis=-1)
                            
                    decal = np.zeros((h, w, 4), dtype=np.float32)
                    up_px1 = max(0, int(min(sx1, sx2)))
                    up_px2 = min(w, int(max(sx1, sx2)))
                    up_py1 = max(0, int(min(sy1, sy2)))
                    up_py2 = min(h, int(max(sy1, sy2)))
                    target_w = up_px2 - up_px1
                    target_h = up_py2 - up_py1
                    
                    crop_left = max(0, 0 - int(min(sx1, sx2)))
                    crop_top = max(0, 0 - int(min(sy1, sy2)))
                    crop_right = crop_left + target_w
                    crop_bottom = crop_top + target_h
                    
                    if target_w > 0 and target_h > 0:
                        if is_hdri and getattr(mask_layer, 'spherical_projection', False):
                            from hdri_match.core.projection import SphericalProjector
                            if sx1 > sx2:
                                cx = (sx1 + sx2 + w) / 2.0
                                if cx >= w: cx -= w
                            else:
                                cx = (sx1 + sx2) / 2.0
                            cy = (sy1 + sy2) / 2.0
                            patch_proj = SphericalProjector.rect_to_equi_roi(
                                patch, cx, cy, h, w, up_px1, up_px2, up_py1, up_py2
                            )
                            decal[up_py1:up_py2, up_px1:up_px2] = patch_proj
                        else:
                            decal[up_py1:up_py2, up_px1:up_px2] = patch[crop_top:crop_bottom, crop_left:crop_right]

            if is_transformed:
                import cv2
                cx = (sx1 + sx2) / 2.0
                cy = (sy1 + sy2) / 2.0
                M = cv2.getRotationMatrix2D((cx, cy), rot, scale)
                M[0, 2] += ox * scale_x
                M[1, 2] += oy * scale_x
                
                mask = cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_LINEAR)
                if mask.ndim == 2:
                    mask = mask[..., np.newaxis]
                    
                if decal is not None:
                    decal = cv2.warpAffine(decal, M, (w, h), flags=cv2.INTER_LINEAR)
                    
                px1, px2, py1, py2 = 0, w, 0, h
            else:
                pad = int(feather) + int(mask_layer.blur * scale_x) + 2
                is_hdri = getattr(mask_layer, 'target', 'HDRI') == 'HDRI'
                if is_hdri and sx1 > sx2:
                    px1, px2 = 0, w
                else:
                    px1 = max(0, int(min(sx1, sx2)) - pad)
                    px2 = min(w, int(max(sx1, sx2)) + pad)
                    
                py1 = max(0, int(min(sy1, sy2)) - pad)
                py2 = min(h, int(max(sy1, sy2)) + pad)
            
            if px2 <= px1 or py2 <= py1:
                continue
                
            roi_calib = calibrated[py1:py2, px1:px2]
            roi_mask = mask[py1:py2, px1:px2]
            
            if getattr(mask_layer, 'stencil_enable', False):
                stencil = self.calculate_stencil(roi_calib, mask_layer)
                roi_mask = roi_mask * stencil[..., np.newaxis]
                
            roi_graded = roi_calib.copy()

            if decal is not None:
                roi_decal = decal[py1:py2, px1:px2]
                alpha = roi_decal[..., 3:4] * roi_mask
                rgb = roi_decal[..., :3]
                roi_graded = roi_graded * (1.0 - alpha) + rgb * alpha
            elif mask_layer.shape == "Image" and getattr(mask_layer, 'image_path', ''):
                import os, cv2
                if os.path.exists(mask_layer.image_path):
                    img_decal = cv2.imread(mask_layer.image_path, cv2.IMREAD_UNCHANGED)
                    if img_decal is not None:
                        if img_decal.ndim == 3:
                            if img_decal.shape[2] == 4:
                                img_decal = cv2.cvtColor(img_decal, cv2.COLOR_BGRA2RGBA)
                            elif img_decal.shape[2] == 3:
                                img_decal = cv2.cvtColor(img_decal, cv2.COLOR_BGR2RGB)
                                
                        is_hdri = getattr(mask_layer, 'target', 'HDRI') == 'HDRI'
                        if is_hdri and sx1 > sx2:
                            up_px1, up_px2 = 0, w
                        else:
                            up_px1, up_px2 = max(0, int(min(sx1, sx2))), min(w, int(max(sx1, sx2)))
                        up_py1, up_py2 = max(0, int(min(sy1, sy2))), min(h, int(max(sy1, sy2)))
                        target_w = up_px2 - up_px1
                        target_h = up_py2 - up_py1
                        off_x = up_px1 - px1
                        off_y = up_py1 - py1
                        
                        if target_w > 0 and target_h > 0 and off_x >= 0 and off_y >= 0:
                            if is_hdri and getattr(mask_layer, 'spherical_projection', False):
                                from hdri_match.core.projection import SphericalProjector
                                if sx1 > sx2:
                                    cx = (sx1 + sx2 + w) / 2.0
                                    if cx >= w: cx -= w
                                else:
                                    cx = (sx1 + sx2) / 2.0
                                cy = (sy1 + sy2) / 2.0
                                patch_proj = SphericalProjector.rect_to_equi_roi(
                                    img_decal, cx, cy, h, w, up_px1, up_px2, up_py1, up_py2
                                )
                                img_decal_f = patch_proj.astype(np.float32) / 255.0
                            else:
                                img_decal = cv2.resize(img_decal, (target_w, target_h), interpolation=cv2.INTER_AREA)
                                img_decal_f = img_decal.astype(np.float32) / 255.0
                            ph, pw = min(target_h, roi_graded.shape[0] - off_y), min(target_w, roi_graded.shape[1] - off_x)
                            if ph > 0 and pw > 0:
                                p = img_decal_f[:ph, :pw]
                                if p.ndim == 3 and p.shape[-1] == 4:
                                    alpha = p[..., 3:4]
                                    rgb = p[..., :3]
                                    rgb = np.power(np.clip(rgb, 0, 1), 2.2) # sRGB to Linear
                                    current_bg = roi_graded[off_y:off_y+ph, off_x:off_x+pw]
                                    local_mask = roi_mask[off_y:off_y+ph, off_x:off_x+pw]
                                    if local_mask.ndim == 2:
                                        local_mask = local_mask[..., np.newaxis]
                                    combined_alpha = alpha * local_mask
                                    roi_graded[off_y:off_y+ph, off_x:off_x+pw] = current_bg * (1.0 - combined_alpha) + rgb * combined_alpha
                                elif p.ndim == 3 and p.shape[-1] == 3:
                                    rgb = np.power(np.clip(p, 0, 1), 2.2)
                                    current_bg = roi_graded[off_y:off_y+ph, off_x:off_x+pw]
                                    local_mask = roi_mask[off_y:off_y+ph, off_x:off_x+pw]
                                    if local_mask.ndim == 2:
                                        local_mask = local_mask[..., np.newaxis]
                                    roi_graded[off_y:off_y+ph, off_x:off_x+pw] = current_bg * (1.0 - local_mask) + rgb * local_mask
            elif mask_layer.mode == "Solid Fill":
                roi_graded[:] = np.array(mask_layer.fill_color, dtype=np.float32)
            elif mask_layer.mode == "Chroma Replace":
                r, g, b = roi_graded[..., 0], roi_graded[..., 1], roi_graded[..., 2]
                if mask_layer.chroma_hue < 180: # Green
                    key = g - np.maximum(r, b)
                else: # Blue
                    key = b - np.maximum(r, g)
                
                max_c = np.maximum(np.maximum(r, g), b)
                key_norm = key / np.maximum(max_c, 1e-6)
                
                tol = mask_layer.chroma_tolerance
                edge0 = max(0.01, 1.0 - tol)
                edge1 = edge0 + 0.2
                
                t = np.clip((key_norm - edge0) / (edge1 - edge0 + 1e-6), 0.0, 1.0)
                chroma_mask = t * t * (3.0 - 2.0 * t)
                chroma_mask = chroma_mask[..., np.newaxis]
                
                fill_color_arr = np.array(mask_layer.fill_color, dtype=np.float32)
                roi_graded = roi_graded * (1.0 - chroma_mask) + fill_color_arr * chroma_mask
            else:
                if abs(mask_layer.ev_offset) > 1e-8:
                    roi_graded = ExposureAnalyzer.apply_exposure(roi_graded, mask_layer.ev_offset)
                if abs(mask_layer.temperature) > 1e-4 or abs(mask_layer.tint) > 1e-4:
                    roi_graded = WhiteBalanceEstimator.apply_temperature_tint(
                        roi_graded, mask_layer.temperature, mask_layer.tint)
                    
            if mask_layer.blur > 0.5:
                blur_px = mask_layer.blur * scale_x
                if blur_px >= 1.0:
                    ksize = int(blur_px * 2) + 1
                    if ksize % 2 == 0:
                        ksize += 1
                    try:
                        import cv2
                        roi_h, roi_w = roi_graded.shape[:2]
                        if max(roi_h, roi_w) > 500 and ksize > 15:
                            scale = 500.0 / max(roi_h, roi_w)
                            small_ksize = max(int(ksize * scale), 5)
                            if small_ksize % 2 == 0: small_ksize += 1
                            small_img = cv2.resize(roi_graded, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                            blurred = cv2.GaussianBlur(small_img, (small_ksize, small_ksize), blur_px * scale)
                            roi_graded = cv2.resize(blurred, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR)
                        else:
                            roi_graded = cv2.GaussianBlur(roi_graded, (ksize, ksize), blur_px)
                    except ImportError:
                        try:
                            from scipy.ndimage import gaussian_filter
                            roi_graded = gaussian_filter(roi_graded, sigma=(blur_px, blur_px, 0))
                        except ImportError:
                            pass
                
            if mask_layer.blend < 1.0:
                roi_mask = roi_mask * mask_layer.blend
                
            b_mode = getattr(mask_layer, 'blend_mode', 'over')
            if b_mode == 'plus':
                calibrated[py1:py2, px1:px2] = roi_calib + roi_graded * roi_mask
            elif b_mode == 'multiply':
                calibrated[py1:py2, px1:px2] = roi_calib * (roi_graded * roi_mask + (1.0 - roi_mask))
            elif b_mode == 'screen':
                screened = roi_calib + roi_graded - (roi_calib * roi_graded)
                calibrated[py1:py2, px1:px2] = roi_calib * (1.0 - roi_mask) + screened * roi_mask
            else:
                calibrated[py1:py2, px1:px2] = roi_calib * (1.0 - roi_mask) + roi_graded * roi_mask
            
        return calibrated

    def set_proxy_resolution(self, target_shape=None):
        """Re-generates proxy arrays to match the UI's requested working resolution (Reformat)."""
        def _resize(arr):
            if arr is None: return None
            if target_shape == "Native":
                return arr.copy()
            if target_shape is None:
                return self._create_proxy(arr, max_dim=800)
            if arr.shape[:2] == target_shape:
                return arr.copy()
            try:
                import cv2
                return cv2.resize(arr, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)
            except ImportError:
                return self._create_proxy(arr, max_dim=800)

        if self.state.hdri_array is not None:
            self.state.hdri_proxy = _resize(self.state.hdri_array)
        if self.state.plate_array is not None:
            self.state.plate_proxy = _resize(self.state.plate_array)
            
        if self.state.cg_lights:
            for name, arr in self.state.cg_lights.items():
                self.state.cg_light_proxies[name] = _resize(arr)
        if self.state.cg_alpha is not None:
            if self.state.cg_alpha.ndim == 2:
                self.state.cg_alpha_proxy = _resize(self.state.cg_alpha[..., np.newaxis])
            else:
                self.state.cg_alpha_proxy = _resize(self.state.cg_alpha)
        if self.state.cg_beauty is not None:
            self.state.cg_beauty_proxy = _resize(self.state.cg_beauty)

    def load_inputs(self, hdri_path: str, plate_path: str,
                    input_space: str = "Linear", working_space: str = "Linear"):
        self.state.hdri_path = hdri_path
        self.state.plate_path = plate_path

        errors = []
        if hdri_path:
            try:
                hdri_raw = load_exr_to_numpy(hdri_path)
                self.state.hdri_array = self.colorspace_manager.transform_image(
                    hdri_raw, input_space, working_space)
                self.state.hdri_proxy = self._create_proxy(self.state.hdri_array)
                pct = SunDetector.sun_coverage_percent(self.state.hdri_array)
                print(f"[SunDetector] HDRI sun coverage: {pct:.2f}%")
            except Exception as e:
                errors.append(f"HDRI Load Error: {e}")

        if plate_path:
            try:
                plate_raw = load_exr_to_numpy(plate_path)
                ext = os.path.splitext(plate_path)[1].lower()
                # Detect display-referred formats (JPG, PNG, TIFF 8-bit, BMP)
                # These are sRGB gamma-encoded. The loader already normalises to
                # 0-1 but does NOT linearize. We must remove the sRGB gamma so
                # that all EV and illuminant math operates in scene-linear space.
                if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tga', '.tif', '.tiff'):
                    self.state.plate_is_display_referred = True
                    # Approximate sRGB → Linear (gamma 2.2 decode)
                    plate_raw = np.power(np.clip(plate_raw, 0.0, 1.0), 2.2)
                    print(f"[Pipeline] Plate '{os.path.basename(plate_path)}' detected as display-referred ({ext}).")
                    print(f"           Applied sRGB→Linear (gamma 2.2) for physically accurate EV matching.")
                else:
                    self.state.plate_is_display_referred = False
                self.state.plate_array = self.colorspace_manager.transform_image(
                    plate_raw, input_space, working_space)
                self.state.plate_proxy = self._create_proxy(self.state.plate_array)
            except Exception as e:
                errors.append(f"Plate Load Error: {e}")

        if errors:
            raise RuntimeError("\n".join(errors))

    def load_cg_lights(self, exr_path: str, prefixes: tuple = ("light_",), input_colorspace: str = "ACEScg", working_space: str = "Linear"):
        """Loads Arnold light AOVs from an EXR and sets up initial tracking."""
        from hdri_match.io.loader import load_light_aovs_from_exr, load_cg_alpha_from_exr
        lights = load_light_aovs_from_exr(exr_path, prefixes=prefixes,
                                           input_colorspace=input_colorspace)
        if not lights:
            raise ValueError(f"No AOVs matching prefixes {prefixes} found in the EXR.\n"
                             "Expected channels named like: C_Light_key.R/G/B etc.")

        self.state.cg_exr_path = exr_path

        self.state.cg_lights = {}
        self.state.cg_light_proxies = {}
        self.state.cg_light_params = {}

        for name, arr in lights.items():
            arr_transformed = self.colorspace_manager.transform_image(arr, input_colorspace, working_space)
            self.state.cg_lights[name] = arr_transformed
            self.state.cg_light_proxies[name] = self._create_proxy(arr_transformed)
            self.state.cg_light_params[name] = {"ev": 0.0, "temp": 0.0, "tint": 0.0, "enabled": True, "color": [1.0, 1.0, 1.0]}

        # Load CG Beauty base (contains emission, background, global illumination missing from AOVs)
        # Use load_exr_to_numpy (cv2.imread path) — proven reliable.
        # load_beauty_from_exr's pure multi-part reader can silently return
        # wrong data for compressed EXRs, zeroing out the reconstruction.
        try:
            from hdri_match.io.loader import load_exr_to_numpy
            beauty_raw = load_exr_to_numpy(exr_path)
            self.state.cg_beauty = self.colorspace_manager.transform_image(beauty_raw, input_colorspace, working_space)
            self.state.cg_beauty_proxy = self._create_proxy(self.state.cg_beauty)
            
            # Match dimensions if needed
            first_key = list(lights.keys())[0]
            cg_h, cg_w = lights[first_key].shape[:2]
            if self.state.cg_beauty.shape[:2] != (cg_h, cg_w):
                try:
                    import cv2
                    self.state.cg_beauty = cv2.resize(self.state.cg_beauty, (cg_w, cg_h), interpolation=cv2.INTER_AREA)
                    self.state.cg_beauty_proxy = self._create_proxy(self.state.cg_beauty)
                except ImportError:
                    try:
                        from scipy.ndimage import zoom
                        sy = cg_h / self.state.cg_beauty.shape[0]
                        sx = cg_w / self.state.cg_beauty.shape[1]
                        self.state.cg_beauty = zoom(self.state.cg_beauty, (sy, sx, 1), order=1)
                        self.state.cg_beauty_proxy = self._create_proxy(self.state.cg_beauty)
                    except ImportError:
                        import numpy as np
                        y = np.linspace(0, self.state.cg_beauty.shape[0] - 1, cg_h).astype(int)
                        x = np.linspace(0, self.state.cg_beauty.shape[1] - 1, cg_w).astype(int)
                        self.state.cg_beauty = self.state.cg_beauty[y, :][:, x, :]
                        self.state.cg_beauty_proxy = self._create_proxy(self.state.cg_beauty)
        except Exception as e:
            print(f"Warning: could not load CG beauty pass: {e}")
            self.state.cg_beauty = None
            self.state.cg_beauty_proxy = None

        # Load alpha channel (for CG-over-plate compositing)
        alpha = load_cg_alpha_from_exr(exr_path)
        if alpha is not None:
            h, w = alpha.shape[:2]
            # Resize alpha to match CG beauty if dimensions differ
            first_key = list(lights.keys())[0]
            cg_h, cg_w = lights[first_key].shape[:2]
            if h != cg_h or w != cg_w:
                try:
                    import cv2
                    alpha = cv2.resize(alpha, (cg_w, cg_h), interpolation=cv2.INTER_AREA)
                except ImportError:
                    try:
                        from scipy.ndimage import zoom
                        alpha = zoom(alpha, (cg_h / h, cg_w / w), order=1)
                    except ImportError:
                        import numpy as np
                        y = np.linspace(0, h - 1, cg_h).astype(int)
                        x = np.linspace(0, w - 1, cg_w).astype(int)
                        alpha = alpha[y, :][:, x]
        self.state.cg_alpha = alpha
        if alpha is not None:
            self.state.cg_alpha_proxy = self._create_proxy(alpha.reshape(alpha.shape[0], alpha.shape[1], 1))
        else:
            self.state.cg_alpha_proxy = None

        print(f"[Pipeline] CG Lights loaded: {list(self.state.cg_lights.keys())}")
        if self.state.cg_beauty is not None:
            b = self.state.cg_beauty
            print(f"[Pipeline] Beauty loaded: shape={b.shape}  min={b.min():.4f}  max={b.max():.4f}")
        else:
            print("[Pipeline] WARNING: Beauty pass NOT loaded (will use sum of light AOVs as base)")
        if self.state.cg_alpha is not None:
            a = self.state.cg_alpha
            print(f"[Pipeline] Alpha loaded: shape={a.shape}  min={a.min():.4f}  max={a.max():.4f}")
        else:
            print("[Pipeline] Alpha NOT found in EXR (will use additive compositing)")

        self.reconstruct_cg_beauty(use_proxy=True)
        self.reconstruct_cg_beauty(use_proxy=False)
        r = self.state.cg_reconstructed
        print(f"[Pipeline] cg_reconstructed: shape={r.shape if r is not None else 'None'}  "
              f"{'min='+str(round(r.min(),4))+' max='+str(round(r.max(),4)) if r is not None else 'EMPTY'}")

    def reconstruct_cg_beauty(self, use_proxy: bool = False) -> np.ndarray:
        """Reconstruct the CG render by summing all graded light AOVs."""
        if not self.state.cg_lights:
            return None

        source_dict = self.state.cg_light_proxies if use_proxy else self.state.cg_lights
        reconstructed = None

        any_solo = any(p.get("solo", False) for p in self.state.cg_light_params.values())

        for name, arr in source_dict.items():
            params = self.state.cg_light_params[name]
            
            if any_solo:
                if not params.get("solo", False):
                    continue
            else:
                if not params.get("enabled", True):
                    continue

            exposed = ExposureAnalyzer.apply_exposure(arr, params["ev"])
            adjusted = WhiteBalanceEstimator.apply_temperature_tint(
                exposed, params["temp"], params["tint"])
                
            color_mult = np.array(params.get("color", [1.0, 1.0, 1.0]), dtype=np.float32)
            if not np.allclose(color_mult, 1.0):
                adjusted = adjusted * color_mult

            if reconstructed is None:
                reconstructed = adjusted.copy()
            else:
                reconstructed += adjusted

        if reconstructed is None:
            reconstructed = np.zeros_like(source_dict[list(source_dict.keys())[0]])

        np.clip(reconstructed, 0.0, None, out=reconstructed)

        if use_proxy:
            self.state.cg_reconstructed_proxy = reconstructed
        else:
            self.state.cg_reconstructed = reconstructed
            self.state.cg_reconstructed_proxy = self._create_proxy(reconstructed)
        return reconstructed

    def _build_plate_reference(self, plate: np.ndarray) -> np.ndarray:
        """Apply plate EV offset and saturation to produce the calibration
        reference.  All math is scene-linear.

        This is the same grading logic as ``process_plate`` but operates on an
        arbitrary array (e.g. a cropped ROI) so that ``compute_calibration``
        can use a consistent, graded plate for EV, black-offset, and
        illuminant estimation.
        """
        if not self.state.plate_adjustments_enabled:
            return plate

        result = plate

        # --- Exposure Offset (EV stops) ---
        ev = self.state.plate_ev_offset
        if abs(ev) > 1e-8:
            result = result * (2.0 ** ev)

        # --- Saturation ---
        sat = self.state.plate_saturation
        if abs(sat - 1.0) > 1e-6:
            luma = (0.2126 * result[..., 0]
                    + 0.7152 * result[..., 1]
                    + 0.0722 * result[..., 2])
            luma_3d = luma[..., np.newaxis]
            result = luma_3d + sat * (result - luma_3d)

        # --- Temperature / Tint ---
        if abs(self.state.plate_temperature) > 1e-4 or abs(self.state.plate_tint) > 1e-4:
            result = WhiteBalanceEstimator.apply_temperature_tint(
                result, self.state.plate_temperature, self.state.plate_tint)

        return result

    def compute_calibration(self, use_chrome_ball: bool = False,
                             use_grey_ball: bool = False,
                             use_macbeth_chart: bool = False,
                             protect_sun: bool = True):
        if self.state.hdri_array is None or self.state.plate_array is None:
            raise ValueError("HDRI and Plate must be loaded before calibration.")

        # --- Build the graded plate reference ---
        # Apply the artist's plate EV offset and saturation so the HDRI is
        # calibrated to match the *graded* plate appearance, not the raw data.
        plate_ref = self._build_plate_reference(self.state.plate_array)

        plate_has_adjustments = self.state.plate_adjustments_enabled and (
                                 abs(self.state.plate_ev_offset) > 1e-8
                                 or abs(self.state.plate_saturation - 1.0) > 1e-6
                                 or abs(self.state.plate_temperature) > 1e-4
                                 or abs(self.state.plate_tint) > 1e-4)
        if plate_has_adjustments:
            print(f"[Calibration] Using graded plate reference "
                  f"(EV {self.state.plate_ev_offset:+.2f}, "
                  f"Sat {self.state.plate_saturation:.2f}, "
                  f"Temp {self.state.plate_temperature:+.2f}, "
                  f"Tint {self.state.plate_tint:+.2f})")

        # --- Build sun mask for HDRI ---
        if protect_sun:
            hdri_mask = SunDetector.build_sun_mask(self.state.hdri_array)
        else:
            hdri_mask = np.ones(self.state.hdri_array.shape[:2], dtype=bool)

        # --- Determine plate sampling region ---
        # If a mask rectangle was drawn on the plate, use that ROI for BOTH
        # EV offset and illuminant estimation. Otherwise, use the full plate.
        plate_roi = self.state.plate_mask_rect  # (x1, y1, x2, y2) or None

        # --- Exposure ---
        if use_chrome_ball and self.state.chrome_ball_array is not None:
            self.state.ev_offset = ExposureAnalyzer.compute_ev_offset_chrome_ball(
                self.state.hdri_array, self.state.chrome_ball_array)
        elif self.state.plate_array is not None:
            # Determine HDRI calculation region
            if self.state.sky_mode == "custom_rect" and self.state.mask_rect is not None:
                nx1, ny1, nx2, ny2 = self.state.mask_rect
                h, w = self.state.hdri_array.shape[:2]
                hx1, hx2 = int(nx1 * w), int(nx2 * w)
                hy1, hy2 = int(ny1 * h), int(ny2 * h)
                if hx1 > hx2:
                    hdri_calc_arr = np.concatenate([
                        self.state.hdri_array[hy1:hy2, hx1:w, :],
                        self.state.hdri_array[hy1:hy2, 0:hx2, :]
                    ], axis=1)
                    if protect_sun:
                        hdri_mask_calc = np.concatenate([
                            hdri_mask[hy1:hy2, hx1:w],
                            hdri_mask[hy1:hy2, 0:hx2]
                        ], axis=1)
                    else:
                        hdri_mask_calc = np.ones((hy2-hy1, (w-hx1)+hx2), dtype=bool)
                else:
                    hdri_calc_arr = self.state.hdri_array[hy1:hy2, hx1:hx2, :]
                    if protect_sun:
                        hdri_mask_calc = hdri_mask[hy1:hy2, hx1:hx2]
                    else:
                        hdri_mask_calc = np.ones((hy2-hy1, hx2-hx1), dtype=bool)
            elif self.state.sky_mode == "top_40":
                h, w = self.state.hdri_array.shape[:2]
                hdri_calc_arr = self.state.hdri_array[:int(h * 0.4), :, :]
                if protect_sun:
                    hdri_mask_calc = hdri_mask[:int(h * 0.4), :]
                else:
                    hdri_mask_calc = np.ones((int(h * 0.4), w), dtype=bool)
            else:
                hdri_calc_arr = self.state.hdri_array
                if protect_sun:
                    hdri_mask_calc = hdri_mask
                else:
                    hdri_mask_calc = np.ones(hdri_calc_arr.shape[:2], dtype=bool)

            hdri_val = SunDetector.masked_percentile(hdri_calc_arr, hdri_mask_calc, 50.0)

            # Determine Plate calculation region
            if plate_roi is not None:
                nx1, ny1, nx2, ny2 = plate_roi
                ph, pw = plate_ref.shape[:2]
                x1, x2 = int(nx1 * pw), int(nx2 * pw)
                y1, y2 = int(ny1 * ph), int(ny2 * ph)
                plate_calc_arr = plate_ref[y1:y2, x1:x2, :]
            elif self.state.sky_mode == "top_40":
                ph, pw = plate_ref.shape[:2]
                plate_calc_arr = plate_ref[:int(ph * 0.4), :, :]
            else:
                plate_calc_arr = plate_ref

            plate_mask_calc = np.ones(plate_calc_arr.shape[:2], dtype=bool)
            plate_val = SunDetector.masked_percentile(plate_calc_arr, plate_mask_calc, 50.0)

            import math
            if hdri_val > 0 and plate_val > 0:
                scale_factor = plate_val / hdri_val
                self.state.ev_offset = math.log2(scale_factor)
            else:
                self.state.ev_offset = 0.0
        elif use_macbeth_chart and self.state.macbeth_chart_array is not None:
            # Fallback: Use the Macbeth chart for exposure matching
            self.state.ev_offset = ExposureAnalyzer.compute_ev_offset_percentile(
                self.state.hdri_array, self.state.macbeth_chart_array, percentile=50.0)

        if self.state.apply_exposure_match:
            # --- Black Offset (Shadow Lift) ---
            # Optional artistic tone match. Keep this off for physically
            # calibrated HDRI export because it changes absolute light energy.
            hdri_exposed = ExposureAnalyzer.apply_exposure(
                self.state.hdri_array, self.state.ev_offset)
            hdri_luma = ExposureAnalyzer.get_luminance(hdri_exposed)
            plate_luma = ExposureAnalyzer.get_luminance(plate_ref)

            hdri_low = max(float(np.percentile(hdri_luma, 2.0)), 0.0)
            plate_low = max(float(np.percentile(plate_luma, 2.0)), 0.0)
            self.state.black_offset = plate_low - hdri_low

            if abs(self.state.black_offset) > 0.5:
                print(f"[BlackOffset] Clamping extreme value {self.state.black_offset:.4f} to 0.0")
                self.state.black_offset = 0.0
        else:
            self.state.ev_offset = 0.0
            self.state.black_offset = 0.0

        # --- White Balance ---
        # When Sky Priority is ON, estimate illuminant from the upper 40% of BOTH
        # images. For the equirectangular HDRI this is the sky hemisphere (pure
        # illuminant). For the plate (ground-level photo) the top 40% includes
        # the sky + distant horizon — still the best proxy for the sky color,
        # and better than full-frame which includes foreground ground reflections.
        # When OFF, use the full frame for both (standard gray world).
        # Region selection strategy:
        # - "custom_rect": use user-drawn rectangle on HDRI;
        #   plate uses top 40% (sky portion of ground-level photo).
        # - "top_40": use the upper 40% (equirectangular sky hemisphere) for BOTH.
        # - "off": full frame for both.
        if self.state.sky_mode == "custom_rect" and self.state.mask_rect is not None:
            hdri_roi = self.state.mask_rect
            plate_sky_only = False
            hdri_sky_only = False
        else:
            hdri_roi = None
            plate_sky_only = (self.state.sky_mode == "top_40")
            hdri_sky_only = (self.state.sky_mode == "top_40")

        if use_grey_ball and self.state.grey_ball_array is not None:
            self.state.plate_illuminant = WhiteBalanceEstimator.estimate_illuminant_from_grey_ball(
                self.state.grey_ball_array)
        elif self.state.plate_array is not None:
            # Convert normalized plate ROI to absolute coords
            plate_roi_abs = None
            if plate_roi is not None:
                ph, pw = plate_ref.shape[:2]
                plate_roi_abs = (int(plate_roi[0] * pw), int(plate_roi[1] * ph),
                                 int(plate_roi[2] * pw), int(plate_roi[3] * ph))
            if self.state.ai_awb_enable:
                self.state.plate_illuminant = WhiteBalanceEstimator.estimate_illuminant_ai(
                    plate_ref, sky_only=plate_sky_only, custom_roi=plate_roi_abs)
            else:
                self.state.plate_illuminant = WhiteBalanceEstimator.estimate_illuminant_gray_world(
                    plate_ref, sky_only=plate_sky_only, custom_roi=plate_roi_abs)
        elif use_macbeth_chart and self.state.macbeth_chart_array is not None:
            # Fallback: A full Macbeth chart perfectly balances to neutral gray on average
            self.state.plate_illuminant = WhiteBalanceEstimator.estimate_illuminant_from_grey_ball(
                self.state.macbeth_chart_array)

        # HDRI illuminant — uses custom_roi when in rectangle mode.
        # When protect_sun is ON, we zero out sun/specular pixels.
        if protect_sun:
            hdri_for_illum = self.state.hdri_array.copy()
            hdri_for_illum[~hdri_mask] = 0.0
        else:
            hdri_for_illum = self.state.hdri_array
            
        hdri_roi_abs = None
        if hdri_roi is not None:
            hh, hw = hdri_for_illum.shape[:2]
            hdri_roi_abs = (int(hdri_roi[0] * hw), int(hdri_roi[1] * hh),
                            int(hdri_roi[2] * hw), int(hdri_roi[3] * hh))
            
        self.state.hdri_illuminant = WhiteBalanceEstimator.estimate_illuminant_gray_world(
            hdri_for_illum, sky_only=hdri_sky_only, custom_roi=hdri_roi_abs)

    def process_plate(self, use_proxy: bool = False) -> np.ndarray:
        """Apply plate-specific EV offset and saturation adjustments.

        These are independent artistic controls that do NOT affect HDRI
        calibration or CG light matching. All math is scene-linear.
        """
        arr = self.state.plate_proxy if use_proxy else self.state.plate_array
        if arr is None:
            if use_proxy:
                self.state.plate_graded_proxy = None
            else:
                self.state.plate_graded = None
                self.state.plate_graded_proxy = None
            return None

        has_active_plate_masks = self.state.masks_enabled and any(m.enabled and getattr(m, 'target', 'HDRI') == 'Plate' for m in self.state.masks)
        if not self.state.plate_adjustments_enabled and not has_active_plate_masks:
            if use_proxy:
                self.state.plate_graded_proxy = arr
            else:
                self.state.plate_graded = arr
                self.state.plate_graded_proxy = self._create_proxy(arr)
            return arr

        result = arr

        if self.state.plate_adjustments_enabled:
            # --- Exposure Offset (EV stops) ---
            ev = self.state.plate_ev_offset
            if abs(ev) > 1e-8:
                result = result * (2.0 ** ev)

            # --- Saturation ---
            sat = self.state.plate_saturation
            if abs(sat - 1.0) > 1e-6:
                # Rec.709 luminance weights (same as compositing pipeline)
                luma = (0.2126 * result[..., 0]
                        + 0.7152 * result[..., 1]
                        + 0.0722 * result[..., 2])
                luma_3d = luma[..., np.newaxis]
                # Linear interpolation: luma + sat * (color - luma)
                result = luma_3d + sat * (result - luma_3d)

            # --- Temperature / Tint ---
            if abs(self.state.plate_temperature) > 1e-4 or abs(self.state.plate_tint) > 1e-4:
                result = WhiteBalanceEstimator.apply_temperature_tint(
                    result, self.state.plate_temperature, self.state.plate_tint)

        # Apply Masks
        result = self._apply_masks(result, "Plate")

        if use_proxy:
            self.state.plate_graded_proxy = result
            return result
        else:
            self.state.plate_graded = result
            self.state.plate_graded_proxy = self._create_proxy(result)
            return result

    def process_hdri(self, use_proxy: bool = False) -> np.ndarray:
        arr = self.state.hdri_proxy if use_proxy else self.state.hdri_array
        if arr is None:
            if use_proxy:
                self.state.calibrated_proxy = None
            else:
                self.state.calibrated_hdri = None
                self.state.calibrated_proxy = None
            return None

        # Step 0: Sun Relighting (move the sun BEFORE any grading)
        if self.state.sun_relight_enabled:
            from hdri_match.analysis.sun_relighter import SunRelighter
            arr = SunRelighter.relight(
                arr,
                source_u=self.state.sun_source_u,
                source_v=self.state.sun_source_v,
                target_u=self.state.sun_target_u,
                target_v=self.state.sun_target_v,
                radius_norm=self.state.sun_radius,
                feather_norm=self.state.sun_feather,
            )

        bake_ev = self.state.apply_exposure_match
        if bake_ev and abs(self.state.ev_offset) > 1e-8:
            exposed = ExposureAnalyzer.apply_exposure(arr, self.state.ev_offset)
        else:
            exposed = arr

        if bake_ev:
            bo = self.state.black_offset
            if abs(bo) > 1e-8:
                exposed = exposed + bo

        # Step 3: Match white balance to plate illuminant
        if self.state.macbeth_matrix is not None:
            # Apply Macbeth 3x3 color matrix instead of simple gray world balance
            # Ensure safe clipping for linear data before matrix multiplication
            exposed_safe = np.clip(exposed, 0.0, None)
            calibrated = np.dot(exposed_safe, self.state.macbeth_matrix).astype(np.float32)
        elif self.state.hdri_illuminant is not None and self.state.plate_illuminant is not None:
            calibrated = WhiteBalanceEstimator.match_illuminant(
                exposed, self.state.hdri_illuminant, self.state.plate_illuminant)
        else:
            calibrated = exposed

        # Step 4: Fine-tune temperature / tint
        if self.state.temperature != 0.0 or self.state.tint != 0.0:
            calibrated = WhiteBalanceEstimator.apply_temperature_tint(
                calibrated, self.state.temperature, self.state.tint)
        # Step 5: Independent Mask Grading (Layered on top, back to front)
        calibrated = self._apply_masks(calibrated, "HDRI")
            
        # Step 6: Horizon / Hemisphere Separation
        if self.state.horizon_enable:
            h, w = arr.shape[:2]
            horizon_y = (1.0 - self.state.horizon_height) * h
            feather_px = max(1.0, self.state.horizon_feather * h)
            
            y_idx = np.arange(h)
            dist_to_horizon = y_idx - horizon_y
            
            alpha = (dist_to_horizon / feather_px) + 0.5
            alpha = np.clip(alpha, 0.0, 1.0)
            alpha = alpha * alpha * (3.0 - 2.0 * alpha)
            
            ground_mask = alpha.reshape(h, 1, 1).astype(np.float32)
            sky_mask = 1.0 - ground_mask
            
            # Grade Sky
            sky_graded = calibrated.copy()
            if abs(self.state.sky_ev_offset) > 1e-8:
                sky_graded = ExposureAnalyzer.apply_exposure(sky_graded, self.state.sky_ev_offset)
            if abs(self.state.sky_temperature) > 1e-4 or abs(self.state.sky_tint) > 1e-4:
                sky_graded = WhiteBalanceEstimator.apply_temperature_tint(
                    sky_graded, self.state.sky_temperature, self.state.sky_tint)
            if self.state.sky_desat > 0.0:
                luma = np.sum(sky_graded * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1, keepdims=True)
                sky_graded = sky_graded * (1.0 - self.state.sky_desat) + luma * self.state.sky_desat
            
            # Grade Ground
            ground_graded = calibrated.copy()
            if abs(self.state.ground_ev_offset) > 1e-8:
                ground_graded = ExposureAnalyzer.apply_exposure(ground_graded, self.state.ground_ev_offset)
            if abs(self.state.ground_temperature) > 1e-4 or abs(self.state.ground_tint) > 1e-4:
                ground_graded = WhiteBalanceEstimator.apply_temperature_tint(
                    ground_graded, self.state.ground_temperature, self.state.ground_tint)
            if self.state.ground_desat > 0.0:
                luma = np.sum(ground_graded * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1, keepdims=True)
                ground_graded = ground_graded * (1.0 - self.state.ground_desat) + luma * self.state.ground_desat
                
            calibrated = (sky_graded * sky_mask) + (ground_graded * ground_mask)

        # Step 7: Highlight Compression (Soft-Clip)
        if self.state.softclip_enable:
            # Calculate threshold (t) and rolloff limit (r) in scene-linear values
            # Mid-grey is assumed 0.18
            t = 0.18 * (2.0 ** self.state.softclip_threshold)
            r = 0.18 * (2.0 ** self.state.softclip_rolloff)
            
            # Extract luminance
            luma = np.sum(calibrated * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1, keepdims=True)
            luma_safe = np.maximum(luma, 1e-8)
            
            # Mask for values above the threshold
            mask = luma > t
            
            # Compress luminance using exponential decay toward asymptote (t + r)
            # Derivative is 1 at x=t for a smooth transition.
            compressed_luma = np.where(mask, t + r * (1.0 - np.exp(-(luma - t) / max(r, 1e-8))), luma)
            
            # Apply the compression ratio to the RGB channels to preserve hue exactly
            ratio = compressed_luma / luma_safe
            calibrated = np.where(mask, calibrated * ratio, calibrated)

        # Step 8: Y-Axis Rotation (Yaw)
        if self.state.hdri_yaw != 0.0:
            h, w = calibrated.shape[:2]
            shift = int(w * (self.state.hdri_yaw / 360.0))
            if shift != 0:
                calibrated = np.roll(calibrated, shift, axis=1)

        if use_proxy:
            self.state.calibrated_proxy = calibrated
            return calibrated
        else:
            self.state.calibrated_hdri = calibrated
            self.state.calibrated_proxy = self._create_proxy(calibrated)
            return calibrated

    def save_project(self, filepath: str, view_mode: str = None, proxy_resolution: str = None, split_ratio: float = None):
        import json
        import dataclasses
        
        data = {
            "view_mode": view_mode,
            "proxy_resolution": proxy_resolution,
            "split_ratio": split_ratio,
            "hdri_path": self.state.hdri_path,
            "plate_path": self.state.plate_path,
            "cg_exr_path": self.state.cg_exr_path,
            
            "hdri_yaw": self.state.hdri_yaw,
            "ev_offset": self.state.ev_offset,
            "black_offset": self.state.black_offset,
            "apply_exposure_match": self.state.apply_exposure_match,
            "temperature": self.state.temperature,
            "tint": self.state.tint,
            "sky_priority": self.state.sky_priority,
            "sky_mode": self.state.sky_mode,
            "ai_awb_enable": self.state.ai_awb_enable,
            
            "masks_enabled": self.state.masks_enabled,
            "masks": [{**dataclasses.asdict(m), 'inpainted_patch': None} for m in self.state.masks],
            
            "horizon_enable": self.state.horizon_enable,
            "horizon_height": self.state.horizon_height,
            "horizon_feather": self.state.horizon_feather,
            "sky_ev_offset": self.state.sky_ev_offset,
            "sky_temperature": self.state.sky_temperature,
            "sky_tint": self.state.sky_tint,
            "sky_desat": self.state.sky_desat,
            "ground_ev_offset": self.state.ground_ev_offset,
            "ground_temperature": self.state.ground_temperature,
            "ground_tint": self.state.ground_tint,
            "ground_desat": self.state.ground_desat,
            
            "softclip_enable": self.state.softclip_enable,
            "softclip_threshold": self.state.softclip_threshold,
            "softclip_rolloff": self.state.softclip_rolloff,
            
            "plate_adjustments_enabled": self.state.plate_adjustments_enabled,
            "plate_ev_offset": self.state.plate_ev_offset,
            "plate_saturation": self.state.plate_saturation,
            "plate_temperature": self.state.plate_temperature,
            "plate_tint": self.state.plate_tint,
            
            "protect_sun": getattr(self.state, "protect_sun", True),
            
            "sun_relight_enabled": self.state.sun_relight_enabled,
            "sun_source_u": self.state.sun_source_u,
            "sun_source_v": self.state.sun_source_v,
            "sun_target_u": self.state.sun_target_u,
            "sun_target_v": self.state.sun_target_v,
            "sun_radius": self.state.sun_radius,
            "sun_feather": self.state.sun_feather,
            
            "cg_light_params": self.state.cg_light_params,
            "cg_aov_prefixes": getattr(self.state, "cg_aov_prefixes", "C_Light_, light_, key, fill, rim, bounce, warm, cool")
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)

    def load_project(self, filepath: str):
        import json
        from hdri_match.core.data_models import MaskLayer
        
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        # We don't restore paths here automatically because load_inputs does that.
        # But we do want to return them so UI can reload the images.
        
        self.state.hdri_yaw = data.get("hdri_yaw", 0.0)
        self.state.ev_offset = data.get("ev_offset", 0.0)
        self.state.black_offset = data.get("black_offset", 0.0)
        self.state.apply_exposure_match = data.get("apply_exposure_match", False)
        self.state.temperature = data.get("temperature", 0.0)
        self.state.tint = data.get("tint", 0.0)
        self.state.sky_priority = data.get("sky_priority", True)
        self.state.sky_mode = data.get("sky_mode", "top_40")
        self.state.ai_awb_enable = data.get("ai_awb_enable", True)
        
        self.state.masks_enabled = data.get("masks_enabled", True)
        self.state.masks = []
        for m_data in data.get("masks", []):
            mask = MaskLayer()
            for k, v in m_data.items():
                if hasattr(mask, k):
                    # Handle tuple conversions for fill_color, rect, points, etc if needed
                    if k == "fill_color" and isinstance(v, list):
                        v = tuple(v)
                    elif k == "rect" and isinstance(v, list):
                        v = tuple(v)
                    elif k == "points" and isinstance(v, list):
                        v = [tuple(p) for p in v]
                    setattr(mask, k, v)
            self.state.masks.append(mask)
            
        self.state.horizon_enable = data.get("horizon_enable", False)
        self.state.horizon_height = data.get("horizon_height", 0.5)
        self.state.horizon_feather = data.get("horizon_feather", 0.1)
        self.state.sky_ev_offset = data.get("sky_ev_offset", 0.0)
        self.state.sky_temperature = data.get("sky_temperature", 0.0)
        self.state.sky_tint = data.get("sky_tint", 0.0)
        self.state.sky_desat = data.get("sky_desat", 0.0)
        self.state.ground_ev_offset = data.get("ground_ev_offset", 0.0)
        self.state.ground_temperature = data.get("ground_temperature", 0.0)
        self.state.ground_tint = data.get("ground_tint", 0.0)
        self.state.ground_desat = data.get("ground_desat", 0.0)
        
        self.state.softclip_enable = data.get("softclip_enable", False)
        self.state.softclip_threshold = data.get("softclip_threshold", 5.0)
        self.state.softclip_rolloff = data.get("softclip_rolloff", 2.0)
        
        self.state.plate_adjustments_enabled = data.get("plate_adjustments_enabled", False)
        self.state.plate_ev_offset = data.get("plate_ev_offset", 0.0)
        self.state.plate_saturation = data.get("plate_saturation", 1.0)
        self.state.plate_temperature = data.get("plate_temperature", 0.0)
        self.state.plate_tint = data.get("plate_tint", 0.0)
        
        self.state.protect_sun = data.get("protect_sun", True)
        
        self.state.sun_relight_enabled = data.get("sun_relight_enabled", False)
        self.state.sun_source_u = data.get("sun_source_u", 0.5)
        self.state.sun_source_v = data.get("sun_source_v", 0.25)
        self.state.sun_target_u = data.get("sun_target_u", 0.5)
        self.state.sun_target_v = data.get("sun_target_v", 0.25)
        self.state.sun_radius = data.get("sun_radius", 0.03)
        self.state.sun_feather = data.get("sun_feather", 0.015)
        
        if "cg_light_params" in data and data["cg_light_params"]:
            self.state.cg_light_params = data["cg_light_params"]
            
        if "cg_aov_prefixes" in data:
            self.state.cg_aov_prefixes = data["cg_aov_prefixes"]
            
        return data.get("hdri_path"), data.get("plate_path"), data.get("cg_exr_path"), data.get("view_mode"), data.get("proxy_resolution"), data.get("split_ratio")
