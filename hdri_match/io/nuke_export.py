def export_nuke_nodes(st, include_yaw=True) -> str:
    def get_rgb_scale(temp, tint):
        r_scale = max(0.01, 1.0 + temp + tint)
        g_scale = max(0.01, 1.0 - tint)
        b_scale = max(0.01, 1.0 - temp)
        lum = (r_scale + g_scale + b_scale) / 3.0
        return r_scale/lum, g_scale/lum, b_scale/lum

    ev = st.ev_offset if getattr(st, 'apply_exposure_match', False) else 0.0
    bo = st.black_offset if getattr(st, 'apply_exposure_match', False) else 0.0
    
    hdri_path = getattr(st, 'hdri_path', '')
    if hdri_path:
        hdri_path = hdri_path.replace('\\', '/')
        nuke_script = f"""version 14.0
Read {{
 inputs 0
 file "{hdri_path}"
 name Read_HDRI
}}
"""
    else:
        nuke_script = f"""set cut_paste_input [stack 0]
version 14.0
push $cut_paste_input
"""

    nuke_script += f"""Dot {{
 name HDRI_Input
}}
set N_Input [stack 0]

EXPTool {{
 mode Stops
 red {ev}
 green {ev}
 blue {ev}
 name HDRI_EV_Offset
}}
Add {{
 value {bo}
 name HDRI_Black_Offset
}}
"""
    
    if getattr(st, 'macbeth_matrix', None) is not None:
        m = st.macbeth_matrix
        nuke_script += f"""ColorMatrix {{
 matrix {{
     {{{m[0,0]:.5f} {m[1,0]:.5f} {m[2,0]:.5f}}}
     {{{m[0,1]:.5f} {m[1,1]:.5f} {m[2,1]:.5f}}}
     {{{m[0,2]:.5f} {m[1,2]:.5f} {m[2,2]:.5f}}}
   }}
 name HDRI_Macbeth_Matrix
}}
"""
    elif getattr(st, 'hdri_illuminant', None) is not None and getattr(st, 'plate_illuminant', None) is not None:
        import numpy as np
        hdri_safe = np.clip(st.hdri_illuminant, 1e-8, None)
        plate_safe = np.clip(st.plate_illuminant, 1e-8, None)
        scale = plate_safe / hdri_safe
        nuke_script += f"""Multiply {{
 value {{{scale[0]:.5f} {scale[1]:.5f} {scale[2]:.5f} 1}}
 name HDRI_Illuminant_Match
}}
"""
    
    cr, cg, cb = get_rgb_scale(getattr(st, 'temperature', 0.0), getattr(st, 'tint', 0.0))
    nuke_script += f"""Multiply {{
 value {{{cr:.5f} {cg:.5f} {cb:.5f} 1}}
 name HDRI_TempTint
}}
"""

    nuke_script += "set N_Calibrated [stack 0]\n"

    # --- MULTI-MASK GRADING ---
    if getattr(st, 'masks', None):
        for i, mask in enumerate(st.masks):
            if not getattr(mask, 'enabled', True) or mask.rect is None:
                continue
                
            nx1, ny1, nx2, ny2 = mask.rect
            nx1, nx2 = min(nx1, nx2), max(nx1, nx2)
            ny1, ny2 = min(ny1, ny2), max(ny1, ny2)
            
            nuke_script += f"""
push $N_Calibrated
Expression {{
 channel0 none
 channel1 none
 channel2 none
 channel3 rgba.alpha
"""
            if mask.shape == "Ellipse":
                cx = (nx1 + nx2) / 2.0
                cy = 1.0 - (ny1 + ny2) / 2.0
                rx = max((nx2 - nx1) / 2.0, 1e-5)
                ry = max((ny2 - ny1) / 2.0, 1e-5)
                nuke_script += f' expr3 "pow((x/width - {cx:.5f})/{rx:.5f}, 2) + pow((y/height - {cy:.5f})/{ry:.5f}, 2) <= 1.0 ? 1.0 : 0.0"\n'
            else:
                y_min = 1.0 - ny2
                y_max = 1.0 - ny1
                nuke_script += f' expr3 "x/width >= {nx1:.5f} && x/width <= {nx2:.5f} && y/height >= {y_min:.5f} && y/height <= {y_max:.5f} ? 1.0 : 0.0"\n'

            nuke_script += f""" name Mask_{i+1}_Shape
}}
"""
            nuke_script += f"""Blur {{
 size {getattr(mask, 'feather', 0.0)}
 name Mask_{i+1}_Feather
}}
"""
            nuke_script += f"""Multiply {{
 value {getattr(mask, 'blend', 1.0)}
 name Mask_{i+1}_Blend
}}
"""
            nuke_script += f"set N_Mask_Alpha_{i+1} [stack 0]\n"
            
            if getattr(mask, 'stencil_enable', False):
                mode = getattr(mask, 'stencil_mode', 'Luminance')
                invert = getattr(mask, 'stencil_invert', False)
                thresh = getattr(mask, 'stencil_threshold', 0.5)
                
                if mode == "Luminance":
                    expr = "0.2126*r + 0.7152*g + 0.0722*b"
                elif mode == "Green Key":
                    expr = "g - max(r, b)"
                else: # Blue Key
                    expr = "b - max(r, g)"
                    
                inv_str = "1.0 - " if invert else ""
                # Simple soft-clip around threshold
                nuke_script += f"""
push $N_Calibrated
Expression {{
 temp_name0 key
 temp_expr0 "{expr}"
 temp_name1 t
 temp_expr1 {thresh:f}
 expr3 "clamp({inv_str}(key - t) * 10.0 + 0.5, 0.0, 1.0)"
 name Mask_{i+1}_Stencil
}}
push $N_Mask_Alpha_{i+1}
Merge2 {{
 inputs 2
 operation multiply
 Achannels alpha
 Bchannels alpha
 output alpha
 name Mask_{i+1}_StencilMix
}}
set N_Mask_Alpha_{i+1} [stack 0]
"""
            
            mode = getattr(mask, 'mode', 'Grade')
            if mode == "Solid Fill":
                r, g, b = getattr(mask, 'fill_color', (0.18, 0.18, 0.18))
                nuke_script += f"""Constant {{
 inputs 0
 channels rgb
 color {{{r} {g} {b} 0}}
 format "none"
 name Mask_{i+1}_Fill
}}
set N_Fill_{i+1} [stack 0]

push $N_Calibrated
push $N_Fill_{i+1}
push $N_Mask_Alpha_{i+1}
Keymix {{
 inputs 3
 name Mask_{i+1}_Apply
}}
set N_Calibrated [stack 0]
"""
            elif mode == "Chroma Replace":
                r, g, b = getattr(mask, 'fill_color', (0.18, 0.18, 0.18))
                is_green = getattr(mask, 'chroma_hue', 120.0) < 180
                tol = getattr(mask, 'chroma_tolerance', 0.5)
                edge0 = max(0.01, 1.0 - tol)
                edge1 = edge0 + 0.2
                delta = max(edge1 - edge0, 1e-6)
                key_expr = "g - max(r,b)" if is_green else "b - max(r,g)"
                nuke_script += f"""push $N_Calibrated
Expression {{
 temp_name0 key
 temp_expr0 "{key_expr}"
 temp_name1 max_c
 temp_expr1 "max(r, max(g, b))"
 temp_name2 key_norm
 temp_expr2 "key / max(max_c, 1e-6)"
 temp_name3 t
 temp_expr3 "clamp((key_norm - {edge0}) / {delta}, 0.0, 1.0)"
 expr3 "t * t * (3.0 - 2.0 * t)"
 name Mask_{i+1}_ChromaKey
}}
set N_ChromaKey_{i+1} [stack 0]

Constant {{
 inputs 0
 channels rgb
 color {{{r} {g} {b} 0}}
 format "none"
 name Mask_{i+1}_ChromaFill
}}
set N_ChromaFill_{i+1} [stack 0]

push $N_Calibrated
push $N_ChromaFill_{i+1}
push $N_ChromaKey_{i+1}
Keymix {{
 inputs 3
 name Mask_{i+1}_ChromaMix
}}
set N_ChromaResult_{i+1} [stack 0]

push $N_Calibrated
push $N_ChromaResult_{i+1}
push $N_Mask_Alpha_{i+1}
Keymix {{
 inputs 3
 name Mask_{i+1}_Apply
}}
set N_Calibrated [stack 0]
"""
            else: # Grade
                nuke_script += f"""push $N_Calibrated
Dot {{
 name Mask_{i+1}_Branch
}}
set N_Branch_{i+1} [stack 0]
"""
                nuke_script += f"""Blur {{
 size {getattr(mask, 'blur', 0.0)}
 name Mask_{i+1}_Blur
}}
"""
                ev = getattr(mask, 'ev_offset', 0.0)
                nuke_script += f"""EXPTool {{
 mode Stops
 red {ev}
 green {ev}
 blue {ev}
 name Mask_{i+1}_EV
}}
"""
                temp = getattr(mask, 'temperature', 0.0)
                tint = getattr(mask, 'tint', 0.0)
                mcr, mcg, mcb = get_rgb_scale(temp, tint)
                nuke_script += f"""Multiply {{
 value {{{mcr:.5f} {mcg:.5f} {mcb:.5f} 1}}
 name Mask_{i+1}_TempTint
}}
"""
            
                nuke_script += f"""set N_Grade_{i+1} [stack 0]

push $N_Branch_{i+1}
push $N_Grade_{i+1}
push $N_Mask_Alpha_{i+1}
Keymix {{
 inputs 3
 name Mask_{i+1}_Apply
}}
set N_Calibrated [stack 0]
"""

    # --- HORIZON SEPARATION ---
    if getattr(st, 'horizon_enable', False):
        hh = getattr(st, 'horizon_height', 0.5)
        hf = getattr(st, 'horizon_feather', 0.1)
        
        nuke_script += f"""
push $N_Calibrated
Expression {{
 expr3 "smoothstep(-{hf}/2.0, {hf}/2.0, {hh} - y/height)"
 name HDRI_Ground_Mask
}}
set N_Mask [stack 0]

push $N_Calibrated
"""
        gev = getattr(st, 'ground_ev_offset', 0.0)
        nuke_script += f"""EXPTool {{
 mode Stops
 red {gev}
 green {gev}
 blue {gev}
 name HDRI_Ground_EV
}}
"""
        gtemp = getattr(st, 'ground_temperature', 0.0)
        gtint = getattr(st, 'ground_tint', 0.0)
        cr, cg, cb = get_rgb_scale(gtemp, gtint)
        nuke_script += f"""Multiply {{
 value {{{cr:.5f} {cg:.5f} {cb:.5f} 1}}
 name HDRI_Ground_TempTint
}}
"""
        gdesat = getattr(st, 'ground_desat', 0.0)
        nuke_script += f"""Saturation {{
 saturation {1.0 - gdesat}
 name HDRI_Ground_Desat
}}
"""
        nuke_script += "set N_Ground [stack 0]\n"
        
        nuke_script += f"""
push $N_Calibrated
"""
        sev = getattr(st, 'sky_ev_offset', 0.0)
        nuke_script += f"""EXPTool {{
 mode Stops
 red {sev}
 green {sev}
 blue {sev}
 name HDRI_Sky_EV
}}
"""
        stemp = getattr(st, 'sky_temperature', 0.0)
        stint = getattr(st, 'sky_tint', 0.0)
        cr, cg, cb = get_rgb_scale(stemp, stint)
        nuke_script += f"""Multiply {{
 value {{{cr:.5f} {cg:.5f} {cb:.5f} 1}}
 name HDRI_Sky_TempTint
}}
"""
        sdesat = getattr(st, 'sky_desat', 0.0)
        nuke_script += f"""Saturation {{
 saturation {1.0 - sdesat}
 name HDRI_Sky_Desat
}}
"""
        nuke_script += "set N_Sky [stack 0]\n"
        
        nuke_script += f"""
push $N_Mask
push $N_Ground
push $N_Sky
Keymix {{
 inputs 3
 name HDRI_Horizon_Mix
}}
"""

    # --- SOFTCLIP ---
    if getattr(st, 'softclip_enable', False):
        t = 0.18 * (2.0 ** getattr(st, 'softclip_threshold', 5.0))
        rolloff = 0.18 * (2.0 ** getattr(st, 'softclip_rolloff', 2.0))
        nuke_script += f"""
Expression {{
 temp_name0 t
 temp_expr0 {t}
 temp_name1 rolloff
 temp_expr1 {rolloff}
 temp_name2 luma
 temp_expr2 "0.2126*r + 0.7152*g + 0.0722*b"
 temp_name3 ratio
 temp_expr3 "(luma > t ? t + rolloff * (1.0 - exp(-(luma - t) / max(rolloff, 1e-8))) : luma) / max(luma, 1e-8)"
 expr0 "r * ratio"
 expr1 "g * ratio"
 expr2 "b * ratio"
 name HDRI_SoftClip
}}
"""
    yaw = getattr(st, 'hdri_yaw', 0.0)
    if include_yaw and yaw != 0.0:
        nuke_script += f"""Expression {{
 temp_name0 offset
 temp_expr0 "({yaw}/360.0)*width"
 temp_name1 x_shifted
 temp_expr1 "x - offset"
 temp_name2 x_wrapped
 temp_expr2 "x_shifted - floor(x_shifted / width) * width"
 expr0 "r(x_wrapped, y)"
 expr1 "g(x_wrapped, y)"
 expr2 "b(x_wrapped, y)"
 name HDRI_Yaw_Rotation
}}
"""
    return nuke_script

def export_cg_nuke_nodes(st) -> str:
    """
    Generates Nuke nodes for reconstructing the CG Multi-Pass Lookdev.
    """
    if not getattr(st, 'cg_lights', None) or not getattr(st, 'cg_exr_path', None):
        return ""
        
    nuke_script = "set cut_paste_input [stack 0]\nversion 14.0\npush $cut_paste_input\n"
    
    nuke_script += f"""Read {{
 inputs 0
 file "{st.cg_exr_path.replace(chr(92), '/')}"
 name CG_EXR_In
}}
set N_CG_EXR [stack 0]
"""

    first = True
    any_solo = any(p.get("solo", False) for p in st.cg_light_params.values())

    for name in sorted(st.cg_lights.keys()):
        params = st.cg_light_params.get(name, {})
        
        enabled = True
        if any_solo:
            if not params.get("solo", False):
                enabled = False
        else:
            if not params.get("enabled", True):
                enabled = False
                
        mult_alpha = 1.0 if enabled else 0.0

        nuke_script += f"""push $N_CG_EXR
Shuffle {{
 in {name}
 name Shuffle_{name}
}}
"""
        ev = params.get("ev", 0.0)
        nuke_script += f"""EXPTool {{
 mode Stops
 red {ev}
 green {ev}
 blue {ev}
 name {name}_EV
}}
"""
        temp = params.get("temp", 0.0)
        tint = params.get("tint", 0.0)
        color = params.get("color", [1.0, 1.0, 1.0])
        r_scale = max(0.01, 1.0 + temp + tint)
        g_scale = max(0.01, 1.0 - tint)
        b_scale = max(0.01, 1.0 - temp)
        lum = (r_scale + g_scale + b_scale) / 3.0
        cr, cg, cb = r_scale/lum, g_scale/lum, b_scale/lum
        
        fr = cr * color[0] * mult_alpha
        fg = cg * color[1] * mult_alpha
        fb = cb * color[2] * mult_alpha
        
        nuke_script += f"""Multiply {{
 value {{{fr:.5f} {fg:.5f} {fb:.5f} 1}}
 name {name}_TempTint
}}
"""
        if first:
            first = False
        else:
            nuke_script += f"""Merge2 {{
 inputs 2
 operation plus
 name Merge_{name}
}}
"""
            
    return nuke_script

def export_backplate_nuke_nodes(st, resolution="UHD_4K", fov=60.0) -> str:
    """
    Generates Nuke nodes for extracting a Rectilinear Backplate from the HDRI.
    Uses the calibrated HDRI script and appends a SphericalTransform.
    """
    nuke_script = export_nuke_nodes(st, include_yaw=False)
    
    # We want to extract the backplate facing the designated yaw angle
    yaw = getattr(st, 'hdri_yaw', 0.0)
    yaw_norm = yaw / 360.0
        
    import math
    f = 1.0 / math.tan(math.radians(fov) / 2.0)
    
    res_map = {
        "HD_1080": (1920, 1080),
        "UHD_4K": (3840, 2160),
        "8K_LatLong": (8192, 4096),
        "square_2K": (2048, 2048)
    }
    w, h = res_map.get(resolution, (3840, 2160))
    aspect = h / float(w)
    
    nuke_script += f"""set N_HDRI_Out [stack 0]

Crop {{
 box {{0 0 {w} {h}}}
 reformat true
 crop false
 name Backplate_Canvas
}}
Expression {{
 temp_name0 px
 temp_expr0 "(x + 0.5) / width * 2.0 - 1.0"
 temp_name1 py
 temp_expr1 "((y + 0.5) / height * 2.0 - 1.0) * {aspect:.5f}"
 temp_name2 length
 temp_expr2 "sqrt(px*px + py*py + {f:.5f}*{f:.5f})"
 temp_name3 u_shifted
 temp_expr3 "atan2(px, {f:.5f}) / (2.0 * pi) + 0.5 - {yaw_norm:.5f}"
 expr0 "u_shifted - floor(u_shifted)"
 expr1 "asin(py / length) / pi + 0.5"
 expr2 "0"
 name Rectilinear_UVs
}}
push $N_HDRI_Out
STMap {{
 inputs 2
 uv rgb
 name Backplate_STMap
}}
"""
    return nuke_script

def export_nuke_3d_scene(st, vp_state) -> str:
    """
    Generates Nuke nodes for a basic 3D scene matching the Viewport3D parameters.
    vp_state is a dict containing viewport properties.
    """
    import math
    
    # 1. Base HDRI calibration setup
    nuke_script = export_nuke_nodes(st, include_yaw=False)
    
    # Apply yaw natively to the sphere rotation in Nuke, rather than mapping
    yaw = getattr(st, 'hdri_yaw', 0.0)
    
    nuke_script += "set N_HDRI_Texture [stack 0]\n"
    
    # Environment node for ambient light
    nuke_script += """Environment {
 name HDRI_Environment
}
set N_Env [stack 0]
"""

    # Sphere (Dome)
    R = vp_state.get('hdri_radius', 50.0)
    tx, ty, tz = vp_state.get('hdri_translate', [0,0,0])
    rx, ry, rz = vp_state.get('hdri_rotate', [0,0,0])
    
    nuke_script += f"""push $N_HDRI_Texture
Sphere {{
 radius {R}
 translate {{{tx} {ty} {tz}}}
 rotate {{{rx-90.0} {ry-yaw} {rz}}}
 name HDRI_Dome
}}
set N_Dome [stack 0]
"""
    
    # Sun Light
    if st.sun_auto_detected or getattr(st, 'sun_relight_enabled', False):
        u, v = st.sun_target_u, st.sun_target_v
        yaw_norm = yaw / 360.0
        vis_u = (u + yaw_norm) % 1.0
        theta = vis_u * 2 * math.pi
        phi = (1.0 - v) * math.pi
        sx = math.sin(phi) * math.cos(theta) * R
        sy = math.cos(phi) * R
        sz = -math.sin(phi) * math.sin(theta) * R
        
        nuke_script += f"""Light3 {{
 inputs 0
 translate {{{sx:.3f} {sy:.3f} {sz:.3f}}}
 intensity 1.0
 name Sun_Light
}}
set N_Sun [stack 0]
"""
    else:
        sun_exists = False
        nuke_script += "\n"
        
    # Camera
    cam_fl = vp_state.get('cam_fl', 50.0)
    cam_sensor = vp_state.get('cam_sensor', 24.0)
    # Assume 16:9 for haperture, sensor_height is vaperture
    aspect = 16.0 / 9.0
    cam_hap = cam_sensor * aspect
    
    cam_dist = vp_state.get('cam_dist', 0.0)
    cam_tx = vp_state.get('cam_pan_x', 0.0)
    cam_ty = vp_state.get('cam_pan_y', 0.0)
    cam_tz = vp_state.get('cam_pan_z', 0.0) + cam_dist
    cam_rx = vp_state.get('cam_rot_x', 0.0)
    cam_ry = vp_state.get('cam_rot_y', 0.0)
    cam_focus = vp_state.get('cam_focus', 100.0)
    
    nuke_script += f"""Camera3 {{
 inputs 0
 focal {cam_fl}
 haperture {cam_hap}
 vaperture {cam_sensor}
 translate {{{cam_tx} {cam_ty} {cam_tz}}}
 rotate {{{cam_rx} {cam_ry} 0}}
 focal_point {cam_focus}
 name Match_Camera
}}
set N_Cam [stack 0]
"""
    # Meshes (Chrome / Grey balls)
    meshes_script = ""
    mesh_pushes = ""
    mesh_count = 0
    for i, m in enumerate(vp_state.get('meshes', [])):
        mat = m.get('material', '')
        t = m.get('t', [0,0,0])
        r = m.get('r', [0,0,0])
        s = m.get('s', [1,1,1])
        name = m.get('name', f'Mesh_{i}').replace(' ', '_')
        
        if mat in ['Chrome', 'Grey']:
            rad = 1.0 * s[0]
            meshes_script += f"""push $N_HDRI_Texture
Environment {{
 name Env_{name}
}}
Sphere {{
 radius {rad}
 translate {{{t[0]} {t[1]} {t[2]}}}
 rotate {{{r[0]} {r[1]} {r[2]}}}
 name {name}
}}
set N_{name} [stack 0]
"""
            mesh_pushes += f"push $N_{name}\n"
            mesh_count += 1
            
    nuke_script += meshes_script
    
    # Scene
    scene_inputs = f"""push $N_Env
push $N_Dome\n"""
    
    if st.sun_auto_detected or getattr(st, 'sun_relight_enabled', False):
        scene_inputs += "push $N_Sun\n"
        input_count = 3 + mesh_count
    else:
        input_count = 2 + mesh_count
        
    scene_inputs += f"{mesh_pushes}Scene {{\n inputs {input_count}\n name Scene1\n}}\nset N_Scene [stack 0]\n"
    
    nuke_script += scene_inputs
    
    plate_path = getattr(st, 'plate_path', '')
    if plate_path:
        plate_path = plate_path.replace('\\', '/')
        nuke_script += f"""Read {{
 inputs 0
 file "{plate_path}"
 name Read_Match_Plate
}}
set N_Plate [stack 0]
"""
        bg_input = "push $N_Plate\n"
    else:
        bg_input = "push 0\n"

    nuke_script += f"""{bg_input}push $N_Cam
push $N_Scene
ScanlineRender {{
 inputs 3
 projection_mode perspective
 name ScanlineRender1
}}
"""

    return nuke_script
