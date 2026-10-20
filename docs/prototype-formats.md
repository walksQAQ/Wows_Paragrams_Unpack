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
| +0x02 | u16 | **含义未定**的打包字段（低字节 0..3 / 高字节仅 WG 非 0），原样输出 `flags` |
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
| +0x78 | u64 | fxPathId（= fx 资源在路径树中的 selfId）|
| +0x80 | u32 | sortOrder（-1 = 未设置；仅少数 mesh_decal 为 1..4）|

> Korabli 记录里**没有** `collisionFlags` 字段（`Korabli64.exe` 里连这个字符串都不存在）。

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

### `collisionFlags` / `sortOrder`：字段语义（exe 反汇编 + 引擎源码 + 数据实测）

**落位（Ghidra 反编译核对，不是猜的）**：WoWS 客户端在启动时注册 `MaterialPrototype` 类型
（类型名字符串 + 记录步长 `0x78` + murmur3 类型哈希），字段注册表按名给出 record 偏移。

**WG 侧**（`WorldOfWarships64.exe` 全量分析后反编译 `FUN_14046ae80` 的尾部，字段名与偏移成对出现）：

```c
plVar4[lVar8*3 + 2] = "fxPathId";        /* 前一行 param_1[1] = lVar7 + 0x68 → +0x68 */
...
local_30 = 0x70;
local_38 = "collisionFlags";
FUN_14046d210(param_1, &local_38);       /* → collisionFlags @ +0x70 */
local_30 = 0x74;
local_38 = "sortOrder";
FUN_14046d210(param_1, &local_38);       /* → sortOrder @ +0x74 */
return param_1;                          /* 表到此结束 → 记录步长 0x78 */
```

同一函数里还能看到 `matrixValues @ +0x60`、`vector4Values @ +0x58`（与 `type_ptrs[8]` 布局吻合）。

| 字段 | WG（item 0x78） | Korabli（item 0x88） |
|---|---|---|
| `fxPathId` | `+0x68` u64 | `+0x78` u64 |
| `collisionFlags` | `+0x70` u32（`-1` = 未设置） | **记录里没有这个字段** |
| `sortOrder` | `+0x74` u32（`-1` = 未设置） | `+0x80` u32（`-1` = 未设置） |

旁证（Ghidra `search_strings` 全量）：`WorldOfWarships64.exe` 有 `collisionFlags` / `sortOrder` /
`fxPathId` 各 1 处，**`CollisionFlags`（首字母大写）与 `materialKind` 均为 0 处**；
`Korabli64.exe` 只有 `fxPathId` / `sortOrder` 各 1 处，`collisionFlags` / `materialKind` 为 0 处。

Lesta 侧用 **Ghidra 反编译**（`Korabli64.exe -26.10ST2`，71,730 个函数）核对过字段注册函数
`FUN_140643320` 的尾部，字段表到 `sortOrder` 就结束了：

```c
param_1[1] = lVar6 + 0x78;   /* → "fxPathId"  @ +0x78 */
...
param_1[1] = lVar6 + 0x80;   /* → "sortOrder" @ +0x80 */
return param_1;              /* 之后不再注册任何字段 → +0x84 是填充 */
```

配合数据实测（`+0x84` 在 29,377 条记录里全为 0），可确认 Korabli 的二进制原型
**没有** `collisionFlags` 字段：

- `<collisionFlags>` 只存在于 **Mod SDK 明文**（Lesta 26.10 有 13,068 处、值全为 0），
  属于导出器沿用共享代码留下的**残留标签**——`Korabli64.exe` 里连这个字符串都没有
  （ASCII / UTF-16 均为 0 处），客户端不会解析它；
- 碰撞相关的运行时接口是另一套：`collisionMaterialName` / `getCollisionMaterialsNum`
  （Python API，碰撞材质名），与 `collisionFlags` 无关。

**实测取值**：

| 字段 | WG（31,534 个材质） | Lesta（29,377 个） |
|---|---|---|
| `collisionFlags` | **全部 0** | 无字段 → 固定 0 |
| `sortOrder` | 31,518 个 `-1`；16 个 `mesh_decal` 为 1..4 | 29,376 个 `-1`；1 个为 2 |

- WG 那 16 个非默认值全在 `mesh_decal.fx`，且与贴花层级一一对应：
  `..._grass`=1、`..._road`=2、`..._sand3`=3、`..._grass2`=4
  （`pillar_Meshdecal2..5` 同样 1..4）—— 即**贴花叠放顺序**。
- `collisionFlags` 全 0，恰好解释了 Mod SDK 明文里 `<collisionFlags>` 恒为 `0`
  （Lesta 26.10：13,068 处、WG 15.9：29,184 处）：不是导出器"丢弃真实值"，而是
  **内容从来没人设置过这个字段**。

**位定义**（`WorldTriangle::flags_` 低字节，`uncode_assets.decoders.COLLISION_FLAG_BITS`）：

| bit | 名称 | 含义 |
|-----|------|------|
| 0x01 | `CAMERANOCOLLIDE` | 相机可穿透（螺旋桨 / gizmo / 装饰薄片 / 草） |
| 0x02 | `TRANSPARENT` | 镂空/alphaTest 面：不算实体、不投影 |
| 0x04 | `BLENDED` | 混合队列 |
| 0x08 | `TERRAIN` | 地形 |
| 0x10 | `NOCOLLIDE` | 角色不碰撞（相机仍碰撞） |
| 0x20 | `DOUBLESIDED` | 双面 |
| 0x40 | `WATER` | 水面 |
| 0x80 | `PROJECTILENOCOLLIDE` | 弹道不碰撞（0xff 整体 = 不进 BSP） |

**怎么填这个值**：8 位 bitmask，任意组合按位或。引擎读法
（`lib/moo/material.cpp::readCollisionFlags`）是 `asInt()` 后**只取低 8 位**
（`packed.bytes.low_low = (uint8)cflags`），`-1` = 不设置（保持默认/继承）。

| 想要的效果 | 单值 | 十进制 |
|---|---|---|
| 相机可穿透 | `0x01` | 1 |
| 镂空 / 透明面（不算实体、不投影） | `0x02` | 2 |
| 混合队列 | `0x04` | 4 |
| 地形 | `0x08` | 8 |
| 角色不碰撞（相机仍碰） | `0x10` | 16 |
| 双面 | `0x20` | 32 |
| 水面 | `0x40` | 64 |
| 弹道不碰撞 | `0x80` | 128 |

常用组合：

| 组合 | 值 | 十进制 |
|---|---|---|
| 相机可穿透 + 镂空 | `0x03` | 3 |
| 镂空 + 双面 | `0x22` | 34 |
| 相机可穿透 + 镂空 + 双面 | `0x23` | 35 |
| 角色不碰撞 + 双面 | `0x30` | 48 |
| 除「弹道不碰撞」外全开 | `0x7F` | 127 |
| 除「相机可穿透」外全开 | `0xFE` | 254 |

> ⚠️ **`0xFF` = 255 不是"全开"，而是哨兵 `TRIANGLE_NOT_IN_BSP`**：`lib/physics2/bsp.cpp` 里
> 所有碰撞/射线遍历都先判 `if (candidate.collisionFlags() != TRIANGLE_NOT_IN_BSP)`，
> 命中 255 的三角形**直接跳过** —— 等于这块面从碰撞场景里彻底消失
> （`BSPTree::canCollide()` 也靠它判断整个模型还有没有可碰撞三角形）。
> 所以"能开的都开"要写 `0x7F`(127) 或 `0xFE`(254)，**别写 255**。

补充：
- `TERRAIN`(0x08) / `WATER`(0x40) 由地形/水面系统给三角形打，写在**模型材质**上语义无意义。
- 引擎里**没有**「材质属性 → 这些位」的自动换算：`calculateMaterialFlags()`
  （`lib/chunk/server_super_model.cpp`）里 `Alpha_test → TRANSPARENT`、
  `Alpha_blended → BLENDED`、`Double_sided → DOUBLESIDED` 那段是**整段注释掉的**，
  实际生效的只有 `packFlags(collisionFlags, materialKind)`（原样打包）；
  运行时 `Moo::EffectMaterial::getFlags()` 同样只做打包。所以想要这些碰撞行为，
  **必须在 `<collisionFlags>` 里显式写位**。
- 那些位在引擎里通常由别处写入：`TRIANGLE_TERRAIN` ← 地形块；`TRIANGLE_WATER` ← 水面
  (`server_chunk_water.cpp`)；`TRIANGLE_NOCOLLIDE` / `TRIANGLE_DOUBLESIDED` ← 编辑器与
  贴花/植被的 BSP 重映射；`TRIANGLE_PROJECTILENOCOLLIDE` ← SpeedTree（树干/树叶）；
  `TRIANGLE_BLENDED` 全仓库没有赋值点，只在相机碰撞里被读
  (`base_camera.cpp`: `ignoreFlags(TRANSPARENT|BLENDED|CAMERANOCOLLIDE)`)。

### 记录 `+0x02` u16：含义未定的打包字段（旧版本文档曾误标为 `collisionFlags`）

旧版本把这个 u16 的**低字节**当成 `collisionFlags`——**已证伪**：真正的 `collisionFlags`
在 `+0x70` 且全为 0。`+0x02` 是另一个字段，工具原样输出为 `flags` / `flags_high`：

- 低字节实测 `0..3`（WG 0×30,012 / 1×944 / 2×573 / 3×5；Lesta 0×27,919 / 1×861 /
  2×595 / 3×2），与碰撞相关属性高度相关：低字节=2 的材质 90% 有 `alphaTestEnable`、
  96% 有 `doubleSided`；=1 的 34% / 50%（螺旋桨 87% 落在 1）。
- 高字节仅 WG 非 0，且**完全由属性集决定**（31,534 个材质归成 686 种属性名签名，
  每个签名对应的高字节唯一，0 个歧义）：

  | 值 | 占比 | 特征 |
  |----|------|------|
  | 0 | 29,667（94.1%） | 普通材质，无 alphaTest / 无动画 |
  | 1 | 748（2.4%） | alphaTest 变体：90.4% `alphaTestEnable`、91.7% `alphaReference`、57.5% `doubleSided`、常带 `detailMap` |
  | 2 | 199（0.6%） | 动态自发光/UV 动画：98.0% `animMap`、99.5% 有 emissive 参数 |
  | 3 | 838（2.7%） | 纹理动画：98.1% `g_texanimFrameNum` |
  | 4 | 82（0.3%） | 纹理动画 + alphaTest：100% `g_texanimFrameNum`、96.3% `alphaTestEnable` |

- 跨服 19,156 个同名材质对比：低字节只差 53 个（0.28%），高字节差 653 个且**全是
  「WG 非 0 / Lesta 为 0」**（Lesta 未使用该字节）。
- 它不出现在 `MaterialPrototype` 的字段注册表里（`fxPathId` / `collisionFlags` /
  `sortOrder` 才是），所以拿不到官方字段名；按数据特征看像是**打包的（变体号<<8 | 渲染相关位）**，
  目前只输出不解释，明文也不回写。

**Mod SDK 明文口径**（实测 Lesta 26.10 / WG 15.9）：`<collisionFlags>` 一律写 `0`
（13,068 / 29,184 处，等于真实值）；`<sortOrder>` **完全不导出**（0 处命中）。
本工具的处理：

- **WG**：始终写 `<collisionFlags>0</collisionFlags>`（与 SDK 一致）；
- **Lesta**：**不写这一行** —— Korabli 的二进制原型没有该字段（上文 Ghidra 反编译），
  客户端也不解析这个标签，写出来只会是"看起来像数据、其实没人读"的噪音；
- `sortOrder`：两服都只在 JSON 里保留，不写明文（二进制里有但 SDK 不导出，写了不算官方口径）。

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
