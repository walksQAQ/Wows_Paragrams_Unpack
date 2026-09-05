"""
space.py —— 港口/地图场景资源包（models.bin / space.bin / models.geometry）解析。

对应 wows-toolkit docs/MODELS.md 的 MergedModels / SpaceInstances / geometry 格式。
只解析**头部元数据 + models.bin 模型记录/渲染集**，不实际解码网格顶点，
供「港口/地图文件列表浏览」展示文件与相关属性。

辅助 API：
  - SceneResolver：用 assets.bin 的 pathId → 路径、字符串名 → 文本（无 assets.bin 时回退 0x 十六进制）
  - scan_scenes：枚举游戏文件树中的 models.bin，组装每个场景目录的 SpaceScene
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Optional

#: models.bin 头部（0x18 = 24B）
MODELS_HEADER_SIZE = 0x18
#: MergedModelRecord 步长（0xA8 = 168B）
MODEL_RECORD_SIZE = 0xA8
#: RenderSet 步长（0x28 = 40B）
RENDER_SET_SIZE = 0x28
#: LOD 步长（0x10 = 16B）
LOD_SIZE = 0x10
#: space.bin 头部（0x60 = 96B，仅用第 1 个 u32 的 instanceCount）
SPACE_HEADER_SIZE = 0x60
#: MergedGeometryPrototype 头部（0x48 = 72B）
GEOMETRY_HEADER_SIZE = 0x48

# 记录内偏移
_MODEL_PATH_ID = 0x00                 # MergedModelRecord.pathId (u64)
_MODEL_VISUAL_ID = 0x08 + 0x00        # ModelPrototype.visualResourceId (u64)
_VP_BASE = 0x30                       # VisualProto 在记录内的偏移
_VP_MERGED_GEOM = _VP_BASE + 0x30     # mergedGeomPathId (u64)
_VP_UNDERWATER = _VP_BASE + 0x38      # underwater_model (u8)
_VP_ABOVEWATER = _VP_BASE + 0x39      # abovewater_model (u8)
_VP_RS_COUNT = _VP_BASE + 0x3A        # render_sets_count (u16)
_VP_LOD_COUNT = _VP_BASE + 0x3C       # lods_count (u8)
_VP_BBOX_MIN = _VP_BASE + 0x40        # 3×f32
_VP_BBOX_MAX = _VP_BASE + 0x50        # 3×f32
_VP_RS_PTR = _VP_BASE + 0x60          # render_sets relptr (i64, rel. vp_base)

_RS_NAME = 0x00
_RS_MAT = 0x04
_RS_VMI = 0x08
_RS_IMI = 0x0C
_RS_MFM = 0x10
_RS_SKINNED = 0x18
_RS_NCNT = 0x19
_RS_NODES_PTR = 0x20


@dataclass
class RenderSet:
    """一条渲染集：shape 名 / 材质名 / 材质 .mfm / 顶点/索引映射 / 蒙皮节点。"""
    name: str
    material_identifier: str
    material_mfm: str
    material_mfm_id: int   # 材质 .mfm 的 selfId（供 assets.bin 反查解码）
    vertices_mapping_id: int
    indices_mapping_id: int
    skinned: bool
    nodes: list[str] = field(default_factory=list)


@dataclass
class SceneModel:
    """models.bin 中的一条模型记录。"""
    path_id: int
    path: str
    visual_path: str
    merged_geometry_path: str
    underwater: bool
    abovewater: bool
    render_sets_count: int
    lods_count: int
    bbox_min: list[float]
    bbox_max: list[float]
    render_sets: list[RenderSet] = field(default_factory=list)


@dataclass
class SpaceScene:
    """一个港口/地图场景目录的聚合信息。"""
    dir_path: str
    kind: str                            # "port" | "map" | "unknown"
    models: list[SceneModel] = field(default_factory=list)
    models_count: int = 0
    skeletons_count: int = 0
    model_bone_count: int = 0
    instance_count: Optional[int] = None   # space.bin（惰性读取后填）
    geometry_attrs: dict = field(default_factory=dict)  # models.geometry 头（浏览器已跳过显示）
    materials: list[tuple[int, str]] = field(default_factory=list)  # 场景内所有 .mfm (selfId, 路径)（去重）
    files: dict[str, int] = field(default_factory=dict)  # 目录内文件名 -> unpacked_size


class SceneResolver:
    """把 models.bin 的 selfId / 字符串哈希解析为可读路径/文本。

    `db` 传 assets.bin 的 PrototypeDatabase；为 None 时全部回退 0x 十六进制。
    """

    def __init__(self, db=None):
        self._db = db
        self._index = None
        if db is not None:
            try:
                self._index = db.build_self_id_index()
            except Exception:  # noqa: BLE001
                self._index = None

    def path(self, self_id: int) -> str:
        if self_id == 0:
            return ""
        if self._db is None or self._index is None:
            return "" if self_id == 0 else f"0x{self_id:016X}"
        i = self._index.get(self_id)
        if i is None:
            return f"0x{self_id:016X}"
        try:
            return self._db.reconstruct_path(i, self._index)
        except Exception:  # noqa: BLE001
            return f"0x{self_id:016X}"

    def string(self, name_id: int) -> str:
        if self._db is None:
            return f"0x{name_id:08X}"
        try:
            return self._db.strings.get_string_or_hex(name_id)
        except Exception:  # noqa: BLE001
            return f"0x{name_id:08X}"

    @property
    def db(self):
        """关联的 assets.bin PrototypeDatabase（无则 None），供材质解码。"""
        return self._db


# ── 各自格式头部解析 ──────────────────────────────────────────────────────

def parse_geometry_header(data: bytes) -> dict:
    """MergedGeometryPrototype 头部（0x48）。"""
    if len(data) < GEOMETRY_HEADER_SIZE:
        return {}
    (mvc, mic, vmc, imc, cmc, amc) = struct.unpack_from("<6I", data, 0)
    return {
        "mergedVerticesCount": mvc,
        "mergedIndicesCount": mic,
        "verticesMappingCount": vmc,
        "indicesMappingCount": imc,
        "collisionModelCount": cmc,
        "armorModelCount": amc,
    }


def parse_space_bin(data: bytes) -> int:
    """space.bin 头部 → 实例数（instanceCount@0x00）。"""
    if len(data) < 4:
        return 0
    return struct.unpack_from("<I", data, 0)[0]


def parse_models_bin(data: bytes, resolver: SceneResolver) -> tuple[int, int, int, list[SceneModel]]:
    """解析 models.bin：返回 (modelsCount, skeletonsCount, modelBoneCount, models)。"""
    if len(data) < MODELS_HEADER_SIZE:
        raise ValueError("models.bin 过短")
    models_count, skeletons_count, model_bone_count = struct.unpack_from("<IHH", data, 0)
    models_rel = struct.unpack_from("<q", data, 0x08)[0]

    models: list[SceneModel] = []
    for i in range(models_count):
        rec_off = models_rel + i * MODEL_RECORD_SIZE
        if rec_off + MODEL_RECORD_SIZE > len(data):
            break
        path_id = struct.unpack_from("<Q", data, rec_off + _MODEL_PATH_ID)[0]
        visual_id = struct.unpack_from("<Q", data, rec_off + _MODEL_VISUAL_ID)[0]
        vp_base = rec_off + _VP_BASE

        merged_geom_id = struct.unpack_from("<Q", data, vp_base + _VP_MERGED_GEOM - _VP_BASE)[0]
        underwater = data[vp_base + _VP_UNDERWATER - _VP_BASE]
        abovewater = data[vp_base + _VP_ABOVEWATER - _VP_BASE]
        rs_count = struct.unpack_from("<H", data, vp_base + _VP_RS_COUNT - _VP_BASE)[0]
        lod_count = data[vp_base + _VP_LOD_COUNT - _VP_BASE]
        bbox_min = list(struct.unpack_from("<3f", data, vp_base + _VP_BBOX_MIN - _VP_BASE))
        bbox_max = list(struct.unpack_from("<3f", data, vp_base + _VP_BBOX_MAX - _VP_BASE))
        rs_ptr = struct.unpack_from("<q", data, vp_base + _VP_RS_PTR - _VP_BASE)[0]

        render_sets: list[RenderSet] = []
        if rs_ptr and rs_count:
            rs_base = vp_base + rs_ptr
            for k in range(rs_count):
                rs_off = rs_base + k * RENDER_SET_SIZE
                if rs_off + RENDER_SET_SIZE > len(data):
                    break
                name_id = struct.unpack_from("<I", data, rs_off + _RS_NAME)[0]
                mat_id = struct.unpack_from("<I", data, rs_off + _RS_MAT)[0]
                vmi = struct.unpack_from("<I", data, rs_off + _RS_VMI)[0]
                imi = struct.unpack_from("<I", data, rs_off + _RS_IMI)[0]
                mfm_id = struct.unpack_from("<Q", data, rs_off + _RS_MFM)[0]
                skinned = data[rs_off + _RS_SKINNED]
                ncnt = data[rs_off + _RS_NCNT]
                nodes_ptr = struct.unpack_from("<q", data, rs_off + _RS_NODES_PTR)[0]
                nodes: list[str] = []
                if skinned and ncnt and nodes_ptr:
                    nabs = rs_off + nodes_ptr
                    if nabs + ncnt * 4 <= len(data):
                        for j in range(ncnt):
                            nid = struct.unpack_from("<I", data, nabs + j * 4)[0]
                            nodes.append(resolver.string(nid))
                render_sets.append(RenderSet(
                    name=resolver.string(name_id),
                    material_identifier=resolver.string(mat_id),
                    material_mfm=resolver.path(mfm_id),
                    material_mfm_id=mfm_id,
                    vertices_mapping_id=vmi,
                    indices_mapping_id=imi,
                    skinned=bool(skinned),
                    nodes=nodes,
                ))

        models.append(SceneModel(
            path_id=path_id,
            path=resolver.path(path_id),
            visual_path=resolver.path(visual_id),
            merged_geometry_path=resolver.path(merged_geom_id),
            underwater=bool(underwater),
            abovewater=bool(abovewater),
            render_sets_count=rs_count,
            lods_count=lod_count,
            bbox_min=bbox_min,
            bbox_max=bbox_max,
            render_sets=render_sets,
        ))
    return models_count, skeletons_count, model_bone_count, models


def detect_kind(dir_path: str) -> str:
    """按目录路径启发式判断是港口还是地图/空间。"""
    low = dir_path.lower()
    if "port" in low or "dock" in low:
        return "port"
    if "space" in low or "map" in low or "arena" in low or "battle" in low:
        return "map"
    return "unknown"


def scan_scenes(extractor, resolver: SceneResolver,
                progress_cb: Optional[Callable[[int, int], None]] = None,
                cancel_event=None) -> list[SpaceScene]:
    """枚举游戏文件树中的所有 `models.bin`，组装每个场景目录的 SpaceScene。"""
    file_tree = getattr(extractor, "file_tree", {}) or {}
    entries = [e for e in file_tree.values()
               if not getattr(e, "is_directory", True) and e.path.endswith("models.bin")]
    scenes: list[SpaceScene] = []
    total = len(entries)
    for idx, e in enumerate(entries):
        if cancel_event is not None and cancel_event.is_set():
            break
        if progress_cb is not None:
            progress_cb(idx, total)
        dir_path = e.path.rsplit("/", 1)[0]
        try:
            data = extractor.pkg_reader.read_file(e.volume.filename, e.file_info)
        except Exception:  # noqa: BLE001
            continue
        try:
            mc, sc, mbc, models = parse_models_bin(data, resolver)
        except Exception:  # noqa: BLE001
            continue
        finally:
            del data

        files: dict[str, int] = {}
        for p2, e2 in file_tree.items():
            if getattr(e2, "is_directory", True) or not e2.path:
                continue
            if p2.rsplit("/", 1)[0] == dir_path:
                files[e2.path.rsplit("/", 1)[-1]] = (
                    e2.file_info.unpacked_size if e2.file_info else 0)

        mat_map: dict = {}
        for m in models:
            for rs in m.render_sets:
                if rs.material_mfm_id or rs.material_mfm:
                    key = rs.material_mfm_id or rs.material_mfm
                    if key not in mat_map:
                        mat_map[key] = (rs.material_mfm_id, rs.material_mfm)
        materials = sorted(mat_map.values(), key=lambda t: t[1])
        scenes.append(SpaceScene(
            dir_path=dir_path,
            kind=detect_kind(dir_path),
            models=models,
            models_count=mc,
            skeletons_count=sc,
            model_bone_count=mbc,
            materials=materials,
            files=files,
        ))
    if progress_cb is not None:
        progress_cb(total, total)
    return scenes
