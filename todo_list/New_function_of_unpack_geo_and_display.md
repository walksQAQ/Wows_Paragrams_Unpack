# 舰船 3D 模型解包与显示 —— 装甲展示重构规划

> 状态：**装甲展示重构已完成（2026-08-20）+ 后续修复已完成（2026-08-20，见「三、重构后修复」）**
>
> 本文档原为 3D 查看器首版规划（已实现，见「一、现状」）。重构任务：**参考 landaire/wows-toolkit 彻底重构装甲模型展示功能并重做查看器 UI**（见「二、装甲展示重构设计」，P0-A~P0-D 全部完成并验证）。`.geometry` 格式规范保留在「附录 A」作为唯一格式文档。

---

## 一、现状（首版已实现，2026-08-18/19）

| 层面 | 文件 | 说明 |
|------|------|------|
| .geometry 解析 | `models/geometry_parser.py` | 72B 头 + relptr + ENCD(meshoptimizer) + 顶点/索引/碰撞/装甲 BVH |
| 装甲厚度 | `services/geometry_service.py` `_load_armor_thickness` | 主库 entity_snapshots 读 `A_Hull.armor` + 各挂载 `HP_*.armor`，DB-first |
| 渲染 | `ui/geometry_renderer.py` + `models/camera.py` | PyOpenGL 3.3 Core（非 ModernGL）；舰体贴图 + INDEXED 分块材质 + 挂载矩阵 + 装甲厚度着色 |
| 装甲分类 | `models/collision_materials.py` | 材质名表 / `thickness_to_color`（游戏 10 色桶）/ `zone_from_material_name` / `get_armor_types`（反编译 ArmorConstants） |
| UI | `ui/geometry_viewer.py` | 独立窗口；装甲类型复选框筛选 + 厚度图例；船体/装甲互斥 |
| 挂载 | `services/geometry_service.py` | HP_ 挂点 + MP_ 甲板设备 + 部件子设备递归定位（骨架世界矩阵） |

架构约束（必须延续）：
- 渲染集/骨架/材质元数据只从 `assets_data.db` 读；舰船实体数据（装甲厚度/挂载引用）只从主库 `entity_snapshots` 读；贴图字节从客户端 pkg 解包。
- 显示阶段绝不读 `data/split/Ship/*.json`、绝不现场读 assets.bin。
- 临时脚本只放 `_temp/scripts/`；内存 2GB 红线；CRLF 行尾；编辑工具避免 4 字节 emoji。

首版遗留（未实现，低优先级）：OBJ 导出（`services/export_service.py`）、碰撞模型渲染。

---

## 二、装甲展示重构设计（当前任务）

### 2.1 目标与范围（用户已确认全部纳入 + UI 重做）

| # | 能力 | wows-toolkit 对应 |
|---|------|-------------------|
| F1 | 板块边界描边（不同厚度/材质交界 + 轮廓 + 折角） | `upload_plate_boundary_edges` |
| F2 | Zone→部件→板块 三级树 + 逐级显隐 | `part_visibility`/`plate_visibility` |
| F3 | 鼠标拾取 + 悬停提示（含多层堆叠厚度） | `show_armor_tooltip` |
| F4 | 高亮悬停/选中板块、部件、区域 | `upload_plate_highlight` |
| F5 | 装甲不透明度滑杆 | `armor_opacity`（0mm 板开关已按用户要求移除） |
| F6 | 船体半透明垫底（装甲下显示半透明船体） | hull backdrop |
| F7 | 查看器 UI 整体重设计 | Armor Viewer 布局 |

不在本次范围：弹道/穿深模拟、相机椭圆环、多船对比、GAP 检测、replay 查看器。

### 2.2 wows-toolkit 参考要点（已核对源码）

- **PlateKey** = `(zone, material_name, thickness_tenths)`，`thickness_tenths = round(mm*10)`；厚度作判别项使高亮在板块边界停止。
- **厚度→颜色**：10 色桶 bisect_left，≤0 为未知浅灰。本项目 `thickness_to_color` 已一致。
- **多层厚度** `lookup_all_layers`：Dual 材质跨 model_index 收集所有非零层 → tooltip 展示堆叠。
- **边界描边**：顶点量化（×10000 取整）做边键；边两侧记录 `(plate_key, face_normal)`；输出条件 = 网格边界（仅 1 个三角形）∨ 板块边界（plate_key 不同）∨ 折角（法线点积 < 0.7 ≈ 45°）。
- **显隐**：part/plate 两级字典，默认 true，上传时跳过不可见三角形。
- **高亮**：匹配三角形沿法线偏移渲染覆盖网格。
- **hidden**：游戏内查看器隐藏的板 = Hull 父区通用材质（Trans/Deck/Belt 等）。

### 2.3 目标架构

```
models/geometry_parser.py        （不动）.geometry 解析
services/geometry_service.py     （小改）ArmorTriangleInfo 补 layers/hidden/plate_key；厚度字典补多层
models/armor_scene.py            （新增）ArmorScene：世界空间三角形汤 + 层级索引 + 边界线 + 拾取
ui/geometry_renderer.py          （改）edge/highlight/backdrop pass + 不透明度 + 拾取射线
ui/geometry_viewer.py            （重做）三级树 + 悬停提示 + 滑杆 + 开关
```

数据流：

```
ShipGeometry.armor_meshes
   └─ ArmorScene.build()
        ├─ world_positions / world_normals（应用 model_matrix）
        ├─ tri_info[]（layers / plate_key / zone / part / hidden）
        ├─ zones 层级 {zone: {part: {thickness_tenths: [tri_idx]}}}
        ├─ edge_positions（边界线端点对）
        └─ per-mesh AABB（拾取预筛）
   └─ GeometryViewport.set_armor_scene(scene)
        ├─ 装甲 GpuMesh（flat 色 + opacity）
        ├─ 边界线 GpuMesh（GL_LINES）
        ├─ 高亮 GpuMesh（按需重建）
        └─ ray_pick()
```

### 2.4 数据模型

`ArmorTriangleInfo` 扩展（`services/geometry_service.py`）：

```python
@dataclass
class ArmorTriangleInfo:
    material_id: int
    material_name: str
    layer_index: int
    thickness_mm: float
    color: tuple
    zone: str
    layers: list[float]   # 新增：该材质所有非零层厚度（Dual 多层，升序）
    hidden: bool          # 新增：游戏内查看器隐藏（Hull 区通用材质）
    plate_key: tuple      # 新增：(zone, material_name, thickness_tenths)
```

多层厚度：`_load_armor_thickness` 保持 `{(model_index, mat_id): mm}`；新增 `_load_armor_layers` → `{mat_id: [mm,...]}`（跨 model_index 收集非零层升序）。`thickness_mm` 取 layer_index 对应层（回退同材质最小非零层，保持现状）。

`models/armor_scene.py`：

```python
@dataclass
class ArmorScene:
    world_positions: np.ndarray        # (T*3,3) 舰船空间
    world_normals: np.ndarray          # (T*3,3)
    tri_info: list[ArmorTriangleInfo]  # 长度 T，与三角形索引对齐
    mesh_aabb: list                    # 每 ArmorMesh 世界包围盒（拾取预筛）
    mesh_tri_range: list               # (start, count) 扁平区间
    zones: dict                        # zone→part→thickness_tenths→[tri_idx]
    edge_positions: np.ndarray         # (E*2,3) 边界线端点
    bounds: tuple                      # (min, max)

    @classmethod
    def build(cls, armor_meshes) -> "ArmorScene"
    def ray_pick(self, ro, rd, visible_tris=None) -> int | None
    def tris_for_plate(self, key) -> list[int]
    def tris_for_part(self, zone, part) -> list[int]
    def tris_for_zone(self, zone) -> list[int]
```

世界变换：`world = (model_matrix @ [pos,1])[:3]`；挂点矩阵为刚体，法线直接用 3x3 部分。

### 2.5 渲染管线（ui/geometry_renderer.py）

着色器：复用现有单 program。装甲 `u_mode=2`（无光照 flat）+ `u_opacity`；边界线/高亮 `u_mode=1`（纯色）。不新增 program。

装甲模式 paintGL pass 顺序：

```
1. （可选 F6）船体垫底：u_opacity≈0.15，不写深度
2. 装甲：flat 色 + armor_opacity，写深度，LEQUAL，polygon offset(-1,-1)
3. 边界线（F1）：GL_LINES 黑色，polygon offset(-2,-2)，不写深度
4. 高亮（F4）：沿法线偏移覆盖，半透明，不写深度
```

- 边界线首版用 `GL_LINES`（core profile 线宽 1px 为已知取舍）；四边形粗边为后续增强。
- 高亮：选中橙色 `(1,0.6,0.1,0.6)`，偏移量随包围盒尺度缩放。

### 2.6 拾取与交互（F3）

- 屏幕坐标 → NDC → `inv(proj@view)` 反投影射线。
- `ray_pick`：per-mesh AABB 预筛 + Möller–Trumbore，返回最近 tri_idx；悬停节流 ~30fps；只拾取当前可见三角形。
- 悬停 → QToolTip：厚度色块 + `{mm} mm`、`{zone} / {material}`、多层时逐层色块（当前层加粗）。
- 点选 → 选中板块：F4 高亮 + 树定位（展开并选中节点）。

### 2.7 UI 重设计（ui/geometry_viewer.py，F7）

侧栏自上而下：

```
[舰船选择 + 加载]
── 显示 ──
  显示船体 / 显示装甲（厚度着色） / 线框叠加
  板块边界描边(F1) / 船体半透明垫底(F6)
  装甲不透明度滑杆(F5)
── 装甲结构树（F2，QTreeWidget 三级）──
  Zone → 部件(material)[三角形数] → {mm}mm 板[三角形数]
  每级 checkbox 三态级联控显隐；悬停高亮；点击选中 + 3D 高亮
  [全选] [全不选] 快捷按钮
── 选中信息 ──（悬停/选中板块详情）
── 装甲厚度图例 ──（保留 10 色桶，可折叠）
── 统计 ──（增加 板块数/部件数/zone 数）
```

- 旧的 8 个装甲类型复选框移除，由三级树取代。
- 双向联动：3D 拾取 → 树展开选中；树选中 → 3D 高亮。
- 保留船体/装甲互斥，但垫底开启时允许并存。

### 2.8 分阶段实施

| 阶段 | 内容 | 验证 | 状态 |
|------|------|------|------|
| P0-A | 数据层扩展（layers/hidden/plate_key + `_load_armor_layers`） | 探针打印 layers/plate_key | ✅ |
| P0-B | `models/armor_scene.py`（三角形汤 + 层级 + 边界线 + 拾取） | 离屏脚本验证边数/拾取 | ✅ |
| P0-C | 渲染器（边界线 + 不透明度 + 垫底 + 高亮） | 真实窗口渲染探针（大和：13117 三角形/5550 边，过滤/拾取/高亮/截图全通过） | ✅ |
| P0-D | UI 三级树 + 显隐联动 + 提示 + 滑杆 | UI 探针（树构建/级联勾选/掩码/双向选中联动全通过） | ✅ |
| 收尾 | 更新 repo memory + 清理 `_temp/scripts` | — | ✅ |

验证沿用离屏渲染探针（`QApplication + GeometryViewport + glReadPixels`，venv python）。不改数据库格式，无需 bump `DB_SCHEMA_VERSION`。

### 2.11 热修复（2026-08-20 晚：渲染不全/挂载偏移/缺失 + 移除 0mm）

用户报告「模型渲染不全、挂载模型坐标偏移、模型缺失」，并要求移除 0mm 板渲染。根因与修复：

1. **挂载装甲矩阵空间颠倒**（`models/armor_scene.py`）：`ArmorMesh.model_matrix` 是渲染空间（已 negz 共轭），而 ArmorScene 存未镜像舰船空间顶点，原代码直接相乘导致挂载装甲（炮塔等）整体偏移/缺失。修复：应用前先 `mat = negz @ mat @ negz` 转回舰船空间。
2. **上下文外上传缓冲**（`ui/geometry_renderer.py`）：`set_visible_tris` / `select_plate` 在 GL 上下文外执行 VBO 上传 → 未定义内容渲染为白色巨三角。修复：`_gl_ready` 守卫 + `_run_gl`（makeCurrent 包裹）+ `_vis_pending`/`_hl_pending` 延迟到 `paintGL`/`initializeGL` 补做。
3. **选中高亮颜色**：`select_plate` 原沿用默认悬停青色，浅色板上近白；修复为选中用 `HIGHLIGHT_SELECT` 橙。
4. **0mm 板渲染功能整体移除**：`ZERO_MM_EPS`、`_show_zero_mm`、`_armor_thicknesses`、`show_zero_mm` 参数、`cb_zero` 复选框及其连接全部删除。

验证：渲染探针（挂载 AABB 在船体范围内 ✓、高亮橙色 ✓、无白三角）+ UI 探针（初始掩码 12863、级联/全选/全不选/双向联动 ✓）。

### 2.9 关键常量

```python
PLATE_EDGE_COLOR = (0, 0, 0, 0.9)
HIGHLIGHT_HOVER = (0, 0.9, 1, 0.5)
HIGHLIGHT_SELECT = (1, 0.6, 0.1, 0.6)
HULL_BACKDROP_OPACITY = 0.15
HIDDEN_GENERIC_MATERIALS = {"Trans", "Deck", "Belt", "Inclin", "ConstrSide", "Bottom"}
QUANT = 10000          # 边键量化系数
CREASE_DOT = 0.7       # 折角阈值（法线点积）
```

### 2.10 风险

- 性能：大舰 >20 万装甲三角形 → 上传过滤而非重建场景；拾取 AABB 预筛 + 节流。
- 内存 2GB：三角形汤无索引共享，控制重复拷贝。
- GL：core profile 线宽=1px；`GL.ERROR_CHECKING=False` 维持。

---

## 三、修复记录（2026-08-20 用户反馈四项）

1. **主炮塔装甲模型方向反转**（`services/geometry_service.py`）
   - 根因：视觉网格与装甲共用含 `Root_BlendBone` 修正的 `mtx`；wows-toolkit（ship.rs L1124-1133）中装甲用**原始** hp_transform（装甲几何已与挂点对齐，不做旋转修正），多套一次 rb 导致方向反转。
   - 修复：三处（HP 主循环 / MP 甲板设备循环 / `_place_skeleton_mps`）为 ArmorMesh 单独计算 `armor_mtx = negz @ m_raw @ negz`（不含 rb）；视觉 MountMesh 保持 `mtx` 不变。
   - 验证：`_temp/scripts/probe_turret_armor.py` post-fix check 3/3 大和主炮塔装甲矩阵已不含 rb（centroid_err 0.271→0.178）。
2. **0mm 装甲仍显示**（`_build_armor_mesh`）
   - 修复：`thickness <= 0` 的三角形**硬剔除**（不进数组），全部剔除时返回 None；与 `hidden`（厚度>0 的通用 Hull 材质，可勾选恢复）语义分离。
   - 验证：大和 11,305 装甲三角形中 0mm 计数 = 0。
3. **装甲区中文词条**（`models/collision_materials.py` + `ui/geometry_viewer.py`）
   - 新增 `ZONE_CHINESE` + `zone_display()`；结构树顶层节点、悬停 tooltip、选中标签三处显示中文；内部 dict key / UserRole 数据保持英文（联动逻辑不变）。
4. **编号映射表外置**（`resources/database/collision_materials.json`）
   - 结构：`{version, description, materials:{id:str}, zones:{英文:中文}}`（206 条材质 + 11 区词条）。
   - `collision_materials.py` 加载器：文件系统（`get_bundled_dir()/resources/database/...`，源码模式热改即时生效）→ QRC（`:/resources/database/collision_materials.json`，打包模式）→ 硬编码兜底；JSON 条目覆盖同名硬编码。`gen_qrc.py` 自动纳入打包（build.bat 无需改动）。

验证（大和 PJSB018，探针 `_temp/scripts/`）：
- `probe_turret_armor.py`：post-fix check 3/3 炮塔装甲矩阵已应用 armor_mtx，centroid_err 0.271→0.178
- 0mm 计数 = 0（11,305 三角形全部 thickness>0）
- `probe_ui_tree.py`：ALL PASS（10 装甲区/71 板块，级联显隐与高亮联动正常）
- 树顶层节点：舰艏/副炮区/核心区/船体/其他/舵机舱/舰艉/上层建筑/防雷带/炮塔

---

## 附录 A：.geometry 格式规范（唯一格式文档，保留）

### A.1 MergedGeometryPrototype 头部（72 字节）

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

### A.2 MappingEntry（0x10 字节）

`u32 mappingId（murmur3 哈希）/ u16 mergedBufferIndex / u16 packedTexelDensity / u32 itemsOffset / u32 itemsCount`

### A.3 VerticesPrototype（0x20 字节）

`i64 verticesDataPtr / PackedString formatName / u32 sizeInBytes / u16 strideInBytes / u8 isSkinned / u8 isBumped`

顶点格式名如 `set3/xyznuvtbpc`：`xyz`=POSITION f32×3，`n`=NORMAL packed 4B，`uv`=TEXCOORD 2×f16，`tb`=切线/副切线，`iiiww`=骨骼索引×3+权重×2。

### A.4 IndicesPrototype（0x10 字节）

`i64 indicesDataPtr / u32 sizeInBytes / u16 保留 / u16 indexSize（2=u16, 4=u32）`

### A.5 CollisionModelPrototype（0x20 字节）

`i64 cmDataPtr / PackedString name / u32 sizeInBytes / u32 填充`。数据范围 = `cmDataPtr → cmDataPtr + sizeInBytes`。

碰撞数据为纯三角形汤：`u32 vertexCount / u32 indexCount / f32×3 顶点 / u16 索引`。命名 `CM_*`（CM_Helium 船体、CM_Turret 炮塔等），无材质信息。

### A.6 ArmorModelPrototype（0x20 字节）

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

### A.7 ENCD 压缩

Magic `ENCD`（0x44434E45）+ u32 elementCount + meshoptimizer 压缩 payload。用 `meshoptimizer` wheel 解码（注意 dtype 与 u16 索引包装）。

### A.8 PackedString（0x10 字节）

`u32 charCount（含 null）/ u32 填充 / i64 textPtr（相对偏移）`。

### A.9 舰船文件路径

```
content/gameplay/{nation}/ship/{type}/{ship_name}/{ship_name}_{part}.geometry
```

### A.10 装甲厚度数据源

主库 entity_snapshots 舰船快照：`A_Hull.armor` + `A1_Artillery/A_ATBA/...` 下各 `HP_*.armor`。键为 `(model_index << 16) | material_id` → mm；几何 layer_index = model_index。多层材质（Dual_*）同一 material_id 有多个 model_index 层。

---

## 参考资源

- [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) — `armor_viewer/ui/tab.rs`（板块上传/描边/高亮/tooltip）、`export/gltf_export.rs`（thickness_to_color / lookup_all_layers / InteractiveArmorMesh）、`docs/MODELS.md`
- 本仓库 `models/collision_materials.py`（材质表/色桶/zone/getArmorType 已与游戏一致）
- 反编译依据：`_decompile/` ArmorConstants.pyc / ModelArmor.pyc（见 repo memory `decompiled-armor-constants.md`）
