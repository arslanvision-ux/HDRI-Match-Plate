import sys
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.io.loader import load_cg_alpha_from_exr, load_light_aovs_from_exr
import numpy as np

file_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'
alpha = load_cg_alpha_from_exr(file_path)
alpha_3d = alpha.reshape(alpha.shape[0], alpha.shape[1], 1)

target_shape = (4000, 6000) # Simulating a large raw plate

import cv2
resized_alpha = cv2.resize(alpha_3d, (target_shape[1], target_shape[0]), interpolation=cv2.INTER_AREA)

print(f"Original alpha shape: {alpha_3d.shape}, min: {alpha_3d.min()}, max: {alpha_3d.max()}")
print(f"Resized alpha shape: {resized_alpha.shape}, min: {resized_alpha.min()}, max: {resized_alpha.max()}")

alpha_2d = np.squeeze(resized_alpha)
if alpha_2d.ndim != 2:
    alpha_2d = alpha_2d[..., 0]
alpha_vis = np.stack([alpha_2d, alpha_2d, alpha_2d], axis=-1)

print(f"Alpha vis shape: {alpha_vis.shape}, min: {alpha_vis.min()}, max: {alpha_vis.max()}")
