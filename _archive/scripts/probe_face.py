# -*- coding: utf-8 -*-
"""检查 TurretShape 三角形长边分布（面错乱检测）。"""
import os
os.environ.pop("QT_QPA_PLATFORM", None)
import sys
import numpy as np
sys.path.insert(0, r"d:\Wows Paragrams Unpack")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from services.geometry_service import GeometryService
from models.geometry_parser import parse_geometry
svc = GeometryService.instance()
ext = svc._get_extractor()
svc._get_assets_service()
sdict = svc._strings_dict(svc._assets_svc.db)
fidx = svc._geometry_folder_index(ext)

def check_turret(folder):
    entries = fidx.get(folder) or []
    for e in entries:
        data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
        p = parse_geometry(data, file_path=e.path)
        del data
        for i, pr in enumerate(p.primitives):
            name = sdict.get(pr.mapping_id) or "?"
            if 'wire' in name.lower() or 'lod' in name.lower(): continue
            I = pr.indices
            if I is None or I.size == 0: continue
            P = pr.positions
            tri = I[:len(I)//3*3].reshape(-1, 3)
            v0, v1, v2 = P[tri[:,0]], P[tri[:,1]], P[tri[:,2]]
            e0 = np.linalg.norm(v1-v0, axis=1)
            e1 = np.linalg.norm(v2-v1, axis=1)
            e2 = np.linalg.norm(v0-v2, axis=1)
            emax = np.maximum(np.maximum(e0, e1), e2)
            # 包围盒对角
            diag = np.linalg.norm(P.max(0) - P.min(0))
            long_ratio = (emax > diag * 0.5).mean() * 100
            print(f"\n{folder} {name}: tri={len(tri)} diag={diag:.3f}")
            print(f"  边长 max={emax.max():.4f} mean={emax.mean():.4f} >半对角比例%={long_ratio:.1f}")
            if long_ratio > 3:
                # 找出长边三角形，看是否跨模型
                idx = np.where(emax > diag * 0.5)[0]
                print(f"  长边三角形数={len(idx)}")
                for t in idx[:5]:
                    a, b, c = tri[t]
                    print(f"    tri[{t}]: v{a}({P[a]}) v{b}({P[b]}) v{c}({P[c]}) len={emax[t]:.4f}")
            return

check_turret("JGA179_25mm_Type96_Triple_closed")
check_turret("JGA180_25mm_Type96_Triple_1945_closed")
check_turret("JGA181_25mm_Type96_light")
check_turret("JGA018_25mm_Type96_single")
