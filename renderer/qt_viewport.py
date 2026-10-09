"""renderer.qt_viewport —— D3D11 渲染控件的**旧接口适配层**。

目的（架构文档 §8.4）：让 `ui/geometry_viewer.py` 以最小改动从
``GeometryViewport(QOpenGLWidget)`` 切到 D3D11 渲染面 —— 保持同名方法/属性，
内部翻译成 :class:`renderer.api.Renderer` 的调用。

尚未实现的功能不静默失败：记录到 :attr:`D3DViewportAdapter.unsupported`
并在 :meth:`D3DViewportAdapter.unsupported_summary` 中汇总，调用方可提示用户
（``ui/geometry_viewer.py`` 会把汇总写入日志面板一次）。

启用方式（由 ``ui.geometry_viewer.resolve_viewport_backend`` 判定）：

- **源码模式默认启用**（``python main.py``；DLL 缺失时自动回退 OpenGL 并提示）；
- 环境变量 ``WSR_USE_D3D_VIEWER=1`` / ``=0`` 可强制开启 / 关闭；
- 发布版 exe 默认仍走旧 OpenGL 路径。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QColor

from ui.render_view import RenderView

from .types import MESH_ARMOR

#: 与旧渲染器一致的常量
HIGHLIGHT_HOVER = (0.0, 0.9, 1.0, 0.5)
HIGHLIGHT_SELECT = (1.0, 0.6, 0.1, 0.6)


class D3DViewportAdapter(RenderView):
    """提供旧 ``GeometryViewport`` 的方法面，内部走 D3D11 后端。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, fps=60)
        # 旧查看器会直接读写这些属性
        self._hover_tri = None
        self._selected_plate = None
        self._hl_color = HIGHLIGHT_HOVER
        self._visible_tris = None
        self.on_hover = None
        self.on_select = None
        self.unsupported: list[str] = []
        self._armor_indices = None      # (T,3) 装甲三角形原始索引
        self._armor_mesh_key = "armor:scene"
        # 分片上传：途中设的装甲可见掩码会被 DLL 忽略（网格还没建）⇒ 传完再套一次
        self.scene_progress.connect(self._reapply_visible_tris)

    def _reapply_visible_tris(self, text: str) -> None:
        if text or self._visible_tris is None:
            return
        self.set_visible_tris(self._visible_tris)

    # ------------------------------------------------------------ 场景

    def set_scene(self, ship_geometry, show_hull: bool = True, show_armor: bool = True,
                  armor_scene=None) -> None:
        self._armor_indices = self._collect_armor_indices(armor_scene)
        self.set_ship(ship_geometry, armor_scene)
        self.set_view_options(show_hull=show_hull, show_armor=show_armor)

    def clear_scene(self) -> None:
        self._armor_indices = None
        super().clear_scene()

    @staticmethod
    def _collect_armor_indices(armor_scene):
        if armor_scene is None or not getattr(armor_scene, "tri_count", 0):
            return None
        return np.arange(int(armor_scene.tri_count) * 3, dtype=np.uint32)

    # ------------------------------------------------------------ 显示选项

    def set_view_options(self, show_hull=None, show_armor=None, wireframe=None,
                         show_mounts=None, armor_components=None, armor_types=None) -> None:
        if armor_components is not None or armor_types is not None:
            self._note_unsupported("装甲按归属/类型过滤（armor_components/armor_types）")
        super().set_view_options(
            show_hull=show_hull, show_armor=show_armor,
            wireframe=wireframe, show_mounts=show_mounts,
        )

    def set_render_style(self, lighting_mode=None, *, normal_space=None, uv_flip=None,
                         env_strength=None, exposure=None) -> None:
        """切换渲染风格/开关（只改每帧参数，下一次 tick 生效，不重建场景）。

        - ``lighting_mode``：0 = 游戏原版着色，1 = Studio PBR（程序化环境 IBL + 曝光 + ACES）
        - ``normal_space``：0 = 切线空间法线直接当世界法线（原版行为），1 = 正确 TBN
        - ``uv_flip``：0 = 纹理 V 不翻转（默认，与 GL 参考一致），1 = 旧行为（翻转）
        - ``env_strength`` / ``exposure``：仅 Studio PBR 生效
        """
        frame = self._frame
        if lighting_mode is not None:
            frame.lighting_mode = int(lighting_mode)
        if normal_space is not None:
            frame.normal_space = int(normal_space)
        if uv_flip is not None:
            frame.uv_flip = int(uv_flip)
        if env_strength is not None:
            frame.env_strength = float(env_strength)
        if exposure is not None:
            frame.exposure = float(exposure)

    def set_armor_display(self, opacity=None, show_edges=None) -> None:
        super().set_view_options(
            armor_opacity=None if opacity is None else float(np.clip(opacity, 0.05, 1.0)),
            show_edges=show_edges,
        )
        # 边界线开关：直接控制边界线 mesh 的可见性
        renderer = self.renderer
        if renderer is not None and show_edges is not None:
            try:
                renderer.set_mesh_visible("armor:edges", bool(show_edges))
            except Exception:  # noqa: BLE001 - 无装甲场景时忽略
                pass

    def set_visible_tris(self, visible_tris) -> None:
        """装甲三角形可见掩码 → 重建装甲索引（(T,) bool；None = 全部）。"""
        self._visible_tris = visible_tris
        renderer = self.renderer
        if renderer is None or self._armor_indices is None:
            return
        if visible_tris is None:
            indices = self._armor_indices
        else:
            mask = np.asarray(visible_tris, dtype=bool)
            tri = self._armor_indices.reshape(-1, 3)
            if mask.shape[0] != tri.shape[0]:
                return
            indices = tri[mask].reshape(-1)
        try:
            renderer.set_mesh_indices(self._armor_mesh_key, indices)
        except Exception:  # noqa: BLE001
            pass

    def select_plate(self, plate_key) -> None:
        """板块高亮：D3D11 侧的独立高亮 pass 尚未接入（记录为不支持）。"""
        self._selected_plate = plate_key
        self._note_unsupported("选中板块高亮（select_plate）")

    # ------------------------------------------------------------ 拾取

    def pick_at(self, x: int, y: int):
        """3D 拾取：CPU 射线拾取尚未接入 D3D 路径（记录为不支持）。"""
        self._note_unsupported("3D 射线拾取（pick_at）")
        return None

    # ------------------------------------------------------------ 截图

    def _capture_png(self, path: str | None = None) -> QImage | None:
        """抓当前帧（走后端 BMP → QImage，避免依赖 GL）。"""
        renderer = self.renderer
        img: QImage | None = None
        if renderer is not None:
            import tempfile
            from pathlib import Path

            tmp = Path(tempfile.gettempdir()) / "wsr_capture.bmp"
            try:
                renderer.capture_bmp(str(tmp))
                img = QImage(str(tmp))
            except Exception:  # noqa: BLE001
                img = None
        if img is None:
            img = QImage(self.width(), self.height(), QImage.Format_RGB32)
            img.fill(QColor("#1b1e24"))
        if path:
            img.save(path)
        return img

    # ------------------------------------------------------------ 内部

    def _note_unsupported(self, what: str) -> None:
        if what not in self.unsupported:
            self.unsupported.append(what)

    def unsupported_summary(self) -> str:
        """返回尚未支持的功能列表（空字符串 = 全部支持）。"""
        if not self.unsupported:
            return ""
        return "D3D11 查看器尚未支持：" + "、".join(self.unsupported)

    # 旧查看器在 paintEvent 里可能调用 update()；QWidget 自带，无需覆写。
    def paintEngine(self):  # noqa: N802
        return None
