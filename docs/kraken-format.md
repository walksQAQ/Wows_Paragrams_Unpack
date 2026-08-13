# Oodle Kraken 压缩流格式

> 来源实现：`data_extractor/kraken.py`
> 参考：domdfcoding/kraken-decompressor (GPLv3) C++ 源码 / oozextract / powzix

## 概述

纯 Python 实现的 Oodle 数据压缩（Kraken / Mermaid / Leviathan / BitKnit）解压器。
核心：**Oodle 3-Stream Huffman 解码（Type 1/2）+ TANS 熵解码 + LZ77 匹配复制 + RLE**。

## 顶层结构

整个压缩流由若干 256KB 逻辑块组成，每块以 **Kraken 头** 起始（`(offset & 0x3FFFF) == 0` 处解析）。

### Kraken 头（`_parse_kraken_header`）

首字节 `b`：

- 低 4 位必须为 `0xC`，`(b >> 4) & 3` 必须为 0
- bit7 = **restart**（1：每块独立解码）
- bit6 = **uncompressed**（1：原始数据直拷）

第二字节：

- 低 7 位 = **decoder_type**
- bit7 = **use_checksums**

支持的 decoder_type：**5, 6, 10, 11, 12**

### Quantum 头（`_parse_quantum_header`，3 字节）

`v = (p[0] << 16) | (p[1] << 8) | p[2]`

- `size = v & 0x3FFFF`（18 位）
- size != 0x3FFFF：`compressed_size = size + 1`，flag1/flag2 在高位
- size == 0x3FFFF 且 `(v >> 18) == 1`：memset 块，`compressed_size = 0`，checksum 在下一字节
- use_checksums 时后跟 3 字节 checksum

### 块大小限制（chunk_limit）

| decoder_type | chunk_limit |
|--------------|-------------|
| Kraken(6) / Mermaid(10) / Leviathan(12) | 0x40000（256KB）|
| BitKnit(11) | 0x4000（16KB）|

## 未压缩块

`uncompressed=1` 时直接拷贝 chunk_limit 字节原始数据。

## memset / 整块匹配块

`compressed_size == 0` 时：

- whole_match_distance != 0：从历史窗口复制
- 否则：填充 checksum 字节（memset）

## 量子块解码（`_decode_quantum`，256KB 内）

每个量子块内按 128KB（0x20000）chunk 处理，每 chunk 有 3 字节**反序块头**
`ch = src[sp+2] | (src[sp+1] << 8) | (src[sp] << 16)`：

- bit23 = 0：纯熵解码（`_decode_bytes`，按 chunk_type 分流）
- bit23 = 1：LZ 块
  - `src_used = ch & 0x7FFFF`，`mode = (ch >> 19) & 0xF`
  - src_used < chunk_sz：读 LZ 表 → LZ 匹配复制
  - src_used == chunk_sz 且 mode == 0：原始直拷

### offset 语义（决定 LZ 表是否读 initial 8 字节）

- **restart 块**：相对块起点（`dp - dst_off`），首个 chunk offset == 0 → 读 initial 8 字节，窗口基址 = dst_off
- **非 restart 块**：绝对输出位置（dp），offset == 0 仅当是整个文件第一个块，窗口基址 = 0（共享整个文件窗口）

## 熵编码 chunk_type（`_decode_bytes`）

chunk 首字节 `chunk_type = (src[0] >> 4) & 0x7`：

| chunk_type | 解码方式 |
|------------|----------|
| 0 | 原始数据直拷 |
| 1 | TANS 熵解码 |
| 2 | Type 1 Huffman（3-stream）|
| 3 | RLE |
| 4 | Type 2 Huffman（3-stream）|
| 5 | 递归（MultiArray 等）|

## 各 decoder 的 LZ 表

- **Kraken（6）**：`_read_lz_table` + `_process_lz_runs`（type0 / type1 两种模式）
- **Mermaid（10）**：`_read_lz_table_mermaid` + `_process_lz_runs_mermaid`
- **Leviathan（12）**：`_read_lz_table_leviathan` + `_process_lz_runs_leviathan`

LZ 表 = lit 流（熵解码）+ cmd 流 + packed offsets（`_unpack_offsets` 解包）+ packed lens + 可能的 initial 8 字节原始数据。

### ⚠️ Leviathan mode=4（O1 预测）关键实现细节

lit 流指针从 `stream+1` 开始（流[0] 被 next_lit 初始消费），Python 中 `li[i]` 必须从 1 开始，
否则 O1 字面量索引偏 1 → 解压数据错。修复后 AM825 (texanim) 通过，Leviathan 859/859 CRC 通过。

## restart=True 流式解压

- **Korabli pkg 的 Kraken 流 restart=True**（每 256KB 块独立解码）→ 可逐块流式解压
- `decompress_stream(src, dst_len)` 生成器：逐块 yield，输出与 `decompress` 逐字节一致
- 遇 restart=False 抛 `KrakenStreamError`，调用方回退到 `decompress`
- 10000 文件回归（6000 container + 4000 stored）100% CRC 通过

## 性能实测

- 纯 Python ~1MB/s（对比原生 Oodle >500MB/s，慢约 500x）
- 有效提速 = 多进程并行（ProcessPoolExecutor，大文件优先调度），8 核约 4.4x
- 已知失败方案（勿重复尝试）：
  1. Cython 直接编译整个 kraken.py —— 行为差异（quantum decode failed）
  2. `kraken-decompressor` (pip, C++) —— 只支持单块纯 Kraken，多块失败
  3. powzix/ooz C 库 —— 单块 Mermaid/Leviathan 不兼容 Korabli 数据，多块全失败
  4. 纯 Python 内联优化 `_process_lz_runs_mermaid` —— 反而变慢 17%，已回滚
