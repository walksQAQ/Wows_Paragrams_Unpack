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
from utils.theme import skin_ids


@dataclass
class AppConfig:
    """应用配置数据类"""
    # 各服务器独立保存的游戏安装路径（"未设置" 表示未配置）
    game_path_lesta: str = "未设置"
    game_path_wargaming: str = "未设置"
    game_version: str = "Unknown"
    game_data_state: bool = False
    wows_type: str = "未选择"   # "Wargaming" | "Lesta" | "未选择"
    keep_split_json: bool = False  # 解析后是否保留 split JSON 文件
    bin_folder: str = ""  # 游戏 bin 子版本号（如 <bin目录名>）
    theme_mode: str = "auto"  # "auto"(跟随系统) | "light" | "dark" | <皮肤 id>(如 cyrene)
    auto_check_update: bool = True   # 启动时自动检测 GitHub 新版本
    include_prerelease: bool = False  # 版本检测是否把 pre-release 视为可更新版本

    # 资源解包器（UnpackerDialog）的**独立**记录：与主程序的 game_path_* 完全分离，
    # 主程序切换服务器/改路径不会影响解包器上次使用的目录。
    unpacker_game_path: str = ""
    unpacker_bin_folder: str = ""
    unpacker_output_dir: str = ""

    # ── 游戏路径（按当前服务器动态解析） ──────────────────
    @property
    def game_path(self) -> str:
        """当前选中服务器对应的游戏安装路径。"""
        if self.wows_type == "Wargaming":
            return self.game_path_wargaming
        if self.wows_type == "Lesta":
            return self.game_path_lesta
        # 未选择服务器：返回任一已设置路径（优先 Lesta）
        if self.game_path_lesta and self.game_path_lesta != "未设置":
            return self.game_path_lesta
        return self.game_path_wargaming

    def set_server_path(self, server: str, value: str) -> bool:
        """写入指定服务器的游戏路径；服务器不明确时不写入，返回是否写入。

        只接受明确的 ``"Wargaming"`` / ``"Lesta"``：旧实现把其它取值（如
        ``wows_type == "未选择"``）一律落到 ``game_path_lesta``，会把另一服
        客户端的目录写进 Lesta 槽位。
        """
        if server == "Wargaming":
            self.game_path_wargaming = value
            return True
        if server == "Lesta":
            self.game_path_lesta = value
            return True
        return False

    @staticmethod
    def _path_valid(path: str) -> bool:
        """路径字段是否有效（非空且未用「未设置」占位）。"""
        return bool(path) and path != "未设置"

    def is_path_set(self, server: str) -> bool:
        """指定服务器是否已设置有效路径。

        当 server 为「未选择」时，任一服务器已设置路径即视为可用，
        避免首次启动未选服务器时因只检查单一路径而误判为不可用。
        """
        if server == "Wargaming":
            return self._path_valid(self.game_path_wargaming)
        if server == "Lesta":
            return self._path_valid(self.game_path_lesta)
        return self._path_valid(self.game_path_lesta) or self._path_valid(self.game_path_wargaming)

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
        # 写入当前选中服务器（wows_type）对应的专用路径字段；
        # 未选择服务器时不写入（避免误写某一服的槽位）
        self.set_server_path(self._config.wows_type, value)

    @property
    def game_path_lesta(self) -> str:
        return self._config.game_path_lesta

    @game_path_lesta.setter
    def game_path_lesta(self, value: str) -> None:
        self._config.game_path_lesta = value
        self.save()

    @property
    def game_path_wargaming(self) -> str:
        return self._config.game_path_wargaming

    @game_path_wargaming.setter
    def game_path_wargaming(self, value: str) -> None:
        self._config.game_path_wargaming = value
        self.save()

    def set_server_path(self, server: str, value: str) -> None:
        """为指定服务器设置游戏路径并保存（服务器不明确时不写入、不落盘）。"""
        if self._config.set_server_path(server, value):
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

    @property
    def theme_mode(self) -> str:
        return self._config.theme_mode

    @theme_mode.setter
    def theme_mode(self, value: str) -> None:
        if value not in ("auto", "light", "dark") and value not in skin_ids():
            value = "auto"
        self._config.theme_mode = value
        self.save()

    @property
    def auto_check_update(self) -> bool:
        return self._config.auto_check_update

    @auto_check_update.setter
    def auto_check_update(self, value: bool) -> None:
        self._config.auto_check_update = bool(value)
        self.save()

    @property
    def include_prerelease(self) -> bool:
        return self._config.include_prerelease

    @include_prerelease.setter
    def include_prerelease(self, value: bool) -> None:
        self._config.include_prerelease = bool(value)
        self.save()

    # ── 资源解包器独立记录 ───────────────────────────────

    @property
    def unpacker_game_path(self) -> str:
        return self._config.unpacker_game_path

    @unpacker_game_path.setter
    def unpacker_game_path(self, value: str) -> None:
        self._config.unpacker_game_path = str(value or "")
        self.save()

    @property
    def unpacker_bin_folder(self) -> str:
        return self._config.unpacker_bin_folder

    @unpacker_bin_folder.setter
    def unpacker_bin_folder(self, value: str) -> None:
        self._config.unpacker_bin_folder = str(value or "")
        self.save()

    @property
    def unpacker_output_dir(self) -> str:
        return self._config.unpacker_output_dir

    @unpacker_output_dir.setter
    def unpacker_output_dir(self, value: str) -> None:
        self._config.unpacker_output_dir = str(value or "")
        self.save()

    # ── 供 Application 内部使用 ─────────────────────────

    @property
    def _raw(self) -> AppConfig:
        """直接返回内部 dataclass（仅供 Application 使用）"""
        return self._config

    # ── 读写方法 ──────────────────────────────────────────

    @staticmethod
    def _migrate_legacy_paths(raw: dict) -> dict:
        """把旧版 config.json 的单一 game_path 迁移到对应服务器的专用路径字段。

        仅当旧配置里只有 game_path（没有服务器专用路径字段）时执行迁移，
        避免覆盖用户后来分别设置的两条路径。迁移目标按旧 wows_type 判定。
        """
        if "game_path_lesta" in raw or "game_path_wargaming" in raw:
            return raw  # 已是新格式，无需迁移
        legacy = raw.get("game_path")
        if not legacy:
            return raw
        if raw.get("wows_type", "未选择") == "Wargaming":
            raw["game_path_wargaming"] = legacy
        else:
            raw["game_path_lesta"] = legacy
        return raw

    @staticmethod
    def _migrate_legacy_skin(raw: dict) -> dict:
        """迁移早期的皮肤命名：theme_mode="anime" -> 皮肤 id（cyrene）。"""
        mode = str(raw.get("theme_mode", "") or "")
        if mode and mode not in ("auto", "light", "dark") and mode not in skin_ids():
            # 旧的 "anime" 就是第一套皮肤（昔涟）
            raw["theme_mode"] = "cyrene" if mode == "anime" else "auto"
        raw.pop("anime_art", None)
        raw.pop("skin_art", None)
        return raw

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
            # 旧版配置迁移：把单一 game_path 拆到对应服务器的专用路径字段
            raw = self._migrate_legacy_paths(raw)
            # 旧版皮肤命名迁移（anime -> cyrene），并清掉已废弃的立绘字段
            raw = self._migrate_legacy_skin(raw)
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
