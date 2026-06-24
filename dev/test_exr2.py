import sys
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.io.exr_pure import read_multipart_exr_parts, _decompress_zips_scanline
import numpy as np

file_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'
parts = read_multipart_exr_parts(file_path)
p = next(p for p in parts if p['name'] == 'C_Light_cool')

import struct
w, h = p['width'], p['height']
channels = p['channels']
offsets = p['offsets']
data = p['_data']
is_mp = True
compress = p['compress']

row_bytes = [w * (2 if pt == 1 else 4) for (_, pt) in channels]
result = np.zeros((h, w, len(channels)), dtype=np.float32)

for off in offsets:
    if off + 12 > len(data): continue
    _pnum = struct.unpack('<I', data[off:off+4])[0]; off += 4
    scan_y = struct.unpack('<I', data[off:off+4])[0]; off += 4
    data_sz = struct.unpack('<I', data[off:off+4])[0]; off += 4
    raw_chunk = data[off:off+data_sz]
    
    scan_data = _decompress_zips_scanline(raw_chunk)
    lines_in_block = min(16, h - scan_y)
    
    sc_off = 0
    for dy in range(lines_in_block):
        for ci, (ch_name, ptype) in enumerate(channels):
            nb = row_bytes[ci]
            strip = scan_data[sc_off:sc_off + nb]
            sc_off += nb
            if len(strip) < nb: continue
            
            if ptype == 1:
                arr = np.frombuffer(strip, dtype='<f2').astype(np.float32)
            else:
                arr = np.frombuffer(strip, dtype='<f4').astype(np.float32)
                
            result[scan_y + dy, :, ci] = arr

print('RGB shape:', result.shape, 'min:', result.min(), 'max:', result.max())
