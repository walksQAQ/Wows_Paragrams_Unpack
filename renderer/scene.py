"""renderer.scene —— 把 :class:`services.geometry_service.ShipGeometry` 装配成可提交的场景。

数据流（架构文档 §2）：

    ShipGeometry / ArmorScene
        → prepare_render_mesh（与 GLB 导出共用的坐标/绕序修正）
        → MeshSpec + TextureSpec（与后端无关的描述）
        → renderer.api → C ABI → D3D11

本节只做「装配」：不猜测材质、不补默认通道（稀疏材质原则，§5.2）。
"""

from __future__ import annotations

import numpy as np

from models.geometry_transform import prepare_render_mesh

from .texture import TEX_HINTS, build_texture_spec
from .types import (
    FAM_DECAL_NORMAL,
    FAM_EMISSIVE,
    FAM_INDEXED,
    FAM_SOLID,
    FAM_UNLIT,
    MESH_ARMOR,
    MESH_HULL,
    MESH_MOUNT,
    MESHF_LINES,
    TEX_ALPHA_N,
    TEX_ART,
    TEX_DIFFUSE,
    TEX_MATID,
    TEX_MG,
    TEX_NORMAL,
    TEX_NOISE,
    TEX_TILES_A,
    TEX_TILES_MG,
    TEX_TILES_N,
    TEXKIND_2D_ARRAY,
    MeshSpec,
    TextureSpec,
)

#: 与旧渲染器一致的装甲绘制常量（搬运，勿改 —— 见架构文档 §7.4 锁定表）
PLATE_EDGE_COLOR = (0.0, 0.0, 0.0, 0.9)

#: 只接受 **2D** 纹理的槽（材质声明的单张图）
_SLOT_2D = (TEX_DIFFUSE, TEX_NORMAL, TEX_MG, TEX_MATID, TEX_ART, TEX_ALPHA_N)
#: 只接受 **2DArray** 纹理的槽（瓦片/噪声数组，靠 slice 选层）
_SLOT_ARRAY = (TEX_TILES_A, TEX_TILES_N, TEX_TILES_MG, TEX_NOISE)

#: 材质属性名 → 纹理槽（与旧渲染器 GpuMesh 的绑定点一一对应）
_SLOT_BY_KEY: dict[str, int] = {
    "materialIdMap": TEX_MATID,
    "albedoArray": TEX_TILES_A,
    "normalArray": TEX_TILES_N,
    "MGArray": TEX_TILES_MG,
    "artMap": TEX_ART,
    "rgbNoiseMap": TEX_NOISE,
    "normalMap": TEX_NORMAL,
    "g_normalMap": TEX_NORMAL,
    "metallicGlossMap": TEX_MG,
    "diffuseMap": TEX_DIFFUSE,
    "g_diffuseMap": TEX_DIFFUSE,
    "g_albedoMap": TEX_DIFFUSE,
    "g_mgMap": TEX_MG,
}

_INDEXED_ARRAY_KEYS = (
    ("arr_offset_scale", "offsetScaleMatIdArr"),
    ("arr_tile_idx", "tileIdxMatIdArr"),
    ("arr_tint", "albedoTintMatIdArr"),
    ("arr_remove", "albedoToRemoveTintMatIdArr"),
)

#: `arr_rotation` 是**复合**数组：x=rotationMatIdArr.x（UV 旋转角）、y=artStrengthMatIdArr.x
#: （artMap 覆盖强度 BaseStrength）。旧渲染器把两块数据合成一个 vec4[196] 传入（省寄存器），
#: HLSL 侧 `g_rotation[matId].y` 即 art 强度 —— 直传原始 rotationMatIdArr 会让 .y 取到
#: 别的分量，artMap 按错误强度盖满浅体（实测表现为船体发黑）。
_INDEXED_ROT_KEYS = ("rotationMatIdArr", "artStrengthMatIdArr")


def _slot_accepts(spec, slot: int) -> bool:
    """槽位类型校验：2D 槽只收 2D 纹理，数组槽只收 2DArray。

    类型不符时跳过绑定（HLSL 声明的资源维度不对会得到未定义行为/读到别的东西），
    比默默串槽安全。spec 为 None（解析失败）时也返回 False。
    """
    if spec is None:
        return False
    is_array = int(spec.kind) == int(TEXKIND_2D_ARRAY)
    if int(slot) in _SLOT_2D:
        return not is_array
    if int(slot) in _SLOT_ARRAY:
        return is_array
    return True


def _find_normal_map(mtexs: dict | None) -> tuple[str, bytes]:
    """稀疏材质：只在**已声明**的属性里找法线通道，绝不按名/前缀补全。"""
    if not mtexs:
        return ("", b"")
    for key in ("g_normalMap", "normalMap", "normalArray"):
        value = mtexs.get(key)
        if value and value[1]:
            return value
    return ("", b"")


def _family_for(tech_family: str, has_color: bool) -> int:
    """材质族判定（照搬旧渲染器的 _is_alpha_blend + tech_family 分派）。"""
    if tech_family == "indexed":
        return FAM_INDEXED
    if tech_family == "emissive":
        return FAM_EMISSIVE
    if not has_color:
        return FAM_DECAL_NORMAL      # 只提供法线的叠加层
    if tech_family in ("grid", "transparent"):
        return FAM_UNLIT             # 无光照 + alpha 混合
    if tech_family == "decal":
        return FAM_UNLIT             # 带 albedo 的贴花
    return FAM_SOLID


class _TexturePool:
    """场景内纹理去重池（同一字节 + 同一采样约定只上传一次）。"""

    def __init__(self) -> None:
        self.specs: list[TextureSpec] = []
        self._by_key: dict[str, TextureSpec] = {}
        self._by_sig: dict[tuple, str] = {}
        self._counter = 0

    def get(self, key: str) -> TextureSpec | None:
        """取已入池的 spec（用于按槽位检查 kind/格式，防止 2D⁄数组串槽）。"""
        return self._by_key.get(key)

    def add(
        self,
        data: bytes | None,
        *,
        srgb: bool = True,
        repeat: bool = False,
        point: bool = False,
        nomip: bool = False,
    ) -> str | None:
        if not data:
            return None
        sig = (id(data), srgb, repeat, point, nomip)
        hit = self._by_sig.get(sig)
        if hit is not None:
            return hit
        self._counter += 1
        key = f"t{self._counter}"
        spec = build_texture_spec(
            key, data, srgb=srgb, repeat=repeat, point=point, nomip=nomip
        )
        if spec is None:
            return None
        self.specs.append(spec)
        self._by_key[key] = spec
        self._by_sig[sig] = key
        return key


def _array_196(arrays: dict, name: str) -> np.ndarray | None:
    arr = arrays.get(name)
    if arr is None:
        return None
    a = np.asarray(arr, dtype=np.float32)
    if a.size < 196 * 4:
        return None
    return np.ascontiguousarray(a.reshape(-1, 4)[:196])


class _KeyGen:
    """网格 key 分配器：保证场景内唯一。

    ⚠️ DLL 以 key 作为网格唯一句柄（`wsr_scene_add_mesh` 遇同名 key 会**就地替换**）。
    `HullMesh.name` 是 ``部件名#材质``，而同一部件的多个节点实例组（``__inst__#K``）
    可解析成**同一个材质** ⇒ 名称重复。若不在此处去重，重复的网格会在 DLL 里互相
    覆盖，舰体大面积消失且**不报错**（阿基坦 453 → 81 实测）。

    去重规则：首次出现保持 ``kind:name``；后续同名依次接 ``#2``、``#3``…（确定性，
    同一输入顺序得同一 key，便于可见性/高亮按 key 回查）。
    """

    def __init__(self) -> None:
        self._used: set[str] = set()
        self.duplicates = 0

    def __call__(self, kind: int, name: str) -> str:
        base = f"{kind}:{name or 'mesh'}"
        key = base
        n = 1
        while key in self._used:
            n += 1
            key = f"{base}#{n}"
        if n > 1:
            self.duplicates += 1
        self._used.add(key)
        return key


def _build_mesh(
    m, kind: int, pool: _TexturePool, default_dds: bytes | None, keygen: _KeyGen
) -> MeshSpec | None:
    if getattr(m, "is_crack", False):
        return None          # 损伤网格不显示（与旧渲染器一致）
    if getattr(m, "is_wire", False):
        return None          # 线框辅助网格需要 GL_LINES 路径，暂不参与实体渲染

    positions = np.asarray(m.positions, dtype=np.float32)
    if positions.size == 0:
        return None
    indices = np.asarray(m.indices, dtype=np.uint32)
    if indices.size == 0:
        return None

    tech_family = getattr(m, "tech_family", "pbs") or "pbs"
    has_color = bool(getattr(m, "has_color", True))
    mtexs = getattr(m, "material_textures", None) or {}
    family = _family_for(tech_family, has_color)

    # ---- 纹理槽 ----
    textures: dict[int, str] = {}
    main_dds = getattr(m, "texture_dds", None) or default_dds
    if not has_color:
        # 稀疏材质 No-albedo：主贴图是其声明的 normalMap（绝不补默认颜色贴图）
        _path, nb = _find_normal_map(mtexs)
        main_dds = nb or None
    if main_dds:
        key = pool.add(main_dds, srgb=has_color)
        # ⚠️ INDEXED 的主贴图是 albedoArray（2DArray）：它进 TEX_TILES_A，
        # **不能**占 2D 的 t0（HLSL 的 g_tex 声明为 Texture2D，类型不符会读到未定义数据）。
        # 被 `_slot_accepts` 拦下是预期行为，不是错误。
        if key and _slot_accepts(pool.get(key), TEX_DIFFUSE):
            textures[TEX_DIFFUSE] = key
    for name, value in mtexs.items():
        slot = _SLOT_BY_KEY.get(name)
        if slot is None:
            continue
        if slot == TEX_DIFFUSE:
            # ⚠️ 与旧渲染器一致：diffuseMap / g_diffuseMap / g_albedoMap 属于**另一套**资源组，
            # 不能覆盖主贴图（INDEXED 下它们是 32×32 占位；覆盖会让船体变暗且丢细节）。
            continue
        # ⚠️ INDEXED 族：材质声明的 normalMap 是 **_alpha_n 法线叠加层**（与 normalArray
        # 瓦片叠加合成），进 t9；t1 是标准 PBS 的法线槽。两族不能混用同一槽
        # （旧 `_bind_indexed` 把 `normalMap` 绑到 u_alpha_n_map）。
        if family == FAM_INDEXED and slot == TEX_NORMAL:
            slot = TEX_ALPHA_N
        payload = value[1] if isinstance(value, (tuple, list)) and len(value) > 1 else None
        if not payload:
            continue
        srgb, repeat, point, nomip = TEX_HINTS.get(name, (True, False, False, False))
        key = pool.add(payload, srgb=srgb, repeat=repeat, point=point, nomip=nomip)
        if key and _slot_accepts(pool.get(key), slot):
            textures[slot] = key

    # ---- 顶点（与 GLB 导出共用同一套变换，保证「看到的 = 导出的」）----
    n_verts = positions.shape[0]
    colors = np.full((n_verts, 4), 1.0, dtype=np.float32)
    p, n, idx, uvs, cols = prepare_render_mesh(
        positions, np.asarray(m.normals, dtype=np.float32), indices, colors,
        getattr(m, "uvs", None),
    )
    vdata = np.empty((p.shape[0], 12), dtype=np.float32)
    vdata[:, 0:3] = p
    vdata[:, 3:6] = n
    if uvs is not None and len(uvs) == p.shape[0]:
        vdata[:, 6:8] = uvs
    else:
        vdata[:, 6:8] = 0.0
    vdata[:, 8:12] = cols if cols is not None else 1.0

    # ---- INDEXED 逐材质数组 ----
    indexed = getattr(m, "indexed_params", None) or {}
    arrays = indexed.get("arrays") or {}
    kwargs: dict = {}
    if family == FAM_INDEXED:
        for attr, src in _INDEXED_ARRAY_KEYS:
            arr = _array_196(arrays, src)
            if arr is not None:
                kwargs[attr] = arr
        rot = _array_196(arrays, _INDEXED_ROT_KEYS[0])
        art = _array_196(arrays, _INDEXED_ROT_KEYS[1])
        comp = np.zeros((196, 4), dtype=np.float32)
        if rot is not None:
            comp[:, 0] = rot[:, 0]
        if art is not None:
            comp[:, 1] = art[:, 0]
        kwargs["arr_rotation"] = comp
        kwargs["matid_count"] = 196

    model = getattr(m, "model_matrix", None)
    inst = getattr(m, "instance_matrices", None)
    model_matrix = None if model is None else np.asarray(model, dtype=np.float32).reshape(4, 4)
    instance_matrices = None
    if inst:
        # DLL 侧已保证「至少 1 个实例」（无实例时用 model_matrix 当单实例，见
        # `wsr_scene_add_mesh` 的实例缓冲构造），所以这里只需处理**合成**：
        # ⚠️ 与旧渲染器一致：实例化网格的最终矩阵是 **base @ inst**（`_apply_model`
        #   里 `model = inst if base is None else base @ inst`）。DLL 的实例路径
        #   `mvp = proj*view` 只吃 INST 属性、**不看 model_matrix** ⇒ 必须在这里合成，
        #   否则丢掉基准矩阵。
        arr = np.asarray(inst, dtype=np.float32).reshape(-1, 4, 4)
        if model_matrix is not None:
            arr = np.matmul(model_matrix[None, :, :], arr)
            model_matrix = None          # 已并入实例矩阵
        instance_matrices = np.ascontiguousarray(arr.reshape(-1, 16), dtype=np.float32)

    return MeshSpec(
        key=keygen(kind, str(getattr(m, "name", "mesh"))),
        kind=kind,
        family=family,
        vertices=vdata,
        indices=np.ascontiguousarray(idx, dtype=np.uint32),
        model_matrix=model_matrix,
        instance_matrices=instance_matrices,
        emissive_k=float(getattr(m, "emissive_power", None) or 1.0),
        textures=textures,
        **kwargs,
    )


def _build_armor(armor_scene) -> list[MeshSpec]:
    """装甲：三角形汤（顶点色=厚度着色）+ 板块边界线。

    坐标与旧渲染器一致：世界坐标 Z 镜像（渲染空间），法线同镜像。
    """
    out: list[MeshSpec] = []
    if armor_scene is None or not getattr(armor_scene, "tri_count", 0):
        return out

    mirror = np.array([1.0, 1.0, -1.0], dtype=np.float32)
    pos = np.ascontiguousarray(np.asarray(armor_scene.world_positions, dtype=np.float32) * mirror)
    nrm = np.ascontiguousarray(np.asarray(armor_scene.world_normals, dtype=np.float32) * mirror)
    col = np.asarray(armor_scene.colors, dtype=np.float32)

    vdata = np.empty((pos.shape[0], 12), dtype=np.float32)
    vdata[:, 0:3] = pos
    vdata[:, 3:6] = nrm
    vdata[:, 6:8] = 0.0
    if col.ndim == 2 and col.shape[1] >= 4 and col.shape[0] == pos.shape[0]:
        vdata[:, 8:12] = col[:, :4]
    else:
        vdata[:, 8:12] = 1.0
    out.append(
        MeshSpec(
            key="armor:scene",
            kind=MESH_ARMOR,
            family=FAM_UNLIT,          # 平涂直显（旧版 u_mode=2）
            vertices=vdata,
            indices=np.arange(pos.shape[0], dtype=np.uint32),
        )
    )

    epos = getattr(armor_scene, "edge_positions", None)
    if epos is not None and len(epos):
        ep = np.ascontiguousarray(np.asarray(epos, dtype=np.float32) * mirror)
        ev = np.zeros((ep.shape[0], 12), dtype=np.float32)
        ev[:, 0:3] = ep
        ev[:, 8:12] = np.asarray(PLATE_EDGE_COLOR, dtype=np.float32)
        out.append(
            MeshSpec(
                key="armor:edges",
                kind=MESH_ARMOR,
                family=FAM_UNLIT,
                flags=MESHF_LINES,
                opacity=float(PLATE_EDGE_COLOR[3]),
                vertices=ev,
                indices=np.arange(ep.shape[0], dtype=np.uint32),
            )
        )
    return out


def build_scene(geometry, armor_scene=None) -> tuple[list[TextureSpec], list[MeshSpec]]:
    """装配场景；返回 ``(纹理描述列表, 网格描述列表)``。"""
    pool = _TexturePool()
    keygen = _KeyGen()
    meshes: list[MeshSpec] = []
    if geometry is not None:
        default_dds = getattr(geometry, "texture_dds", None)
        for kind, items in ((MESH_HULL, geometry.hull_meshes), (MESH_MOUNT, geometry.mounts)):
            for item in items:
                spec = _build_mesh(item, kind, pool, default_dds, keygen)
                if spec is not None:
                    meshes.append(spec)
    meshes.extend(_build_armor(armor_scene))
    return pool.specs, meshes
