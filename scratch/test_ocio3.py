import os
import PyOpenColorIO as OCIO
try:
    config_path = r"C:\Program Files\Nuke14.0v5\plugins\OCIOConfigs\configs\aces_1.2\config.ocio"
    import glob
    paths = glob.glob(r"C:\Program Files\Nuke*\plugins\OCIOConfigs\configs\aces_1.2\config.ocio")
    if paths: config_path = paths[0]
    
    config = OCIO.Config.CreateFromFile(config_path)
    print("Default display:", config.getDefaultDisplay())
    display = config.getDefaultDisplay()
    views = []
    for v in config.getViews(display):
        views.append(v)
    print("Views:", views)
except Exception as e:
    print(e)
