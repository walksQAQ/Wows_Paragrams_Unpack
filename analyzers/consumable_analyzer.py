"""
ConsumableAnalyzer —— 消耗品数据分析器。
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from analyzers.base_analyzer import BaseAnalyzer
from analyzers.ship_analyzer import TextCollector
from models.analysis_result import AnalysisResult


class ConsumableAnalyzer(BaseAnalyzer):

    KNOWN_TYPES = {
        "crashCrew", "regenCrew", "airDefenseDisp", "fighter", "scout",
        "smokeGenerator", "speedBoosters", "sonar", "torpedoReloader", "rls",
        "artilleryBoosters", "healForsage", "callFighters", "regenerateHealth",
        "depthCharges", "hydrophone", "fastRudders", "subsEnergyFreeze",
        "submarineLocator", "planeSmokeGenerator", "vampireDamage", "supportBuoy",
    }

    def __init__(self, log_func: Optional[Callable[[str], None]] = None):
        super().__init__(log_func)
        self.consumable_name_map: dict = {}
        self.plane_name_mapping: dict = {}

    def initialize_mapping(self) -> None:
        self.consumable_name_map = self.load_json_mapping("consumable_names.json")
        self.plane_name_mapping = self.load_json_mapping("plane_names.json")
        self._log("ConsumableAnalyzer 映射表已同步")

    def _make_info(self, item_name: str, config: dict) -> dict | None:
        """从 config 提取标准 info 字典"""
        if not isinstance(config, dict):
            return None
        return {
            "name": item_name,
            "type": config.get("consumableType"),
            "num": config.get("numConsumables", 0),
            "workTime": config.get("workTime", 0),
            "preparationTime": config.get("preparationTime", 0),
            "reloadTime": config.get("reloadTime", 0),
            "isAutoConsumable": config.get("isAutoConsumable", False),
            "isInterceptor": config.get("isInterceptor", False),
            "regenHPSpeed": config.get("regenerationHPSpeed", 0),
            "areaDmgMultiplier": config.get("areaDamageMultiplier", 0),
            "bubbleDmgMultiplier": config.get("bubbleDamageMultiplier", 0),
            "fighterName": config.get("fightersName", "Unknown"),
            "fighterNum": config.get("fightersNum", 0),
            "radiusToKill": config.get("distanceToKill", 0),
            "dogFightTime": config.get("dogFightTime", 0),
            "flyAwayTime": config.get("flyAwayTime", 0),
            "flightClimbAngle": config.get("climbAngle", 0),
            "radius": config.get("radius", 0),
            "timeDelayAtk": config.get("timeDelayAttack", 0),
            "timeWaitDelayAtk": config.get("timeWaitDelayAttack", 0),
            "gunsDistCoeff": config.get("artilleryDistCoeff", 0),
            "speedLimit": config.get("speedLimit", 0),
            "height": config.get("height", 0),
            "lifeTime": config.get("lifeTime", 0),
            "forwardEngForsag": config.get("forwardEngineForsag", 0),
            "forwardEngForsagMaxSpd": config.get("forwardEngineForsagMaxSpeed", 0),
            "backwardEngForsag": config.get("backwardEngineForsag", 0),
            "backwardEngForsagMaxSpd": config.get("backwardEngineForsagMaxSpeed", 0),
            "boostCoeff": config.get("boostCoeff", 0),
            "distShip": config.get("distShip", 0),
            "distTorpedo": config.get("distTorpedo", 0),
            "distMine": config.get("distSeaMine", 0),
            "torpedoReloadTime": config.get("torpedoReloadTime", 0),
            "affectedClasses": config.get("affectedClasses", []),
            "hpUpdFreq": config.get("hydrophoneUpdateFrequency", 0),
            "hpWaveRadius": config.get("hydrophoneWaveRadius", 0),
            "zoneLifeTime": config.get("zoneLifeTime", 0),
            "canUseOnEmpty": config.get("canUseOnEmpty", False),
            "activationDelay": config.get("activationDelay", 0),
            "buoyancyRudderTimeCoeff": config.get("buoyancyRudderTimeCoeff", 0),
            "maxBuoyancySpeedCoeff": config.get("maxBuoyancySpeedCoeff", 0),
            "battleDropActTime": config.get("battleDropActivationTime", 0),
            "battleDropVisualName": config.get("battleDropVisualName", "Unknown"),
            "supportBuoyZoneLifetime": config.get("zoneLifetime", 0),
            "buffDuration": config.get("buffDuration", 0),
            "buffZoneRadius": config.get("buffZoneRadius", 0),
            "damageGMHealCoeff": config.get("modifiers", {}).get("damageGMHealCoeff", 0),
        }

    def analyze(self, raw_data: dict) -> AnalysisResult:
        from models.name_mapping import Mapping as NM
        t = TextCollector()

        display_name = self.consumable_name_map.get(
            raw_data.get('name', '').upper(), raw_data.get('name', '未知')
        )
        t.writeln(f"消耗品名称: {display_name}")
        t.writeln(f"消耗品编号: {raw_data.get('index')}")
        t.writeln(f"消耗品ID: {raw_data.get('id')}")
        t.writeln("=" * 30)
        t.writeln()

        for item_name, config in raw_data.items():
            if not isinstance(config, dict) or item_name in ["typeinfo", "custom"]:
                continue

            info = self._make_info(item_name, config)
            if not info or not info.get('type'):
                continue

            if info['type'] not in self.KNOWN_TYPES:
                t.writeln(f"[警告] 类型未匹配: {info['type']}")
                t.writeln(f"消耗品标识: {item_name}")
                t.writeln(json.dumps(config, indent=2, ensure_ascii=False))
                t.writeln("-" * 20)
                continue

            num_display = "无限" if info['num'] == -1 else info['num']
            auto_str = "是" if info['isAutoConsumable'] else "否"
            prep_str = "（该消耗品无准备时间）" if info['preparationTime'] == 0 else ""

            t.writeln(f"[{info['name']}]")
            t.writeln(f"  类型: {info['type']}")
            t.writeln(f"  基础可用数量: {num_display}")
            t.writeln(f"  是否自动使用: {auto_str}")
            t.writeln(f"  准备时间: {info['preparationTime']}s{prep_str} / 冷却: {info['reloadTime']}s / 持续: {info['workTime']}s")
            t.writeln(f"  消耗品效果:")

            ct = info['type']
            if ct == "crashCrew":
                t.writeln(f"    扑灭起火、清除进水、并修复受损配件。")
            elif ct == "regenCrew":
                t.writeln(f"    每秒回复血量: {'+' if info['regenHPSpeed'] > 0 else ''}{info['regenHPSpeed'] * 100}%")
            elif ct == "airDefenseDisp":
                t.writeln(f"    防空区域秒伤: {'+' if info['areaDmgMultiplier'] > 0 else ''}{info['areaDmgMultiplier'] * 100}%")
                t.writeln(f"    黑云伤害: {'+' if info['bubbleDmgMultiplier'] > 0 else ''}{info['bubbleDmgMultiplier'] * 100}%")
            elif ct == "fighter":
                fn = self.plane_name_mapping.get(info.get('fighterName', '').upper(), info.get('fighterName', '未知'))
                t.writeln(f"    战斗机名称: {fn}")
                t.writeln(f"    数量: {info['fighterNum']} | 截击机: {'是' if info['isInterceptor'] else '否'}")
                t.writeln(f"    狗斗: {info['dogFightTime']}s | 离开: {info['flyAwayTime']}s")
                t.writeln(f"    巡逻半径: {info['radiusToKill'] / 10}km")
            elif ct == "scout":
                dc = info['gunsDistCoeff'] - 1
                t.writeln(f"    主炮射程 {'+' if dc > 0 else ''}{dc * 100:.2f}%")
            elif ct == "smokeGenerator":
                t.writeln(f"    烟雾生成半径: {info['radius'] * 3}m | 高度: {info['height']}m")
                t.writeln(f"    速度限制: {info['speedLimit']}kts | 扩散: {info['lifeTime']}s")
            elif ct == "speedBoosters":
                t.writeln(f"    最高航速: {'+' if info['boostCoeff'] > 0 else ''}{info['boostCoeff'] * 100}%")
                t.writeln(f"    推力: 前进{'+' if info['forwardEngForsag'] > 0 else ''}{info['forwardEngForsag'] * 100}% / 后退{'+' if info['backwardEngForsag'] > 0 else ''}{info['backwardEngForsag'] * 100}%")
            elif ct == "sonar":
                t.writeln(f"    舰船探测: {info['distShip'] * 0.03:.2f} km")
                t.writeln(f"    鱼雷探测: {info['distTorpedo'] * 0.03:.2f} km")
                t.writeln(f"    水雷探测: {info['distMine'] * 0.03:.2f} km")
            elif ct == "torpedoReloader":
                t.writeln(f"    鱼雷装填时间: {info['torpedoReloadTime']}s")
            elif ct == "rls":
                t.writeln(f"    舰船探测: {info['distShip'] * 0.03:.2f} km")
                if info['affectedClasses']:
                    cls_str = ', '.join(NM.SHIP_CLASS_MAP.get(c, c) for c in info['affectedClasses'])
                    t.writeln(f"    限制探测舰种: {cls_str}")
            elif ct == "artilleryBoosters":
                bc = info['boostCoeff'] - 1
                t.writeln(f"    主炮装填时间: {'+' if bc > 0 else ''}{bc * 100:.2f}%")
            elif ct == "depthCharges":
                t.writeln(f"    半径: {info['radius'] * 0.003:.2f}km")
            elif ct == "hydrophone":
                t.writeln(f"    虚影存留: {info['zoneLifeTime']}s | 刷新: {info['hpUpdFreq']}s")
                t.writeln(f"    视野距离: {info['hpWaveRadius'] * 0.001:.2f}km")
            elif ct == "fastRudders":
                brt = info['buoyancyRudderTimeCoeff'] - 1
                bsc = info['maxBuoyancySpeedCoeff'] - 1
                t.writeln(f"    水平舵换挡: {'+' if brt > 0 else ''}{brt * 100:.2f}%")
                t.writeln(f"    上浮/下潜速度: {'+' if bsc > 0 else ''}{bsc * 100:.2f}%")
            elif ct == "subsEnergyFreeze":
                t.writeln(f"    启用后下潜能力将停止消耗")
                t.writeln(f"    可在电池耗尽时启用: {'是' if info['canUseOnEmpty'] else '否'}")
            elif ct == "submarineLocator":
                t.writeln(f"    舰船探测: {info['distShip'] * 0.03:.2f} km")
            elif ct == "planeSmokeGenerator":
                t.writeln(f"    生效延迟: {info['activationDelay']}s")
                t.writeln(f"    烟雾半径: {info['radius'] * 3}m")
            elif ct == "supportBuoy":
                t.writeln(f"    区域: {info.get('battleDropVisualName', '')}")
                t.writeln(f"    布置时间: {info.get('battleDropActTime', 0)}s")
                t.writeln(f"    持续时间: {info.get('supportBuoyZoneLifetime', 0)}s")
            elif ct == "vampireDamage":
                t.writeln(f"    伤害转化系数: {info.get('damageGMHealCoeff', 0) * 100:.2f}%")
            t.writeln("-" * 20)
            t.writeln()

        return t.result(title=display_name, subtitle=f"编号: {raw_data.get('index')}")
