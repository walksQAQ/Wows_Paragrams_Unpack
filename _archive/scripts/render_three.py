"""临时：渲染完整 Yamato 特写中部防空/副炮炮塔。"""
import os
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_OPENGL", "desktop")
import sys, time
import numpy as np
sys.path.insert(0, r'd:\Wows Paragrams Unpack')
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from services.geometry_service import GeometryService
svc = GeometryService.instance()
ships = svc.list_ships()
yam = next((s for s in ships if s.model_folder and 'JSB039' in s.model_folder), None)
t0 = time.time()
geom = svc.load_ship(yam, progress_cb=lambda p, m: None)
print(f'load {time.time()-t0:.0f}s mounts={len(geom.mounts)}')

from ui.geometry_renderer import GeometryViewport
vp = GeometryViewport()
vp.resize(1400, 800)
vp.set_scene(geom, show_hull=True, show_armor=False)
vp.set_view_options(show_mounts=True, wireframe=False)
vp.show(); app.processEvents()

# 特写 JGA179 三联装（HP_JGA_29 附近）从侧后方看，类似用户视角
for m in geom.mounts:
    if m.name == 'HP_JGA_29':
        pos = m.model_matrix[:3, 3]
        print("target:", m.name, m.model_folder, pos)
        vp._camera.target = pos.astype(np.float32)
        vp._camera.yaw = 120.0; vp._camera.pitch = 15.0
        vp._camera.zoom_to(6.0)
        vp.update(); app.processEvents()
        vp.grabFramebuffer().save(r'd:\Wows Paragrams Unpack\_archive\scripts\_three_turrets.png')
        print('saved three_turrets')
        break
