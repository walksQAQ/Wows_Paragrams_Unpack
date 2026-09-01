from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QPushButton


class DataInterfaceCaptureService:
    """Render a full widget tree into a single long pixmap without disturbing current scroll state."""

    @staticmethod
    def _safe_size(widget: QWidget) -> QSize:
        if widget is None:
            return QSize(1, 1)
        size = widget.size()
        if size.width() <= 0 or size.height() <= 0:
            size = widget.sizeHint()
        if size.width() <= 0 or size.height() <= 0:
            size = widget.minimumSize()
        return QSize(max(size.width(), 1), max(size.height(), 1))

    def capture_detail_panel(self, detail_panel) -> QPixmap:
        """Capture the full current DetailPanel page into a long pixmap and restore original UI state."""
        if detail_panel is None:
            return QPixmap()

        components = self._get_capture_components(detail_panel)
        if not components:
            return QPixmap()

        saved = self._snapshot_scroll_positions(components)
        scroll_geom = self._snapshot_scroll_geometry(components)
        button_states = self._snapshot_toggle_buttons(detail_panel)
        render_state = self._snapshot_render_state(detail_panel)
        flatten_saved: list = []

        try:
            if hasattr(detail_panel, "_expand_all_collapsible"):
                detail_panel._expand_all_collapsible()
            setattr(detail_panel, "_capture_accumulate_con", True)
            self._prepare_render_only_detail_pages(detail_panel)
            # 把“弹药/选项详情”堆栈临时展开为纵向一列，让一门炮的所有弹药都参与渲染
            flatten_saved = self._flatten_detail_stacks(components)
            QApplication.processEvents()
            parts = [self.capture_widget(comp) for comp in components]
            clean_parts = [p for p in parts if p is not None and not p.isNull()]
            if not clean_parts:
                return QPixmap()
            return self.compose(clean_parts)
        finally:
            setattr(detail_panel, "_capture_accumulate_con", False)
            self._restore_detail_stacks(flatten_saved)
            self._restore_toggle_buttons(detail_panel, button_states)
            self._restore_scroll_positions(components, saved)
            self._restore_render_state(detail_panel, render_state)
            self._restore_scroll_geometry(scroll_geom)
            QApplication.processEvents()

    def _get_capture_components(self, detail_panel) -> list[QWidget]:
        page = getattr(detail_panel, "stack", None)
        if page is None or page.currentWidget() is None:
            return []
        current = page.currentWidget()
        if hasattr(detail_panel, "get_capture_components"):
            try:
                comps = detail_panel.get_capture_components()
                if comps:
                    return [c for c in comps if c is not None]
            except Exception:
                pass

        if getattr(detail_panel, "_is_ship_mode", False):
            scrollers = current.findChildren(QScrollArea)
            visible = [sa for sa in scrollers if sa.isVisible() and sa.widget() is not None]
            if visible:
                return visible
        return [current]

    def capture_widget(self, widget: QWidget | None) -> QPixmap:
        if widget is None:
            return QPixmap()

        if isinstance(widget, QStackedWidget):
            return self.capture_stacked_widget(widget)
        if isinstance(widget, QScrollArea):
            return self.capture_scroll_area(widget)
        if isinstance(widget, QTextEdit):
            return self.capture_text_edit(widget)
        if isinstance(widget, QAbstractItemView):
            return self.capture_item_view(widget)

        # 页面级容器本身已经包含了所有子堆栈；继续递归会把同一片区域重复渲染
        # 多次，导致长图重复叠加和错误拉伸。仅对独立的 QStackedWidget 进行专门处理。
        return self._render_widget(widget)

    def capture_stacked_widget(self, widget: QStackedWidget) -> QPixmap:
        if widget is None or widget.count() == 0:
            return self._render_widget(widget)

        original_index = widget.currentIndex()
        original_visible = widget.isVisible()
        original_max_h = widget.maximumHeight()
        original_w = widget.width()
        original_min_h = widget.minimumHeight()
        parts: list[QPixmap] = []
        try:
            widget.setVisible(True)
            widget.setMaximumHeight(16777215)
            widget.setMinimumHeight(1)
            QApplication.processEvents()

            for i in range(widget.count()):
                widget.setCurrentIndex(i)
                QApplication.processEvents()
                page = widget.currentWidget()
                if page is None:
                    continue
                page.setVisible(True)
                page.setMaximumHeight(16777215)
                if page.layout() is not None:
                    page.layout().activate()
                    page.resize(max(page.width(), widget.width() or page.width()), max(page.sizeHint().height(), page.minimumHeight(), 1))
                else:
                    page.resize(max(page.width(), widget.width() or page.width()), max(page.minimumHeight(), 1))
                QApplication.processEvents()
                pix = page.grab(page.rect())
                if pix is not None and not pix.isNull():
                    parts.append(pix)

            widget.setCurrentIndex(original_index)
            QApplication.processEvents()

        finally:
            widget.setCurrentIndex(original_index)
            widget.setVisible(original_visible)
            widget.setMaximumHeight(original_max_h)
            widget.setMinimumHeight(original_min_h)
            widget.resize(original_w, max(widget.height(), 1))
            QApplication.processEvents()

        if not parts:
            return self._render_widget(widget)
        return self.compose(parts)

    def capture_widget_with_stacks(self, widget: QWidget, stacked_children: list[QStackedWidget]) -> QPixmap:
        if widget is None:
            return QPixmap()

        saved_states: list[tuple[QStackedWidget, int, bool, int, int]] = []
        parts: list[QPixmap] = []
        try:
            for stack in stacked_children:
                saved_states.append((
                    stack,
                    stack.currentIndex(),
                    stack.isVisible(),
                    stack.maximumHeight(),
                    stack.minimumHeight(),
                ))
                for i in range(stack.count()):
                    stack.setCurrentIndex(i)
                    stack.setVisible(True)
                    stack.setMaximumHeight(16777215)
                    stack.setMinimumHeight(1)
                    QApplication.processEvents()
                    pix = self._render_widget(widget)
                    if pix is not None and not pix.isNull():
                        parts.append(pix)
            if not parts:
                parts.append(self._render_widget(widget))
        finally:
            for stack, idx, visible, max_h, min_h in saved_states:
                try:
                    stack.setCurrentIndex(idx)
                    stack.setVisible(visible)
                    stack.setMaximumHeight(max_h)
                    stack.setMinimumHeight(min_h)
                except Exception:
                    pass
            QApplication.processEvents()

        if len(parts) == 1:
            return parts[0]
        return self.compose(parts)

    def capture_scroll_area(self, scroll_area: QScrollArea) -> QPixmap:
        content = scroll_area.widget()
        if content is None:
            return QPixmap()

        original_geom = content.geometry()
        original_min_h = content.minimumHeight()
        original_min_w = content.minimumWidth()
        original_w = content.width()
        original_h = content.height()
        original_h_policy = scroll_area.horizontalScrollBarPolicy()
        original_v_policy = scroll_area.verticalScrollBarPolicy()

        try:
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

            # 只扩展高度，保持原始宽度，避免把列布局撑宽导致卡片错位重排
            target_w = max(content.width(), scroll_area.viewport().width(), content.minimumWidth(), 1)
            target_h = max(content.height(), content.minimumHeight(), 1)

            if content.layout() is not None:
                layout_h = content.layout().totalSizeHint().height()
                target_h = max(target_h, layout_h)
            if content.sizeHint().height() > target_h:
                target_h = max(target_h, content.sizeHint().height())

            if target_h > content.height():
                content.resize(target_w, target_h)
                content.setMinimumHeight(target_h)
                QApplication.processEvents()

            return content.grab(QRectF(0, 0, content.width(), content.height()).toRect())
        finally:
            try:
                content.resize(original_w, original_h)
                content.setMinimumWidth(original_min_w)
                content.setMinimumHeight(original_min_h)
                content.setGeometry(original_geom)
                scroll_area.setHorizontalScrollBarPolicy(original_h_policy)
                scroll_area.setVerticalScrollBarPolicy(original_v_policy)
            except Exception:
                pass
            QApplication.processEvents()

    def capture_text_edit(self, widget: QTextEdit) -> QPixmap:
        doc = widget.document()
        viewport = widget.viewport()
        width = max(int(viewport.width()), 1)
        height = max(int(doc.size().height()), 1)
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.white)
        painter = QPainter(pixmap)
        try:
            doc.drawContents(painter, QRectF(0, 0, width, height))
        finally:
            painter.end()
        return pixmap

    def capture_item_view(self, view: QAbstractItemView) -> QPixmap:
        viewport = view.viewport()
        if viewport is None:
            return QPixmap()
        size = viewport.size()
        pixmap = QPixmap(size.width(), size.height())
        pixmap.fill(Qt.GlobalColor.white)
        painter = QPainter(pixmap)
        try:
            view.render(painter, QPoint(), viewport.rect())
        finally:
            painter.end()
        return pixmap

    def _render_widget(self, widget: QWidget, width: int | None = None, height: int | None = None) -> QPixmap:
        if width is None and height is None:
            return widget.grab()

        size = self._safe_size(widget)
        if width is not None:
            size.setWidth(max(width, 1))
        if height is not None:
            size.setHeight(max(height, 1))
        if size.width() <= 0 or size.height() <= 0:
            return QPixmap()
        return widget.grab(QRectF(0, 0, size.width(), size.height()).toRect())

    @staticmethod
    def compose(parts: Iterable[QPixmap]) -> QPixmap:
        items = list(parts)
        if not items:
            return QPixmap()
        width = max(p.width() for p in items)
        total_height = sum(p.height() for p in items) + 8 * max(0, len(items) - 1)
        canvas = QPixmap(width, total_height)
        canvas.fill(Qt.GlobalColor.white)
        painter = QPainter(canvas)
        try:
            y = 0
            for pix in items:
                painter.drawPixmap(0, y, pix)
                y += pix.height() + 8
        finally:
            painter.end()
        return canvas

    def copy_to_clipboard(self, pixmap: QPixmap) -> None:
        if pixmap is None or pixmap.isNull():
            return
        QApplication.clipboard().setPixmap(pixmap)

    @staticmethod
    def _snapshot_render_state(detail_panel) -> dict:
        state: dict[str, object] = {"stacks": {}, "active_con_keys": {}, "active_con_btn": None}
        page = getattr(detail_panel, "stack", None)
        if page is None:
            return state
        for stack in page.findChildren(QStackedWidget):
            try:
                state["stacks"][id(stack)] = {
                    "current_index": stack.currentIndex(),
                    "visible": stack.isVisible(),
                    "max_height": stack.maximumHeight(),
                    "min_height": stack.minimumHeight(),
                    "max_width": stack.maximumWidth(),
                    "min_width": stack.minimumWidth(),
                    # 记录原始页数，便于截图后删除“点开详情”时动态新增的页
                    "page_count": stack.count(),
                }
            except Exception:
                continue
        active_con_keys = getattr(detail_panel, "_active_con_keys", None)
        if isinstance(active_con_keys, dict):
            state["active_con_keys"] = dict(active_con_keys)
        state["active_con_btn"] = getattr(detail_panel, "_active_con_btn", None)
        return state

    @staticmethod
    def _restore_render_state(detail_panel, state: dict) -> None:
        if detail_panel is None:
            return
        page = getattr(detail_panel, "stack", None)
        if page is None:
            return
        for stack in page.findChildren(QStackedWidget):
            stack_state = state.get("stacks", {}).get(id(stack))
            if not isinstance(stack_state, dict):
                continue
            try:
                # 删除截图过程中“点开详情”动态新增（超出原始页数）的页面，避免残留拉长卡
                orig_count = int(stack_state.get("page_count", stack.count()))
                while stack.count() > orig_count:
                    w = stack.widget(stack.count() - 1)
                    stack.removeWidget(w)
                    w.deleteLater()
                stack.setCurrentIndex(int(stack_state.get("current_index", 0)))
                stack.setVisible(bool(stack_state.get("visible", stack.isVisible())))
                stack.setMaximumHeight(int(stack_state.get("max_height", stack.maximumHeight())))
                stack.setMinimumHeight(int(stack_state.get("min_height", stack.minimumHeight())))
                stack.setMaximumWidth(int(stack_state.get("max_width", stack.maximumWidth())))
                stack.setMinimumWidth(int(stack_state.get("min_width", stack.minimumWidth())))
                stack.updateGeometry()
            except Exception:
                continue
        active_con_keys = getattr(detail_panel, "_active_con_keys", None)
        if isinstance(active_con_keys, dict):
            active_con_keys.clear()
            active_con_keys.update(state.get("active_con_keys", {}))
        if hasattr(detail_panel, "_active_con_btn"):
            detail_panel._active_con_btn = state.get("active_con_btn")

    @staticmethod
    def _is_detail_reveal_button(btn: QPushButton) -> bool:
        """判断是否为“详情展开按钮”（消耗品/弹药等）。

        特征：按钮所在的行 widget 与一个 QStackedWidget 详情堆栈互为兄弟
        （同在一个父容器布局里）。模块/技能/信号旗等选择按钮不会与详情堆栈
        同层，因此被排除——避免截图流程误点选择按钮造成数据重算等副作用。
        """
        if btn is None or not btn.isEnabled() or not btn.isVisible() or not btn.isCheckable():
            return False
        parent = btn.parentWidget()
        if parent is None:
            return False
        container = parent.parentWidget()
        if container is None:
            return False
        lay = container.layout()
        if lay is None:
            return False
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, QStackedWidget) and w.count() > 0:
                return True
        return False

    @staticmethod
    def _prepare_render_only_detail_pages(detail_panel) -> None:
        """为截图做准备：仅展开详情堆栈的当前页，并点开消耗品/弹药详情按钮。

        - 只点击“详情按钮”（消耗品/弹药），绝不点击模块/技能/信号旗等选择按钮，
          避免截图时误选中、触发数据重算等副作用。
        - 遍历堆栈时不再切换全部页面（那会导致同一区域重复渲染），只展开当前页。
        """
        if detail_panel is None:
            return
        page = getattr(detail_panel, "stack", None)
        if page is None or page.currentWidget() is None:
            return

        for btn in list(page.findChildren(QPushButton)):
            try:
                if not DataInterfaceCaptureService._is_detail_reveal_button(btn):
                    continue
                if btn.isChecked():
                    continue
                btn.click()
            except RuntimeError:
                continue
            except Exception:
                continue

        for stack in list(page.findChildren(QStackedWidget)):
            try:
                stack.setVisible(True)
                stack.setMinimumHeight(0)
                stack.setMaximumHeight(16777215)
                child = stack.currentWidget()
                if child is not None:
                    child.setVisible(True)
                    child.setMinimumHeight(0)
                    child.setMaximumHeight(16777215)
                    if child.layout() is not None:
                        child.layout().activate()
                    child.resize(max(child.width(), stack.width(), 1),
                                 max(child.sizeHint().height(), child.minimumHeight(), 1))
            except RuntimeError:
                continue
            except Exception:
                continue

    @staticmethod
    def _is_prompt_page(widget: QWidget) -> bool:
        """是否为“点击上方…查看详细数据”之类的提示页。"""
        return isinstance(widget, QLabel) and "点击" in (widget.text() or "")

    @staticmethod
    def _should_flatten_stack(stack: QStackedWidget) -> bool:
        """是否是“选项详情堆栈”（如一门炮的多种弹药 / 多个消耗品），截图时应展开显示全部页。

        判定：真实详情页（非“点击…”提示页）数量 > 1，且其父布局中存在一排
        “可勾选按钮”的行给各页做切换。
        """
        if stack is None or stack.count() <= 1:
            return False
        real_pages = [
            stack.widget(i) for i in range(stack.count())
            if not DataInterfaceCaptureService._is_prompt_page(stack.widget(i))
        ]
        if len(real_pages) <= 1:
            return False
        parent = stack.parentWidget()
        lay = parent.layout() if parent else None
        if lay is None:
            return False
        for i in range(lay.count()):
            item = lay.itemAt(i)
            row = item.widget()
            if row is None or row is stack:
                continue
            row_lay = row.layout()
            if row_lay is None:
                continue
            for j in range(row_lay.count()):
                btn = row_lay.itemAt(j).widget()
                if isinstance(btn, QPushButton) and btn.isCheckable():
                    return True
        return False

    @staticmethod
    def _layout_index(lay, widget: QWidget) -> int:
        for i in range(lay.count()):
            if lay.itemAt(i).widget() is widget:
                return i
        return -1

    @staticmethod
    def _flatten_detail_stacks(components) -> list:
        """把“选项详情堆栈”临时展开成纵向一列，使一门炮的所有弹药都在截图中渲染。

        做法：在堆栈内逐个抓取每个真实详情页为 pixmap（此时页面布局正确、内容完整），
        纵向合成后用 QLabel 原位替换堆栈；避免直接把页面重挂到临时布局导致黑底/错位。
        截图后由 _restore_detail_stacks 完整还原堆栈。
        """
        saved: list = []
        seen: set[int] = set()
        for comp in components:
            roots = [comp.widget()] if isinstance(comp, QScrollArea) and comp.widget() else [comp]
            for root in roots:
                if root is None:
                    continue
                for stack in root.findChildren(QStackedWidget):
                    if id(stack) in seen:
                        continue
                    seen.add(id(stack))
                    if not DataInterfaceCaptureService._should_flatten_stack(stack):
                        continue
                    parent = stack.parentWidget()
                    lay = parent.layout() if parent else None
                    if lay is None:
                        continue
                    idx = DataInterfaceCaptureService._layout_index(lay, stack)
                    if idx < 0:
                        continue

                    pages = [
                        stack.widget(i) for i in range(stack.count())
                        if not DataInterfaceCaptureService._is_prompt_page(stack.widget(i))
                    ]
                    page_min = {id(pg): pg.minimumHeight() for pg in pages}
                    orig_index = stack.currentIndex()
                    stack.setVisible(True)
                    stack.setMaximumHeight(16777215)
                    stack.setMinimumHeight(1)

                    parts: list[QPixmap] = []
                    for pg in pages:
                        pos = stack.indexOf(pg)
                        if pos >= 0:
                            stack.setCurrentIndex(pos)
                        QApplication.processEvents()
                        if pg.layout() is not None:
                            pg.layout().activate()
                        # 让页面在新高度下重新布局后再抓取
                        pg_resize = max(int(pg.sizeHint().height() or 0), int(pg.height() or 0), 1)
                        pg.resize(max(pg.width(), stack.width(), 1), pg_resize)
                        QApplication.processEvents()
                        pix = pg.grab()
                        if pix is not None and not pix.isNull() and pix.height() > 0:
                            parts.append(pix)
                    stack.setCurrentIndex(orig_index)

                    composed = DataInterfaceCaptureService.compose(parts) if parts else QPixmap()
                    label = QLabel()
                    label.setObjectName("__cap_flatten_label__")
                    label.setPixmap(composed)
                    # 让合成图随布局宽度自适应，避免窄于列宽造成错位
                    label.setScaledContents(False)

                    saved.append({
                        "stack": stack, "label": label, "pages": pages,
                        "page_min": page_min, "orig_index": orig_index,
                        "lay": lay, "idx": idx,
                        "geometry": QRect(stack.geometry()),
                        "visible": stack.isVisible(),
                        "max_h": stack.maximumHeight(),
                        "min_h": stack.minimumHeight(),
                    })
                    lay.removeWidget(stack)
                    stack.setVisible(False)
                    lay.insertWidget(idx, label)
                    label.show()
        return saved

    @staticmethod
    def _restore_detail_stacks(saved: list) -> None:
        for s in saved:
            try:
                stack = s["stack"]
                label = s["label"]
                lay = s["lay"]
                idx = s["idx"]
                lay.removeWidget(label)
                for pg, orig_min in s.get("page_min", {}).items():
                    try:
                        pg.setMinimumHeight(orig_min)
                    except Exception:
                        pass
                stack.setCurrentIndex(s.get("orig_index", 0))
                stack.setVisible(s["visible"])
                stack.setMaximumHeight(s["max_h"])
                stack.setMinimumHeight(s["min_h"])
                stack.setGeometry(s["geometry"])
                lay.insertWidget(idx, stack)
                stack.show()
                label.setParent(None)
                label.deleteLater()
            except Exception:
                continue

    @staticmethod
    def _snapshot_scroll_geometry(components: Iterable[QWidget]) -> list[dict]:
        """记录所有滚动区及其内容控件的完整几何，便于截图后精确还原，
        避免卡片滚动区内容被错误拉长。"""
        snaps: list[dict] = []
        for comp in components:
            scrolls = ([comp] if isinstance(comp, QScrollArea) else []) \
                + [sa for sa in comp.findChildren(QScrollArea)]
            seen: set[int] = set()
            for sa in scrolls:
                if id(sa) in seen:
                    continue
                seen.add(id(sa))
                try:
                    content = sa.widget()
                    snaps.append({
                        "sa": sa,
                        "sa_geometry": QRect(sa.geometry()),
                        "sa_min": QSize(sa.minimumSize()),
                        "sa_max": QSize(sa.maximumSize()),
                        "sa_h_policy": sa.horizontalScrollBarPolicy(),
                        "sa_v_policy": sa.verticalScrollBarPolicy(),
                        "content_geometry": QRect(content.geometry()) if content else None,
                        "content_min": QSize(content.minimumSize()) if content else None,
                        "content_max": QSize(content.maximumSize()) if content else None,
                        "content_size": QSize(content.size()) if content else None,
                    })
                except Exception:
                    continue
        return snaps

    @staticmethod
    def _restore_scroll_geometry(snaps: Iterable[dict]) -> None:
        for s in snaps:
            sa = s.get("sa")
            if sa is None:
                continue
            try:
                sa.setGeometry(s["sa_geometry"])
                sa.setMinimumSize(s["sa_min"])
                sa.setMaximumSize(s["sa_max"])
                sa.setHorizontalScrollBarPolicy(s["sa_h_policy"])
                sa.setVerticalScrollBarPolicy(s["sa_v_policy"])
                content = sa.widget()
                if content is not None and s.get("content_geometry") is not None:
                    content.setGeometry(s["content_geometry"])
                    content.setMinimumSize(s["content_min"])
                    content.setMaximumSize(s["content_max"])
                    content.resize(s["content_size"])
            except Exception:
                continue
        QApplication.processEvents()

    @staticmethod
    def _snapshot_scroll_positions(components: Iterable[QWidget]) -> dict[int, tuple[int, int]]:
        result: dict[int, tuple[int, int]] = {}
        for widget in components:
            if isinstance(widget, QScrollArea):
                result[id(widget)] = (
                    widget.horizontalScrollBar().value(),
                    widget.verticalScrollBar().value(),
                )
        return result

    @staticmethod
    def _restore_scroll_positions(components: Iterable[QWidget], saved: dict[int, tuple[int, int]]) -> None:
        for widget in components:
            if isinstance(widget, QScrollArea):
                key = id(widget)
                if key in saved:
                    h, v = saved[key]
                    widget.horizontalScrollBar().setValue(h)
                    widget.verticalScrollBar().setValue(v)

    @staticmethod
    def _snapshot_toggle_buttons(detail_panel) -> dict[int, bool]:
        if detail_panel is None:
            return {}
        page = getattr(detail_panel, "stack", None)
        if page is None or page.currentWidget() is None:
            return {}
        state: dict[int, bool] = {}
        for btn in page.currentWidget().findChildren(QWidget):
            try:
                if getattr(btn, "isCheckable", False):
                    state[id(btn)] = btn.isChecked()
            except Exception:
                continue
        return state

    @staticmethod
    def _restore_toggle_buttons(detail_panel, saved: dict[int, bool]) -> None:
        if detail_panel is None:
            return
        page = getattr(detail_panel, "stack", None)
        if page is None or page.currentWidget() is None:
            return
        for btn in page.currentWidget().findChildren(QWidget):
            try:
                if getattr(btn, "isCheckable", False) and id(btn) in saved:
                    btn.setChecked(saved[id(btn)])
            except Exception:
                continue
