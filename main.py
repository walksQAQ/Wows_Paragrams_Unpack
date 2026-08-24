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

# 显式导入 QRC 编译模块，确保 Nuitka 打包时不会将其作为死代码剔除
import app._resources  # noqa: F401

# 确定应用根目录（Nuitka 打包后使用 exe 所在目录）
_app_dir = get_app_dir() if "__compiled__" in globals() else Path(__file__).resolve().parent
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))


def _apply_palette(app: QApplication, theme) -> None:
    """按主题设置应用级调色板（未显式设置 color 的控件也跟随主题）。"""
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    window = QColor(theme["window_bg"])
    panel = QColor(theme["panel_bg"])
    text = QColor(theme["text"])
    muted = QColor(theme["text_muted"])
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, panel)
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(theme["panel_alt"]))
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, panel)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.PlaceholderText, muted)
    pal.setColor(QPalette.ColorRole.Highlight, QColor(theme["selected_bg"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(theme["selected_fg"]))
    if theme.dark:
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2d2d2d"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#e8e8e8"))
        pal.setColor(QPalette.ColorRole.Link, QColor("#4da3ff"))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, muted)
    app.setPalette(pal)


def _load_qss_text() -> str | None:
    """读取 QSS 原文（优先 QRC，回退到文件系统）。"""
    from PySide6.QtCore import QFile, QIODevice
    qf = QFile(":/resources/styles/main.qss")
    if qf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
        text = str(qf.readAll(), encoding="utf-8")
        qf.close()
        return text
    style_path = get_bundled_dir() / "resources" / "styles" / "main.qss"
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def apply_theme(app: QApplication, mode: str = "auto") -> None:
    """按主题模式刷新主题状态、调色板与全局样式表。

    mode: "auto"(跟随系统) | "light" | "dark"
    """
    from utils.theme import theme
    theme.refresh(mode)
    _apply_palette(app, theme)
    qss = _load_qss_text()
    if qss is not None:
        app.setStyleSheet(theme.qss(qss))
    print(f"[main] Theme applied: mode={mode} -> {'dark' if theme.dark else 'light'}")



def _patch_tooltip() -> None:
    """全局修补 QWidget.setToolTip，自动将含 HTML 标记的文本转为富文本格式。
    
    Qt 的 tooltip 仅在文本以 '<' 开头时才启用富文本渲染，否则会将 HTML
    标签原文显示。此修补确保所有 tooltip 中的 HTML 都能正确渲染。
    """
    from PySide6.QtWidgets import QWidget
    from models.name_mapping import Mapping
    _orig_set_tooltip = QWidget.setToolTip

    def _patched_set_tooltip(self, text: str) -> None:
        if isinstance(text, str) and "<" in text and ">" in text:
            text = Mapping.rich_tooltip(text)
        _orig_set_tooltip(self, text)

    QWidget.setToolTip = _patched_set_tooltip


def _ensure_about() -> None:
    """确保 __about__.py 存在（它是 gitignore 的构建生成物）。

    新工作流下 __about__.py 由 scripts/gen_version.py 从 __about__.py.template
    + Git Tag 生成，不入库。开发模式 fresh clone / 误删后直接运行 main.py
    会因缺少该文件而崩溃，这里在导入前自动重建（与 build.bat 打包前
    调用同一脚本，行为一致）。

    Nuitka 编译模式下 __about__.py 已随构建生成并编译进二进制，
    运行时不需要也不应在 exe 目录重建（否则会往 release/ 写入空壳文件）。
    """
    # 编译模式：__about__ 已内嵌，直接跳过（避免往 exe 目录写空壳）
    if "__compiled__" in globals():
        return
    if (_app_dir / "__about__.py").exists():
        return
    template = _app_dir / "__about__.py.template"
    if template.exists():
        try:
            # 按绝对路径加载 scripts/gen_version.py，避免运行时改 sys.path
            # （Pylance 无法静态解析该导入，故用 importlib 显式加载）
            import importlib.util

            gen_path = _app_dir / "scripts" / "gen_version.py"
            spec = importlib.util.spec_from_file_location("gen_version", gen_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载版本生成脚本: {gen_path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["gen_version"] = mod
            spec.loader.exec_module(mod)
            mod.generate_version()
            return
        except Exception as e:  # noqa: BLE001
            print(f"[main] __about__.py 自动生成失败: {e}")
    # 模板也缺失（异常环境）：写最小兜底保证可启动
    try:
        (_app_dir / "__about__.py").write_text(
            '__title__ = "Wows/Korabli Paragrams Unpack"\n'
            '__version__ = "0.0.0-dev"\n'
            '__description__ = ""\n__author__ = "walksQAQ"\n'
            '__author_email__ = ""\n__url__ = ""\n'
            '__license__ = ""\n__copyright__ = ""\n'
            '__license_detail__ = ""\n',
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[main] __about__.py 兜底写入失败: {e}")


def _refresh_all_widgets_theme() -> None:
    """强制所有已存在控件重新应用当前样式，避免主题切换后部分页面停留在旧配色。"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWidgets import QWidget

    app = QApplication.instance()
    if app is None:
        return

    for widget in list(app.topLevelWidgets()):
        try:
            for child in widget.findChildren(QWidget):
                try:
                    stylesheet = child.styleSheet()
                    if stylesheet:
                        child.setStyleSheet(stylesheet)
                    child.style().unpolish(child)
                    child.style().polish(child)
                    child.update()
                except Exception:
                    pass
            stylesheet = widget.styleSheet()
            if stylesheet:
                widget.setStyleSheet(stylesheet)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        except Exception:
            pass


def main() -> None:
    # 0. 确保 __about__.py 存在（生成物缺失时从模板自动重建）
    _ensure_about()

    # 1. 创建 Qt 应用
    app = QApplication(sys.argv)
    import __about__

    app.setApplicationName(__about__.__title__)
    app.setApplicationVersion(__about__.__version__)
    app.setOrganizationName(__about__.__author__)

    # 全局修补：所有 QWidget.setToolTip 自动处理 HTML 富文本
    _patch_tooltip()

    # 初始化全局上下文（Application 单例会自动初始化）
    #    导入即触发初始化 —— Application() 在模块级别实例化
    from app.application import app as app_ctx
    from app.signals import bus

    # 运行日志文件：启动会话（log/log-YYYYMMDD_HHMMSS.log）+ 异常钩子
    from utils.log_writer import log_writer
    log_writer.start(
        version=app.applicationVersion(),
        wows_type=app_ctx.ctx.wows_type,
        bin_folder=app_ctx.ctx.bin_folder or "",
    )
    bus.log_message.connect(log_writer.write)

    # 2. 加载样式（按配置的主题模式：auto/light/dark）
    theme_mode = app_ctx.config.theme_mode
    apply_theme(app, theme_mode)

    # 4. 延迟导入主窗口，避免循环依赖
    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    # 运行时切换主题：监听 theme_changed 信号，动态刷新样式
    from PySide6.QtCore import QTimer

    def _on_theme_changed(mode: str) -> None:
        apply_theme(app, mode)
        # 通知所有已绑定内联样式的控件重新应用新主题颜色
        from utils.theme import theme as _theme
        _theme.apply_bindings()
        # 强制刷新所有现存窗口/控件，避免说明页等已创建页面停留在旧配色
        _refresh_all_widgets_theme()
        # 通知所有顶层窗口重绘
        for _w in QApplication.topLevelWidgets():
            try:
                _w.update()
            except Exception:
                pass
    bus.theme_changed.connect(_on_theme_changed)

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
            elif db.schema_rebuilt():
                # schema 版本落后 → initialize 已整库重建（旧数据被清空）
                bus.log_message.emit("⚠️ 数据库结构已更新，需要重新加载数据")
            else:
                bus.log_message.emit("ℹ️ 数据库为空，请加载数据")
        except Exception as e:
            bus.log_message.emit(f"⚠️ 数据库检查失败: {e}")

    QTimer.singleShot(200, _auto_refresh)

    # 7. 进入事件循环（退出时关闭日志文件）
    ret = app.exec()
    log_writer.close()
    sys.exit(ret)

if __name__ == "__main__":
    main()
