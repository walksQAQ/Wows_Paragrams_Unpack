"""
dds_reader.py —— 读取 DDS 纹理头，识别压缩格式并取回各级 mipmap 数据。

支持格式（直接作为 GPU 压缩纹理上传，无需软件解压）：
  - DXT1 / DXT3 / DXT5（legacy fourCC，BC1/BC2/BC3）
  - DX10 头下的 BC4 / BC5 / BC7
  - 未压缩 BGRA / BGR（回退）

数据来源：`data_extractor` 提取的 .dds 文件（可能含 bc7prep，先经
pkg_reader.decode_bc7prep_file 解码为标准 BC7）。
"""

from __future__ import annotations

import struct

#: DXGI 格式（Windows）
DXGI_FORMAT_BC1_UNORM = 71
DXGI_FORMAT_BC1_UNORM_SRGB = 72
DXGI_FORMAT_BC2_UNORM = 74
DXGI_FORMAT_BC2_UNORM_SRGB = 75
DXGI_FORMAT_BC3_UNORM = 77
DXGI_FORMAT_BC3_UNORM_SRGB = 78
DXGI_FORMAT_BC4_UNORM = 80
DXGI_FORMAT_BC4_SNORM = 81
DXGI_FORMAT_BC5_UNORM = 83
DXGI_FORMAT_BC5_SNORM = 84
DXGI_FORMAT_BC7_UNORM = 98
DXGI_FORMAT_BC7_UNORM_SRGB = 99
DXGI_FORMAT_B8G8R8A8_UNORM = 87
DXGI_FORMAT_B8G8R8X8_UNORM = 88
DXGI_FORMAT_R8G8B8A8_UNORM = 28
DXGI_FORMAT_R8G8B8A8_UNORM_SRGB = 29

_FOURCC = {
    b"DXT1": (1, 8, "dxt1"),
    b"DXT3": (2, 16, "dxt3"),
    b"DXT5": (3, 16, "dxt5"),
    b"BC4U": (4, 8, "bc4"),
    b"BC4S": (5, 8, "bc4"),
    b"ATI1": (4, 8, "bc4"),
    b"BC5U": (6, 16, "bc5"),
    b"BC5S": (7, 16, "bc5"),
    b"ATI2": (6, 16, "bc5"),
    b"BC7 ": (8, 16, "bc7"),
}

_DXGI_TO_BC = {
    DXGI_FORMAT_BC1_UNORM: (1, 8),
    DXGI_FORMAT_BC1_UNORM_SRGB: (1, 8),
    DXGI_FORMAT_BC2_UNORM: (2, 16),
    DXGI_FORMAT_BC2_UNORM_SRGB: (2, 16),
    DXGI_FORMAT_BC3_UNORM: (3, 16),
    DXGI_FORMAT_BC3_UNORM_SRGB: (3, 16),
    DXGI_FORMAT_BC4_UNORM: (4, 8),
    DXGI_FORMAT_BC4_SNORM: (4, 8),
    DXGI_FORMAT_BC5_UNORM: (6, 16),
    DXGI_FORMAT_BC5_SNORM: (6, 16),
    DXGI_FORMAT_BC7_UNORM: (8, 16),
    DXGI_FORMAT_BC7_UNORM_SRGB: (8, 16),
}

_DXGI_TO_RGBA = {
    DXGI_FORMAT_B8G8R8A8_UNORM: 4,
    DXGI_FORMAT_B8G8R8X8_UNORM: 4,
    DXGI_FORMAT_R8G8B8A8_UNORM: 4,
    DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: 4,
}

#: 压缩格式 → GL 内部格式（用于 glCompressedTexImage2D）
GL_COMPRESSED_FORMAT = {
    1: 0x83F0,  # GL_COMPRESSED_RGB_S3TC_DXT1_EXT
    2: 0x83F2,  # GL_COMPRESSED_RGBA_S3TC_DXT3_EXT
    3: 0x83F3,  # GL_COMPRESSED_RGBA_S3TC_DXT5_EXT
    4: 0x8DBB,  # GL_COMPRESSED_RED_RGTC1（BC4 单通道；⚠️ 原误用 0x83F5=DXT5 导致 matid 上传失败）
    6: 0x8DBC,  # GL_COMPRESSED_RG_RGTC2（BC5 双通道；⚠️ 原误用 0x83F7）
    8: 0x8E8C,  # GL_COMPRESSED_RGBA_BPTC_UNORM_ARB
}

#: 压缩格式 → GL sRGB 内部格式（硬件逐 texel sRGB→线性解码；BC4/BC5 无 sRGB 变体）
#: 对应 wows-toolkit 的 Rgba8UnormSrgb 思路：贴图在采样时即被精确解码到线性空间。
GL_SRGB_COMPRESSED_FORMAT = {
    1: 0x8C4D,  # GL_COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT
    2: 0x8C4E,  # GL_COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT
    3: 0x8C4F,  # GL_COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT
    8: 0x8E8D,  # GL_COMPRESSED_SRGB_ALPHA_BPTC_UNORM_EXT
}

#: 未压缩 → GL sRGB 内部格式（0x8C43, GL_SRGB8_ALPHA8）
GL_SRGB_RGBA8 = 0x8C43


class DdsTexture:
    def __init__(self, width: int, height: int, bc_kind: int, mips: list[bytes],
                 internal_format: int, rgba_bpp: int = 0, internal_format_srgb: int = 0,
                 array_size: int = 1, layers: list[list[bytes]] | None = None):
        self.width = width
        self.height = height
        #: 1=DXT1 2=DXT3 3=DXT5 4=BC4 6=BC5 8=BC7；0=未压缩
        self.bc_kind = bc_kind
        self.mips = mips
        self.internal_format = internal_format
        #: sRGB 变体内部格式（硬件解码用）；BC4/BC5 无变体时等于 internal_format
        self.internal_format_srgb = internal_format_srgb or internal_format
        #: 未压缩时每像素字节数
        self.rgba_bpp = rgba_bpp
        #: 2DArray/3D 层数（DX10 arraySize；1=普通 2D）
        self.array_size = array_size
        #: 各层的 mip 数据（array_size>1 时用；每层 list[bytes]）
        self.layers = layers if layers is not None else None


def parse_dds(data: bytes) -> DdsTexture:
    """解析 DDS 字节流，返回各级 mipmap 数据。"""
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ValueError("不是有效的 DDS 文件")

    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    mip_count = struct.unpack_from("<I", data, 28)[0]
    if width == 0 or height == 0:
        raise ValueError("DDS 尺寸无效")

    flags = struct.unpack_from("<I", data, 8)[0]
    fourcc = data[84:88]
    has_dx10 = fourcc == b"DX10"

    bc_kind = 0
    rgba_bpp = 0
    array_size = 1
    if has_dx10:
        dxgi = struct.unpack_from("<I", data, 128)[0]
        data_off = 148
        # DX10 头：dxgiFormat(128) resourceDimension(132) miscFlag(136) arraySize(140) miscFlags2(144)
        array_size = struct.unpack_from("<I", data, 140)[0] or 1
        if dxgi in _DXGI_TO_BC:
            bc_kind, _bs = _DXGI_TO_BC[dxgi]
        elif dxgi in _DXGI_TO_RGBA:
            rgba_bpp = _DXGI_TO_RGBA[dxgi]
        else:
            raise ValueError(f"不支持的 DXGI 格式: {dxgi}")
    elif fourcc in _FOURCC:
        bc_kind, _bs = _FOURCC[fourcc][0], _FOURCC[fourcc][1]
        data_off = 128
    else:
        # 未压缩：flags bit 0x4 (DDSD_PITCH) 时 pitch 含每行字节数
        rgba_bpp = 4
        data_off = 128

    mips: list[bytes] = []
    #: 每 mip level 的 array 层连续数据（array_size>1 时用；顺序 = 该 level 全部层）
    layers: list[bytes] | None = None
    if array_size > 1:
        layers = []
    mw, mh = width, height
    n_mips = max(mip_count, 1)
    block_bytes = 16 if bc_kind in (2, 3, 6, 8) else 8 if bc_kind else None
    for i in range(n_mips):
        mw = max(width >> i, 1)
        mh = max(height >> i, 1)
        if block_bytes is not None:
            per = ((mw + 3) // 4) * ((mh + 3) // 4) * block_bytes
        else:
            per = mw * mh * rgba_bpp
        if array_size > 1:
            size = per * array_size
            chunk = data[data_off:data_off + size]
            if len(chunk) < size:
                break
            layers.append(chunk)          # 该 level 的全部层连续
            data_off += size
        else:
            chunk = data[data_off:data_off + per]
            if len(chunk) < per:
                break
            mips.append(chunk)
            data_off += per

    internal = GL_COMPRESSED_FORMAT.get(bc_kind, 0) if bc_kind else 0
    internal_srgb = GL_SRGB_COMPRESSED_FORMAT.get(bc_kind, internal) if bc_kind else 0
    return DdsTexture(width, height, bc_kind, mips, internal, rgba_bpp, internal_srgb,
                      array_size=array_size, layers=layers)
