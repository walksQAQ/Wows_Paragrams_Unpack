"""
FiringArcDialog —— 炮塔射界查看器（独立弹窗）。

复刻 gamemodels3d 的射界显示逻辑：
  · 总览视图：将 360° 逐度栅格化，每门炮按「可射(2)/俯仰受限(1)/死区(0)」三态标记，
    叠加得到每度角度的可用炮塔数，绘制同心扇形环（雷达图）。
  · 细节视图：点选炮塔，绘制该炮塔的绿/黄/红三态射界扇形 + 舰体俯视轮廓。

数据来源：ship_turret_arcs 表（主炮/副炮/鱼雷每门炮的
horiz_sector / vert_sector / dead_zone / pitch_dead_zones / position）。
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QFont, QPolygonF
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from services.database_service import get_db
from utils.theme import theme


# ── 颜色 ─────────────────────────────────────────────────

def _c(hex_str: str) -> QColor:
    return QColor(hex_str)


ARC_GREEN = "#5dd85d"      # 可射击
ARC_YELLOW = "#ffd24a"     # 俯仰受限
ARC_OVERVIEW = "#8FAAB3"   # 总览图背景填充
ARC_GRID = "#475559"       # 同心网格
ARC_RADIAL = "#111516"     # 径向网格

SLOT_LABELS = {
    "artillery": "主炮",
    "secondary_artillery": "中口径炮",
    "atba": "副炮",
    "torpedoes": "鱼雷",
    "air_defense": "防空",
}


# ── 角度工具 ─────────────────────────────────────────────

def _norm(deg: float) -> int:
    """归一化到 0~359（Lesta ±180° 制 → 0~360 制）"""
    return int(round((deg + 360) % 360)) % 360


def _parse_list(raw, default=None):
    """解析数据库 JSON 字段（字符串 / list / None）"""
    if raw is None:
        return default
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, str):
        try:
            import json
            return json.loads(raw)
        except Exception:
            return default
    return default


# ── 射界绘制控件 ────────────────────────────────────────

class FiringArcCanvas(QWidget):
    """射界图绘制区域：总览视图 ↔ 细节视图切换。"""

    hover_changed = Signal(str)  # 鼠标悬停信息（总览：角度+可用炮塔数）
    selected_changed = Signal(object)  # 选中炮塔（dict 或 None）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._guns: list[dict] = []      # 当前武器类型的炮列表
        self._sectors: list[int] = []    # 聚合后的 360 数组（可用炮塔数）
        self._max_turret = 1
        self._mode = "overview"          # overview / detail
        self._selected: dict | None = None
        self._hover_angle: int | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(320, 340)

    # ── 数据 ─────────────────────────────────────────

    def set_guns(self, guns: list[dict]):
        from utils.firing_arc import compute_facings
        self._guns = [g for g in guns if g.get("horiz_sector")]
        # 计算每门炮默认朝向（船头朝前/船尾朝后）并写入 dict，供绘制与齐射角计算
        for g, f in zip(self._guns, compute_facings(self._guns)):
            g["_facing"] = f
        self._mode = "overview"
        self._selected = None
        self._hover_angle = None
        self._compute_overview()
        self.update()
        self.selected_changed.emit(None)

    def set_mode(self, mode: str):
        self._mode = mode
        self._hover_angle = None
        if mode == "overview":
            self._selected = None
            self.selected_changed.emit(None)
        self.update()

    # ── 计算 ─────────────────────────────────────────

    def _gun_sector_array(self, gun: dict) -> list[int]:
        """单门炮 360° 三态栅格（绝对坐标）：2=可射，1=俯仰受限，0=死区。

        含炮塔默认朝向（_facing）转换：Lesta 射界为相对朝向的角度。
        """
        facing = gun.get("_facing", 0.0)
        sec = [0] * 360
        hs = _parse_list(gun.get("horiz_sector"), [])
        if len(hs) >= 2:
            a, b = _norm(facing + hs[0]), _norm(facing + hs[1])
            angle = a
            while True:
                sec[angle] = 2
                angle = (angle + 1) % 360
                if angle == b:
                    break
        # 俯仰受限区 → 降级为 1
        for dz in _parse_list(gun.get("pitch_dead_zones"), []) or []:
            if len(dz) >= 2:
                a, b = _norm(facing + dz[0]), _norm(facing + dz[1])
                angle = a
                while True:
                    if sec[angle]:
                        sec[angle] = 1
                    angle = (angle + 1) % 360
                    if angle == b:
                        break
        # 死区 → 强制 0
        for dz in _parse_list(gun.get("dead_zones"), []) or []:
            if len(dz) >= 2:
                a, b = _norm(facing + dz[0]), _norm(facing + dz[1])
                angle = a
                while True:
                    sec[angle] = 0
                    angle = (angle + 1) % 360
                    if angle == b:
                        break
        return sec

    def _compute_overview(self):
        sectors = [0] * 360
        max_t = 0
        for g in self._guns:
            t_sec = self._gun_sector_array(g)
            for i in range(360):
                sectors[i] += 1 if t_sec[i] else 0
                if sectors[i] > max_t:
                    max_t = sectors[i]
        # 毛刺平滑（前后邻居相同则取邻居值）
        for i in range(360):
            prev, nxt = (i + 359) % 360, (i + 1) % 360
            if sectors[prev] == sectors[nxt]:
                sectors[i] = sectors[nxt]
        self._sectors = sectors
        self._max_turret = max(1, max_t)

    # ── 几何 ─────────────────────────────────────────

    @staticmethod
    def _pt(cx: float, cy: float, r: float, ang_deg: float) -> QPointF:
        """0°=正上方，顺时针。"""
        rad = math.radians(ang_deg)
        return QPointF(cx + r * math.sin(rad), cy - r * math.cos(rad))

    def _sector_path(self, cx, cy, r, start_deg, end_deg) -> QPainterPath:
        """从 start_deg 顺时针扫到 end_deg 的扇形路径（支持跨 0°）。"""
        sweep = (end_deg - start_deg) % 360
        path = QPainterPath()
        path.moveTo(cx, cy)
        n = max(2, int(sweep) // 2 + 1)
        for k in range(n + 1):
            a = (start_deg + sweep * k / n) % 360
            path.lineTo(self._pt(cx, cy, r, a))
        path.closeSubpath()
        return path

    def _center_radius(self):
        w, h = self.width(), self.height()
        r = min(w, h) / 2 - 14
        return w / 2, h / 2, r

    # ── 绘制 ─────────────────────────────────────────

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 背景
        p.fillRect(self.rect(), theme["panel_bg"])
        if not self._guns:
            p.setPen(QPen(theme["text_muted"]))
            p.setFont(QFont("Microsoft YaHei", 10))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "该武器系统无射界数据")
            return
        if self._mode == "overview":
            self._paint_overview(p)
        else:
            self._paint_detail(p)
        p.end()

    def _paint_overview(self, p: QPainter):
        cx, cy, radius = self._center_radius()
        scale = (radius - 8) / self._max_turret

        # 聚合扇形环：按 sectors 值分段
        base = QPainterPath()
        start_deg = 0.0
        cur = self._sectors[0]
        for i in range(1, 361):
            a = i % 360
            if self._sectors[a] != cur or i == 360:
                end_deg = float(a)
                r = cur * scale
                if r > 1.5:
                    base.addPath(self._sector_path(cx, cy, r, start_deg, end_deg))
                start_deg = end_deg
                cur = self._sectors[a]
        p.fillPath(base, _c(ARC_OVERVIEW))

        # 同心网格
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(_c(ARC_GRID))
        pen.setWidthF(1.0)
        p.setPen(pen)
        for i in range(1, self._max_turret + 1):
            r = i * scale
            p.drawEllipse(QPointF(cx, cy), r, r)
        # 径向网格（15°）
        pen2 = QPen(_c(ARC_RADIAL))
        pen2.setWidthF(1.0)
        p.setPen(pen2)
        for deg in range(0, 360, 15):
            p1 = self._pt(cx, cy, scale, deg)
            p2 = self._pt(cx, cy, radius, deg)
            p.drawLine(p1, p2)
        # 外圈
        p.setPen(QPen(_c(ARC_GRID)))
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        # 悬停指示
        if self._hover_angle is not None:
            r = self._sectors[self._hover_angle] * scale
            if r > 1.5:
                hi = self._sector_path(cx, cy, r, self._hover_angle - 2, self._hover_angle + 2)
                p.fillPath(hi, _c("#3a8fbf"))

    def _paint_detail(self, p: QPainter):
        w, h = self.width(), self.height()
        cx, cy, radius = self._center_radius()
        ship_len = radius * 0.62

        # 舰体（竖直椭圆，船头朝上）
        ecc = 3.0
        body = QPainterPath()
        body.addEllipse(QRectF(cx - ship_len / ecc, cy - ship_len, 2 * ship_len / ecc, 2 * ship_len))
        p.fillPath(body, _c(ARC_OVERVIEW))
        p.setPen(QPen(_c(ARC_GRID)))
        p.drawPath(body)

        # 所有炮塔的显示位置（先算出来，选中炮塔的射界要以该炮塔为基准点）
        positions = self._turret_positions()

        # 选中炮塔的射界面画在最底层（舰体之上、炮塔点之下），
        # 以该炮塔自身位置为圆心，避免射界面遮挡其它炮塔的点
        if self._selected is not None:
            sel_pos = positions.get(id(self._selected))
            sx, sy = sel_pos if sel_pos else (cx, cy)
            # 扇形半径按炮塔到画布边缘的距离收缩，避免画出界
            sector_r = radius * 0.72
            sector_r = min(sector_r, sx - 12, w - 12 - sx, sy - 12, h - 12 - sy)
            if sector_r > 8:
                self._paint_gun_sectors(p, sx, sy, self._selected, sector_r)

        # 所有炮塔点画在最上层（含无 position 的副炮虚拟布局）
        for gun in self._guns:
            pos = positions.get(id(gun))
            if not pos:
                continue
            x, y = pos
            is_sel = gun is self._selected
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c("#2d8cf0" if is_sel else "#e8c15a"))
            p.drawEllipse(QPointF(x, y), 7, 7)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 200)))
            p.drawEllipse(QPointF(x, y), 7, 7)

    def _turret_positions(self) -> dict:
        """返回 {id(gun): (x, y)} 所有炮塔的显示位置。

        位置来源优先级：
          1. mount_pos —— assets_data.db skeleton_mounts 挂点解码的 3D 安装位置 [x,y,z]
             （x=左右舷，z=前后；副炮/主炮都有，最精确）；
          2. position —— 快照的 [col,row] 归一化坐标；
          3. 都没有（如未回填的副炮）按射界中心分左右舷、沿纵向均匀排布。
        """
        cx, cy, radius = self._center_radius()
        ship_len = radius * 0.62
        ecc = 3.0
        step = ship_len / 4.2
        positions: dict = {}
        no_pos = []
        # 先收集 mount_pos 的 z 范围，统一缩放（3D 模型坐标 → 画布）
        m3 = [(g, _parse_list(g.get("mount_pos"), None)) for g in self._guns]
        m3 = [(g, p) for g, p in m3 if p and len(p) >= 3]
        zs = [p[2] for _, p in m3] + [0.0]
        zspan = max(max(zs) - min(zs), 1.0)
        xspan = 1.0
        xs = [abs(p[0]) for _, p in m3] + [0.0]
        if max(xs) > 0:
            xspan = max(xs)
        z_scale = ship_len / zspan
        x_scale = (ship_len / ecc) / xspan if xspan > 0 else 1.0

        for gun in self._guns:
            mpos = _parse_list(gun.get("mount_pos"), None)
            if mpos and len(mpos) >= 3:
                mx, mz = float(mpos[0]), float(mpos[2])
                # x 正=右舷（画布右），z 正=船首（画布上方）
                x = cx + mx * x_scale
                y = cy - mz * z_scale
                positions[id(gun)] = (x, y)
                continue
            pos = _parse_list(gun.get("position"), None)
            if pos and len(pos) >= 2:
                col, row = float(pos[0]), float(pos[1])
                # 纵向（船头→船尾）：col 小 = 船头（上方）
                y = cy + (col - 2.5) * step
                # 横向（左舷/中/右舷）：row 0/1/2
                x = cx + (row - 1) * (ship_len / ecc)
                if abs(x - cx) > ship_len / ecc + 4 or abs(y - cy) > ship_len + 6:
                    continue
                positions[id(gun)] = (x, y)
            else:
                no_pos.append(gun)
        # 无位置信息的炮塔：按射界中心分左右舷，沿纵向排布
        if no_pos:
            from utils.firing_arc import gun_abs_segments, _arc_center
            right, left = [], []
            for gun in no_pos:
                facing = gun.get("_facing", 0.0)
                a = gun_abs_segments(gun, facing)
                c = _arc_center(a) if a else 0.0
                (right if 0 <= c < 180 else left).append((c, gun))
            side = ship_len / ecc
            self._place_fallback(positions, right, cx + side, cy, ship_len)
            self._place_fallback(positions, left, cx - side, cy, ship_len)
        return positions

    @staticmethod
    def _place_fallback(positions, group, x, cy, ship_len):
        """把一组无 position 的炮塔沿该侧纵向均匀排布，避免重叠。"""
        n = len(group)
        if not n:
            return
        group.sort(key=lambda t: t[0])  # 按射界中心角排序
        span = ship_len * 1.5
        for i, (_, gun) in enumerate(group):
            y = cy if n == 1 else cy + ((i + 0.5) / n - 0.5) * span
            positions[id(gun)] = (x, y)

    def _paint_gun_sectors(self, p: QPainter, cx, cy, gun: dict, sector_r: float):
        """选中炮塔的三态射界扇形（绿/黄/红），含朝向转换。

        cx/cy 为炮塔基准点（扇形圆心），sector_r 为扇形半径。
        """
        facing = gun.get("_facing", 0.0)
        sec = self._gun_sector_array(gun)
        hs = _parse_list(gun.get("horiz_sector"), [])
        if len(hs) < 2:
            return
        a0, b0 = _norm(facing + hs[0]), _norm(facing + hs[1])
        # 只画 horizSector 覆盖范围
        r = sector_r
        angle = a0
        while True:
            start = angle
            val = sec[angle]
            while True:
                nxt = (angle + 1) % 360
                if nxt == b0 or sec[nxt] != val:
                    break
                angle = nxt
            end = (angle + 1) % 360
            if val > 0:
                color = ARC_GREEN if val == 2 else ARC_YELLOW
                path = self._sector_path(cx, cy, r, start, end)
                p.fillPath(path, _c(color))
            angle = end
            if angle == b0:
                break

    # ── 交互 ─────────────────────────────────────────

    def mouseMoveEvent(self, ev):
        cx, cy, radius = self._center_radius()
        dx, dy = ev.position().x() - cx, cy - ev.position().y()
        dist = math.hypot(dx, dy)
        if dist < radius:
            ang = int(round(math.degrees(math.atan2(dx, dy)))) % 360
            self._hover_angle = ang
            if self._mode == "overview":
                self.hover_changed.emit(
                    f"角度: {ang}°　可用炮塔数: {self._sectors[ang]}")
            else:
                self.hover_changed.emit(f"角度: {ang}°")
        else:
            self._hover_angle = None
            self.hover_changed.emit("")
        self.update()

    def leaveEvent(self, _ev):
        self._hover_angle = None
        self.hover_changed.emit("")
        self.update()

    def mousePressEvent(self, ev):
        if self._mode != "detail":
            return
        positions = self._turret_positions()
        # 命中半径内取「最近」的炮塔，避免相邻炮塔靠太近时抢点击
        hit = None
        best = 12.0
        for gun in self._guns:
            pos = positions.get(id(gun))
            if not pos:
                continue
            x, y = pos
            d = math.hypot(ev.position().x() - x, ev.position().y() - y)
            if d < best:
                best = d
                hit = gun
        self._selected = hit
        self.selected_changed.emit(hit)
        self.update()


# ── 弹窗 ────────────────────────────────────────────────

class FiringArcDialog(QDialog):
    """炮塔射界查看器（独立弹窗，懒创建单实例）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("炮塔射界")
        self.resize(500, 600)
        self._current_ship_id = ""
        self._current_slot = ""
        self._arcs_by_slot: dict[str, list[dict]] = {}

        self._build_ui()

    def _build_ui(self):
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

        # 标题栏：当前舰船 + 武器类型（只读）
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.title_lbl = QLabel("未选择舰船")
        self.title_lbl.setStyleSheet(theme.qss("font-size: 13px; font-weight: bold; color: @text@;"))
        bar.addWidget(self.title_lbl)
        bar.addStretch(1)
        self.view_btn = QPushButton("详细信息")
        bar.addWidget(self.view_btn)
        root.addLayout(bar)

        # 齐射角文字版（前向/后向全炮塔开火角）
        self.arc_text_lbl = QLabel("")
        self.arc_text_lbl.setWordWrap(True)
        self.arc_text_lbl.setStyleSheet(theme.qss(
            "font-size: 12px; color: @text@; background: @panel_alt@;"
            "border-radius: 4px; padding: 6px 8px;"))
        root.addWidget(self.arc_text_lbl)

        # 画布
        self.canvas = FiringArcCanvas()
        root.addWidget(self.canvas, 1)

        # 信息栏
        self.info = QLabel("")
        self.info.setMinimumHeight(20)
        root.addWidget(self.info)

        # 信号
        self.view_btn.clicked.connect(self._toggle_view)
        self.canvas.hover_changed.connect(self.info.setText)
        self.canvas.selected_changed.connect(self._on_gun_selected)

    # ── 数据加载（弹窗直接绑定当前舰船，无需舰船/武器筛选） ──

    def _resolve_ship_name(self, ship_id: str) -> str:
        """从数据库解析舰船中文名（与 ship_presenter 一致）。

        优先 ship_basic_info.name_mapping_id → name_mappings.id；
        其次按 ship_index 查 category='ship' 的 key_name；查不到返回原始 ID。
        """
        if not ship_id:
            return ship_id
        try:
            db = get_db()
            row = db._conn.execute(
                "SELECT nm.lang_zh AS lang_zh, b.ship_index AS ship_index "
                "FROM ship_basic_info b "
                "LEFT JOIN name_mappings nm ON nm.id = b.name_mapping_id "
                "WHERE b.ship_id=? LIMIT 1", (ship_id,)).fetchone()
            if row and row["lang_zh"]:
                return row["lang_zh"]
            if row and row["ship_index"]:
                r2 = db._conn.execute(
                    "SELECT lang_zh FROM name_mappings "
                    "WHERE category='ship' AND key_name=? LIMIT 1",
                    (str(row["ship_index"]).upper(),)).fetchone()
                if r2 and r2["lang_zh"]:
                    return r2["lang_zh"]
        except Exception:
            pass
        return str(ship_id)

    def _firing_arc_angles(self, guns: list[dict]) -> tuple[int, int]:
        """计算前后齐射角（前向/后向，度）。

        全炮塔可齐射时取全炮塔；炮塔分列左右舷（鱼雷/副炮）时，
        前向取右舷炮塔群从 0°、后向取左舷炮塔群从 180°。
        """
        from utils.firing_arc import firing_arc_angles
        r = firing_arc_angles(guns)
        return r["front"], r["back"]

    def _set_arc_text(self, guns: list[dict], slot_type: str) -> None:
        """显示文字版齐射角：炮塔/鱼雷发射器 射界: X°（前）/Y°（后）"""
        front, back = self._firing_arc_angles(guns)
        wep_name = "鱼雷发射器" if slot_type == "torpedoes" else "炮塔"
        self.arc_text_lbl.setText(f"{wep_name} 射界: {front}°（前）/{back}°（后）")

    def _ship_mount_yaw_map(self, ship_id: str) -> dict:
        """直接从 assets_data.db 读该船炮位安装朝向：{hp_key: (yaw, [x,y,z])}。

        数据源：assets_data.db 的 skeleton_mounts（HP_ 挂点解码值，加载数据时预提取），
        经 ship_models.model_folder 定位舰体模型。按 ship_id 缓存。
        无数据（未加载数据）返回 {}，射界回退默认朝向。
        """
        cache = getattr(self, "_mount_yaw_cache", None)
        if cache is None:
            cache = {}
            self._mount_yaw_cache = cache
        if ship_id in cache:
            return cache[ship_id]
        out: dict = {}
        try:
            from app.application import app as app_ctx
            from services.assets_cache_service import AssetsCacheService
            db = get_db()
            row = db._conn.execute(
                "SELECT model_folder FROM ship_models WHERE ship_id=? LIMIT 1",
                (ship_id,)).fetchone()
            stem = ""
            if row:
                try:
                    stem = row["model_folder"] or ""
                except (IndexError, TypeError, KeyError):
                    stem = row[0] or ""
            if stem:
                c = AssetsCacheService()
                mounts = c.get_skeleton_mounts(app_ctx.ctx.bin_folder or "", stem)
                for hp, m in mounts.items():
                    yaw = math.degrees(math.atan2(m[0, 2], m[2, 2])) % 360.0
                    out[hp] = (round(yaw, 1),
                               [round(m[0, 3], 4), round(m[1, 3], 4), round(m[2, 3], 4)])
        except Exception as exc:
            out = {}
            try:
                from app.signals import bus
                bus.log_message.emit(f"⚠️ 射界挂载朝向读取失败({ship_id}): {exc}，已回退默认朝向")
            except Exception:  # noqa: BLE001
                pass
        cache[ship_id] = out
        return out

    def open_for(self, ship_id: str, slot_type: str = ""):
        """加载指定舰船与武器槽位的射界（供详情面板射界按钮调用）。

        弹窗直接绑定当前舰船，无需舰船筛选或武器类型切换；
        slot_type 指定时显示该武器，否则显示第一个有数据的武器。
        炮位安装朝向/位置从 assets_data.db 直接读取（mount_yaw/mount_pos 不再回填）。
        """
        if not ship_id:
            return
        self._current_ship_id = ship_id
        try:
            db = get_db()
            rows = db.get_turret_arcs(ship_id)
        except Exception as exc:
            self.info.setText(f"读取射界失败: {exc}")
            return
        if not rows:
            self.info.setText("该舰船暂无射界数据（请先执行「加载数据」）")
            self.canvas.set_guns([])
            self.title_lbl.setText(f"{self._resolve_ship_name(ship_id)} · 无射界数据")
            return
        self._arcs_by_slot = {}
        mount_map = self._ship_mount_yaw_map(ship_id)
        for r in rows:
            slot = r.get("slot_type", "")
            hp_key = r.get("hp_key", "")
            myaw, mpos = mount_map.get(hp_key, (None, None))
            self._arcs_by_slot.setdefault(slot, []).append({
                "hp_key": hp_key,
                "gun_index": r.get("gun_index", ""),
                "gun_name": r.get("gun_name", ""),
                "horiz_sector": _parse_list(r.get("horiz_sector_json")),
                "vert_sector": _parse_list(r.get("vert_sector_json")),
                "dead_zones": _parse_list(r.get("dead_zone_json"), []),
                "pitch_dead_zones": _parse_list(r.get("pitch_dead_zones_json"), []),
                "position": _parse_list(r.get("position_json")),
                "mount_yaw": myaw,
                "mount_pos": mpos,
                "rotation_speed_h": r.get("rotation_speed_h"),
                "rotation_speed_v": r.get("rotation_speed_v"),
                "num_barrels": r.get("num_barrels"),
                "barrel_diameter": r.get("barrel_diameter"),
                "shot_delay": r.get("shot_delay"),
            })
        # 选定槽位：优先请求的；否则取第一个有数据的武器
        chosen = None
        if slot_type and slot_type in self._arcs_by_slot and self._arcs_by_slot[slot_type]:
            chosen = slot_type
        else:
            for s in ("artillery", "atba", "torpedoes", "secondary_artillery", "air_defense"):
                if s in self._arcs_by_slot and self._arcs_by_slot[s]:
                    chosen = s
                    break
            if chosen is None and self._arcs_by_slot:
                chosen = next(iter(self._arcs_by_slot))
        self._current_slot = chosen or ""
        guns = self._arcs_by_slot.get(chosen, []) if chosen else []
        self.canvas.set_guns(guns)
        # 副炮等无真实炮塔位置（position/mount_pos）的武器不提供「图表模式」
        # （detail 界面）切换，仅显示总览图 + 齐射角文字；有位置信息的保留图表模式
        has_real_pos = any(
            _parse_list(g.get("position"), None) or _parse_list(g.get("mount_pos"), None)
            for g in guns)
        self.view_btn.setVisible(has_real_pos)
        self.view_btn.setText("详细信息")
        slot_label = SLOT_LABELS.get(chosen, chosen) if chosen else "无"
        self.title_lbl.setText(f"{self._resolve_ship_name(ship_id)} · {slot_label}")
        self.info.setText(f"{slot_label} · {len(guns)} 个炮塔")
        self._set_arc_text(guns, chosen or "")

    def _toggle_view(self):
        if self.canvas._mode == "overview":
            self.canvas.set_mode("detail")
            self.view_btn.setText("图表")
            self.info.setText("点击炮塔查看射界详情")
        else:
            self.canvas.set_mode("overview")
            self.view_btn.setText("详细信息")
            self.info.setText("")

    def _on_gun_selected(self, gun):
        if gun is None:
            return
        hs = _parse_list(gun.get("horiz_sector"), [])
        vs = _parse_list(gun.get("vert_sector"), [])
        parts = []
        name = gun.get("gun_name") or gun.get("gun_index") or gun.get("hp_key", "")
        parts.append(name)
        if len(hs) == 2:
            parts.append(f"水平射界: {hs[0]:g}° ~ {hs[1]:g}°")
        if len(vs) == 2:
            parts.append(f"垂直射界: {vs[0]:g}° ~ {vs[1]:g}°")
        dz = _parse_list(gun.get("dead_zones"), [])
        if dz:
            s = "、".join(f"{d[0]:g}° ~ {d[1]:g}°" for d in dz if len(d) >= 2)
            if s:
                parts.append(f"死区: {s}")
        self.info.setText("　".join(parts))

    def center_on_screen(self, parent=None):
        """居中于主窗口。"""
        try:
            screen = (parent or self).screen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)
        except Exception:
            pass
