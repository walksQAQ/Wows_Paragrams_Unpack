"""舰船提速模型 —— 引擎功率 → 阻力系数 → 航速曲线。

模型与验证：``docs/korabli-ship-acceleration-reverse.md``

模型（牛顿积分形式）
--------------------------------------
    coast    = clamp(Σ speedCoef, 0, 1.3)                            # 航速加成系数（旗/技能/升级品）
    vmax     = base_speed × (1 + coast)                             # 当前极速（也是速度上限）
    v_drag   = (vmax + DRAG_ADD_SPEED) × SPEED_TO_DRAG_COEFF         # 阻力参考航速（> 极速）
    F        = 1690·√(enginePower × tonnage / 1000 / vmax)          # 引擎满出力
    K        = F / (v_drag × KNOTS_TO_MPS)²                          # 阻力系数（阻力 ∝ v²）
    A        = F / (tonnage × MASS_UNIT_KG)                          # 加速度标度 m/s²
    mult(v)  = forsage（当 0 < v < 弹射区间），否则 1
    p(t)     = min(1, t / U)，U = upTime / PHYSICS_TIME_SCALE           # 引擎出力爬升
    dv/dt    = A · ( mult(v) ? forsage : p(t) − (v/v_drag)² )          # 牛顿积分
    v        = min(v, vmax)                                          # 到标称极速截住

**引擎最高出力与「达到最高航速」是两件事**：阻力用**参考航速** ``v_drag`` 而不是标称极速
（客户端换算就是 ``(maxSpeed + FORWARD_MOVEMENT_DRAG_ADD_SPEED) * SPEED_TO_DRAG_COEFF``，
见 :data:`DRAG_ADD_SPEED`）。所以引擎满出力时的平衡航速略高于标称极速，而船速被标称极速
截住 ⇒ 「到极速」是**有限时间**内发生的事（旧口径下平衡点恰好在极速上，永远只能渐近接近）。
``upTime`` 是引擎出力从 0 爬到**最高出力**的时间，与航速上限无关。

**航速加成（speedCoef）规则**：客户端把极速写成
``vmax = hull_maxSpeed × (1 + clamp(hull.speedCoef + engine.speedCoef, 0, 1.3))``，
而这个 ``vmax`` 会**同时**喂给功率式与阻力式（两式里的极速是同一个实参）⇒
极速 ×s 时：``F ∝ s^-0.5``、``K ∝ s^-2.5``，但平衡航速仍恰好是 ``vmax·s``。
⚠️ 社区实测帖主张「推力 ×s² / 阻力系数不变」。现版本客户端里**确实有一个把航速系数平方成
出力系数的换算**，但它乘的是**调速器用的额定出力**（nominal），**不是**逐帧积分用的推力；
写入物理参数的清单里也没有推力/阻力系数的覆盖 ⇒ 推力仍旧走“有效极速”这条链（本模块口径）。
两种口径的平衡航速都是 ``base·s``，只差过渡段；若日后实测证实社区口径，
只需把 :data:`SPEED_BONUS_RULE` 改成 ``"drag_fixed"``。
另：**弹射区间上限不随航速加成缩放**（实测：挂 +6% 航速旗后，平台仍出现在 30.1 kn 附近，
而不是 30.2×1.06≈32.0）。

**弹射区间是标准机制**：数据里所有船都有弹射区间，标准档为「上限 2.5 kn / 倍率 2.5」，
少数船自带更大的区间（如 30.225 kn / ×1.75）。区间内推力 = 满推力 × 倍率，且
**只有加速度方向与速度方向一致时生效**（前进中减速、即使速度在区间内也不生效）。

标准档**不是占位值**：实测标准档的船起步会「窜」一下
（0→2.5 kn ≈ 0.3 s（驱逐）~0.9 s（战列），若没有这一档则要 4~10 s），
越过 2.5 kn 后推力掉回爬升值，于是顶着 2.5 kn 附近慢慢爬。
它跟大区间档一样参与计算；只是**全舰共通、没有舰船个性**，
所以界面不为它单独开一栏、也不画「无弹射」对照（见 :func:`is_standard_forsage`）。

**引擎满推力 ∝ √(功率 / 排水量 / 极速)**：``F ∝ √(P/(M·Vmax))`` 来自客户端换算脚本本身
（``(enginePower·mass/1000/vmax)^0.5 · 1690``），不是拟合出来的。

**弹射段的推力不乘爬升系数**：弹射区间内直接取「满推力 × 弹射倍率」，与爬升进度无关；
爬升只影响区间外那一支。

**平台期现象（实测关键证据）**：实测北安普顿到弹射区间极速 30.1/30.2 约 10 s 多，
之后**在 30.1 附近平台一段（几秒）才继续爬到 34.8**。
这个平台只有「越过区间后推力 = P_lin·P 而 P_lin 还没到 1」才能解释：
此时平衡航速 ``34.8·√P_lin`` 仅略高于 30.1，速度就卡在那里。
反解平台长度 + 尾段时长 ⇒ 真实爬升时间 ≈ ``upTime / 2``（见 ``PHYSICS_TIME_SCALE``）。

校验（北安普顿 PASC520，基速 32.8 / 弹射区间 30.225 / ×1.75 / upTime 40 s；裸船）：

| 目标 | 模型 | 实测 |
|---|---|---|
| 到弹射区间 30.2 kn | 11.5 s | ≈11 s |
| 区间后平台（30.2→30.4 kn） | 4.3 s | 「卡在 30.1 左右晃一会」≈4 s |

数据来源（DB）::

    ship_module_engine: engine_power / forward_forsage_power / forward_forsage_max_speed
                        / forward_engine_up_time / speed_coef ...
    ship_module_hulls : max_speed / tonnage

注意：``forward_forsage_max_speed == 2.5`` 不是「没有弹射」的占位值，而是标准弹射档
（实测口径：区间上限 2.5 kn、倍率 2.5）；只有缺失/0 才算没有弹射（:func:`has_forsage`）。
"""
from __future__ import annotations

import math

#: 节 → m/s
KNOTS_TO_MPS = 0.5144445
#: 阻力功率指数（游戏内阻力指数接口返回 2.0）
DRAG_EXP = 2.0
#: 引擎功率换算系数（标定值）
POWER_COEF = 1690.0
#: 质量换算（吨 → 内部单位，×1000）
MASS_SCALE = 1000.0
#: 标准弹射档的参数值（区间上限 kn / 区间内推力倍率）——数据里所有船都有，不是占位值
FORSAGE_DEFAULT = 2.5

#: 阻力**参考航速**的加性常数（kn）：
#: ``v_drag = (vmax + DRAG_ADD_SPEED) × SPEED_TO_DRAG_COEFF``。
#: 客户端换算脚本里就是 ``(maxSpeed + FORWARD_MOVEMENT_DRAG_ADD_SPEED) * KNOTS_TO_MPS
#: * SPEED_TO_DRAG_COEFF``，当时只能按「模型必须复现 maxSpeed」反推成 0/1。
#: 实测表明不能这么推：**引擎最大出力与标称极速是两个独立的量** ——
#: 满出力时的平衡航速略高于标称极速，船速到标称极速即被截住（速度上限），
#: 所以「到极速」是**有限时间**内发生的事，最后那一小段也比单纯二次阻力的渐近快得多。
#: 取值：三条裸船实测反解（北安普顿/埃德加/佛蒙特，见 docs §14.2），0.25 kn 最合。
DRAG_ADD_SPEED = 0.25
#: 阻力参考航速的乘性系数（客户端换算里的 SPEED_TO_DRAG_COEFF）
SPEED_TO_DRAG_COEFF = 1.0

#: 客户端对航速加成系数的上限（``clamp(…)`` 的右界，即最多 +130%）
SPEED_COEF_MAX = 1.3

#: 航速加成后「满推力 / 阻力系数」怎么变 —— 两种口径的唯一分歧点（待实测判定）。
#: 两种口径的**平衡航速都是 base·s**，差别在过渡段：
#:
#: * ``"default"``（默认）：有效极速同时喂给满推力式与阻力式
#:   ⇒ ``F ∝ s^-0.5``、``K ∝ s^-2.5`` ↞ 挂旗/开增压后，到**同一目标航速**的时间几乎不变
#: * ``"drag_fixed"``（社区实测帖口径）：阻力公式不变（K 不动）、满推力 ``F ∝ s²``
#:   ↞ 挂旗/开增压后会明显更快起步、也明显更快掉速
#:
#: 判别实验（训练房，同一船）：测「挂旗 / 开增压前后，从静止到同一航速（如 30 kn）的秒数」
#: 或「从满速减到半速的秒数」——前者两者预测差 10~40%，后者差 10~45%，很好分辨。
SPEED_BONUS_RULE = "default"

#: 物理域时间缩放：引擎侧 upTime 在真实时间里只走 ``upTime / PHYSICS_TIME_SCALE`` 秒。
#: 含义：**upTime 是「引擎达到最高出力」的时间**（不是「到达最高航速」的时间）。
#: 客户端换算里确实是除以它（``setForwardEngineUpTime(id, upTime / timeScale)``），
#: 该值由客户端按战斗类型取的表（``TeamBuildType`` → 时间尺度）给出，**不是全天候常量**。
#: 取 2.4：三组裸船训练房实测里，**只有北安普顿的「区间后平台」对尺度敏感**
#: （埃德加/佛蒙特的爬升在出区间前就走完了，时间与尺度无关），而那个读数 ≈4 s：
#:   尺度 2.2 → 5.7 s、**2.4 → 4.3 s**、2.5 → 3.8 s、2.6 → 3.1 s、2.7 → 2.7 s、3.0 → 1.3 s。
#: 社区帖的 2.7（客户端表值）会把平台压到 2.7 s，与这个读数不符；
#: 更可能是**另一个（战斗类型）**的表值 —— 本仓库按实测取 2.4。
PHYSICS_TIME_SCALE = 2.4

#: 物理质量换算：物理体质量 = 排水量(吨) × MASS_UNIT_KG。
#: 唯一自由参数，由北安普顿实测两点定标（到区间 ≈ 11.6 s，与实测 9~11 s 吻合）。
#: ⇒ 加速度标度 ``A = F / (tonnage × MASS_UNIT_KG)``，
#: 展开即 ``A ∝ √(hp / (tonnage · vmax))`` —— 这个"越重越慢（且慢于 1/m）"的形状
#: 来自引擎功率→推力的换算关系本身，不是拟合出来的。
MASS_UNIT_KG = 26.1


def ramp_time(up_time) -> float:
    """真实时间轴上的功率爬升时长（秒）= ``upTime / PHYSICS_TIME_SCALE``。"""
    try:
        t = float(up_time)
    except (TypeError, ValueError):
        return 1.0
    return t / PHYSICS_TIME_SCALE if t > 0 else 1e-3


def power_ramp(t: float, up_time: float) -> float:
    """引擎功率爬升系数 0→1（**线性**：``min(1, t/U)``，U = ``upTime/PHYSICS_TIME_SCALE``）。

    游戏实现里功率变化的斜率恒为 `1/τ`（τ = 该档满功率时间），与差值大小无关。
    """
    if not up_time or up_time <= 0:
        return 1.0
    s = t / ramp_time(up_time)
    if s <= 0.0:
        return 0.0
    return 1.0 if s >= 1.0 else s


def _get(engine, key: str, default=None):
    """兼容 sqlite3.Row / dict / 对象属性的取值。"""
    try:
        val = engine[key]
    except (KeyError, IndexError, TypeError):
        val = getattr(engine, key, default)
    return default if val is None else val


def has_forsage(zone, power=None) -> bool:
    """是否有弹射区间（区间上限有效且推力倍率 > 1）。

    数据里所有船都有弹射区间（标准档 = 上限 2.5 kn / ×2.5），仅当上限缺失或为 0
    时才视为没有。
    """
    if zone is None:
        return False
    try:
        if float(zone) <= 0.0:
            return False
    except (TypeError, ValueError):
        return False
    if power is None:
        return True
    try:
        return float(power) > 1.0 + 1e-9
    except (TypeError, ValueError):
        return True


def is_standard_forsage(zone, power=None) -> bool:
    """是否为**标准弹射档**（上限 2.5 kn、倍率 ×2.5）—— 即全舰船共通的那一档。

    实测口径：标准档的船起步会「窜」到 2.5 节再慢慢爬
    （0→2.5 kn：驱逐 0.3~0.4 s、战列 0.8~0.9 s；若没有这一档则要 4~10 s）。
    所以标准档**是真实机制**，必须参与计算（见 :func:`power_and_drag`）；
    它只是没有舰船个性 —— 界面上不必为它单独开一栏或画对照曲线。
    """
    if zone is None or power is None:
        return False
    try:
        return (abs(float(zone) - FORSAGE_DEFAULT) < 1e-6
                and abs(float(power) - FORSAGE_DEFAULT) < 1e-6)
    except (TypeError, ValueError):
        return False


def is_standard_model(model) -> bool:
    """模型（:func:`build_model` 的返回值）是否用的是标准弹射档。

    注意读 ``*_raw``（含升级品/增压覆盖后的实际值），而不是 ``zone``/``forsage``
    —— 没有弹射时后者被归一到 0/1。
    """
    if not model:
        return False
    return is_standard_forsage(model.get("zone_raw"), model.get("forsage_raw"))


#: 惰性减速（油门归零）的**常数摩擦项**（无量纲，减速度 = A × 该值）。
#: 纯二次阻力不消耗完速度（永远停不下来），而实测「8.2 → 0 kn 用 14 s」⇒ 必有常数项。
#: 三条裸船实测（北安普顿松油门）：
#:   32.8→16.5 = 11 s、16.5→8.0 = 11 s、8.2→0 = 14 s
#: 拟合结果（二次 + 常数）：10.8 / 10.7 / 14.2 s ✓✓✓（线性+常数：9.7/8.4/15.0；
#: 二次+线性：3.4/3.9/134 ✗）⇒ 减速规律 = ``A·[(v/vd)² + COAST_FRICTION]``。
#: ⚠️ 这一项**只在没有推力时**生效：若加到加速段，满出力平衢航速会降到 vd·√(1−c) < 极速，
#: 与实测「30→极速用 25 s」矛盾（那是客户端 `brakesPowerCoef` 一类的刹车项）。
COAST_FRICTION = 0.2935


def coast_tau(model: dict) -> float:
    """惰性减速的特征时间（秒）：``v_drag_mps / A``（§ 阻力项为零时的时标）。

    实测北安普顿两次减半用时相同（11 / 11 s）≈ 12.3 / 13.0 s（二次+常数）⇒ 合用。
    """
    a = accel_scale(model)
    vd = float(model.get("drag_ref") or drag_ref_speed(model.get("max_speed") or 0.0))
    return (vd * KNOTS_TO_MPS / a) if a > 0 else 0.0


def coast_time(model: dict, v_from: float, v_to: float) -> float:
    """松油门惰性减速：从 ``v_from`` 掉到 ``v_to`` 的时间（秒）。

    ``dv/dt = −A·[(v/vd)² + c]``（c = :data:`COAST_FRICTION`）⇒
    ``t = vd/(A√c)·[atan(v1/(vd√c)) − atan(v2/(vd√c))]``；``v_to = 0`` 时给出有限停船时间。
    """
    a = accel_scale(model)
    try:
        v1 = float(v_from)
        v2 = max(0.0, float(v_to or 0.0))
    except (TypeError, ValueError):
        return 0.0
    if a <= 0 or v1 <= v2:
        return 0.0
    c = COAST_FRICTION
    vd = float(model.get("drag_ref") or drag_ref_speed(model.get("max_speed") or 0.0)) * KNOTS_TO_MPS
    x = vd * math.sqrt(c)
    if x <= 0:
        return 0.0
    return (vd / (a * math.sqrt(c))) * (math.atan((v1 * KNOTS_TO_MPS) / x)
                                         - math.atan((v2 * KNOTS_TO_MPS) / x))


def stop_time(model: dict, v_from: float) -> float:
    """松油门从 ``v_from`` 到完全停下所需时间（秒，有限值）。"""
    return coast_time(model, v_from, 0.0)


#: 旧名（语义已变：2.5 是标准弹射档，不再表示「无弹射」）
has_builtin_forsage = has_forsage


def clamp_speed_coef(*coefs) -> float:
    """航速加成系数求和并夹到 ``[0, SPEED_COEF_MAX]``（客户端口径）。

    客户端把多个来源（船体/引擎/技能/旗/升级品）的 speedCoef 相加后 clamp。
    """
    total = 0.0
    for c in coefs:
        if c is None:
            continue
        try:
            total += float(c)
        except (TypeError, ValueError):
            continue
    return max(0.0, min(SPEED_COEF_MAX, total))


def effective_max_speed(base_speed, *coefs) -> float:
    """按客户端口径算有效极速：``base_speed × (1 + clamp(Σcoef, 0, 1.3))``。"""
    if not base_speed:
        return 0.0
    return float(base_speed) * (1.0 + clamp_speed_coef(*coefs))


def drag_ref_speed(vmax_kn) -> float:
    """阻力公式的**参考航速**（kn）：``(vmax + DRAG_ADD_SPEED) × SPEED_TO_DRAG_COEFF``。

    它**大于**标称极速 ⇒ 满出力下的平衡航速在极速之上，极速是硬上限 ——
    这就是「引擎最大出力」与「最大航速」分开算的位置。
    """
    try:
        return (float(vmax_kn) + DRAG_ADD_SPEED) * SPEED_TO_DRAG_COEFF
    except (TypeError, ValueError):
        return 0.0


def power_and_drag(hp, tonnage, vmax_kn, base_speed=None) -> tuple[float, float]:
    """由马力 / 排水量 / 极速算「满推力 F」与「阻力系数 K」。

    ``F = 1690·√(hp × tonnage / 1000 / vmax_kn)``、
    ``K = F / (drag_ref_speed(vmax_kn) × 0.5144445)²``
    —— 阻力用**参考航速**而不是标称极速（见 :data:`DRAG_ADD_SPEED`）。

    有航速加成（``base_speed`` 为未加成极速）时，按 :data:`SPEED_BONUS_RULE` 处理：

    * ``"default"``：F 与 K 都由**有效极速**算（同一个实参）
    * ``"drag_fixed"``：K 按**基础极速**算（阻力公式不变），F 乘 ``s²``
    """
    hp = float(hp)
    tonnage = float(tonnage)
    vmax = float(vmax_kn)
    base = float(base_speed) if base_speed else vmax
    s = (vmax / base) if base else 1.0
    if SPEED_BONUS_RULE == "drag_fixed" and abs(s - 1.0) > 1e-9:
        f0 = math.sqrt(hp * tonnage / MASS_SCALE / base) * POWER_COEF
        power = f0 * s ** 2
        drag = f0 / ((drag_ref_speed(base) * KNOTS_TO_MPS) ** DRAG_EXP)
    else:
        power = math.sqrt(hp * tonnage / MASS_SCALE / vmax) * POWER_COEF
        drag = power / ((drag_ref_speed(vmax) * KNOTS_TO_MPS) ** DRAG_EXP)
    return power, drag


def build_model(engine, max_speed_kn=None, tonnage=None,
                *, forsage_power=None, forsage_zone=None, up_time=None,
                backward_power_coef=None, speed_coef=None) -> dict | None:
    """由引擎/船体数据构建提速模型。

    Args:
        engine: 引擎行（sqlite3.Row/dict），需含 engine_power 等字段
        max_speed_kn: 基础极速（船体航速，**不含**航速加成）；缺省取 forward_max_speed
        tonnage: 排水量（吨）；缺省取引擎行内 tonnage（如有）
        forsage_power / forsage_zone / up_time: 覆盖值（叠加改装件/消耗品时使用）；
            改装件倍率示例：得梅因传奇插 PCM052 = 区间 ×3.75、功率 ×1.1、upTime ×0.5
        speed_coef: 航速加成比例（0.06 = +6%；旗/技能/升级品之和）。给了就按客户端口径
            算有效极速 ``base × (1 + clamp(coef, 0, 1.3))`` 再入模；不传即
            ``max_speed_kn`` 已是有效极速（旧调用口径）

    Returns:
        dict（power/drag/max_speed/up_time/forsage/zone/hp_per_ton/...）或 None（数据不足）
    """
    hp = _get(engine, "engine_power")
    if max_speed_kn is None:
        max_speed_kn = _get(engine, "forward_max_speed")
    if tonnage is None:
        tonnage = _get(engine, "tonnage")
    if not hp or not max_speed_kn or not tonnage:
        return None

    fps = forsage_power if forsage_power is not None else _get(engine, "forward_forsage_power", FORSAGE_DEFAULT)
    zone = forsage_zone if forsage_zone is not None else _get(engine, "forward_forsage_max_speed", FORSAGE_DEFAULT)
    t_up = up_time if up_time is not None else _get(engine, "forward_engine_up_time", 60.0)
    t_up = float(t_up or 60.0)
    if t_up <= 0:
        t_up = 1e-3

    base_speed = float(max_speed_kn)
    coef = 0.0 if speed_coef is None else clamp_speed_coef(speed_coef)
    max_speed_kn = base_speed * (1.0 + coef)

    power, drag = power_and_drag(hp, tonnage, max_speed_kn, base_speed)
    # 阻力参考航速要与实际算 K 时用的那个实参一致（drag_fixed 口径用基础极速）
    _kref = (base_speed if (SPEED_BONUS_RULE == "drag_fixed" and coef) else max_speed_kn)
    # 无自带弹射时 forsage/zone 为占位值（2.5），不作为实际机制参与计算，
    # 归一化为「无弹射」（倍率 1.0 / 区间 0），原始值放在 *_raw 供参考
    _fps_raw = float(fps) if fps else FORSAGE_DEFAULT
    _zone_raw = float(zone) if zone else FORSAGE_DEFAULT
    builtin = has_builtin_forsage(zone)
    m = {
        "engine_power": float(hp),
        "tonnage": float(tonnage),
        "max_speed": float(max_speed_kn),
        "base_speed": base_speed,
        "speed_coef": coef,
        "drag_ref": drag_ref_speed(_kref),
        "hp_per_ton": float(hp) / float(tonnage),
        "power": power,
        "drag": drag,
        "up_time": t_up,
        "forsage": _fps_raw if builtin else 1.0,
        "zone": _zone_raw if builtin else 0.0,
        "forsage_raw": _fps_raw,
        "zone_raw": _zone_raw,
        "builtin_forsage": builtin,
        "backward_power_coef": (backward_power_coef if backward_power_coef is not None
                                else _get(engine, "backward_power_coef", 1.0)),
    }
    m["accel"] = accel_scale(m)
    return m


def debuffed_model(model: dict, *, speed_mult: float = 1.0, thrust_mult: float = 1.0,
                   up_time_mult: float = 1.0, label: str = "") -> dict | None:
    """返回带**降速 / 降出力** debuff 的模型副本（输入模型不被修改）。

    只用比例修正，不重算换算链：

    * **进水**：``speed_mult = 1 + forwardSpeedOnFlood``（-0.3 ⇒ ×0.7）——
      极速与阻力参考航速同乘 ⇒ 曲线形状不变、整体左移，满出力平衡航速仍在极速之上
      （即仍能跑到进水后的极速）
    * **引擎受损/瘫痪**：``thrust_mult = 1 + damagedEnginePowerMultiplier``（-0.6 ⇒ ×0.4）、
      ``up_time_mult = damagedEnginePowerTimeMultiplier``（5.5 / 6.5 / 7.0）
      —— 出力上限降低在几何上等价于 ``power ×k`` 且 ``drag_ref ×√k``，
      于是满出力平衡航速从 ``vd`` 降到 ``vd·√k``（k = 0.4 ⇒ 约 79% 极速），
      同时推进加速度也按 A ∝ power 变小 —— 与「引擎受损会掉极速、而且加速更慢」一致
      （表里只给乘数，``damagedEngineCoeff`` 是减少该惩罚的技能系数，不在此处重复扣）

    Args:
        model: :func:`build_model` 的返回值
        speed_mult: 极速/阻力参考航速的比例（进水）
        thrust_mult: 出力上限比例（引擎受损）
        up_time_mult: 满功率时间（``forwardEngineUpTime``）比例（引擎受损）
        label: 记入 ``debuff`` 便于界面/日志显示

    Returns:
        新 dict（含 ``debuff`` 说明键），``model`` 为空时返回 None
    """
    if not model:
        return None
    m = dict(model)
    sm = max(1e-3, float(speed_mult or 1.0))
    k = max(1e-3, float(thrust_mult or 1.0))
    um = max(1e-3, float(up_time_mult or 1.0))
    base = float(model.get("max_speed") or 0.0)          # 修正前的满出力平衡上限
    vd0 = float(model.get("drag_ref") or drag_ref_speed(base))
    m["max_speed"] = base * sm
    m["drag_ref"] = vd0 * sm * math.sqrt(k)
    # 出力上限被压低时，满出力平衡航速会低于标称极速 ⇒ 极速也该跟着降到平衡航速，
    # 否则时间轴（到 99.5% 极速）永远算不出来、曲线也永远在缓慢爬升
    m["max_speed"] = min(m["max_speed"], m["drag_ref"])
    m["power"] = float(model.get("power") or 0.0) * k
    m["drag"] = m["power"] / ((m["drag_ref"] * KNOTS_TO_MPS) ** DRAG_EXP)
    m["up_time"] = max(1e-3, float(model.get("up_time") or 0.0) * um)
    m["accel"] = accel_scale(m)
    m["debuff"] = {"speed_mult": sm, "thrust_mult": k, "up_time_mult": um,
                   "label": label, "max_speed_before": base}
    return m


def debuff_engine_damage(model: dict, power_multiplier: float,
                         time_multiplier: float = 1.0) -> dict | None:
    """引擎受损/瘫痪的模型：见 :func:`debuffed_model`（乘数为 DB 里的 ``-0.6`` 口径）。"""
    k = 1.0 + float(power_multiplier or 0.0)
    return debuffed_model(model, thrust_mult=k,
                          up_time_mult=float(time_multiplier or 1.0), label="引擎受损")


def debuff_flood(model: dict, speed_on_flood: float) -> dict | None:
    """进水的模型：极速 ×(1 + ``forwardSpeedOnFlood``)（如 -0.3 ⇒ ×0.7）。"""
    return debuffed_model(model, speed_mult=1.0 + float(speed_on_flood or 0.0), label="进水")


#: 引擎**瘫痪** +「背水一战」时，保留比例的作用口径：
#:   ``"thrust"`` —— 当作**出力（推力）**比例（默认）：出力 ×0.7833（= 1 − 0.2167）
#:                   ⇒ 平衡航速 v_drag×√0.7833 ≈ **1.11×极速 > 极速** ⇒ 极速不变
#:                   （被极速封顶），只是加速明显变慢（A ∝ 出力，up_time 还 ×5.5~7）
#:   ``"speed"``  —— 当作**航速**比例（极速/阻力参考 ×keep）
ENGINE_DISABLED_MODE = "thrust"


def debuff_engine_disabled(model: dict, keep: float, *, up_time_mult: float = 1.0,
                           mode: str | None = None) -> dict | None:
    """引擎**瘫痪** +「背水一战」的模型：保留 ``keep`` 比例的出力/航速。

    ``keep`` = :func:`services.engine_damage_service.load_keep_skill` 的 ``keep``
    = ``1 - damagedEngineCoeff``（0.7833）= **保留的出力比例**：无技能时瘫痪要损失
    100% 出力，点技能后只损失 21.67% ⇒ 惩罚幅度减少 78.33%。
    ``keep = 0`` 即不点该技能 —— 引擎彻底失效、推进力为 0（曲线是一条恒为 0 的直线，
    画布上画不出来，所以界面只画技能生效那条）。

    Args:
        keep: 保留出力比例（0…1）
        up_time_mult: 满功率时间倍数（沿用引擎受损档的 ``damagedEnginePowerTimeMultiplier``）
        mode: 见 :data:`ENGINE_DISABLED_MODE`；缺省用模块常量
    """
    if not model:
        return None
    k = max(0.0, float(keep or 0.0))
    lbl = "引擎瘫痪+背水一战"
    if (mode or ENGINE_DISABLED_MODE) == "speed":
        return debuffed_model(model, speed_mult=k, up_time_mult=up_time_mult, label=lbl)
    return debuffed_model(model, thrust_mult=k, up_time_mult=up_time_mult, label=lbl)


def accel_scale(model: dict) -> float:
    """推进加速度标度 A（m/s²）= 满推力 / 物理质量。

    ``A = power / (tonnage × MASS_UNIT_KG)``；无吨位数据时退化为一个保守值。
    """
    power = float(model.get("power") or 0.0)
    tn = model.get("tonnage")
    if not power or not tn:
        return 0.0
    return power / (float(tn) * MASS_UNIT_KG)


def integrate(model: dict, dt: float = 0.25, t_end: float | None = None, boost: bool = True,
              tau: float | None = None, ramp: bool = True) -> list[tuple[float, float]]:
    """牛顿积分：[(t 秒, v 节)]。

    ``dv/dt = A·(thrust(v,t) − (v/vmax)²)``，其中
    ``thrust = forsage``（弹射区间内，**不乘爬升**）否则 ``p(t)``。
    弹射开关**瞬间**生效（无平滑），所以越过区间会看到真实拐点 + 平台。

    Args:
        boost: 是否启用电弹射（弹射区间内 thrust = forsage）
        ramp: 功率是否从 0 按 ``upTime`` 线性爬升（**默认 True**：开局油门已置，
            但功率比例从 0 开始爬 —— 平台期现象就是这么来的）；
            传 False 可得到「起步即满功率」的对照曲线
        tau: 兼容旧调用（旧模型的一阶惯性常数），不再使用
    """
    t_end = t_end if t_end is not None else curve_duration(model)
    A = accel_scale(model)
    zone = float(model.get("zone") or 0.0)
    vmax_kn = float(model["max_speed"])
    vmax = vmax_kn * KNOTS_TO_MPS
    # 阻力参考航速 > 标称极速：满出力平衡航速在极速之上，极速是硬上限
    v_drag = float(model.get("drag_ref") or drag_ref_speed(vmax_kn)) * KNOTS_TO_MPS
    if A <= 0.0 or vmax <= 0.0:
        return [(0.0, 0.0)]
    v = 0.0
    t = 0.0
    out: list[tuple[float, float]] = []
    while t <= t_end + 1e-9:
        v_kn = v / KNOTS_TO_MPS
        p = power_ramp(t, model["up_time"]) if ramp else 1.0
        if boost and 0.0 < v_kn < zone:
            # 弹射段：这一支直接取「满推力 × 弹射倍率」，
            # **不乘爬升系数**（爬升只影响区间外那一支）
            thrust = model["forsage"]
        else:
            thrust = p
        a = A * (thrust - (v / v_drag) ** 2)
        v = min(max(v + a * dt, 0.0), vmax)
        out.append((round(t, 3), round(v / KNOTS_TO_MPS, 3)))
        t += dt
    return out


def curve_duration(model: dict, frac: float = 0.995, floor: float = 25.0,
                   ceil: float = 300.0) -> float:
    """曲线时间轴长度（秒）：到 ``frac×极速`` 所需时间 + 15% 余量，带上下限。"""
    t = time_to_speed(model, float(model["max_speed"]) * frac, boost=True, dt=0.1, ramp=True)
    if t is None:
        t = 60.0
    return min(ceil, max(floor, t * 1.15))


def speed_curve(model: dict, dt: float = 0.5, t_end: float | None = None,
                boost: bool = True, tau: float | None = None,
                ramp: bool = True) -> list[tuple[float, float]]:
    """加速曲线 [(t 秒, v 节)]（默认跑到 99.5% 极速再加 15% 余量）。"""
    return integrate(model, dt=dt, t_end=t_end, boost=boost, tau=tau, ramp=ramp)


def time_to_speed(model: dict, target_kn: float, boost: bool = True, dt: float = 0.1,
                  tau: float | None = None, ramp: bool = True) -> float | None:
    """从 0 加速到 target_kn 所需时间（秒）；超过最大航速返回 None。"""
    if target_kn > model["max_speed"] + 1e-9:
        return None
    limit = max(model["up_time"] * 4.0, 600.0)
    for t, v in integrate(model, dt=dt, t_end=limit, boost=boost, tau=tau, ramp=ramp):
        if v >= target_kn - 1e-6:
            return round(t, 2)
    return None


def seconds_to_fraction(model: dict, frac: float, boost: bool = True, dt: float = 0.1,
                        tau: float | None = None) -> float | None:
    """达到 frac×最大航速所需时间（秒）。"""
    return time_to_speed(model, model["max_speed"] * frac, boost=boost, dt=dt, tau=tau)


def plateau(model: dict, dv: float = 0.2, dt: float = 0.02) -> tuple[float, float] | None:
    """区间后「卡顿」：返回 ``(到区间用时, 再涨 dv 节用时)``。

    区间上限处推力从「满推力 × 弹射倍率」降阶到「满推力 × 爬升比例」，净推力变小，
    所以速度会在区间上限附近爬一段 —— 实测里就是「卡在 30.1 左右晃一会」。
    没有弹射区间的模型返回 ``None``。
    """
    zone = float(model.get("zone") or 0.0)
    if zone <= 0.0 or zone >= float(model["max_speed"]):
        return None
    t_zone = time_to_speed(model, zone, boost=True, dt=dt)
    t_out = time_to_speed(model, zone + dv, boost=True, dt=dt)
    if t_zone is None or t_out is None:
        return None
    return t_zone, t_out


def backward_model(engine, forward_power: float, *, mods: tuple = (),
                   tonnage=None, speed_coef=None,
                   forsage_power=None, forsage_zone=None) -> dict | None:
    """构造「后退档」模型（与前进同结构，可直接交给 :func:`integrate` 系列）。

    公式与前进一致，差别：
      · 功率 ``P_b = P_f / backward_power_coef``（倒车推力 = 前进推力 ÷ 倒车功率系数）
      · 阻力 ``k_b`` 由**后退最大航速**反推 ⇒ 平衡航速恰好 = ``backward_max_speed``
      · 加速时间用 ``backward_engine_up_time``，弹射用 ``backward_forsage_*``

    ⚠️ ``backward_power_coef`` / ``tonnage`` 库里没有该列（默认 1.0）也不影响曲线：
    ``v(t) = vmax_b·√(p(t)·mult)`` 与 P/k 的绝对值无关（P/k 只影响内部量）。

    mods: 引擎类升级品的 (功率, 区间, upTime) 乘数（与前进同一套）。
    speed_coef: 航速加成比例（0.06 = +6%）：正反向极速一起按比例放大（客户端口径）。
    forsage_power / forsage_zone: 直接**覆盖**倒船弹射倍率/区间（给引擎增压用 —— 增压是覆盖，
        不是叠加升级品；传了就忽略 ``mods`` 里的对应乘数）。
    """
    vmax_b = _get(engine, "backward_max_speed")
    t_b = _get(engine, "backward_engine_up_time")
    if not vmax_b or not t_b:
        return None
    m_p, m_z, m_t = (list(mods) + [None, None, None])[:3] if mods else (None, None, None)
    try:
        bpc = float(_get(engine, "backward_power_coef", 1.0) or 1.0)
    except (TypeError, ValueError):
        bpc = 1.0
    coef = 0.0 if speed_coef is None else clamp_speed_coef(speed_coef)
    vmax_b_base = float(vmax_b)
    vmax_b = vmax_b_base * (1.0 + coef)
    p_b = float(forward_power) / (bpc if bpc else 1.0)
    # ``drag_fixed`` 口径下阻力系数不随加成变（用基础后退极速反推）
    _k_ref = (vmax_b_base if (SPEED_BONUS_RULE == "drag_fixed" and coef)
              else vmax_b)
    k_b = p_b / ((drag_ref_speed(_k_ref) * KNOTS_TO_MPS) ** DRAG_EXP)
    zone_b = float(_get(engine, "backward_forsage_max_speed", FORSAGE_DEFAULT) or FORSAGE_DEFAULT)
    fp_b = float(_get(engine, "backward_forsage_power", FORSAGE_DEFAULT) or FORSAGE_DEFAULT)
    t_b = float(t_b)
    if forsage_zone is not None:
        zone_b = float(forsage_zone)
    elif m_z:
        zone_b *= float(m_z)
    if forsage_power is not None:
        fp_b = float(forsage_power)
    elif m_p:
        fp_b *= float(m_p)
    if m_t:
        t_b *= float(m_t)
    builtin = has_builtin_forsage(zone_b)
    m = {
        "engine_power": _get(engine, "engine_power"),
        "tonnage": tonnage if tonnage is not None else _get(engine, "tonnage"),
        "max_speed": float(vmax_b),
        "base_speed": vmax_b_base,
        "speed_coef": coef,
        "drag_ref": drag_ref_speed(_k_ref),
        "hp_per_ton": None,
        "power": p_b,
        "drag": k_b,
        "up_time": t_b if t_b > 0 else 1e-3,
        "forsage": fp_b if builtin else 1.0,
        "zone": zone_b if builtin else 0.0,
        "forsage_raw": fp_b,
        "zone_raw": zone_b,
        "builtin_forsage": builtin,
        "backward_power_coef": bpc,
    }
    m["accel"] = accel_scale(m)
    return m
