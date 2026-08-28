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

协作式取消：run_async 返回 _AppTask 句柄，可调用 .cancel() 请求取消；支持
取消的工作函数以 fn(cancel_event) 调用（传入 cancel_event 时），在长循环检查
取消事件并抛出 TaskCancelled 提前退出。已取消的任务不会再执行任何回调。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal


class _Dispatcher(QObject):
    """主线程分发器 —— worker 线程通过它把结果投递回主线程"""
    finished = Signal(object, bool)  # (task, is_error)


# 模块级单例：首次被 import 的线程（即主线程）创建，因此其信号槽在主线程执行
_dispatcher = _Dispatcher()


class TaskCancelled(Exception):
    """后台任务被协作式取消。调度器将其视为正常结束，不当作错误、不调用回调。"""


class _ForceStop(BaseException):
    """强制终止信号（BaseException 子类：不被 except Exception 吞掉）。

    由 _AppTask.kill() 注入工作线程；线程在下一字节码边界抛出，_run 将其
    视为正常取消（不再执行回调）。仅用于只读/内存型任务的强制收尾。
    """


class _AppTask:
    """后台任务（回调投递到主线程执行；支持协作式取消）。"""

    def __init__(self, fn: Callable[[], Any], on_finished=None, on_error=None,
                 cancel_event: threading.Event | None = None):
        self.fn = fn
        self._on_finished = on_finished
        self._on_error = on_error
        self._thread: threading.Thread | None = None
        self._result: Any = None
        self._is_error = False
        self._cancelled = False
        # 显式传入 cancel_event 时，工作函数以 fn(cancel_event) 调用（供长循环检查取消）
        self._pass_event = cancel_event is not None
        self._cancel_event = cancel_event if cancel_event is not None else threading.Event()

    # ── 取消协议 ────────────────────────────────────────

    def cancel(self) -> None:
        """请求协作式取消：设置取消事件，工作函数在下一个检查点退出。"""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        """任务是否已被请求取消。"""
        return self._cancel_event.is_set()

    @property
    def cancel_event(self) -> threading.Event:
        """取消事件：支持取消的工作函数可在长循环中检查它。"""
        return self._cancel_event

    def is_running(self) -> bool:
        """任务线程是否仍在运行。"""
        return self._thread is not None and self._thread.is_alive()

    def kill(self, timeout: float = 1.0) -> bool:
        """强制终止工作线程（无论进度如何，尽力而为）。

        先置取消事件（协作式检查点优先退出），再向线程注入 _ForceStop，
        直到线程退出或超时。⚠️ 仅用于**只读/内存型**任务（如 3D 查看器的
        几何/装甲加载）；正在写数据库/写文件的线程请勿强杀（会留下半写入状态）。
        返回线程是否已退出。
        """
        self.cancel()
        thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        import ctypes
        tid = thread.ident
        deadline = time.monotonic() + max(0.0, timeout)
        while thread.is_alive() and time.monotonic() < deadline:
            if tid is not None:
                try:
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(
                        ctypes.c_long(tid), ctypes.py_object(_ForceStop))
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.01)
        return not thread.is_alive()

    def _run(self) -> None:
        # 外层兜底：_ForceStop 由 kill() 在**任意字节码边界**注入（可能落在 finally /
        # emit 等内层 try/except 之外）。若它逃出工作线程，会触发 threading.excepthook
        # 的 "Exception ignored in thread"（_ForceStop 是 BaseException，log 钩子
        # 用 except Exception 捕不到）。这里把它与一切逃逸的 BaseException 一并吞掉，
        # 绝不让它逃出线程；日志交给主线程 excepthook 兜底。
        try:
            self._run_body()
        except _ForceStop:
            self._cancelled = True
        except BaseException:
            # 兜底：吞掉任何其它未经处理的逃逸异常（仅作线程收尾，不再上抛）
            self._cancelled = True

    def _run_body(self) -> None:
        # 尚未开始执行即已取消 → 直接退出（不运行 fn、不回调）
        if self._cancel_event.is_set():
            self._cancelled = True
            self._remove_from_running()
            return
        try:
            if self._pass_event:
                self._result = self.fn(self._cancel_event)
            else:
                self._result = self.fn()
            self._is_error = False
        except _ForceStop:
            # 强制终止：视为正常取消（不当作错误、不调用回调）
            self._cancelled = True
        except TaskCancelled:
            self._cancelled = True
        except Exception as e:
            self._result = str(e)
            self._is_error = True
        finally:
            self._remove_from_running()
        # 取消后的任务不得再执行任何回调（含「任务完成后、回调投递前」被取消的窗口期）
        if self._cancelled or self._cancel_event.is_set():
            return
        # queued connection：_dispatcher 所在线程（主线程）会执行 _on_dispatched
        _dispatcher.finished.emit(self, self._is_error)

    def _remove_from_running(self) -> None:
        try:
            _running_tasks.remove(self)
        except ValueError:
            pass

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()


@_dispatcher.finished.connect
def _on_dispatched(task: _AppTask, is_error: bool) -> None:
    """在主线程执行任务回调"""
    # 双保险：worker 已结束但回调仍在主线程队列中排队时任务被取消 → 丢弃过期结果
    if task.is_cancelled():
        return
    if is_error:
        if task._on_error:
            task._on_error(task._result)
    else:
        if task._on_finished:
            task._on_finished(task._result)


# 持有所有运行中的任务引用，防止被 GC 回收
_running_tasks: list[_AppTask] = []


def run_async(fn: Callable[[], Any], on_finished=None, on_error=None,
              cancel_event: threading.Event | None = None) -> _AppTask:
    """提交一个任务到后台线程，返回任务句柄。

    fn 在后台线程执行；on_finished(result) / on_error(err_msg) 将在**主线程**被调用。

    协作式取消：
      - 返回值可调用 .cancel() / .is_cancelled() / .is_running()；
      - 若传入 cancel_event（threading.Event），工作函数以 fn(cancel_event) 调用，
        便于在长循环中检查取消；未传入则保持 fn() 调用（旧调用方兼容）；
      - 已取消的任务不会再执行 on_finished / on_error 回调。
    """
    task = _AppTask(fn, on_finished=on_finished, on_error=on_error,
                    cancel_event=cancel_event)
    _running_tasks.append(task)
    task.start()
    return task
