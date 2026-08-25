"""
Application —— 应用全局上下文（单例）。

作者: walksQAQ
许可证: 详见 LICENSE 文件

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

        # 启动时先做一次只读 schema 版本检查（务必在 _sync_data_state 触发
        # initialize/整库重建之前），记录不匹配信息，供主窗口启动后弹提示。
        self._schema_mismatches: list[dict] = []
        try:
            from services.database_service import check_schema_mismatches
            self._schema_mismatches = check_schema_mismatches(self._ctx.wows_type)
        except Exception:  # noqa: BLE001
            self._schema_mismatches = []

        # 启动时自动同步 game_data_state：优先检查主数据库，兼容旧版 split 数据
        self._sync_data_state()

        # ── 信号连接 ──────────────────────────────────────
        bus.wows_type_changed.connect(self._on_wows_type_changed)
        bus.game_path_changed.connect(self._on_game_path_changed)

    def _sync_data_state(self) -> None:
        """检查已入库数据是否有效，自动更新 game_data_state。"""
        split_dir = get_split_dir()
        has_data = False
        try:
            from services.database_service import get_db
            db = get_db(self._ctx.wows_type)
            has_data = db.exists and bool(db.get_latest_version_code())
        except Exception:
            pass
        if not has_data:
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

    @property
    def schema_mismatches(self) -> list[dict]:
        """启动时检测到的数据库 schema 版本不匹配列表（只读记录，供启动后提示）。"""
        return self._schema_mismatches

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

    def set_theme_mode(self, value: str) -> None:
        """切换主题模式（auto/light/dark）并保存，通知全局刷新样式。

        先刷新 theme 单例（更新 colors/dark），再广播 theme_changed，
        确保所有监听主题切换的控件在重设样式时读到的是新主题颜色，
        而不是旧主题（否则会出现“切换后仍停留在上一主题”的问题）。
        """
        self._config_manager.theme_mode = value
        self._refresh_ctx()
        from utils.theme import theme
        theme.refresh(value)
        bus.theme_changed.emit(value)

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
        # 碰撞材质映射表按服务器分文件（resources/database/{lesta|wargaming}/collision_materials.json），
        # 模块导入时只加载一次 → 切服需重载（WG 表独立演进后此步生效）
        try:
            import models.collision_materials as _cm
            _cm._EXT_MATERIALS, _cm._EXT_ZONES = _cm._load_external_material_table()
            if _cm._EXT_MATERIALS:
                _cm.COLLISION_MATERIAL_NAMES.update(_cm._EXT_MATERIALS)
            if _cm._EXT_ZONES:
                _cm.ZONE_CHINESE.update(_cm._EXT_ZONES)
        except Exception:  # noqa: BLE001
            pass

    def _on_game_path_changed(self, value: str) -> None:
        bus.log_message.emit(f"设置游戏目录: {value}")


# 全局单例 —— 整个应用唯一 Application 实例
app = Application()
