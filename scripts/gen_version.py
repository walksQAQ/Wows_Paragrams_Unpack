"""从 Git Tag 生成 __about__.py（模板替换，保留全部元数据）。

用法（build.bat 在 Nuitka 打包前调用）：
    python scripts/gen_version.py

版本号推导顺序：
1. setuptools-scm（若 tag 为合法 PEP 440 版本，如 v3.2.2 / v3.2.2rc1）；
2. 回退：读取最近的 git tag 并去掉 `v` 前缀（本项目历史 tag 形如
   v3.2.2-fix / v3.2.2-test2，非 PEP 440，setuptools-scm 无法解析，
   此回退保证版本串与 tag 完全一致）；
3. 均失败时用 0.0.0-dev 保底，不中断打包。
"""
import os
import subprocess

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 模板与输出（本项目 __about__.py 在根目录）
TEMPLATE_FILE = os.path.join(PROJECT_ROOT, "__about__.py.template")
ABOUT_FILE = os.path.join(PROJECT_ROOT, "__about__.py")


def _scm_version() -> str | None:
    """优先用 setuptools-scm 从 Git Tag 推导（要求 tag 为合法 PEP 440）。"""
    try:
        from setuptools_scm import get_version
        v = get_version(root=PROJECT_ROOT)
        if v and not v.startswith("0.0.0"):
            return v
    except Exception:  # noqa: BLE001  非 PEP440 tag / 无 git 等
        pass
    return None


def _git_tag_version() -> str | None:
    """回退：取最近可达 tag，去掉 v/V 前缀（与 tag 命名保持一致）。"""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
        )
        tag = out.stdout.strip()
        if tag:
            return tag[1:] if tag[:1] in ("v", "V") else tag
    except Exception:  # noqa: BLE001
        pass
    return None


def generate_version():
    version_str = _scm_version() or _git_tag_version() or "0.0.0-dev"

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("{version}", version_str)
    with open(ABOUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Generated {ABOUT_FILE} with __version__ = '{version_str}'")


if __name__ == "__main__":
    generate_version()
