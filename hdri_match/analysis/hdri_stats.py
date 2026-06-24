"""
HDRI Statistics & QC Report Generator.

Analyzes HDRI images to produce production-ready metadata reports including
dynamic range, sun position, correlated color temperature, and coverage stats.
"""
import numpy as np
import math
from typing import Optional, Dict, Any


class HDRIStats:
    """Computes comprehensive statistics and QC metadata for HDRI images."""

    @staticmethod
    def compute_luminance(image: np.ndarray) -> np.ndarray:
        """Rec.709 luminance from linear RGB."""
        return np.dot(image[..., :3], [0.2126, 0.7152, 0.0722])

    @staticmethod
    def rgb_to_cct(r: float, g: float, b: float) -> float:
        """
        Estimate Correlated Color Temperature (Kelvin) from scene-linear RGB.

        Uses McCamy's approximation via CIE 1931 chromaticity coordinates.
        Valid range: ~1667K to ~25000K. Returns 0.0 if input is degenerate.
        """
        total = r + g + b
        if total < 1e-10:
            return 0.0

        # CIE 1931 chromaticity from sRGB primaries (Rec.709)
        # Convert RGB to XYZ (sRGB/Rec.709 matrix)
        X = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
        Y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
        Z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b

        denom = X + Y + Z
        if denom < 1e-10:
            return 0.0

        x = X / denom
        y = Y / denom

        # McCamy's approximation
        n = (x - 0.3320) / (0.1858 - y) if abs(0.1858 - y) > 1e-10 else 0.0
        cct = 449.0 * n**3 + 3525.0 * n**2 + 6823.3 * n + 5520.33

        return max(1000.0, min(40000.0, cct))

    @staticmethod
    def cct_to_description(cct: float) -> str:
        """Human-readable description of a CCT value."""
        if cct <= 0:
            return "Unknown"
        elif cct < 2000:
            return "Candlelight"
        elif cct < 3200:
            return "Tungsten / Warm"
        elif cct < 4000:
            return "Halogen"
        elif cct < 5000:
            return "Horizon / Golden Hour"
        elif cct < 5600:
            return "Daylight (Direct Sun)"
        elif cct < 6500:
            return "Daylight (Overcast)"
        elif cct < 7500:
            return "Cloudy / Shade"
        elif cct < 10000:
            return "Blue Sky / Deep Shade"
        else:
            return "Open Sky / Very Blue"

    @staticmethod
    def compute_sun_position(image: np.ndarray) -> Dict[str, Any]:
        """
        Find the brightest point in the HDRI and return its position
        in equirectangular, spherical, and Cartesian coordinates.
        """
        h, w = image.shape[:2]
        luma = HDRIStats.compute_luminance(image)
        flat_idx = int(np.argmax(luma))
        py, px = divmod(flat_idx, w)

        # UV coordinates
        u = (px + 0.5) / w
        v = (py + 0.5) / h

        # Spherical coordinates
        azimuth_deg = (u * 360.0) - 180.0  # -180 to +180
        elevation_deg = 90.0 - (v * 180.0)  # +90 (zenith) to -90 (nadir)

        # Cartesian direction vector (Y-up, Z-forward)
        theta = math.radians(azimuth_deg)
        phi = math.radians(elevation_deg)

        dir_x = math.cos(phi) * math.sin(theta)
        dir_y = math.sin(phi)
        dir_z = math.cos(phi) * math.cos(theta)

        # Sun color and intensity
        peak_luma = float(luma[py, px])
        color_rgb = image[py, px, :3].tolist()

        return {
            "pixel_xy": (px, py),
            "uv": (u, v),
            "azimuth_deg": azimuth_deg,
            "elevation_deg": elevation_deg,
            "direction_vector": (dir_x, dir_y, dir_z),
            "peak_luminance": peak_luma,
            "peak_ev": float(np.log2(max(peak_luma / 0.18, 1e-8))),
            "color_rgb": color_rgb,
        }

    @staticmethod
    def compute_dynamic_range(image: np.ndarray) -> Dict[str, float]:
        """Compute the useful dynamic range of the image in EV stops."""
        luma = HDRIStats.compute_luminance(image)
        luma_positive = luma[luma > 1e-8]

        if luma_positive.size < 10:
            return {
                "min_ev": 0.0, "max_ev": 0.0, "total_stops": 0.0,
                "p01_ev": 0.0, "p99_ev": 0.0, "usable_stops": 0.0,
                "median_ev": 0.0
            }

        min_luma = float(np.min(luma_positive))
        max_luma = float(np.max(luma_positive))
        p01 = float(np.percentile(luma_positive, 1))
        p99 = float(np.percentile(luma_positive, 99))
        median = float(np.median(luma_positive))

        to_ev = lambda val: float(np.log2(max(val / 0.18, 1e-8)))

        return {
            "min_ev": to_ev(min_luma),
            "max_ev": to_ev(max_luma),
            "total_stops": to_ev(max_luma) - to_ev(min_luma),
            "p01_ev": to_ev(p01),
            "p99_ev": to_ev(p99),
            "usable_stops": to_ev(p99) - to_ev(p01),
            "median_ev": to_ev(median),
        }

    @staticmethod
    def compute_coverage(image: np.ndarray) -> Dict[str, float]:
        """
        Compute coverage percentages for different luminance zones.
        All thresholds are in scene-linear relative to 0.18 mid-grey.
        """
        luma = HDRIStats.compute_luminance(image)
        total = luma.size

        # Thresholds in linear (relative to 0.18 mid-grey)
        underexposed_thresh = 0.18 * (2.0 ** -5)   # 5 stops below mid-grey
        shadow_thresh = 0.18 * (2.0 ** -2)          # 2 stops below mid-grey
        highlight_thresh = 0.18 * (2.0 ** 3)        # 3 stops above mid-grey
        overexposed_thresh = 0.18 * (2.0 ** 10)     # 10 stops above mid-grey (sun threshold)

        pct_underexposed = float(np.sum(luma < underexposed_thresh) / total * 100)
        pct_shadow = float(np.sum((luma >= underexposed_thresh) & (luma < shadow_thresh)) / total * 100)
        pct_midtone = float(np.sum((luma >= shadow_thresh) & (luma < highlight_thresh)) / total * 100)
        pct_highlight = float(np.sum((luma >= highlight_thresh) & (luma < overexposed_thresh)) / total * 100)
        pct_overexposed = float(np.sum(luma >= overexposed_thresh) / total * 100)

        # Negative values
        pct_negative = float(np.sum(np.any(image < 0, axis=-1)) / total * 100)

        # Sky vs Ground (equirectangular: top half = sky, bottom half = ground)
        h = image.shape[0]
        pct_sky_area = 50.0  # by definition
        pct_ground_area = 50.0

        return {
            "underexposed_pct": pct_underexposed,
            "shadow_pct": pct_shadow,
            "midtone_pct": pct_midtone,
            "highlight_pct": pct_highlight,
            "overexposed_pct": pct_overexposed,
            "negative_pct": pct_negative,
            "sky_area_pct": pct_sky_area,
            "ground_area_pct": pct_ground_area,
        }

    @staticmethod
    def compute_illuminant_cct(image: np.ndarray, sky_only: bool = True) -> float:
        """
        Estimate the dominant illuminant CCT from the image.
        Uses the upper 40% (sky hemisphere) by default for best results.
        """
        if sky_only:
            h = image.shape[0]
            region = image[:int(h * 0.4), :, :]
        else:
            region = image

        # Weighted mean (mid-tone weighted to avoid sun/shadow bias)
        luma = HDRIStats.compute_luminance(region)
        median_luma = max(float(np.median(luma)), 1e-8)
        sigma = median_luma * 2.0
        weight = np.exp(-0.5 * ((luma - median_luma) / sigma) ** 2)
        weight = np.maximum(weight, 1e-8)

        mean_r = float(np.average(region[..., 0], weights=weight))
        mean_g = float(np.average(region[..., 1], weights=weight))
        mean_b = float(np.average(region[..., 2], weights=weight))

        return HDRIStats.rgb_to_cct(mean_r, mean_g, mean_b)

    @staticmethod
    def generate_full_report(image: np.ndarray,
                              hdri_path: Optional[str] = None,
                              yaw_offset: float = 0.0) -> Dict[str, Any]:
        """
        Generate a comprehensive QC report for the given HDRI image.

        Args:
            image:       Linear float32 RGB array (H, W, 3).
            hdri_path:   Optional file path for metadata.
            yaw_offset:  Current yaw rotation in degrees.

        Returns:
            Dictionary with all computed statistics.
        """
        import os

        h, w = image.shape[:2]

        # Basic metadata
        report = {
            "file": os.path.basename(hdri_path) if hdri_path else "Unknown",
            "resolution": f"{w} × {h}",
            "resolution_w": w,
            "resolution_h": h,
            "aspect_ratio": f"{w/h:.2f}:1" if h > 0 else "N/A",
            "pixel_count": w * h,
            "yaw_offset_deg": yaw_offset,
        }

        # Dynamic range
        report["dynamic_range"] = HDRIStats.compute_dynamic_range(image)

        # Sun position
        sun = HDRIStats.compute_sun_position(image)
        report["sun"] = sun

        # CCT from sun peak color
        sun_cct = HDRIStats.rgb_to_cct(*sun["color_rgb"])
        report["sun_cct_kelvin"] = sun_cct
        report["sun_cct_description"] = HDRIStats.cct_to_description(sun_cct)

        # Ambient CCT (sky illuminant)
        ambient_cct = HDRIStats.compute_illuminant_cct(image, sky_only=True)
        report["ambient_cct_kelvin"] = ambient_cct
        report["ambient_cct_description"] = HDRIStats.cct_to_description(ambient_cct)

        # Coverage
        report["coverage"] = HDRIStats.compute_coverage(image)

        # Channel statistics
        report["channel_stats"] = {
            "R": {"min": float(image[..., 0].min()), "max": float(image[..., 0].max()),
                   "mean": float(image[..., 0].mean())},
            "G": {"min": float(image[..., 1].min()), "max": float(image[..., 1].max()),
                   "mean": float(image[..., 1].mean())},
            "B": {"min": float(image[..., 2].min()), "max": float(image[..., 2].max()),
                   "mean": float(image[..., 2].mean())},
        }

        return report

    @staticmethod
    def format_report_text(report: Dict[str, Any]) -> str:
        """Format the report as a human-readable text block for clipboard or display."""
        dr = report["dynamic_range"]
        sun = report["sun"]
        cov = report["coverage"]

        lines = [
            "=======================================",
            "       HDRI QC REPORT",
            "=======================================",
            "",
            f"  File:          {report['file']}",
            f"  Resolution:    {report['resolution']}",
            f"  Aspect Ratio:  {report['aspect_ratio']}",
            f"  Yaw Rotation:  {report['yaw_offset_deg']:.1f} deg",
            "",
            "--- Dynamic Range ----------------------",
            f"  Total Range:   {dr['total_stops']:.1f} stops",
            f"  Usable Range:  {dr['usable_stops']:.1f} stops (1%-99%)",
            f"  Min EV:        {dr['min_ev']:+.2f}",
            f"  Max EV:        {dr['max_ev']:+.2f}",
            f"  Median EV:     {dr['median_ev']:+.2f}",
            "",
            "--- Sun / Key Light --------------------",
            f"  Position:      ({sun['pixel_xy'][0]}, {sun['pixel_xy'][1]})",
            f"  Azimuth:       {sun['azimuth_deg']:+.1f} deg",
            f"  Elevation:     {sun['elevation_deg']:+.1f} deg",
            f"  Peak EV:       {sun['peak_ev']:+.2f}",
            f"  Peak Luma:     {sun['peak_luminance']:.2f}",
            f"  Direction:     ({sun['direction_vector'][0]:.4f}, "
            f"{sun['direction_vector'][1]:.4f}, {sun['direction_vector'][2]:.4f})",
            "",
            "--- Color Temperature ------------------",
            f"  Sun CCT:       {report['sun_cct_kelvin']:.0f} K  ({report['sun_cct_description']})",
            f"  Ambient CCT:   {report['ambient_cct_kelvin']:.0f} K  ({report['ambient_cct_description']})",
            "",
            "--- Coverage ---------------------------",
            f"  Underexposed:  {cov['underexposed_pct']:.1f}%",
            f"  Shadows:       {cov['shadow_pct']:.1f}%",
            f"  Midtones:      {cov['midtone_pct']:.1f}%",
            f"  Highlights:    {cov['highlight_pct']:.1f}%",
            f"  Overexposed:   {cov['overexposed_pct']:.1f}%",
            f"  Negative:      {cov['negative_pct']:.1f}%",
            "",
            "=======================================",
        ]
        return "\n".join(lines)
