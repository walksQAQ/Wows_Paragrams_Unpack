"""
UnpackerDialog —— 游戏资源解包器（GUI）。

``data_extractor``（纯 Python 解包器）的图形界面：浏览客户端的虚拟文件系统
（``bin/<版本>/idx`` + ``res_packages/*.pkg``），把选中的文件 / glob 匹配结果
解包到指定目录。功能等价于命令行::

    python -m data_extractor.cli ls      <游戏目录> content/
    python -m data_extractor.cli list    <游戏目录> "gui/**/*.png"
    python -m data_extractor.cli extract <游戏目录> "content/**/*.xml" --output ./out

与工具栏「📦 加载数据」的区别：那个是「提取 → 解析 → 入库」的一键流程（只取
GameParams 等固定目标），本工具面向任意文件的手动挑选与导出，替代
``tools/wowsunpack.exe`` 的图形化用法。

低内存：逐文件**流式**解压写盘（``extract_single``），不整体驻留内存；取消可即时生效
（多进程并行模式例外：``extract()`` 一次性提交，无逐文件进度与取消）。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSplitter,
    QTextBrowser, QVBoxLayout, QWidget,
)

from app.application import app as app_ctx
from app.signals import bus
from utils.theme import theme
from utils.path_utils import get_app_dir
from utils.threading_utils import run_async


def _fmt_size(n: int) -> str:
    """字节 → 人类可读。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


class UnpackerDialog(QDialog):
    """资源解包器：浏览 VFS → 加入队列 / glob 批量 → 解包到目录。"""

    #: 后台线程 → 主线程：进度(0..100) + 状态文本
    progress_sig = Signal(int, str)
    #: 后台线程 → 主线程：追加一行日志
    log_sig = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("资源解包器")
        self.resize(1080, 700)
        self.setMinimumSize(820, 520)

        self._ex = None            # GameExtractor（浏览用，主线程持有）
        self._cwd = ""             # 当前虚拟目录
        self._queue: list[str] = []      # 待解包 vfs 路径
        self._queued: set[str] = set()
        self._task = None          # 解包任务句柄
        self._loading = False      # 解包进行中
        self._gen = 0              # 代数：新任务取代旧任务

        self._build_ui()
        theme.bind(self, """
            QDialog { background: @panel_bg@; }
            QLabel { color: @text@; font-size: 11px; background: transparent; }
        """)
        self.progress_sig.connect(self._on_progress)
        self.log_sig.connect(self._append_log)
        self._bootstrap()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        _edit_qss = """
            QLineEdit { padding: 4px 6px; border: 1px solid @border@; border-radius: 3px;
                        background: @input_bg@; color: @text@; font-size: 11px; }
            QLineEdit:focus { border-color: #0078d4; }
        """
        _btn_qss = """
            QPushButton { background: @panel_alt@; border: 1px solid @border@; border-radius: 3px;
                          padding: 4px 10px; font-size: 11px; color: @text@; }
            QPushButton:hover { border-color: #0078d4; }
            QPushButton:disabled { color: @text_hint@; }
        """
        _combo_qss = ("QComboBox { padding: 3px 6px; border: 1px solid @border@; border-radius: 3px;"
                      " background: @input_bg@; color: @text@; font-size: 11px; }")
        _list_qss = """
            QListWidget { background: @panel_bg@; border: 1px solid @border@;
                          border-radius: 4px; color: @text@; font-size: 12px; }
            QListWidget::item { padding: 2px 6px; }
            QListWidget::item:selected { background: @selected_bg@; color: @selected_fg@; }
            QListWidget::item:hover { background: @hover_bg@; color: @text@; }
        """

        # ── 源：游戏目录 + 版本 ──
        row0 = QHBoxLayout()
        row0.setSpacing(6)
        row0.addWidget(QLabel("游戏目录"))
        self.ed_game = QLineEdit()
        self.ed_game.setPlaceholderText("客户端根目录（含 bin/ 与 res_packages/）")
        theme.bind(self.ed_game, _edit_qss)
        row0.addWidget(self.ed_game, 1)
        self.btn_pick_game = QPushButton("浏览…")
        theme.bind(self.btn_pick_game, _btn_qss)
        row0.addWidget(self.btn_pick_game)
        row0.addWidget(QLabel("版本"))
        self.cb_bin = QComboBox()
        self.cb_bin.setMinimumWidth(110)
        theme.bind(self.cb_bin, _combo_qss)
        row0.addWidget(self.cb_bin)
        self.btn_open = QPushButton("载入")
        theme.bind(self.btn_open, _btn_qss)
        row0.addWidget(self.btn_open)
        root.addLayout(row0)

        self.lbl_status = QLabel("未载入。选择游戏目录后点「载入」。")
        theme.bind(self.lbl_status, "color: @text_muted@; font-size: 11px; background: transparent;")
        root.addWidget(self.lbl_status)

        # ── 过滤：路径 + glob ──
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.btn_up = QPushButton("↑ 上级")
        theme.bind(self.btn_up, _btn_qss)
        row1.addWidget(self.btn_up)
        self.btn_root = QPushButton("⌂ 根")
        theme.bind(self.btn_root, _btn_qss)
        row1.addWidget(self.btn_root)
        self.ed_path = QLineEdit()
        self.ed_path.setPlaceholderText("虚拟路径（回车进入），如 content/gameplay/")
        theme.bind(self.ed_path, _edit_qss)
        row1.addWidget(self.ed_path, 1)
        self.ed_glob = QLineEdit()
        self.ed_glob.setPlaceholderText('glob 筛选/批量添加，如 gui/**/*.png')
        theme.bind(self.ed_glob, _edit_qss)
        row1.addWidget(self.ed_glob, 1)
        self.btn_glob = QPushButton("按 glob 列出")
        theme.bind(self.btn_glob, _btn_qss)
        row1.addWidget(self.btn_glob)
        self.btn_add_glob = QPushButton("glob 结果加入队列")
        theme.bind(self.btn_add_glob, _btn_qss)
        row1.addWidget(self.btn_add_glob)
        root.addLayout(row1)

        # ── 浏览器 | 队列 ──
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        lbl_l = QLabel("文件浏览（双击目录进入 / 双击文件加入）")
        theme.bind(lbl_l, "color: @text_muted@; font-size: 11px; background: transparent;")
        ll.addWidget(lbl_l)
        self.list_browse = QListWidget()
        self.list_browse.setSelectionMode(QListWidget.ExtendedSelection)
        theme.bind(self.list_browse, _list_qss)
        ll.addWidget(self.list_browse, 1)
        rowb = QHBoxLayout()
        rowb.setSpacing(6)
        self.btn_add_sel = QPushButton("＋ 加入队列")
        theme.bind(self.btn_add_sel, _btn_qss)
        rowb.addWidget(self.btn_add_sel)
        self.btn_add_dir = QPushButton("＋ 整个目录（*.data 等子集）")
        self.btn_add_dir.setToolTip("把当前目录下匹配 glob 的全部文件加入队列；glob 为空则用 **/*")
        theme.bind(self.btn_add_dir, _btn_qss)
        rowb.addWidget(self.btn_add_dir)
        rowb.addStretch()
        ll.addLayout(rowb)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.lbl_queue = QLabel("待解包队列（0）")
        theme.bind(self.lbl_queue, "color: @text_muted@; font-size: 11px; background: transparent;")
        rl.addWidget(self.lbl_queue)
        self.list_queue = QListWidget()
        self.list_queue.setSelectionMode(QListWidget.ExtendedSelection)
        theme.bind(self.list_queue, _list_qss)
        rl.addWidget(self.list_queue, 1)
        rowq = QHBoxLayout()
        rowq.setSpacing(6)
        self.btn_del_sel = QPushButton("－ 移除选中")
        theme.bind(self.btn_del_sel, _btn_qss)
        rowq.addWidget(self.btn_del_sel)
        self.btn_clear = QPushButton("清空队列")
        theme.bind(self.btn_clear, _btn_qss)
        rowq.addWidget(self.btn_clear)
        rowq.addStretch()
        rl.addLayout(rowq)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        # ── 输出与选项 ──
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("输出目录"))
        self.ed_out = QLineEdit(str(get_app_dir() / "unpacked"))
        theme.bind(self.ed_out, _edit_qss)
        row2.addWidget(self.ed_out, 1)
        self.btn_pick_out = QPushButton("浏览…")
        theme.bind(self.btn_pick_out, _btn_qss)
        row2.addWidget(self.btn_pick_out)
        root.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(10)
        self.cb_strip = QCheckBox("去除公共前缀目录")
        self.cb_flatten = QCheckBox("压平到输出目录（重名会覆盖）")
        self.cb_par = QCheckBox("多进程并行（无逐文件进度）")
        for cb in (self.cb_strip, self.cb_flatten, self.cb_par):
            theme.bind(cb, "QCheckBox { color: @text@; font-size: 11px; background: transparent; }")
            row3.addWidget(cb)
        row3.addStretch()
        self.btn_start = QPushButton("开始解包")
        theme.bind(self.btn_start, """
            QPushButton { background: #0078d4; color: #ffffff; border: 1px solid #0078d4;
                          border-radius: 3px; padding: 5px 14px; font-size: 12px; font-weight: bold; }
            QPushButton:hover { background: #1a88e0; }
            QPushButton:disabled { background: @panel_alt@; color: @text_hint@; border-color: @border@; }
        """)
        row3.addWidget(self.btn_start)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        theme.bind(self.btn_cancel, _btn_qss)
        row3.addWidget(self.btn_cancel)
        root.addLayout(row3)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(16)
        theme.bind(self.progress, """
            QProgressBar { border: 1px solid #0078d4; border-radius: 4px; background: @input_bg@;
                           color: @text@; font-size: 11px; text-align: center; }
            QProgressBar::chunk { background: #0078d4; }
        """)
        root.addWidget(self.progress)

        self.log = QTextBrowser()
        self.log.setFixedHeight(120)
        theme.bind(self.log, """
            QTextBrowser { background: @panel_alt@; border: 1px solid @border@;
                           border-radius: 4px; color: @text_muted@; font-size: 11px; }
        """)
        root.addWidget(self.log)

        # ── 信号 ──
        self.btn_pick_game.clicked.connect(self._pick_game_dir)
        self.btn_open.clicked.connect(self._open_extractor)
        self.btn_up.clicked.connect(lambda: self._goto(self._parent_of(self._cwd)))
        self.btn_root.clicked.connect(lambda: self._goto(""))
        self.ed_path.returnPressed.connect(lambda: self._goto(self.ed_path.text().strip()))
        self.btn_glob.clicked.connect(self._list_by_glob)
        self.btn_add_glob.clicked.connect(self._add_glob)
        self.btn_add_sel.clicked.connect(self._add_selected)
        self.btn_add_dir.clicked.connect(self._add_current_dir)
        self.btn_del_sel.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear_queue)
        self.btn_pick_out.clicked.connect(self._pick_out_dir)
        self.list_browse.itemDoubleClicked.connect(self._on_browse_activated)
        self.cb_flatten.toggled.connect(self._on_flatten_toggled)
        self.cb_par.toggled.connect(self._on_parallel_toggled)
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)

    # ── 初始化 ────────────────────────────────────────────

    def _bootstrap(self):
        """用应用配置里的游戏目录/版本预填。"""
        try:
            gp = app_ctx.ctx.game_path or ""
        except Exception:  # noqa: BLE001
            gp = ""
        self.ed_game.setText(str(gp))
        self._refresh_versions()
        if gp:
            self._open_extractor()

    def _refresh_versions(self):
        """填充版本下拉：bin 下含 idx/ 的数字目录（新→旧）。"""
        self.cb_bin.clear()
        game = Path(self.ed_game.text().strip() or ".")
        bin_dir = game / "bin"
        folders: list[str] = []
        try:
            if bin_dir.is_dir():
                folders = [d.name for d in bin_dir.iterdir()
                           if d.is_dir() and d.name.isdigit() and (d / "idx").is_dir()]
        except OSError:
            folders = []
        folders.sort(key=lambda s: int(s), reverse=True)
        if folders:
            self.cb_bin.addItem("（最新）", "")
            for f in folders:
                self.cb_bin.addItem(f, f)
        else:
            self.cb_bin.addItem("（自动）", "")

    # ── 载入文件树 ────────────────────────────────────────

    def _pick_game_dir(self):
        cur = self.ed_game.text().strip()
        path = QFileDialog.getExistingDirectory(self, "选择客户端根目录", cur or str(get_app_dir()))
        if not path:
            return
        self.ed_game.setText(path)
        self._refresh_versions()
        self._open_extractor()

    def _open_extractor(self):
        if self._loading:
            return
        game = self.ed_game.text().strip()
        if not game or not Path(game).is_dir():
            self.lbl_status.setText("游戏目录不存在，请重新选择。")
            return
        bin_folder = self.cb_bin.currentData() or ""
        self.btn_open.setEnabled(False)
        self.lbl_status.setText("正在读取 idx（首次约需数秒）...")
        self._ex = None
        self.list_browse.clear()

        def _load():
            from data_extractor import GameExtractor
            return GameExtractor(game, bin_folder=bin_folder or None)

        run_async(_load, on_finished=self._on_extractor_ready,
                  on_error=self._on_extractor_error)

    def _on_extractor_ready(self, ex):
        self.btn_open.setEnabled(True)
        self._ex = ex
        note = f"　⚠️ {ex.bin_folder_note}" if getattr(ex, "bin_folder_note", "") else ""
        files = 0
        volumes = set()
        for e in ex.file_tree.values():
            if e.is_directory:
                continue
            files += 1
            if e.volume is not None:
                volumes.add(e.volume.filename)
        self.lbl_status.setText(
            f"已载入：版本 {ex.bin_folder}，文件 {files} 个，卷 {len(volumes)} 个{note}")
        self._append_log(f"已载入 {ex.game_dir}（版本 {ex.bin_folder}）")
        self._goto("")

    def _on_extractor_error(self, err):
        self.btn_open.setEnabled(True)
        self.lbl_status.setText(f"载入失败：{err}")
        self._append_log(f"❌ 载入失败：{err}")

    # ── 浏览 ─────────────────────────────────────────────

    @staticmethod
    def _parent_of(path: str) -> str:
        path = path.strip("/")
        if not path or "/" not in path:
            return ""
        return path.rsplit("/", 1)[0]

    def _goto(self, path: str):
        self._cwd = path.strip("/")
        self.ed_path.setText(self._cwd)
        self._refresh_browser()

    def _refresh_browser(self):
        self.list_browse.clear()
        if self._ex is None:
            return
        entries = self._ex.list_directory(self._cwd)
        # 目录在前，同级按名称排序
        entries.sort(key=lambda e: (not e.is_directory, e.path.lower()))
        for e in entries:
            if e.is_directory:
                item = QListWidgetItem(f"📁  {Path(e.path).name}/")
            else:
                size = _fmt_size(e.file_info.unpacked_size) if e.file_info else ""
                item = QListWidgetItem(f"📄  {Path(e.path).name}    {size}")
            item.setData(Qt.UserRole, e)
            item.setToolTip(e.path)
            self.list_browse.addItem(item)
        self.lbl_status.setToolTip(f"当前目录：/{self._cwd}")

    def _on_browse_activated(self, item):
        e = item.data(Qt.UserRole)
        if e is None:
            return
        if e.is_directory:
            self._goto(e.path)
        else:
            self._enqueue([e.path])

    def _list_by_glob(self):
        """把 glob 匹配结果显示在浏览器里（便于挑选）。"""
        pattern = self.ed_glob.text().strip()
        if self._ex is None or not pattern:
            return
        matches = self._ex.list_files([pattern])
        self.list_browse.clear()
        files = [e for e in matches if not e.is_directory]
        for e in sorted(files, key=lambda x: x.path)[:5000]:
            size = _fmt_size(e.file_info.unpacked_size) if e.file_info else ""
            item = QListWidgetItem(f"📄  {e.path}    {size}")
            item.setData(Qt.UserRole, e)
            item.setToolTip(e.path)
            self.list_browse.addItem(item)
        shown = min(len(files), 5000)
        self.lbl_status.setText(
            f"glob「{pattern}」匹配 {len(files)} 个文件"
            + (f"（列表只显示前 {shown} 个）" if len(files) > shown else ""))

    def _add_glob(self):
        pattern = self.ed_glob.text().strip()
        if self._ex is None or not pattern:
            self.lbl_status.setText("请输入 glob 模式。")
            return
        matches = self._ex.list_files([pattern])
        self._enqueue([e.path for e in matches if not e.is_directory])

    def _add_selected(self):
        paths = []
        for item in self.list_browse.selectedItems():
            e = item.data(Qt.UserRole)
            if e is not None and not e.is_directory:
                paths.append(e.path)
        if not paths:
            self.lbl_status.setText("请先在左侧选中文件（目录请双击进入，或用「整个目录」按钮）。")
            return
        self._enqueue(paths)

    def _add_current_dir(self):
        """把当前目录下匹配 glob 的文件全部加入（glob 空 → 递归全部）。"""
        if self._ex is None:
            return
        sub = self.ed_glob.text().strip() or "**/*"
        base = self._cwd.rstrip("/")
        pattern = f"{base}/{sub}" if base else sub
        matches = self._ex.list_files([pattern])
        paths = [e.path for e in matches if not e.is_directory]
        if not paths:
            self.lbl_status.setText(f"「{pattern}」无匹配文件。")
            return
        self._enqueue(paths)

    # ── 队列 ─────────────────────────────────────────────

    def _enqueue(self, paths: list[str]):
        added = 0
        for p in paths:
            if p in self._queued:
                continue
            self._queued.add(p)
            self._queue.append(p)
            item = QListWidgetItem(p)
            item.setData(Qt.UserRole, p)
            self.list_queue.addItem(item)
            added += 1
        self._update_queue_label()
        self.lbl_status.setText(f"已加入队列 {added} 个文件（队列共 {len(self._queue)}）。")

    def _remove_selected(self):
        for item in self.list_queue.selectedItems():
            p = item.data(Qt.UserRole)
            self._queued.discard(p)
            if p in self._queue:
                self._queue.remove(p)
            self.list_queue.takeItem(self.list_queue.row(item))
        self._update_queue_label()

    def _clear_queue(self):
        self._queue.clear()
        self._queued.clear()
        self.list_queue.clear()
        self._update_queue_label()

    def _update_queue_label(self):
        total = 0
        if self._ex is not None:
            for p in self._queue:
                e = self._ex.file_tree.get(p)
                if e is not None and e.file_info is not None:
                    total += e.file_info.unpacked_size
        self.lbl_queue.setText(f"待解包队列（{len(self._queue)} 个，解包后约 {_fmt_size(total)}）")

    # ── 输出选项 ─────────────────────────────────────────

    def _pick_out_dir(self):
        cur = self.ed_out.text().strip()
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", cur or str(get_app_dir()))
        if path:
            self.ed_out.setText(path)

    def _on_flatten_toggled(self, on: bool):
        if on and self.cb_par.isChecked():
            self.cb_par.setChecked(False)   # 压平与并行互斥（并行走 extract()，不支持压平）

    def _on_parallel_toggled(self, on: bool):
        if on and self.cb_flatten.isChecked():
            self.cb_flatten.setChecked(False)

    # ── 解包 ─────────────────────────────────────────────

    def _start(self):
        if self._loading:
            return
        if not self._queue:
            self.lbl_status.setText("队列为空：先加入要解包的文件。")
            return
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            self.lbl_status.setText("请先选择输出目录。")
            return
        game = self.ed_game.text().strip()
        bin_folder = self.cb_bin.currentData() or ""
        paths = list(self._queue)
        strip = self.cb_strip.isChecked()
        flatten = self.cb_flatten.isChecked()
        parallel = self.cb_par.isChecked()

        self._loading = True
        self._gen += 1
        gen = self._gen
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self._append_log(
            f"开始解包 {len(paths)} 个文件 → {out_dir}"
            + ("（多进程并行）" if parallel else ""))
        bus.log_message.emit(f"🗜 开始解包 {len(paths)} 个文件 → {out_dir}")

        def _work(ce):
            from data_extractor import GameExtractor
            ex = GameExtractor(game, bin_folder=bin_folder or None)
            try:
                return self._run_extract(ex, paths, Path(out_dir), strip, flatten,
                                         parallel, ce, gen)
            finally:
                ex.close()

        self._task = run_async(_work, on_finished=lambda r: self._on_done(r, gen),
                               on_error=lambda e: self._on_error(e, gen),
                               cancel_event=threading.Event())

    def _run_extract(self, ex, paths, out_dir, strip, flatten, parallel, ce, gen):
        """worker 线程：执行解包（返回统计 dict；取消时带 cancelled=True 正常返回）。"""
        prefix = ""
        if strip:
            from data_extractor import common_dir_prefix
            prefix = common_dir_prefix(paths)

        if parallel:
            self.progress_sig.emit(5, "并行解包中（无逐文件进度）...")
            t0 = time.perf_counter()
            out = ex.extract(paths, out_dir, strip_prefix=strip, workers=0)
            if len(out) < len(paths):
                self.log_sig.emit(
                    f"⚠️ 并行模式已提取 {len(out)}/{len(paths)}"
                    f"（个别路径含 glob 特殊字符，或解压失败）")
            return {"ok": len(out), "fail": len(paths) - len(out), "paths": out,
                    "elapsed": time.perf_counter() - t0, "cancelled": False}

        n = len(paths)
        ok, fail, written = 0, 0, []
        t0 = time.perf_counter()
        for i, vfs in enumerate(paths, 1):
            if ce.is_set():
                return {"ok": ok, "fail": fail, "paths": written,
                        "elapsed": time.perf_counter() - t0, "cancelled": True}
            rel = vfs
            if prefix and vfs.startswith(prefix):
                rel = vfs[len(prefix):]
            if flatten:
                rel = os.path.basename(vfs)
            try:
                p = ex.extract_single(vfs, out_dir / rel)
                written.append(p)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                fail += 1
                self.log_sig.emit(f"⚠️ 失败 {vfs}: {exc}")
            if i % 5 == 0 or i == n:
                self.progress_sig.emit(int(i * 100 / n), f"{i}/{n}  {vfs}")
        return {"ok": ok, "fail": fail, "paths": written,
                "elapsed": time.perf_counter() - t0, "cancelled": False}

    def _finish_ui(self):
        self._loading = False
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self._task = None

    def _on_done(self, result, gen):
        if gen != self._gen:
            return
        self._finish_ui()
        if not isinstance(result, dict):
            return
        total = sum(p.stat().st_size for p in result.get("paths", []) if Path(p).exists())
        head = "已取消：" if result.get("cancelled") else "解包完成："
        msg = (f"{head}成功 {result['ok']}，失败 {result['fail']}，"
               f"共 {_fmt_size(total)}，耗时 {result['elapsed']:.1f}s")
        self.lbl_status.setText(msg)
        self._append_log(("⏹ " if result.get("cancelled") else "✅ ") + msg)
        bus.log_message.emit(
            ("⏹ 解包取消" if result.get("cancelled") else "✅ 解包完成")
            + f"：成功 {result['ok']} / 失败 {result['fail']}")

    def _on_error(self, err, gen):
        if gen != self._gen:
            return
        self._finish_ui()
        self.lbl_status.setText(f"解包中止：{err}")
        self._append_log(f"❌ 解包中止：{err}")
        bus.log_message.emit(f"❌ 解包中止：{err}")

    def _on_progress(self, pct: int, msg: str):
        self.progress.setValue(max(0, min(100, int(pct))))
        self.lbl_status.setText(msg)

    def _cancel(self):
        if self._task is not None:
            self._task.cancel()
            self.lbl_status.setText("已请求取消，等待当前文件写完...")
            self._append_log("⏹ 已请求取消")

    def _append_log(self, text: str):
        if not text:
            return
        self.log.append(text)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── 生命周期 ─────────────────────────────────────────

    def closeEvent(self, event):
        if self._task is not None:
            self._task.cancel()
            self._task.kill(timeout=1.0)
            self._task = None
        self._loading = False
        if self._ex is not None:
            try:
                self._ex.close()
            except Exception:  # noqa: BLE001
                pass
            self._ex = None
        super().closeEvent(event)
