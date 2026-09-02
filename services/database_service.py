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


DB_SCHEMA_VERSION = 47

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
    "skill_names.json": "skill_title",
    "skill_descriptions.json": "skill_desc",
    "torpedo_group_names.json": "torpedo_group",
    "signal_flag_names.json": "signal_flag",
}


class DatabaseManager:
    """SQLite 数据库管理器（线程安全，多版本架构）"""

    def __init__(self, db_path: str | Path | None = None,
                 wows_type: str = ""):
        self._wows_type = wows_type or ""
        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = get_data_dir() / self._db_name(wows_type)
        self._local = threading.local()
        #: 本次 initialize 是否因 schema 版本落后而整库重建（旧数据被清空）。
        #: 供启动/切换服务器时提示「需要重新加载数据」而非「数据库为空」。
        self._schema_rebuilt = False

    def _schema_subdir(self) -> str:
        """按服务器返回 SQL 架构子目录（lesta / wargaming）。"""
        wt = self._wows_type
        if not wt:
            try:
                from app.application import app as app_ctx
                wt = app_ctx.ctx.wows_type
            except Exception:  # noqa: BLE001
                wt = ""
        return "wargaming" if wt == "Wargaming" else "lesta"

    @staticmethod
    def _db_name(wows_type: str = "") -> str:
        """按服务器返回数据库文件名。

        Lesta（默认/空）→ ``game_data.db``（保持旧数据兼容，不迁移）；
        Wargaming → ``game_data_wg.db``（WG 数据独立分库，避免与 Lesta 串用）。
        """
        if wows_type == "Wargaming":
            return "game_data_wg.db"
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

    def _log_ddl_error(self, exc: Exception, table: str = "") -> None:
        """把 DDL/迁移失败写入日志总线（避免静默吞错）。"""
        try:
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 数据库迁移失败 {table}: {exc}")
        except Exception:  # noqa: BLE001
            pass

    def _add_column(self, table: str, col_name: str, col_type: str) -> None:
        """给表添加一列（幂等：列已存在视为成功），失败时记录到日志。

        调用方应先用 PRAGMA table_info 判断列是否缺失，再调用本方法；
        这里对「列已存在」的报错静默忽略，其余错误写入日志。
        """
        try:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
        except Exception as exc:  # noqa: BLE001
            if "duplicate column" in str(exc).lower():
                return
            self._log_ddl_error(exc, f"{table}.{col_name}")

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
        # schema 版本落后 → 整库重建（旧数据被清空），标记以便提示「需要重新加载数据」
        self._schema_rebuilt = False
        if 0 < current_ver < DB_SCHEMA_VERSION:
            self._drop_all_tables()
            self._schema_rebuilt = True

        # 从 QRC 读取 SQL 初始化脚本，若不可用则回退到文件系统
        # 架构按服务器分离：lesta/database_new.sql 与 wargaming/database_new.sql
        # （子目录缺失时回退顶层旧路径，兼容旧 QRC/文件系统）
        from PySide6.QtCore import QFile, QIODevice
        sub = self._schema_subdir()
        qf = QFile(f":/resources/database/{sub}/database_new.sql")
        if qf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
            sql_text = str(qf.readAll(), encoding="utf-8")
            qf.close()
            self._conn.executescript(sql_text)
        else:
            # 回退到文件系统（源码模式或 standalone 无 QRC 的备用路径）
            sql_path = get_bundled_dir() / "resources" / "database" / sub / "database_new.sql"
            if not sql_path.exists():
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
                    self._add_column("plane_basic_info", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_aa 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_aa)").fetchall()}
            for col_name, col_type in [("explosion_count", "REAL"), ("hit_chance", "REAL"), ("max_distance", "REAL"), ("min_distance", "REAL"), ("type", "TEXT")]:
                if col_name not in existing:
                    self._add_column("ship_module_aa", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_air_support 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_air_support)").fetchall()}
            for col_name, col_type in [("support_type", "TEXT"), ("min_time_to_attack", "REAL"), ("max_time_to_attack", "REAL"),
                                       ("ammo_list_json", "TEXT"), ("ammo_switch_coeff", "REAL"),
                                       ("fly_away_time", "REAL"), ("time_from_heaven", "REAL"),
                                       ("auto_use", "INTEGER"), ("available_buoyancy_states_json", "TEXT")]:
                if col_name not in existing:
                    self._add_column("ship_module_air_support", col_name, col_type)
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
                    self._add_column("ship_module_depth_charge", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_engine 引擎加力（弹射起步）/全功率加速时间列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_engine)").fetchall()}
            for col_name, col_type in [("forward_forsage_max_speed", "REAL"),
                                       ("backward_forsage_max_speed", "REAL"),
                                       ("forward_engine_up_time", "REAL"),
                                       ("backward_engine_up_time", "REAL")]:
                if col_name not in existing:
                    self._add_column("ship_module_engine", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 plane_basic_info 引擎加力回复列（用于计算加力冷却时间） ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(plane_basic_info)").fetchall()}
            for col_name, col_type in [("forsage_regeneration", "REAL"), ("forsage_regeneration_delay", "REAL")]:
                if col_name not in existing:
                    self._add_column("plane_basic_info", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_hulls 排水量列（用于推重比计算） ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_hulls)").fetchall()}
            if "tonnage" not in existing:
                self._add_column("ship_module_hulls", "tonnage", "REAL")
                self._conn.commit()
        except Exception:
            pass

        # ── 迁移：创建 entity_snapshots 实体快照表（QRC 内嵌 SQL 过期时的兜底） ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS entity_snapshots (
                version_code TEXT NOT NULL REFERENCES data_version_registry(version_code) ON DELETE CASCADE,
                entity_id    TEXT NOT NULL,
                entity_type  TEXT NOT NULL,
                nation       TEXT,
                data_json    TEXT NOT NULL,
                json_len     INTEGER DEFAULT 0,
                PRIMARY KEY (version_code, entity_id)
            )""")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snap_type ON entity_snapshots(version_code, entity_type)")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：创建 consumable_buff 消耗品增益表（QRC 内嵌 SQL 过期时的兜底） ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS consumable_buff (
                version_code TEXT NOT NULL,
                buff_id TEXT NOT NULL,
                buff_level INTEGER NOT NULL,
                ally_health_regen_percent REAL,
                buff_json TEXT DEFAULT '{}',
                PRIMARY KEY (version_code, buff_id, buff_level),
                FOREIGN KEY (version_code, buff_id) REFERENCES entity_registry(version_code, entity_id) ON DELETE CASCADE
            )""")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：创建 ship_models 可载入舰船列表（3D 查看器用，数据入库时一并写入） ──
        try:
            # 用 IF NOT EXISTS（勿 DROP）：initialize 幂等，DROP 会导致每次启动清空列表
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ship_models (
                version_code TEXT NOT NULL,
                ship_id      TEXT NOT NULL,
                model_folder TEXT NOT NULL DEFAULT '',
                model_path   TEXT NOT NULL DEFAULT '',
                nation       TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (version_code, ship_id)
            )""")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ship_models ON ship_models(version_code)")
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

        # ── 迁移：创建 ship_module_atba_config 表（WG 副炮控制组 + 手动模式修饰符） ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ship_module_atba_config (
                version_code TEXT NOT NULL,
                ship_id TEXT NOT NULL,
                config_group TEXT NOT NULL,
                control_groups_json TEXT,
                manual_mode_modifiers_json TEXT,
                PRIMARY KEY (version_code, ship_id, config_group),
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

        # ── 迁移：补齐 projectile_torpedo_sub_guidance_ext 缺少的 params_json 列（WG 完整 SubmarineTorpedoParams） ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(projectile_torpedo_sub_guidance_ext)").fetchall()}
            if "params_json" not in existing:
                self._add_column("projectile_torpedo_sub_guidance_ext", "params_json", "TEXT")
                self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 projectile_torpedo_ext 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(projectile_torpedo_ext)").fetchall()}
            for col, typ in [("burn_prob", "REAL DEFAULT 0"), ("uw_critical", "REAL DEFAULT 0"),
                             ("distance_of_damage_json", "TEXT")]:
                if col not in existing:
                    self._add_column("projectile_torpedo_ext", col, typ)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 projectile_bomb_ext 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(projectile_bomb_ext)").fetchall()}
            if "max_skip_angle" not in existing:
                self._add_column("projectile_bomb_ext", "max_skip_angle", "REAL")
                self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_hulls 缺少的 size 列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_hulls)").fetchall()}
            for col, typ in [("length", "REAL"), ("width", "REAL"), ("height", "REAL")]:
                if col not in existing:
                    self._add_column("ship_module_hulls", col, typ)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_rage_mode 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_rage_mode)").fetchall()}
            if "rage_mode_name" not in existing:
                self._add_column("ship_rage_mode", "rage_mode_name", "TEXT DEFAULT ''")
                self._conn.commit()
            # buff_params_name 仅 lesta 库需要（WG 战斗指令暂不下拉 buff）
            if self._wows_type != "Wargaming" and "buff_params_name" not in existing:
                self._add_column("ship_rage_mode", "buff_params_name", "TEXT DEFAULT ''")
                self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 crew_unique_skills 缺少的 icon_path 列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(crew_unique_skills)").fetchall()}
            if "icon_path" not in existing:
                self._add_column("crew_unique_skills", "icon_path", "TEXT DEFAULT ''")
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

        # ── 迁移：补齐 ship_module_torpedoes 缺少的 rotation_speed 列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_torpedoes)").fetchall()}
            if "rotation_speed" not in existing:
                self._add_column("ship_module_torpedoes", "rotation_speed", "REAL")
                self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_torpedoes 缺少的 torpedo_angles_narrow/wide/use_one_shot 列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_torpedoes)").fetchall()}
            for col_name, col_type in [("torpedo_angles_narrow", "REAL DEFAULT 0"),
                                        ("torpedo_angles_wide", "REAL DEFAULT 0"),
                                        ("use_one_shot", "INTEGER DEFAULT 0")]:
                if col_name not in existing:
                    self._add_column("ship_module_torpedoes", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_torpedoes 缺少的 top_module_key/launcher_name 列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_torpedoes)").fetchall()}
            for col_name, col_type in [("top_module_key", "TEXT DEFAULT ''"),
                                        ("launcher_name", "TEXT DEFAULT ''")]:
                if col_name not in existing:
                    self._add_column("ship_module_torpedoes", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：为各武器表补齐 launcher_name 列 ──
        _WEAPON_TABLES = ["ship_module_artillery", "ship_module_atba",
                          "ship_module_secondary_artillery", "ship_module_depth_charge"]
        for _tbl in _WEAPON_TABLES:
            try:
                _existing = {r[1] for r in self._conn.execute(f"PRAGMA table_info({_tbl})").fetchall()}
                if "launcher_name" not in _existing:
                    self._add_column(_tbl, "launcher_name", "TEXT DEFAULT ''")
                self._conn.commit()
            except Exception as _e:
                self._log_ddl_error(_e, _tbl)

        # ── 迁移：创建 ship_module_torpedo_config 表 ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ship_module_torpedo_config (
                version_code TEXT NOT NULL,
                ship_id TEXT NOT NULL,
                config_group TEXT NOT NULL,
                use_groups INTEGER DEFAULT 0,
                groups_json TEXT,
                groups_names_json TEXT,
                groups_counts_json TEXT,
                loaders_json TEXT,
                num_torps_in_salvo INTEGER DEFAULT 0,
                use_one_shot INTEGER DEFAULT 0,
                one_shot_wait_time REAL DEFAULT 0,
                module_reload_time REAL DEFAULT 0,
                PRIMARY KEY (version_code, ship_id, config_group),
                FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
            )""")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 ship_module_torpedo_config 缺少的列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(ship_module_torpedo_config)").fetchall()}
            for col_name, col_type in [("groups_counts_json", "TEXT"), ("loaders_json", "TEXT"),
                                        ("ammo_switch_coeff", "REAL DEFAULT 0")]:
                if col_name not in existing:
                    self._add_column("ship_module_torpedo_config", col_name, col_type)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：创建 ship_module_pinger 潜艇声呐表 ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ship_module_pinger (
                version_code TEXT NOT NULL,
                ship_id TEXT NOT NULL,
                config_group TEXT NOT NULL,
                module_key TEXT NOT NULL,
                count INTEGER,
                wave_reload_time REAL,
                wave_distance REAL,
                sector_lifetime REAL,
                max_wave_hits INTEGER,
                exposing_waves INTEGER,
                wave_hit_life REAL,
                wave_speed REAL,
                hp REAL,
                PRIMARY KEY (version_code, ship_id, config_group, module_key),
                FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
            )""")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：补齐 plane_basic_info 缺少的 field_minefield 列 ──
        try:
            existing = {r[1] for r in self._conn.execute("PRAGMA table_info(plane_basic_info)").fetchall()}
            for col, typ in [("field_minefield", "TEXT DEFAULT ''"),
                             ("jato_duration", "REAL"),
                             ("jato_speed_mult", "REAL")]:
                if col not in existing:
                    self._add_column("plane_basic_info", col, typ)
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：创建 ship_module_torpedo_ext 鱼雷弹鼓扩增表 ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ship_module_torpedo_ext (
                version_code TEXT NOT NULL,
                ship_id TEXT NOT NULL,
                config_group TEXT NOT NULL,
                module_key TEXT NOT NULL,
                is_drum_chargeable INTEGER DEFAULT 0,
                drum_charge_time REAL DEFAULT 0,
                drum_max_charges INTEGER DEFAULT 0,
                drum_full_reload_time REAL DEFAULT 0,
                PRIMARY KEY (version_code, ship_id, config_group, module_key),
                FOREIGN KEY (version_code, ship_id, config_group, module_key) REFERENCES ship_module_torpedoes(version_code, ship_id, config_group, module_key) ON DELETE CASCADE
            )""")
            self._conn.commit()
        except Exception:
            pass

        # ── 迁移：创建 ship_turret_arcs 炮塔射界表（旧库补建） ──
        try:
            self._conn.execute("""CREATE TABLE IF NOT EXISTS ship_turret_arcs (
                version_code TEXT NOT NULL,
                ship_id TEXT NOT NULL,
                config_group TEXT NOT NULL,
                slot_type TEXT NOT NULL,
                hp_key TEXT NOT NULL,
                gun_index TEXT,
                gun_name TEXT,
                module_key TEXT,
                horiz_sector_json TEXT,
                vert_sector_json TEXT,
                dead_zone_json TEXT,
                pitch_dead_zones_json TEXT,
                position_json TEXT,
                rotation_speed_h REAL,
                rotation_speed_v REAL,
                num_barrels INTEGER,
                barrel_diameter REAL,
                shot_delay REAL,
                PRIMARY KEY (version_code, ship_id, config_group, slot_type, hp_key),
                FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
            )""")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_turret_arcs_ship "
                "ON ship_turret_arcs(version_code, ship_id)")
            self._conn.commit()
        except Exception:
            pass

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
        # 兜底：炮塔射界表（正式环境由 database_new.sql 创建）
        c.execute("""CREATE TABLE IF NOT EXISTS ship_turret_arcs (
            version_code TEXT NOT NULL,
            ship_id TEXT NOT NULL,
            config_group TEXT NOT NULL,
            slot_type TEXT NOT NULL,
            hp_key TEXT NOT NULL,
            gun_index TEXT,
            gun_name TEXT,
            module_key TEXT,
            horiz_sector_json TEXT,
            vert_sector_json TEXT,
            dead_zone_json TEXT,
            pitch_dead_zones_json TEXT,
            position_json TEXT,
            rotation_speed_h REAL,
            rotation_speed_v REAL,
            num_barrels INTEGER,
            barrel_diameter REAL,
            shot_delay REAL,
            PRIMARY KEY (version_code, ship_id, config_group, slot_type, hp_key),
            FOREIGN KEY (version_code, ship_id) REFERENCES ship_basic_info(version_code, ship_id) ON DELETE CASCADE
        )""")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_turret_arcs_ship "
            "ON ship_turret_arcs(version_code, ship_id)")

    def get_current_version(self) -> int:
        try:
            cur = self._conn.execute(
                "SELECT version FROM meta_schema_version ORDER BY version DESC LIMIT 1")
            row = cur.fetchone()
            return row["version"] if row else 0
        except sqlite3.OperationalError:
            return 0

    def schema_rebuilt(self) -> bool:
        """本次 initialize 是否因 schema 版本落后而整库重建（旧数据被清空）。

        供启动/切换服务器时区分「需要重新加载数据」与「数据库为空」。
        """
        return self._schema_rebuilt

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

    def _resolve_vc(self, version_code: str) -> str:
        """空 version_code → 取最新版本；仍无则返回空串（调用方据此早退）。

        统一"空 vc → 取最新版本"回退样板（原在 9+ 个查询方法中逐字重复）。
        """
        if version_code:
            return version_code
        return self.get_latest_version_code() or ""

    def _resolve_vc(self, version_code: str = "") -> str:
        """解析 version_code：为空时取最新版本；无可用版本返回 ''。

        统一各查询方法重复的"空 vc → 取最新版本"回退样板（N15）。
        调用方在拿到 '' 时按各自语义返回默认值（[] / None / False / 0）。
        """
        if not version_code:
            version_code = self.get_latest_version_code() or ""
        return version_code

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

    def save_entity_snapshots(self, items: list[tuple[str, str, str, str]],
                              version_code: str) -> int:
        """批量写入实体快照到 entity_snapshots（版本级联删除）。

        items 每项为 (entity_id, entity_type, nation, data_json)。
        data_json 必须是规范化 JSON（sort_keys=True, ensure_ascii=False），
        相同数据保证相同文本，供跨版本字符串比较判"未变"。
        """
        rows = [(version_code, eid, etype, nation or "", json_str, len(json_str or ""))
                for eid, etype, nation, json_str in items]
        if not rows:
            return 0
        self._conn.executemany(
            "INSERT OR REPLACE INTO entity_snapshots "
            "(version_code, entity_id, entity_type, nation, data_json, json_len) "
            "VALUES (?,?,?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    # ── 可载入舰船列表（3D 查看器） ────────────────────────

    def save_ship_models(self, items: list[tuple[str, str, str, str]],
                         version_code: str) -> int:
        """写入可载入舰船列表（3D 查看器用）。

        items 每项为 (ship_id, model_folder, model_path, nation)。
        在数据入库时一并调用，使 list_ships 无需再扫描 data/split。
        """
        self._conn.execute("DELETE FROM ship_models WHERE version_code=?", (version_code,))
        rows = [(version_code, sid, mf or "", mp or "", nat or "")
                for sid, mf, mp, nat in items]
        if rows:
            self._conn.executemany(
                "INSERT OR REPLACE INTO ship_models "
                "(version_code, ship_id, model_folder, model_path, nation) "
                "VALUES (?,?,?,?,?)", rows)
        self._conn.commit()
        return len(rows)

    def load_ship_models(self, version_code: str = "") -> list[dict]:
        """读取可载入舰船列表（最新版本，空则返回空列表）。"""
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return []
        try:
            cur = self._conn.execute(
                "SELECT ship_id, model_folder, model_path, nation "
                "FROM ship_models WHERE version_code=? ORDER BY ship_id",
                (version_code,))
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []

    def load_ship_snapshot(self, ship_id: str,
                           version_code: str = "") -> Optional[dict]:
        """读取指定舰船实体的规范化 JSON 快照（entity_snapshots 表）。

        DB-first：3D 查看器的装甲厚度 / HP 挂载引用在显示阶段只走数据库，
        不读 data/split JSON（快照在加载数据入库时写入）。缺失返回 None。
        """
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return None
        try:
            cur = self._conn.execute(
                "SELECT data_json FROM entity_snapshots "
                "WHERE version_code=? AND entity_id=? AND entity_type='ship'",
                (version_code, ship_id))
            row = cur.fetchone()
            if not row:
                return None
            return json.loads(row["data_json"])
        except (sqlite3.OperationalError, json.JSONDecodeError):
            return None

    # ── 查询 ───────────────────────────────────────────────

    def get_entity(self, category: str, key: str,
                   version_code: str = "") -> Optional[dict]:
        etype = self._entity_type(category)
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return None
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

    def get_turret_arcs(self, ship_id: str, version_code: str = "") -> list[dict]:
        """查询一艘舰船所有炮塔的射界数据（ship_turret_arcs 表）。

        每行含 slot_type(artillery/atba/torpedoes/...)、hp_key、gun_index、
        horiz_sector_json / vert_sector_json / dead_zone_json / pitch_dead_zones_json 等。
        """
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return []
        try:
            cur = self._conn.execute(
                "SELECT * FROM ship_turret_arcs "
                "WHERE version_code=? AND ship_id=? ORDER BY slot_type, hp_key",
                (version_code, ship_id))
            return [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []

    def has_turret_arcs(self, ship_id: str, version_code: str = "") -> bool:
        """射界表是否有该舰船数据（用于判断是否需要从快照回填）"""
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return False
        try:
            r = self._conn.execute(
                "SELECT 1 FROM ship_turret_arcs WHERE version_code=? AND ship_id=? LIMIT 1",
                (version_code, ship_id)).fetchone()
            return r is not None
        except sqlite3.OperationalError:
            return False

    def list_entities(self, category: str, keyword: str = "",
                      limit: int = 0, offset: int = 0,
                      version_code: str = "") -> list[dict]:
        etype = self._entity_type(category)
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return []
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
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return 0
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
        version_code = self._resolve_vc(version_code)
        if not version_code:
            return []
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
        version_code = self._resolve_vc(version_code)
        conn = self._conn
        cats, total = {}, 0
        try:
            # 单条 GROUP BY 聚合，替代逐类型 COUNT(*)（N+1）
            if version_code:
                cur = conn.execute(
                    "SELECT entity_type, COUNT(*) FROM entity_registry "
                    "WHERE version_code=? GROUP BY entity_type", (version_code,))
            else:
                cur = conn.execute(
                    "SELECT entity_type, COUNT(*) FROM entity_registry GROUP BY entity_type")
            counts = {r[0]: r[1] for r in cur.fetchall()}
            for et in ENTITY_TYPES:
                cnt = counts.get(et, 0)
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
                items = [(cat, k, _unescape_po_str(v))
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
        # 合并多行 msgstr 续行格式（共用 utils.po_utils）
        from utils.po_utils import join_po_multiline
        text = join_po_multiline(text)
        items = []
        blocks = re.split(r'\n(?=msgid)', text)
        _Q = re.compile(r'^msgstr\s+"((?:[^"\\]|\\.)*)"\s*$', re.MULTILINE)
        for block in blocks:
            m = re.search(r'^msgid\s+"(.+)"\s*$', block, re.MULTILINE)
            s = _Q.search(block)
            if m and s and m.group(1) and s.group(1):
                items.append((m.group(1), _unescape_po_str(s.group(1)), ""))
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


def _unescape_po_str(s: str) -> str:
    """解析 PO/JSON 中未转义的 C 风格转义序列（\\n → 换行、\\t → 制表等）。
    未知转义保留反斜杠原样，避免破坏 Windows 路径等文本。"""
    if "\\" not in s:
        return s
    out = []
    i, n = 0, len(s)
    mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            nxt = s[i + 1]
            out.append(mapping.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


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


# ── Schema 版本一致性检查（纯只读，不触发 initialize/重建）─────────────────

def _read_schema_version(db_path: Path) -> int:
    """只读方式读取数据库文件当前记录的 schema 版本（meta_schema_version 最大值）。

    文件不存在 / 打开失败 / 无该表 → 返回 0（视为全新库，不参与「落后」判定）。
    仅以只读方式打开，绝不触发 SQLite 创建数据库文件或任何重写。
    """
    if not db_path.exists():
        return 0
    try:
        # mode=ro 只读打开（WAL 库也能读到已提交数据），不落盘、不建库
        conn = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "SELECT version FROM meta_schema_version "
                "ORDER BY version DESC LIMIT 1").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return 0


def check_schema_mismatches(wows_type: str = "") -> list[dict]:
    """纯只读检查指定服务器对应的两个数据库文件 schema 版本是否与当前程序不一致。

    对应关系（与 DatabaseManager._db_name / AssetsCacheService._db_name 一致）：
      Lesta      → game_data.db + assets_data.db
      Wargaming  → game_data_wg.db + assets_data_wg.db

    「不一致」判定：库内 meta_schema_version 记录 found > 0 且 found != 当前代码预期版本。
    （found == 0 表示全新/未建库，不算不一致，不提示。）

    返回（仅含不一致的库，空列表表示全部匹配）：
      [{"kind": "game"|"assets", "db": 文件名, "found": 库内版本, "expected": 当前版本}, ...]
    """
    from services.assets_cache_service import (
        AssetsCacheService, ASSETS_SCHEMA_VERSION,
    )
    if not wows_type:
        from app.application import app as app_ctx
        wows_type = app_ctx.ctx.wows_type

    data_dir = get_data_dir()
    checks = [
        ("game", DatabaseManager._db_name(wows_type), DB_SCHEMA_VERSION),
        ("assets", AssetsCacheService._db_name(wows_type), ASSETS_SCHEMA_VERSION),
    ]
    mismatches: list[dict] = []
    for kind, name, expected in checks:
        found = _read_schema_version(data_dir / name)
        if found > 0 and found != expected:
            mismatches.append({
                "kind": kind,
                "db": name,
                "found": found,
                "expected": expected,
            })
    return mismatches
    DatabaseManager.close_all_connections()
    try:
        from presenters.registry import PresenterRegistry
        PresenterRegistry.clear_cache()
    except ImportError:
        pass
