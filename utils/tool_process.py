"""独立工具的进程隔离执行器。

独立工具（模型查看器、独立的客户端浏览器等）的重负载解析放到**子进程**里跑，
而不是主进程的后台线程：

- 线程方案下，纯 Python 解析与 GUI 主线程争同一把 GIL，主界面会周期性掉帧；
- 线程方案下产生的大量临时对象会让主进程 GC 停顿，子进程解析只影响它自己；
- 解析申请的几十 ~ 几百 MB 内存留在子进程，主程序的内存曲线不会被工具拉高。

接口刻意与 :func:`utils.threading_utils.run_async` 对齐：回调同样投递回主线程执行，
调用方只把「跑在线程里」改成「跑在进程里」。

约束（spawn 语义）：
    * ``fn`` 必须是**模块级**函数（靠模块名 + 函数名 pickle 过去）；
    * 参数与返回值必须可 pickle —— 不要传 Qt 对象、文件句柄、pkg 提取器实例；
    * 子进程里没有 Qt 事件循环，也不共享父进程的任何缓存。

取消语义：
    ProcessPoolExecutor 无法中断已在执行的任务。``cancel()`` 会尽力取消尚未开始的
    future，并保证已取消任务的结果被丢弃、不会触发任何回调；已经在跑的任务会在
    子进程里自然结束（工具侧都是只读操作，无副作用）。
"""

from __future__ import annotations

import atexit
import multiprocessing as mp
import threading
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

#: 独立工具用的最大并发子进程数。工具是交互式的，1 个足够且最省内存。
MAX_WORKERS = 1


class _ToolDispatcher(QObject):
    """主线程回调分发器 —— 子进程结果经它投递回 GUI 线程。"""

    finished = Signal(object, object, bool)  # (task, result, is_error)


#: 首次 import 发生在主线程，因此其信号槽在主线程执行
_dispatcher = _ToolDispatcher()

_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def _spawn_context():
    """Windows 上只能用 spawn；显式指定以免受父进程 start method 影响。"""
    return mp.get_context("spawn")


def _ensure_pool() -> ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=MAX_WORKERS,
                                        mp_context=_spawn_context())
        return _pool


def _drop_pool(wait: bool = False) -> None:
    """丢弃当前进程池（子进程崩溃 / 应用退出时调用），下次自动重建。"""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        try:
            pool.shutdown(wait=wait, cancel_futures=True)
        except Exception:  # noqa: BLE001
            pass


def _drop_pool_at_exit() -> None:
    """解释器退出兜底：不阻塞（避免卡住关闭流程）。"""
    _drop_pool(wait=False)


atexit.register(_drop_pool_at_exit)


class ToolProcessTask:
    """子进程任务句柄（与 _AppTask 的 cancel/is_running 语义保持一致）。"""

    def __init__(self, future, on_finished=None, on_error=None) -> None:
        self._future = future
        self._on_finished = on_finished
        self._on_error = on_error
        self._cancelled = False

    def cancel(self) -> None:
        """放弃结果：尽力取消未开始的 future，并丢弃后续回调。"""
        self._cancelled = True
        try:
            self._future.cancel()
        except Exception:  # noqa: BLE001
            pass

    def is_cancelled(self) -> bool:
        return self._cancelled

    def is_running(self) -> bool:
        return not self._future.done()

    # ── 内部：future 完成（在 worker/回调线程）→ 转投主线程 ──
    def _relay(self, future) -> None:
        if self._cancelled:
            return
        try:
            err = future.exception()
        except Exception as e:  # noqa: BLE001  （进程池崩溃等）
            err = e
            result = None
        else:
            result = None if err is not None else future.result()
        _dispatcher.finished.emit(self, result if err is None else str(err),
                                  err is not None)


@_dispatcher.finished.connect
def _on_finished(task: ToolProcessTask, payload: Any, is_error: bool) -> None:
    """主线程：执行调用方回调（已完成/已取消的任务一律丢弃）。"""
    if task.is_cancelled():
        return
    if is_error:
        if task._on_error:
            task._on_error(payload)
    else:
        if task._on_finished:
            task._on_finished(payload)


def run_in_tool_process(fn: Callable[..., Any], *args: Any,
                        on_finished: Callable[[Any], None] | None = None,
                        on_error: Callable[[str], None] | None = None,
                        ) -> ToolProcessTask:
    """在独立的工具子进程里执行 ``fn(*args)``，返回任务句柄。

    ``on_finished(result)`` / ``on_error(err_msg)`` 都会在主线程被调用。
    ``fn`` 必须是模块级函数，参数与返回值必须可 pickle。
    """
    pool = _ensure_pool()
    try:
        future = pool.submit(fn, *args)
    except Exception:  # noqa: BLE001  进程池已损坏 → 重建后重试一次
        _drop_pool()
        future = _ensure_pool().submit(fn, *args)

    task = ToolProcessTask(future, on_finished=on_finished, on_error=on_error)

    def _done(f) -> None:
        task._relay(f)

    future.add_done_callback(_done)
    return task


def shutdown_tool_processes(wait: bool = True) -> None:
    """关闭工具进程池（应用退出时调用，默认等待 worker 真正退出）。"""
    _drop_pool(wait=wait)
