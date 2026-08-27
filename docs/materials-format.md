# 材质格式参考（非 INDEXED）—— 官方 Mod SDK .mfm 明文样式

> 来源：用户提供的官方 Mod SDK 明文 `.mfm`（`PnFMods/ModsSDK.zip/JSB018_Yamato_1944/ship/` 下导出），
> 2026-08-19 归档。这是**非 INDEXED**（非 `0x0009` 材质 ID 分块）材质的权威属性参考，
> 与 `prototype-formats.md`（MaterialPrototype 二进制布局）互补：本文档讲**属性名/语义**，那个讲**字节布局**。
>
> 2026-08-27 更新：INDEXED 材质 `material_full.indexed` **确有 6 个 196×4 vec4 数组**
> （`albedoTintMatIdArr` / `albedoToRemoveTintMatIdArr` / `artStrengthMatIdArr` /
> `offsetScaleMatIdArr` / `rotationMatIdArr` / `tileIdxMatIdArr`）。
> 早前「只有 2 数组、offsetScaleMatIdArr 等不存在」的探针结论**已作废**。
> 详见 `docs/shaders-format.md` 与 `indexed-render-authoritative.md`。

> 注意：`.mfm` 里的贴图路径指向 Mod SDK 内部（`PnFMods/...`），**仅作属性与命名约定参考**；
> 实际渲染路径以客户端 assets.bin 的 `value_path` 为准（`material_full.textures` 已入库原始路径）。

## 非 INDEXED 材质技术族（fx）概览

| fx | 典型属性 | 用途 |
|----|----------|------|
| `ship_material.fx` / `PBS_ship.fx` | 5 贴图 + detail float | 舰体/上层标准 PBS |
| `wire_material.fx` | diffuse + metallicGloss | 栏杆/线缆 wire |
| `glass_material.fx` | diffuse + glass float | 玻璃/透明材质 |
| `grid_alpha.fx` | diffuse | 网格/线网 alpha |

## 1) 标准 PBS（ship_material.fx / PBS_ship.fx）

样例：`JSB039_Yamato_1945_Hull.mfm`、`JSB039_Yamato_1945_DeckHouse.mfm`、`C002_Razlom.mfm`

**贴图属性（5 张）**：

| 属性名 | 文件命名约定 | 说明 |
|--------|--------------|------|
| `ambientOcclusionMap` | `{stem}_ao.dds` | 环境光遮蔽 |
| `detailMap` | `ship_array_detail.dds`（共享） | 细节贴图 |
| `diffuseMap` | `{stem}_a.dds` | 主漫反射颜色 |
| `metallicGlossMap` | `{stem}_mg.dds` | 金属/粗糙度 |
| `normalMap` | `{stem}_n.dds` | 法线 |

**float 参数（detail 混合）**：

| 属性名 | 值 | 说明 |
|--------|----|------|
| `g_detailAlbedoInfluence` | 0.6 | 细节对漫反射影响 |
| `g_detailFadeDistance` | 5.0 | 细节淡出距离 |
| `g_detailGlossInfluence` | 1.0 | 细节对光泽影响 |
| `g_detailNormalInfluence` | 0.4 | 细节对法线影响 |
| `g_detailScaleU` / `g_detailScaleV` | 16 或 32 | 细节 UV 平铺（Hull/DeckHouse=32，C002_Razlom=16） |

## 2) wire（wire_material.fx）

样例：`JSB039_Yamato_1945_Hull_wire.mfm`

- 贴图：`diffuseMap`（`{stem}_a.dds`）、`metallicGlossMap`（`{stem}_mg.dds`）

## 3) glass（glass_material.fx）

样例：`transparent_glass_alpha.mfm`

- 贴图：`diffuseMap`
- float：`glassGlossiness=0.9`、`glassSpecular=0.04`、`glassTint=1.0`

## 4) grid alpha（grid_alpha.fx）

样例：`C011_Grid_9_alpha.mfm`

- 贴图：`diffuseMap`（`{stem}_a.dds`）

## 与当前实现的关系

- `assets_data.db / material_full` 已入库**全部材质**（29139 个）的 `shader_id`、全部贴图原始路径
  （`textures` JSON，含 `diffuseMap/ambientOcclusionMap/metallicGlossMap/normalMap/detailMap` 等）、
  `family`（`pbs` / `indexed` / `other`）、INDEXED 的 vec4 数组。
- `services/geometry_service.py::_resolve_material_full()` 从库返回 `tech_family` + `textures` + `indexed_params`，
  非 INDEXED 渲染目前优先读取 `diffuseMap`，并在 `renderer` 中按 `.dd0/.dd1/.dd2/.dds` 分级实时解包。
- `shader_id` 解析逻辑来自 `geometry_service._material_family()`：高 16 位 `0x0009` 归类为 `indexed`，`0x0005` 归类为 `pbs`，其余为 `other`。
- 本文档的 detail/glass 参数属于**语义参考**：它描述 `.mfm` 明文字段的命名/用途，但程序当前真正的渲染采样路径是数据库缓存后再按材质 family 选择渲染分支。

### 运行时解析方式（当前代码）

1. `assets_cache_service.populate()` 遍历所有 `.mfm`，读取 `shader_id`、名称哈希、属性类型和 `vec4` 数组，写入 `material_full` 和 `mfm_textures`。
2. `geometry_service._resolve_material_full()` 读取 `material_full`，构造：
   - `tech_family`
   - `textures`：`{name: 原始路径}`
   - `indexed_params`：含 `arrays`（真实 vec4 数组，见下） + 渲染回退参数 `offset`/`grid`
3. 真实贴图 bytes 在渲染阶段通过 `_load_texture_tier()` 从客户端 pkg 资源里按 `.dd0` → `.dd1` → `.dd2` → `.dds` 依次加载。

因此，本文档中的“属性名 / fx 语义”是对现有 `.mfm` 规范的说明，
而 `material_full` 表和 `geometry_service` 的分支判断则是当前程序真实的执行入口。

## 原始 .mfm 归档（Bandizip 临时解包）

原始文件位于 `f:\Bandizip_Temp\BNZ.6a849179c11de39\`（C002_Razlom / C011_Grid_9_alpha /
JSB039_Yamato_1945_Hull / JSB039_Yamato_1945_Hull_wire / transparent_glass_alpha）与
`BNZ.6a84917ec11f461\`（JSB039_Yamato_1945_DeckHouse）。
