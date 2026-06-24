import os
import base64
import numpy as np

def array_to_base64_jpg(img_array: np.ndarray, quality: int = 80) -> str:
    """Convert a float32 linear numpy array to a base64 encoded sRGB JPEG string."""
    if img_array is None:
        return ""
    
    try:
        import cv2
        # Apply sRGB gamma curve for display in HTML
        srgb = np.power(np.clip(img_array, 0.0, 1.0), 1.0 / 2.2)
        # Convert to 8-bit
        u8 = (srgb * 255.0).astype(np.uint8)
        
        # BGR to RGB if 3 channels
        if u8.ndim == 3 and u8.shape[2] == 3:
            u8 = cv2.cvtColor(u8, cv2.COLOR_BGR2RGB)
            
        success, encoded_image = cv2.imencode('.jpg', u8, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if success:
            b64_str = base64.b64encode(encoded_image).decode('utf-8')
            return f"data:image/jpeg;base64,{b64_str}"
    except ImportError:
        pass
    except Exception as e:
        print(f"Error converting image to base64: {e}")
        
    return ""

def array_to_base64_png(img_array: np.ndarray) -> str:
    """Convert a float32 linear numpy array to a base64 encoded sRGB PNG string."""
    if img_array is None:
        return ""
    
    try:
        import cv2
        srgb = np.power(np.clip(img_array, 0.0, 1.0), 1.0 / 2.2)
        u8 = (srgb * 255.0).astype(np.uint8)
        
        if u8.ndim == 3 and u8.shape[2] == 3:
            u8 = cv2.cvtColor(u8, cv2.COLOR_BGR2RGB)
            
        success, encoded_image = cv2.imencode('.png', u8)
        if success:
            b64_str = base64.b64encode(encoded_image).decode('utf-8')
            return f"data:image/png;base64,{b64_str}"
    except Exception:
        pass
        
    return ""

def extract_exr_metadata(path):
    if not path or not os.path.exists(path) or not path.lower().endswith(".exr"):
        return {}
    
    meta = {}
    try:
        from hdri_match.io.exr_pure import read_multipart_exr_parts
        import struct
        parts = read_multipart_exr_parts(path)
        if parts:
            attrs = parts[0].get('attrs', {})
            for k, v in attrs.items():
                val = None
                if v[0] == 'float' and len(v[1]) >= 4:
                    val = round(struct.unpack('<f', v[1][:4])[0], 3)
                elif v[0] == 'string':
                    val = v[1].decode('utf-8', errors='ignore').rstrip('\x00')
                elif v[0] == 'int' and len(v[1]) >= 4:
                    val = struct.unpack('<i', v[1][:4])[0]
                elif v[0] == 'v2f' and len(v[1]) >= 8:
                    x, y = struct.unpack('<2f', v[1][:8])
                    val = f"{x:.3f}, {y:.3f}"
                
                if val is not None:
                    meta[k] = val
                    
    except Exception as e:
        print(f"Error extracting metadata from {path}: {e}")
        
    return meta

def generate_html_report(state, output_path: str):
    """Generates a self-contained mobile-friendly HTML QC report."""
    
    hdri_b64 = array_to_base64_jpg(state.calibrated_proxy if state.calibrated_proxy is not None else state.hdri_proxy)
    plate_b64 = array_to_base64_jpg(state.plate_graded_proxy if state.plate_graded_proxy is not None else state.plate_proxy)
    
    # Generate false color
    fc_b64 = ""
    if state.hdri_proxy is not None:
        try:
            import cv2
            hdri_for_fc = state.calibrated_proxy if state.calibrated_proxy is not None else state.hdri_proxy
            # Simple false color mapping based on luminance
            luma = 0.2126 * hdri_for_fc[..., 0] + 0.7152 * hdri_for_fc[..., 1] + 0.0722 * hdri_for_fc[..., 2]
            
            # 0.0 -> Blue, 0.18 -> Green, 1.0 -> Yellow, >1.0 -> Red
            fc_img = np.zeros((hdri_for_fc.shape[0], hdri_for_fc.shape[1], 3), dtype=np.float32)
            
            # Very dark (under exposed)
            fc_img[luma < 0.02] = [0.0, 0.0, 1.0] # Blue
            # Midtones
            mid_mask = (luma >= 0.02) & (luma < 0.5)
            fc_img[mid_mask] = [0.0, 1.0, 0.0] # Green
            # Highlights
            high_mask = (luma >= 0.5) & (luma < 1.0)
            fc_img[high_mask] = [1.0, 1.0, 0.0] # Yellow
            # Over-exposed (clipped)
            fc_img[luma >= 1.0] = [1.0, 0.0, 0.0] # Red
            
            # Blend with grayscale image for context
            luma_3d = np.repeat(luma[..., np.newaxis], 3, axis=2)
            fc_blended = fc_img * 0.7 + luma_3d * 0.3
            fc_b64 = array_to_base64_jpg(fc_blended)
        except Exception as e:
            print(f"Error generating false color: {e}")

    plate_meta = extract_exr_metadata(getattr(state, 'plate_path', ''))
    hdri_meta = extract_exr_metadata(getattr(state, 'hdri_path', ''))
    
    def dict_to_html_list(d, title):
        if not d: return f"<h3>{title}</h3><p style='font-size:12px; color:#888;'>No metadata found</p>"
        # Filter to interesting keys
        interesting = ["focallength", "aperture", "iso", "shutter", "camera", "lens", "owner", "timecode", "exposure", "colorSpace"]
        filtered = {k: v for k,v in d.items() if any(i in k.lower() for i in interesting)}
        if not filtered:
            filtered = {k: d[k] for k in list(d.keys())[:10]} # Fallback
            
        items = "".join(f"<li style='margin-bottom:4px;'><strong style='color:#ccc;'>{k}:</strong> <span style='color:#4CAF50;'>{v}</span></li>" for k, v in filtered.items())
        return f"<h3>{title}</h3><ul style='font-size:12px; list-style-type:none; padding:0; margin:0;'>{items}</ul>"
        
    meta_html = ""
    if plate_meta or hdri_meta:
        meta_html = f"""
    <div class="card">
        <h2>Camera Metadata</h2>
        <div class="comparison">
            <div class="image-container" style="background-color: #252525; padding: 12px; border-radius: 6px;">
                {dict_to_html_list(hdri_meta, "HDRI Metadata")}
            </div>
            <div class="image-container" style="background-color: #252525; padding: 12px; border-radius: 6px;">
                {dict_to_html_list(plate_meta, "Plate Metadata")}
            </div>
        </div>
    </div>
"""

    # Create CSS & HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HDRI QC Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #121212;
            color: #e0e0e0;
            margin: 0;
            padding: 16px;
        }}
        h1, h2, h3 {{
            color: #ffffff;
            margin-top: 0;
        }}
        .header {{
            border-bottom: 1px solid #333;
            padding-bottom: 12px;
            margin-bottom: 20px;
        }}
        .card {{
            background-color: #1e1e1e;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }}
        .stat-box {{
            background-color: #2c2c2c;
            padding: 12px;
            border-radius: 6px;
            text-align: center;
        }}
        .stat-label {{
            font-size: 12px;
            color: #aaaaaa;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }}
        .stat-value {{
            font-size: 18px;
            font-weight: bold;
            color: #4CAF50;
        }}
        .image-container {{
            width: 100%;
            overflow: hidden;
            border-radius: 6px;
            margin-bottom: 12px;
        }}
        img {{
            width: 100%;
            height: auto;
            display: block;
        }}
        .comparison {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        @media (min-width: 768px) {{
            .comparison {{
                flex-direction: row;
            }}
            .comparison .image-container {{
                flex: 1;
            }}
        }}
    </style>
</head>
<body>

    <div class="header">
        <h1>HDRI Calibration Report</h1>
        <p style="color: #888; font-size: 14px;">Generated on set for quick QC validation.</p>
    </div>

    <div class="stats-grid">
        <div class="stat-box">
            <div class="stat-label">EV Offset</div>
            <div class="stat-value">{state.ev_offset:+.2f} stops</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Temperature</div>
            <div class="stat-value">{state.temperature:+.2f}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Tint</div>
            <div class="stat-value">{state.tint:+.2f}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Sun Azimuth</div>
            <div class="stat-value">{getattr(state, 'sun_azimuth', 0.0) or 0.0:.1f}°</div>
        </div>
    </div>

    <div class="card">
        <h2>Side-by-Side Comparison</h2>
        <div class="comparison">
            <div class="image-container">
                <div class="stat-label" style="margin-bottom: 8px;">Calibrated HDRI</div>
                <img src="{hdri_b64}" alt="Calibrated HDRI">
            </div>
            <div class="image-container">
                <div class="stat-label" style="margin-bottom: 8px;">Reference Plate</div>
                <img src="{plate_b64}" alt="Plate">
            </div>
        </div>
    </div>

    <div class="card">
        <h2>False Color Analysis</h2>
        <p style="font-size: 12px; color: #888; margin-bottom: 12px;">Blue: Shadows | Green: Midtones | Yellow: Highlights | Red: Clipped</p>
        <div class="image-container">
            <img src="{fc_b64}" alt="False Color">
        </div>
    </div>

    {meta_html}
    
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Report generated successfully at {output_path}")
