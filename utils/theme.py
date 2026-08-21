"""主题管理 —— 跟随系统深浅色主题。

设计目标：
  应用当前大量界面颜色硬编码为浅色。本模块提供一个集中式主题源：

    theme.dark          → bool，当前是否为深色主题
    theme.qss(template) → 将模板中的 @var@ 占位符替换为当前主题颜色
    theme.colors        → dict，当前主题全部颜色

用法（QSS/内联样式中使用占位符，保持 QSS 的 {} 花括号不受影响）：

    from utils import theme
    style = theme.qss('''
        QLabel { color: @text@; }
        QPushButton { background: @panel_bg@; color: @text@;
                      border: 1px solid @border@; }
    ''')
    widget.setStyleSheet(style)

占位符（颜色语义）：
  @window_bg@   主窗口/对话框背景
  @panel_bg@    面板/卡片背景
  @panel_alt@   次级面板背景（hover/交替行）
  @input_bg@    输入框/编辑控件背景
  @text@        主文字
  @text_muted@  次要文字
  @text_hint@   弱提示文字
  @border@      主边框
  @border_soft@ 浅边框
  @hover_bg@    悬停背景
  @selected_bg@ 选中背景
  @selected_fg@ 选中前景（文字）
  @scroll_bg@   滚动条轨道
  @scroll_handle@ 滚动条滑块
  @scroll_handle_hover@ 滚动条滑块悬停
"""

from __future__ import annotations

import os
import sys

# ── 深浅两套颜色定义 ──────────────────────────────────────

_LIGHT = {
    "window_bg":   "#f5f5f5",
    "panel_bg":    "#ffffff",
    "panel_alt":   "#f0f0f0",
    "input_bg":    "#ffffff",
    "text":        "#1a1a1a",
    "text_muted":  "#555555",
    "text_hint":   "#888888",
    "border":      "#d0d0d0",
    "border_soft": "#e0e0e0",
    "hover_bg":    "#e5f1fb",
    "selected_bg": "#0078d4",
    "selected_fg": "#ffffff",
    "scroll_bg":   "rgba(0, 0, 0, 0.05)",
    "scroll_handle": "rgba(0, 0, 0, 0.15)",
    "scroll_handle_hover": "rgba(0, 0, 0, 0.25)",
    # 工具栏（浅色主题 = 浅色工具栏 + 深色文字）
    "toolbar_bg":        "#f0f0f0",
    "toolbar_btn_bg":    "#ffffff",
    "toolbar_btn_hover": "#e5f1fb",
    "toolbar_btn_border": "#d0d0d0",
    "toolbar_btn_text":  "#1a1a1a",
    "toolbar_btn_disabled": "#e8e8e8",
    "toolbar_text":      "#333333",
    "toolbar_text_muted": "#888888",
}

_DARK = {
    "window_bg":   "#1e1e1e",
    "panel_bg":    "#252526",
    "panel_alt":   "#2d2d2d",
    "input_bg":    "#2d2d2d",
    "text":        "#e0e0e0",
    "text_muted":  "#9a9a9a",
    "text_hint":   "#777777",
    "border":      "#3c3c3c",
    "border_soft": "#333333",
    "scroll_bg":   "rgba(255, 255, 255, 0.06)",
    "scroll_handle": "rgba(255, 255, 255, 0.18)",
    "scroll_handle_hover": "rgba(255, 255, 255, 0.30)",
    "hover_bg":    "#094771",
    "selected_bg": "#0078d4",
    "selected_fg": "#ffffff",
    # 工具栏（深色主题 = 深色工具栏 + 浅色文字）
    "toolbar_bg":        "#2b2b2b",
    "toolbar_btn_bg":    "#3a3a3a",
    "toolbar_btn_hover": "#4a4a4a",
    "toolbar_btn_border": "#555555",
    "toolbar_btn_text":  "#ffffff",
    "toolbar_btn_disabled": "#2a2a2a",
    "toolbar_text":      "#e0e0e0",
    "toolbar_text_muted": "#8a8a8a",
}


def detect_dark_mode(mode: str = "auto") -> bool:
    """检测是否应使用深色主题。

    参数：
      mode = "auto"  → 跟随系统（环境变量 WPU_THEME 可强制覆盖，用于调试）
             "dark"  → 强制深色
             "light" → 强制浅色

    优先级（auto 时）：
      1. 环境变量 WPU_THEME=dark|light 强制指定（调试/演示用）
      2. Qt 的 colorScheme（最准确，随系统实时变化）
      3. Windows 注册表（未创建 QApplication 时的回退）
    """
    # 0) 显式指定模式（优先于环境变量与系统检测）
    if mode == "dark":
        return True
    if mode == "light":
        return False
    # 1) 环境变量强制指定（可覆盖系统设置，调试用）
    forced = os.environ.get("WPU_THEME", "").strip().lower()
    if forced in ("dark", "1", "true", "yes"):
        return True
    if forced in ("light", "0", "false", "no"):
        return False
    # 2) Qt 已就绪：使用 QStyleHints.colorScheme()
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt
        app = QGuiApplication.instance()
        if app is not None:
            scheme = app.styleHints().colorScheme()
            if scheme is not None:
                return scheme == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        pass
    # 3) Windows 注册表回退（无需 Qt）
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
        except Exception:  # noqa: BLE001
            pass
    return False


class _Theme:
    """当前主题单例：持有 dark 标志与颜色表，提供 qss() 占位符替换。"""

    def __init__(self) -> None:
        self.mode: str = "auto"  # "auto" | "light" | "dark"
        self.dark: bool = detect_dark_mode(self.mode)
        self.colors: dict[str, str] = dict(_DARK if self.dark else _LIGHT)
        # 已绑定控件的内联样式模板：[(weakref, template), ...]
        self._bindings: list[tuple] = []

    def refresh(self, mode: str | None = None) -> None:
        """重新检测主题。

        mode 参数："auto" | "light" | "dark"，传入后持久化到 self.mode；
        不传则沿用当前模式。
        """
        if mode is not None and mode in ("auto", "light", "dark"):
            self.mode = mode
        self.dark = detect_dark_mode(self.mode)
        self.colors = dict(_DARK if self.dark else _LIGHT)

    def set_mode(self, mode: str) -> None:
        """显式设置主题模式并立即刷新颜色表。"""
        self.refresh(mode)

    def qss(self, template: str) -> str:
        """将模板中 @var@ 占位符替换为当前主题颜色；图片路径按服务器目录重写。"""
        # N35: 一次遍历替换全部 key（避免 ~30 次 .replace 全量扫描）
        out = template
        for key, value in self.colors.items():
            placeholder = "@" + key + "@"
            out = out.replace(placeholder, value)
        # 应用内图片按服务器目录（lesta/wargaming）重写 QSS 中的图片引用（如 combo_arrow）。
        # 延迟 import 避免循环依赖；无图片引用的 QSS 直接跳过。
        if ":/resources/pictures/" in out:
            from utils.image_paths import pic_dir
            out = out.replace(":/resources/pictures/", f":/resources/pictures/{pic_dir()}/")
        return out

    def bind(self, widget, template: str) -> str:
        """设置控件内联样式并注册模板，主题切换时自动重算。

        用法（替代 widget.setStyleSheet(theme.qss(template))）：
            theme.bind(widget, \"\"\"... QSS ...\"\"\")
        返回渲染后的样式字符串。
        """
        rendered = self.qss(template)
        try:
            widget.setStyleSheet(rendered)
            import weakref
            self._bindings.append((weakref.ref(widget), template))
        except Exception:  # noqa: BLE001
            pass
        return rendered

    def apply_bindings(self) -> None:
        """重新应用所有已绑定控件的内联样式（主题切换后调用）。"""
        import weakref
        keep: list[tuple] = []
        for ref, template in self._bindings:
            w = ref()
            if w is None:
                continue
            try:
                w.setStyleSheet(self.qss(template))
                keep.append((ref, template))
            except Exception:  # noqa: BLE001
                pass
        self._bindings = keep

    # 便捷访问单个颜色
    def __getitem__(self, key: str) -> str:
        return self.colors[key]


# 全局单例 —— 各 UI 文件统一从 utils.theme 导入
theme = _Theme()
