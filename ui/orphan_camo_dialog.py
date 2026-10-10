"""
OrphanCamoDialog —— 「独立涂装」调试工具（源码/调试模式专用）。

列出客户端里存在、但**没有被任何舰船收纳**的皮肤类外观（Exterior）：
它们的 name/index 不在任何舰船的 `permoflages` 里，因此 3D 查看器的涂装切换器
不会显示它们（详见 CamoService.list_orphan_skins）。

带自带模型（hullConfig）**且几何已随包**的条目可在 3D 查看器中预览（无归属舰船 ⇒
通常只有船体）；若客户端根本没随包该几何（如尚未发布的皮肤，只有 Exterior JSON 与
材质定义），列表会标 ⛔ 并禁用预览，避免直接报「未找到 .geometry」。
发布版不挂入口（「工具」菜单项按 is_debug_build() 隐藏）。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from app.signals import bus
from utils.theme import theme
from utils.threading_utils import run_async
from utils.path_utils import get_data_dir


#: species 过滤下拉项：显示文本 → 允许的 species（None = 全部）
_SPECIES_FILTERS: list[tuple[str, tuple[str, ...] | None]] = [
    ("全部类型", None),
    ("仅皮肤 (Skin/MSkin)", ("skin", "mskin")),
    ("永久涂装 (Permoflage)", ("permoflage",)),
    ("通用涂装 (Camouflage)", ("camouflage",)),
]


class OrphanCamoDialog(QDialog):
    """独立涂装列表（无舰船归属的 Exterior）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("独立涂装（未被任何舰船收纳）")
        self.resize(980, 620)
        self.setMinimumSize(720, 460)

        self._all: list = []
        self._loading = False
        self._viewer = None

        self._build_ui()
        theme.bind(self, "QDialog { background: @panel_bg@; }")
        self._reload()

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        hint = QLabel(
            "这些外观存在于客户端，但未被任何舰船的 permoflages 收纳（未发布/预留/无归属），"
            "因此普通涂装切换器里看不到。")
        hint.setWordWrap(True)
        theme.bind(hint, "color: @text_muted@; font-size: 11px; background: transparent;")
        root.addWidget(hint)

        # ── 过滤行 ──
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 搜索名称 / 索引...")
        self.search.setClearButtonEnabled(True)
        theme.bind(self.search, """
            QLineEdit { padding: 4px 6px; border: 1px solid @border@; border-radius: 3px;
                        background: @input_bg@; color: @text@; font-size: 11px; }
            QLineEdit:focus { border-color: #0078d4; }
        """)
        bar.addWidget(self.search, 1)

        self.cb_species = QComboBox()
        for label, _ in _SPECIES_FILTERS:
            self.cb_species.addItem(label)
        theme.bind(self.cb_species,
                   "QComboBox { padding: 3px 6px; border: 1px solid @border@; border-radius: 3px;"
                   " background: @input_bg@; color: @text@; font-size: 11px; }")
        bar.addWidget(self.cb_species)

        self.cb_model_only = QCheckBox("只看自带模型")
        self.cb_model_only.setToolTip("只显示带 hullConfig 的条目（几何未随包的会标 ⛔）")
        theme.bind(self.cb_model_only, "QCheckBox { color: @text@; font-size: 11px; }")
        bar.addWidget(self.cb_model_only)

        self.btn_refresh = QPushButton("↻ 重新扫描")
        theme.bind(self.btn_refresh, """
            QPushButton { background: @panel_alt@; border: 1px solid @border@; border-radius: 3px;
                          padding: 4px 10px; font-size: 11px; color: @text@; }
            QPushButton:hover { border-color: #0078d4; }
            QPushButton:disabled { color: @text_hint@; }
        """)
        bar.addWidget(self.btn_refresh)
        root.addLayout(bar)

        # ── 列表 + 详情 ──
        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setIconSize(QSize(36, 36))
        theme.bind(self.list, """
            QListWidget { background: @panel_bg@; border: 1px solid @border@;
                          border-radius: 4px; color: @text@; font-size: 12px; }
            QListWidget::item { padding: 3px 6px; }
            QListWidget::item:selected { background: @selected_bg@; color: @selected_fg@; }
            QListWidget::item:hover { background: @hover_bg@; color: @text@; }
        """)
        split.addWidget(self.list)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.preview.setVisible(False)
        theme.bind(self.preview,
                   "QLabel { background: @panel_alt@; border: 1px solid @border_soft@;"
                   " border-radius: 4px; }")
        rl.addWidget(self.preview)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        theme.bind(self.detail, """
            QTextBrowser { background: @panel_bg@; border: 1px solid @border@;
                           border-radius: 4px; color: @text@; font-size: 12px; }
        """)
        rl.addWidget(self.detail, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        # ── 底部 ──
        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.count = QLabel("")
        theme.bind(self.count, "color: @text_muted@; font-size: 11px; background: transparent;")
        foot.addWidget(self.count, 1)
        self.btn_view = QPushButton("🖼 在 3D 查看器中查看（仅船体）")
        self.btn_view.setToolTip("无归属舰船 ⇒ 只按皮肤自带 hullConfig 加载船体，挂载可能缺失")
        self.btn_view.setEnabled(False)
        theme.bind(self.btn_view, """
            QPushButton { background: @panel_alt@; border: 1px solid @border@; border-radius: 3px;
                          padding: 5px 12px; font-size: 11px; color: @text@; }
            QPushButton:hover { border-color: #0078d4; }
            QPushButton:disabled { color: @text_hint@; }
        """)
        foot.addWidget(self.btn_view)
        root.addLayout(foot)

        # ── 信号 ──
        self.search.textChanged.connect(self._apply_filter)
        self.cb_species.currentIndexChanged.connect(self._apply_filter)
        self.cb_model_only.toggled.connect(self._apply_filter)
        self.btn_refresh.clicked.connect(self._reload)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.btn_view.clicked.connect(self._on_view_3d)

    # ── 数据加载 ──────────────────────────────────────────

    def _camo_service(self):
        from services.camo_service import CamoService
        from services.geometry_service import GeometryService
        svc = GeometryService.instance()
        cache = None
        try:
            cache = svc._get_assets_cache()
        except Exception:  # noqa: BLE001
            cache = None
        bin_folder = ""
        try:
            from app.application import app as app_ctx
            bin_folder = app_ctx.ctx.bin_folder or ""
        except Exception:  # noqa: BLE001
            pass
        return CamoService(extractor=svc._get_extractor(), cache=cache, bin_folder=bin_folder)

    def _reload(self):
        if self._loading:
            return
        self._loading = True
        self.btn_refresh.setEnabled(False)
        self.count.setText("正在扫描独立涂装...")
        run_async(self._collect, on_finished=self._on_collected,
                  on_error=self._on_collect_error)

    def _collect(self):
        """后台线程：扫描未被任何舰船收纳的皮肤类 Exterior。"""
        return self._camo_service().list_orphan_skins()

    def _on_collected(self, infos):
        self._loading = False
        self.btn_refresh.setEnabled(True)
        self._all = list(infos or [])
        self._apply_filter()

    def _on_collect_error(self, err):
        self._loading = False
        self.btn_refresh.setEnabled(True)
        self.count.setText(f"扫描失败：{err}")
        bus.log_message.emit(f"❌ 独立涂装扫描失败: {err}")

    # ── 过滤与显示 ────────────────────────────────────────

    def _species_allowed(self) -> tuple[str, ...] | None:
        idx = self.cb_species.currentIndex()
        if 0 <= idx < len(_SPECIES_FILTERS):
            return _SPECIES_FILTERS[idx][1]
        return None

    def _apply_filter(self, *args):
        kw = self.search.text().strip().lower()
        allowed = self._species_allowed()
        model_only = self.cb_model_only.isChecked()

        self.list.clear()
        shown = 0
        for s in self._all:
            if allowed is not None and (s.species or "").lower() not in allowed:
                continue
            if model_only and not s.model_folder:
                continue
            if kw:
                hay = f"{s.display_name} {s.ext_index} {s.raw_name} {s.species}".lower()
                if kw not in hay:
                    continue
            item = QListWidgetItem(self._item_text(s))
            item.setData(Qt.UserRole, s)
            icon = self._icon(s)
            if not icon.isNull():
                item.setIcon(icon)
            item.setToolTip(f"{s.ext_index}｜{s.species}｜{s.origin}")
            self.list.addItem(item)
            shown += 1
        total = len(self._all)
        self.count.setText(f"独立涂装 {shown} / {total} 项"
                           + ("（扫描中...）" if self._loading else ""))
        if shown:
            self.list.setCurrentRow(0)
        else:
            self.detail.clear()
            self.preview.setVisible(False)
            self.btn_view.setEnabled(False)

    @staticmethod
    def _item_text(s) -> str:
        name = s.display_name or s.raw_name
        tag = "模型" if s.origin == "model" else "材质"
        hidden = " ·隐藏" if s.hidden else ""
        no_model = " ·⛔无模型" if s.geometry_present is False else ""
        return f"{name}   〔{s.ext_index or s.raw_name}｜{s.species}｜{tag}{hidden}{no_model}〕"

    def _icon(self, s) -> QIcon:
        path = getattr(s, "icon_path", "") or ""
        if not path:
            return QIcon()
        p = get_data_dir() / path
        if not p.exists():
            return QIcon()
        pix = QPixmap(str(p))
        return QIcon(pix) if not pix.isNull() else QIcon()

    def _current_scheme(self):
        cur = self.list.currentItem()
        return cur.data(Qt.UserRole) if cur is not None else None

    @staticmethod
    def _can_preview(s) -> bool:
        """能否 3D 预览：必须自带船体 hullConfig 且几何随包。"""
        return bool(s is not None and s.hull_model and s.model_folder
                    and s.geometry_present is not False)

    def _update_view_button(self, s):
        ok = self._can_preview(s)
        self.btn_view.setEnabled(ok)
        if s is None:
            self.btn_view.setToolTip("")
        elif not s.hull_model:
            self.btn_view.setToolTip("该涂装未提供船体 hullConfig（仅挂载/替换表），无法单独渲染")
        elif s.geometry_present is False:
            self.btn_view.setToolTip("客户端未随包该皮肤的几何（.geometry），无法渲染")
        elif s.geometry_present is None:
            self.btn_view.setToolTip("未构建 pkg 几何索引，随包状态未知（仍可尝试）")
        else:
            self.btn_view.setToolTip(
                "无归属舰船 ⇒ 只按皮肤自带 hullConfig 加载船体，挂载可能缺失")

    def _on_current_changed(self, cur, _prev=None):
        s = cur.data(Qt.UserRole) if cur is not None else None
        if s is None:
            self.detail.clear()
            self.preview.setVisible(False)
            self._update_view_button(None)
            return
        self._show_detail(s)

    def _show_detail(self, s):
        pmodels = s.model_replace or {}
        rows = [
            ("显示名", s.display_name or "（无）"),
            ("索引", s.ext_index or s.raw_name),
            ("原始名", s.raw_name),
            ("类型", s.species or "（无）"),
            ("国家", s.nation or "（无）"),
            ("隐藏(hidden)", "是" if s.hidden else "否"),
            ("归属", "无（未被任何舰船收纳）"),
            ("生效方式", "模型替换（自带 hullConfig）" if s.origin == "model"
                        else ("材质贴图（camo 条目）" if s.entry is not None
                              else "材质贴图（找不到 camo 条目）")),
            ("自带船体模型", s.hull_model or "（无）"),
            ("几何目录", s.model_folder or "（无）"),
            ("客户端资源", _geometry_state(s)),
            ("模型替换数", str(len(pmodels))),
            ("选项图", s.icon_path or "（未缓存；客户端 gui/exteriors 下可能有）"),
        ]
        html = ["<table style='font-size:12px' cellspacing='0' cellpadding='3'>"]
        for k, v in rows:
            html.append(
                f"<tr><td style='color:#888;white-space:nowrap;vertical-align:top'>{k}</td>"
                f"<td>{_esc(v)}</td></tr>")
        html.append("</table>")
        if pmodels:
            html.append("<p style='margin-top:8px;color:#888'>peculiarityModels：</p><ul>")
            for k, v in list(pmodels.items())[:30]:
                html.append(f"<li style='font-size:11px'>{_esc(k)}<br>→ {_esc(v)}</li>")
            html.append("</ul>")
        self.detail.setHtml("".join(html))

        pix = None
        path = getattr(s, "icon_path", "") or ""
        if path:
            p = get_data_dir() / path
            if p.exists():
                cand = QPixmap(str(p))
                if not cand.isNull():
                    pix = cand
        if pix is not None:
            self.preview.setPixmap(
                pix.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.preview.setVisible(True)
        else:
            self.preview.setVisible(False)

        self._update_view_button(s)

    # ── 3D 预览 ──────────────────────────────────────────

    def _on_view_3d(self):
        s = self._current_scheme()
        if s is None:
            return
        if not self._can_preview(s):
            if not s.hull_model:
                bus.log_message.emit(
                    f"⚠️ {s.ext_index or s.raw_name}：未提供船体 hullConfig，无法单独渲染")
            else:
                bus.log_message.emit(
                    f"⚠️ {s.ext_index or s.raw_name}：客户端未随包几何"
                    f"（{s.model_folder}），无法 3D 预览")
            return
        try:
            from ui.geometry_viewer import GeometryViewerDialog
            if self._viewer is None:
                self._viewer = GeometryViewerDialog(self)
            self._viewer.open_skin(
                key=s.ext_index or s.raw_name,
                display_name=s.display_name or s.raw_name,
                model_folder=s.model_folder,
                skin=s.skin or {},
                nation=s.nation,
                model_replace=s.model_replace or {})
        except Exception as exc:  # noqa: BLE001
            bus.log_message.emit(f"❌ 打开独立涂装 3D 预览失败: {exc}")


def _geometry_state(s) -> str:
    """条目自带模型在客户端是否真的存在（决定能不能 3D 预览）。"""
    if s.origin != "model":
        return "（材质类，无需几何）"
    if not s.hull_model:
        return "（无自带船体 hullConfig，仅挂载/替换表）"
    if s.geometry_present is None:
        return "未知（未构建 pkg 索引）"
    return "已随包" if s.geometry_present else "未随包（客户端无该几何，无法渲染）"


def _esc(text) -> str:
    """最小 HTML 转义（避免 & < > 破坏详情表）。"""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
