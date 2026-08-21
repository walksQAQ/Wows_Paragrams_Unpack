"""从 Git Tag 生成 __about__.py（模板替换，保留全部元数据）。

用法（build.bat 在 Nuitka 打包前调用）：
    python scripts/gen_version.py

版本号识别顺序（**含 pre-release 版本号**）：
1. CI（GitHub Actions）中被 push 的 tag（GITHUB_REF_NAME，去掉 v 前缀）：
   打 release/pre-release tag 触发构建时，exe 版本严格等于正在发布的 tag，
   不依赖 master 状态，避免「同一 tag 重复 build 时版本随 master 漂移」；
2. HEAD 可达的最近 tag（本地打 tag 构建直接反映该 tag，含 -beta/-rc/-alpha 等）；
3. master 分支可达的最近 tag（HEAD 无 tag 时的兜底，反映主干最新发布）；
4. 均无 tag 时用 setuptools-scm 推导 dev 版本，最后保底 0.0.0-dev。

本项目历史 tag 形如 v3.2.2-fix / v3.2.2-test2（非 PEP 440），直接取 tag
名去前缀可保证版本串与 tag 完全一致；未来 -betaN 等 PEP 440 tag 同样适用。
"""
import os
import re
import subprocess

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 模板与输出（本项目 __about__.py 在根目录）
TEMPLATE_FILE = os.path.join(PROJECT_ROOT, "__about__.py.template")
ABOUT_FILE = os.path.join(PROJECT_ROOT, "__about__.py")


def _resolve_master_ref() -> str:
    """返回主干分支引用（master 优先，其次 main；本地或 origin 均可）。"""
    for ref in ("master", "origin/master", "main", "origin/main"):
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", ref],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                return ref
        except Exception:  # noqa: BLE001
            continue
    return ""


def _strip_v(tag: str) -> str:
    """去掉 tag 的 v/V 前缀（与 tag 命名保持一致）。"""
    return tag[1:] if tag[:1] in ("v", "V") else tag


def _describe_tag(ref: str) -> str | None:
    """取指定引用可达的最近 tag（去 v 前缀）；无 tag 返回 None。"""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", ref],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
        )
        tag = out.stdout.strip()
        if tag:
            return _strip_v(tag)
    except Exception:  # noqa: BLE001
        pass
    return None


def _scm_version() -> str | None:
    """setuptools-scm 推导（仅在无任何 tag 时作为 dev 版本兜底）。"""
    try:
        from setuptools_scm import get_version
        v = get_version(root=PROJECT_ROOT)
        if v and not v.startswith("0.0.0"):
            return v
    except Exception:  # noqa: BLE001
        pass
    return None


def _ci_ref_name() -> str | None:
    """CI（GitHub Actions）中被 push 的 tag（含 pre-release）；非版本样式 ref 忽略。"""
    ref = os.environ.get("GITHUB_REF_NAME", "").strip()
    if not ref:
        return None
    # 仅接受版本号样式（v3.2.3 / 3.2.3-beta1 等），排除分支名等杂散 ref
    if ref[:1] in ("v", "V") or re.match(r"^\d+\.\d+", ref):
        return ref
    return None


def generate_version():
    # 版本识别顺序（含 pre-release）：
    # 1) CI 中被 push 的 tag（GITHUB_REF_NAME）——最精确，build 版本严格等于发布 tag；
    # 2) HEAD 可达最近 tag（本地打 tag 构建直接反映，含 pre-release）；
    # 3) master 可达最近 tag（HEAD 无 tag 时兜底，反映主干最新发布）。
    ci_tag = _ci_ref_name()
    master_ref = _resolve_master_ref()
    version_str = (
        (_strip_v(ci_tag) if ci_tag else None)
        or _describe_tag("HEAD")
        or (_describe_tag(master_ref) if master_ref else None)
        or _scm_version()
        or "0.0.0-dev"
    )

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("{version}", version_str)
    with open(ABOUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Generated {ABOUT_FILE} with __version__ = '{version_str}'")


if __name__ == "__main__":
    generate_version()
