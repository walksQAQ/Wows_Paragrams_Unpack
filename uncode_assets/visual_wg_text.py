"""visual_wg_text.py —— 寄服（Wargaming）官方 `.visual` 明文导出。

⚠️ 与莱服（Lesta）格式**完全不同**，两套规则不能混用：

寄服（参考 wgmods/ModSDK 的 `ModsSDK_15.9.0/**/*.visual`）：

    <X.visual>
        <skeleton>                       # 嵌套节点树（Scene Root 起）
            <node>
                <identifier>  Scene Root  </identifier>
                <transform> row0..row3 </transform>
                <node> ... </node>
            </node>
        </skeleton>
        <properties>
            <underwaterModel> false </underwaterModel>
            <abovewaterModel> true  </abovewaterModel>
        </properties>
        <boundingBox>
            <min> ... </min>
            <max> ... </max>
        </boundingBox>
        <renderSets>
            <renderSet>
                <name>  TurretShape  </name>
                <treatAsWorldSpaceObject> true </treatAsWorldSpaceObject>
                <nodes>                       # 蒙皮绑定的骨骼
                    <node> Roll_Back1_BlendBone </node>
                </nodes>
                <material>
                    <identifier> TL2_SHIPMAT_PBS_Gun_skinned </identifier>
                    <mfm> .../X_skinned.mfm </mfm>
                </material>
            </renderSet>
        </renderSets>
        <lods>
            <lod>
                <extent> 3.0000 </extent>
                <castsShadow> true </castsShadow>
                <renderSets>
                    <renderSet> TurretShape </renderSet>
                </renderSets>
            </lod>
        </lods>
    </X.visual>

要点：
- 节点树只来自 visual 记录本身；MP_*/SP_* 挂在**独立的 `.skel_ext`** 里（另有导出）。
- renderSet 里没有 `<geometry>`（与莱服不同）：形状名写在 `<name>`。
- 记录自带 LOD 表，导出 `<lods>`（extent / castsShadow / renderSets）。
"""

from __future__ import annotations

from typing import List

_ROOT_PARENT = 0xFFFF


def _num(v) -> str:
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _vec(values) -> str:
    return " ".join(_num(x) for x in values)


def _bool_text(v) -> str:
    return "true" if v else "false"


def is_wg_visual(decoded: dict, wows_type: str = "") -> bool:
    """是否按寄服（WG）格式输出。

    显式传入 Wargaming 优先；否则按记录结构判断：WG 记录带 `nodes`（dict）与
    `lods`，莱服记录是合并后的 `skeleton` + `render_sets`（无 lods）。
    """
    if (wows_type or "").lower() == "wargaming":
        return True
    if decoded.get("skeleton"):
        return False
    nodes = decoded.get("nodes")
    return isinstance(nodes, dict) and bool(nodes.get("name_ids"))


def format_wg_visual_text(decoded: dict, name: str = "") -> str:
    """VisualPrototype（WG 记录）解码结果 → 寄服官方 `.visual` 明文。"""
    root = (name or "visual.visual").strip()
    identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]

    nodes = decoded.get("nodes") or {}
    names = list(nodes.get("name_ids") or [])
    parents = nodes.get("parent_ids") or []
    matrices = nodes.get("matrices") or []

    tree: List[dict] = []
    for i, nm in enumerate(names):
        m = matrices[i] if i < len(matrices) and len(matrices[i]) >= 16 else None
        tree.append({"name": nm, "matrix": m, "children": []})
    roots: List[dict] = []
    for i, nd in enumerate(tree):
        p = parents[i] if i < len(parents) else _ROOT_PARENT
        if p == _ROOT_PARENT or p >= len(tree) or p == i:
            roots.append(nd)
        else:
            tree[p]["children"].append(nd)

    lines: List[str] = [f"<{root}>"]

    # ── skeleton ────────────────────────────────────────────────
    if roots:
        lines.append("\t<skeleton>")

        def emit(nd: dict, depth: int) -> None:
            tab = "\t" * depth
            lines.append(f"{tab}<node>")
            lines.append(f"{tab}\t<identifier>\t{nd['name']}\t</identifier>")
            m = nd["matrix"] or identity
            lines.append(f"{tab}\t<transform>")
            for r in range(4):
                lines.append(f"{tab}\t\t<row{r}>\t{_vec(m[r * 4: r * 4 + 4])}\t</row{r}>")
            lines.append(f"{tab}\t</transform>")
            for child in nd["children"]:
                emit(child, depth + 1)
            lines.append(f"{tab}</node>")

        for r in roots:
            emit(r, 2)
        lines.append("\t</skeleton>")

    # ── properties ──────────────────────────────────────────────
    lines.append("\t<properties>")
    lines.append(f"\t\t<underwaterModel>\t{_bool_text(decoded.get('underwater_model'))}"
                 "\t</underwaterModel>")
    lines.append(f"\t\t<abovewaterModel>\t{_bool_text(decoded.get('abovewater_model'))}"
                 "\t</abovewaterModel>")
    lines.append("\t</properties>")

    # ── boundingBox ─────────────────────────────────────────────
    bbox = decoded.get("bounding_box") or {}
    if bbox.get("min") and bbox.get("max"):
        lines.append("\t<boundingBox>")
        lines.append(f"\t\t<min>\t{_vec(bbox['min'])}\t</min>")
        lines.append(f"\t\t<max>\t{_vec(bbox['max'])}\t</max>")
        lines.append("\t</boundingBox>")

    # ── renderSets ──────────────────────────────────────────────
    render_sets = decoded.get("render_sets") or []
    if render_sets:
        lines.append("\t<renderSets>")
        for rs in render_sets:
            shape = (rs.get("name") or "").strip()
            if not shape:
                shape = (rs.get("vertices") or "").replace(".vertices", "")
            lines.append("\t\t<renderSet>")
            lines.append(f"\t\t\t<name>\t{shape}\t</name>")
            lines.append(f"\t\t\t<treatAsWorldSpaceObject>\t"
                         f"{_bool_text(rs.get('skinned'))}\t</treatAsWorldSpaceObject>")
            bind = rs.get("nodes") or []
            if bind:
                lines.append("\t\t\t<nodes>")
                for b in bind:
                    lines.append(f"\t\t\t\t<node>\t{b}\t</node>")
                lines.append("\t\t\t</nodes>")
            lines.append("\t\t\t<material>")
            lines.append(f"\t\t\t\t<identifier>\t{rs.get('material_identifier') or ''}"
                         "\t</identifier>")
            mfm = rs.get("material_mfm") or ""
            if mfm:
                lines.append(f"\t\t\t\t<mfm>\t{mfm}\t</mfm>")
            lines.append("\t\t\t</material>")
            lines.append("\t\t</renderSet>")
        lines.append("\t</renderSets>")

    # ── lods ────────────────────────────────────────────────────
    lods = decoded.get("lods") or []
    if lods:
        lines.append("\t<lods>")
        for lod in lods:
            lines.append("\t\t<lod>")
            lines.append(f"\t\t\t<extent>\t{_num(lod.get('extent'))}\t</extent>")
            lines.append(f"\t\t\t<castsShadow>\t{_bool_text(lod.get('casts_shadow'))}"
                         "\t</castsShadow>")
            rs_names = lod.get("render_set_names") or []
            if rs_names:
                lines.append("\t\t\t<renderSets>")
                for nm in rs_names:
                    lines.append(f"\t\t\t\t<renderSet>\t{nm}\t</renderSet>")
                lines.append("\t\t\t</renderSets>")
            lines.append("\t\t</lod>")
        lines.append("\t</lods>")

    lines.append(f"</{root}>")
    return "\n".join(lines)
