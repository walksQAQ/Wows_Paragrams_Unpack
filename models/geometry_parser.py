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
import meshoptimizer

from utils.threading_utils import TaskCancelled


def _check_cancel(cancel_event) -> None:
    """协作式取消检查点：取消已请求则抛出 TaskCancelled。

    供 parse_geometry 在缓冲区/图元/装甲三角形批次边界调用，使后台任务
    在关闭 3D 查看器后能尽快停止解析，而不是跑完整个文件。
    """
    if cancel_event is not None and cancel_event.is_set():
        raise TaskCancelled

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
    #: 第二套 UV（格式含 uv2 时），(N,2) float32
    uv2: np.ndarray | None = None
    #: 切线/副切线（格式含 tb 时），(N,3) float32（packed 4B 解出）
    tangents: np.ndarray | None = None
    binormals: np.ndarray | None = None
    #: 单独的 ``t`` 属性原始 4 字节（语义未知，原样保留），(N,4) uint8
    t4: np.ndarray | None = None
    #: ``r`` 属性原始 4 字节（不做语义解释），(N,4) uint8
    extra: np.ndarray | None = None
    mapping_id: int = 0            # vertices_mapping[i].mapping_id（连接渲染集用）
    #: 源顶点缓冲带骨骼语义（格式含 iiiww / i，即蒙皮网格）。
    #: ⚠️ 不能用 VertexBuffer.is_skinned——Korabli 文件里该标志恒为 0，
    #: 只能按顶点格式串判定（见 _build_primitives）。
    is_skinned: bool = False
    #: 蒙皮数据（仅 iiiww 8B 骨骼属性时非 None）：
    #: bone_indices (N,4) uint8 顶点组索引（= 调色板 slot × 3）：前 3 列来自文件，
    #: 第 4 列恒 0；bone_weights (N,4) float32：w0/w1 来自 2×u8/255，
    #: w2 = 1-w0-w1（第三个顶点组的隐含权重），第 4 列恒 0。
    #: 由 geometry_service._apply_skinning 按渲染集调色板施加 bind pose 混合。
    bone_indices: np.ndarray | None = None
    bone_weights: np.ndarray | None = None
    #: 蒙皮调色板（渲染集 nodes 骨骼名）与 bind 世界矩阵（游戏空间）。
    #: 由 geometry_service._apply_skinning 应用成功后填充；供 GLB 导出 skin 用。
    skin_bones: list = field(default_factory=list)
    skin_bind: list = field(default_factory=list)
    #: 该 primitive 在 .visual 里的形状名（`Bow_wireShape`，已去 `.vertices`）
    #: 与绑定节点名（`Bow_wire`）。由 geometry_service 反查字符串表后写入，
    #: GLB 导出按它命名网格/空物体（对齐 BigWorld 插件的导入样式）。
    shape_name: str = ""
    node_name: str = ""


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

    语义: xyz=POSITION(12B) n=NORMAL(4B) uv/uv2=TEXCOORD(4B) t=EXTRA(4B)
          tb=TANGENT+BINORMAL(8B) iiiww=BONE(8B) i=BONE4B r=EXTRA(4B) pc/oi=标记(0B)

    ⚠️ 末尾的 ``_encd``（ENCD 压缩标记，如 ``xyznuvtbipc_encd``）只是数据块
    压缩方式的标记，不参与布局；必须先剥掉，否则后缀里的 ``n``/``d`` 会被
    当成 normal / 其他属性，导致法线偏移错位。
    """
    code = format_name.rsplit("/", 1)[-1]
    if code.lower().endswith("_encd"):
        code = code[:-5]
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
            # uv2/uv3：额外的贴图坐标套数（各 4B，2×f16）
            if i < n and code[i] in "23456789":
                i += 1
                attrs.append((f"uv{uv_count}", offset, 4))
                offset += 4
                uv_count += 1
        elif ch == "t":
            i += 1
            if i < n and code[i] == "b":
                i += 1
                attrs.append(("tangent", offset, 4))
                offset += 4
                attrs.append(("binormal", offset, 4))
                offset += 4
            else:
                # 单独 t：计 4B 步长（实测不是 packed 切线，解出的向量长度不固定），
                # 作为未知属性原样保留（t4），不参与切线导出。
                attrs.append(("t4", offset, 4))
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

    兼容旧调用；需要全部属性（uv2/tangent/binormal/extra）时用
    :func:`unpack_vertex_attributes`。
    """
    attrs = unpack_vertex_attributes(raw, fmt)
    return attrs["positions"], attrs["normals"], attrs["uv"]


def unpack_vertex_attributes(raw: np.ndarray, fmt: str) -> dict:
    """把 (count, stride) uint8 顶点数据拆成**全部**顶点属性。

    返回 dict：

    - ``positions`` (N,3) float32
    - ``normals``   (N,3) float32（4B packed normal → 有符号字节 /127）
    - ``uv``        (N,2) float32 | None（2×f16 + 0.5 偏置）
    - ``uv2``       (N,2) float32 | None（第二套 UV，格式里的 ``uv2``）
    - ``tangent``   (N,3) float32 | None（``tb`` 的前 4B，packed）
    - ``binormal``  (N,3) float32 | None（``tb`` 的后 4B，packed）
    - ``extra``     (N,4) uint8 | None（``r`` 属性原始字节，不做语义解释）
    """
    count = raw.shape[0]
    attrs = {name: (off, size) for name, off, size in parse_vertex_format(fmt)}
    positions = np.zeros((count, 3), dtype=np.float32)
    normals = np.zeros((count, 3), dtype=np.float32)

    pos = attrs.get("position")
    if pos:
        off, size = pos
        positions = np.frombuffer(raw[:, off:off + size].tobytes(), dtype="<f4",
                                  count=count * 3).reshape(count, 3)

    def _packed3(name: str) -> np.ndarray:
        off, _ = attrs[name]
        nb = np.ascontiguousarray(raw[:, off:off + 4])
        return nb.view(np.int8).astype(np.float32)[:, :3] / 127.0

    if "normal" in attrs:
        normals = _packed3("normal")

    def _uv(name: str) -> np.ndarray:
        off, _ = attrs[name]
        ub = raw[:, off:off + 4].tobytes()
        return (np.frombuffer(ub, dtype="<f2").astype(np.float32) + 0.5).reshape(count, 2)

    uv = _uv("uv") if "uv" in attrs else None
    uv2 = _uv("uv1") if "uv1" in attrs else None
    tangent = _packed3("tangent") if "tangent" in attrs else None
    binormal = _packed3("binormal") if "binormal" in attrs else None
    t4 = None
    if "t4" in attrs:
        off, size = attrs["t4"]
        t4 = np.ascontiguousarray(raw[:, off:off + size]).copy()
    extra = None
    if "extra" in attrs:
        off, size = attrs["extra"]
        extra = np.ascontiguousarray(raw[:, off:off + size]).copy()

    return {
        "positions": positions,
        "normals": normals,
        "uv": uv,
        "uv2": uv2,
        "tangent": tangent,
        "binormal": binormal,
        "t4": t4,
        "extra": extra,
    }


# ────────────────────────────────────────────────────────────────────────────
# ENCD 解码
# ────────────────────────────────────────────────────────────────────────────

def _decode_vertex_encd(payload: bytes, count: int, stride: int) -> np.ndarray:
    # 注意：该 wheel 的 dtype=uint8 分支有缓冲区溢出 bug（只分配 vertex_count 字节），
    # 必须用默认 float32 模式（内部正确分配 vertex_count*stride 字节），再按位还原为 uint8。
    out = meshoptimizer.decode_vertex_buffer(count, stride, payload)
    return np.ascontiguousarray(out).view(np.uint8).reshape(-1)


def _decode_index_encd(payload: bytes, count: int, index_size: int) -> np.ndarray:
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


def _read_armor_models(data: bytes, ptr: int, count: int,
                       cancel_event=None) -> list[ArmorModel]:
    """装甲模型：数据范围 = struct_base+0x20 → resolve_relptr(struct_base, data_relptr) + size_in_bytes。"""
    out = []
    for i in range(count):
        _check_cancel(cancel_event)
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
        out.append(ArmorModel(name, _parse_armor_triangles(armor_data, cancel_event=cancel_event)))
    return out


def _parse_armor_triangles(armor_data: bytes, cancel_event=None) -> list[ArmorTriangle]:
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
        if cancel_event is not None and (pos & 0x7FF) == 0:
            _check_cancel(cancel_event)
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

def parse_geometry(data: bytes, file_path: str = "",
                   cancel_event=None) -> ParsedGeometry:
    """解析一个 `.geometry` 文件字节流。

    cancel_event: 协作式取消事件；在缓冲区/图元/装甲三角形批次边界检查，
    取消时抛 TaskCancelled（关闭查看器后用于尽快停止解析）。
    """
    _check_cancel(cancel_event)
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
        _check_cancel(cancel_event)
        vb = _read_vertex_buffer(data, 0, mv_ptr + i * VERT_PROTO_SIZE)
        if vb is not None:
            result.vertex_buffers.append(vb)

    for i in range(merged_i_count):
        _check_cancel(cancel_event)
        ib = _read_index_buffer(data, 0, mi_ptr + i * INDEX_PROTO_SIZE)
        if ib is not None:
            result.index_buffers.append(ib)

    if coll_count:
        result.collision_models = _read_collision_models(data, coll_ptr, coll_count)
    if armor_count:
        result.armor_models = _read_armor_models(
            data, armor_ptr, armor_count, cancel_event=cancel_event)

    _build_primitives(result, cancel_event=cancel_event)
    _check_cancel(cancel_event)
    return result


def _build_primitives(geom: ParsedGeometry, cancel_event=None):
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
        _check_cancel(cancel_event)
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
        va = unpack_vertex_attributes(vraw, vb.format_name)
        positions, normals, uvs = va["positions"], va["normals"], va["uv"]
        # 蒙皮判定 + 数据：按顶点格式串是否含骨骼语义（iiiww / i）。
        # ⚠️ VertexBuffer.is_skinned 在 Korabli 文件里恒为 0，不可用。
        # ``iiiww`` 8B 实测布局（跨 138 个缓冲 / 395k 顶点统计）：
        #   b0..b2 = 3 个顶点组索引（u8，全部为 3 的倍数 = 调色板 slot × 3）
        #   b3,b4  = 0（对齐填充）
        #   b5,b6  = 2 个权重（u8/255；b5+b6=255 占 99.2%，即其余骨骼权重为 0）
        #   b7     = 0（对齐填充）
        # 配对：i0↔w0(b5)、i1↔w1(b6)，第三个顶点组的权重 = 1-w0-w1（通常为 0）。
        # 索引是**渲染集调色板 slot × 3**：slot 指向该 renderSet 的节点名数组
        # （assets.bin：+0x0D count / +0x28 u32 名ID 数组）**按原始顺序**的第 slot 项
        # —— 与 BigWorld 插件 import_bw_primitives.py 的 `iiiww[0]//3` 一致。
        # ⚠️ 调色板顺序不得重排（排序后权重会绑到别的骨骼上）。
        # 实测分布：w1 恒非零（主顶点组=i1），w0 仅 1.6% 非零（双骨骼混合），
        # 1-w0-w1 仅 0.75% 非零（三骨骼混合）—— 与「最多 3 个顶点组」一致。
        bone_attr = next((a for a in parse_vertex_format(vb.format_name)
                          if a[0] == 'bone'), None)
        is_skinned = bone_attr is not None
        bone_indices = None
        bone_weights = None
        if is_skinned and bone_attr[2] == 8 and v_count > 0:
            boff = bone_attr[1]
            chunk = np.ascontiguousarray(vraw[:, boff:boff + 8])
            idx3 = chunk[:, 0:3]
            w01 = chunk[:, 5:7].astype(np.float32) / 255.0
            w2 = np.clip(1.0 - w01[:, 0] - w01[:, 1], 0.0, 1.0)
            bone_indices = np.zeros((chunk.shape[0], 4), dtype=np.uint8)
            bone_indices[:, :3] = idx3
            bone_weights = np.zeros((chunk.shape[0], 4), dtype=np.float32)
            bone_weights[:, 0] = w01[:, 0]
            bone_weights[:, 1] = w01[:, 1]
            bone_weights[:, 2] = w2

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
            uv2=va["uv2"],
            tangents=va["tangent"],
            binormals=va["binormal"],
            t4=va["t4"],
            extra=va["extra"],
            indices=indices,
            mapping_id=vm.mapping_id,
            is_skinned=is_skinned,
            bone_indices=bone_indices,
            bone_weights=bone_weights,
        ))
