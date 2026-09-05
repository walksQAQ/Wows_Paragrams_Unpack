"""AssetsBinVfs —— 把 PrototypeDatabase 暴露为虚拟文件系统。

对应 wows-toolkit `data/assets_bin_vfs.rs`：把每个有 prototype 记录的路径
注册为虚拟文件（内容 = 记录起始 → blob 末尾的字节切片），并提供目录浏览。

内存友好：不复制数据，只保存 (blob_index, record_index, item_size) 引用，
读取时通过 PrototypeDatabase 切片返回。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from . import binary as B
from .decoders import decode_by_type, decode_skeleton, decode_visual
from .parser import BLOB_HEADER_SIZE, PrototypeDatabase, PrototypeLocation
from .types import PrototypeType, get_wows_type, set_wows_type, type_from_magic

#: VFS 索引缓存版本号：目录树/索引构建逻辑变更时 +1，使旧缓存自动失效
# 2026-09-05：Visual 记录纠偏仅限 Lesta（WG 跳过）+ 解码服务器上下文恢复 → +1
CACHE_VERSION = 5


@dataclass
class VirtualFile:
    """虚拟文件：一条 prototype 记录。"""
    path: str
    blob_index: int
    record_index: int
    item_size: int
    byte_length: int
    prototype_type: Optional[PrototypeType]

    @property
    def filename(self) -> str:
        return self.path.rstrip('/').rsplit('/', 1)[-1]


class AssetsBinVfs:
    """基于 PrototypeDatabase 的只读虚拟文件系统。"""

    def __init__(self, db: PrototypeDatabase, wows_type: str = ""):
        self._db = db
        self._wows_type = "Wargaming" if wows_type == "Wargaming" else "Lesta"
        self._files: Dict[str, VirtualFile] = {}
        self._dirs: Dict[str, List[str]] = {}
        self._build_index()

    # ── 构建索引 ─────────────────────────────────────────

    def _build_index(self) -> None:
        db = self._db
        paths = db.paths_storage
        n = len(paths)
        self_id_index = db.build_self_id_index()

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
            self._register_dirs(dirs, full_path)

        # 第二遍：无 prototype 的路径条目（如 .geometry 等存在 PKG 里的资源）
        # **只注册父目录、不注册叶子**，避免遮蔽 PKG 同名文件——
        # 对齐 wows-toolkit build_index 的行为，目录结构更完整。
        for i, entry in enumerate(paths):
            if db.lookup_r2p(entry.self_id) is not None:
                continue
            raw_path = full_paths[i]
            if not raw_path:
                continue
            self._register_parent_dirs(dirs, "/" + raw_path)

        self._dirs = {k: sorted(v) for k, v in dirs.items()}

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
    def _register_parent_dirs(dirs: Dict[str, set], full_path: str) -> None:
        """只注册路径的所有祖先目录（不含叶子本身），供无 prototype 的文件使用。"""
        pos = 1  # 跳过前导 '/'
        while True:
            idx = full_path.find('/', pos)
            if idx == -1:
                break
            parent = full_path[:pos].rstrip('/') if pos > 1 else "/"
            dirs.setdefault(parent, set()).add(full_path[pos:idx])
            pos = idx + 1

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
                f.prototype_type.name if f.prototype_type else None)
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
        vfs._dirs = dirs_index
        vfs._files = {}
        for p, t in files_index.items():
            blob_index, record_index, item_size, byte_length, _type_name = t
            vfs._files[p] = VirtualFile(
                path=p, blob_index=blob_index, record_index=record_index,
                item_size=item_size, byte_length=byte_length,
                prototype_type=type_from_magic(db.databases[blob_index].prototype_magic),
            )
        return vfs

    # ── 查询接口 ─────────────────────────────────────────

    def file_count(self) -> int:
        return len(self._files)

    def dir_count(self) -> int:
        return len(self._dirs)

    def has_file(self, path: str) -> bool:
        return self._normalize(path) in self._files

    def get_file(self, path: str) -> Optional[VirtualFile]:
        return self._files.get(self._normalize(path))

    def prototype_type(self, path: str) -> Optional[PrototypeType]:
        """返回路径对应的 prototype 类型（无则 None）。

        对齐 wows-toolkit `AssetsBinVfs::prototype_type`。
        """
        f = self._files.get(self._normalize(path))
        return f.prototype_type if f else None

    def list_dir(self, dir_path: str = "/") -> List[str]:
        key = self._normalize(dir_path)
        if key == "":
            key = "/"
        return sorted(self._dirs.get(key, []))

    def is_dir(self, path: str) -> bool:
        key = self._normalize(path)
        return key in self._dirs

    def list_entries(self, dir_path: str = "/") -> Tuple[List[str], List[VirtualFile]]:
        """返回指定目录下的 (子目录名列表, 文件列表)。用于 GUI 树懒加载。"""
        key = self._normalize(dir_path)
        if key == "":
            key = "/"
        names = self._dirs.get(key, [])
        subdirs: List[str] = []
        files: List[VirtualFile] = []
        for name in names:
            if key == "/":
                child_path = "/" + name
            else:
                child_path = key + "/" + name
            if child_path in self._dirs:
                subdirs.append(name)
            elif child_path in self._files:
                files.append(self._files[child_path])
        return sorted(subdirs), sorted(files, key=lambda f: f.filename)

    def all_files(self) -> Iterator[VirtualFile]:
        return iter(self._files.values())

    def open_file(self, path: str) -> bytes:
        """返回虚拟文件的字节内容（记录起始 → blob 末尾）。"""
        f = self.get_file(path)
        if f is None:
            raise KeyError(f"虚拟文件不存在: {path}")
        loc = PrototypeLocation(f.blob_index, f.record_index)
        return self._db.get_prototype_data(loc, f.item_size)

    def open_file_len(self, path: str, length: int) -> bytes:
        """返回虚拟文件记录起始起的 length 字节（有界切片，避免整 blob 尾部拷贝）。"""
        f = self.get_file(path)
        if f is None:
            raise KeyError(f"虚拟文件不存在: {path}")
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
        data = self.open_file(path)
        record_base = 16 + f.record_index * f.item_size
        result = decode_by_type(data, self._db, f.prototype_type, record_base)
        # 合并 Skeleton(blob1) + Visual(blob2)，同 rec 索引
        if f.prototype_type is not None:
            try:
                if f.prototype_type.name == "VisualPrototype":
                    skel = self._find_blob(self._db, "SkeletonPrototype")
                    if skel is not None and f.record_index < skel.record_count:
                        sdata = skel.data[16 + f.record_index * skel.item_size:]
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
    def _normalize(path: str) -> str:
        path = path.replace('\\', '/')
        if not path.startswith('/'):
            path = '/' + path
        return path.rstrip('/')
