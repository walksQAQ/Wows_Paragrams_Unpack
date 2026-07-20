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
    QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QColor

from app.signals import bus
from services.database_service import get_db
from presenters.registry import PresenterRegistry, CATEGORY_TO_ETYPE
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
            bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            bar_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
            bar_widget = self._build_top_config_bar(config_bar)
            bar_scroll.setWidget(bar_widget)
            outer_layout.addWidget(bar_scroll)

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
        self._ship_columns_layout.setContentsMargins(0, 0, 0, 0)
        self._ship_columns_layout.setSpacing(8)
        self._ship_columns_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        main_layout.addWidget(columns_wrapper, stretch=1)

        bottom_scroll.setWidget(container)
        outer_layout.addWidget(bottom_scroll, stretch=1)

        self._ship_sections = sections
        self._ship_sub_sections = sub_sections
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

    def _build_top_config_bar(self, config: dict) -> QWidget:
        """构建顶部配置栏：仿浩舰 4 列布局（配件/升级品/舰长/外观）"""
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
                background: #f8f8f8; border: 1px solid #ddd;
                border-radius: 4px; padding: 3px 10px;
                font-size: 11px; color: #444; text-align: left;
            }
            QPushButton:hover { background: #e8e8e8; border-color: #aaa; }
        """
        COL_TITLE = "font-size:11px; font-weight:bold; color:#666; padding:0 0 3px 0;"

        def _col(title: str) -> tuple[QWidget, QVBoxLayout]:
            w = QWidget(); cl = QVBoxLayout(w)
            cl.setContentsMargins(8,0,8,0); cl.setSpacing(2)
            cl.setAlignment(Qt.AlignmentFlag.AlignTop)
            tl = QLabel(title); tl.setStyleSheet(COL_TITLE)
            cl.addWidget(tl)
            return w, cl

        # ── 第1列：配件（基于 ShipUpgradeInfo，含所有升级类型） ──
        col1, l1 = _col("配件")
        upgrades = config.get("upgrades", [])

        UC_ORDER = ["_Artillery", "_Torpedoes", "_Hull", "_Engine",
                    "_Suo", "_Fighter", "_DiveBomber", "_TorpedoBomber", "_FlightControl"]
        UC_ICONS = {"_Artillery": "🔫", "_Torpedoes": "💣", "_Hull": "🚢",
                    "_Engine": "⚙", "_Suo": "📡",
                    "_Fighter": "✈", "_DiveBomber": "💥", "_TorpedoBomber": "⚓",
                    "_FlightControl": "🎯"}
        UC_NAMES = {"_Artillery": "主炮", "_Torpedoes": "鱼雷", "_Hull": "船体",
                    "_Engine": "引擎", "_Suo": "火控",
                    "_Fighter": "战斗机", "_DiveBomber": "轰炸机",
                    "_TorpedoBomber": "鱼雷机", "_FlightControl": "飞控"}
        UC_IMAGE_MAP = {
            "_Artillery": "module_Artillery.png",
            "_Torpedoes": "module_Torpedoes.png",
            "_Hull": "module_Hull.png",
            "_Engine": "module_Engine.png",
            "_Suo": "module_Suo.png",
            "_Fighter": "module_Fighter.png",
            "_DiveBomber": "module_DiveBomber.png",
            "_TorpedoBomber": "module_TorpedoBomber.png",
        }
        MODULES_IMAGE_DIR = Path(__file__).resolve().parent.parent / "resources" / "pictures" / "modules"
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
                background: rgba(240, 244, 250, 0.9);
                border: 1px solid rgba(200, 216, 232, 0.5);
                border-radius: 6px; padding: 2px;
                font-size: 9px; color: #333;
                min-width: 40px; min-height: 40px;
                max-width: 40px; max-height: 40px;
            }
            QPushButton:hover {
                background: rgba(228, 236, 245, 0.95);
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
            title.setStyleSheet("font-size:10px; color:#666;")
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
                if img_file and (MODULES_IMAGE_DIR / img_file).exists():
                    img_path = MODULES_IMAGE_DIR / img_file
                    pixmap = QPixmap(str(img_path))
                    scaled = pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    btn.setIcon(QIcon(scaled))
                    btn.setIconSize(QSize(24, 24))
                else:
                    btn.setText("缺少图片")
                    btn.setStyleSheet(BTN_STYLE.replace("font-size: 9px;", "font-size: 8px;").replace("color: #333;", "color: #999;"))

                if ut == "_Hull":
                    affected = hull_affects.get(letter, [un])
                else:
                    affected = [un]

                btn.clicked.connect(
                    partial(self._on_topbar_module_click, affected, letter)
                )
                bl.addWidget(btn)
                if i == 0:
                    btn.setChecked(True)

            gl.addWidget(btn_row)
            return group

        # 所有配件模块整合到一行，居中对齐
        ALL_UC = ["_Artillery", "_Torpedoes", "_Hull", "_Engine", "_Suo",
                   "_Fighter", "_DiveBomber", "_TorpedoBomber"]

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
        layout.addWidget(col1)

        # 分隔线
        sep_count = 0
        for section_key in ["upgrade", "signal", "commander"]:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setStyleSheet("QFrame{color:#c8c8c8;}")
            sep.setFixedWidth(1)
            layout.addWidget(sep)

            if section_key == "upgrade":  # 第2列：升级品
                col, cl = _col("升级品")
                upgrade_row = QWidget()
                ul = QHBoxLayout(upgrade_row)
                ul.setContentsMargins(0,0,0,0); ul.setSpacing(4)
                ul.setAlignment(Qt.AlignmentFlag.AlignLeft)
                for i in range(6):
                    btn = QPushButton(f"  ⬜")
                    btn.setStyleSheet(ITEM_STYLE)
                    btn.setFixedSize(36, 36)
                    btn.setEnabled(False)
                    btn.setToolTip(f"升级品槽位 {i+1}")
                    ul.addWidget(btn)
                ul.addStretch()
                cl.addWidget(upgrade_row)
                cl.addStretch()
                layout.addWidget(col)

            elif section_key == "signal":  # 第3列：信号旗
                col, cl = _col("信号旗")
                signal_row = QWidget()
                sl = QHBoxLayout(signal_row)
                sl.setContentsMargins(0,0,0,0); sl.setSpacing(4)
                sl.setAlignment(Qt.AlignmentFlag.AlignLeft)
                for i in range(8):
                    btn = QPushButton(f"  ⬜")
                    btn.setStyleSheet(ITEM_STYLE)
                    btn.setFixedSize(36, 36)
                    btn.setEnabled(False)
                    btn.setToolTip(f"信号旗槽位 {i+1}")
                    sl.addWidget(btn)
                sl.addStretch()
                cl.addWidget(signal_row)
                cl.addStretch()
                layout.addWidget(col)

            elif section_key == "commander":  # 第4列：舰长技能
                col, cl = _col("舰长技能")
                from PySide6.QtWidgets import QComboBox
                cb = QComboBox()
                cb.addItem("普通舰长")
                cb.setStyleSheet("font-size:11px; padding:2px 4px;")
                cl.addWidget(cb)
                pts = QLabel("技能点数: 0 / 21")
                pts.setStyleSheet("font-size:10px; color:#888; padding:2px 0;")
                cl.addWidget(pts)
                grid_label = QLabel("（技能加点暂未实现）")
                grid_label.setStyleSheet("font-size:10px; color:#bbb; padding:8px 0;")
                cl.addWidget(grid_label)
                cl.addStretch()
                layout.addWidget(col)

        return bar

    def _on_topbar_module_click(self, section_labels: list[str], config_letter: str):
        """顶栏模块按钮点击：切换到对应子面板的配置页，支持同时切多个 section"""
        for sl in section_labels:
            ctrl = self._subwidget_controllers.get(sl)
            if ctrl is None:
                continue
            stack, btns = ctrl
            target_name = f"{config_letter} 配置"
            if btns is not None:
                # 有标签按钮的模式：模拟点击
                for i, btn in enumerate(btns):
                    if target_name in btn.text():
                        self._on_sub_btn(stack, i, btns)
                        break
            else:
                # 无标签按钮模式：直接按序号切换 stack
                for i in range(stack.count()):
                    w = stack.widget(i)
                    # 通过 widget 名称判断配置字母
                    wname = w.objectName() or ""
                    if config_letter in wname or target_name in wname:
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
                # 四列布局：船体以下武器放入第4列
                LABEL_TO_COL = {
                    "基础属性": 0, "消耗品数据": 0,
                    "船体": 1,
                    "主炮": 3, "副炮": 3, "次级主炮": 3,
                    "鱼雷": 3, "防空": 3, "深水炸弹": 2,
                    "舰载机": 2, "支援": 2,
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
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(8)
                col_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                self._ship_column_layouts.append(col_layout)
                self._ship_column_widgets.append(col_w)
                self._ship_columns_layout.addWidget(col_w)

            # 设置列宽拉伸：第0列2/3，其余列均分剩余
            for i, w in enumerate(self._ship_column_widgets[:cols]):
                stretch = 2 if i == 0 else (3 if cols == 3 else 2)
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

            # 重建每列的内容
            for col_idx, col_layout in enumerate(self._ship_column_layouts):
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
                    elif sub_info and sub_info.get("sub_labels"):
                        if label == "舰载机":
                            widget = self._build_aircraft_widget(sub_info)
                        else:
                            widget = self._build_sub_widget(label, sub_info)
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
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        labels = sub_info.get("sub_labels", [])
        contents = sub_info.get("sub_contents", {})
        stack = QStackedWidget()
        for i, sl in enumerate(labels):
            content = contents.get(sl, [])
            if isinstance(content, list) and content and isinstance(content[0], dict) and "name" in content[0]:
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
        """构建舰载机面板：各类型飞机依次展开显示"""
        from ui.ship_card_widget import CARD_STYLE
        from PySide6.QtWidgets import QGroupBox

        container = QGroupBox("  舰载机")
        container.setStyleSheet(CARD_STYLE)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        labels = sub_info.get("sub_labels", [])
        contents = sub_info.get("sub_contents", {})

        for sl in labels:
            content = contents.get(sl, {})
            if isinstance(content, dict) and "config_labels" in content:
                # 取第一个配置显示（默认配置）
                config_labels = content.get("config_labels", [])
                config_contents = content.get("config_contents", {})
                first_config = config_contents.get(config_labels[0], []) if config_labels else []
                lines = [f"── {sl} ──"] + first_config
                te = QTextEdit()
                te.setReadOnly(True)
                te.setFont(self._make_font("Consolas", 10))
                te.setStyleSheet("""
                    QTextEdit {
                        background-color: #fafafa;
                        color: #1a1a1a;
                        border: 1px solid #e0e0e0;
                        border-radius: 4px;
                        padding: 6px 10px;
                        font-family: "Consolas", "Courier New", monospace;
                        font-size: 11px;
                    }
                """)
                te.setPlainText(self._strip_indent("\n".join(lines)))
                te.setFixedHeight(max(60, min(400, len(lines) * 18 + 20)))
                layout.addWidget(te)
            elif isinstance(content, list) and content and isinstance(content[0], dict):
                section = {"label": sl, "items": content}
                layout.addWidget(ShipCardWidget(section))
            else:
                te = QTextEdit()
                te.setReadOnly(True)
                te.setFont(self._make_font("Consolas", 10))
                te.setStyleSheet("""
                    QTextEdit {
                        background-color: #fafafa;
                        color: #1a1a1a;
                        border: 1px solid #e0e0e0;
                        border-radius: 4px;
                        padding: 6px 10px;
                        font-family: "Consolas", "Courier New", monospace;
                        font-size: 11px;
                    }
                """)
                te.setPlainText(self._strip_indent("\n".join(content) if isinstance(content, list) else ""))
                layout.addWidget(te)

        layout.addStretch()
        return container

    def _build_consumables_widget(self, section: dict) -> QWidget:
        """构建消耗品数据面板：按槽位纵向排列，每槽位以按钮+图片显示"""
        from ui.ship_card_widget import CARD_STYLE
        from PySide6.QtWidgets import QGroupBox, QStackedWidget

        container = QGroupBox("  消耗品数据")
        container.setStyleSheet(CARD_STYLE)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        raw_slots = section.get("raw_consumables", [])
        # 按 slot_index 分组
        slots_map: dict[int, list[dict]] = defaultdict(list)
        for rs in raw_slots:
            slots_map[rs["slot_index"]].append(rs)

        consumables_dir = Path(__file__).resolve().parent.parent / "resources" / "pictures" / "consumables"

        BTN_STYLE = """
            QPushButton {
                background: rgba(240, 244, 250, 0.9);
                border: 1px solid rgba(200, 216, 232, 0.5);
                border-radius: 6px; padding: 2px;
                min-width: 40px; min-height: 40px;
                max-width: 40px; max-height: 40px;
            }
            QPushButton:hover {
                background: rgba(228, 236, 245, 0.95);
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
            slot_label.setStyleSheet("font-size:10px; color:#888; min-width:24px;")
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
                img_path = consumables_dir / img_file
                if img_path.exists():
                    pixmap = QPixmap(str(img_path))
                    scaled = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    btn.setIcon(QIcon(scaled))
                    btn.setIconSize(QSize(32, 32))
                else:
                    # 无图片时显示首字母
                    btn.setText(cid[:2] if cid else "?")
                    btn.setStyleSheet(BTN_STYLE.replace("padding: 2px;", "padding: 2px; font-size:9px; color:#333;"))

                btn.clicked.connect(partial(self._on_consumable_btn_click, cid, dname, container))
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
        from ui.ship_card_widget import CARD_STYLE, TABLE_STYLE, LABEL_COLOR, VALUE_COLOR
        from PySide6.QtWidgets import QGroupBox, QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView
        from PySide6.QtGui import QFont

        container = QGroupBox("  战斗指令")
        container.setStyleSheet(CARD_STYLE)
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        raw = section.get("raw_rage_mode", {})
        rname = raw.get("rage_mode_name", "")
        dname = raw.get("display_name", "战斗指令")

        ragemode_dir = Path(__file__).resolve().parent.parent / "resources" / "pictures" / "ragemode"
        preview_path = ragemode_dir / f"rageMode_{rname}_preview_0.png"

        btn = QPushButton("")
        btn.setFixedSize(32, 32)
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setToolTip(dname)
        btn.setObjectName(f"rage_{rname}")
        BTN_STYLE = """
            QPushButton {
                background: rgba(240, 244, 250, 0.9);
                border: 1px solid rgba(200, 216, 232, 0.5);
                border-radius: 6px; padding: 2px;
                min-width: 32px; min-height: 32px;
                max-width: 32px; max-height: 32px;
            }
            QPushButton:hover {
                background: rgba(228, 236, 245, 0.95);
                border-color: #1a73e8;
            }
            QPushButton:checked {
                background: #1a73e8; border-color: #1a73e8;
            }
        """
        btn.setStyleSheet(BTN_STYLE)

        # 直接加载 _preview 图片
        if preview_path.exists():
            pixmap = QPixmap(str(preview_path))
            scaled = pixmap.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(QSize(28, 28))
        else:
            btn.setText("缺少图片")
            btn.setStyleSheet(BTN_STYLE.replace("font-size: 9px;", "font-size: 8px;").replace("color: #333;", "color: #999;"))

        btn_row = QWidget()
        bl = QHBoxLayout(btn_row)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(btn)
        layout.addWidget(btn_row)

        # ── 数据表格 ──
        items = section.get("items", [])
        table = QTableWidget()
        table.setStyleSheet(TABLE_STYLE)
        table.setColumnCount(2)
        table.setShowGrid(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setStretchLastSection(True)

        VAL_LABEL_STYLE = """
            QLabel {
                font-size: 11px; color: #1a1a1a;
                padding: 2px 10px 2px 0;
                background: transparent;
            }
        """

        for item in items:
            row = table.rowCount()
            row_type = item.get("row_type", "kv")
            name = item.get("name", "")
            value = item.get("value", "")
            unit = item.get("unit", "")

            if row_type == "header":
                table.insertRow(row)
                cell = QTableWidgetItem(name)
                cell.setForeground(QColor("#555555"))
                bold = QFont()
                bold.setBold(True)
                bold.setPointSize(10)
                cell.setFont(bold)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                table.setItem(row, 0, cell)
                table.setItem(row, 1, QTableWidgetItem(""))
            elif row_type == "kv" and name.strip():
                table.insertRow(row)
                name_item = QTableWidgetItem(name)
                name_item.setForeground(QColor(LABEL_COLOR))
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                table.setItem(row, 0, name_item)

                display_value = f"{value} {unit}" if unit and value else (value or unit or "")
                val_label = QLabel(display_value)
                val_label.setWordWrap(True)
                # 百分比着色
                fg = "#1a1a1a"
                if "%" in display_value:
                    stripped = display_value.strip()
                    if stripped.startswith("+"):
                        fg = "#1b8a1b"
                    elif stripped.startswith("-"):
                        fg = "#d32f2f"
                val_label.setStyleSheet(VAL_LABEL_STYLE.replace("#1a1a1a", fg))
                table.setCellWidget(row, 1, val_label)

        # 自动高度：让 QLabel 换行计算后设定行高
        rows = table.rowCount()
        height = table.horizontalHeader().height() + 2
        for r in range(rows):
            w = table.cellWidget(r, 1)
            if isinstance(w, QLabel):
                w.setFixedWidth(w.width() or 200)
                w.adjustSize()
                rh = w.sizeHint().height() + 4
                table.setRowHeight(r, max(20, rh))
            height += table.rowHeight(r) + 2
        table.setFixedHeight(height)
        for r in range(rows):
            height += table.rowHeight(r) + 2
        table.setFixedHeight(height)

        layout.addWidget(table)

        return container

    def _on_consumable_btn_click(self, cid: str, dname: str, parent_container: QWidget):
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
                "SELECT * FROM consumable_configs WHERE version_code=? AND consumable_id=? "
                "AND config_key='Default'",
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
                        kv("每秒回复血量", f"{'+' if rr > 0 else ''}{rr*100:.2f}%")
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
            txt = "\n".join(config_contents.get(cl, []))
            te.setPlainText(self._strip_indent(txt))
            cstack.addWidget(te)
            btn = QPushButton(cl)
            btn.setCheckable(True)
            btn.setStyleSheet("QPushButton{background:transparent;color:#555;border:none;"
                              "border-radius:4px;padding:4px 10px;font-size:11px;}"
                              "QPushButton:hover{background:#d0d0d0;color:#333;}"
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

