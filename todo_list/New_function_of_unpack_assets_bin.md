# assets.bin（PrototypeDatabase）提取与解码功能规划

> 注意：此条目前为半成品
>
> 格式说明：assets.bin 的格式权威文档见 `docs/assets-bin-format.md`；Korabli 逆向详情见 `docs/assets-bin-format.md` 与 `/memories/repo/assets-bin-korabli.md`。本文件的「二、assets.bin 格式」章节为早期规划草稿，以 docs 文档为准。

## 概述

在当前纯 Python 解包器（`data_extractor/`）基础上，新增对 `content/assets.bin`（BigWorld **PrototypeDatabase**）的**提取 + 解码**能力，实现类似 [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) 的 `AssetsBinVfs` / `decode_prototype_to_json` 功能：把二进制 prototype 记录解码为可读 **JSON/XML**（含粒子效果、材质、视觉原型等）。

参考项目（Rust 实现，已逆向并文档化）：
- `crates/wowsunpack/src/models/assets_bin.rs` — PrototypeDatabase 解析
- `crates/wowsunpack/src/data/assets_bin_vfs.rs` — 把 prototype 暴露为虚拟文件
- `crates/wowsunpack/src/models/{material,visual,model}.rs` — 各 prototype 类型解码
- `docs/MODELS.md` — 完整格式文档（Binary Ninja 逆向）

---

## 一、现状与目标

### 现状（已完成）
- `data_extractor/` 已能提取 `content/assets.bin` 的**原始字节**（`compression_info=0x700000006` container/Kraken 解压，大小 227,301,560B，已通过 10000 文件 CRC 回归）
- 粒子效果 XML（`helpers/particles/sfx_fail.xml`、`postfx_animations.xml`）为**明文 stored XML**，已能直接提取
- 粒子纹理（`particles/textures/particles.{atlas,dds,dd0,dd1,dd2}`）已能提取，dd0/dd1 自动解码为标准 BC7

### 目标（待实现）
1. **解析** `assets.bin` 的 PrototypeDatabase 索引（字符串表、r2p 哈希表、路径树、10 个数据库 blob）
2. **按路径浏览**：重建文件路径树，暴露每个 prototype 记录为虚拟文件
3. **解码**：Material / Visual / Model / SkeletonExtender 等 prototype → 可读 JSON
4. **粒子效果**：解析 VisualPrototype 中引用的粒子系统定义，结合明文粒子 XML 输出完整粒子描述

---

## 二、assets.bin 格式（PrototypeDatabase）

> ⚠️ **重要：本节底部为 Korabli 实测数据。wows-toolkit 的 `docs/MODELS.md` 逆向自 `WorldOfWarships64.exe`（国际服），Korabli（Lesta 服）实测存在差异，**不能直接套用 WoWS 的 blob 顺序/类型表**。具体差异见 §2.10。

> 来源：wows-toolkit `docs/MODELS.md`（Binary Ninja 逆向自 `WorldOfWarships64.exe`），源码 `resmgr_prototype_database.cpp` + **Korabli 实测逆向（2026-08-01）**

### 1. 文件头 Header（16 字节 @0x00）

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 4 | u32 | magic = `0x42574442` (`BWDB`) |
| 0x04 | 4 | u32 | version = `0x01010000` |
| 0x08 | 4 | u32 | checksum |
| 0x0C | 2 | u16 | architecture |
| 0x0E | 2 | u16 | endianness |

### 2. Body Header（0x60 = 96 字节 @0x10）

五段索引的描述符，**指针均为 i64 相对偏移**：

| 偏移 | 大小 | 类型 | 字段 | 所属段 |
|------|------|------|------|--------|
| +0x00 | 4 | u32 | offsetsMap.capacity | strings |
| +0x04 | 4 | pad | | |
| +0x08 | 8 | i64 | offsetsMap.buckets_relptr | strings |
| +0x10 | 8 | i64 | offsetsMap.values_relptr | strings |
| +0x18 | 4 | u32 | stringData.size | strings |
| +0x1C | 4 | pad | | |
| +0x20 | 8 | i64 | stringData.relptr | strings |
| +0x28 | 4 | u32 | resourceToPrototypeMap.capacity | r2p |
| +0x2C | 4 | pad | | |
| +0x30 | 8 | i64 | r2p.buckets_relptr | r2p |
| +0x38 | 8 | i64 | r2p.values_relptr | r2p |
| +0x40 | 4 | u32 | pathsStorage.count | paths |
| +0x44 | 4 | pad | | |
| +0x48 | 8 | i64 | pathsStorage.data_relptr | paths |
| +0x50 | 4 | u32 | databasesCount | databases |
| +0x54 | 4 | pad | | |
| +0x58 | 8 | i64 | databases.relptr | databases |

### 3. 指针约定（关键）

- **Body 级字段**：`body_base(0x10) + value`
- **子段字段**（r2p/paths）：`section_base + value`，其中 `section_base = body_base + section_offset`
- **条目级字段**：`entry_base + value`
- `value == 0` 表示空指针

### 4. Strings Section（字符串表）

- `offsetsMap`：哈希表，buckets 8B/项 + values 4B/项，映射字符串哈希 → 字符串偏移
- `stringData`：null 结尾字符串池
- 用于把 MaterialPrototype 里的**属性名哈希**反查为名字（MurmurHash3_x86_32）

### 5. ResourceToPrototypeMap（r2p 哈希表）

开放寻址 + 线性探测：
- **buckets**：capacity × **16B**（`u64 key` + `u64 occupancy`，1=占用/0=空）
- **values**：capacity × **4B**（u32）：
  ```
  value = (record_index << 8) | (blob_index * 4)
  ```
  - 低字节 `value & 0xFF` = `blob_index * 4`（类型标签）
  - 高 24 位 `value >> 8` = blob 内记录索引
  - 槽位：`slot = key % capacity`

### 6. PathsStorage（路径树）

条目数组，每个含 `(selfId u64, parentId u64, name 字符串)`。通过 parentId 构建目录树，得到完整资源路径（如 `content/gameplay/.../foo.visual`）。`selfId` 是 r2p 哈希表的 key。

### 7. Database Entries（数据库描述符数组）

`databasesCount × 0x18 (24B)`：

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 4 | u32 | prototypeMagic（类型名哈希，加载时校验） |
| 0x04 | 4 | u32 | prototypeChecksum |
| 0x08 | 4 | u32 | size（数据 blob 字节数） |
| 0x0C | 4 | pad | |
| 0x10 | 8 | i64 | data_relptr（相对 entry_base → u8[] blob） |

各 blob 连续占据文件剩余部分。

### 8. Prototype Types（Korabli 实测：12 个，全部已识别）

> ⚠️ 下表为 **Korabli 实测**（2026-08-01 解压 `content/assets.bin` + 从 `Korabli64.exe` 提取字符串 + MurmurHash3_x86_32 匹配类型名）。WoWS 是 10 个类型，Korabli 是 **12 个**，且 **blob index 顺序不同**！

| Korabli idx | Magic | 类型名 | Item Size | count | size | 备注 |
|-----|--------|------|-----------|-------|------|------|
| 0 | 0x5069C471 | MaterialPrototype | 0x78 | 28,822 | 10.9MB | ✅ 与 WoWS 同 |
| 1 | 0xD9BB9F4A | **SkeletonPrototype** | 0x40 | 38,287 | **73.1MB** | 🆕 Korabli 独有（非 WoWS 的 SkeletonExtender）|
| 2 | 0x480DC57B | VisualPrototype | 0x70 | 118,502 | 44.5MB | ✅ |
| 3 | 0xA9576F28 | ModelPrototype | 0x28 | 118,530 | 3.8MB | ✅ |
| 4 | 0xDF80CF54 | **ModelFbxPrototype** | 0x10 | 0 | 16B | 🆕 空 blob |
| 5 | 0xEB23E0AF | EffectPrototype | 0x10 | 2,469 | 17.3MB | ✅（粒子！） |
| 6 | 0x42E15336 | EffectPresetPrototype | 0x10 | 1,689 | 27KB | ✅ |
| 7 | 0xDFC8F8E0 | EffectMetadataPrototype | 0x10 | 1,689 | 468KB | ✅ |
| 8 | 0xF64359AA | AtlasContourProto | 0x10 | 285 | 606KB | ✅ |
| 9 | 0xACE328C6 | **MiscSettingsPrototype** | 0x28 | 1 | 33.7KB | 🆕 |
| 10 | 0x42AF895E | **TrailPrototype** | 0x1a0 | 29 | 19.6KB | 🆕（粒子轨迹）|
| 11 | 0xCD880533 | **VfxMaterialPrototype** | 0x210 | 3 | 4.9KB | 🆕 |

> 🔑 **识别方法**：从 `bin/8861049/bin64/Korabli64.exe`（42.5MB）提取 ASCII 字符串，计算 MurmurHash3_x86_32 匹配各 blob 的 prototypeMagic，一次命中全部 12 个类型名。

### 8.1 Korabli vs WoWS 差异分析（逆向结论）

- **数据库数量**：Korabli 12 个，WoWS 10 个
- **一致的类型 magic（7 个）**：Material / Visual / Model / Effect / EffectPreset / EffectMetadata / AtlasContour
- **WoWS 有、Korabli 缺失**：SkeletonExtender (0x1AE023FF)、PointLight (0x0D3665A4)、VelocityField (0xAFD4A63F)
- **Korabli 独有新类型（5 个，已识别）**：`SkeletonPrototype`(0xD9BB9F4A,76MB)、`ModelFbxPrototype`(0xDF80CF54,空)、`MiscSettingsPrototype`(0xACE328C6)、`TrailPrototype`(0x42AF895E,粒子轨迹)、`VfxMaterialPrototype`(0xCD880533)
- **blob index → 类型映射完全不同**：Korabli 的 blob 1 是 Skeleton（不是 Visual），blob 2 是 Visual 等。**必须按 magic 识别类型，不能按 index 套用 WoWS 表**
- 头部（BWDB magic / version / body header 布局）与 WoWS **一致**，仅类型集合不同
- **粒子系统类（exe 内 fx 命名空间，供参考）**：`ParticleActionPrototype`/`EmitterPrototype`/`TrailPrototype`/`VectorGenerator*Prototype`/`Action*Prototype`（Tint/Scale/Jitter/Force/Orbitor/Resizer/Barrier 等）/`VfxMaterialPrototype`——粒子由 EffectPrototype 组合这些子原型构成

### 8.2 Korabli 逆向验证步骤

**✅ 已完成**（2026-08-01，用 exe 字符串 + MurmurHash3 匹配）：
- 12 个 blob 的 prototypeMagic 全部识别为类型名（见 §8）
- 确认 7 个类型与 WoWS 一致，5 个为 Korabli 独有
- 方法：从 `Korabli64.exe` 提取 ASCII 字符串 → 计算 MurmurHash3_x86_32 → 匹配 magic

**✅ 已完成**（2026-08，Ghidra MCP 二进制逆向 5 个新类型的 item_size 与记录布局）：
- 逆向方法链：search_strings(类型名) → xrefs(注册函数) → 注册表条目[7]=deserialize → 复制/批量/逐记录解析(字段名在错误日志) → 实际 blob 数据验证
- **SkeletonPrototype**（0xD9BB9F4A, item_size=0x40）：count u32 + rotationLimitsCount u32 + 7 relptr（nameMapNameIds u32[] / nameMapNodeIds u16[] / nameIds u32[] / matrices 4x4float[] / rotationLimits Vec4×2[] / rotationLimitsIds u16[] / parentIds u16[]），relptr 基准=记录起始 → OOL
- **TrailPrototype**（0x42AF895E, item_size=0x1a0）：8×纹理{flags,pad,relptr,pad}→OOL 路径 + color/size/emission 关键帧(relptr→(time,value)[]) + Vector2/Vector4/float 属性 + u8 technique/bool 区（字段名 57 个）
- **VfxMaterialPrototype**（0xCD880533, item_size=0x210）：3×shader 路径 + cpuProperties(0x60B) + 3×Properties 块(0x80B each: 8×u16 count + planeDesc + 10×u64 relptr)
- **MiscSettingsPrototype**（0xACE328C6, item_size=0x28）：3×u16 count + 4×u64 relptr(necessary/optional/redundant/structuralNameIds → u32[])
- **ModelFbxPrototype**（0xDF80CF54, item_size=0x10）：空 blob（count=0）
- 完整布局已记录于 /memories/repo/assets-bin-korabli.md

**待完成**（需要 Binary Ninja 级反汇编，或数据推断）：
1. **新类型的 item_size 与记录布局**：SkeletonPrototype / ModelFbxPrototype / MiscSettingsPrototype / TrailPrototype / VfxMaterialPrototype 的固定记录步长与字段
   - 方法 A（数据推断）：blob 头 count + 扫描记录中 i64 相对指针规律
   - 方法 B（二进制）：分析 exe 中对应类的 `deserialize` 函数（Binary Ninja）
2. **精确解析 pathsStorage**：修正 packed string 解析（2/4 字节长度前缀 + 对齐），重建 699,681 条完整路径树
3. **扩展名 → 类型映射**：统计各 blob 下文件扩展名，验证类型推断
4. **校验 7 个已知类型**：Material/Visual/Model 记录布局抽样解码，与 WoWS 对比

> 已确认：头部（BWDB/version/body header 布局）、r2p 编码、数据库 blob 结构（16B 头 + 记录 + OOL）与 WoWS 一致。

### 9. Database Blob 结构

```
+0x00  8    count        (u64 — 记录数)
+0x08  8    header_size  (u64 — 恒为 16)
+0x10  N*item  固定大小记录（每条 item_size 字节）
+...   OOL 数据（变长数组、字符串，记录内 i64 相对指针指向这里）
```

- **相对指针基准** = 所在结构起始（顶层记录字段 → 记录起始；子结构字段 → 子结构起始）
- `get_prototype_data(location, item_size)`：返回从记录起始到 blob 末尾的切片（保证 OOL 指针可解析）

---

## 三、分步实现方案

### 步骤 1：提取 assets.bin 原始字节（已完成基础）

- 用 `PkgReader.read_file('...', file_info)` 提取，Kraken 解压得到 227MB 明文
- **内存注意**：227MB 解压 + 解析索引，需控制峰值 <2GB（见第五节）
- 验证：提取后 CRC 与 idx 一致

### 步骤 2：解析 PrototypeDatabase（`services/assets_bin_service.py` 新建）

**⚠️ 先完成 Korabli 逆向验证**（见 §2.10），再移植解析器。

按上文格式实现：
1. `parse_header` — 校验 `BWDB` magic / version
2. `parse_body_header` — 读 5 段描述符（相对偏移解析）
3. `resolve_hashmap` — 通用哈希表解析（bucket_stride / value_stride 参数化）
4. `parse_strings` — 字符串池 + offsetsMap
5. `parse_r2p` — 资源→prototype 位置哈希表
6. `parse_paths_storage` — 路径条目数组
7. `parse_database_entries` — **12 个** blob（按 magic 识别类型，不按 index）
8. `build_self_id_index` / `resolve_path` — 路径后缀 → (blob_index, record_index)

**参考**：wows-toolkit `models/assets_bin.rs`（直接逐行移植标量逻辑，与 kraken.py 做法一致）；但类型表用 §2.10 的 Korabli 实测

### 步骤 3：构建 AssetsBinVfs（虚拟文件系统）

- 遍历 pathsStorage，用 r2p 把有 prototype 的路径注册为虚拟文件
- 每个文件 = 记录起始 → blob 末尾的字节切片（保留 OOL 指针解析空间）
- 提供 `list_dir` / `open_file` / `files_with_type` 接口
- 复用现有 `file_tree` 的浏览 UI 思路

**参考**：wows-toolkit `data/assets_bin_vfs.rs`

### 步骤 4：解码各 prototype 类型 → JSON

按类型实现 `decode_*_to_json`（✅ 已全部实现，`uncode_assets/decoders.py`，Korabli 正式服实测步长）：
- **MaterialPrototype**（blob 0，**0x88B/条**）：属性表 ✅
  - `+0x00 u16 count, +0x02 u16 flags, +0x08 u32 shader, +0x18 names_ptr → u32[count] 属性名哈希, +0x20 type_idx_ptr → u16[count](低4位类型/高12位索引), +0x28~+0x70 9 个类型指针(bool/int32/floatA/floatB/tex/vec2/vec3/vec4/mat4), +0x78 material_hash`
  - 用 strings 表把属性名哈希反查为名字（MurmurHash3_x86_32）
- **VisualPrototype**（blob 2，**0x80B/条**）：渲染集合，含 `render_sets/lods`（geometry/primitives/材质 mfm/节点）✅，并新增 `particle_refs`（扫描渲染集合 OOL 中可反查的粒子路径）✅
- **ModelPrototype**（blob 3，**0x20B/条**）：模型引用（model/visual 资源路径）✅
- **Skeleton/Trail/VfxMaterial/MiscSettings**（Korabli 独有）：✅ 已逆向结构化解码
- **EffectPrototype**（blob 5，0x10B/条，粒子效果图）：✅ `decode_effect` 尽力解析（见步骤 5）

**参考**：wows-toolkit `models/{material,visual,model}.rs` + `scripts/decode_mfm.py`（已有 Python 版 Material 解码参考）

### 步骤 5：粒子效果 XML 提取 / 解码

- **明文粒子 XML**（`helpers/particles/sfx_fail.xml`、`postfx_animations.xml`）：stored 明文，直接提取 ✅（已验证）
- **EffectPrototype 解码**（✅ 2026-08-05 新增 `decode_effect`，数据驱动逆向）：
  - 记录 0x10B：`+0x00 f32 scalar（常为 -1.0）+ 0x04 u32 count + 0x08 u32 relptr（基准=blob 起点）+ 0x0C pad`
  - OOL 区域 = [relptr, 下一记录 relptr)，相邻记录首尾相接无间隙
  - 输出 `embedded_strings`（内嵌原始粒子资源路径，实测如 `particles/animated/Smoke_2_8x8.dds`、`particles/textures/circle_02.tga`、`sparks`、`glow_0`）+ 16B 对齐候选节点头（启发式）
  - ⚠️ 尽力解析（wows-toolkit 亦无结构化解码）；完整节点语义需 exe deserialize 逆向
- **VisualPrototype 粒子引用**（✅ 2026-08-05）：`decode_visual` 新增 `particle_refs`，扫描 render_sets/lods OOL 中可反查的粒子路径
- **组合输出**（❌ 未实现）：把 VisualPrototype 引用的粒子系统 + 明文粒子 XML + 粒子图集纹理组合为可读的粒子描述（XML/JSON）——如需可后续补充

### 步骤 6：UI / CLI 集成

- 在现有 PySide6 应用中新增"Assets.bin 浏览/解码"页面（复用 detail_panel 的 StackedWidget 模式）
- 或提供 `data_extractor/` CLI：`--assets <path>` 列出原型，`--assets-decode <path>` 解码为 JSON
- 参考现有 `ui/` 与 `services/` 分层

---

## 四、粒子效果相关文件清单（已确认）

| 路径 | 模式 | 说明 | 状态 |
|------|------|------|------|
| `helpers/particles/sfx_fail.xml` | stored(0x6) 明文 | 完整粒子系统定义（renderer/texture/ramp） | ✅ 可直接提取 |
| `postfx_animations.xml` | stored(0x6) 明文 | 后期特效动画定义 | ✅ 可直接提取 |
| `particles/textures/particles.{dds,dd0,dd1,dd2}` | container(0x700000006) | 粒子图集纹理（DXT5，dd0/dd1 含 bc7prep） | ✅ 可提取+解码 |
| `particles/textures/particles.atlas` | stored(0x6) | 图集布局 | ✅ 可直接提取 |
| `content/assets.bin` | container(0x700000006) | PrototypeDatabase（含 Visual/Material 粒子引用） | ⏳ 本规划实现解码 |
| `content/particles/mesh/*.geometry` | container(0x700000006) | 粒子网格 | ✅ 可提取（几何解析另规划） |

---

## 五、内存约束（硬性 <2GB）

- assets.bin 解压后 **227MB**，解析时避免整体再复制
- 用 **mmap 或 seek+read 按段读取**，索引结构用紧凑 Python 类型
- 不要像 `_load_pkg` 旧版那样把多个大文件同时驻留内存
- 解码单条 prototype 记录时只保留该记录 + OOL 切片
- 完成后 `clear_cache()` / `close()` 释放

---

## 六、验证方式

1. **索引正确性**：解析后 databases 计数应为 **12**（非 WoWS 的 10），各 blob 记录数与实测一致（Material 28,822 / Visual 118,502 / Model 118,530 / Effect 2,469 等）
2. **路径解析**：随机路径 `resolve_path` 应命中预期的 (blob, record)，且类型按 magic 识别正确
3. **Material 解码**：属性名哈希能反查为字符串，解码结果与 `scripts/decode_mfm.py` 逻辑一致
4. **Visual 解码**：能提取粒子系统/贴图引用，与明文粒子 XML 交叉验证
5. **类型映射**：7 个已知类型的记录布局抽样解码，与 WoWS 文档对比；5 个新类型完成逆向识别
6. **内存**：全程峰值 <2GB

---

## 参考资源

- wows-toolkit `docs/MODELS.md`：assets.bin / .geometry / .visual 完整格式文档（权威）
- wows-toolkit `crates/wowsunpack/src/models/assets_bin.rs`：PrototypeDatabase 解析参考
- wows-toolkit `scripts/decode_mfm.py`：Python 版 MaterialPrototype 解码参考（可直接借鉴）
- 新代码现有基础：`data_extractor/kraken.py`（纯 Python 解压）、`pkg_reader.py`（seek+read 低内存提取）
