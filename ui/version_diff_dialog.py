"""
版本数据比对对话框 —— 跨版本实体级 + 信息面板式差异展示。

从"工具 → 版本数据比对..."打开（独立顶层窗口，懒创建单实例）。
- 左栏：按类型的差异概览统计表 + 差异实体列表（可筛选/搜索）
- 右栏：类似主界面信息面板，展示选中实体的完整字段树（所有字段可见），
      有变动的字段用三色高亮标记并对照展示 源版本值 → 目标版本值
- 后台线程计算（run_async + 本地 Signal 回主线程），避免卡界面
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QObject, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QMessageBox, QWidget, QAbstractItemView,
)

from utils.threading_utils import run_async
from services.diff_service import _fmt_value, KIND_LABELS


# ── 三色高亮（与实体列表一致）──────────────────────────────
_COLOR_ADDED = QColor("#1e7d32")      # 绿
_COLOR_REMOVED = QColor("#c62828")    # 红
_COLOR_MODIFIED = QColor("#b26a00")   # 黄/琥珀
_COLOR_UNCHANGED = QColor("#6b7280")  # 灰

_KIND_COLORS = {
    "added": _COLOR_ADDED,
    "removed": _COLOR_REMOVED,
    "modified": _COLOR_MODIFIED,
    "unchanged": _COLOR_UNCHANGED,
}

#: 实体列表最多展示行数（unchanged 可能上万条，防止一次性渲染卡死）
_MAX_ROWS = 2000


class _DiffSignals(QObject):
    """后台线程结果 → 主线程槽（Qt 队列连接自动保证线程安全）。"""

    diff_done = Signal(str, str, object)     # (base_vc, target_vc, overview)
    fields_done = Signal(str, object, str)   # (entity_id, list[FieldDiff] | None, error)
    failed = Signal(str)


class VersionDiffDialog(QDialog):
    """版本数据比对对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._svc = None
        self._sig = _DiffSignals()
        self._last_result = None            # DiffResult
        self._last_base_vc = ""
        self._last_target_vc = ""
        self._field_counts: dict[str, int] = {}
        self._busy = False

        self.setWindowTitle("版本数据比对")
        self.setMinimumSize(900, 600)
        self.resize(1220, 780)
        self.setStyleSheet("""
            QDialog { background:#ffffff; color:#222; }
            QLabel { color:#222; font-size:12px; }
            QPushButton { background:#f2f2f2; border:1px solid #b9b9b9; border-radius:3px;
                          padding:4px 14px; color:#222; font-size:12px; }
            QPushButton:hover { background:#e4e4e4; }
            QPushButton:disabled { color:#999; background:#f7f7f7; }
            QComboBox, QLineEdit { background:#fff; border:1px solid #bbb; border-radius:3px;
                                   padding:3px 6px; color:#222; font-size:12px; }
            QTableWidget { background:#fff; border:1px solid #d0d0d0; gridline-color:#ececec;
                           color:#222; font-size:12px; }
            QHeaderView::section { background:#f4f4f4; color:#333; font-size:12px;
                                   border:1px solid #d8d8d8; padding:4px; }
            QTreeWidget { background:#fff; border:1px solid #d0d0d0; color:#222; font-size:12px; }
            QSplitter::handle { background:#e6e6e6; }
            #noteBanner { background:#fff7e0; color:#7a5c00; border:1px solid #e8cf8a;
                          border-radius:3px; padding:4px 8px; }
            #fieldHeader { font-size:13px; font-weight:bold; color:#c60; padding:4px 2px; }
            #footer { color:#666; font-size:11px; }
            #sectionTitle { font-size:12px; font-weight:bold; color:#444; }
        """)
        self._build_ui()
        self._load_versions()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # ── 版本选择栏 ──────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("源版本"))
        self.base_combo = QComboBox()
        self.base_combo.setMinimumWidth(220)
        top.addWidget(self.base_combo)
        top.addWidget(QLabel("  目标版本"))
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(220)
        top.addWidget(self.target_combo)
        self.btn_compare = QPushButton("开始比对")
        self.btn_compare.clicked.connect(self._on_compare)
        top.addWidget(self.btn_compare)
        self.btn_swap = QPushButton("⇄ 交换")
        self.btn_swap.setToolTip("交换源/目标版本并重新比对")
        self.btn_swap.clicked.connect(self._on_swap)
        top.addWidget(self.btn_swap)
        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.setToolTip("把当前比对结果（概览+实体列表+字段对照）以文本复制到剪贴板")
        self.btn_copy.clicked.connect(self._on_copy_result)
        top.addWidget(self.btn_copy)
        top.addStretch(1)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color:#555;")
        top.addWidget(self.status_label)
        layout.addLayout(top)

        # ── 筛选栏 ──────────────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)
        filter_bar.addWidget(QLabel("类型筛选"))
        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(120)
        self.type_combo.currentIndexChanged.connect(self._apply_filter)
        filter_bar.addWidget(self.type_combo)
        filter_bar.addWidget(QLabel("  搜索"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("entity_id 关键字...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(260)
        self.search_edit.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self.search_edit)
        filter_bar.addStretch(1)
        self.footer_label = QLabel("")
        self.footer_label.setObjectName("footer")
        filter_bar.addWidget(self.footer_label)
        layout.addLayout(filter_bar)

        # 无快照提示横幅
        self.note_banner = QLabel("")
        self.note_banner.setObjectName("noteBanner")
        self.note_banner.hide()
        layout.addWidget(self.note_banner)

        # ── 中央：左概览/实体 + 右字段对照 ──────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        # 左栏（垂直：概览统计 + 实体列表）
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        overview_title = QLabel("差异概览（按类型）")
        overview_title.setObjectName("sectionTitle")
        left_layout.addWidget(overview_title)

        self.overview_table = QTableWidget(0, 5)
        self.overview_table.setHorizontalHeaderLabels(["类型", "新增", "删除", "修改", "未变"])
        self.overview_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.overview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.overview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.overview_table.verticalHeader().setVisible(False)
        self.overview_table.setMaximumHeight(160)
        self.overview_table.cellClicked.connect(self._on_overview_clicked)
        left_layout.addWidget(self.overview_table)

        entity_title = QLabel("差异实体列表")
        entity_title.setObjectName("sectionTitle")
        left_layout.addWidget(entity_title)

        self.entity_table = QTableWidget(0, 4)
        self.entity_table.setHorizontalHeaderLabels(["类型", "entity_id", "变更", "字段数"])
        self.entity_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.entity_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.entity_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.entity_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self.entity_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.entity_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.entity_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.entity_table.verticalHeader().setVisible(False)
        self.entity_table.cellClicked.connect(self._on_entity_clicked)
        left_layout.addWidget(self.entity_table, 1)

        splitter.addWidget(left_panel)

        # 右栏（字段级对照）
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.field_header = QLabel("在左侧选择实体以查看字段级差异")
        self.field_header.setObjectName("fieldHeader")
        self.field_header.setWordWrap(True)
        right_layout.addWidget(self.field_header)

        self.field_tree = QTreeWidget()
        self.field_tree.setHeaderLabels(["字段", "源版本", "目标版本"])
        self.field_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.field_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.field_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.field_tree.setColumnCount(3)
        right_layout.addWidget(self.field_tree, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([560, 660])
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)

        self.footer = QLabel("")
        self.footer.setObjectName("footer")
        layout.addWidget(self.footer)

        # 信号连接
        self._sig.diff_done.connect(self._on_diff_done)
        self._sig.fields_done.connect(self._on_fields_done)
        self._sig.failed.connect(self._on_failed)

    # ── 窗口定位（复刻 AssetsBinViewer.center_on_screen） ──

    def center_on_screen(self, relative_to=None) -> None:
        """把窗口居中到指定窗口（默认主屏）。"""
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

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        # 每次打开都刷新版本列表（导入新数据后下拉框同步更新）
        self._load_versions()

    # ── 版本加载 ──────────────────────────────────────────

    def _get_svc(self):
        if self._svc is None:
            from services.database_service import get_db
            from services.diff_service import DiffService
            self._svc = DiffService(get_db())
        return self._svc

    @staticmethod
    def _version_label(v: dict) -> str:
        code = v.get("version_code", "?")
        count = v.get("entity_count") or 0
        wt = v.get("wows_type") or ""
        extra = f" ({wt})" if wt else ""
        return f"{code}{extra}  [{count} 实体]"

    def _load_versions(self) -> None:
        try:
            versions = self._get_svc().list_versions()
        except Exception:
            versions = []
        self.base_combo.clear()
        self.target_combo.clear()
        for v in versions:
            label = self._version_label(v)
            code = v["version_code"]
            self.base_combo.addItem(label, code)
            self.target_combo.addItem(label, code)
        if len(versions) >= 2:
            # 默认：源=较旧，目标=最新
            self.target_combo.setCurrentIndex(0)
            self.base_combo.setCurrentIndex(1)
            self.btn_compare.setEnabled(True)
            self.btn_swap.setEnabled(True)
            self.status_label.setText("就绪：选择两个版本后点击[开始比对]")
        elif len(versions) == 1:
            self.btn_compare.setEnabled(False)
            self.btn_swap.setEnabled(False)
            self.status_label.setText("⚠️ 数据库只有 1 个版本，需先导入两次数据")
        else:
            self.btn_compare.setEnabled(False)
            self.btn_swap.setEnabled(False)
            self.status_label.setText("⚠️ 数据库暂无版本数据，请先导入数据")

    # ── 比对动作 ──────────────────────────────────────────

    def _on_compare(self) -> None:
        base = self.base_combo.currentData()
        target = self.target_combo.currentData()
        if not base or not target:
            QMessageBox.information(self, "版本数据比对", "请先选择两个版本")
            return
        if base == target:
            QMessageBox.information(self, "版本数据比对", "源版本与目标版本相同，无需比对")
            return
        self._set_busy(True)
        self.status_label.setText(f"正在比对 {base} → {target} ...")
        self.field_header.setText("正在比对...")
        self.field_tree.clear()

        import time

        def work():
            t0 = time.time()
            overview = self._get_svc().build_overview(base, target)
            overview["elapsed"] = time.time() - t0
            return overview

        run_async(work,
                  on_finished=lambda ov: self._sig.diff_done.emit(base, target, ov),
                  on_error=lambda err: self._sig.failed.emit(err))

    def _on_swap(self) -> None:
        bi = self.base_combo.currentIndex()
        ti = self.target_combo.currentIndex()
        if bi < 0 or ti < 0:
            return
        self.base_combo.setCurrentIndex(ti)
        self.target_combo.setCurrentIndex(bi)
        if self._last_result is not None:
            self._on_compare()

    # ── 复制比对结果（覆盖该界面显示的全部内容） ─────────────

    def _on_copy_result(self) -> None:
        """把当前比对界面显示的内容（概览 + 实体列表 + 字段对照）复制为文本。"""
        if self._last_result is None:
            QMessageBox.information(self, "版本数据比对", "请先点击[开始比对]后再复制")
            return
        from PySide6.QtWidgets import QApplication

        lines: list[str] = []
        lines.append(f"版本数据比对结果：{self._last_base_vc} → {self._last_target_vc}")
        lines.append("=" * 52)

        # 概览统计
        lines.append("【差异概览】")
        lines.append("类型\t新增\t删除\t修改\t未变")
        for etype, row in self._last_result.stats.items():
            lines.append(f"{etype}\t{row['added']}\t{row['removed']}\t{row['modified']}\t{row['unchanged']}")
        if not self._last_result.snapshot_available:
            lines.append("（提示：所选版本无快照，仅实体级比对）")
        lines.append("")

        # 实体列表（当前筛选后的显示内容）
        lines.append("【差异实体列表】")
        lines.append("类型\tentity_id\t变更\t字段数")
        for i in range(self.entity_table.rowCount()):
            cells = []
            for c in range(4):
                item = self.entity_table.item(i, c)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        lines.append("")

        # 信息面板对照（当前树内容）
        lines.append("【信息面板对照】")
        if self.field_tree.topLevelItemCount() == 0:
            lines.append("（未选择实体或无差异）")
        else:
            def _walk(item: QTreeWidgetItem, depth: int = 0) -> None:
                row = "\t".join(item.text(c) for c in range(3))
                lines.append("\t" * depth + row)
                for i in range(item.childCount()):
                    _walk(item.child(i), depth + 1)

            for i in range(self.field_tree.topLevelItemCount()):
                _walk(self.field_tree.topLevelItem(i))

        text = "\n".join(lines).rstrip()
        QApplication.clipboard().setText(text)
        self.footer.setText(f"✅ 已复制比对结果（{len(text)} 字符）到剪贴板")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_compare.setEnabled(not busy)
        self.btn_swap.setEnabled(not busy)
        self.btn_compare.setText("比对中..." if busy else "开始比对")

    # ── 概览 / 实体列表 ───────────────────────────────────

    @Slot(str, str, object)
    def _on_diff_done(self, base_vc: str, target_vc: str, overview: dict) -> None:
        self._set_busy(False)
        self._last_base_vc = base_vc
        self._last_target_vc = target_vc
        result = overview["result"]
        self._last_result = result
        self._field_counts = overview.get("field_counts", {})

        self._populate_overview(result)
        self._populate_entity_table()

        elapsed = overview.get("elapsed", 0)
        if result.snapshot_available:
            self.note_banner.hide()
            note = f"比对完成（耗时 {elapsed:.2f}s）"
        else:
            self.note_banner.show()
            self.note_banner.setText("⚠️ 所选版本无快照，仅能做实体级比对（新增/删除），无法显示字段级差异")
            note = f"比对完成（仅实体级，耗时 {elapsed:.2f}s）"
        self.status_label.setText(
            f"{note}｜新增 {len(result.added)} / 删除 {len(result.removed)}"
            f" / 修改 {len(result.modified)} / 未变 {len(result.unchanged)}")
        self.field_header.setText("在左侧选择实体，右侧展示其信息面板（变动字段已高亮）")

    @Slot(str)
    def _on_failed(self, err: str) -> None:
        self._set_busy(False)
        self.status_label.setText(f"❌ 比对失败: {err}")
        QMessageBox.warning(self, "版本数据比对", f"比对失败：{err}")

    def _populate_overview(self, result) -> None:
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItem("全部", None)
        for etype in result.stats:
            self.type_combo.addItem(etype, etype)
        self.type_combo.blockSignals(False)

        self.overview_table.setRowCount(0)
        self.overview_table.setRowCount(len(result.stats))
        for i, (etype, row) in enumerate(result.stats.items()):
            cells = [etype, row["added"], row["removed"], row["modified"], row["unchanged"]]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, etype)
                elif c == 1:
                    item.setForeground(_COLOR_ADDED)
                elif c == 2:
                    item.setForeground(_COLOR_REMOVED)
                elif c == 3:
                    item.setForeground(_COLOR_MODIFIED)
                self.overview_table.setItem(i, c, item)

    def _on_overview_clicked(self, row: int, _col: int) -> None:
        item = self.overview_table.item(row, 0)
        if item is None:
            return
        etype = item.data(Qt.ItemDataRole.UserRole)
        idx = self.type_combo.findData(etype)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

    def _apply_filter(self) -> None:
        result = self._last_result
        if result is None:
            return
        self._populate_entity_table()

    def _populate_entity_table(self) -> None:
        result = self._last_result
        if result is None:
            return
        etype = self.type_combo.currentData()
        kw = self.search_edit.text().strip().lower()

        def _match(k) -> bool:
            if etype and k[1] != etype:
                return False
            if kw and kw not in k[0].lower():
                return False
            return True

        rows: list[tuple[tuple, str, int]] = []
        for k in result.added:
            if _match(k):
                rows.append((k, "added", 0))
        for k in result.removed:
            if _match(k):
                rows.append((k, "removed", 0))
        for k in result.modified:
            if _match(k):
                rows.append((k, "modified", self._field_counts.get(k[0], 0)))
        for k in result.unchanged:
            if _match(k):
                rows.append((k, "unchanged", 0))

        total = len(rows)
        if total > _MAX_ROWS:
            # 只展示前 _MAX_ROWS 行（unchanged 可能上万条），并提示
            rows = rows[:_MAX_ROWS]

        self.entity_table.setSortingEnabled(False)
        self.entity_table.setRowCount(0)
        self.entity_table.setRowCount(len(rows))
        for i, (k, kind, fcount) in enumerate(rows):
            eid, etype2 = k
            cells = [etype2, eid, KIND_LABELS[kind],
                     str(fcount) if kind == "modified" else ""]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c == 1:
                    item.setData(Qt.ItemDataRole.UserRole, eid)
                if kind in _KIND_COLORS:
                    item.setForeground(_KIND_COLORS[kind])
                self.entity_table.setItem(i, c, item)
        self.entity_table.setSortingEnabled(True)
        self.entity_table.sortItems(1, Qt.SortOrder.AscendingOrder)

        overflow = f"，仅显示前 {_MAX_ROWS} 条" if total > _MAX_ROWS else ""
        self.footer_label.setText(f"共 {total} 条{overflow}")

    # ── 字段级对照 ────────────────────────────────────────

    def _on_entity_clicked(self, row: int, _col: int) -> None:
        item = self.entity_table.item(row, 1)
        if item is None:
            return
        entity_id = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self._load_field_diff(entity_id)

    def _load_field_diff(self, entity_id: str) -> None:
        if self._busy or not self._last_base_vc or not self._last_target_vc:
            return
        self.field_tree.clear()
        self.field_header.setText(f"正在加载 {entity_id} 信息面板...")

        def work():
            svc = self._get_svc()
            node = svc.build_entity_tree(self._last_base_vc, self._last_target_vc, entity_id)
            return entity_id, node

        run_async(work,
                  on_finished=lambda r: self._sig.fields_done.emit(r[0], r[1], ""),
                  on_error=lambda err: self._sig.fields_done.emit(entity_id, None, err))

    @Slot(str, object, str)
    def _on_fields_done(self, entity_id: str, node, error: str) -> None:
        if error:
            self.field_header.setText(f"{entity_id} — 信息加载失败: {error}")
            return
        if node is None:
            self.field_header.setText(f"{entity_id} — 无快照，无法展示信息面板")
            self.field_tree.clear()
            return
        cc = node.get("changed_count", 0)
        badge = f"〔差异字段 {cc} 处〕" if cc else "〔无差异〕"
        self.field_header.setText(
            f"{entity_id}　　{badge}　　{self._last_base_vc} → {self._last_target_vc}")
        self._build_field_tree(node)

    def _build_field_tree(self, node: dict) -> None:
        """把完整字段树渲染为信息面板样式（分组标题 + 键值行，差异三色高亮）。"""
        self.field_tree.clear()
        root = self.field_tree.invisibleRootItem()
        children = node.get("children") or []
        if children:
            # 顶层直接使用一级字段作为分组卡片标题（跳过冗余的 (root) 层）
            for ch in children:
                self._add_tree_node(root, ch, is_top=True)
        else:
            self._add_tree_node(root, node, is_top=True)
        self.field_tree.expandToDepth(2)

    def _add_tree_node(self, parent: QTreeWidgetItem, node: dict,
                       is_top: bool = False) -> None:
        """递归添加一个字段节点。分组节点=卡片标题样式；叶子=键值行。"""
        label = node.get("label") or "(root)"
        kind = node.get("kind", "unchanged")
        children = node.get("children") or []

        if children:
            # 分组节点（卡片标题）
            cc = node.get("changed_count", 0)
            if kind == "branch" and cc:
                title = f"{label}　　〔差异 {cc}〕"
            else:
                title = label
            item = QTreeWidgetItem([title, "", ""])
            font = QFont(self.font())
            font.setBold(True)
            if is_top:
                _ps = font.pointSize()
                if _ps <= 0:
                    _ps = 9  # QFont() 默认 pointSize=-1，+1 会导致 setPointSize(-1) 警告
                font.setPointSize(_ps + 1)
                item.setBackground(0, QColor("#f2f2f2"))
                item.setForeground(0, QColor("#333333"))
            item.setFont(0, font)
            if kind == "branch":
                item.setForeground(0, _COLOR_MODIFIED)
            parent.addChild(item)
            for ch in children:
                self._add_tree_node(item, ch, is_top=False)
            return

        # 叶子节点（键值行）
        # 未变字段只显示目标值（源列留空），与主界面信息面板"只显示当前值"一致
        if kind == "unchanged":
            bv = ""
            tv = _fmt_value(node.get("target")) if node.get("target") is not None else ""
        else:
            bv = _fmt_value(node.get("base")) if node.get("base") is not None else ""
            tv = _fmt_value(node.get("target")) if node.get("target") is not None else ""
        item = QTreeWidgetItem([label, bv, tv])
        color = _KIND_COLORS.get(kind)
        if color is not None:
            for c in range(3):
                item.setForeground(c, color)
        else:  # unchanged
            item.setForeground(0, QColor("#222222"))
            item.setForeground(2, _COLOR_UNCHANGED)
        parent.addChild(item)
