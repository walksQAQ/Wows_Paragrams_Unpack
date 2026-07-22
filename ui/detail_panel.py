"""
DetailPanel —— 右侧详情展示面板（QStackedWidget，动态页面）。

完全基于数据库读取显示，不再调用分析器。
由 ModuleSelect 控制页面切换。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from functools import partial

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QTextEdit, QPushButton, QLabel, QFrame, QButtonGroup,
    QScrollArea, QSizePolicy, QGridLayout, QComboBox, QListView,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QColor

from app.signals import bus
from services.database_service import get_db
from presenters.registry import PresenterRegistry, CATEGORY_TO_ETYPE
from utils.path_utils import get_app_dir
from ui.ship_card_widget import ShipDetailGrid, ShipCardWidget, SECTION_ICONS


class DetailPanel(QWidget):
    """右侧详情面板（数据库驱动）"""

    modules_available = Signal(object)

    TEXT_STYLE = """
        QTextEdit {
            background-color: #ffffff;
            color: #1a1a1a;
            border: none;
            padding: 12px;
            font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            font-size: 13px;
        }
    """
    MONO_STYLE_LIGHT = """
        QTextEdit {
            background-color: #fafafa;
            color: #1a1a1a;
            border: none;
            padding: 12px;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 12px;
        }
    """
    MONO_STYLE_DARK = """
        QTextEdit {
            background-color: #1e1e1e;
            color: #d4d4d4;
            border: none;
            padding: 12px;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 12px;
        }
    """

    @staticmethod
    def _make_font(family: str, size: int) -> QFont:
        """安全创建字体，带备选族"""
        f = QFont()
        f.setFamilies([family, "Segoe UI", "sans-serif"])
        safe_size = size if size > 0 else 10
        f.setPointSize(safe_size)
        return f

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_category: str = ""
        self._current_filename: str = ""
        self._current_raw: dict | None = None
        self._current_analyzed: dict | None = None
        self._is_ship_mode: bool = False
        self._section_page_indices: dict[str, int] = {}
        self._default_pages: list[QTextEdit] = []
        # 船纵向流式布局状态
        self._ship_sections: list[dict] = []
        self._ship_sub_sections: dict = {}
        self._ship_container: QWidget | None = None
        self._ship_columns_layout: QHBoxLayout | None = None
        self._ship_column_widgets: list[QWidget] = []
        self._ship_column_layouts: list[QVBoxLayout] = []
        self._ship_rebuilding: bool = False
        # 子面板控制器映射：section_label → (stack, [buttons])
        self._subwidget_controllers: dict[str, tuple] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self._build_default_pages()
        self._show_hint()
        # 启动时不通知 ModuleSelect，保持空白占位
        bus.file_selected.connect(self._on_file_selected)

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时重建舰船网格（带防重入锁）"""
        super().resizeEvent(event)
        if self._is_ship_mode and self._ship_container is not None:
            self._rebuild_ship_grid()

    # ── 页面构建 ──────────────────────────────────────────

    def _build_default_pages(self) -> None:
        """创建默认三页：详情 / 数据 / 原始"""
        self._clear_pages()
        self._is_ship_mode = False
        self._section_page_indices = {}
        self._default_pages = []

        pages = [
            ("detail", self.TEXT_STYLE, self._make_font("Microsoft YaHei", 11)),
            ("data", self.MONO_STYLE_LIGHT, self._make_font("Consolas", 10)),
            ("raw", self.MONO_STYLE_DARK, self._make_font("Consolas", 10)),
        ]
        for name, style, font in pages:
            te = QTextEdit()
            te.setReadOnly(True)
            te.setFont(font)
            te.setStyleSheet(style)
            te.setObjectName(f"page_{name}")
            self.stack.addWidget(te)
            self._default_pages.append(te)

        self.stack.setCurrentIndex(0)

    def _build_ship_pages(self, sections: list[dict], extra: dict | None = None) -> None:
        """将所有 section 以纵向流式布局展示：先分列，列内纵向叠放卡片"""
        # 切换舰船时清空自定义配置缓存（仅内存）
        DetailPanel._crew_custom_cache.clear()
        self._clear_pages()
        self._is_ship_mode = True
        sub_sections = (extra or {}).get("sub_sections", {})

        # 外层容器：顶部配置栏（独立水平滚动） + 下方卡片流（独立滚动）
        outer_container = QWidget()
        outer_layout = QVBoxLayout(outer_container)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── 顶部配置栏（水平滚动独立） ──
        config_bar = (self._current_analyzed or {}).get("config_bar", {})
        if config_bar:
            bar_scroll = QScrollArea()
            bar_scroll.setWidgetResizable(True)
            bar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            bar_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
            bar_scroll.setMinimumHeight(180)
            bar_widget = self._build_top_config_bar(config_bar)
            bar_scroll.setWidget(bar_widget)
            outer_layout.addWidget(bar_scroll, stretch=0)

        # ── 下方卡片流（独立滚动） ──
        bottom_scroll = QScrollArea()
        bottom_scroll.setWidgetResizable(True)
        bottom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        bottom_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        bottom_scroll.setStyleSheet("QScrollArea{border:none;background-color:#f5f5f5;}")

        container = QWidget()
        self._ship_container = container
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 横向主布局：每列一个 QVBoxLayout
        columns_wrapper = QWidget()
        self._columns_wrapper = columns_wrapper
        self._ship_columns_layout = QHBoxLayout(columns_wrapper)
        self._ship_columns_layout.setContentsMargins(4, 0, 4, 0)
        self._ship_columns_layout.setSpacing(2)
        self._ship_columns_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(columns_wrapper, stretch=1)

        bottom_scroll.setWidget(container)
        outer_layout.addWidget(bottom_scroll, stretch=1)

        self._ship_sections = sections
        self._ship_sub_sections = sub_sections
        self._filter_sections_by_config()
        self._ship_container = columns_wrapper
        self._ship_column_widgets: list[QWidget] = []
        self._ship_column_layouts: list[QVBoxLayout] = []
        self._ship_column_layouts: list[QVBoxLayout] = []

        # 延迟重建，等布局完成后获取真实宽度
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._rebuild_ship_grid)

        # 唯一页面
        self._section_page_indices = {"全部": 0}
        self.stack.addWidget(outer_container)

    # ── EPIC 技能/天赋配置 ──
    # 内存缓存（切换舰船时清空）
    _crew_custom_cache: dict = {}

    @staticmethod
    def _epic_config_path() -> str:
        return str(get_app_dir() / "epic_skill_config.json")

    @staticmethod
    def _load_epic_config() -> dict:
        p = DetailPanel._epic_config_path()
        try:
            if Path(p).exists():
                import json
                return json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    @staticmethod
    def _save_epic_config(cfg: dict):
        p = DetailPanel._epic_config_path()
        try:
            import json
            Path(p).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _apply_epic_overrides(grid_skills: list, epic_keys: list[str], skill_svc=None, ship_type_en=""):
        """将 epic_keys 中匹配的技能重新查询为 EPIC 版本（替换整个 skill dict）"""
        if not epic_keys:
            return
        for row in grid_skills:
            for i, sd in enumerate(row):
                if sd and sd.get('skill_key') in epic_keys:
                    new_sd = skill_svc.reload_skill_with_rarity(sd['skill_key'], 'EPIC', ship_type_en) if skill_svc else None
                    if new_sd:
                        # 保留原位置的 icon_name（用于按钮图标）
                        new_sd['icon_name'] = sd.get('icon_name', '')
                        row[i] = new_sd

    @staticmethod
    def _refresh_epic_overlays(skill_btns: list, grid_skills: list, SKILL_BTN: str):
        """统一刷新所有技能按钮的 EPIC 叠加标记和 tooltip"""
        from pathlib import Path
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel
        _OVERLAY_PATH = ":/resources/pictures/icon_epic_skill.png"
        for _row in range(4):
            for _col in range(6):
                _btn = skill_btns[_row][_col] if _row < len(skill_btns) and _col < len(skill_btns[_row]) else None
                if not _btn:
                    continue
                _sd = grid_skills[_row][_col] if _row < len(grid_skills) and _col < len(grid_skills[_row]) else None
                _rarity = _sd.get('rarity', '') if _sd else ''
                _btn.setStyleSheet(SKILL_BTN)
                if _rarity in ("EPIC", "LEGENDARY"):
                    # 添加上角叠加标记
                    _existing = _btn.findChild(QLabel)
                    if not _existing:
                        _pix = QPixmap(_OVERLAY_PATH)
                        if not _pix.isNull():
                            _el = QLabel(_btn)
                            _el.setPixmap(_pix.scaled(14, 14, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                            _el.setStyleSheet("background:transparent;")
                            _el.setGeometry(0, 0, 14, 14)
                else:
                    # 移除旧的叠加标记
                    for _ch in _btn.findChildren(QLabel):
                        _ch.deleteLater()
                # 更新 tooltip 稀有度标记
                _old_tip = _btn.toolTip()
                if _old_tip:
                    if _rarity in ("EPIC", "LEGENDARY"):
                        _tag = {"EPIC": "[强化]", "LEGENDARY": "[传奇]"}.get(_rarity, "")
                        _repl = f'<span style="color:#ff6600; font-weight:normal;">{_tag}</span>'
                        if "[强化]" not in _old_tip and "[传奇]" not in _old_tip:
                            _old_tip = _old_tip.replace("</b>", f" {_repl}</b>", 1)
                    else:
                        _old_tip = _old_tip.replace(' <span style="color:#ff6600; font-weight:normal;">[强化]</span></b>', '</b>')
                        _old_tip = _old_tip.replace(' <span style="color:#ff6600; font-weight:normal;">[传奇]</span></b>', '</b>')
                    _btn.setToolTip(_old_tip)

    def _build_top_config_bar(self, config: dict) -> QWidget:
        """构建顶部配置栏：仿浩舰 4 列布局（配件/升级品/舰长/外观）"""
        _ship_type = config.get("shiptype", "")
        bar = QWidget()
        bar.setStyleSheet("""
            QWidget#ConfigBar {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
            }
        """)
        bar.setObjectName("ConfigBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(0)

        ITEM_STYLE = """
            QPushButton {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; padding: 3px 10px;
                font-size: 11px; color: #ddd; text-align: left;
            }
            QPushButton:hover { background: #4a4a4a; border-color: #888; }
        """
        COL_TITLE = "font-size:11px; font-weight:bold; color:#444; padding:0 0 3px 0;"

        def _col(title: str) -> tuple[QWidget, QVBoxLayout]:
            w = QWidget(); cl = QVBoxLayout(w)
            cl.setContentsMargins(8,4,8,4); cl.setSpacing(2)
            cl.setAlignment(Qt.AlignmentFlag.AlignTop)
            tl = QLabel(title); tl.setStyleSheet(COL_TITLE)
            cl.addWidget(tl)
            return w, cl

        # ── 第1列：配件（基于 ShipUpgradeInfo，含所有升级类型） ──
        col1, l1 = _col("配件")
        upgrades = config.get("upgrades", [])

        UC_ORDER = ["_Artillery", "_Torpedoes", "_Hull", "_Engine",
                    "_Suo", "_Fighter", "_DiveBomber", "_TorpedoBomber", "_SkipBomber", "_MineBomber", "_FlightControl"]
        UC_ICONS = {"_Artillery": "🔫", "_Torpedoes": "💣", "_Hull": "🚢",
                    "_Engine": "⚙", "_Suo": "📡",
                    "_Fighter": "✈", "_DiveBomber": "💥", "_TorpedoBomber": "⚓",
                    "_FlightControl": "🎯", "_SkipBomber": "💥", "_MineBomber": "💣"}
        UC_NAMES = {"_Artillery": "主炮", "_Torpedoes": "鱼雷", "_Hull": "船体",
                    "_Engine": "引擎", "_Suo": "火控",
                    "_Fighter": "攻击机", "_DiveBomber": "俯冲轰炸机",
                    "_TorpedoBomber": "鱼雷轰炸机", "_FlightControl": "飞控",
                    "_SkipBomber": "弹跳轰炸机", "_MineBomber": "水雷轰炸机"}
        UC_IMAGE_MAP = {
            "_Artillery": "module_Artillery.png",
            "_Torpedoes": "module_Torpedoes.png",
            "_Hull": "module_Hull.png",
            "_Engine": "module_Engine.png",
            "_Suo": "module_Suo.png",
            "_Fighter": "module_Fighter.png",
            "_DiveBomber": "module_DiveBomber.png",
            "_TorpedoBomber": "module_TorpedoBomber.png",
            "_SkipBomber": "module_SkipBomber.png",
            "_MineBomber": "module_MineBomber.png",
        }
        MODULES_IMAGE_DIR = ":/resources/pictures/modules"
        SLOT2SEC = {
            "artillery": "主炮", "torpedoes": "鱼雷", "hull": "船体",
            "engine": "引擎", "atba": "副炮",
            "secondary_artillery": "次级主炮", "airDefense": "防空",
        }

        def _mod_to_letter(mod_id: str) -> str:
            return mod_id[0] if mod_id else "A"

        # 收集各槽位的模块选项：只取该升级类型自己的主槽位
        # 映射: uc_type → 自己的主 slot_type
        UC_OWN_SLOT = {
            "_Artillery": "artillery", "_Torpedoes": "torpedoes",
            "_Hull": "hull", "_Engine": "engine", "_Suo": "fireControl",
            "_Fighter": "fighter", "_DiveBomber": "diveBomber",
            "_TorpedoBomber": "torpedoBomber", "_FlightControl": "flightControl",
            "_SkipBomber": "skipBomber", "_MineBomber": "mineBomber",
        }
        uc_options: dict[str, list[dict]] = {}  # ut → [{"id":component_id, "key":upgrade_key, "name":...}]
        hull_affects: dict[str, list[str]] = {}
        for up in upgrades:
            ut = up["type"]
            comps = up["components"]
            # 只取该类型自己的主槽位
            own_slot = UC_OWN_SLOT.get(ut)
            if own_slot and own_slot in comps:
                uc_options.setdefault(ut, [])
                upgrade_key = up["key"]
                upgrade_name = up.get("key_name", upgrade_key)
                # 用 upgrade_key 去重，避免同一升级项重复出现
                if not any(item.get("key") == upgrade_key for item in uc_options[ut]):
                    # 取第一个组件 ID 保留用于 letter 提取
                    mods = comps[own_slot]
                    first_mid = mods[0]["id"] if mods else upgrade_key
                    uc_options[ut].append({
                        "id": first_mid,
                        "key": upgrade_key,
                        "name": upgrade_name,
                    })
            # hull 还需要记录兼容关系
            if ut == "_Hull":
                for slot_type, mods in comps.items():
                    for m in mods:
                        mid = m["id"]
                        letter = _mod_to_letter(mid)
                        affected = set()
                        for st in comps:
                            sec = SLOT2SEC.get(st)
                            if sec:
                                affected.add(sec)
                        hull_affects[letter] = sorted(affected)

        BTN_STYLE = """
            QPushButton {
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 6px; padding: 2px;
                font-size: 9px; color: #ddd;
                min-width: 40px; min-height: 40px;
                max-width: 40px; max-height: 40px;
            }
            QPushButton:hover {
                background: #4a4a4a;
                border-color: #1a73e8;
            }
            QPushButton:checked {
                background: #1a73e8; color: #fff; border-color: #1a73e8;
            }
        """

        def _build_module_group(ut: str, options: list, un: str, icon: str) -> QWidget:
            """构建单个配件组（标题 + 按钮行）"""
            group = QWidget()
            gl = QVBoxLayout(group)
            gl.setContentsMargins(0,0,0,0); gl.setSpacing(3)
            gl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title = QLabel(f"{icon} {un}")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("font-size:10px; color:#444;")
            gl.addWidget(title)

            btn_row = QWidget()
            bl = QHBoxLayout(btn_row)
            bl.setContentsMargins(0,0,0,0); bl.setSpacing(3)
            bl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # 每组内按钮互斥（同一大类下只能选其一）
            btn_group = QButtonGroup(group)
            btn_group.setExclusive(True)

            for i, mod in enumerate(options):
                # 用 upgrade_key 作为显示标识，保留 component_id 用于 letter 提取
                mid = mod.get("key", mod["id"])
                display_name = mod.get("name", mid)
                letter = _mod_to_letter(mod["id"])
                btn = QPushButton("")
                btn.setFixedSize(40, 40)
                btn.setCheckable(True)
                btn.setStyleSheet(BTN_STYLE)
                btn.setToolTip(display_name)
                btn.setObjectName(f"mod_{ut}_{mid}")
                btn_group.addButton(btn, i)

                # 加载模块图片作为按钮图标
                img_file = UC_IMAGE_MAP.get(ut)
                if img_file:
                    _qp = f"{MODULES_IMAGE_DIR}/{img_file}"
                    pixmap = QPixmap(_qp)
                    if not pixmap.isNull():
                        scaled = pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        btn.setIcon(QIcon(scaled))
                        btn.setIconSize(QSize(24, 24))
                    else:
                        btn.setText("缺少图片")
                        btn.setStyleSheet(BTN_STYLE.replace("font-size: 9px;", "font-size: 8px;").replace("color: #333;", "color: #999;"))

                if ut == "_Hull":
                    btn.clicked.connect(
                        partial(self._on_hull_module_click, mod["id"])
                    )
                elif ut == "_Engine":
                    engine_key = mod["id"]
                    btn.clicked.connect(
                        partial(self._on_engine_module_click, engine_key)
                    )
                elif ut == "_Suo":
                    fc_key = mod["id"]
                    btn.clicked.connect(
                        partial(self._on_fire_control_click, fc_key)
                    )
                elif ut in ("_Fighter", "_DiveBomber", "_TorpedoBomber", "_FlightControl", "_SkipBomber", "_MineBomber"):
                    part_id = mod["id"]
                    btn.clicked.connect(
                        partial(self._on_aircraft_module_click, ut, part_id)
                    )
                else:
                    # 其余模块（主炮、鱼雷、防空等）：传完整组件 ID
                    btn.clicked.connect(
                        partial(self._on_other_module_click, ut, mod["id"])
                    )
                bl.addWidget(btn)
                if i == 0:
                    btn.setChecked(True)

            gl.addWidget(btn_row)
            return group

        # 所有配件模块整合到一行，居中对齐
        ALL_UC = ["_Artillery", "_Torpedoes", "_Hull", "_Engine", "_Suo",
                   "_Fighter", "_DiveBomber", "_TorpedoBomber", "_SkipBomber", "_MineBomber"]

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
        rl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for ut in ALL_UC:
            options = uc_options.get(ut, [])
            if not options:
                continue
            un = UC_NAMES.get(ut, ut)
            icon = UC_ICONS.get(ut, "📦")
            rl.addWidget(_build_module_group(ut, options, un, icon))

        l1.addWidget(row)

        l1.addStretch()
        layout.addWidget(col1, stretch=1)

        # 分隔线
        _ship_status = config.get("group_status", "")
        _hide_config = _ship_status in ("disabled", "unavailable", "event", "preserved")
        for section_key in ["upgrade", "signal", "commander"]:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setStyleSheet("QFrame{color:#c8c8c8;}")
            sep.setFixedWidth(1)
            layout.addWidget(sep)

            if _hide_config:
                _titles = {"upgrade": "升级品", "signal": "信号旗", "commander": "舰长"}
                col, cl = _col(_titles.get(section_key, ""))
                _ph = QLabel("该舰船状态\n不支持此功能")
                _ph.setStyleSheet("color:#bbb; font-size:10px; padding:4px;")
                _ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cl.addWidget(_ph)
                cl.addStretch()
                layout.addWidget(col, stretch=1)
                continue

            if section_key == "upgrade":  # 第2列：升级品
                col, cl = _col("升级品")
                # 从实际可用的升级品数据确定槽位数量（部分特殊船有例外）
                mods_by_slot: dict[int, list[dict]] = {}
                for m in config.get("modernizations", []):
                    mods_by_slot.setdefault(m["slot"], []).append(m)
                max_slots = max(mods_by_slot.keys()) + 1 if mods_by_slot else 0
                modernization_dir = ":/resources/pictures/modernization"
                if not hasattr(self, '_selected_mods'):
                    self._selected_mods: dict[int, dict] = {}
                if not hasattr(self, '_selected_skill_mods'):
                    self._selected_skill_mods: dict[str, dict] = {}
                if not hasattr(self, '_selected_signal_flags'):
                    self._selected_signal_flags: dict[int, dict] = {}
                if not hasattr(self, '_selected_signal_flags'):
                    self._selected_signal_flags: dict[int, dict] = {}
                upgrade_container = QWidget()
                uc_layout = QHBoxLayout(upgrade_container)
                uc_layout.setContentsMargins(0,0,0,0)
                uc_layout.setSpacing(6)
                uc_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                SLOT_STYLE = """
                    QPushButton {
                        background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
                        padding: 2px; min-width: 36px; min-height: 36px; max-width: 36px; max-height: 36px;
                    }
                    QPushButton:hover { background: #4a4a4a; border-color: #1a73e8; }
                    QPushButton:checked { background: #1a73e8; border-color: #1a73e8; }
                """
                for i in range(max_slots):  # 根据等级限制槽位数量
                    slot_mods = mods_by_slot.get(i, [])
                    # 每个插槽一列（编号=slot+1），即使无升级品也占位
                    col_w = QWidget()
                    col_layout = QVBoxLayout(col_w)
                    col_layout.setContentsMargins(0,0,0,0)
                    col_layout.setSpacing(2)
                    col_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                    # 槽位标题
                    title = QLabel(f"槽{i+1}")
                    title.setStyleSheet("font-size:9px;color:#ccc;font-weight:bold;")
                    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    col_layout.addWidget(title)
                    if slot_mods:
                        for mod in slot_mods:
                            mid = mod["mod_id"]
                            ob = QPushButton()
                            ob.setFixedSize(36, 36)
                            ob.setCheckable(True)
                            ob.setStyleSheet(SLOT_STYLE)
                            ob.setObjectName(mid)
                            img = f"{modernization_dir}/icon_modernization_{mid}.png"
                            pix = QPixmap(img)
                            if not pix.isNull():
                                ob.setIcon(QIcon(pix.scaled(28,28,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
                                ob.setIconSize(QSize(28,28))
                            else:
                                ob.setText(mid[:2])
                                ob.setStyleSheet(SLOT_STYLE.replace("padding:2px;","padding:2px;font-size:8px;color:#bbb;"))
                            tt_parts = [mod.get("name", mid)]
                            mod_dict = mod.get("modifiers", {})
                            if mod_dict:
                                from models.name_mapping import Mapping as NMM
                                # 沿用 modernization_analyzer 的显示逻辑
                                NO_PCT = {"planeExtraHangarSize", "AAAuraDamageBonus", "additionalConsumables",
                                          "planeAdditionalConsumables", "AAExtraBubbles",
                                          "smokeGeneratorAdditionalConsumables", "asNumPacksBonus",
                                          "speedBoostersAdditionalConsumables"}
                                FACTOR_KEYS = {"AABubbleDamageBonus"}
                                SECOND_KEYS = {"crashCrewWorkTimeBonus", "torpedoBomberAimingTime", "fighterAimingTime"}
                                KM_KEYS = {"visionXRayMineDist", "visionXRayTorpedoDist"}
                                SP_PCT_KEYS = {"engineBackwardForsageMaxSpeed", "engineBackwardForsagePower",
                                               "engineForwardForsageMaxSpeed", "engineForwardForsagePower",
                                               "hydrophoneWaveSpeedCoeff", "regeneratedHPPartCoef", "boostCoeffForsage"}
                                tt_parts.append("─" * 20)
                                for mk, mv in sorted(mod_dict.items()):
                                    label = NMM.MODIFIER_MAP.get(mk, mk)
                                    if isinstance(mv, dict):
                                        mv = mv.get(_ship_type) or next((v for v in mv.values() if isinstance(v, (int, float))), 0)
                                    try:
                                        mv_f = float(mv)
                                        if mv_f == 0:
                                            continue
                                        if mk in NO_PCT:
                                            pct = f"{'+' if mv_f > 0 else ''}{mv_f:g}"
                                        elif mk in FACTOR_KEYS:
                                            pct = f"{'+' if mv_f > 0 else ''}{round(mv_f * 7, 0):.0f}"
                                        elif mk in SECOND_KEYS:
                                            pct = f"{'+' if mv_f > 0 else ''}{mv_f:g}s"
                                        elif mk in KM_KEYS:
                                            pct = f"{mv_f / 1000:g}km"
                                        elif mk in SP_PCT_KEYS:
                                            pct_val = round(mv_f * 100, 1)
                                            if pct_val == int(pct_val):
                                                pct_val = int(pct_val)
                                            pct = f"{'+' if pct_val > 0 else ''}{pct_val}%"
                                        else:
                                            pct_val = round((mv_f - 1.0) * 100, 3)
                                            sign = "+" if pct_val > 0 else ""
                                            pct = f"{sign}{pct_val:g}%"
                                        tt_parts.append(f"{label}: {pct}")
                                    except (ValueError, TypeError):
                                        tt_parts.append(f"{label}: {mv}")
                                    except (ValueError, TypeError):
                                        tt_parts.append(f"{label}: {mv}")
                            ob.setToolTip("\n".join(tt_parts))
                            ob.clicked.connect(lambda checked, si=i, m=mod, btn=ob: self._on_mod_opt_click(si, m, btn))
                            if self._selected_mods.get(i) and self._selected_mods[i]["mod_id"] == mid:
                                ob.setChecked(True)
                            col_layout.addWidget(ob, alignment=Qt.AlignmentFlag.AlignCenter)
                    col_layout.addStretch()
                    uc_layout.addWidget(col_w)
                cl.addWidget(upgrade_container)
                layout.addWidget(col, stretch=1)

            elif section_key == "signal":  # 第3列：信号旗（6槽位，图片按钮）
                # WG 服暂无数信号旗数据
                try:
                    from app.application import app as _app_ctx2
                    _is_wg_sig = _app_ctx2.ctx.wows_type == "Wargaming"
                except Exception:
                    _is_wg_sig = False

                col, cl = _col("信号旗")

                if _is_wg_sig:
                    _wg_ph = QLabel("Wargaming 服务器\n暂不支持信号旗系统")
                    _wg_ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    _wg_ph.setStyleSheet("color:#666; font-size:11px; padding:20px 8px;")
                    cl.addWidget(_wg_ph)
                    cl.addStretch()
                    layout.addWidget(col, stretch=1)
                    continue

                signal_flags_dir = ":/resources/pictures/signal_flags"
                slot_types_dir = ":/resources/pictures/signal_flags/slot_types"
                signal_slots = config.get("signal_slots", [])
                SIG_BTN = """
                    QPushButton { background: #3a3a3a; border: 1px solid #555;
                    border-radius: 4px; padding: 0; }
                    QPushButton:hover { background: #4a4a4a; border-color: #1a73e8; }
                    QPushButton:checked { background: #4a4a4a; border: 2px solid #1a73e8; }
                """
                RARITY_NAMES = {1: "标准", 2: "特殊", 3: "稀有", 4: "精英"}
                from models.name_mapping import Mapping as _NM

                def _fmt_mod(mk, mv):
                    """格式化修饰符显示值：Bonus 类为加法值，其余为乘法因子"""
                    cn = _NM.MODIFIER_MAP.get(mk, mk)
                    # 处理分舰种字典
                    if isinstance(mv, dict):
                        _st = config.get("shiptype", "")
                        mv = mv.get(_st) or next((v for v in mv.values() if isinstance(v, (int, float))), 0)
                    if isinstance(mv, (int, float)):
                        if 'Bonus' in mk:
                            return f"{cn}: {mv*100:+.1f}%"
                        else:
                            pct = (mv - 1) * 100
                            return f"{cn}: {pct:+.1f}%"
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
                    btn.setToolTip(f"{flag_data.get('name','')}{mods_str}\n{flag_data.get('label','')}")

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
                    lbl.setStyleSheet("font-size:8px;color:#aaa;")
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    grid.addWidget(lbl, 1, si, Qt.AlignmentFlag.AlignCenter)
                cl.addWidget(slot_grid)

                # 信号旗选择面板：预先为每个槽位创建一页
                flag_stack = QStackedWidget()
                flag_stack.setVisible(False)
                flag_stack.setStyleSheet("QStackedWidget{background:#2a2a2a;border:1px solid #555;border-radius:4px;max-height:300px;}")
                flag_stack.setMaximumWidth(220)
                flag_stack.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
                _active_slot = [-1]  # 当前展开的槽位索引，-1=无
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
                        rarity_label = RARITY_NAMES.get(f.get("rarity", 0), str(f.get("rarity", 0)))
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
                        mitem.setToolTip(f"{disp_name}\n{mods_str}" if mods_str else disp_name)
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
                    btn.setToolTip(f"{flag_data.get('name','')}{mods_str}\n{slot_label}")
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
                    all_mods = {}
                    _st = config.get("shiptype", "")
                    if hasattr(self, '_selected_mods'):
                        for m in self._selected_mods.values():
                            mods = m.get("modifiers", {})
                            if isinstance(mods, dict):
                                for k, v in mods.items():
                                    if isinstance(v, dict):
                                        v = v.get(_st) or next((x for x in v.values() if isinstance(x, (int, float))), 1.0)
                                    all_mods[k] = v
                    for fd in self._selected_signal_flags.values():
                        mods = fd.get("modifiers", {})
                        if isinstance(mods, dict):
                            for k, v in mods.items():
                                if isinstance(v, dict):
                                    v = v.get(_st) or next((x for x in v.values() if isinstance(x, (int, float))), 1.0)
                                all_mods[k] = v
                    self._refresh_data_only(all_mods if all_mods else None)

                cl.addStretch()
                layout.addWidget(col, stretch=1)

            elif section_key == "commander":  # 第4列：舰长技能
                # WG 服暂无舰长系统占位
                try:
                    from app.application import app as _app_ctx
                    _is_wg = _app_ctx.ctx.wows_type == "Wargaming"
                except Exception:
                    _is_wg = False

                col, cl = _col("舰长技能")

                if _is_wg:
                    _wg_placeholder = QLabel("Wargaming 服务器\n暂不支持舰长技能系统")
                    _wg_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    _wg_placeholder.setStyleSheet("color:#666; font-size:11px; padding:20px 8px;")
                    cl.addWidget(_wg_placeholder)
                    cl.addStretch()
                    layout.addWidget(col, stretch=1)
                    continue

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

                # 补充 QListView 及 QScrollBar 的 QSS 样式
                self._crew_combo.setStyleSheet("""
                    QComboBox {
                        font-size: 11px;
                        padding: 2px 4px;
                        background: #fff;
                    }
                    QComboBox QAbstractItemView {
                        min-width: 200px;
                        background: #ffffff;
                        color: #222;
                        selection-background-color: #1a73e8;
                        selection-color: #ffffff;
                        border: 1px solid #ccc;
                        outline: none;
                        padding: 2px;
                    }
                    /* 明确指定垂直滚动条样式与宽度 */
                    QComboBox QAbstractItemView QScrollBar:vertical {
                        width: 10px;
                        background: #f0f0f0;
                        border: none;
                        margin: 0px;
                        border-radius: 5px;
                    }
                    QComboBox QAbstractItemView QScrollBar::handle:vertical {
                        background: #aaa;
                        min-height: 20px;
                        border-radius: 5px;
                        margin: 2px;
                    }
                    QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {
                        background: #888;
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
                """)
                self._crew_data: list[dict] = []  # 存储所有舰长条目

                self._crew_customize_btn = QPushButton("✎")
                self._crew_customize_btn.setToolTip("自定义舰长技能/天赋")
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
                    except Exception:
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
                self._skill_pts_label.setStyleSheet("font-size:10px; color:#444; padding:2px 0;")
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

                def _format_trigger_cond(ttype: str, divider: float) -> str:
                    """格式化触发条件描述"""
                    cond_map = {
                        "potentialDamageRatio": f"每积累 {divider:.0f} 潜在伤害时触发1次",
                        "entityIsInvisibleTrigger": "当战舰未被敌方发现时",
                        "activeAirDefense": "当防空炮开火时",
                        "visibleEnemyWithinGsTrigger": "当副炮射程内存在敌军战舰时",
                        "activationOnBurnFlood": "战舰上每个活跃的火源和进水点",
                        "atbaHeat": "存在手动选择的副炮集火目标时",
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
                        return "获得特定勋带时触发"
                    if ttype == "activationOnPingTargetsCount":
                        return "每用声呐标记一艘敌舰时"
                    if ttype == "activationOnEntityVisibilityFlags":
                        return "当被被敌人发现或被敌方潜艇的被动声呐探测时"
                    if ttype == "submarineHydrophone":
                        return "当战舰位于潜望镜深度或工作深度时"
                    if ttype == "activationOnBuoyancyState":
                        return "处于特定深度状态时"
                    return cond_map.get(ttype, f"触发条件: {ttype} ({divider})")

                def _format_skill_mod(mods: dict, st: str) -> list[str]:
                    """格式化技能加成描述，返回每行一条的列表"""
                    _mm = _MM
                    # 特殊修饰符覆盖描述
                    _desc_override = {
                        "restoreForsage": "完全恢复舰载机中队飞机最后一个攻击编队的引擎加力",
                        "fireResistanceEnabled": "最大火灾次数-1",
                    }
                    # 隐藏的修饰符（不在技能提示中显示）
                    _hidden_mods = {"torpedoDetectionCoefficientByPlane"}
                    _hidden_prefixes = ("massHeal", "vampireDamage")
                    # 按战舰等级区分的修饰符
                    _tier_based_keys = {
                        "callFightersAdditionalPlanesHighLevel",
                        "callFightersAdditionalPlanesLowLevel",
                    }
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
                            _add_mod_line(lines, zh, mv, _force_pct=True)
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
                                lines.append(f'{_w}  {_sign}{_pct}')
                            continue
                        elif mk == "shootShiftBatteryLastChanceCoeff":
                            # 每消耗1%下潜能力的变化
                            _pct = f"+{mv:.2f}%"
                            lines.append(f'被敌方炮弹攻击的误差  {_pct}')
                            continue
                        elif mk == "batteryRegenBatteryLastChanceCoeff":
                            # 每消耗1%下潜能力的变化
                            _pct = f"+{mv:.2f}%"
                            lines.append(f'每秒下潜能力恢复  {_pct}')
                            continue
                        elif mk in ("GMHECSDamageCoeff", "GMSHECSDamageCoeff"):
                            # 高爆和半穿甲弹分开显示
                            if isinstance(mv, dict):
                                _he = mv.get("HE", mv.get("he", None))
                                _cs = mv.get("CS", mv.get("cs", mv.get("SAP", None)))
                                if _he is not None:
                                    _add_mod_line(lines, "高爆弹伤害", _he)
                                if _cs is not None:
                                    _add_mod_line(lines, "半穿甲弹伤害", _cs)
                            else:
                                _add_mod_line(lines, _mm.get(mk, mk), mv)
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
                                _add_mod_line(lines, zh, v, _force_pct=(mk in _pct_keys))
                            else:
                                for k, v in mv.items():
                                    if isinstance(v, (int, float)):
                                        _add_mod_line(lines, f"{zh} ({k})", v, _force_pct=(mk in _pct_keys))
                                        break
                        else:
                            _add_mod_line(lines, zh, mv, _force_pct=(mk in _pct_keys))
                    return lines

                def _add_mod_line(lines, label, v, _force_pct=False):
                    """添加一行修饰符描述（自动判断类型）"""
                    if isinstance(v, bool):
                        lines.append(f"启用 {label}" if v else label)
                    elif isinstance(v, (int, float)):
                        # 强制百分比（如 uwCoeffBonus: 7 = +7.00%）
                        if _force_pct:
                            lines.append(f"{label} +{v:.2f}%" if v >= 0 else f"{label} {v:.2f}%")
                        # 乘数百分比（如 1.10 = +10.00%，0.60 = -40.00%）
                        elif isinstance(v, float) and v < 2.0:
                            pct = (v - 1.0) * 100
                            lines.append(f"{label} {pct:+.2f}%")
                        # 整数值保留整数显示
                        elif isinstance(v, int) or (isinstance(v, float) and v == int(v)):
                            _iv = int(v)
                            lines.append(f"{label} {_iv:+.0f}" if _iv >= 0 else f"{label} {_iv:.0f}")
                        else:
                            lines.append(f"{label} {v:+.2f}" if v >= 0 else f"{label} {v:.2f}")
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
                        _cur_ship_type = _cb.get("shiptype", "") if isinstance(_cb, dict) else ""
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
                                    _additive_keys = {"additionalConsumables", "planeAdditionalConsumables", "planeExtraHangarSize",
                                                      "extraFighterCount", "asNumPacksBonus", "healthPerLevel", "planeHealthPerLevel",
                                                      "speedBoostersAdditionalConsumables", "smokeGeneratorAdditionalConsumables",
                                                      "torpedoReloaderAdditionalConsumables"}
                                    if k in _additive_keys:
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
                                icon_path = f":/resources/pictures/skills/{icon_name}.png"
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
                                _epic_pix = QPixmap(":/resources/pictures/icon_epic_skill.png")
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
                                    tip_lines.append(f'<div style="color:#ccc; margin-top:2px;">{skill_desc}</div>')
                                # 特定技能不做加成词条显示
                                _skip_mod_skills = {"detection_alert", "detection_aiming", "planes_forsage_renewal", "maneuverability", "detection_direction", "depth_charge_bomber_alert", "submarine_danger_alert"}
                                if mods and icon_name not in _skip_mod_skills:
                                    tip_lines.append('<hr style="border-color:#444; margin:4px 0;">')
                                    mod_lines = _format_skill_mod(mods, cur_shiptype)
                                    for _ml in mod_lines:
                                        tip_lines.append(f'<div style="color:#aaa; margin-top:2px;">{_ml}</div>')
                                # 触发条件与触发段加成
                                if trigger and trigger.get("triggerType"):
                                    ttype = trigger.get("triggerType", "")
                                    divider = trigger.get("dividerValue", 1.0)
                                    tmods = trigger.get("modifiers", {})
                                    if tmods:
                                        cond_text = _format_trigger_cond(ttype, divider)
                                        tip_lines.append(f'<div style="color:#ffa; margin-top:2px; font-style:italic;">◇ {cond_text}</div>')
                                        # atbaHeat：显示升温/冷却详细描述
                                        if ttype == "atbaHeat":
                                            heat = trigger.get("heatInterpolator", [])
                                            cool = trigger.get("coolingInterpolator", [])
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
                                        # activationOnRibbons：显示勋带要求与持续时间
                                        if ttype == "activationOnRibbons":
                                            _rib_types = trigger.get("triggerRibbonsTypes", [])
                                            _rib_num = trigger.get("triggerRibbonsNum", 1)
                                            _dur = trigger.get("duration", 0)
                                            _rib_labels = [_RIBBON_NAMES.get(str(t), f"勋带{t}") for t in _rib_types]
                                            _cond_parts = []
                                            if _rib_labels:
                                                _cond_parts.append("获得" + "、".join(_rib_labels))
                                            if _rib_num > 1:
                                                _cond_parts[-1] += f" {_rib_num}次"
                                            if _dur > 0:
                                                tip_lines.append(f'<div style="color:#aaa; margin-top:1px; font-size:10px;">{"、".join(_cond_parts)}后 {_dur:.0f} 秒内</div>')
                                        # activationOnBuoyancyState：显示深度状态
                                        if ttype == "activationOnBuoyancyState":
                                            _states = trigger.get("buoyancyStates", [])
                                            if _states:
                                                _depth_names = getattr(_NM, 'DEPTH_MAP', {})
                                                _labels = [_depth_names.get(s, s) for s in _states]
                                                tip_lines.append(f'<div style="color:#aaa; margin-top:1px; font-size:10px;">当战舰位于{"或".join(_labels)}时</div>')
                                        for _ml in _format_skill_mod(tmods, cur_shiptype):
                                            tip_lines.append(f'<div style="color:#aaa; margin-top:2px;">{_ml}</div>')
                                tip_lines.append('</div>')
                                btn.setToolTip("\n".join(tip_lines))
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
                                       trigger_damage_type, trigger_ribbon_types, trigger_ribbons_num
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
                                        return f"战舰血量低于 {sk_row.get('damage_percent_threshold', 0)*100:.0f}% 时触发"
                                    elif trig_type == "enemyVehiclesDead":
                                        return f"敌方舰艇被击沉时触发"
                                    elif trig_type == "rageMode":
                                        return f"激活作战指令时触发"
                                    return tzh

                                def _format_effect(effect_key, effect_val, mod_map, cur_st):
                                    """格式化一条效果描述（cur_st=当前舰船种类）"""
                                    lines = []
                                    for k, v in effect_val.items():
                                        if k in ("uniqueType", "percentTalent", "levelDependent", "workTime"):
                                            continue
                                        zh = mod_map.get(k, k)
                                        is_pct = effect_val.get("percentTalent", False)
                                        if isinstance(v, dict):
                                            # 按舰种区分（如 visibilityDistCoeff）
                                            if cur_st and cur_st in v:
                                                sv = v[cur_st]
                                                _add_talent_line(lines, zh, sv, is_pct)
                                            else:
                                                for skey, sv in v.items():
                                                    if isinstance(sv, (int, float)):
                                                        _add_talent_line(lines, f"{zh} ({skey})", sv, is_pct)
                                                        break
                                        else:
                                            _add_talent_line(lines, zh, v, is_pct)
                                    return "\n".join(lines) if lines else None

                                def _add_talent_line(ln, label, v, is_pct):
                                    if isinstance(v, bool):
                                        ln.append(f"{'启用' if v else ''} {label}")
                                    elif isinstance(v, (int, float)):
                                        if is_pct:
                                            pct = (v - 1.0) * 100
                                            sign = "+" if pct >= 0 else ""
                                            ln.append(f"{sign}{pct:.1f}% {label}")
                                        elif isinstance(v, float) and 0.5 <= v <= 2.0:
                                            pct = (v - 1.0) * 100
                                            sign = "+" if pct >= 0 else ""
                                            ln.append(f"{sign}{pct:.1f}% {label}")
                                        else:
                                            ln.append(f"{label} {v:+.0f}" if v else f"{label} {v:.0f}")

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
                                    btn.setToolTip("\n".join(tip_lines))
                                    self._us_layout.insertWidget(self._us_layout.count() - 1, btn)
                        except Exception:
                            pass

                # 保存基础样式表，选中颜色变更时重设
                _combo_base_qss = self._crew_combo.styleSheet()
                def _sync_combo_color():
                    _idx = self._crew_combo.currentIndex()
                    _item = _model.item(_idx)
                    if _item:
                        _brush = _item.foreground()
                        if _brush is not None:
                            self._crew_combo.setStyleSheet(_combo_base_qss + f"\nQComboBox {{ color: {_brush.color().name()}; }}")
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
                                        _tbtn.setStyleSheet("""
                                            QPushButton { background:#1a1a1a; border:2px solid #ffc107;
                                                          border-radius:6px; min-width:52px; min-height:52px;
                                                          max-width:52px; max-height:52px;
                                                          font-size:9px; color:#ffc107; padding:0px; }
                                            QPushButton:hover { background:#2a2a2a; border-color:#ffd54f; }
                                        """)
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

        return bar

    def _on_aircraft_module_click(self, ut: str, part_id: str) -> None:
        """舰载机模块按钮点击：按组件 ID 查找对应配置页"""
        ctrl = self._subwidget_controllers.get(ut)
        if ctrl is None:
            return
        stack, btns = ctrl
        for i in range(stack.count()):
            w = stack.widget(i)
            wname = w.objectName() or ""
            if part_id in wname:
                stack.setCurrentIndex(i)
                return

    def _on_engine_module_click(self, engine_key: str) -> None:
        """引擎模块按钮点击：不切换配置字母，只刷新引擎数据"""
        self._active_engine_key = engine_key
        self._refresh_data_only()

    def _on_fire_control_click(self, fc_key: str) -> None:
        """火控配件按钮点击：不切换配置字母，只刷新主炮系数"""
        self._active_fire_control_key = fc_key
        self._refresh_data_only()

    def _on_hull_module_click(self, hull_key: str) -> None:
        """船体模块按钮点击：记录完整组件 ID"""
        self._active_hull_key = hull_key
        self._active_config_letter = hull_key[0] if hull_key else "A"
        self._refresh_data_only()

    def _on_other_module_click(self, ut: str, mod_key: str) -> None:
        """其余模块按钮点击（主炮/鱼雷/防空等）"""
        self._active_module_keys[ut] = mod_key
        self._active_config_letter = mod_key[0] if mod_key else "A"
        self._refresh_data_only()

    def _on_topbar_module_click(self, section_labels: list[str], config_letter: str):
        """顶栏模块按钮点击：切换到对应子面板的配置页，支持同时切多个 section"""
        # 记录当前激活的配置字母，用于过滤下方数据段
        self._active_config_letter = config_letter
        # 刷新数据显示
        self._refresh_data_only()
        for sl in section_labels:
            ctrl = self._subwidget_controllers.get(sl)
            if ctrl is None:
                continue
            stack, btns = ctrl
            target_name = f"{config_letter} 配置"
            if btns is not None:
                # 有标签按钮的模式：模拟点击
                found = False
                for i, btn in enumerate(btns):
                    if target_name in btn.text():
                        self._on_sub_btn(stack, i, btns)
                        found = True
                        break
                if not found:
                    # 后备：按 section label 匹配按钮文本
                    for i, btn in enumerate(btns):
                        if sl in btn.text():
                            self._on_sub_btn(stack, i, btns)
                            break
            else:
                # 无标签按钮模式：直接按序号切换 stack
                for i in range(stack.count()):
                    w = stack.widget(i)
                    # 通过 widget 名称判断配置字母
                    wname = w.objectName() or ""
                    if config_letter in wname or target_name in wname or sl in wname:
                        stack.setCurrentIndex(i)
                        break

    def _rebuild_ship_grid(self):
        """重建纵向流式布局：按宽度自动切换三列/四列布局"""
        if self._ship_rebuilding or not self._ship_container:
            return
        self._ship_rebuilding = True
        self._subwidget_controllers.clear()
        try:
            if not self._ship_sections:
                return

            # 根据宽度自动切换布局
            avail_w = self._ship_container.width() or 800
            USE_4_COL = avail_w >= 1200

            if USE_4_COL:
                cols = 4
                # 四列布局：主炮/副炮等武器位于舰载机列左侧
                LABEL_TO_COL = {
                    "基础属性": 0, "消耗品数据": 0,
                    "船体": 1, "支援": 1,
                    "主炮": 2, "副炮": 2, "次级主炮": 2,
                    "鱼雷": 2, "防空": 2, "深水炸弹": 3,
                    "舰载机": 3,
                }
            else:
                cols = 3
                # 三列布局：深水炸弹移到第3列
                LABEL_TO_COL = {
                    "基础属性": 0, "消耗品数据": 0,
                    "船体": 1, "主炮": 1, "副炮": 1, "次级主炮": 1,
                    "鱼雷": 1, "防空": 1, "深水炸弹": 2,
                    "舰载机": 2, "支援": 2,
                }
            # 先确保列容器数量匹配
            while len(self._ship_column_widgets) < cols:
                col_w = QWidget()
                col_layout = QVBoxLayout(col_w)
                col_layout.setContentsMargins(6, 0, 6, 0)
                col_layout.setSpacing(8)
                col_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                self._ship_column_layouts.append(col_layout)
                self._ship_column_widgets.append(col_w)
                self._ship_columns_layout.addWidget(col_w)

            # 列宽：第0列窄（基础信息/消耗品），其余均分
            for i, w in enumerate(self._ship_column_widgets[:cols]):
                stretch = 1 if i == 0 else 2
                self._ship_columns_layout.setStretchFactor(w, stretch)

            # 隐藏多余的列
            for w in self._ship_column_widgets[cols:]:
                w.hide()
            for w in self._ship_column_widgets[:cols]:
                w.show()

            # 按 label 映射分发 section
            col_items: list[list[dict]] = [[] for _ in range(cols)]
            for sec in self._ship_sections:
                label = sec.get("label", "")
                col_idx = LABEL_TO_COL.get(label, 0)  # 未匹配的归入第 0 列
                col_items[col_idx].append(sec)

            # 重建每列的内容（仅前 cols 列，防止列数变化后越界）
            for col_idx, col_layout in enumerate(self._ship_column_layouts[:cols]):
                # 清空该列
                while col_layout.count() > 0:
                    item = col_layout.takeAt(0)
                    if item and item.widget():
                        item.widget().deleteLater()

                for sec in col_items[col_idx]:
                    label = sec.get("label", "未知")
                    sub_info = self._ship_sub_sections.get(label)

                    # 消耗品数据使用独立按钮+图片面板
                    if label == "消耗品数据":
                        widget = self._build_consumables_widget(sec)
                    elif label == "战斗指令":
                        widget = self._build_rage_mode_widget(sec)
                    elif sec.get("raw_ammo_types") and label != "支援":
                        widget = self._build_weapon_widget(sec)
                    elif label == "防空":
                        widget = self._build_aa_widget(sec)
                    elif sub_info and sub_info.get("sub_labels"):
                        if label == "舰载机":
                            widget = self._build_aircraft_widget(sub_info)
                        else:
                            widget = self._build_sub_widget(label, sub_info)
                    elif label == "支援":
                        widget = self._build_support_widget(sec)
                    else:
                        widget = ShipCardWidget(sec)

                    col_layout.addWidget(widget)

        finally:
            self._ship_rebuilding = False
        self.stack.setCurrentIndex(0)

    def _build_sub_widget(self, title: str, sub_info: dict) -> QWidget:
        """构建无标签栏的子分类面板，仅显示默认配置内容，顶栏按钮控制切换"""
        from ui.ship_card_widget import SECTION_ICONS, CARD_STYLE
        from PySide6.QtWidgets import QGroupBox

        icon = SECTION_ICONS.get(title, "")
        title_text = f"  {icon} {title}" if icon else f"  {title}"

        container = QGroupBox(title_text)
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        labels = sub_info.get("sub_labels", [])
        contents = sub_info.get("sub_contents", {})
        from PySide6.QtWidgets import QStackedWidget
        stack = QStackedWidget()
        for i, sl in enumerate(labels):
            content = contents.get(sl, {})
            if isinstance(content, dict):
                items = content.get("items", [])
                raw_ammo = content.get("raw_ammo_types", [])
                wrapper = QWidget()
                wrapper.setObjectName(f"subpage_{sl}")
                wlayout = QVBoxLayout(wrapper)
                wlayout.setContentsMargins(0, 0, 0, 0)
                wlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
                if items and title == "支援":
                    # 支援机组：按 header 拆分为多个机组，各自独立 tooltip
                    KEEP_ASUP = {"飞机型号", "最大充能次数", "装填时间", "持续时间",
                                 "最大距离", "最小距离", "单架飞机血量", "载弹量", "弹药"}
                    groups: list[list[dict]] = []
                    cur_grp: list[dict] = []
                    for it in items:
                        if it.get("row_type") == "header" and cur_grp:
                            groups.append(cur_grp)
                            cur_grp = [it]
                        else:
                            cur_grp.append(it)
                    if cur_grp:
                        groups.append(cur_grp)
                    ammo_idx = 0
                    for grp in groups:
                        disp = []; tip = []
                        for it in grp:
                            n = it.get("name",""); v = it.get("value",""); u = it.get("unit",""); rt = it.get("row_type","")
                            if n and (n in KEEP_ASUP or rt == "header"):
                                disp.append(it)
                            elif n:
                                d = f"{v} {u}" if u else v
                                tip.append(f"<br><b>── {n} ──</b>" if rt=="header" else (f"&nbsp;&nbsp;<b>{n}</b>: {d}" if d else f"&nbsp;&nbsp;{n}"))
                        if not disp:
                            continue
                        card = ShipCardWidget({"label":"","items":disp})
                        if tip:
                            card.setToolTip("<br>".join(tip))
                        wlayout.addWidget(card)
                        # 本组弹药
                        ac = sum(1 for it in grp if it.get("name")=="弹药" and it.get("value"))
                        if ac > 0 and raw_ammo:
                            from pathlib import Path
                            from PySide6.QtGui import QPixmap, QIcon
                            from PySide6.QtCore import QSize
                            from PySide6.QtWidgets import QPushButton, QLabel
                            ammo_dir = ":/resources/pictures/ammo_types"
                            ga = raw_ammo[ammo_idx:ammo_idx+ac]; ammo_idx += ac
                            br = QWidget(); bl = QHBoxLayout(br); bl.setContentsMargins(4,0,4,0); bl.setSpacing(6); bl.setAlignment(Qt.AlignmentFlag.AlignLeft)
                            st = QStackedWidget(); st.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum); st.setVisible(False)
                            for ai in ga:
                                an = ai.get("name",""); di = ai.get("detail_items",[]); at = ai.get("ammo_type","").lower(); sp = ai.get("species","").lower()
                                btn = QPushButton(""); btn.setFixedSize(36,36); btn.setCheckable(True)
                                btn.setStyleSheet("QPushButton{background:#3a3a3a;border:1px solid #555;border-radius:6px;padding:2px;min-width:36px;min-height:36px;max-width:36px;max-height:36px;}QPushButton:hover{background:#4a4a4a;border-color:#1a73e8;}QPushButton:checked{background:#1a73e8;border-color:#1a73e8;}")
                                btn.setToolTip(an)
                                cand = []
                                _proj_to_air = {"rocket": "projectile", "bomb": "bomb", "skipbomb": "skip_bomb", "mine": "mine"}
                                _ap = next((v for k,v in _proj_to_air.items() if sp.startswith(k)), None)
                                if _ap:
                                    if at and _ap != "mine": cand.append(f"ammo_{_ap}_{at}_0.png")
                                    cand.append(f"ammo_{_ap}_0.png")
                                if at: cand.append(f"ammo_{at}_0.png")
                                if sp in ("torpedo","torpedobomber"):
                                    if "deepwater" in ai.get("raw_ammo_type", "").lower():
                                        if sp == "torpedobomber":
                                            cand.insert(0, "ammo_torpedo_deepwater_0.png")
                                            cand.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                                        else:
                                            cand.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                                            cand.insert(0, "ammo_torpedo_deepwater_0.png")
                                    else:
                                        tp = ai.get("torpedo_postfix", "")
                                        if tp == "_subBurn":
                                            cand.insert(0, "ammo_torpedo_subburn_0.png")
                                        elif tp:
                                            cand.insert(0, "ammo_torpedo_subdefault_improve_0.png")
                                    cand.extend(["ammo_torpedo_0.png","ammo_bomber_torpedo_0.png"])
                                if "depthcharge" in sp: cand.extend(["ammo_depthcharge_0.png","ammo_airsupport_depthcharge_0.png"])
                                ip = next((p for c in cand if not (p:=QPixmap(f":/resources/pictures/ammo_types/{c}")).isNull()), None)
                                if ip: btn.setIcon(QIcon(ip.scaled(28,28,Qt.KeepAspectRatio,Qt.SmoothTransformation))); btn.setIconSize(QSize(28,28))
                                else: btn.setText(an[:2] if an else "?"); btn.setStyleSheet(btn.styleSheet().replace("padding:2px;","padding:2px;font-size:8px;color:#333;"))
                                bl.addWidget(btn)
                                st.addWidget(ShipCardWidget({"label":an,"items":di}) if di else (QLabel("无详细数据",styleSheet="color:#999;font-size:11px;padding:8px;",alignment=Qt.AlignmentFlag.AlignCenter)))
                                ci = st.count()-1
                                btn.clicked.connect(lambda checked,i=ci,s=st,b=btn,bl_=bl: self._on_ammo_btn_click(i,s,bl_,b))
                            bl.addStretch(); wlayout.addWidget(br); wlayout.addWidget(st)
                elif items:
                    section = {"label": sl, "items": items}
                    card = ShipCardWidget(section)
                    wlayout.addWidget(card)
                stack.addWidget(wrapper)
            elif isinstance(content, list):
                if content and isinstance(content[0], dict) and "name" in content[0]:
                    section = {"label": sl, "items": content}
                    card = ShipCardWidget(section)
                    wrapper = QWidget()
                    wrapper.setObjectName(f"subpage_{sl}")
                    wlayout = QVBoxLayout(wrapper)
                    wlayout.setContentsMargins(4, 4, 4, 4)
                    wlayout.setAlignment(Qt.AlignmentFlag.AlignTop)
                    wlayout.addWidget(card)
                    stack.addWidget(wrapper)
                else:
                    te = QTextEdit()
                    te.setReadOnly(True)
                    te.setFont(self._make_font("Consolas", 10))
                    te.setStyleSheet("""
                        QTextEdit {
                            background-color: #fafafa;
                            color: #1a1a1a;
                            border: none;
                            padding: 8px 12px;
                            font-family: "Consolas", "Courier New", monospace;
                            font-size: 11px;
                        }
                    """)
                    te.setPlainText(self._strip_indent("\n".join(content) if isinstance(content, list) else ""))
                    te.setObjectName(f"subpage_{sl}")
                    stack.addWidget(te)
        if stack.count() > 0:
            stack.setCurrentIndex(0)
        # 仅存 stack 引用供顶栏联动，btns=None 表示无标签按钮
        self._subwidget_controllers[title] = (stack, None)
        layout.addWidget(stack, stretch=1)
        return container

    def _build_aircraft_widget(self, sub_info: dict) -> QWidget:
        """构建舰载机面板：每个机种为 QGroupBox，各配置用 QStackedWidget 切换"""
        from ui.ship_card_widget import ShipCardWidget, CARD_STYLE
        from PySide6.QtWidgets import QGroupBox, QStackedWidget
        from pathlib import Path
        from PySide6.QtGui import QPixmap, QIcon
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QLabel

        container = QGroupBox("  舰载机")
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        labels = sub_info.get("sub_labels", [])
        sub_keys = sub_info.get("sub_keys", {})
        contents = sub_info.get("sub_contents", {})
        if not labels:
            return container

        BTN_STYLE = """
            QPushButton {
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 6px; padding: 2px;
                min-width: 36px; min-height: 36px;
                max-width: 36px; max-height: 36px;
            }
            QPushButton:hover {
                background: #4a4a4a;
                border-color: #1a73e8;
            }
            QPushButton:checked {
                background: #1a73e8; border-color: #1a73e8;
            }
        """
        ammo_dir = ":/resources/pictures/ammo_types"

        for sl in labels:
            content = contents.get(sl, {})
            if not isinstance(content, dict):
                continue

            grp = QGroupBox(f"  {sl}")
            grp.setStyleSheet(CARD_STYLE)
            grp.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            grp_layout = QVBoxLayout(grp)
            grp_layout.setContentsMargins(2, 2, 2, 2)
            grp_layout.setSpacing(2)

            config_labels = content.get("config_labels", [])
            config_contents = content.get("config_contents", {})
            config_label_map = content.get("config_label_map", {})

            def _lookup_cfg(mk: str) -> dict:
                """通过内部 key 查找配置数据"""
                return config_contents.get(mk, {})

            def _build_aircraft_config_page(cfg_data: dict) -> QWidget:
                """构建单个 aircraft config 的完整页面：飞机卡片 + 弹药按钮 + 消耗品按钮"""
                w = QWidget()
                wl = QVBoxLayout(w)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.setAlignment(Qt.AlignmentFlag.AlignTop)
                wl.setSpacing(2)

                items = cfg_data.get("items", [])
                raw_ammo = cfg_data.get("raw_ammo_types", [])
                raw_con = cfg_data.get("raw_consumables", [])

                # 飞机属性卡片：仅保留关键字段，其余放入 tooltip
                KEEP_NAMES = {
                    "飞机型号", "飞机等级", "巡航速度", "最大速度",
                    "单架飞机血量", "载弹量", "攻击编队大小",
                    "中队规模", "中队飞机数量", "被侦测距离",
                    "最大可用数量", "开局可用数量", "每次整备数量", "每次整备时间",
                    "喷气式助推器作用时间", "喷气式助推器生效期间巡航速度",
                }
                display_items = [it for it in items if it.get("name", "") in KEEP_NAMES]
                tip_parts = []
                for it in items:
                    n = it.get("name", "")
                    v = it.get("value", "")
                    u = it.get("unit", "")
                    rt = it.get("row_type", "")
                    if n not in KEEP_NAMES and n and rt != "header":
                        display = f"{v} {u}" if u else v
                        if display:
                            tip_parts.append(f"&nbsp;&nbsp;<b>{n}</b>: {display}")
                        else:
                            tip_parts.append(f"&nbsp;&nbsp;{n}")
                if tip_parts:
                    card = ShipCardWidget({"label": "", "items": display_items})
                    card.setToolTip("<br>".join(tip_parts))
                    wl.addWidget(card)
                elif display_items:
                    wl.addWidget(ShipCardWidget({"label": "", "items": display_items}))

                # 弹药按钮行
                if raw_ammo:
                    ammo_btn_row = QWidget()
                    abl = QHBoxLayout(ammo_btn_row)
                    abl.setContentsMargins(4, 2, 4, 2)
                    abl.setSpacing(6)
                    abl.setAlignment(Qt.AlignmentFlag.AlignLeft)
                    ammo_stack = QStackedWidget()
                    ammo_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                    ammo_stack.setVisible(False)
                    for ammo_info in raw_ammo:
                        aname = ammo_info.get("name", "")
                        detail_items = ammo_info.get("detail_items", [])
                        at = ammo_info.get("ammo_type", "").lower()
                        sp = ammo_info.get("species", "").lower()
                        btn = QPushButton("")
                        btn.setFixedSize(36, 36)
                        btn.setCheckable(True)
                        btn.setStyleSheet(BTN_STYLE)
                        btn.setToolTip(aname)
                        candidates = []
                        _proj_to_air = {"rocket": "projectile", "bomb": "bomb", "skipbomb": "skip_bomb", "mine": "mine"}
                        _ap = next((v for k,v in _proj_to_air.items() if sp.startswith(k)), None)
                        if _ap:
                            if at and _ap != "mine": candidates.append(f"ammo_{_ap}_{at}_0.png")
                            candidates.append(f"ammo_{_ap}_0.png")
                        if at: candidates.append(f"ammo_{at}_0.png")
                        # 鱼雷回退
                        if sp in ("torpedo", "torpedobomber"):
                            if "deepwater" in ammo_info.get("raw_ammo_type", "").lower():
                                if sp == "torpedobomber":
                                    candidates.insert(0, "ammo_torpedo_deepwater_0.png")
                                    candidates.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                                else:
                                    candidates.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                                    candidates.insert(0, "ammo_torpedo_deepwater_0.png")
                            else:
                                tp = ammo_info.get("torpedo_postfix", "")
                                if tp == "_subBurn":
                                    candidates.insert(0, "ammo_torpedo_subburn_0.png")
                                elif tp:
                                    candidates.insert(0, "ammo_torpedo_subdefault_improve_0.png")
                            candidates.append("ammo_torpedo_0.png")
                            candidates.append("ammo_bomber_torpedo_0.png")
                        # 深水炸弹回退
                        if "depthcharge" in sp:
                            candidates.append("ammo_depthcharge_0.png")
                            candidates.append("ammo_airsupport_depthcharge_0.png")
                        img_path = None
                        for c in candidates:
                            p = QPixmap(f":/resources/pictures/ammo_types/{c}")
                            if not p.isNull(): img_path = p; break
                        if img_path and not img_path.isNull():
                            scaled = img_path.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            btn.setIcon(QIcon(scaled))
                            btn.setIconSize(QSize(28, 28))
                        else:
                            btn.setText(aname[:2] if aname else "?")
                            btn.setStyleSheet(BTN_STYLE.replace("padding: 2px;", "padding: 2px; font-size:8px; color:#333;"))
                        abl.addWidget(btn)
                        if detail_items:
                            ammo_stack.addWidget(ShipCardWidget({"label": aname, "items": detail_items}))
                        else:
                            lbl = QLabel("无详细数据"); lbl.setStyleSheet("color:#999; font-size:11px; padding:8px;"); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                            ammo_stack.addWidget(lbl)
                        ci = ammo_stack.count() - 1
                        btn.clicked.connect(lambda checked, i=ci, s=ammo_stack, b=btn, bl_=abl: self._on_ammo_btn_click(i, s, bl_, b))
                    abl.addStretch()
                    wl.addWidget(ammo_btn_row)
                    wl.addWidget(ammo_stack)

                # 消耗品按钮行 + 详情堆栈（完全照搬舰船消耗品样式）
                if raw_con:
                    CON_BTN_STYLE = """
                        QPushButton {
                            background: #3a3a3a;
                            border: 1px solid #555;
                            border-radius: 6px; padding: 2px;
                            min-width: 40px; min-height: 40px;
                            max-width: 40px; max-height: 40px;
                        }
                        QPushButton:hover {
                            background: #4a4a4a;
                            border-color: #1a73e8;
                        }
                        QPushButton:checked {
                            background: #1a73e8; border-color: #1a73e8;
                        }
                    """
                    consumables_dir = ":/resources/pictures/consumables"
                    con_btn_row = QWidget()
                    cbr_layout = QHBoxLayout(con_btn_row)
                    cbr_layout.setContentsMargins(4, 2, 4, 2)
                    cbr_layout.setSpacing(6)
                    cbr_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                    con_stack = QStackedWidget()
                    con_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                    con_stack.setVisible(False)
                    con_btns: list[QPushButton] = []
                    for con_info in raw_con:
                        dname = con_info.get("display_name", "?")
                        detail_items = con_info.get("detail_items", [])
                        cid = con_info.get("consumable_id", "")
                        btn = QPushButton("")
                        btn.setFixedSize(40, 40)
                        btn.setCheckable(True)
                        btn.setStyleSheet(CON_BTN_STYLE)
                        btn.setToolTip(dname)
                        img_file = f"consumable_{cid}_0.png"
                        img_path = f"{consumables_dir}/{img_file}"
                        pixmap = QPixmap(img_path)
                        if not pixmap.isNull():
                            scaled = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            btn.setIcon(QIcon(scaled))
                            btn.setIconSize(QSize(32, 32))
                        else:
                            btn.setText(cid[:2] if cid else "?")
                            btn.setStyleSheet(CON_BTN_STYLE.replace("padding: 2px;", "padding: 2px; font-size:9px; color:#333;"))
                        cbr_layout.addWidget(btn)
                        con_btns.append(btn)
                        if detail_items:
                            con_stack.addWidget(ShipCardWidget({"label": dname, "items": detail_items}))
                        else:
                            lbl = QLabel("无详细数据"); lbl.setStyleSheet("color:#999; font-size:11px; padding:8px;"); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                            con_stack.addWidget(lbl)
                        ci = con_stack.count() - 1
                        btn.clicked.connect(lambda checked, i=ci, s=con_stack, b=btn, btns=con_btns: self._on_aircraft_con_btn_click(i, s, b, btns))
                    cbr_layout.addStretch()
                    wl.addWidget(con_btn_row)
                    wl.addWidget(con_stack)

                return w

            # 判断是否同一模块内的多飞机（相同 config_group 前缀）
            def _cfg_group(label: str) -> str:
                return label.split("|")[0] if "|" in label else label
            cfg_groups = {_cfg_group(mk) for mk in config_labels}
            same_module = len(cfg_groups) <= 1

            if same_module:
                # 同一模块内的多飞机 → 垂直叠放
                for mk in config_labels:
                    cfg_data = _lookup_cfg(mk)
                    page = _build_aircraft_config_page(cfg_data)
                    if page:
                        page.setObjectName(f"aircraft_{mk}")
                        grp_layout.addWidget(page)
            elif len(config_labels) > 1:
                # 不同模块间使用 QStackedWidget，顶栏按钮切换
                sub_stack = QStackedWidget()
                sub_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                for mk in config_labels:
                    cfg_data = _lookup_cfg(mk)
                    page = _build_aircraft_config_page(cfg_data)
                    if page:
                        page.setObjectName(f"aircraft_{mk}")
                        sub_stack.addWidget(page)
                if sub_stack.count() > 0:
                    sub_stack.setCurrentIndex(0)
                    grp_layout.addWidget(sub_stack)
                    ikey = sub_keys.get(sl, "")
                    if ikey:
                        ctrl_key = f"_{ikey}"
                        self._subwidget_controllers[ctrl_key] = (sub_stack, None)
            else:
                cfg_data = _lookup_cfg(config_labels[0]) if config_labels else {}
                page = _build_aircraft_config_page(cfg_data)
                if page:
                    grp_layout.addWidget(page)

            layout.addWidget(grp)
        return container

    def _build_support_widget(self, section: dict) -> QWidget:
        """构建支援机组面板：按机组分开显示，各自 tooltip 独立"""
        from ui.ship_card_widget import ShipCardWidget, CARD_STYLE
        from pathlib import Path
        from PySide6.QtGui import QPixmap, QIcon
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QGroupBox, QStackedWidget, QPushButton, QLabel

        label = section.get("label", "支援")
        items = section.get("items", [])
        raw_ammo = section.get("raw_ammo_types", [])

        KEEP_ASUP = {"飞机型号", "最大充能次数", "装填时间", "持续时间",
                     "最大距离", "最小距离", "单架飞机血量", "载弹量", "弹药"}

        # 按 header 拆分为多个机组
        groups: list[list[dict]] = []
        cur: list[dict] = []
        for it in items:
            if it.get("row_type") == "header" and cur:
                groups.append(cur)
                cur = [it]
            else:
                cur.append(it)
        if cur:
            groups.append(cur)

        container = QGroupBox(f"  {label}")
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        ammo_dir = ":/resources/pictures/ammo_types"
        BTN_STYLE = """
            QPushButton {
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 6px; padding: 2px;
                min-width: 36px; min-height: 36px;
                max-width: 36px; max-height: 36px;
            }
            QPushButton:hover { background: #4a4a4a; border-color: #1a73e8; }
            QPushButton:checked { background: #1a73e8; border-color: #1a73e8; }
        """

        ammo_idx = 0
        for grp in groups:
            # 过滤本组：卡片字段 + tooltip 分开
            display_items = []
            tip_items = []
            for it in grp:
                n = it.get("name", "")
                v = it.get("value", "")
                u = it.get("unit", "")
                rt = it.get("row_type", "")
                if n and (n in KEEP_ASUP or rt == "header"):
                    display_items.append(it)
                elif n:
                    display = f"{v} {u}" if u else v
                    if rt == "header":
                        tip_items.append(f"<br><b>── {n} ──</b>")
                    elif display:
                        tip_items.append(f"&nbsp;&nbsp;<b>{n}</b>: {display}")
                    else:
                        tip_items.append(f"&nbsp;&nbsp;{n}")

            if not display_items:
                continue

            card = ShipCardWidget({"label": "", "items": display_items})
            if tip_items:
                card.setToolTip("<br>".join(tip_items))
            layout.addWidget(card)

            # 本组的弹药按钮（取 raw_ammo 中对应数量）
            ammo_count = sum(1 for it in grp if it.get("name") == "弹药" and it.get("value"))
            if ammo_count > 0 and ammo_idx < len(raw_ammo):
                group_ammo = raw_ammo[ammo_idx:ammo_idx + ammo_count]
                ammo_idx += ammo_count
                btn_row = QWidget()
                bl = QHBoxLayout(btn_row)
                bl.setContentsMargins(4, 0, 4, 0)
                bl.setSpacing(6)
                bl.setAlignment(Qt.AlignmentFlag.AlignLeft)
                ammo_stack = QStackedWidget()
                ammo_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                ammo_stack.setVisible(False)
                for ammo_info in group_ammo:
                    aname = ammo_info.get("name", "")
                    detail_items = ammo_info.get("detail_items", [])
                    at = ammo_info.get("ammo_type", "").lower()
                    sp = ammo_info.get("species", "").lower()
                    btn = QPushButton("")
                    btn.setFixedSize(36, 36)
                    btn.setCheckable(True)
                    btn.setStyleSheet(BTN_STYLE)
                    btn.setToolTip(aname)
                    candidates = []
                    _proj_to_air = {"rocket": "projectile", "bomb": "bomb", "skipbomb": "skip_bomb", "mine": "mine"}
                    _ap = next((v for k,v in _proj_to_air.items() if sp.startswith(k)), None)
                    if _ap:
                        if at and _ap != "mine": candidates.append(f"ammo_{_ap}_{at}_0.png")
                        candidates.append(f"ammo_{_ap}_0.png")
                    if at: candidates.append(f"ammo_{at}_0.png")
                    if sp in ("torpedo", "torpedobomber"):
                        if "deepwater" in ammo_info.get("raw_ammo_type", "").lower():
                            if sp == "torpedobomber":
                                candidates.insert(0, "ammo_torpedo_deepwater_0.png")
                                candidates.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                            else:
                                candidates.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                                candidates.insert(0, "ammo_torpedo_deepwater_0.png")
                        else:
                            tp = ammo_info.get("torpedo_postfix", "")
                            if tp == "_subBurn":
                                candidates.insert(0, "ammo_torpedo_subburn_0.png")
                            elif tp:
                                candidates.insert(0, "ammo_torpedo_subdefault_improve_0.png")
                        candidates.append("ammo_torpedo_0.png")
                        candidates.append("ammo_bomber_torpedo_0.png")
                    if "depthcharge" in sp:
                        candidates.append("ammo_depthcharge_0.png")
                        candidates.append("ammo_airsupport_depthcharge_0.png")
                    img_path = None
                    for c in candidates:
                        p = QPixmap(f":/resources/pictures/ammo_types/{c}")
                        if not p.isNull(): img_path = p; break
                    if img_path and not img_path.isNull():
                        scaled = img_path.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        btn.setIcon(QIcon(scaled))
                        btn.setIconSize(QSize(28, 28))
                    else:
                        btn.setText(aname[:2] if aname else "?")
                        btn.setStyleSheet(BTN_STYLE.replace("padding: 2px;", "padding: 2px; font-size:8px; color:#333;"))
                    bl.addWidget(btn)
                    if detail_items:
                        ammo_stack.addWidget(ShipCardWidget({"label": aname, "items": detail_items}))
                    else:
                        lbl = QLabel("无详细数据"); lbl.setStyleSheet("color:#999; font-size:11px; padding:8px;"); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        ammo_stack.addWidget(lbl)
                    ci = ammo_stack.count() - 1
                    btn.clicked.connect(lambda checked, i=ci, s=ammo_stack, b=btn, bl_=bl: self._on_ammo_btn_click(i, s, bl_, b))
                bl.addStretch()
                layout.addWidget(btn_row)
                layout.addWidget(ammo_stack)

        return container

    def _build_consumables_widget(self, section: dict) -> QWidget:
        """构建消耗品数据面板：按槽位纵向排列，每槽位以按钮+图片显示"""
        from ui.ship_card_widget import CARD_STYLE
        from PySide6.QtWidgets import QGroupBox, QStackedWidget

        container = QGroupBox("  消耗品数据")
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        raw_slots = section.get("raw_consumables", [])
        # 按 slot_index 分组
        slots_map: dict[int, list[dict]] = defaultdict(list)
        for rs in raw_slots:
            slots_map[rs["slot_index"]].append(rs)

        consumables_dir = ":/resources/pictures/consumables"

        BTN_STYLE = """
            QPushButton {
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 6px; padding: 2px;
                min-width: 40px; min-height: 40px;
                max-width: 40px; max-height: 40px;
            }
            QPushButton:hover {
                background: #4a4a4a;
                border-color: #1a73e8;
            }
        """

        for slot_idx in sorted(slots_map.keys()):
            items_in_slot = slots_map[slot_idx]

            # 槽位行：标签 + 按钮行
            slot_row = QWidget()
            sr_layout = QHBoxLayout(slot_row)
            sr_layout.setContentsMargins(0, 0, 0, 0)
            sr_layout.setSpacing(6)
            sr_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

            # 槽位编号标签
            slot_label = QLabel(f"槽{slot_idx}")
            slot_label.setStyleSheet("font-size:10px; color:#aaa; min-width:24px;")
            slot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sr_layout.addWidget(slot_label)

            for rs in items_in_slot:
                cid = rs["consumable_id"]
                dname = rs["display_name"]
                btn = QPushButton("")
                btn.setFixedSize(40, 40)
                btn.setStyleSheet(BTN_STYLE)
                btn.setToolTip(dname)
                btn.setObjectName(f"con_{cid}")

                # 加载消耗品图片
                img_file = f"consumable_{cid}_0.png"
                img_path = f"{consumables_dir}/{img_file}"
                pixmap = QPixmap(img_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    btn.setIcon(QIcon(scaled))
                    btn.setIconSize(QSize(32, 32))
                else:
                    # 无图片时显示首字母
                    btn.setText(cid[:2] if cid else "?")
                    btn.setStyleSheet(BTN_STYLE.replace("padding: 2px;", "padding: 2px; font-size:9px; color:#333;"))

                ckey = rs.get('config_key', 'Default')
                btn.clicked.connect(partial(self._on_consumable_btn_click, cid, dname, ckey, container))
                sr_layout.addWidget(btn)

            sr_layout.addStretch()
            layout.addWidget(slot_row)

        # 消耗品详情展示区（初始为提示文字）
        self._con_detail_stack = QStackedWidget()
        self._con_detail_stack.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        prompt = QLabel("点击上方消耗品按钮查看详细数据")
        prompt.setStyleSheet("color:#999; font-size:11px; padding:20px;")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._con_detail_stack.addWidget(prompt)
        layout.addWidget(self._con_detail_stack)
        return container

    def _build_rage_mode_widget(self, section: dict) -> QWidget:
        """构建战斗指令面板：按钮+图片，详细数据精简显示"""
        from ui.ship_card_widget import CARD_STYLE
        from PySide6.QtWidgets import QGroupBox

        container = QGroupBox("  战斗指令")
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(container)
        # 增加整体内边距，使其与其他模块卡片保持一致的呼吸感
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        raw = section.get("raw_rage_mode", {})
        rname = raw.get("rage_mode_name", "")
        dname = raw.get("display_name", "战斗指令")

        preview_path = ":/resources/pictures/ragemode/rageMode_" + rname + "_preview_0.png"

        btn = QPushButton("")
        btn.setFixedSize(32, 32)
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setToolTip(dname)
        btn.setObjectName(f"rage_{rname}")
        BTN_STYLE = """
            QPushButton {
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 6px; padding: 2px;
                min-width: 32px; min-height: 32px;
                max-width: 32px; max-height: 32px;
            }
            QPushButton:hover {
                background: #4a4a4a;
                border-color: #1a73e8;
            }
            QPushButton:checked {
                background: #1a73e8; border-color: #1a73e8;
            }
        """
        btn.setStyleSheet(BTN_STYLE)

        pixmap = QPixmap(preview_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(QSize(28, 28))
        else:
            btn.setText("缺少图片")
            btn.setStyleSheet(BTN_STYLE.replace("font-size: 9px;", "font-size: 8px;").replace("color: #333;", "color: #999;"))

        btn_row = QWidget()
        bl = QHBoxLayout(btn_row)
        bl.setContentsMargins(0, 0, 0, 6) # 底部留出间距分隔图标与数据
        bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(btn)
        layout.addWidget(btn_row)

        items = section.get("items", [])
        data_widget = QWidget()
        data_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        data_layout = QVBoxLayout(data_widget)
        # 将内边距和行间距放大，解除紧凑感
        data_layout.setContentsMargins(4, 4, 4, 4)
        data_layout.setSpacing(8)

        for item in items:
            row_type = item.get("row_type", "kv")
            name = item.get("name", "")
            value = item.get("value", "")
            unit = item.get("unit", "")

            if row_type == "header":
                hlbl = QLabel(name)
                hlbl.setStyleSheet("font-size:11px; font-weight:bold; color:#444; background:transparent; padding-top: 4px;")
                hlbl.setFixedHeight(24)
                data_layout.addWidget(hlbl)
                continue

            if not name.strip():
                continue

            row_w = QWidget()
            rl = QHBoxLayout(row_w)
            # 增加每一行的纵向微调间距
            rl.setContentsMargins(0, 2, 0, 2)
            rl.setSpacing(12) # 键值对之间的横向间距拉开

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-size:11px; color:#bbb; background:transparent;")
            name_lbl.setFixedWidth(80)
            rl.addWidget(name_lbl)

            display_value = f"{value} {unit}" if unit and value else (value or unit or "")
            fg = "#000000"
            if "%" in display_value:
                stripped = display_value.strip()
                if stripped.startswith("+"):
                    fg = "#1b8a1b"
                elif stripped.startswith("-"):
                    fg = "#d32f2f"

            val_lbl = QLabel(display_value)
            val_lbl.setWordWrap(True)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            # 通过样式增加 line-height，确保长文本多行折叠时，行与行之间有空隙不重叠
            val_lbl.setStyleSheet(f"font-size:11px; color:{fg}; background:transparent; line-height: 1.3;")
            rl.addWidget(val_lbl, stretch=1)
            data_layout.addWidget(row_w)

            val_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
            row_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

        layout.addWidget(data_widget)
        return container

    def _build_weapon_widget(self, section: dict) -> QWidget:
        """构建武器面板（主炮/副炮）：每座炮独立显示 + 下方弹药按钮 + 点击切换详情"""
        from ui.ship_card_widget import ShipCardWidget, CARD_STYLE
        from PySide6.QtWidgets import QGroupBox, QStackedWidget
        from pathlib import Path

        label = section.get("label", "武器")
        all_items = section.get("items", [])
        raw_ammo = section.get("raw_ammo_types", [])
        section_tooltip = section.get("tooltip_items", [])

        # 按火炮/深弹名称拆分 items，每座炮/发射器一组
        mount_groups: list[list[dict]] = []
        cur: list[dict] = []
        for item in all_items:
            if item.get("name") in ("火炮名称", "深弹名称") and cur:
                mount_groups.append(cur)
                cur = [item]
            else:
                cur.append(item)
        if cur:
            mount_groups.append(cur)

        container = QGroupBox(f"  {label}")
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(6)

        ammo_dir = ":/resources/pictures/ammo_types"

        BTN_STYLE = """
            QPushButton {
                background: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 6px; padding: 2px;
                min-width: 36px; min-height: 36px;
                max-width: 36px; max-height: 36px;
            }
            QPushButton:hover {
                background: #e8e8e8;
                border-color: #1a73e8;
            }
            QPushButton:checked {
                background: #1a73e8; border-color: #1a73e8;
            }
        """

        ammo_idx = 0
        for grp_idx, grp_items in enumerate(mount_groups):
            TOOLTIP_NAMES = {
                "横向散步公式", "弹着群系数(Sigma)", "纵向散步系数",
                "水平回转速度", "垂直回转速度", "口径",
            }

            # ── 1. 过滤掉 Tooltip 属性以及数据末尾的分割线/占位符 ──
            display_items = []
            for it in grp_items:
                name = it.get("name", "")
                row_type = it.get("row_type", "")
                val = it.get("value")

                # 1.1 过滤属于 Tooltip 的属性
                if name in TOOLTIP_NAMES:
                    continue
                # 1.2 过滤分隔线 (separator) 以及不带名称和内容的空占位行
                if row_type == "separator":
                    continue
                if not name and (val is None or str(val).strip() == ""):
                    continue
                    
                display_items.append(it)

            # ── 2. 深度校验：过滤掉值为空的无效字段 ──
            valid_items = [
                it for it in display_items 
                if (it.get("name") and (it.get("value") is not None and str(it.get("value")).strip() != ""))
            ]

            # 计算该组涉及的弹药数量（无论当前炮卡片显示与否，都要步进 ammo_idx 保证游标对齐）
            ammo_count = sum(1 for it in grp_items if it.get("name") == "弹药" and it.get("value"))
            mount_ammo = raw_ammo[ammo_idx: ammo_idx + ammo_count]
            ammo_idx += ammo_count

            # 重点拦截：如果这一组既没有可显示的有效属性，也没有弹药图标，直接 skip，绝不生成任何 UI 控件！
            if not valid_items and not mount_ammo:
                continue

            # ── 3. 只有存在有效属性时，才生成卡片 ──
            if valid_items:
                grp_section = {"label": "", "items": display_items}
                card = ShipCardWidget(grp_section)

                # 提取 Tooltip
                tip_parts = []
                for it in grp_items:
                    n, v, u = it.get("name", ""), it.get("value", ""), it.get("unit", "")
                    if n in TOOLTIP_NAMES and (v is not None and str(v).strip() != ""):
                        display = f"{v} {u}".strip() if u else v
                        tip_parts.append(f"<b>{n}</b>: {display}")

                if tip_parts:
                    card.setToolTip("<br>".join(tip_parts))
                elif section_tooltip:
                    card.setToolTip("<br>".join(section_tooltip))

                layout.addWidget(card)

            # ── 4. 只有存在弹药数据时，才生成弹药按钮行及 Stack 面板 ──
            if mount_ammo:
                btn_row = QWidget()
                bl = QHBoxLayout(btn_row)
                bl.setContentsMargins(4, 0, 4, 0)
                bl.setSpacing(6)
                bl.setAlignment(Qt.AlignmentFlag.AlignLeft)

                ammo_stack = QStackedWidget()
                ammo_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                ammo_stack.setVisible(False)

                for ammo_info in mount_ammo:
                    aname = ammo_info.get("name", "")
                    detail_items = ammo_info.get("detail_items", [])
                    atype_lower = ammo_info.get("ammo_type", "").lower()
                    species_lower = ammo_info.get("species", "").lower()

                    candidates = []
                    if species_lower:
                        candidates.append(f"ammo_{species_lower}_{atype_lower}_0.png" if atype_lower else f"ammo_{species_lower}_0.png")
                    if atype_lower and atype_lower != species_lower:
                        candidates.append(f"ammo_{atype_lower}_0.png")
                    if species_lower in ("torpedo", "torpedobomber"):
                        if "deepwater" in ammo_info.get("raw_ammo_type", "").lower():
                            if species_lower == "torpedobomber":
                                candidates.insert(0, "ammo_torpedo_deepwater_0.png")
                                candidates.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                            else:
                                candidates.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                                candidates.insert(0, "ammo_torpedo_deepwater_0.png")
                        else:
                            tp = ammo_info.get("torpedo_postfix", "")
                            if tp == "_subBurn":
                                candidates.insert(0, "ammo_torpedo_subburn_0.png")
                            elif tp:
                                candidates.insert(0, "ammo_torpedo_subdefault_improve_0.png")
                        candidates.extend(["ammo_torpedo_0.png", "ammo_bomber_torpedo_0.png"])
                    if "depthcharge" in species_lower:
                        candidates.extend(["ammo_depthcharge_0.png", "ammo_airsupport_depthcharge_0.png"])

                    btn = QPushButton("")
                    btn.setFixedSize(36, 36)
                    btn.setCheckable(True)
                    btn.setStyleSheet(BTN_STYLE)
                    btn.setToolTip(aname)

                    img_path = next((p for c in candidates if not (p:=QPixmap(f":/resources/pictures/ammo_types/{c}")).isNull()), None)
                    if img_path:
                        btn.setIcon(QIcon(img_path.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                        btn.setIconSize(QSize(28, 28))
                    else:
                        btn.setText(aname[:2] if aname else "?")
                        btn.setStyleSheet(BTN_STYLE + "QPushButton { font-size: 8px; color: #333; }")

                    bl.addWidget(btn)

                    if detail_items:
                        detail_card = ShipCardWidget({"label": aname, "items": detail_items})
                    else:
                        detail_card = QLabel("无详细数据")
                        detail_card.setStyleSheet("color: #999; font-size: 11px; padding: 8px;")
                        detail_card.setAlignment(Qt.AlignmentFlag.AlignCenter)

                    ammo_stack.addWidget(detail_card)

                    ci = ammo_stack.count() - 1
                    btn.clicked.connect(
                        lambda checked=False, i=ci, s=ammo_stack, b=btn, l=bl: self._on_ammo_btn_click(i, s, l, b)
                    )

                bl.addStretch()
                layout.addWidget(btn_row)
                layout.addWidget(ammo_stack)

        return container

    def _build_aa_widget(self, section: dict) -> QWidget:
        """构建防空面板：每个防空区域拆分为独立卡片，命中率/射程移至 tooltip"""
        from ui.ship_card_widget import ShipCardWidget, CARD_STYLE
        from PySide6.QtWidgets import QGroupBox

        items = section.get("items", [])
        label = section.get("label", "防空")

        # 按 header 分组，每段为一个独立卡片
        groups: list[list[dict]] = []
        cur: list[dict] = []
        for it in items:
            if it.get("row_type") == "header" and cur:
                groups.append(cur)
                cur = [it]
            else:
                cur.append(it)
        if cur:
            groups.append(cur)

        container = QGroupBox(f"  {label}")
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)

        for grp in groups:
            # 提取 tooltip 字段并从显示中去掉
            tooltip_data: list[str] = []
            display_items: list[dict] = []
            for it in grp:
                n = it.get("name", "")
                if n in ("命中率", "射程"):
                    v = it.get("value", "")
                    u = it.get("unit", "")
                    display = f"{v} {u}" if u else v
                    tooltip_data.append(f"<b>{n}</b>: {display}")
                else:
                    display_items.append(it)

            sec = {"label": "", "items": display_items}
            card = ShipCardWidget(sec)
            if tooltip_data:
                card.setToolTip("<br>".join(tooltip_data))
            layout.addWidget(card)

        return container

    def _on_ammo_btn_click(self, stack_idx: int, stack: QStackedWidget, btn_layout: QHBoxLayout, clicked_btn: QPushButton) -> None:
        """弹药按钮点击：切换详情页并更新按钮高亮"""
        # 若点击的是当前已选中页面则收起，否则切换过去
        if stack.isVisible() and stack.currentIndex() == stack_idx:
            stack.setVisible(False)
            stack.setMaximumHeight(0)
            clicked_btn.setChecked(False)
            return
        stack.setVisible(True)
        stack.setCurrentIndex(stack_idx)
        # 调整堆栈高度匹配当前页面
        current = stack.currentWidget()
        if current:
            stack.setMaximumHeight(current.sizeHint().height())
            stack.updateGeometry()
        for i in range(btn_layout.count()):
            w = btn_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(w is clicked_btn)

    def _on_aircraft_con_btn_click(self, stack_idx: int, stack: QStackedWidget, clicked_btn: QPushButton, all_btns: list[QPushButton]) -> None:
        """飞机消耗品按钮点击：切换详情页并更新按钮高亮"""
        if clicked_btn.isChecked() and stack.isVisible() and stack.currentIndex() == stack_idx:
            stack.setVisible(False)
            stack.setMaximumHeight(0)
            clicked_btn.setChecked(False)
            return
        stack.setVisible(True)
        stack.setCurrentIndex(stack_idx)
        # 调整堆栈高度匹配当前页面，防止长短页切换时留白
        current = stack.currentWidget()
        if current:
            stack.setMaximumHeight(current.sizeHint().height())
            stack.updateGeometry()
        for btn in all_btns:
            btn.setChecked(btn is clicked_btn)

    def _on_mod_opt_click(self, slot_idx: int, mod: dict, btn):
        """升级品选项点击：同槽位单选 + 再次点击取消 + 触发数据重算"""
        from PySide6.QtWidgets import QPushButton
        # 检查是否点击了已选中的升级品
        was_selected = (self._selected_mods.get(slot_idx) or {}).get("mod_id") == mod.get("mod_id")
        parent_w = btn.parentWidget()
        if was_selected:
            # 取消选择
            self._selected_mods.pop(slot_idx, None)
            btn.setChecked(False)
        else:
            # 取消同槽位（同父部件）其他按钮的勾选
            if parent_w:
                for child in parent_w.findChildren(QPushButton):
                    if child != btn and child.isCheckable():
                        child.setChecked(False)
            self._selected_mods[slot_idx] = mod
            btn.setChecked(True)
        # 收集所有选中升级品的 modifiers，同 key 累乘/累加
        # 先获取当前舰种，用于解析 dict 型修饰符
        _cur_ship_type = ""
        if hasattr(self, '_current_analyzed') and self._current_analyzed:
            _cb = self._current_analyzed.get("config_bar", {})
            _cur_ship_type = _cb.get("shiptype", "") if isinstance(_cb, dict) else ""
        all_mods: dict[str, float | dict] = {}
        for m in self._selected_mods.values():
            mod_dict = m.get("modifiers", {})
            for k, v in mod_dict.items():
                # dict 型修饰符：按当前舰种提取标量值
                if isinstance(v, dict):
                    v = v.get(_cur_ship_type) or next((x for x in v.values() if isinstance(x, (int, float))), 1.0)
                if k not in all_mods:
                    all_mods[k] = v
                else:
                    existing = all_mods[k]
                    # existing 也可能是 dict（来自旧版本缓存），同样解析
                    if isinstance(existing, dict):
                        existing = existing.get(_cur_ship_type) or next((x for x in existing.values() if isinstance(x, (int, float))), 1.0)
                    try:
                        ev_f, nv_f = float(existing), float(v)
                        _additive_keys = {"additionalConsumables", "planeAdditionalConsumables", "planeExtraHangarSize",
                                          "extraFighterCount", "asNumPacksBonus", "healthPerLevel", "planeHealthPerLevel",
                                          "speedBoostersAdditionalConsumables", "smokeGeneratorAdditionalConsumables",
                                          "torpedoReloaderAdditionalConsumables"}
                        if k in _additive_keys:
                            all_mods[k] = ev_f + nv_f
                        else:
                            all_mods[k] = ev_f * nv_f
                    except (ValueError, TypeError):
                        all_mods[k] = v
        if all_mods:
            self._refresh_data_only(all_mods)
        else:
            self._refresh_data_only(None)

    def _refresh_with_modifiers(self, modifiers: dict | None) -> None:
        """使用升级品修饰符重新构建舰船数据"""
        from services.database_service import get_db
        from presenters.registry import PresenterRegistry
        db = get_db()
        if not db or not db._conn or not self._current_category or not self._current_filename:
            return
        try:
            vc = db.get_latest_version_code() or ""
            etype = CATEGORY_TO_ETYPE.get(self._current_category)
            if not etype:
                return
            presenter = PresenterRegistry.get_presenter(etype, db._conn)
            if not presenter:
                return
            _eng_key = getattr(self, '_active_engine_key', '')
            _fc_key = getattr(self, '_active_fire_control_key', '')
            _mod_keys = getattr(self, '_active_module_keys', {})
            data = presenter.build(self._current_filename, version_code=vc, modifiers=modifiers,
                                   engine_letter=_eng_key, fire_control_key=_fc_key,
                                   active_module_keys=_mod_keys)
            if data:
                self._current_analyzed = data
                self._apply_analyzed()
        except Exception as e:
            import traceback
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 重算失败: {e}\n{traceback.format_exc()}")

    def _refresh_data_only(self, modifiers: dict | None = None) -> None:
        """仅刷新下方数据区，不触碰顶部配置栏（自动合并技能修饰符）"""
        from services.database_service import get_db
        from presenters.registry import PresenterRegistry
        db = get_db()
        if not db or not db._conn or not self._current_category or not self._current_filename:
            return
        try:
            vc = db.get_latest_version_code() or ""
            etype = CATEGORY_TO_ETYPE.get(self._current_category)
            if not etype:
                return
            presenter = PresenterRegistry.get_presenter(etype, db._conn)
            if not presenter:
                return
            # 合并技能修饰符
            _combined = dict(modifiers or {})
            _additive_keys = {"additionalConsumables", "planeAdditionalConsumables", "planeExtraHangarSize",
                              "extraFighterCount", "asNumPacksBonus", "healthPerLevel", "planeHealthPerLevel",
                              "speedBoostersAdditionalConsumables", "smokeGeneratorAdditionalConsumables",
                              "torpedoReloaderAdditionalConsumables"}
            for _pos, _m in getattr(self, '_selected_skill_mods', {}).items():
                for k, v in _m.items():
                    if k not in _combined:
                        _combined[k] = v
                    else:
                        try:
                            ev, nv = _combined[k], v
                            # dict 值保留给 presenter 按舰种处理
                            if isinstance(ev, dict) or isinstance(nv, dict):
                                _combined[k] = v
                            else:
                                ev_f, nv_f = float(ev), float(nv)
                                if k in _additive_keys:
                                    _combined[k] = ev_f + nv_f
                                else:
                                    _combined[k] = ev_f * nv_f
                        except (ValueError, TypeError):
                            _combined[k] = v
            _eng_key = getattr(self, '_active_engine_key', '')
            _fc_key = getattr(self, '_active_fire_control_key', '')
            _mod_keys = getattr(self, '_active_module_keys', {})
            data = presenter.build(self._current_filename, version_code=vc, modifiers=_combined or None,
                                   engine_letter=_eng_key, fire_control_key=_fc_key,
                                   active_module_keys=_mod_keys)
            if data:
                self._current_analyzed = data
                self._ship_sections = data.get("sections", [])
                self._ship_sub_sections = (data.get("extra") or {}).get("sub_sections", {})
                self._filter_sections_by_config()
                self._rebuild_ship_grid()
        except Exception as e:
            import traceback
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 重算失败: {e}\n{traceback.format_exc()}")

    def _filter_sections_by_config(self):
        """根据当前 _active_config_letter 过滤各 section 的 items"""
        if not hasattr(self, '_active_config_letter') or not self._ship_sections:
            return
        _letter = self._active_config_letter
        for sec in self._ship_sections:
            _letters = sec.get("_config_letters")
            _items_by_letter = sec.get("_items_by_letter")
            if not _letters or not _items_by_letter or len(_letters) <= 1:
                continue
            # 从 _items_by_letter 中精确取对应字母的 items
            sec["items"] = _items_by_letter.get(_letter, _items_by_letter.get(_letters[0], []))
            # 同步更新弹药数据
            _ammo_by_letter = sec.get("_ammo_by_letter", {})
            if _ammo_by_letter:
                sec["raw_ammo_types"] = _ammo_by_letter.get(_letter, _ammo_by_letter.get(_letters[0], []))

    def _on_consumable_btn_click(self, cid: str, dname: str, ckey: str, parent_container: QWidget):
        """消耗品按钮点击：查询数据库并展示详情卡片"""
        from ui.ship_card_widget import ShipCardWidget
        from services.database_service import get_db

        # 移除旧详情页（保留索引 0 的提示页）
        while self._con_detail_stack.count() > 1:
            w = self._con_detail_stack.widget(1)
            self._con_detail_stack.removeWidget(w)
            w.deleteLater()

        # 查询消耗品配置
        items = []
        try:
            conn = get_db()._conn
            vc = ""
            vc_row = conn.execute(
                "SELECT version_code FROM data_version_registry ORDER BY version_id DESC LIMIT 1"
            ).fetchone()
            if vc_row:
                vc = vc_row[0]

            cfg = conn.execute(
                "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key=?",
                (vc, cid, ckey)).fetchone()
            if not cfg:
                cfg = conn.execute(
                    "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? AND config_key='Default'",
                    (vc, cid)).fetchone()
            if not cfg:
                cfg = conn.execute(
                    "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? "
                    "AND config_key NOT IN ('_top','custom','typeinfo') ORDER BY config_key LIMIT 1",
                    (vc, cid)).fetchone()

            if cfg:
                cfgd = dict(cfg)
                ej = cfgd.pop('extra_json', None)
                if ej:
                    try:
                        extra = json.loads(ej)
                        cfgd.update(extra)
                    except (json.JSONDecodeError, TypeError):
                        pass

                from presenters.base_presenter import BasePresenter
                bp = BasePresenter(conn)

                def kv(name, value, unit=""):
                    items.append(bp.make_item(name, value, len(items), unit=unit))

                kv("名称", dname)
                num_raw = cfgd.get('numConsumables') or cfgd.get('num_consumables') or "0"
                if num_raw not in ('0', 0):
                    kv("数量", '无限' if str(num_raw) == '-1' else str(num_raw))
                prep = float(cfgd.get('preparationTime', 0) or 0)
                cd_time = float(cfgd.get('reloadTime', 0) or 0)
                wt = float(cfgd.get('workTime', 0) or 0)
                # 应用已选升级品的修饰符
                if hasattr(self, '_selected_mods') and self._selected_mods:
                    from presenters.ship_presenter import ShipPresenter as _SP
                    _ship_type = ""
                    for _m in self._selected_mods.values():
                        for _mk, _mv in _m.get("modifiers", {}).items():
                            _field = _SP.MODIFIER_MAP.get(_mk)
                            if _field == "冷却时间" and cd_time:
                                _mv_f = float(_mv) if not isinstance(_mv, dict) else float(next(v for v in _mv.values()))
                                cd_time *= (_mv_f if 0.5 <= _mv_f <= 1.5 else 1)
                            elif _field == "持续时间" and wt:
                                _mv_f = float(_mv) if not isinstance(_mv, dict) else float(next(v for v in _mv.values()))
                                wt *= (_mv_f if 0.5 <= _mv_f <= 1.5 else 1)
                is_auto = cfgd.get('isAutoConsumable', False)
                if is_auto:
                    kv("自动使用", "是")
                if prep:
                    kv("准备时间", f"{prep}s")
                if cd_time:
                    kv("冷却时间", f"{cd_time}s")
                if wt:
                    kv("持续时间", f"{wt}s")

                items.append(bp.make_item("消耗品效果", "", row_type="header", order=len(items)))
                ct = cfgd.get('consumableType') or cfgd.get('consumable_type') or ""

                if ct == "crashCrew":
                    kv("", "扑灭起火、清除进水、并修复受损配件。")
                elif ct == "fighter":
                    fn = cfgd.get('fightersName') or ""
                    if fn:
                        fname = bp.resolve_name('plane', fn) or fn
                        kv("战斗机名称", fname)
                    fn2 = cfgd.get('fightersNum') or 0
                    is_inter = cfgd.get('isInterceptor') or 0
                    if fn2 or is_inter:
                        kv("数量", f"{fn2}{' | 截击机' if is_inter else ''}")
                    dog = cfgd.get('dogFightTime', 0)
                    fly = cfgd.get('flyAwayTime', 0)
                    if dog or fly:
                        kv("交战时间", f"狗斗 {dog}s | 离开 {fly}s")
                    rk = cfgd.get('distanceToKill', 0)
                    if rk:
                        kv("巡逻半径", f"{rk/10:.2f}km")
                elif ct == "scout":
                    dc = (float(cfgd.get('artilleryDistCoeff', 0) or 1) - 1)
                    kv("主炮射程", f"{dc*100:+.0f}%")
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
                        kv("限制/扩散", f"速度 {sp}kts / {lt}s")
                elif ct == "speedBoosters":
                    bc = float(cfgd.get('boostCoeff', 0) or 0)
                    kv("最高航速", f"{bc*100:+.0f}%")
                    fef = cfgd.get('forwardEngineForsag', 0)
                    bef = cfgd.get('backwardEngineForsag', 0)
                    if fef or bef:
                        kv("推力", f"前进{fef*100:+.0f}% / 后退{bef*100:+.0f}%")
                elif ct == "sonar":
                    ds = float(cfgd.get('distShip', 0) or 0) * 0.03
                    dt = float(cfgd.get('distTorpedo', 0) or 0) * 0.03
                    dm = float(cfgd.get('distMine', 0) or 0) * 0.03
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
                    kv("主炮装填时间", f"{bc*100:+.0f}%")
                elif ct == "depthCharges":
                    r = float(cfgd.get('radius', 0) or 0) * 0.003
                    kv("半径", f"{r:.2f}km")
                elif ct == "regenCrew":
                    rr = cfgd.get('regenerationHPSpeed', 0) or cfgd.get('regenerationRate', 0)
                    if rr:
                        # 查询该船血量（按当前配置字母），计算实际每秒回复量
                        try:
                            ship_id = self._current_filename or ""
                            _letter = getattr(self, '_active_config_letter', 'A')
                            h_hp = conn.execute(
                                "SELECT health FROM ship_module_hulls "
                                "WHERE version_code=? AND ship_id=? AND config_group LIKE ? AND health IS NOT NULL LIMIT 1",
                                (vc, ship_id, f"{_letter}%")).fetchone()
                            if h_hp and h_hp['health']:
                                actual_hp = rr * h_hp['health']
                                kv("每秒回复血量", f"+{actual_hp:.0f} HP")
                            else:
                                kv("每秒回复血量", f"{'+' if rr > 0 else ''}{rr*100:.2f}%")
                        except Exception:
                            kv("每秒回复血量", f"{'+' if rr > 0 else ''}{rr*100:.2f}%")
                    # 从 ship_module_hulls 查询该船的回复率数据
                    try:
                        ship_id = self._current_filename or ""
                        h = conn.execute(
                            "SELECT hull_regen_part, citadel_regen_part FROM ship_module_hulls "
                            "WHERE version_code=? AND ship_id=? LIMIT 1",
                            (vc, ship_id)).fetchone()
                        if h and (h['hull_regen_part'] is not None or h['citadel_regen_part'] is not None):
                            hrp_str = f"{h['hull_regen_part']*100:.0f}%" if h['hull_regen_part'] is not None else "N/A"
                            crp_str = f"{h['citadel_regen_part']*100:.0f}%" if h['citadel_regen_part'] is not None else "N/A"
                            kv("回复率 (船体/核心区)", f"{hrp_str}/{crp_str}")
                    except Exception:
                        pass
                elif ct == "airDefenseDisp":
                    adm = cfgd.get('areaDamageMultiplier', 0)
                    bdm = cfgd.get('bubbleDamageMultiplier', 0)
                    if adm:
                        kv("防空区域秒伤", f"{adm*100:+.0f}%")
                    if bdm:
                        kv("黑云伤害", f"{bdm*100:+.0f}%")
                elif ct == "hydrophone":
                    zlt = cfgd.get('zoneLifeTime', 0)
                    huf = cfgd.get('hydrophoneUpdateFrequency', 0)
                    hwr = cfgd.get('hydrophoneWaveRadius', 0)
                    if zlt:
                        kv("虚影存留", f"{zlt}s")
                    if huf:
                        kv("刷新间隔", f"{huf}s")
                    if hwr:
                        kv("视野距离", f"{hwr*0.001:.2f}km")
                elif ct == "fastRudders":
                    brt = (float(cfgd.get('buoyancyRudderTimeCoeff', 0) or 1) - 1)
                    bsc = (float(cfgd.get('maxBuoyancySpeedCoeff', 0) or 1) - 1)
                    kv("水平舵换挡", f"{brt*100:+.0f}%")
                    if bsc:
                        kv("上浮/下潜速度", f"{bsc*100:+.0f}%")
                elif ct == "subsEnergyFreeze":
                    kv("", "启用后下潜能力将停止消耗")
                    cue = cfgd.get('canUseOnEmpty', False)
                    kv("电池耗尽时启用", "是" if cue else "否")
                elif ct == "submarineLocator":
                    ds = float(cfgd.get('distShip', 0) or 0) * 0.03
                    if ds:
                        kv("潜艇探测", f"{ds:.2f} km")
                    ac = cfgd.get('affectedClasses', [])
                    if ac:
                        kv("限制探测舰种", ', '.join(ac))
                else:
                    kv("", "该消耗品类型未知，请催促作者更新解析逻辑，谢谢。")
            else:
                items = [{"row_type": "header", "label": "  无详细数据", "value": ""}]
        except Exception as e:
            items = [{"row_type": "header", "label": f"  查询出错: {e}", "value": ""}]

        # 构建详情卡片并添加到 stack
        detail_card = ShipCardWidget({"items": items, "label": f"消耗品详情 - {dname}"})
        self._con_detail_stack.addWidget(detail_card)
        self._con_detail_stack.setCurrentWidget(detail_card)

    def _build_config_widget(self, config_data: dict) -> QWidget:
        """构建带配置选择按钮的二级面板"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        config_labels = config_data.get("config_labels", [])
        config_contents = config_data.get("config_contents", {})

        from PySide6.QtWidgets import QScrollArea as QScrollArea2
        scroll = QScrollArea2()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:#e8e8e8;}")
        bar = QWidget()
        bar.setStyleSheet("QWidget{background:#e8e8e8;border-bottom:1px solid #c0c0c0;}")
        blay = QHBoxLayout(bar)
        blay.setContentsMargins(8, 2, 8, 2)
        blay.setSpacing(4)
        scroll.setWidget(bar)

        cstack = QStackedWidget()
        cbtns: list[QPushButton] = []
        for i, cl in enumerate(config_labels):
            te = QTextEdit()
            te.setReadOnly(True)
            te.setFont(self._make_font("Consolas", 10))
            te.setStyleSheet("""
                QTextEdit {
                    background-color: #fafafa;
                    color: #1a1a1a;
                    border: none;
                    padding: 8px 12px;
                    font-family: "Consolas", "Courier New", monospace;
                    font-size: 11px;
                }
            """)
            raw = config_contents.get(cl, [])
            if raw and isinstance(raw[0], dict):
                lines = []
                for it in raw:
                    name = it.get("name", "")
                    val = it.get("value", "")
                    unit = it.get("unit", "")
                    if it.get("row_type") == "header":
                        lines.append(f"── {name} ──")
                    elif val:
                        lines.append(f"{name}: {val}{' ' + unit if unit else ''}")
                    else:
                        lines.append(name)
                txt = "\n".join(lines)
            else:
                txt = "\n".join(raw) if raw else ""
            te.setPlainText(self._strip_indent(txt))
            cstack.addWidget(te)
            btn = QPushButton(cl)
            btn.setCheckable(True)
            btn.setStyleSheet("QPushButton{background:#3a3a3a;color:#ddd;border:1px solid #555;"
                              "border-radius:4px;padding:4px 10px;font-size:11px;}"
                              "QPushButton:hover{background:#4a4a4a;color:#fff;}"
                              "QPushButton:checked{background:#0078d4;color:#fff;}")
            btn.clicked.connect(partial(self._on_sub_btn, cstack, i, cbtns))
            blay.addWidget(btn)
            cbtns.append(btn)
        blay.addStretch()
        if cbtns:
            cbtns[0].setChecked(True)
            cstack.setCurrentIndex(0)
        layout.addWidget(scroll)
        layout.addWidget(cstack, stretch=1)
        return container

    @staticmethod
    def _strip_indent(text: str) -> str:
        """统一去掉所有行的公共前导缩进"""
        lines = text.split("\n")
        indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
        if not indents:
            return text
        min_indent = min(indents)
        if min_indent == 0:
            return text
        return "\n".join(l[min_indent:] if l.strip() else l for l in lines)

    def _clear_pages(self) -> None:
        """清除所有页面"""
        while self.stack.count() > 0:
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()

    def reset_to_default(self) -> None:
        """重置为默认状态（切换分类时调用）"""
        self._current_category = ""
        self._current_filename = ""
        self._current_raw = None
        self._current_analyzed = None
        self._build_default_pages()
        self._show_hint()
        self.modules_available.emit(None)

    # ── 文件选择（数据库驱动）──────────────────────────

    def _on_file_selected(self, category: str, filename: str) -> None:
        if not category or not filename:
            return
        self._current_category = category
        self._current_filename = filename
        self._current_raw = None
        self._current_analyzed = None
        self._selected_mods: dict[int, dict] = {}
        self._selected_skill_mods: dict[str, dict] = {}
        self._active_config_letter = "A"
        self._active_engine_key = ""
        self._active_fire_control_key = ""
        self._active_hull_key = ""
        self._active_module_keys: dict[str, str] = {}
        # 从 presenter 数据中获取基础配置字母
        if self._current_analyzed:
            _cb = self._current_analyzed.get("config_bar", {})
            if _cb and isinstance(_cb, dict):
                _stock_letter = _cb.get("_stock_config_letter", "")
                if _stock_letter:
                    self._active_config_letter = _stock_letter

        db = get_db()
        if db.exists:
            try:
                vc = db.get_latest_version_code() or ""
                entity = db.get_entity(category, filename, version_code=vc)
                if entity:
                    self._current_raw = entity.get("raw_json")
                # ── 新架构：从结构化表通过 Presenter 构建显示数据 ──
                etype = CATEGORY_TO_ETYPE.get(category)
                if etype:
                    presenter = PresenterRegistry.get_presenter(etype, db._conn)
                    if presenter:
                        data = presenter.build(filename, version_code=vc)
                        if data:
                            self._current_analyzed = data
                            self._apply_analyzed()
                            return
            except Exception as e:
                import traceback
                bus.log_message.emit(f"⚠️ [DetailPanel] {category}/{filename} 构建异常: {e}\n{traceback.format_exc()}")
        self._build_default_pages()
        self._show_msg(f"暂无数据: {category}/{filename}")
        self.modules_available.emit(None)

    # ── 应用数据 ──────────────────────────────────────────

    def _apply_analyzed(self) -> None:
        """根据 analyzed 数据决定页面模式（舰船多section / 通用三页）"""
        sections = (self._current_analyzed or {}).get("sections", [])

        # 判断是否为多 section 的舰船数据（section数 > 1 且含中文模块名）
        is_ship = len(sections) > 1

        if is_ship:
            extra = (self._current_analyzed or {}).get("extra")
            self._build_ship_pages(sections, extra)
            # 舰船模式合并为一页，隐藏 ModuleSelect
            self.modules_available.emit(None)
        else:
            self._build_default_pages()
            if self._current_analyzed:
                self._default_pages[0].setPlainText(self._format_analyzed(self._current_analyzed))
                self._default_pages[1].setPlainText(self._format_data(self._current_analyzed))
            else:
                self._default_pages[0].setPlainText("暂无分析数据")
                self._default_pages[1].setPlainText("暂无分析数据")

            if self._current_raw:
                self._default_pages[2].setPlainText(
                    json.dumps(self._current_raw, indent=4, ensure_ascii=False)
                )
            else:
                self._default_pages[2].setPlainText("暂无原始数据")

            self.modules_available.emit(None)

    @staticmethod
    def _on_sub_btn(sub_stack: QStackedWidget, idx: int,
                    all_btns: list[QPushButton], checked: bool = False) -> None:
        """子分类按钮点击：切换子页面并更新按钮高亮"""
        sub_stack.setCurrentIndex(idx)
        for b in all_btns:
            b.setChecked(False)
        if idx < len(all_btns):
            all_btns[idx].setChecked(True)

    def _show_msg(self, msg: str) -> None:
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if isinstance(w, QTextEdit):
                w.setPlainText(msg)

    # ── 格式化 ────────────────────────────────────────────

    @staticmethod
    def _format_analyzed(analyzed: dict) -> str:
        lines = []
        for sec in analyzed.get("sections", []):
            for item in sorted(sec.get("items", []), key=lambda x: x.get("order", 0)):
                name = item.get("name", "")
                if name.startswith("__SUB_MAP__:") or name.startswith("__SUB__:"):
                    continue
                value, unit = item.get("value", ""), item.get("unit", "")
                if not name and not value:
                    lines.append("")
                elif value:
                    lines.append(f"  {name}: {value}{unit}" if unit else f"  {name}: {value}")
                else:
                    lines.append(f"{name}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_data(analyzed: dict) -> str:
        lines = []
        for sec in analyzed.get("sections", []):
            lines.append(f"【{sec.get('label', '')}】")
            lines.append("-" * 40)
            for item in sorted(sec.get("items", []), key=lambda x: x.get("order", 0)):
                name = item.get("name", "")
                if name.startswith("__SUB_MAP__:") or name.startswith("__SUB__:"):
                    continue
                value = item.get("value", "")
                unit = item.get("unit", "")
                raw_val = item.get("raw_value", "")
                if name and value:
                    v = f"{value}{unit}" if unit else str(value)
                    lines.append(f"  {name:<20} {v:>10}  (raw: {raw_val})")
                elif name:
                    lines.append(f"  {name}")
            lines.append("")
        return "\n".join(lines)

    # ── 页面切换 ──────────────────────────────────────────

    def switch_page(self, mod_id: str) -> None:
        """根据模块 ID 切换页面。舰船用 section label 索引，通用用 detail/data/raw"""
        if self._is_ship_mode:
            idx = self._section_page_indices.get(mod_id)
            if idx is not None:
                self.stack.setCurrentIndex(idx)
        else:
            page_map = {"detail": 0, "data": 1, "raw": 2}
            idx = page_map.get(mod_id, 0)
            if idx < self.stack.count():
                self.stack.setCurrentIndex(idx)

    # ── 提示 ──────────────────────────────────────────────

    def _show_hint(self) -> None:
        hint = (
            "📋 使用说明\n\n"
            "1. ⚙ 设置 → 高级设置，配置游戏目录\n"
            "2. 📦 加载数据 — 从游戏中提取并解析数据\n"
            "3. 🌐 加载文本 — 下载语言文件（可选）\n"
            "4. 点击左侧分类按钮选择要浏览的类别\n"
            "5. 在文件列表中点击文件查看详情\n\n"
            "💡 提示：加载数据后，文件列表会自动填充"
        )
        for te in self._default_pages:
            te.setPlainText(hint)

