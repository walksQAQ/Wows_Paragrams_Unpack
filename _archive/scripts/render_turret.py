# -*- coding: utf-8 -*-
"""渲染 TurretShape(xyznuvtpc) 单独 + 检查顶点数据。"""
import os
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_OPENGL", "desktop")
import sys
import numpy as np
sys.path.insert(0, r'd:\Wows Paragrams Unpack')
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from services.geometry_service import GeometryService, ShipGeometry, HullMesh
from models.geometry_parser import parse_geometry
svc = GeometryService.instance()
ext = svc._get_extractor()
svc._get_assets_service()
sdict = svc._strings_dict(svc._assets_svc.db)
fidx = svc._geometry_folder_index(ext)

from ui.geometry_renderer import GeometryViewport

def render_turret(folder, fname):
    entries = fidx.get(folder) or []
    for e in entries:
        data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
        p = parse_geometry(data, file_path=e.path)
        del data
        # 只取 TurretShape（非 wire、非 lod 高模）
        for i, pr in enumerate(p.primitives):
            name = sdict.get(pr.mapping_id) or "?"
            if 'wire' in name.lower() or 'lod' in name.lower(): continue
            vm = p.vertices_mapping[i]
            vb = p.vertex_buffers[vm.merged_buffer_index]
            print(f"{folder} {name}: fmt={vb.format_name} v={len(pr.positions)} tri={pr.indices.size//3} "
                  f"idx_max={pr.indices.max() if pr.indices.size else -1}")
            pos = pr.positions
            mn, mx = pos.min(0), pos.max(0)
            nan = int((~np.isfinite(pos)).sum())
            print(f"   bbox=({mn[0]:.2f},{mn[1]:.2f},{mn[2]:.2f})..({mx[0]:.2f},{mx[1]:.2f},{mx[2]:.2f}) nan={nan}")
            hm = HullMesh(name=name, positions=pos, normals=pr.normals, uvs=pr.uvs,
                          indices=pr.indices, vertex_count=len(pos))
            sg = ShipGeometry(game_key=folder, display_name=name, model_folder=folder, hull_meshes=[hm])
            sg.bounds_min = pos.min(0); sg.bounds_max = pos.max(0)
            vp = GeometryViewport(); vp.resize(800, 600)
            vp.set_scene(sg, show_hull=True, show_armor=False)
            vp.set_view_options(show_mounts=True, wireframe=False)
            vp.show(); app.processEvents()
            vp._camera.yaw = 55.0; vp._camera.pitch = 25.0
            vp._camera.zoom_to(vp._camera.distance * 1.3)
            vp.update(); app.processEvents()
            vp.grabFramebuffer().save(fname)
            print(f"   saved {fname}")
            return

render_turret("JGA179_25mm_Type96_Triple_closed", r'd:\Wows Paragrams Unpack\_archive\scripts\_tur_179.png')
render_turret("JGA180_25mm_Type96_Triple_1945_closed", r'd:\Wows Paragrams Unpack\_archive\scripts\_tur_180.png')
render_turret("JGS158_127mm40_Type_89", r'd:\Wows Paragrams Unpack\_archive\scripts\_tur_158.png')
