"""
geometry_transform.py —— 解析空间 → 渲染空间的几何变换（单一事实来源）。

`.geometry` 解析器输出的顶点/法线位于「游戏解析空间」（左手系，Z 朝向观察者），
而 OpenGL 渲染器与 glTF 导出都需要「右手系 Y 向上」的渲染空间。两者只差一个
Z 镜像（negz = diag(1,1,-1,1)，det=-1 反射）。

本模块提供 prepare_render_mesh()，把单个网格从解析空间变换到渲染空间：

  - 位置：Z 取反（negz 反射）
  - 法线：按「源绕序 vs 源法线」一致性判定翻转（Z 反射会翻转三角形绕序，
    必须抵消否则内外面反）；绕序混合的网格逐三角形拆分对齐
  - 索引：绕序混合时复制顶点并重映射索引

渲染器（ui/geometry_renderer._build_meshes）与导出服务
（services/export_service）共用本函数，保证「查看器里看到的 = 导出的」，
杜绝导出与显示错位 / 朝向翻转。

⚠️ 这是行为敏感的共享函数：改动会影响渲染与导出，务必经探针回归。
"""

from __future__ import annotations

import numpy as np


def prepare_render_mesh(positions, normals, indices,
                        colors=None, uvs=None):
    """把解析空间网格变换为渲染空间（右手系，与 glTF 同构）网格。

    参数：
      positions (N,3) f32  解析空间顶点
      normals   (N,3) f32  解析空间法线
      indices   (M,)  u32  三角形索引
      colors    (N,4) f32  （可选）逐顶点颜色，随顶点拆分同步扩展
      uvs       (N,2) f32  （可选）逐顶点 UV，随顶点拆分同步扩展

    返回：
      (render_positions, render_normals, render_indices, render_uvs, render_colors)
      均为渲染空间数据；colors/uvs 在未提供时原样返回 None。

    变换规则（与 ui/geometry_renderer._build_meshes 完全同源）：
      1. 位置 Z 镜像（negz）：det=-1 反射转右手系
      2. 法线朝向修正：
         - 源绕序与源法线一致（c>0.5）→ 法线取 -negz（抵消反射后的绕序翻转）
         - 混合绕序（0.35≤c≤0.65）→ 坏三角形复制顶点并翻转法线
         - 否则法线取 negz
    """
    pos0 = np.asarray(positions, dtype=np.float32) if positions is not None else None
    n0 = np.asarray(normals, dtype=np.float32) if normals is not None else None
    idx = indices
    colors0 = colors
    uvs0 = uvs
    flip = np.array([1.0, 1.0, -1.0], dtype=np.float32)
    if (idx is not None and getattr(idx, "size", 0) >= 3
            and pos0 is not None and pos0.shape[0] > 0
            and n0 is not None and n0.shape[0] == pos0.shape[0]):
        try:
            tri = idx.reshape(-1, 3)
            v0 = pos0[tri[:, 0]]; v1 = pos0[tri[:, 1]]; v2 = pos0[tri[:, 2]]
            g = np.cross(v1 - v0, v2 - v0)
            gn = np.linalg.norm(g, axis=1)
            gn[gn < 1e-8] = 1.0
            g = g / gn[:, None]
            nv = n0[tri[:, 0]]
            c = float(((nv * g).sum(1) > 0).mean())
            if c > 0.5:
                flip = np.array([-1.0, -1.0, 1.0], dtype=np.float32)
            elif 0.35 <= c <= 0.65:
                # 绕序混合的 prim：单一 flip 无法统一 → 逐三角形拆分对齐
                # （法线与绕序相反的三角形复制顶点并翻转法线）
                bad = (nv * g).sum(1) < 0
                if bad.any() and not bad.all():
                    btri = tri[bad]
                    nb = btri.shape[0]
                    src = btri.ravel()   # 原顶点索引
                    extra_pos = pos0[src]
                    extra_n = -n0[src]
                    extra_idx = (np.arange(nb * 3).reshape(-1, 3)
                                 + len(pos0)).astype(np.uint32)
                    new_idx = idx.copy()
                    bad_flat = np.flatnonzero(bad)
                    for j, t in enumerate(bad_flat):
                        new_idx[t * 3:(t + 1) * 3] = extra_idx[j]
                    n_old = len(pos0)
                    pos0 = np.vstack([pos0, extra_pos])
                    n0 = np.vstack([n0, extra_n])
                    if colors0 is not None and colors0.shape[0] == n_old:
                        colors0 = np.vstack([colors0, colors0[src]])
                    if uvs0 is not None and uvs0.shape[0] == n_old:
                        uvs0 = np.vstack([uvs0, uvs0[src]])
                    idx = new_idx
                    flip = np.array([-1.0, -1.0, 1.0], dtype=np.float32)
        except Exception:  # noqa: BLE001 —— 法线修正失败不阻断导出/渲染
            pass
    p = np.ascontiguousarray(pos0 * np.array([1.0, 1.0, -1.0], dtype=np.float32))
    n = np.ascontiguousarray(n0 * flip)
    if colors0 is not None:
        colors0 = np.ascontiguousarray(colors0, dtype=np.float32)
    return p, n, idx, uvs0, colors0
