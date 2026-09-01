"""
assets.bin 数据缓存服务 —— 把 3D 查看器需要的数据预提取到独立数据库。

assets.bin（约 217MB）每次启动 3D 查看器都要现场提取+解析，很重。使用
「加载数据」功能时，把骨架挂点、视觉渲染集、材质贴图映射一次性写入
`assets_data.db`；后续 3D 查看器直接从数据库读取，不再现场解包 assets.bin。

架构：数据库优先 + 现场兜底（数据库缺数据时才现场解析 assets.bin）。

表结构（均以 bin_folder 绑定客户端版本，避免跨版本串用）：
- meta:            客户端版本元信息
- skeleton_mounts: 舰体骨架 HP_/MP_ 挂点矩阵（行主序渲染空间 16 float；
                   MP_ 为甲板设备挂点，v5 起纳入）
- render_sets:     visual 渲染集 shape → 材质/mfm（按 geometry 路径）
- mfm_textures:    材质 .mfm → diffuseMap 贴图基础名
- material_full:   材质完整信息（shader/全部贴图路径/INDEXED vec4 数组）
- meta_schema_version: schema 版本记录（同 database_new.sql 规则）
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import struct
import threading
from pathlib import Path

from utils.path_utils import get_data_dir

#: assets_data.db schema 版本（与 database_new.sql 的 DB_SCHEMA_VERSION 规则一致：
#: 库内 meta_schema_version 记录已应用版本，低于本值则 initialize 重建全表）
#: v2（2026-08-19）：skeleton_bones 增加解码列（pos/四元数/scale）
#: v4（2026-08-19）：渲染集按 count(+0x70) 精确解析（根治跨模型串用）；新增 shape_names 表
#:    （*.vertices 名哈希→名，LOD/crack 兜底用；显示时只读 DB，绝不现场读 assets.bin）
#: v5（2026-08-20）：skeleton_mounts 纳入 MP_ 甲板设备挂点（此前仅 HP_，
#:    导致 MP 节点挂载的缆桩/小艇/探照灯等甲板设备模型不显示）
#: v6（2026-08-20）：render_sets 增加 skinned 标志 + nodes 调色板（JSON 数组），
#:    供蒙皮网格按渲染集调色板施加 bind pose 混合（修复 PASA111 天线/索具
#:    180° 朝向错误；Korabli 渲染集项 +0x0C skinned / +0x0D nodes_count /
#:    +0x28 item-relative relptr → u32 名ID 数组）
#: v8：material_full 新增 material_hash 列（fx 变体标识，识别材质技术族用）
#: v10（2026-08-25）：render_sets 同一 (geom_path, shape) 可对应**多个节点**（如
#:    BIA400_Motor_Cutter_25ftShape 同时在 _0/_1 两舷节点），此前 PK 折叠导致只渲染
#:    一个；现改为汇总节点调色板（并集），供 geometry_service 按多节点实例化。
#: v11（2026-08-25）：多节点并集**仅对刚性（skinned=0）件**生效；蒙皮 shape 的
#:    nodes 是蒙皮骨骼调色板，并集会污染（如 TurretShape 的 4 骨骼）。保留首条。
ASSETS_SCHEMA_VERSION = 16


class AssetsCacheService:
    """assets.bin 数据缓存（独立数据库 assets_data.db，线程安全）。"""

    def __init__(self, db_path: str | Path | None = None, wows_type: str = ""):
        if not wows_type:
            try:
                from app.application import app as app_ctx
                wows_type = app_ctx.ctx.wows_type
            except Exception:  # noqa: BLE001
                wows_type = ""
        self._wows_type = wows_type or ""
        if db_path is None:
            db_path = get_data_dir() / self._db_name(wows_type)
        self._db_path = Path(db_path)
        self._local = threading.local()

    def _schema_subdir(self) -> str:
        """按服务器返回 SQL 架构子目录（lesta / wargaming）。"""
        return "wargaming" if self._wows_type == "Wargaming" else "lesta"

    @staticmethod
    def _db_name(wows_type: str = "") -> str:
        """按服务器返回 3D 缓存库文件名（Lesta→assets_data.db, WG→assets_data_wg.db）。"""
        if wows_type == "Wargaming":
            return "assets_data_wg.db"
        return "assets_data.db"

    def _is_wg(self) -> bool:
        """当前缓存库是否 WG 服（WG 的 assets.bin 用 10 类型表，布局与 Korabli 不同）。"""
        return self._wows_type == "Wargaming"

    # ── 连接 ────────────────────────────────────────────────

    @staticmethod
    def _merge_render_set_rows(rows: list[tuple]) -> list[tuple]:
        """汇总同一 (geom_path, shape) 的多条渲染集项：合并 node 调色板（并集）。

        原始资产里同一 shape 可绑定多个骨骼节点（左右舷实例化，如 motor_cutter），
        但 render_sets 表 PK 是 (bin_folder, geom_path, shape)，INSERT OR REPLACE 会把
        多条折叠成一条 → 丢失其余节点 → 只渲染一个实例。此处按 PK 合并，把节点并集
        写回单行 nodes 数组，供 geometry_service 逐节点实例化。

        输入 tuple: (bin_folder, geom_path, shape, material, mfm, damage, skinned, nodes_json)
        """
        merged: dict[tuple, list] = {}
        order: list[tuple] = []
        for r in rows:
            bin_folder, gp, shp, mat, mfm, damage, skinned, nodes_json = r
            key = (bin_folder, gp, shp)
            sk = int(skinned)
            if key not in merged:
                nodeset: set = set()
                if nodes_json:
                    try:
                        nodeset.update(json.loads(nodes_json))
                    except Exception:  # noqa: BLE001
                        pass
                # 首条：无论刚性/蒙皮都用它的节点调色板（蒙皮 shape 的调色板 = 蒙皮骨骼）
                merged[key] = [mat, mfm, damage, sk, nodeset]
                order.append(key)
            else:
                m = merged[key]
                m[3] = int(m[3]) or sk
                # ★ 仅**刚性（skinned=0）**项并入额外节点（多实例，如左右舷）；
                #   蒙皮项节点是蒙皮调色板，保留首条即可，并集会污染骨骼调色板。
                if sk == 0 and nodes_json:
                    try:
                        m[4].update(json.loads(nodes_json))
                    except Exception:  # noqa: BLE001
                        pass
        out: list[tuple] = []
        for key in order:
            bin_folder, gp, shp = key
            mat, mfm, damage, skinned, nodeset = merged[key]
            out.append((bin_folder, gp, shp, mat, mfm, damage,
                        int(skinned), json.dumps(sorted(nodeset))))
        return out

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path), check_same_thread=False, timeout=15)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA busy_timeout=8000")
            self._local.conn.row_factory = sqlite3.Row
        else:
            try:
                self._local.conn.execute("SELECT 1")
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                self._local.conn = sqlite3.connect(
                    str(self._db_path), check_same_thread=False, timeout=15)
                self._local.conn.execute("PRAGMA journal_mode=WAL")
                self._local.conn.execute("PRAGMA busy_timeout=8000")
                self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def initialize(self) -> None:
        """创建表（幂等；建表 SQL 从 assets_database.sql 读取，与 database_new.sql 同目录）。

        schema 版本规则同 database_service：库内 meta_schema_version 记录已应用版本，
        若低于 ASSETS_SCHEMA_VERSION 则 drop 全部表重建（避免旧结构残留），随后记录当前版本。
        """
        # 低版本 → 重建全表（同 database_new.sql 规则）
        current_ver = self.get_current_version()
        if 0 < current_ver < ASSETS_SCHEMA_VERSION:
            self._drop_all_tables()
        # 源码模式优先文件系统（assets_database.sql 是维护源，QRC 可能滞后于热改）；
        # 打包/无文件系统时回退 QRC（与 database_new.sql 的 QRC 打包一致）
        sql_text = None
        sub = self._schema_subdir()
        try:
            from utils.path_utils import get_bundled_dir
            sql_path = get_bundled_dir() / "resources" / "database" / sub / "assets_database.sql"
            if not sql_path.exists():
                sql_path = get_bundled_dir() / "resources" / "database" / "assets_database.sql"
            if sql_path.exists():
                sql_text = sql_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            sql_text = None
        if not sql_text:
            try:
                from PySide6.QtCore import QFile, QIODevice
                qf = QFile(f":/resources/database/{sub}/assets_database.sql")
                if qf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
                    sql_text = str(qf.readAll(), encoding="utf-8")
                    qf.close()
            except Exception:  # noqa: BLE001
                sql_text = None
        if sql_text:
            self._conn.executescript(sql_text)
        else:
            self._init_core_tables_inline()
        self._conn.commit()
        # 记录 schema 版本（同 database_new.sql 规则）
        if self.get_current_version() < ASSETS_SCHEMA_VERSION:
            self._record_version(ASSETS_SCHEMA_VERSION)
        # 迁移：mfm_textures 旧 schema（diffuse_base 列）→ 新（texture_path）
        try:
            cols = {r[1] for r in self._conn.execute(
                "PRAGMA table_info(mfm_textures)").fetchall()}
            if cols and "texture_path" not in cols:
                self._conn.execute("DROP TABLE IF EXISTS mfm_textures")
                self._conn.execute("""
                CREATE TABLE mfm_textures (
                    bin_folder TEXT NOT NULL,
                    mfm_path TEXT NOT NULL,
                    texture_path TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(bin_folder, mfm_path)
                );""")
                self._conn.commit()
        except Exception:  # noqa: BLE001
            pass

        # 迁移：exteriors 旧库补 icon_path 列（易用包图标列）
        try:
            cols = {r[1] for r in self._conn.execute(
                "PRAGMA table_info(exteriors)").fetchall()}
            if cols and "icon_path" not in cols:
                self._conn.execute("ALTER TABLE exteriors ADD COLUMN icon_path TEXT DEFAULT ''")
                self._conn.commit()
        except Exception:  # noqa: BLE001
            pass

        # 迁移：camouflages 旧库补 icon_path 列
        try:
            cols = {r[1] for r in self._conn.execute(
                "PRAGMA table_info(camouflages)").fetchall()}
            if cols and "icon_path" not in cols:
                self._conn.execute("ALTER TABLE camouflages ADD COLUMN icon_path TEXT DEFAULT ''")
                self._conn.commit()
        except Exception:  # noqa: BLE001
            pass

        # 迁移：exteriors / camouflages 补 display_name 列（涂装本地化名）
        for tbl in ("exteriors", "camouflages"):
            try:
                cols = {r[1] for r in self._conn.execute(
                    f"PRAGMA table_info({tbl})").fetchall()}
                if cols and "display_name" not in cols:
                    self._conn.execute(f"ALTER TABLE {tbl} ADD COLUMN display_name TEXT DEFAULT ''")
                    self._conn.commit()
            except Exception:  # noqa: BLE001
                pass

    def _init_core_tables_inline(self) -> None:
        """内嵌建表（assets_database.sql 读取失败时的兜底，与 SQL 文件保持一致）。"""
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            bin_folder TEXT PRIMARY KEY,
            game_version TEXT,
            wows_type TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS skeleton_mounts (
            bin_folder TEXT NOT NULL,
            stem TEXT NOT NULL,
            hp_name TEXT NOT NULL,
            pos_x REAL NOT NULL DEFAULT 0,
            pos_y REAL NOT NULL DEFAULT 0,
            pos_z REAL NOT NULL DEFAULT 0,
            rot_qx REAL NOT NULL DEFAULT 0,
            rot_qy REAL NOT NULL DEFAULT 0,
            rot_qz REAL NOT NULL DEFAULT 0,
            rot_qw REAL NOT NULL DEFAULT 1,
            scale_x REAL NOT NULL DEFAULT 1,
            scale_y REAL NOT NULL DEFAULT 1,
            scale_z REAL NOT NULL DEFAULT 1,
            PRIMARY KEY(bin_folder, stem, hp_name)
        );
        CREATE INDEX IF NOT EXISTS idx_skel_stem ON skeleton_mounts(bin_folder, stem);
        CREATE TABLE IF NOT EXISTS skeleton_bones (
            bin_folder TEXT NOT NULL,
            stem TEXT NOT NULL,
            bone_name TEXT NOT NULL,
            pos_x REAL NOT NULL DEFAULT 0,
            pos_y REAL NOT NULL DEFAULT 0,
            pos_z REAL NOT NULL DEFAULT 0,
            rot_qx REAL NOT NULL DEFAULT 0,
            rot_qy REAL NOT NULL DEFAULT 0,
            rot_qz REAL NOT NULL DEFAULT 0,
            rot_qw REAL NOT NULL DEFAULT 1,
            scale_x REAL NOT NULL DEFAULT 1,
            scale_y REAL NOT NULL DEFAULT 1,
            scale_z REAL NOT NULL DEFAULT 1,
            PRIMARY KEY(bin_folder, stem, bone_name)
        );
        CREATE INDEX IF NOT EXISTS idx_bones_stem ON skeleton_bones(bin_folder, stem);
        CREATE TABLE IF NOT EXISTS render_sets (
            bin_folder TEXT NOT NULL,
            geom_path TEXT NOT NULL,
            shape TEXT NOT NULL,
            material TEXT NOT NULL DEFAULT '',
            mfm TEXT NOT NULL DEFAULT '',
            damage INTEGER NOT NULL DEFAULT 0,
            skinned INTEGER NOT NULL DEFAULT 0,
            nodes TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(bin_folder, geom_path, shape)
        );
        CREATE INDEX IF NOT EXISTS idx_rs_geom ON render_sets(bin_folder, geom_path);
        CREATE TABLE IF NOT EXISTS mfm_textures (
            bin_folder TEXT NOT NULL,
            mfm_path TEXT NOT NULL,
            texture_path TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(bin_folder, mfm_path)
        );
        CREATE TABLE IF NOT EXISTS material_full (
            bin_folder TEXT NOT NULL,
            mfm_path TEXT NOT NULL,
            shader_id TEXT NOT NULL DEFAULT '0x0',
            family TEXT NOT NULL DEFAULT '',
            material_hash TEXT NOT NULL DEFAULT '',
            textures TEXT NOT NULL DEFAULT '',
            indexed TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(bin_folder, mfm_path)
        );
        CREATE TABLE IF NOT EXISTS shape_names (
            bin_folder TEXT NOT NULL,
            hash INTEGER NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY(bin_folder, hash)
        );
        CREATE INDEX IF NOT EXISTS idx_sn_bin ON shape_names(bin_folder);
        CREATE TABLE IF NOT EXISTS meta_schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS exteriors (
            version_code TEXT NOT NULL,
            ext_index    TEXT NOT NULL,
            name         TEXT NOT NULL,
            camouflage   TEXT NOT NULL DEFAULT '',
            species      TEXT NOT NULL DEFAULT '',
            nation       TEXT NOT NULL DEFAULT '',
            cost_gold    INTEGER DEFAULT 0,
            can_buy      INTEGER DEFAULT 0,
            parts_json   TEXT DEFAULT '[]',
            custom_json  TEXT DEFAULT '{}',
            unpeculiar_camouflage TEXT DEFAULT '',
            color_scheme_id INTEGER DEFAULT 0,
            icon_path    TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            data_json    TEXT DEFAULT '{}',
            PRIMARY KEY(version_code, ext_index)
        );
        CREATE INDEX IF NOT EXISTS idx_exteriors ON exteriors(version_code, species);
        CREATE TABLE IF NOT EXISTS camouflages (
            version_code TEXT NOT NULL,
            name         TEXT NOT NULL,
            realm        TEXT NOT NULL DEFAULT '',
            tiled        INTEGER DEFAULT 0,
            use_color_scheme INTEGER DEFAULT 0,
            color_scheme TEXT DEFAULT '',
            textures_json TEXT DEFAULT '{}',
            uv_json      TEXT DEFAULT '{}',
            ship_groups_json TEXT DEFAULT '[]',
            target_ships_json TEXT DEFAULT '[]',
            icon_path    TEXT DEFAULT '',
            display_name TEXT DEFAULT '',
            PRIMARY KEY(version_code, name)
        );
        CREATE TABLE IF NOT EXISTS camouflage_color_schemes (
            version_code TEXT NOT NULL,
            name         TEXT NOT NULL,
            color0 TEXT, color1 TEXT, color2 TEXT, color3 TEXT,
            PRIMARY KEY(version_code, name)
        );
        CREATE TABLE IF NOT EXISTS camo_ship_groups (
            version_code TEXT NOT NULL,
            group_name  TEXT NOT NULL,
            ship        TEXT NOT NULL,
            PRIMARY KEY(version_code, group_name, ship)
        );
        CREATE TABLE IF NOT EXISTS camo_thumbs (
            version_code TEXT NOT NULL,
            camo_name    TEXT NOT NULL,
            texture_tag  TEXT NOT NULL DEFAULT 'tile',
            thumb_path   TEXT NOT NULL DEFAULT '',
            tex_path     TEXT NOT NULL DEFAULT '',
            width        INTEGER DEFAULT 0,
            height       INTEGER DEFAULT 0,
            updated_at   TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(version_code, camo_name, texture_tag)
        );
        """)

    # ── schema 版本管理（同 database_service 规则）───────────

    def _drop_all_tables(self) -> None:
        """删除全部表（schema 版本过低时重建用）。"""
        conn = self._conn
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (tname,) in tables:
            try:
                conn.execute(f'DROP TABLE IF EXISTS "{tname}"')
            except sqlite3.OperationalError:
                pass
        conn.commit()

    def get_current_version(self) -> int:
        """当前已应用的 schema 版本（meta_schema_version 最高版本；无表/异常返回 0）。"""
        try:
            row = self._conn.execute(
                "SELECT version FROM meta_schema_version "
                "ORDER BY version DESC LIMIT 1").fetchone()
            return int(row["version"]) if row else 0
        except (sqlite3.OperationalError, TypeError, ValueError):
            return 0

    def _record_version(self, ver: int) -> None:
        """记录已应用的 schema 版本。"""
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO meta_schema_version (version) VALUES (?)", (ver,))
            self._conn.commit()
        except sqlite3.OperationalError:
            pass

    # ── 入库（「加载数据」时调用）────────────────────────────

    @staticmethod
    def _murmur3_32(data: bytes, seed: int = 0) -> int:
        """MurmurHash3_x86_32：渲染集 shape 名 ↔ geometry mapping_id 归属校验用。"""
        from utils.asset_utils import murmur3_32
        return murmur3_32(data, seed)

    def populate(self, assets_path: str, bin_folder: str,
                 game_version: str = "", wows_type: str = "",
                 game_dir: str | Path | None = None,
                 progress_cb=None) -> dict:
        """现场解析 assets.bin 并写入缓存数据库。

        assets_path: assets.bin 文件路径（当前客户端提取产物）
        progress_cb: 可选阶段进度回调（str 消息），用于把骨架/渲染集/材质各阶段
        显示到日志区。
        返回 {skeleton, render_sets, mfm_textures} 各条数。
        """
        from uncode_assets.service import AssetsBinService

        self.initialize()
        # ── 全量重建（覆盖全部内容，无视 bin 版本号）─────────────
        # 用户要求：每次加载数据都清空 assets_data.db 全部表并重新写入一次，
        # 彻底避免跨客户端/旧版本数据残留（旧实现按 bin_folder 逐表 DELETE，
        # 若中途失败会整事务回滚，留下旧数据未覆盖；且多客户端数据并存）。
        # drop 全部表 → 幂等重建（assets_database.sql 优先 / inline 兜底）→ 记录 schema 版本。
        self._drop_all_tables()
        self.initialize()
        # wows_type 传入：WG 服用 10 类型表 + WG 布局（渲染集 0x70/材质 0x78）
        svc = AssetsBinService(assets_path=assets_path, wows_type=self._wows_type)
        db = svc.db

        def _p(msg: str) -> None:
            if progress_cb:
                try:
                    progress_cb(msg)
                except Exception:  # noqa: BLE001
                    pass

        # 共享 pkg 提取器（Exterior/涂装图标；仅在需要时惰性创建），最后由 finally 统一关闭
        _shared_ext = None

        try:
            counts = {"skeleton": 0, "render_sets": 0, "mfm_textures": 0,
                      "material_full": 0, "skeleton_bones": 0, "shape_names": 0,
                      "exteriors": 0, "camouflages": 0, "camouflage_color_schemes": 0,
                      "camo_ship_groups": 0}
            # 共用：字符串 dict + self_id 索引（渲染集/材质解析都要用）
            sdict = self._strings_dict(db)
            self_id_idx = db.build_self_id_index()
            # 表已全量清空重建，无需按 bin_folder 逐表 DELETE；直接写入元信息
            self._conn.execute(
                "INSERT INTO meta(bin_folder, game_version, wows_type, created_at) "
                "VALUES (?,?,?,datetime('now'))",
                (bin_folder, game_version, wows_type))

            _p("清空旧缓存并写入元信息，扫描 VFS 全树...")

            # 收集骨架/视觉/扩展/材质文件（一次遍历全树）：
            #   skel_files: Korabli SkeletonPrototype（HP_/MP_ 挂点 + 骨骼）
            #   vis_files:  WG VisualPrototype .visual（基础骨架 nodes，含 HP_ 挂点）
            #   ext_files:  WG SkeletonExtender .skel_ext（MP_/SP_/EP_ 挂点）
            #   mfm_files:  MaterialPrototype .mfm（材质贴图）
            skel_files: list = []
            mfm_files: list = []
            vis_files: list = []
            ext_files: list = []
            for f in svc.vfs.all_files():
                try:
                    pt = f.prototype_type
                    if pt is None:
                        continue
                except Exception:  # noqa: BLE001
                    continue
                if pt.name == "SkeletonPrototype":
                    skel_files.append(f)
                elif pt.name == "MaterialPrototype" and f.path.endswith(".mfm"):
                    mfm_files.append(f)
                elif pt.name == "VisualPrototype" and f.path.endswith(".visual"):
                    vis_files.append(f)
                elif pt.name == "SkeletonExtenderPrototype" and f.path.endswith(".skel_ext"):
                    ext_files.append(f)

            if self._is_wg():
                _p(f"解析舰体骨架挂点与骨骼（{len(skel_files)} 个骨架文件，"
                   f"Visual {len(vis_files)} / SkeletonExtender {len(ext_files)}）...")
                _p("WG 服：骨架来自 Visual nodes（HP_ 挂点/骨骼）+ "
                   "SkeletonExtender（MP_/SP_/EP_ 挂点）")
            else:
                _p(f"解析舰体骨架挂点与骨骼（{len(skel_files)} 个骨架文件）...")

            # 1) 骨架挂点 + 完整骨骼世界矩阵（bind pose 按 parent 累积）
            #    Korabli：SkeletonPrototype；WG：Visual nodes（HP_）+ SkeletonExtender（MP_）
            import numpy as np
            skel_rows: list[tuple] = []
            bone_rows: list[tuple] = []
            skel_failed: list[str] = []
            for f in skel_files:
                stem = self._stem_of_skeleton(f.path)
                if not stem:
                    continue
                try:
                    sk = svc.decode_skeleton_path(f.path)
                except Exception as exc:  # noqa: BLE001
                    skel_failed.append(f"{stem}({exc})")
                    continue
                names = sk.get("name_ids") or []
                mats = sk.get("matrices") or []
                parents = sk.get("parent_ids") or []
                n = len(names)
                # 完整骨骼世界矩阵（与 geometry_service._skeleton_bone_world 一致）
                if n and n == len(mats):
                    try:
                        local = [np.array(mats[i], dtype=np.float32).reshape(4, 4).T
                                 for i in range(n)]
                        w: list = [None] * n
                        for i in range(n):
                            p = parents[i] if i < len(parents) else 65535
                            if p >= n or p == i or p == 65535:
                                w[i] = local[i]
                            else:
                                w[i] = (w[p] if w[p] is not None
                                        else np.eye(4, dtype=np.float32)) @ local[i]
                        for i, nm in enumerate(names):
                            if i < len(w) and w[i] is not None:
                                # 统一用 _decompose_mat 分解（含反射 det=-1 处理：
                                # 否则 Root_BlendBone 等 Z 镜像骨骼会被存成恒等 → 主炮/副炮方向翻转）
                                pos, quat, scale = self._decompose_mat(w[i])
                                bone_rows.append((
                                    bin_folder, stem, str(nm),
                                    float(pos[0]), float(pos[1]), float(pos[2]),
                                    quat[0], quat[1], quat[2], quat[3],
                                    scale[0], scale[1], scale[2]))
                    except Exception:  # noqa: BLE001
                        pass
                # HP_/MP_ 挂点（舰船骨架定位用；存解码后坐标/四元数/缩放）
                # MP_ 为甲板设备挂点（缆桩/小艇/探照灯等 misc 模型），v5 起纳入；
                # 其 parent 恒为 Scene Root，原始矩阵即船空间 bind pose
                for i, n in enumerate(names):
                    if not (isinstance(n, str)
                            and (n.startswith("HP_") or n.startswith("MP_"))):
                        continue
                    if i >= len(mats) or not mats[i] or len(mats[i]) < 16:
                        continue
                    m = np.array(mats[i], dtype=np.float32).reshape(4, 4).T
                    pos, quat, scale = self._decompose_mat(m)
                    skel_rows.append((bin_folder, stem, n,
                                      pos[0], pos[1], pos[2],
                                      quat[0], quat[1], quat[2], quat[3],
                                      scale[0], scale[1], scale[2]))
            # WG：Visual nodes（HP_ 挂点 + 骨骼）+ SkeletonExtender（MP_/SP_/EP_ 挂点）
            if self._is_wg():
                self._populate_wg_skeleton(
                    svc, db, sdict, self_id_idx, bin_folder,
                    vis_files, ext_files, skel_rows, bone_rows, skel_failed)
            if skel_failed:
                sample = ", ".join(skel_failed[:5])
                more = f" 等 {len(skel_failed)} 个" if len(skel_failed) > 5 else ""
                _p(f"⚠️ {len(skel_failed)} 个骨架解码失败: {sample}{more}")
            if skel_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO skeleton_mounts "
                    "(bin_folder, stem, hp_name, "
                    "pos_x, pos_y, pos_z, rot_qx, rot_qy, rot_qz, rot_qw, "
                    "scale_x, scale_y, scale_z) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    skel_rows)
            counts["skeleton"] = len(skel_rows)
            del skel_rows
            if bone_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO skeleton_bones "
                    "(bin_folder, stem, bone_name, "
                    "pos_x, pos_y, pos_z, rot_qx, rot_qy, rot_qz, rot_qw, "
                    "scale_x, scale_y, scale_z) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    bone_rows)
            counts["skeleton_bones"] = len(bone_rows)
            del bone_rows

            _p("解析视觉渲染集（shape → 材质/mfm 引用）...")

            # 2) 视觉渲染集（VisualPrototype 渲染集区 → shape/材质/mfm）
            rs_rows: list[tuple] = []
            try:
                from uncode_assets.parser import BLOB_HEADER_SIZE
                from uncode_assets.types import type_from_magic
                vis = next((b for b in db.databases if (lambda t: t and
                           t.name == "VisualPrototype")(
                    type_from_magic(b.prototype_magic))), None)
                if vis is not None:
                    data = vis.data
                    isize = vis.item_size
                    nrec = vis.record_count
                    wg = self._is_wg()
                    for ri in range(nrec):
                        off = BLOB_HEADER_SIZE + ri * isize
                        if wg:
                            # WG VisualPrototype 0x70 布局（wows-toolkit visual.rs）：
                            # 渲染集 relptr 在 +0x60，记录头字段与 Korabli 完全不同，
                            # 走专用 WG 解析（每记录一 geometry → 渲染集 0x28 步长）
                            self._render_sets_wg(data, off, db, self_id_idx, sdict,
                                                 bin_folder, rs_rows)
                            continue
                        if off + 0x40 > len(data):
                            break
                        cnt = struct.unpack_from('<Q', data, off + 0x30)[0]
                        rel = struct.unpack_from('<Q', data, off + 0x38)[0]
                        if not rel or cnt <= 0:
                            continue
                        h = struct.unpack_from('<Q', data, off + 0x20)[0]
                        gp = self._path_of(h, db, self_id_idx)
                        if not (gp and gp.endswith(".geometry")):
                            continue
                        # 渲染集数组：+0x38 rel 为 **record-relative**（相对记录起始），
                        # 数组从 rel 起、每项 0x50 步长；+0x30 count 为权威条数。
                        # ⚠️ 2026-08-19 修正：VisualPrototype item_size=0x40（非 0x80）。
                        # 每条记录唯一 geometry（+0x20）+ primitives（+0x28）。旧 0x80
                        # 误把两条记录合并 → JGA180 误用 JGA181 的 TurretShapeff。
                        # 无多 geometry 共用 → 无需广播归属，直接归本记录 geometry。
                        base = off + rel
                        if base + cnt * 0x50 > len(data):
                            continue
                        for k in range(cnt):
                            o = base + k * 0x50
                            shp = sdict.get(struct.unpack_from('<I', data, o)[0]) or ''
                            if not shp.endswith('.vertices'):
                                continue
                            mat = sdict.get(struct.unpack_from('<I', data, o + 8)[0]) or ''
                            mfm_h = struct.unpack_from('<Q', data, o + 0x20)[0]
                            mfm = self._path_of(mfm_h, db, self_id_idx)
                            damage = int('_crack_' in shp or '_lod' in shp
                                         or 'Crack' in mat)
                            # 蒙皮标志 + 调色板节点名（Korabli 渲染集项布局）：
                            #   +0x0C u8 skinned / +0x0D u8 nodes_count /
                            #   +0x28 u64 node_name_ids relptr（**item-relative**）
                            #   → u32 名ID 数组[nodes_count]
                            skinned = data[o + 0x0C]
                            ncnt = data[o + 0x0D]
                            nodes: list[str] = []
                            # ★ 所有条目都读 nodes（含 skinned=0 的刚性父子模型，如
                            #   BIA454_Bollard_bigShape → ['BIA454_Bollard_big_7']），
                            #   供 geometry_service 按父节点矩阵定位到舰船空间。
                            if ncnt:
                                nrel = struct.unpack_from('<Q', data, o + 0x28)[0]
                                if nrel:
                                    nabs = o + nrel
                                    if nabs + ncnt * 4 <= len(data):
                                        for j in range(ncnt):
                                            nid = struct.unpack_from('<I', data, nabs + j * 4)[0]
                                            nm = sdict.get(nid) or ''
                                            if nm:
                                                nodes.append(nm)
                            rs_rows.append((bin_folder, gp, shp, mat, mfm, damage,
                                            int(skinned), json.dumps(nodes)))
            except Exception:  # noqa: BLE001
                pass
            if rs_rows:
                # ★ 汇总同一 shape 的多节点绑定（左右舷实例化），避免 PK 折叠丢节点
                rs_rows = self._merge_render_set_rows(rs_rows)
                self._conn.executemany(
                    "INSERT OR REPLACE INTO render_sets "
                    "(bin_folder, geom_path, shape, material, mfm, damage, "
                    "skinned, nodes) VALUES (?,?,?,?,?,?,?,?)", rs_rows)
            counts["render_sets"] = len(rs_rows)
            del rs_rows

            # 2.5) shape 名哈希表（*.vertices：mapping_id → 名，LOD/crack 兜底跳过用）
            #      ★ 显示时只从本库读取，绝不现场读 assets.bin 字符串表
            sn_rows = [(bin_folder, h, nm) for h, nm in sdict.items()
                       if nm.endswith(".vertices")]
            if sn_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO shape_names (bin_folder, hash, name) "
                    "VALUES (?,?,?)", sn_rows)
            counts["shape_names"] = len(sn_rows)
            del sn_rows

            _p(f"解析材质（{len(mfm_files)} 个 mfm 文件）...")

            # 3) 材质：mfm_textures（diffuseMap 原始路径）+ material_full（完整：
            #    shader_id / 所有贴图原始路径 / INDEXED vec4 数组）。
            #    只存路径与参数，贴图字节渲染时实时从客户端 pkg 解包。
            from uncode_assets import binary as B
            from uncode_assets.decoders import _read_typed_value
            mfm_rows: list[tuple] = []
            mf_rows: list[tuple] = []
            mfm_failed: list[str] = []
            wg_mat = self._is_wg()
            for f in mfm_files:
                try:
                    data = svc.vfs.open_file_len(f.path, 0x78 if wg_mat else 0x90)
                except Exception as exc:  # noqa: BLE001
                    mfm_failed.append(f"{f.path.rsplit('/', 1)[-1]}({exc})")
                    continue
                if len(data) < (0x78 if wg_mat else 0x88):
                    continue
                pc = B.read_u16(data, 0x00)
                if not pc:
                    continue
                if wg_mat:
                    # WG MaterialPrototype 0x78 布局（wows-toolkit material.rs）：
                    # +0x00 u16 property_count / +0x02 u16 flags /
                    # +0x04 u32 shader_id / +0x08 u64 reserved /
                    # +0x10 names_ptr / +0x18 type_idx_ptr /
                    # +0x20..+0x60 type_ptrs[9] / +0x68 material_hash
                    shader_id = B.read_u32(data, 0x04)
                    mat_hash = B.read_u64(data, 0x68)
                    names_ptr = B.read_u64(data, 0x10)
                    type_idx_ptr = B.read_u64(data, 0x18)
                    type_ptrs = {t: B.read_u64(data, 0x20 + t * 8) for t in range(9)}
                else:
                    # Korabli 0x88 布局
                    shader_id = B.read_u32(data, 0x08)
                    mat_hash = B.read_u64(data, 0x78)
                    names_ptr = B.read_u64(data, 0x18)
                    type_idx_ptr = B.read_u64(data, 0x20)
                    type_ptrs = {t: B.read_u64(data, 0x30 + t * 8) for t in range(9)}
                tptr4 = type_ptrs.get(4) or 0
                vec4_ptr = type_ptrs.get(7) or 0
                need = 0x90
                if names_ptr and pc:
                    need = max(need, names_ptr + pc * 4)
                if type_idx_ptr and pc:
                    need = max(need, type_idx_ptr + pc * 2)
                if tptr4 and pc:
                    need = max(need, tptr4 + pc * 8)
                if vec4_ptr and pc:
                    # ⚠️ 覆盖全部 vec4 数组（pidx 最多 4096 槽位，非仅 pc*16：tileIdxMatIdArr 等 pidx 可达 980）
                    need = max(need, vec4_ptr + 4096 * 16 + 64)
                if need > 0x90:
                    try:
                        data = svc.vfs.open_file_len(f.path, need + 8)
                    except Exception:  # noqa: BLE001
                        continue
                names = B.parse_u32_array(data, names_ptr, pc) if (names_ptr and pc) else []
                type_idx = B.parse_u16_array(data, type_idx_ptr, pc) if (type_idx_ptr and pc) else []
                textures: dict = {}
                vec4s: list = []
                diff_base = ""
                for i in range(pc):
                    ti = type_idx[i] if i < len(type_idx) else 0
                    ptype = ti & 0xF
                    pidx = ti >> 4
                    raw_name = names[i] if i < len(names) else 0
                    # 数组名优先查 sdict（shape/贴图名缓存），缺失时回退 db.strings 完整表
                    # （⚠️ tileIdxMatIdArr/offsetScaleMatIdArr/artStrengthMatIdArr 等在 sdict 缺失，
                    #   必须用 db.strings 解析，否则 INDEXED 分块数组被漏提取）
                    nm = (sdict.get(raw_name & 0xFFFFFFFF)
                          or db.strings.get_string_or_hex(raw_name)
                          or "")
                    if ptype == 4:
                        value = _read_typed_value(data, tptr4, 4, pidx)
                        if isinstance(value, int) and value:
                            vp = self._path_of(value, db, self_id_idx)
                            if vp:
                                if nm == "diffuseMap" and not diff_base:
                                    diff_base = vp
                                textures[nm or f"tex_{i}"] = vp
                    elif ptype == 7 and nm:
                        vec4s.append((raw_name, pidx))
                if diff_base:
                    mfm_rows.append((bin_folder, self._norm_vfs_path(f.path), diff_base))
                # INDEXED vec4 数组（每属性 196 项连续，pidx 间距推断长度）
                indexed: dict = {}
                if vec4s and vec4_ptr:
                    for j, (nid, pidx) in enumerate(vec4s):
                        nm = (sdict.get(nid & 0xFFFFFFFF)
                              or db.strings.get_string_or_hex(nid)
                              or f"vec4_{j}")
                        if j + 1 < len(vec4s):
                            length = vec4s[j + 1][1] - pidx
                        elif len(vec4s) > 1:
                            length = vec4s[1][1] - vec4s[0][1]
                        else:
                            length = 1
                        length = max(0, min(length, 4096))
                        off = vec4_ptr + pidx * 16
                        vals = []
                        for k in range(length):
                            o = off + k * 16
                            if o + 16 <= len(data):
                                vals.append([round(float(x), 6) for x in B.parse_vec4(data, o)])
                        if vals:
                            indexed[nm] = vals
                family = self._material_family(f"0x{shader_id:08X}")
                mf_rows.append((bin_folder, self._norm_vfs_path(f.path), f"0x{shader_id:08X}", family,
                                f"0x{mat_hash:016X}", json.dumps(textures), json.dumps(indexed)))
            if mfm_failed:
                sample = ", ".join(mfm_failed[:5])
                more = f" 等 {len(mfm_failed)} 个" if len(mfm_failed) > 5 else ""
                _p(f"⚠️ {len(mfm_failed)} 个材质文件读取失败: {sample}{more}")
            if mfm_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO mfm_textures "
                    "(bin_folder, mfm_path, texture_path) VALUES (?,?,?)", mfm_rows)
            counts["mfm_textures"] = len(mfm_rows)
            del mfm_rows
            if mf_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO material_full "
                    "(bin_folder, mfm_path, shader_id, family, material_hash, textures, indexed) "
                    "VALUES (?,?,?,?,?,?,?)", mf_rows)
            counts["material_full"] = len(mf_rows)
            del mf_rows

            _p("写入外观（Exterior）与涂装（camouflages.xml）数据...")
            # 每次加载清空旧选项图，重新提取存储
            try:
                cdir = get_data_dir() / "camo_thumbs"
                if cdir.exists():
                    shutil.rmtree(cdir)
                cdir.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
            icon_map: dict[str, str] = {}
            material_to_icon: dict[str, str] = {}
            material_to_display: dict[str, str] = {}
            # 共享单个 GameExtractor（仅当需要从 pkg 读图标/涂装时才建）：原实现对每个
            # 命中的外观图标都 new 一个 GameExtractor（重载全部 IDX + 整棵文件树），外观文件
            # 数以千计 → 反复重建巨大文件树，长时间无输出，看起来像卡死。这里惰性建一次复用。
            def _ext_factory():
                nonlocal _shared_ext
                if _shared_ext is None and game_dir:
                    from data_extractor import GameExtractor
                    _shared_ext = GameExtractor(str(game_dir), bin_folder=bin_folder)
                return _shared_ext
            # 涂装本地化名：从本地化文件(.po/.mo)按 IDS_<Exterior name 大写> 提取显示名
            _loc_cands = [str(get_data_dir() / "global.po"), str(get_data_dir() / "global.mo"),
                          str(get_data_dir() / "global_zh_sg.po"), str(get_data_dir() / "zh_cn.po")]
            for _base in (Path(r"D:\战舰世界汉化\bin"),):
                for _fn in ("global_zh_sg.po", "global.po", "global.mo"):
                    _loc_cands.append(str(_base / _fn))
            loc_map = self._load_camo_locale(_loc_cands)
            # 9) Exterior JSON（data/split/Exterior/*.json）→ exteriors 表
            #    同时扫描 pkg gui/exteriors，按 name 优先/index 次之匹配选项图，
            #    提取(复制)到 data/camo_thumbs/<bin>/，并把相对 data 的路径写入 icon_path。
            try:
                from utils.path_utils import get_split_dir
                icon_map = self._camo_icon_map(game_dir, bin_folder, ext_factory=_ext_factory)
                ext_dir = get_split_dir() / "Exterior"
                ext_rows: list[tuple] = []
                if ext_dir.exists():
                    ext_files = sorted(ext_dir.glob("*.json"))
                    ext_total = len(ext_files)
                    # 外观文件极多，分批输出进度，避免长时间无任何日志（显得卡死）
                    ext_batch = max(1, ext_total // 20 or 1)
                    for _i, f in enumerate(ext_files, 1):
                        try:
                            d = json.loads(f.read_text(encoding="utf-8"))
                        except Exception:  # noqa: BLE001
                            continue
                        ti = d.get("typeinfo") or {}
                        ext_name = d.get("name", f.stem)
                        ext_index = d.get("index", f.stem)
                        icon_rel = self._cache_camo_icon(
                            game_dir, bin_folder,
                            self._resolve_camo_icon(icon_map, ext_name, ext_index), ext_name,
                            ext_factory=_ext_factory)
                        camo_mat = d.get("camouflage", "") or ""
                        display_name = loc_map.get("IDS_" + ext_name.upper(), "")
                        if camo_mat:
                            material_to_icon[camo_mat.lower()] = icon_rel
                            material_to_display[camo_mat.lower()] = display_name
                        ext_rows.append((
                            bin_folder,
                            ext_index,
                            ext_name,
                            camo_mat,
                            ti.get("species", "") or "",
                            ti.get("nation", "") or "",
                            int(d.get("costGold", 0) or 0),
                            int(bool(d.get("canBuy"))),
                            json.dumps(d.get("parts", []), ensure_ascii=False),
                            json.dumps(d.get("custom", {}), ensure_ascii=False),
                            d.get("unpeculiarCamouflage", "") or "",
                            int(d.get("unpeculiarCamouflageColorSchemeId", 0) or 0),
                            icon_rel,
                            display_name,
                            json.dumps(d, ensure_ascii=False),
                        ))
                        if ext_total > ext_batch and _i % ext_batch == 0:
                            _p(f"外观数据入库进度 {_i}/{ext_total} ...")
                if ext_rows:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO exteriors "
                        "(version_code, ext_index, name, camouflage, species, nation, "
                        "cost_gold, can_buy, parts_json, custom_json, "
                        "unpeculiar_camouflage, color_scheme_id, icon_path, display_name, data_json) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ext_rows)
                counts["exteriors"] = len(ext_rows)
                _p(f"外观数据已入库: {counts['exteriors']} 条")
                del ext_rows
            except Exception:  # noqa: BLE001
                pass

            # 10) camouflages.xml（包根，含 shipgroups/colorschemes/camouflages 三段）
            #     → camouflages + camouflage_color_schemes 表，供涂装切换器按索引查询。
            try:
                from services.camo_service import parse_camouflages
                camo_xml: bytes | None = None
                if game_dir:
                    rp = Path(game_dir) / "res_unpack" / "camouflages.xml"
                    if rp.exists():
                        camo_xml = rp.read_bytes()
                if camo_xml is None and game_dir:
                    ext = _ext_factory()
                    if ext is not None:
                        try:
                            hits = ext.list_files(["camouflages.xml"])
                            if hits:
                                e = hits[0]
                                camo_xml = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
                        except Exception:  # noqa: BLE001
                            pass
                if camo_xml:
                    _p("解析 camouflages.xml（涂装/配色/船组）...")
                    parsed = parse_camouflages(camo_xml)
                    crows: list[tuple] = []
                    csrows: list[tuple] = []
                    for name, variants in (parsed.get("entries") or {}).items():
                        if not variants:
                            continue
                        entry = variants[0]
                        icon_rel = material_to_icon.get(entry.name.lower(), "")
                        display_name = material_to_display.get(entry.name.lower(), "")
                        crows.append((
                            bin_folder, name, entry.realm, int(entry.tiled),
                            int(entry.use_color_scheme),
                            ",".join(entry.color_schemes
                                     or ([entry.color_scheme] if entry.color_scheme else [])),
                            json.dumps(entry.textures, ensure_ascii=False),
                            json.dumps(
                                {k: {"scale": list(v.scale), "offset": list(v.offset)}
                                 for k, v in entry.uv_transforms.items()},
                                ensure_ascii=False),
                            json.dumps(entry.ship_groups, ensure_ascii=False),
                            json.dumps(entry.target_ships, ensure_ascii=False),
                            icon_rel,
                            display_name,
                        ))
                    for cname, cs in (parsed.get("color_schemes") or {}).items():
                        cols = cs.colors or [[0.0] * 4 for _ in range(4)]
                        csrows.append((bin_folder, cname) + tuple(
                            json.dumps(list(cols[i]), ensure_ascii=False) for i in range(4)))
                    if crows:
                        self._conn.executemany(
                            "INSERT OR REPLACE INTO camouflages "
                            "(version_code, name, realm, tiled, use_color_scheme, "
                            "color_scheme, textures_json, uv_json, "
                            "ship_groups_json, target_ships_json, icon_path, display_name) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", crows)
                    if csrows:
                        self._conn.executemany(
                            "INSERT OR REPLACE INTO camouflage_color_schemes "
                            "(version_code, name, color0, color1, color2, color3) "
                            "VALUES (?,?,?,?,?,?)", csrows)
                    # shipgroups.xml 全局船组映射
                    sgrows: list[tuple] = []
                    for gname, ships in (parsed.get("ship_groups") or {}).items():
                        for s in ships:
                            sgrows.append((bin_folder, gname, s))
                    if sgrows:
                        self._conn.executemany(
                            "INSERT OR REPLACE INTO camo_ship_groups "
                            "(version_code, group_name, ship) VALUES (?,?,?)", sgrows)
                    counts["camouflages"] = len(crows)
                    counts["camouflage_color_schemes"] = len(csrows)
                    counts["camo_ship_groups"] = len(sgrows)
                    _p(f"涂装数据已入库: {counts['camouflages']} 条 / "
                       f"配色 {counts['camouflage_color_schemes']} 条 / "
                       f"船组 {counts['camo_ship_groups']} 条")
            except Exception:  # noqa: BLE001
                pass

            self._conn.commit()
            return counts
        finally:
            svc.close()
            # 关闭共享 pkg 提取器（释放 IDX/文件树内存）
            if _shared_ext is not None:
                try:
                    _shared_ext.close()
                except Exception:  # noqa: BLE001
                    pass

    # ── 查询（3D 查看器用）─────────────────────────────────


    def get_exteriors(self, bin_folder: str) -> list[dict]:
        """该版本全部外观/涂装（Exterior JSON 索引）：[{index,name,species,nation,icon_path,display_name,...}]。"""
        out: list[dict] = []
        try:
            rows = self._conn.execute(
                "SELECT ext_index, name, camouflage, species, nation, cost_gold, can_buy, "
                "parts_json, custom_json, unpeculiar_camouflage, color_scheme_id, "
                "icon_path, display_name, data_json "
                "FROM exteriors WHERE version_code=? ORDER BY ext_index",
                (bin_folder,)).fetchall()
            for r in rows:
                out.append({
                    "index": r["ext_index"],
                    "name": r["name"],
                    "camouflage": r["camouflage"],
                    "species": r["species"],
                    "nation": r["nation"],
                    "cost_gold": r["cost_gold"],
                    "can_buy": bool(r["can_buy"]),
                    "parts": json.loads(r["parts_json"] or "[]"),
                    "custom": json.loads(r["custom_json"] or "{}"),
                    "unpeculiar_camouflage": r["unpeculiar_camouflage"],
                    "color_scheme_id": r["color_scheme_id"],
                    "icon_path": r["icon_path"] or "",
                    "display_name": r["display_name"] or r["name"],
                    "data": json.loads(r["data_json"] or "{}"),
                })
        except (sqlite3.OperationalError, ValueError):
            out = []
        return out

    def get_camouflage(self, bin_folder: str, name: str) -> dict | None:
        """按索引取一条 camo（camouflages.xml 条目）。"""
        try:
            row = self._conn.execute(
                "SELECT name, realm, tiled, use_color_scheme, color_scheme, textures_json, "
                "uv_json, ship_groups_json, target_ships_json, icon_path, display_name "
                "FROM camouflages WHERE version_code=? AND name=?",
                (bin_folder, name)).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        return {
            "name": row["name"],
            "realm": row["realm"],
            "tiled": bool(row["tiled"]),
            "use_color_scheme": bool(row["use_color_scheme"]),
            "color_scheme": row["color_scheme"],
            "textures": json.loads(row["textures_json"] or "{}"),
            "uv": json.loads(row["uv_json"] or "{}"),
            "ship_groups": json.loads(row["ship_groups_json"] or "[]"),
            "target_ships": json.loads(row["target_ships_json"] or "[]"),
            "icon_path": row["icon_path"] or "",
            "display_name": row["display_name"] or row["name"],
        }

    def get_camouflage_color_scheme(self, bin_folder: str, name: str) -> dict | None:
        """取一条颜色方案（默认/若干 color0..3，各 4 float）。"""
        try:
            row = self._conn.execute(
                "SELECT name, color0, color1, color2, color3 "
                "FROM camouflage_color_schemes WHERE version_code=? AND name=?",
                (bin_folder, name)).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        colors = []
        for i in range(4):
            txt = row[f"color{i}"]
            try:
                colors.append(json.loads(txt) if txt else [0.0] * 4)
            except Exception:
                colors.append([0.0] * 4)
        return {"name": row["name"], "colors": colors}

    def get_all_camouflages(self, bin_folder: str) -> list[dict]:
        """该版本全部 camouflages.xml 条目。"""
        out: list[dict] = []
        try:
            rows = self._conn.execute(
                "SELECT name, realm, tiled, use_color_scheme, color_scheme, textures_json, "
                "uv_json, ship_groups_json, target_ships_json, icon_path, display_name "
                "FROM camouflages WHERE version_code=? ORDER BY name",
                (bin_folder,)).fetchall()
        except sqlite3.OperationalError:
            return []
        for r in rows:
            out.append({
                "name": r["name"], "realm": r["realm"],
                "tiled": bool(r["tiled"]), "use_color_scheme": bool(r["use_color_scheme"]),
                "color_scheme": r["color_scheme"] or "",
                "textures": json.loads(r["textures_json"] or "{}"),
                "uv": json.loads(r["uv_json"] or "{}"),
                "ship_groups": json.loads(r["ship_groups_json"] or "[]"),
                "target_ships": json.loads(r["target_ships_json"] or "[]"),
                "icon_path": r["icon_path"] or "",
                "display_name": r["display_name"] or r["name"],
            })
        return out

    def get_all_camo_color_schemes(self, bin_folder: str) -> dict[str, list]:
        """该版本全部颜色方案：{name: [color0..3] 各 4 float}。"""
        out: dict[str, list] = {}
        try:
            rows = self._conn.execute(
                "SELECT name, color0, color1, color2, color3 "
                "FROM camouflage_color_schemes WHERE version_code=?",
                (bin_folder,)).fetchall()
        except sqlite3.OperationalError:
            return {}
        for r in rows:
            cols = []
            for i in range(4):
                txt = r[f"color{i}"]
                try:
                    cols.append(json.loads(txt) if txt else [0.0] * 4)
                except Exception:
                    cols.append([0.0] * 4)
            out[r["name"]] = cols
        return out

    def get_all_camo_ship_groups(self, bin_folder: str) -> dict[str, set]:
        """该版本全部船组映射：{group_name: set(ship)}。"""
        out: dict[str, set] = {}
        try:
            rows = self._conn.execute(
                "SELECT group_name, ship FROM camo_ship_groups WHERE version_code=?",
                (bin_folder,)).fetchall()
        except sqlite3.OperationalError:
            return {}
        for r in rows:
            out.setdefault(r["group_name"], set()).add(r["ship"])
        return out

    # ── 涂装选项图缓存：文件存 data/camo_thumbs，DB 记录路径/尺寸/来源贴图 ──
    @staticmethod
    def camo_thumbs_dir(bin_folder: str = "") -> Path:
        """涂装预览缩略图缓存目录（放 data 目录，符合「解包数据入 data」约定）。

        ⚠️ 不按 bin 分级：所有涂装图平铺在 data/camo_thumbs/，每次加载时整体清空重提取。
        """
        return get_data_dir() / "camo_thumbs"

    def get_camo_thumb(self, bin_folder: str, camo_name: str,
                       texture_tag: str = "tile") -> str | None:
        """返回已缓存缩略图路径；未生成则 None（由调用方拆图后 put_camo_thumb 写回）。"""
        try:
            row = self._conn.execute(
                "SELECT thumb_path FROM camo_thumbs "
                "WHERE version_code=? AND camo_name=? AND texture_tag=?",
                (bin_folder, camo_name, texture_tag)).fetchone()
        except sqlite3.OperationalError:
            return None
        if not row:
            return None
        p = Path(row["thumb_path"])
        return str(p) if p.exists() else None

    def put_camo_thumb(self, bin_folder: str, camo_name: str, texture_tag: str,
                       thumb_path: str, tex_path: str = "",
                       width: int = 0, height: int = 0) -> None:
        """记录已生成的涂装缩略图（文件已在 data/camo_thumbs，此处写索引）。"""
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO camo_thumbs "
                "(version_code, camo_name, texture_tag, thumb_path, tex_path, "
                "width, height, updated_at) "
                "VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))",
                (bin_folder, camo_name, texture_tag, str(thumb_path),
                 tex_path, int(width), int(height)))
            self._conn.commit()
        except (sqlite3.OperationalError, ValueError):
            pass

    @staticmethod
    def _load_camo_locale(source_paths) -> dict[str, str]:
        """从本地化文件(.po/.mo)读取 {msgid.upper(): msgstr}（仅保留翻译非空、非 IDS_ 前缀）。

        涂装本地化 msgid 形如 IDS_<Exterior name 大写>，如 IDS_PFES330_AQUITAINE_WHITE。
        """
        out: dict[str, str] = {}
        for p in source_paths:
            if not p:
                continue
            p = Path(p)
            if not p.exists():
                continue
            try:
                if p.suffix.lower() == ".po":
                    import polib
                    po = polib.pofile(str(p))
                    for e in po:
                        mid = (e.msgid or "").strip()
                        st = (e.msgstr or "").strip()
                        if mid and st and not st.startswith("IDS_"):
                            out[mid.upper()] = st
                else:
                    import gettext
                    with p.open("rb") as f:
                        m = gettext.GNUTranslations(f)
                    for k, v in (m._catalog or {}).items():
                        if isinstance(k, str) and k.startswith("IDS_") and v and not v.startswith("IDS_"):
                            out[k.upper()] = v
            except Exception:  # noqa: BLE001
                continue
        return out

    # ── 涂装选项图来源（pkg gui/exteriors）扫描与 name/index 匹配 ──
    def _camo_icon_map(self, game_dir, bin_folder: str = "", ext_factory=None) -> dict[str, str]:
        """扫描 gui/exteriors 包图标：{key_lower: png 路径}。

        key 取文件名 stem（camouflages/skins/permoflages 平铺）或 colored 目录名
        （camouflages_colored/expendable/<DIR>）。优先 res_unpack 文件系统，回退包列表。
        ext_factory: 可选，返回可复用 GameExtractor 的工厂；提供时包列表分支本方法
        不再自建/关闭，用于批量复制图标时避免每个图标重载全部 IDX/文件树导致卡死。
        """
        icon_map: dict[str, str] = {}
        if not game_dir:
            return icon_map

        # 1) 文件系统 res_unpack（快）
        try:
            base = Path(game_dir) / "res_unpack" / "gui" / "exteriors"
            bad = {"ensigns", "decals_dds_scale"}   # 绝不属涂装系统，明确排除
            if base.is_dir():
                for p in base.rglob("*.png"):
                    rel = p.relative_to(base).parts
                    if any(seg.lower() in bad for seg in rel):
                        continue
                    low = p.as_posix().lower()
                    if len(rel) >= 2 and rel[0].lower() == "camouflages_colored":
                        if len(rel) >= 3 and rel[1].lower() == "expendable":
                            key = rel[2].lower()
                            if key not in icon_map or "color_0" in low:
                                icon_map[key] = p.as_posix()
                        continue
                    key = p.stem.lower()
                    icon_map.setdefault(key, p.as_posix())
                return icon_map
        except Exception:  # noqa: BLE001
            pass

        # 2) 包内列表（无 res_unpack 时）
        try:
            bad = {"ensigns", "decals_dds_scale"}   # 绝不属涂装系统，明确排除
            own = ext_factory is None
            if own:
                from data_extractor import GameExtractor
                ext = GameExtractor(str(game_dir), bin_folder=bin_folder)
            else:
                ext = ext_factory()
            try:
                for f in ext.list_files(["gui/exteriors/**/*"]):
                    path = getattr(f, "path", "") or ""
                    if not path.lower().endswith(".png"):
                        continue
                    parts = path.split("/")
                    if any(seg.lower() in bad for seg in parts):
                        continue
                    low = path.lower()
                    if "camouflages_colored" in low:
                        try:
                            exp = parts.index("expendable")
                            key = parts[exp + 1].lower()
                        except ValueError:
                            continue
                        if key not in icon_map or "color_0" in low:
                            icon_map[key] = path
                        continue
                    stem = path.rsplit("/", 1)[-1][:-4]
                    icon_map.setdefault(stem.lower(), path)
            finally:
                if own:
                    ext.close()
        except Exception:  # noqa: BLE001
            pass
        return icon_map

    @staticmethod
    def _resolve_camo_icon(icon_map: dict[str, str], name: str, index: str) -> str:
        """按 name 优先、index 次之匹配 gui/exteriors 图标路径。"""
        for key in (name or "", index or ""):
            k = key.strip().lower()
            if k and k in icon_map:
                return icon_map[k]
        return ""

    @staticmethod
    def _gui_ext_rel(icon_src: str) -> str | None:
        """从图标路径提取相对 gui/exteriors 的子路径（posix），用于按原始目录分文件夹存储。"""
        s = (icon_src or "").replace("\\", "/")
        marker = "gui/exteriors/"
        idx = s.find(marker)
        if idx >= 0:
            rel = s[idx + len(marker):].strip("/")
            return rel or None
        return None

    def _cache_camo_icon(self, game_dir, bin_folder: str, icon_src: str, name: str = "",
                         ext_factory=None) -> str:
        """把命中的选项图提取/复制到 data/camo_thumbs/<原始相对子目录>，返回相对 data 的路径。

        按原始 gui/exteriors 目录结构存放：camouflages/ · skins/ · permoflages/ · camouflages_colored/...
        如 camo_thumbs/camouflages_colored/expendable/<DIR>/color_0.png。
        icon_src 可能是 res_unpack 文件系统路径（绝对）或 pkg 内路径（相对、无盘符）。
        ext_factory: 可选，返回可复用 GameExtractor 的工厂，用于批量复制图标时避免每图标
        重建提取器（重载全部 IDX/文件树）卡死。
        """
        if not icon_src:
            return ""
        try:
            rel_sub = self._gui_ext_rel(icon_src)
            if not rel_sub:
                return ""
            dest = get_data_dir() / "camo_thumbs" / rel_sub
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = Path(icon_src)
            if src.is_absolute():
                if not src.exists():
                    return ""
                shutil.copyfile(src, dest)
            else:
                # pkg 内路径：复用传入工厂的提取器（避免每图标重载 IDX/文件树，防卡死）
                own = ext_factory is None
                if own:
                    from data_extractor import GameExtractor
                    ext = GameExtractor(str(game_dir), bin_folder=bin_folder)
                else:
                    ext = ext_factory()
                try:
                    # 精确路径优先直接用文件树 O(1) 取，避免 list_files 对整棵树做
                    # fnmatch 全扫描（每个图标一次 O(N)，数百个图标会显著拖慢）
                    e = ext.file_tree.get(icon_src)
                    if e is None or getattr(e, "is_directory", False):
                        hits = ext.list_files([icon_src])
                        if not hits:
                            return ""
                        e = hits[0]
                    data = ext.pkg_reader.read_file(e.volume.filename, e.file_info)
                    dest.write_bytes(data)
                finally:
                    if own:
                        ext.close()
            return dest.relative_to(get_data_dir()).as_posix()
        except Exception:  # noqa: BLE001
            return ""

    def get_skeleton_mounts(self, bin_folder: str, stem: str) -> dict:
        """某舰体骨架的 HP_ 挂点：{hp_name: (4,4) 行主序渲染空间矩阵（由解码值重建）}。"""
        import numpy as np
        out: dict = {}
        try:
            rows = self._conn.execute(
                "SELECT hp_name, pos_x, pos_y, pos_z, "
                "rot_qx, rot_qy, rot_qz, rot_qw, scale_x, scale_y, scale_z "
                "FROM skeleton_mounts WHERE bin_folder=? AND stem=?",
                (bin_folder, stem)).fetchall()
            for r in rows:
                out[r["hp_name"]] = self._quat_to_mat(
                    r["rot_qx"], r["rot_qy"], r["rot_qz"], r["rot_qw"],
                    r["scale_x"], r["scale_y"], r["scale_z"],
                    r["pos_x"], r["pos_y"], r["pos_z"])
        except (sqlite3.OperationalError, ValueError):
            out = {}
        return out

    def get_skeleton_bones(self, bin_folder: str, stem: str) -> dict:
        """某模型骨架的全部骨骼世界矩阵：{bone_name: (4,4)（由解码值重建）}。"""
        import numpy as np
        out: dict = {}
        try:
            rows = self._conn.execute(
                "SELECT bone_name, pos_x, pos_y, pos_z, "
                "rot_qx, rot_qy, rot_qz, rot_qw, scale_x, scale_y, scale_z "
                "FROM skeleton_bones WHERE bin_folder=? AND stem=?",
                (bin_folder, stem)).fetchall()
            for r in rows:
                out[r["bone_name"]] = self._quat_to_mat(
                    r["rot_qx"], r["rot_qy"], r["rot_qz"], r["rot_qw"],
                    r["scale_x"], r["scale_y"], r["scale_z"],
                    r["pos_x"], r["pos_y"], r["pos_z"])
        except (sqlite3.OperationalError, ValueError):
            out = {}
        return out

    def get_skeleton_bones_decoded(self, bin_folder: str, stem: str) -> dict:
        """某模型骨架的全部骨骼**解码后**数据（bind pose 世界）：{bone_name: dict}。

        每项含：pos=(x,y,z) 坐标 / rot=(qx,qy,qz,qw) 旋转四元数 / scale=(x,y,z) 缩放 /
        mat=(4,4) 世界矩阵（由解码值重建）。方便显示与其它功能直接使用坐标/方向。
        """
        import numpy as np
        out: dict = {}
        try:
            rows = self._conn.execute(
                "SELECT bone_name, pos_x, pos_y, pos_z, "
                "rot_qx, rot_qy, rot_qz, rot_qw, scale_x, scale_y, scale_z "
                "FROM skeleton_bones WHERE bin_folder=? AND stem=?",
                (bin_folder, stem)).fetchall()
            for r in rows:
                out[r["bone_name"]] = {
                    "pos": (r["pos_x"], r["pos_y"], r["pos_z"]),
                    "rot": (r["rot_qx"], r["rot_qy"], r["rot_qz"], r["rot_qw"]),
                    "scale": (r["scale_x"], r["scale_y"], r["scale_z"]),
                    "mat": self._quat_to_mat(
                        r["rot_qx"], r["rot_qy"], r["rot_qz"], r["rot_qw"],
                        r["scale_x"], r["scale_y"], r["scale_z"],
                        r["pos_x"], r["pos_y"], r["pos_z"]),
                }
        except (sqlite3.OperationalError, ValueError):
            out = {}
        return out

    def get_render_sets(self, bin_folder: str, geom_paths: list[str]) -> list[dict]:
        """某批 geometry 路径的全部渲染集（含整合模型共享记录）。

        返回 [{geom_path, shape, material, mfm, damage, skinned, nodes}]。
        nodes 为蒙皮调色板节点名列表（JSON 反序列化）。
        """
        out: list[dict] = []
        if not geom_paths:
            return out
        try:
            ph = ",".join("?" * len(geom_paths))
            rows = self._conn.execute(
                f"SELECT geom_path, shape, material, mfm, damage, skinned, nodes "
                f"FROM render_sets "
                f"WHERE bin_folder=? AND geom_path IN ({ph}) "
                f"ORDER BY geom_path, shape", (bin_folder, *geom_paths)).fetchall()
            for r in rows:
                nodes: list[str] = []
                if r["nodes"]:
                    try:
                        nodes = json.loads(r["nodes"])
                    except (ValueError, TypeError):
                        nodes = []
                out.append({
                    "geom_path": r["geom_path"], "shape": r["shape"],
                    "material": r["material"], "mfm": r["mfm"],
                    "damage": bool(r["damage"]),
                    "skinned": bool(r["skinned"]),
                    "nodes": nodes,
                })
        except sqlite3.OperationalError:
            out = []
        return out

    def get_shape_names(self, bin_folder: str) -> dict:
        """*.vertices 名字哈希 → 名字（LOD/crack 兜底跳过用；**只从 DB 读取**）。"""
        out: dict = {}
        try:
            rows = self._conn.execute(
                "SELECT hash, name FROM shape_names WHERE bin_folder=?",
                (bin_folder,)).fetchall()
            for r in rows:
                out[r["hash"]] = r["name"]
        except sqlite3.OperationalError:
            out = {}
        return out

    def get_mfm_textures(self, bin_folder: str) -> dict:
        """全部材质贴图映射：{mfm_path: texture_path（原始路径，含扩展名）}。"""
        out: dict = {}
        try:
            rows = self._conn.execute(
                "SELECT mfm_path, texture_path FROM mfm_textures WHERE bin_folder=?",
                (bin_folder,)).fetchall()
            for r in rows:
                out[r["mfm_path"]] = r["texture_path"]
        except sqlite3.OperationalError:
            out = {}
        return out

    def get_material_full(self, bin_folder: str, mfm_path: str) -> dict | None:
        """材质完整信息：{shader_id, family, material_hash, textures, indexed}。"""
        try:
            row = self._conn.execute(
                "SELECT shader_id, family, material_hash, textures, indexed FROM material_full "
                "WHERE bin_folder=? AND mfm_path=?", (bin_folder, mfm_path)).fetchone()
            if row is None:
                return None
            return {
                "shader_id": row["shader_id"],
                "family": row["family"],
                "material_hash": row["material_hash"],
                "textures": json.loads(row["textures"] or "{}"),
                "indexed": json.loads(row["indexed"] or "{}"),
            }
        except (sqlite3.OperationalError, ValueError, TypeError):
            return None

    @staticmethod
    def _material_family(shader_id: str) -> str:
        """shader_id（0xHHHHLLLL）高 16 位 → 技术族（INDEXED/PBS/其他）。"""
        from utils.asset_utils import material_family
        return material_family(shader_id)

    @staticmethod
    def _norm_vfs_path(p: str) -> str:
        """vfs 路径（/@content/... 或 /content/...）→ 规范化（content/...，与 render_sets 一致）。"""
        if p.startswith("/@"):
            return p[2:]
        if p.startswith("/"):
            return p[1:]
        return p

    # ── 工具 ────────────────────────────────────────────────

    def _render_sets_wg(self, data, off, db, self_id_idx, sdict,
                        bin_folder, rs_rows) -> None:
        """WG VisualPrototype 渲染集解析（0x70 记录 + 0x28 渲染集，wows-toolkit visual.rs）。

        WG 记录布局（与 Korabli 完全不同，不可复用 Korabli 的 +0x30/+0x38/+0x20）：
          +0x30 u64 merged_geometry_path_id
          +0x38 u8 underwater_model / +0x39 u8 abovewater_model /
          +0x3A u16 render_sets_count / +0x3C u8 lods_count
          +0x60 i64 render_sets_relptr（**record-relative**，i64 有符号）
        RenderSet 0x28 步长（parser_utils.rs parse_render_set_fields）：
          +0x00 u32 name_id(.vertices) / +0x04 u32 material_name_id /
          +0x08 u32 vertices_mapping_id / +0x0C u32 indices_mapping_id /
          +0x10 u64 material_mfm_path_id / +0x18 u8 skinned /
          +0x19 u8 nodes_count / +0x20 i64 node_name_ids_relptr（item-relative）
        """
        if off + 0x70 > len(data):
            return
        gp = self._path_of(struct.unpack_from('<Q', data, off + 0x30)[0],
                           db, self_id_idx)
        if not (gp and gp.endswith(".geometry")):
            return
        cnt = struct.unpack_from('<H', data, off + 0x3A)[0]
        rel = struct.unpack_from('<q', data, off + 0x60)[0]
        if not rel or cnt <= 0:
            return
        base = off + rel
        if base + cnt * 0x28 > len(data):
            return
        for k in range(cnt):
            o = base + k * 0x28
            shp = sdict.get(struct.unpack_from('<I', data, o)[0]) or ''
            # WG 渲染集名是形状名（xxShape，无后缀）；对应 .vertices 名 = xxShape.vertices。
            # 与 Korabli 不同（Korabli 渲染集 +0x00 直接就是 .vertices 名）。
            if shp and not shp.endswith('.vertices'):
                shp += '.vertices'
            if not shp.endswith('.vertices'):
                continue
            mat = sdict.get(struct.unpack_from('<I', data, o + 4)[0]) or ''
            mfm_h = struct.unpack_from('<Q', data, o + 0x10)[0]
            mfm = self._path_of(mfm_h, db, self_id_idx)
            damage = int('_crack_' in shp or '_lod' in shp or 'Crack' in mat)
            skinned = data[o + 0x18]
            ncnt = data[o + 0x19]
            nodes: list = []
            # ★ 所有条目都读 nodes（含 skinned=0 的刚性父子模型），供定位用。
            if ncnt:
                nrel = struct.unpack_from('<q', data, o + 0x20)[0]
                if nrel:
                    nabs = o + nrel
                    if nabs + ncnt * 4 <= len(data):
                        for j in range(ncnt):
                            nid = struct.unpack_from('<I', data, nabs + j * 4)[0]
                            nm = sdict.get(nid) or ''
                            if nm:
                                nodes.append(nm)
            rs_rows.append((bin_folder, gp, shp, mat, mfm, damage,
                            int(skinned), json.dumps(nodes)))

    def _populate_wg_skeleton(self, svc, db, sdict, self_id_idx, bin_folder,
                              vis_files, ext_files, skel_rows, bone_rows,
                              skel_failed) -> None:
        """WG 骨架：VisualPrototype nodes（基础骨架，含 HP_ 挂点）+ SkeletonExtender（MP_/SP_/EP_）。

        数据来源（wows-toolkit）：
          - Visual nodes（visual.rs）：+0x00 u32 nodes_count / +0x18 name_ids relptr /
            +0x20 matrices relptr / +0x28 parent_ids relptr（u16 索引，0xFFFF=根）。
            HP_ 炮塔挂点与全部骨架骨骼都在这（舰船按段 Bow/MidFront/MidBack/Stern 分 .visual）。
          - SkeletonExtender（skeleton_extender.rs，0x20 记录）：+0x00 u16 flag /
            +0x02 u16 node_count / +0x08 name_ids relptr / +0x18 matrices relptr。
            parent 为名字哈希（通常 Scene Root）→ local 即船空间；节点含 MP_/SP_/EP_。
        矩阵均为列主序 4x4 → 转行主序 → _decompose_mat（含反射 det=-1 处理）。
        """
        import numpy as np

        # 1) VisualPrototype nodes → HP_ 挂点 + 全部骨骼
        for f in vis_files:
            stem = self._stem_of_skeleton(f.path)
            if not stem:
                continue
            try:
                names, mats, parents = self._wg_visual_nodes(svc, f, sdict)
                if not names or not mats:
                    continue
                n = len(names)
                local = [np.array(mats[i], dtype=np.float32).reshape(4, 4).T
                         for i in range(len(mats))]
                w: list = [None] * len(local)
                for i in range(len(local)):
                    p = parents[i] if i < len(parents) else 65535
                    if p >= len(local) or p == i or p == 65535:
                        w[i] = local[i]
                    else:
                        w[i] = (w[p] if w[p] is not None
                                else np.eye(4, dtype=np.float32)) @ local[i]
                for i in range(n):
                    nm = names[i]
                    if not nm or i >= len(w) or w[i] is None:
                        continue
                    pos, quat, scale = self._decompose_mat(w[i])
                    bone_rows.append((bin_folder, stem, nm,
                                      float(pos[0]), float(pos[1]), float(pos[2]),
                                      quat[0], quat[1], quat[2], quat[3],
                                      scale[0], scale[1], scale[2]))
                    if nm.startswith("HP_"):
                        skel_rows.append((bin_folder, stem, nm,
                                          float(pos[0]), float(pos[1]), float(pos[2]),
                                          quat[0], quat[1], quat[2], quat[3],
                                          scale[0], scale[1], scale[2]))
            except Exception as exc:  # noqa: BLE001
                skel_failed.append(f"{f.path.rsplit('/', 1)[-1]}({exc})")

        # 2) SkeletonExtender → MP_/SP_/EP_ 挂点（local 即船空间）
        for f in ext_files:
            stem = self._stem_of_skeleton(f.path)
            if not stem:
                continue
            try:
                names, mats = self._wg_extender_nodes(svc, f, sdict)
                for i, nm in enumerate(names):
                    if not nm or i >= len(mats):
                        continue
                    mtx = np.array(mats[i], dtype=np.float32).reshape(4, 4).T
                    pos, quat, scale = self._decompose_mat(mtx)
                    bone_rows.append((bin_folder, stem, nm,
                                      float(pos[0]), float(pos[1]), float(pos[2]),
                                      quat[0], quat[1], quat[2], quat[3],
                                      scale[0], scale[1], scale[2]))
                    if nm.startswith(("MP_", "SP_", "EP_")):
                        skel_rows.append((bin_folder, stem, nm,
                                          float(pos[0]), float(pos[1]), float(pos[2]),
                                          quat[0], quat[1], quat[2], quat[3],
                                          scale[0], scale[1], scale[2]))
            except Exception as exc:  # noqa: BLE001
                skel_failed.append(f"{f.path.rsplit('/', 1)[-1]}({exc})")

    def _wg_visual_nodes(self, svc, f, sdict):
        """WG VisualPrototype nodes → (names, matrices, parents)。有界读取（不拷整段 blob）。"""
        import struct
        hdr = svc.vfs.open_file_len(f.path, 0x30)
        if len(hdr) < 0x30:
            return [], [], []
        ncnt = struct.unpack_from('<I', hdr, 0)[0]
        if ncnt <= 0 or ncnt > 5000:
            return [], [], []
        nids_ptr = struct.unpack_from('<q', hdr, 0x18)[0]
        mats_ptr = struct.unpack_from('<q', hdr, 0x20)[0]
        pids_ptr = struct.unpack_from('<q', hdr, 0x28)[0]
        need = 0x30
        if nids_ptr and ncnt:
            need = max(need, nids_ptr + ncnt * 4)
        if mats_ptr and ncnt:
            need = max(need, mats_ptr + ncnt * 64)
        if pids_ptr and ncnt:
            need = max(need, pids_ptr + ncnt * 2)
        data = svc.vfs.open_file_len(f.path, need + 16)
        names = []
        for i in range(ncnt):
            nm = sdict.get(struct.unpack_from('<I', data, nids_ptr + i * 4)[0]) or ''
            names.append(nm)
        mats = []
        for i in range(ncnt):
            mats.append(list(struct.unpack_from('<16f', data, mats_ptr + i * 64)))
        parents = [struct.unpack_from('<H', data, pids_ptr + i * 2)[0] for i in range(ncnt)]
        return names, mats, parents

    def _wg_extender_nodes(self, svc, f, sdict):
        """WG SkeletonExtender → (names, matrices)。列主序矩阵，local 即船空间。"""
        import struct
        hdr = svc.vfs.open_file_len(f.path, 0x20)
        if len(hdr) < 0x20:
            return [], []
        ncnt = struct.unpack_from('<H', hdr, 0x02)[0]
        if ncnt <= 0 or ncnt > 5000:
            return [], []
        nids_ptr = struct.unpack_from('<q', hdr, 0x08)[0]
        mats_ptr = struct.unpack_from('<q', hdr, 0x18)[0]
        need = 0x20
        if nids_ptr and ncnt:
            need = max(need, nids_ptr + ncnt * 4)
        if mats_ptr and ncnt:
            need = max(need, mats_ptr + ncnt * 64)
        data = svc.vfs.open_file_len(f.path, need + 16)
        names = []
        for i in range(ncnt):
            nm = sdict.get(struct.unpack_from('<I', data, nids_ptr + i * 4)[0]) or ''
            names.append(nm)
        mats = []
        for i in range(ncnt):
            mats.append(list(struct.unpack_from('<16f', data, mats_ptr + i * 64)))
        return names, mats

    @staticmethod
    def _stem_of_skeleton(path: str) -> str:
        """骨架路径 → 舰体 model_folder（倒数第二段）。

        例: /@content/gameplay/usa/ship/battleship/ASB107_North_Dakota_1953/
            ASB107_North_Dakota_1953_Bow_ports.visual → ASB107_North_Dakota_1953
        """
        parts = [p for p in path.replace("/@", "/").split("/") if p]
        return parts[-2] if len(parts) >= 2 else ""

    @staticmethod
    def _mat3_to_quat(rot) -> tuple:
        """3x3 旋转矩阵（行主序）→ 单位四元数 (qx, qy, qz, qw)。

        标准矩阵→四元数（Shepperd 方法，数值稳定，避免大角度分支问题）。
        """
        import numpy as np
        m = np.asarray(rot, dtype=np.float64)
        t = m[0, 0] + m[1, 1] + m[2, 2]
        if t > 0.0:
            s = np.sqrt(t + 1.0) * 2.0
            qw = 0.25 * s
            qx = (m[2, 1] - m[1, 2]) / s
            qy = (m[0, 2] - m[2, 0]) / s
            qz = (m[1, 0] - m[0, 1]) / s
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
            qw = (m[2, 1] - m[1, 2]) / s
            qx = 0.25 * s
            qy = (m[0, 1] + m[1, 0]) / s
            qz = (m[0, 2] + m[2, 0]) / s
        elif m[1, 1] > m[2, 2]:
            s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
            qw = (m[0, 2] - m[2, 0]) / s
            qx = (m[0, 1] + m[1, 0]) / s
            qy = 0.25 * s
            qz = (m[1, 2] + m[2, 1]) / s
        else:
            s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
            qw = (m[1, 0] - m[0, 1]) / s
            qx = (m[0, 2] + m[2, 0]) / s
            qy = (m[1, 2] + m[2, 1]) / s
            qz = 0.25 * s
        # 归一化（浮点误差防护）
        n = float(np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw))
        if n > 0.0:
            qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
        return (float(qx), float(qy), float(qz), float(qw))

    @staticmethod
    def _decompose_mat(mtx) -> tuple:
        """行主序 4x4 矩阵 → (pos(x,y,z), quat(qx,qy,qz,qw), scale(x,y,z))。

        pos 取平移列；scale 取三个基列的长度；旋转 = 归一化基列组成 3x3 再转四元数。

        ⚠️ 反射矩阵（det=-1，如挂载骨架的 Root_BlendBone = Z 镜像 diag(1,1,-1)）
        不能表示为旋转四元数（Shepperd 会给出伪结果，重建后丢失镜像 → 主炮/副炮
        方向翻转）。检测到 det<0 时翻转第一基列并把 scale_x 取负，使旋转部分为
        有效旋转（det=+1），重建时 _quat_to_mat 用负 scale 恢复镜像。
        """
        import numpy as np
        m = np.asarray(mtx, dtype=np.float64).reshape(4, 4)
        pos = (float(m[0, 3]), float(m[1, 3]), float(m[2, 3]))
        c0, c1, c2 = m[0:3, 0], m[0:3, 1], m[0:3, 2]
        sx = float(np.linalg.norm(c0))
        sy = float(np.linalg.norm(c1))
        sz = float(np.linalg.norm(c2))
        eps = 1e-8
        r0 = c0 / (sx if sx > eps else 1.0)
        r1 = c1 / (sy if sy > eps else 1.0)
        r2 = c2 / (sz if sz > eps else 1.0)
        r = np.column_stack([r0, r1, r2])
        # 反射矩阵：翻转第一基列 + scale_x 取负，恢复有效旋转（重建时负 scale 还原镜像）
        if np.linalg.det(r) < 0.0:
            sx = -sx
            r = np.column_stack([-r0, r1, r2])
        q = AssetsCacheService._mat3_to_quat(r)
        return pos, q, (sx, sy, sz)

    @staticmethod
    def _quat_to_mat(qx, qy, qz, qw, sx, sy, sz, px, py, pz):
        """解码值（四元数 + 缩放 + 位置）→ 行主序 4x4（渲染器/挂载定位用）。"""
        import numpy as np
        x, y, z, w = float(qx), float(qy), float(qz), float(qw)
        m = np.array([
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w), 0.0],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w), 0.0],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y), 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ], dtype=np.float32)
        m[0:3, 0] *= float(sx)
        m[0:3, 1] *= float(sy)
        m[0:3, 2] *= float(sz)
        m[0, 3] = float(px)
        m[1, 3] = float(py)
        m[2, 3] = float(pz)
        return np.ascontiguousarray(m, dtype=np.float32)

    @staticmethod
    def _path_of(h: int, db, self_id_idx) -> str:
        if h in (0, 0xFFFFFFFFFFFFFFFF):
            return ''
        i = self_id_idx.get(h)
        if i is None:
            return ''
        try:
            return db.reconstruct_path(i, self_id_idx)
        except Exception:  # noqa: BLE001
            return ''

    @staticmethod
    def _strings_dict(db) -> dict:
        """字符串表 → {hash: name}（渲染集 shape 反查）。"""
        from utils.asset_utils import build_strings_dict
        return build_strings_dict(db)

    @staticmethod
    def _to_render_row(mat: list) -> bytes | None:
        """列主序 16 float → 行主序 4x4 的 64 字节（与 geometry_service._matrix_to_render 一致）。"""
        from utils.asset_utils import mat_col_to_row_np
        try:
            return mat_col_to_row_np(mat).tobytes()
        except Exception:  # noqa: BLE001
            return None