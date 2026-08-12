"""离屏渲染版本比对对话框，生成信息面板截图用于视觉验证。

用法:
  $env:QT_QPA_PLATFORM="offscreen"
  .venv\\Scripts\\python.exe _archive\\scripts\\screenshot_diff_dialog.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from services.database_service import DatabaseManager
from services.diff_service import DiffService


def _wait_idle(app, pred, timeout=15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if pred():
            break
        time.sleep(0.02)
    app.processEvents()
    return pred()


def _seed(db: DatabaseManager):
    def _snap(eid, etype, data):
        return (eid, etype, "USA", json.dumps(data, sort_keys=True, ensure_ascii=False))

    def _item(cat, eid, data):
        return (cat, eid, data)

    ship_a1 = {
        "typeinfo": {"type": "Ship", "nation": "USA", "level": 10, "ship_class": "Battleship"},
        "artillery": {"A1_Artillery": {"reload_time": 6.4, "max_range": 18000.0,
                                        "caliber": 406, "sigma": 2.1,
                                        "rotation_time": 45.0}},
        "hull": {"HullA": {"hp": 65500, "turning_radius": 920, "rudder_time": 15.2}},
        "modules": [{"id": "M1", "name": "主炮组一", "hp": 100},
                    {"id": "M2", "name": "副炮组一", "hp": 80}],
    }
    ship_a2 = {
        "typeinfo": {"type": "Ship", "nation": "USA", "level": 10, "ship_class": "Battleship"},
        "artillery": {"A1_Artillery": {"reload_time": 6.2, "max_range": 18000.0,
                                        "caliber": 406, "sigma": 2.1,
                                        "rotation_time": 45.0}},
        "hull": {"HullA": {"hp": 66000, "turning_radius": 920, "rudder_time": 15.2}},
        "modules": [{"id": "M1", "name": "主炮组一", "hp": 100},
                    {"id": "M2", "name": "副炮组一", "hp": 80}],
    }
    v1 = db.begin_version("v26.6.1.0")
    db.insert_entities_batch([_item("Ship", "SHIP_A", ship_a1)], version_code=v1)
    db.save_entity_snapshots([_snap("SHIP_A", "ship", ship_a1)], version_code=v1)
    v2 = db.begin_version("v26.7.0.0")
    db.insert_entities_batch([_item("Ship", "SHIP_A", ship_a2)], version_code=v2)
    db.save_entity_snapshots([_snap("SHIP_A", "ship", ship_a2)], version_code=v2)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="diff_shot_")
    db = DatabaseManager(db_path=os.path.join(tmp, "ui.db"))
    db.initialize()
    _seed(db)

    from ui.version_diff_dialog import VersionDiffDialog
    dlg = VersionDiffDialog()
    dlg._svc = DiffService(db)
    dlg.resize(1240, 820)
    dlg.show()
    app.processEvents()
    dlg._load_versions()
    dlg._on_compare()
    assert _wait_idle(app, lambda: not dlg._busy), "比对超时"
    row = next(i for i in range(dlg.entity_table.rowCount())
               if dlg.entity_table.item(i, 1).text() == "SHIP_A")
    dlg._on_entity_clicked(row, 1)
    assert _wait_idle(app, lambda: dlg.field_tree.topLevelItemCount() > 0), "面板未填充"
    app.processEvents()
    print(f"field_counts = {dlg._field_counts}")
    print(f"tree top items = {[dlg.field_tree.topLevelItem(i).text(0) for i in range(dlg.field_tree.topLevelItemCount())]}")

    out = ROOT / "_archive" / "scripts" / "diff_panel_preview.png"
    dlg.grab().save(str(out))
    print(f"saved: {out}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
