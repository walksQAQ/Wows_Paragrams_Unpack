"""
geometry_parser.py —— `.geometry` 文件格式解析器。

格式规范来源（已在 _archive/scripts/probe_geometry*.py 对 Korabli 真实文件实证）：
  - landaire/wows-toolkit/docs/MODELS.md
  - wowsunpack/src/models/geometry.rs

支持：
  - MergedGeometryPrototype 72 字节头 + relptr 指针解析
  - MappingEntry / PackedString / VerticesPrototype / IndicesPrototype
  - ENCD 压缩顶点/索引解码（meshoptimizer，优先，失败回退提示）
  - 顶点格式字符串解析（set3/xyznuvtpc 等）→ 位置/法线/UV 解包（numpy 向量化）
  - 碰撞模型（原始 blob）
  - 装甲模型（BVH 16 字节条目流 → 三角形 + material_id/layer_index）

内存约定：解码后的顶点/索引用 numpy 数组承载；调用方在合并完大文件后
应及时释放原始 bytes（遵守 2GB 内存红线）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

#: ENCD 魔数（"ENCD" little-endian）
ENCD_MAGIC = 0x44434E45

MAPPING_SIZE = 0x10
VERT_PROTO_SIZE = 0x20
INDEX_PROTO_SIZE = 0x10
MODEL_PROTO_SIZE = 0x20
HEADER_SIZE = 0x48
ARMOR_ENTRY_SIZE = 16


class GeometryError(Exception):
    """`.geometry` 解析错误"""


# ────────────────────────────────────────────────────────────────────────────
# 数据结构
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class MappingEntry:
    mapping_id: int
    merged_buffer_index: int
    packed_texel_density: int
    items_offset: int
    items_count: int


@dataclass
class VertexBuffer:
    """一个合并顶点缓冲（已 ENCD 解码，未拆分属性）。"""
    format_name: str
    stride: int
    size_in_bytes: int
    is_skinned: bool
    is_bumped: bool
    #: 形状 (count, stride) 的 uint8 数组
    data: np.ndarray
    count: int


@dataclass
class IndexBuffer:
    """一个合并索引缓冲（已 ENCD 解码）。"""
    index_size: int
    size_in_bytes: int
    #: uint32 数组
    data: np.ndarray


@dataclass
class MeshPrimitive:
    """一个可渲染网格（由 verticesMapping[i] 与 indicesMapping[i] 配对）。"""
    name: str
    positions: np.ndarray          # (N,3) float32
    normals: np.ndarray            # (N,3) float32
    uvs: np.ndarray | None = None  # (N,2) float32
    indices: np.ndarray | None = None  # (M,) uint32
    mapping_id: int = 0            # vertices_mapping[i].mapping_id（连接渲染集用）
    #: 源顶点缓冲带骨骼语义（格式含 iiiww / i，即蒙皮网格）。
    #: ⚠️ 不能用 VertexBuffer.is_skinned——Korabli 文件里该标志恒为 0，
    #: 只能按顶点格式串判定（见 _build_primitives）。
    is_skinned: bool = False
    #: 蒙皮数据（仅 iiiww 8B 骨骼属性时非 None）：
    #: bone_indices (N,4) uint8 原始索引（Korabli 实测 = 调色板 slot × 3）；
    #: bone_weights (N,4) float32（4×u8/255，逐顶点和=1）。
    #: 由 geometry_service._apply_skinning 按渲染集调色板施加 bind pose 混合。
    bone_indices: np.ndarray | None = None
    bone_weights: np.ndarray | None = None


@dataclass
class CollisionModel:
    name: str
    size_in_bytes: int
    data: bytes  # 原始数据（可能为三角形网格 / 命中区域 AABB）


@dataclass
class ArmorTriangle:
    vertices: np.ndarray  # (3,3) float32
    normals: np.ndarray   # (3,3) float32
    material_id: int
    layer_index: int


@dataclass
class ArmorModel:
    name: str
    triangles: list[ArmorTriangle] = field(default_factory=list)


@dataclass
class ParsedGeometry:
    file_path: str = ""
    vertices_mapping: list[MappingEntry] = field(default_factory=list)
    indices_mapping: list[MappingEntry] = field(default_factory=list)
    vertex_buffers: list[VertexBuffer] = field(default_factory=list)
    index_buffers: list[IndexBuffer] = field(default_factory=list)
    primitives: list[MeshPrimitive] = field(default_factory=list)
    collision_models: list[CollisionModel] = field(default_factory=list)
    armor_models: list[ArmorModel] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────────
# 顶点格式解析
# ────────────────────────────────────────────────────────────────────────────

def parse_vertex_format(format_name: str) -> list[tuple[str, int, int]]:
    """解析格式字符串（如 set3/xyznuvtpc）→ [(semantic, offset, size), ...]。

    语义: xyz=POSITION(12B) n=NORMAL(4B) uv/uv2=TEXCOORD(4B) tb=TANGENT+BINORMAL(8B)
          iiiww=BONE(8B) i=BONE4B r=EXTRA(4B) pc/oi=标记(0B)
    """
    code = format_name.rsplit("/", 1)[-1]
    attrs: list[tuple[str, int, int]] = []
    offset = 0
    uv_count = 0
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch == "x":
            attrs.append(("position", offset, 12))
            offset += 12
            i += 1
            while i < n and code[i] in "yz":
                i += 1
        elif ch == "n":
            attrs.append(("normal", offset, 4))
            offset += 4
            i += 1
        elif ch == "u":
            i += 1
            if i < n and code[i] == "v":
                i += 1
            name = f"uv{uv_count}" if uv_count > 0 else "uv"
            uv_count += 1
            attrs.append((name, offset, 4))
            offset += 4
        elif ch == "t":
            i += 1
            if i < n and code[i] == "b":
                i += 1
                attrs.append(("tangent", offset, 4))
                offset += 4
                attrs.append(("binormal", offset, 4))
                offset += 4
        elif ch == "i":
            # iiiww → 8B 骨骼；单独 i → 4B 实例
            j = i
            while j < n and code[j] == "i":
                j += 1
            while j < n and code[j] == "w":
                j += 1
            if j - i >= 3:
                attrs.append(("bone", offset, 8))
                offset += 8
            else:
                attrs.append(("bone", offset, 4))
                offset += 4
            i = j
        elif ch == "r":
            attrs.append(("extra", offset, 4))
            offset += 4
            i += 1
        elif ch == "p":
            i += 1
            if i < n and code[i] == "c":
                i += 1
        elif ch == "o":
            i += 1
            if i < n and code[i] == "i":
                i += 1
        elif ch == "w":
            i += 1
        else:
            i += 1
    return attrs


def unpack_vertices(raw: np.ndarray, fmt: str) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """把 (count, stride) uint8 顶点数据拆成 (positions, normals, uvs)。

    - positions: (N,3) float32
    - normals:   (N,3) float32（4 字节 packed normal → 有符号字节 /127）
    - uvs:       (N,2) float32 或 None（2×f16 + 0.5 偏置）
    """
    count = raw.shape[0]
    attrs = {name: (off, size) for name, off, size in parse_vertex_format(fmt)}
    pos = attrs.get("position")
    nrm = attrs.get("normal")
    uv = attrs.get("uv")

    positions = np.zeros((count, 3), dtype=np.float32)
    normals = np.zeros((count, 3), dtype=np.float32)
    uvs: np.ndarray | None = None

    if pos:
        off, size = pos
        positions = np.frombuffer(raw[:, off:off + size].tobytes(), dtype="<f4", count=count * 3).reshape(count, 3)

    if nrm:
        off, _ = nrm
        nb = raw[:, off:off + 4]
        # 有符号字节 → [-1, 1]（用 view 按位重解释，避免 astype 溢出告警）
        sb = nb.view(np.int8).astype(np.float32) / 127.0
        normals = sb[:, :3]

    if uv:
        off, _ = uv
        ub = raw[:, off:off + 4].tobytes()
        # 2×f16 + 0.5 偏置
        uvs = (np.frombuffer(ub, dtype="<f2").astype(np.float32) + 0.5).reshape(count, 2)

    return positions, normals, uvs


# ────────────────────────────────────────────────────────────────────────────
# ENCD 解码
# ────────────────────────────────────────────────────────────────────────────

def _decode_vertex_encd(payload: bytes, count: int, stride: int) -> np.ndarray:
    import meshoptimizer
    # 注意：该 wheel 的 dtype=uint8 分支有缓冲区溢出 bug（只分配 vertex_count 字节），
    # 必须用默认 float32 模式（内部正确分配 vertex_count*stride 字节），再按位还原为 uint8。
    out = meshoptimizer.decode_vertex_buffer(count, stride, payload)
    return np.ascontiguousarray(out).view(np.uint8).reshape(-1)


def _decode_index_encd(payload: bytes, count: int, index_size: int) -> np.ndarray:
    import meshoptimizer
    # wheel 的 decode_index_buffer 始终返回 uint32 数组（分配 count*4 字节）。
    # 对 index_size=2，C 层把 u16 索引紧凑写入前 count*2 字节，需按 index_size 重新解释。
    out = np.ascontiguousarray(meshoptimizer.decode_index_buffer(count, index_size, payload))
    raw = out.view(np.uint8)
    if index_size == 2:
        return raw[:count * 2].view("<u2").astype(np.uint32)
    return raw[:count * 4].view("<u4").astype(np.uint32)


# ────────────────────────────────────────────────────────────────────────────
# 底层读取
# ────────────────────────────────────────────────────────────────────────────

def _resolve_relptr(base: int, relptr: int) -> int:
    return base + relptr


def _read_packed_string(data: bytes, off: int) -> str:
    if off + 0x10 > len(data):
        return ""
    char_count = struct.unpack_from("<I", data, off)[0]
    text_rel = struct.unpack_from("<q", data, off + 0x08)[0]
    text_abs = off + text_rel
    if not (0 <= text_abs < len(data)) or not (0 < char_count <= 512):
        return ""
    raw = data[text_abs:text_abs + char_count]
    return raw.split(b"\x00")[0].decode("utf-8", "replace")


def _read_mapping_array(data: bytes, ptr: int, count: int) -> list[MappingEntry]:
    out = []
    for i in range(count):
        off = ptr + i * MAPPING_SIZE
        if off + MAPPING_SIZE > len(data):
            break
        mid, buf_idx, td, item_off, item_count = struct.unpack_from("<IHHII", data, off)
        out.append(MappingEntry(mid, buf_idx, td, item_off, item_count))
    return out


def _read_vertex_buffer(data: bytes, struct_base: int, proto: int) -> VertexBuffer | None:
    if proto + VERT_PROTO_SIZE > len(data):
        return None
    data_relptr = struct.unpack_from("<q", data, proto)[0]
    format_name = _read_packed_string(data, proto + 0x08)
    size_in_bytes, stride = struct.unpack_from("<IH", data, proto + 0x18)
    is_skinned, is_bumped = data[proto + 0x1E], data[proto + 0x1F]
    data_abs = _resolve_relptr(proto, data_relptr)
    if data_abs + size_in_bytes > len(data) or stride <= 0:
        return None

    blob = data[data_abs:data_abs + size_in_bytes]
    count = size_in_bytes // stride
    if blob[:4] == b"ENCD":
        encd_count = struct.unpack_from("<I", blob, 4)[0]
        payload = blob[8:]
        try:
            raw = _decode_vertex_encd(payload, encd_count, stride)
        except Exception as exc:  # noqa: BLE001
            raise GeometryError(f"ENCD 顶点解码失败 {format_name} stride={stride}: {exc}") from exc
        if raw.size < encd_count * stride:
            raw = np.resize(raw, encd_count * stride)
        arr = raw[:encd_count * stride].reshape(encd_count, stride)
    else:
        arr = np.frombuffer(blob, dtype=np.uint8, count=count * stride).reshape(count, stride)

    return VertexBuffer(format_name, stride, size_in_bytes, bool(is_skinned), bool(is_bumped), arr, arr.shape[0])


def _read_index_buffer(data: bytes, struct_base: int, proto: int) -> IndexBuffer | None:
    if proto + INDEX_PROTO_SIZE > len(data):
        return None
    data_relptr = struct.unpack_from("<q", data, proto)[0]
    size_in_bytes, _reserved, index_size = struct.unpack_from("<IHH", data, proto + 0x08)
    data_abs = _resolve_relptr(proto, data_relptr)
    if data_abs + size_in_bytes > len(data) or index_size not in (2, 4):
        return None
    blob = data[data_abs:data_abs + size_in_bytes]
    if blob[:4] == b"ENCD":
        encd_count = struct.unpack_from("<I", blob, 4)[0]
        payload = blob[8:]
        try:
            raw = _decode_index_encd(payload, encd_count, index_size)
        except Exception as exc:  # noqa: BLE001
            raise GeometryError(f"ENCD 索引解码失败 indexSize={index_size}: {exc}") from exc
        arr = np.asarray(raw, dtype=np.uint32).reshape(-1)
    else:
        if index_size == 2:
            arr = np.frombuffer(blob, dtype="<u2").astype(np.uint32)
        else:
            arr = np.frombuffer(blob, dtype="<u4").astype(np.uint32)
    return IndexBuffer(index_size, size_in_bytes, arr)


def _read_collision_models(data: bytes, ptr: int, count: int) -> list[CollisionModel]:
    out = []
    for i in range(count):
        proto = ptr + i * MODEL_PROTO_SIZE
        if proto + MODEL_PROTO_SIZE > len(data):
            break
        data_relptr = struct.unpack_from("<q", data, proto)[0]
        name = _read_packed_string(data, proto + 0x08)
        size_in_bytes = struct.unpack_from("<I", data, proto + 0x18)[0]
        data_abs = _resolve_relptr(proto, data_relptr)
        if data_abs + size_in_bytes <= len(data):
            out.append(CollisionModel(name, size_in_bytes, data[data_abs:data_abs + size_in_bytes]))
        else:
            out.append(CollisionModel(name, size_in_bytes, b""))
    return out


def _read_armor_models(data: bytes, ptr: int, count: int) -> list[ArmorModel]:
    """装甲模型：数据范围 = struct_base+0x20 → resolve_relptr(struct_base, data_relptr) + size_in_bytes。"""
    out = []
    for i in range(count):
        struct_base = ptr + i * MODEL_PROTO_SIZE
        if struct_base + MODEL_PROTO_SIZE > len(data):
            break
        data_relptr = struct.unpack_from("<q", data, struct_base)[0]
        name = _read_packed_string(data, struct_base + 0x08)
        size_in_bytes = struct.unpack_from("<I", data, struct_base + 0x18)[0]

        data_start = struct_base + MODEL_PROTO_SIZE
        data_end = _resolve_relptr(struct_base, data_relptr) + size_in_bytes
        data_end = min(data_end, len(data))
        if data_end <= data_start:
            out.append(ArmorModel(name))
            continue
        armor_data = data[data_start:data_end]
        out.append(ArmorModel(name, _parse_armor_triangles(armor_data)))
    return out


def _parse_armor_triangles(armor_data: bytes) -> list[ArmorTriangle]:
    """解析装甲 BVH 条目流（每条 16 字节）→ 三角形列表。

    布局：2 个全局头条目；随后 N 个 BVH 节点组 =
        2 个头条目（第 1 条 byte0=material_id, byte2=layer_index；
        第 2 条 bytes12..16=vertex_count）+ vertex_count 个顶点条目（每 3 个 = 1 三角形）。
    顶点条目：f32 x,y,z + u8[3] packed_normal（byte/127.5-1）+ u8 zero。
    """
    entry_count = len(armor_data) // ARMOR_ENTRY_SIZE
    if entry_count <= 2:
        return []

    tris: list[ArmorTriangle] = []
    pos = 2  # 跳过 2 个全局头条目
    while pos < entry_count:
        e0 = pos * ARMOR_ENTRY_SIZE
        material_id = armor_data[e0]
        layer_index = armor_data[e0 + 2]
        e1 = (pos + 1) * ARMOR_ENTRY_SIZE
        vertex_count = struct.unpack_from("<I", armor_data, e1 + 12)[0]
        pos += 2
        if vertex_count == 0:
            continue
        if pos + vertex_count > entry_count:
            break

        tri_count = vertex_count // 3
        for t in range(tri_count):
            verts = np.zeros((3, 3), dtype=np.float32)
            nrm = np.zeros((3, 3), dtype=np.float32)
            for v in range(3):
                off = (pos + t * 3 + v) * ARMOR_ENTRY_SIZE
                verts[v] = struct.unpack_from("<3f", armor_data, off)
                nx = armor_data[off + 12] / 127.5 - 1.0
                ny = armor_data[off + 13] / 127.5 - 1.0
                nz = armor_data[off + 14] / 127.5 - 1.0
                nrm[v] = (nx, ny, nz)
            tris.append(ArmorTriangle(verts, nrm, material_id, layer_index))
        pos += vertex_count

    return tris


# ────────────────────────────────────────────────────────────────────────────
# 顶层入口
# ────────────────────────────────────────────────────────────────────────────

def parse_geometry(data: bytes, file_path: str = "") -> ParsedGeometry:
    """解析一个 `.geometry` 文件字节流。"""
    if len(data) < HEADER_SIZE:
        raise GeometryError(f"文件过短: {len(data)} 字节 (< {HEADER_SIZE})")

    (
        merged_v_count, merged_i_count,
        v_map_count, i_map_count,
        coll_count, armor_count,
    ) = struct.unpack_from("<IIIIII", data, 0)
    (
        v_map_ptr, i_map_ptr, mv_ptr,
        mi_ptr, coll_ptr, armor_ptr,
    ) = struct.unpack_from("<qqqqqq", data, 0x18)

    result = ParsedGeometry(file_path=file_path)

    result.vertices_mapping = _read_mapping_array(data, v_map_ptr, v_map_count)
    result.indices_mapping = _read_mapping_array(data, i_map_ptr, i_map_count)

    for i in range(merged_v_count):
        vb = _read_vertex_buffer(data, 0, mv_ptr + i * VERT_PROTO_SIZE)
        if vb is not None:
            result.vertex_buffers.append(vb)

    for i in range(merged_i_count):
        ib = _read_index_buffer(data, 0, mi_ptr + i * INDEX_PROTO_SIZE)
        if ib is not None:
            result.index_buffers.append(ib)

    if coll_count:
        result.collision_models = _read_collision_models(data, coll_ptr, coll_count)
    if armor_count:
        result.armor_models = _read_armor_models(data, armor_ptr, armor_count)

    _build_primitives(result)
    return result


def _build_primitives(geom: ParsedGeometry):
    """把 verticesMapping 与 indicesMapping 配对成可渲染网格。

    ⚠️ BigWorld(.object) 配对：顶点 block 与索引 block 按 **unknown 字段（=td）相等**
    配对（参考 gmConverter3D BigWorldReader.object），**不能用数组下标**——block 顺序
    不一致时（如 JGA180 前两个 16422/16411 交换）按下标会错配 → 顶点/索引串位 → 面全乱。
    已用索引 block 不重复使用；找不到匹配时回退按下标（兼容旧文件）。
    """
    vmaps = geom.vertices_mapping
    imaps = geom.indices_mapping
    vbufs = geom.vertex_buffers
    ibufs = geom.index_buffers
    used_imaps: set = set()   # 已配对的索引 mapping 下标

    for i, vm in enumerate(vmaps):
        if vm.merged_buffer_index >= len(vbufs):
            continue
        vb = vbufs[vm.merged_buffer_index]
        v_start = vm.items_offset
        v_count = vm.items_count
        if v_start + v_count > vb.count:
            v_count = max(0, vb.count - v_start)
        if v_count <= 0:
            continue

        vraw = vb.data[v_start:v_start + v_count]
        positions, normals, uvs = unpack_vertices(vraw, vb.format_name)
        # 蒙皮判定 + 数据：按顶点格式串是否含骨骼语义（iiiww / i）。
        # ⚠️ VertexBuffer.is_skinned 在 Korabli 文件里恒为 0，不可用。
        # iiiww 8B 属性 = 4×u8 骨骼索引（3 索引+1 pad）+ 4×u8 权重(/255，和=1)
        # （PASA111 实测；wows-toolkit 同样只跳过该属性不做蒙皮）。
        bone_attr = next((a for a in parse_vertex_format(vb.format_name)
                          if a[0] == 'bone'), None)
        is_skinned = bone_attr is not None
        bone_indices = None
        bone_weights = None
        if is_skinned and bone_attr[2] == 8 and v_count > 0:
            boff = bone_attr[1]
            chunk = np.ascontiguousarray(vraw[:, boff:boff + 8])
            bone_indices = chunk[:, :4].copy()
            bone_weights = chunk[:, 4:8].astype(np.float32) / 255.0

        # 索引 mapping：优先按 unknown(td) 字段配对（BigWorld 权威方式）
        im = None
        for j, imj in enumerate(imaps):
            if j in used_imaps:
                continue
            if imj.packed_texel_density == vm.packed_texel_density:
                im = imj
                used_imaps.add(j)
                break
        if im is None and i < len(imaps):   # 兜底：按下标
            im = imaps[i]
        indices: np.ndarray | None = None
        if im is not None and im.merged_buffer_index < len(ibufs):
            ib = ibufs[im.merged_buffer_index]
            i_start = im.items_offset
            i_count = im.items_count
            if i_start + i_count <= ib.data.size:
                indices = ib.data[i_start:i_start + i_count]

        # 过滤含越界顶点的索引（部分 wire/损坏网格索引越界，直接渲染致错乱/扭曲；
        # 按整三角形丢弃，保留有效部分）
        if indices is not None and indices.size and positions is not None \
                and positions.shape[0] > 0:
            nv = positions.shape[0]
            bad = indices >= nv
            if bad.any():
                if indices.size % 3 == 0:
                    keep = ~bad.reshape(-1, 3).any(axis=1)
                    indices = indices[keep.repeat(3)]
                else:
                    indices = indices[~bad]

        # ⚠️ 长边三角形过滤已移除（2026-08-19）：它按 边长<=包围盒对角线*0.5 删除三角形，
        # 会误删「甲板主体大平面」这类跨度大的简单面（Yamato 甲板缺失根因）。
        # 如后续需清理 JGA180 TurretShape 类飞线，请用「细长三角形」判据而非绝对边长。

        if indices is None or indices.size == 0:
            # 无索引：非索引渲染（GL_POINTS 等）留空，交由调用方处理
            pass

        geom.primitives.append(MeshPrimitive(
            name=f"prim_{i}",
            positions=positions,
            normals=normals,
            uvs=uvs,
            indices=indices,
            mapping_id=vm.mapping_id,
            is_skinned=is_skinned,
            bone_indices=bone_indices,
            bone_weights=bone_weights,
        ))
