"""Korabli（Lesta 服）assets.bin 的 Prototype 类型表。

⚠️ 依据 2026-08-01 逆向（Korabli64.exe 字符串 + MurmurHash3_x86_32 匹配），
Korabli 有 **12** 个类型（WoWS 只有 10 个），且 blob index → 类型映射与
WoWS 完全不同。**必须按 magic 识别类型，不能按 index 套用 WoWS 表。**
"""

from __future__ import annotations

from typing import List, Optional, Tuple


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

# magic → PrototypeType
_MAGIC_INDEX = {t.magic: t for t in KORABLI_TYPES}
_NAME_INDEX = {t.name: t for t in KORABLI_TYPES}

#: 有结构化解码器的类型（decoders.py 中 decode_by_type 精确处理，非 generic 兜底）
DECODABLE_TYPES = frozenset({
    "MaterialPrototype", "SkeletonPrototype", "VisualPrototype", "ModelPrototype",
    "MiscSettingsPrototype", "TrailPrototype", "VfxMaterialPrototype",
    "EffectPrototype",
})


def type_from_magic(magic: int) -> Optional[PrototypeType]:
    """按 magic 识别 prototype 类型（Korabli 规则）。"""
    return _MAGIC_INDEX.get(magic)


def type_from_blob_index(index: int) -> Optional[PrototypeType]:
    """按 blob index 识别类型（仅作为 fallback，优先用 magic）。"""
    for t in KORABLI_TYPES:
        if t.blob_index == index:
            return t
    return None


def type_from_name(name: str) -> Optional[PrototypeType]:
    """按类型名字符串识别（不区分大小写，支持去掉 Prototype 后缀）。"""
    if not name:
        return None
    t = _NAME_INDEX.get(name)
    if t is not None:
        return t
    for t in KORABLI_TYPES:
        if t.name.lower() == name.lower():
            return t
    for t in KORABLI_TYPES:
        base = t.name.replace("Prototype", "").replace("Proto", "")
        if base.lower() == name.lower():
            return t
    return None


def can_decode(proto_type: Optional[PrototypeType]) -> bool:
    """该类型是否有结构化解码器（对齐 wows-toolkit `can_decode_prototype`）。"""
    return proto_type is not None and proto_type.name in DECODABLE_TYPES


def list_types() -> List[PrototypeType]:
    """按 blob index 排序返回全部类型表。"""
    return sorted(KORABLI_TYPES, key=lambda t: t.blob_index)


def item_size_for_blob(index: int, magic: Optional[int] = None) -> int:
    """返回某 blob 的记录步长。优先按 magic，其次按 index，未知时用 0x10。"""
    if magic is not None:
        t = type_from_magic(magic)
        if t is not None:
            return t.item_size
    t = type_from_blob_index(index)
    if t is not None:
        return t.item_size
    return 0x10


def default_item_sizes() -> dict:
    """Korabli 各 blob 的默认 item_size（供 CLI/工具快速查表）。"""
    return {t.blob_index: t.item_size for t in KORABLI_TYPES}
