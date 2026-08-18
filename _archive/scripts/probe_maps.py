# -*- coding: utf-8 -*-
"""检查 JGA180 TurretShape 所有 primitives 的顶点/索引覆盖。"""
import os, sys
os.environ.pop("QT_QPA_PLATFORM", None)
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

for folder in ["JGA180_25mm_Type96_Triple_1945_closed", "JGA179_25mm_Type96_Triple_closed"]:
    entries = fidx.get(folder) or []
    print(f"\n===== {folder}: {len(entries)} entries =====")
    for e in entries:
        data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
        p = parse_geometry(data, file_path=e.path)
        del data
        print(f"  {e.path.split('/')[-1]}  vmaps={len(p.vertices_mapping)} imaps={len(p.indices_mapping)} vbufs={len(p.vertex_buffers)} ibufs={len(p.index_buffers)}")
        for vi, vm in enumerate(p.vertices_mapping):
            name = sdict.get(vm.mapping_id) or "?"
            vb = p.vertex_buffers[vm.merged_buffer_index]
            print(f"    vm{vi} {name}: vbuf={vm.merged_buffer_index} off={vm.items_offset} cnt={vm.items_count} fmt={vb.format_name} (vbuf count={vb.count})")
            if vi < len(p.indices_mapping):
                im = p.indices_mapping[vi]
                ib = p.index_buffers[im.merged_buffer_index]
                I = ib.data[im.items_offset:im.items_offset+im.items_count]
                mx = int(I.max()) if I.size else -1
                print(f"       im{vi}: ibuf={im.merged_buffer_index} off={im.items_offset} cnt={im.items_count} idx_max={mx} tri={I.size//3}")
