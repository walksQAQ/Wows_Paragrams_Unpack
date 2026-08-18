# -*- coding: utf-8 -*-
"""检查 xyznuvrpc position 解析 + 渲染 wire 网格。"""
import os
os.environ.pop("QT_QPA_PLATFORM", None)
import sys
import numpy as np
sys.path.insert(0, r"d:\Wows Paragrams Unpack")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from services.geometry_service import GeometryService
from models.geometry_parser import parse_geometry, parse_vertex_format, unpack_vertices
svc = GeometryService.instance()
ext = svc._get_extractor()
svc._get_assets_service()
sdict = svc._strings_dict(svc._assets_svc.db)
fidx = svc._geometry_folder_index(ext)

entries = fidx.get("JGA180_25mm_Type96_Triple_1945_closed") or []
for e in entries:
    data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
    p = parse_geometry(data, file_path=e.path)
    del data
    for bi, vb in enumerate(p.vertex_buffers):
        print(f"\nvbuf[{bi}] {vb.format_name} stride={vb.stride} count={vb.count}")
        attrs = parse_vertex_format(vb.format_name)
        print("  attrs:", attrs)
        # 前 4 个顶点原始字节（position offset 附近）
        raw = vb.data
        for v in range(4):
            row = raw[v]
            pos = row[0:12].tobytes()
            fx = np.frombuffer(pos, dtype='<f4')
            print(f"  v{v}: pos_bytes={pos.hex()} -> f32={fx}")
    # 只用 wire 网格（vbuf1）渲染
    for i, pr in enumerate(p.primitives):
        name = sdict.get(pr.mapping_id) or "?"
        if 'wire' not in name.lower(): continue
        print(f"\n  {name}: v={len(pr.positions)} tri={pr.indices.size//3}")
        mn = pr.positions.min(0); mx = pr.positions.max(0)
        print(f"    pos bbox=({mn[0]:.3f},{mn[1]:.3f},{mn[2]:.3f})..({mx[0]:.3f},{mx[1]:.3f},{mx[2]:.3f})")
        print(f"    pos[:5]=\n{pr.positions[:5]}")
