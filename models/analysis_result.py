"""
数据模型 —— 所有分析器返回的统一数据结构。

使分析器（analyzers/）与渲染器（ui/renderers/）完全解耦。
分析器只负责把 JSON 原始数据转换成这些 dataclass，
渲染器只负责把这些 dataclass 绘制到 UI 上。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DataItem:
    """单个数据条目"""
    name: str               # 字段名（已翻译，如"主炮射程"）
    value: str              # 格式化后的值（如"18.3 km"）
    raw_value: Any = None   # 原始数值（可选，供高级渲染用）
    unit: str = ""          # 单位（如"km", "s", "%"）
    order: int = 0          # 排序权重

    def __lt__(self, other: DataItem) -> bool:
        return self.order < other.order


@dataclass
class DataSection:
    """数据区段，包含一组相关条目"""
    label: str               # 区段标题（如"基础属性", "加成效果"）
    items: list[DataItem] = field(default_factory=list)

    def sorted_items(self) -> list[DataItem]:
        return sorted(self.items, key=lambda x: x.order)


@dataclass
class AnalysisResult:
    """分析器统一返回类型"""
    title: str                        # 主标题（如舰船/武器名称）
    subtitle: str = ""                 # 副标题（如编号/ID）
    sections: list[DataSection] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)   # 扩展字段

    def add_section(self, section: DataSection) -> None:
        self.sections.append(section)

    def add_item(self, section_label: str, item: DataItem) -> None:
        """向指定区段添加条目（自动创建区段）"""
        for sec in self.sections:
            if sec.label == section_label:
                sec.items.append(item)
                return
        self.sections.append(DataSection(label=section_label, items=[item]))
