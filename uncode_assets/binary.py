"""低级二进制读取工具 —— 与 wows-toolkit `parser_utils.rs` 一一对应。

实现 BigWorld 通用的相对指针、packed string、标量数组解析。
所有读取均为小端序（BWDB 固定小端）。
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

from .errors import OutOfBoundsError


# ── 标量读取 ──────────────────────────────────────────────────────────────

def read_u8(data: bytes, offset: int) -> int:
    _check(data, offset, 1)
    return data[offset]


def read_u16(data: bytes, offset: int) -> int:
    _check(data, offset, 2)
    return struct.unpack_from('<H', data, offset)[0]


def read_u32(data: bytes, offset: int) -> int:
    _check(data, offset, 4)
    return struct.unpack_from('<I', data, offset)[0]


def read_u64(data: bytes, offset: int) -> int:
    _check(data, offset, 8)
    return struct.unpack_from('<Q', data, offset)[0]


def read_i32(data: bytes, offset: int) -> int:
    _check(data, offset, 4)
    return struct.unpack_from('<i', data, offset)[0]


def read_i64(data: bytes, offset: int) -> int:
    _check(data, offset, 8)
    return struct.unpack_from('<q', data, offset)[0]


def read_f32(data: bytes, offset: int) -> float:
    _check(data, offset, 4)
    return struct.unpack_from('<f', data, offset)[0]


def _check(data: bytes, offset: int, size: int) -> None:
    if offset < 0 or offset + size > len(data):
        raise OutOfBoundsError(offset, size, len(data))


# ── 相对指针 ──────────────────────────────────────────────────────────────

def resolve_relptr(base: int, rel: int) -> int:
    """把相对指针解析为绝对偏移：base + rel（wows-toolkit `resolve_relptr`）。"""
    return base + rel


def resolve_relptr_at(data: bytes, base: int, relptr_field_offset: int) -> int:
    """读取 `base + relptr_field_offset` 处的 i64 relptr，并解析为绝对偏移。"""
    rel = read_i64(data, base + relptr_field_offset)
    return resolve_relptr(base, rel)


# ── Packed String ─────────────────────────────────────────────────────────

def parse_packed_string_fields(data: bytes, struct_base: int) -> Tuple[int, int]:
    """解析 packed string 头（16 字节）：char_count u32, pad u32, text_relptr i64。

    返回 (char_count, text_relptr)。
    """
    _check(data, struct_base, 16)
    char_count = read_u32(data, struct_base + 0)
    _pad = read_u32(data, struct_base + 4)
    text_relptr = read_i64(data, struct_base + 8)
    return char_count, text_relptr


def parse_packed_string(data: bytes, struct_base: int) -> str:
    """从文件数据中解析 packed string。

    字符串实际内容位于 `struct_base + text_relptr`，长度 char_count，
    末尾可能带一个 \\0。
    """
    char_count, text_relptr = parse_packed_string_fields(data, struct_base)
    if char_count == 0:
        return ""
    text_offset = resolve_relptr(struct_base, text_relptr)
    text_end = text_offset + char_count
    if text_end > len(data):
        raise OutOfBoundsError(text_offset, char_count, len(data) - text_offset, "packed string")
    raw = data[text_offset:text_end]
    if raw.endswith(b'\x00'):
        raw = raw[:-1]
    return raw.decode('utf-8', errors='replace')


def read_null_terminated_string(data: bytes, offset: int) -> str:
    """读取以 null 结尾的字符串。"""
    if offset < 0 or offset > len(data):
        raise OutOfBoundsError(offset, 0, len(data), "null-terminated string")
    end = data.find(b'\x00', offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode('utf-8', errors='replace')


# ── 数组解析 ──────────────────────────────────────────────────────────────

def parse_u16_array(data: bytes, offset: int, count: int) -> List[int]:
    _check(data, offset, count * 2)
    return list(struct.unpack_from(f'<{count}H', data, offset))


def parse_u32_array(data: bytes, offset: int, count: int) -> List[int]:
    if count <= 0:
        return []
    _check(data, offset, count * 4)
    return list(struct.unpack_from(f'<{count}I', data, offset))


def parse_i32_array(data: bytes, offset: int, count: int) -> List[int]:
    if count <= 0:
        return []
    _check(data, offset, count * 4)
    return list(struct.unpack_from(f'<{count}i', data, offset))


def parse_f32_array(data: bytes, offset: int, count: int) -> List[float]:
    if count <= 0:
        return []
    _check(data, offset, count * 4)
    return list(struct.unpack_from(f'<{count}f', data, offset))


def parse_matrix_array(data: bytes, offset: int, count: int) -> List[List[float]]:
    """解析 count 个 4×4 矩阵（每个 16×f32 = 64 字节）。"""
    if count <= 0:
        return []
    _check(data, offset, count * 64)
    return [
        list(struct.unpack_from('<16f', data, offset + i * 64))
        for i in range(count)
    ]


# ── 复合结构 ──────────────────────────────────────────────────────────────

def parse_vec2(data: bytes, offset: int) -> List[float]:
    return [read_f32(data, offset), read_f32(data, offset + 4)]


def parse_vec3(data: bytes, offset: int) -> List[float]:
    return [read_f32(data, offset), read_f32(data, offset + 4), read_f32(data, offset + 8)]


def parse_vec4(data: bytes, offset: int) -> List[float]:
    return [read_f32(data, offset), read_f32(data, offset + 4),
            read_f32(data, offset + 8), read_f32(data, offset + 12)]


def parse_matrix4x4(data: bytes, offset: int) -> List[float]:
    return list(struct.unpack_from('<16f', data, offset))


def parse_bounding_box(data: bytes, offset: int) -> dict:
    """解析 32 字节包围盒：3×f32 min + 4 pad + 3×f32 max + 4 pad。"""
    return {
        "min": parse_vec3(data, offset),
        "max": parse_vec3(data, offset + 16),
    }
