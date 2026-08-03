"""Korabli（Lesta 服）assets.bin 的 Prototype 类型表。

⚠️ 依据 2026-08-01 实测匹配（MurmurHash3_x86_32），
Korabli 有 **12** 个类型（WoWS 只有 10 个），且 blob index → 类型映射与
WoWS 完全不同。**必须按 magic 识别类型，不能按 index 套用 WoWS 表。**
"""

from __future__ import annotations

from typing import Optional, Tuple


class PrototypeType:
    """一种 prototype 类型（按 magic 唯一标识）。"""

    __slots__ = ("name", "magic", "item_size", "blob_index", "description")

    def __init__(self, name: str, magic: int, item_size: int, blob_index: int, description: str = ""):
        self.name = name
        self.magic = magic
        self.item_size = item_size
        self.blob_index = blob_index
        self.description = description

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PrototypeType {self.name} magic=0x{self.magic:08X} item=0x{self.item_size:X}>"


# ── Korabli 实测类型表（12 个，blob index 顺序为 Korabli 实测）──────────────

KORABLI_TYPES: Tuple[PrototypeType, ...] = (
    # 实测 0x88（2026-08-03，Korabli 正式服 assets.bin）：
    # 字段 8 字节对齐，names_ptr@+0x18，与 WoWS 的 0x78 不同。
    PrototypeType("MaterialPrototype", 0x5069C471, 0x88, 0, "材质属性表（Korabli 实测 0x88）"),
    PrototypeType("SkeletonPrototype", 0xD9BB9F4A, 0x40, 1, "Lesta 骨架系统（Korabli 独有）"),
    # Visual/Model 步长均为 2026-08-03 Korabli 正式服实测（与 WoWS 0x70/0x28 不同）
    PrototypeType("VisualPrototype", 0x480DC57B, 0x80, 2, "渲染集合（Korabli 实测 0x80，布局待完整逆向）"),
    PrototypeType("ModelPrototype", 0xA9576F28, 0x20, 3, "模型引用（Korabli 实测 0x20，布局待完整逆向）"),
    PrototypeType("ModelFbxPrototype", 0xDF80CF54, 0x10, 4, "FBX 模型（Korabli 独有，空 blob）"),
    PrototypeType("EffectPrototype", 0xEB23E0AF, 0x10, 5, "粒子效果"),
    PrototypeType("EffectPresetPrototype", 0x42E15336, 0x10, 6, "粒子预设"),
    PrototypeType("EffectMetadataPrototype", 0xDFC8F8E0, 0x10, 7, "粒子元数据"),
    PrototypeType("AtlasContourProto", 0xF64359AA, 0x10, 8, "图集轮廓"),
    PrototypeType("MiscSettingsPrototype", 0xACE328C6, 0x28, 9, "杂项设置（Korabli 独有）"),
    PrototypeType("TrailPrototype", 0x42AF895E, 0x1A0, 10, "粒子轨迹（Korabli 独有）"),
    PrototypeType("VfxMaterialPrototype", 0xCD880533, 0x210, 11, "VFX 材质（Korabli 独有）"),
)

# magic → PrototypeType
_MAGIC_INDEX = {t.magic: t for t in KORABLI_TYPES}


def type_from_magic(magic: int) -> Optional[PrototypeType]:
    """按 magic 识别 prototype 类型（Korabli 规则）。"""
    return _MAGIC_INDEX.get(magic)


def type_from_blob_index(index: int) -> Optional[PrototypeType]:
    """按 blob index 识别类型（仅作为 fallback，优先用 magic）。"""
    for t in KORABLI_TYPES:
        if t.blob_index == index:
            return t
    return None


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
