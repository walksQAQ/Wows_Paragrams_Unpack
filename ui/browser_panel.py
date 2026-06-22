"""
BrowserPanel —— 文件列表面板（300px 固定宽度）。

支持按国籍/舰种/等级多选筛选舰船，按本地化舰名或编号搜索。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QLineEdit, QPushButton, QListWidgetItem, QMenu,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QAction

from app.signals import bus
from utils.path_utils import get_split_dir
from services.database_service import get_db


class MultiSelectCombo(QPushButton):
    """多选下拉框 —— 点击弹出可勾选的菜单"""

    selection_changed = Signal()

    def __init__(self, placeholder: str = "全部", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._items: list[tuple[str, str]] = []  # (display, data)
        self._selected: set[str] = set()
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        self.setStyleSheet("""
            QPushButton {
                padding: 3px 4px; border: 1px solid #c0c0c0;
                border-radius: 3px; font-size: 11px;
                background-color: #ffffff; min-width: 70px;
                text-align: left;
            }
            QPushButton:focus { border-color: #0078d4; }
            QPushButton::menu-indicator { subcontrol-position: right center; padding-right: 2px; }
        """)
        self._update_text()

    def fill_items(self, items: list[tuple[str, str]]) -> None:
        """填充项目: [(显示文本, 数据值), ...]"""
        self._items = list(items)
        self._selected.clear()
        self._menu.clear()
        for display, data in self._items:
            action = QAction(display, self)
            action.setCheckable(True)
            action.setData(data)
            action.toggled.connect(lambda checked, d=data: self._on_toggle(d, checked))
            self._menu.addAction(action)
        self._update_text()

    def clear_items(self) -> None:
        self._items.clear()
        self._selected.clear()
        self._menu.clear()
        self._update_text()

    def selected_data(self) -> list[str]:
        return list(self._selected)

    def reset(self) -> None:
        self._selected.clear()
        for action in self._menu.actions():
            action.setChecked(False)
        self._update_text()
        self.selection_changed.emit()

    def _on_toggle(self, data: str, checked: bool) -> None:
        if checked:
            self._selected.add(data)
        else:
            self._selected.discard(data)
        self._update_text()
        self.selection_changed.emit()

    def _update_text(self) -> None:
        if not self._selected:
            self.setText(f"☰ {self._placeholder}")
        else:
            self.setText(f"☰ 已选 {len(self._selected)} 项")


class BrowserPanel(QWidget):
    """文件列表面板（300px 固定宽度）"""

    file_selected = Signal(str, str)

    @staticmethod
    def _safe_db():
        """获取数据库连接，处理 reset_db() 关闭连接后的重连"""
        import sqlite3
        try:
            db = get_db()
            # 测试连接是否有效
            db._conn.execute("SELECT 1")
            return db
        except (sqlite3.ProgrammingError, sqlite3.OperationalError, AttributeError):
            # 连接已关闭，重置全局状态重新获取
            from services.database_service import reset_db
            reset_db()
            return get_db()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrowserPanel")
        self.setFixedWidth(300)
        self.setStyleSheet("""
            #BrowserPanel {
                background-color: #f0f0f0;
                border-right: 1px solid #d0d0d0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(4)

        # ── 搜索框 ─
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 搜索舰名或编号...")
        self.search_box.setStyleSheet("""
            QLineEdit {
                padding: 4px 6px;
                border: 1px solid #c0c0c0;
                border-radius: 3px;
                font-size: 11px;
                background-color: #ffffff;
            }
            QLineEdit:focus { border-color: #0078d4; }
        """)
        layout.addWidget(self.search_box)

        # ── 多选筛选行 ─
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        self.ms_nation = MultiSelectCombo("全部国家")
        self.ms_type = MultiSelectCombo("全部舰种")
        self.ms_tier = MultiSelectCombo("全部等级")
        self.ms_crew_type = MultiSelectCombo("全部类型")
        for ms in (self.ms_nation, self.ms_type, self.ms_tier, self.ms_crew_type):
            filter_row.addWidget(ms)

        self.btn_reset = QPushButton("↺")
        self.btn_reset.setToolTip("重置筛选条件")
        self.btn_reset.setFixedWidth(26)
        self.btn_reset.setStyleSheet("""
            QPushButton {
                background: #e0e0e0; border: 1px solid #c0c0c0;
                border-radius: 3px; font-size: 13px; font-weight: bold;
                padding: 0;
            }
            QPushButton:hover { background: #d0d0d0; border-color: #0078d4; }
        """)
        filter_row.addWidget(self.btn_reset)
        layout.addLayout(filter_row)

        # ── 文件列表 ─
        self.file_list = QListWidget()
        _fnt = QFont()
        _fnt.setFamilies(["Microsoft YaHei", "Segoe UI", "sans-serif"])
        _fnt.setPointSize(10)
        self.file_list.setFont(_fnt)
        self.file_list.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 3px 6px;
                font-size: 12px;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #e5f1fb;
            }
        """)
        layout.addWidget(self.file_list, stretch=1)

        # ── 状态 ─
        self._current_folder = ""
        self._all_entities: list[dict] = []
        self._last_selected_id: str = ""  # 上次选中的实体 ID（用于刷新后恢复）

        # ── 信号 ─
        self.file_list.currentTextChanged.connect(self._on_file_changed)
        self.search_box.textChanged.connect(self._apply_filter)
        self.ms_nation.selection_changed.connect(self._apply_filter)
        self.ms_type.selection_changed.connect(self._apply_filter)
        self.ms_tier.selection_changed.connect(self._apply_filter)
        self.btn_reset.clicked.connect(self._reset_filters)
        self.ms_crew_type.selection_changed.connect(self._apply_filter)
        bus.folder_selected.connect(self._on_category_selected)

    # ── 公共方法 ──────────────────────────────────────────

    def show_category(self, folder: str) -> None:
        self._current_folder = folder
        self.file_list.clear()
        self._all_entities = []

        # 筛选栏仅对 Ship / Crew 类别显示
        is_ship = folder == "Ship"
        is_crew = folder == "Crew"
        self.ms_nation.setVisible(is_ship or is_crew)
        self.ms_type.setVisible(is_ship)
        self.ms_tier.setVisible(is_ship)
        self.ms_crew_type.setVisible(is_crew)
        self.btn_reset.setVisible(is_ship or is_crew)

        if is_ship or is_crew:
            self.search_box.setPlaceholderText("🔍 搜索名称或编号...")
        else:
            self.search_box.setPlaceholderText("🔍 搜索文件名...")

        db = self._safe_db()
        if not db or not db.exists:
            return

        if is_ship:
            self._load_ship_data(db)
        elif is_crew:
            self._load_crew_data(db)
        else:
            self._load_other_data(db, folder)

        self._apply_filter()
        self.file_list.scrollToTop()

    def refresh(self) -> None:
        if self._current_folder:
            # 记住当前选中的 ID
            saved_id = self._last_selected_id
            self.show_category(self._current_folder)
            # 恢复选中并重新触发详情面板刷新
            if saved_id:
                self._last_selected_id = saved_id
                self._select_and_emit(saved_id)

    # ── 数据加载 ──────────────────────────────────────────

    def _load_ship_data(self, db):
        """从数据库加载舰船列表（含名称和筛选字段）"""
        from models.name_mapping import Mapping as NM

        # 获取所有舰船
        rows = db._conn.execute("""
            SELECT e.entity_id,
                   CASE WHEN b.ship_name_zh IS NOT NULL AND b.ship_name_zh != ''
                        THEN b.ship_name_zh ELSE e.entity_id END AS display_name,
                   e.nation, e.shiptype, e.tier
            FROM entity_registry e
            LEFT JOIN ship_basic_info b ON b.ship_id = e.entity_id
            WHERE e.entity_type='ship'
            ORDER BY e.entity_id
        """).fetchall()

        self._all_entities = [dict(r) for r in rows]

        # 填充多选筛选项
        nations = sorted(set(
            NM.NATION_MAP.get(r["nation"], r["nation"]) for r in self._all_entities if r["nation"]
        ))
        self.ms_nation.fill_items([(n, n) for n in nations])

        types = sorted(set(
            NM.SHIP_CLASS_MAP.get(r["shiptype"], r["shiptype"]) for r in self._all_entities if r["shiptype"]
        ))
        self.ms_type.fill_items([(t, t) for t in types])

        tiers = sorted(set(r["tier"] for r in self._all_entities if r["tier"]))
        self.ms_tier.fill_items([(f"{NM.LEVEL_MAP[t]} 级", t) for t in tiers])

    def _load_crew_data(self, db):
        """从数据库加载舰长列表（含国籍和类型筛选）"""
        from models.name_mapping import Mapping as NM
        rows = db._conn.execute("""
            SELECT e.entity_id, COALESCE(c.crew_name, e.entity_id) AS display_name, e.nation,
                   c.is_unique, c.is_elite, c.is_person, c.is_animated
            FROM entity_registry e
            LEFT JOIN crew_basic_info c ON c.crew_id = e.entity_id
            WHERE e.entity_type='crew'
            ORDER BY e.entity_id
        """).fetchall()
        self._all_entities = [dict(r) for r in rows]

        nations = sorted(set(
            NM.NATION_MAP.get(r["nation"], r["nation"]) for r in self._all_entities if r["nation"]
        ))
        self.ms_nation.fill_items([(n, n) for n in nations])

        # 舰长类型筛选
        crew_types = []
        if any(r.get("is_unique") for r in self._all_entities):
            crew_types.append(("传奇舰长", "unique"))
        if any(r.get("is_elite") for r in self._all_entities):
            crew_types.append(("精英舰长", "elite"))
        if any(r.get("is_person") for r in self._all_entities):
            crew_types.append(("历史人物", "person"))
        if any(r.get("is_animated") for r in self._all_entities):
            crew_types.append(("动态立绘", "animated"))
        self.ms_crew_type.fill_items(crew_types)

    def _load_other_data(self, db, folder):
        """从数据库加载非舰船类别的列表（含本地化名称）"""
        # folder → (entity_type, table_name, name_column)
        NAME_LOOKUP = {
            "Gun": ("gun", "gun_basic_info", "gun_name_zh"),
            "Projectile": ("projectile", "projectile_basic_info", "ammo_name_zh"),
            "Aircraft": ("plane", "plane_basic_info", "plane_name_zh"),
            "Ability": ("consumable", "consumable_basic_info", "display_name"),
            "Modernization": ("modernization", "modernization_basic_info", "mod_name_zh"),
        }
        lookup = NAME_LOOKUP.get(folder)
        if lookup:
            etype, tbl, name_col = lookup
            rows = db._conn.execute(f"""
                SELECT e.entity_id,
                       COALESCE(n.{name_col}, e.entity_id) AS display_name
                FROM entity_registry e
                LEFT JOIN {tbl} n ON n.{etype}_id = e.entity_id
                WHERE e.entity_type=?
                ORDER BY e.entity_id
            """, (etype,)).fetchall()
            self._all_entities = [dict(r) for r in rows]
        else:
            rows = db.list_entities(folder) or []
            self._all_entities = [{"id": r["id"], "display_name": r["id"]} for r in rows]

    # ── 筛选与显示 ──────────────────────────────────────

    def _apply_filter(self, *args):
        self.file_list.clear()
        keyword = self.search_box.text().strip().lower()

        # 获取筛选条件
        nation_vals = self.ms_nation.selected_data() if self.ms_nation.isVisible() else []
        type_vals = self.ms_type.selected_data() if self.ms_type.isVisible() else []
        tier_vals = [int(t) for t in self.ms_tier.selected_data()] if self.ms_tier.isVisible() else []
        crew_type_vals = self.ms_crew_type.selected_data() if self.ms_crew_type.isVisible() else []

        from models.name_mapping import Mapping as NM

        for ent in self._all_entities:
            eid = ent.get("entity_id") or ent.get("id") or ""
            dname = ent.get("display_name", eid)

            if nation_vals:
                en = NM.NATION_MAP.get(ent.get("nation", ""), ent.get("nation", ""))
                if en not in nation_vals:
                    continue
            if type_vals:
                et = NM.SHIP_CLASS_MAP.get(ent.get("shiptype", ""), ent.get("shiptype", ""))
                if et not in type_vals:
                    continue
            if tier_vals:
                if ent.get("tier") not in tier_vals:
                    continue
            if crew_type_vals:
                # 舰长类型：检查对应 flag 是否为 1
                has_type = False
                for ct in crew_type_vals:
                    if ent.get(f"is_{ct}"):
                        has_type = True
                        break
                if not has_type:
                    continue

            if keyword and keyword not in dname.lower() and keyword not in eid.lower():
                continue

            item = QListWidgetItem(f"📄 {dname}")
            item.setData(Qt.UserRole, eid)
            self.file_list.addItem(item)

    def _on_filter_changed(self):
        self._apply_filter()

    def _reset_filters(self):
        """一键重置所有筛选器和搜索框"""
        self.search_box.setText("")
        self.ms_nation.reset()
        self.ms_type.reset()
        self.ms_tier.reset()
        self.ms_crew_type.reset()
        self._apply_filter()

    # ── 信号槽 ──────────────────────────────────────────

    def _on_category_selected(self, folder: str) -> None:
        if folder == "__REFRESH__":
            self.refresh()
        else:
            self.show_category(folder)

    def _on_file_changed(self, text: str) -> None:
        if not text or not self._current_folder:
            return
        display = text.replace("📄 ", "").strip()
        # 从 QListWidgetItem 的 UserRole 取 ID
        item = self.file_list.currentItem()
        if item:
            eid = item.data(Qt.UserRole) or ""
            if eid:
                self._last_selected_id = eid
                self.file_selected.emit(self._current_folder, eid)
                return
        # 兜底：遍历查找
        for ent in self._all_entities:
            eid = ent.get("entity_id") or ent.get("id") or ""
            dname = ent.get("display_name", eid)
            if dname == display:
                self._last_selected_id = eid
                self.file_selected.emit(self._current_folder, eid)
                return
        self._last_selected_id = display
        self.file_selected.emit(self._current_folder, display)

    def _select_and_emit(self, entity_id: str) -> None:
        """根据 entity_id 选中列表项并发射信号刷新详情面板"""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item and item.data(Qt.UserRole) == entity_id:
                # 阻止 currentTextChanged 信号重复触发
                self.file_list.blockSignals(True)
                self.file_list.setCurrentItem(item)
                self.file_list.blockSignals(False)
                self._last_selected_id = entity_id
                self.file_selected.emit(self._current_folder, entity_id)
                return
        # 列表找不到（筛选后隐藏了），直接发射信号
        self._last_selected_id = entity_id
        self.file_selected.emit(self._current_folder, entity_id)
