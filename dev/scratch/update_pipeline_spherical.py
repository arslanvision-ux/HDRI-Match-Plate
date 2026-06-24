import re

with open(r'e:\PROJECTS\HDRI_Match_Plate\hdri_match\core\pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Insert projection in run_ai_generation
target_1 = """                        roi_mask.fill(1.0)
            
        backend = getattr(mask_layer, 'inpaint_backend', "ComfyUI (Local)")"""

replacement_1 = """                        roi_mask.fill(1.0)
            
        if is_hdri and getattr(mask_layer, 'spherical_projection', False):
            from hdri_match.core.projection import SphericalProjector
            cx, cy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
            pw, ph = px2 - px1, py2 - py1
            roi_img = SphericalProjector.equi_to_rect(arr, cx, cy, pw, ph)
            full_mask = np.zeros((h, w), dtype=np.float32)
            full_mask[py1:py2, px1:px2] = roi_mask
            roi_mask = SphericalProjector.equi_to_rect(full_mask, cx, cy, pw, ph)
            if roi_mask.ndim == 3:
                roi_mask = roi_mask[..., 0]
            
        backend = getattr(mask_layer, 'inpaint_backend', "ComfyUI (Local)")"""

if target_1 in content:
    content = content.replace(target_1, replacement_1)
else:
    print("Target 1 not found!")

# 2. Insert projection in _apply_masks AI Inpaint
target_2 = """                    if target_w > 0 and target_h > 0:
                        decal[up_py1:up_py2, up_px1:up_px2] = patch[crop_top:crop_bottom, crop_left:crop_right]"""

replacement_2 = """                    if target_w > 0 and target_h > 0:
                        if is_hdri and getattr(mask_layer, 'spherical_projection', False):
                            from hdri_match.core.projection import SphericalProjector
                            cx, cy = (sx1 + sx2) / 2.0, (sy1 + sy2) / 2.0
                            fov_h = (patch.shape[1] / w) * 2 * np.pi
                            patch_proj = SphericalProjector.rect_to_equi_roi(
                                patch, cx, cy, fov_h, h, w, up_px1, up_px2, up_py1, up_py2
                            )
                            decal[up_py1:up_py2, up_px1:up_px2] = patch_proj
                        else:
                            decal[up_py1:up_py2, up_px1:up_px2] = patch[crop_top:crop_bottom, crop_left:crop_right]"""

if target_2 in content:
    content = content.replace(target_2, replacement_2)
else:
    print("Target 2 not found!")

# 3. Insert projection in _apply_masks Image mode
target_3 = """                        if target_w > 0 and target_h > 0 and off_x >= 0 and off_y >= 0:
                            img_decal = cv2.resize(img_decal, (target_w, target_h), interpolation=cv2.INTER_AREA)
                            img_decal_f = img_decal.astype(np.float32) / 255.0"""

replacement_3 = """                        if target_w > 0 and target_h > 0 and off_x >= 0 and off_y >= 0:
                            if is_hdri and getattr(mask_layer, 'spherical_projection', False):
                                from hdri_match.core.projection import SphericalProjector
                                cx, cy = (sx1 + sx2) / 2.0, (sy1 + sy2) / 2.0
                                fov_h = (img_decal.shape[1] / w) * 2 * np.pi
                                patch_proj = SphericalProjector.rect_to_equi_roi(
                                    img_decal, cx, cy, fov_h, h, w, up_px1, up_px2, up_py1, up_py2
                                )
                                img_decal_f = patch_proj.astype(np.float32) / 255.0
                            else:
                                img_decal = cv2.resize(img_decal, (target_w, target_h), interpolation=cv2.INTER_AREA)
                                img_decal_f = img_decal.astype(np.float32) / 255.0"""

if target_3 in content:
    content = content.replace(target_3, replacement_3)
else:
    print("Target 3 not found!")


with open(r'e:\PROJECTS\HDRI_Match_Plate\hdri_match\core\pipeline.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated pipeline.py successfully.")
