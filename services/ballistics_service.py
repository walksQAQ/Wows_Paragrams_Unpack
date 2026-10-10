from __future__ import annotations

import bisect
import math
from typing import Any


class BallisticsCalculator:
    """严格按浩舰 calculator.js / dap.js 逻辑实现的弹道/穿深/散布计算器。"""

    # Korabli 原始弹道常量（与客户端实现一致）
    GRAVITY = 9.8                     # 重力加速度 m/s^2（游戏用 9.8，非 9.81）
    GAS_CST_R = 8.31447
    AIR_MOLAR_MASS = 0.0289644
    SEALEVEL_TEMPERATURE = 288.15     # 海平面温度 K（游戏用 288.15）
    STATIC_PRESSURE = 101325.0
    TEMPERATURE_LAPSE_RATE = 0.0065
    C_PEN = 0.5561613
    CW_1 = 1.0                        # 二次阻力项系数
    N_ANGLE = 200
    MAX_ANGLE_DEG = 45
    # Korabli 自适应步长：dt(h) = clamp(exp(h*0.00065)*h*0.00065, 0.1001, 0.8125)
    KORABLI_DT_MIN = 0.100099996
    KORABLI_DT_MAX = 0.8125
    KORABLI_DT_COEF = 0.00064999994
    # 飞行时间除数：游戏/浩舰显示飞行时间 = 原始模拟时间 ÷ 3.1（用户确认，2026-08-14）
    FLY_TIME_DIVISOR = 3.1

    @staticmethod
    def _air_density(height_m: float) -> float:
        """标准大气 ISA 密度（Korabli 原始公式）。

        T = T0 - L*h
        p = p0 * (1 - L*h/T0)^(g*M/(R*L))
        rho = p*M/(R*T)
        """
        h = max(float(height_m), 0.0)
        t = BallisticsCalculator.SEALEVEL_TEMPERATURE - BallisticsCalculator.TEMPERATURE_LAPSE_RATE * h
        if t <= 0.0:
            return 0.0
        exponent = (BallisticsCalculator.GRAVITY * BallisticsCalculator.AIR_MOLAR_MASS) / (
            BallisticsCalculator.GAS_CST_R * BallisticsCalculator.TEMPERATURE_LAPSE_RATE
        )
        ratio = 1.0 - BallisticsCalculator.TEMPERATURE_LAPSE_RATE * h / BallisticsCalculator.SEALEVEL_TEMPERATURE
        if ratio <= 0.0:
            return 0.0
        pressure = BallisticsCalculator.STATIC_PRESSURE * (ratio ** exponent)
        return pressure * BallisticsCalculator.AIR_MOLAR_MASS / (BallisticsCalculator.GAS_CST_R * t)

    @staticmethod
    def _korabli_dt(height_m: float) -> float:
        """Korabli 自适应步长：dt(h) = clamp(exp(h*0.00065)*h*0.00065, 0.1001, 0.8125)。

        客户端实现：低空（<160m）步长 0.1s，高空（>800m）步长 0.8125s。
        """
        h = max(float(height_m), 0.0)
        dt = math.exp(h * BallisticsCalculator.KORABLI_DT_COEF) * h * BallisticsCalculator.KORABLI_DT_COEF
        return max(BallisticsCalculator.KORABLI_DT_MIN, min(BallisticsCalculator.KORABLI_DT_MAX, dt))

    @staticmethod
    def simulate_trajectory(mass: float, caliber_m: float, air_drag: float, velocity: float, angle_deg: float,
                            start_height_m: float = 0.0, record_path: bool = False) -> dict:
        """Korabli 原始弹道积分（与客户端实现一致）。

        - 标准大气 ISA 密度（T0=288.15, L=0.0065, p0=101325, M=0.0289644, R=8.31447）
        - 纯二次阻力（沿速度反向）：a_drag = rho*A*0.5*c_D*v^2/mass，A = pi/4*d^2
        - 自适应步长 dt(h) = clamp(exp(h*0.00065)*h*0.00065, 0.1001, 0.8125)
        - 重力 g = 9.8
        - start_height_m：起始高度（客户端 getGunDist 以炮口高度 gunHeight 起算，落在 y=0）；默认 0 与旧行为完全一致
        - record_path：额外返回 path_x / path_y（逐步水平位置/高度，末点已插值到 y=0），
          用于把落点垂向位移沿真实弹道传播到水面；默认 False 不产生额外开销
        """
        theta = math.radians(angle_deg)
        v_x = float(velocity) * math.cos(theta)
        v_y = float(velocity) * math.sin(theta)
        x = 0.0
        y = float(start_height_m)
        t = 0.0
        # k = 0.5*c_D*A/mass，A = pi/4*d^2（与 0.5*c_D*(d/2)^2*pi/mass 等价）
        k = 0.5 * float(air_drag) * (float(caliber_m) / 2.0) ** 2 * math.pi / max(float(mass), 1e-9)

        # 记录上一步，用于落地插值（对齐客户端落点处理末尾的线性插值到 y=0）
        prev_x, prev_y, prev_vx, prev_vy, prev_t = 0.0, float(start_height_m), v_x, v_y, 0.0
        path_x: list[float] = [0.0]
        path_y: list[float] = [float(start_height_m)]
        while y >= 0.0:
            prev_x, prev_y, prev_vx, prev_vy, prev_t = x, y, v_x, v_y, t
            dt = BallisticsCalculator._korabli_dt(y)
            rho = BallisticsCalculator._air_density(y)
            v = math.hypot(v_x, v_y)
            if v > 1e-9:
                drag = k * rho * v * v
                v_x -= drag * (v_x / v) * dt
                v_y -= drag * (v_y / v) * dt
            v_y -= BallisticsCalculator.GRAVITY * dt
            x += v_x * dt
            y += v_y * dt
            t += dt
            if record_path:
                path_x.append(x)
                path_y.append(y)
            if t > 5000:
                break

        # 游戏落点修正：最后一段由正转负时，线性插值到 y=0（客户端落点处理末尾，
        # fVar14 = y_{n-1}/(y_{n-1} - y_n)，对落点位置/速度/落弹角/时间加权）
        if prev_y > 0.0 > y:
            frac = prev_y / (prev_y - y)
            x = prev_x + (x - prev_x) * frac
            v_x = prev_vx + (v_x - prev_vx) * frac
            v_y = prev_vy + (v_y - prev_vy) * frac
            t = prev_t + (t - prev_t) * frac
            y = 0.0
            if record_path and len(path_x) > 1:
                path_x[-1] = x
                path_y[-1] = 0.0

        v_imp = math.hypot(v_x, v_y)
        impact_angle_deg = math.degrees(math.atan2(abs(v_y), abs(v_x))) if v_imp > 0 else 0.0
        out = {
            "distance_m": x,
            "velocity": v_imp,
            "fly_time": t,
            "impact_angle_deg": impact_angle_deg,
        }
        if record_path:
            out["path_x"] = path_x
            out["path_y"] = path_y
        return out

    @staticmethod
    def max_range_at_pitch(mass: float, caliber_m: float, air_drag: float, velocity: float,
                           pitch_deg: float, start_height_m: float = 0.0) -> float:
        """给定仰角（度）时炮弹落到水面（y=0）的水平距离（米）。

        对齐客户端 `getGunDist` / `getTrajectoryDist`：仰角先钳到
        `[0, MAX_ANGLE_DEG]`（客户端 DEFAULT_MAX_PITCH = radians(45)，即仰角超过 45° 也按 45° 算），
        起点为炮口高度（默认 0）。
        """
        pitch = max(0.0, min(float(pitch_deg), BallisticsCalculator.MAX_ANGLE_DEG))
        res = BallisticsCalculator.simulate_trajectory(
            mass, caliber_m, air_drag, velocity, pitch, start_height_m=start_height_m)
        return float(res.get("distance_m") or 0.0)

    @staticmethod
    def calc_ap_penetration(krupp: float, mass_kg: float, velocity: float, caliber_m: float) -> float:
        """AP 穿深（与 calc_v3_penetration 数学等价，保留接口兼容）。"""
        return BallisticsCalculator.calc_v3_penetration(krupp, mass_kg, velocity, caliber_m)

    @staticmethod
    def calc_v3_penetration(krupp: float, mass_kg: float, velocity: float, caliber_m: float) -> float:
        """浩舰 V3 (calculator3.js) 穿深公式：m^0.69 * V^1.38 * D^-1.07 * K * 1e-7.

        与 V2 的 K*(m*V^2)^0.69*D^-1.07*1e-7 在数学上等价，但 V3 的着速来自
        后端逐距离弹道表（本地由弹道模拟插值代替）。
        """
        return (
            float(mass_kg) ** 0.69
            * float(velocity) ** 1.38
            * float(caliber_m) ** -1.07
            * float(krupp)
            * 0.0000001
        )

    @staticmethod
    def calc_vertical_effective_pen(pen_abs: float, impact_angle_deg: float, norm_angle_deg: float) -> float:
        """垂直装甲等效穿深 = pen_abs * cos(max(0, IA - norm))（浩舰 V3）"""
        ia = max(0.0, float(impact_angle_deg) - float(norm_angle_deg))
        return float(pen_abs) * math.cos(math.radians(ia))

    @staticmethod
    def interpolate_at_distance(ballistics: dict, distance_km: float) -> dict:
        """从均匀弹道表线性插值指定距离的着速/落弹角/飞行时间。

        ballistics 由 calculate_full_ballistics 生成，含 distance_km / velocity /
        impact_angle_deg / fly_time 列表。
        """
        d_list = ballistics.get("distance_km") or []
        if not d_list:
            return {"velocity": 0.0, "impact_angle_deg": 0.0, "fly_time": 0.0}
        v_list = ballistics.get("velocity") or []
        a_list = ballistics.get("impact_angle_deg") or []
        t_list = ballistics.get("fly_time") or []
        distance_km = float(distance_km)

        if distance_km <= d_list[0]:
            idx = 0
        elif distance_km >= d_list[-1]:
            idx = len(d_list) - 1
        else:
            idx = 0
            while idx + 1 < len(d_list) and d_list[idx + 1] < distance_km:
                idx += 1

        if idx >= len(d_list) - 1:
            return {
                "velocity": v_list[-1],
                "impact_angle_deg": a_list[-1],
                "fly_time": t_list[-1],
            }
        left_d = d_list[idx]
        right_d = d_list[idx + 1]
        ratio = (distance_km - left_d) / (right_d - left_d) if right_d != left_d else 0.0
        return {
            "velocity": v_list[idx] + (v_list[idx + 1] - v_list[idx]) * ratio,
            "impact_angle_deg": a_list[idx] + (a_list[idx + 1] - a_list[idx]) * ratio,
            "fly_time": t_list[idx] + (t_list[idx + 1] - t_list[idx]) * ratio,
        }

    def build_impact_speed_table(self, mass: float, caliber_m: float, air_drag: float, velocity: float) -> list:
        """复刻浩舰后端 API `dap/list-impact-speed` 返回的逐距离弹道表。

        API: GET dap/list-impact-speed?mass=m&diametr=D&airDrag=c_D&speed=v_0
        返回 JSON 数组，每项形如 {dist, velocity, angle, time}：
          - dist      距离 (km)
          - velocity  着速 (m/s)
          - angle     落弹角 (°)
          - time      飞行时间 (s)
        本地用 calculate_full_ballistics（0.1 km 均匀插值）等价复刻。
        """
        table = self.calculate_full_ballistics(mass, caliber_m, air_drag, velocity, 0.0)
        d_list = table.get("distance_km") or []
        v_list = table.get("velocity") or []
        a_list = table.get("impact_angle_deg") or []
        t_list = table.get("fly_time") or []
        rows = []
        for i in range(len(d_list)):
            rows.append({
                "dist": round(float(d_list[i]), 1),
                "velocity": round(float(v_list[i]), 2),
                "angle": round(float(a_list[i]), 2),
                "time": round(float(t_list[i]), 2),
            })
        return rows

    @staticmethod
    def calc_he_penetration(he_value: float) -> float:
        return float(he_value) if he_value else 0.0

    @staticmethod
    def calc_equivalent_penetration(pen_abs: float, impact_angle_rad: float, norm_angle_rad: float) -> tuple[float, float]:
        ia_vert = max(impact_angle_rad - norm_angle_rad, 0.0)
        ia_hori = min(impact_angle_rad + norm_angle_rad, math.pi / 2)
        vert_pen = pen_abs * math.cos(ia_vert)
        hori_pen = pen_abs * math.sin(ia_hori)
        return vert_pen, hori_pen

    def calculate_full_ballistics(self, mass: float, caliber_m: float, air_drag: float, velocity: float, krupp: float, norm_angle: float = 0.0) -> dict:
        # 转正角由调用方给出（游戏逐弹字段 bullet_cap_normalize_max；自定义炮弹由界面手填）；
        # 缺省 0.0 = 不做转正。不再按口径推断。
        norm_angle_rad = math.radians(float(norm_angle or 0.0))
        angles = []
        distances = []
        velocities = []
        fly_times = []
        impact_angles = []

        for i in range(self.N_ANGLE):
            angle_deg = (i * self.MAX_ANGLE_DEG) / max(self.N_ANGLE - 1, 1)
            res = self.simulate_trajectory(mass, caliber_m, air_drag, velocity, angle_deg)
            angles.append(angle_deg)
            distances.append(res["distance_m"])
            velocities.append(res["velocity"])
            fly_times.append(res["fly_time"])
            impact_angles.append(res["impact_angle_deg"])

        max_dist = max(distances) if distances else 0.0
        uniform_distances = []
        uniform_penetrations = []
        uniform_impact_angles = []
        uniform_durations = []
        uniform_velocity = []

        # 统一表步长：10m（0.01km），与计算器曲线 0.01km 采样对齐，
        # 消除 0.1km 边界处的斜率突变（曲线折痕），显著提升平滑度
        step_m = 10.0
        max_point = int(math.ceil(max_dist / step_m))
        for idx in range(max_point + 1):
            target_dist = idx * step_m
            uniform_distances.append(target_dist / 1000.0)
            if not distances:
                val = 0.0
                ang = 0.0
                dur = 0.0
                vel = 0.0
            else:
                v_idx = 0
                while v_idx + 1 < len(distances) and distances[v_idx + 1] < target_dist:
                    v_idx += 1
                if v_idx >= len(distances) - 1:
                    val = self.calc_ap_penetration(krupp, mass, velocities[-1], caliber_m)
                    ang = impact_angles[-1]
                    dur = fly_times[-1]
                    vel = velocities[-1]
                else:
                    left_d = distances[v_idx]
                    right_d = distances[v_idx + 1]
                    left_v = velocities[v_idx]
                    right_v = velocities[v_idx + 1]
                    if right_d == left_d:
                        vel = left_v
                    else:
                        vel = left_v + (right_v - left_v) * ((target_dist - left_d) / (right_d - left_d))
                    ang = impact_angles[v_idx] + (impact_angles[v_idx + 1] - impact_angles[v_idx]) * ((target_dist - left_d) / (right_d - left_d)) if right_d != left_d else impact_angles[v_idx]
                    dur = fly_times[v_idx] + (fly_times[v_idx + 1] - fly_times[v_idx]) * ((target_dist - left_d) / (right_d - left_d)) if right_d != left_d else fly_times[v_idx]
                    val = self.calc_ap_penetration(krupp, mass, vel, caliber_m)
                uniform_impact_angles.append(ang)
                uniform_durations.append(dur / BallisticsCalculator.FLY_TIME_DIVISOR)
                uniform_velocity.append(vel)
            pen_abs = val
            vert_pen, hori_pen = self.calc_equivalent_penetration(pen_abs, math.radians(ang), norm_angle_rad)
            uniform_penetrations.append(max(vert_pen, hori_pen))

        return {
            "distance_km": uniform_distances,
            "penetration": uniform_penetrations,
            "impact_angle_deg": uniform_impact_angles,
            "fly_time": uniform_durations,
            "velocity": uniform_velocity,
            "raw_distance_m": distances,
            "raw_velocity": velocities,
            "raw_impact_angle_deg": impact_angles,
        }

    @staticmethod
    def calc_horizontal_dispersion(distance_km: float, params: dict) -> float:
        td = float(params.get("td", 0.0) or 0.0)
        ha = float(params.get("ha", 0.0) or 0.0)
        hb = float(params.get("hb", 0.0) or 0.0)
        coeff = float(params.get("dispCoeff", 1.0) or 1.0)
        r = float(distance_km)
        if r < td:
            taper_disp = (td * ha + hb) / td if td else 0.0
            return round(r * taper_disp * coeff, 1)
        return round((r * ha + hb) * coeff, 1)

    @staticmethod
    def calc_vertical_dispersion(horiz_disp: float, distance_km: float, max_dist: float, params: dict, impact_angle_deg: float | None = None, hoop_type: int = 0) -> float:
        vd = float(params.get("vd", 0.0) or 0.0)
        vrz = float(params.get("vrz", 0.0) or 0.0)
        vrd = float(params.get("vrd", 0.0) or 0.0)
        vrm = float(params.get("vrm", 0.0) or 0.0)
        max_dist = float(max_dist or 1.0)
        delim_dist = vd * max_dist
        r = float(distance_km)
        if r < delim_dist:
            vert_coeff = vrz + (vrd - vrz) * (r / delim_dist) if delim_dist else vrz
        else:
            vert_coeff = vrd + (vrm - vrd) * ((r - delim_dist) / (max_dist - delim_dist)) if (max_dist - delim_dist) else vrd
        hoop_scale = 1.0
        if hoop_type == 1 and impact_angle_deg is not None:
            hoop_scale = math.sin(math.radians(float(impact_angle_deg)))
        elif hoop_type == 2 and impact_angle_deg is not None:
            hoop_scale = math.cos(math.radians(float(impact_angle_deg)))
        if hoop_scale == 0:
            hoop_scale = 1.0
        return round(float(horiz_disp) * vert_coeff / hoop_scale, 1)

    @staticmethod
    def calc_dispersion_area(horiz_disp: float, vert_disp: float) -> float:
        return round(float(horiz_disp) * float(vert_disp) * math.pi / 1000.0, 1)

    @staticmethod
    def calc_expected_dispersion(dispersion: float, sigma: float) -> float:
        return round(float(dispersion) * float(sigma), 1)

    @staticmethod
    def calc_expected_area(area: float, sigma: float) -> float:
        return round(float(area) * float(sigma) * float(sigma), 1)

    @staticmethod
    def project_vertical_dispersion_geometric(vertical_m: float, impact_angle_deg: float) -> float:
        """【几何（直线）近似，保留对照】ΔR = Δn / sin(落弹角)。

        三维推导（θ = 落弹角，Δn = 垂直面内垂直于弹道的纵向位移）：
          · Δn 在竖直方向的分量 = Δn·cosθ，沿射程方向分量 = Δn·sinθ
          · 弹着点要回到水面，需沿弹道再走 Δn·cosθ/tanθ
          · 合计 ΔR = Δn·sinθ + Δn·cos²θ/sinθ = Δn/sinθ

        ⚠️ 把弹道当成直线，小落弹角下会无限放大（2 km 约 ×3400/Δn）；现行右图口径
        已改为 `project_vertical_dispersion_to_water`（逐条积分真实弹道），本函数仅作对照参考。
        """
        sine = math.sin(math.radians(abs(float(impact_angle_deg))))
        return float(vertical_m) / max(sine, 1e-9)

    # 水面投影弹道族采样数（仰角按 i/(n-1) 平方分布：低仰角更密）
    WATER_FAMILY_ANGLES = 33

    @staticmethod
    def _interp_path(path_x: list, path_y: list, x: float):
        """弹道路径上水平位置 x 处的高度（x 超出路径范围返回 None）。"""
        if not path_x or x < path_x[0] or x > path_x[-1]:
            return None
        i = bisect.bisect_left(path_x, x)
        if i <= 0:
            return float(path_y[0])
        if i >= len(path_x):
            return float(path_y[-1])
        x0, x1 = path_x[i - 1], path_x[i]
        if x1 <= x0:
            return float(path_y[i - 1])
        f = (x - x0) / (x1 - x0)
        return float(path_y[i - 1] + (path_y[i] - path_y[i - 1]) * f)

    @staticmethod
    def build_trajectory_family(mass: float, caliber_m: float, air_drag: float, velocity: float,
                               n_angles: int | None = None) -> dict:
        """采样一组**真实弹道**路径（发射仰角 → 路径 + 落水距离），供水面纵向投影使用。

        仰角按 i/(n-1) 的平方分布（低仰角更密）——近距离弹道对该处仰角最敏感，
        需要更高的角度分辨率。返回：
          {"angles": [...], "paths": [(xs, ys, distance_m), ...], "peak_index": int,
           "max_range_m": float}
        ❗不同仰角的路径不能混用；每次换弹种/初速需重建（约几毫秒）。
        """
        n = max(int(n_angles or BallisticsCalculator.WATER_FAMILY_ANGLES), 5)
        angles = [BallisticsCalculator.MAX_ANGLE_DEG * ((i / (n - 1)) ** 2) for i in range(n)]
        paths = []
        for a in angles:
            r = BallisticsCalculator.simulate_trajectory(
                mass, caliber_m, air_drag, velocity, a, record_path=True)
            paths.append((r.get("path_x") or [0.0], r.get("path_y") or [0.0],
                          float(r.get("distance_m") or 0.0)))
        peak = max(range(n), key=lambda i: paths[i][2])
        return {"angles": angles, "paths": paths, "peak_index": peak,
                "max_range_m": paths[peak][2]}

    @staticmethod
    def project_vertical_dispersion_to_water(family: dict, distance_km: float, vertical_m: float) -> float:
        """ΔR：把垂直面纵向半轴 Δn 当成"落点在目标竖直线上的垂向位移"，沿**真实弹道**投到水面。

        做法：在弹道族里找"恰好穿过 (d, Δn)"的那条弹道——即弹丸在目标处高出 Δn、仍继续飞行的
        那条发射仰角——取其落水距离 R'，则 ΔR = R' − d（Δn>0 → 偏高 → 落得更远）。

        与 `project_vertical_dispersion_geometric`（直线假设 Δn/sinθ）相比：这里逐条积分的
        真实弹道自带弯曲与近最大射程的"弹丸聚挤"效应，近距离不会无上限放大；
        数值上与大落弹角时的 Δn/tanθ 接近，小落弹角时比 Δn/sinθ 小一截。
        """
        d = float(distance_km) * 1000.0
        dn = float(vertical_m)
        if d <= 1.0 or dn <= 0.0 or not family:
            return 0.0
        paths = family.get("paths") or []
        peak = int(family.get("peak_index") or (len(paths) - 1))
        ys: list[float] = []
        rs: list[float] = []
        for i in range(min(peak + 1, len(paths))):   # 低伸支：R 随仰角单调递增
            xs, py, R = paths[i]
            if R < d:
                continue
            y = BallisticsCalculator._interp_path(xs, py, d)
            if y is None:
                continue
            ys.append(y)
            rs.append(R)
            if y >= dn:          # 已找到包裹 Δn 的区间 → 提前结束，避免整族扫完
                break
        if not ys:
            return 0.0
        if dn <= ys[0]:
            # 在名义弹道（锚点 y=0, R=d）与第一个采样之间插值
            R = d + (rs[0] - d) * (dn / ys[0]) if ys[0] > 0.0 else d
        else:
            R = rs[-1]
            for i in range(1, len(ys)):
                if ys[i] >= dn:
                    span = ys[i] - ys[i - 1]
                    f = (dn - ys[i - 1]) / span if span > 0.0 else 0.0
                    R = rs[i - 1] + (rs[i] - rs[i - 1]) * f
                    break
        return max(R - d, 0.0)

    @staticmethod
    def gaussian_dispersion_points(sigma: float, count: int, seed: int = 0) -> list:
        """MKtool randomShellDeviation：Box-Muller 高斯偏移点 (longitudinal, lateral)。

        - 方向角均匀分布 0~π
        - 高斯幅值 / sigma 控制聚散，|g|>1 时回退到均匀值
        - 纵向正侧用 10*ln(0.1*x+1) 对数压缩
        """
        import random

        rng = random.Random(int(seed))
        sigma = max(float(sigma) or 1.0, 0.2)
        points = []
        for _ in range(int(count)):
            angle = rng.random() * math.pi
            u1 = rng.random()
            u2 = rng.random()
            if u1 <= 0:
                u1 = 1e-9
            gaussian = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2) / sigma
            fallback = rng.random() * 2.0 - 1.0
            magnitude = gaussian if abs(gaussian) <= 1.0 else fallback
            lateral = math.sin(angle) * magnitude
            longitudinal = math.cos(angle) * magnitude
            if longitudinal > 0:
                longitudinal = 10.0 * math.log(0.1 * longitudinal + 1.0)
            points.append((longitudinal, lateral))
        return points
