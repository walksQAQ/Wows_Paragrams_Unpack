"""
版本数据比对服务 —— 跨版本实体级 + 字段级 Diff。

依赖 database_service.DatabaseManager 的多版本架构（entity_snapshots 快照表）。
- 实体级：两个版本按 (entity_id, entity_type) 求 新增 / 删除 / 修改 / 未变
- 字段级：对"修改"实体递归比对两版快照 JSON，输出差异路径 + 新旧值 + 变更类型
- 兼容：老版本无快照时，仅基于 entity_registry 做新增/删除集合比对
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

#: 浮点数值容差：abs(new-old) 小于该阈值视为未变
FLOAT_TOL = 1e-6

#: 变更类型 → 中文标签（供 UI 展示）
KIND_LABELS = {
    "added": "新增",
    "removed": "删除",
    "modified": "修改",
    "unchanged": "未变",
}

KINDS = ("added", "removed", "modified", "unchanged")


class _Missing:
    """哨兵：表示某版本中该字段不存在（用于 added/removed 判定）。"""
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return "<missing>"


_MISSING = _Missing()


def _values_equal(a, b) -> bool:
    """标量相等判定：数值用浮点容差，其余按相等比较。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < FLOAT_TOL
    return a == b


def _fmt_value(v) -> str:
    """把值格式化为可读字符串（用于 UI 展示 / 测试断言）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return json.dumps(list(v), ensure_ascii=False, sort_keys=True)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return str(v)


class FieldDiff:
    """单条字段级差异。kind ∈ {'added','removed','modified'}。"""

    __slots__ = ("path", "kind", "base", "target")

    def __init__(self, path: str, kind: str, base, target):
        self.path = path
        self.kind = kind
        self.base = base
        self.target = target

    def to_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind,
                "base": _fmt_value(self.base), "target": _fmt_value(self.target)}

    def __repr__(self) -> str:  # pragma: no cover
        return f"FieldDiff({self.path!r}, {self.kind!r}, {self.base!r} → {self.target!r})"


class DiffResult:
    """实体级比对结果。"""

    def __init__(self, added=None, removed=None, modified=None, unchanged=None,
                 stats=None, snapshot_available: bool = True):
        self.added: list[tuple[str, str]] = added or []
        self.removed: list[tuple[str, str]] = removed or []
        self.modified: list[tuple[str, str]] = modified or []
        self.unchanged: list[tuple[str, str]] = unchanged or []
        self.stats: dict[str, dict[str, int]] = stats or {}
        #: 两个版本都有快照时可做精确的 modified/unchanged 判断
        self.snapshot_available: bool = snapshot_available

    @property
    def total(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified) + len(self.unchanged)


class DiffService:
    """跨版本比对引擎。"""

    def __init__(self, db):
        self.db = db

    # ── 版本侧信息 ────────────────────────────────────────

    def list_versions(self) -> list[dict]:
        """版本列表（按 version_id 倒序）。"""
        return self.db.list_versions()

    def has_snapshot(self, version_code: str) -> bool:
        """该版本是否已有实体快照。"""
        return self.snapshot_count(version_code) > 0

    def snapshot_count(self, version_code: str) -> int:
        try:
            cur = self.db._conn.execute(
                "SELECT COUNT(*) FROM entity_snapshots WHERE version_code=?", (version_code,))
            return int(cur.fetchone()[0])
        except sqlite3.OperationalError:
            return 0

    # ── 数据读取 ──────────────────────────────────────────

    def _load_snapshot_map(self, version_code: str) -> dict[tuple[str, str], str]:
        """返回 {(entity_id, entity_type): data_json}（全量读入内存做集合 diff）。"""
        try:
            cur = self.db._conn.execute(
                "SELECT entity_id, entity_type, data_json FROM entity_snapshots WHERE version_code=?",
                (version_code,))
            return {(r["entity_id"], r["entity_type"]): r["data_json"] for r in cur.fetchall()}
        except sqlite3.OperationalError:
            return {}

    def _load_entity_keys(self, version_code: str) -> set[tuple[str, str]]:
        """从 entity_registry 读取 (entity_id, entity_type) 键集合（无快照时的兜底）。"""
        try:
            cur = self.db._conn.execute(
                "SELECT entity_id, entity_type FROM entity_registry WHERE version_code=?",
                (version_code,))
            return {(r["entity_id"], r["entity_type"]) for r in cur.fetchall()}
        except sqlite3.OperationalError:
            return set()

    # ── 实体级 Diff ───────────────────────────────────────

    def compare_entities(self, base_vc: str, target_vc: str,
                         type_filter: Optional[str] = None) -> DiffResult:
        """实体级比对 base(旧) vs target(新)。

        - added   = 仅在 target
        - removed = 仅在 base
        - modified = 两边都有但 data_json 不同
        - unchanged = 两边都有且 data_json 相同
        若任一版本无快照，则只能基于 entity_registry 求新增/删除，
        modified/unchanged 为空且 snapshot_available=False。
        """
        base_snap = self._load_snapshot_map(base_vc)
        target_snap = self._load_snapshot_map(target_vc)
        has_snap = bool(base_snap) and bool(target_snap)
        if has_snap:
            base_keys = set(base_snap)
            target_keys = set(target_snap)
        else:
            base_keys = self._load_entity_keys(base_vc)
            target_keys = self._load_entity_keys(target_vc)

        added = sorted(target_keys - base_keys)
        removed = sorted(base_keys - target_keys)
        common = base_keys & target_keys
        modified: list[tuple[str, str]] = []
        unchanged: list[tuple[str, str]] = []
        if has_snap:
            for k in sorted(common):
                if base_snap[k] != target_snap[k]:
                    modified.append(k)
                else:
                    unchanged.append(k)

        if type_filter:
            added = [k for k in added if k[1] == type_filter]
            removed = [k for k in removed if k[1] == type_filter]
            modified = [k for k in modified if k[1] == type_filter]
            unchanged = [k for k in unchanged if k[1] == type_filter]

        result = DiffResult(
            added=added, removed=removed, modified=modified, unchanged=unchanged,
            snapshot_available=has_snap)
        result.stats = self._build_stats(result)
        return result

    @staticmethod
    def _build_stats(result: DiffResult) -> dict[str, dict[str, int]]:
        """按 entity_type 分组统计 added/removed/modified/unchanged 数量。"""
        stats: dict[str, dict[str, int]] = {}
        for kind in KINDS:
            for _eid, etype in getattr(result, kind):
                row = stats.setdefault(etype, {"added": 0, "removed": 0,
                                               "modified": 0, "unchanged": 0})
                row[kind] += 1
        return dict(sorted(stats.items()))

    # ── 字段级 Diff（仅 modified 实体，需快照） ─────────────

    def _get_snapshot(self, version_code: str, entity_id: str) -> Optional[str]:
        try:
            cur = self.db._conn.execute(
                "SELECT data_json FROM entity_snapshots WHERE version_code=? AND entity_id=?",
                (version_code, entity_id))
            row = cur.fetchone()
            return row["data_json"] if row else None
        except sqlite3.OperationalError:
            return None

    def diff_entity_fields(self, base_vc: str, target_vc: str,
                           entity_id: str) -> Optional[list[FieldDiff]]:
        """递归比对两版 JSON dict，返回 [{path, kind, base, target}]。

        path 形如 'typeinfo.level' / 'artillery.A1_Artillery.reload_time' / 'modules[2].id'。
        任一版本无快照或解析失败返回 None。
        """
        base_json = self._get_snapshot(base_vc, entity_id)
        target_json = self._get_snapshot(target_vc, entity_id)
        if base_json is None or target_json is None:
            return None
        try:
            base = json.loads(base_json)
            target = json.loads(target_json)
        except Exception:
            return None
        out: list[FieldDiff] = []
        self._recursive_diff(base, target, "", out)
        return out

    def _recursive_diff(self, base, target, path: str,
                        out: list[FieldDiff]) -> None:
        if isinstance(base, dict) and isinstance(target, dict):
            for k in sorted(set(base) | set(target), key=str):
                child_path = f"{path}.{k}" if path else str(k)
                if k not in base:
                    out.append(FieldDiff(child_path, "added", None, target[k]))
                elif k not in target:
                    out.append(FieldDiff(child_path, "removed", base[k], None))
                else:
                    self._recursive_diff(base[k], target[k], child_path, out)
        elif isinstance(base, list) and isinstance(target, list):
            n = max(len(base), len(target))
            for i in range(n):
                child_path = f"{path}[{i}]"
                if i >= len(base):
                    out.append(FieldDiff(child_path, "added", None, target[i]))
                elif i >= len(target):
                    out.append(FieldDiff(child_path, "removed", base[i], None))
                else:
                    self._recursive_diff(base[i], target[i], child_path, out)
        else:
            if not _values_equal(base, target):
                out.append(FieldDiff(path or "(root)", "modified", base, target))

    # ── 完整字段树（含差异标记，供信息面板式展示） ─────────────

    def get_entity_data(self, version_code: str, entity_id: str) -> Optional[dict]:
        """读取某版本实体的完整快照 dict（无快照返回 None）。"""
        js = self._get_snapshot(version_code, entity_id)
        if js is None:
            return None
        try:
            return json.loads(js)
        except Exception:
            return None

    def build_entity_tree(self, base_vc: str, target_vc: str,
                          entity_id: str) -> Optional[dict]:
        """构建实体完整字段树（含所有未变字段），差异字段带标记。

        返回节点 dict：
          {label, kind, base, target, children, changed_count}
        - children 非空 → 分组节点；kind ∈ {'branch'(子树有差异), 'unchanged'}
        - children 为空 → 叶子节点；kind ∈ {'added','removed','modified','unchanged'}
        - changed_count = 该子树内的差异字段总数
        任一版本无快照且另一版本也有数据时仍返回（视为整实体 added/removed）。
        """
        base = self.get_entity_data(base_vc, entity_id)
        target = self.get_entity_data(target_vc, entity_id)
        if base is None and target is None:
            return None
        # 无快照（实体只存在于一侧）→ 用 _MISSING 表示该侧不存在
        if base is None:
            base = _MISSING
        if target is None:
            target = _MISSING
        return self._build_node("", "", base, target)

    @staticmethod
    def _build_node(path: str, label: str, base, target) -> dict:
        """递归构建一个字段节点（与 _recursive_diff 同一套遍历/容差规则）。"""
        # 一侧缺失 + 另一侧是容器 → 展开容器，所有子字段视为 added/removed
        if base is _MISSING and isinstance(target, (dict, list)):
            return DiffService._build_container_missing(label, target, "added")
        if target is _MISSING and isinstance(base, (dict, list)):
            return DiffService._build_container_missing(label, base, "removed")
        if isinstance(base, dict) and isinstance(target, dict):
            keys = sorted(set(base) | set(target), key=str)
            children = []
            changed = 0
            for k in keys:
                child_path = f"{path}.{k}" if path else str(k)
                child = DiffService._build_node(
                    child_path, str(k),
                    base.get(k, _MISSING), target.get(k, _MISSING))
                children.append(child)
                changed += child["changed_count"]
            return {"label": label, "kind": "branch" if changed else "unchanged",
                    "base": None, "target": None,
                    "children": children, "changed_count": changed}
        if isinstance(base, list) and isinstance(target, list):
            n = max(len(base), len(target))
            children = []
            changed = 0
            for i in range(n):
                child_path = f"{path}[{i}]"
                child = DiffService._build_node(
                    child_path, f"[{i}]",
                    base[i] if i < len(base) else _MISSING,
                    target[i] if i < len(target) else _MISSING)
                children.append(child)
                changed += child["changed_count"]
            return {"label": label, "kind": "branch" if changed else "unchanged",
                    "base": None, "target": None,
                    "children": children, "changed_count": changed}
        # 标量 / 结构变化（dict↔标量 等）
        if base is _MISSING:
            return {"label": label, "kind": "added", "base": None, "target": target,
                    "children": [], "changed_count": 1}
        if target is _MISSING:
            return {"label": label, "kind": "removed", "base": base, "target": None,
                    "children": [], "changed_count": 1}
        if _values_equal(base, target):
            return {"label": label, "kind": "unchanged", "base": base, "target": target,
                    "children": [], "changed_count": 0}
        return {"label": label, "kind": "modified", "base": base, "target": target,
                "children": [], "changed_count": 1}

    @staticmethod
    def _build_container_missing(label: str, container, kind: str) -> dict:
        """一侧缺失、另一侧是 dict/list 时，把容器展开为全 added/removed 子节点。"""
        if isinstance(container, dict):
            items = [(str(k), v) for k, v in sorted(container.items(), key=lambda kv: str(kv[0]))]
        else:  # list
            items = [(f"[{i}]", v) for i, v in enumerate(container)]
        children = []
        changed = 0
        for clabel, v in items:
            child = DiffService._build_node(clabel, clabel, _MISSING, v) if kind == "added" \
                else DiffService._build_node(clabel, clabel, v, _MISSING)
            children.append(child)
            changed += child["changed_count"]
        return {"label": label, "kind": "branch" if changed else "unchanged",
                "base": None, "target": None,
                "children": children, "changed_count": changed}

    # ── 概览 ──────────────────────────────────────────────

    def build_overview(self, base_vc: str, target_vc: str) -> dict:
        """一次性计算实体级 diff + 各 modified 实体的字段变更计数。

        返回 {"result": DiffResult, "field_counts": {entity_id: int}}。
        """
        result = self.compare_entities(base_vc, target_vc)
        field_counts: dict[str, int] = {}
        for eid, _etype in result.modified:
            diffs = self.diff_entity_fields(base_vc, target_vc, eid)
            field_counts[eid] = len(diffs) if diffs else 0
        return {"result": result, "field_counts": field_counts}
