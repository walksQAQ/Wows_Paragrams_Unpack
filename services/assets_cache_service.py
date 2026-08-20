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
ASSETS_SCHEMA_VERSION = 7


class AssetsCacheService:
    """assets.bin 数据缓存（独立数据库 assets_data.db，线程安全）。"""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = get_data_dir() / "assets_data.db"
        self._db_path = Path(db_path)
        self._local = threading.local()

    # ── 连接 ────────────────────────────────────────────────

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
        try:
            from utils.path_utils import get_bundled_dir
            sql_path = get_bundled_dir() / "resources" / "database" / "assets_database.sql"
            if sql_path.exists():
                sql_text = sql_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            sql_text = None
        if not sql_text:
            try:
                from PySide6.QtCore import QFile, QIODevice
                qf = QFile(":/resources/database/assets_database.sql")
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
        import struct as _s
        c1 = 0xCC9E2D51
        c2 = 0x1B873593
        length = len(data)
        h1 = seed
        for i in range(length // 4):
            k1 = _s.unpack_from('<I', data, i * 4)[0]
            k1 = (k1 * c1) & 0xFFFFFFFF
            k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
            k1 = (k1 * c2) & 0xFFFFFFFF
            h1 ^= k1
            h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
            h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF
        tail = data[length // 4 * 4:]
        k1 = 0
        if len(tail) >= 3:
            k1 ^= tail[2] << 16
        if len(tail) >= 2:
            k1 ^= tail[1] << 8
        if len(tail) >= 1:
            k1 ^= tail[0]
            k1 = (k1 * c1) & 0xFFFFFFFF
            k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
            k1 = (k1 * c2) & 0xFFFFFFFF
            h1 ^= k1
        h1 ^= length
        h1 ^= h1 >> 16
        h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
        h1 ^= h1 >> 13
        h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
        h1 ^= h1 >> 16
        return h1

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
        svc = AssetsBinService(assets_path=assets_path)
        db = svc.db

        def _p(msg: str) -> None:
            if progress_cb:
                try:
                    progress_cb(msg)
                except Exception:  # noqa: BLE001
                    pass

        try:
            counts = {"skeleton": 0, "render_sets": 0, "mfm_textures": 0,
                      "material_full": 0, "skeleton_bones": 0, "shape_names": 0}
            # 共用：字符串 dict + self_id 索引（渲染集/材质解析都要用）
            sdict = self._strings_dict(db)
            self_id_idx = db.build_self_id_index()
            # 表已全量清空重建，无需按 bin_folder 逐表 DELETE；直接写入元信息
            self._conn.execute(
                "INSERT INTO meta(bin_folder, game_version, wows_type, created_at) "
                "VALUES (?,?,?,datetime('now'))",
                (bin_folder, game_version, wows_type))

            _p("清空旧缓存并写入元信息，扫描 VFS 全树...")

            # 收集 SkeletonPrototype 与 MaterialPrototype 文件（一次遍历全树）
            skel_files: list = []
            mfm_files: list = []
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

            _p(f"解析舰体骨架挂点与骨骼（{len(skel_files)} 个骨架文件）...")

            # 1) 骨架挂点（SkeletonPrototype，含 *_ports.visual 的 HP_ 挂点）
            #    + 完整骨骼世界矩阵（bind pose 按 parent 累积，引用小零件/Root_BlendBone 用）
            import numpy as np
            skel_rows: list[tuple] = []
            bone_rows: list[tuple] = []
            for f in skel_files:
                stem = self._stem_of_skeleton(f.path)
                if not stem:
                    continue
                try:
                    sk = svc.decode_skeleton_path(f.path)
                except Exception:  # noqa: BLE001
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
                    for ri in range(nrec):
                        off = BLOB_HEADER_SIZE + ri * isize
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
                            if skinned and ncnt:
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
            for f in mfm_files:
                try:
                    data = svc.vfs.open_file_len(f.path, 0x90)
                except Exception:  # noqa: BLE001
                    continue
                if len(data) < 0x88:
                    continue
                pc = B.read_u16(data, 0x00)
                if not pc:
                    continue
                shader_id = B.read_u32(data, 0x08)
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
                    need = max(need, vec4_ptr + pc * 16 + 196 * 16 + 64)
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
                    nm = sdict.get(raw_name & 0xFFFFFFFF) or ""
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
                        nm = sdict.get(nid & 0xFFFFFFFF) or f"vec4_{j}"
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
                                json.dumps(textures), json.dumps(indexed)))
            if mfm_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO mfm_textures "
                    "(bin_folder, mfm_path, texture_path) VALUES (?,?,?)", mfm_rows)
            counts["mfm_textures"] = len(mfm_rows)
            del mfm_rows
            if mf_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO material_full "
                    "(bin_folder, mfm_path, shader_id, family, textures, indexed) "
                    "VALUES (?,?,?,?,?,?)", mf_rows)
            counts["material_full"] = len(mf_rows)
            del mf_rows

            self._conn.commit()
            return counts
        finally:
            svc.close()

    # ── 查询（3D 查看器用）─────────────────────────────────

    def has_data(self, bin_folder: str) -> bool:
        """该客户端版本是否已有缓存数据。"""
        try:
            row = self._conn.execute(
                "SELECT 1 FROM meta WHERE bin_folder=?", (bin_folder,)).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False

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
        """材质完整信息：{shader_id, family, textures:{name: 原始路径}, indexed:{name:[[...]]}}。"""
        try:
            row = self._conn.execute(
                "SELECT shader_id, family, textures, indexed FROM material_full "
                "WHERE bin_folder=? AND mfm_path=?", (bin_folder, mfm_path)).fetchone()
            if row is None:
                return None
            return {
                "shader_id": row["shader_id"],
                "family": row["family"],
                "textures": json.loads(row["textures"] or "{}"),
                "indexed": json.loads(row["indexed"] or "{}"),
            }
        except (sqlite3.OperationalError, ValueError, TypeError):
            return None

    @staticmethod
    def _material_family(shader_id: str) -> str:
        """shader_id（0xHHHHLLLL）高 16 位 → 技术族（INDEXED/PBS/其他）。"""
        try:
            family = (int(shader_id, 16) >> 16) & 0xFFFF
        except Exception:  # noqa: BLE001
            family = 0
        if family == 0x0009:
            return "indexed"
        if family == 0x0005:
            return "pbs"
        return "other"

    @staticmethod
    def _norm_vfs_path(p: str) -> str:
        """vfs 路径（/@content/... 或 /content/...）→ 规范化（content/...，与 render_sets 一致）。"""
        if p.startswith("/@"):
            return p[2:]
        if p.startswith("/"):
            return p[1:]
        return p

    # ── 工具 ────────────────────────────────────────────────

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
        out: dict = {}
        try:
            from uncode_assets import binary as B
            hmap = db.strings.offsets_map
            cap = hmap.capacity
            stride = hmap.bucket_stride
            vstride = hmap.value_stride
            buckets = hmap.buckets
            values = hmap.values
            sdata = db.strings.string_data
            read64 = B.read_u64
            read32 = B.read_u32
            read_str = B.read_null_terminated_string
            for idx in range(cap):
                off = idx * stride
                key = read64(buckets, off)
                if stride >= 16:
                    if read64(buckets, off + 8) == 0:
                        continue
                else:
                    if key == 0:
                        continue
                str_off = read32(values, idx * vstride)
                if str_off < len(sdata):
                    s = read_str(sdata, str_off)
                    if s:
                        out[key & 0xFFFFFFFF] = s
        except Exception:  # noqa: BLE001
            pass
        return out

    @staticmethod
    def _to_render_row(mat: list) -> bytes | None:
        """列主序 16 float → 行主序 4x4 的 64 字节（与 geometry_service._matrix_to_render 一致）。"""
        try:
            import numpy as np
            m = np.ascontiguousarray(
                np.array(mat, dtype=np.float32).reshape(4, 4).T, dtype=np.float32)
            return m.tobytes()
        except Exception:  # noqa: BLE001
            return None
