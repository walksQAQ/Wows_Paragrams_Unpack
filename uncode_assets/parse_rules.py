# -*- coding: utf-8 -*-
"""明文转码 / 解析规则的选择：自动识别 vs 手动指定 vs 远古版本。

规则取值（与 UI 下拉框一一对应）：

===========  ====================================================
``auto``     自动：按库内原型类型判断（骨架系统 Skeleton vs SkeletonExtender，
             ModelFbx/MiscSettings/Trail/VfxMaterial 有无区分现代莱服与分家前的老客户端）；
             载入客户端目录时先看客户端版本（``game_info.xml``，没有则读
             ``bin64/bin32`` 主程序的 FileVersion），早于 2023-08 直接判 ``legacy``；
            版本也读不到（目录里只有 .pkg）才走库内判断
``Lesta``    强制按莱服（Korabli，记录 0x88）解析
``Wargaming``强制按寄服（WoWS，记录 0x78）解析
``legacy``   远古版本模式：2023-08 之前、**尚未分家**的老客户端（不分莱服/寄服），
             其记录布局与现行 Lesta（0x88）一致，因此统一按 Lesta 规则解析，
             后续发现差异再单独修正
===========  ====================================================

为什么需要它：同一份 ``assets.bin`` 在 0x88 / 0x78 两套记录布局下解码结果完全不同
（用错就整棵树变成一堆 ``0x`` 地址），而"直接打开 assets.bin 文件"时没有客户端
可探测，必须由用户指定。
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

#: 规则标识（UI 下拉框的 itemData）
RULE_AUTO = "auto"
RULE_LESTA = "Lesta"
RULE_WARGAMING = "Wargaming"
RULE_WG_OLD = "wargaming_old"
RULE_LEGACY = "legacy"

#: UI 文案
RULE_LABELS = {
    RULE_AUTO: "自动",
    RULE_LESTA: "Lesta（莱服）",
    RULE_WARGAMING: "Wargaming（寄服）",
    RULE_WG_OLD: "寄服旧布局（14.0 及更早）",
    RULE_LEGACY: "远古版本（2023年8月前的游戏客户端版本）",
}

#: 判定结果里用的短名（塞进状态栏方括号，不能用 RULE_LABELS 的长文案）
RULE_SHORT_LABELS = {
    RULE_LESTA: "Lesta",
    RULE_WARGAMING: "Wargaming",
    RULE_WG_OLD: "寄服旧布局",
    RULE_LEGACY: "远古版本",
}

#: 2023-08 分界版本：WoWS 12.7；Korabli 同期沿用同一套编号
LEGACY_CUTOFF = (12, 7)
#: 分界说明（写进 UI 提示 / 日志）
LEGACY_CUTOFF_TEXT = "2023-08（12.7）"

#: 寄服记录布局切换点：**14.1.0** 起 `.model` 明文从
#: castsShadow/parent/extent/nodefullVisual 变成 visual/animations/dyes
#: （wgmods/ModSDK release 实测：13.3/13.8/13.11/14.0 全为旧格式，14.1 起为新格式）。
#: 旧格式的记录布局与 Lesta 一致，所以 14.0 及更早的寄服客户端也按 Lesta 表解析。
WG_MODERN_CUTOFF = (14, 1)

#: 明文 `<metaData>` 常量：记录里没有字符串字段，由 SDK 导出器补上
#: （实测：寄服 12.7–13.1 与莱服 13.4–13.6 两服并写；寄服 13.2 起 ``Wargaming.net``，
#:  莱服 13.8 起 ``Lesta Studio``）
META_LEGACY = "Wargaming | Lesta Studio"
META_WG_OLD = "Wargaming.net"
#: 寄服品牌文案切换版本：13.2.0 SDK（13.1 仍并写）
META_WG_BRAND_CUTOFF = (13, 2)
#: 莱服品牌文案切换版本：13.8.0 SDK（13.6 仍并写，13.7 缺样本）
META_LESTA_BRAND_CUTOFF = (13, 7)

_VERSION_TAG_RE = re.compile(r"<version\b[^>]*>", re.I)
_ATTR_NAME_RE = re.compile(r'name\s*=\s*"([^"]*)"', re.I)
_ATTR_INSTALLED_RE = re.compile(r'installed\s*=\s*"([^"]*)"', re.I)

# ── 库内原型魔数（判定年代 / 服务器用；与 types.py 的 PrototypeType 对应）──
#: Lesta 骨架系统：分家前后都有，只是寄服 2022 年后改成了 SkeletonExtender
MAGIC_SKELETON = 0xD9BB9F4A
#: Wargaming 骨架扩展：分家后才有
MAGIC_SKELETON_EXTENDER = 0x1AE023FF
#: 现代莱服独有原型（分家后新增；寄服至今没有这些 blob）
MODERN_LESTA_MAGICS = frozenset({
    0xDF80CF54,  # ModelFbx
    0xACE328C6,  # MiscSettings
    0x42AF895E,  # Trail
    0xCD880533,  # VfxMaterial
})


def layout_for_rule(rule: Optional[str]) -> str:
    """规则 → 记录布局/类型表（``Lesta`` / ``Wargaming`` / ``Legacy``）。

    - ``Lesta``：现行莱服表（Material 0x88 / Visual 0x40 / Model 0x20）
    - ``Wargaming``：寄服 14.1+ 的新布局（0x78 / 0x70 / 0x28）
    - ``legacy`` / ``wargaming_old``：未分家时期的共享布局（Material 0x88 但头部前移、
      Visual 0x40 但 geometry@+0x20、Model 0x40）——独立的第三张表
    """
    if (rule or "") == RULE_WARGAMING:
        return "Wargaming"
    if rule in (RULE_LEGACY, RULE_WG_OLD):
        return "Legacy"
    return "Lesta"


def model_meta_for_rule(rule: Optional[str],
                        version: Optional[Tuple[int, ...]] = None) -> str:
    """`.model` 明文 ``<metaData>`` 的覆盖值（空串 = 用解码器默认常量）。

    官方 ModSDK 实测（WG-devacc / wgmods / 本地莱服 SDK 包）：

    - 寄服 ``Wargaming``（14.1+）：``Wargaming.net``
    - 寄服旧布局 ``wargaming_old``（12.7–14.0）：12.7–13.1 → ``Wargaming | Lesta Studio``；
      13.2 起 → ``Wargaming.net``
    - 远古版本 ``legacy``（12.7 之前）：两服并写 ``Wargaming | Lesta Studio``
    - 莱服 ``Lesta``：13.4–13.6 → 两服并写；13.8 起 → ``Lesta Studio``
    """
    if not version or len(version) < 2:
        # 不知道版本时，旧布局只能按「未分家」口径给并写常量
        return META_LEGACY if rule in (RULE_LEGACY, RULE_WG_OLD) else ""
    v = tuple(version[:2])
    if rule in (RULE_LEGACY, RULE_WG_OLD):
        return META_WG_OLD if v >= META_WG_BRAND_CUTOFF else META_LEGACY
    if rule == RULE_LESTA and v < META_LESTA_BRAND_CUTOFF:
        return META_LEGACY
    return ""


def _game_info_paths(game_dir: str):
    root = str(game_dir or "")
    if not root:
        return []
    cands = [os.path.join(root, "game_info.xml")]
    for sub in ("Korabli", "WorldOfWarships", "wows"):
        cands.append(os.path.join(root, sub, "game_info.xml"))
    return [p for p in cands if os.path.isfile(p)]


def read_client_version(game_dir: str) -> Optional[Tuple[int, ...]]:
    """取客户端版本：先读 ``game_info.xml``，读不到再读 ``bin64/bin32`` 主程序。

    ``game_info.xml`` 里的 ``<version name="client" installed="X.Y.Z.W.build">``
    两个客户端的属性顺序不同（WG 把 name 放前，Lesta 把 name 放后），故整段标签匹配。

    Steam / depot 下载的老客户端**没有这个 xml**，改读客户端主程序（
    ``bin/<构建号>/bin64/WorldOfWarships64.exe`` 等）的 FileVersion 资源 ——
    那里的版本号一直是真的（如 ``v20210216`` → ``0.10.1.0``）。

    返回 ``(X, Y, Z, W)`` 形式的整数元组；两者都读不到返回 ``None``。
    """
    for path in _game_info_paths(game_dir):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(4096)
        except OSError:
            continue
        for tag in _VERSION_TAG_RE.findall(text):
            name = _ATTR_NAME_RE.search(tag)
            if not name or name.group(1).lower() != "client":
                continue
            installed = _ATTR_INSTALLED_RE.search(tag)
            if not installed:
                continue
            parts = [p for p in installed.group(1).split(".") if p.isdigit()]
            if parts:
                return tuple(int(p) for p in parts[:4])

    from utils.path_utils import read_client_version_from_exe
    return read_client_version_from_exe(game_dir)


def version_text(version: Optional[Tuple[int, ...]]) -> str:
    """版本元组 → ``"26.10.0.0"`` 之类的展示串（无版本时空串）。"""
    return ".".join(str(v) for v in version) if version else ""


def is_legacy_version(version: Optional[Tuple[int, ...]]) -> bool:
    """版本是否早于 2023-08 分界（无版本信息时返回 False）。"""
    if not version or len(version) < 2:
        return False
    return (version[0], version[1]) < LEGACY_CUTOFF


def detect_rule(game_dir: str) -> Tuple[str, Optional[Tuple[int, ...]]]:
    """按客户端目录探测规则。

    顺序：客户端版本（``game_info.xml`` → ``bin64/bin32`` 主程序 FileVersion）
    → 早于 2023-08 判 ``legacy``；寄服在 **14.1 之前**仍是旧布局（判
    ``wargaming_old``，与 Lesta 表同构）；版本读不到（目录里没有可执行文件）
    才返回 :data:`RULE_AUTO`，交给 :func:`detect_rule_from_db` 按库内原型判断。

    Returns:
        ``(rule, version)``：``rule`` 为 :data:`RULE_LESTA` / :data:`RULE_WARGAMING` /
        :data:`RULE_WG_OLD` / :data:`RULE_LEGACY` / :data:`RULE_AUTO`；``version`` 可能为 None。
    """
    from utils.path_utils import detect_wows_type

    client = detect_wows_type(game_dir) or RULE_LESTA
    version = read_client_version(game_dir)
    if version is None:
        # 只有 .pkg、没有客户端主程序的目录：交给库内原型判断
        return RULE_AUTO, None
    if is_legacy_version(version):
        # 分家前的客户端不分莱服/寄服（主程序同样叫 WorldOfWarships64.exe），
        # 统一按远古版本处理
        return RULE_LEGACY, version
    if client == RULE_WARGAMING and version[:2] < WG_MODERN_CUTOFF:
        # 寄服 14.1 起才换成新布局：13.x / 14.0 的 .model 明文仍是
        # castsShadow/parent/extent/nodefullVisual（与 Lesta 同构）
        return RULE_WG_OLD, version
    return client, version


def detect_rule_from_db(db) -> Tuple[str, str]:
    """按 assets.bin 里出现的 prototype 魔数判断该用哪套规则。

    只看「分家」前后真正变化的骨架系统：分家前的客户端（含当时的寄服/莱服）
    都有 Skeleton，寄服 2022 年后改成 SkeletonExtender；莱服后来新增了
    ModelFbx / MiscSettings / Trail / VfxMaterial。较早的寄服仅有
    PointLight / VelocityField（老莱服库同样有），不能作为判据。

    Returns:
        ``(rule, reason)``；可为 :data:`RULE_LESTA` / :data:`RULE_WARGAMING` /
        :data:`RULE_LEGACY`；无法判断时 ``rule`` 为空串（调用方自行兜底）。
    """
    magics = set()
    try:
        for entry in getattr(db, "databases", []) or []:
            magic = getattr(entry, "prototype_magic", None)
            if magic is not None:
                magics.add(magic)
    except Exception:  # noqa: BLE001
        return "", "读取 prototype 表失败"

    modern_lesta = magics & MODERN_LESTA_MAGICS
    if MAGIC_SKELETON in magics:
        if modern_lesta:
            return (RULE_LESTA,
                    f"发现骨架系统 + {len(modern_lesta)} 个莱服新增原型类型")
        return (RULE_LEGACY,
                "只有分家前的骨架系统，缺少莱服新增的 ModelFbx/MiscSettings/Trail/VfxMaterial")
    if MAGIC_SKELETON_EXTENDER in magics:
        return RULE_WARGAMING, "发现寄服独有的 SkeletonExtender"
    return "", "库里只有两服共有的原型类型，无法判断"


def rule_tooltip() -> str:
    """下拉框提示文案。"""
    return (
        "明文转码 / 解析规则（默认「自动」，一般不需要改）\n"
        "• 自动：按库内原型类型判断莱服 / 寄服 / 远古版本（分家前的老客户端）；\n"
        "  选择游戏目录时先看客户端版本（game_info.xml，没有则读 bin64/bin32\n"
        "  主程序的版本资源），版本早于分界同样直接判远古版本\n"
        f"• 客户端版本早于 {LEGACY_CUTOFF_TEXT} 时自动进入「远古版本」模式，"
        "目前按 Lesta 规则解析")
