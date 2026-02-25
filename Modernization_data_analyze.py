import tkinter as tk

class ModernizationDataAnalyzer:
    # 属性加成词条翻译表
    MODIFIER_MAP = {
        # 主炮
        "GMRotationSpeed": "主炮回转速度",
        "GMShotDelay": "主炮装填时间",
        "GMMaxDist": "主炮射程",
        "GMIdealRadius": "主炮炮弹的最大误差",
        "GMCritProb": "主炮瘫痪的风险",
        "GMRepairTime": "主炮修理时间",
        "GMAPDamageCoeff": "主炮穿甲弹的伤害",
        "GMDamageCoeff": "主炮炮弹伤害",
        # 副炮
        "GSIdealRadius": "副炮炮弹的最大误差",
        "GSMaxDist": "副炮射程",
        "GSCritProb": "副炮瘫痪的风险",
        "GSRepairTime": "副炮修理时间",
        "GSShotDelay": "副炮装填时间",
        "GSAlphaFactor": "副炮炮弹伤害",
        # 防空炮
        "AAAuraDamageBonus": "在远程防空炮区域的持续伤害",
        "AACritProb": "防空炮瘫痪的风险",
        "AARepairTime": "防空炮修理时间",
        "AAExtraBubbles": "防空齐射炮弹爆炸次数",
        "AABubbleDamageBonus": "防空炮弹爆炸伤害",
        # 鱼雷发射管
        "GTCritProb": "鱼雷发射管瘫痪的风险",
        "GTShotDelay": "鱼雷发射管装填时间",
        "GTRepairTime": "鱼雷管修理时间",
        "GTRotationSpeed": "鱼雷管回转速度",
        "torpedoSpeedMultiplier": "鱼雷航速",
        "torpedoVisibilityFactor": "鱼雷对海被侦察范围",
        "torpedoDamageCoeff": "鱼雷伤害",
        # 声呐
        "pingerCritProb": "声呐瘫痪的风险",
        "pingerRepairTime": "声呐修理时间",
        "pingerWaveSpeedCoeff": "声呐脉冲速度",
        # 水听器
        "hydrophoneUpdateFrequencyCoeff": "脉冲间隔",
        "hydrophoneWaveSpeedCoeff": "水听器波纹扩散速度",
        # 飞机
        "planeExtraHangarSize": "甲板上各类型飞机的最大数量（不包括战术中队）",
        "planeSpawnTime": "飞机整备时间",
        "planeEmptyReturnSpeed": "飞行中队返回速度",
        "planeSpeed": "中队速度",
        "planeHealthCoeff": "中队生命值",
        "planeVisibilityFactor": "中队的被侦察范围",
        "bombAlphaDamageMultiplier": "炸弹伤害",
        "diveBomberSpeedMultiplier": "轰炸机巡航速度",
        "diveBomberMinSpeedMultiplier": "轰炸机最低速度",
        "diveBomberMaxSpeedMultiplier": "轰炸机最高速度",
        "planeForsageTimeCoeff": "中队引擎增压持续时间",
        "planeMaxSpeedMultiplier": "中队最高速度",
        "fighterHealth": "攻击机生命值",
        "torpedoBomberHealth": "鱼雷轰炸机生命值",
        "diveBomberHealth": "轰炸机生命值",
        "skipBomberHealth": "弹跳轰炸机生命值",
        "mineBomberHealth": "水雷轰炸机生命值",
        "fighterAimingTime": "攻击机攻击时间",
        "torpedoBomberAimingTime": "鱼雷轰炸机攻击时间",
        "skipBomberAimingTime": "弹跳轰炸机攻击时间",
        "planeTorpedoSpeedMultiplier": "空投鱼雷航速",
        "planeTorpedoArmingTimeCoeff": "空投鱼雷触发距离",
        "planeAlphaDamageCoeff": "中队武器伤害",
        "planeSpreadMultiplier": "中队攻击最大误差",
        # 空袭/支援中队
        "asMaxHealthCoeff": "空袭和支援中队飞机生命值",
        "asReloadTimeCoeff": "空袭和支援中队装填时间",
        "asNumPacksBonus": "空袭和支援次数",
        # 深水炸弹
        "dcReloadTimeCoeff": "深水炸弹装填时间",
        "dcAlphaDamageMultiplier": "深水炸弹伤害",
        # 水雷
        "minefieldLifeTimeCoeff": "水雷区生效时间",
        # 船体
        "burnProb": "起火的风险",
        "floodProb": "进水的风险",
        "burnTime": "灭火时间",
        "floodTime": "进水恢复时间",
        "engineBackwardForsageMaxSpeed": "倒车加速最大速度倍率",
        "engineBackwardForsagePower": "倒车加速功率",
        "engineBackwardUpTime": "倒车达到发动机全功率所需时间",
        "engineForwardForsageMaxSpeed": "前进加速最大速度倍率",
        "engineForwardForsagePower": "前进加速功率",
        "engineForwardUpTime": "前进达到发动机全功率所需时间",
        "SGCritProb": "操舵装置瘫痪的风险",
        "SGRepairTime": "操舵装置修理时间",
        "engineCritProb": "引擎瘫痪的风险",
        "engineRepairTime": "引擎修理时间",
        "SGRudderTime": "方向舵换挡时间",
        "buoyancyRudderResetTimeCoeff": "水平舵归位时间",
        "buoyancyRudderTimeCoeff": "水平舵换挡时间",
        "uwSourceDmgReduction": "来自鱼雷、水雷和深水炸弹的伤害",
        "visionXRayMineDist": "水雷绝对捕获距离",
        "visionXRayTorpedoDist": "鱼雷绝对捕获距离",
        "shootShift": "被敌方炮弹攻击的误差",
        "visibilityDistCoeff": "战舰的被侦察范围",
        "prioritySectorCooldownMultiplier": "优先防空区域准备时间",
        "batteryRegenCoeff": "每秒下潜能力恢复",
        "batteryCapacityCoeff": "下潜能力",
        "pingerReloadCoeff": "声呐冷却时间",
        "healthHullCoeff": "战舰生命值",
        # 消耗品
        "speedBoostersWorkTimeCoeff": "引擎增压消耗品作用时间",
        "planeSmokeGeneratorWorkTimeCoeff": "烟幕发生器消耗品作用时间",
        "smokeGeneratorWorkTimeCoeff": "发烟器消耗品作用时间",
        "scoutReloadCoeff": "侦察机消耗品装填时间",
        "scoutWorkTimeCoeff": "侦察机消耗品作用时间",
        "crashCrewWorkTimeBonus": "伤害控制小组消耗品作用时间",
        "airDefenseDispReloadCoeff": "防御型对空火力消耗品装填时间",
        "airDefenseDispWorkTimeCoeff": "防御型对空火力消耗品作用时间",
        "sonarWorkTimeCoeff": "对海搜索消耗品作用时间",
        "rlsWorkTimeCoeff": "监视雷达消耗品作用时间",
        "ConsumableReloadTime": "战舰消耗品的准备和装填时间",
        "smokeGeneratorLifeTime": "烟幕扩散时间",
        "additionalConsumables": "战舰消耗品数量",
        "ConsumablesWorkTime": "消耗品作用时间",
        "planeAdditionalConsumables": "中队消耗品数量",
        "regeneratedHPPartCoef": "使用维修小组消耗品时的生命恢复效率",
        "speedBoostersAdditionalConsumables": "引擎增压消耗品可用次数",
        "boostCoeffForsage": "引擎增压消耗品启用时的战舰最高航速",
        "smokeGeneratorAdditionalConsumables": "发烟器消耗品装载数",
        "smokeGeneratorReloadCoeff": "发烟器消耗品冷却时间",
        "regenCrewReloadCoeff": "维修小组消耗品冷却时间",
    }

    def __init__(self, name_mapping=None):
        self.name_mapping = name_mapping or {}

    def analyze(self, display_area, data):
        """
        解析并向 UI 插入升级品（插件）详细数据
        """
        # --- 1. 基础信息提取 ---
        mod_index = data.get("index", "Unknown")
        mod_id = data.get("id", "N/A")
        raw_name = data.get("name", mod_index)

        # 尝试获取映射名，如果没有则美化原始 ID
        display_name = self.name_mapping.get(mod_index, raw_name)

        cost = data.get("costCR", 0)
        slot = data.get("slot", 0)
        slot_str = f"第 {slot+1} 槽位" if slot != -1 else f"已禁用升级品"

        display_area.insert(tk.END, f"升级品名称: {display_name}\n"
                                    f"编号: {mod_index}\n"
                                    f"ID: {mod_id}\n"
                                    f"价格: {cost:,} 银币\n"
                                    f"安装槽位: {slot_str}\n")
        display_area.insert(tk.END, "=" * 45 + "\n\n")

        # --- 2. 核心加成属性 (Modifiers) ---
        # 定义不需要计算百分比、直接显示原值的词条
        NO_PERCENTAGE_KEYS = {"planeExtraHangarSize","AAAuraDamageBonus","additionalConsumables","planeAdditionalConsumables","AAExtraBubbles","smokeGeneratorAdditionalConsumables","asNumPacksBonus","speedBoostersAdditionalConsumables"}
        FACTOR_KEYS = {"AABubbleDamageBonus"}
        SECOND_KEYS = {"crashCrewWorkTimeBonus","torpedoBomberAimingTime","fighterAimingTime"}
        KILOMETER_KEYS = {"visionXRayMineDist","visionXRayTorpedoDist"}
        SP_PERCENT_KEYS = {"engineBackwardForsageMaxSpeed", "engineBackwardForsagePower", "engineForwardForsageMaxSpeed", "engineForwardForsagePower","hydrophoneWaveSpeedCoeff","regeneratedHPPartCoef","boostCoeffForsage"}
        SHIP_CLASS_MAP = {
            "Destroyer": "驱逐",
            "Cruiser": "巡洋",
            "Battleship": "战列",
            "AirCarrier": "航母",
            "Submarine": "潜艇",
            "Auxiliary": "其他"
        }

        modifiers = data.get("modifiers", {})
        if modifiers:
            display_area.insert(tk.END, "[属性加成]\n")
            for key, value in modifiers.items():
                label = self.MODIFIER_MAP.get(key, key)

                # 数值转化逻辑
                if isinstance(value, dict):
                    display_area.insert(tk.END, f"  - {label}:\n")
                    for ship_type, factor in value.items():
                        short_name = SHIP_CLASS_MAP.get(ship_type, ship_type)

                        # 对字典内的数值同样进行百分比/原值判定
                        if key in NO_PERCENTAGE_KEYS:
                            display_area.insert(tk.END, f"      {short_name}: {factor}\n")
                        else:
                            percent = round((factor - 1.0) * 100, 3)
                            percent_str = f"{percent:g}"  # 自动处理小数位，7.5% 不丢，10.0% 变 10%
                            sign = "+" if percent > 0 else ""
                            display_area.insert(tk.END, f"      {short_name}: {sign}{percent_str}%\n")

                elif isinstance(value, (float, int)):
                    # 逻辑：如果 key 在排除列表中，直接显示原值
                    if key in NO_PERCENTAGE_KEYS:
                        value = f"+{value}" if value > 0 else f"{value}"
                        display_area.insert(tk.END, f"  - {label}: {value}\n")
                    elif key in FACTOR_KEYS:
                        result = round(value * 7, 3)
                        sign = "+" if result > 0 else ""
                        display_area.insert(tk.END, f"      {label}: {sign}{result:.0f}\n")
                    elif key in SECOND_KEYS:
                        value = f"+{value}" if value > 0 else f"{value}"
                        display_area.insert(tk.END, f"  - {label}: {value}s\n")
                    elif key in KILOMETER_KEYS:
                        percent = value/1000
                        display_area.insert(tk.END, f"  - {label}: {percent}km\n")
                    elif key in SP_PERCENT_KEYS:
                        percent = round(value * 100, 1)

                        # 如果是整数位（比如 20.0），则去掉小数点显示为 20
                        if percent == int(percent):
                            percent = int(percent)
                        sign = "+" if percent > 0 else ""
                        display_area.insert(tk.END, f"  - {label}: {sign}{percent}%\n")
                    else:
                        # 否则执行百分比转化逻辑 (0.8 -> -20%, 1.1 -> +10%)
                        percent = round((value - 1.0) * 100, 3)
                        percent_str = f"{percent:g}"
                        sign = "+" if percent > 0 else ""
                        # 针对减益属性，负值通常代表“强化”
                        display_area.insert(tk.END, f"  - {label}: {sign}{percent_str}%\n")
                else:
                    display_area.insert(tk.END, f"  - {label}: {value}\n")

        # --- 3. 限制条件 (Restrictions) ---
        # 检查是否有特定的限制列表
        restrictions = [
            ("禁用舰船", data.get("excludes", [])),
            ("可用分类", data.get("group", [])),
            ("可用舰船", data.get("ships", [])),
            ("可用国籍", data.get("nation", [])),
            ("可用等级", data.get("shiplevel", [])),
            ("可用舰种", data.get("shiptype", [])),
        ]

        # 只有当限制列表不为空时才显示
        has_restriction = any(len(val) > 0 for _, val in restrictions)
        if has_restriction:
            display_area.insert(tk.END, "\n[使用限制]\n")
            for label, items in restrictions:
                if items:
                    display_area.insert(tk.END, f"  - {label}: {', '.join(map(str, items))}\n")

        display_area.insert(tk.END, "\n" + "-" * 45 + "\n")