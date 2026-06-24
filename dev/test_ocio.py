import sys
import numpy as np
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.core.colorspace import ColorSpaceManager

csm = ColorSpaceManager()
if csm.config:
    print("OCIO Config loaded successfully.")
    img = np.ones((10, 10, 3), dtype=np.float32)
    try:
        res = csm.transform_image(img, "Linear", "ACEScg")
        print(f"Transform Linear->ACEScg max: {res.max()}, min: {res.min()}, has NaN: {np.isnan(res).any()}")
    except Exception as e:
        print("Transform failed:", e)
else:
    print("No OCIO config loaded.")
