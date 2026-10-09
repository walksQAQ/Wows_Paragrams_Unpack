# 舰船标识（徽章）显示约定

程序内「舰船条目」统一按游戏内的写法显示：

```
[舰种标] [等级] 船名
```

例：可研发 Ⅹ 级驱逐舰 → `〔银色月桂穗 + 银色驱逐舰剪影〕 X 岛风`

## 1. 资源

| 用途 | 资源 |
|---|---|
| 舰种标（含船型装饰） | `resources/pictures/ui/ship_badges/icon_default_<舰种>_{elite,premium,special}.svg` |
| 超级战舰等级标（★） | `resources/pictures/ui/ship_badges/icon_tier_special.svg` |

原始 SVG 取自客户端 GUI 资源目录 `gui/service_kit/ship_classes_svg/`，按原样拷贝（不做描边/矢量重绘），
与既有的 `resources/pictures/ui/ship_silhouette.svg` 保持同一处理方式。

舰种 → 图标名：`Destroyer`/`Cruiser`/`Battleship`/`AirCarrier`/`Submarine`。
无对应图标（如 `Auxiliary`）时只画等级数字。

## 2. 舰种标后缀 = 船型（银/金 + 月桂穗）

后缀由 `ship_basic_info.group_status_key` 决定：

| 船型 | 后缀 | 外观 |
|---|---|---|
| 可研发（科技树） | `_elite` | **银**月桂穗 + **银**舰种剪影 |
| 加值 | `_premium` | **金**月桂穗 + **金**舰种剪影 |
| 特种（含分组未知） | `_special` | **金**月桂穗 + **银**舰种剪影 |

**除可研发与加值外，其余一律按特种显示**（`ultimate` / `specialUnsellable` / `clan` 以及任何未列出的分组）。

分组 → 船型映射（数据实测结论，Lesta 客户端**没有** `premium` 分组）：

| 船型 | `group_status_key` |
|---|---|
| 可研发 | `start`、`upgradeable`、`upgradeableExclusive`、`upgradeableUltimate`、`superShip`、`event`、`earlyAccess`、`demoWithoutStats`、`coopOnly`、`pveOnly`、`notForBattle`、`peculiar` |
| 加值 | `special`、`premium`、`demoWithoutStatsPrem`、`preserved`、`unavailable`、`disabled` |
| 特种 | 上述两组之外的一切（如 `ultimate`、`specialUnsellable`、`clan`） |

实测对照（可研发 / 加值 / 特种）：
大和·中途岛等科技树船 → `upgradeable`；武藏·密苏里·阿拉斯加·企业 → `special`；
莫斯科·雷神·斯大林格勒·斯摩棱斯克·俄亥俄·波多黎各 → `ultimate`。

## 3. 等级

* 1–10 级：罗马数字文本（I…X）绘制在舰种标右侧。
* 11 级（超级战舰）：用 ★ 图标（`icon_tier_special`），不用文本。
* **★ 按视觉等大缩放（1.3 × `capHeight()`）**：先按 2× 尺寸渲染 ★，裁掉透明边后把字形缩放到目标高度，
  字形包围盒中心对齐行中心。
  - 直接按控件尺寸缩放会明显偏小；
  - 即使包围盒高度与罗马数字相同，星形是尖角字形、墨迹集中在中部，**看上去仍偏小**，
    所以乘 1.3 的经验系数（实测 1.0/1.15 偏小、1.35 略大；客户端本身也用比字号更大的图标盒子 ≈1.16×）。
* 字号 ≈ 0.72 × 徽章高度（加粗无衬线体）；罗马数字与 ★ 的垂直居中口径一致（capHeight 居中）。

## 4. 深浅色主题

客户端 SVG 的描线是纯白（运行时才染金），直接放在浅色主题上不可见。程序内按像素重着色：

* 中性色（白/银，色差 ≤ 24）→ **银**（深色主题 `#dde0e3`、浅色主题 `#8b9197`），
  并保留抗锯齿的灰度层次（纯白 = 最亮的银）。**不用主题前景色**，否则浅色主题下徽章会变成黑标，
  与「银穗银标 / 金穗银标」不符；
* 金色保持金色，仅浅色主题下整体乘 0.72 压暗，保证白底可读。
* **等级（罗马数字 / ★）颜色随船型变化**（与游戏内一致）：可研发 = 银（同色 `_SILVER_BY_THEME`）、
  加值/特种 = 金（同色 `_GOLD_BY_THEME`）；★ 与数字同色。
* 船名仍用主题前景色，不染金/银（船型由图标与等级色体现）。

因此**徽章与主题相关**：切换主题时必须 `utils.ship_badge.clear_cache()` 后重建条目
（左侧文件列表、几何查看器舰船下拉、穿深计算器舰船下拉均已接入 `theme_changed`）。

## 5. 代码位置

* `utils/ship_badge.py`：`build_badge()` 合成 `[舰种标][等级]` 位图；`build_badge_icon()` 返回 `QIcon`；
  `icon_box()` 给出视图应设置的 `iconSize`；`_level_rgb()` 给出等级色（银/金）。
  ⚠️ `QIcon` 只缩小不放大：`iconSize` 宽度不足会把整枚徽章等比缩小（高度也随之变小），
  因此宽度需按最长等级（Ⅷ，约 1.35 × 高度）留足 —— `icon_box()` 取 2.5 × 高度。
* 使用方：`ui/browser_panel.py`（左侧文件列表）、`ui/geometry_viewer.py`、`ui/penetration_calculator.py`。

## 6. 条目文本与复制

列表/下拉的**文本字段只放船名**，图标一律走图标通道（`QListWidgetItem.setIcon` / `QComboBox.addItem(icon, …)`），
不再把 `📄` 之类的装饰字符拼进文本 —— 否则复制名称时会连装饰字符一起被带走。

**船名**不染金/银（用主题前景色），船型由徽章与等级颜色体现。
