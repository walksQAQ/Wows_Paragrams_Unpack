"""
数据库服务 —— 轻量化 SQLite 数据存储。

将 20,000+ 零散 JSON 文件整合为单个 SQLite 数据库。
表名按模块前缀组织，保留 raw_json 列保持向后兼容。

数据库位置: data/game_data.db

表结构:
  entity_*      — 实体数据表（entity_Ship, entity_Gun, ...）
  lookup_*      — 查找表（lookup_name_mappings）
  meta_*        — 元数据（meta_schema_version, meta_game_versions）
  fts_entities  — FTS5 全文索引
  v_all_entities— 统一视图
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from utils.path_utils import get_data_dir


# ── 常量 ──────────────────────────────────────────────────
DB_SCHEMA_VERSION = 1

# 所有分类列表（每个对应一张 entity_ 表）
ALL_CATEGORIES: list[str] = [
    "Ship", "Gun", "Projectile", "Aircraft", "Ability", "Modernization", "Crew",
    "Achievement", "BattleScript", "Building", "Catapult", "ClanSupply",
    "Collection", "Component", "Director", "DogTag", "Exterior", "Finder",
    "Other", "Radar", "Sfx", "Unit",
]


def _tn(cat: str) -> str:
    """实体表全名: entity_Ship, entity_Gun, ..."""
    return f"entity_{cat}"


# ══════════════════════════════════════════════════════════
#  DatabaseManager
# ══════════════════════════════════════════════════════════

class DatabaseManager:
    """SQLite 数据库管理器（线程安全）"""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = Path(db_path) if db_path else get_data_dir() / "game_data.db"
        self._local = threading.local()

    # ── 连接管理 ──────────────────────────────────────────

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        return self._local.conn

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")
        conn.row_factory = sqlite3.Row
        return conn

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ══════════════════════════════════════════════════════
    #  Schema
    # ══════════════════════════════════════════════════════

    def initialize(self) -> None:
        """创建所有表、视图、索引（幂等）"""
        conn = self._conn
        parts = []

        # ── 三大类：专用列 ────────────────────────────────
        parts.append(f'''
            CREATE TABLE IF NOT EXISTS "{_tn("Ship")}" (
                id TEXT PRIMARY KEY, name TEXT DEFAULT '', idx TEXT DEFAULT '',
                nation TEXT DEFAULT '', species TEXT DEFAULT '',
                level INTEGER DEFAULT 0, group_type TEXT DEFAULT '',
                raw_json TEXT NOT NULL, analyzed_json TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_{_tn("Ship")}_nat ON "{_tn("Ship")}"(nation);
            CREATE INDEX IF NOT EXISTS idx_{_tn("Ship")}_spe ON "{_tn("Ship")}"(species);
            CREATE INDEX IF NOT EXISTS idx_{_tn("Ship")}_lvl ON "{_tn("Ship")}"(level);
        ''')
        parts.append(f'''
            CREATE TABLE IF NOT EXISTS "{_tn("Gun")}" (
                id TEXT PRIMARY KEY, name TEXT DEFAULT '', idx TEXT DEFAULT '',
                nation TEXT DEFAULT '', species TEXT DEFAULT '',
                barrel_diameter REAL DEFAULT 0, num_barrels INTEGER DEFAULT 0, shot_delay REAL DEFAULT 0,
                raw_json TEXT NOT NULL, analyzed_json TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_{_tn("Gun")}_nat ON "{_tn("Gun")}"(nation);
            CREATE INDEX IF NOT EXISTS idx_{_tn("Gun")}_spe ON "{_tn("Gun")}"(species);
        ''')
        parts.append(f'''
            CREATE TABLE IF NOT EXISTS "{_tn("Projectile")}" (
                id TEXT PRIMARY KEY, name TEXT DEFAULT '', idx TEXT DEFAULT '',
                nation TEXT DEFAULT '', ammo_type TEXT DEFAULT '',
                caliber REAL DEFAULT 0, damage REAL DEFAULT 0,
                raw_json TEXT NOT NULL, analyzed_json TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_{_tn("Projectile")}_amm ON "{_tn("Projectile")}"(ammo_type);
        ''')

        # ── 其余 19 个分类：通用结构 ─────────────────────
        for cat in ALL_CATEGORIES:
            if cat in ("Ship", "Gun", "Projectile"):
                continue
            parts.append(f'''
                CREATE TABLE IF NOT EXISTS "{_tn(cat)}" (
                    id TEXT PRIMARY KEY, name TEXT DEFAULT '', idx TEXT DEFAULT '',
                    nation TEXT DEFAULT '', species TEXT DEFAULT '', type TEXT DEFAULT '',
                    raw_json TEXT NOT NULL, analyzed_json TEXT DEFAULT ''
                );
            ''')

        # ── 查找表 ────────────────────────────────────────
        parts.append('''
            CREATE TABLE IF NOT EXISTS lookup_name_mappings (
                game_id TEXT PRIMARY KEY, zh_name TEXT NOT NULL, category TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_lookup_cat ON lookup_name_mappings(category);
        ''')

        # ── FTS5 ──────────────────────────────────────────
        parts.append('''
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_entities USING fts5(
                id, name, category, nation, species, tokenize='unicode61'
            );
        ''')

        # ── 统一视图 ──────────────────────────────────────
        view_parts = []
        for cat in ALL_CATEGORIES:
            tn = _tn(cat)
            if cat == "Ship":
                view_parts.append(f'SELECT id,\'{cat}\' AS category,name,idx,nation,species,\'\' AS type,level FROM "{tn}"')
            elif cat == "Gun":
                view_parts.append(f'SELECT id,\'{cat}\',name,idx,nation,species,\'\',0 FROM "{tn}"')
            elif cat == "Projectile":
                view_parts.append(f'SELECT id,\'{cat}\',name,idx,nation,ammo_type,\'\',0 FROM "{tn}"')
            else:
                view_parts.append(f'SELECT id,\'{cat}\',name,idx,nation,species,type,0 FROM "{tn}"')
        parts.append("CREATE VIEW IF NOT EXISTS v_all_entities AS " + " UNION ALL ".join(view_parts))

        # ── 元数据表 ──────────────────────────────────────
        parts.append('''
            CREATE TABLE IF NOT EXISTS meta_schema_version (
                version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS meta_game_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_version TEXT NOT NULL, wows_type TEXT NOT NULL DEFAULT '',
                bin_folder TEXT DEFAULT '', entity_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
        ''')

        # 逐条执行（按分号拆分，避免 executescript 长 SQL 问题）
        for p in parts:
            for stmt in p.split(";"):
                s = stmt.strip()
                if s:
                    conn.execute(s + ";")
        conn.commit()
        if self.get_current_version() == 0:
            self._record_version(DB_SCHEMA_VERSION)

    def get_current_version(self) -> int:
        try:
            cur = self._conn.execute(
                "SELECT version FROM meta_schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cur.fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _record_version(self, ver: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO meta_schema_version (version) VALUES (?)", (ver,)
        )
        self._conn.commit()

    # ══════════════════════════════════════════════════════
    #  字段提取
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _common(data: dict) -> dict:
        ti = data.get("typeinfo", {}) or {}
        return {"name": str(data.get("name", "")), "idx": str(data.get("index", "")),
                "nation": str(ti.get("nation", "")), "species": str(ti.get("species") or ""),
                "type": str(ti.get("type", ""))}

    @staticmethod
    def _ship(data: dict) -> dict:
        c = DatabaseManager._common(data)
        return {**c, "level": int(data.get("level", 0) or 0), "group_type": str(data.get("group", ""))}

    @staticmethod
    def _gun(data: dict) -> dict:
        c = DatabaseManager._common(data)
        bd = data.get("barrelDiameter")
        return {**c, "barrel_diameter": round(bd * 1000, 1) if isinstance(bd, (int, float)) else 0,
                "num_barrels": int(data.get("numBarrels", 0) or 0),
                "shot_delay": float(data.get("shotDelay", 0) or 0)}

    @staticmethod
    def _proj(data: dict) -> dict:
        c = DatabaseManager._common(data)
        return {**c, "ammo_type": str(data.get("ammoType", "")),
                "caliber": float(data.get("caliber", 0) or 0),
                "damage": float(data.get("damage", 0) or 0)}

    _ROUTE: dict[str, tuple[str, str]] = {
        "Ship": ("entity_Ship", "_ship"), "Gun": ("entity_Gun", "_gun"),
        "Projectile": ("entity_Projectile", "_proj"),
    }
    _EXTRA = {"Ship": ("level", "group_type"), "Gun": ("barrel_diameter", "num_barrels", "shot_delay"),
              "Projectile": ("ammo_type", "caliber", "damage")}

    # ══════════════════════════════════════════════════════
    #  写入
    # ══════════════════════════════════════════════════════

    def _extract(self, category: str, data: dict) -> dict:
        route = self._ROUTE.get(category)
        if route:
            return getattr(self, route[1])(data)
        return self._common(data)

    def _table(self, category: str) -> str:
        route = self._ROUTE.get(category)
        return route[0] if route else _tn(category)

    def _cols_vals(self, category: str, fields: dict) -> tuple[str, tuple]:
        if category == "Ship":
            cols = "id,name,idx,nation,species,level,group_type,raw_json"
            vals = (fields["id"], fields["name"], fields["idx"], fields["nation"],
                    fields["species"], fields["level"], fields["group_type"], fields["raw_json"])
        elif category == "Gun":
            cols = "id,name,idx,nation,species,barrel_diameter,num_barrels,shot_delay,raw_json"
            vals = (fields["id"], fields["name"], fields["idx"], fields["nation"],
                    fields["species"], fields["barrel_diameter"], fields["num_barrels"],
                    fields["shot_delay"], fields["raw_json"])
        elif category == "Projectile":
            cols = "id,name,idx,nation,ammo_type,caliber,damage,raw_json"
            vals = (fields["id"], fields["name"], fields["idx"], fields["nation"],
                    fields["ammo_type"], fields["caliber"], fields["damage"], fields["raw_json"])
        else:
            cols = "id,name,idx,nation,species,type,raw_json"
            vals = (fields["id"], fields["name"], fields["idx"], fields["nation"],
                    fields["species"], fields["type"], fields["raw_json"])
        return cols, vals

    def insert_entity(self, category: str, key: str, data: dict) -> None:
        f = self._extract(category, data)
        f["id"] = key
        f["raw_json"] = json.dumps(data, ensure_ascii=False, sort_keys=True)
        cols, vals = self._cols_vals(category, f)
        placeholders = ",".join("?" * len(vals))
        self._conn.execute(f'INSERT OR REPLACE INTO "{self._table(category)}" ({cols}) VALUES ({placeholders})', vals)
        self._conn.commit()

    def insert_entities_batch(self, items: list[tuple[str, str, dict]]) -> None:
        buckets: dict[str, list] = {}
        for category, key, data in items:
            f = self._extract(category, data)
            f["id"] = key
            f["raw_json"] = json.dumps(data, ensure_ascii=False, sort_keys=True)
            buckets.setdefault(category, []).append(f)
        conn = self._conn
        for cat, rows in buckets.items():
            table = self._table(cat)
            first, _ = self._cols_vals(cat, rows[0])
            placeholders = ",".join("?" * (first.count(",") + 1))
            conn.executemany(
                f'INSERT OR REPLACE INTO "{table}" ({first}) VALUES ({placeholders})',
                [self._cols_vals(cat, r)[1] for r in rows]
            )
        conn.commit()

    def update_analyzed_json(self, category: str, key: str, analyzed: str) -> None:
        self._conn.execute(f'UPDATE "{self._table(category)}" SET analyzed_json=? WHERE id=?', (analyzed, key))
        self._conn.commit()

    # ══════════════════════════════════════════════════════
    #  查询
    # ══════════════════════════════════════════════════════

    def get_entity(self, category: str, key: str) -> Optional[dict]:
        try:
            cur = self._conn.execute(f'SELECT * FROM "{self._table(category)}" WHERE id=?', (key,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["category"] = category
            d["raw_json"] = json.loads(d.get("raw_json", "{}"))
            ajson = d.get("analyzed_json", "") or ""
            d["analyzed_result"] = json.loads(ajson) if ajson else None
            return d
        except sqlite3.OperationalError:
            return None

    def list_entities(self, category: str, keyword: str = "",
                      limit: int = 0, offset: int = 0) -> list[dict]:
        conn = self._conn
        view = "v_all_entities"
        if keyword:
            p = f"%{keyword}%"
            sql = f"SELECT id,category,name,idx,nation,species,type FROM {view} WHERE category=? AND (id LIKE ? OR name LIKE ? OR idx LIKE ?) ORDER BY id"
            params = [category, p, p, p]
        else:
            sql = f"SELECT id,category,name,idx,nation,species,type FROM {view} WHERE category=? ORDER BY id"
            params = [category]
        if limit > 0:
            sql += f" LIMIT ? OFFSET ?"
            params += [limit, offset]
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []

    def count_entities(self, category: str, keyword: str = "") -> int:
        conn = self._conn
        if keyword:
            p = f"%{keyword}%"
            cur = conn.execute("SELECT COUNT(*) FROM v_all_entities WHERE category=? AND (id LIKE ? OR name LIKE ? OR idx LIKE ?)", (category, p, p, p))
        else:
            cur = conn.execute("SELECT COUNT(*) FROM v_all_entities WHERE category=?", (category,))
        return cur.fetchone()[0]

    def search_entities(self, category: str, keyword: str, limit: int = 50) -> list[dict]:
        try:
            cur = self._conn.execute("""
                SELECT e.id,e.category,e.name,e.idx,e.nation,e.species,'' AS type
                FROM fts_entities f JOIN v_all_entities e ON e.id=f.id AND e.category=f.category
                WHERE f.category=? AND fts_entities MATCH ? ORDER BY rank LIMIT ?
            """, (category, keyword, limit))
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return self.list_entities(category, keyword, limit)

    def get_categories(self) -> list[str]:
        try:
            return [r["category"] for r in self._conn.execute("SELECT DISTINCT category FROM v_all_entities ORDER BY category").fetchall()]
        except sqlite3.OperationalError:
            return []

    def get_stats(self) -> dict:
        conn = self._conn
        cats, total, size = {}, 0, 0
        for cat in ALL_CATEGORIES:
            try:
                tn = _tn(cat)
                c = conn.execute(f'SELECT COUNT(*), SUM(LENGTH(raw_json)) FROM "{tn}"').fetchone()
                cnt, sz = c[0] or 0, c[1] or 0
                cats[cat] = cnt; total += cnt; size += sz
            except sqlite3.OperationalError:
                pass
        try:
            mc = conn.execute("SELECT COUNT(*) FROM lookup_name_mappings").fetchone()[0]
        except sqlite3.OperationalError:
            mc = 0
        return {
            "total_entities": total, "total_size_mb": round(size / (1024 * 1024), 2),
            "db_file_size_mb": self.db_size_mb, "categories": cats, "name_mappings": mc,
        }

    # ══════════════════════════════════════════════════════
    #  FTS
    # ══════════════════════════════════════════════════════

    def rebuild_fts(self) -> None:
        conn = self._conn
        conn.execute("DELETE FROM fts_entities")
        for cat in ALL_CATEGORIES:
            try:
                conn.execute(f'INSERT INTO fts_entities(id,name,category,nation,species) SELECT id,name,\'{cat}\',nation,species FROM "{_tn(cat)}"')
            except sqlite3.OperationalError:
                pass
        conn.commit()

    # ══════════════════════════════════════════════════════
    #  名称映射
    # ══════════════════════════════════════════════════════

    def get_all_name_mappings(self, category: str = "") -> dict[str, str]:
        """获取所有（或指定分类的）名称映射为 {game_id: zh_name} 字典"""
        try:
            if category:
                cur = self._conn.execute(
                    "SELECT game_id, zh_name FROM lookup_name_mappings WHERE category=?",
                    (category,))
            else:
                cur = self._conn.execute("SELECT game_id, zh_name FROM lookup_name_mappings")
            return {r["game_id"]: r["zh_name"] for r in cur.fetchall()}
        except sqlite3.OperationalError:
            return {}

    def import_name_mappings(self, data_dir: str | Path) -> dict[str, int]:
        stats = {}
        for fn, cat in [("ship_names.json", "ship"), ("ammo_names.json", "ammo"),
                        ("guns_names.json", "gun"), ("consumable_names.json", "consumable"),
                        ("modernization_names.json", "modernization"),
                        ("plane_names.json", "plane"), ("rage_mode_names.json", "rage_mode")]:
            fp = Path(data_dir) / fn
            if not fp.exists():
                continue
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    items = [(k, v, cat) for k, v in json.load(f).items()]
                if items:
                    self._conn.executemany("INSERT OR REPLACE INTO lookup_name_mappings VALUES (?,?,?)", items)
                    self._conn.commit()
                    stats[fn] = len(items)
            except Exception:
                continue
        return stats

    # ══════════════════════════════════════════════════════
    #  游戏版本
    # ══════════════════════════════════════════════════════

    def record_game_version(self, game_version: str, wows_type: str = "",
                             bin_folder: str = "", entity_count: int = 0) -> None:
        self._conn.execute("INSERT INTO meta_game_versions (game_version,wows_type,bin_folder,entity_count) VALUES (?,?,?,?)",
                           (game_version, wows_type, str(bin_folder), entity_count))
        self._conn.commit()

    def get_latest_game_version(self) -> Optional[str]:
        try:
            r = self._conn.execute("SELECT game_version FROM meta_game_versions ORDER BY id DESC LIMIT 1").fetchone()
            return r["game_version"] if r else None
        except sqlite3.OperationalError:
            return None

    def get_game_versions(self, limit: int = 10) -> list[dict]:
        try:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM meta_game_versions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        except sqlite3.OperationalError:
            return []

    # ══════════════════════════════════════════════════════
    #  数据库管理
    # ══════════════════════════════════════════════════════

    @property
    def exists(self) -> bool:
        return self._db_path.exists()

    @property
    def db_size_mb(self) -> float:
        return round(self._db_path.stat().st_size / (1024 * 1024), 2) if self._db_path.exists() else 0.0

    @property
    def db_path(self) -> Path:
        return self._db_path

    def vacuum(self) -> None:
        self._conn.execute("VACUUM")

    def drop_all(self) -> None:
        conn = self._conn
        for cat in ALL_CATEGORIES:
            try:
                conn.execute(f'DELETE FROM "{_tn(cat)}"')
            except sqlite3.OperationalError:
                pass
        for t in ["lookup_name_mappings", "meta_game_versions", "meta_schema_version"]:
            try:
                conn.execute(f"DELETE FROM {t}")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("DELETE FROM fts_entities")
        except sqlite3.OperationalError:
            pass
        conn.commit()

    def rebuild_from_split(self, split_dir: str | Path, progress_callback=None) -> dict:
        split_path = Path(split_dir)
        if not split_path.exists():
            raise FileNotFoundError(f"split 目录不存在: {split_dir}")
        all_files = list(split_path.rglob("*.json"))
        total = len(all_files)
        if total == 0:
            return {"entities": 0, "mappings": 0}
        self.initialize()
        batch, processed = [], 0
        for fp in all_files:
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                batch.append((fp.parent.name, fp.stem, data))
                processed += 1
                if len(batch) >= 500:
                    self.insert_entities_batch(batch)
                    batch = []
                    if progress_callback:
                        progress_callback(processed, total, f"导入 {processed}/{total}")
            except Exception:
                continue
        if batch:
            self.insert_entities_batch(batch)
        ms = self.import_name_mappings(get_data_dir())
        self.rebuild_fts()
        self.vacuum()
        return {"entities": processed, "mappings": sum(ms.values())}


# ── 全局单例 ──────────────────────────────────────────────
_db: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        _db = DatabaseManager()
        if _db.exists:
            _db.initialize()
    return _db


def reset_db() -> None:
    global _db
    if _db:
        _db.close()
    _db = None
