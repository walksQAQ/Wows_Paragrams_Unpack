"""renderer —— D3D11 渲染后端的 Python 前端。

职责边界（见 ``todo_list/New_function_of_d3d11_renderer.md`` §2）：

- 本包向上提供「与后端无关」的渲染调用面（相机、场景描述、材质描述）；
- 向下只通过纯 C ABI（``ctypes``）与 ``wows_renderer.dll`` 交互；
- **不**在本包内感知 D3D11 资源、状态对象、pass 调度等实现细节。

P0 仅含 :mod:`renderer.api`（句柄生命周期 + 帧驱动）。
P1+ 将加入 ``scene.py`` / ``texture.py`` / ``viewport.py``，P6 加入 ``material.py`` / ``mfm_parser.py``。
"""

from __future__ import annotations

from .api import (
    WSR_OK,
    Renderer,
    RendererError,
    RendererUnavailable,
    Stats,
    find_library,
    is_available,
)

__all__ = [
    "WSR_OK",
    "Renderer",
    "RendererError",
    "RendererUnavailable",
    "Stats",
    "find_library",
    "is_available",
]
