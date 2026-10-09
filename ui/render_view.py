"""ui.render_view —— 承载 D3D11 渲染面的 QWidget（替代原 ``GeometryViewport``）。

分工（见 ``todo_list/New_function_of_d3d11_renderer.md`` §8.1）：

- Qt 负责：窗口句柄、尺寸/DPI 变化、输入事件、布局；
- DLL 负责：Device / SwapChain / 每帧绘制；
- 本控件**不**在 Qt 绘制路径里做 D3D 呈现，帧驱动交给 ``QTimer``。

P0 说明：内容仍是最小三角形，仅用于验证 DLL 加载、交换链呈现、resize、DPI
与设备丢失恢复。P1+ 由 ``renderer/scene.py`` 接管场景内容。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPaintEngine
from PySide6.QtWidgets import QLabel, QWidget

from models.camera import OrbitCamera
from app.signals import bus
from utils.mem_info import memory_suffix
from renderer import Renderer, RendererError, RendererUnavailable
from renderer.viewport import FrameState, RenderScene, to_d3d_projection

__all__ = ["RenderView"]


class RenderView(QWidget):
    """D3D11 渲染面。

    生命周期要点：

    - 渲染器**必须在** ``showEvent`` 之后创建（此时 ``winId()`` 才对应真实 HWND）；
    - 关闭时先停定时器、再 ``destroy()``，否则会掉进「窗口已销毁 + 设备仍在」的崩溃；
    - DLL 不可用时进入降级状态（画提示文字 + 发 :attr:`failed` 信号），不抛异常穿透事件循环。

    :param fps: 帧率上限。
    :param dpi_aware: 是否按 ``devicePixelRatio`` 换算后备缓冲尺寸。
    :param no_vsync: 关闭垂直同步（压测用）。
    :param legacy_bitblt: 使用 ``DXGI_SWAP_EFFECT_DISCARD``（层叠/闪烁时的降级路径）。
    """

    #: 后端不可用或运行期失败时发出（参数为可展示的错误文本）。
    failed = Signal(str)

    #: 场景「上传到 GPU」进度文本（空串 = 已结束，上层据此隐藏进度遮罩）。
    scene_progress = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        fps: int = 60,
        dpi_aware: bool = True,
        no_vsync: bool = False,
        legacy_bitblt: bool = False,
        deferred: bool = True,
    ) -> None:
        super().__init__(parent)

        # 必须有真实 HWND，且不让 Qt 擦背景（避免与交换链呈现互相闪烁）
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_PaintOnScreen, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.StrongFocus)

        self._renderer: Renderer | None = None
        self._error: str = ""
        self._dpi_aware = dpi_aware
        self._no_vsync = no_vsync
        self._legacy_bitblt = legacy_bitblt
        self._deferred = deferred

        # 降级提示（仅在 DLL 不可用/运行期失败时显示）。
        # 用子控件而不是 QPainter：本控件重写了 paintEngine 返回 None（不让 Qt 绘制），
        # 因此自身 paintEvent 无法用于绘制内容。
        self._error_label = QLabel(self)
        self._error_label.setWordWrap(True)
        self._error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._error_label.setStyleSheet(
            "color:#e6b0b0; background:#1b1e24; padding:12px; font-family:Consolas,monospace;"
        )
        self._error_label.hide()

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(1000 / max(1, int(fps)))))
        self._timer.timeout.connect(self._on_tick)
        # 上传进度日志节流状态
        self._upload_log_pct = -10
        self._upload_log_t = 0.0

        # 相机 / 场景 / 帧参数（相机状态留在 Python，见架构文档 §8.2）
        self._camera = OrbitCamera()
        self._frame = FrameState()
        self._scene: RenderScene | None = None
        self._geometry = None
        self._armor_scene = None
        self._last_mouse = None
        self._view_opts: dict = {
            "show_hull": True,
            "show_mounts": True,
            "show_armor": False,
            "wireframe": False,
            "show_edges": True,
            "armor_opacity": 0.45,
        }

    # ---------------------------------------------------------------- 状态

    @property
    def renderer(self) -> Renderer | None:
        """当前渲染器实例；未创建或已失败时为 ``None``。"""
        return self._renderer

    @property
    def last_error(self) -> str:
        return self._error

    def stats(self):
        """返回 :class:`renderer.Stats`；无渲染器时为 ``None``。"""
        return self._renderer.stats() if self._renderer is not None else None

    def simulate_device_lost(self) -> None:
        """请求模拟一次设备丢失（P0 验收 / 健壮性测试）。"""
        if self._renderer is not None:
            self._renderer.debug_simulate_device_lost()

    # ---------------------------------------------------------------- Qt 事件

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(640, 480)

    def paintEngine(self) -> QPaintEngine | None:  # noqa: N802
        """本控件由 D3D 独占呈现，不参与 Qt 绘制管线（避免 paintEngine 警告）。"""
        return None

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_renderer()
        if self._renderer is not None and not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        # 隐藏时停帧（避免在不可见窗口上继续 Present）；重新显示会在 showEvent 恢复
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._error_label.setGeometry(self.rect())
        if self._renderer is None:
            return
        try:
            self._renderer.set_dpi_scale(self._dpr())
            self._renderer.resize(max(1, self.width()), max(1, self.height()))
        except RendererError as exc:
            self._fail(str(exc))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.shutdown()
        super().closeEvent(event)

    # ---------------------------------------------------------------- 内部

    # ---------------------------------------------------------------- 场景 API

    def set_ship(self, geometry, armor_scene=None) -> None:
        """载入一脠舰船（几何 + 可选装甲场景），并自动取景。"""
        self._geometry = geometry
        self._armor_scene = armor_scene
        center = getattr(geometry, "bounds_center", None) if geometry is not None else None
        self._frame.scene_center = (
            None if center is None else np.asarray(center, dtype=np.float32)
        )
        if self._renderer is not None:
            self._submit_scene()
            self.frame_camera()

    def clear_scene(self) -> None:
        self._geometry = None
        self._armor_scene = None
        self._frame.scene_center = None
        if self._scene is not None:
            try:
                self._scene.clear()
            except RendererError:
                pass

    def set_view_options(self, **options) -> None:
        """更新显示选项（show_hull / show_mounts / show_armor / wireframe / show_edges / armor_opacity）。"""
        for key, value in options.items():
            if value is not None:
                self._view_opts[key] = value
        self._apply_view_options()

    def frame_camera(self) -> None:
        """按包围盒重新取景（与旧查看器的 AABB 精确框选一致）。"""
        g = self._geometry
        center = getattr(g, "bounds_center", None) if g is not None else None
        size = getattr(g, "bounds_size", None) if g is not None else None
        if center is None or size is None:
            return
        self._camera.frame(
            np.asarray(center, dtype=np.float32),
            np.asarray(size, dtype=np.float32),
            float(max(1, self.width())),
            float(max(1, self.height())),
        )

    def set_debug_mode(self, mode: int) -> None:
        self._frame.debug_mode = int(mode)

    @property
    def camera(self) -> OrbitCamera:
        return self._camera

    # ---------------------------------------------------------------- 交互

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._last_mouse = event.position()
        self.setFocus()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last_mouse is None or self._renderer is None:
            return
        pos = event.position()
        dx = pos.x() - self._last_mouse.x()
        dy = pos.y() - self._last_mouse.y()
        self._last_mouse = pos
        buttons = event.buttons()
        if buttons & Qt.LeftButton:
            self._camera.rotate(-dx * 0.4, dy * 0.4)
        elif buttons & (Qt.MiddleButton | Qt.RightButton):
            self._camera.pan(dx, dy, float(max(1, self.height())))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._last_mouse = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self._camera.zoom(0.9 if delta > 0 else 1.1)

    def shutdown(self) -> None:
        """停止帧驱动并释放渲染器（幂等，可在 close 前重复调用）。"""
        self._timer.stop()
        if self._renderer is not None:
            try:
                self._renderer.destroy()
            except Exception:  # pragma: no cover - 关闭路径不抛
                pass
            finally:
                self._renderer = None

    def _dpr(self) -> float:
        if not self._dpi_aware:
            return 1.0
        try:
            return float(self.devicePixelRatioF())
        except Exception:  # pragma: no cover
            return 1.0

    def _ensure_renderer(self) -> None:
        if self._renderer is not None:
            return
        try:
            self._renderer = Renderer(
                int(self.winId()),
                max(1, self.width()),
                max(1, self.height()),
                dpi_scale=self._dpr(),
                no_vsync=self._no_vsync,
                legacy_bitblt=self._legacy_bitblt,
                deferred=self._deferred,
            )
        except (RendererUnavailable, RendererError) as exc:
            self._fail(str(exc))
            return
        self._error = ""
        self._scene = RenderScene(self._renderer)
        self._scene.on_progress = self._on_scene_progress
        self._scene.on_slow = self._on_scene_slow
        if self._geometry is not None:
            self._submit_scene()

    def _submit_scene(self) -> None:
        """登记待提交场景（真正上传由 tick 分片完成，避免主线程被长时间占住）。"""
        if self._renderer is None or self._scene is None:
            return
        self._scene.set_scene(self._geometry, self._armor_scene)
        self._apply_view_options()

    def _on_scene_slow(self, what: str, seconds: float) -> None:
        """单项上传超 0.3s 时当场记一条（不等提交结束，便于定位卡点）。"""
        bus.log_message.emit(f"⏱️ 3D 慢项: {what} {seconds:.2f}s")

    def _on_scene_progress(self, stage: str, done: int, total: int, elapsed: float) -> None:
        """增量上传统计 → 信号给上层（GUI 显示进度）+ 日志（便于只读日志定位慢点）。"""
        if stage == "done":
            self.scene_progress.emit("")
            self._upload_log_pct = -10
            self._upload_log_t = 0.0
            if self._scene is not None and (self._scene.texture_count or self._scene.mesh_count):
                bus.log_message.emit(
                    f"⏱️ 3D: 场景已上传到 GPU —— 纹理 {self._scene.texture_count} 张"
                    f"（{self._scene.last_tex_seconds:.2f}s）/ 网格 {self._scene.mesh_count} 个"
                    f"（{self._scene.last_mesh_seconds:.2f}s），场景描述"
                    f" {self._scene.texture_bytes / 1e6:.0f}MB + "
                    f"{self._scene.mesh_bytes / 1e6:.0f}MB" + memory_suffix())
            return
        if total <= 0:
            return
        pct = int(done * 100 / total)
        # 进度日志节流：每 +10% 或每 3 秒一条（避免刷屏）
        if pct - self._upload_log_pct >= 10 or elapsed - self._upload_log_t >= 3.0:
            self._upload_log_pct = pct
            self._upload_log_t = elapsed
            bus.log_message.emit(f"⏱️ 3D: 上传到 GPU {done}/{total}（{pct}%，{elapsed:.1f}s）")
        self.scene_progress.emit(f"正在上传到 GPU... {done}/{total}（{pct}%）")

    def _apply_view_options(self) -> None:
        if self._renderer is None:
            return
        opts = dict(self._view_opts)
        if opts.get("show_armor"):
            # 船体/装甲互斥（与旧查看器行为一致）
            opts["show_hull"] = False
            opts["show_mounts"] = False
        try:
            self._renderer.set_view_options(**opts)
        except RendererError as exc:
            self._fail(str(exc))

    def _push_frame(self) -> None:
        """上传相机与光照参数（每帧）。"""
        if self._renderer is None:
            return
        cam = self._camera
        radius = self._scene_radius()
        cam.near = max(cam.distance - radius * 2.0, 0.05)
        cam.far = cam.distance + radius * 4.0
        aspect = max(1, self.width()) / max(1, self.height())
        view = cam.view_matrix()
        proj = to_d3d_projection(cam.projection_matrix(aspect))
        self._renderer.set_frame(
            view,
            proj,
            light_pos=self._frame.light_pos(),
            light_dir=self._frame.light_dir,
            ambient=self._frame.ambient,
            normal_strength=self._frame.normal_strength,
            opacity=self._frame.opacity,
            debug_mode=self._frame.debug_mode,
            lighting_mode=self._frame.lighting_mode,
            normal_space=self._frame.normal_space,
            env_strength=self._frame.env_strength,
            exposure=self._frame.exposure,
            uv_flip=self._frame.uv_flip,
            camera_pos=(float(cam.eye()[0]), float(cam.eye()[1]), float(cam.eye()[2])),
        )

    def _scene_radius(self) -> float:
        g = self._geometry
        size = getattr(g, "bounds_size", None) if g is not None else None
        if size is None:
            return 1.0
        return max(float(np.linalg.norm(np.asarray(size, dtype=np.float32))) * 0.5, 0.05)

    def _on_tick(self) -> None:
        if self._renderer is None:
            return
        try:
            if self._scene is not None:
                # 分片上传（每片最多 ~8ms），保证 tick 间隔内 GUI 仍能刷新
                self._scene.submit_if_needed(budget_ms=8.0)
            self._push_frame()
            self._renderer.render()
        except RendererError as exc:
            self._fail(str(exc))

    def _fail(self, message: str) -> None:
        self._error = message
        self.shutdown()
        # 进入降级：允许 Qt 常规绘制，好让提示可见
        self.setAttribute(Qt.WA_PaintOnScreen, False)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self._error_label.setText(message)
        self._error_label.setGeometry(self.rect())
        self._error_label.show()
        self.failed.emit(message)
