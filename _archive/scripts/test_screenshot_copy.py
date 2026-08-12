"""
"复制信息面板完整内容"功能冒烟测试。

覆盖：
  1. toolbar：复制按钮为无下拉 QPushButton + 前三个按钮样式恢复，点击发射 copy_ship_info
  2. 完整文本复制：收集信息面板所有内容（分组/键值行/弹药所有页/表格）
  3. detail_panel 通用模式：QTextEdit 整篇渲染为长图（截图方法保留）
  4. detail_panel 舰船模式：滚动区内容拼接为完整长图
  5. _render_sections_to_text：文本含弹药信息；_render_default_pages_to_text 不含原始

用法:
  $env:QT_QPA_PLATFORM="offscreen"
  .venv\\Scripts\\python.exe _archive\\scripts\\test_screenshot_copy.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget, QScrollArea, QLabel


def _wait(app, pred, timeout=10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if pred():
            break
        time.sleep(0.02)
    app.processEvents()
    return pred()


def test_toolbar(app) -> None:
    """工具栏复制按钮：无下拉 + 前三个按钮样式恢复 + 点击发 copy_ship_info。"""
    from ui.toolbar_widget import TopToolbar
    from PySide6.QtWidgets import QToolButton
    from app.signals import bus

    tb = TopToolbar()
    assert not isinstance(tb.btn_copy, QToolButton), "按钮不应是 QToolButton（无下拉）"
    assert tb.btn_copy.menu() is None, "按钮不应带菜单"
    assert tb.btn_copy.text() == "📋  复制当前信息", f"按钮文字错误: {tb.btn_copy.text()}"
    # 前三个按钮应带 BTN_STYLE（深色样式）—— 修复样式丢失
    for name in ("btn_load", "btn_lang", "btn_refresh"):
        b = getattr(tb, name)
        assert "background-color: #3a3a3a" in b.styleSheet(), f"{name} 样式丢失"

    got: list[str] = []
    conn = bus.copy_ship_info.connect(lambda: got.append("copy"))
    tb.btn_copy.click()
    app.processEvents()
    assert got == ["copy"], f"点击应发射 copy_ship_info, 实为 {got}"
    bus.copy_ship_info.disconnect(conn)
    print("[OK] toolbar: 无下拉按钮 + 前三个样式恢复，点击发射 copy_ship_info")


def test_full_text_copy(app) -> None:
    """完整文本复制：数据驱动，只复制舰船数据（sections+子面板+弹药），不含技能面板。"""
    from ui.detail_panel import DetailPanel
    dp = DetailPanel()
    dp._is_ship_mode = True
    dp._current_filename = "SHIP_A"
    dp._ship_sections = [
        {"label": "基础属性", "icon": "📋",
         "items": [{"row_type": "kv", "name": "舰船名称", "value": "MONTANA"}]},
        {"label": "主炮", "icon": "🔫",
         "items": [{"row_type": "kv", "name": "装填时间", "value": "6.4", "unit": "秒"},
                   {"row_type": "kv", "name": "最大射程", "value": "18.00", "unit": "km"}],
         "raw_ammo_types": [{"name": "AP 穿甲弹",
                             "detail_items": [{"name": "标伤", "value": "12000"},
                                              {"name": "初速", "value": "850", "unit": "m/s"}]}]},
    ]
    dp._ship_sub_sections = {
        "舰载机": {
            "sub_labels": ["轰炸机"],
            "sub_contents": {
                "轰炸机": {
                    "config_labels": ["k1"],
                    "config_contents": {
                        "k1": {"items": [{"row_type": "kv", "name": "载弹量", "value": "6"}],
                               "raw_ammo_types": [{"name": "HE 炸弹",
                                                   "detail_items": [{"name": "标伤", "value": "5000"}]}],
                               "raw_consumables": [{"display_name": "引擎加速器",
                                                    "detail_items": [{"name": "持续", "value": "60", "unit": "s"}]}]},
                    },
                },
            },
        },
    }

    text = DetailPanel._render_sections_to_text(dp._ship_sections)
    assert "📋 基础属性" in text and "舰船名称: MONTANA" in text
    assert "🔫 主炮" in text and "装填时间: 6.4 秒" in text and "最大射程: 18.00 km" in text
    assert "AP 穿甲弹" in text and "标伤: 12000" in text and "初速: 850 m/s" in text
    print("[OK] sections 文本: 舰船数据 + 弹药明细")

    sub = dp._render_sub_sections_to_text(dp._ship_sub_sections)
    assert "【舰载机】" in sub and "载弹量" in sub and "HE 炸弹" in sub
    assert "引擎加速器" in sub and "持续: 60 s" in sub
    print("[OK] 子面板文本: 舰载机数据 + 弹药 + 消耗品")

    # 完整流程：剪贴板收到舰船数据，且不含技能面板
    from PySide6.QtWidgets import QApplication
    dp._copy_ship_info_to_clipboard()
    clip = QApplication.clipboard().text()
    assert "舰船名称: MONTANA" in clip and "装填时间: 6.4 秒" in clip and "AP 穿甲弹" in clip
    assert "载弹量" in clip and "引擎加速器" in clip
    assert "技能" not in clip and "升级品" not in clip and "信号旗" not in clip, \
        "复制内容不应包含技能面板等界面内容"
    print("[OK] 完整文本复制: 只含舰船数据（含弹药/子面板），不含技能面板")



def test_generic_screenshot(app) -> None:
    """通用模式：QTextEdit 整篇渲染长图 + 剪贴板。"""
    from ui.detail_panel import DetailPanel
    dp = DetailPanel()
    dp._current_category = "Gun"
    dp._current_filename = "GUN_A"
    dp._is_ship_mode = False
    # 造一段超过一屏的文本
    dp._default_pages[0].setPlainText("炮名: 406mm 主炮组\n" + "\n".join(f"字段{i}: 值{i}" for i in range(200)))
    dp.stack.setCurrentIndex(0)

    pm = dp._render_current_page_complete()
    assert pm is not None and not pm.isNull(), "通用模式长图渲染失败"
    assert pm.height() > 100, f"长图高度异常: {pm.height()}"

    # 走完整流程：点击 → QTimer 截图 → 剪贴板
    from PySide6.QtWidgets import QApplication
    dp._copy_panel_screenshot()
    assert _wait(app, lambda: not QApplication.clipboard().image().isNull()), "剪贴板未收到图片"
    img = QApplication.clipboard().image()
    assert img.width() > 0 and img.height() > 0
    print(f"[OK] detail_panel 通用模式: 长图渲染 + 剪贴板图片 ({img.width()}×{img.height()})")


def test_ship_screenshot(app) -> None:
    """舰船模式：滚动区内容拼接为完整长图。"""
    from ui.detail_panel import DetailPanel
    dp = DetailPanel()
    page = QWidget()
    lay = QVBoxLayout(page)
    sa1 = QScrollArea()
    sa1.setWidgetResizable(True)
    w1 = QWidget()
    v1 = QVBoxLayout(w1)
    for i in range(60):
        v1.addWidget(QLabel(f"卡片内容第 {i} 行"))
    sa1.setWidget(w1)
    lay.addWidget(sa1)
    dp.stack.addWidget(page)
    dp.stack.setCurrentWidget(page)
    app.processEvents()

    pm = dp._render_current_page_complete()
    assert pm is not None and not pm.isNull(), "舰船模式拼接截图失败"
    assert pm.width() > 0 and pm.height() > 100, f"尺寸异常 {pm.width()}x{pm.height()}"
    print(f"[OK] detail_panel 舰船模式: 滚动区内容拼接长图 ({pm.width()}×{pm.height()})")


def test_expand_buttons(app) -> None:
    """展开折叠按钮：点击未展开的，跳过自定义/已展开。"""
    from ui.detail_panel import DetailPanel
    dp = DetailPanel()
    page = QWidget()
    lay = QVBoxLayout(page)
    clicks = {"ammo": 0, "custom": 0, "checked": 0}
    b_ammo = QPushButton("AP 穿甲弹")
    b_ammo.setCheckable(True)
    b_ammo.clicked.connect(lambda: clicks.__setitem__("ammo", clicks["ammo"] + 1))
    b_custom = QPushButton("自定义舰长")
    b_custom.clicked.connect(lambda: clicks.__setitem__("custom", clicks["custom"] + 1))
    b_checked = QPushButton("已展开")
    b_checked.setCheckable(True)
    b_checked.setChecked(True)
    b_checked.clicked.connect(lambda: clicks.__setitem__("checked", clicks["checked"] + 1))
    for b in (b_ammo, b_custom, b_checked):
        lay.addWidget(b)
    dp.stack.addWidget(page)
    dp.stack.setCurrentWidget(page)
    # 让 DetailPanel 显示，按钮 isVisible() 才为 True（与真实应用一致）
    dp.show()
    app.processEvents()

    dp._expand_all_collapsible()
    app.processEvents()
    assert clicks["ammo"] == 1, f"弹药按钮应被点击 1 次, 实为 {clicks['ammo']}"
    assert clicks["custom"] == 0, "自定义按钮应被跳过"
    assert clicks["checked"] == 0, "已展开按钮应被跳过"
    assert b_ammo.isChecked(), "弹药按钮应已展开"
    print("[OK] _expand_all_collapsible: 展开未选中按钮，跳过自定义/已展开")


def test_text_ammo_and_no_raw(app) -> None:
    """文本复制：含弹药信息，且不含原始。"""
    from ui.detail_panel import DetailPanel
    sections = [
        {"label": "主炮", "icon": "🔫",
         "items": [{"row_type": "kv", "name": "射速", "value": "6.4", "unit": "秒"}],
         "raw_ammo_types": [
             {"name": "AP 穿甲弹",
              "detail_items": [{"name": "伤害", "value": "12000"},
                               {"name": "初速", "value": "850", "unit": "m/s"}]},
             {"name": "HE 高爆弹",
              "detail_items": [{"name": "伤害", "value": "5000"}]},
         ]},
    ]
    text = DetailPanel._render_sections_to_text(sections)
    assert "🔫 主炮" in text
    assert "【弹药】" in text, f"文本缺弹药标题: {text}"
    assert "AP 穿甲弹" in text and "伤害: 12000" in text and "初速: 850 m/s" in text
    assert "HE 高爆弹" in text
    print("[OK] _render_sections_to_text: 弹药信息已包含（AP/HE 及明细）")

    dp = DetailPanel()
    dp._current_filename = "X"
    dp._is_ship_mode = False
    dp._default_pages[0].setPlainText("详情内容")
    dp._default_pages[1].setPlainText("数据内容")
    dp._default_pages[2].setPlainText('{"raw": "json"}')
    dp.stack.setCurrentIndex(0)
    t = dp._render_default_pages_to_text("all")
    assert "【详情】" in t and "【数据】" in t, f"缺详情/数据: {t[:120]}"
    assert "【原始】" not in t and "raw" not in t.lower(), f"不应包含原始: {t[:200]}"
    print("[OK] _render_default_pages_to_text('all'): 仅详情+数据，不含原始")


def test_default_config_letter(app) -> None:
    """问题3修复：首次打开舰船时默认配置字母取 stock，显示对应配置数据。"""
    from ui.detail_panel import DetailPanel
    dp = DetailPanel()
    dp._current_analyzed = {
        "sections": [
            {"label": "基础属性",
             "items": [{"name": "舰船名称", "value": "X", "order": 0}]},
            {"label": "主炮", "items": [],
             "_config_letters": ["A", "B"],
             "_items_by_letter": {
                 "A": [{"name": "reload", "value": "A 配置", "order": 0}],
                 "B": [{"name": "reload", "value": "B 配置", "order": 0}]}},
        ],
        "config_bar": {"_stock_config_letter": "B"},
    }
    dp._apply_analyzed()
    app.processEvents()
    assert dp._active_config_letter == "B", \
        f"默认配置字母应为 B(stock), 实为 {dp._active_config_letter}"
    main_sec = next(s for s in dp._ship_sections if s["label"] == "主炮")
    assert main_sec["items"][0]["value"] == "B 配置", \
        f"主炮应显示 stock(B) 配置数据: {main_sec['items']}"
    print("[OK] 问题3修复: 首次打开默认配置字母取 stock(B)，主炮显示 B 配置数据")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    test_toolbar(app)
    test_full_text_copy(app)
    test_generic_screenshot(app)
    test_ship_screenshot(app)
    test_expand_buttons(app)
    test_text_ammo_and_no_raw(app)
    test_default_config_letter(app)
    print("\n复制功能冒烟测试全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
