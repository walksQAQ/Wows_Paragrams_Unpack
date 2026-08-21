"""
高层解包编排器 —— 提供与 pfsunpack2.exe / wowsunpack.exe 等价的提取功能。

核心流程::

    1. 指定游戏根目录（含 bin/ 和 res_packages/）
    2. 自动检测最新版本目录
    3. 加载并解析版本目录下所有 .idx 文件
    4. 建立完整文件树（路径 → 卷 + 偏移映射）
    5. 支持 glob 模式匹配文件路径
    6. 从 .pkg 卷中读取并解压匹配的文件
    7. 输出到指定目录（保持目录结构）

支持的提取模式:
    - 按 glob 模式提取（如 ``content/**/*.data``, ``gui/**/*.png``）
    - 提取完整内容（等同于 ``**/*``）
    - 列出匹配文件（不实际提取）
    - 仅查看文件树结构
"""

from __future__ import annotations

import fnmatch
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from data_extractor.idx_parser import (
    VfsEntry,
    FileInfo,
    build_file_tree,
    load_idx_directory,
    get_file_tree_stats,
)
from data_extractor.pkg_reader import PkgReader, PkgError


# 每个 worker 进程内复用的 PkgReader 缓存 (pkgs_dir -> reader)
# 进程池每 worker 一个进程, 各自持有独立缓存, 无跨进程共享
_PKG_READER_CACHE: dict[str, PkgReader] = {}


def _get_worker_reader(pkgs_dir: str) -> PkgReader:
    """获取/创建当前进程内的 PkgReader (按 pkgs_dir 复用)。"""
    reader = _PKG_READER_CACHE.get(pkgs_dir)
    if reader is None:
        reader = PkgReader(pkgs_dir)
        _PKG_READER_CACHE[pkgs_dir] = reader
    return reader


def _parallel_extract_worker(args: tuple) -> tuple[Path, Optional[str]]:
    """进程池 worker：流式提取单个文件到输出路径（独立 PkgReader，低内存）。

    参数 (pkgs_dir, volume_filename, file_info, out_path) 均为可 pickle 的基本类型。
    返回 (out_path, None) 成功 / (out_path, 错误信息) 失败。
    """
    pkgs_dir, volume_filename, file_info, out_path = args
    try:
        # 复用当前进程的 reader (避免每个任务重复构建)
        reader = _get_worker_reader(pkgs_dir)
        reader.extract_to_file(volume_filename, file_info, out_path)
        # bc7prep 纹理解码 (仅当需要)
        reader.decode_bc7prep_file(out_path)
        return Path(out_path), None
    except Exception as e:  # noqa: BLE001 —— 子进程内捕获, 汇报给主进程
        return Path(out_path), str(e)


class ExtractorError(Exception):
    """提取过程中的错误"""
    pass


@dataclass
class FileMatch:
    """匹配到的文件信息"""
    vfs_path: str               # 虚拟路径（如 "content/GameParams.data"）
    output_path: Path           # 输出文件的相对路径
    file_info: FileInfo         # 文件物理信息
    volume_filename: str        # 所在 .pkg 文件名
    is_directory: bool = False  # 是否为目录


class GameExtractor:
    """游戏资源提取器 —— 整合 IDX 解析 + PKG 读取。

    使用方式::

        extractor = GameExtractor(
            game_dir="D:/World_of_Warships_RU/Korabli_ST"
        )
        # 列出所有文件
        for entry in extractor.list_files("content/**/*.data"):
            print(entry.vfs_path)

        # 提取文件
        extractor.extract(
            patterns=["content/**/*.data", "gui/**/*.png"],
            output_dir="./extracted",
        )
    """

    def __init__(
        self,
        game_dir: str | Path,
        bin_folder: str | None = None,
        pkgs_dir: str | Path | None = None,
    ):
        """
        参数:
            game_dir: 游戏根目录（含 bin/ 和 res_packages/）
            bin_folder: 指定版本文件夹名（如 "8858711"），
                        不指定则自动使用最新版本
            pkgs_dir: .pkg 文件目录，不指定时自动推断为
                      ``game_dir/res_packages``
        """
        self._game_dir = Path(game_dir)
        if not self._game_dir.exists():
            raise ExtractorError(f"游戏目录不存在: {self._game_dir}")

        # 确定版本目录
        if bin_folder:
            self._bin_folder = bin_folder
        else:
            self._bin_folder = self._find_latest_bin()

        # 确定 IDX 目录
        self._idx_dir = self._game_dir / "bin" / self._bin_folder / "idx"
        if not self._idx_dir.exists():
            raise ExtractorError(f"IDX 目录不存在: {self._idx_dir}")

        # 确定 PKG 目录
        if pkgs_dir:
            self._pkgs_dir = Path(pkgs_dir)
        else:
            self._pkgs_dir = self._game_dir / "res_packages"
        if not self._pkgs_dir.exists():
            raise ExtractorError(f"PKG 目录不存在: {self._pkgs_dir}")

        # 加载 IDX
        self._idx_files = load_idx_directory(self._idx_dir)
        self._file_tree = build_file_tree(self._idx_files)
        self._pkg_reader = PkgReader(self._pkgs_dir)

    # ── 属性 ──────────────────────────────────────────────

    @property
    def game_dir(self) -> Path:
        return self._game_dir

    @property
    def bin_folder(self) -> str:
        return self._bin_folder

    @property
    def idx_dir(self) -> Path:
        return self._idx_dir

    @property
    def pkgs_dir(self) -> Path:
        return self._pkgs_dir

    @property
    def file_tree(self) -> dict[str, VfsEntry]:
        return self._file_tree

    @property
    def pkg_reader(self) -> PkgReader:
        return self._pkg_reader

    # ── 内部帮助方法 ─────────────────────────────────────

    def _find_latest_bin(self) -> str:
        """在 bin/ 下查找最大的版本号目录"""
        from utils.path_utils import find_latest_bin_folder
        result = find_latest_bin_folder(self._game_dir)
        if result is None:
            raise ExtractorError(f"bin 目录不存在或没有版本文件夹: {self._game_dir / 'bin'}")
        return result

    # ── 高级接口 ──────────────────────────────────────────

    def list_files(self, patterns: list[str] | None = None) -> list[VfsEntry]:
        """列出文件树中的文件。

        参数:
            patterns: glob 模式列表。为 None 时返回全部文件

        返回:
            匹配的 VfsEntry 列表
        """
        if patterns is None:
            # 返回所有文件（非目录）
            return [
                e for e in self._file_tree.values()
                if not e.is_directory
            ]

        matched_set: dict[str, VfsEntry] = {}
        for pattern in patterns:
            for path, entry in self._file_tree.items():
                if fnmatch.fnmatch(path, pattern):
                    matched_set[path] = entry

        return list(matched_set.values())

    def list_directory(self, dir_path: str = "") -> list[VfsEntry]:
        """列出虚拟目录下的直接子条目。

        参数:
            dir_path: 目录路径（空字符串 = 根目录）

        返回:
            直接子条目列表
        """
        prefix = dir_path.strip('/')
        if prefix:
            prefix += '/'

        children: dict[str, VfsEntry] = {}
        for path, entry in self._file_tree.items():
            if path.startswith(prefix):
                remainder = path[len(prefix):]
                if '/' in remainder:
                    # 子目录：只取第一级
                    subdir = remainder.split('/')[0]
                    sub_path = f"{prefix}{subdir}".rstrip('/')
                    if sub_path not in children:
                        children[sub_path] = VfsEntry(
                            path=sub_path,
                            is_directory=True,
                        )
                else:
                    children[path] = entry

        return list(children.values())

    def extract(
        self,
        patterns: list[str],
        output_dir: str | Path,
        flatten: bool = False,
        strip_prefix: bool = False,
        dry_run: bool = False,
        workers: int = 0,
    ) -> list[Path]:
        """提取匹配模式的文件。

        参数:
            patterns: glob 模式列表
            output_dir: 输出目录
            flatten: 压平目录结构（所有文件输出到同一目录）
            strip_prefix: 去除匹配的最长公共前缀
            dry_run: 仅打印，不实际写入
            workers: 并行进程数。
                    - 0/负值 = 自动（默认, 用 CPU 核数, 上限 8）
                    - 1 = 顺序
                    - >1 = 多进程并行解压
                    纯 Python Kraken 解压受 GIL 限制, 线程无法并行 CPU 密集,
                    因此用多进程。每个进程独立流式解压写盘, 内存峰值 ≈
                    workers × 单文件流式峰值（约几 MB）, 仍保持低内存。

        返回:
            已提取文件的路径列表
        """
        output_dir = Path(output_dir)
        matches = self._match_files(patterns, strip_prefix)

        if dry_run:
            extracted: list[Path] = []
            for match in matches:
                if match.is_directory:
                    continue
                out_path = output_dir / match.output_path
                print(f"[DRY RUN] {match.vfs_path} → {out_path}")
                extracted.append(out_path)
            return extracted

        nworkers = self._resolve_workers(workers)
        if nworkers > 1:
            return self._extract_parallel(matches, output_dir, nworkers)

        extracted = []

        for match in matches:
            if match.is_directory:
                continue

            out_path = output_dir / match.output_path

            # 确保父目录存在
            out_path.parent.mkdir(parents=True, exist_ok=True)

            # 流式提取 (低内存: 一个一个文件边解压边写, 不整体驻留内存)
            try:
                self._pkg_reader.extract_to_file(
                    match.volume_filename, match.file_info, out_path
                )
                # bc7prep 纹理解码 (仅当文件是 bc7prep 时整体处理)
                self._pkg_reader.decode_bc7prep_file(out_path)
                extracted.append(out_path)
            except (PkgError, OSError) as e:
                print(f"[ERROR] 提取失败 {match.vfs_path}: {e}")

        return extracted

    @staticmethod
    def _resolve_workers(workers: int) -> int:
        """解析并行进程数。

        - workers == 1: 顺序执行
        - workers > 1:  使用指定进程数
        - workers <= 0: 自动用 CPU 核数 (上限 8)
        """
        if workers == 1:
            return 1
        if workers > 1:
            return workers
        cpus = os.cpu_count() or 4
        return min(cpus, 8)

    def _extract_parallel(
        self,
        matches: list[FileMatch],
        output_dir: Path,
        workers: int,
    ) -> list[Path]:
        """多进程并行提取（每个文件一个任务, 流式解压写盘）。

        调度策略: 大文件优先提交, 避免大文件被大量小文件挤到任务队列尾部,
        导致最后的 worker 长时间空闲等待。
        """
        # 收集任务: 先建好所有父目录, 再分发到子进程
        file_matches = [m for m in matches if not m.is_directory]
        # 大文件优先 (解压后大小降序)
        file_matches.sort(key=lambda m: m.file_info.unpacked_size, reverse=True)

        tasks: list[tuple] = []
        for match in file_matches:
            out_path = output_dir / match.output_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tasks.append((
                str(self._pkgs_dir),
                match.volume_filename,
                match.file_info,
                str(out_path),
            ))

        extracted: list[Path] = []
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_parallel_extract_worker, t): t
                for t in tasks
            }
            for fut in as_completed(futures):
                task = futures[fut]
                out_path, err = fut.result()
                if err:
                    print(f"[ERROR] 提取失败 {task[1]}: {err}")
                else:
                    extracted.append(out_path)

        return extracted

    def _match_files(
        self,
        patterns: list[str],
        strip_prefix: bool = False,
    ) -> list[FileMatch]:
        """将 glob 模式转换为 FileMatch 列表"""
        # 收集匹配的文件条目
        matched_entries: dict[str, VfsEntry] = {}
        for pattern in patterns:
            for path, entry in self._file_tree.items():
                if fnmatch.fnmatch(path, pattern):
                    matched_entries[path] = entry

        # 计算公共前缀（用于 strip_prefix）
        common_prefix = ""
        if strip_prefix and matched_entries:
            paths = list(matched_entries.keys())
            common_prefix = os.path.commonpath(paths)
            # 确保前缀是完整目录名
            if common_prefix and '/' in common_prefix:
                common_prefix = common_prefix.rsplit('/', 1)[0] + '/'

        matches = []
        for path, entry in matched_entries.items():
            if entry.is_directory:
                matches.append(FileMatch(
                    vfs_path=path,
                    output_path=Path(path),
                    file_info=FileInfo(),
                    volume_filename="",
                    is_directory=True,
                ))
                continue
            if entry.file_info is None or entry.volume is None:
                continue

            # 计算输出路径
            if strip_prefix and common_prefix:
                rel_path = path[len(common_prefix):] if path.startswith(common_prefix) else path
            else:
                rel_path = path

            matches.append(FileMatch(
                vfs_path=path,
                output_path=Path(rel_path),
                file_info=entry.file_info,
                volume_filename=entry.volume.filename,
            ))

        return matches

    def extract_single(
        self,
        vfs_path: str,
        output_path: str | Path,
    ) -> Path:
        """提取单个文件到指定路径。

        参数:
            vfs_path: 虚拟路径（如 "content/GameParams.data"）
            output_path: 输出文件路径

        返回:
            写入的文件路径
        """
        entry = self._file_tree.get(vfs_path)
        if entry is None:
            raise ExtractorError(f"文件未找到: {vfs_path}")
        if entry.is_directory:
            raise ExtractorError(f"路径是目录: {vfs_path}")
        if entry.file_info is None or entry.volume is None:
            raise ExtractorError(f"文件信息不完整: {vfs_path}")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 流式提取 (低内存: 边解压边写)
        self._pkg_reader.extract_to_file(
            entry.volume.filename, entry.file_info, output_path
        )
        # bc7prep 纹理解码 (仅当需要时)
        self._pkg_reader.decode_bc7prep_file(output_path)
        return output_path

    def print_stats(self) -> None:
        """打印文件树统计信息"""
        stats = get_file_tree_stats(self._file_tree)
        print(f"游戏目录: {self._game_dir}")
        print(f"版本目录: {self._bin_folder}")
        print(f"IDX 文件数: {len(self._idx_files)}")
        print(f"PKG 目录: {self._pkgs_dir}")
        print(f"总条目: {stats['total_entries']}")
        print(f"文件: {stats['files']}")
        print(f"目录: {stats['directories']}")
        print(f"涉及卷: {len(stats['volumes'])}")

    def close(self) -> None:
        """释放资源"""
        self._pkg_reader.close()


# ── 便捷函数 ──────────────────────────────────────────────

def list_files(
    game_dir: str | Path,
    patterns: list[str] | None = None,
    bin_folder: str | None = None,
) -> list[VfsEntry]:
    """便捷函数：列出游戏资源文件。

    参数:
        game_dir: 游戏根目录
        patterns: glob 模式列表
        bin_folder: 指定版本

    返回:
        匹配的 VfsEntry 列表
    """
    extractor = GameExtractor(game_dir, bin_folder=bin_folder)
    try:
        return extractor.list_files(patterns)
    finally:
        extractor.close()


def extract_files(
    game_dir: str | Path,
    patterns: list[str],
    output_dir: str | Path,
    bin_folder: str | None = None,
    flatten: bool = False,
    strip_prefix: bool = False,
    dry_run: bool = False,
) -> list[Path]:
    """便捷函数：提取游戏资源文件。

    参数:
        game_dir: 游戏根目录
        patterns: glob 模式列表
        output_dir: 输出目录
        bin_folder: 指定版本
        flatten: 压平目录结构
        strip_prefix: 去除匹配前缀
        dry_run: 仅预览

    返回:
        已提取文件的路径列表
    """
    extractor = GameExtractor(game_dir, bin_folder=bin_folder)
    try:
        return extractor.extract(
            patterns, output_dir,
            flatten=flatten, strip_prefix=strip_prefix,
            dry_run=dry_run,
        )
    finally:
        extractor.close()
