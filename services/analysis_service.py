"""
预分析服务 —— 在数据入库时运行解析器，将 AnalysisResult 存入数据库。

用法:
    svc = AnalysisService()
    svc.initialize()
    svc.precompute_all(db, progress_callback=...)
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from services.database_service import DatabaseManager


class AnalysisService:

    def __init__(self):
        self._analyzers: dict[str, BaseAnalyzer] = {}
        self._ready = False

    def initialize(self) -> None:
        from analyzers.ship_analyzer import ShipAnalyzer
        from analyzers.gun_analyzer import GunAnalyzer
        from analyzers.projectile_analyzer import ProjectileAnalyzer
        from analyzers.modernization_analyzer import ModernizationAnalyzer
        from analyzers.plane_analyzer import PlaneAnalyzer
        from analyzers.consumable_analyzer import ConsumableAnalyzer
        from analyzers.crew_analyzer import CrewAnalyzer
        for name, cls in [("Ship", ShipAnalyzer), ("Gun", GunAnalyzer),
                          ("Projectile", ProjectileAnalyzer), ("Modernization", ModernizationAnalyzer),
                          ("Aircraft", PlaneAnalyzer), ("Ability", ConsumableAnalyzer),
                          ("Crew", CrewAnalyzer)]:
            try:
                a = cls(); a.initialize_mapping()
                self._analyzers[name] = a
            except Exception as e:
                print(f"[Analysis] {name} 初始化失败: {e}")
        self._ready = bool(self._analyzers)

    @property
    def is_ready(self) -> bool:
        return self._ready

    def analyze_one(self, category: str, raw_data: dict) -> Optional[dict]:
        analyzer = self._analyzers.get(category)
        if not analyzer:
            return None
        try:
            result = analyzer.analyze(raw_data)
            return {
                "title": result.title,
                "subtitle": result.subtitle,
                "sections": [{"label": s.label, "items": [
                    {"name": i.name, "value": i.value, "raw_value": i.raw_value,
                     "unit": i.unit, "order": i.order} for i in s.items]}
                    for s in result.sections],
                "extra": result.extra,
            }
        except Exception as e:
            print(f"[Analysis] {category} 失败: {e}")
            return None

    def precompute_all(self, db: DatabaseManager, progress_callback=None) -> dict:
        if not self._ready:
            self.initialize()
        results: dict[str, int] = {}
        total_processed = 0
        stats = db.get_stats()
        total_entities = sum(stats.get("categories", {}).values())
        if total_entities == 0:
            return results
        batch: list[tuple[str, str, str]] = []
        for cat_name in self._analyzers:
            entities = db.list_entities(cat_name)
            success = 0
            for ent in entities:
                full = db.get_entity(cat_name, ent["id"])
                if not full:
                    continue
                analyzed = self.analyze_one(cat_name, full["raw_json"])
                if analyzed:
                    batch.append((cat_name, ent["id"], json.dumps(analyzed, ensure_ascii=False)))
                    success += 1
                    total_processed += 1
                if len(batch) >= 100:
                    for c, k, a in batch:
                        db.update_analyzed_json(c, k, a)
                    batch = []
                if progress_callback and total_processed % 50 == 0:
                    progress_callback(total_processed, total_entities, f"预分析 {total_processed}/{total_entities}")
            if batch:
                for c, k, a in batch:
                    db.update_analyzed_json(c, k, a)
                batch = []
            results[cat_name] = success
        if progress_callback:
            progress_callback(total_entities, total_entities, "预分析完成")
        return results
