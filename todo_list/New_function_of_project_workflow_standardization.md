# 项目流程规范化：版本管理 + 标准发布流（Gemini 建议整理）

> 状态：**已落地并验证（2026-08-21）**：本地流程 + GitHub Actions 自动 Release 均实测通过
> （测试 tag `v3.2.3-alpha1` → workflow success → Pre-release 自动创建）；剩余：未来打 beta 版 tag
> （来源：Gemini 建议，已按本项目实际适配）
>
> 目标：把"手动改版本号 + 网页手动发 Release"的松散流程，升级为
> **以 Git Tag 为唯一版本真理源、GitHub Actions 自动发 Release** 的规范流程。
>
> 关联文档：`todo_list/New_function_of_version_sync_check.md`（应用内版本同步检测，
> 依赖本流程产出的规范 Tag/Release 才能正确工作）。

---

## 一、现状与问题

| 现状 | 问题 |
|---|---|
| 版本号硬编码在 `__about__.py`（`__version__ = "3.2.2"`） | 发版需手动改代码，易漏改/与 Tag 不一致 |
| Release 在 GitHub 网页手动创建 | 无自动化，变更日志靠手写 |
| 无 `pyproject.toml` | 不符合现代 Python 项目规范，工具链无法读取元数据 |
| 打包用 `build.bat` + Nuitka onefile | 与发布流程脱节，产物需手动上传 |

---

## 二、方案选择（用户已确认：方案 B）

### 方案 B：现代动态版本流（主推，用户已确认）

用 `pyproject.toml` + setuptools-scm 从 **Git Tag 动态生成版本号**，
代码里不再手写 `__version__` 常量。以 Tag 为唯一版本真理源，发版 = 打 Tag。

**Nuitka 兼容方案（关键）**：Nuitka onefile 打包后 `importlib.metadata` 读不到
已安装包元数据，运行时动态读版本会回退 `0.0.0-dev`。因此方案 B 采用
**"构建时生成版本文件"**：在 `build.bat` 打包前用 setuptools-scm 从 Git 读取
版本号，写入 `__about__.py`（生成物），Nuitka 打包的是**具体字符串**，
运行时不依赖 `importlib.metadata`。既满足"不手改版本号"，又保证 Nuitka 正确。

### 方案 A：轻量标准流（降为备选）

保留 Nuitka + build.bat，把 Git Tag 作为版本真理源，但版本号仍在 `__about__.py`
手写维护。仅当方案 B 在打包链路落地遇阻时回退使用。

---

## 三、方案 B 实施步骤

### 3.1 目录结构规范化

Gemini 建议的标准结构（**本项目部分适用**）：

```
my_project/
├── my_package/          # 主包目录
│   ├── __init__.py      # 定义 __version__
│   └── main.py
├── tests/               # 测试代码
├── pyproject.toml       # 项目元数据（动态版本）
├── .gitignore
└── README.md
```

**本项目适配**：代码已按 `app/ models/ services/ ui/ utils/` 分层，**不做大规模
目录搬迁**（风险高、收益低）；仅补充缺失的规范文件：

- [x] 新建 `pyproject.toml`（见 3.2，含 `setuptools-scm` 动态版本配置）
- [x] 确认 `.gitignore` 覆盖 `__pycache__/`、`release/`、`data/`、`.venv/`、`_temp/`
- [ ] `tests/` 目录：暂不强制，后续把 `_temp/scripts/` 中稳定的探针迁移为正式测试

### 3.2 pyproject.toml + setuptools-scm 动态版本

```toml
[build-system]
requires = ["setuptools>=61", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "wows-paragrams-unpack"
dynamic = ["version"]
description = "World of Warships / Mir Korabli 游戏数据分析工具"
readme = "README.md"
license = { file = "LICENSE" }
authors = [{ name = "walksQAQ" }]
requires-python = ">=3.10"

[tool.setuptools.packages.find]
include = ["app*", "models*", "services*", "ui*", "utils*", "data_extractor*", "presenters*", "uncode_assets*"]

[tool.setuptools_scm]
version_scheme = "guess-next-dev"
local_scheme = "no-local-version"
```

- [x] 新建 `pyproject.toml`（如上；license 实际指向 `LICENSE.Apache-2.0`）
- [x] 安装构建依赖：`pip install setuptools-scm`（10.2.1，已加入 requirements.txt）
- [x] 验证：setuptools-scm 10.2.1 可运行；⚠️ 当前 HEAD 最近 tag `v3.2.2-test2` 非 PEP 440，
      由 `gen_version.py` 的 git 回退兜底（见 3.3.2 实际实现）；未来 `-betaN` tag 可被原生解析

### 3.3 构建时生成版本文件（Nuitka 兼容核心，Gemini 细化版）

> 本项目 `__about__.py` 位于**项目根目录**（非 `app/`），且除 `__version__` 外还含
> `__license__` / `__license_detail__` / `__copyright__` 等字段。因此**不能**像 Gemini
> 示例那样整体覆盖文件（会丢失其他元数据），改为**模板替换**：保留
> `__about__.py.template`（含全部元数据，`__version__` 占位），脚本仅替换版本行。

#### 3.3.1 版本模板

- [x] 新建 `__about__.py.template`：复制当前 `__about__.py` 全部字段，
      其中版本行写 `__version__ = "{version}"` 占位
- [x] 仓库内**不再提交** `__about__.py`（已 `git rm --cached`，保留磁盘文件）

#### 3.3.2 scripts/gen_version.py 实现

```python
import os
from setuptools_scm import get_version

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 模板与输出（本项目 __about__.py 在根目录）
TEMPLATE_FILE = os.path.join(PROJECT_ROOT, "__about__.py.template")
ABOUT_FILE = os.path.join(PROJECT_ROOT, "__about__.py")


def generate_version():
    try:
        # 从 Git 标签动态获取版本号；本地无 Tag 时用 fallback 保底
        version_str = get_version(root=PROJECT_ROOT, fallback_version="0.0.0-dev")
    except Exception as e:  # noqa: BLE001
        print(f"[Warning] Failed to get version from setuptools_scm: {e}")
        version_str = "0.0.0-dev"

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("{version}", version_str)
    with open(ABOUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Generated {ABOUT_FILE} with __version__ = '{version_str}'")


if __name__ == "__main__":
    generate_version()
```

- [x] 新增 `scripts/gen_version.py`（模板替换；**版本强制同步自 master**：
      优先取 master（或 origin/master / main）可达的最近 tag 去 v 前缀，
      而非当前分支 HEAD——避免特性分支上的杂散 tag 污染版本号；
      master 引用不存在时回退 HEAD tag，再无则 setuptools-scm / 0.0.0-dev。
      实测：在 new-function-dev 分支构建，版本正确取 master 的 3.2.2-fix1
      而非本分支的 3.2.2-test2）

#### 3.3.3 build.bat 集成

在 Nuitka 打包命令**之前**追加版本生成调用：

```bat
:: ── 步骤 1.5: 从 Git Tag 生成版本文件（Nuitka 编译前） ──
echo [VERSION] 从 Git Tag 生成 __about__.py ...
%PYTHON% scripts/gen_version.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] 生成版本文件失败，中止打包。
    pause
    exit /b %ERRORLEVEL%
)
```

- [x] `build.bat` 在 Nuitka 前插入上述步骤（QRC 之后、`nuitka` 之前，已验证生效）

#### 3.3.4 .gitignore 补充

- [x] `.gitignore` 加入 `__about__.py`（生成物，避免本地版本频繁变更污染 git status）
- [x] 确认 `__about__.py.template` **不被**忽略（需入库）
- [x] 可选：`git update-index --assume-unchanged __about__.py` 已不再需要
      （既然模板方案已让该文件不入库）

#### 3.3.5 验证

- [x] 打包后的 exe 中 `__about__.__version__` 是具体字符串（实测 `3.2.2-test2`，
      由 git 回退推导），而非 `0.0.0-dev`
- [x] `__about__.__license__` / `__license_detail__` 等元数据在打包后仍完整保留
      （实测导入正常，license_detail 782 字符含 Apache/GPLv3 全文引用）
- [ ] 无 Git Tag 的本地仓库打 `build.bat` 时回退到 `0.0.0-dev` 且不报错（未实测，逻辑已覆盖）

### 3.4 Tag 驱动的发布流

规范流程（替代网页手动发 Release）：

```bash
# 1. 修改代码并提交（无需手改版本号）
git add .
git commit -m "feat: xxx"

# 2. 打 Tag 并推送（Tag 即版本）
git tag v3.2.2
git push origin main --tags
```

- [ ] 版本号语义约定（**PEP 440**）：`vX.Y.Z` 正式版；预发布用 `-betaN` / `-rcN` / `-aN`
      （如 `v3.2.3-beta1` → setuptools-scm 解析为 `3.2.3b1`）。
      **弃用** `-test` / `-fix` / `-bugfix` 后缀——非 PEP 440，setuptools-scm 无法解析；
      未来测试版本一律改用 `-betaN`。存量旧 tag 由 `gen_version.py` 的 git 回退兜底，不影响打包。
- [x] **tag 强制同步自 master**：版本号一律取 master 可达的最近 tag（`gen_version.py`
      已实现）；GitHub Actions 建 Release 前校验 tag 必须在 master 上（`release.yml`
      已加 `merge-base --is-ancestor` 校验）。在特性分支打 tag 会被拒绝/忽略。
- [ ] 不再在 GitHub 网页手动创建 Release
- [ ] 发版即打 Tag，版本号由 setuptools-scm 从 Tag 推导，杜绝"代码版本与 Tag 不一致"

### 3.5 GitHub Actions 自动发 Release

新建 `.github/workflows/release.yml`：

```yaml
name: Create Release on Tag Push

on:
  push:
    tags:
      - 'v*'  # 匹配 v3.2.3-beta1, v1.0.0 等

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          name: Release ${{ github.ref_name }}
          generate_release_notes: true  # 自动生成 Commit 变更日志
          prerelease: ${{ contains(github.ref_name, '-') }}  # 带后缀自动设为 Pre-release
```

- [x] 创建 `.github/workflows/release.yml`（含 **tag 必须在 master 上**的校验：
      `git merge-base --is-ancestor <tag> origin/master`，不在则拒绝建 Release）
- [x] 验证：推送一个测试 Tag，确认自动创建 Release 且 pre-release 判定正确
      （2026-08-21 实测：`v3.2.3-alpha1` 推送后 workflow `Create Release on Tag Push`
      conclusion=success，自动创建 `Release v3.2.3-alpha1` 且 `prerelease=True`，
      tag 在 master 上的校验步骤通过）
- [ ] （可选增强）在 workflow 中用 Windows runner 跑 `build.bat` 自动打包 exe 并作为 Release 附件上传

### 3.6 发布流程串联回顾（完整工作流）

> **分支纪律（多人协作 / 标准 Git Flow）**：代码在 `dev` 或特性分支开发，
> **必须先进主干**再打 Tag 发版。若直接在未合并的分支打 Tag，会导致
> Release 对应代码落后于主干，或 Tag 指向错误分支。因此 Tag 一律打在
> `master`（或 `main`）上。

标准发布完整工作流：

1. **合并到主干**：所有新功能与修复测试完毕后，合并推送到 `master`。
2. **切换到主干并拉取最新**：
   ```bash
   git checkout master
   git pull origin master
   ```
3. **在主干上打 Tag 并推送**：
   ```bash
   git tag v3.2.3-beta1
   git push origin master --tags
   ```
4. **触发自动化与本地打包**：
   - GitHub Actions 监听到 `master` 上的新 Tag，自动在云端创建
     对应 Release / Pre-release（带 `-` 后缀自动标记 Pre-release）。
   - 随后在本地 `master` 分支运行 `build.bat`：`gen_version.py` 此时由
     setuptools-scm 准确读取当前 `v3.2.3-beta1` 标签写入 `__about__.py`
     （解析为 `3.2.3b1`），Nuitka 把最新主干代码 + 正确版本号打包成 exe。

> 日常开发则在特性分支随意 commit，不用管版本号（`__about__.py` 是生成物，
> 不入库）；只有上述第 2~4 步（主干 + Tag + 构建）才涉及版本号。

---

## 四、与现有功能的衔接

1. **版本同步检测**（`New_function_of_version_sync_check.md`）：
   本流程产出的规范 Tag/Release（含 prerelease 标记）是该功能正确识别
   pre-release 的前提；两者应一起落地。动态版本从 Tag 推导，天然与 Release 一致。
2. **关于对话框**：`__about__.__version__` 显示构建时生成的具体版本，逻辑不变；
   `__license__` / `__license_detail__` 由模板保留，不因版本生成而丢失。
3. **Nuitka 打包**：`build.bat` 新增"生成版本文件"步骤；版本注入仍走 `__about__.py`
   （但由脚本从模板生成，不再手写）。

---

## 五、风险与注意

1. **不做目录大搬迁**：Gemini 建议的"代码移入主包文件夹"对本项目改动过大，
   现有分层结构已足够清晰，仅补规范文件。
2. **Nuitka 下必须在构建时注入版本**：运行时 `importlib.metadata` 在 onefile 中
   不可用；`scripts/gen_version.py` 是方案 B 能用于本项目的关键，务必在 build.bat
   中正确调用并验证打包产物版本。
3. **无 Tag 时的版本回退**：setuptools-scm 在无 Tag 仓库上会推导出 dev 版本
   （如 `0.0.1.dev0`）；`gen_version.py` 用 `fallback_version="0.0.0-dev"` 保底，
   不中断打包。
4. **模板替换而非整体覆盖**：`__about__.py` 含 license 等多字段，`gen_version.py`
   必须基于 `__about__.py.template` 只替换版本行，否则打包后关于对话框的
   许可证信息会丢失（Gemini 示例只写 `__version__` 的写法不适用于本项目）。
5. **GitHub Actions 网络**：若仓库推送/Actions 受限，自动 Release 会失败，
   需保留手动发 Release 作为降级手段。

---

## 六、配套改动：程序名/产物名统一（WowsAnalyzer.exe → KorabliParagrams.exe）

> 状态：**待办（2026-08-21 加入）**
> 用户已确认：exe 文件名改为 `KorabliParagrams.exe`；
> `__about__.__title__`（任务栏/窗口标题/关于对话框显示名）**保持不变**。

### 6.1 现状

`WowsAnalyzer.exe` 是 Nuitka 打包产物名，全库仅出现在 `build.bat` 的 **3 处**（已全库
grep 确认，README / config.json / 代码均无引用）：

| 行 | 内容 | 作用 |
|---|---|---|
| L16 | `taskkill /f /im WowsAnalyzer.exe` | 打包前强制结束旧进程（防文件锁） |
| L22 | `del /f /q "%OUTDIR%\WowsAnalyzer.exe"` | 清理旧产物 |
| L59 | `--output-filename=WowsAnalyzer.exe` | Nuitka 产物名（**唯一事实源**） |

显示名与文件名**分离**：`__about__.__title__ = "Wows/Korabli Paragrams Unpack"`
（`main.py` L157 用作 `setApplicationName`）只影响任务栏/窗口标题/关于对话框，
与 exe 文件名解耦，本次不改。

### 6.2 改动清单

- [x] `build.bat` 三处 `WowsAnalyzer.exe` → `KorabliParagrams.exe`
- [x] 确认 `config.json` 部署逻辑不依赖旧名（复制到 `%OUTDIR%\config.json`，无需改）
- [x] 清理 `release/` 下旧产物（`WowsAnalyzer.exe` 及 `main.build/`、`main.dist/`、
      `main.onefile-build/` 中间目录）
- [x] 验证：`.\build.bat` 产出 `release/KorabliParagrams.exe`（55.6 MB），启动冒烟测试通过

### 6.3 与发布流的衔接

- [ ] 3.5 可选增强（Windows runner 自动打包 exe 并作为 Release 附件上传）落地时，
      附件名 = `KorabliParagrams.exe`
- [ ] README 下载/使用说明若日后提及 exe 名，一并更新（当前未引用，无需改）

### 6.4 不改动项

- `__about__.__title__` 保持 "Wows/Korabli Paragrams Unpack"（显示名）
- 仓库名 `Wows_Paragrams_Unpack`、3.2 拟定的 `pyproject.toml` `name` 字段
  （`wows-paragrams-unpack`）与 exe 文件名解耦，本次不改
