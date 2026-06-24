import numpy as np

class ExposureAnalyzer:
    """Analyzes and calibrates exposure between an HDRI and a plate."""
    
    @staticmethod
    def get_luminance(image: np.ndarray) -> np.ndarray:
        """Computes relative luminance (Rec.709) of an RGB float image."""
        # Y = 0.2126 R + 0.7152 G + 0.0722 B
        return np.dot(image[..., :3], [0.2126, 0.7152, 0.0722])
    
    @staticmethod
    def compute_ev_offset_percentile(hdri: np.ndarray, plate: np.ndarray, percentile: float = 90.0) -> float:
        """
        Computes the EV (Exposure Value) offset required to match the HDRI to the plate,
        based on a given luminance percentile.
        """
        # Calculate luminance
        hdri_luma = ExposureAnalyzer.get_luminance(hdri)
        plate_luma = ExposureAnalyzer.get_luminance(plate)
        
        # Get target percentiles (ignoring extreme highlights if percentile < 100)
        hdri_val = np.percentile(hdri_luma, percentile)
        plate_val = np.percentile(plate_luma, percentile)
        
        # Prevent log of zero
        hdri_val = max(hdri_val, 1e-8)
        plate_val = max(plate_val, 1e-8)
        
        # The scale factor is (plate_val / hdri_val). EV offset is log2(scale).
        scale_factor = plate_val / hdri_val
        ev_offset = np.log2(scale_factor)
        
        return float(ev_offset)

    @staticmethod
    def compute_ev_offset_chrome_ball(hdri_chrome_array: np.ndarray, plate_chrome_array: np.ndarray) -> float:
        """
        Computes the EV offset specifically using sampled chrome ball inputs.
        Chrome balls reflect the light source directly, providing an accurate peak highlight reference.
        """
        hdri_peak = np.max(ExposureAnalyzer.get_luminance(hdri_chrome_array))
        plate_peak = np.max(ExposureAnalyzer.get_luminance(plate_chrome_array))
        
        hdri_peak = max(hdri_peak, 1e-8)
        plate_peak = max(plate_peak, 1e-8)
        
        return float(np.log2(plate_peak / hdri_peak))

    @staticmethod
    def apply_exposure(image: np.ndarray, ev_offset: float) -> np.ndarray:
        """Applies an EV offset to a linear image."""
        scale_factor = 2.0 ** ev_offset
        return image * scale_factor
