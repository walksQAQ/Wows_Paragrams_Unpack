"""
ConfigManager —— 统一的配置读写模块。

职责：
  - 读取 / 写入 config.json
  - 提供类型安全的字段访问
  - 自动合并默认值与已有配置
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from utils.path_utils import get_config_path


@dataclass
class AppConfig:
    """应用配置数据类"""
    game_path: str = "未设置"
    game_version: str = "Unknown"
    game_data_state: bool = False
    wows_type: str = "未选择"   # "Wargaming" | "Lesta" | "未选择"
    keep_split_json: bool = True  # 解析后是否保留 split JSON 文件
    bin_folder: str = ""  # 游戏 bin 子版本号（如 3859335）

    @classmethod
    def default(cls) -> AppConfig:
        return cls()


class ConfigManager:
    """JSON 配置文件管理器"""

    def __init__(self, config_path: Optional[Path] = None):
        self._path = config_path or get_config_path()
        self._config: AppConfig = self._load()

    # ── 属性访问代理 ──────────────────────────────────────

    @property
    def game_path(self) -> str:
        return self._config.game_path

    @game_path.setter
    def game_path(self, value: str) -> None:
        self._config.game_path = value
        self.save()

    @property
    def game_version(self) -> str:
        return self._config.game_version

    @game_version.setter
    def game_version(self, value: str) -> None:
        self._config.game_version = value
        self.save()

    @property
    def game_data_state(self) -> bool:
        return self._config.game_data_state

    @game_data_state.setter
    def game_data_state(self, value: bool) -> None:
        self._config.game_data_state = value
        self.save()

    @property
    def wows_type(self) -> str:
        return self._config.wows_type

    @wows_type.setter
    def wows_type(self, value: str) -> None:
        self._config.wows_type = value
        self.save()

    @property
    def keep_split_json(self) -> bool:
        return self._config.keep_split_json

    @keep_split_json.setter
    def keep_split_json(self, value: bool) -> None:
        self._config.keep_split_json = value
        self.save()

    @property
    def bin_folder(self) -> str:
        return self._config.bin_folder

    @bin_folder.setter
    def bin_folder(self, value: str) -> None:
        self._config.bin_folder = value
        self.save()

    # ── 供 Application 内部使用 ─────────────────────────

    @property
    def _raw(self) -> AppConfig:
        """直接返回内部 dataclass（仅供 Application 使用）"""
        return self._config

    # ── 读写方法 ──────────────────────────────────────────

    def _load(self) -> AppConfig:
        """从磁盘加载配置，缺失字段用默认值填充"""
        default = AppConfig.default()
        if not self._path.exists():
            self._write(default)
            return default

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return default
            # 只取 dataclass 定义的字段，抛弃多余字段
            valid_keys = {f.name for f in default.__dataclass_fields__.values()}
            filtered = {k: v for k, v in raw.items() if k in valid_keys}
            # 用 default 的字段值补全缺失项
            merged = asdict(default) | filtered
            return AppConfig(**merged)
        except Exception as e:
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 加载配置失败: {e}")
            print(f"加载配置失败: {e}")
            return default

    def save(self) -> None:
        """将当前配置写回磁盘"""
        self._write(self._config)

    def _write(self, config: AppConfig) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(asdict(config), f, indent=4, ensure_ascii=False)
        except Exception as e:
            from app.signals import bus
            bus.log_message.emit(f"⚠️ 保存配置失败: {e}")
            print(f"保存配置失败: {e}")

    def reset(self) -> None:
        """重置为默认配置"""
        self._config = AppConfig.default()
        self.save()
