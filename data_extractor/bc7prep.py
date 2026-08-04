"""纯 Python bc7prep 解码器 (Oodle Texture 的 BC7 预处理格式)

把 Oodle Texture 编码的纹理数据还原成标准 BC7 块流。

格式参考: OodleUE 2.9.15 src/oodle2/texturert/bc7prep_decode.cpp
bc7prep 是 100% 无损的位重排, 解码输出 = 游戏原始 BC7 (与 pfsunpack2 逐位一致)。
"""

import struct

M64 = 0xFFFFFFFFFFFFFFFF

BC7PREP_HEADER_VERSION = 0x000007BC
BC7PREP_MODE_COUNT = 10
BC7PREP_CHUNK_BLOCK_COUNT = 2048

BC7PREP_FLAG_SPLIT0 = 1
BC7PREP_FLAG_SWITCH_COLORSPACE = 1 << 16
BC7PREP_FLAG_ALL_ASSIGNED = ((BC7PREP_FLAG_SPLIT0 << BC7PREP_MODE_COUNT) - 1) | BC7PREP_FLAG_SWITCH_COLORSPACE

MODE_SIZES = [16, 16, 16, 16, 16, 16, 16, 16, 16, 4]
# decode_split_pos (SPLIT(x,sz) => x or sz)
MODE_SPLITS = [8, 8, 12, 12, 6, 8, 8, 12, 16, 4]


# ── 位操作 ──────────────────────────────────────────────

def bit_extract(val: int, start: int, width: int) -> int:
    if width == 0:
        return 0
    return (val >> start) & ((1 << width) - 1)


def packed_add(a: int, b: int, msb_mask: int, nonmsb_mask: int = None) -> int:
    if nonmsb_mask is None:
        nonmsb_mask = ~msb_mask & M64
    low = ((a & nonmsb_mask) + (b & nonmsb_mask)) & M64
    return (low ^ ((a ^ b) & msb_mask)) & M64


def packed_sub(a: int, b: int, msb_mask: int, nonmsb_mask: int = None) -> int:
    if nonmsb_mask is None:
        nonmsb_mask = ~msb_mask & M64
    low = ((a | msb_mask) - (b & nonmsb_mask)) & M64
    return (low ^ ((a ^ ~b) & msb_mask)) & M64


def decorr_to_RGB_packed(r: int, g: int, b: int, msb_mask: int, nonmsb_mask: int = None):
    """就地 YCrCb->RGB: 输入 (r=Y, g=Cr, b=Cb) -> 输出 (r=R, g=G, b=B)"""
    y = r
    cr = g
    cb = b
    if nonmsb_mask is None:
        nonmsb_mask = ~msb_mask & M64
    r = packed_add(y, cr, msb_mask, nonmsb_mask)
    g = y
    b = packed_add(y, cb, msb_mask, nonmsb_mask)
    return r, g, b


def mode4_decorr_fast(rgba: int) -> int:
    # broadcast Y (G) values
    ybroad = ((rgba & 0x3FF) * (1 + (1 << 10) + (1 << 20))) & M64
    crcba = ((rgba >> 10) & 0x3FF) | (rgba & 0xFFFFF00000)
    return packed_add(ybroad, crcba, 0x8421084210)


# ── compact / expand 位重排 ─────────────────────────────

def compact32to7_2x(x: int) -> int:
    return ((x & 0x7F) | ((x >> 25) & 0x3F80))


def compact24to7_3x(x: int) -> int:
    return ((x & 0x7F) | ((x >> 17) & 0x3F80) | ((x >> 34) & 0x1FC000))


def compact24to7_2x(x: int) -> int:
    return ((x & 0x7F) | ((x >> 17) & 0x3F80))


def compact16to1_4x(x: int) -> int:
    x &= 0x0001000100010001
    x = (x * 0x0001000200040008) & M64
    return (x >> 48)


def compact16to1_2x(x: int) -> int:
    return (x & 1) | ((x >> 15) & 2)


def compact16to5_4x(x: int) -> int:
    x &= 0x001F001F001F001F
    x = ((x >> 11) | x) & 0x000003FF000003FF
    x = ((x >> 22) | x) & 0xFFFFF
    return x


def compact16to5_2x(x: int) -> int:
    return (x & 0x1F) | ((x >> 11) & 0x3E0)


def compact16to6_4x(x: int) -> int:
    x = ((x >> 10) | x) & 0x00000FFF00000FFF
    x = ((x >> 20) | x) & 0xFFFFFF
    return x


def compact8to7_8x(x: int) -> int:
    stay1 = 0x007F007F007F007F
    move1 = stay1 << 8
    x = ((x & move1) >> 1) | (x & stay1)
    stay2 = 0x00003FFF00003FFF
    x = ((x & ~stay2) >> 2) | (x & stay2)
    stay4 = 0x000000000FFFFFFF
    x = ((x & ~stay4) >> 4) | (x & stay4)
    return x


def compact8to7_6x(x: int) -> int:
    stay1 = 0x007F007F007F
    move1 = stay1 << 8
    x = ((x & move1) >> 1) | (x & stay1)
    x = ((x >> 0) & 0x0000000FFFF) | ((x >> 2) & 0x0000FFFC000) | ((x >> 4) & 0x3FFF0000000)
    return x


def compact8to1_8x(x: int) -> int:
    x &= 0x0101010101010101
    x = (x * 0x0102040810204080) & M64
    return (x >> 56)


def expand4to5_12x(x: int) -> int:
    x = ((x & 0x0000FFFF00000000) << 8) | ((x & 0x00000000FFFF0000) << 4) | ((x & 0x000000000000FFFF) << 0)
    stay2 = 0x0000FF000FF000FF
    x = ((x & ~stay2) << 2) | (x & stay2)
    x += x & 0x03C0F03C0F03C0F0
    return x


def expand4to5_4x(x: int) -> int:
    x = ((x & 0x0FF00) << 2) | (x & 0x000FF)
    x += x & 0x3C0F0
    return x


def expand2to6_4x(x: int) -> int:
    x = ((x << 8) | x) & 0x0F00F
    x = ((x << 4) | x) & 0xC30C3
    return x


def expand1to5_12x(x: int) -> int:
    x &= 0xFFF
    x = (x * 0x100010001) & 0x0F0000F0000F
    x = (x * 0x1111) & 0x084210842108421
    return x


def expand1to5_4x(x: int) -> int:
    return ((x & 0xF) * 0x1111) & 0x8421


# ── 各 mode 的 un_munge ────────────────────────────────

def target_offs(idx: int) -> int:
    """块索引 -> 输出字节偏移 (每块 16 字节)"""
    return idx * 16


def un_munge_mode0(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        in_lo = int.from_bytes(first_ptr[iblock * advance0: iblock * advance0 + 8], 'little')
        in_hi = int.from_bytes(second_ptr[iblock * advance1: iblock * advance1 + 8], 'little')
        rbits = bit_extract(in_lo, 0, 24)
        gbits = bit_extract(in_lo, 24, 24)
        bbits = bit_extract(in_lo, 48, 16) | (bit_extract(in_hi, 0, 8) << 16)
        partbits = bit_extract(in_hi, 8, 4)
        if switch_cs:
            rbits, gbits, bbits = decorr_to_RGB_packed(rbits, gbits, bbits, 0x888888)
        lo = (1 | (partbits << 1) | (rbits << 5) | (gbits << 29) | (bbits << 53)) & M64
        hi = ((bbits >> 11) | (in_hi & ~0x1FFF)) & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode1(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        rgbs = int.from_bytes(first_ptr[iblock * advance0: iblock * advance0 + 8], 'little')
        extra = int.from_bytes(second_ptr[iblock * advance1: iblock * advance1 + 8], 'little')
        rbits = compact16to6_4x((rgbs >> 0) & 0x003F003F003F003F)
        gbits = compact16to6_4x((rgbs >> 5) & 0x003E003E003E003E)
        bbits = compact16to6_4x((rgbs >> 10) & 0x003E003E003E003E)
        expanded_gb = expand2to6_4x(extra & 0xFF)
        gbits |= (expanded_gb >> 0) & 0x41041
        bbits |= (expanded_gb >> 1) & 0x41041
        if switch_cs:
            rbits, gbits, bbits = decorr_to_RGB_packed(rbits, gbits, bbits, 0x820820)
        lo = (0x2 | ((extra >> 6) & 0xFC) | (rbits << 8) | (gbits << 32) | (bbits << 56)) & M64
        hi = ((bbits >> 8) | (extra & ~0xFFFF)) & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode2(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        o = iblock * advance0
        endpt0 = int.from_bytes(first_ptr[o:o + 8], 'little')
        endpt1 = int.from_bytes(first_ptr[o + 8:o + 12], 'little')
        index = int.from_bytes(second_ptr[iblock * advance1: iblock * advance1 + 4], 'little')
        rbits = compact16to5_4x(endpt0 >> 1) | (compact16to5_2x(endpt1 >> 1) << 20)
        gbits = compact16to5_4x(endpt0 >> 6) | (compact16to5_2x(endpt1 >> 6) << 20)
        bbits = compact16to5_4x(endpt0 >> 11) | (compact16to5_2x(endpt1 >> 11) << 20)
        partbits = compact16to1_4x(endpt0) | (compact16to1_2x(endpt1) << 4)
        if switch_cs:
            rbits, gbits, bbits = decorr_to_RGB_packed(rbits, gbits, bbits, 0x21084210)
        lo = (0x4 | (partbits << 3) | (rbits << 9) | (gbits << 39)) & M64
        hi = ((gbits >> 25) | (bbits << 5) | ((index & ~7) << 32)) & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode3(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        o = iblock * advance0
        endpt0 = int.from_bytes(first_ptr[o:o + 8], 'little')
        endpt1 = int.from_bytes(first_ptr[o + 8:o + 12], 'little')
        index = int.from_bytes(second_ptr[iblock * advance1: iblock * advance1 + 4], 'little')
        rbits = compact24to7_3x(endpt0 >> 0) | ((endpt1 & 0x007F00) << (21 - 8))
        gbits = compact24to7_3x(endpt0 >> 8) | ((endpt1 & 0x7F0000) << (21 - 16))
        bbits = compact24to7_2x(endpt0 >> 16) | (compact24to7_2x(endpt1) << 14)
        partbits = compact8to1_8x(endpt0 >> 7)
        if switch_cs:
            rbits, gbits, bbits = decorr_to_RGB_packed(rbits, gbits, bbits, 0x8102040)
        lo = (0x8 | ((partbits & 0x3F) << 4) | (rbits << 10) | (gbits << 38)) & M64
        hi = ((gbits >> 26) | (bbits << 2) | ((partbits & 0xC0) << 24) | (index << 32)) & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode4(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        o = iblock * advance0
        lo_ptr = o
        in_lo = int.from_bytes(first_ptr[lo_ptr:lo_ptr + 4], 'little') + (int.from_bytes(first_ptr[lo_ptr + 4:lo_ptr + 6], 'little') << 32)
        s = iblock * advance1
        in_hi0 = int.from_bytes(second_ptr[s:s + 2], 'little')
        in_hi1 = int.from_bytes(second_ptr[s + 2:s + 10], 'little')
        rgba = bit_extract(in_lo, 2, 40)
        if switch_cs:
            rgba = mode4_decorr_fast(rgba)
        crot = bit_extract(in_hi0, 0, 2)
        shift_amount = ((0 - crot) & 3) * 10
        xor_mask = (rgba ^ (rgba << shift_amount)) & 0xFFC0000000
        rgba ^= xor_mask
        rgba ^= (xor_mask >> shift_amount) & M64
        rgba += rgba & 0x0FFC0000000
        rgba += rgba & 0x1F000000000
        rgba |= ((in_lo & 3) * 0x21 & 0x41) << 30
        lo = (0x10 | (crot << 5) | (bit_extract(in_lo, 42, 1) << 7) | (rgba << 8) | (bit_extract(in_hi0, 2, 14) << 50)) & M64
        hi = in_hi1 & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode5(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        endpoints = int.from_bytes(first_ptr[iblock * advance0: iblock * advance0 + 8], 'little')
        indices = int.from_bytes(second_ptr[iblock * advance1: iblock * advance1 + 8], 'little')
        lo = 0x20
        crot = indices & 3
        if switch_cs:
            rbits = (endpoints >> 0) & 0x000000FE000000FE
            gbits = (endpoints >> 8) & 0x000000FE000000FE
            bbits = (endpoints >> 16) & 0x000000FE000000FE
            rbits, gbits, bbits = decorr_to_RGB_packed(rbits, gbits, bbits, 0x8000000080, 0x7E0000007E)
            endpoints = rbits | (gbits << 8) | (bbits << 16) | (endpoints & 0xFF010101FF010101)
            shift_amount = ((0 - crot) & 3) << 3
            xor_mask = (endpoints ^ (endpoints << shift_amount)) & 0xFF000000FF000000
            endpoints ^= xor_mask
            endpoints ^= (xor_mask >> shift_amount) & M64
            lo |= crot << 6
            lo |= compact32to7_2x(endpoints >> 1) << 8
            lo |= compact32to7_2x(endpoints >> 9) << 22
            lo |= compact32to7_2x(endpoints >> 17) << 36
            lo |= ((endpoints >> 24) & 0xFF) << 50
            lo |= ((endpoints >> 56) & 0x3F) << 58
        else:
            shift_amount = ((0 - crot) & 3) << 4
            xor_mask = (endpoints ^ (endpoints << shift_amount)) & 0xFFFF000000000000
            endpoints ^= xor_mask
            endpoints ^= (xor_mask >> shift_amount) & M64
            lo |= crot << 6
            lo |= compact8to7_6x(endpoints >> 1) << 8
            lo |= ((endpoints >> 48) & 0xFF) << 50
            lo |= ((endpoints >> 56) & 0x3F) << 58
        hi = (((endpoints >> 62) & 3) | (indices & ~3)) & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode6(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        endpoints = int.from_bytes(first_ptr[iblock * advance0: iblock * advance0 + 8], 'little')
        indices = int.from_bytes(second_ptr[iblock * advance1: iblock * advance1 + 8], 'little')
        lo = 0x40
        if switch_cs:
            rbits = compact32to7_2x(endpoints >> 0)
            gbits = compact32to7_2x(endpoints >> 8)
            bbits = compact32to7_2x(endpoints >> 16)
            abits = compact32to7_2x(endpoints >> 24)
            rbits, gbits, bbits = decorr_to_RGB_packed(rbits, gbits, bbits, 0x2040)
            lo |= rbits << 7
            lo |= gbits << 21
            lo |= bbits << 35
            lo |= abits << 49
        else:
            deint = compact8to7_8x(endpoints)
            lo |= deint << 7
        lo = (lo | (endpoints & (1 << 63))) & M64
        hi = indices & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode7(out: bytearray, first_ptr: bytes, second_ptr: bytes, nblocks: int,
                   target: list, advance0: int, advance1: int, switch_cs: bool):
    for iblock in range(nblocks):
        o = iblock * advance0
        prgbs = int.from_bytes(first_ptr[o:o + 8], 'little')
        rest = int.from_bytes(first_ptr[o + 8:o + 12], 'little')
        rest |= int.from_bytes(second_ptr[iblock * advance1: iblock * advance1 + 4], 'little') << 32
        if switch_cs:
            rbits = compact16to5_4x(prgbs >> 1)
            gbits = compact16to5_4x(prgbs >> 6)
            bbits = compact16to5_4x(prgbs >> 11)
            pbits = compact16to1_4x(prgbs)
            abits = bit_extract(rest, 8, 20)
            rbits, gbits, bbits = decorr_to_RGB_packed(rbits, gbits, bbits, 0x84210)
            lo = 0x80 | (bit_extract(rest, 28, 6) << 8) | (rbits << 14) | (gbits << 34) | (bbits << 54)
            hi = (bbits >> 10) | (abits << 10) | (pbits << 30)
        else:
            pbits = bit_extract(rest, 8, 4)
            rgbbits = (expand4to5_12x(prgbs) << 1) | expand1to5_12x(rest >> 12)
            abits = (expand4to5_4x(prgbs >> 48) << 1) | expand1to5_4x(rest >> 24)
            lo = 0x80 | (bit_extract(rest, 28, 6) << 8) | (rgbbits << 14)
            hi = (rgbbits >> 50) | (abits << 10) | (pbits << 30)
        hi = (hi | (rest & ~0x3FFFFFFFF)) & M64
        dest = target_offs(target[iblock])
        out[dest:dest + 8] = lo.to_bytes(8, 'little')
        out[dest + 8:dest + 16] = hi.to_bytes(8, 'little')


def un_munge_mode8(out: bytearray, first_ptr: bytes, nblocks: int, target: list, advance0: int):
    for iblock in range(nblocks):
        dest = target_offs(target[iblock])
        out[dest:dest + 16] = first_ptr[iblock * advance0: iblock * advance0 + 16]


def un_munge_mode9(out: bytearray, coded_block: bytes, nblocks: int, target: list,
                   switch_cs: bool):
    """mode9: 4 字节 RGBA8 固体色 -> mode5 块"""
    pos = 0
    ti = 0
    while ti < nblocks:
        r = coded_block[pos]
        g = coded_block[pos + 1]
        b = coded_block[pos + 2]
        if switch_cs:
            # decorr_to_RGB(y=r, cr=g, cb=b, 255): R=(r+g)&255, G=r, B=(r+b)&255
            r_orig = r
            r = (r_orig + g) & 255
            b = (r_orig + b) & 255

        bit6_mask = (0x40 << 8) | (0x40 << 22) | (0x40 << 36)
        lo7_mask = (0x7F << 8) | (0x7F << 22) | (0x7F << 36)
        color_bits = (r << 8) | (g << 22) | (b << 36)
        t = color_bits << 6
        color_bits = ((color_bits >> 1) & lo7_mask) - (color_bits & ~lo7_mask)
        color_bits += t + (t & bit6_mask)
        color_bits |= coded_block[pos + 3] << 50
        color_bits |= 0x20
        coded_block32 = int.from_bytes(coded_block[pos:pos + 4], 'little')
        # 连续相同块批量写
        while True:
            dest = target_offs(target[ti])
            out[dest:dest + 8] = (color_bits & M64).to_bytes(8, 'little')
            out[dest + 8:dest + 16] = (0xAAAAAAAC).to_bytes(8, 'little')
            ti += 1
            pos += 4
            if ti >= nblocks:
                return
            if int.from_bytes(coded_block[pos:pos + 4], 'little') != coded_block32:
                break


# ── 主解码 ──────────────────────────────────────────────

def bc7prep_read_header(header: bytes):
    """解析 48 字节头部, 返回 (num_blocks, payload_size) 或 None"""
    if len(header) < 48:
        return None
    version, flags = struct.unpack_from('<II', header, 0)
    if version != BC7PREP_HEADER_VERSION:
        return None
    if (flags & ~BC7PREP_FLAG_ALL_ASSIGNED) != 0:
        return None
    mode_counts = list(struct.unpack_from('<10I', header, 8))
    total_blocks = 0
    payload = 0
    for i in range(BC7PREP_MODE_COUNT):
        total_blocks += mode_counts[i]
        payload += mode_counts[i] * MODE_SIZES[i]
    payload += (total_blocks + 1) // 2
    return total_blocks, payload, flags, mode_counts


def bc7prep_decode(bc7prep_data: bytes, bc7prep_data_size: int,
                   header: bytes) -> bytes:
    """把 bc7prep payload 解码成标准 BC7 块流 (num_blocks * 16 字节)

    参数:
        bc7prep_data: 指向 payload 起点的数据 (含 48 字节 header)
        bc7prep_data_size: bc7prep 数据总长
        header: 48 字节 OodleTexRT_BC7PrepHeader (通常是 bc7prep_data[0:48])
    """
    res = bc7prep_read_header(header)
    if res is None:
        raise ValueError('bc7prep: invalid header')
    num_blocks, expected_payload, flags, mode_counts = res
    if num_blocks == 0:
        return b''
    if bc7prep_data_size < expected_payload:
        raise ValueError('bc7prep: input too small')
    switch_cs = bool(flags & BC7PREP_FLAG_SWITCH_COLORSPACE)

    # prefix sum
    mode_pos = [0] * (BC7PREP_MODE_COUNT + 1)
    mode_idx = [0] * (BC7PREP_MODE_COUNT + 1)
    for i in range(BC7PREP_MODE_COUNT):
        mode_pos[i + 1] = mode_pos[i] + mode_counts[i] * MODE_SIZES[i]
        mode_idx[i + 1] = mode_idx[i] + mode_counts[i]

    # mode nibbles 在 payload 之后
    nibbles_start = mode_pos[BC7PREP_MODE_COUNT]

    # cursor 设置
    cursors0 = []
    cursors1 = []
    advance0 = []
    advance1 = []
    for i in range(BC7PREP_MODE_COUNT):
        split = MODE_SPLITS[i]
        if flags & (BC7PREP_FLAG_SPLIT0 << i):
            cursor0 = mode_pos[i]
            cursor1 = cursor0 + split * mode_counts[i]
            adv0 = split
            adv1 = MODE_SIZES[i] - split
        else:
            cursor0 = mode_pos[i]
            cursor1 = cursor0 + split
            adv0 = adv1 = MODE_SIZES[i]
        cursors0.append(cursor0)
        cursors1.append(cursor1)
        advance0.append(adv0)
        advance1.append(adv1)

    out = bytearray(num_blocks * 16)

    for chunk_base in range(0, num_blocks, BC7PREP_CHUNK_BLOCK_COUNT):
        blocks_in_chunk = min(num_blocks - chunk_base, BC7PREP_CHUNK_BLOCK_COUNT)
        # 排序: 读 nibbles -> 每 mode 的块索引
        mode_cur = [[] for _ in range(BC7PREP_MODE_COUNT + 1)]  # 最后一项 = 非法 mode 的收容所
        nib = nibbles_start + (chunk_base >> 1)
        # C++ 主排序循环: i 从 0 步进 2, 每个 nibble 字节含两块; 存全局块索引
        for j in range((blocks_in_chunk & ~1) // 2):
            two = bc7prep_data[nib + j]
            m0 = two & 0xF
            m1 = two >> 4
            # C++ 中 mode>9 会被路由到 mode_cur[0] (非法 mode), 解码后校验
            if m0 >= BC7PREP_MODE_COUNT:
                m0 = BC7PREP_MODE_COUNT
            if m1 >= BC7PREP_MODE_COUNT:
                m1 = BC7PREP_MODE_COUNT
            mode_cur[m0].append(chunk_base + j * 2)
            mode_cur[m1].append(chunk_base + j * 2 + 1)
        if blocks_in_chunk & 1:
            last = bc7prep_data[nib + (blocks_in_chunk >> 1)] & 0xF
            if last >= BC7PREP_MODE_COUNT:
                last = BC7PREP_MODE_COUNT
            mode_cur[last].append(chunk_base + blocks_in_chunk - 1)
        if mode_cur[BC7PREP_MODE_COUNT]:
            raise ValueError(f'bc7prep: 非法 mode nibble {mode_cur[BC7PREP_MODE_COUNT][0]}')

        # work phase: cursor 跨 chunk 持续累加 (C++ 中每个 chunk 后 cursor += count*advance)
        for i in range(BC7PREP_MODE_COUNT):
            count = len(mode_cur[i])
            if not count:
                continue
            c0 = cursors0[i]
            c1 = cursors1[i]
            a0 = advance0[i]
            a1 = advance1[i]
            first = bc7prep_data[c0:c0 + count * a0]
            second = bc7prep_data[c1:c1 + count * a1]
            if i in (0, 1, 2, 3, 4, 5, 6, 7):
                fn = [un_munge_mode0, un_munge_mode1, un_munge_mode2, un_munge_mode3,
                      un_munge_mode4, un_munge_mode5, un_munge_mode6, un_munge_mode7][i]
                fn(out, first, second, count, mode_cur[i], a0, a1, switch_cs)
            elif i == 8:
                un_munge_mode8(out, first, count, mode_cur[i], a0)
            else:
                un_munge_mode9(out, first, count, mode_cur[i], switch_cs)
            cursors0[i] = c0 + count * a0
            cursors1[i] = c1 + count * a1

    return bytes(out)
