"""
DetailPanel —— 右侧详情展示面板（QStackedWidget，动态页面）。

完全基于数据库读取显示，不再调用分析器。
由 ModuleSelect 控制页面切换。
"""

from __future__ import annotations

import json
from collections import defaultdict

from functools import partial

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QTextEdit, QPushButton, QLabel, QFrame, QButtonGroup,
    QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap

from app.signals import bus
from services.database_service import get_db
from presenters.registry import PresenterRegistry, CATEGORY_TO_ETYPE
from ui.ship_card_widget import ShipCardWidget
from utils.theme import theme
from utils.image_paths import pic_path


# U13: 加性修饰符键集（3 处重复 → 模块级常量）
# crashCrewWorkTimeBonus（损害管制消耗品作用时间）在 ship_presenter 中按加算处理，属加性键
_ADDITIVE_KEYS_BASE = frozenset({
    "additionalConsumables", "planeAdditionalConsumables", "planeExtraHangarSize",
    "extraFighterCount", "asNumPacksBonus", "healthPerLevel", "planeHealthPerLevel",
    "speedBoostersAdditionalConsumables", "smokeGeneratorAdditionalConsumables",
    "torpedoReloaderAdditionalConsumables", "crashCrewWorkTimeBonus",
})


class DetailPanel(QWidget):
    """右侧详情面板（数据库驱动）"""

    modules_available = Signal(object)

    @staticmethod
    def _text_style() -> str:
        return theme.qss("""
            QTextEdit {
                background-color: @panel_bg@;
                color: @text@;
                border: none;
                padding: 12px;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
            }
        """)

    @staticmethod
    def _mono_style_light() -> str:
        return theme.qss("""
            QTextEdit {
                background-color: @panel_alt@;
                color: @text@;
                border: none;
                padding: 12px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
            }
        """)

    @staticmethod
    def _mono_style_dark() -> str:
        """原始数据页：跟随主题的等宽字体样式"""
        return theme.qss("""
            QTextEdit {
                background-color: @input_bg@;
                color: @text@;
                border: none;
                padding: 12px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
            }
        """)

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
        self.wows_type = self._current_server()  # 方案 C：服务器标识（Lesta/Wargaming）
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
        # 消耗品详情选中态：id(详情stack) → 当前激活的 "cid::ckey"（舰船/飞机各自独立）
        self._active_con_keys: dict[int, str] = {}
        # 当前选中的消耗品按钮引用（跨槽位/跨区域唯一高亮）
        self._active_con_btn = None
        # WG 信号旗选中态：mod_id → flag_data（多选可叠加，默认全选参与计算）
        self._selected_wg_signal_flags: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self._build_default_pages()
        self._show_hint()
        # 启动时不通知 ModuleSelect，保持空白占位
        bus.file_selected.connect(self._on_file_selected)
        bus.copy_ship_info.connect(self._copy_ship_info_to_clipboard)
        # 主题切换后刷新默认页文字/背景颜色
        bus.theme_changed.connect(self._on_theme_changed)

    def _apply_default_page_styles(self) -> None:
        """显式重置默认三页样式，确保说明页在主题切换时也跟随更新。"""
        if not self._default_pages:
            return
        styles = (self._text_style(), self._mono_style_light(), self._mono_style_dark())
        for te, style in zip(self._default_pages, styles):
            try:
                te.setStyleSheet(style)
                te.viewport().setAutoFillBackground(False)
            except Exception:  # noqa: BLE001
                pass

    def _on_theme_changed(self, _mode: str) -> None:
        """主题切换后：立即刷新默认页内容与样式；舰船卡片模式则完整重建页面以应用新主题。"""
        try:
            self._apply_default_page_styles()
            if self._default_pages:
                # 过滤已被删除的页面，避免操作失效对象崩溃
                from shiboken6 import isValid
                self._default_pages = [te for te in self._default_pages if isValid(te)]
            if self._default_pages:
                # 强制让说明页重新写入文本，避免它保留旧主题渲染状态直到手动刷新
                self._show_hint()
                for te in self._default_pages:
                    try:
                        te.viewport().update()
                        te.update()
                        te.repaint()
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass
        # 舰船卡片模式：完整重建当前船页面（含 config bar 与所有卡片/子面板）
        if self._is_ship_mode:
            from PySide6.QtCore import QTimer

            def _rebuild_all():
                try:
                    self._build_ship_pages(self._ship_sections, self._ship_extra)
                except Exception:  # noqa: BLE001
                    pass
            # 绑定 receiver=self：面板被 deleteLater 后 Qt 自动取消该挂起回调，
            # 避免访问已删除 C++ 对象触发 RuntimeError: already deleted
            QTimer.singleShot(0, self, _rebuild_all)

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
            ("detail", self._text_style(), self._make_font("Microsoft YaHei", 11)),
            ("data", self._mono_style_light(), self._make_font("Consolas", 10)),
            ("raw", self._mono_style_dark(), self._make_font("Consolas", 10)),
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
        self._ship_extra = extra or {}
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
        bottom_scroll.setStyleSheet(theme.qss("QScrollArea{border:none;background-color:@window_bg@;}"))

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

        # 延迟重建，等布局完成后获取真实宽度（绑定 receiver=self，面板删除时自动取消）
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self, self._rebuild_ship_grid)

        # 唯一页面
        self._section_page_indices = {"全部": 0}
        self.stack.addWidget(outer_container)

    # ── EPIC 技能/天赋配置 ──
    # 内存缓存（切换舰船时清空）
    _crew_custom_cache: dict = {}

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
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel
        _OVERLAY_PATH = pic_path("icon_epic_skill.png")
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
        _ship_type = config.get("shiptype_en", "") or config.get("shiptype", "")
        bar = QWidget()
        bar.setStyleSheet(theme.qss("""
            QWidget#ConfigBar {
                background-color: @panel_bg@;
                border: 1px solid @border@;
                border-radius: 6px;
            }
        """))
        bar.setObjectName("ConfigBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(0)

        COL_TITLE = theme.qss("font-size:11px; font-weight:bold; color:@text_muted@; padding:0 0 3px 0;")

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

        UC_ICONS = {"_Artillery": "🔫", "_Torpedoes": "💣", "_Hull": "🚢",
                    "_Engine": "⚙", "_Suo": "📡",
                    "_Fighter": "✈", "_DiveBomber": "💥", "_TorpedoBomber": "⚓",
                    "_FlightControl": "🎯", "_SkipBomber": "💥", "_MineBomber": "💣"}
        UC_NAMES = {"_Artillery": "主炮", "_Torpedoes": "鱼雷", "_Hull": "船体",
                    "_Engine": "引擎", "_Suo": "火控", "_Sonar": "声呐",
                    "_Fighter": "攻击机", "_DiveBomber": "俯冲轰炸机",
                    "_TorpedoBomber": "鱼雷轰炸机", "_FlightControl": "飞控",
                    "_SkipBomber": "弹跳轰炸机", "_MineBomber": "水雷轰炸机"}
        UC_IMAGE_MAP = {
            "_Artillery": "module_Artillery.png",
            "_Torpedoes": "module_Torpedoes.png",
            "_Hull": "module_Hull.png",
            "_Engine": "module_Engine.png",
            "_Suo": "module_Suo.png",
            "_Sonar": "module_Sonar.png",
            "_Fighter": "module_Fighter.png",
            "_DiveBomber": "module_DiveBomber.png",
            "_TorpedoBomber": "module_TorpedoBomber.png",
            "_SkipBomber": "module_SkipBomber.png",
            "_MineBomber": "module_MineBomber.png",
        }
        MODULES_IMAGE_DIR = pic_path("modules")
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
            "_Sonar": "pinger",
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

        BTN_STYLE = theme.qss("""
            QPushButton {
                background: @panel_alt@;
                border: 1px solid @border@;
                border-radius: 6px; padding: 2px;
                font-size: 9px; color: @text@;
                min-width: 40px; min-height: 40px;
                max-width: 40px; max-height: 40px;
            }
            QPushButton:hover {
                background: @hover_bg@;
                border-color: @selected_bg@;
            }
            QPushButton:checked {
                background: @selected_bg@; color: @selected_fg@; border-color: @selected_bg@;
            }
        """)
        # 缺少图片时：缩小字号、弱化文字（主题化）
        BTN_STYLE_TXT = theme.qss("""
            QPushButton {
                background: @panel_alt@;
                border: 1px solid @border@;
                border-radius: 6px; padding: 2px;
                font-size: 8px; color: @text_hint@;
                min-width: 40px; min-height: 40px;
                max-width: 40px; max-height: 40px;
            }
            QPushButton:hover {
                background: @hover_bg@;
                border-color: @selected_bg@;
            }
            QPushButton:checked {
                background: @selected_bg@; color: @selected_fg@; border-color: @selected_bg@;
            }
        """)

        def _build_module_group(ut: str, options: list, un: str, icon: str) -> QWidget:
            """构建单个配件组（标题 + 按钮行）"""
            group = QWidget()
            gl = QVBoxLayout(group)
            gl.setContentsMargins(0,0,0,0); gl.setSpacing(3)
            gl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title = QLabel(f"{icon} {un}")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet(theme.qss("font-size:10px; color:@text_muted@;"))
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
                btn = QPushButton("")
                btn.setFixedSize(40, 40)
                btn.setCheckable(True)
                btn.setStyleSheet(BTN_STYLE)
                btn.setToolTip(display_name)
                btn.setObjectName(f"mod_{ut}_{mid}")
                btn_group.addButton(btn, i)

                # 加载模块图片作为按钮图标（WG：icon_module_X.png；Lesta：module_X.png）
                img_file = UC_IMAGE_MAP.get(ut)
                if img_file:
                    img_file = self._module_icon_name(img_file)
                    _qp = f"{MODULES_IMAGE_DIR}/{img_file}"
                    pixmap = QPixmap(_qp)
                    if not pixmap.isNull():
                        scaled = pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        btn.setIcon(QIcon(scaled))
                        btn.setIconSize(QSize(24, 24))
                    else:
                        btn.setText("缺少图片")
                        btn.setStyleSheet(BTN_STYLE_TXT)

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
                elif ut == "_Sonar":
                    sonar_key = mod["id"]
                    btn.clicked.connect(
                        partial(self._on_sonar_click, sonar_key)
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
        ALL_UC = ["_Artillery", "_Torpedoes", "_Hull", "_Engine", "_Suo", "_Sonar",
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
                _ph.setStyleSheet(theme.qss("color:@text_hint@; font-size:10px; padding:4px;"))
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
                modernization_dir = pic_path("modernization")
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
                # 老版本(v3.2.2-test1)样式：固定深色底+浅色文字，图标清晰可读（不随主题变化）
                SLOT_STYLE = """
                    QPushButton {
                        background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
                        padding: 2px; min-width: 36px; min-height: 36px; max-width: 36px; max-height: 36px;
                    }
                    QPushButton:hover { background: #4a4a4a; border-color: #1a73e8; }
                    QPushButton:checked { background: #1a73e8; border-color: #1a73e8; }
                """
                SLOT_STYLE_TXT = """
                    QPushButton {
                        background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
                        padding: 2px; font-size: 8px; color: #bbb;
                        min-width: 36px; min-height: 36px; max-width: 36px; max-height: 36px;
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
                    title.setStyleSheet(theme.qss("font-size:9px;color:@text_muted@;font-weight:bold;"))
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
                                ob.setStyleSheet(SLOT_STYLE_TXT)
                            tt_parts = [f'<div style="font-weight:bold;">{mod.get("name", mid)}</div>']
                            mod_dict = mod.get("modifiers", {})
                            if mod_dict:
                                from models.name_mapping import Mapping as NMM
                                tt_parts.append('<hr style="border-color:#555;">')
                                for mk, mv in sorted(mod_dict.items()):
                                    label = NMM.MODIFIER_MAP.get(mk, mk)
                                    if isinstance(mv, dict):
                                        mv = mv.get(_ship_type) or next((v for v in mv.values() if isinstance(v, (int, float))), 0)
                                    try:
                                        mv_f = float(mv)
                                        if mv_f == 0:
                                            continue
                                        ft = NMM.format_modifier(mk, mv_f, color=True)
                                        if ft:
                                            tt_parts.append(f'<div style="white-space:nowrap;">{label}: {ft}</div>')
                                    except (ValueError, TypeError):
                                        tt_parts.append(f'<div>{label}: {mv}</div>')
                            ob.setToolTip(NMM.rich_tooltip("".join(tt_parts)))
                            ob.clicked.connect(lambda checked, si=i, m=mod, btn=ob: self._on_mod_opt_click(si, m, btn))
                            if self._selected_mods.get(i) and self._selected_mods[i]["mod_id"] == mid:
                                ob.setChecked(True)
                            col_layout.addWidget(ob, alignment=Qt.AlignmentFlag.AlignCenter)
                    col_layout.addStretch()
                    uc_layout.addWidget(col_w)
                cl.addWidget(upgrade_container)
                layout.addWidget(col, stretch=1)

            elif section_key == "signal":  # 第3列：信号旗（6槽位，图片按钮）
                if self.is_wg():
                    self._build_wg_signal_column(config, _col, layout)
                    continue
                self._build_lesta_signal_column(config, _col, layout)
            elif section_key == "commander":  # 第4列：舰长技能
                if self.is_wg():
                    self._build_wg_commander_column(config, _col, layout)
                    continue
                self._build_lesta_commander_column(config, _col, layout)
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

    def _on_sonar_click(self, sonar_key: str) -> None:
        """声呐配件按钮点击：不切换配置字母，只过滤声呐模块数据"""
        self._active_sonar_key = sonar_key
        self._refresh_data_only()

    def _on_hull_module_click(self, hull_key: str) -> None:
        """船体模块按钮点击：记录完整组件 ID"""
        self._active_hull_key = hull_key
        self._active_config_letter = hull_key[0] if hull_key else "A"
        # 切换船体时清空火控/引擎 key，让 presenter 自动解析新配置的 stock 值
        self._active_engine_key = ""
        self._active_fire_control_key = ""
        self._active_sonar_key = ""
        self._active_module_keys = {}
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
                    "船体": 1, "引擎": 1, "支援": 1,
                    "主炮": 2, "副炮": 2, "次级主炮": 2,
                    "鱼雷": 2, "防空": 2, "深水炸弹": 3,
                    "舰载机": 3,
                }
            else:
                cols = 3
                # 三列布局：深水炸弹移到第3列
                LABEL_TO_COL = {
                    "基础属性": 0, "消耗品数据": 0,
                    "船体": 1, "引擎": 1, "主炮": 1, "副炮": 1, "次级主炮": 1,
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
                stretch = 2 if i == 0 else 3
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
                        # 「基础属性」卡片最下方追加 3D 模型查看入口按钮
                        action = None
                        if label == "基础属性" and self._current_filename:
                            action = {
                                "text": "⛵  3D 模型查看",
                                "tooltip": "打开当前舰船的 3D 模型 / 装甲查看器（自动载入本舰模型）",
                                "data": self._current_filename,
                            }
                        widget = ShipCardWidget(sec, firing_arc=sec.get("_firing_arc"),
                                                action=action)
                        widget.firing_arc_clicked.connect(self._open_firing_arc)
                        if action:
                            widget.action_clicked.connect(self._open_3d_viewer)

                    col_layout.addWidget(widget)

        finally:
            self._ship_rebuilding = False
        self.stack.setCurrentIndex(0)

    def _open_firing_arc(self, fa: dict):
        """打开炮塔射界查看窗口并定位到指定舰船/武器槽位。"""
        try:
            from ui.firing_arc_dialog import FiringArcDialog
            from utils.window_utils import center_on_screen
            if not hasattr(self, "_arcs_dialog") or self._arcs_dialog is None:
                self._arcs_dialog = FiringArcDialog()
                center_on_screen(self._arcs_dialog, self.window())
            self._arcs_dialog.open_for(fa.get("ship_id", ""), fa.get("slot_type", ""))
            self._arcs_dialog.show()
            self._arcs_dialog.raise_()
            self._arcs_dialog.activateWindow()
        except Exception as exc:
            bus.log_message.emit(f"❌ 打开射界查看器失败: {exc}")

    def _open_3d_viewer(self, ship_id):
        """打开 3D 模型查看器并自动载入当前所选舰船（懒创建单实例）。

        不传 parent：传主窗口为父会让 QOpenGLWidget 作为主窗口子窗口创建，
        Windows 上 GL 上下文创建触发主窗口重绘闪烁。关闭联动由
        MainWindow.closeEvent 显式关闭 detail._geometry_viewer 保证。
        """
        try:
            from ui.geometry_viewer import GeometryViewerDialog
            from utils.window_utils import ensure_dialog_shown
            if not getattr(self, "_geometry_viewer", None) or not getattr(self._geometry_viewer, "_restored_geometry", False):
                ensure_dialog_shown(self, "_geometry_viewer", GeometryViewerDialog, self.window())
            else:
                self._geometry_viewer.show()
                self._geometry_viewer.raise_()
                self._geometry_viewer.activateWindow()
            self._geometry_viewer.open_ship(ship_id)
        except Exception as exc:
            bus.log_message.emit(f"❌ 打开 3D 查看器失败: {exc}")

    def _build_sub_widget(self, title: str, sub_info: dict) -> QWidget:
        """构建无标签栏的子分类面板，仅显示默认配置内容，顶栏按钮控制切换"""
        from ui.ship_card_widget import SECTION_ICONS, card_style
        from PySide6.QtWidgets import QGroupBox

        icon = SECTION_ICONS.get(title, "")
        title_text = f"  {icon} {title}" if icon else f"  {title}"

        container = QGroupBox(title_text)
        container.setStyleSheet(card_style())
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
                                 "最大距离", "最小距离", "单架飞机血量", "载弹量", "弹药",
                                 "巡航速度", "最大速度", "最小速度", "中队飞机数量",
                                 "烟幕半径", "烟幕高度", "烟幕持续时间", "生效时间", "生效延迟",
                                 "主炮射程", "主炮炮弹的最大误差", "中口径炮射程", "中口径炮炮弹的最大误差"}
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
                            from PySide6.QtGui import QPixmap, QIcon
                            from PySide6.QtCore import QSize
                            from PySide6.QtWidgets import QPushButton, QLabel
                            ga = raw_ammo[ammo_idx:ammo_idx+ac]; ammo_idx += ac
                            br = QWidget(); bl = QHBoxLayout(br); bl.setContentsMargins(4,0,4,0); bl.setSpacing(6); bl.setAlignment(Qt.AlignmentFlag.AlignLeft)
                            st = QStackedWidget(); st.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum); st.setVisible(False)
                            for ai in ga:
                                an = ai.get("name",""); di = ai.get("detail_items",[]); at = ai.get("ammo_type","").lower(); sp = ai.get("species","").lower()
                                btn = QPushButton(""); btn.setFixedSize(36,36); btn.setCheckable(True)
                                btn.setStyleSheet(theme.qss("QPushButton{background:@panel_alt@;border:1px solid @border@;border-radius:6px;padding:2px;min-width:36px;min-height:36px;max-width:36px;max-height:36px;}QPushButton:hover{background:@hover_bg@;border-color:@selected_bg@;}QPushButton:checked{background:@selected_bg@;border-color:@selected_bg@;}"))
                                btn.setToolTip(an)
                                cand = self._ammo_icon_candidates(at, sp, ai, bool(ai.get("switchable")))
                                ip = next((p for c in cand if not (p:=QPixmap(pic_path(f"ammo_types/{c}"))).isNull()), None)
                                if ip: btn.setIcon(QIcon(ip.scaled(28,28,Qt.KeepAspectRatio,Qt.SmoothTransformation))); btn.setIconSize(QSize(28,28))
                                else: btn.setText(an[:2] if an else "?"); btn.setStyleSheet(btn.styleSheet().replace("padding:2px;", f"padding:2px;font-size:8px;color:{theme['text_muted']};"))
                                bl.addWidget(btn)
                                st.addWidget(ShipCardWidget({"label":an,"items":di}) if di else (QLabel("无详细数据",styleSheet=theme.qss("color:@text_hint@;font-size:11px;padding:8px;"),alignment=Qt.AlignmentFlag.AlignCenter)))
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
                    te.setStyleSheet(theme.qss("""
                        QTextEdit {
                            background-color: @panel_alt@;
                            color: @text@;
                            border: none;
                            padding: 8px 12px;
                            font-family: "Consolas", "Courier New", monospace;
                            font-size: 11px;
                        }
                    """))
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
        from ui.ship_card_widget import ShipCardWidget, card_style
        from PySide6.QtWidgets import QGroupBox, QStackedWidget
        from PySide6.QtGui import QPixmap, QIcon
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QLabel

        container = QGroupBox("  舰载机")
        container.setStyleSheet(card_style())
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        labels = sub_info.get("sub_labels", [])
        sub_keys = sub_info.get("sub_keys", {})
        contents = sub_info.get("sub_contents", {})
        if not labels:
            return container

        BTN_STYLE = theme.qss("""
            QPushButton {
                background: @panel_alt@;
                border: 1px solid @border@;
                border-radius: 6px; padding: 2px;
                min-width: 36px; min-height: 36px;
                max-width: 36px; max-height: 36px;
            }
            QPushButton:hover {
                background: @hover_bg@;
                border-color: @selected_bg@;
            }
            QPushButton:checked {
                background: @selected_bg@; border-color: @selected_bg@;
            }
        """)

        for sl in labels:
            content = contents.get(sl, {})
            if not isinstance(content, dict):
                continue

            grp = QGroupBox(f"  {sl}")
            grp.setStyleSheet(card_style())
            grp.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            grp_layout = QVBoxLayout(grp)
            grp_layout.setContentsMargins(2, 2, 2, 2)
            grp_layout.setSpacing(2)

            config_labels = content.get("config_labels", [])
            config_contents = content.get("config_contents", {})

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
                    "引擎加速时间", "引擎加速冷却时间",
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
                        candidates = self._ammo_icon_candidates(at, sp, ammo_info, bool(ammo_info.get("switchable")))
                        img_path = None
                        for c in candidates:
                            p = QPixmap(pic_path(f"ammo_types/{c}"))
                            if not p.isNull(): img_path = p; break
                        if img_path and not img_path.isNull():
                            scaled = img_path.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            btn.setIcon(QIcon(scaled))
                            btn.setIconSize(QSize(28, 28))
                        else:
                            btn.setText(aname[:2] if aname else "?")
                            btn.setStyleSheet(BTN_STYLE.replace("padding: 2px;", f"padding: 2px; font-size:8px; color:{theme['text_muted']};"))
                        # 弹跳轰炸机炸弹：skip_bomb 标记覆盖整个按钮（图片自带透明区域）
                        if sp == "skipbomb":
                            _bp = QPixmap(pic_path("ammo_types/unique_features/indicators/skip_bomb.png"))
                            if not _bp.isNull():
                                _badge = QLabel(btn)
                                _badge.setScaledContents(True)
                                _badge.setPixmap(_bp)
                                _badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                                _badge.setStyleSheet("background: transparent;")
                                _badge.setGeometry(0, 0, 36, 36)  # 强制拉伸填满整按钮，与弹药图完全覆盖
                        abl.addWidget(btn)
                        if detail_items:
                            ammo_stack.addWidget(ShipCardWidget({"label": aname, "items": detail_items}))
                        else:
                            lbl = QLabel("无详细数据"); lbl.setStyleSheet(theme.qss("color:@text_hint@; font-size:11px; padding:8px;")); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                            ammo_stack.addWidget(lbl)
                        ci = ammo_stack.count() - 1
                        btn.clicked.connect(lambda checked, i=ci, s=ammo_stack, b=btn, bl_=abl: self._on_ammo_btn_click(i, s, bl_, b))
                    abl.addStretch()
                    wl.addWidget(ammo_btn_row)
                    wl.addWidget(ammo_stack)

                # 消耗品按钮行 + 详情堆栈（完全照搬舰船消耗品样式）
                if raw_con:
                    CON_BTN_STYLE = theme.qss("""
                        QPushButton {
                            background: @panel_alt@;
                            border: 1px solid @border@;
                            border-radius: 6px; padding: 2px;
                            min-width: 40px; min-height: 40px;
                            max-width: 40px; max-height: 40px;
                        }
                        QPushButton:hover {
                            background: @hover_bg@;
                            border-color: @selected_bg@;
                        }
                        QPushButton:checked {
                            background: @selected_bg@; border-color: @selected_bg@;
                        }
                    """)
                    consumables_dir = pic_path("consumables")
                    con_btn_row = QWidget()
                    cbr_layout = QHBoxLayout(con_btn_row)
                    cbr_layout.setContentsMargins(4, 2, 4, 2)
                    cbr_layout.setSpacing(6)
                    cbr_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                    con_stack = QStackedWidget()
                    con_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
                    # 索引 0 = 提示页（与舰船 _con_detail_stack 一致），点击后由
                    # _on_consumable_btn_click 动态添加详情卡片
                    _con_prompt = QLabel("点击上方消耗品按钮查看详细数据")
                    _con_prompt.setStyleSheet(theme.qss("color:@text_hint@; font-size:11px; padding:20px;"))
                    _con_prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    con_stack.addWidget(_con_prompt)
                    con_btns: list[QPushButton] = []
                    for con_info in raw_con:
                        dname = con_info.get("display_name", "?")
                        cid = con_info.get("consumable_id", "")
                        ckey = con_info.get("config_key", "")
                        btn = QPushButton("")
                        btn.setFixedSize(40, 40)
                        btn.setCheckable(True)
                        btn.setStyleSheet(CON_BTN_STYLE)
                        btn.setToolTip(dname)
                        # 消耗品图片命名（WG：consumable_X.png；Lesta：consumable_X_0.png）
                        img_path = f"{consumables_dir}/{self._consumable_icon_name(cid)}"
                        pixmap = QPixmap(img_path)
                        if not pixmap.isNull():
                            scaled = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            btn.setIcon(QIcon(scaled))
                            btn.setIconSize(QSize(32, 32))
                        else:
                            btn.setText(cid[:2] if cid else "?")
                            btn.setStyleSheet(CON_BTN_STYLE.replace("padding: 2px;", f"padding: 2px; font-size:9px; color:{theme['text_muted']};"))
                        # WG：可用激活方式含 AUTO → 整图覆盖按钮（同 skip_bomb，图片带透明部分）
                        _aam = con_info.get('available_activation_modes') or []
                        if any(str(x).upper() == "AUTO" for x in _aam):
                            _aa_pix = QPixmap(pic_path("consumables/features/auto_activation.png"))
                            if not _aa_pix.isNull():
                                _aa_badge = QLabel(btn)
                                _aa_badge.setScaledContents(True)
                                _aa_badge.setPixmap(_aa_pix)
                                _aa_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                                _aa_badge.setStyleSheet("background: transparent;")
                                _aa_badge.setGeometry(0, 0, 40, 40)  # 强制拉伸填满整按钮，与消耗品图完全覆盖
                        # WG 时间制消耗品 → 叠加时间制角标（time_based.png，整图覆盖同 AUTO）
                        if con_info.get("time_based"):
                            _tb_pix = QPixmap(pic_path("consumables/features/time_based.png"))
                            if not _tb_pix.isNull():
                                _tb_badge = QLabel(btn)
                                _tb_badge.setScaledContents(True)
                                _tb_badge.setPixmap(_tb_pix)
                                _tb_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                                _tb_badge.setStyleSheet("background: transparent;")
                                _tb_badge.setGeometry(0, 0, 40, 40)  # 强制拉伸填满整按钮，与消耗品图完全覆盖
                        cbr_layout.addWidget(btn)
                        con_btns.append(btn)
                        # 点击与舰船消耗品共用 _on_consumable_btn_click：
                        # 查数据库 + 走完整类型分支树（WG/Lesta 特有类型、时间制等）
                        btn.clicked.connect(
                            lambda checked=False, cid=cid, dname=dname, ckey=ckey, b=btn,
                                   btns=con_btns, st=con_stack:
                                self._on_consumable_btn_click(cid, dname, ckey, w, 0, b, btns, st))
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
        from ui.ship_card_widget import ShipCardWidget, card_style
        from PySide6.QtGui import QPixmap, QIcon
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QGroupBox, QStackedWidget, QPushButton, QLabel

        label = section.get("label", "支援")
        items = section.get("items", [])
        raw_ammo = section.get("raw_ammo_types", [])

        KEEP_ASUP = {"飞机型号", "最大充能次数", "装填时间", "持续时间", "攻击编组数量", "最远到位时间", "巡航速度",
                     "最大距离", "最小距离", "单架飞机血量", "载弹量", "弹药",
                     "最大速度", "最小速度", "中队飞机数量",
                     "烟幕半径", "烟幕高度", "烟幕持续时间", "生效时间", "生效延迟",
                     "主炮射程", "主炮炮弹的最大误差", "中口径炮射程", "中口径炮炮弹的最大误差"}

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
        container.setStyleSheet(card_style())
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        BTN_STYLE = theme.qss("""
            QPushButton {
                background: @panel_alt@;
                border: 1px solid @border@;
                border-radius: 6px; padding: 2px;
                min-width: 36px; min-height: 36px;
                max-width: 36px; max-height: 36px;
            }
            QPushButton:hover { background: @hover_bg@; border-color: @selected_bg@; }
            QPushButton:checked { background: @selected_bg@; border-color: @selected_bg@; }
        """)

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
                    candidates = self._ammo_icon_candidates(at, sp, ammo_info, bool(ammo_info.get("switchable")))
                    img_path = None
                    for c in candidates:
                        p = QPixmap(pic_path(f"ammo_types/{c}"))
                        if not p.isNull(): img_path = p; break
                    if img_path and not img_path.isNull():
                        scaled = img_path.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        btn.setIcon(QIcon(scaled))
                        btn.setIconSize(QSize(28, 28))
                    else:
                        btn.setText(aname[:2] if aname else "?")
                        btn.setStyleSheet(BTN_STYLE.replace("padding: 2px;", f"padding: 2px; font-size:8px; color:{theme['text_muted']};"))
                    bl.addWidget(btn)
                    if detail_items:
                        ammo_stack.addWidget(ShipCardWidget({"label": aname, "items": detail_items}))
                    else:
                        lbl = QLabel("无详细数据"); lbl.setStyleSheet(theme.qss("color:@text_hint@; font-size:11px; padding:8px;")); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        ammo_stack.addWidget(lbl)
                    ci = ammo_stack.count() - 1
                    btn.clicked.connect(lambda checked, i=ci, s=ammo_stack, b=btn, bl_=bl: self._on_ammo_btn_click(i, s, bl_, b))
                bl.addStretch()
                layout.addWidget(btn_row)
                layout.addWidget(ammo_stack)

        return container

    def _build_consumables_widget(self, section: dict) -> QWidget:
        """构建消耗品数据面板：按槽位纵向排列，每槽位以按钮+图片显示"""
        from ui.ship_card_widget import card_style
        from PySide6.QtWidgets import QGroupBox, QStackedWidget

        container = QGroupBox("  消耗品数据")
        container.setStyleSheet(card_style())
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

        consumables_dir = pic_path("consumables")

        BTN_STYLE = theme.qss("""
            QPushButton {
                background: @panel_alt@;
                border: 1px solid @border@;
                border-radius: 6px; padding: 2px;
                min-width: 40px; min-height: 40px;
                max-width: 40px; max-height: 40px;
            }
            QPushButton:hover {
                background: @hover_bg@;
                border-color: @selected_bg@;
            }
            QPushButton:checked {
                background: @selected_bg@; border-color: @selected_bg@;
            }
        """)

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

            btns_in_slot: list = []
            for rs in items_in_slot:
                cid = rs["consumable_id"]
                dname = rs["display_name"]
                btn = QPushButton("")
                btn.setFixedSize(40, 40)
                btn.setStyleSheet(BTN_STYLE)
                btn.setToolTip(dname)
                btn.setObjectName(f"con_{cid}")
                btn.setCheckable(True)
                btns_in_slot.append(btn)

                # 加载消耗品图片（WG：consumable_X.png；Lesta：consumable_X_0.png）
                img_path = f"{consumables_dir}/{self._consumable_icon_name(cid)}"
                pixmap = QPixmap(img_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    btn.setIcon(QIcon(scaled))
                    btn.setIconSize(QSize(32, 32))
                else:
                    # 无图片时显示首字母
                    btn.setText(cid[:2] if cid else "?")
                    btn.setStyleSheet(BTN_STYLE.replace("padding: 2px;", f"padding: 2px; font-size:9px; color:{theme['text_muted']};"))

                # WG：可用激活方式含 AUTO → 整图覆盖按钮（同 skip_bomb，图片带透明部分）
                _aam = rs.get('available_activation_modes') or []
                if any(str(x).upper() == "AUTO" for x in _aam):
                    _aa_pix = QPixmap(pic_path("consumables/features/auto_activation.png"))
                    if not _aa_pix.isNull():
                        _aa_badge = QLabel(btn)
                        _aa_badge.setScaledContents(True)
                        _aa_badge.setPixmap(_aa_pix)
                        _aa_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                        _aa_badge.setStyleSheet("background: transparent;")
                        _aa_badge.setGeometry(0, 0, 40, 40)  # 强制拉伸填满整按钮，与消耗品图完全覆盖
                # WG 时间制消耗品 → 叠加时间制角标（time_based.png，整图覆盖同 AUTO）
                if rs.get("time_based"):
                    _tb_pix = QPixmap(pic_path("consumables/features/time_based.png"))
                    if not _tb_pix.isNull():
                        _tb_badge = QLabel(btn)
                        _tb_badge.setScaledContents(True)
                        _tb_badge.setPixmap(_tb_pix)
                        _tb_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                        _tb_badge.setStyleSheet("background: transparent;")
                        _tb_badge.setGeometry(0, 0, 40, 40)  # 强制拉伸填满整按钮，与消耗品图完全覆盖

                ckey = rs.get('config_key', 'Default')
                # 计算 additionalConsumables 修饰符值（升级品 + 技能）
                _extra_count = 0
                # 升级品：_selected_mods 的每个值有 "modifiers" 子键
                for _m in getattr(self, '_selected_mods', {}).values():
                    _mods = _m.get("modifiers", {}) if isinstance(_m, dict) else {}
                    if "additionalConsumables" in _mods:
                        _mv = _mods["additionalConsumables"]
                        if isinstance(_mv, dict):
                            _st = (self._current_analyzed or {}).get("config_bar", {}).get("shiptype_en", "")
                            _mv = _mv.get(_st) or next((x for x in _mv.values() if isinstance(x, (int, float))), 0)
                        try:
                            _extra_count += int(float(_mv))
                        except (ValueError, TypeError):
                            pass
                # 技能：_selected_skill_mods 的值本身就是修饰符 dict
                for _sk_mods in getattr(self, '_selected_skill_mods', {}).values():
                    if isinstance(_sk_mods, dict) and "additionalConsumables" in _sk_mods:
                        _mv = _sk_mods["additionalConsumables"]
                        if isinstance(_mv, dict):
                            _st = (self._current_analyzed or {}).get("config_bar", {}).get("shiptype_en", "")
                            _mv = _mv.get(_st) or next((x for x in _mv.values() if isinstance(x, (int, float))), 0)
                        try:
                            _extra_count += int(float(_mv))
                        except (ValueError, TypeError):
                            pass
                btn.clicked.connect(partial(self._on_consumable_btn_click, cid, dname, ckey, container, _extra_count, btn, list(btns_in_slot)))
                sr_layout.addWidget(btn)

            sr_layout.addStretch()
            layout.addWidget(slot_row)

        # 消耗品详情展示区（初始为提示文字）
        self._con_detail_stack = QStackedWidget()
        self._con_detail_stack.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        prompt = QLabel("点击上方消耗品按钮查看详细数据")
        prompt.setStyleSheet(theme.qss("color:@text_hint@; font-size:11px; padding:20px;"))
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._con_detail_stack.addWidget(prompt)
        layout.addWidget(self._con_detail_stack)
        return container

    def _build_rage_mode_widget(self, section: dict) -> QWidget:
        """构建战斗指令面板：按钮+图片，详细数据精简显示"""
        from ui.ship_card_widget import card_style
        from PySide6.QtWidgets import QGroupBox

        container = QGroupBox("  战斗指令")
        container.setStyleSheet(card_style())
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(container)
        # 增加整体内边距，使其与其他模块卡片保持一致的呼吸感
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        raw = section.get("raw_rage_mode", {})
        rname = raw.get("rage_mode_name", "")
        dname = raw.get("display_name", "战斗指令")

        # 战斗指令预览图（WG：ragemode/{rname}_preview.png；Lesta：ragemode/rageMode_{rname}_preview_0.png）
        preview_path = pic_path(self._rage_preview_icon(rname))

        btn = QPushButton("")
        btn.setFixedSize(32, 32)
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setToolTip(dname)
        btn.setObjectName(f"rage_{rname}")
        BTN_STYLE = theme.qss("""
            QPushButton {
                background: @panel_alt@;
                border: 1px solid @border@;
                border-radius: 6px; padding: 2px;
                min-width: 32px; min-height: 32px;
                max-width: 32px; max-height: 32px;
            }
            QPushButton:hover {
                background: @hover_bg@;
                border-color: @selected_bg@;
            }
            QPushButton:checked {
                background: @selected_bg@; border-color: @selected_bg@;
            }
        """)
        btn.setStyleSheet(BTN_STYLE)

        pixmap = QPixmap(preview_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(QSize(28, 28))
        else:
            btn.setText("缺少图片")
            btn.setStyleSheet(BTN_STYLE)

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
                hlbl.setStyleSheet(theme.qss("font-size:11px; font-weight:bold; color:@text_muted@; background:transparent; padding-top: 4px;"))
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
            name_lbl.setWordWrap(True)
            name_lbl.setStyleSheet(theme.qss("font-size:11px; color:@text_hint@; background:transparent;"))
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name_lbl.setMaximumWidth(140)
            rl.addWidget(name_lbl)

            display_value = f"{value} {unit}" if unit and value else (value or unit or "")
            # 优先使用 item 携带的统一加成颜色（与消耗品一致），否则回退到 +/- 启发式
            fg = theme["text"]
            if item.get("color", ""):
                fg = item["color"]
            elif "%" in display_value:
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

    @staticmethod
    def _current_server() -> str:
        """当前服务器标识（Lesta / Wargaming），从 app_ctx 读取。"""
        try:
            from app.application import app as _app_ctx
            return getattr(_app_ctx.ctx, "wows_type", "") or "Lesta"
        except Exception:
            return "Lesta"

    @classmethod
    def for_server(cls, wows_type: str):
        """按服务器返回对应面板子类（方案 C）。"""
        if (wows_type or "").lower() == "wargaming":
            from ui.wargaming.detail_panel import WargamingDetailPanel
            return WargamingDetailPanel
        from ui.lesta.detail_panel import LestaDetailPanel
        return LestaDetailPanel

    def is_wg(self) -> bool:
        """当前面板是否为 WG 服（实例级判断）。"""
        return self.wows_type == "Wargaming"

    def _module_icon_name(self, img_file: str) -> str:
        """模块图片文件名（Lesta 默认 module_X.png；WG 覆盖为 icon_module_X.png）。"""
        return img_file

    def _consumable_icon_name(self, cid: str) -> str:
        """消耗品图片文件名（Lesta 默认 consumable_X_0.png；WG 覆盖为 consumable_X.png）。"""
        return f"consumable_{cid}_0.png"

    def _rage_preview_icon(self, rname: str) -> str:
        """战斗指令预览图路径（Lesta 默认；WG 覆盖）。"""
        return f"ragemode/rageMode_{rname}_preview_0.png"

    def _wg_ammo_icon_candidates(self, atype_lower: str, species_lower: str,
                                 ammo_info: dict | None = None, is_sec: bool = False) -> list[str]:
        """WG 弹药图标候选（由 WargamingDetailPanel 覆盖）。"""
        return []

    def _ammo_icon_candidates(self, atype_lower: str, species_lower: str,
                              ammo_info: dict | None = None, is_sec: bool = False) -> list[str]:
        """生成弹药图标候选文件名（按服务器区分命名）。

        Lesta：resources/pictures/lesta/ammo_types/（ammo_ap_0.png …）
        WG   ：resources/pictures/wargaming/ammo_types/（ap.png；可切换副弹药 ap_sec.png …）
        """
        if self.is_wg():
            return self._wg_ammo_icon_candidates(atype_lower, species_lower, ammo_info, is_sec)

        at = (atype_lower or "").lower()
        sp = (species_lower or "").lower()
        info = ammo_info or {}
        cand: list[str] = []

        # ── Lesta 命名（保持各渲染路径原逻辑） ──
        _proj_to_air = {"rocket": "projectile", "bomb": "bomb", "skipbomb": "skip_bomb", "mine": "mine"}
        _ap = next((v for k, v in _proj_to_air.items() if sp.startswith(k)), None)
        if is_sec and at:
            cand.append(f"ammo_{at}_sec_0.png")
        # 飞机类：映射前缀
        if _ap:
            if at and _ap != "mine":
                cand.append(f"ammo_{_ap}_{at}_0.png")
            cand.append(f"ammo_{_ap}_0.png")
        # 常规武器：species 直拼
        if sp and not _ap:
            cand.append(f"ammo_{sp}_{at}_0.png" if at else f"ammo_{sp}_0.png")
        if at:
            cand.append(f"ammo_{at}_0.png")
        if sp in ("torpedo", "torpedobomber"):
            if "deepwater" in str(info.get("raw_ammo_type", "")).lower():
                if sp == "torpedobomber":
                    cand.insert(0, "ammo_torpedo_deepwater_0.png")
                    cand.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                else:
                    cand.insert(0, "ammo_bomber_torpedo_deepwater_0.png")
                    cand.insert(0, "ammo_torpedo_deepwater_0.png")
            else:
                tp = info.get("torpedo_postfix", "")
                is_guided = info.get("is_guided", False)
                if tp == "_subBurn":
                    cand.insert(0, "ammo_torpedo_subburn_0.png")
                elif tp and is_guided:
                    cand.insert(0, "ammo_torpedo_subdefault_improve_0.png")
            cand.extend(["ammo_torpedo_0.png", "ammo_bomber_torpedo_0.png"])
        if "depthcharge" in sp:
            cand.extend(["ammo_depthcharge_0.png", "ammo_airsupport_depthcharge_0.png"])
        return cand

    def _build_weapon_widget(self, section: dict) -> QWidget:
        """构建武器面板（主炮/副炮）：每座炮独立显示 + 下方弹药按钮 + 点击切换详情"""
        from ui.ship_card_widget import ShipCardWidget, card_style
        from PySide6.QtWidgets import QGroupBox, QStackedWidget

        label = section.get("label", "武器")
        all_items = section.get("items", [])
        raw_ammo = section.get("raw_ammo_types", [])
        section_tooltip = section.get("tooltip_items", [])

        # 按火炮/深弹/鱼雷名称或 header 拆分 items，每座炮/发射器一组
        mount_groups: list[list[dict]] = []
        cur: list[dict] = []
        for item in all_items:
            is_splitter = (item.get("row_type") == "header" or
                           (item.get("name") in ("炮塔", "深弹发射器", "鱼雷发射管") and cur))
            if is_splitter:
                if cur:
                    mount_groups.append(cur)
                cur = [item]
            else:
                cur.append(item)
        if cur:
            mount_groups.append(cur)

        container = QGroupBox(f"  {label}")
        container.setStyleSheet(card_style())
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(6)


        BTN_STYLE = theme.qss("""
            QPushButton {
                background: @panel_alt@;
                border: 1px solid @border@;
                border-radius: 6px; padding: 2px;
                min-width: 36px; min-height: 36px;
                max-width: 36px; max-height: 36px;
            }
            QPushButton:hover {
                background: @hover_bg@;
                border-color: @selected_bg@;
            }
            QPushButton:checked {
                background: @selected_bg@; border-color: @selected_bg@;
            }
        """)

        ammo_idx = 0
        for grp_idx, grp_items in enumerate(mount_groups):
            TOOLTIP_NAMES = {
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
                # 1.2 过滤"弹药"行（已由下方弹药按钮展示）
                if name == "弹药":
                    continue
                # 1.3 过滤分隔线 (separator) 以及不带名称和内容的空占位行
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
                    is_sec = ammo_info.get("switchable")  # 可切换副弹药（switchable_ammo）

                    candidates = self._ammo_icon_candidates(atype_lower, species_lower, ammo_info, is_sec)

                    btn = QPushButton("")
                    btn.setFixedSize(36, 36)
                    btn.setCheckable(True)
                    # 可切换副弹药：无特殊边框，仅使用特殊图标（_ammo_icon_candidates 生成 {at}_sec.png）
                    btn.setStyleSheet(BTN_STYLE)
                    btn.setToolTip(aname)

                    img_path = next((p for c in candidates if not (p:=QPixmap(pic_path(f"ammo_types/{c}"))).isNull()), None)
                    if img_path:
                        btn.setIcon(QIcon(img_path.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                        btn.setIconSize(QSize(28, 28))
                    else:
                        btn.setText(aname[:2] if aname else "?")
                        btn.setStyleSheet(BTN_STYLE + f"QPushButton {{ font-size: 8px; color: {theme['text_muted']}; }}")

                    _trend = ammo_info.get("dmg_dist_trend")
                    if _trend in ("increase", "decrease"):
                        # 距离伤害趋势：标记覆盖整个按钮（图片自带透明区域）
                        _bp = QPixmap(pic_path(f"ammo_types/unique_features/indicators/torpedo_damage_by_dist_{_trend}.png"))
                        if not _bp.isNull():
                            _badge = QLabel(btn)
                            _badge.setScaledContents(True)
                            _badge.setPixmap(_bp)
                            _badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                            _badge.setStyleSheet("background: transparent;")
                            _badge.setGeometry(0, 0, 36, 36)  # 强制拉伸填满整按钮，与弹药图完全覆盖
                    bl.addWidget(btn)

                    if detail_items:
                        detail_card = ShipCardWidget({"label": aname, "items": detail_items})
                    else:
                        detail_card = QLabel("无详细数据")
                        detail_card.setStyleSheet(theme.qss("color: @text_hint@; font-size: 11px; padding: 8px;"))
                        detail_card.setAlignment(Qt.AlignmentFlag.AlignCenter)

                    ammo_stack.addWidget(detail_card)

                    ci = ammo_stack.count() - 1
                    btn.clicked.connect(
                        lambda checked=False, i=ci, s=ammo_stack, b=btn, l=bl: self._on_ammo_btn_click(i, s, l, b)
                    )

                bl.addStretch()
                layout.addWidget(btn_row)
                layout.addWidget(ammo_stack)

        # 射界入口：追加到整个武器面板最下方（所有炮卡片与弹药区域之后），
        # 值按钮显示齐射角，点击打开射界弹窗
        fa = section.get("_firing_arc")
        if fa and fa.get("mode") == "front_back":
            wep_name = "鱼雷发射器" if fa.get("slot_type") == "torpedoes" else "炮塔"
            value_text = f"{fa.get('front', 0)}°（前）/{fa.get('back', 0)}°（后）"
            arc_row = QWidget()
            hb = QHBoxLayout(arc_row)
            hb.setContentsMargins(10, 2, 10, 2)
            hb.setSpacing(10)
            lbl = QLabel(f"{wep_name} 射界")
            lbl.setStyleSheet(theme.qss("color: @text@; font-size: 12px;"))
            btn = QPushButton(value_text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("点击查看该武器系统的射界图（总览 + 单炮塔详情）")
            btn.setStyleSheet(theme.qss("""
                QPushButton {
                    background: @panel_alt@; color: @text@;
                    border: 1px solid @border@; border-radius: 4px;
                    padding: 4px 10px; font-size: 12px; text-align: center;
                }
                QPushButton:hover { background: @hover_bg@; border-color: @selected_bg@; }
            """))
            btn.clicked.connect(lambda _=False, f=fa: self._open_firing_arc(f))
            hb.addWidget(lbl)
            hb.addStretch(1)
            hb.addWidget(btn)
            layout.addWidget(arc_row)

        return container

    def _build_aa_widget(self, section: dict) -> QWidget:
        """构建防空面板：每个防空区域拆分为独立卡片，命中率/射程移至 tooltip"""
        from ui.ship_card_widget import ShipCardWidget, card_style
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
        container.setStyleSheet(card_style())
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
            _cur_ship_type = _cb.get("shiptype_en", "") if isinstance(_cb, dict) else ""
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
                        if k in _ADDITIVE_KEYS_BASE:
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
            _sonar_key = getattr(self, '_active_sonar_key', '')
            _mod_keys = getattr(self, '_active_module_keys', {})
            data = presenter.build(self._current_filename, version_code=vc, modifiers=modifiers,
                                   engine_letter=_eng_key, fire_control_key=_fc_key, sonar_key=_sonar_key,
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
            for _pos, _m in getattr(self, '_selected_skill_mods', {}).items():
                for k, v in (_m.items() if isinstance(_m, dict) else []):
                    if k not in _combined:
                        # 首次出现：直接采用技能值（避免 0×v=0 清掉乘性加成）
                        _combined[k] = v
                    else:
                        try:
                            ev = _combined[k]
                            nv = v
                            # dict 型修饰符（按舰种区分值）：按当前舰种提取标量
                            _cur_st = ""
                            if hasattr(self, '_current_analyzed') and self._current_analyzed:
                                _cb = self._current_analyzed.get("config_bar", {})
                                _cur_st = _cb.get("shiptype_en", "") if isinstance(_cb, dict) else ""
                            if isinstance(ev, dict):
                                ev = ev.get(_cur_st) or next((x for x in ev.values() if isinstance(x, (int, float))), 1.0)
                            if isinstance(nv, dict):
                                nv = nv.get(_cur_st) or next((x for x in nv.values() if isinstance(x, (int, float))), 1.0)
                            ev_f, nv_f = float(ev), float(nv)
                            _add = k in _ADDITIVE_KEYS_BASE
                            _combined[k] = ev_f + nv_f if _add else ev_f * nv_f
                        except (ValueError, TypeError):
                            _combined[k] = v
            _eng_key = getattr(self, '_active_engine_key', '')
            _fc_key = getattr(self, '_active_fire_control_key', '')
            _sonar_key = getattr(self, '_active_sonar_key', '')
            _mod_keys = getattr(self, '_active_module_keys', {})
            data = presenter.build(self._current_filename, version_code=vc, modifiers=_combined or None,
                                   engine_letter=_eng_key, fire_control_key=_fc_key, sonar_key=_sonar_key,
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

    # ── 完整信息复制（覆盖信息面板所有内容）───────────────────

    def _copy_ship_info_to_clipboard(self) -> None:
        """复制舰船数据（不含技能面板等界面内容）到剪贴板。

        基于 presenter 输出的 sections + 子面板数据（数据驱动），
        只包含舰船性能数据与弹药，天然排除技能面板/升级品/信号旗等界面内容。
        """
        if not self._current_filename:
            bus.log_message.emit("ℹ️ 当前未选中实体，无法复制")
            return
        try:
            from PySide6.QtWidgets import QApplication
            if self._is_ship_mode and self._ship_sections:
                text = self._render_sections_to_text(self._ship_sections)
                sub = self._render_sub_sections_to_text(self._ship_sub_sections)
                if sub:
                    text = (text + "\n\n" + sub).rstrip()
            else:
                text = self._render_default_pages_to_text("display")
            if not text.strip():
                bus.log_message.emit("⚠️ 当前无内容可复制")
                return
            QApplication.clipboard().setText(text)
            _show_name = (self._current_analyzed or {}).get("title") or self._current_filename
            bus.log_message.emit(f"📋 已复制「{_show_name}」舰船数据到剪贴板")
        except Exception as e:
            import traceback
            bus.log_message.emit(f"⚠️ 复制失败: {e}\n{traceback.format_exc()}")

    def _render_sub_sections_to_text(self, sub_sections: dict) -> str:
        """渲染子面板（舰载机等）数据为文本（数据驱动）。"""
        lines: list[str] = []
        for label, sub_info in sub_sections.items():
            if not isinstance(sub_info, dict):
                continue
            labels = sub_info.get("sub_labels") or []
            contents = sub_info.get("sub_contents") or {}
            if not labels:
                continue
            lines.append(f"【{label}】")
            for sl in labels:
                content = contents.get(sl) or {}
                if not isinstance(content, dict):
                    continue
                lines.append(f"· {sl}")
                lines.extend(self._render_items_to_text(content.get("items") or [], indent=2))
                lines.extend(self._render_ammo_to_text(content.get("raw_ammo_types") or [], indent=2))
                # 舰载机等嵌套 config_contents
                config_contents = content.get("config_contents") or {}
                if config_contents:
                    for _ck, cv in config_contents.items():
                        if not isinstance(cv, dict):
                            continue
                        lines.extend(self._render_items_to_text(cv.get("items") or [], indent=4))
                        lines.extend(self._render_ammo_to_text(cv.get("raw_ammo_types") or [], indent=4))
                        lines.extend(self._render_consumables_to_text(cv.get("raw_consumables") or [], indent=4))
                lines.append("")
            lines.append("")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _render_items_to_text(items: list[dict], indent: int = 0) -> list[str]:
        """把 section/子面板的 items 渲染为键值文本行。"""
        lines: list[str] = []
        pad = " " * indent
        for item in items:
            rt = item.get("row_type", "kv")
            name = item.get("name", "")
            if rt == "header":
                lines.append(f"{pad}【{name}】")
            elif rt == "sub_header":
                lines.append(f"{pad}· {name}")
            elif rt == "separator":
                lines.append("")
            elif rt == "button_group":
                raw = item.get("raw_value", {})
                cur = raw.get("current", "") if isinstance(raw, dict) else ""
                if name:
                    lines.append(f"{pad}{name}: {cur}".rstrip(": ") if cur else f"{pad}{name}")
                elif cur:
                    lines.append(f"{pad}{cur}")
            else:  # kv
                value = item.get("value", "")
                unit = item.get("unit", "")
                disp = f"{value} {unit}".strip() if unit and value else (value or unit or "")
                details = item.get("details", []) or []
                if details:
                    lines.append(f"{pad}{name}: {disp}" if name else f"{pad}{disp}")
                    for d in details:
                        dn = d.get("name", "")
                        dv = d.get("value", "")
                        du = d.get("unit", "")
                        dd = f"{dv} {du}".strip() if du and dv else (dv or du or "")
                        if dn:
                            lines.append(f"{pad}    {dn}: {dd}")
                        elif dd:
                            lines.append(f"{pad}    {dd}")
                else:
                    lines.append(f"{pad}{name}: {disp}".rstrip(": ") if name else f"{pad}{disp}")
        return lines

    @staticmethod
    def _render_ammo_to_text(raw_ammo: list[dict], indent: int = 0) -> list[str]:
        """把 raw_ammo_types 渲染为文本（弹药名 + 明细）。"""
        lines: list[str] = []
        pad = " " * indent
        if not raw_ammo:
            return lines
        lines.append(f"{pad}【弹药】")
        for ai in raw_ammo:
            an = ai.get("name", "")
            if an:
                lines.append(f"{pad}  ● {an}")
            for d in (ai.get("detail_items") or []):
                dn = d.get("name", "")
                dv = d.get("value", "")
                du = d.get("unit", "")
                dd = f"{dv} {du}".strip() if du and dv else (dv or du or "")
                if dn:
                    lines.append(f"{pad}      {dn}: {dd}")
                elif dd:
                    lines.append(f"{pad}      {dd}")
        return lines

    @staticmethod
    def _render_consumables_to_text(raw_consumables: list[dict], indent: int = 0) -> list[str]:
        """把 raw_consumables 渲染为文本（消耗品名 + 明细）。"""
        lines: list[str] = []
        pad = " " * indent
        if not raw_consumables:
            return lines
        lines.append(f"{pad}【消耗品】")
        for rc in raw_consumables:
            an = rc.get("display_name") or rc.get("name", "")
            if an:
                lines.append(f"{pad}  ● {an}")
            for d in (rc.get("detail_items") or []):
                dn = d.get("name", "")
                dv = d.get("value", "")
                du = d.get("unit", "")
                dd = f"{dv} {du}".strip() if du and dv else (dv or du or "")
                if dn:
                    lines.append(f"{pad}      {dn}: {dd}")
                elif dd:
                    lines.append(f"{pad}      {dd}")
        return lines

    # ── 面板截图复制（展开折叠后整页截图）────────────────────

    def _copy_panel_screenshot(self) -> None:
        """展开信息面板所有折叠内容并整页截图复制到剪贴板。"""
        if not self._current_filename:
            bus.log_message.emit("ℹ️ 当前未选中实体，无法截图复制")
            return
        try:
            self._expand_all_collapsible()
            from PySide6.QtCore import QTimer
            # 展开按钮后布局会变化，等下一轮事件循环再渲染（绑定 receiver=self）
            QTimer.singleShot(0, self, self._do_panel_screenshot)
        except Exception as e:
            bus.log_message.emit(f"⚠️ 截图准备失败: {e}")

    def _do_panel_screenshot(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
            pm = self._render_current_page_complete()
            if pm is None or pm.isNull():
                bus.log_message.emit("⚠️ 截图失败: 无法渲染当前面板")
                return
            QApplication.clipboard().setPixmap(pm)
            _show_name = (self._current_analyzed or {}).get("title") or self._current_filename
            bus.log_message.emit(
                f"📸 已复制「{_show_name}」面板截图到剪贴板 ({pm.width()}×{pm.height()}px)")
        except Exception as e:
            import traceback
            bus.log_message.emit(f"⚠️ 截图失败: {e}\n{traceback.format_exc()}")

    def _expand_all_collapsible(self) -> None:
        """点击信息面板内所有折叠/切换按钮展开详情。

        跳过会弹模态框的"自定义"按钮与已展开（checkable 且 checked）的按钮，
        避免收折已展开内容或卡住界面。
        """
        from PySide6.QtWidgets import QPushButton, QToolButton
        page = self.stack.currentWidget()
        if page is None:
            return
        for btn in page.findChildren(QPushButton) + page.findChildren(QToolButton):
            try:
                if not btn.isEnabled() or not btn.isVisible():
                    continue
                text = (btn.text() or "").strip()
                if "自定义" in text or "复制" in text:
                    continue
                if btn.isCheckable() and btn.isChecked():
                    continue
                btn.click()
            except RuntimeError:
                continue  # 底层 C++ 对象已被重建删除
            except Exception:
                continue

    def _render_current_page_complete(self):
        """渲染当前信息面板为完整长图（含滚动区全部内容，不裁剪）。"""
        from PySide6.QtCore import QRectF, QSizeF, Qt
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QScrollArea, QTextEdit
        page = self.stack.currentWidget()
        if page is None:
            return None

        # 舰船模式：由多个滚动区（顶部配置栏 + 下方卡片流）组成 → 内容拼接
        scrollers = page.findChildren(QScrollArea)
        if scrollers:
            pms = []
            width = 0
            for sa in scrollers:
                cw = sa.widget()
                if cw is None:
                    continue
                p = cw.grab()
                if not p.isNull():
                    pms.append(p)
                    width = max(width, p.width())
            if pms:
                gap = 8
                total_h = sum(p.height() for p in pms) + gap * (len(pms) - 1)
                canvas = QPixmap(width, total_h)
                canvas.fill(Qt.GlobalColor.white)
                pt = QPainter(canvas)
                y = 0
                for p in pms:
                    pt.drawPixmap(0, y, p)
                    y += p.height() + gap
                pt.end()
                return canvas
            return page.grab()

        # 通用模式：QTextEdit 整篇文档渲染为长图（含超出视口部分）
        if isinstance(page, QTextEdit):
            te = page
            viewport = te.viewport()
            doc = te.document()
            old_page_size = doc.pageSize()
            try:
                doc.setPageSize(QSizeF(viewport.width(), -1))
                h = int(doc.size().height())
                w = viewport.width()
                pm = QPixmap(max(w, 1), max(h, 1))
                pm.fill(Qt.GlobalColor.white)
                pt = QPainter(pm)
                doc.drawContents(pt, QRectF(0, 0, w, h))
                pt.end()
                return pm
            finally:
                doc.setPageSize(old_page_size)

        return page.grab()

    def _render_default_pages_to_text(self, scope: str) -> str:
        """渲染通用模式页面（详情/数据）为纯文本（不含原始 JSON）。"""
        if scope == "all":
            labels = ["【详情】", "【数据】"]
            parts = []
            for i in range(min(2, len(self._default_pages))):
                t = self._default_pages[i].toPlainText().strip()
                if not t or t.startswith("📋 使用说明") or "暂无" in t[:20]:
                    continue
                parts.append(f"{labels[i]}\n{t}")
            return "\n\n".join(parts)
        idx = self.stack.currentIndex()
        if 0 <= idx < len(self._default_pages):
            t = self._default_pages[idx].toPlainText()
            if t.startswith("📋 使用说明"):
                return ""
            return t
        return ""

    @classmethod
    def _render_sections_to_text(cls, sections: list[dict]) -> str:
        """将 ship_presenter 输出的 sections 结构渲染为纯文本（键值面板格式）。"""
        lines: list[str] = []
        for sec in sections:
            label = sec.get("label", "")
            icon = sec.get("icon", "")
            title = f"{icon} {label}".strip() if icon else label
            if title:
                lines.append(title)
                lines.append("─" * max(4, len(title) * 2))
            lines.extend(cls._render_items_to_text(sec.get("items", [])))
            lines.extend(cls._render_ammo_to_text(sec.get("raw_ammo_types") or []))
            lines.append("")
        return "\n".join(lines).rstrip()

    def _consumable_detail_items(self, items: list, bp, cfgd: dict, conn, vc: str, kv,
                                  *, num_raw, prep, cd_time, wt, auto, ct) -> None:
        """渲染消耗品详情条目（由服务器子类各自实现，本基类不保留分支内容）。

        公共调用入口在 _on_consumable_btn_click；Lesta 版实现位于
        ui/lesta/detail_panel.py，WG 版实现位于 ui/wargaming/detail_panel.py。
        """
        raise NotImplementedError("_consumable_detail_items 由服务器子类实现")

    def _on_consumable_btn_click(self, cid: str, dname: str, ckey: str, parent_container: QWidget,
                                  extra_count: int = 0, btn=None, all_btns=None,
                                  stack: QStackedWidget | None = None) -> None:
        """消耗品按钮点击：查询数据库并展示详情卡片（舰船/飞机消耗品共用）。

        stack：目标详情堆栈。舰船消耗品默认 self._con_detail_stack；飞机消耗品传入
        各自 con_stack，使飞机消耗品卡片同样走完整类型分支树（WG/Lesta 特有类型、
        时间制等），而非 presenter 的简化 detail_items。
        """
        from ui.ship_card_widget import ShipCardWidget
        from services.database_service import get_db

        # 再次点击当前选中按钮 → 取消选中并收起详情（回到提示页）
        _stack = stack if stack is not None else getattr(self, '_con_detail_stack', None)
        if _stack is None:
            return
        _act = getattr(self, '_active_con_keys', {})
        _sid = id(_stack)
        _key = f"{cid}::{ckey}"
        if _act.get(_sid) == _key and _stack.currentIndex() != 0:
            _act[_sid] = ""
            _stack.setCurrentIndex(0)
            if all_btns:
                for b in all_btns:
                    b.setChecked(False)
            if getattr(self, '_active_con_btn', None) is btn:
                self._active_con_btn = None
            return

        # 跨槽位/跨消耗品区唯一高亮：先取消上一个选中按钮
        _prev_btn = getattr(self, '_active_con_btn', None)
        if _prev_btn is not None and _prev_btn is not btn:
            from shiboken6 import isValid
            if isValid(_prev_btn):
                _prev_btn.setChecked(False)
            else:
                # 旧按钮所属面板已被重建销毁，丢弃失效引用
                self._active_con_btn = None
        # 同槽位互斥高亮（与飞机消耗品/弹药按钮一致）
        if all_btns:
            for b in all_btns:
                b.setChecked(b is btn)
        self._active_con_btn = btn
        _act[_sid] = _key

        # 移除旧详情页（保留索引 0 的提示页）
        while _stack.count() > 1:
            w = _stack.widget(1)
            _stack.removeWidget(w)
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
                # WG：效果数据在 logic 子对象，合并到顶层供各类型分支读取
                _logic = cfgd.get('logic')
                if isinstance(_logic, dict):
                    cfgd.update(_logic)

                from presenters.base_presenter import BasePresenter
                bp = BasePresenter(conn)

                def kv(name, value, unit="", color=""):
                    items.append(bp.make_item(name, value, len(items), unit=unit, color=color))

                kv("名称", dname)
                num_raw = cfgd.get('numConsumables') or cfgd.get('num_consumables') or "0"
                if extra_count and num_raw not in ('0', 0, '-1'):
                    try:
                        num_raw = str(int(num_raw) + extra_count)
                    except (ValueError, TypeError):
                        pass
                prep = float(cfgd.get('preparationTime', 0) or 0)
                cd_time = float(cfgd.get('reloadTime', 0) or 0)
                wt = float(cfgd.get('workTime', 0) or 0)
                # 应用已选升级品的修饰符（冷却/持续时间）
                if hasattr(self, '_selected_mods') and self._selected_mods:
                    from presenters.ship_presenter import ShipPresenter as _SP_MOD
                    from models.name_mapping import Mapping as _NMAP_FMT
                    _reload_label = _SP_MOD.MODIFIER_MAP.get("ConsumableReloadTime")
                    _duration_label = _SP_MOD.MODIFIER_MAP.get("ConsumablesWorkTime")
                    for _m in self._selected_mods.values():
                        for _mk, _mv in _m.get("modifiers", {}).items():
                            if isinstance(_mv, dict):
                                _mv_f = float(next((x for x in _mv.values() if isinstance(x, (int, float))), 0))
                            else:
                                _mv_f = float(_mv)
                            _fmt = _NMAP_FMT.MODIFIER_FORMAT_MAP.get(_mk, "coeff")
                            _field = _SP_MOD.MODIFIER_MAP.get(_mk)
                            if _field == _reload_label and cd_time:
                                cd_time = cd_time * _mv_f if _fmt == "coeff" else cd_time + _mv_f
                            elif _field == _duration_label and wt:
                                wt = wt * _mv_f if _fmt == "coeff" else wt + _mv_f
                ct = cfgd.get('consumableType') or cfgd.get('consumable_type') or ""
                is_auto = cfgd.get('isAutoConsumable', False)
                self._consumable_detail_items(
                    items, bp, cfgd, conn, vc, kv,
                    num_raw=num_raw, prep=prep, cd_time=cd_time, wt=wt, auto=is_auto, ct=ct)
            else:
                items = [{"row_type": "header", "label": "  无详细数据", "value": ""}]
        except Exception as e:
            items = [{"row_type": "header", "label": f"  查询出错: {e}", "value": ""}]

        # 构建详情卡片并添加到 stack
        detail_card = ShipCardWidget({"items": items, "label": f"消耗品详情 - {dname}"})
        _stack.addWidget(detail_card)
        _stack.setCurrentWidget(detail_card)

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
        scroll.setStyleSheet(theme.qss("QScrollArea{border:none;background:@window_bg@;}"))
        bar = QWidget()
        bar.setStyleSheet(theme.qss("QWidget{background:@window_bg@;border-bottom:1px solid @border@;}"))
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
            te.setStyleSheet(theme.qss("""
                QTextEdit {
                    background-color: @panel_alt@;
                    color: @text@;
                    border: none;
                    padding: 8px 12px;
                    font-family: "Consolas", "Courier New", monospace;
                    font-size: 11px;
                }
            """))
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
            btn.setStyleSheet(theme.qss("QPushButton{background:@panel_alt@;color:@text@;border:1px solid @border@;"
                              "border-radius:4px;padding:4px 10px;font-size:11px;}"
                              "QPushButton:hover{background:@hover_bg@;color:@text@;}"
                              "QPushButton:checked{background:@selected_bg@;color:@selected_fg@;}"))
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
        # 先清空默认页引用，避免 deleteLater 后残留失效对象被主题切换等路径访问
        self._default_pages = []
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
        self._active_sonar_key = ""
        self._active_hull_key = ""
        self._active_module_keys: dict[str, str] = {}
        # 切换文件：旧面板/按钮将被销毁，清空消耗品选中态避免残留引用（C++ 对象已删除崩溃）
        self._active_con_keys = {}
        self._active_con_btn = None
        # 信号旗选中态：构建信号旗面板时会按此恢复上一艘船的选中（Lesta），必须随船清空
        self._selected_signal_flags = {}
        # WG 信号旗选中态：随船重置（构建列时按新船全选填充）
        self._selected_wg_signal_flags = {}

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
            # 默认配置字母取 presenter 输出的 stock 配置（首次打开/切换船时）
            _cb = (self._current_analyzed or {}).get("config_bar", {})
            if isinstance(_cb, dict):
                _stock = _cb.get("_stock_config_letter", "")
                if _stock:
                    self._active_config_letter = _stock
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
        for te in list(self._default_pages):
            try:
                from shiboken6 import isValid
                if not isValid(te):
                    continue
                te.setPlainText(hint)
            except Exception:  # noqa: BLE001
                pass

