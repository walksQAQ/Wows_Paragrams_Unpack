"""运行日志文件写入器。

把程序运行日志（日志区消息 + 未处理异常 traceback + 启动信息）持久化到
``get_app_dir()/log/log-YYYYMMDD_HHMMSS.log``，供排查/反馈使用。

Nuitka 兼容：目录用 ``get_app_dir()``（与 data/ 、config.json 同一策略）——
源码模式落在项目根，onefile/standalone 打包后落在 **exe 同级**，
不依赖 importlib/临时解压目录，与 data 等用户数据的落盘要求一致。

设计要点：
- 每次启动新建一个文件（文件名含启动时间戳）；
- 监听 ``bus.log_message`` 把每条日志区消息追加写入；
- 注册 ``sys.excepthook`` / ``threading.excepthook`` 捕获未处理异常写入；
- 只保留最近 30 个 ``log-*.log``，更旧的在会话头写入后删除；
- 不引入新依赖，编码 utf-8，每次写入后 flush。
"""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# 保留的日志文件数量上限
_KEEP_LOGS = 30


class LogWriter:
    """单例式运行日志写入器（由 main.py 启动时创建一次）。"""

    def __init__(self) -> None:
        self._fh = None
        self._path: Path | None = None
        self._lock = threading.Lock()
        self._start_time = datetime.now()

    # ── 生命周期 ─────────────────────────────────────────

    def start(self, version: str, wows_type: str, bin_folder: str) -> None:
        """创建日志文件、写会话头、注册异常钩子、清理旧日志。"""
        from utils.path_utils import get_app_dir

        log_dir = get_app_dir() / "log"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            return

        fname = f"log-{self._start_time.strftime('%Y%m%d_%H%M%S')}.log"
        self._path = log_dir / fname
        try:
            self._fh = open(self._path, "a", encoding="utf-8", buffering=1)
        except Exception:  # noqa: BLE001
            self._fh = None
            return

        # 会话头
        self._write_header(version, wows_type, bin_folder)
        # 清理旧日志（在会话头写入后，避免误删本次文件）
        self._prune_old_logs(log_dir)
        # 注册异常钩子
        self._install_excepthooks()

    def close(self) -> None:
        if self._fh:
            try:
                self._fh.write(f"[{datetime.now().strftime('%H:%M:%S')}] 会话结束\n")
                self._fh.flush()
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
            self._fh = None

    # ── 写入 ─────────────────────────────────────────────

    def write(self, message: str) -> None:
        """追加一条日志（线程安全）。供 bus.log_message 槽调用。"""
        if not self._fh:
            return
        with self._lock:
            try:
                ts = datetime.now().strftime("%H:%M:%S")
                self._fh.write(f"[{ts}] {message}\n")
                self._fh.flush()
            except Exception:  # noqa: BLE001
                pass

    def write_exception(self, exc_type, exc_value, exc_tb, thread_name: str = "") -> None:
        """把完整 traceback 写入日志文件。"""
        if not self._fh:
            return
        # _ForceStop 是 kill() 注入的强制终止信号（BaseException），非真实异常，
        # 不写入日志，避免 "Exception ignored in thread" 的级联报错。
        if exc_type is not None and exc_type.__name__ == "_ForceStop":
            return
        with self._lock:
            try:
                ts = datetime.now().strftime("%H:%M:%S")
                prefix = f"[{ts}] ⚠️ 未处理异常"
                if thread_name:
                    prefix += f" (线程: {thread_name})"
                self._fh.write(prefix + "\n")
                self._fh.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
                self._fh.write("\n")
                self._fh.flush()
            except BaseException:  # noqa: BLE001  # _ForceStop 等强制终止信号也要吞掉
                pass

    # ── 内部 ─────────────────────────────────────────────

    def _write_header(self, version: str, wows_type: str, bin_folder: str) -> None:
        lines = [
            "=" * 60,
            f"  程序版本   : {version}",
            f"  启动时间   : {self._start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  服务器类型 : {wows_type or '(未设置)'}",
            f"  游戏版本   : {bin_folder or '(未设置)'}",
            f"  Python     : {sys.version.split()[0]}",
            "=" * 60,
            "",
        ]
        try:
            self._fh.write("\n".join(lines))
            self._fh.flush()
        except Exception:  # noqa: BLE001
            pass

    def _prune_old_logs(self, log_dir: Path) -> None:
        """只保留最近 _KEEP_LOGS 个 log-*.log（按文件名时间戳排序）。"""
        try:
            logs = sorted(log_dir.glob("log-*.log"), key=lambda p: p.name)
            excess = len(logs) - _KEEP_LOGS
            for p in logs[:excess] if excess > 0 else []:
                try:
                    p.unlink()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    def _install_excepthooks(self) -> None:
        writer = self

        def _hook(exc_type, exc_value, exc_tb):
            writer.write_exception(exc_type, exc_value, exc_tb, thread_name="main")
            # 同时把异常发到日志区（若 Qt 事件循环仍在运行）
            try:
                from app.signals import bus
                bus.log_message.emit(
                    f"⚠️ 未处理异常: {exc_type.__name__}: {exc_value}")
            except Exception:  # noqa: BLE001
                pass
            # 交还原默认行为（打印到 stderr）
            sys.__excepthook__(exc_type, exc_value, exc_tb)

        def _thread_hook(args):
            writer.write_exception(
                args.exc_type, args.exc_value, args.exc_traceback,
                thread_name=args.thread.name if args.thread else "")

        sys.excepthook = _hook
        threading.excepthook = _thread_hook


# 模块级单例（main.py 导入后调用 start()）
log_writer = LogWriter()
