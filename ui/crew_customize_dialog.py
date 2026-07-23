"""
CrewCustomizeDialog —— 自定义稀有/精英舰长的强化技能和国家天赋。

功能：
- 稀有舰长：可查看和配置强化技能（从同国籍传奇舰长处借用国家天赋）
- 精英舰长：可从同国籍传奇舰长中选择一个国家天赋
"""

from __future__ import annotations

import json
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QScrollArea, QWidget, QGridLayout,
    QSizePolicy, QCheckBox,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QFont


class CrewCustomizeDialog(QDialog):
    """自定义舰长配置对话框"""

    def __init__(self, crew_data: dict, db_nation: str, parent=None,
                 ship_type_cn: str = "", ship_type_en: str = "",
                 epic_skills: list[str] | None = None,
                 selected_talent: tuple | None = None):
        super().__init__(parent)
        self._crew_data = crew_data
        self._db_nation = db_nation
        self._ship_type_cn = ship_type_cn
        self._ship_type_en = ship_type_en
        self.epic_skills: list[str] = list(epic_skills) if epic_skills else []
        self.selected_talent: tuple | None = selected_talent
        self.setWindowTitle("自定义舰长配置")
        self.setMinimumSize(420, 400)
        self._max_epic = 3
        self.setStyleSheet("""
            QDialog { background:#ffffff; color:#222; }
            QLabel { color:#000; font-size:12px; }
            QGroupBox { border:1px solid #ccc; border-radius:4px; margin-top:12px;
                        font-size:12px; color:#c60; padding-top:12px; }
            QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
            QComboBox { background:#fff; border:1px solid #bbb; border-radius:3px;
                        padding:3px 6px; color:#000; font-size:11px; }
            QPushButton { background:#f0f0f0; border:1px solid #bbb; border-radius:3px;
                          padding:4px 12px; color:#000; font-size:11px; }
            QPushButton:hover { background:#e0e0e0; }
        """)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 当前舰长信息 ──
        info = QLabel(f"当前: {self._crew_data.get('disp', '未知')}")
        info.setStyleSheet("font-size:14px; font-weight:bold; color:#c60; padding:4px 0;")
        layout.addWidget(info)

        crew_id = self._crew_data.get('crew_id', '')
        is_elite = crew_id == '__elite__'
        is_custom = crew_id == '__custom__'
        is_legendary = self._crew_data.get('is_unique', False) and self._crew_data.get('unique_skill_count', 0) > 0

        if is_elite:
            # 精英舰长：强化技能 + 可自选国家天赋
            self._build_elite_section(layout)
        elif is_custom:
            # 自定义稀有舰长：仅强化技能
            self._build_custom_section(layout)
        elif is_legendary:
            self._build_legendary_section(layout)
        else:
            # 普通传奇/特殊舰长，仅显示信息
            self._build_viewonly_section(layout)

        # ── 底部按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("保存配置")
        save_btn.setStyleSheet("""
            QPushButton { background:#1a73e8; border:1px solid #1a73e8; border-radius:3px;
                          padding:6px 20px; color:#fff; font-size:12px; font-weight:bold; }
            QPushButton:hover { background:#1565c0; }
        """)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _build_elite_section(self, layout: QVBoxLayout):
        """精英舰长：强化技能切换 + 可自选国家天赋"""
        self._build_epic_skill_section(layout)
        # ── 传奇天赋选择 ──
        from services.database_service import get_db

        lbl = QLabel("精英舰长可学习一项同国籍传奇舰长的国家天赋（仅可选一项）：")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        db = get_db()
        vc = db.get_latest_version_code() or "" if db else ""

        # 查询同国籍所有传奇天赋
        self._selected_talent = None  # 存储选中天赋 (crew_id, skill_key)

        talents_found = False
        if db and db._conn and vc:
            try:
                cur = db._conn.execute("""
                    SELECT us.skill_key, us.trigger_type, us.max_trigger_num,
                           us.effects_json, us.icon_path, us.sort_index,
                           c.crew_id, COALESCE(n.lang_zh, c.person_name, c.crew_id) as legend_name,
                           us.trigger_achievement, us.trigger_damage_num, us.trigger_damage_type,
                           us.trigger_ribbon_types, us.trigger_ribbons_num, us.damage_percent_threshold
                    FROM crew_unique_skills us
                    JOIN crew_basic_info c ON c.version_code=us.version_code AND c.crew_id=us.crew_id
                    LEFT JOIN name_mappings n ON n.id=c.display_name_id
                                               OR (n.category='crew' AND n.key_name='IDS_' || UPPER(c.person_name))
                    WHERE us.version_code=? AND c.nation=?
                      AND c.is_unique=1 AND c.person_name!='' AND c.crew_id NOT LIKE '%Template%'
                    ORDER BY legend_name, us.sort_index
                """, (vc, self._db_nation))
                talents = cur.fetchall()
                if talents:
                    talents_found = True
                    from PySide6.QtWidgets import QRadioButton
                    from models.name_mapping import Mapping as NMAP
                    _mod_map = getattr(NMAP, 'MODIFIER_MAP', {})
                    _ribbon_map = getattr(NMAP, 'RIBBON_MAP', {})
                    _trigger_map = getattr(NMAP, 'TRIGGER_TYPE_MAP', {})
                    _achievement_map = getattr(NMAP, 'ACHIEVEMENT_MAP', {})

                    _skip_meta_keys = {'percentTalent', 'uniqueType', 'levelDependent', 'v', 'value'}

                    def _build_trigger_text(sk_row, trig_type, trig_map, rib_map, ach_map):
                        """生成触发条件文本"""
                        tzh = trig_map.get(trig_type, trig_type or "?")
                        if trig_type == "achievement":
                            ach = sk_row['trigger_achievement'] or ""
                            ach_zh = ach_map.get(ach, ach)
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
                            dmg = sk_row['trigger_damage_num'] or 0
                            from models.name_mapping import Mapping as NMAP2
                            dmg_zh = getattr(NMAP2, 'DAMAGE_TYPE_MAP', {}).get(str(sk_row['trigger_damage_type'] or ""), "")
                            label = f"受到 {dmg/10000:.0f}万"
                            if dmg_zh:
                                label += f" ({dmg_zh})"
                            return label + " 伤害时触发"
                        elif trig_type == "health":
                            thr = sk_row['damage_percent_threshold']
                            if thr:
                                return f"战舰血量低于 {thr*100:.0f}% 时触发"
                            return "受到伤害导致血量降低时触发"
                        return tzh

                    def _format_talent_effects_text(eff_dict, mod_map, ship_type_en=""):
                        """格式化天赋效果为多行文本，隐藏分组标题，仅返回单行修饰符列表"""
                        lines = []
                        for ek, ev in eff_dict.items():
                            if not isinstance(ev, dict):
                                continue
                            is_level = ev.get('levelDependent', False)
                            is_pct = ev.get('percentTalent', False)
                            for sub_k, sub_v in ev.items():
                                if sub_k in _skip_meta_keys:
                                    continue
                                sub_zh = mod_map.get(sub_k, sub_k)
                                if isinstance(sub_v, dict):
                                    if ship_type_en and sub_v.get(ship_type_en) is not None:
                                        sub_v = sub_v[ship_type_en]
                                    else:
                                        for x in sub_v.values():
                                            if isinstance(x, (int, float)):
                                                sub_v = x
                                                break
                                        else:
                                            continue
                                if not isinstance(sub_v, (int, float)):
                                    continue
                                if is_pct:
                                    ft = NMAP.format_modifier(sub_k, sub_v, color=True)
                                    if ft:
                                        lines.append(ft + " " + sub_zh)
                                elif isinstance(sub_v, float) and 0.5 <= sub_v <= 2.0:
                                    ft = NMAP.format_modifier(sub_k, sub_v, color=True)
                                    if ft:
                                        lines.append(ft + " " + sub_zh)
                                else:
                                    lines.append(f"{sub_zh} {sub_v:+.0f}" if sub_v else f"{sub_zh} {sub_v:.0f}")
                            if is_level:
                                lines.insert(0, "该天赋作用时间等于战舰等级")
                        return lines

                    def _build_talent_tooltip(talent_row) -> str:
                        """构建天赋 tooltip"""
                        lines = ['<div style="font-size:12px; line-height:1.5;">']
                        tt = talent_row['trigger_type'] or ""
                        desc = _build_trigger_text(talent_row, tt, _trigger_map, _ribbon_map, _achievement_map)
                        lines.append(f'<div style="color:#ffc107; font-weight:bold; margin-bottom:4px;">▸ {desc}</div>')
                        try:
                            eff = json.loads(talent_row['effects_json']) if talent_row['effects_json'] else {}
                        except Exception:
                            eff = {}
                        if eff:
                            lines.append('<div style="color:#aaa; margin-top:4px;">效果：</div>')
                            eff_lines = _format_talent_effects_text(eff, _mod_map, self._ship_type_en)
                            for l in eff_lines:
                                lines.append(f'<div style="color:#ddd; padding-left:8px;">{l}</div>')
                        if talent_row['max_trigger_num']:
                            lines.append(f'<div style="color:#888; font-size:11px; margin-top:4px;">每场最多触发 {talent_row["max_trigger_num"]} 次</div>')
                        lines.append('</div>')
                        return "".join(lines)

                    # 按传奇舰长分组显示
                    by_legend: dict[str, list] = {}
                    for t in talents:
                        lname = t['legend_name']
                        by_legend.setdefault(lname, []).append(t)

                    scroll_content = QWidget()
                    sc_layout = QVBoxLayout(scroll_content)
                    sc_layout.setContentsMargins(0,0,0,0)
                    sc_layout.setSpacing(6)
                    _talent_cbs: list[QCheckBox] = []
                    for lname, ltalents in by_legend.items():
                        # 传奇舰长姓名标签
                        header = QLabel(f"✦ {lname}")
                        header.setWordWrap(False)
                        header.setStyleSheet("color:#c60; font-size:12px; font-weight:bold; padding:4px 0 2px 0;")
                        sc_layout.addWidget(header)
                        for t in ltalents:
                            t = dict(t)  # sqlite3.Row → dict
                            icon_path = t['icon_path'] or ""
                            # 解析效果
                            eff_desc_lines = []
                            try:
                                eff = json.loads(t['effects_json']) if t['effects_json'] else {}
                            except Exception:
                                eff = {}
                            if eff:
                                eff_lines = _format_talent_effects_text(eff, _mod_map, self._ship_type_en)
                                eff_desc_lines.extend(eff_lines)
                            # 触发条件
                            trig_text = _build_trigger_text(t, t.get('trigger_type',''), _trigger_map, _ribbon_map, _achievement_map)
                            # 行容器
                            row = QWidget()
                            hl = QHBoxLayout(row)
                            hl.setContentsMargins(6, 2, 6, 2)
                            hl.setSpacing(8)
                            # 复选框（类似强化技能，上限为1）
                            cb = QCheckBox()
                            cb.setChecked(False)
                            cb.setStyleSheet("""
                                QCheckBox { border:none; background:transparent; padding:0px; }
                                QCheckBox::indicator {
                                    width: 18px; height: 18px;
                                    border: 2px solid #666;
                                    border-radius: 3px;
                                    background: #3a3a3a;
                                }
                                QCheckBox::indicator:checked {
                                    background: #ff8800;
                                    border-color: #ffaa33;
                                }
                                QCheckBox::indicator:hover {
                                    border-color: #ff8800;
                                }
                            """)
                            hl.addWidget(cb)
                            # 图标
                            if icon_path:
                                pix = QPixmap(icon_path)
                                if not pix.isNull():
                                    icon_label = QLabel()
                                    icon_label.setPixmap(pix.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                                    icon_label.setFixedSize(36, 36)
                                    icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
                                    icon_label.setStyleSheet("background:#2a2a2a; border-radius:4px;")
                                    hl.addWidget(icon_label)
                            # 右侧文本：触发条件 + 效果
                            right_layout = QVBoxLayout()
                            right_layout.setContentsMargins(0,0,0,0)
                            right_layout.setSpacing(1)
                            # 触发条件
                            trig_label = QLabel(f"<span style='color:#ffc107; font-size:10px;'>触发：</span><span style='color:#ccc; font-size:10px;'>{trig_text}</span>")
                            trig_label.setWordWrap(True)
                            trig_label.setAttribute(Qt.WA_TransparentForMouseEvents)
                            right_layout.addWidget(trig_label)
                            # 效果
                            if eff_desc_lines:
                                eff_header = QLabel("<span style='color:#4fc3f7; font-size:10px;'>效果：</span>")
                                eff_header.setAttribute(Qt.WA_TransparentForMouseEvents)
                                right_layout.addWidget(eff_header)
                                for _el in eff_desc_lines:
                                    _el_label = QLabel(f"<span style='color:#ddd; font-size:10px;'>{_el}</span>")
                                    _el_label.setWordWrap(True)
                                    _el_label.setAttribute(Qt.WA_TransparentForMouseEvents)
                                    right_layout.addWidget(_el_label)
                            # 触发次数
                            if t.get('max_trigger_num'):
                                cnt_label = QLabel(f"<span style='color:#888; font-size:9px;'>每场最多触发 {t['max_trigger_num']} 次</span>")
                                cnt_label.setAttribute(Qt.WA_TransparentForMouseEvents)
                                right_layout.addWidget(cnt_label)
                            hl.addLayout(right_layout, 1)
                            # 天赋选中逻辑（上限1个，类似强化技能）
                            _td = (t['crew_id'], t['skill_key'], lname)
                            def _on_talent_toggle(checked, _cb=cb, _td=_td):
                                if checked:
                                    # 取消前一个选中的天赋
                                    for _b in _talent_cbs:
                                        if _b is not _cb and _b.isChecked():
                                            _b.setChecked(False)
                                    self.selected_talent = _td
                                else:
                                    self.selected_talent = None
                            cb.toggled.connect(_on_talent_toggle)
                            cb._talent_skill_key = t['skill_key']
                            _talent_cbs.append(cb)
                            # 行点击
                            def _row_click(e, _cb=cb):
                                _cb.setChecked(not _cb.isChecked())
                            row.mousePressEvent = _row_click
                            row.setStyleSheet("background:#2a2a2a; border:1px solid #444; border-radius:4px;")
                            # Tooltip
                            row.setToolTip(_build_talent_tooltip(t))
                            sc_layout.addWidget(row)

                    scroll = QScrollArea()
                    scroll.setWidgetResizable(True)
                    scroll.setWidget(scroll_content)
                    scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
                    scroll.setMinimumHeight(100)
                    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    layout.addWidget(scroll)

                    # 恢复之前选中的天赋
                    if self.selected_talent and _talent_cbs:
                        _tgt_sk = self.selected_talent[1] if len(self.selected_talent) >= 2 else None
                        for _cb in _talent_cbs:
                            if hasattr(_cb, '_talent_skill_key') and _cb._talent_skill_key == _tgt_sk:
                                _cb.setChecked(True)
                                break

            except Exception as e:
                import traceback
                _err = f"[CrewCustomize] _build_elite_section error: {e}\n{traceback.format_exc()}"
                print(_err)
                from app.signals import bus
                try:
                    bus.log_message.emit(_err)
                except Exception:
                    pass

        if not talents_found:
            note = QLabel("（当前国籍没有可学习的传奇天赋）")
            note.setStyleSheet("color:#888; font-size:11px; padding:4px 0;")
            layout.addWidget(note)

    def _build_legendary_section(self, layout: QVBoxLayout):
        """传奇舰长：展示天赋信息"""
        self._talent_preview = QWidget()
        tl = QHBoxLayout(self._talent_preview)
        tl.setContentsMargins(0,0,0,0)
        tl.addStretch()

        from services.database_service import get_db
        from models.name_mapping import Mapping as NMAP
        _mod_map = getattr(NMAP, 'MODIFIER_MAP', {})
        _ribbon_map = getattr(NMAP, 'RIBBON_MAP', {})
        _trigger_map = getattr(NMAP, 'TRIGGER_TYPE_MAP', {})
        _achievement_map = getattr(NMAP, 'ACHIEVEMENT_MAP', {})
        _skip_meta_keys = {'percentTalent', 'uniqueType', 'levelDependent', 'v', 'value'}

        def _trigger_text(row):
            tt = row['trigger_type'] or ''
            tzh = _trigger_map.get(tt, tt or '?')
            if tt == 'achievement':
                ach = row['trigger_achievement'] or ''
                aname = _achievement_map.get(ach, ach)
                return f"获得勋章「{aname}」时触发" if aname else tzh
            elif tt == 'ribbons':
                rnames = [(_ribbon_map.get(r, r)) for r in json.loads(row['trigger_ribbon_types'] or '[]')]
                num = row['trigger_ribbons_num'] or ''
                return f"获得 {num} 个{'/'.join(rnames)} 勋带触发"
            elif tt == 'damage':
                dmg = row['trigger_damage_num'] or 0
                dmg_zh = getattr(NMAP, 'DAMAGE_TYPE_MAP', {}).get(str(row['trigger_damage_type'] or ''), '')
                label = f"受到 {dmg/10000:.0f}万"
                if dmg_zh: label += f" ({dmg_zh})"
                return label + " 伤害时触发"
            elif tt == 'health':
                thr = row['damage_percent_threshold']
                if thr:
                    return f"战舰血量低于 {thr*100:.0f}% 时触发"
                return "受到伤害导致血量降低时触发"
            return tzh

        def _effects_text(eff_dict):
            """返回单行修饰符列表，隐藏分组标题"""
            lines = []
            for ek, ev in eff_dict.items():
                if not isinstance(ev, dict): continue
                is_pct = ev.get('percentTalent', False)
                is_level = ev.get('levelDependent', False)
                for sub_k, sub_v in ev.items():
                    if sub_k in _skip_meta_keys: continue
                    sub_zh = _mod_map.get(sub_k, sub_k)
                    if isinstance(sub_v, dict):
                        for x in sub_v.values():
                            if isinstance(x, (int, float)): sub_v = x; break
                        else: continue
                    if not isinstance(sub_v, (int, float)): continue
                    if is_pct:
                        ft = NMAP.format_modifier(sub_k, sub_v, color=True)
                        if ft:
                            lines.append(" " + ft + " " + sub_zh)
                    elif isinstance(sub_v, float) and 0.5 <= sub_v <= 2.0:
                        ft = NMAP.format_modifier(sub_k, sub_v, color=True)
                        if ft:
                            lines.append(" " + ft + " " + sub_zh)
                    else:
                        lines.append(f"{sub_zh} {sub_v:+.0f}" if sub_v else f"{sub_zh} {sub_v:.0f}")
                if is_level:
                    lines.insert(0, "该天赋作用时间等于战舰等级")
            return lines

        def _build_tip(row):
            lines = ['<div style="font-size:12px; line-height:1.5;">']
            desc = _trigger_text(row)
            lines.append(f'<div style="color:#ffc107; font-weight:bold; margin-bottom:4px;">▸ {desc}</div>')
            try: eff = json.loads(row['effects_json']) if row['effects_json'] else {}
            except Exception: eff = {}
            if eff:
                lines.append('<div style="color:#aaa; margin-top:4px;">效果：</div>')
                for l in _effects_text(eff):
                    lines.append(f'<div style="color:#ddd; padding-left:8px;">{l}</div>')
            if row['max_trigger_num']:
                lines.append(f'<div style="color:#888; font-size:11px; margin-top:4px;">每场最多触发 {row["max_trigger_num"]} 次</div>')
            lines.append('</div>')
            return ''.join(lines)

        db = get_db()
        if db and db._conn:
            try:
                cur = db._conn.execute("""
                    SELECT skill_key, trigger_type, max_trigger_num, effects_json, icon_path
                    FROM crew_unique_skills
                    WHERE version_code=? AND crew_id=?
                    ORDER BY sort_index
                """, (db.get_latest_version_code() or "", self._crew_data['crew_id']))
                for sk in cur.fetchall():
                    icon_path = sk['icon_path'] or ""
                    btn = QPushButton()
                    btn.setStyleSheet("""
                        QPushButton { background:#f0f0f0; border:2px solid #ccc;
                                      border-radius:6px; min-width:52px; min-height:52px;
                                      max-width:52px; max-height:52px; font-size:9px;
                                      color:#000; padding:0px; }
                        QPushButton:hover { background:#e0e0e0; border-color:#999; }
                    """)
                    btn.setCheckable(False)
                    btn.setToolTip(_build_tip(sk))
                    if icon_path:
                        pix = QPixmap(icon_path)
                        if not pix.isNull():
                            btn.setIcon(QIcon(pix))
                            btn.setIconSize(QSize(44, 44))
                    else:
                        short = sk['skill_key'].split('_')[-1] if '_' in sk['skill_key'] else sk['skill_key'][:6]
                        btn.setText(short)
                    tl.insertWidget(tl.count() - 1, btn)
            except Exception:
                pass

        layout.addWidget(self._talent_preview)
        note = QLabel("传奇舰长拥有独特的国家天赋，可在战斗中触发。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888; font-size:11px; padding:4px 0;")
        layout.addWidget(note)

    def _build_viewonly_section(self, layout: QVBoxLayout):
        """普通/特殊舰长：仅查看信息，无自定义功能"""
        lbl = QLabel("该舰长拥有常规技能配置，可在主界面技能网格中自由配置技能点数。")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        note = QLabel("（此类型舰长无法自定义强化技能或国家天赋）")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888; font-size:11px; padding:4px 0;")
        layout.addWidget(note)

    def _build_epic_skill_section(self, layout: QVBoxLayout):
        """构建强化技能切换面板：每行一个技能，图标+名称+加成"""
        from services.database_service import get_db
        from services.skill_service import SkillService
        from PySide6.QtWidgets import QCheckBox
        from PySide6.QtGui import QPixmap, QIcon
        from PySide6.QtCore import QSize
        from models.name_mapping import Mapping as NMAP

        if not self._ship_type_cn or not self._ship_type_en:
            lbl = QLabel("（请先选择舰船以查看可用技能）")
            lbl.setStyleSheet("color:#888; font-size:11px; padding:4px 0;")
            layout.addWidget(lbl)
            return

        grp = QGroupBox(" 强化技能切换")
        layout.addWidget(grp)
        gl = QVBoxLayout(grp)
        gl.setContentsMargins(6, 4, 6, 4)
        gl.setSpacing(4)

        lbl = QLabel("勾选需要切换为强化版本的技能：")
        lbl.setStyleSheet("color:#000; font-size:11px;")
        gl.addWidget(lbl)
        limit_hint = QLabel(f"（最多可选 {self._max_epic} 个强化技能）")
        limit_hint.setStyleSheet("color:#888; font-size:10px;")
        gl.addWidget(limit_hint)

        db = get_db()
        svc = SkillService()
        vc = db.get_latest_version_code() or "" if db else ""
        if not db or not db._conn or not vc:
            gl.addWidget(QLabel("（数据库未就绪）"))
            return

        _mod_map = getattr(NMAP, 'MODIFIER_MAP', {})
        grid = svc._grid_map.get(self._ship_type_cn, {})
        self._epic_checkboxes: dict[str, QCheckBox] = {}
        found = False
        row_w = QWidget()
        rl = QVBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        for pos, icon_name in grid.items():
            try:
                sk = svc._icon_to_skill_key(icon_name, db, vc)
            except Exception:
                sk = None
            if not sk:
                continue
            # 检查是否有 EPIC 版本
            mods_epic = {}
            mods_reg = {}
            try:
                cur = db._conn.execute(
                    "SELECT modifiers_json FROM crew_skill_definitions WHERE version_code=? AND skill_key=? AND rarity='EPIC'",
                    (vc, sk)
                )
                row = cur.fetchone()
                if row:
                    mods_epic = json.loads(row['modifiers_json']) if row['modifiers_json'] else {}
                cur = db._conn.execute(
                    "SELECT modifiers_json FROM crew_skill_definitions WHERE version_code=? AND skill_key=? AND rarity='REGULAR'",
                    (vc, sk)
                )
                row = cur.fetchone()
                if row:
                    mods_reg = json.loads(row['modifiers_json']) if row['modifiers_json'] else {}
            except Exception:
                pass
            if not mods_epic:
                continue
            found = True
            # 获取技能中文名
            sname = icon_name
            try:
                cur = db._conn.execute(
                    "SELECT lang_zh FROM name_mappings WHERE category='skill_title' AND key_name=?",
                    (icon_name.lower(),)
                )
                r = cur.fetchone()
                if r:
                    sname = r['lang_zh']
            except Exception:
                pass
            # ── 行容器 ──
            row = QWidget()
            row.setStyleSheet("background:#f7f7f7; border:1px solid #ddd; border-radius:4px;")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(6, 2, 6, 2)
            hl.setSpacing(8)
            # 勾选框
            cb = QCheckBox()
            cb.setChecked(sk in self.epic_skills)
            cb.setStyleSheet("""
                QCheckBox { border:none; background:transparent; padding:0px; }
                QCheckBox::indicator {
                    width: 18px; height: 18px;
                    border: 2px solid #666;
                    border-radius: 3px;
                    background: #3a3a3a;
                }
                QCheckBox::indicator:checked {
                    background: #ff8800;
                    border-color: #ffaa33;
                }
                QCheckBox::indicator:hover {
                    border-color: #ff8800;
                }
            """)
            cb.stateChanged.connect(lambda checked, k=sk, c=cb: self._on_epic_toggle(k, checked, c))
            self._epic_checkboxes[sk] = cb
            hl.addWidget(cb)
            # 技能图标
            icon_path = f":/resources/pictures/skills/{icon_name}.png"
            pix = QPixmap(icon_path)
            if not pix.isNull():
                icon_label = QLabel()
                icon_label.setPixmap(pix.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                icon_label.setFixedSize(28, 28)
                icon_label.setStyleSheet("background:#2a2a2a; border-radius:4px;")
                hl.addWidget(icon_label)
            # 技能名称
            name_label = QLabel(sname)
            name_label.setStyleSheet("color:#000; font-size:11px; font-weight:bold; min-width:80px;")
            hl.addWidget(name_label)
            # 加成对比
            diff_text = ""
            for mk, mv_epic in mods_epic.items():
                mv_reg = mods_reg.get(mk, mv_epic)
                zh = _mod_map.get(mk, mk)
                # 格式化 EPIC 值
                if isinstance(mv_epic, dict):
                    v_epic = mv_epic.get(self._ship_type_en) or next((x for x in mv_epic.values() if isinstance(x, (int, float))), 0)
                else:
                    v_epic = mv_epic
                if isinstance(mv_reg, dict):
                    v_reg = mv_reg.get(self._ship_type_en) or next((x for x in mv_reg.values() if isinstance(x, (int, float))), 0)
                else:
                    v_reg = mv_reg
                if isinstance(v_epic, (int, float)) and isinstance(v_reg, (int, float)):
                    from models.name_mapping import Mapping as NMAP_FMT
                    reg_str = NMAP_FMT.format_modifier(mk, v_reg, color=True)
                    ep_str = NMAP_FMT.format_modifier(mk, v_epic, color=True)
                    if not reg_str and not ep_str:
                        continue
                    diff_text += f"<span style='color:#888;'>{zh}</span> "
                    diff_text += f"<span style='color:#aaa;'>{reg_str}</span>"
                    if reg_str != ep_str:
                        diff_text += f" <span style='color:#ff6600;'>→ {ep_str}</span>"
                    diff_text += "<br>"

            if diff_text:
                diff_label = QLabel(diff_text)
                diff_label.setStyleSheet("color:#aaa; font-size:10px;")
                diff_label.setWordWrap(True)
                hl.addWidget(diff_label, 1)

            rl.addWidget(row)

        if found:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(row_w)
            scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
            scroll.setMinimumHeight(80)
            scroll.setMaximumHeight(300)
            gl.addWidget(scroll)
        else:
            gl.addWidget(QLabel("（当前舰种没有可用的强化技能）"))

    def _on_epic_toggle(self, skill_key: str, checked: int, cb):
        if checked:
            if skill_key not in self.epic_skills:
                if len(self.epic_skills) >= self._max_epic:
                    cb.setChecked(False)
                    return
                self.epic_skills.append(skill_key)
        else:
            if skill_key in self.epic_skills:
                self.epic_skills.remove(skill_key)

    def _build_custom_section(self, layout: QVBoxLayout):
        """自定义稀有舰长：强化技能切换"""
        self._build_epic_skill_section(layout)
