"""
collision_materials.py —— 碰撞材质名表、装甲厚度颜色映射、命中区域分类。

数据来源：landaire/wows-toolkit `game_params/ttx/armor_materials.rs` 与
`export/gltf_export.rs`（从游戏客户端 py_collisionMaterialName 表逆向）。

- `collision_material_name(id)`：材质 ID → 名称（未收录的 ID 回退 "mat_{id}"）
- `thickness_to_color(mm)`：厚度 → RGBA（游戏 ArmorConstants.py 的 10 色桶）
- `zone_from_material_name(name)`：材质名 → 命中区域分类
"""

from __future__ import annotations


# ────────────────────────────────────────────────────────────────────────────
# 碰撞材质名表（0-254，部分收录；未收录 ID 回退 mat_{id}）
# ────────────────────────────────────────────────────────────────────────────
COLLISION_MATERIAL_NAMES: dict[int, str] = {
    # 0-1 通用
    0: "common",
    1: "zero",
    # 2-31 Dual 分区边界 + Bottom
    2: "Dual_SSC_Bow_Side",
    3: "Dual_SSC_St_Side",
    4: "Dual_Cas_OCit_Belt",
    5: "Dual_OCit_St_Trans",
    6: "Dual_OCit_Bow_Trans",
    7: "Dual_Cit_Bow_Side",
    8: "Dual_Cit_Bow_Belt",
    9: "Dual_Cit_Bow_ArtSide",
    10: "Dual_Cit_St_Side",
    11: "Dual_Cit_St_Belt",
    12: "Bottom",
    13: "Dual_Cit_St_ArtSide",
    14: "Dual_Cas_Bow_Belt",
    15: "Dual_Cas_St_Belt",
    16: "Dual_Cas_SSC_Belt",
    17: "Dual_SSC_Bow_ConstrSide",
    18: "Dual_SSC_St_ConstrSide",
    19: "Cas_Inclin",
    20: "SSC_Inclin",
    21: "Dual_Cas_SSC_Inclin",
    22: "Dual_Cas_Bow_Inclin",
    23: "Dual_Cas_St_Inclin",
    24: "Dual_SSC_Bow_Inclin",
    25: "Dual_SSC_St_Inclin",
    26: "Dual_Cit_Bow_Bulge",
    27: "Dual_Cit_St_Bulge",
    28: "Dual_Cas_SS_Belt",
    29: "Dual_Cit_Cas_ArtDeck",
    30: "Dual_Cit_Cas_ArtSide",
    31: "Dual_OCit_OCit_Side",
    # 32-45 炮塔/火炮组件
    32: "TurretSide",
    33: "TurretTop",
    # 46-51 船首
    46: "Bow_Bottom",
    47: "Bow_Plating",
    48: "Bow_Side",
    49: "Bow_Deck",
    50: "Bow_Inclin",
    51: "Bow_Trans",
    # 52-54 舰桥
    52: "BridgeBottom",
    53: "BridgeSide",
    54: "BridgeTop",
    # 55-58 舷侧副炮区
    55: "Cas_AftTrans",
    56: "Cas_Belt",
    57: "Cas_Deck",
    58: "Cas_FwdTrans",
    # 59-67 核心区
    59: "Cit_AftTrans",
    60: "Cit_Barbette",
    61: "Cit_Belt",
    62: "Cit_Bottom",
    63: "Cit_Bulge",
    64: "Cit_Deck",
    65: "Cit_FwdTrans",
    66: "Cit_Inclin",
    67: "Cit_Side",
    # 68-70
    68: "Dual_Cit_Cas_Bulge",
    69: "ConstrSide",
    70: "Dual_Cit_Cas_Belt",
    # 71-79 船体杂项
    71: "Bow_Fdck",
    72: "St_Fdck",
    73: "KdpBottom",
    74: "KdpSide",
    75: "KdpTop",
    76: "OCit_AftTrans",
    77: "OCit_Belt",
    78: "OCit_Deck",
    79: "OCit_FwdTrans",
    # 80-83 舵
    80: "RudderAft",
    81: "RudderFwd",
    82: "RudderSide",
    # 97-106 通用炮塔/船体
    97: "TurretBarbette",
    98: "TurretTop",
    99: "TurretDown",
    100: "TurretFwd",
    101: "Bulge",
    102: "Trans",
    103: "Deck",
    104: "Belt",
    105: "Dual_Cit_SSC_Bulge",
    106: "Inclin",
    # 107-110
    107: "SS_BridgeTop",
    108: "SS_BridgeSide",
    109: "SS_BridgeBottom",
    110: "Cas_Bottom",
    # 111-133 区域子面
    111: "SideCit",
    112: "DeckCit",
    113: "TransCit",
    114: "InclinCit",
    115: "SideCas",
    116: "DeckCas",
    117: "TransCas",
    118: "InclinCas",
    119: "SideSSC",
    120: "DeckSSC",
    121: "TransSSC",
    122: "InclinSSC",
    123: "SideBow",
    124: "DeckBow",
    125: "TransBow",
    126: "InclinBow",
    127: "SideSt",
    128: "DeckSt",
    129: "TransSt",
    130: "InclinSt",
    131: "SideSS",
    132: "DeckSS",
    133: "TransSS",
    # 134-153 炮座
    134: "Tur1GkBar",
    135: "Tur2GkBar",
    136: "Tur3GkBar",
    137: "Tur4GkBar",
    138: "Tur5GkBar",
    139: "Tur6GkBar",
    140: "Tur7GkBar",
    141: "Tur8GkBar",
    142: "Tur9GkBar",
    143: "Tur10GkBar",
    144: "Tur11GkBar",
    145: "Tur12GkBar",
    146: "Tur13GkBar",
    147: "Tur14GkBar",
    148: "Tur15GkBar",
    149: "Tur16GkBar",
    150: "Tur17GkBar",
    151: "Tur18GkBar",
    152: "Tur19GkBar",
    153: "Tur20GkBar",
    # 174-193 炮塔底部
    174: "Tur1GkDown",
    175: "Tur2GkDown",
    176: "Tur3GkDown",
    177: "Tur4GkDown",
    178: "Tur5GkDown",
    179: "Tur6GkDown",
    180: "Tur7GkDown",
    181: "Tur8GkDown",
    182: "Tur9GkDown",
    183: "Tur10GkDown",
    184: "Tur11GkDown",
    185: "Tur12GkDown",
    186: "Tur13GkDown",
    187: "Tur14GkDown",
    188: "Tur15GkDown",
    189: "Tur16GkDown",
    190: "Tur17GkDown",
    191: "Tur18GkDown",
    192: "Tur19GkDown",
    193: "Tur20GkDown",
    # 194-213 Dual 同区/跨区
    194: "Dual_Cit_Cit_Deck",
    195: "Dual_Cit_Cit_Inclin",
    196: "Dual_Cit_Cit_Trans",
    197: "Dual_Cit_Cit_Side",
    198: "Dual_Cas_Cas_Belt",
    199: "Dual_Cas_Cas_Deck",
    200: "Dual_SSC_SSC_ConstrSide",
    201: "Dual_SSC_SSC_Deck",
    202: "Dual_Bow_Bow_Deck",
    203: "Dual_Bow_Bow_ConstrSide",
    204: "Dual_St_St_Deck",
    205: "Dual_St_St_ConstrSide",
    206: "Dual_SS_SS_Top",
    207: "Dual_SS_SS_Side",
    208: "Dual_Cit_Bow_ArtDeck",
    209: "Dual_Cit_St_ArtDeck",
    210: "Dual_Cas_Bow_Side",
    # 214-233 炮塔顶部
    214: "Tur1GkTop",
    215: "Tur2GkTop",
    216: "Tur3GkTop",
    217: "Tur4GkTop",
    218: "Tur5GkTop",
    219: "Tur6GkTop",
    220: "Tur7GkTop",
    221: "Tur8GkTop",
    222: "Tur9GkTop",
    223: "Tur10GkTop",
    224: "Tur11GkTop",
    225: "Tur12GkTop",
    226: "Tur13GkTop",
    227: "Tur14GkTop",
    228: "Tur15GkTop",
    229: "Tur16GkTop",
    230: "Tur17GkTop",
    231: "Tur18GkTop",
    232: "Tur19GkTop",
    233: "Tur20GkTop",
    # 234-241 机库/前桅
    234: "Cas_Hang",
    235: "Cas_Fdck",
    236: "SSC_Fdck",
    237: "SSC_Hang",
    238: "SS_SGBarbette",
    239: "SS_SGDown",
    240: "SGBarbetteSS",
    241: "SGDownSS",
    # 242-254 Dual 核心区过渡
    242: "Dual_Cit_Cas_Deck",
    243: "Dual_Cit_Cas_Inclin",
    244: "Dual_Cit_Cas_Trans",
    245: "Dual_Cit_SSC_Deck",
    246: "Dual_Cit_SSC_Inclin",
    247: "Dual_Cit_SSC_Trans",
    248: "Dual_Cit_Bow_Trans",
    249: "Dual_Cit_Bow_Inclin",
    250: "Dual_Cit_Bow_Deck",
    251: "Dual_Cit_St_Trans",
    252: "Dual_Cit_St_Inclin",
    253: "Dual_Cit_St_Deck",
    254: "Dual_Cit_SS_Deck",
}


def collision_material_name(material_id: int) -> str:
    return COLLISION_MATERIAL_NAMES.get(material_id, f"mat_{material_id}")


# ────────────────────────────────────────────────────────────────────────────
# 装甲厚度 → 颜色（游戏 ArmorConstants.py 的 10 色桶，alpha=0.8）
# ────────────────────────────────────────────────────────────────────────────
#: (max_thickness_mm, r, g, b)；厚度 ≤ breakpoint 命中该色桶
ARMOR_COLOR_SCALE: list[tuple[float, float, float, float]] = [
    (14.0, 110.0 / 255.0, 209.0 / 255.0, 176.0 / 255.0),   # teal
    (16.0, 149.0 / 255.0, 210.0 / 255.0, 127.0 / 255.0),   # light green
    (24.0, 170.0 / 255.0, 201.0 / 255.0, 102.0 / 255.0),   # yellow-green
    (26.0, 192.0 / 255.0, 193.0 / 255.0, 80.0 / 255.0),    # olive
    (28.0, 226.0 / 255.0, 195.0 / 255.0, 62.0 / 255.0),    # gold
    (33.0, 225.0 / 255.0, 171.0 / 255.0, 54.0 / 255.0),    # orange-gold
    (75.0, 227.0 / 255.0, 144.0 / 255.0, 49.0 / 255.0),    # orange
    (160.0, 230.0 / 255.0, 115.0 / 255.0, 49.0 / 255.0),   # dark orange
    (399.0, 220.0 / 255.0, 78.0 / 255.0, 48.0 / 255.0),    # red-orange
    (999.0, 185.0 / 255.0, 47.0 / 255.0, 48.0 / 255.0),    # dark red
]

#: 色桶名称（图例用）
ARMOR_COLOR_NAMES: list[str] = [
    "蓝绿", "浅绿", "黄绿", "橄榄", "金黄", "橙金", "橙色", "深橙", "橙红", "深红",
]

#: 未知厚度（≤0）颜色
ARMOR_UNKNOWN_COLOR = (0.8, 0.8, 0.8, 0.5)


def thickness_to_color(thickness_mm: float) -> tuple[float, float, float, float]:
    """厚度（mm）→ RGBA，匹配游戏内装甲查看器配色。"""
    if thickness_mm <= 0.0:
        return ARMOR_UNKNOWN_COLOR
    for bp, r, g, b in ARMOR_COLOR_SCALE:
        if thickness_mm <= bp:
            return (r, g, b, 0.8)
    _bp, r, g, b = ARMOR_COLOR_SCALE[-1]
    return (r, g, b, 0.8)


# ────────────────────────────────────────────────────────────────────────────
# 装甲类型（归属）分类 —— 反编译自游戏 ArmorConstants.pyc 的 ARMOR_TYPES + getArmorType
# ────────────────────────────────────────────────────────────────────────────
#: 材质前缀 → 装甲类型（与游戏 ArmorConstants.ARMOR_TYPES 一致，顺序即 TYPE_ORDER）
ARMOR_TYPE_PREFIXES: dict[str, tuple[str, ...]] = {
    "CITADEL": ("Cit",),                                        # 核心区
    "ARTI": ("AuTurret", "Turret", "Tur", "SGBarbetteSS", "SGDownSS"),  # 炮塔
    "CAS": ("Cas",),                                            # 舷侧副炮区
    "UPCAS": ("SSC",),                                          # 上层
    "SS": ("SS",),                                              # 上层建筑
    "OUTER": ("Bulge", "Belt", "Bottom", "OCit"),               # 舷侧/水下
    "BOW_ST": ("Bow", "St"),                                    # 艏艉
    "INNER": ("ConstrSide", "Trans", "Deck", "Rudder", "Art",
              "Inclin", "Bridge", "Hang"),                      # 内部
}

#: 装甲类型显示名（图例/筛选用）
ARMOR_TYPE_NAMES: dict[str, str] = {
    "CITADEL": "核心区",
    "ARTI": "炮塔",
    "CAS": "舷侧副炮区",
    "UPCAS": "上层",
    "SS": "上层建筑",
    "OUTER": "舷侧水下",
    "BOW_ST": "艏艉",
    "INNER": "内部",
}

#: 装甲类型顺序（图例/筛选排序，对应游戏 TYPE_ORDER）
ARMOR_TYPE_ORDER: list[str] = [
    "CITADEL", "ARTI", "CAS", "UPCAS", "SS", "OUTER", "BOW_ST", "INNER",
]


def get_armor_types(mat_name: str) -> frozenset[str]:
    """材质名 → 归属装甲类型集合（游戏 ArmorConstants.getArmorType）。

    - 非 `Dual_`：用完整材质名前缀匹配各类型的 prefix 元组
    - `Dual_X_Y_*`：对 `_` 分隔的第 1、2 段分别匹配（可命中多个类型）
    返回 frozenset（空 = 无归属类型）。
    """
    if not mat_name:
        return frozenset()
    if mat_name.startswith("Dual"):
        candidates = mat_name.split("_")[1:3]
    else:
        candidates = [mat_name]
    result: set[str] = set()
    for candidate in candidates:
        for atype, prefixes in ARMOR_TYPE_PREFIXES.items():
            if any(candidate.startswith(p) for p in prefixes):
                result.add(atype)
    return frozenset(result)


def armor_type_display(atype: str) -> str:
    return ARMOR_TYPE_NAMES.get(atype, atype)


# ────────────────────────────────────────────────────────────────────────────
# 命中区域分类
# ────────────────────────────────────────────────────────────────────────────
def zone_from_material_name(mat_name: str) -> str:
    """材质名 → 命中区域（与 wows-toolkit zone_from_material_name 语义一致）。"""
    if not mat_name:
        return "Default"
    if mat_name.startswith("Dual_"):
        rest = mat_name[5:]
        for prefix, zone in (
            ("Cit", "Citadel"), ("OCit", "Citadel"), ("Cas", "Casemate"),
            ("SSC", "Superstructure"), ("Bow", "Bow"), ("St_", "Stern"),
            ("SS_", "Superstructure"),
        ):
            if rest.startswith(prefix):
                return zone
        return "Other"
    if mat_name.endswith("Cit"):
        return "Citadel"
    if mat_name.endswith("Cas"):
        return "Casemate"
    if mat_name.endswith("SSC"):
        return "Superstructure"
    if mat_name.endswith("Bow"):
        return "Bow"
    if mat_name.endswith("Stern") or mat_name.startswith("St_"):
        return "Stern"
    if mat_name.endswith("SS") and not mat_name.startswith("SG"):
        return "Superstructure"
    if mat_name.startswith("Bow"):
        return "Bow"
    if mat_name.startswith("Cit") or mat_name.startswith("OCit"):
        return "Citadel"
    if mat_name.startswith("Cas"):
        return "Casemate"
    if mat_name.startswith("SSC") or mat_name.startswith("SS_"):
        return "Superstructure"
    if mat_name.startswith("Tur") or mat_name.startswith("AuTurret") or mat_name.startswith("Art"):
        return "Turret"
    if mat_name.startswith("Rudder") or mat_name.startswith("SG"):
        return "SteeringGear"
    if mat_name.startswith("Bulge"):
        return "TorpedoProtection"
    if mat_name.startswith("Kdp"):
        return "Hull"
    if mat_name in ("Deck", "ConstrSide", "Hull", "Side", "Bottom", "Top", "Belt", "Trans", "Inclin"):
        return "Hull"
    return "Other"
