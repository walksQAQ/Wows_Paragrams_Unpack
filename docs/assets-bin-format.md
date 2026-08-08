# assets.bin（PrototypeDatabase / BWDB）格式

> 来源实现：`uncode_assets/parser.py`、`uncode_assets/types.py`
> 参考：wows-toolkit `crates/wowsunpack/src/models/assets_bin.rs`

## 概述

assets.bin 是游戏资源原型数据库（PrototypeDatabase），magic = `0x42574442`（"BWDB"），version = `0x01010000`。
Korabli（Lesta 服）正式服实测：约 217MB，680393 路径，12 个 blob。

## 文件头（16 字节）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u32 | magic = 0x42574442（"BWDB"）|
| +0x04 | u32 | version = 0x01010000 |
| +0x08 | u32 | checksum |
| +0x0C | u16 | architecture（64 位 = 0x40）|
| +0x0E | u16 | endianness |

## Body Header（96 字节 @0x10）

包含 5 段描述符（每段：count/capacity u32 + relptr i64）：

| 段 | 偏移 | 内容 |
|----|------|------|
| strings | +0x00 | offsets_map_capacity u32 @+0x00, buckets_relptr i64 @+0x08, values_relptr i64 @+0x10, string_data_size u32 @+0x18, string_data_relptr i64 @+0x20 |
| r2p | +0x28 | r2p_capacity u32 @+0x28, buckets_relptr i64 @+0x30, values_relptr i64 @+0x38 |
| paths | +0x40 | paths_count u32 @+0x40, paths_data_relptr i64 @+0x48 |
| databases | +0x50 | databases_count u32 @+0x50, databases_relptr i64 @+0x58 |

## 指针约定

- body 级 = body_base(0x10) + value
- 子段级 = section_base + value
- 条目级 = entry_base + value
- **0 = null**

指针为 i64 相对偏移。

## strings 段（字符串哈希表）

- offsetsMap：哈希表，capacity = 786433
  - buckets **8B/项**（仅 u64 key，空槽 key=0）—— 与 r2p 的 16B 不同，按 bucket_stride 自适应
  - values 4B/项（u32 字符串偏移）
- string_data：null 结尾字符串池
- 字符串按 **MurmurHash3_x86_32 的 u32 值**索引反查

## r2p 段（resourceToPrototypeMap）

- 哈希表：capacity = 786433
  - buckets **16B/项**（u64 key + u64 occupancy）
  - values 4B/项（u32 编码值）
- 开放寻址 + 线性探测，slot = `self_id % capacity`
- **r2p 值编码**：`value = (record_index << 8) | (blob_index * 4)`
  - `type_tag = value & 0xFF`，`record_index = (value >> 8) & 0xFFFFFF`，`blob_index = type_tag // 4`

## paths 段（pathsStorage）

- 每条目 32 字节：selfId u64 + parentId u64 + packed string @+0x10
- packed string 头 16B：char_count u32 + pad u32 + text_relptr i64（文本位于 `entry_base + 0x10 + text_relptr`）
- count = 699681（Korabli 正式服实测）

## databases 段（12 个 blob）

- 每条目 24 字节（0x18）：prototype_magic u32 + prototype_checksum u32 + size u32 + _pad u32 + data_relptr i64
- blob 头：16B（count u64 + header_size u64，header_size 恒 16）
- blob = 16B 头 + count × item_size 记录 + OOL（out-of-line）数据

## 类型表（Korabli 12 个，必须按 magic 识别）

| blob | 类型 | magic | item_size | 扩展名 |
|------|------|-------|-----------|--------|
| 0 | MaterialPrototype | 0x5069C471 | 0x88 | .mfm |
| 1 | SkeletonPrototype | 0xD9BB9F4A | 0x40 | .visual（@前缀）|
| 2 | VisualPrototype | 0x480DC57B | 0x80 | .visual |
| 3 | ModelPrototype | 0xA9576F28 | 0x20 | .model |
| 4 | ModelFbxPrototype | 0xDF80CF54 | 0x10 | .model_fbx |
| 5 | EffectPrototype | 0xEB23E0AF | 0x10 | |
| 6 | EffectPresetPrototype | 0x42E15336 | 0x10 | .effect_preset / .xml |
| 7 | EffectMetadataPrototype | 0xDFC8F8E0 | 0x10 | |
| 8 | AtlasContourProto | 0xF64359AA | 0x10 | .contours |
| 9 | MiscSettingsPrototype | 0xACE328C6 | 0x28 | |
| 10 | TrailPrototype | 0x42AF895E | 0x1A0 | .trail |
| 11 | VfxMaterialPrototype | 0xCD880533 | 0x210 | .vfx |

⚠️ **blob index → 类型映射与 WoWS 完全不同**（WoWS 只有 10 个类型），必须按 magic 识别类型。
WoWS 有而 Korabli 缺：SkeletonExtender(0x1AE023FF)、PointLight(0x0D3665A4)、VelocityField(0xAFD4A63F)。

## 路径解析

- selfId（路径哈希）→ pathsStorage 条目 → 沿 parentId 链重建完整路径
- `reconstruct_path`：BFS 拓扑传播 / 沿 parentId 回溯（循环与越界保护）
- r2p 查找 selfId → (blob, record) 定位记录

## VFS 索引缓存

- 以（文件大小, mtime）sha1 作 key，存到 assets.bin 旁 `.uncode_cache/idx_<hash>.pkl`
- 缓存版本 `CACHE_VERSION`（目录 key 修复后加版本使旧缓存失效）
- 二次打开约 1.6s（首次约 8.5s）

## 记录布局

各 Prototype 的具体记录布局见 prototype-formats.md。
