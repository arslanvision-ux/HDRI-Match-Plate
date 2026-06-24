import numpy as np

class MacbethDetector:
    # Standard 24 patches linear sRGB (approximate)
    REFERENCE_LINEAR = np.array([
        [0.031, 0.015, 0.009], [0.150, 0.089, 0.063], [0.046, 0.063, 0.100], [0.036, 0.054, 0.025],
        [0.105, 0.088, 0.160], [0.203, 0.287, 0.222], [0.285, 0.076, 0.016], [0.060, 0.056, 0.161],
        [0.170, 0.038, 0.039], [0.030, 0.013, 0.027], [0.125, 0.179, 0.032], [0.354, 0.151, 0.022],
        [0.016, 0.016, 0.066], [0.054, 0.119, 0.040], [0.110, 0.016, 0.019], [0.472, 0.380, 0.060],
        [0.144, 0.052, 0.100], [0.009, 0.048, 0.088], [0.860, 0.860, 0.860], [0.550, 0.550, 0.550],
        [0.320, 0.320, 0.320], [0.160, 0.160, 0.160], [0.070, 0.070, 0.070], [0.020, 0.020, 0.020]
    ], dtype=np.float32)

    @staticmethod
    def detect_and_build_matrix(image: np.ndarray, color_space: str = "Linear"):
        """
        Assumes the image is roughly cropped to the 24-patch Macbeth chart.
        Samples a 6x4 grid to extract the patch colors robustly.
        """
        h, w = image.shape[:2]
        
        # Determine the target reference colors based on color space
        ref_colors = MacbethDetector.REFERENCE_LINEAR.copy()
        if color_space.lower() == "acescg":
            # Sampled directly from ACEScg_ColorChecker2014.exr
            ref_colors = np.array([
                [0.13574, 0.08508, 0.05844], [0.44727, 0.29622, 0.22607], [0.14404, 0.18530, 0.30762], [0.11804, 0.14587, 0.06372], [0.23254, 0.21704, 0.39697], [0.26196, 0.47803, 0.41626], 
                [0.52686, 0.23767, 0.06519], [0.08972, 0.10303, 0.34717], [0.37646, 0.11469, 0.11987], [0.08813, 0.04837, 0.12622], [0.37329, 0.47803, 0.10223], [0.59424, 0.38135, 0.07593], 
                [0.04327, 0.04965, 0.25073], [0.12939, 0.27075, 0.08832], [0.28809, 0.06543, 0.04855], [0.70947, 0.58350, 0.08929], [0.36133, 0.11279, 0.26929], [0.07062, 0.21643, 0.35132], 
                [0.87891, 0.88379, 0.84131], [0.58691, 0.59131, 0.58545], [0.36133, 0.36646, 0.36523], [0.19031, 0.19080, 0.18994], [0.08710, 0.08856, 0.08960], [0.03146, 0.03149, 0.03220]
            ], dtype=np.float32)
        
        # We expect 6 columns, 4 rows.
        # Add a 10% margin to avoid edges, then divide the rest by 6 and 4.
        margin_x = int(w * 0.05)
        margin_y = int(h * 0.05)
        
        step_x = (w - 2 * margin_x) / 6.0
        step_y = (h - 2 * margin_y) / 4.0
        
        sampled_colors = []
        for row in range(4):
            for col in range(6):
                cx = int(margin_x + (col + 0.5) * step_x)
                cy = int(margin_y + (row + 0.5) * step_y)
                
                # Sample a 5x5 pixel area around the center
                patch = image[max(0, cy-2):min(h, cy+3), max(0, cx-2):min(w, cx+3)]
                color = np.mean(patch, axis=(0,1))[:3]
                sampled_colors.append(color)
                
        sampled_colors = np.array(sampled_colors)
        
        # Check if the chart is upside down by looking at the neutral row.
        # Patch 18 to 23 are the neutral patches in a standard chart.
        # Neutral patches have very low saturation compared to color patches.
        def row_saturation(row_colors):
            max_c = np.max(row_colors, axis=1)
            min_c = np.min(row_colors, axis=1)
            return np.mean(max_c - min_c)
            
        sat_row0 = row_saturation(sampled_colors[0:6])
        sat_row3 = row_saturation(sampled_colors[18:24])
        
        # If the top row has less saturation than the bottom row, it's the neutral row,
        # meaning the chart is rotated 180 degrees (upside down).
        if sat_row0 < sat_row3:
            sampled_colors = sampled_colors[::-1]
        # Decouple exposure from color matrix:
        # Normalize the sampled colors to match the average luminance of the reference
        # so that the resulting matrix only performs color mixing/white balancing,
        # leaving absolute exposure to be handled by the EV slider.
        ref_mean = np.mean(ref_colors)
        sample_mean = np.mean(sampled_colors)
        if sample_mean > 1e-6:
            sampled_colors_norm = sampled_colors * (ref_mean / sample_mean)
        else:
            sampled_colors_norm = sampled_colors
            
        # Least squares: S * M = R -> M = pinv(S) * R
        # Add a tiny ridge penalty to avoid extreme matrices if the colors are badly clipped
        S_inv = np.linalg.pinv(sampled_colors_norm, rcond=1e-3)
        matrix_3x3 = np.dot(S_inv, ref_colors)
        return matrix_3x3
