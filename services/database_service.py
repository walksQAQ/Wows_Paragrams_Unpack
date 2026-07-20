"""
数据库服务 —— 新架构 (Multi-Version Schema)。

支持多版本数据共存 + 级联版本管理。
所有数据表均以 version_code 为第一主键列，与 data_version_registry 死锁。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from utils.path_utils import get_data_dir, get_bundled_dir


DB_SCHEMA_VERSION = 14

ENTITY_TYPES: list[str] = [
    "ship", "gun", "projectile", "plane", "consumable", "modernization", "crew",
]

NAME_MAPPING_FILES: dict[str, str] = {
    "ship_names.json": "ship",
    "ammo_names.json": "ammo",
    "guns_names.json": "gun",
    "consumable_names.json": "consumable",
    "modernization_names.json": "modernization",
    "plane_names.json": "plane",
    "rage_mode_names.json": "rage_mode",
    "module_upgrade_names.json": "module_upgrade",
}


class DatabaseManager:
    """SQLite 数据库管理器（线程安全，多版本架构）"""

    def __init__(self, db_path: str | Path | None = None,
                 wows_type: str = ""):
        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = get_data_dir() / self._db_name(wows_type)
        self._local = threading.local()

    @staticmethod
    def _db_name(wows_type: str = "") -> str:
        return "game_data.db"

    _all_connections: set[sqlite3.Connection] = set()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = self._create_connection()
        else:
            try:
                self._local.conn.execute("SELECT 1")
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                self._local.conn = self._create_connection()
        return self._local.conn

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
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
        for conn in list(cls._all_connections):
            try:
                conn.close()
            except Exception:
                pass
        cls._all_connections.clear()

    # ── Schema ─────────────────────────────────────────────

    def _drop_all_tables(self) -> None:
        conn = self._conn
        conn.execute("PRAGMA foreign_keys=OFF")
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (tname,) in tables:
            try:
                conn.execute(f'DROP TABLE IF EXISTS "{tname}"')
            except sqlite3.OperationalError:
                pass
        views = conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        for (vname,) in views:
            try:
                conn.execute(f'DROP VIEW IF EXISTS "{vname}"')
            except sqlite3.OperationalError:
                pass
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()

    def initialize(self) -> None:
        """创建所有表（使用 database_new.sql）"""
        current_ver = self.get_current_version()
        if 0 < current_ver < DB_SCHEMA_VERSION:
            self._drop_all_tables()

        sql_path = get_bundled_dir() / "resources" / "database" / "database_new.sql"
        if sql_path.exists():
            sql_text = sql_path.read_text(encoding="utf-8")
            self._conn.executescript(sql_text)
        else:
            self._init_core_tables()
        self._conn.commit()

        if self.get_current_version() < DB_SCHEMA_VERSION:
            self._record_version(DB_SCHEMA_VERSION)

        # ── 迁移：补齐 plane_basic_info 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(plane_basic_info)").fetchall()}
            expected = [
                ("outer_salvo_size_x", "REAL"), ("outer_salvo_size_y", "REAL"),
                ("inner_salvo_size_x", "REAL"), ("inner_salvo_size_y", "REAL"),
                ("max_spread_x", "REAL"), ("max_spread_y", "REAL"),
                ("min_spread_x", "REAL"), ("min_spread_y", "REAL"),
                ("inner_bombs_percentage", "REAL"),
                ("post_attack_invulnerability_duration", "REAL"),
                ("ability_slot_0", "TEXT"), ("ability_slot_1", "TEXT"),
                ("ability_slot_2", "TEXT"), ("ability_slot_3", "TEXT"),
                ("ability_slot_4", "TEXT"),
                ("plane_level", "INTEGER"),
                ("max_spread", "REAL"), ("min_spread", "REAL"),
                ("visibility_factor", "REAL"),
                ("skip_height", "REAL"), ("aiming_height", "REAL"),
            ]
            for col_name, col_type in expected:
                if col_name not in existing:
                    try:
                        self._conn.execute(f"ALTER TABLE plane_basic_info ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_aa 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_aa)").fetchall()}
            for col_name, col_type in [("explosion_count", "REAL"), ("hit_chance", "REAL"), ("max_distance", "REAL"), ("min_distance", "REAL"), ("type", "TEXT")]:
                if col_name not in existing:
                    try:
                        self._conn.execute(f"ALTER TABLE ship_module_aa ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_air_support 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_air_support)").fetchall()}
            for col_name, col_type in [("support_type", "TEXT")]:
                if col_name not in existing:
                    try:
                        self._conn.execute(f"ALTER TABLE ship_module_air_support ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_depth_charge 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_depth_charge)").fetchall()}
            for col_name, col_type in [("reload_time", "REAL"), ("shot_delay", "REAL"),
                                       ("max_packs", "INTEGER"), ("num_shots", "INTEGER"),
                                       ("num_bombs", "INTEGER"), ("projectile_id", "TEXT"),
                                       ("damage", "REAL"), ("dc_speed", "REAL"),
                                       ("dc_timer", "REAL"), ("dc_max_depth", "REAL"),
                                       ("depth_splash_size", "REAL")]:
                if col_name not in existing:
                    try:
                        self._conn.execute(f"ALTER TABLE ship_module_depth_charge ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：创建 ship_module_secondary_artillery 表 ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ship_module_secondary_artillery (
                version_code TEXT NOT NULL,
                ship_id TEXT NOT NULL,
                config_group TEXT NOT NULL,
                module_key TEXT NOT NULL,
                count INTEGER,
                num_barrels INTEGER,
                reload_time REAL,
                max_range REAL,
                sigma REAL,
                rotation_speed_h REAL,
                rotation_speed_v REAL,
                ideal_radius REAL,
                min_radius REAL,
                ideal_distance REAL,
                radius_zero REAL,
                radius_delim REAL,
                radius_max REAL,
                delim REAL,
                caliber REAL,
                PRIMARY KEY (version_code, ship_id, config_group, module_key),
                FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
            )""")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：清理废弃的 mod_concealment_config 表 ──
        try:
            self._conn.execute("DROP TABLE IF EXISTS mod_concealment_config")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 projectile_torpedo_ext 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(projectile_torpedo_ext)").fetchall()}
            for col, typ in [("burn_prob", "REAL DEFAULT 0"), ("uw_critical", "REAL DEFAULT 0")]:
                if col not in existing:
                    self._conn.execute(f"ALTER TABLE projectile_torpedo_ext ADD COLUMN {col} {typ}")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 projectile_bomb_ext 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(projectile_bomb_ext)").fetchall()}
            if "max_skip_angle" not in existing:
                self._conn.execute("ALTER TABLE projectile_bomb_ext ADD COLUMN max_skip_angle REAL")
                self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_rage_mode 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_rage_mode)").fetchall()}
            if "rage_mode_name" not in existing:
                self._conn.execute("ALTER TABLE ship_rage_mode ADD COLUMN rage_mode_name TEXT DEFAULT ''")
                self._conn.commit()
        except Exception:
            pass

        # ── 导入静态枚举翻译 ──
        try:
            cnt = self._conn.execute("SELECT COUNT(*) FROM enum_translations").fetchone()[0]
            if cnt == 0:
                self.import_enum_translations()
        except Exception:
            self.import_enum_translations()

    def _init_core_tables(self) -> None:
        """内联兜底（正式环境走 database_new.sql）"""
        c = self._conn
        c.execute("""CREATE TABLE IF NOT EXISTS data_version_registry (
            version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_code TEXT NOT NULL UNIQUE,
            wows_type TEXT DEFAULT '', bin_folder TEXT DEFAULT '',
            entity_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')))""")
        c.execute("""CREATE TABLE IF NOT EXISTS entity_registry (
            version_code TEXT NOT NULL REFERENCES data_version_registry(version_code) ON DELETE CASCADE,
            entity_id TEXT NOT NULL, entity_type TEXT NOT NULL, nation TEXT,
            PRIMARY KEY (version_code, entity_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS name_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, key_name TEXT NOT NULL,
            lang_zh TEXT NOT NULL, UNIQUE(category, key_name))""")
        c.execute("""CREATE TABLE IF NOT EXISTS meta_schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now','localtime')))""")

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

    # ── 多版本管理 ─────────────────────────────────────────

    def begin_version(self, game_version: str, wows_type: str = "",
                      bin_folder: str = "") -> str:
        """创建新版本记录，返回 version_code（含小版本号）。

        如果相同 version_code 已存在（如重复加载同版本数据），
        使用 INSERT OR IGNORE 静默跳过，然后返回已有版本号。
        """
        version_code = f"{game_version}_{bin_folder}" if bin_folder else game_version
        self._conn.execute(
            "INSERT OR IGNORE INTO data_version_registry "
            "(version_code, wows_type, bin_folder) VALUES (?,?,?)",
            (version_code, wows_type, bin_folder))
        self._conn.commit()
        return version_code

    def purge_old_versions(self, keep_count: int = 2) -> int:
        """只保留最近 keep_count 个版本，从最旧的开始级联删除。"""
        cur = self._conn.execute(
            "SELECT version_code FROM data_version_registry ORDER BY version_id DESC LIMIT ?",
            (keep_count,))
        keep_codes = [r[0] for r in cur.fetchall()]
        if not keep_codes:
            return 0
        placeholders = ','.join('?' for _ in keep_codes)
        cur = self._conn.execute(
            f"DELETE FROM data_version_registry WHERE version_code NOT IN ({placeholders})",
            keep_codes)
        self._conn.commit()
        return cur.rowcount

    def get_latest_version_code(self) -> str | None:
        try:
            cur = self._conn.execute(
                "SELECT version_code FROM data_version_registry ORDER BY version_id DESC LIMIT 1")
            row = cur.fetchone()
            return row["version_code"] if row else None
        except sqlite3.OperationalError:
            return None

    def list_versions(self) -> list[dict]:
        try:
            cur = self._conn.execute(
                "SELECT * FROM data_version_registry ORDER BY version_id DESC")
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []

    # ── 实体注册 ───────────────────────────────────────────

    @staticmethod
    def _entity_type(category: str) -> str:
        mapping = {
            "Ship": "ship", "Gun": "gun", "Projectile": "projectile",
            "Aircraft": "plane", "Ability": "consumable",
            "Modernization": "modernization", "Crew": "crew",
        }
        return mapping.get(category, category.lower())

    def insert_entities_batch(self, items: list[tuple[str, str, dict]],
                              version_code: str) -> None:
        """批量注册实体到 entity_registry（含 version_code），并更新版本计数"""
        rows = []
        for category, key, data in items:
            etype = self._entity_type(category)
            ti = data.get("typeinfo", {}) or {}
            nation = str(ti.get("nation", ""))
            rows.append((version_code, key, etype, nation))
        self._conn.executemany(
            "INSERT OR IGNORE INTO entity_registry "
            "(version_code, entity_id, entity_type, nation) VALUES (?,?,?,?)", rows)
        # 更新版本记录中的实体计数
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM entity_registry WHERE version_code=?", (version_code,))
        count = cur.fetchone()[0]
        self._conn.execute(
            "UPDATE data_version_registry SET entity_count=? WHERE version_code=?",
            (count, version_code))
        self._conn.commit()

    # ── 查询 ───────────────────────────────────────────────

    def get_entity(self, category: str, key: str,
                   version_code: str = "") -> Optional[dict]:
        etype = self._entity_type(category)
        if not version_code:
            vc = self.get_latest_version_code()
            if not vc:
                return None
            version_code = vc
        try:
            cur = self._conn.execute(
                "SELECT * FROM entity_registry WHERE version_code=? AND entity_id=? AND entity_type=?",
                (version_code, key, etype))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)
        except sqlite3.OperationalError:
            return None

    def list_entities(self, category: str, keyword: str = "",
                      limit: int = 0, offset: int = 0,
                      version_code: str = "") -> list[dict]:
        etype = self._entity_type(category)
        if not version_code:
            vc = self.get_latest_version_code()
            if not vc:
                return []
            version_code = vc
        conn = self._conn
        if keyword:
            p = f"%{keyword}%"
            sql = ("SELECT entity_id AS id, entity_type AS category, entity_id AS name, "
                   "nation FROM entity_registry WHERE version_code=? AND entity_type=? AND entity_id LIKE ? "
                   "ORDER BY entity_id")
            params = [version_code, etype, p]
        else:
            sql = ("SELECT entity_id AS id, entity_type AS category, entity_id AS name, "
                   "nation FROM entity_registry WHERE version_code=? AND entity_type=? "
                   "ORDER BY entity_id")
            params = [version_code, etype]
        if limit > 0:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            return []

    def count_entities(self, category: str, keyword: str = "",
                       version_code: str = "") -> int:
        etype = self._entity_type(category)
        if not version_code:
            vc = self.get_latest_version_code()
            if not vc:
                return 0
            version_code = vc
        conn = self._conn
        if keyword:
            p = f"%{keyword}%"
            cur = conn.execute(
                "SELECT COUNT(*) FROM entity_registry WHERE version_code=? AND entity_type=? AND entity_id LIKE ?",
                (version_code, etype, p))
        else:
            cur = conn.execute(
                "SELECT COUNT(*) FROM entity_registry WHERE version_code=? AND entity_type=?",
                (version_code, etype))
        return cur.fetchone()[0]

    def get_categories(self, version_code: str = "") -> list[str]:
        if not version_code:
            vc = self.get_latest_version_code()
            if not vc:
                return []
            version_code = vc
        rev = {"ship": "Ship", "gun": "Gun", "projectile": "Projectile",
               "plane": "Aircraft", "consumable": "Ability",
               "modernization": "Modernization", "crew": "Crew"}
        try:
            types = [r["entity_type"] for r in self._conn.execute(
                "SELECT DISTINCT entity_type FROM entity_registry WHERE version_code=? ORDER BY entity_type",
                (version_code,)).fetchall()]
            return [rev.get(t, t.capitalize()) for t in types]
        except sqlite3.OperationalError:
            return []

    def get_stats(self, version_code: str = "") -> dict:
        if not version_code:
            vc = self.get_latest_version_code()
            version_code = vc or ""
        conn = self._conn
        cats, total = {}, 0
        try:
            for et in ENTITY_TYPES:
                if version_code:
                    c = conn.execute(
                        "SELECT COUNT(*) FROM entity_registry WHERE version_code=? AND entity_type=?",
                        (version_code, et)).fetchone()
                else:
                    c = conn.execute(
                        "SELECT COUNT(*) FROM entity_registry WHERE entity_type=?", (et,)).fetchone()
                cnt = c[0] or 0
                cats[et] = cnt; total += cnt
        except sqlite3.OperationalError:
            pass
        try:
            mc = conn.execute("SELECT COUNT(*) FROM name_mappings").fetchone()[0]
        except sqlite3.OperationalError:
            mc = 0
        return {"total_entities": total, "db_file_size_mb": self.db_size_mb,
                "categories": cats, "name_mappings": mc}

    # ── 本地化 ─────────────────────────────────────────────

    def get_all_name_mappings(self, category: str = "") -> dict[str, str]:
        try:
            if category:
                cur = self._conn.execute(
                    "SELECT key_name, lang_zh FROM name_mappings WHERE category=?", (category,))
            else:
                cur = self._conn.execute("SELECT key_name, lang_zh FROM name_mappings")
            return {r["key_name"]: r["lang_zh"] for r in cur.fetchall()}
        except sqlite3.OperationalError:
            return {}

    def import_enum_translations(self) -> int:
        """从 models.name_mapping.Mapping 静态字典写入 enum_translations 表"""
        from models.name_mapping import Mapping as NM
        enum_sources: list[tuple[str, dict]] = [
            ("nation", NM.NATION_MAP),
            ("ship_class", NM.SHIP_CLASS_MAP),
            ("ship_group", NM.SHIP_GROUP_MAP),
            ("weapon_species", NM.WEAPON_SPECIES_MAP),
            ("aircraft_class", NM.AIRCRAFT_CLASS_MAP),
            ("ammo_type", NM.AMMO_TYPE_MAP),
            ("projectile_type", NM.PROJECTILE_TYPE_MAP),
            ("buoyancy_state", NM.BUOYANCY_MAP),
        ]
        total = 0
        for enum_type, mapping in enum_sources:
            items = [(enum_type, k, v) for k, v in mapping.items()]
            if items:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO enum_translations (enum_type, enum_key, lang_zh) VALUES (?,?,?)",
                    items)
                total += len(items)
        if total:
            self._conn.commit()
        return total

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
                        "INSERT OR REPLACE INTO name_mappings (category, key_name, lang_zh) VALUES (?,?,?)", items)
                    self._conn.commit()
                    stats[fn] = len(items)
                fp.unlink(missing_ok=True)
            except Exception:
                continue
        return stats

    def import_po_translations(self, po_path: str | Path) -> int:
        fp = Path(po_path)
        if not fp.exists():
            return 0
        text = fp.read_text(encoding="utf-8")
        fp.unlink(missing_ok=True)
        items = []
        blocks = re.split(r'\n(?=msgid)', text)
        for block in blocks:
            m = re.search(r'^msgid\s+"(.+)"\s*$', block, re.MULTILINE)
            s = re.search(r'^msgstr\s+"(.+)"\s*$', block, re.MULTILINE)
            if m and s and m.group(1) and s.group(1):
                items.append((m.group(1), s.group(1), ""))
        if items:
            try:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO po_translations (msgid, msgstr, context) VALUES (?,?,?)", items)
                self._conn.commit()
            except Exception:
                pass  # po_translations 表可能不存在于新 schema，静默忽略
        return len(items)

    # ── 数据库管理 ─────────────────────────────────────────

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
        conn.execute("PRAGMA foreign_keys=OFF")
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (tname,) in tables:
            try:
                conn.execute(f'DELETE FROM "{tname}"')
            except sqlite3.OperationalError:
                pass
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()


# ── 全局单例 ──────────────────────────────────────────────
_db: Optional[DatabaseManager] = None
_db_wows_type: str = ""


def get_db(wows_type: str = "") -> DatabaseManager:
    global _db, _db_wows_type
    if not wows_type:
        from app.application import app as app_ctx
        wows_type = app_ctx.ctx.wows_type
    if _db is None or _db_wows_type != wows_type:
        if _db is not None:
            _db.close()
        _db = DatabaseManager(wows_type=wows_type)
        _db.initialize()
        _db_wows_type = wows_type
    return _db


def reset_db() -> None:
    global _db, _db_wows_type
    _db = None
    _db_wows_type = ""
    DatabaseManager.close_all_connections()
    try:
        from presenters.registry import PresenterRegistry
        PresenterRegistry.clear_cache()
    except ImportError:
        pass
