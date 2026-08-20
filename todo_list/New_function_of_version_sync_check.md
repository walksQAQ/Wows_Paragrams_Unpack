# 新功能：应用内实时检测与 GitHub 最新版本是否同步（含 pre-release 识别）

## 目标

应用内检测本地版本（`__about__.__version__`，当前 3.2.2）与 GitHub 仓库
`walksQAQ/Wows_Paragrams_Unpack` 的最新版本是否同步，并在有新版本时提示用户。

核心要求：**必须能识别 pre-release 版本**，不能只依赖 GitHub 的 `latest` 端点
（它会排除 pre-release），需要在检测逻辑中自行筛选和比较 release。

## 需求细节

1. 启动后自动检测（不阻塞 UI，静默降级），也可手动触发"检查更新"。
2. 能区分三种结果：
   - 本地版本 == 远程最新正式版（同步）；
   - 本地版本落后于远程最新正式版（有新正式版）；
   - 远程存在更高的 pre-release（提示可选"包含预发布"查看）。
3. 用户可配置：是否自动检查、是否把 pre-release 视为可更新版本、是否忽略某个版本。
4. 网络失败/超时/被墙时静默失败，不影响应用其他功能，记日志并给出"检查失败"状态。
5. 不反复请求 GitHub API（匿名限速约 60 次/小时）：缓存最近一次结果与时间戳。

## GitHub API 方案

### 为什么不能用 /releases/latest

`GET /repos/{owner}/{repo}/releases/latest` 只返回最新**非 pre-release** release；
当仓库最近发布的是 pre-release 时，该端点会退回上一个正式版，甚至可能 404
（全部是 pre-release 时）。因此**必须**用列表接口自行比较。

### 推荐接口

```
GET https://api.github.com/repos/walksQAQ/Wows_Paragrams_Unpack/releases?per_page=100
Accept: application/vnd.github+json
User-Agent: WowsParagramsUnpack/<本地版本>
```

- 拉取全部（或足够多）release；
- 过滤 `draft=true`；
- 每个 release 读取 `tag_name`、`prerelease`（bool）、`published_at`、
  `html_url`、`name`、`body`（更新说明，可选展示）；
- `tag_name` 通常形如 `v3.2.2` 或 `3.2.2`，或含预发布后缀如 `3.2.3-rc.1`。

### 可选兜底

- 若列表接口超时，可回退 `https://api.github.com/repos/.../releases/latest`
  作为"最新正式版"的只读参考，但不要把它的结果当作"包含 pre-release 的最新"。

## 版本比较算法（轻量 semver）

不引入新依赖（`packaging` 会增大 onefile 体积），在项目内实现一个小型比较器：

1. 去掉 `tag_name` 前缀 `v`/`V`；
2. 拆分为 `主.次.修订` 三段数字 + 可选 pre-release 标识（`-alpha`/`-beta`/`-rc`/`-pre` 或
   `-rc.1` 等）；
3. 比较规则：
   - 先比 major，再比 minor，再比 patch；
   - 数字相等时：无 pre-release 后缀 > 有 pre-release 后缀；
   - 本项目实际使用的 pre-release 后缀仅 `-test`（测试版）与 `-fix`（修复版），
     不采用 `-rc` / `-alpha` / `-beta`；
   - 语义层级（从最不稳定到最稳定）：`test` < `fix` < 正式发布（无后缀）；
     - `3.2.2-test1` = 测试版；
     - `3.2.2-fix1` = 修复版；
   - 同级标识（如 `test1` vs `test2`、`fix1` vs `fix2`）按数字后缀逐段比较；
   - 本地 `__about__.__version__` 与远程 tag 一样允许以上后缀，比较器
     必须用同一套规则解析，不能假设本地版本只有纯数字三段式；
   - 注：若 `-fixN` 表示「同主版本正式版发布后的修复补丁」（如 `3.2.2`
     已发布，再出 `3.2.2-fix1` 并视为比 `3.2.2` 更新），则按标准语义会
     误判为旧版本；实现时应把这类 `fix` 单独识别为「高于同号正式版」，
     或在配置中明确该约定后再参与比较，避免误报"已同步"；
   - 其余未知标识（如第三方 tag 带 `-rc` / `-alpha` 等）按"未稳定发布"
     处理，标识间按字典序稳定比较，避免比较出错；但**不作为本项目发布的
     主流程标识**；
   - 无法解析的 tag 跳过并记 warning，不参与比较。
4. 输入本地版本 `__about__.__version__` 与远程 tag，输出：
   - 是否同步；
   - 最新正式版 tag / 版本号；
   - 最新 pre-release tag / 版本号（存在时）；
   - 各自 release 页 URL。

## 服务设计

新增 `services/update_service.py`（参考 `localization_service.py` 的网络写法）：

- `UpdateService.check(session=None, timeout=8) -> UpdateCheckResult`（同步函数，供后台线程调用）；
- 复用现有网络范式：
  ```python
  import requests, urllib.request
  proxies = urllib.request.getproxies()
  r = requests.get(url, headers=headers, timeout=timeout, proxies=proxies)
  ```
- 返回 dataclass：`current`, `latest_release`, `latest_prerelease`, `is_synced`,
  `has_new_release`, `has_new_prerelease`, `release_url`, `prerelease_url`,
  `checked_at`, `error`；
- 结果本地缓存（见下）；多次调用命中缓存不重复请求；
- 纯服务层不依赖 Qt 控件，由 UI 层用 `run_async` 后台执行并在主线程更新界面。

## 缓存、限速与忽略

- 用 `QSettings("walksQAQ", "WowsParagrams")` 或 `data/` 下小文件缓存
  `last_check_time` + `last_result_json`；
- 自动检查间隔建议 >= 24h，未到间隔则直接读缓存展示；
- 手动"检查更新"忽略缓存强制刷新；
- 记录用户忽略的版本号集合（`ignored_versions`），忽略后不再提示该版本；
- 设置变更（自动检查开关、包含预发布开关）实时生效。

## UI 集成点

- **状态栏/工具栏**：加"版本检查"入口；未检测时显示"检查更新..."，检测后显示
  "当前 v3.2.2（最新）" 或 "发现新版本 v3.3.0"；
- **启动自动检测**：主窗口显示后延迟触发（`QTimer.singleShot` 约 1s），避免拖慢启动；
- **新版本提示**：非侵入提示条或弹窗，按钮含"前往 GitHub"（打开 `html_url`）、
  "忽略此版本"、"稍后"；
- **设置面板**：新增"自动检查更新"复选框、"包含预发布版本"复选框；可在
  `ui/advanced_settings.py` 或对应设置页接入；
- **信号**：`app/signals.py` 增加 `update_check_done = Signal(object)`，
  后台线程结果经 `run_async` 回调回到主线程后 emit；
- 采用与现有窗口一致的主题绑定（`theme.bind`）与日志输出（`bus.log_message`）。

## 建议实现步骤

1. 实现 `services/update_service.py`：请求 + 解析 + semver 比较 + 缓存；
2. 用一次性探针（放 `_temp/scripts/`）实际请求该仓库 releases，验证
   API 返回、`tag_name`/`prerelease` 字段与网络代理环境（国内网络需能访问 GitHub API，
   必要时增加镜像/备用源）；
3. 在 `app/signals.py` 加信号；
4. 接入主窗口状态栏/工具栏 + 启动延迟自动检测；
5. 新增设置项（自动检查、包含预发布、忽略版本列表）；
6. 手动"检查更新"与结果展示/跳转；
7. 打包验证。

## 验证计划

### 探针/自动化

- 真实请求 `walksQAQ/Wows_Paragrams_Unpack/releases`，确认能区分正式版与
  pre-release，比较结果与手工核对一致；
- 构造测试 tag 集（含 `v` 前缀、`-test1`、`-fix1`、无后缀）单测 semver 比较器；
- 断网/超时/HTTP 4xx 时返回 `error` 且不崩溃、不弹错误窗；
- 缓存命中时不发网络请求（可临时禁用网络验证）；
- 忽略版本后不再提示。

### 手工验收

- 启动后约 1s 自动检测，状态栏显示结果；
- 手动"检查更新"立即刷新；
- 有新版时提示条可见、可跳转 GitHub、可忽略；
- 开启"包含预发布"后能提示仅存在于 pre-release 的更高版本；
- 打包版（Nuitka onefile）中检测可用，https 证书正常（`certifi` 需被打包），
  代理环境可用。

## 相关代码与文件

- `__about__.py`：本地版本来源（`__version__`，仓库 `__url__`）；
- `services/localization_service.py`：网络请求 + 代理 + 超时的既有范式（参考）；
- `utils/threading_utils.py`：后台线程执行检查（注意其目前无取消协议，检查有
  超时兜底，问题可控；可复用审计计划中的 run_async 改造）；
- `app/signals.py`：新增更新检查完成信号；
- `ui/main_window.py` / `ui/toolbar_widget.py`：状态栏/工具栏与启动检测接入点；
- `ui/advanced_settings.py`：设置项接入；
- `requirements.txt`：`requests>=2.28` 已有，无需新增依赖（打包需确认 certifi）。
