"""utils/qrc_rebuilder.py —— 源码模式下自动重编译 Qt 资源（QRC → _resources.py）。

背景
----
项目把 `resources/` 下的所有文件（图片 / QSS / database_new.sql 等）编译进
`app/_resources.py`（Qt 资源编译器产物）。运行时 `app/__init__.py` 注册 QRC，
且加载资源时**优先**从 QRC 内存读取（`QFile(":/...")`），QRC 打开成功就
不会回退到磁盘文件。

因此，如果修改了 `resources/` 下的文件（尤其是 `database_new.sql`）却没有重新
编译 `_resources.py`，源码运行时仍会加载**过期内嵌资源**，导致类似
`no such table: consumable_buff` 的隐蔽故障。

本模块在**源码模式**启动时按 mtime 检查 `resources.qrc` / `app/_resources.py`
是否过期，过期则自动重新生成 / 重编译，保证源码启动始终使用最新资源。
Nuitka 编译后（`__compiled__` 存在）直接跳过，不产生任何开销。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# 与 scripts/gen_qrc.py 保持一致的排除清单（运行时读写、不进 QRC 的用户数据）
_EXCLUDE = {"epic_skill_config.json"}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RESOURCES_DIR = _PROJECT_ROOT / "resources"
_QRC_PATH = _PROJECT_ROOT / "resources.qrc"
_OUTPUT = _PROJECT_ROOT / "app" / "_resources.py"
_GEN_QRC = _PROJECT_ROOT / "scripts" / "gen_qrc.py"

# 设 WOWS_QRC_REBUILD_DEBUG=1 可输出重编译过程中的详细错误
_DEBUG = os.environ.get("WOWS_QRC_REBUILD_DEBUG") == "1"


def _log(msg: str) -> None:
    print(msg)


def _run(cmd: list[str]) -> bool:
    """运行外部命令；成功返回 True，失败返回 False（不抛异常）。"""
    kwargs: dict = {"capture_output": True, "text": True, "timeout": 300}
    if os.name == "nt":
        # 从 GUI 进程调用时不弹出控制台窗口
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(cmd, **kwargs)
    except Exception as e:  # noqa: BLE001
        if _DEBUG:
            _log(f"[qrc] 命令执行异常: {e}")
        return False
    if proc.returncode != 0:
        if _DEBUG:
            _log(f"[qrc] 命令失败: {' '.join(cmd)}\n{proc.stderr[-2000:]}")
        return False
    return True


def _qrc_referenced_files() -> list[Path]:
    """解析 resources.qrc，返回其引用的资源文件路径列表（相对项目根）。"""
    try:
        text = _QRC_PATH.read_text(encoding="utf-8")
    except OSError:
        return []
    files = []
    for m in re.finditer(r"<file[^>]*>([^<]+)</file>", text):
        rel = m.group(1).strip()
        if rel:
            files.append(_PROJECT_ROOT / rel)
    return files


def _qrc_stale() -> bool:
    """resources.qrc 是否过期：不存在，或早于任一未排除的资源文件。"""
    if not _QRC_PATH.exists():
        return True
    qrc_mtime = _QRC_PATH.stat().st_mtime
    try:
        for p in _RESOURCES_DIR.rglob("*"):
            if p.is_file() and p.name not in _EXCLUDE and p.stat().st_mtime > qrc_mtime:
                return True
    except OSError:
        return True
    return False


def _resources_stale() -> bool:
    """app/_resources.py 是否过期：不存在，或早于 qrc / 任一被引用的资源文件。"""
    if not _OUTPUT.exists():
        return True
    out_mtime = _OUTPUT.stat().st_mtime
    try:
        if _QRC_PATH.stat().st_mtime > out_mtime:
            return True
    except OSError:
        return True
    for p in _qrc_referenced_files():
        try:
            if p.stat().st_mtime > out_mtime:
                return True
        except OSError:
            continue
    return False


def _rcc_command() -> list[str] | None:
    """返回可用的 rcc 编译命令（与 build.bat 保持一致）。"""
    venv_rcc = _PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / "PySide6" / "rcc.exe"
    if venv_rcc.exists():
        return [str(venv_rcc), "-g", "python", str(_QRC_PATH), "-o", str(_OUTPUT)]
    if sys.executable:
        return [sys.executable, "-m", "PySide6.rcc", str(_QRC_PATH), "-o", str(_OUTPUT)]
    return None


def ensure_qrc_fresh() -> bool:
    """确保 QRC 资源最新；返回本次是否执行了重编译。

    仅源码模式生效；编译模式（Nuitka `__compiled__`）直接跳过返回 False。
    """
    if "__compiled__" in globals():
        return False
    if not _RESOURCES_DIR.exists():
        return False

    # 1) 需要时重新生成 resources.qrc（捕捉新增/修改的资源文件）
    if _qrc_stale() and _GEN_QRC.exists():
        if _run([sys.executable, str(_GEN_QRC)]):
            _log("[qrc] 已重新生成 resources.qrc")

    if not _QRC_PATH.exists():
        return False

    # 2) 需要时重编译 app/_resources.py
    if not _resources_stale():
        return False

    cmd = _rcc_command()
    if not cmd:
        _log("[qrc] 警告: 未找到 rcc 编译器，将使用现有 _resources.py")
        return False

    if _run(cmd):
        size_kb = _OUTPUT.stat().st_size // 1024 if _OUTPUT.exists() else 0
        _log(f"[qrc] 检测到资源变更，已重编译 app/_resources.py（{size_kb} KB）")
        return True

    _log("[qrc] 警告: QRC 重编译失败，将使用现有 _resources.py")
    return False


if __name__ == "__main__":
    ensure_qrc_fresh()
