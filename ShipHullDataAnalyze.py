class ShipHullDataAnalyze:

    # 数据解析/显示
    def analyzeShipData(self, hull_data, hull_id):
        # 数据顺序:
        # 通用数据:血量 航速 转向半径 转舵时间 基础水面隐蔽 基础空中隐蔽 是否存在核心区模块 船体回复率 核心回复率
        # 潜艇特殊数据:
        # 提取潜艇相关数据（如果存在）
        cit_module_data = hull_data.get("Cit", {})
        has_cit = True if cit_module_data else False
        sub_battery = hull_data.get("SubmarineBattery", {})
        has_battery = True if sub_battery else False
        hydrophone = hull_data.get("Hydrophone", {})
        has_hydrophone = True if hydrophone else False
        buoyancy = hull_data.get("buoyancyStates", {})
        buoyancy_data = []

        for state, values in buoyancy.items():
            buoyancy_data.append({
                "state": state,
                "depth_range": values[0],
                "speed_multiplier": values[1],
            })

        analyzed_hull_data = {
            "default_data": {
                "label": "通用数据",
                "items": {
                    "hull_id": {"name": "船体模块型号", "val": hull_id, "unit": "", "order": 0},
                    "health": {"name": "基础血量", "val": hull_data.get("health"), "unit": "", "order": 1},
                    "maxSpeed": {"name": "最大航速", "val": hull_data.get("maxSpeed"), "unit": "kts", "order": 2},
                    "turningRadius": {"name": "转弯半径", "val": hull_data.get("turningRadius"), "unit": "m", "order": 3},
                    "rudderTime": {"name": "转舵时间", "val": hull_data.get("rudderTime") * 0.77, "unit": "s", "order": 4},
                    "vis_sea": {"name": "基础水面隐蔽", "val": hull_data.get("visibilityFactor"), "unit": "km", "order": 5},
                    "vis_plane": {"name": "基础空中隐蔽", "val": hull_data.get("visibilityFactorByPlane"), "unit": "km", "order": 6},
                    "has_cit":{"name": "是否存在核心区模块", "val": has_cit, "unit": "", "order": 7},
                    "hull_regenper":{"name": "船体回复率", "val": hull_data.get("Hull", {}).get("regeneratedHPPart"), "unit": "", "order": 8},
                    "cit_regenper":{"name": "核心回复率", "val": hull_data.get("Cit", {}).get("regeneratedHPPart"), "unit": "", "order": 9},
                }
            },
            "submarine_sp_data": {
                "label": "潜艇特殊数据",
                "items": {
                    "has_battery": {"name": "是否存在潜艇电力数据", "val": has_battery, "unit": "", "order": 0},
                    "bat_cap": {"name": "电池容量", "val": sub_battery.get("capacity"), "unit": "", "order": 1},
                    "bat_regen": {"name": "电力恢复", "val": sub_battery.get("regenRate"), "unit": "/s", "order": 2},
                    "has_hydrophone": {"name": "是否存在水听器模块数据", "val": has_hydrophone, "unit": "", "order": 3},
                    "hp_radius": {"name": "水听器范围", "val": hydrophone.get("waveRadius"), "unit": "km", "order": 4},
                    "hp_frep": {"name": "水听器更新周期", "val": hydrophone.get("updateFrequency"), "unit": "s", "order": 5},
                    "hp_work_states": {"name": "水听器工作深度", "val": hydrophone.get("workingBuoyancyStates"), "unit": "", "order": 6},
                    "hp_detect_states": {"name": "水听器可探测深度", "val": hydrophone.get("detectableBuoyancyStates"), "unit": "", "order": 7},
                    "buoyancyStates": {"name": "深度等级数据", "val": buoyancy_data, "unit": "", "order": 8},
                    "buoyancy_rudder_time": {"name": "水平舵转舵时间", "val": hull_data.get("buoyancyRudderTime") * 0.77, "unit": "s", "order": 9},
                    "buoyancy_speed": {"name": "上浮/下潜速度", "val": hull_data.get("maxBuoyancySpeed"), "unit": "m/s", "order": 10},
                }
            }
        }

        return analyzed_hull_data