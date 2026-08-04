"""
data_extractor —— 新一代战舰世界资源提取模块。

基于 landaire/wows-toolkit (Rust) 的 IDX/PKG 文件格式分析重新实现，
支持提取任意类型文件（.data, .png, .jpg, .xml, .model 等），
覆盖 pfsunpack2.exe / wowsunpack.exe 的全部功能。

架构概览::

    idx_parser.py    解析 .idx 索引文件 → 文件树
    pkg_reader.py    从 .pkg 卷文件中读取并解压数据
    extractor.py     高层编排：匹配 glob → 提取文件
    cli.py           命令行入口（测试用）

依赖： Python ≥ 3.10, 无第三方库依赖（仅使用标准库）。
"""

from data_extractor.idx_parser import (
    IdxFile,
    FileInfo,
    Volume,
    PackedFileMetadata,
    VfsEntry,
    parse_idx,
    build_file_tree,
    ROOT_PARENT_ID,
    IDX_MAGIC,
)

from data_extractor.pkg_reader import (
    PkgReader,
    PkgError,
)

from data_extractor.extractor import (
    GameExtractor,
    ExtractorError,
    list_files,
    extract_files,
)

__all__ = [
    # idx_parser
    "IdxFile", "FileInfo", "Volume", "PackedFileMetadata", "VfsEntry",
    "parse_idx", "build_file_tree", "ROOT_PARENT_ID", "IDX_MAGIC",
    # pkg_reader
    "PkgReader", "PkgError",
    # extractor
    "GameExtractor", "ExtractorError", "list_files", "extract_files",
]
