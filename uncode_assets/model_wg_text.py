"""model_wg_text.py —— 寄服（Wargaming）官方 `.model` 明文导出。

⚠️ 与莱服（Lesta）格式**完全不同**：

寄服（参考 wgmods/ModSDK 的 `ModsSDK_15.9.0/**/*.model`）：

    <X.model>
        <visual>    PnFMods/ModsSDK.zip/<Ship>/gun/X.visual    </visual>
        <animations />                                  # 无动画时自闭合
        <animations>                                    # 有动画时逐个列出 .ssm 路径
            <animation> content/animation_state_machines/.../X.ssm </animation>
        </animations>
        <dyes />                                        # 无染色时自闭合
        <skeletonExtenders />                           # 无扩展时自闭合
        <skeletonExtenders>
            <skeletonExtender> .../X.skel_ext </skeletonExtender>
        </skeletonExtenders>
        <metaData>  Wargaming.net   </metaData>
    </X.model>

- `<visual>` 是**带扩展名**的完整路径（莱服用 `<nodefullVisual>` 且不带扩展名）。
- 寄服没有 castsShadow / parent / extent 三个字段。
- `<dye>` 内部结构在官方样例里没有非空样本，这里按 DyeEntry 字段
  （matter / replaces / tint 名与材质路径）尽力输出，可能有偏差。
"""

from __future__ import annotations

from typing import List


def _t(tag: str, value: str, depth: int = 1) -> str:
    tab = "\t" * depth
    return f"{tab}<{tag}>\t{value}\t</{tag}>"


def format_wg_model_text(decoded: dict, name: str = "") -> str:
    """ModelPrototype（WG 记录）解码结果 → 寄服官方 `.model` 明文。"""
    root = (name or "model.model").strip()
    lines: List[str] = [f"<{root}>"]

    lines.append(_t("visual", decoded.get("visual") or ""))

    animations = decoded.get("animations") or []
    if not animations:
        lines.append("\t<animations />")
    else:
        lines.append("\t<animations>")
        for a in animations:
            lines.append(_t("animation", str(a), depth=2))
        lines.append("\t</animations>")

    dyes = decoded.get("dyes") or []
    if not dyes:
        lines.append("\t<dyes />")
    else:
        lines.append("\t<dyes>")
        for dye in dyes:
            lines.append("\t\t<dye>")
            lines.append(_t("matter", dye.get("matter") or "", depth=3))
            lines.append(_t("replaces", dye.get("replaces") or "", depth=3))
            names = dye.get("tint_names") or []
            mats = dye.get("tint_materials") or []
            for i, nm in enumerate(names):
                lines.append("\t\t\t<tint>")
                lines.append(_t("name", str(nm), depth=4))
                mat = mats[i] if i < len(mats) else ""
                if mat:
                    lines.append(_t("material", mat, depth=4))
                lines.append("\t\t\t</tint>")
            lines.append("\t\t</dye>")
        lines.append("\t</dyes>")

    extenders = [x for x in (decoded.get("skelExtResIds") or []) if x]
    if not extenders:
        lines.append("\t<skeletonExtenders />")
    else:
        lines.append("\t<skeletonExtenders>")
        for ext in extenders:
            lines.append(_t("skeletonExtender", ext, depth=2))
        lines.append("\t</skeletonExtenders>")

    meta = decoded.get("metaData") or "Wargaming.net"
    lines.append(_t("metaData", meta))

    lines.append(f"</{root}>")
    return "\n".join(lines)
