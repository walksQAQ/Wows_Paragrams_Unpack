"""
分析器基类 —— 所有分析器的公共父类。

职责：
  1. 统一管理 JSON 映射表的加载
  2. 提供日志回调机制
  3. 定义 analyze() 接口契约
  4. Nuitka 兼容的路径解析

所有具体的分析器（Ship、Projectile、Gun 等）都应继承此类。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject

from utils.path_utils import get_data_dir
from models.analysis_result import AnalysisResult


class BaseAnalyzer(QObject):
    """分析器基类"""

    def __init__(self, log_func: Optional[Callable[[str], None]] = None):
        super().__init__()
        self._log_func = log_func
        self._data_dir: Path = get_data_dir()
        # 所有子类共享此字典存储映射表
        self._mappings: dict[str, dict] = {}

    # ── 映射表管理 ────────────────────────────────────────

    def load_json_mapping(self, filename: str) -> dict:
        """加载 data/ 下的 JSON 映射文件，返回 {key: value} 字典"""
        path = self._data_dir / filename
        if not path.exists():
            self._log(f"映射文件不存在: {path}")
            return {}

        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self._log(f"加载映射文件 {filename} 失败: {e}")
            return {}

    def initialize_mapping(self) -> None:
        """
        子类重写此方法，在此加载所有需要的映射表。
        在应用启动和语言文件重新加载后调用。
        """
        raise NotImplementedError

    # ── 分析接口 ──────────────────────────────────────────

    def analyze(self, raw_data: dict) -> AnalysisResult:
        """
        将 JSON 原始数据解析为 AnalysisResult。

        子类必须重写此方法。
        返回纯数据结构，不涉及任何 UI 操作。
        """
        raise NotImplementedError

    # ── 日志 ──────────────────────────────────────────────

    def _log(self, message: str) -> None:
        if self._log_func:
            self._log_func(message)
        else:
            print(f"[{self.__class__.__name__}] {message}")

    def set_log_func(self, log_func: Callable[[str], None]) -> None:
        self._log_func = log_func
