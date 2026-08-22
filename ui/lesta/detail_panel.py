"""
LestaDetailPanel —— Lesta（Korabli）服详情面板。

方案 C：UI 按服务器拆分。Lesta 侧默认沿用基类 DetailPanel 的通用渲染逻辑；
后续把 Lesta 专属渲染（Lesta commander 分支等）逐步迁移到本类。
"""

from __future__ import annotations

from ui.detail_panel import DetailPanel, _ADDITIVE_KEYS_BASE
import json
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QGridLayout, QVBoxLayout, QPushButton, QLabel,
    QListView, QStackedWidget,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from utils.theme import theme
from utils.image_paths import pic_path


class LestaDetailPanel(DetailPanel):
    """Lesta（Korabli）服详情面板。"""

    SERVER_KEY = "Lesta"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wows_type = "Lesta"


    def _consumable_detail_items(self, items: list, bp, cfgd: dict, conn, vc: str, kv,
                                  *, num_raw, prep, cd_time, wt, auto, ct) -> None:
        """渲染消耗品详情条目（Lesta 版）：共用字段 + Lesta 完整类型分支树。

        WG 特有字段（时间制/可用激活方式/tacticalParams）与 WG 特有类型
        （planeTacticalFighters/auxTorpBooster）不属于本服，不在此显示。
        """
        if num_raw not in ('0', 0):
            kv("数量", '无限' if str(num_raw) == '-1' else str(num_raw))
        if auto:
            kv("自动使用", "是")
        if prep:
            kv("准备时间", f"{prep:.2f}s")
        if cd_time:
            kv("冷却时间", f"{cd_time:.2f}s")
        if wt:
            kv("持续时间", f"{wt:.2f}s")
        items.append(bp.make_item("消耗品效果", "", row_type="header", order=len(items)))
        if not self._consumable_lesta_type_branches(ct, cfgd, conn, vc, bp, kv, wt):
            kv("", "该消耗品类型未知，请催促作者更新解析逻辑，谢谢。")


    def _consumable_lesta_type_branches(self, ct: str, cfgd: dict, conn, vc: str, bp, kv, wt) -> bool:
        """Lesta 消耗品类型显示分支（按 LestaShipPresenter._append_consumables 重写）。

        含 Lesta 特有类型 depthCharges/supportBuoy/vampireDamage/massHeal；
        WG 特有类型（planeTacticalFighters/auxTorpBooster）不属于本服。
        callFighters 在 Lesta 数据中存在，参照 WG presenter 的 callFighters 逻辑补充。
        """
        _handled = True
        if ct == "crashCrew":
            kv("", "扑灭起火、清除进水、并修复受损配件。")
        elif ct == "healForsage":
            _mfa = cfgd.get('max_forsage_amount')
            _frg = cfgd.get('forsage_regeneration')
            if _mfa:
                kv("引擎加速时间", f"{_mfa:.0f}", unit="s")
                if _frg:
                    kv("引擎加速冷却时间", f"{_mfa / _frg:.0f}", unit="s")
            # boostCoeff 必须在 if _mfa 之外取值：_mfa 为空时也不致 NameError
            bc = cfgd.get('boostCoeff', 0)
            if bc:
                kv("加速倍率", f"{bc}倍")
        elif ct == "fighter":
            fn = cfgd.get('fightersName') or ""
            if fn:
                fname = bp.resolve_name('plane', fn) or fn
                kv("战斗机名称", fname)
            is_inter = cfgd.get('isInterceptor') or 0
            kv("战斗机类型", '截击机' if is_inter else '战斗机')
            fn2 = cfgd.get('fightersNum') or 0
            kv("飞机数量", str(fn2))
            dog = cfgd.get('dogFightTime', 0)
            if isinstance(dog, dict):
                dog = next((x for x in dog.values() if isinstance(x, (int, float))), 0)
            fly = cfgd.get('flyAwayTime', 0)
            if dog or fly:
                kv("狗斗/离开", f"狗斗 {dog}s | 离开 {fly}s")
            rk = cfgd.get('distanceToKill', 0)
            if isinstance(rk, dict):
                rk = next((x for x in rk.values() if isinstance(x, (int, float))), 0)
            if rk:
                kv("巡逻半径", f"{rk/10:.2f}km")
        elif ct == "scout":
            dc = (float(cfgd.get('artilleryDistCoeff', 0) or 1) - 1)
            kv("主炮射程", f"{dc*100:+.2f}%")
            modifiers = cfgd.get('modifiers')
            if modifiers and isinstance(modifiers, dict):
                from models.name_mapping import Mapping as NM2
                for mk, mv in sorted(modifiers.items()):
                    label = NM2.MODIFIER_MAP.get(mk, mk)
                    kv(label, f"{(mv-1)*100:+.0f}%")
        elif ct == "smokeGenerator":
            r = float(cfgd.get('radius', 0) or 0)
            kv("烟雾半径", f"{r*3:.2f}m")
            h = cfgd.get('height', 0)
            if h:
                kv("烟雾高度", f"{h}m")
            sp = cfgd.get('speedLimit', 0)
            lt = cfgd.get('lifeTime', 0)
            if sp or lt:
                kv("速度限制/扩散", f"速度 {sp}kts | 扩散 {lt}s")
        elif ct == "speedBoosters":
            bc = float(cfgd.get('boostCoeff', 0) or 0)
            kv("最高航速", f"{bc*100:+.0f}%")
            fef = float(cfgd.get('forwardEngineForsag', 0) or 1)
            bef = float(cfgd.get('backwardEngineForsag', 0) or 1)
            kv("推力", f"前进 ×{fef:g} / 后退 ×{bef:g}")
        elif ct == "sonar":
            ds = float(cfgd.get('distShip', 0) or 0) * 0.03
            dt = float(cfgd.get('distTorpedo', 0) or 0) * 0.03
            dm = float(cfgd.get('distSeaMine', 0) or 0) * 0.03
            kv("舰船探测", f"{ds:.2f} km")
            if dt:
                kv("鱼雷探测", f"{dt:.2f} km")
            if dm:
                kv("水雷探测", f"{dm:.2f} km")
        elif ct == "torpedoReloader":
            trt = cfgd.get('torpedoReloadTime', 0)
            if trt:
                kv("鱼雷装填时间", f"{trt}s")
        elif ct == "rls":
            ds = float(cfgd.get('distShip', 0) or 0) * 0.03
            kv("舰船探测", f"{ds:.2f} km")
            ac_classes = cfgd.get('affectedClasses', [])
            if ac_classes:
                kv("限制探测舰种", ', '.join(ac_classes))
        elif ct == "artilleryBoosters":
            bc = (float(cfgd.get('boostCoeff', 0) or 1) - 1)
            kv("主炮装填时间", f"{bc*100:+.2f}%")
        elif ct == "depthCharges":
            r = float(cfgd.get('radius', 0) or 0) * 0.003
            kv("半径", f"{r:.2f}km")
        elif ct == "regenCrew":
            # 船用维修小组：regenerationHPSpeed 每秒回复比例，按当前舰船血量换算实际回复
            rr = cfgd.get('regenerationHPSpeed', 0) or cfgd.get('regenerationRate', 0)
            if rr:
                # 每秒回复百分比（基础比例）
                kv("每秒回复百分比", f"+{rr*100:.2f}%")
                # 每秒回复血量 / 单次总可回复量：按当前舰船血量换算（无血量数据时用比例兜底）
                _health = None
                try:
                    ship_id = self._current_filename or ""
                    _letter = getattr(self, '_active_config_letter', 'A')
                    h_hp = conn.execute(
                        "SELECT health FROM ship_module_hulls "
                        "WHERE version_code=? AND ship_id=? AND config_group LIKE ? AND health IS NOT NULL LIMIT 1",
                        (vc, ship_id, f"{_letter}%")).fetchone()
                    if h_hp:
                        _health = h_hp['health']
                except Exception:
                    _health = None
                if _health:
                    kv("每秒回复血量", f"+{rr * _health:.0f} HP")
                    if wt:
                        kv("单次总可回复量", f"+{rr * wt * _health:.0f} HP")
                elif wt:
                    kv("单次总可回复量", f"+{rr * wt * 100:.2f}%")
            _delay = cfgd.get('regenerationDelay', 0)
            if _delay:
                kv("回复延迟", f"{_delay}s")
        elif ct == "regenerateHealth":
            # 飞机/中队维修消耗品：regenerationRate 为每秒回复比例（恢复的是飞机，不按船血量换算）
            rr = cfgd.get('regenerationRate', 0) or cfgd.get('regenerationHPSpeed', 0)
            if rr:
                kv("每秒回复百分比", f"+{rr*100:.2f}%")
            _delay = cfgd.get('regenerationDelay', 0)
            if _delay:
                kv("回复延迟", f"{_delay}s")
        elif ct == "airDefenseDisp":
            adm = cfgd.get('areaDamageMultiplier', 0)
            bdm = cfgd.get('bubbleDamageMultiplier', 0)
            if adm:
                kv("防空区域秒伤", f"{adm*100:+.2f}%")
            if bdm:
                kv("黑云伤害", f"{bdm*100:+.2f}%")
        elif ct == "hydrophone":
            zlt = cfgd.get('zoneLifeTime', 0)
            huf = cfgd.get('hydrophoneUpdateFrequency', 0)
            hwr = cfgd.get('hydrophoneWaveRadius', 0)
            if zlt:
                kv("虚影存留", f"{zlt}s")
            if huf:
                kv("刷新", f"{huf}s")
            if hwr:
                kv("视野距离", f"{hwr*0.001:.2f}km")
        elif ct == "fastRudders":
            brt = (float(cfgd.get('buoyancyRudderTimeCoeff', 0) or 1) - 1)
            bsc = (float(cfgd.get('maxBuoyancySpeedCoeff', 0) or 1) - 1)
            kv("水平舵换挡", f"{brt*100:+.2f}%")
            if bsc:
                kv("上浮/下潜速度", f"{bsc*100:+.2f}%")
        elif ct == "subsEnergyFreeze":
            kv("", "启用后下潜能力将停止消耗")
            cue = cfgd.get('canUseOnEmpty', False)
            kv("可在电池耗尽时启用", '是' if cue else '否')
        elif ct == "submarineLocator":
            ds = float(cfgd.get('distShip', 0) or 0) * 0.03
            kv("舰船探测", f"{ds:.2f} km")
        elif ct == "planeSmokeGenerator":
            ad = cfgd.get('activationDelay', 0)
            r = float(cfgd.get('radius', 0) or 0)
            if ad:
                kv("生效延迟", f"{ad}s")
            if r:
                kv("烟雾半径", f"{r*3:.2f}m")
        elif ct == "callFighters":
            # Lesta 数据存在 callFighters（Lesta presenter 未含此分支），参照 WG callFighters 逻辑
            fn = cfgd.get('fightersName') or ""
            if fn:
                fname = bp.resolve_name('plane', fn) or fn
                kv("战斗机名称", fname)
            # 数量/截击机（与飞机消耗品 presenter 对齐）
            fn2 = cfgd.get('fightersNum') or 0
            is_inter = cfgd.get('isInterceptor') or 0
            if fn2 or is_inter:
                kv("数量", f"{fn2}{' | 截击机' if is_inter else ''}")
            tda = cfgd.get('timeDelayAttack', 0)
            fly = cfgd.get('flyAwayTime', 0)
            if tda or fly:
                kv("攻击延迟/离开", f"攻击延迟 {tda}s | 离开 {fly}s")
            wp = cfgd.get('workPreparationTime', 0)
            if wp:
                kv("准备时间", f"{wp}s")
        elif ct == "supportBuoy":
            bdv = cfgd.get('battleDropVisualName', 'Unknown')
            bda = cfgd.get('battleDropActivationTime', 0)
            zlt = cfgd.get('zoneLifetime', 0)
            kv("区域", bdv)
            if bda:
                kv("布置时间", f"{bda}s")
            if zlt:
                kv("持续时间", f"{zlt}s")
        elif ct == "vampireDamage":
            dgm = cfgd.get('damageGMHealCoeff', 0)
            if dgm:
                kv("伤害转化系数", f"{dgm*100:.2f}%")
        elif ct == "massHeal":
            ohp = cfgd.get('ownHealPart', 0)
            if ohp:
                kv("自身每秒回复", f"{ohp*100:.2f}%")
            wr = cfgd.get('workRadius', 0)
            if wr:
                kv("回复作用半径", f"{wr*3/100:.2f} km")
            abn = cfgd.get('allyBuffName', '')
            abl = cfgd.get('allyBuffLevel', 1)
            if abn:
                kv("友军增益", f"{abn} (等级{abl})")
        else:
            _handled = False
        return _handled


    def _build_lesta_commander_column(self, config, _col, layout):
        """Lesta 舰长技能列：舰长下拉（分类配色）+ 技能网格 + 天赋（方案 C 迁移）。"""
        col, cl = _col("舰长技能")
        # ── 按国籍查询可用舰长 ──
        ship_nation = config.get("nation", "")
        # nation映射：中文名→数据库nation code
        from models.name_mapping import Mapping as _NM
        _rev_nation = {v: k for k, v in _NM.NATION_MAP.items()}
        db_nation = _rev_nation.get(ship_nation, ship_nation)

        from PySide6.QtWidgets import QComboBox
        # ── 舰长选择行：下拉框 + 自定义按钮 ──
        crew_row = QWidget()
        crew_row_layout = QHBoxLayout(crew_row)
        crew_row_layout.setContentsMargins(0,0,0,0); crew_row_layout.setSpacing(4)

        self._crew_combo = QComboBox()
        # 关键步骤：显式设置 QListView，确保滚轮事件与滚动条响应正常
        self._crew_combo.setView(QListView())
        self._crew_combo.setMaxVisibleItems(6)

        # 现代化下拉框样式：圆角 + 主题色 + 圆角下拉箭头按钮（与全局 QComboBox 风格一致）
        self._crew_combo.setStyleSheet(theme.qss("""
            QComboBox {
                font-size: 11px;
                padding: 3px 6px;
                background: @input_bg@;
                color: @text@;
                border: 1px solid @border@;
                border-radius: 3px;
                selection-background-color: @selected_bg@;
                selection-color: @selected_fg@;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 18px;
                border-left: 1px solid @border@;
                border-top-right-radius: 3px;
                border-bottom-right-radius: 3px;
                background: @panel_alt@;
            }
            QComboBox::down-arrow {
                image: url(:/resources/pictures/ui/combo_arrow.png);
                width: 10px;
                height: 10px;
            }
            QComboBox QAbstractItemView {
                min-width: 200px;
                background: @panel_bg@;
                color: @text@;
                selection-background-color: @selected_bg@;
                selection-color: @selected_fg@;
                border: 1px solid @border@;
                outline: none;
                padding: 2px;
            }
            /* 明确指定垂直滚动条样式与宽度 */
            QComboBox QAbstractItemView QScrollBar:vertical {
                width: 10px;
                background: @panel_alt@;
                border: none;
                margin: 0px;
                border-radius: 5px;
            }
            QComboBox QAbstractItemView QScrollBar::handle:vertical {
                background: @scroll_handle@;
                min-height: 20px;
                border-radius: 5px;
                margin: 2px;
            }
            QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {
                background: @scroll_handle_hover@;
            }
            QComboBox QAbstractItemView QScrollBar::add-line:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QComboBox QAbstractItemView QScrollBar::add-page:vertical,
            QComboBox QAbstractItemView QScrollBar::sub-page:vertical {
                background: none;
            }
        """))
        self._crew_data: list[dict] = []  # 存储所有舰长条目

        self._crew_customize_btn = QPushButton("✎")
        self._crew_customize_btn.setToolTip("自定义舰长技能/天赋")
        # 老版本(v3.2.2-test1)样式：固定深色底+黄色文字
        self._crew_customize_btn.setStyleSheet("""
            QPushButton { background:#3a3a3a; border:1px solid #ffc107; border-radius:3px;
                          min-width:24px; max-width:24px; min-height:24px; max-height:24px;
                          font-size:13px; color:#ffc107; padding:0px; }
            QPushButton:hover { background:#4a4a4a; border-color:#ffd54f; }
            QPushButton:disabled { background:#2a2a2a; border-color:#555; color:#555; }
        """)
        self._crew_customize_btn.setEnabled(False)

        crew_row_layout.addWidget(self._crew_combo, 1)
        crew_row_layout.addWidget(self._crew_customize_btn)
        cl.addWidget(crew_row)

        # 查库：该国 + 通用的非模板舰长
        from services.database_service import get_db
        _db = get_db()
        _crew_list = []
        if _db and _db._conn:
            try:
                cur = _db._conn.execute("""
                    SELECT c.crew_id, c.nation, c.is_unique, c.is_person, c.is_elite,
                           c.skills_container,
                           COALESCE(n.lang_zh, c.person_name, c.crew_id) as disp,
                           (SELECT COUNT(*) FROM crew_unique_skills us
                            WHERE us.version_code=c.version_code AND us.crew_id=c.crew_id) as unique_skill_count
                    FROM crew_basic_info c
                    LEFT JOIN name_mappings n ON n.id=c.display_name_id
                                               OR (n.category='crew' AND n.key_name='IDS_' || UPPER(c.person_name))
                    WHERE c.nation IN (?, 'Common') AND c.person_name != ''
                      AND c.crew_id NOT LIKE '%Template%'
                    ORDER BY c.is_unique DESC, c.is_elite DESC, c.is_person DESC
                """, (db_nation,))
                _crew_list = [dict(r) for r in cur.fetchall()]
            except Exception as exc:
                try:
                    from app.signals import bus
                    bus.log_message.emit(f"⚠️ 舰长列表查询失败: {exc}")
                except Exception:  # noqa: BLE001
                    pass

        # 填充下拉框：按分类分组
        self._crew_data = []
        from PySide6.QtGui import QStandardItemModel, QStandardItem, QColor
        _model = QStandardItemModel(self._crew_combo)

        def _colored_item(text: str, color: str) -> QStandardItem:
            it = QStandardItem(text)
            it.setForeground(QColor(color))
            return it


        # ── 传奇舰长（有国家天赋） ──
        legends = [cd for cd in _crew_list if cd['is_unique'] and cd['unique_skill_count'] > 0]
        # ── 特殊舰长（is_unique 但有独立技能组） ──
        specials = [cd for cd in _crew_list if cd['is_unique'] and cd['unique_skill_count'] == 0]
        # ── 有独立技能容器的通用舰长（如 PCW 系列自定义 PCOL） ──
        named_regulars = [cd for cd in _crew_list if not cd['is_unique'] and cd.get('skills_container')
                          and cd['skills_container'] != 'PCOL001_CommonCrewSkills']
        # ── 普通舰长（默认技能组） ──
        generic_regulars = [cd for cd in _crew_list if not cd['is_unique']
                            and (not cd.get('skills_container') or cd['skills_container'] == 'PCOL001_CommonCrewSkills')]

        if legends:
            for cd in legends:
                self._crew_data.append(cd)
                _model.appendRow(_colored_item(f"★ {cd['disp']}", "#ffc107"))

        # ── 精英舰长（自定义入口，红色） ──
        elite_entry = {
            'crew_id': '__elite__',
            'nation': db_nation,
            'is_unique': 0,
            'is_person': 0,
            'is_elite': 0,
            'disp': '精英舰长',
            'unique_skill_count': 0,
        }
        self._crew_data.append(elite_entry)
        _model.appendRow(_colored_item("♦ 精英舰长", "#e53935"))

        if specials:
            for cd in specials:
                self._crew_data.append(cd)
                _model.appendRow(_colored_item(f"◆ {cd['disp']}", "#42a5f5"))

        # ── 有独立 PCOL 的通用舰长（特殊通用舰长，青色标识） ──
        if named_regulars:
            for cd in named_regulars:
                self._crew_data.append(cd)
                _model.appendRow(_colored_item(f"◈ {cd['disp']}", "#26c6da"))

        # 自定义稀有舰长（蓝色，始终显示）
        custom_entry = {
            'crew_id': '__custom__',
            'nation': db_nation,
            'is_unique': 0,
            'is_person': 0,
            'is_elite': 0,
            'disp': '自定义稀有舰长',
            'unique_skill_count': 0,
        }
        self._crew_data.append(custom_entry)
        _model.appendRow(_colored_item("◆ ✎ 自定义稀有舰长", "#42a5f5"))

        # ── 标准舰长（默认技能组） ──
        if generic_regulars:
            std_entry = {
                'crew_id': '__standard__',
                'nation': db_nation,
                'is_unique': 0,
                'is_person': 0,
                'is_elite': 0,
                'disp': '标准舰长',
                'unique_skill_count': 0,
            }
            self._crew_data.append(std_entry)
            _model.appendRow(QStandardItem("标准舰长"))

        self._crew_combo.setModel(_model)

        # ── 传奇舰长天赋按钮区域 ──
        self._unique_skill_container = QWidget()
        self._us_layout = QHBoxLayout(self._unique_skill_container)
        self._us_layout.setContentsMargins(0,0,0,0); self._us_layout.setSpacing(4)
        self._us_layout.addStretch()
        cl.addWidget(self._unique_skill_container)

        # ── 技能点数 ──
        self._skill_pts_label = QLabel("技能点数: 0 / 21")
        self._skill_pts_label.setStyleSheet(theme.qss("font-size:10px; color:@text_muted@; padding:2px 0;"))
        cl.addWidget(self._skill_pts_label)

        # ── 技能按钮网格：以当前舰船舰种为准 ──
        cur_shiptype = config.get("shiptype_en", "") or config.get("shiptype", "") or "通用"
        from services.skill_service import SkillService
        _skill_svc = SkillService()
        ship_cn = _skill_svc.get_ship_type_cn(cur_shiptype)

        # 技能容器默认使用标准舰长配置，切换舰长时 _on_crew_changed 会自动更新
        _default_pcol = "PCOL001_CommonCrewSkills"
        _db_vc = _db.get_latest_version_code() if _db else ""

        grid_skills = _skill_svc.get_grid_skills(ship_cn, container_id=_default_pcol, ship_type_en=cur_shiptype) if ship_cn else []
        # 如果默认选中 elite/custom，加载 EPIC 配置
        if self._crew_data and len(self._crew_data) > 0:
            _first = self._crew_data[0]
            if _first and _first['crew_id'] in ('__elite__', '__custom__'):
                _cached_init = DetailPanel._crew_custom_cache.get(_first['crew_id'], {})
                self._apply_epic_overrides(grid_skills, _cached_init.get("epic", []),
                                            skill_svc=_skill_svc, ship_type_en=cur_shiptype)

        TIER_COST = {0: 1, 1: 2, 2: 3, 3: 4}  # 每层花费点数 = 层数
        MAX_POINTS = 21
        skill_btns: list[list[QPushButton]] = [[], [], [], []]  # 按行(层)分组
        selected_tier_spent = [0, 0, 0, 0]  # 每层已花点数

        # 老版本(v3.2.2-test1)样式：固定深色底+浅色文字，图标清晰可读
        SKILL_BTN = """
            QPushButton { background:#2a2a2a; border:1px solid #444; border-radius:4px;
                          min-width:32px; min-height:32px; max-width:32px; max-height:32px;
                          font-size:9px; color:#ccc; padding:0px; }
            QPushButton:hover { background:#3a3a3a; border-color:#1a73e8; }
            QPushButton:checked { background:#1a73e8; color:#fff; border-color:#1a73e8; }
        """

        from models.name_mapping import Mapping as _NM
        _MODIFIER_MAP = getattr(_NM, 'MODIFIER_MAP', {})
        _MM = _MODIFIER_MAP
        _RIBBON_NAMES = getattr(_NM, 'RIBBON_MAP_CREW', {})

        def _format_trigger_cond(ttype: str, divider: float, trigger: dict | None = None) -> str:
            """格式化触发条件描述（trigger 可选，用于补充具体细节，避免重复显示）"""
            cond_map = {
                "potentialDamageRatio": f"每积累 {divider:.0f} 潜在伤害时触发1次",
                "entityIsInvisibleTrigger": "当战舰未被敌方发现时",
                "activeAirDefense": "当防空炮开火时",
                "visibleEnemyWithinGsTrigger": "当副炮射程内存在敌军战舰时",
                "activationOnBurnFlood": "战舰上每个活跃的火源和进水点",
                "atbaHeat": "存在手动选择的副炮优先目标时",
                "enemyWithinVisibilityTrigger": "当战舰的标准被侦查范围内有敌方战舰时",
                "EnemiesNotLessThanAlliesWithinGMTrigger": "当主炮射程范围内的友方战舰不多于敌方战舰时",
                "entityIsVisibleTrigger": "当战舰被敌方发现时",
                "activationOnDetectTrigger": "被敌方发现时",
                "assistDamageRatio": f"每积累 {divider:.0f} 团队协助伤害时触发1次",
                "torpedoHit": "当鱼雷命中时触发",
                "mainCaliberHit": "当主炮命中时触发",
                "secondaryCaliberHit": "当副炮命中时触发",
                "planeAttack": "当飞机攻击时触发",
                "fireChance": "当起火时触发",
                "floodChance": "当进水时触发",
            }
            if ttype == "activationOnRibbons":
                # 合并勋带类型/次数/持续时间到同一行，避免重复显示
                _tr = trigger or {}
                _rib_types = _tr.get("triggerRibbonsTypes", [])
                _rib_num = _tr.get("triggerRibbonsNum", 1)
                _dur = _tr.get("duration", 0)
                _rib_labels = [_RIBBON_NAMES.get(str(t), f"勋带{t}") for t in _rib_types]
                if _rib_labels:
                    _cond = "获得" + "、".join(_rib_labels)
                    if _rib_num > 1:
                        _cond += f" {_rib_num}次"
                    if _dur > 0:
                        _cond += f"后 {_dur:.0f} 秒内"
                    return _cond
                return "获得特定勋带时触发"
            if ttype == "activationOnPingTargetsCount":
                return "每用声呐标记一艘敌舰时"
            if ttype == "activationOnEntityVisibilityFlags":
                return "当被敌人发现或被敌方潜艇的被动声呐探测时"
            if ttype == "submarineHydrophone":
                return "当战舰位于潜望镜深度或工作深度时"
            if ttype == "activationOnBuoyancyState":
                # 合并具体深度状态到同一行，避免重复显示
                _tr = trigger or {}
                _states = _tr.get("buoyancyStates", [])
                if _states:
                    _depth_names = getattr(_NM, 'DEPTH_MAP', {})
                    _labels = [_depth_names.get(s, s) for s in _states]
                    return f"当战舰位于{'或'.join(_labels)}时"
                return "处于特定深度状态时"
            return cond_map.get(ttype, f"触发条件: {ttype} ({divider})")

        def _format_skill_mod(mods: dict, st: str) -> list[str]:
            """格式化技能加成描述，返回每行一条的列表"""
            _mm = _MM
            # 特殊修饰符覆盖描述
            _desc_override = {
                "restoreForsage": "完全恢复舰载机中队飞机最后一个攻击编队的引擎加力",
                "fireResistanceEnabled": "最大火灾次数 <span style=\"color:#4caf50;\">-1</span>",
            }
            # 隐藏的修饰符（不在技能提示中显示）
            _hidden_mods = {"torpedoDetectionCoefficientByPlane"}
            _hidden_prefixes = ("massHeal", "vampireDamage")
            # 按战舰等级区分的修饰符
            _ship_tier = config.get("tier", 0) or 0
            # 合并显示的修饰符
            _burn_chance_shown = False
            # 检查当前舰船是否携带截击机
            _is_interceptor = None
            _ship_id = config.get("ship_id", "")
            if _db and _db._conn and _ship_id:
                try:
                    _vc = _db.get_latest_version_code() or ""
                    _rows = _db._conn.execute("""
                        SELECT DISTINCT 1 FROM ship_consumable_slots scs
                        JOIN consumable_configs cc ON cc.version_code=scs.version_code
                            AND cc.consumable_id=scs.consumable_id AND cc.config_key=scs.config_key
                        WHERE scs.version_code=? AND scs.ship_id=?
                          AND cc.consumable_type IN ('fighter','callFighters')
                          AND json_extract(cc.extra_json, '$.isInterceptor') = 1
                        LIMIT 1
                    """, (_vc, _ship_id)).fetchone()
                    _is_interceptor = _rows is not None
                except Exception:
                    pass
            lines = []
            for mk, mv in mods.items():
                if mk in _desc_override:
                    lines.append(_desc_override[mk])
                    continue
                if mk in _hidden_mods:
                    continue
                if mk.startswith(_hidden_prefixes):
                    continue
                # 等级区分修饰符：按当前舰船等级过滤
                if mk == "callFightersAdditionalPlanesHighLevel" and _ship_tier < 8:
                    continue
                if mk == "callFightersAdditionalPlanesLowLevel" and _ship_tier >= 8:
                    continue
                # burnChanceFactor 高低级合并显示
                # 「造成起火的几率」为进攻属性：降低=减益(红)，升高=增益(绿)，不取反
                if mk in ("burnChanceFactorHighLevel", "burnChanceFactorLowLevel"):
                    if not _burn_chance_shown:
                        _burn_chance_shown = True
                        _add_mod_line(lines, "应用加成前，造成起火的几率", mv)
                    continue
                # 按截击机/巡逻战斗机动态调整标签
                if mk in ("callFightersWorkTimeCoeff", "callFightersAdditionalConsumables"):
                    if _is_interceptor is True:
                        zh = "截击机消耗品作用时间" if mk == "callFightersWorkTimeCoeff" else "截击机消耗品装载数"
                    elif _is_interceptor is False:
                        zh = "巡逻战斗机消耗品作用时间" if mk == "callFightersWorkTimeCoeff" else "巡逻战斗机消耗品装载数"
                    else:
                        zh = _mm.get(mk, mk)
                elif mk in ("uwCoeffBonus", "prioritySectorStrengthBonus", "ignorePTZBonus"):
                    zh = _mm.get(mk, mk)
                    # 整数百分比（如 7 = +7%，25 = +25%）
                    _add_mod_line(lines, zh, mv, _force_pct=True, mod_key=mk)
                    continue
                elif mk == "dcSplashSizeMultiplier":
                    # 同时显示两条描述
                    _add_mod_line(lines, "攻击潜艇时炮弹的爆炸半径", mv)
                    _add_mod_line(lines, "深水炸弹对战舰、鱼雷和水雷的爆炸半径", mv)
                    continue
                elif mk == "lastChanceReloadCoefficient":
                    # 每失去1%生命值的变化（按舰种区分）
                    _pct = f"{mv:.2f}%"
                    if st == "Submarine":
                        _weapons = [
                            "鱼雷发射管装填时间",
                            "深水炸弹装填时间",
                        ]
                    else:
                        _weapons = [
                            "主炮装填时间",
                            "鱼雷发射管装填时间",
                            "深水炸弹装填时间",
                            "空袭和支援中队装填时间",
                            "副炮装填时间",
                            "防空持续伤害",
                        ]
                    for i, _w in enumerate(_weapons):
                        _sign = "+" if i == len(_weapons) - 1 else "-"
                        # 装填时间降低/防空持续伤害提升均视为增益 → 绿色
                        _clr = "#4caf50"
                        lines.append(f'{_w}  <span style="color:{_clr};">{_sign}{_pct}</span>')
                    continue
                elif mk == "shootShiftBatteryLastChanceCoeff":
                    # 每消耗1%下潜能力的变化
                    _pct = f"+{mv:.2f}%"
                    # 敌方对我炮击误差增大 → 增益 → 绿色
                    lines.append(f'被敌方炮弹攻击的误差  <span style="color:#4caf50;">{_pct}</span>')
                    continue
                elif mk == "batteryRegenBatteryLastChanceCoeff":
                    # 每消耗1%下潜能力的变化
                    _pct = f"+{mv:.2f}%"
                    # 下潜能力恢复提升 → 增益 → 绿色
                    lines.append(f'每秒下潜能力恢复  <span style="color:#4caf50;">{_pct}</span>')
                    continue
                elif mk in ("GMHECSDamageCoeff", "GMSHECSDamageCoeff"):
                    # 高爆和半穿甲弹分开显示
                    if isinstance(mv, dict):
                        _he = mv.get("HE", mv.get("he", None))
                        _cs = mv.get("CS", mv.get("cs", mv.get("SAP", None)))
                        if _he is not None:
                            _add_mod_line(lines, "高爆弹伤害", _he, mod_key=mk)
                        if _cs is not None:
                            _add_mod_line(lines, "半穿甲弹伤害", _cs, mod_key=mk)
                    else:
                        _add_mod_line(lines, _mm.get(mk, mk), mv, mod_key=mk)
                    continue
                else:
                    zh = _mm.get(mk, mk)
                # 小数值百分比加成（如起火率 0.05 = +5.00%）
                _pct_keys = {"bombBurnChanceBonus", "rocketBurnChanceBonus",
                             "artilleryBurnChanceBonus", "burnChanceBonus"}
                if isinstance(mv, dict):
                    # 按当前舰种过滤
                    if st and st in mv:
                        v = mv[st]
                        _add_mod_line(lines, zh, v, _force_pct=(mk in _pct_keys), mod_key=mk)
                    else:
                        for k, v in mv.items():
                            if isinstance(v, (int, float)):
                                _add_mod_line(lines, f"{zh} ({k})", v, _force_pct=(mk in _pct_keys), mod_key=mk)
                                break
                else:
                    _add_mod_line(lines, zh, mv, _force_pct=(mk in _pct_keys), mod_key=mk)
            return lines

        def _add_mod_line(lines, label, v, _force_pct=False, mod_key="", _neg=False):
            """添加一行修饰符描述（统一：标签 + 带颜色数值，增益绿/减益红）
            _neg=True 时方向取反（负值=增益，如起火率降低）。"""
            def _c(text, gain):
                clr = "#4caf50" if gain else "#f44336"
                return f'<span style="color:{clr};">{text}</span>'
            if isinstance(v, bool):
                lines.append(f"启用 {label}" if v else label)
            elif isinstance(v, (int, float)):
                if mod_key:
                    from models.name_mapping import Mapping as _NMAP_FMT2
                    ft = _NMAP_FMT2.format_modifier(mod_key, v, color=True)
                    if ft:
                        lines.append(f"{label} {ft}")
                elif _force_pct:
                    text = f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"
                    lines.append(f"{label} {_c(text, (v >= 0) != _neg)}")
                elif isinstance(v, float) and v < 2.0:
                    pct = (v - 1.0) * 100
                    lines.append(f"{label} {_c(f'{pct:+.2f}%', (pct >= 0) != _neg)}")
                elif isinstance(v, int) or (isinstance(v, float) and v == int(v)):
                    _iv = int(v)
                    lines.append(f"{label} {_c(f'{_iv:+.0f}', (_iv >= 0) != _neg)}")
                else:
                    lines.append(f"{label} {_c(f'{v:+.2f}', (v >= 0) != _neg)}")
            return lines
            return "\n".join(lines)

        def _update_skill_state():
            remaining = MAX_POINTS - sum(selected_tier_spent)
            # 逐层检查解锁状态
            for tier in range(4):
                tier_locked = False
                if tier > 0 and selected_tier_spent[tier - 1] < TIER_COST[tier - 1]:
                    tier_locked = True  # 上层未点至少1个技能
                if tier_locked:
                    # 锁定层：清除已选
                    for ci, btn in enumerate(skill_btns[tier]):
                        if btn.isChecked():
                            btn.setChecked(False)
                            _pos_key = f"{tier}-{ci}"
                            if hasattr(self, '_selected_skill_mods'):
                                self._selected_skill_mods.pop(_pos_key, None)
                        btn.setEnabled(False)
                    selected_tier_spent[tier] = 0
                    continue
                for btn in skill_btns[tier]:
                    cost = TIER_COST[tier]
                    if btn.isChecked():
                        btn.setEnabled(True)  # 已选的保持可选
                    elif remaining >= cost:
                        btn.setEnabled(True)
                    else:
                        btn.setEnabled(False)
            total_spent = sum(selected_tier_spent)
            self._skill_pts_label.setText(f"技能点数: {total_spent} / {MAX_POINTS}")

        def _make_skill_click(tier: int, col: int, btn: QPushButton, sk_mods: dict, sk_trigger: dict):
            def _on_click(checked: bool):
                cost = TIER_COST[tier]
                if checked:
                    selected_tier_spent[tier] += cost
                else:
                    selected_tier_spent[tier] -= cost
                _update_skill_state()
                # 跟踪技能修饰符，触发数据重算
                _pos_key = f"{tier}-{col}"
                if not hasattr(self, '_selected_skill_mods'):
                    self._selected_skill_mods = {}
                if checked:
                    # 合并 trigger 段 modifiers
                    _merged = dict(sk_mods)
                    if sk_trigger:
                        _tmods = sk_trigger.get("modifiers", {})
                        if _tmods:
                            _merged.update(_tmods)
                    self._selected_skill_mods[_pos_key] = _merged
                else:
                    self._selected_skill_mods.pop(_pos_key, None)
                # 合并升级品+技能所有修饰符
                if not hasattr(self, '_skill_debounce_timer'):
                    from PySide6.QtCore import QTimer
                    self._skill_debounce_timer = QTimer(self)
                    self._skill_debounce_timer.setSingleShot(True)
                    self._skill_debounce_timer.setInterval(80)
                    self._skill_debounce_timer.timeout.connect(_rebuild_with_skills)
                if self._skill_debounce_timer.isActive():
                    self._skill_debounce_timer.stop()
                self._skill_debounce_timer.start()
            return _on_click

        def _rebuild_with_skills():
            """合并升级品和技能修饰符并触发数据重算（仅刷新下方数据区）"""
            _cur_ship_type = ""
            if hasattr(self, '_current_analyzed') and self._current_analyzed:
                _cb = self._current_analyzed.get("config_bar", {})
                _cur_ship_type = _cb.get("shiptype_en", "") if isinstance(_cb, dict) else ""
            all_mods: dict = {}
            # 升级品修饰符
            for m in getattr(self, '_selected_mods', {}).values():
                mod_dict = m.get("modifiers", {})
                for k, v in mod_dict.items():
                    if isinstance(v, dict):
                        v = v.get(_cur_ship_type) or next((x for x in v.values() if isinstance(x, (int, float))), 1.0)
                    if k not in all_mods:
                        all_mods[k] = v
                    else:
                        try:
                            ev_f, nv_f = float(all_mods[k]), float(v)
                            if k in _ADDITIVE_KEYS_BASE:
                                all_mods[k] = ev_f + nv_f
                            else:
                                all_mods[k] = ev_f * nv_f
                        except (ValueError, TypeError):
                            all_mods[k] = v
            self._refresh_data_only(all_mods if all_mods else None)

        skill_grid = QWidget()
        grid = QGridLayout(skill_grid)
        grid.setContentsMargins(2,2,2,2); grid.setSpacing(2)

        def _rebuild_buttons():
            """完全重建所有技能按钮（清除旧按钮 + 重新创建）"""
            # 清除旧按钮
            while grid.count():
                _item = grid.takeAt(0)
                if _item and _item.widget():
                    _item.widget().deleteLater()
            for _r in range(4):
                skill_btns[_r].clear()
            for _r in range(4):
                selected_tier_spent[_r] = 0

            for row in range(4):
                for col_idx in range(6):
                    skill_data = grid_skills[row][col_idx] if row < len(grid_skills) and col_idx < len(grid_skills[row]) else None
                    sk_key = ""
                    mods = {}
                    icon_name = ""
                    trigger = {}
                    rarity = ""
                    if skill_data:
                        sk_key = skill_data.get('skill_key', '')
                        mods = skill_data.get('modifiers', {})
                        icon_name = skill_data.get('icon_name', '')
                        trigger = skill_data.get('trigger', {})
                        rarity = skill_data.get('rarity', '')
                    else:
                        # 无 DB 数据时从网格映射取图标名
                        for st, skills in _skill_svc._grid_map.items():
                            pos_key = f"{row+1}-{col_idx+1}"
                            if pos_key in skills:
                                icon_name = skills[pos_key]
                                break
                    # 尝试加载图标
                    pix = None
                    if icon_name:
                        icon_path = pic_path(f"skills/{icon_name}.png")
                        pix = QPixmap(icon_path)
                        if pix.isNull():
                            pix = None
                    btn = QPushButton()
                    if pix and not pix.isNull():
                        btn.setIcon(QIcon(pix))
                        btn.setIconSize(QSize(28, 28))
                    else:
                        short = sk_key[:6] if sk_key else f"{row*6+col_idx+1}"
                        btn.setText(short)
                    btn.setCheckable(True)
                    if rarity in ("EPIC", "LEGENDARY"):
                        btn.setStyleSheet(SKILL_BTN)
                        # 左上角 EPIC 标记
                        _epic_pix = QPixmap(pic_path("icon_epic_skill.png"))
                        if not _epic_pix.isNull():
                            _epic_label = QLabel(btn)
                            _epic_pix_scaled = _epic_pix.scaled(14, 14, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            _epic_label.setPixmap(_epic_pix_scaled)
                            _epic_label.setStyleSheet("background:transparent;")
                            _epic_label.setGeometry(0, 0, 14, 14)
                    else:
                        btn.setStyleSheet(SKILL_BTN)
                    # tooltip：查询本地化标题和描述
                    skill_name = ""
                    skill_desc = ""
                    if icon_name and _db:
                        try:
                            lookup_key = icon_name.lower()
                            cur = _db._conn.execute(
                                "SELECT lang_zh FROM name_mappings WHERE category=? AND key_name=?",
                                ("skill_title", lookup_key)
                            )
                            db_row = cur.fetchone()
                            if db_row:
                                skill_name = db_row["lang_zh"]
                            cur = _db._conn.execute(
                                "SELECT lang_zh FROM name_mappings WHERE category=? AND key_name=?",
                                ("skill_desc", lookup_key)
                            )
                            db_row = cur.fetchone()
                            if db_row:
                                skill_desc = db_row["lang_zh"]
                        except Exception:
                            pass
                    if sk_key:
                        title = skill_name if skill_name else sk_key
                        if rarity in ("EPIC", "LEGENDARY"):
                            _tag = {"EPIC": "[强化]", "LEGENDARY": "[传奇]"}.get(rarity, "")
                            title = f'{title} <span style="color:#ff6600; font-weight:normal;">{_tag}</span>'
                        tip_lines = [f'<div style="font-size:11px; line-height:1.4;"><b>{title}</b>']
                        if skill_desc:
                            # 字面 \n（未解析转义）与真实换行符 → 富文本换行
                            _desc = skill_desc.replace("\\n", "<br/>").replace("\n", "<br/>")
                            tip_lines.append(f'<div style="color:#ccc; margin-top:2px;">{_desc}</div>')
                        # 特定技能不做加成词条显示
                        _skip_mod_skills = {"detection_alert", "detection_aiming", "planes_forsage_renewal", "maneuverability", "detection_direction", "depth_charge_bomber_alert", "submarine_danger_alert"}
                        if mods and icon_name not in _skip_mod_skills:
                            tip_lines.append('<hr style="border-color:#444; margin:4px 0;">')
                            for _ml in _format_skill_mod(mods, cur_shiptype):
                                tip_lines.append(f'<div style="color:#aaa; margin-top:2px;">{_ml}</div>')
                        # 触发条件与触发段加成
                        if trigger and trigger.get("triggerType"):
                            ttype = trigger.get("triggerType", "")
                            divider = trigger.get("dividerValue", 1.0)
                            tmods = trigger.get("modifiers", {})
                            if tmods:
                                cond_text = _format_trigger_cond(ttype, divider, trigger)
                                tip_lines.append(f'<div style="color:#ffa; margin-top:2px; font-style:italic;">◇ {cond_text}</div>')
                                for _tl in _format_skill_mod(tmods, cur_shiptype):
                                    tip_lines.append(f'<div style="color:#aaa; margin-top:1px; padding-left:10px;">{_tl}</div>')
                                # atbaHeat：显示升温/冷却详细描述
                                if ttype == "atbaHeat":
                                    heat = trigger.get("heatInterpolator", [])
                                    cdelay = trigger.get("coolingDelay", 0)
                                    penalty = trigger.get("changePriorityTargetPenalty", 1.0)
                                    if len(heat) >= 2:
                                        _full_time = heat[-1][0]
                                        _full_pct = int(heat[-1][1] * 100)
                                        tip_lines.append(f'<div style="color:#aaa; margin-top:1px; font-size:10px;">对副炮优先目标连续射击逐渐提升准度</div>')
                                        tip_lines.append(f'<div style="color:#aaa; margin-top:1px; font-size:10px;">  达到最高效率需 {_full_time:.0f} 秒（{_full_pct}%）</div>')
                                        if cdelay > 0:
                                            tip_lines.append(f'<div style="color:#aaa; margin-top:1px; font-size:10px;">  停火 {cdelay:.0f} 秒后开始降温</div>')
                                        if penalty < 1.0:
                                            tip_lines.append(f'<div style="color:#aaa; margin-top:1px; font-size:10px;">  切换目标保留 {penalty*100:.0f}% 累积准度</div>')
                                # activationOnDetectTrigger：显示持续时间
                                if ttype == "activationOnDetectTrigger":
                                    _dur = trigger.get("duration", 0)
                                    if _dur > 0:
                                        tip_lines.append(f'<div style="color:#aaa; margin-top:1px; font-size:10px;">被发现后 {_dur:.0f} 秒内，降低敌人对您的射击准度</div>')
                                # activationOnRibbons / activationOnBuoyancyState 的具体细节
                                # 已合并进 _format_trigger_cond 的触发条件行，避免重复显示
                        tip_lines.append('</div>')
                        btn.setToolTip("".join(tip_lines))
                        btn.setToolTipDuration(10000)
                    else:
                        btn.setToolTip(f"{cur_shiptype} 第{row+1}层 第{col_idx+1}列 (消耗{row+1}点)")
                    btn.clicked.connect(_make_skill_click(row, col_idx, btn, mods, trigger))
                    skill_btns[row].append(btn)
                    grid.addWidget(btn, row, col_idx)

            # 初始状态：1层可选，2/3/4层锁定
            _update_skill_state()
            # 恢复之前选中的技能状态
            if hasattr(self, '_selected_skill_mods'):
                for _r in range(4):
                    for _c in range(6):
                        _pos = f"{_r}-{_c}"
                        if _pos in self._selected_skill_mods and _r < len(skill_btns) and _c < len(skill_btns[_r]):
                            skill_btns[_r][_c].setChecked(True)
                            selected_tier_spent[_r] += TIER_COST[_r]
            _update_skill_state()

        cl.addWidget(skill_grid)
        skill_grid.setMaximumWidth(380)
        _rebuild_buttons()

        # ── 舰长切换：更新天赋显示 ──
        def _on_crew_changed(idx: int):
            nonlocal _default_pcol
            # 如果选到分隔项，跳到下一个有效项
            if 0 <= idx < len(self._crew_data) and self._crew_data[idx] is None:
                # 尝试向后找有效项
                for ni in range(idx + 1, len(self._crew_data)):
                    if self._crew_data[ni] is not None:
                        self._crew_combo.blockSignals(True)
                        self._crew_combo.setCurrentIndex(ni)
                        self._crew_combo.blockSignals(False)
                        return
                # 向后没有，向前找
                for pi in range(idx - 1, -1, -1):
                    if self._crew_data[pi] is not None:
                        self._crew_combo.blockSignals(True)
                        self._crew_combo.setCurrentIndex(pi)
                        self._crew_combo.blockSignals(False)
                        return
                return
            # ── 根据所选舰长更新技能网格稀有度 ──
            _new_pcol = "PCOL001_CommonCrewSkills"
            if _db and _db._conn and 0 <= idx < len(self._crew_data):
                _cd = self._crew_data[idx]
                if _cd is not None and _cd['crew_id'] not in ('__elite__', '__custom__', '__standard__'):
                    try:
                        _r = _db._conn.execute(
                            "SELECT skills_container FROM crew_basic_info WHERE version_code=? AND crew_id=?",
                            (_db.get_latest_version_code() or "", _cd['crew_id'])
                        ).fetchone()
                        if _r and _r['skills_container']:
                            _new_pcol = _r['skills_container']
                    except Exception:
                        pass
            if _new_pcol != _default_pcol:
                _default_pcol = _new_pcol
                # 重建 grid_skills
                _new_grid = _skill_svc.get_grid_skills(ship_cn, container_id=_default_pcol, ship_type_en=cur_shiptype) if ship_cn else []
                grid_skills[:] = _new_grid
                # 对 elite/custom 应用 EPIC 覆盖
                if 0 <= idx < len(self._crew_data):
                    _cd = self._crew_data[idx]
                    if _cd and _cd['crew_id'] in ('__elite__', '__custom__'):
                        _cached_cfg = DetailPanel._crew_custom_cache.get(_cd['crew_id'], {})
                        self._apply_epic_overrides(grid_skills, _cached_cfg.get("epic", []),
                                                    skill_svc=_skill_svc, ship_type_en=cur_shiptype)
                # 重建按钮（tooltip 数据已变）
                _rebuild_buttons()
            else:
                # PCOL 未变但仍需刷新按钮样式（如首次选中传奇舰长时）
                DetailPanel._refresh_epic_overlays(skill_btns, grid_skills, SKILL_BTN)
            # 清除旧天赋按钮
            while self._us_layout.count():
                w = self._us_layout.takeAt(0)
                if w and w.widget():
                    w.widget().deleteLater()
            if idx < 0 or idx >= len(self._crew_data):
                return
            cd = self._crew_data[idx]
            if cd is None:
                return
            if cd['crew_id'] in ('__elite__', '__custom__'):
                self._crew_customize_btn.setEnabled(True)
                self._crew_customize_btn.setToolTip("自定义舰长技能/天赋")
                return  # 精英统一/自定义不显示天赋
            else:
                self._crew_customize_btn.setEnabled(False)
                self._crew_customize_btn.setToolTip("仅精英舰长和自定义稀有舰长可自定义技能")
            if not (cd['is_unique'] and cd.get('unique_skill_count', 0) > 0):
                return
            # 查询该传奇舰长的天赋
            if _db and _db._conn:
                try:
                    cur = _db._conn.execute("""
                        SELECT skill_key, trigger_type, max_trigger_num,
                               effects_json, icon_path,
                               trigger_achievement, trigger_damage_num,
                               trigger_damage_type, trigger_ribbon_types, trigger_ribbons_num,
                               damage_percent_threshold
                        FROM crew_unique_skills
                        WHERE version_code=? AND crew_id=?
                        ORDER BY sort_index
                    """, (_db.get_latest_version_code() or "", cd['crew_id']))
                    skills = cur.fetchall()
                    if skills:
                        from models.name_mapping import Mapping as NMAP
                        # 取MODIFIER_MAP方便效果翻译
                        _mod_map = getattr(NMAP, 'MODIFIER_MAP', {})
                        _ribbon_map = getattr(NMAP, 'RIBBON_MAP', {})
                        _trigger_map = getattr(NMAP, 'TRIGGER_TYPE_MAP', {})
                        _achievement_map = getattr(NMAP, 'ACHIEVEMENT_MAP', {})
                        _damage_map = getattr(NMAP, 'DAMAGE_TYPE_MAP', {})

                        def _build_trigger_desc(sk_row, trig_type, trig_map, rib_map):
                            """构建触发条件说明"""
                            tzh = trig_map.get(trig_type, trig_type or "?")
                            if trig_type == "achievement":
                                ach = sk_row['trigger_achievement'] or ""
                                # 尝试从成就映射取中文名
                                ach_zh = _achievement_map.get(ach, ach)
                                return f"获得 {ach_zh} 成就触发"
                            elif trig_type == "ribbons":
                                try:
                                    types = json.loads(sk_row['trigger_ribbon_types']) if isinstance(sk_row['trigger_ribbon_types'], str) else (sk_row['trigger_ribbon_types'] or [])
                                except Exception:
                                    types = []
                                rnames = [rib_map.get(str(t), str(t)) for t in types]
                                num = sk_row['trigger_ribbons_num'] or ""
                                return f"获得 {num} 个{'/'.join(rnames)} 勋带触发"
                            elif trig_type == "damage":
                                dmg = sk_row['trigger_damage_num'] or ""
                                dmg_zh = _damage_map.get(str(sk_row['trigger_damage_type'] or ""), "")
                                label = f"受到 {dmg/10000:.0f}万"
                                if dmg_zh:
                                    label += f" ({dmg_zh})"
                                return label + " 伤害时触发"
                            elif trig_type == "health":
                                thr = sk_row['damage_percent_threshold']
                                if thr:
                                    return f"战舰血量低于 {thr*100:.0f}% 时触发"
                                return "受到伤害导致血量降低时触发"
                            elif trig_type == "enemyVehiclesDead":
                                return f"敌方舰艇被击沉时触发"
                            elif trig_type == "rageMode":
                                return f"激活作战指令时触发"
                            return tzh

                        def _format_effect(effect_key, effect_val, mod_map, cur_st):
                            """格式化一条效果描述（cur_st=当前舰船种类）"""
                            lines = []
                            is_level = effect_val.get("levelDependent", False)
                            for k, v in effect_val.items():
                                if k in ("uniqueType", "percentTalent", "levelDependent", "workTime"):
                                    continue
                                zh = mod_map.get(k, k)
                                is_pct = effect_val.get("percentTalent", False)
                                if isinstance(v, dict):
                                    # 按舰种区分（如 visibilityDistCoeff）
                                    if cur_st and cur_st in v:
                                        sv = v[cur_st]
                                        _add_talent_line(lines, zh, sv, is_pct, mod_key=k)
                                    else:
                                        for skey, sv in v.items():
                                            if isinstance(sv, (int, float)):
                                                _add_talent_line(lines, f"{zh} ({skey})", sv, is_pct, mod_key=k)
                                                break
                                else:
                                    _add_talent_line(lines, zh, v, is_pct, mod_key=k)
                            if is_level:
                                lines.insert(0, '<div style="color:#888; font-size:11px;">该天赋作用时间等于战舰等级</div>')
                            return "\n".join(lines) if lines else None

                        def _add_talent_line(ln, label, v, is_pct, mod_key=""):
                            if isinstance(v, bool):
                                ln.append(f"{'启用' if v else ''} {label}")
                            elif isinstance(v, (int, float)):
                                if is_pct:
                                    from models.name_mapping import Mapping as _NMAP_FMT
                                    ft = _NMAP_FMT.format_modifier(mod_key or "", v, color=True)
                                    if ft:
                                        ln.append(ft + " " + label)
                                elif isinstance(v, float) and 0.5 <= v <= 2.0:
                                    ft = _NMAP_FMT.format_modifier(mod_key or "", v, color=True)
                                    if ft:
                                        ln.append(ft + " " + label)
                                else:
                                    ln.append(f"{label} {v:+.0f}" if v else f"{label} {v:.0f}")

                        # 老版本(v3.2.2-test1)样式：固定深色底+黄色文字
                        UNIQUE_BTN = """
                            QPushButton { background:#1a1a1a; border:2px solid #ffc107;
                                          border-radius:6px; min-width:52px; min-height:52px;
                                          max-width:52px; max-height:52px;
                                          font-size:9px; color:#ffc107; padding:0px; }
                            QPushButton:hover { background:#2a2a2a; border-color:#ffd54f; }
                        """
                        for sk in skills:
                            skey = sk['skill_key']
                            ttype = sk['trigger_type']
                            icon_path = sk['icon_path'] or ""
                            btn = QPushButton()
                            btn.setStyleSheet(UNIQUE_BTN)
                            btn.setCheckable(False)
                            # 如果有图标，显示图片
                            if icon_path:
                                pix = QPixmap(icon_path)
                                if pix.isNull(): pix = None
                                if not pix.isNull():
                                    btn.setIcon(QIcon(pix))
                                    btn.setIconSize(QSize(22, 22))
                            else:
                                # 无图标时显示文字缩写
                                short = skey.split('_')[-1] if '_' in skey else skey[:6]
                                label = short
                                if sk['max_trigger_num']:
                                    label += f"\n×{sk['max_trigger_num']}"
                                btn.setText(label)

                            # ── 构建富文本 tooltip ──
                            tip_lines = ['<div style="font-size:12px; line-height:1.5;">']

                            # 触发条件
                            trigger_line = _build_trigger_desc(
                                sk, ttype, _trigger_map, _ribbon_map
                            )
                            tip_lines.append(
                                f'<div style="color:#ffc107; font-weight:bold; '
                                f'margin-bottom:4px;">▸ {trigger_line}</div>'
                            )

                            # 效果列表
                            try:
                                eff = json.loads(sk['effects_json']) if sk['effects_json'] else {}
                            except Exception:
                                eff = {}
                            if eff:
                                tip_lines.append(
                                    '<div style="color:#aaa; margin-top:4px;">效果：</div>'
                                )
                                for ek, ev in eff.items():
                                    if not isinstance(ev, dict):
                                        continue
                                    desc = _format_effect(ek, ev, _mod_map, cur_shiptype)
                                    if desc:
                                        for _line in desc.split("\n"):
                                            tip_lines.append(
                                                f'<div style="color:#ddd; padding-left:8px;">{_line}</div>'
                                            )

                            # 触发次数
                            if sk['max_trigger_num']:
                                tip_lines.append(
                                    f'<div style="color:#888; font-size:11px; '
                                    f'margin-top:4px;">每场最多触发 {sk["max_trigger_num"]} 次</div>'
                                )

                            tip_lines.append('</div>')
                            btn.setToolTip("".join(tip_lines))
                            self._us_layout.insertWidget(self._us_layout.count() - 1, btn)
                except Exception as _tal_e:
                    import traceback
                    from app.signals import bus
                    bus.log_message.emit(f"[天赋] {cd.get('crew_id','?')}: {_tal_e} | {traceback.format_exc()}")

        # 保存基础样式表，选中颜色变更时重设
        _combo_base_qss = self._crew_combo.styleSheet()
        def _sync_combo_color():
            _idx = self._crew_combo.currentIndex()
            _item = _model.item(_idx)
            if _item:
                _brush = _item.foreground()
                _is_default = _item.data(Qt.ItemDataRole.ForegroundRole) is None
                if _is_default:
                    # 未显式设置前景色的项（如"标准舰长"）→ 使用主题文字色，避免深色下变黑
                    _color = theme["text"]
                elif _brush is not None:
                    _color = _brush.color().name()
                else:
                    _color = theme["text"]
                self._crew_combo.setStyleSheet(_combo_base_qss + f"\nQComboBox {{ color: {_color}; }}")
        self._crew_combo.currentIndexChanged.connect(_on_crew_changed)
        self._crew_combo.currentIndexChanged.connect(_sync_combo_color)
        # 默认选中标准舰长
        if self._crew_combo.count() > 0:
            _default_idx = 0
            for _i, _cd in enumerate(self._crew_data):
                if _cd is not None and _cd['crew_id'] == '__standard__':
                    _default_idx = _i
                    break
            self._crew_combo.setCurrentIndex(_default_idx)

        # ── 自定义按钮 ──
        def _open_customize():
            try:
                from ui.crew_customize_dialog import CrewCustomizeDialog
                idx = self._crew_combo.currentIndex()
                if idx < 0 or idx >= len(self._crew_data):
                    return
                cd = self._crew_data[idx]
                if cd is None:
                    return
                # 读取已有配置（内存缓存优先，文件作为持久化后备）
                _cfg_key = cd['crew_id'] if cd['crew_id'] in ('__elite__', '__custom__') else self._current_filename
                _cached = DetailPanel._crew_custom_cache.get(_cfg_key)
                if _cached is not None:
                    _existing_epic = _cached.get("epic", [])
                    _existing_talent = _cached.get("talent")
                else:
                    _existing_epic = []
                    _existing_talent = None
                dlg = CrewCustomizeDialog(cd, db_nation, self,
                                          ship_type_cn=ship_cn, ship_type_en=cur_shiptype,
                                          epic_skills=_existing_epic,
                                          selected_talent=tuple(_existing_talent) if _existing_talent else None)
                if dlg.exec():
                    # 仅保存到内存缓存（切换舰船时自动清空，不持久化到文件）
                    _entry = {"epic": dlg.epic_skills, "talent": dlg.selected_talent}
                    DetailPanel._crew_custom_cache[_cfg_key] = _entry
                    # 重建技能网格
                    _default_pcol = "PCOL001_CommonCrewSkills"
                    _new_grid = _skill_svc.get_grid_skills(ship_cn, container_id=_default_pcol, ship_type_en=cur_shiptype) if ship_cn else []
                    grid_skills[:] = _new_grid
                    if cd['crew_id'] in ('__elite__', '__custom__'):
                        self._apply_epic_overrides(grid_skills, dlg.epic_skills,
                                                    skill_svc=_skill_svc, ship_type_en=cur_shiptype)
                    # 完全重建技能按钮（tooltip 跟随 EPIC 数据自动更新）
                    _rebuild_buttons()
                    DetailPanel._refresh_epic_overlays(skill_btns, grid_skills, SKILL_BTN)
                    # 刷新数据显示（含天赋修饰符）
                    _talent_mods: dict = {}
                    if dlg.selected_talent and _db and _db._conn:
                        _t_crew, _t_skill = dlg.selected_talent[0], dlg.selected_talent[1]
                        try:
                            _tcur = _db._conn.execute(
                                "SELECT effects_json FROM crew_unique_skills WHERE version_code=? AND crew_id=? AND skill_key=?",
                                (_db_vc, _t_crew, _t_skill)
                            )
                            _trow = _tcur.fetchone()
                            if _trow and _trow['effects_json']:
                                import json
                                _teff = json.loads(_trow['effects_json'])
                                for _ek, _ev in _teff.items():
                                    if not isinstance(_ev, dict):
                                        continue
                                    _is_pct = _ev.get('percentTalent', False)
                                    for _sk, _sv in _ev.items():
                                        if _sk in ('percentTalent', 'uniqueType', 'levelDependent', 'planeSpawnTime', 'value', 'v'):
                                            continue
                                        if isinstance(_sv, dict):
                                            if cur_shiptype and _sv.get(cur_shiptype) is not None:
                                                _sv = _sv[cur_shiptype]
                                            else:
                                                for _x in _sv.values():
                                                    if isinstance(_x, (int, float)):
                                                        _sv = _x
                                                        break
                                                    else:
                                                        continue
                                        if not isinstance(_sv, (int, float)):
                                            continue
                                        if _is_pct:
                                            _pct = (_sv - 1.0) * 100 if _sv < 2.0 else _sv * 100
                                            _talent_mods[_sk] = 1.0 + _pct / 100.0
                                        else:
                                            _talent_mods[_sk] = _sv
                        except Exception:
                            pass
                    self._refresh_data_only(_talent_mods if _talent_mods else None)
                    # 刷新天赋显示按钮
                    while self._us_layout.count():
                        _w = self._us_layout.takeAt(0)
                        if _w and _w.widget():
                            _w.widget().deleteLater()
                    if dlg.selected_talent and _db and _db._conn:
                        try:
                            _t_crew2, _t_skill2 = dlg.selected_talent[0], dlg.selected_talent[1]
                            _tcur2 = _db._conn.execute("""
                                SELECT skill_key, trigger_type, max_trigger_num, effects_json, icon_path
                                FROM crew_unique_skills WHERE version_code=? AND crew_id=? AND skill_key=?
                            """, (_db_vc, _t_crew2, _t_skill2))
                            _trow2 = _tcur2.fetchone()
                            if _trow2:
                                from pathlib import Path as _P
                                from PySide6.QtGui import QPixmap as _QP, QIcon as _QI
                                from PySide6.QtCore import QSize as _QS
                                _tbtn = QPushButton()
                                _tbtn.setStyleSheet(theme.qss("""
                                    QPushButton { background:@panel_alt@; border:2px solid #ffc107;
                                                  border-radius:6px; min-width:52px; min-height:52px;
                                                  max-width:52px; max-height:52px;
                                                  font-size:9px; color:#ffc107; padding:0px; }
                                    QPushButton:hover { background:@hover_bg@; border-color:#ffd54f; }
                                """))
                                _tpath = _trow2['icon_path'] or ""
                                if _tpath and _P(_tpath).exists():
                                    _tpix = _QP(_tpath)
                                    if not _tpix.isNull():
                                        _tbtn.setIcon(_QI(_tpix))
                                        _tbtn.setIconSize(_QS(22, 22))
                                _tbtn.setToolTip(f"已选天赋：{_trow2['skill_key']}")
                                self._us_layout.addWidget(_tbtn)
                        except Exception:
                            pass
            except Exception as e:
                import traceback
                from app.signals import bus
                bus.log_message.emit(f"⚠️ 自定义配置异常: {e}\n{traceback.format_exc()}")

        self._crew_customize_btn.clicked.connect(_open_customize)
        cl.addStretch()
        layout.addWidget(col, stretch=1)


    def _build_lesta_signal_column(self, config, _col, layout):
        """Lesta 信号旗列：6 槽位 + 选择面板（方案 C 迁移）。"""
        col, cl = _col("信号旗")
        signal_flags_dir = pic_path("signal_flags")
        slot_types_dir = pic_path("signal_flags/slot_types")
        signal_slots = config.get("signal_slots", [])
        # 老版本(v3.2.2-test1)样式：固定深色底+浅色文字，图标清晰可读
        SIG_BTN = """
            QPushButton { background: #3a3a3a; border: 1px solid #555;
            border-radius: 4px; padding: 0; }
            QPushButton:hover { background: #4a4a4a; border-color: #1a73e8; }
            QPushButton:checked { background: #4a4a4a; border: 2px solid #1a73e8; }
        """
        from models.name_mapping import Mapping as _NM

        def _fmt_mod(mk, mv):
            """格式化修饰符显示值"""
            cn = _NM.MODIFIER_MAP.get(mk, mk)
            if isinstance(mv, dict):
                _st = config.get("shiptype_en", "") or config.get("shiptype", "")
                mv = mv.get(_st) or next((v for v in mv.values() if isinstance(v, (int, float))), 0)
            if isinstance(mv, (int, float)):
                ft = _NM.format_modifier(mk, mv, color=True)
                if ft:
                    return f"{cn}: {ft}"
            return f"{cn}: {mv}"

        # 恢复信号旗选择的辅助函数
        def _restore_flag(btn, flag_data, fd_dir):
            img_key = flag_data.get("image_key", flag_data['mod_id'])
            flag_img = f"{fd_dir}/{img_key}.png"
            btn.setChecked(True)
            pix = QPixmap(flag_img)
            if not pix.isNull():
                btn.setIcon(QIcon(pix.scaled(36,36,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
                btn.setIconSize(QSize(36,36))
            btn.setText("")
            mods_str = ""
            if flag_data.get("modifiers"):
                items = []
                for mk, mv in flag_data["modifiers"].items():
                    items.append(_fmt_mod(mk, mv))
                if items:
                    mods_str = "\n" + "\n".join(items)
            btn.setToolTip(_NM.rich_tooltip(f"{flag_data.get('name','')}{mods_str}\n{flag_data.get('label','')}"))

        # 顶部：6个槽位按钮
        slot_grid = QWidget()
        grid = QGridLayout(slot_grid)
        grid.setContentsMargins(0,0,0,0); grid.setSpacing(4)
        slot_btns: list[QPushButton] = []
        for si, slot in enumerate(signal_slots):
            slot_label = slot.get('label', '')
            slot_img = f"{slot_types_dir}/Param{si:03d}_SlotType.png"
            btn = QPushButton()
            btn.setFixedSize(40, 40)
            btn.setCheckable(True)
            btn.setStyleSheet(SIG_BTN)
            btn.setToolTip(f"槽{si+1}: {slot_label}")
            pix = QPixmap(slot_img)
            if not pix.isNull():
                btn.setIcon(QIcon(pix.scaled(36,36,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
                btn.setIconSize(QSize(36,36))
            else:
                btn.setText("⬜")
            slot_btns.append(btn)
            grid.addWidget(btn, 0, si, Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(f"槽{si+1}")
            lbl.setStyleSheet(theme.qss("font-size:8px;color:@text_hint@;"))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(lbl, 1, si, Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(slot_grid)

        # 信号旗选择面板：预先为每个槽位创建一页
        flag_stack = QStackedWidget()
        flag_stack.setVisible(False)
        flag_stack.setStyleSheet(theme.qss("QStackedWidget{background:@panel_alt@;border:1px solid @border@;border-radius:4px;max-height:300px;}"))
        flag_stack.setMaximumWidth(220)
        flag_stack.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        _active_slot = [-1]  # 当前展开的槽位索引，-1=无
        # 老版本(v3.2.2-test1)样式：固定深色底+浅色文字，图标清晰可读
        MENU_BTN = """
            QPushButton { background: #3a3a3a; border: none;
            border-radius: 3px; padding: 1px 4px; text-align: left;
            font-size: 10px; color: #ddd; min-height: 18px; }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton:checked { background: #1a73e8; }
        """
        from models.name_mapping import Mapping as _NM

        # 恢复之前保存的信号旗选择状态
        self._signal_slot_btns = slot_btns
        for si, btn in enumerate(slot_btns):
            if si in self._selected_signal_flags:
                fd = self._selected_signal_flags[si]
                _restore_flag(btn, fd, signal_flags_dir)

        # 每个槽位一页（纵排菜单）
        for si, slot in enumerate(signal_slots):
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(2,2,2,2); pl.setSpacing(1)
            flags = slot.get("flags", [])
            slot_label = slot.get("label", "")
            slot_btn = slot_btns[si]

            # "不使用" 选项
            none_btn = QPushButton()
            none_btn.setStyleSheet(MENU_BTN)
            none_btn.setIcon(QIcon())  # 清除图标
            none_btn.setText("  ✕  不使用")
            none_btn.setToolTip("清除该槽位的信号旗")
            none_btn.clicked.connect(lambda checked=False, b=slot_btn, idx=si, st_dir=slot_types_dir, lb=slot_label: (
                _clear_signal_flag(b, idx, st_dir, lb),
                flag_stack.setVisible(False),
                _active_slot.__setitem__(0, -1)
            ))
            pl.addWidget(none_btn)

            for f in flags:
                flag_img = f"{signal_flags_dir}/{f.get('image_key', f['mod_id'])}.png"
                disp_name = f.get("name", f['mod_id'])
                # tooltip：加成效果
                mods_str = ""
                if f.get("modifiers"):
                    items = []
                    for mk, mv in f["modifiers"].items():
                        items.append(_fmt_mod(mk, mv))
                    if items:
                        mods_str = "\n" + "\n".join(items)
                mitem = QPushButton()
                mitem.setStyleSheet(MENU_BTN)
                pixf = QPixmap(flag_img)
                if not pixf.isNull():
                    mitem.setIcon(QIcon(pixf.scaled(24,24,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
                    mitem.setIconSize(QSize(24,24))
                # 显示名称 + 稀有度
                mitem.setText(f"  {disp_name}")
                mitem.setToolTip(_NM.rich_tooltip(f"{disp_name}\n{mods_str}" if mods_str else disp_name))
                fd = f
                mitem.clicked.connect(lambda checked=False, b=slot_btn, fdata=fd, lb=slot_label, fd_dir=signal_flags_dir: (
                    _apply_signal_flag(b, fdata, lb, fd_dir),
                    flag_stack.setVisible(False),
                    _active_slot.__setitem__(0, -1)
                ))
                pl.addWidget(mitem)
            pl.addStretch()
            flag_stack.addWidget(page)

        # 点击槽位切换选择面板（再次点击同一个关闭，点击其他自动切换）
        def _on_slot_click(idx):
            # 取消其他槽位的选中状态
            for bi, b in enumerate(slot_btns):
                if bi != idx:
                    b.setChecked(False)
            if _active_slot[0] == idx and flag_stack.isVisible():
                flag_stack.setVisible(False)
                _active_slot[0] = -1
                slot_btns[idx].setChecked(False)
            else:
                flag_stack.setCurrentIndex(idx)
                # 在按钮下方弹出
                btn = slot_btns[idx]
                pos = btn.mapToGlobal(btn.rect().bottomLeft())
                flag_stack.move(pos)
                flag_stack.setVisible(True)
                _active_slot[0] = idx
        for si in range(len(signal_slots)):
            slot_btns[si].clicked.connect(lambda checked, idx=si: _on_slot_click(idx))

        # 点击外部关闭弹出菜单
        flag_stack.installEventFilter(self)
        self._flag_stack = flag_stack

        def _apply_signal_flag(btn, flag_data, slot_label, fd_dir):
            btn.setChecked(True)
            img_key = flag_data.get("image_key", flag_data['mod_id'])
            flag_img = f"{fd_dir}/{img_key}.png"
            pix2 = QPixmap(flag_img)
            if not pix2.isNull():
                btn.setIcon(QIcon(pix2.scaled(36,36,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
                btn.setIconSize(QSize(36,36))
            btn.setText("")
            mods_str = ""
            if flag_data.get("modifiers"):
                items = []
                for mk, mv in flag_data["modifiers"].items():
                    items.append(_fmt_mod(mk, mv))
                if items:
                    mods_str = "\n" + "\n".join(items)
            btn.setToolTip(_NM.rich_tooltip(f"{flag_data.get('name','')}{mods_str}\n{slot_label}"))
            # 存储选择并触发重算
            si = next((i for i, b in enumerate(slot_btns) if b is btn), -1)
            if si >= 0:
                self._selected_signal_flags[si] = flag_data
                _trigger_signal_refresh()

        def _clear_signal_flag(btn, slot_idx, st_dir, slot_label):
            btn.setChecked(False)
            slot_img = f"{st_dir}/Param{slot_idx:03d}_SlotType.png"
            pix3 = QPixmap(slot_img)
            if not pix3.isNull():
                btn.setIcon(QIcon(pix3.scaled(36,36,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
                btn.setIconSize(QSize(36,36))
            btn.setText("")
            btn.setToolTip(f"槽{slot_idx+1}: {slot_label}")
            # 清除选择并触发重算
            if slot_idx in self._selected_signal_flags:
                del self._selected_signal_flags[slot_idx]
                _trigger_signal_refresh()

        def _trigger_signal_refresh():
            """将信号旗修饰符合并到升级品修饰符中一起重算"""
            def _merge_one(mods):
                if not isinstance(mods, dict):
                    return
                for k, v in mods.items():
                    if isinstance(v, dict):
                        v = v.get(_st) or next((x for x in v.values() if isinstance(x, (int, float))), 1.0)
                    if k not in all_mods:
                        all_mods[k] = v
                    else:
                        try:
                            ev_f, nv_f = float(all_mods[k]), float(v)
                            all_mods[k] = ev_f + nv_f if k in _ADDITIVE_KEYS_BASE else ev_f * nv_f
                        except (ValueError, TypeError):
                            all_mods[k] = v

            all_mods = {}
            _st = config.get("shiptype_en", "") or config.get("shiptype", "")
            if hasattr(self, '_selected_mods'):
                for m in self._selected_mods.values():
                    _merge_one(m.get("modifiers", {}))
            for fd in self._selected_signal_flags.values():
                _merge_one(fd.get("modifiers", {}))
            self._refresh_data_only(all_mods if all_mods else None)

        cl.addStretch()
        layout.addWidget(col, stretch=1)
