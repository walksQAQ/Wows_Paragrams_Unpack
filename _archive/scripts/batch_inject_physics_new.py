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


def align(n: int, boundary: int) -> int:
    return (n + (boundary - 1)) & ~(boundary - 1)


def ri64(data: bytes, offset: int) -> int:
    return struct.unpack_from('<q', data, offset)[0]


def ru32(data: bytes, offset: int) -> int:
    return struct.unpack_from('<I', data, offset)[0]


def calculate_logical_end(data: bytes, count: int, start_ptr: int) -> int:
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
    data = geometry_path.read_bytes()
    count = ru32(data, meta['count'])
    ptr = ri64(data, meta['ptr'])

    if count <= 0 or ptr <= 0:
        return b'', 0

    logical_end = calculate_logical_end(data, count, ptr)
    raw_data = data[ptr:logical_end]

    aligned_length = align(len(raw_data), 8)
    raw_data += b'\x00' * (aligned_length - len(raw_data))

    return raw_data, count


def replace_section(target: bytearray, meta: dict, new_data: bytes, new_count: int, name: str) -> bytearray:
    if new_count == 0 or len(new_data) == 0:
        return target

    all_ptrs = {k: ri64(target, offset) for k, offset in GLOBAL_PTR_OFFSETS.items()}
    valid_boundaries = sorted(list(set([p for p in all_ptrs.values() if p > 0])))

    old_count = ru32(target, meta['count'])
    old_ptr = ri64(target, meta['ptr'])

    if old_count > 0 and old_ptr > 0:
        idx = valid_boundaries.index(old_ptr)
        old_span_end = valid_boundaries[idx + 1] if idx + 1 < len(valid_boundaries) else len(target)
        old_size = old_span_end - old_ptr

        del target[old_ptr:old_span_end]
        insert_at = old_ptr
        size_diff = len(new_data) - old_size
    else:
        insert_at = align(len(target), 8)
        pad = insert_at - len(target)
        target.extend(b'\x00' * pad)
        size_diff = len(new_data) + pad
        old_ptr = insert_at

    target[insert_at:insert_at] = new_data
    struct.pack_into('<I', target, meta['count'], new_count)

    for ptr_name, offset in GLOBAL_PTR_OFFSETS.items():
        p = all_ptrs[ptr_name]
        if offset == meta['ptr']:
            struct.pack_into('<q', target, offset, insert_at)
        elif p > 0 and p > old_ptr:
            new_p = p + size_diff
            struct.pack_into('<q', target, offset, new_p)

    return target


def process_single_file(target_path: Path, donor_path: Path, output_path: Path, in_place: bool):
    try:
        col_data, col_count = extract_section(donor_path, TYPE_META['Collision (碰撞)'], 'Collision (碰撞)')
        arm_data, arm_count = extract_section(donor_path, TYPE_META['Armor (装甲)'], 'Armor (装甲)')

        if col_count == 0 and arm_count == 0:
            print(f"[-] 跳过: 原版文件 {donor_path.name} 中未发现碰撞或装甲数据。")
            return False

        if in_place:
            bak_path = target_path.with_name(target_path.name + '.bak')
            shutil.copy2(target_path, bak_path)

        target_buffer = bytearray(target_path.read_bytes())
        target_buffer = replace_section(target_buffer, TYPE_META['Collision (碰撞)'], col_data, col_count,
                                        'Collision (碰撞)')
        target_buffer = replace_section(target_buffer, TYPE_META['Armor (装甲)'], arm_data, arm_count, 'Armor (装甲)')

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(target_buffer)
        return True
    except Exception as e:
        print(f"[!] 处理失败 {target_path.name}: {e}")
        return False


def main():
    # 使用 add_help=False 禁用默认的 -h，以便我们自定义
    p = argparse.ArgumentParser(
        description='批量将游戏中原始的模型文件中包含的物理模型数据移植到同命名的改模文件中。可用于修复Lesta服26.6更新后失效的原基于pnf方式生效的涂装mod。',
        add_help=False,
        # 这里的 usage 决定了顶部显示的顺序
        usage='%(prog)s target_dir donor_dir [--in-place | -o <输出目录>] [--suffix <后缀>] [-h]'
    )

    # 1. 必选参数组
    group_req = p.add_argument_group('必选参数')
    group_req.add_argument('target_dir', type=Path, help='装有需要修复的旧版.geometry 文件的文件夹路径')
    group_req.add_argument('donor_dir', type=Path, help='装有从游戏中提取得到的新版.geometry 文件的文件夹路径')

    # 2. 可选参数组
    group_opt = p.add_argument_group('可选参数')

    # 互斥组放在可选参数中
    mut_group = group_opt.add_mutually_exclusive_group(required=True)
    mut_group.add_argument('--in-place', action='store_true', help='就地修复旧版文件（自动生成 .bak 备份）')
    mut_group.add_argument('-o', '--out-dir', type=Path, metavar='<输出目录>',
                           help='指定一个独立的文件夹路径用于存放合并结果')

    group_opt.add_argument('--suffix', type=str, default='.geometry', metavar='<后缀>',
                           help='识别的文件后缀名，默认为 .geometry')

    # 手动添加 help
    group_opt.add_argument('-h', '--help', action='help', help='显示此帮助信息并退出')

    # 无参数时显示帮助
    if len(sys.argv) == 1:
        p.print_help()
        sys.exit(1)

    args = p.parse_args()

    if not args.target_dir.is_dir():
        print(f"[-] 错误: 包含需要修复的模型文件的文件夹不存在或输入的路径不是目录: {args.target_dir}")
        sys.exit(2)
    if not args.donor_dir.is_dir():
        print(f"[-] 错误: 包含新版模型文件的文件夹不存在或输入的路径不是目录: {args.donor_dir}")
        sys.exit(2)

    # 扫描自制文件夹 (剔除 .bak 备份)
    target_files = sorted([f for f in args.target_dir.rglob(f"*{args.suffix}") if not f.name.endswith('.bak')])

    if not target_files:
        print(f"[-] 在 [{args.target_dir}] 中没有找到后缀为 '{args.suffix}' 的文件。")
        sys.exit(0)

    # 建立全图鉴索引库，留作第二优先级的保底匹配池
    print(f"[*] 正在扫描原版解包路径建立文件索引 (用于保底匹配)...")
    donor_files_map = {f.name: f for f in args.donor_dir.rglob(f"*{args.suffix}")}
    print(f"[*] 索引完毕，共在原版解包目录中发现 {len(donor_files_map)} 个备选模型文件。")

    print(f"[*] 开始匹配处理，目标文件夹共有 {len(target_files)} 个改模文件...")
    success_count = 0
    skip_count = 0

    for t_file in target_files:
        rel_path = t_file.relative_to(args.target_dir)

        # 优先级 1：优先尝试严格遵守相对路径结构匹配
        d_file = args.donor_dir / rel_path
        match_type = "相同路径和名称文件"

        # 优先级 2：如果路径对不上（文件不存在），开启保底机制，在全局字典里按文件名抓取
        if not d_file.exists():
            d_file = donor_files_map.get(t_file.name)
            match_type = "相同命名文件"

        # 如果保底也找不到，说明原版彻底没有这个模型，跳过
        if not d_file or not d_file.exists():
            print(f"[-] 匹配失败: {t_file.name} -> 相对路径与全局文件名均未找到原版文件，跳过。")
            skip_count += 1
            continue

        # 确定输出路径
        if args.in_place:
            out_file = t_file
        else:
            out_file = args.out_dir / rel_path

        print(f"[+] 匹配成功 [{match_type}]: {t_file.name} (使用的原始模型位置: {d_file.parent.name}/{d_file.name})")
        if process_single_file(t_file, d_file, out_file, args.in_place):
            success_count += 1
        else:
            skip_count += 1

    print(f"\n[======== 批量处理完成 ========]")
    print(f"  成功移植: {success_count} 个文件")
    print(f"  跳过/失败: {skip_count} 个文件")
    if args.in_place:
        print(f"  模式: --in-place (原改模文件已直接更新，旧文件已自动备份为 .bak)")
    else:
        print(f"  模式: 输出到独立文件夹 -> [{args.out_dir.absolute()}]")


if __name__ == '__main__':
    main()