"""
version_diff_dialog 冒烟测试 —— 离屏实例化 + 完整比对流程。

用法:
  $env:QT_QPA_PLATFORM="offscreen"
  .venv\\Scripts\\python.exe _archive\\scripts\\test_diff_dialog.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from services.database_service import DatabaseManager
from services.diff_service import DiffService


def _snap(eid, etype, data):
    return (eid, etype, "USA", json.dumps(data, sort_keys=True, ensure_ascii=False))


def _item(category, eid, data):
    return (category, eid, data)


def _seed_db(db: DatabaseManager):
    v1 = db.begin_version("v1.0")
    ship_a1 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 10},
               "artillery": {"A1_Artillery": {"reload_time": 6.4}}}
    ship_b1 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 9}}
    gun_a1 = {"typeinfo": {"type": "Gun", "nation": "USA"}, "caliber": 406}
    db.insert_entities_batch(
        [_item("Ship", "SHIP_A", ship_a1), _item("Ship", "SHIP_B", ship_b1),
         _item("Gun", "GUN_A", gun_a1)], version_code=v1)
    db.save_entity_snapshots(
        [_snap("SHIP_A", "ship", ship_a1), _snap("SHIP_B", "ship", ship_b1),
         _snap("GUN_A", "gun", gun_a1)], version_code=v1)

    v2 = db.begin_version("v2.0")
    ship_a2 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 10},
               "artillery": {"A1_Artillery": {"reload_time": 6.2}}}
    ship_c2 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 8}}
    gun_a2 = dict(gun_a1)
    db.insert_entities_batch(
        [_item("Ship", "SHIP_A", ship_a2), _item("Ship", "SHIP_C", ship_c2),
         _item("Gun", "GUN_A", gun_a2)], version_code=v2)
    db.save_entity_snapshots(
        [_snap("SHIP_A", "ship", ship_a2), _snap("SHIP_C", "ship", ship_c2),
         _snap("GUN_A", "gun", gun_a2)], version_code=v2)


def _wait_idle(app, pred, timeout=15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if pred():
            break
        time.sleep(0.02)
    app.processEvents()
    return pred()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    tmp = tempfile.mkdtemp(prefix="diff_ui_")
    db = DatabaseManager(db_path=os.path.join(tmp, "ui.db"))
    db.initialize()
    _seed_db(db)

    from ui.version_diff_dialog import VersionDiffDialog
    dlg = VersionDiffDialog()
    dlg._svc = DiffService(db)   # 注入临时库

    # 1) 版本加载
    dlg._load_versions()
    assert dlg.base_combo.count() == 2, f"版本下拉应 2 项, 实为 {dlg.base_combo.count()}"
    assert dlg.target_combo.currentIndex() == 0 and dlg.base_combo.currentIndex() == 1
    assert dlg.btn_compare.isEnabled()
    print("[OK] 版本加载: 两个下拉框各 2 项，默认 源=v1.0 / 目标=v2.0")

    # 2) 比对
    dlg._on_compare()
    ok = _wait_idle(app, lambda: not dlg._busy)
    assert ok, "比对超时未完成"
    assert dlg._last_result is not None
    assert dlg.overview_table.rowCount() == 2, "概览应按 2 个类型分 2 行"
    assert dlg.entity_table.rowCount() >= 3, "实体列表应包含 SHIP_A/B/C/GUN_A 相关行"
    print("[OK] 比对完成: 概览 2 行, 实体列表已填充")

    # 3) 类型筛选
    idx = dlg.type_combo.findData("ship")
    dlg.type_combo.setCurrentIndex(idx)
    assert dlg.entity_table.rowCount() >= 1
    ship_rows = [dlg.entity_table.item(i, 1).text() for i in range(dlg.entity_table.rowCount())]
    assert all("SHIP" in s for s in ship_rows), f"筛选后应全为 ship: {ship_rows}"
    print(f"[OK] 类型筛选 ship: {len(ship_rows)} 行")

    # 4) 选中 modified 实体 SHIP_A → 信息面板对照
    dlg.type_combo.setCurrentIndex(0)  # 全部
    row = next(i for i in range(dlg.entity_table.rowCount())
               if dlg.entity_table.item(i, 1).text() == "SHIP_A")
    dlg._on_entity_clicked(row, 1)
    ok = _wait_idle(app, lambda: dlg.field_tree.topLevelItemCount() > 0)
    assert ok, "字段树未填充"
    # 遍历整树（含深层）
    all_items = []
    stack = [dlg.field_tree.topLevelItem(i) for i in range(dlg.field_tree.topLevelItemCount())]
    while stack:
        it = stack.pop()
        all_items.append(it)
        for c in range(it.childCount()):
            stack.append(it.child(c))
    texts = [it.text(0) for it in all_items]
    assert any("reload_time" in t for t in texts), f"信息面板缺 reload_time: {texts}"
    # 信息面板应包含未变字段（完整字段展示，不只差异）
    assert any("nation" in t for t in texts), f"未变字段 nation 应存在: {texts}"
    assert any("level" in t for t in texts), f"未变字段 level 应存在"
    # 未变字段只显示目标值（列2），源版本列留空
    nation_item = next(it for it in all_items if it.text(0) == "nation")
    assert nation_item.text(1) == "" and nation_item.text(2) == "USA", \
        f"未变字段应仅显示目标值: {nation_item.text(1)} | {nation_item.text(2)}"
    # 差异字段对照：reload_time 叶子 源=6.4 目标=6.2
    rl_item = next(it for it in all_items if it.text(0) == "reload_time")
    assert rl_item.text(1) == "6.4" and rl_item.text(2) == "6.2", \
        f"reload_time 对照错误: {rl_item.text(1)} → {rl_item.text(2)}"
    # 分组标题带差异徽标
    assert any("artillery" in t and "差异" in t for t in texts), f"分组缺差异徽标: {texts}"
    print("[OK] 信息面板: 完整字段（含未变）+ reload_time 6.4→6.2 高亮 + 分组差异徽标")

    # 5) 交换
    dlg._on_swap()
    ok = _wait_idle(app, lambda: not dlg._busy)
    assert ok
    assert dlg._last_result is not None
    print("[OK] 交换源/目标后重新比对成功")

    dlg.close()
    db.close()
    print("\nUI 冒烟测试全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
