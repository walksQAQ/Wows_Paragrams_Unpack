"""
线程工具 —— QThreadPool + QRunnable 封装。

替代旧代码中 threading.Thread 的混乱模式。
所有耗时操作通过此模块提交到线程池，执行结果通过信号返回。
"""

from __future__ import annotations

from typing import Callable, Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, QThreadPool


class TaskSignals(QObject):
    """任务执行过程中的信号"""
    finished = pyqtSignal(object)   # 参数: 返回值
    error = pyqtSignal(str)         # 参数: 错误消息
    progress = pyqtSignal(int, str) # 参数: 百分比, 消息


class AppTask(QRunnable):
    """
    通用后台任务。

    使用方式：
        task = AppTask(fn=lambda: do_something(arg))
        task.signals.finished.connect(self.on_finished)
        QThreadPool.globalInstance().start(task)
    """

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn()
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))


def run_async(fn: Callable[[], Any]) -> TaskSignals:
    """快捷方式：提交一个任务到全局线程池，返回信号对象"""
    task = AppTask(fn)
    QThreadPool.globalInstance().start(task)
    return task.signals
