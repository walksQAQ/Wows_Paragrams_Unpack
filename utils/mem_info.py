"""utils/mem_info.py —— 进程内存占用查询（诊断用）。

用途：把「解析 / 建场景 / 上传 GPU」各阶段的真实内存写进日志，避免靠任务管理器猜。
Windows 走 ``psapi.GetProcessMemoryInfo``；其它平台或查询失败时返回 ``None``，
调用方自行跳过打印（不影响功能）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as _wt


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", _wt.DWORD),
        ("PageFaultCount", _wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_memory_mb() -> tuple[float, float] | None:
    """返回 ``(当前工作集 MB, 峰值工作集 MB)``；不可用时返回 ``None``。"""
    if not hasattr(ctypes, "windll"):
        return None
    try:
        pmc = _PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        if not ok:
            return None
        return pmc.WorkingSetSize / 1e6, pmc.PeakWorkingSetSize / 1e6
    except Exception:  # noqa: BLE001 - 诊断功能，失败即静默
        return None


def memory_suffix() -> str:
    """日志后缀：``"，内存 1234MB（峰值 2345MB）"``（不可用时为空串）。"""
    mem = process_memory_mb()
    if mem is None:
        return ""
    return f"，内存 {mem[0]:.0f}MB（峰值 {mem[1]:.0f}MB）"
