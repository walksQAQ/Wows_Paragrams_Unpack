"""uncode_assets —— assets.bin（PrototypeDatabase）浏览与解码模块。

按 `todo_list/New_function_of_unpack_assets_bin.md` 规划实现：

    parser.py     PrototypeDatabase 解析（header/strings/r2p/paths/databases）
    decoders.py   各 Prototype 类型 → 结构化 dict / JSON
    vfs.py        把 prototype 记录暴露为虚拟文件系统（按路径浏览）
    service.py    高层服务（从游戏 .pkg 提取 + 解析 + 浏览 + 解码）
    cli.py        命令行入口

Korabli（Lesta 服）为 12 个类型、blob index 映射与 WoWS 不同，
类型一律按 magic 识别（见 types.py）。
"""

from .errors import (
    AssetsBinError,
    InvalidMagicError,
    OutOfBoundsError,
    ParseError,
    PathNotFoundError,
    UnsupportedVersionError,
)
from .parser import (
    PrototypeDatabase,
    PrototypeLocation,
    parse_assets_bin,
)
from .types import (
    KORABLI_TYPES,
    PrototypeType,
    can_decode,
    can_decode_name,
    list_types,
    type_from_blob_index,
    type_from_extension,
    type_from_magic,
    type_from_name,
)
from .decoders import (
    decode_by_type,
    decode_prototype_to_json,
    decode_record,
    parse_mfm_from_db,
)
from .vfs import AssetsBinVfs, VirtualFile
from .service import AssetsBinService

__all__ = [
    "AssetsBinError", "InvalidMagicError", "OutOfBoundsError", "ParseError",
    "PathNotFoundError", "UnsupportedVersionError",
    "PrototypeDatabase", "PrototypeLocation", "parse_assets_bin",
    "KORABLI_TYPES", "PrototypeType", "type_from_blob_index", "type_from_extension",
    "type_from_magic", "type_from_name", "can_decode", "can_decode_name", "list_types",
    "decode_by_type", "decode_prototype_to_json", "decode_record", "parse_mfm_from_db",
    "AssetsBinVfs", "VirtualFile", "AssetsBinService",
]
