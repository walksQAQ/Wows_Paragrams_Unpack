"""
splash_protection_service —— 舰船模块溅射防护口径（Splash 有效装甲）计算。

背景：
  游戏内 `溅射有效装甲计算`（与客户端实现一致）：
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

说明：`溅射装甲判定` 的精确 thk 由游戏 C++ 在加载 splash mesh 时赋予，
本实现用「模块盒区域内装甲三角形的主导厚度」近似，数量级与游戏一致，可用于展示/对比。
"""

from __future__ import annotations

import os
import struct
from typing import Optional

import numpy as np

from utils.path_utils import get_data_dir


# ── 常量 ────────────────────────────────────────────────────
#: ⚠️【临时开关】模块溅射防护（splashBoxes）功能总闸：
#:   False = 入库计算与 UI 显示全部跳过（缩短「加载数据」耗时，加速主流程）；
#:   True  = 恢复逐船「提取 .splash/.geometry → 射线求交 → 入库 → 卡片显示」。
#:   注：DB 表 ship_module_splash_protection 与代码均保留，改回 True 即可恢复，
#:       无需重载数据（旧数据仍在；若期间换过游戏构建，需重跑数据加载）。
FEATURE_ENABLED: bool = False

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


def _parse_armor_triangles(path_geometry, armor_map) -> "_ArmorMesh":
    """解析 `.geometry` 装甲三角形 → 预计算 (N,3) 数组的装甲网格（供批量射线求交）。"""
    from models.geometry_parser import parse_geometry
    with open(path_geometry, "rb") as f:
        geom = parse_geometry(f.read(), path_geometry)
    verts, thks = [], []
    for m in geom.armor_models:
        for t in m.triangles:
            thk = armor_map.get((t.layer_index, t.material_id), 0.0)
            if thk > 0:
                verts.append(t.vertices)
                thks.append(thk)
    return _ArmorMesh(verts, thks)


# ── 射线-三角形求交（游戏 溅射装甲判定 逐面防护板依据）─────
_AXES = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0],
                  [0, 0, 1], [0, 0, -1]], dtype=float)

#: 批量射线求交的射线分块大小（限制 (M,N,3) 临时数组内存；M×N ≈ 20 万元素/块）
_RAY_CHUNK = 32
#: Möller–Trumbore 判定容差（与旧逐三角形实现严格一致）
_EPS = 1e-6
_DET_EPS = 1e-9


class _ArmorMesh:
    """装甲三角形网格：预计算 (N,3) 数组，射线求交一次向量化。

    旧实现逐三角形跑 Python 循环（射线数 × 三角形数 ≈ 100 万次/船 → 6–28 s/船）；
    这里用批量 Möller–Trumbore，单船降到几十毫秒（实测 277–403×，结果逐条一致）。
    """

    __slots__ = ("a", "e1", "e2", "thk")

    def __init__(self, verts, thks):
        if verts:
            a = np.asarray([v[0] for v in verts], dtype=float)
            e1 = np.asarray([v[1] for v in verts], dtype=float) - a
            e2 = np.asarray([v[2] for v in verts], dtype=float) - a
        else:
            a = e1 = e2 = np.zeros((0, 3), dtype=float)
        self.a, self.e1, self.e2 = a, e1, e2
        self.thk = np.asarray(thks, dtype=float)

    def __len__(self) -> int:
        return len(self.a)

    def first_hit_thickness(self, origins, directions) -> np.ndarray:
        """批量射线求交，返回每根射线最近命中三角形的装甲厚度（未命中为 0.0）。"""
        origins = np.asarray(origins, dtype=float).reshape(-1, 3)
        directions = np.asarray(directions, dtype=float).reshape(-1, 3)
        out = np.zeros(len(origins), dtype=float)
        if len(self.a) == 0 or len(origins) == 0:
            return out
        norms = np.linalg.norm(directions, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        dirs = directions / norms
        a1, e11, e21 = self.a[None, :, :], self.e1[None, :, :], self.e2[None, :, :]
        for s0 in range(0, len(origins), _RAY_CHUNK):
            s1 = min(s0 + _RAY_CHUNK, len(origins))
            o = origins[s0:s1, None, :]                 # (M,1,3)
            d = dirs[s0:s1]                             # (M,3)
            h = np.cross(d[:, None, :], e21)            # (M,N,3)
            det = np.einsum("mnj,mnj->mn", e11, h)      # (M,N)
            valid = np.abs(det) > _DET_EPS
            inv = np.where(valid, det, 1.0)
            s = o - a1
            u = np.einsum("mnj,mnj->mn", s, h) / inv
            q = np.cross(s, e11)
            vv = np.einsum("mnj,mj->mn", q, d) / inv
            t = np.einsum("mnj,mnj->mn", e21, q) / inv
            valid &= ((u >= -_EPS) & (u <= 1.0 + _EPS) & (vv >= -_EPS)
                      & (u + vv <= 1.0 + _EPS) & (t > _EPS))
            t_all = np.where(valid, t, np.inf)
            t_min = t_all.min(axis=1)
            rows = np.nonzero(np.isfinite(t_min))[0]
            if rows.size:
                out[s0 + rows] = self.thk[np.argmin(t_all, axis=1)[rows]]
        return out

    def box_face_thicknesses(self, box) -> np.ndarray:
        """盒中心沿 ±x/±y/±z 六方向射线求交，返回各方向最近防护板厚度（无命中 0）。"""
        mn = np.asarray(box[0:3], dtype=float)
        mx = np.asarray(box[3:6], dtype=float)
        center = (mn + mx) / 2
        return self.first_hit_thickness(
            np.repeat(center[None, :], len(_AXES), axis=0), _AXES)


# ── 核心计算 ────────────────────────────────────────────────

def _module_effective_armor(box_names, splash_boxes, mesh) -> tuple[Optional[float], Optional[float]]:
    """对一组 splash 盒，逐面射线求交各盒防护板厚度，返回 (有效装甲, 防溅口径)。

    依据：
      游戏 `溅射装甲判定` 每盒有 6 个面厚度 thk（x±/y±/z±），
      由 C++/游戏脚本从装甲模型按方向射线求交得到；有效装甲为其距离加权平均。
    此处按「模块所有盒、所有面」的平均防护厚度近似有效装甲。
    """
    origins = []
    for n in box_names:
        v = splash_boxes.get(n)
        if v is None:
            continue
        mn = np.asarray(v[0:3], dtype=float)
        mx = np.asarray(v[3:6], dtype=float)
        origins.append(np.repeat(((mn + mx) / 2)[None, :], len(_AXES), axis=0))
    if not origins:
        return None, None
    # 一次性把所有盒 × 6 方向射线交给向量化求交，摊薄 Python 侧开销
    origins = np.concatenate(origins, axis=0)
    directions = np.tile(_AXES, (len(origins) // len(_AXES), 1))
    thicknesses = mesh.first_hit_thickness(origins, directions)
    faces = thicknesses[thicknesses > 0]
    if not faces.size:
        return None, None

    # 有效装甲 = 模块盒各面防护厚度均值（游戏为距离加权，此处均匀近似）
    effective = float(faces.mean())
    return effective, effective / HE_PEN_FRACTION


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
    mesh = _parse_armor_triangles(ship_geometry_path, armor_map)

    if not len(mesh):
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
            eff, cal = _module_effective_armor(boxes, splash_boxes, mesh)
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


def _cached_file(path: str) -> Optional[str]:
    """返回已存在且非空的提取缓存路径（0 字节/半成品视为未缓存）。"""
    try:
        return path if os.path.getsize(path) > 0 else None
    except OSError:
        return None


def _extract_or_reuse(g, vfs: str, dst: str, legacy_dir: str = "") -> Optional[str]:
    """优先复用已提取文件（本构建缓存目录 → 旧扁平目录），缺才从 pkg 提取。

    单船 2 个文件重提取约 84–184 ms，命中缓存可直接省掉（本仓库 pkg 解压是主要开销）。
    """
    p = _cached_file(dst)
    if p is None and legacy_dir:
        if os.path.abspath(legacy_dir) != os.path.abspath(os.path.dirname(dst)):
            p = _cached_file(os.path.join(legacy_dir, os.path.basename(dst)))
    if p is not None:
        return p
    try:
        g.extract_single(vfs, dst)
    except Exception:  # noqa: BLE001
        return None
    return _cached_file(dst)


def extract_ship_files(game_dir: str, ship_data: dict, out_dir: str | None = None,
                       extractor=None):
    """用 GameExtractor 从 pkg 提取某船的 .splash 与 .geometry（已缓存则跳过提取）。

    extractor: 可选，传入可复用的 GameExtractor（批量调用时共用，避免每个文件
               重载全部 IDX + 文件树）。提供时内部不创建/不关闭；否则自建并在结束时关闭。

    返回 (splash_path, geometry_path) 本地路径；找不到/提取失败返回 (None, None)。
    """
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
    # 旧版提取目录（未按构建分级）：作为只读回退复用，避免重复解压
    legacy = str(get_data_dir() / "_splash")
    splash_path = _extract_or_reuse(g, splash_vfs,
                                    os.path.join(out, os.path.basename(splash_vfs)), legacy)
    geometry_path = _extract_or_reuse(g, geom_vfs,
                                      os.path.join(out, os.path.basename(geom_vfs)), legacy)
    if own:
        try:
            g.close()
        except Exception:  # noqa: BLE001
            pass
    return splash_path, geometry_path


def compute_ship_protection_from_pkg(ship_data: dict, game_dir: str, extractor=None,
                                     out_dir: str | None = None) -> dict[str, list[dict]]:
    """从 pkg 自动提取 splash/geometry 并计算舰船模块防溅口径。

    extractor: 可选，传入可复用的 GameExtractor（见 extract_ship_files）。
    out_dir: 可选，提取缓存目录（建议按 bin_folder 分级，便于复用且不跨版本串用）。
    """
    splash_path, geometry_path = extract_ship_files(game_dir, ship_data,
                                                    out_dir=out_dir, extractor=extractor)
    if not splash_path or not geometry_path:
        return {}
    return compute_ship_splash_protection(ship_data, game_dir, splash_path, geometry_path)
