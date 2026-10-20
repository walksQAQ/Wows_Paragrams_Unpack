"""mfm_text.py —— 把解码后的 MaterialPrototype 还原为 Mod SDK 明文 `.mfm` 样式。

⚠️ **实验性功能**：assets.bin 的记录布局与 Mod SDK 明文并非一一对应
（`<parentMfm>` 继承链二进制里没有、`sortOrder` 二进制里有但 SDK 不导出等），
转码结果可能存在与官方导出不一致之处，请以游戏内实际表现为准。

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

from .types import get_wows_type

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

    `<collisionFlags>` 取自材质记录 WG `+0x70`（碰撞面标记，位定义见
    ``decoders.COLLISION_FLAG_BITS``）。WoWS 内容从不设置该字段，实测 31,534 个 WG
    材质全为 0 —— 与 Mod SDK 明文恒写 0 完全吻合。
    **Korabli 侧不输出该行**：Korabli 的二进制原型里没有这个字段（Ghidra 反编译
    `FUN_140643320` 确认字段表止于 `sortOrder@+0x80`），`Korabli64.exe` 里也没有该
    字符串 —— 明文里的 `<collisionFlags>` 只是 SDK 导出器的残留标签，客户端不解析。
    `sortOrder`（WG `+0x74` / Korabli `+0x80`）只在 16 个 mesh_decal 上非默认，Mod SDK
    明文从不导出它，因此这里也不写（只在 JSON 里保留）。
    写法口径按 WG 15.9：始终写 `<collisionFlags>`（Lesta 26.10 只写了 63.5%）。
    """
    root = (name or "material.mfm").strip()
    lines: List[str] = [f"<{root}>"]
    for parent in parent_mfms or []:
        if parent:
            lines.append(f"\t<parentMfm>\t{parent}\t</parentMfm>")
    if fx:
        lines.append(f"\t<fx>\t{fx}\t</fx>")
    if get_wows_type() != "Lesta":
        try:
            flags = int(decoded.get("collisionFlags") or 0) & 0xFF
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
