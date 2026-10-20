"""各 Prototype 类型 → 结构化 dict（可 JSON 序列化）的解码器。

对应 wows-toolkit `models/{material,visual,model}.rs`，加上 Korabli 独有的
SkeletonPrototype / TrailPrototype / VfxMaterialPrototype / MiscSettingsPrototype。

WG 服（get_wows_type() == 'Wargaming'）：
  - Material 用 WG 0x78 布局（decode_material 内部自适应）
  - Visual/Model 用 generic 兜底（WG 布局与 Korabli 不同，populate 用自写 WG 解析）

`data` 约定：从记录起始到 blob 末尾的切片（`get_prototype_data` 返回），
因此所有相对指针的基准 = 0（记录起始）。
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from . import binary as B
from .errors import ParseError
from .parser import PrototypeDatabase, PrototypeLocation
from .types import PrototypeType, get_wows_type, type_from_magic


# ── 工具 ──────────────────────────────────────────────────────────────────

def _resolve_path_id(db: PrototypeDatabase, self_id: int) -> str:
    """把 selfId（路径哈希）反查为资源路径。"""
    if self_id == 0:
        return ""
    index = db.build_self_id_index()
    idx = index.get(self_id)
    if idx is None:
        return f"0x{self_id:016X}"
    return db.reconstruct_path(idx, index)


def _f(v: float) -> float:
    return round(v, 6)


def read_material_header(data: bytes, wargaming: Optional[bool] = None) -> dict:
    """只读 MaterialPrototype 的头部字段（不解析属性，用于建 fx 索引）。

    比 :func:`decode_material` 快两个数量级（不读贴图/数组），
    但仍返回与解码结果同名的 `shader_id`（`0x%08X`）与 `material_hash`（`0x%016X`）。

    Args:
        data: 记录字节（从记录起始）。
        wargaming: 是否 WG 0x78 布局；None → 按当前线程服务器判定。
    """
    wg = get_wows_type() == "Wargaming" if wargaming is None else bool(wargaming)
    shader_off = 0x04 if wg else 0x08
    mat_hash_off = 0x68 if wg else 0x78
    if len(data) < mat_hash_off + 8:
        return {"shader_id": "", "material_hash": "", "collisionFlags": 0}
    shader_id = B.read_u32(data, shader_off)
    flags = B.read_u16(data, 0x02)
    material_hash = B.read_u64(data, mat_hash_off)
    return {
        "shader_id": f"0x{shader_id:08X}",
        "material_hash": f"0x{material_hash:016X}",
        "collisionFlags": flags,
    }


def _arr(iterable) -> List:
    return list(iterable)


_ASCII_RE = re.compile(rb"[\x20-\x7e]{3,}")


def _extract_ascii_strings(data: bytes, limit: int = 50) -> List[str]:
    """提取二进制区域中的内嵌可打印 ASCII 字符串（去重，限量）。"""
    out: List[str] = []
    seen = set()
    for m in _ASCII_RE.finditer(data):
        s = m.group().decode("ascii", "ignore")
        if s not in seen:
            seen.add(s)
            out.append(s)
            if len(out) >= limit:
                break
    return out


_PARTICLE_HINTS = ("particle", ".effect", ".trail", ".vfx", "vfx", "fx/")


def _is_particle_ref(s: str) -> bool:
    low = s.lower()
    return any(h in low for h in _PARTICLE_HINTS)


def _particle_refs(data: bytes, db: PrototypeDatabase, pos: int, max_len: int) -> List[str]:
    """扫描 OOL 区域中通过字符串表可反查的粒子相关引用路径。"""
    refs: List[str] = []
    end = min(pos + max_len, len(data))
    for off in range(pos, end - 4, 4):
        v = B.read_u32(data, off)
        s = db.strings.get_string_by_id(v)
        if s and _is_particle_ref(s) and s not in refs:
            refs.append(s)
    return refs


# ── MaterialPrototype ─────────────────────────────────────────────────────

_MATERIAL_TYPE_NAMES = {
    0: "bool", 1: "int32", 2: "float_a", 3: "float_b", 4: "texture",
    5: "vec2", 6: "vec3", 7: "vec4", 8: "matrix4x4",
}

#: 值数组元素字节数（type_idx 低 4 位 → 元素大小）；未列出的类型不是数组
MATERIAL_ELEM_SIZE = {1: 4, 2: 4, 3: 4, 5: 8, 6: 12, 7: 16, 8: 64}

#: MaterialPrototype 记录布局（按服务器）：item 记录步长 / names、types、type_ptrs 偏移 /
#: kind（materialKind u32，-1 = 未设置）偏移
_MATERIAL_LAYOUT = {
    False: {"item": 0x88, "names": 0x18, "types": 0x20, "tptr": 0x30,
            "kind": 0x80},  # Korabli
    True: {"item": 0x78, "names": 0x10, "types": 0x18, "tptr": 0x20,
           "kind": 0x74},   # Wargaming
}

#: ``collisionFlags`` 位定义（BigWorld `physics2/worldtri.hpp`，写入碰撞三角 flags 低字节）
COLLISION_FLAG_BITS = {
    0x01: "CAMERANOCOLLIDE",      # 相机可穿透（螺旋桨 / gizmo / 装饰薄片）
    0x02: "TRANSPARENT",          # 镂空/alphaTest 面：不算实体、不投影
    0x04: "BLENDED",              # 混合队列
    0x08: "TERRAIN",              # 地形
    0x10: "NOCOLLIDE",            # 角色不碰撞（相机仍碰撞）
    0x20: "DOUBLESIDED",          # 双面
    0x40: "WATER",                # 水面
    0x80: "PROJECTILENOCOLLIDE",  # 弹道不碰撞
}


def _material_ool_start(data: bytes, off: int, wargaming: bool) -> int:
    """记录 off 处的 OOL 区起点（最小非零指针）；无指针返回 0。"""
    lay = _MATERIAL_LAYOUT[wargaming]
    if off + lay["tptr"] + 9 * 8 + 8 > len(data):
        return 0
    cand = [B.read_u64(data, off + lay["names"]),
            B.read_u64(data, off + lay["types"])]
    cand += [B.read_u64(data, off + lay["tptr"] + t * 8) for t in range(9)]
    cand = [p for p in cand if 0 < p < len(data)]
    return min(cand) if cand else 0


def material_ool_end(data: bytes, wargaming: bool = False,
                     max_scan: int = 8) -> int | None:
    """当前材质记录（``data[0]`` = 记录起始）的 OOL 区结束偏移（记录相对）。

    OOL 区（属性名/类型索引/各类型值数组）在 blob 里按记录顺序**紧密排列**，
    因此本记录的结束 = 后面第一条带 OOL 的记录的起点。扫描不到（blob 末尾）
    返回 None（调用方退回间距推断）。
    """
    lay = _MATERIAL_LAYOUT[wargaming]
    item = lay["item"]
    for k in range(1, max_scan + 1):
        off = k * item
        start = _material_ool_start(data, off, wargaming)
        if start:
            return off + start
    return None


def material_array_lengths(data: bytes, property_count: int, type_idx: List[int],
                           type_ptrs: Dict[int, int], ool_end: int | None,
                           wargaming: bool = False) -> Dict[int, int]:
    """每个属性（按属性下标）的值数组元素数。

    同一类型的属性共享一段**连续**值数组：排序后相邻 pidx 间距即前一组长度。
    最后一组没有“下一组”可参照，旧实现沿用前一组间距——对「6 个 196 项 INDEXED
    数组 + 末尾单个 vec4（blendNoiseParams）」这类布局会多读 195 项，读进下一条
    材质的 OOL 数据，于是出现 1e28 / 1e36 这类荒谬数值。

    这里改用 OOL 边界：该类型值数组从 ``ptr + pidx*elem`` 一直延续到下一个 OOL
    块起点（各类型值数组按类型索引升序紧密排列，最后一块到 ``ool_end``）。
    ``ool_end`` 为 None（无法定位后继 OOL）时退回旧的间距推断。
    """
    by_type: Dict[int, List[Tuple[int, int]]] = {}
    for i in range(property_count):
        ti = type_idx[i] if i < len(type_idx) else 0
        by_type.setdefault(ti & 0xF, []).append((ti >> 4, i))

    # 所有 OOL 块起点（属性名数组 / 类型索引数组 / 各类型值数组），用于求块结束
    lay = _MATERIAL_LAYOUT[wargaming]
    starts = sorted({p for p in type_ptrs.values() if p})
    for off_key in (lay["names"], lay["types"]):
        try:
            p = B.read_u64(data, off_key)
        except Exception:  # noqa: BLE001
            p = 0
        if p:
            starts.append(p)
    starts = sorted(set(starts))

    def _chunk_end(start: int) -> int:
        for s in starts:
            if s > start:
                return s
        return ool_end if ool_end is not None else len(data)

    out: Dict[int, int] = {}
    for ptype, items in by_type.items():
        items.sort()
        n = len(items)
        elem = MATERIAL_ELEM_SIZE.get(ptype)
        ptr = type_ptrs.get(ptype) or 0
        for j, (pidx, i) in enumerate(items):
            if j + 1 < n:
                length = items[j + 1][0] - pidx
            elif elem and ptr and ool_end is not None:
                avail = _chunk_end(ptr) - (ptr + pidx * elem)
                length = avail // elem if avail > 0 else 1
            elif n > 1:
                length = items[-1][0] - items[-2][0]  # 兜底：沿用前一组间距
            else:
                length = 1
            out[i] = max(0, min(int(length), 4096))
    return out


def _read_typed_value(data: bytes, ptr: int, ptype: int, pidx: int):
    """读取某种属性类型第 pidx 个元素（ptr 为该类型值数组起始，相对记录）。"""
    if ptr <= 0 or ptr >= len(data):
        return None
    if ptype == 0:        # bool
        off = ptr + pidx * 1
        return bool(B.read_u8(data, off)) if off < len(data) else None
    if ptype == 1:        # int32
        off = ptr + pidx * 4
        return B.read_i32(data, off) if off + 4 <= len(data) else None
    if ptype in (2, 3):   # float
        off = ptr + pidx * 4
        return _f(B.read_f32(data, off)) if off + 4 <= len(data) else None
    if ptype == 4:        # texture（路径哈希 u64）
        off = ptr + pidx * 8
        return B.read_u64(data, off) if off + 8 <= len(data) else None
    if ptype == 5:        # vec2
        off = ptr + pidx * 8
        return _arr(B.parse_vec2(data, off)) if off + 8 <= len(data) else None
    if ptype == 6:        # vec3
        off = ptr + pidx * 12
        return _arr(B.parse_vec3(data, off)) if off + 12 <= len(data) else None
    if ptype == 7:        # vec4
        off = ptr + pidx * 16
        return _arr(B.parse_vec4(data, off)) if off + 16 <= len(data) else None
    if ptype == 8:        # matrix4x4
        off = ptr + pidx * 64
        return _arr(B.parse_matrix4x4(data, off)) if off + 64 <= len(data) else None
    return None


def _read_typed_array(data: bytes, ptr: int, ptype: int, pidx: int, length: int):
    """读取某属性类型第 pidx 起连续 length 个元素（数组属性完整展开）。

    对齐 assets_cache_service 的 INDEXED vec4 数组提取：同一 ptype 的属性
    共享同一值数组槽位区，pidx 间距即数组长度。越界/无法读取时截断。
    """
    if ptr <= 0 or ptr >= len(data) or length <= 0:
        return None
    out: List = []
    for k in range(length):
        v = _read_typed_value(data, ptr, ptype, pidx + k)
        if v is None:
            break
        if ptype in (5, 6, 7, 8):  # vec2/vec3/vec4/mat4：元素逐个规整，避免 float32 长小数
            v = [_f(x) for x in v]
        out.append(v)
    return out or None


def decode_material(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 MaterialPrototype（Korabli 0x88B / WG 0x78B，按服务器布局自适应）。

    Korabli 布局（2026-08-03 实测）相对 WoWS 的 0x78 布局整体偏移 +8 字节，
    且 +0x28 是"每属性一个 u32"的标志区（值恒 1）：
      +0x00 u16 property_count, +0x02 u16 flags, +0x08 u32 shader_id
      +0x18 u64 names_ptr, +0x20 u64 type_idx_ptr
      +0x28 u64 标志区（每属性 u32，忽略）
      +0x30 bool / +0x38 int32 / +0x40 float_a / +0x48 float_b
      +0x50 texture / +0x58 vec2 / +0x60 vec3 / +0x68 vec4 / +0x70 mat4
      +0x78 u64 material_hash

    WG 布局（wows-toolkit material.rs）：
      +0x00 u16 property_count, +0x02 u16 flags, +0x04 u32 shader_id,
      +0x08 u64 reserved, +0x10 names_ptr, +0x18 type_idx_ptr,
      +0x20..+0x60 type_ptrs[9], +0x68 material_hash,
      +0x70 u32 sort_order, +0x74 u32 material_kind(-1 = 未设置)

    Korabli 末尾：+0x80 u32 material_kind(-1 = 未设置)

    ``+0x02`` 的**低字节**就是 SDK 明文里的 ``<collisionFlags>``（BigWorld
    ``Material::collisionFlags_`` 的低 8 位，写进碰撞三角 flags 低字节）；
    高字节在 WG 侧另有含义（与 alphaTest/双面等材质变体对应，Lesta 恒 0）。

    指针为 u64，基准 = 记录起始。
    """
    wg = get_wows_type() == "Wargaming"
    lay = _MATERIAL_LAYOUT[wg]
    need = lay["item"]
    shader_off = 0x04 if wg else 0x08
    names_off = lay["names"]
    type_idx_off = lay["types"]
    type_ptrs_base = lay["tptr"]
    mat_hash_off = 0x68 if wg else 0x78
    if len(data) < need:
        raise ParseError(f"MaterialPrototype 数据过短: {len(data)}")
    property_count = B.read_u16(data, 0x00)
    flags = B.read_u16(data, 0x02)
    shader_id = B.read_u32(data, shader_off)
    names_ptr = B.read_u64(data, names_off)
    type_idx_ptr = B.read_u64(data, type_idx_off)
    type_ptrs = {t: B.read_u64(data, type_ptrs_base + t * 8) for t in range(9)}
    material_hash = B.read_u64(data, mat_hash_off)
    collision_flags = flags & 0xFF
    # materialKind：独立的 u32 字段，-1（0xFFFFFFFF）= 未设置（BigWorld 语义）
    kind_raw = B.read_u32(data, lay["kind"]) if len(data) >= lay["kind"] + 4 else 0
    material_kind = 0 if kind_raw in (0xFFFFFFFF, -1) else kind_raw

    names = B.parse_u32_array(data, names_ptr, property_count) if names_ptr else []
    type_idx = B.parse_u16_array(data, type_idx_ptr, property_count) if type_idx_ptr else []

    # 数组长度推断：同一 ptype 的属性共享同一值数组槽位区，按 pidx 排序后
    # 相邻间距即数组长度（INDEXED 分块材质的 6 个 196 项数组 pidx 0/196/… 间距
    # 196）；最后一组改用 OOL 区边界，避免把「末尾单个 vec4」误当成 196 项数组
    # （见 material_array_lengths 的说明）。
    arr_lens = material_array_lengths(
        data, property_count, type_idx, type_ptrs,
        material_ool_end(data, wg), wg)

    properties: List[dict] = []
    for i in range(property_count):
        ti = type_idx[i] if i < len(type_idx) else 0
        ptype = ti & 0xF
        pidx = ti >> 4
        raw_name = names[i] if i < len(names) else 0
        value = _read_typed_value(data, type_ptrs.get(ptype, 0), ptype, pidx)
        prop = {
            "name": db.strings.get_string_or_hex(raw_name),
            "name_hash": raw_name,
            "type": _MATERIAL_TYPE_NAMES.get(ptype, f"type_{ptype}"),
            "type_raw": ptype,
        }
        if ptype == 4 and isinstance(value, int):
            prop["value"] = f"0x{value:016X}"
            prop["value_path"] = _resolve_path_id(db, value)
        else:
            prop["value"] = value
        # 数组属性：输出完整值列表（INDEXED vec4 数组等），供浏览器显示明文式完整 arr。
        length = arr_lens.get(i, 1)
        if length > 1 and ptype in (1, 2, 3, 5, 6, 7, 8):
            arr = _read_typed_array(data, type_ptrs.get(ptype, 0), ptype, pidx, length)
            if arr:
                prop["array"] = arr
        properties.append(prop)

    return {
        "_type": "MaterialPrototype",
        # 官方 ModsSDK 明文格式（<mfm><fx>/<materialKind>/<collisionFlags>/<property>）
        # 二进制里没有 fx 字符串：fx 路径由 uncode_assets.mfm_fx 从 material_hash
        # （fx 资源 selfId）独立解析，本函数保持纯材质解码，不掺 fx 逻辑。
        "fx": f"0x{shader_id:08X}",
        # collisionFlags = +0x02 低字节：碰撞面标记（写进碰撞三角 flags 低字节）。
        # bit0 = 相机可穿透、bit1 = 镂空/透明（详见 COLLISION_FLAG_BITS）。
        # 注意：Mod SDK 明文导出时该值恒写 0，与 assets.bin 里的真实值无关。
        "collisionFlags": collision_flags,
        # +0x02 高字节（WG 侧与 alphaTest/双面等材质变体对应，Lesta 恒 0）
        "flags_high": flags >> 8,
        # 原始 u16（= flags_high << 8 | collisionFlags），保留供排查
        "flags": flags,
        # materialKind：BigWorld 的「表面类型」，用于贴花/碰撞材质选择
        # （实测仅 mesh_decal 材质非 0：grass=1 / road=2 / sand=3）
        "materialKind": material_kind,
        "property_count": property_count,
        "shader_id": f"0x{shader_id:08X}",
        "material_hash": f"0x{material_hash:016X}",
        "properties": properties,
    }


# ── VisualPrototype ───────────────────────────────────────────────────────

def decode_visual(data: bytes, db: PrototypeDatabase, record_base: int = 0) -> dict:
    """解码 VisualPrototype（Korabli 实测 0x40B/条，blob 2）。

    Korabli 布局（2026-08-19 重新实测，并与 wows-toolkit 交叉验证）：
      +0x00 vec4 min（取 xyz）, +0x10 vec4 max（取 xyz）
      +0x20 u64 geometry 资源ID（.geometry）, +0x28 u64 primitives 资源ID
      +0x30 u64 render_sets_count, +0x38 u64 render_sets relptr（**record-relative**）
    渲染集 OOL（步长 0x50）：+0x00 u32 shape.vertices 名 / +0x04 u32 indices 名 /
    +0x08 u32 材质名 / +0x20 u64 material_mfm selfId。

    ⚠️ 旧实现误用 0x80 步长（把两条 0x40 记录合并成一条），导致渲染集错配
    （如 JGA180 误用 JGA181 的 TurretShapeff）。修正后每条记录唯一 geometry。
    """
    if len(data) < 0x40:
        raise ParseError(f"VisualPrototype 数据过短: {len(data)}")

    index = db.build_self_id_index()

    def path_of(h: int) -> str:
        if h == 0:
            return ""
        if h == 0xFFFFFFFFFFFFFFFF:
            return "(none)"
        i = index.get(h)
        return db.reconstruct_path(i, index) if i is not None else f"0x{h:016X}"

    render_sets_count = B.read_u64(data, 0x30)
    render_sets_rel = B.read_u64(data, 0x38)

    result = {
        "_type": "VisualPrototype",
        "bounding_box": {
            "min": _arr(B.parse_vec3(data, 0x00)),
            "max": _arr(B.parse_vec3(data, 0x10)),
        },
        "geometry": {
            "path": path_of(B.read_u64(data, 0x20)),
            "id": f"0x{B.read_u64(data, 0x20):016X}",
            "primitives": path_of(B.read_u64(data, 0x28)),
            "primitives_id": f"0x{B.read_u64(data, 0x28):016X}",
        },
        "render_sets_count": render_sets_count,
    }

    # 渲染集 OOL：relptr 为 **record-relative**（data 从记录起始切片 → 下标即 rel）。
    # 渲染集数组从 **rel** 起（每项 0x50 步长）。旧实现误 +0x40（0x80 错位补偿）。
    # 区域边界 = 下一记录 +0x38 relptr（相邻记录渲染集区首尾相接），避免越界。
    rs_pos = render_sets_rel if 0 < render_sets_rel < len(data) else None
    rs_end = len(data)
    if len(data) >= 0x40 + 0x38 + 8:
        _nxt = B.read_u64(data, 0x40 + 0x38)
        if _nxt and _nxt > render_sets_rel:
            rs_end = 0x40 + _nxt
    if rs_pos is not None:
        result["render_sets"] = _visual_render_sets(
            data, rs_pos, db, index, end_pos=rs_end, max_items=render_sets_count)
    else:
        result["render_sets"] = []

    # 粒子相关引用（渲染集 OOL 区域内可反查的粒子路径）
    if rs_pos is not None:
        result["particle_refs"] = sorted(set(
            _particle_refs(data, db, rs_pos, max(0, rs_end - rs_pos))))
    else:
        result["particle_refs"] = []
    return result


def _render_set_bbox(data: bytes, off: int) -> Optional[dict]:
    """renderSet 自带的包围盒（+0x30 min vec3 / +0x40 max vec3，各带 4B 填充）。

    未填充时为哨兵（min = FLT_MAX, max = -FLT_MAX），此时返回 None（明文中省略）。
    """
    try:
        mn = [B.read_f32(data, off + 0x30 + k * 4) for k in range(3)]
        mx = [B.read_f32(data, off + 0x40 + k * 4) for k in range(3)]
    except Exception:  # noqa: BLE001
        return None
    if any(abs(v) >= 3.0e38 or v != v for v in mn + mx):
        return None
    return {"min": mn, "max": mx}


def _visual_render_sets(data: bytes, pos: int, db: PrototypeDatabase,
                        self_id_index: Dict[int, int],
                        end_pos: Optional[int] = None,
                        max_items: int = 0) -> List[dict]:
    """字符串扫描 OOL 渲染集区 → 结构化项列表。

    渲染集结构（Korabli 实测 0x50 步长）：+0x00 u32 shape.vertices 名 /
    +0x04 u32 indices 名 / +0x08 u32 材质名 / +0x20 u64 material_mfm selfId。
    扫描 '*.vertices' 即渲染集起点；只扫 [pos, end_pos)（下一记录 relptr 定界），
    max_items（= +0x70 count，权威渲染集数）作为兜底截断，避免区域边界失效时
    越界扫到其他记录。每个 shape 只保留首次出现。damage 标记：crack 损伤 /
    低模 LOD 变体。
    """
    items: List[dict] = []
    seen: set = set()
    end = min(end_pos or (pos + 0x4000), len(data))
    for off in range(pos, end - 0x30, 4):
        shape = db.strings.get_string_by_id(B.read_u32(data, off)) or ""
        if not shape.endswith(".vertices"):
            continue
        if shape in seen:
            continue
        seen.add(shape)
        sind = db.strings.get_string_by_id(B.read_u32(data, off + 4)) or ""
        mat = db.strings.get_string_by_id(B.read_u32(data, off + 8)) or ""
        mfm_h = B.read_u64(data, off + 0x20)
        smfm = ""
        i = self_id_index.get(mfm_h)
        if i is not None:
            smfm = db.reconstruct_path(i, self_id_index)
        damage = ("_crack_" in shape or "_lod" in shape or "Crack" in mat)
        # +0x0C u8 skinned / +0x0D u8 node_count / +0x28 u32 node_names relptr
        # （相对 render_set 起始）；节点名顺序与官方 Mod SDK 明文一致
        skinned = B.read_u8(data, off + 0x0C)
        node_count = B.read_u8(data, off + 0x0D)
        nodes_rel = B.read_u32(data, off + 0x28)
        node_names: List[str] = []
        if node_count and nodes_rel:
            for j in range(node_count):
                try:
                    sid = B.read_u32(data, off + nodes_rel + j * 4)
                except Exception:  # noqa: BLE001
                    break
                nm = db.strings.get_string_by_id(sid)
                if nm:
                    node_names.append(nm)
        items.append({
            # 官方 ModsSDK 明文格式（<renderSet><geometry><vertices/primitive/material>）
            "vertices": shape,
            "primitive": sind,
            "material_identifier": mat,
            "material_mfm": smfm,
            "damage": damage,
            "skinned": bool(skinned),
            "nodes": node_names,
            "bounding_box": _render_set_bbox(data, off),
        })
        if max_items and len(items) >= max_items:
            break
    return items


# ── VisualPrototype（WG 0x70 布局）───────────────────────────────────────

def decode_visual_wg(data: bytes, db: PrototypeDatabase, record_base: int = 0) -> dict:
    """解码 VisualPrototype（WG 0x70B/条，blob 1；wows-toolkit visual.rs）。

    WG 记录布局（与 Korabli 0x40 完全不同）：
      +0x00 u32 nodes_count / +0x04 pad
      +0x08 i64 name_map_name_ids / +0x10 i64 name_map_node_ids /
      +0x18 i64 name_ids / +0x20 i64 matrices / +0x28 i64 parent_ids（均 relptr）
      +0x30 u64 merged_geometry_path_id
      +0x38 u8 underwater_model / +0x39 u8 abovewater_model /
      +0x3A u16 render_sets_count / +0x3C u8 lods_count
      +0x40 BoundingBox(32B) / +0x60 i64 render_sets relptr / +0x68 i64 lods relptr
    RenderSet 0x28：+0x00 u32 name_id / +0x04 u32 material_name_id /
      +0x08 u32 vertices_mapping / +0x0C u32 indices_mapping /
      +0x10 u64 material_mfm_path_id / +0x18 u8 skinned / +0x19 u8 nodes_count /
      +0x20 i64 node_name_ids relptr
    LOD 0x10：+0x00 f32 extent / +0x04 u8 casts_shadow / +0x06 u16 count / +0x08 relptr
    """
    if len(data) < 0x70:
        raise ParseError(f"VisualPrototype(WG) 数据过短: {len(data)}")
    index = db.build_self_id_index()

    def path_of(h: int) -> str:
        if h == 0:
            return ""
        if h == 0xFFFFFFFFFFFFFFFF:
            return "(none)"
        i = index.get(h)
        return db.reconstruct_path(i, index) if i is not None else f"0x{h:016X}"

    def str_of(h: int) -> str:
        return db.strings.get_string_or_hex(h)

    # ── nodes（基础骨架：HP_ 挂点 / stage/Bow/MidFront... 骨骼）──────────
    nodes_count = B.read_u32(data, 0x00)
    nodes: dict = {"count": nodes_count, "name_ids": [], "matrices": [], "parent_ids": []}
    if 0 < nodes_count < 5000:
        try:
            nodes = {
                "count": nodes_count,
                "name_map_name_ids": B.parse_u32_array(data, B.read_u64(data, 0x08), nodes_count),
                "name_map_node_ids": B.parse_u16_array(data, B.read_u64(data, 0x10), nodes_count),
                "name_ids": [str_of(n) for n in
                             B.parse_u32_array(data, B.read_u64(data, 0x18), nodes_count)],
                "name_id_hashes": B.parse_u32_array(data, B.read_u64(data, 0x18), nodes_count),
                "matrices": B.parse_matrix_array(data, B.read_u64(data, 0x20), nodes_count),
                "parent_ids": B.parse_u16_array(data, B.read_u64(data, 0x28), nodes_count),
            }
        except Exception:  # noqa: BLE001
            pass

    geometry_path_id = B.read_u64(data, 0x30)
    render_sets_count = B.read_u16(data, 0x3A)
    lods_count = B.read_u8(data, 0x3C)

    # ── render_sets ────────────────────────────────────────────────────
    render_sets: List[dict] = []
    rs_rel = B.read_i64(data, 0x60)
    if rs_rel and render_sets_count:
        for k in range(render_sets_count):
            o = rs_rel + k * 0x28
            if o + 0x28 > len(data):
                break
            nid = B.read_u32(data, o)
            mid = B.read_u32(data, o + 0x04)
            vmap_id = B.read_u32(data, o + 0x08)
            imap_id = B.read_u32(data, o + 0x0C)
            mfm_h = B.read_u64(data, o + 0x10)
            skinned = B.read_u8(data, o + 0x18)
            ncnt = B.read_u8(data, o + 0x19)
            node_names: List[str] = []
            nrel = B.read_i64(data, o + 0x20)
            # ⚠️ node 列表**不依赖 skinned**：非蒙皮渲染集同样带绑定节点
            # （实测 3005 个渲染集里 2892 个 skinned=0 但 ncnt>0）。
            if ncnt and nrel:
                nabs = o + nrel
                if nabs + ncnt * 4 <= len(data):
                    node_names = [str_of(B.read_u32(data, nabs + j * 4)) for j in range(ncnt)]
            render_sets.append({
                "name": str_of(nid),
                "material_identifier": str_of(mid),
                "vertices_mapping_id": f"0x{vmap_id:08X}",
                "indices_mapping_id": f"0x{imap_id:08X}",
                # mapping id 就是 shape 名的 MurmurHash3_x86_32，可直接反查字符串表
                "vertices": str_of(vmap_id),
                "primitive": str_of(imap_id),
                "material_mfm": path_of(mfm_h),
                "skinned": bool(skinned),
                "nodes": node_names,
            })

    # ── lods ──────────────────────────────────────────────────────────
    lods: List[dict] = []
    lod_rel = B.read_i64(data, 0x68)
    if lod_rel and lods_count:
        for k in range(lods_count):
            o = lod_rel + k * 0x10
            if o + 0x10 > len(data):
                break
            rsn_cnt = B.read_u16(data, o + 0x06)
            rsn_rel = B.read_i64(data, o + 0x08)
            rsn: List[str] = []
            if rsn_rel and rsn_cnt:
                rabs = o + rsn_rel
                if rabs + rsn_cnt * 4 <= len(data):
                    rsn = [str_of(B.read_u32(data, rabs + j * 4)) for j in range(rsn_cnt)]
            lods.append({
                "extent": B.read_f32(data, o),
                "casts_shadow": bool(B.read_u8(data, o + 0x04)),
                "render_set_names": rsn,
            })

    return {
        "_type": "VisualPrototype",
        "nodes": nodes,
        "geometry": {"path": path_of(geometry_path_id), "id": f"0x{geometry_path_id:016X}"},
        "underwater_model": bool(B.read_u8(data, 0x38)),
        "abovewater_model": bool(B.read_u8(data, 0x39)),
        "bounding_box": {
            "min": _arr(B.parse_vec3(data, 0x40)),
            "max": _arr(B.parse_vec3(data, 0x50)),
        },
        "render_sets_count": render_sets_count,
        "render_sets": render_sets,
        "lods_count": lods_count,
        "lods": lods,
    }


# ── ModelPrototype ────────────────────────────────────────────────────────

def decode_model(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 ModelPrototype（Korabli 实测 0x20B/条，blob 3）。

    2026-08-03 真实数据逆向：两个 u64 均为 selfId 资源引用——
      +0x00 model_resource_id  → .model 路径（可为 0）
      +0x08 visual_resource_id → .visual 路径
      +0x10 2×f32  距离/尺寸参数（3/8/10/16/400/50000…）
      +0x18 u32    count（位标志：bit1 = castsShadow；实测 8/9→false，10/11→true）
      +0x1C u32    tail（通常 0）
    """
    if len(data) < 0x20:
        raise ParseError(f"ModelPrototype 数据过短: {len(data)}")

    model_id = B.read_u64(data, 0x00)
    visual_id = B.read_u64(data, 0x08)
    index = db.build_self_id_index()

    def path_of(self_id: int) -> str:
        if self_id == 0:
            return ""
        idx = index.get(self_id)
        return db.reconstruct_path(idx, index) if idx is not None else f"0x{self_id:016X}"

    count = B.read_u32(data, 0x18)
    return {
        "_type": "ModelPrototype",
        # 官方 ModsSDK 明文格式（<model><castsShadow>/<parent>/<extent>/<nodefullVisual>/<metaData>）
        "parent": path_of(model_id),
        "nodefullVisual": path_of(visual_id),
        "extent": {
            "distance_a": _f(B.read_f32(data, 0x10)),
            "distance_b": _f(B.read_f32(data, 0x14)),
        },
        "castsShadow": bool(count & 0x02),
        "metaData": "Lesta Studio",
        "count": count,
        "tail": B.read_u32(data, 0x1C),
        "raw_hex": data[:0x20].hex(),
    }


def decode_model_wg(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 WG 服 ModelPrototype（0x28B/条，blob 3；wows-toolkit model.rs）。

    WG 布局（与 Korabli 0x20 完全不同）：
      +0x00 u64 visualResourceId   # -> .visual 路径（selfId）  —— 模型引用的视觉
      +0x08 u8  skelExtResIdCount  # 骨架扩展资源数
      +0x09 u8  miscType
      +0x0A u8  animationsCount
      +0x0B u8  dyesCount
      +0x0C u32 (padding)
      +0x10 i64 skelExtResIdsPtr   # relptr -> u64[]
      +0x18 i64 animationsPtr      # relptr -> AnimationEntry[]
      +0x20 i64 dyesPtr            # relptr -> DyeEntry[]

    返回：把「模型引用」与其「视觉」明确拆开（visual 为解析后的 .visual 路径）。
    """
    if len(data) < 0x28:
        raise ParseError(f"ModelPrototype(WG) 数据过短: {len(data)}")
    index = db.build_self_id_index()

    def path_of(self_id: int) -> str:
        if self_id == 0:
            return ""
        idx = index.get(self_id)
        return db.reconstruct_path(idx, index) if idx is not None else f"0x{self_id:016X}"

    def str_of(h: int) -> str:
        return db.strings.get_string_or_hex(h)

    visual_id = B.read_u64(data, 0x00)
    skel_ext_count = data[0x08]
    misc_type = data[0x09]
    animations_count = data[0x0A]
    dyes_count = data[0x0B]
    skel_ext_ids: List[int] = []
    if skel_ext_count and B.read_i64(data, 0x10):
        try:
            skel_ext_ids = B.parse_u64_array(data, B.read_i64(data, 0x10), skel_ext_count)
        except Exception:  # noqa: BLE001
            skel_ext_ids = []
    # animations：u64 路径 selfId 数组（.ssm 动画状态机）
    animations: List[str] = []
    anim_rel = B.read_i64(data, 0x18)
    if animations_count and anim_rel:
        try:
            animations = [path_of(v) for v in
                          B.parse_u64_array(data, anim_rel, animations_count)]
        except Exception:  # noqa: BLE001
            animations = []
    # dyes：DyeEntry 0x20（matter/replaces + tint 名与材质路径）
    dyes: List[dict] = []
    dye_rel = B.read_i64(data, 0x20)
    if dyes_count and dye_rel:
        for k in range(dyes_count):
            off = dye_rel + k * 0x20
            if off + 0x20 > len(data):
                break
            matter = B.read_u32(data, off)
            replaces = B.read_u32(data, off + 0x04)
            tnum = B.read_i32(data, off + 0x08)
            tnum = max(0, min(tnum, 512))
            tint_names: List[str] = []
            tint_mats: List[str] = []
            if tnum:
                try:
                    nrel = B.read_i64(data, off + 0x10)
                    mrel = B.read_i64(data, off + 0x18)
                    if nrel:
                        tint_names = [str_of(v) for v in B.parse_u32_array(data, nrel, tnum)]
                    if mrel:
                        tint_mats = [path_of(v) for v in B.parse_u64_array(data, mrel, tnum)]
                except Exception:  # noqa: BLE001
                    pass
            dyes.append({
                "matter": str_of(matter),
                "replaces": str_of(replaces),
                "tint_names": tint_names,
                "tint_materials": tint_mats,
            })
    return {
        "_type": "ModelPrototype",
        "visualResourceId": f"0x{visual_id:016X}",
        "visual": path_of(visual_id),            # 该模型引用的 .visual（独立展示）
        "skelExtResIdCount": skel_ext_count,
        "skelExtResIds": [path_of(i) for i in skel_ext_ids],
        "miscType": misc_type,
        "animationsCount": animations_count,
        "animations": animations,
        "dyesCount": dyes_count,
        "dyes": dyes,
        "skelExtResIdsPtr": f"0x{B.read_u64(data, 0x10):016X}",
        "animationsPtr": f"0x{B.read_u64(data, 0x18):016X}",
        "dyesPtr": f"0x{B.read_u64(data, 0x20):016X}",
        "raw_hex": data[:0x28].hex(),
    }


# ── SkeletonPrototype（Korabli 独有）──────────────────────────────────────

def decode_skeleton(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 SkeletonPrototype（0x40B/条，blob 1）。

    指针为 **u32 相对指针**，基准 = 记录起始。
    """
    if len(data) < 0x40:
        raise ParseError(f"SkeletonPrototype 数据过短: {len(data)}")
    count = B.read_u32(data, 0x00)
    rotation_limits_count = B.read_u32(data, 0x04)

    # ⚠️ 2026-08-19 修正：指针为 **u64**（旧实现误用 u32，导致骨架节点树解析失败）。
    # rec9769（JGA181 骨架）实证：+0x08 起 u64 relptr → 指向 Scene Root/HP_gunFire 节点名。
    name_map_name_ids: List[int] = []
    name_map_node_ids: List[int] = []
    name_ids: List[int] = []
    matrices: List[List[float]] = []
    parent_ids: List[int] = []
    if count > 0:
        name_map_name_ids = B.parse_u32_array(data, B.read_u64(data, 0x08), count)
        name_map_node_ids = B.parse_u16_array(data, B.read_u64(data, 0x10), count)
        name_ids = B.parse_u32_array(data, B.read_u64(data, 0x18), count)
        matrices = B.parse_matrix_array(data, B.read_u64(data, 0x20), count)
        parent_ids = B.parse_u16_array(data, B.read_u64(data, 0x38), count)

    # 旋转限制：Vec4×2[rotationLimitsCount]（min/max 角度）
    rotation_limits: List[dict] = []
    rotation_limits_ids: List[int] = []
    if rotation_limits_count > 0:
        lim_abs = B.read_u64(data, 0x28)
        for j in range(rotation_limits_count):
            off = lim_abs + j * 32
            rotation_limits.append({
                "min": _arr(B.parse_vec4(data, off)),
                "max": _arr(B.parse_vec4(data, off + 16)),
            })
        rotation_limits_ids = B.parse_u16_array(data, B.read_u64(data, 0x30), count)

    return {
        "_type": "SkeletonPrototype",
        "count": count,
        "rotation_limits_count": rotation_limits_count,
        "name_map_name_ids": name_map_name_ids,
        "name_map_node_ids": name_map_node_ids,
        "name_ids": [db.strings.get_string_or_hex(n) for n in name_ids],
        "name_id_hashes": name_ids,
        "matrices": matrices,
        "rotation_limits": rotation_limits,
        "rotation_limits_ids": rotation_limits_ids,
        "parent_ids": parent_ids,
    }


# ── SkeletonExtenderPrototype（WG 独有）───────────────────────────────────

def decode_skeleton_extender(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 SkeletonExtenderPrototype（WG 0x20B/条，blob 2；wows-toolkit skeleton_extender.rs）。

    +0x00 u16 flag（1=带骨架）/ +0x02 u16 node_count / +0x04 pad
    +0x08 i64 name_ids relptr -> u32[node_count]（节点名哈希）
    +0x10 i64 parent_name_ids relptr -> u32[node_count]（父节点名哈希，如 Scene Root）
    +0x18 i64 matrices relptr -> 4x4float[node_count]（列主序，节点 local 变换）
    三数组 index-aligned；父按名字引用（非数组索引），节点通常挂在 Scene Root（identity）。
    """
    if len(data) < 0x20:
        raise ParseError(f"SkeletonExtenderPrototype 数据过短: {len(data)}")
    flag = B.read_u16(data, 0x00)
    node_count = B.read_u16(data, 0x02)
    name_ids: List[int] = []
    parent_name_ids: List[int] = []
    matrices: List[List[float]] = []
    if node_count > 0:
        name_ids = B.parse_u32_array(data, B.read_i64(data, 0x08), node_count)
        parent_name_ids = B.parse_u32_array(data, B.read_i64(data, 0x10), node_count)
        matrices = B.parse_matrix_array(data, B.read_i64(data, 0x18), node_count)
    return {
        "_type": "SkeletonExtenderPrototype",
        "flag": flag,
        "node_count": node_count,
        "name_ids": [db.strings.get_string_or_hex(n) for n in name_ids],
        "name_id_hashes": name_ids,
        "parent_name_ids": [db.strings.get_string_or_hex(n) for n in parent_name_ids],
        "matrices": matrices,
    }


# ── TrailPrototype（Korabli 独有）─────────────────────────────────────────

_TRAIL_TEXTURE_FIELDS = [
    "albedoTexture", "hatTexture", "beamMaskTexture", "gradientTexture",
    "normalTexture", "emissionTexture", "distortionTexture", "dissolveTexture",
]

_TRAIL_VEC2_FIELDS = [
    "uvScale", "uvOffset", "uvScroll", "emissionBounds", "cameraFade",
    "uvDistortionScale", "uvDistortionScroll", "distortionStrength", "beamSize",
    "uvBeamScroll", "uvBeamScale", "uvBeamSplit",
]

_TRAIL_VEC4_FIELDS = ["hatColor", "beamHeadColor", "beamSplitColor", "beamTailColor"]

_TRAIL_FLOAT_FIELDS = [
    "dissolveStart", "dissolveStrength", "lifetime", "minSpawnDistance",
    "maxSpawnDistance", "hatDistance", "hatSize", "beamDistance", "beamFadeIn",
    "beamFadeOut", "fadeIn", "fadeOut", "spawnAngle",
    "directDiffuseMultiplier", "indirectDiffuseMultiplier",
]

_TRAIL_BOOL_FIELDS = [
    "isBeamEnable", "isHatEnable", "isSoftIntersectionEnabled",
    "isLockAxisEnabled", "isInstantDeath", "isDistortionEnabled",
    "isDissolveEnabled", "isEmissionEnabled",
]


def decode_trail(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 TrailPrototype（0x1A0B/条，blob 10，粒子轨迹）。

    指针为 **u32 相对指针**，基准 = 记录起始。
    布局由实测数据确定。
    """
    if len(data) < 0x1A0:
        raise ParseError(f"TrailPrototype 数据过短: {len(data)}")

    # 8×纹理（每条 16B：flags u32 + pad u32 + relptr u32 + pad u32）
    # 注意：Korabli relptr 指向 OOL 字符串时偶有截断偏差，已做可读性保护，
    # 无法解析为合法路径的置空。
    textures: Dict[str, dict] = {}
    for i, name in enumerate(_TRAIL_TEXTURE_FIELDS):
        base = i * 0x10
        flags = B.read_u32(data, base + 0x00)
        relptr = B.read_u32(data, base + 0x08)
        path = ""
        if relptr and relptr < len(data):
            s = B.read_null_terminated_string(data, relptr)
            if s and all(32 <= ord(c) < 127 for c in s) and ("/" in s or "." in s):
                path = s
        textures[name] = {"flags": flags, "path": path}

    # 关键帧
    def _keyframes(relptr_field: int, count: int) -> List[dict]:
        out: List[dict] = []
        if count > 0 and relptr_field < len(data):
            for j in range(count):
                off = relptr_field + j * 8
                if off + 8 > len(data):
                    break
                out.append({"time": _f(B.read_f32(data, off)), "value": _f(B.read_f32(data, off + 4))})
        return out

    color_kf_count = B.read_u32(data, 0x148)
    size_kf_count = B.read_u32(data, 0x14C)
    emission_kf_count = B.read_u32(data, 0x150)

    result: dict = {
        "_type": "TrailPrototype",
        "textures": textures,
        "color_key_frames": _keyframes(B.read_u32(data, 0x80), color_kf_count),
        "size_key_frames": _keyframes(B.read_u32(data, 0x88), size_kf_count),
        "emission_key_frames": _keyframes(B.read_u32(data, 0x90), emission_kf_count),
        "lock_axis": B.read_u32(data, 0x98),
        "path_point_count": B.read_u32(data, 0x144),
        "vec2": {},
        "vec4": {},
        "floats": {},
        "beam_technique_type": B.read_u8(data, 0x191),
        "bools": {},
    }
    for i, name in enumerate(_TRAIL_VEC2_FIELDS):
        result["vec2"][name] = _arr(B.parse_vec2(data, 0xA4 + i * 8))
    for i, name in enumerate(_TRAIL_VEC4_FIELDS):
        result["vec4"][name] = _arr(B.parse_vec4(data, 0x104 + i * 16))
    for i, name in enumerate(_TRAIL_FLOAT_FIELDS):
        result["floats"][name] = _f(B.read_f32(data, 0x154 + i * 4))
    for i, name in enumerate(_TRAIL_BOOL_FIELDS):
        result["bools"][name] = bool(B.read_u8(data, 0x192 + i))
    return result


# ── VfxMaterialPrototype（Korabli 独有）───────────────────────────────────

def _decode_vfx_packed_string(data: bytes, struct_base: int) -> str:
    """解析 Vfx 中的 packed string：{size u64 @+0, relptr u64 @+8}，基准=结构起始。"""
    size = B.read_u64(data, struct_base) if struct_base + 8 <= len(data) else 0
    rel = B.read_u64(data, struct_base + 8) if struct_base + 16 <= len(data) else 0
    if size <= 0 or rel <= 0:
        return ""
    abs_off = struct_base + rel
    if abs_off + size > len(data):
        abs_off = rel  # 兜底：可能基准就是记录起始
        if abs_off + size > len(data):
            return ""
    raw = data[abs_off:abs_off + size]
    raw = raw.split(b"\x00")[0]
    return raw.decode("utf-8", errors="replace")


def decode_vfx_material(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 VfxMaterialPrototype（0x210B/条，blob 11）。

    2026-08-03 实测：三个路径为 packed string {size u64, relptr u64}，
    基准 = packed string 结构起始。cpuProperties / Properties 块暂以原始
    hex 输出（其布局未逐字段逆向）。
    """
    if len(data) < 0x210:
        raise ParseError(f"VfxMaterialPrototype 数据过短: {len(data)}")

    paths = {
        "pathToEmitter": _decode_vfx_packed_string(data, 0x00),
        "SimulationShader": _decode_vfx_packed_string(data, 0x10),
        "RenderingShader": _decode_vfx_packed_string(data, 0x20),
    }

    return {
        "_type": "VfxMaterialPrototype",
        "shader_paths": paths,
        "head_raw_hex": data[0x30:0x90].hex(),
        "tail_raw_hex": data[0x90:0x210].hex(),
    }


# ── MiscSettingsPrototype（Korabli 独有）──────────────────────────────────

def decode_misc_settings(data: bytes, db: PrototypeDatabase) -> dict:
    """解码 MiscSettingsPrototype（0x28B/条，blob 9）。

    2026-08-03 实测（Korabli 正式服）：4 组 (count u16 @+0x00/0x02/0x04/0x06,
    relptr u64 @+0x08/0x10/0x18/0x20，基准=记录起始)，四组一一对应且连续。
    """
    if len(data) < 0x28:
        raise ParseError(f"MiscSettingsPrototype 数据过短: {len(data)}")

    def _name_ids(relptr_field: int, count: int) -> List[str]:
        if count <= 0 or relptr_field <= 0 or relptr_field >= len(data):
            return []
        if relptr_field + count * 4 > len(data):
            return []  # 越界防御
        return [
            db.strings.get_string_or_hex(n)
            for n in B.parse_u32_array(data, relptr_field, count)
        ]

    return {
        "_type": "MiscSettingsPrototype",
        "counts": {
            "necessary": B.read_u16(data, 0x00),
            "optional": B.read_u16(data, 0x02),
            "redundant": B.read_u16(data, 0x04),
            "extra": B.read_u16(data, 0x06),
        },
        # count 与 relptr 一一对应：0x00→0x08, 0x02→0x10, 0x04→0x18, 0x06→0x20
        "structural_name_ids": _name_ids(B.read_u64(data, 0x08), B.read_u16(data, 0x00)),
        "necessary_name_ids": _name_ids(B.read_u64(data, 0x10), B.read_u16(data, 0x02)),
        "optional_name_ids": _name_ids(B.read_u64(data, 0x18), B.read_u16(data, 0x04)),
        "redundant_name_ids": _name_ids(B.read_u64(data, 0x20), B.read_u16(data, 0x06)),
    }


# ── EffectPrototype（粒子效果图）──────────────────────────────────────

def decode_effect(data: bytes, db: PrototypeDatabase, record_base: int = 0,
                  item_size: int = 0x10) -> dict:
    """解码 EffectPrototype（0x10B/条，blob 5，粒子效果图，Korabli 实测）。

    记录布局（2026-08-05 数据驱动逆向，relptr 基准=blob 起点）：
      +0x00 f32  scalar（通常 -1.0 或正数，语义未知）
      +0x04 u32  count（子节点/条目数）
      +0x08 u32  relptr（本记录 OOL 区域起点）
      +0x0C u32  pad
    OOL 区域 = [relptr, 下一记录 relptr)，相邻记录 OOL 首尾相接无间隙。
    OOL 内含内嵌原始字符串（如 "glow_0"）与重复的 -1.0f/1.0f/计数/偏移 节点模式。

    本解码为尽力解析（wows-toolkit 亦无结构化解码）：
      头部字段 + OOL 内嵌字符串 + 16B 对齐候选节点头（启发式）。
    """
    if len(data) < item_size:
        raise ParseError(f"EffectPrototype 数据过短: {len(data)}")
    scalar = B.read_f32(data, 0x00)
    count = B.read_u32(data, 0x04)
    rel = B.read_u32(data, 0x08)
    pad = B.read_u32(data, 0x0C)

    # OOL 区域（blob-absolute [rel, next_rel) → data 切片坐标）
    ool_start = rel - record_base
    ool_end = len(data)
    if len(data) >= item_size + 8:
        nrel = B.read_u32(data, item_size + 8)
        if nrel > rel:
            ool_end = nrel - record_base
    region = b""
    ool_len = 0
    if 0 <= ool_start < len(data):
        ool_len = max(0, min(ool_end, len(data)) - ool_start)
        region = data[ool_start:ool_start + ool_len]

    # 16B 对齐候选节点头（启发式：relptr 落在本记录可达范围内）
    nodes: List[dict] = []
    blob_end = len(data) + record_base
    for p in range(0, len(region) - 15, 16):
        r = B.read_u32(region, p + 8)
        if 0 < r < blob_end:
            nodes.append({
                "offset": p,
                "value": _f(B.read_f32(region, p)),
                "count": B.read_u32(region, p + 4),
                "relptr": r,
                "pad": B.read_u32(region, p + 12),
            })
            if len(nodes) >= 32:
                break

    return {
        "_type": "EffectPrototype",
        "scalar": _f(scalar),
        "count": count,
        "relptr": rel,
        "pad": pad,
        "ool_size": ool_len,
        "embedded_strings": _extract_ascii_strings(region, limit=40),
        "candidate_nodes": nodes,
        "ool_hex": region[:256].hex(),
    }


# ── 通用解码（EffectPreset / EffectMetadata / AtlasContour / ModelFbx / 未知）─

def decode_generic(data: bytes, db: PrototypeDatabase, type_name: str, item_size: int) -> dict:
    """通用解码：输出原始字节 + 尽力解析 i64 相对指针字段。"""
    raw = data[:item_size]
    fields: List[dict] = []
    # 按 8B 步长把固定区解析为 u64/u64 对，尝试作为 relptr
    for off in range(0, item_size, 8):
        if off + 8 > len(raw):
            break
        word = B.read_u64(raw, off)
        fields.append({"offset": off, "raw_u64": word})

    # 尝试把每个 u64 当相对指针（基准=记录起始）解析字符串
    resolved: Dict[int, str] = {}
    for f in fields:
        v = f["raw_u64"]
        if 0 < v < len(data) and v < 0x200000:
            probe = data[v:v + 4]
            # 启发式：目标看起来像 ASCII 可打印
            if probe and all(32 <= c < 127 for c in probe):
                resolved[f["offset"]] = B.read_null_terminated_string(data, v)

    return {
        "_type": type_name,
        "item_size": item_size,
        "raw_hex": raw.hex(),
        "fields": fields,
        "resolved_strings": resolved,
    }


# ── 分发入口 ─────────────────────────────────────────────────────────────

def decode_by_type(data: bytes, db: PrototypeDatabase, proto_type: Optional[PrototypeType],
                   record_base: int = 0) -> dict:
    """按 PrototypeType 分发解码。

    record_base: 记录在所属 blob 中的绝对偏移（相对 blob 起点），
                 用于解析 Visual 等类型中基准=blob 起点的 relptr。
    """
    name = proto_type.name if proto_type else "Unknown"
    item_size = proto_type.item_size if proto_type else 0x10
    wg = get_wows_type() == "Wargaming"
    if name == "MaterialPrototype":
        return decode_material(data, db)
    if name == "VisualPrototype":
        if wg:
            # WG VisualPrototype 0x70 布局（nodes/geometry/render_sets/lods）
            return decode_visual_wg(data, db, record_base)
        return decode_visual(data, db, record_base)
    if name == "ModelPrototype":
        if wg:
            return decode_model_wg(data, db)
        return decode_model(data, db)
    if name == "SkeletonPrototype":
        return decode_skeleton(data, db)
    if name == "SkeletonExtenderPrototype":
        return decode_skeleton_extender(data, db)
    if name == "TrailPrototype":
        return decode_trail(data, db)
    if name == "VfxMaterialPrototype":
        return decode_vfx_material(data, db)
    if name == "MiscSettingsPrototype":
        return decode_misc_settings(data, db)
    if name == "EffectPrototype":
        return decode_effect(data, db, record_base)
    # ModelFbx / EffectPreset / EffectMetadata / AtlasContour / 未知
    return decode_generic(data, db, name, item_size)


def decode_prototype_to_json(data: bytes, db: PrototypeDatabase, proto_type: PrototypeType) -> str:
    """解码 prototype 记录为格式化 JSON 字符串。"""
    decoded = decode_by_type(data, db, proto_type)
    return json.dumps(decoded, ensure_ascii=False, indent=2, allow_nan=False)


def parse_mfm_from_db(db: PrototypeDatabase, mfm_path_id: int) -> Optional[dict]:
    """按 selfId 反查并解码 MFM 材质。

    对齐 wows-toolkit `export/texture.rs::parse_mfm_from_db`：
    查 r2p → 定位 → 若属 MaterialPrototype blob → 读取记录并解码为属性表。
    找不到 / 类型不符 / 解码失败时返回 None。
    """
    if not mfm_path_id:
        return None
    value = db.lookup_r2p(mfm_path_id)
    if value is None:
        return None
    try:
        location = db.decode_r2p_value(value)
    except ParseError:
        return None
    entry = db.databases[location.blob_index]
    t = type_from_magic(entry.prototype_magic)
    if t is None or t.name != "MaterialPrototype":
        return None
    data = db.get_record(location)
    try:
        return decode_material(data, db)
    except ParseError:
        return None
