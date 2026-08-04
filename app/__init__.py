"""app 包——应用核心组件"""
# 源码模式下启动时自动检查并重编译 QRC 资源（_resources.py），
# 避免修改 resources/ 后仍加载过期内嵌资源（如 no such table: XXX）。
# 编译模式（Nuitka）下 ensure_qrc_fresh 内部直接跳过；失败也不影响启动。
try:
    from utils.qrc_rebuilder import ensure_qrc_fresh
    ensure_qrc_fresh()
except Exception:
    pass

try:
    import app._resources  # noqa: F401 — 注册 Qt 资源系统（QRC）
except Exception:
    import sys
    print("[app] 警告: Qt 资源文件加载失败，部分图标和样式可能不可用", file=sys.stderr)