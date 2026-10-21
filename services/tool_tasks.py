"""可以在**子进程**里执行的工具任务（模块级函数，参数/返回值均可 pickle）。

这些函数的唯一目的是把独立工具的 CPU 密集解析搬出主进程，让主界面在加载
模型/索引时保持流畅。子进程里没有 Qt 事件循环，因此这里不能碰任何 Qt 对象，
也不能依赖父进程的内存缓存（提取器等需在子进程内自行构建）。
"""

from __future__ import annotations

from typing import Any


def parse_geometry_file(path: str) -> Any:
    """读本地 .geometry 文件并解析（子进程）。"""
    from models.geometry_parser import parse_geometry

    with open(path, "rb") as f:
        data = f.read()
    return parse_geometry(data, file_path=path)


def parse_geometry_bytes(data: bytes, file_path: str) -> Any:
    """解析已解压的字节流（子进程）。

    用于「父进程只负责 I/O / pkg 解压，CPU 密集解析交给子进程」的二段式流程。
    """
    from models.geometry_parser import parse_geometry

    return parse_geometry(data, file_path=file_path)
