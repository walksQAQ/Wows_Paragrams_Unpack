"""parts_tree.py —— 模型部件纵列（两个 3D 查看器共用的左侧可勾选部件树）。

一行一个**渲染网格**（``PartEntry.key`` 与视口 ``set_scene`` 生成的网格 key
一一对应，形如 ``hull:3`` / ``mount:12``）：勾选 = 显示，取消 = 隐藏；
``group`` 非空时按分组聚合（船体 / 主炮塔 / 防空 …），组行级联子项；
``group`` 可以是 ``/`` 分隔的**多级路径**（``舰载机/BTD（轰炸机）/AN-M66``），
按层级逐段建节点，父组行的勾选级联到全部后代；
``group`` 为空 = 平铺（模型文件查看器用：一行就是一个形状名）。

行标题由调用方给出，统一使用**模型/形状自己的名字**（不是材质名），并原样附上
顶点格式串（``format_name``，如 ``set3/xyznuvtpcencd``）。

默认可见性由调用方按网格类型给出：

- 普通部件、wire 线框变体：默认勾选；
- 损坏 / 残骸（crack）网格：照常列出，但默认不勾选（可手动打开查看）；
- LOD 低模：调用方**不进列表**（几何阶段就已丢弃）。

状态不跨次加载保存：每次 ``set_entries`` 都按传入的默认值重建。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPalette, QTextOption
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

from utils.theme import theme


@dataclass(frozen=True)
class PartEntry:
    """部件树中的一行（对应视口里的一个渲染网格）。"""

    key: str                 # 与视口网格 key 一一对应（hull:i / mount:i）
    label: str               # 显示名（模型 / 形状名）
    group: str               # 分组路径（"船体" / "舰载机/BTD（轰炸机）/AN-M66"）；空 = 平铺
    checked: bool = True     # 默认是否显示
    badge: str = ""          # 行尾小字（如三角形数）
    detail: str = ""         # tooltip 详细说明
    format_name: str = ""    # 顶点格式串，原样显示（如 set3/xyznuvtpcencd）
    crack: bool = False      # 损坏 / 残骸变体（排序时统一排到分组末尾）


#: 舰船部件的分组顺序（其余分组按出现顺序排在其后）
_GROUP_ORDER = (
    "船体", "主炮塔", "副炮塔", "鱼雷发射管", "深弹发射器", "防空",
    "指挥仪", "测距仪", "雷达", "甲板设备", "舰载机", "其他",
)


def _group_rank(name: str) -> int:
    try:
        return _GROUP_ORDER.index(name)
    except ValueError:
        return len(_GROUP_ORDER)


def _group_path(group: str) -> tuple:
    """`"舰载机/BTD（轰炸机）/AN-M66"` → 分段元组（空组 → 空元组 = 平铺）。"""
    return tuple(p for p in str(group or "").split("/") if p)


def _first_segment(item: QTreeWidgetItem) -> str:
    """分组行的首段名（排序用）；网格行返回空串（排在最后）。"""
    data = item.data(0, Qt.UserRole)
    if not data or data[0] != "group":
        return ""
    return _group_path(data[1])[0] if _group_path(data[1]) else ""


class _WrapDelegate(QStyledItemDelegate):
    """按面板宽度自动换行绘制行文本（长名字/长格式串不省略、不出横向滚动条）。

    ``\n`` 用于调用方强制的换行（格式串单独一行）；超长且无空格的标识符
    按 ``WrapAtWordBoundaryOrAnywhere`` 在任意字符处折行。
    """

    #: 文本区左右留白（右侧补偿 + 避免估算过宽）
    PADDING = 8
    #: 勾选框 + 展开箭头 + 缩进余量（**宁可估宽**：估窄会少算一行 → 格式行被裁掉）
    _DECO_WIDTH = 42

    def __init__(self, tree: QTreeWidget):
        super().__init__(tree)
        self._tree = tree

    def _text_width(self, index) -> int:
        """该行文本区实际可用宽度（扣掉层级缩进 + 勾选框/箭头）。

        ⚠️ 必须按层级扣缩进：只按视口宽度估算会让深一层的长名字少算一行，
        结果行高不够、第二行（格式串）被裁掉。
        """
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        indent = depth * self._tree.indentation() + self._DECO_WIDTH
        return max(80, self._tree.viewport().width() - indent - self.PADDING)

    def _opts(self) -> QTextOption:
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        return opt

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        text = index.data(Qt.DisplayRole) or ""
        if not text:
            return super().sizeHint(option, index)
        width = self._text_width(index)
        rect = option.fontMetrics.boundingRect(
            QRect(0, 0, width, 10000),
            int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), text)
        return QSize(width + self.PADDING,
                     max(option.fontMetrics.height() + 4, int(rect.height()) + 6))

    def paint(self, painter, option, index) -> None:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        # 先让基类样式画出背景/勾选框/选中态，再自己排版文本
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText,
                                         opt, widget)
        painter.save()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        role = (QPalette.ColorRole.HighlightedText if selected
                else QPalette.ColorRole.Text)
        painter.setPen(opt.palette.color(role))
        painter.drawText(QRectF(text_rect), text, self._opts())
        painter.restore()


class PartsTreePanel(QWidget):
    """左侧纵列：按分组列出全部渲染网格 + 逐条勾选显隐。"""

    #: 隐藏网格 key 集合变化（set[str]）
    hidden_changed = Signal(object)

    #: 默认宽度（放进 QSplitter 时作为初始尺寸；用户可拖动分隔条改宽度）
    MIN_WIDTH = 260
    MAX_WIDTH = 820

    def __init__(self, title: str = "模型部件", width: int = 400, parent=None):
        super().__init__(parent)
        self.setObjectName("PartsSide")
        self.preferred_width = int(width)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMaximumWidth(self.MAX_WIDTH)
        self.resize(self.preferred_width, 560)
        # 纯 QWidget 必须开 WA_StyledBackground，QSS 的边框才会真的绘制
        self.setAttribute(Qt.WA_StyledBackground, True)
        theme.bind(self, "#PartsSide { background: transparent;"
                          " border-right: 1px solid @line_structure@; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 10, 2)
        lay.setSpacing(6)

        head = QLabel(title)
        theme.bind(head, "font-size:15px; font-weight:bold; color:@text@;"
                         " background:transparent; border:none;")
        lay.addWidget(head)

        hint = QLabel("勾选 = 显示该网格；取消勾选 = 隐藏。")
        hint.setWordWrap(True)
        theme.bind(hint, "color:@text_muted@; font-size:11px;"
                         " background:transparent; border:none;")
        lay.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.btn_all = QPushButton("全选")
        self.btn_none = QPushButton("全不选")
        self.btn_default = QPushButton("默认")
        self.btn_default.setToolTip("恢复默认可见性（损坏/残骸网格默认隐藏）")
        for b in (self.btn_all, self.btn_none, self.btn_default):
            b.setMaximumWidth(96)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        # 行高随内容变化（格式串换行 → 两行），因此不能固定行高
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(True)
        self.tree.setTextElideMode(Qt.ElideNone)
        # 换行绘制后不再需要横向滚动条：列宽始终等于可视宽度
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollPerPixel)
        self.tree.setItemDelegate(_WrapDelegate(self.tree))
        self.tree.header().setStretchLastSection(True)
        theme.bind(self.tree,
                   "QTreeWidget { background:@input_bg@; color:@text@;"
                   " border:1px solid @border@; border-radius:4px; font-size:12px; }")
        lay.addWidget(self.tree, 1)

        self.summary = QLabel("未加载模型")
        self.summary.setWordWrap(True)
        theme.bind(self.summary, "color:@text_hint@; font-size:11px;"
                                 " background:transparent; border:none;")
        lay.addWidget(self.summary)

        self._building = False
        self._defaults: dict[str, bool] = {}
        self.tree.itemChanged.connect(self._on_item_changed)
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_default.clicked.connect(self.restore_defaults)

    # ── 构建 ──────────────────────────────────────────────

    def set_entries(self, entries: list[PartEntry],
                    group_texts: dict[str, str] | None = None) -> set[str]:
        """按条目重建树，返回默认隐藏的网格 key 集合。

        顺序规则（统一在这里做，两个查看器一致）：**crack（损坏/残骸）行排到
        各自分组的末尾**，其余按名字排序；顶层分组仍按 `_GROUP_ORDER`。
        `PartEntry.group` 支持 ``/`` 分隔的多级路径，逐段建成嵌套节点。

        group_texts：分组路径 → 括号里的计数文字（如 ``{"舰载机/…/AN-M66": "8 枚"}``）；
        缺省按该组下的**网格行数**显示（纯分组计数，不代表实例数）。
        """
        group_texts = group_texts or {}
        entries = sorted(entries or [],
                         key=lambda e: (1 if e.crack else 0, e.label.casefold(), e.key))
        self._defaults = {e.key: bool(e.checked) for e in entries}
        self._building = True
        self.tree.blockSignals(True)
        self.tree.clear()

        # 分组路径 → 该节点下的叶子（网格行）数
        counts: dict[tuple, int] = {}
        paths: list[tuple] = []
        for e in entries:
            path = _group_path(e.group)
            paths.append(path)
            for depth in range(1, len(path) + 1):
                counts[path[:depth]] = counts.get(path[:depth], 0) + 1

        nodes: dict[tuple, QTreeWidgetItem] = {}

        def _node(path: tuple) -> QTreeWidgetItem:
            """取/建该路径的分组行（父节点按需先建）。"""
            item = nodes.get(path)
            if item is not None:
                return item
            item = QTreeWidgetItem([
                f"{path[-1]}（{group_texts.get('/'.join(path)) or counts.get(path, 0)}）"])
            item.setData(0, Qt.UserRole, ("group", "/".join(path)))
            # ⚠️ 不能加 ItemIsAutoTristate：程序里把父项设成 PartiallyChecked 时，
            # Qt 会把它传染给**所有**子项 ⇒ 隐藏集合变成全集（点任意一项全部消失）。
            # 级联与父项状态汇总全部由本类手工处理。
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            parent_path = path[:-1]
            if parent_path:
                _node(parent_path).addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            nodes[path] = item
            return item

        for e, path in zip(entries, paths):
            # 第一行 = 模型名（尽量短）；第二行 = 顶点格式串（原样）+ 面数
            tail = "  ".join(x for x in (e.format_name, e.badge) if x)
            text = f"{e.label}\n{tail}" if tail else e.label
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.UserRole, ("mesh", e.key))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if e.checked else Qt.Unchecked)
            if e.detail:
                item.setToolTip(0, e.detail)
            if path:
                _node(path).addChild(item)
            else:
                self.tree.addTopLevelItem(item)

        # 顶层按 _GROUP_ORDER 排序（首段名决定排序；无分组的行排在最后）
        tops = [self.tree.takeTopLevelItem(0) for _ in range(self.tree.topLevelItemCount())]
        tops.sort(key=lambda it: _group_rank(_first_segment(it)))
        for it in tops:
            self.tree.addTopLevelItem(it)

        # 组内先网格行、后子分组（如「机型」下先机身形状、再弹药分组），避免
        # 弹药分组按形状名首字母插到机身前面
        for node in nodes.values():
            if node.childCount() < 2:
                continue
            kids = [node.takeChild(0) for _ in range(node.childCount())]
            for kid in [k for k in kids if not k.childCount()] + \
                       [k for k in kids if k.childCount()]:
                node.addChild(kid)

        self._refresh_group_states()
        self.tree.blockSignals(False)
        self._building = False
        self._update_summary()
        hidden = self.hidden_keys()
        self.hidden_changed.emit(hidden)
        return hidden

    def resizeEvent(self, event) -> None:  # noqa: N802
        """宽度变化时重排（换行行高依赖可视宽度）。"""
        super().resizeEvent(event)
        self.tree.scheduleDelayedItemsLayout()

    # ── 状态查询 / 批量操作 ────────────────────────────────

    def hidden_keys(self) -> set[str]:
        """当前未勾选（= 隐藏）的网格 key 集合。"""
        out: set[str] = set()
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            item = it.value()
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "mesh" and item.checkState(0) != Qt.Checked:
                out.add(data[1])
            it += 1
        return out

    def _set_all(self, checked: bool) -> None:
        self.tree.blockSignals(True)
        st = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            self._cascade(self.tree.topLevelItem(i), st)
        self.tree.blockSignals(False)
        self._update_summary()
        self.hidden_changed.emit(self.hidden_keys())

    def restore_defaults(self) -> None:
        """恢复本次加载的默认勾选状态（损坏类网格回到隐藏）。"""
        self.tree.blockSignals(True)
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            item = it.value()
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "mesh":
                item.setCheckState(0, Qt.Checked if self._defaults.get(data[1], True)
                                   else Qt.Unchecked)
            it += 1
        self._refresh_group_states()
        self.tree.blockSignals(False)
        self._update_summary()
        self.hidden_changed.emit(self.hidden_keys())

    # ── 内部 ──────────────────────────────────────────────

    @staticmethod
    def _children_state(item: QTreeWidgetItem) -> Qt.CheckState:
        """由子节点勾选状态汇总父节点状态（全勾 / 全不勾 / 部分）。"""
        states = [item.child(i).checkState(0) for i in range(item.childCount())]
        if not states or all(s == Qt.Checked for s in states):
            return Qt.Checked
        if all(s == Qt.Unchecked for s in states):
            return Qt.Unchecked
        return Qt.PartiallyChecked

    def _refresh_group_states(self) -> None:
        """自底向上重算**所有层级**分组行的勾选状态（父行按子行汇总）。"""
        items: list[QTreeWidgetItem] = []
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            items.append(it.value())
            it += 1
        # 迭代器是深度优先前序 → 倒序即「子先于父」
        for item in reversed(items):
            if item.childCount():
                item.setCheckState(0, self._children_state(item))

    def _cascade(self, item: QTreeWidgetItem, st: Qt.CheckState) -> None:
        item.setCheckState(0, st)
        for i in range(item.childCount()):
            self._cascade(item.child(i), st)

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._building:
            return
        self.tree.blockSignals(True)
        st = item.checkState(0)
        if item.childCount():
            for i in range(item.childCount()):
                self._cascade(item.child(i), st)
        # 无论点的是分组行还是网格行，都要向上逐级汇总祖先状态
        # （嵌套分组时父行可能是 PartiallyChecked，不能只算一步）
        parent = item.parent()
        while parent is not None:
            parent.setCheckState(0, self._children_state(parent))
            parent = parent.parent()
        self.tree.blockSignals(False)
        self._update_summary()
        self.hidden_changed.emit(self.hidden_keys())

    def _update_summary(self) -> None:
        total = shown = 0
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            item = it.value()
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "mesh":
                total += 1
                if item.checkState(0) == Qt.Checked:
                    shown += 1
            it += 1
        if not total:
            self.summary.setText("未加载模型")
            return
        self.summary.setText(f"共 {total} 个网格 · 已显示 {shown} 个"
                             f"（隐藏 {total - shown} 个）")
