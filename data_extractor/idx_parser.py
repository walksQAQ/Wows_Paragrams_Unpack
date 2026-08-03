"""
IDX 索引文件解析器。

解析战舰世界 .idx 二进制索引文件，提取文件树结构。
每个 .idx 文件描述了 .pkg 卷中存储的文件清单及元信息。

IDX 文件格式（参考 landaire/wows-toolkit 的 Rust 源码）::

    ┌──────────────────┐
    │ Header (16 bytes) │  magic(u32) + version(u32) + murmur(u32) + arch(u32)
    ├──────────────────┤
    │ ResourceMetadata │  版本相关：表数量、偏移指针
    ├──────────────────┤
    │ Resources Table  │  文件/目录条目（含父节点 ID 与文件名）
    ├──────────────────┤
    │ FileInfos Table  │  每个文件在 .pkg 中的偏移、大小、压缩信息
    ├──────────────────┤
    │ Volumes Table    │  卷 ID → .pkg 文件名映射
    └──────────────────┘

已知版本:
    - 0x01010004 (v0x20): 旧版 BigWorld 格式（Wargaming 早期）
    - 0x02000000 (v0x40): 新版格式（当前 Lesta / WG 通用）
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Optional


# ── 常量 ──────────────────────────────────────────────────

# IDX 魔数 "ISPF"（Little-Endian u32）
IDX_MAGIC: int = 0x50465349

# 根节点父 ID 哨兵值
ROOT_PARENT_ID: int = 0xDDB1A1D1B108B927

# 已知版本号
VERSION_V20: int = 0x01010004  # 旧版 BigWorld
VERSION_V40: int = 0x02000000  # 新版


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class PackedFileMetadata:
    """资源表条目 —— 描述文件/目录在虚拟文件树中的位置"""
    resource_ptr: int = 0       # 未知指针字段（v0x40 有，v0x20 为 0）
    id: int = 0                 # 此资源的唯一 ID
    parent_id: int = 0          # 父节点 ID（根节点为 ROOT_PARENT_ID）
    filename: str = ""           # 文件名（不含路径）


@dataclass
class FileInfo:
    """文件信息表条目 —— 描述文件在 .pkg 卷中的物理位置"""
    resource_id: int = 0        # 对应的资源 ID
    volume_id: int = 0          # 所在卷的 ID
    offset: int = 0             # 在卷中的字节偏移
    compression_info: int = 0   # 压缩方式（0 = 未压缩, ≠0 = deflate）
    size: int = 0               # 压缩后大小（字节）
    crc32: int = 0              # 解压后数据的 CRC32
    unpacked_size: int = 0      # 解压后大小（字节）
    padding: int = 0            # 填充字节


@dataclass
class Volume:
    """卷表条目 —— 描述 .pkg 文件名与 ID 的映射"""
    volume_id: int = 0          # 卷的唯一 ID
    filename: str = ""          # .pkg 文件名（如 "basecontent_0001.pkg"）


@dataclass
class IdxFile:
    """解析后的 .idx 文件内容"""
    resources: list[PackedFileMetadata] = field(default_factory=list)
    file_infos: list[FileInfo] = field(default_factory=list)
    volumes: list[Volume] = field(default_factory=list)


# ── VFS 条目 ──────────────────────────────────────────────

@dataclass
class VfsEntry:
    """虚拟文件系统中的一个条目"""
    path: str                   # 完整路径，如 "content/GameParams.data"
    is_directory: bool = False  # 是否为目录
    file_info: Optional[FileInfo] = None  # 文件的物理信息（目录为 None）
    volume: Optional[Volume] = None       # 所在卷（目录为 None）


# ── 解析器 ────────────────────────────────────────────────

def _read_null_terminated_string(data: bytes, offset: int) -> str:
    """从指定偏移读取以 null 结尾的字符串"""
    end = data.find(b'\x00', offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode('utf-8', errors='replace')


def _strip_bigworld_prefix(name: str) -> str:
    """去除 BigWorld 路径前缀 '//.//'"""
    if name.startswith("//.//"):
        return name[5:]
    return name


def parse_header(data: bytes, offset: int = 0) -> tuple[int, int, int, int]:
    """解析 16 字节的文件头

    返回: (magic, version, murmur_hash, arch_endian)
    """
    (magic, version, murmur_hash, arch_endian) = struct.unpack_from(
        '<IIII', data, offset
    )
    return magic, version, murmur_hash, arch_endian


def parse_file_info_v40(data: bytes, offset: int) -> FileInfo:
    """解析 v0x40 文件信息条目（48 字节）

    布局::
        resource_id(u64) volume_id(u64) offset(u64)
        compression_info(u64) size(u32) crc32(u32)
        unpacked_size(u32) padding(u32)
    """
    (resource_id, volume_id, offset_val, compression_info,
     size, crc32, unpacked_size, padding) = struct.unpack_from(
        '<QQQQIIII', data, offset
    )
    return FileInfo(
        resource_id=resource_id,
        volume_id=volume_id,
        offset=offset_val,
        compression_info=compression_info,
        size=size,
        crc32=crc32,
        unpacked_size=unpacked_size,
        padding=padding,
    )


def parse_file_info_v20(data: bytes, offset: int) -> FileInfo:
    """解析 v0x20 文件信息条目（48 字节）

    布局::
        offset(u64) _padding(u32) size(u32)
        crc32(u32) unpacked_size(u32) compression_info(u64)
        resource_id(u64) volume_id(u64)
    """
    (offset_val, _padding, size, crc32,
     unpacked_size, compression_info,
     resource_id, volume_id) = struct.unpack_from(
        '<QIIIIQQQ', data, offset
    )
    return FileInfo(
        resource_id=resource_id,
        volume_id=volume_id,
        offset=offset_val,
        compression_info=compression_info,
        size=size,
        crc32=crc32,
        unpacked_size=unpacked_size,
        padding=0,
    )


def parse_packed_metadata_v40(data: bytes, offset: int) -> PackedFileMetadata:
    """解析 v0x40 资源条目（32 字节）

    布局::
        resource_ptr(u64) filename_ptr(u64) id(u64) parent_id(u64)

    filename 存储在 filename_ptr 相对偏移处（以条目起始为基准），null 结尾。
    """
    (resource_ptr, filename_ptr, entry_id, parent_id) = struct.unpack_from(
        '<QQQQ', data, offset
    )
    name_offset = offset + filename_ptr
    filename = _read_null_terminated_string(data, name_offset)
    return PackedFileMetadata(
        resource_ptr=resource_ptr,
        id=entry_id,
        parent_id=parent_id,
        filename=filename,
    )


def parse_packed_metadata_v20(data: bytes, offset: int) -> PackedFileMetadata:
    """解析 v0x20 资源条目（24 字节）

    布局::
        name_hash(u64) parent_id(u64) name_len(u32) name_ptr(u32)

    name_ptr 相对于条目偏移 + 16。
    """
    (name_hash, parent_id, name_len, name_ptr) = struct.unpack_from(
        '<QQII', data, offset
    )
    name_offset = offset + 16 + name_ptr
    raw = data[name_offset:name_offset + name_len]
    # 查找 null 终止
    null_pos = raw.find(b'\x00')
    if null_pos != -1:
        raw = raw[:null_pos]
    filename = raw.decode('utf-8', errors='replace')
    return PackedFileMetadata(
        resource_ptr=name_hash,  # v0x20 无 resource_ptr，复用此字段存 name_hash
        id=name_hash,
        parent_id=parent_id,
        filename=filename,
    )


def parse_volume_v40(data: bytes, offset: int) -> Volume:
    """解析 v0x40 卷条目（24 字节）

    Lesta 实际布局::
        short_id(u64)     偏移 +0: 短 ID（如 21）
        name_ptr(u64)     偏移 +8: 相对于条目起始的文件名偏移
        volume_id(u64)    偏移 +16: 与 FileInfo.volume_id 匹配的实际卷 ID

    注意：name_ptr 相对于条目起始（offset），不是 offset+8。
    volume_id 是第三个字段，与 FileInfo 中的 volume_id 匹配。
    """
    (short_id, name_ptr, volume_id) = struct.unpack_from('<QQQ', data, offset)
    # name_ptr 相对于条目起始偏移
    name_offset = offset + name_ptr
    filename = _read_null_terminated_string(data, name_offset)
    filename = _strip_bigworld_prefix(filename)
    return Volume(volume_id=volume_id, filename=filename)


def parse_volume_v20(data: bytes, offset: int) -> Volume:
    """解析 v0x20 卷条目（16 字节）

    布局::
        volume_id(u64) name_len(u32) name_ptr(u32)

    name_ptr 相对于条目偏移 + 8。
    """
    (volume_id, name_len, name_ptr) = struct.unpack_from('<QII', data, offset)
    name_offset = offset + 8 + name_ptr
    raw = data[name_offset:name_offset + name_len]
    null_pos = raw.find(b'\x00')
    if null_pos != -1:
        raw = raw[:null_pos]
    filename = raw.decode('utf-8', errors='replace')
    filename = _strip_bigworld_prefix(filename)
    return Volume(volume_id=volume_id, filename=filename)


def parse_v40(data: bytes) -> IdxFile:
    """解析 v0x40（新版）IDX 文件"""
    meta_offset = 16
    # Resource metadata: 4 u32 + 3 u64 = 40 bytes
    (resources_count, file_infos_count, volumes_count, _unused,
     resources_table_ptr, file_infos_table_ptr,
     volumes_table_ptr) = struct.unpack_from(
        '<IIIIQQQ', data, meta_offset
    )

    # 偏移量是相对于 meta_offset 的
    resources_table_off = meta_offset + resources_table_ptr
    file_infos_table_off = meta_offset + file_infos_table_ptr
    volumes_table_off = meta_offset + volumes_table_ptr

    # 解析资源表（32 字节/条目）
    resources = []
    for i in range(resources_count):
        off = resources_table_off + i * 32
        resources.append(parse_packed_metadata_v40(data, off))

    # 解析文件信息表（48 字节/条目）
    file_infos = []
    for i in range(file_infos_count):
        off = file_infos_table_off + i * 48
        file_infos.append(parse_file_info_v40(data, off))

    # 解析卷表（24 字节/条目）
    volumes = []
    for i in range(volumes_count):
        off = volumes_table_off + i * 24
        volumes.append(parse_volume_v40(data, off))

    return IdxFile(resources=resources, file_infos=file_infos, volumes=volumes)


def parse_v20(data: bytes) -> IdxFile:
    """解析 v0x20（旧版 BigWorld）IDX 文件"""
    meta_offset = 16
    # Resource metadata: 6 u32 = 24 bytes
    (resources_count, resources_table_ptr,
     file_infos_count, file_infos_table_ptr,
     volumes_count, volumes_table_ptr) = struct.unpack_from(
        '<IIIIII', data, meta_offset
    )

    resources_table_off = meta_offset + resources_table_ptr
    file_infos_table_off = meta_offset + file_infos_table_ptr
    volumes_table_off = meta_offset + volumes_table_ptr

    # 解析资源表（24 字节/条目）
    resources = []
    for i in range(resources_count):
        off = resources_table_off + i * 24
        resources.append(parse_packed_metadata_v20(data, off))

    # 解析文件信息表（48 字节/条目）
    file_infos = []
    for i in range(file_infos_count):
        off = file_infos_table_off + i * 48
        file_infos.append(parse_file_info_v20(data, off))

    # 解析卷表（16 字节/条目）
    volumes = []
    for i in range(volumes_count):
        off = volumes_table_off + i * 16
        volumes.append(parse_volume_v20(data, off))

    return IdxFile(resources=resources, file_infos=file_infos, volumes=volumes)


def parse_idx(data: bytes) -> IdxFile:
    """解析 .idx 文件的原始字节，返回 IdxFile。

    自动检测版本并分派到对应解析器。

    参数:
        data: .idx 文件的完整二进制内容

    返回:
        IdxFile 结构体

    抛出:
        ValueError: 魔数无效或版本不支持
    """
    if len(data) < 16:
        raise ValueError(f"IDX 文件过短: {len(data)} 字节")

    magic, version, _murmur, _arch = parse_header(data)
    if magic != IDX_MAGIC:
        raise ValueError(
            f"无效 IDX 魔数: 0x{magic:08X} (期望 0x{IDX_MAGIC:08X})"
        )

    if version == VERSION_V40:
        return parse_v40(data)
    elif version == VERSION_V20:
        return parse_v20(data)
    else:
        raise ValueError(f"不支持的 IDX 版本: 0x{version:08X}")


def resolve_path(
    resource_id: int,
    resources_map: dict[int, PackedFileMetadata],
    path_cache: dict[int, str],
) -> str:
    """通过递归遍历父节点，为指定资源 ID 构建完整路径。

    根节点判断：如果父 ID 不在 resources_map 中，则为根级条目。
    """
    if resource_id in path_cache:
        return path_cache[resource_id]

    resource = resources_map.get(resource_id)
    if resource is None:
        path_cache[resource_id] = f"__unknown_{resource_id}__"
        return path_cache[resource_id]

    # 根级条目：父 ID 不在任何资源表中
    if resource.parent_id not in resources_map:
        path = resource.filename
    else:
        parent_path = resolve_path(resource.parent_id, resources_map, path_cache)
        path = f"{parent_path}/{resource.filename}"

    path_cache[resource_id] = path
    return path


def build_file_tree(idx_files: list[IdxFile]) -> dict[str, VfsEntry]:
    """将多个 IdxFile 合并为一棵完整的文件树。

    参数:
        idx_files: 解析后的 IdxFile 列表

    返回:
        path → VfsEntry 的映射（路径使用 '/' 分隔）
    """
    # 跨所有 IDX 文件建立查找表
    resources_map: dict[int, PackedFileMetadata] = {}
    file_infos_map: dict[int, FileInfo] = {}
    volumes_map: dict[int, Volume] = {}

    for idx_file in idx_files:
        for r in idx_file.resources:
            resources_map[r.id] = r
        for fi in idx_file.file_infos:
            file_infos_map[fi.resource_id] = fi
        for v in idx_file.volumes:
            volumes_map[v.volume_id] = v

    entries: dict[str, VfsEntry] = {}
    path_cache: dict[int, str] = {}

    # 解析所有资源 ID 的路径
    for res_id in resources_map:
        path = resolve_path(res_id, resources_map, path_cache)

        file_info = file_infos_map.get(res_id)
        volume = None
        if file_info:
            volume = volumes_map.get(file_info.volume_id)

        if file_info and volume:
            entries[path] = VfsEntry(
                path=path,
                is_directory=False,
                file_info=file_info,
                volume=volume,
            )
        else:
            entries[path] = VfsEntry(
                path=path,
                is_directory=True,
            )

    # 确保所有父目录都存在
    _ensure_parent_dirs(entries)

    return entries


def _ensure_parent_dirs(entries: dict[str, VfsEntry]) -> None:
    """补全所有父目录条目"""
    paths = list(entries.keys())
    for path in paths:
        parts = path.split('/')
        for i in range(1, len(parts)):
            parent = '/'.join(parts[:i])
            if parent and parent not in entries:
                entries[parent] = VfsEntry(path=parent, is_directory=True)


def load_idx_directory(idx_dir: str | Path) -> list[IdxFile]:
    """加载目录中的所有 .idx 文件并解析。

    参数:
        idx_dir: 包含 .idx 文件的目录路径

    返回:
        解析后的 IdxFile 列表
    """
    idx_dir = Path(idx_dir)
    if not idx_dir.exists():
        raise FileNotFoundError(f"IDX 目录不存在: {idx_dir}")

    idx_files = []
    errors = []

    for fpath in sorted(idx_dir.iterdir()):
        if fpath.suffix.lower() == '.idx' and fpath.is_file():
            try:
                data = fpath.read_bytes()
                idx_files.append(parse_idx(data))
            except Exception as e:
                errors.append((fpath.name, str(e)))

    if not idx_files and errors:
        raise ValueError(
            f"所有 IDX 文件解析失败: {', '.join(f'{n}: {e}' for n, e in errors)}"
        )

    return idx_files


def get_file_tree_stats(file_tree: dict[str, VfsEntry]) -> dict:
    """统计文件树信息"""
    files = sum(1 for e in file_tree.values() if not e.is_directory)
    dirs = sum(1 for e in file_tree.values() if e.is_directory)
    volumes = set()
    for e in file_tree.values():
        if e.volume:
            volumes.add(e.volume.filename)
    return {
        "total_entries": len(file_tree),
        "files": files,
        "directories": dirs,
        "volumes": sorted(volumes),
    }
