"""
PKG 卷文件读取器。

从 .pkg 二进制卷文件中按偏移读取并解压数据。

存储模式（由 FileInfo.compression_info 决定）::

    compression_info == 0x6  ("stored" 模式)
        PKG 中直接存储文件原始数据，无压缩和额外头部。
        size == unpacked_size

    compression_info == 0x700000006  ("container" 模式)
        PKG 中存储的数据带有容器元数据头部。数据部分使用
        **Oodle Kraken** 算法压缩。
        跳过头部后得到 Kraken 压缩流，用纯 Python 解压器解码。

容器头部格式::

    偏移 0-7:   条目 0 大小 / 页大小 (u64)
    偏移 8-11:  索引条目数 (u32)
    偏移 12-15: 压缩类型 (u32, 通常为 1=Oodle Kraken)
    偏移 16-23: 解压后总大小 (u64)
    偏移 24-31: 压缩数据总大小 (u64)
    偏移 32+:   块描述符表 (4 字节 × N)
    之后:       Oodle Kraken 压缩数据流
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

from new_extractor.idx_parser import FileInfo


# ── 压缩信息常量 ──────────────────────────────────────────

STORED_FLAG: int = 0x6                # 原始存储（stored）
CONTAINER_FLAG: int = 0x700000006     # 容器模式（Oodle Kraken 压缩）


class PkgError(Exception):
    """PKG 读取相关错误"""
    pass


class PkgReader:
    """PKG 卷文件读取器。

    按需缓存 .pkg 文件内容，支持按 FileInfo 定位并提取数据。
    container 模式通过 ``new_extractor.kraken`` 纯 Python 实现解压 Oodle Kraken 流。
    """

    def __init__(self, pkgs_dir: str | Path):
        """
        参数:
            pkgs_dir: 包含 .pkg 文件的目录路径（通常是 res_packages）
        """
        self._pkgs_dir = Path(pkgs_dir)
        if not self._pkgs_dir.exists():
            raise PkgError(f"PKG 目录不存在: {self._pkgs_dir}")
        self._cache: dict[str, bytes] = {}
        self._kraken_available = self._check_kraken()

    @property
    def pkgs_dir(self) -> Path:
        return self._pkgs_dir

    def _load_pkg(self, filename: str) -> bytes:
        """将 .pkg 文件加载到内存（带缓存）"""
        if filename not in self._cache:
            pkg_path = self._pkgs_dir / filename
            if not pkg_path.exists():
                raise PkgError(f"PKG 文件不存在: {pkg_path}")
            self._cache[filename] = pkg_path.read_bytes()
        return self._cache[filename]

    @staticmethod
    def _check_kraken() -> bool:
        """检查纯 Python Kraken 解压器是否可用"""
        try:
            from new_extractor.kraken import decompress  # noqa: F401
            return True
        except ImportError:
            return False

    # ── 容器头部解析 ──────────────────────────────────────

    @staticmethod
    def parse_container_header(entry_data: bytes) -> dict:
        """解析容器模式 PKG 条目的头部。

        返回包含头部元数据的字典:
            header_size: 头部总大小
            compressed_size: 压缩数据区大小
            unpacked_size: 解压后总大小
            num_blocks: 索引条目数
            comp_type: 压缩类型
            descriptors: 块描述符列表
        """
        h0 = struct.unpack_from('<Q', entry_data, 0)[0]
        num_blocks = struct.unpack_from('<I', entry_data, 8)[0]
        comp_type = struct.unpack_from('<I', entry_data, 12)[0]
        unpacked_size = struct.unpack_from('<Q', entry_data, 16)[0]
        compressed_size = struct.unpack_from('<Q', entry_data, 24)[0]
        header_size = len(entry_data) - compressed_size

        desc = []
        desc_count = (header_size - 32) // 4
        for i in range(desc_count):
            desc.append(struct.unpack_from('<I', entry_data, 32 + i * 4)[0])

        return {
            "h0": h0, "num_blocks": num_blocks, "comp_type": comp_type,
            "unpacked_size": unpacked_size, "compressed_size": compressed_size,
            "header_size": header_size, "descriptors": desc,
        }

    # ── 主读取接口 ────────────────────────────────────────

    def read_file(self, volume_filename: str, file_info: FileInfo) -> bytes:
        """从指定卷中读取一个文件。

        自动检测存储模式:
        - 0x6 (stored): 直接返回 PKG 原始数据
        - 0x700000006 (container): 跳过容器头, 用 Kraken 解压器解压

        参数:
            volume_filename: .pkg 文件名
            file_info: 文件的 FileInfo

        返回:
            解包后的完整文件字节数据
        """
        pkg_path = self._pkgs_dir / volume_filename
        if not pkg_path.exists():
            raise PkgError(f"PKG 文件不存在: {pkg_path}")
        # 低内存: 只读取该 entry 区间, 不加载整个卷
        with open(pkg_path, 'rb') as f:
            f.seek(file_info.offset)
            entry_data = f.read(file_info.size)

        if len(entry_data) < file_info.size:
            raise PkgError(
                f"文件 {volume_filename} 偏移 {file_info.offset}+{file_info.size} "
                f"超出范围"
            )

        # ── stored 模式: 直接返回 ────────────────────────
        if file_info.compression_info == STORED_FLAG:
            return entry_data

        # ── container 模式: Kraken 解压 ──────────────────
        if file_info.compression_info == CONTAINER_FLAG:
            if not self._kraken_available:
                raise PkgError(
                    f"container 模式需要 Kraken 解压器\n"
                    f"new_extractor/kraken.py 未正确加载"
                )
            meta = self.parse_container_header(entry_data)
            from new_extractor.kraken import decompress as kraken_decompress
            compressed = entry_data[meta["header_size"]:]
            data = kraken_decompress(
                compressed, meta["unpacked_size"]
            )
            data = self._decode_bc7prep(data)
            return data

        # ── 未知模式 ────────────────────────────────────
        raise PkgError(
            f"未知 compression_info=0x{file_info.compression_info:x} "
            f"({volume_filename} @ {file_info.offset})"
        )

    def read_file_direct(self, volume_filename: str,
                         offset: int, size: int,
                         compression_info: int = 0) -> bytes:
        """直接从卷中读取一段原始数据（低级接口, 低内存 seek+read）。"""
        pkg_path = self._pkgs_dir / volume_filename
        if not pkg_path.exists():
            raise PkgError(f"PKG 文件不存在: {pkg_path}")
        with open(pkg_path, 'rb') as f:
            f.seek(offset)
            data = f.read(size)
        if len(data) < size:
            raise PkgError(
                f"文件 {volume_filename} 偏移 {offset}+{size} 超出范围"
            )
        return data

    # ── bc7prep 纹理解码 ─────────────────────────────────

    @staticmethod
    def _decode_bc7prep(data: bytes) -> bytes:
        """若解压结果是 bc7prep 纹理 (Oodle Texture BC7 预处理), 解码为标准 BC7。

        bc7prep 头位于 DDS+DX10 头 (148 字节) 之后: version=0x000007BC。
        解码输出与 pfsunpack2 逐字节一致 (100% 无损位重排)。
        """
        if len(data) < 196:
            return data
        # DDS magic + DX10 fourcc + bc7prep version
        if data[:4] != b'DDS ':
            return data
        if struct.unpack_from('<I', data, 148)[0] != 0x000007BC:
            return data
        try:
            from new_extractor.bc7prep import bc7prep_decode
            pixels = bc7prep_decode(data[196:], len(data) - 196, data[148:196])
            header = bytearray(data[:148])
            # Oodle Texture 在 DDS 保留字段 offset40 写入 0x1 标记; 解码后清零 (与 pfsunpack2 一致)
            struct.pack_into('<I', header, 40, 0)
            return bytes(header) + pixels
        except Exception:
            # 解码失败时回退到原始数据 (保持可用性)
            return data

    def clear_cache(self) -> None:
        """清除缓存的 PKG 数据"""
        self._cache.clear()

    def close(self) -> None:
        """释放所有资源"""
        self._cache.clear()
