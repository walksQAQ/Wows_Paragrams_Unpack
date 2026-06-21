"""
Application —— 应用全局上下文（单例）。

职责：
  1. 统一管理全局状态（AppContext）
  2. 协调 ConfigManager、SignalBus 的初始化
  3. 提供便捷的顶层操作方法（加载、处理、本地化）
  4. 确保 Nuitka 打包后一切正常运转

使用方式：
  from app.application import app
  app.config.game_path = "D:/Game"
  app.ctx.wows_type  # "Wargaming" | "Lesta"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject

from app.config import ConfigManager, AppConfig
from app.signals import bus
from utils.path_utils import get_app_dir, get_data_dir, get_split_dir


@dataclass
class AppContext:
    """不可变的应用上下文（由 Application 管理更新）"""
    exe_dir: Path = field(default_factory=get_app_dir)
    data_dir: Path = field(default_factory=get_data_dir)
    split_dir: Path = field(default_factory=get_split_dir)
    config: AppConfig = field(default_factory=AppConfig.default)

    @property
    def wows_type(self) -> str:
        return self.config.wows_type

    @property
    def game_path(self) -> str:
        return self.config.game_path

    @property
    def game_version(self) -> str:
        return self.config.game_version

    @property
    def game_data_state(self) -> bool:
        return self.config.game_data_state

    @property
    def keep_split_json(self) -> bool:
        return self.config.keep_split_json

    @property
    def bin_folder(self) -> str:
        return self.config.bin_folder


class Application(QObject):
    """应用单例 —— 全局唯一的上下文持有者"""

    def __init__(self):
        super().__init__()
        self._config_manager = ConfigManager()
        self._ctx = AppContext(config=self._config_manager._raw)

        # 启动时自动同步 game_data_state：检查 split 目录是否有数据
        self._sync_data_state()

        # ── 信号连接 ──────────────────────────────────────
        bus.wows_type_changed.connect(self._on_wows_type_changed)
        bus.game_path_changed.connect(self._on_game_path_changed)

    def _sync_data_state(self) -> None:
        """检查 split 目录是否有效，自动更新 game_data_state"""
        split_dir = get_split_dir()
        has_data = split_dir.exists() and any(split_dir.iterdir())
        if has_data != self._ctx.game_data_state:
            self._config_manager.game_data_state = has_data
            self._refresh_ctx()

    # ── 属性 ──────────────────────────────────────────────

    @property
    def ctx(self) -> AppContext:
        return self._ctx

    @property
    def config(self) -> ConfigManager:
        return self._config_manager

    # ── 便捷方法 ──────────────────────────────────────────

    def set_wows_type(self, value: str) -> None:
        """切换服务器类型并保存"""
        self._config_manager.wows_type = value
        self._refresh_ctx()
        bus.wows_type_changed.emit(value)

    def set_game_path(self, value: str) -> None:
        """设置游戏目录并保存"""
        self._config_manager.game_path = value
        self._refresh_ctx()
        bus.game_path_changed.emit(value)

    def set_game_version(self, value: str) -> None:
        self._config_manager.game_version = value
        self._refresh_ctx()

    def set_game_data_state(self, value: bool) -> None:
        self._config_manager.game_data_state = value
        self._refresh_ctx()
        bus.can_process_data.emit(value)

    def set_bin_folder(self, value: str) -> None:
        self._config_manager.bin_folder = value
        self._refresh_ctx()

    def reset_all(self) -> None:
        """重置所有配置"""
        self._config_manager.reset()
        self._refresh_ctx()

    def _refresh_ctx(self) -> None:
        """使 ctx 中的 config 引用指向最新数据"""
        self._ctx.config = self._config_manager._raw

    # ── 信号槽 ────────────────────────────────────────────

    def _on_wows_type_changed(self, value: str) -> None:
        bus.log_message.emit(f"切换服务器: {value}")

    def _on_game_path_changed(self, value: str) -> None:
        bus.log_message.emit(f"设置游戏目录: {value}")


# 全局单例 —— 整个应用唯一 Application 实例
app = Application()
