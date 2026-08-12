"""
diff_service 单元验证 —— 构造两个小版本数据（含增/删/改/同），断言比对结果。

用法: .venv\\Scripts\\python.exe _archive\\scripts\\test_diff_service.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from services.database_service import DatabaseManager
from services.diff_service import DiffService, DiffResult


def _snap(eid, etype, data):
    return (eid, etype, "USA", json.dumps(data, sort_keys=True, ensure_ascii=False))


def _item(category, eid, data):
    return (category, eid, data)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="diff_test_")
    db_path = os.path.join(tmp, "test.db")
    db = DatabaseManager(db_path=db_path)
    db.initialize()

    # ── 版本 1：3 个实体 ──
    v1 = db.begin_version("v1.0")
    ship_a1 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 10},
               "artillery": {"A1_Artillery": {"reload_time": 6.4, "max_range": 18000.0}},
               "modules": [{"id": "M1", "hp": 100}]}
    ship_b1 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 9}}
    gun_a1 = {"typeinfo": {"type": "Gun", "nation": "USA"},
              "caliber": 406, "reload_time": 30.0}
    db.insert_entities_batch(
        [_item("Ship", "SHIP_A", ship_a1),
         _item("Ship", "SHIP_B", ship_b1),
         _item("Gun", "GUN_A", gun_a1)], version_code=v1)
    db.save_entity_snapshots(
        [_snap("SHIP_A", "ship", ship_a1),
         _snap("SHIP_B", "ship", ship_b1),
         _snap("GUN_A", "gun", gun_a1)], version_code=v1)

    # ── 版本 2：SHIP_A 改 reload_time；SHIP_B 删除；新增 SHIP_C；GUN_A 未变 ──
    v2 = db.begin_version("v2.0")
    ship_a2 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 10},
               "artillery": {"A1_Artillery": {"reload_time": 6.2, "max_range": 18000.0}},
               "modules": [{"id": "M1", "hp": 100}]}
    ship_c2 = {"typeinfo": {"type": "Ship", "nation": "USA", "level": 8}}
    gun_a2 = dict(gun_a1)
    db.insert_entities_batch(
        [_item("Ship", "SHIP_A", ship_a2),
         _item("Ship", "SHIP_C", ship_c2),
         _item("Gun", "GUN_A", gun_a2)], version_code=v2)
    db.save_entity_snapshots(
        [_snap("SHIP_A", "ship", ship_a2),
         _snap("SHIP_C", "ship", ship_c2),
         _snap("GUN_A", "gun", gun_a2)], version_code=v2)

    svc = DiffService(db)

    # ── 断言 1：快照写入数量 ──
    assert svc.snapshot_count(v1) == 3, f"v1 快照数 {svc.snapshot_count(v1)} != 3"
    assert svc.snapshot_count(v2) == 3, f"v2 快照数 {svc.snapshot_count(v2)} != 3"
    print("[OK] 快照写入: v1=3, v2=3")

    # ── 断言 2：实体级 diff（v1 旧 → v2 新）──
    r: DiffResult = svc.compare_entities(v1, v2)
    assert r.snapshot_available is True
    assert {k[0] for k in r.added} == {"SHIP_C"}, f"added={r.added}"
    assert {k[0] for k in r.removed} == {"SHIP_B"}, f"removed={r.removed}"
    assert {k[0] for k in r.modified} == {"SHIP_A"}, f"modified={r.modified}"
    assert {k[0] for k in r.unchanged} == {"GUN_A"}, f"unchanged={r.unchanged}"
    # 按类型统计
    assert r.stats["ship"] == {"added": 1, "removed": 1, "modified": 1, "unchanged": 0}
    assert r.stats["gun"] == {"added": 0, "removed": 0, "modified": 0, "unchanged": 1}
    print("[OK] 实体级 diff: added=SHIP_C, removed=SHIP_B, modified=SHIP_A, unchanged=GUN_A")
    print(f"      stats = {r.stats}")

    # ── 断言 3：类型筛选 ──
    r_gun = svc.compare_entities(v1, v2, type_filter="gun")
    assert len(r_gun.modified) == 0 and len(r_gun.unchanged) == 1
    assert len(r_gun.added) == 0 and len(r_gun.removed) == 0
    print("[OK] 类型筛选 type_filter=gun 生效")

    # ── 断言 4：字段级 diff（SHIP_A 的 reload_time 6.4→6.2）──
    diffs = svc.diff_entity_fields(v1, v2, "SHIP_A")
    assert diffs is not None
    pairs = {(d.path, d.kind) for d in diffs}
    assert ("artillery.A1_Artillery.reload_time", "modified") in pairs, pairs
    target = [d for d in diffs if d.path == "artillery.A1_Artillery.reload_time"][0]
    assert abs(target.base - 6.4) < 1e-9 and abs(target.target - 6.2) < 1e-9
    print("[OK] 字段级 diff: reload_time 6.4 → 6.2 (path=artillery.A1_Artillery.reload_time)")

    # ── 断言 4.5：完整字段树（信息面板）──
    tree = svc.build_entity_tree(v1, v2, "SHIP_A")
    assert tree is not None and tree["changed_count"] == 1, f"changed_count={tree and tree['changed_count']}"
    # 收集所有叶子 (label, kind, base, target)
    leaves = {}

    def _walk(node):
        if node["children"]:
            for ch in node["children"]:
                _walk(ch)
        else:
            leaves[(node["label"], node["kind"])] = node
    _walk(tree)
    # 未变字段也应包含（完整信息面板，不只差异）
    assert any(l == "max_range" for l, _ in leaves), "未变字段 max_range 应存在于信息面板"
    assert any(l == "level" for l, _ in leaves), "未变字段 typeinfo.level 应存在"
    # 差异字段
    rl = [v for (l, k), v in leaves.items() if l == "reload_time" and k == "modified"]
    assert rl and abs(rl[0]["base"] - 6.4) < 1e-9 and abs(rl[0]["target"] - 6.2) < 1e-9
    # 顶层分组存在且带差异计数
    top_labels = {ch["label"]: ch for ch in tree["children"]}
    assert "artillery" in top_labels and top_labels["artillery"]["changed_count"] == 1
    print("[OK] 完整字段树: 含未变字段 + reload_time 标记 modified + 分组差异计数")

    # ── 断言 4.6：新增/删除实体的信息面板（整实体展开为 added/removed）──
    def _leaves(node):
        if node["children"]:
            for ch in node["children"]:
                yield from _leaves(ch)
        else:
            yield node

    tree_added = svc.build_entity_tree(v1, v2, "SHIP_C")   # 仅 v2 有
    assert tree_added is not None and tree_added["changed_count"] > 0
    added_leaves = list(_leaves(tree_added))
    assert added_leaves and all(n["kind"] == "added" for n in added_leaves), \
        f"新增实体所有字段应 kind=added: {[n['kind'] for n in added_leaves]}"
    assert "typeinfo" in {ch["label"] for ch in tree_added["children"]}
    tree_removed = svc.build_entity_tree(v1, v2, "SHIP_B")  # 仅 v1 有
    assert tree_removed is not None and tree_removed["changed_count"] > 0
    removed_leaves = list(_leaves(tree_removed))
    assert removed_leaves and all(n["kind"] == "removed" for n in removed_leaves), \
        f"删除实体所有字段应 kind=removed: {[n['kind'] for n in removed_leaves]}"
    # 未变实体
    tree_same = svc.build_entity_tree(v1, v2, "GUN_A")
    assert tree_same is not None and tree_same["changed_count"] == 0
    print("[OK] 新增/删除/未变实体的信息面板树: kind 标记正确")

    # ── 断言 5：级联删除（purge 保留 1 个版本 → v1 快照清除）──
    db.purge_old_versions(keep_count=1)
    assert svc.has_snapshot(v1) is False, "v1 快照应被级联删除"
    assert svc.snapshot_count(v1) == 0
    assert svc.has_snapshot(v2) is True
    print("[OK] purge_old_versions 级联删除 v1 快照")

    # ── 断言 6：无快照兜底（仅实体级）──
    v3 = db.begin_version("v3.0")
    db.insert_entities_batch([_item("Ship", "SHIP_D", {"typeinfo": {"type": "Ship"}})],
                             version_code=v3)
    # v3 不写快照
    r2 = svc.compare_entities(v2, v3)
    assert r2.snapshot_available is False
    assert {k[0] for k in r2.added} == {"SHIP_D"}
    assert r2.modified == [] and r2.unchanged == []
    print("[OK] 无快照版本: snapshot_available=False，仅实体级新增/删除")

    db.close()
    print("\n全部断言通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
