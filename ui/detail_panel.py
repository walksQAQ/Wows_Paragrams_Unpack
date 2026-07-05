"""
DetailPanel —— 右侧详情展示面板（QStackedWidget，动态页面）。

完全基于数据库读取显示，不再调用分析器。
由 ModuleSelect 控制页面切换。
"""

from __future__ import annotations

import json

from functools import partial

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QTextEdit, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from app.signals import bus
from services.database_service import get_db
from presenters.registry import PresenterRegistry, CATEGORY_TO_ETYPE


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self._build_default_pages()
        self._show_hint()
        # 启动时不通知 ModuleSelect，保持空白占位
        bus.file_selected.connect(self._on_file_selected)

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
        self._clear_pages()
        self._is_ship_mode = True
        self._section_page_indices = {}
        sub_sections = (extra or {}).get("sub_sections", {})
        for sec in sections:
            label = sec.get("label", "未知")
            # 子分类：按 section label 直接查找（新结构 key=模块类型）
            sub_info = sub_sections.get(label)
            if sub_info and sub_info.get("sub_labels"):
                widget = self._build_sub_widget(sub_info)
                idx = self.stack.addWidget(widget)
                self._section_page_indices[label] = idx
            else:
                te = QTextEdit()
                te.setReadOnly(True)
                te.setFont(self._make_font("Microsoft YaHei", 11))
                te.setStyleSheet(self.TEXT_STYLE)
                lines = []
                for item in sorted(sec.get("items", []), key=lambda x: x.get("order", 0)):
                    n = item.get("name", "")
                    v = item.get("value", "")
                    if n:
                        lines.append(f"  {n}")
                    elif v:
                        lines.append(v)
                    else:
                        lines.append("")
                te.setPlainText("\n".join(lines))
                idx = self.stack.addWidget(te)
                self._section_page_indices[label] = idx
        if self._section_page_indices:
            self.stack.setCurrentIndex(next(iter(self._section_page_indices.values())))

    def _build_sub_widget(self, sub_info: dict) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        labels = sub_info.get("sub_labels", [])
        contents = sub_info.get("sub_contents", {})
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:#f0f0f0;}")
        bar = QWidget()
        bar.setStyleSheet("QWidget{background:#f0f0f0;border-bottom:1px solid #d0d0d0;}")
        blay = QHBoxLayout(bar)
        blay.setContentsMargins(8, 4, 8, 4)
        blay.setSpacing(4)
        scroll.setWidget(bar)
        stack = QStackedWidget()
        btns: list[QPushButton] = []
        for i, sl in enumerate(labels):
            te = QTextEdit()
            te.setReadOnly(True)
            te.setFont(self._make_font("Microsoft YaHei", 11))
            te.setStyleSheet(self.TEXT_STYLE)
            te.setPlainText("\n".join(contents.get(sl, [])))
            stack.addWidget(te)
            btn = QPushButton(sl)
            btn.setCheckable(True)
            btn.setStyleSheet("QPushButton{background:transparent;color:#555;border:none;"
                              "border-radius:4px;padding:6px 14px;font-size:12px;}"
                              "QPushButton:hover{background:#d0d0d0;color:#333;}"
                              "QPushButton:checked{background:#0078d4;color:#fff;}")
            btn.clicked.connect(partial(self._on_sub_btn, stack, i, btns))
            blay.addWidget(btn)
            btns.append(btn)
        blay.addStretch()
        if btns:
            btns[0].setChecked(True)
        layout.addWidget(scroll)
        layout.addWidget(stack, stretch=1)
        return container

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
            except Exception:
                pass
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
            labels = [s.get("label", "") for s in sections]
            extra = (self._current_analyzed or {}).get("extra")
            self._build_ship_pages(sections, extra)
            self.modules_available.emit(labels)
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

