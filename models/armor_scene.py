"""
armor_scene.py —— 装甲场景聚合（世界空间三角形汤 + 层级索引 + 边界线 + 拾取）。

将 ShipGeometry.armor_meshes（各部件本地坐标的 ArmorMesh）聚合为单一
「装甲场景」，供渲染器与 UI 使用：

  - world_positions / world_normals / colors：扁平化世界空间三角形数据
  - tri_info：每三角形 ArmorTriangleInfo（厚度/材质/zone/layers/hidden/plate_key）
  - zones：zone → 部件(材质名) → thickness_tenths → [三角形索引] 三级层级
  - edge_positions / edge_tris：板块边界描边线段（wows-toolkit
    upload_plate_boundary_edges 语义：网格边界 ∨ 板块交界 ∨ 折角）
  - ray_pick：屏幕射线拾取（Möller–Trumbore，per-mesh AABB 预筛）

参考：landaire/wows-toolkit armor_viewer/ui/tab.rs（PlateKey / 边界边 / 显隐）。
"""

from __future__ import annotations

import numpy as np

from utils.threading_utils import TaskCancelled

#: 顶点量化系数（边键去重用；与 wows-toolkit 一致）
QUANT = 10000
#: 折角判定阈值：相邻面法线点积 < 该值视为折角边界（≈45°）
CREASE_DOT = 0.7


class ArmorScene:
    """聚合后的装甲场景（舰船空间）。"""

    def __init__(self) -> None:
        self.world_positions: np.ndarray = np.zeros((0, 3), dtype=np.float32)
        self.world_normals: np.ndarray = np.zeros((0, 3), dtype=np.float32)
        self.colors: np.ndarray = np.zeros((0, 4), dtype=np.float32)
        self.tri_info: list = []                 # list[ArmorTriangleInfo]，长度 T
        self.tri_count: int = 0
        #: 每三角形板块 id（plate_keys_by_id[plate_ids[t]] == plate_key）
        self.plate_ids: np.ndarray = np.zeros(0, dtype=np.int32)
        self.plate_keys_by_id: list[tuple] = []
        #: 每 ArmorMesh 的扁平三角形区间 (start, count)
        self.mesh_tri_range: list[tuple[int, int]] = []
        self.mesh_names: list[str] = []
        #: 每 ArmorMesh 世界 AABB（拾取预筛）
        self.mesh_aabb: list[tuple[np.ndarray, np.ndarray]] = []
        #: zone → part(材质名) → thickness_tenths → [tri_idx]
        self.zones: dict[str, dict[str, dict[int, list[int]]]] = {}
        #: 边界线段端点 (E*2,3) 与相邻三角形 (E,2)（-1 = 无）
        self.edge_positions: np.ndarray = np.zeros((0, 3), dtype=np.float32)
        self.edge_tris: np.ndarray = np.zeros((0, 2), dtype=np.int32)
        self.bounds_min: np.ndarray = np.zeros(3, dtype=np.float32)
        self.bounds_max: np.ndarray = np.zeros(3, dtype=np.float32)
        #: 板块键 → [tri_idx]；(zone, part) → [tri_idx]；zone → [tri_idx]
        self._plate_tris: dict[tuple, list[int]] = {}
        self._part_tris: dict[tuple, list[int]] = {}
        self._zone_tris: dict[str, list[int]] = {}

    # ── 构建 ────────────────────────────────────────────

    @staticmethod
    def _check_cancel(cancel_event) -> None:
        """协作式取消检查点：取消已请求则抛出 TaskCancelled（正常结束，非错误）。"""
        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelled

    @classmethod
    def build(cls, armor_meshes: list, cancel_event=None) -> "ArmorScene":
        """由 ArmorMesh 列表聚合场景（应用各自 model_matrix 到舰船空间）。

        cancel_event: 协作式取消事件；在批次边界检查，取消时抛 TaskCancelled。
        """
        sc = cls()
        meshes = [m for m in (armor_meshes or [])
                  if m is not None and m.positions.size]
        if not meshes:
            return sc

        pos_parts: list[np.ndarray] = []
        nrm_parts: list[np.ndarray] = []
        col_parts: list[np.ndarray] = []
        infos: list = []
        offset = 0
        # ArmorMesh.model_matrix 是渲染空间矩阵（已 negz 共轭），而本场景
        # 存储未镜像的舰船空间坐标——先转回舰船空间再应用，否则挂载装甲错位
        negz = np.diag([1.0, 1.0, -1.0, 1.0]).astype(np.float32)
        for m in meshes:
            cls._check_cancel(cancel_event)
            n_tri = m.positions.shape[0] // 3
            p = m.positions
            nm = m.normals
            if m.model_matrix is not None:
                mat = negz @ np.asarray(m.model_matrix, dtype=np.float32) @ negz
                hom = np.hstack([p, np.ones((p.shape[0], 1), dtype=np.float32)])
                p = (hom @ mat.T)[:, :3].astype(np.float32)
                # 挂点矩阵为刚体变换：法线直接用 3x3 旋转部分
                r3 = mat[:3, :3]
                nm = (nm @ r3.T).astype(np.float32)
            pos_parts.append(p)
            nrm_parts.append(nm)
            col_parts.append(m.colors)
            infos.extend(m.triangles)
            sc.mesh_tri_range.append((offset, n_tri))
            sc.mesh_names.append(m.name)
            sc.mesh_aabb.append(m.bounds_in_world())
            offset += n_tri

        sc.world_positions = np.concatenate(pos_parts, axis=0)
        sc.world_normals = np.concatenate(nrm_parts, axis=0)
        sc.colors = np.concatenate(col_parts, axis=0)
        sc.tri_info = infos
        sc.tri_count = len(infos)

        # 板块 id 化（plate_key → int）
        key_to_id: dict[tuple, int] = {}
        plate_ids = np.empty(sc.tri_count, dtype=np.int32)
        for t, info in enumerate(infos):
            if cancel_event is not None and (t & 0x1FFF) == 0:
                cls._check_cancel(cancel_event)
            k = info.plate_key
            pid = key_to_id.get(k)
            if pid is None:
                pid = len(sc.plate_keys_by_id)
                key_to_id[k] = pid
                sc.plate_keys_by_id.append(k)
            plate_ids[t] = pid
        sc.plate_ids = plate_ids

        # 层级索引：zone → part → thickness_tenths → [tri_idx]
        for t, info in enumerate(infos):
            if cancel_event is not None and (t & 0x1FFF) == 0:
                cls._check_cancel(cancel_event)
            tenths = info.plate_key[2] if len(info.plate_key) > 2 else round(info.thickness_mm * 10)
            part = info.material_name
            sc.zones.setdefault(info.zone, {}).setdefault(part, {}).setdefault(tenths, []).append(t)
            sc._plate_tris.setdefault(info.plate_key, []).append(t)
            sc._part_tris.setdefault((info.zone, part), []).append(t)
            sc._zone_tris.setdefault(info.zone, []).append(t)

        cls._check_cancel(cancel_event)
        sc._build_edges(cancel_event)

        if sc.world_positions.size:
            sc.bounds_min = sc.world_positions.min(axis=0)
            sc.bounds_max = sc.world_positions.max(axis=0)
        return sc

    def _build_edges(self, cancel_event=None) -> None:
        """提取板块边界线段（向量化）。

        输出条件（与 wows-toolkit 一致）：
          1. 网格边界：该边只有 1 个相邻三角形
          2. 板块边界：两侧三角形 plate_key 不同
          3. 折角：两侧面法线点积 < CREASE_DOT

        cancel_event: 在主要向量化阶段之间检查协作式取消。
        """
        T = self.tri_count
        if T == 0:
            return
        pos = self.world_positions

        # 面法线（几何法线，用于折角判定）
        v0 = pos[0::3]
        e1 = pos[1::3] - v0
        e2 = pos[2::3] - v0
        fn = np.cross(e1, e2)
        ln = np.linalg.norm(fn, axis=1)
        ln[ln < 1e-12] = 1.0
        fn = fn / ln[:, None]
        self._check_cancel(cancel_event)

        # 顶点量化 → 唯一顶点 id（跨三角形汤合并共享顶点）
        vq = np.round(pos.astype(np.float64) * QUANT).astype(np.int64)
        unique_v, inv = np.unique(vq, axis=0, return_inverse=True)
        # 每个唯一顶点的代表世界坐标（量化还原，保证共享顶点坐标一致、接缝闭合）
        unique_pos = (unique_v.astype(np.float64) / QUANT).astype(np.float32)
        self._check_cancel(cancel_event)

        # 三条边的端点唯一 id
        n3 = np.arange(T, dtype=np.int64) * 3
        ea = inv[n3]
        eb = inv[n3 + 1]
        ec = inv[n3 + 2]
        lo = np.concatenate([np.minimum(ea, eb), np.minimum(eb, ec), np.minimum(ec, ea)])
        hi = np.concatenate([np.maximum(ea, eb), np.maximum(eb, ec), np.maximum(ec, ea)])
        # 每条边属于的三角形（每条边 3 份）
        tri_of_edge = np.tile(np.arange(T, dtype=np.int64), 3)

        edge_struct = np.empty(lo.shape[0], dtype=[("lo", "<i8"), ("hi", "<i8")])
        edge_struct["lo"] = lo
        edge_struct["hi"] = hi
        order = np.argsort(edge_struct, kind="stable")
        s_lo = lo[order]
        s_hi = hi[order]
        s_tri = tri_of_edge[order]

        # 分组：相邻相等的边键为同一几何边
        diff = (s_lo[1:] != s_lo[:-1]) | (s_hi[1:] != s_hi[:-1])
        group_start = np.flatnonzero(diff) + 1
        starts = np.concatenate([[0], group_start])
        ends = np.concatenate([group_start, [len(s_lo)]])
        sizes = ends - starts

        emit_lo: list[np.ndarray] = []
        emit_hi: list[np.ndarray] = []
        emit_t1: list[np.ndarray] = []
        emit_t2: list[np.ndarray] = []
        self._check_cancel(cancel_event)

        # 单邻接边（网格边界）与 >2 邻接边（非流形，按边界处理）
        mask_single = sizes == 1
        if mask_single.any():
            st = starts[mask_single]
            emit_lo.append(s_lo[st])
            emit_hi.append(s_hi[st])
            emit_t1.append(s_tri[st])
            emit_t2.append(np.full(st.shape, -1, dtype=np.int64))
        mask_many = sizes > 2
        if mask_many.any():
            st = starts[mask_many]
            emit_lo.append(s_lo[st])
            emit_hi.append(s_hi[st])
            emit_t1.append(s_tri[st])
            emit_t2.append(np.full(st.shape, -1, dtype=np.int64))

        # 双邻接边：板块交界或折角才输出
        mask_pair = sizes == 2
        if mask_pair.any():
            st = starts[mask_pair]
            t1 = s_tri[st]
            t2 = s_tri[st + 1]
            p1 = self.plate_ids[t1]
            p2 = self.plate_ids[t2]
            dot = np.einsum("ij,ij->i", fn[t1], fn[t2])
            keep = (p1 != p2) | (dot < CREASE_DOT)
            if keep.any():
                emit_lo.append(s_lo[st[keep]])
                emit_hi.append(s_hi[st[keep]])
                emit_t1.append(t1[keep])
                emit_t2.append(t2[keep])
        self._check_cancel(cancel_event)

        if emit_lo:
            elo = np.concatenate(emit_lo)
            ehi = np.concatenate(emit_hi)
            et1 = np.concatenate(emit_t1)
            et2 = np.concatenate(emit_t2)
            # 端点坐标（量化还原，避免接缝）
            self.edge_positions = np.concatenate(
                [unique_pos[elo], unique_pos[ehi]], axis=1).reshape(-1, 3).astype(np.float32)
            self.edge_tris = np.stack([et1, et2], axis=1).astype(np.int32)
        else:
            self.edge_positions = np.zeros((0, 3), dtype=np.float32)
            self.edge_tris = np.zeros((0, 2), dtype=np.int32)

    # ── 查询 ────────────────────────────────────────────

    def tris_for_plate(self, plate_key: tuple) -> list[int]:
        return self._plate_tris.get(plate_key, [])

    def tris_for_part(self, zone: str, part: str) -> list[int]:
        return self._part_tris.get((zone, part), [])

    def tris_for_zone(self, zone: str) -> list[int]:
        return self._zone_tris.get(zone, [])

    def visible_edges(self, visible_tris: np.ndarray | None) -> np.ndarray:
        """按三角形可见性过滤边界线段，返回可见线段的端点 (E'*2,3)。"""
        if self.edge_positions.shape[0] == 0:
            return self.edge_positions
        if visible_tris is None:
            return self.edge_positions
        t1 = self.edge_tris[:, 0]
        t2 = self.edge_tris[:, 1]
        vis1 = visible_tris[t1]
        vis2 = (t2 >= 0) & visible_tris[np.maximum(t2, 0)]
        keep = vis1 | vis2
        if keep.all():
            return self.edge_positions
        return self.edge_positions.reshape(-1, 2, 3)[keep].reshape(-1, 3)

    # ── 拾取 ────────────────────────────────────────────

    def ray_pick(self, ro: np.ndarray, rd: np.ndarray,
                 visible_tris: np.ndarray | None = None) -> int | None:
        """射线拾取：返回最近的三角形索引（无命中返回 None）。

        ro/rd：舰船空间射线原点/方向（rd 需归一化）。
        visible_tris：长度 T 的布尔数组，仅拾取可见三角形。
        """
        if self.tri_count == 0:
            return None
        ro = np.asarray(ro, dtype=np.float64)
        rd = np.asarray(rd, dtype=np.float64)
        n = np.linalg.norm(rd)
        if n < 1e-12:
            return None
        rd = rd / n

        # per-mesh AABB 预筛，收集候选三角形
        cand: list[np.ndarray] = []
        for (start, count), (bmin, bmax) in zip(self.mesh_tri_range, self.mesh_aabb):
            if count <= 0:
                continue
            if visible_tris is not None and not visible_tris[start:start + count].any():
                continue
            if not _ray_aabb(ro, rd, bmin, bmax):
                continue
            idx = np.arange(start, start + count, dtype=np.int64)
            if visible_tris is not None:
                idx = idx[visible_tris[start:start + count]]
            if idx.size:
                cand.append(idx)
        if not cand:
            return None
        tris = np.concatenate(cand)

        # Möller–Trumbore（向量化）
        p = self.world_positions
        a = p[tris * 3].astype(np.float64)
        b = p[tris * 3 + 1].astype(np.float64)
        c = p[tris * 3 + 2].astype(np.float64)
        e1 = b - a
        e2 = c - a
        pv = np.cross(rd, e2)
        det = np.einsum("ij,ij->i", e1, pv)
        valid = np.abs(det) > 1e-12
        if not valid.any():
            return None
        inv_det = np.where(valid, 1.0 / np.where(det == 0, 1e-12, det), 0.0)
        tv = ro - a
        u = np.einsum("ij,ij->i", tv, pv) * inv_det
        qv = np.cross(tv, e1)
        v = (qv @ rd) * inv_det
        t = np.einsum("ij,ij->i", e2, qv) * inv_det
        hit = valid & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1.0 + 1e-6) & (t > 1e-6)
        if not hit.any():
            return None
        t_hit = np.where(hit, t, np.inf)
        return int(tris[int(np.argmin(t_hit))])


def _ray_aabb(ro: np.ndarray, rd: np.ndarray,
               bmin: np.ndarray, bmax: np.ndarray) -> bool:
    """射线与 AABB 相交测试（slab 法）。"""
    bmin = np.asarray(bmin, dtype=np.float64)
    bmax = np.asarray(bmax, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / rd
        t1 = (bmin - ro) * inv
        t2 = (bmax - ro) * inv
    t_enter = np.maximum(np.minimum(t1, t2), 0.0)
    t_exit = np.maximum(t1, t2)
    tmin = float(t_enter.max())
    tmax = float(t_exit.min())
    return bool(tmax >= tmin)
