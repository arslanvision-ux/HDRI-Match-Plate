import sys
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.io.exr_pure import read_multipart_exr_parts

parts = read_multipart_exr_parts('E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr')
print(f'Parts: {len(parts)}')
p = parts[0]
print(f"name: {p.get('name')}, ymin: {p.get('_ymin')}, width: {p.get('width')}, height: {p.get('height')}, compress: {p.get('compress')}")
