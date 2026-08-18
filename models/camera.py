"""
camera.py —— 轨道相机（OrbitCamera），纯 numpy 实现。

提供 view / projection 矩阵（用于 OpenGL 渲染）与交互接口：
  左键拖拽旋转、滚轮缩放、右键拖拽平移。
"""

from __future__ import annotations

import numpy as np


class OrbitCamera:
    """围绕目标点的轨道相机。

    - yaw/pitch：球坐标角度（度）
    - distance：相机到目标距离
    - target：注视点
    """

    def __init__(self):
        self.target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.distance = 40.0
        # 默认 yaw=90°：从侧舷（+X 方向）观看，船身长度横向展开
        self.yaw = 90.0
        self.pitch = 22.0
        self.fov = 45.0
        self.near = 0.05
        self.far = 10000.0
        self._min_dist = 0.5
        self._max_dist = 10000.0

    # ── 相机基 ──────────────────────────────────────────

    def eye(self) -> np.ndarray:
        yaw_r = np.radians(self.yaw)
        pitch_r = np.radians(self.pitch)
        dir = np.array([
            np.cos(pitch_r) * np.sin(yaw_r),
            np.sin(pitch_r),
            np.cos(pitch_r) * np.cos(yaw_r),
        ], dtype=np.float32)
        return self.target + self.distance * dir

    def _basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """返回 (forward, right, up) 单位向量。"""
        eye = self.eye()
        forward = self.target - eye
        forward /= np.linalg.norm(forward)
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        right = np.cross(forward, world_up)
        norm = np.linalg.norm(right)
        if norm < 1e-8:
            right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        else:
            right /= norm
        up = np.cross(right, forward)
        return forward, right, up

    def view_matrix(self) -> np.ndarray:
        """4×4 视图矩阵（行主序）。"""
        eye = self.eye()
        fwd, right, up = self._basis()
        m = np.eye(4, dtype=np.float32)
        m[0, :3] = right
        m[1, :3] = up
        m[2, :3] = -fwd
        m[0, 3] = -np.dot(right, eye)
        m[1, 3] = -np.dot(up, eye)
        m[2, 3] = np.dot(fwd, eye)
        return m

    def projection_matrix(self, aspect: float) -> np.ndarray:
        """4×4 透视投影矩阵（行主序，右手系）。"""
        f = 1.0 / np.tan(np.radians(self.fov) / 2.0)
        n, fa = self.near, self.far
        m = np.zeros((4, 4), dtype=np.float32)
        m[0, 0] = f / max(aspect, 1e-6)
        m[1, 1] = f
        m[2, 2] = (fa + n) / (n - fa)
        m[2, 3] = 2.0 * fa * n / (n - fa)
        m[3, 2] = -1.0
        return m

    def model_matrix(self, scale: float = 1.0, center: np.ndarray | None = None) -> np.ndarray:
        """模型矩阵：缩放到以 target 为中心。"""
        m = np.eye(4, dtype=np.float32)
        if center is not None:
            m[0, 3] = -center[0]
            m[1, 3] = -center[1]
            m[2, 3] = -center[2]
        s = np.diag([scale, scale, scale, 1.0]).astype(np.float32)
        return s @ m

    # ── 交互 ────────────────────────────────────────────

    def rotate(self, dyaw_deg: float, dpitch_deg: float):
        self.yaw = (self.yaw + dyaw_deg) % 360.0
        self.pitch = float(np.clip(self.pitch + dpitch_deg, -89.0, 89.0))

    def zoom(self, factor: float):
        self.distance = float(np.clip(self.distance * factor, self._min_dist, self._max_dist))

    def zoom_to(self, distance: float):
        self.distance = float(np.clip(distance, self._min_dist, self._max_dist))

    def pan(self, dx_px: float, dy_px: float, viewport_h: float):
        """按屏幕像素平移 target。"""
        if viewport_h <= 0:
            return
        world_per_px = 2.0 * self.distance * np.tan(np.radians(self.fov) / 2.0) / viewport_h
        fwd, right, up = self._basis()
        self.target = self.target + (-right * dx_px + up * dy_px) * world_per_px

    def frame(self, center: np.ndarray, size: np.ndarray, viewport_w: float, viewport_h: float):
        """自动取景：按当前视角方向把轴对齐包围盒的 8 角精确框进视野（2D 投影）。

        相比按包围球半径取景，对长条形舰船能显著放大（避免船体只占画面一小条）。
        """
        self.target = center.astype(np.float32)
        half = np.asarray(size, dtype=np.float32) * 0.5
        fwd, right, up = self._basis()

        offsets = np.array([
            [sx * half[0], sy * half[1], sz * half[2]]
            for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)
        ], dtype=np.float32)

        aspect = viewport_w / max(viewport_h, 1)
        tan_h = np.tan(np.radians(self.fov / 2.0)) * aspect
        tan_v = np.tan(np.radians(self.fov / 2.0))

        # 相机空间横向/纵向半宽与深度（沿视线分量）
        x_ext = np.abs(offsets @ right)
        y_ext = np.abs(offsets @ up)
        z_ext = offsets @ fwd  # 沿视线，可正可负

        # 保证角点落在视锥内：|x| / ((d - z) * tan) <= 1  ⇒  d >= |x|/tan + z
        dist_x = (x_ext / max(tan_h, 1e-6) + z_ext).max()
        dist_y = (y_ext / max(tan_v, 1e-6) + z_ext).max()
        dist = max(dist_x, dist_y, 0.5) * 1.12
        self.zoom_to(float(dist))
