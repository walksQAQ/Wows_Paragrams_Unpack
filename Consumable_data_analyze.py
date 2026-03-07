import json
import os
import sys
import tkinter as tk

from NameMapping import Mapping as NameMapping

class ConsumableAnalyzer:
    def __init__(self, log_func=None):
        # 兼容打包路径逻辑
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_func = log_func
        self.ability_map = {}
        self.consumable_name_map = {}
        self.plane_name_mapping = {}

    def initialize_mapping(self):
        """预留翻译映射初始化接口，保持与 DataViewer 调用的兼容性"""
        self.load_consumable_name_map()
        self.load_plane_name_mapping()
        self._log("消耗品解析器映射表已同步")

    # 加载映射表
    def reload_mappings(self):
        """
        供外部（MainUI）调用的重新初始化接口
        当 POToolkit 更新了 json 文件后，点击按钮即可刷新内存中的字典
        """
        self.log_func("正在重新加载本地化数据...")
        # 重新执行一遍所有的加载方法
        self.initialize_mapping()
        self.log_func("数据刷新完成。")

    def load_consumable_name_map(self):
        file_path = os.path.join(self.base_dir, "data", "consumable_names.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_json = json.load(f)
                    self.consumable_name_map = {k.upper(): v for k, v in raw_json.items()}
        except Exception as e:
            self.log_func(f"读取消耗品名映射出错: {e}")

    def load_plane_name_mapping(self):
        plane_json_path = os.path.join(self.base_dir, "data", "plane_names.json")
        if os.path.exists(plane_json_path):
            try:
                with open(plane_json_path, 'r', encoding='utf-8') as f:
                    self.plane_name_mapping = json.load(f)
            except Exception as e:
                self._log(f"加载飞机翻译失败: {e}")

    def _log(self, message):
        """内部日志工具"""
        if self.log_func:
            self.log_func(message)
        else:
            print(message)

    def _fill_map(self, data):
        """纯数据处理逻辑：填充字典"""
        for item_name, config in data.items():
            if not isinstance(config, dict): continue

            # 提取数据存入 ability_map 供 Ship 模块使用
            self.ability_map[item_name] = {
                "name": item_name,
                "type": config.get("consumableType"),
                "workTime": config.get("workTime", 0),
                "preparationTime": config.get("preparationTime", 0),
                "reloadTime": config.get("reloadTime", 0),
                "num": config.get("numConsumables", 0),
                "isAutoConsumable": config.get("isAutoConsumable", False),
                "buoyancyStates": config.get("availableBuoyancyStates", []),  # 提取列表
                "regenHPSpeed": config.get("regenerationHPSpeed", 0),
                "areaDmgMultiplier": config.get("areaDamageMultiplier", 0),
                "bubbleDmgMultiplier": config.get("bubbleDamageMultiplier", 0),
                "fighterName": config.get("fightersName", "Unknown"),
                "fighterNum": config.get("fightersNum", 0),
                "radiusToKill": config.get("distanceToKill", 0),
                "dogFightTime": config.get("dogFightTime", 0),
                "flyAwayTime": config.get("flyAwayTime", 0),
                "flightClimbAngle": config.get("climbAngle", 0),
                "isInterceptor": config.get("isInterceptor", False),
                "radius": config.get("radius", 0),
                "timeDelayAtk": config.get("timeDelayAttack", 0),
                "timeToTryingCatch": config.get("timeToTryingCatch", 0),
                "timeWaitDelayAtk": config.get("timeWaitDelayAttack", 0),
                "gunsDistCoeff": config.get("artilleryDistCoeff", 0),
                "speedLimit": config.get("speedLimit", 0),
                "height": config.get("height", 0),
                "startDelay": config.get("startDelayTime", 0),
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
                "buoyancyRudderResetTimeCoeff": config.get("buoyancyRudderResetTimeCoeff", 0),
                "buoyancyRudderTimeCoeff": config.get("buoyancyRudderTimeCoeff", 0),
                "maxBuoyancySpeedCoeff": config.get("maxBuoyancySpeedCoeff", 0),
                "underwaterMaxRudderAngleCoeff": config.get("underwaterMaxRudderAngleCoeff", 0),
                "canUseOnEmpty": config.get("canUseOnEmpty", False),
                "activationDelay": config.get("activationDelay", 0),
                "updatePeriod": config.get("updatePeriod", 0),
                "damageGMHealCoeff": config.get("modifiers", {}).get("damageGMHealCoeff", 0),
                "gmIdealRadius": config.get("GMIdealRadius", 0),
                "gmShotDelay": config.get("GMShotDelay", 0),
                "gsIdealRadius": config.get("GSIdealRadius", 0),
                "gsMaxDistDetail": config.get("GSMaxDist", {}),
                "gsShotDelay": config.get("GSShotDelay", 0),
                "gtShotDelay": config.get("GTShotDelay", 0),
                "battleDropActTime": config.get("battleDropActivationTime", 0),
                "battleDropName": config.get("battleDropName", "Unknown"),
                "battleDropVisualName": config.get("battleDropVisualName", "Unknown"),
                "speedCoef": config.get("speedCoef",0),
                "vulnerability": config.get("vulnerabilityAll", 0),
                "rudderTime": config.get("SGRudderTime", 0),
                "rudderPower": config.get("SGRudderPower", 0),
                "buffDuration": config.get("buffDuration", 0),
                "buffZoneRadius": config.get("buffZoneRadius", 0),
                "supportBuoyZoneLifetime": config.get("zoneLifetime", 0),
                "healthRegenPercent": config.get("healthRegenPercent", 0),
            }

    def analyze(self, display_area, data):
        if not isinstance(data, dict): return
        self._fill_map(data)

        # 1. 先提取所有消耗品配置，并过滤掉非消耗品条目
        consumable_items = [
            (name, cfg) for name, cfg in data.items()
            if isinstance(cfg, dict) and name not in ["typeinfo", "custom"]
        ]

        if not consumable_items:
            return

        # 2. 打印一次性表头（假设 data 本身包含该消耗品的通用名称和 ID）
        display_name = self.consumable_name_map.get(data.get('name', '').upper(), data.get('name', '未知'))
        header = (f"消耗品名称: {display_name}\n"
                  f"消耗品编号: {data.get('index')}\n"
                  f"消耗品ID: {data.get('id')}\n"
                  f"{'=' * 30}\n")
        display_area.insert(tk.END, header)

        # 3. 循环渲染各个配置项的细节
        for item_name, config in consumable_items:
            info = self.ability_map.get(item_name)
            if not info: continue

            # 这里仅生成该条配置的详细参数
            output = self._generate_detail_text(info)
            display_area.insert(tk.END, "".join(output) + "\n" + "-" * 20 + "\n")

    def _generate_detail_text(self, info):
        output = []

        if info['num'] == -1:
            num_display = "无限"
        else:
            num_display = info['num']
        isAutoConsumable = "是" if info['isAutoConsumable'] else "否"
        isInterceptor = "是" if info['isInterceptor'] else "否"
        isNoPreparaTime = "（该消耗品无准备时间）" if info['preparationTime'] == 0 else ""

        output.append(f"[消耗品标识]: {info['name']}\n"
                          f"  - 类型: {info['type']}\n"
                          f"  - 基础可用数量: {num_display}\n"
                          f"  - 是否自动使用: {isAutoConsumable}\n"
                          f"  - 准备时间: {info['preparationTime']}s{isNoPreparaTime} / 冷却时间: {info['reloadTime']}s / 持续时间: {info['workTime']}s\n")

        output.append(f"\n消耗品效果:\n")
        # 类型特有数据展示
        if info['type'] == "crashCrew":
            output.append(f"  - 扑灭起火、清除进水、并修复受损配件。阻止敌方潜艇发射的鱼雷进行导向。\n")
        elif info['type'] == "regenCrew":
            data_type = "+" if info['regenHPSpeed'] > 0 else ""
            output.append(f"  - 每秒回复血量: {data_type}{info['regenHPSpeed'] * 100}%\n")
        elif info['type'] == "airDefenseDisp":
            data_type_1 = "+" if info['areaDmgMultiplier'] > 0 else ""
            data_type_2 = "+" if info['bubbleDmgMultiplier'] > 0 else ""
            output.append(f"  - 防空区域秒伤: {data_type_1}{info['areaDmgMultiplier'] * 100}%\n")
            output.append(f"  - 黑云伤害: {data_type_2}{info['bubbleDmgMultiplier'] * 100}%\n")
        elif info['type'] == "fighter":
            raw_name = info.get('fighterName', '未知')
            display_plane_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)
            output.append(f"  - 战斗机名称: {display_plane_name}\n"
                          f"  - 战斗机数量: {info['fighterNum']}\n"
                          f"  - 截击机: {isInterceptor}\n"
                          f"  - 狗斗时间: {info['dogFightTime']}s\n"
                          f"  - 离开时间: {info['flyAwayTime']}s\n"
                          f"  - 战斗机爬升角度: {info['flightClimbAngle']}°\n"
                          f"  - 巡逻半径: {info['radiusToKill'] / 10}km\n"
                          # f"  - 尝试攻击时间: {info['timeToTryingCatch']}s\n"
                          f"  - 索敌时间: {info['timeDelayAtk']}s / 瞄准时间: {info['timeWaitDelayAtk']}s\n")
        elif info['type'] == "scout":
            DistCoeff = info['gunsDistCoeff'] - 1
            data_type = "+" if DistCoeff > 0 else ""
            output.append(f"  - 主炮射程 {data_type}{DistCoeff * 100:.2f}%\n")
        elif info['type'] == "smokeGenerator":
            output.append(f"  - 烟雾生成半径: {info['radius'] * 3}m\n"
                          f"  - 烟雾生成高度: {info['height']}m\n"
                          f"  - 烟雾生成速度限制: {info['speedLimit']}kts\n"
                          f"  - 烟雾扩散时间: {info['lifeTime']}s\n")
        elif info['type'] == "speedBoosters":
            data_type_1 = "+" if info['boostCoeff'] > 0 else ""
            data_type_2 = "+" if info['forwardEngForsag'] > 0 else ""
            data_type_3 = "+" if info['backwardEngForsag'] > 0 else ""
            data_type_4 = "+" if info['forwardEngForsagMaxSpd'] > 0 else ""
            data_type_5 = "+" if info['backwardEngForsagMaxSpd'] > 0 else ""
            output.append(f"  - 最高航速: {data_type_1}{info['boostCoeff'] * 100}%\n"
                          f"  - 推力加成: 前进{data_type_2}{info['forwardEngForsag'] * 100}% / 后退{data_type_3}{info['backwardEngForsag'] * 100}% \n"
                          f"  - 加速最大速度倍率: 前进{data_type_4}{info['forwardEngForsagMaxSpd']} / 后退{data_type_5}{info['backwardEngForsagMaxSpd']}\n")
        elif info['type'] == "sonar":
            ship_dist = info['distShip'] * 0.03
            torp_dist = info['distTorpedo'] * 0.03
            mine_dist = info['distMine'] * 0.03
            output.append(f"  - 舰船探测距离: {ship_dist:.2f} km\n"
                          f"  - 鱼雷探测距离: {torp_dist:.2f} km\n"
                          f"  - 水雷探测距离: {mine_dist:.2f} km\n")
        elif info['type'] == "torpedoReloader":
            output.append(f"  - 鱼雷装填时间: {info['torpedoReloadTime']}s\n")
        elif info['type'] == "rls":
            ship_dist = info['distShip'] * 0.03
            classes = info.get("affectedClasses", [])
            output.append(f"  - 舰船探测距离: {ship_dist:.2f} km\n")
            if classes:
                class_str = ", ".join([NameMapping.SHIP_CLASS_MAP.get(c, c) for c in classes])
                output.append(f"  - 限制探测舰种: {class_str}\n")
        elif info['type'] == "artilleryBoosters":
            BoostCoeff = info['boostCoeff'] - 1
            data_type = "+" if BoostCoeff > 0 else ""
            output.append(f"  - 主炮装填时间: {data_type}{BoostCoeff * 100:.2f}%\n")
        elif info['type'] == "healForsage":
            data_type = "+" if info['boostCoeff'] > 0 else ""
            output.append(f"  - 引擎冷却速度: {data_type}{info['boostCoeff'] * 100}%\n")
        elif info['type'] == "callFighters":
            raw_name = info.get('fighterName', '未知')
            display_plane_name = self.plane_name_mapping.get(raw_name.upper(), raw_name)
            output.append(f"  - 战斗机名称: {display_plane_name}\n"
                          f"  - 战斗机数量: {info['fighterNum']}\n"
                          f"  - 截击机: {isInterceptor}\n"
                          f"  - 狗斗时间: {info['dogFightTime']}s\n"
                          f"  - 离开时间: {info['flyAwayTime']}s\n"
                          f"  - 战斗机爬升角度: {info['flightClimbAngle']}°\n"
                          f"  - 巡逻半径: {info['radiusToKill'] / 10}km\n"
                          # f"  - 尝试攻击时间: {info['timeToTryingCatch']}s\n"
                          f"  - 索敌时间: {info['timeDelayAtk']}s / 瞄准时间: {info['timeWaitDelayAtk']}s\n")
        elif info['type'] == "regenerateHealth":
            output.append(f"  - 恢复飞机中队部分生命值。在敌方战斗机攻击时使用能免于被击毁。\n")
        elif info['type'] == "depthCharges":
            output.append(f"  - 半径: {info['radius'] * 0.003:.2f}km\n")
        elif info['type'] == "hydrophone":
            output.append(f"  - 虚影存留时间: {info['zoneLifeTime']}s\n"
                          f"  - 刷新时间: {info['hpUpdFreq']}s\n"
                          f"  - 视野距离: {info['hpWaveRadius']* 0.001:.2f}km\n")
        elif info['type'] == "fastRudders":
            buoyancyRudderTimeCoeff = info['buoyancyRudderTimeCoeff'] - 1
            buoyancySpeedCoeff = info['maxBuoyancySpeedCoeff'] - 1
            data_type_1 = "+" if buoyancyRudderTimeCoeff > 0 else ""
            data_type_2 = "+" if buoyancySpeedCoeff > 0 else ""
            output.append(f"  - 水平舵换挡时间: {data_type_1}{buoyancyRudderTimeCoeff * 100:.2f}%\n"
                          f"  - 上浮/下潜速度: {data_type_2}{buoyancyRudderTimeCoeff * 100:.2f}%\n")
        elif info['type'] == "subsEnergyFreeze":
            canUseOnEmpty = "是" if info['canUseOnEmpty'] else "否"
            output.append(f"  - 启用此消耗品后，下潜能力将停止消耗。\n"
                          f"  - 可在电池耗尽时启用: {canUseOnEmpty}\n")
        elif info['type'] == "submarineLocator":
            ship_dist = info['distShip'] * 0.03
            output.append(f"  - 舰船探测距离: {ship_dist:.2f} km\n")
        elif info['type'] == "planeSmokeGenerator":
            output.append(f"  - 烟雾生效延迟: {info['activationDelay']}s\n"
                          f"  - 烟雾生成半径: {info['radius'] * 3}m\n"
                          f"  - 烟雾生成高度: {info['height']}m\n"
                          f"  - 烟雾生成速度限制: {info['speedLimit']}kts\n"
                          f"  - 烟雾扩散时间: {info['lifeTime']}s\n")
        elif info['type'] == "vampireDamage":
            output.append(f"  - 用于恢复生命值的伤害转化系数: {info['damageGMHealCoeff'] * 100:.2f}%\n")
        elif info['type'] == "supportBuoy":
            output.append(f"  - 加成区域: {info['battleDropVisualName']}\n"
                          f"    - 区域布置时间: {info['battleDropActTime']}s\n"
                          f"    - 区域持续时间: {info['supportBuoyZoneLifetime']}s\n"
                          f"    - 区域半径: {info['buffZoneRadius']/ 1000:.2f}km\n"
                          f"    - 加成效果:\n"
                          f"      - 效果持续时间: {info['buffDuration']}s\n")
            if info['battleDropName'] == "PCOD071_SupportBuoy_RU":
                gmIdealRadius = info['gmIdealRadius'] - 1
                gmShotDelay = info['gmShotDelay'] - 1
                gsIdealRadius = info['gsIdealRadius'] - 1
                gsShotDelay = info['gsShotDelay'] - 1
                gtShotDelay = info['gtShotDelay'] - 1
                gs_detail = info['gsMaxDistDetail']
                data_type_1 = "+" if gmIdealRadius > 0 else ""
                data_type_2 = "+" if gmShotDelay > 0 else ""
                data_type_3 = "+" if gsIdealRadius > 0 else ""
                data_type_4 = "+" if gsShotDelay > 0 else ""
                data_type_5 = "+" if gtShotDelay > 0 else ""
                output.append(f"      - 鱼雷管装填时间: {data_type_5}{gtShotDelay * 100:.2f}%\n"
                              f"      - 主炮最大散步面积: {data_type_1}{gmIdealRadius * 100:.2f}%\n"
                              f"      - 主炮装填时间: {data_type_2}{gmShotDelay * 100:.2f}%\n"
                              f"      - 副炮最大散步面积: {data_type_3}{gsIdealRadius * 100:.2f}%\n"
                              f"      - 副炮装填时间: {data_type_4}{gsShotDelay * 100:.2f}%\n"
                              f"      - 副炮射程:\n")
                for ship_class, boost_val in gs_detail.items():
                    cn_name = NameMapping.SHIP_CLASS_MAP.get(ship_class, ship_class)
                    boost_pct = boost_val - 1
                    if boost_pct != 0:
                        output.append(f"        * {cn_name}: +{boost_pct * 100:.2f}%\n")

            elif info['battleDropName'] == "PCOD070_SupportBuoy_US":
                sgRudderPower = info['rudderPower'] - 1
                sgRudderTime = info['rudderTime'] - 1
                speedCoeff = info['speedCoef'] - 1
                vulnerabilityAll = info['vulnerability'] - 1
                data_type_1 = "+" if sgRudderPower > 0 else ""
                data_type_2 = "+" if sgRudderTime > 0 else ""
                data_type_3 = "+" if speedCoeff > 0 else ""
                data_type_4 = "+" if vulnerabilityAll > 0 else ""
                data_type_5 = "+" if info['healthRegenPercent'] > 0 else ""
                output.append(f"      - 方向舵换挡时间: {data_type_2}{sgRudderTime * 100:.2f}%\n"
                              f"      - 方向舵效率: {data_type_1}{sgRudderPower * 100:.2f}%\n"
                              f"      - 战舰航速: {data_type_3}{speedCoeff * 100:.2f}%\n"
                              f"      - 受到的全类型伤害: {data_type_4}{vulnerabilityAll * 100}%\n"
                              f"      - 每秒回复血量: {data_type_5}{info['healthRegenPercent'] * 100:.2f}%\n")
        output.append("-" * 30 + "\n")
        return output

    def get_data_by_item_name(self, item_name):
        return self.ability_map.get(item_name)