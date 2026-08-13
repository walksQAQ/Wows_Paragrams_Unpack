# IDX 索引文件格式（.idx）

> 来源实现：`data_extractor/idx_parser.py`
> 参考：landaire/wows-toolkit Rust 源码

## 概述

`.idx` 索引文件描述了对应 `.pkg` 卷中存储的文件清单及元信息。每个 `.idx` 对应一个或多个 `.pkg` 卷文件。

## 文件头（16 字节）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u32 | magic = `0x50465349`（"ISPF"）|
| +0x04 | u32 | version |
| +0x08 | u32 | murmur hash（校验）|
| +0x0C | u32 | arch（架构 / 大小端）|

## 版本

- `0x01010004`（v0x20）：旧版 BigWorld 格式（Wargaming 早期）
- `0x02000000`（v0x40）：新版格式（当前 Lesta / WG 通用）

## 总体布局

文件头之后是 ResourceMetadata（版本相关：表数量、偏移指针），随后三张表：

- **Resources Table**：文件/目录条目（含父节点 ID 与文件名）
- **FileInfos Table**：每个文件在 `.pkg` 中的偏移、大小、压缩信息
- **Volumes Table**：卷 ID → `.pkg` 文件名映射

---

## v0x40（新版 Lesta / WG）

### ResourceMetadata（@0x10，40 字节）

`<IIIIQQQ>` = resources_count(u32) + file_infos_count(u32) + volumes_count(u32) + _unused(u32) + resources_table_ptr(u64) + file_infos_table_ptr(u64) + volumes_table_ptr(u64)

- 三个表指针是**相对于 meta_offset（0x10）**的偏移。

### Resources 表条目（32 字节）

`<QQQQ>` = resource_ptr(u64) + filename_ptr(u64) + id(u64) + parent_id(u64)

- filename 位于 `条目起始 + filename_ptr` 处，null 结尾（注意基准是条目起始，不是 +8）。

### FileInfos 表条目（48 字节）

`<QQQQIIII>` = resource_id(u64) + volume_id(u64) + offset(u64) + compression_info(u64) + size(u32) + crc32(u32) + unpacked_size(u32) + padding(u32)

### Volumes 表条目（24 字节）

`<QQQ>` = short_id(u64) + name_ptr(u64) + volume_id(u64)

- `name_ptr` 相对于**条目起始**（offset），不是 offset+8
- **volume_id 是第三个字段**，与 `FileInfo.volume_id` 匹配
- 文件名剥离 BigWorld 路径前缀 `//.//`

---

## v0x20（旧版 BigWorld）

### ResourceMetadata（@0x10，24 字节）

`<IIIIII>` = resources_count + resources_table_ptr + file_infos_count + file_infos_table_ptr + volumes_count + volumes_table_ptr

### Resources 表条目（24 字节）

`<QQII>` = name_hash(u64) + parent_id(u64) + name_len(u32) + name_ptr(u32)

- name 位于 `条目起始 + 16 + name_ptr`，长度 name_len，可能带 null 终止
- v0x20 无 resource_ptr 字段，此字段复用存放 name_hash

### FileInfos 表条目（48 字节）

`<QIIIIQQQ>` = offset(u64) + _padding(u32) + size(u32) + crc32(u32) + unpacked_size(u32) + compression_info(u64) + resource_id(u64) + volume_id(u64)

### Volumes 表条目（16 字节）

`<QII>` = volume_id(u64) + name_len(u32) + name_ptr(u32)

- name 位于 `条目起始 + 8 + name_ptr`

---

## 根节点判断（Lesta 关键差异）

- **Lesta 格式不使用** `ROOT_PARENT_ID`（`0xddb1a1d1b108b927`）
- 根级条目 → 父 ID 不在任何 resources_map 中
- `resolve_path` 检查 `parent_id not in resources_map` 判断根节点

## 压缩信息 compression_info

- `0x6`：原始存储（stored）—— PKG 数据即文件原始数据，见 pkg-format.md
- `0x700000006`：容器模式（container / Oodle Kraken）—— 数据带容器元数据头部，见 pkg-format.md
