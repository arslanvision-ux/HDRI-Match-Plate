import numpy as np
import math

class LightExtractor:
    @staticmethod
    def extract_lights(hdri_array, num_lights=3, mask_radius_px=100):
        """
        Scans the HDRI to find the top `num_lights` brightest light sources.
        Returns a list of dicts:
        [{'name': 'Key', 'vector': (x,y,z), 'color': (r,g,b), 'intensity': float}, ...]
        """
        h, w = hdri_array.shape[:2]
        
        # Calculate luma
        luma = np.sum(hdri_array * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1)
        
        lights = []
        names = ["Key", "Fill", "Rim", "Bounce", "Kicker"]
        
        # Work on a copy of luma so we can mask out extracted regions
        working_luma = luma.copy()
        
        for i in range(num_lights):
            # Find brightest pixel
            y, x = np.unravel_index(np.argmax(working_luma), working_luma.shape)
            peak_luma = working_luma[y, x]
            
            if peak_luma <= 1e-6:
                break # No more lights found
                
            # Sample color from the original array at the peak
            r, g, b = hdri_array[y, x, :3]
            
            # Calculate spherical vector (Equirectangular projection)
            # U = x / w, V = y / h
            u = (x + 0.5) / w
            v = (y + 0.5) / h
            
            # Map U to longitude [-pi, pi], V to latitude [pi/2, -pi/2]
            theta = (u * 2.0 * math.pi) - math.pi
            phi = (0.5 - v) * math.pi
            
            # Convert spherical to cartesian vector (Y-Up, Z-Forward)
            # Houdini default coordinate system: +Y up, +Z forward
            dir_x = math.cos(phi) * math.sin(theta)
            dir_y = math.sin(phi)
            dir_z = math.cos(phi) * math.cos(theta)
            
            # Normalize direction
            length = math.sqrt(dir_x**2 + dir_y**2 + dir_z**2)
            if length > 0:
                dir_x /= length
                dir_y /= length
                dir_z /= length
            
            # Determine overall intensity (Houdini lights are usually normalized color * exposure)
            # We'll use peak_luma as linear intensity, and normalized RGB for color.
            max_val = max(r, g, b)
            if max_val > 0:
                norm_r, norm_g, norm_b = r / max_val, g / max_val, b / max_val
            else:
                norm_r, norm_g, norm_b = 1.0, 1.0, 1.0
                
            # Angular size estimation based on mask radius
            angular_size_deg = (mask_radius_px / h) * 180.0

            lights.append({
                'name': names[i] if i < len(names) else f"Light_{i+1}",
                'vector': (dir_x, dir_y, dir_z),
                'color': (float(norm_r), float(norm_g), float(norm_b)),
                'intensity': float(max_val),
                'pos_xy': (int(x), int(y)),
                'radius_px': mask_radius_px,
                'angular_size_deg': angular_size_deg
            })
            
            # Mask out this light so we don't find it again
            # We apply a smooth circular falloff to zero
            y_idx, x_idx = np.ogrid[:h, :w]
            # Wrap around horizontal distance
            dist_x = np.abs(x_idx - x)
            dist_x = np.minimum(dist_x, w - dist_x)
            dist_y = np.abs(y_idx - y)
            
            dist_sq = dist_x**2 + dist_y**2
            mask = dist_sq < mask_radius_px**2
            working_luma[mask] = 0.0
            
        return lights
