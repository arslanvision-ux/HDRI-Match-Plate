import numpy as np
from hdri_match.calibration.exposure import ExposureAnalyzer

class FalseColorEngine:
    """Generates false-color maps for visual analysis of luminance and clipping."""
    
    @staticmethod
    def generate_heatmap(image: np.ndarray, min_ev: float = -5.0, max_ev: float = 5.0) -> np.ndarray:
        """
        Creates a color-mapped visualization of luminance values.
        Maps the logarithmic luminance to a thermal colormap (Blue -> Green -> Red).
        Highlights negatives in Magenta and >15 EV in bright Green.
        """
        negative_mask = np.any(image < 0.0, axis=-1)
        
        luma = ExposureAnalyzer.get_luminance(image)
        luma_safe = np.clip(luma, 1e-8, None)
        
        ev_map = np.log2(luma_safe / 0.18)
        
        high_mask = ev_map > 15.0
        
        normalized_ev = (ev_map - min_ev) / (max_ev - min_ev)
        normalized_ev = np.clip(normalized_ev, 0.0, 1.0)
        
        r = np.clip((normalized_ev - 0.5) * 2.0, 0, 1)
        b = np.clip((0.5 - normalized_ev) * 2.0, 0, 1)
        g = 1.0 - r - b 
        
        heatmap = np.stack([r, g, b], axis=-1)
        
        heatmap[high_mask] = [0.0, 1.0, 0.0]  # Over 15 stops = Green
        heatmap[negative_mask] = [1.0, 0.0, 1.0] # Negatives = Magenta
        
        return heatmap

    @staticmethod
    def detect_clipping(image: np.ndarray, clip_threshold: float = 65500.0) -> np.ndarray:
        """
        Returns an RGB overlay highlighting regions that exceed the clip_threshold.
        Clipped pixels are rendered pure Red [1, 0, 0].
        """
        mask = np.any(image >= clip_threshold, axis=-1)
        
        overlay = np.zeros_like(image)
        overlay[mask] = [1.0, 0.0, 0.0]
        
        return overlay
