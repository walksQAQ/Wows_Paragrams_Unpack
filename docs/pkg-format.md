# PKG 卷文件格式（.pkg）

> 来源实现：`data_extractor/pkg_reader.py`

## 概述

`.pkg` 是 BigWorld 资源卷，按 `FileInfo`（来自 `.idx`）指定的偏移/大小存储文件数据。
存储模式由 `FileInfo.compression_info` 决定。

## 存储模式

| compression_info | 模式 | 说明 |
|------------------|------|------|
| `0x6` | stored | PKG 中直接存储文件原始数据，无压缩/额外头部，`size == unpacked_size`。用于 GameParams.data、UIParams.data、splash、XML 等 |
| `0x700000006` | container | 数据带有容器元数据头部，数据部分为 **Oodle Kraken** 压缩流。用于 DDS 纹理、geometry 模型、visual 文件等 |

## 容器头部（container 模式）

```
偏移 0-7:   条目 0 大小 / 页大小 (u64)
偏移 8-11:  索引条目数 (u32)
偏移 12-15: 压缩类型 (u32, 通常为 1 = Oodle Kraken)
偏移 16-23: 解压后总大小 (u64)
偏移 24-31: 压缩数据总大小 (u64)
偏移 32+:   块描述符表 (4 字节 × N)
之后:       Oodle Kraken 压缩数据流
```

- `header_size = entry_size - compressed_size`
- `descriptors` 数量 = `(header_size - 32) // 4`
- 跳过头部后的数据是 **Oodle Kraken** 压缩流，由 `data_extractor/kraken.py` 解压

## 读取流程

1. 定位 PKG 中该 entry 区间（`offset` + `size`），低内存只读取该区间不加载整个卷
2. stored（0x6）：直接返回 PKG 原始数据
3. container（0x700000006）：解析容器头 → Kraken 解压 → bc7prep 纹理解码（如适用）
4. 未知 compression_info：抛 `PkgError`

## 流式提取（低内存）

- stored：1MB 分块拷贝，边读边写
- container：`decompress_stream` 逐块解压（≤256KB/块）直接写文件；非 restart 流抛 `KrakenStreamError` 回退整体解压
- 效果：216MB assets.bin 流式提取内存峰值从 ~216MB 降到几 MB，速度不变

## bc7prep 集成

- 解压后若为 bc7prep 纹理（DDS + DX10 头 148 字节之后 version == `0x7BC`），解码为标准 BC7
- `file_needs_bc7prep` 只读 196 字节头快速判断；`decode_bc7prep_file` 原地重写
- 详见 bc7prep-format.md
