import os
import PyOpenColorIO as OCIO
try:
    config = OCIO.GetCurrentConfig()
    print("Default display:", config.getDefaultDisplay())
    display = config.getDefaultDisplay()
    print("Views:", config.getViews(display))
except Exception as e:
    print(e)
