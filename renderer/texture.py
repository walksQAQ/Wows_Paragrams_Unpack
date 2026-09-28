"""renderer.texture —— DDS 字节 → :class:`renderer.types.TextureSpec`。

职责边界（架构文档 §6.1）：

- **DDS 容器/头解析与 layer-major → mip-major 重排**保留在 Python
  （复用 ``models/dds_reader.parse_dds`` 的既有定版修正）；
- DLL 只接收「已按 D3D 布局排好的压缩字节 + DXGI 格式」，不做 CPU 解码；
- BCn 块由 GPU 硬件解码（sRGB 变体格式负责颜色贴图的硬件线性化）。

> ⚠️ 数组纹理的 layer-major 修正是历史踩坑的成果（错层会表现为偏色/木纹），
> 迁移时不得在 C++ 侧重新解释这份数据。
"""

from __future__ import annotations

from models.dds_reader import parse_dds

from .types import (
    TEXF_NOMIP,
    TEXF_POINT,
    TEXF_REPEAT,
    TEXF_SRGB,
    TEXKIND_2D,
    TEXKIND_2D_ARRAY,
    TextureSpec,
)

# ---------------------------------------------------------------- DXGI 格式
DXGI_FORMAT_R8G8B8A8_UNORM = 28
DXGI_FORMAT_R8G8B8A8_UNORM_SRGB = 29
DXGI_FORMAT_B8G8R8A8_UNORM = 87
DXGI_FORMAT_B8G8R8X8_UNORM = 88
DXGI_FORMAT_B8G8R8A8_UNORM_SRGB = 91
DXGI_FORMAT_BC1_UNORM = 71
DXGI_FORMAT_BC1_UNORM_SRGB = 72
DXGI_FORMAT_BC2_UNORM = 74
DXGI_FORMAT_BC2_UNORM_SRGB = 75
DXGI_FORMAT_BC3_UNORM = 77
DXGI_FORMAT_BC3_UNORM_SRGB = 78
DXGI_FORMAT_BC4_UNORM = 80
DXGI_FORMAT_BC5_UNORM = 83
DXGI_FORMAT_BC7_UNORM = 98
DXGI_FORMAT_BC7_UNORM_SRGB = 99

#: bc_kind（dds_reader 约定）→ (线性格式, sRGB 格式)
_BC_TO_DXGI: dict[int, tuple[int, int]] = {
    1: (DXGI_FORMAT_BC1_UNORM, DXGI_FORMAT_BC1_UNORM_SRGB),
    2: (DXGI_FORMAT_BC2_UNORM, DXGI_FORMAT_BC2_UNORM_SRGB),
    3: (DXGI_FORMAT_BC3_UNORM, DXGI_FORMAT_BC3_UNORM_SRGB),
    4: (DXGI_FORMAT_BC4_UNORM, DXGI_FORMAT_BC4_UNORM),   # 无 sRGB 变体
    6: (DXGI_FORMAT_BC5_UNORM, DXGI_FORMAT_BC5_UNORM),
    8: (DXGI_FORMAT_BC7_UNORM, DXGI_FORMAT_BC7_UNORM_SRGB),
}


def build_texture_spec(
    key: str,
    dds_bytes: bytes,
    *,
    srgb: bool = True,
    repeat: bool = False,
    point: bool = False,
    nomip: bool = False,
) -> TextureSpec | None:
    """把 DDS 字节整理成上传描述；无法解析时返回 ``None``（调用方跳过该槽）。

    ``srgb`` 只对颜色贴图置真；法线 / MG / materialIdMap 等数据贴图必须为假，
    否则硬件 sRGB 解码会破坏数值（架构文档 §5.4 硬性约束）。
    """
    try:
        dds = parse_dds(dds_bytes)
    except Exception:  # noqa: BLE001 - 单个贴图失败不应中断场景构建
        return None

    if dds.bc_kind:
        pair = _BC_TO_DXGI.get(dds.bc_kind)
        if pair is None:
            return None
        fmt = pair[1] if srgb else pair[0]
        levels = dds.layers if dds.array_size > 1 else dds.mips
    else:
        if dds.rgba_bpp == 4:
            fmt = DXGI_FORMAT_B8G8R8A8_UNORM_SRGB if srgb else DXGI_FORMAT_B8G8R8A8_UNORM
        elif dds.rgba_bpp == 3:
            fmt = DXGI_FORMAT_B8G8R8X8_UNORM
        else:
            return None
        levels = list(dds.mips[:1])

    if not levels:
        return None

    blob = b"".join(levels)
    offsets: list[int] = []
    sizes: list[int] = []
    cursor = 0
    for level in levels:
        offsets.append(cursor)
        sizes.append(len(level))
        cursor += len(level)

    flags = 0
    if srgb:
        flags |= TEXF_SRGB
    if repeat:
        flags |= TEXF_REPEAT
    if point:
        flags |= TEXF_POINT
    if nomip:
        flags |= TEXF_NOMIP

    return TextureSpec(
        key=key,
        kind=TEXKIND_2D_ARRAY if dds.array_size > 1 else TEXKIND_2D,
        format=fmt,
        width=dds.width,
        height=dds.height,
        array_size=max(1, dds.array_size),
        mip_count=len(levels),
        flags=flags,
        data=blob,
        mip_offsets=offsets,
        mip_sizes=sizes,
    )


#: 各类贴图的采样/编码约定（与旧渲染器 ``_upload_texture`` 的调用点一一对应）
#: (srgb, repeat, point, nomip)
TEX_HINTS: dict[str, tuple[bool, bool, bool, bool]] = {
    "materialIdMap": (False, False, True, True),
    "albedoArray": (False, True, False, False),
    "normalArray": (False, True, False, False),
    "rgbNoiseMap": (False, True, False, False),
    "MGArray": (False, True, False, False),
    "normalMap": (False, False, False, False),
    "g_normalMap": (False, False, False, False),
    "metallicGlossMap": (False, False, False, False),
    "ambientOcclusionMap": (False, False, False, False),
    "artMap": (True, False, False, False),
    "diffuseMap": (True, False, False, False),
    "g_diffuseMap": (True, False, False, False),
    "g_albedoMap": (True, False, False, False),
    "g_mgMap": (False, False, False, False),
}
