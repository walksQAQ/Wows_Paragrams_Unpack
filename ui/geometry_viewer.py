"""
geometry_viewer.py —— 3D 模型查看器（独立顶层窗口）。

复刻穿深计算器的集成模式：独立 QDialog + 懒创建单实例 + 后台线程加载 +
bus.log_message + theme.bind。含装甲厚度图例与显示开关。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QSettings, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QCompleter,
    QPushButton, QCheckBox, QWidget, QProgressBar, QFileDialog, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QSlider, QToolTip,
)

from app.signals import bus
from utils.theme import theme
from utils.threading_utils import run_async
from models.collision_materials import ARMOR_COLOR_SCALE, zone_display


class _Spinner(QWidget):
    """转圈加载指示器：paintEvent 画旋转弧线 + QTimer 驱动（不依赖 QProgressBar 动画）。"""

    def __init__(self, parent=None, size: int = 56, color=QColor("#0078d4")):
        super().__init__(parent)
        self._angle = 0
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def _step(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def start(self):
        self._timer.start(28)

    def stop(self):
        self._timer.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._color, max(3.0, self.width() * 0.07))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = max(4.0, self.width() * 0.12)
        rect = self.rect().adjusted(int(m), int(m), -int(m), -int(m))
        p.drawArc(rect, int(self._angle * 16), 110 * 16)
        p.end()


class _ArmorLegend(QWidget):
    """装甲厚度颜色图例（10 色桶）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(96)
        self.setMinimumHeight(170)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        h = self.height()
        rows = len(ARMOR_COLOR_SCALE)
        row_h = h / rows
        prev_max = 0.0
        for i, (bp, r, g, b) in enumerate(ARMOR_COLOR_SCALE):
            y = i * row_h
            p.fillRect(0, int(y), 16, int(row_h) + 1, QColor.fromRgbF(r, g, b))
            p.setPen(theme["text_muted"] if hasattr(theme, "__getitem__") else QColor("#999999"))
            low = int(prev_max) if i > 0 else 0
            high = int(bp)
            p.drawText(20, int(y + row_h * 0.62), f"{low}–{high} mm")
            prev_max = bp
        p.end()


class GeometryViewerDialog(QDialog):
    """舰船 3D 模型 / 装甲查看器。"""

    #: 记录加载状态供外部查询
    ship_loaded = Signal(str)
    #: 后台加载进度（0..100, 消息, 代数）→ 主线程更新右侧进度条
    progress_changed = Signal(float, str, int)
    #: 后台导出进度（0..100, 消息）→ 主线程更新导出进度条
    export_progress_changed = Signal(float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("3D 模型查看器")
        self.resize(1240, 840)
        self.setMinimumSize(760, 520)

        self._settings = QSettings("walksQAQ", "WowsParagrams")
        self._service = None
        self._ships = []
        self._loading = False
        self._current_geom = None
        self._armor_scene = None
        self._plate_items = {}
        #: 详情面板入口：尚未拿到舰船列表前先挂起，列表就绪后自动载入
        self._pending_ship_id = None
        self._restored_geometry = self._restore_geometry()

        # ── 生命周期 / 取消状态 ──
        self._closed = False          # 关闭标记：关闭后丢弃一切过期任务回调
        self._load_generation = 0     # 加载代数：新任务取代旧任务
        self._loading_ships = False   # 舰船列表后台任务进行中
        self._ships_task = None       # 舰船列表任务句柄（可取消）
        self._load_task = None        # 舰船模型加载任务句柄（可取消）
        # ── 导出状态 ──
        self._exporting = False       # 导出进行中
        self._export_task = None      # 导出任务句柄（可取消）

        self._build_ui()
        theme.bind(self, "QDialog { background: @panel_bg@; }")
        bus.log_message.connect(self._on_log)

        # 舰船列表后台加载（保存句柄，关闭时可取消）
        self._start_ships_load()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        body = QHBoxLayout()
        body.setSpacing(8)
        root.addLayout(body, stretch=1)

        # ── 左侧：3D 视口（容器内叠加转圈加载提示）──
        from ui.geometry_renderer import GeometryViewport
        self.viewport = GeometryViewport()
        theme.bind(self.viewport, "QOpenGLWidget { background:#16181d; border:1px solid @border@; border-radius:6px; }")
        self.view_container = QWidget()
        _vc = QGridLayout(self.view_container)
        _vc.setContentsMargins(0, 0, 0, 0)
        _vc.setSpacing(0)
        _vc.addWidget(self.viewport, 0, 0)
        # 加载覆盖层：半透明遮罩 + 居中转圈 + 文本（覆盖在渲染区之上）
        self.loading_overlay = QWidget(self.view_container)
        self.loading_overlay.setObjectName("loadingOverlay")
        self.loading_overlay.setVisible(False)
        self.loading_overlay.setStyleSheet(
            "QWidget#loadingOverlay { background: rgba(18,20,26,168); border-radius:6px; }")
        _lo = QVBoxLayout(self.loading_overlay)
        _lo.setAlignment(Qt.AlignCenter)
        _lo.setSpacing(10)
        self.spinner = _Spinner(size=56)
        _lo.addWidget(self.spinner, 0, Qt.AlignCenter)
        self.loading_label = QLabel("加载舰船模型...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        theme.bind(self.loading_label, "color:@text@; font-size:13px; background:transparent; border:none;")
        _lo.addWidget(self.loading_label, 0, Qt.AlignCenter)
        _vc.addWidget(self.loading_overlay, 0, 0)
        body.addWidget(self.view_container, stretch=1)
        # ── 右侧：控制面板 ──
        panel = QWidget()
        panel.setFixedWidth(330)
        theme.bind(panel, "QWidget { background: @panel_bg@; }")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)

        title = QLabel("3D 模型查看器")
        theme.bind(title, "font-size:15px; font-weight:bold; color:@text@; background:transparent; border:none;")
        pl.addWidget(title)

        # 舰船选择（筛选入口已移到详情面板「基础属性」卡片，此处隐藏保留实例供内部复用）
        ship_row = QHBoxLayout()
        self.ship_combo = QComboBox()
        self.ship_combo.setEditable(True)
        self.ship_combo.setPlaceholderText("搜索舰船...")
        self.ship_combo.setInsertPolicy(QComboBox.NoInsert)
        self.ship_combo.setMinimumWidth(180)
        theme.bind(self.ship_combo, "QComboBox { background:@input_bg@; color:@text@; border:1px solid @border@; border-radius:4px; padding:4px 6px; }")
        self.btn_load = QPushButton("加载")
        theme.bind(self.btn_load, "QPushButton { background:@toolbar_btn_bg@; color:@toolbar_btn_text@; border:1px solid @toolbar_btn_border@; border-radius:4px; padding:6px 12px; }")
        ship_row.addWidget(self.ship_combo, 1)
        ship_row.addWidget(self.btn_load)
        self._ship_row_widget = QWidget()
        self._ship_row_widget.setLayout(ship_row)
        self._ship_row_widget.setVisible(False)
        pl.addWidget(self._ship_row_widget)

        self.ship_status = QLabel("正在加载舰船列表...")
        theme.bind(self.ship_status, "color:@text_muted@; font-size:11px; background:transparent; border:none;")
        self.ship_status.setVisible(False)
        pl.addWidget(self.ship_status)

        # 进度
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(16)
        theme.bind(self.progress, "QProgressBar { border:1px solid #0078d4; border-radius:4px; background:@input_bg@; text-align:center; color:@text@; }"
                    "QProgressBar::chunk { background:#0078d4; }")
        pl.addWidget(self.progress)
        # 后台线程经信号投递进度 → 主线程更新进度条
        self.progress_changed.connect(self._on_progress_changed)

        sec_style = "color:@text_muted@; font-size:11px; font-weight:bold; background:transparent; border:none; padding-top:4px;"
        cb_style = "QCheckBox { color:@text@; font-size:12px; spacing:6px; }"

        # ── 显示选项 ──
        self._add_section_title(pl, "显示", sec_style)
        self.cb_hull = QCheckBox("显示船体")
        self.cb_hull.setChecked(True)
        self.cb_armor = QCheckBox("显示装甲（厚度着色）")
        # 默认关闭装甲叠加：先显示干净的贴图船体
        self.cb_armor.setChecked(False)
        self.cb_wire = QCheckBox("线框叠加")
        self.cb_wire.setChecked(False)
        self.cb_edges = QCheckBox("板块边界描边")
        self.cb_edges.setChecked(True)
        for cb in (self.cb_hull, self.cb_armor, self.cb_wire,
                   self.cb_edges):
            theme.bind(cb, cb_style)
            pl.addWidget(cb)

        op_row = QHBoxLayout()
        op_label = QLabel("装甲不透明度")
        theme.bind(op_label, "color:@text@; font-size:12px; background:transparent; border:none;")
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(100)
        self.opacity_value = QLabel("100%")
        self.opacity_value.setFixedWidth(36)
        theme.bind(self.opacity_value, "color:@text_muted@; font-size:11px; background:transparent; border:none;")
        op_row.addWidget(op_label)
        op_row.addWidget(self.opacity_slider, 1)
        op_row.addWidget(self.opacity_value)
        pl.addLayout(op_row)

        # ── 装甲结构树（Zone → 部件 → 板块，三态 checkbox 级联显隐） ──
        self._add_section_title(pl, "装甲结构", sec_style)
        tree_row = QHBoxLayout()
        self.btn_all = QPushButton("全选")
        self.btn_none = QPushButton("全不选")
        for b in (self.btn_all, self.btn_none):
            theme.bind(b, "QPushButton { background:@toolbar_btn_bg@; color:@toolbar_btn_text@; border:1px solid @toolbar_btn_border@; border-radius:4px; padding:3px 10px; font-size:11px; }")
        tree_row.addWidget(self.btn_all)
        tree_row.addWidget(self.btn_none)
        tree_row.addStretch(1)
        pl.addLayout(tree_row)

        self.armor_tree = QTreeWidget()
        self.armor_tree.setColumnCount(1)
        self.armor_tree.setHeaderHidden(True)
        self.armor_tree.setRootIsDecorated(True)
        self.armor_tree.setUniformRowHeights(True)
        theme.bind(self.armor_tree,
                   "QTreeWidget { background:@input_bg@; color:@text@; border:1px solid @border@; border-radius:4px; font-size:12px; }"
                   "QHeaderView::section { background:@panel_bg@; color:@text_muted@; border:none; border-bottom:1px solid @border@; padding:2px 4px; font-size:11px; }")
        pl.addWidget(self.armor_tree, stretch=1)

        # ── 选中信息 ──
        self._add_section_title(pl, "选中信息", sec_style)
        self.sel_label = QLabel("未选中（点击装甲板块选中）")
        self.sel_label.setWordWrap(True)
        self.sel_label.setAlignment(Qt.AlignTop)
        theme.bind(self.sel_label, "color:@text@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(self.sel_label)

        # 统计
        self.stats_label = QLabel("未加载")
        self.stats_label.setWordWrap(True)
        self.stats_label.setAlignment(Qt.AlignTop)
        theme.bind(self.stats_label, "color:@text_muted@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(self.stats_label)

        # ── 模型导出（渲染模型 / 装甲模型 分开导出）──
        self._add_section_title(pl, "导出模型", sec_style)
        export_row = QHBoxLayout()
        self.btn_export_render = QPushButton("导出渲染模型")
        self.btn_export_armor = QPushButton("导出装甲模型")
        for b in (self.btn_export_render, self.btn_export_armor):
            theme.bind(b, "QPushButton { background:@toolbar_btn_bg@; color:@toolbar_btn_text@; border:1px solid @toolbar_btn_border@; border-radius:4px; padding:4px 8px; font-size:11px; }")
        export_row.addWidget(self.btn_export_render)
        export_row.addWidget(self.btn_export_armor)
        pl.addLayout(export_row)
        self.export_progress = QProgressBar()
        self.export_progress.setVisible(False)
        self.export_progress.setFixedHeight(14)
        theme.bind(self.export_progress, "QProgressBar { border:1px solid #0078d4; border-radius:4px; background:@input_bg@; text-align:center; color:@text@; }"
                    "QProgressBar::chunk { background:#0078d4; }")
        pl.addWidget(self.export_progress)
        self.export_status = QLabel("渲染模型：舰体 + 挂载；装甲模型：厚度着色板块")
        self.export_status.setWordWrap(True)
        self.export_status.setAlignment(Qt.AlignTop)
        theme.bind(self.export_status, "color:@text_hint@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(self.export_status)
        # 后台线程经信号投递导出进度 → 主线程更新进度条
        self.export_progress_changed.connect(self._on_export_progress)

        # ── 装甲厚度图例（可折叠） ──
        self.btn_legend = QPushButton("▸ 装甲厚度图例")
        self.btn_legend.setFlat(True)
        theme.bind(self.btn_legend, "QPushButton { color:@text@; font-size:12px; font-weight:bold; text-align:left; background:transparent; border:none; padding:2px 0; }")
        self.legend_widget = _ArmorLegend()
        self.legend_widget.setVisible(False)
        pl.addWidget(self.btn_legend)
        pl.addWidget(self.legend_widget)

        # 操作提示
        hint = QLabel("左键拖拽：旋转　滚轮：缩放　右键拖拽：平移\n"
                      "悬停装甲：查看厚度　点击装甲：选中板块")
        hint.setWordWrap(True)
        theme.bind(hint, "color:@text_hint@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(hint)

        body.addWidget(panel)

        # ── 信号 ──
        self.btn_load.clicked.connect(self._on_load)
        self.ship_combo.lineEdit().returnPressed.connect(self._on_load)
        self.cb_hull.toggled.connect(self._on_hull_toggled)
        self.cb_armor.toggled.connect(self._on_armor_toggled)
        self.cb_wire.toggled.connect(lambda v: self.viewport.set_view_options(wireframe=v))
        self.cb_edges.toggled.connect(lambda v: self.viewport.set_armor_display(show_edges=v))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.btn_all.clicked.connect(lambda: self._set_all_tree_checked(True))
        self.btn_none.clicked.connect(lambda: self._set_all_tree_checked(False))
        self.btn_legend.clicked.connect(self._toggle_legend)
        self.armor_tree.itemChanged.connect(self._on_tree_item_changed)
        self.armor_tree.itemSelectionChanged.connect(self._on_tree_selection)
        # 模型导出（渲染 / 装甲 分开）
        self.btn_export_render.clicked.connect(lambda: self._start_export(False))
        self.btn_export_armor.clicked.connect(lambda: self._start_export(True))
        # 3D 拾取回调
        self.viewport.on_hover = self._on_viewport_hover
        self.viewport.on_select = self._on_viewport_select

    def _add_section_title(self, layout, text, style):
        t = QLabel(text)
        theme.bind(t, style)
        layout.addWidget(t)

    def _toggle_legend(self):
        show = not self.legend_widget.isVisible()
        self.legend_widget.setVisible(show)
        self.btn_legend.setText("▾ 装甲厚度图例" if show else "▸ 装甲厚度图例")

    def _on_opacity_changed(self, v: int):
        self.opacity_value.setText(f"{v}%")
        self.viewport.set_armor_display(opacity=v / 100.0)

    # ── 显示开关 ─────────────────────────────────────────

    def _on_hull_toggled(self, v: bool):
        """显示船体/装甲互斥：勾选船体时取消装甲。"""
        if v:
            self.cb_armor.setChecked(False)
        self.viewport.set_view_options(show_hull=v)

    def _on_armor_toggled(self, v: bool):
        """装甲显示开关：启用时取消船体。"""
        if v:
            self.cb_hull.setChecked(False)
        else:
            self.cb_hull.setChecked(True)
            # 关闭装甲时清除悬停状态与残留提示（鼠标静止时不会触发 hover 回调）
            self.viewport._hover_tri = None
            QToolTip.hideText()
        self.viewport.set_view_options(show_armor=v)

    # ── 装甲结构树 ───────────────────────────────────────

    def _build_armor_tree(self):
        """由 ArmorScene 构建 Zone→部件→板块 三级树（checkbox 级联显隐）。"""
        tree = self.armor_tree
        tree.blockSignals(True)
        tree.clear()
        self._plate_items = {}
        sc = self._armor_scene
        n_hidden = 0
        if sc is not None and sc.tri_count:
            for zone in sorted(sc.zones):
                parts = sc.zones[zone]
                zitem = QTreeWidgetItem([zone_display(zone)])
                zitem.setData(0, Qt.UserRole, ("zone", zone))
                zitem.setFlags(zitem.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                for part in sorted(parts):
                    tris_part = parts[part]
                    pitem = QTreeWidgetItem([part])
                    pitem.setData(0, Qt.UserRole, ("part", zone, part))
                    pitem.setFlags(pitem.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                    for tenths in sorted(tris_part):
                        tris = tris_part[tenths]
                        key = (zone, part, tenths)
                        hidden = any(sc.tri_info[t].hidden for t in tris)
                        if hidden:
                            n_hidden += len(tris)
                        mm = tenths / 10.0
                        color = sc.tri_info[tris[0]].color
                        citem = QTreeWidgetItem([f"{mm:g} mm"])
                        citem.setData(0, Qt.UserRole, ("plate", key))
                        citem.setFlags(citem.flags() | Qt.ItemIsUserCheckable)
                        st = Qt.Unchecked if hidden else Qt.Checked
                        citem.setCheckState(0, st)
                        self._swatch(citem, color)
                        self._plate_items[key] = citem
                        pitem.addChild(citem)
                    pitem.setCheckState(0, self._children_state(pitem))
                    zitem.addChild(pitem)
                zitem.setCheckState(0, self._children_state(zitem))
                tree.addTopLevelItem(zitem)
        tree.blockSignals(False)
        self._apply_tree_visibility()
        return n_hidden

    @staticmethod
    def _children_state(item):
        """由子节点勾选状态汇总父节点状态（全勾/全不勾/部分）。"""
        states = [item.child(i).checkState(0) for i in range(item.childCount())]
        if not states or all(s == Qt.Checked for s in states):
            return Qt.Checked
        if all(s == Qt.Unchecked for s in states):
            return Qt.Unchecked
        return Qt.PartiallyChecked

    @staticmethod
    def _swatch(item, color):
        """板块节点厚度色块（取装甲颜色前 3 分量）。"""
        r, g, b = int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)
        item.setBackground(0, QColor(r, g, b, 64))

    def _on_tree_item_changed(self, item, column):
        """checkbox 变化：级联子节点 + 重算可见掩码。"""
        tree = self.armor_tree
        tree.blockSignals(True)
        st = item.checkState(0)
        for i in range(item.childCount()):
            self._cascade_check(item.child(i), st)
        # 向上同步父节点状态
        p = item.parent()
        while p is not None:
            p.setCheckState(0, self._children_state(p))
            p = p.parent()
        tree.blockSignals(False)
        self._apply_tree_visibility()

    def _cascade_check(self, item, st):
        item.setCheckState(0, st)
        for i in range(item.childCount()):
            self._cascade_check(item.child(i), st)

    def _set_all_tree_checked(self, checked: bool):
        tree = self.armor_tree
        tree.blockSignals(True)
        st = Qt.Checked if checked else Qt.Unchecked
        for i in range(tree.topLevelItemCount()):
            self._cascade_check(tree.topLevelItem(i), st)
        tree.blockSignals(False)
        self._apply_tree_visibility()

    def _apply_tree_visibility(self):
        """按树的勾选状态重建可见三角形掩码 → 视口。"""
        sc = self._armor_scene
        if sc is None or not sc.tri_count:
            return
        import numpy as np
        vis = np.zeros(sc.tri_count, dtype=bool)
        it = QTreeWidgetItemIterator(self.armor_tree)
        while it.value() is not None:
            item = it.value()
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "plate" and item.checkState(0) == Qt.Checked:
                for t in sc.tris_for_plate(data[1]):
                    vis[t] = True
            it += 1
        self.viewport.set_visible_tris(vis)

    def _on_tree_selection(self):
        """树选中 → 3D 高亮（仅板块级）。"""
        items = self.armor_tree.selectedItems()
        key = None
        if items:
            data = items[0].data(0, Qt.UserRole)
            if data and data[0] == "plate":
                key = data[1]
        if key == self.viewport._selected_plate:
            return
        from ui.geometry_renderer import HIGHLIGHT_SELECT
        self.viewport._hl_color = HIGHLIGHT_SELECT
        self.viewport.select_plate(key)
        self._update_sel_label(key)

    # ── 3D 拾取联动 ──────────────────────────────────────

    def _on_viewport_hover(self, tri, global_pos):
        """悬停拾取 → QToolTip（厚度色块 + zone/材质 + 多层堆叠）。"""
        sc = self._armor_scene
        if tri is None or sc is None:
            QToolTip.hideText()
            return
        info = sc.tri_info[tri]
        mm = info.thickness_mm
        r, g, b = int(info.color[0] * 255), int(info.color[1] * 255), int(info.color[2] * 255)
        swatch = (f'<span style="display:inline-block;width:10px;height:10px;'
                  f'background:rgb({r},{g},{b});border:1px solid #888;"></span>')
        lines = [f'{swatch} <b>{mm:g} mm</b>　{zone_display(info.zone)} / {info.material_name}']
        if len(info.layers) > 1:
            layer_txt = "、".join(
                f'<b>{l:g}</b>' if abs(l - mm) < 0.05 else f'{l:g}' for l in info.layers)
            lines.append(f'层堆叠：{layer_txt} mm')
        QToolTip.showText(global_pos, "<br>".join(lines), self.viewport)

    def _on_viewport_select(self, key):
        """3D 点击选中 → 树定位 + 信息面板。"""
        from ui.geometry_renderer import HIGHLIGHT_SELECT
        self.viewport._hl_color = HIGHLIGHT_SELECT
        self._update_sel_label(key)
        self._sync_tree_to_plate(key)

    def _update_sel_label(self, key):
        sc = self._armor_scene
        if key is None or sc is None:
            self.sel_label.setText("未选中（点击装甲板块选中）")
            return
        tris = sc.tris_for_plate(key)
        info = sc.tri_info[tris[0]] if tris else None
        zone, part, tenths = key
        mm = tenths / 10.0
        txt = f"板块：{zone_display(zone)} / {part}\n厚度：{mm:g} mm　三角形：{len(tris):,}"
        if info is not None and len(info.layers) > 1:
            txt += f"\n层堆叠：{'、'.join(f'{l:g}' for l in info.layers)} mm"
        self.sel_label.setText(txt)

    def _sync_tree_to_plate(self, key):
        """展开并选中树中对应板块节点（3D→树联动）。"""
        tree = self.armor_tree
        tree.blockSignals(True)
        tree.clearSelection()
        target = self._plate_items.get(key) if hasattr(self, "_plate_items") else None
        if target is None:
            # 按数据查找
            it = QTreeWidgetItemIterator(tree)
            while it.value() is not None:
                data = it.value().data(0, Qt.UserRole)
                if data and data[0] == "plate" and data[1] == key:
                    target = it.value()
                    break
                it += 1
        if target is not None:
            p = target.parent()
            while p is not None:
                p.setExpanded(True)
                p = p.parent()
            tree.setCurrentItem(target)
            tree.scrollToItem(target)
            target.setSelected(True)
        tree.blockSignals(False)

    # ── 舰船列表 ─────────────────────────────────────────

    def _get_service(self):
        if self._service is None:
            from services.geometry_service import GeometryService
            self._service = GeometryService.instance()
        return self._service

    def _start_ships_load(self):
        """后台加载舰船列表（幂等：已有结果/已在加载则跳过；保存句柄可取消）。"""
        if self._ships or self._loading_ships:
            return
        self._loading_ships = True
        self.ship_status.setText("正在加载舰船列表...")
        self._ships_task = run_async(self._load_ships_task,
                                     on_finished=self._on_ships_loaded,
                                     on_error=self._on_ships_error)

    def _load_ships_task(self):
        return self._get_service().list_ships()

    def _on_ships_loaded(self, ships):
        self._loading_ships = False
        if self._closed:
            return  # 窗口已关闭：丢弃过期列表结果
        self._ships = ships or []
        self.ship_combo.clear()
        for s in self._ships:
            label = f"{s.display_name}  ({s.game_key})" if s.display_name != s.game_key else s.game_key
            self.ship_combo.addItem(label, s)
        if self._ships:
            completer = QCompleter([self.ship_combo.itemText(i) for i in range(self.ship_combo.count())], self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.ship_combo.setCompleter(completer)
            self.ship_status.setText(f"共 {len(self._ships)} 艘舰船（可搜索）")
            # 默认不选中任何舰船：由用户搜索/选择后手动点「加载」
            self.ship_combo.setCurrentIndex(-1)
        else:
            err = getattr(self._get_service(), "_ships_error", None)
            self.ship_status.setText(f"舰船列表为空：{err or '请先加载数据'}")
        # 列表就绪后兑现详情面板挂起的自动载入请求
        self._try_load_pending()

    def open_ship(self, ship_id: str) -> None:
        """外部入口（详情面板「基础属性」卡片按钮）：载入指定舰船。

        舰船列表尚在后台加载时挂起请求，列表就绪后自动载入。
        """
        if not ship_id:
            return
        self._pending_ship_id = ship_id
        self._try_load_pending()

    def _try_load_pending(self):
        """舰船列表就绪且空闲时，载入挂起的舰船。"""
        if self._closed:
            return
        if not self._pending_ship_id or self._loading or not self._ships:
            return
        ship = next((s for s in self._ships if s.game_key == self._pending_ship_id), None)
        if ship is None:
            bus.log_message.emit(f"⚠️ 3D: 未找到舰船 {self._pending_ship_id} 的模型数据")
            self._pending_ship_id = None
            return
        self._pending_ship_id = None
        # 同步隐藏 combo 选中项，复用既有加载流程
        self.ship_combo.setCurrentIndex(self._ships.index(ship))
        self._on_load()

    def _on_ships_error(self, err):
        self._loading_ships = False
        if self._closed:
            return
        self.ship_status.setText(f"加载舰船列表失败: {err}")

    # ── 加载舰船 ─────────────────────────────────────────

    def _selected_ship(self):
        idx = self.ship_combo.currentIndex()
        if 0 <= idx < len(self._ships):
            return self._ships[idx]
        # 按文本反查
        text = self.ship_combo.currentText().strip()
        for s in self._ships:
            if text == s.game_key or text == s.display_name or text in f"{s.display_name} ({s.game_key})":
                return s
        return None

    def _set_loading_overlay(self, show: bool, text: str = ""):
        """显示/隐藏渲染区之上的转圈加载覆盖层。"""
        if text:
            self.loading_label.setText(text)
        if show:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.loading_overlay.setVisible(show)
        self.loading_overlay.raise_()

    def _on_load(self):
        if self._loading:
            return
        ship = self._selected_ship()
        if ship is None:
            self.stats_label.setText("未找到匹配的舰船")
            return
        # 取消旧加载任务（若仍在运行），并让旧回调因代数不匹配而失效
        if self._load_task is not None:
            self._load_task.cancel()
        self._load_generation += 1
        gen = self._load_generation
        self._loading = True
        self.btn_load.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.stats_label.setText(f"正在加载 {ship.display_name}...")
        self._set_loading_overlay(True, f"正在加载 {ship.display_name}...")

        def _work(cancel_event):
            geom = self._get_service().load_ship(
                ship,
                progress_cb=lambda p, m: self._on_progress(p, m, gen),
                cancel_event=cancel_event,
            )
            # 后台构建装甲聚合场景（拾取/描边/层级数据源）
            from models.armor_scene import ArmorScene
            scene = ArmorScene.build(geom.armor_meshes, cancel_event=cancel_event)
            return geom, scene

        self._load_task = run_async(
            _work,
            on_finished=lambda r: self._on_ship_loaded(r, gen),
            on_error=lambda e: self._on_ship_error(e, gen),
            cancel_event=threading.Event(),
        )

    def _on_progress(self, pct, msg, gen):
        # 后台线程调用：经信号投递到主线程更新进度条；关闭或旧任务不再刷
        if self._closed or gen != self._load_generation:
            return
        self.progress_changed.emit(float(pct), msg, gen)
        bus.log_message.emit(f"🔧 3D: {msg} ({pct:.0f}%)")

    def _on_progress_changed(self, pct: float, msg: str, gen: int) -> None:
        """主线程更新进度条（由后台线程经信号投递，带代数防过期覆盖）。"""
        if self._closed or gen != self._load_generation:
            return
        pct = max(0.0, min(100.0, float(pct)))
        self.progress.setValue(int(pct))
        self.progress.setFormat(f"{msg}  {pct:.0f}%")

    def _on_ship_loaded(self, result, gen):
        if self._closed or gen != self._load_generation:
            return  # 窗口已关闭或已被新任务取代：丢弃过期结果
        geom, scene = result
        self._loading = False
        self.btn_load.setEnabled(True)
        self.progress.setVisible(False)
        self._set_loading_overlay(False)
        self._current_geom = geom
        self._armor_scene = scene if scene.tri_count else None
        # 船体/装甲互斥：装甲开启时取消船体勾选（保持 UI 与渲染一致）
        if self.cb_armor.isChecked() and self.cb_hull.isChecked():
            self.cb_hull.setChecked(False)
        self.viewport.set_scene(geom, show_hull=self.cb_hull.isChecked(),
                                show_armor=self.cb_armor.isChecked(),
                                armor_scene=self._armor_scene)
        # 同步显示选项到新场景
        self.viewport.set_armor_display(
            opacity=self.opacity_slider.value() / 100.0,
            show_edges=self.cb_edges.isChecked())
        # 构建三级结构树（hidden 板默认不勾选）
        n_hidden = self._build_armor_tree()
        self.sel_label.setText("未选中（点击装甲板块选中）")
        st = geom.stats or {}
        total_v = sum(h.vertex_count for h in geom.hull_meshes)
        total_t = sum(h.indices.size // 3 for h in geom.hull_meshes)
        armor_t = sum(len(a.triangles) for a in geom.armor_meshes)
        known_t = sum(sum(1 for t in a.triangles if t.thickness_mm > 0) for a in geom.armor_meshes)
        mounts_n = len(geom.mounts)
        mounts_v = sum(m.vertex_count for m in geom.mounts)
        deck_n = st.get("deck_equipment", 0)
        sub_n = st.get("sub_equipment", 0)
        hp_n = mounts_n - deck_n - sub_n
        warns = len(st.get("warnings", []))
        tex_info = "贴图：已加载" if geom.texture_dds else "贴图：未找到"
        # 装甲结构统计（板块/部件/zone 数）
        if self._armor_scene is not None:
            sc = self._armor_scene
            n_zones = len(sc.zones)
            n_parts = sum(len(parts) for parts in sc.zones.values())
            n_plates = len(sc.plate_keys_by_id)
            struct_info = f"结构：{n_zones} 装甲区 / {n_parts} 部件 / {n_plates} 板块（边界线 {sc.edge_positions.shape[0] // 2:,}）"
        else:
            struct_info = "结构：无装甲数据"
        self.stats_label.setText(
            f"舰船：{geom.display_name}（{geom.game_key}）\n"
            f"模型：{geom.model_folder}\n"
            f"船体：{total_v:,} 顶点 / {total_t:,} 三角形\n"
            f"挂载：{mounts_n} 个（HP {hp_n} + 甲板设备 {deck_n} + 部件子设备 {sub_n}，{mounts_v:,} 顶点）\n"
            f"装甲：{armor_t:,} 三角形（厚度已知 {known_t:,}，隐藏板 {n_hidden:,}）\n"
            f"{struct_info}\n"
            f"{tex_info}\n"
            f"包围盒：{geom.bounds_size[0]:.1f} × {geom.bounds_size[1]:.1f} × {geom.bounds_size[2]:.1f}\n"
            + (f"⚠️ 警告 {warns} 条（见日志）" if warns else "")
        )
        # 把加载警告逐条写入日志区（此前只显示"警告 N 条（见日志）"但日志区从未收到内容）
        for w in st.get("warnings", []):
            bus.log_message.emit(f"⚠️ 3D 加载警告: {w}")
        bus.log_message.emit(
            f"✅ 3D: {geom.display_name} 加载完成（船体 {total_t:,} 三角形 / "
            f"挂载 {mounts_n} 个（HP {hp_n} + 甲板设备 {deck_n} + 部件子设备 {sub_n}） / "
            f"装甲 {armor_t:,}）")
        self.ship_loaded.emit(geom.game_key)
        # 加载期间又收到新的 open_ship 请求 → 现在兑现
        self._try_load_pending()

    def _on_ship_error(self, err, gen):
        if self._closed or gen != self._load_generation:
            return  # 窗口已关闭或已被新任务取代：丢弃过期结果
        self._loading = False
        self.btn_load.setEnabled(True)
        self.progress.setVisible(False)
        self._set_loading_overlay(False)
        self.stats_label.setText(f"加载失败: {err}")
        bus.log_message.emit(f"❌ 3D 加载失败: {err}")
        # 加载失败也要兑现挂起请求，避免按钮点击被吞掉
        self._try_load_pending()

    # ── 模型导出（渲染 / 装甲 分开）─────────────────────

    def _start_export(self, armor: bool):
        """导出入口：选路径 → 后台导出（只读 ShipGeometry/ArmorScene）。"""
        if self._loading or self._exporting:
            return
        geom = self._current_geom
        if geom is None:
            self.export_status.setText("请先加载舰船模型")
            bus.log_message.emit("⚠️ 导出: 请先加载舰船模型")
            return
        if armor and (self._armor_scene is None or not self._armor_scene.tri_count):
            self.export_status.setText("当前舰船没有装甲数据")
            bus.log_message.emit("⚠️ 导出: 当前舰船没有装甲数据")
            return
        base = (geom.display_name or geom.game_key).replace(" ", "_")
        base = base.replace("/", "_").replace("\\", "_").replace(":", "_")
        default_name = f"{base}_armor.glb" if armor else f"{base}_render.glb"
        title = "导出装甲模型 (GLB)" if armor else "导出渲染模型 (GLB)"
        path, _ = QFileDialog.getSaveFileName(self, title, default_name,
                                              "glTF 2.0 Binary (*.glb)")
        if not path:
            return
        if not path.lower().endswith(".glb"):
            path += ".glb"
        self._begin_export(path, armor)

    def _begin_export(self, path: str, armor: bool):
        """启动后台导出任务（后台线程只读几何对象，不触碰 Qt/OpenGL）。"""
        import numpy as np
        self._exporting = True
        self._export_task = None
        for b in (self.btn_export_render, self.btn_export_armor):
            b.setEnabled(False)
        self.export_progress.setVisible(True)
        self.export_progress.setValue(0)
        self.export_status.setText("导出中，请稍候...")
        geom = self._current_geom
        armor_scene = self._armor_scene
        # 冻结当前查看器的装甲显隐掩码（后台线程读取快照）
        visible = None
        if armor and armor_scene is not None and self.viewport._visible_tris is not None:
            visible = np.asarray(self.viewport._visible_tris, dtype=bool).copy()

        def _work(cancel_event):
            from services.export_service import export_render_glb, export_armor_glb
            if armor:
                return export_armor_glb(
                    geom, armor_scene, path, visible_tris=visible,
                    cancel_event=cancel_event,
                    progress_cb=lambda p, m: self.export_progress_changed.emit(float(p), m))
            return export_render_glb(
                geom, path, cancel_event=cancel_event,
                progress_cb=lambda p, m: self.export_progress_changed.emit(float(p), m))

        self._export_task = run_async(
            _work,
            on_finished=self._on_export_done,
            on_error=self._on_export_error,
            cancel_event=threading.Event(),
        )

    def _on_export_progress(self, pct: float, msg: str) -> None:
        """主线程更新导出进度条（由后台线程经信号投递）。"""
        if self._closed or not self._exporting:
            return
        pct = max(0.0, min(100.0, float(pct)))
        self.export_progress.setValue(int(pct))
        self.export_progress.setFormat(f"{msg}  {pct:.0f}%")

    def _on_export_done(self, report):
        if self._closed:
            return
        self._exporting = False
        for b in (self.btn_export_render, self.btn_export_armor):
            b.setEnabled(True)
        self.export_progress.setVisible(False)
        self.export_status.setText("")
        for w in report.warnings:
            bus.log_message.emit(f"⚠️ 导出警告: {w}")
        bus.log_message.emit(report.summary())
        QMessageBox.information(self, "导出完成", report.summary())

    def _on_export_error(self, err):
        if self._closed:
            return
        self._exporting = False
        for b in (self.btn_export_render, self.btn_export_armor):
            b.setEnabled(True)
        self.export_progress.setVisible(False)
        self.export_status.setText("导出失败")
        bus.log_message.emit(f"❌ 导出失败: {err}")
        QMessageBox.warning(self, "导出失败", f"导出失败：{err}")

    # ── 生命周期 ─────────────────────────────────────────

    def _on_log(self, msg: str):
        # 后台线程进度消息走日志面板，这里无需额外处理
        pass

    def center_on_screen(self, relative_to=None):
        from utils.window_utils import center_on_screen
        center_on_screen(self, relative_to)

    def showEvent(self, event):
        # 重新显示：清除关闭状态，按需重载舰船列表/兑现挂起请求
        self._closed = False
        self._start_ships_load()
        self._try_load_pending()
        super().showEvent(event)

    def closeEvent(self, event):
        self._closed = True
        # 后台任务收尾：舰船列表快速查询用协作式取消；模型加载是只读/内存型，
        # 用 kill() 强制终止（无论进度如何立即结束），避免关闭后仍在后台解析。
        if self._ships_task is not None:
            self._ships_task.cancel()
        if self._load_task is not None:
            self._load_task.kill(timeout=1.0)
        self._load_task = None
        self._ships_task = None
        # 导出任务：只读几何/内存型，取消并强制收尾（写入外部路径，不阻塞关闭）
        if self._export_task is not None:
            self._export_task.cancel()
            self._export_task.kill(timeout=1.0)
        self._export_task = None
        self._exporting = False
        # 释放服务层缓存的本次加载重内存（挂载几何/贴图/材质/快照等），
        # 否则关闭后内存仍被单例 GeometryService 占用
        if self._service is not None:
            self._service.release_load_caches()
        # 舰船列表尚未就绪时允许重新打开后重载；模型加载状态复位
        self._loading_ships = False
        self._loading = False
        # 停止转圈并隐藏加载覆盖层（窗口仍在，控件可安全访问）
        self._set_loading_overlay(False)
        self._save_geometry()
        self.viewport.clear_scene()
        self._current_geom = None
        self._armor_scene = None
        self._plate_items = {}
        super().closeEvent(event)

    def _save_geometry(self):
        try:
            self._settings.setValue("geom_win_geometry", self.saveGeometry())
        except Exception:  # noqa: BLE001
            pass

    def _restore_geometry(self) -> bool:
        try:
            geo = self._settings.value("geom_win_geometry")
            if geo:
                self.restoreGeometry(geo)
                return True
        except Exception:  # noqa: BLE001
            pass
        return False
