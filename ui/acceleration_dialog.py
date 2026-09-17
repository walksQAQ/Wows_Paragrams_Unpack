"""AccelerationDialog —— 舰船加速曲线查看器（独立弹窗）。

数据：``ship_module_engine`` / ``ship_module_hulls``（当前服务器数据库）
模型：``services/acceleration_service``（公式与参数的口径见
      ``docs/korabli-ship-acceleration-reverse.md``）

展示内容：
  · v(t) 加速曲线（可叠加可选开关：引擎增压 / 进水 / 引擎受损 的点划线）
  · 弹射区间（弹射起步区间上限）与功率倍率；标准档（2.5 节 ×2.5，全舰共通）
    只标一个「标准」，不单独开栏
  · 关键时间点：到弹射速度（自带大区间时）/ 到 90% 极速（标准档时）
  · 模型参数：引擎功率基准 P、阻力系数 k、推重比、全功率加速时间

注：「无弹射」对照曲线整条机制已于 2026-09-18 删除（避免启用引擎增压时
    冒出一个看起来无关的开关）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPolygonF, QFontMetrics
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QSizePolicy, QGridLayout, QCheckBox, QTabWidget,
)

from services.database_service import get_db
from services import acceleration_service as accel
from utils.path_utils import is_debug_build
from utils.theme import theme

#: 仅调试模式（源码启动）显示的指标：模型内部量，普通使用无需知道
DEBUG_METRIC_KEYS: tuple[str, ...] = ("power", "drag", "forsage")

#: 指标定义：(key, 短标题, 说明-tooltip)。
#: 标题刻意保持短，详细口径放 tooltip —— 否则列宽被长标题撞到挤在一起。
SHARED_METRIC_DEFS: tuple[tuple[str, str, str], ...] = (
    ("engine_power", "引擎马力", "模型输入：引擎模块的马力（HP）"),
    ("tonnage", "排水量", "模型输入：船体模块的排水量（吨）"),
    ("hp_per_ton", "推重比", "引擎马力 / 排水量，越大起步越快"),
    ("vmax", "最大航速", "当前最大航速（船体基础航速，含 speedCoef 与升级品）"),
    ("power", "功率基准 P", "内部量（调试）：功率基准 P"),
    ("drag", "阻力系数 k", "内部量（调试）：阻力系数 k = P/vmax²"),
)

#: 每个方向（前进/后退）各自的指标；后退用 ``bwd_`` 前缀的 key。
DIR_METRIC_DEFS: tuple[tuple[str, str, str], ...] = (
    ("zone", "弹射区间", "弹射起步区间上限：低于此航速且正在加速时，推力乘弹射倍率"
                        "（标准档 2.5 节；部分船自带更大区间）"),
    ("forsage", "弹射倍率", "弹射区间内的推力倍率（游戏数据）"),
    ("up_time", "全功率时间", "游戏数据里的「达到引擎全功率所需时间」"
                             "（= 引擎爬到最高出力的时间）"),
    ("tkey", "到弹射速度", "自带大弹射区间时：从静止到区间上限的时间（弹射段终点）；"
                          "标准档（2.5 节）没有意义，此时改显示到 90% 极速的时间"),
)

#: 标题会随船切换的指标（给动态标题预留列宽）
ALT_CAPTIONS: dict[str, tuple[str, ...]] = {"tkey": ("90% 极速", "到极速")}

#: 后退页的 key 前缀
BWD_PREFIX = "bwd_"


def _eq_speed(m: dict | None) -> float:
    """该模型实际能达到的稳定航速（节）：min(极速, 阻力参考航速)。

    正常（未受损）模型的阻力参考航速高于极速 ⇒ 取极速；引擎受损后出力上限下降，
    平衡航速降到 ``drag_ref`` 以下 ⇒ 取 ``drag_ref``。
    """
    if not m:
        return 0.0
    try:
        return min(float(m.get("max_speed") or 0.0), float(m.get("drag_ref") or 1e9))
    except (TypeError, ValueError):
        return 0.0


class AccelerationDialog(QDialog):
    """加速曲线弹窗（懒创建单实例）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("加速曲线")
        self.resize(820, 620)
        self._ship_id = ""
        self._model: dict | None = None
        #: 基准方案（主界面选中配置：升级品/旗/技能），**不含**引擎增压
        self._base_model: dict | None = None
        #: 增压方案（该舰有加力消耗品时才有）：弹射区间/倍率按增压数据**覆盖**，极速按 boostCoeff 抬高
        self._boost_model: dict | None = None
        self._boost_info: dict | None = None
        #: 引擎受损参数（出力/满功率时间乘数），无数据时为 None
        self._damage_info: dict | None = None
        #: 进水的最大航速惩罚系数（如 -0.3）
        self._flood_coef: float | None = None
        #: 「背水一战」技能参数（引擎瘫痪后保留比例），无数据时为 None
        self._keep_info: dict | None = None
        #: 当前显示的是否为增压方案
        self._active_boost = False
        self._ship_name = ""
        #: 取数上下文（presenter 构建引擎卡片时用的那条引擎/船体记录）
        self._accel_ctx: dict = {}
        self._canvas = None
        self._build_ui()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        theme.bind(self, """
            QDialog { background: @window_bg@; color: @text@; }
            QLabel { color: @text@; font-size: 12px; }
            QPushButton {
                background: @input_bg@; color: @text@;
                border: 1px solid @border@; border-radius: 3px;
                padding: 4px 14px; min-height: 26px;
            }
            QPushButton:hover { background: @hover_bg@; border-color: @selected_bg@; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        bar = QHBoxLayout()
        self.title_lbl = QLabel("未选择舰船")
        self.title_lbl.setStyleSheet(theme.qss("font-size: 13px; font-weight: bold; color: @text@;"))
        bar.addWidget(self.title_lbl)
        bar.addStretch(1)
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.close)
        bar.addWidget(self.close_btn)
        root.addLayout(bar)

        # ── 公共指标（模型输入）：引擎马力 / 排水量 / 推重比 / 最大航速 ──
        # P / k 属调试信息，非 debug 模式不显示。
        # 每个指标一格：「短标题 + 数值」同行，标题定宽对齐，列数随窗口宽度自适应。
        self._metric_labels: dict[str, QLabel] = {}
        self._metric_caps: dict[str, QLabel] = {}
        self._metric_tips: dict[str, str] = {}
        self._metric_grids: list[tuple[QGridLayout, list[QWidget], int]] = []
        self._cap_w = 0
        self.metrics = self._make_metric_grid(SHARED_METRIC_DEFS, "")
        root.addLayout(self.metrics)

        # ── 前进 / 后退 分两页（各自一条曲线 + 自己的指标）──
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        theme.bind(self.tabs, """
            QTabWidget::pane { border: 1px solid @border@; border-radius: 4px;
                               background: @window_bg@; }
            QTabBar::tab { background: @input_bg@; color: @text_muted@;
                           border: 1px solid @border@; border-bottom: none;
                           padding: 4px 18px; margin-right: 2px;
                           border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background: @window_bg@; color: @text@;
                                    border-bottom: 2px solid @selected_bg@; }
        """)
        self._pages: dict[str, dict] = {}
        for key, title in (("fwd", "前进"), ("bwd", "后退")):
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(10, 10, 10, 10)
            pv.setSpacing(8)
            prefix = "" if key == "fwd" else BWD_PREFIX
            grid = self._make_metric_grid(DIR_METRIC_DEFS, prefix)
            pv.addLayout(grid)
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            pv.addLayout(box, 1)
            tip = QLabel("")
            tip.setWordWrap(True)
            tip.setStyleSheet(theme.qss("font-size: 11px; color: @text_muted@;"))
            tip.setVisible(False)
            pv.addWidget(tip)
            self.tabs.addTab(page, title)
            self._pages[key] = {"grid": grid, "box": box, "tip": tip, "canvas": None}
        # 首次布局：resizeEvent 不一定在构建后触发，这里显式排一次
        self._relayout_metrics()
        root.addWidget(self.tabs, 1)
        #: 主画布 = 前进页（保持旧属性名，便于既有工具/脚本取用）
        self.chart_box = self._pages["fwd"]["box"]

        # 引擎增压：**该舰装有加力消耗品时**才出现；默认启用（跟随“有就能用”的实战口径）
        self.cb_boost = QCheckBox("启用引擎增压")
        self.cb_boost.setChecked(True)
        self.cb_boost.setVisible(False)
        theme.bind(self.cb_boost, "QCheckBox { color: @text_muted@; font-size: 11px; }")
        self.cb_boost.toggled.connect(self._on_boost_toggled)
        # 降速状态：进水 / 引擎受损（瘫痪）。两者机制不同（降极速 vs 降出力），分开画。
        # 开关文字用与图上曲线一致的颜色，一眼能对上哪条线是哪个
        self.cb_flood = QCheckBox("进水")
        self.cb_flood.setChecked(False)
        self.cb_flood.setVisible(False)
        theme.bind(self.cb_flood,
                   f"QCheckBox {{ color: {AccelCurveCanvas.C_FLOOD}; font-size: 11px; }}")
        self.cb_flood.toggled.connect(self._on_boost_toggled)
        self.cb_damaged = QCheckBox("引擎受损")
        self.cb_damaged.setChecked(False)
        self.cb_damaged.setVisible(False)
        theme.bind(self.cb_damaged,
                   f"QCheckBox {{ color: {AccelCurveCanvas.C_DAMAGE}; font-size: 11px; }}")
        self.cb_damaged.toggled.connect(self._on_boost_toggled)
        # 背水一战（舰长技能）：引擎/舵机**瘫痪**后保留部分航速；只有该舰有受损参数时才出现
        self.cb_laststand = QCheckBox("背水一战")
        self.cb_laststand.setChecked(False)
        self.cb_laststand.setVisible(False)
        theme.bind(self.cb_laststand,
                   f"QCheckBox {{ color: {AccelCurveCanvas.C_KEEP}; font-size: 11px; }}")
        self.cb_laststand.toggled.connect(self._on_boost_toggled)
        _bottom = QHBoxLayout()
        _bottom.setContentsMargins(0, 0, 0, 0)
        _bottom.setSpacing(10)
        _ov_lbl = QLabel("叠加曲线：")
        theme.bind(_ov_lbl, "color: @text_hint@; font-size: 11px;")
        _bottom.addWidget(_ov_lbl)
        _bottom.addWidget(self.cb_boost)
        _bottom.addWidget(self.cb_flood)
        _bottom.addWidget(self.cb_damaged)
        _bottom.addWidget(self.cb_laststand)
        _bottom.addStretch(1)
        self.chart_hint = QLabel("鼠标悬停查看读数")
        self.chart_hint.setToolTip("鼠标在图上移动：显示该时刻的航速（竖虚线 + 读数框），移出清除。")
        theme.bind(self.chart_hint, "color: @text_hint@; font-size: 11px;")
        _bottom.addWidget(self.chart_hint)
        _bottom.addStretch(1)
        root.addLayout(_bottom)

        # 提示行：仅用于「无数据 / 读取失败」等异常说明（正常载入后为空且隐藏）
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(theme.qss("font-size: 11px; color: @text_muted@;"))
        self.hint.setVisible(False)
        root.addWidget(self.hint)

    # ── 指标格构建 / 自适应重排 ────────────────────────────

    def _make_metric_grid(self, defs, prefix: str) -> QGridLayout:
        """把一组指标定义建成网格（标题定宽 + 数值同行，列数随宽度自适应）。"""
        grid = QGridLayout()
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(9)
        cells: list[QWidget] = []
        specs = [(prefix + k, c, t) for k, c, t in defs]
        if not is_debug_build():
            specs = [s for s in specs
                     if s[0].replace(BWD_PREFIX, "") not in DEBUG_METRIC_KEYS]
        if not specs:
            self._metric_grids.append((grid, cells, 0))
            return grid
        fm = QFontMetrics(self.font())
        _caps = [c for _k, c, _t in specs]
        for _k, _c, _t in specs:
            _caps.extend(ALT_CAPTIONS.get(_k, ()))
        need = max(fm.horizontalAdvance(c) for c in _caps) + 8
        self._cap_w = max(self._cap_w, need)
        for key, label, tip in specs:
            box = QWidget()
            hl = QHBoxLayout(box)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(8)
            cap = QLabel(label)
            cap.setStyleSheet(theme.qss("font-size: 11px; color: @text_muted@;"))
            cap.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cap.setToolTip(tip)
            val = QLabel("—")
            val.setStyleSheet(theme.qss("font-size: 13px; font-weight: bold; color: @text@;"))
            val.setToolTip(tip)
            val.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            hl.addWidget(cap)
            hl.addWidget(val)
            hl.addStretch(1)
            cells.append(box)
            self._metric_labels[key] = val
            self._metric_caps[key] = cap
            self._metric_tips[key] = tip
        self._metric_grids.append((grid, cells, 0))
        return grid

    def _relayout_metrics(self) -> None:
        """按当前宽度重排所有指标格（每格约需 210px，列数 2~4）。"""
        if self._cap_w:
            for cap in self._metric_caps.values():
                cap.setFixedWidth(self._cap_w)
        avail = max(320, self.width() - 46)
        cols_want = 4 if avail >= 760 else (3 if avail >= 540 else 2)
        for i, (grid, cells, cur) in enumerate(self._metric_grids):
            if not cells:
                continue
            cols = min(cols_want, len(cells))
            if cols == cur and grid.count() == len(cells):
                continue
            while grid.count():
                grid.takeAt(0)
            for j, cell in enumerate(cells):
                grid.addWidget(cell, j // cols, j % cols)
            for c in range(8):
                grid.setColumnStretch(c, 1 if c < cols else 0)
            self._metric_grids[i] = (grid, cells, cols)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if getattr(self, "_metric_grids", None):
            self._relayout_metrics()

    def _set_hint(self, text: str) -> None:
        """设置底部提示行文本；空文本时隐藏该行。"""
        self.hint.setText(text or "")
        self.hint.setVisible(bool(text))

    def _set_metric(self, key: str, text: str) -> None:
        """更新指标值（非 debug 模式下被裁掉的指标→静默跳过）。"""
        lbl = self._metric_labels.get(key)
        if lbl is not None:
            lbl.setText(text)

    def _set_metric_cap(self, key: str, text: str) -> None:
        """更新指标标题（个别指标标题随舰船切换，如「到弹射速度 / 90% 极速」）。"""
        cap = self._metric_caps.get(key)
        if cap is not None and cap.text() != text:
            cap.setText(text)

    def _set_metric_tip(self, key: str, text: str) -> None:
        """追加指标说明（取数来源等）。标题保持短标题不变 —— 保证列对齐。"""
        base = self._metric_tips.get(key, "")
        full = (base + "\n" + text) if text else base
        for w in (self._metric_caps.get(key), self._metric_labels.get(key)):
            if w is not None:
                w.setToolTip(full)

    # ── 数据 ──────────────────────────────────────────────

    def _resolve_ship_name(self, ship_id: str) -> str:
        if not ship_id:
            return ship_id
        try:
            db = get_db()
            row = db._conn.execute(
                "SELECT nm.lang_zh AS lang_zh, b.ship_index AS ship_index FROM ship_basic_info b "
                "LEFT JOIN name_mappings nm ON nm.id = b.name_mapping_id "
                "WHERE b.ship_id=? LIMIT 1", (ship_id,)).fetchone()
            if row and row["lang_zh"]:
                return row["lang_zh"]
            if row and row["ship_index"]:
                r2 = db._conn.execute(
                    "SELECT lang_zh FROM name_mappings WHERE category='ship' AND key_name=? LIMIT 1",
                    (str(row["ship_index"]).upper(),)).fetchone()
                if r2 and r2["lang_zh"]:
                    return r2["lang_zh"]
        except Exception:  # noqa: BLE001
            pass
        return ship_id

    def _load_rows(self, ship_id: str):
        """回退路径：自行查库取 (engine_row, hull_row)；任一缺失返回 (None, None)。

        ⚠️ 仅在未传入 ``accel_ctx`` 时使用：这里只能按 ``ORDER BY module_key LIMIT 1``
        选行，一船多套配置（如 北卡1945 有 A/AB 两套引擎）时可能选到**与卡片不同**的
        模块 → P/航速对不上。正常路径由详情面板把 presenter 用到的行连同模型一起传进来。
        """
        db = get_db()
        vc = db.get_latest_version_code()
        eng = db._conn.execute(
            "SELECT * FROM ship_module_engine WHERE version_code=? AND ship_id=? "
            "ORDER BY module_key LIMIT 1", (vc, ship_id)).fetchone()
        hull = None
        if eng is not None:
            hull = db._conn.execute(
                "SELECT max_speed, tonnage FROM ship_module_hulls WHERE version_code=? AND ship_id=? "
                "ORDER BY module_key LIMIT 1", (vc, ship_id)).fetchone()
            if hull is None:
                hull = db._conn.execute(
                    "SELECT max_speed, tonnage FROM ship_module_hulls WHERE ship_id=? "
                    "ORDER BY module_key LIMIT 1", (ship_id,)).fetchone()
        return eng, hull

    def _load_keep_info(self) -> dict | None:
        """读「背水一战」技能参数（按版本缓存，两服同值）。"""
        try:
            from services.engine_damage_service import load_keep_skill
            db = get_db()
            return load_keep_skill(db._conn, db.get_latest_version_code() or "")
        except Exception:  # noqa: BLE001
            return None

    def open_for(self, ship_id: str, accel_ctx: dict | None = None) -> None:
        """载入指定舰船的提速模型并刷新图表。

        Args:
            ship_id: 舰船 ID
            accel_ctx: 详情面板传入的取数上下文
                （``{"model", "engine_key", "engine_power", "hull_key", ...}``）。
                传了就**直接用其中的模型**，保证与引擎卡片逐项一致；为空时回退到
                自行查库（选行口径可能与卡片不同，仅作兼底）。
        """
        if not ship_id:
            self._set_hint("未选择舰船")
            return
        self._ship_id = ship_id
        self._accel_ctx = accel_ctx or {}
        name = self._resolve_ship_name(ship_id)
        self._ship_name = name

        # ── 正常路径：复用卡片（presenter）已经算好的模型 ──
        model = self._accel_ctx.get("model")
        if model:
            model = dict(model)
            model["backward"] = self._accel_ctx.get("backward_model")
            self._base_model = model
            self._boost_model = self._accel_ctx.get("boost_model")
            self._boost_info = self._accel_ctx.get("boost")
            self._damage_info = self._accel_ctx.get("damage_info")
            self._flood_coef = self._accel_ctx.get("flood_coef")
            self._keep_info = self._accel_ctx.get("keep_info") or self._load_keep_info()
            self._sync_boost_ui()
            self.title_lbl.setText(f"{name}（{ship_id}）")
            self.title_lbl.setToolTip(self._source_tooltip())
            self._apply_active_model()
            self._set_hint("")
            return

        # ── 回退路径：自行查库 ──
        try:
            eng, hull = self._load_rows(ship_id)
        except Exception as exc:  # noqa: BLE001
            self.title_lbl.setText(f"{name} · 读取失败")
            self._set_hint(f"读取数据库失败：{exc}（请先执行「加载数据」）")
            return
        if eng is None:
            self.title_lbl.setText(f"{name} · 无引擎数据")
            self._set_hint("该舰船在数据库中缺少引擎记录。")
            return
        max_speed = hull["max_speed"] if hull is not None else None
        tonnage = hull["tonnage"] if hull is not None else None
        sc = eng["speed_coef"] if "speed_coef" in eng.keys() else 0
        try:
            from services.engine_boost_service import load as _load_boost
            boost = _load_boost(get_db()._conn, ship_id)
        except Exception:  # noqa: BLE001
            boost = None
        try:
            from services.engine_damage_service import load as _load_dmg
            self._damage_info = _load_dmg(get_db()._conn, ship_id)
        except Exception:  # noqa: BLE001
            self._damage_info = None
        try:
            self._flood_coef = eng["forward_speed_on_flood"]
        except Exception:  # noqa: BLE001
            self._flood_coef = None
        self._keep_info = self._load_keep_info()
        model = accel.build_model(eng, max_speed or 0, tonnage,
                                  speed_coef=accel.clamp_speed_coef(sc))
        self._base_model = model
        self._boost_model = None
        self._boost_info = boost
        bcoef = accel.clamp_speed_coef(sc, (boost or {}).get("boost_coeff") or 0.0)
        if model and boost and (boost.get("forward_zone") or boost.get("forward_forsag")):
            bm = accel.build_model(eng, max_speed or 0, tonnage, speed_coef=bcoef,
                                   forsage_power=boost.get("forward_forsag"),
                                   forsage_zone=boost.get("forward_zone"))
            if bm:
                b_bwd = accel.backward_model(eng, bm["power"], speed_coef=bcoef,
                                             forsage_power=boost.get("backward_forsag"),
                                             forsage_zone=boost.get("backward_zone"))
                if b_bwd:
                    bm["backward"] = b_bwd
                self._boost_model = bm
        self._sync_boost_ui()
        self.title_lbl.setText(f"{name}（{ship_id}）")
        if not model:
            self._set_hint("数据不足（缺排水量或最大航速），无法构建提速模型。")
            for lbl in self._metric_labels.values():
                lbl.setText("—")
            self._clear_chart()
            return
        self._apply_active_model()
        # 模型公式与推导见 docs/korabli-ship-acceleration-reverse.md（不在界面显示）
        self._set_hint("")

    # ── 增压方案 ──────────────────────────────────────

    def _sync_boost_ui(self) -> None:
        """按“该舰是否有加力消耗品”显示/隐藏增压开关（有则默认启用）。"""
        info = self._boost_info or {}
        has = bool(self._boost_model)
        self.cb_boost.setVisible(has)
        if has:
            bits = []
            z, f = info.get("forward_zone"), info.get("forward_forsag")
            if z and f:
                bits.append(f"弹射区间 {float(z):.0f} 节 ×{float(f):g}（覆盖升级品）")
            bc = info.get("boost_coeff")
            if bc:
                bits.append(f"极速 +{float(bc) * 100:.0f}%")
            if info.get("consumable_id"):
                bits.append(str(info["consumable_id"]))
            self.cb_boost.setToolTip("按该舰的加力消耗品参数计算：" + " · ".join(bits)
                                     + "\n取消勾选则按不带加力的基准配置显示。")
        # 降速状态开关：只有该舰有对应数据时才出现（默认不勾，避免一打开就多两条线）
        dinfo = self._damage_info or {}
        has_dmg = (dinfo.get("power_multiplier") is not None
                   or dinfo.get("time_multiplier") is not None)
        self.cb_damaged.setVisible(has_dmg)
        if has_dmg and self._base_model:
            k = 1.0 + float(dinfo.get("power_multiplier") or 0.0)
            um = float(dinfo.get("time_multiplier") or 1.0)
            dm = accel.debuffed_model(self._base_model, thrust_mult=k, up_time_mult=um,
                                      label="引擎受损")
            tip = (f"引擎受损/瘫痪：出力 ×{k:.2f}、满功率时间 ×{um:g}"
                   + (f"，受损后极速 ≈ {_eq_speed(dm):.1f} 节" if dm else ""))
            if dinfo.get("source") == "default":
                tip += "\n（本舰无受损参数记录，按全库缺省值 -0.6 / 5.5 计算）"
            self.cb_damaged.setToolTip(tip)
        has_flood = bool(self._flood_coef)
        self.cb_flood.setVisible(has_flood)
        if has_flood and self._base_model:
            fm = accel.debuff_flood(self._base_model, self._flood_coef)
            self.cb_flood.setToolTip(
                f"进水：最大航速 ×{1 + float(self._flood_coef):.2f}"
                f"（{float(self._flood_coef) * 100:.0f}%）"
                + (f" ⇒ 进水极速 ≈ {_eq_speed(fm):.1f} 节" if fm else ""))
        # 背水一战：引擎/舵机**瘫痪**后保留部分航速（需该舰有受损参数配套时间倍数）
        kinfo = self._keep_info or {}
        has_keep = bool(kinfo.get("keep")) and bool(self._damage_info)
        self.cb_laststand.setVisible(has_keep)
        if has_keep and self._base_model:
            km = self._keep_model(self._base_model)
            _k = float(kinfo["keep"])
            _loss = float(kinfo.get("loss") if kinfo.get("loss") is not None else 1.0 - _k)
            _um = float((self._damage_info or {}).get("time_multiplier") or 1.0)
            _eq = _eq_speed(km) if km else 0.0
            _vmax0 = float(self._base_model["max_speed"])
            self.cb_laststand.setToolTip(
                (kinfo.get("desc") or "在引擎和操舵装置瘫痪后，战舰还能保持部分航速和机动性。")
                + f"\n保留引擎出力 ×{_k:.4f}（惩罚幅度减少 {_k * 100:.2f}%："
                  f"原本瘫痪损失 100% 出力，点后只损失 {_loss * 100:.2f}% = damagedEngineCoeff）"
                  f"、满功率时间 ×{_um:g}"
                + (f"\n出力仍高于水阻 ⇒ 极速基本不变（≈{_eq:.1f} 节），只是加速明显变慢"
                   if _eq >= _vmax0 - 0.05 else f"\n⇒ 瘫痪后极速 ≈ {_eq:.1f} 节" if km else "")
                + "\n不点该技能时，引擎瘫痪 = 完全没有推进力（画布上画不出来，故只画技能生效的那条）。")

    def _keep_model(self, model: dict) -> dict | None:
        """引擎瘫痪 + 「背水一战」的模型（用于开关 tooltip 与曲线）。"""
        kinfo = self._keep_info or {}
        keep = float(kinfo.get("keep") or 0.0)
        if not keep:
            return None
        um = float((self._damage_info or {}).get("time_multiplier") or 1.0)
        return accel.debuff_engine_disabled(model, keep, up_time_mult=um)

    def _on_boost_toggled(self, _checked: bool) -> None:
        self._apply_active_model()

    def _apply_active_model(self) -> None:
        """按增压开关选择当前方案并刷新指标/图表。"""
        if not self._base_model:
            return
        use_boost = bool(self._boost_model) and self.cb_boost.isChecked()
        self._model = self._boost_model if use_boost else self._base_model
        self._active_boost = use_boost
        self._update_metrics(self._model)
        self._build_chart(self._model, self._ship_name)

    def _debuff_models(self, model: dict) -> list[tuple[str, str, dict]]:
        """当前勾选的降速状态模型：[（图例文本, 颜色, 模型）]。

        三者机制不同（与实测/数据口径一致），因此分开建模型、分开画：
          · **引擎受损**：``damagedEnginePowerMultiplier``（-0.6 ⇒ 出力 ×0.4）
            × ``damagedEnginePowerTimeMultiplier``（满功率时间 ×5.5/6.5/7.0）
          · **引擎瘫痪 + 背水一战**：``damagedEngineCoeff``（0.2167 ⇒ 只保留 21.7% 航速）
          · **进水**：``forwardSpeedOnFlood``（-0.3 ⇒ 极速 ×0.7）
        """
        out: list[tuple[str, str, dict]] = []
        kinfo = self._keep_info or {}
        if self.cb_laststand.isChecked() and kinfo.get("keep") and self._damage_info:
            km = self._keep_model(model)
            if km:
                _nm = kinfo.get("name") or "背水一战"
                # 标签跟着口径走：出力口径说“出力 ×k”，航速口径说“极速 X 节”
                if accel.ENGINE_DISABLED_MODE == "thrust":
                    _lbl = f"{_nm}（出力 ×{float(kinfo['keep']):.2f}）"
                else:
                    _lbl = f"{_nm}（极速 {_eq_speed(km):.1f} 节）"
                out.append((_lbl, AccelCurveCanvas.C_KEEP, km))
        info = self._damage_info or {}
        if self.cb_damaged.isChecked() and info:
            dm = accel.debuffed_model(
                model,
                thrust_mult=1.0 + float(info.get("power_multiplier") or 0.0),
                up_time_mult=float(info.get("time_multiplier") or 1.0),
                label="引擎受损")
            if dm:
                out.append((f"引擎受损（极速 {_eq_speed(dm):.1f} 节）",
                            AccelCurveCanvas.C_DAMAGE, dm))
        fc = self._flood_coef
        if self.cb_flood.isChecked() and fc:
            fm = accel.debuff_flood(model, fc)
            if fm:
                out.append((f"进水（极速 {_eq_speed(fm):.1f} 节）",
                            AccelCurveCanvas.C_FLOOD, fm))
        return out

    # ── 指标 / 图表 ───────────────────────────────────────

    def _source_tooltip(self) -> str:
        """取数来源说明（引擎/船体模块、马力、speedCoef、已生效的升级品），便于核对。"""
        c = self._accel_ctx or {}
        parts = []
        if c.get("engine_key"):
            parts.append(f"引擎模块 {c['engine_key']}"
                         + (f"（配置 {c['engine_config']}）" if c.get("engine_config") else ""))
        if c.get("engine_power"):
            parts.append(f"引擎马力 {c['engine_power']:.0f} HP")
        if c.get("speed_coef"):
            parts.append(f"speedCoef {c['speed_coef']:+.3f}")
        if c.get("hull_key"):
            parts.append(f"船体模块 {c['hull_key']}"
                         + (f"（配置 {c['hull_config']}）" if c.get("hull_config") else ""))
        _line = "加速曲线取数来源：" + " · ".join(parts) if parts else ""
        _mods = c.get("applied_mods") or {}
        if _mods:
            _txt = " · ".join(f"{k} ×{float(v):g}" for k, v in _mods.items())
            _line += ("\n" if _line else "") + f"已生效升级品修饰符：{_txt}"
        return _line

    def _update_metrics(self, model: dict) -> None:
        """填充公共指标 + 前进/后退两页的各自指标。"""
        self._metric_labels["engine_power"].setText(f"{model['engine_power']:,.0f} HP")
        self._metric_labels["tonnage"].setText(f"{model['tonnage']:,.0f} t")
        self._metric_labels["hp_per_ton"].setText(f"{model['hp_per_ton']:.2f}")
        self._metric_labels["vmax"].setText(f"{model['max_speed']:.2f} kn")
        self._set_metric("power", f"{model['power']:,.0f}")
        self._set_metric("drag", f"{model['drag']:.1f}")
        # 取数来源（引擎/船体模块）→ tooltip，不动标题（标题保持定宽对齐）
        _ek = (self._accel_ctx or {}).get("engine_key") or ""
        _hk = (self._accel_ctx or {}).get("hull_key") or ""
        _cfg = (self._accel_ctx or {}).get("engine_config") or ""
        if _ek:
            self._set_metric_tip("engine_power", f"取数来源：引擎模块 {_ek}"
                                                + (f"（配置 {_cfg}）" if _cfg else ""))
        if _hk or model.get("speed_coef"):
            _vt: list[str] = []
            if model.get("speed_coef"):
                _vt.append(f"基础航速 {float(model.get('base_speed') or 0):.2f} kn，"
                           f"航速加成 +{float(model['speed_coef']) * 100:.1f}%"
                           "（含信号旗/技能/升级品"
                           + ("、引擎增压" if self._active_boost else "") + "）")
            if self._active_boost and self._boost_info:
                _bi = self._boost_info
                _b = []
                if _bi.get("forward_zone") and _bi.get("forward_forsag"):
                    _b.append(f"弹射区间 {float(_bi['forward_zone']):.0f} 节 "
                              f"×{float(_bi['forward_forsag']):g}")
                if _bi.get("boost_coeff"):
                    _b.append(f"极速 +{float(_bi['boost_coeff']) * 100:.0f}%")
                if _b:
                    _vt.append("已按引擎加力计算：" + " · ".join(_b)
                               + "（弹射参数为**覆盖**，不与升级品叠加）")
            if _hk:
                _vt.append(f"取数来源：船体模块 {_hk}")
            self._set_metric_tip("vmax", "\n".join(_vt))
        _mods = (self._accel_ctx or {}).get("applied_mods") or {}
        if _mods:
            _txt = "已生效升级品修饰符：" + " · ".join(f"{k} ×{float(v):g}" for k, v in _mods.items())
            for k in ("zone", "forsage", "up_time", "bwd_zone", "bwd_forsage", "bwd_up_time"):
                self._set_metric_tip(k, _txt)

        self._fill_dir_metrics("", model,
                               tip="前进档：从静止满车起步（单次机动）。\n"
                                   "中途换挡会走引擎出力的归零/反向累积路径，曲线不再适用；"
                                   "弹射只在「加速方向与速度方向一致」时生效。")
        bmodel = model.get("backward") or None
        self._fill_dir_metrics(BWD_PREFIX, bmodel,
                               tip="后退档：从静止满车后退起步（单次机动）。") if bmodel else None
        if not bmodel:
            for k, _c, _t in DIR_METRIC_DEFS:
                self._set_metric(BWD_PREFIX + k, "—")

    def _fill_dir_metrics(self, prefix: str, m: dict, *, tip: str = "") -> None:
        """填一个方向（前进/后退）的指标：弹射区间 / 倍率 / 全功率时间 / 到弹射速度。"""
        if not m:
            return
        has_fs = float(m.get("forsage", 1.0)) > 1.001 and float(m.get("zone", 0.0)) > 0.0
        standard = has_fs and accel.is_standard_model(m)
        zone = f"{m['zone']:.1f} 节" if has_fs else "无"
        if has_fs and m["zone"] >= m["max_speed"]:
            # 区间上限超过最大航速：实际上全程生效（升级品把区间放大过头时会这样）
            zone = f"全程（{m['zone']:.1f} 节 ≥ {m['max_speed']:.1f}）"
        elif standard:
            # 标准档（全舰共通）：标成「标准」即可，不给它单开一栏
            zone = f"标准（{m['zone']:.1f} 节）"
        if not has_fs:
            fs = "无"
        else:
            fs = f"×{m['forsage']:.2f}"
        up_txt = f"{m['up_time']:.0f} s"
        _up_tip = tip
        if accel.PHYSICS_TIME_SCALE != 1.0:
            # 只显示真实生效值（游戏数据值放 tooltip），避免长文本把列宽撞开
            _eff = accel.ramp_time(m["up_time"])
            up_txt = f"≈{_eff:.0f} s"
            _up_tip = (f"游戏数据 {m['up_time']:.0f} s；受物理时钟缩放影响，"
                       f"实际约 {_eff:.0f} s。" + ("\n" + tip if tip else ""))
        if standard:
            _std = (f"标准弹射档：上限 {m['zone']:.1f} 节、推力 ×{m['forsage']:.2f}，"
                    "所有舰船共通（不是该舰特性）。起步会「窜」到该航速再慢慢爬，"
                    "所以它照样参与计算。")
            tip = (tip + "\n" if tip else "") + _std
        self._set_metric(prefix + "zone", zone)
        self._set_metric(prefix + "forsage", fs)
        self._set_metric(prefix + "up_time", up_txt)
        # ── 到弹射速度 / 90% 极速（二选一，标题跟着切）──
        # 自带大区间才有"到弹射速度"这件事；标准档（2.5 节）人人都一样、没有信息量，
        # 这时改显示到 90% 极速的时间。
        _zone = float(m.get("zone") or 0.0)
        _vmax = float(m["max_speed"])
        if has_fs and not standard and 0.0 < _zone < _vmax:
            _cap, _tip_key = "到弹射速度", f"到弹射区间上限 {_zone:.2f} 节（弹射段终点）"
            _tv = accel.time_to_speed(m, _zone, boost=True)
        elif has_fs and not standard:
            # 区间 ≥ 极速（升级品/超战插把区间放大过头）⇒ 等效于"到极速"
            _cap, _tip_key = "到极速", f"弹射区间覆盖全程，等效于到标称极速 {_vmax:.1f} 节"
            _tv = accel.time_to_speed(m, _vmax, boost=True)
        else:
            _cap = "90% 极速"
            _tip_key = f"到 90% 极速（{_vmax * 0.9:.1f} 节）——标准弹射档不做单列"
            _tv = accel.seconds_to_fraction(m, 0.9, boost=True)
        self._set_metric_cap(prefix + "tkey", _cap)
        self._set_metric(prefix + "tkey", f"{_tv:.1f} s" if _tv is not None else "—")
        if _tip_key:
            self._set_metric_tip(prefix + "tkey", _tip_key)
        if tip:
            for k in ("zone", "forsage", "tkey"):
                self._set_metric_tip(prefix + k, tip)
        if _up_tip:
            self._set_metric_tip(prefix + "up_time", _up_tip)

    def _clear_chart(self) -> None:
        """清空两页的画布。"""
        for page in self._pages.values():
            box = page["box"]
            while box.count() > 0:
                item = box.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            page["canvas"] = None
        self._canvas = None

    def _build_chart(self, model: dict, ship_name: str) -> None:
        """两页各建一个曲线画布（QPainter 自绘，无 matplotlib 依赖）。"""
        self._clear_chart()
        for key, sub in (("fwd", model), ("bwd", model.get("backward"))):
            page = self._pages[key]
            if not sub:
                page["tip"].setText("该舰船没有后退档数据，无法绘制曲线。")
                page["tip"].setVisible(True)
                continue
            page["tip"].setVisible(False)
            cv = AccelCurveCanvas(direction=key)
            cv.set_data(sub, ship_name, theme,
                        debuffs=self._debuff_models(sub) if key == "fwd" else None)
            page["box"].addWidget(cv)
            page["canvas"] = cv
            if key == "fwd":
                self._canvas = cv


class AccelCurveCanvas(QWidget):
    """加速曲线绘制区（单个方向）：v(t) + 区间/极速参考线 + 关键时间点（+ 降速状态曲线）。

    ``direction``：``"fwd"``/``"bwd"``，只影响图例与读数文案 —— 前进/后退分两页显示。
    """

    C_BOOST = "#2f7fd0"
    C_BACK = "#8e5cd9"          # 后退档（实线）
    C_ZONE = "#e08a1e"
    C_MAX = "#3fa34d"
    C_MARK = "#e05a1e"
    #: 降速状态曲线（点划线）：引擎受损 / 进水
    C_DAMAGE = "#d0463a"
    C_FLOOD = "#1f9aa8"
    #: 引擎瘫痪 +「背水一战」（紫）
    C_KEEP = "#8e5cd9"

    #: 图例带：顶部留给标题的空白 + 每行高度（图例画在坐标区**上方**，不盖曲线/标签）
    LEGEND_TOP = 22.0
    LEGEND_ROW_H = 15.0

    def __init__(self, parent=None, direction: str = "fwd"):
        super().__init__(parent)
        #: "fwd" = 前进页；"bwd" = 后退页（只影响配色与文案）
        self.direction = direction if direction in ("fwd", "bwd") else "fwd"
        self._model: dict | None = None
        self._ship_name = ""
        self._theme = None
        #: 图例折行缓存（宽度/条目变化时重算）
        self._legend_key = None
        self._legend_rows: list[list[tuple[str, str, bool]]] = []
        #: 曲线时间轴长度（秒），在 set_data 时算一次（_geom/绘制/鼠标命中共用）
        self._t_end = 60.0
        self._curve_on: list[tuple[float, float]] = []
        #: 降速状态曲线：[（图例文本, 颜色, [(t, v)]）]（进水 / 引擎受损，由弹窗按开关传入）
        self._debuffs: list[tuple[str, str, list[tuple[float, float]]]] = []
        self._marks: list[tuple[str, float, float]] = []   # (标签, t, v)
        #: 鼠标跟随读数：{"t", "v"}；None = 鼠标不在图上
        self._hover: dict | None = None
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # 开启鼠标跟踪：不按键也能收到 mouseMoveEvent（跟随读数需要）
        self.setMouseTracking(True)

    @property
    def _c_main(self) -> str:
        return self.C_BOOST if self.direction == "fwd" else self.C_BACK

    def _label_on(self) -> str:
        """图例文案。"""
        return "加速曲线" if self.direction == "fwd" else "后退曲线"

    def set_data(self, model: dict, ship_name: str, theme_obj,
                 debuffs: list[tuple[str, str, dict]] | None = None) -> None:
        """载入数据并预积分曲线。

        ``debuffs``：[（图例文本, 颜色, 模型）]，每条画成点划线；
        时间轴取所有曲线所需的最大值，避免降速曲线被截断。
        """
        self._model = model
        self._ship_name = ship_name
        self._theme = theme_obj
        t_end = accel.curve_duration(model)
        for _lbl, _col, _m in (debuffs or []):
            t_end = max(t_end, accel.curve_duration(_m))
        self._t_end = t_end
        self._curve_on = accel.integrate(model, dt=0.25, t_end=t_end, boost=True)
        self._debuffs = [(lbl, col, accel.integrate(m, dt=0.25, t_end=t_end, boost=True))
                         for lbl, col, m in (debuffs or [])]
        self._marks = []
        for frac, tag in ((0.5, "50%"), (0.9, "90%")):
            t = accel.seconds_to_fraction(model, frac, boost=True)
            if t is not None:
                self._marks.append((f"{tag}: {t:.0f}s", t, model["max_speed"] * frac))
        self.update()

    def _col(self, key: str, fallback: str) -> QColor:
        if self._theme is not None:
            try:
                val = self._theme[key]
                if val:
                    return QColor(str(val))
            except Exception:  # noqa: BLE001
                pass
        return QColor(fallback)

    @staticmethod
    def _axis_font() -> QFont:
        """坐标区/图例字体（度量与绘制用同一份，保证坐标一致）。"""
        f = QFont()
        f.setPointSize(8)
        return f

    def _legend_entries(self) -> list[tuple[str, str, bool]]:
        """图例条目：[（文本, 颜色, 是否点划线）] —— 主曲线 + 各降速状态曲线。"""
        out: list[tuple[str, str, bool]] = [(self._label_on(), self._c_main, False)]
        for _lbl, _col, _c in self._debuffs:
            out.append((_lbl, _col, True))
        return out

    def _legend_layout(self) -> list[list[tuple[str, str, bool]]]:
        """把图例按当前宽度折行（带缓存）。`_geom` 与 `paintEvent` 共用，保证两边一致。"""
        entries = self._legend_entries()
        key = (self.width(), self.direction, tuple(e[0] for e in entries))
        if self._legend_key == key:
            return self._legend_rows
        fm = QFontMetrics(self._axis_font())
        avail = max(120.0, float(self.width()) - 48.0 - 14.0 - 16.0)
        rows: list[list[tuple[str, str, bool]]] = []
        cur: list[tuple[str, str, bool]] = []
        cur_w = 0.0
        for e in entries:
            ew = 22 + 6 + fm.horizontalAdvance(e[0]) + 16
            if cur and cur_w + ew > avail:
                rows.append(cur)
                cur, cur_w = [], 0.0
            cur.append(e)
            cur_w += ew
        if cur:
            rows.append(cur)
        self._legend_key = key
        self._legend_rows = rows
        return rows

    def _draw_legend(self, p: QPainter, fg: QColor) -> None:
        """在坐标区上方的专用带里画图例（一行放不下就折行）。"""
        fm = QFontMetrics(self._axis_font())
        for ri, row in enumerate(self._legend_layout()):
            lx = 48 + 8
            ly = float(self.LEGEND_TOP) + ri * self.LEGEND_ROW_H + 4
            for label, col, dashed in row:
                p.setPen(QPen(QColor(col), 2,
                              Qt.PenStyle.DashDotLine if dashed else Qt.PenStyle.SolidLine))
                p.drawLine(QPointF(lx, ly), QPointF(lx + 22, ly))
                p.setPen(QPen(fg))
                p.drawText(QPointF(lx + 28, ly + 4), label)
                lx += 28 + fm.horizontalAdvance(label) + 16

    def _text_chip(self, p: QPainter, x: float, y: float, text: str, color: QColor,
                   bg: QColor, *, align_right: bool = False) -> None:
        """带底色的文字标签：先铺一块背景再写字 —— 曲线/参考线一多也不会糊在一起。"""
        fm = QFontMetrics(p.font())
        cw = fm.horizontalAdvance(text) + 8
        ch = fm.height() + 3
        left = (x - cw) if align_right else x
        _bg = QColor(bg)
        _bg.setAlpha(210)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_bg)
        p.drawRoundedRect(QRectF(left, y - ch + 2, cw, ch), 3, 3)
        p.setPen(QPen(color))
        p.drawText(QPointF(left + 4, y), text)
        p.setBrush(Qt.BrushStyle.NoBrush)

    # ── 坐标换算（绘制与鼠标命中共用同一套几何） ────────

    def _geom(self) -> tuple[float, float, float, float, float, float, float, float]:
        """返回 (L, R, T, B, w, h, t_end, v_top)；顶部会为图例带留出高度。"""
        m = self._model or {}
        L, R, B = 48, 14, 34
        T = float(self.LEGEND_TOP + len(self._legend_layout()) * self.LEGEND_ROW_H + 8)
        w = max(10, self.width() - L - R)
        h = max(10, self.height() - T - B)
        t_end = float(getattr(self, "_t_end", 60.0) or 60.0)
        v_top = float(m.get("max_speed", 30.0)) * 1.08
        return L, R, T, B, w, h, t_end, v_top

    def _mouse_hover(self, pos) -> None:
        """鼠标移动 → 把读数吸附到最近采样点（dt=0.25s，与穿深计算器的吸附一致）。"""
        m = self._model
        if not m or not self._curve_on:
            return
        L, _R, _T, _B, w, _h, t_end, _vt = self._geom()
        t = (pos.x() - L) / w * t_end
        t = min(max(t, 0.0), t_end)

        def _nearest(curve):
            if not curve:
                return None
            step = (curve[1][0] - curve[0][0]) if len(curve) > 1 else 0.25
            i = int(round((t - curve[0][0]) / step)) if step else 0
            return curve[min(max(i, 0), len(curve) - 1)]

        on = _nearest(self._curve_on)
        if on is None:
            return
        # 同时取各降速状态曲线在相同时刻的值（勾了才在读数框里逐条显示）
        _dbg = tuple((lbl, col, (_nearest(curve) or on)[1]) for lbl, col, curve in self._debuffs)
        state = {"t": on[0], "v": on[1], "debuffs": _dbg}
        if self._hover == state:      # 最近点未变 → 不重绘，避免鼠标移动卡顿
            return
        self._hover = state
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._mouse_hover(event.position())

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.update()

    def _paint_hover(self, p: QPainter, m: dict, sx, sy, L: float, T: float,
                     w: float, h: float, fg: QColor) -> None:
        """绘制鼠标跟随读数：竖参考线 + 各曲线交点 + 数值框（同穿深计算器的悬浮图例）。

        勾选了进水 / 引擎受损时，读数框里会**逐条**给出该时刻各曲线的航速（颜色与曲线一致）。
        """
        hv = self._hover
        if not hv:
            return
        x = sx(hv["t"])
        p.setPen(QPen(self._col("text_hint", "#888888"), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x, T), QPointF(x, T + h))
        p.setPen(QPen(QColor(self._c_main), 1))
        p.setBrush(QColor(self._c_main))
        p.drawEllipse(QPointF(x, sy(hv["v"])), 3.2, 3.2)
        # 降速状态曲线：同样标出该时刻的交点
        for _lbl, _col, _v in hv.get("debuffs") or ():
            p.setPen(QPen(QColor(_col), 1))
            p.setBrush(QColor(_col))
            p.drawEllipse(QPointF(x, sy(_v)), 3.0, 3.0)

        vmax = float(m["max_speed"]) or 1.0
        lines: list[tuple[str, QColor]] = [
            (f"时间 {hv['t']:.2f} s", fg),
            (f"{self._label_on()} {hv['v']:.2f} 节（{hv['v'] / vmax * 100:.0f}% 极速）",
             QColor(self._c_main)),
        ]
        for _lbl, _col, _v in hv.get("debuffs") or ():
            lines.append((f"{_lbl.split('（')[0]} {_v:.2f} 节", QColor(_col)))

        fnt = QFont()
        fnt.setPointSize(8)
        fm = QFontMetrics(fnt)
        bw = max(fm.horizontalAdvance(s) for s, _c in lines) + 16
        bh = len(lines) * (fm.height() + 1) + 10
        bx = x + 12
        if bx + bw > L + w:
            bx = x - 12 - bw
        bx = max(L + 2.0, min(bx, L + w - bw - 2.0))
        by = sy(hv["v"]) - bh - 10
        if by < T + 2:
            by = T + 2
        p.setBrush(QColor(self._col("panel_bg", "#ffffff")))
        p.setPen(QPen(self._col("border", "#cccccc"), 1))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
        p.setFont(fnt)
        _ty = by + 5
        for s, _c in lines:
            p.setPen(QPen(_c))
            p.drawText(QPointF(bx + 8, _ty + fm.ascent()), s)
            _ty += fm.height() + 1

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._model:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self._model
        bg = self._col("window_bg", "#ffffff")
        fg = self._col("text", "#222222")
        grid = self._col("border_soft", "#dddddd")
        p.fillRect(self.rect(), bg)

        L, R, T, B, w, h, t_end, v_top = self._geom()

        def sx(t: float) -> float:
            return L + (t / t_end) * w

        def sy(v: float) -> float:
            return T + h - (v / v_top) * h

        # 网格 + 刻度
        p.setPen(QPen(grid, 1))
        fnt = QFont()
        fnt.setPointSize(8)
        p.setFont(fnt)
        n_x = 6
        for i in range(n_x + 1):
            t = t_end * i / n_x
            x = sx(t)
            p.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x, T), QPointF(x, T + h))
            p.setPen(QPen(fg))
            p.drawText(QPointF(x - 12, T + h + 16), f"{t:.0f}")
        n_y = 4
        for i in range(n_y + 1):
            v = v_top * i / n_y
            y = sy(v)
            p.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(L, y), QPointF(L + w, y))
            p.setPen(QPen(fg))
            txt = f"{v:.0f}"
            p.drawText(QPointF(L - 8 - len(txt) * 5, y + 4), txt)
        # 轴标题
        p.setPen(QPen(fg))
        p.drawText(QPointF(L + w - 52, T + h + 16), "时间 (s)")
        p.drawText(QPointF(6, T - 8), "航速 (节)")
        p.setPen(QPen(fg))
        _dir_txt = "前进" if self.direction == "fwd" else "后退"
        p.drawText(QPointF(L, 13), f"{self._ship_name} · {_dir_txt}加速曲线")
        # 图例：画在坐标区上方的专用带（不再与曲线/参考线标签争位置），放不下自动折行
        self._draw_legend(p, fg)

        # 参考线（区间上限 ≥ 最大航速时全程生效，画布上没有对应位置）
        # 标签一律带底色芯片，避免与曲线/关键点文字重叠成一团
        _bgc = QColor(bg)
        if m["builtin_forsage"] and m["zone"] < m["max_speed"]:
            y = sy(m["zone"])
            p.setPen(QPen(QColor(self.C_ZONE), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(L, y), QPointF(L + w, y))
            _zlbl = (f"弹射区间 {m['zone']:.1f} 节（×{m['forsage']:.2f}）"
                     if is_debug_build()
                     else f"弹射区间 {m['zone']:.1f} 节")
            self._text_chip(p, L + 6, y - 5, _zlbl, QColor(self.C_ZONE), _bgc)
        y = sy(m["max_speed"])
        p.setPen(QPen(QColor(self.C_MAX), 1, Qt.PenStyle.DashDotLine))
        p.drawLine(QPointF(L, y), QPointF(L + w, y))
        _maxlbl = "最大航速" if self.direction == "fwd" else "后退极速"
        self._text_chip(p, L + w - 6, y - 5, f"{_maxlbl} {m['max_speed']:.1f} 节",
                        QColor(self.C_MAX), _bgc, align_right=True)

        # 曲线（本页只有一条实线 + 可选的降速状态点划线）
        def draw(curve, color: QColor, dashed: bool) -> None:
            pen = QPen(color, 2 if not dashed else 1.6)
            pen.setStyle(Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine)
            p.setPen(pen)
            poly = QPolygonF([QPointF(sx(t), sy(v)) for t, v in curve])
            p.drawPolyline(poly)

        draw(self._curve_on, QColor(self._c_main), False)
        # 降速状态（进水 / 引擎受损）：点划线，颜色各自区分
        for _lbl, _col, _curve in self._debuffs:
            pen = QPen(QColor(_col), 1.8)
            pen.setStyle(Qt.PenStyle.DashDotLine)
            p.setPen(pen)
            p.drawPolyline(QPolygonF([QPointF(sx(t), sy(v)) for t, v in _curve]))

        # 关键时间点（两个点靠太近时错开高度，避免文字叠在一起）
        _prev_x = None
        for text, t, v in self._marks:
            px, py = sx(t), sy(v)
            p.setBrush(QColor(self.C_MARK))
            p.setPen(QPen(QColor(self.C_MARK), 2))
            p.drawEllipse(QPointF(px, py), 3.5, 3.5)
            _ty = py - 6
            if _prev_x is not None and abs(px - _prev_x) < 46:
                _ty = py - 20
            self._text_chip(p, px + 7, _ty, text, QColor(self.C_MARK), _bgc)
            _prev_x = px

        # 鼠标跟随读数（最后画，确保在最上层）
        self._paint_hover(p, m, sx, sy, L, T, w, h, fg)
        p.end()
