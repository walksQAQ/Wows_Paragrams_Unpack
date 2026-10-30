# .geometry 格式规范（MergedGeometryPrototype）

> 来源实现：`models/geometry_parser.py`（读）/ `models/geometry_writer.py`（写）
> 参考：wows-toolkit（landaire）`.geometry` 逆向
>
> 本文件是 `.geometry` 格式的**唯一格式文档**（原为
> `todo_list/New_function_of_unpack_geo_and_display.md` 附录 A，2026-08-20 迁入 `docs/`）。
> 相关格式文档：`docs/prototype-formats.md`（prototype 字节布局）、`docs/assets-bin-format.md`、
> `docs/kraken-format.md`（Kraken 解压）、`docs/materials-format.md` / `docs/shaders-format.md`。

## 概览

`.geometry` 文件是一个 MergedGeometryPrototype：头部 72 字节 + 若干 relptr 指向的
映射 / 顶点 / 索引 / 碰撞 / 装甲段。所有指针为相对结构体基址的偏移：
`resolve_relptr(base, ptr) = base + ptr`。

## A.1 MergedGeometryPrototype 头部（72 字节）

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 4 | u32 | mergedVerticesCount |
| 0x04 | 4 | u32 | mergedIndicesCount |
| 0x08 | 4 | u32 | verticesMappingCount |
| 0x0C | 4 | u32 | indicesMappingCount |
| 0x10 | 4 | u32 | collisionModelCount |
| 0x14 | 4 | u32 | armorModelCount |
| 0x18 | 8 | i64 | verticesMappingPtr → MappingEntry[] |
| 0x20 | 8 | i64 | indicesMappingPtr → MappingEntry[] |
| 0x28 | 8 | i64 | mergedVerticesPtr → VerticesPrototype[] |
| 0x30 | 8 | i64 | mergedIndicesPtr → IndicesPrototype[] |
| 0x38 | 8 | i64 | collisionModelsPtr → CollisionModelPrototype[] |
| 0x40 | 8 | i64 | armorModelsPtr → ArmorModelPrototype[] |

所有指针为相对结构体基址的偏移：`resolve_relptr(base, ptr) = base + ptr`。

## A.2 MappingEntry（0x10 字节）

`u32 mappingId（murmur3 哈希）/ u16 mergedBufferIndex / u16 packedTexelDensity / u32 itemsOffset / u32 itemsCount`

`mappingId` 就是**形状名字符串的 murmur3_32（seed 0）**，字符串带后缀：
`.visual` 里的 `<vertices>XShape.vertices</vertices>` → `murmur3("XShape.vertices")`，
`<primitive>XShape.indices</primitive>` → `murmur3("XShape.indices")`。
实测（mod 明文 `.visual` + `.geometry` 对拍）：`murmur3("FlatShape.vertices") = 0x6DB21283`、
`murmur3("FlatShape.indices") = 0x2BF791AA`，与文件里的两个 `mappingId` 完全一致。
⇒ 只要 `.visual` 与 `.geometry` 用同一套形状名，**不需要任何全局注册表**（`assets.bin`）。

## A.3 VerticesPrototype（0x20 字节）

`i64 verticesDataPtr / PackedString formatName / u32 sizeInBytes / u16 strideInBytes / u8 isSkinned / u8 isBumped`

顶点格式名如 `set3/xyznuvtbpc`：`xyz`=POSITION f32×3，`n`=NORMAL packed 4B，
`uv`=TEXCOORD 2×f16（`uv2` 为第二套），`t`=4B（单独切线/额外属性）、`tb`=切线+副切线 8B，
`iiiww`=顶点组索引×3 + 权重×2（8B：`u8 idx[3] + 2B pad + u8 w[2] + 1B pad`；
`i0↔w0`、`i1↔w1`，第三个顶点组权重 = `1-w0-w1`），`r`=EXTRA 4B，
`pc`/`oi`=打包标记（0B）。末尾 `_encd` 仅标记 ENCD 压缩方式，不影响布局。

⚠️ 索引是**渲染集调色板 slot × 3**（`slot = idx // 3`，与 BigWorld 插件
`import_bw_primitives.py` 的 `iiiww[0]/3` 一致），slot 指向该 renderSet 的
`<node>` 列表（assets.bin 里就是 `+0x0D nodes_count` / `+0x28` 的 u32 名 ID 数组）
**按原始顺序**的第 slot 项。调色板顺序绝不能重排（排序后权重会绑到别的骨骼）。

⚠️ **每个顶点最多 3 个骨骼影响，且三个权重之和必须 = 1** —— 这是格式决定的硬上限
（只有 3 个 u8 索引 + 2 个 u8 权重，第三个权重由 `1-w0-w1` 隐含推出），
不是导出/导入工具的限制。实测 62 个真实 `.geometry`（1977 个网格、69 个蒙皮网格、
118,185 个蒙皮顶点）：影响数 1 → 117,897、2 → 272、3 → 16，**4 从未出现**；
蒙皮顶点格式只有 `set3/xyznuviiiwwtbpc` 与 `set3/xyznuviiiwwr`（都是 `iiiww`）。
Blender 端把权重裁到 3 个并归一化用 `_archive/animExporter/Tools/权重限3`；
`.anim`（动画）与顶点组无关，不受这条限制。

⚠️ 这条限制只针对**单个顶点**，**不是**「一个网格只能有 3 个顶点组」：
调色板长度上限是 **86 个**（`idx = slot × 3` 且 `idx` 为 u8 ⇒ `slot ≤ 85`），
每个顶点从中各挑 ≤3 个即可。retail 单网格调色板实测中位数 3 根、最大 84 根
（`assets_data.db` 的 `render_sets`）；合成测试里 12 个顶点组的模型导出、自检全过。

⚠️ 「≤3」是**格式 + 着色器级**上限，绕不过去：两个客户端的 exe 里顶点格式名只有
`iiiww` 家族（`…iiiwwpc` / `…iiiwwr` / `…iiiwwtpc|tbpc` / `…uv2iiiww…`），
任何 `iiiwww` / `iiiiwwww` 形式的字符串都不存在，引擎按 D3D11
`BLENDINDICES` / `BLENDWEIGHT` 语义建输入布局、蒙皮着色器按格式排列预编译。
需要更高保真（如 MMD 的 BDEF4）时只能在导出侧折中：把超出的影响合并成一根
**每帧烘焙的辅助骨**（`__blend_k`，`P_H = ΣwᵢPᵢ / Σwᵢ`），矩阵层面等价，
残差只剩 `.anim` 存不下剪切那点；见 `_archive/animExporter/Tools/anim格式说明.md` §11.2.3。

## A.4 IndicesPrototype（0x10 字节）

`i64 indicesDataPtr / u32 sizeInBytes / u16 保留 / u16 indexSize（2=u16, 4=u32）`

## A.5 CollisionModelPrototype（0x20 字节）

`i64 cmDataPtr / PackedString name / u32 sizeInBytes / u32 填充`。数据范围 = `cmDataPtr → cmDataPtr + sizeInBytes`。

碰撞数据为纯三角形汤：`u32 vertexCount / u32 indexCount / f32×3 顶点 / u16 索引`。命名 `CM_*`（CM_Helium 船体、CM_Turret 炮塔等），无材质信息。

## A.6 ArmorModelPrototype（0x20 字节）

同布局，但数据范围 = `struct_base + 0x20 → resolve_relptr(struct_base, data_relptr) + sizeInBytes`。命名 `CM_*.armor`。

装甲数据为 16 字节条目流：每组 = 2 个头条目（第一条目 byte0=material_id、byte2=layer_index；第二条目 offset+12 处 u32=vertex_count）+ vertex_count 个顶点条目。每顶点：`f32 x,y,z + u8[3] packed_normal（/127.5-1）+ u8 zero` = 16B。

```python
ArmorTriangle {
    vertices: [[f32; 3]; 3],
    normals: [[f32; 3]; 3],
    material_id: u8,   # 头条目 byte 0
    layer_index: u8,   # 头条目 byte 2
}
```

## A.7 ENCD 压缩

Magic `ENCD`（0x44434E45）+ u32 elementCount + meshoptimizer 压缩 payload。用 `meshoptimizer` wheel 解码（注意 dtype 与 u16 索引包装）。

## A.8 PackedString（0x10 字节）

`u32 charCount（含 null）/ u32 填充 / i64 textPtr（相对偏移）`。

## A.9 舰船文件路径

```
content/gameplay/{nation}/ship/{type}/{ship_name}/{ship_name}_{part}.geometry
```

## A.10 装甲厚度数据源

主库 entity_snapshots 舰船快照：`A_Hull.armor` + `*_Artillery/A_ATBA/...` 下各 `HP_*.armor`。键为 `(model_index << 16) | material_id` → mm；几何 layer_index = model_index。多层材质（Dual_*）同一 material_id 有多个 model_index 层。

## 与实现的关系

- `models/geometry_parser.py`：`parse_geometry()` 按本格式解析；`ENCD` 段用 meshoptimizer 解码。
- 装甲三角形 → `models/collision_materials.py`（材质名表 / thickness_to_color / zone_from_material_name / get_armor_types）。
- 舰船几何装配 → `services/geometry_service.py`（分段合并、挂载矩阵、装甲厚度字典、取消检查点）。
- 3D 渲染 → `ui/geometry_renderer.py`（舰体贴图 + INDEXED 分块材质 + 装甲厚度着色）。
