import sys
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.io.loader import load_cg_alpha_from_exr, load_light_aovs_from_exr
import numpy as np

file_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'

print("Loading Alpha...")
alpha = load_cg_alpha_from_exr(file_path)
if alpha is not None:
    print(f"Alpha loaded. Shape: {alpha.shape}, Min: {alpha.min():.4f}, Max: {alpha.max():.4f}")
else:
    print("Alpha not loaded.")

print("\nLoading Light AOVs...")
lights = load_light_aovs_from_exr(file_path, prefixes=("light", "C_Light"))
if lights:
    for name, arr in lights.items():
        print(f"Light {name} loaded. Shape: {arr.shape}, Min: {arr.min():.4f}, Max: {arr.max():.4f}")
else:
    print("No lights loaded.")

if lights:
    print("\nReconstructing Beauty...")
    reconstructed = None
    for name, arr in lights.items():
        if reconstructed is None:
            reconstructed = arr.copy()
        else:
            reconstructed += arr
    print(f"Reconstructed Beauty Shape: {reconstructed.shape}")
    print(f"Reconstructed Beauty Min: {reconstructed.min():.4f}, Max: {reconstructed.max():.4f}")
