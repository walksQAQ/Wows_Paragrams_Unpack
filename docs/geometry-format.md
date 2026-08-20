# .geometry 格式规范（MergedGeometryPrototype）

> 来源实现：`models/geometry_parser.py`
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

## A.3 VerticesPrototype（0x20 字节）

`i64 verticesDataPtr / PackedString formatName / u32 sizeInBytes / u16 strideInBytes / u8 isSkinned / u8 isBumped`

顶点格式名如 `set3/xyznuvtbpc`：`xyz`=POSITION f32×3，`n`=NORMAL packed 4B，`uv`=TEXCOORD 2×f16，`tb`=切线/副切线，`iiiww`=骨骼索引×3+权重×2。

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
