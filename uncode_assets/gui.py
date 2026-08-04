"""AssetsBinViewer —— assets.bin 可视化浏览/解码界面（PySide6）。

功能：
  - 打开已解压的 assets.bin 文件或直接选择游戏目录（自动用 data_extractor 提取）
  - 后台线程加载解析（避免卡 UI），左侧懒加载虚拟文件树
  - 点击文件在右侧显示解码 JSON（深色等宽主题）
  - 顶部搜索：按路径关键字定位文件
  - 状态栏显示数据库概览

独立运行：  python -m uncode_assets.gui [assets.bin 或 游戏目录]
也可由主程序通过 AssetsBinViewer(source) 打开。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QPushButton, QLabel, QFileDialog, QLineEdit, QStatusBar, QToolBar,
    QHeaderView, QAbstractItemView,
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


class _LoadWorker(QThread):
    """后台加载线程：解析 assets.bin 并构建 VFS。"""

    loaded = Signal(object)  # AssetsBinService
    failed = Signal(str)

    def __init__(self, game_dir: Optional[str] = None,
                 assets_path: Optional[str] = None,
                 bin_folder: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._game_dir = game_dir
        self._assets_path = assets_path
        self._bin_folder = bin_folder

    def run(self) -> None:
        try:
            if self._game_dir:
                svc = AssetsBinService(game_dir=self._game_dir, bin_folder=self._bin_folder)
            else:
                svc = AssetsBinService(assets_path=self._assets_path)
            self.loaded.emit(svc)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class AssetsBinViewer(QMainWindow):
    """assets.bin 可视化浏览器。"""

    #: 每个目录最多直接显示的文件节点数，超出显示占位项（避免大目录卡死 UI）
    MAX_FILES_PER_DIR = 1000

    def __init__(self, source: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._svc: Optional[AssetsBinService] = None
        self._worker: Optional[_LoadWorker] = None
        self._bin_folder: Optional[str] = None
        self.setWindowTitle("assets.bin 浏览器")
        self.resize(1280, 820)
        self.setStyleSheet(_STYLE)
        self._build_ui()
        if source:
            self.load_source(str(source))
            return
        # 无显式来源时，继承主应用已配置的游戏目录设置
        inherited = self._inherited_game_dir()
        if inherited:
            game_dir, bin_folder = inherited
            self._bin_folder = bin_folder
            self._set_source_label(game_dir)
            self.load_source(game_dir)

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

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索路径关键字 (回车)...")
        self.search_edit.setFixedWidth(260)
        self.search_edit.returnPressed.connect(self._on_search)
        toolbar.addWidget(self.search_edit)

        toolbar.addWidget(QLabel("  "))

        self.info_label = QLabel("未加载")
        self.info_label.setObjectName("info")
        toolbar.addWidget(self.info_label)

        self.source_label = QLabel("")
        self.source_label.setObjectName("source")
        self.source_label.setToolTip("数据来源（继承主应用设置）")
        toolbar.addWidget(self.source_label)

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
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemClicked.connect(self._on_item_clicked)
        splitter.addWidget(self.tree)

        self.json_view = QTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        splitter.addWidget(self.json_view)

        splitter.setSizes([420, 860])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # 状态栏
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("就绪")
        status.addPermanentWidget(self.status_label)

    # ── 窗口定位 ────────────────────────────────────────

    def center_on_screen(self, relative_to: Optional[QWidget] = None) -> None:
        """把窗口居中到指定窗口（默认主屏）。作为独立顶层窗口时避免与主窗口重叠被遮挡。"""
        from PySide6.QtGui import QGuiApplication
        if relative_to is not None and relative_to.isVisible():
            geo = relative_to.frameGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(max(x, 0), max(y, 0))
            return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - self.width()) // 2,
                      geo.y() + (geo.height() - self.height()) // 2)

    # ── 加载 ────────────────────────────────────────────

    def load_source(self, source: str) -> None:
        """加载 assets.bin 文件路径或游戏目录（后台线程）。"""
        p = Path(source)
        if self._worker and self._worker.isRunning():
            return
        self.tree.clear()
        self.json_view.clear()
        self.status_label.setText("正在加载/解析 assets.bin...（Kraken 解压可能较慢）")
        self.info_label.setText("加载中...")
        if p.is_dir():
            self._worker = _LoadWorker(game_dir=str(p), bin_folder=self._bin_folder, parent=self)
        else:
            self._worker = _LoadWorker(assets_path=str(p), parent=self)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._worker.start()

    def _on_loaded(self, svc: AssetsBinService) -> None:
        self._svc = svc
        info = svc.info()
        self.info_label.setText(
            f"blob: {info['databases_count']}  文件: {info['file_count']}  "
            f"目录: {info['dir_count']}  路径: {info['paths_count']}"
        )
        self._build_root()
        self.status_label.setText("加载完成")

    def _on_load_failed(self, message: str) -> None:
        self.status_label.setText("加载失败")
        self.info_label.setText("加载失败")
        self.json_view.setPlainText(f"加载失败:\n{message}")

    # ── 文件树 ──────────────────────────────────────────

    def _build_root(self) -> None:
        self.tree.clear()
        self._load_children_of("/")

    def _node_path(self, item: QTreeWidgetItem) -> str:
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _load_children_of(self, dir_path: str) -> None:
        """把 dir_path 的直接子项挂到对应父节点（懒加载）。"""
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
        # 已加载过则跳过（避免重复）
        if parent_item.childCount() > 0 and dir_path != "/":
            return
        for name in subdirs:
            child_path = ("/" + name) if dir_path == "/" else dir_path + "/" + name
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.ItemDataRole.UserRole, child_path)
            item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            parent_item.addChild(item)
        # 文件节点：限制数量，避免一次性加入海量节点导致 UI 卡顿
        shown = 0
        for f in files:
            if shown >= self.MAX_FILES_PER_DIR:
                remaining = len(files) - shown
                placeholder = QTreeWidgetItem(
                    [f"… 还有 {remaining} 个文件（请用顶部搜索定位）"])
                placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
                placeholder.setFlags(
                    placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                parent_item.addChild(placeholder)
                break
            item = QTreeWidgetItem([f.filename])
            item.setData(0, Qt.ItemDataRole.UserRole, f.path)
            tname = f.prototype_type.name if f.prototype_type else "?"
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
        try:
            decoded = self._svc.vfs.decode_file(path)
            text = json.dumps(decoded, ensure_ascii=False, indent=2, allow_nan=False)
        except (AssetsBinError, KeyError, ValueError, Exception) as e:  # noqa: BLE001
            text = f"解码失败: {e}"
        self.json_view.setPlainText(text)
        self.status_label.setText(f"{path}")

    # ── 搜索 ────────────────────────────────────────────

    def _on_search(self) -> None:
        keyword = self.search_edit.text().strip().lower()
        if not keyword or self._svc is None:
            return
        # 优先匹配文件名（快），找不到再匹配完整路径（较慢）
        first: Optional[VirtualFile] = None
        count = 0
        for f in self._svc.vfs.all_files():
            if keyword in f.filename.lower():
                count += 1
                if first is None:
                    first = f
                if count >= 500:
                    break
        if first is None:
            for f in self._svc.vfs.all_files():
                if keyword in f.path.lower():
                    count += 1
                    if first is None:
                        first = f
                    if count >= 500:
                        break
        msg = f"匹配 {count} 个文件" + ("（已达上限 500）" if count >= 500 else "")
        self.status_label.setText(msg if count else "无匹配")
        if first:
            self._reveal_file(first)

    def _reveal_file(self, vfile: VirtualFile) -> None:
        """展开祖先目录并选中文件节点。"""
        parts = [p for p in vfile.path.split('/') if p]
        node: QTreeWidgetItem = self.tree.invisibleRootItem()
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            # 找到或加载子项
            found = None
            for j in range(node.childCount()):
                child = node.child(j)
                if child.text(0) == part:
                    found = child
                    break
            if found is None:
                # 懒加载当前节点子项后重试
                if node is self.tree.invisibleRootItem():
                    self._load_children_of("/")
                else:
                    self._load_children_of(self._node_path(node))
                for j in range(node.childCount()):
                    child = node.child(j)
                    if child.text(0) == part:
                        found = child
                        break
            if found is None:
                return
            node = found
            if not is_last:
                node.setExpanded(True)
        self.tree.setCurrentItem(node)
        self.tree.scrollToItem(node)
        self._show_file(vfile.path)

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

    def _inherited_game_dir(self) -> Optional[tuple]:
        """继承主应用（app.ctx）已配置的游戏目录，返回 (game_dir, bin_folder) 或 None。"""
        try:
            from app.application import app
            ctx = getattr(app, "ctx", None)
            if ctx is None:
                return None
            game_path = getattr(ctx, "game_path", "")
            if game_path and game_path != "未设置" and Path(game_path).is_dir():
                return game_path, getattr(ctx, "bin_folder", "") or None
        except Exception:  # noqa: BLE001
            pass
        return None

    def _save_inherited_dir(self, path: str) -> None:
        """把浏览器中选择的游戏目录写回主应用配置，保持两侧一致。"""
        try:
            from app.application import app
            app.config.game_path = path
        except Exception:  # noqa: BLE001
            pass

    def _set_source_label(self, path: str) -> None:
        self.source_label.setText(f"来源: {Path(path).name}")


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
