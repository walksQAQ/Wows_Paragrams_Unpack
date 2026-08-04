"""assets.bin（PrototypeDatabase）解码相关的异常定义。"""


class AssetsBinError(Exception):
    """assets.bin 解析/解码过程中的基础错误。"""


class InvalidMagicError(AssetsBinError):
    """文件头 magic 校验失败。"""

    def __init__(self, actual: int, expected: int = 0x42574442):
        super().__init__(f"invalid magic: 0x{actual:08X} (expected 0x{expected:08X})")


class UnsupportedVersionError(AssetsBinError):
    """不支持的版本号。"""

    def __init__(self, actual: int, expected: int = 0x01010000):
        super().__init__(f"unsupported version: 0x{actual:08X} (expected 0x{expected:08X})")


class OutOfBoundsError(AssetsBinError):
    """数据越界。"""

    def __init__(self, offset: int, need: int = 0, have: int = 0, what: str = "offset"):
        if need and have:
            msg = f"{what} at 0x{offset:X} extends beyond data (need {need}, have {have})"
        else:
            msg = f"{what} out of bounds at 0x{offset:X}"
        super().__init__(msg)
        self.offset = offset


class ParseError(AssetsBinError):
    """解析错误。"""


class PathNotFoundError(AssetsBinError):
    """路径未能解析到 prototype 记录。"""

    def __init__(self, path: str, detail: str = ""):
        msg = f"path not found: {path}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


class PrototypeOutOfRangeError(AssetsBinError):
    """prototype 记录索引超出 blob 记录数。"""

    def __init__(self, record_index: int, blob_index: int, count: int):
        super().__init__(
            f"prototype index {record_index} out of range for blob {blob_index} (count: {count})"
        )
