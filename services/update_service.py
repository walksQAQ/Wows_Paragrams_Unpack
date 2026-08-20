"""
update_service.py —— GitHub 版本同步检测服务。

检测本地版本（__about__.__version__）与 GitHub 仓库
walksQAQ/Wows_Paragrams_Unpack 的最新 release 是否同步。

设计要点（见 todo_list/New_function_of_version_sync_check.md）：
- 使用 releases 列表接口（/releases/latest 会排除 pre-release，不可用）；
- 内置轻量 semver 比较器（不引入 packaging 依赖）；
- 本项目 pre-release 语义：test < fix < 正式版（fix 高于同号正式版）；
- 结果缓存（data/update_check.json），自动检查间隔 >= 24h；
- 网络失败/超时静默降级，返回 error 字段，不抛异常、不弹错误窗；
- 纯服务层不依赖 Qt 控件，由 UI 层用 run_async 后台执行。
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests

from app.signals import bus
from utils.path_utils import get_data_dir

GITHUB_REPO = "walksQAQ/Wows_Paragrams_Unpack"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=100"
CACHE_FILE_NAME = "update_check.json"
#: 自动检查最小间隔（秒）：24 小时
AUTO_CHECK_INTERVAL = 24 * 3600

# ── pre-release 标识语义层级（本项目约定） ──────────────
# test < 正式版 < fix。fix 视为「同号正式版发布后的修复补丁」，
# 高于同号正式版（3.2.2-fix1 > 3.2.2），否则会误报"已同步"。
_PRERELEASE_RANK = {"test": 0, "fix": 2}
#: 正式版（无后缀）的层级
_RELEASE_RANK = 1


@dataclass
class ParsedVersion:
    """解析后的版本号：(major, minor, patch, pre_kind, pre_num)。

    pre_kind: None=正式版, "test"/"fix"/其他字符串=预发布标识
    pre_num:  预发布数字后缀（如 test1 → 1），无数字为 0
    """
    major: int = 0
    minor: int = 0
    patch: int = 0
    pre_kind: str | None = None
    pre_num: int = 0
    raw: str = ""
    valid: bool = False


@dataclass
class ReleaseInfo:
    """单个 GitHub release 的关键信息。"""
    tag: str = ""
    version: str = ""          # 去 v 前缀后的版本串
    prerelease: bool = False
    name: str = ""
    html_url: str = ""
    published_at: str = ""
    parsed: ParsedVersion | None = None


@dataclass
class UpdateCheckResult:
    """版本检测结果。"""
    current: str = ""
    latest_release: str = ""       # 最新正式版 tag
    latest_prerelease: str = ""    # 最新 pre-release tag（存在时）
    is_synced: bool = False        # 本地 == 最新正式版
    has_new_release: bool = False  # 存在比本地新的正式版
    has_new_prerelease: bool = False  # 存在比本地新的 pre-release
    release_url: str = ""
    prerelease_url: str = ""
    checked_at: float = 0.0
    error: str = ""
    ignored_versions: list = field(default_factory=list)


# ── 版本解析与比较 ──────────────────────────────────────

_VER_RE = re.compile(
    r"^(\d+)\.(\d+)(?:\.(\d+))?"     # major.minor[.patch]（两段式 tag patch 缺省 0）
    r"(?:[-.]?([A-Za-z]+)[-.]?(\d*))?"  # 可选 pre-release 标识 + 可选数字
    r"(?:[-.+].*)?$"                 # 容忍其余后缀（dev 等）
)


def parse_version(text: str) -> ParsedVersion:
    """解析版本串（容忍 v/V 前缀、两段式与 dev 后缀）。无法解析返回 valid=False。"""
    if not text:
        return ParsedVersion(raw=text)
    s = text.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    m = _VER_RE.match(s)
    if not m:
        return ParsedVersion(raw=text)
    major, minor = int(m.group(1)), int(m.group(2))
    patch = int(m.group(3)) if m.group(3) else 0
    pre_kind = (m.group(4) or "").lower() or None
    pre_num = int(m.group(5)) if m.group(5) else 0
    return ParsedVersion(major, minor, patch, pre_kind, pre_num,
                         raw=text, valid=True)


def _rank(p: ParsedVersion) -> int:
    """返回版本层级：test=0, fix=1, 正式版=2。未知标识按 0（最不稳定）。"""
    if p.pre_kind is None:
        return _RELEASE_RANK
    return _PRERELEASE_RANK.get(p.pre_kind, 0)


def compare_versions(a: ParsedVersion, b: ParsedVersion) -> int:
    """比较两个版本，返回 -1/0/1（a<b / a==b / a>b）。

    规则：
    1. 先比 major/minor/patch；
    2. 三段相等时比层级：fix(2) > 正式版(1) > test(0) > 未知标识(0)；
       —— fix 高于同号正式版（本项目约定：fix 是正式版后的修复补丁）；
    3. 同层级比数字后缀（test1 < test2）；
    4. 未知标识之间按字典序稳定比较。
    """
    if not a.valid or not b.valid:
        return 0
    for x, y in ((a.major, b.major), (a.minor, b.minor), (a.patch, b.patch)):
        if x != y:
            return -1 if x < y else 1
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    # 同层级：正式版无数字后缀，直接相等
    if a.pre_kind is None and b.pre_kind is None:
        return 0
    # 未知标识之间按字典序
    if ra == 0 and a.pre_kind not in _PRERELEASE_RANK \
            and b.pre_kind not in _PRERELEASE_RANK and a.pre_kind != b.pre_kind:
        return -1 if (a.pre_kind or "") < (b.pre_kind or "") else 1
    if a.pre_num != b.pre_num:
        return -1 if a.pre_num < b.pre_num else 1
    return 0


# ── 缓存读写 ────────────────────────────────────────────

def _cache_path() -> Path:
    return get_data_dir() / CACHE_FILE_NAME


def load_cache() -> dict:
    """读取上次检测结果缓存；不存在/损坏返回 {}。"""
    try:
        p = _cache_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {}


def save_cache(result: UpdateCheckResult, ignored: list | None = None) -> None:
    """保存检测结果与忽略版本列表到缓存。"""
    try:
        data = asdict(result)
        data["ignored_versions"] = ignored if ignored is not None else result.ignored_versions
        _cache_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        bus.log_message.emit(f"⚠️ 版本检测缓存写入失败: {e}")


def load_ignored_versions() -> list:
    """读取用户忽略的版本号列表。"""
    return load_cache().get("ignored_versions", []) or []


def save_ignored_versions(versions: list) -> None:
    """单独更新忽略版本列表（保留其余缓存）。"""
    data = load_cache()
    data["ignored_versions"] = versions
    try:
        _cache_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


# ── 核心检测 ────────────────────────────────────────────

def _fetch_releases(timeout: float = 8.0) -> list[dict]:
    """请求 GitHub releases 列表（带系统代理）。失败抛异常由调用方捕获。"""
    import __about__
    proxies = urllib.request.getproxies()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"WowsParagramsUnpack/{__about__.__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.get(RELEASES_API, headers=headers, timeout=timeout, proxies=proxies)
    r.raise_for_status()
    return r.json()


def check(force: bool = False, include_prerelease: bool = True,
          timeout: float = 8.0) -> UpdateCheckResult:
    """执行版本检测（同步函数，供后台线程调用）。

    - force=False 且缓存未过期（< 24h）时直接返回缓存；
    - 网络失败返回带 error 的结果，不抛异常。
    """
    import __about__
    current = __about__.__version__
    ignored = load_ignored_versions()

    # 缓存命中（未过期且非强制）
    if not force:
        cached = load_cache()
        if cached and cached.get("checked_at"):
            age = time.time() - cached.get("checked_at", 0)
            if age < AUTO_CHECK_INTERVAL and not cached.get("error"):
                try:
                    res = UpdateCheckResult(**{
                        k: cached[k] for k in UpdateCheckResult.__dataclass_fields__
                        if k in cached})
                    res.ignored_versions = ignored
                    return res
                except Exception:  # noqa: BLE001
                    pass

    result = UpdateCheckResult(current=current, checked_at=time.time(),
                               ignored_versions=ignored)
    try:
        releases = _fetch_releases(timeout)
    except Exception as e:  # noqa: BLE001
        result.error = f"{type(e).__name__}: {e}"
        bus.log_message.emit(f"⚠️ 版本检测失败: {result.error}")
        save_cache(result, ignored)
        return result

    # 过滤 draft，解析版本
    infos: list[ReleaseInfo] = []
    skipped: list[str] = []
    for rel in releases:
        if rel.get("draft"):
            continue
        tag = rel.get("tag_name") or ""
        parsed = parse_version(tag)
        if not parsed.valid:
            skipped.append(tag)
            continue
        infos.append(ReleaseInfo(
            tag=tag, version=parsed.raw.lstrip("vV"),
            prerelease=bool(rel.get("prerelease")),
            name=rel.get("name") or "", html_url=rel.get("html_url") or "",
            published_at=rel.get("published_at") or "", parsed=parsed))
    if skipped:
        # 汇总为一条日志，避免早期遗留 tag 逐条刷屏
        bus.log_message.emit(f"⚠️ 已跳过 {len(skipped)} 个无法解析的版本 tag: "
                             f"{', '.join(skipped)}")

    if not infos:
        result.error = "未获取到任何有效 release"
        save_cache(result, ignored)
        return result

    cur_parsed = parse_version(current)

    # 最新正式版（prerelease=False 中层级最高者；若无则取全部中最高）
    stable = [i for i in infos if not i.prerelease]
    pool = stable if stable else infos
    latest = max(pool, key=lambda i: _sort_key(i.parsed))
    result.latest_release = latest.tag
    result.release_url = latest.html_url

    # 最新 pre-release（prerelease=True 中最高者）
    pre = [i for i in infos if i.prerelease]
    if pre:
        latest_pre = max(pre, key=lambda i: _sort_key(i.parsed))
        result.latest_prerelease = latest_pre.tag
        result.prerelease_url = latest_pre.html_url

    # 比较（本地版本也按同一套规则解析）
    if cur_parsed.valid:
        if compare_versions(cur_parsed, latest.parsed) < 0:
            result.has_new_release = latest.tag not in ignored
        result.is_synced = compare_versions(cur_parsed, latest.parsed) >= 0
        if include_prerelease and pre:
            latest_pre = max(pre, key=lambda i: _sort_key(i.parsed))
            if compare_versions(cur_parsed, latest_pre.parsed) < 0:
                result.has_new_prerelease = latest_pre.tag not in ignored
    else:
        result.error = f"本地版本无法解析: {current}"

    save_cache(result, ignored)
    return result


def _sort_key(p: ParsedVersion) -> tuple:
    """max() 排序键：(major, minor, patch, 层级, 数字后缀)。"""
    return (p.major, p.minor, p.patch, _rank(p), p.pre_num)


def should_auto_check() -> bool:
    """是否应执行自动检查（距上次 >= 24h 或无缓存）。"""
    cached = load_cache()
    if not cached.get("checked_at"):
        return True
    return (time.time() - cached["checked_at"]) >= AUTO_CHECK_INTERVAL
