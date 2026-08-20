"""
geometry_viewer.py —— 3D 模型查看器（独立顶层窗口）。

复刻穿深计算器的集成模式：独立 QDialog + 懒创建单实例 + 后台线程加载 +
bus.log_message + theme.bind。含装甲厚度图例与显示开关。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSettings, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QCompleter,
    QPushButton, QCheckBox, QWidget, QProgressBar, QFrame, QScrollArea,
)

from app.signals import bus
from utils.theme import theme
from utils.threading_utils import run_async
from models.collision_materials import (
    ARMOR_COLOR_SCALE, ARMOR_COLOR_NAMES,
    ARMOR_TYPE_ORDER, ARMOR_TYPE_NAMES, armor_type_display,
)


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
        self.setFixedWidth(150)
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
            label = f"{low}–{high}" if high >= 1000 else f"{low}–{high}"
            name = ARMOR_COLOR_NAMES[i] if i < len(ARMOR_COLOR_NAMES) else ""
            p.drawText(20, int(y + row_h * 0.62), f"{name}  {label}mm")
            prev_max = bp
        p.end()


class GeometryViewerDialog(QDialog):
    """舰船 3D 模型 / 装甲查看器。"""

    #: 记录加载状态供外部查询
    ship_loaded = Signal(str)

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
        self._restored_geometry = self._restore_geometry()

        self._build_ui()
        theme.bind(self, "QDialog { background: @panel_bg@; }")
        bus.log_message.connect(self._on_log)

        # 舰船列表后台加载
        run_async(self._load_ships_task, on_finished=self._on_ships_loaded,
                  on_error=self._on_ships_error)

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
        panel.setFixedWidth(300)
        theme.bind(panel, "QWidget { background: @panel_bg@; }")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)

        title = QLabel("3D 模型查看器")
        theme.bind(title, "font-size:15px; font-weight:bold; color:@text@; background:transparent; border:none;")
        pl.addWidget(title)

        # 舰船选择
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
        pl.addLayout(ship_row)

        self.ship_status = QLabel("正在加载舰船列表...")
        theme.bind(self.ship_status, "color:@text_muted@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(self.ship_status)

        # 进度
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(16)
        theme.bind(self.progress, "QProgressBar { border:1px solid #0078d4; border-radius:4px; background:@input_bg@; text-align:center; color:@text@; }"
                    "QProgressBar::chunk { background:#0078d4; }")
        pl.addWidget(self.progress)

        # 显示开关
        cb_style = "QCheckBox { color:@text@; font-size:12px; spacing:6px; }"
        self.cb_hull = QCheckBox("显示船体")
        self.cb_hull.setChecked(True)
        self.cb_armor = QCheckBox("显示装甲（厚度着色）")
        # 默认关闭装甲叠加：先显示干净的贴图船体，避免彩色装甲盖住模型被误认为"贴图错乱"
        self.cb_armor.setChecked(False)
        self.cb_wire = QCheckBox("线框叠加")
        self.cb_wire.setChecked(False)
        theme.bind(self.cb_hull, cb_style)
        theme.bind(self.cb_armor, cb_style)
        theme.bind(self.cb_wire, cb_style)
        pl.addWidget(self.cb_hull)
        pl.addWidget(self.cb_armor)
        pl.addWidget(self.cb_wire)

        # ── 装甲类型筛选（归属，反编译自游戏 ArmorConstants） ──
        self._armor_checks: list[QCheckBox] = []
        self._armor_type_checks: dict[str, QCheckBox] = {}

        sec_style = "color:@text_muted@; font-size:11px; font-weight:bold; background:transparent; border:none; padding-top:4px;"
        self._add_armor_filter_title(pl, "装甲筛选", sec_style)
        grid2 = QGridLayout()
        grid2.setSpacing(2)
        for i, atype in enumerate(ARMOR_TYPE_ORDER):
            cb = QCheckBox(armor_type_display(atype))
            cb.setChecked(True)
            theme.bind(cb, cb_style)
            self._armor_type_checks[atype] = cb
            self._armor_checks.append(cb)
            grid2.addWidget(cb, i // 2, i % 2)
        pl.addLayout(grid2)
        for cb in self._armor_checks:
            cb.toggled.connect(self._on_armor_filter_changed)

        # 统计
        self.stats_label = QLabel("未加载")
        self.stats_label.setWordWrap(True)
        self.stats_label.setAlignment(Qt.AlignTop)
        theme.bind(self.stats_label, "color:@text_muted@; font-size:11px; background:transparent; border:none;")
        pl.addWidget(self.stats_label)

        # 装甲图例
        legend_title = QLabel("装甲厚度图例")
        theme.bind(legend_title, "color:@text@; font-size:12px; font-weight:bold; background:transparent; border:none;")
        pl.addWidget(legend_title)
        legend_scroll = QScrollArea()
        legend_scroll.setWidgetResizable(True)
        legend_scroll.setFrameShape(QFrame.NoFrame)
        legend_scroll.setWidget(_ArmorLegend())
        pl.addWidget(legend_scroll, stretch=1)

        # 操作提示
        hint = QLabel("左键拖拽：旋转\n滚轮：缩放\n右键拖拽：平移\n回车：加载选中舰船")
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

    def _add_armor_filter_title(self, layout, text, style):
        t = QLabel(text)
        theme.bind(t, style)
        layout.addWidget(t)

    def _on_hull_toggled(self, v: bool):
        """显示船体/装甲互斥：勾选船体时取消装甲（触发 _on_armor_toggled）。"""
        if v:
            self.cb_armor.setChecked(False)
        self.viewport.set_view_options(show_hull=v)
        self._refresh_armor_filter_state()

    def _on_armor_toggled(self, v: bool):
        """装甲显示开关：启用时取消船体，关闭时恢复船体（互斥）。"""
        if v:
            self.cb_hull.setChecked(False)
        else:
            self.cb_hull.setChecked(True)
        self.viewport.set_view_options(show_armor=v)
        self._refresh_armor_filter_state()

    def _refresh_armor_filter_state(self):
        """装甲未启用时禁用筛选复选框；启用时按当前勾选过滤。"""
        on = self.cb_armor.isChecked()
        for cb in self._armor_checks:
            cb.setEnabled(on)
        if on:
            self._on_armor_filter_changed()
        else:
            self.viewport.set_view_options(armor_types=None)

    def _update_armor_filters(self, geom):
        """按舰船实际拥有的装甲类型启用筛选复选框（不拥有的禁用）。"""
        from models.collision_materials import get_armor_types
        atypes: set = set()
        for a in geom.armor_meshes:
            for t in a.triangles:
                atypes |= get_armor_types(t.material_name)
        for key, cb in self._armor_type_checks.items():
            cb.setEnabled(True)
            cb.setChecked(key in atypes)
            cb.setEnabled(key in atypes)
        self._refresh_armor_filter_state()

    def _on_armor_filter_changed(self):
        """装甲类型筛选变化 → 通知视口（仅过滤装甲 pass）。"""
        atypes = {k for k, cb in self._armor_type_checks.items()
                  if cb.isChecked() and cb.isEnabled()}
        self.viewport.set_view_options(armor_types=atypes or None)

    # ── 舰船列表 ─────────────────────────────────────────

    def _get_service(self):
        if self._service is None:
            from services.geometry_service import GeometryService
            self._service = GeometryService.instance()
        return self._service

    def _load_ships_task(self):
        return self._get_service().list_ships()

    def _on_ships_loaded(self, ships):
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

    def _on_ships_error(self, err):
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
        self._loading = True
        self.btn_load.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.stats_label.setText(f"正在加载 {ship.display_name}...")
        self._set_loading_overlay(True, f"正在加载 {ship.display_name}...")

        def _work():
            geom = self._get_service().load_ship(
                ship,
                progress_cb=lambda p, m: self._on_progress(p, m),
            )
            return geom

        run_async(_work, on_finished=self._on_ship_loaded, on_error=self._on_ship_error)

    def _on_progress(self, pct, msg):
        # 后台线程 → 主线程（queued signal）
        bus.log_message.emit(f"🔧 3D: {msg} ({pct:.0f}%)")

    def _on_ship_loaded(self, geom):
        self._loading = False
        self.btn_load.setEnabled(True)
        self.progress.setVisible(False)
        self._set_loading_overlay(False)
        self._current_geom = geom
        # 船体/装甲互斥：装甲开启时取消船体勾选（保持 UI 与渲染一致）
        if self.cb_armor.isChecked() and self.cb_hull.isChecked():
            self.cb_hull.setChecked(False)
        self.viewport.set_scene(geom, show_hull=self.cb_hull.isChecked(),
                                show_armor=self.cb_armor.isChecked())
        # 按舰船实际拥有的装甲归属/类型更新筛选
        self._update_armor_filters(geom)
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
        self.stats_label.setText(
            f"舰船：{geom.display_name}（{geom.game_key}）\n"
            f"模型：{geom.model_folder}\n"
            f"船体：{total_v:,} 顶点 / {total_t:,} 三角形\n"
            f"挂载：{mounts_n} 个（HP {hp_n} + 甲板设备 {deck_n} + 部件子设备 {sub_n}，{mounts_v:,} 顶点）\n"
            f"装甲：{armor_t:,} 三角形（厚度已知 {known_t:,}）\n"
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

    def _on_ship_error(self, err):
        self._loading = False
        self.btn_load.setEnabled(True)
        self.progress.setVisible(False)
        self._set_loading_overlay(False)
        self.stats_label.setText(f"加载失败: {err}")
        bus.log_message.emit(f"❌ 3D 加载失败: {err}")

    # ── 生命周期 ─────────────────────────────────────────

    def _on_log(self, msg: str):
        # 后台线程进度消息走日志面板，这里无需额外处理
        pass

    def center_on_screen(self, relative_to=None):
        from PySide6.QtGui import QGuiApplication
        if relative_to is not None and relative_to.isVisible():
            geo = relative_to.frameGeometry()
            self.move(max(geo.x() + (geo.width() - self.width()) // 2, 0),
                      max(geo.y() + (geo.height() - self.height()) // 2, 0))
            return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - self.width()) // 2,
                      geo.y() + (geo.height() - self.height()) // 2)

    def closeEvent(self, event):
        self._save_geometry()
        self.viewport.clear_scene()
        self._current_geom = None
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
