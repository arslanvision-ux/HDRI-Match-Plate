"""
Pure-Python OpenEXR reader — single-part AND multi-part (Houdini/Karma style).
Uses only `struct`, `zlib`, and `numpy` — no native DLLs, no Nuke conflicts.

Supported compressions:  NONE (0),  ZIPS (2, per-scanline ZIP),  ZIP (3, multi-scanline ZIP).
The ZIPS/ZIP decode mirrors OpenEXR's ImfZipCompressor.cpp:
    1. zlib.decompress()
    2. delta un-predict  (cumulative sum on signed int8, wraps at ±127)
    3. byte un-interleave (even-indexed bytes stored in first half, odd in second)

Multi-part layout:
    magic(4) + version(4)
    N × attribute headers, each null-terminated; double-null ends all headers
    N × chunk-offset tables  (chunkCount × 8-byte absolute file offsets each)
    interleaved scanline chunks: part_num(4) + y(4) + data_size(4) + data
"""
import struct
import zlib
import numpy as np


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_until_null(buf: bytes, offset: int):
    """(bytes_before_null, offset_past_null)"""
    end = buf.find(b'\x00', offset)
    if end == -1:
        return buf[offset:], len(buf)
    return buf[offset:end], end + 1


def _parse_channels(attr_data: bytes) -> list:
    """Parse chlist → [(ch_name, pixel_type_int), ...]  (alphabetical order)."""
    channels = []
    off = 0
    while off < len(attr_data):
        name_bytes, off = _read_until_null(attr_data, off)
        if not name_bytes:
            break
        ch_name = name_bytes.decode('ascii', errors='replace')
        if off + 4 > len(attr_data):
            break
        ptype = struct.unpack('<I', attr_data[off:off + 4])[0]
        # pixelType(4) + pLinear(1)+reserved(3) + xSampling(4) + ySampling(4) = 16
        off += 16
        channels.append((ch_name, ptype))
    return channels


def _parse_data_window(attr_data: bytes):
    """Return (width, height) from box2i attribute."""
    if len(attr_data) < 16:
        return 0, 0
    x_min, y_min, x_max, y_max = struct.unpack('<4i', attr_data[:16])
    return x_max - x_min + 1, y_max - y_min + 1


def _parse_one_header(data: bytes, offset: int):
    """Parse one EXR attribute header block.
    Returns (attrs_dict, new_offset) or ({}, offset) on terminating null."""
    attrs = {}
    while offset < len(data):
        if data[offset] == 0:
            offset += 1
            break
        name_bytes, offset = _read_until_null(data, offset)
        if not name_bytes:
            break
        type_bytes, offset = _read_until_null(data, offset)
        if offset + 4 > len(data):
            break
        attr_size = struct.unpack('<I', data[offset:offset + 4])[0]
        offset += 4
        attr_data = data[offset:offset + attr_size]
        offset += attr_size
        attrs[name_bytes.decode('ascii', errors='replace')] = (
            type_bytes.decode('ascii', errors='replace'), attr_data)
    return attrs, offset


def _decompress_zips_scanline(compressed: bytes) -> bytes:
    """Decompress one ZIPS/ZIP scanline chunk.

    Order per OpenEXR ImfZipCompressor.cpp (decoder):
      1. zlib inflate
      2. delta un-predict (with -128 offset)
      3. byte un-interleave (interleaved → contiguous)
    """
    raw = zlib.decompress(compressed)
    n = len(raw)

    # Step 2: delta un-predict
    # Formula: d[i] = d[i-1] + d[i] - 128
    arr = np.frombuffer(raw, dtype=np.uint8)
    t = arr.astype(np.int32)
    t[1:] -= 128
    np.cumsum(t, out=t)
    arr2 = t.astype(np.uint8)

    # Step 3: byte un-interleave
    half = (n + 1) // 2
    result = np.empty(n, dtype=np.uint8)
    result[0::2] = arr2[:half]
    result[1::2] = arr2[half:]

    return result.tobytes()


# ---------------------------------------------------------------------------
# Public: parse all part metadata
# ---------------------------------------------------------------------------

def read_multipart_exr_parts(file_path: str) -> list:
    """Parse a (possibly multi-part) EXR and return a list of part descriptors.

    Each dict:
        'name'     : str
        'channels' : [(ch_name, ptype_int), ...]
        'width'    : int
        'height'   : int
        'compress' : int  (0=NONE, 2=ZIPS, 3=ZIP)
        'offsets'  : [absolute_byte_offset_per_scanline, ...]
        '_data'    : bytes  (full file, shared reference — no copy)
    """
    with open(file_path, 'rb') as f:
        data = f.read()

    if len(data) < 8 or data[:4] != b'\x76\x2f\x31\x01':
        raise ValueError(f'Not a valid OpenEXR file: {file_path}')

    version_flags = struct.unpack('<I', data[4:8])[0]
    is_multipart = bool(version_flags & 0x1000)

    # ── 1. Parse all part headers ──
    offset = 8
    raw_parts = []
    while offset < len(data):
        if data[offset] == 0:
            offset += 1
            break
        attrs, offset = _parse_one_header(data, offset)
        if not attrs:
            break
        raw_parts.append(attrs)

    # ── 2. Read chunk-offset tables ──
    # For each part: height × 8-byte unsigned absolute file offsets.
    parts = []
    for attrs in raw_parts:
        p = {}
        p['name'] = (attrs.get('name', ('', b''))[1]
                     .rstrip(b'\x00').decode('ascii', errors='replace'))
        p['channels'] = (_parse_channels(attrs['channels'][1])
                         if 'channels' in attrs else [])
        if 'dataWindow' in attrs:
            x_min, y_min, x_max, y_max = struct.unpack('<4i', attrs['dataWindow'][1][:16])
            p['width'], p['height'] = x_max - x_min + 1, y_max - y_min + 1
            p['_ymin'] = y_min
        else:
            p['width'], p['height'], p['_ymin'] = 0, 0, 0
            
        comp_raw = attrs.get('compression', ('', b'\x00'))[1]
        p['compress'] = comp_raw[0] if comp_raw else 0
        p['_data'] = data
        p['attrs'] = attrs

        h = p['height']
        if h > 0 and offset + h * 8 <= len(data):
            fmt = f'<{h}Q'
            p['offsets'] = list(struct.unpack(fmt, data[offset:offset + h * 8]))
            offset += h * 8
        else:
            p['offsets'] = []

        parts.append(p)

    return parts


# ---------------------------------------------------------------------------
# Public: decode individual parts
# ---------------------------------------------------------------------------

def read_part_as_rgb(file_path: str, part: dict) -> np.ndarray:
    """Decode one part into float32 (H, W, 3) RGB.  Returns None if no RGB."""
    channels = part['channels']
    w, h = part['width'], part['height']
    offsets = part['offsets']
    data = part['_data']
    is_multipart = bool(struct.unpack('<I', data[4:8])[0] & 0x1000)

    if w == 0 or h == 0 or not channels or not offsets:
        return None

    r_idx = g_idx = b_idx = None
    for ci, (ch_name, _) in enumerate(channels):
        suffix = ch_name.rsplit('.', 1)[-1].upper()
        if suffix in ('R', 'RED')   and r_idx is None: r_idx = ci
        if suffix in ('G', 'GREEN') and g_idx is None: g_idx = ci
        if suffix in ('B', 'BLUE')  and b_idx is None: b_idx = ci

    if None in (r_idx, g_idx, b_idx):
        return None

    raw = _decode_via_offsets(data, offsets, w, h, channels,
                               is_multipart, part.get('compress', 0), part.get('_ymin', 0))
    if raw is None:
        return None
    return np.stack([raw[..., r_idx], raw[..., g_idx], raw[..., b_idx]], axis=-1)


def read_part_alpha(file_path: str, part: dict) -> np.ndarray:
    """Return alpha (H, W) float32 from a part, or None."""
    channels = part['channels']
    w, h = part['width'], part['height']
    offsets = part['offsets']
    data = part['_data']
    is_multipart = bool(struct.unpack('<I', data[4:8])[0] & 0x1000)

    if w == 0 or h == 0 or not channels or not offsets:
        return None

    a_idx = None
    for ci, (ch_name, _) in enumerate(channels):
        suffix = ch_name.rsplit('.', 1)[-1].upper()
        if suffix in ('A', 'ALPHA') and a_idx is None:
            a_idx = ci

    if a_idx is None:
        return None

    raw = _decode_via_offsets(data, offsets, w, h, channels,
                               is_multipart, part.get('compress', 0), part.get('_ymin', 0))
    if raw is None:
        return None
    return raw[..., a_idx]


def _decode_via_offsets(data: bytes, offsets: list, width: int, height: int,
                         channels: list, is_multipart: bool,
                         compress: int = 0, ymin: int = 0) -> np.ndarray:
    """Decode all scanlines using the pre-parsed chunk-offset table."""
    n_ch = len(channels)
    result = np.zeros((height, width, n_ch), dtype=np.float32)
    row_bytes = [width * (2 if ptype == 1 else 4) for (_, ptype) in channels]

    for chunk_offset in offsets:
        off = chunk_offset
        if is_multipart:
            if off + 12 > len(data):
                continue
            _pnum   = struct.unpack('<I', data[off:off + 4])[0];  off += 4
            scan_y  = struct.unpack('<I', data[off:off + 4])[0];  off += 4
            data_sz = struct.unpack('<I', data[off:off + 4])[0];  off += 4
        else:
            if off + 8 > len(data):
                continue
            scan_y  = struct.unpack('<I', data[off:off + 4])[0];  off += 4
            data_sz = struct.unpack('<I', data[off:off + 4])[0];  off += 4

        if scan_y < ymin or scan_y >= ymin + height or off + data_sz > len(data):
            continue

        raw_chunk = data[off:off + data_sz]
        local_y = scan_y - ymin

        # Decompress if needed
        if compress in (2, 3):  # ZIPS or ZIP
            try:
                scan_data = _decompress_zips_scanline(raw_chunk)
            except Exception:
                continue
        else:
            scan_data = raw_chunk  # NONE: raw bytes directly

        lines_in_block = min(16 if compress == 3 else 1, height - local_y)

        # Decode channels
        sc_off = 0
        for ci, (ch_name, ptype) in enumerate(channels):
            nb = row_bytes[ci]
            channel_size = nb * lines_in_block
            strip = scan_data[sc_off:sc_off + channel_size]
            sc_off += channel_size
            if len(strip) < channel_size:
                break
            
            if ptype == 1:   # HALF → float16 little-endian
                arr = np.frombuffer(strip, dtype='<f2').astype(np.float32)
            else:            # FLOAT32 little-endian
                arr = np.frombuffer(strip, dtype='<f4').astype(np.float32)
            
            arr = arr.reshape((lines_in_block, width))
            result[local_y:local_y + lines_in_block, :, ci] = arr

    return result


# ---------------------------------------------------------------------------
# Legacy single-file API (Nuke temp-file compatibility)
# ---------------------------------------------------------------------------

def read_uncompressed_exr(file_path: str) -> np.ndarray:
    """Read part 0 of an EXR (any compression) into (H, W, C) float32."""
    parts = read_multipart_exr_parts(file_path)
    if not parts:
        return None
    p = parts[0]
    data = p['_data']
    is_mp = bool(struct.unpack('<I', data[4:8])[0] & 0x1000)
    return _decode_via_offsets(data, p['offsets'], p['width'], p['height'],
                                p['channels'], is_mp, p.get('compress', 0), p.get('_ymin', 0))


def read_uncompressed_exr_single_channel(file_path: str) -> np.ndarray:
    """Read first channel of part 0 as a 2D float32 array."""
    arr = read_uncompressed_exr(file_path)
    if arr is None:
        return None
    return arr[..., 0] if arr.ndim == 3 else arr