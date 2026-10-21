"""生成「主界面主题版式」PSD，供人工在 Photoshop 里调整样式后再回填代码。

用法：
    pip install psd-tools
    python scripts/gen_ui_psd.py

输出：
    docs/ui/main-window-theme.psd   分层版式（每层对应一个主题 token / 代码位置）
    docs/ui/main-window-theme.png   同版式的 PNG 预览
    docs/ui/palette.png             当前主题色板

图层命名规则：`分区/元素`，例如 `04 详情面板/card / fill`。
在 PS 里调整完把 PSD 发回来即可，不需要自己改代码。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from psd_tools.constants import Compression  # noqa: E402

OUT_DIR = ROOT / "docs" / "ui"

# ── 版式尺寸与各区块坐标（与 1600x920 时的实际渲染一致） ──
W, H = 1600, 920
MENUBAR = (0, 0, 1600, 30)
TOOLBAR = (0, 30, 1600, 40)
BROWSER = (8, 78, 294, 698)
DETAIL = (310, 78, 1074, 698)
ART_SLOT = (1392, 78, 200, 698)
LOG = (8, 784, 1584, 100)
STATUS = (0, 892, 1600, 28)

CHAMFER = 12

FONT_PATHS = [
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),
    (r"C:\Windows\Fonts\simhei.ttf", 0),
]


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    order = (1, 0, 2) if bold else (0, 1, 2)
    for idx in order:
        path, face = FONT_PATHS[idx]
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=face)
            except Exception:  # noqa: BLE001
                pass
    return ImageFont.load_default()


def rgba(hexstr: str, alpha: float = 1.0) -> tuple[int, int, int, int]:
    """支持 `#RRGGBB` / `#RGB` / `rgba(r, g, b, a)` 两种写法（与 theme 一致）。"""
    s = hexstr.strip()
    m = re.match(r"rgba?\(([^)]*)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        r, g, b = (int(float(p)) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return (r, g, b, max(0, min(255, int(round(a * 255 * alpha)))))
    h = s.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (r, g, b, max(0, min(255, int(round(alpha * 255)))))


def solid(size: tuple[int, int], color) -> Image.Image:
    return Image.new("RGBA", size, color)


def _dashed_polyline(d, pts, color, width: int, dash: int = 6, gap: int = 5) -> None:
    """沿闭合多边形逐边画虚线（PIL 没有 dash 支持，手动切段）。"""
    closed = list(pts) + [pts[0]]
    for i in range(len(closed) - 1):
        x0, y0 = closed[i]
        x1, y1 = closed[i + 1]
        seg = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if seg <= 0:
            continue
        ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
        t = 0.0
        while t < seg:
            e = min(t + dash, seg)
            d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e)],
                   fill=color, width=width)
            t = e + gap


def chamfered(box, color, *, width: int = 1, fill=None, chamfer: int = CHAMFER,
              dash: bool = False) -> Image.Image:
    """切角矩形图层（左上/右下 45° 切角），可描边 + 填充。"""
    x, y, w, h = box
    c = min(chamfer, w // 3, h // 3)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(c, 0), (w - 1, 0), (w - 1, h - 1 - c), (w - 1 - c, h - 1),
           (0, h - 1), (0, c)]
    if fill is not None:
        d.polygon(pts, fill=fill)
    if dash:
        _dashed_polyline(d, pts, color, width)
    else:
        d.line(pts + [pts[0]], fill=color, width=width, joint="curve")
    return img


def box_layer(box, color, *, radius: int = 0, width: int = 1) -> Image.Image:
    """圆角/直角矩形（普通控件用圆角）。"""
    x, y, w, h = box
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if radius > 0:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, outline=color, width=width)
    else:
        d.rectangle([0, 0, w - 1, h - 1], outline=color, width=width)
    return img


def fill_layer(box, color, *, radius: int = 0) -> Image.Image:
    x, y, w, h = box
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if radius > 0:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=color)
    else:
        d.rectangle([0, 0, w - 1, h - 1], fill=color)
    return img


def text_layer(text: str, color, *, size: int = 12, bold: bool = False,
               pad: int = 2) -> Image.Image:
    f = font(size, bold)
    tmp = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(tmp)
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    img = Image.new("RGBA", (max(1, r - l + pad * 2), max(1, b - t + pad * 2)), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - l, pad - t), text, font=f, fill=color)
    return img


def grid_layer(size, color, step: int = 32) -> Image.Image:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(0, size[0], step):
        d.line([(x, 0), (x, size[1])], fill=color, width=1)
    for y in range(0, size[1], step):
        d.line([(0, y), (size[0], y)], fill=color, width=1)
    return img


def diamond(size: int, outline, fill) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size - 1
    pts = [(m // 2, 0), (m, m // 2), (m // 2, m), (0, m // 2)]
    d.polygon(pts, fill=fill)
    d.line(pts + [pts[0]], fill=outline, width=1)
    d.line([(m // 2, 0), (m // 2, m)], fill=outline, width=1)
    return img


# ── 生成 ────────────────────────────────────────────────────

def build(theme: dict[str, str], mode_name: str, ref_png: Path | None) -> "PSDImage":
    from psd_tools import PSDImage

    psd = PSDImage.new("RGB", (W, H), color=rgba(theme["window_bg"], 1.0)[:3])

    def group(name: str, opacity: int = 255, visible: bool = True):
        g = psd.create_group(name=name)
        g.opacity = opacity
        g.visible = visible
        g.open_folder = True
        return g

    def add(g, img: Image.Image, name: str, box) -> None:
        x, y = box[0], box[1]
        # ZIP：大块纯色图层压缩率极高，PSD 体积能小一个数量级
        g.create_pixel_layer(img, name=name, top=y, left=x,
                             compression=Compression.ZIP)

    # 00 参考 -------------------------------------------------
    if ref_png is not None and ref_png.exists():
        g = group("00 reference", opacity=45)
        add(g, Image.open(ref_png).convert("RGBA"), "reference-screenshot (deletable)", (0, 0, W, H))

    # 01 背景 -------------------------------------------------
    g = group("01 background")
    add(g, solid((W, H), rgba(theme["window_bg"])), "bg / window-bg  @window_bg@", (0, 0, W, H))
    add(g, grid_layer((W, H), rgba(theme["grid"])), "bg / grid 32px  @grid@", (0, 0, W, H))
    for i, (cx, cy) in enumerate(((26, 96), (W - 26, 96), (26, H - 130), (W - 26, H - 130))):
        add(g, diamond(22, rgba(theme["crystal_edge"]), rgba(theme["crystal"], 0.12)),
            f"bg / corner-crystal {i + 1}  @crystal@", (cx - 11, cy - 11, 22, 22))

    # 02 顶部栏 -----------------------------------------------
    g = group("02 topbar")
    add(g, solid((MENUBAR[2], MENUBAR[3]), rgba(theme["panel_alt"])),
        "topbar / menubar-bg  @panel_alt@", MENUBAR)
    add(g, solid((TOOLBAR[2], TOOLBAR[3]), rgba(theme["toolbar_bg"])),
        "topbar / toolbar-bg  @toolbar_bg@", TOOLBAR)
    add(g, solid((TOOLBAR[2], 1), rgba(theme["border_soft"])),
        "topbar / divider  @border_soft@", (0, TOOLBAR[1] + TOOLBAR[3] - 1, W, 1))
    add(g, text_layer("工具    设置    关于", rgba(theme["text"]), size=13),
        "topbar / menu-text  @text@", (18, 7, 200, 20))

    # 品牌铭牌
    add(g, chamfered((16, 38, 244, 26), rgba(theme["panel_frame"], 1.0),
                     fill=rgba(theme["toolbar_btn_bg"]), chamfer=8),
        "topbar / brand-plate  @panel_frame@", (16, 38, 244, 26))
    add(g, diamond(12, rgba(theme["crystal_edge"]), rgba(theme["crystal"], 0.25)),
        "topbar / brand-mark  @crystal@", (25, 45, 12, 12))
    add(g, text_layer("Wows Paragrams Unpack", rgba(theme["text"]), size=12, bold=True),
        "topbar / app-name  @text@", (44, 44, 200, 16))

    # 工具栏按钮（斜切薄片）
    bx = 300
    for bi, label in enumerate(("加载数据", "加载文本", "刷新界面", "穿深计算器",
                                "复制当前信息", "复制完整界面")):
        wbtn = 16 + len(label) * 13
        add(g, chamfered((bx, 36, wbtn, 30), rgba(theme["metal_mid"]),
                         fill=rgba(theme["toolbar_btn_bg"]), chamfer=9),
            f"topbar / button-{bi + 1}  SciFiButton", (bx, 36, wbtn, 30))
        add(g, text_layer(label, rgba(theme["text"]), size=12),
            f"topbar / button-text-{bi + 1}", (bx + 10, 43, wbtn - 16, 16))
        bx += wbtn + 10

    add(g, text_layer("服务器选项：  ● Lesta    ○ Wargaming", rgba(theme["text_muted"]), size=12),
        "topbar / server-select  @text_muted@", (1210, 43, 300, 16))
    add(g, chamfered((1470, 36, 84, 30), rgba(theme["metal_mid"]),
                     fill=rgba(theme["toolbar_btn_bg"]), chamfer=9),
        "topbar / button-check-update", (1470, 36, 84, 30))

    # 03 文件列表面板 -----------------------------------------
    g = group("03 file-list-panel")
    add(g, chamfered(BROWSER, rgba(theme["panel_frame"], 1.0),
                     fill=rgba(theme["panel_fill"]), width=1),
        "browser / chamfer-frame  @panel_frame@", BROWSER)
    add(g, fill_layer((20, 98, 268, 24), rgba(theme["input_bg"]), radius=4),
        "browser / search-fill  @input_bg@", (20, 98, 268, 24))
    add(g, box_layer((20, 98, 268, 24), rgba(theme["border"]), radius=4),
        "browser / search-border  @border@", (20, 98, 268, 24))
    add(g, text_layer("搜索名称或编号…", rgba(theme["text_hint"]), size=11),
        "browser / search-placeholder  @text_hint@", (28, 103, 160, 14))
    for row, (y, items) in enumerate((
        (130, ("全部国家", "全部舰种")),
        (162, ("全部等级", "本地化缺失")),
    )):
        x = 20
        for ci, it in enumerate(items):
            ci_name = f"{row + 1}-{ci + 1}"
            add(g, fill_layer((x, y, 118, 24), rgba(theme["panel_bg"]), radius=4),
                f"browser / combo-fill-{ci_name}", (x, y, 118, 24))
            add(g, box_layer((x, y, 118, 24), rgba(theme["border"]), radius=4),
                f"browser / combo-border-{ci_name}", (x, y, 118, 24))
            add(g, text_layer(it, rgba(theme["text"]), size=11),
                f"browser / combo-text-{ci_name}", (x + 8, y + 5, 100, 14))
            x += 126
    for i in range(9):
        y = 200 + i * 32
        if y + 24 > BROWSER[1] + BROWSER[3] - 20:
            break
        add(g, solid((264, 1), rgba(theme["border"])),
            f"browser / row-divider {i + 1}  @border@", (24, y + 24, 264, 1))
        add(g, text_layer(f"Ⅷ  示例舰船 {i + 1}", rgba(theme["text"]), size=12),
            f"browser / row-item {i + 1}  @text@", (32, y + 2, 200, 16))
    add(g, solid((260, 24), rgba(theme["hover_bg"])),
        "browser / row-selected-fill  @hover_bg@", (24, 200 + 32 * 3, 260, 24))
    add(g, solid((2, 24), rgba(theme["accent"])),
        "browser / row-selected-bar  @accent@", (24, 200 + 32 * 3, 2, 24))

    # 04 详情面板 ---------------------------------------------
    g = group("04 detail-panel")
    add(g, chamfered(DETAIL, rgba(theme["panel_frame_hi"], 1.0),
                     fill=rgba(theme["panel_fill"]), width=1),
        "detail / chamfer-frame  @panel_frame_hi@", DETAIL)

    # 顶部模块区
    add(g, box_layer((318, 86, 1058, 268), rgba(theme["border"])),
        "detail / modules-border  @border@", (318, 86, 1058, 268))
    for si, (name, box) in enumerate((
        ("配件", (326, 92, 232, 256)),
        ("升级品", (566, 92, 340, 256)),
        ("信号旗", (914, 92, 220, 120)),
        ("舰长技能", (1142, 92, 226, 256)),
    ), start=1):
        add(g, text_layer(name, rgba(theme["text"]), size=12, bold=True),
            f"detail / section-title-{si}  @text@", (box[0] + 4, box[1], 120, 16))
    # 图标格子（深底 + 亮边，两套主题都保持深色）
    for i in range(4):
        x = 330 + i * 56
        add(g, fill_layer((x, 116, 44, 44), rgba(theme["icon_btn_bg"]), radius=6),
            f"detail / icon-fill modules {i + 1}  @icon_btn_bg@", (x, 116, 44, 44))
        add(g, box_layer((x, 116, 44, 44), rgba(theme["icon_btn_border"]), radius=6),
            f"detail / icon-border modules {i + 1}  @icon_btn_border@", (x, 116, 44, 44))
    for i in range(7):
        x = 570 + i * 46
        add(g, fill_layer((x, 116, 40, 40), rgba(theme["icon_btn_bg"]), radius=6),
            f"detail / icon-fill upgrades {i + 1}  @icon_btn_bg@", (x, 116, 40, 40))
    for i in range(6):
        x = 920 + i * 34
        add(g, fill_layer((x, 116, 30, 30), rgba(theme["icon_btn_checked"]), radius=6),
            f"detail / icon-fill signals {i + 1}  @icon_btn_checked@", (x, 116, 30, 30))
    for r in range(3):
        for c in range(6):
            x, y = 1150 + c * 34, 150 + r * 34
            add(g, fill_layer((x, y, 30, 30), rgba(theme["icon_btn_bg"]), radius=6),
                f"detail / icon-fill skills {r + 1}-{c + 1}  @icon_btn_bg@", (x, y, 30, 30))

    # 三张卡片
    for ci2, (name, box) in enumerate((
        ("基础属性", (334, 368, 240, 336)),
        ("船体", (592, 368, 366, 336)),
        ("主炮", (972, 368, 412, 336)),
    ), start=1):
        add(g, fill_layer((box[0], box[1], box[2], 26), rgba(theme["card_bg"]), radius=6),
            f"card / title-strip-{ci2}  @card_bg@", (box[0], box[1], box[2], 26))
        add(g, box_layer((box[0], box[1], box[2], box[3]), rgba(theme["border"]), radius=6),
            f"card / border-{ci2}  @border@", box)
        add(g, text_layer(name, rgba(theme["accent"]), size=12, bold=True),
            f"card / title-{ci2}  @accent@", (box[0] + 10, box[1] + 5, 140, 16))
        for k in range(6):
            y = box[1] + 42 + k * 34
            if y + 14 > box[1] + box[3] - 12:
                break
            add(g, text_layer("属性名称", rgba(theme["text_muted"]), size=11),
                f"card / key {k + 1}-{ci2}  @text_muted@", (box[0] + 12, y, 100, 14))
            add(g, text_layer("1234.5", rgba(theme["text"]), size=11),
                f"card / value {k + 1}-{ci2}  @text@", (box[0] + box[2] - 80, y, 68, 14))

    # 05 立绘预留位 -------------------------------------------
    g = group("05 art-slot-reserved")
    add(g, chamfered(ART_SLOT, rgba(theme["accent"], 0.85),
                     fill=rgba(theme["panel_fill"], 0.6), width=2, dash=True),
        "art-slot / reserved-dashed-frame", ART_SLOT)
    add(g, text_layer("立绘预留位\n自行准备素材", rgba(theme["text_hint"]), size=11),
        "art-slot / hint-text  @text_hint@", (ART_SLOT[0] + 50, ART_SLOT[1] + ART_SLOT[3] - 60, 110, 36))

    # 06 日志面板 ---------------------------------------------
    g = group("06 log-panel")
    add(g, chamfered(LOG, rgba(theme["panel_frame_hi"], 0.9),
                     fill=rgba(theme["panel_fill_soft"]), width=1, chamfer=10),
        "log / chamfer-frame  @panel_frame@", LOG)
    add(g, text_layer("[12:00:00] 就绪  ·  日志区使用等宽字体，颜色取 @text_muted@",
                      rgba(theme["text_muted"]), size=11),
        "log / text  @text_muted@", (LOG[0] + 20, LOG[1] + 18, 900, 16))

    # 07 状态栏 -----------------------------------------------
    g = group("07 statusbar")
    add(g, solid((STATUS[2], 1), rgba(theme["border_soft"])),
        "statusbar / divider  @border_soft@", (0, STATUS[1], W, 1))
    add(g, solid((STATUS[2], STATUS[3] - 1), rgba(theme["panel_alt"])),
        "statusbar / bg  @panel_alt@", (0, STATUS[1] + 1, W, STATUS[3] - 1))
    add(g, text_layer("就绪", rgba(theme["text_muted"]), size=11),
        "statusbar / text  @text_muted@", (W - 60, STATUS[1] + 7, 40, 14))

    # 合成预览（PSD 必带的扁平图）也用 ZIP，否则整份文件会多出 4MB
    psd._record.image_data.compression = Compression.ZIP
    return psd


def palette_png(theme: dict[str, str], path: Path) -> None:
    keys = [
        ("window_bg", "窗口底"), ("panel_bg", "面板底"), ("panel_alt", "次级底"),
        ("card_bg", "card / fill"), ("border", "分隔线"), ("border_soft", "结构线"),
        ("accent", "主信号"), ("accent_hi", "主信号深"), ("accent_warm", "暖强调"),
        ("text", "主文字"), ("text_muted", "次文字"), ("text_hint", "弱提示"),
        ("hover_bg", "悬停底"), ("grid", "网格"), ("crystal", "晶体"),
        ("icon_btn_bg", "图标底"), ("icon_btn_checked", "图标选中"),
        ("value_pos", "增益"), ("value_neg", "减益"), ("warning", "警告"),
    ]
    cell_w, cell_h, cols = 240, 56, 4
    rows = (len(keys) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell_w + 20, rows * cell_h + 20),
                    rgba(theme["window_bg"])[:3])
    d = ImageDraw.Draw(img)
    for i, (key, label) in enumerate(keys):
        cx = 10 + (i % cols) * cell_w
        cy = 10 + (i // cols) * cell_h
        d.rounded_rectangle([cx, cy, cx + 56, cy + 40], radius=4, fill=rgba(theme[key])[:3],
                            outline=rgba(theme["border"])[:3])
        d.text((cx + 68, cy + 4), label, font=font(13), fill=rgba(theme["text"])[:3])
        d.text((cx + 68, cy + 22), f"{key}  {theme[key]}", font=font(11),
               fill=rgba(theme["text_muted"])[:3])
    img.save(path)


if __name__ == "__main__":
    from utils.theme import SKINS, _DARK, _LIGHT, get_skin

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ref = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    variants = [("浅色 light", _LIGHT), ("深色 dark", _DARK)]
    for sid, spec in SKINS.items():
        variants.append((f"角色主题 {sid}", spec.palette))

    for label, pal in variants:
        slug = re.sub(r"\s+", "-", label.replace("角色主题 ", "skin-").replace("浅色 light", "light")
                      .replace("深色 dark", "dark"))
        psd_path = OUT_DIR / f"main-window-{slug}.psd"
        psd = build(pal, label, ref)
        psd.save(psd_path)
        preview = psd.composite()
        preview.convert("RGB").save(OUT_DIR / f"main-window-{slug}.png")
        print("wrote", psd_path.relative_to(ROOT),
              psd_path.stat().st_size // 1024, "KB")

    palette_png(_LIGHT, OUT_DIR / "palette-light.png")
    for sid, spec in SKINS.items():
        palette_png(spec.palette, OUT_DIR / f"palette-{sid}.png")
    print("done")
