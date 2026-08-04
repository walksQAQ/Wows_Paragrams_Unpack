"""
纯 Python Oodle Kraken 解压器

参考 domdfcoding/kraken-decompressor (GPLv3) C++ 源码。
实现 Oodle 3-Stream Huffman 解码 (Type 1/2) + LZ77 匹配复制。
"""

from __future__ import annotations

import struct
from typing import Optional


# ══════════════════════════════════════════════════════════
# 1. OodleBitReader — 24-bit 初始化填充 + refill/no-refill
# ══════════════════════════════════════════════════════════

class OodleBitReader:
    """匹配 C++ BitReader (MSB优先): 加载4字节, 从bit31读, 左移消耗, 右移补充"""
    __slots__ = ('data', 'ptr', 'bit_buf', 'bits_left')
    
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.ptr = offset
        self.bit_buf = 0
        self.bits_left = 0
        self._init_stream()
    
    def _init_stream(self):
        """匹配 C++ BitReader_Refill: 加载4字节 MSB优先到32位缓冲"""
        self.bit_buf = 0
        for _ in range(4):
            if self.ptr < len(self.data):
                self.bit_buf = (self.bit_buf << 8) | self.data[self.ptr]
                self.ptr += 1
                self.bits_left += 8
    
    def _init_stream_reverse(self):
        """反向流: 从末尾加载4字节, 小端序, 保持32位"""
        self.bit_buf = 0
        self.bits_left = 0
        for _ in range(4):
            if self.ptr > 0:
                self.ptr -= 1
                self.bit_buf = ((self.bit_buf << 8) | self.data[self.ptr]) & 0xFFFFFFFF
                self.bits_left += 8
    
    def refill(self):
        """C++ Refill: 右移8bit, 在24位加载新字节"""
        while self.bits_left <= 24 and self.ptr < len(self.data):
            self.bit_buf = (self.bit_buf >> 8) | (self.data[self.ptr] << 24)
            self.ptr += 1
            self.bits_left += 8
    
    def refill_reverse(self):
        """反向流补充: 从ptr-1加载到低位, 保持32位"""
        while self.bits_left <= 24 and self.ptr > 0:
            self.ptr -= 1
            self.bit_buf = ((self.bit_buf << 8) | self.data[self.ptr]) & 0xFFFFFFFF
            self.bits_left += 8
    
    def peek(self, n: int = 11) -> int:
        """窥视顶部 n 比特"""
        if self.bits_left < n:
            self.refill()
        return self.bit_buf >> (32 - n)
    
    def peek_reverse(self, n: int = 11) -> int:
        if self.bits_left < n:
            self.refill_reverse()
        return self.bit_buf >> (32 - n)
    
    def consume(self, n: int):
        """消耗顶部 n 比特 (左移)"""
        self.bit_buf = (self.bit_buf << n) & 0xFFFFFFFF
        self.bits_left -= n
        if self.bits_left <= 24:
            self.refill()
    
    def read_bit_nr(self) -> int:
        """读1比特 (从MSB, no refill)"""
        b = (self.bit_buf >> 31) & 1
        self.bit_buf = (self.bit_buf << 1) & 0xFFFFFFFF
        self.bits_left -= 1
        return b
    
    def read_bits_nr(self, n: int) -> int:
        """读 n 比特 (从MSB, no refill)"""
        val = self.bit_buf >> (32 - n)
        self.bit_buf = (self.bit_buf << n) & 0xFFFFFFFF
        self.bits_left -= n
        return val


# ══════════════════════════════════════════════════════════
# 2. 2048 条目规范 Huffman LUT (Bit-Reversed)
# ══════════════════════════════════════════════════════════

def _read_huff_codelens_old(br, syms: list[int],
                            code_prefix: list[int]) -> int:
    """oozextract huff_read_code_lengths_old — gamma 或 sparse 路径

    br: BitReaderP (powzix rotl 模型, 与 oozextract BitReader 一致)
    第一个选择位已被 _decode_huff_type12 消费 (bit0==0 → Old)。
    返回读取的符号数 (0 = 失败)
    """
    if br.read_bit_no_refill():
        # 完整 gamma 路径
        sym = 0
        num_symbols = 0
        avg_bits_x4 = 32
        forced_bits = br.read_bits_no_refill(2)
        thres_for_valid_gamma_bits = 1 << (31 - (20 >> forced_bits))
        skip_initial_zeros = br.read_bit()
        while sym != 256:
            if skip_initial_zeros:
                skip_initial_zeros = False
            else:
                if not (br.bits & 0xff000000):
                    return 0
                sym += br.read_bits_no_refill(2 * (br.leading_zeros() + 1)) - 1
                if sym >= 256:
                    break
            br.refill()
            if not (br.bits & 0xff000000):
                return 0
            n = br.read_bits_no_refill(2 * (br.leading_zeros() + 1)) - 1
            if sym + n > 256:
                return 0
            br.refill()
            num_symbols += n
            while True:
                if br.bits < thres_for_valid_gamma_bits:
                    return 0
                lz = br.leading_zeros()
                v = br.read_bits_no_refill(lz + forced_bits + 1) + ((lz - 1) << forced_bits)
                codelen = (-(v & 1) ^ (v >> 1)) + ((avg_bits_x4 + 2) >> 2)
                if codelen < 1 or codelen > 11:
                    return 0
                avg_bits_x4 = codelen + ((3 * avg_bits_x4 + 2) >> 2)
                br.refill()
                syms[code_prefix[codelen]] = sym
                code_prefix[codelen] += 1
                sym += 1
                n -= 1
                if n == 0:
                    break
        if sym != 256:
            return 0
        if num_symbols < 2:
            return 0
        return num_symbols
    else:
        # Sparse symbol encoding
        num_symbols = br.read_bits_no_refill(8)
        if num_symbols == 0:
            return 0
        if num_symbols == 1:
            syms[0] = br.read_bits_no_refill(8)
        else:
            codelen_bits = br.read_bits_no_refill(3)
            if codelen_bits > 4:
                return 0
            for _ in range(num_symbols):
                br.refill()
                sym = br.read_bits_no_refill(8)
                codelen = br.read_bits_no_refill_zero(codelen_bits) + 1
                if codelen > 11:
                    return 0
                syms[code_prefix[codelen]] = sym
                code_prefix[codelen] += 1
        return num_symbols


# ══════════════════════════════════════════════════════════
# Rice/Golomb 解码表 (C++ kRiceCodeBits2Value / kRiceCodeBits2Len)
# ══════════════════════════════════════════════════════════

_RICE_VAL = [
    0x80000000, 0x00000007, 0x10000006, 0x00000006, 0x20000005, 0x00000105, 0x10000005, 0x00000005,
    0x30000004, 0x00000204, 0x10000104, 0x00000104, 0x20000004, 0x00010004, 0x10000004, 0x00000004,
    0x40000003, 0x00000303, 0x10000203, 0x00000203, 0x20000103, 0x00010103, 0x10000103, 0x00000103,
    0x30000003, 0x00020003, 0x10010003, 0x00010003, 0x20000003, 0x01000003, 0x10000003, 0x00000003,
    0x50000002, 0x00000402, 0x10000302, 0x00000302, 0x20000202, 0x00010202, 0x10000202, 0x00000202,
    0x30000102, 0x00020102, 0x10010102, 0x00010102, 0x20000102, 0x01000102, 0x10000102, 0x00000102,
    0x40000002, 0x00030002, 0x10020002, 0x00020002, 0x20010002, 0x01010002, 0x10010002, 0x00010002,
    0x30000002, 0x02000002, 0x11000002, 0x01000002, 0x20000002, 0x00000012, 0x10000002, 0x00000002,
    0x60000001, 0x00000501, 0x10000401, 0x00000401, 0x20000301, 0x00010301, 0x10000301, 0x00000301,
    0x30000201, 0x00020201, 0x10010201, 0x00010201, 0x20000201, 0x01000201, 0x10000201, 0x00000201,
    0x40000101, 0x00030101, 0x10020101, 0x00020101, 0x20010101, 0x01010101, 0x10010101, 0x00010101,
    0x30000101, 0x02000101, 0x11000101, 0x01000101, 0x20000101, 0x00000111, 0x10000101, 0x00000101,
    0x50000001, 0x00040001, 0x10030001, 0x00030001, 0x20020001, 0x01020001, 0x10020001, 0x00020001,
    0x30010001, 0x02010001, 0x11010001, 0x01010001, 0x20010001, 0x00010011, 0x10010001, 0x00010001,
    0x40000001, 0x03000001, 0x12000001, 0x02000001, 0x21000001, 0x01000011, 0x11000001, 0x01000001,
    0x30000001, 0x00000021, 0x10000011, 0x00000011, 0x20000001, 0x00001001, 0x10000001, 0x00000001,
    0x70000000, 0x00000600, 0x10000500, 0x00000500, 0x20000400, 0x00010400, 0x10000400, 0x00000400,
    0x30000300, 0x00020300, 0x10010300, 0x00010300, 0x20000300, 0x01000300, 0x10000300, 0x00000300,
    0x40000200, 0x00030200, 0x10020200, 0x00020200, 0x20010200, 0x01010200, 0x10010200, 0x00010200,
    0x30000200, 0x02000200, 0x11000200, 0x01000200, 0x20000200, 0x00000210, 0x10000200, 0x00000200,
    0x50000100, 0x00040100, 0x10030100, 0x00030100, 0x20020100, 0x01020100, 0x10020100, 0x00020100,
    0x30010100, 0x02010100, 0x11010100, 0x01010100, 0x20010100, 0x00010110, 0x10010100, 0x00010100,
    0x40000100, 0x03000100, 0x12000100, 0x02000100, 0x21000100, 0x01000110, 0x11000100, 0x01000100,
    0x30000100, 0x00000120, 0x10000110, 0x00000110, 0x20000100, 0x00001100, 0x10000100, 0x00000100,
    0x60000000, 0x00050000, 0x10040000, 0x00040000, 0x20030000, 0x01030000, 0x10030000, 0x00030000,
    0x30020000, 0x02020000, 0x11020000, 0x01020000, 0x20020000, 0x00020010, 0x10020000, 0x00020000,
    0x40010000, 0x03010000, 0x12010000, 0x02010000, 0x21010000, 0x01010010, 0x11010000, 0x01010000,
    0x30010000, 0x00010020, 0x10010010, 0x00010010, 0x20010000, 0x00011000, 0x10010000, 0x00010000,
    0x50000000, 0x04000000, 0x13000000, 0x03000000, 0x22000000, 0x02000010, 0x12000000, 0x02000000,
    0x31000000, 0x01000020, 0x11000010, 0x01000010, 0x21000000, 0x01001000, 0x11000000, 0x01000000,
    0x40000000, 0x00000030, 0x10000020, 0x00000020, 0x20000010, 0x00001010, 0x10000010, 0x00000010,
    0x30000000, 0x00002000, 0x10001000, 0x00001000, 0x20000000, 0x00100000, 0x10000000, 0x00000000,
]

_RICE_LEN = [
    0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4, 1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5,
    1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5, 2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
    1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5, 2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
    2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6, 3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7,
    1, 2, 2, 3, 2, 3, 3, 4, 2, 3, 3, 4, 3, 4, 4, 5, 2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6,
    2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6, 3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7,
    2, 3, 3, 4, 3, 4, 4, 5, 3, 4, 4, 5, 4, 5, 5, 6, 3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7,
    3, 4, 4, 5, 4, 5, 5, 6, 4, 5, 5, 6, 5, 6, 6, 7, 4, 5, 5, 6, 5, 6, 6, 7, 5, 6, 6, 7, 6, 7, 7, 8,
]


class BitReader2:
    """1:1 复刻 C++ Oodle BitReader2 — ptr + bitpos 递增模型
    
    - ptr: 当前字节指针 (byte pointer)
    - bitpos: 当前字节内的位偏移 [0, 7]，从 MSB (bit 7) 到 LSB (bit 0) 递增
    """
    __slots__ = ('data', 'ptr', 'bitpos')
    
    def __init__(self, data: bytes, offset: int = 0, bitpos: int = 0):
        self.data = data
        self.ptr = offset
        self.bitpos = bitpos
    
    def read_bit(self) -> int:
        """读取单 bit (MSB 优先)"""
        if self.ptr >= len(self.data):
            return 0
        bit = (self.data[self.ptr] >> (7 - self.bitpos)) & 1
        self.bitpos += 1
        if self.bitpos >= 8:
            self.ptr += self.bitpos // 8
            self.bitpos %= 8
        return bit
    
    def read_bits(self, count: int) -> int:
        """从 MSB 到 LSB 读取 count 个 bits"""
        if count == 0:
            return 0
        result = 0
        for _ in range(count):
            result = (result << 1) | self.read_bit()
        return result
    
    def align_to_byte(self):
        """字节对齐"""
        if self.bitpos != 0:
            self.ptr += 1
            self.bitpos = 0


def _decode_golomb_rice_lengths(dst, dst_size, br2):
    """C++ DecodeGolombRiceLengths — 基于查找表的 Rice 解码
    
    dst: 输出列表 (长度 >= dst_size), 从 dst[0] 开始写入
    br2: BitReader2, 从 br2.ptr/br2.bitpos 开始读取
    返回: bool 成功 (br2 原地更新)
    """
    di = 0
    p = br2.ptr
    data = br2.data
    p_end = len(data)
    
    if p >= p_end:
        return False
    
    count = -br2.bitpos
    v = data[p] & (255 >> br2.bitpos)
    p += 1
    
    while di < dst_size:
        if v == 0:
            count += 8
        else:
            x = _RICE_VAL[v]
            # C++: *(u32*)dst = count + (x & 0x0f0f0f0f)
            #      *(u32*)(dst+4) = (x >> 4) & 0x0f0f0f0f  (小端字节展开)
            low = count + (x & 0x0f0f0f0f)
            high = (x >> 4) & 0x0f0f0f0f
            vals = [
                low & 0xFF, (low >> 8) & 0xFF, (low >> 16) & 0xFF, (low >> 24) & 0xFF,
                high & 0xFF, (high >> 8) & 0xFF, (high >> 16) & 0xFF, (high >> 24) & 0xFF,
            ]
            di_start = di
            n_write = _RICE_LEN[v]
            for i in range(n_write):
                if di < dst_size:
                    dst[di] = vals[i]
                    di += 1
            if di >= dst_size:
                # C++: dst += step; if (dst >= dst_end) break;
                #      但实际只消耗了 remaining = dst_size - di_start 个 unary 位,
                #      多余 (n_write - remaining) 个位未读 → v &= v-1 清除这些位
                #      (这决定最终 br2.bitpos = 8 - BSF(v))
                n_over = n_write - (dst_size - di_start)
                for _ in range(n_over):
                    v &= v - 1
                break
            count = x >> 28
        if p >= p_end:
            return False
        v = data[p]
        p += 1
    
    # C++: 若最后字节 LSB 为 0, 回退一字节并计算 bitpos = 8 - BSF(v)
    bitpos = 0
    if not (v & 1):
        p -= 1
        q = 0
        while not ((v >> q) & 1):
            q += 1
        bitpos = 8 - q
    
    br2.ptr = p
    br2.bitpos = bitpos
    return True


def _decode_golomb_rice_bits(dst, size, bitcount, br2):
    """C++ DecodeGolombRiceBits — 每符号读 bitcount bit 并与既有值组合
    
    C++: *(u64*)dst = *(u64*)dst * (2^bitcount) + expanded_bits
    → dst[i] = (dst[i] << bitcount) | read_bits(bitcount)
    dst 已有 Rice 长度值 (来自 DecodeGolombRiceLengths), 累加组合。
    
    dst: 输出列表 (长度 >= size)
    br2: BitReader2
    返回: (bool 成功, 更新后的 br2)
    """
    if bitcount == 0:
        return True, br2
    for i in range(size):
        dst[i] = (dst[i] << bitcount) | br2.read_bits(bitcount)
    return True, br2


def _huff_convert_to_ranges(range_out, num_symbols, P, symlen, br2):
    """C++ Huff_ConvertToRanges — 构建符号范围列表
    
    range_out: 输出列表 [(symbol, num), ...]
    symlen: 码长差分数组 (从 num_symbols 开始)
    br2: BitReader2 (读取额外位)
    返回: 范围数 (负数表示失败)
    """
    num_ranges = P >> 1
    sym_idx = 0
    
    if P & 1:
        v = symlen[0] if symlen else 0
        if v >= 8:
            return -1
        sym_idx = br2.read_bits(v + 1) + (1 << (v + 1)) - 1
    syms_used = 0
    sli = 0
    
    for i in range(num_ranges):
        v = symlen[sli] if sli < len(symlen) else 0
        sli += 1
        if v >= 9:
            return -1
        num = br2.read_bits(v) + (1 << v)
        v = symlen[sli] if sli < len(symlen) else 0
        sli += 1
        if v >= 8:
            return -1
        space = br2.read_bits(v + 1) + (1 << (v + 1)) - 1
        range_out.append((sym_idx, num))
        syms_used += num
        sym_idx += num + space
    
    if sym_idx >= 256 or syms_used >= num_symbols or sym_idx + num_symbols - syms_used > 256:
        return -1
    
    range_out.append((sym_idx, num_symbols - syms_used))
    return len(range_out)


def _read_huff_codelens_new(src: bytes, byte_off: int, bit_off: int,
                            syms: list[int], code_prefix: list[int],
                            CODE_PREFIX_ORG: list[int]) -> tuple[int, int]:
    """C++ Huff_ReadCodeLengthsNew — 独立的 BitReader2 (ptr + bitpos 递增模型)
    
    src: 完整源数据
    byte_off: 位选择后数据起始字节偏移
    bit_off: 起始字节内的位偏移 [0,7] (MSB 优先)
    
    返回: (num_syms, 消耗字节数) — 消耗字节数用于定位后续流数据
    """
    br2 = BitReader2(src, byte_off, bit_off)
    
    # C++: forced_bits = ReadBitsNoRefill(2)
    forced_bits = br2.read_bits(2)
    # C++: num_symbols = ReadBitsNoRefill(8) + 1
    num_symbols = br2.read_bits(8) + 1
    
    # C++: fluff = BitReader_ReadFluff(bits, num_symbols)
    # 真实 Oodle newLZ_decode_alphabet_shape_num_EG:
    #   nbits = bit_length(num_eg_bound - 1); peek nbits; large_thresh = (1<<nbits) - bound
    #   if ((peek>>1) < large_thresh): num_eg = peek>>1; consume nbits-1
    #   else: num_eg = peek - large_thresh; consume nbits
    if num_symbols == 256:
        fluff = 0
    else:
        x = 257 - num_symbols
        if x > num_symbols:
            x = num_symbols
        x *= 2
        y = (x - 1).bit_length()
        z = (1 << y) - x
        # 先读前 y-1 位, 其值即 (peek >> 1)
        partial = br2.read_bits(y - 1)
        if partial >= z:
            # 条件 (peek>>1) >= large_thresh → 消耗 nbits, 返回 peek - large_thresh
            bit_y = br2.read_bits(1)
            v = (partial << 1) | bit_y
            fluff = v - z
        else:
            # 条件 (peek>>1) < large_thresh → 消耗 nbits-1, 返回 peek>>1
            fluff = partial
    
    # 3. C++: uint8 code_len[512]
    #    DecodeGolombRiceLengths(code_len, num_symbols+fluff, &br2)
    code_len = [0] * 512
    if not _decode_golomb_rice_lengths(code_len, num_symbols + fluff, br2):
        return -1, 0
    
    # 4. C++: memset(code_len + num_symbols+fluff, 0, 16)
    #    DecodeGolombRiceBits(code_len, num_symbols, forced_bits, &br2)
    #    → 写入 code_len[0..num_symbols-1] (覆盖前 num_symbols 个 Rice 值)
    if not _decode_golomb_rice_bits(code_len, num_symbols, forced_bits, br2):
        return -1, 0
    
    # 5. Codelen 预测 (powzix Huff_ReadCodeLengthsNew / oozextract huff_read_code_lengths_new):
    #    running_sum = 0x1e (= 30)
    #    v = -(codelen&1) ^ (codelen>>1)   (unfold)
    #    len = v + (running_sum>>2) + 1
    #    running_sum += v
    running_sum = 0x1e
    for i in range(num_symbols):
        vv = code_len[i]
        delta = -(vv & 1) ^ (vv >> 1)
        clen = delta + (running_sum >> 2) + 1
        if clen < 1 or clen > 11:
            return -1, 0
        code_len[i] = clen
        running_sum += delta
    
    # 6. Huff_ConvertToRanges(range, num_symbols, P=fluff, symlen=&code_len[num_symbols], bits)
    #    symlen = code_len[num_symbols .. num_symbols+fluff-1]
    symlen = code_len[num_symbols:]
    P = fluff
    num_ranges = P >> 1
    sym_idx = 0
    if P & 1:
        v = symlen[0]
        if v >= 8:
            return -1, 0
        sym_idx = br2.read_bits(v + 1) + (1 << (v + 1)) - 1
    syms_used = 0
    # C++/Rust: if (P & 1) { symlen += 1; } — 跳过已使用的 symlen[0]
    sli = P & 1
    ranges = []
    for i in range(num_ranges):
        v = symlen[sli] if sli < len(symlen) else 0
        sli += 1
        if v >= 9:
            return -1, 0
        num = br2.read_bits(v) + (1 << v)
        v = symlen[sli] if sli < len(symlen) else 0
        sli += 1
        if v >= 8:
            return -1, 0
        space = br2.read_bits(v + 1) + (1 << (v + 1)) - 1
        ranges.append((sym_idx, num))
        syms_used += num
        sym_idx += num + space
    if sym_idx >= 256 or syms_used >= num_symbols or sym_idx + num_symbols - syms_used > 256:
        return -1, 0
    ranges.append((sym_idx, num_symbols - syms_used))
    
    # 7. C++: cp = code_len (从 0 开始), 按 range 逐符号填充
    #    syms[code_prefix[*cp++]++] = sym++
    cp = 0
    for sym_start, num in ranges:
        sym = sym_start
        for _ in range(num):
            if cp >= num_symbols:
                break
            clen = code_len[cp]
            cp += 1
            if clen >= 1 and clen <= 11:
                pos = code_prefix[clen]
                if pos < len(syms):
                    syms[pos] = sym
                code_prefix[clen] = pos + 1
            sym += 1
    
    # 8. 计算消耗字节数 (流数据起点 = byte_off + consumed)
    #    C++: src = bits.p - ((24 - bits.bitpos) / 8) — 用 br2 当前位置
    consumed = br2.ptr - byte_off + (1 if br2.bitpos else 0)
    if consumed < 0:
        consumed = 0
    
    return num_symbols, consumed


def build_kraken_lut(syms: list[int], code_prefix: list[int],
                     num_syms: int) -> tuple[list[int], list[int]]:
    """构建 2048 条目 Huffman LUT (匹配 C++ Huff_MakeLut)
    
    code_prefix_org[i] = 长度 i 的码的起始符号索引
    code_prefix[i] = 长度 i 的码的结束符号索引(更新后)
    
    返回 (lut_sym, lut_bits) — 需 bit-reversed 才能使用
    """
    CODE_PREFIX_ORG = [0x0, 0x0, 0x2, 0x6, 0xE, 0x1E, 0x3E, 0x7E,
                       0xFE, 0x1FE, 0x2FE, 0x3FE]
    
    lut_sym = [0] * 2048
    lut_bits = [0] * 2048
    currslot = 0
    
    for length in range(1, 12):
        start_idx = CODE_PREFIX_ORG[length]  # 起始符号索引
        end_idx = code_prefix[length]        # 结束符号索引
        count = end_idx - start_idx          # 此长度的符号数
        if count <= 0:
            continue
        
        stepsize = 1 << (11 - length)        # 码在 LUT 中的间隔
        num_to_set = count * stepsize        # 要填充的 LUT 条目数
        
        if currslot + num_to_set > 2048:
            break
        
        # 填充码长
        for j in range(num_to_set):
            lut_bits[currslot + j] = length
        
        # 填充符号 (C++: for j in count, p += stepsize, FillByteOverflow16(p, syms[start+j], stepsize))
        # powzix 直接访问 syms[start_idx + j] (整个 1280 数组, 不限于 num_syms)
        for j in range(count):
            sym = syms[start_idx + j]
            base = currslot + j * stepsize
            for k in range(stepsize):
                if base + k < 2048:
                    lut_sym[base + k] = sym
        
        currslot += num_to_set
    
    # Bit-Reverse (C++ ReverseBitsArray2048)
    rev_sym = [0] * 2048
    rev_bits = [0] * 2048
    for i in range(2048):
        rev = ((i >> 0) & 1) << 10 | ((i >> 1) & 1) << 9 | \
              ((i >> 2) & 1) << 8 | ((i >> 3) & 1) << 7 | \
              ((i >> 4) & 1) << 6 | ((i >> 5) & 1) << 5 | \
              ((i >> 6) & 1) << 4 | ((i >> 7) & 1) << 3 | \
              ((i >> 8) & 1) << 2 | ((i >> 9) & 1) << 1 | \
              ((i >> 10) & 1) << 0
        rev_sym[rev] = lut_sym[i]
        rev_bits[rev] = lut_bits[i]
    
    return rev_sym, rev_bits


# ══════════════════════════════════════════════════════════
# 3. 查表消费 + 三流并行解码
# ══════════════════════════════════════════════════════════

def _lookup(rd: OodleBitReader, lut_sym: list[int],
             lut_bits: list[int], reverse: bool = False) -> tuple[int, int]:
    """查表消费1个符号, 返回 (symbol, consumed_bits)
    
    MSB优先: peek = bit_buf >> 21 (高11位), consume = 左移
    """
    if reverse:
        if rd.bits_left < 11:
            rd.refill_reverse()
        peek = rd.bit_buf >> 21
    else:
        if rd.bits_left < 11:
            rd.refill()
        peek = rd.bit_buf >> 21
    
    sym = lut_sym[peek]
    nb = lut_bits[peek]
    if nb == 0:
        rd.consume(1)
        return 0, 1
    rd.consume(nb)
    return sym, nb


# ══════════════════════════════════════════════════════════
# 3b. Kraken_DecodeBytesCore — 三流交错 LSB-first (powzix/oozextract)
# ══════════════════════════════════════════════════════════

def _u32le(d: bytes, i: int) -> int:
    return d[i] | (d[i + 1] << 8) | (d[i + 2] << 16) | (d[i + 3] << 24)


def _u16le(d: bytes, i: int) -> int:
    return d[i] | (d[i + 1] << 8)


def _bswap32(x: int) -> int:
    return (((x >> 24) & 0xFF) | ((x >> 8) & 0xFF00) |
            ((x << 8) & 0xFF0000) | ((x << 24) & 0xFFFFFFFF)) & 0xFFFFFFFF


def _decode_bytes_core(data: bytes, src_off: int, src_mid_org: int,
                       src_mid_off: int, src_end_off: int,
                       lut_sym: list[int], lut_bits: list[int],
                       out_size: int) -> Optional[bytes]:
    """powzix Kraken_DecodeBytesCore / oozextract HuffReader::decode_bytes
    
    三流交错: src 正向, src_mid 正向, src_end 反向, LSB-first (k = bits & 0x7FF)
    依赖 x86 mod-32 shift (负 bitpos 时用 (bitpos & 31))
    """
    out = bytearray(out_size)
    src = src_off
    src_mid = src_mid_off
    src_end = src_end_off
    src_bits = 0
    src_bitpos = 0
    src_mid_bits = 0
    src_mid_bitpos = 0
    src_end_bits = 0
    src_end_bitpos = 0
    dst = 0
    dst_end = out_size
    n_data = len(data)

    def byte(i: int) -> int:
        return data[i] if 0 <= i < n_data else 0

    if src > src_mid:
        return None

    # 主循环 (每轮 6 符号)
    if (src_end - src_mid) >= 4 and (dst_end - dst) >= 6:
        dst_end -= 5
        src_end -= 4
        while dst < dst_end and src <= src_mid and src_mid <= src_end:
            src_bits = (src_bits | (_u32le(data, src) << (src_bitpos & 31))) & 0xFFFFFFFF
            src += (31 - src_bitpos) >> 3
            src_end_bits = (src_end_bits | (_bswap32(_u32le(data, src_end)) << (src_end_bitpos & 31))) & 0xFFFFFFFF
            src_end -= (31 - src_end_bitpos) >> 3
            src_mid_bits = (src_mid_bits | (_u32le(data, src_mid) << (src_mid_bitpos & 31))) & 0xFFFFFFFF
            src_mid += (31 - src_mid_bitpos) >> 3
            src_bitpos |= 0x18
            src_end_bitpos |= 0x18
            src_mid_bitpos |= 0x18
            # 6 符号: src, src_end, src_mid, src, src_end, src_mid
            k = src_bits & 0x7FF; n = lut_bits[k]; src_bits = (src_bits >> n) & 0xFFFFFFFF; src_bitpos -= n; out[dst] = lut_sym[k]; dst += 1
            k = src_end_bits & 0x7FF; n = lut_bits[k]; src_end_bits = (src_end_bits >> n) & 0xFFFFFFFF; src_end_bitpos -= n; out[dst] = lut_sym[k]; dst += 1
            k = src_mid_bits & 0x7FF; n = lut_bits[k]; src_mid_bits = (src_mid_bits >> n) & 0xFFFFFFFF; src_mid_bitpos -= n; out[dst] = lut_sym[k]; dst += 1
            k = src_bits & 0x7FF; n = lut_bits[k]; src_bits = (src_bits >> n) & 0xFFFFFFFF; src_bitpos -= n; out[dst] = lut_sym[k]; dst += 1
            k = src_end_bits & 0x7FF; n = lut_bits[k]; src_end_bits = (src_end_bits >> n) & 0xFFFFFFFF; src_end_bitpos -= n; out[dst] = lut_sym[k]; dst += 1
            k = src_mid_bits & 0x7FF; n = lut_bits[k]; src_mid_bits = (src_mid_bits >> n) & 0xFFFFFFFF; src_mid_bitpos -= n; out[dst] = lut_sym[k]; dst += 1
        dst_end += 5
        src -= src_bitpos >> 3
        src_bitpos &= 7
        src_end += 4 + (src_end_bitpos >> 3)
        src_end_bitpos &= 7
        src_mid -= src_mid_bitpos >> 3
        src_mid_bitpos &= 7

    # 尾部循环 (逐符号)
    while dst < dst_end:
        if (src_mid - src) <= 1:
            if (src_mid - src) == 1:
                src_bits = (src_bits | (byte(src) << (src_bitpos & 31))) & 0xFFFFFFFF
        else:
            src_bits = (src_bits | (_u16le(data, src) << (src_bitpos & 31))) & 0xFFFFFFFF
        k = src_bits & 0x7FF
        n = lut_bits[k]
        src_bitpos -= n
        src_bits = (src_bits >> n) & 0xFFFFFFFF
        out[dst] = lut_sym[k]
        dst += 1
        src += (7 - src_bitpos) >> 3
        src_bitpos &= 7
        if dst < dst_end:
            if (src_end - src_mid) <= 1:
                if (src_end - src_mid) == 1:
                    mid = byte(src_mid)
                    src_end_bits = (src_end_bits | (mid << (src_end_bitpos & 31))) & 0xFFFFFFFF
                    src_mid_bits = (src_mid_bits | (mid << (src_mid_bitpos & 31))) & 0xFFFFFFFF
            else:
                v = _u16le(data, src_end - 2)
                src_end_bits = (src_end_bits | ((((v >> 8) | (v << 8)) & 0xffff) << (src_end_bitpos & 31))) & 0xFFFFFFFF
                src_mid_bits = (src_mid_bits | (_u16le(data, src_mid) << (src_mid_bitpos & 31))) & 0xFFFFFFFF
            k = src_end_bits & 0x7FF
            out[dst] = lut_sym[k]
            dst += 1
            n = lut_bits[k]
            src_end_bitpos -= n
            src_end_bits = (src_end_bits >> n) & 0xFFFFFFFF
            src_end -= (7 - src_end_bitpos) >> 3
            src_end_bitpos &= 7
            if dst < dst_end:
                k = src_mid_bits & 0x7FF
                out[dst] = lut_sym[k]
                dst += 1
                n = lut_bits[k]
                src_mid_bitpos -= n
                src_mid_bits = (src_mid_bits >> n) & 0xFFFFFFFF
                src_mid += (7 - src_mid_bitpos) >> 3
                src_mid_bitpos &= 7
        if src > src_mid or src_mid > src_end:
            return None
    if src != src_mid_org or src_end != src_mid:
        return None
    return bytes(out)


def _decode_huff_type12(src: bytes, out_size: int, huff_type: int
                        ) -> Optional[bytes]:
    """Huffman 解码入口 (powzix Kraken_DecodeBytes_Type12)

    huff_type=1: 一段三流
    huff_type=2: 两段三流
    """
    if len(src) < 2:
        return None

    br = OodleBitReader(src, 0)
    CODE_PREFIX_ORG = [0x0, 0x0, 0x2, 0x6, 0xE, 0x1E, 0x3E, 0x7E,
                       0xFE, 0x1FE, 0x2FE, 0x3FE]
    code_prefix = list(CODE_PREFIX_ORG)
    syms = list(range(1280))

    # C++: 读2选择位 — 0=Old, 10=New, 11=Error
    bit0 = br.read_bit_nr()
    if bit0 == 0:
        # Old codelens — 用 powzix rotl BitReader (与 oozextract 一致)
        brp = BitReaderP(src, 0, len(src))
        _ = brp.read_bit_no_refill()  # bit0 (应为 0)
        num_syms = _read_huff_codelens_old(brp, syms, code_prefix)
        byte_pos = brp.p - ((24 - brp.bitpos) >> 3)
    else:
        bit1 = br.read_bit_nr()
        if bit1 == 0:
            consumed_bits = 32 - br.bits_left
            byte_off = consumed_bits // 8
            bit_off = consumed_bits % 8
            num_syms, consumed = _read_huff_codelens_new(
                src, byte_off, bit_off, syms, code_prefix, CODE_PREFIX_ORG)
            byte_pos = byte_off + consumed
        else:
            return None  # 11 → Error
    if num_syms < 1:
        return None
    if num_syms == 1:
        return bytes([syms[0]] * out_size)

    lut_sym, lut_bits = build_kraken_lut(syms, code_prefix, num_syms)

    if byte_pos < 0:
        byte_pos = 0
    data = src[byte_pos:]
    src_end = len(data)

    if huff_type == 1:
        # 一段三流: split_mid(2) + [src, src_mid_org) + [src_mid_org, src_end)
        if len(data) < 2:
            return None
        split_mid = data[0] | (data[1] << 8)
        s = 2
        src_mid_org = s + split_mid
        if src_mid_org > src_end:
            return None
        return _decode_bytes_core(data, s, src_mid_org, src_mid_org, src_end,
                                  lut_sym, lut_bits, out_size)
    else:
        # 两段三流: split_mid(3) + split_left(2) + [前半] + split_right(2) + [后半]
        if len(data) < 6:
            return None
        half_output_size = (out_size + 1) >> 1
        split_mid = _u32le(data, 0) & 0xFFFFFF
        s = 3
        src_mid = s + split_mid
        if src_mid > src_end:
            return None
        split_left = _u16le(data, s)
        s += 2
        split_right = _u16le(data, src_mid)

        out1 = _decode_bytes_core(data, s, s + split_left, s + split_left, src_mid,
                                  lut_sym, lut_bits, half_output_size)
        if out1 is None:
            return None
        out2 = _decode_bytes_core(data, src_mid + 2, src_mid + 2 + split_right,
                                  src_mid + 2 + split_right, src_end,
                                  lut_sym, lut_bits, out_size - half_output_size)
        if out2 is None:
            return None
        return out1 + out2


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════

def _byteswap(x: int) -> int:
    return ((x >> 24) & 0xFF) | ((x >> 8) & 0xFF00) | ((x << 8) & 0xFF0000) | ((x << 24) & 0xFF000000)


# ══════════════════════════════════════════════════════════
# 头部解析
# ══════════════════════════════════════════════════════════

def _parse_kraken_header(data: bytes, off: int) -> tuple[dict, int]:
    if off >= len(data):
        return None, -1
    b = data[off]
    if (b & 0xF) != 0xC or ((b >> 4) & 3) != 0:
        return None, -1
    hdr = {'restart': bool((b >> 7) & 1), 'uncompressed': bool((b >> 6) & 1)}
    off += 1
    if off >= len(data):
        return None, -1
    b = data[off]
    hdr['decoder_type'] = b & 0x7F
    hdr['use_checksums'] = bool(b >> 7)
    if hdr['decoder_type'] not in (5, 6, 10, 11, 12):
        return None, -1
    return hdr, off + 1


def _parse_quantum_header(data: bytes, off: int, use_checksum: bool) -> tuple[dict, int]:
    """powzix Kraken_ParseQuantumHeader

    3 字节量子头: v = (p[0]<<16)|(p[1]<<8)|p[2]
    - size = v & 0x3FFFF (18 位)
    - size != 0x3FFFF: compressed_size = size + 1
    - size == 0x3FFFF 且 (v>>18)==1: memset, compressed_size=0
    """
    if off + 3 > len(data):
        return None, -1
    v = (data[off] << 16) | (data[off + 1] << 8) | data[off + 2]
    size = v & 0x3FFFF
    qh = {'whole_match_distance': 0, 'checksum': 0, 'flag1': 0, 'flag2': 0}
    if size != 0x3FFFF:
        qh['compressed_size'] = size + 1
        qh['flag1'] = (v >> 18) & 1
        qh['flag2'] = (v >> 19) & 1
        off += 3
        if use_checksum:
            if off + 3 > len(data):
                return None, -1
            qh['checksum'] = (data[off] << 16) | (data[off + 1] << 8) | data[off + 2]
            off += 3
        return qh, off
    v >>= 18
    if v == 1:
        # memset
        qh['checksum'] = data[off + 3]
        qh['compressed_size'] = 0
        return qh, off + 4
    return None, -1
    prefix = 0
    prev_len = 0
    for i in range(count):
        while prev_len < tmp_lens[i]:
            prefix >>= 1
            prev_len += 1
        code_prefix[num_syms] = prefix
        # 存储码长到 code_prefix 的高位
        code_prefix[num_syms] |= tmp_lens[i] << 24
        # 下一个码
        if tmp_lens[i] <= 11:
            prefix += 0x80000000 >> (tmp_lens[i] + 11)
        else:
            prefix += 1
        syms[num_syms] = tmp_syms[i]
        num_syms += 1

    return num_syms


# ── 以下为已通过之前验证的 RLE/LZ/Quantum 等代码 ──


# ══════════════════════════════════════════════════════════
# RLE 解码
# ══════════════════════════════════════════════════════════

def _decode_rle_unpacked(cmd: bytes, dst_size: int) -> Optional[bytes]:
    """oozextract decode_rle_unpacked — 从命令 buffer 解 RLE 数据

    命令从末尾 (cmd_ptr_end-1) 读取, 数据从开头 (cmd_ptr) 读取。
    """
    dst = bytearray()
    cmd_ptr = 0
    cmd_ptr_end = len(cmd)
    rle_byte = 0
    n_cmd = len(cmd)

    def u16le(i: int) -> int:
        if 0 <= i + 1 < n_cmd:
            return cmd[i] | (cmd[i + 1] << 8)
        return 0

    while cmd_ptr < cmd_ptr_end and len(dst) < dst_size:
        c = cmd[cmd_ptr_end - 1]
        if c == 0 or c > 0x2f:
            # bytes_to_copy = ~c & 0xF ; bytes_to_rle = c >> 4
            cmd_ptr_end -= 1
            bc = (-1 - c) & 0xF
            br = c >> 4
            if bc > 0:
                dst.extend(cmd[cmd_ptr:cmd_ptr + bc])
                cmd_ptr += bc
            dst.extend([rle_byte] * br)
        elif c >= 0x10:
            cmd_ptr_end -= 2
            val = u16le(cmd_ptr_end) - 4096
            bc = val & 0x3F
            br = val >> 6
            if bc > 0:
                dst.extend(cmd[cmd_ptr:cmd_ptr + bc])
                cmd_ptr += bc
            dst.extend([rle_byte] * br)
        elif c == 1:
            rle_byte = cmd[cmd_ptr]
            cmd_ptr += 1
            cmd_ptr_end -= 1
        elif c >= 9:
            cmd_ptr_end -= 2
            br = (u16le(cmd_ptr_end) - 0x8FF) * 128
            dst.extend([rle_byte] * br)
        else:
            cmd_ptr_end -= 2
            bc = (u16le(cmd_ptr_end) - 511) * 64
            if bc > 0:
                dst.extend(cmd[cmd_ptr:cmd_ptr + bc])
                cmd_ptr += bc

    return bytes(dst[:dst_size])


def _decode_rle(src: bytes, dst_size: int) -> Optional[bytes]:
    """oozextract decode_rle — 完整版

    - src_size == 1: 全 memset 为 src[0]
    - src[0] != 0: 先解包命令 buffer (递归 decode_bytes), 再把剩余原始字节
      追加到命令 buffer 末尾, 然后 decode_rle_unpacked
    - src[0] == 0: 直接 decode_rle_unpacked(src[1:], ...)
    """
    if len(src) == 0:
        return None
    if len(src) == 1:
        return bytes([src[0]] * dst_size)

    if src[0] != 0:
        # 先解包命令 buffer: decode_bytes 消耗 n 字节, 解出 dec_size 字节
        r, n = _decode_bytes(src, max(len(src) * 4, 1 << 20))
        if r is None:
            return None
        cmd = bytearray(r)
        cmd.extend(src[n:])
        return _decode_rle_unpacked(bytes(cmd), dst_size)
    else:
        return _decode_rle_unpacked(src[1:], dst_size)


# ══════════════════════════════════════════════════════════
# TANS 解码 (chunk_type=1)
# ══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
# TANS 熵解码 (chunk_type=1)
# ══════════════════════════════════════════════════════════

_MASK64 = (1 << 64) - 1


def _tans_read_fluff(br, num_symbols):
    """oozextract BitReader::read_fluff"""
    if num_symbols == 256:
        return 0
    x = 257 - num_symbols
    if x > num_symbols:
        x = num_symbols
    x *= 2
    y = (x - 1).bit_length()
    v = br.bits >> (32 - y)
    z = (1 << y) - x
    if (v >> 1) >= z:
        br.bits = (br.bits << y) & 0xFFFFFFFF
        br.bitpos += y
        return v - z
    else:
        br.bits = (br.bits << (y - 1)) & 0xFFFFFFFF
        br.bitpos += y - 1
        return v >> 1


def _tans_convert_to_ranges(num_symbols, p, symlen, br):
    """oozextract convert_to_ranges (BitReader 版, 用 read_bits_no_refill_zero)"""
    ranges = []
    sym_idx = 0
    sli = num_symbols
    if p & 1:
        br.refill()
        v = symlen[sli] if sli < len(symlen) else 0
        sli += 1
        if v >= 8:
            return None
        sym_idx = br.read_bits_no_refill(v + 1) + (1 << (v + 1)) - 1
    syms_used = 0
    num_ranges = p >> 1
    for _ in range(num_ranges):
        br.refill()
        v = symlen[sli] if sli < len(symlen) else 0
        sli += 1
        if v >= 9:
            return None
        num = br.read_bits_no_refill_zero(v) + (1 << v)
        v = symlen[sli] if sli < len(symlen) else 0
        sli += 1
        if v >= 8:
            return None
        space = br.read_bits_no_refill(v + 1) + (1 << (v + 1)) - 1
        ranges.append((sym_idx, num))
        syms_used += num
        sym_idx += num + space
    if sym_idx >= 256 or syms_used >= num_symbols or sym_idx + num_symbols - syms_used > 256:
        return None
    ranges.append((sym_idx, num_symbols - syms_used))
    return ranges


def _tans_decode_table_old(br, l_bits):
    """oozextract decode_table — count-based (reserved bit=0)"""
    l = 1 << l_bits
    br.refill()
    count = br.read_bits_no_refill(3) + 1
    bits_per_sym = l_bits.bit_length()  # ilog2 + 1
    max_delta_bits = br.read_bits_no_refill(bits_per_sym)
    if max_delta_bits == 0:
        return None
    a_list = []
    b_list = []
    seen = [False] * 256
    weight = 0
    total_weights = 0
    for _ in range(count):
        br.refill()
        sym = br.read_bits_no_refill(8)
        if seen[sym]:
            return None
        delta = br.read_bits_no_refill(max_delta_bits)
        weight += delta
        if weight == 0:
            return None
        seen[sym] = True
        if weight == 1:
            a_list.append(sym)
        else:
            b_list.append((sym, weight))
        total_weights += weight
    br.refill()
    sym = br.read_bits_no_refill(8)
    if seen[sym]:
        return None
    if l - total_weights < weight:
        return None
    if l - total_weights <= 1:
        return None
    b_list.append((sym, l - total_weights))
    a_list.sort()
    b_list.sort(key=lambda x: x[0])
    return {'a': a_list, 'b': b_list}


def _tans_decode_table_new(br, l_bits, data):
    """oozextract decode_table — rice-based (reserved bit=1)"""
    br.refill()
    q = br.read_bits_no_refill(3)
    num_symbols = br.read_bits_no_refill(8) + 1
    if num_symbols < 2:
        return None
    fluff = _tans_read_fluff(br, num_symbols)
    total_rice_values = num_symbols + fluff
    rice = [0] * (512 + 16)
    # 转换到 BitReader2
    br2_p = br.p - ((24 - br.bitpos + 7) >> 3)
    br2_bitpos = (br.bitpos - 24) & 7
    if br2_p < 0:
        br2_p = 0
    br2 = BitReader2(data, br2_p, br2_bitpos)
    if not _decode_golomb_rice_lengths(rice, total_rice_values, br2):
        return None
    # 切回 BitReader
    br.bitpos = 24
    br.p = br2.ptr
    br.bits = 0
    br.refill()
    br.bits = (br.bits << br2.bitpos) & 0xFFFFFFFF
    br.bitpos += br2.bitpos
    ranges = _tans_convert_to_ranges(num_symbols, fluff, rice, br)
    if ranges is None:
        return None
    br.refill()
    l = 1 << l_bits
    cur_rice_ptr = 0
    average = 6
    somesum = 0
    a_list = []
    b_list = []
    for sym_start, num in ranges:
        symbol = sym_start
        for _ in range(num):
            br.refill()
            nextra = rice[cur_rice_ptr] + q
            cur_rice_ptr += 1
            v = br.read_bits_no_refill_zero(nextra) + (1 << nextra) - (1 << q)
            average_div4 = average >> 2
            limit = 2 * average_div4
            if v <= limit:
                v = average_div4 + ((v >> 1) ^ -(v & 1))
            if limit > v:
                limit = v
            v += 1
            average += limit - average_div4
            if v == 1:
                a_list.append(symbol)
            else:
                b_list.append((symbol, v))
            somesum += v
            symbol += 1
    if somesum != l:
        return None
    return {'a': a_list, 'b': b_list}


def _tans_init_lut_full(tans, l_bits):
    """oozextract TansDecoder::init_lut — LUT 条目 (x, bits_x, symbol, w)"""
    l = 1 << l_bits
    a_used = len(tans['a'])
    b = tans['b']
    slots_left_to_alloc = l - a_used
    sa = slots_left_to_alloc >> 2
    sb = sa
    if (slots_left_to_alloc & 3) > 0:
        sb += 1
    pointers = [0, sb, 0, 0]
    sb += sa
    if (slots_left_to_alloc & 3) > 1:
        sb += 1
    pointers[2] = sb
    sb += sa
    if (slots_left_to_alloc & 3) > 2:
        sb += 1
    pointers[3] = sb
    lut = [(0, 0, 0, 0)] * l
    # weight=1 条目
    for i in range(a_used):
        lut[slots_left_to_alloc + i] = ((1 << l_bits) - 1, l_bits, tans['a'][i], 0)
    # weight>=2 条目
    weights_sum = 0
    for sym, weight in b:
        if weight > 4:
            sym_bits = weight.bit_length() - 1
            z = l_bits - sym_bits
            le_x = (1 << z) - 1
            le_w = ((l - 1) & (weight << z)) & 0xFFFF
            le_symbol = sym
            le_bits = z
            what_to_add = 1 << z
            x = (1 << (sym_bits + 1)) - weight
            for j in range(4):
                dst_idx = pointers[j]
                y = (weight + ((weights_sum - j - 1) & 3)) >> 2
                if x >= y:
                    for _ in range(y):
                        lut[dst_idx] = (le_x, le_bits, le_symbol, le_w)
                        dst_idx += 1
                        le_w = (le_w + what_to_add) & 0xFFFF
                    x -= y
                else:
                    for _ in range(x):
                        lut[dst_idx] = (le_x, le_bits, le_symbol, le_w)
                        dst_idx += 1
                        le_w = (le_w + what_to_add) & 0xFFFF
                    z -= 1
                    what_to_add >>= 1
                    le_bits = z
                    le_w = 0
                    le_x >>= 1
                    for _ in range(y - x):
                        lut[dst_idx] = (le_x, le_bits, le_symbol, le_w)
                        dst_idx += 1
                        le_w = (le_w + what_to_add) & 0xFFFF
                    x = weight
                pointers[j] = dst_idx
        else:
            bits = ((1 << weight) - 1) << (weights_sum & 3)
            bits |= bits >> 4
            ww = weight
            for _ in range(weight):
                idx = (bits & -bits).bit_length() - 1  # trailing_zeros
                bits &= bits - 1
                dst_idx = pointers[idx]
                pointers[idx] += 1
                weight_bits = ww.bit_length() - 1
                bl = l_bits - weight_bits
                lut[dst_idx] = ((1 << bl) - 1, bl, sym, ((l - 1) & (ww << bl)) & 0xFFFF)
                ww += 1
        weights_sum += weight
    return lut


def _decode_tans(src: bytes, dst_size: int) -> Optional[bytes]:
    """TANS 熵解码 — 完整实现 (oozextract TansDecoder)"""
    if dst_size < 5 or len(src) < 12:
        return None
    src_end = len(src)
    br = BitReaderP(src, 0, src_end)
    br.refill()
    # 保留位
    if br.read_bit_no_refill():
        return None
    l_bits = br.read_bits_no_refill(2) + 8
    br.refill()
    if br.read_bit_no_refill():
        tans = _tans_decode_table_new(br, l_bits, src)
    else:
        tans = _tans_decode_table_old(br, l_bits)
    if tans is None:
        return None
    byte_pos = br.p - (24 - br.bitpos) // 8
    if byte_pos < 0 or byte_pos >= src_end:
        return None
    lut = _tans_init_lut_full(tans, l_bits)
    l_mask = (1 << l_bits) - 1
    if byte_pos + 4 > src_end:
        return None
    bits_f = struct.unpack_from('<I', src, byte_pos)[0]
    src_pos = byte_pos + 4
    src_end2 = src_end - 4
    bits_b = _byteswap(struct.unpack_from('<I', src, src_end2)[0])
    bitpos_f = 32
    bitpos_b = 32
    state = [0] * 5
    state[0] = bits_f & l_mask; bits_f >>= l_bits; bitpos_f -= l_bits
    state[1] = bits_b & l_mask; bits_b >>= l_bits; bitpos_b -= l_bits
    state[2] = bits_f & l_mask; bits_f >>= l_bits; bitpos_f -= l_bits
    state[3] = bits_b & l_mask; bits_b >>= l_bits; bitpos_b -= l_bits
    if src_pos + 4 <= src_end:
        bits_f |= struct.unpack_from('<I', src, src_pos)[0] << (bitpos_f & 63)
        src_pos += (31 - bitpos_f) >> 3
        bitpos_f |= 24
    state[4] = bits_f & l_mask; bits_f >>= l_bits; bitpos_f -= l_bits
    bits_f &= _MASK64
    ptr_f = src_pos - (bitpos_f >> 3)
    bitpos_f &= 7
    bits_b &= _MASK64
    ptr_b = src_end2 + (bitpos_b >> 3)
    bitpos_b &= 7
    dst = bytearray(dst_size)
    dst_i = 0
    dst_end2 = dst_size - 5
    step = 0
    while dst_i < dst_end2:
        if step < 5:
            if (step & 1) == 0:
                if ptr_f + 4 <= src_end:
                    bits_f = (bits_f | (struct.unpack_from('<I', src, ptr_f)[0] << (bitpos_f & 63))) & _MASK64
                ptr_f += (31 - bitpos_f) >> 3
                bitpos_f |= 24
            i = step
            x_v, bits_v, sym_v, w_v = lut[state[i]]
            dst[dst_i] = sym_v & 0xFF
            dst_i += 1
            bitpos_f -= bits_v
            state[i] = (bits_f & x_v) + w_v
            bits_f = (bits_f >> bits_v) & _MASK64
        else:
            if (step & 1) == 1:
                if ptr_b - 4 >= 0:
                    bits_b = (bits_b | (_byteswap(struct.unpack_from('<I', src, ptr_b - 4)[0]) << (bitpos_b & 63))) & _MASK64
                ptr_b -= (31 - bitpos_b) >> 3
                bitpos_b |= 24
            i = step - 5
            x_v, bits_v, sym_v, w_v = lut[state[i]]
            dst[dst_i] = sym_v & 0xFF
            dst_i += 1
            bitpos_b -= bits_v
            state[i] = (bits_b & x_v) + w_v
            bits_b = (bits_b >> bits_v) & _MASK64
        step = (step + 1) % 10
    for i in range(5):
        dst[dst_size - 5 + i] = state[i] & 0xFF
    return bytes(dst)


# ══════════════════════════════════════════════════════════
# Kraken_DecodeBytes - 分派
# ══════════════════════════════════════════════════════════

def _decode_bytes(src: bytes, out_size: int) -> tuple[Optional[bytes], int]:
    """返回 (输出数据, 消耗字节数)"""
    if len(src) < 2:
        return None, -1
    
    chunk_type = (src[0] >> 4) & 0x7
    
    if chunk_type == 0:
        # memcopy
        if src[0] >= 0x80:
            sz = ((src[0] << 8) | src[1]) & 0xFFF
            consumed = 2
        else:
            if len(src) < 3:
                return None, -1
            # 大端 (oozextract get_be_bytes(src,3))
            sz = (src[0] << 16) | (src[1] << 8) | src[2]
            consumed = 3
        if sz > out_size or len(src) - consumed < sz:
            return None, -1
        return src[consumed:consumed + sz], consumed + sz
    
    # 非 memcopy: 读 src_size 和 dst_size (精确匹配 C++ domdfcoding/kraken.cpp)
    if src[0] >= 0x80:
        # Short mode: 3 bytes header, bits = ((src[0]<<16) | (src[1]<<8) | src[2])
        if len(src) < 3:
            return None, -1
        bits = (src[0] << 16) | (src[1] << 8) | src[2]
        src_size = bits & 0x3FF          # 10 bit
        dst_size = src_size + ((bits >> 10) & 0x3FF) + 1
        consumed = 3
    else:
        # Long mode: 5 bytes header, bits = ((src[1]<<24) | (src[2]<<16) | (src[3]<<8) | src[4])
        if len(src) < 5:
            return None, -1
        bits = (src[1] << 24) | (src[2] << 16) | (src[3] << 8) | src[4]
        src_size = bits & 0x3FFFF        # 18 bit, NO +1
        dst_size = (((bits >> 18) | (src[0] << 14)) & 0x3FFFF) + 1
        consumed = 5
    
    if len(src) - consumed < src_size:
        return None, -1
    
    chunk = src[consumed:consumed + src_size]
    
    # Recursive type (C++: Krak_DecodeRecursive(src, src_size, dst, dst_size, ...))
    if chunk_type == 5:
        result, total_used = _decode_recursive(chunk, dst_size)
        if result is None:
            return None, -1
        return result, consumed + total_used
    
    if src_size >= dst_size or dst_size > out_size:
        return None, -1
    
    if chunk_type in (2, 4):
        # chunk_type 2 = type 1 Huffman, chunk_type 4 = type 2 Huffman
        result = _decode_huff_type12(chunk, dst_size, chunk_type >> 1)
        if result is None:
            return None, -1
        return result, consumed + src_size
    elif chunk_type == 1:
        result = _decode_tans(chunk, dst_size)
        if result is None:
            return None, -1
        return result, consumed + src_size
    elif chunk_type == 3:
        result = _decode_rle(chunk, dst_size)
        if result is None:
            return None, -1
        return result, consumed + src_size
    else:
        return None, -1


_BITMASKS = [(1 << n) - 1 for n in range(32)]


def _be4(d: bytes, i: int) -> int:
    """4 字节大端 (越界截断)"""
    if 0 <= i and i + 4 <= len(d):
        return (d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]
    v = 0
    for k in range(4):
        v <<= 8
        if i + k < len(d):
            v |= d[i + k]
    return v


def _le4(d: bytes, i: int) -> int:
    """4 字节小端 (越界截断)"""
    if 0 <= i and i + 4 <= len(d):
        return d[i] | (d[i + 1] << 8) | (d[i + 2] << 16) | (d[i + 3] << 24)
    v = 0
    for k in range(4):
        if i + k < len(d):
            v |= d[i + k] << (8 * k)
    return v


def _get_block_size(src: bytes, sp: int) -> Optional[int]:
    """oozextract get_block_size — 读一个块的 dst_size (用于 num_indexes)"""
    n_data = len(src)
    if sp >= n_data:
        return None
    ct = (src[sp] >> 4) & 0x7
    if ct == 0:
        if src[sp] >= 0x80:
            if sp + 2 > n_data:
                return None
            return ((src[sp] << 8) | src[sp + 1]) & 0xFFF
        if sp + 3 > n_data:
            return None
        return (src[sp] << 16) | (src[sp + 1] << 8) | src[sp + 2]
    if ct >= 6:
        return None
    if src[sp] >= 0x80:
        if sp + 3 > n_data:
            return None
        bits = (src[sp] << 16) | (src[sp + 1] << 8) | src[sp + 2]
        src_size = bits & 0x3FF
        dst_size = src_size + ((bits >> 10) & 0x3FF) + 1
    else:
        if sp + 5 > n_data:
            return None
        bits = (src[sp + 1] << 24) | (src[sp + 2] << 16) | (src[sp + 3] << 8) | src[sp + 4]
        src_size = bits & 0x3FFFF
        dst_size = (((bits >> 18) | (src[sp] << 14)) & 0x3FFFF) + 1
        if src_size >= dst_size:
            return None
    return dst_size


def _decode_multi_array(src: bytes, sp: int, array_data: list,
                        out_limit: int = 0x7FFFFFFF) -> Optional[int]:
    """oozextract decode_multi_array — 多数组熵解码

    array_data: list, 每个元素更新为 (bytes, size)
    返回: 解码后 src 位置 (sp), 或 None
    """
    n_data = len(src)
    if sp >= n_data:
        return None
    num_arrays_in_file = src[sp] & 0x3F
    sp += 1
    if num_arrays_in_file == 0:
        total_size = 0
        for k in range(len(array_data)):
            r, used = _decode_bytes(src[sp:], out_limit)
            if r is None:
                return None
            array_data[k] = (r, len(r))
            sp += used
            total_size += len(r)
        return sp
    # 解码熵数组
    entropy_array_data = []
    for _ in range(num_arrays_in_file):
        r, used = _decode_bytes(src[sp:], out_limit)
        if r is None:
            return None
        entropy_array_data.append(r)
        sp += used
    # q
    if sp + 2 > n_data:
        return None
    q = _u16le(src, sp)
    sp += 2
    # num_indexes
    num_indexes = _get_block_size(src, sp)
    if num_indexes is None:
        return None
    num_lens = num_indexes - len(array_data)
    if num_lens < 0:
        return None
    interval_lenlog2 = [0] * num_indexes
    interval_indexes = [0] * num_indexes
    if q & 0x8000:
        r, used = _decode_bytes(src[sp:], num_indexes)
        if r is None or len(r) != num_indexes:
            return None
        sp += used
        for i in range(num_indexes):
            t = r[i]
            interval_lenlog2[i] = t >> 4
            interval_indexes[i] = t & 0xF
        num_lens = num_indexes
    else:
        lenlog2_chunksize = num_indexes - len(array_data)
        r, used = _decode_bytes(src[sp:], num_indexes)
        if r is None or len(r) != num_indexes:
            return None
        sp += used
        for i in range(num_indexes):
            interval_indexes[i] = r[i]
        r, used = _decode_bytes(src[sp:], lenlog2_chunksize)
        if r is None or len(r) != lenlog2_chunksize:
            return None
        sp += used
        for i in range(lenlog2_chunksize):
            if r[i] > 16:
                return None
            interval_lenlog2[i] = r[i]
    # varbits 解码 intervals
    varbits_complen = q & 0x3FFF
    if sp + varbits_complen > n_data:
        return None
    src_end_actual = sp + varbits_complen
    decoded_intervals = []
    # varbits 解码 intervals — Oodle 真实格式 (rrVarBits 32-bit)
    # Reset: bits=0, inv=24 (BitLen = 24 - inv = 0)
    # Get_0Ok(count) = ((bits>>1) >> (31-count)); 消费 count 位
    # cur_len = (1<<log2) | Get_0Ok(log2)   (PLUS_TOP)
    # 正向 f 从 sp 开始 (大端), 反向 b 从 src_end_actual 开始 (小端)
    vb_f = 0
    vb_inv_f = 24
    vb_c_f = sp
    vb_b = 0
    vb_inv_b = 24
    vb_c_b = src_end_actual
    M32 = 0xFFFFFFFF

    def vb_refill_f():
        nonlocal vb_f, vb_inv_f, vb_c_f
        bl = 24 - vb_inv_f
        bc = (31 - bl) >> 3
        nxt = _be4(src, vb_c_f)
        vb_f = (vb_f | (nxt >> bl)) & M32
        vb_c_f += bc
        vb_inv_f -= bc << 3

    def vb_refill_b():
        nonlocal vb_b, vb_inv_b, vb_c_b
        bl = 24 - vb_inv_b
        bc = (31 - bl) >> 3
        nxt = _le4(src, vb_c_b - 4)
        vb_b = (vb_b | (nxt >> bl)) & M32
        vb_c_b -= bc
        vb_inv_b -= bc << 3

    def vb_get_f(cnt):
        nonlocal vb_f, vb_inv_f
        v = (vb_f >> 1) >> (31 - cnt)
        vb_f = (vb_f << cnt) & M32
        vb_inv_f += cnt
        return v

    def vb_get_b(cnt):
        nonlocal vb_b, vb_inv_b
        v = (vb_b >> 1) >> (31 - cnt)
        vb_b = (vb_b << cnt) & M32
        vb_inv_b += cnt
        return v

    i = 0
    while i + 2 <= num_lens:
        vb_refill_f()
        vb_refill_b()
        nb_f = interval_lenlog2[i]
        nb_b = interval_lenlog2[i + 1]
        decoded_intervals.append((1 << nb_f) | vb_get_f(nb_f))
        decoded_intervals.append((1 << nb_b) | vb_get_b(nb_b))
        i += 2
    if i < num_lens:
        vb_refill_f()
        nb_f = interval_lenlog2[i]
        decoded_intervals.append((1 << nb_f) | vb_get_f(nb_f))
    if num_indexes == 0 or interval_indexes[num_indexes - 1] != 0:
        return None
    # 组装各数组
    indi = 0
    leni = 0
    increment_leni = (q & 0x8000) != 0
    entropy_used = [0] * num_arrays_in_file
    for k in range(len(array_data)):
        out = bytearray()
        while True:
            if indi >= num_indexes:
                return None
            source = interval_indexes[indi]
            indi += 1
            if source == 0:
                break
            if source > num_arrays_in_file:
                return None
            if leni >= len(decoded_intervals):
                return None
            cur_len = decoded_intervals[leni]
            leni += 1
            src_arr = entropy_array_data[source - 1]
            used_so_far = entropy_used[source - 1]
            if used_so_far + cur_len > len(src_arr):
                return None
            out.extend(src_arr[used_so_far:used_so_far + cur_len])
            entropy_used[source - 1] = used_so_far + cur_len
        if increment_leni:
            leni += 1
        array_data[k] = (bytes(out), len(out))
    if indi != num_indexes or leni != num_lens:
        return None
    for i in range(num_arrays_in_file):
        if entropy_used[i] != len(entropy_array_data[i]):
            return None
    return src_end_actual


def _decode_recursive(src: bytes, out_size: int) -> tuple[Optional[bytes], int]:
    """递归解码 (chunk_type=5)"""
    if len(src) < 6:
        return None, -1

    n = src[0] & 0x7F
    if n < 2:
        return None, -1
    sp = 1  # skip count byte

    if not (src[0] & 0x80):
        # 简单模式: n 个子流顺序排列
        output = bytearray()
        for _ in range(n):
            if sp >= len(src):
                return None, -1
            r, used = _decode_bytes(src[sp:], out_size - len(output))
            if r is None or used < 0:
                return None, -1
            output.extend(r)
            sp += used
        return bytes(output[:out_size]), sp

    # MultiArray 模式 — 完整解码
    # 注意: powzix/oozextract 的 recursive else 分支不跳过 count byte,
    # DecodeMultiArray 直接从 src[0] (即 recursive 的 byte) 读 num_arrays_in_file。
    array_data = [None]
    end = _decode_multi_array(src, 0, array_data)
    if end is None:
        return None, -1
    data, size = array_data[0]
    return data, end


# ══════════════════════════════════════════════════════════
# LZ 表处理
# ══════════════════════════════════════════════════════════

class LzTable:
    __slots__ = ('lit', 'cmd', 'offs', 'lens', 'initial_data')
    def __init__(self):
        self.lit = b''
        self.cmd = b''
        self.offs: list[int] = []
        self.lens: list[int] = []
        self.initial_data = b''


# ────────────────────────────────────────────────────────────
# powzix C BitReader (bits + bitpos + p/p_end 模型) — 用于 UnpackOffsets
# ────────────────────────────────────────────────────────────

def _rotl32(x: int, n: int) -> int:
    n &= 31
    if n == 0:
        return x & 0xFFFFFFFF
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _i32(x: int) -> int:
    if x >= 0x80000000:
        x -= 0x100000000
    return x


class BitReaderP:
    """1:1 复刻 powzix BitReader — bits(u32) + bitpos + p/p_end"""
    __slots__ = ('data', 'p', 'p_end', 'bits', 'bitpos')

    def __init__(self, data: bytes, p: int, p_end: int):
        self.data = data
        self.p = p
        self.p_end = p_end
        self.bits = 0
        self.bitpos = 24
        if p <= p_end:
            self.refill()
        else:
            self.refill_backwards()

    def get_byte(self, i: int) -> int:
        if 0 <= i < len(self.data):
            return self.data[i]
        return 0

    def refill(self):
        while self.bitpos > 0:
            self.bits = (self.bits | (self.get_byte(self.p) << self.bitpos)) & 0xFFFFFFFF
            self.bitpos -= 8
            self.p += 1

    def refill_backwards(self):
        while self.bitpos > 0:
            self.p -= 1
            self.bits = (self.bits | (self.get_byte(self.p) << self.bitpos)) & 0xFFFFFFFF
            self.bitpos -= 8

    def read_bit_no_refill(self) -> int:
        r = (self.bits >> 31) & 1
        self.bits = (self.bits << 1) & 0xFFFFFFFF
        self.bitpos += 1
        return r

    def read_bit(self) -> int:
        """oozextract read_bit — 先 refill 再读 bit31"""
        self.refill()
        r = (self.bits >> 31) & 1
        self.bits = (self.bits << 1) & 0xFFFFFFFF
        self.bitpos += 1
        return r

    def read_bits_no_refill(self, n: int) -> int:
        if n >= 32:
            r = self.bits
        else:
            r = (self.bits >> (32 - n)) & ((1 << n) - 1)
        self.bits = (self.bits << n) & 0xFFFFFFFF
        self.bitpos += n
        return r

    def read_bits_no_refill_zero(self, n: int) -> int:
        r = (self.bits >> 1 >> (31 - n)) & ((1 << n) - 1)
        self.bits = (self.bits << n) & 0xFFFFFFFF
        self.bitpos += n
        return r

    def leading_zeros(self) -> int:
        if self.bits == 0:
            return 32
        return 32 - self.bits.bit_length()

    def bsr(self) -> int:
        if self.bits == 0:
            return -1
        return self.bits.bit_length() - 1

    def read_more_than_24bits(self, n: int) -> int:
        if n <= 24:
            rv = self.read_bits_no_refill_zero(n)
        else:
            rv = self.read_bits_no_refill(24) << (n - 24)
            self.refill()
            rv += self.read_bits_no_refill(n - 24)
        self.refill()
        return rv

    def read_more_than_24bits_b(self, n: int) -> int:
        if n <= 24:
            rv = self.read_bits_no_refill_zero(n)
        else:
            rv = self.read_bits_no_refill(24) << (n - 24)
            self.refill_backwards()
            rv += self.read_bits_no_refill(n - 24)
        self.refill_backwards()
        return rv

    def read_distance(self, v: int) -> int:
        v &= 0xFF
        if v < 0xF0:
            n = (v >> 4) + 4
            w = _rotl32(self.bits | 1, n)
            self.bitpos += n
            m = (2 << n) - 1
            self.bits = (w & ~m) & 0xFFFFFFFF
            rv = ((w & m) << 4) + (v & 0xF) - 248
        else:
            n = v - 0xF0 + 4
            w = _rotl32(self.bits | 1, n)
            self.bitpos += n
            m = (2 << n) - 1
            self.bits = (w & ~m) & 0xFFFFFFFF
            rv = 8322816 + ((w & m) << 12)
            self.refill()
            rv += (self.bits >> 20)
            self.bitpos += 12
            self.bits = (self.bits << 12) & 0xFFFFFFFF
        self.refill()
        return rv & 0xFFFFFFFF

    def read_distance_b(self, v: int) -> int:
        v &= 0xFF
        if v < 0xF0:
            n = (v >> 4) + 4
            w = _rotl32(self.bits | 1, n)
            self.bitpos += n
            m = (2 << n) - 1
            self.bits = (w & ~m) & 0xFFFFFFFF
            rv = ((w & m) << 4) + (v & 0xF) - 248
        else:
            n = v - 0xF0 + 4
            w = _rotl32(self.bits | 1, n)
            self.bitpos += n
            m = (2 << n) - 1
            self.bits = (w & ~m) & 0xFFFFFFFF
            rv = 8322816 + ((w & m) << 12)
            self.refill_backwards()
            rv += (self.bits >> (32 - 12))
            self.bitpos += 12
            self.bits = (self.bits << 12) & 0xFFFFFFFF
        self.refill_backwards()
        return rv & 0xFFFFFFFF

    def read_length(self) -> Optional[int]:
        if self.bits == 0:
            return None
        n = 31 - self.bsr()
        if n > 12:
            return None
        self.bitpos += n
        self.bits = (self.bits << n) & 0xFFFFFFFF
        self.refill()
        n += 7
        self.bitpos += n
        rv = (self.bits >> (32 - n)) - 64
        self.bits = (self.bits << n) & 0xFFFFFFFF
        self.refill()
        return rv

    def read_length_b(self) -> Optional[int]:
        if self.bits == 0:
            return None
        n = 31 - self.bsr()
        if n > 12:
            return None
        self.bitpos += n
        self.bits = (self.bits << n) & 0xFFFFFFFF
        self.refill_backwards()
        n += 7
        self.bitpos += n
        rv = (self.bits >> (32 - n)) - 64
        self.bits = (self.bits << n) & 0xFFFFFFFF
        self.refill_backwards()
        return rv


# ────────────────────────────────────────────────────────────
# Kraken_UnpackOffsets — 解包 32 位 offset/len 流
# ────────────────────────────────────────────────────────────

def _unpack_offsets(src: bytes, src_end: int,
                    packed_offs_stream: bytes, packed_offs_stream_extra,
                    packed_offs_stream_size: int, multi_dist_scale: int,
                    packed_litlen_stream: bytes, packed_litlen_stream_size: int,
                    offs_stream: list, len_stream: list) -> bool:
    bits_a = BitReaderP(src, 0, src_end)
    bits_b = BitReaderP(src, src_end, 0)

    # 读取 u32_len_stream_size (反向, gamma-like)
    if bits_b.bits < 0x2000:
        return False
    n = 31 - bits_b.bsr()
    bits_b.bitpos += n
    bits_b.bits = (bits_b.bits << n) & 0xFFFFFFFF
    bits_b.refill_backwards()
    n += 1
    u32_len_stream_size = (bits_b.bits >> (32 - n)) - 1
    bits_b.bitpos += n
    bits_b.bits = (bits_b.bits << n) & 0xFFFFFFFF
    bits_b.refill_backwards()

    if multi_dist_scale == 0:
        # 传统方式: ReadDistance/ReadDistanceB
        i = 0
        while i < packed_offs_stream_size:
            offs_stream.append(-_i32(bits_a.read_distance(packed_offs_stream[i])))
            i += 1
            if i >= packed_offs_stream_size:
                break
            offs_stream.append(-_i32(bits_b.read_distance_b(packed_offs_stream[i])))
            i += 1
    else:
        # 新方式: cmd-based
        offs_start = len(offs_stream)
        i = 0
        while i < packed_offs_stream_size:
            cmd = packed_offs_stream[i]
            i += 1
            if (cmd >> 3) > 26:
                return False
            offs = ((8 + (cmd & 7)) << (cmd >> 3)) | bits_a.read_more_than_24bits(cmd >> 3)
            offs_stream.append(8 - _i32(offs))
            if i >= packed_offs_stream_size:
                break
            cmd = packed_offs_stream[i]
            i += 1
            if (cmd >> 3) > 26:
                return False
            offs = ((8 + (cmd & 7)) << (cmd >> 3)) | bits_b.read_more_than_24bits_b(cmd >> 3)
            offs_stream.append(8 - _i32(offs))
        if multi_dist_scale != 1:
            # CombineScaledOffsetArrays: offs[i] = scale * offs[i] - low_bits[i]
            extra = packed_offs_stream_extra if packed_offs_stream_extra else b''
            for j in range(offs_start, len(offs_stream)):
                lo = extra[j - offs_start] if (j - offs_start) < len(extra) else 0
                offs_stream[j] = multi_dist_scale * offs_stream[j] - lo

    # 读取 u32 长度流 (双向交错)
    u32_len_stream = []
    i = 0
    while i + 1 < u32_len_stream_size:
        v = bits_a.read_length()
        if v is None:
            return False
        u32_len_stream.append(v)
        v = bits_b.read_length_b()
        if v is None:
            return False
        u32_len_stream.append(v)
        i += 2
    if i < u32_len_stream_size:
        v = bits_a.read_length()
        if v is None:
            return False
        u32_len_stream.append(v)

    bits_a.p -= (24 - bits_a.bitpos) >> 3
    bits_b.p += (24 - bits_b.bitpos) >> 3
    if bits_a.p != bits_b.p:
        return False

    leni = 0
    for i in range(packed_litlen_stream_size):
        v = packed_litlen_stream[i]
        if v == 255:
            if leni >= len(u32_len_stream):
                return False
            v = u32_len_stream[leni] + 255
            leni += 1
        len_stream.append(v + 3)
    if leni != len(u32_len_stream):
        return False
    return True


def _read_lz_table(src: bytes, dst_size: int, mode: int, offset: int) -> Optional[LzTable]:
    """powzix Kraken_ReadLzTable"""
    if mode > 1:
        return None
    if len(src) < 13:
        return None

    lzt = LzTable()
    sp = 0
    src_end = len(src)

    # 若 offset == 0, 前 8 字节是原始数据拷贝
    if offset == 0:
        lzt.initial_data = bytes(src[sp:sp + 8])
        sp += 8

    # flag byte (powzix: excess bytes not supported → 失败)
    if src[sp] & 0x80:
        flag = src[sp]
        if (flag & 0xc0) != 0x80:
            return None
        sp += 1
        return None  # excess bytes not supported

    # lit stream (bounded by dst_size)
    r, used = _decode_bytes(src[sp:], dst_size)
    if r is None or used < 0:
        return None
    lzt.lit = r
    sp += used

    # cmd stream (bounded by dst_size)
    r, used = _decode_bytes(src[sp:], dst_size)
    if r is None or used < 0:
        return None
    lzt.cmd = r
    cmd_size = len(r)
    sp += used

    if src_end - sp < 3:
        return None

    offs_scaling = 0
    packed_offs_stream_extra = None

    if src[sp] & 0x80:
        # 2-table 模式
        offs_scaling = src[sp] - 127
        sp += 1
        r, used = _decode_bytes(src[sp:], cmd_size)
        if r is None or used < 0:
            return None
        packed_offs = r
        offs_stream_size = len(r)
        sp += used
        if offs_scaling != 1:
            r, used = _decode_bytes(src[sp:], offs_stream_size)
            if r is None or used < 0 or len(r) != offs_stream_size:
                return None
            packed_offs_stream_extra = r
            sp += used
    else:
        r, used = _decode_bytes(src[sp:], cmd_size)
        if r is None or used < 0:
            return None
        packed_offs = r
        offs_stream_size = len(r)
        sp += used

    # len stream (bounded by dst_size >> 2)
    r, used = _decode_bytes(src[sp:], dst_size >> 2)
    if r is None or used < 0:
        return None
    packed_len = r
    len_stream_size = len(r)
    sp += used

    # C++: Kraken_UnpackOffsets(src, src_end, packed_offs_stream, ...)
    offs_stream = []
    len_stream = []
    if not _unpack_offsets(src[sp:], src_end - sp,
                           packed_offs, packed_offs_stream_extra, offs_stream_size,
                           offs_scaling, packed_len, len_stream_size,
                           offs_stream, len_stream):
        return None
    lzt.offs = offs_stream
    lzt.lens = len_stream
    return lzt


def _process_lz_runs_type1(lzt: LzTable, dst: bytearray, dst_start: int,
                           dst_end: int) -> bool:
    """powzix Kraken_ProcessLzRuns_Type1 (mode==1)"""
    cmd = lzt.cmd
    cmd_idx = 0
    cmd_end = len(cmd)
    len_stream = lzt.lens
    leni = 0
    lit_stream = lzt.lit
    li = 0
    offs_stream = lzt.offs
    oi = 0

    recent_offs = [0] * 7
    recent_offs[3] = -8
    recent_offs[4] = -8
    recent_offs[5] = -8

    dp = dst_start
    while cmd_idx < cmd_end:
        f = cmd[cmd_idx]
        cmd_idx += 1
        litlen = f & 3
        offs_index = f >> 6
        matchlen = (f >> 2) & 0xF

        if litlen == 3:
            if leni >= len(len_stream):
                return False
            litlen = len_stream[leni]
            leni += 1
        recent_offs[6] = offs_stream[oi] if oi < len(offs_stream) else 0

        # 复制 literal (Type1: 直接拷贝 litlen 字节)
        for _ in range(litlen):
            if li < len(lit_stream) and dp < dst_end:
                dst[dp] = lit_stream[li]
            dp += 1
            li += 1

        offset = recent_offs[offs_index + 3]
        recent_offs[offs_index + 3] = recent_offs[offs_index + 2]
        recent_offs[offs_index + 2] = recent_offs[offs_index + 1]
        recent_offs[offs_index + 1] = recent_offs[offs_index + 0]
        recent_offs[3] = offset

        if (offs_index + 1) & 4:
            oi += 1

        # copyfrom = dst + offset (offset 为负)
        if matchlen != 15:
            ml = matchlen + 2
            if ml > dst_end - dp:
                ml = dst_end - dp
            srcp = dp + offset
            if srcp < 0:
                return False
            for i in range(ml):
                if dp < dst_end:
                    dst[dp] = dst[srcp + i]
                dp += 1
        else:
            if leni >= len(len_stream):
                return False
            matchlen = 14 + len_stream[leni]
            leni += 1
            ml = matchlen
            if ml > dst_end - dp:
                ml = dst_end - dp
            srcp = dp + offset
            if srcp < 0:
                return False
            for i in range(ml):
                if dp < dst_end:
                    dst[dp] = dst[srcp + i]
                dp += 1

    # 最终 literal 拷贝
    if oi != len(offs_stream) or leni != len(len_stream):
        return False
    final_len = dst_end - dp
    if final_len != len(lit_stream) - li:
        return False
    for _ in range(final_len):
        if dp < dst_end and li < len(lit_stream):
            dst[dp] = lit_stream[li]
        dp += 1
        li += 1
    return True


def _process_lz_runs_type0(lzt: LzTable, dst: bytearray, dst_start: int,
                           dst_end: int, last_offset_ref: list) -> bool:
    """powzix Kraken_ProcessLzRuns_Type0 (mode==0) — literal 差分编码"""
    cmd = lzt.cmd
    cmd_idx = 0
    cmd_end = len(cmd)
    len_stream = lzt.lens
    leni = 0
    lit_stream = lzt.lit
    li = 0
    offs_stream = lzt.offs
    oi = 0

    recent_offs = [0] * 7
    recent_offs[3] = -8
    recent_offs[4] = -8
    recent_offs[5] = -8
    last_offset = -8

    dp = dst_start
    while cmd_idx < cmd_end:
        f = cmd[cmd_idx]
        cmd_idx += 1
        litlen = f & 3
        offs_index = f >> 6
        matchlen = (f >> 2) & 0xF

        if litlen == 3:
            if leni >= len(len_stream):
                return False
            litlen = len_stream[leni]
            leni += 1
        recent_offs[6] = offs_stream[oi] if oi < len(offs_stream) else 0

        # 复制 literal (Type0: 差分, dst[i] = lit[i] + dst[last_offset+i])
        for _ in range(litlen):
            if li < len(lit_stream) and dp < dst_end:
                src_idx = dp + last_offset
                if 0 <= src_idx < len(dst):
                    dst[dp] = (lit_stream[li] + dst[src_idx]) & 0xFF
            dp += 1
            li += 1

        offset = recent_offs[offs_index + 3]
        recent_offs[offs_index + 3] = recent_offs[offs_index + 2]
        recent_offs[offs_index + 2] = recent_offs[offs_index + 1]
        recent_offs[offs_index + 1] = recent_offs[offs_index + 0]
        recent_offs[3] = offset
        last_offset = offset

        if (offs_index + 1) & 4:
            oi += 1

        if matchlen != 15:
            ml = matchlen + 2
            if ml > dst_end - dp:
                ml = dst_end - dp
            srcp = dp + offset
            if srcp < 0:
                return False
            for i in range(ml):
                if dp < dst_end:
                    dst[dp] = dst[srcp + i]
                dp += 1
        else:
            if leni >= len(len_stream):
                return False
            matchlen = 14 + len_stream[leni]
            leni += 1
            ml = matchlen
            if ml > dst_end - dp:
                ml = dst_end - dp
            srcp = dp + offset
            if srcp < 0:
                return False
            for i in range(ml):
                if dp < dst_end:
                    dst[dp] = dst[srcp + i]
                dp += 1

    if oi != len(offs_stream) or leni != len(len_stream):
        return False
    final_len = dst_end - dp
    if final_len != len(lit_stream) - li:
        return False
    # 最终 literal (Type0: 差分)
    for _ in range(final_len):
        if dp < dst_end and li < len(lit_stream):
            src_idx = dp + last_offset
            if 0 <= src_idx < len(dst):
                dst[dp] = (lit_stream[li] + dst[src_idx]) & 0xFF
        dp += 1
        li += 1
    last_offset_ref[0] = last_offset
    return True


# ══════════════════════════════════════════════════════════
# Mermaid (decoder_type 10) 解码
# ══════════════════════════════════════════════════════════

class MermaidLzTable:
    __slots__ = ('lit_stream', 'cmd_stream', 'cmd_stream_2_offs',
                 'cmd_stream_2_offs_end', 'off16_stream',
                 'off32_stream_1', 'off32_stream_2', 'length_stream',
                 'initial_data')
    def __init__(self):
        self.lit_stream = b''
        self.cmd_stream = b''
        self.cmd_stream_2_offs = 0
        self.cmd_stream_2_offs_end = 0
        self.off16_stream: list[int] = []
        self.off32_stream_1: list[int] = []
        self.off32_stream_2: list[int] = []
        self.length_stream = b''
        self.initial_data = b''


def _mermaid_decode_far_offsets(data: bytes, sp: int, output_size: int,
                                offset: int) -> tuple[list[int], int]:
    offs = []
    if offset < 0xC00000 - 1:
        for _ in range(output_size):
            off = data[sp] | (data[sp + 1] << 8) | (data[sp + 2] << 16)
            sp += 3
            offs.append(off)
    else:
        for _ in range(output_size):
            off = data[sp] | (data[sp + 1] << 8) | (data[sp + 2] << 16)
            sp += 3
            if off >= 0xC00000:
                off += data[sp] << 22
                sp += 1
            offs.append(off)
    return offs, sp


def _read_lz_table_mermaid(src: bytes, dst_size: int, mode: int,
                           offset: int) -> Optional[MermaidLzTable]:
    """oozextract MermaidLzTable::read_lz_table"""
    if mode > 1:
        return None
    if len(src) < 10:
        return None
    lzt = MermaidLzTable()
    sp = 0
    if offset == 0:
        lzt.initial_data = bytes(src[0:8])
        sp = 8
    # lit 流
    r, used = _decode_bytes(src[sp:], dst_size)
    if r is None:
        return None
    lzt.lit_stream = r
    sp += used
    # cmd/flag 流
    r, used = _decode_bytes(src[sp:], dst_size)
    if r is None:
        return None
    lzt.cmd_stream = r
    cmd_size = len(r)
    sp += used
    lzt.cmd_stream_2_offs_end = cmd_size
    if dst_size <= 0x10000:
        lzt.cmd_stream_2_offs = cmd_size
    else:
        if sp + 2 > len(src):
            return None
        lzt.cmd_stream_2_offs = _u16le(src, sp)
        sp += 2
    # off16
    if sp + 2 > len(src):
        return None
    off16_count = _u16le(src, sp)
    sp += 2
    if off16_count == 0xFFFF:
        r, used = _decode_bytes(src[sp:], dst_size >> 1)
        if r is None:
            return None
        off16_hi = r
        sp += used
        r, used = _decode_bytes(src[sp:], dst_size >> 1)
        if r is None:
            return None
        off16_lo = r
        sp += used
        if len(off16_lo) != len(off16_hi):
            return None
        lzt.off16_stream = [off16_lo[i] + (off16_hi[i] << 8)
                            for i in range(len(off16_lo))]
    else:
        if sp + off16_count * 2 > len(src):
            return None
        off16_bytes = src[sp:sp + off16_count * 2]
        sp += off16_count * 2
        lzt.off16_stream = [off16_bytes[i] | (off16_bytes[i + 1] << 8)
                            for i in range(0, len(off16_bytes), 2)]
    # off32 sizes
    if sp + 3 > len(src):
        return None
    tmp = src[sp] | (src[sp + 1] << 8) | (src[sp + 2] << 16)
    sp += 3
    if tmp != 0:
        off32_size_1 = tmp >> 12
        off32_size_2 = tmp & 0xFFF
        if off32_size_1 == 4095:
            if sp + 2 > len(src):
                return None
            off32_size_1 = _u16le(src, sp)
            sp += 2
        if off32_size_2 == 4095:
            if sp + 2 > len(src):
                return None
            off32_size_2 = _u16le(src, sp)
            sp += 2
        lzt.off32_stream_1, sp = _mermaid_decode_far_offsets(
            src, sp, off32_size_1, offset)
        lzt.off32_stream_2, sp = _mermaid_decode_far_offsets(
            src, sp, off32_size_2, offset + 0x10000)
    lzt.length_stream = src[sp:]
    return lzt


def _process_lz_runs_mermaid(lzt: MermaidLzTable, dst: bytearray,
                             dst_pos: int, dst_size: int, mode: int,
                             offset: int) -> bool:
    """oozextract MermaidLzTable::process_lz_runs + process
    精确复刻 powzix 的 SIMD 过度写语义 (COPY_64/COPY_64_ADD 写 8 字节但只前进 n)"""
    saved_dist = -8
    lit_index = 0
    length_index = 0
    off16_index = 0
    add_mode = (mode == 0)
    dst_remaining = dst_size
    lit = lzt.lit_stream
    dst_len_all = len(dst)

    for iteration in range(2):
        dst_size_cur = min(dst_remaining, 0x10000)
        dst_cur = dst_pos + (dst_size - dst_remaining)
        dst_cur_end = dst_cur + dst_size_cur
        if iteration == 0:
            cmd_index = 0
            cmd_end = lzt.cmd_stream_2_offs
            off32 = lzt.off32_stream_1
        else:
            cmd_index = lzt.cmd_stream_2_offs
            cmd_end = lzt.cmd_stream_2_offs_end
            off32 = lzt.off32_stream_2
        startoff = 8 if (offset == 0 and iteration == 0) else 0
        dst_begin = dst_cur
        dp = dst_cur + startoff
        off32_index = 0
        recent_offs = saved_dist

        def lit_val(si, pos):
            """mode0: lit+prev; mode1: lit"""
            if si < len(lit):
                if add_mode:
                    src_idx = pos + recent_offs
                    if 0 <= src_idx < dst_len_all:
                        return (lit[si] + dst[src_idx]) & 0xFF
                    return lit[si]
                return lit[si]
            return None

        def copy_lit(n):
            """powzix COPY_64/COPY_64_ADD: 写 8 字节, 前进 n"""
            nonlocal dp, lit_index
            for k in range(8):
                if dp + k >= dst_len_all:
                    break
                v = lit_val(lit_index + k, dp + k)
                if v is not None:
                    dst[dp + k] = v
            dp += n
            lit_index += n

        def copy_match(n, srcp):
            """powzix COPY_64 x2: 写 16 字节, 前进 n"""
            nonlocal dp
            for i in range(16):
                if dp + i >= dst_len_all:
                    break
                si = srcp + i
                if 0 <= si < dst_len_all:
                    dst[dp + i] = dst[si]
            dp += n

        def copy_lit_blocks(length):
            """flag==0: 16 字节块 COPY_64_ADD x2 + 回退"""
            nonlocal dp, lit_index
            while length > 0:
                for k in range(16):
                    if dp + k >= dst_len_all:
                        break
                    v = lit_val(lit_index + k, dp + k)
                    if v is not None:
                        dst[dp + k] = v
                dp += 16
                lit_index += 16
                length -= 16
            dp += length
            lit_index += length

        def copy_match_blocks(length, srcp):
            """flag==1/2: 16 字节块 COPY_64 x2 + 回退 (srcp 前进)"""
            nonlocal dp
            while length > 0:
                for i in range(16):
                    if dp + i >= dst_len_all:
                        break
                    si = srcp + i
                    if 0 <= si < dst_len_all:
                        dst[dp + i] = dst[si]
                dp += 16
                srcp += 16
                length -= 16
            dp += length

        while cmd_index < cmd_end:
            cmd = lzt.cmd_stream[cmd_index]
            cmd_index += 1
            if cmd >= 24:
                litlen = cmd & 7
                copy_lit(litlen)
                # powzix: use_distance = (cmd>>7) - 1
                #  -1 (cmd>>7==0): 用新 offset 并推进 off16
                #   0 (cmd>>7==1): 用旧 offset
                #   1 (cmd>>7==2): 用新 offset 但不推进 off16
                use_distance = (cmd >> 7) - 1
                if use_distance != 0:
                    if off16_index >= len(lzt.off16_stream):
                        return False
                    recent_offs = -lzt.off16_stream[off16_index]
                    if use_distance & 2:
                        off16_index += 1
                ml = (cmd >> 3) & 0xF
                copy_match(ml, dp + recent_offs)
            elif cmd > 2:
                length = cmd + 5
                offs_ptr = dst_begin - off32[off32_index]
                off32_index += 1
                recent_offs = offs_ptr - dp
                # COPY_64 x4: 写 32 字节, 前进 length
                for i in range(32):
                    if dp + i >= dst_len_all:
                        break
                    si = offs_ptr + i
                    if 0 <= si < dst_len_all:
                        dst[dp + i] = dst[si]
                dp += length
            elif cmd == 0:
                length = lzt.length_stream[length_index]
                if length > 251:
                    length += _u16le(lzt.length_stream, length_index + 1) * 4
                    length_index += 2
                length_index += 1
                length += 64
                copy_lit_blocks(length)
            elif cmd == 1:
                length = lzt.length_stream[length_index]
                if length > 251:
                    length += _u16le(lzt.length_stream, length_index + 1) * 4
                    length_index += 2
                length_index += 1
                length += 91
                offs_ptr = dp - lzt.off16_stream[off16_index]
                off16_index += 1
                recent_offs = offs_ptr - dp
                copy_match_blocks(length, offs_ptr)
            else:  # cmd == 2
                length = lzt.length_stream[length_index]
                if length > 251:
                    length += _u16le(lzt.length_stream, length_index + 1) * 4
                    length_index += 2
                length_index += 1
                length += 29
                offs_ptr = dst_begin - off32[off32_index]
                off32_index += 1
                recent_offs = offs_ptr - dp
                copy_match_blocks(length, offs_ptr)

        # final literal (8 字节块循环 + 余数)
        length = dst_cur_end - dp
        while length >= 8:
            for k in range(8):
                if dp + k >= dst_len_all:
                    break
                v = lit_val(lit_index + k, dp + k)
                if v is not None:
                    dst[dp + k] = v
            dp += 8
            lit_index += 8
            length -= 8
        while length > 0:
            if dp < dst_len_all:
                v = lit_val(lit_index, dp)
                if v is not None:
                    dst[dp] = v
            dp += 1
            lit_index += 1
            length -= 1
        saved_dist = recent_offs
        dst_remaining -= dst_size_cur
        if dst_remaining <= 0:
            break
    return True


# ══════════════════════════════════════════════════════════
# Leviathan (decoder_type 12) 解码
# ══════════════════════════════════════════════════════════

class LeviathanLzTable:
    __slots__ = ('offs_stream', 'len_stream', 'lit_stream', 'lit_stream_total',
                 'multi_cmd_ptr', 'cmd_stream', 'cmd_stream_size', 'initial_data')
    def __init__(self):
        self.offs_stream: list[int] = []
        self.len_stream: list[int] = []
        self.lit_stream: list = [None] * 16
        self.lit_stream_total = 0
        self.multi_cmd_ptr: list = [None] * 8
        self.cmd_stream = None
        self.cmd_stream_size = 0
        self.initial_data = b''


def _read_lz_table_leviathan(src: bytes, dst_size: int, mode: int,
                             offset: int) -> Optional[LeviathanLzTable]:
    """oozextract LeviathanLzTable::read_lz_table"""
    if mode > 5:
        return None
    if len(src) < 13:
        return None
    lzt = LeviathanLzTable()
    sp = 0
    if offset == 0:
        lzt.initial_data = bytes(src[0:8])
        sp = 8
    offs_scaling = 0
    packed_offs_stream_extra = None
    offs_stream_limit = dst_size // 3
    if (src[sp] & 0x80) == 0:
        r, used = _decode_bytes(src[sp:], offs_stream_limit)
        if r is None:
            return None
        packed_offs_stream = r
        offs_stream_size = len(r)
        sp += used
    else:
        offs_scaling = src[sp] - 127
        sp += 1
        r, used = _decode_bytes(src[sp:], offs_stream_limit)
        if r is None:
            return None
        packed_offs_stream = r
        offs_stream_size = len(r)
        sp += used
        if offs_scaling != 1:
            r, used = _decode_bytes(src[sp:], offs_stream_limit)
            if r is None or len(r) != offs_stream_size:
                return None
            packed_offs_stream_extra = r
            sp += used
    # packed_len_stream
    r, used = _decode_bytes(src[sp:], dst_size // 5)
    if r is None:
        return None
    packed_len_stream = r
    len_stream_size = len(r)
    sp += used
    # 注意: _unpack_offsets 用 append 填充, 必须传空列表
    lzt.offs_stream = []
    lzt.len_stream = []
    # lit 流
    if mode <= 1:
        r, used = _decode_bytes(src[sp:], dst_size)
        if r is None:
            return None
        lzt.lit_stream[0] = (r, len(r))
        sp += used
        lzt.lit_stream_total = len(r)
    else:
        array_count = 2 if mode == 2 else (4 if mode == 3 else 16)
        arr = [None] * array_count
        end = _decode_multi_array(src, sp, arr, 0x7FFFFFFF)
        if end is None:
            return None
        sp = end
        tot = 0
        for i in range(array_count):
            lzt.lit_stream[i] = arr[i]
            if arr[i] is not None:
                tot += arr[i][1]
        lzt.lit_stream_total = tot
    # cmd 流
    if sp >= len(src):
        return None
    flag = src[sp]
    if (flag & 0x80) == 0:
        r, used = _decode_bytes(src[sp:], dst_size)
        if r is None:
            return None
        lzt.cmd_stream = r
        lzt.cmd_stream_size = len(r)
        sp += used
    else:
        if flag != 0x83:
            return None
        sp += 1
        arr = [None] * 8
        end = _decode_multi_array(src, sp, arr, 0x7FFFFFFF)
        if end is None:
            return None
        sp = end
        lzt.multi_cmd_ptr = arr
        lzt.cmd_stream = None
        lzt.cmd_stream_size = sum(s for _, s in arr if _ is not None)
    # unpack_offsets
    tail = src[sp:]
    if not _unpack_offsets(tail, len(tail), packed_offs_stream,
                           packed_offs_stream_extra, offs_stream_size,
                           offs_scaling, packed_len_stream, len_stream_size,
                           lzt.offs_stream, lzt.len_stream):
        return None
    return lzt


def _process_lz_runs_leviathan(lzt: LeviathanLzTable, dst: bytearray,
                               dst_pos: int, dst_size: int, mode: int,
                               offset: int) -> bool:
    """oozextract LeviathanLzTable::process_lz_runs + process_lz"""
    dst_cur = dst_pos + 8 if offset == 0 else dst_pos
    dst_end = dst_pos + dst_size
    dst_start = dst_pos - offset  # window base
    if dst_end - dst_start >= 16:
        match_zone_end = dst_end - 16
    else:
        match_zone_end = dst_start

    recent_offs = [0] * 16
    for i in range(8, 15):
        recent_offs[i] = -8
    cur_offset = -8

    offs_stream = lzt.offs_stream
    offs_index = 0
    len_stream = lzt.len_stream
    len_fwd = 0      # len_stream.next()
    len_bwd = len(len_stream)  # len_stream.next_back()

    # mode 状态
    li = [0] * 16  # lit 流索引
    if mode == 4:
        # O1: next_lit 初始化
        # oozextract LeviathanModeO1::new: lit_streams[i] = stream + 1 (流[0] 被 next_lit 消耗),
        # next_lit[i] = stream[0]。所以 li[i] 从 1 开始。
        next_lit = [0] * 16
        for i in range(16):
            if lzt.lit_stream[i] is not None:
                d, _ = lzt.lit_stream[i]
                next_lit[i] = d[0] if len(d) > 0 else 0
                li[i] = 1
        context = 0
    else:
        next_lit = None
        context = 0

    def lit_data(i):
        if lzt.lit_stream[i] is not None:
            return lzt.lit_stream[i][0]
        return b''

    # cmd 流初始化
    if lzt.cmd_stream is not None:
        cmd_index = 0
        cmd_end = lzt.cmd_stream_size
        multi = False
    else:
        multi = True
        cmd_left = lzt.cmd_stream_size
        # streams[j] = multi_cmd_ptr[(j - dst_start) & 7], index 从 0 开始
        streams = [(None, 0)] * 8
        for j in range(8):
            p = (j - dst_start) & 7
            md = lzt.multi_cmd_ptr[p]
            if md is not None:
                streams[j] = (md[0], 0)
        cmd_index = 0
        cmd_end = 0

    def copy_literals_mode(cmd):
        """按 mode 拷贝 literal, 更新 dst_cur/li/len_fwd"""
        nonlocal dst_cur, li, len_fwd, context, next_lit
        if mode == 0:
            litlen = (cmd >> 3) & 3
            if litlen == 3:
                if len_fwd >= len(len_stream):
                    return False
                litlen = len_stream[len_fwd] & 0xFFFFFF
                len_fwd += 1
            d = lit_data(0)
            for _ in range(litlen):
                if li[0] < len(d) and dst_cur < dst_end:
                    src_idx = dst_cur + cur_offset
                    if 0 <= src_idx < len(dst):
                        dst[dst_cur] = (d[li[0]] + dst[src_idx]) & 0xFF
                dst_cur += 1
                li[0] += 1
        elif mode == 1:
            litlen = (cmd >> 3) & 3
            if litlen == 3:
                if len_fwd >= len(len_stream):
                    return False
                litlen = len_stream[len_fwd] & 0xFFFFFF
                len_fwd += 1
            d = lit_data(0)
            for _ in range(litlen):
                if li[0] < len(d) and dst_cur < dst_end:
                    dst[dst_cur] = d[li[0]]
                dst_cur += 1
                li[0] += 1
        elif mode == 2:
            lit_cmd = cmd & 0x18
            if lit_cmd == 0:
                return True
            litlen = lit_cmd >> 3
            if litlen == 3:
                if len_fwd >= len(len_stream):
                    return False
                litlen = len_stream[len_fwd] & 0xFFFFFF
                len_fwd += 1
            if litlen < 1:
                return True
            litlen -= 1
            lam = lit_data(1)
            d = lit_data(0)
            if li[1] < len(lam) and dst_cur < dst_end:
                src_idx = dst_cur + cur_offset
                if 0 <= src_idx < len(dst):
                    dst[dst_cur] = (lam[li[1]] + dst[src_idx]) & 0xFF
            li[1] += 1
            dst_cur += 1
            for _ in range(litlen):
                if li[0] < len(d) and dst_cur < dst_end:
                    src_idx = dst_cur + cur_offset
                    if 0 <= src_idx < len(dst):
                        dst[dst_cur] = (d[li[0]] + dst[src_idx]) & 0xFF
                dst_cur += 1
                li[0] += 1
        elif mode in (3, 5):
            num = 4 if mode == 3 else 16
            lit_cmd = cmd & 0x18
            if lit_cmd == 0x18:
                if len_fwd >= len(len_stream):
                    return False
                litlen = len_stream[len_fwd] & 0xFFFFFF
                len_fwd += 1
                for _ in range(litlen):
                    slot = dst_cur & (num - 1)
                    d = lit_data(slot)
                    if li[slot] < len(d) and dst_cur < dst_end:
                        src_idx = dst_cur + cur_offset
                        if 0 <= src_idx < len(dst):
                            dst[dst_cur] = (d[li[slot]] + dst[src_idx]) & 0xFF
                    dst_cur += 1
                    li[slot] += 1
            elif lit_cmd != 0:
                slot = dst_cur & (num - 1)
                d = lit_data(slot)
                if li[slot] < len(d) and dst_cur < dst_end:
                    src_idx = dst_cur + cur_offset
                    if 0 <= src_idx < len(dst):
                        dst[dst_cur] = (d[li[slot]] + dst[src_idx]) & 0xFF
                dst_cur += 1
                li[slot] += 1
                if lit_cmd == 0x10:
                    slot = dst_cur & (num - 1)
                    d = lit_data(slot)
                    if li[slot] < len(d) and dst_cur < dst_end:
                        src_idx = dst_cur + cur_offset
                        if 0 <= src_idx < len(dst):
                            dst[dst_cur] = (d[li[slot]] + dst[src_idx]) & 0xFF
                    dst_cur += 1
                    li[slot] += 1
        else:  # mode 4 O1
            lit_cmd = cmd & 0x18
            if lit_cmd == 0x18:
                if len_fwd >= len(len_stream):
                    return False
                litlen = len_stream[len_fwd]
                len_fwd += 1
                context = dst[dst_cur - 1] if dst_cur > dst_pos else 0
                for _ in range(litlen):
                    if not _o1_copy():
                        return False
            elif lit_cmd != 0:
                context = dst[dst_cur - 1] if dst_cur > dst_pos else 0
                if not _o1_copy():
                    return False
                if lit_cmd == 0x10:
                    if not _o1_copy():
                        return False
        return True

    def _o1_copy():
        nonlocal dst_cur, context, next_lit
        slot = (context >> 4) & 0xF
        context = next_lit[slot]
        if dst_cur < dst_end:
            dst[dst_cur] = context
        dst_cur += 1
        d = lit_data(slot)
        if li[slot] < len(d):
            next_lit[slot] = d[li[slot]]
        else:
            next_lit[slot] = 0
        li[slot] += 1
        return True

    while True:
        if multi:
            if cmd_left <= 0:
                break
            cmd_left -= 1
            slot = dst_cur & 7
            sdata, sindex = streams[slot]
            if sdata is None:
                return False
            if sindex >= len(sdata):
                return False
            cmd = sdata[sindex]
            streams[slot] = (sdata, sindex + 1)
        else:
            if cmd_index >= cmd_end:
                break
            cmd = lzt.cmd_stream[cmd_index]
            cmd_index += 1

        offs_idx_val = cmd >> 5
        if offs_idx_val > 8:
            return False
        matchlen = (cmd & 7) + 2
        recent_offs[15] = offs_stream[offs_index] if offs_index < len(offs_stream) else 0

        if not copy_literals_mode(cmd):
            return False

        cur_offset = recent_offs[offs_idx_val + 8]
        # 置换 recent_offs: copy_within(offs_idx..offs_idx+8, offs_idx+1)
        seg = recent_offs[offs_idx_val:offs_idx_val + 8]
        recent_offs[offs_idx_val + 1:offs_idx_val + 9] = seg
        recent_offs[8] = cur_offset
        if offs_idx_val == 7:
            offs_index += 1

        copyfrom = dst_cur + cur_offset
        if copyfrom < 0 or copyfrom >= len(dst):
            return False
        if matchlen == 9:
            if len_bwd <= len_fwd:
                return False
            len_bwd -= 1
            matchlen = len_stream[len_bwd] + 6
        if matchlen > dst_end - dst_cur:
            matchlen = dst_end - dst_cur
        for i in range(matchlen):
            if dst_cur < dst_end:
                dst[dst_cur] = dst[copyfrom + i]
            dst_cur += 1

    # 检查 offs/len 用完
    if offs_index != len(offs_stream) or len_fwd != len_bwd:
        return False
    # final literals
    final_len = dst_end - dst_cur
    if mode == 0:
        d = lit_data(0)
        for _ in range(final_len):
            if li[0] < len(d) and dst_cur < dst_end:
                src_idx = dst_cur + cur_offset
                if 0 <= src_idx < len(dst):
                    dst[dst_cur] = (d[li[0]] + dst[src_idx]) & 0xFF
            dst_cur += 1
            li[0] += 1
    elif mode == 1:
        d = lit_data(0)
        for _ in range(final_len):
            if li[0] < len(d) and dst_cur < dst_end:
                dst[dst_cur] = d[li[0]]
            dst_cur += 1
            li[0] += 1
    elif mode == 2:
        if final_len >= 1:
            lam = lit_data(1)
            if li[1] < len(lam) and dst_cur < dst_end:
                src_idx = dst_cur + cur_offset
                if 0 <= src_idx < len(dst):
                    dst[dst_cur] = (lam[li[1]] + dst[src_idx]) & 0xFF
            li[1] += 1
            dst_cur += 1
            final_len -= 1
            d = lit_data(0)
            for _ in range(final_len):
                if li[0] < len(d) and dst_cur < dst_end:
                    src_idx = dst_cur + cur_offset
                    if 0 <= src_idx < len(dst):
                        dst[dst_cur] = (d[li[0]] + dst[src_idx]) & 0xFF
                dst_cur += 1
                li[0] += 1
    elif mode in (3, 5):
        num = 4 if mode == 3 else 16
        for _ in range(final_len):
            slot = dst_cur & (num - 1)
            d = lit_data(slot)
            if li[slot] < len(d) and dst_cur < dst_end:
                src_idx = dst_cur + cur_offset
                if 0 <= src_idx < len(dst):
                    dst[dst_cur] = (d[li[slot]] + dst[src_idx]) & 0xFF
            dst_cur += 1
            li[slot] += 1
    else:  # mode 4 O1
        context = dst[dst_cur - 1] if dst_cur > dst_pos else 0
        for _ in range(final_len):
            if not _o1_copy():
                return False
    return dst_cur == dst_end


def _process_lz_runs(lzt, dst: bytearray, dst_pos: int,
                     dst_size: int, mode: int, offset: int,
                     decoder_type: int = 6) -> bool:
    """分派到 Kraken / Mermaid / Leviathan LZ 处理"""
    # 所有类型: offset==0 时先写 initial 8 字节 (process 从 +8 开始)
    if offset == 0:
        init = getattr(lzt, 'initial_data', b'')
        if init:
            n = min(len(init), dst_pos + dst_size - dst_pos)
            dst[dst_pos:dst_pos + n] = init[:n]
    if decoder_type == 10:
        return _process_lz_runs_mermaid(lzt, dst, dst_pos, dst_size, mode, offset)
    if decoder_type == 12:
        return _process_lz_runs_leviathan(lzt, dst, dst_pos, dst_size, mode, offset)
    dst_end = dst_pos + dst_size
    # dst_start = block 起始 (相对输出 buffer 的绝对位置)
    # powzix: ProcessLzRuns_Type1(lzt, dst + (offset==0 ? 8 : 0), dst_end, dst - offset)
    #   dst 参数 = 当前块写入起始; dst_start = dst - offset (整个窗口起始)
    block_start = dst_pos
    if offset == 0:
        # 先复制 initial 8 字节
        init = lzt.initial_data
        if init:
            n = min(len(init), dst_end - block_start)
            dst[block_start:block_start + n] = init[:n]
        write_start = block_start + 8
    else:
        write_start = block_start

    if mode == 1:
        return _process_lz_runs_type1(lzt, dst, write_start, dst_end)
    else:
        ref = [0]
        ok = _process_lz_runs_type0(lzt, dst, write_start, dst_end, ref)
        return ok


# ══════════════════════════════════════════════════════════
# Quantum 解码
# ══════════════════════════════════════════════════════════

def _decode_quantum(dst: bytearray, dst_off: int,
                    src: bytes, scratch: bytearray,
                    dst_bytes: int = None, decoder_type: int = 6,
                    restart: bool = False) -> int:
    """解码一个量子块 (256KB)，返回消耗的 src 字节数

    restart=True 时该块是独立解码单元 (header.restart 置位):
    LZ 表 offset 从块起点算 (第一个 128KB chunk 的 offset==0, 读 initial 8 字节),
    窗口基址 = dst_off (不共享之前的窗口)。
    restart=False 时 offset 用绝对输出位置, 窗口基址 = 0 (共享整个文件窗口)。
    """
    sp = 0
    dp = dst_off
    if dst_bytes is None:
        dst_bytes = len(dst) - dst_off
    dst_end = dst_off + dst_bytes

    while dp < dst_end:
        chunk_sz = min(dst_end - dp, 0x20000)
        if sp + 3 > len(src):
            return -1
        
        # 3 字节反序块头 (匹配 C++ 位布局)
        ch = src[sp + 2] | (src[sp + 1] << 8) | (src[sp] << 16)
        
        if not (ch & 0x800000):
            # 纯熵解码 — 不跳过 3 字节 (chunkhdr 本身是 _decode_bytes header 的一部分)
            data, used = _decode_bytes(src[sp:], chunk_sz)
            if data is None or used < 0 or len(data) != chunk_sz:
                return -1
            dst[dp:dp + chunk_sz] = data
            sp += used
        else:
            sp += 3
            src_used = ch & 0x7FFFF
            mode = (ch >> 19) & 0xF
            if sp + src_used > len(src):
                # 处理 off-by-1: 夹紧到实际可用
                src_used = len(src) - sp
            if src_used < 0:
                return -1
            
            if src_used < chunk_sz:
                lz_data = src[sp:sp + src_used]
                # offset 决定 LZ 表读取是否读 initial 8 字节 (offset==0) 及窗口基址:
                #  - restart 块: 相对块起点 (dp-dst_off), 第一个 chunk offset==0 → 读 initial
                #  - 非 restart 块: 绝对输出位置 (dp), offset==0 仅当这是整个文件的第一个块
                offset = (dp - dst_off) if restart else dp
                if decoder_type == 10:
                    lzt = _read_lz_table_mermaid(lz_data, chunk_sz, mode, offset)
                elif decoder_type == 12:
                    lzt = _read_lz_table_leviathan(lz_data, chunk_sz, mode, offset)
                else:
                    lzt = _read_lz_table(lz_data, chunk_sz, mode, offset)
                if lzt is None:
                    return -1
                if not _process_lz_runs(lzt, dst, dp, chunk_sz, mode, offset, decoder_type):
                    return -1
                sp += src_used
            elif mode != 0:
                return -1
            else:
                if src_used > chunk_sz:
                    return -1
                dst[dp:dp + src_used] = src[sp:sp + src_used]
                sp += src_used
        
        dp += chunk_sz
    
    return sp


# ══════════════════════════════════════════════════════════
# 顶层解压
# ══════════════════════════════════════════════════════════

def decompress(src: bytes, dst_len: int) -> bytes:
    """解压 Oodle Kraken 压缩数据"""
    dst = bytearray(dst_len)
    src_off = 0
    offset = 0
    remaining = dst_len
    hdr = None
    
    while remaining != 0:
        if src_off >= len(src):
            raise ValueError("Kraken: insufficient input")
        
        # 每 256KB 解析一次 Kraken 头
        if (offset & 0x3FFFF) == 0:
            hdr, src_off = _parse_kraken_header(src, src_off)
            if hdr is None:
                raise ValueError("Kraken: invalid header")
        
        is_kraken = hdr['decoder_type'] in (6, 10, 12)
        chunk_limit = 0x40000 if is_kraken else 0x4000
        dst_bytes = min(chunk_limit, remaining)
        
        # 未压缩块 (uncompressed=1): 直接拷贝 dst_bytes 字节
        if hdr['uncompressed']:
            if src_off + dst_bytes > len(src):
                raise ValueError("Kraken: not enough input for uncompressed")
            dst[offset:offset + dst_bytes] = src[src_off:src_off + dst_bytes]
            src_off += dst_bytes
            offset += dst_bytes
            remaining -= dst_bytes
            continue
        
        qh, src_off = _parse_quantum_header(src, src_off, hdr['use_checksums'])
        if qh is None:
            raise ValueError("Kraken: invalid quantum header")
        
        cs = qh['compressed_size']
        
        if cs == 0:
            wmd = qh['whole_match_distance']
            if wmd != 0:
                for i in range(dst_bytes):
                    dst[offset + i] = dst[offset + i - wmd]
            else:
                for i in range(dst_bytes):
                    dst[offset + i] = qh['checksum'] & 0xFF
            offset += dst_bytes
            remaining -= dst_bytes
            continue
        
        if cs > dst_bytes:
            raise ValueError("Kraken: compressed size > dst bytes")
        
        if src_off + cs > len(src):
            raise ValueError("Kraken: not enough input for quantum")
        
        if cs == dst_bytes:
            dst[offset:offset + dst_bytes] = src[src_off:src_off + dst_bytes]
            src_off += dst_bytes
            offset += dst_bytes
            remaining -= dst_bytes
            continue
        
        if hdr['decoder_type'] in (6, 10, 12):
            chunk_data = src[src_off:src_off + cs]
            n = _decode_quantum(dst, offset, chunk_data, bytearray(), dst_bytes,
                                hdr['decoder_type'], hdr['restart'])
            if n < 0:
                raise ValueError("Kraken: quantum decode failed")
            src_off += n
        else:
            raise ValueError(f"Kraken: unsupported decoder type {hdr['decoder_type']}")
        
        offset += dst_bytes
        remaining -= dst_bytes
    
    return bytes(dst)


class KrakenStreamError(Exception):
    """Kraken 流无法逐块解压（遇到 restart=False 的跨块引用块）"""
    pass


def decompress_stream(src: bytes, dst_len: int):
    """逐块解压 Oodle Kraken 流 —— 生成器，每 256KB 一块。

    与 :func:`decompress` 输出逐字节一致，但一次只持有单块（≤256KB）内存，
    适合"边解压边写文件"的低内存流式解包。

    依赖 Korabli pkg 的 Kraken 流 restart=True（每块独立解码）。
    若遇到 restart=False 的块（跨块引用历史数据，无法独立解码），
    抛出 :class:`KrakenStreamError`，调用方可回退到 :func:`decompress`。
    """
    src_off = 0
    offset = 0
    remaining = dst_len
    hdr = None

    while remaining != 0:
        if src_off >= len(src):
            raise ValueError("Kraken: insufficient input")

        # 每 256KB 解析一次 Kraken 头
        if (offset & 0x3FFFF) == 0:
            hdr, src_off = _parse_kraken_header(src, src_off)
            if hdr is None:
                raise ValueError("Kraken: invalid header")
            if not hdr['restart']:
                raise KrakenStreamError(
                    "Kraken: 非 restart 块无法流式解压, 请回退到 decompress()"
                )

        is_kraken = hdr['decoder_type'] in (6, 10, 12)
        chunk_limit = 0x40000 if is_kraken else 0x4000
        dst_bytes = min(chunk_limit, remaining)
        block = bytearray(dst_bytes)

        # 未压缩块 (uncompressed=1): 直接拷贝 dst_bytes 字节
        if hdr['uncompressed']:
            if src_off + dst_bytes > len(src):
                raise ValueError("Kraken: not enough input for uncompressed")
            block[:] = src[src_off:src_off + dst_bytes]
            src_off += dst_bytes
            yield bytes(block)
            offset += dst_bytes
            remaining -= dst_bytes
            continue

        qh, src_off = _parse_quantum_header(src, src_off, hdr['use_checksums'])
        if qh is None:
            raise ValueError("Kraken: invalid quantum header")

        cs = qh['compressed_size']

        if cs == 0:
            wmd = qh['whole_match_distance']
            if wmd != 0:
                for i in range(dst_bytes):
                    block[i] = block[i - wmd]
            else:
                for i in range(dst_bytes):
                    block[i] = qh['checksum'] & 0xFF
            yield bytes(block)
            offset += dst_bytes
            remaining -= dst_bytes
            continue

        if cs > dst_bytes:
            raise ValueError("Kraken: compressed size > dst bytes")

        if src_off + cs > len(src):
            raise ValueError("Kraken: not enough input for quantum")

        if cs == dst_bytes:
            block[:] = src[src_off:src_off + dst_bytes]
            src_off += dst_bytes
        else:
            if hdr['decoder_type'] in (6, 10, 12):
                chunk_data = src[src_off:src_off + cs]
                n = _decode_quantum(block, 0, chunk_data, bytearray(), dst_bytes,
                                    hdr['decoder_type'], hdr['restart'])
                if n < 0:
                    raise ValueError("Kraken: quantum decode failed")
                src_off += n
            else:
                raise ValueError(f"Kraken: unsupported decoder type {hdr['decoder_type']}")

        yield bytes(block)
        offset += dst_bytes
        remaining -= dst_bytes
