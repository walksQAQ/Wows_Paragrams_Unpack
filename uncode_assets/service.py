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

from .decoders import (
    decode_material,
    decode_prototype_to_json,
    decode_record,
    parse_mfm_from_db,
)
from .errors import AssetsBinError
from .parser import PrototypeDatabase, parse_assets_bin
from .types import PrototypeType, can_decode, type_from_magic
from .vfs import AssetsBinVfs, VirtualFile

ASSETS_BIN_PATH = "content/assets.bin"


class AssetsBinService:
    """封装 assets.bin 的加载、解析、浏览与解码。"""

    def __init__(
        self,
        game_dir: Optional[str | Path] = None,
        assets_path: Optional[str | Path] = None,
        assets_bytes: Optional[bytes] = None,
        bin_folder: Optional[str] = None,
    ):
        """
        参数:
            game_dir: 游戏根目录（含 bin/ 和 res_packages/），
                      自动用 data_extractor 提取 content/assets.bin
            assets_path: 已解压的 assets.bin 文件路径
            assets_bytes: 内存中的 assets.bin 字节
            bin_folder: 游戏 bin 子版本号（继承主应用设置时传入）
        """
        self._db: Optional[PrototypeDatabase] = None
        self._vfs: Optional[AssetsBinVfs] = None
        self._game_dir: Optional[Path] = None
        self._bin_folder: Optional[str] = bin_folder
        self._from_cache: bool = False

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

        优先使用游戏目录下已解压的 res_unpack/content/assets.bin（秒开），
        否则用 data_extractor 从 .pkg 中提取（Kraken 解压 227MB，较慢）。
        """
        game_dir = Path(game_dir)
        # 优先使用已解压的明文 assets.bin
        unpacked = game_dir / "res_unpack" / "content" / "assets.bin"
        if unpacked.exists():
            self._game_dir = game_dir
            return self.load_file(unpacked)

        from data_extractor import GameExtractor

        extractor = GameExtractor(game_dir, bin_folder=self._bin_folder)
        try:
            entry = extractor.file_tree.get(ASSETS_BIN_PATH)
            if entry is None or entry.is_directory or entry.file_info is None:
                raise AssetsBinError(f"未在文件树中找到 {ASSETS_BIN_PATH}")
            data = extractor.pkg_reader.read_file(entry.volume.filename, entry.file_info)
        finally:
            extractor.close()

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
        self._db = parse_assets_bin(data)
        if cache_path is not None and Path(cache_path).exists():
            try:
                import pickle
                from .vfs import CACHE_VERSION
                with open(cache_path, "rb") as fh:
                    idx = pickle.load(fh)
                if idx.get("version") != CACHE_VERSION:
                    raise ValueError("缓存版本过旧，需重建")
                self._vfs = AssetsBinVfs.from_index(self._db, idx["files"], idx["dirs"])
                self._from_cache = True
                return
            except Exception:  # noqa: BLE001
                pass
        self._vfs = AssetsBinVfs(self._db)
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
    def game_dir(self) -> Optional[Path]:
        return self._game_dir

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
        return self.vfs.decode_file(path)

    def decode_path_json(self, path: str) -> str:
        """解码指定路径为 JSON 字符串。"""
        f = self.vfs.get_file(path)
        if f is None:
            raise AssetsBinError(f"虚拟文件不存在: {path}")
        if f.prototype_type is None:
            raise AssetsBinError(f"未知 prototype 类型: {path}")
        data = self.vfs.open_file(path)
        return decode_prototype_to_json(data, self.db, f.prototype_type)

    def can_decode_path(self, path: str) -> bool:
        """该虚拟文件是否有结构化解码器（对齐 wows-toolkit `can_decode_prototype`）。"""
        return can_decode(self.vfs.prototype_type(path))

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
