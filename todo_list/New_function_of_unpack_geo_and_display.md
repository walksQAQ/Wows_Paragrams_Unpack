# 舰船 3D 模型解包与显示功能规划

## 概述

在当前 PySide6 数据分析工具中新增**3D 模型查看器**模块，实现从游戏客户端解包并显示舰船 3D 模型、装甲模型、碰撞模型的能力。

参考项目：
- [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) — Rust 编写的完整 WoWS 工具包，含 `.geometry` 解析、GLB 导出、装甲查看器（wgpu 3D 渲染）
- gmConverter3D — Electron + Three.js 实现的 BigWorld 模型查看器，支持 `.primitives`/`.object` 格式读取和 `.obj` 导出

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                   现有应用（PySide6）                      │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────────┐ │
│  │分类栏     │  │文件列表   │  │ 详情面板 (StackedWidget) │ │
│  │CategoryBar│  │Browser   │  │ ┌────────────────────┐ │ │
│  │          │  │          │  │ │ 现有数据分析页面    │ │ │
│  │          │  │          │  │ ├────────────────────┤ │ │
│  │          │  │          │  │ │ ★ 新: 3D 查看器页面 │ │ │
│  │          │  │          │  │ └────────────────────┘ │ │
│  └──────────┘  └──────────┘  └────────────────────────┘ │
│                      ┌──────────────────────┐           │
│                      │ 3D 渲染引擎 (PyQtGraph │           │
│                      │ / ModernGL / pygltf  │           │
│                      │ + QtOpenGLWidget)    │           │
│                      └──────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

---

## 二、分步实现方案

### 步骤 1：新建 3D 查看器页面（UI 层）

**文件**：`ui/geometry_viewer.py`

**内容**：
1. 新建 `GeometryViewer` 类，继承 `QWidget`，作为 `DetailPanel` 的 `QStackedWidget` 新页面
2. 添加 `QOpenGLWidget` 作为 3D 渲染区域
3. 添加控制面板（旋转/缩放/平移控制、装甲层开关、碰撞模型开关、LOD 选择）
4. 在 `DetailPanel` 中注册该新页面，通过分类栏切换
5. **按钮入口**：在 `toolbar_widget.py` 或 `category_bar.py` 中新增一个"3D 查看"按钮

**关键点**：
- `QOpenGLWidget` 提供 OpenGL 上下文
- 可使用 `ModernGL`（Python 轻量 OpenGL 绑定）或 `PyOpenGL` 直接渲染
- 或者使用 `pygltf` + `pyglet` 嵌入，但 Qt 集成度不如 ModernGL

**参考**：gmConverter3D 使用 Three.js + WebGL + OrbitControls，对应的 Python Qt 方案是 `ModernGL` + `QtGui.QOpenGLWidget` + 自实现轨道控制

### 步骤 2：游戏文件资源读取（数据层）

**文件**：`services/geometry_service.py`

**内容**：
1. 复用现有 `extractor_service.py` 的 IDX/PKG 解包机制
2. 新增 `GeometryExtractor` 类，负责从 `.pkg` 中定位并提取 `.geometry` 文件
3. 舰船 `.geometry` 文件路径规则（来自 wows-toolkit）：

```
content/gameplay/{nation}/ship/{type}/{ship_name}/{ship_name}_{part}.geometry
```

其中：
- `nation`: japan, usa, germany, uk, france, ussr, italy, pan_asia, europe, netherlands, commonwealth, spain, pan_america
- `type`: destroyer, cruiser, battleship, aircraftcarrier, submarine, torpedoboat, topship, topship, topship
- `part`: 如 `hull`, `hull_damaged`, `turret_1`, `tower` 等

4. 提供 `extract_geometry(ship_name: str) -> dict[str, bytes]` 方法

**参考**：wows-toolkit 的 `wowsunpack/src/main.rs:run_dump_uvs()` 函数通过遍历 nations 路径列表定位 `.geometry` 文件

### 步骤 3：`.geometry` 文件解析（核心）

**文件**：`models/geometry_parser.py`

**需要实现的二进制格式解析**（根据 wows-toolkit `docs/MODELS.md` 规范）：

#### 3.1 MergedGeometryPrototype 头部（72 字节）

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

**指针解析**：所有指针是相对于文件开头的**相对偏移**（`relptr`），解析时 `resolve_relptr(struct_base, relptr)` = `struct_base + relptr`。

#### 3.2 MappingEntry（0x10 字节）

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 4 | u32 | mappingId（哈希标识符） |
| 0x04 | 2 | u16 | mergedBufferIndex（合并缓冲区索引） |
| 0x06 | 2 | u16 | packedTexelDensity（编码纹素密度） |
| 0x08 | 4 | u32 | itemsOffset（在合并缓冲区中的起始偏移） |
| 0x0C | 4 | u32 | itemsCount（元素数量） |

#### 3.3 VerticesPrototype（0x20 字节）

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 8 | i64 | verticesDataPtr → 顶点数据 blob |
| 0x08 | 16 | PackedString | formatName（如 `"set3/xyznuvtbpc"`） |
| 0x18 | 4 | u32 | sizeInBytes |
| 0x1C | 2 | u16 | strideInBytes（每顶点步长，如 28, 32） |
| 0x1E | 1 | u8 | isSkinned |
| 0x1F | 1 | u8 | isBumped |

**顶点格式解析**（`set3/xyznuvtbpc` 含义）：
- `xyz` → POSITION (f32 × 3, 12 字节)
- `n` → NORMAL (packed 4 字节)
- `uv` → TEXCOORD_0 (packed 4 字节, 2× float16)
- `tb` → TANGENT + BINORMAL (2× packed 4 字节)
- `iiiww` → BONE_INDICES(3) + BONE_WEIGHTS(2) = 8 字节

#### 3.4 IndicesPrototype（0x10 字节）

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 8 | i64 | indicesDataPtr → 索引数据 blob |
| 0x08 | 4 | u32 | sizeInBytes |
| 0x0C | 2 | u16 | (保留) |
| 0x0E | 2 | u16 | indexSize（2=uint16, 4=uint32）|

#### 3.5 CollisionModelPrototype（0x20 字节）

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 8 | i64 | cmDataPtr → 碰撞数据 blob（相对偏移）|
| 0x08 | 16 | PackedString | collisionModelName（如 `"CM_FireControl"`）|
| 0x18 | 4 | u32 | sizeInBytes |
| 0x1C | 4 | (填充) | |

**碰撞模型数据结构**：

碰撞模型的原始数据 blob 不是 BVH 树格式（与装甲模型不同），而是**直接存储的三角形网格**（triangle soup），用于物理碰撞检测和弹道计算。其二进制布局如下：

```
[Header: 8 字节]
  u32 vertexCount          # 顶点数量
  u32 indexCount           # 索引数量（每个三角形 3 个索引）

[顶点数据: vertexCount × 12 字节]
  f32 x, f32 y, f32 z     # 每个顶点 3 × f32 = 12 字节

[索引数据: indexCount × 2 字节]
  u16 indices[]            # 每个索引 2 字节（uint16），每 3 个索引构成一个三角形
```

**碰撞模型命名规则**（`CM_` 前缀，表示 Collision Model）：
- `CM_FireControl` — 火控系统碰撞体
- `CM_Helium` — 船体
- `CM_Deck` — 甲板
- `CM_Tower` — 舰桥/上层建筑
- `CM_Turret` — 炮塔
- `CM_Bridge` — 舰桥
- `CM_Stack` — 烟囱

> **注意**：与装甲模型（`.armor` 后缀）不同，碰撞模型的数据 blob 直接从 `cmDataPtr` 指向的地址读取到 `cmDataPtr + sizeInBytes`，范围与装甲模型不同（装甲模型的数据范围从 struct_base + 0x20 开始）。

**碰撞模型 vs 装甲模型的区别**：

| 特性 | 碰撞模型 (Collision) | 装甲模型 (Armor) |
|------|---------------------|-----------------|
| 数据结构 | 简单三角形网格（顶点+索引） | BVH 树 + 三角形（带材质/层信息） |
| 数据范围 | cmDataPtr → cmDataPtr + sizeInBytes | struct_base + 0x20 → data_offset + sizeInBytes |
| 用途 | 物理碰撞检测、弹道阻挡 | 装甲穿透计算、装甲查看器显示 |
| 命名 | `CM_*` | `CM_*.armor` |
| 材质信息 | 无（纯几何） | 有 material_id + layer_index |

**Python 解析代码结构**：
```python
@dataclass
class CollisionMesh:
    name: str
    vertices: list[tuple[float, float, float]]
    indices: list[tuple[int, int, int]]

def parse_collision_model(data: bytes, name: str) -> CollisionMesh:
    stream = DataStream(data)
    vertex_count = stream.read_u32()
    index_count = stream.read_u32()
    
    vertices = []
    for _ in range(vertex_count):
        x = stream.read_f32()
        y = stream.read_f32()
        z = stream.read_f32()
        vertices.append((x, y, z))
    
    indices = []
    for _ in range(index_count // 3):
        i0 = stream.read_u16()
        i1 = stream.read_u16()
        i2 = stream.read_u16()
        indices.append((i0, i1, i2))
    
    return CollisionMesh(name=name, vertices=vertices, indices=indices)
```

#### 3.6 ArmorModelPrototype（0x20 字节）

与 CollisionModelPrototype 相同布局，但 `armorDataPtr` 指向的**数据范围从结构体结束处（struct_base + 0x20）到 data_offset + size_in_bytes**。

**装甲模型二进制格式（BVH + 三角形数据）**：
- 所有条目 16 字节
- 2 个全局头条目（包围盒 + BVH 节点数）
- N 个 BVH 节点组，每组：2 条目（节点头 + 包围盒最大 + 顶点数），vertex_count 个三角形顶点
- 每顶点：f32 x, f32 y, f32 z, u8[3] packed_normal, u8 zero = 16 字节

**装甲三角形结构**：
```python
ArmorTriangle {
    vertices: [[f32; 3]; 3],    # 三个顶点
    normals: [[f32; 3]; 3],     # 三个法线
    material_id: u8,             # 碰撞材质 ID（来自 BVH 节点头 byte 0）
    layer_index: u8,             # 层索引（来自 BVH 节点头 byte 2）
}
```

#### 3.7 ENCD 压缩数据解码

顶点和索引数据可能使用 **ENCD**（`0x44434E45`）格式压缩：
- Magic: `ENCD`（4 字节）
- elementCount: u32（4 字节）
- Payload: 剩余字节
- 使用 **meshoptimizer** 解码

**Python 实现**：需要使用 `meshoptimizer` 的 Python 绑定，或使用 `meshpy`，或用 `ctypes` 调用 meshoptimizer DLL。gmConverter3D 的 BigWorldReader 使用了 `MeshoptDecoder`（JS 版），Python 侧可以使用 `meshoptimizer` PyPI 包。

#### 3.8 PackedString 解析（0x10 字节）

| 偏移 | 大小 | 类型 | 字段 |
|------|------|------|------|
| 0x00 | 4 | u32 | charCount（包括 null 终止符）|
| 0x04 | 4 | (填充) | |
| 0x08 | 8 | i64 | textPtr（相对偏移 → 文本数据）|

---

### 步骤 4：装甲贴图与碰撞材质系统

**文件**：`services/armor_service.py`、`models/collision_materials.py`

根据 wows-toolkit 的反向工程结果：

#### 4.1 碰撞材质名称表

材质 ID 0–255 映射到材质名称，如：
- `Cit_Belt`, `Cit_Deck`, `Cit_Bulkhead` → 核心区
- `Bow_Bottom`, `Bow_Deck`, `Bow_Plating` → 船首
- `Cas_Plating`, `Cas_Deck` → 船中上层
- `SS_Plating` → 防雷鼓包
- `Deck_Armor`, `Belt_Armor`, `Bulge_Armor` → 通用装甲层
- `Trans_Water`, `Trans_Water_Additional` → 水下透明

#### 4.2 Splash Boxes（`.splash` 文件）

与 `.geometry` 文件同名的 `.splash` 文件包含命名 AABB，用于将装甲三角形分类到不同命中区域：
```
u32 count
每个 box:
  u32 name_len
  char[name_len] name     # 如 "CM_SB_bow_1"
  f32 min_x, min_y, min_z
  f32 max_x, max_y, max_z
```

分类规则：测试三角形中心点与所有 AABB，最小体积命中者获胜。

**重要**：游戏内装甲查看器的 Python 脚本决定哪些材质显示/隐藏。`Hull` 区域的板材在游戏查看器中不可见，但碰撞检测中仍然有效。

#### 4.3 多层装甲

某些材质（如 `Dual_Cit_Belt_0`）有多层，通过 `layer_index` 区分。不同层覆盖不同的空间区域。

---

### 步骤 5：3D 渲染（显示层）

#### 5.1 OpenGL 渲染方案

**方案 A：ModernGL + PyQt6**（推荐）
```python
from PySide6.QtOpenGLWidgets import QOpenGLWidget
import moderngl as mgl

class GeometryWidget(QOpenGLWidget):
    def initializeGL(self):
        self.ctx = mgl.create_context()
        # 编译 shader、创建 VAO

    def paintGL(self):
        self.ctx.clear(0.1, 0.1, 0.1)
        # 渲染所有网格
```

**方案 B：PyOpenGL + PyQt6**（传统方案）
```python
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL import GL

class GeometryWidget(QOpenGLWidget):
    def paintGL(self):
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        # 渲染网格
```

#### 5.2 需要实现的渲染功能

1. **舰船外壳模型**：从 `.geometry` 解析的顶点索引缓冲区渲染三角网格（带纹理/颜色）
2. **装甲模型**：半透明着色，按厚度颜色编码（从 wows-toolkit 移植 `thickness_to_color` 函数）
3. **碰撞模型**：线框/半透明显示，支持独立开关
4. **OrbitControls**：鼠标轨道控制（旋转/平移/缩放）— 可参考 gmConverter3D 的 `OrbitControls` 或 Three.js 实现
5. **光照系统**：简单环境光 + 方向光

#### 5.3 碰撞模型渲染详细方案

碰撞模型用于物理碰撞检测，通常不可见，但在开发/调试时需要显示。渲染方式：

**渲染模式选项**（UI 下拉选择）：
| 模式 | 说明 | 实现方式 |
|------|------|----------|
| 隐藏 | 不显示碰撞模型 | 默认状态 |
| 线框 | 显示三角形边线 | `GL_LINES`，颜色亮绿 `#00FF00` |
| 半透明实体 | 半透明填充 | `GL_TRIANGLES`，alpha=0.3，颜色按区域区分 |
| 叠加显示 | 叠加在船体上 | 深度测试 `GL_LEQUAL`，Z 偏移避免 Z-fighting |

**按碰撞模型名称着色**（便于区分不同碰撞体）：
```python
COLLISION_COLORS = {
    'CM_FireControl': (0.0, 1.0, 0.0, 0.3),   # 绿色 — 火控
    'CM_Helium':      (0.0, 0.5, 1.0, 0.3),   # 蓝色 — 船体
    'CM_Deck':        (1.0, 1.0, 0.0, 0.3),   # 黄色 — 甲板
    'CM_Tower':       (1.0, 0.5, 0.0, 0.3),   # 橙色 — 上层建筑
    'CM_Turret':      (1.0, 0.0, 0.0, 0.3),   # 红色 — 炮塔
    'CM_Bridge':      (1.0, 0.0, 1.0, 0.3),   # 紫色 — 舰桥
    'CM_Stack':       (0.5, 0.5, 0.5, 0.3),   # 灰色 — 烟囱
}
```

**碰撞模型列表面板**：在 UI 右侧显示所有碰撞模型的列表，带复选框控制显隐：
```
□ CM_FireControl    [线框] [半透明]
☑ CM_Helium         [线框] [半透明]
□ CM_Turret_1       [线框] [半透明]
...
```

#### 5.5 厚度颜色映射

```python
# 来自 wows-toolkit 的厚度到颜色映射
def thickness_to_color(mm: float) -> tuple[float, float, float, float]:
    if mm <= 0: return (0.5, 0.5, 0.5, 0.3)     # 灰色半透明
    if mm < 20: return (0.0, 1.0, 0.0, 0.6)      # 绿色
    if mm < 50: return (0.0, 1.0, 1.0, 0.6)      # 青色
    if mm < 100: return (0.0, 0.5, 1.0, 0.6)     # 蓝色
    if mm < 150: return (1.0, 1.0, 0.0, 0.6)     # 黄色
    if mm < 200: return (1.0, 0.5, 0.0, 0.6)     # 橙色
    if mm < 300: return (1.0, 0.0, 0.0, 0.6)     # 红色
    if mm < 400: return (0.8, 0.0, 0.8, 0.6)     # 紫色
    return (1.0, 0.0, 1.0, 0.6)                   # 品红
```

### 步骤 6：GLB/OBJ 导出功能

**文件**：`services/export_service.py`

1. 实现将解析后的 `.geometry` 数据导出为 Wavefront `.obj` 格式（参考 gmConverter3D 的 `WavefrontSaver.js`）
2. 可选实现 GLB 二进制导出（参考 wows-toolkit 的 `gltf_export.rs`）
3. 对装甲模型导出带厚度颜色信息的网格

**OBJ 格式导出**（简单可靠）：
```
# 顶点
v x y z
# 法线
vn nx ny nz
# 纹理坐标
vt u v
# 面
f v1/vt1/vn1 v2/vt2/vn2 v3/vt3/vn3
```

---

## 三、重点/难点详解

### 3.1 `.geometry` 二进制解析

这是**最核心也最复杂**的部分。关键点：

1. **相对指针解析**：所有指针（i64）是相对于结构体基址的偏移量。`resolve_relptr(base, ptr)` = `base + ptr`
2. **ENCD 压缩**：顶点/索引数据可能是 ENCD 压缩的（magic = `0x44434E45`），需要用 `meshoptimizer` 解码
3. **PackedString**：字符串存储为 16 字节结构体，实际文本在偏移位置，以 null 终止
4. **装甲数据 BVH 结构**：不是简单的三角列表示，而是 BVH 树结构需要遍历

**参考实现**：wows-toolkit 的 `crates/wowsunpack/src/models/geometry.rs` 提供了完整实现，可直接参考逻辑翻译为 Python。

### 3.5 ENCD 解码

Python 中没有现成的 ENCD/meshoptimizer 解码库，但有几种方案：

**方案 A**：使用 `subprocess` 调用 wowsunpack CLI 工具的 `--decode` 参数（最简单但需要分发 exe）
**方案 B**：用 `ctypes` 调用 `meshoptimizer` 的 C DLL
**方案 C**：使用 `numpy` 直接实现解码算法（复杂但纯 Python）

推荐**方案 B**，因为 gmConverter3D 和 wows-toolkit 都依赖 meshoptimizer 解码。

### 3.6 碰撞模型解析（Collision Model）

碰撞模型与装甲模型共享相同的 **0x20 字节结构体原型**（`ModelPrototype`），但数据格式完全不同：

| 方面 | 碰撞模型 | 装甲模型 |
|------|---------|---------|
| 解析函数 | `parse_model_array()` → `Vec<ModelPrototype>` | `parse_armor_model_array()` → `Vec<ArmorModel>` |
| 数据结构 | 纯三角形网格（顶点+索引，无材质信息） | BVH 树 + 三角形（带材质ID、层索引） |
| 数据范围 | `cmDataPtr → cmDataPtr + sizeInBytes` | `struct_base + 0x20 → data_offset + sizeInBytes` |
| 名称后缀 | 无（`CM_*`） | `.armor`（`CM_*.armor`） |
| 用途 | 物理碰撞检测、弹道阻挡判定 | 装甲穿透计算、厚度可视化 |

**关键实现细节**：

1. **数据读取**：碰撞模型的二进制协议与装甲模型使用同一 `parse_model_fields()` 解析前 8 字节（data_relptr + sizeInBytes），但碰撞模型的 `data_relptr` 直接指向数据起始位置

2. **三角形端点编号**：碰撞模型的索引数据可能使用 uint16（最常见）或 uint32，需根据文件实际编码判断

3. **碰撞模型名称**：通过 `PackedString` 解析得到 `CM_*` 格式的名称，可用于分类显示

4. **无材质系统**：碰撞模型不关联 `material_id` 或 `layer_index`，因此无法像装甲模型那样按厚度着色；渲染时按名称前缀分配固定颜色

**参考实现**：wows-toolkit 的 `geometry.rs:parse_model_array()` 和 `geometry.rs:parse_model_fields()`

### 3.7 装甲模型分层与着色

装甲模型在 `.geometry` 中以 BVH 树格式存储，需要：

1. 遍历 BVH 节点提取三角形
2. 读取每三角形的 `material_id` 和 `layer_index`
3. 查询 `GameParams` 获取材质厚度
4. 按厚度颜色编码渲染
5. 多层装甲需要将同一位置不同层的三角形重叠显示

### 3.9 与现有系统的集成

当前应用已有：
- `extractor_service.py` — 解包 `.pkg` 文件
- `database_service.py` — 数据库读写
- `analysis_service.py` — 数据分析
- `processor_service.py` — 数据处理

新的 3D 模块应：
- 复用 `extractor_service` 的 IDX/PKG 解包能力
- 从 `GameParams` 中读取装甲厚度数据
- 新增 `geometry_service.py` 管理 `.geometry` 文件的提取、缓存、解析

### 3.10 UI 集成

在 `category_bar.py` 或 `toolbar_widget.py` 新增"3D 模型"按钮：
```python
# 在 TopToolbar 或 CategoryBar 中
self.btn_3d_viewer = QPushButton("3D 查看")
self.btn_3d_viewer.clicked.connect(self._open_3d_viewer)
```

在 `DetailPanel` 中注册新页面：
```python
# detail_panel.py 中
class DetailPanel(QWidget):
    def __init__(self):
        # ... 现有代码 ...
        self.geometry_viewer = GeometryViewer()  # 新页面
        self.stacked.addWidget(self.geometry_viewer)
```

---

## 四、文件清单与实现顺序

| 优先级 | 文件 | 说明 |
|--------|------|------|
| P0 | `models/geometry_parser.py` | `.geometry` 文件格式解析（最核心，含碰撞/装甲模型）|
| P0 | `services/geometry_service.py` | 几何数据提取服务 |
| P1 | `ui/geometry_viewer.py` | 3D 查看器 UI 页面（含 QOpenGLWidget） |
| P1 | `ui/geometry_renderer.py` | OpenGL 渲染引擎（ModernGL 实现） |
| P2 | `models/collision_materials.py` | 碰撞材质名称表与厚度数据 |
| P2 | `services/armor_service.py` | 装甲数据处理服务 |
| P2 | `models/collision_parser.py` | 碰撞模型数据解析（从 raw blob 提取三角网格）|
| P3 | `services/export_service.py` | OBJ/GLB 导出功能（含碰撞模型导出） |
| P3 | 修改 `detail_panel.py` | 注册几何查看器页面 |
| P3 | 修改 `category_bar.py` / `toolbar_widget.py` | 添加 3D 查看按钮 |
| P4 | `models/camera.py` | 轨道摄像头控制 |
| P4 | `models/shader.py` | GLSL 着色器程序（碰撞模型线框/实体两种）|

---

## 五、参考资源

### 格式规范
- [landaire/wows-toolkit/docs/MODELS.md](https://github.com/landaire/wows-toolkit/blob/main/docs/MODELS.md) — 完整的 `.geometry`、`models.bin`、`space.bin` 装甲系统格式规范

### 参考实现
- [wowsunpack/src/models/geometry.rs](https://github.com/landaire/wows-toolkit/blob/main/crates/wowsunpack/src/models/geometry.rs) — `.geometry` 解析器（Rust）
- [wowsunpack/src/export/gltf_export.rs](https://github.com/landaire/wows-toolkit/blob/main/crates/wowsunpack/src/export/gltf_export.rs) — GLB 导出（Rust）
- [wows-toolkit-gpui/src/armor_viewer](https://github.com/landaire/wows-toolkit/tree/main/crates/wows-toolkit-gpui/src/armor_viewer) — wgpu 装甲查看器（Rust + gpui）
- [wows_toolkit/src/armor_viewer](https://github.com/landaire/wows-toolkit/tree/main/crates/wows_toolkit/src/armor_viewer) — egui 装甲查看器（Rust + egui + wgpu）
- gmConverter3D BigWorldReader.js — BigWorld `.primitives`/`.object` 格式读取（JavaScript）
- gmConverter3D WavefrontSaver.js — OBJ 导出（JavaScript）

### Python 3D 库
- [ModernGL](https://github.com/moderngl/moderngl) — 轻量 Python OpenGL 绑定
- [PyGLM](https://github.com/Zuzu-Typ/PyGLM) — OpenGL 数学库
- [meshoptimizer](https://pypi.org/project/meshoptimizer/) — 网格优化/解码（需 C++ 扩展编译）
- [trimesh](https://github.com/mikedh/trimesh) — 三角形网格处理库
- [pygltflib](https://github.com/teknotus/pygltflib) — GLTF/GLB 读写
