# -*- coding: utf-8 -*-
"""全局审计：长边三角形过滤对每个 primitive 的影响（找误删 >5% 的模型）。"""
import os, sys, gc
os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, r"d:\Wows Paragrams Unpack")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import numpy as np
from services.geometry_service import GeometryService
from models.geometry_parser import parse_geometry

svc = GeometryService.instance()
ext = svc._get_extractor()
svc._get_assets_service()
fidx = svc._geometry_folder_index(ext)

# 统计：哪些 primitive 有超长边三角形（>0.5 对角，会被新过滤删除）
overall_total = 0
overall_long = 0
warn = []  # (folder, name, tri_before, tri_after, removed_ratio)
count = 0

# 遍历所有 folder（不重复读同文件）
for folder in list(fidx.keys()):
    for e in fidx[folder]:
        if not e.path.endswith('.geometry'):
            continue
        try:
            data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
            p = parse_geometry(data, file_path=e.path)
            del data
        except Exception:
            continue
        for i, pr in enumerate(p.primitives):
            if pr.indices is None or pr.indices.size == 0:
                continue
            tri = pr.indices.size // 3
            overall_total += tri
            P = pr.positions
            if tri < 4 or P.shape[0] == 0:
                continue
            I = pr.indices[:tri * 3].reshape(-1, 3)
            v0 = P[I[:, 0]]; v1 = P[I[:, 1]]; v2 = P[I[:, 2]]
            emax = np.maximum(np.maximum(
                np.linalg.norm(v1 - v0, axis=1),
                np.linalg.norm(v2 - v1, axis=1)),
                np.linalg.norm(v0 - v2, axis=1))
            diag = np.linalg.norm(P.max(0) - P.min(0))
            if diag <= 1e-6:
                continue
            long_n = int((emax > diag * 0.5).sum())
            if long_n:
                overall_long += long_n
                name = getattr(pr, 'name', '?')
                warn.append((folder, name, tri, tri - long_n, long_n / tri))
        del p
        count += 1
        if count % 300 == 0:
            print(f"... {count} files scanned", flush=True)
    gc.collect()

print(f"\nTOTAL files={count} triangles={overall_total} long_triangles={overall_long} ratio={overall_long/overall_total*100:.3f}%")
warn.sort(key=lambda w: -w[4])
print(f"primitive 受影响数={len(warn)}，其中删除比例>3%的:")
for folder, name, tb, ta, r in warn:
    if r > 0.03:
        print(f"  {folder} {name}: tri {tb}->{ta} (删{r*100:.1f}%)")
