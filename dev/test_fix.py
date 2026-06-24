import sys

with open('e:/PROJECTS/HDRI_Match_Plate/hdri_match/io/loader.py', 'r') as f:
    content = f.read()

content = content.replace('''    if not _IN_NUKE:
        try:
            import OpenEXR''', '''    try:
        if _IN_NUKE: raise Exception("Nuke segfault protection")
        import OpenEXR''')

with open('e:/PROJECTS/HDRI_Match_Plate/hdri_match/io/loader.py', 'w') as f:
    f.write(content)
