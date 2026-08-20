"""
geometry_renderer.py —— 舰船 3D 渲染引擎（QOpenGLWidget + PyOpenGL）。

直接在 QOpenGLWidget 的 GL 上下文内调用 OpenGL（无需 ModernGL 独立上下文层）。

- 船体：可选漫反射贴图（DXT1/BC 压缩纹理直接上传 GPU 采样）+ 光照
- 装甲：半透明厚度着色（无贴图）
- 单个 GLSL 程序（模式 0=光照实体 1=线框 2=无光照实体）
- 轨道相机交互 + 自动取景（按 2D 投影精确框选舰船）
"""

from __future__ import annotations

import ctypes
import time

import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QSurfaceFormat, QMouseEvent, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from OpenGL import GL

# 关闭 PyOpenGL 每次调用自动抛 GL 错误异常：避免 paintGL 中途因单个 GL 错误
# 中断导致整帧渲染缺失。错误改为静默/手动检查。
GL.ERROR_CHECKING = False

from models.camera import OrbitCamera

# ── 装甲展示重构常量（参考 landaire/wows-toolkit）─────────────────────────
PLATE_EDGE_COLOR = (0.0, 0.0, 0.0, 0.9)       # 板块边界描边色
HIGHLIGHT_HOVER = (0.0, 0.9, 1.0, 0.5)        # 悬停高亮（青）
HIGHLIGHT_SELECT = (1.0, 0.6, 0.1, 0.6)       # 选中高亮（橙）

# ── OpenGL 3.3 Core 表面格式（在首个 QOpenGLWidget 创建前生效）──────────────
_gl_format_done = False


def _ensure_gl_format():
    global _gl_format_done
    if _gl_format_done:
        return
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    _gl_format_done = True


_ensure_gl_format()

VERT_SRC = """
#version 330 core
in vec3 in_position;
in vec3 in_normal;
in vec2 in_uv;
in vec4 in_color;
uniform mat4 u_mvp;
uniform mat3 u_normal_mat;
out vec4 v_color;
out vec3 v_normal;
out vec2 v_uv;
void main() {
    gl_Position = u_mvp * vec4(in_position, 1.0);
    v_normal = u_normal_mat * in_normal;
    v_color = in_color;
    v_uv = in_uv;
}
"""

FRAG_SRC = """
#version 330 core
in vec4 v_color;
in vec3 v_normal;
in vec2 v_uv;
uniform int u_mode;        // 0=光照实体 1=线框 2=无光照实体 3=INDEXED分块
uniform float u_opacity;
uniform vec3 u_light_dir;
uniform vec3 u_ambient;
uniform sampler2D u_tex;
uniform int u_has_tex;
// INDEXED 分块涂装（ship_material_indexed.fx，参考 uncode_assets/shaders.py 对 fxo 的逆向）
uniform sampler2D u_matid_tex;   // materialIdMap（R=材质ID）
uniform sampler2D u_tiles_tex;   // albedoArray（分块图集）
uniform sampler2D u_art_tex;     // artMap（艺术涂装叠加层）
uniform vec4 u_tile_idx[196];    // tileIdxMatIdArr：每材质ID (albedo/normal/MG/camo tile)
uniform vec2 u_grid;             // offsetScaleMatIdArr scale（图集网格 列,行）
uniform vec2 u_grid_offset;      // offsetScaleMatIdArr offset
uniform float u_art_strength;    // artStrengthMatIdArr 基底强度
out vec4 fragColor;
void main() {
    vec4 base = v_color;
    bool is_tex = (u_has_tex == 1);
    if (is_tex) {
        base = texture(u_tex, v_uv);
    }
    if (u_mode == 3) {
        // INDEXED：materialIdMap → tileIdxMatIdArr → albedoArray 分块采样
        float matIdF = texture(u_matid_tex, v_uv).r * 255.0;
        int matId = int(clamp(round(matIdF), 0.0, 195.0));
        vec4 tile = u_tile_idx[matId];
        vec2 grid = max(u_grid, vec2(1.0));
        vec2 tileUv = fract(v_uv * grid - u_grid_offset);
        float albedoIdx = tile.x;
        float tx = mod(floor(albedoIdx), grid.x);
        float ty = floor(floor(albedoIdx) / grid.x);
        vec2 tuv = (vec2(tx, ty) + clamp(tileUv, vec2(0.0), vec2(1.0))) / grid;
        vec3 albedo = texture(u_tiles_tex, tuv).rgb;
        vec3 art = texture(u_art_tex, v_uv).rgb;
        vec3 rgb = albedo + art * u_art_strength;
        rgb = pow(rgb, vec3(1.0 / 2.2));
        fragColor = vec4(rgb, 1.0);
        return;
    }
    if (u_mode == 1) {
        fragColor = vec4(base.rgb, 1.0);
        return;
    }
    vec3 n = normalize(v_normal);
    float diff = max(dot(n, -u_light_dir), 0.0);
    float hl = diff * 0.5 + 0.5;   // half-Lambert：远侧永不黑
    vec3 lit = u_ambient + (1.0 - u_ambient) * hl;
    vec3 rgb2 = (u_mode == 2) ? base.rgb : base.rgb * lit;
    if (is_tex) {
        // 贴图已被硬件解码到线性空间，这里仅做线性→sRGB 编码输出
        rgb2 = pow(rgb2, vec3(1.0 / 2.2));
    }
    fragColor = vec4(rgb2, base.a * u_opacity);
}
"""

#: 每顶点 12 个 float：position(3) + normal(3) + uv(2) + color(4)
_VERTEX_STRIDE = 48
_POS_OFFSET = 0
_NRM_OFFSET = 12
_UV_OFFSET = 24
_COL_OFFSET = 32

_UNIFORMS = ("u_mvp", "u_normal_mat", "u_mode", "u_opacity", "u_light_dir", "u_ambient",
             "u_tex", "u_has_tex", "u_matid_tex", "u_tiles_tex", "u_art_tex",
             "u_tile_idx", "u_grid", "u_grid_offset", "u_art_strength")


def _compile_shader(shader_type: int, source: str) -> int:
    sh = GL.glCreateShader(shader_type)
    GL.glShaderSource(sh, source)
    GL.glCompileShader(sh)
    if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
        log = GL.glGetShaderInfoLog(sh)
        GL.glDeleteShader(sh)
        raise RuntimeError(f"Shader 编译失败: {log}")
    return sh


def _link_program(vs_src: str, fs_src: str) -> int:
    prog = GL.glCreateProgram()
    vs = _compile_shader(GL.GL_VERTEX_SHADER, vs_src)
    fs = _compile_shader(GL.GL_FRAGMENT_SHADER, fs_src)
    GL.glAttachShader(prog, vs)
    GL.glAttachShader(prog, fs)
    # 显式绑定顶点属性位置（与 GpuMesh 的 VAO 布局一致），避免链接器错位
    GL.glBindAttribLocation(prog, 0, "in_position")
    GL.glBindAttribLocation(prog, 1, "in_normal")
    GL.glBindAttribLocation(prog, 2, "in_uv")
    GL.glBindAttribLocation(prog, 3, "in_color")
    GL.glLinkProgram(prog)
    GL.glDeleteShader(vs)
    GL.glDeleteShader(fs)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        log = GL.glGetProgramInfoLog(prog)
        GL.glDeleteProgram(prog)
        raise RuntimeError(f"Program 链接失败: {log}")
    return prog


def _gl_off(offset: int):
    return ctypes.c_void_p(offset)


def _upload_texture(dds_bytes: bytes, srgb: bool = True, label: str = "") -> int:
    """把 DDS 字节上传为 GL 压缩/未压缩纹理，返回纹理 id（失败返回 0）。

    srgb=False：materialIdMap 等数据纹理（存储 0-255 材质 ID）用非 sRGB 格式，
    避免被硬件 sRGB 解码产生 gamma 失真。
    """
    from models.dds_reader import parse_dds, GL_SRGB_RGBA8
    try:
        dds = parse_dds(dds_bytes)
    except Exception as exc:  # noqa: BLE001
        try:
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 贴图解析失败{(' ' + label) if label else ''}: {exc}")
        except Exception:  # noqa: BLE001
            pass
        return 0
    tex = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex)

    if dds.bc_kind and dds.internal_format:
        # 压缩纹理：用 sRGB 内部格式上传，让 GPU 硬件逐 texel 解码（wows-toolkit 方案）
        fmt = dds.internal_format_srgb if srgb else dds.internal_format
        n_mips = len(dds.mips)
        for i, mip in enumerate(dds.mips):
            w = max(dds.width >> i, 1)
            h = max(dds.height >> i, 1)
            GL.glCompressedTexImage2D(GL.GL_TEXTURE_2D, i, fmt, w, h, 0, mip)
        if n_mips <= 1:
            # 仅 level 0：让 GPU 生成 mipmap
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    else:
        # 未压缩 RGBA（BGR 字节序交换为 RGB，sRGB 内部格式硬件解码）
        if not dds.mips:
            GL.glDeleteTextures([tex])
            return 0
        rgba = np.frombuffer(dds.mips[0], dtype=np.uint8).reshape(dds.height, dds.width, dds.rgba_bpp)
        if dds.rgba_bpp == 4:
            rgb = rgba[:, :, [2, 1, 0, 3]].copy()
        else:
            rgb = rgba[:, :, [2, 1, 0]].copy()
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL_SRGB_RGBA8 if srgb else GL.GL_RGBA8,
                        dds.width, dds.height, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, np.ascontiguousarray(rgb))
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)

    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return tex


class GpuMesh:
    """上传到 GPU 的网格（VAO/VBO/IBO，可选贴图 + 模型矩阵 + 归属组件）。"""

    def __init__(self, name: str, positions: np.ndarray, normals: np.ndarray,
                 uvs: np.ndarray | None, colors: np.ndarray, indices: np.ndarray,
                 kind: str = "hull", texture_dds: bytes | None = None,
                 model_matrix: np.ndarray | None = None,
                 component: str | None = None,
                 armor_types: frozenset | None = None,
                 tech_family: str = "pbs",
                 material_textures: dict | None = None,
                 indexed_params: dict | None = None,
                 is_wire: bool = False):
        self.name = name
        self.kind = kind
        self.is_wire = is_wire
        #: 模型矩阵（行主序 4x4，渲染空间）；None = 恒等（舰体已在世界坐标）
        self.model_matrix = None if model_matrix is None else np.ascontiguousarray(model_matrix, dtype=np.float32)
        #: 装甲归属分类（kind='armor' 时用于按归属过滤显示）
        self.component = component
        #: 装甲类型（ArmorConstants.getArmorType 归属类型集合），用于类型过滤
        self.armor_types = armor_types or frozenset()
        #: shader 技术族（pbs/indexed/other）—— INDEXED 走分块渲染
        self.tech_family = tech_family
        #: INDEXED 分块参数（tileIdxMatIdArr 数组、网格等）
        self.indexed_params = indexed_params
        n = positions.shape[0]
        vdata = np.empty((n, 12), dtype=np.float32)
        vdata[:, 0:3] = positions
        vdata[:, 3:6] = normals
        if uvs is not None and uvs.shape[0] == n:
            vdata[:, 6:8] = uvs
        else:
            vdata[:, 6:8] = 0.0
        vdata[:, 8:12] = colors
        self._vdata = np.ascontiguousarray(vdata)
        self._indices = np.ascontiguousarray(indices, dtype=np.uint32)
        self.index_count = int(indices.size)

        self._vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, self._vdata.nbytes, self._vdata, GL.GL_STATIC_DRAW)

        self._ibo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._ibo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, self._indices.nbytes, self._indices, GL.GL_STATIC_DRAW)

        self._vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_POS_OFFSET))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_NRM_OFFSET))
        GL.glEnableVertexAttribArray(2)
        GL.glVertexAttribPointer(2, 2, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_UV_OFFSET))
        GL.glEnableVertexAttribArray(3)
        GL.glVertexAttribPointer(3, 4, GL.GL_FLOAT, GL.GL_FALSE, _VERTEX_STRIDE, _gl_off(_COL_OFFSET))
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._ibo)
        GL.glBindVertexArray(0)

        self._texture = 0
        self.has_tex = False
        if texture_dds:
            tid = _upload_texture(texture_dds, label=self.name)
            if tid:
                self._texture = tid
                self.has_tex = True

        #: 额外贴图（INDEXED：materialIdMap/albedoArray/artMap 等）{键: GL 纹理 id}
        self._extra_tex: dict = {}
        if material_textures:
            for key, (_path, tbytes) in material_textures.items():
                # materialIdMap 是数据纹理（材质 ID 0-255），用非 sRGB 避免 gamma 失真
                tid = _upload_texture(tbytes, srgb=(key != "materialIdMap"), label=_path or key)
                if tid:
                    self._extra_tex[key] = tid

        self._line_ibo = None
        self._line_count = 0

    def _build_lines(self):
        if self._line_ibo is not None:
            return
        tri = self._indices.reshape(-1, 3)
        lines = np.empty((tri.shape[0], 6), dtype=np.uint32)
        lines[:, 0:2] = tri[:, [0, 1]]
        lines[:, 2:4] = tri[:, [1, 2]]
        lines[:, 4:6] = tri[:, [2, 0]]
        self._line_ibo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._line_ibo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, lines.nbytes, np.ascontiguousarray(lines), GL.GL_STATIC_DRAW)
        self._line_count = int(lines.size)

    def render(self, mode: int, line: bool = False):
        ibo = self._line_ibo if line else self._ibo
        count = self._line_count if line else self.index_count
        if count == 0:
            return
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ibo)
        GL.glDrawElements(mode, count, GL.GL_UNSIGNED_INT, None)
        GL.glBindVertexArray(0)

    def update_indices(self, indices: np.ndarray):
        """动态替换索引缓冲（可见性过滤/高亮重建，不重建 VBO/VAO）。"""
        idx = np.ascontiguousarray(indices, dtype=np.uint32)
        self._indices = idx
        self.index_count = int(idx.size)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, self._ibo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL.GL_DYNAMIC_DRAW)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, 0)
        # 索引变化后线框 IBO 失效
        if self._line_ibo is not None:
            GL.glDeleteBuffers(1, [self._line_ibo])
            self._line_ibo = None
            self._line_count = 0

    def release(self):
        try:
            GL.glDeleteVertexArrays(1, [self._vao])
            GL.glDeleteBuffers(2, [self._vbo, self._ibo])
            if self._line_ibo is not None:
                GL.glDeleteBuffers(1, [self._line_ibo])
            if self._texture:
                GL.glDeleteTextures([self._texture])
                self._texture = 0
            if self._extra_tex:
                GL.glDeleteTextures(list(self._extra_tex.values()))
                self._extra_tex = {}
        except Exception:  # noqa: BLE001
            pass


class GeometryViewport(QOpenGLWidget):
    """3D 视口（PyOpenGL）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._camera = OrbitCamera()
        self._program = 0
        self._uniforms = {}
        self._meshes: list[GpuMesh] = []
        self._mesh_specs: list[dict] = []
        self._scene_bounds = None
        self._show_hull = True
        self._show_mounts = True
        self._show_armor = True
        self._wireframe = False
        #: 装甲归属过滤：None/空 = 全部显示；否则仅显示集合内的 component
        self._armor_components: set | None = None
        #: 装甲类型过滤（ArmorConstants 归属类型）：None/空 = 全部
        self._armor_types: set | None = None
        self._auto_frame = True
        self._needs_rebuild = False
        self._last_pos: QPoint | None = None
        # ── 装甲场景（重构后：世界空间三角形汤聚合） ──
        self._armor_scene = None              # ArmorScene | None
        self._armor_gpu: GpuMesh | None = None     # 聚合装甲网格（渲染空间）
        self._edge_gpu: GpuMesh | None = None      # 板块边界线
        self._hl_gpu: GpuMesh | None = None        # 高亮覆盖网格（按需重建）
        self._hl_color: tuple = HIGHLIGHT_HOVER
        self._visible_tris: np.ndarray | None = None   # (T,) bool，None=全可见
        self._armor_opacity: float = 1.0
        self._show_edges: bool = True
        #: GL 上下文是否已就绪（initializeGL 后）；未就绪的重建操作延迟到 paintGL
        self._gl_ready: bool = False
        self._vis_pending: bool = False
        self._hl_pending: bool = False
        self._hover_tri: int | None = None
        self._selected_plate: tuple | None = None
        self._last_pick_time: float = 0.0
        self._press_pos: QPoint | None = None
        #: 交互回调（viewer 设置）：on_hover(tri_idx|None, QPoint全局坐标)
        self.on_hover = None
        #: on_select(plate_key|None)
        self.on_select = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(480, 360)

    # ── 场景设置 ─────────────────────────────────────────

    def set_scene(self, ship_geometry, show_hull: bool = True, show_armor: bool = True,
                  armor_scene=None):
        """加载舰船场景：舰体分段 + 挂载模型（各自独立贴图/变换）+ 装甲。

        armor_scene：ArmorScene 聚合场景（重构后装甲渲染/拾取数据源）。
        传入时装甲改由场景渲染（跳过逐 ArmorMesh 的 spec 路径）。
        """
        specs = []
        if ship_geometry is not None:
            tex = ship_geometry.texture_dds if ship_geometry.texture_dds else None
            white = (1.0, 1.0, 1.0, 1.0)
            for hm in ship_geometry.hull_meshes:
                # 按材质拆分的分段使用自己的贴图（如 DeckHouse），否则用舰体默认贴图
                hm_tex = getattr(hm, "texture_dds", None) or tex
                specs.append({
                    "name": hm.name, "kind": "hull",
                    "positions": hm.positions, "normals": hm.normals, "uvs": hm.uvs,
                    "colors": np.full((hm.positions.shape[0], 4), white, dtype=np.float32),
                    "indices": hm.indices, "texture": hm_tex,
                    "tech_family": getattr(hm, "tech_family", "pbs"),
                    "material_textures": getattr(hm, "material_textures", None),
                    "indexed_params": getattr(hm, "indexed_params", None),
                    "is_wire": getattr(hm, "is_wire", False),
                })
            for mm in ship_geometry.mounts:
                specs.append({
                    "name": mm.name, "kind": "mount",
                    "positions": mm.positions, "normals": mm.normals, "uvs": mm.uvs,
                    "colors": np.full((mm.positions.shape[0], 4), white, dtype=np.float32),
                    "indices": mm.indices,
                    "texture": mm.texture_dds if mm.texture_dds else tex,
                    "model": mm.model_matrix,
                    "is_wire": getattr(mm, "is_wire", False),
                })
            if armor_scene is None:
                # 旧路径：逐 ArmorMesh spec（无聚合场景时的兼容渲染）
                for am in ship_geometry.armor_meshes:
                    atypes = frozenset()
                    from models.collision_materials import get_armor_types
                    for tri in am.triangles:
                        atypes |= get_armor_types(tri.material_name)
                    specs.append({
                        "name": am.name, "kind": "armor",
                        "positions": am.positions, "normals": am.normals, "uvs": None,
                        "colors": am.colors, "indices": am.indices, "texture": None,
                        "model": am.model_matrix, "component": am.component,
                        "armor_types": atypes,
                    })
            if ship_geometry.bounds_min is not None:
                self._scene_bounds = (ship_geometry.bounds_center, ship_geometry.bounds_size)
        self._mesh_specs = specs
        self._armor_scene = armor_scene
        self._visible_tris = None
        self._hover_tri = None
        self._selected_plate = None
        self._show_hull = show_hull
        self._show_armor = show_armor
        self._auto_frame = True
        # GL 调用必须在上下文激活时执行（initializeGL/paintGL 内），这里只登记重建标记
        self._needs_rebuild = True
        self.update()

    def _build_meshes(self):
        for m in self._meshes:
            m.release()
        self._meshes = []
        for spec in self._mesh_specs:
            pos0 = spec["positions"]
            n0 = spec["normals"]
            idx = spec["indices"]
            colors0 = spec["colors"]
            uvs0 = spec.get("uvs")
            # ── 法线朝向修正 ─────────────────────────────
            # 顶点做 Z 镜像(negz, det=-1)转右手系会翻转三角形绕序（几何法线方向反），
            # 法线必须按各 mesh 实际绕序抵消：Korabli 数据绕序不统一（约一半模型
            # 外表面是另一绕序），统一翻转会让另一半内外面反。
            # 检测原始坐标系下 法线·几何叉积 的一致性：>0.5 表示绕序=外表面，
            # 渲染后需用 -S 翻转法线；否则用 S。
            flip = np.array([1.0, 1.0, -1.0], dtype=np.float32)
            if idx is not None and idx.size >= 3 and pos0.shape[0] > 0 \
                    and n0 is not None and n0.shape[0] == pos0.shape[0]:
                try:
                    tri = idx.reshape(-1, 3)
                    v0 = pos0[tri[:, 0]]; v1 = pos0[tri[:, 1]]; v2 = pos0[tri[:, 2]]
                    g = np.cross(v1 - v0, v2 - v0)
                    gn = np.linalg.norm(g, axis=1)
                    gn[gn < 1e-8] = 1.0
                    g = g / gn[:, None]
                    nv = n0[tri[:, 0]]
                    c = float(((nv * g).sum(1) > 0).mean())
                    if c > 0.5:
                        flip = np.array([-1.0, -1.0, 1.0], dtype=np.float32)
                    # 绕序混合的 prim（c 接近 0.5，如部分防空炮 TurretShape）：单一 flip
                    # 无法统一 → 逐三角形拆分对齐（法线与绕序相反的三角形复制顶点并翻转法线）
                    elif 0.35 <= c <= 0.65:
                        bad = (nv * g).sum(1) < 0
                        if bad.any() and not bad.all():
                            btri = tri[bad]
                            nb = btri.shape[0]
                            src = btri.ravel()   # 原顶点索引
                            extra_pos = pos0[src]
                            extra_n = -n0[src]
                            extra_idx = (np.arange(nb * 3).reshape(-1, 3)
                                         + len(pos0)).astype(np.uint32)
                            new_idx = idx.copy()
                            bad_flat = np.flatnonzero(bad)
                            for j, t in enumerate(bad_flat):
                                new_idx[t * 3:(t + 1) * 3] = extra_idx[j]
                            n_old = len(pos0)
                            pos0 = np.vstack([pos0, extra_pos])
                            n0 = np.vstack([n0, extra_n])
                            # 颜色 / UV 随拆分的顶点同步扩展
                            if colors0 is not None and colors0.shape[0] == n_old:
                                colors0 = np.vstack([colors0, colors0[src]])
                            if uvs0 is not None and uvs0.shape[0] == n_old:
                                uvs0 = np.vstack([uvs0, uvs0[src]])
                            idx = new_idx
                            # 对齐后法线=绕序方向，渲染镜像需用 -S 抵消
                            flip = np.array([-1.0, -1.0, 1.0], dtype=np.float32)
                except Exception:  # noqa: BLE001
                    pass
            # ⚠️ 逐三角形「质心向外」定向已移除（2026-08-19）：当初为修甲板面加，
            # 但甲板缺失的真因是「长边剔除」误删（已修），并非面朝向错误；
            # 该逻辑复制顶点翻转法线会破坏平滑着色，且文件法线(u8/255*2-1)已正确。
            # ─────────────────────────────────────────────
            p = np.ascontiguousarray(pos0 * np.array([1.0, 1.0, -1.0], dtype=np.float32))
            n = np.ascontiguousarray(n0 * flip)
            mesh = GpuMesh(
                name=spec["name"], kind=spec["kind"],
                positions=p, normals=n, uvs=uvs0,
                colors=np.ascontiguousarray(colors0, dtype=np.float32),
                indices=np.ascontiguousarray(idx, dtype=np.uint32),
                texture_dds=spec.get("texture"),
                model_matrix=spec.get("model"),
                component=spec.get("component"),
                armor_types=spec.get("armor_types"),
                tech_family=spec.get("tech_family", "pbs"),
                material_textures=spec.get("material_textures"),
                indexed_params=spec.get("indexed_params"),
                is_wire=spec.get("is_wire", False),
            )
            self._meshes.append(mesh)

        # ── 装甲场景聚合网格（重构后路径） ──
        self._release_armor_gpu()
        if self._armor_scene is not None and self._armor_scene.tri_count:
            self._build_armor_gpu()

    def _build_armor_gpu(self):
        """由 ArmorScene 构建聚合装甲网格 + 边界线网格（渲染空间：Z 镜像）。"""
        sc = self._armor_scene
        # 渲染空间：世界坐标 Z 取反（与 _build_meshes 的镜像一致）
        mirror = np.array([1.0, 1.0, -1.0], dtype=np.float32)
        pos = np.ascontiguousarray(sc.world_positions * mirror)
        # 法线：Z 镜像后需翻转 Z 分量（位置镜像 det=-1）
        nrm = np.ascontiguousarray(sc.world_normals * mirror)
        col = np.ascontiguousarray(sc.colors, dtype=np.float32)
        idx = np.arange(sc.tri_count * 3, dtype=np.uint32)
        self._armor_gpu = GpuMesh(
            name="armor_scene", kind="armor_scene",
            positions=pos, normals=nrm, uvs=None, colors=col, indices=idx,
        )
        # 边界线：端点对 → 渲染空间坐标，索引为顺序对
        if sc.edge_positions.shape[0]:
            epos = np.ascontiguousarray(sc.edge_positions * mirror)
            enrm = np.zeros_like(epos)
            ecol = np.full((epos.shape[0], 4), PLATE_EDGE_COLOR, dtype=np.float32)
            eidx = np.arange(epos.shape[0], dtype=np.uint32)
            self._edge_gpu = GpuMesh(
                name="armor_edges", kind="armor_edge",
                positions=epos, normals=enrm, uvs=None, colors=ecol, indices=eidx,
            )

    def _release_armor_gpu(self):
        for attr in ("_armor_gpu", "_edge_gpu", "_hl_gpu"):
            m = getattr(self, attr)
            if m is not None:
                m.release()
                setattr(self, attr, None)

    def clear_scene(self):
        self._mesh_specs = []
        self._scene_bounds = None
        self._armor_scene = None
        self._needs_rebuild = True
        self.update()

    # ── 显示选项 ─────────────────────────────────────────

    def set_view_options(self, show_hull=None, show_armor=None, wireframe=None,
                         show_mounts=None, armor_components=None, armor_types=None):
        if show_hull is not None:
            self._show_hull = bool(show_hull)
        if show_armor is not None:
            self._show_armor = bool(show_armor)
            # 船体/装甲互斥：装甲开启时隐藏船体与挂载；关闭时恢复船体/挂载
            # （仅当未同时显式设置 show_hull 时恢复，避免覆盖调用方意图）
            if self._show_armor:
                self._show_hull = False
                self._show_mounts = False
            elif show_hull is None:
                self._show_hull = True
                self._show_mounts = True
        if show_mounts is not None:
            self._show_mounts = bool(show_mounts)
        if wireframe is not None:
            self._wireframe = bool(wireframe)
        if armor_components is not None:
            # None = 全部；否则为可见归属集合
            self._armor_components = set(armor_components) if armor_components else None
        if armor_types is not None:
            self._armor_types = set(armor_types) if armor_types else None
        self.update()

    # ── 装甲场景显示控制（重构后） ─────────────────────

    def set_armor_display(self, opacity=None, show_edges=None):
        """装甲显示选项：不透明度 / 板块描边。"""
        if opacity is not None:
            self._armor_opacity = float(np.clip(opacity, 0.05, 1.0))
        if show_edges is not None:
            self._show_edges = bool(show_edges)
        self.update()

    def set_visible_tris(self, visible_tris):
        """设置装甲三角形可见掩码（(T,) bool；None=全部可见）。"""
        self._visible_tris = visible_tris
        if not self._run_gl(self._apply_visibility):
            self._vis_pending = True
        self.update()

    def select_plate(self, plate_key):
        """选中板块（plate_key=(zone, mat, tenths)；None=取消），重建高亮。"""
        self._selected_plate = plate_key
        self._hl_color = HIGHLIGHT_SELECT if plate_key is not None else HIGHLIGHT_HOVER
        if not self._run_gl(self._rebuild_highlight):
            self._hl_pending = True
        self.update()

    def _run_gl(self, fn):
        """在 GL 上下文内执行 GL 依赖的重建操作。

        GL 未就绪（initializeGL 前）返回 False，由调用方置 pending 标记，
        在 paintGL 首帧补做；避免在上下文外上传缓冲产生未定义内容。
        """
        if not self._gl_ready:
            return False
        self.makeCurrent()
        try:
            fn()
        finally:
            self.doneCurrent()
        return True

    def _flush_pending_gl(self):
        """在 paintGL/initializeGL 内补做上下文外登记的重建操作。"""
        if self._vis_pending:
            self._apply_visibility()
            self._vis_pending = False
        if self._hl_pending:
            self._rebuild_highlight()
            self._hl_pending = False

    def _apply_visibility(self):
        """按可见掩码重建装甲/边界线索引缓冲。"""
        if self._armor_gpu is None or self._armor_scene is None:
            return
        sc = self._armor_scene
        vis = self._visible_tris
        if vis is None:
            idx = np.arange(sc.tri_count * 3, dtype=np.uint32)
        else:
            idx = (np.nonzero(vis)[0][:, None] * 3
                   + np.arange(3, dtype=np.uint32)).ravel().astype(np.uint32)
        self._armor_gpu.update_indices(idx)
        # 边界线：任一侧三角形可见即显示
        if self._edge_gpu is not None and sc.edge_positions.shape[0]:
            if vis is None:
                eidx = np.arange(sc.edge_positions.shape[0], dtype=np.uint32)
            else:
                t1, t2 = sc.edge_tris[:, 0], sc.edge_tris[:, 1]
                keep = np.zeros(sc.edge_tris.shape[0], dtype=bool)
                k1 = t1 >= 0
                k2 = t2 >= 0
                keep[k1] |= vis[t1[k1]]
                keep[k2] |= vis[t2[k2]]
                eidx = (np.nonzero(keep)[0][:, None] * 2
                        + np.arange(2, dtype=np.uint32)).ravel().astype(np.uint32)
            self._edge_gpu.update_indices(eidx)

    def _rebuild_highlight(self):
        """按选中板块重建高亮覆盖网格（沿法线微偏移防 z-fighting）。"""
        if self._hl_gpu is not None:
            self._hl_gpu.release()
            self._hl_gpu = None
        if self._selected_plate is None or self._armor_scene is None \
                or self._armor_gpu is None:
            return
        tris = self._armor_scene.tris_for_plate(self._selected_plate)
        if not len(tris):
            return
        tris = np.asarray(tris, dtype=np.int64)
        sc = self._armor_scene
        mirror = np.array([1.0, 1.0, -1.0], dtype=np.float32)
        p = sc.world_positions[tris[:, None] * 3 + np.arange(3)].reshape(-1, 3)
        n = sc.world_normals[tris[:, None] * 3 + np.arange(3)].reshape(-1, 3)
        pos = np.ascontiguousarray((p + n * 0.02) * mirror)
        nrm = np.ascontiguousarray(n * mirror)
        col = np.full((pos.shape[0], 4), self._hl_color, dtype=np.float32)
        idx = np.arange(pos.shape[0], dtype=np.uint32)
        self._hl_gpu = GpuMesh(
            name="armor_highlight", kind="armor_hl",
            positions=pos, normals=nrm, uvs=None, colors=col, indices=idx,
        )

    def pick_at(self, x: int, y: int):
        """屏幕坐标 → 射线拾取。返回 (tri_idx, ArmorTriangleInfo) 或 None。"""
        sc = self._armor_scene
        if sc is None or not sc.tri_count or self.width() < 2:
            return None
        aspect = self.width() / max(self.height(), 1)
        inv_vp = np.linalg.inv(
            self._camera.projection_matrix(aspect) @ self._camera.view_matrix())
        ndcx = 2.0 * x / self.width() - 1.0
        ndcy = 1.0 - 2.0 * y / max(self.height(), 1)

        def _unproj(z):
            v = inv_vp @ np.array([ndcx, ndcy, z, 1.0], dtype=np.float64)
            return v[:3] / v[3]

        p0, p1 = _unproj(0.0), _unproj(1.0)
        d = p1 - p0
        d /= (np.linalg.norm(d) + 1e-12)
        # ArmorScene 为未镜像船体空间 → 射线 Z 取反
        ro = p0 * np.array([1.0, 1.0, -1.0])
        rd = d * np.array([1.0, 1.0, -1.0])
        ti = sc.ray_pick(ro, rd, self._visible_tris)
        if ti is None:
            return None
        return int(ti), sc.tri_info[int(ti)]

    def camera(self) -> OrbitCamera:
        return self._camera

    def _frame_camera(self):
        if self._scene_bounds is None:
            return
        center, size = self._scene_bounds
        self._camera.frame(center, size, self.width(), max(self.height(), 1))

    # ── OpenGL 生命周期 ─────────────────────────────────

    def initializeGL(self):
        self._program = _link_program(VERT_SRC, FRAG_SRC)
        for name in _UNIFORMS:
            self._uniforms[name] = GL.glGetUniformLocation(self._program, name)
        GL.glEnable(GL.GL_DEPTH_TEST)
        self._gl_ready = True
        self._build_meshes()
        self._needs_rebuild = False
        self._flush_pending_gl()
        if self._auto_frame:
            self._frame_camera()

    def resizeGL(self, w, h):
        GL.glViewport(0, 0, w, h)

    def paintGL(self):
        w, h = self.width(), max(self.height(), 1)
        GL.glViewport(0, 0, w, h)
        GL.glClearColor(0.10, 0.12, 0.15, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        # 每帧重设默认 GL 状态（防御上一帧遗留的 depth/blend 被调试覆盖层破坏）
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)
        GL.glDepthFunc(GL.GL_LESS)

        # 上下文已激活，执行挂起的网格重建/取景
        if self._needs_rebuild and self._program:
            self._build_meshes()
            self._needs_rebuild = False
            if self._auto_frame:
                self._frame_camera()
        self._flush_pending_gl()

        if not self._meshes or not self._program:
            return

        # 按当前相机距离动态收紧 near/far，提升深度精度，避免远处薄面 z-fighting
        cam = self._camera
        radius = float(np.linalg.norm(self._scene_bounds[1])) * 0.5 if self._scene_bounds else 1.0
        cam.near = max(cam.distance - radius * 2.0, 0.05)
        cam.far = cam.distance + radius * 4.0

        aspect = w / h
        view = cam.view_matrix()
        proj = cam.projection_matrix(aspect)

        GL.glUseProgram(self._program)
        u = self._uniforms
        GL.glUniform3f(u["u_light_dir"], 0.35, 0.6, 0.72)
        GL.glUniform3f(u["u_ambient"], 0.30, 0.30, 0.32)

        try:
            # ── 不透明 pass：舰体 + 挂载（各自独立贴图 + 挂点模型矩阵） ──
            GL.glDisable(GL.GL_BLEND)
            GL.glDepthMask(GL.GL_TRUE)
            GL.glUniform1i(u["u_mode"], 0)
            GL.glUniform1f(u["u_opacity"], 1.0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glUniform1i(u["u_tex"], 0)
            self._apply_model(view, proj, None)
            for mesh in self._meshes:
                if mesh.kind not in ("hull", "mount"):
                    continue
                if mesh.kind == "hull" and (not self._show_hull or self._show_armor):
                    continue
                if mesh.kind == "mount" and (not self._show_mounts or self._show_armor):
                    continue
                self._apply_model(view, proj, mesh.model_matrix)
                if mesh.kind == "hull" and mesh.tech_family == "indexed":
                    self._bind_indexed(mesh, u)
                else:
                    GL.glUniform1i(u["u_mode"], 0)
                    if mesh.has_tex:
                        GL.glBindTexture(GL.GL_TEXTURE_2D, mesh._texture)
                        GL.glUniform1i(u["u_has_tex"], 1)
                    else:
                        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
                        GL.glUniform1i(u["u_has_tex"], 0)
                mesh.render(GL.GL_TRIANGLES)
            self._apply_model(view, proj, None)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

            # ── 装甲 pass ──
            if self._show_armor:
                GL.glUniform1i(u["u_has_tex"], 0)
                GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glPolygonOffset(-1.0, -1.0)   # 装甲略微拉向相机，避免与船体 z-fight
                GL.glEnable(GL.GL_BLEND)
                GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
                GL.glDepthMask(GL.GL_TRUE)
                GL.glDepthFunc(GL.GL_LEQUAL)
                if self._armor_scene is not None and self._armor_gpu is not None:
                    # 重构后：聚合装甲场景（平涂色 + 不透明度）
                    GL.glUniform1i(u["u_mode"], 2)
                    GL.glUniform1f(u["u_opacity"], self._armor_opacity)
                    self._apply_model(view, proj, None)
                    self._armor_gpu.render(GL.GL_TRIANGLES)
                    GL.glUniform1f(u["u_opacity"], 1.0)
                    GL.glUniform1i(u["u_mode"], 0)
                else:
                    # 旧路径：逐 ArmorMesh
                    for mesh in self._meshes:
                        if mesh.kind != "armor":
                            continue
                        if self._armor_components is not None and \
                                mesh.component not in self._armor_components:
                            continue
                        if self._armor_types is not None and \
                                not (mesh.armor_types & self._armor_types):
                            continue
                        self._apply_model(view, proj, mesh.model_matrix)
                        mesh.render(GL.GL_TRIANGLES)
                self._apply_model(view, proj, None)
                GL.glDisable(GL.GL_BLEND)
                GL.glDepthFunc(GL.GL_LESS)
                GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glDepthMask(GL.GL_TRUE)

                # ── 板块边界描边 pass（装甲场景模式） ──
                if self._armor_scene is not None and self._edge_gpu is not None \
                        and self._show_edges and self._edge_gpu.index_count:
                    GL.glDisable(GL.GL_BLEND)
                    GL.glDepthMask(GL.GL_FALSE)
                    GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glPolygonOffset(-2.0, -2.0)
                    GL.glUniform1i(u["u_mode"], 2)
                    GL.glUniform1f(u["u_opacity"], PLATE_EDGE_COLOR[3])
                    self._apply_model(view, proj, None)
                    self._edge_gpu.render(GL.GL_LINES)
                    GL.glUniform1f(u["u_opacity"], 1.0)
                    GL.glUniform1i(u["u_mode"], 0)
                    GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glDepthMask(GL.GL_TRUE)

                # ── 选中板块高亮 pass ──
                if self._hl_gpu is not None and self._hl_gpu.index_count:
                    GL.glEnable(GL.GL_BLEND)
                    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
                    GL.glDepthMask(GL.GL_FALSE)
                    GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glPolygonOffset(-2.0, -2.0)
                    GL.glUniform1i(u["u_mode"], 2)
                    GL.glUniform1f(u["u_opacity"], 1.0)
                    self._apply_model(view, proj, None)
                    self._hl_gpu.render(GL.GL_TRIANGLES)
                    GL.glUniform1i(u["u_mode"], 0)
                    GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                    GL.glDisable(GL.GL_BLEND)
                    GL.glDepthMask(GL.GL_TRUE)

            # ── 线框叠加 ──
            if self._wireframe:
                GL.glDisable(GL.GL_BLEND)
                GL.glDepthMask(GL.GL_FALSE)
                GL.glUniform1i(u["u_mode"], 1)
                GL.glUniform1f(u["u_opacity"], 1.0)
                for mesh in self._meshes:
                    if mesh.kind not in ("hull", "mount"):
                        continue
                    if mesh.kind == "hull" and (not self._show_hull or self._show_armor):
                        continue
                    if mesh.kind == "mount" and (not self._show_mounts or self._show_armor):
                        continue
                    self._apply_model(view, proj, mesh.model_matrix)
                    mesh._build_lines()
                    mesh.render(GL.GL_LINES, line=True)
                self._apply_model(view, proj, None)
                GL.glDepthMask(GL.GL_TRUE)
        except Exception:  # noqa: BLE001 —— 渲染异常不中断 Qt 绘制循环
            pass

        GL.glUseProgram(0)

    def _bind_indexed(self, mesh, u):
        """绑定 INDEXED 分块贴图与参数（u_mode=3），供 paintGL 调用。

        纹理单元：0=materialIdMap 1=albedoArray(tiles) 2=artMap。
        分块参数来自材质 .mfm 的 vec4 数组（tileIdxMatIdArr/offsetScaleMatIdArr/...）。
        """
        ex = mesh._extra_tex
        ip = mesh.indexed_params or {}
        arrays = ip.get("arrays") or {}
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, ex.get("materialIdMap", 0))
        GL.glUniform1i(u["u_matid_tex"], 0)
        GL.glActiveTexture(GL.GL_TEXTURE1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, ex.get("albedoArray", 0))
        GL.glUniform1i(u["u_tiles_tex"], 1)
        GL.glActiveTexture(GL.GL_TEXTURE2)
        GL.glBindTexture(GL.GL_TEXTURE_2D, ex.get("artMap", 0))
        GL.glUniform1i(u["u_art_tex"], 2)
        # 分块参数
        grid = ip.get("grid") or (38, 38)
        offs = ip.get("offset") or (0.0, 0.0)
        GL.glUniform2f(u["u_grid"], float(grid[0]), float(grid[1]))
        GL.glUniform2f(u["u_grid_offset"], float(offs[0]), float(offs[1]))
        tile = arrays.get("tileIdxMatIdArr")
        if tile is not None and tile.size >= 196:
            arr = np.ascontiguousarray(tile[:196], dtype=np.float32)
        else:
            arr = np.zeros((196, 4), dtype=np.float32)
        GL.glUniform4fv(u["u_tile_idx"], 196, arr)
        art = arrays.get("artStrengthMatIdArr")
        art_s = float(art[0, 0]) if art is not None and len(art) else 0.0
        GL.glUniform1f(u["u_art_strength"], art_s)
        GL.glUniform1i(u["u_has_tex"], 0)
        GL.glUniform1i(u["u_mode"], 3)
        GL.glActiveTexture(GL.GL_TEXTURE0)

    def _apply_model(self, view: np.ndarray, proj: np.ndarray,
                     model: np.ndarray | None):
        """按网格模型矩阵设置 u_mvp / u_normal_mat（None = 恒等）。

        model 为行主序 4x4（渲染空间）；挂载网格需矩阵定位，舰体/装甲恒等。
        """
        u = self._uniforms
        if model is None:
            m = np.eye(4, dtype=np.float32)
        else:
            m = model
        mvp = np.ascontiguousarray((proj @ view @ m).T, dtype=np.float32)
        nm = np.ascontiguousarray(m[:3, :3].T, dtype=np.float32)
        GL.glUniformMatrix4fv(u["u_mvp"], 1, GL.GL_FALSE, mvp)
        GL.glUniformMatrix3fv(u["u_normal_mat"], 1, GL.GL_FALSE, nm)

    # ── 交互 ─────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        self._last_pos = event.position().toPoint()
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        buttons = event.buttons()
        if not buttons:
            # 悬停拾取（节流 ~30fps）
            self._hover_pick(pos)
            self._last_pos = pos
            return
        if self._last_pos is None:
            self._last_pos = pos
            return
        dx = pos.x() - self._last_pos.x()
        dy = pos.y() - self._last_pos.y()
        self._last_pos = pos
        if buttons & Qt.LeftButton:
            self._camera.rotate(-dx * 0.4, dy * 0.4)
            self.update()
        elif buttons & Qt.RightButton:
            self._camera.pan(dx, dy, max(self.height(), 1))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            pos = event.position().toPoint()
            moved = (pos - self._press_pos).manhattanLength()
            self._press_pos = None
            if moved < 5 and self._armor_scene is not None and self._show_armor:
                # 点击选中/取消选中板块
                hit = self.pick_at(pos.x(), pos.y())
                key = hit[1].plate_key if hit else None
                if key == self._selected_plate:
                    key = None
                self.select_plate(key)
                if self.on_select is not None:
                    self.on_select(key)
        self._last_pos = None

    def _hover_pick(self, pos):
        """鼠标悬停拾取：更新 hover 三角形并回调 on_hover。"""
        if self._armor_scene is None or self.on_hover is None:
            return
        if not self._show_armor:
            # 装甲未显示时不做拾取：清除悬停状态并隐藏提示
            if self._hover_tri is not None:
                self._hover_tri = None
                self.on_hover(None, QPoint())
            return
        now = time.perf_counter()
        if now - self._last_pick_time < 0.033:
            return
        self._last_pick_time = now
        hit = self.pick_at(pos.x(), pos.y())
        tri = hit[0] if hit else None
        if tri != self._hover_tri:
            self._hover_tri = tri
        global_pos = self.mapToGlobal(pos)
        self.on_hover(tri, global_pos)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = (0.88 if delta > 0 else 1.0 / 0.88)
        self._camera.zoom(factor)
        self.update()

    def leaveEvent(self, event):
        self._last_pos = None
        if self._hover_tri is not None:
            self._hover_tri = None
            if self.on_hover is not None:
                self.on_hover(None, QPoint())
