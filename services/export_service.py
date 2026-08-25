"""
export_service.py —— 舰船 3D 模型导出（GLB / glTF 2.0 Binary）。

渲染模型（船体 + 挂载）与装甲模型**分开导出**，各自生成独立 .glb 文件：

  - export_render_glb()  → 舰体分段 + 挂载实例（含挂点矩阵、贴图）
  - export_armor_glb()   → 装甲三角形汤（按 Zone → 部件 → 厚度分组，厚度着色）

导出数据一律取自查看器已加载的 ShipGeometry / ArmorScene，不重新解析
.geometry、不读 data/split、不反向读回 OpenGL 缓冲区，因此不影响查看器的
显示功能。导出在后台线程执行（只读几何对象，不触碰 Qt/OpenGL API）。

坐标约定（关键，保证不错位/不翻转，与查看器严格一致）：
  - .geometry 解析空间 = 游戏左手系（Z 朝向观察者）
  - 渲染空间 = 右手系 Y 向上（Z 镜像 negz = diag(1,1,-1,1)），与 glTF 同构
  - 顶点/法线经 models.geometry_transform.prepare_render_mesh() 统一变换到
    渲染空间（与渲染器共用同一函数 → 「导出的 = 看到的」）
  - 挂载几何保留本地坐标，model_matrix（渲染空间，行主序，world = m @ local）
    写入 node.matrix（glTF 列主序存储 = m.T.flatten()），与渲染器一致
  - 装甲沿用 ArmorScene.world_positions（舰船空间）再 negz 镜像
  - 全部材质 doubleSided=True：绕序不统一也不致背面剔除/面消失

贴图：DDS → RGBA → PNG 嵌入 GLB（BC1/BC2/BC3/BC4/BC5/BC7 + 未压缩）；
解码失败保留几何并记 warning。INDEXED 舰船首期嵌入原始 tiles 图集并记
warning（完整逐材质烘焙为后续任务，见 todo 规划）。
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
    Node, Scene, Skin,
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
#: 4x4 版镜像（矩阵共轭用：M_gltf = M4 @ M_game @ M4）
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


def dds_to_png(data: bytes, max_size: int = 4096) -> bytes | None:
    """DDS → PNG 字节（sRGB，行序保持与上传/采样一致）。失败返回 None。

    超长边降采样到 max_size 控制体积；0/负 = 不限制。
    """
    try:
        from PIL import Image
        rgba = dds_to_rgba(data)
        if rgba is None:
            return None
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
        #: mesh 键 -> skin index（蒙皮网格去重后复用 skin）
        self._mesh_skin_cache: dict[object, int] = {}

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

    def add_texture_from_dds(self, dds_bytes: bytes, label: str = "") -> int | None:
        """DDS → PNG → glTF 纹理（按 dds 字节对象去重）。解码失败返回 None。"""
        key = id(dds_bytes)
        cached = self._texture_cache.get(key)
        if cached is not None:
            return cached
        png = dds_to_png(dds_bytes, max_size=4096)
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
                     double_sided: bool = True, extras: dict | None = None) -> int:
        """材质（带去重缓存）。base_color 需可哈希（tuple）。"""
        key = (texture_idx, tuple(base_color), alpha_mode, double_sided)
        cached = self._material_cache.get(key)
        if cached is not None:
            return cached
        pbr = PbrMetallicRoughness(
            baseColorFactor=[float(x) for x in base_color],
            metallicFactor=0.0, roughnessFactor=1.0)
        if texture_idx is not None:
            pbr.baseColorTexture = TextureInfo(index=texture_idx)
        mat = Material(pbrMetallicRoughness=pbr, alphaMode=alpha_mode,
                       doubleSided=bool(double_sided), name=name)
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
                 joints0: np.ndarray | None = None,
                 weights0: np.ndarray | None = None) -> int:
        """加入一个网格，返回 mesh 索引。

        positions/normals/indices 必须已是渲染空间（右手系）数据。
        cache_key 非 None 时按 id 去重（挂载实例共享几何，只存一份）。

        flip_winding：glTF 默认 **CCW 为正面**。解析空间经负 Z 镜像（det=-1）转右手系
        会把绕序翻转为 CW（背面朝外，Blender 里看面朝向反了，实测 400 条船外射线
        首碰面法线全部朝内）。因此导出时统一翻转一次：交换三角形绕序 + 取反法线，
        使正面 CCW 朝外且法线与新绕序一致（法线·几何法线仍 >0，光照正确）。

        joints0/weights0：蒙皮网格的 (N,4) JOINTS_0（uint8）与 WEIGHTS_0（float32）。
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
        if joints0 is not None and weights0 is not None:
            if joints0.shape[0] == positions.shape[0] and weights0.shape[0] == positions.shape[0]:
                j_acc = self.add_accessor(np.asarray(joints0, dtype=np.uint8),
                                          "VEC4", _UNSIGNED_BYTE, _ARRAY_BUFFER)
                w_acc = self.add_accessor(np.asarray(weights0, dtype=np.float32),
                                          "VEC4", _FLOAT, _ARRAY_BUFFER)
                attrs.JOINTS_0 = j_acc
                attrs.WEIGHTS_0 = w_acc
        idx_acc = self.add_accessor(indices.astype(np.uint32), "SCALAR",
                                    _UNSIGNED_INT, _ELEMENT_ARRAY_BUFFER)
        prim = Primitive(attributes=attrs, indices=idx_acc, mode=_TRIANGLES)
        if material_idx is not None:
            prim.material = material_idx
        self.gltf.meshes.append(Mesh(primitives=[prim], name=name))
        idx = len(self.gltf.meshes) - 1
        if cache_key is not None:
            self._mesh_cache[cache_key] = idx
        return idx

    def add_node(self, name: str, mesh: int | None = None,
                 matrix: np.ndarray | None = None,
                 skin: int | None = None,
                 extras: dict | None = None) -> int:
        """加入一个节点，返回 node 索引。

        matrix：渲染空间行主序 4x4（world = m @ local）；glTF 列主序存储。
        skin：蒙皮索引（蒙皮网格的节点需引用）。
        """
        node = Node(name=name, mesh=mesh, skin=skin)
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

    def _skin_data(self, src):
        """从网格提取蒙皮数据 → (joints0, weights0, joints_matrices)。

        joints0：(N,4) uint8，索引指向 build_skin 生成的 joints 数组；
        weights0：(N,4) float32 归一化；joints_matrices：有效骨骼的 bind 矩阵（游戏空间）。
        非蒙皮网格返回 (None, None, [])。
        """
        if getattr(src, "bone_indices", None) is None or not getattr(src, "skin_bind", None):
            return None, None, []
        bind = list(src.skin_bind)
        slot_to_joint: dict = {}
        joints: list = []
        for i, m in enumerate(bind):
            if m is not None:
                slot_to_joint[i] = len(joints)
                joints.append(m)
        if not joints:
            return None, None, []
        slots = np.asarray(src.bone_indices, dtype=np.int64) // 3  # 调色板 slot
        n = len(bind)
        remap = np.zeros(n, dtype=np.int64)
        for si, ji in slot_to_joint.items():
            remap[si] = ji
        cl = np.clip(slots, 0, n - 1)
        joints0 = remap[cl].astype(np.uint8)
        weights0 = np.asarray(src.bone_weights, dtype=np.float32).copy()
        valid = (slots >= 0) & (slots < n) & \
            np.asarray([m is not None for m in bind], dtype=bool)[cl]
        weights0[~valid] = 0.0
        s = weights0.sum(axis=1, keepdims=True)
        s[s < 1e-6] = 1.0
        weights0 = weights0 / s
        return joints0, weights0, joints

    def build_skin(self, name: str, joints_matrices: list,
                   scene_children: list[int] | None = None,
                   pre_matrix: np.ndarray | None = None,
                   joint_parent: int | None = None) -> int:
        """创建 joint 节点 + 逆 bind accessor + glTF Skin，返回 skin 索引。

        joints_matrices：有效骨骼的 **游戏空间** bind (4,4) 列表。
        joint 节点矩阵 = M4 @ M @ M4（转 glTF 空间），逆 bind = 其逆；
        bind pose 下 jointGlobal × inverseBind = I → skin 恒等，网格保持烘焙位置，
        同时保留骨骼权重供重绑定/动画。

        pre_matrix：挂载蒙皮时传入挂载 model_matrix（渲染空间行主序）——
        网格顶点已烘焙到最终世界坐标，joint 也放到世界 bind（A @ M_gltf），保持同空间。
        joint_parent：把 joint 节点挂到该空物体骨骼下（层级组织）。
        scene_children：若提供且无 joint_parent，把 joint 节点追加为场景根。
        """
        joint_nodes: list[int] = []
        inv_binds: list[np.ndarray] = []
        for i, m in enumerate(joints_matrices):
            m_gltf = _MIRROR4 @ np.asarray(m, dtype=np.float32) @ _MIRROR4
            if pre_matrix is not None:
                m_gltf = np.asarray(pre_matrix, dtype=np.float32) @ m_gltf
            jn = self.add_node(name=f"{name}_bone{i}", matrix=m_gltf)
            joint_nodes.append(jn)
            inv_binds.append(np.linalg.inv(m_gltf.astype(np.float64)).astype(np.float32))
        if joint_parent is not None:
            self.add_children(joint_parent, joint_nodes)
        elif scene_children is not None:
            scene_children.extend(joint_nodes)
        inv_arr = np.ascontiguousarray(np.stack(inv_binds))  # (n,4,4) float32
        inv_acc = self.add_accessor(inv_arr, "MAT4", _FLOAT)
        sk = Skin(joints=joint_nodes, inverseBindMatrices=inv_acc,
                  skeleton=joint_nodes[0], name=name)
        self.gltf.skins.append(sk)
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
        "wows_export_version": 3,
    }
    # ── 层级：空物体骨骼（identity）组织父子关系；网格各自独立、烘焙到最终世界坐标 ──
    root_bone = builder.add_node(name=f"ship_{_sanitize(geometry.game_key)}")
    hull_bone = builder.add_node(name="Hull")
    mounts_bone = builder.add_node(name="Mounts")
    builder.add_children(root_bone, [hull_bone, mounts_bone])
    scene_children: list[int] = [root_bone]

    bmin = np.full(3, np.inf, dtype=np.float32)
    bmax = np.full(3, -np.inf, dtype=np.float32)
    fallback_tex = getattr(geometry, "texture_dds", None)

    def _add_solid(builder_, src, label, matrix=None, component="", parent_bone=None):
        """单个网格：变换 → 烘焙到最终世界坐标 → 材质 → 网格(+skin) → Shape 节点。"""
        nonlocal bmin, bmax, report
        if getattr(src, "is_wire", False):
            report.skipped_meshes += 1
            return False, None
        p, n, idx, uvs, _c = prepare_render_mesh(
            src.positions, src.normals, src.indices, None, getattr(src, "uvs", None))
        if p.shape[0] == 0 or idx.size == 0:
            report.skipped_meshes += 1
            return False, None
        # 烘焙挂点矩阵到顶点 → 最终世界坐标（网格独立，空物体骨骼不再承担坐标变换）
        if matrix is not None:
            p = _apply_matrix(p, matrix).astype(np.float32)
            n = _apply_matrix3(n, matrix).astype(np.float32)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            ln[ln < 1e-8] = 1.0
            n = (n / ln).astype(np.float32)
        tex = getattr(src, "texture_dds", None) or fallback_tex
        tex_idx = None
        if options.embed_textures and tex:
            tex_idx = builder_.add_texture_from_dds(tex, label)
            if tex_idx is None:
                report.skipped_textures += 1
        mat_idx = builder_.add_material(
            label, base_color=(1.0, 1.0, 1.0, 1.0), texture_idx=tex_idx,
            double_sided=options.double_sided,
            extras={"component": component,
                    "texture_path": getattr(src, "texture_path", "")})
        joints0, weights0, joints_mat = builder_._skin_data(src)
        mesh_idx = builder_.add_mesh(f"{label}_Shape", p, n, idx, uvs, mat_idx,
                                     extras={"component": component},
                                     flip_winding=options.flip_winding,
                                     joints0=joints0, weights0=weights0)
        # 蒙皮：joint 放世界 bind（挂载乘矩阵），挂到所属空物体骨骼下
        skin_idx = None
        if joints0 is not None:
            skin_idx = builder_.build_skin(label, joints_mat, pre_matrix=matrix,
                                           joint_parent=parent_bone)
        node = builder_.add_node(f"{label}_Shape", mesh=mesh_idx, skin=skin_idx)
        if parent_bone is not None:
            builder_.add_children(parent_bone, [node])
        else:
            scene_children.append(node)
        report.meshes += 1
        report.triangles += int(idx.size) // 3
        report.vertices += int(p.shape[0])
        bmin = np.minimum(bmin, p.min(axis=0))
        bmax = np.maximum(bmax, p.max(axis=0))
        return True, (p.min(axis=0), p.max(axis=0))

    # ── 舰体分段（Shape 直接挂 Hull 骨骼；crack 损伤网格挂 Crack 骨骼）──
    crack_bone = builder.add_node(name="Crack")
    builder.add_children(root_bone, [crack_bone])
    n_hull = len(geometry.hull_meshes)
    for i, hm in enumerate(geometry.hull_meshes):
        _check_cancel(cancel_event)
        if progress_cb:
            progress_cb(5 + 60 * i / max(1, n_hull), f"导出舰体 {i + 1}/{n_hull}")
        inst = getattr(hm, "instance_matrices", None) or []
        if getattr(hm, "is_crack", False):
            _add_solid(builder, hm, f"crack_{_sanitize(hm.name)}", component="hull",
                       parent_bone=crack_bone)
        elif inst:
            # 多节点实例化：一份原始几何 → 导出时按每个节点矩阵各烘焙一份（各处实例）
            for _k, _m in enumerate(inst):
                _add_solid(builder, hm, f"hull_{_sanitize(hm.name)}_{_k}",
                           matrix=_m, component="hull", parent_bone=hull_bone)
        else:
            _add_solid(builder, hm, f"hull_{_sanitize(hm.name)}", component="hull",
                       parent_bone=hull_bone)

    # ── 挂载（每个挂载一个空物体骨骼，Shape 挂其下，矩阵烘焙进顶点；crack 挂 Crack 骨骼）──
    mounts = geometry.mounts if options.export_mounts else []
    n_mounts = len(mounts)
    for i, mm in enumerate(mounts):
        _check_cancel(cancel_event)
        if progress_cb:
            progress_cb(65 + 30 * i / max(1, n_mounts), f"导出挂载 {i + 1}/{n_mounts}")
        inst_mm = getattr(mm, "instance_matrices", None) or []
        if getattr(mm, "is_crack", False):
            _add_solid(builder, mm, f"crack_{_sanitize(mm.name)}",
                       matrix=mm.model_matrix, component=getattr(mm, "component", ""),
                       parent_bone=crack_bone)
            continue
        if inst_mm:
            # 实例化挂载：一份几何 → 按各节点矩阵各烘焙一份（省顶点内存）
            for _k, _m in enumerate(inst_mm):
                _add_solid(builder, mm, f"mount_{_sanitize(mm.name)}_{_k}",
                           matrix=_m, component=getattr(mm, "component", ""),
                           parent_bone=mounts_bone)
        else:
            mount_bone = builder.add_node(f"mount_{_sanitize(mm.name)}")
            builder.add_children(mounts_bone, [mount_bone])
            _add_solid(builder, mm, f"mount_{_sanitize(mm.name)}",
                       matrix=mm.model_matrix, component=getattr(mm, "component", ""),
                       parent_bone=mount_bone)

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
                mesh_idx = builder.add_mesh(
                    plate_name, pos_r, nrm_r, idx, None, mat_idx,
                    extras=dict(plate_extras, triangle_count=int(tri_list.size)),
                    flip_winding=options.flip_winding)
                node = builder.add_node(plate_name, mesh=mesh_idx)
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
