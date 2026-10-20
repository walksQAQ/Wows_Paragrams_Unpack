"""
model_file_viewer.py —— 独立几何模型文件查看器（几何 + 可选实时材质）。

与舰船 3D 查看器（``ui/geometry_viewer.py``）解耦：本工具不依赖 GameParams /
数据库，直接加载任意 ``.geometry`` 文件的网格并渲染，用于快速检查模型本身
是否正确。

两种来源：

- **本地磁盘**：选择任意 ``.geometry`` 文件；
- **游戏客户端**：枚举客户端 VFS 中的 ``.geometry`` 文件，搜索后直接读取。

渲染内容：

- 几何：始终加载（顶点/法线/UV/索引）；蒙皮网格按 bind pose 的原始顶点显示；
- 材质：**仅客户端来源**、且勾选「加载材质效果」时，按渲染集实时解析
  ``assets.bin`` 的 MaterialPrototype（mfm）并从 pkg 读取贴图，交由渲染器
  按 shader 技术族（PBS / INDEXED 分块 / 贴花 / 透明…）绘制；
  本地文件模式无法定位渲染集与材质，只能显示白模。
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from app.signals import bus
from models.geometry_parser import parse_geometry
from services.geometry_service import HullMesh, ShipGeometry
from ui.geometry_viewer import _Spinner, resolve_viewport_backend
from utils.threading_utils import run_async
from utils.theme import theme
from utils.window_utils import center_on_screen


#: 几何文件扩展名
GEOMETRY_SUFFIX = ".geometry"


@dataclass(frozen=True)
class VfsGeometryEntry:
    """游戏客户端 VFS 中的一个几何文件。"""
    path: str
    size: int          # 解压后大小（字节）
    volume: str        # 所在 .pkg 卷


def _ensure_normals(positions: np.ndarray, normals, indices) -> np.ndarray:
    """保证法线可用：文件缺法线（全零）时按面法线累加生成。

    部分几何格式（以及部分 misc 模型）不带法线或法线全零，直接渲染会因
    ``dot(N, L)`` 恒为 0 而接近全黑。这里检测到无效法线后用三角形面法线
    累加到顶点并归一化，保证几何能被看清。
    """
    pos = np.asarray(positions, dtype=np.float32)
    if normals is not None:
        nrm = np.asarray(normals, dtype=np.float32)
        if nrm.shape == pos.shape and pos.size:
            lengths = np.linalg.norm(nrm, axis=1)
            valid = int(np.count_nonzero(lengths > 0.5))
            if valid >= max(1, pos.shape[0] // 10):
                return np.ascontiguousarray(nrm)

    out = np.zeros_like(pos)
    idx = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    if idx.size:
        tri = pos[idx]
        face = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        for k in range(3):
            np.add.at(out, idx[:, k], face.astype(np.float32))
    length = np.linalg.norm(out, axis=1, keepdims=True)
    out /= np.maximum(length, 1e-12)
    return out


def _model_stem(file_path: str) -> str:
    """从 .geometry 路径取模型目录名（骨架/渲染集的 stem）。"""
    p = file_path.replace("\\", "/").rstrip("/")
    parts = p.split("/")
    return parts[-2] if len(parts) >= 2 else ""


def _attach_assets_live(parsed, geom_path: str, cancel_event=None) -> tuple[dict, dict]:
    """**实时从客户端 assets.bin** 读取渲染集（材质 / 蒙皮调色板）与骨架。

    - 渲染集：`GeometryService._section_render_sets` 直接解析 assets.bin
      （shape → material/mfm/skinned/nodes），不读 assets_data.db。
    - 骨架：`GeometryService.live_skeleton(stem)` 实时解码 SkeletonPrototype。
    - 对蒙皮 primitive 施加 bind pose 混合（原地），并填充 skin_bones/skin_bind。

    返回 ``(rs_by_mid, info)``；任何一步缺失都安全降级（不抛异常）。
    """
    info = {"source": "client", "materials": 0, "bones": 0,
            "skinned": 0, "applied": 0}
    rs_by_mid: dict = {}
    try:
        from services.geometry_service import GeometryService
        svc = GeometryService.instance()
        for rs in svc._section_render_sets(geom_path) or []:
            mid = svc._murmur3_32((rs.get("shape") or "").encode())
            rs_by_mid.setdefault(mid, rs)
        info["materials"] = len(rs_by_mid)
        stem = _model_stem(geom_path)
        bones = svc.live_skeleton(stem) if stem else {}
        info["bones"] = len(bones)
        if bones:
            svc._current_skinning_stem = stem
            # 供 _apply_skinning 使用实时骨架（避免它回退查 assets_data.db）
            svc._skeleton_bones_cache[stem] = bones
        for prim in parsed.primitives:
            if cancel_event is not None and cancel_event.is_set():
                break
            entry = rs_by_mid.get(prim.mapping_id)
            if entry is None:
                continue
            if not getattr(prim, "is_skinned", False) or prim.bone_indices is None:
                continue
            if not entry.get("skinned") or not bones:
                continue
            info["skinned"] += 1
            if svc._apply_skinning(prim, entry):
                info["applied"] += 1
        if info["skinned"]:
            bus.log_message.emit(
                f"ℹ️ 模型文件查看器：assets.bin 实时骨架 {stem}"
                f"（{info['bones']} 骨骼 / 渲染集 {info['materials']}），"
                f"bind pose 混合 {info['applied']}/{info['skinned']}")
    except Exception as exc:  # noqa: BLE001
        bus.log_message.emit(f"⚠️ 模型文件查看器：assets.bin 实时读取失败: {exc}")
    return rs_by_mid, info


def _shape_stem(entry) -> str:
    """渲染集的 shape 名（`TurretShape.vertices` → `TurretShape`），无则空串。"""
    name = str((entry or {}).get("shape") or "")
    return name[:-len(".vertices")] if name.endswith(".vertices") else name


def _bound_node(entry) -> str:
    """渲染集绑定的 visual 节点名（第一个），无则空串。"""
    nodes = (entry or {}).get("nodes") or []
    return str(nodes[0]) if nodes else ""


def geometry_from_parsed(name: str, parsed, file_path: str = "",
                         cancel_event=None, source: str = "client",
                         load_materials: bool = True) -> ShipGeometry:
    """把 parse_geometry 的结果包装成视口可直接渲染的 ShipGeometry。

    未加载到材质的网格保持 ``has_color=True`` + 无贴图 → 渲染器走普通光照
    实体分支（白模），不会被误当成法线叠加层。

    source：
      - ``"client"``：模型来自游戏客户端。实时解析 assets.bin 获取
        渲染集（材质/mfm/蒙皮调色板）与骨架，保留顶点组/权重并施加 bind pose。
      - ``"local"``：直接读取本地文件。**不含顶点组/权重与材质数据**
        （无法可靠定位客户端资产），并在 stats 中给出提示。

    load_materials：仅对 ``"client"`` 有效。为 True 时按渲染集的 mfm 实时
    解析材质（贴图 / INDEXED 分块参数 / 技术族）；为 False 则只显示白模。
    """
    if source == "client":
        rs_by_mid, sk_info = _attach_assets_live(parsed, file_path, cancel_event)
        drop_skin = False
        sk_info["textured"] = 0
        sk_info["materialized"] = 0
    else:
        rs_by_mid = {}
        sk_info = {"source": "local", "materials": 0, "bones": 0,
                   "skinned": 0, "applied": 0, "textured": 0,
                   "materialized": 0}
        drop_skin = True
    svc = None
    extractor = None
    if source == "client" and load_materials:
        try:
            from services.geometry_service import GeometryService
            svc = GeometryService.instance()
            extractor = svc.get_extractor()
        except Exception as exc:  # noqa: BLE001
            svc = None
            bus.log_message.emit(f"⚠️ 模型文件查看器：材质加载不可用: {exc}")
    geom = ShipGeometry(game_key=name, display_name=name, model_folder="")
    skipped = 0
    for i, prim in enumerate(parsed.primitives):
        indices = prim.indices
        positions = np.asarray(prim.positions, dtype=np.float32)
        if indices is None or indices.size < 3 or positions.size == 0:
            skipped += 1
            continue
        normals = _ensure_normals(positions, prim.normals, indices)
        entry = rs_by_mid.get(prim.mapping_id)
        hm = HullMesh(
            name=f"{name}#{i}",
            positions=positions,
            normals=normals,
            indices=np.ascontiguousarray(indices, dtype=np.uint32),
            # 无材质渲染不使用 UV，但保留导出（GLB TEXCOORD_0）供外部工具使用
            uvs=(None if prim.uvs is None
                 else np.ascontiguousarray(prim.uvs, dtype=np.float32)),
            # 完整保留其余顶点属性：第二套 UV / 切线副切线 / r 属性
            uv2=(None if prim.uv2 is None
                 else np.ascontiguousarray(prim.uv2, dtype=np.float32)),
            tangents=(None if prim.tangents is None
                      else np.ascontiguousarray(prim.tangents, dtype=np.float32)),
            binormals=(None if prim.binormals is None
                       else np.ascontiguousarray(prim.binormals, dtype=np.float32)),
            t4=(None if prim.t4 is None
                else np.ascontiguousarray(prim.t4, dtype=np.uint8)),
            extra=(None if prim.extra is None
                   else np.ascontiguousarray(prim.extra, dtype=np.uint8)),
            vertex_count=int(positions.shape[0]),
            has_color=True,
            tech_family="pbs",
            # 渲染集元数据（assets.bin 实时）；有材质时下方 apply_live_material
            # 会覆盖 texture_path / tech_family / has_color 并填好贴图与分块参数
            material=((entry or {}).get("material") or None),
            texture_path=((entry or {}).get("mfm") or ""),
            # 客户端模式：完整保留顶点组/权重 + skin；
            # 本地模式：明确不含顶点组/权重（无法可靠定位客户端资产）
            bone_indices=(None if drop_skin or prim.bone_indices is None
                          else prim.bone_indices.copy()),
            bone_weights=(None if drop_skin or prim.bone_weights is None
                          else prim.bone_weights.copy()),
            skin_bones=([] if drop_skin
                        else list(getattr(prim, "skin_bones", []) or [])),
            skin_bind=([] if drop_skin
                       else list(getattr(prim, "skin_bind", []) or [])),
            # 单 primitive 网格 → 一个 shape 切片：导出时网格名 = visual 的 Shape 名
            shape_names=[_shape_stem(entry)] if _shape_stem(entry) else [],
            node_names=[_bound_node(entry)] if _bound_node(entry) else [],
            shape_spans=(
                [(_shape_stem(entry), _bound_node(entry), 0,
                  int(positions.shape[0]), 0, int(indices.size))]
                if _shape_stem(entry) else []),
        )
        if svc is not None and entry is not None and entry.get("mfm"):
            try:
                if svc.apply_live_material(hm, entry.get("mfm") or "", extractor):
                    sk_info["textured"] += 1
                sk_info["materialized"] += 1
            except Exception as exc:  # noqa: BLE001
                bus.log_message.emit(
                    f"⚠️ 模型文件查看器：材质装配失败({entry.get('mfm')}): {exc}")
        geom.hull_meshes.append(hm)
    if not geom.hull_meshes:
        raise ValueError("文件中没有可渲染的三角形网格")
    mins = np.min([h.positions.min(axis=0) for h in geom.hull_meshes], axis=0)
    maxs = np.max([h.positions.max(axis=0) for h in geom.hull_meshes], axis=0)
    geom.bounds_min = mins.astype(np.float32)
    geom.bounds_max = maxs.astype(np.float32)
    note = ""
    if drop_skin:
        note = "本地文件模式：无法加载顶点组/权重与材质数据"
    elif not load_materials:
        note = "已关闭材质加载（白模显示）"
    geom.stats = {"file_path": file_path, "skipped_primitives": skipped,
                  "skeleton": sk_info, "source": source,
                  "load_materials": bool(load_materials and not drop_skin),
                  "note": note}
    return geom


def _collect_vfs_geometry(extractor) -> list[VfsGeometryEntry]:
    """枚举客户端文件树中的全部 ``.geometry`` 文件（仅文件条目）。"""
    out: list[VfsGeometryEntry] = []
    for path, entry in extractor.file_tree.items():
        if entry.is_directory or entry.file_info is None or entry.volume is None:
            continue
        if not path.lower().endswith(GEOMETRY_SUFFIX):
            continue
        out.append(VfsGeometryEntry(
            path=path,
            size=int(entry.file_info.unpacked_size),
            volume=entry.volume.filename,
        ))
    out.sort(key=lambda e: e.path.lower())
    return out


def _human_size(n: int) -> str:
    value = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} GB"


class GeometryFilePicker(QDialog):
    """客户端 VFS 几何文件选择框（搜索 + 列表）。"""

    def __init__(self, entries: list[VfsGeometryEntry], parent=None):
        super().__init__(parent)
        self.setWindowTitle("从游戏客户端选择模型文件")
        self.resize(860, 620)
        self._entries = entries

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索路径 / 模型名（如 playable/ship、misc、JSB018）...")
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        root.addLayout(row)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setWordWrap(False)
        theme.bind(self.list,
                   "QListWidget { background:@input_bg@; color:@text@;"
                   " border:1px solid @border@; border-radius:4px; font-size:12px; }")
        root.addWidget(self.list, stretch=1)

        self.count_label = QLabel()
        theme.bind(self.count_label,
                   "color:@text_muted@; font-size:11px; background:transparent; border:none;")
        root.addWidget(self.count_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_ok = QPushButton("加载")
        theme.bind(self.btn_cancel,
                   "QPushButton { background:@toolbar_btn_bg@; color:@toolbar_btn_text@;"
                   " border:1px solid @toolbar_btn_border@; border-radius:4px; padding:5px 14px; }")
        theme.bind(self.btn_ok,
                   "QPushButton { background:@toolbar_btn_bg@; color:@toolbar_btn_text@;"
                   " border:1px solid @toolbar_btn_border@; border-radius:4px; padding:5px 14px; }")
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        root.addLayout(btn_row)

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._apply_filter)

        self.search.textChanged.connect(lambda _: self._filter_timer.start())
        self.search.returnPressed.connect(self._accept_if_possible)
        self.list.itemDoubleClicked.connect(lambda _: self._accept_if_possible())
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._accept_if_possible)

        self._populate()
        self.search.setFocus()

    def _populate(self) -> None:
        self.list.setUpdatesEnabled(False)
        try:
            for entry in self._entries:
                item = QListWidgetItem(f"{entry.path}    [{_human_size(entry.size)}]")
                item.setData(Qt.UserRole, entry.path)
                item.setToolTip(f"{entry.path}\n{_human_size(entry.size)}  ({entry.volume})")
                self.list.addItem(item)
        finally:
            self.list.setUpdatesEnabled(True)
        self.count_label.setText(f"共 {len(self._entries):,} 个 .geometry 文件")
        if self.list.count():
            self.list.setCurrentRow(0)

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        shown = 0
        first_visible = -1
        for i in range(self.list.count()):
            item = self.list.item(i)
            hidden = bool(text) and text not in item.data(Qt.UserRole).lower()
            item.setHidden(hidden)
            if not hidden:
                shown += 1
                if first_visible < 0:
                    first_visible = i
        self.count_label.setText(
            f"共 {self.list.count():,} 个 .geometry 文件，匹配 {shown:,} 个")
        if shown and (self.list.currentRow() < 0 or self.list.currentItem().isHidden()):
            self.list.setCurrentRow(first_visible)

    def _accept_if_possible(self) -> None:
        if self.selected_path():
            self.accept()

    def selected_path(self) -> str:
        item = self.list.currentItem()
        if item is None or item.isHidden():
            # 过滤后当前项不可见时，取第一个可见项
            for i in range(self.list.count()):
                if not self.list.item(i).isHidden():
                    return self.list.item(i).data(Qt.UserRole)
            return ""
        return item.data(Qt.UserRole) or ""


class ModelFileViewerDialog(QDialog):
    """独立几何模型查看器（客户端来源可加载实时材质）。"""

    #: 后台加载进度提示（文本；空串 = 结束）
    busy_changed = Signal(str)
    #: 后台导出进度（0..100, 消息）→ 主线程更新导出进度条
    export_progress_changed = Signal(float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模型文件查看器")
        self.resize(1240, 820)
        self.setMinimumSize(760, 520)

        self._settings = QSettings("walksQAQ", "WowsParagrams")
        self._closed = False
        self._load_gen = 0
        self._load_task = None
        self._vfs_task = None
        self._current_name = "model"
        #: 导出状态（后台只读几何，不触碰 Qt/OpenGL）
        self._exporting = False
        self._export_task = None
        self.export_progress_changed.connect(self._on_export_progress)
        self._vfs_entries: list[VfsGeometryEntry] | None = None
        self._current_geom: ShipGeometry | None = None
        #: 当前模型的来源（client/local）与 VFS 路径（材质开关切换时重载用）
        self._current_source = ""
        self._current_vfs_path = ""

        self._build_ui()
        theme.bind(self, "QDialog { background: @panel_bg@; }")
        self._restore_geometry()

        # 后台任务经信号回到主线程更新遮罩
        self.busy_changed.connect(self._on_busy_changed)
        # 服务器 / 游戏目录变化：客户端文件索引缓存失效
        bus.wows_type_changed.connect(self._on_env_changed)
        bus.game_path_changed.connect(self._on_env_changed)

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        body = QHBoxLayout()
        body.setSpacing(8)
        root.addLayout(body, stretch=1)

        # 左侧：3D 视口 + 加载遮罩
        self._backend, self._backend_note = resolve_viewport_backend()
        if self._backend == "d3d":
            from renderer.qt_viewport import D3DViewportAdapter
            self.viewport = D3DViewportAdapter()
        else:
            from ui.geometry_renderer import GeometryViewport
            self.viewport = GeometryViewport()
        theme.bind(self.viewport,
                   "QOpenGLWidget { background:#16181d; border:1px solid @border@;"
                   " border-radius:6px; }")

        self.view_container = QWidget()
        grid = QGridLayout(self.view_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.viewport, 0, 0)

        self.loading_overlay = QWidget(self.view_container)
        self.loading_overlay.setObjectName("loadingOverlay")
        self.loading_overlay.setVisible(False)
        self.loading_overlay.setStyleSheet(
            "QWidget#loadingOverlay { background: rgba(10,12,16,196); border-radius:6px; }")
        overlay_layout = QVBoxLayout(self.loading_overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)
        self.spinner = _Spinner(size=56)
        overlay_layout.addWidget(self.spinner, 0, Qt.AlignCenter)
        self.loading_label = QLabel("正在加载模型...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setWordWrap(True)
        self.loading_label.setStyleSheet(
            "color:#f2f5f9; font-size:13px; font-weight:600; background:rgba(0,0,0,120);"
            "border-radius:6px; padding:5px 12px;")
        overlay_layout.addWidget(self.loading_label, 0, Qt.AlignCenter)
        grid.addWidget(self.loading_overlay, 0, 0)
        body.addWidget(self.view_container, stretch=1)

        # 右侧控制面板
        panel = QWidget()
        panel.setFixedWidth(320)
        theme.bind(panel, "QWidget { background: @panel_bg@; }")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)

        title = QLabel("模型文件查看器")
        theme.bind(title,
                   "font-size:15px; font-weight:bold; color:@text@;"
                   " background:transparent; border:none;")
        pl.addWidget(title)

        hint = QLabel("独立加载任意 .geometry 模型；从客户端选择时可实时加载材质与骨架。")
        hint.setWordWrap(True)
        theme.bind(hint,
                   "color:@text_muted@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(hint)

        btn_style = ("QPushButton { background:@toolbar_btn_bg@; color:@toolbar_btn_text@;"
                     " border:1px solid @toolbar_btn_border@; border-radius:4px;"
                     " padding:6px 10px; font-size:12px; }")

        self.btn_local = QPushButton("打开本地模型文件...")
        self.btn_game = QPushButton("从游戏客户端选择...")
        for b in (self.btn_local, self.btn_game):
            theme.bind(b, btn_style)
            pl.addWidget(b)

        sec_style = ("color:@text_muted@; font-size:11px; font-weight:bold;"
                     " background:transparent; border:none; padding-top:6px;")
        self._add_section_title(pl, "当前模型", sec_style)
        self.info_label = QLabel("未加载模型")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignTop)
        theme.bind(self.info_label,
                   "color:@text@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(self.info_label)

        self._add_section_title(pl, "显示", sec_style)
        self.cb_wire = QCheckBox("线框叠加")
        self.cb_wire.setChecked(False)
        theme.bind(self.cb_wire,
                   "QCheckBox { color:@text@; font-size:12px; spacing:6px; }")
        pl.addWidget(self.cb_wire)

        self.cb_material = QCheckBox("加载材质效果")
        self.cb_material.setChecked(
            str(self._settings.value("model_file_viewer_load_materials", "true"))
            .lower() not in ("false", "0"))
        self.cb_material.setToolTip(
            "仅对『从游戏客户端选择』加载的模型生效（实时解析 assets.bin 材质 +\n"
            "从 pkg 读取贴图）；本地文件无法定位材质，始终为白模。\n"
            "当前是客户端模型时会立即重新加载。")
        theme.bind(self.cb_material,
                   "QCheckBox { color:@text@; font-size:12px; spacing:6px; }")
        self.cb_material.toggled.connect(self._on_material_toggled)
        pl.addWidget(self.cb_material)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(14)
        theme.bind(self.progress,
                   "QProgressBar { border:1px solid #0078d4; border-radius:4px;"
                   " background:@input_bg@; text-align:center; color:@text@; }"
                   "QProgressBar::chunk { background:#0078d4; }")
        pl.addWidget(self.progress)

        # ── 导出（纯几何 GLB：保留 UV，不含材质/贴图）──
        self._add_section_title(pl, "导出", sec_style)
        self.btn_export = QPushButton("导出 GLB...")
        theme.bind(self.btn_export, btn_style)
        pl.addWidget(self.btn_export)
        self.export_progress = QProgressBar()
        self.export_progress.setVisible(False)
        self.export_progress.setFixedHeight(14)
        theme.bind(self.export_progress,
                   "QProgressBar { border:1px solid #0078d4; border-radius:4px;"
                   " background:@input_bg@; text-align:center; color:@text@; }"
                   "QProgressBar::chunk { background:#0078d4; }")
        pl.addWidget(self.export_progress)
        self.export_status = QLabel("导出为 glTF 2.0 Binary（含 UV，不含材质/贴图）")
        self.export_status.setWordWrap(True)
        theme.bind(self.export_status,
                   "color:@text_hint@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(self.export_status)

        pl.addStretch(1)

        op_hint = QLabel("左键拖拽：旋转　滚轮：缩放　右键拖拽：平移")
        op_hint.setWordWrap(True)
        theme.bind(op_hint,
                   "color:@text_hint@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(op_hint)

        body.addWidget(panel)

        self.btn_local.clicked.connect(self._open_local)
        self.btn_game.clicked.connect(self._pick_from_game)
        self.btn_export.clicked.connect(self._start_export)
        self.cb_wire.toggled.connect(
            lambda v: self.viewport.set_view_options(wireframe=v))

    @staticmethod
    def _add_section_title(layout, text: str, style: str) -> None:
        label = QLabel(text)
        theme.bind(label, style)
        layout.addWidget(label)

    def _on_material_toggled(self, checked: bool) -> None:
        """材质开关：记住设置；当前是客户端模型则立即按新开关重新加载。"""
        self._settings.setValue("model_file_viewer_load_materials",
                                "true" if checked else "false")
        if self._closed:
            return
        if self._current_source == "client" and self._current_vfs_path:
            self._load_vfs_path(self._current_vfs_path)

    # ── 加载遮罩 ──────────────────────────────────────────

    def _on_busy_changed(self, text: str) -> None:
        if self._closed:
            return
        if text:
            self.loading_label.setText(text)
            self.spinner.start()
            self.loading_overlay.setVisible(True)
            self.loading_overlay.raise_()
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
        else:
            self.spinner.stop()
            self.loading_overlay.setVisible(False)
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)

    def _set_busy(self, text: str) -> None:
        # 供后台线程调用（信号投递到主线程）
        self.busy_changed.emit(text)

    # ── 本地文件 ──────────────────────────────────────────

    def _open_local(self) -> None:
        last_dir = self._settings.value("model_file_viewer_last_dir", "") or ""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 .geometry 模型文件", last_dir,
            "Geometry 模型 (*.geometry);;所有文件 (*)")
        if not paths:
            return
        path = paths[0]
        self._settings.setValue("model_file_viewer_last_dir", os.path.dirname(path))
        label = os.path.basename(path)

        def work(cancel_event):
            with open(path, "rb") as f:
                data = f.read()
            try:
                parsed = parse_geometry(data, file_path=path, cancel_event=cancel_event)
            finally:
                del data
            return geometry_from_parsed(os.path.splitext(label)[0], parsed, path,
                                        cancel_event=cancel_event,
                                        source="local")

        self._start_load(label, work)

    # ── 游戏客户端 ────────────────────────────────────────

    def _pick_from_game(self) -> None:
        if self._vfs_entries is None:
            self._scan_vfs()
            return
        self._show_picker()

    def _scan_vfs(self) -> None:
        if self._vfs_task is not None:
            return
        self._set_busy("正在读取游戏客户端文件索引...")
        env = self._current_env()

        def work(cancel_event):
            from services.geometry_service import GeometryService
            extractor = GeometryService.instance().get_extractor()
            return _collect_vfs_geometry(extractor)

        def done(entries):
            self._vfs_task = None
            if env != self._current_env():
                # 扫描期间切换了服务器/游戏目录：结果作废，缓存保持为空
                self._set_busy("")
                bus.log_message.emit("ℹ️ 模型文件查看器：服务器已切换，客户端索引缓存已重置")
                return
            self._on_vfs_ready(entries)

        self._vfs_task = run_async(
            work,
            on_finished=done,
            on_error=self._on_vfs_error,
            cancel_event=threading.Event(),
        )

    @staticmethod
    def _current_env() -> tuple[str, str]:
        """当前游戏目录 + 服务器标识（用于判定后台扫描结果是否过期）。"""
        try:
            from app.application import app as app_ctx
            ctx = app_ctx.ctx
            return (str(getattr(ctx, "game_path", "") or ""),
                    str(getattr(ctx, "wows_type", "") or ""))
        except Exception:  # noqa: BLE001
            return ("", "")

    def _on_env_changed(self, *_args) -> None:
        self._vfs_entries = None

    def _on_vfs_ready(self, entries) -> None:
        self._vfs_task = None
        self._set_busy("")
        if self._closed:
            return
        self._vfs_entries = list(entries or [])
        if not self._vfs_entries:
            QMessageBox.information(
                self, "没有找到模型文件",
                "当前游戏客户端的 VFS 中没有找到 .geometry 文件。\n"
                "请确认已在主界面选择正确的游戏目录与服务器。")
            return
        bus.log_message.emit(
            f"ℹ️ 模型文件查看器：客户端共 {len(self._vfs_entries):,} 个 .geometry 文件")
        self._show_picker()

    def _on_vfs_error(self, err) -> None:
        self._vfs_task = None
        self._set_busy("")
        if self._closed:
            return
        bus.log_message.emit(f"❌ 模型文件查看器：读取客户端索引失败: {err}")
        QMessageBox.warning(self, "读取失败",
                            f"无法读取游戏客户端文件索引：\n{err}\n\n"
                            "请确认已在主界面设置正确的游戏目录。")

    def _show_picker(self) -> None:
        if not self._vfs_entries:
            return
        picker = GeometryFilePicker(self._vfs_entries, self)
        try:
            if picker.exec() != QDialog.Accepted:
                return
            path = picker.selected_path()
        finally:
            picker.deleteLater()
        if not path:
            return
        self._load_vfs_path(path)

    def _load_vfs_path(self, path: str) -> None:
        label = path.rsplit("/", 1)[-1]
        load_materials = self.cb_material.isChecked()

        def work(cancel_event):
            self._set_busy("正在实时解析客户端 assets.bin（首次可能较慢）...")
            from services.geometry_service import GeometryService
            extractor = GeometryService.instance().get_extractor()
            entry = extractor.file_tree.get(path)
            if entry is None or entry.file_info is None or entry.volume is None:
                raise ValueError(f"客户端中找不到文件: {path}")
            data = extractor.pkg_reader.read_file(
                entry.volume.filename, entry.file_info)
            try:
                parsed = parse_geometry(data, file_path=path, cancel_event=cancel_event)
            finally:
                del data
            if load_materials:
                self._set_busy("正在加载材质贴图...")
            return geometry_from_parsed(os.path.splitext(label)[0], parsed, path,
                                        cancel_event=cancel_event,
                                        source="client",
                                        load_materials=load_materials)

        self._start_load(path, work)

    # ── 通用加载流程 ──────────────────────────────────────

    def _start_load(self, label: str, work) -> None:
        if self._load_task is not None:
            self._load_task.cancel()
        self._load_gen += 1
        gen = self._load_gen
        self.viewport.clear_scene()
        self._current_geom = None
        self._current_source = ""
        self._current_vfs_path = ""
        self.info_label.setText(f"正在加载 {label}...")
        self._set_busy(f"正在解析 {label}...")
        self._load_task = run_async(
            work,
            on_finished=lambda geom: self._on_loaded(geom, gen),
            on_error=lambda err: self._on_load_error(err, gen),
            cancel_event=threading.Event(),
        )

    def _on_loaded(self, geom, gen: int) -> None:
        if self._closed or gen != self._load_gen:
            return
        self._load_task = None
        self._current_geom = geom
        path0 = (geom.stats or {}).get("file_path", "")
        self._current_name = os.path.splitext(os.path.basename(path0))[0] or "model"
        _src = (geom.stats or {}).get("source", "client")
        self._current_source = _src
        self._current_vfs_path = path0 if _src == "client" else ""
        try:
            self.viewport.set_scene(geom, show_hull=True, show_armor=False,
                                    armor_scene=None)
            self.viewport.set_view_options(wireframe=self.cb_wire.isChecked())
        except Exception as exc:  # noqa: BLE001
            self._set_busy("")
            bus.log_message.emit(f"❌ 模型文件查看器：显示失败: {exc}")
            QMessageBox.warning(self, "显示失败", f"无法显示该模型：\n{exc}")
            return
        self._set_busy("")

        verts = sum(h.vertex_count for h in geom.hull_meshes)
        tris = sum(int(h.indices.size // 3) for h in geom.hull_meshes)
        size = geom.bounds_size
        path = (geom.stats or {}).get("file_path", "")
        skipped = int((geom.stats or {}).get("skipped_primitives", 0))
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        short = "/".join(parts[-2:]) if len(parts) > 2 else path
        extra = f"\n跳过：{skipped} 个非三角形图元" if skipped else ""
        stats = geom.stats or {}
        sk = stats.get("skeleton") or {}
        src = stats.get("source", "client")
        if src == "client":
            src_line = (f"数据源：客户端 assets.bin（实时）"
                        f"（渲染集 {sk.get('materials', 0)}）")
            if stats.get("load_materials"):
                mat_line = (f"材质：{sk.get('materialized', 0)} 个网格已装配，"
                            f"{sk.get('textured', 0)} 个带颜色贴图")
            else:
                mat_line = "材质：未加载（白模显示）"
            if sk.get("bones"):
                sk_line = (f"骨架：{_model_stem(path)}（{sk['bones']} 骨骼 / "
                           f"bind pose 混合 {sk.get('applied', 0)}/"
                           f"{sk.get('skinned', 0)}）")
            else:
                sk_line = "骨架：未找到（静态显示）"
        else:
            src_line = "数据源：本地文件（不含顶点组/权重与材质）"
            mat_line = "材质：本地文件模式不可用（白模显示）"
            sk_line = stats.get("note") or "提示：从游戏客户端选择可加载骨架/材质数据"
        self.info_label.setText(
            f"文件：{os.path.basename(path)}\n"
            f"位置：…/{short}\n"
            f"网格：{len(geom.hull_meshes)} 个（{verts:,} 顶点 / {tris:,} 三角形）\n"
            f"包围盒：{size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f}\n"
            f"{src_line}\n"
            f"{mat_line}\n"
            f"{sk_line}")
        self.info_label.setToolTip(path)
        bus.log_message.emit(
            f"✅ 模型文件查看器：{os.path.basename(path)} 加载完成"
            f"（{len(geom.hull_meshes)} 网格 / {tris:,} 三角形）")

    def _on_load_error(self, err, gen: int) -> None:
        if self._closed or gen != self._load_gen:
            return
        self._load_task = None
        self._set_busy("")
        self.info_label.setText("未加载模型")
        bus.log_message.emit(f"❌ 模型文件查看器：加载失败: {err}")
        QMessageBox.warning(self, "加载失败", f"无法加载该模型文件：\n{err}")

    # ── 模型导出（GLB）────────────────────────────────────

    def _start_export(self) -> None:
        """选择保存路径并启动后台导出（只读 ShipGeometry，不触碰 Qt/OpenGL）。"""
        if self._exporting:
            return
        geom = self._current_geom
        if geom is None:
            self.export_status.setText("请先加载模型")
            bus.log_message.emit("⚠️ 模型文件查看器：请先加载模型")
            return
        last_dir = self._settings.value("model_file_viewer_last_export_dir", "") or ""
        default_name = f"{self._current_name or 'model'}.glb"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出模型 (GLB)",
            os.path.join(last_dir, default_name) if last_dir else default_name,
            "glTF 2.0 Binary (*.glb)")
        if not path:
            return
        if not path.lower().endswith(".glb"):
            path += ".glb"
        self._settings.setValue("model_file_viewer_last_export_dir",
                                os.path.dirname(path))
        self._begin_export(geom, path)

    def _begin_export(self, geom: ShipGeometry, path: str) -> None:
        self._exporting = True
        self.btn_export.setEnabled(False)
        self.export_progress.setVisible(True)
        self.export_progress.setValue(0)
        self.export_status.setText("导出中，请稍候...")

        def work(cancel_event):
            from services.export_service import GlbRenderOptions, export_render_glb
            return export_render_glb(
                geom,
                path,
                # 独立模型：无材质/贴图、无挂载；保留 UV
                options=GlbRenderOptions(embed_textures=False, export_mounts=False),
                cancel_event=cancel_event,
                progress_cb=lambda p, m: self.export_progress_changed.emit(float(p), m),
            )

        self._export_task = run_async(
            work,
            on_finished=self._on_export_done,
            on_error=self._on_export_error,
            cancel_event=threading.Event(),
        )

    def _on_export_progress(self, pct: float, msg: str) -> None:
        if self._closed or not self._exporting:
            return
        pct = max(0.0, min(100.0, float(pct)))
        self.export_progress.setValue(int(pct))
        self.export_progress.setFormat(f"{msg}  {pct:.0f}%")

    def _on_export_done(self, report) -> None:
        if self._closed:
            return
        self._exporting = False
        self._export_task = None
        self.btn_export.setEnabled(True)
        self.export_progress.setVisible(False)
        self.export_status.setText("导出为 glTF 2.0 Binary（含 UV，不含材质/贴图）")
        for w in report.warnings:
            bus.log_message.emit(f"⚠️ 模型导出警告: {w}")
        bus.log_message.emit(report.summary())
        QMessageBox.information(self, "导出完成", report.summary())

    def _on_export_error(self, err) -> None:
        if self._closed:
            return
        self._exporting = False
        self._export_task = None
        self.btn_export.setEnabled(True)
        self.export_progress.setVisible(False)
        self.export_status.setText("导出失败")
        bus.log_message.emit(f"❌ 模型导出失败: {err}")
        QMessageBox.warning(self, "导出失败", f"导出失败：{err}")

    # ── 生命周期 ─────────────────────────────────────────

    def showEvent(self, event):
        self._closed = False
        super().showEvent(event)

    def closeEvent(self, event):
        self._closed = True
        if self._load_task is not None:
            self._load_task.kill(timeout=1.0)
            self._load_task = None
        if self._vfs_task is not None:
            self._vfs_task.kill(timeout=1.0)
            self._vfs_task = None
        if self._export_task is not None:
            self._export_task.kill(timeout=1.0)
            self._export_task = None
        self._exporting = False
        self._current_geom = None
        self._vfs_entries = None
        self._set_busy("")
        self.viewport.clear_scene()
        # 释放实时材质/贴图/骨架缓存（共享图集可达 20MB+）
        try:
            from services.geometry_service import GeometryService
            GeometryService.instance().release_live_material_caches()
        except Exception:  # noqa: BLE001
            pass
        self._save_geometry()
        super().closeEvent(event)

    def center_on_screen(self, relative_to=None) -> None:
        center_on_screen(self, relative_to)

    def _save_geometry(self) -> None:
        try:
            self._settings.setValue("model_file_viewer_geometry", self.saveGeometry())
        except Exception:  # noqa: BLE001
            pass

    def _restore_geometry(self) -> None:
        try:
            geo = self._settings.value("model_file_viewer_geometry")
            if geo:
                self.restoreGeometry(geo)
        except Exception:  # noqa: BLE001
            pass
