#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

# 定义 6 个全局绝对指针在 Header 中的偏移量
GLOBAL_PTR_OFFSETS = {
    'verticesMapping': 0x18,
    'indicesMapping': 0x20,
    'mergedVertices': 0x28,
    'mergedIndices': 0x30,
    'collisionModels': 0x38,
    'armorModels': 0x40
}

TYPE_META = {
    'Collision (碰撞)': {'count': 0x10, 'ptr': 0x38},
    'Armor (装甲)': {'count': 0x14, 'ptr': 0x40}
}

USAGE_TIP = (
    '用法说明:\n'
    '  python inject_physics.py <你的改模.geo> <原版解包.geo> --in-place\n\n'
    '功能:\n'
    '  从原版提取 Collision 和 Armor 数据，一次性彻底替换到你的自制改模文件中。\n'
)


def align(n: int, boundary: int) -> int:
    return (n + (boundary - 1)) & ~(boundary - 1)


def ri64(data: bytes, offset: int) -> int:
    return struct.unpack_from('<q', data, offset)[0]


def ru32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<I', data, offset)[0]


def calculate_logical_end(data: bytes, count: int, start_ptr: int) -> int:
    """计算单个数据块的逻辑最大物理边界，确保把对应的字符串也囊括在内"""
    span_end = start_ptr + (count * 0x20)
    for i in range(count):
        struct_base = start_ptr + (i * 0x20)
        if struct_base + 0x1C > len(data): continue

        data_rel = ri64(data, struct_base + 0x00)
        name_len = ru32(data, struct_base + 0x08)
        name_rel = ri64(data, struct_base + 0x10)
        data_size = ru32(data, struct_base + 0x18)

        payload_end = struct_base + data_rel + data_size
        name_end = (struct_base + 0x08) + name_rel + name_len
        span_end = max(span_end, payload_end, name_end)
    return span_end


def extract_section(geometry_path: Path, meta: dict, name: str) -> tuple[bytes, int]:
    """从原版文件中提取指定的数据块"""
    data = geometry_path.read_bytes()
    count = ru32(data, meta['count'])
    ptr = ri64(data, meta['ptr'])

    if count <= 0 or ptr <= 0:
        print(f"[-] 警告: 原版文件 {geometry_path.name} 中没有找到 {name} 数据。")
        return b'', 0

    logical_end = calculate_logical_end(data, count, ptr)
    raw_data = data[ptr:logical_end]

    # 8 字节对齐，防止植入后破坏引擎读取规律
    aligned_length = align(len(raw_data), 8)
    raw_data += b'\x00' * (aligned_length - len(raw_data))

    return raw_data, count


def replace_section(target: bytearray, meta: dict, new_data: bytes, new_count: int, name: str) -> bytearray:
    """在目标文件中切除旧块，植入新块，并修复所有受影响的偏移指针"""
    if new_count == 0 or len(new_data) == 0:
        return target  # 没有新数据要植入，直接跳过

    # 1. 搜集当前文件内所有的有效边界
    all_ptrs = {k: ri64(target, offset) for k, offset in GLOBAL_PTR_OFFSETS.items()}
    valid_boundaries = sorted(list(set([p for p in all_ptrs.values() if p > 0])))

    old_count = ru32(target, meta['count'])
    old_ptr = ri64(target, meta['ptr'])

    # 2. 物理切除与插入点定位
    if old_count > 0 and old_ptr > 0:
        idx = valid_boundaries.index(old_ptr)
        # 寻找下一个最近的指针确定当前块的物理结束位置
        old_span_end = valid_boundaries[idx + 1] if idx + 1 < len(valid_boundaries) else len(target)
        old_size = old_span_end - old_ptr

        print(f"  -> [切除] 发现目标文件中存在的旧 {name} (物理位置 {old_ptr} -> {old_span_end})，已切除。")
        del target[old_ptr:old_span_end]
        insert_at = old_ptr
        size_diff = len(new_data) - old_size
    else:
        # 如果自制文件里原本完全没有这部分数据，则追加到文件末尾
        insert_at = align(len(target), 8)
        pad = insert_at - len(target)
        target.extend(b'\x00' * pad)
        size_diff = len(new_data) + pad
        old_ptr = insert_at
        print(f"  -> [追加] 目标文件中没有旧 {name}，将在文件末尾追加。")

    # 3. 植入新数据
    target[insert_at:insert_at] = new_data

    # 4. 更新当前块的 Count
    struct.pack_into('<I', target, meta['count'], new_count)

    # 5. 修复全文件指针“地震”位移
    for ptr_name, offset in GLOBAL_PTR_OFFSETS.items():
        p = all_ptrs[ptr_name]

        if offset == meta['ptr']:
            # 自己这个块的指针指向插入点
            struct.pack_into('<q', target, offset, insert_at)
        elif p > 0 and p > old_ptr:
            # 物理位置排在被修改块后面的数据，跟着 size_diff 同步平移
            new_p = p + size_diff
            struct.pack_into('<q', target, offset, new_p)

    print(f"  -> [植入] 成功写入原版 {name} (共 {new_count} 个模型, 尺寸变化 {size_diff:+d} 字节)")
    return target


def main():
    if len(sys.argv) == 1:
        print(USAGE_TIP)
        sys.exit(1)

    p = argparse.ArgumentParser(description='将原版游戏的物理模型(Collision & Armor)精准移植到你的自制改模文件中。')
    # 【已修改】：调换了这两个参数的顺序
    p.add_argument('target_geo', type=Path, help='要被物理替换的 自制改模 .geometry (放在前面)')
    p.add_argument('donor_geo', type=Path, help='提供数据的 原版解包 .geometry (放在后面)')

    p.add_argument('-o', '--output', type=Path, default=None)
    p.add_argument('--in-place', action='store_true', help='就地修改自制文件（自动备份）')

    args = p.parse_args()

    try:
        if args.in_place and args.output:
            raise ValueError('不能同时使用 --in-place 和 -o/--output')

        output = args.target_geo if args.in_place else (
                    args.output or args.target_geo.with_name(args.target_geo.stem + '_injected.geometry'))

        # === 第 1 步：从原版提取数据 ===
        print(f"\n[*] 正在从原版提取文件 [{args.donor_geo.name}] 中读取数据...")
        col_data, col_count = extract_section(args.donor_geo, TYPE_META['Collision (碰撞)'], 'Collision (碰撞)')
        arm_data, arm_count = extract_section(args.donor_geo, TYPE_META['Armor (装甲)'], 'Armor (装甲)')

        if col_count == 0 and arm_count == 0:
            print("[-] 提取终止：原版文件中既没有碰撞也没有装甲数据。")
            sys.exit(0)

        # === 第 2 步：向自制文件执行双重外科手术 ===
        print(f"\n[*] 正在向你的自制文件 [{args.target_geo.name}] 注入数据并重组指针...")
        if args.in_place:
            shutil.copy2(args.target_geo, args.target_geo.with_name(args.target_geo.name + '.bak'))
        target_buffer = bytearray(args.target_geo.read_bytes())

        # 依次注入两块数据
        target_buffer = replace_section(target_buffer, TYPE_META['Collision (碰撞)'], col_data, col_count,
                                        'Collision (碰撞)')
        target_buffer = replace_section(target_buffer, TYPE_META['Armor (装甲)'], arm_data, arm_count, 'Armor (装甲)')

        # === 第 3 步：保存 ===
        output.write_bytes(target_buffer)
        print(f"\n[+] 物理数据移植大功告成！完美合并文件已保存至: {output.name}")

    except Exception as e:
        print(f"错误: {e}")
        sys.exit(2)


if __name__ == '__main__':
    main()