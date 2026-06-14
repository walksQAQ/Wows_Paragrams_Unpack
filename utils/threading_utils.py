"""
线程工具 —— threading.Thread 封装。

后台任务通过回调返回结果，避免 Qt 信号跨线程的兼容问题。
"""

from __future__ import annotations

import threading
from typing import Callable, Any


class _AppTask:
    """后台任务（回调方式，不走 Qt 信号）"""

    def __init__(self, fn: Callable[[], Any], on_finished=None, on_error=None):
        self.fn = fn
        self._on_finished = on_finished
        self._on_error = on_error
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        try:
            result = self.fn()
            if self._on_finished:
                self._on_finished(result)
        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
        finally:
            try:
                _running_tasks.remove(self)
            except ValueError:
                pass

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()


# 持有所有运行中的任务引用，防止被 GC 回收
_running_tasks: list[_AppTask] = []

def run_async(fn: Callable[[], Any], on_finished=None, on_error=None) -> None:
    """提交一个任务到后台线程，通过回调返回结果"""
    task = _AppTask(fn, on_finished=on_finished, on_error=on_error)
    task.start()
    _running_tasks.append(task)
