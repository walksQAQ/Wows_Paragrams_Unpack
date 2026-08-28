# 涂装切换器（Camo Switcher）—— 设计方案

> 状态：**设计稿（2026-08-28 立项）**
> 目标：在 3D 查看器里增加**涂装切换器**，逐艘船列出可切换涂装，点击切换后
> **贴图层（artMap/tint/MG 等）与模型/网格变体**同步变化（两者都要）。
>
> 关联：
> - `todo_list/New_function_of_fix_indexed_render_and_export_glb.md`（INDEXED 渲染基线）
> - `docs/shaders-format.md`（camo / INDEXED shader 纹理与公式）
> - `docs/dds-format.md`（artMap BC7 512² 艺术涂装叠加层）
> - `resources/fx_mapping_wargaming.md`（`ship_camo_preview_material.fx` 等 camo fx）
> - 反编译：`ship_material_indexed.fx` / `ship_camo_*`（艺术涂装叠加公式）
> - wows-toolkit：`viewport_3d/renderer.rs`（camo 混合）、`types.rs`（LightingSettings）

---

## 一、背景：已实现的部分

现有 INDEXED 渲染已把涂装的一部分接进来了（`ui/geometry_renderer.py::_bind_indexed` + `u_mode=3`）：

1. **artMap 艺术涂装叠加层**（`*_art.dds` BC7 512²）：
   ```glsl
   vec4 art4 = texture(u_art_tex, v_uv);
   float am = clamp(art4.a * u_rotation[matId].y, 0.0, 1.0);   // artStrengthMatIdArr.x
   c = mix(c, art4.rgb, am);
   ```
2. **tint 调色**：`albedoTintMatIdArr[196]` + `albedoToRemoveTintMatIdArr[196]`，shader 做
   `lerp(tint_lin, albedo_lin, k)`。
3. **无 camo 兜底**：`_resolve_material_full()` 里若 artMap 是**洋红占位**（`_is_magenta_placeholder`），
   把 `artStrengthMatIdArr[:,0]` 置 0，避免占位洋红被满强度混入。

> 结论：**贴图层**的渲染公式已基本具备，缺的是「多套涂装的**数据来源** + **切换**」。
> 而**模型/网格变体**切换目前完全没有。

---

## 二、涂装数据模型（需探针验证，先作假设）

游戏内的"涂装"（camouflage / permanent camo）在数据上通常表现两类变化：

### 2.1 贴图层变化（假设）
- 同一套 geometry 模型，不同 camo 对应**不同 artMap**（不同 `*_art.dds`）；
- 也可能连 `albedoTintMatIdArr / albedoToRemoveTintMatIdArr / artStrengthMatIdArr` 一起变
  （同一 materialIdMap/albedoArray 之下，调色/强度随 camo 走）；
- 少数 camo 会换 `MGArray` 或 `normalArray`？

**待探针确认**：
- P-A1：一艘船（如 Waterloo）目录下到底有几张 `*_art.dds` / 几个 camo 材质（`*_cam*.mfm`）？
- P-A2：这些 camo 材质是否共用同一 `materialIdMap / albedoArray / normalArray / MGArray`，只换 artMap？
- P-A3：`albedoTintMatIdArr` 是否随 camo 变化（还是固定 per-geometry）？

### 2.2 模型/网格变体变化（假设）
- 两种来源：
  - **同一材质/geometry 的不同分块**：camo 只改 `disableMGNCamo`（tileIdx 第 4 分量）或 art 权重；
  - **真正的模型/"挂件"变体**：如永久涂装会加/换某些装饰 mesh（贴花、舷号、甲板图案、部件）。
- `geometry_service` 目前按**一段 geometry** 拆 primitive（`_split_primitives_by_material`），
  尚未区分"哪段是哪个 camo 专属"。

**待探针确认**：
- P-B1：不同 camo 是否对应**不同 geometry 文件**（如 `*_camo_*.geometry`）或同 geometry 内不同 primitive？
- P-B2：是否存在"camo 专属 mesh"（如临时贴花/装饰），需要按 camo 显示/隐藏？

---

## 三、查看器 UI 设计

位置：`ui/geometry_viewer.py` 右侧控制面板，在"舰船选择/显示选项"附近新增**涂装区**。

```
[涂装]                         ← 区块标题
┌───────────────────────────┐
│ ○ 标准涂装 (默认)          │
│ ● 迷彩 A (海洋)            │
│ ○ 永久涂装 B (旗帜)        │
└───────────────────────────┘
```

- **控件**：`QListWidget`（单项可选）或 `QComboBox` + 预览缩略（`QIcon` 取自 artMap 低清）
  + 一个"切换/应用"按钮。
- **点击切换**：选中项变化 → 触发重载/换绑 → `viewport.update()`。
- 状态来源：加载某艘船时，后台解析该船**可切换涂装列表**返回给 UI 填充；
  列表未拿到前显示空/占位。

### 交互细节
- 切换是**异步**（可能换 geometry / 重新上传贴图），沿用现有 `run_async` + 取消代数
  （`_load_generation`）机制，避免连点造成竞态。
- 切换期间显示 `loading_overlay`（复用现有）。

---

## 四、渲染实现

### 4.1 贴图层切换（优先、改动小）
现有 `_resolve_material_full` 已按 mfm 解析 `textures` 与 `indexed_params`。
切换方案：

- `GeometryViewport` 增加 `set_camo(camo_id)`：
  - 目标：只用**同一 geometry 的 GPU 网格**，仅替换该 mesh 的：
    - `_extra_tex["artMap"]`（换 artMap 纹理）
    - `indexed_params["arrays"]["artStrengthMatIdArr"]` / `albedoTintMatIdArr` 等（若随 camo 变）
  - 实现：`_bind_indexed()` 读取 `mesh._extra_tex` / `mesh.indexed_params`；
    切换时**重建该 mesh 的 GL 纹理/param 缓存**（只需更新 artMap 纹理 + 上传数组即可，
    不必重建 VBO/IBO）。
- 渲染公式不变（已是官方 artMap 叠加）。

### 4.2 模型/网格变体切换
- 若 camo 对应**不同 geometry**（P-B1 成立）：
  - 切换=重新 `set_scene` 加载对应 geometry 变体（走现有 `load_ship` 的变体路径），
    代价较大，但复用现有加载/缓存。
- 若 camo 对应**同 geometry 内的不同 mesh/primitive**（P-B2 成立）：
  - 切换=显示/隐藏某些 mesh（`GpuMesh` 加 `visible`/`camo` 标记，`_draw_ship_solid` / 透明 pass
    按标记跳过）+ 换绑该 mesh 的 artMap。
  - 更轻，无需重建 VBO。

> 设计上先落地**方案 4.1（贴图层）**，把 camo 列表和切换打通；**4.2（模型变体）**
> 视探针结果（P-B1/B2）再定通过"重载变体"或"mesh 显隐"实现。

---

## 五、数据管线（新增）

需要新增一个"该船可切换涂装列表"的解析：

```
geometry_service.list_camos(ship) -> list[CamoInfo]
  CamoInfo = {
    camo_id: str,          # 涂装标识（如 mfm 路径 / camo 名）
    name: str,             # UI 显示名（优先本地化/文件名）
    artmap_vfs: str | None,# artMap 路径
    mfm: str,              # 该 camo 的材质
    geometry_variant: str | None,  # 若走模型变体：对应 geometry 文件/无
    params_override: dict, # 可选：artStrength/tint 数组覆盖
    thumb: bytes | None,   # 缩略图（artMap 低清）
  }
```

- 数据源：从 `assets_data.db` 的 `material_full` 反查**同一 ship_model_folder 下所有相关 mfm**，
  再按 `artMap`/camo fx 归类出 camo 列表。
- 若模型变体成立：还需索引该船的**变体 geometry 文件清单**。

---

## 六、待验证问题（先探针，再实现）

| 编号 | 问题 | 探针/方法 |
|---|---|---|
| P-A1 | 一船有几个 camo 材质/artMap | 列 `material_full` 里 `ship.model_folder` 相关 mfm，统计各自 artMap |
| P-A2 | camo 是否只换 artMap | 对比各 camo 材质 textures 的健集合差异 |
| P-A3 | tint/artStrength 是否随 camo 变 | dump 各 camo 材质的 `albedoTintMatIdArr` |
| P-B1 | camo 是否有专属 geometry | 列该船目录所有 `.geometry`，看是否按 camo 命名 |
| P-B2 | camo 是否走同 geometry 内 mesh 显隐 | 检查 primitive 分组是否含 camo 标记 |
| P-C1 | 涂装名/本地化 | 从哪里取可读涂装名（GameParams? artifacts?） |

---

## 七、任务清单

### P0：数据探针（确认上表）
- [ ] P0-1 探针：列出某船全部 camo 材质/artMap（P-A1/A2/A3）
- [ ] P0-2 探针：确认模型变体来源（P-B1/B2）
- [ ] P0-3 探针：涂装名/本地化（P-C1）

### P1：贴图层切换（打通核心）
- [ ] `geometry_service.list_camos(ship)` 返回 `CamoInfo[]`
- [ ] `GeometryViewport.set_camo(id)`：换绑 artMap + （可选）覆盖 params 数组
- [ ] `_bind_indexed()` 支持动态 artMap/params
- [ ] UI：查看器右侧涂装区（列表 + 点击切换 + loading）
- [ ] 离屏验证：切换后 artMap 生效（对比不同 camo 的 art 叠加区域）

### P2：模型/网格变体
- [ ] 若 P-B1：`load_ship` 支持按 camo 变体加载 geometry
- [ ] 若 P-B2：`GpuMesh` camo 显隐标记 + 渲染按标记跳过
- [ ] 切换时同步更新 viewport 场景

### P3：打磨
- [ ] 涂装缩略图（artMap 低清）
- [ ] 涂装名本地化
- [ ] 切换动画/即时反馈；错误/缺失 camo 兜底（沿用洋红占位置 0 逻辑）

---

## 八、参考

- **反编译**：`ship_material_indexed.fx` 的 artMap/tint 官方公式（已对齐部分）；
  `ship_camo_preview_material.fx`（camo 预览，来自 fx_mapping_wargaming.md）。
- **wows-toolkit**：`crates/wows-toolkit/src/viewport_3d/renderer.rs` 的 camo 混合；
  `types.rs` 的 LightingSettings（可参考其 camo/光照预设）。
- **本地**：`docs/shaders-format.md`、`docs/dds-format.md`、`resources/fx_mapping_*.md`。
