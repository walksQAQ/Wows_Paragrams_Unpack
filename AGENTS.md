<!-- markdownlint-disable MD032 -->
# AGENTS.md — 仓库记忆

本文件是给 AI 助手/新贡献者的**项目长期记忆**：约定、红线、常见坑。改代码前先读这里。
细节设计文档见 [docs/ui-design-system.md](docs/ui-design-system.md)。

---

## 1. 项目速览

PySide6 桌面工具：从《战舰世界 / Korabli》客户端提取并分析游戏数据（舰船、模块、火炮、弹药、飞机、消耗品、升级品、舰长等），支持 Lesta 与 Wargaming 双服务器。

| 目录 | 职责 |
|---|---|
| `main.py` | 入口：字体、调色板、全局 QSS、主题应用 |
| `app/` | 应用上下文、配置（`config.py`）、信号总线（`signals.py`） |
| `services/` | 数据服务：数据库、解析、导出 |
| `presenters/` | 数据 → 视图模型 |
| `models/` | 数据模型、名称映射 |
| `ui/` | 全部界面；`ui/widgets/` 为自绘控件与主题组件 |
| `utils/` | 主题（`theme.py`）、路径、子进程工具 |
| `uncode_assets/` | assets.bin / PKG / IDX 等二进制解析与其独立 GUI |
| `resources/styles/main.qss` | 全局样式表（`@token@` 占位符） |

**验证环境**：一律用 `.venv\Scripts\python.exe`（系统 Python 缺依赖）。

---

## 2. UI 约定（改界面必读）

### 2.1 颜色只能来自主题 token

- 所有颜色必须走 `utils/theme.py` 的 token（`theme["key"]` / `theme.qcolor("key")` / QSS 里的 `@key@`）。
- **禁止**在业务代码里写死十六进制色值。
- QSS 块必须用 `theme.qss(...)` 或 `theme.bind(...)` 包裹，否则 `@token@` 不会被替换。

### 2.2 主题 = 深浅模式 × 角色配色

- 深浅：`auto` / `light` / `dark`；角色配色：见 `utils/theme.py` 的 `SKINS` 注册表。
- 角色配色**只替换整份调色板**，不含任何纹样/立绘/水印；界面结构（网格、切角、辉光）在所有主题下完全一致。
- 启用角色配色时 `theme.dark` 恒为 `False`。
- 所有调色板（`_LIGHT` / `_DARK` / 各角色）的**键集必须完全一致**，新增 token 时每份都要加。
- **角色配色仅在源码/调试运行时可用**：`skin_ids()` 在 Nuitka 编译的发布版里返回空元组，因此发布版的下拉里只有 auto/light/dark，配置文件里写皮肤 id 也会被 `get_skin()` 判为不可用并回落到普通深浅色。

### 2.3 圆角规则（2026-10 明确）

- **没有特殊造型的普通控件一律圆角**：滑条、输入框、下拉框、普通按钮、数值框、滚动条滑块、分组框等。半径集中在 `resources/styles/main.qss`（3–7px），不要在各个页面重复定义。
- **只有带斜角切割的专用控件才有直角/切角**：`SciFiPanel`、`SciFiButton`、`HoloDialog` 外框等，由自绘代码实现，不受 QSS 圆角影响。
- 判断标准：这个控件是不是"光学结构"的一部分？不是 → 圆角。

### 2.4 装饰要素不得影响数据

- 底纹、光带、品牌标识**只能出现在背景层**（`HoloBackdrop` 的底图上），即所有面板之下，绝不覆盖任何文字或数值。
- **禁止**用置顶叠加层（`raise_()` 之后绘制）去盖文字实现"水印感"。
- 角色主题**只改配色**；唯一允许保留的结构性空间是「立绘预留位」（`ui/widgets/skin_art.py` 的 `SkinArtSlot`），它只占横向空间、不绘制内容，也不接收鼠标。
- **唯一允许的颜色叠加**：舰长技能、舰船配件等图标格子的深色底——因为游戏图标是白色单色图形，浅色主题下必须有高对比底才能看清。
- 半透明只作用于**背景层**；禁止 `setWindowOpacity`（会把文字一起淡化）。

### 2.5 图标按钮（技能/配件/升级品/信号旗）

- 底色在深浅两套主题下**都保持深色**，白图标对比度 ≥ 9:1。
- 三态靠亮度分档 + 亮色描边表达，不靠把底色刷亮。
- 相关 token：`icon_btn_bg` / `icon_btn_bg_hover` / `icon_btn_checked` / `icon_btn_border` / `icon_btn_border_hi` / `icon_btn_text` / `icon_btn_text_hi`。

### 2.6 模型查看器左栏（部件列表 / 装甲结构）

- 左栏是 `QStackedWidget`，两块列表**互斥显示**：`PartsTreePanel`（模型部件）+ `ArmorTreePanel`（装甲结构），由右栏「显示船体 / 显示装甲」切换（两者本就互斥，`_show_side_page` 负责翻页）。
- **不要**把装甲结构树塞回右栏：右栏是固定 330px 宽的控件堆栈，多一个 `stretch=1` 的列表会把其它分组挤成缝、列表本身只剩几行。
- 右栏布局末尾必须保留 `addStretch(1)`，否则隐藏/新增控件会让各分组之间冒出随机空隙。

---

## 4. 常见坑（踩过的）

| 坑 | 说明 |
|---|---|
| QSS 能力边界 | 不支持 `box-shadow` / `transition` / `transform` / `backdrop-filter` / `letter-spacing` |
| `QPen(col, w, cap=...)` | PySide6 非法，必须用 `QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)` |
| `WA_StyledBackground` | 纯 `QWidget` 子类必须设置，否则 QSS 的 `background-color` 静默不绘制 |
| 内联样式优先级 | `widget.setStyleSheet()` > `app.setStyleSheet()`；`QPalette.Highlight` 又压过 QSS 的 `::item:selected` |
| 弹出列表必须自带不透明底 | 全局 QSS 为了让列表融进面板把 `QListView` 设成 `transparent`；`QCompleter` 的 popup 是**独立顶层窗口**，透明 = 什么都不绘制 = 黑块 + 深色文字不可读。新建 completer 后必须调 `theme.style_popup_view(completer.popup())` |
| 父控件绘制会被子控件覆盖 | 装饰必须画在内容区之外的空带里，或退回背景层 |
| 切角是斜的 | 内容四角必须满足 `x + y >= 2*MARGIN + chamfer`，否则控件从切掉的角穿出；用 `SciFiPanel.content_margins()` |
| `apply_theme()` 不广播 | `main.apply_theme()` 单独调用不会发 `theme_changed`，自绘控件缓存会滞留旧色；只有 `application.set_theme_mode()` 会广播 |
| `compileall` 触发 qrc 重建 | `resources/__pycache__` 曾被打进资源包；`.pyc` 与缓存目录已在 qrc 生成脚本里排除 |
| 子进程约束 | spawn 下 worker 必须是模块级函数、参数可 pickle、子进程内无 Qt 事件循环；打包必须 `multiprocessing.freeze_support()` |
| 输出路径必须校验落点 | `.idx`/`.pkg` 条目名与游戏数据字段都是外部输入，可直接 `Path / name` 或 `os.path.join` 会被 `../`、反斜杠、盘符前缀带出输出目录（任意文件写入）。一律用 `utils.path_utils.safe_join(base, *parts)`，越界抛 `ValueError` |
| 部件树 key 必须与后端一致 | `hull:i` / `mount:i` 由 `GeometryViewport.set_scene` 与 `renderer/scene.py::build_scene` 按**生成顺序**分配，左侧 `PartsTreePanel` 与两套后端共用这套 key；改生成顺序或再跳过某类网格会让勾选错位/指向不存在的网格（损坏网格改为「默认隐藏」而不是丢弃） |
| 网格 key 不能被贴图 key 覆盖 | `renderer/scene.py::_build_mesh` 内部的局部变量 `key` 是**贴图** key（`t12` 之类）。新增参数误命名成 `key` 会让全部网格 key 变成贴图 key ⇒ 大量重名 ⇒ DLL 同名网格就地替换（模型炸开/错乱、`set_mesh_visible` 全失效）。显式网格 key 参数必须叫 `mesh_key`，并统一经 `_KeyGen.take()` 去重 |
| `ItemIsAutoTristate` 会向下传染 | 部件树的父行**不能**加 `Qt.ItemIsAutoTristate`：程序里把父项设成 `PartiallyChecked` 时 Qt 会把它写给所有子项 ⇒ 取消任意一行都会让"隐藏集合"变成全集（整个模型消失）。级联与父项汇总由 `PartsTreePanel` 手工处理 |
| 递归删除必须先认目录 | `rmtree` 的目标若由「exe 同级 / 数据目录」推出来，删除前要确认它确实是本程序的产物（例：旧工具的 `content/` 根下必有 `GameParams*.data`）。否则把解包器 exe 放进客户端或 `res_unpack/` 旁边，一次「加载数据」就会连带删掉整棵 `content/` 资源树 |
| 解包落点必须收进 `res_unpack` | 客户端目录内只能落在 `<客户端>/res_unpack/`：客户端根自动改指，客户端内其它位置直接拒绝；另一个客户端（根或子目录）一律拒绝；普通目录自动套一层 `res_unpack`。规则集中在 `ui/unpacker_dialog.py::_resolve_output_dir`。判「是不是客户端根」只看目录自身（主程序名，或 `res_packages/` + `bin/` 并存），**不能**用 `detect_wows_type` 的递归探测——`res_unpack/` 里解包出的 `bin/` 会让它把自己的产物误判成客户端 |
| Qt 对象被 GC | 冒烟脚本里窗口必须用列表持有引用，否则 C++ 析构可能崩溃（`0xC0000409`） |
| 中文乱码 | PowerShell 内联 here-string 经管道传给 Python 会变 `?`；复杂脚本写成 UTF-8 `.py` 文件再执行 |
| 启动闪小窗 | 自绘控件在 `__init__` 里对**还没有父控件**的自己调 `setVisible(True)`，会让它先变成一个独立的顶层窗口（12×12 闪一下）。构造期只在需要隐藏时 `setVisible(False)`，显示交给布局；给控件设显隐要放在 `layout.addWidget()` 之后 |
| D3D 视口鼠标悬停没反应 | `D3DViewportAdapter`（原生子窗口 + `WA_PaintOnScreen`）不会自动收到「无按键移动」：Qt 默认只在按住鼠标时发 `mouseMoveEvent`，所以装甲厚度提示 / 悬停高亮全军覆没而**点击选中仍然正常**。`D3DViewportAdapter.__init__` 里必须 `setMouseTracking(True)` |
| 加载遮罩不能叠在 D3D 面上 | D3D 视口（`RenderView`）是 `WA_PaintOnScreen` 原生子窗口，Qt 自绘控件叠在它上面无法可靠合成：进度文字会留鬼影，上传早在 0.1s 内结束、屏幕上却一直停在旧百分比（`正在上传到 GPU 172/215（80%）`，实测被当成卡死）。D3D 后端不叠遮罩：加载文字写右侧面板状态区，上传进度走面板进度条（`RenderView.scene_upload` → `GeometryViewerDialog._on_scene_upload`）；遮罩只给 OpenGL 后端用 |
| 重载期间别先清场景 | 3D 查看器加载/重载**不要**先 `viewport.clear_scene()`：解析一艘船几十秒，渲染区整段全黑，看起来像卡死。保留上一帧模型，新场景上传时一次换掉；只有加载失败/关闭时才清 |
| 「本地化缺失」口径 | 只认「语言文件里**没有该键**」。键存在但译文为空/只有一个空格/原样回填 `IDS_xxx` 只算"未翻译"，**不算**缺失——这类条目在列表/详情名称后标「⚠ 未翻译」，由 `utils/loc_status.py` 统一文案与判定。语言文件侧仍以 `lang_zh=''` 写进 `name_mappings`（保留键存在性、不覆盖已有译名），读取侧（Python 真值判断、SQL 一律 `COALESCE(NULLIF(lang_zh,''), ...)`）自动回退。判断缺失用 `nm.id IS NULL`，不要用 `TRIM(lang_zh)=''` |

---

## 5. 验证流程
1. 全量语法检查（排除 `.venv` / `__pycache__` / `_decompile`）：
   ```powershell
   .venv\Scripts\python.exe -c "import pathlib,py_compile,os; ..."
   ```
2. 界面改动必须**实际渲染截图**核对，而不是凭代码推断：
   - `WA_DontShowOnScreen` + `windows` 平台可无窗口抓图；
   - 覆盖三套主题（`light` / `dark` / 皮肤）；
   - 覆盖空态与真实数据态。
3. 真实数据验证路径：
   - `ship_basic_info` 里按 `shiptype='Battleship'` + `group_status_key NOT IN ('disabled','unavailable')` 取 `ship_id`；
   - 发信号：`bus.folder_selected.emit("Ship")` → `bus.file_selected.emit("Ship", ship_id)`。
4. 主题往返切换（含角色配色）后，确认调色板、立绘预留位显隐、配置保存都正确，并恢复用户原配置。
5. 独立工具（模型查看器 / 资源浏览器 / 场景浏览器 / 版本比对 / 解包器 / 计算工具）改动后要逐个实例化冒烟。

---

## 6. 版式 PSD

`docs/ui/` 下有从代码渲染导出的分层 PSD（浅色 / 深色 / 角色主题各一份），图层名格式
`分区 / 元素  @token@`。用途与回填流程见 [docs/ui/README.md](docs/ui/README.md)。

配色或布局改动后重新导出：

```powershell
pip install psd-tools        # 仅生成 PSD 需要，不是运行依赖
.venv\Scripts\python.exe scripts\gen_ui_psd.py
```

⚠️ PSD 的**图层名必须是纯 ASCII**：psd-tools 用 macroman 写图层名，中文会直接抛
`UnicodeEncodeError`。中文说明请画进图层像素或写在文档里。
