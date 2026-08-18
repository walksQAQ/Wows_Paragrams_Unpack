# -*- coding: utf-8 -*-
"""调查缅因 127 副炮贴图 + North Dakota 加载警告。"""
import os, sys, time
os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, r"d:\Wows Paragrams Unpack")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
import numpy as np
from services.geometry_service import GeometryService

svc = GeometryService.instance()
ships = svc.list_ships()
print(f"total ships={len(ships)}")
for s in ships:
    name = (s.display_name or s.game_key or '')
    low = name.lower()
    if 'pasb111' in low or 'maine' in low or 'north_dakota' in low or 'pasb529' in low:
        print(f"{s.game_key} | {s.display_name} | model_folder={s.model_folder}")
