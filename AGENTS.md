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

---

## 3. 版权红线

- **不内置任何官方美术素材**（游戏角色立绘、官方宣传图、同人图等）。
- **也不要自己绘制"看起来像"的替代品**去冒充官方立绘；界面里只用抽象的几何结构（网格、切角、细线轮廓）。
- 需要角色插画时由用户自行准备，且不纳入版本库。

---

## 4. 常见坑（踩过的）

| 坑 | 说明 |
|---|---|
| QSS 能力边界 | 不支持 `box-shadow` / `transition` / `transform` / `backdrop-filter` / `letter-spacing` |
| `QPen(col, w, cap=...)` | PySide6 非法，必须用 `QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)` |
| `WA_StyledBackground` | 纯 `QWidget` 子类必须设置，否则 QSS 的 `background-color` 静默不绘制 |
| 内联样式优先级 | `widget.setStyleSheet()` > `app.setStyleSheet()`；`QPalette.Highlight` 又压过 QSS 的 `::item:selected` |
| 父控件绘制会被子控件覆盖 | 装饰必须画在内容区之外的空带里，或退回背景层 |
| 切角是斜的 | 内容四角必须满足 `x + y >= 2*MARGIN + chamfer`，否则控件从切掉的角穿出；用 `SciFiPanel.content_margins()` |
| `apply_theme()` 不广播 | `main.apply_theme()` 单独调用不会发 `theme_changed`，自绘控件缓存会滞留旧色；只有 `application.set_theme_mode()` 会广播 |
| `compileall` 触发 qrc 重建 | `resources/__pycache__` 曾被打进资源包；`.pyc` 与缓存目录已在 qrc 生成脚本里排除 |
| 子进程约束 | spawn 下 worker 必须是模块级函数、参数可 pickle、子进程内无 Qt 事件循环；打包必须 `multiprocessing.freeze_support()` |
| Qt 对象被 GC | 冒烟脚本里窗口必须用列表持有引用，否则 C++ 析构可能崩溃（`0xC0000409`） |
| 中文乱码 | PowerShell 内联 here-string 经管道传给 Python 会变 `?`；复杂脚本写成 UTF-8 `.py` 文件再执行 |
| 启动闪小窗 | 自绘控件在 `__init__` 里对**还没有父控件**的自己调 `setVisible(True)`，会让它先变成一个独立的顶层窗口（12×12 闪一下）。构造期只在需要隐藏时 `setVisible(False)`，显示交给布局；给控件设显隐要放在 `layout.addWidget()` 之后 |

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
