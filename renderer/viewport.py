"""renderer.viewport —— 场景提交与逐帧参数（与 Qt 无关）。

职责（架构文档 §8）：

- 持有场景的 **CPU 侧权威描述**，负责首次提交与设备丢失后的重提交（§11.2）；
- 把 Python 相机矩阵转换成后端可直接使用的形式（含 D3D 的 z ∈ [0,1] 修正）；
- 保持与旧渲染器一致的相机/光照语义（near/far 动态收紧、点光源位置、环境光）。

相机与交互状态留在 Python（不做 C++ 侧重复实现）。
"""

from __future__ import annotations

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

    # ------------------------------------------------------------ 场景

    def set_scene(self, geometry, armor_scene=None) -> None:
        self._textures, self._meshes = build_scene(geometry, armor_scene)
        self._dirty = True

    def clear(self) -> None:
        self._textures = []
        self._meshes = []
        self._dirty = False
        self._r.scene_clear()
        self._r.clear_textures()

    @property
    def mesh_keys(self) -> list[str]:
        return [m.key for m in self._meshes]

    @property
    def mesh_count(self) -> int:
        return len(self._meshes)

    @property
    def texture_count(self) -> int:
        return len(self._textures)

    def submit_if_needed(self, force: bool = False) -> bool:
        """提交场景（首次 / 有变更 / 后端要求重提交）。返回是否真的提交。"""
        if not (force or self._dirty or self._r.needs_resubmit()):
            return False
        self._r.scene_clear()
        self._r.clear_textures()
        for tex in self._textures:
            self._r.upload_texture(tex)
        self._r.scene_begin()
        for mesh in self._meshes:
            self._r.scene_add_mesh(mesh)
        self._r.scene_end()
        self._dirty = False
        return True
