import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import re
import numpy as np


# ---------------------------------------------------------------------------
# Generic single-layer image loader
# ---------------------------------------------------------------------------

def load_exr_to_numpy(file_path: str) -> np.ndarray:
    """
    Reads a 16/32-bit EXR, HDR, or RAW image into a float32 RGB NumPy array.
    Attempts multiple backends in order: rawpy → OpenCV → ImageIO → OpenEXR.
    """
    errors = []
    ext = os.path.splitext(file_path)[1].lower()

    # --- RAW formats ---
    if ext in ('.arw', '.cr2', '.nef', '.dng', '.raw'):
        try:
            import rawpy
            with rawpy.imread(file_path) as raw:
                img = raw.postprocess(
                    gamma=(1, 1), no_auto_bright=True,
                    output_bps=16, use_camera_wb=True)
                return img.astype(np.float32) / 65535.0
        except Exception as e:
            errors.append(f"rawpy: {e}")

    # --- OpenCV (handles EXR + HDR natively when env var is set) ---
    try:
        import cv2
        img = cv2.imread(file_path, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
        if img is not None:
            if len(img.shape) == 3 and img.shape[2] >= 3:
                img = cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2RGB)
            orig_dtype = img.dtype
            img = img.astype(np.float32)
            if orig_dtype == np.uint8:
                img /= 255.0
            elif orig_dtype == np.uint16:
                img /= 65535.0
            return img
        errors.append("cv2.imread returned None")
    except Exception as e:
        errors.append(f"OpenCV: {e}")

    # --- ImageIO ---
    try:
        import imageio.v3 as iio
        img = iio.imread(file_path)
        orig_dtype = img.dtype
        img = img.astype(np.float32)
        if orig_dtype == np.uint8:
            img /= 255.0
        elif orig_dtype == np.uint16:
            img /= 65535.0
        return img
    except Exception as e:
        errors.append(f"imageio: {e}")

    # --- OpenEXR (last resort, C-binding may not be installed) ---
    try:
        import OpenEXR
        import Imath
        if OpenEXR.isOpenExrFile(file_path):
            exr_file = OpenEXR.InputFile(file_path)
            header = exr_file.header()
            dw = header['dataWindow']
            width = dw.max.x - dw.min.x + 1
            height = dw.max.y - dw.min.y + 1
            pt = Imath.PixelType(Imath.PixelType.FLOAT)
            r = np.frombuffer(exr_file.channel('R', pt), dtype=np.float32).reshape(height, width)
            g = np.frombuffer(exr_file.channel('G', pt), dtype=np.float32).reshape(height, width)
            b = np.frombuffer(exr_file.channel('B', pt), dtype=np.float32).reshape(height, width)
            return np.stack([r, g, b], axis=-1)
        errors.append("OpenEXR: file did not validate")
    except Exception as e:
        errors.append(f"OpenEXR: {e}")

    raise ImportError(f"All backends failed for '{file_path}':\n" + "\n".join(f"  • {e}" for e in errors))


# ---------------------------------------------------------------------------
# Multi-channel AOV loader for CG Light Passes
# ---------------------------------------------------------------------------

# Built-in Nuke / OpenEXR layers that should never be treated as light AOVs.
_IGNORED_LAYERS = frozenset(layer.lower() for layer in (
    'rgba', 'rgb', 'alpha', 'z', 'depth', 'motion', 'forward', 'backward',
))


# Determine at module load time whether we're running inside Nuke.
# This avoids calling 'import nuke' repeatedly and — critically — prevents
# *any* code path from reaching 'import OpenEXR' (which segfaults Nuke
# due to native DLL conflicts) when running inside Nuke.
_IN_NUKE = False
try:
    import nuke
    _IN_NUKE = True
except ImportError:
    pass


def _resolve_nuke_colorspace(requested: str) -> str:
    """
    Maps a generic OCIO / user-facing colorspace name (e.g. 'ACEScg',
    'ACES2065-1', 'Linear', 'sRGB') to the matching Nuke LUT name.

    Nuke's LUT names depend on the OCIO config loaded and typically look
    like 'ACES - ACEScg', 'scene_linear', 'Output - sRGB', etc.
    We do a case-insensitive substring search through all registered
    colorspaces in Nuke and return the best match.

    Falls back to 'scene_linear' (then to the raw string) if nothing matches.
    """
    if not _IN_NUKE:
        return requested

    import nuke

    # Get all colorspace names registered in the current Nuke session
    try:
        all_cs = nuke.colorspaces()
        if hasattr(all_cs, 'keys'):
            cs_names = list(all_cs.keys())
        else:
            # Older Nuke returns a list of strings
            cs_names = list(all_cs)
    except Exception:
        # nuke.colorspaces() may not exist in very old builds — try knob enumeration
        try:
            tmp = nuke.nodes.Read()
            knob = tmp['colorspace']
            cs_names = [knob.enumName(i) for i in range(knob.numValues())]
            nuke.delete(tmp)
        except Exception:
            return requested

    if not cs_names:
        return requested

    req_lower = requested.lower().strip()

    # 1) Exact match (case-insensitive)
    for name in cs_names:
        if name.lower() == req_lower:
            return name

    # 2) Substring match — e.g. 'ACEScg' matches 'ACES - ACEScg'
    #    Prefer shorter names (more specific) when multiple match.
    candidates = [n for n in cs_names if req_lower in n.lower()]
    if candidates:
        candidates.sort(key=len)
        return candidates[0]

    # 3) Common alias table for typical ACES configs
    _ALIASES = {
        'acescg':     ['scene_linear', 'aces - acescg', 'acescg', 'linear'],
        'aces2065-1': ['aces2065-1', 'aces - aces2065-1'],
        'linear':     ['scene_linear', 'linear', 'acescg'],
        'srgb':       ['srgb', 'output - srgb'],
        'rec709':     ['rec709', 'output - rec.709'],
    }
    aliases = _ALIASES.get(req_lower, [])
    for alias in aliases:
        for name in cs_names:
            if alias in name.lower():
                return name

    # 4) Last resort: try 'scene_linear', then return raw string
    for name in cs_names:
        if 'scene_linear' in name.lower():
            return name

    return requested


def _is_rgb_component(comp_name: str) -> str:
    """Returns 'R', 'G', or 'B' if comp_name is a recognised RGB component, else None."""
    c = comp_name.lower()
    if c in ('r', 'red'):
        return 'R'
    elif c in ('g', 'green'):
        return 'G'
    elif c in ('b', 'blue'):
        return 'B'
    return None


def _nuke_channel_to_components(all_channels: list, prefixes: tuple = ()) -> dict:
    """
    Parses Nuke's flat channel list into a dict of {layer: {comp: channel_name}}.
    
    Example:
      'key_01.red'       → layer='key_01', comp='R', channel='key_01.red'
      'key_01.0'         → single-channel, ignored
      'rgba.red'         → built-in layer 'rgba', skipped
    """
    aov_map = {}
    for ch in all_channels:
        parts = ch.rsplit('.', 1)
        if len(parts) != 2:
            continue
        layer, comp_raw = parts

        if prefixes:
            matched_prefix = None
            for p in prefixes:
                if p.lower() in layer.lower():
                    matched_prefix = p
                    break
            if not matched_prefix:
                continue

            # Skip built-in layers ONLY if they aren't explicitly requested
            if layer.lower() in _IGNORED_LAYERS:
                if layer.lower() != matched_prefix.lower():
                    continue
        else:
            # Skip built-in layers (rgba, rgb, z, depth, alpha, etc.)
            if layer.lower() in _IGNORED_LAYERS:
                continue

        # Map component name to R/G/B
        comp = _is_rgb_component(comp_raw)
        if comp is None:
            continue  # skip alpha, z, 0, 1, etc.

        aov_map.setdefault(layer, {})[comp] = ch

    return aov_map


def _exr_channel_to_components(all_channels: list, prefixes: tuple = ()) -> dict:
    """
    Converts an EXR channel list to {layer: {comp: channel_name}}.

    Arnold / OpenEXR naming convention: 'key_01.R', 'fill_01.G', etc.
    Also handles optional prefix: 'light_key_01.R' → layer='light_key_01'

    Built-in EXR layers (rgba, z, depth) are skipped.
    """
    aov_map = {}
    for ch in all_channels:
        parts = ch.rsplit('.', 1)
        if len(parts) != 2:
            continue
        layer, comp_raw = parts

        # Optionally filter by keywords/substrings
        if prefixes:
            # Always pass shadow and reflection AOVs regardless of light prefixes
            layer_l = layer.lower()
            if not any(p.lower() in layer_l for p in prefixes):
                if "shadow" not in layer_l and "refl" not in layer_l:
                    continue

        # Skip built-in layers
        if layer.lower() in _IGNORED_LAYERS:
            continue

        comp = _is_rgb_component(comp_raw)
        if comp is None:
            continue

        aov_map.setdefault(layer, {})[comp] = ch

    return aov_map



def load_cg_alpha_from_exr(file_path: str) -> np.ndarray:
    """
    Reads the alpha channel (rgba.alpha or A) from a multi-channel EXR.

    Returns:
        float32 (H, W) alpha array, or None if no alpha channel is found.
    """
    def _find_alpha_channel(channels: list) -> str:
        """Looks for an alpha channel name in the channel list."""
        for ch in channels:
            parts = ch.rsplit('.', 1)
            if len(parts) == 2 and parts[0].lower() in ('rgba', 'rgb', ''):
                if parts[1].lower() in ('a', 'alpha'):
                    return ch
        for ch in channels:
            if ch.lower() in ('a', 'alpha'):
                return ch
        return None

    # --- Standalone: OpenEXR binding FIRST (handles all compressions reliably) ---
    try:
        if _IN_NUKE: raise Exception("Nuke segfault protection")
        import OpenEXR
        import Imath
        if not OpenEXR.isOpenExrFile(file_path):
            return None
        exr_file = OpenEXR.InputFile(file_path)
        header = exr_file.header()
        dw = header['dataWindow']
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1
        channels = list(header['channels'].keys())
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        a_ch = _find_alpha_channel(channels)
        if a_ch is not None:
            return np.frombuffer(exr_file.channel(a_ch, pt), np.float32).reshape(height, width)
        return None
    except Exception as e:
        print(f"[Alpha] OpenEXR failed: {e}")

    # --- Standalone fallback: pure multi-part reader ---
    try:
        from hdri_match.io.exr_pure import read_multipart_exr_parts, read_part_alpha
        parts = read_multipart_exr_parts(file_path)
        if parts:
            for p in parts:
                has_dot = any('.' in ch for ch, _ in p['channels'])
                if not has_dot:
                    alpha = read_part_alpha(file_path, p)
                    if alpha is not None:
                        print(f"[Alpha] Loaded from part '{p['name']}': "
                              f"min={alpha.min():.4f}  max={alpha.max():.4f}")
                        return alpha.astype(np.float32)
    except Exception as e:
        print(f"[Alpha] Pure reader failed: {e}")

    return None



def _find_rgb_channels(channels: list, preferred_layers: tuple = ('rgba', 'rgb', '')):
    """Returns channel names for an RGB beauty layer, preferring rgba/rgb."""
    for layer in preferred_layers:
        comps = {}
        for ch in channels:
            if layer:
                parts = ch.rsplit('.', 1)
                if len(parts) != 2 or parts[0].lower() != layer:
                    continue
                comp = _is_rgb_component(parts[1])
            else:
                if '.' in ch:
                    continue
                comp = _is_rgb_component(ch)
            if comp is not None:
                comps[comp] = ch
        if 'R' in comps and 'G' in comps and 'B' in comps:
            return comps
    return None


def load_beauty_from_exr(file_path: str) -> np.ndarray:
    """
    Reads the final RGB beauty from a multi-channel EXR.

    Supports:
    * Single-part EXR: looks for rgba/rgb/bare-RGB channels.
    * Multi-part EXR (Houdini Karma): reads the FIRST part that has R,G,B
      channels (regardless of part name — 'C', 'beauty', 'rgba', 'rgb', etc.).

    Falls back to cv2 / load_exr_to_numpy if pure reader fails.
    """
    # --- Nuke path ---
    if False:
        try:
            import shutil, tempfile
            from hdri_match.io.exr_pure import read_uncompressed_exr

            rd = nuke.nodes.Read(file=file_path)
            rd['raw'].setValue(True)
            all_channels = rd.channels()
            comps = _find_rgb_channels(all_channels)
            if comps is None:
                nuke.delete(rd)
                return load_exr_to_numpy(file_path)

            expr = nuke.nodes.Expression(inputs=[rd],
                                         expr0=comps['R'],
                                         expr1=comps['G'],
                                         expr2=comps['B'])
            temp_dir = tempfile.mkdtemp(prefix="hdri_match_beauty_")
            temp_path = os.path.join(temp_dir, "beauty.exr").replace('\\', '/')
            write = nuke.nodes.Write(
                file=temp_path, file_type='exr', channels='rgb', inputs=[expr])
            write['compression'].setValue('none')
            nuke.execute(write, 1, 1)
            raw = read_uncompressed_exr(temp_path)
            nuke.delete(write); nuke.delete(expr); nuke.delete(rd)
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            if raw is not None and raw.ndim >= 2:
                arr = raw.astype(np.float32)
                if arr.ndim == 2:
                    arr = np.stack([arr, arr, arr], axis=-1)
                return arr[..., :3]
        except Exception:
            pass
        return load_exr_to_numpy(file_path)

    # --- Standalone: use pure multi-part reader ---
    try:
        from hdri_match.io.exr_pure import read_multipart_exr_parts, read_part_as_rgb
        parts = read_multipart_exr_parts(file_path)
        if parts:
            # Beauty = first part that has R, G, B channels.
            # In Karma multi-part EXRs part 0 is always the full beauty
            # (named 'C', 'beauty', 'rgba', or anything else).
            for p in parts:
                rgb = read_part_as_rgb(file_path, p)
                if rgb is not None:
                    print(f"[Beauty] Loaded part '{p['name']}' as beauty: "
                          f"shape={rgb.shape}  min={rgb.min():.4f}  max={rgb.max():.4f}")
                    return rgb.astype(np.float32)
    except Exception as e:
        print(f"[Beauty] Pure reader failed: {e}")

    # --- Last resort: cv2 (only works for uncompressed single-part) ---
    return load_exr_to_numpy(file_path)


def load_light_aovs_from_exr(file_path: str, prefixes: tuple = ("light_",),
                              input_colorspace: str = "ACEScg") -> dict:
    """
    Reads a multi-channel EXR and extracts light AOV layers into
    {layer_name: float32 RGB array}.

    Any layer that has R, G, B sub-channels is treated as a light AOV, EXCEPT
    for known built-in layers (rgba, rgb, z, depth, alpha, motion, etc.).

    The optional *prefixes* filter (default: 'light_') is applied when the EXR
    uses a naming convention like 'light_key_01.R'. Bare names like
    'key_01.red' are accepted regardless of prefix.

    Args:
        file_path: Path to multi-channel EXR.
        prefixes: Channel name prefixes to filter by.
        input_colorspace: OCIO colorspace name. Applied to Nuke's Read node
                          so that Shuffle can access all channels correctly.

    Strategy:
      1. **Inside Nuke**: Pure-Python EXR reader (100% Nuke safe!)
      2. **Standalone**: OpenEXR binding (full channel name control).
      3. **Standalone fallback**: pure multi-part reader.
    """
    errors = []

    # --- Pure-Python EXR reader (100% Nuke safe!) ---
    try:
        from hdri_match.io.exr_pure import read_multipart_exr_parts, read_part_as_rgb
        parts = read_multipart_exr_parts(file_path)
        lights = {}
        for p in parts:
            cnames = [c[0] for c in p['channels']]
            p_map = _exr_channel_to_components(cnames, prefixes=prefixes)
            for layer_name, comps in p_map.items():
                if 'R' in comps and 'G' in comps and 'B' in comps:
                    arr = read_part_as_rgb(file_path, p, comps['R'], comps['G'], comps['B'])
                    if arr is not None:
                        lights[layer_name] = arr
        if lights:
            return lights
        errors.append("Pure reader: No matching light AOVs found.")
    except Exception as e:
        errors.append(f"Pure reader failed: {e}")
    # --- Standalone: OpenEXR binding FIRST (handles all compressions reliably) ---
    try:
        if _IN_NUKE: raise Exception("Nuke segfault protection")
        import OpenEXR
        import Imath
        if not OpenEXR.isOpenExrFile(file_path):
            raise ValueError("Not a valid EXR")

        exr_file = OpenEXR.InputFile(file_path)
        header = exr_file.header()
        dw = header['dataWindow']
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1
        channels = list(header['channels'].keys())
        pt = Imath.PixelType(Imath.PixelType.FLOAT)

        aov_map = _exr_channel_to_components(channels, prefixes=prefixes)

        lights = {}
        for layer, comps in aov_map.items():
            if 'R' in comps and 'G' in comps and 'B' in comps:
                r = np.frombuffer(exr_file.channel(comps['R'], pt), np.float32).reshape(height, width)
                g = np.frombuffer(exr_file.channel(comps['G'], pt), np.float32).reshape(height, width)
                b = np.frombuffer(exr_file.channel(comps['B'], pt), np.float32).reshape(height, width)
                lights[layer] = np.stack([r, g, b], axis=-1)

        if lights:
            return lights
        errors.append("OpenEXR: no matching AOV layers found")
    except Exception as e:
        errors.append(f"OpenEXR binding: {e}")

    # --- Standalone fallback: pure multi-part reader ---
    try:
        from hdri_match.io.exr_pure import read_multipart_exr_parts, read_part_as_rgb
        parts = read_multipart_exr_parts(file_path)

        if len(parts) > 1:
            lights = {}
            for p in parts:
                pname = p['name']
                has_dot = any('.' in ch for ch, _ in p['channels'])
                is_bare_rgba = (not has_dot and
                                any(ch.upper() in ('R', 'G', 'B')
                                    for ch, _ in p['channels']))
                if is_bare_rgba:
                    continue
                if prefixes:
                    if not any(px.lower() in pname.lower()
                               for px in prefixes):
                        continue
                if pname.lower() in _IGNORED_LAYERS:
                    continue
                rgb = read_part_as_rgb(file_path, p)
                if rgb is not None:
                    lights[pname] = rgb.astype(np.float32)
            if lights:
                return lights
    except Exception as e:
        errors.append(f"Pure multi-part reader: {e}")

    raise ImportError(
        "Could not extract Light AOVs from EXR. Details:\n" +
        "\n".join(f"  \u2022 {e}" for e in errors)
    )
