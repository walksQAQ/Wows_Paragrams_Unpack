"""visual_text.py —— 把解码后的 VisualPrototype 还原为 Mod SDK 明文 `.visual` 样式。

明文语法（官方 Mod SDK 导出的 `.visual`，Tab 分隔）：

    <文件名.visual>
        <node>                                         # 节点树，Scene Root 起
            <identifier>    Scene Root    </identifier>
            <transform>
                <row0>  1.0000 0.0000 0.0000 0.0000  </row0>
                ... row1 / row2 / row3
            </transform>
            <rotate>                                   # 旋转限制（可选）
                <min>   -25.0000 -360.0000 -360.0000  </min>
                <max>    25.0000  360.0000  360.0000  </max>
            </rotate>
            <node> ... 子节点 ... </node>
        </node>
        <renderSet>
            <treatAsWorldSpaceObject>    false    </treatAsWorldSpaceObject>
            <node>   disc    </node>                    # 绑定节点（0..N）
            <geometry>
                <vertices>   discShape.vertices   </vertices>
                <primitive>  discShape.indices    </primitive>
                <primitiveGroup>    0
                    <material>
                        <identifier>    PROPELLERMAT_propeller    </identifier>
                        <mfm>   .../Planes_Propeller_2_ryb_alpha.mfm    </mfm>
                    </material>
                </primitiveGroup>
            </geometry>
        </renderSet>
        <boundingBox>
            <min>   -0.5397 0.0000 -0.5212  </min>
            <max>    0.5392 0.3144 0.2530   </max>
        </boundingBox>
    </文件名.visual>

已知的推断规则（对照官方明文实测）：
- `treatAsWorldSpaceObject`：材质标识含 `_skinned` → true，否则 false
  （抽样 2081 个 renderSet 中 2074 个一致）。
- 非蒙皮 renderSet 的 `<node>`：由形状名反推——去掉 `Shape`、`_lod<N>` 与首尾下划线
  （`hull_lod1Shape.vertices` → `hull`；`AD096_Director_MkShape16.vertices` → `AD096_Director_Mk16`；
  抽样 1755 个中 1754 个一致）。
- 蒙皮 renderSet 的 `<node>`：二进制里没有该列表，统一列出骨架中全部 `*_BlendBone`
  节点（集合与官方一致，顺序不同无影响）。
"""

from __future__ import annotations

import re
from typing import List

_ROOT_PARENT = 0xFFFF


def _num(v) -> str:
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _vec(values) -> str:
    return " ".join(_num(x) for x in values)


def shape_node_name(vertices: str) -> str:
    """形状名 → 绑定节点名（去 `Shape`、`_lodN` 与首尾下划线）。"""
    name = (vertices or "").rsplit("/", 1)[-1]
    if name.endswith(".vertices"):
        name = name[: -len(".vertices")]
    name = name.replace("Shape", "").strip("_")
    name = re.sub(r"_lod\d*$", "", name)
    return name.strip("_")


#: 舰船/部件分段的命名令牌（`X_Bow.visual`、`X_MidFront_ports.visual` 等）
SEGMENT_TOKENS = ("Bow", "MidFront", "MidBack", "Stern", "Full")


def segment_name(name: str) -> str:
    """从文件名取分段名（`ASB029_Massachusetts_Black_Bow` → `Bow`）。

    找不到分段令牌时返回空串（如飞机/炮塔的主 visual）。`_lodN` 后缀会去掉。
    """
    base = (name or "").rsplit("/", 1)[-1]
    if base.lower().endswith(".visual"):
        base = base[: -len(".visual")]
    parts = base.split("_")
    for i, part in enumerate(parts):
        if part in SEGMENT_TOKENS:
            seg = "_".join(parts[i:])
            return re.sub(r"_lod\d+$", "", seg)
    return ""


def _node_lines(skeleton: dict, segment: str = "",
                extra_shapes: List[str] | None = None) -> List[str]:
    """骨架 + 渲染集形状 → 嵌套节点树（官方明文结构）。

    官方明文把**渲染集形状**也作为节点写进树里（identity transform），
    外面再套一层段名节点（如 `Bow`），并把骨架里属于该段的节点收进去：

        Scene Root
          Bow                       ← 段名包装（与某个形状同名时复用）
            Bow_crack_MidFront
              Bow_crack_MidFront_in
            Bow_net                 ← 骨架没有、由渲染集补的节点
            Bow_wire

    `extra_shapes` 为非蒙皮渲染集的形状基名（按渲染集顺序）。
    """
    identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    names = list(skeleton.get("name_ids") or [])
    parents = skeleton.get("parent_ids") or []
    matrices = skeleton.get("matrices") or []

    nodes: List[dict] = []
    for i, name in enumerate(names):
        matrix = matrices[i] if i < len(matrices) else None
        nodes.append({
            "name": name,
            "matrix": matrix if (matrix and len(matrix) >= 16) else None,
            "children": [],
        })
    roots: List[dict] = []
    for i, node in enumerate(nodes):
        parent = parents[i] if i < len(parents) else _ROOT_PARENT
        if parent == _ROOT_PARENT or parent >= len(nodes) or parent == i:
            roots.append(node)
        else:
            nodes[parent]["children"].append(node)
    by_name: dict[str, dict] = {node["name"]: node for node in nodes}

    # 没有骨架记录（典型为 LOD visual）时，官方明文仍以 Scene Root 为根
    if not nodes and (segment or extra_shapes):
        scene_node = {"name": "Scene Root", "matrix": None, "children": []}
        roots.append(scene_node)
        by_name["Scene Root"] = scene_node
    scene = next((r for r in roots if r["name"] == "Scene Root"), None)

    # ── 段名包装节点：把该段的骨架节点收进去 ──────────────────────
    seg_node: dict | None = None
    seg_created = False
    if segment:
        seg_node = by_name.get(segment)
        if seg_node is None:
            seg_node = {"name": segment, "matrix": None, "children": []}
            by_name[segment] = seg_node
            seg_created = True
            if scene is not None:
                scene["children"].insert(0, seg_node)
            else:
                roots.append(seg_node)
        if scene is not None and scene is not seg_node:
            moved = [c for c in scene["children"] if c["name"].startswith(segment + "_")]
            if moved:
                scene["children"] = [c for c in scene["children"] if c not in moved]
                seg_node["children"].extend(moved)
            elif seg_created:
                # 骨架**完全平铺**（典型：`X_Bow_ports` 挂点表——二进制 parent_ids
                # 全部指向 Scene Root，本身没有段名节点）。官方明文会新建段名
                # 包装节点，把全部节点收进去：Scene Root → Bow_ports → HP_*/MP_*。
                moved = [c for c in scene["children"] if c is not seg_node]
                scene["children"] = [seg_node]
                seg_node["children"].extend(moved)

    # ── 渲染集形状：缺的补 identity 节点，按名字前缀归位 ──────────
    order = {name: i for i, name in enumerate(extra_shapes or [])}
    shapes_all = list(dict.fromkeys(s for s in (extra_shapes or []) if s))
    # 先短后长：父节点（如 `Bow_crack_MidFront`）先建，子节点（`..._in`）才能找到父
    for shape in sorted(shapes_all, key=lambda s: (s.count("_"), order.get(s, 10 ** 6))):
        if shape in by_name:
            continue
        node = {"name": shape, "matrix": None, "children": []}
        by_name[shape] = node
        parent_node = None
        # 只有 `_in` 变体才嵌到同名前缀节点下（其它 shape 与段名平级，
        # 例如 `Bow_patch_MidFront_wire` 与 `Bow_patch_MidFront` 同级）
        if shape.endswith("_in"):
            for cand_name, cand in by_name.items():
                if cand is node or not shape.startswith(cand_name + "_"):
                    continue
                if parent_node is None or len(cand_name) > len(parent_node["name"]):
                    parent_node = cand
        if parent_node is None:
            if seg_node is not None and shape.startswith(segment + "_"):
                parent_node = seg_node
            else:
                for cand_name, cand in by_name.items():
                    if cand is node or not shape.startswith(cand_name + "_"):
                        continue
                    if parent_node is None or len(cand_name) > len(parent_node["name"]):
                        parent_node = cand
        if parent_node is not None:
            parent_node["children"].append(node)
        elif seg_node is not None:
            seg_node["children"].append(node)
        else:
            roots.append(node)

    # ── 主舰船 visual：官方明文用 `export` 包装平铺骨架 ──────────────
    # 形如 `Scene Root / Full / HP_Bow / HP_Full / HP_MidBack ...`（文件名无分段令牌），
    # 官方 ModSDK 会插入一个 identity 的 `export` 节点把它们收进去。
    if seg_node is None and scene is not None and scene["children"]:
        if "Full" in by_name:
            export_node = {"name": "export", "matrix": None,
                           "children": list(scene["children"])}
            by_name["export"] = export_node
            scene["children"] = [export_node]

    # 段内直接子节点按渲染集顺序排列（官方明文即该顺序）
    for holder in (seg_node, scene):
        if holder is not None:
            holder["children"].sort(
                key=lambda c: order.get(c.get("name"), 10 ** 6))

    lines: List[str] = []

    def emit(node: dict, depth: int) -> None:
        tab = "\t" * depth
        lines.append(f"{tab}<node>")
        lines.append(f"{tab}\t<identifier>\t{node['name']}\t</identifier>")
        matrix = node["matrix"] or identity
        lines.append(f"{tab}\t<transform>")
        for row in range(4):
            lines.append(
                f"{tab}\t\t<row{row}>\t{_vec(matrix[row * 4: row * 4 + 4])}\t</row{row}>")
        lines.append(f"{tab}\t</transform>")
        for child in node["children"]:
            emit(child, depth + 1)
        lines.append(f"{tab}</node>")

    for root in roots:
        emit(root, 1)
    return lines


def _render_set_lines(rs: dict, bind_nodes: List[str] | None = None) -> List[str]:
    ident = rs.get("material_identifier") or ""
    skinned = rs.get("skinned")
    if skinned is None:
        world = "true" if "_skinned" in ident.lower() else "false"
    else:
        world = "true" if skinned else "false"
    lines = [
        "\t<renderSet>",
        f"\t\t<treatAsWorldSpaceObject>\t{world}\t</treatAsWorldSpaceObject>",
    ]
    bbox = rs.get("bounding_box")
    if isinstance(bbox, dict) and bbox.get("min") and bbox.get("max"):
        lines.append("\t\t<boundingBox>")
        lines.append(f"\t\t\t<min>\t{_vec(bbox['min'])}\t</min>")
        lines.append(f"\t\t\t<max>\t{_vec(bbox['max'])}\t</max>")
        lines.append("\t\t</boundingBox>")
    if world == "false":
        node = shape_node_name(rs.get("vertices") or "")
        if node:
            lines.append(f"\t\t<node>\t{node}\t</node>")
    else:
        # 蒙皮：优先用记录里自带的绑定节点列表（顺序与官方一致），无则回退骨架推断
        for node in rs.get("nodes") or bind_nodes or []:
            lines.append(f"\t\t<node>\t{node}\t</node>")
    lines += [
        "\t\t<geometry>",
        f"\t\t\t<vertices>\t{rs.get('vertices') or ''}\t</vertices>",
        f"\t\t\t<primitive>\t{rs.get('primitive') or ''}\t</primitive>",
        "\t\t\t<primitiveGroup>\t0",
        "\t\t\t\t<material>",
        f"\t\t\t\t\t<identifier>\t{ident}\t</identifier>",
    ]
    mfm = rs.get("material_mfm") or ""
    if mfm:
        lines.append(f"\t\t\t\t\t<mfm>\t{mfm}\t</mfm>")
    lines += [
        "\t\t\t\t</material>",
        "\t\t\t</primitiveGroup>",
        "\t\t</geometry>",
        "\t</renderSet>",
    ]
    return lines


def _as_visual_view(decoded: dict) -> dict:
    """把 SkeletonPrototype 的解码结果转成 VisualPrototype 视角。

    Lesta 的 `.visual` 拆成两条记录：`@content/...` 是 SkeletonPrototype（骨架），
    `content/...` 是 VisualPrototype（渲染集）；`decode_file` 会互相合并。
    若用户选中的是骨架那条（导出按钮也可用），这里用它的 `visual` 字段 + 自身骨架
    拼出等价的 VisualPrototype 视图，否则会导出成空文件。
    """
    if decoded.get("_type") != "SkeletonPrototype":
        return decoded
    out = dict(decoded.get("visual") or {})
    out["_type"] = "VisualPrototype"
    out["skeleton"] = {
        "name_ids": decoded.get("name_ids") or [],
        "parent_ids": decoded.get("parent_ids") or [],
        "matrices": decoded.get("matrices") or [],
    }
    if not out.get("bounding_box"):
        bb = decoded.get("bounding_box")
        if isinstance(bb, dict):
            out["bounding_box"] = bb
    return out


def format_visual_text(decoded: dict, name: str = "",
                      infer_skinned_nodes: bool = True,
                      wows_type: str = "") -> str:
    """VisualPrototype 解码结果 → 明文 `.visual` 文本。

    ⚠️ 两套格式（对应两套官方 SDK，**不能混用**）：
      - 寄服（Wargaming，wgmods/ModSDK）：
        `<skeleton>` / `<properties>` / `<boundingBox>` / `<renderSets>`（含 `<name>`
        `<nodes>` `<material>`）/ `<lods>` 五段结构；节点树只来自 visual 记录本身，
        MP_*/SP_* 在独立的 `.skel_ext` 里。
      - 莱服（Lesta，ModsSDK_*.zip）：
        扁平结构——顶层直接 `<node>` 树 + `<renderSet>`（内含 `<geometry>` 与
        渲染集 bbox）+ 末尾 `<boundingBox>`；骨架来自同 rec 的 SkeletonPrototype。

    Args:
        decoded: :func:`uncode_assets.decoders.decode_visual`（或 WG 版）的返回值；
            Korabli 下需已合并 `skeleton`（`AssetsBinVfs.decode_file` 自动合并）。
        name: 根元素名（通常为文件名，如 `AAB705_Martin_T4M_proto.visual`）。
        infer_skinned_nodes: 二进制里没有 renderSet 的骨骼绑定列表时，
            用骨架中的 `*_BlendBone` 节点补全（仅 Lesta 格式使用）。
        wows_type: `"Wargaming"` → 寄服格式；其它 → 莱服格式（默认按记录结构自动判断）。
    """
    root = (name or "visual.visual").strip()
    decoded = _as_visual_view(decoded)
    # 寄服/莱服两套格式：寄服走 visual_wg_text（skeleton/properties/bbox/renderSets/lods）
    from .visual_wg_text import format_wg_visual_text, is_wg_visual
    if is_wg_visual(decoded, wows_type):
        return format_wg_visual_text(decoded, root)
    skeleton = decoded.get("skeleton") or {}
    render_sets = decoded.get("render_sets") or []
    bind_nodes: List[str] = []
    if infer_skinned_nodes:
        names = skeleton.get("name_ids") or []
        bind_nodes = [n for n in names if n.endswith("_BlendBone")]

    lines: List[str] = [f"<{root}>"]
    extra_shapes: List[str] = []
    for rs in render_sets:
        if "_skinned" in (rs.get("material_identifier") or "").lower():
            continue
        base = shape_node_name(rs.get("vertices") or "")
        if base and base not in extra_shapes:
            extra_shapes.append(base)
    lines += _node_lines(skeleton, segment_name(root), extra_shapes)
    for rs in render_sets:
        lines += _render_set_lines(rs, bind_nodes)
    bbox = decoded.get("bounding_box")
    if isinstance(bbox, dict):
        mn, mx = bbox.get("min"), bbox.get("max")
        if mn and mx:
            lines.append("\t<boundingBox>")
            lines.append(f"\t\t<min>\t{_vec(mn)}\t</min>")
            lines.append(f"\t\t<max>\t{_vec(mx)}\t</max>")
            lines.append("\t</boundingBox>")
    lines.append(f"</{root}>")
    return "\n".join(lines)
