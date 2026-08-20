# INDEXED 材质（材质 ID 分块涂装）特殊渲染规则实施

> 📌 **状态：待办（2026-08-19 记录，稍后实施）**
>
> 背景：`assets_data.db` 的 `material_full` 表已入库全部材质（含 162 个 INDEXED 材质），
> `_resolve_material_full` 已能返回 `tech_family=indexed` + 贴图路径 + `indexed_params`（vec4 数组）。
> 但**渲染器尚未应用 INDEXED 的特殊渲染规则**（目前只按普通 PBS 渲染）。
> 需参考全部反编译/逆向内容后实施，不要现在就改。

## 参考反编译内容

| 来源 | 位置 | 关键信息 |
|------|------|----------|
| 逆向文档 | `docs/shaders-format.md` | INDEXED pass1 像素着色器纹理绑定顺序、分块参数语义（第 39-48、88-99 行） |
| fxo 逆向 | `uncode_assets/shaders.py` | 资源绑定提取（纹理/采样器名序列）；`ship_material_indexed.win.dx11.fxo` ↔ `ship_material_indexed.fx` |
| 已入库数据 | `assets_data.db/material_full` | 每个 INDEXED 材质的 shader_id、全部贴图原始路径、vec4 数组（JSON） |
| 反编译代码 | `_decompile/`（pyc 反编译产物） | 客户端材质/着色器相关逻辑（如需更深层规则） |

## INDEXED 渲染规则要点（来自反编译/逆向）

- **INDEXED = 材质 ID 分块涂装**：`TL2_SHIPMAT_INDEXED_[PINST_]PBS_*`（如 Hull/DeckHouse/Gun/Misc），
  shader 高 16 位 `0x0009`（`ship_material_indexed.fx`），与普通 PBS（`0x0005`）渲染路径不同。
- **pass1 纹理绑定顺序**（bindPoint 5/4 交替）：
  `ambientOcclusionMap → materialIdMap → artMap → rgbNoiseMap → albedoArray → normalArray → MGArray`
- **materialIdMap**（`_matid.dds`，ATI1/BC4 单通道 4096²）：**R 通道 = 材质 ID 0~195**。
- **分块参数数组**（`material_full.indexed` 里的 vec4 数组，每数组 196 项）：
  - `offsetScaleMatIdArr` = "Offset/Scale For Material Index Array" → `params["offset"]`/`params["grid"]`
  - `albedoTintMatIdArr` = 每材质 ID 的 tint 颜色（196×4 RGBA）
  - `albedoToRemoveTintMatIdArr` 等其它数组
- **渲染时**（每 fragment）：
  1. 采样 `materialIdMap` R 通道 → 材质 ID（0~195）
  2. 用材质 ID 查 `albedoTintMatIdArr` / `offsetScaleMatIdArr` → tint 颜色 + 分块 offset/scale
  3. 用 offset/scale 从 `albedoArray`（分块图集）采样对应分块 → 与 tint 混合输出

## 实施计划（稍后）

- [ ] 渲染器（`ui/geometry_renderer.py`）对 `tech_family=='indexed'` 的网格启用 INDEXED 着色路径：
      materialIdMap + albedoArray + tint/分块参数（GLSL 实现材质 ID 查表 + 分块 UV 采样）
- [ ] 查看器（`ui/geometry_viewer.py`）INDEXED 材质正确显示（验证舰体分块涂装 vs 普通 PBS）
- [ ] 验证：大和/缅因等 INDEXED 舰体 hull 材质分块涂装正确；与 `_decompile/` 反编译规则逐条核对
- [ ] 性能：INDEXED 逐 fragment 查表（196 项数组 → uniform 数组或纹理）避免分支/索引纹理开销

## 数据已就绪（无需再改入库）

- `_resolve_material_full(mfm)` 已从库返回：`tech_family` / `shader_id` / `textures`（贴图路径，
  渲染时实时解包字节）/ `indexed_params`（`arrays` + `offset`/`grid`）
- INDEXED 材质示例：`content/gameplay/common/instance/asset/textures/CIA000_instances_atlas.mfm`
  （shader=0x00090000，`albedoTintMatIdArr` 196×4、`albedoToRemoveTintMatIdArr` 19×4）
