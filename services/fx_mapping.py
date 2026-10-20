"""fx_mapping.py —— fx 路径 → 渲染技术族（**不解析 fx、不使用固定映射表**）。

背景（2026-10-20 修订）：
- MaterialPrototype 的 ``material_hash``（Korabli +0x78 / WG +0x68）是 fx 资源
  在 assets.bin 路径树里的 selfId。解析逻辑独立在
  ``uncode_assets.mfm_fx.resolve_fx_path()``（assets.bin 浏览器的独立功能）。
- 本模块只保留「fx 路径 → 技术族」的纯函数，供 3D 渲染分支使用。
"""

from __future__ import annotations


def tech_family(fx_path: str, shader_id: str = "") -> str:
    """按 fx 路径判定渲染类别（渲染分支用）；路径缺失退回 shader_id 高 16 位族。

    渲染类别（geometry_renderer.paintGL 按此分支）：
      grid        → 网格/线网 alpha（透明 pass，无光照）
      indexed     → INDEXED 分块渲染（materialIdMap+albedoArray）
      emissive    → 自发光/燃烧（无光照亮色，u_mode=2 不透明）
      transparent → 半透明（玻璃/螺旋桨/水/云/旗帜等，blend + 贴图 alpha）
      decal       → 贴花叠加（普通光照）
      wire        → 细线/栏杆材质（普通）
      pbs         → 标准 PBS（光照实体）
      other       → shader_id 高 16 位兜底
    """
    low = (fx_path or "").lower()
    base = low.split("/")[-1]
    if "grid_alpha" in low:
        return "grid"
    if "indexed" in low:
        return "indexed"
    # 自发光/燃烧：无光照亮色
    if "emissive" in low or "blaze" in low:
        return "emissive"
    # 半透明：玻璃/透明/螺旋桨/水/瀑布/云平面/旗帜（blend + 贴图 alpha）
    if ("glass" in low or "transparent" in low or "propeller" in low
            or "water" in low or "waterfall" in low or "cloud_plane" in low
            or base == "flag.fx" or "dirty_glass" in low
            or "interior_behind_glass" in low):
        return "transparent"
    if "decal" in low or "mesh_decal" in low:
        return "decal"
    if "wire" in low:
        return "wire"
    if ("pbs" in low or "camo" in low or "ship_material" in low
            or "diffuse" in low or "base_material" in low):
        return "pbs"
    # 无 fx 路径/无法归类：退回 shader_id 高 16 位族
    from utils.asset_utils import material_family
    return material_family(shader_id)
