"""mfm_fx.py —— MaterialPrototype → fx 路径解析（assets.bin 浏览器独立功能）。

只依赖 assets.bin 解析出来的 :class:`PrototypeDatabase`：

- MaterialPrototype 的 ``material_hash``（Korabli +0x78 / WG +0x68）不是哈希值，
  而是 fx 资源的路径 selfId；在路径树里反查即得真实 fx 路径
  （如 ``shaders/std_effects/PBS_ship_skinned.fx``）。
- 不读 ``assets_data.db``、不依赖固定映射表、也不需要 pkg 里的 ``.fxo`` 清单；
  直接打开单个 assets.bin 文件也能解析。
"""

from __future__ import annotations

FX_SUFFIX = ".fx"


def resolve_fx_path(db, material_hash) -> str:
    """material_hash（``"0x..."`` 或 int）→ fx 完整路径；无法解析返回空串。

    Args:
        db: assets.bin 解析出的 :class:`PrototypeDatabase`（可为 None）。
        material_hash: 材质记录里的 selfId（十进制 int 或十六进制字符串）。
    """
    if db is None or material_hash in (None, "", 0, "0"):
        return ""
    try:
        value = int(material_hash, 16) if isinstance(material_hash, str) else int(material_hash)
    except (TypeError, ValueError):
        return ""
    if not value:
        return ""
    try:
        path = db.resolve_self_path(value)
    except Exception:  # noqa: BLE001
        return ""
    return path if (path or "").lower().endswith(FX_SUFFIX) else ""
