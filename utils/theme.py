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

科幻重设计新增（全息指挥台风格）：
  @accent@ @accent_hi@ @on_accent@   交互 / 选中信号色（lime），唯一交互色
  @warn@ @danger@ @info@             警示 / 错误 / 信息
  @surface_2@ @inset@ @line_strong@  三级色阶与强描边
  @hud@                              面板四角 HUD 短线
  @holo_ice@ @holo_glow@             全息顶部高光 / 聚焦外辉光（不得表示交互态）
  @spark_pearl@ @spark_violet@       昔涟点缀（仅 5 处固定位置）
  @holo_panel@                       全息面板半透明底
注：旧 token 一律为不透明 hex（会被 QColor / matplotlib 直接解析）；
    新 token 可能是 rgba()，在 Python 里请用 theme.qcolor(key)。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

# ── 深浅两套颜色定义 ──────────────────────────────────────

_LIGHT = {
    # ── PRISM CORE · 亮色版（规范只给了深色，这边按同色相提亮推导）──
    "window_bg":   "#F2F6FA",                 # bg-primary
    "panel_bg":    "#FFFFFF",                 # bg-surface
    "panel_alt":   "#E8EFF6",                 # bg-secondary
    "input_bg":    "#F7FAFD",                 # inset
    "text":        "#0D1B26",                 # text-primary
    "text_muted":  "#4A5F73",                 # text-secondary
    "text_hint":   "#7C8FA0",                 # text-muted
    "border":      "#C9D8E4",                 # line-subtle
    "border_soft": "#A8C2D6",                 # line-structure
    "hover_bg":    "#EAF2FB",                 # photon-blue 8% 预混
    "selected_bg": "#2E6FB0",                 # photon-blue（亮色需压深保对比）
    "selected_fg": "#FFFFFF",                 # on_accent
    "scroll_bg":   "rgba(0, 0, 0, 0.04)",
    "scroll_handle": "rgba(46, 111, 176, 0.22)",
    "scroll_handle_hover": "rgba(46, 111, 176, 0.40)",
    # 工具栏
    "toolbar_bg":        "#E8EFF6",
    "toolbar_btn_bg":    "#FFFFFF",
    "toolbar_btn_hover": "#EAF2FB",
    "toolbar_btn_border": "#C9D8E4",
    "toolbar_btn_text":  "#0D1B26",
    "toolbar_btn_disabled": "#EEF3F8",
    "toolbar_text":      "#0D1B26",
    "toolbar_text_muted": "#7C8FA0",
    # ── 语义色 ──
    "accent":       "#2E6FB0",                # photon-blue：焦点 / 主交互
    "accent_hi":    "#1E5A9E",
    "on_accent":    "#FFFFFF",
    "warn":         "#A35A00",                # state-warning
    "danger":       "#B3243C",                # state-error
    "info":         "#2F6FD0",                # photon-blue / state-info
    "success":      "#0E7A5A",                # state-success
    "warning":      "#A35A00",
    "error":        "#B3243C",
    "photon_blue":  "#2F6FD0",
    "photon_violet": "#6B5BB5",
    "crystal":      "#3E7FA8",                 # 晶体折射色（浅色主题下用钢蓝，不用紫）
    "crystal_edge": "#2B6A93",
    "surface_2":    "#F7FAFD",                # bg-elevated
    "elevated":     "#F7FAFD",
    "inset":        "#F7FAFD",
    "line_strong":  "#A8C2D6",                # line-structure
    "line_structure": "#8FB0CC",
    "hud":          "rgba(46, 111, 176, 0.50)",
    "holo_ice":     "rgba(46, 111, 176, 0.16)",
    "holo_glow":    "rgba(46, 111, 176, 0.22)",
    "spark_pearl":  "#0D1B26",
    "spark_violet": "#6B5BB5",
    "holo_panel":   "rgba(248, 251, 254, 0.55)",
    "grid":         "rgba(46, 111, 176, 0.16)",
    # ── 银色金属 + 蓝色光线（浅色）──
    "metal_hi":     "#FFFFFF",
    "metal_mid":    "#C7D3DE",
    "metal_lo":     "#8FA0B0",
    "metal_edge":   "rgba(120, 145, 170, 0.55)",
    "metal_glow":   "rgba(90, 150, 200, 0.10)",
    "metal_sheen_a": "rgba(255, 255, 255, 0.85)",
    "metal_sheen_b": "rgba(170, 190, 210, 0.30)",
    "metal_brush":  "rgba(110, 140, 170, 0.08)",
    "light_core":   "rgba(46, 118, 190, 0.92)",
    "light_halo":   "rgba(62, 140, 214, 0.22)",
    # ── 参考图对齐（浅色）──
    "accent_warm":    "#B87315",
    "accent_warm_hi": "#D68910",
    "panel_frame":      "rgba(70, 122, 182, 0.55)",
    "panel_frame_hi":   "rgba(42, 100, 168, 0.90)",
    "panel_fill":       "rgba(255, 255, 255, 0.72)",
    "panel_fill_soft":  "rgba(245, 250, 254, 0.60)",
    "card_bg":          "#FFFFFF",
    # ── 图标按钮（浅色主题下底色同样保持深色，保证白图标可读）──
    "gold":        "#A35A00",
    "gold_hi":     "#C47300",
    "gold_bg":     "#FBF1DE",
    "gold_border": "#D8A24B",
    "value_pos":   "#0E7A5A",
    "value_neg":   "#B3243C",
    "tip_text":    "#0D1B26",
    "tip_muted":   "#3B4F63",
    "tip_dim":     "#5E7186",
    "tip_rule":    "#C9D8E4",
    # ── 图标按钮（浅色主题下底色同样保持深色，保证白图标可读）──
    # 与深色主题同一策略：深底 + 亮蓝描边；绝不能用中间明度蓝做选中底。
    "icon_btn_bg":        "#1A3155",
    "icon_btn_bg_hover":  "#2F5D8E",
    "icon_btn_checked":   "#12467A",
    "icon_btn_border":    "#3F639B",
    "icon_btn_border_hi": "#7FC3F0",
    "icon_btn_text":      "#DCE9F4",
    "icon_btn_text_dim":  "#93A9BE",
    "icon_btn_text_hi":   "#A8D8FA",
}


_DARK = {
    # ── PRISM CORE · 深色（参考图配色：深海军蓝 + 冰蓝光线 + 橙黄强调）──
    "window_bg":   "#070F1C",                 # 深海军蓝底（不用纯黑）
    "panel_bg":    "#0C1A2E",                 # 面板底
    "panel_alt":   "#091422",                 # 次级区域
    "input_bg":    "#0A1626",                 # 凹陷输入底
    "text":        "#DCEAF7",                 # 主文字（冷白）
    "text_muted":  "#8CA6C2",                 # 次要说明
    "text_hint":   "#5A7290",                 # 弱化提示
    "border":      "#1B3350",                 # 普通分隔线
    "border_soft": "#2C5478",                 # 结构线
    "hover_bg":    "#13293F",                 # 悬停底
    "selected_bg": "#4FD8F2",
    "selected_fg": "#06131A",
    "scroll_bg":   "rgba(255, 255, 255, 0.03)",
    "scroll_handle": "rgba(79, 216, 242, 0.22)",
    "scroll_handle_hover": "rgba(79, 216, 242, 0.40)",
    # 工具栏
    "toolbar_bg":        "#091422",
    "toolbar_btn_bg":    "#0A1626",
    "toolbar_btn_hover": "#13293F",
    "toolbar_btn_border": "#1B3350",
    "toolbar_btn_text":  "#DCEAF7",
    "toolbar_btn_disabled": "#091422",
    "toolbar_text":      "#DCEAF7",
    "toolbar_text_muted": "#5A7290",
    # ── 语义色 ──
    "accent":       "#4FD8F2",                # 冰蓝：焦点 / 主交互
    "accent_hi":    "#8CEAFF",
    "on_accent":    "#04121C",
    "warn":         "#FFB454",                # 橙黄：关键数值 / 警告
    "danger":       "#FF6E88",
    "info":         "#6C9DFF",
    "success":      "#5FE8B8",
    "warning":      "#FFB454",
    "error":        "#FF6E88",
    "photon_blue":  "#5B9BE8",
    "photon_violet": "#9B8CFF",
    "crystal":      "#8FB8FF",                # 晶体折射色
    "crystal_edge": "#7FE3FF",
    # 参考图里被强调的数字用暖色，与冰蓝主色形成对比（不是把所有文字都染蓝）
    "accent_warm":    "#FFB454",
    "accent_warm_hi": "#FFD08A",
    "surface_2":    "#122640",
    "elevated":     "#122640",
    "inset":        "#0A1626",
    "line_strong":  "#2C5478",
    "line_structure": "#3E93C8",
    # 面板轮廓：参考图是 1px 青色细线，不是粗金属框
    "panel_frame":      "rgba(96, 198, 242, 0.88)",
    "panel_frame_hi":   "rgba(140, 226, 255, 0.92)",
    "panel_fill":       "rgba(13, 33, 58, 0.82)",
    "panel_fill_soft":  "rgba(16, 38, 66, 0.62)",
    "card_bg":          "#0C1A2E",
    "hud":          "rgba(79, 216, 242, 0.50)",
    "holo_ice":     "rgba(79, 216, 242, 0.22)",
    "holo_glow":    "rgba(79, 216, 242, 0.28)",
    "spark_pearl":  "#DCEAF7",
    "spark_violet": "#9B8CFF",
    "holo_panel":   "rgba(10, 26, 46, 0.72)",
    "grid":         "rgba(90, 180, 220, 0.075)",
    # ── 银色金属 + 蓝色光线（深色）──
    "metal_hi":     "#C8DCEC",
    "metal_mid":    "#7E9CB8",
    "metal_lo":     "#3A5470",
    "metal_edge":   "rgba(120, 170, 210, 0.45)",
    "metal_glow":   "rgba(110, 190, 235, 0.18)",
    "metal_sheen_a": "rgba(150, 200, 238, 0.10)",
    "metal_sheen_b": "rgba(70, 110, 150, 0.03)",
    "metal_brush":  "rgba(160, 205, 240, 0.04)",
    "light_core":   "rgba(120, 226, 250, 0.95)",
    "light_halo":   "rgba(60, 170, 220, 0.30)",
    # ── 图标按钮（技能 / 升级品 / 信号旗 / 模块）──
    # 游戏图标是「白色图形 + 透明底」，因此这层底色在深浅两套主题下都保持深色，
    # 让白图标始终有足够对比度，不随主题变亮而消失。
    # 强化 / 传奇技能：琥珀金强调
    "gold":        "#FFC24D",
    "gold_hi":     "#FFD98A",
    "gold_bg":     "#2A2113",
    "gold_border": "#8A6520",
    # 属性增减值
    "value_pos":   "#5FE8B8",
    "value_neg":   "#FF6E88",
    # 富文本 tooltip 用色
    "tip_text":    "#DCEAF7",
    "tip_muted":   "#A8BED4",
    "tip_dim":     "#7A90A8",
    "tip_rule":    "#2C5478",
    # ── 图标按钮（技能 / 升级品 / 信号旗 / 模块）──
    # 游戏图标是「单色浅色图形 + 透明底」，只有在深色底上才对比清楚。
    # 因此这层底色在深浅两套主题下都保持深色；选中态用「更深的蓝 + 亮青描边」，
    # 而不是中间明度的青色——后者会让白图标几乎看不见。
    "icon_btn_bg":        "#0F2033",
    "icon_btn_bg_hover":  "#1E3E5C",
    "icon_btn_checked":   "#0B4C6E",
    "icon_btn_border":    "#31536F",
    "icon_btn_border_hi": "#8AF0FF",
    "icon_btn_text":      "#C6DAEC",
    "icon_btn_text_dim":  "#8199B2",
    "icon_btn_text_hi":   "#9AF3FF",
}


_SKIN_CYRENE = {
    # ── 角色皮肤 · 昔涟（白 + 粉）：白为底，粉只做装饰与交互信号 ──
    "window_bg":   "#FBF7FC",                 # 带一丝藕荷的白
    "panel_bg":    "#FFFFFF",                 # 面板纯白，保证数据区可读
    "panel_alt":   "#F8F0F9",                 # 次级区域
    "input_bg":    "#FDF9FE",                 # 输入框
    "text":        "#382A4A",                 # 主文字（深藕紫）
    "text_muted":  "#756286",                 # 次要说明
    "text_hint":   "#A091AF",                 # 弱提示
    "border":      "#EFE4F3",                 # 普通分隔线
    "border_soft": "#DECDE8",                 # 结构线
    "hover_bg":    "#F9EFF8",                 # 悬停底
    "selected_bg": "#C2557C",                 # 樱粉（白底上压深保对比）
    "selected_fg": "#FFFFFF",
    "scroll_bg":   "rgba(194, 85, 124, 0.06)",
    "scroll_handle": "rgba(194, 85, 124, 0.24)",
    "scroll_handle_hover": "rgba(194, 85, 124, 0.42)",
    # 工具栏
    "toolbar_bg":        "#F8F0F9",
    "toolbar_btn_bg":    "#FFFFFF",
    "toolbar_btn_hover": "#F9EFF8",
    "toolbar_btn_border": "#EFE4F3",
    "toolbar_btn_text":  "#382A4A",
    "toolbar_btn_disabled": "#F5ECF7",
    "toolbar_text":      "#382A4A",
    "toolbar_text_muted": "#A091AF",
    # ── 语义色 ──
    "accent":       "#C2557C",                # 樱粉：焦点 / 主交互（对白 4.6:1）
    "accent_hi":    "#A8436A",
    "on_accent":    "#FFFFFF",
    "warn":         "#A96A1C",
    "danger":       "#C4395F",                # 偏玫红，仍与主色区分
    "info":         "#7B79C9",                # 长春花蓝
    "success":      "#2F8F6E",
    "warning":      "#A96A1C",
    "error":        "#C4395F",
    "photon_blue":  "#8990D9",                # 官方长春花蓝
    "photon_violet": "#A87BC4",
    "crystal":      "#B98BD0",                # 水晶：藕荷紫（官方 #C195D6 系）
    "crystal_edge": "#8E86D4",                # 折射棱：长春花蓝
    "accent_warm":    "#B0734F",              # 关键数值用玫瑰金，与粉紫拉开
    "accent_warm_hi": "#C98A63",
    "surface_2":    "#FDF9FE",
    "elevated":     "#FFFFFF",
    "inset":        "#FDF9FE",
    "line_strong":  "#DECDE8",
    "line_structure": "#D5BEDF",
    # 面板轮廓：1px 樱粉细线 + 外侧极弱粉辉
    "panel_frame":      "rgba(232, 132, 170, 0.52)",
    "panel_frame_hi":   "rgba(200, 92, 134, 0.88)",
    "panel_fill":       "rgba(255, 255, 255, 0.62)",
    "panel_fill_soft":  "rgba(252, 246, 253, 0.50)",
    # 卡片底特意留一点透明：大尺度底纹要能透过面板与卡片显出来
    "card_bg":          "rgba(255, 255, 255, 0.70)",
    "hud":          "rgba(235, 126, 163, 0.48)",
    "holo_ice":     "rgba(235, 126, 163, 0.15)",
    "holo_glow":    "rgba(235, 126, 163, 0.24)",
    "spark_pearl":  "#382A4A",
    "spark_violet": "#C195D6",
    "holo_panel":   "rgba(255, 251, 253, 0.62)",
    "grid":         "rgba(200, 92, 134, 0.13)",
    # ── 冷银金属（她的饰品是银质，不是金色）+ 粉光 ──
    "metal_hi":     "#FFFFFF",
    "metal_mid":    "#DCD6E4",
    "metal_lo":     "#A99DB5",
    "metal_edge":   "rgba(166, 150, 180, 0.55)",
    "metal_glow":   "rgba(224, 142, 178, 0.12)",
    "metal_sheen_a": "rgba(255, 255, 255, 0.92)",
    "metal_sheen_b": "rgba(226, 205, 232, 0.30)",
    "metal_brush":  "rgba(178, 160, 192, 0.08)",
    "light_core":   "rgba(235, 126, 163, 0.92)",
    "light_halo":   "rgba(216, 150, 196, 0.22)",
    # ── 强化 / 传奇技能：暖金（识别性优先，不跟主题走）──
    "gold":        "#C08A2E",
    "gold_hi":     "#D9A445",
    "gold_bg":     "#FDF3E3",
    "gold_border": "#E3BC7A",
    # 属性增减值
    "value_pos":   "#2F8F6E",
    "value_neg":   "#C4395F",
    # 富文本 tooltip 用色
    "tip_text":    "#382A4A",
    "tip_muted":   "#6A566F",
    "tip_dim":     "#8E7C9A",
    "tip_rule":    "#DECDE8",
    # ── 图标按钮：深藕紫底，白色游戏图标才不会糊在浅色背景上 ──
    "icon_btn_bg":        "#3A2C52",
    "icon_btn_bg_hover":  "#58417A",
    "icon_btn_checked":   "#4A2C63",
    "icon_btn_border":    "#6B4E86",
    "icon_btn_border_hi": "#FFA9CF",
    "icon_btn_text":      "#F1E7F5",
    "icon_btn_text_dim":  "#BBA6C9",
    "icon_btn_text_hi":   "#FFC6E0",
}


# ─────────────────────────────────────────────────────────────
#  角色皮肤注册表
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SkinSpec:
    """一套「角色皮肤」的注册信息。

    皮肤与 auto/light/dark **正交**：主题模式决定深浅，皮肤决定一整套配色与
    装饰语言。皮肤是整份调色板（覆盖明暗），所以启用皮肤时 ``theme.dark``
    恒为 False。

    以后加新的二次元主题（别的角色 / 别的世界观），只需往 :data:`SKINS` 里
    补一条，界面各处都按下面的**能力位**走，不必再改控件代码：

    ``brand``      品牌标识形态（"crystal" 棱晶 / "heart" 心形）
    ``watermark``  工作区背景水印（"" 无 / "mobius" 莫比乌斯环 …）
    ``art_slot``   是否启用右侧立绘装饰列
    ``art_files``  ``data/skins/`` 下的约定文件名，按顺序探测
    """

    id: str
    name: str
    palette: dict[str, str]
    brand: str = "crystal"
    watermark: str = ""
    art_slot: bool = False
    art_files: tuple[str, ...] = ()


SKINS: dict[str, SkinSpec] = {
    "cyrene": SkinSpec(
        id="cyrene",
        name="昔涟（半成品）",
        palette=_SKIN_CYRENE,
        brand="heart",
        watermark="mobius",
        art_slot=True,
        art_files=("cyrene.png", "cyrene.webp", "cyrene.jpg", "cyrene.jpeg"),
    ),
}


def skin_ids() -> tuple[str, ...]:
    """皮肤 id 列表（保持注册顺序，供设置界面生成下拉项）。"""
    return tuple(SKINS)


def get_skin(skin_id: str) -> SkinSpec | None:
    """按 id 取皮肤定义；未知 id 返回 None（等同「不启用皮肤」）。"""
    return SKINS.get(skin_id or "")


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
    """当前主题单例：持有深浅标志、皮肤与颜色表，提供 qss() 占位符替换。

    两层正交：**深浅模式**（auto / light / dark）与**角色皮肤**（见 :data:`SKINS`）。
    启用皮肤时它接管整份调色板，因此 ``dark`` 恒为 False。
    """

    #: 内置皮肤 id 集合（"auto"/"light"/"dark" 之外的取值都当皮肤处理）
    def __init__(self) -> None:
        self.mode: str = "auto"  # "auto" | "light" | "dark" | <skin id>
        self.skin: SkinSpec | None = None
        self.dark: bool = detect_dark_mode(self.mode)
        self.colors: dict[str, str] = dict(_DARK if self.dark else _LIGHT)
        # 已绑定控件的内联样式模板：[(weakref, template), ...]
        self._bindings: list[tuple] = []

    @property
    def skin_id(self) -> str:
        """当前皮肤 id；未启用皮肤时为空串。"""
        return self.skin.id if self.skin else ""

    def _palette(self) -> dict[str, str]:
        """按当前模式选调色板。皮肤是完整调色板，不参与系统深浅检测。"""
        self.skin = get_skin(self.mode) if self.mode not in ("auto", "light", "dark") else None
        if self.skin is not None:
            return self.skin.palette
        return _DARK if self.dark else _LIGHT

    def refresh(self, mode: str | None = None) -> None:
        """重新检测主题。

        mode 参数："auto" | "light" | "dark" | <皮肤 id>，传入后持久化到
        self.mode；不传则沿用当前模式。
        """
        if mode is not None and (mode in ("auto", "light", "dark") or mode in SKINS):
            self.mode = mode
        self.dark = detect_dark_mode(self.mode)
        self.colors = dict(self._palette())

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
        # ⚠️ 通用 UI 控件图标（resources/pictures/ui/，如 check_checked/combo_arrow）**不分服**，
        # 保持公共路径 :/resources/pictures/ui/...；仅重写服务器特定目录（modules/consumables/…）。
        # 延迟 import 避免循环依赖；无图片引用的 QSS 直接跳过。
        if ":/resources/pictures/" in out:
            from utils.image_paths import pic_dir
            _PIC_UI_GUARD = "\x00PIC_UI_GUARD\x00"
            out = out.replace(":/resources/pictures/ui/", _PIC_UI_GUARD)
            out = out.replace(":/resources/pictures/", f":/resources/pictures/{pic_dir()}/")
            out = out.replace(_PIC_UI_GUARD, ":/resources/pictures/ui/")
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

    def palette_name(self) -> str:
        """当前生效的调色板名：light / dark / <皮肤 id>。"""
        if self.skin is not None:
            return self.skin.id
        return "dark" if self.dark else "light"

    # ── 皮肤能力位（未启用皮肤时回落到中性值） ──

    @property
    def brand_style(self) -> str:
        """品牌标识形态："crystal"（棱晶）/ "heart"（心形）…"""
        return self.skin.brand if self.skin else "crystal"

    @property
    def watermark_style(self) -> str:
        """工作区背景水印形态：""（无）/ "mobius" …"""
        return self.skin.watermark if self.skin else ""

    @property
    def uses_art_slot(self) -> bool:
        """当前皮肤是否启用右侧立绘装饰列。"""
        return bool(self.skin and self.skin.art_slot)

    def qcolor(self, key: str):
        """返回 token 对应的 QColor（支持 rgba(r, g, b, a) 写法，a 为 0–1 浮点）。"""
        from PySide6.QtGui import QColor
        val = self.colors.get(key, key).strip()
        if val.startswith("rgba(") and val.endswith(")"):
            parts = [p.strip() for p in val[5:-1].split(",")]
            r, g, b = (int(float(x)) for x in parts[:3])
            a = float(parts[3]) if len(parts) > 3 else 1.0
            return QColor(r, g, b, max(0, min(255, round(a * 255))))
        return QColor(val)

    # ── 全息效果总开关（网格 / 辉光 / 呼吸 / 扫描 / 昔涟点缀）──
    holo_enabled: bool = True

    def set_holo(self, enabled: bool) -> None:
        self.holo_enabled = bool(enabled)


# 全局单例 —— 各 UI 文件统一从 utils.theme 导入
theme = _Theme()
