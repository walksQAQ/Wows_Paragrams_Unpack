"""
SignalBus —— 全局信号总线（单例模式）。

职责：
  - 集中管理所有跨模块通信信号
  - 替代旧代码中函数回调 + tkinter after() 的混乱模式
  - 所有信号在主线程发射，自动保证线程安全（Qt 机制）

使用方式：
  from app.signals import bus
  bus.log_message.emit("你好")
  bus.log_message.connect(self.on_log)
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class SignalBus(QObject):
    """全局信号总线，所有通信信号在此定义"""

    # ── 日志 ──────────────────────────────────────────────
    log_message = pyqtSignal(str)

    # ── 状态变更 ──────────────────────────────────────────
    data_loaded = pyqtSignal(str)           # 参数: 版本号
    data_processed = pyqtSignal(bool)       # 参数: 成功/失败
    localization_ready = pyqtSignal()       # 本地化文件就绪

    # ── 进度 ──────────────────────────────────────────────
    task_progress = pyqtSignal(int, str)    # 参数: 百分比, 消息

    # ── 浏览器 / 导航 ────────────────────────────────────
    folder_selected = pyqtSignal(str)       # 参数: 分类名
    file_selected = pyqtSignal(str, str)    # 参数: 分类名, 文件名(不含.json)

    # ── 配置变更 ──────────────────────────────────────────
    wows_type_changed = pyqtSignal(str)     # 参数: "Wargaming" | "Lesta"
    game_path_changed = pyqtSignal(str)     # 参数: 新路径

    # ── 按钮状态 ──────────────────────────────────────────
    # 用于统一控制 sidebar 按钮的启用/禁用
    can_process_data = pyqtSignal(bool)


# 全局单例 —— 整个应用共用这一个信号总线对象
bus = SignalBus()
