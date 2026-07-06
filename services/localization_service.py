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


def import_text_to_db(db=None) -> dict:
    """将磁盘上的 JSON 映射文件和 PO 翻译文件写入数据库。

    这是从文本/本地化角度写入数据库的独立入口，不依赖数据加载流程。
    如果未传入 db，自动查找最新（有数据）的数据库文件。
    返回统计: {name_mappings: {filename: count}, po_translations: int}
    """
    from services.database_service import DatabaseManager, get_db
    # 优先使用传入的 db，否则找当前服务器对应的 DB
    target = db if isinstance(db, DatabaseManager) else get_db()
    # 如果 target 无数据，尝试查找同服务器的其他 DB 文件
    if not target.exists or target.get_stats().get("total_entities", 0) == 0:
        data_dir = get_data_dir()
        from app.application import app as app_ctx
        # 尝试当前服务器对应的 DB
        svr_path = data_dir / DatabaseManager._db_name(app_ctx.ctx.wows_type)
        if svr_path.exists() and svr_path != target.db_path:
            candidate = DatabaseManager(svr_path)
            candidate.initialize()
            if candidate.get_stats().get("total_entities", 0) > 0:
                target = candidate
    if target.exists:
        nm = target.import_name_mappings(str(get_data_dir()))
        po_path = get_data_dir() / "global.po"
        po_cnt = target.import_po_translations(str(po_path)) if po_path.exists() else 0
        return {"name_mappings": nm, "po_translations": po_cnt}
    return {"name_mappings": {}, "po_translations": 0}


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
        bus.task_progress.emit(5, "下载/复制语言文件")
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

        bus.task_progress.emit(15, "转换 PO 文件")
        # ── MO → PO ─────────────────────────────────
        import polib
        mo = polib.mofile(os.path.join(str(data_dir), "global.mo"))
        po = polib.POFile()
        po.metadata = mo.metadata
        for e in mo:
            po.append(e)
        po.save(os.path.join(str(data_dir), "global.po"))
        os.remove(os.path.join(str(data_dir), "global.mo"))

        bus.task_progress.emit(25, "提取映射并写入 JSON")
        # ── PO → JSON ────────────────────────────────
        return _extract_mappings(os.path.join(str(data_dir), "global.po"), str(data_dir))

    def _ok(stats):
        bus.task_progress.emit(45, "导入文本到数据库")
        bus.log_message.emit("✅ 语言文件加载完成")
        for k, v in stats.items():
            bus.log_message.emit(f"  {k}: {v['count']} 条")
        # 将文本数据写入数据库
        try:
            from services.database_service import get_db
            res = import_text_to_db(get_db())
            if res["name_mappings"]:
                bus.log_message.emit(f"📦 名称映射已入库: {sum(res['name_mappings'].values())} 条")
            if res["po_translations"]:
                bus.log_message.emit(f"📦 PO 翻译已入库: {res['po_translations']} 条")
        except Exception as e:
            bus.log_message.emit(f"⚠️ 文本入库失败: {e}")
        finally:
            # 兜底清理：删除所有临时 JSON/PO 文件
            import glob
            for f in glob.glob(os.path.join(str(data_dir), "*_names.json")):
                try: os.remove(f)
                except: pass
            pof = os.path.join(str(data_dir), "global.po")
            if os.path.exists(pof):
                try: os.remove(pof)
                except: pass
        bus.task_progress.emit(100, "本地化完成")
        bus.localization_ready.emit()
        # 刷新名称映射 → 清理 Presenter 缓存 + 刷新界面
        try:
            from presenters.registry import PresenterRegistry
            PresenterRegistry.clear_cache()
        except Exception:
            pass
        bus.log_message.emit("✅ 文本数据加载完成，本地化内容已就绪")
        bus.folder_selected.emit("__REFRESH__")

    def _err(msg: str):
        bus.log_message.emit(f"❌ 加载失败: {msg}")

    run_async(_run, on_finished=_ok, on_error=_err)
