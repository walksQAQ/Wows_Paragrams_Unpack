"""AssetsBinService —— assets.bin 高层服务。

按规划文档的流程整合：
  步骤 1: 用 data_extractor 从游戏 .pkg 中提取 content/assets.bin 原始字节
          （莱服 Kraken 容器 / 寄服 raw-deflate 解压）
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
from .types import (PrototypeType, get_wows_type, model_meta as current_model_meta,
                    set_model_meta, set_wows_type, type_from_magic)
from .vfs import AssetsBinVfs, VirtualFile

ASSETS_BIN_PATH = "content/assets.bin"


def read_assets_bin_bytes(game_dir: str | Path, bin_folder: Optional[str] = None,
                          pkg_paths: Optional[set] = None) -> bytes:
    """从游戏 .pkg 现场读取 content/assets.bin 原始字节（**全内存，不落盘**）。

    这是 assets.bin 的唯一提取入口：不读任何既有解包产物、也不写临时文件，
    因此绝不会读到别的客户端/旧版本的残留。失败抛 :class:`AssetsBinError`。
    注意莱服 assets.bin 为 Kraken container，纯 Python 解码 220MB+ 较慢；
    寄服为 raw-deflate（zlib 解压），快得多。

    ‼ 传入 `pkg_paths`（一个 set）时，用同一个文件树填充 **PKG 内全部文件路径**，
    供 VFS 标记「无 prototype 的路径条目是否真存在于 PKG」（几万个字符串，约几十 MB）。
    """
    from data_extractor import GameExtractor

    extractor = GameExtractor(game_dir, bin_folder=bin_folder)
    try:
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
        model_meta: str = "",
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
            model_meta: `.model` 明文 `<metaData>` 的覆盖值（空串 = 用解码器默认常量）。
                      该字段不在二进制里，随 SDK 版本变化，由
                      :func:`uncode_assets.parse_rules.model_meta_for_rule` 按规则+版本给出；
                      ``wows_type='auto'`` 时由库内原型判定结果自动置位。
        """
        self._wows_type = (wows_type if wows_type in ("Wargaming", "Legacy") else "Lesta")
        #: `.model` metaData 覆盖值（空串 = 用默认）；auto 判定后自动置位
        self._model_meta = str(model_meta or "")
        #: 请求「自动」时，解析完 DB 后按原型魔数判定（见 load_bytes）
        self._wows_type_auto = (wows_type == "auto")
        #: 自动判定的规则（``Lesta`` / ``Wargaming`` / ``legacy``；判不出来为空串）
        self._auto_rule = ""
        # 构造期临时切换类型上下文，结束恢复：浏览器里选寄服/莱服不得污染主程序
        _prev_type = get_wows_type()
        _prev_meta = current_model_meta()
        set_wows_type(self._wows_type)
        set_model_meta(self._model_meta)
        try:
            self._db: Optional[PrototypeDatabase] = None
            self._vfs: Optional[AssetsBinVfs] = None
            self._game_dir: Optional[Path] = None
            self._bin_folder: Optional[str] = bin_folder
            self._from_cache: bool = False
            self._cache_path: Optional[Path] = None
            #: PKG 文件树路径集合（None = 未收集，资源节点不带 in_pkg 标记）
            self._pkg_paths: Optional[set] = pkg_paths

            if assets_bytes is not None:
                self.load_bytes(assets_bytes)
            elif assets_path is not None:
                self.load_file(assets_path)
            elif game_dir is not None:
                self.load_from_game(game_dir)
            else:
                raise ValueError("必须提供 game_dir / assets_path / assets_bytes 之一")
        finally:
            set_wows_type(_prev_type)
            set_model_meta(_prev_meta)

    # ── 加载 ─────────────────────────────────────────────

    def load_from_game(self, game_dir: str | Path) -> bytes:
        """步骤 1：从游戏 .pkg 中提取 content/assets.bin 并解析。

        用 data_extractor 从当前客户端 .pkg 现场提取到内存（Kraken 解压 220MB+，较慢），
        不落盘、不复用任何既有解包产物。
        """
        game_dir = Path(game_dir)
        data = read_assets_bin_bytes(game_dir, bin_folder=self._bin_folder,
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

        ``wows_type='auto'`` 时先解析 DB，再按「原型魔数」判断该库属于现代 Lesta、
        Wargaming 还是分家前的老客户端（``legacy``，见
        :func:`uncode_assets.parse_rules.detect_rule_from_db`），判不出来才退回默认 Lesta。
        """
        from .parse_rules import (detect_rule_from_db, layout_for_rule,
                                  model_meta_for_rule)
        from .types import wows_type_context

        self._cache_path = Path(cache_path) if cache_path is not None else None
        self._db = parse_assets_bin(data)
        if getattr(self, "_wows_type_auto", False):
            rule, reason = detect_rule_from_db(self._db)
            self._auto_rule = rule
            self._auto_rule_reason = reason
            if rule:
                self._wows_type = layout_for_rule(rule)
                self._model_meta = model_meta_for_rule(rule)

        with wows_type_context(self._wows_type, model_meta=self._model_meta):
            # 布局已最终确定（含 auto 判定结果）：把步长/记录区偏移锁定到 DB 条目上，
            # 之后在主线程/GUI 读 database_stats、resolve 时不会退回默认表。
            self._db.resolve_layout(self._wows_type)
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
                        self._db, idx["files"], idx["dirs"], wows_type=self._wows_type,
                        model_meta=self._model_meta)
                    self._from_cache = True
                    return
                except Exception:  # noqa: BLE001
                    pass
            self._vfs = AssetsBinVfs(self._db, wows_type=self._wows_type,
                                     pkg_paths=self._pkg_paths,
                                     model_meta=self._model_meta)
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
    def wows_type(self) -> str:
        """本服务实际使用的服务器类型（``Lesta`` / ``Wargaming``）。

        构造时传 ``wows_type='auto'`` 的话，这里是按库内原型魔数自动判定的结果。
        """
        return self._wows_type

    @property
    def legacy(self) -> bool:
        """``wows_type='auto'`` 判定出的规则是否属于旧布局（远古版本 / 寄服旧布局）。"""
        from .parse_rules import RULE_LEGACY, RULE_WG_OLD
        return getattr(self, "_auto_rule", "") in (RULE_LEGACY, RULE_WG_OLD)

    @property
    def wows_type_auto(self) -> bool:
        """构造时是否请求了「自动」判定。"""
        return getattr(self, "_wows_type_auto", False)

    @property
    def auto_rule(self) -> str:
        """``wows_type='auto'`` 自动判定出的规则（``Lesta`` / ``Wargaming`` / ``legacy``）。

        判不出来时为空串 —— 此时 :attr:`wows_type` 仍是退回的默认 Lesta。
        """
        return getattr(self, "_auto_rule", "")

    @property
    def auto_rule_reason(self) -> str:
        """``wows_type='auto'`` 时的判定依据说明（未自动判定为空串）。"""
        return getattr(self, "_auto_rule_reason", "")

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
        """解码指定路径的 prototype 记录（解码后恢复线程类型上下文）。"""
        from .types import wows_type_context
        with wows_type_context(self._wows_type):
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
        """解码指定路径为 JSON 字符串（解码后恢复线程类型上下文）。"""
        from .types import wows_type_context
        with wows_type_context(self._wows_type):
            f = self.vfs.get_file(path)
            if f is None:
                raise AssetsBinError(f"虚拟文件不存在: {path}")
            if f.prototype_type is None:
                raise AssetsBinError(f"未知 prototype 类型: {path}")
            data = self.vfs.open_file(path)
            return decode_prototype_to_json(data, self.db, f.prototype_type)

    def decode_material_by_path(self, path: str) -> dict:
        """按路径解码 MFM 材质（对齐 wows-toolkit `--parse-material` / `parse_mfm_from_db`）。"""
        from .types import wows_type_context
        with wows_type_context(self._wows_type):
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
