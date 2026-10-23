"""AssetsBinViewer —— assets.bin 可视化浏览/解码界面（PySide6）。

功能：
  - 打开已解压的 assets.bin 文件或直接选择游戏目录（自动用 data_extractor 提取）
  - **解析规则**：直接打开 assets.bin 文件时由用户在工具栏下拉框选择
    （Lesta / Wargaming / 远古版本）；选择游戏目录时按客户端自动识别
    （game_info.xml 版本早于 2023-08 → 远古版本模式，目前按 Lesta 解析；
    没有 game_info.xml 的 Steam/depot 老客户端改按库内原型类型判断，
    Skeleton 且无 ModelFbx/MiscSettings/Trail/VfxMaterial 即判为远古版本）
  - 选择游戏目录**只影响本窗口**：不写回主程序的 game_path / bin_folder 配置
  - 打开窗口时不自动载入数据，由用户手动选择数据源
  - 后台线程加载解析（避免卡 UI），左侧懒加载虚拟文件树
  - 文件树为「名称 + 类型」两列：目录与文件一眼可分；两列宽度可拖动，默认铺满左侧面板
  - 粒子 `/particles/xxx.xml` 的 `high` / `low` / `shared` 在树里**折叠成一行**
    （类型列写 `粒子效果 .xml`），点它/导出即得合并后的整份明文
  - 点击文件在右侧显示解码 JSON（深色等宽主题）
  - 顶部搜索：文件名/路径模糊匹配（多关键词交集），或按材质 **fx** 搜索
    （列出使用该 fx 的 `.mfm`；首次建立索引仅需秒级，之后即时）
  - 明文导出：单文件弹「另存为」；**多选（Ctrl/Shift）时选文件夹批量导出**
  - 粒子 `.xml` 的 `high` / `low` / `shared` 会**合成一份**明文（格式对齐游戏自带的
    粒子 XML，例如 `helpers/particles/sfx_fail.xml`），文件名 `<名字>.xml`
  - 粒子图集 `.contours`（`AtlasContourProto`）也有明文：每帧点数 + 轮廓点坐标
  - 状态栏显示数据库概览
  - 关闭窗口时询问是否清理 .uncode_cache 索引缓存

⚠️ **明文转码（.mfm / .visual / .model / .skel_ext / 粒子 .xml / .contours）为实验性功能**：
   assets.bin 与 Mod SDK 明文字段并非一一对应（如 `sortOrder` 二进制里有但 SDK
   不导出、`<parentMfm>` 继承链二进制里没有），部分数据可能与官方 SDK 导出结果
   存在差异，请以游戏内实际表现为准。粒子部分覆盖 `high`/`low`
   （`EffectPrototype`）与 `shared`（`EffectMetadataPrototype`）两类记录，
   导出时按 `<high>` / `<low>` / `<shared>` 三段写进同一个文件。

独立运行：  python -m uncode_assets.gui [assets.bin 或 游戏目录]
也可由主程序通过 AssetsBinViewer(source) 打开。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QThread, Signal, QEvent
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QPushButton, QLabel, QFileDialog, QLineEdit, QStatusBar, QToolBar,
    QHeaderView, QAbstractItemView, QMessageBox, QComboBox, QApplication, QSizePolicy,
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
)

from .errors import AssetsBinError
from ui.widgets import HoloDialog, HoloWindow
from utils.theme import theme
from .parse_rules import (RULE_AUTO, RULE_LABELS, RULE_LESTA, RULE_LEGACY,
                          RULE_SHORT_LABELS, RULE_WARGAMING, RULE_WG_OLD,
                          detect_rule, layout_for_rule, model_meta_for_rule,
                          version_text)
from .service import AssetsBinService
from .vfs import VirtualFile




class _SourceLabel(QLabel):
    """工具栏「来源」标签：路径按可用宽度中间省略，结论（规则/版本）永远完整。

    路径可能很长（``...\\res_unpack\\content\\assets.bin``），但工具栏不能因此把窗口撑宽，
    所以 sizeHint 固定为一个中等宽度、文本按实际宽度省略；完整路径与判定依据放 tooltip。
    最小尺寸给得很小，空间不足时只缩短文字，而不是被收进工具栏的「»」溢出菜单。
    标签占满工具栏剩余宽度并右对齐，文字贴着右边缘显示。
    """

    #: 期望宽度（决定工具栏分给它的空间；不影响窗口最小宽度）
    PREFERRED_WIDTH = 360
    #: 最小宽度（再窄就整段省略，只留规则结论）
    MIN_WIDTH = 110

    def __init__(self, parent=None):
        super().__init__(parent)
        # 右对齐：标签撑满工具栏剩余空间，文字紧贴右边缘
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._path = ""
        self._suffix = ""

    def sizeHint(self):  # noqa: N802 (Qt 命名)
        return QSize(self.PREFERRED_WIDTH, super().sizeHint().height())

    def minimumSizeHint(self):  # noqa: N802 (Qt 命名)
        return QSize(self.MIN_WIDTH, super().minimumSizeHint().height())

    def set_source(self, path_text: str, suffix: str) -> None:
        self._path, self._suffix = path_text, suffix
        self._refresh()

    def _refresh(self) -> None:
        fm = self.fontMetrics()
        # 左右各 10px padding（见 ui/widgets/dialog_style.py 的 QToolBar QLabel#source）+ 余量
        avail = self.width() - fm.horizontalAdvance(self._suffix) - 24
        if avail < 60:
            super().setText(self._suffix.strip())
            return
        shown = fm.elidedText(self._path, Qt.TextElideMode.ElideMiddle, avail)
        super().setText(f"{shown}{self._suffix}")

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._refresh()


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
            legacy = (self._wows_type or "").lower() == "legacy"
            # 只取记录头部：材质记录 0x58（远古）/0x78（WG）/0x88（莱服），避免整 blob 尾部拷贝
            need = 0x58 if legacy else (0x78 if wg else 0x88)
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
                 wows_type: str = "", model_meta: str = "", parent=None):
        super().__init__(parent)
        self._game_dir = game_dir
        self._assets_path = assets_path
        self._bin_folder = bin_folder
        self._wows_type = wows_type
        self._model_meta = str(model_meta or "")

    def run(self) -> None:
        try:
            if self._game_dir:
                # 传空 set 启用 PKG 文件树收集：资源节点据此标记「PKG 中确有该文件」
                svc = AssetsBinService(game_dir=self._game_dir, bin_folder=self._bin_folder,
                                       wows_type=self._wows_type, pkg_paths=set(),
                                       model_meta=self._model_meta)
            else:
                svc = AssetsBinService(assets_path=self._assets_path,
                                       wows_type=self._wows_type,
                                       model_meta=self._model_meta)
            self.loaded.emit(svc)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class _OpenAssetsDialog(HoloDialog):
    """「打开 assets.bin」对话框：选文件 + 选解析规则。

    裸 assets.bin 没有客户端信息可探测，规则必须在这里指定（浏览器界面里不再放规则选项）；
    选择游戏目录时仍由 :func:`uncode_assets.parse_rules.detect_rule` 自动识别。
    """

    def __init__(self, parent=None, path: str = "", rule: str = RULE_AUTO):
        super().__init__(parent)
        self.setWindowTitle("打开 assets.bin")
        self.setMinimumWidth(560)

        self.path_edit = QLineEdit(path)
        self.path_edit.setPlaceholderText("assets.bin 路径")
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._on_browse)

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(btn_browse)

        self.rule_combo = QComboBox()
        for key, text in RULE_LABELS.items():
            self.rule_combo.addItem(text, key)
        idx = self.rule_combo.findData(rule)
        if idx >= 0:
            self.rule_combo.setCurrentIndex(idx)

        hint = QLabel(
            "解析规则决定用哪套记录布局解码：\n"
            "• 自动 → 按 assets.bin 里的原型类型自动判断（推荐）\n"
            "• Lesta（莱服）→ 适配Lesta现版本客户端（26.10）\n"
            "• Wargaming（寄服）→ 适配寄服 14.1 及以后（15.9）的新记录布局\n"
            "• 寄服旧布局（14.0 及更早）→ 13.x / 14.0 的寄服客户端，记录布局同 Lesta\n"
            "• 远古版本 → 2023-08（12.7）之前的老客户端（未分家，只有一个客户端）")
        hint.setWordWrap(True)
        hint.setObjectName("info")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("assets.bin 文件"))
        layout.addLayout(path_row)
        layout.addSpacing(8)
        layout.addWidget(QLabel("解析 / 明文规则"))
        layout.addWidget(self.rule_combo)
        layout.addSpacing(8)
        layout.addWidget(hint)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        start = self.path_edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 assets.bin", str(Path(start).parent) if start else "",
            "assets.bin (*.bin);;所有文件 (*)")
        if path:
            self.path_edit.setText(path)

    def _on_accept(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.information(self, "打开 assets.bin", "请先选择 assets.bin 文件")
            return
        self.accept()

    def selected_path(self) -> str:
        return self.path_edit.text().strip()

    def selected_rule(self) -> str:
        return self.rule_combo.currentData() or RULE_AUTO


class AssetsBinViewer(HoloWindow):
    """assets.bin 可视化浏览器。"""

    #: 每个目录最多直接显示的文件节点数，超出显示占位项（避免大目录卡死 UI）
    MAX_FILES_PER_DIR = 1000
    #: 搜索结果最多列出的条目数
    MAX_SEARCH_RESULTS = 2000
    #: 初始窗口尺寸下限 / 上限（树 + JSON 并排，太窄看不全路径）
    PREFERRED_MIN_SIZE = (1440, 900)
    PREFERRED_MAX_SIZE = (1920, 1200)

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
        # 服务器类型表：本窗口独立判定，不继承主应用设置
        # （载入时由 parse_rules 自动识别或按对话框所选规则决定）
        self._wows_type = "Lesta"
        #: 解析/明文规则（auto / Lesta / Wargaming / legacy）——窗口级，不写回配置
        self._rule = RULE_AUTO
        #: 「自动」判定的依据说明（由服务回填，仅用于状态显示）
        self._auto_reason = ""
        #: 「自动」判定的规则（由服务回填：Lesta / Wargaming / legacy；未判定为空串）
        self._auto_rule = ""
        #: 「自动」没能判定（库里只有两服共有类型），服务已退回默认 Lesta
        self._auto_undetermined = False
        #: 上一次加载的来源（切换规则时重载用）
        self._last_source = ""
        self._source_is_dir = False
        #: 从 game_info.xml 读到的客户端版本（仅目录载入时可用）
        self._client_version = None
        self.setWindowTitle("assets.bin 浏览器")
        self._apply_preferred_size()
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

        self.btn_plain = QPushButton("明文格式（实验性）")
        self.btn_plain.setCheckable(True)
        self.btn_plain.setToolTip(
            "以官方 Mod SDK 明文样式显示（材质 .mfm / 视觉 .visual / 模型 .model / 粒子 .xml）\n"
            "⚠️ 实验性功能：assets.bin 与 SDK 明文字段并非一一对应，\n"
            "部分数据可能与官方导出结果存在差异，请以游戏内实际表现为准。")
        self.btn_plain.toggled.connect(self._on_toggle_plain)
        toolbar.addWidget(self.btn_plain)

        self.btn_export_file = QPushButton("导出明文")
        self.btn_export_file.setToolTip(
            "明文导出所选文件（可 Ctrl/Shift 多选，批量导出到文件夹）\n"
            "⚠️ 实验性功能：转码结果可能与官方 Mod SDK 导出存在差异。")
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

        # 「来源」放回工具栏右侧：_SourceLabel 的 sizeHint/minimumSizeHint 都很小，
        # 可用宽度不足时只会把路径中间省略（tooltip 里始终有完整路径与判定依据）。
        self.source_label = _SourceLabel()
        self.source_label.setObjectName("source")
        self.source_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Preferred)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._source_tip = (
            "当前数据来源与解析规则\n"
            "本窗口独立判定：载入时按客户端类型 / 库内原型类型自动识别，\n"
            "或按「打开 assets.bin」对话框里选的规则；\n"
            "不继承、也不影响主应用的服务器设置")
        self.source_label.setToolTip(self._source_tip)
        toolbar.addWidget(self.source_label)

        # 计数（概览）留在状态栏：内容会随加载变长，放工具栏容易被挤进「»」溢出菜单
        self.info_label = QLabel("未加载")
        self.info_label.setObjectName("info")
        self.info_label.setToolTip("assets.bin 概览")

        # 中央：树 + JSON
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self.tree = QTreeWidget()
        # 两列：名称 + 类型 —— 粒子的 `/particles/xxx.xml` 是**目录**，
        # 它下面的 high/low/shared 才是文件；只显示名字无法区分，故用类型列标注。
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["名称", "类型"])
        hdr = self.tree.header()
        # 两列都可拖动改宽；最后一列拉伸填满左侧面板（不留空白带）
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setMinimumSectionSize(56)
        # 初始列宽（真正显示后再按面板宽度重新分配，见 _fit_tree_columns）
        self.tree.setColumnWidth(0, self.NAME_COLUMN_WIDTH)
        self.tree.setColumnWidth(1, self.TYPE_COLUMN_WIDTH)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setAutoScroll(True)
        # 面板尺寸变化时重新分配列宽；用户手动拖过分隔线后就不再自动分配
        self._last_fit_name_w = -1
        self.tree.viewport().installEventFilter(self)
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

        # 状态栏：左侧概览（信息），右侧当前状态
        status = QStatusBar()
        self.setStatusBar(status)
        status.addWidget(self.info_label)
        self.status_label = QLabel("就绪")
        status.addPermanentWidget(self.status_label)

    # ── 窗口定位 ────────────────────────────────────────

    def _apply_preferred_size(self) -> None:
        """按可用屏幕放大初始窗口：默认铺满约 95% 可用区域，并夹在 min/max 之间。"""
        min_w, min_h = self.PREFERRED_MIN_SIZE
        max_w, max_h = self.PREFERRED_MAX_SIZE
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(min_w, min_h)
            return
        avail = screen.availableGeometry()
        w = max(min_w, int(avail.width() * 0.95))
        h = max(min_h, int(avail.height() * 0.95))
        self.resize(min(w, max_w, avail.width()), min(h, max_h, avail.height()))

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
        self._last_source = str(p)
        self._source_is_dir = p.is_dir()
        self.info_label.setText("加载中...")
        # 上一次加载的自动判定结果作废，避免加载期间显示旧依据
        self._auto_reason = ""
        self._auto_rule = ""
        self._auto_undetermined = False
        if self._source_is_dir:
            # 客户端目录：按客户端版本判定（<12.7 → 远古版本；寄服 <14.1 → 旧布局）；
            # 没有可执行文件（只有 .pkg）→ auto，交给库内原型类型判定
            rule, version = detect_rule(str(p))
            self._rule = rule
            self._client_version = version
            # auto 时交给服务按库内原型判定
            self._wows_type = ("auto" if rule == RULE_AUTO
                               else layout_for_rule(rule))
            self._set_source_label(str(p))
            self._worker = _LoadWorker(game_dir=str(p), bin_folder=self._bin_folder,
                                       wows_type=self._wows_type,
                                       model_meta=model_meta_for_rule(rule, version),
                                       parent=self)
        else:
            # 裸 assets.bin：规则在「打开 assets.bin」对话框里选。
            # 选「自动」时交给服务按库内原型魔数判定（不是回退主程序设置）。
            self._client_version = None
            self._wows_type = "auto" if self._rule == RULE_AUTO else layout_for_rule(self._rule)
            self._set_source_label(str(p))
            self._worker = _LoadWorker(assets_path=str(p),
                                       wows_type=self._wows_type,
                                       model_meta=model_meta_for_rule(self._rule),
                                       parent=self)
        # Kraken 容器解压只有现代莱服 .pkg 才有（寄服 / 远古版本都是 raw-deflate，很快）；
        # 裸 assets.bin 直接读文件，同样不涉及解压。
        if not self._source_is_dir:
            self.status_label.setText("正在加载/解析 assets.bin...")
        elif self._rule == RULE_LESTA:
            self.status_label.setText(
                "正在从游戏 .pkg 解压并解析 assets.bin...（莱服 Kraken 解压可能较慢）")
        elif self._rule == RULE_WARGAMING:
            self.status_label.setText("正在从游戏 .pkg 解压并解析 assets.bin...（raw-deflate 解压）")
        else:
            # 远古版本 / 无 game_info.xml（待判定）：不预先断言解压方式
            self.status_label.setText("正在从游戏 .pkg 解压并解析 assets.bin...")
        self._worker.loaded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._worker.start()

    def _on_loaded(self, svc: AssetsBinService) -> None:
        self._svc = svc
        # 「自动」规则由服务按原型魔数判定，这里同步结果用于显示
        pending_auto = self._wows_type == "auto"
        resolved = getattr(svc, "wows_type", "") or ""
        if resolved in ("Lesta", "Wargaming"):
            self._wows_type = resolved
        self._auto_reason = getattr(svc, "auto_rule_reason", "") or ""
        self._auto_rule = getattr(svc, "auto_rule", "") or ""
        # 旧布局（远古版本 / 寄服旧布局）：服务按库内原型判定出来时同步，
        # 用于 .model 的 metaData 等展示常量
        if getattr(svc, "legacy", False):
            self._rule = (RULE_LEGACY if self._auto_rule == RULE_LEGACY
                          else RULE_WG_OLD)
            self._wows_type = layout_for_rule(self._rule)
        self._auto_undetermined = bool(pending_auto
                                       and not getattr(svc, "auto_rule", ""))
        if self._last_source:
            self._set_source_label(self._last_source)
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
        self._fit_tree_columns()
        self._load_children_of("/")

    def _fit_tree_columns(self) -> None:
        """按左侧面板当前宽度分配两列：名称列优先，类型列拿剩余空间。

        最后一列由 ``stretchLastSection`` 自动填满，因此面板拉宽时不会留空白带；
        两列都是 Interactive，用户随时可以拖分隔线改宽度——一旦手动改过名称列宽度，
        之后面板尺寸变化就不再自动覆盖（见 :meth:`eventFilter`）。
        """
        avail = self.tree.viewport().width()
        if avail <= 0:
            avail = self.tree.width()
        if avail <= 0:
            name_w = self.NAME_COLUMN_WIDTH
            type_w = self.TYPE_COLUMN_WIDTH
        else:
            name_w = max(self.NAME_COLUMN_WIDTH, int(avail * 0.62))
            name_w = min(name_w, avail - self.MIN_TYPE_COLUMN_WIDTH)
            name_w = max(140, name_w)
            type_w = max(self.MIN_TYPE_COLUMN_WIDTH, avail - name_w)
        self.tree.setColumnWidth(0, name_w)
        self.tree.setColumnWidth(1, type_w)
        self._last_fit_name_w = name_w

    def eventFilter(self, obj, event):  # noqa: N802 (Qt 命名)
        if obj is self.tree.viewport() and event.type() == QEvent.Type.Resize:
            # 名称列宽度仍等于上次自动分配值 ⇒ 用户没拖过，可以按新宽度重新分配
            if self.tree.columnWidth(0) == self._last_fit_name_w:
                self._fit_tree_columns()
        return super().eventFilter(obj, event)

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
        # 粒子分组已被折叠成叶子节点（数据不是目录）→ 不再往下加载
        parent_path = self._node_path(parent_item)
        if (parent_item is not self.tree.invisibleRootItem()
                and parent_path and not self._svc.vfs.is_dir(parent_path)):
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
            primary = self._particle_part_file(child_path)
            if primary:
                # 粒子 .xml 的 high/low/shared 只是同一份 XML 的分区：折成一行
                parent_item.addChild(self._particle_leaf_item(name, primary))
                continue
            item = QTreeWidgetItem([name, self.DIR_LABEL])
            item.setData(0, Qt.ItemDataRole.UserRole, child_path)
            item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            item.setForeground(1, QBrush(theme.qcolor("text_hint")))
            item.setToolTip(1, "目录（点开才会加载下层）")
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
                tlabel = "PKG 资源（需解包）"
            else:
                tname = f.prototype_type.name
                if f.merged_skeleton:
                    # Lesta 的 .visual 拆成 Skeleton+Visual 两条记录，此处已合并为一个节点
                    tname += "（含骨架）"
                tlabel = self._TYPE_LABELS.get(
                    f.prototype_type.name, f.prototype_type.description or tname)
            label = (f.filename if name_counts.get(f.filename, 0) == 1
                     else f"{f.filename}  [{tname}]")
            item = QTreeWidgetItem([label, tlabel])
            item.setData(0, Qt.ItemDataRole.UserRole, f.path)
            if f.prototype_type is None:
                item.setForeground(0, QBrush(theme.qcolor("text_hint")))
            item.setToolTip(0, f"{f.path}  [{tname}]")
            item.setToolTip(1, tname)
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
        "EffectPrototype": (".xml", "Particle XML (*.xml);;所有文件 (*)"),
        "EffectMetadataPrototype": (".xml", "Particle XML (*.xml);;所有文件 (*)"),
        "AtlasContourProto": (".contours", "Atlas contour (*.contours);;所有文件 (*)"),
    }

    #: 树里「类型」列的显示名（缺少时退回 PrototypeType.description）
    _TYPE_LABELS = {
        "MaterialPrototype": "材质 .mfm",
        "VisualPrototype": "模型 .visual",
        "ModelPrototype": "模型 .model",
        "SkeletonPrototype": "骨架 .visual",
        "SkeletonExtenderPrototype": "骨架扩展 .skel_ext",
        "EffectPrototype": "粒子效果 .xml",
        "EffectMetadataPrototype": "粒子元数据 .xml",
        "EffectPresetPrototype": "粒子预设 .effect_preset",
        "TrailPrototype": "粒子轨迹 .trail",
        "VfxMaterialPrototype": "VFX 材质 .vfx",
        "AtlasContourProto": "图集轮廓 .contours",
        "ModelFbxPrototype": "FBX 模型 .model_fbx",
        "PointLightPrototype": "点光源 .point_light",
        "VelocityFieldPrototype": "速度场 .velocity_field",
        "MiscSettingsPrototype": "杂项设置",
    }

    #: 目录节点在「类型」列的文字
    DIR_LABEL = "文件夹"

    #: 文件树「名称」列默认宽度（未测量到面板宽度时用）
    NAME_COLUMN_WIDTH = 260
    #: 文件树「类型」列默认宽度 / 最小可用宽度
    TYPE_COLUMN_WIDTH = 180
    MIN_TYPE_COLUMN_WIDTH = 120

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
        """导出按钮在选中可明文导出的文件时启用（.mfm / .visual / .model / .skel_ext / 粒子 .xml / .contours）。"""
        files = self._selected_export_files()
        n = len(files)
        self.btn_export_file.setEnabled(n > 0)
        self.btn_export_file.setText("导出明文" if n <= 1 else f"导出明文（{n}）")
        if n <= 0:
            self.btn_export_file.setToolTip(
                "明文导出所选文件——目前支持 .mfm / .visual / .model / .skel_ext / "
                "粒子 .xml / .contours（其他类型暂未支持；可 Ctrl/Shift 多选批量导出）")
        elif n == 1:
            ext = self._EXPORT_KINDS[files[0].prototype_type.name][0]
            extra = ""
            if self._is_particle_path(files[0].path):
                extra = "；同一 .xml 的 high / low / shared 会合成一份"
            self.btn_export_file.setToolTip(
                f"明文导出当前所选文件（{ext}{extra}）")
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
            if self._is_effect(decoded) or self._is_effect_metadata(decoded):
                self.json_view.setPlainText(self._effect_text(self._current_path or "", decoded))
                return
            if self._is_contour(decoded):
                self.json_view.setPlainText(self._contour_text(self._current_path or "", decoded))
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

    @staticmethod
    def _is_effect(decoded) -> bool:
        return isinstance(decoded, dict) and decoded.get("_type") == "EffectPrototype"

    @staticmethod
    def _is_effect_metadata(decoded) -> bool:
        return (isinstance(decoded, dict)
                and decoded.get("_type") == "EffectMetadataPrototype")

    @staticmethod
    def _is_contour(decoded) -> bool:
        return isinstance(decoded, dict) and decoded.get("_type") == "AtlasContourProto"

    def _on_toggle_plain(self, checked: bool) -> None:
        self._mfm_plain = bool(checked)
        if (self._is_material(self._current_decoded) or self._is_visual(self._current_decoded)
                or self._is_model(self._current_decoded)
                or self._is_skel_ext(self._current_decoded)
                or self._is_effect(self._current_decoded)
                or self._is_effect_metadata(self._current_decoded)
                or self._is_contour(self._current_decoded)):
            self._render()
            if checked:
                self.status_label.setText(
                    "⚠️ 明文格式为实验性功能：assets.bin 与 SDK 明文字段并非一一对应，"
                    "部分数据可能与官方导出存在差异")
        elif checked:
            self.status_label.setText(
                "当前文件没有明文格式（仅 .mfm / .visual / .model / .skel_ext / "
                "粒子 .xml / .contours），保持 JSON 显示")

    def _mfm_text(self, path: str, decoded) -> str:
        """解码结果 → 官方 Mod SDK 明文 `.mfm` 文本。"""
        from .mfm_text import format_mfm_text
        name = (path or "").rsplit("/", 1)[-1] or "material.mfm"
        return format_mfm_text(decoded, name=name,
                               fx=self._material_fx_path(decoded),
                               wows_type=self._wows_type)

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

    def _effect_text(self, path: str, decoded) -> str:
        """解码结果 → 粒子 XML（同一 `.xml` 的 high / low / shared 合成一份）。"""
        from .fx import format_particle_text
        _base, file_name = self._particle_group(path)
        return format_particle_text(self._particle_parts(path, decoded),
                                    file_name or "effect.xml")

    def _contour_text(self, path: str, decoded) -> str:
        """解码结果 → 图集轮廓明文（每帧一组轮廓点）。"""
        from .atlas_contour import format_contours_text
        name = (path or "").rsplit("/", 1)[-1] or "atlas.contours"
        return format_contours_text(decoded, name)

    #: 粒子文件的分区名（同一 `.xml` 的三个分区会合成一份明文）
    _PARTICLE_PARTS = ("high", "low", "shared")

    @classmethod
    def _particle_group(cls, path: str) -> tuple[str, str]:
        """`/particles/foo.xml/high` → (`/particles/foo.xml`, `foo.xml`)；非分区返回空。"""
        parts = [p for p in (path or "").split("/") if p]
        if len(parts) >= 2 and parts[-1] in cls._PARTICLE_PARTS:
            return "/" + "/".join(parts[:-1]), parts[-2]
        return "", ""

    @classmethod
    def _is_particle_path(cls, path: str) -> bool:
        """路径是否是粒子文件的某个分区（`…/xxx.xml/high|low|shared`）。"""
        return bool(cls._particle_group(path)[0])

    def _particle_part_file(self, dir_path: str) -> str:
        """`…/xxx.xml` 若是只装 high/low/shared 的粒子分区目录，返回主分区文件路径。

        树里把它折成**一行**（点它直接看/导出合并后的整份 .xml 明文），
        所以这里同时充当「该目录是不是粒子分组」的判定。
        """
        if self._svc is None or not dir_path.lower().endswith(".xml"):
            return ""
        try:
            subdirs, files = self._svc.vfs.list_entries(dir_path)
        except Exception:  # noqa: BLE001
            return ""
        if subdirs or not files:
            return ""
        if any(f.filename not in self._PARTICLE_PARTS for f in files):
            return ""
        for part in self._PARTICLE_PARTS:
            target = f"{dir_path}/{part}"
            if self._svc.vfs.get_file(target) is not None:
                return target
        return ""

    def _particle_leaf_item(self, name: str, primary: str) -> QTreeWidgetItem:
        """粒子分组合并后的单行节点（数据仍指向某个分区，导出自带合并逻辑）。"""
        vf = self._svc.vfs.get_file(primary) if self._svc is not None else None
        tname = ("EffectPrototype" if vf is None or vf.prototype_type is None
                 else vf.prototype_type.name)
        tlabel = self._TYPE_LABELS.get(tname, tname)
        item = QTreeWidgetItem([name, tlabel])
        item.setData(0, Qt.ItemDataRole.UserRole, primary)
        item.setToolTip(0, f"/{name}：high / low / shared 已合并为一份明文")
        item.setToolTip(1, f"{tname}（同一 .xml 的分区合并显示为一行）")
        return item

    def _particle_parts(self, path: str, decoded) -> dict:
        """收集同一粒子文件各分区的解码结果（不存在/解码失败的分区跳过）。"""
        base, _name = self._particle_group(path)
        fallback = {"high": decoded} if self._is_effect(decoded) else {"shared": decoded}
        if not base:
            return fallback
        found: dict = {}
        for part in self._PARTICLE_PARTS:
            target = f"{base}/{part}"
            if target == path:
                found[part] = decoded
                continue
            if self._svc is None:
                continue
            try:
                if self._svc.vfs.get_file(target) is None:
                    continue
                found[part] = self._svc.vfs.decode_file(target)
            except Exception:  # noqa: BLE001  单个分区失败不影响整体导出
                continue
        return found or fallback

    @classmethod
    def _effect_default_name(cls, path: str) -> str:
        """`/particles/foo.xml/high` → `foo.xml`（三个分区合成同一份明文）。"""
        base, file_name = cls._particle_group(path)
        if file_name:
            return file_name if file_name.lower().endswith(".xml") else f"{file_name}.xml"
        name = (path or "").rsplit("/", 1)[-1]
        return name or "effect.xml"

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
        if self._is_effect(decoded) or self._is_effect_metadata(decoded):
            return ("导出粒子 XML", self._EXPORT_KINDS["EffectPrototype"][1],
                    self._effect_default_name(path), self._effect_text(path, decoded))
        if self._is_contour(decoded):
            return ("导出图集轮廓", self._EXPORT_KINDS["AtlasContourProto"][1],
                    name or "atlas.contours", self._contour_text(path, decoded))
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
                "当前所选文件暂不支持明文导出"
                "（仅 .mfm / .visual / .model / .skel_ext / 粒子 .xml）")
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
                f"{f.filename} 暂不支持明文导出"
                "（仅 .mfm / .visual / .model / .skel_ext / 粒子 .xml）")
            return
        caption, filt, default, text = payload
        out, _sel = QFileDialog.getSaveFileName(
            self, f"{caption}（实验性转码）", default, filt)
        if not out:
            return
        try:
            Path(out).write_text(text, encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))
            return
        note = self._visual_export_note(decoded) if self._is_visual(decoded) else ""
        self.status_label.setText(
            f"已导出: {out}{note}（⚠️ 实验性转码，可能与官方 Mod SDK 导出存在差异）")

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
            self, f"选择导出文件夹（{n} 个文件，实验性转码）", self._last_export_dir or "")
        if not out_dir:
            return
        self._last_export_dir = out_dir
        dest = Path(out_dir)
        used: dict[str, int] = {}
        done_groups: set[str] = set()
        exported = 0
        failed: list[str] = []
        t0 = time.time()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i, f in enumerate(files, 1):
                self.status_label.setText(f"导出明文 {i}/{n}：{f.filename}")
                QApplication.processEvents()
                group, _grp_name = self._particle_group(f.path)
                if group:
                    # high / low / shared 合成一份明文，同一粒子文件只写一次
                    if group in done_groups:
                        continue
                    done_groups.add(group)
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
        merged = len(done_groups)
        msg = f"已导出 {exported}/{n} 个文件 → {out_dir}（{time.time() - t0:.1f}s）"
        if merged:
            msg += f"；其中 {merged} 个粒子 .xml 由 high/low/shared 合成"
        if failed:
            more = f" 等 {len(failed)} 个" if len(failed) > 3 else ""
            msg += f"；失败: {', '.join(failed[:3])}{more}"
        self.status_label.setText(msg)
        (QMessageBox.information if not failed else QMessageBox.warning)(
            self, "导出完成",
            msg + "\n\n⚠️ 明文转码为实验性功能：assets.bin 与 Mod SDK 明文字段"
                  "并非一一对应，部分数据可能与官方导出存在差异。")

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
        # 同一逻辑路径只保留一个命中（@content 骨架与 content 视觉在树中已合并）；
        # 同一粒子 .xml 的 high/low/shared 在树里也是一行，只留一条命中。
        best: dict = {}
        order: list = []
        for p, _ in hits:
            group, _grp = self._particle_group(p)
            key = ("P:" + group) if group else self._svc.vfs.logical_path(p)
            if key not in best:
                best[key] = p
                order.append(key)
            elif group:
                if (self._PARTICLE_PARTS.index(p.rsplit("/", 1)[-1])
                        < self._PARTICLE_PARTS.index(best[key].rsplit("/", 1)[-1])):
                    best[key] = p
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

    def _tree_location(self, path: str) -> tuple[str, str]:
        """路径 → （树中所在目录, 该节点保存的路径）。

        粒子 `/x.xml/high` 在树里被并成 `/x.xml` 那一行，节点数据仍是主分区
        （`/high` 优先），所以搜索定位要落到那一行上。
        """
        base, _name = self._particle_group(path)
        if base:
            parts = [p for p in path.split("/") if p]
            parent = "/" + "/".join(parts[:-2]) if len(parts) > 2 else "/"
            return parent, (self._particle_part_file(base) or path)
        parent = self._svc.vfs.logical_path(path).rpartition("/")[0] or "/"
        return parent, path

    def _reveal_file(self, vfile: VirtualFile) -> None:
        """展开祖先目录并选中文件节点（目录树按逻辑路径合并 @content）。

        逐级**显式加载**子项后再查找，不依赖 itemExpanded 信号时序。
        """
        parent_dir, node_path = self._tree_location(vfile.path)
        dir_parts = [p for p in parent_dir.split('/') if p]
        node: QTreeWidgetItem = self.tree.invisibleRootItem()
        cur_path = "/"
        for part in dir_parts:
            # 确保当前目录的子项已加载（root 已由 _build_root 加载）
            if cur_path != "/":
                self._load_children_of(cur_path)
            found = None
            for j in range(node.childCount()):
                child = node.child(j)
                if child.text(0) == part and self._node_path(child) is not None:
                    found = child
                    break
            if found is None:
                return
            node = found
            cur_path = ("/" + part) if cur_path == "/" else cur_path + "/" + part
            node.setExpanded(True)
        if cur_path != "/":
            self._load_children_of(cur_path)
        found = self._find_child_by_path(node, node_path)
        if found is None:
            # 目录文件数超过 MAX_FILES_PER_DIR 时树里只有前 N 个 → 全量重载后重试
            self._load_children_of(cur_path, show_all=True, force=True)
            found = self._find_child_by_path(node, node_path)
        if found is None:
            # 仍找不到（理论上不再发生）：直接打开内容，避免“点了没反应”
            self._show_file(vfile.path)
            self.status_label.setText(
                f"{vfile.path}（树中未找到对应节点，已在右侧直接打开）")
            return
        self.tree.setCurrentItem(found)
        self.tree.scrollToItem(found)
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
        """打开 assets.bin：文件与解析规则在同一个对话框里选。

        裸 assets.bin 没有客户端信息可探测，规则必须此时指定（浏览器界面里不再放规则选项）。
        """
        start = "" if self._source_is_dir else (self._last_source or "")
        dlg = _OpenAssetsDialog(self, path=start, rule=self._rule)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path = dlg.selected_path()
        if not path:
            return
        self._rule = dlg.selected_rule()
        self._client_version = None
        self._source_is_dir = False
        self._set_source_label(path)
        self.load_source(path)

    def _on_open_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择游戏目录（含 bin 与 res_packages）")
        if path:
            self._bin_folder = None
            self._source_is_dir = True
            self._set_source_label(path)
            self.load_source(path)

    def _set_source_label(self, path: str) -> None:
        ver = version_text(getattr(self, "_client_version", None))
        extra = f"，客户端 {ver}" if ver else ""
        if self._wows_type == "auto":
            # 「自动」尚未判定完：还没有结论，不显示任何服务器/类型表
            rule_label = "自动（识别中…）"
        elif self._rule == RULE_AUTO:
            resolved = getattr(self, "_auto_rule", "")
            if self._wows_type == "Wargaming":
                tag = "Wargaming"
            elif self._wows_type == "Legacy":
                tag = "远古布局"
            else:
                tag = "Lesta"
            if self._auto_undetermined or not resolved:
                rule_label = f"自动（未判定，按 {tag} 解析）"
            else:
                rule_label = f"自动（识别为 {RULE_SHORT_LABELS.get(resolved, resolved)}）"
        else:
            rule_label = RULE_LABELS.get(self._rule, self._rule)
        hint = ""
        if self._rule == RULE_AUTO:
            reason = getattr(self, "_auto_reason", "")
            hint = f"（{reason}）" if reason else ""
        # 裸 assets.bin 同名文件遍地都是，标出完整路径才知道加载的是哪一份
        full = str(path)
        shown = full if not self._source_is_dir else Path(full).name
        self.source_label.set_source(f"来源: {shown}", f"  [{rule_label}{extra}]")
        tip = [self._source_tip, f"路径: {full}"]
        if hint:
            tip.append(f"判定依据: {hint.strip('（）')}")
        self.source_label.setToolTip("\n".join(tip))
        self.setWindowTitle(f"assets.bin 浏览器 — {shown}")

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
