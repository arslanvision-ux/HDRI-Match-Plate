import dataclasses
from typing import Optional, Tuple, List
import numpy as np
import uuid

@dataclasses.dataclass
class MaskLayer:
    id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Mask"
    target: str = "HDRI" # "HDRI" or "Plate"
    enabled: bool = True
    shape: str = "Rectangle"
    rect: Optional[Tuple[int, int, int, int]] = None
    points: Optional[list] = None  # List of normalized (x, y) tuples for Polygon/Lasso/Brush shape
    brush_size: int = 20
    feather: float = 0.0
    blur: float = 0.0
    ev_offset: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    blend: float = 1.0
    blend_mode: str = "over" # over, plus, multiply, screen
    mode: str = "Grade"
    
    # 2D Transform
    offset_x: float = 0.0      # Normalized translation X
    offset_y: float = 0.0      # Normalized translation Y
    scale: float = 1.0         # Uniform scale factor
    rotation: float = 0.0      # Rotation in degrees
    
    fill_color: Tuple[float, float, float] = (0.18, 0.18, 0.18)
    chroma_hue: float = 120.0
    chroma_tolerance: float = 0.5
    light_type: str = "Dome"
    # Advanced Keyer Stencil
    stencil_enable: bool = False
    stencil_mode: str = "Luminance"  # "Luminance", "Green Key", "Blue Key"
    stencil_invert: bool = False
    stencil_threshold: float = 0.5
    
    # AI Inpainting
    inpaint_prompt: str = ""
    inpaint_negative_prompt: str = "bad quality, blurry, text, watermark"
    inpaint_backend: str = "ComfyUI (Local)"
    inpaint_api: str = "http://127.0.0.1:8188"
    inpaint_unet: str = ""
    inpaint_clip: str = "qwen_3_8b_fp8mixed.safetensors"
    inpaint_vae: str = "flux2-vae.safetensors"
    inpaint_ckpt: str = "flux-2-klein-9b-fp8mixed.safetensors"
    inpaint_steps: int = 20
    inpaint_cfg: float = 4.0
    inpaint_denoise: float = 1.0
    inpaint_profile: str = "Auto-Detect"
    inpaint_use_custom_wf: bool = False
    inpaint_custom_workflow: str = ""
    inpaint_rembg: bool = False
    inpaint_key_green: bool = False
    inpaint_seed: int = 0
    inpaint_seed_method: str = "randomize"
    inpaint_model_dir: str = r"E:\ComfyUI\ComfyUI\models"
    inpaint_upscaler: str = "None"
    spherical_projection: bool = False
    is_inpainted: bool = False
    inpainted_patch: Optional[np.ndarray] = None
    image_path: str = ""

@dataclasses.dataclass
class ImageState:
    """Holds the current state of images being processed."""
    hdri_path: Optional[str] = None
    plate_path: Optional[str] = None
    
    # Sequence Support
    hdri_sequence: List[str] = dataclasses.field(default_factory=list)
    plate_sequence: List[str] = dataclasses.field(default_factory=list)
    current_frame_index: int = 0

    
    # Raw loaded linear arrays (Full Res)
    hdri_array: Optional[np.ndarray] = None
    plate_array: Optional[np.ndarray] = None
    
    # Proxies for fast UI interaction (Downsampled)
    hdri_proxy: Optional[np.ndarray] = None
    plate_proxy: Optional[np.ndarray] = None
    calibrated_proxy: Optional[np.ndarray] = None
    
    # Calibration References
    macbeth_chart_array: Optional[np.ndarray] = None
    macbeth_matrix: Optional[np.ndarray] = None
    chrome_ball_array: Optional[np.ndarray] = None
    grey_ball_array: Optional[np.ndarray] = None
    
    # Processed arrays
    calibrated_hdri: Optional[np.ndarray] = None
    
    # Metadata and computed parameters
    hdri_yaw: float = 0.0     # 0 to 360 degrees
    ev_offset: float = 0.0
    black_offset: float = 0.0
    apply_exposure_match: bool = False
    hdri_illuminant: Optional[np.ndarray] = None
    plate_illuminant: Optional[np.ndarray] = None
    temperature: float = 0.0  # Blue (-1) to Yellow (1)
    tint: float = 0.0         # Green (-1) to Magenta (1)
    sky_priority: bool = True
    sky_mode: str = "top_40"  # "top_40" | "custom_rect" | "off"
    ai_awb_enable: bool = True
    
    # Multi-Mask System
    masks: List[MaskLayer] = dataclasses.field(default_factory=list)
    masks_enabled: bool = True
    active_mask_id: Optional[str] = None
    mask_rect: Optional[Tuple[int, int, int, int]] = None
    plate_mask_rect: Optional[Tuple[int, int, int, int]] = None
    
    # Horizon / Hemisphere Separation
    horizon_enable: bool = False
    horizon_height: float = 0.5                # Normalized Y position of horizon (0.0 to 1.0)
    horizon_feather: float = 0.1               # Softness of the horizon line
    
    sky_ev_offset: float = 0.0
    sky_temperature: float = 0.0
    sky_tint: float = 0.0
    sky_desat: float = 0.0
    
    ground_ev_offset: float = 0.0             # EV adjustment for the ground
    ground_temperature: float = 0.0
    ground_tint: float = 0.0
    ground_desat: float = 0.0                 # Desaturation of the ground (0.0 to 1.0)
    
    # Highlight Compression (Soft-Clip)
    softclip_enable: bool = False
    softclip_threshold: float = 5.0           # EV stops above mid-grey where soft-clip begins
    softclip_rolloff: float = 2.0             # EV stops of extra headroom (asymptote)
    
    plate_mask_rect: Optional[Tuple[int, int, int, int]] = None  # (x1, y1, x2, y2) drawn on plate
    plate_is_display_referred: bool = False  # True for JPG/PNG (sRGB gamma), False for EXR/HDR (linear)
    
    # Plate Adjustments (independent of HDRI calibration)
    plate_adjustments_enabled: bool = False
    plate_ev_offset: float = 0.0      # Exposure offset for plate display (EV stops)
    plate_saturation: float = 1.0     # Saturation multiplier for plate (1.0 = unchanged)
    plate_temperature: float = 0.0    # Blue (-1) to Yellow (1) for plate
    plate_tint: float = 0.0           # Green (-1) to Magenta (1) for plate
    
    # Sun Relighting
    sun_relight_enabled: bool = False
    sun_source_u: float = 0.5         # Original sun U position (normalised 0-1)
    sun_source_v: float = 0.25        # Original sun V position (normalised 0-1)
    sun_target_u: float = 0.5         # Target sun U position (normalised 0-1)
    sun_target_v: float = 0.25        # Target sun V position (normalised 0-1)
    sun_radius: float = 0.03          # Normalised extraction radius
    sun_feather: float = 0.015        # Normalised feather width
    sun_auto_detected: bool = False   # True if sun position was auto-detected
    
    plate_graded: Optional[np.ndarray] = None        # Plate with EV/sat applied (Full Res)
    plate_graded_proxy: Optional[np.ndarray] = None   # Downsampled graded plate
    
    # CG Light Match
    cg_exr_path: Optional[str] = None
    cg_lights: Optional[dict] = None
    cg_light_proxies: Optional[dict] = None
    cg_light_params: Optional[dict] = None # {"light_key_01": {"ev": 0.0, "temp": 0.0, "tint": 0.0}}
    cg_beauty: Optional[np.ndarray] = None
    cg_beauty_proxy: Optional[np.ndarray] = None
    cg_reconstructed: Optional[np.ndarray] = None
    cg_reconstructed_proxy: Optional[np.ndarray] = None
    cg_alpha: Optional[np.ndarray] = None       # CG alpha channel (H, W) float32
    cg_alpha_proxy: Optional[np.ndarray] = None  # Downsampled CG alpha
    cg_aov_prefixes: str = "C_Light_, light_, key, fill, rim, bounce, warm, cool"
    
    # CG Comp Options
    cg_comp_shadow: float = 1.0                  # Shadow catch intensity (0-2)
    cg_comp_refl: float = 1.0                    # Reflection catch intensity (0-2)
    cg_comp_blend: float = 1.0                   # Global CG opacity mix (0-1)
