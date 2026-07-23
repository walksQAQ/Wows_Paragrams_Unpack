"""
name_mapping —— 全局中文翻译映射表。

所有游戏内英文标识 → 中文翻译的静态字典。
"""


class Mapping:
    MODIFIER_MAP = {
        "GMRotationSpeed": "主炮回转速度",
        "GMShotDelay": "主炮装填时间",
        "GMMaxDist": "主炮射程",
        "GMIdealRadius": "主炮炮弹的最大误差",
        "GMCritProb": "主炮瘫痪的风险",
        "GMRepairTime": "主炮修理时间",
        "GMAPDamageCoeff": "主炮穿甲弹的伤害",
        "GMDamageCoeff": "主炮炮弹伤害",
        "GMPenetrationCoeffHE": "主炮高爆弹穿深",
        "artilleryKruppMultiplier": "主炮穿甲弹穿深",
        "GMBigGunVisibilityCoeff": "主炮口径149mm及以上的战舰被侦查范围",
        "GMHeavyCruiserCaliberDamageCoeff": "主炮口径190mm及以上的主炮穿甲弹伤害",
        "GMHECSDamageCoeff": "主炮高爆和半穿甲弹伤害",
        "GMSHECSDamageCoeff": "中口径炮高爆和半穿甲弹伤害",
        "GSIdealRadius": "副炮炮弹的最大误差",
        "GSMaxDist": "副炮射程",
        "GSCritProb": "副炮瘫痪的风险",
        "GSRepairTime": "副炮修理时间",
        "GSShotDelay": "副炮装填时间",
        "GSAlphaFactor": "副炮炮弹伤害",
        "GSPenetrationCoeffHE": "副炮高爆弹穿深",
        "GSPriorityTargetIdealRadius": "对优先目标发射副炮炮弹时的最大误差",
        "GMSRotationSpeed": "中口径炮回转速度",
        "GMSShotDelay": "中口径炮装填时间",
        "GMSMaxDist": "中口径炮射程",
        "GMSIdealRadius": "中口径炮炮弹的最大误差",
        "GMSCritProb": "中口径炮瘫痪的风险",
        "GMSRepairTime": "中口径炮修理时间",
        "GMSDamageCoeff": "中口径炮炮弹伤害",
        "GMSAPDamageCoeff": "中口径炮穿甲弹伤害",
        "GMSHECSDamageCoeff": "中口径炮高爆/半穿甲弹伤害",
        "GMSPenetrationCoeffHE": "中口径炮高爆弹穿深",
        "GMSSwitchAmmoReloadCoef": "中口径炮炮弹类型切换时间",
        "GMSwitchAmmoReloadCoef": "主炮炮弹类型切换时间",
        "AAAuraDamageBonus": "在远程防空炮区域的持续伤害",
        "AACritProb": "防空炮瘫痪的风险",
        "AARepairTime": "防空炮修理时间",
        "AAExtraBubbles": "防空齐射炮弹爆炸数",
        "AABubbleDamageBonus": "防空炮弹爆炸伤害",
        "AABubbleDamage": "防空炮弹爆炸伤害",
        "AAAuraDamage": "防空炮每秒伤害",
        "AAAuraReceiveDamageCoeff": "防空持续伤害",
        "lastChanceReloadCoefficient": "每失去1%生命值，装填时间与防空持续伤害变化",
        "GTCritProb": "鱼雷发射管瘫痪的风险",
        "GTShotDelay": "鱼雷发射管装填时间",
        "GTRepairTime": "鱼雷管修理时间",
        "GTRotationSpeed": "鱼雷管回转速度",
        "torpedoSpeedMultiplier": "鱼雷航速",
        "torpedoVisibilityFactor": "鱼雷对海被侦查范围",
        "torpedoDamageCoeff": "鱼雷伤害",
        "torpedoRangeCoefficient": "鱼雷射程",
        "floodChanceFactorTorpedo": "舰载鱼雷造成进水的几率",
        "ignorePTZBonus": "使鱼雷防护无效",
        "pingerCritProb": "声呐瘫痪的风险",
        "pingerRepairTime": "声呐修理时间",
        "pingerWaveSpeedCoeff": "声呐脉冲速度",
        "hydrophoneUpdateFrequencyCoeff": "脉冲间隔",
        "hydrophoneWaveSpeedCoeff": "水听器波纹扩散速度",
        "planeExtraHangarSize": "甲板上各类型飞机的最大数量",
        "planeSpawnTime": "飞机整备时间",
        "planeEmptyReturnSpeed": "飞行中队返回速度",
        "planeSpeed": "中队速度",
        "planeHealthPerLevel": "每个战舰等级提升的飞机生命值",
        "planeHealthCoeff": "中队生命值",
        "planeVisibilityFactor": "中队的被侦察范围",
        "bombAlphaDamageMultiplier": "炸弹伤害",
        "bombApAlphaDamageMultiplier": "穿甲炸弹伤害",
        "rocketApAlphaDamageMultiplier": "穿甲火箭弹伤害",
        "diveBomberSpeedMultiplier": "轰炸机巡航速度",
        "diveBomberMinSpeedMultiplier": "轰炸机最低速度",
        "diveBomberMaxSpeedMultiplier": "轰炸机最高速度",
        "diveBomberAccuracyIncRateCoeff": "俯冲轰炸机瞄准速度",
        "planeForsageTimeCoeff": "中队引擎增压持续时间",
        "planeMaxSpeedMultiplier": "中队最高速度",
        "fighterAccuracyIncRateCoeff": "攻击机瞄准速度",
        "fighterHealth": "攻击机生命值",
        "torpedoBomberHealth": "鱼雷轰炸机生命值",
        "diveBomberHealth": "轰炸机生命值",
        "skipBomberAccuracyIncRateCoeff": "弹跳轰炸机瞄准速度",
        "skipBomberHealth": "弹跳轰炸机生命值",
        "mineBomberHealth": "水雷轰炸机生命值",
        "fighterAimingTime": "攻击机攻击时间",
        "torpedoBomberAccuracyIncRateCoeff": "鱼雷轰炸机瞄准速度",
        "torpedoBomberAimingTime": "鱼雷轰炸机攻击时间",
        "skipBomberAimingTime": "弹跳轰炸机攻击时间",
        "skipBomberSpeedMultiplier": "弹跳轰炸机巡航速度",
        "planeTorpedoSpeedMultiplier": "空投鱼雷航速",
        "planeTorpedoArmingTimeCoeff": "空投鱼雷触发距离",
        "planeAlphaDamageCoeff": "中队武器伤害",
        "planeSpreadMultiplier": "中队攻击最大误差",
        "asMaxHealthCoeff": "空袭和支援中队飞机生命值",
        "asReloadTimeCoeff": "空袭和支援中队装填时间",
        "asNumPacksBonus": "空袭和支援次数",
        "dcReloadTimeCoeff": "深水炸弹装填时间",
        "dcAlphaDamageMultiplier": "深水炸弹伤害",
        "dcSplashSizeMultiplier": "深水炸弹和攻击潜艇时炮弹的爆炸半径",
        "minefieldLifeTimeCoeff": "水雷区生效时间",
        "burnProb": "起火的风险",
        "floodProb": "在防雷带被鱼雷/水雷命中时进水的风险",
        "burnTime": "灭火时间",
        "floodTime": "进水恢复时间",
        "speedCoef": "战舰航速",
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
        "extraFighterCount": "飞机数量",
        "SGRudderTime": "方向舵换挡时间",
        "buoyancyRudderResetTimeCoeff": "水平舵归位时间",
        "buoyancyRudderTimeCoeff": "水平舵换挡时间",
        "uwSourceDmgReduction": "来自鱼雷、水雷和深水炸弹的伤害",
        "visionXRayMineDist": "水雷绝对捕获距离",
        "visionXRayTorpedoDist": "鱼雷绝对捕获距离",
        "mineDetectionCoefficient": "水雷被探测距离",
        "torpedoDetectionCoefficient": "鱼雷捕获范围",
        "torpedoDetectionCoefficientByPlane": "空中鱼雷捕获范围",
        "uwCoeffBonus": "鱼雷防护",
        "shootShift": "被敌方炮弹攻击的误差",
        "shootShiftBatteryLastChanceCoeff": "每消耗1%下潜能力，被敌方炮弹攻击的误差变化",
        "visibilityDistCoeff": "战舰的被侦察范围",
        "prioritySectorCooldownMultiplier": "优先防空区域准备时间",
        "prioritySectorStrengthBonus": "优先区域强化",
        "batteryRegenCoeff": "每秒下潜能力恢复",
        "batteryRegenBatteryLastChanceCoeff": "每消耗1%下潜能力，每秒下潜能力恢复变化",
        "batteryCapacityCoeff": "下潜能力",
        "maxBuoyancySpeedCoeff": "最大下潜和上浮速度",
        "speedBatteryLastChanceCoeff": "位于水面时的航速",
        "pingerReloadCoeff": "声呐冷却时间",
        "healthHullCoeff": "战舰生命值",
        "healthPerLevel": "基础血量",
        "healthRegen": "每秒回复血量",
        "vulnerabilityBurn": "受到的火灾伤害",
        "vulnerabilityFlood": "受到的进水伤害",
        "vulnerabilityDBomb": "受到的深水炸弹伤害",
        "planeBubbleArmorCoeff": "受到的防空炮弹爆炸伤害",
        "burnChanceBonus": "造成目标起火的几率",
        "artilleryBurnChanceBonus": "高爆弹造成目标起火的几率",
        "bombBurnChanceBonus": "高爆炸弹造成目标起火的几率",
        "rocketBurnChanceBonus": "高爆火箭弹造成目标起火的几率",
        "critProbCoefficient": "配件瘫痪的风险",
        "floodChanceCommonBonus": "造成目标进水的几率",
        "regenerationHPSpeed": "战舰每秒生命值",
        "allConsumableReloadTime": "消耗品的准备和装填时间",
        "speedBoostersWorkTimeCoeff": "引擎增压消耗品作用时间",
        "planeSmokeGeneratorWorkTimeCoeff": "烟幕发生器消耗品作用时间",
        "smokeGeneratorWorkTimeCoeff": "发烟器消耗品作用时间",
        "scoutReloadCoeff": "侦察机消耗品冷却时间",
        "scoutWorkTimeCoeff": "侦察机消耗品作用时间",
        "scoutAdditionalConsumables": "侦察机消耗品装载数",
        "crashCrewWorkTimeBonus": "损害管制小组消耗品作用时间",
        "crashCrewReloadCoeff": "损害管制小组消耗品冷却时间",
        "crashCrewAdditionalConsumables": "损害管制小组消耗品装载数",
        "crashCrewWorkTimeCoeff": "损害管制小组消耗品作用时间",
        "hlCritTimeCoeff": "修理、灭火和进水恢复时间",
        "artilleryBoostersReloadCoeff": "主炮组装填助推器消耗品冷却时间",
        "fighterReloadCoeff": "战斗机消耗品冷却时间",
        "airDefenseDispReloadCoeff": "防御型对空火力消耗品冷却时间",
        "airDefenseDispWorkTimeCoeff": "防御型对空火力消耗品作用时间",
        "sonarWorkTimeCoeff": "对海搜索消耗品作用时间",
        "rlsWorkTimeCoeff": "监视雷达消耗品作用时间",
        "ConsumableReloadTime": "战舰消耗品的准备和装填时间",
        "smokeGeneratorLifeTime": "烟幕扩散时间",
        "additionalConsumables": "战舰消耗品数量",
        "ConsumablesWorkTime": "消耗品作用时间",
        "planeAdditionalConsumables": "中队消耗品数量",
        "healForsageReloadCoeff": "引擎冷却消耗品冷却时间",
        "callFightersRadiusCoeff": "巡逻半径",
        "callFightersAdditionalConsumables": "巡逻战斗机/截击机消耗品装载数",
        "callFightersAdditionalPlanesHighLevel": "VIII、X级和超级航空母舰的战斗机数量",
        "callFightersAdditionalPlanesLowLevel": "IV和VI级航空母舰的战斗机数量",
        "burnChanceFactorHighLevel": "应用加成前，造成起火的几率",
        "burnChanceFactorLowLevel": "应用加成前，造成起火的几率",
        "callFightersTimeDelayAttack": "攻击前所需时间",
        "callFightersWorkTimeCoeff": "巡逻战斗机/截击机消耗品作用时间",
        "planeConsumableReloadTime": "中队消耗品冷却时间",
        "planeConsumablesWorkTime": "中队消耗品作用时间",
        "planeConsumableWorkTime": "中队消耗品作用时间",
        "regeneratedHPPartCoef": "使用维修小组消耗品时的生命恢复效率",
        "regenerateHealthAdditionalConsumables": "维修消耗品装载数",
        "regenerateHealthWorkTimeCoeff": "维修消耗品持续时间",
        "speedBoostersAdditionalConsumables": "引擎增压消耗品可用次数",
        "boostCoeffForsage": "引擎增压消耗品启用时的战舰最高航速",
        "smokeGeneratorAdditionalConsumables": "发烟器消耗品装载数",
        "smokeGeneratorReloadCoeff": "发烟器消耗品冷却时间",
        "regenCrewReloadCoeff": "维修小组消耗品冷却时间",
        "regenCrewAdditionalConsumables": "维修小组消耗品装载数",
        "regenCrewWorkTimeCoeff": "维修小组消耗品作用时间",
        "torpedoReloaderAdditionalConsumables": "鱼雷装填助推器消耗品装填数",
        "torpedoReloaderReloadCoeff": "鱼雷装填助推器消耗品冷却时间",
        "workTime": "生效时间",
    }

    NATION_MAP = {
        "USA": "美国", "Japan": "日本", "Germany": "德国", "Russia": "苏联",
        "United_Kingdom": "英国", "France": "法国", "Italy": "意大利",
        "Pan_Asia": "泛亚", "Europe": "欧洲", "Netherlands": "荷兰",
        "Commonwealth": "英联邦", "Pan_America": "泛美", "Spain": "西班牙",
        "Events": "其他",
    }

    SHIP_GROUP_MAP = {
        "start": "初始", "preserved": "已移除", "upgradeable": "可研发",
        "earlyAccess": "抢先体验", "superShip": "超级战舰", "premium": "加值",
        "ultimate": "特殊", "special": "特殊", "specialUnsellable": "特殊",
        "disabled": "禁用", "clan": "仅军团", "coopOnly": "仅人机",
        "demoWithoutStatsPrem": "加值测试", "demoWithoutStats": "测试",
        "unavailable": "不可用", "event": "仅事件",
    }

    LEVEL_MAP = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "★"]

    WEAPON_SPECIES_MAP = {
        "Main": "主炮", "Secondary": "副炮", "Torpedo": "鱼雷发射管",
        "AAircraft": "防空炮", "DCharge": "深弹发射器",
    }

    SHIP_CLASS_MAP = {
        "Destroyer": "驱逐舰", "Cruiser": "巡洋舰", "Battleship": "战列舰",
        "AirCarrier": "航空母舰", "Submarine": "潜艇", "Auxiliary": "其他类型",
        "default": "默认",
    }

    AIRCRAFT_CLASS_MAP = {
        "Bomber": "鱼雷轰炸机", "Dive": "俯冲轰炸机", "Fighter": "战斗机",
        "Mine": "水雷轰炸机", "Scout": "侦察机", "Skip": "弹跳轰炸机",
        "Auxiliary": "其他飞机",
    }

    AMMO_TYPE_MAP = {"HE": "HE", "AP": "AP", "CS": "SAP"}

    PROJECTILE_TYPE_MAP = {
        "Artillery": "火炮炮弹", "Bomb": "炸弹", "DepthCharge": "深水炸弹",
        "Laser": "激光", "Rocket": "火箭弹", "Torpedo": "鱼雷", "Wave": "波浪",
    }

    BUOYANCY_MAP = {
        "SURFACE": "水面状态", "PERISCOPE": "潜望镜深度",
        "SEMI_DEEP_WATER": "半潜深度", "DEEP_WATER": "作业深度",
        "DEEP_WATER_INVUL": "最大深度",
    }

    DETAIL_MAP = {
        "requiredCount": "所需次数", "radius": "有效半径",
        "separateTracking": "独立计数", "subRibbons": "有效勋带",
        "timeLimit": "时间限制", "progress": "进度", "progressName": "进度标识",
        "stateName": "状态标识", "RibbonActivator": "缎带/勋章触发",
        "RageModeProgressAction": "累加战斗指令进度",
        "healPerSecond": "每秒回复血量", "duration": "持续时间",
        "triggerName": "触发标识", "isRepeating": "可重复",
        "isVisible": "是否显示", "isEnabled": "是否启用",
        "consumableTypes": "消耗品类型", "count": "数量",
        "potentialDamageShift": "所受的潜在伤害", "planeName": "飞机型号",
        "reduceTime": "减少整备时间",
    }

    # ── 加成词条显示格式规则 ────────────────────────────
    # coeff: 乘数（0.6=-40%, 1.1=+10%），数值>0 即正收益
    # raw_pct: 原始百分比（0.01=+1%）
    # raw_int: 原始整型（25=+25）
    MODIFIER_FORMAT_MAP: dict[str, str] = {
        # ── 主炮 ──
        "GMRotationSpeed": "coeff",
        "GMShotDelay": "coeff",
        "GMMaxDist": "coeff",
        "GMIdealRadius": "coeff",
        "GMCritProb": "coeff",
        "GMRepairTime": "coeff",
        "GMAPDamageCoeff": "coeff",
        "GMDamageCoeff": "coeff",
        "GMPenetrationCoeffHE": "coeff",
        "artilleryKruppMultiplier": "coeff",
        "GMBigGunVisibilityCoeff": "coeff",
        "GMHeavyCruiserCaliberDamageCoeff": "coeff",
        "GMHECSDamageCoeff": "coeff",
        "GMSHECSDamageCoeff": "coeff",
        "GMSRotationSpeed": "coeff",
        "GMSShotDelay": "coeff",
        "GMSMaxDist": "coeff",
        "GMSIdealRadius": "coeff",
        "GMSCritProb": "coeff",
        "GMSRepairTime": "coeff",
        "GMSDamageCoeff": "coeff",
        "GMSAPDamageCoeff": "coeff",
        "GMSPenetrationCoeffHE": "coeff",
        "GMSSwitchAmmoReloadCoef": "coeff",
        "GMSwitchAmmoReloadCoef": "coeff",
        # ── 副炮 ──
        "GSIdealRadius": "coeff",
        "GSMaxDist": "coeff",
        "GSCritProb": "coeff",
        "GSRepairTime": "coeff",
        "GSShotDelay": "coeff",
        "GSAlphaFactor": "coeff",
        "GSPenetrationCoeffHE": "coeff",
        "GSPriorityTargetIdealRadius": "coeff",
        # ── 防空 ──
        "AAAuraDamageBonus": "raw_int",
        "AACritProb": "coeff",
        "AARepairTime": "coeff",
        "AAExtraBubbles": "raw_int",
        "AABubbleDamageBonus": "raw_int",
        "AABubbleDamage": "coeff",
        "AAAuraDamage": "coeff",
        "AAAuraReceiveDamageCoeff": "coeff",
        "prioritySectorCooldownMultiplier": "coeff",
        "prioritySectorStrengthBonus": "raw_pct",
        # ── 鱼雷 ──
        "GTCritProb": "coeff",
        "GTShotDelay": "coeff",
        "GTRepairTime": "coeff",
        "GTRotationSpeed": "coeff",
        "torpedoSpeedMultiplier": "coeff",
        "torpedoVisibilityFactor": "coeff",
        "torpedoDamageCoeff": "coeff",
        "torpedoRangeCoefficient": "coeff",
        "floodChanceFactorTorpedo": "raw_pct",
        "ignorePTZBonus": "raw_int",
        # ── 声呐 ──
        "pingerCritProb": "coeff",
        "pingerRepairTime": "coeff",
        "pingerWaveSpeedCoeff": "coeff",
        "pingerReloadCoeff": "coeff",
        "hydrophoneUpdateFrequencyCoeff": "coeff",
        "hydrophoneWaveSpeedCoeff": "coeff",
        # ── 舰载机 ──
        "planeExtraHangarSize": "raw_int",
        "planeSpawnTime": "coeff",
        "planeEmptyReturnSpeed": "coeff",
        "planeSpeed": "coeff",
        "planeHealthPerLevel": "raw_int",
        "planeHealthCoeff": "coeff",
        "planeVisibilityFactor": "coeff",
        "bombAlphaDamageMultiplier": "coeff",
        "bombApAlphaDamageMultiplier": "coeff",
        "rocketApAlphaDamageMultiplier": "coeff",
        "diveBomberSpeedMultiplier": "coeff",
        "diveBomberMinSpeedMultiplier": "coeff",
        "diveBomberMaxSpeedMultiplier": "coeff",
        "diveBomberAccuracyIncRateCoeff": "coeff",
        "planeForsageTimeCoeff": "coeff",
        "planeMaxSpeedMultiplier": "coeff",
        "fighterAccuracyIncRateCoeff": "coeff",
        "fighterHealth": "coeff",
        "torpedoBomberHealth": "coeff",
        "diveBomberHealth": "coeff",
        "skipBomberHealth": "coeff",
        "mineBomberHealth": "coeff",
        "fighterAimingTime": "raw_int",
        "torpedoBomberAccuracyIncRateCoeff": "coeff",
        "torpedoBomberAimingTime": "raw_int",
        "skipBomberAccuracyIncRateCoeff": "coeff",
        "skipBomberAimingTime": "raw_int",
        "skipBomberSpeedMultiplier": "coeff",
        "planeTorpedoSpeedMultiplier": "coeff",
        "planeTorpedoArmingTimeCoeff": "coeff",
        "planeAlphaDamageCoeff": "coeff",
        "planeSpreadMultiplier": "coeff",
        "extraFighterCount": "raw_int",
        "callFightersAdditionalPlanesHighLevel": "raw_int",
        "callFightersAdditionalPlanesLowLevel": "raw_int",
        "callFightersRadiusCoeff": "coeff",
        "callFightersAdditionalConsumables": "raw_int",
        "callFightersWorkTimeCoeff": "coeff",
        "callFightersTimeDelayAttack": "coeff",
        # ── 空袭/支援 ──
        "asMaxHealthCoeff": "coeff",
        "asReloadTimeCoeff": "coeff",
        "asNumPacksBonus": "raw_int",
        # ── 深弹、水雷 ──
        "dcReloadTimeCoeff": "coeff",
        "dcAlphaDamageMultiplier": "coeff",
        "dcSplashSizeMultiplier": "coeff",
        "minefieldLifeTimeCoeff": "coeff",
        # ── 起火、进水 ──
        "burnProb": "coeff",
        "floodProb": "coeff",
        "burnTime": "coeff",
        "floodTime": "coeff",
        "burnChanceBonus": "raw_pct",
        "artilleryBurnChanceBonus": "raw_pct",
        "bombBurnChanceBonus": "raw_pct",
        "rocketBurnChanceBonus": "raw_pct",
        "floodChanceCommonBonus": "raw_pct",
        "burnChanceFactorHighLevel": "raw_pct",
        "burnChanceFactorLowLevel": "raw_pct",
        # ── 机动性 ──
        "speedCoef": "coeff",
        "engineBackwardForsageMaxSpeed": "coeff",
        "engineBackwardForsagePower": "coeff",
        "engineBackwardUpTime": "coeff",
        "engineForwardForsageMaxSpeed": "coeff",
        "engineForwardForsagePower": "coeff",
        "engineForwardUpTime": "coeff",
        "SGCritProb": "coeff",
        "SGRepairTime": "coeff",
        "engineCritProb": "coeff",
        "engineRepairTime": "coeff",
        "SGRudderTime": "coeff",
        "buoyancyRudderResetTimeCoeff": "coeff",
        "buoyancyRudderTimeCoeff": "coeff",
        # ── 隐蔽 ──
        "visibilityDistCoeff": "coeff",
        "torpedoDetectionCoefficient": "coeff",
        "mineDetectionCoefficient": "coeff",
        "torpedoDetectionCoefficientByPlane": "coeff",
        "visionXRayMineDist": "coeff",
        "visionXRayTorpedoDist": "coeff",
        # ── 生存性 ──
        "healthHullCoeff": "coeff",
        "healthPerLevel": "coeff",
        "healthRegen": "coeff",
        "regenerationHPSpeed": "coeff",
        "vulnerabilityBurn": "coeff",
        "vulnerabilityFlood": "coeff",
        "vulnerabilityDBomb": "coeff",
        "planeBubbleArmorCoeff": "coeff",
        "critProbCoefficient": "coeff",
        "uwSourceDmgReduction": "coeff",
        "uwCoeffBonus": "raw_pct",
        "batteryRegenCoeff": "coeff",
        "batteryRegenBatteryLastChanceCoeff": "coeff",
        "batteryCapacityCoeff": "coeff",
        "maxBuoyancySpeedCoeff": "coeff",
        "speedBatteryLastChanceCoeff": "coeff",
        "shootShift": "coeff",
        "shootShiftBatteryLastChanceCoeff": "coeff",
        "lastChanceReloadCoefficient": "coeff",
        # ── 消耗品 ──
        "allConsumableReloadTime": "coeff",
        "speedBoostersWorkTimeCoeff": "coeff",
        "planeSmokeGeneratorWorkTimeCoeff": "coeff",
        "smokeGeneratorWorkTimeCoeff": "coeff",
        "scoutReloadCoeff": "coeff",
        "scoutWorkTimeCoeff": "coeff",
        "scoutAdditionalConsumables": "raw_int",
        "crashCrewWorkTimeBonus": "raw_int",
        "crashCrewReloadCoeff": "coeff",
        "crashCrewAdditionalConsumables": "raw_int",
        "crashCrewWorkTimeCoeff": "coeff",
        "hlCritTimeCoeff": "coeff",
        "artilleryBoostersReloadCoeff": "coeff",
        "fighterReloadCoeff": "coeff",
        "airDefenseDispReloadCoeff": "coeff",
        "airDefenseDispWorkTimeCoeff": "coeff",
        "sonarWorkTimeCoeff": "coeff",
        "rlsWorkTimeCoeff": "coeff",
        "ConsumableReloadTime": "coeff",
        "smokeGeneratorLifeTime": "coeff",
        "smokeGeneratorReloadCoeff": "coeff",
        "additionalConsumables": "raw_int",
        "ConsumablesWorkTime": "coeff",
        "planeAdditionalConsumables": "raw_int",
        "healForsageReloadCoeff": "coeff",
        "planeConsumableReloadTime": "coeff",
        "planeConsumablesWorkTime": "coeff",
        "planeConsumableWorkTime": "coeff",
        "regeneratedHPPartCoef": "coeff",
        "regenerateHealthAdditionalConsumables": "raw_int",
        "regenerateHealthWorkTimeCoeff": "coeff",
        "speedBoostersAdditionalConsumables": "raw_int",
        "boostCoeffForsage": "coeff",
        "smokeGeneratorAdditionalConsumables": "raw_int",
        "regenCrewReloadCoeff": "coeff",
        "regenCrewAdditionalConsumables": "raw_int",
        "regenCrewWorkTimeCoeff": "coeff",
        "torpedoReloaderAdditionalConsumables": "raw_int",
        "torpedoReloaderReloadCoeff": "coeff",
        # ── 特殊 ──
        "workTime": "coeff",
    }

    # ── 颜色方向：哪些词条是"负值=增益" ─────────────────
    # 默认方向为"pos"（正值=增益，标记为绿色；负值=减益，标记为红色）
    # 以下列表中的词条方向为"neg"（负值=增益，标记为绿色；正值=减益，标记为红色）
    # 适用场景：装填时间、修理时间、散布、隐蔽、航速减益等"越低越好"的属性

    # ── 值倍率：需要将存储值乘以固定系数后才能得到真实百分比 ──
    MODIFIER_VALUE_FACTOR: dict[str, float] = {
        "AABubbleDamageBonus": 7.0,   # 42.86 × 7 = +300%
    }

    # ── 符号翻转：显示时取反的词条（原始值为正，但实际效果为减益） ──
    MODIFIER_SIGN_INVERT: set[str] = {
        "ignorePTZBonus",
    }

    # ── 隐藏词条：不显示
    MODIFIER_HIDDEN: set[str] = {
        "massHealReloadCoeff",
        "vampireDamageReloadCoeff",
    }

    # ── 单位后缀：各词条数值后附加的单位 ──
    MODIFIER_UNIT_MAP: dict[str, str] = {
        "fighterAimingTime": "s",
        "torpedoBomberAimingTime": "s",
        "skipBomberAimingTime": "s",
        "crashCrewWorkTimeBonus": "s",
        "ignorePTZBonus": "%",
    }
    # 默认方向为"pos"（正值=增益，标记为绿色；负值=减益，标记为红色）
    # 以下列表中的词条方向为"neg"（负值=增益，标记为绿色；正值=减益，标记为红色）
    # 适用场景：装填时间、修理时间、散布、隐蔽、航速减益等"越低越好"的属性
    MODIFIER_COLOR_NEG: set[str] = {
        # ── 主炮 ──
        "GMShotDelay", "GMSShotDelay",
        "GMIdealRadius", "GMSIdealRadius",
        "GMRepairTime", "GMSRepairTime", "GMCritProb", "GMSCritProb",
        "GMSSwitchAmmoReloadCoef", "GMSwitchAmmoReloadCoef",
        "GMBigGunVisibilityCoeff",
        # ── 副炮 ──
        "GSShotDelay", "GSIdealRadius", "GSRepairTime", "GSCritProb",
        "GSPriorityTargetIdealRadius",
        # ── 防空 ──
        "AARepairTime", "AACritProb",
        "prioritySectorCooldownMultiplier",
        # ── 鱼雷 ──
        "GTShotDelay", "GTRepairTime", "GTCritProb", "GTRotationSpeed",
        "torpedoVisibilityFactor", "planeTorpedoArmingTimeCoeff",
        "ignorePTZBonus",
        # ── 声呐 ──
        "pingerRepairTime", "pingerCritProb", "pingerReloadCoeff",
        # ── 舰载机 ──
        "planeSpawnTime", 
        "planeVisibilityFactor",
        "planeSpreadMultiplier",
        "callFightersTimeDelayAttack",
        # ── 空袭/支援 ──
        "asReloadTimeCoeff",
        # ── 深弹 ──
        "dcReloadTimeCoeff",
        # ── 机动性 ──
        "SGRepairTime", "SGCritProb", "engineRepairTime", "engineCritProb",
        "SGRudderTime", "buoyancyRudderTimeCoeff",
        "buoyancyRudderResetTimeCoeff",
        "engineBackwardUpTime", "engineForwardUpTime",
        # —— 起火/进水 ──
        "burnTime", "floodTime",
        "burnProb", "floodProb",
        # ── 隐蔽 ──
        "visibilityDistCoeff",
        "torpedoDetectionCoefficient", "mineDetectionCoefficient",
        "torpedoDetectionCoefficientByPlane",
        # ── 生存性 ──
        "critProbCoefficient",
        "vulnerabilityBurn", "vulnerabilityFlood", "vulnerabilityDBomb",
        "planeBubbleArmorCoeff", "uwSourceDmgReduction",
        # ── 消耗品 ──
        "allConsumableReloadTime", "ConsumableReloadTime",
        "scoutReloadCoeff", "crashCrewReloadCoeff",
        "artilleryBoostersReloadCoeff", "fighterReloadCoeff",
        "airDefenseDispReloadCoeff", "smokeGeneratorReloadCoeff",
        "regenCrewReloadCoeff", "torpedoReloaderReloadCoeff",
        "healForsageReloadCoeff", "planeConsumableReloadTime",
        # ── 特殊 ──
        "hlCritTimeCoeff",
    }

    @staticmethod
    def get_modifier_color(key: str, value: float | int) -> str:
        """根据词条规则返回数值颜色 CSS 字符串，空字符串表示不指定颜色。"""
        fmt = Mapping.MODIFIER_FORMAT_MAP.get(key, "coeff")
        av = abs(value)
        if av < 0.001:
            return ""
        # 注：值倍率不影响符号/方向，因此此处不应用 MODIFIER_VALUE_FACTOR
        # 符号翻转
        if key in Mapping.MODIFIER_SIGN_INVERT:
            value = -value
        if fmt == "coeff" and abs(value - 1.0) < 0.001:
            return ""
        is_neg_dir = key in Mapping.MODIFIER_COLOR_NEG
        if fmt == "coeff":
            is_increase = value > 1.0
        else:
            is_increase = value > 0
        is_buff = (not is_neg_dir and is_increase) or (is_neg_dir and not is_increase)
        return "#4caf50" if is_buff else "#f44336"

    @staticmethod
    def format_modifier(key: str, value: float | int, *, color: bool = False) -> str:
        """根据词条规则格式化修饰符数值，返回显示文本。
        当 color=True 时返回带 HTML 颜色标签的文本：
          - pos方向：正数绿色(#4caf50)、负数红色(#f44336)
          - neg方向：负数绿色(#4caf50)、正数红色(#f44336)
        """
        if key in Mapping.MODIFIER_HIDDEN:
            return ""
        fmt = Mapping.MODIFIER_FORMAT_MAP.get(key, "coeff")
        av = abs(value)
        if av < 0.001:
            return ""
        # 应用值倍率（存储值 × 系数 = 真实百分比）
        factor = Mapping.MODIFIER_VALUE_FACTOR.get(key, 1.0)
        value = value * factor
        # 符号翻转：存储值与实际效果符号相反
        invert = key in Mapping.MODIFIER_SIGN_INVERT
        if invert:
            value = -value
        if fmt == "coeff":
            if abs(value - 1.0) < 0.001:
                return ""
            pct = (value - 1.0) * 100
            text = f"{pct:+.1f}%"
        elif fmt == "raw_pct":
            pct = value * 100
            text = f"{pct:+.1f}%"
        elif fmt == "raw_int":
            iv = int(value)
            text = f"{iv:+.0f}"
        else:
            text = f"{value:+.1f}"
        unit = Mapping.MODIFIER_UNIT_MAP.get(key, "")
        if unit:
            text += unit
        if color:
            # 颜色判断传入原始值（未翻转），由 get_modifier_color 自行处理符号翻转
            raw_for_color = -value if invert else value
            clr = Mapping.get_modifier_color(key, raw_for_color)
            if clr:
                text = f'<span style="color:{clr};">{text}</span>'
        return text

    @staticmethod
    def rich_tooltip(text: str) -> str:
        """将可能包含 HTML 标记的文本转为适合 QWidget.setToolTip 的富文本格式。
        
        Qt 的 tooltip 仅在文本以 '<' 开头时才启用富文本渲染，否则会将 HTML
        标签原文显示。此方法确保：
          - 检测到 HTML 标记时，整个文本包裹在 <html> 标签内
          - 将 \\n 替换为 <br/>（HTML 模式下 \\n 不换行）
        """
        if "<" not in text or ">" not in text:
            return text
        text = text.replace("\n", "<br/>")
        text = text.replace("\r", "")
        if not text.strip().startswith("<html"):
            text = f"<html>{text}</html>"
        return text

    TRIGGER_TYPE_MAP = {
        "enemyVehiclesDead": "敌方舰艇被击沉", "rageMode": "激活作战指令",
        "ribbons": "获得特定数量勋带", "achievement": "获得特定成就",
        "damage": "受到特定伤害", "health": "战舰血量低于特定值",
    }

    DAMAGE_TYPE_MAP = {"2": "潜在伤害"}
    ACHIEVEMENT_MAP = {}

    RIBBON_MAP = {
        "0": "主炮命中", "1": "鱼雷命中", "2": "炸弹命中",
        "3": "击落飞机", "5": "已摧毁", "7": "造成进水",
        "8": "命中装甲区", "10": "副炮命中", "12": "火箭弹命中",
        "13": "副炮组命中", "14": "主炮过度击穿", "15": "主炮击穿",
        "16": "主炮未击穿", "17": "主炮跳弹", "19": "发现",
        "20": "战略贡献", "28": "主炮命中防雷鼓包", "47": "掩护",
        "56": "吸引火力", "59": "协助校射",
    }

    RIBBON_MAP_CREW = {
        "0": "主炮命中", "1": "鱼雷命中", "2": "炸弹命中",
        "3": "击落飞机", "5": "已摧毁", "7": "造成进水",
        "8": "命中装甲区", "10": "副炮命中", "12": "火箭弹命中",
        "13": "战斗机击落飞机", "14": "主炮过度击穿",
        "15": "主炮击穿", "16": "主炮未击穿", "17": "主炮跳弹",
        "19": "发现", "20": "战略贡献", "28": "主炮命中防雷鼓包",
        "47": "掩护", "56": "吸引火力", "59": "协助校射",
    }

    DEPTH_MAP = {
        "SURFACE": "水面", "PERISCOPE": "潜望镜深度",
        "DEEP_WATER": "工作深度", "DEEP_WATER_INVUL": "最大深度",
    }
