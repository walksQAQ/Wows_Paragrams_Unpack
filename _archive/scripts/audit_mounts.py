# -*- coding: utf-8 -*-
"""快速审计：大和所有挂载模型 + 主文件的长边三角形比例（确认过滤不误删）。"""
import os, sys
os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, r"d:\Wows Paragrams Unpack")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import numpy as np
from services.geometry_service import GeometryService
from models.geometry_parser import parse_geometry

svc = GeometryService.instance()
ships = svc.list_ships()
yam = next(s for s in ships if s.model_folder and 'JSB039' in s.model_folder)
folders = set()
folders.add(yam.model_folder)
geom = svc.load_ship(yam, progress_cb=lambda p, m: None)
for m in geom.mounts:
    folders.add(m.model_folder)
print(f"mount 模型文件夹数={len(folders)}")
del geom

ext = svc._get_extractor()
svc._get_assets_service()
fidx = svc._geometry_folder_index(ext)

total = 0
long_n = 0
warn = []
for folder in folders:
    for e in fidx.get(folder) or []:
        if not e.path.endswith('.geometry'):
            continue
        data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
        p = parse_geometry(data, file_path=e.path)
        del data
        for pr in p.primitives:
            if pr.indices is None or pr.indices.size == 0:
                continue
            tri = pr.indices.size // 3
            total += tri
            P = pr.positions
            if tri < 4 or P.shape[0] == 0:
                continue
            I = pr.indices[:tri*3].reshape(-1, 3)
            v0 = P[I[:, 0]]; v1 = P[I[:, 1]]; v2 = P[I[:, 2]]
            emax = np.maximum(np.maximum(
                np.linalg.norm(v1-v0, axis=1),
                np.linalg.norm(v2-v1, axis=1)),
                np.linalg.norm(v0-v2, axis=1))
            diag = np.linalg.norm(P.max(0) - P.min(0))
            if diag <= 1e-6:
                continue
            ln = int((emax > diag*0.5).sum())
            if ln:
                long_n += ln
                warn.append((folder, pr.name, tri, tri-ln, ln/tri))
        del p

print(f"\nTOTAL mount tris={total} 长边三角形={long_n} 比例={long_n/total*100:.3f}%")
print(f"受影响 primitive={len(warn)}")
warn.sort(key=lambda w: -w[4])
for folder, name, tb, ta, r in warn:
    flag = "  <== 注意" if r > 0.03 else ""
    print(f"  {folder} {name}: tri {tb}->{ta} (删{r*100:.1f}%){flag}")
