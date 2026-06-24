import sys
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.io.exr_pure import read_multipart_exr_parts
import numpy as np
import struct
import zlib

file_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'
parts = read_multipart_exr_parts(file_path)
p = next(p for p in parts if p['name'] == 'C')

w, h = p['width'], p['height']
channels = p['channels']
offsets = p['offsets']
data = p['_data']
row_bytes = [w * (2 if pt == 1 else 4) for (_, pt) in channels]

for off in offsets:
    if off + 12 > len(data): continue
    _pnum = struct.unpack('<I', data[off:off+4])[0]; off += 4
    scan_y = struct.unpack('<I', data[off:off+4])[0]; off += 4
    data_sz = struct.unpack('<I', data[off:off+4])[0]; off += 4
    raw = zlib.decompress(data[off:off+data_sz])
    lines_in_block = min(16, h - scan_y)
    expected = sum(row_bytes) * lines_in_block
    print(f"y={scan_y}, decompressed bytes={len(raw)}, expected={expected}")
    break
