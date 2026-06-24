import numpy as np
from typing import Optional, Tuple
import os

_ONNX_SESSION = None
_ONNX_LOAD_ATTEMPTED = False

class WhiteBalanceEstimator:
    """Estimates illuminants and applies chromatic adaptation."""

    @staticmethod
    def _get_region(image: np.ndarray, sky_only: bool,
                    custom_roi: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
        """Extract the relevant region (sky, custom ROI, or full)."""
        if custom_roi is not None:
            x1, y1, x2, y2 = custom_roi
            if x1 > x2:
                return np.concatenate([
                    image[y1:y2, x1:, :],
                    image[y1:y2, :x2, :]
                ], axis=1)
            else:
                return image[y1:y2, x1:x2, :]
        if sky_only:
            h = int(image.shape[0] * 0.4)
            return image[:h, :, :]
        return image

    @staticmethod
    def estimate_illuminant_gray_world(image: np.ndarray, sky_only=False,
                                        custom_roi=None) -> np.ndarray:
        """
        Gray-world illuminant estimation with adaptive mid-tone weighting.

        A standard gray-world average is easily biased by dominant scene colors
        (e.g. 60% green foliage). Mid-tone weighting uses the luminance of each
        pixel as a *soft* weight, peaking near the *median* luminance of the
        region and falling off for very dark or very bright pixels.

        CRITICAL: The weight center is the MEDIAN luminance of the region,
        NOT a fixed 0.18 middle grey. In an HDRI sky, the median luminance
        might be 5-50 nits — far above 0.18. A fixed 0.18 weight center would
        sample deep shadows in the HDRI, not the actual sky mid-tones.

        Args:
            image:        Float32 RGB linear array (H, W, 3).
            sky_only:     If True, use top 40% of image (equirectangular sky).
            custom_roi:   Optional (x1, y1, x2, y2) pixel coordinates. Overrides
                          `sky_only` — only pixels inside this rectangle are used.
        Returns:
            illuminant:   (3,) float32 array normalized so G = 1.0.
        """
        region = WhiteBalanceEstimator._get_region(image, sky_only, custom_roi)
        if region.size == 0:
            # Fallback to full image if region is empty
            region = image

        luma = (0.2126 * region[..., 0]
              + 0.7152 * region[..., 1]
              + 0.0722 * region[..., 2])

        # Adaptive weight center: use the median luminance of the region.
        # Sigma = 2 stops in linear space (median × 2).
        median_luma = float(np.median(luma))
        center = max(median_luma, 1e-8)
        sigma = center * 2.0  # ±2 stops captures most mid-tones

        # Gaussian weight centered on the region's median luminance
        weight = np.exp(-0.5 * ((luma - center) / sigma) ** 2)
        weight = np.maximum(weight, 1e-8)

        weighted_mean_r = np.average(region[..., 0], weights=weight)
        weighted_mean_g = np.average(region[..., 1], weights=weight)
        weighted_mean_b = np.average(region[..., 2], weights=weight)

        illuminant = np.array([weighted_mean_r, weighted_mean_g, weighted_mean_b],
                              dtype=np.float32)
        if weighted_mean_g > 1e-8:
            illuminant /= weighted_mean_g
        return illuminant

    @staticmethod
    def estimate_illuminant_ai(image: np.ndarray, sky_only=False,
                                custom_roi=None) -> np.ndarray:
        """
        AI-Powered Auto White Balance using ONNX Runtime.
        Falls back to gray-world if the model is unavailable or inference fails.
        """
        region = WhiteBalanceEstimator._get_region(image, sky_only, custom_roi)
        if region.size == 0:
            region = image

        global _ONNX_SESSION, _ONNX_LOAD_ATTEMPTED

        import os
        model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ml', 'awbnet_v1.onnx')
        
        try:
            import onnxruntime as ort
            
            if not _ONNX_LOAD_ATTEMPTED:
                _ONNX_LOAD_ATTEMPTED = True
                if os.path.exists(model_path):
                    _ONNX_SESSION = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
            
            if _ONNX_SESSION is not None:
                # Nearest neighbor downsample to 64x64 to avoid cv2 dependency
                h, w = region.shape[:2]
                y_idx = np.round(np.linspace(0, h - 1, 64)).astype(int)
                x_idx = np.round(np.linspace(0, w - 1, 64)).astype(int)
                resized = region[y_idx][:, x_idx]
                
                # Ensure linear float32
                resized = resized.astype(np.float32)
                # HWC to CHW
                input_tensor = np.transpose(resized, (2, 0, 1))
                # Add batch dimension
                input_tensor = np.expand_dims(input_tensor, axis=0)

                input_name = _ONNX_SESSION.get_inputs()[0].name
                output_name = _ONNX_SESSION.get_outputs()[0].name

                illuminant = _ONNX_SESSION.run([output_name], {input_name: input_tensor})[0]
                illuminant = illuminant.flatten()
                
                # Normalize so G = 1.0
                if illuminant[1] > 1e-8:
                    illuminant /= illuminant[1]
                
                return illuminant
        except ImportError:
            # Silently fallback if onnxruntime is not installed (e.g. inside Nuke)
            pass
        except Exception as e:
            print(f"[HDRI Match Plate] AI AWB Inference Failed: {e}. Falling back to Gray-World.")

        # Fallback
        return WhiteBalanceEstimator.estimate_illuminant_gray_world(image, sky_only, custom_roi)


    @staticmethod
    def estimate_illuminant_from_grey_ball(grey_ball_array: np.ndarray) -> np.ndarray:
        mean_r = np.mean(grey_ball_array[..., 0])
        mean_g = np.mean(grey_ball_array[..., 1])
        mean_b = np.mean(grey_ball_array[..., 2])
        illuminant = np.array([mean_r, mean_g, mean_b], dtype=np.float32)
        if mean_g > 1e-8:
            illuminant /= mean_g
        return illuminant

    @staticmethod
    def match_illuminant(hdri: np.ndarray, hdri_ill: np.ndarray,
                          plate_ill: np.ndarray,
                          preserve_luminance: bool = True) -> np.ndarray:
        """
        Matches the HDRI color balance to the target plate balance.
        After applying per-channel color scale factors, the overall luminance
        shifts. If preserve_luminance is True, the output is re-normalized so
        the luminance after color matching equals the luminance before.
        """
        hdri_safe = np.clip(hdri_ill, 1e-8, None)
        plate_safe = np.clip(plate_ill, 1e-8, None)

        scale_factors = plate_safe / hdri_safe

        # Store input luminance for later re-normalization
        if preserve_luminance:
            luma_in = (0.2126 * hdri[..., 0]
                     + 0.7152 * hdri[..., 1]
                     + 0.0722 * hdri[..., 2])

        matched_image = hdri.copy()
        for i in range(3):
            matched_image[..., i] *= scale_factors[i]

        if preserve_luminance:
            luma_out = (0.2126 * matched_image[..., 0]
                      + 0.7152 * matched_image[..., 1]
                      + 0.0722 * matched_image[..., 2])
            luma_out = np.maximum(luma_out, 1e-8)
            luma_ratio = luma_in / luma_out
            for i in range(3):
                matched_image[..., i] *= luma_ratio

        return matched_image

    @staticmethod
    def apply_temperature_tint(image: np.ndarray, temp: float, tint: float) -> np.ndarray:
        """
        Applies temperature (Blue-Yellow) and tint (Green-Magenta) adjustments.
        temp: -1.0 (cooler/blue) to 1.0 (warmer/yellow)
        tint: -1.0 (greener) to 1.0 (magenta)
        """
        if temp == 0.0 and tint == 0.0:
            return image

        r_scale = 1.0 + temp + tint
        g_scale = 1.0 - tint
        b_scale = 1.0 - temp

        lum = (r_scale + g_scale + b_scale) / 3.0
        r_scale /= lum
        g_scale /= lum
        b_scale /= lum

        matched_image = image.copy()
        matched_image[..., 0] *= max(0.01, r_scale)
        matched_image[..., 1] *= max(0.01, g_scale)
        matched_image[..., 2] *= max(0.01, b_scale)

        return matched_image