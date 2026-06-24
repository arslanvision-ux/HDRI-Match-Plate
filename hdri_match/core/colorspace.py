import numpy as np

try:
    import PyOpenColorIO as OCIO
except ImportError:
    OCIO = None

class ColorSpaceManager:
    """Manages OCIO color space transformations."""
    
    def __init__(self, config_path=None):
        self.config_path = config_path
        self._printed_errors = set()
        if OCIO is None:
            self.config = None
            print("PyOpenColorIO not found. Running in fallback mode (No color management).")
        else:
            try:
                if config_path:
                    self.config = OCIO.Config.CreateFromFile(config_path)
                else:
                    self.config = OCIO.GetCurrentConfig()
                    
                # Reject dummy fallback config from OCIO
                if self.config:
                    spaces = list(self.config.getColorSpaces())
                    if len(spaces) == 1 and spaces[0].getName() == "raw":
                        print("Detected PyOpenColorIO dummy config. Falling back to internal color management.")
                        self.config = None
                        
            except Exception as e:
                print(f"Failed to load OCIO config: {e}")
                self.config = None
                
        if self.config is None:
            print("[ColorSpaceManager] Using Built-In mathematical fallback (ACEScg, sRGB, Rec.709).")
            self._builtin_spaces = ["Linear - sRGB", "ACEScg", "sRGB", "Rec.709"]
        else:
            self._builtin_spaces = []
                
    def get_color_spaces(self):
        """Returns a list of available color spaces."""
        if not self.config:
            return self._builtin_spaces
        return [cs.getName() for cs in self.config.getColorSpaces()]

    def get_display_views(self):
        """Returns a list of views for the default display."""
        if not self.config:
            return ["sRGB", "Raw"]
        
        try:
            display = self.config.getDefaultDisplay()
            views_raw = self.config.getViews(display)
            
            views = []
            if isinstance(views_raw, str):
                views = [v.strip() for v in views_raw.split(',') if v.strip()]
            else:
                for v in views_raw:
                    views.append(str(v))
                    
            if not views:
                # Fallback to output color spaces
                spaces = [cs.getName() for cs in self.config.getColorSpaces()]
                outputs = [s for s in spaces if "Output" in s or "sRGB" in s]
                return outputs if outputs else ["sRGB", "Raw"]
            return views
        except Exception as e:
            print(f"Error getting display views: {e}")
            return ["sRGB", "Raw"]
            
    def apply_display_transform(self, image: np.ndarray, src_space: str, view: str = "sRGB") -> np.ndarray:
        """Applies a display transform using OCIO (e.g. RRT+ODT for ACES) or fallback."""
        if not self.config:
            if view == "sRGB" and "acescg" in src_space.lower():
                # Built-in ACES filmic fallback
                img = np.copy(image)
                a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
                img = (img * (a * img + b)) / (img * (c * img + d) + e)
                img = np.clip(img, 0.0, 1.0)
                np.power(img, 1.0 / 2.2, out=img)
                return img
            if view == "Raw" or view == "Linear":
                return np.clip(image, 0.0, 1.0)
            return self._fallback_transform(image, src_space, "srgb_display")
            
        try:
            display = self.config.getDefaultDisplay()
            
            # Use DisplayViewTransform (OCIO v2) or DisplayTransform (OCIO v1)
            try:
                dt = OCIO.DisplayViewTransform()
                dt.setSrc(src_space)
                dt.setDisplay(display)
                dt.setView(view)
            except AttributeError:
                dt = OCIO.DisplayTransform()
                dt.setInputColorSpaceName(src_space)
                dt.setDisplay(display)
                dt.setView(view)
                
            processor = self.config.getProcessor(dt)
            cpu = processor.getDefaultCPUProcessor()
            
            h, w, c = image.shape
            img_flat = np.ascontiguousarray(image, dtype=np.float32).flatten()
            
            if c == 3:
                try:
                    cpu.applyRGB(img_flat)
                except AttributeError:
                    rgba = np.ones((h * w, 4), dtype=np.float32)
                    rgba[:, :3] = image.reshape(-1, 3)
                    cpu.applyRGBA(rgba.flatten())
                    img_flat = rgba[:, :3].flatten()
                return img_flat.reshape((h, w, 3))
            elif c == 4:
                cpu.applyRGBA(img_flat)
                return img_flat.reshape((h, w, 4))
                
            return image
        except Exception as e:
            print(f"DisplayViewTransform failed, falling back to direct transform: {e}")
            return self.transform_image(image, src_space, view)
        
    def transform_image(self, image: np.ndarray, src_space: str, dst_space: str) -> np.ndarray:
        """
        Transforms a numpy array from src_space to dst_space using OCIO or Built-in Math.
        """
        if src_space == dst_space:
            return image
            
        if not self.config:
            return self._fallback_transform(image, src_space, dst_space)
            
        try:
            # Handle common aliases if the exact name isn't found
            def resolve_space(space_name):
                if self.config.getColorSpace(space_name):
                    return space_name
                    
                aliases = {
                    "Linear": ["scene_linear", "linear", "Utility - Linear - sRGB", "Utility - Linear - Rec.709", "lin_srgb", "ACES - ACEScg"],
                    "sRGB": ["srgb", "Utility - sRGB - Texture", "Output - sRGB", "sRGB - Texture"],
                    "Rec709": ["rec709", "Utility - Rec.709 - Texture", "Output - Rec.709", "Rec.709 - Texture"],
                    "ACEScg": ["ACES - ACEScg", "acescg", "cg"],
                    "ACES2065-1": ["ACES - ACES2065-1", "aces2065-1"]
                }
                
                for attempt in aliases.get(space_name, []):
                    if self.config.getColorSpace(attempt):
                        return attempt
                return None # Signal failure
                
            real_src = resolve_space(src_space)
            real_dst = resolve_space(dst_space)
            
            if not real_src or not real_dst:
                missing = src_space if not real_src else dst_space
                if missing not in self._printed_errors:
                    print(f"OCIO Bypassed: Color space '{missing}' not found in current config.")
                    self._printed_errors.add(missing)
                return image
            
            # Create a processor
            processor = self.config.getProcessor(real_src, real_dst)
            cpu = processor.getDefaultCPUProcessor()
            
            h, w, c = image.shape
            
            # OCIO CPU processor typically prefers interleaved RGB or RGBA float32 arrays
            if c == 3:
                # Depending on OCIO version, applyRGB or applyRGBA is used.
                # Here we assume a modern OCIO version that supports applyRGB.
                img_flat = np.ascontiguousarray(image, dtype=np.float32).flatten()
                try:
                    cpu.applyRGB(img_flat)
                    return img_flat.reshape((h, w, 3))
                except AttributeError:
                    # Fallback for older OCIO requiring RGBA
                    rgba = np.ones((h * w, 4), dtype=np.float32)
                    rgba[:, :3] = image.reshape(-1, 3)
                    cpu.applyRGBA(rgba.flatten())
                    return rgba[:, :3].reshape((h, w, 3))
            elif c == 4:
                img_flat = np.ascontiguousarray(image, dtype=np.float32).flatten()
                cpu.applyRGBA(img_flat)
                return img_flat.reshape((h, w, 4))
                
            return image

        except Exception as e:
            error_msg = str(e)
            if error_msg not in self._printed_errors:
                print(f"OCIO Transform failed: {error_msg}")
                self._printed_errors.add(error_msg)
            return self._fallback_transform(image, src_space, dst_space)

    def _fallback_transform(self, image: np.ndarray, src: str, dst: str) -> np.ndarray:
        """Built-in mathematical fallback for ACEScg, sRGB, and Rec709."""
        if src == dst: return image
        
        # Determine normalized source/dest
        def norm(s):
            s = s.lower()
            if "acescg" in s: return "acescg"
            if "srgb" in s and "linear" not in s: return "srgb_display"
            if "709" in s and "linear" not in s: return "rec709_display"
            return "linear_srgb" # Default linear space
            
        src_n = norm(src)
        dst_n = norm(dst)
        
        if src_n == dst_n: return image
        
        # 1. Convert to Linear sRGB
        out = np.copy(image)
        has_alpha = out.shape[-1] == 4
        rgb = out[..., :3]
        
        if src_n == "acescg":
            # ACEScg to Linear sRGB Matrix
            M = np.array([
                [ 1.705051, -0.621864, -0.083187],
                [-0.130256,  1.140803, -0.010547],
                [-0.024007, -0.128968,  1.152975]
            ], dtype=np.float32)
            rgb = np.dot(rgb, M.T)
        elif src_n == "srgb_display":
            # Inverse sRGB OETF
            rgb = np.where(rgb <= 0.04045, rgb / 12.92, np.power(np.clip((rgb + 0.055) / 1.055, 0, None), 2.4))
        elif src_n == "rec709_display":
            # Inverse Rec.709 OETF
            rgb = np.where(rgb < 0.081, rgb / 4.5, np.power(np.clip((rgb + 0.099) / 1.099, 0, None), 1.0 / 0.45))
            
        # 2. Convert from Linear sRGB to Dest
        if dst_n == "acescg":
            # Linear sRGB to ACEScg Matrix
            M = np.array([
                [0.613097, 0.339523, 0.047379],
                [0.070194, 0.916354, 0.013452],
                [0.020616, 0.109570, 0.869815]
            ], dtype=np.float32)
            rgb = np.dot(rgb, M.T)
        elif dst_n == "srgb_display":
            # sRGB OETF
            rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(np.clip(rgb, 0, None), 1/2.4) - 0.055)
        elif dst_n == "rec709_display":
            # Rec.709 OETF
            rgb = np.where(rgb < 0.018, rgb * 4.5, 1.099 * np.power(np.clip(rgb, 0, None), 0.45) - 0.099)
            
        out[..., :3] = rgb
        return out
