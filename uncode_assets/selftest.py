"""uncode_assets 自测：构造合成 PrototypeDatabase 并验证完整解析/解码链路。

没有真实 assets.bin 时用此脚本验证：
    header → body header → strings(offsetsMap) → r2p → paths → databases → Material 解码 → VFS

运行: python -m uncode_assets.selftest
"""

from __future__ import annotations

import struct

from . import binary as B
from .decoders import decode_by_type, decode_material
from .parser import parse_assets_bin
from .types import type_from_magic
from .vfs import AssetsBinVfs

BWDB_MAGIC = 0x42574442
BWDB_VERSION = 0x01010000
MATERIAL_MAGIC = 0x5069C471

# 合成测试用的常量
HASH_A = 1      # 字符串哈希 → "diffuse"
HASH_B = 5      # 字符串哈希 → "myTexture"
SELF_ID = 0x2222  # 路径 selfId


def _build() -> bytes:
    """构造一个最小的合成 assets.bin。"""
    buf = bytearray()

    def push(data: bytes) -> int:
        off = len(buf)
        buf.extend(data)
        return off

    # 1) header (16B)
    push(struct.pack('<IIIHH', BWDB_MAGIC, BWDB_VERSION, 0x12345678, 0x40, 0))

    # 2) body header (96B) 占位
    body_header_off = push(bytes(96))

    # 3) strings.offsetsMap.buckets: capacity=3, 8B each
    om_cap = 3
    om_buckets_off = push(bytes(om_cap * 8))
    # 4) strings.offsetsMap.values: 3*4
    om_values_off = push(bytes(om_cap * 4))
    # 5) string_data
    string_data = b'diffuse\x00myTexture\x00'
    sd_off = push(string_data)

    # 6) r2p.buckets: capacity=3, 16B each
    r2p_cap = 3
    r2p_buckets_off = push(bytes(r2p_cap * 16))
    # 7) r2p.values: 3*4
    r2p_values_off = push(bytes(r2p_cap * 4))

    # 8) paths.data: 1 条 (32B) —— packed string 文本放后面，最后回填
    paths_count = 1
    paths_data_off = push(bytes(paths_count * 32))

    # 9) path 名字文本 OOL
    path_name = b'test.mfm'
    path_name_off = push(path_name + b'\x00')

    # 10) databases 数组: 1*24
    db_count = 1
    db_entries_off = push(bytes(db_count * 0x18))

    # 11) blob0: MaterialPrototype
    blob_size = 16 + 0x88 + 32  # 头 + 1 条记录 + OOL(2*4+2*2+1+8)
    blob_off = push(bytes(blob_size))

    # ── 回填 body header ────────────────────────────────
    def relptr(base, target):
        return target - base

    body_base = 0x10
    struct.pack_into('<I', buf, body_header_off + 0x00, om_cap)
    struct.pack_into('<q', buf, body_header_off + 0x08, relptr(body_base, om_buckets_off))
    struct.pack_into('<q', buf, body_header_off + 0x10, relptr(body_base, om_values_off))
    struct.pack_into('<I', buf, body_header_off + 0x18, len(string_data))
    struct.pack_into('<q', buf, body_header_off + 0x20, relptr(body_base, sd_off))
    struct.pack_into('<I', buf, body_header_off + 0x28, r2p_cap)
    struct.pack_into('<q', buf, body_header_off + 0x30, relptr(body_base + 0x28, r2p_buckets_off))
    struct.pack_into('<q', buf, body_header_off + 0x38, relptr(body_base + 0x28, r2p_values_off))
    struct.pack_into('<I', buf, body_header_off + 0x40, paths_count)
    struct.pack_into('<q', buf, body_header_off + 0x48, relptr(body_base + 0x40, paths_data_off))
    struct.pack_into('<I', buf, body_header_off + 0x50, db_count)
    struct.pack_into('<q', buf, body_header_off + 0x58, relptr(body_base, db_entries_off))

    # ── 填充 offsetsMap ─────────────────────────────────
    # slot = hash % cap
    hash_a, hash_b = HASH_A, HASH_B  # slot 1, slot 2
    struct.pack_into('<QQ', buf, om_buckets_off + 1 * 8, hash_a, 1)
    struct.pack_into('<QQ', buf, om_buckets_off + 2 * 8, hash_b, 1)
    struct.pack_into('<I', buf, om_values_off + 1 * 4, 0)  # "diffuse" @0
    struct.pack_into('<I', buf, om_values_off + 2 * 4, 8)  # "myTexture" @8

    # ── 填充 r2p ────────────────────────────────────────
    self_id = SELF_ID
    slot = self_id % r2p_cap
    struct.pack_into('<QQ', buf, r2p_buckets_off + slot * 16, self_id, 1)
    r2p_value = (0 << 8) | (0 * 4)  # blob 0, record 0
    struct.pack_into('<I', buf, r2p_values_off + slot * 4, r2p_value)

    # ── 填充 paths ──────────────────────────────────────
    entry_base = paths_data_off
    struct.pack_into('<QQ', buf, entry_base, self_id, 0)  # self_id, parent_id=0
    name_base = entry_base + 0x10
    struct.pack_into('<I', buf, name_base, len(path_name))      # char_count
    struct.pack_into('<I', buf, name_base + 4, 0)               # pad
    struct.pack_into('<q', buf, name_base + 8, path_name_off - name_base)  # text_relptr

    # ── 填充 databases ──────────────────────────────────
    dentry = db_entries_off
    struct.pack_into('<I', buf, dentry + 0x00, MATERIAL_MAGIC)
    struct.pack_into('<I', buf, dentry + 0x04, 0xABCDEF01)
    struct.pack_into('<I', buf, dentry + 0x08, blob_size)
    struct.pack_into('<q', buf, dentry + 0x10, blob_off - dentry)

    # ── 填充 blob0 ──────────────────────────────────────
    record_base = blob_off + 16
    struct.pack_into('<Q', buf, blob_off + 0x00, 1)   # count
    struct.pack_into('<Q', buf, blob_off + 0x08, 16)  # header_size

    # OOL 布局（记录后，Korabli 0x88 布局）:
    #   names_ool: 2*u32
    #   type_idx_ool: 2*u16
    #   bool_ool: 1*u8
    #   texture_ool: 1*u64
    names_ool = record_base + 0x88
    type_idx_ool = names_ool + 8
    bool_ool = type_idx_ool + 4
    texture_ool = bool_ool + 1

    struct.pack_into('<H', buf, record_base + 0x00, 2)      # property_count
    struct.pack_into('<H', buf, record_base + 0x02, 1)      # flags
    struct.pack_into('<I', buf, record_base + 0x08, 0x100)  # shader_id
    struct.pack_into('<Q', buf, record_base + 0x18, names_ool - record_base)
    struct.pack_into('<Q', buf, record_base + 0x20, type_idx_ool - record_base)
    struct.pack_into('<Q', buf, record_base + 0x30, bool_ool - record_base)     # bool_ptr
    struct.pack_into('<Q', buf, record_base + 0x50, texture_ool - record_base)  # texture_ptr
    struct.pack_into('<Q', buf, record_base + 0x78, 0xFEED)  # material_hash

    struct.pack_into('<II', buf, names_ool, hash_a, hash_b)
    struct.pack_into('<HH', buf, type_idx_ool, 0x00, 0x04)  # (type0,idx0) / (type4,idx0)
    struct.pack_into('<B', buf, bool_ool, 1)
    struct.pack_into('<Q', buf, texture_ool, SELF_ID)  # 指向自己的路径 hash

    return bytes(buf)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ✓ {msg}")


def run() -> None:
    print("== 构造合成 assets.bin ==")
    data = _build()
    # 0x42574442 小端字节 = BDWB（与 wows-toolkit le_u32 解析一致）
    _assert(data[:4] == struct.pack('<I', BWDB_MAGIC), "magic bytes == 0x42574442")

    print("== 解析 PrototypeDatabase ==")
    db = parse_assets_bin(data)
    _assert(db.header.magic == BWDB_MAGIC, "header.magic")
    _assert(db.header.version == BWDB_VERSION, "header.version")
    _assert(len(db.databases) == 1, "databases count = 1")
    _assert(db.databases[0].prototype_magic == MATERIAL_MAGIC, "blob0 magic = MaterialPrototype")
    _assert(db.databases[0].record_count == 1, "blob0 record_count = 1")
    _assert(db.databases[0].prototype_name == "MaterialPrototype", "prototype_name")

    print("== 字符串反查 ==")
    _assert(db.strings.get_string_by_id(HASH_A) == "diffuse", "get_string_by_id(1) == 'diffuse'")
    _assert(db.strings.get_string_by_id(HASH_B) == "myTexture", "get_string_by_id(5) == 'myTexture'")
    _assert(db.strings.get_string_by_id(999) is None, "未知 hash 返回 None")

    print("== r2p 查找 ==")
    r2p_value = db.lookup_r2p(SELF_ID)
    _assert(r2p_value is not None, "lookup_r2p(0x2222) 命中")
    loc = db.decode_r2p_value(r2p_value)
    _assert(loc.blob_index == 0 and loc.record_index == 0, "r2p → (blob0, record0)")

    print("== paths 解析 ==")
    _assert(len(db.paths_storage) == 1, "paths count = 1")
    _assert(db.paths_storage[0].self_id == SELF_ID, "path self_id")
    _assert(db.paths_storage[0].name == "test.mfm", f"path name == 'test.mfm'")

    print("== resolve_path ==")
    resolved_loc, full = db.resolve_path("test.mfm")
    _assert(full == "test.mfm", f"full path = {full}")
    _assert(resolved_loc.record_index == 0, "resolved record = 0")

    print("== MaterialPrototype 解码 ==")
    record = db.get_record(resolved_loc)
    proto_type = type_from_magic(MATERIAL_MAGIC)
    mat = decode_by_type(record, db, proto_type)
    _assert(mat["_type"] == "MaterialPrototype", "type tag")
    _assert(mat["property_count"] == 2, "property_count = 2")
    props = mat["properties"]
    _assert(props[0]["name"] == "diffuse", f"prop[0].name == 'diffuse'")
    _assert(props[0]["type"] == "bool" and props[0]["value"] is True, "prop[0] bool=True")
    _assert(props[1]["name"] == "myTexture", f"prop[1].name == 'myTexture'")
    _assert(props[1]["type"] == "texture", "prop[1] type=texture")
    _assert(props[1]["value_path"] == "test.mfm", f"prop[1].value_path resolves path")

    print("== decode_prototype_to_json ==")
    from .decoders import decode_prototype_to_json
    js = decode_prototype_to_json(record, db, proto_type)
    _assert('"MaterialPrototype"' in js, "JSON 含类型名")

    print("== VFS ==")
    vfs = AssetsBinVfs(db)
    _assert(vfs.file_count() == 1, "vfs file_count = 1")
    _assert(vfs.has_file("/test.mfm"), "vfs has /test.mfm")
    _assert(vfs.list_dir("/") == ["test.mfm"], f"vfs root children = {vfs.list_dir('/')}")
    f = vfs.get_file("/test.mfm")
    _assert(f.prototype_type.name == "MaterialPrototype", "vfs file type")
    decoded = vfs.decode_file("/test.mfm")
    _assert(decoded["_type"] == "MaterialPrototype", "vfs decode")

    print("\n✅ 全部自测通过")


if __name__ == "__main__":
    run()
