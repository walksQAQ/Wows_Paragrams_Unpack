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
COMPONENT_SECONDARY = "副炮"
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

#: GameParams 组件键 → 归属分类（按 base 组件名匹配任意前缀变体）
#: 键格式 {PREFIX}_{BASE}，如 AB1_Artillery / B_AirDefense / A1_Torpedoes
_COMPONENT_BY_BASE = {
    "Artillery": COMPONENT_MAIN,            # 主炮塔（A1_/AB1_/B_/C_/X_... 前缀）
    "ATBA": COMPONENT_SECONDARY,            # 副炮（A_/B_...）
    "SecondaryArtillery": COMPONENT_SECONDARY,
    "AirDefense": COMPONENT_AA,             # 防空（A_/B_...）
    "AirSupport": COMPONENT_AA,
    "Directors": COMPONENT_DIRECTOR,        # 指挥仪（A_/AB_...）
    "Finders": COMPONENT_FINDER,            # 测距仪（A_/AB_...）
    "Radars": COMPONENT_RADAR,              # 雷达（A_/AB_...）
    "AirArmament": COMPONENT_OTHER,         # 弹射器（HP_JC_*）
    "Torpedoes": COMPONENT_OTHER,           # 鱼雷发射管（HP_*GT_*）
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
    tech_family: str = "pbs"           # shader 技术族：pbs(0x0005)/indexed(0x0009)/other
    material_textures: dict = field(default_factory=dict)  # {贴图键: (vfs_path, bytes)}
    indexed_params: dict | None = None  # INDEXED 分块参数 {arrays, grid, offset}
    opaque: bool = True                 # 半透明材质（玻璃等）用 alpha 混合
    is_wire: bool = False               # wire 线框辅助网格：用 GL_LINES 渲染（非实体面）
    #: bind pose 蒙皮已实际施加到顶点（Root_BlendBone 已烘焙进几何）；
    #: 挂载矩阵不得再乘 rb，否则双重镜像 → 朝向翻转（PASB111 副炮 AGS542 实证）
    skinned_applied: bool = False


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
    #: 船体漫反射贴图（.dds 原始字节）与 VFS 路径（可能为 None，未找到贴图）
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
                  cancel_event: threading.Event | None = None) -> ShipGeometry:
        """加载一艘船的船体网格 + 挂载模型 + 装甲网格 + 碰撞模型。

        实际逻辑见 _load_ship_impl；此处保证**每次加载结束（成功/失败/取消）
        立即释放本船产生的挂载几何/贴图/快照等缓存**——本服务不跨船复用缓存，
        避免内存随多次加载累积（返回的 ShipGeometry 已持有所需数组引用）。
        """
        try:
            return self._load_ship_impl(ship, progress_cb=progress_cb,
                                        cancel_event=cancel_event)
        finally:
            self._clear_per_load_caches()

    def _load_ship_impl(self, ship: ShipInfo, progress_cb=None,
                        cancel_event: threading.Event | None = None) -> ShipGeometry:
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

        # 舰体分段：模型目录内全部 .geometry（已处于舰船坐标系）
        entries = self._geometry_folder_index(extractor).get(ship.model_folder) or []
        if not entries:
            # 回退：按 model_folder 全树匹配任意路径下的 geometry
            pattern = f"content/**/{ship.model_folder}/{ship.model_folder}*.geometry"
            try:
                entries = [
                    e for e in extractor.list_files([pattern])
                    if not e.is_directory
                ]
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"列出几何文件失败: {exc}") from exc

        if not entries:
            raise RuntimeError(f"未找到 {ship.model_folder} 的 .geometry 文件")

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
            if stem == ship.model_folder:
                main_entries.append(e)
                continue
            seg_uniq.append(e)
        if seg_uniq:
            uniq = seg_uniq
        elif uniq:
            # 只有主文件（无分段模型）：明确报错提示，而非静默用主文件回退
            raise RuntimeError(
                f"未找到 {ship.model_folder} 的分段模型文件"
                f"（仅存在主文件 {ship.model_folder}.geometry）")

        # 该船全部渲染集索引（含整合模型：高模 shape 渲染集可能在别的分段记录）
        ship_rs = self._ship_render_sets(ship.model_folder)

        geom = ShipGeometry(
            game_key=ship.game_key,
            display_name=ship.display_name,
            model_folder=ship.model_folder,
        )

        # 蒙皮 bind pose 骨架 stem（舰船模型目录；_apply_skinning 用它查骨骼矩阵）
        self._current_skinning_stem = ship.model_folder

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
                groups = self._split_primitives_by_material(parsed.primitives, ship_rs, sdict)
                if groups:
                    for mat_key, g in groups.items():
                        if not g.get('prims'):
                            continue
                        nm = part_name if mat_key is None else f"{part_name}#{mat_key}"
                        hm = self._merge_hull(nm, g['prims'])
                        if mat_key is not None:
                            hm.material = mat_key
                        if mat_key == '__wire__' or mat_key == 'WIRE':
                            hm.is_wire = True
                        if mat_key is not None:
                            # 完整材质信息：技术族 + 贴图集 + INDEXED 分块参数（fx 区分渲染）
                            bundle = self._resolve_material_full(g.get('mfm') or '', extractor)
                            if bundle:
                                hm.tech_family = bundle.get('tech_family', 'pbs')
                                hm.material_textures = bundle.get('textures') or {}
                                hm.indexed_params = bundle.get('indexed_params')
                                texs = hm.material_textures
                                # 主贴图：INDEXED 用 albedoArray（分块图集）；标准用 diffuseMap
                                if hm.tech_family == 'indexed' and 'albedoArray' in texs:
                                    hm.texture_path, hm.texture_dds = texs['albedoArray']
                                elif 'diffuseMap' in texs:
                                    hm.texture_path, hm.texture_dds = texs['diffuseMap']
                            if not hm.texture_dds:
                                try:
                                    tp, td = self._resolve_material_texture(g.get('mfm') or '', extractor)
                                    hm.texture_path, hm.texture_dds = tp, td
                                except Exception:  # noqa: BLE001
                                    pass
                        geom.hull_meshes.append(hm)
                        if hm.positions.size:
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
                          cancel_event=cancel_event)

        if progress_cb:
            progress_cb(100, "加载完成")
        return geom

    # ── 挂载模型 ────────────────────────────────────────

    def _load_mounts(self, geom: ShipGeometry, ship: ShipInfo, extractor,
                     armor_thickness: dict, progress_cb=None,
                     cancel_event: threading.Event | None = None):
        """加载 GameParams 各 HP_* 挂载模型并按骨架挂点定位。

        同一模型目录（如 JGM178 炮塔）只解析一次几何，按每个挂点实例化；
        每个挂载使用该模型自己的贴图（`{stem}_a.dd0` 命名约定）。
        """
        refs = self._load_mount_refs(
            ship, warnings=geom.stats.setdefault("warnings", []))
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
        placed = 0
        sub_placed = 0   # 挂载模型骨架上的 MP 子设备（炮塔测距仪/炮上防空炮等）
        _negz = np.diag([1.0, 1.0, -1.0, 1.0])   # 几何(左手系)→渲染(右手系) 共轭
        n_refs = len(refs)
        for idx, (hp, comp, model_path, misc_filter, custom_battle) in enumerate(refs):
            self._raise_if_cancelled(cancel_event)
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

            # 每个材质分片实例化一个挂载网格（本地坐标 + 挂点矩阵 + 独立贴图）
            # ★ 已蒙皮网格的顶点已含 Root_BlendBone（_apply_skinning 烘焙），
            #   矩阵用 armor_mtx（不乘 rb），否则双重镜像 → 朝向翻转（PASB111 副炮）
            for hm in src["meshes"]:
                mm = MountMesh(
                    name=hp, component=comp,
                    positions=hm.positions, normals=hm.normals,
                    uvs=hm.uvs, indices=hm.indices,
                    model_matrix=(armor_mtx if hm.skinned_applied else mtx),
                    texture_dds=hm.texture_dds, texture_path=hm.texture_path,
                    model_folder=folder, vertex_count=hm.vertex_count,
                    is_wire=hm.is_wire,
                )
                geom.mounts.append(mm)

                # 世界包围盒（含挂载，供取景框选）
                if mm.positions.size:
                    mn, mx = mm.bounds_in_world()
                    bmin = np.minimum(bmin, mn)
                    bmax = np.maximum(bmax, mx)

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

        # ── MP 甲板设备挂载（缆桩/小艇/探照灯/救生筏等 misc 模型）──
        # MP 节点不在 GameParams，由 populate 纳入 skeleton_mounts（v5）；
        # 模型目录由命名约定推导：MP_{baseID}_... → misc/{baseID}/{baseID}.geometry
        mp_placed = 0
        mp_items = [(n, m) for n, m in transforms.items() if n.startswith("MP_")]
        n_mp = len(mp_items)
        for idx, (mp_name, m_raw) in enumerate(mp_items):
            self._raise_if_cancelled(cancel_event)
            if progress_cb:
                progress_cb(66 + 33 * (n_refs + idx) / max(1, n_refs + n_mp),
                            f"加载甲板设备 {mp_name}")
            folder = mp_base_id(mp_name)
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
            for hm in src["meshes"]:
                mm = MountMesh(
                    name=mp_name, component=COMPONENT_DECK,
                    positions=hm.positions, normals=hm.normals,
                    uvs=hm.uvs, indices=hm.indices,
                    model_matrix=(armor_mtx if hm.skinned_applied else mtx),
                    texture_dds=hm.texture_dds, texture_path=hm.texture_path,
                    model_folder=folder, vertex_count=hm.vertex_count,
                    is_wire=hm.is_wire,
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
                from services.assets_cache_service import AssetsCacheService
                c = AssetsCacheService()
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
                         warnings: list | None = None) -> list[tuple[str, str, str, list, list]]:
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
                out.append((hp, category, str(model),
                            [str(x) for x in mf if isinstance(x, str)],
                            [str(x) for x in cb if isinstance(x, str)]))
            if has_mount and not is_known_component_key(key):
                if warnings is not None:
                    warnings.append(
                        f"组件 {key} 含挂载引用但未被识别，已按「其他」归属加载")
        return out

    # ── assets.bin 骨架挂点 ─────────────────────────────

    def _locate_assets_bin(self) -> str | None:
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
            path = self._locate_assets_bin()
            if path:
                self._assets_svc = AssetsBinService(assets_path=path)
        except Exception:  # noqa: BLE001
            self._assets_svc = None
        return self._assets_svc

    @staticmethod
    def _matrix_to_render(m: list) -> np.ndarray:
        """骨架挂点矩阵（列主序 16 float）→ 行主序 4x4（原始矩阵，不做坐标变换）。

        方向/位置匹配改由 **基于骨骼** 完成（_load_mounts 组合模型 Root_BlendBone
        并用 negz 共轭转渲染空间），这里仅转换矩阵布局。
        """
        return np.ascontiguousarray(
            np.array(m, dtype=np.float32).reshape(4, 4).T, dtype=np.float32)

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
            from services.assets_cache_service import AssetsCacheService
            c = AssetsCacheService()
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
            from services.assets_cache_service import AssetsCacheService
            world = AssetsCacheService().get_skeleton_bones(
                app_ctx.ctx.bin_folder or "", folder)
        except Exception:  # noqa: BLE001
            world = {}
        self._mount_model_cache[key] = world
        return world

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
            sub_folder = mp_base_id(mp_name)
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
            from services.assets_cache_service import AssetsCacheService
            c = AssetsCacheService()
            out = c.get_skeleton_mounts(app_ctx.ctx.bin_folder or "", stem)
        except Exception:  # noqa: BLE001
            out = {}
        self._stem_mount_cache[stem] = out
        return out

    # ── 挂载模型几何/贴图加载 ───────────────────────────

    @staticmethod
    def _murmur3_32(data: bytes, seed: int = 0) -> int:
        """MurmurHash3_x86_32：Korabli 字符串哈希（渲染集 shape 名 ↔ geometry mapping_id）。"""
        c1 = 0xCC9E2D51
        c2 = 0x1B873593
        length = len(data)
        h1 = seed
        for i in range(length // 4):
            k1 = struct.unpack_from('<I', data, i * 4)[0]
            k1 = (k1 * c1) & 0xFFFFFFFF
            k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
            k1 = (k1 * c2) & 0xFFFFFFFF
            h1 ^= k1
            h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
            h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF
        tail = data[length // 4 * 4:]
        k1 = 0
        if len(tail) >= 3:
            k1 ^= tail[2] << 16
        if len(tail) >= 2:
            k1 ^= tail[1] << 8
        if len(tail) >= 1:
            k1 ^= tail[0]
            k1 = (k1 * c1) & 0xFFFFFFFF
            k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
            k1 = (k1 * c2) & 0xFFFFFFFF
            h1 ^= k1
        h1 ^= length
        h1 ^= h1 >> 16
        h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
        h1 ^= h1 >> 13
        h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
        h1 ^= h1 >> 16
        return h1

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
        #    +0x08 材质名 / +0x20 .mfm 路径 selfId。
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
                if "/lods/" in path or "_lod" in path.rsplit("/", 1)[-1]:
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
        # 蒙皮 bind pose 骨架 stem = 挂载模型目录（_apply_skinning 用它查骨骼矩阵）
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
                groups = self._split_primitives_by_material(parsed.primitives, mount_rs, sdict)
                for mat, g in groups.items():
                    # 保留所有分组（含 None 组：shape 无渲染集材质时用默认/文件名约定贴图，
                    # 如指挥仪 ControlTowerShape —— 否则指挥仪/雷达等会整组丢失不显示）
                    if not g.get('prims'):
                        continue
                    mfm = g.get('mfm') or ''
                    tex_path, tex_bytes = "", b""
                    # 1) 当前模型自己的 mfm（路径含 folder）
                    if mfm and folder in mfm:
                        tex_path, tex_bytes = self._resolve_material_texture(mfm, extractor)
                    # 2) 当前模型自有贴图（{folder}_a.dd0 文件名约定）
                    if not tex_bytes:
                        tex_path, tex_bytes = self._find_model_diffuse(
                            first_geom_path, folder, extractor)
                    # 3) 共享 mfm（同型号变体共享材质，如 JGA018/JGA181→JGA010）；
                    #    跨型号串用（JGS156→JGS157）已在 2) 用自有贴图挡住
                    if not tex_bytes and mfm and folder not in mfm:
                        tex_path, tex_bytes = self._resolve_material_texture(mfm, extractor)
                    hm = self._merge_hull(f"{folder}|{mat or 'default'}", g['prims'])
                    hm.material = mat
                    hm.is_wire = (mat == '__wire__' or mat == 'WIRE')
                    hm.skinned_applied = bool(g.get('skinned_applied'))
                    hm.texture_path = tex_path
                    hm.texture_dds = tex_bytes
                    meshes.append(hm)
                    if not main_tex[1]:
                        main_tex = (tex_path, tex_bytes)

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
                from services.assets_cache_service import AssetsCacheService
                c = AssetsCacheService()
                self._mfm_textures_db = c.get_mfm_textures(
                    app_ctx.ctx.bin_folder or "") or {}
            if self._mfm_textures_db:
                cands = []
                for mfm_path, tex_path in self._mfm_textures_db.items():
                    if not tex_path:
                        continue
                    name = mfm_path.rsplit("/", 1)[-1][:-4]
                    if name == stem or name.startswith(stem + "_"):
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

    @staticmethod
    def _load_texture_tier(base: str, extractor) -> tuple[str, bytes]:
        """按 .dd0/.dd1/.dd2/.dds 分级读取贴图（.dd0 最高清），返回 (vfs_path, bytes)。"""
        for tier in (".dd0", ".dd1", ".dd2", ".dds"):
            cand = base + tier
            data = GeometryService._read_vfs(extractor, cand)
            if data and data[:4] == b"DDS ":
                return cand, data
        return "", b""

    def _find_model_diffuse(self, geometry_path: str, folder: str, extractor) -> tuple[str, bytes]:
        """挂载模型贴图：**基于 .mfm 识别**（diffuseMap 权威），回退文件名约定。"""
        # 1) .mfm 识别：{folder}.mfm / {folder}_skinned.mfm → diffuseMap → _a 基础名
        base = self._mfm_diffuse_base(folder, prefer=(folder, f"{folder}_skinned"))
        if base:
            path, data = self._load_texture_tier(base, extractor)
            if data:
                return path, data
        # 2) 回退：文件名约定 {stem}_a.dd0（无 _Hull 后缀，与舰体不同）
        model_dir = geometry_path.rsplit("/", 1)[0]
        tex_dir = model_dir.rsplit("/", 1)[0] + "/textures"
        stem = folder
        candidates = [
            f"{tex_dir}/{stem}_a.dd0",
            f"{tex_dir}/{stem}_a.dds",
            f"{tex_dir}/{stem}.dd0",
            f"{tex_dir}/{stem}.dds",
            f"{tex_dir}/{stem}_Hull_a.dd0",
            f"{tex_dir}/{stem}_Hull_a.dds",
        ]
        for cand in candidates:
            data = self._read_vfs(extractor, cand)
            if data and data[:4] == b"DDS ":
                return cand, data
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
        """舰体贴图：**基于 .mfm 识别**（Hull.mfm 的 diffuseMap 权威），回退文件名约定。

        颜色贴图以 `_a` 后缀为准，优先 `.dd0`（4096×4096 高清 DDS）。
        """
        # 1) .mfm 识别：{stem}_Hull.mfm / {stem}.mfm → diffuseMap
        stem = ship.model_folder
        base = self._mfm_diffuse_base(stem, prefer=(f"{stem}_Hull", stem))
        if base:
            path, data = self._load_texture_tier(base, extractor)
            if data:
                return path, data
        # 2) 回退：文件名约定 {stem}_Hull_a.dd0
        model_dir = ship.model_path.rsplit("/", 1)[0]
        tex_dir = model_dir.rsplit("/", 1)[0] + "/textures"
        candidates = [
            f"{tex_dir}/{stem}_Hull_a.dd0",
            f"{tex_dir}/{stem}_Hull_a.dds",
            f"{tex_dir}/{stem}_Hull.dd0",
            f"{tex_dir}/{stem}_Hull.dds",
            f"{tex_dir}/{stem}_Hull_d.dd0",
            f"{tex_dir}/{stem}_Hull_d.dds",
            f"content/gameplay/common/camouflage/textures/{stem}_Hull_camo_01.dds",
        ]
        for cand in candidates:
            data = self._read_vfs(extractor, cand)
            if data and data[:4] == b"DDS ":
                return cand, data
        return "", b""

    def _split_primitives_by_material(self, primitives, global_rs: dict,
                                      sdict: dict | None = None) -> dict:
        """按渲染集索引把 primitives 分组：{material_key: {material, mfm, prims}}。

        - 用 murmur3(shape.vertices) == primitive.mapping_id 连接渲染集与几何
        - **damage 渲染集（crack/patch/wire/lod）的网格直接跳过**（不渲染）
        - 匹配到材质的按材质分组；未匹配的归 None（用舰体默认贴图）
        - sdict 兜底：无渲染集匹配的 primitive 用字符串表反查 shape 名，
          LOD/crack 低模也跳过（渲染集精确区域可能未收录其 LOD 渲染集）
        - 多个 shape 同材质（如 Hull 本体 + DeckHouse）自动合并
        """
        mat_by_mid: dict = {}
        damage_mids: set = set()
        norm_to_rs: dict = {}   # 归一化 shape stem → 渲染集（模糊兜底：处理视觉/几何笔误）
        for mid, rs in global_rs.items():
            mat_by_mid[mid] = (rs.get('material') or '', rs.get('mfm') or '')
            if rs.get('damage'):
                damage_mids.add(mid)
                continue
            nk = GeometryService._norm_shape_stem(rs.get('shape') or '')
            if nk and nk not in norm_to_rs:
                norm_to_rs[nk] = rs
        groups: dict = {}
        for p in primitives:
            if p.mapping_id in damage_mids:
                continue   # 跳过 crack/patch/wire 等损伤网格
            entry = mat_by_mid.get(p.mapping_id)
            if entry is None:
                # 无渲染集匹配：字符串表反查 shape 名，LOD/crack 低模兜底跳过
                if sdict is not None:
                    _name = sdict.get(p.mapping_id) or ''
                    if '_lod' in _name or '_crack_' in _name or 'Crack' in _name:
                        continue
                    # 模糊兜底：归一化 shape 名匹配渲染集（游戏数据笔误，
                    # 如 JGA180 视觉写 TurretShapeff.vertices、几何是 TurretShape.vertices）
                    if _name:
                        fuz = norm_to_rs.get(GeometryService._norm_shape_stem(_name))
                        if fuz is not None:
                            mat = fuz.get('material') or ''
                            mfm = fuz.get('mfm') or ''
                            if self._apply_skinning(p, fuz):
                                g = groups.setdefault(mat, {'material': mat, 'mfm': mfm, 'prims': []})
                                g['skinned_applied'] = True
                            else:
                                g = groups.setdefault(mat, {'material': mat, 'mfm': mfm, 'prims': []})
                            g['prims'].append(p)
                            continue
                groups.setdefault(None, {'material': None, 'mfm': '', 'prims': []})['prims'].append(p)
            else:
                mat, mfm = entry
                rs = global_rs.get(p.mapping_id)
                applied = self._apply_skinning(p, rs)
                g = groups.setdefault(mat, {'material': mat, 'mfm': mfm, 'prims': []})
                g['prims'].append(p)
                if applied:
                    g['skinned_applied'] = True
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
        out: dict = {}
        try:
            from uncode_assets import binary as B
            hmap = db.strings.offsets_map
            cap = hmap.capacity
            stride = hmap.bucket_stride
            vstride = hmap.value_stride
            buckets = hmap.buckets
            values = hmap.values
            sdata = db.strings.string_data
            read64 = B.read_u64
            read32 = B.read_u32
            read_str = B.read_null_terminated_string
            for idx in range(cap):
                off = idx * stride
                key = read64(buckets, off)
                if stride >= 16:
                    if read64(buckets, off + 8) == 0:
                        continue
                else:
                    if key == 0:
                        continue
                str_off = read32(values, idx * vstride)
                if str_off < len(sdata):
                    s = read_str(sdata, str_off)
                    if s:
                        out[key & 0xFFFFFFFF] = s
        except Exception:  # noqa: BLE001
            pass
        self._strings_dict_cache = out
        return out

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
            from services.assets_cache_service import AssetsCacheService
            c = AssetsCacheService()
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
            from services.assets_cache_service import AssetsCacheService
            c = AssetsCacheService()
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
                    if mid in idx:
                        # 跨模型同名 shape（murmur3 冲突）：优先当前模型自己的 mfm
                        if mfm and model_folder in mfm:
                            idx[mid] = entry
                        continue
                    idx[mid] = entry
        except Exception as exc:  # noqa: BLE001
            idx = {}
            bus.log_message.emit(f"⚠️ 渲染集数据读取失败({model_folder}): {exc}，已回退默认贴图")
        self._visual_rs_cache[key] = idx
        return idx

    def _resolve_material_texture(self, mfm_path: str, extractor) -> tuple[str, bytes]:
        """材质 .mfm 路径 → 贴图（diffuseMap → .dd0/.dd1/.dd2/.dds 分级），按 mfm 缓存。"""
        if not mfm_path or not mfm_path.endswith('.mfm'):
            return "", b""
        cached = self._material_texture_cache.get(mfm_path)
        if cached is not None:
            return cached
        stem = mfm_path.rsplit('/', 1)[-1][:-4]
        base = self._mfm_diffuse_base(stem, prefer=(stem,))
        result = ("", b"")
        if base:
            result = self._load_texture_tier(base, extractor)
        self._material_texture_cache[mfm_path] = result
        return result

    # ── 材质技术族 + INDEXED 分块渲染 ───────────────────

    @staticmethod
    def _material_family(shader_id: str) -> str:
        """shader_id（0xHHHHLLLL）高 16 位 → 技术族。

        INDEXED 分块(0x0009, ship_material_indexed.fx) / 标准 ship PBS(0x0005,
        PBS_ship_camo*.fx) / 其他。参考 uncode_assets/shaders.py 对 fxo 的逆向。
        """
        try:
            family = (int(shader_id, 16) >> 16) & 0xFFFF
        except Exception:  # noqa: BLE001
            family = 0
        if family == 0x0009:
            return "indexed"
        if family == 0x0005:
            return "pbs"
        return "other"

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
            from services.assets_cache_service import AssetsCacheService
            c = AssetsCacheService()
            info = c.get_material_full(app_ctx.ctx.bin_folder or "", mfm_path)
            if info:
                sid = info.get("shader_id") or "0x0"
                family = info.get("family") or self._material_family(sid)
                # 贴图属性 → 实时从客户端 pkg 解包字节（.dds/.dd0 分级）
                textures: dict = {}
                for name, vp in (info.get("textures") or {}).items():
                    if not vp:
                        continue
                    base = vp[:-4] if vp.endswith(".dds") else vp
                    tp, td = self._load_texture_tier(base, extractor)
                    if td:
                        textures[name] = (tp, td)
                result = {"tech_family": family, "shader_id": sid, "textures": textures}
                # INDEXED 分块参数（material_full.indexed 已含 vec4 数组）
                indexed = info.get("indexed") or {}
                if indexed:
                    try:
                        arrs = {k: np.array(v, dtype=np.float32) for k, v in indexed.items()}
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
            from services.assets_cache_service import AssetsCacheService
            c = AssetsCacheService()
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

        - 调色板缺失 / 骨骼缺失 / 全部骨骼为恒等 → 不修改（保持原样，安全回退）。
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
        return True

    @staticmethod
    def _merge_hull(part_name: str, primitives) -> HullMesh:
        """把同一部件的所有 primitive 合并成单个网格。"""
        v_total = sum(p.positions.shape[0] for p in primitives)
        i_total = sum(0 if p.indices is None else p.indices.size for p in primitives)
        has_uv = any(p.uvs is not None for p in primitives)

        positions = np.empty((v_total, 3), dtype=np.float32)
        normals = np.empty((v_total, 3), dtype=np.float32)
        uvs = np.empty((v_total, 2), dtype=np.float32) if has_uv else None
        indices = np.empty(i_total, dtype=np.uint32)

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
