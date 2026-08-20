"""
data_extractor 命令行入口 —— 用于测试和验证提取功能。

提供与 wowsunpack.exe / pfsunpack2.exe 相似的 CLI 接口。

用法::

    # 列出文件树统计信息
    python -m data_extractor.cli stats D:/World_of_Warships_RU/Korabli_ST

    # 列出匹配的文件
    python -m data_extractor.cli list D:/World_of_Warships_RU/Korabli_ST "content/**/*.data"

    # 列出目录内容
    python -m data_extractor.cli ls D:/World_of_Warships_RU/Korabli_ST content/

    # 提取匹配的文件
    python -m data_extractor.cli extract D:/World_of_Warships_RU/Korabli_ST "^
        "content/**/*.data" "gui/**/*.png" --output ./extracted

    # 提取单个文件
    python -m data_extractor.cli get D:/World_of_Warships_RU/Korabli_ST "^
        "content/GameParams.data" --output ./extracted/GameParams.data

    # 提取全部内容（完整解包）
    python -m data_extractor.cli extract D:/World_of_Warships_RU/Korabli_ST "^
        "**/*" --output ./full_extract

    # 指定版本目录
    python -m data_extractor.cli list D:/World_of_Warships_RU/Korabli_ST "^
        "gui/**/*" --bin 8858711

    # 只查看会提取哪些文件（dry-run）
    python -m data_extractor.cli extract D:/World_of_Warships_RU/Korabli_ST "^
        "content/**/*.xml" --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_extractor import (
    GameExtractor,
    ExtractorError,
)


def cmd_stats(args: argparse.Namespace) -> None:
    """显示文件树统计信息"""
    extractor = GameExtractor(args.game_dir, bin_folder=args.bin)
    try:
        extractor.print_stats()
    finally:
        extractor.close()


def cmd_list(args: argparse.Namespace) -> None:
    """按模式列出文件"""
    extractor = GameExtractor(args.game_dir, bin_folder=args.bin)
    try:
        matches = extractor.list_files(args.patterns)
        if not matches:
            print("(无匹配文件)")
            return
        for entry in sorted(matches, key=lambda e: e.path):
            vol = f" [{entry.volume.filename}]" if entry.volume else ""
            size = f" ({entry.file_info.unpacked_size} 字节)" if entry.file_info else ""
            print(f"  {entry.path}{size}{vol}")
        print(f"\n总计: {len(matches)} 个文件")
    finally:
        extractor.close()


def cmd_ls(args: argparse.Namespace) -> None:
    """列出目录内容"""
    extractor = GameExtractor(args.game_dir, bin_folder=args.bin)
    try:
        dir_path = args.dir or ""
        entries = extractor.list_directory(dir_path)
        if not entries:
            print("(空目录)")
            return
        for entry in sorted(entries, key=lambda e: (not e.is_directory, e.path)):
            indicator = "📁 " if entry.is_directory else "📄 "
            size = ""
            if entry.file_info:
                size = f" ({entry.file_info.unpacked_size} 字节)"
            print(f"  {indicator}{Path(entry.path).name}{size}")
        print(f"\n总计: {len(entries)} 个条目")
    finally:
        extractor.close()


def cmd_extract(args: argparse.Namespace) -> None:
    """按模式提取文件"""
    output_dir = Path(args.output)
    extractor = GameExtractor(args.game_dir, bin_folder=args.bin)
    try:
        extracted = extractor.extract(
            args.patterns,
            output_dir,
            flatten=args.flatten,
            strip_prefix=args.strip_prefix,
            dry_run=args.dry_run,
            workers=getattr(args, 'workers', 0),
        )
        if args.dry_run:
            print(f"\n[DRY RUN] 将提取 {len(extracted)} 个文件到: {output_dir}")
            return

        success = [p for p in extracted if p.exists()]
        failed = len(extracted) - len(success)
        total_bytes = sum(p.stat().st_size for p in success)

        print(f"\n提取完成!")
        print(f"  成功: {len(success)} 个文件")
        print(f"  失败: {failed} 个文件")
        print(f"  总大小: {_format_size(total_bytes)}")
        print(f"  输出目录: {output_dir.resolve()}")
    finally:
        extractor.close()


def cmd_get(args: argparse.Namespace) -> None:
    """提取单个文件"""
    output_path = Path(args.output)
    extractor = GameExtractor(args.game_dir, bin_folder=args.bin)
    try:
        result = extractor.extract_single(args.vfs_path, output_path)
        size = result.stat().st_size
        print(f"✅ 已提取: {result} ({_format_size(size)})")
    except ExtractorError as e:
        print(f"❌ {e}")
        sys.exit(1)
    finally:
        extractor.close()


def cmd_search(args: argparse.Namespace) -> None:
    """搜索文件名包含关键字的文件"""
    extractor = GameExtractor(args.game_dir, bin_folder=args.bin)
    try:
        keyword = args.keyword.lower()
        matches = []
        for path, entry in extractor.file_tree.items():
            if not entry.is_directory and keyword in path.lower():
                matches.append(entry)

        if not matches:
            print(f"(未找到包含 '{args.keyword}' 的文件)")
            return

        for entry in sorted(matches, key=lambda e: e.path):
            vol = f" [{entry.volume.filename}]" if entry.volume else ""
            size = f" ({entry.file_info.unpacked_size} 字节)" if entry.file_info else ""
            print(f"  {entry.path}{size}{vol}")
        print(f"\n总计: {len(matches)} 个文件")
    finally:
        extractor.close()


def _format_size(bytes_val: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="战舰世界资源提取工具 (data_extractor)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 统计信息
  python -m data_extractor.cli stats "D:/World_of_Warships_RU/Korabli_ST"

  # 列出所有 .data 文件
  python -m data_extractor.cli list "D:/World_of_Warships_RU/Korabli_ST" "content/**/*.data"

  # 提取所有 PNG 图片
  python -m data_extractor.cli extract "D:/World_of_Warships_RU/Korabli_ST" \\
      "gui/**/*.png" --output ./extracted

  # 指定版本
  python -m data_extractor.cli list "D:/World_of_Warships_RU/Korabli_ST" \\
      "content/**/*" --bin 8858711

  # 完整解包（提取全部文件）
  python -m data_extractor.cli extract "D:/World_of_Warships_RU/Korabli_ST" \\
      "**/*" --output ./full_extract
        """,
    )
    parser.add_argument(
        "--bin", "-b",
        help="指定版本文件夹名（如 8858711），不指定则自动使用最新版本",
    )

    sub = parser.add_subparsers(title="命令", dest="command")

    # stats
    p_stats = sub.add_parser("stats", help="显示文件树统计信息")
    p_stats.add_argument("game_dir", help="游戏根目录")
    p_stats.set_defaults(func=cmd_stats)

    # list
    p_list = sub.add_parser("list", help="按 glob 模式列出文件")
    p_list.add_argument("game_dir", help="游戏根目录")
    p_list.add_argument("patterns", nargs="+", help="glob 模式（如 content/**/*.data）")
    p_list.set_defaults(func=cmd_list)

    # ls
    p_ls = sub.add_parser("ls", help="列出虚拟目录内容")
    p_ls.add_argument("game_dir", help="游戏根目录")
    p_ls.add_argument("dir", nargs="?", default="", help="虚拟目录路径")
    p_ls.set_defaults(func=cmd_ls)

    # extract
    p_extract = sub.add_parser("extract", help="按 glob 模式提取文件")
    p_extract.add_argument("game_dir", help="游戏根目录")
    p_extract.add_argument("patterns", nargs="+", help="glob 模式")
    p_extract.add_argument("--output", "-o", default="./extracted", help="输出目录")
    p_extract.add_argument("--flatten", "-f", action="store_true", help="压平目录结构")
    p_extract.add_argument("--strip-prefix", action="store_true", help="去除匹配前缀")
    p_extract.add_argument("--dry-run", "-n", action="store_true", help="仅预览不写入")
    p_extract.add_argument("--workers", "-w", type=int, default=0,
                           help="并行进程数; 默认0=自动(CPU核数, 上限8), 1=顺序")
    p_extract.set_defaults(func=cmd_extract)

    # get (single file)
    p_get = sub.add_parser("get", help="提取单个文件")
    p_get.add_argument("game_dir", help="游戏根目录")
    p_get.add_argument("vfs_path", help="虚拟路径（如 content/GameParams.data）")
    p_get.add_argument("--output", "-o", default="./extracted", help="输出文件路径")
    p_get.set_defaults(func=cmd_get)

    # search
    p_search = sub.add_parser("search", help="按文件名关键字搜索")
    p_search.add_argument("game_dir", help="游戏根目录")
    p_search.add_argument("keyword", help="搜索关键字")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
