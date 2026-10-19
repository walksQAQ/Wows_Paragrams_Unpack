"""AssetsBinVfs —— 把 PrototypeDatabase 暴露为虚拟文件系统。

对应 wows-toolkit `data/assets_bin_vfs.rs`：把每个有 prototype 记录的路径
注册为虚拟文件（内容 = 记录起始 → blob 末尾的字节切片），并提供目录浏览。

内存友好：不复制数据，只保存 (blob_index, record_index, item_size) 引用，
读取时通过 PrototypeDatabase 切片返回。
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from . import binary as B
from .decoders import decode_by_type, decode_skeleton, decode_visual
from .errors import AssetsBinError
from .parser import BLOB_HEADER_SIZE, PrototypeDatabase, PrototypeLocation
from .types import PrototypeType, get_wows_type, set_wows_type, type_from_magic

#: VFS 索引缓存版本号：目录树/索引构建逻辑变更时 +1，使旧缓存自动失效
# 2026-09-05：Visual 记录纠偏仅限 Lesta（WG 跳过）+ 解码服务器上下文恢复 → +1
# 2026-10-20：无 prototype 的路径条目改为注册「PKG 资源」节点（可列表/点击提示）→ +1
CACHE_VERSION = 7


@dataclass
class VirtualFile:
    """虚拟文件：一条 prototype 记录，或一条「仅存在于 PKG」的资源路径条目。

    `prototype_type is None` ⇒ 该路径在 assets.bin 里**没有** prototype 记录，
    原始文件直接存放在客户端 PKG 中（`.dds`/`.geometry`/`.fxo` 等）。
    这类节点只用于补全目录结构、供搜索定位，不能解码（见 `is_resource`）。
    """
    path: str
    blob_index: int
    record_index: int
    item_size: int
    byte_length: int
    prototype_type: Optional[PrototypeType]
    #: 仅资源节点有意义：路径是否在当前客户端 PKG 文件树中确认存在（None = 未核对）
    in_pkg: Optional[bool] = None
    #: Visual 记录是否自带同一 rec 索引的 Skeleton 半条（Lesta 的 .visual 拆分存储）
    merged_skeleton: bool = False

    @property
    def filename(self) -> str:
        return self.path.rstrip('/').rsplit('/', 1)[-1]

    @property
    def is_resource(self) -> bool:
        """是否是「PKG 内原始存储、assets.bin 无记录」的资源节点。"""
        return self.prototype_type is None


class AssetsBinVfs:
    """基于 PrototypeDatabase 的只读虚拟文件系统。"""

    #: 本应带 prototype 记录的路径后缀：路径表里有、却查不到 r2p ⇒ 残留/别名条目，
    #: 既不当资源列出，也不为其建目录（否则会凭空出现「空目录」）。
    _RESIDUAL_SUFFIXES = (
        ".mfm", ".visual", ".model", ".model_fbx", ".primitives", ".contours",
        ".trail", ".vfx", ".effect_preset", ".skeleton_extender", ".skel_ext",
        ".point_light", ".velocity_field",
    )

    def __init__(self, db: PrototypeDatabase, wows_type: str = "",
                 pkg_paths: Optional[set] = None):
        """
        pkg_paths: 当前客户端 PKG 文件树的路径集合（可选）。传入后，资源节点会带
            `in_pkg` 标记（精确区分「PKG 中确有该文件」与「仅是路径表残留」）。
        """
        self._db = db
        self._wows_type = "Wargaming" if wows_type == "Wargaming" else "Lesta"
        self._pkg_paths = pkg_paths
        self._files: Dict[str, VirtualFile] = {}
        self._dirs: Dict[str, List[str]] = {}
        #: 逻辑路径 → 原始路径列表（Lesta 的 @content 与 content 合并显示）
        self._logical_files: Dict[str, List[str]] = {}
        self._build_index()

    # ── 构建索引 ─────────────────────────────────────────

    def _build_index(self) -> None:
        db = self._db
        paths = db.paths_storage
        n = len(paths)
        self_id_index = db.build_self_id_index()
        pkg_paths = self._pkg_paths

        # 用 BFS 沿 parent 链传播完整路径（无前导 '/'），O(N) 而非每条 O(深度)。
        children: Dict[int, List[int]] = {}
        for i, entry in enumerate(paths):
            children.setdefault(entry.parent_id, []).append(i)

        full_paths: List[Optional[str]] = [None] * n
        queue = deque(i for i, entry in enumerate(paths) if entry.parent_id not in self_id_index)
        for i in queue:
            full_paths[i] = paths[i].name
        while queue:
            i = queue.popleft()
            base = full_paths[i]
            for c in children.get(paths[i].self_id, ()):
                if full_paths[c] is None:
                    name = paths[c].name
                    full_paths[c] = (base + "/" + name) if base else name
                    queue.append(c)
        # 兜底：环/孤立节点
        for i in range(n):
            if full_paths[i] is None:
                full_paths[i] = paths[i].name

        # 目录子项用 set 累积（O(1) 去重），构建完再转排序列表
        dirs: Dict[str, set] = {}
        dirs.setdefault("/", set())

        # ── Korabli ST 服 r2p→visual 记录偏移修正索引 ────────────────────
        # ST assets.bin 的 r2p 表对 VisualPrototype（blob 2）的记录索引错乱
        # （rec 应为 N，r2p 却指向别船的记录），但 Model/Skeleton 正常。正确记录
        # 可按「visual 同目录 geometry 文件名 → geometry self_id 索引」反查：
        #   1) vis_geom_to_rec: {geometry self_id: 引用它的 visual 记录}
        #      （扫描 visual blob +0x20/+0x60 两处引用，首个命中）
        #   2) dir_geos: {目录: {去 .geometry 名: self_id}}（复用 full_paths O(1)）
        # 无偏移的正式服 assets.bin 自校验通过，record_index 原样返回。
        # ⚠️ 仅对 Lesta/Korabli 生效：WG VisualPrototype 为 0x70 布局且
        #   geometry@+0x30，此处硬编码 +0x40/+0x20 会读错字段，故 WG 跳过。
        is_lesta = self._wows_type != "Wargaming"
        vis_blob: Optional[object] = None
        vis_geom_to_rec: Dict[int, int] = {}
        dir_geos: Dict[str, Dict[str, int]] = {}
        if is_lesta:
            for b in db.databases:
                t = type_from_magic(b.prototype_magic)
                if t is not None and t.name == "VisualPrototype":
                    vis_blob = b
                    break
            if vis_blob is not None:
                vsize = vis_blob.item_size
                vdata = vis_blob.data
                for ri in range(vis_blob.record_count):
                    voff = BLOB_HEADER_SIZE + ri * vsize
                    if voff + 0x40 > len(vdata):
                        break
                    vrec = vdata[voff:voff + 0x40]
                    # ⚠️ 2026-08-19 修正：VisualPrototype item=0x40（非 0x80），
                    # 每条记录唯一 geometry（+0x20）+ primitives（+0x28），无 +0x60。
                    h = B.read_u64(vrec, 0x20)
                    if h not in vis_geom_to_rec:
                        i = self_id_index.get(h)
                        if i is not None:
                            gp = full_paths[i]
                            if gp and gp.endswith(".geometry"):
                                vis_geom_to_rec[h] = ri
            for i, e in enumerate(paths):
                if not e.name.endswith(".geometry"):
                    continue
                fp = full_paths[i]
                if not fp:
                    continue
                dir_geos.setdefault(fp.rsplit('/', 1)[0], {})[
                    e.name[:-len(".geometry")]] = e.self_id

        for i, entry in enumerate(paths):
            value = db.lookup_r2p(entry.self_id)
            if value is None:
                continue
            blob_index = (value & 0xFF) // 4
            record_index = (value >> 8) & 0xFFFFFF
            if blob_index >= len(db.databases):
                continue
            db_entry = db.databases[blob_index]
            if record_index >= db_entry.record_count:
                continue
            proto_type = type_from_magic(db_entry.prototype_magic)
            if proto_type is None:
                continue
            item_size = db_entry.item_size
            raw_path = full_paths[i]
            if not raw_path:
                continue
            if proto_type.name == "VisualPrototype" and vis_blob is not None:
                record_index = self._correct_visual_record(
                    raw_path, record_index, vis_blob, vis_geom_to_rec,
                    dir_geos, self_id_index, full_paths)
            full_path = "/" + raw_path
            record_offset = BLOB_HEADER_SIZE + record_index * item_size
            byte_length = len(db_entry.data) - record_offset
            if byte_length <= 0:
                continue
            self._files[full_path] = VirtualFile(
                path=full_path,
                blob_index=blob_index,
                record_index=record_index,
                item_size=item_size,
                byte_length=byte_length,
                prototype_type=proto_type,
            )
            # 逻辑路径 → 原始路径（@content 与 content 合并显示）；get_file/list_entries 依赖
            self._logical_files.setdefault(
                self._logical_path(full_path), []).append(full_path)
            # 目录树用**逻辑路径**：Lesta 的 @content/@helpers/@vehicles
            # 与无 @ 的同名根是同一逻辑路径的两套资源（骨架 vs 视觉/模型）。
            self._register_dirs(dirs, self._logical_path(full_path))

        # 第二遍：无 prototype 的路径条目 —— 原始文件直接存在客户端 PKG 里
        # （.dds/.geometry/.fxo 等），注册为「资源节点」并照常补齐目录树。
        # 旧实现只登记祖先目录名、不登记叶子，导致叶子所在目录拿不到 key：
        # `list_entries` 把该名字当作「既非目录也非文件」丢弃，于是出现
        # 「目录存在但展开为空 / 纹理目录整个不出现」。
        # 本应带记录却查不到 r2p 的条目（.mfm/.visual/.primitives、Lesta 的
        # `@content/...` 重复树）视为残留/别名，不列出（也就不再凭空产生空目录）。
        for i, entry in enumerate(paths):
            if db.lookup_r2p(entry.self_id) is not None:
                continue
            raw_path = full_paths[i]
            if not raw_path or self._is_residual_path(raw_path):
                continue
            full_path = "/" + raw_path
            if full_path in self._files:
                continue
            self._files[full_path] = VirtualFile(
                path=full_path,
                blob_index=-1,
                record_index=-1,
                item_size=0,
                byte_length=0,
                prototype_type=None,
                in_pkg=(None if pkg_paths is None else raw_path in pkg_paths),
            )
            self._logical_files.setdefault(
                self._logical_path(full_path), []).append(full_path)
            self._register_dirs(dirs, self._logical_path(full_path))

        self._dirs = {k: sorted(v) for k, v in dirs.items()}
        self._mark_visual_skeleton()

    def _mark_visual_skeleton(self) -> None:
        """标记「Visual 记录另有同 rec 索引的 Skeleton 半条」的条目。

        Lesta（Korabli）把 .visual 拆成两条记录：
          - `@content/.../X.visual` → SkeletonPrototype（节点树/骨骼 bind pose，blob1）
          - `content/.../X.visual`  → VisualPrototype（渲染集，blob2）
        两者**同 rec 索引**（全库 39793 对 100% 相等），因此目录里可按逻辑路径
        合并为一个节点（解码 Visual 时已自动附带骨架）。
        """
        skel = {(self._logical_path(p), f.record_index)
                for p, f in self._files.items()
                if f.prototype_type is not None
                and f.prototype_type.name == "SkeletonPrototype"}
        if not skel:
            return
        for p, f in self._files.items():
            if f.prototype_type is not None and f.prototype_type.name == "VisualPrototype":
                f.merged_skeleton = (self._logical_path(p), f.record_index) in skel

    @staticmethod
    def _merge_visual_skeleton(group: List["VirtualFile"]) -> List["VirtualFile"]:
        """同一目录里同名（同逻辑路径）的 Skeleton/Visual 两条记录只留一个节点。

        保留 VisualPrototype（解码时已合并骨架）；仅有骨架、没有对应 Visual 的
        记录照旧保留，不丢数据。
        """
        if len(group) < 2:
            return group
        vis = [g for g in group if g.prototype_type is not None
               and g.prototype_type.name == "VisualPrototype"]
        if not vis:
            return group
        vis_recs = {g.record_index for g in vis}
        out: List["VirtualFile"] = list(vis)
        for g in group:
            if g in vis:
                continue
            if (g.prototype_type is not None
                    and g.prototype_type.name == "SkeletonPrototype"
                    and g.record_index in vis_recs):
                continue  # 与 Visual 同 rec 的骨架半条：已被合并
            out.append(g)
        return out

    @classmethod
    def _is_residual_path(cls, rel_path: str) -> bool:
        """路径表里「本该有 prototype 记录、却查不到」的残留/别名条目。"""
        low = rel_path.lower()
        if low.startswith("@"):  # Lesta 的 `@content/...` 重复树（骨架/视觉别名）
            return True
        return low.endswith(cls._RESIDUAL_SUFFIXES)

    @staticmethod
    def _correct_visual_record(rel_path: str, record_index: int, vis_blob,
                               vis_geom_to_rec: Dict[int, int],
                               dir_geos: Dict[str, Dict[str, int]],
                               self_id_index: Dict[int, int],
                               full_paths: List[Optional[str]]) -> int:
        """自校验并修正 Korabli ST 服 r2p→visual 记录索引。

        r2p 表对 VisualPrototype 的记录索引错乱（指向别船记录）；这里校验
        r2p rec 引用的 geometry 是否与 visual 同目录同名（含 `_ports` 等变体），
        不符则按「同目录 geometry 文件名 → geometry self_id 反查正确 rec」修正。
        正式服（无偏移）校验通过，record_index 原样返回。
        """
        if record_index >= vis_blob.record_count:
            return record_index
        vsize = vis_blob.item_size
        voff = BLOB_HEADER_SIZE + record_index * vsize
        vrec = vis_blob.data[voff:voff + 0x40]
        vdir = rel_path.rsplit('/', 1)[0]
        vname = rel_path.rsplit('/', 1)[-1][:-len(".visual")]

        # 1) r2p rec 已正确：引用 geometry 与 visual 同目录且文件名匹配
        #    ⚠️ 2026-08-19 修正：item=0x40，唯一 geometry@+0x20（无 +0x60）。
        h = B.read_u64(vrec, 0x20)
        i = self_id_index.get(h)
        if i is None:
            return record_index
        gp = full_paths[i]
        if not gp or not gp.endswith(".geometry"):
            return record_index
        gdir = gp.rsplit('/', 1)[0]
        gname = gp.rsplit('/', 1)[-1][:-len(".geometry")]
        if gdir == vdir and (gname == vname or gname.startswith(vname + "_")
                             or vname.startswith(gname)):
            return record_index

        # 2) 修正：同目录 geometry 候选（精确名优先，其次前缀变体）→ self_id 索引
        cands = dir_geos.get(vdir)
        if not cands:
            return record_index
        gid = cands.get(vname)
        if gid is None:
            for nm, sid in cands.items():
                if nm.startswith(vname + "_") or vname.startswith(nm):
                    gid = sid
                    break
        if gid is None:
            return record_index
        fixed = vis_geom_to_rec.get(gid)
        return fixed if fixed is not None else record_index

    @staticmethod
    def _register_dirs(dirs: Dict[str, set], full_path: str) -> None:
        """把路径的所有祖先目录与子项写入 set 累积结构（key 无尾斜杠）。"""
        pos = 1  # 跳过前导 '/'
        while True:
            idx = full_path.find('/', pos)
            if idx == -1:
                break
            parent = full_path[:pos].rstrip('/') if pos > 1 else "/"
            dirs.setdefault(parent, set()).add(full_path[pos:idx])
            pos = idx + 1
        # 叶子（文件或末级目录）
        parent = full_path[:pos].rstrip('/') if pos > 1 else "/"
        dirs.setdefault(parent, set()).add(full_path[pos:])

    # ── 索引持久化缓存 ─────────────────────────────────

    def save_index(self, cache_path: str | Path) -> None:
        """把构建好的 (文件索引, 目录索引) 序列化到磁盘，供二次加载秒开。"""
        import pickle
        from pathlib import Path
        cache_path = Path(cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        files_index = {
            p: (f.blob_index, f.record_index, f.item_size, f.byte_length,
                f.prototype_type.name if f.prototype_type else None, f.in_pkg)
            for p, f in self._files.items()
        }
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            pickle.dump({"version": CACHE_VERSION,
                         "wows_type": self._wows_type,
                         "files": files_index, "dirs": self._dirs},
                        fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(cache_path)

    @classmethod
    def from_index(cls, db: PrototypeDatabase, files_index: dict, dirs_index: dict,
                   wows_type: str = "") -> "AssetsBinVfs":
        """从缓存索引恢复 VFS（跳过耗时的路径重建/目录构建）。

        调用方需先校验 idx["version"] == CACHE_VERSION。
        """
        vfs = cls.__new__(cls)
        vfs._db = db
        vfs._wows_type = "Wargaming" if wows_type == "Wargaming" else "Lesta"
        vfs._pkg_paths = None
        vfs._dirs = dirs_index
        vfs._files = {}
        for p, t in files_index.items():
            blob_index, record_index, item_size, byte_length, type_name, in_pkg = t
            proto = (type_from_magic(db.databases[blob_index].prototype_magic)
                     if type_name is not None else None)
            vfs._files[p] = VirtualFile(
                path=p, blob_index=blob_index, record_index=record_index,
                item_size=item_size, byte_length=byte_length,
                prototype_type=proto, in_pkg=in_pkg,
            )
        vfs._logical_files = {}
        for raw in vfs._files:
            vfs._logical_files.setdefault(cls._logical_path(raw), []).append(raw)
        vfs._mark_visual_skeleton()
        return vfs

    # ── 查询接口 ─────────────────────────────────────────

    def file_count(self) -> int:
        return len(self._files)

    def resource_count(self) -> int:
        """其中「PKG 内原始存储、assets.bin 无记录」的资源节点数。"""
        return sum(1 for f in self._files.values() if f.prototype_type is None)

    def dir_count(self) -> int:
        return len(self._dirs)

    def has_file(self, path: str) -> bool:
        return self.get_file(path) is not None

    def get_file(self, path: str) -> Optional[VirtualFile]:
        key = self._normalize(path)
        vf = self._files.get(key)
        if vf is not None:
            return vf
        raws = self._logical_files.get(self._logical_path(key)) or []
        if not raws:
            return None
        # 逻辑命中多个（@ + 非 @）：优先普通路径，保持既有语义
        for raw in raws:
            if not raw.startswith("/@"):
                return self._files.get(raw)
        return self._files.get(raws[0])

    def prototype_type(self, path: str) -> Optional[PrototypeType]:
        """返回路径对应的 prototype 类型（无则 None）。

        对齐 wows-toolkit `AssetsBinVfs::prototype_type`。
        """
        f = self.get_file(path)
        return f.prototype_type if f else None

    def list_dir(self, dir_path: str = "/") -> List[str]:
        key = self._normalize(dir_path)
        if key == "":
            key = "/"
        return sorted(self._dirs.get(key, []))

    def pkg_has(self, path: str) -> Optional[bool]:
        """该路径（PKG 内相对路径，无前导 '/'）是否存在于 PKG 文件树。

        未提供 PKG 文件树（直接打开 assets.bin 文件）时返回 None。
        """
        if self._pkg_paths is None:
            return None
        return path.lstrip("/") in self._pkg_paths


    def is_dir(self, path: str) -> bool:
        return self._logical_path(path) in self._dirs

    def list_entries(self, dir_path: str = "/") -> Tuple[List[str], List[VirtualFile]]:
        """返回指定目录下的 (子目录名列表, 文件列表)。用于 GUI 树懒加载。

        目录按**逻辑路径**合并（@content 与 content 同一棵树）；同名不同
        prototype 类型的文件会全部返回（GUI 用类型后缀区分）。
        """
        key = self._logical_path(dir_path)
        if key == "":
            key = "/"
        names = self._dirs.get(key, [])
        subdirs: List[str] = []
        files: List[VirtualFile] = []
        for name in names:
            child_path = ("/" + name) if key == "/" else key + "/" + name
            if child_path in self._dirs:
                subdirs.append(name)
            elif child_path in self._logical_files:
                group = [self._files.get(raw) for raw in self._logical_files[child_path]]
                group = [g for g in group if g is not None]
                files.extend(self._merge_visual_skeleton(group))
        return (sorted(subdirs),
                sorted(files, key=lambda f: (f.filename, f.path)))

    def all_files(self) -> Iterator[VirtualFile]:
        return iter(self._files.values())

    def open_file(self, path: str) -> bytes:
        """返回虚拟文件的字节内容（记录起始 → blob 末尾）。"""
        f = self.get_file(path)
        if f is None:
            raise KeyError(f"虚拟文件不存在: {path}")
        if f.prototype_type is None:
            raise AssetsBinError(
                f"{path} 不是 assets.bin 的 prototype 记录（原始文件在 PKG 中）")
        loc = PrototypeLocation(f.blob_index, f.record_index)
        return self._db.get_prototype_data(loc, f.item_size)

    def open_file_len(self, path: str, length: int) -> bytes:
        """返回虚拟文件记录起始起的 length 字节（有界切片，避免整 blob 尾部拷贝）。"""
        f = self.get_file(path)
        if f is None:
            raise KeyError(f"虚拟文件不存在: {path}")
        if f.prototype_type is None:
            raise AssetsBinError(
                f"{path} 不是 assets.bin 的 prototype 记录（原始文件在 PKG 中）")
        loc = PrototypeLocation(f.blob_index, f.record_index)
        return self._db.get_prototype_data_len(loc, f.item_size, length)

    def decode_file(self, path: str) -> dict:
        """解码虚拟文件为结构化 dict。

        ⚠️ 2026-08-19：.visual 记录**骨架在 blob1(Skeleton)、视觉在 blob2(Visual)、
        同 rec 索引**——浏览器显示时合并两者（ModsSDK 明文 visual 同时含节点树+渲染集）。

        assets.bin 一般在后台线程加载，而 GUI 点击解码发生在主线程；此处恢复
        VFS 所属服务器类型，避免 thread-local 回退为 Lesta 导致 WG 记录按 Lesta
        布局解析（geometry/primitives/渲染集全部错位）。
        """
        set_wows_type(self._wows_type)
        f = self.get_file(path)
        if f is None:
            raise KeyError(f"虚拟文件不存在: {path}")
        if f.prototype_type is None:
            raise AssetsBinError(
                f"{path} 不是 assets.bin 的 prototype 记录（原始文件在 PKG 中，请解包查看）")
        data = self.open_file(path)
        record_base = 16 + f.record_index * f.item_size
        result = decode_by_type(data, self._db, f.prototype_type, record_base)
        # 合并 Skeleton(blob1) + Visual(blob2)，同 rec 索引
        if f.prototype_type is not None:
            try:
                if f.prototype_type.name == "VisualPrototype":
                    skel = self._find_blob(self._db, "SkeletonPrototype")
                    if skel is not None:
                        rec = self._skeleton_record_for(path, f.record_index, skel)
                        if rec is not None and rec < skel.record_count:
                            sdata = skel.data[16 + rec * skel.item_size:]
                            result["skeleton"] = decode_skeleton(sdata, self._db)
                elif f.prototype_type.name == "SkeletonPrototype":
                    vis = self._find_blob(self._db, "VisualPrototype")
                    if vis is not None and f.record_index < vis.record_count:
                        vdata = vis.data[16 + f.record_index * vis.item_size:]
                        result["visual"] = decode_visual(vdata, self._db)
            except Exception:  # noqa: BLE001
                pass
        return result

    @staticmethod
    def _find_blob(db, name: str):
        """按类型名找 database blob（用于跨 blob 合并骨架/视觉）。"""
        for b in db.databases:
            t = type_from_magic(b.prototype_magic)
            if t is not None and t.name == name:
                return b
        return None

    @staticmethod
    def _main_visual_path(path: str) -> Optional[str]:
        """`.../lods/X_lod2.visual` → `.../X.visual`；非 LOD 返回 None。"""
        if "/lods/" not in path:
            return None
        base = path.replace("/lods/", "/", 1)
        return re.sub(r"_lod\d+(\.visual)$", r"\1", base)

    def _skeleton_record_for(self, path: str, rec: int, skel) -> Optional[int]:
        """visual 对应的骨架记录索引（LOD 为空时回退到主 visual）。

        LOD visual 的骨架记录常为空（count=0），官方 Mod SDK 明文里 LOD 的
        节点树就是主视觉的节点树（抽样 400 个：312 个完全一致，其余仅主视觉
        多出 wire/hide 等节点，LOD 从未出现独有节点）。

        注意 LOD 的 visual rec 索引可能超出骨架记录数（LOD visual 多、骨架少），
        这种情况同样回退到主 visual。
        """
        if rec < skel.record_count:
            if B.read_u32(skel.data[16 + rec * skel.item_size:], 0) > 0:
                return rec
        main_path = self._main_visual_path(path)
        if not main_path:
            return None
        main = self.get_file(main_path)
        if main is None or main.record_index >= skel.record_count:
            return None
        mrec = main.record_index
        if B.read_u32(skel.data[16 + mrec * skel.item_size:], 0) > 0:
            return mrec
        return None

    @staticmethod
    def _normalize(path: str) -> str:
        path = path.replace('\\', '/')
        if not path.startswith('/'):
            path = '/' + path
        return path.rstrip('/')

    @staticmethod
    def _logical_path(path: str) -> str:
        """去掉顶层 ``@`` 前缀（Lesta 的 @content 与 content 是同一逻辑路径）。

        路径表里 ``@content/...`` 存放 SkeletonPrototype（骨架），
        ``content/...`` 存放 Visual/Model/Material 等；两者共用同一逻辑路径，
        目录树应合并显示（文件仍按原始路径精确定位）。
        """
        p = path.replace("\\", "/")
        if not p.startswith("/"):
            p = "/" + p
        parts = [x for x in p.split("/") if x]
        if parts and parts[0].startswith("@"):
            parts[0] = parts[0][1:]
        return "/" + "/".join(parts) if parts else "/"

    @staticmethod
    def logical_path(path: str) -> str:
        """公开接口：原始路径 → 目录树逻辑路径。"""
        return AssetsBinVfs._logical_path(path)
