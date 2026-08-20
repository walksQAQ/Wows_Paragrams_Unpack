# 报错日志可见性修复 + 运行日志文件功能

> 状态：**待办（2026-08-21 立项）**
>
> 目标：
> 1. 把「报错 / 超出预期」的内容全部显示到日志区（`bus.log_message`），
>    包括被静默吞掉的异常与**被送进回退/兜底**的降级内容；
> 2. 追加「启动时把程序运行日志输出到 `log/` 下 `log-[程序启动时间].log`」功能。
>
> 日志区通道：`app/signals.py` `log_message` 信号 → `ui/main_window.py` `_on_log` → 日志面板。

---

## 一、审计结论摘要

全库 48 个文件约 295 处 `except`。用户可见路径上存在多类问题：

- **静默吞错**：`except ...: pass` / `except Exception:` 后不 emit 任何日志；
- **回退无提示**：失败后静默走 fallback（回退默认贴图 / 恒等矩阵 / 跳过文件），
  用户看到「缺失/降级」但不知原因；
- **抛错未进日志区**：异常被吞或被固定文案伪装成「没数据/没炮」；
- 少数已妥善处理（见第四节）。

---

## 二、高优先级问题（用户可见 / 数据正确性受影响）

### 2.1 3D 挂载模型读取/解析失败静默跳过（整组挂载消失）
- `services/geometry_service.py::_load_mount_model` ≈ L1402-1407：
  `read_file` 失败 `continue`、`parse_geometry` 抛 `GeometryError` 也 `continue`，无 warning；
- 消费端 `_load_mounts` ≈ L706-707 `if src is None: continue` 静默跳过。
- 影响：某炮塔/副炮/防空挂载在 3D 视图整组消失，日志区只说「挂载 N 个」，无「哪个挂载为何失败」。
- 修复：仿照船体分段 L524-530 既有模式，向 `geom.stats["warnings"]` 追加
  `"{path}: 读取失败/解析失败 {exc}"`。

### 2.2 主文件装甲（CM_PA_*.armor）读取/解析失败静默跳过
- `services/geometry_service.py` ≈ L622-634（main_entries 循环）：
  `except Exception: continue` / `except GeometryError: continue`，无 warning。
- 影响：船体装甲缺失，用户看不到原因。
- 修复：同上，追加 warnings。

### 2.3 渲染集/材质 DB 读取异常 → 整船静默回退默认贴图
- `services/geometry_service.py`：`_ship_render_sets` ≈ L1880-1900（`except: idx={}`）、
  `_shape_names_sdict` ≈ L1863-1868、`_resolve_material_full` ≈ L1799-1800、`_mfm_diffuse_base` ≈ L1662。
- 影响：整船/整挂载材质错误（默认灰贴图），无法区分「数据没入库」还是「解析失败」。
- 修复：DB 读失败/为空时向 warnings 追加「渲染集/材质数据缺失，已回退默认贴图」。

### 2.4 Root_BlendBone 回退恒等矩阵无提示
- `services/geometry_service.py::_mount_root_blend` ≈ L1050-1051：`except Exception: pass` 后回退 `np.eye(4)`。
- 影响：含非恒等 Root_BlendBone 的模型（防空/火控）朝向翻转，无解释。
- 修复：DB 读失败时向 warnings 追加降级原因。

### 2.5 split JSON 解析失败静默跳过（数据入库不完整）
- `services/analysis_service.py::precompute_all` ≈ L1776-1780：
  `except Exception: continue` 静默跳过损坏/编码异常的文件。
- 影响：该文件（某船/弹药/消耗品）不入库 → 详情显示「暂无数据」，N 与目录文件数对不上。
- 修复：记录 `(fp.stem, exc)` 并计数，batch 结束时若 `len(items) < len(fps)` 追加
  `⚠️ N 个文件解析失败未入库`。

### 2.6 3D 缓存 populate 解码失败静默 continue
- `services/assets_cache_service.py` ≈ L335-336 / L356-357 / L485-486 / L543-544。
- 影响：个别骨架/材质缺失 → 3D 对应部件或贴图缺失，仅总数可见。
- 修复：逐项失败追加计数与示例名日志。

### 2.7 贴图 DDS 解析失败 → 网格无贴图渲染
- `ui/geometry_renderer.py::_upload_texture` ≈ L187-190：`except Exception: return 0`。
- 影响：个别网格灰白/无贴图，用户以为渲染 bug。
- 修复：失败时向日志区输出贴图路径 + 异常。

### 2.8 list_ships 异常被吞 → 误导「请先加载数据」
- `services/geometry_service.py` ≈ L393-401：`except Exception: ships=[]` 后
  `_ships_error="数据库无可载入舰船（请先「加载数据」）"`。
- 影响：真实原因若是 DB 读失败/损坏，用户被引导去「加载数据」，误导。
- 修复：固定文案后追加真实异常 `: {exc}`（或单独 emit 日志）。

### 2.9 _geometry_folder_index 构建异常 → 空索引 → 全部「未找到几何文件」
- `services/geometry_service.py` ≈ L622-623。
- 修复：异常时向 warnings/日志区输出原因。

### 2.10 版本比对 _load_versions 异常 → 误导「暂无版本数据」
- `ui/version_diff_dialog.py` ≈ L295-296。
- 修复：保留真实异常提示（`⚠️ 版本列表加载失败: {exc}`）。

### 2.11 穿深计算器列表加载异常 → 误导「无可用火炮/舰船」
- `ui/penetration_calculator.py`：`_reload_guns` ≈ L1046、`_find_first_valid_ship_index` ≈ L1029。
- 修复：真实异常进日志区（计算主路径已有 `_set_error` ✓）。

### 2.12 详情面板舰长列表查询失败 → 空列表无提示
- `ui/detail_panel.py` ≈ L1060-1080（`except Exception: pass`）。
- 修复：异常时日志区提示。

### 2.13 射界安装朝向缺失 → 静默回退默认朝向
- `ui/firing_arc_dialog.py` ≈ L585-594。
- 修复：`get_skeleton_mounts` 失败/无数据时提示。

### 2.14 低优先级共性模式（可选）
- `presenters/base_presenter.py` / `ship_presenter.py` 字段级 `except: pass`：名称解析失败
  显示原始 key、弹药详情/弹道摘要整段静默缺失。
- `services/database_service.py::initialize` 迁移块 `except Exception: pass`（L169-555）。
- 修复：可加「调试级」日志，仅字段级缺失数量超阈值时提示一次，避免刷屏。

---

## 三、已妥善处理（无需修改）

| 位置 | 说明 |
|---|---|
| `ui/geometry_viewer.py` `_on_ship_loaded` | 把 `geom.stats["warnings"]` 逐条写入日志区 ✓ |
| `services/geometry_service.py` 船体分段解析失败 | 已追加 warnings ✓ |
| `services/geometry_service.py` `_load_mount_transforms` | 「未找到挂点骨架」已进 warnings ✓ |
| `services/extractor_service.py` / `processor_service.py` / `localization_service.py` | 错误均 emit 日志区 ✓ |
| `ui/penetration_calculator.py` 计算主路径 | `_set_error` 可见 ✓ |
| `ui/version_diff_dialog.py` 比对动作 | `_on_failed` 弹窗 ✓ |
| `ui/detail_panel.py` 自定义配置/射界/3D/构建 | 异常入日志区 ✓ |

---

## 四、修复优先级建议

1. **高 ROI（改动小、直接解决静默缺失）**：
   - 2.1、2.2：挂载模型 / 主文件装甲 `continue` → warnings 追加（对齐船体分段模式）；
   - 2.5：split JSON 失败计数 + batch 汇总日志；
   - 2.3、2.4：渲染集/材质/RootBlend 降级原因进 warnings。
2. **提示文案**：2.8、2.10、2.11 保留真实异常（固定文案后追加 `: {exc}`）。
3. **低优先级**：2.6、2.7、2.12、2.13、2.14。

---

## 五、追加功能：启动时运行日志输出到文件

### 5.1 目标

把程序运行日志（含日志区内容 + 异常/警告 + 启动信息）持久化到
`log/` 目录下、按 **`log-[程序启动时间].log`** 命名的文件，供排查/反馈使用。

> Windows 文件名不能含 `:` 等字符，实际文件名为
> `log-YYYYMMDD_HHMMSS.log`（如 `log-20260821_153200.log`），即「log-程序启动时间」。

### 5.2 文件与接入点

- 目录：`get_app_dir()/log/`（程序根目录旁，打包后为 exe 同级）。
- 启动时机：主程序 `main.py` 启动、主窗口显示后创建；每次启动新建一个文件。
- 内容：
  1. **会话头**：程序版本（`__about__.__version__`）、启动时间、服务器类型、游戏版本/bin_folder；
  2. **日志区全部消息**：监听 `bus.log_message`，把每条追加写入文件（复用 `_on_log` 同一回调即可）；
  3. **未处理异常**：`sys.excepthook` + `threading.excepthook` 捕获 → 写入文件 + 日志区；
  4. **关键错误**：各服务层 `bus.log_message` 已覆盖的内容自然落入文件。

### 5.3 实现要点

- 不引入新依赖：轻量实现（`pathlib` + 打开文件追加 + flush），或标准 `logging`
  （`FileHandler` + 同时 `StreamHandler` 到日志区）二选一；建议**监听 `bus.log_message` +
  `sys.excepthook`**，与现有信号总线一致、改动最小。
- 编码 `utf-8`；每次写入后 `flush()`（防崩溃丢失）；可选 `line buffering`。
- 文件命名用 `datetime.now().strftime("%Y%m%d_%H%M%S")`，避免冒号/非法字符。
- 异常 traceback 完整写入（含堆栈）。
- 启动旧日志保留（不覆盖），新会话新建文件；启动时按文件名时间戳排序，
  **只保留最近 30 个 `log-*.log`**，更旧的删除（即保留最近 30 次运行的记录）。
  删除在会话头写入后再执行，避免误删本次会话文件。
- 性能：写文件是追加文本，量小无压力；不阻塞主线程（日志消息本就少）。
- 敏感信息：日志可能含游戏路径，属用户本机信息，可接受；不输出凭据。

### 5.4 UI / 设置（可选）

- 设置页加「打开日志文件夹」按钮（`os.startfile(log_dir)` 或系统文件管理器）；
- Bug 报告提示：反馈时可附上 `log/log-*.log`（与 `.github/ISSUE_TEMPLATE/bug_report.yml`
  的「日志/截图」字段联动）。

### 5.5 验证

- 启动后 `log/` 生成 `log-<启动时间>.log`，含会话头 + 日志区消息；
- 启动超过 30 次后，`log/` 只保留最近 30 个日志文件，更旧的被清理；
- 触发一个已知异常（如加载损坏数据 / 未加载数据时操作）→ 文件含 traceback；
- 应用正常退出 / 崩溃后文件完整保留，可复读；
- 打包版（Nuitka onefile）在 exe 同级 `log/` 生成文件。

---

## 六、相关代码与文件

- `app/signals.py`：`bus.log_message` 日志通道。
- `main.py`：启动入口（建日志文件 + 会话头 + excepthook 注册）。
- `ui/main_window.py`：`_on_log`（日志区 + 写文件复用点）。
- `services/geometry_service.py` / `services/analysis_service.py` /
  `services/assets_cache_service.py`：第二、四节的静默吞错修复点。
- `.github/ISSUE_TEMPLATE/bug_report.yml`：可引导用户附上 `log/log-*.log`。
