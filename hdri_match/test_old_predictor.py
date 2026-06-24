import sys
sys.path.append('e:/PROJECTS/HDRI_Match_Plate')
from hdri_match.io.exr_pure import read_multipart_exr_parts
import numpy as np
import struct
import zlib
import cv2

file_path = 'E:/PROJECTS/HDRI_Match_Plate/input_hdri_plate/7/render/table.exr'
parts = read_multipart_exr_parts(file_path)
p = next(p for p in parts if p['name'] == 'C')

w, h = p['width'], p['height']
channels = p['channels']
offsets = p['offsets']
data = p['_data']
row_bytes = [w * (2 if pt == 1 else 4) for (_, pt) in channels]

def unpredict_old(raw):
    n = len(raw)
    half = (n + 1) // 2
    arr = np.frombuffer(raw, dtype=np.uint8).copy().view(np.int8)
    np.cumsum(arr, out=arr)
    arr2 = arr.view(np.uint8)
    uninterleaved = np.empty(n, dtype=np.uint8)
    uninterleaved[0::2] = arr2[:half]
    uninterleaved[1::2] = arr2[half:]
    return uninterleaved.tobytes()

result = np.zeros((h, w, len(channels)), dtype=np.float32)

for off in offsets:
    if off + 12 > len(data): continue
    _pnum = struct.unpack('<I', data[off:off+4])[0]; off += 4
    scan_y = struct.unpack('<I', data[off:off+4])[0]; off += 4
    data_sz = struct.unpack('<I', data[off:off+4])[0]; off += 4
    raw = zlib.decompress(data[off:off+data_sz])
    scan_data = unpredict_old(raw)
    
    sc_off = 0
    for ci, (ch_name, ptype) in enumerate(channels):
        nb = row_bytes[ci]
        strip = scan_data[sc_off:sc_off + nb]
        sc_off += nb
        if len(strip) < nb: continue
        if ptype == 1: arr = np.frombuffer(strip, dtype='<f2').astype(np.float32)
        else: arr = np.frombuffer(strip, dtype='<f4').astype(np.float32)
        result[scan_y, :, ci] = arr

# Alpha is index 0
alpha = result[..., 0]
alpha = np.clip(alpha, 0.0, 1.0)
cv2.imwrite('old_alpha_test.png', (alpha * 255).astype(np.uint8))
