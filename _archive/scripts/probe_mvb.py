# -*- coding: utf-8 -*-
"""检查多 vertex buffer 模型的索引跨 buffer 引用。"""
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

for folder in ("JGA179_25mm_Type96_Triple_closed", "JGA180_25mm_Type96_Triple_1945_closed",
               "JGA181_25mm_Type96_light", "JGS158_127mm40_Type_89"):
    entries = fidx.get(folder) or []
    print(f"\n== {folder} ==")
    for e in entries:
        data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
        p = parse_geometry(data, file_path=e.path)
        del data
        # 每个 primitive：索引值范围 vs 对应 vbuf 顶点数
        for i, pr in enumerate(p.primitives):
            name = sdict.get(pr.mapping_id) or "?"
            vm = p.vertices_mapping[i]
            vbuf = vm.merged_buffer_index
            vb = p.vertex_buffers[vbuf]
            # 该 primitive 实际使用的顶点（v_start..v_start+v_count）
            v_start = vm.items_offset
            v_end = v_start + vm.items_count
            idx = pr.indices
            if idx is None or idx.size == 0: continue
            i_min = int(idx.min()); i_max = int(idx.max())
            nv = len(pr.positions)
            # 索引是否引用本 primitive 顶点范围外
            out_of_local = (i_max >= vm.items_count)
            print(f"  {name!r:30} vbuf={vbuf}({vb.format_name.split('/')[-1]}) "
                  f"vcount={vm.items_count} idx_range=[{i_min},{i_max}] 越界(相对本prim)={bool(out_of_local)}")
