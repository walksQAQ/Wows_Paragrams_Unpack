"""app 包——应用核心组件"""
try:
    import app._resources  # noqa: F401 — 注册 Qt 资源系统（QRC）
except Exception:
    import sys
    print("[app] 警告: Qt 资源文件加载失败，部分图标和样式可能不可用", file=sys.stderr)