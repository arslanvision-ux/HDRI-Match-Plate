import sys
import os
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.core.pipeline import CalibrationPipeline
import numpy as np

# Mock main window logic
p = CalibrationPipeline()

hdri_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/hdri/hdri.hdr'
plate_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/plate/DSC07548.ARW'
cg_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'

print("Loading inputs...")
try:
    p.load_inputs(hdri_path, plate_path, input_space="Linear", working_space="Linear")
    print(f"Plate loaded. Shape: {p.state.plate_array.shape}")
except Exception as e:
    print("Failed to load plate:", e)

print("Loading CG lights...")
try:
    p.load_cg_lights(cg_path, prefixes=("light", "C_Light"), input_colorspace="Linear", working_space="Linear")
    print(f"CG Reconstructed shape: {p.state.cg_reconstructed.shape}, max: {p.state.cg_reconstructed.max()}")
    print(f"CG Alpha shape: {p.state.cg_alpha.shape}, max: {p.state.cg_alpha.max()}")
except Exception as e:
    print("Failed to load CG:", e)

# Test viewer blend logic
print("Testing viewer blend logic...")
try:
    cg_arr = p.state.cg_reconstructed
    plate_arr = p.state.plate_array
    alpha_arr = p.state.cg_alpha

    # Simulate _resize_to_match
    target_shape = plate_arr.shape[:2]
    import cv2
    cg_arr = cv2.resize(cg_arr, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)
    alpha_arr = cv2.resize(alpha_arr, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)

    alpha_2d = np.squeeze(alpha_arr)
    if alpha_2d.ndim != 2:
        alpha_2d = alpha_2d[..., 0]
    alpha_2d = np.clip(alpha_2d, 0.0, 1.0)
    alpha_3d = alpha_2d[:, :, np.newaxis]

    composite = cg_arr[..., :3] + plate_arr[..., :3] * (1.0 - alpha_3d)
    print(f"Composite shape: {composite.shape}, max: {composite.max()}")
except Exception as e:
    print("Failed to blend:", e)
