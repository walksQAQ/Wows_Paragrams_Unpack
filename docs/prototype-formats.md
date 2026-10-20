# Prototype 记录格式（assets.bin 各类型）

> 来源实现：`uncode_assets/decoders.py`、`uncode_assets/types.py`
> 逆向方法：Korabli64.exe 字符串 + MurmurHash3_x86_32 匹配 + 真实数据驱动

## 指针基准约定

除非特别说明，相对指针的基准 = **记录起始**（`get_prototype_data` 返回记录起始到 blob 末尾的切片）。
Visual / Effect 的 relptr 基准为 **blob 起点**（标注）。

> 实际代码已确认：`uncode_assets/decoders.py` 里 `decode_visual()`、`decode_material()`、`decode_model()` 都按“记录起始”为相对基准解包；
> 旧的 WoWS 0x80 视觉条目推断已被修正为 Korabli 实测的 `0x40` 记录大小。

### 关键实现态势

- `uncode_assets/types.py` 中 `type_from_magic()` 为主识别入口，`blob_index` 仅作兜底。
- `decode_visual()` 中 `render_sets_count` 在 `+0x30`，`render_sets relptr` 在 `+0x38`；
  OOL 区域边界要看“下一记录的同偏移 relptr”，不能直接假设固定 `0x80` 步长。
- `decode_material()` 中 `type_idx` 的低 4 位编码为值类型，`name_hash` 通过 `strings` 段反查；
  这也是当前数据库缓存侧 `material_full` 的来源。

## 通用 blob 布局

```
blob = 16B 头（count u64 + header_size u64）
     + count × item_size 记录
     + OOL（out-of-line）数据
```

- 记录相对 blob 起点的绝对偏移 = `16 + record_index × item_size`
- OOL 数据通常为紧凑数据（非对齐，不可直接结构映射）
- 记录起始到 blob 末尾的切片中，relptr 基准 = 记录起始（下标 0）

---

## MaterialPrototype（0x5069C471，item_size=0x88，blob 0）

Korabli 布局相对 WoWS 的 0x78 整体偏移 +8，字段 8 字节对齐，**指针 u64，基准 = 记录起始**：

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u16 | property_count |
| +0x02 | u16 | flags（材质自身标记；**不是** SDK 明文的 `<collisionFlags>`，见下）|
| +0x08 | u32 | shader_id |
| +0x18 | u64 | names_ptr（属性名哈希 u32 数组）|
| +0x20 | u64 | type_idx_ptr（u16 数组）|
| +0x28 | u64 | 标志区（每属性 u32，值恒 1，忽略）|
| +0x30 | u64 | bool 值数组指针 |
| +0x38 | u64 | int32 值数组指针 |
| +0x40 | u64 | float_a 值数组指针 |
| +0x48 | u64 | float_b 值数组指针 |
| +0x50 | u64 | texture 值数组指针（u64 路径哈希）|
| +0x58 | u64 | vec2 值数组指针 |
| +0x60 | u64 | vec3 值数组指针 |
| +0x68 | u64 | vec4 值数组指针 |
| +0x70 | u64 | mat4 值数组指针 |
| +0x78 | u64 | material_hash（= fx 资源在路径树中的 selfId）|

- **material_hash 不是哈希值**：它是 assets.bin `pathsStorage` 的 selfId，
  用 `PrototypeDatabase.resolve_self_path()` 可直接解析出 fx 完整路径
  （如 `shaders/std_effects/PBS_ship.fx`）。Lesta 28,822 个材质 100% 可解析，
  WG 布局中对应 +0x68。
- **type_idx 编码**：低 4 位 = 类型，高 12 位 = 索引
  - 0=bool, 1=int32, 2=float_a, 3=float_b, 4=texture, 5=vec2, 6=vec3, 7=vec4, 8=matrix4x4
- 值元素大小：bool 1B / int32 4B / float 4B / tex u64 hash / vec2 8B / vec3 12B / vec4 16B / mat4 64B
- 属性名用 **MurmurHash3_x86_32** 哈希（name_ids 为哈希值，经 strings 段反查，找不到输出 `0xXXXXXXXX`）
- 例：diffuseMap=2182021760, artMap=1835779052, materialIdMap=2195144431, normalMap=1213756509

### 数组属性的长度（type_idx 高 12 位 = pidx）

同一类型的属性共享一段**连续**值数组：把该类型的属性按 pidx 排序，**相邻 pidx 间距**就是前一组的元素数
（INDEXED 的 6 个数组 pidx = 0/196/392/588/784/980，间距 196）。

最后一组没有“下一组”可参照，必须用 **OOL 区边界**：
`ptr + pidx*elem` 一直延续到下一个 OOL 块起点（属性名数组 → 类型索引数组 → 各类型值数组按类型升序紧密排列），
最后一块到后继记录的 OOL 起点为止（`uncode_assets.decoders.material_array_lengths()`）。

> 若沿用前一组间距，`RSD100_Shaumian_1942.mfm` 这类「6 个 196 项数组 + 末尾单个 vec4
> `blendNoiseParams`」会多读 195 项，读进**下一条材质的 OOL 数据**，表现为
> `blendNoiseParams` 出现 `1e28` / `1e36` 这类明显不合理的数值。

### `<collisionFlags>` 口径（Lesta 26.10 vs WG 15.9 SDK 实测）

- **与 +0x02 的 flags 无关**：两个 SDK 里该行取值**恒为 0**
  （Lesta 26.10 共 13,068 处、WG 15.9 全部 29,184 个 `.mfm`），
  而同名材质在 assets.bin 里的 flags 常见 1/2/3（Lesta）或 0x101/0x102/0x300（WG）。
  wows-toolkit 也把 +0x02 记为 `unknown (layer count?)`。
- **两服写法不同**：
  - WG 15.9：**每个** `.mfm` 都写 `<collisionFlags> 0`（含 `grid_alpha` / `glass` 等）。
  - Lesta 26.10：只有 63.5% 写（13,068 / 20,591），且按 fx 家族区分：
    `glass_material` / `ship_mesh_decal` / indexed 系列 ≈ 0%，`grid_alpha` 0.4%、
    `grid_alpha_skinned` 4.9%，而 `ship_material` 75.8%、`PBS_ship_skinned` 91.6%。
- 本工具统一按 **WG 口径**：明文里始终写 `<collisionFlags> 0`（`mfm_text.format_mfm_text`），
  JSON 另以 `flags` 保留二进制原始值。

---

## VisualPrototype（0x480DC57B，item_size=0x80，blob 2）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | vec3 | bbox1 min |
| +0x10 | vec3 | bbox1 max |
| +0x20 | u64 | geometry 资源ID（.geometry）|
| +0x28 | u64 | primitives 资源ID（.primitives）|
| +0x30 | u64 | render_sets_count |
| +0x38 | u64 | render_sets relptr（**基准 = blob 起点**）|
| +0x40 | vec3 | bbox2 min |
| +0x50 | vec3 | bbox2 max |
| +0x60 | u64 | geometry2 资源ID |
| +0x68 | u64 | primitives2 资源ID |
| +0x70 | u64 | lods_count |
| +0x78 | u64 | lods relptr |

### render_sets / lods OOL 结构（`_ool_items`）

每项 = `{ shape_vertices: '*.vertices', shape_indices: '*.indices', material: 'SHIPMAT_*', material_mfm: '*.mfm'（u64 selfId 反查）, nodes: ['Scene Root' / '*_Jnt_BlendBone'] }`

- 项以 `'*.vertices'` 为边界分组
- nodes 可能跨项归属；mfm 实为整组共享的 skinned 蒙皮文件（归入区末项，近似）
- **区边界**：render_sets 区 = [rs_pos, lod_pos)；lods 区 = [lod_pos, 下一记录 render_sets_rel)（从 `data[0x80 + 0x38]` 读下一记录 relptr 定界，否则越界把后续记录也算进来）
- 每项引用均经 selfId 反查验证真实有效

---

## ModelPrototype（0xA9576F28，item_size=0x20，blob 3）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u64 | model_resource_id（.model 路径 selfId，可为 0）|
| +0x08 | u64 | visual_resource_id（.visual 路径 selfId）|
| +0x10 | 2×f32 | 距离/尺寸参数（3/8/10/16/400/50000…）|
| +0x18 | u32 | count（多数 11，少数 8/9/10）|
| +0x1C | u32 | tail（通常 0）|

---

## SkeletonPrototype（0xD9BB9F4A，item_size=0x40，blob 1，Korabli 独有）

Lesta 骨架系统（非 WoWS SkeletonExtender）。记录 64B，**u32 相对指针，基准 = 记录起始**：

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u32 | count（节点数）|
| +0x04 | u32 | rotationLimitsCount |
| +0x08 | u32 | nameMapNameIds → u32[count]（名称 hash 映射）|
| +0x10 | u32 | nameMapNodeIds → u16[count]（节点 id 映射）|
| +0x18 | u32 | nameIds → u32[count]（节点名 hash）|
| +0x20 | u32 | matrices → 4x4float[count]（单位矩阵）|
| +0x28 | u32 | rotationLimits → Vec4×2[rotLimitsCount]（min/max 角度 ±360）|
| +0x30 | u32 | rotationLimitsIds → u16[count] |
| +0x38 | u32 | parentIds → u16[count]（父节点，0xFFFF=根）|

OOL 起始 = `rec_base + count × item_size`（紧凑数据，非对齐）。

---

## TrailPrototype（0x42AF895E，item_size=0x1A0，blob 10，Korabli 独有）

粒子轨迹。**u32 相对指针，基准 = 记录起始**：

| 区域 | 偏移 | 说明 |
|------|------|------|
| 纹理 ×8 | 0x00-0x70 | 每条 16B `{flags u32 + pad u32 + relptr u32 @+8 + pad u32}` → OOL 路径字符串：albedoTexture / hatTexture / beamMaskTexture / gradientTexture / normalTexture / emissionTexture / distortionTexture / dissolveTexture |
| 关键帧 relptr | 0x80 / 0x88 / 0x90 | colorKeyFrame / sizeKeyFrame / emissionKeyFrame → `(time:float, value:float)[count]` |
| +0x98 | u32 | lockAxis |
| +0x144 | u32 | pathPointCount |
| vec2 | 0xA4-0xFC | 12×Vector2：uvScale / uvOffset / uvScroll / emissionBounds / cameraFade / uvDistortionScale / uvDistortionScroll / distortionStrength / beamSize / uvBeamScroll / uvBeamScale / uvBeamSplit |
| vec4 | 0x104-0x134 | 4×Vector4 颜色：hatColor / beamHeadColor / beamSplitColor / beamTailColor |
| +0x148 / +0x14C / +0x150 | u32 | colorKFCount / sizeKFCount / emissionKFCount |
| float ×15 | 0x154-0x18C | dissolveStart / dissolveStrength / lifetime / minSpawnDistance / maxSpawnDistance / hatDistance / hatSize / beamDistance / beamFadeIn / beamFadeOut / fadeIn / fadeOut / spawnAngle / directDiffuseMultiplier / indirectDiffuseMultiplier |
| +0x191 | u8 | beamTechniqueType |
| bool ×8 | 0x192-0x199 | isBeamEnable / isHatEnable / isSoftIntersectionEnabled / isLockAxisEnabled / isInstantDeath / isDistortionEnabled / isDissolveEnabled / isEmissionEnabled |

> relptr 指向 OOL 字符串时偶有截断偏差，解码时已加可读性保护（无法解析为合法路径的置空）。

---

## VfxMaterialPrototype（0xCD880533，item_size=0x210，blob 11，Korabli 独有）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | packed string | pathToEmitter（`{size u64, relptr u64}`，基准 = 结构起始）|
| +0x10 | packed string | SimulationShader |
| +0x20 | packed string | RenderingShader |
| +0x30 | - | cpuProperties 块（0x60B，布局未逐字段逆向）|
| +0x90 / +0x110 / +0x190 | - | emitter / simulation / rendering Properties 块（0x80B each）|

packed string 示例：`shaders/gpuvfx_effects/vfx/emitter/primitive_emitter.fx`。

---

## MiscSettingsPrototype（0xACE328C6，item_size=0x28，blob 9，Korabli 独有）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | u16 | necessaryCount |
| +0x02 | u16 | optionalCount |
| +0x04 | u16 | redundantCount |
| +0x06 | u16 | extraCount |
| +0x08 | u64 | structuralNameIds relptr → u32[] |
| +0x10 | u64 | necessaryNameIds relptr → u32[] |
| +0x18 | u64 | optionalNameIds relptr → u32[] |
| +0x20 | u64 | redundantNameIds relptr → u32[] |

count 与 relptr 一一对应：0x00→0x08, 0x02→0x10, 0x04→0x18, 0x06→0x20（基准 = 记录起始）。

---

## EffectPrototype（0xEB23E0AF，item_size=0x10，blob 5，粒子效果图）

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0x00 | f32 | scalar（常 -1.0 或正数如 9.5，语义未知）|
| +0x04 | u32 | count（子节点/条目数）|
| +0x08 | u32 | relptr（本记录 OOL 区域起点，**基准 = blob 起点**）|
| +0x0C | u32 | pad |

- OOL 区域 = [relptr, 下一记录 relptr)，**相邻记录首尾相接无间隙**（rec0 0x9A90 → rec1 0xAEAF → ...单调递增）
- OOL 内含**内嵌原始字符串**（非 strings 表，如 `particles/animated/Smoke_2_8x8.dds`、`particles/textures/circle_02.tga`、`sparks`、`glow_0`、`Biggy_fire_2`）→ `_extract_ascii_strings` 提取
- OOL 内重复 `-1.0f/1.0f + u32 count + u32 偏移 + pad` 16B 节点模式 → `candidate_nodes`（16B 对齐启发式扫描）
- 尽力解析（wows-toolkit 亦无结构化解码）

---

## 其它类型（0x10 item_size，generic 兜底）

- **EffectPresetPrototype**（0x42E15336）：.effect_preset / .xml
- **EffectMetadataPrototype**（0xDFC8F8E0）
- **AtlasContourProto**（0xF64359AA）：.contours
- **ModelFbxPrototype**（0xDF80CF54）：空 blob（count=0，16B 占位）

generic 解码：输出原始字节 + 按 8B 步长解析 u64 相对指针字段（基准 = 记录起始），启发式解析 ASCII 字符串。

## 解码器清单（DECODABLE_TYPES）

Material / Skeleton / Visual / Model / MiscSettings / Trail / VfxMaterial / Effect

### 扩展名 → 类型映射（2026-08-03 实测）

- `.mfm` → Material
- `.visual` → Visual（主）或 Skeleton（路径带 `'@'` 前缀，二义）
- `.model` → Model
- `.effect_preset` / `.xml` → EffectPreset
- `.contours` → AtlasContour
- `.trail` → Trail
- `.vfx` → VfxMaterial
- Effect / EffectMetadata / MiscSettings / ModelFbx 无扩展名
