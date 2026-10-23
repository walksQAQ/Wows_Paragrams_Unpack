# Wows Paragrams Unpack

> 战舰世界 / Korabli 游戏数据自动化提取与分析工具

## 当前版本

[![Pre-release](https://img.shields.io/github/v/release/walksQAQ/Wows_Paragrams_Unpack?include_prereleases&label=pre-release)](https://github.com/walksQAQ/Wows_Paragrams_Unpack/releases)

[![Latest](https://img.shields.io/github/v/release/walksQAQ/Wows_Paragrams_Unpack)](https://github.com/walksQAQ/Wows_Paragrams_Unpack/releases/latest)

---

## 📖 简介

本工具用于从 **《战舰世界》（World of Warships / Mir Korablei）** 中提取、解析并可视化游戏数据。纯 Python 实现，支持 **Wargaming（WG）** 与 **Lesta（莱斯塔）** 双服务器。

- 完整数据链：舰船、模块、火炮、炮弹、飞机、消耗品、升级品、舰长等
- 资源提取：GameParams、assets.bin、PKG/IDX、纹理（bc7prep/DDS）、模型与特效等二进制格式解析
- 可视化：3D 舰船模型与装甲查看、穿深与散布计算、涂装与特效展示

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🔓 **数据提取** | 自动从游戏目录提取最新 GameParams / assets.bin，并在本地保存 |
| 🖥️ **图形界面** | PySide6 构建，分类导航 + 筛选 + 详情查看 |
| 🌐 **本地化** | 自动下载语言文件，显示中文名称 |
| 📦 **单文件打包** | 基于 Nuitka 编译为独立 exe，无需 Python 环境 |
| ⚔️ **3D 可视化** | `.geometry` 模型解析 + 装甲厚度着色渲染（PyOpenGL） |
| 🎯 **穿深 / 散布** | 基于游戏公式的穿深、纵向 / 横向散布计算 |
| 🧊 **模型导出** | 导出 GLB / glTF 2.0（含装甲模型、PBR 通道贴图、挂点层级、顶点权重） |
| 🧾 **明文转码**（实验性） | assets.bin 的 `.mfm` / `.visual` / `.model` / `.skel_ext` / 粒子 `.xml`（`high`/`low` 效果 + `shared` 元数据）转 Mod SDK 明文格式 |


### 使用流程

```
1. ⚙ 设置 → 高级设置，配置游戏目录路径，选择服务器（Lesta / Wargaming）
2. 📦 点击"加载数据" — 自动提取并解析数据
3. 🌐 点击"加载文本" — 下载中文语言文件（可选）
4. 左侧选择分类 → 中间筛选文件 → 右侧查看详情
```

#### 导出的 GLB 在 Blender 里怎么用

- **默认（勾选“导出骨骼顶点组”）**：层级/命名与 BigWorld 插件（`.primitives + .visual`）
  一致，`Scene Root → 部件 → visual 节点 → <Shape>`；蒙皮网格写标准 glTF skin，
  Blender 里直接得到顶点组与 Armature。骨骼显示球是 Blender 导入选项 "Bone Shape"
  造成的，导入时取消勾选即可隐藏。
- **取消勾选“导出骨骼顶点组”**（`GlbRenderOptions(export_skins=False)`）：**不含骨架**，
  所以没有骨骼球。顶点权重仍完整保存在网格属性里（`_JOINTS_0`/`_WEIGHTS_0` +
  `bone_palette`），需要顶点组时在 Blender 运行一次
  `tools/blender_wows_vertex_groups.py`（Scripting 工作区 → Run Script，或
  `blender --background --python tools/blender_wows_vertex_groups.py -- 模型.glb`），
  它会按上述属性还原顶点组，**不会创建骨架**。
- **顶点组与游戏内一致**：骨骼索引 = 渲染集调色板 slot × 3（同 BigWorld 插件的
  `index//3`），调色板按 `.visual` 原始顺序保留；同一材质下不同调色板的 shape 会
  拆成独立网格，避免权重被翻译到别人的骨骼上。


---
<br>

## 📸 程序主界面截图

![程序截图](FilesNotNeedInProgram/程序截图.png)


## 🧪 实验性功能：assets.bin 明文转码

assets.bin 浏览器里的「明文格式」/「导出明文」会把 `.mfm` / `.visual` / `.model` /
`.skel_ext` / 粒子图集 `.contours` 转成可读明文，并把粒子效果转成与游戏 `.xml`
粒子文件同构的 XML：

- `/particles/xxx.xml/high`、`/particles/xxx.xml/low`（`EffectPrototype`）→ 完整效果
  （系统 / 渲染器 / 发射器 / 动画 / 距离与标量曲线 / 强度通道曲线 /
  **动作载荷**：tint 渐变、ramp、力场、屏障等 / 光照组件）；
- `/particles/xxx.xml/shared`（`EffectMetadataPrototype`）→ 强度通道元数据
  （通道名 + min / max / 默认值，固定 6 个槽位，与 `high` 里每个 system 的
  `intensities` 曲线条数无关）；
- `/particles/*/<贴图>.dds_<fx>_<fy>_<a>_<b>.contours`（`AtlasContourProto`）→
  粒子图集**每帧轮廓多边形**（每帧 `pointCount` 个 vec2 点）。

同一个粒子 `.xml` 的 `high` / `low` / `shared` **会合成一份明文**（`xxx.xml`），
版式对齐游戏自带的粒子 XML（`res_unpack/helpers/particles/sfx_fail.xml`）：
`<high>` / `<low>` / `<shared>` 三段 + `<prototype>` + 制表符缩进、4 位小数。
文件树里这类粒子 `.xml` 也只占**一行**（自动折叠 high/low/shared，点它即得整份明文）。

**该功能为实验性，可能存在部分数据有误。**

粒子 XML 的字段布局来自客户端反编译（见
[docs/korabli-particles-effect-format.md](./docs/korabli-particles-effect-format.md)）：
**莱服 `Korabli64.exe`** 与 **寄服 `WorldOfWarships64.exe`** 各有一套布局
（寄服系统结构 0x1C8、莱服 0x210），按当前服务器自动选用，两服的
`high`/`low`/`shared` 都能转成明文（寄服差异见该文档 §16）。
结构化字段已全部解码；数据池里没有被任何字段引用的对齐/空闲字节不写进明文，
但仍参与回写，所以不改动时可逐字节还原原始数据。

原因是 assets.bin 的记录布局与 Mod SDK 明文并非一一对应，已知差异包括：

- **解析/明文规则（在「打开 assets.bin」对话框里选，默认「自动」，一般不用碰）**：
  - **选择游戏目录**时不弹对话框：先看客户端版本（`game_info.xml`；**Steam / depot 下载的老客户端
    没有这个文件**，改读 `bin/<构建号>/bin64|bin32` 的客户端主程序版本资源，如
    `v20210216` → `0.10.1.0`），早于 12.7 即进入远古版本模式；识别结果与客户端版本显示在
    工具栏「来源」里（悬停可看完整路径与判定依据）；
  - 连版本都读不到（目录里只有 `.pkg`）时，才退到**库内 prototype 类型**判断：
    有 Skeleton 且没有 ModelFbx/MiscSettings/Trail/VfxMaterial → **远古版本**；
    有 Skeleton 且有上述莱服新增类型 → Lesta；只有 SkeletonExtender → Wargaming；
  - **直接打开 `assets.bin` 文件**时没有客户端信息可探测，才需要在对话框里指定
    （`Lesta（莱服）` / `Wargaming（寄服）` / `远古版本`）；保持默认的 **`自动`** 走同一套
    库内原型判断，判不出来才退回 Lesta；
  - 客户端版本**早于 2023-08（12.7）**时进入**远古版本模式**：那时还没分家，只有一个客户端，
    统一按远古版本处理；寄服 **14.1 之前**（13.x / 14.0）的客户端记录布局也没变，
    归入「寄服旧布局」按同一套表解析（依据：官方 ModSDK release 的 `.model` 明文对照）；
  - 三个模式各自用**一张类型表**（`LEGACY_TYPES` / `WG_TYPES` / `KORABLI_TYPES`）：
    远古版本是 Material `0x58` + Model `0x40`（`.visual` 的 geometry/primitives 位置还互换），
    寄服现代是 `0x78/0x70/0x28`，莱服是 `0x88/0x40/0x20`。远古版本唯一还没坐实的是
    `castsShadow`（明文里省略该行，JSON 里保留 `+0x14` 的 `flags` 原值）；
  - 该规则是**本窗口的临时选项**：每次加载现选、不写回主程序配置，**也不继承主程序的
    `wows_type`** —— 浏览器自己判定该用哪张类型表（解码时用 `types.wows_type_context`
    临时切换并恢复），主程序的服务器设置既不被读取也不被改动；
- `<parentMfm>` 继承链：明文里有，assets.bin 二进制里没有（因此不会输出）；
- `<collisionFlags>`：SDK 导出器**一律写 0**（Lesta 26.10 共 13,068 处、WG 15.9 全部
  29,184 个文件都是 0）。经 exe 反汇编核对，该字段在 WG 记录 `+0x70`、且 31,534 个材质
  **实测全为 0**（内容从未设置过）；Korabli 记录里**没有这个字段**（Ghidra 反编译确认），
  所以 WG 侧写 `<collisionFlags>0</collisionFlags>`、**Lesta 侧不写这一行**；
- `sortOrder`（WG `+0x74` / Korabli `+0x80`）：二进制里有（16 个 `mesh_decal` 为 1..4，
  是贴花叠放顺序），但 **SDK 明文完全不导出**，因此本工具只在 JSON 里显示、不写明文；
- 数组属性按「材质 ID 稀疏」写出，全零项省略，与 SDK 的实际写法可能存在出入；
- `.visual` 的节点旋转限制、部分 renderSet 标志在二进制中缺失。

`collisionFlags` 位定义与取值表详见 [docs/prototype-formats.md](./docs/prototype-formats.md)。

请以**游戏内实际表现**为准；转码结果用于对照/排查，不建议直接当作官方 SDK 导出物使用。


## ⚠️ 免责声明

本工具仅用于学习和研究目的，所有游戏数据均由用户自行从其游戏客户端提取，本工具仅随附部分取自客户端的图片，不附带任何游戏数据或其他官方素材。

- 游戏相关一切内容版权归 **Wargaming.net** 或 **Lesta Studio** 所有；
- 例外：部分图片（如舰船/装备图标等）取自游戏客户端，随本工具打包分发，仅用于程序内数据辨识与展示，版权归原公司所有；
- 请勿将本工具用于商业用途，或再传播从游戏客户端提取的受版权保护内容。
- 界面主题中的装饰纹样（网格、切角、莫比乌斯环、心形、棱晶等）均为**代码绘制的原创几何图形**，不包含任何第三方角色立绘或宣传美术素材。

---

## 🎨 界面与主题

界面为一套集中管理的设计系统：深浅双主题 + 可扩展的「角色皮肤」注册表（当前提供「昔涟」白粉主题）。

- 设计规范与实现约定：[docs/ui-design-system.md](./docs/ui-design-system.md)
- 改代码前必读的项目约定与常见坑：[AGENTS.md](./AGENTS.md)

---

## 📄 许可证

本仓库采用**分离授权**结构，按代码归属分别适用不同许可证：

- **Apache License 2.0**：除下述 GPLv3 文件外，本仓库全部原创代码与文档按 Apache-2.0 授权（含专利授权条款）。详见 [LICENSE.Apache-2.0](./LICENSE.Apache-2.0)。
- **GPLv3**：`data_extractor/kraken.py` 基于 [kraken-decompressor](https://github.com/domdfcoding/kraken-decompressor)（GPLv3）移植，单独按 GNU GPL v3.0（或更高版本）授权，不适用 Apache-2.0。详见 [LICENSE.GPLv3](./LICENSE.GPLv3) 与该文件头部的许可证声明。

> ⚠️ **组合分发提示**：`kraken.py` 被本程序其余部分导入并构成同一组合程序。当你**分发**包含该文件的组合程序（如打包后的 exe）时，整体分发行为须遵守 GPLv3 的相应义务（提供对应源代码等）。Apache-2.0 与 GPLv3 兼容，可共存于同一程序。详见 [LICENSE](./LICENSE)。

## 👤 作者

- **walksQAQ** — 开发维护
- 仓库: [https://github.com/walksQAQ/Wows_Paragrams_Unpack]
- 下载编译好的程序请到 **Releases** 页面查找。


## ✨ 特别鸣谢

感谢 **DeepSeek**、**GitHub Copilot**、**Gemini** 等 AI 工具在本项目开发过程中的协助，大幅降低了代码编写、逆向分析与调试的工作量。


---
<br>

## 📚 引用与技术来源

本工具为纯 Python 实现，绝大多数数据格式分析参考和借助了以下开源项目与官方提供的部分文件，并结合 Ghidra 对游戏客户端的逆向验证。完整格式文档见仓库内 `docs/` 目录。

### 本项目参考

| 类别 | 项目 / 来源 | 用途 |
|------|------------|------|
| 格式解析 | [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) | IDX / PKG / `.geometry` / assets.bin / 材质 / 装甲 / camo 等格式与功能参考 |
| 格式解析 | [EdibleBug/WoWS-GameParams](https://github.com/EdibleBug/WoWS-GameParams) | `GameParams.data` 解析参考 |
| 解压算法 | [domdfcoding/kraken-decompressor](https://github.com/domdfcoding/kraken-decompressor)（C++，GPLv3） | Oodle Kraken 解压参考（对应移植文件 `data_extractor/kraken.py`） |
| 解压算法 | [powzix/kraken](https://github.com/powzix/kraken) | Kraken `DecodeBytes` / Huffman 熵解码参考 |
| 解压算法 | [detly/oozextract](https://github.com/detly/oozextract) | Oodle 解压（TANS / RLE / Huffman）参考 |
| 解压算法 | [WorkingRobot/OodleUE](https://github.com/WorkingRobot/OodleUE) | Oodle 引擎集成（2.9.15）、bc7prep 纹理格式参考 |
| 本地化 | [LocalizedKorabli/Korabli-LESTA-L10N](https://gitlab.com/localizedkorabli/korabli-lesta-l10n) | 本地化文本来源仓库 |
| 界面 / 计算 | [浩舰 iwarship](https://iwarship.net/wowsdb/dap) | 部分数据界面、散布穿深计算器参考 |
| 界面 / 计算 | [MKtool](https://mktool.info) | 舰船详情 / 穿深计算参考 |
| 3D 可视化 | [PyOpenGL](https://pypi.org/project/PyOpenGL/) / [pygltflib](https://github.com/teknotus/pygltflib) / [meshoptimizer](https://pypi.org/project/meshoptimizer/) | `.geometry` 解析与装甲展示渲染（PySide6 `QOpenGLWidget` + OpenGL）、GLB / glTF 2.0 导出、网格优化 |

<br>