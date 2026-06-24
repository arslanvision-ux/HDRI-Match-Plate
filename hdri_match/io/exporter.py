import numpy as np
import os
import json

# Must be set before cv2 is first imported — OpenCV reads this at import time
# on some platforms. Setting it inside a function body (after import) is too late.
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"


def save_numpy_to_image(image_array: np.ndarray, file_path: str):
    """Saves a NumPy float32 RGB array to an EXR or HDR file."""
    if image_array.ndim < 3:
        raise ValueError("Expected a 3-channel (H, W, 3) array.")
    height, width, channels = image_array.shape

    if channels != 3:
        raise ValueError("Only 3-channel RGB arrays are currently supported for export.")

    ext = os.path.splitext(file_path)[1].lower()

    try:
        import cv2
        contiguous_img = np.ascontiguousarray(image_array, dtype=np.float32)
        bgr = cv2.cvtColor(contiguous_img, cv2.COLOR_RGB2BGR)
        success = cv2.imwrite(file_path, bgr)
        if success:
            print(f"Saved {ext} successfully via OpenCV to: {file_path}")
            return
    except Exception as e:
        print(f"OpenCV export failed: {e}")
        
    try:
        import imageio.v3 as iio
        contiguous_img = np.ascontiguousarray(image_array, dtype=np.float32)
        iio.imwrite(file_path, contiguous_img)
        print(f"Saved {ext} successfully via ImageIO to: {file_path}")
        return
    except Exception as e:
        print(f"ImageIO export failed: {e}")
        
    raise RuntimeError(f"Failed to save {ext}. Ensure opencv-python or imageio is installed properly.")

def export_cg_light_data(light_params: dict, export_path: str):
    # 1. Clean up Light names (Strip 'C_' prefix, lowercase) so they match Houdini nodes
    cleaned_params = {}
    for k, v in light_params.items():
        new_key = k.lower()
        if new_key.startswith("c_"):
            new_key = new_key[2:]  # turns 'c_light_key' into 'light_key'
        cleaned_params[new_key] = v

    # 2. Export JSON
    with open(export_path, 'w') as f:
        json.dump(cleaned_params, f, indent=4)
    # 2. Generate standard Houdini OBJ Python Script
    script_path = os.path.splitext(export_path)[0] + "_houdini_obj.py"
    script = [
        "import hou",
        "import json",
        "",
        f"json_path = r'{export_path}'",
        "with open(json_path, 'r') as f:",
        "    light_data = json.load(f)",
        "",
        "for node in hou.node('/').allSubChildren():",
        "    name = node.name().lower()",
        "    matching_keys = [k for k in light_data.keys() if k.endswith(name) or name in k]",
        "    if not matching_keys:",
        "        continue",
        "",
        "    exp_names = ['exposure', 'ar_exposure', 'xn__inputsexposure_control', 'xn__inputsexposure_v3a']",
        "    col_names = ['color', 'light_color', 'ar_color', 'xn__inputscolor_control', 'xn__inputscolor_v3a']",
        "",
        "    exp_p = next((node.parm(en) for en in exp_names if node.parm(en) is not None), None)",
        "    col_p = next((node.parmTuple(cn) for cn in col_names if node.parmTuple(cn) is not None and len(node.parmTuple(cn)) >= 3), None)",
        "",
        "    if exp_p or col_p:",
        "        params = light_data[matching_keys[0]]",
        "        ev = params['ev']",
        "        temp = params['temp']",
        "        tint = params['tint']",
        "",
        "        if exp_p:",
        "            try: exp_p.set(exp_p.eval() + ev)",
        "            except: pass",
        "",
        "        r_scale = max(0.01, 1.0 + temp + tint)",
        "        g_scale = max(0.01, 1.0 - tint)",
        "        b_scale = max(0.01, 1.0 - temp)",
        "        lum = (r_scale + g_scale + b_scale) / 3.0",
        "        wb_color = (r_scale/lum, g_scale/lum, b_scale/lum)",
        "",
        "        explicit_color = params.get('color', [1.0, 1.0, 1.0])",
        "        color_mult = (wb_color[0]*explicit_color[0], wb_color[1]*explicit_color[1], wb_color[2]*explicit_color[2])",
        "",
        "        if col_p:",
        "            try:",
        "                c = col_p.eval()",
        "                col_p.set((c[0]*color_mult[0], c[1]*color_mult[1], c[2]*color_mult[2]))",
        "            except: pass",
        "",
        "print('Successfully updated Houdini Lights from HDRI Match Plate JSON!')"
    ]
    with open(script_path, 'w') as f:
        f.write("\n".join(script))

    # 3. Generate Solaris Python LOP script
    solaris_script_path = os.path.splitext(export_path)[0] + "_solaris_lop.py"
    solaris_script = [
        "node = hou.pwd()",
        "stage = node.editableStage()",
        "import json",
        "from pxr import UsdLux, Gf",
        "",
        f"json_path = r'{export_path}'",
        "with open(json_path, 'r') as f:",
        "    light_data = json.load(f)",
        "",
        "for prim in stage.TraverseAll():",
        "    if prim.HasAPI(UsdLux.LightAPI) or prim.IsA(UsdLux.Light):",
        "        name = prim.GetName().lower()",
        "        matching_keys = [k for k in light_data.keys() if k.endswith(name) or name in k]",
        "        if matching_keys:",
        "            params = light_data[matching_keys[0]]",
        "            ev = params['ev']",
        "            temp = params['temp']",
        "            tint = params['tint']",
        "",
        "            # Update Exposure",
        "            exp_attr = prim.GetAttribute('inputs:exposure')",
        "            if exp_attr.IsValid():",
        "                current_exp = exp_attr.Get() or 0.0",
        "                exp_attr.Set(current_exp + ev)",
        "",
        "            # Update Color",
        "            r_scale = max(0.01, 1.0 + temp + tint)",
        "            g_scale = max(0.01, 1.0 - tint)",
        "            b_scale = max(0.01, 1.0 - temp)",
        "            lum = (r_scale + g_scale + b_scale) / 3.0",
        "            wb_color = (r_scale/lum, g_scale/lum, b_scale/lum)",
        "",
        "            explicit_color = params.get('color', [1.0, 1.0, 1.0])",
        "            color_mult = (wb_color[0]*explicit_color[0], wb_color[1]*explicit_color[1], wb_color[2]*explicit_color[2])",
        "",
        "            color_attr = prim.GetAttribute('inputs:color')",
        "            if color_attr.IsValid():",
        "                c = color_attr.Get() or Gf.Vec3f(1.0, 1.0, 1.0)",
        "                color_attr.Set(Gf.Vec3f(c[0]*color_mult[0], c[1]*color_mult[1], c[2]*color_mult[2]))",
    ]
    with open(solaris_script_path, 'w') as f:
        f.write("\n".join(solaris_script))
        
    return export_path, solaris_script_path

def export_masks_as_solaris_lights(masks, hdri_array, export_dir):
    import math
    import cv2
    
    script_lines = [
        "import hou",
        "from pxr import Usd, UsdGeom, UsdLux, Gf",
        "node = hou.pwd()",
        "stage = node.editableStage()",
        "if not stage:",
        "    print('Please run inside a Python LOP')",
        "    pass",
        ""
    ]
    
    h, w = hdri_array.shape[:2]
    
    for i, mask in enumerate(masks):
        if mask.rect is None: continue
        
        nx1, ny1, nx2, ny2 = mask.rect
        cx = (nx1 + nx2) / 2.0
        cy = (ny1 + ny2) / 2.0
        
        # Crop texture
        sx1, sx2 = int(nx1 * w), int(nx2 * w)
        sy1, sy2 = int(ny1 * h), int(ny2 * h)
        
        sx1, sx2 = max(0, sx1), min(w, sx2)
        sy1, sy2 = max(0, sy1), min(h, sy2)
        
        if sx2 <= sx1 or sy2 <= sy1:
            continue
            
        roi = hdri_array[sy1:sy2, sx1:sx2].copy()
        
        # Resize to max 128
        roi_h, roi_w = roi.shape[:2]
        max_dim = max(roi_w, roi_h)
        if max_dim > 128:
            scale = 128.0 / max_dim
            new_w, new_h = int(roi_w * scale), int(roi_h * scale)
            roi = cv2.resize(roi, (new_w, new_h), interpolation=cv2.INTER_AREA)
            
        # Save texture
        safe_name = "".join(c if c.isalnum() else "_" for c in mask.name)
        if not safe_name: safe_name = f"Mask_{i}"
        
        tex_filename = f"mask_{i}_{safe_name}_tex.exr"
        tex_path = os.path.join(export_dir, tex_filename)
        
        contiguous_roi = np.ascontiguousarray(roi, dtype=np.float32)
        bgr = cv2.cvtColor(contiguous_roi, cv2.COLOR_RGB2BGR)
        cv2.imwrite(tex_path, bgr)
        
        # Calculate 3D position
        theta = (cx * 2.0 * math.pi) - math.pi
        phi = (0.5 - cy) * math.pi
        
        dir_x = math.cos(phi) * math.sin(theta)
        dir_y = math.sin(phi)
        dir_z = math.cos(phi) * math.cos(theta)
        
        # Light width/height in 3D (approximate based on radians)
        width_rad = (nx2 - nx1) * 2.0 * math.pi
        height_rad = (ny2 - ny1) * math.pi
        radius = 100.0  # default distance
        
        light_width = max(width_rad * radius, 0.1)
        light_height = max(height_rad * radius, 0.1)
        
        # Write USD generation script
        script_lines.append(f"# --- Mask: {mask.name} ---")
        light_path = f"/lights/{safe_name}"
        if mask.shape == "Ellipse":
            script_lines.append(f"light = UsdLux.SphereLight.Define(stage, '{light_path}')")
            script_lines.append(f"light.GetRadiusAttr().Set({max(light_width, light_height) / 2.0})")
        else:
            script_lines.append(f"light = UsdLux.RectLight.Define(stage, '{light_path}')")
            script_lines.append(f"light.GetWidthAttr().Set({light_width})")
            script_lines.append(f"light.GetHeightAttr().Set({light_height})")
            
        script_lines.append(f"light.GetTextureFileAttr().Set(r'{tex_path.replace(chr(92), '/')}')")
        
        # Place and orient light using LookAt inverse matrix
        script_lines.append(f"xform = UsdGeom.Xformable(light)")
        script_lines.append(f"xform.ClearXformOpOrder()")
        script_lines.append(f"eye = Gf.Vec3d({dir_x*radius}, {dir_y*radius}, {dir_z*radius})")
        script_lines.append(f"center = Gf.Vec3d(0, 0, 0)")
        script_lines.append(f"up = Gf.Vec3d(0, 1, 0)")
        # In Houdini/USD, look-at inverse maps a camera (looking down -Z) to point at origin
        script_lines.append(f"mat = Gf.Matrix4d().SetLookAt(eye, center, up).GetInverse()")
        script_lines.append(f"xform.AddTransformOp().Set(mat)")
        script_lines.append("")

    script_path = os.path.join(export_dir, "export_masks_to_solaris.py")
    with open(script_path, "w") as f:
        f.write("\n".join(script_lines))
        
    return script_path

def export_extracted_lights(hdri_array, export_dir, hdri_file_path, num_lights=1, mask_radius_px=100):
    from hdri_match.analysis.light_extractor import LightExtractor
    import json
    
    lights = LightExtractor.extract_lights(hdri_array, num_lights, mask_radius_px)
    if not lights:
        return None, None
        
    # 1. Export JSON with Light Data
    json_path = os.path.join(export_dir, "extracted_lights.json")
    with open(json_path, 'w') as f:
        json.dump(lights, f, indent=4)
        
    # 2. Export Nuke Script for Patching
    h, w = hdri_array.shape[:2]
    nk_path = os.path.join(export_dir, "patch_hdri.nk")
    
    nk_lines = [
        "#! Nuke - nx",
        f'Read {{',
        f' file "{hdri_file_path.replace(chr(92), "/")}"',
        f' format "{w} {h} 0 0 {w} {h} 1 "',
        f' name Read_HDRI',
        f'}}',
        "set N_read [stack 0]",
        "Dot {",
        " name Dot1",
        "}",
        "set N_dot [stack 0]",
        f"Blur {{",
        f" size {int(mask_radius_px * 1.5)}",
        f" name Blur_Patch",
        f"}}",
        "set N_blur [stack 0]",
    ]
    
    radial_nodes = []
    for i, light in enumerate(lights):
        cx, cy = light['pos_xy']
        ny = h - cy  # Nuke Y is up
        r = light['radius_px']
        
        # area {left bottom right top}
        area_str = f"{cx-r} {ny-r} {cx+r} {ny+r}"
        
        nk_lines.extend([
            "push 0",
            f"Radial {{",
            f" area {{{area_str}}}",
            f" softness 0",
            f" name Radial_Hole_{i+1}",
            f"}}"
        ])
        radial_nodes.append(f"Radial_Hole_{i+1}")
        
    if len(radial_nodes) > 1:
        nk_lines.extend([
            f"Merge2 {{",
            f" inputs {len(radial_nodes)}",
            f" operation max",
            f" name Merge_Radials",
            f"}}"
        ])
        
    nk_lines.extend([
        "push $N_blur",
        "push $N_dot",
        "Merge2 {",
        " inputs 2+1",
        " operation copy",
        " name Merge_Patch",
        "}",
        "Write {",
        " file \"[file dirname [value root.name]]/patched_hdri.exr\"",
        " file_type exr",
        " name Write_Patched",
        "}"
    ])
    
    with open(nk_path, 'w') as f:
        f.write("\n".join(nk_lines))
        
    # 3. Export USD/Solaris script for the lights
    solaris_path = os.path.join(export_dir, "extracted_lights_solaris.py")
    solaris_lines = [
        "import hou",
        "from pxr import UsdLux, Gf, UsdGeom",
        "node = hou.pwd()",
        "stage = node.editableStage()",
        "if not stage:",
        "    print('Please run inside a Python LOP')",
        "    pass",
        ""
    ]
    for i, light in enumerate(lights):
        safe_name = f"Extracted_{light['name']}"
        solaris_lines.append(f"# --- {safe_name} ---")
        solaris_lines.append(f"light = UsdLux.SphereLight.Define(stage, '/lights/{safe_name}')")
        solaris_lines.append(f"light.GetRadiusAttr().Set({light['angular_size_deg']}) # approximate scale")
        solaris_lines.append(f"light.GetColorAttr().Set(Gf.Vec3f({light['color'][0]}, {light['color'][1]}, {light['color'][2]}))")
        solaris_lines.append(f"light.GetIntensityAttr().Set({light['intensity']})")
        solaris_lines.append(f"xform = UsdGeom.Xformable(light)")
        solaris_lines.append(f"xform.ClearXformOpOrder()")
        
        # Position
        dir_x, dir_y, dir_z = light['vector']
        radius = 1000.0
        solaris_lines.append(f"eye = Gf.Vec3d({dir_x*radius}, {dir_y*radius}, {dir_z*radius})")
        solaris_lines.append(f"center = Gf.Vec3d(0, 0, 0)")
        solaris_lines.append(f"up = Gf.Vec3d(0, 1, 0)")
        solaris_lines.append(f"mat = Gf.Matrix4d().SetLookAt(eye, center, up).GetInverse()")
        solaris_lines.append(f"xform.AddTransformOp().Set(mat)")
        solaris_lines.append("")
        
    with open(solaris_path, 'w') as f:
        f.write("\n".join(solaris_lines))
        
    return nk_path, solaris_path


def export_camera_to_solaris(plate_path, export_dir):
    from hdri_match.io.exr_pure import read_multipart_exr_parts
    import struct
    import os
    
    parts = read_multipart_exr_parts(plate_path)
    if not parts:
        return None
        
    attrs = parts[0].get('attrs', {})
    
    # Fuzzy search for attributes to handle exr/cameraTransform, Nuke/cameraTransform, etc.
    cam_matrix = None
    focal_length = None
    aperture = None
    is_world_to_cam = False
    
    for k, v in attrs.items():
        k_lower = k.lower()
        if 'cameratransform' in k_lower:
            mat_bytes = v[1]
            if len(mat_bytes) >= 64:
                cam_matrix = struct.unpack('<16f', mat_bytes[:64])
                is_world_to_cam = False
        elif 'worldtocamera' in k_lower and not cam_matrix:
            mat_bytes = v[1]
            if len(mat_bytes) >= 64:
                cam_matrix = struct.unpack('<16f', mat_bytes[:64])
                is_world_to_cam = True
                
        elif 'focallength' in k_lower:
            # Often float (4 bytes)
            if len(v[1]) >= 4:
                focal_length = struct.unpack('<f', v[1][:4])[0]
        elif 'aperture' in k_lower:
            if len(v[1]) >= 4:
                aperture = struct.unpack('<f', v[1][:4])[0]

    if not cam_matrix and focal_length is None and aperture is None:
        return None
        
    script_path = os.path.join(export_dir, "export_camera_to_solaris.py")
    script_lines = [
        "import hou",
        "from pxr import Usd, UsdGeom, Gf",
        "node = hou.pwd()",
        "stage = node.editableStage()",
        "if not stage:",
        "    print('Please run inside a Python LOP')",
        "    pass",
        "",
        "cam_path = '/cameras/plate_cam'",
        "cam = UsdGeom.Camera.Define(stage, cam_path)",
    ]
    
    if cam_matrix:
        script_lines.append(f"mat = Gf.Matrix4d(")
        for i in range(4):
            r = cam_matrix[i*4:(i+1)*4]
            script_lines.append(f"    {r[0]}, {r[1]}, {r[2]}, {r[3]},")
        script_lines.append(")")
        if is_world_to_cam:
            script_lines.append("mat = mat.GetInverse()") # Convert world-to-cam to local-to-world
        
        script_lines.append("xform = UsdGeom.Xformable(cam)")
        script_lines.append("xform.ClearXformOpOrder()")
        script_lines.append("xform.AddTransformOp().Set(mat)")
        
    if focal_length is not None:
        script_lines.append(f"cam.GetFocalLengthAttr().Set({focal_length})")
    if aperture is not None:
        # Houdini USD horizontalAperture is in mm usually, and cameraAperture metadata is typically horizontal in mm
        script_lines.append(f"cam.GetHorizontalApertureAttr().Set({aperture})")
        
    script_lines.append("print('Camera extracted to', cam_path)")
    
    with open(script_path, 'w') as f:
        f.write("\n".join(script_lines))
        
    return script_path

def export_lookdev_balls_solaris(export_dir):
    import os
    script_path = os.path.join(export_dir, "create_lookdev_balls.py")
    script_lines = [
        "import hou",
        "from pxr import Usd, UsdGeom, Gf, Sdf, UsdShade",
        "node = hou.pwd()",
        "stage = node.editableStage()",
        "if not stage:",
        "    print('Please run inside a Python LOP')",
        "    pass",
        "",
        "# Find the first camera in the scene to parent the balls to",
        "cam_path = ''",
        "for prim in stage.TraverseAll():",
        "    if prim.IsA(UsdGeom.Camera):",
        "        cam_path = prim.GetPath().pathString",
        "        break",
        "if not cam_path:",
        "    cam_path = '/cameras/Plate_Camera1'",
        "",
        "balls_path = cam_path + '/lookdev_balls'",
        "balls_xform = UsdGeom.Xform.Define(stage, balls_path)",
        "",
        "# Position at the top left of the camera view (Z=-50 units away, X=-15 left, Y=10 up)",
        "UsdGeom.Xformable(balls_xform).AddTranslateOp().Set(Gf.Vec3d(-15, 10, -50))",
        "",
        "# 1. Create Chrome Ball",
        "chrome_path = balls_path + '/chrome'",
        "chrome_sphere = UsdGeom.Sphere.Define(stage, chrome_path)",
        "chrome_sphere.GetRadiusAttr().Set(3.0)",
        "UsdGeom.Xformable(chrome_sphere).AddTranslateOp().Set(Gf.Vec3d(-3.5, 0, 0))",
        "",
        "# 2. Create Grey Ball",
        "grey_path = balls_path + '/grey'",
        "grey_sphere = UsdGeom.Sphere.Define(stage, grey_path)",
        "grey_sphere.GetRadiusAttr().Set(3.0)",
        "UsdGeom.Xformable(grey_sphere).AddTranslateOp().Set(Gf.Vec3d(3.5, 0, 0))",
        "",
        "# 3. Create Materials",
        "mtl_path = balls_path + '/materials'",
        "UsdGeom.Scope.Define(stage, mtl_path)",
        "",
        "# Chrome Material",
        "chrome_mtl_path = mtl_path + '/chrome_mtl'",
        "chrome_mtl = UsdShade.Material.Define(stage, chrome_mtl_path)",
        "chrome_shader = UsdShade.Shader.Define(stage, chrome_mtl_path + '/shader')",
        "chrome_shader.CreateIdAttr('UsdPreviewSurface')",
        "chrome_shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.0, 0.0, 0.0))",
        "chrome_shader.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(1.0)",
        "chrome_shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(0.0)",
        "chrome_mtl.CreateSurfaceOutput().ConnectToSource(chrome_shader.ConnectableAPI(), 'surface')",
        "",
        "# Grey Material (18% Grey)",
        "grey_mtl_path = mtl_path + '/grey_mtl'",
        "grey_mtl = UsdShade.Material.Define(stage, grey_mtl_path)",
        "grey_shader = UsdShade.Shader.Define(stage, grey_mtl_path + '/shader')",
        "grey_shader.CreateIdAttr('UsdPreviewSurface')",
        "grey_shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.18, 0.18, 0.18))",
        "grey_shader.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(0.0)",
        "grey_shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(0.6)",
        "grey_mtl.CreateSurfaceOutput().ConnectToSource(grey_shader.ConnectableAPI(), 'surface')",
        "",
        "# Bind Materials",
        "UsdShade.MaterialBindingAPI.Apply(chrome_sphere.GetPrim()).Bind(chrome_mtl)",
        "UsdShade.MaterialBindingAPI.Apply(grey_sphere.GetPrim()).Bind(grey_mtl)",
        "print('Lookdev balls created at', balls_path)"
    ]
    
    with open(script_path, 'w') as f:
        f.write("\n".join(script_lines))
        
    return script_path
