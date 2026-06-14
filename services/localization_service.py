"""
本地化服务 —— 下载并解析 global.mo → global.po → JSON 映射文件。

完全内联了旧 POToolkit 的逻辑，不再依赖旧代码。
"""

from __future__ import annotations

import json
import os
import re
import shutil

import requests
import urllib.request

from app.signals import bus
from app.application import app as app_ctx
from utils.threading_utils import run_async
from utils.path_utils import get_data_dir


def _extract_mappings(po_path: str, out_dir: str) -> dict:
    """从 PO 文件中提取所有翻译映射并保存为 JSON"""
    import polib

    raw = open(po_path, 'r', encoding='utf-8', errors='ignore').read()
    raw = raw.replace('˙', '·')

    def save(data, fn):
        p = os.path.join(out_dir, fn)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return p

    stats = {}

    # 消耗品
    pat = re.compile(r'msgid "IDS_DOCK_CONSUME_TITLE_((?:P[XYC]\d{3}|[A-Z0-9]+)_[A-Z0-9_]+)"\s+msgstr "(.*?)"', re.MULTILINE)
    data = {k: v for k, v in pat.findall(raw) if v.strip() and not v.startswith("IDS_")}
    stats["consumable_names"] = {"path": save(data, "consumable_names.json"), "count": len(data)}

    # 舰船名
    ship_map = {}
    cur = None
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r'^msgid\s+"IDS_(P[A-Z]S[ABCDSX]\d+)"$', line)
        if m:
            cur = m.group(1)
            continue
        if cur:
            m = re.match(r'^msgstr\s+"(.*)"$', line)
            if m and m.group(1) and not m.group(1).isdigit():
                ship_map[cur] = m.group(1)
            cur = None
    stats["ship_names"] = {"path": save(ship_map, "ship_names.json"), "count": len(ship_map)}

    # 火炮
    pat = re.compile(r'msgid "IDS_(P[A-Z]G[A-Z]+.*?)"\s+msgstr "(.*?)"', re.MULTILINE)
    data = {k: v for k, v in pat.findall(raw) if v.strip() and not v.startswith("IDS_DOCK")}
    stats["guns_names"] = {"path": save(data, "guns_names.json"), "count": len(data)}

    # 弹药
    pat = re.compile(r'msgid "IDS_(P[A-Z]P[ABDLMRTW]+\d+\S*?)"\s+msgstr "(.*?)"', re.MULTILINE)
    data = {k.upper(): v for k, v in pat.findall(raw) if v.strip() and not v.startswith("IDS_")}
    stats["ammo_names"] = {"path": save(data, "ammo_names.json"), "count": len(data)}

    # 升级品
    pat = re.compile(r'msgid "IDS_(?:TITLE_|MODERNIZATION_)?(P[CU]M\d{3}[A-Z0-9_]*?)"\s+msgstr "(.*?)"', re.MULTILINE)
    data = {k.upper(): v for k, v in pat.findall(raw) if v.strip() and not v.startswith("IDS_")}
    stats["modernization_names"] = {"path": save(data, "modernization_names.json"), "count": len(data)}

    # 飞机
    pat = re.compile(r'msgid "IDS_(P[A-Z]A[BDFMLSX][A-Z0-9_]*)"\s+msgstr "(.*?)"', re.MULTILINE)
    data = {k.upper(): v for k, v in pat.findall(raw) if v.strip() and not v.startswith("IDS_")}
    stats["plane_names"] = {"path": save(data, "plane_names.json"), "count": len(data)}

    # 狂暴模式
    pat = re.compile(r'msgid\s+"(IDS_DOCK_RAGE_MODE_TITLE_.*?)"\s+msgstr\s+"(.*?)"', re.MULTILINE)
    data = {k: v for k, v in pat.findall(raw) if v.strip()}
    stats["rage_mode_names"] = {"path": save(data, "rage_mode_names.json"), "count": len(data)}

    return stats


def run_localization() -> None:
    ctx = app_ctx.ctx
    wows_type = ctx.wows_type
    game_path = ctx.game_path
    data_dir = get_data_dir()

    def _run():
        # ── 下载 / 复制 global.mo ────────────────────
        if wows_type == "Wargaming":
            bin_root = os.path.join(game_path, "bin")
            if not os.path.exists(bin_root):
                raise Exception("找不到 bin 目录")
            folders = [f for f in os.listdir(bin_root)
                       if f.isdigit() and os.path.isdir(os.path.join(bin_root, f))]
            if not folders:
                raise Exception("未找到版本文件夹")
            lb = sorted(folders, key=int)[-1]
            src = os.path.join(bin_root, lb, "res/texts/zh_sg/LC_MESSAGES/global.mo")
            if not os.path.exists(src):
                alt = os.path.join(bin_root, lb, "res/texts/zh_cn/LC_MESSAGES/global.mo")
                if os.path.exists(alt):
                    src = alt
                else:
                    raise Exception("找不到 global.mo")
            shutil.copy2(src, os.path.join(str(data_dir), "global.mo"))

        elif wows_type == "Lesta":
            urls = [
                "https://gitlab.com/localizedkorabli/korabli-lesta-l10n/-/raw/main/Localizations/latest/global.mo",
                "https://github.com/LocalizedKorabli/Korabli-LESTA-L10N/raw/main/Localizations/latest/global.mo",
                "https://gitee.com/localized-korabli/Korabli-LESTA-L10N/raw/main/Localizations/latest/global.mo",
            ]
            mo_path = os.path.join(str(data_dir), "global.mo")
            proxies = urllib.request.getproxies()
            headers = {"User-Agent": "Mozilla/5.0"}
            ok = False
            for url in urls:
                try:
                    r = requests.get(url, headers=headers, timeout=15, proxies=proxies)
                    r.raise_for_status()
                    with open(mo_path, "wb") as f:
                        f.write(r.content)
                    ok = True
                    break
                except Exception:
                    continue
            if not ok:
                raise Exception("所有下载节点均无法连接")
        else:
            raise Exception("未知服务器类型")

        # ── MO → PO ─────────────────────────────────
        import polib
        mo = polib.mofile(os.path.join(str(data_dir), "global.mo"))
        po = polib.POFile()
        po.metadata = mo.metadata
        for e in mo:
            po.append(e)
        po.save(os.path.join(str(data_dir), "global.po"))
        os.remove(os.path.join(str(data_dir), "global.mo"))

        # ── PO → JSON ────────────────────────────────
        return _extract_mappings(os.path.join(str(data_dir), "global.po"), str(data_dir))

    def _ok(stats):
        bus.log_message.emit("✅ 语言文件加载完成")
        for k, v in stats.items():
            bus.log_message.emit(f"  {k}: {v['count']} 条")
        bus.localization_ready.emit()

    def _err(msg: str):
        bus.log_message.emit(f"❌ 加载失败: {msg}")

    run_async(_run, on_finished=_ok, on_error=_err)
