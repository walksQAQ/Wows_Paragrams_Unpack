"""
export_service.py —— 舰船 3D 模型导出（GLB / glTF 2.0 Binary）。

渲染模型（船体 + 挂载）与装甲模型**分开导出**，各自生成独立 .glb 文件：

  - export_render_glb()  → 舰体分段 + 挂载实例，层级/命名对齐 BigWorld 插件
  - export_armor_glb()   → 装甲三角形汤（按 Zone → 部件 → 厚度分组，厚度着色）

导出数据一律取自查看器已加载的 ShipGeometry / ArmorScene，不重新解析
.geometry、不读 data/split、不反向读回 OpenGL 缓冲区，因此不影响查看器的
显示功能。导出在后台线程执行（只读几何对象，不触碰 Qt/OpenGL API）。

坐标与层级约定（关键，保证不错位/不翻转，与查看器严格一致）：
  - .geometry 解析空间 = 游戏左手系（Z 朝向观察者）
  - 渲染空间 = 右手系 Y 向上（Z 镜像 negz = diag(1,1,-1,1)），与 glTF 同构
  - 顶点/法线经 models.geometry_transform.prepare_render_mesh() 统一变换到
    渲染空间（与渲染器共用同一函数 → 「导出的 = 看到的」）
  - 渲染模型的网格顶点烘焙到最终世界坐标；**空物体节点携带真实变换**：
    HP_*/MP_* 挂载节点用挂点矩阵（.visual/skeleton 的世界矩阵），网格顶点写在其
    局部坐标（world = 节点矩阵 × 顶点），所以几何世界位置不变、层级却有意义。
    舰体分段节点的源变换本就是恒等（GEOMETRY 已在舰船坐标系），故仍在原点 ——
    与 BigWorld 插件导入原始模型的结果一致。
  - 层级对齐该插件：`Scene Root` → 部件（舰体分段 / HP_* 挂载节点）空物体 →
    .visual 节点空物体 → 网格（名字 = visual 的 `<vertices>` 去后缀，如
    `Bow_wireShape`）
  - 顶点组/权重（`xyznuviiiwwtb` 的 `iiiww`）：默认**写标准 glTF skin**
    （`JOINTS_0` / `WEIGHTS_0` + `skins`），joint 节点名 = visual 骨骼名 →
    Blender 里直接得到同名顶点组与可绑定骨架。
    需要**顶点组但不要骨架**时改 `GlbRenderOptions(export_skins=False)`：改为写
    自定义属性 `_JOINTS_0`（FLOAT，骨骼索引，避免 uint8 被当成 BYTE_COLOR 归一化）
    + `_WEIGHTS_0`（FLOAT）+ `mesh.extras.bone_palette`（骨骼名表），数据完整保留，
    但 Blender 导入后不会生成 Armature / 骨骼显示球（glTF 的顶点组必须挂在 skin 上，
    skin 又必然建骨架）；随后在 Blender 运行 `tools/blender_wows_vertex_groups.py`
    按上述数据还原顶点组（不建骨架；实测与 skin 模式的顶点组逐组权重完全一致）。
    ⚠️ skins 模式的骨架节点挂在 Scene Root 下的 `<部件>_bones`（恒等变换）空物体里：
    骨骼矩阵直接是世界矩阵；bind 矩阵先做 `M4 @ bind @ M4` 共轭到渲染空间。
    若把关节挂在带挂点矩阵的部件空物体下，Blender 会把父变换重复施加，
    骨骼显示位置会跑到船外（实测偏差 6~10 单位）。
    骨骼位置严格取源数据（`.visual` 里 bind 平移为 0 的 `*_BlendBone` 就落在原点）。
  - 骨骼显示尺寸：Blender 的 `pick_bone_length()` 对「没有骨子骨骼」的根骨骼用
    「到骨架原点的距离」，舰体/炮塔动辄几米到几十米 → 棱角球比部件还大。
    因此每个 skin 额外挂一根恒等变换的 `<网格名>_root` 骨骼 + 一个
    `GlbRenderOptions.bone_length`（默认 0.2m）长的 `_tip` 子骨骼：根骨长 =
    min(子骨偏移) = 0.2，其余关节无骨子骨骼则继承父骨长 → 全部骨骼显示尺寸恒定。
    代价：每个 skin 多 2 个骨骼（Blender 里对应 2 个空顶点组）。
    需要**每根骨骼各自带骨尖**时用 `GlbRenderOptions(tip_bones=True)`
    （顶点组数量翻倍），`bone_length=0` 可退回旧行为（骨骼球随原点距离放大）。
  - 装甲沿用 ArmorScene.world_positions（舰船空间）再 negz 镜像
  - 全部材质 doubleSided=True：绕序不统一也不致背面剔除/面消失

贴图：DDS → RGBA → PNG 嵌入 GLB（BC1/BC2/BC3/BC4/BC5/BC7 + 未压缩）；
解码失败保留几何并记 warning。按 .mfm **声明的贴图键**映射到 glTF 标准 PBR 槽
（Blender 会自动接线，不是全部压到 baseColor）：

  - `diffuseMap`（或 INDEXED 的 `albedoArray` / `g_albedoMap`）→ `baseColorTexture`
  - `normalMap` / `g_normalMap` → `normalTexture`（WoWS 只存 XY，导出时补 Z；
    否则 Blender 里法线 Z=0 → 完全扁平）
  - `metallicGlossMap` / `g_mgMap` → `metallicRoughnessTexture`
    （WoWS 是 R=F0 权重、G=gloss，glTF 要 G=roughness、B=metallic，导出时换算）
  - `ambientOcclusionMap` → `occlusionTexture`
  - `detailMap` / INDEXED 图集数组 / `artMap` 无 glTF 等价物 → 只记在
    `material.extras.wows_textures`（原始 DDS 路径），不做伪造

INDEXED 族（舰体分块涂装）的 `normalMap` 是 alpha 法线叠加层且需按
materialIdMap 分块，暂不映射（避免导出错误的法线）。

顶点属性：除 POSITION/NORMAL/TEXCOORD_0-1/TANGENT 外，`r`（`_EXTRA`）与
`t`（`_T4`）原始字节按 VEC4 uint8 原样保留（glTF 无对应语义）。
"""

from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass, field

import numpy as np

from models.geometry_transform import prepare_render_mesh
from utils.threading_utils import TaskCancelled

from pygltflib import (
    GLTF2, Asset, Buffer, BufferView, Accessor, Image, Texture, Sampler,
    Material, PbrMetallicRoughness, TextureInfo, Mesh, Primitive, Attributes,
    Node, Scene, Skin, NormalMaterialTexture, OcclusionTextureInfo,
)

#: glTF 常量
_FLOAT = 5126
_UNSIGNED_BYTE = 5121
_UNSIGNED_INT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4
_REPEAT = 10497
_LINEAR = 9729
_LINEAR_MIPMAP_LINEAR = 9987
_OPAQUE = "OPAQUE"
_BLEND = "BLEND"

#: 渲染空间镜像（解析空间 → 渲染空间/glTF 的 Z 反射）
_MIRROR = np.array([1.0, 1.0, -1.0], dtype=np.float32)
#: 4x4 版镜像（矩阵共轭用：M_render = M4 @ M_game @ M4）
_MIRROR4 = np.diag([1.0, 1.0, -1.0, 1.0]).astype(np.float32)


def _check_cancel(cancel_event) -> None:
    """协作式取消检查点：取消已请求则抛出 TaskCancelled（正常结束，非错误）。"""
    if cancel_event is not None and cancel_event.is_set():
        raise TaskCancelled


# ────────────────────────────────────────────────────────────────────────────
# 选项与报告
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class GlbRenderOptions:
    """渲染模型导出选项。"""
    embed_textures: bool = True        # 是否嵌入贴图（false 导出纯几何）
    export_mounts: bool = True         # 是否包含挂载（炮塔/副炮/防空/甲板设备等）
    double_sided: bool = True          # 材质双面渲染（绕序不统一时防背面剔除）
    #: 面朝向统一翻转（glTF 默认 CCW 正面；负 Z 镜像后绕序为 CW 背面，需翻转一次）
    flip_winding: bool = True
    #: 是否导出 glTF skin（顶点组 + 骨骼权重 + Armature）。
    #: True（默认）：写标准 skin/JOINTS_0/WEIGHTS_0，Blender 里得到顶点组（按 visual
    #: 节点名命名）与可绑定骨架。
    #: False：蒙皮数据写成 ``_JOINTS_0`` / ``_WEIGHTS_0`` 自定义属性 +
    #: ``extras.bone_palette``（骨骼名表），文件里**没有** skin/joints，
    #: Blender 导入后是干净的空物体层级（无 Armature、无骨骼球），
    #: 需要顶点组时再跑 `tools/blender_wows_vertex_groups.py` 还原。
    export_skins: bool = True
    #: 合成根骨骼的骨尖长度（米，0 = 不建根骨骼）。Blender 的 `pick_bone_length()`
    #: 对「没有骨子骨骼」的根骨骼会退化成「骨骼到骨架原点的距离」（舰体动辄几十米），
    #: 而骨骼显示尺寸 = 骨长，于是骨骼棱角球比模型部件还大。
    #: >0 时把该 skin 的全部关节挂到一根恒等变换的 `<网格名>_root` 骨骼下，并给它加
    #: 一个该长度的 `_tip` 子骨骼：根骨长 = min(子骨偏移) = 该值，其余关节无骨子骨骼
    #: → 继承父骨长 → 全部骨骼显示尺寸统一、恒定。代价：每个 skin 多 2 个骨骼
    #: （对应 2 个空顶点组）。
    bone_length: float = 0.2
    #: 是否给**每根**骨骼附带一个 `*_tip` 子骨骼（仅为缩小 Blender 的骨骼显示球）。
    #: `bone_length` 已能用 2 个节点解决同一问题，本项只在需要「每根骨骼都被单独
    #: 测量」时使用；代价是 tip 必须进 `skin.joints` 才算骨骼，而 Blender 会为每个
    #: joint 建顶点组 → 顶点组数量翻倍（多出来的是空 `*_tip` 组）。默认关闭。
    tip_bones: bool = False


@dataclass
class GlbArmorOptions:
    """装甲模型导出选项。"""
    visible_only: bool = True          # 只导出查看器当前可见板块（false=全部）
    thickness_colors: bool = True      # 用厚度颜色着色（false=统一灰色）
    armor_alpha: float = 1.0           # 装甲不透明度（1.0=不透明；<1.0 用 BLEND）
    double_sided: bool = True
    #: 面朝向翻转。⚠️ 装甲默认 **False**：装甲三角形源的绕序与渲染网格相反，
    #: 负 Z 镜像后已朝外（实测 0.72），再翻转反而朝内（0.28）。渲染模型才需翻转。
    flip_winding: bool = False


@dataclass
class ExportReport:
    """导出结果摘要。"""
    output_path: str = ""
    content: str = "render"            # "render" | "armor"
    nodes: int = 0
    meshes: int = 0
    triangles: int = 0
    vertices: int = 0
    textures: int = 0
    skipped_textures: int = 0
    skipped_meshes: int = 0
    warnings: list = field(default_factory=list)
    bounds_min: tuple = ()
    bounds_max: tuple = ()
    elapsed_seconds: float = 0.0

    def summary(self) -> str:
        """面向用户的一行摘要。"""
        kind = "渲染模型" if self.content == "render" else "装甲模型"
        tex = f"，贴图 {self.textures} 张" if self.textures else ""
        skip = f"，跳过 {self.skipped_meshes} 网格" if self.skipped_meshes else ""
        warn = f"，⚠️ {len(self.warnings)} 条警告" if self.warnings else ""
        return (f"✅ 导出{kind}完成：{self.meshes} 网格 / {self.triangles:,} 三角形"
                f" / {self.vertices:,} 顶点{tex}{skip}{warn}\n→ {self.output_path}")


# ────────────────────────────────────────────────────────────────────────────
# DDS → RGBA / PNG
# ────────────────────────────────────────────────────────────────────────────

def dds_to_rgba(data: bytes) -> np.ndarray | None:
    """DDS 字节 → (H, W, 4) uint8 **RGBA**（行序与上传/采样一致）。

    支持 BC1/BC2/BC3/BC4/BC5/BC7 压缩与未压缩 BGRA/BGR；不支持返回 None。
    texture2ddecoder 输出为 **BGRA**（实测 red 编码返回 [0,0,255,255]），
    这里统一交换为 RGBA。
    """
    try:
        from models.dds_reader import parse_dds
        dds = parse_dds(data)
    except Exception:  # noqa: BLE001
        return None
    if not dds.mips:
        return None
    mip0 = dds.mips[0]
    w, h = dds.width, dds.height
    try:
        if dds.bc_kind:
            import texture2ddecoder as tdec
            if dds.bc_kind == 1:
                raw = tdec.decode_bc1(mip0, w, h)
            elif dds.bc_kind == 2:
                raw = _decode_bc2(mip0, w, h)
            elif dds.bc_kind == 3:
                raw = tdec.decode_bc3(mip0, w, h)
            elif dds.bc_kind == 4:
                raw = tdec.decode_bc4(mip0, w, h)
            elif dds.bc_kind == 6:
                raw = tdec.decode_bc5(mip0, w, h)
            elif dds.bc_kind == 8:
                raw = tdec.decode_bc7(mip0, w, h)
            else:
                return None
            arr = np.frombuffer(bytes(raw), dtype=np.uint8)
            if arr.size == w * h * 4:
                bgra = arr.reshape(h, w, 4)
            elif arr.size == w * h * 3:
                bgra = np.dstack([arr.reshape(h, w, 3),
                                  np.full((h, w, 1), 255, np.uint8)])
            else:
                return None
            rgba = bgra[:, :, [2, 1, 0, 3]].copy()
            if dds.bc_kind == 4:
                # BC4 单通道（AO / materialIdMap）：任取 RGB 中数据通道做灰度
                gray = rgba[:, :, :3].max(axis=2)
                rgba = np.dstack([gray, gray, gray,
                                  np.full((h, w, 1), 255, np.uint8)])
            return np.ascontiguousarray(rgba)
        # 未压缩 BGRA / BGR
        bpp = dds.rgba_bpp or 4
        arr = np.frombuffer(mip0, dtype=np.uint8).reshape(h, w, bpp)
        if bpp == 4:
            return np.ascontiguousarray(arr[:, :, [2, 1, 0, 3]])
        return np.ascontiguousarray(
            np.dstack([arr[:, :, [2, 1, 0]],
                       np.full((h, w, 1), 255, np.uint8)]))
    except Exception:  # noqa: BLE001
        return None


def _decode_bc2(block_data: bytes, w: int, h: int) -> bytes:
    """BC2 (DXT3) 解码：8 字节显式 alpha + 8 字节 BC1 色块。

    texture2ddecoder 无 decode_bc2，这里用 decode_bc1 解色块再覆写 alpha。
    """
    import texture2ddecoder as tdec
    n_blocks = ((w + 3) // 4) * ((h + 3) // 4)
    block_size = 16
    if len(block_data) < n_blocks * block_size:
        return b""
    rgba = bytearray(w * h * 4)
    b_idx = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            alpha_bytes = block_data[b_idx:b_idx + 8]
            color_bytes = block_data[b_idx + 8:b_idx + 16]
            b_idx += block_size
            color = tdec.decode_bc1(color_bytes, 4, 4)
            a4 = np.zeros(16, dtype=np.uint8)
            for i in range(8):
                lo = alpha_bytes[i] & 0x0F
                hi = (alpha_bytes[i] >> 4) & 0x0F
                a4[i * 2] = (lo << 4) | lo
                a4[i * 2 + 1] = (hi << 4) | hi
            for py in range(4):
                for px in range(4):
                    x, y = bx + px, by + py
                    if x >= w or y >= h:
                        continue
                    idx = (y * w + x) * 4
                    ci = (py * 4 + px) * 4
                    rgba[idx:idx + 3] = color[ci:ci + 3]
                    rgba[idx + 3] = a4[py * 4 + px]
    return bytes(rgba)


def _to_gltf_normal_map(rgba: np.ndarray) -> np.ndarray:
    """WoWS 法线图（只存 XY，B 恒 0）→ glTF/Blender 用的切线空间法线（XY 同约定）。

    WoWS shader 里是 `n = (nm.xy*2-1, sqrt(1-x²-y²))`（OpenGL/Blender 同约定），
    所以这里只补 Z 通道、保持 R=X / G=Y；否则导出后法线 Z=0 → Blender 里完全扁平。
    """
    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    if float(rgb[:, :, 2].max()) > 0.05:
        # 已有 Z 通道（少数 3 通道法线图）：原样保留
        out = rgba.copy()
        out[:, :, 3] = 255
        return out
    x = rgb[:, :, 0] * 2.0 - 1.0
    y = rgb[:, :, 1] * 2.0 - 1.0
    z = np.sqrt(np.clip(1.0 - x * x - y * y, 0.0, 1.0))
    out = np.empty_like(rgba)
    out[:, :, 0] = rgba[:, :, 0]
    out[:, :, 1] = rgba[:, :, 1]
    out[:, :, 2] = ((z * 0.5 + 0.5) * 255.0).astype(np.uint8)
    out[:, :, 3] = 255
    return out


def _to_gltf_metallic_roughness(rgba: np.ndarray) -> np.ndarray:
    """WoWS `metallicGlossMap`（R=F0 混合权重, G=gloss, B=发光强度）→ glTF MR 图。

    glTF `metallicRoughnessTexture` 约定 **G=roughness、B=metallic**，
    所以 G ← 1-gloss，B ← R（F0 权重，作为 metallic 近似）。R 通道留 AO/255。
    """
    src = rgba.astype(np.float32)
    out = np.empty_like(rgba)
    out[:, :, 0] = 255
    out[:, :, 1] = (255.0 - src[:, :, 1]).astype(np.uint8)      # roughness = 1 - gloss
    out[:, :, 2] = rgba[:, :, 0]                                # metallic ≈ F0 权重
    out[:, :, 3] = 255
    return out


#: 贴图转换类型（影响 DDS 解码后的通道处理与缓存键）
_TEX_COLOR = "color"
_TEX_NORMAL = "normal"
_TEX_MR = "mr"


def dds_to_png(data: bytes, max_size: int = 4096, kind: str = _TEX_COLOR) -> bytes | None:
    """DDS → PNG 字节（sRGB，行序保持与上传/采样一致）。失败返回 None。

    超长边降采样到 max_size 控制体积；0/负 = 不限制。
    kind：``color``（原样）/ ``normal``（补 Z 通道）/ ``mr``（gloss→roughness 换算）。
    """
    try:
        from PIL import Image
        rgba = dds_to_rgba(data)
        if rgba is None:
            return None
        if kind == _TEX_NORMAL:
            rgba = _to_gltf_normal_map(rgba)
        elif kind == _TEX_MR:
            rgba = _to_gltf_metallic_roughness(rgba)
        img = Image.fromarray(rgba, "RGBA")
        if max_size and max(rgba.shape[:2]) > max_size:
            scale = max_size / float(max(rgba.shape[:2]))
            img = img.resize((max(1, int(rgba.shape[1] * scale)),
                              max(1, int(rgba.shape[0] * scale))),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


# ────────────────────────────────────────────────────────────────────────────
# GLB 构建器
# ────────────────────────────────────────────────────────────────────────────

class _GlbBuilder:
    """增量构建 GLB：单一二进制 blob + glTF 图（bufferView/accessor/…/node）。"""

    def __init__(self):
        self.blob = bytearray()
        self.offset = 0
        self.gltf = GLTF2()
        self.gltf.asset = Asset(version="2.0", generator="WowsParagramsUnpack")
        self.gltf.scenes = [Scene()]
        self.gltf.scene = 0
        self.gltf.samplers.append(Sampler(magFilter=_LINEAR,
                                          minFilter=_LINEAR_MIPMAP_LINEAR,
                                          wrapS=_REPEAT, wrapT=_REPEAT))
        self.sampler_idx = 0
        #: 去重缓存：id(dds_bytes) -> texture index；material 键 -> index；mesh 键 -> index
        self._texture_cache: dict[int, int] = {}
        self._material_cache: dict[tuple, int] = {}
        self._mesh_cache: dict[object, int] = {}

    # ── 二进制 ─────────────────────────────────────────

    def _align(self, n: int = 4) -> None:
        pad = (-self.offset) % n
        if pad:
            self.blob += b"\x00" * pad
            self.offset += pad

    def add_buffer_view(self, data: bytes, target: int | None = None) -> int:
        self._align(4)
        idx = len(self.gltf.bufferViews)
        self.gltf.bufferViews.append(BufferView(
            buffer=0, byteOffset=self.offset, byteLength=len(data), target=target))
        self.blob += data
        self.offset += len(data)
        return idx

    def add_accessor(self, arr: np.ndarray, type_: str, component_type: int,
                     target: int | None = None, minmax: bool = False) -> int:
        arr = np.ascontiguousarray(arr)
        bv = self.add_buffer_view(arr.tobytes(), target)
        acc = Accessor(bufferView=bv, byteOffset=0, componentType=component_type,
                       count=int(arr.shape[0]), type=type_)
        if minmax and type_ == "VEC3" and component_type == _FLOAT:
            mn = arr.reshape(-1, 3).min(axis=0).astype(float).tolist()
            mx = arr.reshape(-1, 3).max(axis=0).astype(float).tolist()
            acc.min = mn
            acc.max = mx
        self.gltf.accessors.append(acc)
        return len(self.gltf.accessors) - 1

    # ── 贴图 / 材质 ─────────────────────────────────────

    def add_texture_from_dds(self, dds_bytes: bytes, label: str = "",
                             kind: str = _TEX_COLOR) -> int | None:
        """DDS → PNG → glTF 纹理（按 dds 字节对象 + 通道类型去重）。解码失败返回 None。"""
        key = (id(dds_bytes), kind)
        cached = self._texture_cache.get(key)
        if cached is not None:
            return cached
        png = dds_to_png(dds_bytes, max_size=4096, kind=kind)
        if png is None:
            return None
        bv = self.add_buffer_view(png)
        img_idx = len(self.gltf.images)
        self.gltf.images.append(Image(bufferView=bv, mimeType="image/png",
                                      name=label or None))
        tex_idx = len(self.gltf.textures)
        self.gltf.textures.append(Texture(sampler=self.sampler_idx, source=img_idx,
                                          name=label or None))
        self._texture_cache[key] = tex_idx
        return tex_idx

    def add_material(self, name: str, base_color=(1.0, 1.0, 1.0, 1.0),
                     texture_idx: int | None = None, alpha_mode: str = _OPAQUE,
                     double_sided: bool = True, extras: dict | None = None,
                     normal_tex: int | None = None,
                     mr_tex: int | None = None,
                     occlusion_tex: int | None = None,
                     emissive_tex: int | None = None,
                     metallic: float = 0.0,
                     roughness: float = 1.0) -> int:
        """材质（带去重缓存）。base_color 需可哈希（tuple）。

        贴图通道对应 glTF 标准槽：baseColor / normal / metallicRoughness /
        occlusion / emissive —— Blender 等 DCC 会自动按槽推断色彩空间与接线。
        """
        key = (texture_idx, tuple(base_color), alpha_mode, double_sided,
               normal_tex, mr_tex, occlusion_tex, emissive_tex, metallic, roughness)
        cached = self._material_cache.get(key)
        if cached is not None:
            return cached
        pbr = PbrMetallicRoughness(
            baseColorFactor=[float(x) for x in base_color],
            metallicFactor=float(metallic), roughnessFactor=float(roughness))
        if texture_idx is not None:
            pbr.baseColorTexture = TextureInfo(index=texture_idx)
        if mr_tex is not None:
            pbr.metallicRoughnessTexture = TextureInfo(index=mr_tex)
        mat = Material(pbrMetallicRoughness=pbr, alphaMode=alpha_mode,
                       doubleSided=bool(double_sided), name=name)
        if normal_tex is not None:
            mat.normalTexture = NormalMaterialTexture(index=normal_tex)
        if occlusion_tex is not None:
            mat.occlusionTexture = OcclusionTextureInfo(index=occlusion_tex)
        if emissive_tex is not None:
            mat.emissiveTexture = TextureInfo(index=emissive_tex)
            mat.emissiveFactor = [1.0, 1.0, 1.0]
        if extras:
            mat.extras = extras
        self.gltf.materials.append(mat)
        idx = len(self.gltf.materials) - 1
        self._material_cache[key] = idx
        return idx

    # ── 网格 / 节点 ─────────────────────────────────────

    def add_mesh(self, name: str, positions: np.ndarray, normals: np.ndarray,
                 indices: np.ndarray, uvs: np.ndarray | None = None,
                 material_idx: int | None = None,
                 extras: dict | None = None, cache_key=None,
                 flip_winding: bool = True,
                 uvs2: np.ndarray | None = None,
                 tangents: np.ndarray | None = None,
                 t4: np.ndarray | None = None,
                 extra: np.ndarray | None = None,
                 joints0: np.ndarray | None = None,
                 weights0: np.ndarray | None = None,
                 skin_attrs_as_custom: bool = False) -> int:
        """加入一个网格，返回 mesh 索引。

        positions/normals/indices 必须已是渲染空间（右手系）数据。
        cache_key 非 None 时按 id 去重（挂载实例共享几何，只存一份）。

        flip_winding：glTF 默认 **CCW 为正面**。解析空间经负 Z 镜像（det=-1）转右手系
        会把绕序翻转为 CW（背面朝外，Blender 里看面朝向反了，实测 400 条船外射线
        首碰面法线全部朝内）。因此导出时统一翻转一次：交换三角形绕序 + 取反法线，
        使正面 CCW 朝外且法线与新绕序一致（法线·几何法线仍 >0，光照正确）。
        """
        if cache_key is not None:
            cached = self._mesh_cache.get(cache_key)
            if cached is not None:
                return cached
        if flip_winding:
            # (a,b,c) → (a,c,b)：反向绕序；法线取反以跟随新绕序朝外
            indices = np.ascontiguousarray(indices.reshape(-1, 3)[:, [0, 2, 1]].reshape(-1))
            normals = np.ascontiguousarray(-np.asarray(normals, dtype=np.float32))
        pos_acc = self.add_accessor(positions, "VEC3", _FLOAT, _ARRAY_BUFFER, minmax=True)
        nrm_acc = self.add_accessor(normals, "VEC3", _FLOAT, _ARRAY_BUFFER)
        attrs = Attributes(POSITION=pos_acc, NORMAL=nrm_acc)
        if uvs is not None and uvs.shape[0] == positions.shape[0] and uvs.shape[1] == 2:
            uv_acc = self.add_accessor(np.asarray(uvs, dtype=np.float32),
                                       "VEC2", _FLOAT, _ARRAY_BUFFER)
            attrs.TEXCOORD_0 = uv_acc
        if uvs2 is not None and uvs2.shape[0] == positions.shape[0] and uvs2.shape[1] == 2:
            attrs.TEXCOORD_1 = self.add_accessor(np.asarray(uvs2, dtype=np.float32),
                                                 "VEC2", _FLOAT, _ARRAY_BUFFER)
        if tangents is not None and tangents.shape[0] == positions.shape[0] \
                and tangents.shape[1] == 4:
            attrs.TANGENT = self.add_accessor(np.asarray(tangents, dtype=np.float32),
                                              "VEC4", _FLOAT, _ARRAY_BUFFER)
        if extra is not None and extra.shape[0] == positions.shape[0]:
            # 自定义属性（glTF 无标准语义）：原样保留 ``r`` 的 4 个字节
            acc = self.add_accessor(np.asarray(extra, dtype=np.uint8),
                                    "VEC4", _UNSIGNED_BYTE, _ARRAY_BUFFER)
            attrs.__dict__["_EXTRA"] = acc
        if t4 is not None and t4.shape[0] == positions.shape[0]:
            # 自定义属性：单独 ``t`` 的原始 4 字节（语义未知，原样保留）
            acc = self.add_accessor(np.asarray(t4, dtype=np.uint8),
                                    "VEC4", _UNSIGNED_BYTE, _ARRAY_BUFFER)
            attrs.__dict__["_T4"] = acc
        if joints0 is not None and weights0 is not None \
                and joints0.shape[0] == positions.shape[0] \
                and weights0.shape[0] == positions.shape[0]:
            if skin_attrs_as_custom:
                # 不建 skin：顶点组/权重写成自定义属性（`_` 前缀），数据不丢，
                # 但 Blender 不会因此生成 Armature（也就没有骨骼球）。
                # ⚠️ 骨骼**索引**必须以 FLOAT 写：glTF 的 VEC4 uint8 会被 Blender
                # 当作 BYTE_COLOR 并按 /255 归一化（索引 5 → 0.0196，失真）；
                # FLOAT 则原样保留（实测导入为 FLOAT_COLOR，值不变）。
                attrs.__dict__["_JOINTS_0"] = self.add_accessor(
                    np.asarray(joints0, dtype=np.float32), "VEC4", _FLOAT,
                    _ARRAY_BUFFER)
                attrs.__dict__["_WEIGHTS_0"] = self.add_accessor(
                    np.asarray(weights0, dtype=np.float32), "VEC4", _FLOAT,
                    _ARRAY_BUFFER)
            else:
                attrs.JOINTS_0 = self.add_accessor(
                    np.asarray(joints0, dtype=np.uint8), "VEC4", _UNSIGNED_BYTE,
                    _ARRAY_BUFFER)
                attrs.WEIGHTS_0 = self.add_accessor(
                    np.asarray(weights0, dtype=np.float32), "VEC4", _FLOAT,
                    _ARRAY_BUFFER)
        idx_acc = self.add_accessor(indices.astype(np.uint32), "SCALAR",
                                    _UNSIGNED_INT, _ELEMENT_ARRAY_BUFFER)
        prim = Primitive(attributes=attrs, indices=idx_acc, mode=_TRIANGLES)
        if material_idx is not None:
            prim.material = material_idx
        mesh = Mesh(primitives=[prim], name=name)
        if extras:
            mesh.extras = extras
        self.gltf.meshes.append(mesh)
        idx = len(self.gltf.meshes) - 1
        if cache_key is not None:
            self._mesh_cache[cache_key] = idx
        return idx

    def add_node(self, name: str, mesh: int | None = None,
                 matrix: np.ndarray | None = None,
                 extras: dict | None = None) -> int:
        """加入一个节点，返回 node 索引。

        matrix：渲染空间行主序 4x4（world = m @ local）；glTF 列主序存储。
        """
        node = Node(name=name, mesh=mesh)
        if matrix is not None:
            node.matrix = [float(x) for x in matrix.T.flatten().tolist()]
        if extras:
            node.extras = extras
        self.gltf.nodes.append(node)
        return len(self.gltf.nodes) - 1

    def add_children(self, parent_idx: int, child_idxs: list[int]) -> None:
        node = self.gltf.nodes[parent_idx]
        if node.children is None:
            node.children = []
        node.children.extend(child_idxs)

    # ── 蒙皮 / skin ────────────────────────────────────

    def skin_data(self, src, bone_indices: np.ndarray, bone_weights: np.ndarray):
        """提取蒙皮数据 → (joints0, weights0, joints_matrices, joint_names)。

        bone_indices/bone_weights：逐顶点 (N,4) 数组（**拆点后**的数组，与顶点一一对应）。
        joints0：(N,4) uint8，索引指向 joints_matrices/joint_names（已重映射为紧凑索引）；
        weights0：(N,4) float32 归一化；joints_matrices：有效骨骼的 bind 世界矩阵
        （游戏空间）；joint_names：骨骼名（visual 节点名，来自 `skin_bones`）。
        无蒙皮数据返回 (None, None, [], [])。
        """
        if bone_indices is None or bone_weights is None \
                or not getattr(src, "skin_bind", None):
            return None, None, [], []
        bind = list(src.skin_bind)
        names = list(getattr(src, "skin_bones", None) or [])
        slot_to_joint: dict = {}
        joints: list = []
        joint_names: list = []
        for i, m in enumerate(bind):
            if m is not None:
                slot_to_joint[i] = len(joints)
                joints.append(m)
                joint_names.append(str(names[i]) if i < len(names) else f"bone{i}")
        if not joints:
            return None, None, [], []
        slots = np.asarray(bone_indices, dtype=np.int64) // 3  # 调色板 slot
        n = len(bind)
        remap = np.zeros(n, dtype=np.int64)
        for si, ji in slot_to_joint.items():
            remap[si] = ji
        cl = np.clip(slots, 0, n - 1)
        joints0 = remap[cl].astype(np.uint8)
        weights0 = np.asarray(bone_weights, dtype=np.float32).copy()
        valid = (slots >= 0) & (slots < n) & \
            np.asarray([m is not None for m in bind], dtype=bool)[cl]
        weights0[~valid] = 0.0
        s = weights0.sum(axis=1, keepdims=True)
        s[s < 1e-6] = 1.0
        weights0 = weights0 / s
        return joints0, weights0, joints, joint_names

    def build_skin(self, name: str, joints_matrices: list, joint_names: list,
                   joint_parent: int | None = None,
                   pre_matrix: np.ndarray | None = None,
                   anchors: list | None = None,
                   tip_length: float = 0.2,
                   scene_children: list[int] | None = None,
                   root_tip: float = 0.0) -> int:
        """创建 joint 节点 + 逆 bind accessor + glTF Skin，返回 skin 索引。

        joint 节点名取 visual 节点名 → Blender 导入后顶点组就是这些名字。

        坐标换算（两者都不能少，否则骨骼位置会明显跑偏）：
          - bind 矩阵来自 assets.bin，是**游戏空间**（Z 朝观察者），必须先共轭到
            渲染空间：``render_bind = M4 @ bind @ M4``；
          - 关节世界矩阵 = ``pre_matrix @ render_bind``（pre_matrix = 挂点→世界）。
        ⚠️ joint_parent 必须是**恒等变换**的节点：Blender 的 glTF 导入器把 armature
        对象放在关节父节点上、骨骼坐标按世界算，挂在带挂点矩阵的部件下会被父变换
        重复施加（骨骼跑到船外）。因此调用方把关节挂到 Scene Root 下的 `<part>_bones`。
        inverseBindMatrices 必须是**关节世界矩阵**的逆（glTF 语义），这样 bind pose
        下 worldJoint × inverseBind = I，蒙皮网格保持烘焙位置不变。

        anchors：已废弃（保留参数兼容）——舰体天线的 `*_BlendBone` 在源 `.visual`
        里 bind 平移就是 0，骨骼落在原点属于原始数据，不再伪造落点。

        tip_length：给每根骨骼加一个子级「骨尖」节点（沿局部 +Y 偏移），用于告诉
        Blender 骨长。否则 importer 的 `pick_bone_length()` 在「无子骨骼」时退化用
        「骨骼到原点的距离」（炮塔实测 6.6），而骨骼显示球尺寸 = 骨长 × 5%
        （`custom_shape_scale_xyz`）→ 球大得离谱。0 = 不加。

        root_tip：合成根骨骼的骨尖长度（0 = 不建根骨骼）。>0 时把全部关节挂到一根
        恒等变换的 `<name>_root` 骨骼下，并给它加一个该长度的 `_tip` 子骨骼。
        Blender 的 `pick_bone_length()`：有骨子骨骼 → 取 min(子骨偏移)，否则父级是
        骨骼 → 继承父骨长。于是根骨长 = root_tip，全部关节继承同一骨长，
        骨骼显示尺寸恒定且与模型尺度无关（不再随「到原点距离」放大）。

        ⚠️ skin.joints 的顺序前 n 个**必须**与 joints0 的索引一一对应（JOINTS_0 指向
        该数组下标）。骨尖/根骨骼一律追加到数组尾部，绝不能与真骨骼交错，否则索引
        整体错位 —— 顶点权重会落到别的骨骼（甚至骨尖）上，Blender 里看到的顶点组
        数量也会变多。
        """
        joint_nodes: list[int] = []
        parented: list[int] = []
        inv_binds: list[np.ndarray] = []
        used: set[str] = set()
        worlds: list[np.ndarray] = []
        # 1) 先按 joints0 的顺序建全部真骨骼（前 n 个 = 权重索引目标）
        for i, m in enumerate(joints_matrices):
            jname = _sanitize(joint_names[i] if i < len(joint_names) else f"bone{i}")
            if jname in used:
                jname = f"{jname}_{i}"
            used.add(jname)
            bind = np.asarray(m, dtype=np.float32)
            m_world = (_MIRROR4 @ bind @ _MIRROR4).astype(np.float64)
            if pre_matrix is not None:
                m_world = np.asarray(pre_matrix, dtype=np.float64) @ m_world
            jn = self.add_node(name=jname, matrix=m_world.astype(np.float32))
            joint_nodes.append(jn)
            parented.append(jn)
            inv_binds.append(np.linalg.inv(m_world).astype(np.float32))
            worlds.append(m_world)
        # 2) 骨尖追加在尾部（只影响 Blender 的骨长推断，不参与权重索引）
        if tip_length > 0:
            for jn, jname, m_world in zip(parented,
                                          [self.gltf.nodes[n].name for n in parented],
                                          worlds):
                tip = np.eye(4, dtype=np.float32)
                tip[1, 3] = float(tip_length)          # 局部 +Y
                tip_idx = self.add_node(name=f"{jname}_tip", matrix=tip)
                self.add_children(jn, [tip_idx])       # 骨尖只挂在该骨骼下
                joint_nodes.append(tip_idx)
                inv_binds.append(np.linalg.inv(
                    (m_world @ tip.astype(np.float64))).astype(np.float32))
        # 3) 合成根骨骼：全部关节挂到它下面 + 给它一个 root_tip 长的骨尖，
        #    使 Blender 推断出的骨长恒为 root_tip（详见 docstring）
        anchor_nodes = parented
        root_node = None
        if root_tip > 0 and parented:
            base = _sanitize(f"{name}_root") or "WOWS_root"
            rname = base
            k = 1
            while rname in used:
                rname = f"{base}_{k}"
                k += 1
            used.add(rname)
            root_node = self.add_node(name=rname, matrix=np.eye(4, dtype=np.float32))
            tname = f"{rname}_tip"
            while tname in used:
                tname = f"{tname}_"
            used.add(tname)
            tip_m = np.eye(4, dtype=np.float32)
            tip_m[1, 3] = float(root_tip)             # 根骨骼局部 +Y
            root_tip_node = self.add_node(name=tname, matrix=tip_m)
            self.add_children(root_node, [root_tip_node] + parented)
            joint_nodes.extend([root_node, root_tip_node])
            inv_binds.append(np.eye(4, dtype=np.float32))
            inv_binds.append(np.linalg.inv(
                tip_m.astype(np.float64)).astype(np.float32))
            anchor_nodes = [root_node]
        if joint_parent is not None:
            self.add_children(joint_parent, anchor_nodes)
        elif scene_children is not None:
            scene_children.extend(anchor_nodes)
        inv_arr = np.ascontiguousarray(
            np.stack([m.T for m in inv_binds]))  # (n,4,4) float32，glTF 列主序
        inv_acc = self.add_accessor(inv_arr, "MAT4", _FLOAT)
        self.gltf.skins.append(Skin(joints=joint_nodes,
                                    inverseBindMatrices=inv_acc,
                                    skeleton=(root_node if root_node is not None
                                              else joint_nodes[0]),
                                    name=name))
        return len(self.gltf.skins) - 1

    # ── 输出 ────────────────────────────────────────────

    def finalize(self, output_path: str, scene_children: list[int] | None = None) -> None:
        """把 blob 写入 GLB（原子写：先写临时文件再替换）。

        scene_children：场景根直接引用的节点索引列表（扁平结构，无空容器占位）。
        None 时保持现有 scene 引用。
        """
        if scene_children is not None:
            self.gltf.scenes[0].nodes = scene_children
        self.gltf.set_binary_blob(bytes(self.blob))
        self.gltf.buffers = [Buffer(byteLength=len(self.blob))]
        tmp = f"{output_path}.tmp{os.getpid()}"
        ok = self.gltf.save_binary(tmp)
        if not ok:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise RuntimeError("GLB 写入失败（pygltflib save_binary 返回 False）")
        os.replace(tmp, output_path)


# ────────────────────────────────────────────────────────────────────────────
# 导出入口
# ────────────────────────────────────────────────────────────────────────────

def export_render_glb(geometry, output_path: str, options: GlbRenderOptions | None = None,
                      progress_cb=None, cancel_event=None) -> ExportReport:
    """导出渲染模型（舰体 + 挂载）为 GLB。

    geometry：已加载的 ShipGeometry（查看器 _current_geom，后台线程只读）。
    """
    options = options or GlbRenderOptions()
    _check_cancel(cancel_event)
    t0 = time.time()
    report = ExportReport(output_path=str(output_path), content="render")

    builder = _GlbBuilder()
    builder.gltf.asset.extras = {
        "game_key": geometry.game_key,
        "display_name": geometry.display_name,
        "model_folder": geometry.model_folder,
        "content": "render",
        "hierarchy": "bigworld-visual",
        "wows_export_version": 5,
    }
    # ── 层级：对齐 BigWorld 插件（.primitives + .visual）的导入样式 ──
    #   Scene Root
    #   ├─ <部件>          舰体分段/挂载模型 → 空物体
    #   │   └─ <visual 节点>   按名称前缀嵌套（近似 .visual 的 <node> 树）
    #   │       └─ <Shape>     网格（名字 = visual 的 <vertices> 去后缀）
    # 顶点烘焙到世界坐标；网格节点本身不带变换（坐标即世界），部件空物体携带挂点
    # 矩阵；骨架（skins 模式）单独挂在恒等变换的空物体下，见 _emit 内注释。
    root_node = builder.add_node(name="Scene Root")
    scene_children: list[int] = [root_node]
    #: 部件节点索引 → 骨架空物体索引（同一部件的多个蒙皮网格共用一个骨架）
    bones_nodes: dict[int, int] = {}

    bmin = np.full(3, np.inf, dtype=np.float32)
    bmax = np.full(3, -np.inf, dtype=np.float32)
    fallback_tex = getattr(geometry, "texture_dds", None)
    used_names: set[str] = {"Scene Root"}

    def _unique_name(base: str, fallback: str = "mesh") -> str:
        """节点/网格名去重（Blender 对象同名会被加 .001，这里先自己保证唯一）。"""
        name = _sanitize(base) or fallback
        if name not in used_names:
            used_names.add(name)
            return name
        i = 2
        while f"{name}_{i}" in used_names:
            i += 1
        name = f"{name}_{i}"
        used_names.add(name)
        return name

    class _Part:
        """一个源模型（舰体分段 / 挂载实例）→ 部件空物体 + visual 节点空物体树。

        world：该部件节点的世界矩阵（渲染空间行主序）。挂载用真实挂点矩阵，
        舰体分段为 None（.visual 里就是恒等 → 空物体在原点，几何本身在舰船空间，
        与 BigWorld 插件导入一致）。子网格顶点会转到该节点局部坐标（见 `_emit`）。
        """

        def __init__(self, label: str, world=None):
            self.label = label
            self.world = None if world is None else np.asarray(world, dtype=np.float32)
            self.inv_world = (None if self.world is None
                              else np.linalg.inv(self.world.astype(np.float64))
                              .astype(np.float32))
            self.node = builder.add_node(name=_unique_name(label), matrix=self.world)
            builder.add_children(root_node, [self.node])
            self.nodes: dict[str, int] = {"Scene Root": self.node}

        def build_nodes(self, node_names) -> None:
            """按「名称前缀」嵌套创建 visual 节点空物体（.visual 里是显式树）。

            与部件同名的节点（如 Bow 部件里的 `Bow`）直接映射到部件空物体本身，
            不再套一层；其余按最长前缀挂到已有节点下。
            """
            names = [n for n in node_names if n and n != "Scene Root"]
            if self.label:
                self.nodes.setdefault(self.label, self.node)
            for nm in sorted(set(names), key=len):
                if nm in self.nodes:
                    continue
                parent, best = self.node, -1
                for exist, idx in self.nodes.items():
                    if nm.startswith(exist + "_") and len(exist) > best:
                        best, parent = len(exist), idx
                idx = builder.add_node(name=_unique_name(nm))
                builder.add_children(parent, [idx])
                self.nodes[nm] = idx

        def parent_for(self, node_name: str) -> int:
            return self.nodes.get(node_name or "", self.node)

    class _Slice:
        """合并网格的一个 shape 切片（顶点/索引改为相对该切片）。"""

        def __init__(self, src, v0: int, vn: int, i0: int, ic: int, mat):
            sl = slice(v0, v0 + vn)
            self.positions = src.positions[sl]
            self.normals = src.normals[sl]
            self.indices = np.ascontiguousarray(
                np.asarray(src.indices[i0:i0 + ic], dtype=np.int64) - v0, dtype=np.uint32)
            for attr in ("uvs", "uv2", "tangents", "binormals", "t4", "extra",
                         "bone_indices", "bone_weights"):
                arr = getattr(src, attr, None)
                setattr(self, attr, None if arr is None else arr[sl])
            self.material = mat
            self.texture_dds = getattr(src, "texture_dds", None)
            self.texture_path = getattr(src, "texture_path", "")
            self.is_wire = bool(getattr(src, "is_wire", False))
            self.skin_bones = list(getattr(src, "skin_bones", None) or [])
            self.skin_bind = list(getattr(src, "skin_bind", None) or [])
            # 材质通道信息必须一起带上：否则拆出来的 shape 会丢掉
            # normal / metallicGloss / AO（舰体正是被拆成多个 shape 的）
            self.tech_family = getattr(src, "tech_family", "pbs")
            self.material_textures = dict(getattr(src, "material_textures", None) or {})
            self.indexed_params = getattr(src, "indexed_params", None)
            self.has_color = bool(getattr(src, "has_color", True))
            self.opaque = bool(getattr(src, "opaque", True))

    def _pieces(src):
        """按 `shape_spans` 把合并网格拆回 .visual 的 renderSet：[(shape, node, view)]。"""
        spans = getattr(src, "shape_spans", None) or []
        if not spans:
            return [("", "", src)]
        out = []
        for (shape, node, v0, vn, i0, ic) in spans:
            if vn <= 0 or ic <= 0:
                continue
            if v0 == 0 and vn == src.positions.shape[0]:
                out.append((shape, node, src))
            else:
                out.append((shape, node, _Slice(src, v0, vn, i0, ic,
                                                getattr(src, "material", None))))
        return out

    def _emit(src, name, matrix, component, parent_idx, extras=None,
              parent_world=None):
        """单个网格：镜像/顶点拆分 → 烘焙矩阵 → 节点局部化 → 材质 → 网格 + Shape 节点。

        parent_world：父空物体的世界矩阵；给了就把顶点转到它的局部坐标
        （world = parent_world @ p），使空物体能携带真实挂点变换而几何世界位置不变。
        """
        nonlocal bmin, bmax
        if getattr(src, "is_wire", False):
            report.skipped_meshes += 1
            return
        uv2 = getattr(src, "uv2", None)
        tan = getattr(src, "tangents", None)
        bin_ = getattr(src, "binormals", None)
        raw_t4 = getattr(src, "t4", None)
        raw_extra = getattr(src, "extra", None)
        bone_idx = getattr(src, "bone_indices", None)
        bone_w = getattr(src, "bone_weights", None)
        # 骨骼索引/权重也放进 extra_attributes：绕序拆分复制顶点时同步扩展，
        # 保证 iiiww 数据与拆点后的顶点一一对应（否则顶点组会错位/丢失）。
        scalar_attrs = [uv2, raw_t4, raw_extra, bone_idx, bone_w]
        vector_attrs = [tan, bin_]
        p, n, idx, uvs, _c = prepare_render_mesh(
            src.positions, src.normals, src.indices, None, getattr(src, "uvs", None),
            extra_attributes=scalar_attrs, vector_attributes=vector_attrs)
        uv2, raw_t4, raw_extra, bone_idx, bone_w = scalar_attrs
        tan, bin_ = vector_attrs
        if p.shape[0] == 0 or idx.size == 0:
            report.skipped_meshes += 1
            return
        # ── 蒙皮数据（xyznuviiiwwtb 的 iiiww）提前取出，决定顶点坐标空间 ──
        joints0, weights0, joints_mat, joint_names = builder.skin_data(src, bone_idx, bone_w)
        skinned = joints0 is not None and options.export_skins
        node_matrix = None
        if parent_world is not None:
            inv_w = np.linalg.inv(
                np.asarray(parent_world, dtype=np.float64)).astype(np.float32)
            if skinned:
                # glTF 的 skin 结果在**世界空间**（节点自身变换被忽略）：顶点保持
                # 世界坐标，骨骼也放世界；而蒙皮网格的节点矩阵取 inv(父) ——
                # 这样 Blender 拿到的对象变换是单位阵，不会把世界坐标再乘一次。
                node_matrix = inv_w
            else:
                # 普通网格：世界坐标 ← 父空物体变换 × 局部顶点，
                # 把挂点矩阵从顶点挪到父节点上（几何世界位置不变）
                matrix = inv_w if matrix is None \
                    else inv_w @ np.asarray(matrix, dtype=np.float32)
        if matrix is not None:
            p = _apply_matrix(p, matrix).astype(np.float32)
            n = _apply_matrix3(n, matrix).astype(np.float32)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            ln[ln < 1e-8] = 1.0
            n = (n / ln).astype(np.float32)
            if tan is not None:
                tan = _apply_matrix3(np.asarray(tan, dtype=np.float32), matrix)
            if bin_ is not None:
                bin_ = _apply_matrix3(np.asarray(bin_, dtype=np.float32), matrix)
        # TANGENT = xyz + w（由 normal×tangent 与 binormal 的朝向得到）
        tangent4 = None
        if tan is not None:
            t = np.asarray(tan, dtype=np.float32)
            nv = np.asarray(n, dtype=np.float32)
            b = (np.asarray(bin_, dtype=np.float32) if bin_ is not None
                 else np.cross(nv, t))
            w = np.sign(np.sum(np.cross(nv, t) * b, axis=1))
            w[w == 0] = 1.0
            tangent4 = np.hstack([t, w[:, None]]).astype(np.float32)
        tex = getattr(src, "texture_dds", None) or fallback_tex
        tex_idx = None
        if options.embed_textures and tex:
            tex_idx = builder.add_texture_from_dds(tex, name)
            if tex_idx is None:
                report.skipped_textures += 1
        # ── 其他 PBR 通道：只认 .mfm 声明的贴图键（material_textures）──
        mtexs = getattr(src, "material_textures", None) or {}

        def _pick(*keys):
            for k in keys:
                v = mtexs.get(k)
                if v and len(v) > 1 and v[1]:
                    return v
            return None

        normal_idx = mr_idx = ao_idx = None
        # INDEXED 族的 normalMap 是 alpha 法线叠加层（见 renderer/scene.py），
        # 贴图集也要逐材质分块才能取到正确结果 → 仅标准 PBS 材质接 PBR 通道。
        if options.embed_textures and getattr(src, "tech_family", "pbs") != "indexed":
            for kind, keys, slot in (
                (_TEX_NORMAL, ("normalMap", "g_normalMap"), "normal"),
                (_TEX_MR, ("metallicGlossMap", "g_mgMap"), "mr"),
                (_TEX_COLOR, ("ambientOcclusionMap",), "ao"),
            ):
                picked = _pick(*keys)
                if not picked:
                    continue
                slot_idx = builder.add_texture_from_dds(picked[1], f"{name}_{slot}", kind)
                if slot_idx is None:
                    report.skipped_textures += 1
                    continue
                if slot == "normal":
                    normal_idx = slot_idx
                elif slot == "mr":
                    mr_idx = slot_idx
                else:
                    ao_idx = slot_idx
        mat_idx = builder.add_material(
            getattr(src, "material", None) or name,
            base_color=(1.0, 1.0, 1.0, 1.0), texture_idx=tex_idx,
            double_sided=options.double_sided,
            extras={"component": component,
                    "texture_path": getattr(src, "texture_path", ""),
                    "wows_textures": {k: (v[0] if isinstance(v, (tuple, list)) else "")
                                      for k, v in mtexs.items()}},
            normal_tex=normal_idx, mr_tex=mr_idx, occlusion_tex=ao_idx)
        # ── 顶点组 / 权重（iiiww 属性）──
        mesh_extras = dict(extras or {}, component=component)
        if joints0 is not None and not skinned:
            # 数据保留（自定义属性）+ 骨骼名表，供需要时重建顶点组/骨骼
            mesh_extras["bone_palette"] = list(joint_names)
        mesh_idx = builder.add_mesh(name, p, n, idx, uvs, mat_idx,
                                    extras=mesh_extras,
                                    flip_winding=options.flip_winding,
                                    uvs2=uv2, tangents=tangent4, t4=raw_t4,
                                    extra=raw_extra,
                                    joints0=joints0, weights0=weights0,
                                    skin_attrs_as_custom=not skinned)
        skin_idx = None
        if skinned:
            # 骨架节点挂在**恒等变换**的空物体下（Scene Root 的子级）：
            # Blender 的 glTF 导入器把 armature 对象放在关节的父节点上、骨骼坐标按
            # 世界空间算 —— 若挂在带挂点矩阵的部件空物体下，父变换会被重复施加，
            # 骨骼就跑到船外去了。父级保持恒等 → 关节局部矩阵 == 世界矩阵。
            bnode = bones_nodes.get(parent_idx)
            if bnode is None:
                part_name = (builder.gltf.nodes[parent_idx].name or "mount") + "_bones"
                bnode = builder.add_node(name=_unique_name(part_name))
                builder.add_children(root_node, [bnode])
                bones_nodes[parent_idx] = bnode
            # 骨骼位置严格按 bind 矩阵（源 .visual 里 bind 平移为 0 的 BlendBone 就落在
            # 原点，属原始数据，不做任何补偿）
            skin_idx = builder.build_skin(name, joints_mat, joint_names,
                                          joint_parent=bnode, pre_matrix=matrix,
                                          tip_length=0.2 if options.tip_bones else 0.0,
                                          root_tip=float(options.bone_length or 0.0))
        node = builder.add_node(name=name, mesh=mesh_idx, matrix=node_matrix)
        if skin_idx is not None:
            builder.gltf.nodes[node].skin = skin_idx
        builder.add_children(parent_idx, [node])
        report.meshes += 1
        report.triangles += int(idx.size) // 3
        report.vertices += int(p.shape[0])
        # 包围盒按世界坐标统计：蒙皮网格顶点已是世界坐标，其余需乘父变换
        if skinned or parent_world is None:
            world_p = p
        else:
            world_p = _apply_matrix(p, np.asarray(parent_world, dtype=np.float32))
        bmin = np.minimum(bmin, world_p.min(axis=0))
        bmax = np.maximum(bmax, world_p.max(axis=0))

    def _shape_label(src, shape: str, fallback: str) -> str:
        """网格名：优先 renderSet 的 Shape 名（与插件导入同名），否则部件+材质。"""
        return (shape or f"{fallback}_{getattr(src, 'material', None) or 'default'}Shape")

    def _node_list(src):
        spans = getattr(src, "shape_spans", None) or []
        names = [sp[1] for sp in spans if sp[1] and sp[1] != "Scene Root"]
        if names:
            return names
        return [n for n in (getattr(src, "node_names", None) or [])
                if n and n != "Scene Root"]

    def _part_label(stem: str) -> str:
        """部件空物体名 = 模型文件短名（ASA036_Essex_1945_MidBack → MidBack），
        与 .visual 里该部件的根节点同名（插件导入时就是这个层级）。"""
        folder = str(getattr(geometry, "model_folder", "") or "")
        if folder and stem.startswith(folder + "_"):
            return stem[len(folder) + 1:]
        return stem

    # ── 舰体分段：每个分段（Bow/MidFront/…）一个空物体，renderSet 各一个网格 ──
    hull_parts: dict[str, _Part] = {}
    n_hull = len(geometry.hull_meshes)
    for i, hm in enumerate(geometry.hull_meshes):
        _check_cancel(cancel_event)
        if progress_cb:
            progress_cb(5 + 60 * i / max(1, n_hull), f"导出舰体 {i + 1}/{n_hull}")
        key = str(hm.name).split("#")[0].split("|")[0]
        part = hull_parts.get(key)
        if part is None:
            part = hull_parts.setdefault(key, _Part(_part_label(key)))
        part.build_nodes(_node_list(hm))
        inst = getattr(hm, "instance_matrices", None) or []
        matrices = list(inst) if inst else [None]
        for k, matrix in enumerate(matrices):
            for shape, node_name, piece in _pieces(hm):
                label = _shape_label(piece, shape, key)
                if len(matrices) > 1:
                    label = f"{label}_{k}"
                _emit(piece, _unique_name(label), matrix, "hull",
                      part.parent_for(node_name))

    # ── 挂载：每个挂载节点（HP_*/MP_*）一个空物体，内含其模型形状 ──
    mounts = geometry.mounts if options.export_mounts else []
    mount_parts: dict[tuple, _Part] = {}
    n_mounts = len(mounts)
    for i, mm in enumerate(mounts):
        _check_cancel(cancel_event)
        if progress_cb:
            progress_cb(65 + 30 * i / max(1, n_mounts), f"导出挂载 {i + 1}/{n_mounts}")
        inst = getattr(mm, "instance_matrices", None) or []
        labels = list(getattr(mm, "instance_labels", None) or [])
        if inst:
            matrices = [(labels[k] if k < len(labels) else str(mm.name), m)
                        for k, m in enumerate(inst)]
        elif getattr(mm, "model_matrix", None) is not None:
            matrices = [(labels[0] if labels else str(mm.name), mm.model_matrix)]
        else:
            matrices = [(labels[0] if labels else str(mm.name), None)]
        component = getattr(mm, "component", "")
        nodes = _node_list(mm)
        for label, matrix in matrices:
            # 同一挂载节点的多材质分片共用一个空物体（不按材质再拆一层）
            key = (component, label)
            part = mount_parts.get(key)
            if part is None:
                # 空物体携带真实挂点矩阵（渲染空间），顶点随后转到它的局部坐标
                part = mount_parts.setdefault(key, _Part(label, world=matrix))
            part.build_nodes(nodes)
            for shape, node_name, piece in _pieces(mm):
                name = _shape_label(piece, shape, getattr(mm, "model_folder", "") or label)
                _emit(piece, _unique_name(name), matrix, component,
                      part.parent_for(node_name),
                      extras={"mount": label}, parent_world=part.world)

    report.textures = len(builder._texture_cache)
    if np.isfinite(bmin).all():
        report.bounds_min = tuple(bmin.tolist())
        report.bounds_max = tuple(bmax.tolist())
    if progress_cb:
        progress_cb(95, "写入 GLB...")
    builder.finalize(output_path, scene_children=scene_children)
    report.nodes = len(builder.gltf.nodes)
    report.elapsed_seconds = time.time() - t0
    return report


def export_armor_glb(geometry, armor_scene, output_path: str,
                     options: GlbArmorOptions | None = None,
                     visible_tris=None, progress_cb=None,
                     cancel_event=None) -> ExportReport:
    """导出装甲模型为 GLB（按 Zone → 部件 → 厚度分组，厚度着色）。

    armor_scene：查看器已构建的 ArmorScene（世界空间三角形汤）。
    visible_tris：可选 (T,) bool 掩码（查看器当前可见三角形）；None=全部。
    """
    options = options or GlbArmorOptions()
    _check_cancel(cancel_event)
    t0 = time.time()
    report = ExportReport(output_path=str(output_path), content="armor")
    sc = armor_scene
    if sc is None or not sc.tri_count:
        report.warnings.append("当前舰船没有装甲数据")
        report.elapsed_seconds = time.time() - t0
        return report

    builder = _GlbBuilder()
    builder.gltf.asset.extras = {
        "game_key": geometry.game_key,
        "display_name": geometry.display_name,
        "model_folder": geometry.model_folder,
        "content": "armor",
        "visible_only": bool(options.visible_only),
        "wows_export_version": 2,
    }
    # 扁平层级：无空容器占位节点，每块装甲板直接挂场景根（坐标由自身顶点承担），
    # zone/部件/厚度信息编码进节点名 + extras。
    scene_children: list[int] = []

    mirror = _MIRROR
    zones = sc.zones
    n_plates = sum(len(parts) for parts in zones.values() for _ in parts.values())
    done = 0
    bmin = np.full(3, np.inf, dtype=np.float32)
    bmax = np.full(3, -np.inf, dtype=np.float32)
    total_tri = 0
    total_vert = 0

    for zone in sorted(zones):
        for part in sorted(zones[zone]):
            for tenths in sorted(zones[zone][part]):
                done += 1
                if progress_cb:
                    progress_cb(10 + 85 * done / max(1, n_plates),
                                f"导出装甲 {done}/{n_plates}")
                _check_cancel(cancel_event)
                tri_list = np.asarray(zones[zone][part][tenths], dtype=np.int64)
                if options.visible_only and visible_tris is not None:
                    tri_list = tri_list[visible_tris[tri_list]]
                if tri_list.size == 0:
                    continue
                info = sc.tri_info[int(tri_list[0])]
                pos = sc.world_positions[tri_list[:, None] * 3 + np.arange(3)].reshape(-1, 3)
                nrm = sc.world_normals[tri_list[:, None] * 3 + np.arange(3)].reshape(-1, 3)
                # 渲染空间 = 舰船空间 Z 镜像
                pos_r = np.ascontiguousarray(pos * mirror)
                nrm_r = np.ascontiguousarray(nrm * mirror)
                ln = np.linalg.norm(nrm_r, axis=1, keepdims=True)
                ln[ln < 1e-8] = 1.0
                nrm_r = np.ascontiguousarray(nrm_r / ln)
                idx = np.arange(pos_r.shape[0], dtype=np.uint32)
                if options.thickness_colors:
                    base_color = _color_tuple(info.color, options.armor_alpha)
                else:
                    base_color = (0.72, 0.72, 0.72, options.armor_alpha)
                alpha_mode = _BLEND if options.armor_alpha < 0.999 else _OPAQUE
                mm = tenths / 10.0
                plate_name = f"{_sanitize(zone)}|{_sanitize(part)} {mm:g}mm"
                plate_extras = {"zone": zone, "material": part,
                                "thickness_mm": float(mm),
                                "hidden": bool(getattr(info, "hidden", False))}
                mat_idx = builder.add_material(
                    plate_name, base_color=base_color, alpha_mode=alpha_mode,
                    double_sided=options.double_sided, extras=plate_extras)
                # 节点位置 = 板块中心（顶点改为局部坐标，世界坐标不变）：
                # 导出后每个板块节点落在自己的实际位置，而不是全部堆在原点。
                center = (pos_r.min(axis=0) + pos_r.max(axis=0)) * 0.5
                plate_m = np.eye(4, dtype=np.float32)
                plate_m[:3, 3] = center
                local_pos = np.ascontiguousarray(pos_r - center, dtype=np.float32)
                mesh_idx = builder.add_mesh(
                    plate_name, local_pos, nrm_r, idx, None, mat_idx,
                    extras=dict(plate_extras, triangle_count=int(tri_list.size)),
                    flip_winding=options.flip_winding)
                node = builder.add_node(plate_name, mesh=mesh_idx, matrix=plate_m)
                scene_children.append(node)
                bmin = np.minimum(bmin, pos_r.min(axis=0))
                bmax = np.maximum(bmax, pos_r.max(axis=0))
                report.meshes += 1
                total_tri += tri_list.size
                total_vert += pos_r.shape[0]

    report.triangles = total_tri
    report.vertices = total_vert
    report.textures = 0
    if np.isfinite(bmin).all():
        report.bounds_min = tuple(bmin.tolist())
        report.bounds_max = tuple(bmax.tolist())
    if progress_cb:
        progress_cb(95, "写入 GLB...")
    builder.finalize(output_path, scene_children=scene_children)
    report.nodes = len(builder.gltf.nodes)
    report.elapsed_seconds = time.time() - t0
    return report


# ────────────────────────────────────────────────────────────────────────────
# 工具
# ────────────────────────────────────────────────────────────────────────────

def _sanitize(name) -> str:
    s = str(name or "").strip().replace("/", "_").replace("\\", "_")
    return s[:120] or "mesh"


def _color_tuple(color, alpha: float) -> tuple:
    """厚度颜色 (r,g,b,a) → (r,g,b,alpha)；裁剪到 [0,1]。"""
    return (float(np.clip(color[0], 0.0, 1.0)),
            float(np.clip(color[1], 0.0, 1.0)),
            float(np.clip(color[2], 0.0, 1.0)),
            float(np.clip(alpha, 0.0, 1.0)))


def _apply_matrix(points: np.ndarray, matrix) -> np.ndarray:
    """把本地坐标经行主序矩阵变换到世界坐标。"""
    if matrix is None:
        return points
    m = np.asarray(matrix, dtype=np.float32)
    hom = np.hstack([points, np.ones((points.shape[0], 1), dtype=np.float32)])
    return (hom @ m.T)[:, :3]


def _apply_matrix3(normals: np.ndarray, matrix) -> np.ndarray:
    """法线经行主序矩阵的 3x3 旋转部分变换（刚体矩阵，忽略平移）。"""
    if matrix is None:
        return normals
    m = np.asarray(matrix, dtype=np.float32)[:3, :3]
    return normals @ m.T
