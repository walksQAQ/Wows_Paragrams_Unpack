"""
数据库服务 —— 基于合并解析级架构 (Merged Analysis Schema)。

作者: walksQAQ
许可证: 详见 LICENSE 文件

架构:
  1. 本地化层 — name_mappings / po_translations / enum_translations
  2. 存储层   — entity_registry (实体注册索引)
  3. 分析层   — ship_* / gun_* / projectile_* / plane_* / consumable_* / modernization_* / crew_*
  4. 元数据   — meta_schema_version / meta_game_versions

与原版差异:
  - 取消 22 张 entity_* 分表，合并为 1 张 entity_registry
  - 分析结果不再存 JSON blob，存入结构化分析表
  - 本地化独立入库，支持 JSON 映射 + PO 翻译 + 枚举字典
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from utils.path_utils import get_data_dir, get_bundled_dir


# ── 常量 ──────────────────────────────────────────────────
DB_SCHEMA_VERSION = 2

# 实体分类 (映射到 raw_entities.entity_type)
ENTITY_TYPES: list[str] = [
    "ship", "gun", "projectile", "plane", "consumable", "modernization", "crew",
]

# JSON 映射文件 → name_mappings.category
NAME_MAPPING_FILES: dict[str, str] = {
    "ship_names.json": "ship",
    "ammo_names.json": "ammo",
    "guns_names.json": "gun",
    "consumable_names.json": "consumable",
    "modernization_names.json": "modernization",
    "plane_names.json": "plane",
    "rage_mode_names.json": "rage_mode",
}


# ══════════════════════════════════════════════════════════
#  DatabaseManager
# ══════════════════════════════════════════════════════════

class DatabaseManager:
    """SQLite 数据库管理器（线程安全，固定 game_data.db）"""

    def __init__(self, db_path: str | Path | None = None):
        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = get_data_dir() / "game_data.db"
        self._local = threading.local()

    @staticmethod
    def _versioned_path(data_dir: Path, wows_type: str, version: str,
                        bin_folder: str = "") -> Path:
        """统一使用 game_data.db（版本信息由内部表追踪）"""
        return data_dir / "game_data.db"

    @staticmethod
    def prune_old_files(data_dir: Path) -> None:
        """清理残留的 game_data_*.db 分版本文件"""
        for f in data_dir.glob("game_data_*.db"):
            if f.name == "game_data.db":
                continue
            try:
                f.unlink()
            except Exception:
                pass

    # ── 连接管理 ──────────────────────────────────────────

    # 全部分类跟踪所有已创建的连接，方便跨线程关闭
    _all_connections: set[sqlite3.Connection] = set()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        else:
            # 检查连接是否已被 close_all_connections() 关闭
            try:
                self._local.conn.execute("SELECT 1")
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                self._local.conn = self._create_connection()
        return self._local.conn

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False,
                               timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        type(self)._all_connections.add(conn)
        return conn

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            type(self)._all_connections.discard(self._local.conn)
            self._local.conn = None

    @classmethod
    def close_all_connections(cls) -> None:
        """关闭所有已创建的数据库连接（跨线程）"""
        for conn in list(cls._all_connections):
            try:
                conn.close()
            except Exception:
                pass
        cls._all_connections.clear()

    # ══════════════════════════════════════════════════════
    #  Schema (从 resources/database/database.sql 同步)
    # ══════════════════════════════════════════════════════

    def initialize(self) -> None:
        """创建所有表、视图、索引（幂等）"""
        sql_path = get_bundled_dir() / "resources" / "database" / "database.sql"
        if sql_path.exists():
            sql_text = sql_path.read_text(encoding="utf-8")
            self._conn.executescript(sql_text)
        else:
            self._init_core_tables()
        # 创建加载版本追踪表
        self._init_load_tracking()
        self._conn.commit()

        # ── 向后兼容：补充旧 DB 可能缺失的列 ──
        for tbl, col, col_def in [
            ("ship_module_aircraft", "armament_name", "TEXT"),
            ("ship_module_aircraft", "module_variant", "TEXT DEFAULT ''"),
            ("ship_rage_mode", "description_ids", "TEXT DEFAULT ''"),
            ("ship_rage_mode", "modifiers_json", "TEXT DEFAULT '{}'"),
            ("ship_rage_mode", "triggers_json", "TEXT DEFAULT '[]'"),
            ("ship_module_aa", "bubble_damage", "REAL"),
            ("plane_basic_info", "armament_name_zh", "TEXT DEFAULT ''"),
            ("plane_basic_info", "max_speed", "REAL"),
            ("plane_basic_info", "min_speed", "REAL"),
            ("consumable_basic_info", "extra_json", "TEXT DEFAULT '{}'"),
            ("projectile_basic_info", "extra_json", "TEXT DEFAULT '{}'"),
            ("projectile_basic_info", "damage", "REAL"),
            ("projectile_basic_info", "alpha_piercing_cs", "REAL"),
            ("projectile_basic_info", "depth_splash_size", "REAL"),
            ("projectile_basic_info", "depth_splash_size_to_torpedo", "REAL"),
            ("projectile_basic_info", "custom_ui_postfix", "TEXT DEFAULT ''"),
            ("crew_unique_skills", "effects_json", "TEXT DEFAULT '{}'"),
            ("ship_module_artillery", "drum_shots_count", "INTEGER DEFAULT 0"),
            ("ship_module_artillery", "drum_shot_delay", "REAL DEFAULT 0"),
            ("ship_module_artillery", "drum_full_reload_time", "REAL DEFAULT 0"),
            ("ship_module_artillery", "drum_is_switchable", "INTEGER DEFAULT 0"),
            ("ship_module_artillery", "drum_is_chargeable", "INTEGER DEFAULT 0"),
            ("ship_module_artillery", "drum_charge_time_min", "REAL DEFAULT 0"),
            ("ship_module_artillery", "drum_charge_time_max", "REAL DEFAULT 0"),
            ("ship_module_artillery", "drum_charge_mode", "INTEGER DEFAULT 0"),
            ("ship_module_artillery", "drum_modifiers_json", "TEXT DEFAULT '{}'"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass  # 列已存在

        if self.get_current_version() < DB_SCHEMA_VERSION:
            self._record_version(DB_SCHEMA_VERSION)

    def _init_core_tables(self) -> None:
        """内联核心表定义（SQL 文件不存在时兜底）"""
        c = self._conn
        c.execute("""CREATE TABLE IF NOT EXISTS name_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, key_name TEXT NOT NULL,
            lang_zh TEXT NOT NULL, UNIQUE(category, key_name))""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mappings_lookup ON name_mappings(category, key_name)")
        c.execute("""CREATE TABLE IF NOT EXISTS po_translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msgid TEXT NOT NULL UNIQUE, msgstr TEXT NOT NULL, context TEXT DEFAULT '')""")
        c.execute("""CREATE TABLE IF NOT EXISTS enum_translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enum_type TEXT NOT NULL, enum_key TEXT NOT NULL,
            lang_zh TEXT NOT NULL, UNIQUE(enum_type, enum_key))""")
        c.execute("""CREATE TABLE IF NOT EXISTS entity_registry (
            entity_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL,
            nation TEXT, shiptype TEXT, tier INTEGER)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_registry_filter ON entity_registry(entity_type, nation, shiptype, tier)")
        c.execute("""CREATE TABLE IF NOT EXISTS entity_dynamic_attributes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
            scope TEXT NOT NULL, attr_key TEXT NOT NULL,
            attr_value TEXT, attr_value_num REAL,
            UNIQUE(entity_id, scope, attr_key))""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dynamic_attr_lookup ON entity_dynamic_attributes(entity_id, scope)")
        c.execute("""CREATE TABLE IF NOT EXISTS ship_sub_depth_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hull_ref_id INTEGER NOT NULL REFERENCES ship_module_hulls(id) ON DELETE CASCADE,
            state_name TEXT NOT NULL, underwater_max_speed REAL,
            buoyancy_burn_rate REAL, visibility_factor REAL,
            UNIQUE(hull_ref_id, state_name))""")
        c.execute("""CREATE TABLE IF NOT EXISTS rel_ship_weapon_ammo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weapon_type TEXT NOT NULL, weapon_ref_id INTEGER NOT NULL,
            ammo_id TEXT NOT NULL,
            UNIQUE(weapon_type, weapon_ref_id, ammo_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS ship_module_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ship_id TEXT NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
            module_letter TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            source_key TEXT DEFAULT '',
            display_order INTEGER DEFAULT 0,
            UNIQUE(ship_id, module_letter, sub_category))""")
        c.execute("""CREATE TABLE IF NOT EXISTS gun_drum_details (
            gun_id TEXT PRIMARY KEY,
            clip_size INTEGER, clip_reload_time REAL,
            burst_count INTEGER, burst_reload_time REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS meta_schema_version (
            version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now','localtime')))""")
        c.execute("""CREATE TABLE IF NOT EXISTS meta_game_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_version TEXT NOT NULL, wows_type TEXT NOT NULL DEFAULT '',
            bin_folder TEXT DEFAULT '', entity_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')))""")


    def get_current_version(self) -> int:
        try:
            cur = self._conn.execute(
                "SELECT version FROM meta_schema_version ORDER BY version DESC LIMIT 1")
            row = cur.fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _record_version(self, ver: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO meta_schema_version (version) VALUES (?)", (ver,))
        self._conn.commit()

    # ══════════════════════════════════════════════════════
    #  实体注册 (写入 entity_registry)
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _entity_type(category: str) -> str:
        mapping = {
            "Ship": "ship", "Gun": "gun", "Projectile": "projectile",
            "Aircraft": "plane", "Ability": "consumable",
            "Modernization": "modernization", "Crew": "crew",
        }
        return mapping.get(category, category.lower())

    @staticmethod
    def _extract_filters(data: dict) -> dict:
        ti = data.get("typeinfo", {}) or {}
        raw_level = data.get("level", 0)
        if isinstance(raw_level, dict):
            raw_level = 0
        return {"nation": str(ti.get("nation", "")),
                "shiptype": str(ti.get("species") or ""),
                "tier": int(raw_level or 0)}

    def insert_entity(self, category: str, key: str, data: dict) -> None:
        """注册实体到 entity_registry（不再存储 raw_json）"""
        etype = self._entity_type(category)
        flt = self._extract_filters(data)
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_registry "
            "(entity_id, entity_type, nation, shiptype, tier) "
            "VALUES (?,?,?,?,?)",
            (key, etype, flt["nation"], flt["shiptype"], flt["tier"]))
        self._conn.commit()

    def insert_entities_batch(self, items: list[tuple[str, str, dict]],
                              load_seq: int = 0) -> None:
        """批量注册实体到 entity_registry（不再存储 raw_json）

        如果指定 load_seq，会自动记录实体批次归属。
        """
        rows = []
        entity_ids = []
        for category, key, data in items:
            etype = self._entity_type(category)
            flt = self._extract_filters(data)
            rows.append((key, etype, flt["nation"], flt["shiptype"], flt["tier"]))
            entity_ids.append(key)
        # 使用 UPSERT（INSERT … ON CONFLICT DO UPDATE）代替 INSERT OR REPLACE，
        # 避免 DELETE + INSERT 触发 ON DELETE CASCADE 清空 ship_basic_info 等分析表。
        self._conn.executemany(
            "INSERT INTO entity_registry "
            "(entity_id, entity_type, nation, shiptype, tier) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(entity_id) DO UPDATE SET "
            "  entity_type=excluded.entity_type,"
            "  nation=excluded.nation,"
            "  shiptype=excluded.shiptype,"
            "  tier=excluded.tier", rows)
        if load_seq > 0 and entity_ids:
            self.record_entities_load(entity_ids, load_seq)
        self._conn.commit()

    # ══════════════════════════════════════════════════════
    #  查询 (从 entity_registry + 分析表读取)
    # ══════════════════════════════════════════════════════

    def get_entity(self, category: str, key: str) -> Optional[dict]:
        etype = self._entity_type(category)
        try:
            cur = self._conn.execute(
                "SELECT * FROM entity_registry WHERE entity_id=? AND entity_type=?",
                (key, etype))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["category"] = category
            d["raw_json"] = None  # 新架构不存储 raw_json
            d["analyzed_result"] = self._get_analyzed_result(etype, key)
            return d
        except sqlite3.OperationalError:
            return None

    def _get_analyzed_result(self, etype: str, key: str) -> Optional[dict]:
        """委托 PresenterRegistry 从结构化分析表读取分析结果"""
        try:
            from presenters.registry import PresenterRegistry
            return PresenterRegistry.build(etype, key, self._conn)
        except sqlite3.OperationalError:
            return None

    def list_entities(self, category: str, keyword: str = "",
                      limit: int = 0, offset: int = 0) -> list[dict]:
        etype = self._entity_type(category)
        conn = self._conn
        if keyword:
            p = f"%{keyword}%"
            sql = ("SELECT entity_id AS id, entity_type AS category, "
                   "entity_id AS name, '' AS idx, nation, shiptype AS species, '' AS type "
                   "FROM entity_registry WHERE entity_type=? AND entity_id LIKE ? "
                   "ORDER BY entity_id")
            params = [etype, p]
        else:
            sql = ("SELECT entity_id AS id, entity_type AS category, "
                   "entity_id AS name, '' AS idx, nation, shiptype AS species, '' AS type "
                   "FROM entity_registry WHERE entity_type=? ORDER BY entity_id")
            params = [etype]
        if limit > 0:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []

    def count_entities(self, category: str, keyword: str = "") -> int:
        etype = self._entity_type(category)
        conn = self._conn
        if keyword:
            p = f"%{keyword}%"
            cur = conn.execute(
                "SELECT COUNT(*) FROM entity_registry WHERE entity_type=? AND entity_id LIKE ?",
                (etype, p))
        else:
            cur = conn.execute(
                "SELECT COUNT(*) FROM entity_registry WHERE entity_type=?", (etype,))
        return cur.fetchone()[0]

    def search_entities(self, category: str, keyword: str, limit: int = 50) -> list[dict]:
        return self.list_entities(category, keyword, limit)

    def get_categories(self) -> list[str]:
        rev = {"ship": "Ship", "gun": "Gun", "projectile": "Projectile",
               "plane": "Aircraft", "consumable": "Ability",
               "modernization": "Modernization", "crew": "Crew"}
        try:
            types = [r["entity_type"] for r in self._conn.execute(
                "SELECT DISTINCT entity_type FROM entity_registry ORDER BY entity_type"
            ).fetchall()]
            return [rev.get(t, t.capitalize()) for t in types]
        except sqlite3.OperationalError:
            return []

    def get_stats(self) -> dict:
        conn = self._conn
        cats, total = {}, 0
        try:
            for et in ENTITY_TYPES:
                c = conn.execute(
                    "SELECT COUNT(*) FROM entity_registry WHERE entity_type=?",
                    (et,)).fetchone()
                cnt = c[0] or 0
                cats[et] = cnt; total += cnt
        except sqlite3.OperationalError:
            pass
        try:
            mc = conn.execute("SELECT COUNT(*) FROM name_mappings").fetchone()[0]
        except sqlite3.OperationalError:
            mc = 0
        return {"total_entities": total,
                "db_file_size_mb": self.db_size_mb,
                "categories": cats, "name_mappings": mc}

    # ══════════════════════════════════════════════════════
    #  本地化
    # ══════════════════════════════════════════════════════

    def get_all_name_mappings(self, category: str = "") -> dict[str, str]:
        try:
            if category:
                cur = self._conn.execute(
                    "SELECT key_name, lang_zh FROM name_mappings WHERE category=?",
                    (category,))
            else:
                cur = self._conn.execute("SELECT key_name, lang_zh FROM name_mappings")
            return {r["key_name"]: r["lang_zh"] for r in cur.fetchall()}
        except sqlite3.OperationalError:
            return {}

    def import_name_mappings(self, data_dir: str | Path) -> dict[str, int]:
        stats = {}
        for fn, cat in NAME_MAPPING_FILES.items():
            fp = Path(data_dir) / fn
            if not fp.exists():
                continue
            try:
                items = [(cat, k, v)
                         for k, v in json.loads(fp.read_text(encoding="utf-8")).items()]
                if items:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO name_mappings "
                        "(category, key_name, lang_zh) VALUES (?,?,?)", items)
                    self._conn.commit()
                    stats[fn] = len(items)
                # 入库后删除 JSON 文件
                fp.unlink(missing_ok=True)
            except Exception:
                continue
        return stats

    def import_po_translations(self, po_path: str | Path) -> int:
        fp = Path(po_path)
        if not fp.exists():
            return 0
        text = fp.read_text(encoding="utf-8")
        items = []
        blocks = re.split(r'\n(?=msgid)', text)
        for block in blocks:
            m = re.search(r'^msgid\s+"(.+)"\s*$', block, re.MULTILINE)
            s = re.search(r'^msgstr\s+"(.+)"\s*$', block, re.MULTILINE)
            if m and s and m.group(1) and s.group(1):
                items.append((m.group(1), s.group(1), ""))
        if items:
            self._conn.executemany(
                "INSERT OR REPLACE INTO po_translations "
                "(msgid, msgstr, context) VALUES (?,?,?)", items)
            self._conn.commit()
        # 入库后删除 PO 文件
        fp.unlink(missing_ok=True)
        return len(items)

    # ══════════════════════════════════════════════════════
    #  游戏版本
    # ══════════════════════════════════════════════════════

    def record_game_version(self, game_version: str, wows_type: str = "",
                            bin_folder: str = "", entity_count: int = 0) -> None:
        self._conn.execute(
            "INSERT INTO meta_game_versions "
            "(game_version,wows_type,bin_folder,entity_count) VALUES (?,?,?,?)",
            (game_version, wows_type, str(bin_folder), entity_count))
        self._conn.commit()

    def get_latest_game_version(self) -> Optional[str]:
        try:
            r = self._conn.execute(
                "SELECT game_version FROM meta_game_versions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return r["game_version"] if r else None
        except sqlite3.OperationalError:
            return None

    def get_game_versions(self, limit: int = 10) -> list[dict]:
        try:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM meta_game_versions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]
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
        for t in ["entity_registry", "entity_dynamic_attributes",
                   "ship_sub_depth_states", "rel_ship_weapon_ammo",
                   "gun_drum_details",
                   "name_mappings", "po_translations", "enum_translations",
                   "meta_game_versions", "meta_schema_version"]:
            try:
                conn.execute(f"DELETE FROM {t}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

    # ── 加载版本追踪 ──────────────────────────────────────

    def _init_load_tracking(self) -> None:
        """创建加载版本追踪表（幂等）"""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta_load_seq (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                game_version TEXT DEFAULT '',
                wows_type TEXT DEFAULT '',
                bin_folder TEXT DEFAULT '',
                entity_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS entity_load_log (
                entity_id TEXT NOT NULL,
                load_seq INTEGER NOT NULL,
                PRIMARY KEY (entity_id, load_seq)
            );
            CREATE INDEX IF NOT EXISTS idx_load_log_seq ON entity_load_log(load_seq);
        """)

    def begin_load(self, game_version: str = '', wows_type: str = '',
                   bin_folder: str = '', entity_count: int = 0) -> int:
        """开始一个新的加载批次，返回 load_seq"""
        cur = self._conn.execute(
            "INSERT INTO meta_load_seq (game_version, wows_type, bin_folder, entity_count) "
            "VALUES (?,?,?,?)",
            (game_version, wows_type, bin_folder, entity_count))
        self._conn.commit()
        return cur.lastrowid

    def record_entity_load(self, entity_id: str, load_seq: int) -> None:
        """记录实体属于哪个加载批次（追加记录，保留历史）"""
        self._conn.execute(
            "INSERT OR IGNORE INTO entity_load_log (entity_id, load_seq) VALUES (?,?)",
            (entity_id, load_seq))

    def record_entities_load(self, entity_ids: list[str], load_seq: int) -> None:
        """批量记录实体批次归属（追加记录，保留历史）"""
        self._conn.executemany(
            "INSERT OR IGNORE INTO entity_load_log (entity_id, load_seq) VALUES (?,?)",
            [(eid, load_seq) for eid in entity_ids])
        self._conn.commit()

    def purge_old_loads(self, keep_count: int = 2) -> int:
        """只保留最近 keep_count 次加载的实体，删除更旧批次的数据。

        利用 entity_load_log 找到「最新出现批次已过期」的 entity_id，
        从 entity_registry 中删除（ON DELETE CASCADE 自动清理分析表）。
        """
        conn = self._conn
        # 找到最新的 keep_count 个批次号
        cur = conn.execute(
            "SELECT seq FROM meta_load_seq ORDER BY seq DESC LIMIT ?", (keep_count,))
        keep_seqs = [r[0] for r in cur.fetchall()]
        if not keep_seqs:
            return 0

        placeholders = ','.join('?' for _ in keep_seqs)
        # 删除「最新出现批次不在保留列表内」的实体
        # 例如保留 [5,4]，则实体最近一次出现是 batch 3 → 被删除
        cur = conn.execute(
            f"DELETE FROM entity_registry WHERE entity_id IN ("
            f"  SELECT entity_id FROM entity_load_log"
            f"  GROUP BY entity_id"
            f"  HAVING MAX(load_seq) NOT IN ({placeholders})"
            f")", keep_seqs)
        deleted = cur.rowcount

        if deleted > 0:
            # 同步清理过期日志
            conn.execute(
                f"DELETE FROM entity_load_log WHERE load_seq NOT IN ({placeholders})",
                keep_seqs)
            conn.execute(
                f"DELETE FROM meta_load_seq WHERE seq NOT IN ({placeholders})",
                keep_seqs)
            conn.commit()
        return deleted

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
        po_path = get_data_dir() / "global.po"
        if po_path.exists():
            self.import_po_translations(po_path)
        self.vacuum()
        return {"entities": processed, "mappings": sum(ms.values())}


# ── 全局单例 ──────────────────────────────────────────────
_db: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        _db = DatabaseManager()
        _db.initialize()
    return _db


def reset_db() -> None:
    global _db
    _db = None
    # 关闭所有数据库连接（跨线程）
    DatabaseManager.close_all_connections()
    # 清空 Presenter 缓存，防止旧连接被 GC 后新连接 id() 撞地址
    try:
        from presenters.registry import PresenterRegistry
        PresenterRegistry.clear_cache()
    except ImportError:
        pass
