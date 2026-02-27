class Mapping:
    # 加成词条
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
        "GMPenetrationCoeffHE": "主炮高爆弹穿深",
        "artilleryKruppMultiplier": "主炮穿甲弹穿深",
        # 副炮
        "GSIdealRadius": "副炮炮弹的最大误差",
        "GSMaxDist": "副炮射程",
        "GSCritProb": "副炮瘫痪的风险",
        "GSRepairTime": "副炮修理时间",
        "GSShotDelay": "副炮装填时间",
        "GSAlphaFactor": "副炮炮弹伤害",
        "GSPenetrationCoeffHE": "副炮高爆弹穿深",
        # 防空炮
        "AAAuraDamageBonus": "在远程防空炮区域的持续伤害",
        "AACritProb": "防空炮瘫痪的风险",
        "AARepairTime": "防空炮修理时间",
        "AAExtraBubbles": "防空齐射炮弹爆炸次数",
        "AABubbleDamageBonus": "防空炮弹爆炸伤害",
        "AAAuraDamage": "防空炮每秒伤害",
        # 鱼雷发射管
        "GTCritProb": "鱼雷发射管瘫痪的风险",
        "GTShotDelay": "鱼雷发射管装填时间",
        "GTRepairTime": "鱼雷管修理时间",
        "GTRotationSpeed": "鱼雷管回转速度",
        "torpedoSpeedMultiplier": "鱼雷航速",
        "torpedoVisibilityFactor": "鱼雷对海被侦察范围",
        "torpedoDamageCoeff": "鱼雷伤害",
        "torpedoRangeCoefficient": "鱼雷射程",
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
        "healthRegen": "每秒回复血量",
        "vulnerabilityBurn": "受到的火灾伤害",
        "vulnerabilityFlood": "受到的进水伤害",
        # 消耗品
        "allConsumableReloadTime": "消耗品的准备和装填时间",
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

    # 国家名称
    NATION_MAP = {
        "USA": "美国", "Japan": "日本", "Germany": "德国", "Russia": "苏联",
        "United_Kingdom": "英国", "France": "法国", "Italy": "意大利",
        "Pan_Asia": "泛亚", "Europe": "欧洲", "Netherlands": "荷兰",
        "Commonwealth": "英联邦", "Pan_America": "泛美", "Spain": "西班牙",
        "Events": "其他"
    }

    # 舰船状态
    SHIP_GROUP_MAP = {
        "start": "初始", "preserved": "已移除", "upgradeable": "可研发", "earlyAccess": "抢先体验",
        "superShip": "超级战舰", "premium": "加值", "ultimate": "特殊", "special": "特殊",
        "specialUnsellable": "特殊", "disabled": "禁用", "clan": "仅军团", "coopOnly": "仅人机",
        "demoWithoutStatsPrem": "加值测试", "demoWithoutStats": "测试", "unavailable": "不可用"
    }

    # 舰船等级
    LEVEL_MAP = ["0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "★"]

    # 武器种类
    WEAPON_SPECIES_MAP = {
        "Main": "主炮",
        "Secondary": "副炮",
        "Torpedo": "鱼雷发射管",
        "AAircraft": "防空炮",
        "DCharge": "深弹发射器"
    }

    # 舰种名称
    SHIP_CLASS_MAP = {
        "Destroyer": "驱逐舰",
        "Cruiser": "巡洋舰",
        "Battleship": "战列舰",
        "AirCarrier": "航空母舰",
        "Submarine": "潜艇",
        "Auxiliary": "其他类型",
        "default": "默认"
    }

    AIRCRAFT_CLASS_MAP = {
        "Bomber": "鱼雷轰炸机",
        "Dive": "俯冲轰炸机",
        "Fighter": "战斗机",
        "Mine": "水雷轰炸机",
        "Scout": "侦察机",
        "Skip": "弹跳轰炸机",
        "Auxiliary": "其他飞机",
    }

    # 弹种类型
    AMMO_TYPE_MAP = {
        "HE": "HE",
        "AP": "AP",
        "CS": "SAP",
    }

    # 投射物类型
    PROJECTILE_TYPE_MAP = {
        "Artillery": "火炮炮弹",
        "Bomb": "炸弹",
        "DepthCharge": "深水炸弹",
        "Laser": "激光",
        "Rocket": "火箭弹",
        "Torpedo": "鱼雷",
        "Wave": "波浪"
    }

    # 深度状态
    BUOYANCY_MAP = {
        "SURFACE": "水面状态",
        "PERISCOPE": "潜望镜深度",
        "SEMI_DEEP_WATER": "半潜深度",
        "DEEP_WATER": "作业深度",
        "DEEP_WATER_INVUL": "最大深度"
    }

    # 战斗指令相关
    DETAIL_MAP = {
        "requiredCount": "所需次数",
        "radius": "有效半径",
        "separateTracking": "独立计数",
        "subRibbons": "有效勋带",
        "timeLimit": "时间限制",
        "progress": "进度",
        "progressName": "进度标识",
        "stateName": "状态标识",
        "RibbonActivator": "缎带/勋章触发",
        "RageModeProgressAction": "累加战斗指令进度",
        "healPerSecond": "每秒回复血量",
        "duration": "持续时间",
        "triggerName": "触发标识",
        "isRepeating": "可重复",
        "isVisible": "是否显示",
        "isEnabled": "是否启用",
        "consumableTypes": "消耗品类型",
        "count": "数量",
        "potentialDamageShift": "所受的潜在伤害",
        "planeName": "飞机型号",
        "reduceTime": "减少整备时间",
    }

    # 特定勋带（对应顺序为推测）
    RIBBON_MAP = {
        "13": "副炮组命中",
        "14": "主炮过度击穿",
        "15": "主炮击穿",
        "16": "主炮未击穿",
        "17": "主炮跳弹",
        "19": "发现",
        "28": "主炮命中防雷鼓包",
        "47": "掩护",
        "56": "吸引火力",
        "59": "协助校射",
    }

    # 深度
    DEPTH_MAP = {
        "SURFACE": "水面",
        "PERISCOPE": "潜望镜深度",
        "DEEP_WATER": "工作深度",
        "DEEP_WATER_INVUL": "最大深度",
    }