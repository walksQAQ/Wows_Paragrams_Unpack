"""renderer.types —— 与后端无关的场景/纹理描述（Python ↔ C ABI 的中间层）。

设计要点（架构文档 §4.3）：

- 这里的数据结构**只描述**「要画什么」，不含任何 D3D11 概念；
- ``renderer.api`` 负责把它们翻译成 ctypes 结构；
- CPU 侧描述是权威副本：设备丢失后由调用方重新提交（见 §11.2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------- 枚举（与 C 头一致）

MESH_HULL = 0
MESH_MOUNT = 1
MESH_ARMOR = 2

#: mesh 标志（与 C 头一致）
MESHF_NONE = 0
MESHF_NO_DEPTH_WRITE = 1
MESHF_LINES = 4

FAM_SOLID = 0
FAM_INDEXED = 1
FAM_EMISSIVE = 2
FAM_UNLIT = 3
FAM_DECAL_NORMAL = 4

TEX_DIFFUSE = 0
TEX_NORMAL = 1
TEX_MG = 2
TEX_MATID = 3
TEX_TILES_A = 4
TEX_TILES_N = 5
TEX_TILES_MG = 6
TEX_ART = 7
TEX_NOISE = 8
TEX_ALPHA_N = 9
TEX_COUNT = 10

TEXKIND_2D = 0
TEXKIND_2D_ARRAY = 1

TEXF_SRGB = 1
TEXF_REPEAT = 2
TEXF_POINT = 4
TEXF_NOMIP = 8


# ---------------------------------------------------------------- 纹理


@dataclass
class TextureSpec:
    """已整理为 D3D 期望布局（mip-major）的纹理数据。"""

    key: str
    kind: int
    format: int          # DXGI_FORMAT
    width: int
    height: int
    array_size: int
    mip_count: int
    flags: int
    data: bytes
    mip_offsets: list[int] = field(default_factory=list)
    mip_sizes: list[int] = field(default_factory=list)


# ---------------------------------------------------------------- 网格


@dataclass
class MeshSpec:
    """一个待提交的网格（顶点/索引 + 材质描述）。"""

    key: str
    kind: int
    family: int
    vertices: np.ndarray          # (N, 12) float32：pos3 + normal3 + uv2 + color4
    indices: np.ndarray           # (M,) uint32
    flags: int = 0
    opacity: float = 1.0
    emissive_k: float = 1.0
    model_matrix: np.ndarray | None = None      # (4,4) float32 行主序（渲染空间）
    instance_matrices: np.ndarray | None = None  # (K,16) float32 行主序
    textures: dict[int, str] = field(default_factory=dict)   # 槽 → 纹理 key
    # INDEXED 逐材质数组（各 (196,4) float32）
    matid_count: int = 0
    arr_offset_scale: np.ndarray | None = None
    arr_rotation: np.ndarray | None = None
    arr_tile_idx: np.ndarray | None = None
    arr_tint: np.ndarray | None = None
    arr_remove: np.ndarray | None = None
