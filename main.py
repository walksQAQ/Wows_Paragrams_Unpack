"""
Wows Paragrams Unpack —— 战舰世界数据提取/分析工具

PySide6 重构版入口。

启动流程：
  1. 初始化 QApplication
  2. 初始化全局应用上下文（Application 单例）
  3. 加载全局样式表
  4. 创建并显示主窗口

作者: walksQAQ
仓库: https://github.com/walksQAQ/Wows_Paragrams_Unpack
许可证: 详见项目根目录 LICENSE 文件
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from utils.path_utils import get_app_dir, get_bundled_dir

# 确定应用根目录（Nuitka 打包后使用 exe 所在目录）
_app_dir = get_app_dir() if "__compiled__" in globals() else Path(__file__).resolve().parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


def load_stylesheet(app: QApplication) -> None:
    """加载 QSS 样式表（可选）"""
    # resources/ 是打包内置资源，用 get_bundled_dir() 定位
    style_path = get_bundled_dir() / "resources" / "styles" / "main.qss"
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())


def main() -> None:
    # 1. 创建 Qt 应用
    app = QApplication(sys.argv)
    import __about__

    app.setApplicationName(__about__.__title__)
    app.setApplicationVersion(__about__.__version__)
    app.setOrganizationName(__about__.__author__)

    # 2. 加载样式
    load_stylesheet(app)

    # 3. 初始化全局上下文（Application 单例会自动初始化）
    #    导入即触发初始化 —— Application() 在模块级别实例化
    from app.application import app as app_ctx
    from app.signals import bus

    # 4. 延迟导入主窗口，避免循环依赖
    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    # 5. 启动时写入一条日志
    bus.log_message.emit(f"应用启动 | 应用版本: {app.applicationVersion()}")
    bus.log_message.emit(f"数据目录: {app_ctx.ctx.data_dir}")
    bus.log_message.emit(f"当前服务器: {app_ctx.ctx.wows_type}")

    # 6. 启动后自动刷新（如果已有可用数据库）
    from PySide6.QtCore import QTimer

    def _auto_refresh():
        try:
            from services.database_service import get_db
            server = app_ctx.ctx.wows_type
            db = get_db(server)
            if not db.exists:
                return
            stats = db.get_stats()
            if stats.get("total_entities", 0) > 0:
                bus.folder_selected.emit("__REFRESH__")
                bus.log_message.emit(
                    f"🔄 加载数据库 [{server}]: {db.db_path.name} "
                    f"({stats['total_entities']} 实体)")
                bus.can_process_data.emit(True)
                # 刷新完成后重新选中舰船大类
                QTimer.singleShot(0, lambda: bus.folder_selected.emit("Ship"))
            else:
                bus.log_message.emit("ℹ️ 数据库为空，请加载数据")
        except Exception as e:
            bus.log_message.emit(f"⚠️ 数据库检查失败: {e}")

    QTimer.singleShot(200, _auto_refresh)

    # 7. 进入事件循环
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
