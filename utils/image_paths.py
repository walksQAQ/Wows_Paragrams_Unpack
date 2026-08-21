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
