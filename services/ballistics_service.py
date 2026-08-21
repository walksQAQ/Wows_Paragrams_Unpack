from __future__ import annotations

import math
from typing import Any


class BallisticsCalculator:
    """严格按浩舰 calculator.js / dap.js 逻辑实现的弹道/穿深/散布计算器。"""

    # Korabli 原始弹道常量（Ghidra 反推自 Korabli64.exe FUN_1404d3680）
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
    def get_normalization_angle(caliber_m: float) -> float:
        if caliber_m <= 0.13:
            return 10.0
        if caliber_m <= 0.152:
            return 8.5
        if caliber_m <= 0.22:
            return 7.0
        return 6.0

    @staticmethod
    def _air_density(height_m: float) -> float:
        """标准大气 ISA 密度（Korabli 原始公式，Ghidra 反推自 FUN_1404d3680）。

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

        Ghidra 反推自 FUN_1404d3680：低空（<160m）步长 0.1s，高空（>800m）步长 0.8125s。
        """
        h = max(float(height_m), 0.0)
        dt = math.exp(h * BallisticsCalculator.KORABLI_DT_COEF) * h * BallisticsCalculator.KORABLI_DT_COEF
        return max(BallisticsCalculator.KORABLI_DT_MIN, min(BallisticsCalculator.KORABLI_DT_MAX, dt))

    @staticmethod
    def simulate_trajectory(mass: float, caliber_m: float, air_drag: float, velocity: float, angle_deg: float) -> dict:
        """Korabli 原始弹道积分（Ghidra 反推自 FUN_1404d3680 / Korabli64.exe）。

        - 标准大气 ISA 密度（T0=288.15, L=0.0065, p0=101325, M=0.0289644, R=8.31447）
        - 纯二次阻力（沿速度反向）：a_drag = rho*A*0.5*c_D*v^2/mass，A = pi/4*d^2
        - 自适应步长 dt(h) = clamp(exp(h*0.00065)*h*0.00065, 0.1001, 0.8125)
        - 重力 g = 9.8
        """
        theta = math.radians(angle_deg)
        v_x = float(velocity) * math.cos(theta)
        v_y = float(velocity) * math.sin(theta)
        x = 0.0
        y = 0.0
        t = 0.0
        # k = 0.5*c_D*A/mass，A = pi/4*d^2（与 0.5*c_D*(d/2)^2*pi/mass 等价）
        k = 0.5 * float(air_drag) * (float(caliber_m) / 2.0) ** 2 * math.pi / max(float(mass), 1e-9)

        # 记录上一步，用于落地插值（对齐游戏 FUN_1404d3990 末尾的落点线性插值到 y=0）
        prev_x, prev_y, prev_vx, prev_vy, prev_t = 0.0, 0.0, v_x, v_y, 0.0
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
            if t > 5000:
                break

        # 游戏落点修正：最后一段由正转负时，线性插值到 y=0（FUN_1404d3990 末尾，
        # fVar14 = y_{n-1}/(y_{n-1} - y_n)，对落点位置/速度/落弹角/时间加权）
        if prev_y > 0.0 > y:
            frac = prev_y / (prev_y - y)
            x = prev_x + (x - prev_x) * frac
            v_x = prev_vx + (v_x - prev_vx) * frac
            v_y = prev_vy + (v_y - prev_vy) * frac
            t = prev_t + (t - prev_t) * frac
            y = 0.0

        v_imp = math.hypot(v_x, v_y)
        impact_angle_deg = math.degrees(math.atan2(abs(v_y), abs(v_x))) if v_imp > 0 else 0.0
        return {
            "distance_m": x,
            "velocity": v_imp,
            "fly_time": t,
            "impact_angle_deg": impact_angle_deg,
        }

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

    def calculate_full_ballistics(self, mass: float, caliber_m: float, air_drag: float, velocity: float, krupp: float, norm_angle: float | None = None) -> dict:
        if norm_angle is None:
            norm_angle = self.get_normalization_angle(caliber_m)
        norm_angle_rad = math.radians(float(norm_angle))
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
    def calc_longitudinal_radius(perp_radius_m: float, impact_angle_deg: float) -> float:
        """纵向散布半径 = 垂直散布半径 / sin(落弹角)（MKtool shellDispersionMetrics）。

        落弹角被钳制在 2°~45° 之间，分母最小 0.035，避免除零。
        """
        ia = min(max(float(impact_angle_deg), 2.0), 45.0)
        return float(perp_radius_m) / max(math.sin(math.radians(ia)), 0.035)

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
