"""model_text.py —— 把解码后的 ModelPrototype 还原为 Mod SDK 明文 `.model` 样式。

明文语法（官方 Mod SDK 导出的 `.model`，Tab 分隔）：

    <文件名.model>
        <castsShadow>    true    </castsShadow>
        <parent>     content/.../X_lod1    </parent>        # 可缺省
        <extent>     6.0000    </extent>
        <nodefullVisual>    content/.../X    </nodefullVisual>
        <metaData>    Lesta Studio    </metaData>
    </文件名.model>

要点：
- `<parent>` / `<nodefullVisual>` 里的资源路径**不带扩展名**（`.model` / `.visual` 去掉）；
- `castsShadow` 来自 ModelPrototype 的 count 字段 bit1（实测 8/9 → false，10/11 → true）；
- `extent` 取记录 `+0x10` 的 f32（`+0x14` 实测恒等于它）。
"""

from __future__ import annotations

from typing import List


def _strip_ext(path: str) -> str:
    """去掉资源扩展名（`.model` / `.visual`），官方明文里不写。"""
    low = path.lower()
    for ext in (".model", ".visual"):
        if low.endswith(ext):
            return path[: -len(ext)]
    return path


def _num(v) -> str:
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def format_model_text(decoded: dict, name: str = "", wows_type: str = "") -> str:
    """ModelPrototype 解码结果 → 明文 `.model` 文本。

    ⚠️ 两套格式：寄服（WG）`<visual>/<animations>/<dyes>/<skeletonExtenders>/<metaData>`；
    莱服（Lesta）`<castsShadow>/<parent>/<extent>/<nodefullVisual>/<metaData>`。
    """
    if (wows_type or "").lower() == "wargaming" or (
            "skelExtResIds" in decoded and "nodefullVisual" not in decoded):
        from .model_wg_text import format_wg_model_text
        return format_wg_model_text(decoded, name)

    root = (name or "model.model").strip()
    lines: List[str] = [f"<{root}>"]

    casts = decoded.get("castsShadow")
    if casts is None:  # 兼容旧解码结果：用 count 的 bit1 兜底
        casts = bool((decoded.get("count") or 0) & 0x02)
    lines.append(f"\t<castsShadow>\t{'true' if casts else 'false'}\t</castsShadow>")

    parent = _strip_ext(decoded.get("parent") or "")
    if parent:
        lines.append(f"\t<parent>\t{parent}\t</parent>")

    extent = decoded.get("extent")
    if isinstance(extent, dict):
        val = extent.get("distance_a")
        if val is None:
            val = extent.get("distance_b")
        if val is not None:
            lines.append(f"\t<extent>\t{_num(val)}\t</extent>")

    visual = _strip_ext(decoded.get("nodefullVisual") or "")
    if visual:
        lines.append(f"\t<nodefullVisual>\t{visual}\t</nodefullVisual>")

    meta = decoded.get("metaData") or "Lesta Studio"
    lines.append(f"\t<metaData>\t{meta}\t</metaData>")

    lines.append(f"</{root}>")
    return "\n".join(lines)
