"""mfm_text.py —— 把解码后的 MaterialPrototype 还原为 Mod SDK 明文 `.mfm` 样式。

明文语法（官方 Mod SDK 导出的 `.mfm`，文本元素，Tab 分隔）：

    <文件名.mfm>
        <parentMfm>    被继承材质路径.mfm    </parentMfm>        # 0..N 个
        <fx>           shaders/materials/xxx.fx    </fx>          # 可缺省
        <collisionFlags>    0    </collisionFlags>
        <property>   属性名
            <Texture>  资源路径.dds  </Texture>
        </property>
        <property>   g_detailScaleU
            <Float>    16.0000  </Float>
        </property>
        <property>   offsetScaleMatIdArr
            <Vector4_69>    -0.0050 0.0000 37.7090 39.4090 </Vector4_69>
            <Vector4_70>    -0.3870 0.7230 37.7090 39.4100 </Vector4_70>
        </property>
    </文件名.mfm>

要点：
- 值元素名与属性类型一一对应：`Bool` / `Int` / `Float` / `Texture` / `Vector2`
  / `Vector3` / `Vector4` / `Matrix`。
- 数组属性（INDEXED 材质的 vec4 数组）按**材质 ID 稀疏写出**：标签后缀即 matId
  （`Vector4_69` = 第 69 号材质），全零项省略。
"""

from __future__ import annotations

from typing import Iterable, List, Optional

#: 属性类型（MaterialPrototype type_raw）→ 明文值元素名
TYPE_TAGS = {
    0: "Bool",
    1: "Int",
    2: "Float",
    3: "Float",
    4: "Texture",
    5: "Vector2",
    6: "Vector3",
    7: "Vector4",
    8: "Matrix",
}

#: 数组属性支持的明文标签（后缀 matId）
_ARRAY_TAGS = {"Vector2", "Vector3", "Vector4", "Matrix"}


def _num(v) -> str:
    """浮点统一 4 位小数（与官方明文一致）。"""
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _vec_text(values: Iterable) -> str:
    return " ".join(_num(x) for x in values)


def _is_zero_vec(values) -> bool:
    try:
        return all(abs(float(x)) < 1e-9 for x in values)
    except (TypeError, ValueError):
        return False


def format_mfm_text(
    decoded: dict,
    name: str = "",
    fx: str = "",
    parent_mfms: Optional[List[str]] = None,
) -> str:
    """MaterialPrototype 解码结果 → 明文 `.mfm` 文本。

    Args:
        decoded: :func:`uncode_assets.decoders.decode_material` 的返回值。
        name: 根元素名（通常为文件名，如 `ABS077_Iowa_Azurlane.mfm`）。
        fx: `.fx` 路径（已解析的完整路径）；为空则省略 `<fx>`。
        parent_mfms: `<parentMfm>` 列表（继承链）；二进制里没有，通常为空。

    `<collisionFlags>` 是 Mod SDK 明文里的独立字段，**取值恒为 0**、与材质记录
    +0x02 的 flags 无关（实测：Lesta 26.10 SDK 13,068 处、WG 15.9 SDK 全部
    29,184 个 .mfm 都是 0；二进制 flags 却常见 1/2/3 或 0x300 等）。
    两服的**写法**不同：WG 15.9 每个 .mfm 都写这一行；Lesta 26.10 只写了 63.5%
    （glass / grid / mesh_decal / indexed 系列几乎不写，ship PBS 系列 50~92%）。
    本函数统一按 WG 口径**始终写出**（值为 SDK 的 0），信息更完整且两服都合法。
    """
    root = (name or "material.mfm").strip()
    lines: List[str] = [f"<{root}>"]
    for parent in parent_mfms or []:
        if parent:
            lines.append(f"\t<parentMfm>\t{parent}\t</parentMfm>")
    if fx:
        lines.append(f"\t<fx>\t{fx}\t</fx>")
    try:
        flags = int(decoded.get("collisionFlags") or 0)
    except (TypeError, ValueError):
        flags = 0
    lines.append(f"\t<collisionFlags>\t{flags}\t</collisionFlags>")

    for prop in decoded.get("properties") or []:
        pname = prop.get("name") or "?"
        ptype = prop.get("type_raw")
        tag = TYPE_TAGS.get(ptype, "Float")
        arr = prop.get("array")
        lines.append(f"\t<property>\t{pname}")
        if tag in _ARRAY_TAGS and isinstance(arr, list) and len(arr) > 1:
            wrote = False
            for mat_id, item in enumerate(arr):
                if not isinstance(item, (list, tuple)) or _is_zero_vec(item):
                    continue
                lines.append(f"\t\t<{tag}_{mat_id}>\t{_vec_text(item)}\t</{tag}_{mat_id}>")
                wrote = True
            if not wrote:
                # 全为零：保留第 0 项，避免属性整体丢失
                lines.append(f"\t\t<{tag}_0>\t{_vec_text(arr[0])}\t</{tag}_0>")
        else:
            val = prop.get("value")
            if ptype == 4:  # texture
                text = prop.get("value_path") or str(val)
            elif ptype == 0:  # bool
                text = "true" if val else "false"
            elif ptype == 1:  # int32
                text = str(int(val)) if val is not None else "0"
            elif isinstance(val, (list, tuple)):
                text = _vec_text(val)
            elif isinstance(val, (int, float)) and not isinstance(val, bool):
                text = _num(val)
            else:
                text = "" if val is None else str(val)
            lines.append(f"\t\t<{tag}>\t{text}\t</{tag}>")
        lines.append("\t</property>")

    lines.append(f"</{root}>")
    return "\n".join(lines)
