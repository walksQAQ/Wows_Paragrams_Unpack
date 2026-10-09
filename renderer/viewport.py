"""renderer.viewport —— 场景提交与逐帧参数（与 Qt 无关）。

职责（架构文档 §8）：

- 持有场景的 **CPU 侧权威描述**，负责首次提交与设备丢失后的重提交（§11.2）；
- 把 Python 相机矩阵转换成后端可直接使用的形式（含 D3D 的 z ∈ [0,1] 修正）；
- 保持与旧渲染器一致的相机/光照语义（near/far 动态收紧、点光源位置、环境光）。

相机与交互状态留在 Python（不做 C++ 侧重复实现）。
"""

from __future__ import annotations

import time

import numpy as np

from .scene import build_scene

#: 与旧渲染器 paintGL 一致的常量（搬运，不得擅自改动 —— 见架构文档 §7.4 锁定表）
LIGHT_DIR = (-0.35, -0.6, -0.72)
AMBIENT = (0.06, 0.08, 0.10)
NORMAL_STRENGTH = 1.5
LIGHT_HEIGHT = 45.0


def to_d3d_projection(proj: np.ndarray) -> np.ndarray:
    """把 OpenGL 约定（z ∈ [-1,1]）的投影矩阵改为 D3D 约定（z ∈ [0,1]）。

    做法：``z' = 0.5*z + 0.5*w`` ⇒ 行主序下 ``row2 = 0.5*row2 + 0.5*row3``。
    这样不必改动已验证的 :class:`models.camera.OrbitCamera`，也不影响其它调用方。
    """
    out = np.array(proj, dtype=np.float32, copy=True)
    out[2, :] = 0.5 * out[2, :] + 0.5 * out[3, :]
    return out


class FrameState:
    """光照/调试等每帧参数（默认值与旧渲染器一致）。"""

    def __init__(self) -> None:
        self.light_dir = LIGHT_DIR
        self.ambient = AMBIENT
        self.normal_strength = NORMAL_STRENGTH
        self.debug_mode = 0
        self.opacity = 1.0
        #: 渲染风格：0 = 游戏原版（逐行搬运），1 = Studio PBR（程序化 studio 环境 + IBL + 曝光 + ACES）
        #: 默认 1：用户要求先看 Blender 式环境光效果（面板「渲染风格」可随时切回原版）
        self.lighting_mode = 1
        #: 法线空间：0 = 切线空间法线直接当世界法线（旧行为），1 = 正确 TBN（**固定默认**）
        #: _n 只有在正确 TBN 下才会真的产生表面细节，故不再提供开关。
        self.normal_space = 1
        #: 环境亮度（原版路径用作环境反射强度；Studio 模式用作 IBL 强度）；0 = 关闭
        self.env_strength = 1.0
        self.exposure = 1.0
        #: 纹理 V 轴（仅 D3D 后端有该参数）：0 = 不翻转（默认，与游戏内一致，已实测）。
        #: GL 后端（ui/geometry_renderer.py）不读这个参数；它的采样路径与 0 等价
        #: （两边都是「数据第 0 行 ↔ 坐标 0」，同一个 (u,v) 取同一行），所以不需要翻转。
        self.uv_flip = 0
        self.scene_center: np.ndarray | None = None

    def light_pos(self) -> tuple[float, float, float]:
        if self.scene_center is None:
            return (0.0, LIGHT_HEIGHT, 0.0)
        c = self.scene_center
        return (float(c[0]), float(c[1]) + LIGHT_HEIGHT, float(c[2]))


class RenderScene:
    """场景的 CPU 侧描述 + 提交/重提交。"""

    def __init__(self, renderer) -> None:
        self._r = renderer
        self._textures = []
        self._meshes = []
        self._dirty = False
        #: 场景代数：``set_scene`` 每次自增；提交中的切片发现代数变了才重头来
        #: （⚠️ 不能用 ``_dirty`` 当判据：它在整个提交过程中一直是 True，会让
        #:  每个 tick 都重启提交，上传永远完不成。）
        self._scene_gen = 0
        self._stage_gen = -1
        #: 增量提交状态（``_stage`` 为空串 = 空闲）
        self._stage = ""
        self._tex_i = 0
        self._mesh_i = 0
        self._submit_started = 0.0
        self._tex_elapsed = 0.0
        self._last_pct = -1
        #: 上两次上传耗时（秒），供调用方打日志／定位性能问题
        self.last_tex_seconds = 0.0
        self.last_mesh_seconds = 0.0
        #: 上次上传中耗时超阈值的单项 ``[(描述, 秒), ...]``（按耗时降序，最多 20 条）
        self.last_slow_items: list[tuple[str, float]] = []
        self._slow: list[tuple[str, float]] = []
        #: 进度回调（主线程调用）：``fn(stage, done, total, elapsed_s)``
        #: ``stage`` ∈ ``"start"`` / ``"tex"`` / ``"mesh"`` / ``"done"``
        self.on_progress = None
        #: 单项超时回调：``fn(描述, 秒)``（上传慢时用来当场定位是哪张贴图/网格）
        self.on_slow = None
        self._slow_logged = 0

    # ------------------------------------------------------------ 场景

    def set_scene(self, geometry, armor_scene=None) -> None:
        self._textures, self._meshes = build_scene(geometry, armor_scene)
        self._scene_gen += 1
        self._dirty = True

    def clear(self) -> None:
        self._textures = []
        self._meshes = []
        self._dirty = False
        self._stage = ""
        self._r.scene_clear()
        self._r.clear_textures()

    @property
    def is_submitting(self) -> bool:
        """是否正在增量提交（GUI 可据此显示「上传到 GPU」提示）。"""
        return self._stage != ""

    def _begin_submit(self) -> None:
        """开始（重新开始）一次提交：清空后端场景并重置游标。"""
        self._r.scene_clear()
        self._r.clear_textures()
        self._stage = "tex" if self._textures else "mesh"
        self._tex_i = 0
        self._mesh_i = 0
        self._submit_started = time.perf_counter()
        self._tex_elapsed = 0.0
        self._last_pct = -1
        self._slow = []
        self._slow_logged = 0
        self._stage_gen = self._scene_gen
        if self._stage == "mesh":
            self._r.scene_begin()
        self._notify("start", force=True)

    def _notify(self, stage: str, force: bool = False) -> None:
        cb = self.on_progress
        if cb is None:
            return
        total = len(self._textures) + len(self._meshes)
        done = self._tex_i + self._mesh_i
        if not force:
            pct = 0 if total == 0 else int(done * 100 / total)
            if done < total and pct - self._last_pct < 2:
                return
            self._last_pct = pct
        cb(stage, done, total, time.perf_counter() - self._submit_started)

    @property
    def mesh_keys(self) -> list[str]:
        return [m.key for m in self._meshes]

    @property
    def mesh_count(self) -> int:
        return len(self._meshes)

    @property
    def texture_count(self) -> int:
        return len(self._textures)

    @property
    def texture_bytes(self) -> int:
        """场景描述里纹理字节总数（诊断用）。"""
        return sum(len(t.data) for t in self._textures)

    @property
    def mesh_bytes(self) -> int:
        """场景描述里顶点+索引字节总数（诊断用）。"""
        return sum(m.vertices.nbytes + m.indices.nbytes for m in self._meshes)

    def submit_if_needed(self, force: bool = False, budget_ms: float = 8.0) -> bool:
        """增量提交场景（首次 / 有变更 / 后端要求重提交）。返回**本次是否已全部完成**。

        ``budget_ms`` 是单个时间片允许占用的主线程毫秒数：一次调用最多干这么多活，
        没干完留到下一次调用（调用方是渲染 tick）—— 大船（中途岛那类 INDEXED
        数组可达几百 MB）一次性上传会把 GUI 冻住很久，这里改成分片上传。
        ``budget_ms <= 0`` 表示不限时（一次干完；仅用于无 GUI 的测试/探针）。
        """
        if self._stage and self._stage_gen != self._scene_gen:
            self._begin_submit()          # 上传途中场景被替换 → 重头来
        elif not self._stage:
            if not (force or self._dirty or self._r.needs_resubmit()):
                return False
            self._begin_submit()

        deadline = None if budget_ms <= 0 else time.perf_counter() + budget_ms / 1000.0

        if self._stage == "tex":
            while self._tex_i < len(self._textures):
                spec = self._textures[self._tex_i]
                t1 = time.perf_counter()
                self._r.upload_texture(spec)
                self._note_slow(
                    f"纹理 {spec.key} {spec.width}x{spec.height} 层{spec.array_size} "
                    f"mip{spec.mip_count} {len(spec.data) / 1e6:.1f}MB",
                    time.perf_counter() - t1)
                self._tex_i += 1
                if deadline is not None and time.perf_counter() >= deadline:
                    self._notify("tex")
                    return False
            self._r.scene_begin()
            self._stage = "mesh"
            self._tex_elapsed = time.perf_counter() - self._submit_started

        while self._mesh_i < len(self._meshes):
            spec_m = self._meshes[self._mesh_i]
            t1 = time.perf_counter()
            self._r.scene_add_mesh(spec_m)
            self._note_slow(
                f"网格 {spec_m.key[:60]} 顶点{len(spec_m.vertices)} "
                f"索引{len(spec_m.indices)}",
                time.perf_counter() - t1)
            self._mesh_i += 1
            if deadline is not None and time.perf_counter() >= deadline:
                self._notify("mesh")
                return False

        self._r.scene_end()
        self._stage = ""
        self._dirty = False
        total_elapsed = time.perf_counter() - self._submit_started
        self.last_tex_seconds = self._tex_elapsed
        self.last_mesh_seconds = max(0.0, total_elapsed - self._tex_elapsed)
        self.last_slow_items = sorted(self._slow, key=lambda kv: -kv[1])[:20]
        self._notify("done", force=True)
        return True

    def _note_slow(self, what: str, seconds: float, threshold: float = 0.3) -> None:
        """记录单项上传耗时（超阈值）——当场打日志，上传慢时用来定位卡在哪一项。"""
        if seconds < threshold:
            return
        self._slow.append((what, seconds))
        if self.on_slow is not None and self._slow_logged < 10:
            self._slow_logged += 1
            self.on_slow(what, seconds)
