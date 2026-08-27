# INDEXED 渲染修正 + GLB 模型导出 —— 计划任务

> 状态：**待办（2026-08-20 立项）**
>
> 顺序约束（用户已确认）：**先修正 INDEXED 特殊渲染规则（P1），渲染正确后再实施 GLB 导出（P2）**。
> 导出贴图目标是「类似标准非 INDEXED（PBS）材质的形态」：baseColor / normal / MG 常规贴图集，
> 不要求外部工具理解游戏私有分块系统。
>
> 关联文档：
> - `todo_list/New_function_of_unpack_geo_and_display.md`「GLB 舰船模型导出设计方案」章节（导出总体设计）
> - `todo_list/New_function_of_indexed_material_rendering.md`（旧渲染实施记录，已被本文档取代）
> - `docs/shaders-format.md` / `docs/dds-format.md` / `docs/materials-format.md`（逆向依据）

---

## 一、已确证事实（2026-08-20 数据库探针结论）

探针脚本（`_temp/scripts/`）：`probe_indexed_material.py` / `probe_indexed_arrays.py` / `probe_indexed_tint.py`。

1. **INDEXED 材质共 162 个**（`assets_data.db / material_full`，`family='indexed'`，shader_id 高 16 位 `0x0009`）。
2. **每材质 9 张贴图**（全部已入库 `material_full.textures`）：

   | 键 | 典型文件 | 格式/尺寸 | 用途 |
   |---|---|---|---|
   | materialIdMap | `*_matid.dds` | BC4 单通道 4096² | R = 材质 ID 0~195 |
   | albedoArray | `CIT000_1k_ship_tiles_a.dds` | BC7 1024² | 漫反射图集（真正主纹理） |
   | normalArray | `CIT000_1k_ship_tiles_n.dds` | BC7 1024² | 法线图集 |
   | MGArray | `CIT000_1k_ship_tiles_mg.dds` | BC7 1024² | 金属/光泽图集 |
   | artMap | `*_art.dds` | BC7 512² | 艺术涂装叠加层 |
   | ambientOcclusionMap | `*_ao.dds` | — | AO |
   | rgbNoiseMap | `CIC001_splice_rgb_noise_a.dds` | — | 噪声 |
   | diffuseMap | `*_a.dds` | BC1 32² | 占位（INDEXED 下非主纹理） |
   | normalMap | `*_alpha_n.dds` | — | alpha 法线 |

3. **vec4 数组实测有 6 个**（196×4，2026-08-27 确认；早前「只有两个」探针结论已作废）：
   - `albedoTintMatIdArr`：196×4。RGB = tint 颜色；第 4 分量范围 0~999，
     整数分布 0~9 + 999（999 疑似特殊标记，语义待验证）。171/196 项非零。
   - `albedoToRemoveTintMatIdArr`：196×4。
   - `offsetScaleMatIdArr` / `rotationMatIdArr` / `tileIdxMatIdArr` / `artStrengthMatIdArr`：均 196×4。
4. **渲染器引用的 6 数组确实存在**：`ui/geometry_renderer.py` 的 `u_mode=3` 分支使用
   `tileIdxMatIdArr` / `offsetScaleMatIdArr` / `artStrengthMatIdArr` 是正确的（名字与库一致）。
   早期「这 3 个数组从未出现 → uniform 全 0」的判断**是探针漏读所致**，非数组缺失。
5. shader 资源绑定顺序（fxo RDEF 实测）：
   `ambientOcclusionMap → materialIdMap → artMap → rgbNoiseMap → albedoArray → normalArray → MGArray`。

---

## 二、P1：修正 INDEXED 特殊渲染规则

### 2.1 根因

`_bind_indexed()`（`ui/geometry_renderer.py`）绑定的参数与真实数据需对齐：

| 渲染器引用 | 数据库实际（2026-08-27 实测） | 后果 |
|---|---|---|
| `tileIdxMatIdArr`（瓦片索引） | 存在（196×4） | `u_tile_idx` 按 `tileIdx.x` 采样 |
| `offsetScaleMatIdArr`（网格/偏移） | 存在（196×4，scale=38） | 需传对 scale/倒数，否则 UV 错误（见权威记录） |
| `artStrengthMatIdArr`（叠加强度） | 存在（196×4，BaseStrength=1.0） | art 叠加按 `.x`=1.0 |
| `albedoTintMatIdArr` | 存在（196×4） | tint 混合用 lerp（非乘法） |

> ⚠️ 早前「这 3 个数组不存在」的判断**是探针漏读所致**，非真实缺失。

### 2.2 修正方案

1. **重写 GLSL `u_mode=3` 分支**（候选公式，需探针验证后定稿）：

   ```glsl
   int matId = clamp(round(texture(u_matid_tex, v_uv).r * 255.0), 0, 195);
   vec4 tint = u_tint[matId];                 // albedoTintMatIdArr
   vec3 albedo = texture(u_tiles_tex, v_uv).rgb;   // albedoArray 直接采样（待验证是否分块）
   vec3 art = texture(u_art_tex, v_uv).rgb;
   vec3 rgb = mix(albedo, albedo * tint.rgb, tintStrength) + art * artStrength;
   ```

   待验证点（按顺序排查）：
   - `albedoArray` 是按 UV 直接采样，还是按材质 ID 映射到瓦片（`g_tileScale` 仅 1 个材质有，
     倾向「直接采样 + tint 调色」模型）；
   - tint 第 4 分量（0~999）的确切作用：混合权重 / 材质分组索引 / 特殊标记（999）；
   - `albedoToRemoveTintMatIdArr` 的 196 项（每项多为 `[1,0,1,1]` 掩码语义待验证）；
   - artMap 叠加强度：`artStrengthMatIdArr` 已确认存在，BaseStrength=1.0（叠加按 `.x`）。

2. **数据管线修正**：
   - `geometry_service._resolve_material_full()`：`indexed_params` 改为透传全部 6 个
     真实数组（`albedoTintMatIdArr` / `albedoToRemoveTintMatIdArr` / `artStrengthMatIdArr` /
     `offsetScaleMatIdArr` / `rotationMatIdArr` / `tileIdxMatIdArr`）；
   - `_bind_indexed()`：uniform 改为 6 数组各 `[196]`（含 `u_tint[196]`）+ 实际存在的标量；
   - `HullMesh.material_textures` 已含全部 9 张路径，补加载 `normalArray` / `MGArray`
     （当前只加载了 albedoArray 作主贴图）。

3. **验证手段**（沿用离屏渲染探针）：
   - 选 INDEXED 舰船（如使用 `BIA000_instances_atlas` 的英系舰）渲染截图；
   - 与游戏内截图 / wows-toolkit 渲染结果对比 tint 区域颜色；
   - 非 INDEXED（PBS）材质回归测试不受影响。

### 2.3 任务清单（P1）

- [ ] 探针验证 albedoArray 采样方式（直接 UV vs 瓦片）与 tint 混合公式
- [ ] 探针验证 tint.w 与 albedoToRemoveTintMatIdArr 语义
- [ ] 重写 GLSL `u_mode=3` 分支 + `_bind_indexed()` uniform
- [ ] `_resolve_material_full()` 透传真实数组，删除不存在数组的引用
- [ ] 补加载 normalArray / MGArray 到 `material_textures`
- [ ] 离屏渲染探针验证（INDEXED 舰船 + PBS 回归）
- [ ] 更新 `New_function_of_indexed_material_rendering.md` 状态为「已由本计划取代/完成」

---

## 三、P2：GLB 导出（渲染修正完成后启动）

总体设计见 `New_function_of_unpack_geo_and_display.md`「GLB 舰船模型导出设计方案」，
此处只列与 INDEXED 转码相关的增量决策。

### 3.1 INDEXED → 标准 PBR 转码策略（用户要求：输出形态对齐标准 PBS 材质）

标准 PBS 材质的贴图形态（`docs/materials-format.md`）：

```
diffuseMap(_a.dds) / normalMap(_n.dds) / metallicGlossMap(_mg.dds) / ambientOcclusionMap(_ao.dds)
```

INDEXED 转码目标 = 烘焙出同样形态的四张常规贴图：

| 输出 | 来源 | 烘焙方式 |
|---|---|---|
| baseColor | albedoArray + albedoTintMatIdArr + artMap | 按 materialIdMap 逐像素：采样 albedoArray → 应用 tint 混合 → 叠加 art → sRGB |
| normal | normalArray | 与 baseColor 相同的采样/混合规则（公式随 P1 定稿） |
| metallicRoughness | MGArray | 同上；通道映射（M/R 归属）随 P1 验证 |
| occlusion | ambientOcclusionMap | 直接转码（已是常规贴图） |

关键原则：

- **烘焙公式必须与 P1 修正后的渲染器完全一致**（同一份混合逻辑的 CPU 实现），
  保证「查看器里看到的 = 导出的」；
- 烘焙在 materialIdMap 的 UV 空间进行（4096²，输出可降采样到 2048² 控制体积）；
- BC4/BC7 CPU 解码需新增依赖（`texture2ddecoder` 或等价库），加入 `requirements.txt`
  并验证 Nuitka onefile 打包；
- 原始 INDEXED 参数（tint 数组、贴图路径、shader_id）写入 `material.extras.wows_indexed`
  供追溯，但不作为 glTF 标准字段。

### 3.2 任务清单（P2）

- [ ] 依赖选型：BC4/BC7 CPU 解码库 + PNG 编码，验证 onefile 打包
- [ ] `services/export_service.py`：`export_ship_glb(geometry, path, options)`（接口见总体设计）
- [ ] INDEXED 烘焙器：CPU 复刻 P1 定稿的混合公式 → baseColor/normal/MG/AO 四张 PNG
- [ ] 非 INDEXED（PBS）材质直接映射 diffuse/normal/MG/AO，无需烘焙
- [ ] 查看器「导出 GLB」按钮 + 后台线程 + 进度/警告反馈
- [ ] 验证：Blender/Three.js 打开导出结果，INDEXED 舰船贴图与查看器渲染一致
- [ ] 大船内存/耗时验证（2GB 红线）+ 打包版导出验证

---

## 四、风险与开放问题

1. **tint 混合公式未定稿**：SHEX 字节码无法反汇编（Lesta 自定义编码），
   公式需靠「数据库数据 + 渲染对比」实证；若无法完全还原，以视觉最接近的公式为准并记录偏差。
2. **999 特殊值**：tint.w=999 的材质行为未知，探针需单独覆盖。
3. **normal/MG 通道映射**：MGArray 的金属/粗糙度通道归属未验证，首期可只烘焙 baseColor，
   normal/MG 作为增强项。
4. **4096² 烘焙体积**：单张 PNG 约 16~32MB，多材质舰船 GLB 可能超 100MB，
   需要提供输出分辨率选项（4096/2048/1024）。
