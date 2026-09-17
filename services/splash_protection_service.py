"""
splash_protection_service —— 舰船模块溅射防护口径（Splash 有效装甲）计算。

背景：
  游戏内「溅射有效装甲」的实现（具体地址/符号名不记录在本仓库，
  需要时用 Ghidra 在公开客户端主程序里现场定位）：
      dist[i] = |splash_pos[i]| - half_extent[i]        # 仅 >0 计入
      effective_armor = (dist_x·thk_x + dist_y·thk_y + dist_z·thk_z) / sum(dist)
  其中 half_extent = 炮弹口径 / 6（溅射立方体半边），thk_x/y/z 为每轴穿透的装甲厚度。
  HE 溅射穿甲判定：HE_pen(=口径/4) >= effective_armor 才损坏该区模块；
  因此「模块防溅口径」X 满足 X/4 ≈ effective_armor(X)，亦即：
      X ≈ 4 × effective_armor。

本服务把上述逻辑落到本仓库可访问的原始数据上：
  - 舰船 split JSON：含 A_Hull.armor（材质→厚度）、各模块 HitLocation.splashBoxes（盒名）；
  - pkg 内 `.splash` 文件：每个盒的 AABB；
  - pkg 内 `.geometry` 文件：装甲模型三角形（材质+厚度）。
  用盒所在区域的装甲厚度作为每轴 thk，按公式求有效装甲 → 防溅口径。

说明：溅射装甲判定的精确 thk 由游戏 C++ 在加载 splash mesh 时赋予，
本实现用「模块盒区域内装甲三角形的主导厚度」近似，数量级与游戏一致，可用于展示/对比。
"""

from __future__ import annotations

import struct
from typing import Optional

import numpy as np

from utils.path_utils import get_data_dir


# ── 常量 ────────────────────────────────────────────────────
#: HE 穿甲系数（HER 大部分 = 口径/4，部分巡洋 = 口径/6，英巡 = 口径/5）
HE_PEN_FRACTION = 0.25
#: 溅射立方体半边 = 口径 / 6
SPLASH_CUBE_FRACTION = 1.0 / 6.0
#: 盒区域外扩（舰模单位，15m/单位）——用于圈定模块「防护板」（在盒外沿，非盒内薄壁）
BOX_PAD = 0.6


# ── 数据访问 ────────────────────────────────────────────────

def _build_armor_map(ship_data: dict) -> dict[tuple[int, int], float]:
    """从舰船 JSON 的所有 armor 字典构建 {(model_idx, material_id): thickness_mm}。

    原数据中 armor 字典的键是大编码值：raw = (model_index << 16) | material_id。
    """
    out: dict[tuple[int, int], float] = {}

    def _collect(o):
        if isinstance(o, dict):
            arm = o.get("armor")
            if isinstance(arm, dict):
                for k, v in arm.items():
                    try:
                        raw = int(k)
                    except (TypeError, ValueError):
                        continue
                    mi, mat = raw >> 16, raw & 0xFFFF
                    try:
                        out[(mi, mat)] = float(v)
                    except (TypeError, ValueError):
                        continue
            for v in o.values():
                _collect(v)
        elif isinstance(o, list):
            for v in o:
                _collect(v)

    _collect(ship_data)
    return out


def _parse_splash(path) -> dict[str, tuple[float, float, float, float, float, float]]:
    """解析 `.splash` 文件 → {盒名: (min_x,min_y,min_z,max_x,max_y,max_z)}。"""
    data = open(path, "rb").read()
    off = 0
    count = struct.unpack_from("<I", data, off)[0]
    off += 4
    boxes = {}
    for _ in range(count):
        nlen = struct.unpack_from("<I", data, off)[0]
        off += 4
        name = data[off:off + nlen].decode("latin1")
        off += nlen
        boxes[name] = struct.unpack_from("<6f", data, off)
        off += 24
    return boxes


def _parse_armor_triangles(path_geometry, armor_map):
    """解析 `.geometry` 装甲三角形。

    返回 (顶点列表, 中心列表, 厚度列表, 材质列表)。
    顶点用于真实射线-三角形求交（游戏 C++ 逐面射线找防护板的依据）。
    """
    from models.geometry_parser import parse_geometry
    geom = parse_geometry(open(path_geometry, "rb").read(), path_geometry)
    verts, tris, thks, mats = [], [], [], []
    for m in geom.armor_models:
        for t in m.triangles:
            thk = armor_map.get((t.layer_index, t.material_id), 0.0)
            if thk > 0:
                verts.append(np.array(t.vertices, dtype=float))
                tris.append(np.mean(t.vertices, axis=0))
                thks.append(thk)
                mats.append(t.material_id)
    return verts, tris, thks, mats


# ── 射线-三角形求交（游戏内逐面防护板厚度依据）─────
_AXES = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0],
                  [0, 0, 1], [0, 0, -1]], dtype=float)


def _ray_first_hit(origin, direction, verts):
    """从 origin 沿 direction 求交所有三角形，返回最近的 (命中距离, 三角形序号)。"""
    d = direction / np.linalg.norm(direction)
    best = None
    for i, v in enumerate(verts):
        a, b, c = v[0], v[1], v[2]
        e1 = b - a
        e2 = c - a
        h = np.cross(d, e2)
        a1 = np.dot(e1, h)
        if abs(a1) < 1e-9:
            continue
        s = origin - a
        u = np.dot(s, h) / a1
        if u < -1e-6 or u > 1 + 1e-6:
            continue
        q = np.cross(s, e1)
        vv = np.dot(d, q) / a1
        if vv < -1e-6 or u + vv > 1 + 1e-6:
            continue
        t_ = np.dot(e2, q) / a1
        if t_ <= 1e-6:
            continue
        if best is None or t_ < best[0]:
            best = (t_, i)
    return best


def _box_face_thicknesses(box, verts, thks):
    """对每个盒，从盒中心沿 ±x/±y/±z 六方向射线求交，取各方向最近防护板厚度。

    返回 6 元组 (thk_x+, thk_x-, thk_y+, thk_y-, thk_z+, thk_z-)，无命中为 0。
    """
    mn = np.array(box[0:3], dtype=float)
    mx = np.array(box[3:6], dtype=float)
    center = (mn + mx) / 2
    out = []
    for d in _AXES:
        hit = _ray_first_hit(center, d, verts)
        if hit is None:
            out.append(0.0)
        else:
            out.append(float(thks[hit[1]]))
    return out


# ── 核心计算 ────────────────────────────────────────────────

def _module_effective_armor(box_names, splash_boxes, verts, thks) -> tuple[Optional[float], Optional[float]]:
    """对一组 splash 盒，逐面射线求交各盒防护板厚度，返回 (有效装甲, 防溅口径)。

    依据：
      游戏内实现中每盒有 6 个面厚度 thk（x±/y±/z±），
      由 C++/游戏脚本从装甲模型按方向射线求交得到；有效装甲为其距离加权平均。
    此处按「模块所有盒、所有面」的平均防护厚度近似有效装甲。
    """
    faces: list[float] = []
    for n in box_names:
        v = splash_boxes.get(n)
        if v is None:
            continue
        faces.extend(_box_face_thicknesses(v, verts, thks))
    faces = [f for f in faces if f > 0]
    if not faces:
        return None, None

    # 有效装甲 = 模块盒各面防护厚度均值（游戏为距离加权，此处均匀近似）
    effective = float(np.mean(faces))
    caliber = effective / HE_PEN_FRACTION
    return effective, caliber


def compute_ship_splash_protection(ship_data: dict, game_dir: str, ship_splash_path: str,
                                   ship_geometry_path: str) -> dict[str, list[dict]]:
    """计算舰船各模块的溅射防护口径。

    参数:
        ship_data: split JSON 反序列化后的 dict（含 A_Hull.armor、各模块 splashBoxes）。
        game_dir: 游戏根目录（需要 bin/ 与 res_packages/）。
        ship_splash_path: 舰船 .splash 文件路径（已提取）。
        ship_geometry_path: 舰船 .geometry 文件路径（已提取）。

    返回:
        {module_type: [{config, module_key, boxes, effective_armor, protection_caliber}]}
    """
    armor_map = _build_armor_map(ship_data)
    splash_boxes = _parse_splash(ship_splash_path)
    verts, _tris, _thks, _mats = _parse_armor_triangles(ship_geometry_path, armor_map)

    if not verts:
        return {}

    # 收集各模块（含引擎/舵机/弹药库等带 splashBoxes 的命中位置）
    module_types = {
        "engine": "engine_hitlocation",
        "steering": "steering_gear_hitlocation",
        "magazine": "powdermagazine_hitlocation",
        "torpedo": "torpedo_hitlocation",
        "sonar": "sonar_hitlocation",
    }
    results: dict[str, list[dict]] = {}
    for modk, modv in ship_data.items():
        if not isinstance(modv, dict):
            continue
        for regk, regv in modv.items():
            if not isinstance(regv, dict):
                continue
            hl = regv.get("hlType") or ""
            boxes = regv.get("splashBoxes") or []
            if not boxes:
                continue
            mtype = None
            for t, hlt in module_types.items():
                if hl == hlt:
                    mtype = t
                    break
            if mtype is None:
                continue
            eff, cal = _module_effective_armor(boxes, splash_boxes, verts, _thks)
            if cal is None:
                continue
            results.setdefault(mtype, []).append({
                "config": modk.rstrip("1234567890"),
                "module_key": modk,
                "boxes": boxes,
                "effective_armor": round(eff, 2),
                "protection_caliber": round(cal, 1),
            })
    return results


# ── pkg 自动提取入口 ────────────────────────────────────────

def locate_ship_files(game_dir: str, hull_model: str) -> tuple[Optional[str], Optional[str]]:
    """根据船体模型路径定位同一目录下的 `.splash` 与主 `.geometry`。

    返回 (splash_vfs_path, geometry_vfs_path)，找不到返回 (None, None)。
    """
    if not hull_model:
        return None, None
    base = hull_model.rsplit("/", 1)[0] if "/" in hull_model else hull_model
    # 主 geometry = 与 model 同名的 .geometry（去后缀）
    stem = hull_model.rsplit("/", 1)[-1]
    if stem.endswith(".model"):
        stem = stem[: -len(".model")]
    splash = f"{base}/{stem}.splash"
    geom = f"{base}/{stem}.geometry"
    return splash, geom


def extract_ship_files(game_dir: str, ship_data: dict, out_dir: str | None = None,
                       extractor=None):
    """用 GameExtractor 从 pkg 提取某船的 .splash 与 .geometry。

    extractor: 可选，传入可复用的 GameExtractor（批量调用时共用，避免每个文件
               重载全部 IDX + 文件树）。提供时内部不创建/不关闭；否则自建并在结束时关闭。

    返回 (splash_path, geometry_path) 本地路径；找不到/提取失败返回 (None, None)。
    """
    import os
    from data_extractor import GameExtractor
    from data_extractor.extractor import ExtractorError

    hull = (ship_data.get("A_Hull") or {}).get("model") or ""
    splash_vfs, geom_vfs = locate_ship_files(game_dir, hull)
    if not splash_vfs or not geom_vfs:
        return None, None
    own = extractor is None
    if own:
        try:
            g = GameExtractor(game_dir)
        except ExtractorError:
            return None, None
    else:
        g = extractor
    out = out_dir or str(get_data_dir() / "_splash")
    os.makedirs(out, exist_ok=True)
    splash_path, geometry_path = None, None
    try:
        sp = os.path.join(out, os.path.basename(splash_vfs))
        g.extract_single(splash_vfs, sp)
        splash_path = sp
    except Exception:  # noqa: BLE001
        splash_path = None
    try:
        gp = os.path.join(out, os.path.basename(geom_vfs))
        g.extract_single(geom_vfs, gp)
        geometry_path = gp
    except Exception:  # noqa: BLE001
        geometry_path = None
    if own:
        try:
            g.close()
        except Exception:  # noqa: BLE001
            pass
    return splash_path, geometry_path


def compute_ship_protection_from_pkg(ship_data: dict, game_dir: str, extractor=None) -> dict[str, list[dict]]:
    """从 pkg 自动提取 splash/geometry 并计算舰船模块防溅口径。

    extractor: 可选，传入可复用的 GameExtractor（见 extract_ship_files）。
    """
    splash_path, geometry_path = extract_ship_files(game_dir, ship_data, extractor=extractor)
    if not splash_path or not geometry_path:
        return {}
    return compute_ship_splash_protection(ship_data, game_dir, splash_path, geometry_path)
