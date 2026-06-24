import traceback

def log_ocio():
    try:
        import PyOpenColorIO as OCIO
        config = OCIO.GetCurrentConfig()
        if config:
            display = config.getDefaultDisplay()
            views = config.getViews(display)
            with open("C:/Users/test/ocio_debug.txt", "w") as f:
                f.write(f"Display: {display}\n")
                f.write(f"Views type: {type(views)}\n")
                f.write(f"Views list: {list(views)}\n")
    except Exception as e:
        with open("C:/Users/test/ocio_debug.txt", "w") as f:
            f.write(traceback.format_exc())

log_ocio()
