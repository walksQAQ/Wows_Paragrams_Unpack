"""fx_mapping.py —— fx 坐标映射：material_hash → fx 名（Korabli/Lesta + WG 各一份）。

背景（2026-08-23）：
- assets.bin 的 MaterialPrototype 只有 shader_id(u32) + material_hash(u64)，
  **字符串表里没有 fx 名字符串**（含 `.fx` 的字符串 = 0）。
- shader_id 高 16 位是材质族（0x0001=diffuse/0x0005=PBS/0x0009=INDEXED），
  **无法区分同一族内的不同 fx**（如 grid_alpha.fx 与普通 diffuse 都是 0x0001）。
- **material_hash 是 fx 变体的稳定标识**（跨服务器一致）：
  grid_alpha=0x337DB144A9F7A335、grid_alpha_skinned=0x4AF45D4D6FCB4781 等。
- 映射表文件 `resources/fx_mapping_{lesta|wargaming}.md`（md 表格）由人工填写：
  每行 `| shader_id高16 | material_hash | ... | fx 名 |`。
  **没有合适 fx 名/路径时该列存 shader_id**（如 `0x00010000`），
  程序据此退回 shader_id 高 16 位族判定，不凭空假设默认 fx。
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Tuple

_FX_KEY = Tuple[str, str]  # (shader_id 高16位, material_hash) 小写

_maps: Dict[str, Dict[_FX_KEY, str]] = {}
_lock = threading.Lock()


def _mapping_path(wows_type: str) -> str:
    from utils.path_utils import get_bundled_dir
    key = "wargaming" if (wows_type or "").lower() == "wargaming" else "lesta"
    return os.path.join(get_bundled_dir(), "resources", f"fx_mapping_{key}.md")


def load(wows_type: str) -> Dict[_FX_KEY, str]:
    """读取映射表 → {(shader_id高16, material_hash): fx 名}（小写键，跨调用缓存）。"""
    key = "wargaming" if (wows_type or "").lower() == "wargaming" else "lesta"
    with _lock:
        if key in _maps:
            return _maps[key]
    out: Dict[_FX_KEY, str] = {}
    path = _mapping_path(key)
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 5:
                    continue
                sh, mh, fx = cells[0].lower(), cells[1].lower(), cells[4]
                if not fx or fx in ("", "-"):
                    continue
                out[(sh, mh)] = fx
    except OSError:
        pass
    with _lock:
        _maps[key] = out
    return out


def _shader_family_key(shader_id: str) -> str:
    """shader_id（0xHHHHLLLL）→ 高 16 位小写（如 0x00010000）。"""
    try:
        v = int(shader_id, 16) & 0xFFFF0000
        return f"0x{v:08X}".lower()
    except Exception:  # noqa: BLE001
        return (shader_id or "").lower()


def fx_name(wows_type: str, shader_id: str, material_hash: str) -> str:
    """material_hash → fx 名（映射表值）；无合适映射退回 shader_id 字符串。

    只做**精确 (shader_id 高16位, material_hash) 匹配**——material_hash 标识
    材质模板/继承族（如 ship_base_colors），同一哈希可跨 shader 族出现
    （ZGA3007 INDEXED 与其 parentMfm base_colors 共享 0x1EC81C72EED8E0E3），
    若只按 material_hash 匹配会把不同 fx 的材质误归一组。fx 名由 shader 族
    主导、material_hash 用于族内细分。
    均无 → 返回 shader_id（用户约定：没有合适映射时存入 shader_id）。
    """
    if not material_hash:
        return shader_id
    m = load(wows_type)
    if not m:
        return shader_id
    sh = _shader_family_key(shader_id)
    return m.get((sh, material_hash.lower())) or shader_id


def fx_full_path(
    wows_type: str,
    shader_id: str,
    material_hash: str,
    short_map: Dict[str, object] | None = None,
) -> str:
    """返回完整 fx 路径（如 `shaders/std_effects/flag.fx`）。

    `short_map` 由调用方从**当前客户端的 pkg 清单**现场扫描得到
    （短名 → 完整路径）；未提供时只认映射表里的完整路径。
    同一短名可能对应多个目录，此时用 ` | ` 连接返回。
    """
    fx = fx_name(wows_type, shader_id, material_hash)
    if not fx:
        return ""
    low = fx.lower()
    if "/" in fx and low.endswith(".fx"):
        return fx
    if short_map and low.endswith(".fx"):
        hit = short_map.get(fx)
        if isinstance(hit, str):
            return hit
        if isinstance(hit, list) and hit:
            return " | ".join(str(x) for x in hit)
    return ""


def fx_names_by_material_hash(wows_type: str, material_hash: str) -> list[str]:
    """同一 material_hash 在其它 shader 族下的 fx 名（**仅供参考，不参与判定**）。

    材质模板会跨 shader 族复用（同一 hash 常见于 0x0005/0x0006/0x0007 多个族），
    因此精确未命中时用它提示“大概对应哪个 fx”。
    """
    if not material_hash:
        return []
    h = material_hash.lower()
    out: list[str] = []
    for (_sh, mh), fx in load(wows_type).items():
        if mh == h and fx and fx.lower().endswith(".fx") and fx not in out:
            out.append(fx)
    return out


def _resolve_short(fx: str, short_map: Dict[str, object]) -> str:
    """短名 → 完整路径（同短名多目录用 ` | ` 连接）；已是完整路径则原样返回。"""
    if "/" in fx:
        return fx
    hit = short_map.get(fx)
    if isinstance(hit, str):
        return hit
    if isinstance(hit, list) and hit:
        return " | ".join(str(x) for x in hit)
    return fx


def fx_display(
    wows_type: str,
    shader_id: str,
    material_hash: str,
    short_map: Dict[str, object] | None = None,
) -> str:
    """给界面用的 fx 展示文本。

    - 无 `short_map`（直接打开单个 assets.bin 文件）→ 空串，界面不显示该行
    - 命中 → 完整路径；映射表路径在当前客户端不存在/已改目录时附注
    - 未命中 → `(未映射 · 技术族=... · 参考同 material_hash: ...)`
    """
    if not short_map:
        return ""
    path = fx_full_path(wows_type, shader_id, material_hash, short_map)
    if path:
        hit = short_map.get(path.rsplit("/", 1)[-1])
        if hit is None:
            return f"{path}  (当前客户端中不存在)"
        if isinstance(hit, str) and hit != path:
            return f"{path}  (当前客户端路径: {hit})"
        return path
    fam = tech_family(wows_type, shader_id, material_hash)
    refs: list[str] = []
    for name in fx_names_by_material_hash(wows_type, material_hash):
        p = _resolve_short(name, short_map)
        if p not in refs:
            refs.append(p)
    if refs:
        return f"(未映射 · 技术族={fam} · 参考同 material_hash: {', '.join(refs[:3])})"
    return f"(未映射 · 技术族={fam} · material_hash={material_hash})"


def tech_family(wows_type: str, shader_id: str, material_hash: str) -> str:
    """按 fx 名判定渲染类别（渲染分支用）；无映射退回 shader_id 高 16 位族。

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
    fx = fx_name(wows_type, shader_id, material_hash)
    low = fx.lower()
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
    # fx 名是 shader_id 或无匹配：退回 shader_id 高 16 位族
    from utils.asset_utils import material_family
    return material_family(shader_id)
