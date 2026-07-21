"""
CrewCustomizeDialog —— 自定义稀有/精英舰长的强化技能和国家天赋。

功能：
- 稀有舰长：可查看和配置强化技能（从同国籍传奇舰长处借用国家天赋）
- 精英舰长：可从同国籍传奇舰长中选择一个国家天赋
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QScrollArea, QWidget, QGridLayout,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QFont


class CrewCustomizeDialog(QDialog):
    """自定义舰长配置对话框"""

    def __init__(self, crew_data: dict, db_nation: str, parent=None):
        super().__init__(parent)
        self._crew_data = crew_data
        self._db_nation = db_nation
        self.setWindowTitle("自定义舰长配置")
        self.setMinimumSize(420, 400)
        self.setStyleSheet("""
            QDialog { background:#1e1e1e; color:#ddd; }
            QLabel { color:#ddd; font-size:12px; }
            QGroupBox { border:1px solid #444; border-radius:4px; margin-top:12px;
                        font-size:12px; color:#ffc107; padding-top:12px; }
            QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
            QComboBox { background:#2a2a2a; border:1px solid #555; border-radius:3px;
                        padding:3px 6px; color:#ddd; font-size:11px; }
            QPushButton { background:#3a3a3a; border:1px solid #555; border-radius:3px;
                          padding:4px 12px; color:#ddd; font-size:11px; }
            QPushButton:hover { background:#4a4a4a; }
        """)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 当前舰长信息 ──
        info = QLabel(f"当前: {self._crew_data.get('disp', '未知')}")
        info.setStyleSheet("font-size:14px; font-weight:bold; color:#ffc107; padding:4px 0;")
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
        """精英舰长：可从同国籍传奇舰长的所有天赋中选一项"""
        from services.database_service import get_db
        from PySide6.QtWidgets import QButtonGroup

        lbl = QLabel("精英舰长可学习一项同国籍传奇舰长的国家天赋（仅可选一项）：")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        db = get_db()
        vc = db.get_latest_version_code() or "" if db else ""

        # 查询同国籍所有传奇天赋
        self._talent_group = QButtonGroup(self)
        self._talent_group.setExclusive(True)
        self._selected_talent = None  # 存储选中天赋 (crew_id, skill_key)

        talents_found = False
        if db and db._conn and vc:
            try:
                cur = db._conn.execute("""
                    SELECT us.skill_key, us.trigger_type, us.max_trigger_num,
                           us.effects_json, us.icon_path, us.sort_index,
                           c.crew_id, COALESCE(n.lang_zh, c.person_name, c.crew_id) as legend_name
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
                    # 用网格显示（每行3个）
                    from PySide6.QtWidgets import QGridLayout
                    tw = QWidget()
                    tg = QGridLayout(tw)
                    tg.setContentsMargins(0,0,0,0); tg.setSpacing(4)

                    def _make_talent_btn(talent_row):
                        icon_path = talent_row['icon_path'] or ""
                        btn = QPushButton()
                        btn.setCheckable(True)
                        btn.setStyleSheet("""
                            QPushButton { background:#1a1a1a; border:2px solid #444;
                                          border-radius:6px; min-width:56px; min-height:56px;
                                          max-width:56px; max-height:56px; font-size:8px;
                                          color:#aaa; padding:0px; }
                            QPushButton:hover { background:#2a2a2a; border-color:#888; }
                            QPushButton:checked { background:#2a2a2a; border-color:#ffc107; color:#ffc107; }
                        """)
                        if icon_path and Path(icon_path).exists():
                            pix = QPixmap(icon_path)
                            if not pix.isNull():
                                btn.setIcon(QIcon(pix))
                                btn.setIconSize(QSize(46, 46))
                        else:
                            short = talent_row['skill_key'].split('_')[-1] if '_' in talent_row['skill_key'] else talent_row['skill_key'][:5]
                            label = short
                            if talent_row['max_trigger_num']:
                                label += f"\n×{talent_row['max_trigger_num']}"
                            btn.setText(label)
                        # tooltip
                        lname = talent_row['legend_name']
                        tip = f"<div style='font-size:12px;'><b style='color:#ffc107;'>{lname}</b>"
                        tip += f"<br><span style='color:#ddd;'>{talent_row['skill_key']}</span></div>"
                        btn.setToolTip(tip)
                        self._talent_group.addButton(btn)
                        return btn

                    for i, t in enumerate(talents):
                        btn = _make_talent_btn(t)
                        btn.talent_data = (t['crew_id'], t['skill_key'], t['legend_name'])
                        tg.addWidget(btn, i // 3, i % 3)
                        btn.clicked.connect(lambda checked, d=btn.talent_data: self._on_talent_selected(d) if checked else None)

                    scroll = QScrollArea()
                    scroll.setWidgetResizable(True)
                    scroll.setWidget(tw)
                    scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
                    scroll.setMinimumHeight(80)
                    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    layout.addWidget(scroll)

            except Exception:
                pass

        if not talents_found:
            note = QLabel("（当前国籍没有可学习的传奇天赋）")
            note.setStyleSheet("color:#888; font-size:11px; padding:4px 0;")
            layout.addWidget(note)

    def _on_talent_selected(self, talent_data):
        """记录选中的天赋"""
        self._selected_talent = talent_data

    def _build_legendary_section(self, layout: QVBoxLayout):
        """传奇舰长：展示天赋信息"""
        self._talent_preview = QWidget()
        tl = QHBoxLayout(self._talent_preview)
        tl.setContentsMargins(0,0,0,0)
        tl.addStretch()

        from services.database_service import get_db
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
                        QPushButton { background:#1a1a1a; border:2px solid #ffc107;
                                      border-radius:6px; min-width:52px; min-height:52px;
                                      max-width:52px; max-height:52px; font-size:9px;
                                      color:#ffc107; padding:0px; }
                        QPushButton:hover { background:#2a2a2a; border-color:#ffd54f; }
                    """)
                    btn.setCheckable(False)
                    if icon_path and Path(icon_path).exists():
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

    def _build_custom_section(self, layout: QVBoxLayout):
        """自定义稀有舰长：仅强化技能"""
        lbl = QLabel("自定义稀有舰长可自由配置强化技能。")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        note = QLabel("回到主界面后，可在技能网格中为自定义舰长分配技能点数。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888; font-size:11px; padding:4px 0;")
        layout.addWidget(note)
