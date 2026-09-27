"""
image_paths.py —— 应用内图片按服务器解析（qrc 路径）。

图片资源按服务器分目录（resources/pictures/ 下）：
  lesta/      Lesta（Korabli）素材
  wargaming/  Wargaming（WG）素材（缺失即缺失，不回退 lesta）

UI 通过 pic_path() 获取当前服务器对应的 qrc 路径：
  Lesta      → :/resources/pictures/lesta/<rel>
  Wargaming  → :/resources/pictures/wargaming/<rel>
"""
from __future__ import annotations


def pic_dir(wows_type: str = "") -> str:
    """返回当前服务器对应的图片目录名（lesta / wargaming）。"""
    if not wows_type:
        from app.application import app as app_ctx
        wows_type = app_ctx.ctx.wows_type
    return "wargaming" if wows_type == "Wargaming" else "lesta"


def pic_path(rel: str, wows_type: str = "") -> str:
    """返回按服务器解析的 qrc 图片路径。

    rel 为相对 resources/pictures/ 的路径（如 "signal_flags/PCEF101_xxx.png"
    或目录前缀 "signal_flags"，调用方再拼接文件名）。
    WG 素材缺失时缺失（不回退 lesta）。
    """
    rel = str(rel).lstrip("/")
    return f":/resources/pictures/{pic_dir(wows_type)}/{rel}"


#: qrc 目录索引缓存：{目录: {小写文件名: 真实文件名}}
_QRC_DIR_CACHE: dict[str, dict[str, str]] = {}


def _qrc_dir_index(qrc_dir: str) -> dict[str, str]:
    """枚举 qrc 目录，返回 ``{小写文件名: 真实文件名}``（进程内缓存）。"""
    idx = _QRC_DIR_CACHE.get(qrc_dir)
    if idx is None:
        idx = {}
        try:
            from PySide6.QtCore import QDir
            for name in QDir(qrc_dir).entryList(["*.png"], QDir.Filter.Files):
                idx[str(name).lower()] = str(name)
        except Exception:  # noqa: BLE001
            pass
        _QRC_DIR_CACHE[qrc_dir] = idx
    return idx


def pic_path_ci(rel: str, wows_type: str = "") -> str:
    """同 `pic_path`，但文件名不区分大小写地解析到 qrc 里的**真实文件名**。

    用途：文件名由**键名转换**得来时（如战斗指令 IDS 标签 → xxx_preview.png），
    素材里的大小写可能与推导结果不同（例：预览图是 ``*_TE_preview.png``，
    推导出的是 ``*_te_preview.png``）。Qt 的 `:/` 路径**区分大小写**，精确名
    对不上就会显示"缺少图片"。
    精确名存在时直接返回（零额外开销）；否则在本目录内做一次不区分大小写的匹配。
    """
    p = pic_path(rel, wows_type)
    try:
        from PySide6.QtCore import QFile
        if QFile(p).exists():
            return p
        d, _, fn = p.rpartition("/")
        real = _qrc_dir_index(d).get(fn.lower())
        if real:
            return f"{d}/{real}"
    except Exception:  # noqa: BLE001
        pass
    return p
