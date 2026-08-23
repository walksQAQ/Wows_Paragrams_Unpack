"""
WargamingDetailPanel —— Wargaming（WG）服详情面板。

方案 C：UI 按服务器拆分。WG 专属渲染（舰长下拉/技能网格/天赋、信号旗、
消耗品 logic/tacticalParams/auto 角标等）迁移到本类。
"""

from __future__ import annotations

from ui.detail_panel import DetailPanel, _ADDITIVE_KEYS_BASE
import json
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QGridLayout, QPushButton, QLabel,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from utils.theme import theme
from utils.image_paths import pic_path
from services import wg_compat


class WargamingDetailPanel(DetailPanel):
    """Wargaming（WG）服详情面板。"""

    SERVER_KEY = "Wargaming"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wows_type = "Wargaming"



    def _build_wg_commander_column(self, config, _col, layout):
        """WG 舰长技能列：舰长下拉（分类配色）+ 技能网格 + 传奇天赋（方案 C 迁移）。"""
        col, cl = _col("舰长技能")
        # WG 服舰长技能架构：潜艇 4×5、其他舰种 4×6；数据按舰长技能组（crew_skill_groups）直接调取
        from services.skill_service import SkillService as _WG_SkillSvc
        _wsvc = _WG_SkillSvc()
        _cur_st = config.get("shiptype_en", "") or config.get("shiptype", "") or ""
        _ship_cn = _wsvc.get_ship_type_cn(_cur_st)
        _wg_cols = 5 if _cur_st == "Submarine" else 6
        _wg_db = _wsvc._get_db()
        _wg_vc = (_wg_db.get_latest_version_code() or "") if (_wg_db and _wg_db._conn) else ""
        # 当前舰船原始 nation（entity_registry）
        _nat_raw = ""
        if _wg_db and _wg_db._conn and _wg_vc and config.get("ship_id"):
            try:
                _nr = _wg_db._conn.execute(
                    "SELECT nation FROM entity_registry WHERE version_code=? AND entity_id=?",
                    (_wg_vc, config.get("ship_id"))).fetchone()
                _nat_raw = _nr["nation"] if _nr else ""
            except Exception:
                _nat_raw = ""
        # 舰长列表（该国 + Common，排除 Template/无名字），
        # 分类：is_unique→传奇、有强化技能(has_epic)→强化、其余→普通
        _crew_list: list = []
        _def_crew = ""
        if _wg_db and _wg_db._conn and _wg_vc:
            try:
                _q = ("SELECT c.crew_id, c.person_name, c.is_unique, "
                      "COALESCE(n.lang_zh, c.person_name, c.crew_id) AS disp, "
                      "(SELECT COUNT(*) FROM crew_unique_skills us "
                      " WHERE us.version_code=c.version_code AND us.crew_id=c.crew_id) AS us_cnt, "
                      "EXISTS(SELECT 1 FROM crew_skill_groups g "
                      "WHERE g.version_code=c.version_code AND g.crew_id=c.crew_id AND g.is_epic=1) AS has_epic "
                      "FROM crew_basic_info c "
                      "LEFT JOIN name_mappings n ON n.id = c.display_name_id "
                      "WHERE c.version_code=? AND c.person_name!='' "
                      "AND c.crew_id NOT LIKE '%Template%' AND (c.nation=? OR c.nation='Common') "
                      "ORDER BY c.nation, c.crew_id")
                _crew_list = [(r["crew_id"], r["disp"], bool(r["is_unique"]), int(r["us_cnt"]), bool(r["has_epic"]))
                              for r in _wg_db._conn.execute(_q, (_wg_vc, _nat_raw)).fetchall()]
                _dr = _wg_db._conn.execute(
                    "SELECT crew_id FROM crew_basic_info WHERE version_code=? AND nation=? "
                    "AND person_name='' AND crew_id LIKE '%DefaultCrew%' LIMIT 1",
                    (_wg_vc, _nat_raw)).fetchone()
                _def_crew = _dr["crew_id"] if _dr else ""
                if not _def_crew and _crew_list:
                    _def_crew = _crew_list[0][0]
            except Exception:
                _crew_list, _def_crew = [], ""
        WG_SKILL_BTN = """
            QPushButton { background:#2a2a2a; border:1px solid #444; border-radius:4px;
                          min-width:30px; min-height:30px; max-width:30px; max-height:30px;
                          font-size:8px; color:#ccc; padding:0px; }
            QPushButton:hover { background:#3a3a3a; border-color:#1a73e8; }
        """
        wg_grid = QWidget()
        wgl = QGridLayout(wg_grid)
        wgl.setContentsMargins(0, 0, 0, 0); wgl.setSpacing(3)
        wgl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from models.name_mapping import Mapping as _NM_WG2
        from PySide6.QtGui import QPixmap as _QPixmap
        from PySide6.QtGui import QIcon as _QI
        from PySide6.QtCore import QSize as _QS
        from PySide6.QtWidgets import QLabel as _Qlbl
        from PySide6.QtWidgets import QComboBox as _QComboBox
        _WG_TRIGGER_COND = {
            "activeAirDefense": "当防空炮开火时",
            "entityIsVisibleTrigger": "当战舰被敌方发现时",
            "entityIsInvisibleTrigger": "当战舰未被敌方发现时",
            "activationOnBurnFlood": "战舰上每个活跃的火源和进水点",
            "activationOnConsumable": "当消耗品激活时",
            "activationOnBattery": "当使用电池动力时",
            "potentialDamageRatio": "每积累潜在伤害时",
            "visibleEnemyWithinGsTrigger": "当副炮射程内存在敌军战舰时",
            "atbaHeat": "存在手动选择的副炮优先目标时",
            "enemyWithinVisibilityTrigger": "当标准被侦查范围内有敌方战舰时",
            "EnemiesNotLessThanAlliesWithinGMTrigger": "当主炮射程内友方战舰不多于敌方战舰时",
            "activationOnDetectTrigger": "被敌方发现时",
        }

        # 天赋区域（传奇舰长 UniqueSkills）
        _wg_talent_container = QWidget()
        _wg_talent_layout = QHBoxLayout(_wg_talent_container)
        _wg_talent_layout.setContentsMargins(0, 0, 0, 0); _wg_talent_layout.setSpacing(4)
        _wg_talent_layout.addStretch()
        _WG_UNIQUE_BTN = """
            QPushButton { background:#1a1a1a; border:2px solid #ffc107;
                          border-radius:6px; min-width:52px; min-height:52px;
                          max-width:52px; max-height:52px;
                          font-size:9px; color:#ffc107; padding:0px; }
            QPushButton:hover { background:#2a2a2a; border-color:#ffd54f; }
        """

        def _wg_rebuild(crew_id: str):
            """按所选舰长重建技能网格（数据取自该舰长技能组）"""
            while wgl.count():
                _it = wgl.takeAt(0)
                if _it and _it.widget():
                    _it.widget().deleteLater()
            # ── 传奇舰长天赋（UniqueSkills → crew_unique_skills）──
            while _wg_talent_layout.count():
                _tw = _wg_talent_layout.takeAt(0)
                if _tw and _tw.widget():
                    _tw.widget().deleteLater()
            if crew_id and _wg_db and _wg_db._conn and _wg_vc:
                try:
                    _ts = _wg_db._conn.execute(
                        "SELECT skill_key, trigger_type, max_trigger_num, effects_json, icon_path "
                        "FROM crew_unique_skills WHERE version_code=? AND crew_id=? ORDER BY sort_index",
                        (_wg_vc, crew_id)).fetchall()
                except Exception:
                    _ts = []
                if _ts:
                    _trig_map = getattr(_NM_WG2, 'TRIGGER_TYPE_MAP', {})
                    _skip_trig = ("GameLogicTrigger", "Action", "Activator", "EventTrigger")
                    _skip_meta = {"uniqueType", "percentTalent", "levelDependent", "workTime",
                                  "fakeUniqueType", "useShipTierAsWorkTime", "speedCoefUI", "type",
                                  "battleGroup", "isUnlimited", "maxTriggerNum", "sortIndex",
                                  "startEnabled", "triggerAllowedShips", "triggerJoinRibbons",
                                  "triggerRibbonsNum", "triggerRibbonsTypes", "triggerType",
                                  "uiFeedbackMessages", "uiTriggerName"}
                    for _tsk in _ts:
                        _tkey = _tsk["skill_key"]
                        _ttype = _tsk["trigger_type"] or ""
                        _icon = _tsk["icon_path"] or ""
                        _tbtn = QPushButton()
                        _tbtn.setStyleSheet(_WG_UNIQUE_BTN)
                        _short = _tkey.split("_")[-1] if "_" in _tkey else _tkey[:6]
                        if _icon:
                            _tp = _QPixmap(_icon)
                            if not _tp.isNull():
                                _tbtn.setIcon(_QI(_tp.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                                _tbtn.setIconSize(_QS(24, 24))
                            else:
                                _tbtn.setText(_short)
                        else:
                            _tbtn.setText(_short)
                        # tooltip：触发条件 + 效果
                        _tip = ['<div style="font-size:12px;line-height:1.5;">']
                        _tcond = _trig_map.get(_ttype, "获得特定勋带时触发" if _ttype == "ribbons" else (_ttype or "触发"))
                        _tip.append(f'<div style="color:#ffc107;font-weight:bold;margin-bottom:4px;">▸ {_tcond}</div>')
                        try:
                            _eff = json.loads(_tsk["effects_json"]) if _tsk["effects_json"] else {}
                        except Exception:
                            _eff = {}
                        _eff_lines = []
                        for _ek, _ev in _eff.items():
                            if not isinstance(_ev, dict) or _ek.startswith(_skip_trig) or _ek in _skip_meta:
                                continue
                            _lvs = sorted(k for k in _ev if k.startswith("level_"))
                            _pairs = []
                            if _lvs:
                                for _lv in _lvs:
                                    _lv_d = _ev[_lv] if isinstance(_ev[_lv], dict) else {}
                                    for _k2, _v2 in _lv_d.items():
                                        if _k2 not in _skip_meta:
                                            _pairs.append((_k2, _v2))
                            else:
                                for _k2, _v2 in _ev.items():
                                    if _k2 not in _skip_meta:
                                        _pairs.append((_k2, _v2))
                            for _k2, _v2 in _pairs:
                                _zh2 = _NM_WG2.MODIFIER_MAP.get(_k2, _k2)
                                if isinstance(_v2, bool):
                                    if _v2:
                                        _eff_lines.append(_zh2)
                                elif isinstance(_v2, float):
                                    _ft = _NM_WG2.format_modifier(_k2, _v2, color=True)
                                    if _ft:
                                        _eff_lines.append(f"{_zh2}: {_ft}")
                                elif isinstance(_v2, int):
                                    _ft = _NM_WG2.format_modifier(_k2, _v2, color=True)
                                    _eff_lines.append(f"{_zh2}: {_ft}" if _ft else _zh2)
                        if _eff_lines:
                            _tip.append('<div style="color:#aaa;margin-top:4px;">效果：</div>')
                            for _el in _eff_lines:
                                _tip.append(f'<div style="color:#ddd;padding-left:8px;">{_el}</div>')
                        _mt = _tsk["max_trigger_num"]
                        if _mt:
                            _tip.append(f'<div style="color:#888;font-size:11px;margin-top:4px;">每场最多触发 {_mt} 次</div>')
                        _tip.append('</div>')
                        _tbtn.setToolTip(_NM_WG2.rich_tooltip("".join(_tip)))
                        _wg_talent_layout.insertWidget(_wg_talent_layout.count() - 1, _tbtn)
            _grid = (_wsvc.get_grid_skills(_ship_cn, container_id="PCOL001_CommonCrewSkills",
                                           ship_type_en=_cur_st, wows_type="Wargaming",
                                           crew_id=crew_id) if _ship_cn else [])
            for _r in range(4):
                for _c in range(_wg_cols):
                    _b = QPushButton()
                    _b.setFixedSize(30, 30)
                    _b.setStyleSheet(WG_SKILL_BTN)
                    _sk = None
                    if _r < len(_grid) and _c < len(_grid[_r]):
                        _sk = _grid[_r][_c]
                    if _sk:
                        _skn = _sk.get("skill_key", "")
                        _icon_name = _sk.get("icon_name", "")
                        # 图标映射：skills/<icon_name>.png，加载失败回退文字缩写
                        _sicon = _QPixmap(pic_path(f"skills/{_icon_name}.png")) if _icon_name else _QPixmap()
                        if not _sicon.isNull():
                            _b.setIcon(_QI(_sicon.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                            _b.setIconSize(_QS(28, 28))
                        else:
                            _b.setText(_skn[:3])
                        # 技能本地化名：name_mappings.skill_title（按 icon_name snake_case 匹配），回退 skill_key
                        _skill_zh = ""
                        if _icon_name and _wg_db and _wg_db._conn:
                            try:
                                _nm_r = _wg_db._conn.execute(
                                    "SELECT lang_zh FROM name_mappings WHERE category='skill_title' AND key_name=?",
                                    (_icon_name.lower(),)).fetchone()
                                if _nm_r:
                                    _skill_zh = _nm_r["lang_zh"]
                            except Exception:
                                pass
                        _tt = [f"<div style='font-weight:bold;'>{_skill_zh or _skn}</div>"]
                        _rar = _sk.get("rarity", "")
                        if _rar in ("EPIC", "LEGENDARY"):
                            _tag = {"EPIC": "[强化]", "LEGENDARY": "[传奇]"}.get(_rar, "")
                            _tt.append(f"<div style='color:#ff6600;'>{_tag}</div>")
                        # 词条属性：中文名 + 格式化数值（bool 项只显示开启名称，list/dict 等非数值跳过）
                        _mods = _sk.get("modifiers") or {}
                        if _mods:
                            _tt.append("<hr style='border-color:#444;margin:4px 0;'>")
                            for _mk, _mv in _mods.items():
                                _zh = _NM_WG2.MODIFIER_MAP.get(_mk, _mk)
                                if isinstance(_mv, bool):
                                    if _mv:
                                        _tt.append(f"<div style='white-space:nowrap;'>{_zh}</div>")
                                    continue
                                if not isinstance(_mv, (int, float)):
                                    continue  # excludedConsumables 等 list 值不显示
                                _val = _NM_WG2.format_modifier(_mk, _mv, color=True)
                                if _val:
                                    _tt.append(f"<div style='white-space:nowrap;'>{_zh}: {_val}</div>")
                        # 触发条件（WG LogicTrigger.triggerType）及触发段加成
                        _trig = _sk.get("trigger") or {}
                        _ttype = _trig.get("triggerType", "")
                        if _ttype:
                            _tcond = _WG_TRIGGER_COND.get(_ttype, _ttype)
                            _tt.append(f"<div style='color:#ffa;margin-top:2px;font-style:italic;'>◇ {_tcond}</div>")
                            for _mk, _mv in (_trig.get("modifiers") or {}).items():
                                _zh = _NM_WG2.MODIFIER_MAP.get(_mk, _mk)
                                if not isinstance(_mv, (int, float)):
                                    continue  # dict/list 等非数值修饰符（如分舰种表）不显示
                                _val = _NM_WG2.format_modifier(_mk, _mv, color=True)
                                if _val:
                                    _tt.append(f"<div style='white-space:nowrap;padding-left:10px;'>{_zh}: {_val}</div>")
                        _b.setToolTip(_NM_WG2.rich_tooltip("".join(_tt)))
                        if _rar in ("EPIC", "LEGENDARY"):
                            _pix = _QPixmap(pic_path("icon_epic_skill.png"))
                            if not _pix.isNull():
                                _el = _Qlbl(_b)
                                _el.setPixmap(_pix.scaled(14, 14, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                                _el.setStyleSheet("background:transparent;")
                                _el.setGeometry(0, 0, 14, 14)
                    else:
                        _b.setEnabled(False)
                    wgl.addWidget(_b, _r, _c)

        # 舰长下拉：分类组（传奇/强化/普通，标准舰长并入普通），按分类配色（同 Lesta）
        from PySide6.QtGui import QStandardItemModel as _QSIM, QStandardItem as _QSIt, QColor as _QCol
        _wg_crew_combo = _QComboBox()
        _wg_model = _QSIM(_wg_crew_combo)
        _cat_order = [("legendary", "传奇舰长", "#ffc107", "★ "),
                      ("epic", "强化舰长", "#26c6da", "◈ "),
                      ("normal", "普通舰长", None, "")]
        _cat_items = {k: [] for k, *_ in _cat_order}
        for _cid, _pname, _uniq, _us_cnt, _epic in _crew_list:
            if _uniq and _us_cnt > 0:
                _cat_items["legendary"].append((_cid, _pname))
            elif _epic:
                _cat_items["epic"].append((_cid, _pname))
            # 其余无强化技能的普通舰长不显示
        for _k, _label, _color, _prefix in _cat_order:
            _items = _cat_items[_k]
            # 普通舰长分类：只保留标准舰长（DefaultCrew），其余无强化技能普通舰长不显示
            if _k == "normal":
                _items = [(_def_crew, "普通舰长")] if _def_crew else []
            # 同 Lesta：无分类标题/分隔线，直接以彩色前缀分组
            for _cid, _pname in _items:
                _it = _QSIt(f"{_prefix}{_pname}")
                if _color:
                    _it.setForeground(_QCol(_color))
                _it.setData(_cid, Qt.ItemDataRole.UserRole)
                _wg_model.appendRow(_it)
        _wg_crew_combo.setModel(_wg_model)
        if _def_crew:
            _di = _wg_crew_combo.findData(_def_crew)
            if _di >= 0:
                _wg_crew_combo.setCurrentIndex(_di)
        _wg_crew_combo.setStyleSheet(theme.qss("QComboBox{font-size:11px;min-height:22px;}"))
        _wg_crew_combo.currentIndexChanged.connect(
            lambda _i: _wg_rebuild(_wg_crew_combo.itemData(_i) or ""))
        cl.addWidget(_wg_crew_combo)
        cl.addWidget(_wg_talent_container)
        cl.addWidget(wg_grid)
        _wg_rebuild(_wg_crew_combo.itemData(_wg_crew_combo.currentIndex()) or "")
        cl.addStretch()
        layout.addWidget(col, stretch=1)

    def _build_wg_signal_column(self, config, _col, layout):
        """WG 信号旗列：14 种信号旗同时显示（方案 C 迁移）。

        可交互：按钮可点击切换启用/禁用，选中旗的 modifiers 参与舰船数据计算
        （多选可叠加）；初始默认不选中任何信号旗（用户手动点选）。
        """
        col, cl = _col("信号旗")
        # WG 服：14 种信号旗同时显示（PCEF010 无加成不显示），每种显示加成属性
        from models.name_mapping import Mapping as _NM_WG
        wg_flags = config.get("signal_flags", [])
        if wg_flags:
            wg_sig_dir = pic_path("signal_flags")
            WG_SIG_BTN = """
                QPushButton { background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; padding: 0; }
                QPushButton:hover { background: #4a4a4a; border-color: #1a73e8; }
                QPushButton:checked { background: #1a73e8; border-color: #1a73e8; }
            """
            def _fmt_wg(mk, mv):
                cn = _NM_WG.MODIFIER_MAP.get(mk, mk)
                if isinstance(mv, dict):
                    _st2 = config.get("shiptype_en", "") or config.get("shiptype", "")
                    mv = mv.get(_st2) or next((v for v in mv.values() if isinstance(v, (int, float))), 1.0)
                try:
                    ft = _NM_WG.format_modifier(mk, float(mv), color=True)
                    return f"{cn}: {ft}" if ft else f"{cn}: {mv}"
                except (ValueError, TypeError):
                    return f"{cn}: {mv}"
            wg_grid = QWidget()
            wgl = QGridLayout(wg_grid)
            wgl.setContentsMargins(0, 0, 0, 0); wgl.setSpacing(4)
            wgl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _st3 = config.get("shiptype_en", "") or config.get("shiptype", "") or ""
            for idx, f in enumerate(wg_flags):
                b = QPushButton()
                b.setFixedSize(36, 36)
                b.setCheckable(True)
                b.setChecked(f.get("mod_id") in self._selected_wg_signal_flags)
                b.setStyleSheet(WG_SIG_BTN)
                img2 = f"{wg_sig_dir}/{f.get('image_key', f['mod_id'])}.png"
                pixf = QPixmap(img2)
                if not pixf.isNull():
                    b.setIcon(QIcon(pixf.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                    b.setIconSize(QSize(30, 30))
                else:
                    b.setText(f['mod_id'])
                lines = [f"<div style='font-weight:bold;'>{f.get('name', f['mod_id'])}（{f['mod_id']}）</div>"]
                fl = f.get("flags", [])
                mod_lines = []
                for mk, mv in f.get("modifiers", {}).items():
                    s = _fmt_wg(mk, mv)
                    if s:
                        mod_lines.append(f"<div style='white-space:nowrap;'>{s}</div>")
                if mod_lines:
                    lines.append('<hr style="border-color:#555;">')
                    lines.extend(mod_lines)
                b.setToolTip(_NM_WG.rich_tooltip("".join(lines)))
                b.clicked.connect(lambda checked=False, bb=b, ff=f, st=_st3:
                                  self._toggle_wg_signal_flag(bb, ff, st))
                wgl.addWidget(b, idx // 7, idx % 7, Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(wg_grid)
        else:
            _wg_ph = QLabel(wg_compat.signal_flag_placeholder())
            _wg_ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _wg_ph.setStyleSheet(theme.qss("color:@text_hint@; font-size:11px; padding:20px 8px;"))
            cl.addWidget(_wg_ph)
        cl.addStretch()
        layout.addWidget(col, stretch=1)

    def _toggle_wg_signal_flag(self, btn, flag_data, ship_type):
        """WG 信号旗点击：更新选中集合并触发数据重算（选中旗 modifiers 参与计算，多选可叠加）。"""
        mid = flag_data.get("mod_id", "")
        if btn.isChecked():
            self._selected_wg_signal_flags[mid] = flag_data
        else:
            self._selected_wg_signal_flags.pop(mid, None)
        merged: dict = {}
        for _m in getattr(self, '_selected_mods', {}).values():
            _mods = _m.get("modifiers", {}) if isinstance(_m, dict) else {}
            self._merge_wg_signal_mods(merged, _mods, ship_type)
        for _fd in self._selected_wg_signal_flags.values():
            self._merge_wg_signal_mods(merged, _fd.get("modifiers", {}), ship_type)
        self._refresh_data_only(merged if merged else None)

    def _merge_wg_signal_mods(self, dst, src, ship_type):
        """合并修饰符：同 key 按加性/乘性累加，dict 型按舰种取标量。"""
        if not isinstance(src, dict):
            return
        for k, v in src.items():
            if isinstance(v, dict):
                v = v.get(ship_type) or next((x for x in v.values() if isinstance(x, (int, float))), 1.0)
            if k not in dst:
                dst[k] = v
            else:
                try:
                    ev_f, nv_f = float(dst[k]), float(v)
                    dst[k] = ev_f + nv_f if k in _ADDITIVE_KEYS_BASE else ev_f * nv_f
                except (ValueError, TypeError):
                    dst[k] = v

    def _module_icon_name(self, img_file: str) -> str:
        """WG：模块图片加 icon_ 前缀。"""
        return f"icon_{img_file}"

    def _consumable_icon_name(self, cid: str) -> str:
        """WG：消耗品图片无 _0 后缀。"""
        return f"consumable_{cid}.png"

    def _rage_preview_icon(self, rname: str) -> str:
        """WG：战斗指令预览图无 rageMode_ 前缀、无 _0 后缀。"""
        return f"ragemode/{rname}_preview.png"

    def _consumable_detail_items(self, items: list, bp, cfgd: dict, conn, vc: str, kv,
                                  *, num_raw, prep, cd_time, wt, auto, ct) -> None:
        """渲染消耗品详情条目（WG 版）：共用字段 + WG 完整类型分支树。

        WG 特有：时间制（lifeCycleType==1 总容量计数）、可用/默认激活方式、
        tacticalParams 使用方式、planeTacticalFighters（可部署距离/准备时间随距离）、
        auxTorpBooster（logic.buff → PCOM buff 词条）。
        """
        from presenters.wargaming.ship import WargamingShipPresenter
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
        # WG 时间制（总容量/总时间计数）
        for _tb_lbl, _tb_val in WargamingShipPresenter.format_time_based(cfgd):
            kv(_tb_lbl, _tb_val)
        # WG 可用/默认激活方式
        _aam = cfgd.get('availableActivationModes') or []
        if _aam:
            _modes_zh = []
            for _m in _aam:
                _mu = str(_m).upper()
                _modes_zh.append("手动" if _mu == "MANUAL" else ("自动" if _mu == "AUTO" else str(_m)))
            kv("可用激活方式", '/'.join(_modes_zh))
        _dam = cfgd.get('defaultActivationMode') or ""
        if _dam:
            _du = str(_dam).upper()
            kv("默认激活方式", "手动" if _du == "MANUAL" else ("自动" if _du == "AUTO" else str(_dam)))
        items.append(bp.make_item("消耗品效果", "", row_type="header", order=len(items)))
        # WG 使用方式（tacticalParams）
        _tp = cfgd.get('tacticalParams') or {}
        if isinstance(_tp, dict) and _tp:
            _ut = _tp.get('usageType', '')
            _ut_zh = {"default": "常规", "position": "指定位置", "entity": "指定目标"}.get(_ut, _ut)
            kv("使用方式", _ut_zh)
            _wr = _tp.get('workRange')
            _ar = _tp.get('aimRange')
            if _ut != "default":
                if _wr:
                    kv("最大部署距离", f"{float(_wr)/1000:.2f} km")
                elif _ar:
                    kv("瞄准范围", f"{float(_ar):.0f} m")
        # WG 完整类型分支树（按 WargamingShipPresenter._append_consumables 重写）
        if self._consumable_wg_type_branches(ct, cfgd, conn, vc, bp, kv, wt):
            return
        kv("", "该消耗品类型未知，请催促作者更新解析逻辑，谢谢。")

    def _consumable_wg_type_branches(self, ct: str, cfgd: dict, conn, vc: str, bp, kv, wt) -> bool:
        """WG 消耗品类型显示分支（按 WargamingShipPresenter._append_consumables 重写）。

        WG 完整分支树，含 WG 特有类型 planeTacticalFighters/auxTorpBooster；
        不含 Lesta 特有类型（supportBuoy/vampireDamage/massHeal）。
        """
        from presenters.wargaming.ship import WargamingShipPresenter
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
        elif ct == "activeManeuvering":
            pddc = (cfgd.get('planeDamageDodgeCoeff', 0) - 1)
            pdc = (cfgd.get('planeDodgeChance', 0) - 1)
            if pddc != 0:
                kv("机动规避伤害", f"{(pddc)*100:+.2f}%")
            if pdc != 0:
                kv("机动规避概率", f"{(pdc)*100:+.2f}%")
        elif ct == "airDefenseDisp":
            adm = cfgd.get('areaDamageMultiplier', 0)
            bdm = cfgd.get('bubbleDamageMultiplier', 0)
            if adm:
                kv("防空区域秒伤", f"{adm*100:+.2f}%")
            if bdm:
                kv("黑云伤害", f"{bdm*100:+.2f}%")
        elif ct == "hydrophone":
            zlt = cfgd.get('zoneLifeTime', 0)
            hwr = cfgd.get('hydrophoneWaveRadius', 0)
            if zlt:
                kv("虚影存留", f"{zlt}s")
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
            r = float(cfgd.get('radius', 0) or 0)
            h = cfgd.get('height', 0)
            lt = cfgd.get('lifeTime', 0)
            sd = cfgd.get('startDelayTime', 0) or cfgd.get('activationDelay', 0)
            if r:
                kv("烟雾半径", f"{r*3:.2f}m")
            if h:
                kv("烟雾高度", f"{h}m")
            if lt:
                kv("持续时间", f"{lt}s")
            if sd:
                kv("起效延迟", f"{sd}s")
        elif ct in ("planeTacticalFighters", "callFighters"):
            fn = cfgd.get('fightersName') or ""
            if fn:
                fname = bp.resolve_name('plane', fn) or fn
                kv("战斗机名称", fname)
            if ct == "callFighters":
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
            if ct == "planeTacticalFighters":
                rd = cfgd.get('radius', 0)
                if rd:
                    kv("可部署距离", f"{rd*0.03:.2f}km")
                _prep_segs = WargamingShipPresenter.format_distance_of_preparation(
                    cfgd.get('distanceOfPreparation') or [])
                if _prep_segs:
                    kv("准备时间随距离变化", "\n".join(_prep_segs))
        elif ct in "auxTorpBooster":
            for _blbl, _bval, _bcol in WargamingShipPresenter.format_aux_torp_buff(conn, vc, cfgd):
                kv(_blbl, _bval, color=_bcol)
        elif ct in ("tacticalBuffGunBoost", "tacticalBuffAuxBoost", "tacticalFireExtinguishing", "tacticalBuffHeal", "tacticalBuffHealConsumableReload"):
            # 支援飞机投掷类：部署飞机/落地时间/离开时间 + logic.buff(buffOnSelf) PCOM buff 效果
            for _sd_lbl, _sd_val, _sd_col in WargamingShipPresenter.format_support_drop(
                    conn, vc, cfgd, lambda pid: bp.resolve_name('plane', pid)):
                kv(_sd_lbl, _sd_val, color=_sd_col)
        elif ct == "buff":
            # 通用 buff：logic.buff → PCOM 实体（如 PCY080 反空袭，效果为受到的鱼雷/火箭弹/炸弹伤害降低）
            for _blbl, _bval, _bcol in WargamingShipPresenter.format_torpedo_damage_decrease_buff(conn, vc, cfgd):
                kv(_blbl, _bval, color=_bcol)
        else:
            _handled = False
        return _handled

    def _wg_ammo_icon_candidates(self, atype_lower: str, species_lower: str,
                                 ammo_info: dict | None = None, is_sec: bool = False) -> list[str]:
        """WG 弹药图标候选命名（方案 C 迁移）。"""
        at = (atype_lower or "").lower()
        sp = (species_lower or "").lower()
        info = ammo_info or {}
        cand: list[str] = []
        # 修改型/可切换副弹药：ap_sec.png / he_sec.png / cs_sec.png
        if is_sec and at:
            cand.append(f"{at}_sec.png")
        # 飞机弹药 species → WG 图片前缀（species 仅 Bomb/SkipBomb/Rocket/Torpedo/DepthCharge）
        # WG 命名：Bomb→bomb_he.png、SkipBomb→skip_bomb_he.png、Rocket→projectile.png/projectile_ap.png
        _wg_air = {"bomb": "bomb", "skipbomb": "skip_bomb", "rocket": "rocket"}
        _wbase = next((v for k, v in _wg_air.items() if sp.startswith(k)), None)
        if _wbase:
            if _wbase == "rocket":
                if at == "he":
                    cand.append("projectile.png")
                elif at == "ap":
                    cand.append("projectile_ap.png")
            else:
                if at:
                    cand.append(f"{_wbase}_{at}.png")
                    cand.append(f"{_wbase}_{at}_alt.png")
                cand.append(f"{_wbase}.png")
        # 鱼雷
        if sp in ("torpedo", "torpedobomber"):
            if "deepwater" in str(info.get("raw_ammo_type", "")).lower():
                cand.insert(0, "torpedo_deepwater.png")
                cand.insert(0, "bomber_torpedo_deepwater.png")
            else:
                tp = info.get("torpedo_postfix", "")
                if tp == "_subBurn":
                    cand.insert(0, "torpedo_alternative_subburn.png")
                elif tp:
                    cand.insert(0, "torpedo_subdefault.png")
            cand.extend(["torpedo.png", "bomber_torpedo.png"])
        if "depthcharge" in sp:
            cand.extend(["depthcharge.png", "airsupport_depthcharge.png"])
        # 兜底：常规 {at}.png（he/ap/cs 等）
        if at:
            cand.append(f"{at}.png")
        return cand
