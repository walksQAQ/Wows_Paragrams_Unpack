"""AssetsBinService —— assets.bin 高层服务。

按规划文档的流程整合：
  步骤 1: 用 data_extractor 从游戏 .pkg 中提取 content/assets.bin 原始字节（Kraken 解压）
  步骤 2: 解析 PrototypeDatabase
  步骤 3: 构建 AssetsBinVfs（按路径浏览）
  步骤 4: 解码各 prototype 类型 → JSON
  步骤 6: CLI / 批量导出

内存约束：assets.bin 解压后约 227MB，解析全程 <2GB。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from . import binary as _B
from .decoders import (
    decode_material,
    decode_prototype_to_json,
    decode_skeleton,
    parse_mfm_from_db,
)
from .errors import AssetsBinError
from .parser import PrototypeDatabase, parse_assets_bin
from .types import PrototypeType, set_wows_type, type_from_magic
from .vfs import AssetsBinVfs, VirtualFile

ASSETS_BIN_PATH = "content/assets.bin"

#: 已编译 fx 的资源后缀（一个 .fx 对应一份 .win.dx11.fxo）
FXO_SUFFIX = ".win.dx11.fxo"


def collect_fx_catalog(file_tree, out: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """从 pkg 文件树构建 fx 短名 → 完整路径。

    运行时 fx 名以**短名**形式保存（如 `flag.fx`），完整路径由
    `shaders/<目录>/<短名>` 拼接；客户端内没有静态的短名→路径表，
    只能从 `.fxo` 清单反推。同名多目录时值为路径列表。

    `file_tree` 为 `GameExtractor.file_tree`（键为 VFS 路径）。
    """
    cat: Dict[str, object] = {} if out is None else out
    for p in file_tree:
        if not p.endswith(FXO_SUFFIX):
            continue
        fx = p[:-len(FXO_SUFFIX)] + ".fx"
        short = fx.rsplit("/", 1)[-1]
        prev = cat.get(short)
        if prev is None:
            cat[short] = fx
        elif isinstance(prev, list):
            if fx not in prev:
                prev.append(fx)
        elif prev != fx:
            cat[short] = [prev, fx]
    return cat


def read_assets_bin_bytes(game_dir: str | Path, bin_folder: Optional[str] = None,
                          fx_catalog: Optional[Dict[str, object]] = None,
                          pkg_paths: Optional[set] = None) -> bytes:
    """从游戏 .pkg 现场读取 content/assets.bin 原始字节（**全内存，不落盘**）。

    这是 assets.bin 的唯一提取入口：不读任何既有解包产物、也不写临时文件，
    因此绝不会读到别的客户端/旧版本的残留。失败抛 :class:`AssetsBinError`。
    注意 assets.bin 为 Kraken container，解压 220MB+ 较慢（纯 Python 解码）。

    传入 `fx_catalog` 时，顺便用同一个 extractor 的文件树填充
    `fx 短名 → 完整 .fx 路径`（不额外读盘）。
    ‼ 传入 `pkg_paths`（一个 set）时，用同一个文件树填充 **PKG 内全部文件路径**，
    供 VFS 标记「无 prototype 的路径条目是否真存在于 PKG 」（几万个字符串，约几十 MB）。
    """
    from data_extractor import GameExtractor

    extractor = GameExtractor(game_dir, bin_folder=bin_folder)
    try:
        if fx_catalog is not None:
            try:
                collect_fx_catalog(extractor.file_tree, fx_catalog)
            except Exception:  # noqa: BLE001
                pass
        if pkg_paths is not None:
            try:
                pkg_paths.update(extractor.file_tree.keys())
            except Exception:  # noqa: BLE001
                pass
        entry = extractor.file_tree.get(ASSETS_BIN_PATH)
        if entry is None or entry.is_directory or entry.file_info is None:
            raise AssetsBinError(f"未在文件树中找到 {ASSETS_BIN_PATH}")
        data = extractor.pkg_reader.read_file(entry.volume.filename, entry.file_info)
    finally:
        extractor.close()
    if not data:
        raise AssetsBinError("assets.bin 解压结果为空")
    return data


class AssetsBinService:
    """封装 assets.bin 的加载、解析、浏览与解码。"""

    def __init__(
        self,
        game_dir: Optional[str | Path] = None,
        assets_path: Optional[str | Path] = None,
        assets_bytes: Optional[bytes] = None,
        bin_folder: Optional[str] = None,
        wows_type: str = "",
        pkg_paths: Optional[set] = None,
    ):
        """
        参数:
            game_dir: 游戏根目录（含 bin/ 和 res_packages/），
                      自动用 data_extractor 提取 content/assets.bin
            assets_path: 已解压的 assets.bin 文件路径
            assets_bytes: 内存中的 assets.bin 字节
            bin_folder: 游戏 bin 子版本号（继承主应用设置时传入）
            wows_type: 服务器类型（'Wargaming'→WG 10 类型表；其余→Korabli 12 类型表）。
                      需在解析**之前**传入，内部按服务器设置类型表上下文。
            pkg_paths: 可选的 PKG 文件路径集合（调用方传入空 set 即启用收集）。
                      传入后 VFS 会为「无 prototype 的路径条目」标记 `in_pkg`，
                      用于区分「PKG 中确有该文件」与「仅是 assets.bin 路径残留」。
        """
        self._wows_type = "Wargaming" if wows_type == "Wargaming" else "Lesta"
        set_wows_type(self._wows_type)
        self._db: Optional[PrototypeDatabase] = None
        self._vfs: Optional[AssetsBinVfs] = None
        self._game_dir: Optional[Path] = None
        self._bin_folder: Optional[str] = bin_folder
        self._from_cache: bool = False
        self._cache_path: Optional[Path] = None
        #: PKG 文件树路径集合（None = 未收集，资源节点不带 in_pkg 标记）
        self._pkg_paths: Optional[set] = pkg_paths
        #: fx 短名 → 完整路径（仅从游戏目录加载时填充）
        self._fx_catalog: Dict[str, object] = {}

        if assets_bytes is not None:
            self.load_bytes(assets_bytes)
        elif assets_path is not None:
            self.load_file(assets_path)
        elif game_dir is not None:
            self.load_from_game(game_dir)
        else:
            raise ValueError("必须提供 game_dir / assets_path / assets_bytes 之一")

    # ── 加载 ─────────────────────────────────────────────

    def load_from_game(self, game_dir: str | Path) -> bytes:
        """步骤 1：从游戏 .pkg 中提取 content/assets.bin 并解析。

        用 data_extractor 从当前客户端 .pkg 现场提取到内存（Kraken 解压 220MB+，较慢），
        不落盘、不复用任何既有解包产物。
        """
        game_dir = Path(game_dir)
        data = read_assets_bin_bytes(game_dir, bin_folder=self._bin_folder,
                                     fx_catalog=self._fx_catalog,
                                     pkg_paths=self._pkg_paths)
        self._game_dir = game_dir
        self.load_bytes(data)
        return data

    def load_file(self, path: str | Path) -> bytes:
        """从已解压的 assets.bin 文件加载。"""
        path = Path(path)
        if not path.exists():
            raise AssetsBinError(f"assets.bin 文件不存在: {path}")
        data = path.read_bytes()
        self.load_bytes(data, cache_path=self._cache_path_for(path))
        return data

    @staticmethod
    def _cache_path_for(source_path: Path) -> Optional[Path]:
        """根据文件大小 + mtime 生成稳定缓存路径（assets.bin 旁边的 .uncode_cache/）。"""
        try:
            st = source_path.stat()
        except OSError:
            return None
        key = hashlib.sha1(f"{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:16]
        return source_path.parent / ".uncode_cache" / f"idx_{key}.pkl"

    def load_bytes(self, data: bytes, cache_path: Optional[str | Path] = None) -> None:
        """步骤 2+3：解析并构建 VFS。

        cache_path 存在且有效时，用缓存索引快速恢复 VFS（跳过耗时的
        路径重建与目录构建）；否则正常构建并写缓存。
        """
        self._cache_path = Path(cache_path) if cache_path is not None else None
        self._db = parse_assets_bin(data)
        if cache_path is not None and Path(cache_path).exists():
            try:
                import pickle
                from .types import get_wows_type
                from .vfs import CACHE_VERSION
                with open(cache_path, "rb") as fh:
                    idx = pickle.load(fh)
                if idx.get("version") != CACHE_VERSION:
                    raise ValueError("缓存版本过旧，需重建")
                # 缓存按服务器隔离：item_size 依赖服务器类型表（WG 0x78 vs Korabli 0x88），
                # 混用会错位（Material/Visual/Model 记录偏移全错）。不匹配则重建。
                if idx.get("wows_type") != get_wows_type():
                    raise ValueError("缓存服务器与当前不符，需重建")
                self._vfs = AssetsBinVfs.from_index(
                    self._db, idx["files"], idx["dirs"], wows_type=self._wows_type)
                self._from_cache = True
                return
            except Exception:  # noqa: BLE001
                pass
        self._vfs = AssetsBinVfs(self._db, wows_type=self._wows_type,
                                 pkg_paths=self._pkg_paths)
        self._from_cache = False
        if cache_path is not None:
            try:
                self._vfs.save_index(cache_path)
            except Exception:  # noqa: BLE001
                pass

    # ── 属性 ─────────────────────────────────────────────

    @property
    def db(self) -> PrototypeDatabase:
        if self._db is None:
            raise AssetsBinError("尚未加载 assets.bin")
        return self._db

    @property
    def vfs(self) -> AssetsBinVfs:
        if self._vfs is None:
            raise AssetsBinError("尚未加载 assets.bin")
        return self._vfs

    @property
    def cache_path(self) -> Optional[Path]:
        """本次加载使用（或将写入）的 .uncode_cache 索引缓存路径；无缓存为 None。"""
        return self._cache_path

    @property
    def game_dir(self) -> Optional[Path]:
        return self._game_dir

    @property
    def fx_catalog(self) -> Dict[str, object]:
        """fx 短名 → 完整 `.fx` 路径；直接打开 assets.bin 文件时为空字典。"""
        return self._fx_catalog

    # ── 概览 ─────────────────────────────────────────────

    def info(self) -> dict:
        """数据库概览。"""
        db = self.db
        return {
            "magic": f"0x{db.header.magic:08X}",
            "version": f"0x{db.header.version:08X}",
            "checksum": f"0x{db.header.checksum:08X}",
            "architecture": f"0x{db.header.architecture:04X}",
            "endianness": f"0x{db.header.endianness:04X}",
            "strings_capacity": db.strings.offsets_map.capacity,
            "r2p_capacity": db.resource_to_prototype_map.capacity,
            "paths_count": len(db.paths_storage),
            "databases_count": len(db.databases),
            "file_count": self.vfs.file_count(),
            "resource_count": self.vfs.resource_count(),
            "dir_count": self.vfs.dir_count(),
        }

    def database_stats(self) -> List[dict]:
        """各 blob 的统计信息。"""
        out = []
        for i, entry in enumerate(self.db.databases):
            out.append({
                "blob_index": i,
                "magic": f"0x{entry.prototype_magic:08X}",
                "type": entry.prototype_name,
                "checksum": f"0x{entry.prototype_checksum:08X}",
                "size": entry.size,
                "record_count": entry.record_count,
                "item_size": entry.item_size,
            })
        return out

    # ── 浏览 ─────────────────────────────────────────────

    def list_dir(self, dir_path: str = "/") -> List[str]:
        """列出虚拟目录下的子项。"""
        return self.vfs.list_dir(dir_path)

    def find_files(self, keyword: str = "", max_results: int = 100) -> List[VirtualFile]:
        """按路径关键字查找虚拟文件。"""
        kw = keyword.lower()
        matches = []
        for f in self.vfs.all_files():
            if kw in f.path.lower():
                matches.append(f)
                if max_results and len(matches) >= max_results:
                    break
        return matches

    # ── 解码 ─────────────────────────────────────────────

    def resolve(self, path: str) -> Tuple[dict, str]:
        """解析路径 → (位置信息, 完整路径)。"""
        location, full_path = self.db.resolve_path(path)
        entry = self.db.databases[location.blob_index]
        return {
            "blob_index": location.blob_index,
            "record_index": location.record_index,
            "type": entry.prototype_name,
            "item_size": entry.item_size,
            "full_path": full_path,
        }, full_path

    def decode_path(self, path: str) -> dict:
        """解码指定路径的 prototype 记录。"""
        set_wows_type(self._wows_type)
        return self.vfs.decode_file(path)

    def decode_skeleton_path(self, path: str) -> dict:
        """快速解码骨架：只读取记录头 + 所需 OOL 区，避免复制整段 blob 尾部。

        背景：Skeleton blob 达 73MB，原 decode_path 每次解码都返回
        「记录起始 → blob 末尾」的整段尾部切片，批量解码（如回填炮位朝向）
        会复制数十 MB × 数千次。此处按骨架记录头（64B）里的 relptr 计算
        所需 OOL 长度，做有界切片后解码；异常时回退到完整解码保证正确。
        """
        try:
            f = self.vfs.get_file(path)
            if f is None:
                raise AssetsBinError(f"虚拟文件不存在: {path}")
            hdr = self.vfs.open_file_len(path, 0x40)
            if len(hdr) < 0x40:
                raise AssetsBinError(f"骨架数据过短: {path}")
            count = _B.read_u32(hdr, 0x00)
            rot_count = _B.read_u32(hdr, 0x04)
            need = 0x40
            # (relptr 字段偏移, 元素字节数, 元素个数)
            arrays = [
                (0x08, 4, count),   # name_map_name_ids u32
                (0x10, 2, count),   # name_map_node_ids u16
                (0x18, 4, count),   # name_ids u32
                (0x20, 16, count),  # matrices float4x4
                (0x38, 2, count),   # parent_ids u16
                (0x30, 2, count),   # rotation_limits_ids u16
            ]
            for off, esize, c in arrays:
                if c > 0:
                    # ⚠️ 2026-08-19：relptr 为 u64（旧 u32 读低 4 字节碰巧对，但需一致）
                    rel = _B.read_u64(hdr, off)
                    need = max(need, rel + esize * c)
            if rot_count > 0:
                rel = _B.read_u64(hdr, 0x28)  # rotation_limits Vec4×2，32B/条
                need = max(need, rel + 32 * rot_count)
            data = self.vfs.open_file_len(path, need + 16)  # 留安全余量
            return decode_skeleton(data, self.db)
        except Exception:
            return self.decode_path(path)

    def decode_path_json(self, path: str) -> str:
        """解码指定路径为 JSON 字符串。"""
        set_wows_type(self._wows_type)
        f = self.vfs.get_file(path)
        if f is None:
            raise AssetsBinError(f"虚拟文件不存在: {path}")
        if f.prototype_type is None:
            raise AssetsBinError(f"未知 prototype 类型: {path}")
        data = self.vfs.open_file(path)
        return decode_prototype_to_json(data, self.db, f.prototype_type)

    def decode_material_by_path(self, path: str) -> dict:
        """按路径解码 MFM 材质（对齐 wows-toolkit `--parse-material` / `parse_mfm_from_db`）。"""
        f = self.vfs.get_file(path)
        if f is None:
            raise AssetsBinError(f"虚拟文件不存在: {path}")
        if f.prototype_type is None or f.prototype_type.name != "MaterialPrototype":
            raise AssetsBinError(f"路径不是 MaterialPrototype: {path} ({f.prototype_type})")
        data = self.vfs.open_file(path)
        return decode_material(data, self.db)

    def decode_mfm_by_self_id(self, self_id: int) -> Optional[dict]:
        """按 selfId 反查并解码 MFM 材质（对齐 wows-toolkit `parse_mfm_from_db`）。"""
        return parse_mfm_from_db(self.db, self_id)

    # ── 批量导出 ─────────────────────────────────────────

    def dump(
        self,
        output_dir: str | Path,
        type_filter: Optional[str] = None,
        max_records: Optional[int] = None,
        extension: str = ".json",
    ) -> Dict[str, int]:
        """把虚拟文件批量解码导出为 JSON。

        参数:
            output_dir: 输出目录
            type_filter: 仅导出该类型（如 "VisualPrototype"、"Material"）
            max_records: 最多导出的记录数
            extension: 输出文件扩展名
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        stats: Dict[str, int] = {}
        count = 0
        for f in self.vfs.all_files():
            if f.prototype_type is None:  # PKG 资源节点：assets.bin 中无记录可导出
                continue
            if type_filter:
                tname = f.prototype_type.name if f.prototype_type else ""
                if type_filter.lower() not in tname.lower():
                    continue
            if max_records is not None and count >= max_records:
                break

            rel = f.path.lstrip('/')
            out_path = output_dir / (rel + extension)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                out_path.write_text(self.decode_path_json(f.path), encoding='utf-8')
                stats[f.prototype_type.name if f.prototype_type else "Unknown"] = \
                    stats.get(f.prototype_type.name if f.prototype_type else "Unknown", 0) + 1
                count += 1
            except Exception as e:  # 单条失败不中断
                print(f"[ERROR] 解码失败 {f.path}: {e}", file=sys.stderr)

        return stats

    # ── 释放 ─────────────────────────────────────────────

    def close(self) -> None:
        """释放引用（帮助 GC 回收大块内存）。"""
        self._db = None
        self._vfs = None
