import sys
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.io.exr_pure import read_multipart_exr_parts, read_part_as_rgb, read_part_alpha
file_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'
parts = read_multipart_exr_parts(file_path)
print('Found', len(parts), 'parts')
for p in parts:
    print('Part:', p['name'])

p = next(p for p in parts if p['name'] == 'C_Light_cool')
print('Decoding RGB...')
rgb = read_part_as_rgb(file_path, p)
print('RGB shape:', rgb.shape, 'min:', rgb.min(), 'max:', rgb.max())

print('Decoding Alpha...')
alpha = read_part_alpha(file_path, p)
print('Alpha shape:', alpha.shape, 'min:', alpha.min(), 'max:', alpha.max())
