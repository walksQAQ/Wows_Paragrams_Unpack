from __future__ import annotations

import json
import math

from PySide6.QtCore import Qt, QSettings, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap, QIntValidator
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QWidget, QMessageBox, QSizePolicy,
    QSpinBox, QDoubleSpinBox, QLineEdit, QGroupBox,
    QTabWidget, QFrame, QListWidget, QSlider, QScrollArea,
    QGridLayout, QCheckBox, QCompleter,
)


class CustomWeaponDialog(QDialog):
    """自定义炮弹输入对话框：所有计算值均允许手动填写。

    get_data() 返回 {"label", "ammo": {...}, "gun": {...}}，字段与数据库
    ammo_row / gun_row 兼容，可直接用于 _compute_rows_for_weapon。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义炮弹数据")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名称:"))
        self.name_edit = QLineEdit("自定义炮弹名")
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        # 弹药参数
        ammo_box = QGroupBox("弹药参数")
        ag = QGridLayout(ammo_box)
        ag.setSpacing(6)
        self.f_mass = QDoubleSpinBox(); self.f_mass.setRange(0, 100000); self.f_mass.setDecimals(2); self.f_mass.setValue(800.0); self.f_mass.setSuffix(" kg")
        self.f_caliber = QDoubleSpinBox(); self.f_caliber.setRange(0, 1000); self.f_caliber.setDecimals(1); self.f_caliber.setValue(305.0); self.f_caliber.setSuffix(" mm")
        self.f_drag = QDoubleSpinBox(); self.f_drag.setRange(0, 10); self.f_drag.setDecimals(3); self.f_drag.setValue(0.35)
        self.f_speed = QDoubleSpinBox(); self.f_speed.setRange(0, 5000); self.f_speed.setDecimals(0); self.f_speed.setValue(800.0); self.f_speed.setSuffix(" m/s")
        self.f_krupp = QDoubleSpinBox(); self.f_krupp.setRange(0, 100000); self.f_krupp.setDecimals(0); self.f_krupp.setValue(2400.0)
        self.f_ammo_type = QComboBox(); self.f_ammo_type.addItems(["AP", "HE", "CS"])
        self.f_fixed_pen = QDoubleSpinBox(); self.f_fixed_pen.setRange(0, 10000); self.f_fixed_pen.setDecimals(1); self.f_fixed_pen.setValue(0.0); self.f_fixed_pen.setSuffix(" mm")
        _ammo_rows = [
            ("弹重", self.f_mass), ("口径", self.f_caliber), ("风阻", self.f_drag),
            ("初速", self.f_speed), ("Krupp", self.f_krupp),
            ("弹种", self.f_ammo_type), ("HE/CS 固定穿深(0=自动)", self.f_fixed_pen),
        ]
        for _i, (_lb, _w) in enumerate(_ammo_rows):
            ag.addWidget(QLabel(_lb), _i, 0)
            ag.addWidget(_w, _i, 1)
        root.addWidget(ammo_box)

        # 火炮参数
        gun_box = QGroupBox("火炮参数（散布 / 射程）")
        gg = QGridLayout(gun_box)
        gg.setSpacing(6)
        self.f_max_range = QDoubleSpinBox(); self.f_max_range.setRange(0.1, 100); self.f_max_range.setDecimals(1); self.f_max_range.setValue(20.0); self.f_max_range.setSuffix(" km")
        self.f_sigma = QDoubleSpinBox(); self.f_sigma.setRange(0.1, 10); self.f_sigma.setDecimals(2); self.f_sigma.setValue(2.0)
        self.f_min_radius = QDoubleSpinBox(); self.f_min_radius.setRange(0, 10000); self.f_min_radius.setDecimals(1); self.f_min_radius.setValue(100.0)
        self.f_ideal_radius = QDoubleSpinBox(); self.f_ideal_radius.setRange(0, 100000); self.f_ideal_radius.setDecimals(1); self.f_ideal_radius.setValue(200.0)
        self.f_ideal_distance = QDoubleSpinBox(); self.f_ideal_distance.setRange(0, 100000); self.f_ideal_distance.setDecimals(1); self.f_ideal_distance.setValue(1000.0)
        self.f_radius_zero = QDoubleSpinBox(); self.f_radius_zero.setRange(0, 10); self.f_radius_zero.setDecimals(3); self.f_radius_zero.setValue(0.2)
        self.f_radius_delim = QDoubleSpinBox(); self.f_radius_delim.setRange(0, 10); self.f_radius_delim.setDecimals(3); self.f_radius_delim.setValue(0.5)
        self.f_radius_max = QDoubleSpinBox(); self.f_radius_max.setRange(0, 10); self.f_radius_max.setDecimals(3); self.f_radius_max.setValue(0.6)
        self.f_delim = QDoubleSpinBox(); self.f_delim.setRange(0, 2); self.f_delim.setDecimals(2); self.f_delim.setValue(0.5)
        self.f_norm = QDoubleSpinBox(); self.f_norm.setRange(0, 90); self.f_norm.setDecimals(1); self.f_norm.setValue(0.0); self.f_norm.setSuffix(" °")
        _gun_rows = [
            ("最大射程", self.f_max_range), ("Sigma", self.f_sigma),
            ("最小散布半径", self.f_min_radius), ("理想散布半径", self.f_ideal_radius),
            ("理想距离", self.f_ideal_distance), ("零距离散布系数", self.f_radius_zero),
            ("分隔点散布系数", self.f_radius_delim), ("最大散布系数", self.f_radius_max),
            ("delim", self.f_delim), ("归一化角(0=按口径)", self.f_norm),
        ]
        for _i, (_lb, _w) in enumerate(_gun_rows):
            gg.addWidget(QLabel(_lb), _i, 0)
            gg.addWidget(_w, _i, 1)
        root.addWidget(gun_box)

        # 自定义加成（Buff）：射程 / 散布倍率
        buff_box = QGroupBox("自定义加成（Buff）")
        bg = QGridLayout(buff_box)
        bg.setSpacing(6)
        self.f_buff_range = QDoubleSpinBox(); self.f_buff_range.setRange(0.1, 5.0); self.f_buff_range.setDecimals(3); self.f_buff_range.setValue(1.0); self.f_buff_range.setSuffix(" ×")
        self.f_buff_acc = QDoubleSpinBox(); self.f_buff_acc.setRange(0.1, 5.0); self.f_buff_acc.setDecimals(3); self.f_buff_acc.setValue(1.0); self.f_buff_acc.setSuffix(" ×")
        bg.addWidget(QLabel("射程倍率"), 0, 0)
        bg.addWidget(self.f_buff_range, 0, 1)
        bg.addWidget(QLabel("散布倍率"), 1, 0)
        bg.addWidget(self.f_buff_acc, 1, 1)
        root.addWidget(buff_box)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

    def get_data(self) -> dict:
        ammo_type = self.f_ammo_type.currentText()
        fixed = self.f_fixed_pen.value()
        return {
            "label": self.name_edit.text().strip() or "自定义炮弹名",
            "ammo": {
                "bullet_mass": self.f_mass.value(),
                "bullet_diameter": self.f_caliber.value() / 1000.0,  # mm → m
                "bullet_air_drag": self.f_drag.value(),
                "bullet_speed": self.f_speed.value(),
                "bullet_krupp": self.f_krupp.value(),
                "ammo_type": ammo_type,
                "alpha_piercing_he": fixed if ammo_type == "HE" else 0.0,
                "alpha_piercing_cs": fixed if ammo_type == "CS" else 0.0,
            },
            "gun": {
                "max_range": self.f_max_range.value(),
                "sigma": self.f_sigma.value(),
                "min_radius": self.f_min_radius.value(),
                "ideal_radius": self.f_ideal_radius.value(),
                "ideal_distance": self.f_ideal_distance.value(),
                "radius_zero": self.f_radius_zero.value(),
                "radius_delim": self.f_radius_delim.value(),
                "radius_max": self.f_radius_max.value(),
                "delim": self.f_delim.value(),
                "norm_angle": self.f_norm.value(),
            },
            "buff": {
                "gmmd": self.f_buff_range.value(),
                "gm": self.f_buff_acc.value(),
                "name": "自定义加成",
            },
        }


class SideAmmoLabel(QWidget):
    """侧边面板可点击弹药标签：第一行大字体弹药名，下方每行小字体加成来源名。
    QPushButton 不支持富文本，改用 QWidget + QLabel（QLabel 支持不同字体大小与自动换行）。"""
    clicked = Signal(int)

    def __init__(self, label: str, mod_names: list[str], color: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QWidget { background:#ffffff; border:1px solid #d8d8d8; border-radius:4px; }"
            "QWidget:hover { background:#ffeaea; border-color:#e91e63; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(1)
        main_lb = QLabel(f"✕  {label}")
        main_lb.setStyleSheet(f"font-size:11px; color:{color}; background:transparent; border:none;")
        main_lb.setWordWrap(True)
        lay.addWidget(main_lb)
        for name in mod_names:
            sub = QLabel(str(name))
            sub.setStyleSheet("font-size:9px; color:#999999; background:transparent; border:none;")
            sub.setWordWrap(True)
            lay.addWidget(sub)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(0)
        super().mouseReleaseEvent(ev)


class PenetrationCalculatorDialog(QDialog):
    """穿深/散布计算器对话框。"""

    NATION_MAP = {
        "USA": "美国",
        "JAPAN": "日本",
        "GERMANY": "德国",
        "RUSSIA": "苏联",
        "UNITED_KINGDOM": "英国",
        "FRANCE": "法国",
        "ITALY": "意大利",
        "PAN_ASIA": "泛亚",
        "EUROPE": "欧洲",
        "NETHERLANDS": "荷兰",
        "COMMONWEALTH": "英联邦",
        "PAN_AMERICA": "泛美",
        "SPAIN": "西班牙",
        "EVENTS": "其他",
    }

    SHIP_CLASS_MAP = {
        "DESTROYER": "驱逐舰",
        "CRUISER": "巡洋舰",
        "BATTLESHIP": "战列舰",
        "AIRCARRIER": "航空母舰",
        "SUBMARINE": "潜艇",
        "AUXILIARY": "其他类型",
    }

    # 主弹药使用池[0]（蓝色），对比系列从池[1]起按序分配颜色
    COLOR_POOL = [
        "#0078d4", "#ff7a45", "#3fa34d", "#9a4dff", "#d4a000",
        "#00a6a6", "#e91e63", "#8d6e63", "#5c6bc0", "#26a69a",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("穿深/散布计算器")
        self.resize(1180, 780)
        self.setMinimumSize(960, 620)
        self._settings = QSettings("PenetrationCalculator", "DAP")
        self._build_ui()
        self._load_data()
        self._restored_geometry = self._restore_geometry()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.setStyleSheet("""
            QDialog {
                background: #f5f5f5;
                color: #222222;
            }
            QLabel {
                color: #333333;
                font-size: 12px;
            }
            QComboBox {
                background: #ffffff;
                color: #222222;
                border: 1px solid #b8b8b8;
                border-radius: 4px;
                padding: 4px 8px;
                min-height: 28px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #c3c3c3;
                background: #f0f0f0;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                color: #222222;
                border: 1px solid #b8b8b8;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
            }
            QPushButton {
                background: #f2f2f2;
                color: #222222;
                border: 1px solid #b5b5b5;
                border-radius: 4px;
                padding: 6px 12px;
                min-height: 28px;
            }
            QPushButton:hover {
                background: #e8f3ff;
                border-color: #0078d4;
            }
            QPushButton:pressed {
                background: #dcecff;
            }
            QPushButton:disabled {
                background: #f7f7f7;
                color: #999999;
                border-color: #d2d2d2;
            }
            QTableWidget {
                background: #ffffff;
                color: #222222;
                border: 1px solid #d0d0d0;
                gridline-color: #e6e6e6;
                alternate-background-color: #f8fbff;
            }
            QHeaderView::section {
                background: #efefef;
                color: #222222;
                padding: 6px 8px;
                border: 1px solid #d0d0d0;
                font-weight: bold;
            }
            QTableWidget::item {
                background: #ffffff;
                color: #222222;
                border: 1px solid #ececec;
                padding: 4px;
            }
            QTableWidget::item:selected {
                background: #0078d4;
                color: #ffffff;
            }
            QWidget {
                color: #222222;
            }
        """)

        # 主体：左侧炮弹清单 + 右侧内容
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        root.addLayout(body)

        self.side_panel = QWidget(self)
        self.side_panel.setObjectName("CalculatorSidePanel")
        self.side_panel.setFixedWidth(250)
        self.side_panel.setStyleSheet("""
            QWidget#CalculatorSidePanel {
                background: #ffffff;
                border: 1px solid #d8d8d8;
                border-radius: 6px;
            }
        """)
        sp = QVBoxLayout(self.side_panel)
        sp.setContentsMargins(8, 8, 8, 8)
        sp.setSpacing(6)
        sp.addWidget(QLabel("已添加炮弹"))
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.side_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.side_container = QWidget()
        self.side_container_layout = QVBoxLayout(self.side_container)
        self.side_container_layout.setContentsMargins(0, 0, 0, 0)
        self.side_container_layout.setSpacing(6)
        self.side_container_layout.addStretch()
        self.side_scroll.setWidget(self.side_container)
        sp.addWidget(self.side_scroll, 1)
        self.side_clear_btn = QPushButton("清空")
        sp.addWidget(self.side_clear_btn)
        self.side_hint = QLabel("从顶部筛选器选择炮弹后\n点击 \"➕ 添加此弹药\"\n\n点击炮弹按钮即可将其移出显示")
        self.side_hint.setStyleSheet("color:#999; font-size:11px;")
        self.side_hint.setWordWrap(True)
        sp.addWidget(self.side_hint)
        body.addWidget(self.side_panel)

        self._right = QWidget(self)
        rl = QVBoxLayout(self._right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        body.addWidget(self._right, 1)

        filters = QWidget(self)
        filters.setObjectName("CalculatorFilterBar")
        filters.setStyleSheet("""
            QWidget#CalculatorFilterBar {
                background: #ffffff;
                border: 1px solid #d8d8d8;
                border-radius: 6px;
            }
        """)
        fv = QVBoxLayout(filters)
        fv.setContentsMargins(8, 4, 8, 4)
        fv.setSpacing(4)

        self.nation_cb = QComboBox()
        self.ship_type_cb = QComboBox()
        self.tier_cb = QComboBox()
        self.ship_cb = QComboBox()
        self.gun_cb = QComboBox()
        self.ammo_cb = QComboBox()

        self.nation_cb.setMinimumWidth(105)
        self.ship_type_cb.setMinimumWidth(95)
        self.tier_cb.setMinimumWidth(70)
        self.ship_cb.setMinimumWidth(130)
        self.gun_cb.setMinimumWidth(220)
        self.ammo_cb.setMinimumWidth(200)

        # 行1：舰船选择
        row_ship = QHBoxLayout()
        row_ship.setSpacing(6)
        row_ship.addWidget(QLabel("国籍:"))
        row_ship.addWidget(self.nation_cb)
        row_ship.addWidget(QLabel("舰种:"))
        row_ship.addWidget(self.ship_type_cb)
        row_ship.addWidget(QLabel("等级:"))
        row_ship.addWidget(self.tier_cb)
        row_ship.addWidget(QLabel("舰船:"))
        # 舰船选择框可编辑，输入即搜索（与主界面搜索逻辑一致：匹配舰名/编号）
        self.ship_cb.setEditable(True)
        self.ship_cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # 禁用内置 completer，改用挂到 lineEdit 的独立 QCompleter：
        # 输入时弹建议列表但【完全不切换焦点】。UnfilteredPopupCompletion 直接显示我们已过滤的 model
        self.ship_cb.setCompleter(None)
        self.ship_cb.view().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ship_completer = QCompleter([], self)
        self._ship_completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._ship_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.ship_cb.lineEdit().setCompleter(self._ship_completer)
        self.ship_cb.lineEdit().setPlaceholderText("🔍 搜索/选择舰船")
        row_ship.addWidget(self.ship_cb)
        row_ship.addStretch()
        fv.addLayout(row_ship)

        # 行2：武器选择 + 操作按钮（紧凑合并）
        row_weapon = QHBoxLayout()
        row_weapon.setSpacing(6)
        row_weapon.addWidget(QLabel("火炮:"))
        row_weapon.addWidget(self.gun_cb)
        row_weapon.addWidget(QLabel("弹药:"))
        row_weapon.addWidget(self.ammo_cb)
        row_weapon.addStretch()
        self.add_cmp_btn = QPushButton("➕ 添加此弹药")
        self.custom_btn = QPushButton("✎ 添加自定义弹药")
        row_weapon.addWidget(self.add_cmp_btn)
        row_weapon.addWidget(self.custom_btn)
        fv.addLayout(row_weapon)
        rl.addWidget(filters)

        # 插件加成卡片（射程 / 精度）—— 主界面升级品按钮样式
        self.mods_frame = QFrame(self)
        self.mods_frame.setObjectName("CalculatorModsBar")
        self.mods_frame.setStyleSheet(
            "QFrame#CalculatorModsBar { background:#ffffff; border:1px solid #d8d8d8; border-radius:6px; }"
        )
        mvl = QVBoxLayout(self.mods_frame)
        mvl.setContentsMargins(8, 4, 8, 4)
        mvl.setSpacing(4)
        mh = QHBoxLayout()
        _mods_title = QLabel("射程 / 精度加成（插件 · 消耗品 · 战斗指令）：")
        _mods_title.setStyleSheet("font-size:12px; color:#555;")
        mh.addWidget(_mods_title)
        mh.addStretch()
        self.mods_reset_btn = QPushButton("清空选择")
        self.mods_reset_btn.setStyleSheet("font-size:11px; padding:2px 10px;")
        mh.addWidget(self.mods_reset_btn)
        mvl.addLayout(mh)
        # 加成按钮容器（图标 + 加成文字直接显示，不依赖悬浮窗）—— 单行 + 横向滚动条
        self.mods_scroll = QScrollArea(self.mods_frame)
        self.mods_scroll.setWidgetResizable(True)  # 内容随视口自适应宽度；末尾 stretch 保证超宽时出现横向滚动条
        self.mods_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.mods_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.mods_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.mods_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.mods_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:horizontal { height:10px; background:#f0f0f0; border-radius:5px; }"
            "QScrollBar::handle:horizontal { background:#b0b0b0; border-radius:5px; min-width:30px; }"
            "QScrollBar::handle:horizontal:hover { background:#909090; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; background:none; border:none; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:none; }"
        )
        self.mods_container = QWidget()
        self.mods_scroll.setWidget(self.mods_container)
        self.mods_grid = QHBoxLayout(self.mods_container)
        self.mods_grid.setContentsMargins(0, 0, 0, 0)
        self.mods_grid.setSpacing(6)
        mvl.addWidget(self.mods_scroll)
        rl.addWidget(self.mods_frame)
        self.mods_frame.setVisible(False)

        self.chart_tabs = QTabWidget(self)
        self.chart_tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #d8d8d8; border-radius: 6px; background:#ffffff; }")

        self.chart_container = QWidget(self)
        self.chart_layout = QVBoxLayout(self.chart_container)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_label = QLabel("穿深曲线：等待计算…")
        self.chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label.setStyleSheet("color: #444444; border: 1px solid #d0d0d0; background: #ffffff; border-radius: 6px; padding: 10px 12px;")
        self.chart_layout.addWidget(self.chart_label)
        self.chart_label.setVisible(False)  # 样本点提示显示区域已删除（用户要求）
        self.chart_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.chart_container.setMinimumHeight(180)
        self.chart_container.setStyleSheet("QWidget { background: #ffffff; border-radius: 6px; }")
        self.chart_tabs.addTab(self.chart_container, "穿深曲线")

        self.ellipse_container = QWidget(self)
        self.ellipse_layout = QVBoxLayout(self.ellipse_container)
        self.ellipse_layout.setContentsMargins(4, 4, 4, 4)
        ellipse_ctl = QHBoxLayout()
        ellipse_ctl.setSpacing(8)
        ellipse_ctl.addWidget(QLabel("散布射程:"))
        self.ellipse_slider = QSlider(Qt.Orientation.Horizontal)
        self.ellipse_slider.setRange(2, 400)  # 0.2 ~ 40.0 km，按最大射程调整
        self.ellipse_slider.setValue(100)
        self.ellipse_slider.setSingleStep(1)
        self.ellipse_slider.setFixedWidth(240)
        ellipse_ctl.addWidget(self.ellipse_slider)
        self.ellipse_value_label = QLabel("10.0 km")
        self.ellipse_value_label.setFixedWidth(64)
        ellipse_ctl.addWidget(self.ellipse_value_label)
        ellipse_ctl.addWidget(QLabel("散点:"))
        # 彻底重做：QLineEdit + 独立 ▲▼ 按钮（弃用 QSpinBox，避免其箭头 QSS subcontrol 各种显示问题）
        self.scatter_wrap = QWidget(self)
        _sw = QHBoxLayout(self.scatter_wrap)
        _sw.setContentsMargins(0, 0, 0, 0)
        _sw.setSpacing(2)
        self.scatter_edit = QLineEdit(self)
        self.scatter_edit.setFixedSize(54, 30)
        self.scatter_edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.scatter_edit.setValidator(QIntValidator(50, 3000, self))
        self.scatter_edit.setText("600")
        _btn_style = (
            "QPushButton { background:#f0f0f0; color:#222; border:1px solid #b8b8b8;"
            " border-radius:2px; padding:0px; font-size:9px;"
            " min-height:0px; max-height:14px; }"
            "QPushButton:hover { background:#e8f3ff; border-color:#0078d4; }"
            "QPushButton:pressed { background:#dcecff; }"
        )
        self.scatter_btn_up = QPushButton("▲", self)
        self.scatter_btn_down = QPushButton("▼", self)
        self.scatter_btn_up.setFixedSize(26, 14)
        self.scatter_btn_down.setFixedSize(26, 14)
        self.scatter_btn_up.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.scatter_btn_down.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.scatter_btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scatter_btn_down.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scatter_btn_up.setStyleSheet(_btn_style)
        self.scatter_btn_down.setStyleSheet(_btn_style)
        _btns = QVBoxLayout()
        _btns.setContentsMargins(0, 0, 0, 0)
        _btns.setSpacing(1)
        _btns.addWidget(self.scatter_btn_up)
        _btns.addWidget(self.scatter_btn_down)
        _sw.addWidget(self.scatter_edit)
        _sw.addLayout(_btns)
        ellipse_ctl.addWidget(self.scatter_wrap)
        # 莱斯塔 wiki：未锁定目标射击 → 散布椭圆 ×2
        self.ellipse_unlocked_cb = QCheckBox("未锁定目标 ×2")
        self.ellipse_unlocked_cb.setToolTip("未捕获目标时射击，散布椭圆增大 2 倍（莱斯塔 wiki）")
        self.ellipse_unlocked_cb.setStyleSheet("QCheckBox { color:#333; font-size:11px; }")
        ellipse_ctl.addWidget(self.ellipse_unlocked_cb)
        ellipse_ctl.addStretch()
        self.ellipse_layout.addLayout(ellipse_ctl)
        # 散布信息区：左侧“当前设定射程” + 右侧炮弹信息（每炮弹一行、左对齐），垂直居中
        self.ellipse_label = QWidget(self)
        self.ellipse_label.setStyleSheet("QWidget { background:#ffffff; border:1px solid #d0d0d0; border-radius:6px; }")
        _ell_lay = QHBoxLayout(self.ellipse_label)
        _ell_lay.setContentsMargins(10, 8, 10, 8)
        _ell_lay.setSpacing(12)
        self.ellipse_range_label = QLabel("当前设定射程：—")
        self.ellipse_range_label.setStyleSheet("color:#333333; font-weight:bold; background:transparent; border:none;")
        self.ellipse_range_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        _ell_lay.addWidget(self.ellipse_range_label)
        self.ellipse_info_label = QLabel("等待计算…")
        self.ellipse_info_label.setWordWrap(True)
        self.ellipse_info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.ellipse_info_label.setStyleSheet("color:#444444; background:transparent; border:none;")
        _ell_lay.addWidget(self.ellipse_info_label, 1)
        self.ellipse_layout.addWidget(self.ellipse_label)
        self.ellipse_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.ellipse_container.setMinimumHeight(180)
        self.ellipse_container.setStyleSheet("QWidget { background: #ffffff; border-radius: 6px; }")
        self.chart_tabs.addTab(self.ellipse_container, "散布椭圆")

        self.flytime_container = QWidget(self)
        self.flytime_layout = QVBoxLayout(self.flytime_container)
        self.flytime_layout.setContentsMargins(0, 0, 0, 0)
        self.flytime_label = QLabel("飞行时间曲线：等待计算…")
        self.flytime_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.flytime_label.setStyleSheet("color: #444444; border: 1px solid #d0d0d0; background: #ffffff; border-radius: 6px; padding: 10px 12px;")
        self.flytime_layout.addWidget(self.flytime_label)
        self.flytime_label.setVisible(False)  # 样本点提示显示区域已删除（用户要求）
        self.flytime_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.flytime_container.setMinimumHeight(180)
        self.flytime_container.setStyleSheet("QWidget { background: #ffffff; border-radius: 6px; }")
        self.chart_tabs.addTab(self.flytime_container, "飞行时间")

        self._metric_tabs = []
        self._metric_tab_map = {}
        for key, title, ylabel, idx in (
            ("angle", "落弹角", "落弹角 (°)", 6),
        ):
            container = QWidget(self)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(f"{title}：等待计算…")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #444444; border: 1px solid #d0d0d0; background: #ffffff; border-radius: 6px; padding: 10px 12px;")
            layout.addWidget(label)
            label.setVisible(False)  # 样本点提示显示区域已删除（用户要求）
            container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            container.setMinimumHeight(180)
            container.setStyleSheet("QWidget { background: #ffffff; border-radius: 6px; }")
            self.chart_tabs.addTab(container, title)
            spec = {"key": key, "title": title, "ylabel": ylabel, "idx": idx, "layout": layout, "label": label}
            self._metric_tabs.append(spec)
            self._metric_tab_map[key] = spec

        # Tab 顺序：散布椭圆 → 飞行时间 → 落弹角 → 穿深曲线
        _tab_order = ["散布椭圆", "飞行时间", "落弹角", "穿深曲线"]
        for _tidx, _tt in enumerate(_tab_order):
            for _t in range(self.chart_tabs.count()):
                if self.chart_tabs.tabText(_t) == _tt:
                    _tw = self.chart_tabs.widget(_t)
                    self.chart_tabs.removeTab(_t)
                    self.chart_tabs.insertTab(_tidx, _tw, _tt)
                    break
        # 重排会让 currentIndex 漂移，强制默认显示第一个（散布椭圆）
        self.chart_tabs.setCurrentIndex(0)
        rl.addWidget(self.chart_tabs)

        self.nation_cb.currentIndexChanged.connect(self._reload_ships)
        self.ship_type_cb.currentIndexChanged.connect(self._reload_ships)
        self.tier_cb.currentIndexChanged.connect(self._reload_ships)
        self.ship_cb.lineEdit().textChanged.connect(self._on_ship_search)
        self.ship_cb.activated.connect(self._on_ship_activated)
        self.ship_cb.currentIndexChanged.connect(self._reload_guns)
        self._ship_completer.activated.connect(self._on_completer_activated)
        # 双保险：completer popup 的点击/回车也直接选中（QCompleter 内部转发可能不完全）
        self._ship_completer.popup().activated.connect(self._on_completer_index)
        self._ship_completer.popup().clicked.connect(self._on_completer_index)
        self.gun_cb.currentIndexChanged.connect(self._on_gun_changed)
        self.add_cmp_btn.clicked.connect(self._add_custom_series)
        self.custom_btn.clicked.connect(self._open_custom_weapon_dialog)
        self.side_clear_btn.clicked.connect(self._clear_side)
        self.mods_reset_btn.clicked.connect(self._reset_mods)
        self.ellipse_slider.valueChanged.connect(self._on_ellipse_slider)
        self.scatter_btn_up.clicked.connect(lambda: self._scatter_step(1))
        self.scatter_btn_down.clicked.connect(lambda: self._scatter_step(-1))
        self.scatter_edit.editingFinished.connect(self._scatter_apply)
        self.ellipse_unlocked_cb.toggled.connect(self._update_dispersion_ellipse)

        self._ship_catalog = []
        self._ship_keyword = ""
        self._ship_searching = False
        self._ship_popup_open = False
        self._ship_allow_auto = False
        self._last_rows = []
        self._last_compare_series = []
        self._last_sigma = 1.0
        self._last_norm_angle = 6.0
        self._custom_series = []
        self._mod_items = []
        self._mod_buttons = []
        self._side_buttons = []

    def _resolve_nation_label(self, nation: str | None) -> str:
        if not nation:
            return "未知"
        key = str(nation).strip()
        return self.NATION_MAP.get(key, self.NATION_MAP.get(key.upper(), key))

    def _resolve_ship_class_label(self, ship_class: str | None) -> str:
        if not ship_class:
            return "未知"
        key = str(ship_class).strip()
        return self.SHIP_CLASS_MAP.get(key, self.SHIP_CLASS_MAP.get(key.upper(), key))

    def _on_ship_search(self, text: str):
        """筛选器舰船搜索：同主界面逻辑，匹配舰名（中文）与舰船编号。输入时弹出 completer 建议。"""
        # 选中后的文本同步：当前文本即选中项文本 → 不进入搜索、不弹建议、不取消选中
        cur_idx = self.ship_cb.currentIndex()
        if (self.ship_cb.currentData() is not None and cur_idx >= 0
                and self.ship_cb.itemText(cur_idx) == str(text or "")):
            self._ship_keyword = ""
            self._ship_searching = False
            self._ship_popup_open = False
            return
        self._ship_searching = True
        self._ship_keyword = str(text or "")
        self._reload_ships()
        kw = self._ship_keyword.strip()
        # 可见匹配项数（隐藏法下 count() 恒为全量，须用可见数判断）
        _view = self.ship_cb.view()
        _visible = sum(1 for _i in range(self.ship_cb.count()) if not _view.isRowHidden(_i))
        if kw and _visible > 0 and self.ship_cb.currentData() is None:
            # 用 completer 弹建议（UnfilteredPopupCompletion：model 已是过滤后的匹配项，直接全部显示）。
            # completer popup 设计上不抢焦点 → 输入框保持焦点可继续输入
            try:
                self._ship_completer.setCompletionPrefix(str(text or ""))
                self._ship_completer.complete()
            except Exception:
                pass
            self._ship_popup_open = True
        else:
            self._ship_popup_open = False
            try:
                self._ship_completer.popup().hide()
            except Exception:
                pass

    def _on_completer_activated(self, text):
        """用户从 completer 建议列表选择：把对应舰船选到 combo。"""
        idx = self.ship_cb.findText(str(text))
        if idx >= 0:
            self.ship_cb.setCurrentIndex(idx)
            self._on_ship_activated(idx)

    def _on_completer_index(self, index):
        """completer popup 项被点击/激活（QModelIndex 版本）。"""
        if index is not None and index.isValid():
            self._on_completer_activated(index.data())

    def _on_ship_activated(self, index: int):
        """用户从下拉选择舰船后，结束搜索态（避免选中后再次自动弹出）。"""
        self._ship_searching = False
        self._ship_popup_open = False

    def _reload_ships(self):
        prev_ship_id = self.ship_cb.currentData()
        nation = self.nation_cb.currentData() if self.nation_cb.count() else ""
        ship_class = self.ship_type_cb.currentData() if self.ship_type_cb.count() else ""
        tier = self.tier_cb.currentData() if self.tier_cb.count() else ""
        keyword = getattr(self, "_ship_keyword", "").strip().lower()
        line_edit = self.ship_cb.lineEdit() if self.ship_cb.isEditable() else None

        # 隐藏法：不重建列表，按条件隐藏不匹配行（item 列表固定 = 全部 catalog）。
        # 避免 clear+addItem 自动选中回填、setCurrentIndex(-1)+setText 恢复链在真实事件循环下丢字符
        view = self.ship_cb.view()
        self.ship_cb.blockSignals(True)
        if line_edit is not None:
            line_edit.blockSignals(True)
        visible_count = 0
        for i, ship in enumerate(self._ship_catalog):
            match = True
            if keyword:
                hay = f"{ship.get('label') or ''} {ship['ship_id']}".lower()
                if keyword not in hay:
                    match = False
            if match and nation and ship["nation"] != nation:
                match = False
            if match and ship_class and ship["shiptype"] != ship_class:
                match = False
            if match and tier != "" and ship["tier"] != tier:
                match = False
            view.setRowHidden(i, not match)
            if match:
                visible_count += 1

        # 更新 completer 建议数据（仅可见项；UnfilteredPopupCompletion 下这些即全部候选）
        try:
            self._ship_completer.model().setStringList(
                [self._ship_catalog[i]["label"] for i in range(len(self._ship_catalog)) if not view.isRowHidden(i)]
            )
        except Exception:
            pass

        if keyword or getattr(self, "_ship_searching", False):
            if self.ship_cb.currentData() is not None:
                # 之前选中过船 → 取消选中（editable 的 setCurrentIndex(-1) 会清空 lineEdit，用权威文本恢复）
                self.ship_cb.setCurrentIndex(-1)
                if line_edit is not None:
                    restore = str(getattr(self, "_ship_keyword", "") or "")
                    if restore:
                        line_edit.setText(restore)
                        line_edit.setCursorPosition(len(restore))
                    else:
                        line_edit.clear()
            # 未选中：lineEdit 文本即用户输入，绝不动它（setText/setCurrentIndex 会打断 IME/光标
            # 并反复触发重置 → 逐字符输入被"自动切断"的根因）
        elif prev_ship_id is not None:
            # 非搜索态：恢复之前选中的舰船（须可见）
            keep_idx = self.ship_cb.findData(prev_ship_id)
            if keep_idx >= 0 and not view.isRowHidden(keep_idx):
                self.ship_cb.setCurrentIndex(keep_idx)
            else:
                self.ship_cb.setCurrentIndex(-1)
        elif getattr(self, "_ship_allow_auto", False):
            # 非初始且无此前选中：自动选第一艘可见有效船
            valid_index = self._find_first_valid_ship_index()
            self.ship_cb.setCurrentIndex(valid_index if valid_index is not None else -1)
        else:
            # 初始加载：不选中任何舰船，方便直接输入搜索
            self.ship_cb.setCurrentIndex(-1)
            if line_edit is not None:
                line_edit.clear()
        if line_edit is not None:
            line_edit.blockSignals(False)
        self.ship_cb.blockSignals(False)

        if visible_count == 0:
            # 无匹配：保持用户输入原样、无选中、不弹下拉
            self._ship_popup_open = False
            self._reload_guns()
            return
        self._reload_guns()

    def _resolve_name(self, category: str, key: str | None) -> str:
        if not key:
            return ""
        try:
            from services.database_service import get_db
            db = get_db()
            row = db._conn.execute(
                "SELECT lang_zh FROM name_mappings WHERE category=? AND key_name=? LIMIT 1",
                (category, str(key).upper()),
            ).fetchone()
            if row and row["lang_zh"]:
                return row["lang_zh"]
        except Exception:
            pass
        return str(key)

    def _load_data(self):
        try:
            from services.database_service import get_db
            db = get_db()
            if not db.exists:
                self._set_error("当前未加载数据库，无法填充计算器数据。")
                return

            ship_rows = db._conn.execute(
                """
                SELECT DISTINCT sb.ship_id, sb.ship_index, sb.name_mapping_id, sb.shiptype, sb.tier, er.nation
                FROM ship_basic_info sb
                LEFT JOIN ship_module_artillery g
                    ON g.version_code = sb.version_code
                    AND g.ship_id = sb.ship_id
                LEFT JOIN ship_module_atba a
                    ON a.version_code = sb.version_code
                    AND a.ship_id = sb.ship_id
                LEFT JOIN ship_module_secondary_artillery s
                    ON s.version_code = sb.version_code
                    AND s.ship_id = sb.ship_id
                LEFT JOIN entity_registry er
                    ON er.version_code = sb.version_code
                    AND er.entity_id = sb.ship_id
                WHERE g.ship_id IS NOT NULL OR a.ship_id IS NOT NULL OR s.ship_id IS NOT NULL
                ORDER BY sb.ship_id
                """
            ).fetchall()
            if not ship_rows:
                ship_rows = db._conn.execute(
                    """
                    SELECT DISTINCT sb.ship_id, sb.ship_index, sb.name_mapping_id, sb.shiptype, sb.tier, er.nation
                    FROM ship_basic_info sb
                    LEFT JOIN entity_registry er
                        ON er.version_code = sb.version_code
                        AND er.entity_id = sb.ship_id
                    ORDER BY sb.ship_id
                """
            ).fetchall()

            self._ship_catalog = []
            # 批量解析舰船中文名，避免逐条查询（全量 ~964 艘）
            mapping_ids = [s["name_mapping_id"] for s in ship_rows if s["name_mapping_id"]]
            name_map = {}
            if mapping_ids:
                placeholders = ",".join("?" * len(mapping_ids))
                for row in db._conn.execute(
                    f"SELECT id, lang_zh FROM name_mappings WHERE id IN ({placeholders})",
                    mapping_ids,
                ).fetchall():
                    name_map[row["id"]] = row["lang_zh"]
            for ship in ship_rows:
                ship_id = ship["ship_id"]
                label = ship_id
                ship_index = ship["ship_index"]
                if ship_index:
                    label = self._resolve_name("ship", ship_index)
                if ship["name_mapping_id"] and name_map.get(ship["name_mapping_id"]):
                    label = name_map[ship["name_mapping_id"]]
                self._ship_catalog.append({
                    "ship_id": ship_id,
                    "label": label,
                    "nation": ship["nation"] or "",
                    "shiptype": ship["shiptype"] or "",
                    "tier": int(ship["tier"] or 0) if ship["tier"] is not None else 0,
                })

            self.nation_cb.blockSignals(True)
            self.nation_cb.clear()
            self.nation_cb.addItem("全部国籍", "")
            nation_values = sorted({s["nation"] for s in self._ship_catalog if s["nation"]})
            for nation in nation_values:
                self.nation_cb.addItem(self._resolve_nation_label(nation), nation)
            self.nation_cb.blockSignals(False)

            self.ship_type_cb.blockSignals(True)
            self.ship_type_cb.clear()
            self.ship_type_cb.addItem("全部舰种", "")
            shiptype_values = sorted({s["shiptype"] for s in self._ship_catalog if s["shiptype"]})
            for ship_type in shiptype_values:
                self.ship_type_cb.addItem(self._resolve_ship_class_label(ship_type), ship_type)
            self.ship_type_cb.blockSignals(False)

            self.tier_cb.blockSignals(True)
            self.tier_cb.clear()
            self.tier_cb.addItem("全部等级", "")
            tier_values = sorted({s["tier"] for s in self._ship_catalog if s["tier"] > 0})
            for t in tier_values:
                self.tier_cb.addItem(f"{t} 级", t)
            self.tier_cb.blockSignals(False)

            self._ship_allow_auto = False  # 初始加载不自动选中舰船，方便直接输入搜索
            # 一次性添加全部舰船（item 顺序 = _ship_catalog），后续用 view.setRowHidden 过滤，
            # 不重建列表——避免 clear+addItem 自动选中回填、setCurrentIndex(-1)+setText 链导致的输入截断
            self.ship_cb.blockSignals(True)
            self.ship_cb.clear()
            for _ship in self._ship_catalog:
                self.ship_cb.addItem(_ship["label"], _ship["ship_id"])
            self.ship_cb.setCurrentIndex(-1)
            self.ship_cb.blockSignals(False)
            self._reload_ships()
            self._calculate_current()
            self._ship_allow_auto = True
        except Exception as exc:
            self._set_error(str(exc))

    def _find_first_valid_ship_index(self):
        """返回第一个可见且有效的舰船索引（隐藏法下 item 列表固定 = 全部 catalog）。"""
        try:
            from services.database_service import get_db
            db = get_db()
            rows = db._conn.execute(
                "SELECT ship_id FROM ship_module_artillery "
                "UNION SELECT ship_id FROM ship_module_atba "
                "UNION SELECT ship_id FROM ship_module_secondary_artillery "
                "ORDER BY ship_id"
            ).fetchall()
            view = self.ship_cb.view()
            for row in rows:
                idx = self.ship_cb.findData(row["ship_id"])
                if idx >= 0 and not view.isRowHidden(idx):
                    return idx
        except Exception:
            pass
        # 兜底：第一个可见项
        try:
            view = self.ship_cb.view()
            for i in range(self.ship_cb.count()):
                if not view.isRowHidden(i):
                    return i
        except Exception:
            pass
        return None

    def _split_gun_key(self, gun_key):
        """解析复合 gun_key → (kind, module_key)。kind ∈ {'main','atba','sec'}。

        - main: 主炮（ship_module_artillery）
        - atba: 副炮（ship_module_atba）
        - sec:  次级主炮/中口径（ship_module_secondary_artillery）
        """
        gk = str(gun_key or "")
        if gk.startswith("atba:"):
            return "atba", gk[5:]
        if gk.startswith("sec:"):
            return "sec", gk[4:]
        if gk.startswith("main:"):
            return "main", gk[5:]
        return "main", gk

    def _slot_types_for_kind(self, kind):
        if kind == "atba":
            return ("atba",)
        if kind == "sec":
            return ("secondary_artillery",)
        return ("artillery",)

    def _load_gun_row(self, ship_id, gun_key):
        """按 gun_key 从主炮/副炮(atba)/次级主炮表加载炮数据，返回 (gun_row, kind)。"""
        kind, mod_key = self._split_gun_key(gun_key)
        table = {
            "main": "ship_module_artillery",
            "atba": "ship_module_atba",
            "sec": "ship_module_secondary_artillery",
        }.get(kind, "ship_module_artillery")
        from services.database_service import get_db
        db = get_db()
        row = db._conn.execute(
            f"SELECT * FROM {table} WHERE ship_id=? AND module_key=? LIMIT 1",
            (ship_id, mod_key),
        ).fetchone()
        return row, kind

    def _reload_guns(self):
        self.gun_cb.blockSignals(True)
        self.gun_cb.clear()
        ship_id = self.ship_cb.currentData()
        if not ship_id:
            self.gun_cb.addItem("无可用火炮")
            self.gun_cb.blockSignals(False)
            return
        try:
            from services.database_service import get_db
            db = get_db()
            # 主炮
            rows = db._conn.execute(
                "SELECT module_key, launcher_name FROM ship_module_artillery WHERE ship_id=? GROUP BY module_key ORDER BY module_key LIMIT 50",
                (ship_id,),
            ).fetchall()
            for row in rows:
                label = self._resolve_name("gun", row["module_key"]) or row["launcher_name"] or row["module_key"]
                self.gun_cb.addItem(f"主炮 · {label}", f"main:{row['module_key']}")
            # 副炮（atba）
            arows = db._conn.execute(
                "SELECT module_key, launcher_name FROM ship_module_atba WHERE ship_id=? GROUP BY module_key ORDER BY module_key LIMIT 50",
                (ship_id,),
            ).fetchall()
            for row in arows:
                label = self._resolve_name("gun", row["module_key"]) or row["launcher_name"] or row["module_key"]
                self.gun_cb.addItem(f"副炮 · {label}", f"atba:{row['module_key']}")
            # 次级主炮（中口径）
            srows = db._conn.execute(
                "SELECT module_key, launcher_name FROM ship_module_secondary_artillery WHERE ship_id=? GROUP BY module_key ORDER BY module_key LIMIT 50",
                (ship_id,),
            ).fetchall()
            for row in srows:
                label = self._resolve_name("gun", row["module_key"]) or row["launcher_name"] or row["module_key"]
                self.gun_cb.addItem(f"次级主炮 · {label}", f"sec:{row['module_key']}")
            if self.gun_cb.count() == 0:
                self.gun_cb.addItem("无可用火炮")
        except Exception:
            self.gun_cb.addItem("无可用火炮")
        # clear+addItem 会自动选中第 0 项且被 blockSignals 屏蔽；先复位 -1，
        # 确保下面 setCurrentIndex 一定改变索引并触发 currentIndexChanged → 重载加成面板
        self.gun_cb.setCurrentIndex(-1)
        self.gun_cb.blockSignals(False)

        valid_index = self._find_first_valid_gun_index()
        if valid_index is not None:
            self.gun_cb.setCurrentIndex(valid_index)
        elif self.gun_cb.count():
            self.gun_cb.setCurrentIndex(0)
        self._reload_ammo()

    def _find_first_valid_gun_index(self):
        ship_id = self.ship_cb.currentData()
        if not ship_id:
            return None
        try:
            from services.database_service import get_db
            db = get_db()
            rows = db._conn.execute(
                "SELECT DISTINCT module_key FROM ship_module_artillery WHERE ship_id=? ORDER BY module_key",
                (ship_id,),
            ).fetchall()
            for row in rows:
                idx = self.gun_cb.findData(f"main:{row['module_key']}")
                if idx >= 0:
                    return idx
            arows = db._conn.execute(
                "SELECT DISTINCT module_key FROM ship_module_atba WHERE ship_id=? ORDER BY module_key",
                (ship_id,),
            ).fetchall()
            for row in arows:
                idx = self.gun_cb.findData(f"atba:{row['module_key']}")
                if idx >= 0:
                    return idx
            srows = db._conn.execute(
                "SELECT DISTINCT module_key FROM ship_module_secondary_artillery WHERE ship_id=? ORDER BY module_key",
                (ship_id,),
            ).fetchall()
            for row in srows:
                idx = self.gun_cb.findData(f"sec:{row['module_key']}")
                if idx >= 0:
                    return idx
        except Exception:
            pass
        return None

    def _on_gun_changed(self, index: int):
        """切换火炮类型（主炮/副炮/次级主炮）时：按当前炮种重载加成按钮并刷新弹药。"""
        self._load_mod_bonuses()
        self._reload_ammo()

    def _reload_ammo(self):
        self.ammo_cb.blockSignals(True)
        self.ammo_cb.clear()
        ship_id = self.ship_cb.currentData()
        gun_key = self.gun_cb.currentData()
        if not ship_id or not gun_key:
            self.ammo_cb.addItem("无可用弹药")
            self.ammo_cb.blockSignals(False)
            return
        try:
            from services.database_service import get_db
            db = get_db()
            kind, mod_key = self._split_gun_key(gun_key)
            slot_types = self._slot_types_for_kind(kind)
            placeholders = ",".join("?" * len(slot_types))
            rows = db._conn.execute(
                f"""
                SELECT p.ammo_id, pb.ammo_type, pb.species
                FROM ship_weapon_projectiles p
                LEFT JOIN projectile_basic_info pb ON pb.projectile_id = p.ammo_id
                WHERE p.ship_id=? AND p.module_id=? AND p.slot_type IN ({placeholders})
                GROUP BY p.ammo_id
                ORDER BY p.ammo_order, p.ammo_id
                LIMIT 30
                """,
                (ship_id, mod_key, *slot_types),
            ).fetchall()
            if not rows:
                self.ammo_cb.addItem("无可用弹药")
            else:
                for row in rows:
                    ammo_id = row["ammo_id"]
                    ammo_type = row["ammo_type"] or ""
                    label = self._resolve_name("ammo", ammo_id)
                    if ammo_type:
                        label = f"{ammo_type} · {label}"
                    self.ammo_cb.addItem(label, ammo_id)
        except Exception:
            self.ammo_cb.addItem("无可用弹药")
        self.ammo_cb.blockSignals(False)
        valid_index = self._find_first_valid_ammo_index()
        if valid_index is not None:
            self.ammo_cb.setCurrentIndex(valid_index)
        elif self.ammo_cb.count():
            self.ammo_cb.setCurrentIndex(0)
        self._calculate_current()

    def _find_first_valid_ammo_index(self):
        ship_id = self.ship_cb.currentData()
        gun_key = self.gun_cb.currentData()
        if not ship_id or not gun_key:
            return None
        try:
            from services.database_service import get_db
            db = get_db()
            kind, mod_key = self._split_gun_key(gun_key)
            slot_types = self._slot_types_for_kind(kind)
            placeholders = ",".join("?" * len(slot_types))
            rows = db._conn.execute(
                f"SELECT DISTINCT ammo_id FROM ship_weapon_projectiles WHERE ship_id=? AND module_id=? AND slot_type IN ({placeholders}) ORDER BY ammo_id",
                (ship_id, mod_key, *slot_types),
            ).fetchall()
            for row in rows:
                idx = self.ammo_cb.findData(row["ammo_id"])
                if idx >= 0:
                    return idx
        except Exception:
            pass
        return None

    def _ensure_valid_current_selection(self):
        if getattr(self, "_ship_allow_auto", False):
            ship_index = self._find_first_valid_ship_index()
            if ship_index is not None and self.ship_cb.currentData() is None:
                self.ship_cb.setCurrentIndex(ship_index)

        gun_index = self._find_first_valid_gun_index()
        if gun_index is not None and self.gun_cb.currentData() is None:
            self.gun_cb.setCurrentIndex(gun_index)

        ammo_index = self._find_first_valid_ammo_index()
        if ammo_index is not None and self.ammo_cb.currentData() is None:
            self.ammo_cb.setCurrentIndex(ammo_index)

    def _set_error(self, msg: str):
        """延迟弹错误框：确保对话框窗口先显示再弹，避免 __init__/_load_data 在对话框尚未显示时
        弹模态框 → 阻塞等待点击且用户看不到窗口（表现为“点击后无窗口、程序卡住”）。"""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: QMessageBox.warning(self, "穿深计算器", msg))

    def _get_selected_weapon(self):
        ship_id = self.ship_cb.currentData()
        gun_key = self.gun_cb.currentData()
        ammo_id = self.ammo_cb.currentData()
        if not (ship_id and gun_key and ammo_id):
            return None, None, None
        from services.database_service import get_db
        db = get_db()
        gun_row, kind = self._load_gun_row(ship_id, gun_key)
        _, mod_key = self._split_gun_key(gun_key)
        slot_types = self._slot_types_for_kind(kind)
        placeholders = ",".join("?" * len(slot_types))
        ammo_row = db._conn.execute(
            f"""
            SELECT p.*, pb.ammo_type, pb.species, e.*
            FROM ship_weapon_projectiles p
            LEFT JOIN projectile_basic_info pb ON pb.projectile_id = p.ammo_id
            LEFT JOIN projectile_bullet_ext e ON e.projectile_id = p.ammo_id
            WHERE p.ship_id=? AND p.module_id=? AND p.ammo_id=? AND p.slot_type IN ({placeholders})
            LIMIT 1
            """,
            (ship_id, mod_key, ammo_id, *slot_types),
        ).fetchone()
        return gun_row, ammo_row, ship_id

    def _get_all_ammo_for_current_gun(self):
        ship_id = self.ship_cb.currentData()
        gun_key = self.gun_cb.currentData()
        if not ship_id or not gun_key:
            return []
        from services.database_service import get_db
        db = get_db()
        kind, mod_key = self._split_gun_key(gun_key)
        slot_types = self._slot_types_for_kind(kind)
        placeholders = ",".join("?" * len(slot_types))
        rows = db._conn.execute(
            f"""
            SELECT p.*, pb.ammo_type, pb.species, e.*
            FROM ship_weapon_projectiles p
            LEFT JOIN projectile_basic_info pb ON pb.projectile_id = p.ammo_id
            LEFT JOIN projectile_bullet_ext e ON e.projectile_id = p.ammo_id
            WHERE p.ship_id=? AND p.module_id=? AND p.slot_type IN ({placeholders})
            GROUP BY p.ammo_id
            ORDER BY p.ammo_order, p.ammo_id
            """,
            (ship_id, mod_key, *slot_types),
        ).fetchall()
        return list(rows)

    # ── 散布射程滑条 ───────────────────────────────────
    def _ellipse_dist_km(self) -> float:
        return self.ellipse_slider.value() / 10.0

    # ── 散点数量（QLineEdit + ▲▼ 按钮） ──
    def _scatter_value(self) -> int:
        try:
            return max(50, min(3000, int(self.scatter_edit.text() or 600)))
        except ValueError:
            return 600

    def _scatter_step(self, delta: int):
        """▲/▼ 步进 ±50。"""
        v = max(50, min(3000, self._scatter_value() + delta * 50))
        self.scatter_edit.setText(str(v))
        self._update_dispersion_ellipse()

    def _scatter_apply(self):
        """手动输入后收敛到 [50, 3000]。"""
        self.scatter_edit.setText(str(self._scatter_value()))
        self._update_dispersion_ellipse()

    def _on_ellipse_slider(self):
        self.ellipse_value_label.setText(f"{self._ellipse_dist_km():.1f} km")
        self._update_dispersion_ellipse()

    # ── 加入对比展示（筛选器选择 → 加入下方数据展示） ──
    def _load_weapon_for(self, ship_id, gun_key, ammo_id, mods=None):
        """加载任意 (舰船, 主炮/副炮, 弹药) 组合并计算，返回 (gun_row, ammo_row, rows)。"""
        from services.database_service import get_db
        db = get_db()
        try:
            gun_row, kind = self._load_gun_row(ship_id, gun_key)
            _, mod_key = self._split_gun_key(gun_key)
            slot_types = self._slot_types_for_kind(kind)
            placeholders = ",".join("?" * len(slot_types))
            ammo_row = db._conn.execute(
                f"""
                SELECT p.*, pb.ammo_type, pb.species, e.*
                FROM ship_weapon_projectiles p
                LEFT JOIN projectile_basic_info pb ON pb.projectile_id = p.ammo_id
                LEFT JOIN projectile_bullet_ext e ON e.projectile_id = p.ammo_id
                WHERE p.ship_id=? AND p.module_id=? AND p.ammo_id=? AND p.slot_type IN ({placeholders})
                LIMIT 1
                """,
                (ship_id, mod_key, ammo_id, *slot_types),
            ).fetchone()
        except Exception:
            return None, None, []
        if not gun_row or not ammo_row:
            return None, None, []
        rows = self._compute_rows_for_weapon(gun_row, ammo_row, mods)
        return gun_row, ammo_row, rows

    def _resolve_custom_label(self, ship_id, gun_key, ammo_id):
        from services.database_service import get_db
        ship_name = ship_id
        try:
            db = get_db()
            row = db._conn.execute(
                "SELECT ship_index FROM ship_basic_info WHERE ship_id=? LIMIT 1", (ship_id,)
            ).fetchone()
            if row and row["ship_index"]:
                ship_name = self._resolve_name("ship", row["ship_index"]) or ship_id
        except Exception:
            pass
        ammo_name = self._resolve_name("ammo", ammo_id) or ammo_id
        return f"{ship_name}·{ammo_name}"

    def _add_custom_series(self):
        ship_id = self.ship_cb.currentData()
        gun_key = self.gun_cb.currentData()
        ammo_id = self.ammo_cb.currentData()
        if not (ship_id and gun_key and ammo_id):
            self._set_error("请先选择舰船/主炮/弹药。")
            return
        for item in self._custom_series:
            if item.get("custom"):
                continue  # 跳过自定义炮弹项
            cur_mods = self._current_mods()
            if (item["ship_id"] == ship_id and item["gun_key"] == gun_key and item["ammo_id"] == ammo_id
                    and item.get("mods") == cur_mods):
                return  # 同炮弹且插件配置相同 → 不重复添加（不同插件配置可分别添加对比）
        self._custom_series.append({
            "ship_id": ship_id,
            "gun_key": gun_key,
            "ammo_id": ammo_id,
            "label": self._resolve_custom_label(ship_id, gun_key, ammo_id),
            "mods": self._current_mods(),  # 添加时固化插件选择
        })
        self._refresh_side_panel()
        self._calculate_current()

    def _clear_side(self):
        if not self._custom_series:
            return
        self._custom_series.clear()
        self._refresh_side_panel()
        self._calculate_current()

    def _open_custom_weapon_dialog(self):
        dlg = CustomWeaponDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._add_custom_weapon(dlg.get_data())

    def _custom_weapon_label(self, custom):
        return custom["label"]

    def _add_custom_weapon(self, data):
        custom = {"label": data["label"], "ammo": data["ammo"], "gun": data["gun"]}
        cur_mods = self._current_mods()
        # 自定义 buff 加成（射程/散布倍率）并入固化加成列表
        _buff = data.get("buff") or {}
        if _buff:
            _bg = float(_buff.get("gmmd", 1.0))
            _ba = float(_buff.get("gm", 1.0))
            if abs(_bg - 1.0) >= 1e-9 or abs(_ba - 1.0) >= 1e-9:
                cur_mods = list(cur_mods)
                cur_mods.append((_bg, _ba, _buff.get("name") or "自定义加成"))
        for item in self._custom_series:
            if item.get("custom") and item["custom"]["ammo"] == custom["ammo"] and item["custom"]["gun"] == custom["gun"] \
                    and item.get("mods") == cur_mods:
                return  # 同自定义炮弹且加成配置相同 → 不重复添加
        self._custom_series.append({"custom": custom, "label": self._custom_weapon_label(custom), "mods": cur_mods})
        self._refresh_side_panel()
        self._calculate_current()

    def _refresh_side_panel(self):
        # 清空按钮（保留最后的 stretch）
        while self.side_container_layout.count() > 1:
            item = self.side_container_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._side_buttons = []
        for i, item in enumerate(self._custom_series):
            color = self.COLOR_POOL[(i + 1) % len(self.COLOR_POOL)]
            mod_names = [str(m[2]) for m in (item.get("mods") or []) if len(m) > 2 and m[2]]
            lb = SideAmmoLabel(item['label'], mod_names, color)
            lb.setToolTip(f"点击移出显示：{item['label']}")
            lb.clicked.connect(lambda _idx=0, idx=i: self._on_side_button(idx))
            self.side_container_layout.insertWidget(self.side_container_layout.count() - 1, lb)
            self._side_buttons.append(lb)
        # 提示信息永久显示，不随是否有已添加炮弹而隐藏
        self.side_hint.setVisible(True)

    def _on_side_button(self, idx):
        """点击炮弹按钮 → 将该炮弹移出显示列。"""
        if idx < 0 or idx >= len(self._custom_series):
            return
        del self._custom_series[idx]
        self._refresh_side_panel()
        self._calculate_current()

    # ── 插件加成（射程 / 精度） ─────────────────────────
    MOD_BTN_STYLE = """
        QPushButton {
            background:#f7f7f7; border:1px solid #d0d0d0; border-radius:4px;
            padding:4px 7px; font-size:12px; color:#1a1a1a;
        }
        QPushButton:hover { background:#eef4fc; border-color:#0078d4; }
        QPushButton:checked { background:#dce9f7; border-color:#0078d4; color:#004578; }
    """

    def _load_mod_bonuses(self):
        # 清空旧按钮
        for _b in getattr(self, "_mod_buttons", []):
            try:
                _b["btn"].deleteLater()
            except Exception:
                pass
        while self.mods_grid.count():
            _it = self.mods_grid.takeAt(0)
            if _it.widget():
                _it.widget().deleteLater()
        self._mod_buttons = []
        self._mod_items = []
        ship_id = self.ship_cb.currentData()
        gun_key = self.gun_cb.currentData()
        # 当前火炮类型 → 加成键（主炮 GM / 副炮 GS / 次级主炮 GMS）
        kind, _ = self._split_gun_key(gun_key) if gun_key else ("main", "")
        range_key, acc_key = self._mod_keys_for_kind(kind)
        if ship_id:
            try:
                from services.database_service import get_db
                db = get_db()
                basic = db._conn.execute(
                    "SELECT shiptype, tier, group_status_key FROM ship_basic_info WHERE ship_id=? LIMIT 1", (ship_id,)
                ).fetchone()
                ship_type = basic["shiptype"] or "" if basic else ""
                ship_tier = int(basic["tier"] or 0) if basic else 0
                ship_group = basic["group_status_key"] or "" if basic else ""
                nat_row = db._conn.execute(
                    "SELECT nation FROM entity_registry WHERE entity_id=? LIMIT 1", (ship_id,)
                ).fetchone()
                ship_nation = nat_row["nation"] or "" if nat_row else ""
                for r in db._conn.execute(
                    "SELECT mod_id, name, slot, modifiers_json, ships_json, excludes_json, nations_json, shiptype_json, shiplevel_json, groups_json FROM modernization_basic_info WHERE slot>=0"
                ).fetchall():
                    mods = json.loads(r["modifiers_json"] or "{}")
                    if range_key not in mods and acc_key not in mods:
                        continue
                    if not self._mod_matches(r, ship_type, ship_tier, ship_nation, ship_group, ship_id):
                        continue
                    gmmd, gm = self._resolve_mod_bonus(mods, ship_type, range_key, acc_key)
                    if gmmd == 1.0 and gm == 1.0:
                        continue
                    self._mod_items.append({"mod_id": r["mod_id"], "slot": r["slot"], "gmmd": gmmd, "gm": gm})
                    self._add_mod_button(r["mod_id"], gmmd, gm, keys=(range_key, acc_key), slot=r["slot"])
                # 消耗品（侦察机）与战斗指令（含对应炮种射程、精度加成）
                self._load_special_bonuses(ship_id, db._conn, ship_type, kind)
                # 舰种技能中含射程/精度加成的技能
                self._load_skill_bonuses(ship_id, db._conn, ship_type, kind)
                # 辅助机组（友军提供的支援侦察机 scout）：无条件显示
                self._load_ally_support_bonus(ship_id, db._conn, ship_type, kind)
                self._ensure_mods_stretch()
            except Exception:
                pass
        self.mods_frame.setVisible(len(self._mod_buttons) > 0)

    @staticmethod
    def _mod_keys_for_kind(kind: str) -> tuple[str, str]:
        """按火炮类型返回 (射程加成键, 精度加成键)：主炮 GM / 副炮 GS / 次级主炮 GMS。"""
        if kind == "atba":
            return ("GSMaxDist", "GSIdealRadius")
        if kind == "sec":
            return ("GMSMaxDist", "GMSIdealRadius")
        return ("GMMaxDist", "GMIdealRadius")

    def _ensure_mods_stretch(self):
        """按钮全部添加后，在布局末尾放一个伸缩项：宽窗口按钮靠左，窄窗口出现横向滚动条。"""
        n = self.mods_grid.count()
        if n == 0 or self.mods_grid.itemAt(n - 1).spacerItem() is None:
            self.mods_grid.addStretch(1)

    def _add_mod_button(self, mod_id: str, gmmd: float, gm: float, kind: str = "modernization",
                        name: str = "", bonus_lines: list[str] | None = None,
                        icon_path: str = "", keys: tuple[str, str] | None = None,
                        slot: int | None = None):
        """主界面升级品按钮样式的加成按钮：图标 + 名称 + 加成文字。
        kind: modernization=升级品 / consumable=消耗品 / rage_mode=战斗指令 / skill=技能。
        keys: (射程键, 精度键)，用于生成升级品加成文字；消耗品/战斗指令自带 bonus_lines。
        名称统一显示在按钮上（升级品同消耗品/战斗指令），不再使用悬浮窗。"""
        from models.name_mapping import Mapping as NMM
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setStyleSheet(self.MOD_BTN_STYLE)
        if kind == "modernization":
            img = f":/resources/pictures/modernization/icon_modernization_{mod_id}.png"
            pix = QPixmap(img)
            if not pix.isNull():
                btn.setIcon(QIcon(pix.scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
                btn.setIconSize(QSize(26, 26))
        elif icon_path:
            pix = QPixmap(icon_path)
            if not pix.isNull():
                btn.setIcon(QIcon(pix.scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
                btn.setIconSize(QSize(26, 26))
        if bonus_lines is None:
            bonus_lines = []
            range_key, acc_key = keys or ("GMMaxDist", "GMIdealRadius")
            for key, val in ((range_key, gmmd), (acc_key, gm)):
                if val is None or abs(float(val) - 1.0) < 1e-9:
                    continue
                label = NMM.MODIFIER_MAP.get(key, key)
                fmt = NMM.format_modifier(key, float(val))
                if fmt:
                    bonus_lines.append(f"{label}: {fmt}")
        # 名称显示在按钮上（升级品/消耗品/战斗指令/技能一致）
        disp_name = (self._resolve_name("modernization", mod_id) or mod_id[:6]) if kind == "modernization" else (name or mod_id)
        title = disp_name
        if bonus_lines:
            title += "\n" + "\n".join(bonus_lines)
        btn.setText(title)
        # 名称已在按钮上，悬浮窗全部去掉
        # 最小宽度 = 内容完整宽度：图标与文字永不压缩截断，超出时由横向滚动条查看
        btn.setMinimumWidth(btn.sizeHint().width())
        btn.clicked.connect(lambda checked=False, _btn=btn, _slot=slot: self._on_mod_toggled(_btn, _slot))
        self.mods_grid.addWidget(btn)  # 单行排列，超宽时横向滚动
        self._mod_buttons.append({"btn": btn, "mod_id": mod_id, "gmmd": gmmd, "gm": gm,
                                  "kind": kind, "name": disp_name, "slot": slot})

    def _on_mod_toggled(self, btn, slot):
        """加成按钮勾选：升级品同一槽位互斥（只能勾选一个），随后重算。消耗品/战斗指令/技能无槽位不受限制。"""
        if slot is not None and btn.isChecked():
            for b in getattr(self, "_mod_buttons", []):
                if b["btn"] is not btn and b.get("slot") == slot and b["btn"].isChecked():
                    b["btn"].setChecked(False)
        self._calculate_current()

    def _resolve_mod_value(self, v, ship_type: str) -> float:
        """解析加成倍率：数值直接返回；dict 按舰船类型（缺省用 Battleship）。"""
        if isinstance(v, dict):
            return float(v.get(ship_type, v.get("Battleship", 1.0)))
        try:
            return float(v) if v is not None else 1.0
        except Exception:
            return 1.0

    @staticmethod
    def _rage_icon_path(rage_name: str) -> str:
        """IDS_DOCK_RAGE_MODE_TITLE_ATBA_FIREPOWER → :/.../rageMode_atba_firepower_preview_0.png"""
        import re as _re
        m = _re.search(r"TITLE_(.+)$", str(rage_name or "").upper())
        tag = m.group(1).lower() if m else ""
        return f":/resources/pictures/ragemode/rageMode_{tag}_preview_0.png" if tag else ""

    def _load_special_bonuses(self, ship_id: str, conn, ship_type: str, kind: str = "main"):
        """加载该船提供对应炮种射程/精度加成的消耗品（侦察机，仅主炮）与战斗指令（rage_mode）。"""
        from models.name_mapping import Mapping as NMM
        range_key, acc_key = self._mod_keys_for_kind(kind)
        # ── 侦察机消耗品：仅主炮显示（主炮射程 ×artilleryDistCoeff、主炮精度 ×GMIdealRadius）──
        if kind == "main":
            seen: set = set()
            for s in conn.execute(
                "SELECT consumable_id, config_key FROM ship_consumable_slots WHERE ship_id=? ORDER BY slot_index, item_index",
                (ship_id,)).fetchall():
                cid = s["consumable_id"]
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                cfg = conn.execute(
                    "SELECT * FROM consumable_configs WHERE consumable_id=? AND config_key=?",
                    (cid, s["config_key"])).fetchone()
                if not cfg:
                    cfg = conn.execute(
                        "SELECT * FROM consumable_configs WHERE consumable_id=? AND config_key='Default'",
                        (cid,)).fetchone()
                if not cfg:
                    continue
                try:
                    ej = json.loads(cfg["extra_json"] or "{}")
                except Exception:
                    continue
                ct = ej.get("consumableType") or cfg["consumable_type"] or ""
                if ct != "scout":
                    continue
                adc = self._resolve_mod_value(ej.get("artilleryDistCoeff"), ship_type)
                mods = ej.get("modifiers") or {}
                gm = self._resolve_mod_value(mods.get("GMIdealRadius"), ship_type) if isinstance(mods, dict) else 1.0
                if abs(adc - 1.0) < 1e-9 and abs(gm - 1.0) < 1e-9:
                    continue
                lines = []
                if abs(adc - 1.0) >= 1e-9:
                    lines.append(f"主炮射程: {NMM.format_modifier('GMMaxDist', adc)}")
                if abs(gm - 1.0) >= 1e-9:
                    lines.append(f"主炮炮弹的最大误差: {NMM.format_modifier('GMIdealRadius', gm)}")
                self._mod_items.append({"mod_id": cid, "gmmd": adc, "gm": gm, "kind": "consumable"})
                self._add_mod_button(cid, adc, gm, kind="consumable", name="侦察机", bonus_lines=lines,
                                     icon_path=f":/resources/pictures/consumables/consumable_{cid}_0.png")
        # ── 战斗指令（rage_mode）：对应炮种射程、精度 ──
        for rm in conn.execute(
            "SELECT rage_mode_name, modifiers_json FROM ship_rage_mode WHERE ship_id=?",
            (ship_id,)).fetchall():
            try:
                mods = json.loads(rm["modifiers_json"] or "{}")
            except Exception:
                continue
            gmmd = self._resolve_mod_value(mods.get(range_key), ship_type) if mods.get(range_key) is not None else 1.0
            gm = self._resolve_mod_value(mods.get(acc_key), ship_type) if mods.get(acc_key) is not None else 1.0
            if abs(gmmd - 1.0) < 1e-9 and abs(gm - 1.0) < 1e-9:
                continue
            lines = []
            for key, val in ((range_key, gmmd), (acc_key, gm)):
                if mods.get(key) is not None and abs(float(val) - 1.0) >= 1e-9:
                    fmt = NMM.format_modifier(key, float(val))
                    if fmt:
                        lines.append(f"{NMM.MODIFIER_MAP.get(key, key)}: {fmt}")
            rname = self._resolve_name("rage_mode", rm["rage_mode_name"]) or "战斗指令"
            self._mod_items.append({"mod_id": rm["rage_mode_name"] or f"rage_{ship_id}", "gmmd": gmmd, "gm": gm, "kind": "rage_mode"})
            self._add_mod_button(rm["rage_mode_name"] or f"rage_{ship_id}", gmmd, gm,
                                 kind="rage_mode", name=rname, bonus_lines=lines,
                                 icon_path=self._rage_icon_path(rm["rage_mode_name"]))

    # 敌方散布类键：为敌方战舰增加炮弹散布/误差（如「眼花缭乱」shootShift）。
    # 与当前炮种（主炮/副炮/中口径炮）无关，无论选择何种舰船/炮种均应正常显示词条。
    ENEMY_SPREAD_KEYS = ("shootShift", "shootShiftBatteryLastChanceCoeff")

    def _load_skill_bonuses(self, ship_id: str, conn, ship_type: str, kind: str = "main"):
        """加载该船舰种的「舰种技能」中影响当前炮种射程/精度的技能加成，
        以及为敌方战舰增加散布的词条（如「眼花缭乱」）。"""
        from services.skill_service import SkillService
        from models.name_mapping import Mapping as NMM
        range_key, acc_key = self._mod_keys_for_kind(kind)
        spread_keys = list(self.ENEMY_SPREAD_KEYS)
        svc = SkillService()
        ship_cn = svc.get_ship_type_cn(ship_type)
        if not ship_cn:
            return
        grid = svc.get_grid_skills(ship_cn, container_id="PCOL001_CommonCrewSkills", ship_type_en=ship_type)
        seen: set = set()
        for row in grid or []:
            for skill in row or []:
                if not skill:
                    continue
                sk = skill.get("skill_key") or ""
                if not sk or sk in seen:
                    continue
                seen.add(sk)
                mods = skill.get("modifiers") or {}
                if not isinstance(mods, dict):
                    mods = {}
                # 触发式技能（trigger_json.modifiers，如「敌众我寡」「眼花缭乱」）同样提供加成，
                # 合并后判断是否影响当前炮种或敌方散布
                trig = skill.get("trigger") or {}
                if isinstance(trig, dict):
                    tmods = trig.get("modifiers") or {}
                    if isinstance(tmods, dict):
                        merged = dict(tmods)
                        merged.update(mods)  # 直接 modifiers 优先
                        mods = merged
                has_spread = any(k in mods for k in spread_keys)
                if range_key not in mods and acc_key not in mods and not has_spread:
                    continue
                gmmd = self._resolve_mod_value(mods.get(range_key), ship_type) if range_key in mods else 1.0
                gm = self._resolve_mod_value(mods.get(acc_key), ship_type) if acc_key in mods else 1.0
                if abs(gmmd - 1.0) < 1e-9 and abs(gm - 1.0) < 1e-9 and not has_spread:
                    continue
                icon_name = skill.get("icon_name") or ""
                sname = ""
                if icon_name:
                    try:
                        r2 = conn.execute(
                            "SELECT lang_zh FROM name_mappings WHERE category='skill_title' AND key_name=? LIMIT 1",
                            (icon_name.lower(),)).fetchone()
                        if r2:
                            sname = r2["lang_zh"]
                    except Exception:
                        pass
                if not sname:
                    sname = sk
                lines = []
                for key, val in ((range_key, gmmd), (acc_key, gm)):
                    if mods.get(key) is not None and abs(float(val) - 1.0) >= 1e-9:
                        fmt = NMM.format_modifier(key, float(val))
                        if fmt:
                            lines.append(f"{NMM.MODIFIER_MAP.get(key, key)}: {fmt}")
                # 敌方散布词条：与炮种无关，始终显示其加成（数值按当前舰船解析，dict 类型不因选船丢失）
                for k in spread_keys:
                    if mods.get(k) is not None:
                        v = self._resolve_mod_value(mods.get(k), ship_type)
                        if abs(float(v) - 1.0) >= 1e-9:
                            fmt = NMM.format_modifier(k, float(v))
                            if fmt:
                                lines.append(f"{NMM.MODIFIER_MAP.get(k, k)}: {fmt}")
                self._mod_items.append({"mod_id": sk, "gmmd": gmmd, "gm": gm, "kind": "skill"})
                self._add_mod_button(sk, gmmd, gm, kind="skill", name=sname, bonus_lines=lines,
                                     icon_path=f":/resources/pictures/skills/{icon_name}.png" if icon_name else "")

    def _load_ally_support_bonus(self, ship_id: str, conn, ship_type: str, kind: str = "main"):
        """辅助机组（友军提供的支援侦察机 scout）射程/精度加成，无条件显示。

        按当前舰船实际携带的支援侦察机（ship_module_air_support.support_type='scout'）
        显示，按钮名直接采用该侦察机的飞机名（如 Curtiss SC-1）。
        由友军提供而非自身携带，因此不随当前所选舰船/炮种变化，始终显示为可勾选加成。
        多艘携带支援机组的船的支援型侦察机之间不能互相叠加 → 该 buff 固定只取一份。
        """
        from models.name_mapping import Mapping as NMM
        # 所属战舰状态为被禁用（group_status_key='disabled'）时不显示辅助机组
        st = conn.execute(
            "SELECT group_status_key FROM ship_basic_info WHERE ship_id=? LIMIT 1",
            (ship_id,)).fetchone()
        if st and (st["group_status_key"] or "") == "disabled":
            return
        # 该船携带的支援侦察机（可能有多个配置，去重）
        srows = conn.execute(
            "SELECT DISTINCT plane_name FROM ship_module_air_support "
            "WHERE ship_id=? AND support_type='scout'", (ship_id,)).fetchall()
        if not srows:
            return
        plane_id = srows[0]["plane_name"] or ""
        # 飞机显示名：name_mappings.plane（如 Curtiss SC-1），无则退回 plane_id
        sname = plane_id
        if plane_id:
            nm = conn.execute(
                "SELECT lang_zh FROM name_mappings WHERE category='plane' AND key_name=? LIMIT 1",
                (plane_id,)).fetchone()
            if nm and nm["lang_zh"]:
                sname = nm["lang_zh"]
        range_key, acc_key = self._mod_keys_for_kind(kind)
        row = conn.execute(
            "SELECT buff_json FROM consumable_buff WHERE buff_id='PCOM061_AirSupport_Scout' "
            "ORDER BY buff_level DESC LIMIT 1"
        ).fetchone()
        if not row:
            return
        try:
            mods = json.loads(row["buff_json"] or "{}")
        except Exception:
            return
        # 取当前炮种对应的射程/精度键（主炮 GM、副炮 GS、次级主炮 GMS）
        gmmd = self._resolve_mod_value(mods.get(range_key), ship_type) if range_key in mods else 1.0
        gm = self._resolve_mod_value(mods.get(acc_key), ship_type) if acc_key in mods else 1.0
        # 词条：显示该 buff 提供的全部有效加成（主炮/中口径），不论当前炮种
        lines = []
        for key in ("GMMaxDist", "GMIdealRadius", "GMSMaxDist", "GMSIdealRadius"):
            if mods.get(key) is None:
                continue
            val = self._resolve_mod_value(mods.get(key), ship_type)
            if abs(float(val) - 1.0) < 1e-9:
                continue
            fmt = NMM.format_modifier(key, float(val))
            if fmt:
                lines.append(f"{NMM.MODIFIER_MAP.get(key, key)}: {fmt}")
        if not lines:
            return
        # 固定 mod_id：多艘支援航母的侦察机 buff 不叠加，只此一份
        self._mod_items.append({"mod_id": f"ally_{plane_id}", "gmmd": gmmd, "gm": gm,
                                "kind": "ally_support"})
        self._add_mod_button(f"ally_{plane_id}", gmmd, gm, kind="ally_support",
                             name=sname or "支援侦察机", bonus_lines=lines,
                             icon_path=":/resources/pictures/ammo_types/ammo_airsupport_scout_scout_0.png")

    def _mod_matches(self, mod_row, ship_type, ship_tier, ship_nation, ship_group, ship_id):
        try:
            ships = json.loads(mod_row["ships_json"] or "[]")
            excludes = json.loads(mod_row["excludes_json"] or "[]")
            types = json.loads(mod_row["shiptype_json"] or "[]")
            levels = json.loads(mod_row["shiplevel_json"] or "[]")
            nations = json.loads(mod_row["nations_json"] or "[]")
            groups = json.loads(mod_row["groups_json"] or "[]")
        except Exception:
            return False
        # 可用/不可用规则与主界面（ship_presenter._build_config_bar）完全一致
        has_any = bool(ships or groups or nations or types or levels)
        if not has_any:
            return False
        if ship_id in excludes:
            return False
        if ships and not groups and not nations and not types and not levels:
            # ships 是唯一正面条件 → 排他
            return ship_id in ships
        if ships and ship_id in ships:
            # ships 包含该船 → 直接通过
            return True
        if types and ship_type not in types:
            return False
        if levels and ship_tier not in levels:
            return False
        if nations and ship_nation not in nations:
            return False
        if groups and ship_group not in groups:
            return False
        return True

    def _resolve_mod_bonus(self, modifiers, ship_type, range_key="GMMaxDist", acc_key="GMIdealRadius"):
        def _resolve(v):
            if isinstance(v, dict):
                return float(v.get(ship_type, v.get("Battleship", 1.0)))
            try:
                return float(v) if v is not None else 1.0
            except Exception:
                return 1.0
        return _resolve(modifiers.get(range_key)), _resolve(modifiers.get(acc_key))

    def _reset_mods(self):
        for _b in getattr(self, "_mod_buttons", []):
            _b["btn"].setChecked(False)
        self._calculate_current()

    def _compute_distances(self, max_range_km: float):
        """固定从 0 km 到火炮最大射程，按 0.01 km 步长采样（高精度曲线）。"""
        end = max_range_km if max_range_km > 0 else 20.0
        step = 0.01
        points = []
        cur = 0.0
        while cur <= end + 1e-9:
            points.append(round(cur, 3))
            cur = round(cur + step, 6)
        if not points:
            points = [round(0.0, 3)]
        return points

    @staticmethod
    def _effective_max_range(gun_row, mods=None) -> float:
        """计算火炮有效最大射程（km）= 基础射程 × 各加成倍率（含勾选的升级品/技能等）。"""
        g = dict(gun_row) if hasattr(gun_row, "keys") else (gun_row or {})
        mr = float(g.get("max_range") or 0.0)
        for _mod in (mods or []):
            mr *= float(_mod[0])
        return mr

    def _update_ellipse_slider_range(self, max_range_km):
        """散布射程滑条上限 = 火炮最大射程。"""
        new_max = int(round(max_range_km * 10))
        if new_max < 2:
            new_max = 2
        if self.ellipse_slider.maximum() != new_max:
            self.ellipse_slider.blockSignals(True)
            self.ellipse_slider.setRange(2, new_max)
            if self.ellipse_slider.value() > new_max:
                self.ellipse_slider.setValue(max(2, new_max // 2))
            self.ellipse_slider.blockSignals(False)
            self._on_ellipse_slider()

    def _current_mods(self):
        """返回当前勾选加成（升级品/消耗品/战斗指令/技能）的 [(gmmd, gm, 来源名)] 列表（添加炮弹时固化用）。"""
        return [(float(b["gmmd"]), float(b["gm"]), b.get("name") or "")
                for b in getattr(self, "_mod_buttons", []) if b["btn"].isChecked()]

    def _compute_rows_for_weapon(self, gun_row, ammo_row, mods=None):
        from services.ballistics_service import BallisticsCalculator
        if not gun_row or not ammo_row:
            return []
        gun_row = dict(gun_row)
        ammo_row = dict(ammo_row)

        mass = float(ammo_row.get("bullet_mass") or 0.0)
        caliber = float(ammo_row.get("bullet_diameter") or 0.0)
        air_drag = float(ammo_row.get("bullet_air_drag") or 0.0)
        velocity = float(ammo_row.get("bullet_speed") or 0.0)
        krupp = float(ammo_row.get("bullet_krupp") or 0.0)
        if mass <= 0 or caliber <= 0 or velocity <= 0:
            return []

        max_range_km = float(gun_row.get("max_range") or 10.0)
        disp_coeff = 1.0
        if mods is None:
            # 未固化（如筛选器当前预览）：用当前勾选状态
            mods = self._current_mods()
        for _mod in mods:
            max_range_km *= float(_mod[0])
            disp_coeff *= float(_mod[1])
        min_radius = float(gun_row.get("min_radius") or 1.0)
        ideal_radius = float(gun_row.get("ideal_radius") or 0.0)
        ideal_distance = float(gun_row.get("ideal_distance") or 1.0)
        radius_zero = float(gun_row.get("radius_zero") or 0.0)
        radius_delim = float(gun_row.get("radius_delim") or 0.0)
        radius_max = float(gun_row.get("radius_max") or 0.0)
        delim = float(gun_row.get("delim") or 0.5)

        td = (ideal_radius * delim / min_radius) if min_radius > 0 and ideal_radius > 0 else 0.0
        ha = (ideal_radius - min_radius) / (ideal_distance / 1000.0) if ideal_distance > 0 and ideal_radius > min_radius else 0.0
        hb = min_radius * 30.0
        vd = 0.5 if delim <= 0 else delim
        params = {
            "td": td,
            "ha": ha,
            "hb": hb,
            "vd": vd,
            "vrz": radius_zero,
            "vrd": radius_delim,
            "vrm": radius_max,
            "dispCoeff": disp_coeff,
        }

        self._last_sigma = float(gun_row.get("sigma") or 1.0)
        _norm_override = gun_row.get("norm_angle")
        self._last_norm_angle = float(_norm_override) if _norm_override else BallisticsCalculator.get_normalization_angle(caliber)

        # HE / SAP(CS) 使用其特有固定穿深，不参与 V3 弹道穿深计算
        ammo_type = (ammo_row.get("ammo_type") or "").upper()
        fixed_pen = None
        if ammo_type == "HE":
            fixed_pen = float(ammo_row.get("alpha_piercing_he") or 0.0) or (caliber * 1000.0 / 6.0)
        elif ammo_type == "CS":
            fixed_pen = float(ammo_row.get("alpha_piercing_cs") or 0.0)

        # 弹道模拟仍用于飞行时间 / 落弹角（与穿深类型无关）
        ballistics = BallisticsCalculator().calculate_full_ballistics(mass, caliber, air_drag, velocity, krupp)

        # 散布射程滑条上限 = 火炮最大射程（含插件加成）
        self._update_ellipse_slider_range(max_range_km)
        target_distances = self._compute_distances(max_range_km)

        rows = []
        for distance in target_distances:
            horiz = BallisticsCalculator.calc_horizontal_dispersion(distance, params)
            vert = BallisticsCalculator.calc_vertical_dispersion(horiz, distance, max_range_km, params, 0.0, 0)
            area = BallisticsCalculator.calc_dispersion_area(horiz, vert)
            pt = BallisticsCalculator.interpolate_at_distance(ballistics, distance)
            impact = float(pt["impact_angle_deg"])
            fly = float(pt["fly_time"])
            if fixed_pen:
                pen = fixed_pen
            else:
                v_imp = float(pt["velocity"])
                pen_abs = BallisticsCalculator.calc_v3_penetration(krupp, mass, v_imp, caliber)
                pen = BallisticsCalculator.calc_vertical_effective_pen(pen_abs, impact, self._last_norm_angle)
            # 散布公式文字（横向 / 纵向），用于散布椭圆标签的“炮弹名后”说明
            if td > 0 and distance < td:
                h_expr = f"{distance:.1f}×{(td * ha + hb) / td:.2f}"
            else:
                h_expr = f"{distance:.1f}×{ha:.2f}+{hb:.1f}"
            if disp_coeff != 1.0:
                h_expr += f"×{disp_coeff:.2f}"
            _delim_km = vd * max_range_km
            if distance < _delim_km:
                _vc = radius_zero + (radius_delim - radius_zero) * (distance / _delim_km) if _delim_km else radius_zero
            else:
                _vc = radius_delim + (radius_max - radius_delim) * ((distance - _delim_km) / (max_range_km - _delim_km)) if (max_range_km - _delim_km) else radius_delim
            formula = f"横={h_expr}；纵=横×{_vc:.3f}"
            # 存全精度（悬浮提示已自行格式化为 2 位小数）；不再对 fly/impact 四舍五入，
            # 否则曲线被量化为 0.1s/0.1° 的阶梯状（锐角）
            rows.append((distance, horiz, vert, area, fly, pen, impact, formula))
        return rows

    def _build_curve_chart(self, rows, compare_series=None):
        if not rows and not compare_series:
            self.chart_label.setText("穿深曲线：无可用数据")
            return
        try:
            import matplotlib
            matplotlib.use("Qt5Agg")
            matplotlib.rcParams["font.sans-serif"] = [
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "WenQuanYi Zen Hei",
                "DejaVu Sans",
            ]
            matplotlib.rcParams["axes.unicode_minus"] = False
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        except Exception as exc:
            self.chart_label.setText(f"穿深曲线：matplotlib 不可用（{exc}）")
            return

        for i in reversed(range(self.chart_layout.count())):
            w = self.chart_layout.itemAt(i).widget()
            if w is not None and w is not self.chart_label:
                self.chart_layout.removeWidget(w)
                w.deleteLater()

        figure = Figure(figsize=(7, 3.6), dpi=100)
        ax = figure.add_subplot(111)
        color_pool = self.COLOR_POOL

        meta = []
        if compare_series:
            for idx, series in enumerate(compare_series):
                series_rows = series.get("rows") or []
                if not series_rows:
                    continue
                distances = [float(r[0]) for r in series_rows]
                penetrations = [float(r[5]) for r in series_rows]
                color = series.get("color") or color_pool[idx % len(color_pool)]
                ax.plot(distances, penetrations, color=color, linewidth=2, label=series.get("label") or f"弹药{idx + 1}")
                meta.append((series.get("label") or f"弹药{idx + 1}", distances, penetrations, color))
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8)
            figure.subplots_adjust(right=0.78)
        else:
            distances = [float(r[0]) for r in rows]
            penetrations = [float(r[5]) for r in rows]
            ax.plot(distances, penetrations, color=color_pool[0], linewidth=2)
            ax.scatter(distances[0], penetrations[0], color="#3fa34d", s=28)
            ax.scatter(distances[-1], penetrations[-1], color="#ff7a45", s=28)
            meta.append(("穿深", distances, penetrations, color_pool[0]))

        ax.set_title("穿深曲线")
        ax.set_xlabel("距离 (km)")
        ax.set_ylabel("穿深 (mm)")
        ax.grid(True, alpha=0.25)
        canvas = FigureCanvasQTAgg(figure)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chart_layout.addWidget(canvas)
        self._attach_hover_legend(ax, figure, canvas, meta, "mm")
        point_count = len(rows) if rows else 0
        if compare_series:
            count = sum(1 for s in compare_series if s.get("rows"))
            self.chart_label.setText(f"穿深曲线：{count} 条弹种曲线，对比样本点 {point_count}")
        else:
            self.chart_label.setText(f"穿深曲线：{point_count} 个样本点")

    def _build_flytime_chart(self, rows, compare_series=None):
        if not rows and not compare_series:
            self.flytime_label.setText("飞行时间曲线：无可用数据")
            return
        try:
            import matplotlib
            matplotlib.use("Qt5Agg")
            matplotlib.rcParams["font.sans-serif"] = [
                "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans",
            ]
            matplotlib.rcParams["axes.unicode_minus"] = False
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        except Exception as exc:
            self.flytime_label.setText(f"飞行时间曲线：matplotlib 不可用（{exc}）")
            return

        for i in reversed(range(self.flytime_layout.count())):
            w = self.flytime_layout.itemAt(i).widget()
            if w is not None and w is not self.flytime_label:
                self.flytime_layout.removeWidget(w)
                w.deleteLater()

        figure = Figure(figsize=(7, 3.6), dpi=100)
        ax = figure.add_subplot(111)
        color_pool = self.COLOR_POOL
        meta = []
        if compare_series:
            for idx, series in enumerate(compare_series):
                series_rows = series.get("rows") or []
                if not series_rows:
                    continue
                distances = [float(r[0]) for r in series_rows]
                times = [float(r[4]) for r in series_rows]
                color = series.get("color") or color_pool[idx % len(color_pool)]
                ax.plot(distances, times, color=color, linewidth=2, label=series.get("label") or f"弹药{idx + 1}")
                meta.append((series.get("label") or f"弹药{idx + 1}", distances, times, color))
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8)
            figure.subplots_adjust(right=0.78)
        else:
            distances = [float(r[0]) for r in rows]
            times = [float(r[4]) for r in rows]
            ax.plot(distances, times, color=color_pool[0], linewidth=2)
            ax.scatter(distances[0], times[0], color="#3fa34d", s=28)
            ax.scatter(distances[-1], times[-1], color="#ff7a45", s=28)
            meta.append(("飞行时间", distances, times, color_pool[0]))

        ax.set_title("飞行时间曲线")
        ax.set_xlabel("距离 (km)")
        ax.set_ylabel("飞行时间 (s)")
        ax.grid(True, alpha=0.25)
        canvas = FigureCanvasQTAgg(figure)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.flytime_layout.addWidget(canvas)
        self._attach_hover_legend(ax, figure, canvas, meta, "s")
        self.flytime_label.setText(f"飞行时间曲线：{len(rows) if rows else 0} 个样本点")

    def _build_metric_chart(self, metric_key, rows, compare_series=None):
        spec = self._metric_tab_map.get(metric_key)
        if spec is None:
            return
        layout = spec["layout"]
        label_w = spec["label"]
        title = spec["title"]
        ylabel = spec["ylabel"]
        idx = spec["idx"]
        if not rows and not compare_series:
            label_w.setText(f"{title}曲线：无可用数据")
            return
        try:
            import matplotlib
            matplotlib.use("Qt5Agg")
            matplotlib.rcParams["font.sans-serif"] = [
                "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans",
            ]
            matplotlib.rcParams["axes.unicode_minus"] = False
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        except Exception as exc:
            label_w.setText(f"{title}曲线：matplotlib 不可用（{exc}）")
            return

        for i in reversed(range(layout.count())):
            w = layout.itemAt(i).widget()
            if w is not None and w is not label_w:
                layout.removeWidget(w)
                w.deleteLater()

        figure = Figure(figsize=(7, 3.6), dpi=100)
        ax = figure.add_subplot(111)
        color_pool = self.COLOR_POOL
        meta = []
        if compare_series:
            for si, series in enumerate(compare_series):
                srows = series.get("rows") or []
                if not srows:
                    continue
                d = [float(r[0]) for r in srows]
                y = [float(r[idx]) for r in srows]
                color = series.get("color") or color_pool[si % len(color_pool)]
                ax.plot(d, y, color=color, linewidth=2, label=series.get("label") or f"弹药{si + 1}")
                meta.append((series.get("label") or f"弹药{si + 1}", d, y, color))
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8)
            figure.subplots_adjust(right=0.78)
        else:
            d = [float(r[0]) for r in rows]
            y = [float(r[idx]) for r in rows]
            ax.plot(d, y, color=color_pool[0], linewidth=2)
            ax.scatter(d[0], y[0], color="#3fa34d", s=28)
            ax.scatter(d[-1], y[-1], color="#ff7a45", s=28)
            meta.append((title, d, y, color_pool[0]))
        ax.set_title(f"{title}曲线")
        ax.set_xlabel("距离 (km)")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
        canvas = FigureCanvasQTAgg(figure)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(canvas)
        _units = {"angle": "°"}
        self._attach_hover_legend(ax, figure, canvas, meta, _units.get(metric_key, ""))
        label_w.setText(f"{title}曲线：{len(rows) if rows else 0} 个样本点")

    def _attach_hover_legend(self, ax, figure, canvas, series_meta, unit=""):
        """浩舰式悬浮：鼠标移到曲线上时，显示当前射程及各炮弹在该射程的对应值。

        series_meta: list[(label, xs, ys, color)]，xs 为距离(km)列表，ys 为对应值。
        unit: y 值单位后缀（如 mm / s / °），为空则不显示。
        附一根竖向参考线 + 悬浮文本框。
        """
        annot = ax.annotate(
            "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc="#ffffff", ec="#999999", alpha=0.92),
            fontsize=8, zorder=10,
        )
        annot.set_visible(False)
        vline = ax.axvline(0, color="#666666", linestyle="--", linewidth=0.8, alpha=0.0)
        _state = {"last_key": None}

        def _on_hover(event):
            if event.inaxes is not ax or event.xdata is None:
                if annot.get_visible():
                    annot.set_visible(False)
                    vline.set_alpha(0.0)
                    canvas.draw_idle()
                return
            x = float(event.xdata)
            lines = []
            ref_x = None
            key = []
            for label, xs, ys, _c in series_meta:
                if not xs:
                    continue
                # 鼠标射程超出该炮弹最大射程 → 不显示该炮弹信息（正确规则：超出射程不显示）
                if x > xs[-1]:
                    continue
                i = min(range(len(xs)), key=lambda k: abs(xs[k] - x))
                key.append(i)
                lines.append(f"{label}: {ys[i]:.2f} {unit}" if unit else f"{label}: {ys[i]:.2f}")
                if ref_x is None:
                    ref_x = xs[i]
            if ref_x is None:
                if annot.get_visible():
                    annot.set_visible(False)
                    vline.set_alpha(0.0)
                    canvas.draw_idle()
                return
            # 最近数据点未变化时跳过重绘，避免鼠标移动卡顿
            if tuple(key) == _state["last_key"] and annot.get_visible():
                return
            _state["last_key"] = tuple(key)
            annot.set_text("射程: %.2f km\n%s" % (ref_x, "\n".join(lines)))
            annot.xy = (x, event.ydata)
            annot.set_visible(True)
            vline.set_xdata([ref_x, ref_x])
            vline.set_alpha(0.4)
            canvas.draw_idle()

        canvas.mpl_connect("motion_notify_event", _on_hover)

    def _compute_rows(self):
        gun_row, ammo_row, _ = self._get_selected_weapon()
        return self._compute_rows_for_weapon(gun_row, ammo_row)

    def _calculate_current(self):
        self._ensure_valid_current_selection()
        try:
            # 显示内容 = 左侧已添加的炮弹（不再默认显示筛选器当前选中的炮弹）
            compare_series = []
            max_range_global = 0.0
            for i, item in enumerate(self._custom_series):
                sigma = 1.0
                if "custom" in item:
                    srows = self._compute_rows_for_weapon(item["custom"]["gun"], item["custom"]["ammo"], item.get("mods"))
                    sigma = float(item["custom"]["gun"].get("sigma") or 1.0)
                    mr = self._effective_max_range(item["custom"]["gun"], item.get("mods"))
                else:
                    gun_row, _, srows = self._load_weapon_for(item["ship_id"], item["gun_key"], item["ammo_id"], item.get("mods"))
                    if gun_row:
                        sigma = float(dict(gun_row).get("sigma") or 1.0)
                        mr = self._effective_max_range(gun_row, item.get("mods"))
                    else:
                        mr = 0.0
                if srows:
                    if mr > max_range_global:
                        max_range_global = mr
                    compare_series.append({
                        "label": item["label"],
                        "rows": srows,
                        "color": self.COLOR_POOL[(i + 1) % len(self.COLOR_POOL)],
                        "sigma": sigma,
                    })
            rows = compare_series[0]["rows"] if compare_series else []
            self._last_rows = rows
            self._last_compare_series = compare_series

            if not rows:
                self.chart_label.setText("穿深曲线：暂无已添加炮弹")
                self._set_ellipse_text("当前设定射程：—", "散布椭圆：暂无已添加炮弹")
                self.flytime_label.setText("飞行时间曲线：暂无已添加炮弹")
                for spec in self._metric_tabs:
                    spec["label"].setText(f"{spec['title']}曲线：暂无已添加炮弹")
                return

            # 散布椭圆最大可设定射程 = 当前显示炮弹中射程最远者（含加成）
            if max_range_global > 0:
                self._update_ellipse_slider_range(max_range_global)

            self._build_curve_chart(rows, compare_series)
            self._build_flytime_chart(rows, compare_series)
            self._build_metric_chart("angle", rows, compare_series)
            self._update_dispersion_ellipse()
        except Exception as exc:
            self._last_rows = []
            self.chart_label.setText(f"穿深曲线：计算失败（{exc}）")
            self._set_error(f"计算失败: {exc}")

    # ── 散布椭圆图 ──────────────────────────────────────
    def _set_ellipse_text(self, range_text: str, info_text: str):
        """更新散布信息区：左侧“当前设定射程” + 右侧炮弹信息（每炮弹一行）。"""
        self.ellipse_range_label.setText(range_text)
        self.ellipse_info_label.setText(info_text)

    def _update_dispersion_ellipse(self):
        if not self._last_rows:
            self._set_ellipse_text("当前设定射程：—", "散布椭圆：无可用数据")
            return
        self._build_dispersion_ellipse()

    def _build_dispersion_ellipse(self):
        series_list = getattr(self, "_last_compare_series", None) or []
        if not series_list:
            if not self._last_rows:
                self._set_ellipse_text("当前设定射程：—", "散布椭圆：无可用数据")
                return
            series_list = [{
                "label": "炮弹",
                "rows": self._last_rows,
                "color": self.COLOR_POOL[0],
                "sigma": getattr(self, "_last_sigma", 1.0) or 1.0,
            }]
        try:
            import matplotlib
            matplotlib.use("Qt5Agg")
            matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.patches import Ellipse
        except Exception as exc:
            self._set_ellipse_text("当前设定射程：—", f"散布椭圆：matplotlib 不可用（{exc}）")
            return

        for i in reversed(range(self.ellipse_layout.count())):
            w = self.ellipse_layout.itemAt(i).widget()
            if w is not None and w is not self.ellipse_label:
                self.ellipse_layout.removeWidget(w)
                w.deleteLater()

        from services.ballistics_service import BallisticsCalculator
        target_dist = self._ellipse_dist_km()
        count = self._scatter_value()

        figure = Figure(figsize=(5.5, 4.4), dpi=100)
        ax = figure.add_subplot(111)
        ax.set_aspect("equal")
        max_lateral = 0.0
        max_long = 0.0
        info_parts = []
        shown_dist = target_dist
        for idx, series in enumerate(series_list):
            rows = series.get("rows") or []
            if not rows:
                continue
            best_row = next((r for r in rows if abs(float(r[0]) - target_dist) <= 0.0001), None)
            if best_row is None:
                best_row = min(rows, key=lambda r: abs(float(r[0]) - target_dist))
            dist = float(best_row[0])
            shown_dist = dist
            lateral = float(best_row[1])        # 横向 = 水平散布（=最大散布半径，100% 弹丸落点在此椭圆内）
            # 纵向 = 垂直散布（垂直面命中椭圆）：随距离单调递增，最大射程处椭圆最大。
            # 不投影到水面(vert/sin 落弹角)——近距落弹角→0 时纵向会爆炸，导致中间距离椭圆反超最远（非单调）
            longitudinal = float(best_row[2])
            if self.ellipse_unlocked_cb.isChecked():
                # 未锁定目标 → 散布椭圆 ×2（莱斯塔 wiki 明确规则）
                lateral *= 2.0
                longitudinal *= 2.0
            sigma = float(series.get("sigma") or getattr(self, "_last_sigma", 1.0) or 1.0)
            color = series.get("color") or self.COLOR_POOL[idx % len(self.COLOR_POOL)]
            label = series.get("label") or f"炮弹{idx + 1}"
            points = BallisticsCalculator.gaussian_dispersion_points(sigma, count, seed=idx + 1)
            # 椭圆：水平(x) = 横向，垂直(y) = 纵向（每炮弹一个，分色显示）
            ax.add_patch(Ellipse(
                (0, 0), width=lateral * 2, height=longitudinal * 2,
                facecolor=color, alpha=0.10, edgecolor=color, linewidth=2, label=label,
            ))
            xs = [p[1] * lateral for p in points]
            ys = [p[0] * longitudinal for p in points]
            ax.scatter(xs, ys, s=7, alpha=0.4, color=color, linewidths=0)
            max_lateral = max(max_lateral, lateral)
            max_long = max(max_long, longitudinal)
            info_parts.append(
                f"{label}: 横向半径: {lateral:.0f} m * 纵向半径: {longitudinal:.0f} m; sigma: {sigma:.2f}"
            )

        if not info_parts:
            self._set_ellipse_text("当前设定射程：—", "散布椭圆：无可用数据")
            return
        ax.plot([0], [0], marker="+", color="#d43a00", markersize=10)
        ax.axhline(0, color="#cccccc", linewidth=0.8)
        ax.axvline(0, color="#cccccc", linewidth=0.8)
        margin = max(max_long, max_lateral) * 1.15 + 5
        ax.set_xlim(-margin, margin)
        ax.set_ylim(-margin, margin)
        _lock_note = " ×2" if self.ellipse_unlocked_cb.isChecked() else ""
        ax.set_title(f"{shown_dist:.1f} km 命中散布{_lock_note}（{count} 发模拟/弹，σ 越大越密集）")
        ax.set_xlabel("横向半径 (m)")
        ax.set_ylabel("纵向半径 (m)")
        ax.grid(True, alpha=0.25)
        if len(series_list) > 1:
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8)
            figure.subplots_adjust(right=0.76)

        canvas = FigureCanvasQTAgg(figure)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ellipse_layout.addWidget(canvas)
        self._set_ellipse_text(f"当前设定射程：{shown_dist:.1f} km", "\n".join(info_parts))

    def center_on_screen(self, relative_to=None) -> None:
        """把窗口居中到指定窗口（默认主屏），复刻 AssetsBinViewer.center_on_screen。"""
        from PySide6.QtGui import QGuiApplication
        if relative_to is not None and relative_to.isVisible():
            geo = relative_to.frameGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(max(x, 0), max(y, 0))
            return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - self.width()) // 2,
                      geo.y() + (geo.height() - self.height()) // 2)

    def _save_geometry(self):
        try:
            self._settings.setValue("win_geometry", self.saveGeometry())
            self._settings.setValue("win_state", self.saveState())
        except Exception:
            pass

    def _restore_geometry(self) -> bool:
        """恢复上次窗口位置/大小；成功返回 True。"""
        try:
            geo = self._settings.value("win_geometry")
            if geo:
                self.restoreGeometry(geo)
                return True
        except Exception:
            pass
        return False

    def closeEvent(self, event):
        try:
            self._save_geometry()
        except Exception:
            pass
        super().closeEvent(event)
