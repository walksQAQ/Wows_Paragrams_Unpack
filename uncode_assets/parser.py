"""PrototypeDatabase（assets.bin）解析器。

逐行移植 wows-toolkit `crates/wowsunpack/src/models/assets_bin.rs` 的标量逻辑，
但类型表采用 Korabli 实测（见 types.py）。

内存约束：全程 <2GB。本解析器只保存对原始 bytes 的**视图切片**，
不复制大数组；字符串/路径等只在需要时才解码。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import binary as B
from .errors import (
    InvalidMagicError,
    OutOfBoundsError,
    ParseError,
    PathNotFoundError,
    PrototypeOutOfRangeError,
    UnsupportedVersionError,
)
from .types import item_size_for_blob, type_from_magic, type_from_blob_index

BWDB_MAGIC: int = 0x42574442
BWDB_VERSION: int = 0x01010000
BODY_BASE: int = 0x10
BLOB_HEADER_SIZE: int = 16

# Body header 内各 section 的偏移（相对 body_base）
STRINGS_OFFSET = 0x00
R2P_OFFSET = 0x28
PATHS_OFFSET = 0x40
DATABASES_OFFSET = 0x50


# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class Header:
    magic: int
    version: int
    checksum: int
    architecture: int
    endianness: int


@dataclass
class HashmapSection:
    """通用哈希表段：buckets + values 并行数组。"""
    capacity: int
    buckets: bytes
    values: bytes
    bucket_stride: int
    value_stride: int


@dataclass
class StringsSection:
    offsets_map: HashmapSection
    string_data: bytes
    string_data_base: int = 0

    def get_string_by_id(self, hash_id: int) -> Optional[str]:
        """用字符串哈希（MurmurHash3_x86_32 的 u32 值）反查字符串名。

        offsetsMap 的 buckets 为 8B/项（仅 u64 key，空槽 key=0），
        与 r2p 的 16B（key+occupancy）不同，故按 bucket_stride 自适应。
        """
        hmap = self.offsets_map
        cap = hmap.capacity
        if cap == 0:
            return None
        stride = hmap.bucket_stride
        slot = (hash_id & 0xFFFFFFFF) % cap
        for i in range(cap):
            idx = (slot + i) % cap
            bucket_off = idx * stride
            key = B.read_u64(hmap.buckets, bucket_off)
            if stride >= 16:
                occ = B.read_u64(hmap.buckets, bucket_off + 8)
                if occ == 0:
                    return None
            else:
                if key == 0:
                    return None
            if (key & 0xFFFFFFFF) == (hash_id & 0xFFFFFFFF):
                value_off = idx * hmap.value_stride
                str_off = B.read_u32(hmap.values, value_off)
                if str_off >= len(self.string_data):
                    return None
                return B.read_null_terminated_string(self.string_data, str_off)
        return None

    def get_string_or_hex(self, hash_id: int) -> str:
        s = self.get_string_by_id(hash_id)
        return s if s is not None else f"0x{hash_id & 0xFFFFFFFF:08X}"


@dataclass
class PathEntry:
    self_id: int
    parent_id: int
    name: str


@dataclass
class DatabaseEntry:
    prototype_magic: int
    prototype_checksum: int
    size: int
    data: bytes            # 整个 blob（含 16B 头）
    record_count: int
    blob_index: int = -1   # 在数据库数组中的序号

    @property
    def item_size(self) -> int:
        return item_size_for_blob(self.blob_index, self.prototype_magic)

    @property
    def prototype_name(self) -> str:
        t = type_from_magic(self.prototype_magic)
        return t.name if t else f"0x{self.prototype_magic:08X}"


@dataclass
class PrototypeLocation:
    blob_index: int
    record_index: int


@dataclass
class PrototypeDatabase:
    """解析后的 assets.bin 内容。"""
    header: Header
    strings: StringsSection
    resource_to_prototype_map: HashmapSection
    paths_storage: List[PathEntry]
    databases: List[DatabaseEntry]
    data: bytes = field(default=b"", repr=False)

    # ── r2p 查找 ─────────────────────────────────────────

    def lookup_r2p(self, self_id: int) -> Optional[int]:
        """在 resourceToPrototypeMap 中查找 selfId → 编码值 (u32)。

        开放寻址 + 线性探测。buckets 16B（key u64 + occupancy u64），values 4B。
        """
        hmap = self.resource_to_prototype_map
        cap = hmap.capacity
        if cap == 0:
            return None
        slot = self_id % cap
        for i in range(cap):
            idx = (slot + i) % cap
            bucket_off = idx * hmap.bucket_stride
            key = B.read_u64(hmap.buckets, bucket_off)
            occ = B.read_u64(hmap.buckets, bucket_off + 8)
            if occ == 0:
                return None
            if key == self_id:
                return B.read_u32(hmap.values, idx * hmap.value_stride)
        return None

    def decode_r2p_value(self, value: int) -> PrototypeLocation:
        """解码 r2p 值：value = (record_index << 8) | (blob_index * 4)。"""
        type_tag = value & 0xFF
        record_index = (value >> 8) & 0xFFFFFF
        blob_index = type_tag // 4
        if blob_index >= len(self.databases):
            raise ParseError(
                f"r2p value 0x{value:08X}: blob_index {blob_index} >= database count {len(self.databases)}"
            )
        db = self.databases[blob_index]
        if record_index >= db.record_count:
            raise PrototypeOutOfRangeError(record_index, blob_index, db.record_count)
        return PrototypeLocation(blob_index, record_index)

    # ── 记录数据 ─────────────────────────────────────────

    def get_prototype_data(self, location: PrototypeLocation, item_size: int) -> bytes:
        """返回从记录起始到 blob 末尾的切片（保留 OOL 相对指针解析空间）。

        relptr 的基准是记录起始（本切片下标 0）。
        """
        db = self.databases[location.blob_index]
        if location.record_index >= db.record_count:
            raise PrototypeOutOfRangeError(location.record_index, location.blob_index, db.record_count)
        record_offset = BLOB_HEADER_SIZE + location.record_index * item_size
        if record_offset + item_size > len(db.data):
            raise OutOfBoundsError(record_offset, item_size, len(db.data), "record")
        return db.data[record_offset:]

    def get_record(self, location: PrototypeLocation) -> bytes:
        """按该 blob 的 item_size 取记录数据。"""
        db = self.databases[location.blob_index]
        return self.get_prototype_data(location, db.item_size)

    # ── 路径解析 ─────────────────────────────────────────

    def build_self_id_index(self) -> Dict[int, int]:
        """构建 selfId → pathsStorage 下标 的索引。"""
        return {entry.self_id: i for i, entry in enumerate(self.paths_storage)}

    def reconstruct_path(self, entry_index: int, self_id_index: Dict[int, int]) -> str:
        """沿 parentId 链重建完整路径（不含前导 '/'）。"""
        parts: List[str] = []
        seen: set = set()
        cur = entry_index
        while cur is not None:
            if cur in seen or cur < 0 or cur >= len(self.paths_storage):
                break
            seen.add(cur)
            entry = self.paths_storage[cur]
            parts.append(entry.name)
            if entry.parent_id == 0:
                break
            cur = self_id_index.get(entry.parent_id)
        parts.reverse()
        return "/".join(p for p in parts if p)

    def find_path_by_suffix(self, path_suffix: str) -> Tuple[int, str]:
        """按后缀查找路径条目，返回 (entry_index, full_path)。"""
        suffix = path_suffix.strip().lstrip("/")
        # 精确匹配优先
        for i, entry in enumerate(self.paths_storage):
            if entry.name == suffix:
                full = self.reconstruct_path(i, self.build_self_id_index())
                if full == suffix or full.endswith("/" + suffix):
                    return i, full
        # 后缀匹配：路径以 suffix 结尾
        self_id_index = self.build_self_id_index()
        for i, entry in enumerate(self.paths_storage):
            full = self.reconstruct_path(i, self_id_index)
            if full == suffix:
                return i, full
            if full.endswith("/" + suffix):
                return i, full
        raise PathNotFoundError(path_suffix)

    def resolve_path(self, path_suffix: str) -> Tuple[PrototypeLocation, str]:
        """把路径后缀解析为 (blob, record) + 完整路径。"""
        entry_index, full_path = self.find_path_by_suffix(path_suffix)
        self_id = self.paths_storage[entry_index].self_id
        r2p_value = self.lookup_r2p(self_id)
        if r2p_value is None:
            raise PathNotFoundError(path_suffix, f"selfId=0x{self_id:016X} 不在 r2p 表中")
        location = self.decode_r2p_value(r2p_value)
        return location, full_path


# ── 解析函数 ──────────────────────────────────────────────────────────────

def _parse_header(data: bytes) -> Header:
    magic = B.read_u32(data, 0)
    version = B.read_u32(data, 4)
    checksum = B.read_u32(data, 8)
    architecture = B.read_u16(data, 12)
    endianness = B.read_u16(data, 14)
    return Header(magic, version, checksum, architecture, endianness)


def _parse_body_header(data: bytes) -> dict:
    """解析 body header（96B @0x10），返回各 section 描述符。"""
    base = BODY_BASE
    return {
        # strings
        "offsets_map_capacity": B.read_u32(data, base + 0x00),
        "offsets_map_buckets_relptr": B.read_i64(data, base + 0x08),
        "offsets_map_values_relptr": B.read_i64(data, base + 0x10),
        "string_data_size": B.read_u32(data, base + 0x18),
        "string_data_relptr": B.read_i64(data, base + 0x20),
        # r2p
        "r2p_capacity": B.read_u32(data, base + 0x28),
        "r2p_buckets_relptr": B.read_i64(data, base + 0x30),
        "r2p_values_relptr": B.read_i64(data, base + 0x38),
        # paths
        "paths_count": B.read_u32(data, base + 0x40),
        "paths_data_relptr": B.read_i64(data, base + 0x48),
        # databases
        "databases_count": B.read_u32(data, base + 0x50),
        "databases_relptr": B.read_i64(data, base + 0x58),
    }


def _resolve_hashmap(
    data: bytes,
    base: int,
    capacity: int,
    buckets_relptr: int,
    values_relptr: int,
    bucket_stride: int,
    value_stride: int,
) -> HashmapSection:
    buckets_offset = B.resolve_relptr(base, buckets_relptr)
    buckets_end = buckets_offset + capacity * bucket_stride
    if buckets_end > len(data):
        raise OutOfBoundsError(buckets_offset, capacity * bucket_stride, len(data) - buckets_offset, "hashmap buckets")
    values_offset = B.resolve_relptr(base, values_relptr)
    values_end = values_offset + capacity * value_stride
    if values_end > len(data):
        raise OutOfBoundsError(values_offset, capacity * value_stride, len(data) - values_offset, "hashmap values")
    return HashmapSection(
        capacity=capacity,
        buckets=data[buckets_offset:buckets_end],
        values=data[values_offset:values_end],
        bucket_stride=bucket_stride,
        value_stride=value_stride,
    )


def _parse_path_entries(data: bytes, data_offset: int, count: int) -> List[PathEntry]:
    """解析 pathsStorage 条目数组。

    每条目 32 字节：selfId u64 + parentId u64 + packed string @+0x10
    （packed string 头 16B：char_count u32 + pad u32 + text_relptr i64，
     文本位于 entry_base+0x10 + text_relptr）。
    """
    total = data_offset + count * 32
    if total > len(data):
        raise OutOfBoundsError(data_offset, count * 32, len(data) - data_offset, "path entries")
    result: List[PathEntry] = [None] * count  # type: ignore[list-item]
    for i in range(count):
        entry_base = data_offset + i * 32
        self_id, parent_id = struct.unpack_from('<QQ', data, entry_base)
        char_count, _pad, rel = struct.unpack_from('<IIq', data, entry_base + 0x10)
        if char_count:
            text_offset = entry_base + 0x10 + rel
            raw = data[text_offset:text_offset + char_count]
            if raw.endswith(b'\x00'):
                raw = raw[:-1]
            name = raw.decode('utf-8', errors='replace')
        else:
            name = ""
        result[i] = PathEntry(self_id, parent_id, name)
    return result


def _parse_database_entries(data: bytes, entries_offset: int, count: int) -> List[DatabaseEntry]:
    result: List[DatabaseEntry] = []
    for i in range(count):
        entry_base = entries_offset + i * 0x18
        if entry_base + 0x18 > len(data):
            raise OutOfBoundsError(entry_base, 0x18, len(data) - entry_base, "database entry")
        prototype_magic = B.read_u32(data, entry_base + 0x00)
        prototype_checksum = B.read_u32(data, entry_base + 0x04)
        size = B.read_u32(data, entry_base + 0x08)
        _pad = B.read_u32(data, entry_base + 0x0C)
        data_relptr = B.read_i64(data, entry_base + 0x10)

        if size > 0:
            data_offset = B.resolve_relptr(entry_base, data_relptr)
            data_end = data_offset + size
            if data_end > len(data):
                raise OutOfBoundsError(data_offset, size, len(data) - data_offset, "blob data")
            blob = data[data_offset:data_end]
            # blob 头：count u64 + header_size u64（恒 16）
            record_count = B.read_u64(blob, 0) if len(blob) >= 8 else 0
        else:
            blob = b""
            record_count = 0

        result.append(DatabaseEntry(
            prototype_magic=prototype_magic,
            prototype_checksum=prototype_checksum,
            size=size,
            data=blob,
            record_count=record_count,
            blob_index=i,
        ))
    return result


def parse_assets_bin(data: bytes) -> PrototypeDatabase:
    """解析 assets.bin 文件字节为 PrototypeDatabase。"""
    if len(data) < 0x70:
        raise ParseError(f"assets.bin 数据过短: {len(data)} 字节")
    header = _parse_header(data)
    if header.magic != BWDB_MAGIC:
        raise InvalidMagicError(header.magic)
    if header.version != BWDB_VERSION:
        raise UnsupportedVersionError(header.version)

    body = _parse_body_header(data)

    # strings：base = body_base (0x10)
    strings_base = BODY_BASE
    offsets_map = _resolve_hashmap(
        data, strings_base,
        body["offsets_map_capacity"],
        body["offsets_map_buckets_relptr"],
        body["offsets_map_values_relptr"],
        bucket_stride=8,   # u64 key
        value_stride=4,    # u32 offset
    )
    string_data_offset = B.resolve_relptr(strings_base, body["string_data_relptr"])
    string_data_end = string_data_offset + body["string_data_size"]
    if string_data_end > len(data):
        raise OutOfBoundsError(string_data_offset, body["string_data_size"],
                               len(data) - string_data_offset, "string data")
    strings = StringsSection(
        offsets_map=offsets_map,
        string_data=data[string_data_offset:string_data_end],
        string_data_base=string_data_offset,
    )

    # r2p：base = body_base + 0x28
    r2p_base = BODY_BASE + R2P_OFFSET
    r2p = _resolve_hashmap(
        data, r2p_base,
        body["r2p_capacity"],
        body["r2p_buckets_relptr"],
        body["r2p_values_relptr"],
        bucket_stride=16,  # u64 key + u64 occupancy
        value_stride=4,    # u32 value
    )

    # paths：base = body_base + 0x40
    paths_base = BODY_BASE + PATHS_OFFSET
    paths_data_offset = B.resolve_relptr(paths_base, body["paths_data_relptr"])
    paths_storage = _parse_path_entries(data, paths_data_offset, body["paths_count"])

    # databases：relptr 相对 body_base
    db_entries_offset = B.resolve_relptr(BODY_BASE, body["databases_relptr"])
    databases = _parse_database_entries(data, db_entries_offset, body["databases_count"])

    return PrototypeDatabase(
        header=header,
        strings=strings,
        resource_to_prototype_map=r2p,
        paths_storage=paths_storage,
        databases=databases,
        data=data,
    )
