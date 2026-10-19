"""skel_ext_text.py —— 把解码后的 SkeletonExtenderPrototype 还原为 Mod SDK 明文 `.skel_ext`。

官方明文样式（ModsSDK 原文实测，Tab 分隔，1 个 Tab 一级）：

    <AGS145_5in54.skel_ext>
        <exported>    true    </exported>
        <node>
            <identifier>    SP_YMS100_YGBS_M_1    </identifier>
            <parent>    Rotate_X    </parent>
            <transform>
                <row0>  0.3874 0.0000 0.0000 0.0000  </row0>
                <row1>  0.0000 0.3874 0.0000 0.0000  </row1>
                <row2>  0.0000 0.0000 0.3874 0.0000  </row2>
                <row3>  -0.0919 0.0000 0.1358 1.0000 </row3>
            </transform>
        </node>
        ...
    </AGS145_5in54.skel_ext>

要点：
- `<node>` 是**平铺列表**（不嵌套），父级用 `<parent>` 名引用（如 `Rotate_X` / `Roll_Back1` / `Scene Root`）。
- 变换 4 行，每行 4 个 4 位小数；row3 是平移 + w=1。
- `<exported>` 对应记录头 +0x00 的 flag（1 = 带骨架，官方明文写 true）。
"""

from __future__ import annotations

from typing import List

_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
             0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _num(v) -> str:
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _vec(values) -> str:
    return " ".join(_num(x) for x in values)


def format_skel_ext_text(decoded: dict, name: str = "") -> str:
    """SkeletonExtenderPrototype 解码结果 → 明文 `.skel_ext` 文本。

    Args:
        decoded: :func:`uncode_assets.decoders.decode_skeleton_extender` 的返回值。
        name: 根元素名（通常为文件名，如 `AGS145_5in54.skel_ext`）。
    """
    root = (name or "skeleton_extender.skel_ext").strip()
    flag = decoded.get("flag")
    exported = "true" if flag else "false"

    names: List[str] = list(decoded.get("name_ids") or [])
    parents: List[str] = list(decoded.get("parent_name_ids") or [])
    matrices = decoded.get("matrices") or []

    lines: List[str] = [f"<{root}>", f"\t<exported>\t{exported}\t</exported>"]
    for i, node_name in enumerate(names):
        matrix = matrices[i] if i < len(matrices) and len(matrices[i]) >= 16 else _IDENTITY
        parent = parents[i] if i < len(parents) else "Scene Root"
        lines.append("\t<node>")
        lines.append(f"\t\t<identifier>\t{node_name}\t</identifier>")
        lines.append(f"\t\t<parent>\t{parent}\t</parent>")
        lines.append("\t\t<transform>")
        for row in range(4):
            lines.append(
                f"\t\t\t<row{row}>\t{_vec(matrix[row * 4: row * 4 + 4])}\t</row{row}>")
        lines.append("\t\t</transform>")
        lines.append("\t</node>")
    lines.append(f"</{root}>")
    return "\n".join(lines)
