import sys
import os
import cv2
import numpy as np

sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.core.pipeline import CalibrationPipeline
from hdri_match.ui.viewer import ViewerWidget

def hdr_to_uint8(arr):
    img = np.array(arr[..., :3], dtype=np.float32, copy=True)
    np.nan_to_num(img, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    luma = (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2])
    p98 = float(np.percentile(luma, 98))
    target_level = 0.9
    if p98 > 1e-6:
        img = img * (target_level / p98)
    np.clip(img, 0.0, 1.0, out=img)
    np.power(img, 1.0 / 2.2, out=img)
    return (img * 255.0).astype(np.uint8)[..., ::-1] # BGR for cv2

p = CalibrationPipeline()

plate_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/plate/DSC07548.ARW'
cg_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'

try:
    p.load_inputs(None, plate_path, input_space="sRGB", working_space="Linear")
    print("Plate loaded:", p.state.plate_array.shape)
except Exception as e:
    print("Failed to load plate:", e)
    # create dummy plate
    p.state.plate_array = np.zeros((6336, 9504, 3), dtype=np.float32)

p.load_cg_lights(cg_path, prefixes=("light", "C_Light"), input_colorspace="Linear", working_space="Linear")
print("CG Lights loaded.")

cg_arr = p.state.cg_reconstructed
alpha_arr = p.state.cg_alpha

print(f"CG Arr: {cg_arr.shape}, max={cg_arr.max()}")
print(f"Alpha Arr: {alpha_arr.shape}, max={alpha_arr.max()}")

cv2.imwrite('test_output_cg.png', hdr_to_uint8(cg_arr))
cv2.imwrite('test_output_alpha.png', (alpha_arr * 255).astype(np.uint8))

target_shape = p.state.plate_array.shape[:2]
print(f"Target shape: {target_shape}")

cg_resized = cv2.resize(cg_arr, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)
alpha_resized = cv2.resize(alpha_arr, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)

print(f"Resized CG max: {cg_resized.max()}")
print(f"Resized Alpha max: {alpha_resized.max()}")

alpha_2d = np.clip(np.squeeze(alpha_resized), 0.0, 1.0)
if alpha_2d.ndim != 2: alpha_2d = alpha_2d[..., 0]
alpha_3d = alpha_2d[:, :, np.newaxis]

composite = cg_resized[..., :3] + p.state.plate_array[..., :3] * (1.0 - alpha_3d)

print(f"Composite max: {composite.max()}")
cv2.imwrite('test_output_composite.png', hdr_to_uint8(composite))

