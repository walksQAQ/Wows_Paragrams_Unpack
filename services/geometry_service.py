"""
geometry_service.py —— 舰船 3D 几何与装甲提取服务。

职责：
  1. 发现舰船（GameParams 键、model 路径、装甲厚度字典、显示名）——DB-first：
     优先主库 ship_models/entity_snapshots 表；data/split JSON 仅作旧库回退
  2. 用 data_extractor.GameExtractor 从游戏客户端读取该舰所有 .geometry 部件文件
  3. 解析并合并为可直接上传 GPU 的 HullMesh / ArmorMesh / 碰撞模型

内存约定：逐文件读取→解析→合并，随即释放原始 bytes；大船（数十万顶点）
总占用控制在合理范围（遵守 2GB 红线）。后台线程中调用，通过 progress_cb 汇报。
"""

from __future__ import annotations

import re
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.application import app as app_ctx
from app.signals import bus
from models.geometry_parser import parse_geometry, ArmorModel, GeometryError
from models.collision_materials import collision_material_name, thickness_to_color
from services.fx_mapping import tech_family as fx_tech_family
from utils.threading_utils import TaskCancelled


@dataclass
class ShipInfo:
    """发现到的舰船（用于舰船列表下拉框）。"""
    game_key: str          # GameParams 键，如 "PFSB510_Bourgogne"
    display_name: str      # 本地化名称，如 "勃艮第"
    model_folder: str      # 几何文件夹名，如 "FSB025_Bourgogne_1945"
    model_path: str        # 完整 model VFS 路径
    nation: str = ""
    ship_type: str = ""
    has_geometry: bool = False


#: 模型部件归属（component / 归属分类，用于挂载与装甲按归属筛选显示）
COMPONENT_HULL = "船体"
COMPONENT_MAIN = "主炮塔"
COMPONENT_SECONDARY = "副炮塔"
COMPONENT_TORPEDOES = "鱼雷发射管"
COMPONENT_DEPTH_CHARGE = "深弹发射器"
COMPONENT_AA = "防空"
COMPONENT_DIRECTOR = "指挥仪"
COMPONENT_FINDER = "测距仪"
COMPONENT_RADAR = "雷达"
COMPONENT_DECK = "甲板设备"
COMPONENT_OTHER = "其他"

#: 游戏内装甲查看器隐藏的「通用 Hull 材质」集合（wows-toolkit hidden 语义）：
#: 原本借鉴 wows-toolkit 把 Hull 区通用材质（Trans/Deck/Belt 等）标记为隐藏，
#: 但这些板有真实厚度数据，在我们的查看器中应默认显示。清空该集合即可。
HIDDEN_GENERIC_MATERIALS: set[str] = set()


def _is_magenta_placeholder(dds_bytes: bytes, sample: int = 256) -> bool:
    """检测贴图是否为「洋红占位纹理」（缺失贴图常用纯色洋红，BC7 全 mode0）。

    只抽前若干 BC7 块解码颜色端点求平均色；平均 RGB 偏洋红(R>180,G<110,B>90)
    即视为占位。非 BC7 / 解析失败返回 False（不误判正常 camo）。
    实例图集(CIA000_instances_atlas_art)实测全 mode0 纯洋红 (238,51,127)。
    """
    try:
        from models.dds_reader import parse_dds
        dds = parse_dds(dds_bytes)
        if dds.bc_kind != 8 or not dds.mips:
            return False
        mip0 = dds.mips[0]
        w, h = dds.width, dds.height
        nblocks = (w // 4) * (h // 4)
        if nblocks == 0:
            return False

        def _unpack(b: bytes, off: int, n: int) -> int:
            v = 0
            for i in range(n):
                bit = (off + i) // 8
                biti = (off + i) % 8
                if bit < len(b):
                    v |= ((b[bit] >> biti) & 1) << i
            return v

        def _ep(b: bytes, offs) -> list:
            """按 (off, bits) 解码 3 通道端点色，返回 0~255 值。"""
            out = []
            for off, bits in offs:
                v = _unpack(b, off, bits)
                out.append(v / ((1 << bits) - 1) * 255.0)
            return out

        total = [0.0, 0.0, 0.0]
        cnt = 0
        stride = max(1, nblocks // sample)
        for bi in range(0, nblocks, stride):
            if cnt >= sample:
                break
            blk = mip0[bi * 16: bi * 16 + 16]
            if len(blk) < 16:
                break
            m = 0
            for k in range(8):
                if (blk[0] >> (7 - k)) & 1:
                    m += 1
                else:
                    break
            if m == 0:
                p0 = _ep(blk, [(7, 4), (11, 4), (15, 4)])
                p1 = _ep(blk, [(22, 4), (26, 4), (30, 4)])
            elif m == 1:
                p0 = _ep(blk, [(8, 6), (14, 6), (20, 6)])
                p1 = _ep(blk, [(50, 6), (56, 6), (62, 6)])
            elif m == 2:
                p0 = _ep(blk, [(8, 5), (17, 5), (26, 5)])
                p1 = _ep(blk, [(56, 5), (65, 5), (74, 5)])
            elif m == 3:
                p0 = _ep(blk, [(8, 7), (15, 7), (22, 7)])
                p1 = _ep(blk, [(50, 7), (57, 7), (64, 7)])
            elif m == 4:
                p0 = _ep(blk, [(8, 5), (19, 5), (30, 5)])
                p1 = _ep(blk, [(49, 5), (60, 5), (71, 5)])
            elif m == 5:
                p0 = _ep(blk, [(8, 7), (15, 7), (22, 7)])
                p1 = _ep(blk, [(49, 7), (56, 7), (63, 7)])
            elif m == 6:
                p0 = _ep(blk, [(8, 7), (15, 7), (22, 7)])
                p1 = _ep(blk, [(43, 7), (50, 7), (57, 7)])
            elif m == 7:
                p0 = _ep(blk, [(8, 5), (17, 5), (26, 5)])
                p1 = _ep(blk, [(56, 5), (65, 5), (74, 5)])
            else:
                continue
            total[0] += (p0[0] + p1[0]) * 0.5
            total[1] += (p0[1] + p1[1]) * 0.5
            total[2] += (p0[2] + p1[2]) * 0.5
            cnt += 1
        if cnt == 0:
            return False
        r, g, b = total[0] / cnt, total[1] / cnt, total[2] / cnt
        return r > 180.0 and g < 110.0 and b > 90.0
    except Exception:
        return False

#: GameParams 组件键 → 归属分类（按 base 组件名匹配任意前缀变体）
#: 键格式 {PREFIX}_{BASE}，如 AB1_Artillery / B_AirDefense / A1_Torpedoes
_COMPONENT_BY_BASE = {
    "Artillery": COMPONENT_MAIN,            # 主炮塔（A1_/AB1_/B_/C_/X_... 前缀）
    "ATBA": COMPONENT_SECONDARY,            # 副炮（A_/B_...）
    "SecondaryArtillery": COMPONENT_MAIN,
    "AirDefense": COMPONENT_AA,             # 防空（A_/B_...）
    "AirSupport": COMPONENT_OTHER,
    "Directors": COMPONENT_DIRECTOR,        # 指挥仪（A_/AB_...）
    "Finders": COMPONENT_FINDER,            # 测距仪（A_/AB_...）
    "Radars": COMPONENT_RADAR,              # 雷达（A_/AB_...）
    "AirArmament": COMPONENT_OTHER,         # 弹射器（HP_JC_*）
    "Torpedoes": COMPONENT_TORPEDOES,        # 鱼雷发射管（HP_*GT_*）
    "DepthChargeGuns": COMPONENT_DEPTH_CHARGE,  # 深水炸弹炮塔（HP_*GB_*）
}


def _component_base(comp_key: str) -> str:
    """组件键的 base 组件名：`AB1_Artillery` → `Artillery`。"""
    if not comp_key:
        return ""
    return comp_key.split("_", 1)[1] if "_" in comp_key else comp_key


def component_for_key(comp_key: str) -> str:
    """GameParams 组件键 → 归属分类（未知键归"其他"）。

    键格式 {PREFIX}_{BASE}，BASE 匹配任意前缀变体（A1_/AB_/B_/C_/X_...），
    避免固定键列表遗漏合法变体（如 PGSB207 的 AB1_Artillery、AB_Directors、
    B_AirDefense、A1_Torpedoes 等）。
    """
    return _COMPONENT_BY_BASE.get(_component_base(comp_key), COMPONENT_OTHER)


def is_known_component_key(comp_key: str) -> bool:
    """组件键是否已被识别（按 base 组件名匹配任意前缀变体）。"""
    return _component_base(comp_key) in _COMPONENT_BY_BASE


def iter_component_groups(data: dict):
    """遍历快照中所有组件分组，产出 (component_key, category, group_dict)。

    不依赖固定键列表：按 base 组件名匹配任意前缀变体，其余归「其他」。
    或归「其他」。调用方据此加载挂载引用/装甲厚度，并可选告警未知组件。
    """
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        yield key, component_for_key(key), value


# ── MP 甲板设备节点 → misc 模型映射（纯命名约定，数据驱动校验 99.99% 命中）──
# MP_{baseID}_{desc}_{instance}[_INDEX_N] → 去 MP_ 前缀 → 首个「字母+数字」token
# 即 baseID；国家目录由 baseID 首字母决定；模型目录 = baseID（几何在
# content/gameplay/{nation}/misc/{baseID}/{baseID}.geometry，与 HP 挂载同一
# 目录索引/渲染集/贴图管线加载）。
_MP_NATION_BY_LETTER = {
    "A": "usa", "B": "uk", "C": "common", "F": "france", "G": "germany",
    "H": "netherlands", "I": "italy", "J": "japan", "R": "russia",
    "S": "spain", "U": "commonwealth", "V": "panamerica", "W": "europe",
    "X": "events", "Z": "panasia",
}
_MP_BASE_RE = re.compile(r"^([A-Z][A-Z0-9]*?\d+)")


def mp_base_id(mp_name: str) -> str:
    """MP 节点名 → baseID（模型目录名）；无法解析返回空串。

    例：MP_AM003_Fairlead_1 / MP_AM003_Fairlead_1_INDEX_2 → "AM003"
    """
    body = mp_name[3:] if mp_name.startswith("MP_") else mp_name
    m = _MP_BASE_RE.match(body)
    return m.group(1) if m else ""


def mp_nation(base_id: str) -> str:
    """baseID 首字母 → 国家目录名；未知返回空串。"""
    return _MP_NATION_BY_LETTER.get(base_id[:1], "") if base_id else ""


@dataclass
class HullMesh:
    """一个舰体部件网格（顶点/法线/UV/索引，已合并该部件全部 primitive）。

    若按材质拆分（不同模型使用不同贴图），material/texture_dds 记录该分片的
    材质与独立贴图；否则 material=None，使用舰体默认贴图。
    """
    name: str
    positions: np.ndarray          # (N,3) f32
    normals: np.ndarray            # (N,3) f32
    indices: np.ndarray            # (M,) u32
    vertex_count: int = 0
    uvs: np.ndarray | None = None  # (N,2) f32（贴图用）
    material: str | None = None    # 材质名（如 TL2_SHIPMAT_PBS_DeckHouse）
    texture_dds: bytes | None = None   # 该材质独立贴图（.mfm diffuseMap 或 INDEXED albedoArray）
    texture_path: str = ""
    #: 是否声明了颜色贴图（mfm 有 diffuseMap / indexed 有 albedoArray）。False=无色：
    #: 按透明/不参与颜色计算处理（如仅 normalMap 的贴花层），避免误渲成白色/串错贴图。
    has_color: bool = True
    tech_family: str = "pbs"           # shader 技术族：pbs(0x0005)/indexed(0x0009)/other
    material_textures: dict = field(default_factory=dict)  # {贴图键: (vfs_path, bytes)}
    indexed_params: dict | None = None  # INDEXED 分块参数 {arrays, grid, offset}
    #: emissive 自发光强度（mfm emissivePower 属性；None=默认 1.0）
    emissive_power: float | None = None
    opaque: bool = True                 # 半透明材质（玻璃等）用 alpha 混合
    is_wire: bool = False               # wire 线框辅助网格：用 GL_LINES 渲染（非实体面）
    #: crack/damage 损伤网格（查看器不显示，导出保留用）
    is_crack: bool = False
    #: bind pose 蒙皮已实际施加到顶点（Root_BlendBone 已烘焙进几何）；
    #: 挂载矩阵不得再乘 rb，否则双重镜像 → 朝向翻转（PASB111 副炮 AGS542 实证）
    skinned_applied: bool = False
    #: 蒙皮权重（GLB 导出 glTF skin 用；非蒙皮网格为 None）
    bone_indices: np.ndarray | None = None   # (N,4) uint8（调色板 slot × 3）
    bone_weights: np.ndarray | None = None   # (N,4) float32
    #: 蒙皮调色板骨骼名与 bind 世界矩阵（游戏空间），导出时转 glTF 空间
    skin_bones: list = field(default_factory=list)
    skin_bind: list = field(default_factory=list)
    #: 构成该网格的形状名（*.vertices 去后缀，如 BIA454_Bollard_bigShape）与
    #: 对应绑定的骨骼节点名（如 BIA454_Bollard_big_6）；调试模式 3 标签用。
    shape_names: list = field(default_factory=list)
    node_names: list = field(default_factory=list)
    #: 逐节点实例矩阵（渲染空间 4x4 行主序）；非空时该网格是一份原始几何，
    #: 渲染时按其每个矩阵各画一次（左右舷/多处实例，如切锯机 _0/_1）。
    instance_matrices: list = field(default_factory=list)


@dataclass
class MountMesh:
    """一个挂载实例（炮塔/副炮/防空/指挥仪等）。

    - 几何为该部件模型目录（本地坐标），经 model_matrix 变换到舰船空间
    - 每个部件使用自己的独立贴图（`{stem}_a.dd0` 等命名约定）
    - component 为归属分类（主炮塔/副炮/防空/...），支持按归属筛选显示
    """
    name: str                      # HP_JGM_1
    component: str                 # 归属分类
    positions: np.ndarray          # (N,3) f32 本地坐标
    normals: np.ndarray            # (N,3) f32
    indices: np.ndarray            # (M,) u32
    uvs: np.ndarray | None = None  # (N,2) f32
    model_matrix: np.ndarray | None = None  # (4,4) f32 行主序（渲染空间）
    texture_dds: bytes | None = None
    texture_path: str = ""
    model_folder: str = ""         # 来源模型目录
    vertex_count: int = 0
    is_wire: bool = False          # wire 线框辅助网格：GL_LINES 渲染
    #: 是否声明了颜色贴图（mfm 有 diffuseMap / indexed 有 albedoArray）。False=无色：
    #: 按透明/不参与颜色计算处理（如仅 normalMap 的贴花层）。
    has_color: bool = True
    tech_family: str = "pbs"      # shader 技术族：pbs/indexed/other/grid
    #: 材质贴图集 {贴图键: (vfs_path, bytes)}（INDEXED：albedoArray/materialIdMap/artMap）
    material_textures: dict = field(default_factory=dict)
    #: INDEXED 分块参数 {arrays, grid, offset}（炮塔等分块涂装）
    indexed_params: dict | None = None
    #: emissive 自发光强度（mfm emissivePower 属性；None=默认 1.0）
    emissive_power: float | None = None
    #: crack/damage 损伤网格（查看器不显示，导出保留用）
    is_crack: bool = False
    #: 蒙皮权重（GLB 导出 glTF skin 用；非蒙皮为 None）
    bone_indices: np.ndarray | None = None
    bone_weights: np.ndarray | None = None
    skin_bones: list = field(default_factory=list)
    skin_bind: list = field(default_factory=list)
    #: 构成该网格的形状名与绑定的骨骼节点名（调试模式 3 标签用）。
    shape_names: list = field(default_factory=list)
    node_names: list = field(default_factory=list)
    #: 逐节点实例矩阵（渲染空间 4x4 行主序）；非空时该网格是一份原始几何，
    #: 渲染时按其每个矩阵各画一次（挂载模型内的多处实例）。
    instance_matrices: list = field(default_factory=list)

    def bounds_in_world(self) -> tuple[np.ndarray, np.ndarray]:
        """本地包围盒经 model_matrix 变换后的世界包围盒。"""
        pts = np.empty((8, 3), dtype=np.float32)
        if self.model_matrix is not None:
            mn = self.positions.min(axis=0)
            mx = self.positions.max(axis=0)
            corners = np.array([
                [mn[0], mn[1], mn[2]], [mx[0], mn[1], mn[2]],
                [mn[0], mx[1], mn[2]], [mx[0], mx[1], mn[2]],
                [mn[0], mn[1], mx[2]], [mx[0], mn[1], mx[2]],
                [mn[0], mx[1], mx[2]], [mx[0], mx[1], mx[2]],
            ], dtype=np.float32)
            hom = np.hstack([corners, np.ones((8, 1), dtype=np.float32)])
            w = hom @ self.model_matrix.T
            return w[:, :3].min(axis=0), w[:, :3].max(axis=0)
        return self.positions.min(axis=0), self.positions.max(axis=0)


@dataclass
class ArmorTriangleInfo:
    material_id: int
    material_name: str
    layer_index: int
    thickness_mm: float
    color: tuple[float, float, float, float]
    zone: str
    #: 该材质所有非零层厚度（Dual 多层材质，升序；tooltip 展示堆叠）
    layers: list[float] = field(default_factory=list)
    #: 游戏内装甲查看器隐藏的板（Hull 区通用材质 Trans/Deck/Belt 等）
    hidden: bool = False
    #: 板块键 (zone, material_name, thickness_tenths)；高亮/显隐/描边判别
    plate_key: tuple = ()


@dataclass
class ArmorMesh:
    name: str
    positions: np.ndarray          # (N,3) f32（N = 三角形数×3）
    normals: np.ndarray            # (N,3) f32
    colors: np.ndarray             # (N,4) f32（每个三角形三顶点同色）
    indices: np.ndarray            # (M,) u32
    triangles: list[ArmorTriangleInfo] = field(default_factory=list)
    #: 归属分类（船体/主炮塔/副炮/防空/...），用于按归属筛选显示
    component: str = COMPONENT_HULL
    #: 舰船空间变换（挂载装甲需经挂点矩阵定位；舰体装甲为 None）
    model_matrix: np.ndarray | None = None

    def bounds_in_world(self) -> tuple[np.ndarray, np.ndarray]:
        """装甲本地包围盒经 model_matrix 变换后的世界包围盒（舰体装甲恒等）。"""
        pts = self.positions
        if self.model_matrix is not None and pts.size:
            corners = np.array([
                [pts[:, 0].min(), pts[:, 1].min(), pts[:, 2].min()],
                [pts[:, 0].max(), pts[:, 1].min(), pts[:, 2].min()],
                [pts[:, 0].min(), pts[:, 1].max(), pts[:, 2].min()],
                [pts[:, 0].max(), pts[:, 1].max(), pts[:, 2].min()],
                [pts[:, 0].min(), pts[:, 1].min(), pts[:, 2].max()],
                [pts[:, 0].max(), pts[:, 1].min(), pts[:, 2].max()],
                [pts[:, 0].min(), pts[:, 1].max(), pts[:, 2].max()],
                [pts[:, 0].max(), pts[:, 1].max(), pts[:, 2].max()],
            ], dtype=np.float32)
            hom = np.hstack([corners, np.ones((8, 1), dtype=np.float32)])
            w = hom @ self.model_matrix.T
            return w[:, :3].min(axis=0), w[:, :3].max(axis=0)
        if pts.size:
            return pts.min(axis=0), pts.max(axis=0)
        return np.zeros(3, dtype=np.float32), np.zeros(3, dtype=np.float32)


@dataclass
class CollisionModelData:
    name: str
    size_in_bytes: int
    data: bytes = b""


@dataclass
class ShipGeometry:
    game_key: str
    display_name: str
    model_folder: str
    hull_meshes: list[HullMesh] = field(default_factory=list)
    mounts: list[MountMesh] = field(default_factory=list)
    armor_meshes: list[ArmorMesh] = field(default_factory=list)
    collision_models: list[CollisionModelData] = field(default_factory=list)
    bounds_min: np.ndarray | None = None
    bounds_max: np.ndarray | None = None
    stats: dict = field(default_factory=dict)
    #: 舰体漫反射贴图（.dds 原始字节）与 VFS 路径（可能为 None，未找到贴图）
    texture_dds: bytes | None = None
    texture_path: str = ""

    @property
    def bounds_center(self) -> np.ndarray:
        if self.bounds_min is None or self.bounds_max is None:
            return np.zeros(3, dtype=np.float32)
        return (self.bounds_min + self.bounds_max) * 0.5

    @property
    def bounds_size(self) -> np.ndarray:
        if self.bounds_min is None or self.bounds_max is None:
            return np.ones(3, dtype=np.float32)
        return np.maximum(self.bounds_max - self.bounds_min, 1e-6)


# ────────────────────────────────────────────────────────────────────────────
# 舰船发现
# ────────────────────────────────────────────────────────────────────────────

class GeometryService:
    """舰船几何服务（单例用法：GeometryService.instance）。"""

    _instance: "GeometryService | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._ships: list[ShipInfo] | None = None
        self._ships_error: str | None = None
        self._extractor = None  # 懒创建
        # assets.bin 骨架/材质服务（懒加载，跨船复用）
        self._assets_svc = None
        self._assets_tried = False
        # AC11: AssetsCacheService 单实例（替代 9 处每次 new → 新 sqlite 连接）
        self._assets_cache = None
        self._assets_cache_wows_type = None  # 创建时服务器，切服后重建（分库隔离）
        self._mfm_index_cache: dict | None = None  # mfm 名(去 .mfm) -> 完整路径
        self._mfm_diffuse_cache: dict = {}       # stem -> 贴图基础名（.mfm 识别结果）
        #: 几何目录索引 {文件夹名: [VfsEntry]}，一次构建跨船复用（避免重复全树扫描）
        self._geom_folder_index: dict | None = None
        #: 挂载模型加载缓存 {文件夹名: 结果 or None}，跨船复用（多船共享同一炮塔/副炮模型）
        self._mount_model_cache: dict = {}
        #: 舰体骨架挂点变换缓存 {model_stem: {hp: matrix}}
        self._stem_mount_cache: dict = {}
        #: 骨架骨骼世界矩阵缓存 {stem: {bone_name: (4,4)}}（蒙皮 bind pose 用，跨船复用）
        self._skeleton_bones_cache: dict = {}
        #: 分段渲染集缓存 {geometry_path: [{shape, material, mfm}]}
        self._visual_rs_cache: dict = {}
        #: visual blob 一次性索引 {geometry_path: [record_index]}（避免每分段全量扫描）
        self._visual_geom_index: dict | None = None
        self._assets_self_id_index = None
        #: 材质贴图缓存 {mfm_path: (texture_path, texture_bytes)}，跨船复用
        self._material_texture_cache: dict = {}
        #: 贴图字节缓存 {base路径: bytes}（同次加载内共享图集只解压一次；
        #: INDEXED 的 albedoArray/normalArray/MGArray 是 20MB+ 共享图集，
        #: 每 mfm 现场解压 30s/个 → 多个 mfm 复用同一图集时严重卡死）
        self._texture_bytes_cache: dict = {}
        #: 材质完整信息缓存 {mfm_path: dict}（技术族 + 贴图集 + INDEXED 分块参数）
        self._material_full_cache: dict = {}
        #: 全局渲染集索引 {murmur3(shape.vertices): {shape, material, mfm, damage}}
        #: 整合模型的高模 shape 渲染集可能在别的分段记录里，需全局扫描一次
        self._global_rs_index: dict | None = None
        #: 字符串表 {hash: name} dict（加速渲染集扫描，避免逐次哈希查表）
        self._strings_dict_cache: dict | None = None
        #: shape 名哈希表（**只从 assets_data.db 读取**）{hash: name} + 已尝试标记
        self._shape_names_cache: dict | None = None
        self._shape_names_tried = False
        #: assets_data.db 材质贴图映射缓存 {mfm_path: diffuse_base}（数据库优先，一次加载）
        self._mfm_textures_db: dict | None = None
        #: 舰船实体 JSON 快照缓存 {game_key: dict}（DB-first：只读主库 entity_snapshots）
        self._ship_snapshot_cache: dict = {}
    @classmethod
    def instance(cls) -> "GeometryService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ── 提取器 ──────────────────────────────────────────

    def _get_extractor(self):
        if self._extractor is None:
            from data_extractor import GameExtractor
            self._extractor = GameExtractor(
                app_ctx.ctx.game_path,
                bin_folder=app_ctx.ctx.bin_folder,
            )
        return self._extractor

    def _release_extractor(self):
        if self._extractor is not None:
            try:
                self._extractor.close()
            except Exception:  # noqa: BLE001
                pass
            self._extractor = None

    # ── 舰船列表 ────────────────────────────────────────

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        """协作式取消检查点：取消已请求则抛出 TaskCancelled（正常结束，非错误）。

        供 load_ship 及挂载加载等长循环在批次边界调用，使后台任务能在
        关闭 3D 查看器后尽快退出，而不是继续跑完整艘船。
        """
        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelled

    def list_ships(self, refresh: bool = False) -> list[ShipInfo]:
        """发现可载入舰船（DB-first：只读主库 ship_models 表）。

        ship_models 在「加载数据」入库时写入；数据库无记录提示先加载数据，
        不再回退扫描 data/split JSON。
        """
        if self._ships is not None and not refresh:
            return self._ships

        ships: list[ShipInfo] = []
        try:
            from services.database_service import get_db
            db = get_db(app_ctx.ctx.wows_type)
            if db.exists:
                for row in db.load_ship_models():
                    ships.append(ShipInfo(
                        game_key=row["ship_id"],
                        display_name=self._resolve_ship_name(row["ship_id"]),
                        model_folder=row["model_folder"],
                        model_path=row["model_path"],
                        nation=row["nation"],
                        has_geometry=bool(row["model_folder"]),
                    ))
        except Exception as exc:  # noqa: BLE001
            ships = []
            bus.log_message.emit(f"⚠️ 舰船列表加载异常: {exc}")
        if not ships:
            self._ships_error = "数据库无可载入舰船（请先「加载数据」）"
        self._ships = ships
        return ships

    @staticmethod
    def _resolve_ship_name(game_key: str) -> str:
        """GameParams 键前缀 → 本地化舰船名（DB name_mappings，category='ship'）。"""
        try:
            prefix = game_key.split("_", 1)[0]
            from services.database_service import get_db
            db = get_db(app_ctx.ctx.wows_type)
            if db.exists:
                names = db.get_all_name_mappings("ship")
                name = names.get(prefix) or names.get(game_key)
                if name:
                    return name
        except Exception:  # noqa: BLE001
            pass
        return game_key

    # ── 舰船几何加载 ────────────────────────────────────

    def load_ship(self, ship: ShipInfo, progress_cb=None,
                  cancel_event: threading.Event | None = None,
                  model_replace: dict | None = None,
                  skin: dict | None = None) -> ShipGeometry:
        """加载一艘船的船体网格 + 挂载模型 + 装甲网格 + 碰撞模型。

        model_replace：皮肤变体（origin="model"）的「原始 .model 路径 → 替换路径」映射
        （Exterior.peculiarityModels），用于把船体/挂载模型替换成皮肤变体。
        skin：Exterior 皮肤的完整数据（hull_config/nodes_config/peculiarity_models），
        用于整体替换船体模型 + 各挂载模型 + miscFilter 过滤。
        """
        try:
            return self._load_ship_impl(ship, progress_cb=progress_cb,
                                        cancel_event=cancel_event,
                                        model_replace=model_replace, skin=skin)
        finally:
            self._clear_per_load_caches()

    def apply_camo(self, geom: ShipGeometry, camo, extractor=None) -> int:
        # ⚠️【临时标记】涂装渲染逻辑尚未正确：camouflage/MSkin/Permoflage/通用永久等几类
        # 生效方式不同的涂装需**分开处理**，当前统一 artMap/composite 覆盖是错的（配色1 全灰）。
        # 此函数按涂装类型拆分前，先屏蔽涂装入口（见 geometry_viewer 临时标记），勿继续在
        # 这条统一路径上调试。拆分点建议：标准 PBS 用 composite 到 diffuse；
        # INDEXED（视觉 2.0）用 artMap 叠加；二者对 colorScheme 的 zone 掩膜判定需分别验证。
        """把 camo（CamouflageEntry 或 dict）的贴图按部件分类覆盖到标准(PBS)材质 mesh，返回替换数。

        INDEXED 图集（albedoArray 等）需单独 artMap/tint 覆盖，暂回退不改；仅处理单张 diffuseMap 的标准材质。
        """
        if camo is None:
            return 0
        texs = getattr(camo, "textures", None)
        if texs is None and isinstance(camo, dict):
            texs = camo.get("textures") or {}
        texs = texs or {}
        if not texs:
            return 0
        from services.camo_service import classify_part_category
        extractor = extractor or self._get_extractor()
        import numpy as np
        count = 0
        meshes = list(geom.hull_meshes) + [m for m in getattr(geom, "mounts", [])]
        for hm in meshes:
            is_idx = getattr(hm, "tech_family", "pbs") == "indexed"
            name = getattr(hm, "material", "") or ""
            cat = classify_part_category(name)
            tp = texs.get(cat) or texs.get("hull") or texs.get("tile")
            if not tp:
                continue
            base = tp[:-4] if tp.endswith(".dds") else tp
            try:
                vp, td = self._load_texture_tier(base, extractor)
            except Exception:  # noqa: BLE001
                continue
            if not td:
                continue
            ucs = self._camo_attr(camo, "use_color_scheme", False)
            colors = self._camo_attr(camo, "colors", None)
            tiled = bool(self._camo_attr(camo, "tiled", False))
            if is_idx:
                # INDEXED 涂装：zone mask 按颜色方案烘焙 → artMap 叠加。
                # 覆盖量 = art alpha(图案遮罩) × 材质 art 强度；non-tiled 黑区 α=0 透出底色。
                art_td = td
                if ucs and colors:
                    baked = self._bake_camo_art(td, colors, tiled=tiled)
                    if baked is not None:
                        art_td = baked
                mt = dict(getattr(hm, "material_textures", {}) or {})
                mt["artMap"] = (vp, art_td)
                hm.material_textures = mt
                ip = dict(hm.indexed_params or {})
                arrays = dict(ip.get("arrays") or {})
                asa = np.zeros((196, 4), dtype=np.float32)
                asa[:, 0] = 1.0
                arrays["artStrengthMatIdArr"] = asa
                ip["arrays"] = arrays
                hm.indexed_params = ip
                hm.has_color = True
                count += 1
            else:
                # 标准（PBS）：烘焙并按颜色方案**叠加到底色**后作为 diffuseMap
                diff_td = td
                if ucs and colors:
                    baked = self._bake_camo_art(td, colors, tiled=tiled)
                    if baked is not None:
                        comp = self._composite_camo_over_base(
                            getattr(hm, "texture_dds", None), baked)
                        diff_td = comp if comp is not None else baked
                hm.texture_path, hm.texture_dds = vp, diff_td
                mt = dict(getattr(hm, "material_textures", {}) or {})
                mt["diffuseMap"] = (vp, diff_td)
                hm.material_textures = mt
                hm.has_color = True
                count += 1
        return count

    @staticmethod
    def _camo_attr(camo, name: str, default=None):
        """从 CamouflageEntry 或 dict 取属性。"""
        if camo is None:
            return default
        if isinstance(camo, dict):
            return camo.get(name, default)
        return getattr(camo, name, default)

    @staticmethod
    def _rgba_to_dds_bgra(rgba) -> bytes | None:
        """RGBA (H,W,4) uint8 → 未压缩 DDS（BGRA 像素，供 _upload_texture 未压缩分支上传）。"""
        import struct
        import numpy as np
        h, w, _ = rgba.shape
        bgra = rgba[:, :, [2, 1, 0, 3]].copy()
        hdr = bytearray(128)
        hdr[0:4] = b"DDS "
        struct.pack_into("<I", hdr, 4, 124)        # dwSize
        struct.pack_into("<I", hdr, 8, 0x1007)     # flags: caps|height|width|pixelformat
        struct.pack_into("<I", hdr, 12, h)         # height
        struct.pack_into("<I", hdr, 16, w)         # width
        struct.pack_into("<I", hdr, 20, w * 4)     # pitch
        struct.pack_into("<I", hdr, 24, 0)         # depth
        struct.pack_into("<I", hdr, 28, 1)         # mip count
        struct.pack_into("<I", hdr, 76, 32)        # pixel format size
        struct.pack_into("<I", hdr, 80, 0x41)      # DDPF_RGB | DDPF_ALPHAPIXELS
        struct.pack_into("<I", hdr, 84, 0)         # fourcc = 0（未压缩）
        struct.pack_into("<I", hdr, 88, 32)        # RGB bit count
        struct.pack_into("<I", hdr, 92, 0x00ff0000)
        struct.pack_into("<I", hdr, 96, 0x0000ff00)
        struct.pack_into("<I", hdr, 100, 0x000000ff)
        struct.pack_into("<I", hdr, 104, 0xff000000)
        struct.pack_into("<I", hdr, 108, 0x1000)   # DDSCAPS_TEXTURE
        return bytes(hdr) + np.ascontiguousarray(bgra).tobytes()

    def _bake_camo_art(self, dds_bytes: bytes, colors, tiled: bool = False) -> bytes | None:
        """把 camo zone mask 按颜色方案 CPU 上色为 RGBA，再包成未压缩 DDS（作为 artMap）。

        对齐 wows-toolkit bake_tiled_camo_png：
        - zone 由**主色通道**判定：红→color1、绿→color2、蓝→color3、黑→color0。
        - 颜色为线性 [0,1]，写回前转 sRGB（linear→sRGB）。
        - black_passthrough = !tiled：非 tiled（整船涂装）黑区 α=0（透出底涂），
          tiled（重复图案）黑区 α=255（作为真实图案色）。
        - 若纹理由真实烘焙贴图而非 zone mask 组成（zone 像素占比 < 0.90），返回 None，
          由调用方回退未上色的原始贴图。
        """
        import numpy as np
        try:
            from services.export_service import dds_to_rgba
        except Exception:  # noqa: BLE001
            return None
        try:
            rgba = dds_to_rgba(dds_bytes)
        except Exception:  # noqa: BLE001
            return None
        if rgba is None:
            return None
        h, w, _ = rgba.shape
        r = rgba[..., 0].astype(np.int32)
        g = rgba[..., 1].astype(np.int32)
        b = rgba[..., 2].astype(np.int32)
        red_zone = (r > g) & (r > b) & (r > 30)
        green_zone = (g > r) & (g > b) & (g > 30)
        blue_zone = (b > r) & (b > g) & (b > 30)
        near_black = (r <= 30) & (g <= 30) & (b <= 30)
        black_zone = ~(red_zone | green_zone | blue_zone)
        # zone_mask_fraction：主色通道或近黑的像素占比，过低则视为真实烘焙贴图 → 回退
        frac = (red_zone | green_zone | blue_zone | near_black).sum() / float(h * w)
        if frac < 0.90:
            return None
        c = np.asarray(colors, dtype=np.float64).reshape(4, 4)
        if c.max() > 1.001:
            c = c / 255.0

        def _lin2srgb(x):
            x = np.clip(x, 0.0, 1.0)
            return (np.where(x <= 0.0031308, x * 12.92,
                             1.055 * np.power(x, 1.0 / 2.4) - 0.055) * 255.0).astype(np.uint8)

        srgb = [_lin2srgb(c[i][:3]) for i in range(4)]
        black_alpha = 0 if not tiled else 255
        out = np.zeros((h, w, 4), np.uint8)
        for i, mask in enumerate((black_zone, red_zone, green_zone, blue_zone)):
            if not mask.any():
                continue
            col = srgb[i]
            out[..., 0][mask] = col[0]
            out[..., 1][mask] = col[1]
            out[..., 2][mask] = col[2]
        out[..., 3] = 255
        if not tiled:
            out[..., 3][black_zone] = 0
        return self._rgba_to_dds_bgra(out)

    def _composite_camo_over_base(self, base_dds, camo_baked) -> bytes | None:
        """把烘焙后的 camo RGBA（alpha = 覆盖遮罩）叠加到底色 diffuse 上，返回未压缩 DDS。

        对齐 wows-toolkit 导出流程：zone mask 黑区（= 未涂装，α=0）透出底色，
        涂装区（α=255）用 camo 颜色。两者 UV 均为 0..1，分辨率不同则重采样到底色尺寸。
        """
        import numpy as np
        if not base_dds:
            return None
        try:
            from services.export_service import dds_to_rgba
            base = dds_to_rgba(base_dds)
            camo = dds_to_rgba(camo_baked)
        except Exception:  # noqa: BLE001
            return None
        if base is None or camo is None:
            return None
        if camo.shape[:2] != base.shape[:2]:
            try:
                from PIL import Image
                ci = Image.fromarray(camo)
                ci = ci.resize((base.shape[1], base.shape[0]), Image.BILINEAR)
                camo = np.asarray(ci, dtype=np.uint8)
            except Exception:  # noqa: BLE001
                return None
        a = camo[..., 3:4].astype(np.float32) / 255.0
        comp = (base[..., :3].astype(np.float32) * (1.0 - a)
                + camo[..., :3].astype(np.float32) * a)
        out = np.zeros_like(base)
        out[..., :3] = np.clip(comp, 0, 255).astype(np.uint8)
        out[..., 3] = 255
        return self._rgba_to_dds_bgra(out)

    def _load_ship_impl(self, ship: ShipInfo, progress_cb=None,
                        cancel_event: threading.Event | None = None,
                        model_replace: dict | None = None,
                        skin: dict | None = None) -> ShipGeometry:
        """加载一艘船的船体网格 + 挂载模型 + 装甲网格 + 碰撞模型（实现）。

        - 舰体：模型目录内全部 .geometry 分段（已处于舰船坐标系，直接合并）
        - 挂载：GameParams 各 HP_* 挂载模型 + assets.bin 骨架挂点变换定位，
          每个部件使用自己的独立贴图（以骨架信息为基准区分不同模型贴图）
        - 装甲：按归属分类标记（船体/主炮塔/副炮/防空/指挥仪/测距/雷达）

        progress_cb(pct: float, message: str) —— 0..100
        cancel_event: 协作式取消事件；在长循环边界检查，取消时抛 TaskCancelled。
        """
        if progress_cb:
            progress_cb(2, "定位几何文件...")
        self._raise_if_cancelled(cancel_event)
        extractor = self._get_extractor()

        # 读取该舰的装甲厚度字典（A_Hull.armor + 各挂载 HP_*.armor）
        armor_thickness = self._load_armor_thickness(ship)

        # 皮肤变体（origin="model"）：把船体 model 目录替换成皮肤变体目录
        #   优先 hullConfig 的 model；其次 peculiarityModels 的船体替换；最后原 model_folder
        use_mf = ship.model_folder
        skin_nodes: dict = {}
        if skin:
            if not model_replace:
                model_replace = skin.get("peculiarity_models") or None
            for hv in (skin.get("hull_config") or {}).values():
                if isinstance(hv, dict) and hv.get("model"):
                    use_mf_override = hv["model"].rsplit("/", 2)[-2] if "/" in hv["model"] else ""
                    if use_mf_override:
                        use_mf = use_mf_override
                    break
            for nodes in (skin.get("nodes_config") or {}).values():
                if isinstance(nodes, dict):
                    for hp, nv in nodes.items():
                        if isinstance(nv, dict):
                            skin_nodes[hp] = nv
        if use_mf == ship.model_folder and model_replace:
            for _k, _v in model_replace.items():
                _d = _k.rsplit("/", 2)[-2] if "/" in _k else ""
                if _d and _d == ship.model_folder:
                    use_mf = _v.rsplit("/", 2)[-2] if "/" in _v else use_mf
                    break

        # 舰体分段：模型目录内全部 .geometry（已处于舰船坐标系）
        entries = self._geometry_folder_index(extractor).get(use_mf) or []
        if not entries:
            # 回退：按 model_folder 全树匹配任意路径下的 geometry
            pattern = f"content/**/{use_mf}/{use_mf}*.geometry"
            try:
                entries = [
                    e for e in extractor.list_files([pattern])
                    if not e.is_directory
                ]
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"列出几何文件失败: {exc}") from exc

        if not entries:
            raise RuntimeError(f"未找到 {use_mf} 的 .geometry 文件")

        # 去重（相同路径+大小只加载一次）
        seen = set()
        uniq = []
        for e in sorted(entries, key=lambda x: x.path):
            key = (e.path, e.file_info.size)
            if key not in seen:
                seen.add(key)
                uniq.append(e)

        # 跳过「不带分段后缀」的主文件（如 JSB039_Yamato_1945.geometry）：
        # 多为 base/聚合文件，含烟囱等多余模型；真正高模在 *_Bow/_MidBack/... 分段。
        # 但**主文件可能含船体装甲**（CM_PA_*.armor，如 Yamato 12487 tris）→ 单独保留。
        main_entries = []
        seg_uniq = []
        for e in uniq:
            stem = e.path.rsplit('/', 1)[-1][:-len('.geometry')]
            if stem == use_mf:
                main_entries.append(e)
                continue
            seg_uniq.append(e)
        if seg_uniq:
            uniq = seg_uniq
        elif uniq:
            # 只有主文件（无分段模型）：明确报错提示，而非静默用主文件回退
            raise RuntimeError(
                f"未找到 {use_mf} 的分段模型文件"
                f"（仅存在主文件 {use_mf}.geometry）")

        # 该船全部渲染集索引（含整合模型：高模 shape 渲染集可能在别的分段记录）
        ship_rs = self._ship_render_sets(use_mf)

        geom = ShipGeometry(
            game_key=ship.game_key,
            display_name=ship.display_name,
            model_folder=use_mf,
        )

        # 蒙皮 bind pose 骨架 stem（舰船模型目录；_apply_skinning 用它查骨骼矩阵）
        self._current_skinning_stem = use_mf

        bmin = np.full(3, np.inf, dtype=np.float32)
        bmax = np.full(3, -np.inf, dtype=np.float32)
        total_parts = len(uniq)

        for idx, e in enumerate(uniq):
            self._raise_if_cancelled(cancel_event)
            if progress_cb:
                progress_cb(5 + 80 * idx / total_parts, f"解析 {e.path.rsplit('/', 1)[-1]}")
            try:
                data = extractor.pkg_reader.read_file(e.volume.filename, e.file_info)
            except Exception as exc:  # noqa: BLE001
                geom.stats.setdefault("warnings", []).append(f"{e.path}: 读取失败 {exc}")
                continue
            try:
                parsed = parse_geometry(data, file_path=e.path, cancel_event=cancel_event)
            except GeometryError as exc:
                geom.stats.setdefault("warnings", []).append(f"{e.path}: {exc}")
                continue
            finally:
                del data

            part_name = e.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

            # 合并该部件的全部 primitive → 按材质拆分的 HullMesh（不同模型不同贴图）
            if parsed.primitives:
                # ship_rs 含 LOD/crack 的 damage 标记，但部分船的 LOD/crack 渲染集
                # 不在数据库（如 ST 服 Yamato MidFront 无 LOD1/LOD3 visual 记录）——
                # 用 shape_names 表（populate 时写入 DB）按名兜底跳过 _lod/_crack_；
                # ★ 只从数据库读取，绝不现场读 assets.bin
                sdict = self._shape_names_sdict()
                groups = self._split_primitives_by_material(parsed.primitives, ship_rs, sdict,
                                                            geom_path=e.path, instancing=True)
                if groups:
                    for mat_key, g in groups.items():
                        if not g.get('prims'):
                            continue
                        inst = list(g.get('instance_matrices') or [])
                        # __inst__# 组：真实材质在 g['material']，带逐节点实例矩阵
                        if isinstance(mat_key, str) and mat_key.startswith('__inst__#'):
                            real = g.get('material')
                            nm = part_name if real is None else f"{part_name}#{real}"
                        else:
                            real = mat_key
                            nm = part_name if mat_key is None else f"{part_name}#{mat_key}"
                        hm = self._merge_hull(nm, g['prims'],
                                              shape_names=g.get('shape_names', []),
                                              node_names=g.get('node_names', []),
                                              instance_matrices=inst)
                        if real is not None:
                            hm.material = real
                        if mat_key == '__wire__' or mat_key == 'WIRE':
                            hm.is_wire = True
                        if isinstance(mat_key, str) and mat_key.startswith('__crack__'):
                            hm.is_crack = True
                        if real is not None:
                            # 完整材质信息：技术族 + 贴图集 + INDEXED 分块参数（fx 区分渲染）
                            # ★ 只认 mfm 声明的贴图属性；未声明颜色贴图 → 无色（不按名补全）
                            bundle = self._resolve_material_full(g.get('mfm') or '', extractor)
                            self._apply_declared_color(hm, bundle, extractor)
                        geom.hull_meshes.append(hm)
                        if hm.positions.size:
                            if inst:
                                # 实例化网格：包围盒按各个节点矩阵求并集
                                for _m in inst:
                                    mn, mx = self._instanced_bounds(hm.positions, _m)
                                    bmin = np.minimum(bmin, mn)
                                    bmax = np.maximum(bmax, mx)
                            else:
                                pmin = hm.positions.min(axis=0)
                                pmax = hm.positions.max(axis=0)
                                bmin = np.minimum(bmin, pmin)
                                bmax = np.maximum(bmax, pmax)
                else:
                    hm = self._merge_hull(part_name, parsed.primitives)
                    geom.hull_meshes.append(hm)
                    if hm.positions.size:
                        pmin = hm.positions.min(axis=0)
                        pmax = hm.positions.max(axis=0)
                        bmin = np.minimum(bmin, pmin)
                        bmax = np.maximum(bmax, pmax)

            # 装甲网格（舰体装甲 → 归属"船体"，已在舰船坐标系）
            for am in parsed.armor_models:
                mesh = self._build_armor_mesh(am, armor_thickness, component=COMPONENT_HULL)
                if mesh is not None:
                    geom.armor_meshes.append(mesh)
                    if mesh.positions.size:
                        pmin = mesh.positions.min(axis=0)
                        pmax = mesh.positions.max(axis=0)
                        bmin = np.minimum(bmin, pmin)
                        bmax = np.maximum(bmax, pmax)

            # 碰撞模型
            for cm in parsed.collision_models:
                geom.collision_models.append(CollisionModelData(cm.name, cm.size_in_bytes, cm.data))

            geom.stats[f"parts"] = len(uniq)
            geom.stats[f"prim_{idx}"] = {
                "file": part_name,
                "vertices": sum(p.positions.shape[0] for p in parsed.primitives),
                "triangles": sum(0 if p.indices is None else p.indices.size // 3 for p in parsed.primitives),
                "armor_tris": sum(len(a.triangles) for a in parsed.armor_models),
            }

        if np.isfinite(bmin).all():
            geom.bounds_min = bmin
            geom.bounds_max = bmax

        # 提取船体漫反射贴图（尽力而为：单贴图应用到全部舰体分段）
        self._raise_if_cancelled(cancel_event)
        try:
            tex_path, tex_bytes = self._find_hull_diffuse(ship, extractor)
            if tex_bytes:
                geom.texture_dds = tex_bytes
                geom.texture_path = tex_path
        except Exception:  # noqa: BLE001
            pass

        # ── 主文件装甲（几何已跳过渲染，但船体装甲 CM_PA_*.armor 在此） ──
        for e in main_entries:
            try:
                data = extractor.pkg_reader.read_file(e.volume.filename, e.file_info)
            except Exception as exc:  # noqa: BLE001
                geom.stats.setdefault("warnings", []).append(f"{e.path}: 装甲读取失败 {exc}")
                continue
            try:
                parsed = parse_geometry(data, file_path=e.path, cancel_event=cancel_event)
            except GeometryError as exc:  # noqa: BLE001
                geom.stats.setdefault("warnings", []).append(f"{e.path}: 装甲解析失败 {exc}")
                continue
            finally:
                del data
            for am in parsed.armor_models:
                mesh = self._build_armor_mesh(am, armor_thickness, component=COMPONENT_HULL)
                if mesh is not None:
                    geom.armor_meshes.append(mesh)
                    if mesh.positions.size:
                        pmin = mesh.positions.min(axis=0)
                        pmax = mesh.positions.max(axis=0)
                        bmin = np.minimum(bmin, pmin)
                        bmax = np.maximum(bmax, pmax)

        # ── 挂载模型（骨架定位 + 每个部件独立贴图） ──
        self._raise_if_cancelled(cancel_event)
        self._load_mounts(geom, ship, extractor, armor_thickness, progress_cb,
                          cancel_event=cancel_event, model_replace=model_replace,
                          skin_nodes=skin_nodes)

        if progress_cb:
            progress_cb(100, "加载完成")
        return geom

    # ── 挂载模型 ────────────────────────────────────────

    def _emit_instanced_mount(self, geom: ShipGeometry, src: dict, folder: str,
                              comp: str, group_items: list,
                              bmin: np.ndarray, bmax: np.ndarray):
        """为一个 (folder, comp) 组创建**实例化**挂载网格（一份几何 + 各节点矩阵）。

        同一模型目录被多个挂载节点引用（如 MP_... / MP_..._INDEX2、多座同型炮塔）时，
        不再为每个节点复制一份几何（N×顶点内存爆炸）；而是只创建每个材质分片一份网格，
        把各节点的渲染空间矩阵存入 instance_matrices，渲染时逐节点各画一次。
        group_items: [(label, mtx, armor_mtx), ...]。
        """
        for hm in src["meshes"]:
            mats = [(_armor_mtx if hm.skinned_applied else _mtx)
                    for (_label, _mtx, _armor_mtx) in group_items]
            mm = MountMesh(
                name=folder, component=comp,
                positions=hm.positions, normals=hm.normals,
                uvs=hm.uvs, indices=hm.indices,
                model_matrix=None,
                instance_matrices=[np.ascontiguousarray(m, dtype=np.float32)
                                   for m in mats],
                texture_dds=hm.texture_dds, texture_path=hm.texture_path,
                model_folder=folder, vertex_count=hm.vertex_count,
                is_wire=hm.is_wire, is_crack=hm.is_crack,
                tech_family=hm.tech_family,
                material_textures=hm.material_textures or {},
                indexed_params=hm.indexed_params,
                has_color=hm.has_color,
                bone_indices=hm.bone_indices, bone_weights=hm.bone_weights,
                skin_bones=hm.skin_bones, skin_bind=hm.skin_bind,
                shape_names=hm.shape_names, node_names=hm.node_names,
            )
            geom.mounts.append(mm)
            if mm.positions.size:
                for _m in mm.instance_matrices:
                    mn, mx = self._instanced_bounds(mm.positions, _m)
                    bmin = np.minimum(bmin, mn)
                    bmax = np.maximum(bmax, mx)
        return bmin, bmax

    def _dedupe_mount_instances(self, geom: ShipGeometry) -> None:
        """把 `geom.mounts` 中共享同一几何的 MountMesh 合并为**实例化**网格。

        所有节点类型（HP 挂载 / MP 甲板设备 / 挂载模型骨架上的 MP 子设备）统一收敛：
        同一模型目录被多个节点引用时，不再逐节点复制顶点，而是每个
        (model_folder, 几何, component) 只保留一份网格，把各节点的渲染矩阵存入
        instance_matrices。渲染时逐节点各画一次 → 大幅降低 GPU 内存。

        依据：`_load_mount_model` 按 folder 缓存，同一模型的 `positions` 是同一个
        ndarray 对象，故用 `id(positions)` 判同几何。
        """
        groups: dict = {}
        order: list = []
        for mm in geom.mounts:
            key = (getattr(mm, 'model_folder', ''), id(mm.positions),
                   getattr(mm, 'component', ''), getattr(mm, 'tech_family', 'pbs'))
            if key not in groups:
                groups[key] = [mm, []]
                order.append(key)
            g = groups[key]
            if mm.instance_matrices:
                g[1].extend(list(mm.instance_matrices))
            elif mm.model_matrix is not None:
                g[1].append(np.ascontiguousarray(mm.model_matrix, dtype=np.float32))
            else:
                g[1].append(np.eye(4, dtype=np.float32))
        new_mounts: list = []
        for key in order:
            rep, mats = groups[key]
            n = len(mats)
            if n == 1:
                # 单节点：无需实例化，保留原样（不额外复制）
                if rep.instance_matrices and not rep.model_matrix:
                    rep.instance_matrices = mats
                new_mounts.append(rep)
                continue
            name = f"{getattr(rep, 'name', rep.model_folder)}+({n})"
            inst = MountMesh(
                name=name, component=rep.component,
                positions=rep.positions, normals=rep.normals,
                uvs=rep.uvs, indices=rep.indices,
                model_matrix=None,
                texture_dds=rep.texture_dds, texture_path=rep.texture_path,
                model_folder=rep.model_folder, vertex_count=rep.vertex_count,
                is_wire=rep.is_wire, is_crack=rep.is_crack,
                tech_family=rep.tech_family,
                material_textures=rep.material_textures or {},
                indexed_params=rep.indexed_params,
                has_color=rep.has_color,
                bone_indices=rep.bone_indices, bone_weights=rep.bone_weights,
                skin_bones=rep.skin_bones, skin_bind=rep.skin_bind,
                shape_names=rep.shape_names, node_names=rep.node_names,
                instance_matrices=mats,
            )
            new_mounts.append(inst)
        geom.mounts = new_mounts

    def _load_mounts(self, geom: ShipGeometry, ship: ShipInfo, extractor,
                     armor_thickness: dict, progress_cb=None,
                     cancel_event: threading.Event | None = None,
                     model_replace: dict | None = None,
                     skin_nodes: dict | None = None):
        """加载 GameParams 各 HP_* 挂载模型并按骨架挂点定位。

        同一模型目录（如 JGM178 炮塔）只解析一次几何，按每个挂点实例化；
        每个挂载使用该模型自己的贴图（`{stem}_a.dd0` 命名约定）。
        """
        refs = self._load_mount_refs(
            ship, warnings=geom.stats.setdefault("warnings", []), skin_nodes=skin_nodes)
        transforms = self._load_mount_transforms(ship)
        if not refs and not transforms:
            geom.stats["mounts"] = 0
            return
        if not transforms:
            geom.stats["mounts"] = 0
            geom.stats.setdefault("warnings", []).append(
                "未找到 assets.bin 挂点骨架，挂载模型未定位（舰体仍正常显示）")
            return

        bmin = geom.bounds_min
        bmax = geom.bounds_max
        if bmin is None or bmax is None:
            bmin = np.full(3, np.inf, dtype=np.float32)
            bmax = np.full(3, -np.inf, dtype=np.float32)

        model_cache: dict = {}   # model_folder -> 加载结果 or None
        hp_groups: dict = {}     # (folder, comp) -> [(label, mtx, armor_mtx), ...]
        placed = 0
        sub_placed = 0   # 挂载模型骨架上的 MP 子设备（炮塔测距仪/炮上防空炮等）
        _negz = np.diag([1.0, 1.0, -1.0, 1.0])   # 几何(左手系)→渲染(右手系) 共轭
        n_refs = len(refs)
        for idx, (hp, comp, model_path, misc_filter, custom_battle) in enumerate(refs):
            self._raise_if_cancelled(cancel_event)
            if model_replace:
                model_path = model_replace.get(model_path, model_path)
            # 挂载加载阶段同样报进度（66%→99%），避免进度条停在分段解析末尾
            if progress_cb:
                progress_cb(66 + 33 * idx / max(1, n_refs), f"加载挂载 {hp}")
            folder = self._folder_from_model_path(model_path)
            if not folder:
                continue
            m_raw = transforms.get(hp)
            if m_raw is None:
                # 引用小零件（如 HP_JGM_2_HP_JGA_1 主炮塔上防空炮）：
                # 父挂点(舰船) × 父模型骨架内子挂点(bind pose 世界)
                m_raw = self._child_mount_transform(hp, refs, transforms)
            if m_raw is None:
                # 兜底：继承父挂点矩阵（HP_JGM_2），随炮塔定位
                m_raw = self._derived_mount_transform(hp, transforms)
            if m_raw is None:
                continue
            # 基于原始骨骼组匹配：几何空间 = HP 挂点 × 模型 Root_BlendBone(静息朝向)，
            # 再 negz 共轭转渲染空间（等价于顶点几何 Z 取反）
            rb = self._mount_root_blend(folder)
            mtx = np.ascontiguousarray(_negz @ (m_raw @ rb) @ _negz, dtype=np.float32)
            # ★ 装甲几何在制作时已与挂点对齐（wows-toolkit ship.rs：armor 用
            # 原始 hp_transform，不做 Root_BlendBone 旋转修正）；若套用 mtx 会
            # 多转一次 rb → 主炮塔装甲方向反转。装甲单独用原始挂点矩阵。
            armor_mtx = np.ascontiguousarray(_negz @ m_raw @ _negz, dtype=np.float32)
            if folder not in model_cache:
                model_cache[folder] = self._load_mount_model(
                    folder, extractor, armor_thickness, comp, cancel_event=cancel_event)
            src = model_cache[folder]
            if src is None:
                continue

            # ★ 不逐节点复制几何：把该节点的 (label, mtx, armor_mtx) 累积到分组，
            #   循环后按 (folder, comp) 一次性实例化（一份几何 + 各节点矩阵）。
            hp_groups.setdefault((folder, comp), []).append((hp, mtx, armor_mtx))

            # 该模型的装甲（本地坐标 + 原始挂点矩阵定位 + 归属分类）
            for am in src["armor_meshes"]:
                mesh = ArmorMesh(
                    name=am.name, positions=am.positions, normals=am.normals,
                    colors=am.colors, indices=am.indices, triangles=am.triangles,
                    component=comp, model_matrix=armor_mtx,
                )
                geom.armor_meshes.append(mesh)
                if mesh.positions.size:
                    mn, mx = mesh.bounds_in_world()
                    bmin = np.minimum(bmin, mn)
                    bmax = np.maximum(bmax, mx)
            placed += 1

            # 该挂载模型骨架上的 MP 子设备（炮塔测距仪/炮管防空炮/弹药箱等，
            # 全库约 1% MP 父节点非 Scene Root）。骨架空间→船 = m_raw。
            # miscFilter 白名单：**恒生效**（空列表 = 空白名单 = 不显示任何
            # MP 子设备），对齐游戏 MiscsController；customMiscs.battle 预设
            # 按 miscName 兜底显示。同一模型在不同炮位显示不同挂件（PGSB106）。
            mp_allow = frozenset(misc_filter)
            battle_customs = frozenset(custom_battle)
            sub_n, bmin, bmax = self._place_skeleton_mps(
                geom, folder, m_raw, model_cache, extractor, armor_thickness,
                comp, bmin, bmax, 0, frozenset(), cancel_event=cancel_event,
                mp_allow=mp_allow, battle_customs=battle_customs)
            sub_placed += sub_n

        # ★ 一次性实例化 HP 挂载（同模型多节点 → 一份几何 + 各节点矩阵）
        for (folder, comp), items in hp_groups.items():
            src = model_cache.get(folder)
            if src is None:
                continue
            bmin, bmax = self._emit_instanced_mount(geom, src, folder, comp,
                                                    items, bmin, bmax)

        # ── MP 甲板设备挂载（缆桩/小艇/探照灯/救生筏等 misc 模型）──
        # MP 节点不在 GameParams，由 populate 纳入 skeleton_mounts（v5）；
        # 模型目录由命名约定推导：MP_{baseID}_... → misc/{baseID}/{baseID}.geometry
        mp_placed = 0
        mp_items = [(n, m) for n, m in transforms.items() if n.startswith("MP_")]
        mp_groups: dict = {}   # folder -> [(label, mtx, armor_mtx), ...]
        n_mp = len(mp_items)
        for idx, (mp_name, m_raw) in enumerate(mp_items):
            self._raise_if_cancelled(cancel_event)
            if progress_cb:
                progress_cb(66 + 33 * (n_refs + idx) / max(1, n_refs + n_mp),
                            f"加载甲板设备 {mp_name}")
            folder = self._mp_model_folder(mp_name)
            if not folder:
                continue
            rb = self._mount_root_blend(folder)
            mtx = np.ascontiguousarray(_negz @ (m_raw @ rb) @ _negz, dtype=np.float32)
            # 装甲用原始挂点矩阵（同 HP 挂载：不做 Root_BlendBone 修正）
            armor_mtx = np.ascontiguousarray(_negz @ m_raw @ _negz, dtype=np.float32)
            if folder not in model_cache:
                model_cache[folder] = self._load_mount_model(
                    folder, extractor, armor_thickness, COMPONENT_DECK,
                    cancel_event=cancel_event)
            src = model_cache[folder]
            if src is None:
                continue
            # ★ 不逐节点复制几何：累积到分组，循环后一次性实例化
            mp_groups.setdefault(folder, []).append((mp_name, mtx, armor_mtx))
            for am in src["armor_meshes"]:
                mesh = ArmorMesh(
                    name=am.name, positions=am.positions, normals=am.normals,
                    colors=am.colors, indices=am.indices, triangles=am.triangles,
                    component=COMPONENT_DECK, model_matrix=armor_mtx,
                )
                geom.armor_meshes.append(mesh)
                if mesh.positions.size:
                    mn, mx = mesh.bounds_in_world()
                    bmin = np.minimum(bmin, mn)
                    bmax = np.maximum(bmax, mx)
            mp_placed += 1
            # 甲板设备模型自身骨架上的 MP 子设备（递归，防环）
            sub_n, bmin, bmax = self._place_skeleton_mps(
                geom, folder, m_raw, model_cache, extractor, armor_thickness,
                COMPONENT_DECK, bmin, bmax, 0, frozenset(), cancel_event=cancel_event)
            sub_placed += sub_n

        # ★ 一次性实例化 MP 甲板设备（同模型多节点 → 一份几何 + 各节点矩阵）
        for folder, items in mp_groups.items():
            src = model_cache.get(folder)
            if src is None:
                continue
            bmin, bmax = self._emit_instanced_mount(geom, src, folder, COMPONENT_DECK,
                                                    items, bmin, bmax)

        # ★ 统一收敛：把所有节点类型（含挂载模型骨架上的 MP 子设备）中共享同一
        #   几何的 MountMesh 合并为实例化网格（一份几何 + 各节点矩阵），省 GPU 内存。
        self._dedupe_mount_instances(geom)

        if np.isfinite(bmin).all():
            geom.bounds_min = bmin
            geom.bounds_max = bmax
        geom.stats["mounts"] = placed
        geom.stats["deck_equipment"] = mp_placed
        geom.stats["sub_equipment"] = sub_placed
        geom.stats["unique_mount_models"] = len(model_cache)

    @staticmethod
    def _folder_from_model_path(model_path: str) -> str:
        """`.model` 路径 → 模型目录名（末段）。"""
        parts = [p for p in str(model_path).replace("\\", "/").split("/") if p]
        return parts[-2] if len(parts) >= 2 else ""

    @staticmethod
    def _derived_mount_transform(hp: str, transforms: dict) -> np.ndarray | None:
        """无独立骨架挂点的 HP（如 `HP_JGM_2_HP_JGA_1` 主炮塔上防空炮）
        按最长前缀回退父挂点矩阵（`HP_JGM_2`）；找不到返回 None。"""
        parts = hp.split("_")
        for i in range(len(parts) - 1, 1, -1):
            cand = "_".join(parts[:i])
            if cand in transforms:
                return transforms[cand]
        return None

    def _skeleton_bone_world(self, folder: str, bone_name: str) -> np.ndarray | None:
        """读挂载模型骨架某 bone 的世界矩阵（bind pose，**只从 assets_data.db 读取**）。

        按 folder 缓存整棵骨架的世界矩阵表。"""
        key = f"skelworld:{folder}"
        if key not in self._mount_model_cache:
            world: dict = {}
            try:
                c = self._get_assets_cache()
                world = c.get_skeleton_bones(app_ctx.ctx.bin_folder or "", folder)
            except Exception:  # noqa: BLE001
                world = {}
            self._mount_model_cache[key] = world
        return self._mount_model_cache[key].get(bone_name)

    def _child_mount_transform(self, hp: str, refs: list, transforms: dict) -> np.ndarray | None:
        """引用小零件（如 `HP_JGM_2_HP_JGA_1` 主炮塔上防空炮）的精确挂点：

        = 父挂点矩阵(舰船骨架 HP_JGM_2) × 父模型骨架内子挂点(HP_JGA_1) 的 bind pose 世界矩阵。
        无法解析（找不到父模型/子挂点）返回 None（调用方回退 _derived_mount_transform）。
        """
        if "_HP_" not in hp:
            return None
        parent, child = hp.split("_HP_", 1)
        child = "HP_" + child
        pm = transforms.get(parent)
        if pm is None:
            return None
        parent_folder = None
        for _hp, _comp, _mp, *_ in refs:
            if _hp == parent:
                parent_folder = self._folder_from_model_path(_mp)
                break
        if not parent_folder:
            return None
        child_w = self._skeleton_bone_world(parent_folder, child)
        if child_w is None:
            return None
        return pm @ child_w

    def _ship_snapshot(self, ship: ShipInfo) -> dict:
        """舰船实体 JSON（DB-first：只读主库 entity_snapshots，绝不读 data/split）。

        快照在「加载数据」入库时写入；按 game_key 缓存（同船多次查询复用）。
        数据库无记录返回 {}（装甲厚度/挂载引用为空，舰体仍正常显示）。
        """
        cached = self._ship_snapshot_cache.get(ship.game_key)
        if cached is not None:
            return cached
        data: dict = {}
        try:
            from services.database_service import get_db
            db = get_db(app_ctx.ctx.wows_type)
            if db.exists:
                data = db.load_ship_snapshot(ship.game_key) or {}
        except Exception:  # noqa: BLE001
            data = {}
        self._ship_snapshot_cache[ship.game_key] = data
        return data

    def _load_mount_refs(self, ship: ShipInfo,
                         warnings: list | None = None,
                         skin_nodes: dict | None = None) -> list[tuple[str, str, str, list, list]]:
        """从舰船实体快照收集所有 HP_ 挂载引用：
        [(hp_name, component, model_path, misc_filter, custom_battle)]。

        遍历全部组件分组（不依赖固定键列表），按 base 组件名归类；
        未知组件若含 HP_ + model 挂载引用，记录到 warnings（可见诊断而非静默丢失）。

        misc_filter：该挂点的 `miscFilter` 白名单（MP 节点**全名**；**空列表 =
        空白名单 = 不显示任何**骨架 MP 子设备，对齐游戏 MiscsController）。
        custom_battle：`customMiscs.battle` 预设的 misc 名集合（按 miscName 兜底显示）。
        """
        out: list[tuple[str, str, str, list, list]] = []
        data = self._ship_snapshot(ship)
        if not data:
            return out
        for key, category, group in iter_component_groups(data):
            has_mount = False
            for hp, v in group.items():
                if not hp.startswith("HP_"):
                    continue
                if not isinstance(v, dict):
                    continue
                model = v.get("model")
                if not model:
                    continue
                has_mount = True
                mf = v.get("miscFilter") or []
                if not isinstance(mf, list):
                    mf = []
                cm = v.get("customMiscs") or {}
                if not isinstance(cm, dict):
                    cm = {}
                cb = cm.get("battle") or []
                if not isinstance(cb, list):
                    cb = []
                # 皮肤 nodesConfig 覆盖：替换挂载 model / miscFilter / customMiscs
                if skin_nodes and hp in skin_nodes:
                    ov = skin_nodes[hp]
                    if ov.get("model"):
                        model = ov["model"]
                    if ov.get("miscFilter"):
                        mf = ov["miscFilter"]
                        if not isinstance(mf, list):
                            mf = []
                    if ov.get("customMiscs"):
                        cm = ov["customMiscs"]
                        if not isinstance(cm, dict):
                            cm = {}
                        cb = cm.get("battle") or []
                        if not isinstance(cb, list):
                            cb = []
                out.append((hp, category, str(model),
                            [str(x) for x in mf if isinstance(x, str)],
                            [str(x) for x in cb if isinstance(x, str)]))
            if has_mount and not is_known_component_key(key):
                if warnings is not None:
                    warnings.append(
                        f"组件 {key} 含挂载引用但未被识别，已按「其他」归属加载")
        return out

    # ── assets.bin 骨架挂点 ─────────────────────────────

    def locate_assets_bin(self) -> str | None:
        """定位 assets.bin（3D 查看器骨架挂点权威来源）。

        只使用**当前加载客户端**的 assets.bin，绝不用别的客户端/来源不明的缓存：
        1) 加载数据流程（extractor_service._extract_assets_bin）已提取的 data/assets.bin
           （3D 查看器现场提取也写入同一路径，供下次复用）
        2) 现场用解包器从当前客户端 .pkg 提取 content/assets.bin
        """
        import os
        game = app_ctx.ctx.game_path
        if not game:
            return None
        try:
            from utils.path_utils import get_data_dir
            data_dir = get_data_dir()
        except Exception:  # noqa: BLE001
            data_dir = None
        # 1) 复用加载数据流程（extractor_service._extract_assets_bin）已提取的 data/assets.bin
        if data_dir is not None:
            target = data_dir / "assets.bin"
            if os.path.exists(target):
                return str(target)
        # 2) 现场从当前客户端 .pkg 提取（骨架挂点须与模型同版本），产物写入 data/assets.bin 复用
        try:
            ext = self._get_extractor()
            candidates = [
                e for e in ext.list_files(["content/assets.bin"]) if not e.is_directory
            ]
            if not candidates:
                return None
            entry = candidates[0]
            data = ext.pkg_reader.read_file(entry.volume.filename, entry.file_info)
            if not data:
                return None
            if data_dir is None:
                from utils.path_utils import get_data_dir
                data_dir = get_data_dir()
            out = data_dir / "assets.bin"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            return str(out)
        except Exception:  # noqa: BLE001
            return None

    def _get_assets_service(self):
        if self._assets_svc is not None:
            return self._assets_svc
        if self._assets_tried:
            return None
        self._assets_tried = True
        try:
            from uncode_assets.service import AssetsBinService
            path = self.locate_assets_bin()
            if path:
                self._assets_svc = AssetsBinService(assets_path=path)
        except Exception:  # noqa: BLE001
            self._assets_svc = None
        return self._assets_svc

    def _get_assets_cache(self):
        """AC11: AssetsCacheService 单实例惰性缓存（替代 9 处每次 new 新 sqlite 连接）。

        按服务器分库：切服（Lesta↔WG）后缓存失效重建，避免读到上一服务器的 assets_data.db。
        """
        from app.application import app as app_ctx
        cur = app_ctx.ctx.wows_type
        if self._assets_cache is None or self._assets_cache_wows_type != cur:
            from services.assets_cache_service import AssetsCacheService
            self._assets_cache = AssetsCacheService(wows_type=cur)
            self._assets_cache_wows_type = cur
        return self._assets_cache

    @staticmethod
    def _matrix_to_render(m: list) -> np.ndarray:
        """骨架挂点矩阵（列主序 16 float）→ 行主序 4x4（原始矩阵，不做坐标变换）。

        方向/位置匹配改由 **基于骨骼** 完成（_load_mounts 组合模型 Root_BlendBone
        并用 negz 共轭转渲染空间），这里仅转换矩阵布局。
        """
        from utils.asset_utils import mat_col_to_row_np
        return mat_col_to_row_np(m)

    def _mount_root_blend(self, folder: str) -> np.ndarray:
        """挂载模型骨架的 `Root_BlendBone` 矩阵（静息朝向修正，仅用于**视觉**网格）。

        从 assets_data.db 该模型的 SkeletonPrototype 读取；找不到回退恒等。按 folder 缓存。
        实测值因模型而异（大和主炮塔 JGM178 = diag(1,1,-1,1) Z 镜像，自逆）。
        ⚠️ 装甲几何不使用此修正（装甲已与挂点对齐，见 armor_mtx）。
        """
        key = f"rblend:{folder}"
        cached = self._mount_model_cache.get(key)
        if cached is not None:
            return cached
        # 回退**恒等**：找不到 Root_BlendBone 的模型（多数防空/火控，骨架只有
        # 2-4 bone）几何已含自身朝向，不施加任何补偿（用户要求删除 R180 回退，
        # 否则这些模型整体翻转）
        rb = np.eye(4, dtype=np.float32)
        try:
            c = self._get_assets_cache()
            bones = c.get_skeleton_bones(app_ctx.ctx.bin_folder or "", folder)
            if bones and "Root_BlendBone" in bones:
                rb = bones["Root_BlendBone"]
        except Exception as exc:  # noqa: BLE001
            bus.log_message.emit(f"⚠️ Root_BlendBone 读取失败({folder}): {exc}，已回退恒等矩阵")
        self._mount_model_cache[key] = rb
        return rb

    def _skeleton_bones_all(self, folder: str) -> dict:
        """某模型骨架的**全部骨骼世界矩阵**表（bind pose，只读 assets_data.db）。

        与 `_skeleton_bone_world` 共用 `skelworld:{folder}` 缓存；返回
        {bone_name: (4,4)}（含 MP_/HP_ 挂点节点，供子设备递归放置用）。
        """
        key = f"skelworld:{folder}"
        cached = self._mount_model_cache.get(key)
        if cached is not None:
            return cached
        world: dict = {}
        try:
            world = self._get_assets_cache().get_skeleton_bones(
                app_ctx.ctx.bin_folder or "", folder)
        except Exception:  # noqa: BLE001
            world = {}
        self._mount_model_cache[key] = world
        return world

    def _mp_model_folder(self, mp_name: str) -> str:
        """MP_ 节点 → 模型目录：WG 用完整 miscName（如 AM003_Fairlead_1），Lesta 用 baseID（AM003）。

        WG 的甲板设备模型目录按 misc 全名命名（wows-toolkit misc_name_from_node：
        去 MP_ 前缀 + 去实例后缀），Lesta 按 baseID（首个字母+数字 token）命名；
        用错则 `misc/{folder}/{folder}.geometry` 找不到 → 甲板设备不显示。
        """
        if app_ctx.ctx.wows_type == "Wargaming":
            return self._misc_name_from_node(mp_name)
        return mp_base_id(mp_name)

    @staticmethod
    def _misc_name_from_node(node_name: str) -> str:
        """MP_ 节点名 → misc 模型名（去 MP_ 前缀 + 尾部实例索引）。

        对齐 wows-toolkit `misc_name_from_node`：去 MP_ 前缀，剥尾部
        `.NNN`（带点三位数）或 `_INDEX_N`（传统索引）后缀。
        例：MP_BM800_Ventilators_mushroom_INDEX_16 → BM800_Ventilators_mushroom
        """
        if not node_name.startswith("MP_"):
            return node_name
        rest = node_name[3:]
        if "." in rest:
            pos = rest.rfind(".")
            tail = rest[pos + 1:]
            if len(tail) == 3 and tail.isdigit():
                return rest[:pos]
        idx = rest.rfind("_INDEX_")
        if idx >= 0:
            return rest[:idx]
        return rest


    def _place_skeleton_mps(self, geom, folder: str, skel_to_ship_game: np.ndarray,
                            model_cache: dict, extractor, armor_thickness: dict,
                            component: str, bmin: np.ndarray, bmax: np.ndarray,
                            depth: int, visited: frozenset,
                            cancel_event: threading.Event | None = None,
                            mp_allow: frozenset | None = None,
                            battle_customs: frozenset | None = None) \
            -> tuple[int, np.ndarray, np.ndarray]:
        """递归放置挂载模型骨架上的 MP 子设备（炮塔测距仪/炮管防空炮/弹药箱等）。

        全库约 1% 的 MP 节点父节点不是 Scene Root，而是挂在炮塔/火控等挂载模型
        自己的骨架里（`Rotate_Y`/`Roll_Back1` 等骨骼下）。这些子设备此前被遗漏。

        参数：
          folder: 当前挂载模型目录（读其骨架的 MP_ 节点）
          skel_to_ship_game: 当前模型**骨架空间 → 舰船游戏空间**矩阵（未 negz 共轭）。
              挂载模型骨架→船 = 其 HP 挂点矩阵 m_raw（几何→骨架 = Root_BlendBone 已约去）。
          component: 归属分类（继承父挂载，如主炮塔；甲板设备为 COMPONENT_DECK）
          visited: 递归路径上已出现的模型目录（防环）
          mp_allow: 当前层 MP 节点白名单（来自挂点 miscFilter；None=不过滤
              （甲板设备/递归子设备），空集合=空白名单=不显示任何节点）。
          battle_customs: customMiscs.battle 预设的 misc 名集合（按 miscName 兜底）。

        变换链（与舰体级 MP 同一规律：几何→自身骨架 = Root_BlendBone）：
          子设备骨架→船 = skel_to_ship_game @ W_sub（MP 节点世界矩阵）
          子设备几何→船（视觉）= 上式 @ rb_sub，再 negz 共轭转渲染空间。
          子设备装甲 = 上式（不乘 rb_sub）再 negz 共轭（装甲已与挂点对齐）。
        返回 (放置数, bmin, bmax)。
        """
        if depth > 3 or folder in visited:
            return 0, bmin, bmax
        bones = self._skeleton_bones_all(folder)
        mp_nodes = {k: v for k, v in bones.items() if k.startswith("MP_")}
        if not mp_nodes:
            return 0, bmin, bmax
        _negz = np.diag([1.0, 1.0, -1.0, 1.0])
        placed = 0
        visited_next = visited | {folder}
        for mp_name, W in mp_nodes.items():
            self._raise_if_cancelled(cancel_event)
            # miscFilter 白名单过滤：仅放置白名单内节点（空白名单 = 不放置任何），
            # 或 miscName 命中 customMiscs.battle 预设的兜底显示
            if mp_allow is not None and mp_name not in mp_allow \
                    and self._misc_name_from_node(mp_name) not in (battle_customs or ()):
                continue
            sub_folder = self._mp_model_folder(mp_name)
            if not sub_folder or sub_folder in visited_next:
                continue
            sub_skel_to_ship = skel_to_ship_game @ W
            rb_sub = self._mount_root_blend(sub_folder)
            mtx = np.ascontiguousarray(
                _negz @ (sub_skel_to_ship @ rb_sub) @ _negz, dtype=np.float32)
            # 装甲用原始变换（不做 Root_BlendBone 修正，同 HP 挂载）
            armor_mtx = np.ascontiguousarray(
                _negz @ sub_skel_to_ship @ _negz, dtype=np.float32)
            if sub_folder not in model_cache:
                model_cache[sub_folder] = self._load_mount_model(
                    sub_folder, extractor, armor_thickness, component,
                    cancel_event=cancel_event)
            src = model_cache[sub_folder]
            if src is None:
                continue
            for hm in src["meshes"]:
                mm = MountMesh(
                    name=mp_name, component=component,
                    positions=hm.positions, normals=hm.normals,
                    uvs=hm.uvs, indices=hm.indices,
                    model_matrix=(armor_mtx if hm.skinned_applied else mtx),
                    texture_dds=hm.texture_dds, texture_path=hm.texture_path,
                    model_folder=sub_folder, vertex_count=hm.vertex_count,
                    is_wire=hm.is_wire,
                    is_crack=hm.is_crack,
                    has_color=hm.has_color,
                    bone_indices=hm.bone_indices, bone_weights=hm.bone_weights,
                    skin_bones=hm.skin_bones, skin_bind=hm.skin_bind,
                    shape_names=hm.shape_names, node_names=hm.node_names,
                )
                geom.mounts.append(mm)
                if mm.positions.size:
                    mn, mx = mm.bounds_in_world()
                    bmin = np.minimum(bmin, mn)
                    bmax = np.maximum(bmax, mx)
            for am in src["armor_meshes"]:
                mesh = ArmorMesh(
                    name=am.name, positions=am.positions, normals=am.normals,
                    colors=am.colors, indices=am.indices, triangles=am.triangles,
                    component=component, model_matrix=armor_mtx,
                )
                geom.armor_meshes.append(mesh)
                if mesh.positions.size:
                    mn, mx = mesh.bounds_in_world()
                    bmin = np.minimum(bmin, mn)
                    bmax = np.maximum(bmax, mx)
            placed += 1
            # 子设备自身骨架可能还有 MP（递归，防环）
            sub_n, bmin, bmax = self._place_skeleton_mps(
                geom, sub_folder, sub_skel_to_ship, model_cache, extractor,
                armor_thickness, component, bmin, bmax, depth + 1, visited_next,
                cancel_event=cancel_event)
            placed += sub_n
        return placed, bmin, bmax

    def _load_mount_transforms(self, ship: ShipInfo) -> dict:
        """收集舰体骨架 HP_ 挂点矩阵（**只从 assets_data.db 读取**）。

        返回 {hp_name: (4,4) 行主序渲染空间矩阵}；数据库无数据返回 {}（不读 assets.bin）。
        按 model stem 缓存（姊妹舰/共享船体复用）。
        """
        stem = ship.model_folder
        cached = self._stem_mount_cache.get(stem)
        if cached is not None:
            return cached
        out: dict[str, np.ndarray] = {}
        try:
            c = self._get_assets_cache()
            out = c.get_skeleton_mounts(app_ctx.ctx.bin_folder or "", stem)
        except Exception:  # noqa: BLE001
            out = {}
        self._stem_mount_cache[stem] = out
        return out

    # ── 挂载模型几何/贴图加载 ───────────────────────────

    @staticmethod
    def _murmur3_32(data: bytes, seed: int = 0) -> int:
        """MurmurHash3_x86_32：Korabli 字符串哈希（渲染集 shape 名 ↔ geometry mapping_id）。"""
        from utils.asset_utils import murmur3_32
        return murmur3_32(data, seed)

    def _section_render_sets(self, section_geom_path: str) -> list[dict]:
        """从 assets.bin 提取某分段几何的渲染集（shape → material → mfm）。

        返回 [{shape: 'BowShape.vertices', material: 'TL2_SHIPMAT_PBS_Hull',
               mfm: '...Hull.mfm'}]；按 material 分组后的主渲染集（排除 crack/patch 损伤变体）。

        注意：Korabli ST assets.bin 的 r2p→visual 记录偏移 5510（读错记录），
        这里改为**扫描** visual blob 找 +0x20/+0x60 引用该几何的记录，再解析其
        record-relative OOL 渲染集（起始 +0x40、步长 0x50）。
        """
        cache_key = section_geom_path
        cached = self._visual_rs_cache.get(cache_key)
        if cached is not None:
            return cached
        svc = self._get_assets_service()
        result: list[dict] = []
        if svc is not None:
            try:
                result = self._parse_visual_render_sets(svc, section_geom_path)
            except Exception:  # noqa: BLE001
                result = []
        self._visual_rs_cache[cache_key] = result
        return result

    def _parse_visual_render_sets(self, svc, section_geom_path: str) -> list[dict]:
        from uncode_assets.parser import BLOB_HEADER_SIZE
        db = svc.db
        entry = db.databases[2]   # VisualPrototype blob
        data = entry.data
        if self._assets_self_id_index is None:
            self._assets_self_id_index = db.build_self_id_index()
        idx = self._assets_self_id_index

        def path_of(h):
            if h in (0, 0xFFFFFFFFFFFFFFFF):
                return ''
            i = idx.get(h)
            return db.reconstruct_path(i, idx) if i is not None else ''

        target = section_geom_path.rstrip('/')
        # 1) 一次性索引：geometry 路径 → 引用它的 visual 记录（+0x20 geometry）
        #    ⚠️ 2026-08-19 修正：VisualPrototype item_size=0x40（非 0x80）。
        #    每条记录唯一 geometry（+0x20）+ primitives（+0x28），无 +0x60 第二引用。
        if self._visual_geom_index is None:
            geom_idx: dict = {}
            for ri in range(entry.record_count):
                off = BLOB_HEADER_SIZE + ri * entry.item_size
                if off + 0x40 > len(data):
                    break
                rec = data[off:off + 0x40]
                h = struct.unpack_from('<Q', rec, 0x20)[0]
                if h in idx:
                    gp = db.reconstruct_path(idx[h], idx)
                    geom_idx.setdefault(gp, []).append(ri)
            self._visual_geom_index = geom_idx
        recs = self._visual_geom_index.get(target) or []
        if not recs:
            return []

        # 2) 解析 OOL 渲染集（rel 起、0x50 步长、count 项）：
        #    渲染集结构（0x50 步长）：+0x00 shape.vertices / +0x04 indices /
        #    +0x08 材质名 / +0x20 .mfm 路径 selfId.
        out: dict[str, dict] = {}
        for ri in recs:
            rec_off = BLOB_HEADER_SIZE + ri * entry.item_size
            rec = data[rec_off:rec_off + 0x40]
            cnt = struct.unpack_from('<Q', rec, 0x30)[0]
            rel = struct.unpack_from('<Q', rec, 0x38)[0]
            if not rel or cnt <= 0 or cnt > 500:
                continue
            base = rec_off + rel
            if base + cnt * 0x50 > len(data):
                continue
            for k in range(cnt):
                o = base + k * 0x50
                shape_h = struct.unpack_from('<I', data, o)[0]
                shape = db.strings.get_string_by_id(shape_h) or ''
                if not shape.endswith('.vertices'):
                    continue
                iid = struct.unpack_from('<I', data, o + 4)[0]
                mat_h = struct.unpack_from('<I', data, o + 8)[0]
                mfm_h = struct.unpack_from('<Q', data, o + 0x20)[0]
                sind = db.strings.get_string_by_id(iid) or ''
                mat = db.strings.get_string_by_id(mat_h) or ''
                smfm = path_of(mfm_h)
                # 仅跳过 crack 损伤与低模 LOD；patch/wire/hide 保留渲染
                damage = ('_crack_' in shape or '_lod' in shape or 'Crack' in mat)
                if shape not in out:
                    out[shape] = {'shape': shape, 'indices': sind,
                                  'material': mat, 'mfm': smfm, 'damage': damage}
        return list(out.values())

    def _geometry_folder_index(self, extractor) -> dict:
        """懒构建：{模型目录名: [VfsEntry .geometry]}，一次构建跨船复用。

        `list_files` 对每个模式全树 fnmatch（数万条目×多次）极慢，这里改用
        一次性目录索引做 O(1) 查找。排除 LOD 子目录与 `_lodN` 后缀文件。
        """
        if self._geom_folder_index is not None:
            return self._geom_folder_index
        idx: dict = {}
        try:
            for path, entry in extractor.file_tree.items():
                if entry.is_directory or not path.endswith(".geometry"):
                    continue
                # 排除 LOD 子目录与损伤/残骸变体几何（主模型目录常含 *_dead/_broken.geometry，
                # 不过滤会被当独立网格重复渲染 → 同一挂点出现多个炮塔）
                fname = path.rsplit("/", 1)[-1]
                if "/lods/" in path or "_lod" in fname:
                    continue
                if any(x in fname for x in ("_dead", "_broken", "_destroyed", "_burn")):
                    continue
                parts = path.split("/")
                if len(parts) < 2:
                    continue
                folder = parts[-2]
                idx.setdefault(folder, []).append(entry)
        except Exception as exc:  # noqa: BLE001
            bus.log_message.emit(f"⚠️ 几何目录索引构建失败: {exc}")
        self._geom_folder_index = idx
        return idx

    def _load_mount_model(self, folder: str, extractor, armor_thickness: dict,
                          component: str,
                          cancel_event: threading.Event | None = None) -> dict | None:
        """加载一个挂载模型目录的几何+贴图+装甲（本地坐标）。失败返回 None。

        使用目录索引 O(1) 查找；结果按 folder 缓存（跨船复用，多船共享炮塔等）。
        返回 {meshes: [HullMesh...], texture_dds, texture_path, armor_meshes}
        - **按材质拆分成多个 mesh**（每材质分片独立贴图）：挂载模型常含多个
          材质（如雷达 Turret=PBS + Net=GRID、指挥仪玻璃、天线网），合并成单
          网格单贴图会让其他分片 UV 错位 → 贴图错误。
        """
        cached = self._mount_model_cache.get(folder)
        if cached is not None:
            return cached
        entries = self._geometry_folder_index(extractor).get(folder) or []
        if not entries:
            bus.log_message.emit(f"⚠️ 挂载模型 {folder}: 未找到几何文件，该挂载不显示")
            self._mount_model_cache[folder] = None
            return None
        # 蒙皮 bind pose 骨架 stem（舰船模型目录；_apply_skinning 用它查骨骼矩阵）
        self._current_skinning_stem = folder

        all_armor = []
        meshes: list = []
        # 挂载模型也按船体逻辑：渲染集（visual→mfm→贴图）+ LOD/低模/wire 兜底跳过
        mount_rs = self._ship_render_sets(folder)
        # mount_rs 含 damage 标记，但部分 LOD/crack 渲染集不在数据库时用
        # shape_names 表（DB）按名兜底跳过；★ 只从数据库读取，绝不现场读 assets.bin
        sdict = self._shape_names_sdict()
        main_tex = ("", b"")
        first_geom_path = entries[0].path
        for e in entries:
            self._raise_if_cancelled(cancel_event)
            try:
                data = extractor.pkg_reader.read_file(e.volume.filename, e.file_info)
            except Exception as exc:  # noqa: BLE001
                bus.log_message.emit(f"⚠️ 挂载模型读取失败 {e.path}: {exc}")
                continue
            try:
                parsed = parse_geometry(data, file_path=e.path, cancel_event=cancel_event)
            except GeometryError as exc:  # noqa: BLE001
                bus.log_message.emit(f"⚠️ 挂载模型解析失败 {e.path}: {exc}")
                continue
            finally:
                del data
            all_armor.extend(parsed.armor_models)
            if parsed.primitives:
                groups = self._split_primitives_by_material(parsed.primitives, mount_rs, sdict,
                                                            geom_path=e.path)
                for mat, g in groups.items():
                    # 保留所有分组（含 None 组：shape 无渲染集材质时用默认/文件名约定贴图，
                    # 如指挥仪 ControlTowerShape —— 否则指挥仪/雷达等会整组丢失不显示）
                    if not g.get('prims'):
                        continue
                    mfm = g.get('mfm') or ''
                    hm = self._merge_hull(f"{folder}|{mat or 'default'}", g['prims'],
                                          shape_names=g.get('shape_names', []),
                                          node_names=g.get('node_names', []),
                                          instance_matrices=g.get('instance_matrices') or [])
                    hm.material = mat
                    hm.is_wire = (mat == '__wire__' or mat == 'WIRE')
                    hm.is_crack = bool(g.get('damage'))
                    hm.skinned_applied = bool(g.get('skinned_applied'))
                    if mfm:
                        # ★ 只认 mfm 声明的贴图属性（indexed→albedoArray，否则 diffuseMap）；
                        #   未声明颜色贴图 → has_color=False（无色，不按名补全 diffuse）。
                        #   INDEXED 数组不变，继续按老样子参与渲染。
                        _bundle = self._resolve_material_full(mfm, extractor)
                        self._apply_declared_color(hm, _bundle, extractor)
                    else:
                        # 无 mfm 的默认组：取模型自身 mfm 声明的 diffuseMap（只认声明）
                        tex_path, tex_bytes = self._find_model_diffuse(
                            first_geom_path, folder, extractor)
                        hm.texture_path, hm.texture_dds = tex_path, tex_bytes
                        hm.has_color = bool(tex_bytes)
                    meshes.append(hm)
                    if not main_tex[1] and hm.texture_dds:
                        main_tex = (hm.texture_path, hm.texture_dds)

        if not meshes and not all_armor:
            bus.log_message.emit(f"⚠️ 挂载模型 {folder}: 解析后无网格/装甲，该挂载不显示")
            self._mount_model_cache[folder] = None
            return None

        armor_meshes = []
        for am in all_armor:
            mesh = self._build_armor_mesh(am, armor_thickness, component=component)
            if mesh is not None:
                armor_meshes.append(mesh)
        result = {
            "meshes": meshes,
            "texture_dds": main_tex[1], "texture_path": main_tex[0],
            "armor_meshes": armor_meshes,
        }
        self._mount_model_cache[folder] = result
        return result

    def _mfm_index(self) -> dict:
        """懒构建 材质名(去 .mfm) → 完整路径 索引（一次，跨船复用）。"""
        if self._mfm_index_cache is not None:
            return self._mfm_index_cache
        svc = self._get_assets_service()
        idx: dict = {}
        if svc is not None:
            try:
                for f in svc.vfs.all_files():
                    if f.prototype_type is not None \
                            and f.prototype_type.name == "MaterialPrototype" \
                            and f.path.endswith(".mfm"):
                        idx[f.path.rsplit("/", 1)[-1][:-4]] = f.path
            except Exception:  # noqa: BLE001
                idx = {}
        self._mfm_index_cache = idx
        return idx

    def _mfm_diffuse_base(self, stem: str, prefer: tuple[str, ...] = ()) -> str:
        """基于 .mfm 识别贴图（**只从 assets_data.db 读取**）：diffuseMap 原始路径。

        数据由「加载数据」时预提取入库（assets_cache_service.populate）。
        按 stem 前缀匹配材质（排除 _wire/_dead/_blaze 变体），优先 prefer 精确名；
        找不到返回 ""（调用方回退到文件名约定）。
        """
        cached = self._mfm_diffuse_cache.get(stem)
        if cached is not None:
            return cached
        result = ""
        try:
            if self._mfm_textures_db is None:
                c = self._get_assets_cache()
                self._mfm_textures_db = c.get_mfm_textures(
                    app_ctx.ctx.bin_folder or "") or {}
            if self._mfm_textures_db:
                cands = []
                for mfm_path, tex_path in self._mfm_textures_db.items():
                    if not tex_path:
                        continue
                    name = mfm_path.rsplit("/", 1)[-1][:-4]
                    # ★ 只认精确 mfm 名：不再 `startswith(stem + "_")` 前缀补全，
                    #   避免把一个变体(如 _decal_tech/_wire/_alpha)声明的 diffuse 串到主材质。
                    if name == stem or name in prefer:
                        if any(x in name for x in ("_wire", "_dead", "_blaze", "_alpha")):
                            continue
                        # 库存原始路径（含扩展名），渲染分级仍用基础名
                        base = tex_path[:-4] if tex_path.endswith(".dds") else tex_path
                        cands.append((name, base))
                if cands:
                    def _key(item):
                        name, _b = item
                        for i, pref in enumerate(prefer):
                            if name == pref:
                                return (i, 0)
                        return (len(prefer), 1)
                    cands.sort(key=_key)
                    result = cands[0][1]
        except Exception as exc:  # noqa: BLE001
            result = ""
            bus.log_message.emit(f"⚠️ mfm 贴图识别失败({stem}): {exc}")
        self._mfm_diffuse_cache[stem] = result
        return result

    @staticmethod
    def _vfs_entry(extractor, path: str):
        """O(1) 文件树查找（file_tree 是按路径索引的 dict，避免 list_files 全树扫描）。"""
        try:
            return extractor.file_tree.get(path)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _read_vfs(extractor, path: str) -> bytes:
        """按路径读取文件字节；不存在/失败返回 b""。"""
        e = GeometryService._vfs_entry(extractor, path)
        if e is None or e.is_directory or e.file_info is None:
            return b""
        try:
            return extractor.pkg_reader.read_file(e.volume.filename, e.file_info)
        except Exception:  # noqa: BLE001
            return b""

    def _load_texture_tier(self, base: str, extractor) -> tuple[str, bytes]:
        """按 .dd0/.dd1/.dd2/.dds 分级读取贴图（.dd0 最高清），返回 (vfs_path, bytes)。

        ⚠️ 按 base 路径缓存解压字节：共享图集（CIT000_1k_ship_tiles_*.dds 等 20MB+）
        被大量 INDEXED 材质复用，若不缓存则每个 mfm 都重新 Kraken 解压（~30s/个）
        导致加载卡死。缓存只跨同一次 load_ship（_clear_per_load_caches 清理）。
        """
        if base in self._texture_bytes_cache:
            return base + ".dds", self._texture_bytes_cache[base]
        for tier in (".dd0", ".dd1", ".dd2", ".dds"):
            cand = base + tier
            data = GeometryService._read_vfs(extractor, cand)
            if data and data[:4] == b"DDS ":
                # 校验可解析出 mip/层（bc7prep 的 .dd0 若未正确解码会得到空 mip，
                # 上传后是空纹理 → 采样 (0,0,0,1) 黑不透明 → 全黑），回退下一层级
                try:
                    from models.dds_reader import parse_dds
                    d = parse_dds(data)
                    if not (d.mips or d.layers):
                        continue
                except Exception:
                    continue
                # 只缓存非空解压结果（共享图集多为 .dds；.dd0 大文件也缓存）
                if len(data) > 256 * 1024:
                    self._texture_bytes_cache[base] = data
                return cand, data
        return "", b""

    def _find_model_diffuse(self, geometry_path: str, folder: str, extractor) -> tuple[str, bytes]:
        """挂载模型贴图：**只认 .mfm 声明**的 diffuseMap（不再按文件名约定补全）。"""
        # 1) .mfm 识别：{folder}.mfm / {folder}_skinned.mfm → diffuseMap → _a 基础名
        base = self._mfm_diffuse_base(folder, prefer=(folder, f"{folder}_skinned"))
        if base:
            path, data = self._load_texture_tier(base, extractor)
            if data:
                return path, data
        # ★ 不再按文件名约定补全（_a.dd0/_Hull_camo 等）：只认 mfm 声明的 diffuseMap，
        #   缺失就当不存在。下面走渲染集 mfm 兜底（同型号变体共享材质）仍是只认声明。
        # 3) 渲染集 mfm 兜底：同型号变体共享材质（如 JGA181→JGA010、JGA020 无自有时）
        try:
            seen_mfm: set = set()
            mfms: list = []
            for r in self._ship_render_sets(folder).values():
                m = r.get("mfm") or ""
                if not m or m in seen_mfm:
                    continue
                seen_mfm.add(m)
                mfms.append(m)
            # 优先与当前 folder 型号 token 匹配的 mfm：TurretShape 等通用 shape 名的
            # 渲染集只存在于**同型号主炮/主模型**记录里（如 AGS542_5in54_Mark42 副炮
            # 无独立 TurretShape 渲染集，共享 AGM127_5in54_Mark42 主炮的贴图；
            # 若按记录顺序取第一个 mfm 会串到别的型号 → 副炮贴图错误）
            tok = self._model_family_token(folder)
            if tok:
                mfms.sort(key=lambda m: 0 if tok in m else 1)
            for m in mfms:
                p2, d2 = self._resolve_material_texture(m, extractor)
                if d2:
                    return p2, d2
        except Exception:  # noqa: BLE001
            pass
        return "", b""

    @staticmethod
    def _model_family_token(folder: str) -> str:
        """提取型号 token（如 '5in54_Mark42'），用于同型号跨目录贴图共享匹配。

        型号段形如 `数字+字母+数字+_名称`（跳过目录名开头的编号段如 AGS542_）。
        """
        import re
        m = re.search(r"\d+[a-z]+\d+_\w+", folder)
        return m.group(0) if m else ""

    def _find_hull_diffuse(self, ship: ShipInfo, extractor) -> tuple[str, bytes]:
        """舰体贴图：**只认 .mfm 声明**的 diffuseMap（Hull.mfm 权威，不再按文件名约定补全）。

        颜色贴图以 `_a` 后缀为准，优先 `.dd0`（4096×4096 高清 DDS）。
        """
        # 1) .mfm 识别：{stem}_Hull.mfm / {stem}.mfm → diffuseMap（只认声明）
        stem = ship.model_folder
        base = self._mfm_diffuse_base(stem, prefer=(f"{stem}_Hull", stem))
        if base:
            path, data = self._load_texture_tier(base, extractor)
            if data:
                return path, data
        # ★ 不再按文件名约定补全（_Hull_a.dd0/_Hull_camo 等）：只认 mfm 声明的 diffuseMap。
        return "", b""

    def _split_primitives_by_material(self, primitives, global_rs: dict,
                                      sdict: dict | None = None,
                                      geom_path: str | None = None,
                                      instancing: bool = False) -> dict:
        """按渲染集索引把 primitives 分组：{material_key: {material, mfm, prims}}。

        - 用 murmur3(shape.vertices) == primitive.mapping_id 连接渲染集与几何
        - **damage/crack 渲染集**（crack/patch 等损伤网格）保留到 `__crack__` 组
          （查看器不显示，GLB 导出保留用；带 crack mfm）
        - LOD 低模仍跳过（不同 LOD 级，非 crack）
        - 匹配到材质的按材质分组；未匹配的归 None（用舰体默认贴图）
        - sdict 兜底：无渲染集匹配的 primitive 用字符串表反查 shape 名，
          LOD 低模跳过；`_crack_`/Crack 名归 `__crack__` 组
        - 多个 shape 同材质（如 Hull 本体 + DeckHouse）自动合并
        """
        mat_by_mid: dict = {}
        damage_mids: set = set()
        norm_to_rs: dict = {}   # 归一化 shape stem → 渲染集（模糊兜底：处理视觉/几何笔误）
        rs_by_mid: dict = {}    # 任意一个 entry（按 mid 兜底）
        rs_by_gp_mid: dict = {} # (geom_path, mid) → 分段精确（刚性绑定用）
        for key, rs in global_rs.items():
            mid = key[1] if isinstance(key, tuple) else key
            mat_by_mid[mid] = (rs.get('material') or '', rs.get('mfm') or '')
            rs_by_mid.setdefault(mid, rs)
            if isinstance(key, tuple):
                rs_by_gp_mid[key] = rs
            if rs.get('damage'):
                damage_mids.add(mid)
                continue
            nk = GeometryService._norm_shape_stem(rs.get('shape') or '')
            if nk and nk not in norm_to_rs:
                norm_to_rs[nk] = rs

        def _rs_for(mid: int):
            """优先当前几何分段的渲染集条目（保留各自骨骼节点），否则任一兜底。"""
            if geom_path:
                rs = rs_by_gp_mid.get((geom_path, mid))
                if rs is not None:
                    return rs
            return rs_by_mid.get(mid)
        groups: dict = {}

        def _new_group(mat: str, mfm: str, damage: bool = False) -> dict:
            return {'material': mat, 'mfm': mfm, 'prims': [],
                    'shape_names': [], 'node_names': [], 'damage': damage}

        def _crack_group(mat: str, mfm: str) -> dict:
            """damage/crack 网格组（按材质分键，避免多种 crack 材质混入同一网格）。"""
            key = f"__crack__#{mat}" if mat else "__crack__"
            return groups.setdefault(key, _new_group(mat, mfm, damage=True))

        def _add_names(g: dict, p, rs=None) -> None:
            """收集该 primitive 的形状名（sdict 反查）与**全部**骨骼节点名到分组，供调试标签用。"""
            if sdict is not None:
                _sn = sdict.get(p.mapping_id) or ''
                if _sn and _sn not in g['shape_names']:
                    g['shape_names'].append(_sn)
            nodes = (rs or {}).get('nodes') or []
            for _nn in nodes:
                if _nn and _nn not in g['node_names']:
                    g['node_names'].append(_nn)

        for p in primitives:
            if p.mapping_id in damage_mids:
                # 损伤网格：DB 把 LOD 与真 crack 都标 damage=1，按 shape 名区分——
                # `_lod` 低模跳过（非 crack）；保留真 crack（`_crack_`/Crack 名或
                # crack 材质变体，如 BowShape 的 crack 渲染集）到 __crack__ 组
                _rs = _rs_for(p.mapping_id) or {}
                _sname = (_rs.get('shape') or '')
                if '_lod' in _sname.lower():
                    continue
                mat, mfm = mat_by_mid.get(p.mapping_id, ('', ''))
                _crack_group(mat, mfm)['prims'].append(p)
                continue
            entry = mat_by_mid.get(p.mapping_id)
            if entry is None:
                # 无渲染集匹配：字符串表反查 shape 名，LOD 低模跳过；crack 名保留
                if sdict is not None:
                    _name = sdict.get(p.mapping_id) or ''
                    if '_lod' in _name:
                        continue
                    if '_crack_' in _name or 'Crack' in _name:
                        _crack_group('', '')['prims'].append(p)
                        continue
                    # 模糊兜底：归一化 shape 名匹配渲染集（游戏数据笔误，
                    # 如 JGA180 视觉写 TurretShapeff.vertices、几何是 TurretShape.vertices）
                    if _name:
                        fuz = norm_to_rs.get(GeometryService._norm_shape_stem(_name))
                        if fuz is not None:
                            mat = fuz.get('material') or ''
                            mfm = fuz.get('mfm') or ''
                            g = groups.setdefault(mat, _new_group(mat, mfm))
                            applied = self._apply_skinning(p, fuz)
                            if applied:
                                g['prims'].append(p)
                                g['skinned_applied'] = True
                                _add_names(g, p, fuz)
                            elif instancing:
                                bake, instmats = self._rigid_instance_matrices(p, fuz)
                                if instmats:
                                    ig = groups.setdefault(
                                        f"__inst__#{mat}#{p.mapping_id}",
                                        _new_group(mat, mfm))
                                    ig['prims'].append(p)
                                    ig['instance_matrices'] = instmats
                                    ig['skinned_applied'] = True
                                    _add_names(ig, p, fuz)
                                elif bake is not None:
                                    self._bake_rigid(p, bake)
                                    g['prims'].append(p)
                                    g['skinned_applied'] = True
                                    _add_names(g, p, fuz)
                                else:
                                    g['prims'].append(p)
                                    _add_names(g, p, fuz)
                            else:
                                clones = self._apply_rigid_multi(p, fuz)
                                if clones:
                                    g['prims'].extend(clones)
                                    g['skinned_applied'] = True
                                else:
                                    g['prims'].append(p)
                                _add_names(g, p, fuz)
                            continue
                groups.setdefault(None, _new_group(None, ''))['prims'].append(p)
            else:
                mat, mfm = entry
                rs = _rs_for(p.mapping_id)
                applied = self._apply_skinning(p, rs)
                g = groups.setdefault(mat, _new_group(mat, mfm))
                if applied:
                    g['prims'].append(p)
                    g['skinned_applied'] = True
                else:
                    if instancing:
                        # 只存各节点坐标：网格一份原始几何，渲染时逐节点各画一次
                        bake, instmats = self._rigid_instance_matrices(p, rs)
                        if instmats:
                            ig = groups.setdefault(
                                f"__inst__#{mat}#{p.mapping_id}", _new_group(mat, mfm))
                            ig['prims'].append(p)
                            ig['instance_matrices'] = instmats
                            ig['skinned_applied'] = True
                            _add_names(ig, p, rs)
                        elif bake is not None:
                            self._bake_rigid(p, bake)
                            g['prims'].append(p)
                            g['skinned_applied'] = True
                            _add_names(g, p, rs)
                        else:
                            g['prims'].append(p)
                            _add_names(g, p, rs)
                    else:
                        # 非蒙皮：按绑定节点实例化（同一 shape 可绑多节点 → 左右舷多实例）
                        clones = self._apply_rigid_multi(p, rs)
                        if clones:
                            g['prims'].extend(clones)
                            g['skinned_applied'] = True
                        else:
                            g['prims'].append(p)
                        _add_names(g, p, rs)
        return groups

    @staticmethod
    def _norm_shape_stem(name: str) -> str:
        """归一化 shape 名（仅去 .vertices 后缀；**不再剥尾部重复字母**）。

        ⚠️ 旧实现会把 TurretShapeff → TurretShape（剥 ff），导致 JGA180 的 TurretShape
        网格在渲染集里模糊匹配到 JGA181 的 TurretShapeff 行，错用 JGA010 贴图。
        实证 PT 26.9：TurretShapeff 是 JGA181.geometry 的真实网格名（mapping_id
        0xb6f4c31d），TurretShape 是 JGA180 的真实网格名（0x03432c0c）——二者是
        不同网格，必须严格区分，不得归并。模糊兜底保留（去后缀后同名才匹配），
        仅处理真正的大小写/后缀笔误。
        """
        return name[:-len('.vertices')] if name.endswith('.vertices') else name

    def _strings_dict(self, db) -> dict:
        """字符串表 → {hash: name} Python dict（一次构建，O(1) 查询）。

        assets.bin 的 StringsSection 是哈希表（offsetsMap），get_string_by_id 每次
        线性探测较慢；构建全局渲染集索引时调用数百万次，改为先转成 Python dict。
        """
        if self._strings_dict_cache is not None:
            return self._strings_dict_cache
        from utils.asset_utils import build_strings_dict
        self._strings_dict_cache = build_strings_dict(db)
        return self._strings_dict_cache

    def _shape_names_sdict(self) -> dict:
        """渲染 shape 名哈希表 {hash32: name}（**只从 assets_data.db 读取**）。

        populate 时把 assets.bin 字符串表里 *.vertices 的名字哈希写入 shape_names 表；
        显示时 _split_primitives_by_material 用它按名跳过缺失渲染集的 LOD/crack 低模。
        数据库缺失/异常返回空 dict（= 不兜底），**绝不现场读 assets.bin**。
        """
        if self._shape_names_tried:
            return self._shape_names_cache or {}
        self._shape_names_tried = True
        out: dict = {}
        try:
            c = self._get_assets_cache()
            out = c.get_shape_names(app_ctx.ctx.bin_folder or "") or {}
        except Exception as exc:  # noqa: BLE001
            out = {}
            bus.log_message.emit(f"⚠️ shape_names 数据读取失败: {exc}")
        self._shape_names_cache = out
        return out

    def _ensure_visual_geom_index(self):
        """构建 {geometry 路径: [引用它的 visual 记录索引]} 全局索引（一次，跨船复用）。"""
        if self._visual_geom_index is not None:
            return
        self._visual_geom_index = {}
        svc = self._get_assets_service()
        if svc is None:
            return
        try:
            import struct as _s
            from uncode_assets.parser import BLOB_HEADER_SIZE
            from uncode_assets.types import type_from_magic
            db = svc.db
            idx = db.build_self_id_index()
            vis = next((b for b in db.databases if (lambda t: t and t.name == 'VisualPrototype')(
                type_from_magic(b.prototype_magic))), None)
            if vis is None:
                return
            data = vis.data
            isize = vis.item_size
            geom_idx: dict = {}
            for ri in range(vis.record_count):
                off = BLOB_HEADER_SIZE + ri * isize
                if off + 0x40 > len(data):
                    break
                rec = data[off:off + 0x40]
                h = _s.unpack_from('<Q', rec, 0x20)[0]
                if h in idx:
                    gp = db.reconstruct_path(idx[h], idx)
                    geom_idx.setdefault(gp, []).append(ri)
            self._visual_geom_index = geom_idx
        except Exception:  # noqa: BLE001
            self._visual_geom_index = {}

    def _ship_render_sets(self, model_folder: str) -> dict:
        """该船全部记录的渲染集索引（**只从 assets_data.db 读取**）。

        {murmur3(shape.vertices): {shape, material, mfm, damage, skinned, nodes}}。
        数据由「加载数据」时预提取入库（render_sets 表，含整合模型共享记录）；
        数据库缺失时返回空（不再从任何 assets.bin 现场扫描）。
        """
        key = f"ship_rs:{model_folder}"
        cached = self._visual_rs_cache.get(key)
        if cached is not None:
            return cached
        idx: dict = {}
        try:
            c = self._get_assets_cache()
            ext = self._get_extractor()
            entries = self._geometry_folder_index(ext).get(model_folder) or []
            if entries:
                paths = [e.path for e in entries]
                rows = c.get_render_sets(app_ctx.ctx.bin_folder or "", paths)
                for r in rows:
                    mid = self._murmur3_32(r["shape"].encode())
                    mat, mfm, damage = r["material"], r["mfm"], r["damage"]
                    entry = {'shape': r["shape"], 'material': mat, 'mfm': mfm,
                             'damage': damage, 'skinned': r.get('skinned', False),
                             'nodes': r.get('nodes') or []}
                    # ★ 按 (geom_path, mid) 索引：同一 shape 名可能出现在多个几何分段
                    #   且各自绑定不同骨骼节点（如 BIA454_Bollard_bigShape 在 MidBack 绑
                    #   _6、MidFront 绑 _0），必须保留各分段的节点，否则只渲染一个。
                    gp = r.get('geom_path') or ''
                    key = (gp, mid)
                    if key in idx:
                        # 跨模型同名 shape：优先当前模型自己的 mfm
                        if mfm and model_folder in mfm:
                            idx[key] = entry
                        continue
                    idx[key] = entry
        except Exception as exc:  # noqa: BLE001
            idx = {}
            bus.log_message.emit(f"⚠️ 渲染集数据读取失败({model_folder}): {exc}，已回退默认贴图")
        self._visual_rs_cache[key] = idx
        return idx

    def _apply_declared_color(self, hm, bundle: dict, extractor):
        """按 .mfm **声明的贴图属性**设置 mesh 颜色贴图（只认声明，不按名补全）。

        - indexed：用 albedoArray（分块图集）
        - 标准：用 diffuseMap
        - 都没声明：has_color=False、texture_dds=None（无色 → 按透明/不参与颜色计算处理）

        bundle 为空（mfm 不在库/解析失败）同样按无色处理，绝不按文件名补全。
        """
        texs = (bundle or {}).get('textures') or {}
        hm.tech_family = (bundle or {}).get('tech_family', 'pbs')
        hm.material_textures = texs
        hm.indexed_params = (bundle or {}).get('indexed_params')
        if hm.tech_family == 'indexed' and 'albedoArray' in texs:
            hm.texture_path, hm.texture_dds = texs['albedoArray']
        elif 'diffuseMap' in texs:
            hm.texture_path, hm.texture_dds = texs['diffuseMap']
        # meshdecal 的 albedo（SHIP_MESHDECAL_ALBEDO_*）用 g_albedoMap：
        # 仍是该材质的颜色贴图（alpha 遮罩），应参与渲染，不能当无色 overlay。
        elif 'g_albedoMap' in texs:
            hm.texture_path, hm.texture_dds = texs['g_albedoMap']
        else:
            # ★ 只认 mfm 声明：没声明颜色贴图就当不存在，不再按名/前缀猜 diffuse
            hm.texture_path, hm.texture_dds = "", None
        hm.has_color = bool(hm.texture_dds)

    def _resolve_material_texture(self, mfm_path: str, extractor) -> tuple[str, bytes]:
        """材质 .mfm 声明的 diffuseMap 贴图（只认 mfm 里声明的属性；未声明 → 不存在）。

        绝不再按 mfm 文件名/前缀自动补全（旧版 _mfm_diffuse_base 前缀匹配会把
        无颜色贴花/变体的 diffuse 串到别的材质，indexed 也受影响）。找不到返回 ("", b"")。
        """
        if not mfm_path or not mfm_path.endswith('.mfm'):
            return "", b""
        cached = self._material_texture_cache.get(mfm_path)
        if cached is not None:
            return cached
        result = ("", b"")
        try:
            bundle = self._resolve_material_full(mfm_path, extractor)
            result = (bundle.get('textures') or {}).get('diffuseMap', ("", b""))
        except Exception:  # noqa: BLE001
            result = ("", b"")
        self._material_texture_cache[mfm_path] = result
        return result

    # ── 材质技术族 + INDEXED 分块渲染 ───────────────────

    @staticmethod
    def _material_family(shader_id: str) -> str:
        """shader_id（0xHHHHLLLL）高 16 位 → 技术族。

        INDEXED 分块(0x0009, ship_material_indexed.fx) / 标准 ship PBS(0x0005,
        PBS_ship_camo*.fx) / 其他。
        """
        from utils.asset_utils import material_family
        return material_family(shader_id)

    def _resolve_material_full(self, mfm_path: str, extractor) -> dict:
        """完整解析材质渲染信息（**只从 assets_data.db 读取**）：技术族 + 贴图集 + INDEXED 分块参数。

        数据由「加载数据」时预提取入库（assets_cache_service.populate 的 material_full 表）。
        - tech_family: indexed(0x0009) / pbs(0x0005) / other
        - textures: {贴图键: (vfs_path, bytes)}（diffuseMap/albedoArray/materialIdMap/artMap/...）
        - indexed_params: {arrays: {名: (N,4)f32}, grid:(rows,cols), offset:(x,y)}
        """
        if not mfm_path or not mfm_path.endswith(".mfm"):
            return {}
        cached = self._material_full_cache.get(mfm_path)
        if cached is not None:
            return cached
        result: dict = {}
        try:
            c = self._get_assets_cache()
            info = c.get_material_full(app_ctx.ctx.bin_folder or "", mfm_path)
            if info:
                sid = info.get("shader_id") or "0x0"
                mh = info.get("material_hash") or ""
                family = info.get("family") or self._material_family(sid)
                # fx 坐标映射（material_hash → fx 名 → 技术族）：识别精确到 fx
                # 变体，替代 shader_id 族/mfm 名启发式。assets.bin 无 fx 名字符串，
                # 但 material_hash 是 fx 变体稳定标识（grid_alpha=0x337D...、
                # grid_alpha_skinned=0x4AF4...）；映射表 resources/fx_mapping_*.md
                # 由人工填写，无合适映射时该列存 shader_id → 退回 shader_id 高 16 位族。
                if mh:
                    family = fx_tech_family(app_ctx.ctx.wows_type or "", sid, mh)
                # 贴图属性 → 实时从客户端 pkg 解包字节（.dds/.dd0 分级）
                textures: dict = {}
                for name, vp in (info.get("textures") or {}).items():
                    if not vp:
                        continue
                    base = vp[:-4] if vp.endswith(".dds") else vp
                    tp, td = self._load_texture_tier(base, extractor)
                    if td:
                        textures[name] = (tp, td)
                result = {"tech_family": family, "shader_id": sid,
                          "material_hash": mh, "textures": textures}
                # INDEXED 分块参数（material_full.indexed 已含 vec4 数组）
                indexed = info.get("indexed") or {}
                if indexed:
                    try:
                        arrs = {k: np.array(v, dtype=np.float32) for k, v in indexed.items()}
                        # 洋红占位 artMap = 缺失/无 camo：把艺术涂装 BaseStrength 置 0，
                        # 否则占位洋红会被满强度混入 → 雷达/炮塔粉红（CIA000_instances_atlas 实测）。
                        art_tx = textures.get("artMap")
                        if art_tx and _is_magenta_placeholder(art_tx[1]):
                            a_arr = arrs.get("artStrengthMatIdArr")
                            if a_arr is not None and a_arr.ndim == 2 and a_arr.shape[1] >= 1:
                                a_arr[:, 0] = 0.0
                        params: dict = {"arrays": arrs}
                        off = arrs.get("offsetScaleMatIdArr")
                        if off is not None and len(off):
                            params["offset"] = (float(off[0, 0]), float(off[0, 1]))
                            params["grid"] = (int(round(off[0, 2])), int(round(off[0, 3])))
                        result["indexed_params"] = params
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as exc:  # noqa: BLE001
            result = {}
            bus.log_message.emit(f"⚠️ 材质数据读取失败({mfm_path}): {exc}")
        self._material_full_cache[mfm_path] = result
        return result

    def _skeleton_bones(self, stem: str) -> dict:
        """某模型骨架全部骨骼世界矩阵 {bone_name: (4,4)}（DB 读取，跨船缓存）。"""
        cached = self._skeleton_bones_cache.get(stem)
        if cached is not None:
            return cached
        out: dict = {}
        try:
            c = self._get_assets_cache()
            out = c.get_skeleton_bones(app_ctx.ctx.bin_folder or "", stem) or {}
        except Exception:  # noqa: BLE001
            out = {}
        self._skeleton_bones_cache[stem] = out
        return out

    def _apply_skinning(self, prim, rs: dict | None) -> bool:
        """对蒙皮图元施加 bind pose 混合（原地修改 positions/normals）。

        返回是否**实际变换了顶点**（True → Root_BlendBone 已烘焙进几何，
        挂载矩阵不得再乘 rb，否则双重镜像导致朝向翻转）。

        背景（PASA111 实证）：Korabli 的蒙皮网格（如 Bow_Antenna / Bow_Antenna_wire，
        材质 *_skinned）顶点存于 **BlendBone 局部帧**，渲染集调色板节点（*_BlendBone /
        Root_BlendBone）的 bind pose 世界矩阵多为 **原点 Z 镜像 diag(1,1,-1)**（det=-1）。
        游戏引擎按权重混合这些矩阵把顶点摆到舰船空间；我们此前直接渲染原始坐标，
        导致 Z 镜像骨骼的网格整体前后（艏艉）翻转 —— 即用户报告的 180° 朝向错误。

        修正：按渲染集调色板 + 顶点骨骼索引/权重做标准线性混合蒙皮：
            p' = Σ_j w_j · (R_j · p + t_j)
        顶点骨骼索引 = 调色板 slot × 3（Korabli 实测），权重 4×u8/255（和=1）。

        - 调色板缺失 / 骨架缺失 / 全部骨骼为恒等 → 不修改（保持原样，安全回退）。
        - 法线用旋转部分（忽略平移）混合后归一化。
        - 反射骨骼（det=-1）会翻转三角形绕序，但渲染器不启用背面剔除，无碍。
        """
        if prim is None or not prim.is_skinned:
            return False
        if prim.bone_indices is None or prim.bone_weights is None:
            return False
        if rs is None or not rs.get('skinned'):
            return False
        palette = rs.get('nodes') or []
        if not palette:
            return False
        # 骨架 stem：渲染集 shape 名 → 模型目录（如 Bow_AntennaShape → ASA031_...）
        # 用当前舰船 model_folder 的骨架（调色板节点名在舰船骨架里）
        stem = getattr(self, '_current_skinning_stem', None)
        if not stem:
            return False
        bones = self._skeleton_bones(stem)
        if not bones:
            return False
        # 收集调色板骨骼世界矩阵（缺失的跳过）
        mats: list[np.ndarray | None] = []
        any_non_identity = False
        for nm in palette:
            m = bones.get(nm)
            mats.append(m)
            if m is not None and not np.allclose(m, np.eye(4), atol=1e-4):
                any_non_identity = True
        if not any_non_identity:
            return False  # 全部恒等 → 无需变换

        idx = prim.bone_indices  # (N,4) uint8
        wts = prim.bone_weights  # (N,4) float32
        pos = prim.positions
        nrm = prim.normals
        n = pos.shape[0]
        # 顶点索引 → 调色板 slot（Korabli：slot × 3）
        slots = (idx.astype(np.int32) // 3)
        # 越界 slot 置 -1（权重归零，不参与混合）
        valid = slots < len(mats)
        slots = np.where(valid, slots, -1)

        new_pos = np.zeros_like(pos, dtype=np.float64)
        new_nrm = np.zeros_like(nrm, dtype=np.float64)
        for j in range(4):
            s = slots[:, j]
            w = wts[:, j]
            for slot in np.unique(s):
                if slot < 0 or slot >= len(mats):
                    continue
                m = mats[slot]
                if m is None:
                    continue
                mask = s == slot
                if not mask.any():
                    continue
                R = m[:3, :3].astype(np.float64)
                t = m[:3, 3].astype(np.float64)
                wm = w[mask, None]
                new_pos[mask] += wm * ((pos[mask].astype(np.float64) @ R.T) + t)
                new_nrm[mask] += wm * (nrm[mask].astype(np.float64) @ R.T)
        prim.positions = new_pos.astype(np.float32)
        ln = np.linalg.norm(new_nrm, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        prim.normals = (new_nrm / ln).astype(np.float32)
        # 保留蒙皮调色板与 bind 世界矩阵（GLB 导出 skin 用；bones 保持原样）
        prim.skin_bones = list(palette)
        prim.skin_bind = mats
        return True

    def _apply_rigid_binding(self, prim, rs: dict | None) -> bool:
        """对**非蒙皮但刚性绑定到骨架节点**的子模型施加父节点世界矩阵（原地烘焙顶点）。

        背景：船体几何文件里的一些甲板/上层建筑小件（如 BIA454_Bollard_bigShape、
        BIA703_HelmetsShape）在文件里位于**原点**，渲染集条目 skinned=0 但 nodes 非空
        （如 ['BIA454_Bollard_big_7']），即刚性父级绑定到某个骨骼节点。需乘该骨骼的
        世界矩阵（_skeleton_bones 返回）把顶点摆到舰船空间，否则渲染/导出都停在世界中心。

        返回是否实际变换了顶点（True → 已烘焙，后续按普通几何处理）。
        """
        if prim is None or rs is None:
            return False
        if rs.get('skinned'):
            return False  # 蒙皮走 _apply_skinning
        nodes = rs.get('nodes') or []
        if not nodes:
            return False  # 无父节点（主船体/独立几何）→ 保持原点
        stem = getattr(self, '_current_skinning_stem', None)
        if not stem:
            return False
        bones = self._skeleton_bones(stem)
        if not bones:
            return False
        m = bones.get(nodes[0])
        if m is None:
            return False
        if np.allclose(m, np.eye(4), atol=1e-4):
            return False  # 恒等无需变换
        R = m[:3, :3].astype(np.float64)
        t = m[:3, 3].astype(np.float64)
        pos = prim.positions
        nrm = prim.normals
        prim.positions = ((pos.astype(np.float64) @ R.T) + t).astype(np.float32)
        new_nrm = nrm.astype(np.float64) @ R.T
        ln = np.linalg.norm(new_nrm, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        prim.normals = (new_nrm / ln).astype(np.float32)
        return True

    def _bake_rigid(self, prim, m) -> None:
        """把刚性父节点矩阵 m（4x4 行主序）烘焙进 primitive 的顶点（原地）。"""
        R = m[:3, :3].astype(np.float64)
        t = m[:3, 3].astype(np.float64)
        prim.positions = ((prim.positions.astype(np.float64) @ R.T) + t).astype(np.float32)
        new_nrm = prim.normals.astype(np.float64) @ R.T
        ln = np.linalg.norm(new_nrm, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        prim.normals = (new_nrm / ln).astype(np.float32)

    @staticmethod
    def _clone_prim(p):
        """复制一个 MeshPrimitive（顶点/法线/uv/索引各拷贝一份，供多节点分别烘焙）。"""
        from models.geometry_parser import MeshPrimitive
        return MeshPrimitive(
            name=p.name,
            positions=p.positions.copy(),
            normals=p.normals.copy(),
            uvs=None if p.uvs is None else p.uvs.copy(),
            indices=None if p.indices is None else p.indices.copy(),
            mapping_id=p.mapping_id,
            is_skinned=p.is_skinned,
            bone_indices=None if p.bone_indices is None else p.bone_indices.copy(),
            bone_weights=None if p.bone_weights is None else p.bone_weights.copy(),
            skin_bones=list(p.skin_bones),
            skin_bind=list(p.skin_bind),
        )

    def _apply_rigid_multi(self, prim, rs: dict | None) -> list:
        """对**非蒙皮但刚性绑定**的子模型：按每个绑定节点烘焙一份顶点，返回列表。

        同一 shape 可绑定多个骨骼节点（左右舷实例化，如 BIA400_Motor_Cutter_25ftShape
        在 `_0`/`_1` 两节点各一份）。每节点烘焙一份 → `_merge_hull` 合并为一网格，
        从而在两个位置各渲染一个实例。
        - 单节点：原地烘焙（保留既有行为），返回 [prim]。
        - 多节点：每节点克隆一份并烘焙，返回克隆列表（不改原 prim）。
        - 无法定位（无骨骼/全恒等/蒙皮）：返回 []（调用方追加原始 prim）。
        """
        if prim is None or rs is None:
            return []
        if rs.get('skinned'):
            return []
        nodes = rs.get('nodes') or []
        if not nodes:
            return []
        stem = getattr(self, '_current_skinning_stem', None)
        if not stem:
            return []
        bones = self._skeleton_bones(stem)
        if not bones:
            return []
        mats: list[tuple[str, object]] = []
        for nd in nodes:
            m = bones.get(nd)
            if m is None:
                continue
            if np.allclose(m, np.eye(4), atol=1e-4):
                continue
            mats.append((nd, m))
        if not mats:
            return []
        if len(mats) == 1:
            self._bake_rigid(prim, mats[0][1])
            return [prim]
        out = []
        for _nd, m in mats:
            clone = self._clone_prim(prim)
            self._bake_rigid(clone, m)
            out.append(clone)
        return out

    def _rigid_instance_matrices(self, prim, rs: dict | None):
        """刚性绑定：返回 (bake_matrix, instance_matrices)。

        只存各骨架节点坐标，不复制顶点——网格只含一份原始几何，渲染时按每个节点
        矩阵各画一次（左右舷/多处实例）。比逐节点烘焙复制顶点更省内存。

        返回：
          (None, None)                  —— 不可刚性绑定（蒙皮/无节点/无骨骼/全恒等），
                                            调用方保留原始几何（原样放入网格）。
          (M_game, [])                  —— 恰一个有效节点：调用方用 M_game 原地烘焙
                                            （既有单节点行为）。
          (None, [M_render_i, ...])     —— 多节点：调用方保留原始几何，并把 M_render_i
                                            写入网格 instance_matrices；渲染时逐实例绘制。
        M_render = MirrorZ @ M_game @ MirrorZ（游戏空间 → 渲染空间模型矩阵）。
        """
        if prim is None or rs is None or rs.get('skinned'):
            return None, None
        nodes = rs.get('nodes') or []
        if not nodes:
            return None, None
        stem = getattr(self, '_current_skinning_stem', None)
        if not stem:
            return None, None
        bones = self._skeleton_bones(stem)
        if not bones:
            return None, None
        negz = np.diag([1.0, 1.0, -1.0, 1.0]).astype(np.float32)
        game_mats: list[np.ndarray] = []
        for nd in nodes:
            m = bones.get(nd)
            if m is None:
                continue
            if np.allclose(m, np.eye(4), atol=1e-4):
                continue
            game_mats.append(np.asarray(m, dtype=np.float32))
        if not game_mats:
            return None, None
        if len(game_mats) == 1:
            return game_mats[0], []
        inst = [(negz @ m @ negz).astype(np.float32) for m in game_mats]
        return None, inst

    @staticmethod
    def _instanced_bounds(positions, matrix) -> tuple[np.ndarray, np.ndarray]:
        """局部顶点包围盒经实例矩阵变换后的世界包围盒（8 角点法）。"""
        mn = positions.min(axis=0)
        mx = positions.max(axis=0)
        corners = np.array([
            [mn[0], mn[1], mn[2]], [mn[0], mn[1], mx[2]],
            [mn[0], mx[1], mn[2]], [mn[0], mx[1], mx[2]],
            [mx[0], mn[1], mn[2]], [mx[0], mn[1], mx[2]],
            [mx[0], mx[1], mn[2]], [mx[0], mx[1], mx[2]],
        ], dtype=np.float32)
        hom = np.hstack([corners, np.ones((8, 1), dtype=np.float32)])
        w = (hom @ matrix.T)[:, :3]
        return w.min(axis=0), w.max(axis=0)

    @staticmethod
    def _merge_hull(part_name: str, primitives, shape_names: list | None = None,
                    node_names: list | None = None,
                    instance_matrices: list | None = None) -> HullMesh:
        """把同一部件的所有 primitive 合并成单个网格。"""
        v_total = sum(p.positions.shape[0] for p in primitives)
        i_total = sum(0 if p.indices is None else p.indices.size for p in primitives)
        has_uv = any(p.uvs is not None for p in primitives)
        has_bone = any(p.bone_indices is not None for p in primitives)

        positions = np.empty((v_total, 3), dtype=np.float32)
        normals = np.empty((v_total, 3), dtype=np.float32)
        uvs = np.empty((v_total, 2), dtype=np.float32) if has_uv else None
        indices = np.empty(i_total, dtype=np.uint32)
        bone_indices = np.empty((v_total, 4), dtype=np.uint8) if has_bone else None
        bone_weights = np.empty((v_total, 4), dtype=np.float32) if has_bone else None
        skin_bones: list = []
        skin_bind: list = []

        voff = 0
        ioff = 0
        for p in primitives:
            n = p.positions.shape[0]
            positions[voff:voff + n] = p.positions
            normals[voff:voff + n] = p.normals
            if uvs is not None:
                if p.uvs is not None:
                    uvs[voff:voff + n] = p.uvs
                else:
                    uvs[voff:voff + n] = 0.0
            if bone_indices is not None:
                if p.bone_indices is not None:
                    bone_indices[voff:voff + n] = p.bone_indices
                    bone_weights[voff:voff + n] = p.bone_weights
                else:
                    bone_indices[voff:voff + n] = 0
                    bone_weights[voff:voff + n] = 0.0
            if not skin_bones and p.skin_bones:
                skin_bones = list(p.skin_bones)
                skin_bind = list(p.skin_bind)
            if p.indices is not None and p.indices.size:
                indices[ioff:ioff + p.indices.size] = p.indices.astype(np.uint32) + voff
                ioff += p.indices.size
            voff += n

        return HullMesh(
            name=part_name,
            positions=positions,
            normals=normals,
            uvs=uvs,
            indices=indices[:ioff] if ioff < i_total else indices,
            vertex_count=voff,
            bone_indices=bone_indices,
            bone_weights=bone_weights,
            skin_bones=skin_bones,
            skin_bind=skin_bind,
            shape_names=list(dict.fromkeys(shape_names or [])),
            node_names=list(dict.fromkeys(node_names or [])),
            instance_matrices=list(instance_matrices or []),
        )

    @staticmethod
    def _build_armor_mesh(am: ArmorModel, armor_thickness: dict,
                          component: str = COMPONENT_HULL,
                          model_matrix: np.ndarray | None = None) -> ArmorMesh | None:
        """装甲模型 → 带厚度颜色/材质信息的 ArmorMesh（每三角形 3 顶点同色）。

        component 标记该装甲的归属分类（船体/主炮塔/副炮/...）；挂载装甲
        传入 model_matrix（挂点变换）用于定位到舰船空间。

        ★ 厚度 ≤0（0mm）的三角形**直接剔除**（游戏内装甲查看器不显示无厚度
        数据的碰撞面；保留会与有效装甲叠色干扰判读）。全部被剔除时返回 None。
        """
        tris = am.triangles
        if not tris:
            return None
        infos: list[ArmorTriangleInfo] = []
        layers_cache: dict[int, list[float]] = {}
        keep: list[int] = []   # 保留的三角形下标（thickness > 0）

        for t, tri in enumerate(tris):
            mat_id = tri.material_id
            layer = tri.layer_index
            thickness = GeometryService._match_thickness(armor_thickness, mat_id, layer)
            if thickness <= 0.0:
                continue   # 0mm：无厚度数据，彻底驱逐
            keep.append(t)
            color = thickness_to_color(thickness)
            mat_name = collision_material_name(mat_id)
            from models.collision_materials import zone_from_material_name
            zone = zone_from_material_name(mat_name)
            layers = layers_cache.get(mat_id)
            if layers is None:
                layers = GeometryService._material_layers(armor_thickness, mat_id)
                layers_cache[mat_id] = layers
            hidden = zone == "Hull" and mat_name in HIDDEN_GENERIC_MATERIALS
            infos.append(ArmorTriangleInfo(
                material_id=mat_id,
                material_name=mat_name,
                layer_index=layer,
                thickness_mm=thickness,
                color=color,
                zone=zone,
                layers=layers,
                hidden=hidden,
                plate_key=(zone, mat_name, round(thickness * 10)),
            ))

        if not keep:
            return None
        n = len(keep)
        positions = np.empty((n * 3, 3), dtype=np.float32)
        normals = np.empty((n * 3, 3), dtype=np.float32)
        colors = np.empty((n * 3, 4), dtype=np.float32)
        indices = np.arange(n * 3, dtype=np.uint32)
        for i, t in enumerate(keep):
            tri = tris[t]
            base = i * 3
            positions[base:base + 3] = tri.vertices
            normals[base:base + 3] = tri.normals
            colors[base:base + 3] = infos[i].color

        return ArmorMesh(
            name=am.name,
            positions=positions,
            normals=normals,
            colors=colors,
            indices=indices,
            triangles=infos,
            component=component,
            model_matrix=model_matrix,
        )

    @staticmethod
    def _match_thickness(armor: dict, material_id: int, layer_index: int) -> float:
        """按 (layer_index, material_id) 查厚度；未命中时取该材质任意非零层。"""
        v = armor.get((layer_index, material_id))
        if v is not None:
            return float(v)
        # 回退：该材质任一层（取最小非零，避免极端值）
        best = 0.0
        for (mi, mat), thk in armor.items():
            if mat == material_id and thk and (best == 0.0 or thk < best):
                best = thk
        return float(best)

    @staticmethod
    def _material_layers(armor: dict, material_id: int) -> list[float]:
        """该材质跨 model_index 的所有非零层厚度（升序）。

        Dual 多层材质同一 material_id 可有多个 model_index 层；tooltip
        需要展示全部堆叠厚度（wows-toolkit lookup_all_layers 语义）。
        """
        vals = sorted({float(thk) for (mi, mat), thk in armor.items()
                       if mat == material_id and thk})
        return vals

    # ── 装甲厚度字典 ────────────────────────────────────

    def _load_armor_thickness(self, ship: ShipInfo) -> dict:
        """读取 A_Hull.armor + 炮塔/副炮 armor，构建 {(model_index, material_id): mm}。

        DB-first：数据源为主库 entity_snapshots 舰船快照（加载数据时入库），
        不读 data/split JSON。
        """
        out: dict[tuple[int, int], float] = {}
        data = self._ship_snapshot(ship)
        if not data:
            return out

        def _collect(d):
            if not isinstance(d, dict):
                return
            armor = d.get("armor")
            if isinstance(armor, dict):
                for k, v in armor.items():
                    try:
                        raw = int(k)
                    except (TypeError, ValueError):
                        continue
                    mi = raw >> 16
                    mat = raw & 0xFFFF
                    try:
                        thk = float(v)
                    except (TypeError, ValueError):
                        continue
                    out[(mi, mat)] = thk

        hull = data.get("A_Hull") or {}
        _collect(hull)
        # 炮塔 / 副炮 / 防空等各挂载 HP_*.armor（含 A_Artillery / AB1_Artillery 等主炮变体）
        for key, _category, group in iter_component_groups(data):
            if key == "A_Hull":
                continue
            for sub in group.values():
                if isinstance(sub, dict):
                    _collect(sub)
        return out

    # ── 生命周期 ────────────────────────────────────────

    def clear(self):
        self._ships = None
        self._ship_snapshot_cache.clear()
        self._release_extractor()

    def _clear_per_load_caches(self) -> None:
        """释放单次加载产生的全部重内存缓存（本服务**不跨船复用**缓存）。

        挂载模型几何/贴图、材质贴图字节/信息、整船快照、骨架/挂点变换、
        渲染集、mfm 识别结果均为单次加载的中间产物；返回的 ShipGeometry
        已按引用共享这些数组（geom 持有引用），清空缓存不影响已加载场景。
        全局参考数据（目录索引 / 材质名表 / mfm 映射 / shape 名表 / 渲染集
        全局索引）保留，它们不是按船复用的加载结果。
        """
        self._mount_model_cache.clear()
        self._material_texture_cache.clear()
        self._texture_bytes_cache.clear()
        self._material_full_cache.clear()
        self._ship_snapshot_cache.clear()
        self._skeleton_bones_cache.clear()
        self._stem_mount_cache.clear()
        self._visual_rs_cache.clear()
        self._mfm_diffuse_cache.clear()

    def release_load_caches(self) -> None:
        """释放本次加载产生的重内存缓存（3D 查看器关闭时的兜底清理）。

        正常情况下每次 load_ship 结束已在 finally 里清空缓存（无跨船复用）；
        此处为关闭窗口时的安全网：再清一次并立即 gc.collect() 回收。
        """
        import gc
        self._clear_per_load_caches()
        gc.collect()
