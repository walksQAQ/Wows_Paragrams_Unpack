"""
space_gui.py —— 港口/地图场景浏览器（PySide6）。

在游戏资源树中枚举所有 `models.bin` 场景目录，按「港口 / 地图」分组；
每个场景一个文件夹节点，展开后显示该场景的文件、使用模型、材质文件；
右侧面板显示选中项的属性（模型包围盒 / 渲染集 / 材质路径等）。

数据来源：data_extractor（.idx/.pkg）+ 可选 assets.bin（pathId → 路径反查）。
启动方式：  python -m uncode_assets.space_gui [游戏目录]
也可由主程序通过 SpaceBrowser(game_dir) 打开（见 ui/main_window.py 工具菜单）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QPushButton, QLabel, QFileDialog, QLineEdit, QStatusBar, QToolBar,
    QHeaderView, QAbstractItemView, QMessageBox,
)

from .space import (
    SceneResolver, SpaceScene, parse_space_bin, parse_geometry_header, scan_scenes,
)

_STYLE = """
QMainWindow, QWidget { background-color: #1e1e1e; color: #d4d4d4; }
QToolBar { background-color: #252526; border-bottom: 1px solid #333; spacing: 6px; padding: 4px; }
QToolBar QPushButton { background-color: #0e639c; color: white; border: none; border-radius: 3px; padding: 4px 12px; }
QToolBar QPushButton:hover { background-color: #1177bb; }
QTreeWidget { background-color: #1e1e1e; color: #d4d4d4; border: none; outline: none; }
QTreeWidget::item { padding: 3px; }
QTreeWidget::item:selected { background-color: #094771; }
QTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: none; padding: 8px;
            font-family: Consolas, "Courier New", monospace; font-size: 12px; }
QLineEdit { background-color: #333; color: #d4d4d4; border: 1px solid #555; border-radius: 3px; padding: 4px 8px; }
QStatusBar { background-color: #252526; color: #9cdcfe; }
QLabel#info { color: #9cdcfe; padding: 0 8px; }
QLabel#source { color: #7f7f7f; padding: 0 8px; font-size: 11px; }
"""

_ROLE_SCENE = Qt.ItemDataRole.UserRole
_ROLE_KIND = Qt.ItemDataRole.UserRole + 1
_ROLE_EXTRA = Qt.ItemDataRole.UserRole + 2


def detect_wows_type(game_dir: str) -> str:
    """按游戏目录内容探测服务器类型（Korabli→Lesta，WoWS→Wargaming）。"""
    g = Path(game_dir)
    bin_dir = g / "bin"
    if bin_dir.is_dir():
        try:
            subs = sorted(bin_dir.iterdir(), key=lambda x: str(x), reverse=True)
        except Exception:  # noqa: BLE001
            subs = []
        for bd in subs:
            if not bd.is_dir():
                continue
            bin64 = bd / "bin64"
            if (bin64 / "Korabli64.exe").exists():
                return "Lesta"
            if (bin64 / "WorldOfWarships64.exe").exists() \
                    or (bin64 / "WorldOfWarships.exe").exists():
                return "Wargaming"
    if (g / "Korabli64.exe").exists():
        return "Lesta"
    if (g / "WorldOfWarships.exe").exists():
        return "Wargaming"
    return ""


def build_resolver(game_dir: str, wows_type: str,
                   bin_folder: Optional[str] = None) -> SceneResolver:
    """构建 pathId → 路径解析器。

    解析依赖 assets.bin 的路径表/字符串表。为了可靠且不每次重提 227MB：
      - 按「游戏目录+服务器」落盘缓存提取出的 assets.bin → data/assets_<key>.bin；
      - 命中缓存直接加载；未命中则从被浏览游戏目录提取 content/assets.bin 后写缓存再加载。
    这样路径/名字 hash 都能反查回可读文本；任何一步失败回退 SceneResolver(None)（0x 十六进制）。
    """
    try:
        import hashlib
        from .service import AssetsBinService
        from utils.path_utils import get_data_dir
        key = hashlib.sha1(
            f"{os.path.normpath(str(game_dir))}|{wows_type}".encode()).hexdigest()[:12]
        cached = get_data_dir() / f"assets_{key}.bin"
        if not cached.exists():
            extract_assets_bin(game_dir, bin_folder, cached)
        svc = AssetsBinService(assets_path=cached, wows_type=wows_type)
        return SceneResolver(svc.db)
    except Exception:  # noqa: BLE001
        return SceneResolver(None)


def extract_assets_bin(game_dir: str, bin_folder: Optional[str], cached: Path) -> None:
    """从游戏目录的 .pkg 提取 content/assets.bin 并写到缓存文件。"""
    from data_extractor import GameExtractor
    ext = GameExtractor(game_dir, bin_folder=bin_folder)
    try:
        entry = ext.file_tree.get("content/assets.bin")
        if entry is None or getattr(entry, "is_directory", True) or entry.file_info is None:
            raise RuntimeError("未找到 content/assets.bin")
        data = ext.pkg_reader.read_file(entry.volume.filename, entry.file_info)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        del data
    finally:
        try:
            ext.close()
        except Exception:  # noqa: BLE001
            pass


class _ScanWorker(QThread):
    """后台扫描线程：建 extractor + assets 解析器 + 枚举场景。"""

    loaded = Signal(object)   # (extractor, resolver, list[SpaceScene])
    failed = Signal(str)

    def __init__(self, game_dir: str, wows_type: str = "",
                 bin_folder: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._game_dir = game_dir
        self._wows_type = wows_type
        self._bin_folder = bin_folder

    def run(self) -> None:
        try:
            from data_extractor import GameExtractor
            extractor = GameExtractor(self._game_dir, bin_folder=self._bin_folder)
            resolver = build_resolver(self._game_dir, self._wows_type,
                                      bin_folder=self._bin_folder)
            scenes = scan_scenes(extractor, resolver)
            self.loaded.emit((extractor, resolver, scenes))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class SpaceBrowser(QMainWindow):
    """港口/地图场景浏览器。"""

    def __init__(self, game_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._extractor = None
        self._resolver: Optional[SceneResolver] = None
        self._scenes: list[SpaceScene] = []
        self._worker: Optional[_ScanWorker] = None
        self._bin_folder: Optional[str] = None
        self._wows_type = ""
        # 继承主应用设置；未显式传目录时回退到当前配置的游戏路径
        try:
            from app.application import app as app_ctx
            self._wows_type = getattr(app_ctx.ctx, "wows_type", "") or ""
            if not game_dir:
                game_dir = getattr(app_ctx.ctx, "game_path", "") or None
        except Exception:  # noqa: BLE001
            self._wows_type = ""
        if game_dir:
            w = detect_wows_type(game_dir)
            if w:
                self._wows_type = w
        self.setWindowTitle("港口 / 地图场景浏览器")
        self.resize(1280, 820)
        self.setStyleSheet(_STYLE)
        self._build_ui()
        self._geom_cache: dict[str, dict] = {}
        self._space_cache: dict[str, int] = {}
        self._mfm_cache: dict[int, dict] = {}
        if game_dir:
            self.load_source(str(game_dir))
        else:
            self.status_label.setText("未加载 —— 请选择游戏目录")

    # ── UI 构建 ─────────────────────────────────────────

    def _build_ui(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        btn_game = QPushButton("选择游戏目录...")
        btn_game.clicked.connect(self._on_open_game_dir)
        toolbar.addWidget(btn_game)

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self._on_refresh)
        toolbar.addWidget(btn_refresh)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("  "))

        self.info_label = QLabel("未加载")
        self.info_label.setObjectName("info")
        toolbar.addWidget(self.info_label)

        self.source_label = QLabel("")
        self.source_label.setObjectName("source")
        toolbar.addWidget(self.source_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setAutoScroll(True)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemClicked.connect(self._on_item_clicked)
        splitter.addWidget(self.tree)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        splitter.addWidget(self.detail)

        splitter.setSizes([460, 820])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("就绪")
        status.addPermanentWidget(self.status_label)

    # ── 加载 ────────────────────────────────────────────

    def load_source(self, game_dir: str) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.tree.clear()
        self.detail.clear()
        self._scenes = []
        w = detect_wows_type(game_dir)
        if w and w != self._wows_type:
            self._wows_type = w
        self._set_source_label(game_dir)
        self.status_label.setText("正在扫描港口 / 地图场景...")
        self.info_label.setText("扫描中...")
        self._worker = _ScanWorker(game_dir, wows_type=self._wows_type,
                                   bin_folder=self._bin_folder, parent=self)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_loaded(self, payload) -> None:
        self._extractor, self._resolver, self._scenes = payload
        self._build_tree()
        self.status_label.setText("加载完成")
        self.info_label.setText(
            f"场景: {len(self._scenes)}   "
            f"港口: {sum(1 for s in self._scenes if s.kind == 'port')}   "
            f"地图: {sum(1 for s in self._scenes if s.kind == 'map')}")
        # 选中第一个场景
        if self.tree.topLevelItemCount() > 0:
            node = self._first_scene_node()
            if node is not None:
                self.tree.setCurrentItem(node)
                self._show_scene(node)

    def _on_failed(self, message: str) -> None:
        self.status_label.setText("加载失败")
        self.info_label.setText("加载失败")
        self.detail.setPlainText(f"加载失败:\n{message}")

    def _set_source_label(self, path: str) -> None:
        tag = "WG" if self._wows_type == "Wargaming" else "Lesta"
        self.source_label.setText(f"来源: {Path(path).name}  [{tag}]")

    # ── 树构建 ──────────────────────────────────────────

    def _build_tree(self) -> None:
        self.tree.clear()
        groups = {
            "port": QTreeWidgetItem(["港口 (Port)"]),
            "map": QTreeWidgetItem(["地图 / 空间 (Map / Space)"]),
            "unknown": QTreeWidgetItem(["未分类"]),
        }
        # 按 kind 分组；无明确场景的未知也展示
        seen: dict[str, QTreeWidgetItem] = {}
        for node in groups.values():
            node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(node)
            seen[node.text(0)] = node
        for idx, scene in enumerate(self._scenes):
            group = groups.get(scene.kind, groups["unknown"])
            leaf = scene.dir_path.rstrip('/').rsplit('/', 1)[-1]
            item = QTreeWidgetItem([leaf])
            item.setToolTip(0, scene.dir_path)
            item.setData(0, _ROLE_SCENE, idx)
            item.setData(0, _ROLE_KIND, scene.kind)
            group.addChild(item)

    def _first_scene_node(self) -> Optional[QTreeWidgetItem]:
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            if g.childCount() > 0:
                return g.child(0)
        return None

    def _populate_scene(self, node: QTreeWidgetItem) -> None:
        """展开场景节点时，按其数据文件层级填充子节点。"""
        if node.childCount() > 0:
            return
        idx = int(node.data(0, _ROLE_SCENE))
        scene = self._scenes[idx]

        # ── models.bin：模型 + 材质（按层级）───────────────
        mb_node = QTreeWidgetItem([f"models.bin ({len(scene.models)} 模型)"])
        mb_node.setData(0, _ROLE_SCENE, idx)
        mb_node.setData(0, _ROLE_KIND, "modelsbin")
        node.addChild(mb_node)

        models_node = QTreeWidgetItem([f"模型 ({len(scene.models)})"])
        models_node.setFlags(models_node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for mi, m in enumerate(scene.models):
            label = m.path or f"#{mi} 0x{m.path_id:016X}"
            mn = QTreeWidgetItem([label])
            mn.setToolTip(0, m.path or f"pathId 0x{m.path_id:016X}")
            mn.setData(0, _ROLE_SCENE, idx)
            mn.setData(0, _ROLE_KIND, "model")
            mn.setData(0, _ROLE_EXTRA, mi)
            models_node.addChild(mn)
        mb_node.addChild(models_node)

        mats_node = QTreeWidgetItem([f"材质文件 ({len(scene.materials)})"])
        mats_node.setFlags(mats_node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for mfm_id, path in scene.materials:
            mn = QTreeWidgetItem([path.rsplit('/', 1)[-1] or f"0x{mfm_id:016X}"])
            mn.setToolTip(0, path or f"0x{mfm_id:016X}")
            mn.setData(0, _ROLE_SCENE, idx)
            mn.setData(0, _ROLE_KIND, "material")
            mn.setData(0, _ROLE_EXTRA, (mfm_id, path))
            mats_node.addChild(mn)
        mb_node.addChild(mats_node)

        # ── 其他数据文件（space.bin / models.geometry / 其他）────
        for name in sorted(scene.files):
            if name == "models.bin":
                continue
            size = scene.files[name]
            fnode = QTreeWidgetItem([f"{name}  ({size:,} B)"])
            fnode.setData(0, _ROLE_SCENE, idx)
            fnode.setData(0, _ROLE_KIND, "file")
            fnode.setToolTip(0, name)
            node.addChild(fnode)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        kind = item.data(0, _ROLE_KIND)
        if kind in ("port", "map", "unknown"):
            self._populate_scene(item)

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, _ROLE_KIND)
        if kind in ("port", "map", "unknown"):
            item.setExpanded(True)
            self._show_scene(item)
        elif kind == "modelsbin":
            self._show_scene(item)
        elif kind == "file":
            self._show_file(item)
        elif kind == "model":
            self._show_model(item)
        elif kind == "material":
            self._show_material(item)

    # ── 详情渲染 ────────────────────────────────────────

    def _scene_by_node(self, item: QTreeWidgetItem) -> Optional[SpaceScene]:
        idx = int(item.data(0, _ROLE_SCENE))
        if 0 <= idx < len(self._scenes):
            return self._scenes[idx]
        return None

    def _show_scene(self, item: QTreeWidgetItem) -> None:
        scene = self._scene_by_node(item)
        if scene is None:
            return
        if scene.dir_path not in self._space_cache:
            self._space_cache[scene.dir_path] = self._read_instance_count(scene.dir_path)
        instance = self._space_cache[scene.dir_path]

        lines = [
            f"场景目录: {scene.dir_path}",
            f"分类: {scene.kind}",
            "",
            "── models.bin ────────────────────────────────",
            f"  模型数: {scene.models_count}",
            f"  骨架数: {scene.skeletons_count}",
            f"  骨骼数: {scene.model_bone_count}",
            "",
            "── space.bin ─────────────────────────────────",
            f"  实例数: {instance if instance is not None else '未读取'}",
            "",
            "── models.geometry ───────────────────────────",
            "  （按要求跳过几何显示；点击该文件查看包信息）",
            "",
            "── 目录文件 ──────────────────────────────────",
        ]
        for name, size in sorted(scene.files.items()):
            lines.append(f"  {name}  ({size:,} B)")
        self.detail.setPlainText("\n".join(lines))

    def _show_file(self, item: QTreeWidgetItem) -> None:
        scene = self._scene_by_node(item)
        if scene is None:
            return
        name = item.text(0).split("  (")[0]
        size = scene.files.get(name, 0)
        lines = [f"文件: {scene.dir_path}/{name}", f"解压后大小: {size:,} B"]
        if name == "space.bin":
            inst = self._read_instance_count(scene.dir_path)
            lines.append("")
            lines.append(f"space.bin 实例数: {inst}")
        elif name == "models.geometry":
            attrs = self._geometry_attrs(scene.dir_path)
            lines.append("")
            if attrs:
                lines.append("MergedGeometryPrototype 头部（仅统计，未展开网格）:")
                for k, v in attrs.items():
                    lines.append(f"  {k}: {v}")
            else:
                lines.append("  （按要求跳过几何解码；仅文件信息）")
        else:
            lines.append("")
            lines.append("（该文件无内置解析器；可在 assets.bin 浏览器查看）")
        self.detail.setPlainText("\n".join(lines))

    def _show_model(self, item: QTreeWidgetItem) -> None:
        scene = self._scene_by_node(item)
        if scene is None:
            return
        mi = int(item.data(0, _ROLE_EXTRA))
        if not (0 <= mi < len(scene.models)):
            return
        m = scene.models[mi]
        lines = [
            f"模型: {m.path or f'0x{m.path_id:016X}'}",
            f"pathId: 0x{m.path_id:016X}",
            "",
            "────────── 模型 (ModelPrototype) ──────────────",
            f"  路径: {m.path or f'0x{m.path_id:016X}'}",
            f"  引用的视觉: {m.visual_path}",
            "",
            "────────── 视觉 (VisualPrototype) ─────────────",
            f"  合并几何: {m.merged_geometry_path}",
            f"  水下: {m.underwater}   水上: {m.abovewater}",
            f"  包围盒 min: {m.bbox_min}",
            f"  包围盒 max: {m.bbox_max}",
            f"  LOD 数: {m.lods_count}",
            "",
            f"  渲染集 ({m.render_sets_count}):",
        ]
        for rs in m.render_sets:
            lines.append(f"    • {rs.name}")
            lines.append(f"        材质: {rs.material_identifier}")
            lines.append(f"        mfm: {rs.material_mfm}")
            lines.append(f"        顶点映射 0x{rs.vertices_mapping_id:08X} / "
                         f"索引映射 0x{rs.indices_mapping_id:08X}  蒙皮: {rs.skinned}")
            if rs.nodes:
                lines.append(f"        节点: {rs.nodes[:8]}")
            lines += self._fmt_mfm(rs.material_mfm_id, "          ")
        self.detail.setPlainText("\n".join(lines))

    def _show_material(self, item: QTreeWidgetItem) -> None:
        scene = self._scene_by_node(item)
        if scene is None:
            return
        mfm_id, path = item.data(0, _ROLE_EXTRA)
        users = [m.path for m in scene.models
                 if any(rs.material_mfm_id == mfm_id for rs in m.render_sets)]
        lines = [
            f"材质文件: {path or f'0x{mfm_id:016X}'}",
            f"mfm id: 0x{mfm_id:016X}",
            "",
            f"使用它的模型 ({len(users)}):",
        ]
        for u in users:
            lines.append(f"  {u}")
        lines.append("")
        lines.append("── 材质属性 (MaterialPrototype) ────────")
        lines += self._fmt_mfm(mfm_id, "  ")
        self.detail.setPlainText("\n".join(lines))

    # ── 懒读取 ──────────────────────────────────────────

    def _read_file(self, dir_path: str, name: str) -> Optional[bytes]:
        if self._extractor is None:
            return None
        path = dir_path + "/" + name
        e = self._extractor.file_tree.get(path)
        if e is None or getattr(e, "is_directory", True) or e.file_info is None:
            return None
        try:
            return self._extractor.pkg_reader.read_file(e.volume.filename, e.file_info)
        except Exception:  # noqa: BLE001
            return None

    # ── 材质属性解码 ──────────────────────────────────

    def _mfm_props(self, mfm_id: int) -> Optional[dict]:
        """用 assets.bin 解码指定 .mfm 材质；无 db 或失败返回 None（带缓存）。"""
        if not mfm_id:
            return None
        if mfm_id in self._mfm_cache:
            return self._mfm_cache[mfm_id]
        props = None
        db = getattr(self._resolver, "db", None) if self._resolver else None
        if db is not None:
            try:
                # decode_material 依赖 thread-local 服务器类型；浏览器解码发生在
                # 主线程，需先恢复上下文，避免 WG 材质按 Lesta 布局解码。
                from .types import set_wows_type
                set_wows_type(self._wows_type)
                from .decoders import parse_mfm_from_db
                props = parse_mfm_from_db(db, mfm_id)
            except Exception:  # noqa: BLE001
                props = None
        self._mfm_cache[mfm_id] = props
        return props

    def _fmt_mfm(self, mfm_id: int, indent: str = "        ") -> list[str]:
        """把 mfm 材质格式化为多行缩进文本。"""
        if not mfm_id:
            return [f"{indent}(无材质)"]
        props = self._mfm_props(mfm_id)
        if not props:
            return [f"{indent}(无法解码: 0x{mfm_id:016X})"]
        lines: list[str] = []
        shader = props.get("shader_id")
        if shader not in (None, "", "0x00000000"):
            lines.append(f"{indent}shader: {shader}")
        for p in props.get("properties", []) or []:
            name = p.get("name") or "?"
            typ = p.get("type") or "?"
            val = p.get("value")
            lines.append(f"{indent}- {name} ({typ}) = {val}")
        if not lines:
            lines.append(f"{indent}(空材质)")
        return lines

    def _read_instance_count(self, dir_path: str) -> Optional[int]:
        data = self._read_file(dir_path, "space.bin")
        if data is None:
            return None
        try:
            return parse_space_bin(data)
        except Exception:  # noqa: BLE001
            return None
        finally:
            del data

    def _geometry_attrs(self, dir_path: str) -> dict:
        if dir_path in self._geom_cache:
            return self._geom_cache[dir_path]
        data = self._read_file(dir_path, "models.geometry")
        if data is None:
            self._geom_cache[dir_path] = {}
            return {}
        try:
            attrs = parse_geometry_header(data)
        except Exception:  # noqa: BLE001
            attrs = {}
        self._geom_cache[dir_path] = attrs
        del data
        return attrs

    # ── 打开 ────────────────────────────────────────────

    def _on_open_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择游戏目录（含 bin 与 res_packages）")
        if path:
            self._save_inherited_dir(path)
            self._bin_folder = None
            self.load_source(path)

    def _on_refresh(self) -> None:
        if self._extractor is not None:
            self.load_source(str(self._extractor.game_dir))

    def _save_inherited_dir(self, path: str) -> None:
        try:
            from app.application import app
            app.config.game_path = path
        except Exception:  # noqa: BLE001
            pass


def main(argv: Optional[list] = None) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(argv or sys.argv)
    app.setStyle("Fusion")
    source = sys.argv[1] if len(sys.argv) > 1 else None
    win = SpaceBrowser(game_dir=source)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
