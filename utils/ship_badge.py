"""utils/ship_badge.py —— 舰船标识徽章（舰种 + 船型 + 等级）渲染。

与游戏内保持一致（Unbound2 的 ``shipinfo_elements.unbound``）：

    排列：[舰种标] [等级罗马数字（或 ★）] 船名

* 舰种标 = ``icon_default_<舰种><后缀>``，后缀由**船型**决定：
    - ``_elite``   —— 可研发（已完成研发：**银月桂穗 + 银舰种剪影**）
    - ``_premium`` —— 加值（**金月桂穗 + 金舰种剪影**）
    - ``_special`` —— 特种（**金月桂穗 + 银舰种剪影**）

  除可研发与加值外**一律按特种显示**（含分组未知的船）。
* 等级 = 罗马数字文本（I…X）；超级战舰（11 级）用 ★ 图标 ``icon_tier_special``。

资源为客户端原生 SVG，放在 ``resources/pictures/ui/ship_badges/``。
深浅色主题下都会把「中性色（白/银）」描线重着色为主题前景色，
浅色主题下再压暗金色，保证两种主题下都可读。切换主题需调用 :func:`clear_cache`。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPixmap

from models.name_mapping import Mapping as NM
from utils.theme import theme

# ── 资源定位 ─────────────────────────────────────────────

_QRC_DIR = ":/resources/pictures/ui/ship_badges"

#: 舰种（shiptype）→ 客户端图标名
CLASS_ICON_NAME: dict[str, str] = {
    "Destroyer": "destroyer",
    "Cruiser": "cruiser",
    "Battleship": "battleship",
    "AirCarrier": "aircarrier",
    "Submarine": "submarine",
}

#: 船型分组 → 图标后缀
_ELITE_GROUPS = frozenset({
    "start", "upgradeable", "upgradeableExclusive", "upgradeableUltimate",
    "superShip", "event", "earlyAccess", "demoWithoutStats",
    "coopOnly", "pveOnly", "notForBattle", "peculiar",
})
_PREMIUM_GROUPS = frozenset({
    "special", "premium", "demoWithoutStatsPrem", "preserved",
    "unavailable", "disabled",
})

#: 船型分组 → 中文类型名（供 tooltip / 文本显示）
GROUP_TYPE_LABEL: dict[str, str] = {
    "elite": "可研发",
    "premium": "加值",
    "special": "特种",
}


def group_type(group: str | None) -> str:
    """船型分组 → ``"elite"`` / ``"premium"`` / ``"special"``。

    只有可研发与加值保留各自外观，**其余（含分组未知）一律按特种**。
    """
    g = (group or "").strip()
    if g in _ELITE_GROUPS:
        return "elite"
    if g in _PREMIUM_GROUPS:
        return "premium"
    return "special"


def _asset_path(name: str) -> str:
    """徽章 SVG 路径：优先 QRC（打包/正常启动），回退磁盘（裸源码测试）。"""
    from PySide6.QtCore import QFile  # noqa: PLC0415
    qrc = f"{_QRC_DIR}/{name}.svg"
    if QFile(qrc).exists():
        return qrc
    from pathlib import Path  # noqa: PLC0415
    disk = Path(__file__).resolve().parent.parent / "resources" / "pictures" / "ui" / "ship_badges" / f"{name}.svg"
    return str(disk)


# ── 着色 ─────────────────────────────────────────────────

#: 客户端 SVG 里的描线是纯白（月桂穗/舰种剪影）：在浅色背景上不可见，
#: 因此重新着色为「银」。深色主题用亮银，浅色主题用中银（仍可读且不偏黑）。
_SILVER_BY_THEME = {"dark": (0xDD, 0xE0, 0xE3), "light": (0x8B, 0x91, 0x97)}
#: 金色：客户端 SVG 原色 #FFCC66；浅色主题下同比例压暗，保证白底可读。
_GOLD_BY_THEME = {"dark": (0xFF, 0xCC, 0x66), "light": (0xB7, 0x92, 0x49)}
#: ★ 相对罗马数字字面高度（capHeight）的缩放：星形是尖角字形，
#: 即便包围盒高度相同，视觉上仍明显偏小；客户端也用比字号更大的图标盒子（≈1.16×）。
#: 取 1.3 是目视等大的实测值（1.0/1.15 偏小，1.35 略大）。
_STAR_SCALE = 1.3


def _level_rgb(kind: str) -> tuple[int, int, int]:
    """等级（罗马数字 / ★）颜色：与游戏内一致 —— 可研发 = 白/银，加值、特种 = 金。"""
    dark = "dark" if theme.dark else "light"
    return _GOLD_BY_THEME[dark] if kind in ("premium", "special") else _SILVER_BY_THEME[dark]


def _adapt_image(img: QImage, neutral: tuple[int, int, int] | None = None) -> QImage:
    """把中性色（白/银）像素重着色，浅色主题下压暗金色。

    特种标 = 金穗 + 银标（SVG 里穗为金色、标为白色）；
    可研发标 = 银穗 + 银标（整个 SVG 都是白色）；加值标 = 全金。
    neutral：中性色替换成的颜色；默认银色（舰种标的剪影用），★ 会传入等级色。
    """
    if neutral is None:
        neutral = _SILVER_BY_THEME["dark" if theme.dark else "light"]
    sr, sg, sb = neutral
    for y in range(img.height()):
        for x in range(img.width()):
            px = img.pixelColor(x, y)
            a = px.alpha()
            if a == 0:
                continue
            r, g, b = px.red(), px.green(), px.blue()
            neutral_px = max(r, g, b) - min(r, g, b) <= 24
            if neutral_px:
                # 保留抗锯齿的灰度层次（纯白 = 最亮的实色）
                lum = (r + g + b) / 3.0 / 255.0
                img.setPixelColor(x, y, QColor(sr, sg, sb, int(round(a * max(lum, 0.35)))))
            elif not theme.dark:
                # 浅色主题：金色压暗，避免白底看不清
                img.setPixelColor(x, y, QColor(int(r * 0.72), int(g * 0.72), int(b * 0.72), a))
    return img


def _render_svg(name: str, size: int, neutral: tuple[int, int, int] | None = None) -> QImage | None:
    """渲染 SVG 为 ARGB32 图像（尺寸 size×size）。"""
    if size <= 0:
        return None
    icon = QIcon(_asset_path(name))
    if icon.isNull():
        return None
    pm = icon.pixmap(QSize(size, size))
    if pm.isNull():
        return None
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return _adapt_image(img, neutral)


def _alpha_bbox(img: QImage) -> tuple[int, int, int, int] | None:
    """图像中非透明像素的包围盒 (x, y, w, h)；全透明返回 None。"""
    min_x, min_y, max_x, max_y = img.width(), img.height(), -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 8:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < 0:
        return None
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def _crop_scaled(img: QImage, target_h: int) -> QImage | None:
    """裁掉透明边并等比缩放到目标**字形**高度（用于 ★ 与罗马数字对齐）。"""
    bbox = _alpha_bbox(img)
    if bbox is None:
        return None
    x, y, w, h = bbox
    cropped = img.copy(x, y, w, h)
    if target_h <= 0 or h <= 0:
        return cropped
    target_w = max(1, int(round(w * target_h / h)))
    return cropped.scaled(target_w, target_h, Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)


# ── 徽章合成 ─────────────────────────────────────────────

_cache: dict[tuple, QPixmap] = {}


def clear_cache() -> None:
    """清空徽章缓存（切换主题后调用，重新按新主题着色）。"""
    _cache.clear()


def level_text(tier: int | None) -> str:
    """等级 → 罗马数字文本；11 级（超级战舰）返回 ``"★"``，未知返回 ``""``。"""
    try:
        t = int(tier)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if 0 < t < len(NM.LEVEL_MAP):
        return NM.LEVEL_MAP[t]
    return ""


def build_badge(ship_class: str | None, tier: int | None, group: str | None = None,
                icon_size: int = 20) -> QPixmap | None:
    """合成「[舰种标] [等级]」徽章；无可用信息时返回 None。

    Args:
        ship_class: ``shiptype``，如 ``"Destroyer"``（``None``/未知则只画等级）。
        tier:       等级 1..10（11 = 超级战舰画 ★，字形按视觉等大缩放）。
        group:      ``group_status_key``（决定可研发/加值/特种外观与等级颜色）。
        icon_size:  舰种标边长（px）；等级（罗马数字/★）字高约 0.72×。
    """
    kind = group_type(group)
    text = level_text(tier)
    is_star = text == "★"
    key = (ship_class, int(tier or 0), group, icon_size, theme.dark)
    cached = _cache.get(key)
    if cached is not None:
        return cached if not cached.isNull() else None

    icon_name = CLASS_ICON_NAME.get(ship_class or "", "")
    class_img = None
    if icon_name:
        suffix = {"elite": "_elite", "premium": "_premium", "special": "_special"}.get(kind, "_special")
        class_img = _render_svg(f"icon_default_{icon_name}{suffix}", icon_size)

    level_px = max(10, int(round(icon_size * 0.72)))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(level_px)
    fm = QFontMetrics(font)
    cap_h = max(1, fm.capHeight())

    # ★：先按大字号渲染再裁到字形包围盒，按 capHeight × _STAR_SCALE 缩放并中心对齐
    # （直接按控件尺寸缩放会让 ★ 明显偏小；同高度包围盒也仍显小，故乘视觉系数）
    star_img = None
    if is_star:
        raw = _render_svg("icon_tier_special", max(icon_size * 2, 24),
                          neutral=_level_rgb(kind))
        star_img = (_crop_scaled(raw, max(1, int(round(cap_h * _STAR_SCALE))))
                    if raw is not None else None)

    if class_img is None and not text:
        _cache[key] = QPixmap()  # 空标记：避免重复尝试
        return None

    gap = 2
    if star_img is not None:
        level_w = star_img.width()
    elif text:
        level_w = fm.horizontalAdvance(text)
    else:
        level_w = 0

    class_w = class_img.width() if class_img is not None else 0
    total_w = class_w + (gap if class_w and level_w else 0) + level_w
    height = max(icon_size, cap_h, star_img.height() if star_img is not None else 0)
    center_y = height / 2.0

    pm = QPixmap(total_w, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    x = 0
    if class_img is not None:
        p.drawImage(x, int(round(center_y - class_img.height() / 2.0)), class_img)
        x += class_w + (gap if level_w else 0)
    if star_img is not None:
        # 字形包围盒中心对齐行中心（与罗马数字的 capHeight 居中一致）
        p.drawImage(x, int(round(center_y - star_img.height() / 2.0)), star_img)
    elif text:
        p.setFont(font)
        p.setPen(QColor(*_level_rgb(kind)))
        # 基线 = 行中心 + capHeight/2 → 字面（全部大写）视觉居中
        p.drawText(QPointF(x, center_y + cap_h / 2.0), text)
    p.end()

    if pm.isNull():
        _cache[key] = QPixmap()
        return None
    _cache[key] = pm
    return pm


def build_badge_icon(ship_class: str | None, tier: int | None, group: str | None = None,
                     icon_size: int = 20) -> QIcon:
    """给 ``QListWidgetItem`` / ``QComboBox`` 用的 QIcon 版本（无徽章时返回空 QIcon）。"""
    pm = build_badge(ship_class, tier, group, icon_size=icon_size)
    return QIcon(pm) if pm is not None else QIcon()


def icon_box(icon_size: int) -> QSize:
    """视图/下拉应设置的 ``iconSize``。

    QIcon 只会**缩小**不会放大：徽章比 iconSize 宽时会被整体缩小（高度也变小），
    所以宽度必须留足（最长等级罗马数字 VIII 约 1.35×icon_size + 舰种标）。
    """
    return QSize(int(round(icon_size * 2.5)), icon_size)


def type_label(ship_class: str | None, tier: int | None, group: str | None) -> str:
    """徽章对应的可读描述，如 ``「可研发 X 级驱逐舰」``（供 tooltip 用）。"""
    cls = NM.SHIP_CLASS_MAP.get(ship_class or "", "")
    lvl = level_text(tier)
    kind = GROUP_TYPE_LABEL.get(group_type(group), "")
    parts = [p for p in (kind, lvl and f"{lvl} 级", cls) if p]
    return " ".join(parts)
