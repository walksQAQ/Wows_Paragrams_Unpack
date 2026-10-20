"""AssetsBinViewer —— assets.bin 可视化浏览/解码界面（PySide6）。

功能：
  - 打开已解压的 assets.bin 文件或直接选择游戏目录（自动用 data_extractor 提取）
  - 打开窗口时不自动载入数据，由用户手动选择数据源
  - 后台线程加载解析（避免卡 UI），左侧懒加载虚拟文件树
  - 点击文件在右侧显示解码 JSON（深色等宽主题）
  - 顶部搜索：文件名/路径模糊匹配（多关键词交集），或按材质 **fx** 搜索
    （列出使用该 fx 的 `.mfm`；首次建立索引仅需秒级，之后即时）
  - 明文导出：单文件弹「另存为」；**多选（Ctrl/Shift）时选文件夹批量导出**
  - 状态栏显示数据库概览
  - 关闭窗口时询问是否清理 .uncode_cache 索引缓存

独立运行：  python -m uncode_assets.gui [assets.bin 或 游戏目录]
也可由主程序通过 AssetsBinViewer(source) 打开。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QPushButton, QLabel, QFileDialog, QLineEdit, QStatusBar, QToolBar,
    QHeaderView, QAbstractItemView, QMessageBox, QComboBox, QApplication,
)

from .errors import AssetsBinError
from .service import AssetsBinService
from .vfs import VirtualFile

# 深色主题样式
_STYLE = """
QMainWindow, QWidget { background-color: #1e1e1e; color: #d4d4d4; }
QToolBar { background-color: #252526; border-bottom: 1px solid #333; spacing: 6px; padding: 4px; }
QToolBar QPushButton { background-color: #0e639c; color: white; border: none; border-radius: 3px; padding: 4px 12px; }
QToolBar QPushButton:hover { background-color: #1177bb; }
QToolBar QPushButton:checked { background-color: #0e8a3c; }
QTreeWidget { background-color: #1e1e1e; color: #d4d4d4; border: none; outline: none; }
QTreeWidget::item { padding: 3px; }
QTreeWidget::item:selected { background-color: #094771; }
QTextEdit { background-color: #1e1e1e; color: #d4d4d4; border: none; padding: 8px;
            font-family: Consolas, "Courier New", monospace; font-size: 12px; }
QLineEdit { background-color: #333; color: #d4d4d4; border: 1px solid #555; border-radius: 3px; padding: 4px 8px; }
QComboBox { background-color: #333; color: #d4d4d4; border: 1px solid #555; border-radius: 3px; padding: 3px 6px; }
QComboBox QAbstractItemView { background-color: #252526; color: #d4d4d4; selection-background-color: #094771; }
QStatusBar { background-color: #252526; color: #9cdcfe; }
QLabel#info { color: #9cdcfe; padding: 0 8px; }
QLabel#source { color: #7f7f7f; padding: 0 8px; font-size: 11px; }
"""


def _insert_after(data: dict, anchor: str, key: str, value) -> dict:
    """在 `anchor` 键之后插入一个新键（保持其余键顺序）；无 anchor 时追加到末尾。"""
    out: dict = {}
    placed = False
    for k, v in data.items():
        out[k] = v
        if k == anchor:
            out[key] = value
            placed = True
    if not placed:
        out[key] = value
    return out


class _FxIndexWorker(QThread):
    """后台构建 `.mfm → fx` 索引（只读材质头，不解析属性）。

    全量 `.mfm` 约 3 万个，解析属性需 1 分钟以上；只取 shader_id +
    material_hash（= fx 资源 selfId），在 assets.bin 路径树里解析 fx 路径，
    仅需数秒。
    """

    progress = Signal(int, int)
    done = Signal(object)  # list[tuple[path, fx_path, shader_id, material_hash]]
    failed = Signal(str)

    def __init__(self, svc: AssetsBinService, wows_type: str, parent=None):
        super().__init__(parent)
        self._svc = svc
        self._wows_type = wows_type

    def run(self) -> None:
        try:
            from .decoders import read_material_header
            from .mfm_fx import resolve_fx_path
            from .types import set_wows_type

            set_wows_type(self._wows_type)
            svc = self._svc
            # svc.db 是 assets.bin 解析出的内存 PrototypeDatabase（含路径树），
            # **不是** assets_data.db：浏览器始终直接读当前 assets.bin。
            db = svc.db
            wg = (self._wows_type or "").lower() == "wargaming"
            # 只取记录头部：材质记录 0x88（WG 0x78），避免整 blob 尾部拷贝
            need = 0x78 if wg else 0x88
            files = [f.path for f in svc.vfs.all_files()
                     if f.prototype_type is not None
                     and f.path.lower().endswith(".mfm")]
            total = len(files)
            out: list[tuple[str, str, str, str]] = []
            for i, path in enumerate(files):
                try:
                    data = svc.vfs.open_file_len(path, need)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    hdr = read_material_header(data, wargaming=wg)
                except Exception:  # noqa: BLE001
                    continue
                sh = hdr["shader_id"]
                mh = hdr["material_hash"]
                fx = resolve_fx_path(db, mh)
                out.append((path, fx, sh, mh))
                if (i & 1023) == 0:
                    self.progress.emit(i, total)
            self.progress.emit(total, total)
            self.done.emit(out)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class _LoadWorker(QThread):
    """后台加载线程：解析 assets.bin 并构建 VFS。"""

    loaded = Signal(object)  # AssetsBinService
    failed = Signal(str)

    def __init__(self, game_dir: Optional[str] = None,
                 assets_path: Optional[str] = None,
                 bin_folder: Optional[str] = None,
                 wows_type: str = "", parent=None):
        super().__init__(parent)
        self._game_dir = game_dir
        self._assets_path = assets_path
        self._bin_folder = bin_folder
        self._wows_type = wows_type

    def run(self) -> None:
        try:
            if self._game_dir:
                # 传空 set 启用 PKG 文件树收集：资源节点据此标记「PKG 中确有该文件」
                svc = AssetsBinService(game_dir=self._game_dir, bin_folder=self._bin_folder,
                                       wows_type=self._wows_type, pkg_paths=set())
            else:
                svc = AssetsBinService(assets_path=self._assets_path,
                                       wows_type=self._wows_type)
            self.loaded.emit(svc)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class AssetsBinViewer(QMainWindow):
    """assets.bin 可视化浏览器。"""

    #: 每个目录最多直接显示的文件节点数，超出显示占位项（避免大目录卡死 UI）
    MAX_FILES_PER_DIR = 1000
    #: 搜索结果最多列出的条目数
    MAX_SEARCH_RESULTS = 2000

    def __init__(self, source: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._svc: Optional[AssetsBinService] = None
        self._worker: Optional[_LoadWorker] = None
        self._fx_worker: Optional[_FxIndexWorker] = None
        self._fx_index: Optional[list] = None
        self._pending_fx_query: str = ""
        self._searching = False
        #: 搜索导航：命中路径列表 + 当前索引（同一关键词再次回车 → 下一个）
        self._search_key: tuple = ()
        self._search_title = ""
        self._search_hits: list = []
        self._search_hit_index = 0
        #: 已加载子项的目录（避免用 childCount 误判「已加载」）
        self._loaded_dirs: set = set()
        self._bin_folder: Optional[str] = None
        #: 当前选中文件的路径与解码结果（切换显示方式时重用）
        self._current_path: Optional[str] = None
        self._current_decoded = None
        #: 批量导出上次使用的目标文件夹
        self._last_export_dir: str = ""
        #: 是否以 Mod SDK 明文 .mfm 样式显示材质
        self._mfm_plain = False
        # 服务器类型表：继承主应用设置（WG→10 类型表，Lesta→12 类型表）
        self._wows_type = ""
        try:
            from app.application import app as app_ctx
            self._wows_type = getattr(app_ctx.ctx, "wows_type", "") or ""
        except Exception:  # noqa: BLE001
            self._wows_type = ""
        self.setWindowTitle("assets.bin 浏览器")
        self.resize(1280, 820)
        self.setStyleSheet(_STYLE)
        self._build_ui()
        # 打开窗口时不自动载入数据：由用户手动选择 assets.bin 文件或游戏目录，
        # 避免后台解析与模型查看器渲染争抢 GIL 造成卡顿。
        # 仅命令行显式传入路径时才自动加载（python -m uncode_assets.gui <path>）。
        if source:
            self.load_source(str(source))
        else:
            self.status_label.setText("未加载 —— 请打开 assets.bin 文件或选择游戏目录")

    # ── UI 构建 ─────────────────────────────────────────

    def _build_ui(self) -> None:
        # 工具栏
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        btn_open = QPushButton("打开 assets.bin...")
        btn_open.clicked.connect(self._on_open_file)
        toolbar.addWidget(btn_open)

        btn_game = QPushButton("选择游戏目录...")
        btn_game.clicked.connect(self._on_open_game_dir)
        toolbar.addWidget(btn_game)

        toolbar.addSeparator()

        self.btn_plain = QPushButton("明文格式")
        self.btn_plain.setCheckable(True)
        self.btn_plain.setToolTip(
            "以官方 Mod SDK 明文样式显示（材质 .mfm / 视觉 .visual / 模型 .model）")
        self.btn_plain.toggled.connect(self._on_toggle_plain)
        toolbar.addWidget(self.btn_plain)

        self.btn_export_file = QPushButton("导出明文")
        self.btn_export_file.setToolTip(
            "明文导出所选文件（可 Ctrl/Shift 多选，批量导出到文件夹）")
        self.btn_export_file.setEnabled(False)
        self.btn_export_file.clicked.connect(self._on_export_file)
        toolbar.addWidget(self.btn_export_file)

        toolbar.addSeparator()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索（空格分隔多关键词，回车）...")
        self.search_edit.setFixedWidth(210)
        self.search_edit.returnPressed.connect(self._on_search)
        toolbar.addWidget(self.search_edit)

        self.search_mode = QComboBox()
        self.search_mode.addItems(["文件名/路径", "fx"])
        self.search_mode.setFixedWidth(96)
        self.search_mode.setToolTip(
            "文件名/路径：模糊匹配路径或文件名（多关键词取交集）\n"
            "fx：在全部 .mfm 材质里按 fx 路径搜索（fx 由 material_hash 在\n"
            "     assets.bin 路径树中解析；也可输入 shader_id/material_hash）")
        toolbar.addWidget(self.search_mode)

        # ⚠️ 计数/来源不再放在工具栏：QToolBar 宽度不足时会把后续原部件收进「»」
        # 溢出菜单（不换行、不滚动），看起来像「加载后消失了」。改放状态栏。
        self.info_label = QLabel("未加载")
        self.info_label.setObjectName("info")
        self.info_label.setToolTip("assets.bin 概览")

        # 中央：树 + JSON
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        # 列宽随内容自适应，长路径/文件名超出时出现水平滚动条
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setAutoScroll(True)
        # 支持多选：Ctrl/Shift 选中多个文件后「导出明文」批量导出到文件夹
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemSelectionChanged.connect(self._update_export_state)
        splitter.addWidget(self.tree)

        self.json_view = QTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        splitter.addWidget(self.json_view)

        splitter.setSizes([420, 860])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # 状态栏：左侧概览（信息），右侧来源 + 当前状态
        status = QStatusBar()
        self.setStatusBar(status)
        status.addWidget(self.info_label)
        self.source_label = QLabel("")
        self.source_label.setObjectName("source")
        self.source_label.setToolTip("数据来源（继承主应用设置）")
        status.addPermanentWidget(self.source_label)
        self.status_label = QLabel("就绪")
        status.addPermanentWidget(self.status_label)

    # ── 窗口定位 ────────────────────────────────────────

    def center_on_screen(self, relative_to: Optional[QWidget] = None) -> None:
        """把窗口居中到指定窗口（默认主屏）。"""
        from utils.window_utils import center_on_screen
        center_on_screen(self, relative_to)

    # ── 加载 ────────────────────────────────────────────

    def load_source(self, source: str) -> None:
        """加载 assets.bin 文件路径或游戏目录（后台线程）。

        游戏目录按内容自动探测服务器类型（Korabli64.exe→Lesta，
        WorldOfWarships*.exe→Wargaming），避免主应用为 Lesta 时用 Lesta
        类型表(0x88)解析 WG 客户端的 assets.bin(0x78) 导致解码错乱
        （路径显示为一串 0x 地址）。
        """
        p = Path(source)
        if self._worker and self._worker.isRunning():
            return
        self.tree.clear()
        self.json_view.clear()
        self._current_path = None
        self._current_decoded = None
        self._fx_index = None
        self._searching = False
        self._reset_search_nav()
        self._update_export_state()
        self.status_label.setText("正在加载/解析 assets.bin...（Kraken 解压可能较慢）")
        self.info_label.setText("加载中...")
        if p.is_dir():
            detected = self._detect_wows_type(str(p))
            if detected and detected != self._wows_type:
                self._wows_type = detected
                self._set_source_label(str(p))
            self._worker = _LoadWorker(game_dir=str(p), bin_folder=self._bin_folder,
                                       wows_type=self._wows_type, parent=self)
        else:
            self._worker = _LoadWorker(assets_path=str(p),
                                       wows_type=self._wows_type, parent=self)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._worker.start()

    @staticmethod
    def _detect_wows_type(game_dir: str) -> str:
        """按游戏目录内容探测服务器类型（Korabli→Lesta，WoWS→Wargaming）。"""
        from utils.path_utils import detect_wows_type
        return detect_wows_type(game_dir)

    def _on_loaded(self, svc: AssetsBinService) -> None:
        self._svc = svc
        # 数据源已切换：fx 索引与搜索状态失效
        self._fx_index = None
        self._pending_fx_query = ""
        self._searching = False
        self._reset_search_nav()
        self._current_path = None
        self._current_decoded = None
        self._update_export_state()
        info = svc.info()
        proto_n = info['file_count'] - info.get('resource_count', 0)
        # 工具栏右侧空间有限：只显示最关键的计数，明细放 tooltip
        self.info_label.setText(
            f"{info['file_count']:,} 文件（PKG 资源 {info.get('resource_count', 0):,}）")
        self.info_label.setToolTip(
            f"blob: {info['databases_count']}\n"
            f"prototype 文件: {proto_n:,}\n"
            f"PKG 资源（无 prototype，需解包查看）: {info.get('resource_count', 0):,}\n"
            f"目录: {info['dir_count']:,}   路径条目: {info['paths_count']:,}")
        self._build_root()
        self.status_label.setText("加载完成")

    def _on_load_failed(self, message: str) -> None:
        self.status_label.setText("加载失败")
        self.info_label.setText("加载失败")
        self.json_view.setPlainText(f"加载失败:\n{message}")

    # ── 文件树 ──────────────────────────────────────────

    def _build_root(self) -> None:
        self.tree.clear()
        self._loaded_dirs.clear()
        self._load_children_of("/")

    def _node_path(self, item: QTreeWidgetItem) -> str:
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _load_children_of(self, dir_path: str, show_all: bool = False,
                          force: bool = False) -> None:
        """把 dir_path 的直接子项挂到对应父节点（懒加载）。

        show_all: 不套用 MAX_FILES_PER_DIR 上限（搜索定位到超大目录时用，
                  否则目标文件排在 1000 名之后就找不到节点，表现为“搜到但打不开”）
        force:    已加载过也重新加载（配合 show_all 把被截断的项补全）
        """
        if self._svc is None:
            return
        subdirs, files = self._svc.vfs.list_entries(dir_path)
        parent_item: QTreeWidgetItem
        if dir_path == "/":
            parent_item = self.tree.invisibleRootItem()
        else:
            # 找到对应节点（已被展开触发）
            parent_item = self._find_dir_item(dir_path)
        if parent_item is None:
            return
        # 已加载过则跳过（避免重复）；不能用 childCount 判断——
        # 目录可能已有子目录但文件尚未加载（如首次展开时提前返回）。
        key = self._svc.vfs.logical_path(dir_path)
        if key in self._loaded_dirs and not force:
            return
        if force:
            # 清空重建：占位项「还有 N 个文件」被真实文件替换
            parent_item.takeChildren()
        self._loaded_dirs.add(key)
        for name in subdirs:
            child_path = ("/" + name) if dir_path == "/" else dir_path + "/" + name
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.ItemDataRole.UserRole, child_path)
            item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            parent_item.addChild(item)
        # 文件节点：限制数量，避免一次性加入海量节点导致 UI 卡顿
        # 逻辑目录合并后，同名文件可能有多个原型类型（如 @content 骨架 +
        # content 视觉），此时在名字后标注类型以便区分。
        name_counts: dict = {}
        for f in files:
            name_counts[f.filename] = name_counts.get(f.filename, 0) + 1
        shown = 0
        cap = len(files) if show_all else self.MAX_FILES_PER_DIR
        for f in files:
            if shown >= cap:
                remaining = len(files) - shown
                placeholder = QTreeWidgetItem(
                    [f"… 还有 {remaining} 个文件（请用顶部搜索定位）"])
                placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
                placeholder.setFlags(
                    placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                parent_item.addChild(placeholder)
                break
            if f.prototype_type is None:
                # PKG 内原始存储的资源（assets.bin 无记录）：灰显 + 提示
                tname = "PKG 资源"
            else:
                tname = f.prototype_type.name
                if f.merged_skeleton:
                    # Lesta 的 .visual 拆成 Skeleton+Visual 两条记录，此处已合并为一个节点
                    tname += "（含骨架）"
            label = (f.filename if name_counts.get(f.filename, 0) == 1
                     else f"{f.filename}  [{tname}]")
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.ItemDataRole.UserRole, f.path)
            if f.prototype_type is None:
                item.setForeground(0, QBrush(QColor("#8f8f8f")))
            item.setToolTip(0, f"{f.path}  [{tname}]")
            parent_item.addChild(item)
            shown += 1

    def _find_dir_item(self, dir_path: str) -> Optional[QTreeWidgetItem]:
        """按路径在树中定位目录节点（沿已展开路径查找）。"""
        parts = [p for p in dir_path.split('/') if p]
        node: QTreeWidgetItem = self.tree.invisibleRootItem()
        for part in parts:
            found = None
            for i in range(node.childCount()):
                child = node.child(i)
                if child.text(0) == part and self._node_path(child) is not None:
                    found = child
                    break
            if found is None:
                return None
            node = found
        return node

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        path = self._node_path(item)
        if path:
            self._load_children_of(path)

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        path = self._node_path(item)
        if not path:
            return
        if self._svc is not None and self._svc.vfs.is_dir(path):
            item.setExpanded(not item.isExpanded())
            return
        self._show_file(path)

    def _show_file(self, path: str) -> None:
        if self._svc is None:
            return
        vfile = self._svc.vfs.get_file(path)
        if vfile is not None and vfile.prototype_type is None:
            # 无 prototype 记录：原始文件在 PKG 中，assets.bin 无法解码
            self._show_resource_hint(vfile)
            return
        self._current_path = path
        try:
            self._current_decoded = self._svc.vfs.decode_file(path)
        except (AssetsBinError, KeyError, ValueError, Exception) as e:  # noqa: BLE001
            self._current_decoded = None
            self.json_view.setPlainText(f"解码失败: {e}")
            self.status_label.setText(f"{path}")
            self._update_export_state()
            return
        self._render()
        self.status_label.setText(f"{path}")
        self._update_export_state()

    def _show_resource_hint(self, vfile: VirtualFile) -> None:
        """点击「PKG 内原始存储」的节点：只给提示，不做解码。

        这类条目只存在于 assets.bin 的路径表（无 prototype 记录），
        原始字节直接存放在客户端 `.pkg` 里，需自行解包才能查看内容。
        """
        self._current_path = vfile.path
        self._current_decoded = None
        self._update_export_state()
        vfs = self._svc.vfs if self._svc is not None else None
        is_fx = vfile.path.lower().endswith(".fx")
        # .fx 是着色器源码名，客户端里存的是编译产物 <同名>.win.dx11.fxo
        fxo_rel = ""
        fxo_state: Optional[bool] = None
        if is_fx and vfs is not None:
            fxo_rel = vfile.path[: -len(".fx")] + ".win.dx11.fxo"
            fxo_state = vfs.pkg_has(fxo_rel)
        if is_fx:
            if fxo_state is True:
                state = "该名字是着色器源码名；客户端内存放的是它的编译产物（下方路径，已确认存在）。"
            elif fxo_state is False:
                state = "该名字是着色器源码名；客户端内应有同名编译产物，但当前 PKG 中未找到。"
            else:
                state = "该名字是着色器源码名；客户端内存放的是它的编译产物（下方路径）。"
        elif vfile.in_pkg is True:
            state = "该文件确实直接存放在客户端 PKG 中（assets.bin 里只有路径，无记录）。"
        elif vfile.in_pkg is False:
            state = ("assets.bin 只有该路径条目，当前客户端 PKG 中未找到同名文件"
                     "（可能是内部资源名/别名，或本版本已移除）。")
        else:
            state = "该路径在 assets.bin 中没有 prototype 记录，原始文件直接存放在客户端 PKG 中。"
        lines = [f"路径：{vfile.path}", "", state, ""]
        if fxo_rel:
            lines += [f"编译产物：{fxo_rel}", ""]
        lines += ["assets.bin 浏览器只能解码带 prototype 记录的条目。",
                  "如需查看该文件内容，请自行解包（数据解包 → 按此路径导出）。"]
        self.json_view.setPlainText("\n".join(lines))
        self.status_label.setText(f"{vfile.path}  [PKG 资源，需解包查看]")

    #: 可明文导出的 prototype 类型 → (扩展名, 另存为过滤器)
    _EXPORT_KINDS = {
        "MaterialPrototype": (".mfm", "Material (*.mfm);;所有文件 (*)"),
        "VisualPrototype": (".visual", "Visual (*.visual);;所有文件 (*)"),
        "ModelPrototype": (".model", "Model (*.model);;所有文件 (*)"),
        "SkeletonExtenderPrototype": (".skel_ext",
                                      "SkeletonExtender (*.skel_ext);;所有文件 (*)"),
    }

    def _selected_export_files(self) -> list[VirtualFile]:
        """当前树中选中的、可明文导出的文件（Ctrl/Shift 多选，按选择顺序去重）。"""
        if self._svc is None:
            return []
        vfs = self._svc.vfs
        out: list[VirtualFile] = []
        seen: set[str] = set()
        for item in self.tree.selectedItems():
            path = self._node_path(item)
            if not path or path in seen:
                continue
            try:
                if vfs.is_dir(path):
                    continue
            except Exception:  # noqa: BLE001
                continue
            f = vfs.get_file(path)
            if f is None or f.prototype_type is None:
                continue
            if f.prototype_type.name not in self._EXPORT_KINDS:
                continue
            seen.add(path)
            out.append(f)
        return out

    def _update_export_state(self) -> None:
        """导出按钮在选中可明文导出的文件时启用（.mfm / .visual / .model / .skel_ext）。"""
        files = self._selected_export_files()
        n = len(files)
        self.btn_export_file.setEnabled(n > 0)
        self.btn_export_file.setText("导出明文" if n <= 1 else f"导出明文（{n}）")
        if n <= 0:
            self.btn_export_file.setToolTip(
                "明文导出所选文件——目前支持 .mfm / .visual / .model / .skel_ext"
                "（其他类型暂未支持；可 Ctrl/Shift 多选批量导出）")
        elif n == 1:
            ext = self._EXPORT_KINDS[files[0].prototype_type.name][0]
            self.btn_export_file.setToolTip(
                f"明文导出当前所选文件（{ext}，官方 Mod SDK 格式）")
        else:
            self.btn_export_file.setToolTip(
                f"明文导出所选 {n} 个文件（选择目标文件夹）")

    def _render(self) -> None:
        """根据当前显示模式重绘右侧内容（JSON / 明文）。"""
        decoded = self._current_decoded
        if decoded is None:
            return
        if self._mfm_plain:
            if self._is_material(decoded):
                self.json_view.setPlainText(self._mfm_text(self._current_path or "", decoded))
                return
            if self._is_visual(decoded):
                self.json_view.setPlainText(self._visual_text(self._current_path or "", decoded))
                return
            if self._is_model(decoded):
                self.json_view.setPlainText(self._model_text(self._current_path or "", decoded))
                return
            if self._is_skel_ext(decoded):
                self.json_view.setPlainText(self._skel_ext_text(self._current_path or "", decoded))
                return
        data = decoded
        fx_path = self._material_fx_path(decoded)
        if fx_path:
            data = _insert_after(decoded, "material_hash", "fx_path", fx_path)
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        except ValueError as e:
            text = f"无法序列化为 JSON: {e}"
        self.json_view.setPlainText(text)

    @staticmethod
    def _is_material(decoded) -> bool:
        return isinstance(decoded, dict) and decoded.get("_type") == "MaterialPrototype"

    def _material_fx_path(self, decoded) -> str:
        """mfm 的 fx 解析（独立功能）：material_hash → fx 路径。

        只查当前 assets.bin 的内存路径树，不读/写 assets_data.db；
        直接打开单个 assets.bin 文件时同样可用。
        """
        if not self._is_material(decoded) or self._svc is None:
            return ""
        from .mfm_fx import resolve_fx_path
        return resolve_fx_path(self._svc.db, decoded.get("material_hash") or "")

    @staticmethod
    def _is_visual(decoded) -> bool:
        return isinstance(decoded, dict) and decoded.get("_type") == "VisualPrototype"

    @staticmethod
    def _is_model(decoded) -> bool:
        return isinstance(decoded, dict) and decoded.get("_type") == "ModelPrototype"

    @staticmethod
    def _is_skel_ext(decoded) -> bool:
        return isinstance(decoded, dict) and decoded.get("_type") == "SkeletonExtenderPrototype"

    def _on_toggle_plain(self, checked: bool) -> None:
        self._mfm_plain = bool(checked)
        if (self._is_material(self._current_decoded) or self._is_visual(self._current_decoded)
                or self._is_model(self._current_decoded)
                or self._is_skel_ext(self._current_decoded)):
            self._render()
        elif checked:
            self.status_label.setText(
                "当前文件没有明文格式（仅 .mfm / .visual / .model / .skel_ext），保持 JSON 显示")

    def _mfm_text(self, path: str, decoded) -> str:
        """解码结果 → 官方 Mod SDK 明文 `.mfm` 文本。"""
        from .mfm_text import format_mfm_text
        name = (path or "").rsplit("/", 1)[-1] or "material.mfm"
        return format_mfm_text(decoded, name=name, fx=self._material_fx_path(decoded))

    def _visual_text(self, path: str, decoded) -> str:
        """解码结果 → 官方 Mod SDK 明文 `.visual` 文本（寄服/莱服两套格式）。"""
        from .visual_text import format_visual_text
        name = (path or "").rsplit("/", 1)[-1] or "visual.visual"
        return format_visual_text(decoded, name=name, wows_type=self._wows_type)

    def _model_text(self, path: str, decoded) -> str:
        """解码结果 → 官方 Mod SDK 明文 `.model` 文本（寄服/莱服两套格式）。"""
        from .model_text import format_model_text
        name = (path or "").rsplit("/", 1)[-1] or "model.model"
        return format_model_text(decoded, name=name, wows_type=self._wows_type)

    def _skel_ext_text(self, path: str, decoded) -> str:
        """解码结果 → 官方 Mod SDK 明文 `.skel_ext` 文本。"""
        from .skel_ext_text import format_skel_ext_text
        name = (path or "").rsplit("/", 1)[-1] or "skeleton_extender.skel_ext"
        return format_skel_ext_text(decoded, name=name)

    def _export_payload(self, path: str, decoded):
        """解码结果 → (标题, 过滤器, 默认文件名, 明文文本)；不支持的类型返回 None。"""
        name = (path or "").rsplit("/", 1)[-1]
        if self._is_material(decoded):
            return ("导出明文 .mfm", self._EXPORT_KINDS["MaterialPrototype"][1],
                    name or "material.mfm", self._mfm_text(path, decoded))
        if self._is_visual(decoded):
            return ("导出明文 .visual", self._EXPORT_KINDS["VisualPrototype"][1],
                    name or "visual.visual", self._visual_text(path, decoded))
        if self._is_model(decoded):
            return ("导出明文 .model", self._EXPORT_KINDS["ModelPrototype"][1],
                    name or "model.model", self._model_text(path, decoded))
        if self._is_skel_ext(decoded):
            return ("导出明文 .skel_ext",
                    self._EXPORT_KINDS["SkeletonExtenderPrototype"][1],
                    name or "skeleton_extender.skel_ext",
                    self._skel_ext_text(path, decoded))
        return None

    def _decode_for_export(self, path: str):
        """解码待导出文件（当前展示的那个直接复用缓存，避免重复解析）。"""
        if self._svc is None:
            return None
        if path == self._current_path and self._current_decoded is not None:
            return self._current_decoded
        try:
            return self._svc.vfs.decode_file(path)
        except Exception as e:  # noqa: BLE001
            self.status_label.setText(f"解码失败: {path} ({e})")
            return None

    @staticmethod
    def _visual_export_note(decoded) -> str:
        """visual 无节点记录时的提示后缀（单文件导出用）。"""
        skel = decoded.get("skeleton") or {}
        nodes = decoded.get("nodes") or {}
        has_tree = bool(skel.get("name_ids")) or (
            isinstance(nodes, dict) and bool(nodes.get("name_ids")))
        return "" if has_tree else "（该 visual 无节点记录，未包含节点树）"

    @staticmethod
    def _unique_export_name(name: str, used: dict) -> str:
        """同一批导出内的重名处理：`x.mfm` → `x (1).mfm`、`x (2).mfm`…"""
        p = Path(name)
        key = name.lower()
        n = used.get(key, 0)
        used[key] = n + 1
        return name if n == 0 else f"{p.stem} ({n}){p.suffix}"

    def _on_export_file(self) -> None:
        """明文导出所选文件：单个 → 另存为；多选 → 选文件夹批量导出。"""
        files = self._selected_export_files()
        if not files:
            self.status_label.setText(
                "当前所选文件暂不支持明文导出（仅 .mfm / .visual / .model / .skel_ext）")
            return
        if len(files) == 1:
            self._export_single_file(files[0])
        else:
            self._export_many_files(files)

    def _export_single_file(self, f: VirtualFile) -> None:
        """单文件导出：弹「另存为」。"""
        path = f.path
        decoded = self._decode_for_export(path)
        if decoded is None:
            QMessageBox.warning(self, "导出失败", f"无法解码该文件：\n{path}")
            return
        payload = self._export_payload(path, decoded)
        if payload is None:
            self.status_label.setText(
                f"{f.filename} 暂不支持明文导出（仅 .mfm / .visual / .model / .skel_ext）")
            return
        caption, filt, default, text = payload
        out, _sel = QFileDialog.getSaveFileName(self, caption, default, filt)
        if not out:
            return
        try:
            Path(out).write_text(text, encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))
            return
        note = self._visual_export_note(decoded) if self._is_visual(decoded) else ""
        self.status_label.setText(f"已导出: {out}{note}")

    def _export_many_files(self, files: list[VirtualFile]) -> None:
        """多文件导出：选目标文件夹，逐个写明文（同名自动加序号）。"""
        n = len(files)
        if n > 200:
            ret = QMessageBox.question(
                self, "批量导出",
                f"将导出 {n} 个文件，可能耗时较长（大 .visual 需要完整解码）。\n"
                "是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        out_dir = QFileDialog.getExistingDirectory(
            self, f"选择导出文件夹（{n} 个文件）", self._last_export_dir or "")
        if not out_dir:
            return
        self._last_export_dir = out_dir
        dest = Path(out_dir)
        used: dict[str, int] = {}
        exported = 0
        failed: list[str] = []
        t0 = time.time()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i, f in enumerate(files, 1):
                self.status_label.setText(f"导出明文 {i}/{n}：{f.filename}")
                QApplication.processEvents()
                decoded = self._decode_for_export(f.path)
                payload = self._export_payload(f.path, decoded) if decoded else None
                if payload is None:
                    failed.append(f.filename)
                    continue
                _caption, _filt, default, text = payload
                name = self._unique_export_name(default or f.filename, used)
                try:
                    (dest / name).write_text(text, encoding="utf-8")
                    exported += 1
                except OSError as e:
                    failed.append(f"{f.filename}({e})")
        finally:
            QApplication.restoreOverrideCursor()
        msg = f"已导出 {exported}/{n} 个文件 → {out_dir}（{time.time() - t0:.1f}s）"
        if failed:
            more = f" 等 {len(failed)} 个" if len(failed) > 3 else ""
            msg += f"；失败: {', '.join(failed[:3])}{more}"
        self.status_label.setText(msg)
        (QMessageBox.information if not failed else QMessageBox.warning)(
            self, "导出完成", msg)

    # ── 搜索 ────────────────────────────────────────────

    def _on_search(self) -> None:
        """搜索入口：在**当前目录树中直接定位**匹配文件，不另开结果界面。

        - 首次回车：扫描命中并定位到第 1 个；
        - 同一关键词再次回车：循环定位下一个命中；
        - 空关键词回车：清空搜索导航状态。
        """
        if self._svc is None:
            return
        keyword = self.search_edit.text().strip()
        if not keyword:
            self._reset_search_nav()
            self.status_label.setText("搜索已清空")
            return
        mode = self.search_mode.currentIndex()
        key = (mode, keyword)
        if key == self._search_key and self._search_hits:
            self._search_hit_index = (
                (self._search_hit_index + 1) % len(self._search_hits))
            self._locate_hit()
            return
        self._search_key = key
        if mode == 1:
            self._search_fx(keyword)
        else:
            self._search_files(keyword)

    def _search_files(self, keyword: str) -> None:
        """文件名部分匹配（多关键词 AND）；文件名命中优先，其次完整路径。"""
        words = [w for w in keyword.lower().split() if w]
        if not words:
            return
        limit = self.MAX_SEARCH_RESULTS
        name_hits: list[str] = []
        path_hits: list[str] = []
        for f in self._svc.vfs.all_files():
            name = f.filename.lower()
            if all(w in name for w in words):
                if len(name_hits) < limit:
                    name_hits.append(f.path)
            elif all(w in f.path.lower() for w in words):
                if len(path_hits) < limit:
                    path_hits.append(f.path)
            if len(name_hits) >= limit:
                break
        hits = [(p, "") for p in (name_hits + path_hits)[:limit]]
        # 同一逻辑路径只保留一个命中（@content 骨架与 content 视觉在树中已合并）
        best: dict = {}
        order: list = []
        for p, _ in hits:
            key = self._svc.vfs.logical_path(p)
            if key not in best:
                best[key] = p
                order.append(key)
            elif best[key].startswith("/@") and not p.startswith("/@"):
                best[key] = p
        self._set_search_hits(f"搜索「{keyword}」", [best[k] for k in order])

    def _search_fx(self, keyword: str) -> None:
        """按 fx 搜索：首次需建立索引（后台线程），之后即时。"""
        if self._fx_index is None:
            if self._fx_worker is not None and self._fx_worker.isRunning():
                self._pending_fx_query = keyword
                return
            self._pending_fx_query = keyword
            self.status_label.setText("正在建立 fx 索引（首次较慢，之后即时）...")
            self._fx_worker = _FxIndexWorker(self._svc, self._wows_type, parent=self)
            self._fx_worker.progress.connect(self._on_fx_progress)
            self._fx_worker.done.connect(self._on_fx_index_ready)
            self._fx_worker.failed.connect(
                lambda m: self.status_label.setText(f"fx 索引建立失败: {m}"))
            self._fx_worker.start()
            return
        self._apply_fx_search(keyword)

    def _on_fx_progress(self, done: int, total: int) -> None:
        self.status_label.setText(f"正在建立 fx 索引... {done}/{total}")

    def _on_fx_index_ready(self, index: list) -> None:
        self._fx_index = index
        self.status_label.setText(f"fx 索引就绪（{len(index)} 个材质）")
        query, self._pending_fx_query = self._pending_fx_query, ""
        if query:
            self._apply_fx_search(query)

    def _apply_fx_search(self, keyword: str) -> None:
        """在 fx 索引里匹配：fx 路径、shader_id、material_hash 均可搜。"""
        words = [w for w in keyword.lower().split() if w]
        if not words:
            return
        hits: list[tuple[str, str]] = []
        for path, fx, sh, mh in self._fx_index or []:
            hay = f"{fx} {sh} {mh}".lower()
            if all(w in hay for w in words):
                note = fx or f"{sh} (无法解析 fx)"
                hits.append((path, note))
                if len(hits) >= self.MAX_SEARCH_RESULTS:
                    break
        self._set_search_hits(f"fx「{keyword}」", [p for p, _ in hits])

    def _set_search_hits(self, title: str, paths: list) -> None:
        """保存命中列表并定位到第 1 个（目录树原地展开/选中，不替换树）。"""
        self._search_title = title
        self._search_hits = list(paths)
        self._search_hit_index = 0
        if not self._search_hits:
            self.status_label.setText(f"{title}: 未找到匹配")
            return
        self._locate_hit()

    def _locate_hit(self) -> None:
        """在目录树中展开并选中当前命中文件。"""
        if not self._search_hits:
            return
        idx = self._search_hit_index
        path = self._search_hits[idx]
        vf = self._display_file_for(path)
        total = len(self._search_hits)
        if vf is None:
            self.status_label.setText(
                f"{self._search_title}: {idx + 1}/{total}  {path}（无法定位）")
            return
        self._reveal_file(vf)
        limit_note = ("，已达上限"
                      if total >= self.MAX_SEARCH_RESULTS else "")
        self.status_label.setText(
            f"{self._search_title}: {idx + 1}/{total}  {path}"
            f"（回车定位下一个{limit_note}）")

    def _reset_search_nav(self) -> None:
        self._search_key = ()
        self._search_title = ""
        self._search_hits = []
        self._search_hit_index = 0

    def _display_file_for(self, path: str) -> Optional[VirtualFile]:
        """搜索路径 → 目录树中的显示节点。

        `@content/...` 的骨架记录已与同名视觉记录合并为单一节点，
        定位/显示时用合并后的 Visual 节点。
        """
        vf = self._svc.vfs.get_file(path)
        if vf is None:
            return None
        if (vf.prototype_type is not None
                and vf.prototype_type.name == "SkeletonPrototype"):
            merged = self._svc.vfs.get_file(self._svc.vfs.logical_path(path))
            if merged is not None and merged is not vf:
                return merged
        return vf

    def _reveal_file(self, vfile: VirtualFile) -> None:
        """展开祖先目录并选中文件节点（目录树按逻辑路径合并 @content）。

        逐级**显式加载**子项后再查找，不依赖 itemExpanded 信号时序。
        """
        parts = [p for p in self._svc.vfs.logical_path(vfile.path).split('/') if p]
        node: QTreeWidgetItem = self.tree.invisibleRootItem()
        cur_path = "/"
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            # 确保当前目录的子项已加载（root 已由 _build_root 加载）
            if cur_path != "/":
                self._load_children_of(cur_path)
            target = vfile.path if is_last else None
            found = None
            for j in range(node.childCount()):
                child = node.child(j)
                if target is not None:
                    # 文件节点文本可能带 [类型] 后缀，按原始路径匹配
                    if child.data(0, Qt.ItemDataRole.UserRole) == target:
                        found = child
                        break
                elif child.text(0) == part:
                    found = child
                    break
            if found is None:
                if not is_last:
                    return
                # 目录文件数超过 MAX_FILES_PER_DIR 时树里只有前 N 个 → 全量重载后重试
                self._load_children_of(cur_path, show_all=True, force=True)
                found = self._find_child_by_path(node, target)
                if found is None:
                    # 仍找不到（理论上不再发生）：直接打开内容，避免“点了没反应”
                    self._show_file(vfile.path)
                    self.status_label.setText(
                        f"{vfile.path}（目录过大，已在右侧直接打开）")
                    return
            node = found
            cur_path = ("/" + part) if cur_path == "/" else cur_path + "/" + part
            if not is_last:
                node.setExpanded(True)
        self.tree.setCurrentItem(node)
        self.tree.scrollToItem(node)
        self._show_file(vfile.path)

    @staticmethod
    def _find_child_by_path(parent: QTreeWidgetItem, path: Optional[str]):
        """在父节点的直接子项里按「原始路径」找节点（文件节点文本可能带类型后缀）。"""
        if not path:
            return None
        for j in range(parent.childCount()):
            child = parent.child(j)
            if child.data(0, Qt.ItemDataRole.UserRole) == path:
                return child
        return None

    # ── 打开 ────────────────────────────────────────────

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 assets.bin", "", "assets.bin (*.bin);;所有文件 (*)")
        if path:
            self._set_source_label(path)
            self.load_source(path)

    def _on_open_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择游戏目录（含 bin 与 res_packages）")
        if path:
            self._save_inherited_dir(path)
            self._bin_folder = None
            self._set_source_label(path)
            self.load_source(path)

    # ── 主应用目录继承 ─────────────────────────────────

    def _save_inherited_dir(self, path: str) -> None:
        """把浏览器中选择的游戏目录写回主应用配置（**仅当服务器类型一致**）。

        ⚠️ 主程序配置按当前 ``wows_type`` 分槽存路径（game_path_lesta /
        game_path_wargaming）。若浏览器里打开了另一服的客户端（如主程序是
        Lesta 却选了 WG 目录）直接写回，会把本服槽位指向另一服客户端，
        下次启动就会「用 Lesta 身份读 WG 数据」。所以这里先探测类型再决定。
        """
        try:
            from app.application import app
            detected = self._detect_wows_type(path) or self._wows_type
            current = getattr(app.config, "wows_type", "") or ""
            if current in ("Lesta", "Wargaming") and detected in ("Lesta", "Wargaming") \
                    and detected != current:
                self.status_label.setText(
                    f"该目录属于 {detected} 客户端，与主程序当前服务器（{current}）"
                    f"不一致，未写入配置")
                return
            old = app.config.game_path
            app.config.game_path = path
            if old and str(old) != str(path) and hasattr(app.config, "bin_folder"):
                app.config.bin_folder = ""  # 目录变了：版本号交给自动探测，避免旧 bin 号报「已不存在」
        except Exception:  # noqa: BLE001
            pass

    def _set_source_label(self, path: str) -> None:
        tag = "WG" if self._wows_type == "Wargaming" else "Lesta"
        self.source_label.setText(f"来源: {Path(path).name}  [{tag}] 类型表")

    # ── 关闭与索引缓存清理 ─────────────────────────────

    def closeEvent(self, event) -> None:
        """关闭窗口：若存在 .uncode_cache 索引缓存，弹出询问是否清理。

        清理后下次打开同一 assets.bin 需重新构建索引（加载变慢）；
        保留则下次秒开。索引缓存读取功能本身不受影响。
        仅删除本浏览器写入的 idx_*.pkl（目录可能还含其他工具缓存）。
        """
        cache_dir = None
        if self._svc is not None:
            cp = getattr(self._svc, "cache_path", None)
            if cp is not None:
                cache_dir = Path(cp).parent
        if cache_dir is not None and cache_dir.is_dir() \
                and any(cache_dir.glob("idx_*.pkl")):
            ans = QMessageBox.question(
                self, "清理索引缓存",
                f"检测到 assets.bin 索引缓存：\n{cache_dir}\n\n"
                "是否在关闭时清理该索引缓存？\n"
                "清理后下次打开同一文件将重新构建索引（加载变慢）。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                for f in cache_dir.glob("idx_*.pkl"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
                # 目录已空则一并删除
                try:
                    if not any(cache_dir.iterdir()):
                        cache_dir.rmdir()
                except OSError:
                    pass
        event.accept()


def main(argv: Optional[list] = None) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(argv or sys.argv)
    app.setStyle("Fusion")
    source = sys.argv[1] if len(sys.argv) > 1 else None
    win = AssetsBinViewer(source=source)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
