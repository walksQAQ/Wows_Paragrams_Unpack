"""炮塔射界计算工具（纯数据层，供 presenter 与 UI 复用）。

数据约定（来自 ship_turret_arcs 表 / 弹窗 gun dict）：
    horiz_sector      [-147.0, 147.0]  水平射界（Lesta ±180°制，相对炮塔默认朝向）
    vert_sector       [-2.0, 30.0]     垂直射界
    dead_zones        [[146.0, -146.0]] 水平死区
    pitch_dead_zones  [[153.0, -153.0, 13.5, 30.0]] 俯仰受限区
    position          [col, row]       炮塔位置（col 小=船头，col 大=船尾；row 横向）

角度约定：
    绝对坐标 0°=船头，顺时针（90°=右舷，180°=船尾，270°=左舷）。
    Lesta 数据是「相对炮塔默认朝向」的角度；炮塔默认朝向判定优先级：
        1. gun['mount_yaw']（assets.bin 舰体骨架节点矩阵提取的真实安装朝向）；
        2. 由 position 决定（船头段朝前 0°，船尾段朝后 180°）；
        3. 都无则数据自洽为朝前（0°）。

对外接口：
    compute_facings(guns)          -> [facing, ...]  每门炮默认朝向（0/180）
    gun_abs_segments(gun, facing)  -> [(start, end), ...]  绝对可射扇区
    gun_sector_array(gun, facing)  -> [0..359] 三态栅格（2可射/1俯仰受限/0死区）
    firing_arc_angles(guns)        -> {"mode", "front", "back"}

齐射角规则：
    全炮塔可射交集非空（中线布置，如主炮）：
        前向 = 从正前 0° 到全炮塔可射的最近边界；后向 = 从正后 180° 同理。
    全炮塔无法齐射（炮塔分列左右舷，如鱼雷/副炮）：
        右舷炮塔只能向右射击、左舷炮塔只能向左射击，互不交叉；
        前向齐射角 = 右舷炮塔群从正前 0° 的齐射角，
        后向齐射角 = 左舷炮塔群从正后 180° 的齐射角。
"""

from __future__ import annotations

import json
import math


def parse_list(raw, default=None):
    """解析数据库 JSON 字段（字符串 / list / None）"""
    if raw is None:
        return default
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return default
    return default


# ── 扇区区间运算（0-360 顺时针弧） ────────────────────────

def _merge(segs):
    """合并重叠/相邻区间"""
    segs = sorted(segs)
    res = []
    for a, b in segs:
        if not res or a > res[-1][1] + 1e-9:
            res.append([a, b])
        else:
            res[-1][1] = max(res[-1][1], b)
    return [(a, b) for a, b in res]


def _seg_arc(start, end):
    """顺时针弧 (start -> end)（可负/超 360）拆成不跨 0° 的 0-360 区间列表。"""
    s = start % 360.0
    e = end % 360.0
    if abs(s - e) < 1e-9:
        # 起点==终点：360° 转炮标记（horizSector 为 [a,a]），可射=全圈减死区
        return [(0.0, 360.0)]
    if s < e:
        return [(s, e)]
    return [(s, 360.0), (0.0, e)]


def _sub_dead(segs, ds, de):
    """从区间列表减去死区弧 (ds -> de)。"""
    for d1, d2 in _seg_arc(ds, de):
        new = []
        for x, y in segs:
            if y <= d1 + 1e-9 or x >= d2 - 1e-9:
                new.append((x, y))
            else:
                if x < d1:
                    new.append((x, d1))
                if y > d2:
                    new.append((d2, y))
        segs = new
    return _merge(segs)


def _intersect(a, b):
    res = []
    for x1, y1 in a:
        for x2, y2 in b:
            lo, hi = max(x1, x2), min(y1, y2)
            if hi - lo > 1e-9:
                res.append((lo, hi))
    return _merge(res)


# ── 朝向判断 ────────────────────────────────────────────

def compute_facings(guns):
    """判断每门炮的默认朝向（绝对角度 0-360°，0=船首顺时针）。

    优先级：
      1. gun['mount_yaw'] —— assets.bin 舰体骨架节点提取的真实安装朝向
         （如副炮左舷 270°、右舷 90°；主炮舰首 0°、舰尾 180°）。
      2. 基于 position[0] 纵向坐标：取炮塔分布的最大间隙切分船头/船尾段（0/180）。
      3. 都没有则默认朝前（0°）。
    """
    facings: list[float] = []
    pos_idx: list[int] = []          # 需要 position 推断的炮（原索引）
    for g in guns:
        my = g.get("mount_yaw")
        if my is not None:
            try:
                facings.append(float(my) % 360.0)
            except (TypeError, ValueError):
                pos_idx.append(len(facings))
                facings.append(0.0)
        else:
            pos_idx.append(len(facings))
            facings.append(0.0)
    if not pos_idx:
        return facings
    poss = [(i, g["position"][0]) for i, g in enumerate(guns)
            if i in pos_idx and g.get("position") and len(g["position"]) >= 1]
    cut = None
    if len(poss) >= 2:
        sp = sorted(p[1] for p in poss)
        span = sp[-1] - sp[0]
        if span > 0:
            gap_i = max(range(len(sp) - 1), key=lambda i: sp[i + 1] - sp[i])
            gap = sp[gap_i + 1] - sp[gap_i]
            if gap > span * 0.3:
                cut = (sp[gap_i] + sp[gap_i + 1]) / 2
    for i, g in enumerate(guns):
        if i not in pos_idx:
            continue
        if cut is not None and g.get("position") and len(g["position"]) >= 1 and g["position"][0] >= cut:
            facings[i] = 180.0
    return facings


# ── 单门炮扇区 ─────────────────────────────────────────

def gun_abs_segments(gun, facing=0.0):
    """单门炮的绝对可射扇区列表（0-360 顺时针），已减去水平死区。

    相对 horiz_sector 按 facing 旋转到绝对坐标（0°=船头，顺时针）。
    horiz_sector 为 [a, a] 时视为 360° 转炮（可射 = 全圈减死区）。
    """
    hs = parse_list(gun.get("horiz_sector"), [])
    if len(hs) < 2:
        return []
    h0, h1 = hs[0], hs[1]
    if abs(h0 - h1) < 1e-9:
        segs = [(0.0, 360.0)]
    else:
        segs = _seg_arc(facing + h0, facing + h1)
    for dz in parse_list(gun.get("dead_zones"), []) or []:
        if len(dz) >= 2:
            segs = _sub_dead(segs, facing + dz[0], facing + dz[1])
    return _merge(segs)


def gun_sector_array(gun, facing=0.0):
    """单门炮 360° 三态栅格（绝对坐标）：2=可射击，1=俯仰受限，0=死区/不能打。

    优先级：死区(0) > 俯仰受限(1) > 可射击(2)。含朝向转换。
    """
    sec = [0] * 360
    hs = parse_list(gun.get("horiz_sector"), [])
    if len(hs) >= 2:
        a = int(round((facing + hs[0]) % 360)) % 360
        b = int(round((facing + hs[1]) % 360)) % 360
        angle = a
        while True:
            sec[angle] = 2
            angle = (angle + 1) % 360
            if angle == b:
                break
    # 俯仰受限区 → 降级为 1
    for dz in parse_list(gun.get("pitch_dead_zones"), []) or []:
        if len(dz) >= 2:
            a = int(round((facing + dz[0]) % 360)) % 360
            b = int(round((facing + dz[1]) % 360)) % 360
            angle = a
            while True:
                if sec[angle]:
                    sec[angle] = 1
                angle = (angle + 1) % 360
                if angle == b:
                    break
    # 死区 → 强制 0
    for dz in parse_list(gun.get("dead_zones"), []) or []:
        if len(dz) >= 2:
            a = int(round((facing + dz[0]) % 360)) % 360
            b = int(round((facing + dz[1]) % 360)) % 360
            angle = a
            while True:
                sec[angle] = 0
                angle = (angle + 1) % 360
                if angle == b:
                    break
    return sec


# ── 齐射角 ─────────────────────────────────────────────

def _coverage(arcs, angle):
    a = angle % 360.0
    return any(x <= a <= y for x, y in arcs)


def _arc_center(arcs):
    """可射区间的角度质量中心（复数平均，避免跨 0° 问题）。"""
    total = 0.0
    wsum = 0.0
    for x, y in arcs:
        w = y - x
        if w <= 0:
            continue
        mid = math.radians((x + y) / 2.0)
        total += w * math.e ** (1j * mid)
        wsum += w
    if wsum <= 0:
        return 0.0
    c = total / wsum
    return math.degrees(math.atan2(c.imag, c.real)) % 360.0


def _salvo_exact(arcs, center):
    """从 center（0/90/180/270）到最近可射扇区边界的角距离（齐射角，度）。

    统一语义：前/后/左/右齐射角 = 从基准方向到「可射扇区边界」的最短角距。
    例如主炮 34 = 正前 0° 到全炮塔可射区间起点的距离（正前死区宽度）；
    副炮右舷组 15 = 正前 0° 到可射区间边界的距离（含跨 0° 另一侧）。
    """
    c = center % 360.0
    merged = _merge(arcs)
    total_span = sum(y - x for x, y in merged)
    if total_span >= 359.9:
        return 180.0  # 全圈可射
    best = 360.0
    for x, y in merged:
        for p in (x, y):
            d = min((p - c) % 360.0, (c - p) % 360.0)
            if d > 1e-6 and d < best:
                best = d
    return round(best, 1)


def firing_arc_angles(guns):
    """计算前后齐射角（度）。

    全炮塔可射扇区交集非空（中线布置，如主炮）：
        前向 = 从正前 0° 到全炮塔可射的最近边界；后向 = 从正后 180° 同理。
    全炮塔无法齐射（炮塔分列左右舷，如鱼雷/副炮）：
        右舷炮塔只能向右射击、左舷炮塔只能向左射击，互不交叉；
        前向齐射角 = 右舷炮塔群从正前 0° 的齐射角，
        后向齐射角 = 左舷炮塔群从正后 180° 的齐射角。

    返回 {"mode": "front_back", "front": int, "back": int}。
    """
    empty = {"mode": "front_back", "front": 0, "back": 0}
    if not guns:
        return empty
    facings = compute_facings(guns)
    entries = [(g, gun_abs_segments(g, f))
               for g, f in zip(guns, facings) if g.get("horiz_sector")]
    entries = [(g, s) for g, s in entries if s]
    if not entries:
        return empty
    total = entries[0][1]
    for _, s in entries[1:]:
        total = _intersect(total, s)
    total = _merge(total)
    if total:
        # 全炮塔可射且覆盖侧面（90°/270°）→ 中线布置（如主炮），用全炮塔前后
        if _coverage(total, 90.0) or _coverage(total, 270.0):
            return {
                "mode": "front_back",
                "front": int(round(_salvo_exact(total, 0.0))),
                "back": int(round(_salvo_exact(total, 180.0))),
            }
    # 全炮塔无法齐射，或仅在船头/船尾小范围可射（左右舷交叉布置，如鱼雷/副炮）
    # → 前向取右舷炮塔群、后向取左舷炮塔群
    right, left = [], []
    for _, a in entries:
        c = _arc_center(a)
        (right if 0 <= c < 180 else left).append(a)

    def _group(gps):
        if not gps:
            return None
        t = gps[0]
        for a in gps[1:]:
            t = _intersect(t, a)
        return _merge(t)

    ra, la = _group(right), _group(left)
    front = int(round(_salvo_exact(ra or la, 0.0))) if (ra or la) else 0
    back = int(round(_salvo_exact(la or ra, 180.0))) if (la or ra) else 0
    return {"mode": "front_back", "front": front, "back": back}
