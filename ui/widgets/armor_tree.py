"""armor_tree.py —— 装甲结构纵列（装甲区 → 部件 → 厚度板块，逐板块勾选显隐）。

与 :class:`ui.widgets.parts_tree.PartsTreePanel` 并列占用模型查看器左栏：
「显示船体」时显示部件列表，「显示装甲」时显示本面板——两块列表不再争抢
右栏那点高度，也不需要用户在两处来回找。

勾选状态直接映射成视口的可见三角形掩码（:attr:`visible_tris_changed`），
选中板块行发 :attr:`plate_selected`（``None`` = 选中的是非板块行）。

⚠️ 父行**不加** ``Qt.ItemIsAutoTristate``：程序里把父项设成
``PartiallyChecked`` 时 Qt 会把它写给所有子项（见 AGENTS.md 部件树同类坑）。
级联与父项汇总全部由本类手工处理。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

from models.collision_materials import zone_display
from utils.theme import theme

# 与部件树共用换行委托（长部件名/长厚度名按面板宽度折行，不出横向滚动条）
from ui.widgets.parts_tree import _WrapDelegate


class ArmorTreePanel(QWidget):
    """左侧纵列：按装甲区/部件/厚度列出全部装甲板块 + 逐条勾选显隐。"""

    #: 可见三角形掩码变化（``np.ndarray[bool]``，长度 = 场景三角形数）
    visible_tris_changed = Signal(object)
    #: 选中板块 key（``(zone, part, tenths)``）；非板块行 / 无选中 = ``None``
    plate_selected = Signal(object)

    #: 默认宽度（放进 QSplitter 时作为初始尺寸；用户可拖动分隔条改宽度）
    MIN_WIDTH = 260
    MAX_WIDTH = 820

    def __init__(self, title: str = "装甲结构", width: int = 400, parent=None):
        super().__init__(parent)
        self.setObjectName("ArmorSide")
        self.preferred_width = int(width)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMaximumWidth(self.MAX_WIDTH)
        self.resize(self.preferred_width, 560)
        # 纯 QWidget 必须开 WA_StyledBackground，QSS 的边框才会真的绘制
        self.setAttribute(Qt.WA_StyledBackground, True)
        theme.bind(self, "#ArmorSide { background: transparent;"
                          " border-right: 1px solid @line_structure@; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 10, 2)
        lay.setSpacing(6)

        head = QLabel(title)
        theme.bind(head, "font-size:15px; font-weight:bold; color:@text@;"
                         " background:transparent; border:none;")
        lay.addWidget(head)

        hint = QLabel("勾选 = 显示该板块；取消勾选 = 隐藏。损坏 / 隐藏板默认不勾选。")
        hint.setWordWrap(True)
        theme.bind(hint, "color:@text_muted@; font-size:11px;"
                         " background:transparent; border:none;")
        lay.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.btn_all = QPushButton("全选")
        self.btn_none = QPushButton("全不选")
        self.btn_default = QPushButton("默认")
        self.btn_default.setToolTip("恢复默认可见性（损坏 / 隐藏板不勾选）")
        for b in (self.btn_all, self.btn_none, self.btn_default):
            b.setMaximumWidth(96)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        # 行高随内容变化（长部件名换行），因此不能固定行高
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

        self.summary = QLabel("无装甲数据")
        self.summary.setWordWrap(True)
        theme.bind(self.summary, "color:@text_hint@; font-size:11px;"
                                 " background:transparent; border:none;")
        lay.addWidget(self.summary)

        self._scene = None
        self._plate_items: dict[tuple, QTreeWidgetItem] = {}
        self._defaults: dict[tuple, bool] = {}
        self._building = False

        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_default.clicked.connect(self.restore_defaults)

    # ── 构建 ──────────────────────────────────────────────

    def set_scene(self, scene) -> int:
        """按 ``ArmorScene`` 重建三级树，返回默认隐藏（损坏板）的三角形数。

        ``scene`` 为 ``None`` 或空场景时清空列表并显示「无装甲数据」。
        """
        self._scene = scene
        self._plate_items = {}
        self._defaults = {}
        tree = self.tree
        self._building = True
        tree.blockSignals(True)
        tree.clear()

        n_hidden = 0
        if scene is not None and getattr(scene, "tri_count", 0):
            for zone in sorted(scene.zones):
                parts = scene.zones[zone]
                zitem = QTreeWidgetItem([zone_display(zone)])
                zitem.setData(0, Qt.UserRole, ("zone", zone))
                zitem.setFlags(zitem.flags() | Qt.ItemIsUserCheckable)
                for part in sorted(parts):
                    tris_part = parts[part]
                    pitem = QTreeWidgetItem([part])
                    pitem.setData(0, Qt.UserRole, ("part", zone, part))
                    pitem.setFlags(pitem.flags() | Qt.ItemIsUserCheckable)
                    for tenths in sorted(tris_part):
                        tris = tris_part[tenths]
                        key = (zone, part, tenths)
                        hidden = any(scene.tri_info[t].hidden for t in tris)
                        if hidden:
                            n_hidden += len(tris)
                        citem = QTreeWidgetItem([f"{tenths / 10.0:g} mm"])
                        citem.setData(0, Qt.UserRole, ("plate", key))
                        citem.setFlags(citem.flags() | Qt.ItemIsUserCheckable)
                        citem.setCheckState(0, Qt.Unchecked if hidden else Qt.Checked)
                        self._swatch(citem, scene.tri_info[tris[0]].color)
                        self._defaults[key] = not hidden
                        self._plate_items[key] = citem
                        pitem.addChild(citem)
                    pitem.setCheckState(0, self._children_state(pitem))
                    zitem.addChild(pitem)
                zitem.setCheckState(0, self._children_state(zitem))
                tree.addTopLevelItem(zitem)

        tree.blockSignals(False)
        self._building = False
        # 默认展开装甲区与部件行：列表够高，一进来就能看到具体板厚，不用逐级点开
        tree.expandToDepth(1)
        self._update_summary()
        self.visible_tris_changed.emit(self.visible_mask())
        return n_hidden

    def clear(self) -> None:
        """清空列表（切船 / 重新加载 / 关闭窗口时调用）。"""
        self.set_scene(None)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """宽度变化时重排（换行行高依赖可视宽度）。"""
        super().resizeEvent(event)
        self.tree.scheduleDelayedItemsLayout()

    # ── 状态查询 / 批量操作 ────────────────────────────────

    def visible_mask(self) -> np.ndarray:
        """按当前勾选状态生成可见三角形掩码（无场景时为空数组）。"""
        sc = self._scene
        if sc is None or not getattr(sc, "tri_count", 0):
            return np.zeros(0, dtype=bool)
        vis = np.zeros(sc.tri_count, dtype=bool)
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            item = it.value()
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "plate" and item.checkState(0) == Qt.Checked:
                for t in sc.tris_for_plate(data[1]):
                    vis[t] = True
            it += 1
        return vis

    def restore_defaults(self) -> None:
        """恢复本次加载的默认勾选状态（损坏 / 隐藏板回到不勾选）。"""
        self.tree.blockSignals(True)
        for key, item in self._plate_items.items():
            item.setCheckState(0, Qt.Checked if self._defaults.get(key, True)
                               else Qt.Unchecked)
        self._sync_parents()
        self.tree.blockSignals(False)
        self._update_summary()
        self.visible_tris_changed.emit(self.visible_mask())

    def select_plate(self, key) -> None:
        """在树中展开并选中指定板块（3D 拾取 → 列表联动）。

        静默执行（阻塞信号）：选中结果由调用方负责，避免与视口互相触发。
        """
        tree = self.tree
        if key is None:
            tree.clearSelection()
            return
        target = self._plate_items.get(key)
        if target is None:
            return
        tree.blockSignals(True)
        tree.clearSelection()
        p = target.parent()
        while p is not None:
            p.setExpanded(True)
            p = p.parent()
        tree.setCurrentItem(target)
        tree.scrollToItem(target)
        target.setSelected(True)
        tree.blockSignals(False)

    def _set_all(self, checked: bool) -> None:
        tree = self.tree
        tree.blockSignals(True)
        st = Qt.Checked if checked else Qt.Unchecked
        for i in range(tree.topLevelItemCount()):
            self._cascade(tree.topLevelItem(i), st)
        tree.blockSignals(False)
        self._update_summary()
        self.visible_tris_changed.emit(self.visible_mask())

    # ── 内部 ──────────────────────────────────────────────

    @staticmethod
    def _children_state(item) -> Qt.CheckState:
        """由子节点勾选状态汇总父节点状态（全勾 / 全不勾 / 部分）。"""
        states = [item.child(i).checkState(0) for i in range(item.childCount())]
        if not states or all(s == Qt.Checked for s in states):
            return Qt.Checked
        if all(s == Qt.Unchecked for s in states):
            return Qt.Unchecked
        return Qt.PartiallyChecked

    @staticmethod
    def _swatch(item, color) -> None:
        """板块节点厚度色块（取装甲颜色前 3 分量）。"""
        r, g, b = int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)
        item.setBackground(0, QColor(r, g, b, 64))

    def _sync_parents(self) -> None:
        """自下而上重算父节点状态（调用方负责 blockSignals）。"""
        for zi in range(self.tree.topLevelItemCount()):
            zone_item = self.tree.topLevelItem(zi)
            for i in range(zone_item.childCount()):
                pitem = zone_item.child(i)
                pitem.setCheckState(0, self._children_state(pitem))
            zone_item.setCheckState(0, self._children_state(zone_item))

    def _cascade(self, item, st) -> None:
        item.setCheckState(0, st)
        for i in range(item.childCount()):
            self._cascade(item.child(i), st)

    def _on_item_changed(self, item, _column: int) -> None:
        """勾选变化：级联子节点 + 向上同步父节点 + 重算可见掩码。"""
        if self._building:
            return
        tree = self.tree
        tree.blockSignals(True)
        st = item.checkState(0)
        for i in range(item.childCount()):
            self._cascade(item.child(i), st)
        p = item.parent()
        while p is not None:
            p.setCheckState(0, self._children_state(p))
            p = p.parent()
        tree.blockSignals(False)
        self._update_summary()
        self.visible_tris_changed.emit(self.visible_mask())

    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        key = None
        if items:
            data = items[0].data(0, Qt.UserRole)
            if data and data[0] == "plate":
                key = data[1]
        self.plate_selected.emit(key)

    def _update_summary(self) -> None:
        sc = self._scene
        if sc is None or not getattr(sc, "tri_count", 0):
            self.summary.setText("无装甲数据")
            return
        n_zones = len(sc.zones)
        n_parts = sum(len(parts) for parts in sc.zones.values())
        n_checked = sum(1 for it in self._plate_items.values()
                        if it.checkState(0) == Qt.Checked)
        self.summary.setText(
            f"共 {len(self._plate_items)} 个板块"
            f"（{n_zones} 装甲区 / {n_parts} 部件），已勾选 {n_checked}")
