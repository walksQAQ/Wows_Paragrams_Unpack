"""assets.bin 的 Prototype 类型表（Korabli/Lesta 12 类 + Wargaming/WG 10 类）。

⚠️ 依据 2026-08-01 逆向（Korabli64.exe 字符串 + MurmurHash3_x86_32 匹配），
Korabli 有 **12** 个类型（WoWS 只有 10 个），且 blob index → 类型映射与
WoWS 完全不同。**必须按 magic 识别类型，不能按 index 套用 WoWS 表。**

WG 10 类型表（wows-toolkit crates/wowsunpack/src/data/assets_bin_vfs.rs +
models/{material,visual,model}.rs + docs/MODELS.md，2026-08-21 交叉验证）：
  Material 0x5069C471/0x78、Visual 0x480DC57B/0x70、SkeletonExtender 0x1AE023FF/0x20、
  Model 0xA9576F28/0x28、PointLight 0x0D3665A4/0x70、Effect 0xEB23E0AF/0x10、
  VelocityField 0xAFD4A63F/0x18、EffectPreset 0x42E15336/0x10、
  EffectMetadata 0xDFC8F8E0/0x10、AtlasContour 0xF64359AA/0x10。
Material/Visual/Model 的 magic 两服相同，但 item_size 不同（WG 0x78/0x70/0x28，
Korabli 0x88/0x40/0x20）。

服务器切换：thread-local 上下文（AssetsBinService 构造时 set_wows_type），
type_from_magic / item_size_for_blob 等自动按当前服务器查表；未设置时默认 Korabli。
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple


class PrototypeType:
    """一种 prototype 类型（按 magic 唯一标识）。"""

    __slots__ = ("name", "magic", "item_size", "blob_index", "description", "extensions")

    def __init__(self, name: str, magic: int, item_size: int, blob_index: int,
                 description: str = "", extensions: Tuple[str, ...] = ()):
        self.name = name
        self.magic = magic
        self.item_size = item_size
        self.blob_index = blob_index
        self.description = description
        #: 该类型虚拟文件的典型扩展名（2026-08-03 实测；可为空）
        self.extensions = extensions

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PrototypeType {self.name} magic=0x{self.magic:08X} item=0x{self.item_size:X}>"


# ── Korabli 实测类型表（12 个，blob index 顺序为 Korabli 实测）──────────────
# extensions 依据 2026-08-03 正式服统计：
#   .visual 二义（Visual 115232 条 + Skeleton 38287 条，后者路径带 '@' 前缀）

KORABLI_TYPES: Tuple[PrototypeType, ...] = (
    # 实测 0x88（2026-08-03，Korabli 正式服 assets.bin）：
    # 字段 8 字节对齐，names_ptr@+0x18，与 WoWS 的 0x78 不同。
    PrototypeType("MaterialPrototype", 0x5069C471, 0x88, 0, "材质属性表（Korabli 实测 0x88）", (".mfm",)),
    PrototypeType("SkeletonPrototype", 0xD9BB9F4A, 0x40, 1, "Lesta 骨架系统（Korabli 独有）", (".visual",)),
    # Visual/Model 步长均为 2026-08-19 Korabli 重新实测（Visual 0x40，非 0x80）
    PrototypeType("VisualPrototype", 0x480DC57B, 0x40, 2, "渲染集合（Korabli 实测 0x40；geometry@+0x20/primitives@+0x28/render_sets count@+0x30 rel@+0x38）", (".visual",)),
    PrototypeType("ModelPrototype", 0xA9576F28, 0x20, 3, "模型引用（Korabli 实测 0x20；model/visual 资源路径已解码）", (".model",)),
    PrototypeType("ModelFbxPrototype", 0xDF80CF54, 0x10, 4, "FBX 模型（Korabli 独有，空 blob）", (".model_fbx",)),
    PrototypeType("EffectPrototype", 0xEB23E0AF, 0x10, 5, "粒子效果"),
    PrototypeType("EffectPresetPrototype", 0x42E15336, 0x10, 6, "粒子预设", (".effect_preset", ".xml")),
    PrototypeType("EffectMetadataPrototype", 0xDFC8F8E0, 0x10, 7, "粒子元数据"),
    PrototypeType("AtlasContourProto", 0xF64359AA, 0x10, 8, "图集轮廓", (".contours",)),
    PrototypeType("MiscSettingsPrototype", 0xACE328C6, 0x28, 9, "杂项设置（Korabli 独有）"),
    PrototypeType("TrailPrototype", 0x42AF895E, 0x1A0, 10, "粒子轨迹（Korabli 独有）", (".trail",)),
    PrototypeType("VfxMaterialPrototype", 0xCD880533, 0x210, 11, "VFX 材质（Korabli 独有）", (".vfx",)),
)

# ── Wargaming（WG 服）10 类型表 ────────────────────────────────────────────
# 依据 wows-toolkit assets_bin_vfs.rs（from_blob_index/item_size）+
# models/material.rs（0x78）/visual.rs（0x70）/model.rs（0x28）。
# 与 Korabli 相同的 magic：Material/Visual/Model/Effect/EffectPreset/
# EffectMetadata/AtlasContour；WG 独有 SkeletonExtender/PointLight/VelocityField；
# WG 无 Skeleton/ModelFbx/MiscSettings/Trail/VfxMaterial。
WG_TYPES: Tuple[PrototypeType, ...] = (
    PrototypeType("MaterialPrototype", 0x5069C471, 0x78, 0, "材质属性表（WG 实测 0x78）", (".mfm",)),
    PrototypeType("VisualPrototype", 0x480DC57B, 0x70, 1, "渲染集合（WG 实测 0x70）", (".visual",)),
    PrototypeType("SkeletonExtenderPrototype", 0x1AE023FF, 0x20, 2, "骨架扩展（WG 独有）", (".skeleton_extender",)),
    PrototypeType("ModelPrototype", 0xA9576F28, 0x28, 3, "模型引用（WG 实测 0x28）", (".model",)),
    PrototypeType("PointLightPrototype", 0x0D3665A4, 0x70, 4, "点光源（WG 独有）", (".point_light",)),
    PrototypeType("EffectPrototype", 0xEB23E0AF, 0x10, 5, "粒子效果"),
    PrototypeType("VelocityFieldPrototype", 0xAFD4A63F, 0x18, 6, "速度场（WG 独有）", (".velocity_field",)),
    PrototypeType("EffectPresetPrototype", 0x42E15336, 0x10, 7, "粒子预设", (".effect_preset", ".xml")),
    PrototypeType("EffectMetadataPrototype", 0xDFC8F8E0, 0x10, 8, "粒子元数据"),
    PrototypeType("AtlasContourProto", 0xF64359AA, 0x10, 9, "图集轮廓", (".contours",)),
)

# ── 服务器上下文（thread-local；AssetsBinService 构造时 set_wows_type）─────
_DEFAULT_WOWS_TYPE = "Lesta"
_local = threading.local()

#: 类型表缓存（按服务器名）
_TABLE_CACHE: Dict[str, Tuple[PrototypeType, ...]] = {
    "Lesta": KORABLI_TYPES,
    "Wargaming": WG_TYPES,
}
_MAGIC_CACHE: Dict[str, Dict[int, PrototypeType]] = {}
_NAME_CACHE: Dict[str, Dict[str, PrototypeType]] = {}


def set_wows_type(wows_type: str) -> None:
    """设置当前线程的服务器类型表（'Wargaming'→WG_TYPES，其余→KORABLI_TYPES）。

    ⚠️ 必须在解析 assets.bin / 查表**之前**调用（AssetsBinService 构造时自动设置）。
    """
    _local.wows_type = "Wargaming" if wows_type == "Wargaming" else "Lesta"


def get_wows_type() -> str:
    return getattr(_local, "wows_type", _DEFAULT_WOWS_TYPE)


def _type_table(wows_type: Optional[str] = None) -> Tuple[PrototypeType, ...]:
    w = wows_type or get_wows_type()
    return _TABLE_CACHE.get(w, KORABLI_TYPES)


def _magic_index(wows_type: Optional[str] = None) -> Dict[int, PrototypeType]:
    w = wows_type or get_wows_type()
    idx = _MAGIC_CACHE.get(w)
    if idx is None:
        idx = {t.magic: t for t in _type_table(w)}
        _MAGIC_CACHE[w] = idx
    return idx


def _name_index(wows_type: Optional[str] = None) -> Dict[str, PrototypeType]:
    w = wows_type or get_wows_type()
    idx = _NAME_CACHE.get(w)
    if idx is None:
        idx = {t.name: t for t in _type_table(w)}
        _NAME_CACHE[w] = idx
    return idx


def type_from_magic(magic: int, wows_type: Optional[str] = None) -> Optional[PrototypeType]:
    """按 magic 识别 prototype 类型（按服务器表）。"""
    return _magic_index(wows_type).get(magic)


def type_from_blob_index(index: int, wows_type: Optional[str] = None) -> Optional[PrototypeType]:
    """按 blob index 识别类型（仅作为 fallback，优先用 magic）。"""
    for t in _type_table(wows_type):
        if t.blob_index == index:
            return t
    return None


def type_from_name(name: str, wows_type: Optional[str] = None) -> Optional[PrototypeType]:
    """按类型名字符串识别（不区分大小写，支持去掉 Prototype 后缀）。"""
    if not name:
        return None
    t = _name_index(wows_type).get(name)
    if t is not None:
        return t
    for t in _type_table(wows_type):
        if t.name.lower() == name.lower():
            return t
    for t in _type_table(wows_type):
        base = t.name.replace("Prototype", "").replace("Proto", "")
        if base.lower() == name.lower():
            return t
    return None


def can_decode(proto_type: Optional[PrototypeType]) -> bool:
    """该类型是否有结构化解码器（对齐 wows-toolkit `can_decode_prototype`）。"""
    return proto_type is not None and proto_type.name in _decodable_types()


def _decodable_types() -> frozenset:
    """按服务器返回可结构化解码的类型集合（decoders.py decode_by_type 精确处理）。"""
    if get_wows_type() == "Wargaming":
        # WG 无 Skeleton/Trail/VfxMaterial/MiscSettings；Material/Visual/Model/Effect/SkeletonExtender 有解码器
        return frozenset({
            "MaterialPrototype", "VisualPrototype", "ModelPrototype",
            "EffectPrototype", "SkeletonExtenderPrototype",
        })
    return frozenset({
        "MaterialPrototype", "SkeletonPrototype", "VisualPrototype", "ModelPrototype",
        "MiscSettingsPrototype", "TrailPrototype", "VfxMaterialPrototype",
        "EffectPrototype",
    })


def list_types(wows_type: Optional[str] = None) -> List[PrototypeType]:
    """按 blob index 排序返回全部类型表（当前服务器）。"""
    return sorted(_type_table(wows_type), key=lambda t: t.blob_index)


def item_size_for_blob(index: int, magic: Optional[int] = None,
                       wows_type: Optional[str] = None) -> int:
    """返回某 blob 的记录步长。优先按 magic，其次按 index，未知时用 0x10。"""
    if magic is not None:
        t = type_from_magic(magic, wows_type)
        if t is not None:
            return t.item_size
    t = type_from_blob_index(index, wows_type)
    if t is not None:
        return t.item_size
    return 0x10


def default_item_sizes(wows_type: Optional[str] = None) -> dict:
    """各 blob 的默认 item_size（供 CLI/工具快速查表；当前服务器）。"""
    return {t.blob_index: t.item_size for t in _type_table(wows_type)}
