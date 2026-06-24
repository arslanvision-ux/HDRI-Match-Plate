import numpy as np
import cv2

class AutoCropper:
    @staticmethod
    def autocrop_ball(image: np.ndarray) -> np.ndarray:
        """Finds the largest circular object and crops the image to it."""
        try:
            # Convert to 8-bit for OpenCV
            img_8u = np.clip(image * 255.0, 0, 255).astype(np.uint8)
            gray = cv2.cvtColor(img_8u, cv2.COLOR_RGB2GRAY)
            
            # Blur to reduce noise
            gray_blur = cv2.medianBlur(gray, 5)
            
            # Find circles using HoughCircles
            h, w = gray.shape
            min_r = int(min(h, w) * 0.05)
            max_r = int(min(h, w) * 0.5)
            
            # HoughCircles can be finicky. Let's try findContours with circularity first.
            _, thresh = cv2.threshold(gray_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            
            best_circle = None
            best_score = 0
            
            for c in contours:
                area = cv2.contourArea(c)
                if area < (h * w * 0.01):
                    continue
                    
                perimeter = cv2.arcLength(c, True)
                if perimeter == 0:
                    continue
                    
                circularity = 4 * np.pi * (area / (perimeter * perimeter))
                x, y, bw, bh = cv2.boundingRect(c)
                aspect_ratio = float(bw) / bh
                
                # A perfect circle has circularity 1.0 and aspect ratio 1.0
                if 0.5 < circularity <= 1.2 and 0.6 < aspect_ratio < 1.4:
                    score = area * circularity
                    if score > best_score:
                        best_score = score
                        best_circle = (x, y, bw, bh)
            
            if best_circle is not None:
                x, y, bw, bh = best_circle
                # Add a 5% margin
                margin_x = int(bw * 0.05)
                margin_y = int(bh * 0.05)
                x1 = max(0, x - margin_x)
                y1 = max(0, y - margin_y)
                x2 = min(w, x + bw + margin_x)
                y2 = min(h, y + bh + margin_y)
                return image[y1:y2, x1:x2]
                
            # Fallback to HoughCircles if contour circularity failed
            circles = cv2.HoughCircles(gray_blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min_r,
                                       param1=50, param2=30, minRadius=min_r, maxRadius=max_r)
            if circles is not None:
                circles = np.round(circles[0, :]).astype("int")
                # Pick the largest circle
                circles = sorted(circles, key=lambda x: x[2], reverse=True)
                cx, cy, r = circles[0]
                
                margin = int(r * 0.1)
                x1 = max(0, cx - r - margin)
                y1 = max(0, cy - r - margin)
                x2 = min(w, cx + r + margin)
                y2 = min(h, cy + r + margin)
                return image[y1:y2, x1:x2]
                
        except Exception as e:
            print(f"Ball autocrop failed: {e}")
            
        return image  # Return original if failed

    @staticmethod
    def autocrop_macbeth(image: np.ndarray) -> np.ndarray:
        """Finds the Macbeth chart by looking for a cluster of square patches."""
        try:
            img_8u = np.clip(image * 255.0, 0, 255).astype(np.uint8)
            gray = cv2.cvtColor(img_8u, cv2.COLOR_RGB2GRAY)
            
            # Use adaptive thresholding to handle uneven lighting
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
            
            contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            
            squares = []
            h, w = gray.shape
            min_area = (h * w) * 0.0001  # Patch must be at least 0.01% of image
            max_area = (h * w) * 0.05    # Patch cannot be larger than 5% of image
            
            for c in contours:
                area = cv2.contourArea(c)
                if min_area < area < max_area:
                    peri = cv2.arcLength(c, True)
                    approx = cv2.approxPolyDP(c, 0.04 * peri, True)
                    if len(approx) == 4:
                        x, y, bw, bh = cv2.boundingRect(approx)
                        aspect_ratio = float(bw) / bh
                        # Macbeth patches are square
                        if 0.8 < aspect_ratio < 1.2:
                            squares.append((x, y, bw, bh))
                            
            if not squares:
                return image
                
            # We want to find the largest cluster of squares.
            # A simple clustering: find the bounding box that contains the most squares 
            # within a reasonable area. Or just use DBSCAN on the centroids.
            # Since OpenCV doesn't have DBSCAN built-in, we can just find the median size 
            # of the squares and filter outliers.
            
            # Sort squares by area and take the median 50%
            squares.sort(key=lambda s: s[2]*s[3])
            q1 = len(squares) // 4
            q3 = q1 * 3
            if q3 > q1:
                valid_squares = squares[q1:q3]
            else:
                valid_squares = squares
                
            # Bounding box of valid squares
            min_x = min(s[0] for s in valid_squares)
            min_y = min(s[1] for s in valid_squares)
            max_x = max(s[0] + s[2] for s in valid_squares)
            max_y = max(s[1] + s[3] for s in valid_squares)
            
            # Check if this cluster makes sense (aspect ratio of chart is ~1.5)
            cw, ch = max_x - min_x, max_y - min_y
            if cw > 0 and ch > 0 and 0.5 < (cw / ch) < 3.0:
                # Add margin
                margin_x = int(cw * 0.05)
                margin_y = int(ch * 0.05)
                
                # Check if it contains enough squares to be a chart (at least 12 patches found)
                # If not, it might just be noise. But if it's the only cluster, we'll try it.
                if len(valid_squares) >= 6:
                    x1 = max(0, min_x - margin_x)
                    y1 = max(0, min_y - margin_y)
                    x2 = min(w, max_x + margin_x)
                    y2 = min(h, max_y + margin_y)
                    return image[y1:y2, x1:x2]
                    
        except Exception as e:
            print(f"Macbeth autocrop failed: {e}")
            
        return image
