# 材质格式参考（非 INDEXED）—— 官方 Mod SDK .mfm 明文样式

> 来源：用户提供的官方 Mod SDK 明文 `.mfm`（`PnFMods/ModsSDK.zip/JSB018_Yamato_1944/ship/` 下导出），
> 2026-08-19 归档。这是**非 INDEXED**（非 `0x0009` 材质 ID 分块）材质的权威属性参考，
> 与 `prototype-formats.md`（MaterialPrototype 二进制布局）互补：本文档讲**属性名/语义**，那个讲**字节布局**。
>
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
  `family`（pbs/indexed/other）、INDEXED 的 vec4 数组。
- `_resolve_material_full(mfm)` 从库返回 `tech_family` + `textures`（路径）+ `indexed_params`，
  非 INDEXED 渲染目前主要用 `diffuseMap`（`_load_texture_tier` 实时解包）。
- 本文档的 detail/glass 参数可作后续完善非 INDEXED PBS 渲染（细节混合、玻璃折射/透明）的参考。

## 原始 .mfm 归档（Bandizip 临时解包）

原始文件位于 `f:\Bandizip_Temp\BNZ.6a849179c11de39\`（C002_Razlom / C011_Grid_9_alpha /
JSB039_Yamato_1945_Hull / JSB039_Yamato_1945_Hull_wire / transparent_glass_alpha）与
`BNZ.6a84917ec11f461\`（JSB039_Yamato_1945_DeckHouse）。
