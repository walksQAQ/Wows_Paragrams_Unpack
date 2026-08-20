# 舰船 3D 模型解包与显示 —— 装甲展示重构规划

> 状态：**装甲展示重构已完成（2026-08-20）+ 后续修复已完成（2026-08-20，见「三、重构后修复」）**
>
> 本文档原为 3D 查看器首版规划（已实现，见「一、现状」）。重构任务：**参考 landaire/wows-toolkit 彻底重构装甲模型展示功能并重做查看器 UI**（见「二、装甲展示重构设计」，P0-A~P0-D 全部完成并验证）。`.geometry` 格式规范见 `docs/geometry-format.md`（唯一格式文档）。

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

首版遗留（未实现，低优先级）：OBJ 导出、碰撞模型渲染。

### GLB 舰船模型导出设计方案（待实现）

> 实施顺序与 INDEXED 转码细节见 `todo_list/New_function_of_fix_indexed_render_and_export_glb.md`：
> 先修正 INDEXED 特殊渲染规则（P1），渲染正确后再启动导出（P2）；INDEXED 导出贴图
> 按用户要求烘焙成标准 PBS 形态（baseColor/normal/MG/AO 常规贴图集）。

#### 1. 目标与边界

新增 GLB（glTF 2.0 Binary）导出能力，导出结果应能在 Blender、Godot、Three.js
等标准 glTF 工具中直接打开。导出对象以当前 `ShipGeometry` 为唯一输入，不重新解析
`.geometry`，不依赖 `data/split/*.json`，也不把 OpenGL 缓冲区反向读回 CPU。

首期目标：

- 导出舰体全部 `hull_meshes`；
- 导出 `mounts` 中的炮塔、副炮、防空、指挥仪和甲板设备，并应用已有挂载矩阵；
- 导出法线、UV、三角形索引和可用的漫反射贴图；
- 导出装甲作为独立节点，可选择“实体舰体”“装甲着色”“两者同时导出”；
- 大模型采用二进制 GLB，避免 OBJ 的多文件贴图、材质和坐标管理问题；
- 导出在后台线程执行，完成后由主线程弹出保存结果和警告摘要。

明确不在首期强行复刻游戏 shader：GLB 使用 glTF 标准 `PBR Metallic-Roughness`，
不能完整表达游戏的 INDEXED 分块涂装、detailMap、多层材质混合和运行时 shader 参数。
这些信息通过贴图烘焙或 `extras` 保留，不能静默宣称与游戏内渲染完全一致。

#### 2. 数据映射

| 当前对象 | GLB 对象 | 处理方式 |
|---|---|---|
| `ShipGeometry` | 根节点 `ship_<game_key>` | 写入舰船 ID、名称、模型目录和导出版本到 `node.extras` |
| `HullMesh` | 一个 glTF `mesh` + `node` | 位置、法线、UV、索引直接转为 accessor；舰体坐标保持统一 |
| `MountMesh` | 一个带局部矩阵的 `node` | 几何保留本地坐标，`model_matrix` 写入 node.matrix；不得再次烘焙矩阵 |
| `ArmorMesh` | 独立的 `armor` 节点/mesh | 应用与 `ArmorScene` 相同的世界空间变换；按 `component` 和 `plate_key` 分组 |
| `texture_dds` | glTF image / bufferView | 转码为 PNG 或 JPEG 后嵌入 GLB；原始 DDS 路径写入 `extras` |
| `material_textures` | PBR 贴图集合 | 首期至少映射 diffuse/albedo；normal、metallic/roughness 按可解码性映射 |
| `indexed_params` | `extras.wows_indexed` | 保存数组、网格、offset 和原始材质路径，首期不直接作为标准 shader 输出 |

推荐节点层级：

```text
ship_<game_key>
├─ Hull
│  ├─ <hull mesh part> ...
├─ Mounts
│  ├─ MainBattery/<mount> ...
│  ├─ Secondary/<mount> ...
│  ├─ AA/<mount> ...
│  └─ Equipment/<mount> ...
└─ Armor
   ├─ Hull/<zone>/<part>/<thickness> ...
   └─ Mounts/<component>/<part>/<thickness> ...
```

#### 3. 坐标系与矩阵规则

当前渲染链路包含 `negz = diag(1, 1, -1, 1)` 的 OpenGL 镜像约定，GLB 导出不能
直接复制渲染器中的矩阵。导出服务先统一到 glTF 右手坐标系，再对所有顶点执行一次
坐标转换：

```text
gltf_position = C * source_position
gltf_normal   = normalize(C3 * source_normal)
gltf_matrix   = C4 * source_matrix * inverse(C4)
```

其中 `C` 的具体定义必须由一个小型探针用已知船体和挂载 AABB 验证；不能凭视觉猜测。
舰体 `HullMesh` 通常已经在舰船坐标系，直接应用 `C`；挂载沿用 `MountMesh.model_matrix`；
装甲沿用 `ArmorScene.build()` 的世界空间变换规则，并验证炮塔装甲质心仍落在对应挂载附近。

#### 4. 材质与贴图策略

分三档实现，避免把游戏专用材质问题混入几何导出：

1. **标准基础档（首期必做）**：每个 mesh 使用 `baseColorTexture` 或
   `baseColorFactor`；无贴图时使用白色。`opaque=False` 的材质设置 alpha blend，
   并将 `alphaMode` 写入 glTF。
2. **PBS 增强档**：将 `normalMap` 映射为 `normalTexture`，将 metallicGloss 拆成
   metallic/roughness 通道；必要时先把 DDS 转码到 PNG，记录通道来源和近似规则。
3. **INDEXED/游戏 shader 档**：不伪造标准 PBR 结果。支持时将 material ID map、
   albedoArray、art map 烘焙成一张最终 base color；不支持烘焙时导出默认材质，
   同时在 `material.extras.wows_indexed` 保存原始参数和资源路径。

当前程序的 DDS 读取器主要服务 OpenGL 上传，导出服务应增加明确的
`DDS -> PNG/JPEG` CPU 转码步骤，并在遇到 BC/格式不支持时记录警告而跳过贴图，
不能把 DDS 原始字节直接伪装成 glTF PNG/JPEG。

#### 5. 装甲导出模式

导出接口建议提供：

```text
armor_mode = "none"       # 只导出可视舰船
             | "solid"     # 导出装甲几何，使用厚度颜色
             | "both"       # 舰体 + 装甲，装甲半透明
armor_hidden = false       # 是否包含当前 hidden 通用 Hull 板
armor_visible_only = true  # 是否遵循查看器当前树的显隐掩码
```

装甲 mesh 按 `plate_key=(zone, material_name, thickness_tenths)` 分组，材质使用
厚度颜色和透明度；每个节点的 `extras` 保存 `zone`、材质名、厚度、layer index、
component 和 triangle 数。这样导入 Blender 后仍能按装甲区筛选，而不是只得到一张
无法追溯来源的彩色大网格。`0mm` 三角形已经在 `_build_armor_mesh()` 中剔除，
导出层不应重新生成它们。

#### 6. 服务与接口设计

新增 `services/export_service.py`，只负责把已加载的 `ShipGeometry` 转换为 GLB，
不负责加载舰船。建议接口：

```python
class GlbExportOptions:
    armor_mode: str = "none"
    armor_hidden: bool = False
    armor_visible_only: bool = True
    embed_textures: bool = True
    export_mounts: bool = True
    export_collision: bool = False


def export_ship_glb(
    geometry: ShipGeometry,
    output_path: Path,
    options: GlbExportOptions | None = None,
    progress_cb=None,
) -> ExportReport:
    ...
```

实现建议使用成熟 glTF 库（优先 `pygltflib`；若验证后需要更方便的 mesh/材质
构建，可评估 `trimesh`），不要手写 GLB 二进制 chunk。`ExportReport` 至少包含
导出节点数、三角形数、贴图数、跳过数量和警告列表。

导出流程：

1. 校验 `ShipGeometry` 非空，并冻结当前查看器的装甲显隐掩码；
2. 建立 glTF buffer、bufferView、accessor，按 mesh 批量追加顶点/法线/UV/索引；
3. 建立材质缓存，使用“材质属性 + 贴图路径 + alpha 状态”作为去重键；
4. 写入 Hull、Mounts、Armor 节点和矩阵；
5. 转码并嵌入贴图，失败时保留几何并追加 warning；
6. 计算每个 mesh 的 bounds 与总 bounds；
7. 写入 `asset.extras.wows_export`、节点 extras 和可选的原始路径信息；
8. 在临时文件写完并成功重新读取校验后，再原子替换目标 `.glb`。

#### 7. 查看器 UI 与线程

在 `ui/geometry_viewer.py` 增加“导出 GLB”按钮和保存对话框：

- 没有 `_current_geom` 或正在加载时禁用；
- 导出选项使用复选框/下拉框：挂载、装甲模式、当前可见板块、嵌入贴图；
- 复用现有 `run_async`，导出期间显示进度和取消状态；
- 后台线程只读 `ShipGeometry`，不调用 Qt/OpenGL API；
- 完成后在主线程显示输出路径、统计和警告；
- 窗口关闭或切换舰船时，不删除正在写入的临时文件。

详情页的“3D 模型查看”只负责打开查看器，不直接触碰导出服务，避免把导出失败
误判为查看器加载失败。导出入口应使用当前已加载的模型，避免再次加载客户端 VFS。

#### 8. 验证计划

分阶段验证，先验证几何和坐标，再验证材质：

| 阶段 | 验证内容 | 通过条件 |
|---|---|---|
| G0 | 最小合成三角形导出/再读 | GLB 能被标准 glTF 解析器重新打开 |
| G1 | 真实舰体无贴图导出 | 节点、顶点、索引、bounds 与 `ShipGeometry` 一致 |
| G2 | 炮塔/挂载矩阵 | 导入后挂载 AABB 在舰体范围内，质心方向不反转 |
| G3 | 装甲分组 | zone/part/厚度节点数量和三角形计数与 `ArmorScene` 一致 |
| G4 | 贴图 | Blender/Three.js 可显示 base color；失败贴图有 warning |
| G5 | 大船性能 | 导出不超过内存红线，后台 UI 不冻结，临时文件可清理 |
| G6 | 打包版 | onefile 中点击导出可用，输出 GLB 不依赖临时解压目录 |

必须保留一份探针到 `_temp/scripts/`：使用真实舰船导出 GLB，再用 glTF 解析器检查
buffer、accessor、image 和 node matrix；必要时用 Blender 或 Three.js 做一次人工
截图验收。不同服务器、缺失贴图、无装甲数据和空模型都应有明确警告而不是静默失败。

#### 9. 依赖与打包注意事项

- 将 `pygltflib`（或最终选定库）加入 `requirements.txt`；
- 若导出库含动态导入或本地扩展，先在 onefile 构建中验证并按实际情况添加
  `--include-package`，不能仅凭源码能导入判断打包完整；
- `meshoptimizer` 继续作为模块级依赖，并确认
  `meshoptimizer/_meshoptimizer*.pyd` 被打入 onefile；
- GLB 输出只写到用户选择的外部路径，不能写入 Nuitka onefile 临时目录；
- 不把游戏原始 `.dds`、`.mfm` 或客户端路径作为 GLB 必需外链，嵌入失败时仍应生成
  无贴图几何；
- 导出格式版本和坐标转换规则写入 `asset.extras`，以后调整矩阵时可追溯。

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

## 附录 A：.geometry 格式规范

> `.geometry` 格式规范已迁移至 `docs/geometry-format.md`（唯一格式文档，2026-08-20）。

## 参考资源

- [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) — `armor_viewer/ui/tab.rs`（板块上传/描边/高亮/tooltip）、`export/gltf_export.rs`（thickness_to_color / lookup_all_layers / InteractiveArmorMesh）、`docs/MODELS.md`
- 本仓库 `models/collision_materials.py`（材质表/色桶/zone/getArmorType 已与游戏一致）
- 反编译依据：`_decompile/` ArmorConstants.pyc / ModelArmor.pyc（见 repo memory `decompiled-armor-constants.md`）
