import sys
import os
import numpy as np

# Nuke-safe image writer (PPM format)
def write_ppm(filepath, image_rgb_uint8):
    h, w, c = image_rgb_uint8.shape
    with open(filepath, 'wb') as f:
        f.write(f"P6\n{w} {h}\n255\n".encode('ascii'))
        f.write(image_rgb_uint8.tobytes())

def debug_viewer_logic():
    print("\n" + "="*50)
    print(" HDRI MATCH PLATE - CG RENDER DEBUGGER (NUKE SAFE)")
    print("="*50 + "\n")

    # Force reload the pipeline and exr modules if running inside Nuke's persistent session!
    import importlib
    try:
        import hdri_match.io.exr_pure
        importlib.reload(hdri_match.io.exr_pure)
        import hdri_match.core.pipeline
        importlib.reload(hdri_match.core.pipeline)
        print("✅ Flushed Nuke's sys.modules cache!")
    except Exception:
        pass

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from hdri_match.core.pipeline import CalibrationPipeline
    from hdri_match.io.exr_pure import read_multipart_exr_parts

    p = CalibrationPipeline()
    cg_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'

    print(f"[1] Loading CG Multi-Pass EXR:\n    -> {cg_path}")
    
    try:
        p.load_cg_lights(cg_path, prefixes=("light_", "C_Light_", "ght_"), input_colorspace="Linear", working_space="Linear")
        if not p.state.cg_lights:
            print("❌ ERROR: No light AOVs were extracted from the EXR!")
            return
        else:
            print(f"✅ SUCCESS: Extracted {len(p.state.cg_lights)} light AOVs:")
            for k, v in p.state.cg_lights.items():
                print(f"    - {k}: shape={v.shape}, min={v.min():.4f}, max={v.max():.4f}")
    except Exception as e:
        print(f"❌ CRITICAL ERROR during EXR parsing: {e}")
        return

    # 2. Check CG Reconstructed Beauty
    print("\n[2] Checking Reconstructed Beauty Pass (Merge Plus)...")
    cg_arr = p.state.cg_reconstructed
    if cg_arr is None:
        print("❌ ERROR: Reconstructed Beauty is None!")
        return
    print(f"✅ SUCCESS: Beauty Reconstructed: shape={cg_arr.shape}, min={cg_arr.min():.4f}, max={cg_arr.max():.4f}")

    # 3. Check Alpha
    print("\n[3] Checking Alpha extraction...")
    alpha_arr = p.state.cg_alpha
    if alpha_arr is None:
        print("❌ ERROR: Alpha channel is None!")
        return
    print(f"✅ SUCCESS: Alpha Extracted: shape={alpha_arr.shape}, min={alpha_arr.min():.4f}, max={alpha_arr.max():.4f}")

    # 4. Save raw debug images for the user to inspect
    print("\n[4] Writing intermediate debug images to disk (PPM format)...")
    try:
        debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_output")
        os.makedirs(debug_dir, exist_ok=True)
        
        # Save Alpha
        alpha_u8 = (np.clip(alpha_arr, 0.0, 1.0) * 255.0).astype(np.uint8)
        alpha_rgb = np.stack([alpha_u8]*3, axis=-1)
        write_ppm(os.path.join(debug_dir, "debug_01_alpha.ppm"), alpha_rgb)
        
        # Save Beauty Tone-mapped
        img = np.array(cg_arr[..., :3], dtype=np.float32, copy=True)
        np.nan_to_num(img, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        luma = (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2])
        p98 = float(np.percentile(luma, 98))
        if p98 > 1e-6:
            img = img * (0.9 / p98)
        np.clip(img, 0.0, 1.0, out=img)
        np.power(img, 1.0 / 2.2, out=img) # sRGB gamma
        u8 = (img * 255.0).astype(np.uint8)
        
        write_ppm(os.path.join(debug_dir, "debug_02_beauty.ppm"), u8)
        print("    -> Wrote 'debug_01_alpha.ppm' and 'debug_02_beauty.ppm'")
    except Exception as e:
        print(f"❌ Failed to write debug images: {e}")

    print("\n" + "="*50)
    print(" DEBUG COMPLETE")
    print("="*50 + "\n")

if __name__ == "__main__":
    debug_viewer_logic()
