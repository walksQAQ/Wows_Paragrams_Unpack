"""uncode_assets 命令行入口 —— assets.bin 浏览/解码工具。

用法::

    # 从游戏 .pkg 提取并解析
    python -m uncode_assets.cli info  D:/World_of_Warships_RU/Korabli_ST

    # 直接解析已解压的 assets.bin
    python -m uncode_assets.cli stats D:/extracted/assets.bin

    # 浏览虚拟文件
    python -m uncode_assets.cli list D:/extracted/assets.bin [关键字]

    # 目录列表
    python -m uncode_assets.cli ls  D:/extracted/assets.bin [目录]

    # 解析路径 → (blob, record)
    python -m uncode_assets.cli resolve D:/extracted/assets.bin content/gameplay/foo.visual

    # 解码单条为 JSON
    python -m uncode_assets.cli decode D:/extracted/assets.bin content/gameplay/foo.visual

    # 批量解码导出 JSON
    python -m uncode_assets.cli dump D:/extracted/assets.bin ./out --type Visual

    # 从游戏提取 assets.bin 到本地文件
    python -m uncode_assets.cli extract D:/World_of_Warships_RU/Korabli_ST --out ./assets.bin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import AssetsBinError
from .service import AssetsBinService
from .types import can_decode, list_types


from contextlib import contextmanager


def _make_service(source: str) -> AssetsBinService:
    """根据来源自动选择：目录→游戏目录，文件→assets.bin 文件。"""
    p = Path(source)
    if p.is_dir():
        return AssetsBinService(game_dir=p)
    return AssetsBinService(assets_path=p)


@contextmanager
def _open_service(source: str):
    """N23: context manager —— 统一 _make_service + close 样板。"""
    svc = _make_service(source)
    try:
        yield svc
    finally:
        svc.close()


def cmd_info(args: argparse.Namespace) -> None:
    with _open_service(args.source) as svc:
        info = svc.info()
        print("=== assets.bin (PrototypeDatabase) ===")
        print(f"  magic:        {info['magic']}")
        print(f"  version:      {info['version']}")
        print(f"  checksum:     {info['checksum']}")
        print(f"  architecture: {info['architecture']}  endianness: {info['endianness']}")
        print(f"  strings 容量: {info['strings_capacity']}")
        print(f"  r2p 容量:     {info['r2p_capacity']}")
        print(f"  路径条目:     {info['paths_count']}")
        print(f"  数据库 blob:  {info['databases_count']}")
        print(f"  虚拟文件:     {info['file_count']}  目录: {info['dir_count']}")


def cmd_stats(args: argparse.Namespace) -> None:
    with _open_service(args.source) as svc:
        print("Databases:")
        for s in svc.database_stats():
            print(
                f"  [{s['blob_index']:2d}] {s['type']:<26} magic={s['magic']} "
                f"records={s['record_count']:>7} size={s['size']:>11} item=0x{s['item_size']:X}"
            )


def cmd_list(args: argparse.Namespace) -> None:
    with _open_service(args.source) as svc:
        files = svc.find_files(args.keyword or "", max_results=args.max)
        if not files:
            print("(无匹配文件)")
            return
        for f in files:
            tname = f.prototype_type.name if f.prototype_type else "?"
            print(f"  [{tname:<24}] {f.path}")
        print(f"\n总计: {len(files)} 个文件")


def cmd_ls(args: argparse.Namespace) -> None:
    with _open_service(args.source) as svc:
        entries = svc.list_dir(args.dir or "/")
        if not entries:
            print("(空目录)")
            return
        for e in entries:
            print(f"  {e}")
        print(f"\n总计: {len(entries)} 个条目")


def cmd_resolve(args: argparse.Namespace) -> None:
    try:
        with _open_service(args.source) as svc:
            loc, full = svc.resolve(args.path)
            print(f"Resolved: {full}")
            print(f"  blob_index={loc['blob_index']} record_index={loc['record_index']}")
            print(f"  type={loc['type']} item_size=0x{loc['item_size']:X}")
    except AssetsBinError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_decode(args: argparse.Namespace) -> None:
    try:
        with _open_service(args.source) as svc:
            text = svc.decode_path_json(args.path)
            print(text)
    except AssetsBinError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_types(args: argparse.Namespace) -> None:
    """列出全部 prototype 类型（对齐 wows-toolkit `PrototypeType` 枚举）。"""
    print(f"{'blob':>4}  {'类型名':<26} {'magic':<12} {'item':>5}  扩展名                  可解码")
    for t in list_types():
        ext = ",".join(t.extensions) if t.extensions else "-"
        flag = "✅" if can_decode(t) else "—"
        print(f"  {t.blob_index:>2}  {t.name:<26} 0x{t.magic:08X}  0x{t.item_size:02X}  {ext:<22} {flag}")


def cmd_mfm(args: argparse.Namespace) -> None:
    """按路径解码 MFM 材质（对齐 wows-toolkit `--parse-material`）。"""
    try:
        with _open_service(args.source) as svc:
            if args.self_id:
                mat = svc.decode_mfm_by_self_id(int(args.self_id, 0))
                if mat is None:
                    print("❌ 未找到该 selfId 对应的 MFM 材质", file=sys.stderr)
                    sys.exit(1)
            else:
                mat = svc.decode_material_by_path(args.path)
            print(json.dumps(mat, ensure_ascii=False, indent=2, allow_nan=False))
    except AssetsBinError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dump(args: argparse.Namespace) -> None:
    with _open_service(args.source) as svc:
        stats = svc.dump(
            args.output,
            type_filter=args.type,
            max_records=args.max,
        )
        total = sum(stats.values())
        print(f"\n导出完成! 共 {total} 个文件:")
        for name, n in sorted(stats.items()):
            print(f"  {name}: {n}")
        print(f"  输出目录: {Path(args.output).resolve()}")


def cmd_extract(args: argparse.Namespace) -> None:
    out = Path(args.output) if args.output else Path("assets.bin")
    with _open_service(args.game_dir) as svc:
        data = svc.load_from_game(args.game_dir)
        out.write_bytes(data)
        print(f"✅ 已提取 assets.bin ({len(data)} 字节) → {out.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="assets.bin（PrototypeDatabase）浏览与解码工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python -m uncode_assets.cli info  D:/Korabli_ST
  python -m uncode_assets.cli stats D:/assets.bin
  python -m uncode_assets.cli list  D:/assets.bin particle
  python -m uncode_assets.cli decode D:/assets.bin content/gameplay/foo.visual
  python -m uncode_assets.cli dump  D:/assets.bin ./out --type Visual
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_cmd(name, help_text, *args, **kwargs):
        p = sub.add_parser(name, help=help_text)
        for a in args:
            p.add_argument(*a[0], **a[1])
        return p

    add_cmd("info", "显示数据库概览", (["source"], {"help": "游戏目录或 assets.bin 文件"}))
    add_cmd("stats", "显示各 blob 统计", (["source"], {"help": "游戏目录或 assets.bin 文件"}))
    add_cmd("list", "按关键字列出虚拟文件", (["source"], {"help": "游戏目录或 assets.bin 文件"}),
            (["keyword"], {"nargs": "?", "default": "", "help": "路径关键字"}),
            (["--max"], {"type": int, "default": 100, "help": "最多显示数量"}))
    add_cmd("ls", "列出虚拟目录内容", (["source"], {"help": "游戏目录或 assets.bin 文件"}),
            (["dir"], {"nargs": "?", "default": "/", "help": "目录路径"}))
    add_cmd("resolve", "解析路径 → (blob, record)", (["source"], {"help": "游戏目录或 assets.bin 文件"}),
            (["path"], {"help": "路径后缀"}))
    add_cmd("decode", "解码单条 prototype 为 JSON", (["source"], {"help": "游戏目录或 assets.bin 文件"}),
            (["path"], {"help": "路径后缀"}))
    add_cmd("types", "列出全部 prototype 类型表", (["source"], {"help": "游戏目录或 assets.bin 文件"}))
    add_cmd("mfm", "按路径/selfId 解码 MFM 材质", (["source"], {"help": "游戏目录或 assets.bin 文件"}),
            (["path"], {"nargs": "?", "default": None, "help": "MFM 路径（与 --self-id 二选一）"}),
            (["--self-id"], {"default": None, "help": "按 selfId 反查（如 0x1234 或 4660）"}))
    add_cmd("dump", "批量解码导出 JSON", (["source"], {"help": "游戏目录或 assets.bin 文件"}),
            (["output"], {"help": "输出目录"}),
            (["--type"], {"default": None, "help": "仅导出该类型（如 Visual）"}),
            (["--max"], {"type": int, "default": None, "help": "最多记录数"}))
    add_cmd("extract", "从游戏 .pkg 提取 assets.bin", (["game_dir"], {"help": "游戏根目录"}),
            (["--out"], {"default": None, "help": "输出文件路径"}))

    args = parser.parse_args()
    cmd_map = {
        "info": cmd_info, "stats": cmd_stats, "list": cmd_list, "ls": cmd_ls,
        "resolve": cmd_resolve, "decode": cmd_decode, "types": cmd_types,
        "mfm": cmd_mfm, "dump": cmd_dump, "extract": cmd_extract,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
