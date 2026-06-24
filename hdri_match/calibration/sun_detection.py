import numpy as np


class SunDetector:
    """
    Detects and masks extreme highlights (sun disc, specular highlights) in
    HDR panoramas so they are excluded from white balance and exposure matching.

    The core idea: pixels above a threshold (e.g., 10x middle grey = ~1.8 in linear)
    are considered 'sun-class' highlights and are masked out before any statistical
    analysis (mean, percentile) is performed.
    """

    # Default threshold: 10 stops above middle grey (0.18)
    DEFAULT_THRESHOLD = 0.18 * (2 ** 10)  # ≈ 184.0 in linear

    @staticmethod
    def compute_luminance(image: np.ndarray) -> np.ndarray:
        """Rec.709 relative luminance."""
        return np.dot(image[..., :3], [0.2126, 0.7152, 0.0722])

    @staticmethod
    def build_sun_mask(image: np.ndarray, threshold: float = None, dilate_pixels: int = 8) -> np.ndarray:
        """
        Returns a boolean mask (H, W) where True = safe pixel (not sun/specular).
        Bright pixels AND a small dilation border around them are excluded.

        Args:
            image:          Linear float32 RGB array.
            threshold:      Luminance value above which a pixel is 'sun class'.
            dilate_pixels:  Number of pixels to grow the exclusion zone outward.
        Returns:
            safe_mask: (H, W) bool array — True means pixel is safe to use.
        """
        if threshold is None:
            threshold = SunDetector.DEFAULT_THRESHOLD

        luma = SunDetector.compute_luminance(image)
        hot_mask = luma >= threshold  # True = too bright

        if dilate_pixels > 0:
            try:
                # Fast path: use scipy if available
                from scipy.ndimage import binary_dilation
                struct = np.ones((dilate_pixels * 2 + 1, dilate_pixels * 2 + 1), dtype=bool)
                hot_mask = binary_dilation(hot_mask, structure=struct)
            except ImportError:
                # Fallback: manual 2D max-pooling via cumsum (slightly slower)
                d = dilate_pixels
                padded = np.pad(hot_mask.astype(np.float32), d, mode='edge')
                h, w = hot_mask.shape
                # Vertical cumsum
                cs = np.cumsum(padded, axis=0)
                row_sum = cs[2 * d:, :] - cs[:h, :]
                # Horizontal cumsum
                cs2 = np.cumsum(row_sum, axis=1)
                col_sum = cs2[:, 2 * d:] - cs2[:, :w]
                hot_mask = col_sum > 0

        return ~hot_mask  # Invert: safe = True

    @staticmethod
    def masked_mean(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Computes per-channel mean of image using only pixels where mask is True.
        Falls back to full-image mean if the mask eliminates everything.
        """
        safe_pixels = image[mask]
        if safe_pixels.shape[0] < 10:
            # Mask too aggressive — fall back to unmasked
            safe_pixels = image.reshape(-1, image.shape[-1])
        return safe_pixels.mean(axis=0).astype(np.float32)

    @staticmethod
    def masked_percentile(image: np.ndarray, mask: np.ndarray, percentile: float) -> float:
        """
        Computes luminance percentile using only non-sun pixels.
        """
        luma = SunDetector.compute_luminance(image)
        safe_luma = luma[mask]
        if safe_luma.size < 10:
            safe_luma = luma.flatten()
        val = float(np.percentile(safe_luma, percentile))
        return max(val, 1e-8)

    @staticmethod
    def sun_coverage_percent(image: np.ndarray, threshold: float = None) -> float:
        """Returns what % of pixels are classified as sun/specular highlights."""
        if threshold is None:
            threshold = SunDetector.DEFAULT_THRESHOLD
        luma = SunDetector.compute_luminance(image)
        return float((luma >= threshold).sum() / luma.size * 100.0)
