"""renderer.api —— ``wows_renderer.dll`` 的 ctypes 绑定与句柄生命周期管理。

约定（与 ``native/include/wows_renderer.h`` 一一对应）：

- 纯 C ABI；句柄不透明。
- 所有函数返回 ``int32_t``：``0`` = 成功，负值 = 错误码。
- 所有结构体首字段 ``struct_size``，调用前必须填充为 ``ctypes.sizeof(...)``。
- **线程约束**：必须在创建 renderer 的同一线程调用（即 Qt 主线程）。
- DLL 缺失时抛 :class:`RendererUnavailable`（:class:`RendererError` 子类），
  调用方据此降级为界面提示，而不是让异常穿透事件循环。
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, byref, c_char_p, c_float, c_int32, c_uint32, c_uint64, c_void_p
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

# ------------------------------------------------------------------ 常量

WSR_OK = 0
WSR_ERR_INVALID_ARG = -1
WSR_ERR_DEVICE = -2
WSR_ERR_SWAPCHAIN = -3
WSR_ERR_OUT_OF_MEMORY = -4
WSR_ERR_SHADER = -5
WSR_ERR_INTERNAL = -6

WSR_FLAG_NONE = 0x0
WSR_FLAG_NO_VSYNC = 0x1
WSR_FLAG_LEGACY_BITBLT = 0x2
#: 启用 deferred（MRT + 全屏光照）；默认关闭，见 C 头注释
WSR_FLAG_DEFERRED = 0x8

_ERROR_NAMES = {
    WSR_OK: "OK",
    WSR_ERR_INVALID_ARG: "INVALID_ARG",
    WSR_ERR_DEVICE: "DEVICE",
    WSR_ERR_SWAPCHAIN: "SWAPCHAIN",
    WSR_ERR_OUT_OF_MEMORY: "OUT_OF_MEMORY",
    WSR_ERR_SHADER: "SHADER",
    WSR_ERR_INTERNAL: "INTERNAL",
}

DLL_NAME = "wows_renderer.dll"


# ------------------------------------------------------------------ 异常


class RendererError(RuntimeError):
    """渲染后端调用失败。"""


class RendererUnavailable(RendererError):
    """DLL 不存在或无法加载（可降级处理）。"""


# ------------------------------------------------------------------ 结构体


class _WsrStats(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("struct_size", c_uint32),
        ("draw_calls", c_uint32),
        ("device_lost_count", c_uint32),
        ("frame_index", c_uint32),
        ("frame_ms_last", c_float),
        ("frame_ms_avg", c_float),
    ]


class _WsrOptions(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("struct_size", c_uint32),
        ("clear_color", c_float * 4),
    ]


@dataclass(frozen=True)
class Stats:
    """``wsr_stats`` 的 Python 视图。"""

    draw_calls: int
    device_lost_count: int
    frame_index: int
    frame_ms_last: float
    frame_ms_avg: float


class _WsrVertex(ctypes.Structure):
    """48 字节：pos(3) + normal(3) + uv(2) + color(4)。"""

    _fields_ = [
        ("pos", c_float * 3),
        ("normal", c_float * 3),
        ("uv", c_float * 2),
        ("color", c_float * 4),
    ]


class _WsrTextureDesc(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("kind", c_uint32),
        ("format", c_uint32),
        ("width", c_uint32),
        ("height", c_uint32),
        ("array_size", c_uint32),
        ("mip_count", c_uint32),
        ("flags", c_uint32),
        ("data", c_void_p),
        ("data_size", c_uint64),
        ("mip_offsets", POINTER(c_uint32)),
        ("mip_sizes", POINTER(c_uint32)),
    ]


class _WsrMeshDesc(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("key", c_char_p),
        ("kind", c_uint32),
        ("family", c_uint32),
        ("flags", c_uint32),
        ("vertices", POINTER(_WsrVertex)),
        ("vertex_count", c_uint32),
        ("indices", POINTER(c_uint32)),
        ("index_count", c_uint32),
        ("model_matrix", POINTER(c_float)),
        ("instance_matrices", POINTER(c_float)),
        ("instance_count", c_uint32),
        ("opacity", c_float),
        ("emissive_k", c_float),
        ("textures", c_char_p * 10),
        ("matid_count", c_uint32),
        ("arr_offset_scale", POINTER(c_float)),
        ("arr_rotation", POINTER(c_float)),
        ("arr_tile_idx", POINTER(c_float)),
        ("arr_tint", POINTER(c_float)),
        ("arr_remove", POINTER(c_float)),
    ]


class _WsrFrameParams(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("view", c_float * 16),
        ("proj", c_float * 16),
        ("light_pos", c_float * 3),
        ("light_dir", c_float * 3),
        ("ambient", c_float * 3),
        ("normal_strength", c_float),
        ("opacity", c_float),
        ("debug_mode", c_uint32),
    ]


class _WsrViewOptions(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("show_hull", c_uint32),
        ("show_mounts", c_uint32),
        ("show_armor", c_uint32),
        ("wireframe", c_uint32),
        ("show_edges", c_uint32),
        ("armor_opacity", c_float),
        ("clear_color", c_float * 4),
    ]


# ------------------------------------------------------------------ DLL 定位


def _search_paths() -> list[Path]:
    """按优先级返回候选 DLL 路径。

    ``WSR_DLL_PATH`` 一旦设置则**只使用它**（不回退到默认位置）：
    既方便本地切换构建产物，也让「DLL 缺失」能够被可靠复现与测试。
    """
    override = os.environ.get("WSR_DLL_PATH", "").strip()
    if override:
        return [Path(override)]

    candidates: list[Path] = []
    roots: list[Path] = []
    # 源码运行：renderer/api.py -> <root>
    try:
        roots.append(Path(__file__).resolve().parent.parent)
    except NameError:  # pragma: no cover - 打包环境极端情况
        pass
    # 打包运行：可执行文件所在目录（含其上级的 release/）
    exe_dir = Path(sys.executable).resolve().parent
    roots.extend([exe_dir, exe_dir.parent])
    # Nuitka onefile 解包目录
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))

    seen: set[Path] = set()
    for root in roots:
        for rel in (
            Path("release") / DLL_NAME,
            Path(DLL_NAME),
            Path("native") / "build" / "Release" / DLL_NAME,
            Path("native") / "build" / DLL_NAME,
        ):
            p = (root / rel).resolve()
            if p not in seen:
                seen.add(p)
                candidates.append(p)
    return candidates


def find_library() -> Path | None:
    """返回第一个存在的 DLL 路径；都不存在时返回 ``None``。"""
    for p in _search_paths():
        if p.is_file():
            return p
    return None


def iter_searched_paths() -> Iterable[Path]:
    """调试用：列出所有候选路径。"""
    return tuple(_search_paths())


# ------------------------------------------------------------------ 函数原型

_LIB_CACHE: ctypes.CDLL | None = None
_LIB_ERROR: str | None = None


def _load_library() -> ctypes.CDLL:
    global _LIB_CACHE, _LIB_ERROR
    if _LIB_CACHE is not None:
        return _LIB_CACHE
    if _LIB_ERROR is not None:
        raise RendererUnavailable(_LIB_ERROR)

    path = find_library()
    if path is None:
        searched = "\n  ".join(str(p) for p in _search_paths())
        _LIB_ERROR = (
            f"{DLL_NAME} not found. Searched:\n  {searched}\n"
            f"Build it with: cmake -S native -B native/build && "
            f"cmake --build native/build --config Release"
        )
        raise RendererUnavailable(_LIB_ERROR)

    try:
        lib = ctypes.CDLL(str(path))
    except OSError as exc:  # pragma: no cover - 依赖系统状态
        _LIB_ERROR = f"failed to load {path}: {exc}"
        raise RendererUnavailable(_LIB_ERROR) from exc

    lib.wsr_create.argtypes = [c_void_p, c_uint32, c_uint32, c_uint32, POINTER(c_void_p)]
    lib.wsr_create.restype = c_int32
    lib.wsr_destroy.argtypes = [c_void_p]
    lib.wsr_destroy.restype = None
    lib.wsr_resize.argtypes = [c_void_p, c_uint32, c_uint32]
    lib.wsr_resize.restype = c_int32
    lib.wsr_set_dpi_scale.argtypes = [c_void_p, c_float]
    lib.wsr_set_dpi_scale.restype = c_int32
    lib.wsr_set_options.argtypes = [c_void_p, POINTER(_WsrOptions)]
    lib.wsr_set_options.restype = c_int32
    lib.wsr_render.argtypes = [c_void_p]
    lib.wsr_render.restype = c_int32
    lib.wsr_stats_get.argtypes = [c_void_p, POINTER(_WsrStats)]
    lib.wsr_stats_get.restype = c_int32
    lib.wsr_last_error.argtypes = []
    lib.wsr_last_error.restype = c_char_p
    lib.wsr_debug_simulate_device_lost.argtypes = [c_void_p]
    lib.wsr_debug_simulate_device_lost.restype = c_int32

    lib.wsr_texture_upload.argtypes = [c_void_p, c_char_p, POINTER(_WsrTextureDesc)]
    lib.wsr_texture_upload.restype = c_int32
    lib.wsr_texture_clear.argtypes = [c_void_p]
    lib.wsr_texture_clear.restype = c_int32

    lib.wsr_scene_begin.argtypes = [c_void_p]
    lib.wsr_scene_begin.restype = c_int32
    lib.wsr_scene_add_mesh.argtypes = [c_void_p, POINTER(_WsrMeshDesc)]
    lib.wsr_scene_add_mesh.restype = c_int32
    lib.wsr_scene_end.argtypes = [c_void_p]
    lib.wsr_scene_end.restype = c_int32
    lib.wsr_scene_clear.argtypes = [c_void_p]
    lib.wsr_scene_clear.restype = c_int32

    lib.wsr_frame_set.argtypes = [c_void_p, POINTER(_WsrFrameParams)]
    lib.wsr_frame_set.restype = c_int32
    lib.wsr_view_options_set.argtypes = [c_void_p, POINTER(_WsrViewOptions)]
    lib.wsr_view_options_set.restype = c_int32

    lib.wsr_mesh_set_visible.argtypes = [c_void_p, c_char_p, c_uint32]
    lib.wsr_mesh_set_visible.restype = c_int32
    lib.wsr_mesh_set_indices.argtypes = [c_void_p, c_char_p, POINTER(c_uint32), c_uint32]
    lib.wsr_mesh_set_indices.restype = c_int32
    lib.wsr_mesh_set_highlight.argtypes = [c_void_p, c_char_p, POINTER(c_uint32), c_uint32]
    lib.wsr_mesh_set_highlight.restype = c_int32

    lib.wsr_scene_stats.argtypes = [c_void_p, POINTER(c_uint32), POINTER(c_uint32)]
    lib.wsr_scene_stats.restype = c_int32
    lib.wsr_needs_resubmit.argtypes = [c_void_p]
    lib.wsr_needs_resubmit.restype = c_int32
    lib.wsr_capture_bmp.argtypes = [c_void_p, c_char_p]
    lib.wsr_capture_bmp.restype = c_int32
    lib.wsr_diag_state.argtypes = [c_void_p, POINTER(c_uint32)]
    lib.wsr_diag_state.restype = c_int32

    _LIB_CACHE = lib
    return lib


def is_available() -> bool:
    """DLL 是否可加载（不抛异常）。"""
    try:
        _load_library()
    except RendererUnavailable:
        return False
    return True


def last_error() -> str:
    """读取 ``wsr_last_error()``（无 renderer 实例也能调用）。"""
    try:
        lib = _load_library()
    except RendererUnavailable:
        return ""
    raw = lib.wsr_last_error()
    return raw.decode("utf-8", "replace") if raw else ""


# ------------------------------------------------------------------ Renderer


class Renderer:
    """一个 D3D11 渲染后端实例（对应一个窗口 / 交换链）。

    典型用法（Qt 主线程内）::

        r = Renderer(int(widget.winId()), widget.width(), widget.height())
        r.set_dpi_scale(widget.devicePixelRatioF())
        r.render()            # 每帧
        r.resize(w, h)        # resizeEvent
        r.destroy()           # 关闭时
    """

    __slots__ = ("_handle", "_destroyed")

    def __init__(
        self,
        hwnd: int,
        width: int,
        height: int,
        *,
        dpi_scale: float = 1.0,
        no_vsync: bool = False,
        legacy_bitblt: bool = False,
        deferred: bool = True,
    ) -> None:
        if not hwnd:
            raise RendererError("hwnd must be a valid window handle")

        lib = _load_library()
        flags = WSR_FLAG_NONE
        if no_vsync:
            flags |= WSR_FLAG_NO_VSYNC
        if legacy_bitblt:
            flags |= WSR_FLAG_LEGACY_BITBLT
        if deferred:
            flags |= WSR_FLAG_DEFERRED

        handle = c_void_p()
        code = lib.wsr_create(
            c_void_p(int(hwnd)),
            c_uint32(max(1, int(width))),
            c_uint32(max(1, int(height))),
            c_uint32(flags),
            byref(handle),
        )
        if code != WSR_OK or not handle:
            raise RendererError(self._describe("wsr_create", code))

        self._handle: c_void_p | None = handle
        self._destroyed = False

        if dpi_scale and abs(dpi_scale - 1.0) > 1e-6:
            self.set_dpi_scale(dpi_scale)

    # -------------------------------------------------------------- 生命周期

    def destroy(self) -> None:
        """幂等释放。必须在创建它的线程调用。"""
        if self._destroyed or self._handle is None:
            return
        _load_library().wsr_destroy(self._handle)
        self._handle = None
        self._destroyed = True

    def __del__(self) -> None:  # pragma: no cover - 兜底
        try:
            self.destroy()
        except Exception:
            pass

    def __enter__(self) -> "Renderer":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.destroy()

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    # -------------------------------------------------------------- 每帧

    def render(self) -> None:
        code = self._lib().wsr_render(self._require())
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_render", code))

    def resize(self, width: int, height: int) -> None:
        code = self._lib().wsr_resize(
            self._require(), c_uint32(max(1, int(width))), c_uint32(max(1, int(height)))
        )
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_resize", code))

    def set_dpi_scale(self, scale: float) -> None:
        code = self._lib().wsr_set_dpi_scale(self._require(), c_float(float(scale)))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_set_dpi_scale", code))

    def set_clear_color(self, r: float, g: float, b: float, a: float = 1.0) -> None:
        opt = _WsrOptions()
        opt.struct_size = ctypes.sizeof(_WsrOptions)
        opt.clear_color[0] = float(r)
        opt.clear_color[1] = float(g)
        opt.clear_color[2] = float(b)
        opt.clear_color[3] = float(a)
        code = self._lib().wsr_set_options(self._require(), byref(opt))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_set_options", code))

    def stats(self) -> Stats:
        raw = _WsrStats()
        raw.struct_size = ctypes.sizeof(_WsrStats)
        code = self._lib().wsr_stats_get(self._require(), byref(raw))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_stats_get", code))
        return Stats(
            draw_calls=raw.draw_calls,
            device_lost_count=raw.device_lost_count,
            frame_index=raw.frame_index,
            frame_ms_last=raw.frame_ms_last,
            frame_ms_avg=raw.frame_ms_avg,
        )

    # -------------------------------------------------------------- 调试

    def debug_simulate_device_lost(self) -> None:
        """模拟设备丢失，用于验证恢复链路（P0 验收项）。"""
        code = self._lib().wsr_debug_simulate_device_lost(self._require())
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_debug_simulate_device_lost", code))

    # -------------------------------------------------------------- 内部

    def _lib(self) -> ctypes.CDLL:
        return _load_library()

    def _require(self) -> c_void_p:
        if self._destroyed or self._handle is None:
            raise RendererError("renderer has been destroyed")
        return self._handle

    def _describe(self, func: str, code: int) -> str:
        name = _ERROR_NAMES.get(code, f"UNKNOWN({code})")
        detail = last_error()
        base = f"{func} failed: {name}"
        return f"{base}: {detail}" if detail else base

    # -------------------------------------------------------------- 纹理

    def upload_texture(self, spec) -> None:
        """上传一个 :class:`renderer.types.TextureSpec`（同 key 覆盖）。"""
        data = spec.data
        n = max(1, len(spec.mip_offsets))
        offs = (c_uint32 * n)(*spec.mip_offsets)
        sizes = (c_uint32 * n)(*spec.mip_sizes)
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)

        desc = _WsrTextureDesc()
        desc.struct_size = ctypes.sizeof(_WsrTextureDesc)
        desc.kind = spec.kind
        desc.format = spec.format
        desc.width = spec.width
        desc.height = spec.height
        desc.array_size = spec.array_size
        desc.mip_count = spec.mip_count
        desc.flags = spec.flags
        desc.data = ctypes.cast(buf, c_void_p)
        desc.data_size = len(data)
        desc.mip_offsets = offs
        desc.mip_sizes = sizes

        code = self._lib().wsr_texture_upload(
            self._require(), str(spec.key).encode("utf-8"), byref(desc)
        )
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_texture_upload", code))

    def clear_textures(self) -> None:
        code = self._lib().wsr_texture_clear(self._require())
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_texture_clear", code))

    # -------------------------------------------------------------- 场景

    def scene_begin(self) -> None:
        code = self._lib().wsr_scene_begin(self._require())
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_scene_begin", code))

    def scene_add_mesh(self, spec) -> None:
        """提交一个 :class:`renderer.types.MeshSpec`。"""
        verts = np.ascontiguousarray(spec.vertices, dtype=np.float32)
        indices = np.ascontiguousarray(spec.indices, dtype=np.uint32)
        if verts.ndim != 2 or verts.shape[1] != 12:
            raise RendererError(f"mesh '{spec.key}': vertices must be (N,12) float32")

        desc = _WsrMeshDesc()
        desc.struct_size = ctypes.sizeof(_WsrMeshDesc)
        desc.key = spec.key.encode("utf-8")
        desc.kind = spec.kind
        desc.family = spec.family
        desc.flags = spec.flags
        desc.vertices = ctypes.cast(verts.ctypes.data, POINTER(_WsrVertex))
        desc.vertex_count = int(verts.shape[0])
        desc.indices = ctypes.cast(indices.ctypes.data, POINTER(c_uint32))
        desc.index_count = int(indices.size)
        desc.opacity = float(spec.opacity)
        desc.emissive_k = float(spec.emissive_k)

        model = None
        if spec.model_matrix is not None:
            model = np.ascontiguousarray(spec.model_matrix, dtype=np.float32).reshape(-1)
            desc.model_matrix = ctypes.cast(model.ctypes.data, POINTER(c_float))

        inst = None
        if spec.instance_matrices is not None and len(spec.instance_matrices):
            inst = np.ascontiguousarray(spec.instance_matrices, dtype=np.float32).reshape(-1)
            desc.instance_matrices = ctypes.cast(inst.ctypes.data, POINTER(c_float))
            desc.instance_count = int(inst.size // 16)

        tex_bytes: list[bytes | None] = []
        for slot in range(10):
            key = spec.textures.get(slot)
            tex_bytes.append(key.encode("utf-8") if key else None)
        desc.textures = (c_char_p * 10)(*tex_bytes)

        arr_refs = []
        for name, slot in (
            ("arr_offset_scale", "arr_offset_scale"),
            ("arr_rotation", "arr_rotation"),
            ("arr_tile_idx", "arr_tile_idx"),
            ("arr_tint", "arr_tint"),
            ("arr_remove", "arr_remove"),
        ):
            arr = getattr(spec, name, None)
            if arr is None:
                continue
            flat = np.ascontiguousarray(arr, dtype=np.float32).reshape(-1)
            arr_refs.append(flat)
            setattr(desc, slot, ctypes.cast(flat.ctypes.data, POINTER(c_float)))
        if spec.matid_count:
            desc.matid_count = int(spec.matid_count)

        code = self._lib().wsr_scene_add_mesh(self._require(), byref(desc))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_scene_add_mesh", code))

    def scene_end(self) -> None:
        code = self._lib().wsr_scene_end(self._require())
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_scene_end", code))

    def scene_clear(self) -> None:
        code = self._lib().wsr_scene_clear(self._require())
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_scene_clear", code))

    def set_mesh_visible(self, key: str, visible: bool) -> None:
        code = self._lib().wsr_mesh_set_visible(
            self._require(), str(key).encode("utf-8"), 1 if visible else 0
        )
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_mesh_set_visible", code))

    def set_mesh_indices(self, key: str, indices) -> None:
        if indices is None or len(indices) == 0:
            code = self._lib().wsr_mesh_set_indices(
                self._require(), str(key).encode("utf-8"), None, 0
            )
        else:
            arr = np.ascontiguousarray(indices, dtype=np.uint32)
            code = self._lib().wsr_mesh_set_indices(
                self._require(), str(key).encode("utf-8"),
                ctypes.cast(arr.ctypes.data, POINTER(c_uint32)), int(arr.size),
            )
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_mesh_set_indices", code))

    def scene_stats(self) -> tuple[int, int]:
        meshes = c_uint32(0)
        textures = c_uint32(0)
        code = self._lib().wsr_scene_stats(self._require(), byref(meshes), byref(textures))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_scene_stats", code))
        return int(meshes.value), int(textures.value)

    def needs_resubmit(self) -> bool:
        """设备丢失重建后为真：必须重新提交纹理与场景。"""
        return self._lib().wsr_needs_resubmit(self._require()) == 1

    def capture_bmp(self, path: str) -> None:
        """把当前后备缓冲抓成 32bpp BMP（A/B 对比用）。"""
        code = self._lib().wsr_capture_bmp(self._require(), str(path).encode("utf-8"))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_capture_bmp", code))
    def diag_state(self) -> int:
        """内部对象就绪位标志（诊断用，含义见 C 头）。"""
        flags = c_uint32(0)
        code = self._lib().wsr_diag_state(self._require(), byref(flags))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_diag_state", code))
        return int(flags.value)
    # -------------------------------------------------------------- 帧 / 选项

    def set_frame(
        self,
        view,
        proj,
        *,
        light_pos=(0.0, 0.0, 0.0),
        light_dir=(-0.35, -0.6, -0.72),
        ambient=(0.06, 0.08, 0.10),
        normal_strength: float = 1.5,
        opacity: float = 1.0,
        debug_mode: int = 0,
    ) -> None:
        """上传相机与光照参数（矩阵为行主序数学矩阵）。"""
        p = _WsrFrameParams()
        p.struct_size = ctypes.sizeof(_WsrFrameParams)
        v = np.ascontiguousarray(view, dtype=np.float32).reshape(-1)
        m = np.ascontiguousarray(proj, dtype=np.float32).reshape(-1)
        for i in range(16):
            p.view[i] = float(v[i])
            p.proj[i] = float(m[i])
        for i in range(3):
            p.light_pos[i] = float(light_pos[i])
            p.light_dir[i] = float(light_dir[i])
            p.ambient[i] = float(ambient[i])
        p.normal_strength = float(normal_strength)
        p.opacity = float(opacity)
        p.debug_mode = int(debug_mode)
        code = self._lib().wsr_frame_set(self._require(), byref(p))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_frame_set", code))

    def set_view_options(
        self,
        *,
        show_hull: bool = True,
        show_mounts: bool = True,
        show_armor: bool = False,
        wireframe: bool = False,
        show_edges: bool = True,
        armor_opacity: float = 0.45,
        clear_color=(0.30, 0.46, 0.60, 1.0),
    ) -> None:
        o = _WsrViewOptions()
        o.struct_size = ctypes.sizeof(_WsrViewOptions)
        o.show_hull = 1 if show_hull else 0
        o.show_mounts = 1 if show_mounts else 0
        o.show_armor = 1 if show_armor else 0
        o.wireframe = 1 if wireframe else 0
        o.show_edges = 1 if show_edges else 0
        o.armor_opacity = float(armor_opacity)
        for i in range(4):
            o.clear_color[i] = float(clear_color[i])
        code = self._lib().wsr_view_options_set(self._require(), byref(o))
        if code != WSR_OK:
            raise RendererError(self._describe("wsr_view_options_set", code))


def sizeof_stats() -> int:
    """供测试比对 Python 与 C 侧结构体大小。"""
    return ctypes.sizeof(_WsrStats)
