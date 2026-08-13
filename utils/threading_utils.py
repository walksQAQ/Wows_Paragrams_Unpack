"""
线程工具 —— threading.Thread 封装。

后台任务通过回调返回结果；on_finished / on_error 统一投递到**主线程**执行。

为什么必须主线程化回调？
  1. 回调里常直接操作 Qt 控件（QPushButton.setEnabled 等），非 GUI 线程访问
     QWidget 会导致 Qt 崩溃；
  2. 回调里会关闭/重置数据库连接（如 reset_db → close_all_connections），
     若在后台线程关闭主线程正在使用的 sqlite 连接，会引发 sqlite C 扩展
     段错误（无 traceback 的"莫名崩溃"，打包后时序更易触发）。

实现：worker 线程把结果通过"主线程 QObject 的信号"（queued connection）
投递回主线程，由主线程执行回调。这样所有 UI/数据库收尾都在主线程串行执行。
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal


class _Dispatcher(QObject):
    """主线程分发器 —— worker 线程通过它把结果投递回主线程"""
    finished = Signal(object, bool)  # (task, is_error)


# 模块级单例：首次被 import 的线程（即主线程）创建，因此其信号槽在主线程执行
_dispatcher = _Dispatcher()


class _AppTask:
    """后台任务（回调投递到主线程执行）"""

    def __init__(self, fn: Callable[[], Any], on_finished=None, on_error=None):
        self.fn = fn
        self._on_finished = on_finished
        self._on_error = on_error
        self._thread: threading.Thread | None = None
        self._result: Any = None
        self._is_error = False

    def _run(self) -> None:
        try:
            self._result = self.fn()
            self._is_error = False
        except Exception as e:
            self._result = str(e)
            self._is_error = True
        finally:
            try:
                _running_tasks.remove(self)
            except ValueError:
                pass
        # queued connection：_dispatcher 所在线程（主线程）会执行 _on_dispatched
        _dispatcher.finished.emit(self, self._is_error)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()


@_dispatcher.finished.connect
def _on_dispatched(task: _AppTask, is_error: bool) -> None:
    """在主线程执行任务回调"""
    if is_error:
        if task._on_error:
            task._on_error(task._result)
    else:
        if task._on_finished:
            task._on_finished(task._result)


# 持有所有运行中的任务引用，防止被 GC 回收
_running_tasks: list[_AppTask] = []


def run_async(fn: Callable[[], Any], on_finished=None, on_error=None) -> None:
    """提交一个任务到后台线程。

    fn 在后台线程执行；on_finished(result) / on_error(err_msg) 将在**主线程**被调用。
    """
    task = _AppTask(fn, on_finished=on_finished, on_error=on_error)
    _running_tasks.append(task)
    task.start()
